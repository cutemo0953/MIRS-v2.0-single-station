# MIRS Anesthesia Module v1.6.0 - 術中問題處置記錄 (PIO) 與時間補登

**Version:** 1.6.0
**基於:** v1.5.1
**更新日期:** 2026-01-06
**狀態:** 規格草案

---

## Changelog

### v1.6.0 新增功能

| 功能 | 描述 | 來源 |
|------|------|------|
| **PIO 記錄系統** | 完整的「問題-處置-結果」(Problem-Intervention-Outcome) 記錄 | 麻醉護士回饋 |
| **時間補登** | 先處理病人、後補記錄，可修改事件時間 | 麻醉護士回饋 |

---

## 1. PIO 記錄系統 (Problem-Intervention-Outcome)

### 1.1 設計理念

麻醉照護的核心是**持續監測 → 發現問題 → 處置介入 → 確認結果**的循環。
目前系統只有獨立的 Vitals 和 Medication 記錄，缺乏「因果關係」的呈現。

**PIO 系統目標:**
1. 清楚記錄「為什麼做這個處置」
2. 追蹤處置後的結果
3. 支援多重處置（一個問題可能需要多次介入）
4. 未解決的問題持續追蹤直到結案

### 1.2 資料模型

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PIO Record (問題處置記錄)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Problem (問題)                                                      │    │
│  │  ├── problem_id: "PIO-001"                                          │    │
│  │  ├── category: "HEMODYNAMIC"                                        │    │
│  │  ├── problem_type: "HYPOTENSION"                                    │    │
│  │  ├── severity: "MODERATE"                                           │    │
│  │  ├── detected_at: "10:30"                                           │    │
│  │  ├── detected_value: "BP 75/45, MAP 55"                             │    │
│  │  └── status: "ACTIVE" | "MONITORING" | "RESOLVED"                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Interventions (處置) - 可多筆                                       │    │
│  │  ├── [1] 10:31 Ephedrine 5mg IV                                     │    │
│  │  ├── [2] 10:35 LR 250ml bolus                                       │    │
│  │  ├── [3] 10:40 Phenylephrine 100mcg IV                              │    │
│  │  └── [4] 10:45 Notify surgeon, reduce bleeding                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Outcomes (結果) - 追蹤至解決                                        │    │
│  │  ├── [1] 10:35 BP 85/50 - 改善中                                    │    │
│  │  ├── [2] 10:45 BP 95/60 - 持續改善                                  │    │
│  │  └── [3] 10:55 BP 110/70 - 已解決 ✓                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 問題分類 (Problem Categories)

#### 1.3.1 血行動力學 (Hemodynamic)

| 問題類型 | 定義 | 嚴重度判斷 |
|----------|------|-----------|
| **HYPOTENSION** | MAP < 65 或 SBP < 90 | MILD: MAP 60-65 / MOD: MAP 50-60 / SEVERE: MAP < 50 |
| **HYPERTENSION** | SBP > 160 或 MAP > 100 | MILD: SBP 160-180 / MOD: 180-200 / SEVERE: > 200 |
| **BRADYCARDIA** | HR < 50 | MILD: 45-50 / MOD: 40-45 / SEVERE: < 40 |
| **TACHYCARDIA** | HR > 100 | MILD: 100-120 / MOD: 120-150 / SEVERE: > 150 |
| **ARRHYTHMIA** | 心律不整 | 依類型: AF, VT, VF, PVC, PAC |
| **BLEEDING** | 異常出血 | MILD: EBL < 500ml / MOD: 500-1000ml / SEVERE: > 1000ml |

#### 1.3.2 呼吸系統 (Respiratory)

| 問題類型 | 定義 | 嚴重度判斷 |
|----------|------|-----------|
| **HYPOXIA** | SpO2 < 94% | MILD: 90-94% / MOD: 85-90% / SEVERE: < 85% |
| **HYPERCAPNIA** | EtCO2 > 45 | MILD: 45-50 / MOD: 50-60 / SEVERE: > 60 |
| **HYPOCAPNIA** | EtCO2 < 30 | MILD: 25-30 / MOD: 20-25 / SEVERE: < 20 |
| **BRONCHOSPASM** | 呼吸道阻力增加 | 依 Peak pressure 變化 |
| **DIFFICULT_VENTILATION** | 通氣困難 | 依 compliance 變化 |
| **ASPIRATION** | 誤吸 | 依吸入物及影響程度 |

