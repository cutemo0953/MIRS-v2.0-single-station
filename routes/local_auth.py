"""
MIRS Local Authentication Module (v2.8)
Policy Snapshot + Offline PIN Verification

支援離線模式下的本地身份驗證:
1. 從 CIRS Hub 同步 Policy Snapshot
2. 本地 PIN 驗證
3. 簽發短效本地 Token
"""

import os
import json
import hashlib
import hmac
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import httpx
import jwt

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/local-auth", tags=["local-auth"])
security = HTTPBearer(auto_error=False)

# ==============================================================================
# Configuration
# ==============================================================================

CIRS_HUB_URL = os.getenv("CIRS_HUB_URL", "http://localhost:8090")
IS_VERCEL = os.getenv("VERCEL", "").lower() in ("1", "true")

# 快照簽章密鑰 (必須與 CIRS 相同)
# 優先使用 CIRS_SNAPSHOT_SECRET，確保 Hub-Satellite 一致性
SNAPSHOT_SECRET = os.getenv(
    "CIRS_SNAPSHOT_SECRET",
    os.getenv("MIRS_SNAPSHOT_SECRET", "snapshot-secret-change-in-production")
).encode()
LOCAL_JWT_SECRET = os.getenv("MIRS_JWT_SECRET", "mirs-local-jwt-secret").encode()

# 本地 Token 有效期
LOCAL_TOKEN_TTL_HOURS = 4  # 離線模式 Token 有效 4 小時

# 快照同步間隔
SNAPSHOT_SYNC_INTERVAL_MINUTES = 60  # 每小時同步一次

# SQLite 路徑
DB_PATH = os.getenv("MIRS_DB_PATH", "data/mirs.db")


# ==============================================================================
# Database Helpers
# ==============================================================================

def get_snapshot_db():
    """Get snapshot database connection"""
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_snapshot_tables():
    """Initialize policy snapshot tables"""
    with get_snapshot_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS policy_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_version INTEGER NOT NULL,
                snapshot_data TEXT NOT NULL,
                signature TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS local_auth_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id TEXT,
                success INTEGER NOT NULL,
                reason TEXT,
                ts_local TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Index for faster lookup
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_version ON policy_snapshots(snapshot_version)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_active ON policy_snapshots(is_active)")
        except Exception:
            pass

        conn.commit()

    logger.info("[MIRS] Policy snapshot tables initialized")


# ==============================================================================
# Snapshot Sync
# ==============================================================================

class SnapshotSyncResult(BaseModel):
    success: bool
    snapshot_version: Optional[int] = None
    user_count: Optional[int] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


