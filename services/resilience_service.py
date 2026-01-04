"""
韌性計算服務 (Resilience Calculation Service)
Based on: IRS_RESILIENCE_FRAMEWORK.md v1.0

Provides endurance calculation for oxygen, power, and reagents
with dependency chain resolution.
"""

import sqlite3
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum


class StatusLevel(str, Enum):
    """韌性警戒狀態"""
    SAFE = "SAFE"           # Green: >= 120% of isolation target
    WARNING = "WARNING"     # Yellow: 100-120% of isolation target
    CRITICAL = "CRITICAL"   # Red: < 100% of isolation target
    UNKNOWN = "UNKNOWN"     # Gray: Cannot calculate


@dataclass
class EnduranceResult:
    """單項韌性計算結果"""
    item_code: str
    item_name: str
    endurance_type: str
    inventory: Dict[str, Any]
    consumption: Dict[str, Any]
    raw_hours: float
    effective_hours: float
    effective_days: float
    dependency: Optional[Dict[str, Any]]
    status: StatusLevel
    vs_isolation: Dict[str, Any]
    message: str


@dataclass
class ReagentEndurance:
    """試劑韌性計算結果"""
    item_code: str
    item_name: str
    tests_remaining: int
    tests_per_day: float
    days_by_volume: float
    days_by_expiry: Optional[float]
    effective_days: float
    limited_by: str  # 'VOLUME' or 'EXPIRY'
    status: StatusLevel
    alert: Optional[str]


