#!/usr/bin/env python3
"""
MIRS Equipment Architecture Migration v1 → v2

This script migrates the equipment system from the old dual-table architecture
to the new Unit-Centric, Single Source of Truth architecture.

Changes:
- Creates equipment_types table (configurable types)
- Simplifies equipment table (removes redundant fields)
- Ensures all equipment have units (Unit-Centric)
- Creates Views for aggregated status

Usage:
    python scripts/migration_v1_to_v2.py --dry-run     # Preview changes
    python scripts/migration_v1_to_v2.py --execute     # Execute migration
    python scripts/migration_v1_to_v2.py --rollback    # Rollback to backup
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# Configuration
DB_PATH = Path(__file__).parent.parent / "medical_inventory.db"
BACKUP_DIR = Path(__file__).parent.parent / "backups"

# =============================================================================
# Equipment Types Definition (from EQUIPMENT_ARCHITECTURE_REDESIGN.md)
# =============================================================================

EQUIPMENT_TYPES = [
    # Power Equipment
    {
        "type_code": "POWER_STATION",
        "type_name": "行動電源站",
        "category": "電力設備",
        "resilience_category": "POWER",
        "unit_label": "%",
        "capacity_config": json.dumps({
            "strategy": "LINEAR",
            "base_capacity_wh": 2048,
            "output_watts": 100,
            "hours_per_100pct": 20.48
        }),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "CHARGING", "MAINTENANCE", "OFFLINE"]),
        "icon": "battery",
        "color": "amber"
    },
    {
        "type_code": "GENERATOR",
        "type_name": "發電機",
        "category": "電力設備",
        "resilience_category": "POWER",
        "unit_label": "%",
        "capacity_config": json.dumps({
            "strategy": "FUEL_BASED",
            "tank_liters": 50,
            "fuel_rate_lph": 1.5,
            "output_watts": 2000,
            "hours_per_100pct": 33.3
        }),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "MAINTENANCE", "OFFLINE"]),
        "icon": "lightning",
        "color": "amber"
    },
    # Oxygen Equipment
    {
        "type_code": "O2_CYLINDER_H",
        "type_name": "H型氧氣鋼瓶",
        "category": "呼吸設備",
        "resilience_category": "OXYGEN",
        "unit_label": "%",
        "capacity_config": json.dumps({
            "strategy": "LINEAR",
            "capacity_liters": 6900,
            "flow_rate_lpm": 10,
            "hours_per_100pct": 11.5
        }),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "EMPTY", "MAINTENANCE"]),
        "icon": "cylinder",
        "color": "cyan"
    },
    {
        "type_code": "O2_CYLINDER_E",
        "type_name": "E型氧氣鋼瓶",
        "category": "急救設備",
        "resilience_category": "OXYGEN",
        "unit_label": "%",
        "capacity_config": json.dumps({
            "strategy": "LINEAR",
            "capacity_liters": 680,
            "flow_rate_lpm": 5,
            "hours_per_100pct": 2.27
        }),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "EMPTY", "MAINTENANCE"]),
        "icon": "cylinder",
        "color": "cyan"
    },
    {
        "type_code": "O2_CONCENTRATOR",
        "type_name": "氧氣濃縮機",
        "category": "呼吸設備",
        "resilience_category": "OXYGEN",
        "unit_label": "%",
        "capacity_config": json.dumps({
            "strategy": "POWER_DEPENDENT",
            "output_lpm": 5,
            "requires_power": True,
            "hours_unlimited": True
        }),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "MAINTENANCE", "OFFLINE"]),
        "icon": "oxygen",
        "color": "cyan"
    },
    # General Equipment (non-resilience)
    {
        "type_code": "MONITOR",
        "type_name": "生理監視器",
        "category": "監測設備",
        "resilience_category": None,
        "unit_label": None,
        "capacity_config": json.dumps({"power_watts": 50}),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "MAINTENANCE"]),
        "icon": "monitor",
        "color": "gray"
    },
    {
        "type_code": "VENTILATOR",
        "type_name": "呼吸器",
        "category": "呼吸設備",
        "resilience_category": None,
        "unit_label": None,
        "capacity_config": json.dumps({"power_watts": 150}),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "MAINTENANCE"]),
        "icon": "ventilator",
        "color": "gray"
    },
    {
        "type_code": "REFRIGERATOR",
        "type_name": "醫療冰箱",
        "category": "冷藏設備",
        "resilience_category": None,
        "unit_label": "°C",
        "capacity_config": json.dumps({"power_watts": 150}),
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "MAINTENANCE"]),
        "icon": "refrigerator",
        "color": "gray"
    },
    {
        "type_code": "GENERAL",
        "type_name": "一般設備",
        "category": "其他",
        "resilience_category": None,
        "unit_label": None,
        "capacity_config": None,
        "status_options": json.dumps(["AVAILABLE", "IN_USE", "MAINTENANCE"]),
        "icon": "equipment",
        "color": "gray"
    },
]

# Mapping from old device_type to new type_code
DEVICE_TYPE_MAPPING = {
    "POWER_STATION": "POWER_STATION",
    "GENERATOR": "GENERATOR",
    "O2_CYLINDER": "O2_CYLINDER_H",
    "O2_CONCENTRATOR": "O2_CONCENTRATOR",
    "MONITOR": "MONITOR",
    "VENTILATOR": "VENTILATOR",
    "REFRIGERATOR": "REFRIGERATOR",
}

# Mapping from equipment ID prefix to type_code
EQUIPMENT_ID_MAPPING = {
    "RESP-001": "O2_CYLINDER_H",
    "RESP-002": "O2_CONCENTRATOR",
    "EMER-EQ-006": "O2_CYLINDER_E",
    "UTIL-001": "POWER_STATION",
    "UTIL-002": "GENERATOR",
}


# =============================================================================
# SQL Definitions
# =============================================================================

CREATE_EQUIPMENT_TYPES_TABLE = """
CREATE TABLE IF NOT EXISTS equipment_types (
    type_code       TEXT PRIMARY KEY,
    type_name       TEXT NOT NULL,
    category        TEXT NOT NULL,
    resilience_category TEXT,
    unit_label      TEXT,
    capacity_config TEXT,
    status_options  TEXT DEFAULT '["AVAILABLE", "IN_USE", "MAINTENANCE"]',
    icon            TEXT,
    color           TEXT DEFAULT 'gray',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_V_EQUIPMENT_STATUS_VIEW = """
CREATE VIEW IF NOT EXISTS v_equipment_status AS
SELECT
    e.id,
    e.name,
    e.type_code,
    et.type_name,
    et.category,
    et.resilience_category,
    COUNT(u.id) as unit_count,
    ROUND(AVG(u.level_percent)) as avg_level,
    SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) as checked_count,
    MAX(u.last_check) as last_check,
    CASE
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0
            THEN 'UNCHECKED'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id)
            THEN 'CHECKED'
        ELSE 'PARTIAL'
    END as check_status
FROM equipment e
LEFT JOIN equipment_types et ON e.type_code = et.type_code
LEFT JOIN equipment_units u ON e.id = u.equipment_id
GROUP BY e.id;
"""

CREATE_V_RESILIENCE_EQUIPMENT_VIEW = """
CREATE VIEW IF NOT EXISTS v_resilience_equipment AS
SELECT
    e.id as equipment_id,
    e.name,
    et.type_code,
    et.type_name,
    et.resilience_category,
    et.capacity_config,
    e.capacity_override,
    u.id as unit_id,
    u.unit_serial,
    u.unit_label,
    u.level_percent,
    u.status,
    u.last_check,
    u.level_percent as effective_percent
FROM equipment e
JOIN equipment_types et ON e.type_code = et.type_code
JOIN equipment_units u ON e.id = u.equipment_id
WHERE et.resilience_category IS NOT NULL
ORDER BY et.resilience_category, e.id, u.unit_serial;
"""

ADD_TYPE_CODE_COLUMN = """
ALTER TABLE equipment ADD COLUMN type_code TEXT REFERENCES equipment_types(type_code);
"""

ADD_CAPACITY_OVERRIDE_COLUMN = """
ALTER TABLE equipment ADD COLUMN capacity_override TEXT;
"""


# =============================================================================
# Migration Functions
# =============================================================================

def backup_database() -> Path:
    """Create a timestamped backup before migration."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"medical_inventory_{timestamp}_pre_v2_migration.db"
    backup_path = BACKUP_DIR / backup_name
    BACKUP_DIR.mkdir(exist_ok=True)
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def check_existing_schema(conn: sqlite3.Connection) -> dict:
    """Check current database schema."""
    cursor = conn.cursor()

    # Check for existing tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    # Check equipment columns
    cursor.execute("PRAGMA table_info(equipment)")
    eq_columns = [row[1] for row in cursor.fetchall()]

    return {
        "tables": tables,
        "equipment_columns": eq_columns,
        "has_equipment_types": "equipment_types" in tables,
        "has_type_code": "type_code" in eq_columns,
        "has_capacity_override": "capacity_override" in eq_columns,
    }


def create_equipment_types(conn: sqlite3.Connection, dry_run: bool = False):
    """Create equipment_types table and populate with data."""
    cursor = conn.cursor()

    if not dry_run:
        cursor.execute(CREATE_EQUIPMENT_TYPES_TABLE)

        for et in EQUIPMENT_TYPES:
            cursor.execute("""
                INSERT OR REPLACE INTO equipment_types
                (type_code, type_name, category, resilience_category, unit_label,
                 capacity_config, status_options, icon, color)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                et["type_code"], et["type_name"], et["category"],
                et["resilience_category"], et["unit_label"],
                et["capacity_config"], et["status_options"],
                et["icon"], et["color"]
            ))

    print(f"  - equipment_types: {len(EQUIPMENT_TYPES)} types defined")