#### 1.3.3 麻醉相關 (Anesthesia)

| 問題類型 | 定義 | 嚴重度判斷 |
|----------|------|-----------|
| **AWARENESS** | 術中覺醒跡象 | 緊急 |
| **DEPTH_LIGHT** | 麻醉深度不足 | 體動、血壓心跳上升 |
| **DEPTH_DEEP** | 麻醉過深 | BIS < 40, 血壓過低 |
| **MH_SUSPECT** | 疑似惡性高熱 | EtCO2 急升、體溫升高、肌強直 |
| **ANAPHYLAXIS** | 過敏反應 | MILD/MOD/SEVERE |
| **PONV** | 術中噁心嘔吐 | MILD: 噁心 / MOD: 嘔吐 / SEVERE: 持續嘔吐 |

#### 1.3.4 體液與代謝 (Fluid & Metabolic)

| 問題類型 | 定義 |
|----------|------|
| **HYPOVOLEMIA** | 低血容 |
| **HYPERVOLEMIA** | 容積過載 |
| **ELECTROLYTE** | 電解質異常 (K+, Na+, Ca2+) |
| **GLUCOSE** | 血糖異常 |
| **HYPOTHERMIA** | 體溫 < 35°C |
| **HYPERTHERMIA** | 體溫 > 38°C |
| **ACIDOSIS** | pH < 7.35 |
| **COAGULOPATHY** | 凝血異常 |

#### 1.3.5 設備與技術 (Equipment & Technical)

| 問題類型 | 定義 |
|----------|------|
| **ETT_ISSUE** | ETT 問題 (移位、阻塞、脫出) |
| **IV_ISSUE** | IV 問題 (滲漏、阻塞) |
| **ARTERIAL_LINE** | A-line 問題 |
| **MONITOR_FAILURE** | 監測器故障 |
| **EQUIPMENT_ALARM** | 設備警報 |

### 1.4 處置分類 (Intervention Categories)

#### 1.4.1 藥物處置 (Medication)

```typescript
interface MedicationIntervention {
  type: 'MEDICATION';
  subtype: 'VASOPRESSOR' | 'VASODILATOR' | 'INOTROPE' | 'CHRONOTROPE' |
           'BRONCHODILATOR' | 'ANTIEMETIC' | 'ANALGESIC' | 'SEDATIVE' |
           'NEUROMUSCULAR' | 'REVERSAL' | 'STEROID' | 'ANTIBIOTIC' | 'OTHER';

  drug: {
    code?: string;
    name: string;
    dose: number;
    unit: string;
    route: 'IV_BOLUS' | 'IV_INFUSION' | 'IM' | 'SC' | 'PO' | 'INH' | 'TOPICAL';
    infusion_rate?: string;  // "5mcg/kg/min"
  };

  indication: string;  // 連結到 problem_id
}
```

**常用藥物快捷範本:**

| 類別 | 藥物 | 預設劑量 | 適應症 |
|------|------|---------|--------|
| **昇壓劑** | Ephedrine | 5-10 mg IV | Hypotension |
| | Phenylephrine | 50-100 mcg IV | Hypotension (reflex brady) |
| | Norepinephrine | 0.05-0.2 mcg/kg/min | Severe hypotension |
| | Epinephrine | 10-100 mcg IV | Cardiac arrest, anaphylaxis |
| **降壓劑** | Nicardipine | 0.5-1 mg IV | Hypertension |
| | Labetalol | 5-10 mg IV | Hypertension |
| | Esmolol | 0.5 mg/kg IV | Tachycardia |
| **心律** | Atropine | 0.5 mg IV | Bradycardia |
| | Adenosine | 6-12 mg IV | SVT |
| | Amiodarone | 150 mg IV | VT/VF |
| **呼吸道** | Salbutamol | 2 puffs INH | Bronchospasm |
| | Hydrocortisone | 100 mg IV | Bronchospasm, allergy |
| | Diphenhydramine | 25-50 mg IV | Allergy |
| **止吐** | Ondansetron | 4 mg IV | PONV |
| | Metoclopramide | 10 mg IV | PONV |
| **其他** | Dexamethasone | 4-8 mg IV | Airway edema, PONV |
| | Sugammadex | 2-4 mg/kg IV | Neuromuscular reversal |

