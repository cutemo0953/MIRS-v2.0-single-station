#!/usr/bin/env python3
"""
MIRS Database Backup Script
Automatically backs up the SQLite database with timestamp and version info.

Usage:
    python scripts/backup.py
    python scripts/backup.py --version 1.4.8
    python scripts/backup.py --label pre_migration
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# Configuration
DB_PATH = Path(__file__).parent.parent / "medical_inventory.db"
BACKUP_DIR = Path(__file__).parent.parent / "backups"


def get_db_stats(db_path: Path) -> dict:
    """Get basic stats from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    stats = {}
    tables = ['equipment', 'equipment_units', 'inventory', 'equipment_check_history']

    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            stats[table] = 0

    conn.close()
    return stats


def backup_database(version: str = None, label: str = None) -> Path:
    """
    Create a backup of the database.

    Args:
        version: Version string (e.g., "1.4.8")
        label: Custom label (e.g., "pre_migration")

    Returns:
        Path to the backup file
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    # Create backup directory if needed
    BACKUP_DIR.mkdir(exist_ok=True)

    # Generate backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = ["medical_inventory", timestamp]

    if version:
        parts.append(f"v{version}")
    if label:
        parts.append(label)

    backup_name = "_".join(parts) + ".db"
    backup_path = BACKUP_DIR / backup_name

    # Copy database
    shutil.copy2(DB_PATH, backup_path)

    # Verify backup
    if not backup_path.exists():
        raise RuntimeError("Backup file was not created")

    original_size = DB_PATH.stat().st_size
    backup_size = backup_path.stat().st_size

    if original_size != backup_size:
        raise RuntimeError(f"Backup size mismatch: {original_size} vs {backup_size}")

    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Backup MIRS database")
    parser.add_argument("--version", "-v", help="Version string (e.g., 1.4.8)")
    parser.add_argument("--label", "-l", help="Custom label (e.g., pre_migration)")
    args = parser.parse_args()

    print(f"MIRS Database Backup")
    print(f"=" * 50)
    print(f"Source: {DB_PATH}")

    # Get stats before backup
    stats = get_db_stats(DB_PATH)
    print(f"\nDatabase stats:")
    for table, count in stats.items():
        print(f"  - {table}: {count} rows")

    # Create backup
    try:
        backup_path = backup_database(version=args.version, label=args.label)
        print(f"\n✅ Backup created: {backup_path}")
        print(f"   Size: {backup_path.stat().st_size:,} bytes")
    except Exception as e:
        print(f"\n❌ Backup failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
