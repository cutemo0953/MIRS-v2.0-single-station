# MIRS Pharmacy Sub-Hub Dispatch Specification v1.1

**Version**: 1.1 (Hardened)
**Date**: 2025-12-23
**Status**: Ready for Implementation
**Target**: MIRS v1.4.3+
**Supersedes**: v1.0

---

## Changelog from v1.0

| Change | Rationale |
|--------|-----------|
| **Inventory Reservation** | Prevent overselling when multiple PENDING dispatches exist |
| **MED_RECEIPT Closed-loop** | MIRS can confirm stock arrived at sub-hub |
| **Mandatory Signature Verification** | Zero-trust security in offline scenarios |
| **Strict Target Binding** | Prevent diversion, especially for controlled drugs |
| **Idempotent Confirm/Receipt** | Safe retry under field stress |

---

## 1. Overview

### 1.1 Complete Flow (Closed-Loop)

```
┌───────────────────┐                    ┌────────────────────────┐
│  MIRS (Central)   │     MED_DISPATCH   │   xIRS Pharmacy PWA    │
│  藥品物資中心      │  ────────────────► │   Sub-Hub              │
│                   │      QR / USB      │                        │
│  ┌─────────────┐  │                    │  ┌────────────────┐   │
│  │ Stock: 1000 │  │     MED_RECEIPT    │  │ Receive +200   │   │
│  │ Reserved:200│  │  ◄──────────────── │  │ Local Inv: 200 │   │
│  │ Avail: 800  │  │      QR / USB      │  └────────────────┘   │
│  └─────────────┘  │                    │                        │
│                   │                    │                        │
│  Status: RECEIVED │                    │  Receipt Generated ✓   │
└───────────────────┘                    └────────────────────────┘
```

**Key Difference from v1.0**: Closed-loop with receipt confirmation.

---

## 2. Data Model

### 2.1 Dispatch Order (Updated)

```sql
CREATE TABLE pharmacy_dispatch_orders (
    dispatch_id TEXT PRIMARY KEY,           -- DISP-20251223-001
    created_at TEXT NOT NULL,               -- ISO timestamp
    created_by TEXT NOT NULL,               -- 操作人員

    -- Target Station (REQUIRED for controlled drugs)
    target_station_id TEXT,                 -- 目標站點 ID
    target_station_name TEXT,               -- 目標站點名稱
    target_unbound BOOLEAN DEFAULT FALSE,   -- 允許任何站接收 (非管制藥限定)

    -- Status
    status TEXT DEFAULT 'DRAFT',            -- DRAFT | RESERVED | DISPATCHED | RECEIVED | CANCELLED
    dispatch_method TEXT DEFAULT 'QR',      -- QR | USB | MANUAL

    -- Manifest
    total_items INTEGER NOT NULL,           -- 總品項數
    total_quantity INTEGER NOT NULL,        -- 總數量
    has_controlled BOOLEAN DEFAULT FALSE,   -- 含管制藥品

    -- Dispatch Tracking
    reserved_at TEXT,                       -- 保留庫存時間 (v1.1)
    dispatched_at TEXT,                     -- 實際發出時間
    dispatched_by TEXT,                     -- 發出操作員

    -- Receipt Tracking (v1.1 CLOSED-LOOP)
    received_at TEXT,                       -- 確認收到時間
    received_by TEXT,                       -- 收貨人
    receiver_station_id TEXT,               -- 實際收貨站點
    receipt_signature TEXT,                 -- 收貨回執簽章

    -- Metadata
    notes TEXT,
    signature TEXT,                         -- 發出方 Ed25519 簽章
    qr_chunks INTEGER DEFAULT 1
);

CREATE TABLE pharmacy_dispatch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_id TEXT NOT NULL,
    medicine_code TEXT NOT NULL,
    medicine_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,              -- 撥發數量
    reserved_qty INTEGER DEFAULT 0,         -- 已保留數量 (v1.1)
    unit TEXT DEFAULT '單位',
    batch_number TEXT,
    expiry_date TEXT,
    is_controlled BOOLEAN DEFAULT FALSE,

    FOREIGN KEY (dispatch_id) REFERENCES pharmacy_dispatch_orders(dispatch_id)
);

-- Status index for queries
CREATE INDEX idx_dispatch_status ON pharmacy_dispatch_orders(status);
CREATE INDEX idx_dispatch_target ON pharmacy_dispatch_orders(target_station_id);
CREATE INDEX idx_dispatch_controlled ON pharmacy_dispatch_orders(has_controlled);
```

