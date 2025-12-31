# xIRS Hub-Satellite Integration Plan v0.1

**Version:** 0.1
**Date:** 2025-12-31
**Status:** Active Development

---

## 0. Overview

### Goal
Keep MIRS and CIRS independently deployable (separate repos/ports/DBs) while enabling deterministic, auditable patient/registration synchronization under intermittent or zero connectivity.

### Non-Goal
- Immediate monorepo merge
- Single database unification
- Tightly coupled systems

### Systems Involved

| System | Role | Port | Repository |
|--------|------|------|------------|
| CIRS | Hub (Authority) | 8000 | github.com/cutemo0953/CIRS |
| MIRS | Satellite | 8090 | github.com/cutemo0953/MIRS-v2.0-single-station |
| HIRS | Optional | 8001 | github.com/cutemo0953/HIRS |

---

## 1. Authority Boundary Contract

This table defines who "owns" which data. Treat as **breaking-change guarded**.

| Data Type | System of Record | Sync Direction | Conflict Rule |
|-----------|-----------------|----------------|---------------|
| patients | CIRS Hub | Hub → Satellite | Hub wins |
| registrations | CIRS Hub | Hub → Satellite | Hub wins |
| prescriptions | CIRS Hub | Hub → Satellite | Hub wins |
| inventory | MIRS Satellite | Local only | N/A |
| equipment | MIRS Satellite | Local only | N/A |
| anesthesia | MIRS Satellite | Satellite → Hub | Satellite authoritative |
| controlled_drugs | MIRS Satellite | Satellite → Hub | Satellite authoritative (legal) |

---

## 2. xIRS-Contracts v1.0

### 2.1 Data Structures

```python
# Canonical schema - both ends must respect

class PatientStub(BaseModel):
    """Hub → Satellite: Patient basic info snapshot"""
    patient_id: str
    name: Optional[str] = None
    dob: Optional[str] = None
    sex: Optional[str] = None
    allergies: List[str] = []
    weight_kg: Optional[float] = None
    blood_type: Optional[str] = None
    hub_revision: int = 0

class RegistrationStub(BaseModel):
    """Hub → Satellite: Registration snapshot"""
    registration_id: str
    patient_id: Optional[str] = None
    triage_category: Optional[str] = None
    chief_complaint: Optional[str] = None
    status: str = "WAITING"
    hub_revision: int = 0

class EncounterLink(BaseModel):
    """Satellite → Hub: Case creation notification"""
    encounter_id: str
    registration_id: str
    station_id: str
    opened_at: str
    closed_at: Optional[str] = None

class TempRegistration(BaseModel):
    """Satellite: Offline identity placeholder"""
    temp_registration_id: str  # TMP-{ULID}
    patient_hint: str
    confidence: str = "LOW"
    created_at: str

class MergeMap(BaseModel):
    """Hub → Satellite: TempRegistration resolution"""
    mappings: Dict[str, str]  # {"TMP-xxx": "REG-yyy"}
    timestamp: str
```

### 2.2 Protocol Headers

All sync API responses must include:

| Header | Example | Description |
|--------|---------|-------------|
| `X-XIRS-Protocol-Version` | `1.0` | Contract version |
| `X-XIRS-Hub-Revision` | `1542` | Hub's latest revision |
| `X-XIRS-Station-Id` | `MIRS-BORP-01` | Requesting station |

### 2.3 Version Compatibility Matrix

| Hub Version | Satellite Version | Compatibility | Notes |
|-------------|-------------------|---------------|-------|
| 1.5.x | 1.5.x | ✅ Full | Patient Snapshot + Proxy |
| 1.6.x | 1.5.x | ⚠️ Partial | Satellite can't use TempReg merge |
| 1.6.x | 1.6.x | ✅ Full | Full Sync + TempRegistration |
| 2.0.x | 1.6.x | ✅ Backward | Hub supports legacy Satellite |

---

## 3. API Endpoints

### 3.1 CIRS Hub Endpoints

```
GET  /api/sync/bootstrap?sinceHubRevision=N
     → { hubTime, protocolVersion, patients[], registrations[] }

GET  /api/sync/pull?cursor=...
     → Incremental streaming/pagination

POST /api/sync/ops
     → Receive Satellite ops batch

POST /api/sync/resolve-temp
     → Resolve TempRegistration → MergeMap
```

### 3.2 MIRS Satellite Endpoints

```
GET  /api/anesthesia/proxy/cirs/waiting-list
     → Proxy to CIRS waiting list (with offline fallback)

GET  /api/anesthesia/proxy/cirs/patient/{id}
     → Fetch patient details from CIRS

GET  /api/anesthesia/hub/status
     → Hub connectivity status

POST /api/sync/push
     → Push pending ops to Hub
```

