"""
MIRS Anesthesia Module - Phase A
Event-Sourced, Offline-First Architecture

Version: 1.5.1
"""

import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/anesthesia", tags=["anesthesia"])


# =============================================================================
# Enums
# =============================================================================

class ContextMode(str, Enum):
    STANDARD = "STANDARD"
    BATTLEFIELD = "BATTLEFIELD"


class CaseStatus(str, Enum):
    PREOP = "PREOP"
    IN_PROGRESS = "IN_PROGRESS"
    PACU = "PACU"
    CLOSED = "CLOSED"


class AnesthesiaTechnique(str, Enum):
    GA_ETT = "GA_ETT"           # General Anesthesia with ETT
    GA_LMA = "GA_LMA"           # General Anesthesia with LMA
    GA_MASK = "GA_MASK"         # General Anesthesia with Mask
    RA_SPINAL = "RA_SPINAL"     # Regional - Spinal
    RA_EPIDURAL = "RA_EPIDURAL" # Regional - Epidural
    RA_NERVE = "RA_NERVE"       # Regional - Nerve Block
    LA = "LA"                   # Local Anesthesia
    SEDATION = "SEDATION"       # Monitored Anesthesia Care / Sedation


class EventType(str, Enum):
    # Vital Signs
    VITAL_SIGN = "VITAL_SIGN"

    # Medications
    MEDICATION_ADMIN = "MEDICATION_ADMIN"

    # Fluids & Blood
    FLUID_IN = "FLUID_IN"
    BLOOD_PRODUCT = "BLOOD_PRODUCT"
    FLUID_OUT = "FLUID_OUT"

    # Airway
    AIRWAY_EVENT = "AIRWAY_EVENT"

    # Milestones
    MILESTONE = "MILESTONE"

    # Resource
    RESOURCE_CHECK = "RESOURCE_CHECK"

    # Equipment
    EQUIPMENT_EVENT = "EQUIPMENT_EVENT"

    # Notes
    NOTE = "NOTE"

    # Lifecycle
    STATUS_CHANGE = "STATUS_CHANGE"
    STAFF_CHANGE = "STAFF_CHANGE"

    # Corrections
    CORRECTION = "CORRECTION"


class OxygenSourceType(str, Enum):
    CENTRAL = "CENTRAL"
    CONCENTRATOR = "CONCENTRATOR"
    CYLINDER = "CYLINDER"


class PreopMode(str, Enum):
    STANDARD = "STANDARD"
    BATTLEFIELD = "BATTLEFIELD"


class PreopStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# Phase B: Drug Transaction Types
class DrugTxType(str, Enum):
    DISPENSE = "DISPENSE"   # 藥局核發
    ADMIN = "ADMIN"         # 給藥
    WASTE = "WASTE"         # 廢棄 (需見證)
    RETURN = "RETURN"       # 退回


class DrugRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISPENSED = "DISPENSED"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"


# =============================================================================
# Request/Response Models
# =============================================================================

class PatientSnapshot(BaseModel):
    """Patient data snapshot for offline resilience (Hub-Satellite sync)"""
    name: Optional[str] = None
    dob: Optional[str] = None
    sex: Optional[str] = None
    allergies: Optional[List[str]] = None
    weight_kg: Optional[float] = None
    blood_type: Optional[str] = None
    # Additional fields from CIRS
    triage_category: Optional[str] = None
    chief_complaint: Optional[str] = None


class CreateCaseRequest(BaseModel):
    surgery_case_id: Optional[str] = None
    patient_id: str
    patient_name: Optional[str] = None
    context_mode: ContextMode = ContextMode.STANDARD
    planned_technique: Optional[AnesthesiaTechnique] = None
    primary_anesthesiologist_id: Optional[str] = None
    primary_nurse_id: Optional[str] = None
    # Hub-Satellite sync fields
    cirs_registration_ref: Optional[str] = None
    patient_snapshot: Optional[PatientSnapshot] = None


class CaseResponse(BaseModel):
    id: str
    surgery_case_id: Optional[str]
    patient_id: str
    patient_name: Optional[str]
    context_mode: str
    planned_technique: Optional[str]
    primary_anesthesiologist_id: Optional[str]
    primary_nurse_id: Optional[str]
    oxygen_source_type: Optional[str]
    oxygen_source_id: Optional[str]
    status: str
    preop_completed_at: Optional[str]
    anesthesia_start_at: Optional[str]
    surgery_start_at: Optional[str]
    surgery_end_at: Optional[str]
    anesthesia_end_at: Optional[str]
    created_at: str
    created_by: str


class AddEventRequest(BaseModel):
    event_type: EventType
    clinical_time: Optional[datetime] = None  # If None, use current time
    payload: Dict[str, Any]
    device_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    is_correction: bool = False
    corrects_event_id: Optional[str] = None
    correction_reason: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    case_id: str
    event_type: str
    clinical_time: str
    recorded_at: str
    payload: Dict[str, Any]
    actor_id: str
    device_id: Optional[str]
    idempotency_key: Optional[str]
    is_correction: bool
    corrects_event_id: Optional[str]


class VitalSignPayload(BaseModel):
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    etco2: Optional[int] = None
    temp: Optional[float] = None
    o2_flow_lpm: Optional[float] = None
    fio2: Optional[float] = None
    rr: Optional[int] = None  # Respiratory rate


class QuickVitalRequest(BaseModel):
    """One-tap vital sign entry"""
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    etco2: Optional[int] = None
    temp: Optional[float] = None
    o2_flow_lpm: Optional[float] = None
    device_id: Optional[str] = None


class QuickMedicationRequest(BaseModel):
    """Quick medication entry"""
    drug_code: str
    drug_name: str
    dose: float
    unit: str
    route: str = "IV"
    device_id: Optional[str] = None


class ClaimOxygenRequest(BaseModel):
    cylinder_unit_id: int
    initial_pressure_psi: Optional[int] = None


# PreOp Models
class BattlefieldQuickFlags(BaseModel):
    airway_risk: str = Field(..., pattern="^(NORMAL|DIFFICULT)$")
    hd_stable: str = Field(..., pattern="^(YES|NO|UNKNOWN)$")
    npo_status: str = Field(..., pattern="^(EMPTY|FULL_OR_UNKNOWN)$")
    hemorrhage_risk: str = Field(..., pattern="^(LOW|HIGH)$")
    estimated_duration: str = Field(..., pattern="^(SHORT|MEDIUM|LONG)$")
    critical_notes: Optional[str] = None


class CreatePreopRequest(BaseModel):
    mode: PreopMode = PreopMode.STANDARD

    # Standard mode fields
    asa_class: Optional[int] = Field(None, ge=1, le=6)
    asa_emergency: bool = False
    npo_hours: Optional[float] = None
    npo_status: Optional[str] = None
    allergies: Optional[List[str]] = None
    mallampati_score: Optional[int] = Field(None, ge=1, le=4)
    difficult_airway_anticipated: bool = False
    comorbidities: Optional[List[str]] = None

    # Battlefield mode
    quick_flags: Optional[BattlefieldQuickFlags] = None

    # Common
    planned_technique: Optional[str] = None
    special_considerations: Optional[str] = None


class PreopResponse(BaseModel):
    id: str
    case_id: str
    mode: str
    status: str
    asa_class: Optional[int]
    asa_emergency: bool
    npo_hours: Optional[float]
    allergies: Optional[List[str]]
    mallampati_score: Optional[int]
    difficult_airway_anticipated: bool
    quick_flags: Optional[Dict[str, Any]]
    planned_technique: Optional[str]
    assessed_by: str
    assessment_datetime: str


# =============================================================================
# Database Schema Initialization
# =============================================================================

