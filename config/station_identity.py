"""
MIRS 全域唯一站點識別系統
Station Identity Management System

生成格式: {TYPE}-{TIMESTAMP}-{UUID}
範例: HC-250130-a3f2

站點類型代碼:
- HC: Health Center (衛生所/基層醫療站)
- SURG: Surgical Station (手術站)
- LOGI: Logistics Hub (後勤中樞)
- HOSP: Hospital (醫院/自訂醫療機構)
"""

import uuid
from datetime import datetime
from typing import Dict, Optional


class StationIdentity:
    """全域唯一站點識別系統"""

    # 站點類型映射
    STATION_TYPES = {
        'health_center': {
            'prefix': 'HC',
            'name': '衛生所',
            'name_en': 'Health Center',
            'category': 'HEALTH_CENTER'
        },
        'surgical_station': {
            'prefix': 'SURG',
            'name': '手術站',
            'name_en': 'Surgical Station',
            'category': 'SURGICAL_STATION'
        },
        'logistics_hub': {
            'prefix': 'LOGI',
            'name': '後勤中樞',
            'name_en': 'Logistics Hub',
            'category': 'LOGISTICS_HUB'
        },
        'hospital_custom': {
            'prefix': 'HOSP',
            'name': '醫療機構',
            'name_en': 'Hospital',
            'category': 'HOSPITAL'
        }
    }

    # 反向映射：prefix -> profile
    PREFIX_TO_PROFILE = {
        'HC': 'health_center',
        'SURG': 'surgical_station',
        'LOGI': 'logistics_hub',
        'HOSP': 'hospital_custom'
    }

    @staticmethod
    def generate_station_id(
        station_type: str,
        region_code: str = "TW",
        org_code: Optional[str] = None
    ) -> str:
        """
        生成全域唯一站點ID

        Args:
            station_type: Profile名稱 (health_center, surgical_station, logistics_hub, hospital_custom)
            region_code: 區域代碼 (預設 TW)
            org_code: 組織代碼 (選填，用於區分不同組織)

        Returns:
            格式化的站點ID

        Examples:
            >>> StationIdentity.generate_station_id('health_center')
            'HC-250130-a3f2'

            >>> StationIdentity.generate_station_id('health_center', org_code='CUTEMO')
            'CUTEMO-HC-250130-a3f2'
        """
        if station_type not in StationIdentity.STATION_TYPES:
            raise ValueError(f"Invalid station type: {station_type}")

        # 取得站點類型前綴
        prefix = StationIdentity.STATION_TYPES[station_type]['prefix']

        # 生成時間戳（年月日格式：YYMMDD）
        timestamp = datetime.now().strftime("%y%m%d")

        # 生成唯一識別碼（UUID4 前4碼）
        unique_id = str(uuid.uuid4())[:4]

        # 組合站點ID
        if org_code:
            return f"{org_code}-{prefix}-{timestamp}-{unique_id}"
        else:
            return f"{prefix}-{timestamp}-{unique_id}"

    @staticmethod
    def parse_station_id(station_id: str) -> Dict[str, str]:
        """
        解析站點ID

        Args:
            station_id: 站點ID字串

        Returns:
            包含解析結果的字典

        Examples:
            >>> StationIdentity.parse_station_id('HC-250130-a3f2')
            {'prefix': 'HC', 'date': '250130', 'uuid': 'a3f2', 'org_code': None}

            >>> StationIdentity.parse_station_id('CUTEMO-HC-250130-a3f2')
            {'prefix': 'HC', 'date': '250130', 'uuid': 'a3f2', 'org_code': 'CUTEMO'}
        """
        parts = station_id.split('-')

        if len(parts) == 3:
            # 格式: {PREFIX}-{DATE}-{UUID}
            return {
                'prefix': parts[0],
                'date': parts[1],
                'uuid': parts[2],
                'org_code': None,
                'profile': StationIdentity.PREFIX_TO_PROFILE.get(parts[0], 'unknown')
            }
        elif len(parts) == 4:
            # 格式: {ORG}-{PREFIX}-{DATE}-{UUID}
            return {
                'org_code': parts[0],
                'prefix': parts[1],
                'date': parts[2],
                'uuid': parts[3],
                'profile': StationIdentity.PREFIX_TO_PROFILE.get(parts[1], 'unknown')
            }
        else:
            raise ValueError(f"Invalid station ID format: {station_id}")

    @staticmethod
    def get_station_type_info(profile: str) -> Dict[str, str]:
        """
        取得站點類型資訊

        Args:
            profile: Profile名稱

        Returns:
            站點類型資訊字典
        """
        return StationIdentity.STATION_TYPES.get(profile, {})

    @staticmethod
    def validate_station_id(station_id: str) -> bool:
        """
        驗證站點ID格式是否正確

        Args:
            station_id: 站點ID字串

        Returns:
            True if valid, False otherwise
        """
        try:
            parsed = StationIdentity.parse_station_id(station_id)
            return parsed['prefix'] in StationIdentity.PREFIX_TO_PROFILE
        except (ValueError, KeyError, IndexError):
            return False

    @staticmethod
    def generate_display_name(station_id: str, custom_name: Optional[str] = None) -> str:
        """
        生成站點顯示名稱

        Args:
            station_id: 站點ID
            custom_name: 自訂名稱（選填）

        Returns:
            格式化的顯示名稱

        Examples:
            >>> StationIdentity.generate_display_name('HC-250130-a3f2')
            'HC-250130-a3f2 衛生所'

            >>> StationIdentity.generate_display_name('HC-250130-a3f2', '臺北衛生所')
            'HC-250130-a3f2 臺北衛生所'
        """
        try:
            parsed = StationIdentity.parse_station_id(station_id)
            profile = parsed['profile']
            type_info = StationIdentity.STATION_TYPES.get(profile, {})

            if custom_name:
                return f"{station_id} {custom_name}"
            else:
                default_name = type_info.get('name', '醫療站')
                return f"{station_id} {default_name}"
        except ValueError:
            return station_id


# 使用範例
if __name__ == "__main__":
    # 生成不同類型的站點ID
    print("=== 生成站點ID範例 ===")
    for profile in StationIdentity.STATION_TYPES.keys():
        station_id = StationIdentity.generate_station_id(profile)
        print(f"{profile:20} -> {station_id}")

    print("\n=== 帶組織代碼的站點ID ===")
    station_id_with_org = StationIdentity.generate_station_id('health_center', org_code='CUTEMO')
    print(f"With org code: {station_id_with_org}")

    print("\n=== 解析站點ID ===")
    test_ids = [
        'HC-250130-a3f2',
        'CUTEMO-HC-250130-a3f2',
        'SURG-250130-b5e3'
    ]
    for test_id in test_ids:
        parsed = StationIdentity.parse_station_id(test_id)
        print(f"{test_id:30} -> {parsed}")

    print("\n=== 驗證站點ID ===")
    valid_id = 'HC-250130-a3f2'
    invalid_id = 'INVALID-ID'
    print(f"{valid_id} is valid: {StationIdentity.validate_station_id(valid_id)}")
    print(f"{invalid_id} is valid: {StationIdentity.validate_station_id(invalid_id)}")

    print("\n=== 生成顯示名稱 ===")
    print(StationIdentity.generate_display_name('HC-250130-a3f2'))
    print(StationIdentity.generate_display_name('HC-250130-a3f2', '臺北衛生所'))
