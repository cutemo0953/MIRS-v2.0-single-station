# EMT Transfer Handoff 開發規格書

**版本**: 2.0
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
| **結構化交班** | ISBAR (一般) / MIST (外傷) 格式 | EMT 實務回饋 |
| **病患基本資料** | 身高、體重、過敏史 | EMT 實務回饋 |
| **Step 重整** | Step 1 改為交班事項，Step 2 為物資整備 | UX 改進 |
| **Doctor PWA 帶入** | 自動匯入已有病歷資料 | 效率優化 |

---

## 1. Step 流程重設計

### 1.1 新版 Step 架構

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 0      │  Step 1        │  Step 2      │  Step 3  │  Step 4  │
│  任務設定    │  交班事項      │  物資整備    │  轉送中  │  結案    │
│  (PLANNING)  │  (PLANNING)    │  (READY)     │  (EN_ROUTE) │ (ARRIVED)│
│              │                │              │          │          │
│  目的地      │  ISBAR/MIST    │  氧氣鋼瓶    │  即時    │  消耗    │
│  ETA         │  基本資料      │  設備電量    │  追蹤    │  統計    │
│  O2/IV       │  過敏史        │  藥物/耗材   │          │          │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Step 變更對照

| 版本 | Step 0 | Step 1 | Step 2 | Step 3 | Step 4 |
|------|--------|--------|--------|--------|--------|
| v1.x | 任務設定 | 物資確認 (多餘) | 物資整備 | 轉送中 | 結案 |
| v2.0 | 任務設定 | **交班事項** | 物資整備 | 轉送中 | 結案 |

---

## 2. 結構化交班格式

### 2.1 ISBAR 格式 (一般/內科)

| 欄位 | 英文 | 說明 | 範例 |
|------|------|------|------|
| **I** | Identify | 身份辨識 | 王小明，45歲，男性 |
| **S** | Situation | 現況說明 | 胸痛 2 小時，需轉送心導管室 |
| **B** | Background | 病史背景 | HTN, DM, 過敏: Penicillin |
| **A** | Assessment | 評估狀況 | BP 150/90, HR 88, SpO2 98% |
| **R** | Recommendation | 建議事項 | 監測心電圖，準備 NTG |

### 2.2 MIST 格式 (外傷)

| 欄位 | 英文 | 說明 | 範例 |
|------|------|------|------|
| **M** | Mechanism | 受傷機轉 | 機車對撞，時速約 60 |
| **I** | Injuries | 傷勢發現 | 右股骨開放性骨折，右胸挫傷 |
| **S** | Signs | 生命徵象 | GCS 15, BP 110/70, HR 100 |
| **T** | Treatment | 已處置 | 止血帶、夾板固定、TXA 1g |

### 2.3 UI 設計：Tab 切換

```
┌─────────────────────────────────────────────────────────────┐
│ 交班格式                                                     │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐                         │
│  │    ISBAR     │  │    MIST      │                         │
│  │   (一般)     │  │   (外傷)     │                         │
│  └──────────────┘  └──────────────┘                         │
│      ●選取                                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 病患基本資料

### 3.1 資料欄位

```
┌─────────────────────────────────────────────────────────────┐
│ 病患資料                                                     │
├─────────────────────────────────────────────────────────────┤
│ 姓名: [王小明        ]  年齡: [45] 歲  性別: ○男 ○女       │
│                                                             │
│ 身高: [170] cm    體重: [70] kg    → BMI: 24.2              │
│                                                             │
│ 過敏史:                                                      │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Penicillin, Aspirin                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 病史:                                                        │
│ [+HTN] [+DM] [+CAD] [ ] CKD [ ] COPD [+其他...]            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 從 Doctor PWA 自動帶入

當 EMT 接收來自 CIRS 的交班請求時，以下欄位自動填入：

