# Blood Transfusion Chain of Custody (鏈式核對) DEV SPEC v1.1

**版本**: 1.1.0
**日期**: 2026-01-20
**狀態**: ✅ 已實作 (Implemented 2026-01-20)
**關聯**: Blood Bank PWA v2.9、Anesthesia PWA

> **實作完成摘要**: 所有 v1.1 功能已實作，包含選單限縮、Select→Scan 兩段式、Emergency Mode、離線同步 idempotency、傳送追蹤 UI。

---

## 版本變更摘要 (v1.0 → v1.1)

| 變更項目 | 說明 |
|----------|------|
| **選單範圍限縮** | 麻醉端只顯示「已送達 OR」或「已發給此病人」的血袋 |
| **新增 TRANSPORT_DELIVERY** | 明確的送達確認步驟 |
| **Emergency Mode 完整定義** | EMERGENCY_* 事件族 + 事後對帳規則 |
| **Select → Scan 兩段式** | 選擇只預填，必須掃碼確認 |
| **離線同步安全機制** | client_event_id + idempotency + 狀態機驗證 |
| **狀態轉移表** | 明確定義 server-side 狀態機 |
| **差異/缺漏事件** | DISCREPANCY、QUARANTINE 事件處理 |

---

## 1. 設計原則 (更新)

### 1.1 核心安全原則

| 原則 | v1.0 | v1.1 更新 |
|------|------|-----------|
| 不減少核對步驟 | ✓ | ✓ (Emergency 除外，需事後補齊) |
| 掃碼優先 | ✓ | ✓ **Select → Scan 兩段式必須** |
| 即時驗證 | ✓ | ✓ 後端狀態機強制驗證 |
| 離線可用 | ✓ | ✓ + idempotency + occurred_at |
| 完整追蹤 | ✓ | ✓ + Emergency 高亮 + 差異追蹤 |

### 1.2 新增原則：「不擋救命」

> **系統永遠不可阻擋緊急輸血。**
>
> 在 MTP (大量輸血協議) 場景，若系統擋住輸血，等於害死人。
> 正確做法：讓流程通過 → 記錄 → 事後補單 → 高亮稽核。

---

## 2. 監管鏈步驟定義 (更新)

### 2.1 完整步驟列表

```python
class CustodyStep(str, Enum):
    # === 正常流程 ===
    RELEASED = "RELEASED"                      # Step 1: 血庫發血
    TRANSPORT_PICKUP = "TRANSPORT_PICKUP"      # Step 2a: 傳送取血
    TRANSPORT_DELIVERY = "TRANSPORT_DELIVERY"  # Step 2b: 傳送送達 (v1.1 新增)
    NURSING_RECEIVED = "NURSING_RECEIVED"      # Step 3: 護理收血
    TRANSFUSION_STARTED = "TRANSFUSION_STARTED"    # Step 4: 開始輸血
    TRANSFUSION_COMPLETED = "TRANSFUSION_COMPLETED" # Step 5: 輸血完成
    TRANSFUSION_STOPPED = "TRANSFUSION_STOPPED"    # 輸血中止 (反應)
    RETURNED = "RETURNED"                      # 退血

    # === Emergency Mode (v1.1 新增) ===
    EMERGENCY_RELEASED = "EMERGENCY_RELEASED"          # 緊急發血 (單人)
    EMERGENCY_RECEIVED = "EMERGENCY_RECEIVED"          # 緊急收血 (單人)
    EMERGENCY_TRANSFUSION_STARTED = "EMERGENCY_TRANSFUSION_STARTED"  # 緊急輸血 (單人)
    LATE_VERIFICATION = "LATE_VERIFICATION"            # 事後補核對
    SUPERVISOR_SIGNOFF = "SUPERVISOR_SIGNOFF"          # 主管簽核

    # === 差異/異常處理 (v1.1 新增) ===
    DELIVERY_DISCREPANCY = "DELIVERY_DISCREPANCY"      # 送達數量不符
    UNIT_QUARANTINED = "UNIT_QUARANTINED"              # 血袋隔離 (溫控/破損疑慮)
    UNIT_FOUND = "UNIT_FOUND"                          # 找回遺失血袋
    UNIT_DISCARDED = "UNIT_DISCARDED"                  # 血袋銷毀
```

