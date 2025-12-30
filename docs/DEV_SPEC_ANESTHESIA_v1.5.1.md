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

**ADR-006: xIRS Unified vs Separate Architecture** ⚠️ PENDING DECISION

- **Context:** MIRS、CIRS、HIRS 目前為獨立系統，各自運行在不同 port
- **Status:** 待決定
- **Decision:** TBD

#### 現況（分開架構）

```
樹莓派 (192.168.4.1)
├── MIRS → :8000  (獨立 codebase: /MIRS-v2.0-single-station)
├── CIRS → :8001  (獨立 codebase: /CIRS)
└── HIRS → :8082  (獨立 codebase: /HIRS)

各系統獨立資料庫：
├── mirs.db
├── cirs.db
└── hirs.db
```

#### 方案 A：維持分開架構

| 優點 | 缺點 |
|------|------|
| 各系統獨立開發、部署 | 需維護多個 codebase |
| 模組化，可選擇性部署 | 跨系統資料同步複雜 |
| 單一系統故障不影響其他 | 病患資料可能不一致 |
| 適合不同團隊維護 | 部署腳本複雜（多服務） |

#### 方案 B：統一 xIRS 架構

```
┌─────────────────────────────────────────────────────────────┐
│  xIRS Unified Backend (單一進程)                             │
│  Port: 8000                                                  │
├─────────────────────────────────────────────────────────────┤
│  Routes:                                                     │
│  ├── /                     → Landing / Dashboard             │
│  ├── /cirs/triage          → 檢傷站 PWA                      │
│  ├── /cirs/registration    → 掛號站 PWA                      │
│  ├── /cirs/doctor          → 醫師站 PWA                      │
│  ├── /mirs/station         → 物資站 PWA                      │
│  ├── /mirs/admin           → 管理站 PWA                      │
│  ├── /anesthesia           → 麻醉站 PWA                      │
│  ├── /hirs/...             → HIRS PWAs                       │
│  └── /api/...              → 統一 API                        │
│                                                              │
│  Database: xirs_hub.db (單一資料庫)                          │
└─────────────────────────────────────────────────────────────┘
```

| 優點 | 缺點 |
|------|------|
| 單一 codebase，維護簡單 | 整合工作量大 |
| 統一資料庫，無同步問題 | 所有功能耦合 |
| 部署簡單（單一服務） | 單點故障風險 |
| 跨模組功能容易實作 | 需重構現有程式碼 |
| 病患資料一致性保證 | 啟動時間較長 |

#### 方案 C：Hub-Satellite 架構（混合）

```
┌─────────────────────────────────────────────────────────────┐
│  CIRS Hub (權威資料庫)                                       │
│  Port: 8001                                                  │
│  ├── 病患主檔 (patients)                                     │
│  ├── 掛號資料 (registrations)                                │
│  └── 處方資料 (prescriptions)                                │
└─────────────────────────────────────────────────────────────┘
              │
              │ Sync API (REST/WebSocket)
              ▼
┌─────────────────────────────────────────────────────────────┐
│  MIRS Satellite (本地資料 + 同步)                            │
│  Port: 8000                                                  │
│  ├── 物資管理 (local)                                        │
│  ├── 設備狀態 (local)                                        │
│  ├── 麻醉記錄 (local → sync to hub)                          │
│  └── 病患資料 (sync from hub)                                │
└─────────────────────────────────────────────────────────────┘
```

| 優點 | 缺點 |
|------|------|
| 各系統可獨立離線運作 | 同步邏輯複雜 |
| 資料權威性明確 | 衝突解決需設計 |
| 漸進式整合 | 需額外 sync service |
| 現有程式碼改動較小 | 延遲同步可能造成資料不一致 |

#### 決策考量因素

| 因素 | 傾向方案 A | 傾向方案 B | 傾向方案 C |
|------|-----------|-----------|-----------|
| 開發資源有限 | | ✓ | |
| 需快速部署 | ✓ | | |
| 強調資料一致性 | | ✓ | |
| 離線運作需求高 | ✓ | | ✓ |
| 長期維護考量 | | ✓ | |
| 現有系統已穩定 | ✓ | | ✓ |

#### 待決定事項

1. **短期（v1.5.x）**：麻醉模組先整合進 MIRS，維持 MIRS/CIRS 分開
2. **中期（v2.0）**：評估是否統一為 xIRS
3. **資料同步**：若維持分開，需設計 CIRS ↔ MIRS 病患資料同步機制

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

### 7.1 Architecture Decision: Single PWA with Role Switching

**ADR-005: 單一麻醉 PWA + 角色切換**

#### 問題背景

