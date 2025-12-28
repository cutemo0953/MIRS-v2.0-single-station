"""
MIRS Mobile Authentication v1.4
配對碼 + JWT 認證模組
支援裝置黑名單、撤銷恢復、Rate Limiting
"""

import secrets
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import jwt
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Rate limiting settings (v1.4)
RATE_LIMIT_ATTEMPTS = 5            # Max attempts per minute per IP
RATE_LIMIT_WINDOW = 60             # Window in seconds
_rate_limit_store = defaultdict(list)  # IP -> list of timestamps


def check_rate_limit(ip: str) -> bool:
    """
    Check if IP has exceeded rate limit.
    Returns True if allowed, False if rate limited.
    """
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    # Clean old entries
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if t > window_start]

    # Check limit
    if len(_rate_limit_store[ip]) >= RATE_LIMIT_ATTEMPTS:
        return False

    # Record this attempt
    _rate_limit_store[ip].append(now)
    return True

# JWT 密鑰 (生產環境應使用環境變數)
JWT_SECRET = "mirs-mobile-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 12

@dataclass
class PairingCode:
    """配對碼資料結構"""
    code: str
    expires_at: datetime
    allowed_roles: List[str]
    scopes: List[str]
    station_id: str
    created_by: str
    used: bool = False
    used_by_device: Optional[str] = None

@dataclass
class MobileDevice:
    """行動裝置資料結構"""
    device_id: str
    device_name: str
    staff_id: str
    staff_name: str
    role: str
    scopes: List[str]
    station_id: str
    paired_at: datetime
    last_seen: Optional[datetime] = None
    revoked: bool = False
    revoked_at: Optional[datetime] = None
    revoked_reason: Optional[str] = None