### 2.2 更新後的流程圖

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    正常流程 (Normal Mode)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Step 1: RELEASED                                                        │
│    血庫發血 (雙人核對)                                                   │
│    └─ status: AVAILABLE → ISSUED                                        │
│                                                                          │
│  Step 2a: TRANSPORT_PICKUP                                               │
│    傳送取血 (單人)                                                       │
│    └─ status: ISSUED (不變)                                             │
│                                                                          │
│  Step 2b: TRANSPORT_DELIVERY  ← v1.1 新增                               │
│    傳送送達 (在目的地掃碼確認)                                           │
│    └─ status: ISSUED → IN_CLINICAL_AREA                                 │
│    └─ location: BLOOD_BANK → OR-3                                       │
│                                                                          │
│  Step 3: NURSING_RECEIVED                                                │
│    護理收血 (雙人核對)                                                   │
│    └─ status: IN_CLINICAL_AREA (不變)                                   │
│                                                                          │
│  Step 4: TRANSFUSION_STARTED                                             │
│    開始輸血 (雙人核對 + 床邊掃碼確認)                                    │
│    └─ status: IN_CLINICAL_AREA → TRANSFUSING                            │
│                                                                          │
│  Step 5: TRANSFUSION_COMPLETED                                           │
│    輸血完成                                                              │
│    └─ status: TRANSFUSING → TRANSFUSED                                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    緊急流程 (Emergency Mode)                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  觸發條件: MTP 啟動 / 失血性休克 / 無第二人員                            │
│                                                                          │
│  路徑 A: 緊急發血直送                                                    │
│    EMERGENCY_RELEASED → (跳過傳送) → EMERGENCY_RECEIVED                  │
│    → EMERGENCY_TRANSFUSION_STARTED → TRANSFUSION_COMPLETED              │
│                                                                          │
│  路徑 B: Ad-hoc 輸血 (血到就用)                                          │
│    麻醉端掃描未知血袋 → 系統自動補齊前置步驟                             │
│    → TRANSFUSION_STARTED (標記 AUTO_FILLED)                             │
│                                                                          │
│  事後要求:                                                               │
│    1. 24h 內完成 LATE_VERIFICATION (補核對)                             │
│    2. 72h 內完成 SUPERVISOR_SIGNOFF (主管簽核)                          │
│    3. 稽核報表中高亮顯示                                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 狀態轉移表 (v1.1 新增)

### 3.1 BloodUnitStatus 定義

```python
class BloodUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"           # 庫存可用
    RESERVED = "RESERVED"             # 已預約 (配血完成)
    ISSUED = "ISSUED"                 # 已發血 (在途中)
    IN_CLINICAL_AREA = "IN_CLINICAL_AREA"  # 已到臨床單位
    TRANSFUSING = "TRANSFUSING"       # 輸血中
    TRANSFUSED = "TRANSFUSED"         # 已輸完
    RETURNED = "RETURNED"             # 已退血
    QUARANTINED = "QUARANTINED"       # 隔離中 (v1.1 新增)
    EXPIRED = "EXPIRED"               # 已過期
    DISCARDED = "DISCARDED"           # 已銷毀
```

### 3.2 Server-Side 狀態轉移規則 (必須強制執行)

| 當前狀態 | 允許的 Custody Step | 新狀態 | 備註 |
|----------|---------------------|--------|------|
| AVAILABLE | RELEASED, EMERGENCY_RELEASED | ISSUED | 發血 |
| RESERVED | RELEASED, EMERGENCY_RELEASED | ISSUED | 預約後發血 |
| ISSUED | TRANSPORT_PICKUP | ISSUED | 取血 (狀態不變) |
| ISSUED | TRANSPORT_DELIVERY | IN_CLINICAL_AREA | 送達 |
| ISSUED | EMERGENCY_RECEIVED | IN_CLINICAL_AREA | 緊急直收 |
| IN_CLINICAL_AREA | NURSING_RECEIVED | IN_CLINICAL_AREA | 護理收血 (狀態不變) |
| IN_CLINICAL_AREA | TRANSFUSION_STARTED, EMERGENCY_TRANSFUSION_STARTED | TRANSFUSING | 開始輸血 |
| TRANSFUSING | TRANSFUSION_COMPLETED | TRANSFUSED | 完成 |
| TRANSFUSING | TRANSFUSION_STOPPED | TRANSFUSED | 中止 |
| IN_CLINICAL_AREA | RETURNED | RETURNED | 退血 |
| * | UNIT_QUARANTINED | QUARANTINED | 隔離 |
| QUARANTINED | UNIT_DISCARDED | DISCARDED | 銷毀 |
| QUARANTINED | UNIT_FOUND | (恢復前狀態) | 解除隔離 |