def init_anesthesia_schema(cursor):
    """Initialize anesthesia module tables"""

    # Anesthesia Cases (Container)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_cases (
            id TEXT PRIMARY KEY,
            surgery_case_id TEXT,
            patient_id TEXT NOT NULL,
            patient_name TEXT,

            context_mode TEXT NOT NULL DEFAULT 'STANDARD',

            primary_anesthesiologist_id TEXT,
            primary_nurse_id TEXT,

            planned_technique TEXT,

            oxygen_source_type TEXT,
            oxygen_source_id TEXT,

            preop_completed_at DATETIME,
            anesthesia_start_at DATETIME,
            surgery_start_at DATETIME,
            surgery_end_at DATETIME,
            anesthesia_end_at DATETIME,
            pacu_admission_at DATETIME,
            pacu_discharge_at DATETIME,

            status TEXT NOT NULL DEFAULT 'PREOP',

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            CHECK(context_mode IN ('STANDARD', 'BATTLEFIELD')),
            CHECK(status IN ('PREOP', 'IN_PROGRESS', 'PACU', 'CLOSED'))
        )
    """)

    # Anesthesia Events (Append-Only)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_events (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,

            event_type TEXT NOT NULL,

            clinical_time DATETIME NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            payload TEXT NOT NULL,

            actor_id TEXT NOT NULL,
            device_id TEXT,

            idempotency_key TEXT UNIQUE,

            is_correction INTEGER DEFAULT 0,
            corrects_event_id TEXT,
            correction_reason TEXT,

            sync_status TEXT DEFAULT 'LOCAL',

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            FOREIGN KEY (corrects_event_id) REFERENCES anesthesia_events(id),
            CHECK(is_correction IN (0, 1)),
            CHECK(sync_status IN ('LOCAL', 'SYNCED', 'CONFLICT'))
        )
    """)

    # PreOp Assessments
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS preop_assessments (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL UNIQUE,

            mode TEXT NOT NULL DEFAULT 'STANDARD',

            asa_class INTEGER,
            asa_emergency INTEGER DEFAULT 0,

            npo_hours REAL,
            last_oral_intake DATETIME,
            npo_status TEXT,

            allergies TEXT,
            allergy_verified INTEGER DEFAULT 0,

            mallampati_score INTEGER,
            thyromental_distance TEXT,
            neck_mobility TEXT,
            mouth_opening TEXT,
            teeth_status TEXT,
            difficult_airway_history INTEGER DEFAULT 0,
            difficult_airway_anticipated INTEGER DEFAULT 0,

            comorbidities TEXT,
            current_medications TEXT,
            cardiac_risk_index INTEGER,

            quick_flags TEXT,

            planned_technique TEXT,
            backup_plan TEXT,
            special_considerations TEXT,

            assessed_by TEXT NOT NULL,
            assessment_datetime DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'PENDING',
            approved_by TEXT,
            approved_at DATETIME,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(mode IN ('STANDARD', 'BATTLEFIELD')),
            CHECK(asa_class IS NULL OR asa_class BETWEEN 1 AND 6),
            CHECK(mallampati_score IS NULL OR mallampati_score BETWEEN 1 AND 4),
            CHECK(status IN ('PENDING', 'APPROVED', 'NEEDS_REVIEW'))
        )
    """)

    # Indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_events_timeline
        ON anesthesia_events(case_id, clinical_time)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_events_type
        ON anesthesia_events(case_id, event_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_events_sync
        ON anesthesia_events(sync_status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_cases_status
        ON anesthesia_cases(status, created_at DESC)
    """)

    # Add O2 claim columns to equipment_units if not exist
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_case_id TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_at DATETIME")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_user_id TEXT")
    except:
        pass

    # Phase C: Add patient snapshot columns for Hub-Satellite sync
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN patient_snapshot TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN cirs_registration_ref TEXT")
    except:
        pass

    # Phase A-6: WAL Sync Queue for offline-first operations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_sync_queue (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            payload TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            last_error TEXT,
            status TEXT DEFAULT 'PENDING',
            synced_at DATETIME,
            CHECK(status IN ('PENDING', 'SYNCING', 'SYNCED', 'FAILED'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_queue_status
        ON anesthesia_sync_queue(status, created_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_queue_device
        ON anesthesia_sync_queue(device_id, status)
    """)

    # =========================================================================
    # Phase B: Controlled Drugs Schema
    # =========================================================================

    # Drug Requests (申請單)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drug_requests (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,

            requester_id TEXT NOT NULL,
            requester_role TEXT NOT NULL,

            items TEXT NOT NULL,

            approver_id TEXT,
            approved_at DATETIME,

            status TEXT NOT NULL DEFAULT 'PENDING',

            offline_proof_artifact_id TEXT,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(status IN ('PENDING', 'APPROVED', 'DISPENSED', 'RECONCILED', 'REJECTED'))
        )
    """)

    # Drug Transactions (交易流水帳 - The Ledger)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drug_transactions (
            id TEXT PRIMARY KEY,
            request_id TEXT,
            case_id TEXT NOT NULL,

            drug_code TEXT NOT NULL,
            drug_name TEXT NOT NULL,
            schedule_class INTEGER NOT NULL DEFAULT 4,
            batch_number TEXT,

            tx_type TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL,

            actor_id TEXT NOT NULL,
            witness_id TEXT,
            witness_verified_at DATETIME,

            idempotency_key TEXT UNIQUE,
            device_id TEXT,
            local_seq INTEGER,

            tx_time DATETIME NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            sync_status TEXT DEFAULT 'LOCAL',
            notes TEXT,

            FOREIGN KEY (request_id) REFERENCES drug_requests(id),
            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(tx_type IN ('DISPENSE', 'ADMIN', 'WASTE', 'RETURN')),
            CHECK(quantity > 0),
            CHECK(sync_status IN ('LOCAL', 'SYNCED', 'CONFLICT'))
        )
    """)

    # Indexes for drug tables
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_drug_requests_case
        ON drug_requests(case_id, status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_drug_tx_case
        ON drug_transactions(case_id, drug_code)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_drug_tx_request
        ON drug_transactions(request_id)
    """)

    logger.info("✓ Anesthesia schema initialized (Phase A + B)")


# =============================================================================
# Helper Functions
# =============================================================================

def generate_case_id() -> str:
    """Generate unique case ID: ANES-YYYYMMDD-XXX"""
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"ANES-{date_str}-{short_uuid}"


def generate_event_id() -> str:
    """Generate unique event ID"""
    return str(uuid.uuid4())


def generate_preop_id() -> str:
    """Generate unique preop ID"""
    return f"PREOP-{uuid.uuid4().hex[:8].upper()}"


# =============================================================================
# API Routes - Cases
# =============================================================================

def get_db_connection():
    """Get database connection - to be injected from main"""
    # This will be set by main.py
    from main import db
    return db.get_connection()


@router.post("/cases", response_model=CaseResponse)
async def create_case(request: CreateCaseRequest, actor_id: str = Query(...)):
    """Create a new anesthesia case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    case_id = generate_case_id()

    # Serialize patient snapshot if provided
    patient_snapshot_json = None
    if request.patient_snapshot:
        patient_snapshot_json = json.dumps(request.patient_snapshot.model_dump())

    try:
        cursor.execute("""
            INSERT INTO anesthesia_cases (
                id, surgery_case_id, patient_id, patient_name,
                context_mode, planned_technique,
                primary_anesthesiologist_id, primary_nurse_id,
                cirs_registration_ref, patient_snapshot,
                created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            request.surgery_case_id,
            request.patient_id,
            request.patient_name,
            request.context_mode.value,
            request.planned_technique.value if request.planned_technique else None,
            request.primary_anesthesiologist_id,
            request.primary_nurse_id,
            request.cirs_registration_ref,
            patient_snapshot_json,
            actor_id
        ))

        # Add STATUS_CHANGE event
        event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, ?, datetime('now'), ?, ?)
        """, (
            event_id, case_id, 'STATUS_CHANGE',
            json.dumps({"from": None, "to": "PREOP", "reason": "Case created"}),
            actor_id
        ))

        conn.commit()

        # Fetch and return
        cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
        row = cursor.fetchone()

        return CaseResponse(
            id=row['id'],
            surgery_case_id=row['surgery_case_id'],
            patient_id=row['patient_id'],
            patient_name=row['patient_name'],
            context_mode=row['context_mode'],
            planned_technique=row['planned_technique'],
            primary_anesthesiologist_id=row['primary_anesthesiologist_id'],
            primary_nurse_id=row['primary_nurse_id'],
            oxygen_source_type=row['oxygen_source_type'],
            oxygen_source_id=row['oxygen_source_id'],
            status=row['status'],
            preop_completed_at=row['preop_completed_at'],
            anesthesia_start_at=row['anesthesia_start_at'],
            surgery_start_at=row['surgery_start_at'],
            surgery_end_at=row['surgery_end_at'],
            anesthesia_end_at=row['anesthesia_end_at'],
            created_at=row['created_at'],
            created_by=row['created_by']
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create case: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases")
async def list_cases(
    status: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = Query(default=50, le=200)
):
    """List anesthesia cases"""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM anesthesia_cases WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if date:
        query += " AND date(created_at) = ?"
        params.append(date)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return {
        "cases": [dict(row) for row in rows],
        "count": len(rows)
    }


@router.get("/cases/{case_id}")
async def get_case(case_id: str):
    """Get case details"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    return dict(row)