---

## 4. Offline Identity: TempRegistration

When Hub is unreachable and identity cannot be confirmed:

```
┌─────────────────────────────────────────────────┐
│  Satellite creates TempRegistration             │
│  temp_registration_id = "TMP-" + ULID           │
│  patient_hint = "男性約40歲，右腿骨折"           │
└─────────────────────────────────────────────────┘
              │
              │ All operations bind to temp_registration_id
              │
              ▼ (When connection recovers)
┌─────────────────────────────────────────────────┐
│  Satellite sends TEMP_REGISTRATION_SUBMIT       │
│  Hub returns MERGE_MAP:                         │
│  { "TMP-xxx": "REG-20251230-001" }              │
│                                                 │
│  Satellite uses alias table for reference       │
│  rebinding (non-destructive)                    │
└─────────────────────────────────────────────────┘
```

---

## 5. Deployment Topology

### 5.1 Service Architecture

```
┌─────────────────────────────────────────────────┐
│  Raspberry Pi (Hub-Satellite)                   │
│  ┌───────────┬───────────────┬────────────┐     │
│  │ CIRS:8000 │ MIRS:8090     │ HIRS:8001  │     │
│  │   (Hub)   │  (Satellite)  │ (Optional) │     │
│  └───────────┴───────────────┴────────────┘     │
└─────────────────────────────────────────────────┘
```

### 5.2 Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CIRS_HUB_URL` | `http://localhost:8000` | Hub connection URL |
| `MIRS_STATION_ID` | `MIRS-UNKNOWN` | Station identifier |

### 5.3 systemd Services

```bash
# CIRS Hub
sudo systemctl start cirs    # Port 8000

# MIRS Satellite
sudo systemctl start mirs    # Port 8090

# HIRS (Optional)
sudo systemctl start hirs    # Port 8001
```

---

## 6. Acceptance Tests

| Test | Condition | Expected |
|------|-----------|----------|
| 72-Hour Offline | Create TempReg + procedures → reconnect | Full sync, no data loss |
| Merge Correctness | Two TempRegs → same person | MergeMap correctly rebinds |
| Idempotency | Resend same ops batch | Hub state unchanged |
| QR Fallback | Hub completely unreachable | Scan QR to create case |
| Severed Cable | CIRS stops mid-case | MIRS continues with manual entry |
| Snapshot Retention | Delete patient from CIRS | MIRS case still shows patient info |

---

## 7. Roadmap

| Version | Target | Features |
|---------|--------|----------|
| v1.5.x | Current | CIRS Proxy + Patient Snapshot ✅ |
| v1.6.x | Q1 2026 | Full Sync API + TempRegistration |
| v2.0.x | Q2 2026 | Stable Hub-Satellite, 72h offline acceptance |

---

## 8. Related Documents

| Document | Location |
|----------|----------|
| MIRS Anesthesia Dev Spec | `MIRS-v2.0-single-station/docs/DEV_SPEC_ANESTHESIA_v1.5.1.md` |
| CIRS Dev Spec | `CIRS/CIRS_DEV_SPEC.md` |
| HIRS README | `HIRS/README.md` |
| RPi Deployment Guide | `MIRS-v2.0-single-station/RPi5_MIRS_安裝說明.md` |
| Hub-Satellite Tests | `MIRS-v2.0-single-station/tests/test_hub_satellite.py` |

---

## 9. Thinking Process Log

### 2025-12-31: Initial Integration

**Problem Statement:**
MIRS and CIRS were in different repos with different ports. User worried about turning MIRS into a "spoke" of CIRS without proper planning.

**Analysis:**
1. Consulted ChatGPT and Gemini for architecture recommendations
2. Both recommended Hub-Satellite over monorepo or complete separation
3. Key insight: Keep systems independently deployable while enabling sync

**Decisions Made:**
1. CIRS = Hub (port 8000) - Authority for patient identity
2. MIRS = Satellite (port 8090) - Authority for procedures
3. Use versioned contracts, not direct code imports
4. Implement patient snapshot for offline resilience

**Implementation:**
1. Created CIRS proxy endpoints in MIRS
2. Added patient_snapshot column to anesthesia_cases
3. Added protocol version headers (X-XIRS-Protocol-Version)
4. Created acceptance tests (9 tests, all passing)
5. Updated all documentation (CIRS, MIRS, HIRS, RPi guide)

**Validation:**
- Tested offline fallback: ✅ Works
- Tested protocol headers: ✅ Present
- Tested patient snapshot: ✅ Stored
- All backends running: ✅ Healthy

---

*Generated: 2025-12-31*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