async def sync_policy_snapshot(cirs_token: str = None) -> SnapshotSyncResult:
    """
    從 CIRS Hub 同步 Policy Snapshot

    Args:
        cirs_token: CIRS JWT token (需要認證)

    Returns:
        SnapshotSyncResult
    """
    if IS_VERCEL:
        # Demo mode - return mock snapshot
        return SnapshotSyncResult(
            success=True,
            snapshot_version=1,
            user_count=3,
            expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat(),
            error="Demo mode - using mock snapshot"
        )

    try:
        headers = {}
        if cirs_token:
            headers["Authorization"] = f"Bearer {cirs_token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get station ID from env or generate
            station_id = os.getenv("MIRS_STATION_ID", "MIRS-001")

            response = await client.get(
                f"{CIRS_HUB_URL}/api/auth/policy-snapshot",
                params={"station_id": station_id},
                headers=headers
            )

            if response.status_code == 401:
                return SnapshotSyncResult(
                    success=False,
                    error="Authentication required - please provide CIRS token"
                )

            if response.status_code != 200:
                return SnapshotSyncResult(
                    success=False,
                    error=f"CIRS returned {response.status_code}: {response.text}"
                )

            snapshot = response.json()

            # Verify signature
            if not verify_snapshot_signature(snapshot):
                return SnapshotSyncResult(
                    success=False,
                    error="Snapshot signature verification failed"
                )

            # Store locally
            store_snapshot(snapshot)

            return SnapshotSyncResult(
                success=True,
                snapshot_version=snapshot.get('snapshot_version'),
                user_count=snapshot.get('user_count'),
                expires_at=snapshot.get('expires_at')
            )

    except httpx.RequestError as e:
        logger.warning(f"[MIRS] Failed to sync snapshot: {e}")
        return SnapshotSyncResult(
            success=False,
            error=f"Network error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"[MIRS] Snapshot sync error: {e}")
        return SnapshotSyncResult(
            success=False,
            error=str(e)
        )


def verify_snapshot_signature(snapshot: dict) -> bool:
    """Verify snapshot HMAC signature"""
    signature = snapshot.get('signature')
    if not signature:
        return False

    # Remove signature for verification
    snapshot_copy = {k: v for k, v in snapshot.items() if k != 'signature'}
    canonical = json.dumps(snapshot_copy, sort_keys=True, separators=(',', ':'))

    expected = hmac.new(SNAPSHOT_SECRET, canonical.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def store_snapshot(snapshot: dict):
    """Store snapshot to local database"""
    with get_snapshot_db() as conn:
        # Deactivate old snapshots
        conn.execute("UPDATE policy_snapshots SET is_active = 0")

        # Insert new snapshot
        conn.execute("""
            INSERT INTO policy_snapshots (snapshot_version, snapshot_data, signature, expires_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (
            snapshot.get('snapshot_version'),
            json.dumps(snapshot),
            snapshot.get('signature'),
            snapshot.get('expires_at')
        ))

        conn.commit()

    logger.info(f"[MIRS] Stored snapshot v{snapshot.get('snapshot_version')} with {snapshot.get('user_count')} users")


def get_active_snapshot() -> Optional[dict]:
    """Get current active policy snapshot"""
    try:
        with get_snapshot_db() as conn:
            cursor = conn.execute("""
                SELECT snapshot_data, expires_at
                FROM policy_snapshots
                WHERE is_active = 1
                ORDER BY snapshot_version DESC
                LIMIT 1
            """)
            row = cursor.fetchone()

            if not row:
                return None

            snapshot = json.loads(row['snapshot_data'])
            return snapshot
    except Exception as e:
        logger.error(f"[MIRS] Failed to get active snapshot: {e}")
        return None


# ==============================================================================
# Local Authentication
# ==============================================================================

class LocalLoginRequest(BaseModel):
    person_id: str
    pin: str


class LocalLoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    person: Optional[dict] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    is_offline: bool = True


def hash_pin(pin: str) -> str:
    """SHA256 hash for PIN (for new local-only users)"""
    return "sha256:" + hashlib.sha256(pin.encode()).hexdigest()


def verify_pin_hash(pin: str, stored_hash: str) -> bool:
    """
    Verify PIN against stored hash.
    Supports multiple formats:
    - bcrypt: $2b$... or $2a$... (from CIRS - migration mode)
    - sha256: sha256:... (MIRS local format)
    - sha256_salted: 64-char hex (CIRS salted SHA256)
    - legacy: raw hex string
    """
    if not stored_hash:
        return False

    # bcrypt format (from CIRS) - migration mode
    # CIRS uses a migration workaround where bcrypt hashes accept default PIN
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        # First try proper bcrypt verification
        if BCRYPT_AVAILABLE:
            try:
                if bcrypt.checkpw(pin.encode(), stored_hash.encode()):
                    return True
            except Exception as e:
                logger.debug(f"[MIRS] bcrypt check failed: {e}")

        # CIRS migration mode: accept default PIN 1234 for legacy bcrypt hashes
        # This matches CIRS behavior for accounts that haven't changed their PIN
        if pin == "1234":
            logger.info("[MIRS] Accepting default PIN for bcrypt hash (migration mode)")
            return True
        return False

    # sha256:xxx format (MIRS local)
    if stored_hash.startswith("sha256:"):
        computed = "sha256:" + hashlib.sha256(pin.encode()).hexdigest()
        return hmac.compare_digest(computed, stored_hash)

    # CIRS salted SHA256 format (64-char hex)
    # CIRS uses: SHA256(salt + pin + salt)
    PIN_SALT = os.getenv("PIN_SALT", "xirs-pin-salt-2024")
    salted = f"{PIN_SALT}{pin}{PIN_SALT}"
    computed = hashlib.sha256(salted.encode()).hexdigest()
    if hmac.compare_digest(computed, stored_hash):
        return True

    # Legacy format - plain SHA256
    plain_hash = hashlib.sha256(pin.encode()).hexdigest()
    return hmac.compare_digest(plain_hash, stored_hash)


def sign_local_token(payload: dict) -> str:
    """Sign local JWT token"""
    return jwt.encode(payload, LOCAL_JWT_SECRET, algorithm="HS256")


def decode_local_token(token: str) -> Optional[dict]:
    """Decode and verify local JWT token"""
    try:
        return jwt.decode(token, LOCAL_JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def local_login(person_id: str, pin: str) -> LocalLoginResponse:
    """
    本地離線登入

    使用 Policy Snapshot 進行本地 PIN 驗證，
    簽發短效本地 Token。
    """
    snapshot = get_active_snapshot()

    if not snapshot:
        return LocalLoginResponse(
            success=False,
            error="NO_SNAPSHOT",
            warning="無本地權限快照，請先同步"
        )

    # Check snapshot expiry
    expires_at = snapshot.get('expires_at')
    if expires_at:
        try:
            exp_time = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if datetime.utcnow() > exp_time.replace(tzinfo=None):
                return LocalLoginResponse(
                    success=False,
                    error="SNAPSHOT_EXPIRED",
                    warning="權限快照已過期，請重新同步"
                )
        except Exception:
            pass

    # Find user in snapshot
    users = snapshot.get('users', {})
    user = users.get(person_id)

    if not user:
        log_local_auth('LOCAL_LOGIN_FAIL', person_id, False, 'USER_NOT_FOUND')
        return LocalLoginResponse(
            success=False,
            error="USER_NOT_FOUND",
            warning="使用者不在本地快照中"
        )

    # Verify PIN
    stored_hash = user.get('pin_hash')
    if not stored_hash:
        log_local_auth('LOCAL_LOGIN_FAIL', person_id, False, 'NO_PIN_HASH')
        return LocalLoginResponse(
            success=False,
            error="NO_PIN_HASH",
            warning="使用者無 PIN 設定"
        )

    if not verify_pin_hash(pin, stored_hash):
        log_local_auth('LOCAL_LOGIN_FAIL', person_id, False, 'INVALID_PIN')
        return LocalLoginResponse(
            success=False,
            error="INVALID_PIN",
            warning="PIN 錯誤"
        )

    # Generate local token
    # Use time.time() to avoid datetime.utcnow().timestamp() timezone bug
    import time
    now_ts = int(time.time())
    exp_ts = now_ts + (LOCAL_TOKEN_TTL_HOURS * 3600)

    token_payload = {
        "sub": person_id,
        "role": user.get('role', 'volunteer'),
        "scopes": user.get('scopes', []),
        "cap_version": user.get('cap_version', 1),
        "iat": now_ts,
        "exp": exp_ts,
        "local": True,  # Mark as local token
        "snapshot_version": snapshot.get('snapshot_version')
    }

    token = sign_local_token(token_payload)

    log_local_auth('LOCAL_LOGIN_SUCCESS', person_id, True)

    return LocalLoginResponse(
        success=True,
        token=token,
        person={
            "id": person_id,
            "name": user.get('name', person_id),
            "role": user.get('role', 'volunteer'),
            "scopes": user.get('scopes', [])
        },
        warning="離線模式：部分功能可能受限",
        is_offline=True
    )


def log_local_auth(event_type: str, user_id: str, success: bool, reason: str = None):
    """Log local authentication event"""
    try:
        with get_snapshot_db() as conn:
            conn.execute("""
                INSERT INTO local_auth_log (event_type, user_id, success, reason)
                VALUES (?, ?, ?, ?)
            """, (event_type, user_id, 1 if success else 0, reason))
            conn.commit()
    except Exception as e:
        logger.warning(f"[MIRS] Failed to log auth event: {e}")


# ==============================================================================
# API Routes
# ==============================================================================

@router.post("/login", response_model=LocalLoginResponse)
async def api_local_login(request: LocalLoginRequest):
    """
    本地離線登入 API

    使用 Policy Snapshot 進行 PIN 驗證，
    適用於 MIRS 與 CIRS Hub 斷線時。
    """
    return local_login(request.person_id, request.pin)


@router.post("/sync-snapshot")
async def api_sync_snapshot(
    cirs_token: str = None,
    background_tasks: BackgroundTasks = None
):
    """
    同步 Policy Snapshot

    從 CIRS Hub 取得最新的權限快照。
    需要提供有效的 CIRS token。
    """
    result = await sync_policy_snapshot(cirs_token)
    return result


@router.get("/snapshot-status")
async def api_snapshot_status():
    """
    取得本地 Snapshot 狀態
    """
    snapshot = get_active_snapshot()

    if not snapshot:
        return {
            "has_snapshot": False,
            "message": "無本地快照，請先同步"
        }

    expires_at = snapshot.get('expires_at')
    is_expired = False

    if expires_at:
        try:
            exp_time = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            is_expired = datetime.utcnow() > exp_time.replace(tzinfo=None)
        except Exception:
            pass

    return {
        "has_snapshot": True,
        "snapshot_version": snapshot.get('snapshot_version'),
        "snapshot_time": snapshot.get('snapshot_time'),
        "expires_at": expires_at,
        "is_expired": is_expired,
        "user_count": snapshot.get('user_count', len(snapshot.get('users', {}))),
        "station_id": snapshot.get('station_id')
    }


@router.get("/verify-token")
async def api_verify_local_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    驗證本地 Token
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Token required")

    payload = decode_local_token(credentials.credentials)

    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check against current snapshot version
    snapshot = get_active_snapshot()
    if snapshot:
        current_version = snapshot.get('snapshot_version', 0)
        token_version = payload.get('snapshot_version', 0)

        if token_version < current_version:
            return {
                "valid": False,
                "reason": "SNAPSHOT_STALE",
                "message": "Token 基於舊版快照，建議重新登入",
                "token_snapshot_version": token_version,
                "current_snapshot_version": current_version
            }

    return {
        "valid": True,
        "payload": {
            "sub": payload.get('sub'),
            "role": payload.get('role'),
            "scopes": payload.get('scopes'),
            "cap_version": payload.get('cap_version'),
            "exp": payload.get('exp'),
            "local": payload.get('local', False)
        }
    }


@router.get("/auth-log")
async def api_auth_log(limit: int = 50):
    """
    取得本地認證日誌
    """
    try:
        with get_snapshot_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM local_auth_log
                ORDER BY ts_local DESC
                LIMIT ?
            """, (limit,))

            logs = []
            for row in cursor.fetchall():
                logs.append({
                    "id": row['id'],
                    "event_type": row['event_type'],
                    "user_id": row['user_id'],
                    "success": bool(row['success']),
                    "reason": row['reason'],
                    "ts_local": row['ts_local']
                })

            return {"logs": logs, "count": len(logs)}
    except Exception as e:
        return {"logs": [], "count": 0, "error": str(e)}


# ==============================================================================
# Hub Connection Status
# ==============================================================================

async def check_hub_connection() -> dict:
    """Check if CIRS Hub is reachable"""
    if IS_VERCEL:
        return {
            "connected": False,
            "hub_url": CIRS_HUB_URL,
            "mode": "demo"
        }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{CIRS_HUB_URL}/api/health")
            return {
                "connected": response.status_code == 200,
                "hub_url": CIRS_HUB_URL,
                "hub_status": response.json() if response.status_code == 200 else None
            }
    except Exception as e:
        return {
            "connected": False,
            "hub_url": CIRS_HUB_URL,
            "error": str(e)
        }


@router.get("/hub-status")
async def api_hub_status():
    """
    檢查 CIRS Hub 連線狀態
    """
    return await check_hub_connection()


# ==============================================================================
# Initialization
# ==============================================================================

def init_local_auth():
    """Initialize local auth module"""
    try:
        init_snapshot_tables()
        logger.info("[MIRS] Local auth module initialized (v2.8)")
    except Exception as e:
        logger.error(f"[MIRS] Failed to initialize local auth: {e}")
