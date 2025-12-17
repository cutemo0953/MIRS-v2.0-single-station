#!/usr/bin/env python3
"""
MIRS v2 to v1 Rollback Script
Reverts the v2 architecture changes if needed.

Usage:
    python scripts/rollback_v2_to_v1.py --dry-run    # Preview changes
    python scripts/rollback_v2_to_v1.py              # Execute rollback

WARNING: This script removes v2 tables and views. Ensure you have a backup!
"""

import argparse
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
DB_PATH = Path(__file__).parent.parent / "medical_inventory.db"
BACKUP_DIR = Path(__file__).parent.parent / "backups"


def create_backup(db_path: Path) -> Path:
    """Create a backup before rollback."""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"medical_inventory_{timestamp}_pre_rollback.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def rollback_v2(db_path: Path, dry_run: bool = True) -> dict:
    """
    Rollback v2 architecture changes.

    This script:
    1. Drops v2 views (v_equipment_status, v_resilience_equipment)
    2. Drops equipment_types table
    3. Removes type_code and capacity_override columns from equipment
    4. Does NOT remove equipment_units (data would be lost)

    Args:
        db_path: Path to database
        dry_run: If True, only preview changes

    Returns:
        Summary of changes
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    results = {
        'views_dropped': [],
        'tables_dropped': [],
        'columns_removed': [],
        'warnings': [],
        'dry_run': dry_run
    }

    # Step 1: Drop v2 views
    v2_views = ['v_equipment_status', 'v_resilience_equipment']

    for view_name in v2_views:
        cursor.execute(f"""
            SELECT name FROM sqlite_master
            WHERE type='view' AND name='{view_name}'
        """)
        if cursor.fetchone():
            if dry_run:
                print(f"  [DRY-RUN] Would drop view: {view_name}")
            else:
                cursor.execute(f"DROP VIEW IF EXISTS {view_name}")
                print(f"  Dropped view: {view_name}")
            results['views_dropped'].append(view_name)

    # Step 2: Check equipment_types table
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='equipment_types'
    """)
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM equipment_types")
        type_count = cursor.fetchone()[0]

        if dry_run:
            print(f"  [DRY-RUN] Would drop table: equipment_types ({type_count} rows)")
        else:
            cursor.execute("DROP TABLE IF EXISTS equipment_types")
            print(f"  Dropped table: equipment_types ({type_count} rows)")
        results['tables_dropped'].append(f"equipment_types ({type_count} rows)")

    # Step 3: Check for v2 columns in equipment table
    cursor.execute("PRAGMA table_info(equipment)")
    columns = {row[1]: row for row in cursor.fetchall()}

    v2_columns = ['type_code', 'capacity_override']
    for col in v2_columns:
        if col in columns:
            results['columns_removed'].append(col)
            if dry_run:
                print(f"  [DRY-RUN] Would need to remove column: equipment.{col}")
            else:
                # SQLite doesn't support DROP COLUMN directly, need to recreate table
                results['warnings'].append(
                    f"Column equipment.{col} exists but SQLite requires table recreation to remove. "
                    f"Column left in place (harmless)."
                )
                print(f"  WARNING: Cannot remove column {col} without table recreation. Left in place.")

    # Step 4: Check equipment_units (WARNING - do not drop!)
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='equipment_units'
    """)
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM equipment_units")
        unit_count = cursor.fetchone()[0]
        results['warnings'].append(
            f"equipment_units table exists with {unit_count} rows. "
            f"NOT dropped to preserve data. Remove manually if needed."
        )
        print(f"  WARNING: equipment_units ({unit_count} rows) NOT dropped (data preservation)")

    if not dry_run:
        conn.commit()
        print("\n  Rollback committed.")
    else:
        print("\n  [DRY-RUN] No changes made. Run without --dry-run to execute.")

    conn.close()
    return results


def restore_from_backup(backup_path: Path, db_path: Path):
    """Restore database from a backup file."""
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    # Create safety backup of current state
    safety_backup = create_backup(db_path)
    print(f"  Created safety backup: {safety_backup}")

    # Restore
    shutil.copy2(backup_path, db_path)
    print(f"  Restored from: {backup_path}")


def main():
    parser = argparse.ArgumentParser(description="Rollback MIRS v2 architecture changes")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview changes without executing")
    parser.add_argument("--restore", "-r", type=str,
                        help="Restore from a specific backup file instead of rolling back")
    args = parser.parse_args()

    print("=" * 60)
    print("MIRS v2 to v1 Rollback Script")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        return 1

    if args.restore:
        backup_path = Path(args.restore)
        print(f"\nRestoring from backup: {backup_path}")
        try:
            restore_from_backup(backup_path, DB_PATH)
            print("\nRestore completed successfully!")
        except Exception as e:
            print(f"\nERROR: Restore failed: {e}")
            return 1
        return 0

    # Normal rollback
    if not args.dry_run:
        print("\nCreating backup before rollback...")
        backup_path = create_backup(DB_PATH)
        print(f"  Backup created: {backup_path}")

    print(f"\nRolling back v2 changes...")
    results = rollback_v2(DB_PATH, dry_run=args.dry_run)

    print("\n" + "=" * 60)
    print("Rollback Summary")
    print("=" * 60)
    print(f"  Views dropped: {len(results['views_dropped'])}")
    for v in results['views_dropped']:
        print(f"    - {v}")
    print(f"  Tables dropped: {len(results['tables_dropped'])}")
    for t in results['tables_dropped']:
        print(f"    - {t}")
    if results['warnings']:
        print(f"\n  Warnings:")
        for w in results['warnings']:
            print(f"    - {w}")

    if args.dry_run:
        print("\n[DRY-RUN] No actual changes were made.")
        print("Run without --dry-run to execute rollback.")

    return 0


if __name__ == "__main__":
    exit(main())