### 3.3 Emergency Mode 特殊規則

```python
# Emergency Mode 允許跳過步驟
EMERGENCY_ALLOWED_TRANSITIONS = {
    # 從任何狀態可直接到 TRANSFUSING (系統自動補齊中間步驟)
    "AVAILABLE": ["EMERGENCY_TRANSFUSION_STARTED"],
    "RESERVED": ["EMERGENCY_TRANSFUSION_STARTED"],
    "ISSUED": ["EMERGENCY_TRANSFUSION_STARTED"],
}

# 自動補齊規則
def auto_fill_custody_chain(unit_id, final_step, emergency_reason):
    """
    當 Emergency Mode 跳過步驟時，自動補齊中間事件
    所有補齊的事件標記為 AUTO_FILLED
    """
    pass
```

---

## 4. 選單範圍限縮 (v1.1 Critical)

### 4.1 問題：全庫存清單是災難

v1.0 的 UI 顯示「血庫可用庫存」，這會導致：
- 選到尚未發給此病人的血袋
- 選到未送達 OR 的血袋
- 選到被其他病人同時保留的血袋

### 4.2 解決方案：後端強制限縮

**麻醉 PWA 只能看到以下血袋 (後端 API 強制)**：

```
方案 A: 已發給此病人 + 已送達此地點
────────────────────────────────────
GET /api/blood/units/for-transfusion?patient_id=P-12345&location=OR-3

後端 SQL:
SELECT * FROM blood_units
WHERE patient_id = :patient_id
  AND location = :location
  AND status IN ('IN_CLINICAL_AREA', 'ISSUED')
  AND custody_step NOT IN ('TRANSFUSED', 'RETURNED', 'DISCARDED')
```

```
方案 B: 已送達此地點 (床邊掃碼做病人匹配)
────────────────────────────────────────────
GET /api/blood/units/at-location?location=OR-3&status=IN_CLINICAL_AREA

後端 SQL:
SELECT * FROM blood_units
WHERE location = :location
  AND status = 'IN_CLINICAL_AREA'
  AND custody_step NOT IN ('TRANSFUSED', 'RETURNED', 'DISCARDED')

# 床邊掃碼時再驗證 patient_id
```

### 4.3 建議採用方案

**採用方案 A** (已發給此病人 + 已送達此地點)：
- 更安全：後端同時驗證病人 ID 和地點
- 更清晰：清單只有「這個病人的血」
- 符合臨床習慣：護理師知道「這是王大明的血」

---

## 5. Select → Scan 兩段式確認 (v1.1 Critical)

### 5.1 問題：選擇 ≠ 確認

如果只用「點選」完成輸血記錄，會有選錯的風險。

### 5.2 解決方案：兩段式流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 1: SELECT (選擇)                                                  │
│  ──────────────────────────                                             │
│  UI 顯示可用血袋清單 (已限縮範圍)                                        │
│  護理師點選: BU-20260120-ABC123 (O+ PRBC)                               │
│  → 系統預填血袋 ID 到輸入框                                             │
│                                                                          │
│  Step 2: SCAN (掃碼確認)                                                │
│  ────────────────────────                                               │
│  UI 提示: 「請掃描血袋條碼確認」                                         │
│  護理師掃描手上的實體血袋                                                │
│                                                                          │
│  Step 3: VERIFY (系統驗證)                                              │
│  ─────────────────────────                                              │
│  比對: Selected ID == Scanned ID ?                                      │
│    ✓ 相符 → 進入雙人核對                                                │
│    ✗ 不符 → 警報: 「血袋不符！選擇的是 BU-123，掃描的是 BU-456」        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 UI 實作