麻醉團隊包含兩種角色，各有不同權限：

| 任務 | 麻醉護士 (ANES_NA) | 麻醉醫師 (ANES_MD) |
|------|:------------------:|:------------------:|
| 記錄 Vitals / 用藥 / 事件 | ✓ | ✓ |
| 管制藥品給藥記錄 | ✓ | ✓ |
| 管制藥品廢棄 (actor) | ✓ | ✓ |
| 管制藥品廢棄見證 (witness) | ✓ | - |
| 氧氣瓶認領 | ✓ | ✓ |
| **術前評估核准** | - | ✓ |
| **案例 Sign-off** | - | ✓ |
| **管藥結算核准** | - | ✓ |
| **PACU 出院授權** | - | ✓ |

#### 方案評估

| 方案 | 說明 | 優點 | 缺點 |
|------|------|------|------|
| A. 擴充 Doctor PWA | 在 `/doctor` 加入麻醉功能 | 少維護一個 PWA | Doctor PWA 設計是給 CIRS 門診用，workflow 完全不同 |
| B. 獨立 Anesthesia Doctor PWA | 新增 `/anesthesia-doctor` | 專注麻醉流程 | 多一個 PWA 維護，醫師需切換兩個 App |
| **C. 單一 PWA + 角色切換** | `/anesthesia` 根據角色顯示不同功能 | 護士醫師共用一台平板，UX 一致 | 需實作角色切換機制 |

#### 決策：採用方案 C

**理由：**

1. **BORP 環境特性**
   - 團隊小（1 麻醉醫師 + 1-2 護士）
   - 可能共用同一台平板
   - 醫師有時也要幫忙記錄 vitals

2. **Workflow 連貫性**
   - 護士記錄 → 醫師核准 → 護士繼續記錄
   - 單一 PWA 避免切換 App 的中斷

3. **與 Doctor PWA 區隔**
   - `/doctor` = CIRS 門診看診、開處方
   - `/anesthesia` = BORP 手術室麻醉支援
   - 不同場景，不應混用

#### 後果

- 單一 `/anesthesia` PWA 維護
- 需實作 PIN-based 角色提升機制
- 敏感操作（sign-off）需重新驗證

---

### 7.2 Anesthesia PWA (`/anesthesia`) - Role-Based Design

**Purpose:** 麻醉團隊共用的術中記錄與管理介面

#### 7.2.1 角色切換機制

```
┌─────────────────────────────────────────────────────────────────────┐
│  /anesthesia PWA - Role Switching                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Header                                                       │    │
│  │  麻醉站  [目前角色: 👤 護士 ▼]  [🔄 同步]                    │    │
│  │                     ↓ 點擊展開                               │    │
│  │              ┌──────────────────┐                            │    │
│  │              │ 👤 護士模式      │ ← 預設                     │    │
│  │              │ 👨‍⚕️ 醫師模式 🔒  │ ← 需 PIN                   │    │
│  │              └──────────────────┘                            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 護士模式 (預設)                                              │    │
│  │                                                              │    │
│  │  功能：                                                      │    │
│  │  ✓ 建立案例 (從 CIRS 待診清單選取)                          │    │
│  │  ✓ 記錄 Vitals / 用藥 / 事件                                │    │
│  │  ✓ 管制藥品給藥記錄                                         │    │
│  │  ✓ 氧氣瓶認領與監控                                         │    │
│  │  ✓ 術前評估填寫 (無法核准)                                  │    │
│  │  ✓ 見證管藥廢棄                                             │    │
│  │                                                              │    │
│  │  限制：                                                      │    │
│  │  ✗ 術前評估核准 → 顯示「需醫師核准」                        │    │
│  │  ✗ 案例 Sign-off → 按鈕 disabled                            │    │
│  │  ✗ 管藥結算核准 → 按鈕 disabled                             │    │
│  │  ✗ PACU 出院授權 → 按鈕 disabled                            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 醫師模式 (PIN 驗證後)                                        │    │
│  │                                                              │    │
│  │  所有護士功能 +                                              │    │
│  │                                                              │    │
│  │  額外功能：                                                  │    │
│  │  ✓ 術前評估核准 (digital signature)                         │    │
│  │  ✓ 案例 Sign-off                                            │    │
│  │  ✓ 管藥結算核准                                             │    │
│  │  ✓ PACU 出院授權                                            │    │
│  │                                                              │    │
│  │  Session：                                                   │    │
│  │  - 5 分鐘無操作自動降級回護士模式                           │    │
│  │  - 敏感操作需重新輸入 PIN                                   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

#### 7.2.2 PIN 驗證機制

```typescript
// 角色提升流程
async function elevateToDoctor() {
    const pin = await showPinModal("請輸入醫師 PIN");

    const res = await fetch('/api/auth/verify-pin', {
        method: 'POST',
        body: JSON.stringify({ pin, role: 'ANES_MD' })
    });

    if (res.ok) {
        const { doctor_id, session_token, expires_at } = await res.json();
        currentRole = 'ANES_MD';
        doctorSession = { doctor_id, session_token, expires_at };
        updateUIForRole('ANES_MD');
        startSessionTimer(5 * 60 * 1000); // 5 min timeout
    } else {
        showError("PIN 錯誤");
    }
}

