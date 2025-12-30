# MIRS Module Spec: Anesthesia & Controlled Substances

**Version:** 1.5.1 (Renewed)
**Strategy:** Event-Sourced, Offline-First, Resource-Aware
**Core Philosophy:** "No Updates, Only Events"

---

## Changelog: Why This Spec Was Rewritten

### Original Spec v1.5.0 Issues

| Issue | Original Design | Problem | Fix in v1.5.1 |
|-------|-----------------|---------|---------------|
| **Vital Signs Storage** | `vital_signs TEXT` (JSON array) | Merge conflicts during offline sync; no audit trail for individual changes | Append-only `anesthesia_events` table |
| **Medication Records** | `medications TEXT` (JSON array) | Same as above; can't track who recorded what when | Each medication = discrete event row |
| **Update Pattern** | `PUT /api/anesthesia/records/{id}` | Semantic updates destroy audit trail; violates medical record immutability | `POST` events only; `PUT` limited to metadata |
| **Controlled Drugs** | Single status field | Can't track balance; no double-entry accounting | Transaction ledger with balance computation |
| **Offline Proof** | Not addressed | No way to verify actions taken offline | `witness_id` + `offline_proof_artifact_id` |
| **Wartime Mode** | Full preop form only | Too slow for battlefield conditions | `STANDARD` vs `BATTLEFIELD` mode switch |
| **Resource Coupling** | Not addressed | Anesthesia doesn't drive O2 consumption | Oxygen cylinder "claim" + flow rate tracking |

### Architecture Decision Records (ADR)

**ADR-001: Event Sourcing for Clinical Data**
- **Context:** Medical records must be immutable and auditable
- **Decision:** All clinical events are append-only; corrections create new events referencing the original
- **Consequence:** Simpler merge resolution; complete audit trail; slightly more storage

**ADR-002: Controlled Drugs as Ledger**
- **Context:** Controlled substances require strict accountability
- **Decision:** Use double-entry transaction log (DISPENSE/ADMIN/WASTE/RETURN)
- **Consequence:** Balance always computable; discrepancies immediately visible

**ADR-003: Oxygen Cylinder Claim Model**
- **Context:** Need to track which O2 cylinder is used by which case
- **Decision:** "Claim" model (case binds to cylinder) instead of "dispatch" model (station owns cylinder)
- **Consequence:** Simpler than full station management; prevents accidental multi-use

**ADR-004: Separate Anesthesia Doctor PWA**
- **Context:** Digital signature needed for legal compliance
- **Decision:** Create `/anesthesia-doctor` PWA with PIN-based signing (same pattern as CIRS Doctor PWA)
- **Consequence:** Reuse existing signing infrastructure; clear role separation

---

## 1. System Context

### 1.1 What "Anesthesia" Means in BORP

In a Backup Operating Room Point (BORP), anesthesia is not just documentation—it is:

1. **Physiologic Safety Control** - Continuous monitoring and intervention
2. **Scarce Resource Governor** - Oxygen, power, controlled drugs
3. **Legal Record** - Must survive audit, even if handwritten first

### 1.2 Current Reality (Taiwan Hospital Practice)

```
Today's Workflow:
┌─────────────────────────────────────────────────────────┐
│ 1. 麻醉護士手寫紀錄單                                    │
│ 2. 每5分鐘記錄 vital signs                               │
│ 3. 管制藥品用專用處方箋                                  │
│ 4. 術後拍照存檔成 PDF                                    │
│ 5. 管藥由藥局獨立管理                                    │
└─────────────────────────────────────────────────────────┘

MIRS Goal:
┌─────────────────────────────────────────────────────────┐
│ 1. 數位化事件流（可與手寫並行）                          │
│ 2. 自動計算氧氣消耗                                      │
│ 3. 管藥雙人簽核 + 離線存證                               │
│ 4. 支援 BATTLEFIELD 快速模式                             │
└─────────────────────────────────────────────────────────┘
```