#### 1.4.2 輸液/輸血 (Fluid/Blood)

```typescript
interface FluidIntervention {
  type: 'FLUID' | 'BLOOD_PRODUCT';

  product: {
    type: 'CRYSTALLOID' | 'COLLOID' | 'PRBC' | 'FFP' | 'PLATELET' | 'CRYO';
    name: string;  // "LR", "NS", "Voluven"
    volume_ml: number;
    rate?: string;  // "wide open", "over 30min"
    unit_id?: string;  // 血品單位號碼
  };

  indication: string;
}
```

#### 1.4.3 呼吸道處置 (Airway/Ventilation)

```typescript
interface AirwayIntervention {
  type: 'AIRWAY' | 'VENTILATION';

  action: 'FIO2_ADJUST' | 'PEEP_ADJUST' | 'TV_ADJUST' | 'RR_ADJUST' |
          'MODE_CHANGE' | 'SUCTION' | 'REPOSITION_ETT' | 'BRONCHOSCOPY' |
          'REINTUBATION' | 'MANUAL_VENTILATION' | 'RECRUITMENT';

  detail: {
    from?: string;  // "FiO2 40%"
    to?: string;    // "FiO2 60%"
    note?: string;
  };
}
```

#### 1.4.4 麻醉調整 (Anesthesia Adjustment)

```typescript
interface AnesthesiaIntervention {
  type: 'ANESTHESIA_ADJUSTMENT';

  action: 'DEEPEN' | 'LIGHTEN' | 'AGENT_CHANGE' | 'BOLUS' | 'INFUSION_ADJUST';

  detail: {
    agent: string;  // "Sevoflurane", "Propofol", "Remifentanil"
    from?: string;  // "MAC 1.0", "150 mcg/kg/min"
    to?: string;    // "MAC 1.5", "200 mcg/kg/min"
    bolus?: string; // "Propofol 30mg"
  };
}
```

#### 1.4.5 其他處置

```typescript
interface OtherIntervention {
  type: 'POSITIONING' | 'WARMING' | 'COOLING' | 'COMPRESSION' |
        'NOTIFY_SURGEON' | 'CALL_FOR_HELP' | 'PAUSE_SURGERY' | 'OTHER';

  description: string;
}
```

### 1.5 結果追蹤 (Outcome Tracking)

```typescript
interface Outcome {
  timestamp: string;
  status: 'IMPROVING' | 'STABLE' | 'WORSENING' | 'RESOLVED' | 'ESCALATED';

  // 數值追蹤
  follow_up_values?: {
    vital_type?: string;
    value?: string;  // "BP 95/60", "SpO2 96%"
  };

  // 自由文字
  note?: string;

  // 結案資訊
  resolution?: {
    resolved_at: string;
    total_interventions: number;
    summary: string;
  };
}
```

### 1.6 PIO 狀態機

```
                    ┌─────────────┐
                    │   ACTIVE    │ ← 新發現問題
                    │   (紅色)    │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
    ┌───────────┐  ┌───────────┐  ┌───────────┐
    │ IMPROVING │  │  STABLE   │  │ WORSENING │
    │  (橙色)   │  │  (黃色)   │  │  (紅色)   │
    └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
          │              │              │
          │              │              ▼
          │              │      ┌───────────┐
          │              │      │ ESCALATED │ → 升級處理
          │              │      │  (紫色)   │   (呼叫支援)
          │              │      └───────────┘
          │              │
          └──────┬───────┘
                 │
                 ▼
         ┌───────────┐
         │ RESOLVED  │ ← 問題解決
         │  (綠色)   │
         └───────────┘
```

### 1.7 UI 設計：PIO 記錄介面

