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
UNIT_TYPES = ['WB', 'PRBC', 'FFP', 'PLT', 'CRYO']  # v2.7.1: WB 全血支援


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


class SimpleBatchReceive(BaseModel):
    """簡易批次入庫 (MIRS Tab 使用)"""
    blood_type: str
    quantity: int = 1
    unit_type: str = "PRBC"
    source: str = "blood_center"  # blood_center | walking_donor
    donor_name: Optional[str] = None
    donor_phone: Optional[str] = None
    remarks: Optional[str] = None
    expiry_days: int = 35  # PRBC 預設 35 天, FFP 365 天


class PendingOrderResolve(BaseModel):
    """補單解除"""
    order_id: str
    resolver_id: str
    notes: Optional[str] = None


# ==============================================================================
# Phase 1-3: Chain of Custody Models (鏈式核對)
# ==============================================================================

class CustodyStep(str):
    """監管鏈步驟類型"""
    RELEASED = "RELEASED"                      # 血庫發血
    TRANSPORT_PICKUP = "TRANSPORT_PICKUP"      # 傳送取血
    TRANSPORT_DELIVERY = "TRANSPORT_DELIVERY"  # 傳送送達
    NURSING_RECEIVED = "NURSING_RECEIVED"      # 護理收血
    TRANSFUSION_STARTED = "TRANSFUSION_STARTED"    # 開始輸血
    TRANSFUSION_COMPLETED = "TRANSFUSION_COMPLETED" # 輸血完成
    TRANSFUSION_STOPPED = "TRANSFUSION_STOPPED"    # 輸血中止 (反應)
    RETURNED = "RETURNED"                      # 退血


CUSTODY_STEPS = [
    "RELEASED", "TRANSPORT_PICKUP", "TRANSPORT_DELIVERY",
    "NURSING_RECEIVED", "TRANSFUSION_STARTED",
    "TRANSFUSION_COMPLETED", "TRANSFUSION_STOPPED", "RETURNED"
]


class BloodVerifyRequest(BaseModel):
    """血袋-病人驗證請求"""
    blood_unit_id: str
    patient_id: str
    patient_blood_type: Optional[str] = None  # 可選，若提供會比對


class CustodyEventCreate(BaseModel):
    """監管鏈事件記錄"""
    step: str  # CustodyStep
    patient_id: str
    actor1_id: str                 # 執行人員 1
    actor2_id: Optional[str] = None  # 覆核人員 2 (雙人核對步驟)
    location: str = "UNKNOWN"      # 地點 (BLOOD_BANK, OR-1, WARD-5A, etc.)
    notes: Optional[str] = None
    # 輸血完成時的額外欄位
    duration_minutes: Optional[int] = None
    reaction: Optional[str] = None  # NONE, MILD, SEVERE


class DualVerificationRequest(BaseModel):
    """雙人核對請求"""
    actor1_id: str
    actor2_id: str
    verification_type: str = "BLOOD_TRANSFUSION"  # 驗證類型


# 血品預設保存期限 (天)
DEFAULT_EXPIRY_DAYS = {
    "WB": 7,     # 全血 - 凝血因子7天內有效 (Fresh Whole Blood)
    "PRBC": 35,
    "FFP": 365,
    "PLT": 5,
    "CRYO": 365,
}


# ==============================================================================
# API Endpoints
# ==============================================================================

