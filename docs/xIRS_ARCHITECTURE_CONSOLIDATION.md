# xIRS 架構收斂 - 以護理為核心串聯

**版本**: v1.0
**日期**: 2026-01-07
**狀態**: Draft
**整合來源**: Claude Code + ChatGPT + Gemini 分析

---

## 1. 核心問題診斷

### 1.1 三方共識

| 問題類型 | 描述 | 來源 |
|----------|------|------|
| **功能碎片化** | 各 PWA 獨立造輪子，缺乏共用核心 | Gemini |
| **因果斷裂** | 里程碑式記錄無法表達「為何這樣做」| ChatGPT |
| **執行閉環缺失** | 醫師開單 → 護理執行 → 確認完成的鏈路斷開 | Gemini |
| **時間語意混亂** | 事件發生時間 ≠ 輸入時間，缺乏稽核機制 | ChatGPT |
| **角色邊界模糊** | CIRS/MIRS 功能重疊，PWA 職責不清 | Claude |

### 1.2 碎片化現況

```
                現況：散落的珍珠

  [Triage PWA]     [Doctor PWA]     [Anesthesia PWA]
       │                │                  │
       ▼                ▼                  ▼
  registrations      orders?          anesthesia_events
  (含 VS JSON)     (無執行確認)        (獨立 VS)

  [Pharmacy PWA]   [EMT PWA]         [MIRS Index]
       │                │                  │
       ▼                ▼                  ▼
   扣庫存?         transfer_events    處置耗材記錄
  (誰給的藥?)      (又一個 VS)        (又扣一次庫存?)
```

**問題**：
1. Vital Signs 分散在至少 4 個地方
2. 醫囑開了，沒人知道有沒有執行
3. 庫存在多處被「扣」，真相在哪？
4. 病患從手術室出來，去哪了？

---

## 2. 統一資料核心 (The Data Layer)

### 2.1 設計原則

```
原則 1: 單一真相來源 (Single Source of Truth)
原則 2: 事件溯源 (Event Sourcing) - 不可變事件流
原則 3: 因果可追溯 (Causality Traceable)
原則 4: 離線優先 (Offline First)
```

### 2.2 核心資料表重整