### 1.3 Module Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                         MIRS                                 │
├─────────────────┬───────────────────┬───────────────────────┤
│   Anesthesia    │    Equipment      │      Pharmacy         │
│   Module        │    Module         │      Module           │
│                 │                   │                       │
│ - Case Header   │ - O2 Cylinders    │ - Drug Inventory      │
│ - Event Stream  │ - Power Stations  │ - Dispatch Flow       │
│ - Drug Ledger   │ - Ventilators     │                       │
│ - PreOp/PACU    │                   │                       │
├─────────────────┴───────────────────┴───────────────────────┤
│                    Shared: WAL Sync Engine                   │
└─────────────────────────────────────────────────────────────┘
```

**What Anesthesia Module Does NOT Own:**
- Billing/收費 (→ CashDesk)
- Equipment maintenance (→ Equipment Module)
- Drug inventory management (→ Pharmacy Module)

---

## 2. Data Model: Event-Sourced Architecture

### 2.1 Core Tables

```sql
-- =============================================================================
-- 麻醉案例 (The Container - Mostly Immutable)
-- =============================================================================
CREATE TABLE anesthesia_cases (
    id TEXT PRIMARY KEY,                    -- 'ANES-YYYYMMDD-NNN'
    surgery_case_id TEXT NOT NULL,          -- Link to surgery_cases
    patient_id TEXT NOT NULL,

    -- Context (Captured at Creation, Locked In)
    context_mode TEXT NOT NULL DEFAULT 'STANDARD',  -- 'STANDARD' | 'BATTLEFIELD'

    -- Staff Assignment (Mutable via specific events)
    primary_anesthesiologist_id TEXT,
    primary_nurse_id TEXT,

    -- Planning
    planned_technique TEXT,                 -- 'GA_ETT', 'RA_SPINAL', 'LA', 'SEDATION'

    -- Oxygen Source Claim (See Section 4)
    oxygen_source_type TEXT,                -- 'CENTRAL', 'CONCENTRATOR', 'CYLINDER'
    oxygen_source_id TEXT,                  -- equipment_unit.id if CYLINDER

    -- Timestamps (Updated by lifecycle events)
    preop_completed_at DATETIME,
    anesthesia_start_at DATETIME,
    surgery_start_at DATETIME,
    surgery_end_at DATETIME,
    anesthesia_end_at DATETIME,
    pacu_admission_at DATETIME,
    pacu_discharge_at DATETIME,

    -- Status
    status TEXT NOT NULL DEFAULT 'PREOP',   -- 'PREOP', 'IN_PROGRESS', 'PACU', 'CLOSED'

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL,

    FOREIGN KEY (surgery_case_id) REFERENCES surgery_cases(id)
);

-- =============================================================================
-- 麻醉事件流 (The Append-Only Truth)
-- =============================================================================
CREATE TABLE anesthesia_events (
    id TEXT PRIMARY KEY,                    -- UUID
    case_id TEXT NOT NULL,

    -- Event Classification
    event_type TEXT NOT NULL,               -- See EventType enum below

    -- Timestamps
    clinical_time DATETIME NOT NULL,        -- When it happened (user-entered or inferred)
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- When it was recorded (system)

    -- Polymorphic Payload (JSON)
    payload TEXT NOT NULL,                  -- JSON object, schema depends on event_type

    -- Actor & Device (Audit)
    actor_id TEXT NOT NULL,                 -- Who recorded this
    device_id TEXT,                         -- Which device

    -- Idempotency (Critical for Offline Sync)
    idempotency_key TEXT UNIQUE,            -- '{case_id}:{device_id}:{local_seq}'

    -- Correction Chain (No Delete, Only Correct)
    is_correction BOOLEAN DEFAULT FALSE,
    corrects_event_id TEXT,                 -- Points to the event being corrected
    correction_reason TEXT,

    -- Sync Status
    sync_status TEXT DEFAULT 'LOCAL',       -- 'LOCAL', 'SYNCED', 'CONFLICT'

    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
    FOREIGN KEY (corrects_event_id) REFERENCES anesthesia_events(id)
);

