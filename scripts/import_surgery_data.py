#!/usr/bin/env python3
"""
MIRS Surgery Codes & Self-Pay Items Data Importer
Version: 1.0.0

用途：
1. 獨立腳本執行（Production 正規路徑）
2. 作為模組供 main.py 呼叫（DEV 自動預載）

使用方式：
    python scripts/import_surgery_data.py --pack data/packs/pack.json
    python scripts/import_surgery_data.py --pack data/packs/pack.json --dry-run
    python scripts/import_surgery_data.py --pack data/packs/pack.json --actor admin001
"""

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "medical_inventory.db"
DEFAULT_PACK_PATH = PROJECT_ROOT / "data" / "packs" / "pack.json"

# CSV 欄位定義
SURGERY_CODES_COLUMNS = ['code', 'name_zh', 'name_en', 'category', 'category_code', 'points', 'notes', 'keywords', 'is_common']
SELFPAY_ITEMS_COLUMNS = ['item_id', 'name', 'category', 'unit_price', 'unit', 'is_common', 'display_order', 'notes']
SURGERY_CATEGORIES_COLUMNS = ['category_code', 'category_name', 'code_range', 'notes']


def calculate_file_sha256(filepath: Path) -> str:
    """計算檔案 SHA256"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def calculate_pack_sha256(pack_dir: Path, files: List[str]) -> str:
    """計算整個資料包的 SHA256"""
    sha256 = hashlib.sha256()
    for filename in sorted(files):
        filepath = pack_dir / filename
        if filepath.exists():
            with open(filepath, 'rb') as f:
                sha256.update(f.read())
    return sha256.hexdigest()


def validate_pack(pack_path: Path) -> Tuple[bool, Dict, str]:
    """
    驗證資料包

    Returns:
        (is_valid, pack_data, error_message)
    """
    if not pack_path.exists():
        return False, {}, f"Pack file not found: {pack_path}"

    try:
        with open(pack_path, 'r', encoding='utf-8') as f:
            pack_data = json.load(f)
    except json.JSONDecodeError as e:
        return False, {}, f"Invalid JSON in pack file: {e}"

    # 檢查必要欄位
    required_fields = ['pack_id', 'schema_version', 'sha256', 'files']
    for field in required_fields:
        if field not in pack_data:
            return False, pack_data, f"Missing required field: {field}"

    # 檢查 schema 版本
    if pack_data['schema_version'] != '1.0':
        return False, pack_data, f"Unsupported schema version: {pack_data['schema_version']}"

    # 驗證檔案存在
    pack_dir = pack_path.parent
    for filename in pack_data['files']:
        filepath = pack_dir / filename
        if not filepath.exists():
            return False, pack_data, f"Missing data file: {filename}"

    # 驗證個別檔案 checksum
    for filename, file_info in pack_data['files'].items():
        filepath = pack_dir / filename
        actual_sha256 = calculate_file_sha256(filepath)
        expected_sha256 = file_info.get('sha256', '')
        if expected_sha256 and actual_sha256 != expected_sha256:
            return False, pack_data, f"Checksum mismatch for {filename}: expected {expected_sha256[:16]}..., got {actual_sha256[:16]}..."

    # 驗證整體 checksum
    files_list = list(pack_data['files'].keys())
    actual_pack_sha256 = calculate_pack_sha256(pack_dir, files_list)
    if actual_pack_sha256 != pack_data['sha256']:
        return False, pack_data, f"Pack checksum mismatch: expected {pack_data['sha256'][:16]}..., got {actual_pack_sha256[:16]}..."

    return True, pack_data, ""


def read_csv_data(filepath: Path) -> List[Dict]:
    """讀取 CSV 檔案"""
    rows = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 清理空白
            cleaned = {k.strip(): v.strip() if v else '' for k, v in row.items()}
            rows.append(cleaned)
    return rows


def import_surgery_data(
    db_path: Path = DEFAULT_DB_PATH,
    pack_path: Path = DEFAULT_PACK_PATH,
    actor_id: Optional[str] = None,
    seed: bool = False,
    dry_run: bool = False
) -> Tuple[bool, Dict]:
    """
    匯入手術代碼與自費品項資料

    Args:
        db_path: 資料庫路徑
        pack_path: 資料包 pack.json 路徑
        actor_id: 操作者 ID
        seed: 是否為 seed 模式（DEV 自動預載）
        dry_run: 是否為預覽模式（不實際寫入）

    Returns:
        (success, result_dict)
    """
    result = {
        'success': False,
        'pack_id': None,
        'categories_imported': 0,
        'codes_imported': 0,
        'items_imported': 0,
        'errors': [],
        'warnings': []
    }

    # 1. 驗證資料包
    is_valid, pack_data, error = validate_pack(pack_path)
    if not is_valid:
        result['errors'].append(f"Pack validation failed: {error}")
        return False, result

    result['pack_id'] = pack_data['pack_id']
    pack_dir = pack_path.parent

    # 2. 連接資料庫
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    except Exception as e:
        result['errors'].append(f"Database connection failed: {e}")
        return False, result

    try:
        # 3. 檢查表是否存在，若不存在則執行 migration
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='surgery_codes'")
        if not cursor.fetchone():
            migration_path = PROJECT_ROOT / "database" / "migrations" / "add_surgery_codes_selfpay.sql"
            if migration_path.exists():
                with open(migration_path, 'r', encoding='utf-8') as f:
                    cursor.executescript(f.read())
                conn.commit()
                print(f"[INFO] Executed migration: {migration_path.name}")
            else:
                result['errors'].append("Migration file not found and tables don't exist")
                return False, result

        # 4. 檢查是否已匯入過
        cursor.execute("SELECT pack_id FROM master_data_imports WHERE pack_id = ?", (pack_data['pack_id'],))
        existing = cursor.fetchone()
        if existing:
            result['errors'].append(f"Pack already imported: {pack_data['pack_id']}")
            return False, result

        # 5. 讀取 CSV 資料
        categories_data = []
        codes_data = []
        items_data = []

        for filename, file_info in pack_data['files'].items():
            filepath = pack_dir / filename
            table = file_info['table']

            if table == 'surgery_categories':
                categories_data = read_csv_data(filepath)
            elif table == 'surgery_codes':
                codes_data = read_csv_data(filepath)
            elif table == 'selfpay_items':
                items_data = read_csv_data(filepath)

        print(f"[INFO] Read {len(categories_data)} categories, {len(codes_data)} codes, {len(items_data)} items")

        if dry_run:
            result['success'] = True
            result['categories_imported'] = len(categories_data)
            result['codes_imported'] = len(codes_data)
            result['items_imported'] = len(items_data)
            result['warnings'].append("DRY RUN - No data was written")
            conn.close()
            return True, result

        # 6. 開始 Transaction
        cursor.execute("BEGIN TRANSACTION")

        # 7. 匯入分類
        for cat in categories_data:
            cursor.execute("""
                INSERT OR REPLACE INTO surgery_categories
                (category_code, category_name, code_range, notes)
                VALUES (?, ?, ?, ?)
            """, (
                cat.get('category_code', ''),
                cat.get('category_name', ''),
                cat.get('code_range', ''),
                cat.get('notes', '')
            ))
        result['categories_imported'] = len(categories_data)

        # 8. 匯入術式代碼
        for code in codes_data:
            is_common = 1 if code.get('is_common', '').upper() in ('TRUE', '1', 'YES') else 0
            points = int(code.get('points', 0) or 0)

            cursor.execute("""
                INSERT OR REPLACE INTO surgery_codes
                (code, name_zh, name_en, category_code, points, keywords, is_common, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code.get('code', ''),
                code.get('name_zh', ''),
                code.get('name_en', ''),
                code.get('category_code', ''),
                points,
                code.get('keywords', ''),
                is_common,
                code.get('notes', '')
            ))
        result['codes_imported'] = len(codes_data)

        # 9. 匯入自費項目
        for item in items_data:
            is_common = 1 if item.get('is_common', '').upper() in ('TRUE', '1', 'YES') else 0
            unit_price = float(item.get('unit_price', 0) or 0)
            display_order = int(item.get('display_order', 0) or 0)

            cursor.execute("""
                INSERT OR REPLACE INTO selfpay_items
                (item_id, name, category, unit_price, unit, is_common, display_order, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.get('item_id', ''),
                item.get('name', ''),
                item.get('category', ''),
                unit_price,
                item.get('unit', '組'),
                is_common,
                display_order,
                item.get('notes', '')
            ))
        result['items_imported'] = len(items_data)

        # 10. 記錄匯入記錄
        cursor.execute("""
            INSERT INTO master_data_imports
            (pack_id, sha256, effective_date, applied_at, actor_id, seed, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            pack_data['pack_id'],
            pack_data['sha256'],
            pack_data.get('effective_date', ''),
            int(time.time()),
            actor_id or 'system',
            1 if seed else 0,
            f"Imported {result['categories_imported']} categories, {result['codes_imported']} codes, {result['items_imported']} items"
        ))

        # 11. Commit
        cursor.execute("COMMIT")
        result['success'] = True

        print(f"[SUCCESS] Import completed:")
        print(f"  - Categories: {result['categories_imported']}")
        print(f"  - Surgery Codes: {result['codes_imported']}")
        print(f"  - Self-Pay Items: {result['items_imported']}")

    except Exception as e:
        cursor.execute("ROLLBACK")
        result['errors'].append(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False, result

    finally:
        conn.close()

    return True, result


def should_seed_master_data(db_path: Path = DEFAULT_DB_PATH) -> bool:
    """
    檢查是否應該自動預載主檔資料

    條件：
    1. 環境變數 SEED_ON_EMPTY=true 或 ENV in {dev, test}
    2. surgery_codes 表為空
    """
    env = os.environ.get('ENV', '').lower()
    seed_enabled = os.environ.get('SEED_ON_EMPTY', '').lower() in ('true', '1', 'yes')

    if env not in ('dev', 'test') and not seed_enabled:
        return False

    if not db_path.exists():
        return True

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 檢查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='surgery_codes'")
        if not cursor.fetchone():
            conn.close()
            return True

        # 檢查是否有資料
        cursor.execute("SELECT COUNT(*) FROM surgery_codes")
        count = cursor.fetchone()[0]
        conn.close()

        return count == 0

    except Exception:
        return True


def main():
    parser = argparse.ArgumentParser(description='Import surgery codes and self-pay items')
    parser.add_argument('--pack', type=str, default=str(DEFAULT_PACK_PATH),
                        help='Path to pack.json')
    parser.add_argument('--db', type=str, default=str(DEFAULT_DB_PATH),
                        help='Path to database')
    parser.add_argument('--actor', type=str, default=None,
                        help='Actor ID for audit')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate only, do not import')
    parser.add_argument('--seed', action='store_true',
                        help='Mark as seed import (auto-preload)')

    args = parser.parse_args()

    pack_path = Path(args.pack)
    db_path = Path(args.db)

    print(f"[INFO] Pack: {pack_path}")
    print(f"[INFO] Database: {db_path}")
    print(f"[INFO] Actor: {args.actor or 'system'}")
    print(f"[INFO] Dry Run: {args.dry_run}")
    print(f"[INFO] Seed Mode: {args.seed}")
    print()

    success, result = import_surgery_data(
        db_path=db_path,
        pack_path=pack_path,
        actor_id=args.actor,
        seed=args.seed,
        dry_run=args.dry_run
    )

    if not success:
        print(f"\n[ERROR] Import failed:")
        for err in result['errors']:
            print(f"  - {err}")
        sys.exit(1)

    if result['warnings']:
        print(f"\n[WARNINGS]:")
        for warn in result['warnings']:
            print(f"  - {warn}")

    sys.exit(0)


if __name__ == '__main__':
    main()