#### 1.7.1 主畫面 - 活躍問題儀表板

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  麻醉記錄  │  Timeline  │  Vitals  │  管藥  │ ★ PIO │                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  === 活躍問題 (2) ===                                             [+ 新問題] │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 🔴 PIO-001  HYPOTENSION (血壓低)                        10:30 開始  │    │
│  │    ├── 發現: BP 75/45, MAP 55                                       │    │
│  │    ├── 處置: Ephedrine 5mg (10:31) → LR 250ml (10:35) → ...        │    │
│  │    ├── 目前: BP 95/60 (改善中) 🟠                                   │    │
│  │    └── [追蹤 Vitals] [新增處置] [標記解決]                          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 🟡 PIO-002  HYPOTHERMIA (低體溫)                        09:45 開始  │    │
│  │    ├── 發現: Temp 34.8°C                                            │    │
│  │    ├── 處置: Bair Hugger ON, Fluid warmer ON                        │    │
│  │    ├── 目前: Temp 35.5°C (穩定) 🟡                                  │    │
│  │    └── [追蹤 Vitals] [新增處置] [標記解決]                          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  === 已解決問題 (1) ===                                          [展開 ▼]   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ ✅ PIO-000  BRADYCARDIA → Resolved in 5 min (1 intervention)        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  === 快速記錄 ===                                                           │
│                                                                              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ BP Low  │ │ BP High │ │SpO2 Low │ │ HR Low  │ │Bleeding │ │ Other   │  │
│  │   ▼     │ │   ▼     │ │   ▼     │ │   ▼     │ │   ▼     │ │   ▼     │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 1.7.2 新增問題 Modal

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  新增問題                                                            [X]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  === 問題分類 ===                                                           │
│                                                                              │
│  [血行動力學▼]  [呼吸系統]  [麻醉相關]  [體液代謝]  [設備技術]  [其他]     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ● 血壓低 (Hypotension)                                             │    │
│  │  ○ 血壓高 (Hypertension)                                            │    │
│  │  ○ 心跳過慢 (Bradycardia)                                           │    │
│  │  ○ 心跳過快 (Tachycardia)                                           │    │
│  │  ○ 心律不整 (Arrhythmia)                                            │    │
│  │  ○ 出血 (Bleeding)                                                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  === 發現數值 ===                                                           │
│                                                                              │
│  BP: [ 75 ] / [ 45 ]    MAP: [ 55 ] (自動計算)                             │
│                                                                              │
│  === 嚴重度 ===                                                             │
│                                                                              │
│  ○ MILD (輕度)    ● MODERATE (中度)    ○ SEVERE (嚴重)                     │
│                                                                              │
│  === 發現時間 ===                                                           │
│                                                                              │
│  ● 現在 (10:30)    ○ 指定時間 [    :    ]                                  │
│                                                                              │
│  === 立即處置 (可選) ===                                                    │
│                                                                              │
│  ☑ Ephedrine 5mg IV                                                        │
│  ☐ Phenylephrine 100mcg IV                                                 │
│  ☐ LR 250ml bolus                                                          │
│  ☐ 通知外科醫師                                                            │
│  ☐ 其他: [________________]                                                │
│                                                                              │
│                                           [取消]    [建立問題並記錄處置]    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 1.7.3 追蹤/新增處置 Modal

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PIO-001: 血壓低 (Hypotension)                                       [X]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  === 問題摘要 ===                                                           │
│  發現: 10:30 | BP 75/45, MAP 55 | 嚴重度: MODERATE                         │
│                                                                              │
│  === 處置歷程 ===                                                           │
│                                                                              │
│  10:31  💊 Ephedrine 5mg IV                              → BP 80/50        │
│  10:35  💧 LR 250ml bolus                                → BP 85/55        │
│  10:40  💊 Phenylephrine 100mcg IV                       → BP 92/58        │
│  10:45  📢 通知外科減少出血                               → EBL 穩定       │
│                                                                              │
│  === 目前狀態 ===                                                           │
│                                                                              │
│  最近 Vitals: BP 95/60, HR 72, SpO2 98%  (10:50)                           │
│  狀態: 🟠 IMPROVING (改善中)                                                │
│                                                                              │
│  === 新增處置 ===                                                           │
│                                                                              │
│  [藥物▼]  [輸液]  [輸血]  [呼吸]  [麻醉]  [其他]                           │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  藥物: [Norepinephrine        ▼]                                    │    │
│  │  劑量: [0.05] [mcg/kg/min ▼]                                        │    │
│  │  給藥: [IV infusion ▼]                                              │    │
│  │  備註: [________________]                                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  === 或 標記狀態 ===                                                        │
│                                                                              │
│  [改善中 🟠]  [穩定 🟡]  [惡化 🔴]  [✅ 已解決]  [升級處理 🟣]             │
│                                                                              │
│                                              [取消]    [記錄處置/狀態]      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.8 Schema 設計