```sql
-- ═══════════════════════════════════════════════════════════════
-- 1. 全域生命徵象庫 (Universal Vital Signs)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE vital_signs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,           -- 連結到 registrations.id 或 person

    -- 時間戳記 (雙時間軸)
    event_time INTEGER NOT NULL,       -- 臨床發生時間 (timeline 渲染用)
    recorded_at INTEGER NOT NULL,      -- 輸入時間 (稽核用)
    time_source TEXT DEFAULT 'NOW',    -- NOW | BACKDATED | CORRECTED

    -- 來源情境
    source_context TEXT NOT NULL,      -- TRIAGE | ER | OR | PACU | WARD | AMBULANCE
    source_pwa TEXT,                   -- 來自哪個 PWA
    source_case_id TEXT,               -- 關聯案例 (anesthesia_case, transfer_mission 等)

    -- 數值
    hr INTEGER,                        -- Heart Rate
    sbp INTEGER,                       -- Systolic BP
    dbp INTEGER,                       -- Diastolic BP
    spo2 INTEGER,                      -- SpO2
    rr INTEGER,                        -- Respiratory Rate
    temp REAL,                         -- Temperature
    etco2 INTEGER,                     -- End-tidal CO2 (手術/轉送用)
    gcs_e INTEGER,                     -- GCS - Eye
    gcs_v INTEGER,                     -- GCS - Verbal
    gcs_m INTEGER,                     -- GCS - Motor

    -- 補充
    notes TEXT,
    recorded_by TEXT,

    -- 稽核
    corrected_from INTEGER,            -- 若為更正，指向原始 id
    correction_reason TEXT
);

CREATE INDEX idx_vs_person_time ON vital_signs(person_id, event_time);
CREATE INDEX idx_vs_context ON vital_signs(source_context);


-- ═══════════════════════════════════════════════════════════════
-- 2. 醫囑表 (Orders) - 醫師開的所有指令
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE orders (
    id TEXT PRIMARY KEY,               -- ORD-{timestamp}-{seq}
    person_id TEXT NOT NULL,

    order_type TEXT NOT NULL,          -- MEDICATION | PROCEDURE | LAB | TRANSFER | DIET

    -- 內容
    item_code TEXT,                    -- 藥品碼/處置碼/檢驗碼
    item_name TEXT NOT NULL,
    dosage TEXT,                       -- "10mg" / "1 unit"
    route TEXT,                        -- PO | IV | IM | SC | TOPICAL
    frequency TEXT,                    -- STAT | PRN | Q4H | Q6H | QD

    -- 狀態
    status TEXT DEFAULT 'PENDING',     -- PENDING | VERIFIED | DISPENSED | ADMINISTERED | CANCELLED

    -- 時間
    ordered_at INTEGER NOT NULL,
    ordered_by TEXT NOT NULL,

    -- 緊急
    is_stat INTEGER DEFAULT 0,

    -- 備註
    notes TEXT
);

CREATE INDEX idx_orders_person ON orders(person_id);
CREATE INDEX idx_orders_status ON orders(status);


-- ═══════════════════════════════════════════════════════════════
-- 3. 執行記錄表 (Executions) - 護理/藥局的執行確認
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,            -- 關聯到 orders.id

    -- 時間 (雙時間軸)
    event_time INTEGER NOT NULL,       -- 實際執行時間
    recorded_at INTEGER NOT NULL,      -- 輸入時間
    time_source TEXT DEFAULT 'NOW',

    -- 執行狀態
    action TEXT NOT NULL,              -- VERIFIED | DISPENSED | ADMINISTERED | HELD | REFUSED

    -- 執行細節
    actual_dose TEXT,                  -- 實際劑量 (可能與醫囑不同)
    site TEXT,                         -- 注射部位

    -- 資源連動 (這裡才真正扣庫存！)
    resource_consumed TEXT,            -- JSON: [{"item_id": "...", "qty": 1, "lot": "..."}]
    resource_intent_id TEXT,           -- MIRS consume intent id
    resource_confirmed INTEGER DEFAULT 0,

    -- 執行者
    executed_by TEXT NOT NULL,
    witness_by TEXT,                   -- 管藥需要見證者

    -- 備註
    notes TEXT,
    refusal_reason TEXT                -- 若 REFUSED
);

CREATE INDEX idx_exec_order ON executions(order_id);
CREATE INDEX idx_exec_time ON executions(event_time);


-- ═══════════════════════════════════════════════════════════════
-- 4. PIO 臨床問題追蹤 (Problem-Intervention-Outcome)
-- ═══════════════════════════════════════════════════════════════
-- 遵循 ChatGPT 建議：用關聯事件，非單一 JSON blob

CREATE TABLE pio_problems (
    id TEXT PRIMARY KEY,               -- PIO-{case_id}-{seq}
    case_id TEXT NOT NULL,             -- anesthesia_case 或 ward_admission
    person_id TEXT NOT NULL,

    -- 問題定義
    problem_type TEXT NOT NULL,        -- HEMODYNAMIC | RESPIRATORY | DEPTH | TEMPERATURE | BLEEDING | OTHER
    problem_subtype TEXT,              -- BP_LOW | BP_HIGH | SPO2_LOW | ETCO2_HIGH | DEPTH_LIGHT | DEPTH_DEEP
    detected_at INTEGER NOT NULL,      -- 發現時間
    recorded_at INTEGER NOT NULL,

    -- 狀態
    status TEXT DEFAULT 'ACTIVE',      -- ACTIVE | IMPROVING | STABLE | RESOLVED | ESCALATED
    severity TEXT DEFAULT 'MODERATE',  -- MILD | MODERATE | SEVERE | CRITICAL

    -- 觸發值
    trigger_value TEXT,                -- JSON: {"sbp": 75, "hr": 110}

    -- 解決
    resolved_at INTEGER,
    resolution_notes TEXT,

    -- 稽核
    detected_by TEXT,

    -- Bookmark (先救人後補登)
    is_placeholder INTEGER DEFAULT 0,  -- Quick Marker 建立的暫存
    placeholder_filled_at INTEGER
);


CREATE TABLE pio_interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id TEXT NOT NULL,          -- FK to pio_problems.id

    -- 時間
    event_time INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL,
    time_source TEXT DEFAULT 'NOW',

    -- 介入類型
    intervention_type TEXT NOT NULL,   -- MEDICATION | FLUID | BLOOD | AIRWAY | DEPTH_ADJUST | NOTIFY | OTHER
    intervention_subtype TEXT,         -- VASOPRESSOR | VASODILATOR | CRYSTALLOID | PRBC | FIO2_ADJUST | ...

    -- 內容
    drug_name TEXT,
    dose TEXT,
    route TEXT,

    -- 血品特殊欄位
    blood_product_type TEXT,           -- PRBC | FFP | PLT | CRYO
    blood_unit_id TEXT,                -- 血袋條碼 (可追溯)

    -- 資源連動
    resource_intent_id TEXT,

    -- 備註
    notes TEXT,
    performed_by TEXT
);

CREATE INDEX idx_pio_int_problem ON pio_interventions(problem_id);


CREATE TABLE pio_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id TEXT NOT NULL,
    intervention_id INTEGER,           -- 可選：特定介入的結果

    -- 時間
    event_time INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL,

    -- 結果
    outcome_type TEXT NOT NULL,        -- IMPROVED | NO_CHANGE | WORSENED | COMPLICATION

    -- 觀察值
    observed_value TEXT,               -- JSON: {"sbp": 95, "hr": 88}

    -- 備註
    notes TEXT,
    observed_by TEXT
);


-- ═══════════════════════════════════════════════════════════════
-- 5. 位置追蹤 (Location Tracking)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE location_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,

    location_code TEXT NOT NULL,       -- TRIAGE | ER-1 | OR-1 | PACU | WARD-A | AMBULANCE-1
    location_name TEXT,

    arrived_at INTEGER NOT NULL,
    departed_at INTEGER,

    logged_by TEXT,
    method TEXT DEFAULT 'MANUAL'       -- MANUAL | QR_SCAN | RFID
);

CREATE INDEX idx_loc_person ON location_logs(person_id);
CREATE INDEX idx_loc_current ON location_logs(location_code, departed_at);


-- ═══════════════════════════════════════════════════════════════
-- 6. 交班記錄 (Unified Handoff)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE handoff_records (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,

    -- 交班類型
    handoff_type TEXT NOT NULL,        -- TRIAGE_TO_ER | ER_TO_OR | OR_TO_PACU | PACU_TO_WARD | WARD_SHIFT | TRANSFER_OUT

    -- 交接雙方
    from_unit TEXT,
    from_user TEXT,
    to_unit TEXT,
    to_user TEXT,

    -- ISBAR 內容
    situation TEXT,                    -- I: 身份 + 狀況
    background TEXT,                   -- S: 背景
    assessment TEXT,                   -- B: 評估
    recommendation TEXT,               -- A: 建議
    readback_confirmed INTEGER,        -- R: 覆誦確認

    -- 時間
    initiated_at INTEGER NOT NULL,
    accepted_at INTEGER,

    -- 狀態
    status TEXT DEFAULT 'PENDING',     -- PENDING | ACCEPTED | REJECTED

    -- 附件
    attached_pio_ids TEXT,             -- JSON: 活躍 PIO 問題
    attached_orders TEXT,              -- JSON: 待執行醫囑

    -- 備註
    notes TEXT
);
```

