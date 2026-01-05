# EMT Transfer Handoff 開發規格書

**版本**: 1.0
**日期**: 2026-01-05
**狀態**: Draft
**依賴**: DEV_SPEC_EMT_TRANSFER_PWA.md v2.2.4

---

## 0. 摘要

本規格書描述 CIRS Doctor PWA 與 MIRS EMT Transfer PWA 之間的**快速交班**功能。

### 使用情境

```
┌──────────────────┐      交班請求      ┌──────────────────┐
│  CIRS Doctor     │ ───────────────▶  │  MIRS EMT PWA    │
│  (醫師站)         │                    │  (轉送模組)       │
│                  │   ◀──────────────  │                  │
│  「需要轉送」     │      接收確認       │  「接收交班」     │
└──────────────────┘                    └──────────────────┘
```

### 核心需求

| 需求 | 說明 | 來源 |
|------|------|------|
| **O2 流量預設值** | 無/3/6/10/15 L/min 快選按鈕 | EMT 實務回饋 |
| **快速交班** | Doctor PWA 一鍵發起轉送請求 | EMT 實務回饋 |
| **手動模式** | 保留非掛號病患的手動輸入 | 現有功能 |
| **交班備註** | 自由文字欄位記錄交班事項 | EMT 實務回饋 |

---

## 1. O2 流量預設值更新

### 1.1 現有設計

目前 EMT PWA 的 O2 流量為自由輸入欄位 (`o2_lpm: REAL`)。

### 1.2 更新設計

改為**快選按鈕 + 自訂輸入**：

```
┌─────────────────────────────────────────────────────────────┐
│ 氧氣流量 (L/min)                                            │
├─────────────────────────────────────────────────────────────┤
│ [無] [3] [6] [10] [15] [自訂: ___]                          │
│  ○    ○   ●    ○    ○                                       │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 O2 流量對照表

| 選項 | L/min | 適用情境 |
|------|-------|----------|
| 無 | 0 | 無氧氣需求 |
| 3 | 3 | 鼻導管低流量 |
| 6 | 6 | 鼻導管中流量 |
| 10 | 10 | 面罩 / NRB |
| 15 | 15 | NRB 高流量 / BVM |
| 自訂 | N | 特殊需求（如 1, 2, 4, 8 等） |

### 1.4 UI 元件

```html
<!-- O2 流量快選 -->
<div class="flex flex-wrap gap-2">
    <template x-for="opt in [{v:0,l:'無'},{v:3,l:'3'},{v:6,l:'6'},{v:10,l:'10'},{v:15,l:'15'}]">
        <button @click="setO2Flow(opt.v)"
                :class="o2_lpm === opt.v ? 'bg-amber-500 text-white' : 'bg-amber-100 text-amber-700'"
                class="px-4 py-2 rounded-full text-sm font-medium">
            <span x-text="opt.l"></span>
        </button>
    </template>
    <button @click="showO2Custom = !showO2Custom"
            :class="showO2Custom ? 'bg-amber-500 text-white' : 'bg-amber-100 text-amber-700'"
            class="px-4 py-2 rounded-full text-sm font-medium">
        自訂
    </button>
</div>
<div x-show="showO2Custom" class="mt-2">
    <input type="number" x-model.number="o2_lpm"
           class="w-24 px-3 py-2 border rounded-lg" placeholder="L/min">
</div>
```

---

## 2. CIRS Doctor PWA 轉送按鈕

### 2.1 按鈕位置

在醫師完成看診後的動作選單中新增「需要轉送」按鈕：

```
┌─────────────────────────────────────────────────────────────┐
│ 完成看診                                                     │
├─────────────────────────────────────────────────────────────┤
│ 此病患需要：                                                 │
│                                                             │
│ [✓] 需處置        [開立處置單]                              │
│ [✓] 需麻醉        [轉介麻醉科]                              │
│ [✓] 需轉送        [發起轉送]  ← 新增                        │
│                                                             │
│ 轉送備註：                                                   │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 右股骨骨折，已固定，需轉後送醫院手術                       │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│                            [取消] [完成看診]                 │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 按鈕樣式

