"""
MIRS Inventory Engine API v1.0
Sprint 1: 資源消費端點 (供 CIRS 閉環執行使用)

此模組實作 xIRS_ARCHITECTURE_FINAL.md 定義的:
- POST /api/inventory/consume - 消費庫存 (from CIRS resource_intent)
- GET /api/inventory/engine/status - 引擎狀態
"""

import logging
import hashlib
import hmac
import time
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, HTTPException, Depends

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inventory", tags=["Inventory Engine"])

# ============================================================
# Pydantic Models
# ============================================================

class ConsumeItem(BaseModel):
    """單一消費項目"""
    item_code: str = Field(..., description="物品代碼")
    quantity: float = Field(..., gt=0, description="數量")
    lot: Optional[str] = Field(None, description="批號")
    blood_unit_id: Optional[str] = Field(None, description="血品 unit_id")


class ConsumeRequest(BaseModel):
    """
    消費請求 (from CIRS resource_intent)

    CIRS 在 execution 建立後，會產生 resource_intent 並呼叫此 API
    """
    intent_id: str = Field(..., description="resource_intent ID (來自 CIRS)")
    execution_id: str = Field(..., description="關聯的 execution ID")
    person_id: Optional[str] = Field(None, description="病患 ID")
    items: List[ConsumeItem] = Field(..., min_length=1, description="消費項目清單")
    station_id: str = Field(..., description="來源站點 ID")
    operator: Optional[str] = Field(None, description="執行者")
    timestamp: Optional[int] = Field(None, description="執行時間 (ms)")


class ConsumeResult(BaseModel):
    """單一項目消費結果"""
    item_code: str
    status: str  # CONFIRMED | FAILED
    quantity_deducted: float
    remaining_stock: float
    error: Optional[str] = None


class ConsumeResponse(BaseModel):
    """消費回應"""
    status: str = Field(..., description="整體狀態: CONFIRMED | PARTIAL | FAILED")
    mirs_ref: str = Field(..., description="MIRS 交易參考號")
    intent_id: str = Field(..., description="原始 intent_id")
    confirmed_at: int = Field(..., description="確認時間 (ms)")
    results: List[ConsumeResult] = Field(..., description="各項目結果")
    error_message: Optional[str] = None


# ============================================================
# Station Token Verification
# ============================================================

# In production, this should come from database/config
TRUSTED_STATIONS = {
    # station_id -> station_secret (HMAC key)
    # These are set during CIRS-MIRS pairing
}

# Fallback: Accept any token in dev mode (MIRS_DEV_MODE=true)
import os
DEV_MODE = os.environ.get("MIRS_DEV_MODE", "false").lower() == "true"