// 自動降級
function startSessionTimer(timeout) {
    sessionTimer = setTimeout(() => {
        currentRole = 'ANES_NA';
        doctorSession = null;
        updateUIForRole('ANES_NA');
        showToast("醫師 session 已過期，已切換回護士模式");
    }, timeout);
}

// 任何操作重置計時器
function resetSessionTimer() {
    if (currentRole === 'ANES_MD') {
        clearTimeout(sessionTimer);
        startSessionTimer(5 * 60 * 1000);
    }
}
```

#### 7.2.3 UI 差異對照

| UI 元素 | 護士模式 | 醫師模式 |
|---------|---------|---------|
| Header badge | `👤 護士` | `👨‍⚕️ 醫師 (Dr. 李)` |
| 術前評估 | 可編輯，「核准」按鈕 disabled | 可編輯 + 可核准 |
| 案例卡片 | 無 sign-off 按鈕 | 顯示 sign-off 按鈕 |
| 管藥結算 | 只能查看 | 可核准結算 |
| PACU 出院 | 只能查看 | 可授權出院 |
| Timeline | 記錄顯示 `by: 護士` | 記錄顯示 `by: Dr. 李` |

#### 7.2.4 安全考量

| 風險 | 緩解措施 |
|------|---------|
| 護士誤用醫師功能 | PIN 驗證 + 5 分鐘 session timeout |
| Session 被盜用 | 敏感操作 (sign-off) 需重新輸入 PIN |
| 平板遺失 | 無本地儲存醫師憑證，每次需重新驗證 |
| 離線時無法驗證 | 允許離線操作，但 sign-off 需上線後補驗 |

---

### 7.3 PWA Ecosystem Summary

| PWA | 路徑 | 用途 | 使用者 |
|-----|------|------|--------|
| **Anesthesia** | `/anesthesia` | 麻醉記錄、手術支援 | 麻醉護士 + 麻醉醫師 |
| Doctor | `/doctor` | CIRS 門診看診、開處方 | 一般醫師 |
| Admin | `/admin` | 系統管理、設定 | 管理員 |
| Pharmacy | `/pharmacy` | 藥品調劑、管藥核發 | 藥師 |
| Station | `/station` | 物資管理、設備掃描 | 站點人員 |

### 7.4 Existing PWA Modifications

| PWA | Modification |
|-----|--------------|
| `/admin` | Add Anesthesia module config |
| `/pharmacy` | Add drug request approval queue |
| `/station` | Add O2 cylinder barcode scanning |

### 7.5 Deployment Architecture

#### 7.5.1 Single Server Requirement

**重要：麻醉模組必須與 MIRS 主系統運行在同一伺服器/port 上。**

```
┌─────────────────────────────────────────────────────────────────┐
│  MIRS Backend (main.py) - Single Process                        │
│  Port: 8090 (or configured port)                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Routes:                                                         │
│  ├── /                     → MIRS 主頁面                         │
│  ├── /station              → Station PWA                         │
│  ├── /admin                → Admin PWA                           │
│  ├── /anesthesia           → Anesthesia PWA ← 新增               │
│  ├── /api/...              → MIRS API                            │
│  └── /api/anesthesia/...   → Anesthesia API ← 新增               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 7.5.2 常見錯誤

| 錯誤 | 原因 | 解決方案 |
|------|------|----------|
| `/anesthesia` 返回 404 | 舊版 MIRS (無麻醉模組) 仍在運行 | 停止所有舊進程，啟動新版 main.py |
| MIRS 連結到 `/anesthesia` 失敗 | 多個進程在不同 port 運行 | 統一使用單一 port |
| Raspberry Pi 部署後無法訪問 | 未更新 systemd service | 更新 service 指向新版 main.py |

#### 7.5.3 Raspberry Pi 部署