| 欄位 | 來源 | 可編輯 |
|------|------|--------|
| 姓名、年齡、性別 | `registrations.person` | 否 |
| 身高、體重 | `persons.height`, `persons.weight` | 是 |
| 過敏史 | `persons.allergies` | 是 |
| 病史 | `persons.medical_history` | 是 |
| 主訴 | `registrations.chief_complaint` | 否 |
| 處置記錄 | `procedure_orders` | 否 (只讀) |

---

## 4. Step 1: 交班事項 UI

### 4.1 ISBAR 模式

```html
<!-- Step 1: 交班事項 (ISBAR) -->
<div x-show="currentMission && currentStep === 1 && handoffFormat === 'ISBAR'" x-cloak>
    <div class="bg-white rounded-xl shadow-lg p-6 mb-4">
        <!-- 格式切換 -->
        <div class="flex border-b mb-4">
            <button @click="handoffFormat = 'ISBAR'"
                    :class="handoffFormat === 'ISBAR' ? 'border-b-2 border-amber-500 text-amber-600' : 'text-gray-500'"
                    class="flex-1 py-2 font-medium">ISBAR (一般)</button>
            <button @click="handoffFormat = 'MIST'"
                    :class="handoffFormat === 'MIST' ? 'border-b-2 border-red-500 text-red-600' : 'text-gray-500'"
                    class="flex-1 py-2 font-medium">MIST (外傷)</button>
        </div>

        <!-- 病患基本資料 -->
        <div class="bg-amber-50 rounded-lg p-4 mb-4">
            <h3 class="font-bold text-amber-700 mb-3">病患資料</h3>
            <div class="grid grid-cols-3 gap-3 text-sm">
                <div>
                    <label class="text-gray-500">姓名</label>
                    <div class="font-medium" x-text="handoff.patient_name || '未填寫'"></div>
                </div>
                <div>
                    <label class="text-gray-500">年齡</label>
                    <div class="font-medium" x-text="(handoff.patient_age || '-') + ' 歲'"></div>
                </div>
                <div>
                    <label class="text-gray-500">性別</label>
                    <div class="font-medium" x-text="handoff.patient_gender === 'M' ? '男' : handoff.patient_gender === 'F' ? '女' : '-'"></div>
                </div>
            </div>
            <div class="grid grid-cols-3 gap-3 text-sm mt-3">
                <div>
                    <label class="text-gray-500">身高</label>
                    <input type="number" x-model.number="handoff.height_cm"
                           class="w-full border rounded px-2 py-1" placeholder="cm">
                </div>
                <div>
                    <label class="text-gray-500">體重</label>
                    <input type="number" x-model.number="handoff.weight_kg"
                           class="w-full border rounded px-2 py-1" placeholder="kg">
                </div>
                <div>
                    <label class="text-gray-500">BMI</label>
                    <div class="font-medium py-1"
                         x-text="handoff.height_cm && handoff.weight_kg ? (handoff.weight_kg / Math.pow(handoff.height_cm/100, 2)).toFixed(1) : '-'"></div>
                </div>
            </div>
            <div class="mt-3">
                <label class="text-gray-500 text-sm">過敏史</label>
                <input type="text" x-model="handoff.allergies"
                       class="w-full border rounded px-2 py-1 mt-1" placeholder="如: Penicillin, Aspirin">
            </div>
        </div>

        <!-- I: Identify -->
        <div class="mb-4 p-4 border-l-4 border-blue-400 bg-blue-50">
            <label class="font-bold text-blue-700">I - Identify (身份確認)</label>
            <div class="text-sm text-gray-600 mt-1"
                 x-text="handoff.patient_name + ', ' + handoff.patient_age + '歲, ' + (handoff.patient_gender === 'M' ? '男' : '女')">
            </div>
        </div>

        <!-- S: Situation -->
        <div class="mb-4 p-4 border-l-4 border-green-400 bg-green-50">
            <label class="font-bold text-green-700">S - Situation (現況說明)</label>
            <textarea x-model="handoff.situation" rows="2"
                      class="w-full mt-2 border rounded px-3 py-2"
                      placeholder="為何需要轉送？目前狀況？"></textarea>
        </div>

        <!-- B: Background -->
        <div class="mb-4 p-4 border-l-4 border-yellow-400 bg-yellow-50">
            <label class="font-bold text-yellow-700">B - Background (病史背景)</label>
            <div class="flex flex-wrap gap-2 mt-2">
                <template x-for="h in ['HTN', 'DM', 'CAD', 'CKD', 'COPD', 'Stroke']">
                    <label class="flex items-center gap-1 px-2 py-1 bg-white rounded border cursor-pointer">
                        <input type="checkbox" :checked="handoff.medical_history?.includes(h)"
                               @change="toggleHistory(h)">
                        <span class="text-sm" x-text="h"></span>
                    </label>
                </template>
            </div>
            <textarea x-model="handoff.background_notes" rows="2"
                      class="w-full mt-2 border rounded px-3 py-2"
                      placeholder="其他病史、用藥..."></textarea>
        </div>

        <!-- A: Assessment -->
        <div class="mb-4 p-4 border-l-4 border-orange-400 bg-orange-50">
            <label class="font-bold text-orange-700">A - Assessment (評估)</label>
            <div class="grid grid-cols-3 gap-2 mt-2">
                <div>
                    <label class="text-xs text-gray-500">BP</label>
                    <input type="text" x-model="handoff.bp" class="w-full border rounded px-2 py-1" placeholder="120/80">
                </div>
                <div>
                    <label class="text-xs text-gray-500">HR</label>
                    <input type="number" x-model.number="handoff.hr" class="w-full border rounded px-2 py-1" placeholder="80">
                </div>
                <div>
                    <label class="text-xs text-gray-500">SpO2</label>
                    <input type="number" x-model.number="handoff.spo2" class="w-full border rounded px-2 py-1" placeholder="98">
                </div>
                <div>
                    <label class="text-xs text-gray-500">RR</label>
                    <input type="number" x-model.number="handoff.rr" class="w-full border rounded px-2 py-1" placeholder="16">
                </div>
                <div>
                    <label class="text-xs text-gray-500">Temp</label>
                    <input type="number" x-model.number="handoff.temp" step="0.1" class="w-full border rounded px-2 py-1" placeholder="36.5">
                </div>
                <div>
                    <label class="text-xs text-gray-500">GCS</label>
                    <input type="text" x-model="handoff.gcs" class="w-full border rounded px-2 py-1" placeholder="E4V5M6">
                </div>
            </div>
        </div>

        <!-- R: Recommendation -->
        <div class="mb-4 p-4 border-l-4 border-red-400 bg-red-50">
            <label class="font-bold text-red-700">R - Recommendation (建議)</label>
            <textarea x-model="handoff.recommendation" rows="2"
                      class="w-full mt-2 border rounded px-3 py-2"
                      placeholder="轉送途中注意事項、預期處置..."></textarea>
        </div>
    </div>

    <div class="flex gap-3">
        <button @click="goToStep(0)" class="flex-1 bg-gray-200 text-gray-700 font-bold py-4 rounded-xl">
            返回
        </button>
        <button @click="goToStep(2)" class="flex-1 bg-amber-500 text-white font-bold py-4 rounded-xl">
            下一步：物資整備
        </button>
    </div>
</div>
```