def add_columns_to_equipment(conn: sqlite3.Connection, schema: dict, dry_run: bool = False):
    """Add new columns to equipment table."""
    cursor = conn.cursor()

    if not schema["has_type_code"]:
        if not dry_run:
            cursor.execute(ADD_TYPE_CODE_COLUMN)
        print("  - Added type_code column to equipment")

    if not schema["has_capacity_override"]:
        if not dry_run:
            cursor.execute(ADD_CAPACITY_OVERRIDE_COLUMN)
        print("  - Added capacity_override column to equipment")


def map_equipment_to_types(conn: sqlite3.Connection, dry_run: bool = False):
    """Map existing equipment to their type_codes."""
    cursor = conn.cursor()

    # Get all equipment
    cursor.execute("SELECT id, device_type, category FROM equipment")
    equipment_list = cursor.fetchall()

    mapped_count = 0
    for eq_id, device_type, category in equipment_list:
        # Determine type_code
        type_code = None

        # First try equipment ID mapping
        if eq_id in EQUIPMENT_ID_MAPPING:
            type_code = EQUIPMENT_ID_MAPPING[eq_id]
        # Then try device_type mapping
        elif device_type and device_type in DEVICE_TYPE_MAPPING:
            type_code = DEVICE_TYPE_MAPPING[device_type]
        # Default to GENERAL
        else:
            type_code = "GENERAL"

        if not dry_run:
            cursor.execute("UPDATE equipment SET type_code = ? WHERE id = ?", (type_code, eq_id))

        mapped_count += 1
        print(f"    {eq_id}: {device_type or 'N/A'} → {type_code}")

    print(f"  - Mapped {mapped_count} equipment to types")


