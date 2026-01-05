"""
MIRS EMT Transfer Module API
Version: 2.0.0

病患轉送任務管理：
- 物資計算 (1-15× 安全係數)
- PSI 單瓶追蹤
- 設備電量追蹤
- 三分離計量 (攜帶/歸還/消耗)
- 離線優先架構
- 庫存連動 (Reserve/Issue/Return)
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import uuid
import math
import json
import logging
import os

logger = logging.getLogger(__name__)

# Vercel demo mode detection
IS_VERCEL = os.environ.get("VERCEL") == "1"

# Demo data for Vercel mode
# Note: All missions start as COMPLETED so the initial screen shows "Create Mission"
# When user creates a mission, TRF-DEMO-NEW is used for the flow
DEMO_MISSIONS = [
    {
        "mission_id": "TRF-DEMO-001",
        "status": "COMPLETED",  # Changed to COMPLETED so it doesn't auto-load
        "origin_station": "MIRS-DEMO",
        "destination": "第二野戰醫院",
        "estimated_duration_min": 90,
        "patient_condition": "STABLE",
        "patient_summary": "右脛骨開放性骨折，已固定",
        "oxygen_requirement_lpm": 6.0,
        "iv_rate_mlhr": 100.0,
        "ventilator_required": 0,
        "safety_factor": 3.0,
        "emt_name": "王大明",
        "departed_at": (datetime.now() - timedelta(hours=2)).isoformat(),
        "arrived_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        "finalized_at": (datetime.now() - timedelta(minutes=30)).isoformat(),
        "created_at": (datetime.now() - timedelta(hours=3)).isoformat()
    },
    {
        "mission_id": "TRF-DEMO-NEW",
        "status": "PLANNING",
        "origin_station": "MIRS-DEMO",
        "destination": "",
        "estimated_duration_min": 60,
        "patient_condition": "STABLE",
        "patient_summary": "",
        "oxygen_requirement_lpm": 0,
        "iv_rate_mlhr": 0,
        "ventilator_required": 0,
        "safety_factor": 3.0,
        "emt_name": None,
        "departed_at": None,
        "created_at": datetime.now().isoformat()
    }
]

DEMO_ITEMS = [
    # TRF-DEMO-001 (COMPLETED) items - historical record
    {"id": 1, "mission_id": "TRF-DEMO-001", "item_type": "OXYGEN", "item_name": "E-Tank 氧氣鋼瓶", "unit": "瓶", "suggested_qty": 3, "carried_qty": 3, "returned_qty": 1, "consumed_qty": 2, "calculation_explain": "6 L/min × 1.5hr × 3 = 810L → 3瓶"},
    {"id": 2, "mission_id": "TRF-DEMO-001", "item_type": "IV_FLUID", "item_name": "NS 500mL", "unit": "袋", "suggested_qty": 1, "carried_qty": 1, "returned_qty": 0, "consumed_qty": 1, "calculation_explain": "100 mL/hr × 1.5hr × 3 = 450mL → 1袋"},
    {"id": 3, "mission_id": "TRF-DEMO-001", "item_type": "EQUIPMENT", "item_name": "生理監視器", "unit": "台", "suggested_qty": 1, "carried_qty": 1, "returned_qty": 1, "consumed_qty": 0, "calculation_explain": "電量需求 45%"},
    # TRF-DEMO-NEW (PLANNING) items - dynamically updated when user creates mission
    {"id": 4, "mission_id": "TRF-DEMO-NEW", "item_type": "OXYGEN", "item_name": "E-Tank 氧氣鋼瓶", "unit": "瓶", "suggested_qty": 2, "carried_qty": None, "calculation_explain": "依需求計算"},
    {"id": 5, "mission_id": "TRF-DEMO-NEW", "item_type": "IV_FLUID", "item_name": "NS 500mL", "unit": "袋", "suggested_qty": 1, "carried_qty": None, "calculation_explain": "依需求計算"},
    {"id": 6, "mission_id": "TRF-DEMO-NEW", "item_type": "EQUIPMENT", "item_name": "生理監視器", "unit": "台", "suggested_qty": 1, "carried_qty": None, "calculation_explain": "電量需求"},
    {"id": 7, "mission_id": "TRF-DEMO-NEW", "item_type": "MEDICATION", "item_name": "Epinephrine 1mg", "unit": "支", "suggested_qty": 2, "carried_qty": None, "calculation_explain": "急救藥物標準備量"},
]

router = APIRouter(prefix="/api/transfer", tags=["transfer"])


# =============================================================================
# Pydantic Models
# =============================================================================

class MissionCreate(BaseModel):
    """v2.0 任務建立模型 (v3.1: 新增 handoff_data)"""
    # 目的地 (v2.0: destination_text 為主, destination 為 alias)
    destination: Optional[str] = None
    destination_text: Optional[str] = None

    # 時間 (v2.0: eta_min 為單程, estimated_duration_min 為往返)
    eta_min: Optional[int] = Field(None, ge=10, le=480)
    estimated_duration_min: Optional[int] = Field(None, ge=10, le=720)

    # 病患狀況
    patient_condition: Optional[str] = "STABLE"  # CRITICAL, STABLE, INTUBATED
    patient_summary: Optional[str] = None

    # 氧氣 (v2.0: o2_lpm 為主)
    o2_lpm: Optional[float] = Field(None, ge=0, le=15)
    oxygen_requirement_lpm: Optional[float] = Field(None, ge=0, le=15)  # v1.x compat

    # 輸液 (v2.0: iv_mode + iv_mlhr_override)
    iv_mode: Optional[str] = "NONE"  # NONE, KVO, BOLUS, CUSTOM
    iv_mlhr_override: Optional[float] = Field(None, ge=0, le=1000)
    iv_rate_mlhr: Optional[float] = Field(None, ge=0, le=500)  # v1.x compat

    # 其他
    ventilator_required: bool = False
    safety_factor: float = Field(default=3.0, ge=1.0, le=15.0)  # v2.0: 1-15
    emt_name: Optional[str] = None
    notes: Optional[str] = None

    # v3.1: External source handoff data
    source_type: Optional[str] = "CIRS"  # CIRS | EXTERNAL
    handoff_data: Optional[dict] = None  # External handoff info with MIST report

    def get_destination(self) -> str:
        """Get destination, preferring destination_text"""
        return self.destination_text or self.destination or ""

    def get_eta_min(self) -> int:
        """Get ETA, calculating from duration if needed"""
        if self.eta_min:
            return self.eta_min
        if self.estimated_duration_min:
            return self.estimated_duration_min // 2  # Half of round-trip
        return 60  # Default 1 hour

    def get_o2_lpm(self) -> float:
        """Get O2 L/min, with v1.x compat"""
        return self.o2_lpm if self.o2_lpm is not None else (self.oxygen_requirement_lpm or 0)

    def get_iv_rate(self) -> float:
        """Get effective IV rate based on mode"""
        if self.iv_mode == "NONE":
            return 0
        if self.iv_mode == "KVO":
            return 30
        if self.iv_mode == "BOLUS":
            return 1000  # 500mL/30min equivalent
        if self.iv_mode == "CUSTOM" and self.iv_mlhr_override:
            return self.iv_mlhr_override
        # v1.x compat
        return self.iv_rate_mlhr or 0


class MissionUpdate(BaseModel):
    destination: Optional[str] = None
    estimated_duration_min: Optional[int] = Field(None, ge=10, le=720)
    patient_condition: Optional[str] = None
    patient_summary: Optional[str] = None
    oxygen_requirement_lpm: Optional[float] = Field(None, ge=0, le=15)
    iv_rate_mlhr: Optional[float] = Field(None, ge=0, le=500)
    ventilator_required: Optional[bool] = None
    safety_factor: Optional[float] = Field(None, ge=1.0, le=5.0)
    notes: Optional[str] = None


class TransferItemConfirm(BaseModel):
    """v1.x 相容的確認模型"""
    item_id: int
    carried_qty: float
    initial_status: Optional[str] = None  # e.g., "PSI: 2100"


# =============================================================================
# v2.0 Models - Cylinder & Battery Tracking
# =============================================================================

class OxygenCylinderConfirm(BaseModel):
    """v2.0 氧氣瓶確認 (PSI 追蹤)"""
    cylinder_id: Optional[str] = None       # Equipment unit ID
    cylinder_type: str = "E"                # E, D, H, M
    unit_label: Optional[str] = None        # Physical label
    starting_psi: int = Field(..., ge=0, le=3000)


class OxygenCylinderFinalize(BaseModel):
    """v2.0 氧氣瓶結案"""
    cylinder_id: Optional[str] = None
    ending_psi: int = Field(..., ge=0, le=3000)


class EquipmentBatteryConfirm(BaseModel):
    """v2.0 設備電量確認"""
    equipment_id: Optional[str] = None
    equipment_name: str
    equipment_type: Optional[str] = None    # MONITOR, VENTILATOR, SUCTION
    starting_battery_pct: int = Field(..., ge=0, le=100)


class EquipmentBatteryFinalize(BaseModel):
    """v2.0 設備電量結案"""
    equipment_id: Optional[str] = None
    ending_battery_pct: int = Field(..., ge=0, le=100)


class RecheckItem(BaseModel):
    """歸還確認"""
    item_id: int
    returned_qty: float
    final_status: Optional[str] = None  # e.g., "PSI: 500"


class ConfirmLoadoutV2(BaseModel):
    """v2.0 確認攜帶清單"""
    items: List[TransferItemConfirm] = []
    oxygen_cylinders: List[OxygenCylinderConfirm] = []
    equipment: List[EquipmentBatteryConfirm] = []


class FinalizeV2(BaseModel):
    """v2.0 結案"""
    items: List[RecheckItem] = []
    oxygen_cylinders: List[OxygenCylinderFinalize] = []
    equipment: List[EquipmentBatteryFinalize] = []


class IncomingItem(BaseModel):
    """外帶物資"""
    item_type: str
    item_name: str
    quantity: float
    unit: str = "個"
    source_station: Optional[str] = None
    condition: str = "GOOD"
    oxygen_psi: Optional[int] = None
    battery_percent: Optional[int] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = None


class SupplySuggestion(BaseModel):
    item_type: str
    item_name: str
    suggested_qty: float
    unit: str
    calculation_explain: str
    min_battery_percent: Optional[float] = None


# =============================================================================
# Database Helpers
# =============================================================================

def get_db_connection():
    """Get database connection from main module."""
    from main import db
    return db.get_connection()


def generate_mission_id() -> str:
    """Generate mission ID: TRF-YYYYMMDD-NNN"""
    date_str = datetime.now().strftime("%Y%m%d")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM transfer_missions WHERE mission_id LIKE ?",
        (f"TRF-{date_str}-%",)
    )
    count = cursor.fetchone()[0] + 1
    conn.close()
    return f"TRF-{date_str}-{count:03d}"


def emit_event(mission_id: str, event_type: str, payload: dict, actor_id: str = None):
    """Emit a transfer event (append-only)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    event_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO transfer_events (event_id, mission_id, type, payload_json, actor_id)
        VALUES (?, ?, ?, ?, ?)
    """, (event_id, mission_id, event_type, json.dumps(payload), actor_id))
    conn.commit()
    conn.close()
    return event_id


# =============================================================================
# Schema Initialization
# =============================================================================

def init_transfer_schema(cursor):
    """Initialize transfer module schema (v1.0 + v2.0)."""
    from pathlib import Path

    # v1.0 base migration
    migration_path = Path(__file__).parent.parent / "database" / "migrations" / "add_transfer_module.sql"

    if migration_path.exists():
        logger.info("Running transfer module migration (v1.0)...")
        with open(migration_path, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        try:
            cursor.connection.executescript(migration_sql)
            logger.info("✓ Transfer module schema v1.0 initialized")
        except Exception as e:
            if "already exists" not in str(e).lower():
                logger.warning(f"Transfer v1.0 migration warning: {e}")
    else:
        logger.warning(f"Transfer v1.0 migration not found: {migration_path}")

    # v2.0 upgrade migration
    v2_migration_path = Path(__file__).parent.parent / "database" / "migrations" / "transfer_v2_upgrade.sql"

    if v2_migration_path.exists():
        logger.info("Running transfer module migration (v2.0)...")
        with open(v2_migration_path, 'r', encoding='utf-8') as f:
            v2_sql = f.read()

        # Run each ALTER TABLE separately (SQLite doesn't support multiple in one statement)
        for statement in v2_sql.split(';'):
            statement = statement.strip()
            if not statement or statement.startswith('--'):
                continue
            try:
                cursor.execute(statement)
            except Exception as e:
                # Ignore "duplicate column" and "table already exists" errors
                err_str = str(e).lower()
                if "duplicate" not in err_str and "already exists" not in err_str:
                    logger.debug(f"v2.0 migration statement skipped: {e}")

        cursor.connection.commit()
        logger.info("✓ Transfer module schema v2.0 initialized")

    # Add claimed_by_mission_id column to equipment_units if not exists
    try:
        cursor.execute("SELECT claimed_by_mission_id FROM equipment_units LIMIT 1")
    except Exception:
        try:
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_mission_id TEXT")
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN mission_claimed_at TIMESTAMP")
            logger.info("✓ Added claimed_by_mission_id to equipment_units")
        except Exception as e:
            if "duplicate" not in str(e).lower():
                logger.warning(f"Failed to add claimed_by_mission_id: {e}")


# =============================================================================
# Inventory Interlock Functions
# =============================================================================

# Cylinder capacity reference (liters at full PSI)
CYLINDER_CAPACITY = {
    'E': {'liters': 660, 'full_psi': 2100},
    'D': {'liters': 350, 'full_psi': 2100},
    'M': {'liters': 3000, 'full_psi': 2200},
    'H': {'liters': 6900, 'full_psi': 2200},
    'Jumbo-D': {'liters': 640, 'full_psi': 2200},
}


def calculate_consumed_liters(cylinder_type: str, starting_psi: int, ending_psi: int) -> float:
    """Calculate consumed liters from PSI difference."""
    cap = CYLINDER_CAPACITY.get(cylinder_type, CYLINDER_CAPACITY['E'])
    if starting_psi <= 0:
        return 0
    consumed = (starting_psi - ending_psi) / cap['full_psi'] * cap['liters']
    return max(0, round(consumed, 1))


# =============================================================================
# v2.0 Inventory Interlock - PSI & Battery Tracking
# =============================================================================

def reserve_cylinders_v2(mission_id: str, cylinders: List[dict], cursor) -> List[dict]:
    """
    v2.0: 預留氧氣鋼瓶 (PLANNING → READY)
    記錄每瓶的 starting_psi 到 transfer_oxygen_cylinders 表
    Returns: list of reserved cylinder records
    """
    reserved = []

    for cyl in cylinders:
        # Insert into tracking table
        cursor.execute("""
            INSERT INTO transfer_oxygen_cylinders (
                mission_id, cylinder_id, cylinder_type, unit_label, starting_psi, status
            ) VALUES (?, ?, ?, ?, ?, 'ASSIGNED')
        """, (
            mission_id,
            cyl.get('cylinder_id'),
            cyl.get('cylinder_type', 'E'),
            cyl.get('unit_label'),
            cyl.get('starting_psi', 0)
        ))

        # If linked to equipment_units, mark as reserved
        if cyl.get('cylinder_id'):
            try:
                cursor.execute("""
                    UPDATE equipment_units
                    SET claimed_by_mission_id = ?,
                        mission_claimed_at = CURRENT_TIMESTAMP,
                        status = 'RESERVED'
                    WHERE id = ? OR unit_label = ?
                """, (mission_id, cyl['cylinder_id'], cyl['cylinder_id']))
            except Exception as e:
                logger.debug(f"Could not reserve equipment unit: {e}")

        reserved.append({
            'cylinder_id': cyl.get('cylinder_id'),
            'cylinder_type': cyl.get('cylinder_type', 'E'),
            'starting_psi': cyl.get('starting_psi', 0)
        })
        logger.info(f"Reserved O2 cylinder {cyl.get('cylinder_id') or 'unlabeled'} @ {cyl.get('starting_psi')} PSI")

    return reserved


def reserve_equipment_v2(mission_id: str, equipment: List[dict], cursor) -> List[dict]:
    """
    v2.0: 預留設備 (PLANNING → READY)
    記錄每台設備的 starting_battery_pct 到 transfer_equipment_battery 表
    """
    reserved = []

    for eq in equipment:
        cursor.execute("""
            INSERT INTO transfer_equipment_battery (
                mission_id, equipment_id, equipment_name, equipment_type,
                starting_battery_pct, status
            ) VALUES (?, ?, ?, ?, ?, 'ASSIGNED')
        """, (
            mission_id,
            eq.get('equipment_id'),
            eq.get('equipment_name', 'Unknown'),
            eq.get('equipment_type'),
            eq.get('starting_battery_pct', 100)
        ))

        # If linked to equipment_units, mark as reserved
        if eq.get('equipment_id'):
            try:
                cursor.execute("""
                    UPDATE equipment_units
                    SET claimed_by_mission_id = ?,
                        mission_claimed_at = CURRENT_TIMESTAMP,
                        status = 'RESERVED'
                    WHERE id = ? OR unit_label = ?
                """, (mission_id, eq['equipment_id'], eq['equipment_id']))
            except Exception as e:
                logger.debug(f"Could not reserve equipment unit: {e}")

        reserved.append({
            'equipment_id': eq.get('equipment_id'),
            'equipment_name': eq.get('equipment_name'),
            'starting_battery_pct': eq.get('starting_battery_pct', 100)
        })
        logger.info(f"Reserved equipment {eq.get('equipment_name')} @ {eq.get('starting_battery_pct')}%")

    return reserved


def finalize_cylinders_v2(mission_id: str, cylinders: List[dict], cursor) -> dict:
    """
    v2.0: 歸還氧氣鋼瓶 (ARRIVED → COMPLETED)
    記錄 ending_psi，計算 consumed_liters
    """
    total_consumed = 0
    finalized = []

    for cyl in cylinders:
        cyl_id = cyl.get('cylinder_id')
        ending_psi = cyl.get('ending_psi', 0)

        # Get starting PSI from tracking table
        cursor.execute("""
            SELECT id, cylinder_type, starting_psi
            FROM transfer_oxygen_cylinders
            WHERE mission_id = ? AND (cylinder_id = ? OR cylinder_id IS NULL)
            LIMIT 1
        """, (mission_id, cyl_id))
        row = cursor.fetchone()

        if row:
            starting_psi = row['starting_psi'] or 0
            cyl_type = row['cylinder_type'] or 'E'
            consumed = calculate_consumed_liters(cyl_type, starting_psi, ending_psi)
            total_consumed += consumed

            # Update tracking table
            cursor.execute("""
                UPDATE transfer_oxygen_cylinders
                SET ending_psi = ?, consumed_liters = ?, status = 'RETURNED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (ending_psi, consumed, row['id']))

            finalized.append({
                'cylinder_id': cyl_id,
                'starting_psi': starting_psi,
                'ending_psi': ending_psi,
                'consumed_liters': consumed
            })

        # Release equipment_units
        if cyl_id:
            try:
                # Convert PSI to level_percent
                cap = CYLINDER_CAPACITY.get(cyl_type, CYLINDER_CAPACITY['E'])
                new_level = min(100, (ending_psi / cap['full_psi']) * 100)

                cursor.execute("""
                    UPDATE equipment_units
                    SET claimed_by_mission_id = NULL,
                        mission_claimed_at = NULL,
                        status = 'UNCHECKED',
                        level_percent = ?
                    WHERE id = ? OR unit_label = ?
                """, (new_level, cyl_id, cyl_id))
            except Exception as e:
                logger.debug(f"Could not release equipment unit: {e}")

    return {
        'cylinders': finalized,
        'total_consumed_liters': total_consumed
    }