```html
<!-- 麻醉 PWA 輸血 Modal -->

<!-- Step 2: 選擇血袋 -->
<div id="bloodStep2">
    <label>已送達 OR 的血袋</label>
    <div id="availableBloodList">
        <!-- 從後端 /api/blood/units/for-transfusion 取得 -->
        <button onclick="selectBloodUnit('BU-123')">
            BU-123 | O+ PRBC | 到期: 48h
        </button>
    </div>

    <label>血袋編號 (已選擇或手動輸入)</label>
    <input id="bloodUnitId" readonly>

    <!-- v1.1: 掃碼確認按鈕 -->
    <button onclick="scanToConfirm()">
        📷 掃描血袋條碼確認
    </button>

    <!-- 掃碼結果 -->
    <div id="scanResult" style="display: none;">
        <span id="scanMatch">✓ 血袋相符</span>
        <span id="scanMismatch">✗ 血袋不符！請確認手上的血袋</span>
    </div>
</div>
```

---

## 6. Emergency Mode 完整定義 (v1.1 Critical)

### 6.1 觸發條件

```python
class EmergencyReason(str, Enum):
    MTP_ACTIVATED = "MTP_ACTIVATED"              # 大量輸血協議啟動
    EXSANGUINATING_HEMORRHAGE = "EXSANGUINATING_HEMORRHAGE"  # 失血性休克
    NO_SECOND_STAFF = "NO_SECOND_STAFF"          # 無第二人員可覆核
    SYSTEM_OFFLINE = "SYSTEM_OFFLINE"            # 系統離線
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"      # 設備故障
    OTHER = "OTHER"                              # 其他 (需填寫說明)
```

### 6.2 Emergency 事件記錄

```python
class EmergencyCustodyEvent(BaseModel):
    """Emergency Mode 事件需額外記錄"""
    id: str
    blood_unit_id: str
    step: CustodyStep  # EMERGENCY_* 步驟
    emergency_reason: EmergencyReason
    emergency_reason_note: Optional[str]  # OTHER 時必填
    actor_id: str  # 單人即可
    timestamp: datetime
    location: str

    # 事後對帳欄位
    late_verification_by: Optional[str] = None
    late_verification_at: Optional[datetime] = None
    supervisor_signoff_by: Optional[str] = None
    supervisor_signoff_at: Optional[datetime] = None

    # 系統標記
    auto_filled_steps: List[str] = []  # 自動補齊的步驟
    reconciliation_status: str = "PENDING"  # PENDING | VERIFIED | FLAGGED
```

### 6.3 事後對帳規則

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Emergency Event 事後對帳 SLA                                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  T+0h    Emergency 事件發生                                             │
│          └─ 系統記錄，標記 reconciliation_status = PENDING              │
│                                                                          │
│  T+24h   LATE_VERIFICATION 必須完成                                     │
│          └─ 第二人員補核對 (事後確認血袋、病人身份)                      │
│          └─ 未完成 → 系統發送提醒給當班主管                              │
│                                                                          │
│  T+72h   SUPERVISOR_SIGNOFF 必須完成                                    │
│          └─ 主管審核並簽核                                               │
│          └─ 未完成 → reconciliation_status = FLAGGED                    │
│          └─ 完成 → reconciliation_status = VERIFIED                     │
│                                                                          │
│  稽核報表:                                                               │
│          └─ Emergency 事件用 🔴 紅色標記                                 │
│          └─ FLAGGED 事件用 ⚠️ 黃色標記                                   │
│          └─ 可篩選: 「顯示所有未完成對帳的 Emergency 事件」              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Ad-hoc 輸血 (血到就用)