### 4.2 MIST 模式

```html
<!-- Step 1: 交班事項 (MIST) -->
<div x-show="currentMission && currentStep === 1 && handoffFormat === 'MIST'" x-cloak>
    <div class="bg-white rounded-xl shadow-lg p-6 mb-4">
        <!-- 格式切換 Tab -->
        <!-- ... 同上 ... -->

        <!-- 病患基本資料 -->
        <!-- ... 同上 ... -->

        <!-- M: Mechanism -->
        <div class="mb-4 p-4 border-l-4 border-red-500 bg-red-50">
            <label class="font-bold text-red-700">M - Mechanism (受傷機轉)</label>
            <div class="flex flex-wrap gap-2 mt-2">
                <template x-for="m in ['車禍', '墜落', '穿刺傷', '鈍傷', '爆炸', '槍傷']">
                    <button @click="handoff.mechanism_type = m"
                            :class="handoff.mechanism_type === m ? 'bg-red-500 text-white' : 'bg-white border'"
                            class="px-3 py-1 rounded-full text-sm" x-text="m"></button>
                </template>
            </div>
            <textarea x-model="handoff.mechanism_detail" rows="2"
                      class="w-full mt-2 border rounded px-3 py-2"
                      placeholder="詳細描述：時速、高度、武器類型..."></textarea>
        </div>

        <!-- I: Injuries -->
        <div class="mb-4 p-4 border-l-4 border-orange-500 bg-orange-50">
            <label class="font-bold text-orange-700">I - Injuries (傷勢發現)</label>
            <div class="grid grid-cols-2 gap-2 mt-2 text-sm">
                <label class="flex items-center gap-2 p-2 bg-white rounded border">
                    <input type="checkbox" x-model="handoff.injuries.head"> 頭部
                </label>
                <label class="flex items-center gap-2 p-2 bg-white rounded border">
                    <input type="checkbox" x-model="handoff.injuries.chest"> 胸部
                </label>
                <label class="flex items-center gap-2 p-2 bg-white rounded border">
                    <input type="checkbox" x-model="handoff.injuries.abdomen"> 腹部
                </label>
                <label class="flex items-center gap-2 p-2 bg-white rounded border">
                    <input type="checkbox" x-model="handoff.injuries.pelvis"> 骨盆
                </label>
                <label class="flex items-center gap-2 p-2 bg-white rounded border">
                    <input type="checkbox" x-model="handoff.injuries.extremity"> 四肢
                </label>
                <label class="flex items-center gap-2 p-2 bg-white rounded border">
                    <input type="checkbox" x-model="handoff.injuries.spine"> 脊椎
                </label>
            </div>
            <textarea x-model="handoff.injuries_detail" rows="2"
                      class="w-full mt-2 border rounded px-3 py-2"
                      placeholder="傷勢描述：開放性/閉鎖性、出血情況..."></textarea>
        </div>

        <!-- S: Signs -->
        <div class="mb-4 p-4 border-l-4 border-yellow-500 bg-yellow-50">
            <label class="font-bold text-yellow-700">S - Signs (生命徵象)</label>
            <div class="grid grid-cols-3 gap-2 mt-2">
                <!-- 同 ISBAR Assessment -->
                <div>
                    <label class="text-xs text-gray-500">GCS</label>
                    <input type="text" x-model="handoff.gcs" class="w-full border rounded px-2 py-1" placeholder="E4V5M6">
                </div>
                <div>
                    <label class="text-xs text-gray-500">BP</label>
                    <input type="text" x-model="handoff.bp" class="w-full border rounded px-2 py-1" placeholder="120/80">
                </div>
                <div>
                    <label class="text-xs text-gray-500">HR</label>
                    <input type="number" x-model.number="handoff.hr" class="w-full border rounded px-2 py-1" placeholder="80">
                </div>
                <div>
                    <label class="text-xs text-gray-500">RR</label>
                    <input type="number" x-model.number="handoff.rr" class="w-full border rounded px-2 py-1" placeholder="16">
                </div>
                <div>
                    <label class="text-xs text-gray-500">SpO2</label>
                    <input type="number" x-model.number="handoff.spo2" class="w-full border rounded px-2 py-1" placeholder="98">
                </div>
                <div>
                    <label class="text-xs text-gray-500">Shock Index</label>
                    <div class="py-1 font-medium"
                         :class="(handoff.hr / parseInt(handoff.bp?.split('/')[0] || 120)) > 1 ? 'text-red-600' : 'text-green-600'"
                         x-text="handoff.hr && handoff.bp ? (handoff.hr / parseInt(handoff.bp.split('/')[0])).toFixed(2) : '-'"></div>
                </div>
            </div>
        </div>

        <!-- T: Treatment -->
        <div class="mb-4 p-4 border-l-4 border-green-500 bg-green-50">
            <label class="font-bold text-green-700">T - Treatment (已處置)</label>
            <div class="flex flex-wrap gap-2 mt-2">
                <template x-for="t in ['止血帶', '夾板固定', '頸圈', '胸腔封閉', 'IV access', 'O2', 'TXA', '止痛']">
                    <label class="flex items-center gap-1 px-2 py-1 bg-white rounded border cursor-pointer">
                        <input type="checkbox" :checked="handoff.treatments?.includes(t)"
                               @change="toggleTreatment(t)">
                        <span class="text-sm" x-text="t"></span>
                    </label>
                </template>
            </div>
            <textarea x-model="handoff.treatment_notes" rows="2"
                      class="w-full mt-2 border rounded px-3 py-2"
                      placeholder="其他處置、用藥劑量..."></textarea>
        </div>
    </div>

    <!-- 同樣的導航按鈕 -->
</div>
```

