# MIRS Anesthesia Module v1.6.1 - PIO 因果鏈系統 (整合版)

**Version:** 1.6.1
**基於:** v1.6.0 + ChatGPT/Gemini 回饋整合
**更新日期:** 2026-01-06
**狀態:** 規格定稿

---

## Changelog

### v1.6.1 整合回饋

| 來源 | 建議 | 採納 |
|------|------|------|
| ChatGPT | PIO 是連結層，不是獨立記錄 | ✓ |
| ChatGPT | 事件類型擴充 (VASOACTIVE, BLOOD, VENT) | ✓ |
| ChatGPT | 補登 >30min 需 PIN 提升 | ✓ |
| Gemini | Quick Scenario Bundle (情境快速包) | ✓ |
| Gemini | 相對時間偏移 API | ✓ |

---

## 核心設計原則

### 原則 1: PIO 是「連結層」，不是獨立表單

```
❌ 錯誤理解: PIO 是三個獨立欄位讓護士填寫
✓ 正確理解: PIO 是把現有事件 (Vitals/Meds/Blood) 串成因果鏈的 metadata
```

**硬規則:**
- 所有術中事件仍為 append-only 的 `anesthesia_events`
- `pio_interventions` 和 `pio_outcomes` 必須有 `event_ref_id` 指向實際事件
- 不允許「只有 PIO 記錄但沒有底層事件」的情況

### 原則 2: 里程碑只是事件類型之一

```
MILESTONE (切皮/關閉) = 一種 event_type
VITAL_SIGN           = 一種 event_type
MED_ADMIN            = 一種 event_type
VASOACTIVE_TITRATION = 一種 event_type  ← 新增
...

PIO 是把這些事件「組織起來」的結構，不取代它們
```

---

## 1. 事件類型擴充 (Event Taxonomy)

### 1.1 完整事件類型定義

```typescript
type AnesthesiaEventType =
  // === 生命徵象 ===
  | 'VITAL_SIGN'              // 定時 vitals (BP, HR, SpO2, EtCO2, Temp)

  // === 藥物 ===
  | 'MED_ADMIN'               // 一般藥物給予
  | 'VASOACTIVE_BOLUS'        // 昇壓劑/降壓劑 單次給藥 (Ephedrine 5mg IV)
  | 'VASOACTIVE_INFUSION'     // 昇壓劑 幫浦調整 (Levophed 0.05→0.1 mcg/kg/min)

  // === 輸液/輸血 ===
  | 'FLUID_BOLUS'             // 輸液挑戰 (LR 500ml fast)
  | 'BLOOD_PRODUCT'           // 輸血 (PRBC/FFP/PLT/CRYO)

  // === 呼吸/氣道 ===
  | 'VENT_SETTING_CHANGE'     // 呼吸器參數調整 (FiO2, PEEP, VT, RR)
  | 'AIRWAY_EVENT'            // 氣道事件 (插管/拔管/LMA/困難氣道)

  // === 麻醉深度 ===
  | 'ANESTHESIA_DEPTH_ADJUST' // 麻醉深度調整 (Gas%/Propofol TCI/Bolus)

  // === 手術里程碑 ===
  | 'MILESTONE'               // 切皮/關閉/tourniquet 等

  // === 其他 ===
  | 'LAB_RESULT_POINT'        // Point-of-care 檢驗 (Hb/ABG/ACT/Glucose)
  | 'PROCEDURE_NOTE'          // 術中短註記
  | 'POSITION_CHANGE'         // 姿勢調整 (Trendelenburg, lateral)
  | 'EQUIPMENT_EVENT'         // 設備相關 (O2 cylinder switch, monitor issue)
```

### 1.2 新增事件 Payload Schema

#### VASOACTIVE_BOLUS

```typescript
interface VasoactiveBolus {
  drug_name: string;          // "Ephedrine", "Phenylephrine", "Atropine"
  dose: number;
  unit: string;               // "mg", "mcg"
  route: 'IV' | 'IM';
  indication: string;         // "Hypotension", "Bradycardia"
  linked_problem_id?: string; // 連結到 PIO Problem
}
```