### 2.2 Medication Inventory (Add reserved_qty)

```sql
-- Add to existing medication_inventory table
ALTER TABLE medication_inventory ADD COLUMN reserved_qty INTEGER DEFAULT 0;

-- Computed available quantity (for queries)
-- available = current_qty - reserved_qty
```

### 2.3 Dispatch Payload (MED_DISPATCH)

```json
{
  "type": "MED_DISPATCH",
  "v": "1.1",
  "dispatch_id": "DISP-20251223-001",
  "source_station": "MIRS-DNO-01",
  "target_station": "PHARM-SUB-01",
  "target_unbound": false,
  "items": [
    {
      "code": "MED-PARA-500",
      "name": "Paracetamol 500mg",
      "qty": 200,
      "unit": "tablets",
      "batch": "B2024001",
      "expiry": "2026-06",
      "controlled": false
    },
    {
      "code": "MED-MORP-10",
      "name": "Morphine 10mg",
      "qty": 20,
      "unit": "ampules",
      "batch": "C2024050",
      "expiry": "2025-12",
      "controlled": true
    }
  ],
  "total_items": 2,
  "total_qty": 220,
  "has_controlled": true,
  "ts": 1735012345,
  "nonce": "abc123def456789012345678",
  "signature": "<Ed25519 mandatory>"
}
```

### 2.4 Receipt Payload (MED_RECEIPT) - NEW in v1.1

```json
{
  "type": "MED_RECEIPT",
  "v": "1.0",
  "dispatch_id": "DISP-20251223-001",
  "receipt_id": "RCPT-20251223-001",
  "receiver_station": "PHARM-SUB-01",
  "received_by": "pharmacist001",
  "items_received": [
    { "code": "MED-PARA-500", "qty": 200, "status": "OK" },
    { "code": "MED-MORP-10", "qty": 20, "status": "OK" }
  ],
  "total_received": 220,
  "partial": false,
  "notes": null,
  "ts": 1735012500,
  "nonce": "def456abc789012345678901",
  "signature": "<Ed25519>"
}
```

---

## 3. Inventory Reservation Logic (v1.1 CRITICAL)

### 3.1 Available Quantity Calculation

```python
def get_available_qty(medicine_code: str) -> int:
    """Available = Current - Reserved"""
    med = db.query("SELECT current_qty, reserved_qty FROM medication_inventory WHERE code = ?", medicine_code)
    return med.current_qty - med.reserved_qty
```

### 3.2 State Transitions

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DISPATCH LIFECYCLE                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   [Create]              [Reserve]           [Confirm]    [Receipt]   │
│      │                     │                    │           │        │
│      ▼                     ▼                    ▼           ▼        │
│   ┌──────┐   validate   ┌────────┐  dispatch ┌──────────┐ ┌────────┐│
│   │DRAFT │ ───────────► │RESERVED│ ────────► │DISPATCHED│►│RECEIVED││
│   └──────┘   +reserve   └────────┘  -reserve └──────────┘ └────────┘│
│      │                     │        -deduct                          │
│      │    [Cancel]         │                                         │
│      ▼                     ▼                                         │
│   ┌─────────────────────────────┐                                   │
│   │         CANCELLED           │  (release reservation)            │
│   └─────────────────────────────┘                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 Reservation Operations

| Action | Inventory Effect |
|--------|------------------|
| Create DRAFT | None (no reservation yet) |
| Reserve (DRAFT→RESERVED) | `reserved_qty += dispatch_qty` |
| Confirm (RESERVED→DISPATCHED) | `reserved_qty -= dispatch_qty`, `current_qty -= dispatch_qty` |
| Cancel (any→CANCELLED) | `reserved_qty -= dispatch_qty` (if was RESERVED) |
| Receive (DISPATCHED→RECEIVED) | None (already deducted) |

---

## 4. API Endpoints (Updated)

### 4.1 Create Dispatch Order (DRAFT)

```http
POST /api/pharmacy/dispatch
Content-Type: application/json

{
  "items": [
    { "medicine_code": "MED-PARA-500", "quantity": 200 },
    { "medicine_code": "MED-MORP-10", "quantity": 20 }
  ],
  "target_station_id": "PHARM-SUB-01",
  "target_station_name": "前線藥局 A",
  "notes": "緊急補給",
  "created_by": "admin001"
}
```

