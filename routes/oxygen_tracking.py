"""
xIRS Oxygen Tracking Module v1.0

Implements DEV_SPEC_OXYGEN_TRACKING_SYNC_v1.1:
- Canonical oxygen events (OXYGEN_CLAIMED, OXYGEN_FLOW_CHANGE, OXYGEN_CHECKED, OXYGEN_SWAPPED, OXYGEN_RELEASED)
- Virtual Sensor calculation
- Projection updates
- SSE endpoint for cross-device sync

Author: Claude Code (Opus 4.5)
Date: 2026-01-24
"""

import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# =============================================================================
# Router Setup
# =============================================================================

router = APIRouter(prefix="/api/oxygen", tags=["oxygen-tracking"])

IS_VERCEL = os.environ.get("VERCEL") == "1"
# Use medical_inventory.db which contains equipment_units table
DB_PATH = os.environ.get("MIRS_DB_PATH", "medical_inventory.db")


def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# Phase 2: Canonical Events Schema
# =============================================================================

def init_oxygen_events_schema(cursor):
    """
    Initialize oxygen events table (main events table for Walkaway compatibility)

    This follows the entity_type/entity_id pattern for event sourcing.
    """

    # Main events table (if not exists)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_id TEXT UNIQUE NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            ts_device INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            sync_status TEXT DEFAULT 'LOCAL'
        )
    """)

    # Indexes for efficient querying
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_entity
        ON events(entity_type, entity_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_type
        ON events(event_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_ts
        ON events(ts_device)
    """)

    # Add last_flow_rate_lpm to equipment_units if not exists
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN last_flow_rate_lpm REAL")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add capacity_liters to equipment if not exists (for cylinder types)
    try:
        cursor.execute("ALTER TABLE equipment ADD COLUMN capacity_liters INTEGER")
    except sqlite3.OperationalError:
        pass


# =============================================================================
# Phase 3: Request/Response Models
# =============================================================================

class ClaimOxygenRequest(BaseModel):
    unit_id: int = Field(..., description="equipment_units.id")
    initial_level_percent: int = Field(..., ge=0, le=100)
    initial_psi: Optional[int] = Field(None, ge=0)
    flow_rate_lpm: float = Field(..., gt=0, description="Flow rate in L/min")
    capacity_liters: int = Field(680, description="Cylinder capacity (E=680L, H=7000L)")
    note: Optional[str] = None


class FlowChangeRequest(BaseModel):
    new_flow_rate_lpm: float = Field(..., gt=0)
    reason: Optional[str] = None


class OxygenCheckRequest(BaseModel):
    level_percent: int = Field(..., ge=0, le=100)
    psi: Optional[int] = Field(None, ge=0)
    flow_rate_lpm: Optional[float] = Field(None, gt=0)


class SwapCylinderRequest(BaseModel):
    old_unit_id: int
    old_final_level_percent: int = Field(..., ge=0, le=100)
    old_final_psi: Optional[int] = Field(None, ge=0)
    new_unit_id: int
    new_initial_level_percent: int = Field(..., ge=0, le=100)
    new_initial_psi: Optional[int] = Field(None, ge=0)
    new_capacity_liters: int = Field(680)
    inherited_flow_rate_lpm: float = Field(..., gt=0)


class ReleaseOxygenRequest(BaseModel):
    final_level_percent: int = Field(..., ge=0, le=100)
    final_psi: Optional[int] = Field(None, ge=0)


# =============================================================================
# Phase 3: Core Event Creation Functions
# =============================================================================

def create_oxygen_event(
    cursor,
    entity_id: int,
    event_type: str,
    payload: dict,
    actor_id: str
) -> dict:
    """
    Create a canonical oxygen event in the events table.

    This is the ONLY way to record oxygen state changes (Single Source of Truth).
    """
    # Use uuid7 if available (Python 3.12+), otherwise fall back to uuid4
    event_id = str(uuid.uuid7() if hasattr(uuid, 'uuid7') else uuid.uuid4())
    ts_device = int(time.time() * 1000)

    cursor.execute("""
        INSERT INTO events (id, event_id, entity_type, entity_id, event_type, ts_device, actor_id, payload)
        VALUES (?, ?, 'equipment_unit', ?, ?, ?, ?, ?)
    """, (
        event_id,
        event_id,
        str(entity_id),
        event_type,
        ts_device,
        actor_id,
        json.dumps(payload)
    ))

    return {
        "event_id": event_id,
        "entity_type": "equipment_unit",
        "entity_id": str(entity_id),
        "event_type": event_type,
        "ts_device": ts_device,
        "actor_id": actor_id,
        "payload": payload
    }