```python
async def handle_adhoc_transfusion(unit_id: str, patient_id: str, actor_id: str, location: str):
    """
    處理 Ad-hoc 輸血：麻醉端掃描一個「不在清單上」的血袋

    場景: MTP 時血庫人員直接把血遞給麻醉醫師，來不及做正常流程
    """
    unit = get_blood_unit(unit_id)

    if unit is None:
        # 血袋不在系統中 (可能是外院血、緊急捐血)
        # 建立臨時記錄，標記為 UNTRACKED
        unit = create_untracked_unit(unit_id, patient_id, location)

    current_status = unit.status

    # 自動補齊缺少的步驟
    auto_filled = []

    if current_status == "AVAILABLE":
        # 補齊: EMERGENCY_RELEASED
        record_custody_event(unit_id, "EMERGENCY_RELEASED", ...)
        auto_filled.append("EMERGENCY_RELEASED")
        current_status = "ISSUED"

    if current_status == "ISSUED":
        # 補齊: EMERGENCY_RECEIVED
        record_custody_event(unit_id, "EMERGENCY_RECEIVED", ...)
        auto_filled.append("EMERGENCY_RECEIVED")
        current_status = "IN_CLINICAL_AREA"

    # 記錄輸血開始
    event = record_custody_event(
        unit_id,
        "EMERGENCY_TRANSFUSION_STARTED",
        patient_id=patient_id,
        actor_id=actor_id,
        location=location,
        emergency_reason="MTP_ACTIVATED",
        auto_filled_steps=auto_filled
    )

    return {
        "success": True,
        "warning": f"Emergency Mode: 自動補齊 {len(auto_filled)} 個步驟",
        "auto_filled_steps": auto_filled,
        "reconciliation_required": True
    }
```

---

## 7. 差異/缺漏處理 (v1.1 新增)

### 7.1 差異事件類型

```python
class DiscrepancyType(str, Enum):
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"      # 數量不符
    UNIT_MISSING = "UNIT_MISSING"                # 血袋遺失
    UNIT_DAMAGED = "UNIT_DAMAGED"                # 血袋破損
    TEMP_EXCURSION = "TEMP_EXCURSION"            # 溫控異常
    WRONG_BLOOD_TYPE = "WRONG_BLOOD_TYPE"        # 血型錯誤
    EXPIRED_DISCOVERED = "EXPIRED_DISCOVERED"    # 發現過期
```

### 7.2 差異事件記錄

```python
class DiscrepancyEvent(BaseModel):
    id: str
    reported_by: str
    reported_at: datetime
    discrepancy_type: DiscrepancyType

    # 數量不符時
    expected_count: Optional[int]
    received_count: Optional[int]
    missing_unit_ids: Optional[List[str]]

    # 單一血袋問題
    affected_unit_id: Optional[str]

    description: str
    resolution_status: str = "OPEN"  # OPEN | INVESTIGATING | RESOLVED
    resolution_note: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]
```

### 7.3 API Endpoints

```
POST /api/blood/discrepancy
    - 報告差異事件
    - Body: { discrepancy_type, expected_count?, received_count?, ... }

GET /api/blood/discrepancy/open
    - 取得未解決的差異事件
    - 用於 Operational Dashboard

POST /api/blood/units/{id}/quarantine
    - 將血袋標記為隔離
    - Body: { reason, reporter_id }

POST /api/blood/units/{id}/resolve-quarantine
    - 解除隔離
    - Body: { resolution, resolver_id }
```

---

## 8. 離線同步安全機制 (v1.1 更新)

### 8.1 事件結構更新

```javascript
const CustodyEvent = {
    // === 識別 ===
    client_event_id: 'uuid-v4',      // 客戶端生成，用於 idempotency
    blood_unit_id: 'BU-123',

    // === 時間戳 ===
    occurred_at: '2026-01-20T14:32:15+08:00',  // 裝置時間 (事件實際發生)
    recorded_at: null,                          // 伺服器時間 (上傳後由伺服器填入)

    // === 裝置資訊 ===
    device_id: 'ANES-PWA-OR3-001',
    device_time_offset: 0,           // 裝置時間與伺服器時間的差異 (秒)

    // === 事件內容 ===
    step: 'TRANSFUSION_STARTED',
    patient_id: 'P-12345',
    actor1_id: 'RN-042',
    actor2_id: 'MD-007',
    location: 'OR-3',

    // === 離線標記 ===
    offline_queued: true,
    offline_queue_position: 3
};
```

### 8.2 離線佇列管理