@router.get("/availability")
async def get_blood_availability():
    """
    取得血品可用性總覽 (View 驅動)
    v2.5: 自動清理過期預約 (Lazy Cleanup)
    """
    if IS_VERCEL:
        # Demo 模式 - 模擬戰時野戰醫院庫存
        today = datetime.now()
        return {
            "success": True,
            "data": [
                # PRBC (紅血球) - 戰傷主要需求
                {"blood_type": "O+", "unit_type": "PRBC", "available_count": 8, "reserved_count": 3, "physical_valid_count": 11, "expiring_soon_count": 2, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=3)).strftime("%Y-%m-%d")},
                {"blood_type": "O-", "unit_type": "PRBC", "available_count": 4, "reserved_count": 1, "physical_valid_count": 5, "expiring_soon_count": 1, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=5)).strftime("%Y-%m-%d")},
                {"blood_type": "A+", "unit_type": "PRBC", "available_count": 6, "reserved_count": 2, "physical_valid_count": 8, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=12)).strftime("%Y-%m-%d")},
                {"blood_type": "A-", "unit_type": "PRBC", "available_count": 2, "reserved_count": 0, "physical_valid_count": 2, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=18)).strftime("%Y-%m-%d")},
                {"blood_type": "B+", "unit_type": "PRBC", "available_count": 4, "reserved_count": 1, "physical_valid_count": 5, "expiring_soon_count": 1, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=2)).strftime("%Y-%m-%d")},
                {"blood_type": "B-", "unit_type": "PRBC", "available_count": 1, "reserved_count": 0, "physical_valid_count": 1, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=25)).strftime("%Y-%m-%d")},
                {"blood_type": "AB+", "unit_type": "PRBC", "available_count": 2, "reserved_count": 0, "physical_valid_count": 2, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=20)).strftime("%Y-%m-%d")},
                {"blood_type": "AB-", "unit_type": "PRBC", "available_count": 1, "reserved_count": 0, "physical_valid_count": 1, "expiring_soon_count": 0, "expired_pending_count": 1, "nearest_expiry": (today - timedelta(days=1)).strftime("%Y-%m-%d")},
                # FFP (血漿) - 凝血支援
                {"blood_type": "AB+", "unit_type": "FFP", "available_count": 6, "reserved_count": 0, "physical_valid_count": 6, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=180)).strftime("%Y-%m-%d")},
                {"blood_type": "O+", "unit_type": "FFP", "available_count": 3, "reserved_count": 1, "physical_valid_count": 4, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=200)).strftime("%Y-%m-%d")},
                # PLT (血小板) - 短效期
                {"blood_type": "O+", "unit_type": "PLT", "available_count": 2, "reserved_count": 0, "physical_valid_count": 2, "expiring_soon_count": 2, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=2)).strftime("%Y-%m-%d")},
                # WB (全血) - Walking Blood Bank 緊急輸血
                {"blood_type": "O+", "unit_type": "WB", "available_count": 2, "reserved_count": 0, "physical_valid_count": 2, "expiring_soon_count": 0, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=18)).strftime("%Y-%m-%d")},
                {"blood_type": "O-", "unit_type": "WB", "available_count": 1, "reserved_count": 0, "physical_valid_count": 1, "expiring_soon_count": 1, "expired_pending_count": 0, "nearest_expiry": (today + timedelta(days=5)).strftime("%Y-%m-%d")},
            ],
            "demo": True
        }

    with get_db() as conn:
        # v2.5: Lazy cleanup of expired reservations
        release_expired_reservations(conn)

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
        # Demo 模式 - 模擬戰時野戰醫院血袋列表
        today = datetime.now()
        demo_units = [
            # O+ PRBC - 最常用
            {"id": "BU-20260112-A1B2C3", "blood_type": "O+", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "EXPIRING_SOON", "expiry_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"), "hours_until_expiry": 48, "fifo_priority": 1},
            {"id": "BU-20260112-D4E5F6", "blood_type": "O+", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "AVAILABLE", "expiry_date": (today + timedelta(days=8)).strftime("%Y-%m-%d"), "hours_until_expiry": 192, "fifo_priority": 2},
            {"id": "BU-20260111-G7H8I9", "blood_type": "O+", "unit_type": "PRBC", "volume_ml": 250, "status": "RESERVED", "display_status": "RESERVED", "expiry_date": (today + timedelta(days=15)).strftime("%Y-%m-%d"), "hours_until_expiry": 360, "fifo_priority": 3, "reserved_for_order": "ORD-2026-0001"},
            # O- PRBC - 萬能血
            {"id": "BU-20260110-J1K2L3", "blood_type": "O-", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "AVAILABLE", "expiry_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"), "hours_until_expiry": 120, "fifo_priority": 1},
            {"id": "BU-20260109-M4N5O6", "blood_type": "O-", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "EXPIRING_SOON", "expiry_date": (today + timedelta(days=3)).strftime("%Y-%m-%d"), "hours_until_expiry": 72, "fifo_priority": 2, "is_emergency_release": 1},
            # A+ PRBC
            {"id": "BU-20260112-P7Q8R9", "blood_type": "A+", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "AVAILABLE", "expiry_date": (today + timedelta(days=12)).strftime("%Y-%m-%d"), "hours_until_expiry": 288, "fifo_priority": 1},
            {"id": "BU-20260108-S1T2U3", "blood_type": "A+", "unit_type": "PRBC", "volume_ml": 250, "status": "RESERVED", "display_status": "RESERVED", "expiry_date": (today + timedelta(days=20)).strftime("%Y-%m-%d"), "hours_until_expiry": 480, "fifo_priority": 2, "reserved_for_order": "ORD-2026-0002"},
            # B+ PRBC
            {"id": "BU-20260111-V4W5X6", "blood_type": "B+", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "EXPIRING_SOON", "expiry_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"), "hours_until_expiry": 48, "fifo_priority": 1},
            # AB+ FFP - 萬能血漿
            {"id": "BU-20260101-Y7Z8A9", "blood_type": "AB+", "unit_type": "FFP", "volume_ml": 200, "status": "AVAILABLE", "display_status": "AVAILABLE", "expiry_date": (today + timedelta(days=180)).strftime("%Y-%m-%d"), "hours_until_expiry": 4320, "fifo_priority": 1},
            # PLT - 短效期
            {"id": "BU-20260112-B1C2D3", "blood_type": "O+", "unit_type": "PLT", "volume_ml": 50, "status": "AVAILABLE", "display_status": "EXPIRING_SOON", "expiry_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"), "hours_until_expiry": 48, "fifo_priority": 1},
            # WB (全血) - Walking Blood Bank 緊急來源
            {"id": "BU-20260113-WB001", "blood_type": "O+", "unit_type": "WB", "volume_ml": 450, "status": "AVAILABLE", "display_status": "AVAILABLE", "expiry_date": (today + timedelta(days=18)).strftime("%Y-%m-%d"), "hours_until_expiry": 432, "fifo_priority": 1},
            {"id": "BU-20260113-WB002", "blood_type": "O+", "unit_type": "WB", "volume_ml": 450, "status": "AVAILABLE", "display_status": "AVAILABLE", "expiry_date": (today + timedelta(days=20)).strftime("%Y-%m-%d"), "hours_until_expiry": 480, "fifo_priority": 2},
            {"id": "BU-20260112-WB003", "blood_type": "O-", "unit_type": "WB", "volume_ml": 450, "status": "AVAILABLE", "display_status": "EXPIRING_SOON", "expiry_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"), "hours_until_expiry": 120, "fifo_priority": 1, "is_emergency_release": 1},
            # 已過期等待報廢
            {"id": "BU-20260105-E4F5G6", "blood_type": "AB-", "unit_type": "PRBC", "volume_ml": 250, "status": "AVAILABLE", "display_status": "EXPIRED", "expiry_date": (today - timedelta(days=1)).strftime("%Y-%m-%d"), "hours_until_expiry": -24, "fifo_priority": 99},
        ]

        # Filter based on query params
        result = demo_units
        if blood_type:
            result = [u for u in result if u["blood_type"] == blood_type]
        if unit_type:
            result = [u for u in result if u["unit_type"] == unit_type]
        if status:
            result = [u for u in result if u["display_status"] == status]
        if not include_expired:
            result = [u for u in result if u["display_status"] != "EXPIRED"]

        return {
            "success": True,
            "data": result,
            "demo": True
        }

    with get_db() as conn:
        # v2.5: Lazy cleanup of expired reservations
        release_expired_reservations(conn)

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


