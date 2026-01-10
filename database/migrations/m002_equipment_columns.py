"""
Migration 002: Add resilience columns to equipment and items tables
"""
from . import migration


def _safe_add_column(cursor, table, col_name, col_def):
    """Add column if not exists (SQLite doesn't have IF NOT EXISTS for ALTER)"""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
    except Exception:
        pass  # Column already exists


@migration(2, "add_resilience_columns")
def apply(cursor):
    """Add resilience-related columns to equipment and items tables"""

    # Equipment table columns for resilience calculation
    equipment_columns = [
        ("tracking_mode", "TEXT DEFAULT 'AGGREGATE'"),
        ("power_watts", "REAL"),
        ("capacity_wh", "REAL"),
        ("output_watts", "REAL"),
        ("fuel_rate_lph", "REAL"),
        ("device_type", "TEXT"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("type_code", "TEXT"),
    ]
    for col_name, col_def in equipment_columns:
        _safe_add_column(cursor, "equipment", col_name, col_def)

    # Items table columns for endurance calculation
    items_columns = [
        ("endurance_type", "TEXT"),
        ("capacity_per_unit", "REAL"),
        ("capacity_unit", "TEXT"),
        ("tests_per_unit", "INTEGER"),
        ("valid_days_after_open", "INTEGER"),
        ("depends_on_item_code", "TEXT"),
        ("dependency_note", "TEXT"),
    ]
    for col_name, col_def in items_columns:
        _safe_add_column(cursor, "items", col_name, col_def)

    # Resilience_config additional columns
    config_columns = [
        ("isolation_source", "TEXT DEFAULT 'manual'"),
        ("oxygen_profile_id", "INTEGER"),
        ("power_profile_id", "INTEGER"),
        ("reagent_profile_id", "INTEGER"),
        ("threshold_safe", "REAL DEFAULT 1.2"),
        ("threshold_warning", "REAL DEFAULT 1.0"),
        ("updated_by", "TEXT"),
    ]
    for col_name, col_def in config_columns:
        _safe_add_column(cursor, "resilience_config", col_name, col_def)
