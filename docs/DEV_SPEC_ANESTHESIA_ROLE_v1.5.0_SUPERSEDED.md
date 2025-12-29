# Dev Spec: 麻醉科醫師角色模組

**MIRS v1.5.0 - 備援手術室麻醉管理**

## 1. 背景與需求分析

### 1.1 現況

MIRS 目前作為「備援手術室」(BORP) 系統，主要功能聚焦於：
- 設備韌性管理（電力、氧氣）
- 庫存物資管理（醫材、藥品）
- 藥局撥發流程

**缺失**：目前沒有針對麻醉科醫師的專屬角色與功能。

### 1.2 麻醉科在備援手術室的關鍵角色

在備援手術室情境（如戰時、災難）中，麻醉科醫師負責：

| 職責 | 說明 | 系統需求 |
|------|------|----------|
| **術前評估** | 病患 ASA 分級、禁食確認、過敏史 | 術前檢查表 |
| **麻醉計畫** | 麻醉方式選擇（全麻/區域/脊椎/局部） | 麻醉方式主檔 |
| **藥物管理** | 管制藥品領用、使用、歸還記錄 | 管藥追蹤系統 |
| **設備準備** | 呼吸器、監視器、麻醉機檢查 | 設備清單連動 |
| **術中監測** | 生命徵象、麻醉深度、輸液輸血 | 麻醉紀錄表 |
| **術後恢復** | PACU 評估、拔管標準、疼痛控制 | 恢復評分表 |

### 1.3 設計原則

1. **離線優先**：所有功能必須在網路中斷時可運作
2. **快速紀錄**：戰時情境下需最少點擊完成紀錄
3. **管藥合規**：符合管制藥品管理條例第四級以上追蹤
4. **與現有模組整合**：複用設備檢查、藥品撥發流程

---

## 2. 角色定義

### 2.1 新增角色：麻醉科醫師 (Anesthesiologist)

```python
class Role(str, Enum):
    # 現有角色
    ADMIN = "admin"
    DOCTOR = "doctor"
    NURSE = "nurse"
    PHARMACIST = "pharmacist"

    # 新增角色
    ANESTHESIOLOGIST = "anesthesiologist"  # 麻醉科醫師
    ANESTHESIA_NURSE = "anesthesia_nurse"  # 麻醉護理師（選配）
```

### 2.2 權限矩陣

| 功能模組 | Admin | Doctor | Anesthesiologist | Nurse | Pharmacist |
|----------|-------|--------|------------------|-------|------------|
| 術前評估表 | - | R | RW | R | - |
| 麻醉紀錄 | - | R | RW | R | - |
| 管藥領用申請 | - | - | RW | - | Approve |
| 管藥使用紀錄 | - | R | RW | R | R |
| 設備檢查（麻醉相關） | R | R | RW | RW | - |
| PACU 評估表 | - | R | RW | RW | - |

---

## 3. 資料模型

### 3.1 資料庫 Schema 新增