def ensure_units_exist(conn: sqlite3.Connection, dry_run: bool = False):
    """Ensure all equipment have at least one unit (Unit-Centric)."""
    cursor = conn.cursor()

    # Find equipment without units
    cursor.execute("""
        SELECT e.id, e.name, e.quantity, e.power_level, e.status
        FROM equipment e
        LEFT JOIN equipment_units u ON e.id = u.equipment_id
        WHERE u.id IS NULL
    """)
    equipment_without_units = cursor.fetchall()

    created_count = 0
    for eq_id, name, quantity, power_level, status in equipment_without_units:
        qty = quantity or 1
        level = power_level or 100

        for i in range(qty):
            unit_serial = f"{eq_id}-{i+1:03d}"
            unit_label = f"{name} {i+1}號" if qty > 1 else name

            if not dry_run:
                cursor.execute("""
                    INSERT INTO equipment_units
                    (equipment_id, unit_serial, unit_label, level_percent, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (eq_id, unit_serial, unit_label, level, status or "AVAILABLE"))

            created_count += 1
            print(f"    Created unit: {unit_serial}")

    print(f"  - Created {created_count} units for equipment without units")


def create_views(conn: sqlite3.Connection, dry_run: bool = False):
    """Create database views for aggregated status."""
    cursor = conn.cursor()

    if not dry_run:
        # Drop existing views if any
        cursor.execute("DROP VIEW IF EXISTS v_equipment_status")
        cursor.execute("DROP VIEW IF EXISTS v_resilience_equipment")

        # Create new views
        cursor.execute(CREATE_V_EQUIPMENT_STATUS_VIEW)
        cursor.execute(CREATE_V_RESILIENCE_EQUIPMENT_VIEW)

    print("  - Created v_equipment_status view")
    print("  - Created v_resilience_equipment view")


def verify_migration(conn: sqlite3.Connection):
    """Verify the migration was successful."""
    cursor = conn.cursor()

    # Check equipment_types count
    cursor.execute("SELECT COUNT(*) FROM equipment_types")
    type_count = cursor.fetchone()[0]

    # Check equipment with type_code
    cursor.execute("SELECT COUNT(*) FROM equipment WHERE type_code IS NOT NULL")
    mapped_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM equipment")
    total_count = cursor.fetchone()[0]

    # Check units
    cursor.execute("SELECT COUNT(*) FROM equipment_units")
    unit_count = cursor.fetchone()[0]

    # Check views
    try:
        cursor.execute("SELECT COUNT(*) FROM v_equipment_status")
        view_status_count = cursor.fetchone()[0]
    except:
        view_status_count = "ERROR"

    try:
        cursor.execute("SELECT COUNT(*) FROM v_resilience_equipment")
        view_resilience_count = cursor.fetchone()[0]
    except:
        view_resilience_count = "ERROR"

    print("\nVerification Results:")
    print(f"  - equipment_types: {type_count} types")
    print(f"  - equipment mapped: {mapped_count}/{total_count}")
    print(f"  - equipment_units: {unit_count} units")
    print(f"  - v_equipment_status: {view_status_count} rows")
    print(f"  - v_resilience_equipment: {view_resilience_count} rows")

    return mapped_count == total_count and type_count > 0


def run_migration(dry_run: bool = False):
    """Run the full migration."""
    print("=" * 60)
    print("MIRS Equipment Architecture Migration v1 → v2")
    print("=" * 60)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")
    else:
        print("\n🔄 EXECUTING MIGRATION\n")

    # Backup
    if not dry_run:
        backup_path = backup_database()
        print(f"✅ Backup created: {backup_path}\n")

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    try:
        # Check current schema
        print("Step 1: Checking current schema...")
        schema = check_existing_schema(conn)
        print(f"  - Tables: {len(schema['tables'])}")
        print(f"  - equipment_types exists: {schema['has_equipment_types']}")
        print(f"  - type_code column exists: {schema['has_type_code']}")

        # Create equipment_types
        print("\nStep 2: Creating equipment_types table...")
        create_equipment_types(conn, dry_run)

        # Add columns
        print("\nStep 3: Adding new columns to equipment...")
        add_columns_to_equipment(conn, schema, dry_run)

        # Map equipment to types
        print("\nStep 4: Mapping equipment to types...")
        map_equipment_to_types(conn, dry_run)

        # Ensure units exist
        print("\nStep 5: Ensuring all equipment have units...")
        ensure_units_exist(conn, dry_run)

        # Create views
        print("\nStep 6: Creating database views...")
        create_views(conn, dry_run)

        # Commit
        if not dry_run:
            conn.commit()
            print("\n✅ Migration committed successfully!")

            # Verify
            print("\nStep 7: Verifying migration...")
            success = verify_migration(conn)

            if success:
                print("\n" + "=" * 60)
                print("✅ MIGRATION COMPLETED SUCCESSFULLY")
                print("=" * 60)
            else:
                print("\n⚠️  Some verification checks failed. Please review.")
        else:
            print("\n" + "=" * 60)
            print("DRY RUN COMPLETED - No changes made")
            print("Run with --execute to apply changes")
            print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def rollback(backup_path: str = None):
    """Rollback to a backup."""
    if backup_path:
        backup = Path(backup_path)
    else:
        # Find most recent backup
        backups = list(BACKUP_DIR.glob("medical_inventory_*_pre_v2_migration.db"))
        if not backups:
            print("❌ No migration backups found")
            return
        backup = max(backups, key=lambda p: p.stat().st_mtime)

    print(f"Rolling back to: {backup}")
    shutil.copy2(backup, DB_PATH)
    print("✅ Rollback completed")


def main():
    parser = argparse.ArgumentParser(description="MIRS Equipment Migration v1 → v2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    group.add_argument("--execute", action="store_true", help="Execute the migration")
    group.add_argument("--rollback", nargs="?", const=True, metavar="BACKUP_PATH",
                       help="Rollback to backup (uses most recent if no path given)")

    args = parser.parse_args()

    if args.rollback:
        backup_path = args.rollback if isinstance(args.rollback, str) else None
        rollback(backup_path)
    else:
        run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