#### VASOACTIVE_INFUSION

```typescript
interface VasoactiveInfusion {
  drug_name: string;          // "Norepinephrine", "Dopamine", "Nicardipine"
  action: 'START' | 'TITRATE' | 'STOP';
  rate_from?: number;         // mcg/kg/min (titrate 時)
  rate_to?: number;
  target?: string;            // "MAP > 65", "SBP < 140"
  linked_problem_id?: string;
}
```

#### BLOOD_PRODUCT

```typescript
interface BloodProduct {
  product_type: 'PRBC' | 'FFP' | 'PLATELET' | 'CRYO' | 'WHOLE_BLOOD';
  unit_id: string;            // 血袋編號
  unit_count: number;         // 通常 1
  action: 'START' | 'COMPLETE' | 'REACTION';
  reaction_type?: 'FEBRILE' | 'ALLERGIC' | 'HEMOLYTIC' | 'NONE';
  linked_problem_id?: string; // 連結到 BLEEDING 問題

  // 庫存連動
  inventory_deduct: boolean;  // 是否觸發 MIRS 庫存扣減
}
```

#### VENT_SETTING_CHANGE

```typescript
interface VentSettingChange {
  parameter: 'FIO2' | 'PEEP' | 'VT' | 'RR' | 'MODE' | 'PIP_LIMIT';
  from_value: string;
  to_value: string;
  reason?: string;            // "Hypoxia", "Hypercarbia", "Recruitment"
  linked_problem_id?: string;
}
```

#### ANESTHESIA_DEPTH_ADJUST

```typescript
interface AnesthesiaDepthAdjust {
  action: 'DEEPEN' | 'LIGHTEN';
  method: 'VOLATILE' | 'IV_BOLUS' | 'IV_INFUSION';
  agent?: string;             // "Sevoflurane", "Propofol"

  // Volatile
  mac_from?: number;
  mac_to?: number;

  // IV
  bolus_dose?: string;        // "Propofol 30mg"
  infusion_rate_from?: string;
  infusion_rate_to?: string;

  reason?: string;            // "Patient movement", "BP/HR spike"
  linked_problem_id?: string;
}
```

---

## 2. PIO 結構化圖 (Structured Graph)