def finalize_equipment_v2(mission_id: str, equipment: List[dict], cursor) -> dict:
    """
    v2.0: 歸還設備 (ARRIVED → COMPLETED)
    記錄 ending_battery_pct，計算 drain
    """
    finalized = []

    for eq in equipment:
        eq_id = eq.get('equipment_id')
        ending_pct = eq.get('ending_battery_pct', 0)

        # Get starting battery from tracking table
        cursor.execute("""
            SELECT id, equipment_name, starting_battery_pct
            FROM transfer_equipment_battery
            WHERE mission_id = ? AND (equipment_id = ? OR equipment_id IS NULL)
            LIMIT 1
        """, (mission_id, eq_id))
        row = cursor.fetchone()

        if row:
            starting_pct = row['starting_battery_pct'] or 100
            drain = starting_pct - ending_pct

            # Update tracking table
            cursor.execute("""
                UPDATE transfer_equipment_battery
                SET ending_battery_pct = ?, battery_drain_pct = ?, status = 'RETURNED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (ending_pct, drain, row['id']))

            finalized.append({
                'equipment_id': eq_id,
                'equipment_name': row['equipment_name'],
                'starting_battery_pct': starting_pct,
                'ending_battery_pct': ending_pct,
                'drain_pct': drain
            })

        # Release equipment_units
        if eq_id:
            try:
                cursor.execute("""
                    UPDATE equipment_units
                    SET claimed_by_mission_id = NULL,
                        mission_claimed_at = NULL,
                        status = 'UNCHECKED',
                        level_percent = ?
                    WHERE id = ? OR unit_label = ?
                """, (ending_pct, eq_id, eq_id))
            except Exception as e:
                logger.debug(f"Could not release equipment unit: {e}")

    return {'equipment': finalized}


# =============================================================================
# v1.x Legacy Inventory Interlock (for backwards compatibility)
# =============================================================================

def reserve_oxygen_cylinders(mission_id: str, quantity: int, cursor) -> List[int]:
    """
    預留氧氣鋼瓶 (PLANNING → READY)
    選擇可用的鋼瓶，標記為已預留
    Returns: list of reserved unit IDs
    """
    reserved_units = []

    # 找到氧氣鋼瓶設備 (E-tank 或類似)
    # Note: claimed_by_mission_id may not exist in older DBs, so we catch errors
    try:
        cursor.execute("""
            SELECT eu.id, eu.unit_label, eu.level_percent
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE (e.name LIKE '%氧氣%' OR e.name LIKE '%O2%' OR e.name LIKE '%E-Tank%')
              AND eu.status IN ('OK', 'CHECKED', 'UNCHECKED')
              AND eu.is_active = 1
              AND eu.claimed_by_case_id IS NULL
              AND (eu.claimed_by_mission_id IS NULL OR eu.claimed_by_mission_id = '')
            ORDER BY eu.level_percent DESC
            LIMIT ?
        """, (quantity,))
    except Exception:
        # Fallback: claimed_by_mission_id column doesn't exist
        cursor.execute("""
            SELECT eu.id, eu.unit_label, eu.level_percent
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE (e.name LIKE '%氧氣%' OR e.name LIKE '%O2%' OR e.name LIKE '%E-Tank%')
              AND eu.status IN ('OK', 'CHECKED', 'UNCHECKED')
              AND eu.is_active = 1
              AND eu.claimed_by_case_id IS NULL
            ORDER BY eu.level_percent DESC
            LIMIT ?
        """, (quantity,))

    available_units = cursor.fetchall()

    for unit in available_units:
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_mission_id = ?,
                mission_claimed_at = CURRENT_TIMESTAMP,
                status = 'RESERVED'
            WHERE id = ?
        """, (mission_id, unit['id']))
        reserved_units.append(unit['id'])
        logger.info(f"Reserved O2 unit {unit['id']} ({unit['unit_label']}) for mission {mission_id}")

    return reserved_units


