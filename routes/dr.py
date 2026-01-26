"""
MIRS Disaster Recovery (Lifeboat) API Routes

Provides REST endpoints for Walkaway Test / Disaster Recovery:
- GET /api/dr/health - Server identity and database fingerprint
- GET /api/dr/export - Export events and snapshot for client backup
- POST /api/dr/restore - Restore events and snapshot from client

Security:
- Export: No PIN required (read-only)
- Restore: Requires Admin PIN (X-MIRS-PIN header)

Version: 1.0
Date: 2026-01-26
Reference: DEV_SPEC_LIFEBOAT_MIRS_v1.1
"""

import logging
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Request, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

DB_PATH = os.environ.get('MIRS_DB_PATH', 'medical_inventory.db')
ADMIN_PIN = os.environ.get('MIRS_ADMIN_PIN', '888888')
STATION_ID = os.environ.get('MIRS_STATION_ID', 'MIRS-DEFAULT')

# =============================================================================
# Router
# =============================================================================

router = APIRouter(
    prefix="/api/dr",
    tags=["disaster-recovery"],
    # Note: This router is exempt from license middleware (C7)
)

# =============================================================================
# Request/Response Models
# =============================================================================

class DRHealthResponse(BaseModel):
    """Response for DR health check."""
    server_uuid: str
    db_fingerprint: Optional[str]
    station_id: str
    events_count: int
    last_event_hlc: Optional[str]
    system_time_ms: int
    system_time_iso: str


class ExportResponse(BaseModel):
    """Response for event export."""
    export_id: str
    exported_at: int
    server_uuid: str
    db_fingerprint: Optional[str]
    events: List[dict]
    events_count: int
    pagination: dict
    snapshot: Optional[Dict[str, List[dict]]] = None


class RestoreRequest(BaseModel):
    """Request to restore events."""
    restore_session_id: str
    source_device_id: str
    batch_number: int = 1
    total_batches: Optional[int] = None
    is_final_batch: bool = True
    snapshot: Optional[Dict[str, List[dict]]] = None
    events: List[dict] = []
    events_count: int = 0


class RestoreResponse(BaseModel):
    """Response for restore operation."""
    status: str
    restore_session_id: str
    batch_number: int
    events_received: int
    events_inserted: int
    events_already_present: int
    events_rejected: int
    rejected_event_ids: List[str]
    snapshot_tables_restored: List[str]
    message: str


class RestoreHistoryResponse(BaseModel):
    """Response for restore history."""
    sessions: List[dict]


# =============================================================================
# Import Services
# =============================================================================

try:
    from services.id_service import (
        get_server_uuid,
        get_db_fingerprint,
        get_current_timestamp_ms,
        generate_event_id,
        is_time_valid,
    )
    from services.event_service import (
        export_events,
        export_snapshot,
        restore_events_batch,
        get_event_count,
        get_last_hlc,
    )
    DR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"DR services not available: {e}")
    DR_AVAILABLE = False


# =============================================================================
# Helper Functions
# =============================================================================

def get_db_connection() -> sqlite3.Connection:
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def require_admin_pin(pin: Optional[str]):
    """
    Verify Admin PIN for sensitive operations.

    Args:
        pin: PIN from X-MIRS-PIN header

    Raises:
        HTTPException 403 if PIN is invalid or missing
    """
    if not pin:
        raise HTTPException(
            status_code=403,
            detail="Admin PIN required. Set X-MIRS-PIN header."
        )

    if pin != ADMIN_PIN:
        logger.warning(f"Invalid Admin PIN attempt")
        raise HTTPException(
            status_code=403,
            detail="Invalid Admin PIN"
        )


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/health", response_model=DRHealthResponse)
async def dr_health():
    """
    Get DR health status.

    Returns server identity and database fingerprint.
    Clients use this to detect new/empty servers (triggering restore).

    No authentication required.
    """
    if not DR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="DR services not available"
        )

    conn = get_db_connection()
    try:
        server_uuid = get_server_uuid(conn)
        db_fingerprint = get_db_fingerprint(conn)
        events_count = get_event_count(conn)
        last_hlc = get_last_hlc(conn)

        now_ms = get_current_timestamp_ms()
        now_iso = datetime.utcfromtimestamp(now_ms / 1000).isoformat() + 'Z'

        return DRHealthResponse(
            server_uuid=server_uuid,
            db_fingerprint=db_fingerprint,
            station_id=STATION_ID,
            events_count=events_count,
            last_event_hlc=last_hlc,
            system_time_ms=now_ms,
            system_time_iso=now_iso,
        )
    finally:
        conn.close()