-- Index for timeline reconstruction
CREATE INDEX idx_anes_events_timeline ON anesthesia_events(case_id, clinical_time);
CREATE INDEX idx_anes_events_type ON anesthesia_events(case_id, event_type);
CREATE INDEX idx_anes_events_sync ON anesthesia_events(sync_status);
```

### 2.2 Event Types

```typescript
type AnesthesiaEventType =
  // Vital Signs (Every 5 minutes)
  | 'VITAL_SIGN'          // { bp_sys, bp_dia, hr, spo2, etco2, temp, o2_flow_lpm, fio2 }

  // Medications
  | 'MEDICATION_ADMIN'    // { drug_code, drug_name, dose, unit, route, tx_id? }

  // Fluids & Blood
  | 'FLUID_IN'            // { fluid_type, volume_ml }
  | 'BLOOD_PRODUCT'       // { product_type, unit_id, volume_ml }
  | 'FLUID_OUT'           // { type: 'URINE'|'EBL'|'DRAIN', volume_ml }

  // Airway & Ventilation
  | 'AIRWAY_EVENT'        // { action: 'INTUBATION'|'EXTUBATION'|'LMA', details }

  // Clinical Milestones
  | 'MILESTONE'           // { type: 'ANESTHESIA_START'|'INCISION'|'CLOSURE'|'ANESTHESIA_END' }

  // Resource Checks (Drives Oxygen Calculation)
  | 'RESOURCE_CHECK'      // { resource: 'O2_CYLINDER', value, unit, est_minutes_left }

  // Equipment Events
  | 'EQUIPMENT_EVENT'     // { equipment_id, action: 'START'|'STOP'|'ALARM', details }

  // Free-form Notes
  | 'NOTE'                // { text, category?: 'CRITICAL'|'INFO' }

  // Lifecycle
  | 'STATUS_CHANGE'       // { from, to, reason? }
  | 'STAFF_CHANGE'        // { role, from_id, to_id }

  // Signatures (Digital or Offline Proof)
  | 'SIGNATURE'           // { signer_id, role, signature_data?, offline_proof_id? }
```

### 2.3 Event Payload Examples

```json
// VITAL_SIGN
{
  "bp_sys": 120,
  "bp_dia": 75,
  "hr": 72,
  "spo2": 99,
  "etco2": 35,
  "temp": 36.5,
  "o2_flow_lpm": 2.0,
  "fio2": 0.4
}

// MEDICATION_ADMIN
{
  "drug_code": "PROPO001",
  "drug_name": "Propofol 1% 200mg/20ml",
  "dose": 150,
  "unit": "mg",
  "route": "IV",
  "tx_id": "TX-2025-001"  // Links to drug_transactions if controlled
}

// AIRWAY_EVENT
{
  "action": "INTUBATION",
  "device": "ETT",
  "size": "7.5",
  "depth_cm": 22,
  "attempts": 1,
  "difficulty": "EASY",
  "cormack_lehane": 1
}

// RESOURCE_CHECK
{
  "resource": "O2_CYLINDER",
  "cylinder_id": "O2-CYL-003",
  "pressure_psi": 1500,
  "flow_lpm": 2.0,
  "est_minutes_left": 45
}
```

---

## 3. Controlled Substances: The Ledger Model

### 3.1 Why a Ledger?

管制藥品 = 現金。我們使用**雙重登錄**（Double-Entry）確保每一毫克可追溯。

```
Transaction Flow:
┌─────────┐    DISPENSE    ┌─────────┐    ADMIN     ┌─────────┐
│ Pharmacy │ ────────────▶ │  Nurse  │ ───────────▶ │ Patient │
│  (Cr)    │               │  (Dr)   │              │  (Dr)   │
└─────────┘                └─────────┘              └─────────┘
                                │
                                │ WASTE (with witness)
                                ▼
                           ┌─────────┐
                           │  Trash  │
                           │  (Dr)   │
                           └─────────┘
```

**Balance Equation:**
```
Current Holding = Sum(DISPENSE) - Sum(ADMIN) - Sum(WASTE) - Sum(RETURN)
```

If `Current Holding ≠ 0` at case closure → **Block Sign-off**

### 3.2 Schema

```sql
-- =============================================================================
-- 管制藥品申請單 (The Request)
-- =============================================================================
CREATE TABLE drug_requests (
    id TEXT PRIMARY KEY,                    -- 'REQ-YYYYMMDD-NNN'
    case_id TEXT NOT NULL,

    -- Requester
    requester_id TEXT NOT NULL,             -- ANES_MD or ANES_NA
    requester_role TEXT NOT NULL,

    -- Request Details (Multiple Items per Request)
    items TEXT NOT NULL,                    -- JSON: [{ drug_code, qty_requested }]

    -- Approval
    approver_id TEXT,                       -- PHARMACY or SUPERVISOR
    approved_at DATETIME,

    -- Status
    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'APPROVED', 'DISPENSED', 'RECONCILED', 'REJECTED'

    -- Offline Proof (if approved offline)
    offline_proof_artifact_id TEXT,         -- Photo of paper form

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);