@router.patch("/cases/{case_id}")
async def update_case_metadata(
    case_id: str,
    primary_anesthesiologist_id: Optional[str] = None,
    primary_nurse_id: Optional[str] = None,
    planned_technique: Optional[str] = None,
    actor_id: str = Query(...)
):
    """Update case metadata (non-event fields only)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if primary_anesthesiologist_id is not None:
        updates.append("primary_anesthesiologist_id = ?")
        params.append(primary_anesthesiologist_id)

    if primary_nurse_id is not None:
        updates.append("primary_nurse_id = ?")
        params.append(primary_nurse_id)

    if planned_technique is not None:
        updates.append("planned_technique = ?")
        params.append(planned_technique)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(case_id)

    try:
        cursor.execute(f"""
            UPDATE anesthesia_cases SET {', '.join(updates)} WHERE id = ?
        """, params)
        conn.commit()

        cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
        return dict(cursor.fetchone())

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# API Routes - Events (Append-Only)
# =============================================================================

@router.post("/cases/{case_id}/events")
async def add_event(case_id: str, request: AddEventRequest, actor_id: str = Query(...)):
    """Add event to case timeline (append-only)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot add events to closed case")

    event_id = generate_event_id()
    clinical_time = request.clinical_time or datetime.now()
    idempotency_key = request.idempotency_key or f"{case_id}:{actor_id}:{event_id[:8]}"

    try:
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload,
                actor_id, device_id, idempotency_key,
                is_correction, corrects_event_id, correction_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            case_id,
            request.event_type.value,
            clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time,
            json.dumps(request.payload),
            actor_id,
            request.device_id,
            idempotency_key,
            1 if request.is_correction else 0,
            request.corrects_event_id,
            request.correction_reason
        ))

        # Handle milestone events that update case timestamps
        if request.event_type == EventType.MILESTONE:
            milestone_type = request.payload.get('type')
            timestamp_field = {
                'ANESTHESIA_START': 'anesthesia_start_at',
                'SURGERY_START': 'surgery_start_at',
                'SURGERY_END': 'surgery_end_at',
                'ANESTHESIA_END': 'anesthesia_end_at'
            }.get(milestone_type)

            if timestamp_field:
                cursor.execute(f"""
                    UPDATE anesthesia_cases
                    SET {timestamp_field} = ?, updated_at = datetime('now')
                    WHERE id = ?
                """, (clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time, case_id))

            # Update status based on milestone
            if milestone_type == 'ANESTHESIA_START':
                cursor.execute("""
                    UPDATE anesthesia_cases SET status = 'IN_PROGRESS', updated_at = datetime('now')
                    WHERE id = ?
                """, (case_id,))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "clinical_time": clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time
        }

    except Exception as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            # Idempotency: return existing event
            cursor.execute("""
                SELECT id FROM anesthesia_events WHERE idempotency_key = ?
            """, (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                return {"success": True, "event_id": existing['id'], "duplicate": True}
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/events")
async def get_events(
    case_id: str,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = Query(default=500, le=2000)
):
    """Get all events for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM anesthesia_events WHERE case_id = ?"
    params = [case_id]

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)

    if since:
        query += " AND clinical_time > ?"
        params.append(since)

    query += " ORDER BY clinical_time ASC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    events = []
    for row in rows:
        event = dict(row)
        event['payload'] = json.loads(event['payload']) if event['payload'] else {}
        events.append(event)

    return {"events": events, "count": len(events)}


@router.get("/cases/{case_id}/timeline")
async def get_timeline(case_id: str):
    """Get reconstructed timeline (grouped by type)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM anesthesia_events
        WHERE case_id = ? AND is_correction = 0
        ORDER BY clinical_time ASC
    """, (case_id,))

    events = [dict(row) for row in cursor.fetchall()]

    # Parse payloads
    for event in events:
        event['payload'] = json.loads(event['payload']) if event['payload'] else {}

    # Group by type
    timeline = {
        'vitals': [e for e in events if e['event_type'] == 'VITAL_SIGN'],
        'medications': [e for e in events if e['event_type'] == 'MEDICATION_ADMIN'],
        'fluids': [e for e in events if e['event_type'] in ('FLUID_IN', 'FLUID_OUT', 'BLOOD_PRODUCT')],
        'airway': [e for e in events if e['event_type'] == 'AIRWAY_EVENT'],
        'milestones': [e for e in events if e['event_type'] == 'MILESTONE'],
        'notes': [e for e in events if e['event_type'] == 'NOTE'],
        'all': events
    }

    return timeline


# =============================================================================
# API Routes - Quick Entry (One-Tap)
# =============================================================================

@router.post("/cases/{case_id}/vitals")
async def add_vital_sign(case_id: str, request: QuickVitalRequest, actor_id: str = Query(...)):
    """Quick vital sign entry (one-tap)"""
    payload = {k: v for k, v in request.dict().items() if v is not None and k != 'device_id'}

    event_request = AddEventRequest(
        event_type=EventType.VITAL_SIGN,
        payload=payload,
        device_id=request.device_id
    )

    return await add_event(case_id, event_request, actor_id)


@router.post("/cases/{case_id}/medication")
async def add_medication(case_id: str, request: QuickMedicationRequest, actor_id: str = Query(...)):
    """Quick medication entry"""
    payload = {
        "drug_code": request.drug_code,
        "drug_name": request.drug_name,
        "dose": request.dose,
        "unit": request.unit,
        "route": request.route
    }

    event_request = AddEventRequest(
        event_type=EventType.MEDICATION_ADMIN,
        payload=payload,
        device_id=request.device_id
    )

    return await add_event(case_id, event_request, actor_id)


@router.post("/cases/{case_id}/milestone")
async def add_milestone(
    case_id: str,
    milestone_type: str = Query(..., regex="^(ANESTHESIA_START|SURGERY_START|SURGERY_END|ANESTHESIA_END)$"),
    actor_id: str = Query(...)
):
    """Add milestone event"""
    event_request = AddEventRequest(
        event_type=EventType.MILESTONE,
        payload={"type": milestone_type}
    )

    return await add_event(case_id, event_request, actor_id)


# =============================================================================
# API Routes - PreOp
# =============================================================================

@router.post("/cases/{case_id}/preop")
async def create_preop(case_id: str, request: CreatePreopRequest, actor_id: str = Query(...)):
    """Create pre-op assessment"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if already exists
    cursor.execute("SELECT id FROM preop_assessments WHERE case_id = ?", (case_id,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="PreOp assessment already exists")

    preop_id = generate_preop_id()

    try:
        cursor.execute("""
            INSERT INTO preop_assessments (
                id, case_id, mode,
                asa_class, asa_emergency,
                npo_hours, npo_status,
                allergies, mallampati_score,
                difficult_airway_anticipated,
                comorbidities, quick_flags,
                planned_technique, special_considerations,
                assessed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            preop_id,
            case_id,
            request.mode.value,
            request.asa_class,
            1 if request.asa_emergency else 0,
            request.npo_hours,
            request.npo_status,
            json.dumps(request.allergies) if request.allergies else None,
            request.mallampati_score,
            1 if request.difficult_airway_anticipated else 0,
            json.dumps(request.comorbidities) if request.comorbidities else None,
            json.dumps(request.quick_flags.dict()) if request.quick_flags else None,
            request.planned_technique,
            request.special_considerations,
            actor_id
        ))

        conn.commit()

        cursor.execute("SELECT * FROM preop_assessments WHERE id = ?", (preop_id,))
        row = cursor.fetchone()
        result = dict(row)
        result['allergies'] = json.loads(result['allergies']) if result['allergies'] else []
        result['quick_flags'] = json.loads(result['quick_flags']) if result['quick_flags'] else None

        return result

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/preop")
async def get_preop(case_id: str):
    """Get pre-op assessment"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM preop_assessments WHERE case_id = ?", (case_id,))
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="PreOp assessment not found")

    result = dict(row)
    result['allergies'] = json.loads(result['allergies']) if result['allergies'] else []
    result['comorbidities'] = json.loads(result['comorbidities']) if result['comorbidities'] else []
    result['quick_flags'] = json.loads(result['quick_flags']) if result['quick_flags'] else None

    return result


@router.post("/cases/{case_id}/preop/approve")
async def approve_preop(case_id: str, actor_id: str = Query(...)):
    """Approve pre-op assessment"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE preop_assessments
            SET status = 'APPROVED', approved_by = ?, approved_at = datetime('now')
            WHERE case_id = ?
        """, (actor_id, case_id))

        cursor.execute("""
            UPDATE anesthesia_cases
            SET preop_completed_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        conn.commit()

        return {"success": True, "approved_by": actor_id}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase A-5: Battlefield Preop (Quick 5 Flags)
# =============================================================================

class BattlefieldPreopRequest(BaseModel):
    """Battlefield mode quick preop assessment"""
    is_allergic: bool = False
    is_full_stomach: bool = False
    is_difficult_airway: bool = False
    is_hemodynamically_unstable: bool = False
    is_high_risk: bool = False
    quick_note: Optional[str] = None


@router.post("/cases/{case_id}/battlefield-preop")
async def save_battlefield_preop(
    case_id: str,
    request: BattlefieldPreopRequest,
    actor_id: str = Query(...)
):
    """Save battlefield mode quick preop assessment (5 flags)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        # Check if preop_assessments record exists
        cursor.execute("SELECT id FROM preop_assessments WHERE case_id = ?", (case_id,))
        existing = cursor.fetchone()

        quick_flags = {
            "is_allergic": request.is_allergic,
            "is_full_stomach": request.is_full_stomach,
            "is_difficult_airway": request.is_difficult_airway,
            "is_hemodynamically_unstable": request.is_hemodynamically_unstable,
            "is_high_risk": request.is_high_risk,
            "quick_note": request.quick_note
        }

        if existing:
            cursor.execute("""
                UPDATE preop_assessments
                SET quick_flags = ?, assessment_datetime = datetime('now')
                WHERE case_id = ?
            """, (json.dumps(quick_flags), case_id))
        else:
            preop_id = generate_event_id()
            cursor.execute("""
                INSERT INTO preop_assessments (
                    id, case_id, quick_flags, mode, assessed_by, assessment_datetime
                ) VALUES (?, ?, ?, 'BATTLEFIELD', ?, datetime('now'))
            """, (preop_id, case_id, json.dumps(quick_flags), actor_id))

        conn.commit()

        return {
            "success": True,
            "quick_flags": quick_flags
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/battlefield-preop")
async def get_battlefield_preop(case_id: str):
    """Get battlefield preop quick flags"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT quick_flags FROM preop_assessments WHERE case_id = ?", (case_id,))
    row = cursor.fetchone()

    if not row or not row['quick_flags']:
        return {"battlefield_preop": None}

    return {
        "battlefield_preop": json.loads(row['quick_flags'])
    }


# =============================================================================
# API Routes - Oxygen Cylinder Claim
# =============================================================================

@router.post("/cases/{case_id}/claim-oxygen")
async def claim_oxygen_cylinder(case_id: str, request: ClaimOxygenRequest, actor_id: str = Query(...)):
    """Claim an oxygen cylinder for this case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check cylinder is available
    cursor.execute("""
        SELECT id, unit_serial, claimed_by_case_id, level_percent
        FROM equipment_units
        WHERE id = ? AND (is_active = 1 OR is_active IS NULL)
    """, (request.cylinder_unit_id,))

    unit = cursor.fetchone()
    if not unit:
        raise HTTPException(status_code=404, detail="Cylinder not found")

    if unit['claimed_by_case_id']:
        raise HTTPException(
            status_code=400,
            detail=f"此氧氣瓶已被 {unit['claimed_by_case_id']} 使用中"
        )

    try:
        # Claim the cylinder
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_case_id = ?, claimed_at = datetime('now'), claimed_by_user_id = ?
            WHERE id = ?
        """, (case_id, actor_id, request.cylinder_unit_id))

        # Update case
        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = 'CYLINDER', oxygen_source_id = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (str(request.cylinder_unit_id), case_id))

        # Add resource check event
        event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_CHECK', datetime('now'), ?, ?)
        """, (
            event_id, case_id,
            json.dumps({
                "resource": "O2_CYLINDER",
                "cylinder_id": unit['unit_serial'],
                "unit_id": request.cylinder_unit_id,
                "level_percent": unit['level_percent'],
                "pressure_psi": request.initial_pressure_psi,
                "action": "CLAIM"
            }),
            actor_id
        ))

        conn.commit()

        return {
            "success": True,
            "cylinder_serial": unit['unit_serial'],
            "level_percent": unit['level_percent']
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cases/{case_id}/claim-oxygen")
async def release_oxygen_cylinder(case_id: str, actor_id: str = Query(...)):
    """Release claimed oxygen cylinder"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT oxygen_source_id FROM anesthesia_cases WHERE id = ?
    """, (case_id,))
    case = cursor.fetchone()

    if not case or not case['oxygen_source_id']:
        raise HTTPException(status_code=400, detail="No cylinder claimed")

    try:
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_case_id = NULL, claimed_at = NULL, claimed_by_user_id = NULL
            WHERE id = ?
        """, (int(case['oxygen_source_id']),))

        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = NULL, oxygen_source_id = NULL, updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        conn.commit()

        return {"success": True}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/oxygen-status")
async def get_oxygen_status(case_id: str):
    """Get current oxygen status and estimate"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT oxygen_source_type, oxygen_source_id FROM anesthesia_cases WHERE id = ?
    """, (case_id,))
    case = cursor.fetchone()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['oxygen_source_type'] != 'CYLINDER' or not case['oxygen_source_id']:
        return {
            "source_type": case['oxygen_source_type'] or "NONE",
            "cylinder_id": None,
            "est_minutes_remaining": None
        }

    # Get cylinder info
    cursor.execute("""
        SELECT u.unit_serial, u.level_percent, et.capacity_config
        FROM equipment_units u
        JOIN equipment e ON u.equipment_id = e.id
        LEFT JOIN equipment_types et ON e.type_code = et.type_code
        WHERE u.id = ?
    """, (int(case['oxygen_source_id']),))

    cylinder = cursor.fetchone()
    if not cylinder:
        return {"source_type": "CYLINDER", "error": "Cylinder not found"}

    # Get latest flow rate from vitals
    cursor.execute("""
        SELECT payload FROM anesthesia_events
        WHERE case_id = ? AND event_type = 'VITAL_SIGN'
        ORDER BY clinical_time DESC LIMIT 10
    """, (case_id,))

    vitals = cursor.fetchall()
    flow_rates = []
    for v in vitals:
        payload = json.loads(v['payload'])
        if payload.get('o2_flow_lpm'):
            flow_rates.append(payload['o2_flow_lpm'])

    avg_flow = sum(flow_rates) / len(flow_rates) if flow_rates else 2.0  # Default 2 L/min

    # Calculate estimate
    capacity_config = json.loads(cylinder['capacity_config']) if cylinder['capacity_config'] else {}
    hours_per_100 = capacity_config.get('hours_per_100pct', 8)  # Default 8 hours
    current_hours = (cylinder['level_percent'] / 100) * hours_per_100
    est_minutes = int(current_hours * 60)

    # Adjust for flow rate if we have it
    if avg_flow > 0:
        # Assuming default is 2 L/min
        adjustment = 2.0 / avg_flow
        est_minutes = int(est_minutes * adjustment)

    return {
        "source_type": "CYLINDER",
        "cylinder_serial": cylinder['unit_serial'],
        "level_percent": cylinder['level_percent'],
        "avg_flow_lpm": round(avg_flow, 1),
        "est_minutes_remaining": est_minutes,
        "est_hours_remaining": round(est_minutes / 60, 1)
    }


# =============================================================================
# API Routes - Case Close
# =============================================================================

@router.post("/cases/{case_id}/close")
async def close_case(case_id: str, actor_id: str = Query(...)):
    """Close anesthesia case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status, oxygen_source_id FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Case already closed")

    try:
        # Release oxygen cylinder if claimed
        if case['oxygen_source_id']:
            cursor.execute("""
                UPDATE equipment_units
                SET claimed_by_case_id = NULL, claimed_at = NULL, claimed_by_user_id = NULL
                WHERE id = ?
            """, (int(case['oxygen_source_id']),))

        # Update case status
        cursor.execute("""
            UPDATE anesthesia_cases
            SET status = 'CLOSED', oxygen_source_type = NULL, oxygen_source_id = NULL,
                updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        # Add status change event
        event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'STATUS_CHANGE', datetime('now'), ?, ?)
        """, (
            event_id, case_id,
            json.dumps({"from": case['status'], "to": "CLOSED"}),
            actor_id
        ))

        conn.commit()

        return {"success": True, "status": "CLOSED"}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase A-4: Quick Actions (One-Tap Medications & Vitals)
# =============================================================================

QUICK_DRUGS = [
    {"code": "PROP", "name": "Propofol", "default_dose": 100, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "FENT", "name": "Fentanyl", "default_dose": 100, "unit": "mcg", "route": "IV", "is_controlled": True},
    {"code": "ROCU", "name": "Rocuronium", "default_dose": 50, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "SUXI", "name": "Succinylcholine", "default_dose": 100, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "MIDA", "name": "Midazolam", "default_dose": 2, "unit": "mg", "route": "IV", "is_controlled": True},
    {"code": "ATRO", "name": "Atropine", "default_dose": 0.5, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "EPHE", "name": "Ephedrine", "default_dose": 10, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "PHEN", "name": "Phenylephrine", "default_dose": 100, "unit": "mcg", "route": "IV", "is_controlled": False},
    {"code": "STER", "name": "Sugammadex", "default_dose": 200, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "NEOS", "name": "Neostigmine", "default_dose": 2.5, "unit": "mg", "route": "IV", "is_controlled": False},
]


@router.get("/quick-drugs")
async def get_quick_drugs():
    """Get list of quick drugs for one-tap administration"""
    return {"drugs": QUICK_DRUGS}


@router.post("/cases/{case_id}/quick-drug/{drug_code}")
async def quick_drug_admin(
    case_id: str,
    drug_code: str,
    dose: Optional[float] = Query(None, description="Custom dose (uses default if not provided)"),
    actor_id: str = Query(..., description="User ID administering the drug")
):
    """Quick one-tap drug administration"""
    drug = next((d for d in QUICK_DRUGS if d["code"] == drug_code), None)
    if not drug:
        raise HTTPException(status_code=404, detail=f"Drug code '{drug_code}' not in quick list")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    actual_dose = dose if dose is not None else drug["default_dose"]
    event_id = generate_event_id()

    payload = {
        "drug_code": drug["code"],
        "drug_name": drug["name"],
        "dose": actual_dose,
        "unit": drug["unit"],
        "route": drug["route"],
        "is_controlled": drug["is_controlled"],
        "quick_admin": True
    }

    try:
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'MEDICATION_ADMIN', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(payload), actor_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "drug": drug["name"],
            "dose": actual_dose,
            "unit": drug["unit"]
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# Quick vital signs templates
QUICK_VITALS_TEMPLATES = [
    {"name": "正常", "hr": 75, "sbp": 120, "dbp": 80, "spo2": 99, "rr": 14},
    {"name": "誘導中", "hr": 85, "sbp": 100, "dbp": 60, "spo2": 100, "rr": 0},
    {"name": "維持期", "hr": 70, "sbp": 110, "dbp": 70, "spo2": 100, "rr": 12},
    {"name": "甦醒", "hr": 80, "sbp": 130, "dbp": 85, "spo2": 98, "rr": 16},
]


@router.get("/quick-vitals-templates")
async def get_quick_vitals_templates():
    """Get predefined vital sign templates for quick entry"""
    return {"templates": QUICK_VITALS_TEMPLATES}


@router.post("/cases/{case_id}/quick-vitals")
async def quick_vitals(
    case_id: str,
    template: Optional[str] = Query(None, description="Template name (正常/誘導中/維持期/甦醒)"),
    hr: Optional[int] = Query(None, ge=0, le=300),
    sbp: Optional[int] = Query(None, ge=0, le=300),
    dbp: Optional[int] = Query(None, ge=0, le=200),
    spo2: Optional[int] = Query(None, ge=0, le=100),
    rr: Optional[int] = Query(None, ge=0, le=60),
    actor_id: str = Query(...)
):
    """Quick vital signs entry (supports templates or individual values)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    # Use template or provided values
    vitals = {}
    if template:
        tpl = next((t for t in QUICK_VITALS_TEMPLATES if t["name"] == template), None)
        if tpl:
            vitals = {k: v for k, v in tpl.items() if k != "name"}

    # Override with any provided values
    if hr is not None: vitals["hr"] = hr
    if sbp is not None: vitals["sbp"] = sbp
    if dbp is not None: vitals["dbp"] = dbp
    if spo2 is not None: vitals["spo2"] = spo2
    if rr is not None: vitals["rr"] = rr

    if not vitals:
        raise HTTPException(status_code=400, detail="No vital signs provided")

    event_id = generate_event_id()

    try:
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'VITAL_SIGN', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(vitals), actor_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "vitals": vitals
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase A-6: WAL Sync API (Offline-First)
# =============================================================================

class SyncQueueItem(BaseModel):
    """Item to be synced from offline queue"""
    id: str
    device_id: str
    operation: str  # POST, PUT, DELETE
    endpoint: str   # e.g., /cases/{id}/events
    payload: Dict[str, Any]
    idempotency_key: str
    created_at: str


class SyncBatchRequest(BaseModel):
    """Batch sync request from offline client"""
    device_id: str
    items: List[SyncQueueItem]


class SyncStatusResponse(BaseModel):
    """Sync status for a device"""
    device_id: str
    pending_count: int
    last_sync: Optional[str]
    failed_items: List[str]


@router.post("/sync/batch")
async def sync_batch(request: SyncBatchRequest):
    """
    Process a batch of offline operations.
    Uses idempotency keys to prevent duplicates.
    Returns results for each item.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    results = []

    for item in request.items:
        try:
            # Check if already processed (idempotency)
            cursor.execute("""
                SELECT id, status FROM anesthesia_sync_queue
                WHERE idempotency_key = ?
            """, (item.idempotency_key,))
            existing = cursor.fetchone()

            if existing and existing['status'] == 'SYNCED':
                results.append({
                    "id": item.id,
                    "status": "duplicate",
                    "message": "Already synced"
                })
                continue

            # Record in sync queue
            if not existing:
                cursor.execute("""
                    INSERT INTO anesthesia_sync_queue (
                        id, device_id, operation, endpoint, payload,
                        idempotency_key, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'SYNCING')
                """, (
                    item.id, item.device_id, item.operation,
                    item.endpoint, json.dumps(item.payload),
                    item.idempotency_key
                ))
            else:
                cursor.execute("""
                    UPDATE anesthesia_sync_queue
                    SET status = 'SYNCING', retry_count = retry_count + 1
                    WHERE id = ?
                """, (existing['id'],))

            # Process the operation based on endpoint pattern
            success = False
            error_msg = None

            try:
                # Parse endpoint to determine action
                endpoint = item.endpoint
                payload = item.payload

                if endpoint.startswith("/cases/") and "/events" in endpoint:
                    # Event creation
                    case_id = endpoint.split("/")[2]
                    event_id = generate_event_id()
                    cursor.execute("""
                        INSERT INTO anesthesia_events (
                            id, case_id, event_type, clinical_time, payload,
                            actor_id, device_id, idempotency_key, sync_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SYNCED')
                    """, (
                        event_id, case_id, payload.get('event_type'),
                        payload.get('clinical_time', datetime.now().isoformat()),
                        json.dumps(payload.get('payload', {})),
                        payload.get('actor_id'), item.device_id,
                        item.idempotency_key
                    ))
                    success = True

                elif endpoint.startswith("/cases") and item.operation == "POST":
                    # Case creation - handled by main API
                    success = True

                else:
                    error_msg = f"Unknown endpoint: {endpoint}"

            except Exception as e:
                error_msg = str(e)

            # Update sync queue status
            if success:
                cursor.execute("""
                    UPDATE anesthesia_sync_queue
                    SET status = 'SYNCED', synced_at = datetime('now')
                    WHERE idempotency_key = ?
                """, (item.idempotency_key,))
                results.append({
                    "id": item.id,
                    "status": "synced",
                    "message": "OK"
                })
            else:
                cursor.execute("""
                    UPDATE anesthesia_sync_queue
                    SET status = 'FAILED', last_error = ?
                    WHERE idempotency_key = ?
                """, (error_msg, item.idempotency_key))
                results.append({
                    "id": item.id,
                    "status": "failed",
                    "message": error_msg
                })

        except Exception as e:
            results.append({
                "id": item.id,
                "status": "error",
                "message": str(e)
            })

    conn.commit()

    return {
        "processed": len(results),
        "results": results
    }


@router.get("/sync/status")
async def get_sync_status(device_id: str = Query(...)):
    """Get sync status for a specific device"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get pending count
    cursor.execute("""
        SELECT COUNT(*) as count FROM anesthesia_sync_queue
        WHERE device_id = ? AND status = 'PENDING'
    """, (device_id,))
    pending = cursor.fetchone()['count']

    # Get last sync time
    cursor.execute("""
        SELECT MAX(synced_at) as last_sync FROM anesthesia_sync_queue
        WHERE device_id = ? AND status = 'SYNCED'
    """, (device_id,))
    last_sync = cursor.fetchone()['last_sync']

    # Get failed items
    cursor.execute("""
        SELECT id FROM anesthesia_sync_queue
        WHERE device_id = ? AND status = 'FAILED'
        ORDER BY created_at DESC
        LIMIT 10
    """, (device_id,))
    failed = [row['id'] for row in cursor.fetchall()]

    return {
        "device_id": device_id,
        "pending_count": pending,
        "last_sync": last_sync,
        "failed_items": failed
    }


@router.get("/sync/pending")
async def get_pending_events(
    case_id: str = Query(...),
    since: Optional[str] = Query(None, description="ISO timestamp to get events after")
):
    """
    Get events that need to be synced to a device.
    Used for pulling updates from server to offline client.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if since:
        cursor.execute("""
            SELECT id, event_type, clinical_time, payload, actor_id,
                   recorded_at, idempotency_key
            FROM anesthesia_events
            WHERE case_id = ? AND recorded_at > ?
            ORDER BY clinical_time ASC
        """, (case_id, since))
    else:
        cursor.execute("""
            SELECT id, event_type, clinical_time, payload, actor_id,
                   recorded_at, idempotency_key
            FROM anesthesia_events
            WHERE case_id = ?
            ORDER BY clinical_time ASC
        """, (case_id,))

    events = []
    for row in cursor.fetchall():
        events.append({
            "id": row['id'],
            "event_type": row['event_type'],
            "clinical_time": row['clinical_time'],
            "payload": json.loads(row['payload']) if row['payload'] else {},
            "actor_id": row['actor_id'],
            "recorded_at": row['recorded_at'],
            "idempotency_key": row['idempotency_key']
        })

    return {
        "case_id": case_id,
        "events": events,
        "count": len(events),
        "server_time": datetime.now().isoformat()
    }


@router.delete("/sync/queue/{item_id}")
async def remove_from_queue(item_id: str):
    """Remove a synced or failed item from the queue"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM anesthesia_sync_queue
        WHERE id = ? AND status IN ('SYNCED', 'FAILED')
    """, (item_id,))

    conn.commit()

    return {"deleted": cursor.rowcount > 0}


# =============================================================================
# Phase B: Controlled Drugs API
# =============================================================================

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class DrugRequestItem(BaseModel):
    drug_code: str
    drug_name: str
    quantity: float
    unit: str
    schedule_class: int = 4  # 管制藥品級別 (1-4)


class CreateDrugRequestRequest(BaseModel):
    items: List[DrugRequestItem]


class DrugTransactionRequest(BaseModel):
    drug_code: str
    drug_name: str
    quantity: float
    unit: str
    tx_type: DrugTxType
    schedule_class: int = 4
    batch_number: Optional[str] = None
    witness_id: Optional[str] = None  # Required for WASTE
    notes: Optional[str] = None
    request_id: Optional[str] = None
    device_id: Optional[str] = None
    idempotency_key: Optional[str] = None


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def generate_request_id() -> str:
    """Generate unique drug request ID"""
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:4].upper()
    return f"REQ-{date_str}-{short_uuid}"


