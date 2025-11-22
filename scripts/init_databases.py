#!/usr/bin/env python3
"""
資料庫初始化腳本
初始化一般庫存資料庫和藥局資料庫，並同步站點後設資料
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime


def init_database(db_path: str, schema_file: str) -> bool:
    """
    初始化資料庫

    Args:
        db_path: 資料庫檔案路徑
        schema_file: Schema SQL 檔案路徑

    Returns:
        是否成功
    """
    try:
        # 確保資料庫目錄存在
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            print(f"✓ 創建目錄: {db_dir}")

        # 讀取 Schema SQL 檔案
        if not os.path.exists(schema_file):
            print(f"✗ Schema 檔案不存在: {schema_file}")
            return False

        with open(schema_file, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        # 連接資料庫（如果不存在會自動創建）
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 執行 Schema SQL
        cursor.executescript(schema_sql)
        conn.commit()

        # 驗證表格是否創建成功
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()

        conn.close()

        print(f"✓ 資料庫初始化成功: {db_path}")
        print(f"  - 創建了 {len(tables)} 個表格")

        return True

    except Exception as e:
        print(f"✗ 資料庫初始化失敗: {db_path}")
        print(f"  錯誤: {e}")
        return False


def sync_station_metadata(config_path: str, general_db: str, pharmacy_db: str) -> bool:
    """
    從配置檔案同步站點後設資料到兩個資料庫

    Args:
        config_path: 配置檔案路徑 (config/station.json)
        general_db: 一般庫存資料庫路徑
        pharmacy_db: 藥局資料庫路徑

    Returns:
        是否成功
    """
    try:
        # 讀取配置檔案
        if not os.path.exists(config_path):
            print(f"✗ 配置檔案不存在: {config_path}")
            return False

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 提取站點資訊
        station = config.get('station', {})
        organization = config.get('organization', {})
        location = config.get('location', {})
        capabilities = config.get('capabilities', {})

        # 準備插入資料
        station_data = {
            'station_uuid': station.get('uuid'),
            'station_code': station.get('code', 'UNKNOWN'),
            'station_name': station.get('name', 'Unknown Station'),
            'station_type': station.get('station_type', 'THIRD_CLASS_BORP'),
            'admin_level': station.get('admin_level', 'STATION_LOCAL'),
            'parent_node': station.get('parent_node'),
            'organization_code': organization.get('code'),
            'organization_name': organization.get('name'),
            'region_code': location.get('region_code'),
            'region_name': location.get('region_name'),
            'beds': capabilities.get('beds', 0),
            'daily_capacity': capabilities.get('daily_capacity', 0),
            'has_pharmacy': 1 if capabilities.get('has_pharmacy', False) else 0,
            'has_surgery': 1 if capabilities.get('has_surgery', False) else 0,
            'has_emergency': 1 if capabilities.get('has_emergency', False) else 0,
            'storage_capacity_m3': capabilities.get('storage_capacity_m3', 0),
            'status': station.get('status', 'ACTIVE'),
            'created_at': station.get('created_at') or datetime.now().isoformat(),
        }

        # 同步到一般庫存資料庫
        conn_general = sqlite3.connect(general_db)
        cursor_general = conn_general.cursor()

        # 檢查是否已存在
        cursor_general.execute(
            "SELECT id FROM station_metadata WHERE station_code = ?",
            (station_data['station_code'],)
        )
        existing = cursor_general.fetchone()

        if existing:
            # 更新現有記錄
            cursor_general.execute("""
                UPDATE station_metadata SET
                    station_uuid = ?,
                    station_name = ?,
                    station_type = ?,
                    admin_level = ?,
                    parent_node = ?,
                    organization_code = ?,
                    organization_name = ?,
                    region_code = ?,
                    region_name = ?,
                    beds = ?,
                    daily_capacity = ?,
                    has_pharmacy = ?,
                    has_surgery = ?,
                    has_emergency = ?,
                    storage_capacity_m3 = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE station_code = ?
            """, (
                station_data['station_uuid'],
                station_data['station_name'],
                station_data['station_type'],
                station_data['admin_level'],
                station_data['parent_node'],
                station_data['organization_code'],
                station_data['organization_name'],
                station_data['region_code'],
                station_data['region_name'],
                station_data['beds'],
                station_data['daily_capacity'],
                station_data['has_pharmacy'],
                station_data['has_surgery'],
                station_data['has_emergency'],
                station_data['storage_capacity_m3'],
                station_data['status'],
                station_data['station_code']
            ))
            action_general = "更新"
        else:
            # 插入新記錄
            cursor_general.execute("""
                INSERT INTO station_metadata (
                    station_uuid, station_code, station_name, station_type, admin_level,
                    parent_node, organization_code, organization_name, region_code, region_name,
                    beds, daily_capacity, has_pharmacy, has_surgery, has_emergency,
                    storage_capacity_m3, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                station_data['station_uuid'],
                station_data['station_code'],
                station_data['station_name'],
                station_data['station_type'],
                station_data['admin_level'],
                station_data['parent_node'],
                station_data['organization_code'],
                station_data['organization_name'],
                station_data['region_code'],
                station_data['region_name'],
                station_data['beds'],
                station_data['daily_capacity'],
                station_data['has_pharmacy'],
                station_data['has_surgery'],
                station_data['has_emergency'],
                station_data['storage_capacity_m3'],
                station_data['status'],
                station_data['created_at']
            ))
            action_general = "插入"

        conn_general.commit()
        conn_general.close()

        print(f"✓ 一般庫存資料庫 - 站點資料{action_general}成功")

        # 同步到藥局資料庫
        conn_pharmacy = sqlite3.connect(pharmacy_db)
        cursor_pharmacy = conn_pharmacy.cursor()

        # 檢查是否已存在
        cursor_pharmacy.execute(
            "SELECT id FROM station_metadata WHERE station_code = ?",
            (station_data['station_code'],)
        )
        existing = cursor_pharmacy.fetchone()

        if existing:
            # 更新現有記錄
            cursor_pharmacy.execute("""
                UPDATE station_metadata SET
                    station_uuid = ?,
                    station_name = ?,
                    station_type = ?,
                    admin_level = ?,
                    parent_node = ?,
                    organization_code = ?,
                    organization_name = ?,
                    region_code = ?,
                    region_name = ?,
                    beds = ?,
                    daily_capacity = ?,
                    has_pharmacy = ?,
                    has_surgery = ?,
                    has_emergency = ?,
                    storage_capacity_m3 = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE station_code = ?
            """, (
                station_data['station_uuid'],
                station_data['station_name'],
                station_data['station_type'],
                station_data['admin_level'],
                station_data['parent_node'],
                station_data['organization_code'],
                station_data['organization_name'],
                station_data['region_code'],
                station_data['region_name'],
                station_data['beds'],
                station_data['daily_capacity'],
                station_data['has_pharmacy'],
                station_data['has_surgery'],
                station_data['has_emergency'],
                station_data['storage_capacity_m3'],
                station_data['status'],
                station_data['station_code']
            ))
            action_pharmacy = "更新"
        else:
            # 插入新記錄
            cursor_pharmacy.execute("""
                INSERT INTO station_metadata (
                    station_uuid, station_code, station_name, station_type, admin_level,
                    parent_node, organization_code, organization_name, region_code, region_name,
                    beds, daily_capacity, has_pharmacy, has_surgery, has_emergency,
                    storage_capacity_m3, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                station_data['station_uuid'],
                station_data['station_code'],
                station_data['station_name'],
                station_data['station_type'],
                station_data['admin_level'],
                station_data['parent_node'],
                station_data['organization_code'],
                station_data['organization_name'],
                station_data['region_code'],
                station_data['region_name'],
                station_data['beds'],
                station_data['daily_capacity'],
                station_data['has_pharmacy'],
                station_data['has_surgery'],
                station_data['has_emergency'],
                station_data['storage_capacity_m3'],
                station_data['status'],
                station_data['created_at']
            ))
            action_pharmacy = "插入"

        conn_pharmacy.commit()
        conn_pharmacy.close()

        print(f"✓ 藥局資料庫 - 站點資料{action_pharmacy}成功")

        # 顯示同步的資料摘要
        print(f"\n站點資訊摘要:")
        print(f"  - 站點代碼: {station_data['station_code']}")
        print(f"  - 站點名稱: {station_data['station_name']}")
        print(f"  - 站點類型: {station_data['station_type']}")
        print(f"  - 管理層級: {station_data['admin_level']}")
        print(f"  - 床位數: {station_data['beds']}")
        print(f"  - 有藥局: {'是' if station_data['has_pharmacy'] else '否'}")

        return True

    except Exception as e:
        print(f"✗ 站點資料同步失敗")
        print(f"  錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函數"""
    print("=" * 70)
    print("資料庫初始化工具 v1.5.0")
    print("=" * 70)

    # 檢查命令行參數
    if len(sys.argv) < 2:
        print("\n使用方式:")
        print(f"  python {sys.argv[0]} <config_path>")
        print(f"\n範例:")
        print(f"  python {sys.argv[0]} config/station.json")
        sys.exit(1)

    config_path = sys.argv[1]

    # 取得專案根目錄
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # 轉換為絕對路徑
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_root, config_path)

    # 讀取配置以取得資料庫路徑
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 從配置檔案取得資料庫路徑
    db_config = config.get('database', {})
    general_db_path = db_config.get('general_inventory_path', 'database/general_inventory.db')
    pharmacy_db_path = db_config.get('pharmacy_path', 'database/pharmacy.db')

    # 轉換為絕對路徑
    general_db = os.path.join(project_root, general_db_path)
    pharmacy_db = os.path.join(project_root, pharmacy_db_path)

    # 定義 Schema 檔案路徑
    general_schema = os.path.join(project_root, 'database', 'schema_general_inventory.sql')
    pharmacy_schema = os.path.join(project_root, 'database', 'schema_pharmacy.sql')

    print(f"\n配置檔案: {config_path}")
    print(f"專案根目錄: {project_root}")
    print()

    # Step 1: 初始化一般庫存資料庫
    print("Step 1: 初始化一般庫存資料庫")
    print("-" * 70)
    success_general = init_database(general_db, general_schema)
    print()

    # Step 2: 初始化藥局資料庫
    print("Step 2: 初始化藥局資料庫")
    print("-" * 70)
    success_pharmacy = init_database(pharmacy_db, pharmacy_schema)
    print()

    # Step 3: 同步站點後設資料
    if success_general and success_pharmacy:
        print("Step 3: 同步站點後設資料")
        print("-" * 70)
        success_sync = sync_station_metadata(config_path, general_db, pharmacy_db)
        print()
    else:
        print("✗ 資料庫初始化失敗，跳過站點資料同步")
        success_sync = False

    # 總結
    print("=" * 70)
    if success_general and success_pharmacy and success_sync:
        print("✅ 資料庫初始化完成！")
        print()
        print("已創建的資料庫:")
        print(f"  - {general_db}")
        print(f"  - {pharmacy_db}")
    else:
        print("❌ 資料庫初始化失敗")
        sys.exit(1)
    print("=" * 70)


if __name__ == '__main__':
    main()
