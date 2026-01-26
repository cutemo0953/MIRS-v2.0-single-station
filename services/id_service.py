"""
MIRS ID Service - UUIDv7 + Time Validity Gate

Provides:
- UUIDv7 generation (time-sortable unique IDs)
- Server UUID management (persistent instance identity)
- Time validity gate (prevents operation with invalid system time)

Version: 1.0
Date: 2026-01-26
Reference: DEV_SPEC_LIFEBOAT_MIRS_v1.1
"""

import hashlib
import os
import random
import sqlite3
import struct
import threading
import time
import uuid
from datetime import datetime
from typing import Optional, Tuple

# =============================================================================
# Constants
# =============================================================================

# Build date - operations are blocked if system time is before this
# This protects against RTC reset issues on RPi
BUILD_DATE_TS = 1737849600000  # 2026-01-26 00:00:00 UTC in milliseconds

# Database path
DB_PATH = os.environ.get('MIRS_DB_PATH', 'medical_inventory.db')


# =============================================================================
# Exceptions
# =============================================================================

class TimeValidityError(Exception):
    """Raised when system time is invalid (before build date)."""
    pass


class IDServiceError(Exception):
    """Generic ID service error."""
    pass


# =============================================================================
# Time Validity Gate
# =============================================================================

def validate_time() -> bool:
    """
    Validate that system time is after build date.

    This prevents issues with HLC/UUIDv7 when RPi RTC has reset.

    Returns:
        True if time is valid

    Raises:
        TimeValidityError if time is before build date
    """
    now_ms = int(time.time() * 1000)

    if now_ms < BUILD_DATE_TS:
        build_date_str = datetime.utcfromtimestamp(BUILD_DATE_TS / 1000).strftime('%Y-%m-%d')
        current_str = datetime.utcfromtimestamp(now_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
        raise TimeValidityError(
            f"System time ({current_str}) is before build date ({build_date_str}). "
            "Please sync time via NTP or RTC."
        )

    return True


def is_time_valid() -> Tuple[bool, Optional[str]]:
    """
    Non-throwing version of validate_time.

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        validate_time()
        return True, None
    except TimeValidityError as e:
        return False, str(e)


# =============================================================================
# UUIDv7 Generator
# =============================================================================

class UUIDv7Generator:
    """
    Thread-safe UUIDv7 generator.

    UUIDv7 format (RFC draft):
    - 48 bits: Unix timestamp in milliseconds
    - 4 bits: Version (7)
    - 12 bits: Random (rand_a)
    - 2 bits: Variant (10)
    - 62 bits: Random (rand_b)

    Benefits:
    - Time-sortable (older IDs sort before newer)
    - Globally unique
    - No coordination required
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last_timestamp = 0
        self._sequence = 0

    def generate(self) -> str:
        """
        Generate a new UUIDv7.

        Returns:
            UUIDv7 as hyphenated string (e.g., "019beaab-ac13-7001-8000-123456789abc")

        Raises:
            TimeValidityError if system time is invalid
        """
        validate_time()

        with self._lock:
            now_ms = int(time.time() * 1000)

            if now_ms == self._last_timestamp:
                # Same millisecond - use sequence counter
                self._sequence += 1
                if self._sequence > 0xFFF:  # 12 bits max
                    # Sequence exhausted - wait for next millisecond
                    while now_ms == self._last_timestamp:
                        time.sleep(0.001)
                        now_ms = int(time.time() * 1000)
                    self._sequence = 0
            else:
                self._last_timestamp = now_ms
                self._sequence = random.randint(0, 0xFFF)

            # Build UUIDv7
            # First 48 bits: timestamp
            # Next 4 bits: version (7)
            # Next 12 bits: sequence/random
            time_high = (now_ms >> 16) & 0xFFFFFFFF
            time_low = now_ms & 0xFFFF

            # Version 7 + 12-bit sequence
            ver_seq = 0x7000 | (self._sequence & 0x0FFF)

            # Variant (10) + 62 bits random
            rand_b = random.getrandbits(62)
            var_rand = 0x8000000000000000 | rand_b

            # Combine into UUID
            uuid_int = (time_high << 96) | (time_low << 80) | (ver_seq << 64) | var_rand

            # Format as hyphenated string
            uuid_bytes = uuid_int.to_bytes(16, 'big')
            return str(uuid.UUID(bytes=uuid_bytes))

    def parse_timestamp(self, uuid7: str) -> int:
        """
        Extract timestamp from a UUIDv7.

        Args:
            uuid7: UUIDv7 string

        Returns:
            Unix timestamp in milliseconds
        """
        u = uuid.UUID(uuid7)
        uuid_int = u.int
        timestamp_ms = (uuid_int >> 80)
        return timestamp_ms

    def compare(self, uuid1: str, uuid2: str) -> int:
        """
        Compare two UUIDv7s chronologically.

        Returns:
            -1 if uuid1 < uuid2
             0 if uuid1 == uuid2
             1 if uuid1 > uuid2
        """
        ts1 = self.parse_timestamp(uuid1)
        ts2 = self.parse_timestamp(uuid2)

        if ts1 < ts2:
            return -1
        if ts1 > ts2:
            return 1

        # Same timestamp - compare full UUID
        u1 = uuid.UUID(uuid1)
        u2 = uuid.UUID(uuid2)
        if u1.int < u2.int:
            return -1
        if u1.int > u2.int:
            return 1
        return 0


# Global instance
_uuid7_generator: Optional[UUIDv7Generator] = None
_uuid7_lock = threading.Lock()


def get_uuid7_generator() -> UUIDv7Generator:
    """Get or create the global UUIDv7 generator."""
    global _uuid7_generator

    with _uuid7_lock:
        if _uuid7_generator is None:
            _uuid7_generator = UUIDv7Generator()
        return _uuid7_generator


def generate_uuidv7() -> str:
    """Convenience function to generate a UUIDv7."""
    return get_uuid7_generator().generate()


def generate_event_id() -> str:
    """Generate an event ID (alias for UUIDv7)."""
    return generate_uuidv7()


# =============================================================================
# Server UUID Management
# =============================================================================

def get_server_uuid(conn: Optional[sqlite3.Connection] = None) -> str:
    """
    Get or create the persistent server UUID.

    The server_uuid identifies this MIRS instance. It persists across restarts
    but changes if the database is reset/replaced.

    Used by clients to detect when they're talking to a new/different server
    (triggering Lifeboat restore).

    Args:
        conn: Optional database connection (creates one if not provided)

    Returns:
        Server UUID string (e.g., "MIRS-550e8400e29b41d4")
    """
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close_conn = True

    try:
        cursor = conn.cursor()

        # Ensure system_config table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Try to get existing server_uuid
        cursor.execute("SELECT value FROM system_config WHERE key = 'server_uuid'")
        row = cursor.fetchone()

        if row:
            return row[0]

        # Generate new server_uuid
        server_uuid = f"MIRS-{uuid.uuid4().hex[:16]}"

        cursor.execute(
            "INSERT INTO system_config (key, value) VALUES ('server_uuid', ?)",
            (server_uuid,)
        )
        conn.commit()

        return server_uuid

    finally:
        if close_conn:
            conn.close()


def get_db_fingerprint(conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """
    Get the database fingerprint (last event_id).

    Used by clients to detect if database is empty (needs restore).

    Args:
        conn: Optional database connection

    Returns:
        Last event_id or None if no events
    """
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close_conn = True

    try:
        cursor = conn.cursor()

        # Check if events table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='events'
        """)
        if not cursor.fetchone():
            return None

        # Get the last event_id
        cursor.execute("SELECT event_id FROM events ORDER BY event_id DESC LIMIT 1")
        row = cursor.fetchone()

        return row[0] if row else None

    finally:
        if close_conn:
            conn.close()


# =============================================================================
# Event Hash Computation
# =============================================================================

def compute_event_hash(event: dict) -> str:
    """
    Compute a hash of event content for idempotency checking.

    Only includes fields that should match for the same event.
    Excludes sync status fields that may differ.

    Args:
        event: Event dictionary

    Returns:
        16-character hex hash
    """
    import json

    # Fields that define event identity
    hashable = {
        'event_id': event.get('event_id'),
        'entity_type': event.get('entity_type'),
        'entity_id': event.get('entity_id'),
        'event_type': event.get('event_type'),
        'payload': event.get('payload') or event.get('payload_json'),
        'ts_device': event.get('ts_device'),
        'hlc': event.get('hlc') or event.get('hlc_timestamp'),
    }

    # Sort keys for deterministic hashing
    content = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


# =============================================================================
# Utility Functions
# =============================================================================

def get_current_timestamp_ms() -> int:
    """Get current Unix timestamp in milliseconds."""
    validate_time()
    return int(time.time() * 1000)


def timestamp_ms_to_iso(ts_ms: int) -> str:
    """Convert millisecond timestamp to ISO string."""
    return datetime.utcfromtimestamp(ts_ms / 1000).isoformat() + 'Z'


def iso_to_timestamp_ms(iso_str: str) -> int:
    """Convert ISO string to millisecond timestamp."""
    # Handle Z suffix
    if iso_str.endswith('Z'):
        iso_str = iso_str[:-1]
    dt = datetime.fromisoformat(iso_str)
    return int(dt.timestamp() * 1000)