使用 MIRS/EMT 橘紅色系：

```css
/* 轉送按鈕配色 (同 MIRS amber) */
.btn-transfer {
    background-color: #f59e0b; /* amber-500 */
    color: white;
}
.btn-transfer:hover {
    background-color: #d97706; /* amber-600 */
}
```

### 2.3 勾選「需轉送」後的 UI

```
┌─────────────────────────────────────────────────────────────┐
│ [✓] 需轉送                                                   │
├─────────────────────────────────────────────────────────────┤
│ 目的地：                                                     │
│ ○ 後送醫院 (預設)                                           │
│ ○ 其他站點                                                   │
│ ○ 自訂: [________________]                                   │
│                                                             │
│ 預估 ETA：                                                   │
│ [30] [60] [90] [120] 分鐘  或 自訂: [___] 分鐘              │
│                                                             │
│ 初步 O2 需求：                                               │
│ [無] [3] [6] [10] [15] L/min                                │
│                                                             │
│ 病患狀態：                                                   │
│ ○ 穩定 (STABLE)                                              │
│ ● 需監測 (MONITORED)                                         │
│ ○ 危急 (CRITICAL)                                            │
│                                                             │
│ 交班備註：                                                   │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ (醫師填寫重要交班事項)                                    │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 資料模型

### 3.1 CIRS 端：transfer_requests 表

```sql
CREATE TABLE transfer_requests (
    request_id TEXT PRIMARY KEY,          -- 'TREQ-YYYYMMDD-NNN'
    registration_id TEXT NOT NULL,        -- FK → registrations
    person_id TEXT NOT NULL,              -- FK → persons

    -- 來源資訊
    requesting_doctor_id TEXT,            -- 發起醫師 ID
    requesting_doctor_name TEXT,          -- 醫師姓名 (denormalized)
    origin_station_id TEXT,               -- 出發站點

    -- 目的地
    destination_type TEXT DEFAULT 'HOSPITAL', -- HOSPITAL/STATION/CUSTOM
    destination_text TEXT,                -- 目的地描述

    -- 初步評估
    eta_min INTEGER,                      -- 預估時間 (分鐘)
    o2_lpm REAL DEFAULT 0,                -- 初步 O2 需求
    patient_status TEXT DEFAULT 'STABLE', -- STABLE/MONITORED/CRITICAL

    -- 交班備註
    handoff_notes TEXT,                   -- 自由文字

    -- 狀態
    status TEXT DEFAULT 'PENDING',        -- PENDING/ACCEPTED/IN_PROGRESS/COMPLETED/CANCELLED

    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accepted_at TIMESTAMP,
    accepted_by TEXT,                     -- EMT 姓名
    mirs_mission_id TEXT,                 -- 對應的 MIRS 任務 ID

    -- 審計
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_transfer_requests_status ON transfer_requests(status);
CREATE INDEX idx_transfer_requests_person ON transfer_requests(person_id);
```

### 3.2 MIRS 端：transfer_missions 更新

在現有 `transfer_missions` 表新增欄位：

```sql
ALTER TABLE transfer_missions ADD COLUMN cirs_request_id TEXT;
ALTER TABLE transfer_missions ADD COLUMN handoff_notes TEXT;
ALTER TABLE transfer_missions ADD COLUMN requesting_doctor TEXT;
```

### 3.3 transfer_request 狀態流程

```
PENDING ──(EMT accept)──> ACCEPTED ──(EMT depart)──> IN_PROGRESS ──(EMT arrive)──> COMPLETED
    │
    └──(Doctor cancel / timeout)──> CANCELLED
```

---

## 4. API 設計

### 4.1 CIRS API (新增)

#### 4.1.1 發起轉送請求

```
POST /api/transfer-requests
Authorization: Bearer {doctor_token}

{
    "registration_id": "REG-20260105-001",
    "destination_type": "HOSPITAL",
    "destination_text": "台大醫院急診",
    "eta_min": 60,
    "o2_lpm": 6,
    "patient_status": "MONITORED",
    "handoff_notes": "右股骨骨折已固定，生命徵象穩定，需後送手術"
}

Response 201:
{
    "request_id": "TREQ-20260105-001",
    "status": "PENDING",
    "created_at": "2026-01-05T10:30:00Z"
}
```

#### 4.1.2 查詢待處理轉送 (EMT PWA 輪詢用)

```
GET /api/transfer-requests?status=PENDING
Authorization: Bearer {emt_token}

Response 200:
{
    "requests": [
        {
            "request_id": "TREQ-20260105-001",
            "person": {
                "person_id": "P001",
                "name": "王小明",
                "age": 45,
                "triage_status": "YELLOW"
            },
            "registration": {
                "registration_id": "REG-20260105-001",
                "chief_complaint": "車禍外傷",
                "priority": "URGENT"
            },
            "requesting_doctor_name": "陳醫師",
            "destination_text": "台大醫院急診",
            "eta_min": 60,
            "o2_lpm": 6,
            "patient_status": "MONITORED",
            "handoff_notes": "右股骨骨折已固定...",
            "created_at": "2026-01-05T10:30:00Z"
        }
    ]
}
```

#### 4.1.3 EMT 接受轉送

```
POST /api/transfer-requests/{request_id}/accept
Authorization: Bearer {emt_token}

{
    "emt_name": "李技術員",
    "mirs_mission_id": "TRF-20260105-001"
}

Response 200:
{
    "request_id": "TREQ-20260105-001",
    "status": "ACCEPTED",
    "accepted_at": "2026-01-05T10:35:00Z"
}
```

### 4.2 MIRS API (更新)

#### 4.2.1 從 CIRS 匯入轉送請求

```
POST /api/transfer/import-from-cirs
Authorization: Bearer {emt_token}

{
    "cirs_request_id": "TREQ-20260105-001",
    "cirs_hub_url": "http://10.0.0.1:8090"
}

Response 201:
{
    "mission_id": "TRF-20260105-001",
    "status": "PLANNING",
    "patient": { ... },
    "handoff_notes": "右股骨骨折已固定...",
    "o2_lpm": 6,
    "eta_min": 60
}
```

---

## 5. EMT PWA UI 更新

### 5.1 新任務頁面 (v2.3 更新)

```
┌─────────────────────────────────────────────────────────────┐
│ 📋 新增轉送任務                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 📥 待接收交班 (2)                               [重新整理] │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ ┌───────────────────────────────────────────────────┐  │ │
│ │ │ 🟡 王小明 (45歲)              10:30 陳醫師發起    │  │ │
│ │ │    車禍外傷 - 右股骨骨折                          │  │ │
│ │ │    → 台大醫院急診 (60min)                        │  │ │
│ │ │    O2: 6 L/min | 狀態: 需監測                    │  │ │
│ │ │    備註: 已固定，生命徵象穩定                    │  │ │
│ │ │                                    [接收此交班]  │  │ │
│ │ └───────────────────────────────────────────────────┘  │ │
│ │ ┌───────────────────────────────────────────────────┐  │ │
│ │ │ 🔴 李大華 (62歲)              10:45 林醫師發起    │  │ │
│ │ │    胸痛 - 疑似 STEMI                             │  │ │
│ │ │    → 榮總心導管室 (45min)                        │  │ │
│ │ │    O2: 10 L/min | 狀態: 危急                     │  │ │
│ │ │                                    [接收此交班]  │  │ │
│ │ └───────────────────────────────────────────────────┘  │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ───────────────── 或 ─────────────────                      │
│                                                             │
│ [➕ 手動建立任務 (非掛號病患)]                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 接收交班後的自動填入

當 EMT 點擊「接收此交班」後：

1. 自動填入病患資訊（姓名、年齡、主訴）
2. 自動填入 ETA、O2 需求、目的地
3. 自動填入交班備註
4. EMT 可修改/補充任何欄位
5. 進入「設定」步驟確認物資

### 5.3 手動建立任務

保留現有功能，讓 EMT 可以：
- 手動輸入病患資訊（非 CIRS 掛號）
- 自由輸入交班備註
- 完整設定所有欄位

---

## 6. CIRS Doctor PWA 更新

### 6.1 完成看診對話框更新

在現有 `frontend/doctor/index.html` 的「完成看診」對話框中新增：

```html
<!-- 需轉送選項 -->
<div class="p-4 border-b">
    <label class="flex items-center gap-3">
        <input type="checkbox" x-model="completeForm.needs_transfer"
               class="w-5 h-5 text-amber-500 rounded">
        <span class="font-medium text-amber-700">需轉送</span>
    </label>

    <!-- 展開轉送詳情 -->
    <div x-show="completeForm.needs_transfer" class="mt-4 space-y-4">
        <!-- 目的地 -->
        <div>
            <label class="text-sm text-gray-600">目的地</label>
            <div class="flex gap-2 mt-1">
                <button @click="completeForm.destination_type = 'HOSPITAL'"
                        :class="completeForm.destination_type === 'HOSPITAL' ? 'bg-amber-500 text-white' : 'bg-amber-100 text-amber-700'"
                        class="px-3 py-1 rounded-full text-sm">後送醫院</button>
                <button @click="completeForm.destination_type = 'CUSTOM'"
                        :class="completeForm.destination_type === 'CUSTOM' ? 'bg-amber-500 text-white' : 'bg-amber-100 text-amber-700'"
                        class="px-3 py-1 rounded-full text-sm">自訂</button>
            </div>
            <input x-show="completeForm.destination_type === 'CUSTOM'"
                   x-model="completeForm.destination_text"
                   class="mt-2 w-full px-3 py-2 border rounded-lg"
                   placeholder="輸入目的地">
        </div>

        <!-- 預估 ETA -->
        <div>
            <label class="text-sm text-gray-600">預估 ETA</label>
            <div class="flex gap-2 mt-1">
                <template x-for="eta in [30, 60, 90, 120]">
                    <button @click="completeForm.eta_min = eta"
                            :class="completeForm.eta_min === eta ? 'bg-amber-500 text-white' : 'bg-amber-100 text-amber-700'"
                            class="px-3 py-1 rounded-full text-sm" x-text="eta + '分'"></button>
                </template>
            </div>
        </div>

        <!-- O2 需求 -->
        <div>
            <label class="text-sm text-gray-600">初步 O2 需求</label>
            <div class="flex gap-2 mt-1">
                <template x-for="o2 in [{v:0,l:'無'},{v:3,l:'3'},{v:6,l:'6'},{v:10,l:'10'},{v:15,l:'15'}]">
                    <button @click="completeForm.o2_lpm = o2.v"
                            :class="completeForm.o2_lpm === o2.v ? 'bg-amber-500 text-white' : 'bg-amber-100 text-amber-700'"
                            class="px-3 py-1 rounded-full text-sm" x-text="o2.l"></button>
                </template>
            </div>
        </div>

        <!-- 交班備註 -->
        <div>
            <label class="text-sm text-gray-600">交班備註</label>
            <textarea x-model="completeForm.handoff_notes"
                      class="w-full mt-1 px-3 py-2 border rounded-lg" rows="3"
                      placeholder="重要交班事項（診斷、已處置、注意事項）"></textarea>
        </div>
    </div>
</div>
```

### 6.2 Alpine.js 資料

```javascript
completeForm: {
    // 既有欄位
    needs_procedure: false,
    procedure_notes: '',
    needs_anesthesia: false,
    anesthesia_notes: '',

    // 新增：轉送相關
    needs_transfer: false,
    destination_type: 'HOSPITAL',
    destination_text: '',
    eta_min: 60,
    o2_lpm: 0,
    patient_status: 'STABLE',
    handoff_notes: ''
}
```

### 6.3 完成看診 API 呼叫

```javascript
async completeConsultation() {
    const payload = {
        // ... 既有欄位 ...
    };

    // 如果需要轉送，同時發起轉送請求
    if (this.completeForm.needs_transfer) {
        await fetch(`${this.apiUrl}/transfer-requests`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${this.token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                registration_id: this.currentPatient.registration_id,
                destination_type: this.completeForm.destination_type,
                destination_text: this.completeForm.destination_text,
                eta_min: this.completeForm.eta_min,
                o2_lpm: this.completeForm.o2_lpm,
                patient_status: this.completeForm.patient_status,
                handoff_notes: this.completeForm.handoff_notes
            })
        });
    }

    // ... 完成看診 API ...
}
```

---

## 7. 實作順序

### Phase 1: O2 流量快選 (MIRS EMT PWA)

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 1.1 | `static/emt/index.html` | O2 流量改為快選按鈕 |
| 1.2 | `docs/DEV_SPEC_EMT_TRANSFER_PWA.md` | 更新 O2 選項文件 |

### Phase 2: CIRS 轉送請求 API

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 2.1 | `backend/migrations/` | 新增 transfer_requests 表 |
| 2.2 | `backend/routes/transfer.py` | 新增 API 端點 |
| 2.3 | `backend/main.py` | 註冊 router |

### Phase 3: CIRS Doctor PWA 轉送按鈕

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 3.1 | `frontend/doctor/index.html` | 完成看診對話框新增轉送選項 |
| 3.2 | `frontend/doctor/service-worker.js` | 版本更新 |

### Phase 4: MIRS EMT PWA 接收交班

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 4.1 | `routes/transfer.py` | 新增 CIRS 匯入 API |
| 4.2 | `static/emt/index.html` | 新增待接收交班列表 |
| 4.3 | `database/migrations/` | transfer_missions 新增欄位 |

---

## 8. 檔案變更清單

| 系統 | 檔案 | 變更類型 |
|------|------|----------|
| MIRS | `static/emt/index.html` | 修改 |
| MIRS | `routes/transfer.py` | 修改 |
| MIRS | `database/migrations/transfer_v3_handoff.sql` | 新增 |
| MIRS | `docs/DEV_SPEC_EMT_TRANSFER_PWA.md` | 修改 |
| CIRS | `backend/routes/transfer.py` | 新增 |
| CIRS | `backend/migrations/add_transfer_requests.sql` | 新增 |
| CIRS | `frontend/doctor/index.html` | 修改 |
| CIRS | `frontend/doctor/service-worker.js` | 修改 |

---

## 9. 測試情境

### 9.1 O2 流量測試

| 測試 | 預期結果 |
|------|----------|
| 點擊「無」 | o2_lpm = 0，按鈕高亮 |
| 點擊「6」 | o2_lpm = 6，按鈕高亮 |
| 點擊「自訂」輸入 8 | o2_lpm = 8 |

### 9.2 交班流程測試

| 步驟 | 操作 | 預期結果 |
|------|------|----------|
| 1 | Doctor 勾選「需轉送」 | 顯示轉送詳情欄位 |
| 2 | Doctor 填寫並完成看診 | CIRS 建立 transfer_request (PENDING) |
| 3 | EMT PWA 開啟新任務 | 顯示待接收交班列表 |
| 4 | EMT 點擊「接收此交班」 | 自動填入資訊，狀態改 ACCEPTED |
| 5 | EMT 確認出發 | CIRS request 狀態改 IN_PROGRESS |
| 6 | EMT 抵達結案 | CIRS request 狀態改 COMPLETED |

---

## 10. 注意事項

### 10.1 離線處理

- EMT PWA 應定期輪詢待接收交班（有網路時）
- 接收交班後，本地建立任務，可離線操作
- 狀態同步在恢復連線時進行

### 10.2 權限控制

- 只有醫師 (role: doctor) 可發起轉送請求
- 只有 EMT 可接受轉送請求
- 一個請求只能被一位 EMT 接受

### 10.3 超時處理

- 轉送請求 30 分鐘未接受自動標記為 EXPIRED
- 醫師可取消未接受的請求

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*文件版本: v1.0 Draft*
*更新日期: 2026-01-05*
