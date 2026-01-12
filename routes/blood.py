"""
MIRS Blood Bank Module (v1.0.0)
===============================

Based on DEV_SPEC_BLOOD_BANK_PWA_v2.0:
- Order-driven 職責邊界
- 原子預約 (409 CONFLICT)
- 狀態機硬規則
- 緊急發血 (Break-Glass)
- Event Sourcing 稽核

雙軌並行：
- MIRS Tab (簡易版): 庫存總覽、簡易扣庫
- Blood PWA (專業版): 完整配血流程、Barcode 掃描
"""

import os
import json
import uuid
import hashlib
import sqlite3
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blood", tags=["blood"])

# ==============================================================================
# Configuration
# ==============================================================================

IS_VERCEL = os.getenv("VERCEL", "").lower() in ("1", "true")
PROJECT_ROOT = Path(__file__).parent.parent

# 冷鏈限制 (分鐘)
COLD_CHAIN_LIMIT_MINUTES = 30

# 預約過期時間 (小時)
RESERVE_EXPIRY_HOURS = 4

# ==============================================================================
# 狀態機定義 (API 強制)
# ==============================================================================

ALLOWED_TRANSITIONS = {
    'RECEIVED': ['AVAILABLE', 'QUARANTINE', 'WASTE'],
    'AVAILABLE': ['RESERVED', 'ISSUED', 'WASTE', 'QUARANTINE'],
    'RESERVED': ['AVAILABLE', 'ISSUED', 'WASTE'],  # AVAILABLE = unreserve/timeout
    'ISSUED': [],  # 不可逆
    'QUARANTINE': ['AVAILABLE', 'WASTE'],
    'WASTE': [],  # 不可逆
}

BLOOD_TYPES = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']
UNIT_TYPES = ['PRBC', 'FFP', 'PLT', 'CRYO']


def validate_status_transition(current: str, target: str) -> bool:
    """驗證狀態轉移是否合法"""
    return target in ALLOWED_TRANSITIONS.get(current, [])


# ==============================================================================
# Database Helpers
# ==============================================================================

