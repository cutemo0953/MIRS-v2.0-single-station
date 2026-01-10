"""
Migration 001: Create resilience-related tables
"""
from . import migration


@migration(1, "create_resilience_tables")
def apply(cursor):
    """Create resilience tables if not exist"""

    # resilience_config - station-level resilience settings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resilience_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL UNIQUE,
            isolation_target_days REAL DEFAULT 3,
            isolation_source TEXT DEFAULT 'manual',
            population_count INTEGER DEFAULT 2,
            population_label TEXT DEFAULT '插管患者數',
            oxygen_profile_id INTEGER,
            power_profile_id INTEGER,
            reagent_profile_id INTEGER,
            threshold_safe REAL DEFAULT 1.2,
            threshold_warning REAL DEFAULT 1.0,
            oxygen_consumption_rate REAL DEFAULT 10.0,
            fuel_consumption_rate REAL DEFAULT 3.0,
            power_consumption_watts REAL DEFAULT 500.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    """)

    # equipment_units - per-unit tracking for PER_UNIT equipment
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id TEXT NOT NULL,
            unit_serial TEXT,
            unit_label TEXT,
            level_percent INTEGER DEFAULT 100,
            status TEXT DEFAULT 'AVAILABLE',
            last_check TIMESTAMP,
            checked_by TEXT,
            remarks TEXT,
            is_active INTEGER DEFAULT 1,
            removed_at TIMESTAMP,
            removed_by TEXT,
            removal_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # equipment_check_history - audit trail for equipment checks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id TEXT NOT NULL,
            unit_label TEXT,
            check_date DATE NOT NULL,
            check_time TIMESTAMP NOT NULL,
            checked_by TEXT,
            level_before INTEGER,
            level_after INTEGER,
            status_before TEXT,
            status_after TEXT,
            remarks TEXT,
            station_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # resilience_profiles - consumption scenarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resilience_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            endurance_type TEXT NOT NULL,
            profile_name TEXT NOT NULL,
            profile_name_en TEXT,
            burn_rate REAL NOT NULL,
            burn_rate_unit TEXT NOT NULL,
            population_multiplier INTEGER DEFAULT 0,
            description TEXT,
            is_default INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # reagent_open_records - reagent expiry tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reagent_open_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT NOT NULL,
            batch_number TEXT,
            station_id TEXT NOT NULL,
            opened_at DATETIME NOT NULL,
            tests_remaining INTEGER,
            is_active INTEGER DEFAULT 1,
            notes TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
