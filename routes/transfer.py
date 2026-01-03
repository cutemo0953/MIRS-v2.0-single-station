"""
MIRS EMT Transfer Module API
Version: 1.0.0

病患轉送任務管理：
- 物資計算 (3× 安全係數)
- 離線優先架構
- 庫存連動
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
import math
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transfer", tags=["transfer"])


# =============================================================================
# Pydantic Models
# =============================================================================

class MissionCreate(BaseModel):
    destination: str = Field(..., min_length=1)
    estimated_duration_min: int = Field(..., ge=10, le=720)
    patient_condition: Optional[str] = "STABLE"  # CRITICAL, STABLE, INTUBATED
    patient_summary: Optional[str] = None
    oxygen_requirement_lpm: float = Field(default=0, ge=0, le=15)
    iv_rate_mlhr: float = Field(default=0, ge=0, le=500)
    ventilator_required: bool = False
    safety_factor: float = Field(default=3.0, ge=1.0, le=5.0)
    emt_name: Optional[str] = None
    notes: Optional[str] = None


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
    item_id: int
    carried_qty: float
    initial_status: Optional[str] = None  # e.g., "PSI: 2100"


class RecheckItem(BaseModel):
    item_id: int
    returned_qty: float
    final_status: Optional[str] = None  # e.g., "PSI: 500"


class IncomingItem(BaseModel):
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
    """Initialize transfer module schema."""
    from pathlib import Path

    migration_path = Path(__file__).parent.parent / "database" / "migrations" / "add_transfer_module.sql"

    if migration_path.exists():
        logger.info("Running transfer module migration...")
        with open(migration_path, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        try:
            cursor.connection.executescript(migration_sql)
            logger.info("✓ Transfer module schema initialized")
        except Exception as e:
            if "already exists" not in str(e).lower():
                logger.warning(f"Transfer migration warning: {e}")
    else:
        logger.warning(f"Transfer migration not found: {migration_path}")

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
# Mission CRUD
# =============================================================================

@router.get("/missions")
async def list_missions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """取得轉送任務列表"""
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
    """建立轉送任務"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get station info (may not exist in all setups)
        try:
            cursor.execute("SELECT station_id, display_name FROM station_info LIMIT 1")
            station = cursor.fetchone()
            origin = station['station_id'] if station else 'MIRS-LOCAL'
        except Exception:
            origin = 'MIRS-LOCAL'

        mission_id = generate_mission_id()

        cursor.execute("""
            INSERT INTO transfer_missions (
                mission_id, origin_station, destination, estimated_duration_min,
                patient_condition, patient_summary, oxygen_requirement_lpm,
                iv_rate_mlhr, ventilator_required, safety_factor, emt_name, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mission_id, origin, mission.destination, mission.estimated_duration_min,
            mission.patient_condition, mission.patient_summary, mission.oxygen_requirement_lpm,
            mission.iv_rate_mlhr, 1 if mission.ventilator_required else 0,
            mission.safety_factor, mission.emt_name, mission.notes
        ))
        conn.commit()

        # Emit CREATE event
        emit_event(mission_id, 'CREATE', mission.model_dump())

        # Calculate suggested supplies
        supplies = calculate_supplies({
            'estimated_duration_min': mission.estimated_duration_min,
            'safety_factor': mission.safety_factor,
            'oxygen_requirement_lpm': mission.oxygen_requirement_lpm,
            'iv_rate_mlhr': mission.iv_rate_mlhr,
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


@router.post("/missions/{mission_id}/depart")
async def depart_mission(mission_id: str):
    """出發 (READY → EN_ROUTE) - 含庫存發放"""
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