```sql
-- =============================================================================
-- 麻醉方式主檔
-- =============================================================================
CREATE TABLE anesthesia_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,           -- 'GA', 'RA-SPINAL', 'RA-EPIDURAL', 'LA', 'SEDATION'
    name_zh TEXT NOT NULL,               -- '全身麻醉'
    name_en TEXT,                        -- 'General Anesthesia'
    category TEXT NOT NULL,              -- 'GENERAL', 'REGIONAL', 'LOCAL', 'SEDATION'
    default_drugs TEXT,                  -- JSON: 預設用藥組合
    airway_required BOOLEAN DEFAULT FALSE,
    ventilator_required BOOLEAN DEFAULT FALSE,
    monitoring_level TEXT DEFAULT 'STANDARD', -- 'BASIC', 'STANDARD', 'ADVANCED'
    is_active BOOLEAN DEFAULT TRUE
);

-- =============================================================================
-- 術前評估表
-- =============================================================================
CREATE TABLE preop_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,               -- 關聯手術案例
    patient_id TEXT NOT NULL,

    -- ASA 分級
    asa_class INTEGER CHECK(asa_class BETWEEN 1 AND 6),
    asa_emergency BOOLEAN DEFAULT FALSE,

    -- 禁食狀態
    npo_hours REAL,                      -- 禁食時數
    last_oral_intake DATETIME,
    npo_verified_by TEXT,

    -- 過敏史
    allergies TEXT,                      -- JSON array
    allergy_verified BOOLEAN DEFAULT FALSE,

    -- 困難氣道評估
    mallampati_score INTEGER CHECK(mallampati_score BETWEEN 1 AND 4),
    thyromental_distance TEXT,           -- 'NORMAL', 'SHORT'
    neck_mobility TEXT,                  -- 'FULL', 'LIMITED', 'RESTRICTED'
    difficult_airway_anticipated BOOLEAN DEFAULT FALSE,

    -- 共病症
    comorbidities TEXT,                  -- JSON array
    cardiac_risk_index INTEGER,

    -- 麻醉計畫
    planned_anesthesia_type TEXT,        -- 關聯 anesthesia_types.code
    backup_plan TEXT,

    -- 簽核
    assessed_by TEXT NOT NULL,           -- 評估醫師
    assessment_datetime DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'PENDING',       -- 'PENDING', 'APPROVED', 'NEEDS_REVIEW'

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id)
);

-- =============================================================================
-- 麻醉紀錄
-- =============================================================================
CREATE TABLE anesthesia_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    preop_assessment_id INTEGER,

    -- 時間軸
    anesthesia_start DATETIME,
    induction_start DATETIME,
    intubation_time DATETIME,
    surgery_start DATETIME,
    surgery_end DATETIME,
    extubation_time DATETIME,
    anesthesia_end DATETIME,

    -- 氣道管理
    airway_device TEXT,                  -- 'ETT', 'LMA', 'MASK', 'NONE'
    ett_size TEXT,
    ett_depth TEXT,
    intubation_attempts INTEGER DEFAULT 1,
    intubation_difficulty TEXT,          -- 'EASY', 'MODERATE', 'DIFFICULT'

    -- 生命徵象記錄 (每5分鐘)
    vital_signs TEXT,                    -- JSON array of timestamped records

    -- 用藥記錄
    medications TEXT,                    -- JSON array

    -- 輸液輸血
    fluids TEXT,                         -- JSON array
    blood_products TEXT,                 -- JSON array
    estimated_blood_loss INTEGER,        -- ml
    urine_output INTEGER,                -- ml

    -- 特殊事件
    events TEXT,                         -- JSON array: 低血壓、心律不整等

    -- 簽核
    anesthesiologist_id TEXT NOT NULL,
    assistant_id TEXT,
    status TEXT DEFAULT 'IN_PROGRESS',   -- 'IN_PROGRESS', 'COMPLETED', 'SIGNED'

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id),
    FOREIGN KEY (preop_assessment_id) REFERENCES preop_assessments(id)
);

-- =============================================================================
-- 管制藥品追蹤
-- =============================================================================
CREATE TABLE controlled_drug_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,                        -- 可為 NULL (非手術用途)

    -- 藥品資訊
    drug_code TEXT NOT NULL,
    drug_name TEXT NOT NULL,
    schedule_class INTEGER NOT NULL,     -- 第幾級管制藥品 (1-4)

    -- 領用
    quantity_requested INTEGER NOT NULL,
    quantity_dispensed INTEGER,
    requested_by TEXT NOT NULL,
    dispensed_by TEXT,
    request_datetime DATETIME DEFAULT CURRENT_TIMESTAMP,
    dispense_datetime DATETIME,

    -- 使用
    quantity_used INTEGER,
    quantity_wasted INTEGER,
    waste_witness TEXT,                  -- 廢棄見證人

    -- 歸還
    quantity_returned INTEGER,
    returned_datetime DATETIME,
    received_by TEXT,

    -- 審計
    discrepancy TEXT,                    -- 差異說明
    status TEXT DEFAULT 'REQUESTED',     -- 'REQUESTED', 'DISPENSED', 'USED', 'RECONCILED', 'DISCREPANCY'

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id)
);

-- =============================================================================
-- PACU 恢復評估
-- =============================================================================
CREATE TABLE pacu_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    anesthesia_record_id INTEGER,

    -- 入室評估
    admission_time DATETIME,
    admission_aldrete_score INTEGER,     -- Aldrete Score (0-10)

    -- 定時評估 (每15分鐘)
    assessments TEXT,                    -- JSON array

    -- 出室評估
    discharge_time DATETIME,
    discharge_aldrete_score INTEGER,
    discharge_criteria_met BOOLEAN,

    -- 疼痛管理
    pain_scores TEXT,                    -- JSON array: NRS 0-10
    analgesics_given TEXT,               -- JSON array

    -- 併發症
    complications TEXT,                  -- JSON array

    -- 簽核
    nurse_id TEXT NOT NULL,
    anesthesiologist_sign_off TEXT,
    status TEXT DEFAULT 'IN_PACU',       -- 'IN_PACU', 'READY_FOR_DISCHARGE', 'DISCHARGED'

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id),
    FOREIGN KEY (anesthesia_record_id) REFERENCES anesthesia_records(id)
);
```