### 2.3 資料流架構

```
                    統一資料核心

                ┌─────────────────┐
                │   vital_signs   │ ← 所有 VS 匯流
                └────────┬────────┘
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
    ▼                    ▼                    ▼
┌─────────┐        ┌─────────┐         ┌─────────┐
│ orders  │───────▶│executions│───────▶│resources│
│(醫師開) │        │(護理執行)│         │(MIRS扣) │
└─────────┘        └─────────┘         └─────────┘
                         │
                         │ 麻醉/手術情境
                         ▼
                ┌─────────────────┐
                │   pio_problems  │
                │ + interventions │
                │ + outcomes      │
                └─────────────────┘
                         │
                         ▼
                ┌─────────────────┐
                │ handoff_records │ ← 統一交班格式
                └─────────────────┘
```

---

## 3. PWA 角色重整 (Role-Based PWAs)

### 3.1 「以護理為核心」的設計

```
                     護理是串聯一切的樞紐

    ┌─────────┐                           ┌─────────┐
    │ 醫師    │──── orders ────────────▶ │         │
    │ 開醫囑  │                           │         │
    └─────────┘                           │         │
                                          │  護理   │
    ┌─────────┐                           │         │
    │ 藥局    │◀─── 調劑請求 ───────────│  執行   │
    │ 調劑    │──── 發藥確認 ──────────▶ │         │
    └─────────┘                           │  確認   │
                                          │         │
    ┌─────────┐                           │         │
    │ MIRS    │◀─── 扣庫存 ─────────────│         │
    │ 庫存    │──── 確認 ──────────────▶ └─────────┘
    └─────────┘                                │
                                               │
                                               ▼
                                         ┌─────────┐
                                         │ 病患    │
                                         │ 康復    │
                                         └─────────┘
```