```bash
# 1. 停止舊服務
sudo systemctl stop mirs

# 2. 更新代碼
cd /opt/mirs
git pull origin v1.4.2-plus

# 3. 確認 service 文件指向正確的 main.py
# /etc/systemd/system/mirs.service
# ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8090

# 4. 重啟服務
sudo systemctl daemon-reload
sudo systemctl restart mirs

# 5. 驗證
curl http://localhost:8090/api/health
curl http://localhost:8090/anesthesia
```

#### 7.5.4 Vercel 部署注意事項

- Vercel Serverless 使用 ephemeral SQLite（每次部署重置）
- 案例資料不會持久化
- 正式環境需使用外部資料庫 (Turso, PlanetScale, Supabase)
- 404 錯誤處理已加入前端（自動返回案例列表）

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

### Phase B: Controlled Drugs ✅ COMPLETED (2025-12-30)

**Goal:** Drug ledger with balance tracking and dual-control enforcement

| Task | Status |
|------|--------|
| Schema: `drug_requests`, `drug_transactions` | ✅ Done |
| API: Drug request/tx/holdings (10+ endpoints) | ✅ Done |
| UI: 管藥 Tab with holdings display | ✅ Done |
| Dual-control enforcement (witness for WASTE) | ✅ Done |
| Balance validation (block close if ≠ 0) | ✅ Done |
| Transaction history log | ✅ Done |

**Delivered:**
- Drug ledger with balance tracking: `Balance = DISPENSE - (ADMIN + WASTE + RETURN)`
- Block case close if balance ≠ 0 via `/drugs/can-close` endpoint
- Witness requirement enforced for WASTE transactions
- Full transaction history with timestamps and actor/witness tracking
- Fuchsia/purple-pink color scheme for controlled drug UI elements

### Phase C: Resource Coupling + PACU 🚧 IN PROGRESS

| Task | Status |
|------|--------|
| O2 cylinder claim API | ✅ Done |
| O2 minutes estimation | ✅ Done |
| UI: O2 status in header | ✅ Done |
| Schema: `pacu_assessments` | Pending |
| API: PACU endpoints | Pending |
| UI: PACU dashboard | Pending |

**Delivered (O2 Claim - 2025-12-30):**
- Claim O2 cylinder via modal UI (click O2 in resource bar)
- Automatic estimation: est_minutes_remaining based on level% and flow rate
- Prevents double-claim (returns error if cylinder already in use)
- Release cylinder on case close or manual release

**Pending (PACU):**
- PACU admit/assess/discharge flow

### Phase D: Signatures + Polish

| Task | Priority |
|------|----------|
| Role switching (nurse/doctor) with PIN | High |
| Digital signature flow | High |
| Reports: Case summary, Drug reconciliation | Medium |
| Edge case handling | Medium |

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
| **CIRS Registration Integration** | ⚠️ NOT IMPLEMENTED | See 11.3 |

### 11.2 Out of Scope (Future Dev Specs)

| Topic | Why Deferred |
|-------|--------------|
| **MIRS Station Management** | Needs separate spec; Anesthesia uses "claim" model instead |
| **Automated Monitor Integration** | Requires hardware; Phase 2 consideration |
| **Hash Chain / Merkle Tree** | Nice-to-have for audit; not MVP critical |
| **Full PKI for Signatures** | Current approach uses session-bound keys |

### 11.3 CIRS Registration Integration (GAP ANALYSIS)

#### Current Status: ❌ NOT IMPLEMENTED

**問題描述:**
當 MIRS 麻醉站輸入病歷號建立案例時，目前**不會**與 CIRS 檢傷分類系統的掛號連結。

#### Reference: xIRS_REGISTRATION_SPEC_v1.2

根據 CIRS 已定義的掛號規格 (`/CIRS/docs/xIRS_REGISTRATION_SPEC_v1.0.md`)：