class MobileAuth:
    """MIRS Mobile 認證管理"""

    def __init__(self, db_path: str = "medical_inventory.db"):
        self.db_path = db_path
        self._init_tables()
        self._cleanup_expired_codes()

    def _get_conn(self) -> sqlite3.Connection:
        """取得資料庫連線"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        """初始化資料表"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # 配對碼資料表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mirs_mobile_pairing_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    expires_at DATETIME NOT NULL,
                    allowed_roles TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    used INTEGER DEFAULT 0,
                    used_by_device TEXT,
                    used_at DATETIME
                )
            """)

            # 已配對裝置資料表 (v1.4: 新增黑名單、IP、User-Agent)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mirs_mobile_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT UNIQUE NOT NULL,
                    device_name TEXT,
                    staff_id TEXT NOT NULL,
                    staff_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    paired_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen DATETIME,
                    revoked INTEGER DEFAULT 0,
                    revoked_at DATETIME,
                    revoked_reason TEXT,
                    blacklisted INTEGER DEFAULT 0,
                    revoked_by TEXT,
                    ip_address TEXT,
                    user_agent TEXT
                )
            """)

            # v1.4: 添加新欄位 (如果表已存在)
            try:
                cursor.execute("ALTER TABLE mirs_mobile_devices ADD COLUMN blacklisted INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # 欄位已存在
            try:
                cursor.execute("ALTER TABLE mirs_mobile_devices ADD COLUMN revoked_by TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE mirs_mobile_devices ADD COLUMN ip_address TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE mirs_mobile_devices ADD COLUMN user_agent TEXT")
            except sqlite3.OperationalError:
                pass

            # 行動操作日誌
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mirs_mobile_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT UNIQUE NOT NULL,
                    action_type TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    staff_id TEXT NOT NULL,
                    patient_id TEXT,
                    payload TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    hub_received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'PENDING',
                    adjustment_note TEXT,
                    review_status TEXT DEFAULT 'NOT_REQUIRED',
                    reviewer_staff_id TEXT,
                    reviewed_at DATETIME,
                    station_id TEXT NOT NULL
                )
            """)

            # 建立索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pairing_code ON mirs_mobile_pairing_codes(code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_device_id ON mirs_mobile_devices(device_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_action_id ON mirs_mobile_actions(action_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_action_device ON mirs_mobile_actions(device_id)")

            conn.commit()
            logger.info("MIRS Mobile 資料表初始化完成")
        except Exception as e:
            logger.error(f"初始化資料表失敗: {e}")
            raise
        finally:
            conn.close()

    def _cleanup_expired_codes(self):
        """清理過期配對碼"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM mirs_mobile_pairing_codes
                WHERE expires_at < datetime('now') OR used = 1
            """)
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info(f"清理了 {deleted} 個過期/已使用的配對碼")
        finally:
            conn.close()

    def generate_pairing_code(
        self,
        station_id: str,
        created_by: str = "admin",
        allowed_roles: List[str] = None,
        scopes: List[str] = None,
        expires_minutes: int = 5
    ) -> Dict[str, Any]:
        """
        產生 6 位數配對碼

        Args:
            station_id: 站點 ID
            created_by: 建立者
            allowed_roles: 允許的角色 ['nurse', 'doctor', 'admin']
            scopes: 權限範圍
            expires_minutes: 有效分鐘數 (預設 5)

        Returns:
            配對碼資訊
        """
        if allowed_roles is None:
            allowed_roles = ["nurse", "doctor"]

        if scopes is None:
            scopes = [
                "mirs:equipment:read",
                "mirs:equipment:write",
                "mirs:inventory:read",
                "mirs:resilience:read"
            ]

        # 產生 6 位數配對碼
        code = str(secrets.randbelow(1000000)).zfill(6)
        expires_at = datetime.now() + timedelta(minutes=expires_minutes)

        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # 確保配對碼唯一
            while True:
                cursor.execute("SELECT 1 FROM mirs_mobile_pairing_codes WHERE code = ?", (code,))
                if cursor.fetchone() is None:
                    break
                code = str(secrets.randbelow(1000000)).zfill(6)

            cursor.execute("""
                INSERT INTO mirs_mobile_pairing_codes
                (code, expires_at, allowed_roles, scopes, station_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                code,
                expires_at.isoformat(),
                json.dumps(allowed_roles),
                json.dumps(scopes),
                station_id,
                created_by
            ))
            conn.commit()

            logger.info(f"產生配對碼 {code} for station {station_id}, expires {expires_at}")

            return {
                "code": code,
                "expires_at": expires_at.isoformat(),
                "allowed_roles": allowed_roles,
                "scopes": scopes,
                "station_id": station_id
            }
        finally:
            conn.close()

    def is_device_blacklisted(self, device_id: str) -> bool:
        """檢查裝置是否在黑名單中 (v1.4)"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT blacklisted FROM mirs_mobile_devices
                WHERE device_id = ?
            """, (device_id,))
            row = cursor.fetchone()
            return row is not None and row['blacklisted'] == 1
        finally:
            conn.close()

    def exchange_pairing_code(
        self,
        pairing_code: str,
        device_id: str,
        device_name: str = None,
        staff_id: str = "STAFF-001",
        staff_name: str = "醫護人員",
        role: str = "nurse",
        ip_address: str = None,
        user_agent: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        交換配對碼取得 JWT Token (v1.4: 支援黑名單檢查)

        Args:
            pairing_code: 6 位數配對碼
            device_id: 裝置 UUID
            device_name: 裝置名稱 (選填)
            staff_id: 人員 ID
            staff_name: 人員名稱
            role: 角色
            ip_address: 客戶端 IP (v1.4)
            user_agent: 客戶端 User-Agent (v1.4)

        Returns:
            JWT Token 與相關資訊，或 None/錯誤字典
        """
        # v1.4: 先檢查黑名單
        if self.is_device_blacklisted(device_id):
            logger.warning(f"裝置 {device_id} 在黑名單中，拒絕配對")
            return {"error": "BLACKLISTED", "message": "此裝置已被永久封鎖，請聯繫管理員"}

        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # 查詢配對碼
            cursor.execute("""
                SELECT * FROM mirs_mobile_pairing_codes
                WHERE code = ? AND used = 0 AND expires_at > datetime('now')
            """, (pairing_code,))

            row = cursor.fetchone()
            if row is None:
                logger.warning(f"配對碼 {pairing_code} 無效或已過期")
                return None

            allowed_roles = json.loads(row['allowed_roles'])
            scopes = json.loads(row['scopes'])
            station_id = row['station_id']

            # 使用配對碼設定的角色（Hub 管理員指定的）
            # 如果 PWA 發送的角色在允許清單中，使用它；否則使用配對碼的第一個允許角色
            if role not in allowed_roles:
                logger.info(f"角色 {role} 不在允許清單中 {allowed_roles}，使用配對碼指定角色: {allowed_roles[0]}")
                role = allowed_roles[0]

            # 標記配對碼已使用
            cursor.execute("""
                UPDATE mirs_mobile_pairing_codes
                SET used = 1, used_by_device = ?, used_at = datetime('now')
                WHERE code = ?
            """, (device_id, pairing_code))

            # 註冊或更新裝置 (v1.4: 加入 IP 和 User-Agent)
            cursor.execute("""
                INSERT INTO mirs_mobile_devices
                (device_id, device_name, staff_id, staff_name, role, scopes, station_id, paired_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    device_name = excluded.device_name,
                    staff_id = excluded.staff_id,
                    staff_name = excluded.staff_name,
                    role = excluded.role,
                    scopes = excluded.scopes,
                    station_id = excluded.station_id,
                    paired_at = datetime('now'),
                    revoked = 0,
                    revoked_at = NULL,
                    revoked_reason = NULL,
                    ip_address = COALESCE(excluded.ip_address, ip_address),
                    user_agent = COALESCE(excluded.user_agent, user_agent)
            """, (
                device_id,
                device_name or f"Device-{device_id[:8]}",
                staff_id,
                staff_name,
                role,
                json.dumps(scopes),
                station_id,
                ip_address,
                user_agent
            ))

            conn.commit()

            # 產生 JWT Token
            token_payload = {
                "device_id": device_id,
                "staff_id": staff_id,
                "staff_name": staff_name,
                "role": role,
                "scopes": scopes,
                "station_id": station_id,
                "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
                "iat": datetime.utcnow()
            }

            token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

            logger.info(f"裝置 {device_id} 配對成功，角色: {role}, 站點: {station_id}")

            return {
                "access_token": token,
                "expires_in": JWT_EXPIRATION_HOURS * 3600,
                "station_id": station_id,
                "station_name": self._get_station_name(station_id),
                "staff_id": staff_id,
                "staff_name": staff_name,
                "role": role,
                "scopes": scopes
            }
        except Exception as e:
            logger.error(f"配對碼交換失敗: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        驗證 JWT Token

        Returns:
            Token payload 或 None (如果無效)
        """
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

            # 檢查裝置是否已被撤銷
            if self.is_device_revoked(payload.get("device_id")):
                logger.warning(f"裝置 {payload.get('device_id')} 已被撤銷")
                return None

            # 更新最後活動時間
            self._update_last_seen(payload.get("device_id"))

            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token 已過期")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Token 無效: {e}")
            return None

    def is_device_revoked(self, device_id: str) -> bool:
        """檢查裝置是否已被撤銷"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT revoked FROM mirs_mobile_devices
                WHERE device_id = ?
            """, (device_id,))
            row = cursor.fetchone()
            return row is not None and row['revoked'] == 1
        finally:
            conn.close()

    def revoke_device(self, device_id: str, reason: str, revoked_by: str = "admin") -> bool:
        """撤銷裝置"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            # v1.4: 檢查是否已黑名單
            cursor.execute("SELECT blacklisted FROM mirs_mobile_devices WHERE device_id = ?", (device_id,))
            row = cursor.fetchone()
            if row and row['blacklisted'] == 1:
                logger.warning(f"裝置 {device_id} 已在黑名單，無需撤銷")
                return False

            cursor.execute("""
                UPDATE mirs_mobile_devices
                SET revoked = 1, revoked_at = datetime('now'), revoked_reason = ?, revoked_by = ?
                WHERE device_id = ?
            """, (reason, revoked_by, device_id))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"裝置 {device_id} 已被撤銷: {reason}")
                return True
            return False
        finally:
            conn.close()

    def unrevoke_device(self, device_id: str, unrevoked_by: str = "admin") -> bool:
        """恢復已撤銷的裝置 (v1.4)"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            # 檢查是否已黑名單
            cursor.execute("SELECT blacklisted, revoked FROM mirs_mobile_devices WHERE device_id = ?", (device_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            if row['blacklisted'] == 1:
                logger.warning(f"裝置 {device_id} 在黑名單中，無法恢復")
                return False
            if row['revoked'] == 0:
                logger.info(f"裝置 {device_id} 未被撤銷")
                return False

            cursor.execute("""
                UPDATE mirs_mobile_devices
                SET revoked = 0, revoked_at = NULL, revoked_reason = NULL, revoked_by = NULL
                WHERE device_id = ?
            """, (device_id,))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"裝置 {device_id} 已恢復存取權限 by {unrevoked_by}")
                return True
            return False
        finally:
            conn.close()

    def blacklist_device(self, device_id: str, reason: str, blacklisted_by: str = "admin") -> bool:
        """將裝置加入黑名單 (v1.4)"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            # 檢查裝置是否存在
            cursor.execute("SELECT device_id FROM mirs_mobile_devices WHERE device_id = ?", (device_id,))
            row = cursor.fetchone()

            if row is None:
                # 裝置不存在，建立黑名單記錄
                cursor.execute("""
                    INSERT INTO mirs_mobile_devices
                    (device_id, device_name, staff_id, staff_name, role, scopes, station_id,
                     blacklisted, revoked, revoked_reason, revoked_by, revoked_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, datetime('now'))
                """, (
                    device_id,
                    f"Blacklisted-{device_id[:8]}",
                    "BLOCKED",
                    "已封鎖",
                    "blocked",
                    "[]",
                    "N/A",
                    reason,
                    blacklisted_by
                ))
            else:
                cursor.execute("""
                    UPDATE mirs_mobile_devices
                    SET blacklisted = 1, revoked = 1,
                        revoked_at = datetime('now'), revoked_reason = ?, revoked_by = ?
                    WHERE device_id = ?
                """, (reason, blacklisted_by, device_id))

            conn.commit()
            logger.info(f"裝置 {device_id} 已加入黑名單: {reason}")
            return True
        except Exception as e:
            logger.error(f"加入黑名單失敗: {e}")
            return False
        finally:
            conn.close()

    def unblacklist_device(self, device_id: str, unblacklisted_by: str = "admin") -> bool:
        """將裝置從黑名單移除 (v1.4)"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT blacklisted FROM mirs_mobile_devices WHERE device_id = ?", (device_id,))
            row = cursor.fetchone()

            if row is None:
                return False
            if row['blacklisted'] == 0:
                logger.info(f"裝置 {device_id} 不在黑名單中")
                return False

            cursor.execute("""
                UPDATE mirs_mobile_devices
                SET blacklisted = 0, revoked = 0,
                    revoked_at = NULL, revoked_reason = NULL, revoked_by = NULL
                WHERE device_id = ?
            """, (device_id,))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"裝置 {device_id} 已從黑名單移除 by {unblacklisted_by}")
                return True
            return False
        finally:
            conn.close()

    def _update_last_seen(self, device_id: str):
        """更新裝置最後活動時間"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE mirs_mobile_devices
                SET last_seen = datetime('now')
                WHERE device_id = ?
            """, (device_id,))
            conn.commit()
        finally:
            conn.close()

    def _get_station_name(self, station_id: str) -> str:
        """取得站點名稱"""
        # 這裡可以從配置或資料庫取得站點名稱
        station_names = {
            "TC-01": "醫療站 TC-01",
            "BORP-01": "備援手術站 BORP-01",
            "BORP-DNO-01": "備援手術站 BORP-DNO-01",
            "LOG-HUB": "物資中心"
        }
        return station_names.get(station_id, f"站點 {station_id}")

    def log_action(
        self,
        action_id: str,
        action_type: str,
        device_id: str,
        staff_id: str,
        station_id: str,
        payload: Dict[str, Any],
        patient_id: str = None,
        created_at: str = None
    ) -> bool:
        """記錄行動操作"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO mirs_mobile_actions
                (action_id, action_type, device_id, staff_id, patient_id, payload,
                 created_at, station_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED')
                ON CONFLICT(action_id) DO NOTHING
            """, (
                action_id,
                action_type,
                device_id,
                staff_id,
                patient_id,
                json.dumps(payload),
                created_at or datetime.now().isoformat(),
                station_id
            ))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"記錄操作失敗: {e}")
            return False
        finally:
            conn.close()

    def get_paired_devices(self, station_id: str = None) -> List[Dict[str, Any]]:
        """取得已配對裝置列表 (v1.4: 包含黑名單狀態)"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            if station_id:
                cursor.execute("""
                    SELECT * FROM mirs_mobile_devices
                    WHERE station_id = ?
                    ORDER BY paired_at DESC
                """, (station_id,))
            else:
                cursor.execute("""
                    SELECT * FROM mirs_mobile_devices
                    ORDER BY paired_at DESC
                """)

            devices = []
            for row in cursor.fetchall():
                # v1.4: 安全讀取可能不存在的新欄位
                try:
                    blacklisted = bool(row['blacklisted']) if 'blacklisted' in row.keys() else False
                    ip_address = row['ip_address'] if 'ip_address' in row.keys() else None
                    user_agent = row['user_agent'] if 'user_agent' in row.keys() else None
                    revoked_by = row['revoked_by'] if 'revoked_by' in row.keys() else None
                except (KeyError, IndexError):
                    blacklisted = False
                    ip_address = None
                    user_agent = None
                    revoked_by = None

                devices.append({
                    "device_id": row['device_id'],
                    "device_name": row['device_name'],
                    "staff_id": row['staff_id'],
                    "staff_name": row['staff_name'],
                    "role": row['role'],
                    "station_id": row['station_id'],
                    "paired_at": row['paired_at'],
                    "last_seen": row['last_seen'],
                    "revoked": bool(row['revoked']),
                    "blacklisted": blacklisted,
                    "revoked_reason": row['revoked_reason'] if row['revoked_reason'] else None,
                    "revoked_by": revoked_by,
                    "ip_address": ip_address,
                    "user_agent": user_agent
                })
            return devices
        finally:
            conn.close()
