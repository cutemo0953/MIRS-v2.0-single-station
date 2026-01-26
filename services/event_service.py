"""
MIRS Event Service - Event Sourcing for Disaster Recovery

Provides:
- Event creation and storage
- Batch restore with idempotency
- Snapshot UPSERT for immediate UI usability
- Hash-based duplicate detection

Version: 1.0
Date: 2026-01-26
Reference: DEV_SPEC_LIFEBOAT_MIRS_v1.1
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

from .id_service import (
    generate_event_id,
    compute_event_hash,
    get_current_timestamp_ms,
    get_server_uuid,
    get_db_fingerprint,
)
from .hlc import hlc_now, get_hlc

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

DB_PATH = os.environ.get('MIRS_DB_PATH', 'medical_inventory.db')
STATION_ID = os.environ.get('MIRS_STATION_ID', 'MIRS-DEFAULT')


# =============================================================================
# Data Classes
# =============================================================================

class EventInsertResult(Enum):
    """Result of attempting to insert an event."""
    INSERTED = "INSERTED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    REJECTED = "REJECTED"  # Hash mismatch


@dataclass
class Event:
    """Unified event record."""
    event_id: str
    site_id: str
    entity_type: str
    entity_id: str
    actor_id: str
    actor_name: Optional[str]
    actor_role: Optional[str]
    device_id: Optional[str]
    ts_device: int  # milliseconds
    ts_server: Optional[int]
    hlc: Optional[str]
    event_type: str
    schema_version: str
    payload_json: str
    payload_hash: str
    synced: int = 0
    acknowledged: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Event':
        return cls(
            event_id=row['event_id'],
            site_id=row['site_id'],
            entity_type=row['entity_type'],
            entity_id=row['entity_id'],
            actor_id=row['actor_id'],
            actor_name=row.get('actor_name'),
            actor_role=row.get('actor_role'),
            device_id=row.get('device_id'),
            ts_device=row['ts_device'],
            ts_server=row.get('ts_server'),
            hlc=row.get('hlc'),
            event_type=row['event_type'],
            schema_version=row['schema_version'],
            payload_json=row['payload_json'],
            payload_hash=row['payload_hash'],
            synced=row.get('synced', 0),
            acknowledged=row.get('acknowledged', 0),
        )


@dataclass
class RestoreResult:
    """Result of a restore operation."""
    status: str  # "IN_PROGRESS" or "COMPLETED"
    restore_session_id: str
    batch_number: int
    events_received: int
    events_inserted: int
    events_already_present: int
    events_rejected: int
    rejected_event_ids: List[str]
    snapshot_tables_restored: List[str]
    message: str


# =============================================================================
# Event Creation
# =============================================================================

def create_event(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: dict,
    actor_id: str = "system",
    actor_name: Optional[str] = None,
    actor_role: Optional[str] = None,
    device_id: Optional[str] = None,
    site_id: Optional[str] = None,
) -> Event:
    """
    Create and store a new event.

    Args:
        conn: Database connection
        entity_type: Type of entity (e.g., "anesthesia_case", "blood_unit")
        entity_id: ID of the entity
        event_type: Type of event (e.g., "CREATED", "STATUS_CHANGE")
        payload: Event payload dictionary
        actor_id: ID of actor creating event
        actor_name: Name of actor (optional)
        actor_role: Role of actor (optional)
        device_id: Device ID (optional)
        site_id: Site ID (defaults to STATION_ID)

    Returns:
        Created Event object
    """
    event_id = generate_event_id()
    ts_device = get_current_timestamp_ms()
    hlc = hlc_now(STATION_ID)
    payload_json = json.dumps(payload, ensure_ascii=False)

    # Compute hash
    event_dict = {
        'event_id': event_id,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'event_type': event_type,
        'payload': payload,
        'ts_device': ts_device,
        'hlc': hlc,
    }
    payload_hash = compute_event_hash(event_dict)

    event = Event(
        event_id=event_id,
        site_id=site_id or STATION_ID,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_role=actor_role,
        device_id=device_id,
        ts_device=ts_device,
        ts_server=ts_device,  # Same as device on server
        hlc=hlc,
        event_type=event_type,
        schema_version="1.0",
        payload_json=payload_json,
        payload_hash=payload_hash,
    )

    # Insert into events table
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO events (
            event_id, site_id, entity_type, entity_id,
            actor_id, actor_name, actor_role, device_id,
            ts_device, ts_server, hlc, event_type,
            schema_version, payload_json, payload_hash,
            synced, acknowledged
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event.event_id, event.site_id, event.entity_type, event.entity_id,
        event.actor_id, event.actor_name, event.actor_role, event.device_id,
        event.ts_device, event.ts_server, event.hlc, event.event_type,
        event.schema_version, event.payload_json, event.payload_hash,
        event.synced, event.acknowledged,
    ))

    logger.debug(f"Created event {event_id}: {entity_type}/{entity_id} - {event_type}")
    return event


# =============================================================================
# Event Export (for DR)
# =============================================================================

def export_events(
    conn: sqlite3.Connection,
    since_hlc: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0,
) -> Tuple[List[dict], bool, int]:
    """
    Export events for disaster recovery.

    Args:
        conn: Database connection
        since_hlc: Only export events after this HLC (cursor-based pagination)
        limit: Maximum number of events to return
        offset: Offset for pagination (deprecated, use since_hlc)

    Returns:
        Tuple of (events, has_more, total_count)
    """
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row

    # Get total count
    if since_hlc:
        cursor.execute(
            "SELECT COUNT(*) FROM events WHERE hlc > ?",
            (since_hlc,)
        )
    else:
        cursor.execute("SELECT COUNT(*) FROM events")
    total_count = cursor.fetchone()[0]

    # Get events
    if since_hlc:
        cursor.execute("""
            SELECT * FROM events
            WHERE hlc > ?
            ORDER BY hlc ASC
            LIMIT ? OFFSET ?
        """, (since_hlc, limit + 1, offset))  # +1 to check has_more
    else:
        cursor.execute("""
            SELECT * FROM events
            ORDER BY hlc ASC
            LIMIT ? OFFSET ?
        """, (limit + 1, offset))

    rows = cursor.fetchall()

    # Check if there are more
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    events = [dict(row) for row in rows]
    return events, has_more, total_count


def export_snapshot(conn: sqlite3.Connection) -> Dict[str, List[dict]]:
    """
    Export current state snapshot for disaster recovery.

    Returns:
        Dictionary with table names as keys and rows as values
    """
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row

    snapshot = {}

    # Tables to include in snapshot
    tables_to_export = [
        'anesthesia_cases',
        'patients',
        'equipment',
        'blood_units',
        'blood_orders',
    ]

    for table in tables_to_export:
        try:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            snapshot[table] = [dict(row) for row in rows]
            logger.debug(f"Exported {len(rows)} rows from {table}")
        except sqlite3.OperationalError as e:
            # Table doesn't exist - skip
            logger.debug(f"Table {table} not found, skipping: {e}")
            continue

    return snapshot


# =============================================================================
# Event Restore (for DR)
# =============================================================================

def insert_event_idempotent(
    cursor: sqlite3.Cursor,
    event: dict,
    restore_session_id: str,
) -> Tuple[EventInsertResult, Optional[str]]:
    """
    Insert event with idempotency check.

    If event_id already exists:
    - If hash matches: ALREADY_PRESENT
    - If hash differs: REJECTED (logged to restore_rejects)

    Args:
        cursor: Database cursor
        event: Event dictionary
        restore_session_id: Session ID for audit logging

    Returns:
        Tuple of (result, error_message)
    """
    event_id = event.get('event_id')

    # Compute hash for incoming event
    incoming_hash = compute_event_hash(event)

    # Check if event already exists
    cursor.execute(
        "SELECT payload_hash FROM events WHERE event_id = ?",
        (event_id,)
    )
    existing = cursor.fetchone()

    if existing:
        existing_hash = existing[0]
        if existing_hash == incoming_hash:
            return EventInsertResult.ALREADY_PRESENT, None
        else:
            # Hash mismatch - reject and log
            cursor.execute("""
                INSERT INTO restore_rejects
                (event_id, restore_session_id, reason, old_hash, new_hash)
                VALUES (?, ?, 'HASH_MISMATCH', ?, ?)
            """, (event_id, restore_session_id, existing_hash, incoming_hash))
            return EventInsertResult.REJECTED, f"Hash mismatch: {existing_hash} != {incoming_hash}"

    # Insert new event
    cursor.execute("""
        INSERT INTO events (
            event_id, site_id, entity_type, entity_id,
            actor_id, actor_name, actor_role, device_id,
            ts_device, ts_server, hlc, event_type,
            schema_version, payload_json, payload_hash,
            synced, acknowledged
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id,
        event.get('site_id', STATION_ID),
        event.get('entity_type'),
        event.get('entity_id'),
        event.get('actor_id', 'restored'),
        event.get('actor_name'),
        event.get('actor_role'),
        event.get('device_id'),
        event.get('ts_device'),
        event.get('ts_server'),
        event.get('hlc'),
        event.get('event_type'),
        event.get('schema_version', '1.0'),
        event.get('payload_json') or json.dumps(event.get('payload', {})),
        incoming_hash,
        1,  # Mark as synced (came from restore)
        1,  # Mark as acknowledged
    ))

    return EventInsertResult.INSERTED, None