# =============================================================================
# Phase 4: Virtual Sensor Calculation
# =============================================================================

def calculate_virtual_sensor(cursor, unit_id: int, case_id: str) -> Optional[dict]:
    """
    Virtual Sensor: Calculate current oxygen level based on flow events.

    This is the CORRECT way to get real-time oxygen levels.
    Instead of writing events every minute (DB spam), we calculate on-demand.

    Flow Rate Authority (ChatGPT recommendation):
    1. Most recent OXYGEN_CHECKED.flow_rate_lpm
    2. Else OXYGEN_FLOW_CHANGE.new_flow_rate_lpm
    3. Else OXYGEN_CLAIMED.flow_rate_lpm
    """
    # Get all relevant events for this unit
    cursor.execute("""
        SELECT event_type, payload, ts_device
        FROM events
        WHERE entity_type = 'equipment_unit'
          AND entity_id = ?
          AND event_type IN ('OXYGEN_CLAIMED', 'OXYGEN_FLOW_CHANGE', 'OXYGEN_CHECKED')
        ORDER BY ts_device DESC
    """, (str(unit_id),))

    events = cursor.fetchall()
    if not events:
        return None

    # Extract values from events (priority: CHECKED > FLOW_CHANGE > CLAIMED)
    flow_rate = None
    initial_level = None
    claim_time = None
    capacity = None

    # Track flow rate changes for segment-based calculation
    flow_segments = []
    last_check_time = None
    last_check_level = None

    for event in events:
        payload = json.loads(event['payload'])
        event_type = event['event_type']
        event_ts = event['ts_device']

        if event_type == 'OXYGEN_CHECKED':
            if flow_rate is None:
                flow_rate = payload.get('flow_rate_lpm')
            if last_check_time is None:
                last_check_time = event_ts
                last_check_level = payload.get('level_percent')

        elif event_type == 'OXYGEN_FLOW_CHANGE':
            if flow_rate is None:
                flow_rate = payload.get('new_flow_rate_lpm')
            flow_segments.append({
                'time': event_ts,
                'flow_rate': payload.get('new_flow_rate_lpm')
            })

        elif event_type == 'OXYGEN_CLAIMED':
            if flow_rate is None:
                flow_rate = payload.get('flow_rate_lpm', 2.0)
            initial_level = payload.get('initial_level_percent')
            claim_time = event_ts
            capacity = payload.get('capacity_liters', 680)

    if not all([flow_rate, claim_time, capacity]):
        return None

    # Use last check as baseline if available
    if last_check_time and last_check_level is not None:
        baseline_time = last_check_time
        baseline_level = last_check_level
    else:
        baseline_time = claim_time
        baseline_level = initial_level

    if baseline_level is None:
        return None

    # Calculate consumption since baseline
    current_time = int(time.time() * 1000)
    elapsed_ms = current_time - baseline_time
    elapsed_minutes = elapsed_ms / 1000 / 60

    # Calculate using current flow rate (simplified - not segment-based for now)
    baseline_liters = (baseline_level / 100) * capacity
    consumed_liters = elapsed_minutes * flow_rate
    remaining_liters = max(0, baseline_liters - consumed_liters)

    current_level = int(remaining_liters / capacity * 100)
    time_to_empty = int(remaining_liters / flow_rate) if flow_rate > 0 else None

    return {
        'current_level': max(0, min(100, current_level)),
        'consumed_liters': round(consumed_liters, 1),
        'remaining_liters': round(remaining_liters, 1),
        'flow_rate_lpm': flow_rate,
        'time_to_empty': time_to_empty,
        'elapsed_minutes': round(elapsed_minutes, 1),
        'baseline_level': baseline_level,
        'capacity_liters': capacity
    }