---

## 5. 資料模型更新

### 5.1 MIRS transfer_missions 欄位擴充

```sql
-- v2.0: 交班資料欄位
ALTER TABLE transfer_missions ADD COLUMN handoff_format TEXT DEFAULT 'ISBAR'; -- ISBAR/MIST

-- 病患基本資料
ALTER TABLE transfer_missions ADD COLUMN patient_name TEXT;
ALTER TABLE transfer_missions ADD COLUMN patient_age INTEGER;
ALTER TABLE transfer_missions ADD COLUMN patient_gender TEXT;
ALTER TABLE transfer_missions ADD COLUMN height_cm REAL;
ALTER TABLE transfer_missions ADD COLUMN weight_kg REAL;
ALTER TABLE transfer_missions ADD COLUMN allergies TEXT;

-- ISBAR 欄位
ALTER TABLE transfer_missions ADD COLUMN situation TEXT;
ALTER TABLE transfer_missions ADD COLUMN background_history TEXT;  -- JSON: ["HTN","DM"]
ALTER TABLE transfer_missions ADD COLUMN background_notes TEXT;
ALTER TABLE transfer_missions ADD COLUMN assessment_vitals TEXT;   -- JSON: {bp, hr, spo2, rr, temp, gcs}
ALTER TABLE transfer_missions ADD COLUMN recommendation TEXT;

-- MIST 欄位 (外傷)
ALTER TABLE transfer_missions ADD COLUMN mechanism_type TEXT;
ALTER TABLE transfer_missions ADD COLUMN mechanism_detail TEXT;
ALTER TABLE transfer_missions ADD COLUMN injuries_regions TEXT;    -- JSON: {head, chest, ...}
ALTER TABLE transfer_missions ADD COLUMN injuries_detail TEXT;
ALTER TABLE transfer_missions ADD COLUMN treatments_given TEXT;    -- JSON: ["止血帶","TXA"]
ALTER TABLE transfer_missions ADD COLUMN treatment_notes TEXT;

-- CIRS 連結
ALTER TABLE transfer_missions ADD COLUMN cirs_request_id TEXT;
ALTER TABLE transfer_missions ADD COLUMN cirs_person_id TEXT;
ALTER TABLE transfer_missions ADD COLUMN cirs_registration_id TEXT;
ALTER TABLE transfer_missions ADD COLUMN requesting_doctor TEXT;
```