**Validation:**
- If ANY item is controlled → `target_station_id` REQUIRED
- If `target_station_id` is null → `target_unbound` = true

**Response:**
```json
{
  "success": true,
  "dispatch_id": "DISP-20251223-001",
  "status": "DRAFT",
  "has_controlled": true,
  "message": "撥發單已建立 (草稿)"
}
```

### 4.2 Reserve Inventory (DRAFT→RESERVED)

```http
POST /api/pharmacy/dispatch/{dispatch_id}/reserve
```

**Logic:**
1. Validate available_qty >= dispatch_qty for each item
2. If insufficient: return error with shortage details
3. If OK: `reserved_qty += dispatch_qty` for each item
4. Status → RESERVED

**Response:**
```json
{
  "success": true,
  "dispatch_id": "DISP-20251223-001",
  "status": "RESERVED",
  "reserved_at": "2025-12-23T14:30:00Z",
  "message": "庫存已保留"
}
```

**Error (insufficient stock):**
```json
{
  "success": false,
  "error": "INSUFFICIENT_STOCK",
  "shortages": [
    { "code": "MED-MORP-10", "requested": 20, "available": 15, "shortage": 5 }
  ],
  "message": "庫存不足，無法保留"
}
```

### 4.3 Generate QR Codes (RESERVED only)

```http
GET /api/pharmacy/dispatch/{dispatch_id}/qr
```

**Precondition:** Status must be RESERVED or DISPATCHED

**Response:**
```json
{
  "dispatch_id": "DISP-20251223-001",
  "status": "RESERVED",
  "chunks": 2,
  "qr_data": [
    "XIR1|MF|1/2|eyJ0eXBlIjoiTUVE...|a1b2c3d4",
    "XIR1|MF|2/2|Li4ufSwic2lnbmF...|b2c3d4e5"
  ],
  "qr_images": [
    "data:image/png;base64,...",
    "data:image/png;base64,..."
  ]
}
```

### 4.4 Confirm Dispatched (RESERVED→DISPATCHED)

```http
POST /api/pharmacy/dispatch/{dispatch_id}/confirm
Content-Type: application/json

{
  "dispatched_by": "admin001"
}
```

**Logic (IDEMPOTENT):**
1. If already DISPATCHED: return success (no-op)
2. `reserved_qty -= dispatch_qty` for each item
3. `current_qty -= dispatch_qty` for each item
4. Status → DISPATCHED

**Response:**
```json
{
  "success": true,
  "dispatch_id": "DISP-20251223-001",
  "status": "DISPATCHED",
  "dispatched_at": "2025-12-23T14:45:00Z",
  "message": "已確認發出，庫存已扣除"
}
```

### 4.5 Ingest Receipt (DISPATCHED→RECEIVED) - NEW v1.1

```http
POST /api/pharmacy/dispatch/receipt
Content-Type: application/json

{
  "receipt_data": "XIR1|MF|1/1|eyJ0eXBlIjoiTUVEX1JFQ0V...|c3d4e5f6"
}
```

**Logic (IDEMPOTENT):**
1. Parse XIR1 receipt payload
2. Verify signature against trusted Pharmacy key
3. Validate dispatch_id exists and status is DISPATCHED
4. If already RECEIVED: return success (no-op)
5. Update: received_at, received_by, receiver_station_id, receipt_signature
6. Status → RECEIVED

**Response:**
```json
{
  "success": true,
  "dispatch_id": "DISP-20251223-001",
  "status": "RECEIVED",
  "received_at": "2025-12-23T15:00:00Z",
  "received_by": "pharmacist001",
  "receiver_station": "PHARM-SUB-01",
  "message": "收貨回執已確認"
}
```

### 4.6 Cancel Dispatch

```http
DELETE /api/pharmacy/dispatch/{dispatch_id}
```

**Logic:**
- Only allowed for DRAFT or RESERVED status
- If RESERVED: release `reserved_qty`
- Status → CANCELLED

---

## 5. Security Requirements (MANDATORY)

### 5.1 Signature Verification

| Scenario | Requirement |
|----------|-------------|
| MED_DISPATCH at Pharmacy PWA | **MUST verify** against trusted MIRS key |
| MED_RECEIPT at MIRS | **MUST verify** against trusted Pharmacy key |
| Verification fails | **REJECT immediately**, log to quarantine |