-- =============================================================================
-- 管制藥品交易流水帳 (The Ledger)
-- =============================================================================
CREATE TABLE drug_transactions (
    id TEXT PRIMARY KEY,                    -- UUID
    request_id TEXT NOT NULL,
    case_id TEXT NOT NULL,

    -- Drug
    drug_code TEXT NOT NULL,
    drug_name TEXT NOT NULL,
    schedule_class INTEGER NOT NULL,        -- 第幾級 (1-4)
    batch_number TEXT,                      -- Lot tracking

    -- Transaction
    tx_type TEXT NOT NULL,                  -- 'DISPENSE', 'ADMIN', 'WASTE', 'RETURN'
    quantity REAL NOT NULL,                 -- Always positive
    unit TEXT NOT NULL,                     -- 'mg', 'ml', 'amp'

    -- Actors
    actor_id TEXT NOT NULL,                 -- Who performed
    witness_id TEXT,                        -- Required for WASTE

    -- Idempotency
    idempotency_key TEXT UNIQUE,
    device_id TEXT,
    local_seq INTEGER,

    -- Timestamps
    tx_time DATETIME NOT NULL,              -- When it happened
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Sync
    sync_status TEXT DEFAULT 'LOCAL',

    FOREIGN KEY (request_id) REFERENCES drug_requests(id),
    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);

-- View: Current Holdings per Case
CREATE VIEW drug_holdings AS
SELECT
    case_id,
    drug_code,
    drug_name,
    SUM(CASE WHEN tx_type = 'DISPENSE' THEN quantity ELSE 0 END) as dispensed,
    SUM(CASE WHEN tx_type = 'ADMIN' THEN quantity ELSE 0 END) as administered,
    SUM(CASE WHEN tx_type = 'WASTE' THEN quantity ELSE 0 END) as wasted,
    SUM(CASE WHEN tx_type = 'RETURN' THEN quantity ELSE 0 END) as returned,
    SUM(CASE WHEN tx_type = 'DISPENSE' THEN quantity ELSE 0 END) -
    SUM(CASE WHEN tx_type IN ('ADMIN', 'WASTE', 'RETURN') THEN quantity ELSE 0 END) as balance
FROM drug_transactions
GROUP BY case_id, drug_code;

-- Index
CREATE INDEX idx_drug_tx_case ON drug_transactions(case_id, drug_code);
CREATE INDEX idx_drug_tx_request ON drug_transactions(request_id);
```

### 3.3 Dual-Control Rules

| Action | Primary Actor | Witness Required | Offline Policy |
|--------|---------------|------------------|----------------|
| REQUEST | ANES_MD / ANES_NA | No | Allowed |
| DISPENSE | PHARMACY / SUPERVISOR | No | Requires offline_proof |
| ADMIN | ANES_MD / ANES_NA | No | Allowed |
| WASTE | ANES_MD / ANES_NA | **Yes** (ANES_NA or SUPERVISOR) | Requires offline_proof + witness |
| RETURN | ANES_MD / ANES_NA | No | Allowed |
| RECONCILE | PHARMACY + ANES_MD | Both sign | Both sign required |

---

## 4. Oxygen Cylinder Claim Model

### 4.1 Why "Claim" Instead of "Dispatch"?

| Model | Description | Complexity | Use Case |
|-------|-------------|------------|----------|
| **Dispatch** | Station owns inventory, dispatches to sub-stations | High (needs station management) | CIRS multi-station |
| **Claim** | Case binds to equipment unit directly | Low | MIRS single-station BORP |

For MIRS, we use **Claim**:
- Anesthesia nurse scans O2 cylinder barcode
- System marks cylinder as `IN_USE_BY: {case_id}`
- Other cases cannot claim the same cylinder
- Case closure releases the claim

### 4.2 Schema Extension

```sql
-- Add to equipment_units table (already exists in MIRS)
ALTER TABLE equipment_units ADD COLUMN claimed_by_case_id TEXT;
ALTER TABLE equipment_units ADD COLUMN claimed_at DATETIME;
ALTER TABLE equipment_units ADD COLUMN claimed_by_user_id TEXT;
```

### 4.3 Claim Flow

```
1. Nurse scans barcode → GET /api/equipment/units/{serial}
2. Check: unit.claimed_by_case_id IS NULL
3. If available → POST /api/anesthesia/{case_id}/claim-oxygen
   - Updates equipment_unit.claimed_by_case_id
   - Updates anesthesia_case.oxygen_source_id