# =============================================================================
# Phase 6: Projection Update Functions
# =============================================================================

def update_oxygen_projection(conn, event: dict):
    """
    Update equipment_units projection based on oxygen event.

    Rule (ChatGPT): level_percent is only updated by projection logic,
    not by arbitrary services writing back.
    """
    cursor = conn.cursor()
    unit_id = int(event['entity_id'])
    payload = event['payload'] if isinstance(event['payload'], dict) else json.loads(event['payload'])
    event_type = event['event_type']

    if event_type == 'OXYGEN_CLAIMED':
        cursor.execute("""
            UPDATE equipment_units SET
                status = 'IN_USE',
                claimed_by_case_id = ?,
                claimed_at = datetime('now'),
                last_flow_rate_lpm = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload.get('case_id'), payload.get('flow_rate_lpm', 2.0), unit_id))

    elif event_type == 'OXYGEN_FLOW_CHANGE':
        cursor.execute("""
            UPDATE equipment_units SET
                last_flow_rate_lpm = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload.get('new_flow_rate_lpm'), unit_id))

    elif event_type == 'OXYGEN_CHECKED':
        # Manual check updates cached value
        cursor.execute("""
            UPDATE equipment_units SET
                level_percent = ?,
                last_flow_rate_lpm = COALESCE(?, last_flow_rate_lpm),
                last_check = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload.get('level_percent'), payload.get('flow_rate_lpm'), unit_id))

    elif event_type == 'OXYGEN_RELEASED':
        new_status = 'AVAILABLE' if payload.get('final_level_percent', 0) > 10 else 'EMPTY'
        cursor.execute("""
            UPDATE equipment_units SET
                status = ?,
                level_percent = ?,
                claimed_by_case_id = NULL,
                claimed_at = NULL,
                claimed_by_user_id = NULL,
                last_flow_rate_lpm = NULL,
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload.get('new_status', new_status), payload.get('final_level_percent'), unit_id))

    elif event_type == 'OXYGEN_SWAPPED':
        old = payload.get('old_cylinder', {})
        new = payload.get('new_cylinder', {})

        # Old cylinder -> EMPTY
        cursor.execute("""
            UPDATE equipment_units SET
                status = ?,
                level_percent = ?,
                claimed_by_case_id = NULL,
                claimed_at = NULL,
                claimed_by_user_id = NULL,
                last_flow_rate_lpm = NULL,
                updated_at = datetime('now')
            WHERE id = ?
        """, (old.get('new_status', 'EMPTY'), old.get('final_level_percent'), old.get('unit_id')))

        # New cylinder -> IN_USE
        cursor.execute("""
            UPDATE equipment_units SET
                status = 'IN_USE',
                level_percent = ?,
                claimed_by_case_id = ?,
                claimed_at = datetime('now'),
                last_flow_rate_lpm = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (
            new.get('initial_level_percent'),
            payload.get('case_id'),
            new.get('inherited_flow_rate_lpm'),
            new.get('unit_id')
        ))

    conn.commit()


# =============================================================================
# Phase 3 & 5: API Endpoints
# =============================================================================

@router.post("/cases/{case_id}/claim")
async def claim_oxygen(
    case_id: str,
    request: ClaimOxygenRequest,
    actor_id: str = Query(...)
):
    """
    Claim an oxygen cylinder for a case.

    Creates OXYGEN_CLAIMED event and updates projection.
    """
    if IS_VERCEL:
        # Return demo response for Vercel
        return {
            "success": True,
            "event_id": f"demo-{uuid.uuid4().hex[:8]}",
            "message": "Demo mode - oxygen claimed",
            "live_status": {
                "unit_id": request.unit_id,
                "status": "IN_USE",
                "level_percent": request.initial_level_percent,
                "flow_rate_lpm": request.flow_rate_lpm
            }
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check unit exists and is available
        cursor.execute("""
            SELECT id, unit_serial, claimed_by_case_id, level_percent, status
            FROM equipment_units WHERE id = ?
        """, (request.unit_id,))
        unit = cursor.fetchone()

        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")

        if unit['claimed_by_case_id']:
            raise HTTPException(
                status_code=409,
                detail=f"Unit already claimed by case {unit['claimed_by_case_id']}"
            )

        # Get equipment info for capacity
        cursor.execute("""
            SELECT e.name, e.capacity_liters
            FROM equipment e
            JOIN equipment_units eu ON eu.equipment_id = e.id
            WHERE eu.id = ?
        """, (request.unit_id,))
        equip = cursor.fetchone()

        # Determine cylinder type from equipment name
        cylinder_type = 'E' if equip and 'E' in equip['name'] else 'H'
        capacity = request.capacity_liters or (equip['capacity_liters'] if equip and equip['capacity_liters'] else 680)

        # Create OXYGEN_CLAIMED event
        payload = {
            "case_id": case_id,
            "unit_serial": unit['unit_serial'],
            "cylinder_type": cylinder_type,
            "initial_level_percent": request.initial_level_percent,
            "initial_psi": request.initial_psi,
            "capacity_liters": capacity,
            "flow_rate_lpm": request.flow_rate_lpm,
            "note": request.note
        }

        event = create_oxygen_event(cursor, request.unit_id, "OXYGEN_CLAIMED", payload, actor_id)

        # Update projection
        update_oxygen_projection(conn, event)

        # Also update anesthesia_cases oxygen_source
        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = 'CYLINDER', oxygen_source_id = ?
            WHERE id = ?
        """, (str(request.unit_id), case_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event['event_id'],
            "message": f"Cylinder {unit['unit_serial']} claimed",
            "live_status": {
                "unit_id": request.unit_id,
                "unit_serial": unit['unit_serial'],
                "status": "IN_USE",
                "level_percent": request.initial_level_percent,
                "flow_rate_lpm": request.flow_rate_lpm,
                "capacity_liters": capacity
            }
        }

    finally:
        conn.close()


@router.post("/cases/{case_id}/flow-change")
async def change_flow_rate(
    case_id: str,
    unit_id: int,
    request: FlowChangeRequest,
    actor_id: str = Query(...)
):
    """
    Record a flow rate change for an oxygen cylinder.
    """
    if IS_VERCEL:
        return {"success": True, "message": "Demo mode - flow rate changed"}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Verify unit is claimed by this case
        cursor.execute("""
            SELECT last_flow_rate_lpm FROM equipment_units
            WHERE id = ? AND claimed_by_case_id = ?
        """, (unit_id, case_id))
        unit = cursor.fetchone()

        if not unit:
            raise HTTPException(status_code=404, detail="Unit not claimed by this case")

        payload = {
            "case_id": case_id,
            "previous_flow_rate_lpm": unit['last_flow_rate_lpm'],
            "new_flow_rate_lpm": request.new_flow_rate_lpm,
            "reason": request.reason
        }

        event = create_oxygen_event(cursor, unit_id, "OXYGEN_FLOW_CHANGE", payload, actor_id)
        update_oxygen_projection(conn, event)
        conn.commit()

        return {
            "success": True,
            "event_id": event['event_id'],
            "previous_flow_rate": unit['last_flow_rate_lpm'],
            "new_flow_rate": request.new_flow_rate_lpm
        }

    finally:
        conn.close()


@router.post("/cases/{case_id}/check")
async def check_oxygen(
    case_id: str,
    unit_id: int,
    request: OxygenCheckRequest,
    actor_id: str = Query(...)
):
    """
    Record a manual PSI/level check (recalibration point).
    """
    if IS_VERCEL:
        return {"success": True, "message": "Demo mode - oxygen checked"}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT id FROM equipment_units
            WHERE id = ? AND claimed_by_case_id = ?
        """, (unit_id, case_id))

        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Unit not claimed by this case")

        payload = {
            "case_id": case_id,
            "level_percent": request.level_percent,
            "psi": request.psi,
            "flow_rate_lpm": request.flow_rate_lpm
        }

        event = create_oxygen_event(cursor, unit_id, "OXYGEN_CHECKED", payload, actor_id)
        update_oxygen_projection(conn, event)
        conn.commit()

        return {
            "success": True,
            "event_id": event['event_id'],
            "level_percent": request.level_percent
        }

    finally:
        conn.close()


# =============================================================================
# Phase 7: Swap Workflow
# =============================================================================

@router.post("/cases/{case_id}/swap")
async def swap_cylinder(
    case_id: str,
    request: SwapCylinderRequest,
    actor_id: str = Query(...)
):
    """
    Atomic cylinder swap operation.

    Releases old cylinder (marks as EMPTY) and claims new cylinder in one transaction.
    """
    if IS_VERCEL:
        return {"success": True, "message": "Demo mode - cylinder swapped"}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Verify old unit is claimed by this case
        cursor.execute("""
            SELECT eu.*, e.capacity_liters
            FROM equipment_units eu
            LEFT JOIN equipment e ON eu.equipment_id = e.id
            WHERE eu.id = ? AND eu.claimed_by_case_id = ?
        """, (request.old_unit_id, case_id))
        old_unit = cursor.fetchone()

        if not old_unit:
            raise HTTPException(status_code=404, detail="Old unit not claimed by this case")

        # Verify new unit is available
        cursor.execute("""
            SELECT eu.*, e.capacity_liters, e.name
            FROM equipment_units eu
            LEFT JOIN equipment e ON eu.equipment_id = e.id
            WHERE eu.id = ?
        """, (request.new_unit_id,))
        new_unit = cursor.fetchone()

        if not new_unit:
            raise HTTPException(status_code=404, detail="New unit not found")

        if new_unit['claimed_by_case_id']:
            raise HTTPException(
                status_code=409,
                detail=f"New unit already claimed by {new_unit['claimed_by_case_id']}"
            )

        # Calculate consumed liters from old cylinder
        old_capacity = old_unit['capacity_liters'] or 680
        consumed_liters = round((100 - request.old_final_level_percent) / 100 * old_capacity, 1)

        # Create OXYGEN_SWAPPED event
        payload = {
            "case_id": case_id,
            "old_cylinder": {
                "unit_id": request.old_unit_id,
                "unit_serial": old_unit['unit_serial'],
                "final_level_percent": request.old_final_level_percent,
                "final_psi": request.old_final_psi,
                "consumed_liters": consumed_liters,
                "new_status": "EMPTY"
            },
            "new_cylinder": {
                "unit_id": request.new_unit_id,
                "unit_serial": new_unit['unit_serial'],
                "initial_level_percent": request.new_initial_level_percent,
                "initial_psi": request.new_initial_psi,
                "capacity_liters": request.new_capacity_liters,
                "inherited_flow_rate_lpm": request.inherited_flow_rate_lpm
            }
        }

        # Create event with old unit as entity_id (primary subject)
        event = create_oxygen_event(cursor, request.old_unit_id, "OXYGEN_SWAPPED", payload, actor_id)

        # Update projections for both units
        update_oxygen_projection(conn, event)

        # Update anesthesia_cases oxygen_source
        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_id = ?
            WHERE id = ?
        """, (str(request.new_unit_id), case_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event['event_id'],
            "old_cylinder": {
                "unit_id": request.old_unit_id,
                "status": "EMPTY",
                "consumed_liters": consumed_liters
            },
            "new_cylinder": {
                "unit_id": request.new_unit_id,
                "status": "IN_USE",
                "level_percent": request.new_initial_level_percent
            }
        }

    finally:
        conn.close()


@router.post("/cases/{case_id}/release")
async def release_oxygen(
    case_id: str,
    request: ReleaseOxygenRequest,
    actor_id: str = Query(...)
):
    """
    Release oxygen cylinder from case.
    """
    if IS_VERCEL:
        return {"success": True, "message": "Demo mode - oxygen released"}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get current cylinder info - first try via anesthesia_cases, then fallback to direct claim
        cursor.execute("""
            SELECT eu.*, ac.id as case_id
            FROM anesthesia_cases ac
            JOIN equipment_units eu ON eu.id = CAST(ac.oxygen_source_id AS INTEGER)
            WHERE ac.id = ? AND eu.claimed_by_case_id = ?
        """, (case_id, case_id))
        unit = cursor.fetchone()

        # Fallback: find by claimed_by_case_id directly (for non-anesthesia cases)
        if not unit:
            cursor.execute("""
                SELECT * FROM equipment_units
                WHERE claimed_by_case_id = ?
            """, (case_id,))
            unit = cursor.fetchone()

        if not unit:
            raise HTTPException(status_code=404, detail="No cylinder claimed by this case")

        # Determine new status based on remaining level
        new_status = 'AVAILABLE' if request.final_level_percent > 10 else 'EMPTY'

        payload = {
            "case_id": case_id,
            "final_level_percent": request.final_level_percent,
            "final_psi": request.final_psi,
            "new_status": new_status
        }

        event = create_oxygen_event(cursor, unit['id'], "OXYGEN_RELEASED", payload, actor_id)
        update_oxygen_projection(conn, event)

        # Clear anesthesia_cases oxygen_source
        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = NULL, oxygen_source_id = NULL
            WHERE id = ?
        """, (case_id,))

        conn.commit()

        return {
            "success": True,
            "event_id": event['event_id'],
            "unit_id": unit['id'],
            "final_level_percent": request.final_level_percent,
            "new_status": new_status
        }

    finally:
        conn.close()


# =============================================================================
# Phase 5: Live Status Endpoint
# =============================================================================

@router.get("/units/{unit_id}/live-status")
async def get_unit_live_status(unit_id: int):
    """
    Get live status of an oxygen unit including Virtual Sensor calculation.

    Returns:
        - level_percent: Cached projection value
        - live_level_percent: Real-time calculated value (if IN_USE)
        - consumed_liters, remaining_liters, time_to_empty_minutes
    """
    if IS_VERCEL:
        # Demo data
        return {
            "unit_id": unit_id,
            "unit_serial": f"O2-DEMO-{unit_id:03d}",
            "status": "IN_USE",
            "level_percent": 85,
            "live_level_percent": 82,
            "consumed_liters": 122.4,
            "remaining_liters": 557.6,
            "flow_rate_lpm": 2.0,
            "time_to_empty_minutes": 279,
            "is_live_calculation": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT eu.*, e.capacity_liters, e.name as equipment_name
            FROM equipment_units eu
            LEFT JOIN equipment e ON eu.equipment_id = e.id
            WHERE eu.id = ?
        """, (unit_id,))

        unit = cursor.fetchone()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")

        result = dict(unit)
        result['is_live_calculation'] = False

        # If in use, calculate live values
        if unit['status'] == 'IN_USE' and unit['claimed_by_case_id']:
            live = calculate_virtual_sensor(cursor, unit_id, unit['claimed_by_case_id'])
            if live:
                result.update({
                    'live_level_percent': live['current_level'],
                    'consumed_liters': live['consumed_liters'],
                    'remaining_liters': live['remaining_liters'],
                    'flow_rate_lpm': live['flow_rate_lpm'],
                    'time_to_empty_minutes': live['time_to_empty'],
                    'elapsed_minutes': live['elapsed_minutes'],
                    'is_live_calculation': True
                })

        return result

    finally:
        conn.close()