@router.post("/units/batch")
async def batch_receive_blood(data: SimpleBatchReceive):
    """
    簡易批次入庫 (MIRS Tab 使用)
    - 自動生成血袋 ID
    - 自動計算效期 (依血品類型)
    - 支援 Walking Blood Bank 來源記錄
    """
    if IS_VERCEL:
        return {
            "success": True,
            "count": data.quantity,
            "ids": [f"BU-demo-{uuid.uuid4().hex[:8]}" for _ in range(data.quantity)],
            "demo": True
        }

    # 驗證血型
    if data.blood_type not in BLOOD_TYPES:
        raise HTTPException(status_code=400, detail=f"無效血型: {data.blood_type}")

    if data.unit_type not in UNIT_TYPES:
        raise HTTPException(status_code=400, detail=f"無效血品類型: {data.unit_type}")

    if data.quantity < 1 or data.quantity > 50:
        raise HTTPException(status_code=400, detail="數量必須在 1-50 之間")

    # 計算效期
    expiry_days = data.expiry_days or DEFAULT_EXPIRY_DAYS.get(data.unit_type, 35)
    expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
    collection_date = datetime.now().strftime("%Y-%m-%d")

    created_ids = []

    with get_db() as conn:
        cursor = conn.cursor()

        for i in range(data.quantity):
            unit_id = f"BU-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

            # Walking Blood Bank 來源記錄 + 備註
            metadata = {"source": data.source}
            if data.remarks:
                metadata["remarks"] = data.remarks
            if data.source == "walking_donor":
                if data.donor_name:
                    metadata["donor_name"] = data.donor_name
                if data.donor_phone:
                    metadata["donor_phone"] = data.donor_phone

            cursor.execute("""
                INSERT INTO blood_units (
                    id, blood_type, unit_type, volume_ml,
                    collection_date, expiry_date, status
                ) VALUES (?, ?, ?, 250, ?, ?, 'AVAILABLE')
            """, (
                unit_id,
                data.blood_type,
                data.unit_type,
                collection_date,
                expiry_date
            ))

            # 記錄事件 (metadata 包含來源和備註)
            log_blood_event(
                cursor, unit_id, "RECEIVE", "mirs-tab",
                f"簡易入庫: {data.blood_type} {data.unit_type}",
                metadata=metadata
            )

            created_ids.append(unit_id)

        conn.commit()

    return {
        "success": True,
        "count": len(created_ids),
        "ids": created_ids,
        "blood_type": data.blood_type,
        "expiry_date": expiry_date,
        "message": f"成功入庫 {len(created_ids)} 袋 {data.blood_type} 血品"
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

        # v2.4: Create pending order for follow-up
        pending_id = f"PO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
        deadline = (datetime.now() + timedelta(hours=24)).isoformat()

        cursor.execute("""
            INSERT INTO pending_orders (
                id, type, unit_ids, requester_id, reason, deadline, status, created_at
            ) VALUES (?, 'EMERGENCY_RELEASE', ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP)
        """, (pending_id, json.dumps(unit_ids), data.requester_id, data.reason, deadline))
        conn.commit()

        return {
            "success": True,
            "unit_ids": unit_ids,
            "pending_order_id": pending_id,
            "deadline": deadline,
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
# P4: Pending Order Tracking (待補單追蹤)
# ==============================================================================

@router.get("/pending-orders")
async def list_pending_orders(
    status: str = "PENDING",
    include_overdue: bool = True
):
    """
    列出待補單 (緊急發血後需補開醫囑)
    v2.4: P4 新增
    """
    if IS_VERCEL:
        # Demo 模式
        now = datetime.now()
        return {
            "success": True,
            "data": [
                {
                    "id": "PO-20260112-A1B2",
                    "type": "EMERGENCY_RELEASE",
                    "unit_ids": ["BU-20260112-X1Y2Z3"],
                    "requester_id": "blood-pwa",
                    "reason": "大量傷患湧入",
                    "deadline": (now + timedelta(hours=12)).isoformat(),
                    "status": "PENDING",
                    "is_overdue": False,
                    "hours_remaining": 12,
                    "created_at": (now - timedelta(hours=12)).isoformat()
                },
                {
                    "id": "PO-20260111-C3D4",
                    "type": "EMERGENCY_RELEASE",
                    "unit_ids": ["BU-20260111-A1B2C3", "BU-20260111-D4E5F6"],
                    "requester_id": "blood-pwa",
                    "reason": "休克病患緊急輸血",
                    "deadline": (now - timedelta(hours=6)).isoformat(),
                    "status": "PENDING",
                    "is_overdue": True,
                    "hours_remaining": -6,
                    "created_at": (now - timedelta(hours=30)).isoformat()
                }
            ],
            "overdue_count": 1,
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM pending_orders WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY deadline ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        now = datetime.now()
        result = []
        overdue_count = 0

        for row in rows:
            item = dict(row)
            deadline = datetime.fromisoformat(item['deadline'])
            item['is_overdue'] = now > deadline
            item['hours_remaining'] = int((deadline - now).total_seconds() / 3600)

            if item['is_overdue']:
                overdue_count += 1

            # Parse unit_ids JSON
            if item.get('unit_ids'):
                item['unit_ids'] = json.loads(item['unit_ids'])

            if include_overdue or not item['is_overdue']:
                result.append(item)

        return {
            "success": True,
            "data": result,
            "overdue_count": overdue_count
        }


@router.post("/pending-orders/{order_id}/resolve")
async def resolve_pending_order(order_id: str, data: PendingOrderResolve):
    """
    補單完成 - 解除待補單狀態
    v2.4: P4 新增
    """
    if IS_VERCEL:
        return {"success": True, "demo": True}

    with get_db() as conn:
        cursor = conn.cursor()

        # 更新待補單狀態
        cursor.execute("""
            UPDATE pending_orders
            SET status = 'RESOLVED',
                resolved_order_id = ?,
                resolved_by = ?,
                resolved_at = CURRENT_TIMESTAMP,
                resolve_notes = ?
            WHERE id = ? AND status = 'PENDING'
        """, (data.order_id, data.resolver_id, data.notes, order_id))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="待補單不存在或已解除")

        # 記錄事件
        cursor.execute("SELECT unit_ids FROM pending_orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()
        if row and row['unit_ids']:
            unit_ids = json.loads(row['unit_ids'])
            for unit_id in unit_ids:
                log_blood_event(
                    cursor, unit_id, "PENDING_ORDER_RESOLVED", data.resolver_id,
                    f"補單完成: {data.order_id}", data.order_id
                )

        conn.commit()

        return {
            "success": True,
            "message": f"待補單 {order_id} 已解除"
        }


@router.get("/pending-orders/summary")
async def get_pending_orders_summary():
    """
    待補單摘要 (Dashboard 用)
    v2.4: P4 新增
    """
    if IS_VERCEL:
        return {
            "success": True,
            "pending_count": 2,
            "overdue_count": 1,
            "oldest_overdue_hours": 6,
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN deadline < datetime('now', 'localtime') THEN 1 ELSE 0 END) as overdue
            FROM pending_orders
            WHERE status = 'PENDING'
        """)

        row = cursor.fetchone()
        pending_count = row['total'] or 0
        overdue_count = row['overdue'] or 0

        # 最久過期的時數
        oldest_overdue_hours = 0
        if overdue_count > 0:
            cursor.execute("""
                SELECT MIN(deadline) as oldest
                FROM pending_orders
                WHERE status = 'PENDING' AND deadline < datetime('now', 'localtime')
            """)
            oldest_row = cursor.fetchone()
            if oldest_row and oldest_row['oldest']:
                oldest = datetime.fromisoformat(oldest_row['oldest'])
                oldest_overdue_hours = int((datetime.now() - oldest).total_seconds() / 3600)

        return {
            "success": True,
            "pending_count": pending_count,
            "overdue_count": overdue_count,
            "oldest_overdue_hours": oldest_overdue_hours
        }


# ==============================================================================
# P4: Reserve Timeout (預約逾時自動釋放)
# ==============================================================================

def release_expired_reservations(conn: sqlite3.Connection = None) -> dict:
    """
    釋放過期的預約血袋
    v2.5: P4 自動釋放機制

    Returns:
        dict: { released_count, unit_ids }
    """
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True

    cursor = conn.cursor()

    # 找出過期的預約
    cursor.execute("""
        SELECT id, blood_type, reserved_for_order, reserved_by, reserve_expires_at
        FROM blood_units
        WHERE status = 'RESERVED'
          AND reserve_expires_at IS NOT NULL
          AND reserve_expires_at < datetime('now', 'localtime')
    """)

    expired_units = cursor.fetchall()
    released_ids = []

    for unit in expired_units:
        unit_id = unit['id']

        # 更新狀態為 AVAILABLE
        cursor.execute("""
            UPDATE blood_units
            SET status = 'AVAILABLE',
                reserved_for_order = NULL,
                reserved_at = NULL,
                reserved_by = NULL,
                reserve_expires_at = NULL
            WHERE id = ?
        """, (unit_id,))

        # 記錄事件
        log_blood_event(
            cursor, unit_id, "RESERVE_TIMEOUT", "system",
            f"預約逾時自動釋放 (原訂單: {unit['reserved_for_order']}, 預約者: {unit['reserved_by']})",
            unit['reserved_for_order'],
            severity="WARNING"
        )

        released_ids.append(unit_id)
        logger.info(f"[Blood] Released expired reservation: {unit_id}")

    if released_ids:
        conn.commit()
        logger.info(f"[Blood] Released {len(released_ids)} expired reservations")

    if close_conn:
        conn.close()

    return {
        "released_count": len(released_ids),
        "unit_ids": released_ids
    }


@router.post("/reserve-timeout/process")
async def process_reserve_timeout():
    """
    手動觸發預約逾時清理
    v2.5: P4 新增 (Admin 用)
    """
    if IS_VERCEL:
        return {
            "success": True,
            "released_count": 0,
            "unit_ids": [],
            "demo": True,
            "message": "Demo 模式無實際清理"
        }

    result = release_expired_reservations()

    return {
        "success": True,
        **result,
        "message": f"已釋放 {result['released_count']} 筆過期預約"
    }


@router.get("/reserve-timeout/status")
async def get_reserve_timeout_status():
    """
    查詢即將過期的預約
    v2.5: P4 新增
    """
    if IS_VERCEL:
        now = datetime.now()
        return {
            "success": True,
            "data": [
                {
                    "id": "BU-20260111-G7H8I9",
                    "blood_type": "O+",
                    "reserved_for_order": "ORD-2026-0001",
                    "reserve_expires_at": (now - timedelta(minutes=30)).isoformat(),
                    "is_expired": True,
                    "hours_remaining": -0.5
                },
                {
                    "id": "BU-20260112-X1Y2Z3",
                    "blood_type": "A+",
                    "reserved_for_order": "ORD-2026-0003",
                    "reserve_expires_at": (now + timedelta(hours=2)).isoformat(),
                    "is_expired": False,
                    "hours_remaining": 2
                }
            ],
            "expired_count": 1,
            "expiring_soon_count": 1,
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, blood_type, unit_type, reserved_for_order, reserved_by,
                   reserved_at, reserve_expires_at
            FROM blood_units
            WHERE status = 'RESERVED'
              AND reserve_expires_at IS NOT NULL
            ORDER BY reserve_expires_at ASC
        """)

        rows = cursor.fetchall()
        now = datetime.now()

        result = []
        expired_count = 0
        expiring_soon_count = 0  # < 1 hour

        for row in rows:
            item = dict(row)
            expires_at = datetime.fromisoformat(item['reserve_expires_at'])
            is_expired = now > expires_at
            hours_remaining = (expires_at - now).total_seconds() / 3600

            item['is_expired'] = is_expired
            item['hours_remaining'] = round(hours_remaining, 1)

            if is_expired:
                expired_count += 1
            elif hours_remaining < 1:
                expiring_soon_count += 1

            result.append(item)

        return {
            "success": True,
            "data": result,
            "expired_count": expired_count,
            "expiring_soon_count": expiring_soon_count
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


# ==============================================================================
# Phase 1: Blood Verification API (血袋-病人驗證)
# ==============================================================================

# 血型相容性表 (接收者 -> 可接受的捐贈者)
BLOOD_TYPE_COMPATIBILITY = {
    'O-': ['O-'],
    'O+': ['O-', 'O+'],
    'A-': ['O-', 'A-'],
    'A+': ['O-', 'O+', 'A-', 'A+'],
    'B-': ['O-', 'B-'],
    'B+': ['O-', 'O+', 'B-', 'B+'],
    'AB-': ['O-', 'A-', 'B-', 'AB-'],
    'AB+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],  # 萬能受血者
}


def check_blood_compatibility(donor_type: str, recipient_type: str) -> bool:
    """檢查血型相容性"""
    compatible_donors = BLOOD_TYPE_COMPATIBILITY.get(recipient_type, [])
    return donor_type in compatible_donors


@router.post("/verify")
async def verify_blood_unit(data: BloodVerifyRequest):
    """
    Phase 1: 驗證血袋與病人是否匹配

    檢查項目:
    1. 血袋是否存在
    2. 血袋是否已過期
    3. 血型是否相容 (若提供病人血型)
    4. 血袋狀態是否可用

    Returns:
        match: bool - 是否通過所有驗證
        details: dict - 各項驗證結果
        warnings: list - 警告訊息 (非阻擋性)
    """
    if IS_VERCEL:
        # Demo 模式 - 模擬驗證結果
        demo_units = {
            "BU-20260112-A1B2C3": {"blood_type": "O+", "status": "AVAILABLE", "expiry_date": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")},
            "BU-20260112-D4E5F6": {"blood_type": "O+", "status": "AVAILABLE", "expiry_date": (datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d")},
            "BU-20260110-J1K2L3": {"blood_type": "O-", "status": "AVAILABLE", "expiry_date": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")},
            "BU-20260112-P7Q8R9": {"blood_type": "A+", "status": "AVAILABLE", "expiry_date": (datetime.now() + timedelta(days=12)).strftime("%Y-%m-%d")},
        }

        unit = demo_units.get(data.blood_unit_id)
        if not unit:
            return {
                "match": False,
                "details": {
                    "unit_exists": False,
                    "blood_type_compatible": False,
                    "not_expired": False,
                    "status_valid": False
                },
                "errors": ["血袋不存在"],
                "warnings": [],
                "demo": True
            }

        # 檢查血型相容性
        blood_type_compatible = True
        if data.patient_blood_type:
            blood_type_compatible = check_blood_compatibility(unit["blood_type"], data.patient_blood_type)

        # 檢查效期
        expiry = datetime.strptime(unit["expiry_date"], "%Y-%m-%d")
        not_expired = expiry > datetime.now()
        hours_until_expiry = (expiry - datetime.now()).total_seconds() / 3600

        warnings = []
        if hours_until_expiry < 24:
            warnings.append(f"血袋即將過期 (剩餘 {int(hours_until_expiry)} 小時)")

        errors = []
        if not blood_type_compatible:
            errors.append(f"血型不相容: 血袋 {unit['blood_type']} vs 病人 {data.patient_blood_type}")
        if not not_expired:
            errors.append("血袋已過期")

        return {
            "match": blood_type_compatible and not_expired,
            "details": {
                "unit_exists": True,
                "blood_type_compatible": blood_type_compatible,
                "not_expired": not_expired,
                "status_valid": True,
                "unit_blood_type": unit["blood_type"],
                "patient_blood_type": data.patient_blood_type,
                "expiry_date": unit["expiry_date"],
                "hours_until_expiry": int(hours_until_expiry)
            },
            "errors": errors,
            "warnings": warnings,
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        # 取得血袋資訊
        cursor.execute("""
            SELECT id, blood_type, unit_type, status, expiry_date, volume_ml,
                   reserved_for_order, issued_to_order
            FROM blood_units WHERE id = ?
        """, (data.blood_unit_id,))

        unit = cursor.fetchone()

        if not unit:
            return {
                "match": False,
                "details": {
                    "unit_exists": False,
                    "blood_type_compatible": False,
                    "not_expired": False,
                    "status_valid": False
                },
                "errors": ["血袋不存在"],
                "warnings": []
            }

        unit = dict(unit)
        errors = []
        warnings = []

        # 1. 檢查效期
        expiry = datetime.strptime(unit["expiry_date"], "%Y-%m-%d")
        not_expired = expiry > datetime.now()
        hours_until_expiry = (expiry - datetime.now()).total_seconds() / 3600

        if not not_expired:
            errors.append("血袋已過期")
        elif hours_until_expiry < 24:
            warnings.append(f"血袋即將過期 (剩餘 {int(hours_until_expiry)} 小時)")

        # 2. 檢查血型相容性
        blood_type_compatible = True
        if data.patient_blood_type:
            blood_type_compatible = check_blood_compatibility(unit["blood_type"], data.patient_blood_type)
            if not blood_type_compatible:
                errors.append(f"血型不相容: 血袋 {unit['blood_type']} vs 病人 {data.patient_blood_type}")

        # 3. 檢查狀態
        valid_statuses = ['AVAILABLE', 'RESERVED', 'ISSUED']
        status_valid = unit["status"] in valid_statuses
        if not status_valid:
            errors.append(f"血袋狀態不可用: {unit['status']}")

        match = (not_expired and blood_type_compatible and status_valid)

        # 記錄驗證事件
        log_blood_event(
            cursor, data.blood_unit_id,
            "VERIFY_PASS" if match else "VERIFY_FAIL",
            data.patient_id,
            f"病人: {data.patient_id}, 血型比對: {blood_type_compatible}",
            metadata={
                "patient_blood_type": data.patient_blood_type,
                "match": match,
                "errors": errors
            }
        )
        conn.commit()

        return {
            "match": match,
            "details": {
                "unit_exists": True,
                "blood_type_compatible": blood_type_compatible,
                "not_expired": not_expired,
                "status_valid": status_valid,
                "unit_blood_type": unit["blood_type"],
                "unit_type": unit["unit_type"],
                "volume_ml": unit["volume_ml"],
                "patient_blood_type": data.patient_blood_type,
                "expiry_date": unit["expiry_date"],
                "hours_until_expiry": int(hours_until_expiry),
                "current_status": unit["status"]
            },
            "errors": errors,
            "warnings": warnings
        }


# ==============================================================================
# Phase 2-3: Chain of Custody API (監管鏈追蹤)
# ==============================================================================

@router.post("/units/{unit_id}/custody")
async def record_custody_event(unit_id: str, data: CustodyEventCreate):
    """
    Phase 2-3: 記錄監管鏈事件

    每個步驟記錄:
    - 誰 (actor1_id, actor2_id)
    - 何時 (timestamp)
    - 在哪裡 (location)
    - 做了什麼 (step)
    - 驗證結果 (自動執行)
    """
    # 驗證步驟類型
    if data.step not in CUSTODY_STEPS:
        raise HTTPException(status_code=400, detail=f"無效的監管鏈步驟: {data.step}")

    # 雙人核對步驟需要 actor2_id
    dual_check_steps = ["RELEASED", "NURSING_RECEIVED", "TRANSFUSION_STARTED"]
    if data.step in dual_check_steps and not data.actor2_id:
        raise HTTPException(status_code=400, detail=f"步驟 {data.step} 需要雙人核對 (actor2_id)")

    if IS_VERCEL:
        # Demo 模式
        event_id = f"CE-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
        return {
            "success": True,
            "event_id": event_id,
            "step": data.step,
            "timestamp": datetime.now().isoformat(),
            "verification": {
                "blood_type_match": True,
                "patient_match": True,
                "expiry_valid": True
            },
            "next_step": get_next_custody_step(data.step),
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        # 取得血袋資訊
        cursor.execute("SELECT * FROM blood_units WHERE id = ?", (unit_id,))
        unit = cursor.fetchone()

        if not unit:
            raise HTTPException(status_code=404, detail="血袋不存在")

        unit = dict(unit)

        # 執行驗證
        verification = {
            "blood_type_match": True,  # 需要病人血型資訊才能驗證
            "patient_match": True,      # 假設 patient_id 正確
            "expiry_valid": unit["expiry_date"] > datetime.now().strftime("%Y-%m-%d")
        }

        if not verification["expiry_valid"]:
            raise HTTPException(status_code=403, detail="血袋已過期，無法繼續流程")

        # 記錄事件
        event_id = f"CE-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
        timestamp = datetime.now().isoformat()

        metadata = {
            "step": data.step,
            "patient_id": data.patient_id,
            "actor1_id": data.actor1_id,
            "actor2_id": data.actor2_id,
            "location": data.location,
            "verification": verification,
            "notes": data.notes
        }

        # 輸血完成的額外資訊
        if data.step == "TRANSFUSION_COMPLETED":
            metadata["duration_minutes"] = data.duration_minutes
            metadata["reaction"] = data.reaction

        # 儲存到 blood_custody_events 表 (如果存在) 或 blood_unit_events
        log_blood_event(
            cursor, unit_id,
            f"CUSTODY_{data.step}",
            data.actor1_id,
            f"監管鏈: {data.step} @ {data.location}",
            metadata=metadata
        )

        # 更新血袋狀態 (根據步驟)
        status_updates = {
            "RELEASED": "ISSUED",
            "NURSING_RECEIVED": "ISSUED",  # 保持 ISSUED
            "TRANSFUSION_STARTED": "ISSUED",  # 保持 ISSUED (可加新狀態 TRANSFUSING)
            "TRANSFUSION_COMPLETED": "ISSUED",  # 可加新狀態 TRANSFUSED
            "RETURNED": "AVAILABLE"
        }

        if data.step in status_updates:
            new_status = status_updates[data.step]
            if unit["status"] != new_status:
                # 驗證狀態轉移
                if data.step == "RELEASED" and unit["status"] not in ["AVAILABLE", "RESERVED"]:
                    raise HTTPException(status_code=409, detail=f"血袋狀態 {unit['status']} 無法發血")

                cursor.execute("""
                    UPDATE blood_units SET status = ? WHERE id = ?
                """, (new_status, unit_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "step": data.step,
            "timestamp": timestamp,
            "verification": verification,
            "next_step": get_next_custody_step(data.step),
            "actors": {
                "actor1": data.actor1_id,
                "actor2": data.actor2_id
            }
        }


def get_next_custody_step(current_step: str) -> Optional[str]:
    """取得下一個監管鏈步驟"""
    step_order = [
        "RELEASED", "TRANSPORT_PICKUP", "TRANSPORT_DELIVERY",
        "NURSING_RECEIVED", "TRANSFUSION_STARTED", "TRANSFUSION_COMPLETED"
    ]

    if current_step in ["TRANSFUSION_COMPLETED", "TRANSFUSION_STOPPED", "RETURNED"]:
        return None  # 終點

    try:
        idx = step_order.index(current_step)
        if idx < len(step_order) - 1:
            return step_order[idx + 1]
    except ValueError:
        pass

    return None


@router.get("/units/{unit_id}/custody")
async def get_custody_chain(unit_id: str):
    """
    Phase 3: 取得血袋完整監管鏈歷史

    返回時間軸格式的監管鏈事件
    """
    if IS_VERCEL:
        # Demo 模式 - 模擬監管鏈
        now = datetime.now()
        return {
            "success": True,
            "unit_id": unit_id,
            "blood_type": "O+",
            "patient_id": "P-DEMO-001",
            "patient_name": "王大明",
            "chain": [
                {
                    "step": "RELEASED",
                    "timestamp": (now - timedelta(minutes=45)).isoformat(),
                    "actor1": {"id": "BB-001", "name": "陳小明"},
                    "actor2": {"id": "BB-002", "name": "林小華"},
                    "location": "血庫",
                    "verification": {"blood_type_match": True, "expiry_valid": True}
                },
                {
                    "step": "TRANSPORT_PICKUP",
                    "timestamp": (now - timedelta(minutes=40)).isoformat(),
                    "actor1": {"id": "TR-015", "name": "王傳送"},
                    "actor2": None,
                    "location": "血庫",
                    "verification": {}
                },
                {
                    "step": "NURSING_RECEIVED",
                    "timestamp": (now - timedelta(minutes=30)).isoformat(),
                    "actor1": {"id": "RN-042", "name": "張護理"},
                    "actor2": {"id": "RN-018", "name": "李護理"},
                    "location": "OR-3 手術室",
                    "verification": {"blood_type_match": True, "patient_match": True}
                },
                {
                    "step": "TRANSFUSION_STARTED",
                    "timestamp": (now - timedelta(minutes=15)).isoformat(),
                    "actor1": {"id": "RN-042", "name": "張護理"},
                    "actor2": {"id": "MD-007", "name": "陳醫師"},
                    "location": "OR-3 手術室",
                    "verification": {"blood_type_match": True, "patient_match": True, "bedside_confirm": True}
                }
            ],
            "current_step": "TRANSFUSION_STARTED",
            "elapsed_minutes": 45,
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        # 取得血袋資訊
        cursor.execute("SELECT * FROM blood_units WHERE id = ?", (unit_id,))
        unit = cursor.fetchone()

        if not unit:
            raise HTTPException(status_code=404, detail="血袋不存在")

        unit = dict(unit)

        # 取得監管鏈事件
        cursor.execute("""
            SELECT * FROM blood_unit_events
            WHERE unit_id = ? AND event_type LIKE 'CUSTODY_%'
            ORDER BY ts_server ASC
        """, (unit_id,))

        events = cursor.fetchall()

        chain = []
        current_step = None
        first_timestamp = None
        patient_id = None

        for event in events:
            event = dict(event)
            metadata = json.loads(event.get("metadata") or "{}")

            step = metadata.get("step") or event["event_type"].replace("CUSTODY_", "")
            current_step = step

            if not first_timestamp:
                first_timestamp = event["ts_server"]

            if not patient_id and metadata.get("patient_id"):
                patient_id = metadata["patient_id"]

            chain.append({
                "step": step,
                "timestamp": datetime.fromtimestamp(event["ts_server"]).isoformat() if event["ts_server"] else None,
                "actor1": {"id": metadata.get("actor1_id"), "name": None},
                "actor2": {"id": metadata.get("actor2_id"), "name": None} if metadata.get("actor2_id") else None,
                "location": metadata.get("location"),
                "verification": metadata.get("verification", {}),
                "notes": metadata.get("notes"),
                "duration_minutes": metadata.get("duration_minutes"),
                "reaction": metadata.get("reaction")
            })

        # 計算經過時間
        elapsed_minutes = 0
        if first_timestamp:
            elapsed_minutes = int((datetime.now().timestamp() - first_timestamp) / 60)

        return {
            "success": True,
            "unit_id": unit_id,
            "blood_type": unit["blood_type"],
            "unit_type": unit["unit_type"],
            "patient_id": patient_id,
            "chain": chain,
            "current_step": current_step,
            "elapsed_minutes": elapsed_minutes
        }


@router.get("/custody/pending")
async def get_pending_custody(
    location: Optional[str] = None,
    step: Optional[str] = None
):
    """
    Phase 3: 取得待完成的監管鏈 (如：已發血但尚未開始輸血)

    用於各 PWA 顯示待處理項目
    """
    if IS_VERCEL:
        # Demo 模式
        now = datetime.now()
        return {
            "success": True,
            "data": [
                {
                    "unit_id": "BU-20260112-A1B2C3",
                    "blood_type": "O+",
                    "patient_id": "P-DEMO-001",
                    "patient_name": "王大明",
                    "current_step": "NURSING_RECEIVED",
                    "next_step": "TRANSFUSION_STARTED",
                    "location": "OR-3",
                    "elapsed_minutes": 15,
                    "released_at": (now - timedelta(minutes=30)).isoformat()
                },
                {
                    "unit_id": "BU-20260112-D4E5F6",
                    "blood_type": "O+",
                    "patient_id": "P-DEMO-001",
                    "patient_name": "王大明",
                    "current_step": "RELEASED",
                    "next_step": "TRANSPORT_PICKUP",
                    "location": "BLOOD_BANK",
                    "elapsed_minutes": 5,
                    "released_at": (now - timedelta(minutes=5)).isoformat()
                }
            ],
            "demo": True
        }

    with get_db() as conn:
        cursor = conn.cursor()

        # 查詢已發血但未完成輸血的血袋
        cursor.execute("""
            SELECT bu.id, bu.blood_type, bu.unit_type, bu.status, bu.issued_at,
                   bue.metadata, bue.ts_server
            FROM blood_units bu
            LEFT JOIN blood_unit_events bue ON bu.id = bue.unit_id
                AND bue.event_type LIKE 'CUSTODY_%'
            WHERE bu.status = 'ISSUED'
            ORDER BY bu.issued_at DESC
        """)

        rows = cursor.fetchall()

        # 處理結果 (按 unit_id 分組，取最新事件)
        units_map = {}
        for row in rows:
            row = dict(row)
            unit_id = row["id"]

            if unit_id not in units_map:
                units_map[unit_id] = {
                    "unit_id": unit_id,
                    "blood_type": row["blood_type"],
                    "unit_type": row["unit_type"],
                    "current_step": None,
                    "next_step": None,
                    "location": None,
                    "elapsed_minutes": 0,
                    "released_at": row["issued_at"]
                }

            if row.get("metadata"):
                metadata = json.loads(row["metadata"])
                step = metadata.get("step")
                if step:
                    units_map[unit_id]["current_step"] = step
                    units_map[unit_id]["next_step"] = get_next_custody_step(step)
                    units_map[unit_id]["location"] = metadata.get("location")

                    if row.get("ts_server"):
                        elapsed = int((datetime.now().timestamp() - row["ts_server"]) / 60)
                        units_map[unit_id]["elapsed_minutes"] = elapsed

        result = list(units_map.values())

        # 過濾
        if location:
            result = [r for r in result if r.get("location") == location]
        if step:
            result = [r for r in result if r.get("current_step") == step]

        # 只返回未完成的
        result = [r for r in result if r.get("next_step") is not None]

        return {
            "success": True,
            "data": result
        }