```sql
-- =============================================================================
-- PIO 問題主表
-- =============================================================================
CREATE TABLE pio_problems (
    id TEXT PRIMARY KEY,                    -- 'PIO-YYYYMMDD-NNN'
    case_id TEXT NOT NULL,

    -- 問題分類
    category TEXT NOT NULL,                 -- 'HEMODYNAMIC', 'RESPIRATORY', ...
    problem_type TEXT NOT NULL,             -- 'HYPOTENSION', 'HYPOXIA', ...
    severity TEXT NOT NULL,                 -- 'MILD', 'MODERATE', 'SEVERE'

    -- 發現時
    detected_at DATETIME NOT NULL,
    detected_value TEXT,                    -- JSON: {"bp_sys": 75, "bp_dia": 45, "map": 55}
    detected_note TEXT,

    -- 狀態追蹤
    status TEXT NOT NULL DEFAULT 'ACTIVE',  -- 'ACTIVE', 'IMPROVING', 'STABLE', 'WORSENING', 'ESCALATED', 'RESOLVED'
    status_updated_at DATETIME,

    -- 解決時
    resolved_at DATETIME,
    resolution_summary TEXT,

    -- 稽核
    created_by TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);

-- =============================================================================
-- PIO 處置記錄 (多筆對一個問題)
-- =============================================================================
CREATE TABLE pio_interventions (
    id TEXT PRIMARY KEY,                    -- UUID
    problem_id TEXT NOT NULL,
    case_id TEXT NOT NULL,

    -- 處置分類
    intervention_type TEXT NOT NULL,        -- 'MEDICATION', 'FLUID', 'BLOOD', 'AIRWAY', 'ANESTHESIA', 'OTHER'

    -- 處置內容 (JSON，schema 依 type 不同)
    detail TEXT NOT NULL,

    -- 時間
    performed_at DATETIME NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 處置後立即觀察
    immediate_response TEXT,                -- "BP 80/50"

    -- 稽核
    performed_by TEXT NOT NULL,

    FOREIGN KEY (problem_id) REFERENCES pio_problems(id),
    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);

-- =============================================================================
-- PIO 結果追蹤 (狀態變化記錄)
-- =============================================================================
CREATE TABLE pio_outcomes (
    id TEXT PRIMARY KEY,                    -- UUID
    problem_id TEXT NOT NULL,

    -- 狀態
    status TEXT NOT NULL,                   -- 'IMPROVING', 'STABLE', 'WORSENING', 'RESOLVED', 'ESCALATED'

    -- 追蹤數值
    follow_up_value TEXT,                   -- JSON: {"bp_sys": 95, "bp_dia": 60}
    note TEXT,

    -- 時間
    observed_at DATETIME NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    recorded_by TEXT NOT NULL,

    FOREIGN KEY (problem_id) REFERENCES pio_problems(id)
);

-- Indexes
CREATE INDEX idx_pio_problems_case ON pio_problems(case_id, status);
CREATE INDEX idx_pio_interventions_problem ON pio_interventions(problem_id);
CREATE INDEX idx_pio_outcomes_problem ON pio_outcomes(problem_id);
```

### 1.9 API 端點

```
# 問題管理
POST   /api/anesthesia/cases/{id}/pio/problems              # 建立問題
GET    /api/anesthesia/cases/{id}/pio/problems              # 列出問題
GET    /api/anesthesia/cases/{id}/pio/problems/{pid}        # 問題詳情
PATCH  /api/anesthesia/cases/{id}/pio/problems/{pid}/status # 更新狀態

# 處置記錄
POST   /api/anesthesia/cases/{id}/pio/problems/{pid}/interventions  # 新增處置
GET    /api/anesthesia/cases/{id}/pio/problems/{pid}/interventions  # 處置歷程

# 結果追蹤
POST   /api/anesthesia/cases/{id}/pio/problems/{pid}/outcomes       # 記錄結果
GET    /api/anesthesia/cases/{id}/pio/problems/{pid}/timeline       # 完整時間軸

# 快速記錄 (問題+處置一次建立)
POST   /api/anesthesia/cases/{id}/pio/quick                         # 快速記錄
```

