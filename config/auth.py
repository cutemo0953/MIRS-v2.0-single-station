"""
PIN 認證系統
管理使用者身份驗證與權限控制
"""

from enum import Enum
import hashlib
from typing import Dict, Any, List


class UserRole(Enum):
    """使用者角色"""
    ADMIN = "ADMIN"
    PHARMACIST = "PHARMACIST"
    NURSE = "NURSE"
    PHYSICIAN = "PHYSICIAN"
    EMT = "EMT"  # Emergency Medical Technician - 緊急醫療技術員
    LOGISTICS = "LOGISTICS"


# 權限矩陣
PERMISSION_MATRIX: Dict[str, List[UserRole]] = {
    'PHARMACY': [UserRole.PHARMACIST, UserRole.NURSE, UserRole.PHYSICIAN, UserRole.ADMIN],
    'GENERAL': [UserRole.PHARMACIST, UserRole.NURSE, UserRole.EMT, UserRole.LOGISTICS, UserRole.ADMIN],
    'CONTROLLED_DRUG': [UserRole.PHARMACIST, UserRole.ADMIN]
}


def hash_pin(pin: str) -> str:
    """
    使用 SHA256 加密 PIN

    Args:
        pin: 原始 PIN

    Returns:
        SHA256 hash
    """
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()


# PIN 註冊表（使用 SHA256 hash）
PIN_REGISTRY: Dict[str, Dict[str, Any]] = {
    hash_pin("1234"): {
        "user_id": "USER001",
        "name": "王藥師",
        "role": UserRole.PHARMACIST
    },
    hash_pin("2345"): {
        "user_id": "USER002",
        "name": "李護理師",
        "role": UserRole.NURSE
    },
    hash_pin("9999"): {
        "user_id": "ADMIN",
        "name": "管理員",
        "role": UserRole.ADMIN
    }
}


def verify_pin(pin: str) -> Dict[str, Any]:
    """
    驗證 PIN 並回傳使用者資料

    Args:
        pin: 使用者輸入的 PIN

    Returns:
        使用者資料字典

    Raises:
        ValueError: PIN 錯誤
    """
    pin_hash = hash_pin(pin)

    if pin_hash not in PIN_REGISTRY:
        raise ValueError("PIN 錯誤")

    return PIN_REGISTRY[pin_hash]


def check_permission(user_role: UserRole, inventory_type: str) -> bool:
    """
    檢查權限是否足夠

    Args:
        user_role: 使用者角色
        inventory_type: 庫存類型 (PHARMACY/GENERAL/CONTROLLED_DRUG)

    Returns:
        是否有權限
    """
    if inventory_type not in PERMISSION_MATRIX:
        return False

    return user_role in PERMISSION_MATRIX[inventory_type]


def add_user(pin: str, user_id: str, name: str, role: UserRole) -> bool:
    """
    新增使用者到 PIN 註冊表

    Args:
        pin: 使用者 PIN
        user_id: 使用者ID
        name: 使用者姓名
        role: 使用者角色

    Returns:
        是否成功
    """
    pin_hash = hash_pin(pin)

    if pin_hash in PIN_REGISTRY:
        return False  # PIN 已存在

    PIN_REGISTRY[pin_hash] = {
        "user_id": user_id,
        "name": name,
        "role": role
    }

    return True


def get_all_roles() -> List[UserRole]:
    """
    取得所有可用角色

    Returns:
        角色列表
    """
    return list(UserRole)


def get_users_by_role(role: UserRole) -> List[Dict[str, Any]]:
    """
    取得特定角色的所有使用者

    Args:
        role: 使用者角色

    Returns:
        使用者列表
    """
    users = []
    for user_data in PIN_REGISTRY.values():
        if user_data['role'] == role:
            users.append(user_data)
    return users


# 導出所有公開介面
__all__ = [
    'UserRole',
    'PERMISSION_MATRIX',
    'PIN_REGISTRY',
    'hash_pin',
    'verify_pin',
    'check_permission',
    'add_user',
    'get_all_roles',
    'get_users_by_role'
]