def verify_station_token(
    x_station_token: str = Header(..., alias="X-Station-Token"),
    x_station_id: str = Header(..., alias="X-Station-ID"),
    x_timestamp: str = Header(None, alias="X-Timestamp")
) -> dict:
    """
    驗證 Station Token

    Token 格式: HMAC-SHA256(station_secret, f"{station_id}:{timestamp}")

    Headers:
        X-Station-Token: HMAC signature
        X-Station-ID: 來源站點 ID
        X-Timestamp: 請求時間戳 (防 replay, 5 分鐘內有效)
    """
    # Dev mode: 跳過驗證
    if DEV_MODE:
        logger.warning(f"DEV_MODE: 跳過 Station Token 驗證 for {x_station_id}")
        return {"station_id": x_station_id, "verified": False, "dev_mode": True}

    # 檢查時間戳
    if x_timestamp:
        try:
            req_time = int(x_timestamp)
            now = int(time.time() * 1000)
            if abs(now - req_time) > 5 * 60 * 1000:  # 5 分鐘
                raise HTTPException(status_code=401, detail="Token expired (timestamp)")
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid timestamp format")

    # 查找站點 secret
    station_secret = TRUSTED_STATIONS.get(x_station_id)
    if not station_secret:
        # 嘗試從資料庫載入
        station_secret = _load_station_secret(x_station_id)
        if not station_secret:
            raise HTTPException(status_code=401, detail=f"Unknown station: {x_station_id}")

    # 驗證 HMAC
    message = f"{x_station_id}:{x_timestamp or ''}"
    expected = hmac.new(
        station_secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(x_station_token, expected):
        logger.warning(f"Station token verification failed for {x_station_id}")
        raise HTTPException(status_code=401, detail="Invalid station token")

    logger.info(f"Station {x_station_id} verified successfully")
    return {"station_id": x_station_id, "verified": True}


def _load_station_secret(station_id: str) -> Optional[str]:
    """從資料庫載入站點 secret"""
    try:
        import sqlite3
        conn = sqlite3.connect("medical_inventory.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT station_secret FROM paired_stations
            WHERE station_id = ? AND status = 'ACTIVE'
        """, (station_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            TRUSTED_STATIONS[station_id] = row['station_secret']
            return row['station_secret']
        return None
    except Exception as e:
        logger.error(f"Failed to load station secret: {e}")
        return None


# ============================================================
# Database Operations
# ============================================================

def _get_db_connection():
    """取得資料庫連線"""
    import sqlite3
    conn = sqlite3.connect("medical_inventory.db")
    conn.row_factory = sqlite3.Row
    return conn


def _get_current_stock(cursor, item_code: str) -> float:
    """計算當前庫存"""
    cursor.execute("""
        SELECT COALESCE(SUM(
            CASE WHEN event_type = 'RECEIVE' THEN quantity
                 WHEN event_type IN ('CONSUME', 'DISPATCH_RESERVE') THEN -quantity
                 WHEN event_type = 'DISPATCH_RELEASE' THEN quantity
                 ELSE 0 END
        ), 0) as current_stock
        FROM inventory_events
        WHERE item_code = ?
    """, (item_code,))
    row = cursor.fetchone()
    return float(row['current_stock']) if row else 0.0


def _deduct_inventory(
    item_code: str,
    quantity: float,
    intent_id: str,
    execution_id: str,
    person_id: Optional[str],
    operator: Optional[str],
    lot: Optional[str] = None
) -> ConsumeResult:
    """
    執行庫存扣減

    Returns:
        ConsumeResult with status CONFIRMED or FAILED
    """
    conn = _get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. 檢查物品是否存在
        cursor.execute("SELECT item_code, item_name FROM items WHERE item_code = ?", (item_code,))
        item = cursor.fetchone()
        if not item:
            conn.close()
            return ConsumeResult(
                item_code=item_code,
                status="FAILED",
                quantity_deducted=0,
                remaining_stock=0,
                error=f"ITEM_NOT_FOUND: {item_code}"
            )

        # 2. 檢查庫存
        current_stock = _get_current_stock(cursor, item_code)
        if current_stock < quantity:
            conn.close()
            return ConsumeResult(
                item_code=item_code,
                status="FAILED",
                quantity_deducted=0,
                remaining_stock=current_stock,
                error=f"INSUFFICIENT_STOCK: need {quantity}, have {current_stock}"
            )

        # 3. 寫入 CONSUME 事件
        remarks = f"[ENGINE] intent:{intent_id} exec:{execution_id}"
        if person_id:
            remarks += f" pt:{person_id}"

        cursor.execute("""
            INSERT INTO inventory_events (
                event_type, item_code, quantity, batch_number,
                remarks, operator, timestamp
            ) VALUES ('CONSUME', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (item_code, quantity, lot, remarks, operator or "MIRS_ENGINE"))

        conn.commit()

        # 4. 計算剩餘庫存
        remaining = _get_current_stock(cursor, item_code)

        logger.info(f"✓ Inventory deducted: {item_code} x{quantity}, remaining: {remaining}")

        return ConsumeResult(
            item_code=item_code,
            status="CONFIRMED",
            quantity_deducted=quantity,
            remaining_stock=remaining
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Inventory deduction failed: {e}")
        return ConsumeResult(
            item_code=item_code,
            status="FAILED",
            quantity_deducted=0,
            remaining_stock=0,
            error=f"DB_ERROR: {str(e)}"
        )
    finally:
        conn.close()


def _deduct_blood_unit(blood_unit_id: str, intent_id: str, person_id: Optional[str]) -> ConsumeResult:
    """
    扣減血品 (by unit_id)

    血品使用 blood_bags 表追蹤，狀態從 IN_STOCK → USED
    """
    conn = _get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. 查找血袋
        cursor.execute("""
            SELECT bag_code, blood_type, volume_ml, status
            FROM blood_bags
            WHERE bag_code = ?
        """, (blood_unit_id,))
        bag = cursor.fetchone()

        if not bag:
            conn.close()
            return ConsumeResult(
                item_code=f"BLOOD:{blood_unit_id}",
                status="FAILED",
                quantity_deducted=0,
                remaining_stock=0,
                error=f"BLOOD_UNIT_NOT_FOUND: {blood_unit_id}"
            )

        if bag['status'] != 'IN_STOCK':
            conn.close()
            return ConsumeResult(
                item_code=f"BLOOD:{blood_unit_id}",
                status="FAILED",
                quantity_deducted=0,
                remaining_stock=0,
                error=f"BLOOD_UNIT_NOT_AVAILABLE: status={bag['status']}"
            )

        # 2. 更新血袋狀態
        cursor.execute("""
            UPDATE blood_bags
            SET status = 'USED', used_at = CURRENT_TIMESTAMP, used_for = ?
            WHERE bag_code = ?
        """, (f"intent:{intent_id} pt:{person_id or 'N/A'}", blood_unit_id))

        # 3. 更新血庫庫存
        cursor.execute("""
            UPDATE blood_inventory
            SET quantity = quantity - 1
            WHERE blood_type = ?
        """, (bag['blood_type'],))

        # 4. 記錄血袋事件
        cursor.execute("""
            INSERT INTO blood_events (event_type, blood_type, quantity, operator, remarks)
            VALUES ('CONSUME', ?, 1, 'MIRS_ENGINE', ?)
        """, (bag['blood_type'], f"[ENGINE] intent:{intent_id} bag:{blood_unit_id}"))

        conn.commit()

        logger.info(f"✓ Blood unit consumed: {blood_unit_id} ({bag['blood_type']})")

        return ConsumeResult(
            item_code=f"BLOOD:{blood_unit_id}",
            status="CONFIRMED",
            quantity_deducted=1,
            remaining_stock=-1  # Blood units are tracked individually
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Blood unit consumption failed: {e}")
        return ConsumeResult(
            item_code=f"BLOOD:{blood_unit_id}",
            status="FAILED",
            quantity_deducted=0,
            remaining_stock=0,
            error=f"DB_ERROR: {str(e)}"
        )
    finally:
        conn.close()


# ============================================================
# API Endpoints
# ============================================================

@router.post("/consume", response_model=ConsumeResponse)
async def consume_inventory(
    request: ConsumeRequest,
    station: dict = Depends(verify_station_token)
):
    """
    消費庫存 (MIRS Engine 核心端點)

    此端點由 CIRS 呼叫，當 Nursing PWA 確認執行後：
    1. CIRS 建立 execution 記錄
    2. CIRS 建立 resource_intent (status=PENDING_SYNC)
    3. CIRS 呼叫此端點
    4. MIRS 扣庫存，回傳結果
    5. CIRS 更新 resource_intent status

    ## Headers
    - X-Station-Token: HMAC signature
    - X-Station-ID: 來源站點 ID
    - X-Timestamp: 請求時間戳 (ms)

    ## Response
    - status: CONFIRMED (全部成功) | PARTIAL (部分成功) | FAILED (全部失敗)
    - mirs_ref: 交易參考號 (供追蹤)
    - results: 各項目結果
    """
    logger.info(f"🔧 Consume request from {station.get('station_id')}: intent={request.intent_id}")

    mirs_ref = f"MIRS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    results = []

    for item in request.items:
        if item.blood_unit_id:
            # 血品: 使用 unit_id 追蹤
            result = _deduct_blood_unit(
                blood_unit_id=item.blood_unit_id,
                intent_id=request.intent_id,
                person_id=request.person_id
            )
        else:
            # 一般物品
            result = _deduct_inventory(
                item_code=item.item_code,
                quantity=item.quantity,
                intent_id=request.intent_id,
                execution_id=request.execution_id,
                person_id=request.person_id,
                operator=request.operator,
                lot=item.lot
            )
        results.append(result)

    # 判斷整體狀態
    confirmed_count = sum(1 for r in results if r.status == "CONFIRMED")
    if confirmed_count == len(results):
        overall_status = "CONFIRMED"
    elif confirmed_count > 0:
        overall_status = "PARTIAL"
    else:
        overall_status = "FAILED"

    response = ConsumeResponse(
        status=overall_status,
        mirs_ref=mirs_ref,
        intent_id=request.intent_id,
        confirmed_at=int(time.time() * 1000),
        results=results,
        error_message=None if overall_status == "CONFIRMED" else "Some items failed to consume"
    )

    logger.info(f"✓ Consume completed: {overall_status}, ref={mirs_ref}")

    return response


@router.get("/engine/status")
async def get_engine_status():
    """
    取得 MIRS Engine 狀態

    供 CIRS 健康檢查使用
    """
    conn = _get_db_connection()
    cursor = conn.cursor()

    try:
        # 統計今日消費
        cursor.execute("""
            SELECT COUNT(*) as count, COALESCE(SUM(quantity), 0) as total
            FROM inventory_events
            WHERE event_type = 'CONSUME'
            AND DATE(timestamp) = DATE('now')
        """)
        today_stats = cursor.fetchone()

        # 低庫存警示
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM items i
            LEFT JOIN (
                SELECT item_code,
                       SUM(CASE WHEN event_type = 'RECEIVE' THEN quantity
                                WHEN event_type = 'CONSUME' THEN -quantity
                                ELSE 0 END) as current_stock
                FROM inventory_events
                GROUP BY item_code
            ) stock ON i.item_code = stock.item_code
            WHERE COALESCE(stock.current_stock, 0) < i.min_stock
        """)
        low_stock = cursor.fetchone()

        return {
            "status": "ONLINE",
            "version": "1.0.0",
            "timestamp": int(time.time() * 1000),
            "dev_mode": DEV_MODE,
            "stats": {
                "today_consume_count": today_stats['count'],
                "today_consume_quantity": today_stats['total'],
                "low_stock_alerts": low_stock['count']
            }
        }
    finally:
        conn.close()


@router.get("/engine/trusted-stations")
async def get_trusted_stations():
    """
    取得已信任的站點列表 (Admin 用)
    """
    conn = _get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT station_id, station_name, paired_at, last_seen, status
            FROM paired_stations
            ORDER BY paired_at DESC
        """)
        stations = [dict(row) for row in cursor.fetchall()]
        return {"stations": stations, "count": len(stations)}
    except Exception:
        # Table might not exist
        return {"stations": list(TRUSTED_STATIONS.keys()), "count": len(TRUSTED_STATIONS)}
    finally:
        conn.close()