4. If already claimed → Show error: "此氧氣瓶已被 Case-XXX 使用中"
5. Case closes → Automatically release claim
```

### 4.4 O2 Consumption Tracking

Every `VITAL_SIGN` event includes `o2_flow_lpm`. Combined with `RESOURCE_CHECK` events, we can:

```python
def estimate_o2_minutes_remaining(case_id: str) -> float:
    # Get claimed cylinder
    case = get_case(case_id)
    if case.oxygen_source_type != 'CYLINDER':
        return float('inf')  # Central supply assumed infinite

    # Get latest resource check
    last_check = get_latest_event(case_id, 'RESOURCE_CHECK',
                                   filter={'resource': 'O2_CYLINDER'})

    # Get average flow rate since last check
    vitals = get_events_since(case_id, 'VITAL_SIGN', last_check.clinical_time)
    avg_flow = mean([v.payload.o2_flow_lpm for v in vitals if v.payload.o2_flow_lpm])

    # Calculate
    if avg_flow > 0:
        liters_remaining = pressure_to_liters(last_check.payload.pressure_psi)
        return liters_remaining / avg_flow
    return last_check.payload.est_minutes_left
```

---

## 5. Pre-Op Assessment: Standard vs Battlefield

### 5.1 Schema

```sql
CREATE TABLE preop_assessments (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE,

    -- Mode
    mode TEXT NOT NULL DEFAULT 'STANDARD',  -- 'STANDARD' | 'BATTLEFIELD'

    -- ===========================================
    -- STANDARD Mode Fields (Full Assessment)
    -- ===========================================

    -- ASA Classification
    asa_class INTEGER CHECK(asa_class BETWEEN 1 AND 6),
    asa_emergency BOOLEAN DEFAULT FALSE,

    -- NPO Status
    npo_hours REAL,
    last_oral_intake DATETIME,
    npo_status TEXT,                        -- 'EMPTY', 'CLEAR_LIQUID', 'FULL', 'UNKNOWN'

    -- Allergies
    allergies TEXT,                         -- JSON array
    allergy_verified BOOLEAN DEFAULT FALSE,

    -- Airway Assessment
    mallampati_score INTEGER CHECK(mallampati_score BETWEEN 1 AND 4),
    thyromental_distance TEXT,              -- 'NORMAL', 'SHORT' (<6cm)
    neck_mobility TEXT,                     -- 'FULL', 'LIMITED', 'RESTRICTED'
    mouth_opening TEXT,                     -- 'NORMAL', 'LIMITED' (<3cm)
    teeth_status TEXT,                      -- 'NORMAL', 'LOOSE', 'DENTURES', 'DAMAGED'
    difficult_airway_history BOOLEAN,
    difficult_airway_anticipated BOOLEAN,

    -- Medical History
    comorbidities TEXT,                     -- JSON array
    current_medications TEXT,               -- JSON array
    cardiac_risk_index INTEGER,

    -- ===========================================
    -- BATTLEFIELD Mode Fields (Quick Flags)
    -- ===========================================

    -- Quick Decision Flags (JSON for flexibility)
    quick_flags TEXT,                       -- See schema below

    -- ===========================================
    -- Common Fields
    -- ===========================================

    -- Plan
    planned_technique TEXT,
    backup_plan TEXT,
    special_considerations TEXT,

    -- Sign-off
    assessed_by TEXT NOT NULL,
    assessment_datetime DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'PENDING',          -- 'PENDING', 'APPROVED', 'NEEDS_REVIEW'
    approved_by TEXT,
    approved_at DATETIME,

    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);
```

### 5.2 Battlefield Quick Flags Schema

```typescript
interface BattlefieldQuickFlags {
  // 5 Critical Decision Points
  airwayRisk: 'NORMAL' | 'DIFFICULT';
  hdStable: 'YES' | 'NO' | 'UNKNOWN';
  npoStatus: 'EMPTY' | 'FULL_OR_UNKNOWN';
  hemorrhageRisk: 'LOW' | 'HIGH';
  estimatedDuration: 'SHORT' | 'MEDIUM' | 'LONG';  // <1h, 1-3h, >3h