def restore_snapshot(
    cursor: sqlite3.Cursor,
    snapshot: Dict[str, List[dict]],
) -> List[str]:
    """
    Restore snapshot data using UPSERT.

    This makes UI immediately usable while events are being restored.

    Args:
        cursor: Database cursor
        snapshot: Dictionary with table names as keys and rows as values

    Returns:
        List of restored table names
    """
    restored_tables = []

    for table_name, rows in snapshot.items():
        if not rows:
            continue

        # Get table columns
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns_info = cursor.fetchall()
        if not columns_info:
            logger.warning(f"Table {table_name} does not exist, skipping")
            continue

        columns = [col[1] for col in columns_info]
        pk_column = next((col[1] for col in columns_info if col[5] == 1), columns[0])

        for row in rows:
            # Filter to only columns that exist in table
            row_filtered = {k: v for k, v in row.items() if k in columns}
            if not row_filtered:
                continue

            col_names = list(row_filtered.keys())
            placeholders = ', '.join(['?' for _ in col_names])
            col_list = ', '.join(col_names)

            # Build UPSERT (INSERT OR REPLACE)
            cursor.execute(f"""
                INSERT OR REPLACE INTO {table_name} ({col_list})
                VALUES ({placeholders})
            """, list(row_filtered.values()))

        restored_tables.append(table_name)
        logger.info(f"Restored {len(rows)} rows to {table_name}")

    return restored_tables