@router.get("/units")
async def list_oxygen_units():
    """
    List all oxygen-related equipment units with live status.
    """
    if IS_VERCEL:
        return {
            "units": [
                {"unit_id": 1, "unit_serial": "E-CYL-001", "status": "AVAILABLE", "level_percent": 100},
                {"unit_id": 2, "unit_serial": "E-CYL-002", "status": "IN_USE", "level_percent": 85, "claimed_by_case_id": "ANES-DEMO-001"},
                {"unit_id": 3, "unit_serial": "H-CYL-001", "status": "EMPTY", "level_percent": 5}
            ]
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get all oxygen-related units (E-type and H-type cylinders)
        # Note: capacity_liters is derived from cylinder type (E=680L, H=6900L)
        cursor.execute("""
            SELECT eu.*, e.name as equipment_name
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE e.name LIKE '%氧氣%' OR e.name LIKE '%O2%' OR e.id LIKE '%CYL%'
               OR eu.unit_serial LIKE '%CYL%' OR eu.unit_serial LIKE 'O2%'
            ORDER BY eu.equipment_id, eu.unit_serial
        """)

        units = []
        for row in cursor.fetchall():
            unit_data = dict(row)

            # Add live calculation if in use
            if row['status'] == 'IN_USE' and row['claimed_by_case_id']:
                live = calculate_virtual_sensor(cursor, row['id'], row['claimed_by_case_id'])
                if live:
                    unit_data['live_level_percent'] = live['current_level']
                    unit_data['time_to_empty_minutes'] = live['time_to_empty']

            units.append(unit_data)

        return {"units": units}

    finally:
        conn.close()


# =============================================================================
# Phase 9: SSE Endpoint for Cross-Device Sync
# =============================================================================

@router.get("/events/stream")
async def event_stream(
    entity_type: Optional[str] = Query(None),
    since_event_id: Optional[str] = Query(None)
):
    """
    Server-Sent Events (SSE) endpoint for cross-device sync.

    BioMed / MIRS can subscribe to receive real-time event notifications.

    Note: This is for cross-device sync. Same-device uses xIRS.Bus (BroadcastChannel).
    """
    if IS_VERCEL:
        # Vercel doesn't support long-running SSE well, return demo
        async def demo_generator():
            yield f"data: {json.dumps({'type': 'connected', 'message': 'Demo SSE mode'})}\n\n"
            await asyncio.sleep(5)
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

        return StreamingResponse(
            demo_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    async def generate() -> AsyncGenerator[str, None]:
        conn = get_db_connection()
        cursor = conn.cursor()
        last_id = since_event_id

        # Send connected message
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"

        try:
            while True:
                # Query for new events
                if last_id:
                    cursor.execute("""
                        SELECT * FROM events
                        WHERE id > ?
                        AND (entity_type = ? OR ? IS NULL)
                        ORDER BY ts_device ASC
                        LIMIT 100
                    """, (last_id, entity_type, entity_type))
                else:
                    # First connection - just get latest event ID
                    cursor.execute("SELECT id FROM events ORDER BY ts_device DESC LIMIT 1")
                    row = cursor.fetchone()
                    last_id = row['id'] if row else ''
                    yield f"data: {json.dumps({'type': 'sync', 'last_event_id': last_id})}\n\n"
                    await asyncio.sleep(1)
                    continue

                events = cursor.fetchall()

                for event in events:
                    event_data = {
                        'type': 'event',
                        'event_id': event['event_id'],
                        'entity_type': event['entity_type'],
                        'entity_id': event['entity_id'],
                        'event_type': event['event_type'],
                        'ts_device': event['ts_device'],
                        'payload': json.loads(event['payload'])
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                    last_id = event['id']

                # Heartbeat every 30 seconds
                yield f"data: {json.dumps({'type': 'heartbeat', 'ts': int(time.time() * 1000)})}\n\n"

                await asyncio.sleep(1)  # Poll interval

        except asyncio.CancelledError:
            pass
        finally:
            conn.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# =============================================================================
# Utility: Get Events for a Unit (for debugging/audit)
# =============================================================================

@router.get("/units/{unit_id}/events")
async def get_unit_events(
    unit_id: int,
    limit: int = Query(50, le=200)
):
    """
    Get event history for an oxygen unit.
    """
    if IS_VERCEL:
        return {"events": [], "message": "Demo mode - no events stored"}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT * FROM events
            WHERE entity_type = 'equipment_unit' AND entity_id = ?
            ORDER BY ts_device DESC
            LIMIT ?
        """, (str(unit_id), limit))

        events = []
        for row in cursor.fetchall():
            events.append({
                "event_id": row['event_id'],
                "event_type": row['event_type'],
                "ts_device": row['ts_device'],
                "actor_id": row['actor_id'],
                "payload": json.loads(row['payload']),
                "created_at": row['created_at']
            })

        return {"unit_id": unit_id, "events": events}

    finally:
        conn.close()


# =============================================================================
# Schema Initialization Hook
# =============================================================================

def init_schema():
    """Initialize oxygen tracking schema (called from main.py)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        init_oxygen_events_schema(cursor)
        conn.commit()
    finally:
        conn.close()