def issue_oxygen_cylinders(mission_id: str, cursor) -> int:
    """
    發放氧氣鋼瓶 (READY → EN_ROUTE)
    將預留的鋼瓶改為發放狀態
    Returns: number of issued units
    """
    cursor.execute("""
        UPDATE equipment_units
        SET status = 'IN_TRANSFER'
        WHERE claimed_by_mission_id = ? AND status = 'RESERVED'
    """, (mission_id,))

    issued_count = cursor.rowcount
    logger.info(f"Issued {issued_count} O2 units for mission {mission_id}")
    return issued_count


def return_oxygen_cylinders(mission_id: str, returned_items: List[dict], cursor) -> int:
    """
    歸還氧氣鋼瓶 (ARRIVED → COMPLETED)
    更新鋼瓶狀態和剩餘量
    Returns: number of returned units
    """
    returned_count = 0

    # 取得任務關聯的氧氣鋼瓶
    cursor.execute("""
        SELECT id, unit_label, level_percent
        FROM equipment_units
        WHERE claimed_by_mission_id = ?
    """, (mission_id,))

    units = cursor.fetchall()

    for unit in units:
        # 尋找對應的歸還資訊
        final_psi = None
        for item in returned_items:
            if item.get('final_status') and 'PSI' in str(item.get('final_status', '')):
                # Parse PSI from final_status like "PSI: 500"
                try:
                    final_psi = int(item['final_status'].replace('PSI:', '').strip())
                    # Convert PSI to percent (assuming 2100 PSI = 100%)
                    new_level = min(100, (final_psi / 2100) * 100)
                except:
                    new_level = 50  # Default if parsing fails

        # 更新鋼瓶狀態
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_mission_id = NULL,
                mission_claimed_at = NULL,
                status = 'UNCHECKED',
                level_percent = COALESCE(?, level_percent)
            WHERE id = ?
        """, (new_level if final_psi else None, unit['id']))

        returned_count += 1
        logger.info(f"Returned O2 unit {unit['id']} for mission {mission_id}")

    return returned_count


def cancel_oxygen_reservation(mission_id: str, cursor) -> int:
    """
    取消氧氣預留 (任何狀態 → ABORTED)
    Returns: number of released units
    """
    cursor.execute("""
        UPDATE equipment_units
        SET claimed_by_mission_id = NULL,
            mission_claimed_at = NULL,
            status = CASE
                WHEN status = 'IN_TRANSFER' THEN 'UNCHECKED'
                WHEN status = 'RESERVED' THEN 'UNCHECKED'
                ELSE status
            END
        WHERE claimed_by_mission_id = ?
    """, (mission_id,))

    released_count = cursor.rowcount
    logger.info(f"Released {released_count} O2 units for aborted mission {mission_id}")
    return released_count


def get_effective_oxygen_inventory(cursor) -> dict:
    """
    取得有效氧氣庫存 (韌性計算用)
    Returns: {available, reserved, in_transfer, total}
    """
    try:
        cursor.execute("""
            SELECT
                SUM(CASE WHEN eu.claimed_by_mission_id IS NULL AND eu.claimed_by_case_id IS NULL THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN eu.status = 'RESERVED' THEN 1 ELSE 0 END) as reserved,
                SUM(CASE WHEN eu.status = 'IN_TRANSFER' THEN 1 ELSE 0 END) as in_transfer,
                COUNT(*) as total
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE (e.name LIKE '%氧氣%' OR e.name LIKE '%O2%' OR e.name LIKE '%E-Tank%')
              AND eu.is_active = 1
        """)
    except Exception:
        # Fallback: claimed_by_mission_id column doesn't exist
        cursor.execute("""
            SELECT
                SUM(CASE WHEN eu.claimed_by_case_id IS NULL THEN 1 ELSE 0 END) as available,
                0 as reserved,
                0 as in_transfer,
                COUNT(*) as total
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE (e.name LIKE '%氧氣%' OR e.name LIKE '%O2%' OR e.name LIKE '%E-Tank%')
              AND eu.is_active = 1
        """)

    row = cursor.fetchone()
    return {
        'available': row['available'] or 0,
        'reserved': row['reserved'] or 0,
        'in_transfer': row['in_transfer'] or 0,
        'total': row['total'] or 0
    }


# =============================================================================
# Calculation Engine
# =============================================================================

def calculate_supplies(mission: dict) -> List[dict]:
    """
    計算轉送任務所需物資
    公式: 建議量 = 消耗率 × 預估時間 × 安全係數
    """
    duration_hr = mission['estimated_duration_min'] / 60
    safety = mission.get('safety_factor', 3.0)
    supplies = []

    # 1. 氧氣計算
    lpm = mission.get('oxygen_requirement_lpm', 0)
    if lpm > 0:
        liters_needed = lpm * 60 * duration_hr * safety
        # E-tank: 660L
        e_tanks = math.ceil(liters_needed / 660)

        supplies.append({
            'item_type': 'OXYGEN',
            'item_name': 'E-Tank 氧氣鋼瓶',
            'suggested_qty': e_tanks,
            'unit': '瓶',
            'calculation_explain': f'{lpm} L/min × {duration_hr:.1f}hr × {safety} = {liters_needed:.0f}L → {e_tanks}瓶'
        })

    # 2. 輸液計算
    iv_rate = mission.get('iv_rate_mlhr', 0)
    if iv_rate > 0:
        ml_needed = iv_rate * duration_hr * safety
        bags = math.ceil(ml_needed / 500)  # 500mL 袋

        supplies.append({
            'item_type': 'IV_FLUID',
            'item_name': 'NS 500mL',
            'suggested_qty': bags,
            'unit': '袋',
            'calculation_explain': f'{iv_rate} mL/hr × {duration_hr:.1f}hr × {safety} = {ml_needed:.0f}mL → {bags}袋'
        })

    # 3. 設備電量
    battery_drain = 10  # %/hr (監視器)
    if mission.get('ventilator_required'):
        battery_drain = 20  # 呼吸器耗電更高

    min_battery = min(100, battery_drain * duration_hr * safety)

    supplies.append({
        'item_type': 'EQUIPMENT',
        'item_name': '生理監視器',
        'suggested_qty': 1,
        'unit': '台',
        'min_battery_percent': min_battery,
        'calculation_explain': f'{battery_drain}%/hr × {duration_hr:.1f}hr × {safety} = {min_battery:.0f}%'
    })

    # 4. 基本急救藥物 (建議)
    supplies.append({
        'item_type': 'MEDICATION',
        'item_name': 'Epinephrine 1mg',
        'suggested_qty': 2,
        'unit': '支',
        'calculation_explain': '急救藥物標準備量'
    })

    supplies.append({
        'item_type': 'MEDICATION',
        'item_name': 'Atropine 0.5mg',
        'suggested_qty': 2,
        'unit': '支',
        'calculation_explain': '急救藥物標準備量'
    })

    return supplies


# =============================================================================
# Equipment Availability API
# =============================================================================

@router.get("/available-cylinders")
async def get_available_cylinders():
    """取得可用氧氣鋼瓶列表 (供認領)"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "cylinders": [
                {"id": "demo-1", "unit_label": "E-001", "cylinder_type": "E", "level_percent": 100, "estimated_psi": 2100},
                {"id": "demo-2", "unit_label": "E-002", "cylinder_type": "E", "level_percent": 85, "estimated_psi": 1785},
                {"id": "demo-3", "unit_label": "E-003", "cylinder_type": "E", "level_percent": 50, "estimated_psi": 1050},
            ],
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT eu.id, eu.unit_label, eu.level_percent, e.name
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE (e.name LIKE '%氧氣%' OR e.name LIKE '%O2%' OR e.name LIKE '%E-Tank%' OR e.name LIKE '%D-Tank%')
              AND eu.status IN ('OK', 'CHECKED', 'UNCHECKED')
              AND eu.is_active = 1
              AND eu.claimed_by_case_id IS NULL
              AND (eu.claimed_by_mission_id IS NULL OR eu.claimed_by_mission_id = '')
            ORDER BY eu.level_percent DESC
        """)
        rows = cursor.fetchall()

        cylinders = []
        for row in rows:
            # 判斷鋼瓶類型
            name = row['name'].upper()
            if 'D-TANK' in name or 'D TANK' in name:
                cyl_type = 'D'
                full_psi = 2100
            elif 'H-TANK' in name or 'H TANK' in name:
                cyl_type = 'H'
                full_psi = 2200
            else:
                cyl_type = 'E'  # 預設 E-tank
                full_psi = 2100

            cylinders.append({
                "id": row['id'],
                "unit_label": row['unit_label'],
                "cylinder_type": cyl_type,
                "level_percent": row['level_percent'] or 100,
                "estimated_psi": int((row['level_percent'] or 100) / 100 * full_psi)
            })

        return {"cylinders": cylinders}
    finally:
        conn.close()


# =============================================================================
# Mission CRUD
# =============================================================================

@router.get("/missions")
async def list_missions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """取得轉送任務列表"""
    # Vercel demo mode - return mock data instantly
    if IS_VERCEL:
        # 只回傳 COMPLETED 任務，讓使用者看到「開始新任務」畫面
        # TRF-DEMO-NEW 會在使用者建立任務時動態使用
        missions = [m for m in DEMO_MISSIONS if m['status'] == 'COMPLETED']
        if status:
            missions = [m for m in missions if m['status'] == status]
        return {
            "missions": missions[offset:offset+limit],
            "total": len(missions),
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if status:
            cursor.execute("""
                SELECT * FROM transfer_missions
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (status, limit, offset))
        else:
            cursor.execute("""
                SELECT * FROM transfer_missions
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))

        missions = [dict(row) for row in cursor.fetchall()]

        # Get total count
        if status:
            cursor.execute("SELECT COUNT(*) FROM transfer_missions WHERE status = ?", (status,))
        else:
            cursor.execute("SELECT COUNT(*) FROM transfer_missions")
        total = cursor.fetchone()[0]

        return {"missions": missions, "total": total}
    finally:
        conn.close()


@router.post("/missions")
async def create_mission(mission: MissionCreate):
    """建立轉送任務 (v2.0)"""
    # Extract v2.0 compatible values
    destination = mission.get_destination()
    eta_min = mission.get_eta_min()
    o2_lpm = mission.get_o2_lpm()
    iv_rate = mission.get_iv_rate()
    duration_min = mission.estimated_duration_min or (eta_min * 2)  # Round-trip

    # Vercel demo mode - return existing PLANNING mission for demo flow
    if IS_VERCEL:
        # Use TRF-DEMO-NEW so loadMission() works
        demo_mission = DEMO_MISSIONS[1]  # TRF-DEMO-NEW
        # Update demo mission with user input
        demo_mission['destination'] = destination or "Demo 目的地"
        demo_mission['destination_text'] = destination
        demo_mission['eta_min'] = eta_min
        demo_mission['estimated_duration_min'] = duration_min
        demo_mission['oxygen_requirement_lpm'] = o2_lpm
        demo_mission['o2_lpm'] = o2_lpm
        demo_mission['iv_mode'] = mission.iv_mode
        demo_mission['iv_rate_mlhr'] = iv_rate
        demo_mission['safety_factor'] = mission.safety_factor
        demo_mission['patient_condition'] = mission.patient_condition
        demo_mission['emt_name'] = mission.emt_name
        demo_mission['status'] = 'PLANNING'

        supplies = calculate_supplies({
            'estimated_duration_min': duration_min,
            'safety_factor': mission.safety_factor,
            'oxygen_requirement_lpm': o2_lpm,
            'iv_rate_mlhr': iv_rate,
            'ventilator_required': mission.ventilator_required
        })

        # Update demo items with calculated supplies
        for i, s in enumerate(supplies):
            if i < len(DEMO_ITEMS) - 3:
                idx = i + 3  # Start from index 3
                if idx < len(DEMO_ITEMS):
                    DEMO_ITEMS[idx]['suggested_qty'] = s['suggested_qty']
                    DEMO_ITEMS[idx]['calculation_explain'] = s['calculation_explain']

        return {
            "mission_id": "TRF-DEMO-NEW",
            "status": "PLANNING",
            "supplies": supplies,
            "demo_mode": True,
            "demo_note": "Demo 模式 - 任務已建立"
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get station info
        try:
            cursor.execute("SELECT station_id, display_name FROM station_info LIMIT 1")
            station = cursor.fetchone()
            origin_id = station['station_id'] if station else 'MIRS-LOCAL'
            origin_name = station['display_name'] if station else 'MIRS-LOCAL'
        except Exception:
            origin_id = 'MIRS-LOCAL'
            origin_name = 'MIRS-LOCAL'

        import json as jsonlib

        mission_id = generate_mission_id()

        # v3.1: Ensure new columns exist for handoff data
        try:
            cursor.execute("ALTER TABLE transfer_missions ADD COLUMN source_type TEXT DEFAULT 'CIRS'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE transfer_missions ADD COLUMN handoff_data TEXT")
        except:
            pass

        # v3.1: Serialize handoff data
        handoff_data_json = jsonlib.dumps(mission.handoff_data) if mission.handoff_data else None

        # v3.1: Build patient summary from handoff data if external
        patient_summary = mission.patient_summary
        if mission.handoff_data and mission.source_type == 'EXTERNAL':
            hd = mission.handoff_data
            patient_summary = f"[{hd.get('source_org', '外部')}] {hd.get('patient_name', '')} {hd.get('patient_age', '')} - {hd.get('chief_complaint', '')}"

        # v2.0/v3.1: Insert with new fields
        cursor.execute("""
            INSERT INTO transfer_missions (
                mission_id, origin_station_id, origin_station, destination, destination_text,
                eta_min, estimated_duration_min, patient_condition, patient_summary,
                oxygen_requirement_lpm, iv_mode, iv_mlhr_override, iv_rate_mlhr,
                ventilator_required, safety_factor, emt_name, notes,
                source_type, handoff_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mission_id, origin_id, origin_name, destination, destination,
            eta_min, duration_min, mission.patient_condition, patient_summary,
            o2_lpm, mission.iv_mode, mission.iv_mlhr_override, iv_rate,
            1 if mission.ventilator_required else 0,
            mission.safety_factor, mission.emt_name, mission.notes,
            mission.source_type, handoff_data_json
        ))
        conn.commit()

        # Emit CREATE event
        emit_event(mission_id, 'CREATE', mission.model_dump())

        # Calculate suggested supplies
        supplies = calculate_supplies({
            'estimated_duration_min': duration_min,
            'safety_factor': mission.safety_factor,
            'oxygen_requirement_lpm': o2_lpm,
            'iv_rate_mlhr': iv_rate,
            'ventilator_required': mission.ventilator_required
        })

        # Insert suggested items
        for s in supplies:
            cursor.execute("""
                INSERT INTO transfer_items (
                    mission_id, item_type, item_name, unit, suggested_qty, calculation_explain
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                mission_id, s['item_type'], s['item_name'],
                s['unit'], s['suggested_qty'], s['calculation_explain']
            ))
        conn.commit()

        return {
            "mission_id": mission_id,
            "status": "PLANNING",
            "supplies": supplies
        }
    finally:
        conn.close()


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    """取得任務詳情"""
    # Vercel demo mode
    if IS_VERCEL:
        for m in DEMO_MISSIONS:
            if m['mission_id'] == mission_id:
                items = [i for i in DEMO_ITEMS if i['mission_id'] == mission_id]
                return {
                    "mission": m,
                    "items": items,
                    "incoming_items": [],
                    "demo_mode": True
                }
        raise HTTPException(status_code=404, detail="Mission not found (demo)")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        mission = cursor.fetchone()
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")

        cursor.execute("SELECT * FROM transfer_items WHERE mission_id = ?", (mission_id,))
        items = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM transfer_incoming_items WHERE mission_id = ?", (mission_id,))
        incoming = [dict(row) for row in cursor.fetchall()]

        return {
            "mission": dict(mission),
            "items": items,
            "incoming_items": incoming
        }
    finally:
        conn.close()


@router.post("/missions/{mission_id}/calculate")
async def recalculate_mission(mission_id: str):
    """重新計算物資需求"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        mission = cursor.fetchone()
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")

        supplies = calculate_supplies(dict(mission))

        # Update items
        cursor.execute("DELETE FROM transfer_items WHERE mission_id = ?", (mission_id,))
        for s in supplies:
            cursor.execute("""
                INSERT INTO transfer_items (
                    mission_id, item_type, item_name, unit, suggested_qty, calculation_explain
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                mission_id, s['item_type'], s['item_name'],
                s['unit'], s['suggested_qty'], s['calculation_explain']
            ))
        conn.commit()

        return {"supplies": supplies}
    finally:
        conn.close()


# =============================================================================
# Mission State Transitions
# =============================================================================

@router.post("/missions/{mission_id}/confirm")
async def confirm_loadout(mission_id: str, items: List[TransferItemConfirm]):
    """確認攜帶清單 (PLANNING → READY) - 含庫存預留"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "status": "READY",
            "message": "Loadout confirmed (demo)",
            "reserved_oxygen_units": 2,
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'PLANNING':
            raise HTTPException(status_code=400, detail="Mission must be in PLANNING status")

        # Update items with carried quantities
        oxygen_qty = 0
        for item in items:
            cursor.execute("""
                UPDATE transfer_items
                SET carried_qty = ?, initial_status = ?, checked = 1, checked_at = CURRENT_TIMESTAMP
                WHERE id = ? AND mission_id = ?
            """, (item.carried_qty, item.initial_status, item.item_id, mission_id))

            # Check if this is an oxygen item
            cursor.execute("SELECT item_type FROM transfer_items WHERE id = ?", (item.item_id,))
            item_row = cursor.fetchone()
            if item_row and item_row['item_type'] == 'OXYGEN':
                oxygen_qty += int(item.carried_qty or 0)

        # Reserve oxygen cylinders (inventory interlock)
        reserved_units = []
        if oxygen_qty > 0:
            try:
                reserved_units = reserve_oxygen_cylinders(mission_id, oxygen_qty, cursor)
            except Exception as e:
                logger.warning(f"Oxygen reservation warning: {e}")

        # Update mission status
        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'READY', ready_at = CURRENT_TIMESTAMP
            WHERE mission_id = ?
        """, (mission_id,))
        conn.commit()

        # Emit RESERVE event
        emit_event(mission_id, 'RESERVE', {
            'items': [i.model_dump() for i in items],
            'reserved_oxygen_units': reserved_units
        })

        return {
            "status": "READY",
            "message": "Loadout confirmed",
            "reserved_oxygen_units": len(reserved_units)
        }
    finally:
        conn.close()


@router.post("/missions/{mission_id}/confirm/v2")
async def confirm_loadout_v2(mission_id: str, payload: ConfirmLoadoutV2):
    """v2.0 確認攜帶清單 - 含 PSI/電量追蹤"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "status": "READY",
            "message": "Loadout confirmed (demo v2.0)",
            "cylinders": [{"cylinder_type": "E", "starting_psi": 2100}],
            "equipment": [{"equipment_name": "Monitor", "starting_battery_pct": 95}],
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'PLANNING':
            raise HTTPException(status_code=400, detail="Mission must be in PLANNING status")

        # Update items with carried quantities
        for item in payload.items:
            cursor.execute("""
                UPDATE transfer_items
                SET carried_qty = ?, initial_status = ?, checked = 1, checked_at = CURRENT_TIMESTAMP
                WHERE id = ? AND mission_id = ?
            """, (item.carried_qty, item.initial_status, item.item_id, mission_id))

        # v2.0: Reserve cylinders with PSI tracking
        reserved_cylinders = []
        if payload.oxygen_cylinders:
            reserved_cylinders = reserve_cylinders_v2(
                mission_id,
                [c.model_dump() for c in payload.oxygen_cylinders],
                cursor
            )

        # v2.0: Reserve equipment with battery tracking
        reserved_equipment = []
        if payload.equipment:
            reserved_equipment = reserve_equipment_v2(
                mission_id,
                [e.model_dump() for e in payload.equipment],
                cursor
            )

        # Update mission status and store JSON
        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'READY',
                ready_at = CURRENT_TIMESTAMP,
                confirmed_at = CURRENT_TIMESTAMP,
                oxygen_cylinders_json = ?,
                equipment_battery_json = ?
            WHERE mission_id = ?
        """, (
            json.dumps(reserved_cylinders),
            json.dumps(reserved_equipment),
            mission_id
        ))
        conn.commit()

        # Emit RESERVE event
        emit_event(mission_id, 'TRANSFER_RESERVE', {
            'items': [i.model_dump() for i in payload.items],
            'cylinders': reserved_cylinders,
            'equipment': reserved_equipment
        })

        return {
            "status": "READY",
            "message": "Loadout confirmed (v2.0)",
            "cylinders": reserved_cylinders,
            "equipment": reserved_equipment
        }
    finally:
        conn.close()


@router.post("/missions/{mission_id}/depart")
async def depart_mission(mission_id: str):
    """出發 (READY → EN_ROUTE) - 含庫存發放"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "status": "EN_ROUTE",
            "message": "Mission started (demo)",
            "issued_oxygen_units": 2,
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'READY':
            raise HTTPException(status_code=400, detail="Mission must be in READY status")

        # Issue oxygen cylinders (inventory interlock)
        issued_count = 0
        try:
            issued_count = issue_oxygen_cylinders(mission_id, cursor)
        except Exception as e:
            logger.warning(f"Oxygen issue warning: {e}")

        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'EN_ROUTE', departed_at = CURRENT_TIMESTAMP
            WHERE mission_id = ?
        """, (mission_id,))
        conn.commit()

        # Emit ISSUE event
        emit_event(mission_id, 'ISSUE', {
            'departed_at': datetime.now().isoformat(),
            'issued_oxygen_units': issued_count
        })

        return {
            "status": "EN_ROUTE",
            "message": "Mission started",
            "issued_oxygen_units": issued_count
        }
    finally:
        conn.close()


@router.post("/missions/{mission_id}/arrive")
async def arrive_mission(mission_id: str):
    """抵達 (EN_ROUTE → ARRIVED)"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "status": "ARRIVED",
            "actual_duration_min": 45,
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status, departed_at FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'EN_ROUTE':
            raise HTTPException(status_code=400, detail="Mission must be in EN_ROUTE status")

        # Calculate actual duration
        departed = datetime.fromisoformat(row['departed_at'].replace('Z', '+00:00'))
        actual_min = int((datetime.now() - departed).total_seconds() / 60)

        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'ARRIVED', arrived_at = CURRENT_TIMESTAMP, actual_duration_min = ?
            WHERE mission_id = ?
        """, (actual_min, mission_id))
        conn.commit()

        return {"status": "ARRIVED", "actual_duration_min": actual_min}
    finally:
        conn.close()


@router.post("/missions/{mission_id}/recheck")
async def recheck_items(mission_id: str, items: List[RecheckItem]):
    """返站確認剩餘量"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'ARRIVED':
            raise HTTPException(status_code=400, detail="Mission must be in ARRIVED status")

        for item in items:
            # Get carried qty to calculate consumed
            cursor.execute("SELECT carried_qty FROM transfer_items WHERE id = ?", (item.item_id,))
            carried = cursor.fetchone()
            consumed = (carried['carried_qty'] or 0) - item.returned_qty if carried else 0

            cursor.execute("""
                UPDATE transfer_items
                SET returned_qty = ?, final_status = ?, consumed_qty = ?
                WHERE id = ? AND mission_id = ?
            """, (item.returned_qty, item.final_status, consumed, item.item_id, mission_id))

        conn.commit()

        # Emit RETURN event
        emit_event(mission_id, 'RETURN', {'items': [i.model_dump() for i in items]})

        return {"message": "Recheck completed"}
    finally:
        conn.close()


@router.post("/missions/{mission_id}/incoming")
async def add_incoming_items(mission_id: str, items: List[IncomingItem]):
    """登記外帶物資"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        for item in items:
            cursor.execute("""
                INSERT INTO transfer_incoming_items (
                    mission_id, item_type, item_name, quantity, unit,
                    source_station, condition, oxygen_psi, battery_percent, lot_number, expiry_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mission_id, item.item_type, item.item_name, item.quantity, item.unit,
                item.source_station, item.condition, item.oxygen_psi, item.battery_percent,
                item.lot_number, item.expiry_date
            ))
        conn.commit()

        # Emit INCOMING event
        emit_event(mission_id, 'INCOMING', {'items': [i.model_dump() for i in items]})

        return {"message": f"Added {len(items)} incoming items"}
    finally:
        conn.close()


@router.post("/missions/{mission_id}/finalize")
async def finalize_mission(mission_id: str):
    """結案 (ARRIVED → COMPLETED) - 含庫存歸還"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "status": "COMPLETED",
            "summary": {
                "total_carried": 5,
                "total_returned": 2,
                "total_consumed": 3,
                "incoming_items": 0,
                "returned_oxygen_units": 2
            },
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'ARRIVED':
            raise HTTPException(status_code=400, detail="Mission must be in ARRIVED status")

        # Get returned items info for oxygen return
        cursor.execute("""
            SELECT id, item_type, returned_qty, final_status
            FROM transfer_items WHERE mission_id = ?
        """, (mission_id,))
        returned_items = [dict(r) for r in cursor.fetchall()]

        # Return oxygen cylinders (inventory interlock)
        returned_count = 0
        try:
            returned_count = return_oxygen_cylinders(mission_id, returned_items, cursor)
        except Exception as e:
            logger.warning(f"Oxygen return warning: {e}")

        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'COMPLETED', finalized_at = CURRENT_TIMESTAMP
            WHERE mission_id = ?
        """, (mission_id,))
        conn.commit()

        # Get summary
        cursor.execute("""
            SELECT
                SUM(carried_qty) as total_carried,
                SUM(returned_qty) as total_returned,
                SUM(consumed_qty) as total_consumed
            FROM transfer_items WHERE mission_id = ?
        """, (mission_id,))
        summary = dict(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) as count FROM transfer_incoming_items WHERE mission_id = ?", (mission_id,))
        incoming_count = cursor.fetchone()['count']

        # Emit FINALIZE event
        emit_event(mission_id, 'FINALIZE', {
            'returned_oxygen_units': returned_count,
            'summary': summary
        })

        return {
            "status": "COMPLETED",
            "summary": {
                **summary,
                "incoming_items": incoming_count,
                "returned_oxygen_units": returned_count
            }
        }
    finally:
        conn.close()