@router.get("/export", response_model=ExportResponse)
async def dr_export(
    since_hlc: Optional[str] = Query(None, description="Export events after this HLC"),
    limit: int = Query(1000, ge=1, le=10000, description="Max events per page"),
    include_snapshot: bool = Query(False, description="Include current state snapshot"),
):
    """
    Export events for client backup.

    Supports cursor-based pagination via `since_hlc`.
    Optionally includes current state snapshot for immediate UI usability.

    No authentication required (read-only).
    """
    if not DR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="DR services not available"
        )

    conn = get_db_connection()
    try:
        # Check time validity
        time_valid, time_error = is_time_valid()
        if not time_valid:
            raise HTTPException(
                status_code=503,
                detail=f"System time invalid: {time_error}"
            )

        server_uuid = get_server_uuid(conn)
        db_fingerprint = get_db_fingerprint(conn)

        # Export events
        events, has_more, total_count = export_events(
            conn,
            since_hlc=since_hlc,
            limit=limit,
        )

        # Determine next cursor
        next_cursor = events[-1]['hlc'] if events and has_more else None

        # Export snapshot if requested
        snapshot = None
        if include_snapshot:
            snapshot = export_snapshot(conn)

        now_ms = get_current_timestamp_ms()

        return ExportResponse(
            export_id=generate_event_id(),
            exported_at=now_ms,
            server_uuid=server_uuid,
            db_fingerprint=db_fingerprint,
            events=events,
            events_count=len(events),
            pagination={
                "has_more": has_more,
                "next_cursor": next_cursor,
                "total_count": total_count,
            },
            snapshot=snapshot,
        )
    finally:
        conn.close()


@router.post("/restore", response_model=RestoreResponse)
async def dr_restore(
    request: RestoreRequest,
    x_mirs_pin: Optional[str] = Header(None, alias="X-MIRS-PIN"),
):
    """
    Restore events and snapshot from client.

    Requires Admin PIN (X-MIRS-PIN header).

    Supports batched restore:
    - First batch should include snapshot (for immediate UI usability)
    - Subsequent batches contain events only
    - Set is_final_batch=true on last batch

    All operations in a single batch are performed in one transaction
    to protect SD card lifespan.
    """
    if not DR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="DR services not available"
        )

    # G2: Require Admin PIN
    require_admin_pin(x_mirs_pin)

    conn = get_db_connection()
    try:
        # Check time validity
        time_valid, time_error = is_time_valid()
        if not time_valid:
            raise HTTPException(
                status_code=503,
                detail=f"System time invalid: {time_error}"
            )

        # Perform restore
        result = restore_events_batch(
            conn=conn,
            restore_session_id=request.restore_session_id,
            source_device_id=request.source_device_id,
            events=request.events,
            snapshot=request.snapshot,
            batch_number=request.batch_number,
            is_final_batch=request.is_final_batch,
        )

        logger.info(
            f"Restore batch {request.batch_number} from {request.source_device_id}: "
            f"{result.events_inserted} inserted, {result.events_already_present} existing, "
            f"{result.events_rejected} rejected"
        )

        return RestoreResponse(
            status=result.status,
            restore_session_id=result.restore_session_id,
            batch_number=result.batch_number,
            events_received=result.events_received,
            events_inserted=result.events_inserted,
            events_already_present=result.events_already_present,
            events_rejected=result.events_rejected,
            rejected_event_ids=result.rejected_event_ids,
            snapshot_tables_restored=result.snapshot_tables_restored,
            message=result.message,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Restore failed: {str(e)}"
        )
    finally:
        conn.close()


@router.get("/history", response_model=RestoreHistoryResponse)
async def dr_history(
    limit: int = Query(20, ge=1, le=100, description="Max sessions to return"),
):
    """
    Get restore history.

    Returns a summary of previous restore sessions.
    No authentication required (read-only).
    """
    if not DR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="DR services not available"
        )

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Check if view exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='view' AND name='v_restore_history'
        """)
        if not cursor.fetchone():
            return RestoreHistoryResponse(sessions=[])

        cursor.execute(f"""
            SELECT * FROM v_restore_history
            LIMIT {limit}
        """)

        sessions = [dict(row) for row in cursor.fetchall()]
        return RestoreHistoryResponse(sessions=sessions)
    finally:
        conn.close()


@router.get("/stats")
async def dr_stats():
    """
    Get DR statistics.

    Returns event counts by entity type.
    No authentication required (read-only).
    """
    if not DR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="DR services not available"
        )

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Check if view exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='view' AND name='v_event_stats'
        """)
        if not cursor.fetchone():
            return {"stats": [], "total_events": 0}

        cursor.execute("SELECT * FROM v_event_stats")
        stats = [dict(row) for row in cursor.fetchall()]

        total_events = sum(s.get('event_count', 0) for s in stats)

        return {
            "stats": stats,
            "total_events": total_events,
        }
    finally:
        conn.close()