### 3.2 PWA 矩陣重定義

| PWA | 使用者 | 模式 (Context) | 核心職責 | 寫入資料表 |
|-----|--------|----------------|----------|------------|
| **Clinician** | 醫師 | 急診/門診/查房 | 診斷、開醫囑、決策 | orders, registrations |
| **Nursing** | 護理師 | **檢傷/病房/PACU/交班** | VS採集、給藥(MAR)、執行確認、交班 | vital_signs, executions, handoff_records |
| **Anesthesia** | 麻醉科 | 術中/PACU | PIO追蹤、麻醉記錄、資源互鎖 | pio_*, vital_signs, anesthesia_events |
| **Logistics** | EMT/庫房 | 轉送/庫存 | 物資管理、轉送任務 | transfer_*, resources |
| **Pharmacy** | 藥師 | 調劑/發藥 | 處方審核、調劑、發藥 | executions (DISPENSED) |
| **Admin** | 站長 | 管理/報表 | 站點設定、報表、帳號 | system_config, audit_log |

### 3.3 Nursing PWA 多模式設計

```
┌─────────────────────────────────────────────────────────────┐
│                     Nursing PWA                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │ 檢傷    │ │ 急診    │ │ 病房    │ │ 交班    │           │
│  │ Triage  │ │ ER      │ │ Ward    │ │ Handoff │           │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘           │
│       │           │           │           │                 │
│       ▼           ▼           ▼           ▼                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 共用核心功能                                         │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ • VS 採集 (寫入 vital_signs)                        │   │
│  │ • 待辦事項 (從 orders 讀取 PENDING)                 │   │
│  │ • 給藥確認 MAR (寫入 executions)                    │   │
│  │ • 交班準備 (寫入 handoff_records)                   │   │
│  │ • 護理紀錄 (寫入 nursing_notes)                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 模式特殊功能                                         │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 檢傷: 分流決策、優先序                              │   │
│  │ 急診: 快速處置、監測警示                            │   │
│  │ 病房: Q4H 提醒、傷口評估、I/O 記錄                  │   │
│  │ 交班: ISBAR 產生、待辦移交                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 時間語意與稽核 (Time Semantics)

### 4.1 雙時間軸原則 (Bi-temporal)

```
event_time    = 臨床發生時間 (Timeline 渲染用)
recorded_at   = 系統輸入時間 (稽核用)
time_source   = NOW | BACKDATED | CORRECTED
```

### 4.2 補登與更正規則

| 情境 | 規則 |
|------|------|
| 即時輸入 | `event_time = recorded_at`, `time_source = NOW` |
| 補登 (< 30 min) | `event_time < recorded_at`, `time_source = BACKDATED` |
| 補登 (> 30 min) | 同上 + `late_entry_reason` 必填 |
| 關案後更正 | 新增 CORRECTION 事件，`corrected_from` 指向原始，需 co-sign |

### 4.3 Append-Only 更正機制

```javascript
// 錯誤做法：UPDATE event SET time = new_time
// 正確做法：

async function correctEventTime(originalEventId, newEventTime, reason, coSignUserId) {
    const original = await getEvent(originalEventId);

    // 建立更正事件
    const correction = {
        event_type: 'EVENT_CORRECTION',
        target_event_id: originalEventId,
        corrected_field: 'event_time',
        old_value: original.event_time,
        new_value: newEventTime,
        correction_reason: reason,
        corrected_by: currentUserId,
        co_signed_by: coSignUserId,  // 關案後必須
        recorded_at: Date.now()
    };

    await insertEvent(correction);

    // UI 投影時，以最新更正為準
    // 但原始事件永遠保留供稽核
}
```

---

## 5. PIO 時間軸實作 (ChatGPT 建議整合)

### 5.1 PIO 作為一級時間軸軌道

```
Timeline 軌道結構:
─────────────────────────────────────────────────────────
│ Milestones │  ●────●────●────●────●────●────●        │  里程碑軌
─────────────────────────────────────────────────────────
│ PIO        │  ▼    ◆◆   ✓         ▼   ◆    ✓        │  問題-介入-結果
│            │  │    ││   │         │   │    │        │
│            │ 低血壓 升壓藥 穩定    低血壓 輸血 改善   │
─────────────────────────────────────────────────────────
│ Vitals     │  ─────────────────────────────────       │  VS 折線圖
─────────────────────────────────────────────────────────
│ Medication │  💊   💊💊        💊                     │  用藥點
─────────────────────────────────────────────────────────
│ Events     │       ✂️              🩸                  │  事件
─────────────────────────────────────────────────────────
         09:00  09:15  09:30  09:45  10:00  10:15

