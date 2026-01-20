#!/usr/bin/env python3
"""
藥品主檔 Seeder - 從 resilience_formulary.json 匯入 MIRS medicines 表

Usage:
    python seeder_medications.py [--db-path PATH]

Version: 1.2.0
Date: 2026-01-20
Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md Section 12
"""

import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

# 預設路徑
DEFAULT_FORMULARY_PATH = Path(__file__).parent / "shared/data/resilience_formulary.json"
DEFAULT_DB_PATH = Path(__file__).parent / "database/mirs.db"


def ensure_schema_columns(cursor):
    """確保 medicines 表有需要的欄位 (v1.2 擴充)"""

    # 檢查並新增欄位
    columns_to_add = [
        ("content_per_unit", "REAL"),
        ("content_unit", "TEXT"),
        ("billing_rounding", "TEXT DEFAULT 'CEIL'"),
    ]

    # 取得現有欄位
    cursor.execute("PRAGMA table_info(medicines)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE medicines ADD COLUMN {col_name} {col_type}")
                print(f"  Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise


def seed_medications(db_path: Path, formulary_path: Path, verbose: bool = True):
    """
    匯入藥品主檔

    Args:
        db_path: SQLite 資料庫路徑
        formulary_path: resilience_formulary.json 路徑
        verbose: 是否顯示詳細輸出
    """

    if not formulary_path.exists():
        print(f"Error: Formulary file not found: {formulary_path}")
        return False

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        return False

    # 讀取 JSON
    with open(formulary_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    medications = data.get('medications', [])
    if not medications:
        print("Warning: No medications found in formulary")
        return False

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 確保 schema 有需要的欄位
    if verbose:
        print("Checking schema...")
    ensure_schema_columns(cursor)
    conn.commit()

    # Dosage form 對照表
    dosage_form_map = {
        'INJ': 'INJECTION',
        'TAB': 'TABLET',
        'CAP': 'CAPSULE',
        'SOL': 'SOLUTION',
        'INFUSION': 'SOLUTION',
        'CREAM': 'CREAM',
        'OINTMENT': 'OINTMENT',
        'SYRUP': 'SYRUP',
        'PATCH': 'PATCH',
        'INHALER': 'INHALER',
        'DROPS': 'DROPS',
        'POWDER': 'POWDER',
        'SUPPOSITORY': 'SUPPOSITORY',
        'SUSPENSION': 'SUSPENSION',
    }

    # 統計
    inserted = 0
    updated = 0
    errors = 0

    if verbose:
        print(f"Seeding {len(medications)} medications...")

    for med in medications:
        try:
            # 轉換欄位
            medicine_code = med.get('nhi_code')
            if not medicine_code:
                if verbose:
                    print(f"  Skip: No nhi_code for {med.get('name_en', 'unknown')}")
                continue

            # 管制等級轉換
            controlled_level = None
            is_controlled = 0
            if med.get('controlled_level', 0) > 0:
                controlled_level = f"LEVEL_{med['controlled_level']}"
                is_controlled = 1

            # Dosage form 轉換
            dosage_form = dosage_form_map.get(
                med.get('dosage_form', 'INJ').upper(),
                'INJECTION'
            )

            # 檢查是否已存在
            cursor.execute(
                "SELECT id FROM medicines WHERE medicine_code = ?",
                (medicine_code,)
            )
            exists = cursor.fetchone() is not None

            # 插入或更新
            cursor.execute("""
                INSERT OR REPLACE INTO medicines (
                    medicine_code, generic_name, brand_name,
                    dosage_form, strength, unit,
                    is_controlled_drug, controlled_level,
                    nhi_price,
                    content_per_unit, content_unit, billing_rounding,
                    current_stock, min_stock, is_active,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                medicine_code,
                med.get('name_zh', ''),
                med.get('name_en', ''),
                dosage_form,
                med.get('spec', ''),
                med.get('billing_unit', '支'),
                is_controlled,
                controlled_level,
                float(med.get('nhi_points', 0)),
                med.get('content_per_unit'),
                med.get('content_unit'),
                med.get('billing_rounding', 'CEIL'),
                10,  # 預設庫存
                2,   # 最低庫存
                1,   # is_active
                datetime.now().isoformat()
            ))

            if exists:
                updated += 1
            else:
                inserted += 1

        except Exception as e:
            errors += 1
            if verbose:
                print(f"  Error processing {med.get('nhi_code', 'unknown')}: {e}")

    conn.commit()
    conn.close()

    # 輸出統計
    print(f"\nSeeder completed:")
    print(f"  - Inserted: {inserted}")
    print(f"  - Updated:  {updated}")
    print(f"  - Errors:   {errors}")
    print(f"  - Total:    {inserted + updated}")

    return errors == 0


def list_medications(db_path: Path, limit: int = 20):
    """列出已匯入的藥品"""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT medicine_code, generic_name, brand_name,
               dosage_form, strength, unit,
               is_controlled_drug, controlled_level,
               nhi_price, current_stock,
               content_per_unit, content_unit, billing_rounding
        FROM medicines
        WHERE is_active = 1
        ORDER BY generic_name
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()

    print(f"\n{'='*80}")
    print(f"Medications in database ({len(rows)} shown):")
    print(f"{'='*80}")
    print(f"{'Code':<15} {'Name':<25} {'Spec':<15} {'Stock':>6} {'Price':>8} {'Ctrl'}")
    print(f"{'-'*80}")

    for row in rows:
        ctrl = row['controlled_level'] or '-'
        print(f"{row['medicine_code']:<15} {row['generic_name'][:24]:<25} "
              f"{row['strength'][:14]:<15} {row['current_stock']:>6} "
              f"{row['nhi_price']:>8.1f} {ctrl}")

    # 統計
    cursor.execute("SELECT COUNT(*) FROM medicines WHERE is_active = 1")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM medicines WHERE is_controlled_drug = 1")
    controlled = cursor.fetchone()[0]

    print(f"\nTotal: {total} medications ({controlled} controlled)")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="MIRS Medication Seeder - Import from resilience_formulary.json"
    )
    parser.add_argument(
        '--db-path', '-d',
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        '--formulary-path', '-f',
        type=Path,
        default=DEFAULT_FORMULARY_PATH,
        help=f"Formulary JSON path (default: {DEFAULT_FORMULARY_PATH})"
    )
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help="List medications after seeding"
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help="Quiet mode"
    )

    args = parser.parse_args()

    success = seed_medications(
        db_path=args.db_path,
        formulary_path=args.formulary_path,
        verbose=not args.quiet
    )

    if args.list and success:
        list_medications(args.db_path)

    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