def generate_tx_id() -> str:
    """Generate unique transaction ID"""
    return f"TX-{uuid.uuid4().hex[:12].upper()}"


def calculate_drug_holdings(cursor, case_id: str) -> List[Dict]:
    """
    Calculate current drug holdings for a case.
    Balance = DISPENSE - (ADMIN + WASTE + RETURN)
    """
    cursor.execute("""
        SELECT
            drug_code,
            drug_name,
            unit,
            schedule_class,
            SUM(CASE WHEN tx_type = 'DISPENSE' THEN quantity ELSE 0 END) as dispensed,
            SUM(CASE WHEN tx_type = 'ADMIN' THEN quantity ELSE 0 END) as administered,
            SUM(CASE WHEN tx_type = 'WASTE' THEN quantity ELSE 0 END) as wasted,
            SUM(CASE WHEN tx_type = 'RETURN' THEN quantity ELSE 0 END) as returned
        FROM drug_transactions
        WHERE case_id = ?
        GROUP BY drug_code, drug_name, unit
    """, (case_id,))

    holdings = []
    for row in cursor.fetchall():
        dispensed = row['dispensed'] or 0
        administered = row['administered'] or 0
        wasted = row['wasted'] or 0
        returned = row['returned'] or 0
        balance = dispensed - administered - wasted - returned

        holdings.append({
            "drug_code": row['drug_code'],
            "drug_name": row['drug_name'],
            "unit": row['unit'],
            "schedule_class": row['schedule_class'],
            "dispensed": dispensed,
            "administered": administered,
            "wasted": wasted,
            "returned": returned,
            "balance": round(balance, 2)
        })

    return holdings


