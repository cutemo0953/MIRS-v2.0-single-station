"""
MIRS Mobile API v1.4 Routes
API 路由: /api/mirs-mobile/v1/*
支援裝置黑名單、撤銷恢復、Rate Limiting
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
import logging
import uuid
import socket
from io import BytesIO

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


def get_local_ip() -> str:
    """取得本機的區域網路 IP 位址"""
    try:
        # 建立一個 socket 連接到外部位址來取得本機 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_client_ip(request: Request) -> str:
    """取得客戶端 IP (v1.4)"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


from .auth import MobileAuth, check_rate_limit

logger = logging.getLogger(__name__)

# API Router with prefix
router = APIRouter(prefix="/api/mirs-mobile/v1", tags=["MIRS Mobile"])

# Global auth instance (will be set by main.py)
_mobile_auth: Optional[MobileAuth] = None
_resilience_service = None
_db_manager = None


def init_mobile_services(db_path: str = "medical_inventory.db", resilience_service=None, db_manager=None):
    """初始化 Mobile 服務"""
    global _mobile_auth, _resilience_service, _db_manager
    _mobile_auth = MobileAuth(db_path)
    _resilience_service = resilience_service
    _db_manager = db_manager
    logger.info("MIRS Mobile 服務初始化完成")


def get_mobile_auth() -> MobileAuth:
    """取得 MobileAuth 實例"""
    if _mobile_auth is None:
        raise HTTPException(status_code=500, detail="Mobile auth service not initialized")
    return _mobile_auth


# ============================================================================
# Pydantic Models
# ============================================================================

class GeneratePairingCodeRequest(BaseModel):
    """產生配對碼請求"""
    station_id: str = Field(..., description="站點 ID")
    allowed_roles: List[str] = Field(default=["nurse", "doctor"], description="允許的角色")
    scopes: List[str] = Field(
        default=[
            "mirs:equipment:read",
            "mirs:equipment:write",
            "mirs:inventory:read",
            "mirs:resilience:read"
        ],
        description="權限範圍"
    )
    expires_minutes: int = Field(default=5, ge=1, le=30, description="有效分鐘數")


class ExchangePairingCodeRequest(BaseModel):
    """交換配對碼請求"""
    pairing_code: str = Field(..., min_length=6, max_length=6, description="6 位數配對碼")
    device_id: str = Field(..., description="裝置 UUID")
    device_name: Optional[str] = Field(None, description="裝置名稱")
    staff_id: str = Field(..., description="人員 ID")
    staff_name: str = Field(..., description="人員名稱")
    role: str = Field(default="nurse", description="角色")


class EquipmentCheckRequest(BaseModel):
    """設備檢查請求"""
    equipment_id: str = Field(..., description="設備 ID")
    check_mode: str = Field(..., description="檢查模式: FULL | QUICK | VISUAL")
    status: str = Field(..., description="狀態: CHECKED_OK | NEEDS_SERVICE | OUT_OF_SERVICE")
    notes: Optional[str] = Field(None, description="備註")
    level_percent: Optional[int] = Field(None, ge=0, le=100, description="電量/容量百分比 (0-100)")


class SyncActionPayload(BaseModel):
    """離線操作同步載荷"""
    action_id: str = Field(..., description="操作 UUID")
    action_type: str = Field(..., description="操作類型")
    payload: Dict[str, Any] = Field(..., description="操作資料")
    created_at: str = Field(..., description="建立時間 ISO8601")
    patient_id: Optional[str] = Field(None, description="病患 ID")


class SyncActionsRequest(BaseModel):
    """批量同步請求"""
    actions: List[SyncActionPayload] = Field(..., description="操作列表")


# ============================================================================
# Token Verification Dependency
# ============================================================================

