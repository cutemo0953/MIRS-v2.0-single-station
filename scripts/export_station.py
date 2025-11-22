#!/usr/bin/env python3
"""
資料匯出腳本
從兩個資料庫匯出站點資料到統一的 JSON 格式
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime


def read_config(config_path: str) -> dict:
    """
    讀取站點配置檔案

    Args:
        config_path: 配置檔案路徑

    Returns:
        配置字典
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"✗ 讀取配置檔案失敗: {e}")
        sys.exit(1)


def export_pharmacy_data(db_path: str) -> dict:
    """
    從藥局資料庫匯出資料

    Args:
        db_path: 藥局資料庫路徑

    Returns:
        藥局資料字典
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # 使用 Row 物件以便轉換為字典
        cursor = conn.cursor()

        # 匯出 medicines
        cursor.execute("SELECT * FROM medicines")
        medicines = [dict(row) for row in cursor.fetchall()]

        # 匯出 pharmacy_transactions
        cursor.execute("SELECT * FROM pharmacy_transactions")
        transactions = [dict(row) for row in cursor.fetchall()]

        # 匯出 controlled_drug_log
        cursor.execute("SELECT * FROM controlled_drug_log")
        controlled_drug_logs = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return {
            "medicines": medicines,
            "transactions": transactions,
            "controlled_drug_logs": controlled_drug_logs,
            "record_count": {
                "medicines": len(medicines),
                "transactions": len(transactions),
                "controlled_drug_logs": len(controlled_drug_logs)
            }
        }

    except Exception as e:
        print(f"✗ 從藥局資料庫匯出失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def export_general_data(db_path: str) -> dict:
    """
    從一般庫存資料庫匯出資料

    Args:
        db_path: 一般庫存資料庫路徑

    Returns:
        一般庫存資料字典
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 匯出 items
        cursor.execute("SELECT * FROM items")
        items = [dict(row) for row in cursor.fetchall()]

        # 匯出 transactions
        cursor.execute("SELECT * FROM transactions")
        transactions = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return {
            "items": items,
            "transactions": transactions,
            "record_count": {
                "items": len(items),
                "transactions": len(transactions)
            }
        }

    except Exception as e:
        print(f"✗ 從一般庫存資料庫匯出失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def get_station_metadata(db_path: str) -> dict:
    """
    從資料庫取得站點後設資料

    Args:
        db_path: 資料庫路徑

    Returns:
        站點後設資料字典
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM station_metadata LIMIT 1")
        row = cursor.fetchone()

        conn.close()

        if row:
            return dict(row)
        else:
            return {}

    except Exception as e:
        print(f"✗ 讀取站點資料失敗: {e}")
        return {}


def export_station_data(config_path: str, output_path: str) -> bool:
    """
    匯出站點資料

    Args:
        config_path: 配置檔案路徑
        output_path: 輸出檔案路徑

    Returns:
        是否成功
    """
    try:
        # 讀取配置
        config = read_config(config_path)

        # 取得專案根目錄
        if os.path.isabs(config_path):
            project_root = Path(config_path).parent.parent
        else:
            script_dir = Path(__file__).parent
            project_root = script_dir.parent

        # 取得資料庫路徑
        general_db = os.path.join(
            project_root,
            config.get('database', {}).get('general_inventory_path', 'database/general_inventory.db')
        )
        pharmacy_db = os.path.join(
            project_root,
            config.get('database', {}).get('pharmacy_path', 'database/pharmacy.db')
        )

        # 檢查資料庫是否存在
        if not os.path.exists(general_db):
            print(f"✗ 一般庫存資料庫不存在: {general_db}")
            return False

        if not os.path.exists(pharmacy_db):
            print(f"✗ 藥局資料庫不存在: {pharmacy_db}")
            return False

        print(f"✓ 讀取配置檔案: {config_path}")
        print(f"✓ 一般庫存資料庫: {general_db}")
        print(f"✓ 藥局資料庫: {pharmacy_db}")
        print()

        # 取得站點後設資料
        print("正在讀取站點資料...")
        station_metadata = get_station_metadata(general_db)

        # 匯出藥局資料
        print("正在匯出藥局資料...")
        pharmacy_data = export_pharmacy_data(pharmacy_db)
        print(f"  - Medicines: {pharmacy_data['record_count']['medicines']} 筆")
        print(f"  - Transactions: {pharmacy_data['record_count']['transactions']} 筆")
        print(f"  - Controlled Drug Logs: {pharmacy_data['record_count']['controlled_drug_logs']} 筆")

        # 匯出一般庫存資料
        print("正在匯出一般庫存資料...")
        general_data = export_general_data(general_db)
        print(f"  - Items: {general_data['record_count']['items']} 筆")
        print(f"  - Transactions: {general_data['record_count']['transactions']} 筆")
        print()

        # 組合匯出資料
        export_data = {
            "export_meta": {
                "station_id": station_metadata.get('station_code', config.get('station', {}).get('code', 'UNKNOWN')),
                "station_name": station_metadata.get('station_name', config.get('station', {}).get('name', 'Unknown Station')),
                "station_type": station_metadata.get('station_type', config.get('station', {}).get('station_type', 'UNKNOWN')),
                "exported_at": datetime.now().isoformat(),
                "schema_version": config.get('schema_version', '1.5.0')
            },
            "pharmacy_data": pharmacy_data,
            "general_data": general_data
        }

        # 確保輸出目錄存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"✓ 創建輸出目錄: {output_dir}")

        # 寫入 JSON 檔案
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        # 取得檔案大小
        file_size = os.path.getsize(output_path)
        file_size_kb = file_size / 1024

        print(f"✓ 資料匯出成功: {output_path}")
        print(f"  - 檔案大小: {file_size_kb:.2f} KB")

        # 顯示匯出摘要
        total_records = (
            pharmacy_data['record_count']['medicines'] +
            pharmacy_data['record_count']['transactions'] +
            pharmacy_data['record_count']['controlled_drug_logs'] +
            general_data['record_count']['items'] +
            general_data['record_count']['transactions']
        )

        print()
        print("匯出摘要：")
        print(f"  - 站點ID: {export_data['export_meta']['station_id']}")
        print(f"  - 站點名稱: {export_data['export_meta']['station_name']}")
        print(f"  - 總記錄數: {total_records} 筆")
        print(f"  - 匯出時間: {export_data['export_meta']['exported_at']}")

        return True

    except Exception as e:
        print(f"✗ 資料匯出失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函數"""
    print("=" * 70)
    print("資料匯出工具 v1.5.0")
    print("=" * 70)
    print()

    # 檢查命令行參數
    if len(sys.argv) < 3:
        print("使用方式:")
        print(f"  python {sys.argv[0]} <config_path> <output_path>")
        print()
        print("範例:")
        print(f"  python {sys.argv[0]} config/station.json exports/output.json")
        sys.exit(1)

    config_path = sys.argv[1]
    output_path = sys.argv[2]

    # 執行匯出
    success = export_station_data(config_path, output_path)

    print("=" * 70)
    if success:
        print("✅ 匯出完成！")
    else:
        print("❌ 匯出失敗")
        sys.exit(1)
    print("=" * 70)


if __name__ == '__main__':
    main()