### 1.10 Timeline 整合

PIO 記錄應與現有 Timeline 整合顯示：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Timeline (整合 Vitals + PIO)                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  10:55  ● Vitals: BP 110/70, HR 68, SpO2 99%                               │
│         ✅ PIO-001 已解決 (血壓低) - 共 4 次處置, 歷時 25 分鐘              │
│                                                                              │
│  10:50  ● Vitals: BP 95/60, HR 72, SpO2 98%                                │
│                                                                              │
│  10:45  🟠 PIO-001 改善中                                                   │
│         💊 Phenylephrine 100mcg IV → BP 92/58                              │
│         📢 通知外科減少出血                                                 │
│                                                                              │
│  10:40  ● Vitals: BP 85/55, HR 78, SpO2 97%                                │
│                                                                              │
│  10:35  💧 LR 250ml bolus (PIO-001) → BP 85/55                             │
│                                                                              │
│  10:31  💊 Ephedrine 5mg IV (PIO-001) → BP 80/50                           │
│                                                                              │
│  10:30  🔴 PIO-001 發現: 血壓低 (BP 75/45, MAP 55) - MODERATE              │
│                                                                              │
│  10:25  ● Vitals: BP 120/75, HR 65, SpO2 99%                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 時間補登功能 (Retrospective Entry)

### 2.1 問題描述

麻醉護士反映：目前時間無法改，但實際上有時要先處理病人、再回去補記錄。

**臨床場景:**
1. 病人血壓突然下降，護士立即處理
2. 穩定後才有時間記錄
3. 需要記錄**實際發生時間**（如 10:30），而非**記錄時間**（如 10:45）

### 2.2 現有架構分析

```sql
-- 現有 anesthesia_events 表已有兩個時間欄位:
clinical_time DATETIME NOT NULL,    -- 臨床事件實際發生時間
recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 系統記錄時間
```

**問題:** 目前 UI 未提供 `clinical_time` 編輯功能，預設為當前時間。

### 2.3 解決方案：允許設定過去時間

#### 2.3.1 時間輸入規則

| 規則 | 說明 |
|------|------|
| 允許過去時間 | `clinical_time` 可設為案例開始後的任意時間 |
| 禁止未來時間 | `clinical_time` 不可超過當前時間 |
| 禁止案例前時間 | `clinical_time` 不可早於 `anesthesia_start_at` |
| 記錄時間不可改 | `recorded_at` 永遠是系統當前時間 |
| 補登標記 | 若 `clinical_time` 與 `recorded_at` 差距 > 5分鐘，標記為「補登」 |

#### 2.3.2 補登識別邏輯

```python
def is_retrospective_entry(event) -> bool:
    """判斷是否為補登記錄"""
    time_diff = event.recorded_at - event.clinical_time
    return time_diff.total_seconds() > 300  # > 5 分鐘視為補登

def get_entry_badge(event) -> str:
    """取得記錄標籤"""
    if is_retrospective_entry(event):
        return "補登"  # 顯示於 UI
    return ""
```

### 2.4 UI 設計：時間選擇器

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  記錄 Vitals                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  === 事件時間 ===                                                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ○ 現在 (11:45)                                                      │    │
│  │  ● 指定時間 [ 11 : 30 ]  ← 時間選擇器                               │    │
│  │                                                                      │    │
│  │  快捷: [5分鐘前] [10分鐘前] [15分鐘前] [30分鐘前]                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ⚠ 此記錄將標記為「補登」(記錄時間: 11:45, 事件時間: 11:30)               │
│                                                                              │
│  === Vitals 數值 ===                                                         │
│                                                                              │
│  BP: [___]/[___]  HR: [___]  SpO2: [___]%  ...                             │
│                                                                              │
│                                                    [取消]  [確認記錄]        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.5 時間選擇器元件