def get_db():
    """Get database connection"""
    db_path = PROJECT_ROOT / "medical_inventory.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def log_blood_event(
    cursor: sqlite3.Cursor,
    unit_id: str,
    event_type: str,
    actor: str,
    reason: str = None,
    order_id: str = None,
    metadata: dict = None,
    severity: str = "INFO"
):
    """記錄血袋事件 (Event Sourcing)"""
    event_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO blood_unit_events (
            id, unit_id, order_id, event_type, actor, reason, metadata, severity, ts_server
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
    """, (
        event_id,
        unit_id,
        order_id,
        event_type,
        actor,
        reason,
        json.dumps(metadata) if metadata else None,
        severity
    ))
    return event_id


# ==============================================================================
# Pydantic Models
# ==============================================================================

class BloodUnitCreate(BaseModel):
    """血袋入庫"""
    id: Optional[str] = None  # 可自動生成
    blood_type: str
    unit_type: str = "PRBC"
    volume_ml: int = 250
    donation_id: Optional[str] = None
    collection_date: Optional[str] = None
    expiry_date: str
    refrigerator_id: Optional[str] = None


class BloodUnitReserve(BaseModel):
    """預約血袋"""
    order_id: str
    reserver_id: str


class BloodUnitIssue(BaseModel):
    """發血出庫"""
    order_id: str
    issuer_id: str


class BloodUnitReturn(BaseModel):
    """血品退庫"""
    out_of_refrigerator_minutes: int
    reason: str
    returner_id: str


class EmergencyRelease(BaseModel):
    """緊急發血"""
    blood_type: str
    quantity: int = 1
    reason: str
    requester_id: str


class BatchUpdate(BaseModel):
    """批次更新"""
    refrigerator_id: str
    target_status: str  # QUARANTINE 或 WASTE
    reason: str
    actor: str


# ==============================================================================
# API Endpoints
# ==============================================================================

@router.get("/availability")
async def get_blood_availability():
    """
    取得血品可用性總覽 (View 驅動)
    """
    if IS_VERCEL:
        # Demo 模式
        return {
            "success": True,
            "data": [
                {"blood_type": "O+", "unit_type": "PRBC", "available_count": 5, "reserved_count": 2, "physical_valid_count": 7, "expiring_soon_count": 1, "expired_pending_count": 0, "nearest_expiry": "2026-01-15"},
                {"blood_type": "O-", "unit_type": "PRBC", "available_count": 3, "reserved_count": 0, "physical_valid_count": 3, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": "2026-01-20"},
                {"blood_type": "A+", "unit_type": "PRBC", "available_count": 4, "reserved_count": 1, "physical_valid_count": 5, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": "2026-01-18"},
                {"blood_type": "B+", "unit_type": "PRBC", "available_count": 2, "reserved_count": 0, "physical_valid_count": 2, "expiring_soon_count": 1, "expired_pending_count": 0, "nearest_expiry": "2026-01-14"},
            ],
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM v_blood_availability ORDER BY blood_type, unit_type")
        rows = cursor.fetchall()

        return {
            "success": True,
            "data": [dict(row) for row in rows]
        }


@router.get("/units")
async def list_blood_units(
    blood_type: Optional[str] = None,
    unit_type: Optional[str] = None,
    status: Optional[str] = None,
    include_expired: bool = False
):
    """
    列出血袋 (使用 v_blood_unit_status View)
    """
    if IS_VERCEL:
        # Demo 模式
        return {
            "success": True,
            "data": [
                {"id": "BU-20260112-001", "blood_type": "O+", "unit_type": "PRBC", "display_status": "AVAILABLE", "hours_until_expiry": 72, "fifo_priority": 1},
                {"id": "BU-20260112-002", "blood_type": "O+", "unit_type": "PRBC", "display_status": "EXPIRING_SOON", "hours_until_expiry": 48, "fifo_priority": 2},
                {"id": "BU-20260112-003", "blood_type": "A+", "unit_type": "PRBC", "display_status": "RESERVED", "hours_until_expiry": 120, "fifo_priority": 1},
            ],
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM v_blood_unit_status WHERE 1=1"
        params = []

        if blood_type:
            query += " AND blood_type = ?"
            params.append(blood_type)

        if unit_type:
            query += " AND unit_type = ?"
            params.append(unit_type)

        if status:
            query += " AND display_status = ?"
            params.append(status)

        if not include_expired:
            query += " AND display_status != 'EXPIRED'"

        query += " ORDER BY blood_type, unit_type, fifo_priority"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return {
            "success": True,
            "data": [dict(row) for row in rows]
        }


@router.get("/units/{unit_id}")
async def get_blood_unit(unit_id: str):
    """
    取得單一血袋詳情
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM v_blood_unit_status WHERE id = ?", (unit_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="血袋不存在")

        return {
            "success": True,
            "data": dict(row)
        }


@router.post("/units")
async def receive_blood_unit(unit: BloodUnitCreate):
    """
    血袋入庫 (Receive)
    """
    if IS_VERCEL:
        return {"success": True, "id": f"BU-demo-{uuid.uuid4().hex[:8]}", "demo": True}

    # 驗證血型
    if unit.blood_type not in BLOOD_TYPES:
        raise HTTPException(status_code=400, detail=f"無效血型: {unit.blood_type}")

    if unit.unit_type not in UNIT_TYPES:
        raise HTTPException(status_code=400, detail=f"無效血品類型: {unit.unit_type}")

    # 生成 ID
    unit_id = unit.id or f"BU-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO blood_units (
                id, blood_type, unit_type, volume_ml, donation_id,
                collection_date, expiry_date, status, refrigerator_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'AVAILABLE', ?)
        """, (
            unit_id,
            unit.blood_type,
            unit.unit_type,
            unit.volume_ml,
            unit.donation_id,
            unit.collection_date,
            unit.expiry_date,
            unit.refrigerator_id
        ))

        log_blood_event(cursor, unit_id, "RECEIVE", "system", f"入庫: {unit.blood_type} {unit.unit_type}")
        conn.commit()

        return {
            "success": True,
            "id": unit_id,
            "message": f"血袋 {unit_id} 入庫成功"
        }


@router.post("/units/{unit_id}/reserve")
async def reserve_blood_unit(unit_id: str, data: BloodUnitReserve):
    """
    預約血袋 - 原子操作，防止雙重預約
    返回 409 CONFLICT 如果血袋已被預約
    """
    if IS_VERCEL:
        return {"success": True, "demo": True}

    with get_db() as conn:
        cursor = conn.cursor()

        # Guard Update: 只有 AVAILABLE 且未過期才能被預約
        reserve_expires_at = (datetime.now() + timedelta(hours=RESERVE_EXPIRY_HOURS)).isoformat()

        cursor.execute("""
            UPDATE blood_units
            SET status = 'RESERVED',
                reserved_for_order = ?,
                reserved_at = CURRENT_TIMESTAMP,
                reserved_by = ?,
                reserve_expires_at = ?
            WHERE id = ?
            AND status = 'AVAILABLE'
            AND expiry_date > DATE('now', 'localtime')
        """, (data.order_id, data.reserver_id, reserve_expires_at, unit_id))

        if cursor.rowcount == 0:
            # 檢查失敗原因
            cursor.execute("SELECT status, expiry_date FROM blood_units WHERE id = ?", (unit_id,))
            unit = cursor.fetchone()

            if not unit:
                raise HTTPException(status_code=404, detail="血袋不存在")
            elif unit['status'] == 'RESERVED':
                raise HTTPException(status_code=409, detail="CONFLICT: 血袋已被其他訂單預約")
            elif unit['expiry_date'] < date.today().isoformat():
                raise HTTPException(status_code=403, detail="BLOOD_EXPIRED: 血袋已過期")
            else:
                raise HTTPException(status_code=409, detail=f"血袋狀態為 {unit['status']}，無法預約")

        log_blood_event(cursor, unit_id, "RESERVE", data.reserver_id, f"訂單: {data.order_id}", data.order_id)
        conn.commit()

        return {
            "success": True,
            "reserved_until": reserve_expires_at,
            "message": f"血袋 {unit_id} 預約成功"
        }


@router.post("/units/{unit_id}/unreserve")
async def unreserve_blood_unit(unit_id: str, reason: str = None, actor: str = "system"):
    """
    取消血袋預約 (預約後未使用)
    """
    if IS_VERCEL:
        return {"success": True, "demo": True}

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE blood_units
            SET status = 'AVAILABLE',
                reserved_for_order = NULL,
                reserved_at = NULL,
                reserved_by = NULL,
                reserve_expires_at = NULL
            WHERE id = ? AND status = 'RESERVED'
        """, (unit_id,))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=409, detail="血袋非預約狀態")

        log_blood_event(cursor, unit_id, "UNRESERVE", actor, reason)
        conn.commit()

        return {
            "success": True,
            "message": f"血袋 {unit_id} 預約已取消"
        }