### 5.2 CIRS transfer_requests 表 (完整版)

```sql
CREATE TABLE transfer_requests (
    request_id TEXT PRIMARY KEY,          -- 'TREQ-YYYYMMDD-NNN'
    registration_id TEXT NOT NULL,        -- FK → registrations
    person_id TEXT NOT NULL,              -- FK → persons

    -- 發起資訊
    requesting_doctor_id TEXT,
    requesting_doctor_name TEXT,
    origin_station_id TEXT,

    -- 目的地
    destination_type TEXT DEFAULT 'HOSPITAL',
    destination_text TEXT,
    eta_min INTEGER,

    -- 初步評估
    o2_lpm REAL DEFAULT 0,
    patient_status TEXT DEFAULT 'STABLE',

    -- 結構化交班
    handoff_format TEXT DEFAULT 'ISBAR',  -- ISBAR/MIST

    -- 病患資料 (從 persons 複製，允許覆寫)
    patient_height_cm REAL,
    patient_weight_kg REAL,
    patient_allergies TEXT,

    -- ISBAR 內容
    isbar_situation TEXT,
    isbar_background TEXT,                -- JSON
    isbar_assessment TEXT,                -- JSON (vitals)
    isbar_recommendation TEXT,

    -- MIST 內容
    mist_mechanism TEXT,                  -- JSON
    mist_injuries TEXT,                   -- JSON
    mist_signs TEXT,                      -- JSON (vitals)
    mist_treatment TEXT,                  -- JSON

    -- 狀態
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accepted_at TIMESTAMP,
    accepted_by TEXT,
    mirs_mission_id TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Alpine.js 資料結構

### 6.1 handoff 物件

```javascript
// EMT PWA: emtTransfer() 內
handoff: {
    format: 'ISBAR',  // 'ISBAR' or 'MIST'

    // 病患基本資料
    patient_name: '',
    patient_age: null,
    patient_gender: '',  // 'M' or 'F'
    height_cm: null,
    weight_kg: null,
    allergies: '',
    medical_history: [],  // ['HTN', 'DM', ...]

    // ISBAR
    situation: '',
    background_notes: '',
    bp: '',
    hr: null,
    spo2: null,
    rr: null,
    temp: null,
    gcs: '',
    recommendation: '',

    // MIST
    mechanism_type: '',
    mechanism_detail: '',
    injuries: {
        head: false,
        chest: false,
        abdomen: false,
        pelvis: false,
        extremity: false,
        spine: false
    },
    injuries_detail: '',
    treatments: [],  // ['止血帶', 'TXA', ...]
    treatment_notes: ''
},