```html
<!-- 時間選擇器元件 -->
<div class="time-selector" x-data="{ mode: 'now', customTime: null }">
    <label class="flex items-center gap-2 p-2 rounded cursor-pointer"
           :class="mode === 'now' ? 'bg-indigo-100' : 'bg-gray-50'"
           @click="mode = 'now'">
        <input type="radio" x-model="mode" value="now">
        <span>現在</span>
        <span class="text-gray-500" x-text="currentTime"></span>
    </label>

    <label class="flex items-center gap-2 p-2 rounded cursor-pointer"
           :class="mode === 'custom' ? 'bg-indigo-100' : 'bg-gray-50'"
           @click="mode = 'custom'">
        <input type="radio" x-model="mode" value="custom">
        <span>指定時間</span>
        <input type="time"
               x-model="customTime"
               :disabled="mode !== 'custom'"
               class="ml-2 px-2 py-1 border rounded">
    </label>

    <!-- 快捷按鈕 -->
    <div class="flex gap-2 mt-2" x-show="mode === 'custom'">
        <button @click="setTimeOffset(5)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">5分鐘前</button>
        <button @click="setTimeOffset(10)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">10分鐘前</button>
        <button @click="setTimeOffset(15)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">15分鐘前</button>
        <button @click="setTimeOffset(30)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">30分鐘前</button>
    </div>

    <!-- 補登提示 -->
    <div x-show="mode === 'custom'"
         class="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-sm">
        <span class="text-amber-700">
            此記錄將標記為「補登」
        </span>
    </div>
</div>
```

### 2.6 Timeline 顯示補登標記

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Timeline                                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  11:45  ● Vitals: BP 120/75, HR 68, SpO2 99%                               │
│                                                                              │
│  11:30  ● Vitals: BP 85/55, HR 95, SpO2 94%  [補登 11:45]                  │
│         │                                     ↑ 顯示實際記錄時間            │
│         │                                                                   │
│  11:30  ⚠ INTERVENTION: BP Low → Ephedrine 5mg  [補登 11:45]               │
│                                                                              │
│  11:15  ● Vitals: BP 115/70, HR 72, SpO2 98%                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.7 API 請求範例

```json
// POST /api/anesthesia/cases/{id}/events
{
  "event_type": "VITAL_SIGN",
  "clinical_time": "2026-01-06T11:30:00",  // 實際發生時間 (可設為過去)
  "payload": {
    "bp_sys": 85,
    "bp_dia": 55,
    "hr": 95,
    "spo2": 94
  }
}

// 回應
{
  "id": "evt-xxx",
  "event_type": "VITAL_SIGN",
  "clinical_time": "2026-01-06T11:30:00",
  "recorded_at": "2026-01-06T11:45:23",    // 系統自動設定
  "is_retrospective": true,                 // 補登標記
  "payload": { ... }
}
```

---

## 3. Schema 變更

### 3.1 無需修改現有表格

現有 `anesthesia_events` 表已支援 `clinical_time` 和 `recorded_at` 分離，無需 ALTER TABLE。

### 3.2 建議新增 View

```sql
-- 方便查詢補登記錄
CREATE VIEW retrospective_entries AS
SELECT
    id,
    case_id,
    event_type,
    clinical_time,
    recorded_at,
    (julianday(recorded_at) - julianday(clinical_time)) * 24 * 60 as delay_minutes,
    CASE
        WHEN (julianday(recorded_at) - julianday(clinical_time)) * 24 * 60 > 5
        THEN 1
        ELSE 0
    END as is_retrospective,
    payload,
    actor_id
FROM anesthesia_events
WHERE recorded_at > clinical_time;
```

---

## 4. 實作優先順序

### Phase 1: 時間補登 (基礎功能)

| 優先級 | 功能 | 預估工時 |
|--------|------|----------|
| **P0** | 時間選擇器 UI 元件 | 2 小時 |
| **P0** | API 接受過去時間 + 驗證 | 1 小時 |
| **P0** | Timeline 補登標記顯示 | 1 小時 |

### Phase 2: PIO 系統核心

| 優先級 | 功能 | 預估工時 |
|--------|------|----------|
| **P0** | PIO Schema (3 tables) | 1 小時 |
| **P0** | PIO 問題 CRUD API | 3 小時 |
| **P0** | PIO 處置 API | 2 小時 |
| **P0** | PIO Outcomes API | 2 小時 |
| **P1** | PIO Tab UI (活躍問題儀表板) | 4 小時 |
| **P1** | 新增問題 Modal | 3 小時 |
| **P1** | 追蹤/新增處置 Modal | 3 小時 |