### 5.2 Quarantine Inbox

```javascript
// Pharmacy PWA - Mandatory verification
async processInventoryDispatch(dispatch) {
    // 1. Verify signature (MANDATORY)
    const isValid = await this.verifyDispatchSignature(dispatch);

    if (!isValid) {
        // DO NOT accept into inventory
        await this.saveToQuarantine(dispatch, 'SIGNATURE_INVALID');
        this.showError('簽章驗證失敗，資料已隔離待人工處理');
        return;
    }

    // 2. Verify target binding
    if (dispatch.target_station && dispatch.target_station !== this.myStationId) {
        await this.saveToQuarantine(dispatch, 'TARGET_MISMATCH');
        this.showError('此撥發單不是發給本站');
        return;
    }

    // 3. Proceed with acceptance
    await this.acceptDispatch(dispatch);
}
```

### 5.3 Target Binding Rules

| Condition | target_station_id | target_unbound | Pharmacy PWA Behavior |
|-----------|------------------|----------------|----------------------|
| Has controlled drugs | REQUIRED | false | Must match my station ID |
| No controlled drugs | Optional | true allowed | Accept if unbound=true |
| Mismatch | Any | Any | REJECT, save to quarantine |

---

## 6. Frontend UI Updates

### 6.1 Dispatch Modal (Updated Workflow)

```
┌─────────────────────────────────────────────────────────────────────┐
│  🏥 撥發藥品給 Pharmacy Sub-Hub                              [✕]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 1: 選擇目標站點                                                │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ [下拉選單] PHARM-SUB-01 - 前線藥局 A                         │    │
│  └─────────────────────────────────────────────────────────────┘    │
│  ⚠️ 含管制藥品時必須指定目標站點                                      │
│                                                                      │
│  Step 2: 選擇撥發藥品                                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ 藥品                  庫存  可用  撥發數量    管制   操作     │  │
│  ├───────────────────────────────────────────────────────────────┤  │
│  │ Paracetamol 500mg    1000  800  [___200__]   ○     [🗑️]     │  │
│  │ Morphine 10mg          50   30  [____20__]   ●     [🗑️]     │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  📊 摘要: 2 品項 / 220 單位 / ⚠️ 含管制藥 1 項                       │
│                                                                      │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐     │
│  │     取消       │  │  📝 建立草稿   │  │  🔒 保留並產生 QR  │     │
│  └────────────────┘  └────────────────┘  └────────────────────┘     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 QR Display + Confirm Modal

```
┌─────────────────────────────────────────────────────────────────────┐
│  ✅ 庫存已保留，準備撥發                                       [✕]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│              DISP-20251223-001                                       │
│              狀態: 🔒 已保留庫存                                     │
│                                                                      │
│           ┌──────────────────────┐                                   │
│           │                      │                                   │
│           │      [QR CODE]       │                                   │
│           │       250x250        │                                   │
│           │                      │                                   │
│           └──────────────────────┘                                   │
│                   1 / 2                                              │
│           [◀ 上一張]  [下一張 ▶]                                     │
│                                                                      │
│  ─────────────────────────────────────────────────────────────────   │
│                                                                      │
│  ⚠️ 請讓藥局人員掃描此 QR Code 後，點擊「確認已發出」                  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    ✅ 確認已發出 (扣除庫存)                     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    ❌ 取消撥發 (釋放保留)                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.3 Receipt Ingestion (MIRS側)