圖例:
  ▼ = Problem detected
  ◆ = Intervention
  ✓ = Outcome / Resolved
```

### 5.2 Quick Marker (先救人後補登)

```javascript
// 一鍵建立暫存問題 (手忙時按)
const quickMarkers = [
    { label: 'BP Low',      type: 'HEMODYNAMIC', subtype: 'BP_LOW' },
    { label: 'BP High',     type: 'HEMODYNAMIC', subtype: 'BP_HIGH' },
    { label: 'SpO₂ Low',    type: 'RESPIRATORY', subtype: 'SPO2_LOW' },
    { label: 'EtCO₂ High',  type: 'RESPIRATORY', subtype: 'ETCO2_HIGH' },
    { label: 'Depth Light', type: 'DEPTH',       subtype: 'DEPTH_LIGHT' },
    { label: 'Depth Deep',  type: 'DEPTH',       subtype: 'DEPTH_DEEP' },
    { label: 'Bleeding',    type: 'BLEEDING',    subtype: 'ACTIVE' }
];

function createQuickMarker(marker) {
    return {
        id: generatePioId(),
        problem_type: marker.type,
        problem_subtype: marker.subtype,
        detected_at: Date.now(),
        recorded_at: Date.now(),
        status: 'ACTIVE',
        is_placeholder: 1,  // 標記為暫存，待補充
        trigger_value: null // 稍後補
    };
}
```

### 5.3 未完成清單 (Incomplete Queue)

```javascript
function getIncompleteItems(caseId) {
    return {
        // PIO 問題未結案
        unresolvedProblems: pio_problems.filter(p =>
            p.case_id === caseId &&
            p.status === 'ACTIVE' &&
            !p.resolved_at
        ),

        // 處置缺劑量
        incompleteInterventions: pio_interventions.filter(i =>
            i.intervention_type === 'MEDICATION' && !i.dose
        ),

        // 血品缺 unit_id
        missingBloodUnitId: pio_interventions.filter(i =>
            i.intervention_type === 'BLOOD' && !i.blood_unit_id
        ),

        // 補登未填理由
        backdatedWithoutReason: events.filter(e =>
            e.time_source === 'BACKDATED' &&
            !e.late_entry_reason &&
            (e.recorded_at - e.event_time) > 30 * 60 * 1000
        ),

        // Placeholder 未填充
        unfilledPlaceholders: pio_problems.filter(p =>
            p.is_placeholder === 1 && !p.placeholder_filled_at
        )
    };
}
```

---

## 6. 資源互鎖策略 (Resource Linkage)

### 6.1 兩階段確認

```
階段 A: 臨床記錄 (離線可做)
─────────────────────────────
  PIO Intervention
  ├── drug_name: "Ephedrine"
  ├── dose: "10mg"
  ├── route: "IV"
  └── resource_intent_id: NULL  ← 尚未連動

階段 B: 資源連動 (上線時同步)
─────────────────────────────
  emit INVENTORY_CONSUME_INTENT
  ├── item_code: "MED-EPHE-50"
  ├── quantity: 1
  ├── source_event: intervention.id
  └── status: PENDING_SYNC

  MIRS 回應 →
  ├── 成功: resource_confirmed = 1
  └── 失敗: 顯示 "resource pending" badge
```

### 6.2 失敗處理

```
離線時：
- 臨床記錄照常進行 (護理不會被系統卡住)
- Resource intent 存入 queue
- 顯示小 badge 提醒「資源待同步」