// 方法
toggleHistory(h) {
    const idx = this.handoff.medical_history.indexOf(h);
    if (idx === -1) {
        this.handoff.medical_history.push(h);
    } else {
        this.handoff.medical_history.splice(idx, 1);
    }
},

toggleTreatment(t) {
    const idx = this.handoff.treatments.indexOf(t);
    if (idx === -1) {
        this.handoff.treatments.push(t);
    } else {
        this.handoff.treatments.splice(idx, 1);
    }
},
```

### 6.2 從 CIRS 匯入時自動填入

```javascript
async importFromCIRS(request) {
    // 基本資料
    this.handoff.patient_name = request.person?.name || '';
    this.handoff.patient_age = request.person?.age || null;
    this.handoff.patient_gender = request.person?.gender || '';
    this.handoff.height_cm = request.person?.height_cm || null;
    this.handoff.weight_kg = request.person?.weight_kg || null;
    this.handoff.allergies = request.person?.allergies || '';

    // 交班格式
    this.handoff.format = request.handoff_format || 'ISBAR';

    // ISBAR
    if (request.isbar_situation) this.handoff.situation = request.isbar_situation;
    if (request.isbar_background) this.handoff.medical_history = JSON.parse(request.isbar_background);
    if (request.isbar_assessment) {
        const vitals = JSON.parse(request.isbar_assessment);
        Object.assign(this.handoff, vitals);
    }
    if (request.isbar_recommendation) this.handoff.recommendation = request.isbar_recommendation;

    // MIST
    if (request.mist_mechanism) {
        const mech = JSON.parse(request.mist_mechanism);
        this.handoff.mechanism_type = mech.type;
        this.handoff.mechanism_detail = mech.detail;
    }
    if (request.mist_injuries) {
        const inj = JSON.parse(request.mist_injuries);
        this.handoff.injuries = inj.regions;
        this.handoff.injuries_detail = inj.detail;
    }
    if (request.mist_treatment) {
        const tx = JSON.parse(request.mist_treatment);
        this.handoff.treatments = tx.list || [];
        this.handoff.treatment_notes = tx.notes || '';
    }

    // Mission 設定
    this.newMission.destination = request.destination_text || '';
    this.newMission.eta_min = request.eta_min || 60;
    this.newMission.o2_lpm = request.o2_lpm || 0;
}
```

---

## 7. O2 流量預設值 (已實作)

### 7.1 按鈕配置

```
[無] [3] [6] [10] [15]
```

### 7.2 對照表

| 選項 | L/min | 適用情境 |
|------|-------|----------|
| 無 | 0 | 無氧氣需求 |
| 3 | 3 | 鼻導管低流量 |
| 6 | 6 | 鼻導管中流量 |
| 10 | 10 | 面罩 / NRB |
| 15 | 15 | NRB 高流量 / BVM |

---

## 8. CIRS Doctor PWA 更新

### 8.1 完成看診對話框

在「需轉送」勾選後顯示交班表單：

```
┌─────────────────────────────────────────────────────────────┐
│ [✓] 需轉送                                                   │
├─────────────────────────────────────────────────────────────┤
│ 交班格式: [ISBAR] [MIST]                                     │
│                                                             │
│ ─────────── ISBAR ───────────                               │
│ S - 現況: [                                               ] │
│ B - 病史: [HTN] [DM] [CAD] [___]                           │
│ A - 評估: BP [   ] HR [  ] SpO2 [  ]                       │
│ R - 建議: [                                               ] │
│                                                             │
│ 目的地: [後送醫院 ▼]  ETA: [60] 分                          │
│ O2: [無] [3] [6] [10] [15]                                  │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 資料自動填入來源