@router.post("/units/{unit_id}/issue")
async def issue_blood_unit(unit_id: str, data: BloodUnitIssue):
    """
    發血出庫
    包含效期阻擋 (Layer 3: API 拒絕)
    """
    if IS_VERCEL:
        return {"success": True, "demo": True}

    with get_db() as conn:
        cursor = conn.cursor()

        # 先檢查血袋狀態
        cursor.execute("SELECT * FROM blood_units WHERE id = ?", (unit_id,))
        unit = cursor.fetchone()

        if not unit:
            raise HTTPException(status_code=404, detail="血袋不存在")

        # 效期阻擋 (Layer 3)
        if unit['expiry_date'] < date.today().isoformat():
            log_blood_event(cursor, unit_id, "BLOCK_EXPIRED_ATTEMPT", data.issuer_id,
                          f"嘗試發放過期血袋", data.order_id, severity="WARNING")
            conn.commit()
            raise HTTPException(status_code=403, detail="BLOOD_EXPIRED: 血袋已過期，禁止發放")

        # 驗證狀態轉移
        current_status = unit['status']
        if not validate_status_transition(current_status, 'ISSUED'):
            raise HTTPException(status_code=409, detail=f"無法從 {current_status} 轉移到 ISSUED")

        # 如果是 RESERVED 狀態，檢查是否為同一訂單
        if current_status == 'RESERVED' and unit['reserved_for_order'] != data.order_id:
            raise HTTPException(status_code=409, detail="血袋已被其他訂單預約")

        # 執行出庫
        cursor.execute("""
            UPDATE blood_units
            SET status = 'ISSUED',
                issued_at = CURRENT_TIMESTAMP,
                issued_by = ?,
                issued_to_order = ?
            WHERE id = ?
        """, (data.issuer_id, data.order_id, unit_id))

        log_blood_event(cursor, unit_id, "ISSUE", data.issuer_id, f"訂單: {data.order_id}", data.order_id)
        conn.commit()

        # TODO: 回呼 CIRS (帶 idempotency_key)
        idempotency_key = f"{data.order_id}:{unit_id}:{int(datetime.now().timestamp())}"

        return {
            "success": True,
            "idempotency_key": idempotency_key,
            "message": f"血袋 {unit_id} 已發放"
        }