async def verify_mobile_token(authorization: str = Header(...)) -> Dict[str, Any]:
    """驗證 Mobile JWT Token"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:]  # Remove "Bearer "
    auth = get_mobile_auth()
    payload = auth.verify_token(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


# ============================================================================
# Authentication Endpoints
# ============================================================================

@router.post("/auth/pairing")
async def generate_pairing_code(request: GeneratePairingCodeRequest):
    """
    產生配對碼 (管理員限定)

    行動端顯示此配對碼，讓護理師輸入後完成配對。
    配對碼 5 分鐘內有效，使用後失效。
    """
    auth = get_mobile_auth()
    result = auth.generate_pairing_code(
        station_id=request.station_id,
        allowed_roles=request.allowed_roles,
        scopes=request.scopes,
        expires_minutes=request.expires_minutes
    )
    return result


@router.post("/auth/exchange-debug")
async def exchange_debug(raw_request: Request):
    """Debug endpoint to see raw request body"""
    try:
        body = await raw_request.body()
        body_str = body.decode('utf-8') if body else '<empty>'
        logger.warning(f"DEBUG exchange from {raw_request.client.host}: {body_str[:500]}")
        return {"received": body_str[:500], "content_type": raw_request.headers.get("content-type")}
    except Exception as e:
        return {"error": str(e)}


@router.post("/auth/exchange")
async def exchange_pairing_code(request: ExchangePairingCodeRequest, raw_request: Request):
    """
    交換配對碼取得 JWT Token (v1.4: Rate limiting + Blacklist check)

    行動端提交配對碼與裝置資訊，成功後取得 JWT Token。
    Rate limit: 5 attempts per minute per IP.
    """
    client_ip = get_client_ip(raw_request)
    user_agent = raw_request.headers.get("User-Agent")

    # v1.4: Rate limiting
    if not check_rate_limit(client_ip):
        logger.warning(f"Rate limit exceeded for {client_ip}")
        raise HTTPException(
            status_code=429,
            detail="嘗試次數過多，請等待 60 秒後再試"
        )

    logger.info(f"Exchange request from {client_ip}: code={request.pairing_code}, device={request.device_id}")
    auth = get_mobile_auth()
    result = auth.exchange_pairing_code(
        pairing_code=request.pairing_code,
        device_id=request.device_id,
        device_name=request.device_name,
        staff_id=request.staff_id,
        staff_name=request.staff_name,
        role=request.role,
        ip_address=client_ip,
        user_agent=user_agent
    )

    if result is None:
        raise HTTPException(
            status_code=400,
            detail="配對碼無效、已過期或角色不允許"
        )

    # v1.4: Check for blacklist error
    if isinstance(result, dict) and result.get("error") == "BLACKLISTED":
        raise HTTPException(
            status_code=403,
            detail=result.get("message", "此裝置已被永久封鎖")
        )

    return result


@router.get("/auth/verify")
async def verify_token(token_payload: Dict = Depends(verify_mobile_token)):
    """驗證 Token 有效性並取得使用者資訊"""
    return {
        "valid": True,
        "device_id": token_payload.get("device_id"),
        "staff_id": token_payload.get("staff_id"),
        "staff_name": token_payload.get("staff_name"),
        "role": token_payload.get("role"),
        "station_id": token_payload.get("station_id"),
        "scopes": token_payload.get("scopes", [])
    }


@router.get("/auth/devices")
async def list_paired_devices(
    station_id: Optional[str] = Query(None),
    token_payload: Dict = Depends(verify_mobile_token)
):
    """取得已配對裝置列表 (管理員限定)"""
    if token_payload.get("role") != "admin":
        # Allow nurses to see only their own device
        auth = get_mobile_auth()
        devices = auth.get_paired_devices(station_id or token_payload.get("station_id"))
        return [d for d in devices if d["device_id"] == token_payload.get("device_id")]

    auth = get_mobile_auth()
    return auth.get_paired_devices(station_id)


@router.post("/auth/devices/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    reason: str = Query(...),
    token_payload: Dict = Depends(verify_mobile_token)
):
    """撤銷裝置授權 (管理員限定)"""
    if token_payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="僅管理員可撤銷裝置")

    auth = get_mobile_auth()
    success = auth.revoke_device(
        device_id=device_id,
        reason=reason,
        revoked_by=token_payload.get("staff_id", "admin")
    )

    if not success:
        raise HTTPException(status_code=404, detail="裝置不存在")

    return {"success": True, "message": f"裝置 {device_id} 已被撤銷"}


# ============================================================================
# Hub 裝置管理 Endpoints (無需 Mobile Token)
# ============================================================================

class RevokeDeviceRequest(BaseModel):
    """撤銷裝置請求"""
    reason: str = Field(default="管理員撤銷", description="撤銷原因")

@router.get("/devices")
async def hub_list_paired_devices(
    station_id: Optional[str] = Query(None)
):
    """
    取得已配對裝置列表 (Hub 管理端)
    無需 Mobile Token，供 Hub 管理介面使用
    """
    auth = get_mobile_auth()
    devices = auth.get_paired_devices(station_id)
    return {"devices": devices, "count": len(devices)}


@router.post("/devices/{device_id}/revoke")
async def hub_revoke_device(
    device_id: str,
    request: RevokeDeviceRequest
):
    """
    撤銷裝置授權 (Hub 管理端)
    無需 Mobile Token，供 Hub 管理介面使用
    """
    auth = get_mobile_auth()
    success = auth.revoke_device(
        device_id=device_id,
        reason=request.reason,
        revoked_by="hub_admin"
    )

    if not success:
        raise HTTPException(status_code=404, detail="裝置不存在或已在黑名單中")

    logger.info(f"Hub 撤銷裝置: {device_id}, 原因: {request.reason}")
    return {"success": True, "message": f"裝置 {device_id} 已被撤銷"}


@router.post("/devices/{device_id}/unrevoke")
async def hub_unrevoke_device(device_id: str):
    """
    恢復已撤銷的裝置授權 (Hub 管理端 v1.4)
    無需 Mobile Token，供 Hub 管理介面使用
    """
    auth = get_mobile_auth()
    success = auth.unrevoke_device(
        device_id=device_id,
        unrevoked_by="hub_admin"
    )

    if not success:
        raise HTTPException(status_code=400, detail="裝置不存在、未被撤銷或已在黑名單中")

    logger.info(f"Hub 恢復裝置: {device_id}")
    return {"success": True, "message": f"裝置 {device_id} 已恢復存取權限"}


class BlacklistDeviceRequest(BaseModel):
    """黑名單請求"""
    reason: str = Field(default="管理員封鎖", description="封鎖原因")


@router.post("/devices/{device_id}/blacklist")
async def hub_blacklist_device(
    device_id: str,
    request: BlacklistDeviceRequest
):
    """
    將裝置加入黑名單 (Hub 管理端 v1.4)
    永久封鎖，即使重新配對也無法使用
    """
    auth = get_mobile_auth()
    success = auth.blacklist_device(
        device_id=device_id,
        reason=request.reason,
        blacklisted_by="hub_admin"
    )

    if not success:
        raise HTTPException(status_code=400, detail="加入黑名單失敗")

    logger.info(f"Hub 黑名單裝置: {device_id}, 原因: {request.reason}")
    return {"success": True, "message": f"裝置 {device_id} 已加入黑名單"}


@router.post("/devices/{device_id}/unblacklist")
async def hub_unblacklist_device(device_id: str):
    """
    將裝置從黑名單移除 (Hub 管理端 v1.4)
    移除後裝置可以重新配對
    """
    auth = get_mobile_auth()
    success = auth.unblacklist_device(
        device_id=device_id,
        unblacklisted_by="hub_admin"
    )

    if not success:
        raise HTTPException(status_code=400, detail="裝置不存在或不在黑名單中")

    logger.info(f"Hub 解除黑名單: {device_id}")
    return {"success": True, "message": f"裝置 {device_id} 已從黑名單移除"}


# ============================================================================
# Resilience Endpoints
# ============================================================================

@router.get("/resilience")
async def get_mobile_resilience_status(
    token_payload: Dict = Depends(verify_mobile_token)
):
    """
    取得韌性狀態摘要 (行動端首頁)

    返回簡化版的韌性狀態，適合行動端顯示。
    """
    station_id = token_payload.get("station_id")

    if _resilience_service is None:
        raise HTTPException(status_code=500, detail="Resilience service not available")

    try:
        full_status = _resilience_service.calculate_resilience_status(station_id)

        # 解析 lifelines 列表
        lifelines = full_status.get("lifelines", [])
        summary = full_status.get("summary", {})
        weakest = full_status.get("weakest_link")

        # 分類整理
        categories = {
            "oxygen": {"status": "UNKNOWN", "effective_days": 0, "item_count": 0},
            "power": {"status": "UNKNOWN", "effective_days": 0, "item_count": 0},
            "reagents": {"status": "UNKNOWN", "effective_days": 0, "item_count": 0}
        }

        for item in lifelines:
            item_type = item.get("type", "").lower()
            if item_type == "oxygen":
                cat_key = "oxygen"
            elif item_type == "power":
                cat_key = "power"
            elif item_type == "reagent":
                cat_key = "reagents"
            else:
                continue

            endurance = item.get("endurance", {})
            eff_days = endurance.get("effective_days", 0)
            status = item.get("status", "UNKNOWN")

            categories[cat_key]["item_count"] += 1
            # 取最小的天數
            if categories[cat_key]["effective_days"] == 0 or (eff_days > 0 and eff_days < categories[cat_key]["effective_days"]):
                categories[cat_key]["effective_days"] = eff_days
                categories[cat_key]["status"] = status

        # 決定總體狀態
        overall_status = summary.get("overall_status", "UNKNOWN")

        mobile_summary = {
            "station_id": station_id,
            "updated_at": datetime.now().isoformat(),
            "overall_status": overall_status,
            "weakest_link": weakest.get("item") if weakest else None,
            "categories": categories
        }

        return mobile_summary

    except Exception as e:
        logger.error(f"取得韌性狀態失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Equipment Endpoints
# ============================================================================

@router.get("/equipment")
async def get_equipment_list(
    category: Optional[str] = Query(None, description="篩選類別"),
    needs_check: bool = Query(False, description="僅顯示需要檢查的設備"),
    token_payload: Dict = Depends(verify_mobile_token)
):
    """
    取得設備清單

    返回站點的所有設備，可篩選類別和檢查狀態。
    """
    if _db_manager is None:
        raise HTTPException(status_code=500, detail="Database not available")

    station_id = token_payload.get("station_id")

    try:
        conn = _db_manager.get_connection()
        cursor = conn.cursor()

        # 查詢設備 (使用 equipment 表的實際欄位)
        query = """
            SELECT e.id, e.name, e.type_code, et.type_name, e.category,
                   et.resilience_category, e.status, e.remarks,
                   e.last_check, e.power_level
            FROM equipment e
            LEFT JOIN equipment_types et ON e.type_code = et.type_code
            WHERE 1=1
        """
        params = []

        if category:
            query += " AND (e.category = ? OR et.category = ?)"
            params.extend([category, category])

        if needs_check:
            query += " AND (e.status = 'UNCHECKED' OR e.last_check IS NULL OR e.last_check < date('now'))"

        query += " ORDER BY et.resilience_category DESC NULLS LAST, e.category, e.name"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        equipment_list = []
        for row in rows:
            last_check = row[8]
            today = datetime.now().strftime("%Y-%m-%d")
            needs_check_flag = row[6] == 'UNCHECKED' or last_check is None or (last_check and last_check < today)

            equipment_list.append({
                "id": row[0],
                "name": row[1],
                "type_code": row[2],
                "type_name": row[3] or row[2],
                "category": row[4],
                "resilience_category": row[5],
                "status": row[6],
                "location": None,  # 設備表沒有位置欄位
                "last_check_date": last_check[:10] if last_check else None,
                "next_check_date": None,
                "notes": row[7],
                "power_level": row[9],
                "needs_check": needs_check_flag
            })

        return {
            "station_id": station_id,
            "equipment": equipment_list,
            "total": len(equipment_list),
            "needs_check_count": sum(1 for e in equipment_list if e["needs_check"])
        }

    except Exception as e:
        logger.error(f"取得設備清單失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/equipment/{equipment_id}/check")
async def update_equipment_check(
    equipment_id: str,  # equipment.id 是 TEXT 類型
    request: EquipmentCheckRequest,
    token_payload: Dict = Depends(verify_mobile_token)
):
    """
    更新設備檢查狀態

    巡房時更新設備狀態與下次檢查日期。
    """
    if _db_manager is None:
        raise HTTPException(status_code=500, detail="Database not available")

    # 檢查權限
    scopes = token_payload.get("scopes", [])
    if "mirs:equipment:write" not in scopes:
        raise HTTPException(status_code=403, detail="無設備寫入權限")

    try:
        conn = _db_manager.get_connection()
        cursor = conn.cursor()

        # 更新設備狀態 (使用正確的欄位名稱)
        # 如果有提供 level_percent，同時更新 power_level
        if request.level_percent is not None:
            cursor.execute("""
                UPDATE equipment
                SET status = ?,
                    last_check = datetime('now'),
                    remarks = COALESCE(?, remarks),
                    power_level = ?,
                    updated_at = datetime('now')
                WHERE id = ?
            """, (
                request.status,
                request.notes,
                request.level_percent,
                equipment_id
            ))
        else:
            cursor.execute("""
                UPDATE equipment
                SET status = ?,
                    last_check = datetime('now'),
                    remarks = COALESCE(?, remarks),
                    updated_at = datetime('now')
                WHERE id = ?
            """, (
                request.status,
                request.notes,
                equipment_id
            ))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="設備不存在")

        # 記錄檢查日誌
        action_id = str(uuid.uuid4())
        auth = get_mobile_auth()
        auth.log_action(
            action_id=action_id,
            action_type="EQUIPMENT_CHECK",
            device_id=token_payload.get("device_id"),
            staff_id=token_payload.get("staff_id"),
            station_id=token_payload.get("station_id"),
            payload={
                "equipment_id": equipment_id,
                "check_mode": request.check_mode,
                "status": request.status,
                "notes": request.notes
            }
        )

        conn.commit()

        return {
            "success": True,
            "action_id": action_id,
            "equipment_id": equipment_id,
            "status": request.status,
            "message": "設備檢查狀態已更新"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新設備檢查失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Sync Endpoints (Offline Support)
# ============================================================================

@router.post("/sync/actions")
async def sync_offline_actions(
    request: SyncActionsRequest,
    token_payload: Dict = Depends(verify_mobile_token)
):
    """
    同步離線操作

    行動端在離線時記錄操作，網路恢復後批量同步至 Hub。
    返回每個操作的處理結果 (ACCEPTED / ACCEPTED_WITH_ADJUSTMENT / REJECTED)。
    """
    auth = get_mobile_auth()
    results = []

    for action in request.actions:
        try:
            # 記錄操作
            success = auth.log_action(
                action_id=action.action_id,
                action_type=action.action_type,
                device_id=token_payload.get("device_id"),
                staff_id=token_payload.get("staff_id"),
                station_id=token_payload.get("station_id"),
                payload=action.payload,
                patient_id=action.patient_id,
                created_at=action.created_at
            )

            if success:
                # 根據操作類型執行實際動作
                process_result = await _process_synced_action(action, token_payload)
                results.append({
                    "action_id": action.action_id,
                    "status": process_result.get("status", "ACCEPTED"),
                    "adjustment_note": process_result.get("adjustment_note"),
                    "hub_received_at": datetime.now().isoformat()
                })
            else:
                # 重複的 action_id，已處理過
                results.append({
                    "action_id": action.action_id,
                    "status": "ALREADY_PROCESSED",
                    "hub_received_at": datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"處理操作 {action.action_id} 失敗: {e}")
            results.append({
                "action_id": action.action_id,
                "status": "REJECTED",
                "rejection_reason": str(e)
            })

    return {
        "processed": len(results),
        "results": results
    }


async def _process_synced_action(action: SyncActionPayload, token_payload: Dict) -> Dict:
    """處理同步的操作"""
    action_type = action.action_type
    payload = action.payload

    if action_type == "EQUIPMENT_CHECK":
        # 設備檢查
        try:
            equipment_id = payload.get("equipment_id")
            if equipment_id and _db_manager:
                conn = _db_manager.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE equipment
                    SET status = ?,
                        last_check_date = ?,
                        next_check_date = ?,
                        notes = COALESCE(?, notes),
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (
                    payload.get("status", "CHECKED_OK"),
                    payload.get("check_date", datetime.now().strftime("%Y-%m-%d")),
                    payload.get("next_check_date"),
                    payload.get("notes"),
                    equipment_id
                ))
                conn.commit()
            return {"status": "ACCEPTED"}
        except Exception as e:
            return {"status": "REJECTED", "rejection_reason": str(e)}

    # 其他操作類型在後續版本實作
    return {"status": "ACCEPTED"}


# ============================================================================
# Info Endpoints
# ============================================================================

@router.get("/info")
async def get_mobile_api_info():
    """取得 Mobile API 資訊"""
    return {
        "api": "MIRS Mobile API",
        "version": "1.4.0",
        "phase": "P0",
        "features": {
            "rate_limiting": "5 attempts/minute per IP",
            "device_blacklist": True,
            "device_unrevoke": True
        },
        "endpoints": {
            "auth": [
                "POST /auth/pairing",
                "POST /auth/exchange",
                "GET /auth/verify",
                "GET /auth/devices",
                "POST /auth/devices/{id}/revoke"
            ],
            "devices": [
                "GET /devices",
                "POST /devices/{id}/revoke",
                "POST /devices/{id}/unrevoke",
                "POST /devices/{id}/blacklist",
                "POST /devices/{id}/unblacklist"
            ],
            "resilience": [
                "GET /resilience"
            ],
            "equipment": [
                "GET /equipment",
                "POST /equipment/{id}/check"
            ],
            "sync": [
                "POST /sync/actions"
            ],
            "qr": [
                "GET /auth/pairing-qr",
                "GET /auth/pairing-info"
            ]
        }
    }


@router.get("/auth/pairing-qr")
async def get_pairing_qr(request: Request):
    """
    產生 Mobile PWA URL 的 QR Code 圖片

    QR Code 內容為 Mobile PWA 的完整 URL，包含 Hub IP。
    """
    if not QRCODE_AVAILABLE:
        raise HTTPException(status_code=500, detail="QR code library not available")

    # 取得 Hub IP (從請求的 Host header)
    host = request.headers.get("host", "localhost:8000")
    # 移除 port 如果是標準 port
    if ":" in host:
        hub_ip = host.split(":")[0]
        port = host.split(":")[1]
    else:
        hub_ip = host
        port = "80"

    # 如果是 localhost 或 127.0.0.1，自動取得實際網路 IP
    if hub_ip in ["localhost", "127.0.0.1"]:
        hub_ip = get_local_ip()

    # 組合 Mobile PWA URL
    scheme = "https" if request.url.scheme == "https" else "http"
    if port in ["80", "443"]:
        mobile_url = f"{scheme}://{hub_ip}/mobile"
    else:
        mobile_url = f"{scheme}://{hub_ip}:{port}/mobile"

    # 產生 QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(mobile_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # 轉換為 PNG bytes
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"}
    )


class PairingConfigRequest(BaseModel):
    """配對設定請求（從 Hub 設定角色與權限）"""
    role: str = Field(default="nurse", description="角色: nurse/warehouse/maintenance/admin")
    scopes: List[str] = Field(
        default=["mirs:resilience:read", "mirs:equipment:read", "mirs:equipment:write", "mirs:inventory:read"],
        description="權限範圍"
    )


def _get_pairing_info_common(request: Request, role: str, scopes: List[str]):
    """配對資訊產生的共用邏輯"""
    auth = get_mobile_auth()

    # 取得 Hub IP
    host = request.headers.get("host", "localhost:8000")
    if ":" in host:
        hub_ip = host.split(":")[0]
        port = host.split(":")[1]
    else:
        hub_ip = host
        port = "8000"

    # 如果是 localhost 或 127.0.0.1，自動取得實際網路 IP
    if hub_ip in ["localhost", "127.0.0.1"]:
        hub_ip = get_local_ip()

    # 組合 Mobile URL
    scheme = "https" if request.url.scheme == "https" else "http"
    if port in ["80", "443"]:
        mobile_url = f"{scheme}://{hub_ip}/mobile"
    else:
        mobile_url = f"{scheme}://{hub_ip}:{port}/mobile"

    # 產生新配對碼
    pairing = auth.generate_pairing_code(
        station_id="BORP-DNO-01",  # TODO: 從配置取得
        allowed_roles=[role],
        scopes=scopes,
        expires_minutes=5
    )

    return {
        "hub_ip": hub_ip,
        "hub_port": port,
        "mobile_url": mobile_url,
        "pairing_code": pairing["code"],
        "expires_at": pairing["expires_at"],
        "allowed_roles": pairing["allowed_roles"],
        "role": role,
        "scopes": pairing["scopes"]
    }


@router.get("/auth/pairing-info")
async def get_pairing_info(request: Request):
    """
    取得配對資訊 (包含 Hub IP 與新產生的配對碼) - 預設權限

    用於顯示在 Hub 介面上，讓使用者知道如何連接。
    使用預設角色(nurse)與預設權限。
    """
    default_scopes = [
        "mirs:resilience:read",
        "mirs:equipment:read",
        "mirs:equipment:write",
        "mirs:inventory:read"
    ]
    return _get_pairing_info_common(request, "nurse", default_scopes)


@router.post("/auth/pairing-info")
async def create_pairing_with_config(request: Request, config: PairingConfigRequest):
    """
    產生配對碼（自訂角色與權限）

    從 Hub 介面設定角色和功能權限後，產生對應的配對碼。
    """
    return _get_pairing_info_common(request, config.role, config.scopes)