### Phase 3: 快捷功能

| 優先級 | 功能 | 預估工時 |
|--------|------|----------|
| **P1** | 快速記錄 API (問題+處置一次建立) | 2 小時 |
| **P1** | 常見問題快捷按鈕 | 3 小時 |
| **P1** | 常用藥物範本 | 2 小時 |
| **P2** | Timeline 整合 PIO 事件 | 3 小時 |
| **P2** | PIO 案例摘要報表 | 2 小時 |

### 總工時估算

| Phase | 工時 |
|-------|------|
| Phase 1 (時間補登) | 4 小時 |
| Phase 2 (PIO 核心) | 18 小時 |
| Phase 3 (快捷功能) | 12 小時 |
| **總計** | **34 小時** |

---

## 5. 驗收測試

### 5.1 時間補登測試

| 測試案例 | 預期結果 |
|----------|----------|
| 記錄 Vitals 選擇「10分鐘前」 | `clinical_time` = now - 10min, 顯示「補登」標籤 |
| 記錄 Vitals 選擇「現在」 | `clinical_time` ≈ `recorded_at`, 無補登標籤 |
| 輸入未來時間 | 顯示錯誤「時間不可超過現在」 |
| 輸入案例開始前時間 | 顯示錯誤「時間不可早於麻醉開始」 |

### 5.2 PIO 系統測試

| 測試案例 | 預期結果 |
|----------|----------|
| 建立問題「血壓低」 | PIO 卡片顯示在活躍問題區，狀態 ACTIVE (紅色) |
| 對問題新增處置「Ephedrine 5mg」 | 處置歷程新增一筆，顯示處置時間 |
| 記錄處置後 Vitals | 可連結到問題，顯示 immediate_response |
| 標記問題「改善中」 | 狀態變 IMPROVING (橙色) |
| 標記問題「已解決」 | 狀態變 RESOLVED (綠色)，移至已解決區 |
| 點擊快捷「BP Low → Ephedrine」 | 一次建立 Problem + Intervention |
| 問題有多次處置 | 處置歷程正確顯示所有處置 |
| 案例結案時有活躍問題 | 顯示警告「尚有未解決問題」 |

### 5.3 Timeline 整合測試

| 測試案例 | 預期結果 |
|----------|----------|
| PIO 事件顯示在 Timeline | 問題發現、處置、結果變化都有顯示 |
| Timeline 篩選 PIO | 可篩選只看 PIO 相關事件 |
| PIO 卡片點擊 Timeline 連結 | 跳轉到該時間點 |

---

## 6. 安全與稽核考量

### 6.1 補登的法律效力

| 考量 | 措施 |
|------|------|
| 補登記錄的真實性 | 保留 `recorded_at` 做為稽核證據 |
| 防止濫用 | 報表可篩選補登記錄，異常延遲可被審查 |
| 時間限制 | 考慮限制最大補登間隔 (如 2 小時內) |

### 6.2 補登報表

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  補登記錄報表 (案例: ANES-20260106-001)                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  總事件數: 45                                                                │
│  補登記錄: 8 (17.8%)                                                         │
│  平均延遲: 12.3 分鐘                                                         │
│  最大延遲: 28 分鐘                                                           │
│                                                                              │
│  明細:                                                                       │
│  ┌──────────┬────────────┬────────────┬────────────┬───────────┐           │
│  │ 事件類型  │ 事件時間   │ 記錄時間   │ 延遲(分鐘) │ 記錄者    │           │
│  ├──────────┼────────────┼────────────┼────────────┼───────────┤           │
│  │ VITAL    │ 11:30      │ 11:45      │ 15         │ 護士A     │           │
│  │ INTERVEN │ 11:30      │ 11:47      │ 17         │ 護士A     │           │
│  │ VITAL    │ 11:35      │ 11:48      │ 13         │ 護士A     │           │
│  └──────────┴────────────┴────────────┴────────────┴───────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*Version: 1.6.0*
*Last Updated: 2026-01-06*
*Status: 規格草案，待實作*