上線後：
- 自動 flush queue
- 失敗項目進入 Incomplete 清單
- 不影響臨床記錄的完整性
```

---

## 7. 遷移路徑 (Migration Path)

### 7.1 Phase 1: 資料層統一 (v3.0)

```
□ 建立 vital_signs 統一表
□ 建立 orders / executions 閉環
□ 建立 pio_* 關聯表
□ 建立 location_logs
□ 建立 handoff_records
□ 遷移腳本：從舊表匯入新表
```

### 7.2 Phase 2: Nursing PWA 升級 (v3.1)

```
□ 改造現有 Nurse PWA 為多模式
□ 新增 Ward Mode
□ 新增 MAR 給藥確認功能
□ 新增交班模式
□ VS 改寫入 vital_signs 表
```

### 7.3 Phase 3: Anesthesia Timeline 2.0 (v3.2)

```
□ PIO 軌道實作
□ Quick Marker 實作
□ Incomplete Queue 實作
□ 雙時間軸 + 更正機制
□ 資源 intent 兩階段
```

### 7.4 Phase 4: 整合與淘汰 (v3.3)

```
□ Clinician PWA 統一 (整合 Doctor)
□ Logistics PWA 統一 (整合 EMT + Mobile)
□ 淘汰重複功能
□ 統一報表
```

---

## 8. 驗收測試 (Acceptance Tests)

### 8.1 VS 統一

```gherkin
Given 病患在檢傷區量了血壓 120/80
  And 病患進入手術室，麻醉中血壓 90/60
  And 病患轉送途中血壓 100/70
When 醫師打開 Clinician PWA 查看病患
Then 應該看到一條連續的血壓曲線
  And 曲線包含三個來源 (TRIAGE, OR, AMBULANCE)
```

### 8.2 醫囑執行閉環

```gherkin
Given 醫師開了 Morphine 5mg IV STAT
When 藥局調劑完成
  And 護理師掃描病人手圈
  And 護理師掃描藥品
  And 護理師確認給藥
Then orders.status = 'ADMINISTERED'
  And executions 有一筆記錄
  And MIRS 庫存被扣減
  And 管藥帳可追溯
```

### 8.3 PIO 因果追蹤

```gherkin
Given 麻醉中血壓降到 70/40
When 護理師按 Quick Marker "BP Low"
  And 稍後補充 trigger_value = {sbp: 70}
  And 記錄給予 Ephedrine 10mg
  And 記錄 5 分鐘後血壓回到 95/65
  And 將問題標記為 RESOLVED
Then Timeline 顯示:
  | 10:30 ▼ BP Low (detected) |
  | 10:31 ◆ Ephedrine 10mg    |
  | 10:36 ✓ Resolved          |
  And PIO 問題可完整追溯因果
```

### 8.4 補登稽核

```gherkin
Given 護理師在 10:30 處理緊急狀況
When 護理師在 11:00 補登 10:30 的事件
Then event_time = 10:30
  And recorded_at = 11:00
  And time_source = 'BACKDATED'
  And 因間隔 > 30 min，系統要求填寫 late_entry_reason
```

### 8.5 關案後更正

```gherkin
Given 麻醉案例已關案
When 護理師發現 10:30 的藥物劑量記錄錯誤
  And 護理師嘗試更正
Then 系統要求輸入更正原因
  And 系統要求 co-sign (醫師或主管 PIN)
  And 建立 EVENT_CORRECTION 事件
  And 原始事件保留不變
  And Timeline 顯示更正後數值，但可查看原始
```

---

## 9. 結論

### 9.1 核心轉變

| 之前 | 之後 |
|------|------|
| 各 PWA 獨立資料 | 統一資料核心 |
| 里程碑式記錄 | PIO 因果追蹤 |
| 開單即扣庫存 | 執行確認才扣 |
| 時間可覆寫 | Append-only 更正 |
| 功能分散 | 護理為核心串聯 |

### 9.2 護理為核心的意義

```
護理師是臨床執行的樞紐：
- 醫師「想」→ 護理師「做」→ 病患「好」
- 開醫囑只是開始，執行確認才是真相
- 所有臨床活動最終都經過護理師之手

因此：
- Nursing PWA 應該是最功能完整的
- 其他 PWA 是護理工作的上游 (Clinician) 或下游 (Logistics)
- VS、MAR、交班都以護理為主體設計
```

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 - 整合 Claude/ChatGPT/Gemini 分析 |
