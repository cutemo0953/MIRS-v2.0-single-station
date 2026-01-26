"""
MIRS Walkaway/Lifeboat Migration (m009)
=======================================

Creates tables for Disaster Recovery (Lifeboat):
- events: Unified event store for all entity types
- restore_log: Audit log of restore operations
- restore_rejects: Events rejected during restore (hash mismatch)
- system_config: System configuration (server_uuid, etc.)

Reference: DEV_SPEC_LIFEBOAT_MIRS_v1.1
All migrations are idempotent.
"""

import sqlite3
from . import migration


@migration(9, "walkaway_lifeboat")
def m009_walkaway(cursor: sqlite3.Cursor):
    """Create Walkaway/Lifeboat tables"""

    # =========================================================================
    # 1. events table - Unified event store
    # Handle both fresh creation and evolution from older schema
    # =========================================================================

    # Check if events table exists and has old schema
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
    events_exists = cursor.fetchone() is not None

    if events_exists:
        # Check schema - look for event_id column
        cursor.execute("PRAGMA table_info(events)")
        columns = {row[1]: row for row in cursor.fetchall()}

        if 'event_id' not in columns:
            # Old schema - rename and recreate
            cursor.execute("ALTER TABLE events RENAME TO events_old")

            cursor.execute("""
                CREATE TABLE events (
                    event_id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL DEFAULT 'main',
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_name TEXT,
                    actor_role TEXT,
                    device_id TEXT,
                    ts_device INTEGER NOT NULL,
                    ts_server INTEGER,
                    hlc TEXT,
                    event_type TEXT NOT NULL,
                    schema_version TEXT DEFAULT '1.0',
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT,
                    synced INTEGER DEFAULT 0,
                    acknowledged INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migrate data from old table if any
            cursor.execute("""
                INSERT INTO events (
                    event_id, entity_type, entity_id, event_type,
                    ts_device, actor_id, payload_json, synced, created_at
                )
                SELECT
                    COALESCE(event_id, id),
                    entity_type,
                    entity_id,
                    event_type,
                    ts_device,
                    actor_id,
                    COALESCE(payload, '{}'),
                    CASE WHEN sync_status = 'SYNCED' THEN 1 ELSE 0 END,
                    created_at
                FROM events_old
            """)

            # Drop old table
            cursor.execute("DROP TABLE events_old")

        else:
            # New-ish schema - just add missing columns
            for col, col_def in [
                ('site_id', "TEXT NOT NULL DEFAULT 'main'"),
                ('actor_name', 'TEXT'),
                ('actor_role', 'TEXT'),
                ('device_id', 'TEXT'),
                ('ts_server', 'INTEGER'),
                ('hlc', 'TEXT'),
                ('schema_version', "TEXT DEFAULT '1.0'"),
                ('payload_json', 'TEXT'),
                ('payload_hash', 'TEXT'),
                ('acknowledged', 'INTEGER DEFAULT 0'),
            ]:
                if col not in columns:
                    try:
                        cursor.execute(f"ALTER TABLE events ADD COLUMN {col} {col_def}")
                    except sqlite3.OperationalError:
                        pass  # Column might already exist

    else:
        # Fresh creation
        cursor.execute("""
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                site_id TEXT NOT NULL DEFAULT 'main',
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_name TEXT,
                actor_role TEXT,
                device_id TEXT,
                ts_device INTEGER NOT NULL,
                ts_server INTEGER,
                hlc TEXT,
                event_type TEXT NOT NULL,
                schema_version TEXT DEFAULT '1.0',
                payload_json TEXT NOT NULL,
                payload_hash TEXT,
                synced INTEGER DEFAULT 0,
                acknowledged INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Indexes for efficient querying
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_entity
        ON events(entity_type, entity_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_hlc
        ON events(hlc)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_ts_device
        ON events(ts_device)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_site
        ON events(site_id)
    """)

    # =========================================================================
    # 2. restore_log table - Audit log of restore operations
    # =========================================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restore_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restore_session_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            batch_number INTEGER NOT NULL,
            events_count INTEGER NOT NULL,
            inserted INTEGER DEFAULT 0,
            already_present INTEGER DEFAULT 0,
            rejected INTEGER DEFAULT 0,
            is_final INTEGER DEFAULT 0,
            restored_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restore_log_session
        ON restore_log(restore_session_id)
    """)

    # =========================================================================
    # 3. restore_rejects table - Events rejected during restore
    # =========================================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restore_rejects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            restore_session_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            old_hash TEXT,
            new_hash TEXT,
            rejected_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restore_rejects_session
        ON restore_rejects(restore_session_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restore_rejects_event
        ON restore_rejects(event_id)
    """)

    # =========================================================================
    # 4. system_config table - System configuration
    # =========================================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Generate server_uuid if not exists
    cursor.execute("""
        INSERT OR IGNORE INTO system_config (key, value)
        VALUES ('server_uuid', 'MIRS-' || lower(hex(randomblob(8))))
    """)

    # =========================================================================
    # 5. View for event statistics
    # =========================================================================

    cursor.execute("""
        CREATE VIEW IF NOT EXISTS v_event_stats AS
        SELECT
            entity_type,
            COUNT(*) as event_count,
            COUNT(DISTINCT entity_id) as entity_count,
            MIN(ts_device) as first_event_ts,
            MAX(ts_device) as last_event_ts,
            SUM(CASE WHEN synced = 1 THEN 1 ELSE 0 END) as synced_count
        FROM events
        GROUP BY entity_type
    """)

    # =========================================================================
    # 6. View for restore history
    # =========================================================================

    cursor.execute("""
        CREATE VIEW IF NOT EXISTS v_restore_history AS
        SELECT
            restore_session_id,
            source_device_id,
            COUNT(*) as batch_count,
            SUM(events_count) as total_events,
            SUM(inserted) as total_inserted,
            SUM(already_present) as total_existing,
            SUM(rejected) as total_rejected,
            MIN(restored_at) as started_at,
            MAX(restored_at) as completed_at,
            MAX(is_final) as is_complete
        FROM restore_log
        GROUP BY restore_session_id
        ORDER BY completed_at DESC
    """)