```
CIRS 掛號流程（已實作於 Doctor PWA）:
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. CIRS Admin 點擊「掛號」                                                  │
│     └── 產生 registrations record                                            │
│     └── 產生 QR Code (PATIENT_REGISTRATION payload)                          │
│                                                                              │
│  2. Doctor PWA 兩種方式取得病患：                                            │
│     ├── 掃描 QR Code → 自動帶入病患資料                                      │
│     └── GET /api/registrations/waiting/list → 同步待診清單                   │
│                                                                              │
│  3. 醫師 claim 病患後，其他醫師看不到                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Anesthesia Station 應採用相同模式

```
麻醉站 (建議實作):
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────────────────────────────────────┐ │
│  │ 新增案例 Modal  │    │                                                 │ │
│  ├─────────────────┤    │  待診病患清單 (從 CIRS 同步)                    │ │
│  │                 │    │  ┌───────────────────────────────────────────┐  │ │
│  │ ○ 從待診清單選取│───▶│  │ 🟡 ***0042 王小明 - 頭痛、發燒           │  │ │
│  │   (建議)        │    │  │    URGENT · 10:30 掛號              [選取]│  │ │
│  │                 │    │  ├───────────────────────────────────────────┤  │ │
│  │ ○ 掃描掛號 QR   │    │  │ 🟢 ***0088 李小華 - 腹部外傷              │  │ │
│  │                 │    │  │    ROUTINE · 10:45 掛號             [選取]│  │ │
│  │ ○ 手動輸入      │    │  └───────────────────────────────────────────┘  │ │
│  │   (緊急 fallback)    │                                                 │ │
│  └─────────────────┘    └─────────────────────────────────────────────────┘ │
│                                                                              │
│  選取後自動帶入：                                                            │
│  - patient_id (masked)                                                       │
│  - patient_name                                                              │
│  - chief_complaint                                                           │
│  - triage_level                                                              │
│  - registration_id (for linking)                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### API (已存在於 CIRS，麻醉站直接使用)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/registrations/waiting/list` | GET | 取得待診清單 (公開，無需授權) |
| `POST /api/registrations/{reg_id}/claim` | POST | Claim 病患 (避免重複選取) |

#### 麻醉站需要新增的邏輯

```python
# routes/anesthesia.py - 修改 create_case

class CreateCaseRequest(BaseModel):
    # 方式 1: 從掛號清單選取 (建議)
    registration_id: Optional[str] = None

    # 方式 2: 手動輸入 (fallback)
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None

    planned_technique: str
    context_mode: str = "STANDARD"

@router.post("/cases")
async def create_case(req: CreateCaseRequest, actor_id: str):
    if req.registration_id:
        # 從 CIRS 取得病患資料
        reg = await fetch_registration(req.registration_id)
        patient_id = reg['patient_ref']
        patient_name = reg['display_name']

        # Claim 病患，防止其他站重複選取
        await claim_registration(req.registration_id, "ANESTHESIA")
    else:
        # 手動輸入 (緊急情況)
        patient_id = req.patient_id
        patient_name = req.patient_name

    # 建立案例...
```

#### Frontend 修改 (New Case Modal)

```html
<!-- 新增案例 Modal - 病患來源選擇 -->
<div class="patient-source-tabs">
    <button class="tab active" onclick="showPatientList()">
        待診清單 (建議)
    </button>
    <button class="tab" onclick="showQrScanner()">
        掃描 QR
    </button>
    <button class="tab" onclick="showManualInput()">
        手動輸入
    </button>
</div>

<!-- 待診清單 View -->
<div id="patientListView">
    <!-- 從 /api/registrations/waiting/list 載入 -->
</div>

<!-- 手動輸入 View (hidden by default) -->
<div id="manualInputView" class="hidden">
    <input type="text" id="newPatientId" placeholder="病歷號">
    <input type="text" id="newPatientName" placeholder="姓名">
</div>
```

#### 結論：病歷號應自動帶入

| 場景 | 病歷號來源 | 實作方式 |
|------|-----------|----------|
| **正常流程** | CIRS 掛號系統 | 從待診清單選取，自動帶入 |
| **QR 掃描** | 掛號單 QR Code | 掃描後自動帶入 |
| **緊急 fallback** | 手動輸入 | 僅限網路斷線或系統故障時 |

**建議：預設隱藏手動輸入，引導使用者從清單選取。**

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
*Status: Phase A & B Complete, Ready for Phase C*

---

## UI Design Notes (v1.5.1)

### Color Palette

- **Primary (Indigo):**
  - `--primary: #6366f1` (indigo-500)
  - `--primary-dark: #4f46e5` (indigo-600)
  - Background: `#0f172a` (dark navy, suitable for low-light OR environment)
  - Cards: `#1e293b` (slate-800)

- **Controlled Drugs (Fuchsia/Purple-Pink):**
  - `--controlled: #c026d3` (fuchsia-600)
  - `--controlled-dark: #a21caf` (fuchsia-700)
  - Used for: 給藥 button, timeline medication dots, 管藥 tab (when active)

- **Status Colors (Grayscale - replacing yellow/red):**
  - `--warning: #a1a1aa` (zinc-400)
  - `--danger: #52525b` (zinc-600)

### Icons

All icons use Heroicons (outline style) via inline SVG. No emoji usage.

### Navigation UX

- Bottom nav tabs use `--text-muted` when inactive
- Active tab uses `--primary` (indigo)
- 管藥 tab uses `--controlled` (fuchsia) only when active, to avoid confusion with other tabs