def get_total_balance(cursor, case_id: str) -> float:
    """Get total drug balance for a case (for validation)"""
    holdings = calculate_drug_holdings(cursor, case_id)
    return sum(h['balance'] for h in holdings)


# -----------------------------------------------------------------------------
# Drug Request API
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/drugs/request")
async def create_drug_request(
    case_id: str,
    request: CreateDrugRequestRequest,
    actor_id: str = Query(...),
    actor_role: str = Query("ANES_NA")
):
    """Create a new controlled drug request for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot request drugs for closed case")

    request_id = generate_request_id()

    try:
        cursor.execute("""
            INSERT INTO drug_requests (
                id, case_id, requester_id, requester_role, items, status
            ) VALUES (?, ?, ?, ?, ?, 'PENDING')
        """, (
            request_id,
            case_id,
            actor_id,
            actor_role,
            json.dumps([item.dict() for item in request.items])
        ))

        conn.commit()

        return {
            "request_id": request_id,
            "case_id": case_id,
            "status": "PENDING",
            "items": [item.dict() for item in request.items]
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/drugs/requests")
async def list_drug_requests(case_id: str):
    """List all drug requests for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, case_id, requester_id, requester_role, items,
               approver_id, approved_at, status, created_at
        FROM drug_requests
        WHERE case_id = ?
        ORDER BY created_at DESC
    """, (case_id,))

    requests = []
    for row in cursor.fetchall():
        requests.append({
            "id": row['id'],
            "case_id": row['case_id'],
            "requester_id": row['requester_id'],
            "requester_role": row['requester_role'],
            "items": json.loads(row['items']) if row['items'] else [],
            "approver_id": row['approver_id'],
            "approved_at": row['approved_at'],
            "status": row['status'],
            "created_at": row['created_at']
        })

    return {"requests": requests}


@router.post("/drugs/requests/{request_id}/approve")
async def approve_drug_request(
    request_id: str,
    actor_id: str = Query(...),
    actor_role: str = Query("PHARMACY")
):
    """Approve a drug request (Pharmacy or Supervisor)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM drug_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req['status'] != 'PENDING':
        raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

    try:
        cursor.execute("""
            UPDATE drug_requests
            SET status = 'APPROVED', approver_id = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (actor_id, request_id))

        conn.commit()

        return {"request_id": request_id, "status": "APPROVED"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drugs/requests/{request_id}/dispense")
async def dispense_drug_request(
    request_id: str,
    actor_id: str = Query(...),
    batch_numbers: Optional[Dict[str, str]] = None  # drug_code -> batch_number
):
    """
    Dispense drugs from an approved request.
    Creates DISPENSE transactions for each item.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM drug_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req['status'] not in ('APPROVED', 'PENDING'):
        raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

    items = json.loads(req['items'])
    case_id = req['case_id']
    tx_time = datetime.now().isoformat()

    try:
        # Create DISPENSE transactions for each item
        transactions = []
        for item in items:
            tx_id = generate_tx_id()
            batch = (batch_numbers or {}).get(item['drug_code'])

            cursor.execute("""
                INSERT INTO drug_transactions (
                    id, request_id, case_id,
                    drug_code, drug_name, schedule_class, batch_number,
                    tx_type, quantity, unit,
                    actor_id, tx_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DISPENSE', ?, ?, ?, ?)
            """, (
                tx_id, request_id, case_id,
                item['drug_code'], item['drug_name'], item.get('schedule_class', 4), batch,
                item['quantity'], item['unit'],
                actor_id, tx_time
            ))

            transactions.append({
                "tx_id": tx_id,
                "drug_code": item['drug_code'],
                "quantity": item['quantity']
            })

        # Update request status
        cursor.execute("""
            UPDATE drug_requests SET status = 'DISPENSED' WHERE id = ?
        """, (request_id,))

        conn.commit()

        return {
            "request_id": request_id,
            "status": "DISPENSED",
            "transactions": transactions
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Drug Transaction API (Direct Recording)
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/drugs/transaction")
async def record_drug_transaction(
    case_id: str,
    request: DrugTransactionRequest,
    actor_id: str = Query(...)
):
    """
    Record a drug transaction (ADMIN, WASTE, RETURN).
    WASTE requires witness_id.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists and is not closed
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot record transaction for closed case")

    # WASTE requires witness
    if request.tx_type == DrugTxType.WASTE and not request.witness_id:
        raise HTTPException(
            status_code=400,
            detail="Witness ID required for drug waste (管藥廢棄需要見證人)"
        )

    # Check for sufficient balance for ADMIN/WASTE/RETURN
    if request.tx_type in (DrugTxType.ADMIN, DrugTxType.WASTE, DrugTxType.RETURN):
        holdings = calculate_drug_holdings(cursor, case_id)
        drug_holding = next((h for h in holdings if h['drug_code'] == request.drug_code), None)
        current_balance = drug_holding['balance'] if drug_holding else 0

        if request.quantity > current_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient balance. Available: {current_balance} {request.unit}"
            )

    tx_id = generate_tx_id()
    tx_time = datetime.now().isoformat()

    # Handle idempotency
    if request.idempotency_key:
        cursor.execute(
            "SELECT id FROM drug_transactions WHERE idempotency_key = ?",
            (request.idempotency_key,)
        )
        existing = cursor.fetchone()
        if existing:
            return {"tx_id": existing['id'], "status": "DUPLICATE"}

    try:
        cursor.execute("""
            INSERT INTO drug_transactions (
                id, request_id, case_id,
                drug_code, drug_name, schedule_class, batch_number,
                tx_type, quantity, unit,
                actor_id, witness_id, witness_verified_at,
                device_id, idempotency_key, tx_time, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx_id,
            request.request_id,
            case_id,
            request.drug_code,
            request.drug_name,
            request.schedule_class,
            request.batch_number,
            request.tx_type.value,
            request.quantity,
            request.unit,
            actor_id,
            request.witness_id,
            datetime.now().isoformat() if request.witness_id else None,
            request.device_id,
            request.idempotency_key,
            tx_time,
            request.notes
        ))

        conn.commit()

        # Get updated holdings
        holdings = calculate_drug_holdings(cursor, case_id)

        return {
            "tx_id": tx_id,
            "tx_type": request.tx_type.value,
            "drug_code": request.drug_code,
            "quantity": request.quantity,
            "unit": request.unit,
            "actor_id": actor_id,
            "witness_id": request.witness_id,
            "holdings": holdings
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Drug Holdings API
# -----------------------------------------------------------------------------

@router.get("/cases/{case_id}/drugs/holdings")
async def get_drug_holdings(case_id: str):
    """Get current drug holdings (balance) for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    holdings = calculate_drug_holdings(cursor, case_id)
    total_balance = sum(h['balance'] for h in holdings)

    return {
        "case_id": case_id,
        "holdings": holdings,
        "total_balance": round(total_balance, 2),
        "is_reconciled": total_balance == 0
    }


@router.get("/cases/{case_id}/drugs/transactions")
async def list_drug_transactions(case_id: str):
    """List all drug transactions for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, request_id, drug_code, drug_name, schedule_class,
               tx_type, quantity, unit, actor_id, witness_id,
               tx_time, recorded_at, notes
        FROM drug_transactions
        WHERE case_id = ?
        ORDER BY tx_time DESC
    """, (case_id,))

    transactions = []
    for row in cursor.fetchall():
        transactions.append({
            "id": row['id'],
            "request_id": row['request_id'],
            "drug_code": row['drug_code'],
            "drug_name": row['drug_name'],
            "schedule_class": row['schedule_class'],
            "tx_type": row['tx_type'],
            "quantity": row['quantity'],
            "unit": row['unit'],
            "actor_id": row['actor_id'],
            "witness_id": row['witness_id'],
            "tx_time": row['tx_time'],
            "recorded_at": row['recorded_at'],
            "notes": row['notes']
        })

    return {"transactions": transactions, "count": len(transactions)}


# -----------------------------------------------------------------------------
# Drug Reconciliation API
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/drugs/reconcile")
async def reconcile_drugs(
    case_id: str,
    actor_id: str = Query(...),
    actor_role: str = Query("ANES_MD")
):
    """
    Reconcile drugs for a case.
    Requires total balance = 0 and ANES_MD role.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify role
    if actor_role != "ANES_MD":
        raise HTTPException(
            status_code=403,
            detail="Only ANES_MD can reconcile drugs (需要麻醉醫師核准)"
        )

    # Verify case exists
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check balance
    total_balance = get_total_balance(cursor, case_id)
    if total_balance != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reconcile: balance is {total_balance}, must be 0"
        )

    # Update all pending requests to RECONCILED
    cursor.execute("""
        UPDATE drug_requests
        SET status = 'RECONCILED'
        WHERE case_id = ? AND status = 'DISPENSED'
    """, (case_id,))

    conn.commit()

    return {
        "case_id": case_id,
        "status": "RECONCILED",
        "reconciled_by": actor_id,
        "reconciled_at": datetime.now().isoformat()
    }


@router.get("/cases/{case_id}/drugs/can-close")
async def check_can_close_case(case_id: str):
    """Check if case can be closed (drug balance must be 0)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    total_balance = get_total_balance(cursor, case_id)
    holdings = calculate_drug_holdings(cursor, case_id)

    return {
        "case_id": case_id,
        "can_close": total_balance == 0,
        "total_balance": round(total_balance, 2),
        "holdings": holdings,
        "message": None if total_balance == 0 else f"Drug balance must be 0 (current: {total_balance})"
    }


# ============================================================
# CIRS Hub Proxy Endpoints (Hub-Satellite Architecture)
# ============================================================

import httpx
from typing import Optional
import os
from fastapi.responses import JSONResponse

# CIRS Hub configuration
CIRS_HUB_URL = os.getenv("CIRS_HUB_URL", "http://localhost:8000")
CIRS_TIMEOUT = 5.0  # seconds

# xIRS Protocol Version (see DEV_SPEC Section I.2)
XIRS_PROTOCOL_VERSION = "1.0"
STATION_ID = os.getenv("MIRS_STATION_ID", "MIRS-UNKNOWN")


def make_xirs_response(data: dict, hub_revision: int = 0) -> JSONResponse:
    """Create response with xIRS protocol headers."""
    return JSONResponse(
        content=data,
        headers={
            "X-XIRS-Protocol-Version": XIRS_PROTOCOL_VERSION,
            "X-XIRS-Hub-Revision": str(hub_revision),
            "X-XIRS-Station-Id": STATION_ID,
        }
    )


@router.get("/proxy/cirs/waiting-list")
async def get_cirs_waiting_list(
    status: Optional[str] = "waiting",
    limit: int = 50
):
    """
    Proxy endpoint to fetch waiting list from CIRS Hub.
    Returns patients waiting for procedures (for case creation).

    Gracefully handles offline scenarios by returning empty list with offline flag.

    Response Headers:
    - X-XIRS-Protocol-Version: Contract version (1.0)
    - X-XIRS-Hub-Revision: Latest Hub revision number
    - X-XIRS-Station-Id: This satellite's station ID
    """
    hub_revision = 0

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            # Use the waiting list endpoint (no auth required for Doctor PWA compatibility)
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/waiting/list"
            )

            # Extract hub revision from response headers if available
            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                data = response.json()
                # Transform CIRS data to MIRS format
                # CIRS waiting list format: reg_id, patient_ref, display_name, triage, priority, etc.
                patients = []
                for reg in data.get("registrations", data if isinstance(data, list) else []):
                    patients.append({
                        "registration_id": reg.get("reg_id") or reg.get("id") or reg.get("registration_id"),
                        "patient_id": reg.get("patient_id") or reg.get("person_id"),
                        "patient_ref": reg.get("patient_ref"),  # Masked patient reference
                        "name": reg.get("display_name") or reg.get("patient_name") or reg.get("name"),
                        "age_group": reg.get("age_group"),
                        "dob": reg.get("dob"),
                        "sex": reg.get("gender") or reg.get("sex"),
                        "allergies": reg.get("allergies", []),
                        "weight_kg": reg.get("weight_kg"),
                        "blood_type": reg.get("blood_type"),
                        "triage_category": reg.get("triage") or reg.get("triage_category"),
                        "priority": reg.get("priority"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "status": reg.get("status"),
                        "registered_at": reg.get("registered_at") or reg.get("created_at")
                    })

                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "patients": patients,
                    "count": len(patients),
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)
            else:
                logger.warning(f"CIRS Hub returned {response.status_code}")
                return make_xirs_response({
                    "online": False,
                    "source": "offline",
                    "patients": [],
                    "count": 0,
                    "error": f"CIRS returned status {response.status_code}",
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)

    except httpx.TimeoutException:
        logger.warning("CIRS Hub timeout - operating in offline mode")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub timeout",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except httpx.ConnectError:
        logger.info("CIRS Hub not reachable - operating in offline mode")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub not reachable",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except Exception as e:
        logger.error(f"CIRS proxy error: {e}")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "patients": [],
            "count": 0,
            "error": str(e),
            "protocol_version": XIRS_PROTOCOL_VERSION
        })


@router.get("/proxy/cirs/waiting-anesthesia")
async def get_cirs_waiting_anesthesia():
    """
    v1.1: 取得待麻醉清單 (使用新的 CIRS /waiting/anesthesia 端點)

    只返回:
    - status = CONSULTATION_DONE
    - needs_anesthesia = 1

    這是 v1.1 流程改進的核心：醫師完成看診後勾選「需麻醉」的病患才會出現。
    """
    hub_revision = 0

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            # v1.1: 使用新的 waiting/anesthesia 端點
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/waiting/anesthesia"
            )

            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                data = response.json()
                # Transform CIRS data to MIRS format
                patients = []
                for reg in data.get("items", []):
                    patients.append({
                        "registration_id": reg.get("reg_id"),
                        "patient_id": reg.get("person_id"),
                        "patient_ref": reg.get("patient_ref"),
                        "name": reg.get("display_name"),
                        "age_group": reg.get("age_group"),
                        "sex": reg.get("gender"),
                        "triage_category": reg.get("triage"),
                        "priority": reg.get("priority"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "anesthesia_notes": reg.get("anesthesia_notes"),
                        "consultation_by": reg.get("consultation_by"),
                        "consultation_completed_at": reg.get("consultation_completed_at"),
                        "waiting_minutes": reg.get("waiting_minutes"),
                        "claimed_by": reg.get("anesthesia_claimed_by"),
                        "claimed_at": reg.get("anesthesia_claimed_at")
                    })

                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "queue": "ANESTHESIA",
                    "patients": patients,
                    "count": len(patients),
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)
            else:
                logger.warning(f"CIRS Hub waiting/anesthesia returned {response.status_code}")
                return make_xirs_response({
                    "online": False,
                    "source": "offline",
                    "queue": "ANESTHESIA",
                    "patients": [],
                    "count": 0,
                    "error": f"CIRS returned status {response.status_code}",
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)

    except httpx.TimeoutException:
        logger.warning("CIRS Hub timeout for waiting/anesthesia")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "ANESTHESIA",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub timeout",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except httpx.ConnectError:
        logger.info("CIRS Hub not reachable for waiting/anesthesia")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "ANESTHESIA",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub not reachable",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except Exception as e:
        logger.error(f"CIRS waiting/anesthesia proxy error: {e}")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "ANESTHESIA",
            "patients": [],
            "count": 0,
            "error": str(e),
            "protocol_version": XIRS_PROTOCOL_VERSION
        })


@router.get("/proxy/cirs/patient/{registration_id}")
async def get_cirs_patient_details(registration_id: str):
    """
    Fetch detailed patient info from CIRS Hub by registration ID.
    Used when creating a case to get full patient snapshot.

    Response Headers:
    - X-XIRS-Protocol-Version: Contract version (1.0)
    - X-XIRS-Hub-Revision: Latest Hub revision number
    - X-XIRS-Station-Id: This satellite's station ID
    """
    hub_revision = 0

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/{registration_id}"
            )

            # Extract hub revision from response headers if available
            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                reg = response.json()
                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "patient": {
                        "registration_id": reg.get("id") or reg.get("registration_id"),
                        "patient_id": reg.get("patient_id"),
                        "name": reg.get("patient_name") or reg.get("name"),
                        "dob": reg.get("dob"),
                        "sex": reg.get("sex"),
                        "allergies": reg.get("allergies", []),
                        "weight_kg": reg.get("weight_kg"),
                        "blood_type": reg.get("blood_type"),
                        "triage_category": reg.get("triage_category"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "medical_history": reg.get("medical_history"),
                        "current_medications": reg.get("current_medications"),
                        "status": reg.get("status")
                    },
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Registration not found in CIRS")
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"CIRS Hub error: {response.status_code}"
                )

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="CIRS Hub timeout")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="CIRS Hub not reachable")
    except Exception as e:
        logger.error(f"CIRS patient fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hub/status")
async def get_hub_status():
    """
    Returns Hub-Satellite sync status for this station.

    Response Headers:
    - X-XIRS-Protocol-Version: Contract version (1.0)
    - X-XIRS-Station-Id: This satellite's station ID
    """
    # Check CIRS Hub connectivity
    hub_online = False
    hub_revision = 0
    hub_error = None

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.get(f"{CIRS_HUB_URL}/api/health")
            if response.status_code == 200:
                hub_online = True
                hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))
    except Exception as e:
        hub_error = str(e)

    return make_xirs_response({
        "station_id": STATION_ID,
        "protocol_version": XIRS_PROTOCOL_VERSION,
        "hub_url": CIRS_HUB_URL,
        "hub_online": hub_online,
        "hub_revision": hub_revision,
        "hub_error": hub_error,
        "last_sync": None,  # TODO: Track last sync time
        "pending_ops": 0,   # TODO: Count pending operations
    }, hub_revision)