def restore_events_batch(
    conn: sqlite3.Connection,
    restore_session_id: str,
    source_device_id: str,
    events: List[dict],
    snapshot: Optional[Dict[str, List[dict]]] = None,
    batch_number: int = 1,
    is_final_batch: bool = True,
) -> RestoreResult:
    """
    Restore a batch of events (and optionally snapshot) from a client.

    All operations are performed in a single transaction for SD card protection.

    Args:
        conn: Database connection
        restore_session_id: Unique session ID for this restore
        source_device_id: Device ID of the source (client)
        events: List of event dictionaries
        snapshot: Optional snapshot data (usually only sent in first batch)
        batch_number: Batch number (1-indexed)
        is_final_batch: Whether this is the last batch

    Returns:
        RestoreResult with statistics
    """
    cursor = conn.cursor()

    inserted = 0
    already_present = 0
    rejected = 0
    rejected_ids = []
    snapshot_tables = []

    try:
        # Start transaction (G3: single batch transaction)
        conn.execute("BEGIN IMMEDIATE")

        # Step 1: Restore snapshot if provided (G1: UI immediately usable)
        if snapshot:
            snapshot_tables = restore_snapshot(cursor, snapshot)

        # Step 2: Insert events with idempotency check (C3: hash validation)
        for event in events:
            result, error = insert_event_idempotent(cursor, event, restore_session_id)
            if result == EventInsertResult.INSERTED:
                inserted += 1
            elif result == EventInsertResult.ALREADY_PRESENT:
                already_present += 1
            elif result == EventInsertResult.REJECTED:
                rejected += 1
                rejected_ids.append(event.get('event_id'))
                logger.warning(f"Rejected event {event.get('event_id')}: {error}")

        # Log restore operation
        cursor.execute("""
            INSERT INTO restore_log
            (restore_session_id, source_device_id, batch_number, events_count,
             inserted, already_present, rejected, is_final, restored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            restore_session_id, source_device_id, batch_number, len(events),
            inserted, already_present, rejected, is_final_batch, datetime.now().isoformat()
        ))

        conn.commit()

        status = "COMPLETED" if is_final_batch else "IN_PROGRESS"
        message = f"Batch {batch_number} processed: {inserted} inserted, {already_present} existing, {rejected} rejected"

        return RestoreResult(
            status=status,
            restore_session_id=restore_session_id,
            batch_number=batch_number,
            events_received=len(events),
            events_inserted=inserted,
            events_already_present=already_present,
            events_rejected=rejected,
            rejected_event_ids=rejected_ids,
            snapshot_tables_restored=snapshot_tables,
            message=message,
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Restore batch failed: {e}")
        raise


# =============================================================================
# Utility Functions
# =============================================================================

def get_events_by_entity(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
) -> List[Event]:
    """Get all events for a specific entity."""
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row

    cursor.execute("""
        SELECT * FROM events
        WHERE entity_type = ? AND entity_id = ?
        ORDER BY hlc ASC
    """, (entity_type, entity_id))

    return [Event.from_row(row) for row in cursor.fetchall()]


def get_event_count(conn: sqlite3.Connection) -> int:
    """Get total event count."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM events")
    return cursor.fetchone()[0]


def get_last_hlc(conn: sqlite3.Connection) -> Optional[str]:
    """Get the HLC of the last event."""
    cursor = conn.cursor()
    cursor.execute("SELECT hlc FROM events ORDER BY hlc DESC LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else None
