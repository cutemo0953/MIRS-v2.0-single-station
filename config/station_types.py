"""
站點類型定義模組
定義不同等級的站點類型與管理層級
"""

from enum import Enum
from typing import Dict, Any


class StationType(Enum):
    """站點類型"""
    FIRST_CLASS = "FIRST_CLASS"           # 一級站：大型醫院或區域醫療中心
    SECOND_CLASS = "SECOND_CLASS"         # 二級站：中型醫院或地區醫療站
    THIRD_CLASS_BORP = "THIRD_CLASS_BORP" # 三級站：基層醫療站（BORP: Basic Outpost/Rural Post）


class AdminLevel(Enum):
    """管理層級"""
    STATION_LOCAL = "STATION_LOCAL"  # 站點層級（最基層）
    DISTRICT = "DISTRICT"            # 區域層級
    COUNTY = "COUNTY"                # 縣市層級
    MOHW = "MOHW"                    # 中央層級（Ministry of Health and Welfare）


# 站點能力定義
STATION_CAPABILITIES: Dict[StationType, Dict[str, Any]] = {
    StationType.FIRST_CLASS: {
        "beds": 100,                    # 床位數
        "daily_capacity": 500,          # 每日門診量
        "has_pharmacy": True,           # 是否有藥局
        "has_surgery": True,            # 是否有手術室
        "has_icu": True,                # 是否有加護病房
        "has_emergency": True,          # 是否有急診
        "has_blood_bank": True,         # 是否有血庫
        "can_store_controlled": True,   # 是否可儲存管制藥品
        "max_staff": 200,               # 最大員工數
        "storage_capacity_m3": 100,     # 儲存空間（立方公尺）
        "backup_power": True,           # 是否有備用電源
        "satellite_comms": True,        # 是否有衛星通訊
        "can_perform_major_surgery": True,     # 可執行重大手術
        "trauma_level": 1,              # 創傷等級（1最高）
        "description": "大型醫療中心，具備完整醫療能力"
    },

    StationType.SECOND_CLASS: {
        "beds": 50,
        "daily_capacity": 200,
        "has_pharmacy": True,
        "has_surgery": True,
        "has_icu": False,
        "has_emergency": True,
        "has_blood_bank": True,
        "can_store_controlled": True,
        "max_staff": 80,
        "storage_capacity_m3": 50,
        "backup_power": True,
        "satellite_comms": True,
        "can_perform_major_surgery": False,
        "trauma_level": 2,
        "description": "中型醫療站，具備基本醫療與手術能力"
    },

    StationType.THIRD_CLASS_BORP: {
        "beds": 20,
        "daily_capacity": 50,
        "has_pharmacy": True,           # 基層也可有藥局
        "has_surgery": False,           # 無手術室
        "has_icu": False,
        "has_emergency": True,          # 有急診處置能力
        "has_blood_bank": False,        # 無血庫，依賴上級供應
        "can_store_controlled": True,   # 可儲存少量管制藥品
        "max_staff": 30,
        "storage_capacity_m3": 20,
        "backup_power": True,           # 有備用電源
        "satellite_comms": True,        # 有衛星通訊
        "can_perform_major_surgery": False,
        "trauma_level": 3,
        "description": "基層醫療站，提供初級醫療照護與緊急處置"
    }
}


def get_station_capability(station_type: StationType, capability: str) -> Any:
    """
    獲取特定站點類型的能力值

    Args:
        station_type: 站點類型
        capability: 能力名稱

    Returns:
        能力值，如果不存在則返回 None
    """
    return STATION_CAPABILITIES.get(station_type, {}).get(capability)


def can_station_perform(station_type: StationType, action: str) -> bool:
    """
    檢查站點是否可以執行特定動作

    Args:
        station_type: 站點類型
        action: 動作名稱（如 'surgery', 'store_controlled_drugs'）

    Returns:
        是否可以執行
    """
    capability_map = {
        'surgery': 'has_surgery',
        'major_surgery': 'can_perform_major_surgery',
        'store_controlled_drugs': 'can_store_controlled',
        'blood_storage': 'has_blood_bank',
        'emergency_care': 'has_emergency',
        'icu_care': 'has_icu',
        'pharmacy_services': 'has_pharmacy'
    }

    capability_key = capability_map.get(action, action)
    return get_station_capability(station_type, capability_key) or False


def get_parent_station_type(station_type: StationType) -> StationType:
    """
    獲取上級站點類型

    Args:
        station_type: 當前站點類型

    Returns:
        上級站點類型，如果已是最高級則返回自己
    """
    hierarchy = {
        StationType.THIRD_CLASS_BORP: StationType.SECOND_CLASS,
        StationType.SECOND_CLASS: StationType.FIRST_CLASS,
        StationType.FIRST_CLASS: StationType.FIRST_CLASS  # 最高級
    }
    return hierarchy.get(station_type, station_type)


def validate_station_config(station_type: StationType, config: Dict[str, Any]) -> tuple[bool, str]:
    """
    驗證站點配置是否符合其類型的能力限制

    Args:
        station_type: 站點類型
        config: 站點配置

    Returns:
        (是否有效, 錯誤訊息)
    """
    capabilities = STATION_CAPABILITIES.get(station_type)
    if not capabilities:
        return False, f"未知的站點類型: {station_type}"

    # 檢查床位數
    if 'beds' in config and config['beds'] > capabilities['beds']:
        return False, f"床位數 {config['beds']} 超過站點類型限制 {capabilities['beds']}"

    # 檢查員工數
    if 'staff_count' in config and config['staff_count'] > capabilities['max_staff']:
        return False, f"員工數 {config['staff_count']} 超過站點類型限制 {capabilities['max_staff']}"

    # 檢查是否嘗試啟用不支援的功能
    unsupported_features = []
    if config.get('has_icu') and not capabilities['has_icu']:
        unsupported_features.append('ICU')
    if config.get('has_surgery') and not capabilities['has_surgery']:
        unsupported_features.append('手術室')
    if config.get('has_blood_bank') and not capabilities['has_blood_bank']:
        unsupported_features.append('血庫')

    if unsupported_features:
        return False, f"站點類型不支援以下功能: {', '.join(unsupported_features)}"

    return True, ""


# 導出所有公開介面
__all__ = [
    'StationType',
    'AdminLevel',
    'STATION_CAPABILITIES',
    'get_station_capability',
    'can_station_perform',
    'get_parent_station_type',
    'validate_station_config'
]