@router.post("/units/{unit_id}/return")
async def return_blood_unit(unit_id: str, data: BloodUnitReturn):
    """
    血品退庫 (已發出但未使用)
    包含冷鏈檢查
    """
    if IS_VERCEL:
        return {"success": True, "demo": True}

    with get_db() as conn:
        cursor = conn.cursor()

        if data.out_of_refrigerator_minutes > COLD_CHAIN_LIMIT_MINUTES:
            # 冷鏈中斷，不可退回庫存
            cursor.execute("""
                UPDATE blood_units
                SET status = 'WASTE',
                    waste_reason = ?
                WHERE id = ?
            """, (f"冷鏈中斷 ({data.out_of_refrigerator_minutes} 分鐘)", unit_id))

            log_blood_event(
                cursor, unit_id, "WASTE", data.returner_id,
                f"冷鏈中斷 ({data.out_of_refrigerator_minutes} 分鐘)",
                severity="WARNING"
            )
            conn.commit()

            return {
                "success": True,
                "status": "WASTE",
                "warning": f"血袋離開冰箱 {data.out_of_refrigerator_minutes} 分鐘，超過 {COLD_CHAIN_LIMIT_MINUTES} 分鐘限制，已標記為報廢"
            }
        else:
            # 可退回庫存
            cursor.execute("""
                UPDATE blood_units
                SET status = 'AVAILABLE',
                    issued_at = NULL,
                    issued_by = NULL,
                    issued_to_order = NULL
                WHERE id = ? AND status = 'ISSUED'
            """, (unit_id,))

            if cursor.rowcount == 0:
                raise HTTPException(status_code=409, detail="血袋非已發放狀態")

            log_blood_event(cursor, unit_id, "RETURN", data.returner_id, data.reason)
            conn.commit()

            return {
                "success": True,
                "status": "AVAILABLE",
                "message": f"血袋 {unit_id} 已退回庫存"
            }