### 3.2 索引設計

```sql
-- 快速查詢當日案例
CREATE INDEX idx_anesthesia_records_date ON anesthesia_records(date(anesthesia_start));
CREATE INDEX idx_preop_status ON preop_assessments(status, assessment_datetime);

-- 管藥追蹤
CREATE INDEX idx_controlled_drug_status ON controlled_drug_log(status, request_datetime);
CREATE INDEX idx_controlled_drug_case ON controlled_drug_log(case_id);

-- PACU 即時狀態
CREATE INDEX idx_pacu_status ON pacu_assessments(status);
```

---

## 4. API 設計

### 4.1 術前評估 API

```
GET    /api/anesthesia/preop                     # 列出待評估案例
GET    /api/anesthesia/preop/{case_id}           # 取得評估表
POST   /api/anesthesia/preop                     # 建立評估表
PUT    /api/anesthesia/preop/{id}                # 更新評估表
POST   /api/anesthesia/preop/{id}/approve        # 核准評估
```

### 4.2 麻醉紀錄 API

```
GET    /api/anesthesia/records                   # 列出紀錄
GET    /api/anesthesia/records/{case_id}         # 取得紀錄
POST   /api/anesthesia/records                   # 開始紀錄
PUT    /api/anesthesia/records/{id}              # 更新紀錄
POST   /api/anesthesia/records/{id}/vitals       # 新增生命徵象
POST   /api/anesthesia/records/{id}/medication   # 新增用藥
POST   /api/anesthesia/records/{id}/event        # 新增事件
POST   /api/anesthesia/records/{id}/complete     # 完成紀錄
```

### 4.3 管藥追蹤 API

```
GET    /api/anesthesia/controlled-drugs          # 列出管藥記錄
POST   /api/anesthesia/controlled-drugs/request  # 申請領用
POST   /api/anesthesia/controlled-drugs/{id}/dispense  # 發放
POST   /api/anesthesia/controlled-drugs/{id}/use       # 使用記錄
POST   /api/anesthesia/controlled-drugs/{id}/waste     # 廢棄記錄
POST   /api/anesthesia/controlled-drugs/{id}/return    # 歸還
GET    /api/anesthesia/controlled-drugs/reconcile      # 對帳報表
```

### 4.4 PACU API

```
GET    /api/anesthesia/pacu                      # 列出恢復室病患
GET    /api/anesthesia/pacu/{id}                 # 取得評估
POST   /api/anesthesia/pacu                      # 入室登錄
POST   /api/anesthesia/pacu/{id}/assess          # 定時評估
POST   /api/anesthesia/pacu/{id}/discharge       # 出室
```

---

## 5. PWA 設計

### 5.1 新增 PWA：麻醉站 (Anesthesia Station)

**路由**：`/anesthesia`

**主要功能頁面**：

```
/anesthesia
├── /           # 儀表板：當日案例總覽
├── /preop      # 術前評估列表
├── /preop/:id  # 術前評估表單
├── /record     # 進行中的麻醉紀錄
├── /record/:id # 麻醉紀錄詳情
├── /drugs      # 管藥管理
├── /pacu       # 恢復室看板
└── /settings   # 設定
```

### 5.2 UI 設計重點

#### 5.2.1 麻醉紀錄介面（核心）

```
┌─────────────────────────────────────────────────────┐
│ 🏥 Case #OR-001  張○○  M/45  ASA II               │
│ 手術：ORIF Lt femur fracture                        │
├─────────────────────────────────────────────────────┤
│ [時間軸] ─●──●──●──●──────────────────●──○        │
│         開始 誘導 插管 切皮            結束         │
├────────────────┬────────────────────────────────────┤
│ 生命徵象        │ 最新: BP 120/75  HR 72  SpO2 99% │
│ ┌────────────┐ │ ┌─────────────────────────────────┐│
│ │ 📈 趨勢圖   │ │ │  [+藥物] [+輸液] [+事件]      ││
│ │            │ │ ├─────────────────────────────────┤│
│ │            │ │ │ 10:15 Propofol 150mg IV        ││
│ │            │ │ │ 10:16 Rocuronium 50mg IV       ││
│ │            │ │ │ 10:18 ETT #7.5 @ 22cm          ││
│ └────────────┘ │ │ 10:20 Surgery start            ││
│                │ └─────────────────────────────────┘│
├────────────────┴────────────────────────────────────┤
│ [暫停] [新增生命徵象] [完成麻醉]                    │
└─────────────────────────────────────────────────────┘
```