  // Optional Notes
  criticalNotes?: string;
}
```

### 5.3 UI Comparison

```
STANDARD Mode:                          BATTLEFIELD Mode:
┌─────────────────────────────┐        ┌─────────────────────────────┐
│ ASA Classification          │        │ ⚡ BATTLEFIELD MODE         │
│ ○ I  ○ II  ● III  ○ IV     │        ├─────────────────────────────┤
├─────────────────────────────┤        │ Airway:   [Normal] [Difficult]
│ NPO Status                  │        │ HD:       [Stable] [Unstable]
│ Last intake: [______] hrs   │        │ NPO:      [Empty] [Unknown]  │
├─────────────────────────────┤        │ Bleeding: [Low]   [High]     │
│ Mallampati: ○1 ○2 ●3 ○4    │        │ Duration: [<1h] [1-3h] [>3h] │
│ TMD: ○ Normal  ● Short      │        ├─────────────────────────────┤
│ Neck: ● Full  ○ Limited     │        │ Notes: [________________]   │
│ ...20+ more fields...       │        ├─────────────────────────────┤
├─────────────────────────────┤        │      [Ready for Induction]  │
│ [Save Draft] [Submit]       │        └─────────────────────────────┘
└─────────────────────────────┘
```

---

## 6. PACU (Post-Anesthesia Care Unit)

### 6.1 Schema

```sql
CREATE TABLE pacu_assessments (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    anesthesia_case_id TEXT NOT NULL,

    -- Admission
    admission_time DATETIME NOT NULL,
    handoff_from TEXT NOT NULL,             -- Anesthesiologist ID
    handoff_to TEXT NOT NULL,               -- PACU Nurse ID

    -- Handoff Checklist
    handoff_checklist TEXT NOT NULL,        -- JSON: { airway, analgesia, ponv, complications }

    -- Aldrete Scores (Timed)
    assessments TEXT,                       -- JSON array: [{ time, aldrete_total, details }]

    -- Pain
    pain_scores TEXT,                       -- JSON array: [{ time, nrs_score }]
    analgesics_given TEXT,                  -- JSON array

    -- Complications
    complications TEXT,                     -- JSON array: [{ time, type, intervention }]

    -- Discharge
    discharge_time DATETIME,
    discharge_aldrete_score INTEGER,
    discharge_criteria_met BOOLEAN,
    discharged_by TEXT,
    discharge_destination TEXT,             -- 'WARD', 'ICU', 'HOME'

    -- Sign-off
    anesthesiologist_signoff_id TEXT,
    anesthesiologist_signoff_at DATETIME,

    -- Status
    status TEXT DEFAULT 'IN_PACU',          -- 'IN_PACU', 'READY_DISCHARGE', 'DISCHARGED'

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id),
    FOREIGN KEY (anesthesia_case_id) REFERENCES anesthesia_cases(id)
);
```

### 6.2 Handoff Checklist Schema

```typescript
interface PACUHandoffChecklist {
  airway: {
    type: 'EXTUBATED' | 'INTUBATED' | 'LMA' | 'MASK';
    issues?: string;
  };
  analgesia: {
    method: 'IV_PCA' | 'EPIDURAL' | 'NERVE_BLOCK' | 'IV_PRN' | 'NONE';
    current_pain_nrs: number;
  };
  ponv: {
    risk: 'LOW' | 'MODERATE' | 'HIGH';
    prophylaxis_given: boolean;
  };
  complications: string[];
  specialInstructions?: string;
}
```

---

## 7. PWA Architecture

### 7.1 New PWA: Anesthesia Doctor (`/anesthesia-doctor`)

**Purpose:** Digital signature, case review, reconciliation approval

**Features:**
- PIN-based login (same as CIRS Doctor PWA)
- Session-bound signing key
- Case list with sign-off status
- Drug reconciliation approval
- PACU discharge authorization

**Tech:** Reuse CIRS Doctor PWA pattern (Ed25519 signing)

### 7.2 New PWA: Anesthesia Station (`/anesthesia`)

**Purpose:** Primary intraop documentation interface (tablet-optimized)

**Features:**
- Timeline-based event entry
- One-tap vitals recording
- Medication quick-buttons
- Drug ledger view
- O2 cylinder claim + monitoring
- Wartime mode toggle

### 7.3 Existing PWA Modifications

| PWA | Modification |
|-----|--------------|
| `/admin` | Add Anesthesia module config |
| `/pharmacy` | Add drug request approval queue |
| `/station` | Add O2 cylinder barcode scanning |

---

## 8. API Specification

### 8.1 Case Management

```
POST   /api/anesthesia/cases                    # Create case
GET    /api/anesthesia/cases                    # List cases
GET    /api/anesthesia/cases/{id}               # Get case detail
PATCH  /api/anesthesia/cases/{id}               # Update metadata only
POST   /api/anesthesia/cases/{id}/close         # Close case (with validation)
```

### 8.2 Event Stream (Append-Only)

```
POST   /api/anesthesia/cases/{id}/events        # Add event(s)
GET    /api/anesthesia/cases/{id}/events        # Get all events
GET    /api/anesthesia/cases/{id}/timeline      # Get reconstructed timeline
POST   /api/anesthesia/cases/{id}/events/{eid}/correct  # Add correction event
```

### 8.3 Drug Ledger

```
POST   /api/anesthesia/drugs/request            # Create request
GET    /api/anesthesia/drugs/requests           # List requests
POST   /api/anesthesia/drugs/requests/{id}/approve  # Approve
POST   /api/anesthesia/drugs/tx                 # Record transaction
GET    /api/anesthesia/drugs/holdings/{case_id} # Get current holdings
GET    /api/anesthesia/drugs/reconciliation     # Discrepancy report
POST   /api/anesthesia/drugs/requests/{id}/reconcile  # Final reconciliation
```

### 8.4 Oxygen Claim

```
POST   /api/anesthesia/cases/{id}/claim-oxygen  # Claim cylinder
DELETE /api/anesthesia/cases/{id}/claim-oxygen  # Release claim
GET    /api/anesthesia/cases/{id}/oxygen-status # Current O2 status + estimate
```

### 8.5 Pre-Op

```
POST   /api/anesthesia/cases/{id}/preop         # Create assessment
GET    /api/anesthesia/cases/{id}/preop         # Get assessment
PUT    /api/anesthesia/cases/{id}/preop         # Update assessment
POST   /api/anesthesia/cases/{id}/preop/approve # Approve
```

### 8.6 PACU

```
POST   /api/anesthesia/pacu                     # Admit to PACU
GET    /api/anesthesia/pacu                     # List current patients
POST   /api/anesthesia/pacu/{id}/assess         # Add assessment
POST   /api/anesthesia/pacu/{id}/discharge      # Discharge
```

### 8.7 Signatures

```
POST   /api/anesthesia/cases/{id}/sign          # Digital sign-off
POST   /api/anesthesia/cases/{id}/offline-proof # Upload offline proof
```

---

## 9. Role-Based Access Control

### 9.1 New Roles

```python
class AnesthesiaRole(str, Enum):
    ANES_MD = "anes_md"           # 麻醉科醫師
    ANES_NA = "anes_na"           # 麻醉護理師
    PACU_RN = "pacu_rn"           # 恢復室護理師
