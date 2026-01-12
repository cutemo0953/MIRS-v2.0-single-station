"""
MIRS Idempotent Migration System
================================

Based on Gemini + ChatGPT recommendations:
- Replace single-gate seeding with module-level ensure()
- Track schema_version and seed_version separately
- All migrations are idempotent (can run multiple times safely)

Usage:
    from database.migrations import run_migrations
    run_migrations(conn)
"""

import sqlite3
import logging
from datetime import datetime
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

# Migration registry: (version, name, function)
_migrations: List[Tuple[int, str, Callable]] = []


def migration(version: int, name: str):
    """Decorator to register a migration function"""
    def decorator(func: Callable):
        _migrations.append((version, name, func))
        return func
    return decorator


def _ensure_version_table(cursor: sqlite3.Cursor):
    """Create version tracking table if not exists"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS _mirs_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT
        )
    """)


def _get_applied_versions(cursor: sqlite3.Cursor) -> set:
    """Get set of already applied migration versions"""
    try:
        cursor.execute("SELECT version FROM _mirs_migrations")
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        return set()


def run_migrations(conn: sqlite3.Connection, target_version: int = None) -> int:
    """
    Run all pending migrations up to target_version.

    Args:
        conn: SQLite connection
        target_version: Optional max version to apply (default: all)

    Returns:
        Number of migrations applied
    """
    cursor = conn.cursor()
    _ensure_version_table(cursor)

    applied = _get_applied_versions(cursor)
    pending = sorted([m for m in _migrations if m[0] not in applied], key=lambda x: x[0])

    if target_version is not None:
        pending = [m for m in pending if m[0] <= target_version]

    applied_count = 0
    for version, name, func in pending:
        try:
            logger.info(f"[Migration] Applying v{version}: {name}")
            func(cursor)
            cursor.execute(
                "INSERT INTO _mirs_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now().isoformat())
            )
            conn.commit()
            applied_count += 1
            logger.info(f"[Migration] v{version} applied successfully")
        except Exception as e:
            conn.rollback()
            logger.error(f"[Migration] v{version} failed: {e}")
            raise

    if applied_count == 0:
        logger.info("[Migration] All migrations already applied")
    else:
        logger.info(f"[Migration] Applied {applied_count} migration(s)")

    return applied_count


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get the current migration version"""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT MAX(version) FROM _mirs_migrations")
        result = cursor.fetchone()[0]
        return result if result else 0
    except sqlite3.OperationalError:
        return 0


# Import all migration modules to register them
from . import m001_resilience_tables
from . import m002_equipment_columns
from . import m003_ensure_resilience_equipment
from . import m004_ensure_surgical_packs
from . import m005_ensure_equipment_units
from . import m006_ensure_resilience_profiles
from . import m007_blood_bank