### 2.1 核心概念

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PIO = 連結層 (Linking Layer)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   anesthesia_events (底層事件)              pio_* (連結層)                   │
│   ┌──────────────────────────┐             ┌──────────────────────────┐     │
│   │ evt-001: VITAL (BP 75/45)│◄────────────│ Problem: HYPOTENSION     │     │
│   │ evt-002: VASOACTIVE_BOLUS│◄────────────│   └── Intervention       │     │
│   │ evt-003: FLUID_BOLUS     │◄────────────│       └── event_ref_id   │     │
│   │ evt-004: VITAL (BP 95/60)│◄────────────│   └── Outcome            │     │
│   │ evt-005: VITAL (BP 110/70│◄────────────│       └── evidence_refs[]│     │
│   └──────────────────────────┘             └──────────────────────────┘     │
│                                                                              │
│   事件是「真相」，PIO 是「詮釋」                                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Schema 定義

```sql
-- =============================================================================
-- PIO Problem (問題)
-- =============================================================================
CREATE TABLE pio_problems (
    problem_id TEXT PRIMARY KEY,            -- 'PIO-{case_id}-001'
    case_id TEXT NOT NULL,

    -- 問題分類
    problem_type TEXT NOT NULL,             -- enum (見下方)
    severity INTEGER NOT NULL CHECK(severity BETWEEN 1 AND 3),  -- 1=輕, 2=中, 3=重

    -- 時間
    detected_clinical_time DATETIME NOT NULL,
    resolved_clinical_time DATETIME,

    -- 狀態
    status TEXT NOT NULL DEFAULT 'OPEN',    -- 'OPEN', 'WATCHING', 'RESOLVED', 'ABANDONED'

    -- 觸發事件 (通常是發現問題的那筆 VITAL)
    trigger_event_id TEXT,

    -- 稽核
    created_by TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
    FOREIGN KEY (trigger_event_id) REFERENCES anesthesia_events(id)
);

-- =============================================================================
-- PIO Intervention (處置) - 必須連結 Problem + Event
-- =============================================================================
CREATE TABLE pio_interventions (
    intervention_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,               -- 必填！處置必須掛回問題
    case_id TEXT NOT NULL,

    -- 底層事件引用 (必填)
    event_ref_id TEXT NOT NULL,             -- 指向 anesthesia_events.id

    -- 處置類型 (冗餘，方便查詢)
    action_type TEXT NOT NULL,              -- 'VASOACTIVE_BOLUS', 'FLUID_BOLUS', etc.

    -- 時間 (從 event 繼承，冗餘存放)
    performed_clinical_time DATETIME NOT NULL,

    -- 立即反應 (可選)
    immediate_response TEXT,                -- "BP 80/50 after 2 min"

    -- 稽核
    performed_by TEXT NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (problem_id) REFERENCES pio_problems(problem_id),
    FOREIGN KEY (event_ref_id) REFERENCES anesthesia_events(id)
);

-- =============================================================================
-- PIO Outcome (結果) - 必須連結 Problem + Evidence Events
-- =============================================================================
CREATE TABLE pio_outcomes (
    outcome_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,

    -- 結果類型
    outcome_type TEXT NOT NULL,             -- 'IMPROVED', 'NO_CHANGE', 'WORSENED', 'ADVERSE_REACTION'

    -- 證據事件 (可多筆)
    evidence_event_ids TEXT NOT NULL,       -- JSON array: ["evt-004", "evt-005"]

    -- 時間
    observed_clinical_time DATETIME NOT NULL,

    -- 狀態變更
    new_problem_status TEXT,                -- 若此 outcome 導致 problem 狀態變更

    -- 備註
    note TEXT,

    -- 稽核
    recorded_by TEXT NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (problem_id) REFERENCES pio_problems(problem_id)
);
```

### 2.3 Problem Type Enum

```typescript
type ProblemType =
  // 血行動力學
  | 'HYPOTENSION'           // MAP < 65 or SBP < 90
  | 'HYPERTENSION'          // SBP > 160 or MAP > 100
  | 'BRADYCARDIA'           // HR < 50
  | 'TACHYCARDIA'           // HR > 100
  | 'ARRHYTHMIA'            // AF, VT, VF, etc.

  // 呼吸
  | 'HYPOXEMIA'             // SpO2 < 94%
  | 'HYPERCAPNIA'           // EtCO2 > 45
  | 'AIRWAY_DIFFICULTY'     // 困難氣道/重新插管

  // 出血
  | 'BLEEDING_SUSPECTED'    // 出血量異常
  | 'MASSIVE_TRANSFUSION'   // 啟動大量輸血

  // 麻醉深度
  | 'ANESTHESIA_TOO_LIGHT'  // 體動、awareness 跡象
  | 'ANESTHESIA_TOO_DEEP'   // BIS < 40, 血壓過低

  // 其他
  | 'ALLERGIC_REACTION'     // 過敏反應
  | 'MH_SUSPECTED'          // 疑似惡性高熱
  | 'HYPOTHERMIA'           // Temp < 35°C
  | 'EQUIPMENT_ISSUE'       // 設備問題
```

---

## 3. 時間補登強化

### 3.1 補登規則層級

| 延遲時間 | 處理方式 |
|----------|----------|
| ≤ 5 分鐘 | 正常記錄，無標記 |
| 5-30 分鐘 | 自動標記「補登」，顯示 [補登 HH:MM] |
| 30-60 分鐘 | 必填 `late_entry_reason`，需確認 |
| > 60 分鐘 | 必填原因 + **PIN 提升確認** |

### 3.2 補登原因 Enum

```typescript
type LateEntryReason =
  | 'EMERGENCY_HANDLING'    // 緊急處理病人中
  | 'EQUIPMENT_ISSUE'       // 設備/網路問題
  | 'SHIFT_HANDOFF'         // 交班補記
  | 'DOCUMENTATION_CATCH_UP' // 文書補齊
  | 'OTHER'                 // 其他 (需填文字說明)
```

### 3.3 API: 相對時間偏移

**Gemini 建議**: 護士腦中的時間是相對的「五分鐘前」，不是絕對時間。

```typescript
// 請求方式 1: 絕對時間
POST /api/anesthesia/cases/{id}/events
{
  "event_type": "VASOACTIVE_BOLUS",
  "clinical_time": "2026-01-06T10:30:00",  // 絕對時間
  "payload": { ... }
}

// 請求方式 2: 相對偏移 (新增)
POST /api/anesthesia/cases/{id}/events
{
  "event_type": "VASOACTIVE_BOLUS",
  "clinical_time_offset_seconds": -300,    // -5 分鐘 = -300 秒
  "payload": { ... }
}

// 後端計算
if (clinical_time_offset_seconds) {
  clinical_time = recorded_at + offset  // offset 為負數
}
```

### 3.4 UI: 相對時間快捷按鈕

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  事件時間                                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ● 現在 (10:45)                                                             │
│  ○ 指定時間 [  :  ]                                                        │
│                                                                              │
│  快捷偏移:                                                                   │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐                         │
│  │ -5分 │  │-10分 │  │-15分 │  │-20分 │  │-30分 │                         │
│  └──────┘  └──────┘  └──────┘  └──────┘  └──────┘                         │
│     ↑                                                                       │
│   點擊後 clinical_time = 10:40，且 UI 顯示「10:40 (5分鐘前)」              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Quick Scenario Bundle (情境快速包)

### 4.1 設計概念 (Gemini 建議)

```
傳統 PIO: 三個獨立欄位，護士手動填寫
         ↓
Quick Scenario Bundle: 系統根據 Vital 觸發建議，一鍵產生 Problem + Intervention + Event
```

### 4.2 觸發條件與建議

| 觸發條件 | 自動建議 |
|----------|----------|
| MAP < 60 | Problem: HYPOTENSION + 處置選項: Ephedrine / Phenyl / Fluid / Deepen |
| MAP > 100 | Problem: HYPERTENSION + 處置選項: Nicardipine / Deepen / Analgesic |
| HR < 45 | Problem: BRADYCARDIA + 處置選項: Atropine / Ephedrine |
| HR > 120 | Problem: TACHYCARDIA + 處置選項: Esmolol / Deepen / Analgesic |
| SpO2 < 90 | Problem: HYPOXEMIA + 處置選項: FiO2↑ / Suction / Recruitment |

### 4.3 UI: 情境快速卡片

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ 偵測到低血壓 (MAP 55)                                      10:30       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Problem: HYPOTENSION                                    [自動建立 ▼]       │
│                                                                              │
│  選擇處置 (可多選):                                                         │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ ● Ephedrine     │  │ ○ Phenylephrine │  │ ○ Fluid 250ml   │             │
│  │   5mg IV        │  │   100mcg IV     │  │   LR bolus      │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐                                  │
│  │ ○ Deepen        │  │ ○ 通知外科      │                                  │
│  │   Anesthesia    │  │   減少出血      │                                  │
│  └─────────────────┘  └─────────────────┘                                  │
│                                                                              │
│  時間: ● 現在  ○ [-5分] [-10分]                                            │
│                                                                              │
│                                    [取消]  [一鍵記錄 Problem + Intervention] │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.4 一鍵記錄產生的資料

點擊「一鍵記錄」後，系統自動建立:

1. **anesthesia_events** (底層事件)
   ```json
   {
     "id": "evt-123",
     "event_type": "VASOACTIVE_BOLUS",
     "clinical_time": "2026-01-06T10:30:00",
     "payload": {
       "drug_name": "Ephedrine",
       "dose": 5,
       "unit": "mg",
       "route": "IV",
       "indication": "Hypotension",
       "linked_problem_id": "PIO-001"
     }
   }
   ```

2. **pio_problems** (問題)
   ```json
   {
     "problem_id": "PIO-001",
     "problem_type": "HYPOTENSION",
     "severity": 2,
     "detected_clinical_time": "2026-01-06T10:30:00",
     "status": "OPEN",
     "trigger_event_id": "evt-122"  // 觸發的那筆 VITAL
   }
   ```

3. **pio_interventions** (處置連結)
   ```json
   {
     "intervention_id": "INT-001",
     "problem_id": "PIO-001",
     "event_ref_id": "evt-123",  // 連結到 VASOACTIVE_BOLUS 事件
     "action_type": "VASOACTIVE_BOLUS",
     "performed_clinical_time": "2026-01-06T10:30:00"
   }
   ```

---

## 5. Timeline 整合

### 5.1 Timeline 作為主要介面

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Timeline                                               [篩選: All ▼]       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ PIO-001: HYPOTENSION ──────────────────────────────────── RESOLVED ─┐  │
│  │                                                                       │  │
│  │  10:30  🔴 發現: MAP 55 (Severity: 2)                                │  │
│  │  10:31  💊 Ephedrine 5mg IV                           → MAP 58       │  │
│  │  10:35  💧 LR 250ml bolus                             → MAP 62       │  │
│  │  10:40  💊 Phenylephrine 100mcg IV                    → MAP 68       │  │
│  │  10:50  ✅ Resolved: MAP 75                                          │  │
│  │                                                                       │  │
│  │  [+ 新增處置]                              [4 interventions, 20 min]  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  10:55  ● Vitals: BP 115/70, HR 68, SpO2 99%                               │
│                                                                              │
│  11:00  ⏱ MILESTONE: Closure started                                       │
│                                                                              │
│  11:05  ● Vitals: BP 120/75, HR 65, SpO2 99%  [補登 11:20]                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 新增事件 Composer

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  + 新增事件                                                          [X]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  事件類型:                                                                   │
│                                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │  Vital   │ │   藥物   │ │  輸液    │ │  輸血    │ │  呼吸    │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
│                                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ 昇壓劑   │ │麻醉深度  │ │ Problem │ │  Outcome │ │   Note   │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
│                                                                              │
│  連結到問題: [無 ▼] / [PIO-001: HYPOTENSION (OPEN)]                        │
│                                                                              │
│  時間: ● 現在  ○ [-5分] [-10分] [-15分] ○ 指定 [  :  ]                    │
│                                                                              │
│                                                    [取消]  [記錄]           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 庫存連動 (Inventory Linkage)

### 6.1 事件觸發庫存扣減

| 事件類型 | 庫存動作 |
|----------|----------|
| BLOOD_PRODUCT | 扣減血品庫存 (by unit_id) |
| VASOACTIVE_BOLUS | 扣減藥品庫存 (非管制) |
| MED_ADMIN (controlled) | 觸發管制藥品 ledger (現有流程) |
| FLUID_BOLUS | 扣減輸液庫存 (可選) |

### 6.2 實作方式

```python
# routes/anesthesia.py

@router.post("/cases/{case_id}/events")
async def add_event(case_id: str, event: EventCreate):
    # 1. 建立事件
    event_id = create_anesthesia_event(case_id, event)

    # 2. 庫存連動 (if applicable)
    if event.event_type == "BLOOD_PRODUCT" and event.payload.inventory_deduct:
        await deduct_blood_inventory(event.payload.unit_id)

    if event.event_type == "VASOACTIVE_BOLUS":
        await deduct_medication_inventory(
            event.payload.drug_name,
            event.payload.dose,
            event.payload.unit
        )

    return {"event_id": event_id}
```

---

## 7. API 端點總覽

### 7.1 事件 API

```
POST   /api/anesthesia/cases/{id}/events              # 新增事件 (支援 offset)
GET    /api/anesthesia/cases/{id}/events              # 列出所有事件
GET    /api/anesthesia/cases/{id}/timeline            # Timeline 格式 (含 PIO 群組)
```

### 7.2 PIO API

```
# Problem
POST   /api/anesthesia/cases/{id}/pio/problems        # 建立問題
GET    /api/anesthesia/cases/{id}/pio/problems        # 列出問題
PATCH  /api/anesthesia/cases/{id}/pio/problems/{pid}  # 更新狀態

# Intervention (必須有 event_ref_id)
POST   /api/anesthesia/cases/{id}/pio/interventions   # 建立處置連結
GET    /api/anesthesia/cases/{id}/pio/problems/{pid}/interventions

# Outcome
POST   /api/anesthesia/cases/{id}/pio/outcomes        # 記錄結果
GET    /api/anesthesia/cases/{id}/pio/problems/{pid}/outcomes

# Quick Scenario Bundle
POST   /api/anesthesia/cases/{id}/pio/quick           # 一鍵記錄 (Problem + Event + Intervention)
```

### 7.3 Quick Scenario API 範例

```json
POST /api/anesthesia/cases/{id}/pio/quick
{
  "scenario": "HYPOTENSION",
  "detected_value": { "map": 55, "sbp": 75, "dbp": 45 },
  "interventions": [
    {
      "type": "VASOACTIVE_BOLUS",
      "drug_name": "Ephedrine",
      "dose": 5,
      "unit": "mg"
    }
  ],
  "clinical_time_offset_seconds": -120  // 2 分鐘前
}

// Response
{
  "problem_id": "PIO-001",
  "events_created": ["evt-123"],
  "interventions_created": ["INT-001"]
}
```

---

## 8. 實作優先順序

| Phase | 功能 | 工時 | 狀態 |
|-------|------|------|------|
| **1** | 事件類型擴充 (VASOACTIVE, BLOOD, VENT) | 4h | |
| **1** | 相對時間偏移 API | 2h | |
| **1** | 補登強化 (分級 + 原因) | 3h | |
| **2** | PIO Schema + CRUD API | 4h | |
| **2** | PIO 連結層邏輯 (event_ref_id 強制) | 3h | |
| **3** | Quick Scenario Bundle API | 4h | |
| **3** | 情境快速卡片 UI | 6h | |
| **4** | Timeline 整合 (collapsible PIO groups) | 6h | |
| **4** | 庫存連動 | 4h | |
| | **總計** | **36h** | |

---

## 9. 驗收測試

### 9.1 事件類型測試

| 測試 | 預期 |
|------|------|
| 記錄 VASOACTIVE_BOLUS | 事件建立，payload 含 drug/dose/indication |
| 記錄 BLOOD_PRODUCT | 事件建立，庫存扣減觸發 |
| 記錄 VENT_SETTING_CHANGE | 事件建立，from/to 值正確 |

### 9.2 PIO 連結測試

| 測試 | 預期 |
|------|------|
| 建立 Intervention 無 event_ref_id | **拒絕** (400 Bad Request) |
| 建立 Intervention 有 event_ref_id | 成功，連結正確 |
| 查詢 Problem timeline | 顯示所有關聯事件 |

### 9.3 時間補登測試

| 測試 | 預期 |
|------|------|
| offset = -300 (5分鐘) | clinical_time 正確計算，標記補登 |
| offset = -1800 (30分鐘) | 要求填寫 late_entry_reason |
| offset = -3600 (60分鐘) | 要求 PIN 提升確認 |

### 9.4 Quick Scenario 測試

| 測試 | 預期 |
|------|------|
| Quick HYPOTENSION + Ephedrine | 建立 Problem + Event + Intervention，三者正確連結 |
| Quick 選多個處置 | 建立 1 Problem + N Events + N Interventions |

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*Version: 1.6.1*
*Last Updated: 2026-01-06*
*Status: 規格定稿，待實作*