```

### 9.2 Permission Matrix

| Action | ANES_MD | ANES_NA | PACU_RN | PHARMACY | ADMIN |
|--------|---------|---------|---------|----------|-------|
| Create Case | ✓ | ✓ | - | - | ✓ |
| Add Event | ✓ | ✓ | - | - | - |
| Correct Event | ✓ | - | - | - | - |
| Request Drug | ✓ | ✓ | - | - | - |
| Dispense Drug | - | - | - | ✓ | ✓ |
| Record ADMIN | ✓ | ✓ | - | - | - |
| Record WASTE (actor) | ✓ | ✓ | - | - | - |
| Witness WASTE | - | ✓ | - | - | ✓ |
| Reconcile Drug | ✓ | - | - | ✓ | - |
| Claim O2 | ✓ | ✓ | - | - | - |
| PreOp Create | ✓ | ✓ | - | - | - |
| PreOp Approve | ✓ | - | - | - | - |
| PACU Admit | ✓ | ✓ | ✓ | - | - |
| PACU Assess | - | - | ✓ | - | - |
| PACU Discharge Sign | ✓ | - | - | - | - |
| Close Case | ✓ | - | - | - | - |

---

## 10. Implementation Roadmap

### Phase A: Core Event Stream ✅ COMPLETED (2025-12-30)

**Goal:** Basic intraop documentation with append-only events

| Task | Status |
|------|--------|
| Schema: `anesthesia_cases`, `anesthesia_events` | ✅ Done |
| API: Case CRUD, Event POST (27 endpoints) | ✅ Done |
| PWA: `/anesthesia` timeline view | ✅ Done |
| UI: One-tap vitals grid | ✅ Done |
| UI: Medication quick-buttons (10 drugs) | ✅ Done |
| Battlefield preop mode (5 quick flags) | ✅ Done |
| WAL integration (offline sync queue) | ✅ Done |
| UI: Heroicons + Grayscale theme | ✅ Done |

**Delivered:**
- Create case, add events, view timeline
- Vitals and medications recordable
- Works offline with localStorage queue, syncs when online
- Grayscale UI with purple-pink (fuchsia) for controlled drugs
- All emojis replaced with Heroicons SVG

### Phase B: Controlled Drugs 🚧 NEXT

**Goal:** Drug ledger with balance tracking and dual-control enforcement

| Task | Priority |
|------|----------|
| Schema: `drug_requests`, `drug_transactions` | High |
| API: Drug request/tx/holdings | High |
| UI: Drug panel with balance display | High |
| Dual-control enforcement | High |
| Offline proof upload | Medium |
| Pharmacy integration | Medium |

**Deliverables:**
- Drug ledger with balance tracking
- Block case close if balance ≠ 0
- Witness requirement for WASTE
- Integration with existing pharmacy module

### Phase C: Resource Coupling + PACU (1 Week)

| Task | Days |
|------|------|
| O2 cylinder claim API | 1 |
| O2 minutes estimation | 1 |
| UI: O2 status in header | 0.5 |
| Schema: `pacu_assessments` | 0.5 |
| API: PACU endpoints | 1 |
| UI: PACU dashboard | 2 |

**Deliverables:**
- Claim O2 cylinder by barcode
- Real-time O2 remaining estimate
- PACU admit/assess/discharge flow

### Phase D: Signatures + Polish (1 Week)

| Task | Days |
|------|------|
| Anesthesia Doctor PWA | 2 |
| Digital signature flow | 2 |
| Reports: Case summary, Drug reconciliation | 2 |
| Edge case handling | 1 |

**Deliverables:**
- Doctor PWA with signing
- Printable case summary
- Drug reconciliation report

---

## 11. Dependencies & Future Work

### 11.1 Dependencies

| Dependency | Status | Impact |
|------------|--------|--------|
| `surgery_cases` table | To be created | Case linkage |
| Equipment module O2 cylinders | Exists | Claim integration |
| Pharmacy drug inventory | Exists | Drug request workflow |
| WAL sync engine | Exists | Offline sync |

### 11.2 Out of Scope (Future Dev Specs)

| Topic | Why Deferred |
|-------|--------------|
| **MIRS Station Management** | Needs separate spec; Anesthesia uses "claim" model instead |
| **Automated Monitor Integration** | Requires hardware; Phase 2 consideration |
| **Hash Chain / Merkle Tree** | Nice-to-have for audit; not MVP critical |
| **Full PKI for Signatures** | Current approach uses session-bound keys |

---

## 12. Appendix: Migration from Handwritten Records

### 12.1 Parallel Operation Mode

During transition, system supports:

```
┌─────────────────────────────────────────────────────────────┐
│                    HYBRID MODE                               │
├─────────────────────────────────────────────────────────────┤
│ Option A: Digital-first                                      │
│   Nurse enters events in real-time on tablet                │
│                                                              │
│ Option B: Paper-first                                        │
│   Nurse handwrites → After surgery, photo upload as          │
│   offline_proof_artifact → Events entered retrospectively    │
│                                                              │
│ Option C: Minimal Digital                                    │
│   Only critical events (drug tx) entered digitally           │
│   Full record uploaded as PDF attachment                     │
└─────────────────────────────────────────────────────────────┘
```

### 12.2 Required Staff Training

| Role | Training Focus | Duration |
|------|----------------|----------|
| ANES_MD | Doctor PWA signing, case closure | 30 min |
| ANES_NA | Timeline entry, drug recording, O2 claim | 2 hrs |
| PACU_RN | PACU dashboard, Aldrete entry | 1 hr |
| PHARMACY | Drug request queue | 30 min |

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*Version: 1.5.1*
*Last Updated: 2025-12-30*
*Status: Phase A Complete, Ready for Phase B*

---

## UI Design Notes (v1.5.1)

### Color Palette

- **Primary Grayscale:**
  - `--primary: #64748b` (slate-500)
  - `--primary-dark: #475569` (slate-600)
  - Background: `#0f172a` (dark navy)
  - Cards: `#1e293b` (slate-800)

- **Controlled Drugs (Fuchsia/Purple-Pink):**
  - `--controlled: #c026d3` (fuchsia-600)
  - `--controlled-dark: #a21caf` (fuchsia-700)

### Icons

All icons use Heroicons (outline style) via inline SVG. No emoji usage.
