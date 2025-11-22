#!/usr/bin/env python3
"""
MIRS Database Initialization Script
Supports multiple profiles for different deployment scenarios
"""

import sqlite3
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent
DATABASE_PATH = PROJECT_ROOT / "medical_inventory.db"
PROFILES_DIR = PROJECT_ROOT / "database" / "profiles"
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"

PROFILES = {
    "health_center": "Taiwan government health center (衛生所) - 15 medicines + 4 equipment",
    "hospital_custom": "Hospital custom - Empty schema for importing existing data",
    "surgical_station": "BORP surgical station (備援手術站) - 16 surgical instrument sets",
    "logistics_hub": "Logistics hub (物資中繼站) - Bulk storage with 5x quantities"
}


def get_profile_from_config():
    """Check multiple sources for profile configuration"""

    # 1. Environment variable
    if os.getenv("MIRS_DB_PROFILE"):
        return os.getenv("MIRS_DB_PROFILE")

    # 2. config/db_profile.txt
    config_file = PROJECT_ROOT / "config" / "db_profile.txt"
    if config_file.exists():
        return config_file.read_text().strip()

    # 3. config.ini
    ini_file = PROJECT_ROOT / "config.ini"
    if ini_file.exists():
        import configparser
        config = configparser.ConfigParser()
        config.read(ini_file)
        if config.has_option('database', 'profile'):
            return config.get('database', 'profile')

    # 4. Default
    return "health_center"


def backup_database():
    """Create backup of existing database"""
    if not DATABASE_PATH.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DATABASE_PATH.parent / f"medical_inventory_backup_{timestamp}.db"

    import shutil
    shutil.copy2(DATABASE_PATH, backup_path)
    print(f"✅ Backup created: {backup_path.name}")
    return backup_path


def initialize_database(profile, force=False, backup=True):
    """Initialize database with specified profile"""

    print(f"\n{'='*60}")
    print(f"🏥 MIRS Database Initialization")
    print(f"{'='*60}")
    print(f"Profile: {profile}")
    print(f"Description: {PROFILES.get(profile, 'Custom profile')}")
    print(f"Database: {DATABASE_PATH}")
    print(f"{'='*60}\n")

    # Check if database exists
    if DATABASE_PATH.exists() and not force:
        print("⚠️  Database already exists!")
        response = input("Do you want to recreate it? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Cancelled.")
            return False

    # Backup if requested
    if backup and DATABASE_PATH.exists():
        backup_database()

    # Check if profile file exists
    profile_file = PROFILES_DIR / f"{profile}.sql"
    if not profile_file.exists():
        print(f"❌ Error: Profile '{profile}' not found!")
        print(f"Expected file: {profile_file}")
        print(f"\nAvailable profiles:")
        for p, desc in PROFILES.items():
            exists = "✅" if (PROFILES_DIR / f"{p}.sql").exists() else "❌"
            print(f"  {exists} {p}: {desc}")
        return False

    # Remove existing database
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
        print(f"🗑️  Removed existing database")

    # Create new database from profile
    print(f"📦 Loading profile: {profile_file.name}")

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # First, load base schemas
    schema_general = PROJECT_ROOT / "database" / "schema_general_inventory.sql"
    schema_pharmacy = PROJECT_ROOT / "database" / "schema_pharmacy.sql"

    print(f"📋 Loading base schemas...")

    if schema_general.exists():
        with open(schema_general, 'r', encoding='utf-8') as f:
            cursor.executescript(f.read())

    if schema_pharmacy.exists():
        with open(schema_pharmacy, 'r', encoding='utf-8') as f:
            cursor.executescript(f.read())

    conn.commit()

    # Then execute profile-specific SQL (skip .read commands)
    print(f"📦 Loading profile data...")
    with open(profile_file, 'r', encoding='utf-8') as f:
        profile_sql = f.read()

        # Remove .read commands (SQLite shell commands won't work in Python)
        lines = []
        for line in profile_sql.split('\n'):
            if not line.strip().startswith('.read'):
                lines.append(line)

        cleaned_sql = '\n'.join(lines)
        cursor.executescript(cleaned_sql)

    conn.commit()

    # Run migrations
    migration_file = MIGRATIONS_DIR / "add_procedure_links.sql"
    if migration_file.exists():
        print(f"🔄 Applying migration: {migration_file.name}")
        with open(migration_file, 'r', encoding='utf-8') as f:
            migration_sql = f.read()
            try:
                cursor.executescript(migration_sql)
                conn.commit()
                print(f"✅ Migration applied successfully")
            except sqlite3.Error as e:
                # Migration might already be applied or column exists
                print(f"⚠️  Migration note: {e}")

    # Verify database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    print(f"\n✅ Database initialized successfully!")
    print(f"📊 Tables created: {len(tables)}")
    print(f"   {', '.join(tables[:10])}")
    if len(tables) > 10:
        print(f"   ... and {len(tables) - 10} more")

    # Show data counts
    print(f"\n📈 Data Summary:")
    for table in ['items', 'medicines', 'equipment', 'surgery_records', 'dispense_records']:
        if table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"   {table}: {count} records")

    conn.close()

    print(f"\n{'='*60}")
    print(f"✨ Ready to use! Start the server with: python3 main.py")
    print(f"{'='*60}\n")

    return True


def list_profiles():
    """List available database profiles"""
    print(f"\n{'='*60}")
    print(f"📋 Available Database Profiles")
    print(f"{'='*60}\n")

    for profile, description in PROFILES.items():
        profile_file = PROFILES_DIR / f"{profile}.sql"
        exists = "✅" if profile_file.exists() else "❌ (not created yet)"
        print(f"{exists} {profile:15} - {description}")

    # Check for custom profiles
    if PROFILES_DIR.exists():
        custom_profiles = list(PROFILES_DIR.glob("custom_*.sql"))
        if custom_profiles:
            print(f"\n📁 Custom Profiles:")
            for profile_path in custom_profiles:
                profile_name = profile_path.stem
                print(f"✅ {profile_name:15} - (custom)")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Initialize MIRS database with different profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use government profile
  python3 scripts/init_database.py --profile government

  # Force recreation with backup
  python3 scripts/init_database.py --profile testing --force --backup

  # List available profiles
  python3 scripts/init_database.py --list

  # Use profile from config
  export MIRS_DB_PROFILE=government
  python3 scripts/init_database.py
        """
    )

    parser.add_argument(
        '--profile',
        choices=list(PROFILES.keys()) + ['auto'],
        default='auto',
        help='Database profile to use (default: auto-detect from config)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force recreation without confirmation'
    )

    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip backup of existing database'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='List available profiles and exit'
    )

    args = parser.parse_args()

    # List profiles
    if args.list:
        list_profiles()
        return

    # Determine profile
    if args.profile == 'auto':
        profile = get_profile_from_config()
        print(f"🔍 Auto-detected profile: {profile}")
    else:
        profile = args.profile

    # Initialize
    success = initialize_database(
        profile=profile,
        force=args.force,
        backup=not args.no_backup
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