@router.post("/missions/{mission_id}/finalize/v2")
async def finalize_mission_v2(mission_id: str, payload: FinalizeV2):
    """v2.0 結案 - 含 PSI/電量計算"""
    # Vercel demo mode
    if IS_VERCEL:
        return {
            "status": "COMPLETED",
            "summary": {
                "total_carried": 5,
                "total_returned": 2,
                "total_consumed": 3,
            },
            "cylinders": [
                {"cylinder_type": "E", "starting_psi": 2100, "ending_psi": 1200, "consumed_liters": 283}
            ],
            "equipment": [
                {"equipment_name": "Monitor", "starting_battery_pct": 95, "ending_battery_pct": 70, "drain_pct": 25}
            ],
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] != 'ARRIVED':
            raise HTTPException(status_code=400, detail="Mission must be in ARRIVED status")

        # Update items with returned quantities
        for item in payload.items:
            cursor.execute("SELECT carried_qty FROM transfer_items WHERE id = ?", (item.item_id,))
            carried = cursor.fetchone()
            consumed = (carried['carried_qty'] or 0) - item.returned_qty if carried else 0

            cursor.execute("""
                UPDATE transfer_items
                SET returned_qty = ?, final_status = ?, consumed_qty = ?
                WHERE id = ? AND mission_id = ?
            """, (item.returned_qty, item.final_status, consumed, item.item_id, mission_id))

        # v2.0: Finalize cylinders with PSI tracking
        cylinder_result = {'cylinders': [], 'total_consumed_liters': 0}
        if payload.oxygen_cylinders:
            cylinder_result = finalize_cylinders_v2(
                mission_id,
                [c.model_dump() for c in payload.oxygen_cylinders],
                cursor
            )

        # v2.0: Finalize equipment with battery tracking
        equipment_result = {'equipment': []}
        if payload.equipment:
            equipment_result = finalize_equipment_v2(
                mission_id,
                [e.model_dump() for e in payload.equipment],
                cursor
            )

        # Update mission status
        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'COMPLETED',
                finalized_at = CURRENT_TIMESTAMP,
                oxygen_cylinders_json = ?,
                equipment_battery_json = ?
            WHERE mission_id = ?
        """, (
            json.dumps(cylinder_result['cylinders']),
            json.dumps(equipment_result['equipment']),
            mission_id
        ))
        conn.commit()

        # Get summary
        cursor.execute("""
            SELECT
                SUM(carried_qty) as total_carried,
                SUM(returned_qty) as total_returned,
                SUM(consumed_qty) as total_consumed
            FROM transfer_items WHERE mission_id = ?
        """, (mission_id,))
        summary = dict(cursor.fetchone())

        # Emit FINALIZE event
        emit_event(mission_id, 'TRANSFER_RETURN', {
            'items': [i.model_dump() for i in payload.items],
            'cylinders': cylinder_result['cylinders'],
            'equipment': equipment_result['equipment'],
            'total_consumed_liters': cylinder_result['total_consumed_liters']
        })

        return {
            "status": "COMPLETED",
            "summary": summary,
            "cylinders": cylinder_result['cylinders'],
            "total_consumed_liters": cylinder_result['total_consumed_liters'],
            "equipment": equipment_result['equipment']
        }
    finally:
        conn.close()


@router.post("/missions/{mission_id}/abort")
async def abort_mission(mission_id: str, reason: str = None):
    """中止任務 - 含庫存釋放"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT status FROM transfer_missions WHERE mission_id = ?", (mission_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mission not found")
        if row['status'] in ['COMPLETED', 'ABORTED']:
            raise HTTPException(status_code=400, detail="Mission already finalized")

        # Cancel oxygen reservation (inventory interlock)
        released_count = 0
        try:
            released_count = cancel_oxygen_reservation(mission_id, cursor)
        except Exception as e:
            logger.warning(f"Oxygen release warning: {e}")

        cursor.execute("""
            UPDATE transfer_missions
            SET status = 'ABORTED', notes = COALESCE(notes || ' | ', '') || ?
            WHERE mission_id = ?
        """, (f"ABORTED: {reason or 'No reason'}", mission_id))
        conn.commit()

        # Emit ABORT event
        emit_event(mission_id, 'ABORT', {
            'reason': reason,
            'released_oxygen_units': released_count
        })

        return {
            "status": "ABORTED",
            "released_oxygen_units": released_count
        }
    finally:
        conn.close()


# =============================================================================
# Consumption Rates
# =============================================================================

@router.get("/consumption-rates")
async def get_consumption_rates():
    """取得消耗率設定"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM consumption_rates ORDER BY item_type, condition")
        rates = [dict(row) for row in cursor.fetchall()]
        return {"rates": rates}
    finally:
        conn.close()


@router.get("/oxygen-inventory")
async def get_oxygen_inventory_status():
    """
    取得氧氣有效庫存狀態 (韌性計算用)
    Returns: available, reserved, in_transfer, total
    Invariant: available = total - reserved - in_transfer - claimed_by_anesthesia
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        inventory = get_effective_oxygen_inventory(cursor)

        # Also get active transfer missions count
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM transfer_missions
            WHERE status IN ('READY', 'EN_ROUTE')
        """)
        active_missions = cursor.fetchone()['count']

        return {
            **inventory,
            "active_transfer_missions": active_missions
        }
    finally:
        conn.close()