#### 5.2.2 管藥快速記錄

```
┌─────────────────────────────────────────┐
│ 💊 管制藥品記錄                          │
├─────────────────────────────────────────┤
│ Fentanyl 0.1mg/2ml                      │
│ [領取: 2 amp] [使用: 1.5 amp] [廢棄: 0.5]│
│ 廢棄見證: 護理師 王○○ ✓                 │
├─────────────────────────────────────────┤
│ Midazolam 5mg/ml                        │
│ [領取: 1 amp] [使用: 1 amp]             │
└─────────────────────────────────────────┘
```

---

## 6. 整合點

### 6.1 與現有設備模組整合

麻醉相關設備類型需納入現有 `equipment_types` 表：

```sql
INSERT INTO equipment_types (type_code, type_name, category, resilience_category) VALUES
('VENT', '呼吸器', '麻醉設備', 'POWER'),
('ANESTH_MACHINE', '麻醉機', '麻醉設備', 'POWER'),
('MONITOR', '生理監視器', '麻醉設備', 'POWER'),
('DEFIBRILLATOR', '電擊器', '急救設備', 'POWER'),
('SUCTION', '抽吸器', '麻醉設備', 'POWER');
```

### 6.2 與藥局撥發整合

麻醉科管藥申請流程整合現有 Pharmacy Dispatch API：

```
1. 麻醉科 POST /api/anesthesia/controlled-drugs/request
2. 藥局收到通知，在 /pharmacy 介面審核
3. 藥局 POST /api/pharmacy/dispatch/{id}/approve
4. 麻醉科確認領取
5. 術後對帳
```

### 6.3 與手術案例整合

新增 `surgery_cases` 表（如尚未存在）：

```sql
CREATE TABLE IF NOT EXISTS surgery_cases (
    id TEXT PRIMARY KEY,                 -- 'OR-YYYYMMDD-NNN'
    patient_id TEXT NOT NULL,
    patient_name TEXT,
    procedure_codes TEXT,                -- JSON array of surgery codes
    surgeon_id TEXT,
    scheduled_datetime DATETIME,
    actual_start DATETIME,
    actual_end DATETIME,
    status TEXT DEFAULT 'SCHEDULED',     -- 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. 實作順序建議

### Phase 1: 基礎架構 (Week 1-2)

1. 資料庫 schema 建立
2. 角色與權限系統擴充
3. 麻醉方式主檔載入
4. 術前評估 API + 基本 UI

### Phase 2: 核心紀錄 (Week 3-4)

1. 麻醉紀錄 API
2. 生命徵象紀錄介面（離線優先）
3. 用藥紀錄介面
4. 即時同步機制

### Phase 3: 管藥追蹤 (Week 5)

1. 管藥 API
2. 與藥局整合
3. 對帳報表

### Phase 4: PACU 與完善 (Week 6)

1. PACU 看板
2. Aldrete 評分自動計算
3. 報表匯出

---

## 8. 考量事項

### 8.1 離線優先

- 所有表單需有 IndexedDB 本地暫存
- 網路恢復時自動同步
- 衝突解決策略：以時間戳記為準，保留雙方版本供人工審閱

### 8.2 法規遵循

- 管制藥品需符合「管制藥品管理條例」
- 電子簽章需符合「電子簽章法」（未來整合）
- 病歷保存需符合「醫療法」7年規定

### 8.3 效能考量

- 生命徵象每5分鐘一筆，一台刀約可達 60+ 筆
- 建議使用 batch insert
- 儀表板使用 WebSocket 即時更新

---

## 9. 開放問題

1. **是否需要獨立的「麻醉護理師」角色？**
   - 目前建議先合併至 Nurse 角色，加上 `anesthesia_certified` 標記

2. **生命徵象是否需要圖表顯示？**
   - 建議 Phase 1 先用表格，Phase 2 加入 Chart.js 趨勢圖

3. **是否整合生理監視器自動擷取？**
   - 這需要硬體整合，建議列為 v2.0 規劃

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*文件版本: Draft 1.0*
*更新日期: 2025-12-29*