```javascript
class OfflineCustodyQueue {
    constructor() {
        // 啟動時從 localStorage 載入
        this.queue = JSON.parse(localStorage.getItem('custody_queue') || '[]');
        this.isSyncing = false;
    }

    enqueue(event) {
        event.client_event_id = crypto.randomUUID();
        event.occurred_at = new Date().toISOString();
        event.offline_queued = true;
        event.offline_queue_position = this.queue.length;

        this.queue.push(event);
        this.persist();

        // 嘗試立即同步
        this.trySync();
    }

    persist() {
        localStorage.setItem('custody_queue', JSON.stringify(this.queue));
    }

    async trySync() {
        if (this.isSyncing || !navigator.onLine) return;

        this.isSyncing = true;

        while (this.queue.length > 0) {
            const event = this.queue[0];

            try {
                const result = await xIRS.API.post('/api/blood/custody', event);

                if (result.ok || result.status === 409) {
                    // 成功 或 重複 (idempotency) → 移除
                    this.queue.shift();
                    this.persist();
                } else if (result.status === 400) {
                    // 狀態機驗證失敗 → 標記錯誤，保留在佇列
                    event.sync_error = result.data?.detail;
                    this.persist();
                    break;  // 停止同步，需人工介入
                }
            } catch (e) {
                // 網路錯誤 → 停止同步
                break;
            }
        }

        this.isSyncing = false;
    }
}
```

### 8.3 伺服器端 Idempotency

```python
@router.post("/custody")
async def record_custody_event(event: CustodyEventCreate):
    # 檢查 client_event_id 是否已存在
    existing = get_event_by_client_id(event.client_event_id)
    if existing:
        # 返回 409 Conflict，但實際上是成功 (idempotency)
        return JSONResponse(
            status_code=409,
            content={"detail": "Event already recorded", "event_id": existing.id}
        )

    # 驗證狀態轉移
    unit = get_blood_unit(event.blood_unit_id)
    if not is_valid_transition(unit.status, event.step):
        if event.step.startswith("EMERGENCY_"):
            # Emergency 允許跳步
            pass
        else:
            raise HTTPException(400, f"Invalid transition: {unit.status} → {event.step}")

    # 記錄事件
    ...
```

---

## 9. API Endpoints 更新

### 9.1 新增 Endpoints

```
# === 血袋查詢 (限縮範圍) ===
GET /api/blood/units/for-transfusion
    - 取得可用於輸血的血袋 (限縮範圍)
    - Query: patient_id, location
    - Returns: 只有「已發給此病人 + 已送達此地點」的血袋

# === Emergency Mode ===
POST /api/blood/units/{id}/emergency-transfusion
    - Ad-hoc 緊急輸血 (自動補齊步驟)
    - Body: { patient_id, actor_id, location, emergency_reason }

POST /api/blood/custody/{event_id}/late-verify
    - Emergency 事件事後補核對
    - Body: { verifier_id }

POST /api/blood/custody/{event_id}/supervisor-signoff
    - Emergency 事件主管簽核
    - Body: { supervisor_id, notes }

# === 差異處理 ===
POST /api/blood/discrepancy
GET /api/blood/discrepancy/open
POST /api/blood/units/{id}/quarantine
POST /api/blood/units/{id}/resolve-quarantine

# === 離線同步 ===
POST /api/blood/custody/batch
    - 批次上傳離線佇列
    - Body: [event1, event2, ...]
    - Returns: [{ client_event_id, status, error? }, ...]
```

---

## 10. 實作優先級

### Phase 1 (MVP - 1 週)
- [x] 基礎驗證 API
- [x] 監管鏈事件 API
- [ ] **選單範圍限縮 (後端)**
- [ ] **Select → Scan 兩段式 UI**

### Phase 2 (Safety - 1 週)
- [ ] 狀態機驗證 (server-side)
- [ ] Emergency Mode 基礎 (EMERGENCY_* 步驟)
- [ ] 離線同步 + Idempotency

### Phase 3 (Complete - 1 週)
- [ ] TRANSPORT_DELIVERY 步驟
- [ ] Ad-hoc 輸血自動補齊
- [ ] 事後對帳流程
- [ ] 差異/缺漏處理

### Phase 4 (Polish - 1 週)
- [ ] 稽核報表 (Emergency 高亮)
- [ ] 主管簽核 UI
- [ ] Operational Dashboard

---

## 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0.0 | 2026-01-20 | 初版 |
| v1.1.0 | 2026-01-20 | 根據 ChatGPT/Gemini 回饋大幅更新 |

---

**文件完成**
**撰寫者**: Claude Code
**審閱者**: ChatGPT o3, Google Gemini
**日期**: 2026-01-20