class ResilienceService:
    """
    韌性計算服務

    實作 IRS Resilience Framework 的三大定律:
    1. Law of Capacity: Total Usable = Σ(quantity × capacity_per_unit)
    2. Law of Dependency: Endurance(A) = MIN(Endurance(A), Endurance(Dependency_B))
    3. Law of Weakest Link: Effective Days = MIN(volume_days, expiry_days)
    """

    def __init__(self, db_manager_or_path):
        """
        初始化服務

        Args:
            db_manager_or_path: DatabaseManager instance or db_path string
                For in-memory databases, pass DatabaseManager to share connection
        """
        # Support both DatabaseManager instance and direct path
        if hasattr(db_manager_or_path, 'get_connection'):
            self._db_manager = db_manager_or_path
            self.db_path = None
        else:
            self._db_manager = None
            self.db_path = db_manager_or_path

    def _get_connection(self) -> sqlite3.Connection:
        """取得資料庫連接"""
        if self._db_manager:
            # Use shared connection from DatabaseManager (critical for in-memory mode)
            return self._db_manager.get_connection()
        else:
            # Fallback to direct connection (for file-based databases)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    # =========================================================================
    # Configuration Methods
    # =========================================================================

    def get_config(self, station_id: str) -> Dict[str, Any]:
        """取得站點韌性設定"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM resilience_config WHERE station_id = ?
        """, (station_id,))
        row = cursor.fetchone()

        if not row:
            # Return defaults
            conn.close()
            return {
                'station_id': station_id,
                'isolation_target_days': 3,
                'population_count': 1,
                'population_label': '人數',
                'threshold_safe': 1.2,
                'threshold_warning': 1.0
            }

        result = dict(row)
        conn.close()
        return result

    def update_config(self, station_id: str, config: Dict[str, Any]) -> bool:
        """更新站點韌性設定"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO resilience_config (
                station_id, isolation_target_days, population_count,
                population_label, oxygen_profile_id, power_profile_id,
                reagent_profile_id, threshold_safe, threshold_warning,
                updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            station_id,
            config.get('isolation_target_days', 3),
            config.get('population_count', 1),
            config.get('population_label', '人數'),
            config.get('oxygen_profile_id'),
            config.get('power_profile_id'),
            config.get('reagent_profile_id'),
            config.get('threshold_safe', 1.2),
            config.get('threshold_warning', 1.0),
            datetime.now().isoformat(),
            config.get('updated_by', 'SYSTEM')
        ))

        conn.commit()
        conn.close()
        return True

    # =========================================================================
    # Profile Methods
    # =========================================================================

    def get_profiles(self, endurance_type: str, station_id: str = '*') -> List[Dict[str, Any]]:
        """取得情境設定列表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM resilience_profiles
            WHERE endurance_type = ? AND (station_id = '*' OR station_id = ?)
            ORDER BY sort_order, id
        """, (endurance_type, station_id))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_profile(self, profile_id: int) -> Optional[Dict[str, Any]]:
        """取得單一情境設定"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM resilience_profiles WHERE id = ?", (profile_id,))
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def create_profile(self, profile: Dict[str, Any]) -> int:
        """建立自訂情境設定"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO resilience_profiles (
                station_id, endurance_type, profile_name, profile_name_en,
                burn_rate, burn_rate_unit, population_multiplier,
                description, is_default, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile.get('station_id', '*'),
            profile['endurance_type'],
            profile['profile_name'],
            profile.get('profile_name_en'),
            profile['burn_rate'],
            profile['burn_rate_unit'],
            profile.get('population_multiplier', 0),
            profile.get('description'),
            0,  # Custom profiles are never default
            profile.get('sort_order', 99)
        ))

        profile_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return profile_id

    # =========================================================================
    # Equipment-based Resilience Calculation (v1.2.2)
    # =========================================================================

    # Mapping: equipment_id -> (capacity_per_unit, capacity_unit, item_name, endurance_type)
    # Note: This map is for legacy fuel-based power calculation
    # v1.2.3: Power stations are now calculated via capacity_wh/output_watts fields
    EQUIPMENT_CAPACITY_MAP = {
        # Oxygen equipment
        'RESP-001': (6900, 'liters', 'H型氧氣瓶', 'OXYGEN'),      # H-type cylinder
        'EMER-EQ-006': (680, 'liters', 'E型氧氣瓶', 'OXYGEN'),    # E-type cylinder
        'RESP-002': (None, 'L/min', '氧氣濃縮機', 'OXYGEN'),      # Concentrator (infinite with power)
        # Power equipment (generator fuel)
        'UTIL-002': (50, 'liters', '發電機油箱', 'POWER'),        # Generator tank (50L default)
    }

    def _get_equipment_stock(self, station_id: str, endurance_type: str) -> List[Dict[str, Any]]:
        """
        從設備表取得韌性相關設備數量 (v1.2.6)
        支援 PER_UNIT 追蹤模式，回傳個別單位狀態
        v1.4.5: 修正 PostgreSQL cursor 重用問題
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get equipment with tracking mode
        cursor.execute("""
            SELECT id, name, quantity, power_level, tracking_mode
            FROM equipment
        """)
        # v1.4.5: 先將結果存入 list，避免 PostgreSQL cursor 重用問題
        all_equipment = list(cursor.fetchall())

        # v1.4.5: 一次取得所有 equipment_units
        # v2.0: 排除轉送中和已被案例佔用的單位
        try:
            cursor.execute("""
                SELECT equipment_id, unit_label, level_percent, status, last_check
                FROM equipment_units
                WHERE (claimed_by_mission_id IS NULL OR claimed_by_mission_id = '')
                  AND (claimed_by_case_id IS NULL OR claimed_by_case_id = '')
                ORDER BY equipment_id, unit_label
            """)
        except Exception:
            # Fallback: columns may not exist in older DBs
            cursor.execute("""
                SELECT equipment_id, unit_label, level_percent, status, last_check
                FROM equipment_units
                ORDER BY equipment_id, unit_label
            """)
        all_units = list(cursor.fetchall())

        # 建立 units lookup map
        units_by_equipment = {}
        for u in all_units:
            eq_id = u['equipment_id']
            if eq_id not in units_by_equipment:
                units_by_equipment[eq_id] = []
            units_by_equipment[eq_id].append(u)

        results = []
        for row in all_equipment:
            eq_id = row['id']
            if eq_id in self.EQUIPMENT_CAPACITY_MAP:
                capacity, unit, name, eq_type = self.EQUIPMENT_CAPACITY_MAP[eq_id]
                if eq_type == endurance_type:
                    tracking_mode = row['tracking_mode'] or 'AGGREGATE'

                    if tracking_mode == 'PER_UNIT' and capacity:
                        # v1.4.5: 從預先載入的 units 取得
                        units = units_by_equipment.get(eq_id, [])

                        if units:
                            # 計算總有效容量 (每單位容量 × 充填%)
                            total_effective = sum(
                                capacity * (u['level_percent'] / 100.0)
                                for u in units
                            )
                            avg_level = sum(u['level_percent'] for u in units) / len(units)
                            checked_count = sum(1 for u in units if u['last_check'])

                            results.append({
                                'item_code': eq_id,
                                'item_name': row['name'] or name,
                                'endurance_type': eq_type,
                                'capacity_per_unit': capacity,
                                'capacity_unit': unit,
                                'stock': len(units),
                                'depends_on_item_code': None,
                                'power_level': round(avg_level, 1),
                                'tracking_mode': 'PER_UNIT',
                                'units': [
                                    {
                                        'label': u['unit_label'],
                                        'level': u['level_percent'],
                                        'status': u['status'],
                                        'capacity': round(capacity * u['level_percent'] / 100.0, 0),
                                        'checked': u['last_check'] is not None,
                                        'last_check': u['last_check']
                                    } for u in units
                                ],
                                'total_effective_capacity': round(total_effective, 0),
                                'checked_count': checked_count
                            })
                            continue

                    # AGGREGATE mode (default)
                    qty = row['quantity'] or 1
                    level = row['power_level']
                    if level is not None and capacity:
                        effective_capacity = capacity * (level / 100.0)
                    else:
                        effective_capacity = capacity

                    results.append({
                        'item_code': eq_id,
                        'item_name': row['name'] or name,
                        'endurance_type': eq_type,
                        'capacity_per_unit': effective_capacity,
                        'capacity_unit': unit,
                        'stock': qty,
                        'depends_on_item_code': 'GEN-FUEL-20L' if capacity is None else None,
                        'power_level': level,
                        'tracking_mode': 'AGGREGATE'
                    })

        conn.close()
        return results

    # =========================================================================
    # Inventory Calculation Methods
    # =========================================================================

    def _get_stock_by_type(self, station_id: str, endurance_type: str) -> List[Dict[str, Any]]:
        """取得特定類型的庫存項目及數量"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Sum inventory events for each item
        cursor.execute("""
            SELECT
                i.item_code,
                i.item_name,
                i.endurance_type,
                i.capacity_per_unit,
                i.capacity_unit,
                i.tests_per_unit,
                i.valid_days_after_open,
                i.depends_on_item_code,
                i.dependency_note,
                COALESCE(SUM(
                    CASE
                        WHEN e.event_type = 'RECEIVE' THEN e.quantity
                        ELSE -e.quantity
                    END
                ), 0) as stock
            FROM items i
            LEFT JOIN inventory_events e ON i.item_code = e.item_code AND e.station_id = ?
            WHERE i.endurance_type = ?
            GROUP BY i.item_code
            HAVING stock > 0 OR i.depends_on_item_code IS NOT NULL
        """, (station_id, endurance_type))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def _calculate_total_capacity(self, items: List[Dict[str, Any]]) -> float:
        """計算總容量 (Law of Capacity)"""
        total = 0.0
        for item in items:
            if item.get('capacity_per_unit') and item.get('stock'):
                total += item['capacity_per_unit'] * item['stock']
        return total

    def _calculate_hours(
        self,
        total_capacity: float,
        burn_rate: float,
        burn_rate_unit: str
    ) -> float:
        """計算可用時數"""
        if burn_rate <= 0:
            return float('inf')

        if burn_rate_unit == 'L/min':
            # Convert L/min to hours: capacity / (rate * 60)
            return total_capacity / (burn_rate * 60)
        elif burn_rate_unit == 'L/hr':
            return total_capacity / burn_rate
        elif burn_rate_unit == 'tests/day':
            # Convert to hours
            return (total_capacity / burn_rate) * 24
        else:
            # Assume hourly rate
            return total_capacity / burn_rate

    def _determine_status(
        self,
        hours_remaining: float,
        isolation_hours: float,
        threshold_safe: float = 1.2,
        threshold_warning: float = 1.0
    ) -> StatusLevel:
        """判斷警戒狀態"""
        if isolation_hours <= 0:
            return StatusLevel.UNKNOWN

        if hours_remaining == float('inf'):
            return StatusLevel.SAFE

        ratio = hours_remaining / isolation_hours

        if ratio >= threshold_safe:
            return StatusLevel.SAFE
        elif ratio >= threshold_warning:
            return StatusLevel.WARNING
        else:
            return StatusLevel.CRITICAL

    # =========================================================================
    # Main Calculation Method
    # =========================================================================

    def calculate_resilience_status(self, station_id: str) -> Dict[str, Any]:
        """
        計算站點完整韌性狀態

        Returns:
            完整韌性狀態 JSON (符合 IRS Framework API Response Format)
        """
        # Get configuration
        config = self.get_config(station_id)
        isolation_days = config.get('isolation_target_days', 3)
        isolation_hours = isolation_days * 24
        population = config.get('population_count', 1)

        # Get active profiles
        oxygen_profile = self.get_profile(config.get('oxygen_profile_id')) or \
                        self._get_default_profile('OXYGEN')
        power_profile = self.get_profile(config.get('power_profile_id')) or \
                       self._get_default_profile('POWER')
        reagent_profile = self.get_profile(config.get('reagent_profile_id')) or \
                         self._get_default_profile('REAGENT')

        # Calculate lifelines
        lifelines = []
        endurance_map = {}  # For dependency resolution

        # 1. Calculate Power (must be first for dependency)
        power_result = self._calculate_power_endurance(
            station_id, power_profile, isolation_hours, config
        )
        if power_result:
            lifelines.append(power_result)
            endurance_map['POWER'] = power_result['endurance']['effective_hours']

        # 2. Calculate Oxygen (may depend on power)
        oxygen_results = self._calculate_oxygen_endurance(
            station_id, oxygen_profile, isolation_hours, config, endurance_map
        )
        lifelines.extend(oxygen_results)

        # 3. Calculate Reagents
        reagents = self._calculate_reagent_endurance(
            station_id, reagent_profile, isolation_days, config
        )

        # Determine overall status
        all_statuses = [l['status'] for l in lifelines] + [r['status'] for r in reagents]
        if StatusLevel.CRITICAL.value in all_statuses:
            overall_status = StatusLevel.CRITICAL.value
        elif StatusLevel.WARNING.value in all_statuses:
            overall_status = StatusLevel.WARNING.value
        elif StatusLevel.UNKNOWN.value in all_statuses:
            overall_status = StatusLevel.UNKNOWN.value
        else:
            overall_status = StatusLevel.SAFE.value

        # Find weakest link
        # v1.4.6: Skip lifelines that are limited by dependencies (avoid double-counting)
        #         e.g., O2 concentrator limited by power is already reflected in power lifeline
        weakest = None
        min_hours = float('inf')

        # v2.5.3: 分別計算電力和氧氣的最佳時數
        # 氧氣供應取各來源的最大值（濃縮機有電時可用，鋼瓶作為備用）
        power_hours = 0
        oxygen_max_hours = 0

        for l in lifelines:
            eff_hours = l['endurance']['effective_hours']
            # Handle string '∞' or actual infinity
            if isinstance(eff_hours, str):
                eff_hours = float('inf')

            if l['type'] == 'POWER':
                power_hours = eff_hours if eff_hours != float('inf') else power_hours
            elif l['type'] == 'OXYGEN':
                # 氧氣取各來源的最大值（濃縮機有電時可持續供氧）
                if eff_hours != float('inf') and eff_hours > oxygen_max_hours:
                    oxygen_max_hours = eff_hours

        # Weakest link 在電力和氧氣之間選擇
        effective_lifelines = []
        if power_hours > 0:
            effective_lifelines.append({'type': 'POWER', 'hours': power_hours, 'item': '電力供應'})
        if oxygen_max_hours > 0:
            effective_lifelines.append({'type': 'OXYGEN', 'hours': oxygen_max_hours, 'item': '氧氣供應'})

        for eff in effective_lifelines:
            if eff['hours'] < min_hours:
                min_hours = eff['hours']
                weakest = eff

        # v1.4.4: Extract oxygen supplies with unit details for frontend
        oxygen_items = []
        for result in oxygen_results:
            # Check inventory.items for PER_UNIT tracking details
            inv_items = result.get('inventory', {}).get('items', [])
            for inv_item in inv_items:
                if inv_item.get('tracking_mode') == 'PER_UNIT' and inv_item.get('units'):
                    oxygen_items.append({
                        'item_code': inv_item.get('item_code', 'O2'),  # 使用設備代碼
                        'item_name': inv_item.get('name', '氧氣瓶'),
                        'endurance_type': 'OXYGEN',
                        'capacity_per_unit': inv_item.get('capacity_each'),
                        'capacity_unit': inv_item.get('unit', 'L'),
                        'stock': inv_item.get('qty', 0),
                        'power_level': inv_item.get('avg_level', 0),
                        'tracking_mode': 'PER_UNIT',
                        'units': inv_item['units'],
                        'total_effective_capacity': inv_item.get('effective_total', 0),
                        'checked_count': inv_item.get('checked_count', 0)
                    })

        # Build response
        return {
            'system': 'MIRS',
            'version': '1.0',
            'station_id': station_id,
            'calculated_at': datetime.now().isoformat(),
            'context': {
                'isolation_target_days': isolation_days,
                'isolation_target_hours': isolation_hours,
                'isolation_source': config.get('isolation_source', 'manual'),
                'population': {
                    'count': population,
                    'label': config.get('population_label', '人數')
                }
            },
            'lifelines': lifelines,
            'reagents': reagents,
            # v1.4.4: Add oxygen_supplies for frontend compatibility
            'oxygen_supplies': {
                'items': oxygen_items
            },
            'summary': {
                'overall_status': overall_status,
                'weakest_link': weakest,
                'can_survive_isolation': overall_status != StatusLevel.CRITICAL.value,
                'critical_items': [l['item_code'] for l in lifelines if l['status'] == StatusLevel.CRITICAL.value],
                'warning_items': [l['item_code'] for l in lifelines if l['status'] == StatusLevel.WARNING.value],
                # v2.5.3: 獨立運作時數（電力/氧氣各取最佳來源）
                'power_hours': round(power_hours, 1) if power_hours > 0 else None,
                'oxygen_hours': round(oxygen_max_hours, 1) if oxygen_max_hours > 0 else None
            }
        }

    def _get_default_profile(self, endurance_type: str) -> Dict[str, Any]:
        """取得預設情境設定"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM resilience_profiles
            WHERE endurance_type = ? AND is_default = 1
            LIMIT 1
        """, (endurance_type,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)

        # Hardcoded fallbacks
        defaults = {
            'OXYGEN': {'burn_rate': 10, 'burn_rate_unit': 'L/min', 'profile_name': '1位插管患者', 'population_multiplier': 1},
            'POWER': {'burn_rate': 3.0, 'burn_rate_unit': 'L/hr', 'profile_name': '標準運作', 'population_multiplier': 0},
            'REAGENT': {'burn_rate': 5, 'burn_rate_unit': 'tests/day', 'profile_name': '平時', 'population_multiplier': 0}
        }
        return defaults.get(endurance_type, {})

    def _calculate_power_endurance(
        self,
        station_id: str,
        profile: Dict[str, Any],
        isolation_hours: float,
        config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        計算電力韌性 - v1.4.7: 支援 PER_UNIT 追蹤模式

        計算邏輯：
        1. 總負載 = Σ(設備.power_watts) 從所有耗電設備
        2. 電源站時數 = capacity_wh × (power_level/100) ÷ 總負載
        3. 發電機時數 = 油量 ÷ fuel_rate_lph
        4. 總時數 = 電源站時數 + 發電機時數 (依序使用)

        v1.4.7: 支援 PER_UNIT 追蹤，個別追蹤每台電源站/發電機電量
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # 1. 計算總負載 (所有有 power_watts 的設備，考慮數量)
        cursor.execute("""
            SELECT id, name, power_watts, COALESCE(quantity, 1) as qty
            FROM equipment
            WHERE power_watts IS NOT NULL AND power_watts > 0
        """)
        consuming_equipment = cursor.fetchall()
        total_load_watts = sum(row['power_watts'] * row['qty'] for row in consuming_equipment)

        # 如果沒有耗電設備，使用預設負載
        if total_load_watts == 0:
            total_load_watts = profile.get('burn_rate', 900)  # 預設 900W

        # 2. 取得電源站 (有 capacity_wh 的設備)
        cursor.execute("""
            SELECT id, name, capacity_wh, output_watts, power_level,
                   COALESCE(quantity, 1) as qty, tracking_mode
            FROM equipment
            WHERE capacity_wh IS NOT NULL AND capacity_wh > 0
        """)
        power_stations = cursor.fetchall()

        # 3. 取得發電機 (有 fuel_rate_lph 的設備)
        cursor.execute("""
            SELECT id, name, output_watts, fuel_rate_lph, power_level,
                   COALESCE(quantity, 1) as qty, tracking_mode
            FROM equipment
            WHERE fuel_rate_lph IS NOT NULL AND fuel_rate_lph > 0
        """)
        generators = cursor.fetchall()

        # 4. 取得備用油料 (FUEL_RESERVE 類型設備)
        cursor.execute("""
            SELECT SUM(quantity * 20) as total_fuel
            FROM equipment
            WHERE device_type = 'FUEL_RESERVE'
               OR name LIKE '%備用油%'
               OR name LIKE '%油桶%'
        """)
        fuel_row = cursor.fetchone()
        extra_fuel = fuel_row['total_fuel'] if fuel_row and fuel_row['total_fuel'] else 0

        # 5. 取得所有電力設備的 equipment_units (PER_UNIT 用)
        # v2.0: 排除轉送中和已被案例佔用的單位
        power_eq_ids = [ps['id'] for ps in power_stations] + [g['id'] for g in generators]
        units_by_equipment = {}
        if power_eq_ids:
            placeholders = ','.join(['?' for _ in power_eq_ids])
            try:
                cursor.execute(f"""
                    SELECT equipment_id, unit_serial, unit_label, level_percent, status, last_check
                    FROM equipment_units
                    WHERE equipment_id IN ({placeholders})
                      AND (claimed_by_mission_id IS NULL OR claimed_by_mission_id = '')
                      AND (claimed_by_case_id IS NULL OR claimed_by_case_id = '')
                    ORDER BY equipment_id, unit_serial
                """, power_eq_ids)
            except Exception:
                # Fallback: columns may not exist in older DBs
                cursor.execute(f"""
                    SELECT equipment_id, unit_serial, unit_label, level_percent, status, last_check
                    FROM equipment_units
                    WHERE equipment_id IN ({placeholders})
                    ORDER BY equipment_id, unit_serial
                """, power_eq_ids)
            for row in cursor.fetchall():
                eq_id = row['equipment_id']
                if eq_id not in units_by_equipment:
                    units_by_equipment[eq_id] = []
                units_by_equipment[eq_id].append({
                    'serial': row['unit_serial'],
                    'label': row['unit_label'],
                    'level': row['level_percent'] or 0,
                    'status': row['status'] or 'AVAILABLE',
                    'last_check': row['last_check']
                })

        conn.close()

        # 計算各電源可用時數
        sources = []
        power_items = []  # v1.4.7: 詳細電力設備清單
        total_battery_wh = 0
        total_fuel_liters = extra_fuel
        charging_warnings = []  # 充電中提醒

        # 電源站計算 (支援 PER_UNIT)
        for ps in power_stations:
            capacity_per_unit = ps['capacity_wh']
            qty = ps['qty']
            tracking_mode = ps['tracking_mode'] or 'AGGREGATE'
            eq_id = ps['id']

            if tracking_mode == 'PER_UNIT' and eq_id in units_by_equipment:
                # PER_UNIT 模式：計算個別單位
                units = units_by_equipment[eq_id]
                unit_details = []
                ps_available_wh = 0
                charging_count = 0

                for unit in units:
                    level = unit['level']
                    status = unit['status']
                    unit_wh = capacity_per_unit * (level / 100.0)

                    # CHARGING 狀態：計入容量但標記提醒
                    if status == 'CHARGING':
                        charging_count += 1
                        ps_available_wh += unit_wh
                    # AVAILABLE, IN_USE: 正常計入
                    elif status in ('AVAILABLE', 'IN_USE'):
                        ps_available_wh += unit_wh
                    # MAINTENANCE, OFFLINE: 不計入

                    unit_details.append({
                        'label': unit['label'],
                        'level': level,
                        'status': status,
                        'capacity': round(unit_wh, 1),
                        'last_check': unit['last_check']
                    })

                total_battery_wh += ps_available_wh
                hours = ps_available_wh / total_load_watts if total_load_watts > 0 else 0
                avg_level = sum(u['level'] for u in unit_details) / len(unit_details) if unit_details else 0

                if charging_count > 0:
                    charging_warnings.append(f"{ps['name']} 有 {charging_count} 台充電中，請於充電完成後更新設備狀態")

                sources.append({
                    'name': f"{ps['name']} ({avg_level:.0f}%)",
                    'capacity': f"{capacity_per_unit * len(unit_details):.1f} Wh",
                    'available': f"{ps_available_wh:.1f} Wh",
                    'hours': round(hours, 1)
                })

                power_items.append({
                    'item_code': eq_id,
                    'name': ps['name'],
                    'device_type': 'POWER_STATION',
                    'qty': len(unit_details),
                    'capacity_each': capacity_per_unit,
                    'avg_level': round(avg_level, 1),
                    'effective_total': round(ps_available_wh, 1),
                    'unit': 'Wh',
                    'tracking_mode': 'PER_UNIT',
                    'units': unit_details
                })
            else:
                # AGGREGATE 模式：原有邏輯
                level = ps['power_level'] if ps['power_level'] is not None else 100
                total_capacity = capacity_per_unit * qty
                available_wh = total_capacity * (level / 100.0)
                hours = available_wh / total_load_watts if total_load_watts > 0 else 0
                total_battery_wh += available_wh

                qty_label = f" ×{qty}" if qty > 1 else ""
                sources.append({
                    'name': f"{ps['name']}{qty_label} ({level}%)",
                    'capacity': f"{total_capacity:.1f} Wh",
                    'available': f"{available_wh:.1f} Wh",
                    'hours': round(hours, 1)
                })

                power_items.append({
                    'item_code': eq_id,
                    'name': ps['name'],
                    'device_type': 'POWER_STATION',
                    'qty': qty,
                    'capacity_each': capacity_per_unit,
                    'avg_level': level,
                    'effective_total': round(available_wh, 1),
                    'unit': 'Wh',
                    'tracking_mode': 'AGGREGATE'
                })

        # 發電機計算 (支援 PER_UNIT)
        for gen in generators:
            fuel_rate = gen['fuel_rate_lph']
            qty = gen['qty']
            tracking_mode = gen['tracking_mode'] or 'AGGREGATE'
            eq_id = gen['id']
            tank_capacity = 50  # 預設 50L 油箱

            if tracking_mode == 'PER_UNIT' and eq_id in units_by_equipment:
                # PER_UNIT 模式
                units = units_by_equipment[eq_id]
                unit_details = []
                gen_total_fuel = 0

                for unit in units:
                    level = unit['level']
                    status = unit['status']
                    unit_fuel = tank_capacity * (level / 100.0)

                    if status in ('AVAILABLE', 'IN_USE', 'CHARGING'):
                        gen_total_fuel += unit_fuel

                    unit_details.append({
                        'label': unit['label'],
                        'level': level,
                        'status': status,
                        'capacity': round(unit_fuel, 1),
                        'last_check': unit['last_check']
                    })

                total_fuel_liters += gen_total_fuel
                gen_hours = (gen_total_fuel + extra_fuel) / fuel_rate if fuel_rate > 0 else 0
                avg_level = sum(u['level'] for u in unit_details) / len(unit_details) if unit_details else 0

                sources.append({
                    'name': f"{gen['name']} (燃油 {gen_total_fuel + extra_fuel:.1f}L)",
                    'capacity': f"{gen['output_watts']}W, {fuel_rate}L/hr",
                    'available': f"{gen_hours:.1f} hr 運轉",
                    'hours': round(gen_hours, 1)
                })

                power_items.append({
                    'item_code': eq_id,
                    'name': gen['name'],
                    'device_type': 'GENERATOR',
                    'qty': len(unit_details),
                    'capacity_each': tank_capacity,
                    'avg_level': round(avg_level, 1),
                    'effective_total': round(gen_total_fuel, 1),
                    'unit': 'L',
                    'tracking_mode': 'PER_UNIT',
                    'units': unit_details,
                    'fuel_rate_lph': fuel_rate
                })
            else:
                # AGGREGATE 模式
                level = gen['power_level'] if gen['power_level'] is not None else 100
                tank_fuel = tank_capacity * qty * (level / 100.0)
                total_fuel_liters += tank_fuel
                gen_hours = (tank_fuel + extra_fuel) / fuel_rate if fuel_rate > 0 else 0

                qty_label = f" ×{qty}" if qty > 1 else ""
                sources.append({
                    'name': f"{gen['name']}{qty_label} (燃油 {tank_fuel + extra_fuel:.1f}L)",
                    'capacity': f"{gen['output_watts']}W, {fuel_rate}L/hr",
                    'available': f"{gen_hours:.1f} hr 運轉",
                    'hours': round(gen_hours, 1)
                })

                power_items.append({
                    'item_code': eq_id,
                    'name': gen['name'],
                    'device_type': 'GENERATOR',
                    'qty': qty,
                    'capacity_each': tank_capacity,
                    'avg_level': level,
                    'effective_total': round(tank_fuel, 1),
                    'unit': 'L',
                    'tracking_mode': 'AGGREGATE',
                    'fuel_rate_lph': fuel_rate
                })

        # 總時數 = 電池時數 + 發電機時數
        battery_hours = total_battery_wh / total_load_watts if total_load_watts > 0 else 0

        # 發電機時數 (使用第一台發電機的油耗率)
        gen_fuel_rate = generators[0]['fuel_rate_lph'] if generators else 1.5
        generator_hours = total_fuel_liters / gen_fuel_rate if gen_fuel_rate > 0 else 0

        total_hours = battery_hours + generator_hours

        status = self._determine_status(
            total_hours, isolation_hours,
            config.get('threshold_safe', 1.2),
            config.get('threshold_warning', 1.0)
        )

        ratio = total_hours / isolation_hours if isolation_hours > 0 else 0
        can_survive = ratio >= 1.0
        gap = max(0, isolation_hours - total_hours)

        # v1.4.7: 組合充電提醒訊息
        base_message = self._generate_message('POWER', total_hours, isolation_hours, status)
        if charging_warnings:
            charging_note = " | 🔌 " + "; ".join(charging_warnings)
            full_message = base_message + charging_note
        else:
            full_message = base_message

        return {
            'item_code': 'POWER-TOTAL',
            'name': '電力供應',
            'type': 'POWER',
            'inventory': {
                'sources': sources,
                'items': power_items,  # v1.4.7: 詳細電力設備清單 (類似氧氣鋼瓶)
                'total_battery_wh': round(total_battery_wh, 1),
                'total_fuel_liters': round(total_fuel_liters, 1),
                'capacity_unit': 'Wh'
            },
            'consumption': {
                'profile_name': profile.get('profile_name', '標準運作'),
                'load_watts': total_load_watts,
                'load_display': f"{total_load_watts} W",
                'equipment_count': len(consuming_equipment),
                'equipment_list': [eq['name'] for eq in consuming_equipment[:5]]  # 前5項
            },
            'endurance': {
                'battery_hours': round(battery_hours, 1),
                'generator_hours': round(generator_hours, 1),
                'raw_hours': round(total_hours, 1),
                'effective_hours': round(total_hours, 1),
                'effective_days': round(total_hours / 24, 1)
            },
            'dependency': None,
            'status': status.value,
            'vs_isolation': {
                'ratio': round(ratio, 2),
                'can_survive': can_survive,
                'gap_hours': round(gap, 1) if not can_survive else 0,
                'gap_display': f"缺口 {gap:.1f} 小時" if not can_survive else None
            },
            'charging_warnings': charging_warnings if charging_warnings else None,  # v1.4.7
            'message': full_message
        }

    def _calculate_oxygen_endurance(
        self,
        station_id: str,
        profile: Dict[str, Any],
        isolation_hours: float,
        config: Dict[str, Any],
        endurance_map: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """計算氧氣韌性 (含依賴解析) - v1.2.2: 使用設備表數量"""
        # v1.2.2: 優先使用設備表數量，備用庫存表
        items = self._get_equipment_stock(station_id, 'OXYGEN')
        if not items:
            # Fallback to inventory
            items = self._get_stock_by_type(station_id, 'OXYGEN')
        if not items:
            return []

        results = []
        burn_rate = profile.get('burn_rate', 10)  # L/min

        # v1.4.5: Apply population multiplier (e.g., 2 ventilated patients = 2x oxygen)
        population = config.get('population_count', 1)
        if profile.get('population_multiplier', 0):
            # 人數直接乘上消耗率（可為小數，如 0.5 位插管患者）
            if population <= 0:
                burn_rate = 0  # No oxygen demand
            else:
                burn_rate = burn_rate * population

        # Separate cylinders and concentrators
        cylinders = [i for i in items if i.get('capacity_per_unit')]
        concentrators = [i for i in items if not i.get('capacity_per_unit')]

        # Calculate cylinder endurance (v1.2.6: 支援 PER_UNIT 追蹤)
        if cylinders:
            # 計算總有效容量
            total_liters = 0
            inventory_items = []

            for c in cylinders:
                if c.get('tracking_mode') == 'PER_UNIT' and c.get('total_effective_capacity'):
                    # 使用個別追蹤的實際容量
                    total_liters += c['total_effective_capacity']
                    inventory_items.append({
                        'item_code': c.get('item_code'),  # v1.4.4: 保留設備代碼
                        'name': c['item_name'],
                        'qty': c['stock'],
                        'capacity_each': c['capacity_per_unit'],
                        'avg_level': c.get('power_level'),
                        'effective_total': c['total_effective_capacity'],
                        'unit': 'liters',
                        'tracking_mode': 'PER_UNIT',
                        'units': c.get('units', []),  # 個別單位詳情
                        'checked_count': c.get('checked_count', 0)  # v1.4.4
                    })
                else:
                    # AGGREGATE 模式
                    effective = c['capacity_per_unit'] * c['stock']
                    total_liters += effective
                    inventory_items.append({
                        'item_code': c.get('item_code'),  # v1.4.4
                        'name': c['item_name'],
                        'qty': c['stock'],
                        'capacity_each': c['capacity_per_unit'],
                        'unit': 'liters',
                        'tracking_mode': 'AGGREGATE'
                    })

            hours = self._calculate_hours(total_liters, burn_rate, 'L/min')

            status = self._determine_status(
                hours, isolation_hours,
                config.get('threshold_safe', 1.2),
                config.get('threshold_warning', 1.0)
            )

            ratio = hours / isolation_hours if isolation_hours > 0 else 0
            can_survive = ratio >= 1.0
            gap = max(0, isolation_hours - hours)

            results.append({
                'item_code': 'O2-SUPPLY',
                'name': '氧氣供應(鋼瓶)',
                'type': 'OXYGEN',
                'inventory': {
                    'items': inventory_items,
                    'total_capacity': round(total_liters, 0),
                    'capacity_unit': 'liters'
                },
                'consumption': {
                    'profile_name': profile.get('profile_name', '1位插管患者'),
                    'burn_rate': burn_rate,
                    'burn_rate_unit': 'L/min',
                    'burn_rate_display': f"{burn_rate} L/min"
                },
                'endurance': {
                    'raw_hours': round(hours, 1),
                    'effective_hours': round(hours, 1),
                    'effective_days': round(hours / 24, 2)
                },
                'dependency': None,
                'status': status.value,
                'vs_isolation': {
                    'ratio': round(ratio, 2),
                    'can_survive': can_survive,
                    'gap_hours': round(gap, 1) if not can_survive else 0,
                    'gap_display': f"缺口 {gap:.1f} 小時" if not can_survive else None
                },
                'message': self._generate_message('OXYGEN', hours, isolation_hours, status)
            })

        # Calculate concentrator endurance (with dependency)
        for conc in concentrators:
            raw_hours = float('inf')  # Infinite as long as power available
            effective_hours = raw_hours

            dependency = None
            if conc.get('depends_on_item_code'):
                power_hours = endurance_map.get('POWER', float('inf'))
                if power_hours < raw_hours:
                    effective_hours = power_hours
                    dependency = {
                        'depends_on': conc['depends_on_item_code'],
                        'dependency_name': '發電機電力',
                        'is_limiting': True,
                        'warning': f"⚠️ 受限於發電機電力：當油料耗盡時，{conc['item_name']} 將停止運作"
                    }

            status = self._determine_status(
                effective_hours, isolation_hours,
                config.get('threshold_safe', 1.2),
                config.get('threshold_warning', 1.0)
            )

            ratio = effective_hours / isolation_hours if isolation_hours > 0 else 0

            results.append({
                'item_code': conc['item_code'],
                'name': conc['item_name'],
                'type': 'OXYGEN',
                'inventory': {
                    'items': [{
                        'name': conc['item_name'],
                        'qty': conc['stock'],
                        'capacity_each': None,  # 製造機持續供氧，無固定容量
                        'unit': 'device'
                    }],
                    'total_capacity': None,
                    'note': '持續供氧 (需電力)'
                },
                'consumption': {
                    'profile_name': '持續供氧',
                    'burn_rate': 5 if '5L' in conc['item_name'] else 10,
                    'burn_rate_unit': 'L/min',
                    'burn_rate_display': f"持續供氧"
                },
                'endurance': {
                    'raw_hours': '∞' if raw_hours == float('inf') else round(raw_hours, 1),
                    'effective_hours': round(effective_hours, 1) if effective_hours != float('inf') else '∞',
                    'effective_days': round(effective_hours / 24, 1) if effective_hours != float('inf') else '∞'
                },
                'dependency': dependency,
                'status': status.value,
                'vs_isolation': {
                    'ratio': round(ratio, 2) if ratio != float('inf') else '∞',
                    'can_survive': ratio >= 1.0 if ratio != float('inf') else True
                },
                'message': f"製造機本身無限供氧，但受限於發電機（{effective_hours:.0f}小時）" if dependency else "製造機供氧正常"
            })

        return results

    def _calculate_reagent_endurance(
        self,
        station_id: str,
        profile: Dict[str, Any],
        isolation_days: float,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """計算試劑韌性 (含開封效期邏輯)"""
        items = self._get_stock_by_type(station_id, 'REAGENT')
        if not items:
            return []

        tests_per_day = profile.get('burn_rate', 5)
        results = []

        for item in items:
            stock = item.get('stock', 0)
            tests_per_unit = item.get('tests_per_unit', 1)
            valid_days = item.get('valid_days_after_open')

            total_tests = stock * tests_per_unit
            days_by_volume = total_tests / tests_per_day if tests_per_day > 0 else float('inf')

            # Check for open records
            days_by_expiry = None
            limited_by = 'VOLUME'
            alert = None

            if valid_days:
                open_record = self._get_open_reagent(station_id, item['item_code'])
                if open_record:
                    days_since_open = (datetime.now() - datetime.fromisoformat(open_record['opened_at'])).days
                    days_by_expiry = max(0, valid_days - days_since_open)

                    if days_by_expiry < days_by_volume:
                        limited_by = 'EXPIRY'
                        alert = f"⚠️ 效期限制：試劑將於 {days_by_expiry} 天後失效（開封已 {days_since_open} 天）"

            effective_days = min(days_by_volume, days_by_expiry) if days_by_expiry else days_by_volume

            status = self._determine_status(
                effective_days * 24,  # Convert to hours
                isolation_days * 24,
                config.get('threshold_safe', 1.2),
                config.get('threshold_warning', 1.0)
            )

            results.append({
                'item_code': item['item_code'],
                'name': item['item_name'],
                'inventory': {
                    'kits_remaining': stock,
                    'tests_per_kit': tests_per_unit,
                    'tests_remaining': total_tests
                },
                'consumption': {
                    'profile_name': profile.get('profile_name', '平時'),
                    'tests_per_day': tests_per_day
                },
                'endurance': {
                    'days_by_volume': round(days_by_volume, 1),
                    'days_by_expiry': round(days_by_expiry, 1) if days_by_expiry else None,
                    'effective_days': round(effective_days, 1),
                    'limited_by': limited_by
                },
                'status': status.value,
                'alert': alert
            })

        return results

    def _get_open_reagent(self, station_id: str, item_code: str) -> Optional[Dict[str, Any]]:
        """取得開封中的試劑記錄"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM reagent_open_records
            WHERE station_id = ? AND item_code = ? AND is_active = 1
            ORDER BY opened_at DESC LIMIT 1
        """, (station_id, item_code))

        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def mark_reagent_opened(
        self,
        station_id: str,
        item_code: str,
        batch_number: str = None,
        tests_remaining: int = None,
        opened_by: str = 'SYSTEM'
    ) -> int:
        """標記試劑已開封"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Deactivate previous open records
        cursor.execute("""
            UPDATE reagent_open_records
            SET is_active = 0
            WHERE station_id = ? AND item_code = ? AND is_active = 1
        """, (station_id, item_code))

        # Create new open record
        cursor.execute("""
            INSERT INTO reagent_open_records (
                item_code, batch_number, station_id, opened_at,
                tests_remaining, is_active, created_by
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (item_code, batch_number, station_id, datetime.now().isoformat(),
              tests_remaining, opened_by))

        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return record_id

    def _generate_message(
        self,
        endurance_type: str,
        hours: float,
        isolation_hours: float,
        status: StatusLevel
    ) -> str:
        """生成狀態訊息"""
        type_names = {
            'OXYGEN': '氧氣',
            'POWER': '電力',
            'REAGENT': '試劑'
        }
        name = type_names.get(endurance_type, '物資')

        if hours == float('inf'):
            return f"{name}供應充足"

        days = hours / 24
        isolation_days = isolation_hours / 24

        if status == StatusLevel.CRITICAL:
            gap = isolation_hours - hours
            return f"{name}僅剩 {hours:.1f} 小時，無法撐過 {isolation_days:.0f} 天斷航期（缺口 {gap:.1f} 小時）"
        elif status == StatusLevel.WARNING:
            return f"{name}可撐 {hours:.1f} 小時 ({days:.1f}天)，建議補充"
        else:
            return f"{name}充足，可撐 {hours:.1f} 小時 ({days:.1f}天)"


# Export
__all__ = ['ResilienceService', 'StatusLevel', 'EnduranceResult', 'ReagentEndurance']