```
┌─────────────────────────────────────────────────────────────────────┐
│  📥 掃描收貨回執                                              [✕]   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                                                              │    │
│  │                    [Camera Scanner]                          │    │
│  │                                                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  或貼上回執 QR 內容:                                                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ XIR1|MF|1/1|...                                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      確認匯入回執                             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Pharmacy PWA Receiver Flow (Updated)

### 7.1 Accept Dispatch

```javascript
async acceptDispatch(dispatch) {
    // 1. Check for duplicate (replay protection)
    const existing = await this.db.get('received_dispatches', dispatch.dispatch_id);
    if (existing) {
        this.showError('此撥發單已接收過');
        return;
    }

    // 2. Add items to local inventory
    for (const item of dispatch.items) {
        await this.addToInventory(item);
    }

    // 3. Record as received
    await this.db.put('received_dispatches', {
        dispatch_id: dispatch.dispatch_id,
        received_at: new Date().toISOString(),
        received_by: this.currentUser,
        items: dispatch.items
    });

    // 4. Generate receipt QR
    const receipt = await this.generateReceipt(dispatch);
    this.showReceiptQR(receipt);
}
```

### 7.2 Generate Receipt QR

```javascript
async generateReceipt(dispatch) {
    const receipt = {
        type: 'MED_RECEIPT',
        v: '1.0',
        dispatch_id: dispatch.dispatch_id,
        receipt_id: `RCPT-${this.generateId()}`,
        receiver_station: this.myStationId,
        received_by: this.currentUser,
        items_received: dispatch.items.map(i => ({
            code: i.code,
            qty: i.qty,
            status: 'OK'
        })),
        total_received: dispatch.total_qty,
        partial: false,
        ts: Math.floor(Date.now() / 1000),
        nonce: this.generateNonce()
    };

    // Sign with station's Ed25519 key
    receipt.signature = await this.sign(receipt);

    // Generate XIR1 QR
    const { chunks, dataURLs } = await xIRS.QRProtocol.generateAndRender('MF', receipt);
    return { receipt, chunks, dataURLs };
}
```

---

## 8. Implementation Checklist (v1.1)

### Phase 1: Database Schema

- [ ] Add `reserved_qty` to `medication_inventory`
- [ ] Update `pharmacy_dispatch_orders` with new columns
- [ ] Add `pharmacy_dispatch_items.reserved_qty`
- [ ] Create indexes

### Phase 2: MIRS Backend API

- [ ] `POST /dispatch` - Create DRAFT
- [ ] `POST /dispatch/{id}/reserve` - Reserve inventory
- [ ] `GET /dispatch/{id}/qr` - Get QR codes
- [ ] `POST /dispatch/{id}/confirm` - Confirm & deduct (idempotent)
- [ ] `POST /dispatch/receipt` - Ingest receipt QR
- [ ] `DELETE /dispatch/{id}` - Cancel & release
- [ ] `GET /dispatch` - List with status filter

### Phase 3: MIRS Frontend

- [ ] Add "撥發給藥局" button
- [ ] Dispatch modal with target selection
- [ ] Show "可用庫存" (current - reserved)
- [ ] Two-step: Draft → Reserve → QR
- [ ] Confirm dispatch action
- [ ] Receipt scanner modal

### Phase 4: xIRS Pharmacy PWA

- [ ] Handle `MED_DISPATCH` type
- [ ] **Mandatory** signature verification
- [ ] **Mandatory** target binding check
- [ ] Quarantine inbox for failed validation
- [ ] Add to local inventory on accept
- [ ] Generate `MED_RECEIPT` QR
- [ ] Track received dispatches (replay protection)

### Phase 5: Protocol Updates

- [ ] Add `MED_RECEIPT` to xirs-protocol.js packet types
- [ ] Add receipt generation to xirs-qr.js

---

## 9. Error Handling Summary

| Error | HTTP | User Message |
|-------|------|--------------|
| Insufficient stock | 409 | 庫存不足，無法保留 |
| Already reserved | 409 | 此撥發單已保留 |
| Already dispatched | 200 | (Idempotent OK) |
| Already received | 200 | (Idempotent OK) |
| Controlled drug without target | 400 | 管制藥品必須指定目標站點 |
| Invalid status transition | 400 | 狀態不允許此操作 |
| Signature invalid | 401 | 簽章驗證失敗 |
| Target mismatch | 403 | 此撥發單不是發給本站 |
| Dispatch not found | 404 | 找不到撥發單 |

---

## 10. Summary: v1.0 vs v1.1

| Feature | v1.0 | v1.1 |
|---------|------|------|
| Inventory deduction | On confirm only | Reserve on draft, deduct on confirm |
| Overselling protection | ❌ None | ✅ Reservation system |
| Closed-loop receipt | ❌ Future | ✅ MED_RECEIPT mandatory |
| Signature verification | Optional offline | ✅ Mandatory, quarantine on fail |
| Target binding | Optional | ✅ Mandatory for controlled drugs |
| Idempotent operations | Not specified | ✅ Confirm & Receipt idempotent |
| Status transitions | 3 states | 5 states (DRAFT→RESERVED→DISPATCHED→RECEIVED) |

---

**This spec is ready for implementation.**