@router.post("/emergency-release")
async def emergency_release(data: EmergencyRelease):
    """
    緊急發血 - 繞過正常流程 (Break-Glass)
    - 只允許 O 型血
    - 跳過 Order ID 驗證
    - 觸發 CRITICAL 稽核事件
    """
    if IS_VERCEL:
        return {
            "success": True,
            "unit_ids": [f"BU-emergency-{uuid.uuid4().hex[:6]}"],
            "warning": "緊急發血已記錄，請於 24h 內補齊醫囑",
            "demo": True
        }

    # 驗證血型 (只允許 O 型)
    if data.blood_type not in ['O+', 'O-']:
        raise HTTPException(status_code=400, detail="緊急發血僅限 O 型血")

    with get_db() as conn:
        cursor = conn.cursor()

        # 查詢可用血袋 (FIFO)
        cursor.execute("""
            SELECT id FROM blood_units
            WHERE blood_type = ? AND status = 'AVAILABLE'
            AND expiry_date > DATE('now', 'localtime')
            ORDER BY expiry_date ASC
            LIMIT ?
        """, (data.blood_type, data.quantity))

        units = cursor.fetchall()
        if len(units) < data.quantity:
            raise HTTPException(status_code=409, detail=f"庫存不足: 需要 {data.quantity} 袋，只有 {len(units)} 袋")

        unit_ids = [u['id'] for u in units]

        # 原子更新
        for unit_id in unit_ids:
            cursor.execute("""
                UPDATE blood_units
                SET status = 'ISSUED',
                    issued_at = CURRENT_TIMESTAMP,
                    issued_by = ?,
                    is_emergency_release = 1,
                    is_uncrossmatched = 1
                WHERE id = ? AND status = 'AVAILABLE'
            """, (data.requester_id, unit_id))

            if cursor.rowcount == 0:
                conn.rollback()
                raise HTTPException(status_code=409, detail=f"血袋 {unit_id} 狀態已變更")

            # Break-Glass 稽核
            log_blood_event(
                cursor, unit_id, "EMERGENCY_RELEASE", data.requester_id,
                data.reason, severity="CRITICAL"
            )

        conn.commit()

        logger.warning(f"[BREAK-GLASS] 緊急發血: {unit_ids}, 請求者: {data.requester_id}, 原因: {data.reason}")

        return {
            "success": True,
            "unit_ids": unit_ids,
            "warning": "緊急發血已記錄，請於 24h 內補齊醫囑"
        }


@router.post("/batch-update")
async def batch_update_blood(data: BatchUpdate):
    """
    批次更新血袋狀態 (冰箱斷電等情況)
    """
    if IS_VERCEL:
        return {"success": True, "affected_count": 0, "demo": True}

    if data.target_status not in ['QUARANTINE', 'WASTE']:
        raise HTTPException(status_code=400, detail="target_status 必須是 QUARANTINE 或 WASTE")

    with get_db() as conn:
        cursor = conn.cursor()

        # 查詢符合條件的血袋
        cursor.execute("""
            SELECT id FROM blood_units
            WHERE refrigerator_id = ?
            AND status IN ('AVAILABLE', 'RESERVED')
        """, (data.refrigerator_id,))

        units = cursor.fetchall()
        affected_ids = [u['id'] for u in units]

        if not affected_ids:
            return {
                "success": True,
                "affected_count": 0,
                "message": "沒有符合條件的血袋"
            }

        # 批次更新
        placeholders = ','.join('?' * len(affected_ids))
        if data.target_status == 'QUARANTINE':
            cursor.execute(f"""
                UPDATE blood_units
                SET status = 'QUARANTINE',
                    quarantine_reason = ?
                WHERE id IN ({placeholders})
            """, (data.reason, *affected_ids))
        else:
            cursor.execute(f"""
                UPDATE blood_units
                SET status = 'WASTE',
                    waste_reason = ?
                WHERE id IN ({placeholders})
            """, (data.reason, *affected_ids))

        # 批次記錄事件
        for unit_id in affected_ids:
            log_blood_event(
                cursor, unit_id, f"BATCH_{data.target_status}", data.actor,
                data.reason, severity="WARNING"
            )

        conn.commit()

        return {
            "success": True,
            "affected_count": len(affected_ids),
            "affected_ids": affected_ids
        }


@router.get("/events/{unit_id}")
async def get_blood_events(unit_id: str, limit: int = 50):
    """
    取得血袋事件歷史 (Event Sourcing)
    """
    if IS_VERCEL:
        return {"success": True, "data": [], "demo": True}

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM blood_unit_events
            WHERE unit_id = ?
            ORDER BY ts_server DESC
            LIMIT ?
        """, (unit_id, limit))

        rows = cursor.fetchall()
        return {
            "success": True,
            "data": [dict(row) for row in rows]
        }


# ==============================================================================
# Schema Initialization
# ==============================================================================

def init_blood_schema():
    """
    初始化 Blood Bank schema
    如果使用 migration 系統，這個函數可以為空
    """
    logger.info("[Blood] Schema initialization delegated to migration system")
