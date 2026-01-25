"""
MIRS HLC Migration (m008)
=========================

Adds Hybrid Logical Clock columns for distributed event ordering:
- hlc_timestamp: HLC value when event was created
- source_node: Node that created the event

Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.7 (P2-01)
All migrations are idempotent.
"""

import sqlite3
from . import migration


@migration(8, "hlc_columns")
def m008_hlc(cursor: sqlite3.Cursor):
    """Add HLC columns to event tables"""

    # =========================================================================
    # Add HLC to anesthesia_events
    # =========================================================================

    # Check if column exists first (idempotent)
    cursor.execute("PRAGMA table_info(anesthesia_events)")
    columns = {row[1] for row in cursor.fetchall()}

    if 'hlc_timestamp' not in columns:
        cursor.execute("""
            ALTER TABLE anesthesia_events ADD COLUMN hlc_timestamp TEXT
        """)

    if 'source_node' not in columns:
        cursor.execute("""
            ALTER TABLE anesthesia_events ADD COLUMN source_node TEXT
        """)

    # =========================================================================
    # Add HLC to offline_event_queue (if exists)
    # =========================================================================

    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='offline_event_queue'
    """)
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(offline_event_queue)")
        columns = {row[1] for row in cursor.fetchall()}

        if 'client_hlc' not in columns:
            cursor.execute("""
                ALTER TABLE offline_event_queue ADD COLUMN client_hlc TEXT
            """)

        if 'server_hlc' not in columns:
            cursor.execute("""
                ALTER TABLE offline_event_queue ADD COLUMN server_hlc TEXT
            """)

    # =========================================================================
    # Add HLC to blood_unit_events (if exists)
    # =========================================================================

    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='blood_unit_events'
    """)
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(blood_unit_events)")
        columns = {row[1] for row in cursor.fetchall()}

        if 'hlc_timestamp' not in columns:
            cursor.execute("""
                ALTER TABLE blood_unit_events ADD COLUMN hlc_timestamp TEXT
            """)

        if 'source_node' not in columns:
            cursor.execute("""
                ALTER TABLE blood_unit_events ADD COLUMN source_node TEXT
            """)

    # =========================================================================
    # Create index for HLC ordering
    # =========================================================================

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anesthesia_events_hlc
        ON anesthesia_events(hlc_timestamp)
    """)

    # =========================================================================
    # Create HLC comparison view for debugging
    # =========================================================================

    cursor.execute("""
        CREATE VIEW IF NOT EXISTS v_hlc_event_order AS
        SELECT
            id,
            case_id,
            event_type,
            clinical_time,
            recorded_at,
            hlc_timestamp,
            source_node,
            -- Parse HLC for sorting
            CAST(SUBSTR(hlc_timestamp, 1, INSTR(hlc_timestamp, '.') - 1) AS INTEGER) as hlc_physical,
            CAST(SUBSTR(
                hlc_timestamp,
                INSTR(hlc_timestamp, '.') + 1,
                INSTR(SUBSTR(hlc_timestamp, INSTR(hlc_timestamp, '.') + 1), '.') - 1
            ) AS INTEGER) as hlc_logical
        FROM anesthesia_events
        WHERE hlc_timestamp IS NOT NULL
        ORDER BY hlc_physical, hlc_logical
    """)