| 欄位 | 資料來源 |
|------|----------|
| 姓名、年齡、性別 | `registrations.person_id` → `persons` |
| 身高、體重 | `persons.height`, `persons.weight` |
| 過敏史 | `persons.allergies` |
| 病史 | `persons.medical_history` (JSON) |
| 生命徵象 | 最近一筆 `vital_signs` 記錄 |
| 已處置 | `procedure_orders` 或 `treatments` 記錄 |

---

## 9. 實作順序

### Phase 1: O2 流量快選 ✓ (已完成)

### Phase 2: EMT PWA Step 重構

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 2.1 | `static/emt/index.html` | Step 1 改為交班事項 UI |
| 2.2 | `static/emt/index.html` | 新增 handoff 資料結構 |
| 2.3 | `static/emt/index.html` | ISBAR/MIST Tab 切換 |
| 2.4 | `static/emt/sw.js` | 版本更新 |

### Phase 3: CIRS 轉送請求 API

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 3.1 | `backend/migrations/` | 新增 transfer_requests 表 |
| 3.2 | `backend/routes/transfer.py` | API 端點 |
| 3.3 | `frontend/doctor/index.html` | 轉送表單 UI |

### Phase 4: MIRS/CIRS 整合

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 4.1 | `routes/transfer.py` | 從 CIRS 匯入 API |
| 4.2 | `static/emt/index.html` | 待接收交班列表 |
| 4.3 | `database/` | transfer_missions 欄位擴充 |

---

## 10. 注意事項

### 10.1 隱私保護

- 病患資料只在任務期間保存
- 結案後保留摘要，清除詳細病歷
- 符合 HIPAA/GDPR 要求

### 10.2 離線處理

- 交班資料本地暫存
- 恢復連線後同步至 CIRS/MIRS

### 10.3 欄位驗證

- 必填：姓名、年齡、目的地
- 建議填：過敏史、生命徵象
- 選填：BMI、病史詳情

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*文件版本: v2.0 Draft*
*更新日期: 2026-01-05*
