# MIRS 設備架構重新設計計劃書

**版本**: v2.0
**日期**: 2025-12-17
**狀態**: ✅ Phase 1-4 全部完成

---

## 一、現況分析

### 1.1 目前資料表結構

```
┌─────────────────────────────────────────────────────────────────┐
│ equipment (設備主表)                                              │
├─────────────────────────────────────────────────────────────────┤
│ id            TEXT PK      設備ID (如 UTIL-001, RESP-001)        │
│ name          TEXT         設備名稱                               │
│ category      TEXT         類別 (電力設備, 呼吸設備...)            │
│ quantity      INTEGER      數量                                   │
│ status        TEXT         狀態 (UNCHECKED/NORMAL/WARNING/ERROR) │
│ last_check    TIMESTAMP    最後檢查時間                           │
│ power_level   INTEGER      電量/油量 (冗餘欄位)                    │
│ tracking_mode TEXT         追蹤模式 (AGGREGATE/PER_UNIT)          │
│ power_watts   REAL         耗電瓦數                               │
│ capacity_wh   REAL         容量 (Wh)                              │
│ output_watts  REAL         輸出功率                               │
│ fuel_rate_lph REAL         油耗率 (L/hr)                          │
│ device_type   TEXT         設備類型 (POWER_STATION/GENERATOR...)  │
└─────────────────────────────────────────────────────────────────┘
           │
           │ 1:N (僅 PER_UNIT 模式)
           ▼
┌─────────────────────────────────────────────────────────────────┐
│ equipment_units (設備單位表)                                      │
├─────────────────────────────────────────────────────────────────┤
│ id            INTEGER PK   自增ID                                 │
│ equipment_id  TEXT FK      關聯設備ID                             │
│ unit_serial   TEXT         序號 (如 PS-001)                       │
│ unit_label    TEXT         顯示標籤 (如 電源站1號)                 │
│ level_percent INTEGER      存量百分比                             │
│ status        TEXT         狀態 (AVAILABLE/IN_USE/CHARGING...)   │
│ last_check    TIMESTAMP    最後檢查時間                           │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 目前問題

#### 問題 1: 狀態冗餘與不一致
```
equipment.status ←──?──→ equipment_units.last_check
equipment.power_level ←──?──→ AVG(equipment_units.level_percent)
```
- `equipment.status` 和 `equipment_units` 的狀態需手動同步
- 更新 `equipment_units` 後需額外更新 `equipment` 表
- 前端需要 `refreshKey` 技巧強制重新渲染

#### 問題 2: 追蹤模式混亂
```
AGGREGATE 模式: equipment 表直接存 power_level
PER_UNIT 模式:  需 JOIN equipment_units 計算
```
- 兩種模式的查詢邏輯完全不同
- Resilience Service 需要大量條件判斷
- 新增設備類型需修改多處程式碼

#### 問題 3: 設備類型硬編碼
```python
# resilience_service.py 中的硬編碼
if device_type == 'POWER_STATION':
    ...
elif device_type == 'GENERATOR':
    ...
elif device_type == 'O2_CYLINDER':
    ...
```
- 新增設備類型需修改服務層程式碼
- 韌性計算公式散落在多處
- 缺乏可擴展性

#### 問題 4: 前端資料流問題
```
韌性估算 Tab                     設備管理 Tab
      │                              │
      │ 更新 equipment_units         │
      │         │                    │
      ▼         ▼                    │
  API call → equipment_units 更新    │
             equipment 同步更新      │
                    │                │
                    └───── 前端需手動 reload ─────►
```
- 資料更新後需手動觸發重新載入
- 兩個 Tab 的資料來源不一致

---

## 二、新架構設計

### 2.1 設計原則

1. **單一真相來源 (Single Source of Truth)**
   - 狀態只存一處，其他都是計算值

2. **單位為中心 (Unit-Centric)**
   - 所有設備都是「單位」，即使只有一台

3. **類型可配置 (Type Configurable)**
   - 設備類型定義在資料庫/設定檔，而非程式碼

4. **API 驅動 (API-Driven)**
   - 韌性計算等複雜邏輯由 API 提供，前端只負責顯示

### 2.2 新資料表結構

```sql
-- ═══════════════════════════════════════════════════════════════
-- 1. 設備類型定義表 (可擴展)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE equipment_types (
    type_code       TEXT PRIMARY KEY,      -- 'POWER_STATION', 'O2_CYLINDER', 'GENERATOR'
    type_name       TEXT NOT NULL,         -- '行動電源站', '氧氣鋼瓶', '發電機'
    category        TEXT NOT NULL,         -- '電力設備', '呼吸設備'

    -- 韌性相關設定
    resilience_category TEXT,              -- 'POWER', 'OXYGEN', NULL (非韌性設備)
    unit_label      TEXT DEFAULT '%',      -- 顯示單位: '%', 'L', 'Wh'

    -- 容量與轉換公式 (JSON 格式, 可擴展)
    capacity_config TEXT,  -- SQLite 用 TEXT 儲存 JSON
    -- 範例: {
    --   "base_capacity": 2048,        -- 基礎容量
    --   "capacity_unit": "Wh",        -- 容量單位
    --   "output_rate": 100,           -- 輸出速率 (W 或 L/hr)
    --   "hours_formula": "capacity * level / 100 / output_rate"
    -- }

    -- 狀態選項 (JSON 陣列)
    status_options  TEXT DEFAULT '["AVAILABLE", "IN_USE", "MAINTENANCE"]',  -- SQLite 用 TEXT
    -- 電力設備: ["AVAILABLE", "IN_USE", "CHARGING", "MAINTENANCE", "OFFLINE"]
    -- 氧氣鋼瓶: ["AVAILABLE", "IN_USE", "EMPTY", "MAINTENANCE"]

    -- 顯示設定
    icon            TEXT,                  -- 圖示名稱
    color           TEXT DEFAULT 'gray',   -- 主題色

    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════════════════════════════
-- 2. 設備主表 (簡化，只存不變的資訊)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE equipment (
    id              TEXT PRIMARY KEY,      -- 'UTIL-001', 'RESP-001'
    type_code       TEXT NOT NULL,         -- FK → equipment_types
    name            TEXT NOT NULL,         -- '行動電源站 A'

    -- 設備特有參數 (覆蓋 type 預設值)
    capacity_override TEXT,                -- 可覆蓋 type 的 capacity_config (JSON)

    -- 中繼資料
    remarks         TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (type_code) REFERENCES equipment_types(type_code)
);

-- ═══════════════════════════════════════════════════════════════
-- 3. 設備單位表 (所有設備都有單位，即使只有一台)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE equipment_units (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id    TEXT NOT NULL,         -- FK → equipment
    unit_serial     TEXT NOT NULL CHECK(unit_serial <> ''),  -- 'PS-001', 'H-001'
    unit_label      TEXT NOT NULL,         -- '電源站1號', 'H型1號'

    -- 狀態 (這是唯一的真相來源!)
    level_percent   INTEGER DEFAULT 100 CHECK(level_percent BETWEEN 0 AND 100),
    status          TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK(status <> ''),

    -- 檢查狀態
    last_check      TIMESTAMP,             -- NULL = 未檢查
    checked_by      TEXT,                  -- 檢查人員

    -- 中繼資料
    remarks         TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (equipment_id) REFERENCES equipment(id),
    UNIQUE (equipment_id, unit_serial)
);

-- ChatGPT 建議: status ∈ status_options 由 API/Pydantic 層驗證

-- ═══════════════════════════════════════════════════════════════
-- 4. 檢查歷史表 (不變)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE equipment_check_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id    TEXT NOT NULL,
    unit_serial     TEXT NOT NULL,

    check_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    check_date      DATE,

    level_before    INTEGER,
    level_after     INTEGER,
    status_before   TEXT,
    status_after    TEXT,

    checked_by      TEXT,
    remarks         TEXT,

    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);

-- ═══════════════════════════════════════════════════════════════
-- 5. 檢視表: 設備狀態總覽 (取代 equipment.status 冗餘欄位)
-- ═══════════════════════════════════════════════════════════════
CREATE VIEW v_equipment_status AS
SELECT
    e.id,
    e.name,
    e.type_code,
    et.type_name,
    et.category,
    et.resilience_category,

    -- 聚合計算 (不再存在 equipment 表)
    COUNT(u.id) as unit_count,
    ROUND(AVG(u.level_percent), 1) as avg_level,
    SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) as checked_count,
    MAX(u.last_check) as last_check,

    -- 狀態判斷
    CASE
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0
            THEN 'UNCHECKED'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id)
            THEN 'CHECKED'
        ELSE 'PARTIAL'
    END as check_status

FROM equipment e
JOIN equipment_types et ON e.type_code = et.type_code
LEFT JOIN equipment_units u ON e.id = u.equipment_id
-- ChatGPT: GROUP BY 所有非聚合欄位，確保 SQL 可攜性
GROUP BY e.id, e.name, e.type_code, et.type_name, et.category, et.resilience_category;

-- ═══════════════════════════════════════════════════════════════
-- 6. 檢視表: 韌性設備明細 (供 Resilience API 使用)
-- ═══════════════════════════════════════════════════════════════
CREATE VIEW v_resilience_equipment AS
SELECT
    e.id as equipment_id,
    e.name,
    et.type_code,
    et.type_name,
    et.resilience_category,
    et.capacity_config,
    e.capacity_override,

    u.id as unit_id,
    u.unit_serial,
    u.unit_label,
    u.level_percent,
    u.status,
    u.last_check,

    -- 計算有效容量 (需在 API 層處理 JSON)
    u.level_percent as effective_percent

FROM equipment e
JOIN equipment_types et ON e.type_code = et.type_code
JOIN equipment_units u ON e.id = u.equipment_id
WHERE et.resilience_category IS NOT NULL
ORDER BY et.resilience_category, e.id, u.unit_serial;
```

### 2.3 預設設備類型資料

```sql
INSERT INTO equipment_types (type_code, type_name, category, resilience_category, unit_label, capacity_config, status_options) VALUES

-- 電力設備
('POWER_STATION', '行動電源站', '電力設備', 'POWER', '%',
 '{"base_capacity_wh": 2048, "output_watts": 100, "hours_per_100pct": 20}',
 '["AVAILABLE", "IN_USE", "CHARGING", "MAINTENANCE", "OFFLINE"]'),

('GENERATOR', '發電機', '電力設備', 'POWER', '%',
 '{"tank_liters": 50, "fuel_rate_lph": 3.0, "output_watts": 2000, "hours_per_100pct": 16.7}',
 '["AVAILABLE", "IN_USE", "MAINTENANCE", "OFFLINE"]'),

-- 氧氣設備
('O2_CYLINDER_H', 'H型氧氣鋼瓶', '呼吸設備', 'OXYGEN', '%',
 '{"capacity_liters": 6900, "flow_rate_lpm": 6, "hours_per_100pct": 19.2}',
 '["AVAILABLE", "IN_USE", "EMPTY", "MAINTENANCE"]'),

('O2_CYLINDER_E', 'E型氧氣鋼瓶', '急救設備', 'OXYGEN', '%',
 '{"capacity_liters": 680, "flow_rate_lpm": 5, "hours_per_100pct": 2.3}',
 '["AVAILABLE", "IN_USE", "EMPTY", "MAINTENANCE"]'),

('O2_CONCENTRATOR', '氧氣濃縮機', '呼吸設備', 'OXYGEN', '%',
 '{"output_lpm": 5, "requires_power": true, "hours_unlimited": true}',
 '["AVAILABLE", "IN_USE", "MAINTENANCE", "OFFLINE"]'),

-- 一般設備 (無韌性計算)
('SURGICAL_PACK', '手術包', '手術室', NULL, NULL,
 NULL,
 '["READY", "IN_USE", "NEEDS_RESTOCK"]'),

('MONITOR', '生理監視器', '診斷設備', NULL, NULL,
 '{"power_watts": 50}',
 '["AVAILABLE", "IN_USE", "MAINTENANCE"]');
```

### 2.4 新 API 設計

```
┌─────────────────────────────────────────────────────────────────┐
│ Equipment API (設備管理)                                         │
├─────────────────────────────────────────────────────────────────┤
│ GET  /api/v2/equipment                                          │
│      → 列出所有設備 (含聚合狀態，來自 v_equipment_status)          │
│                                                                 │
│ GET  /api/v2/equipment/{id}                                     │
│      → 取得單一設備詳情 (含所有單位)                               │
│                                                                 │
│ GET  /api/v2/equipment/{id}/units                               │
│      → 取得設備的所有單位                                         │
│                                                                 │
│ POST /api/v2/equipment/units/{unit_id}/check                    │
│      → 檢查/更新單位狀態                                          │
│      Body: { level_percent, status, remarks }                   │
│      → 回傳更新後的設備聚合狀態                                    │
│                                                                 │
│ POST /api/v2/equipment/units/{unit_id}/reset                    │
│      → 重置單位檢查狀態                                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Equipment Types API (設備類型管理)                                │
├─────────────────────────────────────────────────────────────────┤
│ GET  /api/v2/equipment-types                                    │
│      → 列出所有設備類型 (含狀態選項、容量設定等)                    │
│                                                                 │
│ GET  /api/v2/equipment-types/{type_code}                        │
│      → 取得單一類型詳情                                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Resilience API (韌性儀表板，供前端直接使用)                        │
├─────────────────────────────────────────────────────────────────┤
│ GET  /api/v2/resilience/dashboard                               │
│      → 韌性儀表板資料 (已計算好的時數、狀態)                        │
│      Response: {                                                │
│        summary: { overall_status, min_hours, ... },             │
│        lifelines: [                                             │
│          {                                                      │
│            category: "POWER",                                   │
│            name: "電力供應",                                     │
│            total_hours: 24.5,                                   │
│            items: [                                             │
│              {                                                  │
│                equipment_id: "UTIL-001",                        │
│                name: "行動電源站",                                │
│                units: [                                         │
│                  { serial: "PS-001", level: 95, status: "IN_USE", │
│                    hours: 19, last_check: "..." }               │
│                ]                                                │
│              }                                                  │
│            ]                                                    │
│          },                                                     │
│          { category: "OXYGEN", ... }                            │
│        ]                                                        │
│      }                                                          │
│                                                                 │
│ GET  /api/v2/resilience/power                                   │
│      → 電力韌性詳情                                               │
│                                                                 │
│ GET  /api/v2/resilience/oxygen                                  │
│      → 氧氣韌性詳情                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、新舊架構對比

### 3.1 資料流對比

**舊架構:**
```
前端更新 → equipment_units 更新
        → 計算平均值
        → 更新 equipment 表 (冗餘)
        → 前端需 refreshKey 技巧重新載入
```

**新架構:**
```
前端更新 → equipment_units 更新 (唯一寫入點)
        → API 回傳即時計算的聚合值
        → 前端直接使用回傳值更新 UI
```

### 3.2 查詢對比

**舊架構 (Resilience Service):**
```python
# 需要判斷 tracking_mode
if equipment['tracking_mode'] == 'PER_UNIT':
    # 查 equipment_units，計算...
else:
    # 用 equipment.power_level...

# 需要判斷 device_type
if device_type == 'POWER_STATION':
    hours = capacity_wh * level / 100 / output_watts
elif device_type == 'GENERATOR':
    hours = tank * level / 100 / fuel_rate
```

**新架構:**
```python
# 統一查詢 v_resilience_equipment 檢視表
# 容量計算公式存在 equipment_types.capacity_config
# API 層解析 JSON 並套用公式
```

### 3.3 擴展性對比

**舊架構 - 新增太陽能板:**
1. 修改 equipment 表結構 (新增欄位)
2. 修改 seeder_demo.py
3. 修改 resilience_service.py (新增 device_type 判斷)
4. 修改 Index.html (新增 UI)

**新架構 - 新增太陽能板:**
1. INSERT INTO equipment_types (新類型)
2. INSERT INTO equipment (新設備)
3. INSERT INTO equipment_units (新單位)
4. 前端自動根據 API 回傳的 resilience_category 渲染

---

## 四、實施計劃

### Phase 1: 資料庫遷移 (Day 1-2)

#### 1.1 建立新表結構
```sql
-- 建立新表 (equipment_types, 新版 equipment_units)
-- 建立檢視表 (v_equipment_status, v_resilience_equipment)
```

#### 1.2 資料遷移腳本
```python
def migrate_equipment_data():
    # 1. 從舊 equipment 表推斷 type_code
    # 2. 確保所有設備都有對應的 units (即使只有一台)
    # 3. 保留 equipment_check_history
```

#### 1.3 相容性層
```python
# 提供舊 API 相容端點，逐步過渡
@app.get("/api/equipment")  # 舊 API，呼叫新架構
@app.get("/api/v2/equipment")  # 新 API
```

### Phase 2: API 重構 (Day 3-4)

#### 2.1 新增 v2 API 端點
- `/api/v2/equipment`
- `/api/v2/equipment-types`
- `/api/v2/resilience/dashboard`

#### 2.2 重構 Resilience Service
- 改用 v_resilience_equipment 檢視表
- 從 equipment_types.capacity_config 讀取計算公式
- 移除硬編碼的 device_type 判斷

### Phase 3: 前端重構 (Day 5-7)

#### 3.1 設備管理 Tab
- 使用新 API `/api/v2/equipment`
- 移除 refreshKey 技巧
- 狀態直接從 API 回傳取得

#### 3.2 韌性估算 Tab
- 使用新 API `/api/v2/resilience/dashboard`
- 統一渲染邏輯 (根據 resilience_category)
- 移除設備類型硬編碼

#### 3.3 即時同步
- 更新單位後，API 回傳包含更新後的聚合狀態
- 前端直接更新對應的 UI 區塊

### Phase 4: 測試與優化 (Day 8)

#### 4.1 功能測試
- [ ] 設備狀態更新同步
- [ ] 韌性計算正確性
- [ ] 設備類型擴展測試

#### 4.2 效能優化
- 索引優化
- 查詢計劃分析

---

## 五、風險評估

| 風險 | 影響 | 緩解措施 |
|------|------|----------|
| 資料遷移失敗 | 高 | 完整備份、遷移腳本測試、回滾計劃 |
| API 相容性問題 | 中 | 保留 v1 API 相容層 |
| 前端改動範圍大 | 中 | 分階段重構、保留舊程式碼 |
| Vercel 冷啟動 | 低 | 與現行相同，無額外影響 |

---

## 六、成功指標

1. **同步問題消除**: 設備狀態在所有 Tab 即時一致
2. **擴展性提升**: 新增設備類型只需資料庫操作
3. **程式碼簡化**: Resilience Service 減少 50% 以上的條件判斷
4. **API 清晰**: 前端只需調用預先計算好的 API

---

## 七、附錄

### A. 現有設備類型對照表

| 舊 device_type | 新 type_code | resilience_category |
|---------------|--------------|---------------------|
| POWER_STATION | POWER_STATION | POWER |
| GENERATOR | GENERATOR | POWER |
| (無) | O2_CYLINDER_H | OXYGEN |
| (無) | O2_CYLINDER_E | OXYGEN |
| O2_CONCENTRATOR | O2_CONCENTRATOR | OXYGEN |
| (無) | SURGICAL_PACK | NULL |
| (無) | MONITOR | NULL |

### B. API 回應範例

```json
// GET /api/v2/resilience/dashboard
{
  "summary": {
    "overall_status": "CAUTION",
    "min_hours": 8.5,
    "limiting_factor": "OXYGEN",
    "check_progress": {
      "total": 12,
      "checked": 10,
      "percentage": 83
    }
  },
  "lifelines": [
    {
      "category": "POWER",
      "name": "電力供應",
      "status": "SAFE",
      "total_hours": 24.5,
      "consumption": {
        "load_watts": 500,
        "load_display": "500W"
      },
      "items": [
        {
          "equipment_id": "UTIL-001",
          "name": "行動電源站",
          "type_code": "POWER_STATION",
          "check_status": "CHECKED",
          "units": [
            {
              "unit_id": 1,
              "serial": "PS-001",
              "label": "電源站1號",
              "level_percent": 95,
              "status": "IN_USE",
              "hours": 19.0,
              "last_check": "2025-12-17T10:30:00Z"
            },
            {
              "unit_id": 2,
              "serial": "PS-002",
              "label": "電源站2號",
              "level_percent": 60,
              "status": "CHARGING",
              "hours": 12.0,
              "last_check": "2025-12-17T10:30:00Z",
              "warning": "充電中，請於完成後更新狀態"
            }
          ]
        }
      ],
      "charging_warnings": [
        "行動電源站 有 1 台充電中，請於充電完成後更新狀態"
      ]
    },
    {
      "category": "OXYGEN",
      "name": "氧氣供應",
      "status": "CAUTION",
      "total_hours": 8.5,
      "items": [...]
    }
  ]
}
```

---

## 八、外部評審意見 (Gemini Review)

> 日期: 2025-12-17

### ✅ 核心優點確認

1. **Single Source of Truth**: 將動態數據統一存於 `equipment_units`，透過 View 即時聚合
2. **Unit-Centric**: 統一後端邏輯，前端不需處理單一/多單位兩套程式碼
3. **Configurable Types**: 新增設備類型只需資料庫操作，不需修改程式碼
4. **xIRS 家族一致性**: API 回傳格式設計了 `category` 和 `resilience_category`

### ⚠️ 技術風險與對策

#### 風險 1: SQLite 對 JSON 的支援性

**問題**: Spec 使用 `JSONB`，但 MIRS 使用 SQLite，需用 `TEXT` + `json_extract()`。

**對策**:
```sql
-- 改用 TEXT 儲存 JSON
capacity_config TEXT,  -- 原 JSONB → TEXT

-- 查詢時使用 json_extract
SELECT json_extract(capacity_config, '$.base_capacity_wh') as capacity
FROM equipment_types WHERE type_code = 'POWER_STATION';
```

**Python 層驗證**:
```python
from pydantic import BaseModel, validator
import json

class CapacityConfig(BaseModel):
    base_capacity_wh: int | None = None
    output_watts: int | None = None
    hours_per_100pct: float | None = None

    @validator('*', pre=True)
    def validate_positive(cls, v):
        if isinstance(v, (int, float)) and v < 0:
            raise ValueError('Capacity values must be positive')
        return v
```

#### 風險 2: 計算公式的安全性

**問題**: `hours_formula` 若用 `eval()` 執行有資安風險。

**對策**: 採用 **Calculator Strategy 模式** (推薦方案 A)

```python
# strategies/capacity_calculator.py
from abc import ABC, abstractmethod

class CapacityCalculator(ABC):
    @abstractmethod
    def calculate_hours(self, level_percent: int, config: dict) -> float:
        pass

class LinearDepletionCalculator(CapacityCalculator):
    """線性消耗 (電源站、氧氣瓶)"""
    def calculate_hours(self, level_percent: int, config: dict) -> float:
        return config['hours_per_100pct'] * level_percent / 100

class FuelBasedCalculator(CapacityCalculator):
    """燃油消耗 (發電機)"""
    def calculate_hours(self, level_percent: int, config: dict) -> float:
        tank_liters = config['tank_liters'] * level_percent / 100
        return tank_liters / config['fuel_rate_lph']

# 註冊表 (取代 eval)
CALCULATORS = {
    'LINEAR': LinearDepletionCalculator(),
    'FUEL_BASED': FuelBasedCalculator(),
}

def get_calculator(strategy: str) -> CapacityCalculator:
    return CALCULATORS.get(strategy, LinearDepletionCalculator())
```

**capacity_config JSON 格式修改**:
```json
{
  "strategy": "LINEAR",
  "hours_per_100pct": 20,
  "base_capacity_wh": 2048,
  "output_watts": 100
}
```

#### 風險 3: 負載動態性

**問題**: 發電機油耗取決於負載 (開冷氣 vs 只開燈)。

**對策**: 保留為 **Phase 2** 功能

```python
# Phase 2: 新增 Scenario Multiplier
class ScenarioConfig:
    NORMAL = 1.0      # 正常運作
    EMERGENCY = 0.8   # 緊急節能模式
    HIGH_LOAD = 1.5   # 高負載模式 (如夏天開冷氣)

# 韌性計算時套用
def calculate_with_scenario(base_hours: float, scenario: str) -> float:
    multiplier = getattr(ScenarioConfig, scenario, 1.0)
    return base_hours / multiplier  # 高負載 → 時數減少
```

---

## 九、實作優先順序 (Action Plan)

基於外部評審建議，調整執行順序：

### Phase 0: 準備工作 (Day 0)
- [ ] 備份現有 SQLite 資料庫
- [ ] 撰寫 `backup.py` 自動備份腳本
- [ ] 建立 `migration_v1_to_v2.py` 框架

### Phase 1: 資料庫遷移 (Day 1-2)
- [ ] 建立新表 (`equipment_types`, 新版 `equipment_units`)
- [ ] 建立 View (`v_equipment_status`, `v_resilience_equipment`)
- [ ] 遷移舊資料 (`equipment.quantity` → 對應數量的 `equipment_units`)
- [ ] 驗證遷移正確性

### Phase 2: API 重構 (Day 3-4)
- [ ] 實作 Calculator Strategy 模式
- [ ] 新增 `/api/v2/resilience/dashboard` (前端最需要)
- [ ] 新增 `/api/v2/equipment` 系列端點
- [ ] 保留 v1 API 相容層

### Phase 3: 前端重構 (Day 5-7)
- [ ] 設備管理 Tab 改用 v2 API
- [ ] 韌性估算 Tab 改用 dashboard API
- [ ] 移除 `refreshKey` 技巧
- [ ] 實作 Optimistic UI 更新

### Phase 4: 測試與優化 (Day 8)
- [ ] 功能測試清單
- [ ] 效能優化 (索引)
- [ ] 文件更新

---

## 十、決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2025-12-17 | 採用 Calculator Strategy 取代 eval | 資安考量，避免程式碼注入風險 |
| 2025-12-17 | 使用 TEXT 儲存 JSON (非 JSONB) | SQLite 相容性 |
| 2025-12-17 | 負載動態性移至 Phase 2 | 優先完成核心重構，避免範圍蔓延 |
| 2025-12-17 | 外部評審通過，可開始實作 | Gemini 確認架構方向正確 |

---

## 十一、外部評審意見 (Grok Review)

> 日期: 2025-12-17

### ✅ Grok 最欣賞的亮點

1. **Unit-Centric 設計的徹底性**
   - 連「只有一台的發電機」也強制建立 `equipment_units`（serial: 1）
   - 後端邏輯完全統一，前端不用寫 `if quantity == 1 else ...` 分支
   - 長期維護成本大幅下降

2. **透過 View 實現即時聚合（v_equipment_status）**
   - 前端永遠只讀 View，永遠是最新計算結果
   - 不會出現「單位更新了但主表沒變」的鬼影問題
   - SQLite 普通 view 性能在 MIRS 資料量下完全足夠

3. **equipment_types + capacity_config 的可配置性**
   - 從「硬編碼系統」進化到「可設定系統」
   - 未來新增「太陽能板」「淨水器」只需插入資料，不用碰 Python 程式碼
   - 真正的「低代碼擴展」

4. **與 HIRS/xIRS 家族一致的 category 設計**
   - 統一分類讓「跨系統匯出/匯入」和「上報給上級單位」更容易
   - MIRS 可輕鬆對接更高層的災害應變系統

### ⚠️ Grok 更擔心的風險點

#### 風險 1: 資料遷移的破壞性

**建議對策**:
- ✅ 已建立 `backup.py` 自動備份腳本
- ✅ 遷移腳本支援 `--dry-run` 預覽
- ✅ 已建立 `rollback_v2_to_v1.py` 回滾腳本
- 建議：保留舊表 1-2 個月後再清除

#### 風險 2: SQLite JSON 欄位與 Pydantic 型別問題

**建議對策**:
```python
# 已實作於 models/v2_models.py
@validator('capacity_config', pre=True)
def parse_capacity_config(cls, v):
    if isinstance(v, str):
        return json.loads(v)
    return v
```

- ✅ 已建立 `models/v2_models.py` 含完整 Pydantic validators
- ✅ 所有 JSON 欄位都有 pre-validator 處理字串轉換

#### 風險 3: 負載動態性 (Phase 2 預留)

**建議結構**:
```json
{
  "strategy": "FUEL_BASED",
  "tank_liters": 50,
  "fuel_rate_lph": 1.5,
  "load_profiles": {
    "low": 1.0,
    "medium": 1.5,
    "high": 2.5
  }
}
```

- ✅ 已更新 GENERATOR 類型加入 `load_profiles` 結構
- ✅ `LoadProfile` Pydantic model 已定義於 `models/v2_models.py`
- 未來可讓使用者選擇「災難情境負載」

### 🚀 Grok 建議的實作順序 (與我們實際執行比對)

| Phase | Grok 建議 | 我們的實作狀態 |
|-------|-----------|---------------|
| 1. 資料庫層 | 新表、View、遷移腳本、backup | ✅ 完成 |
| 2. 後端 API | `/api/v2/resilience/dashboard` 最優先 | ✅ 完成 |
| 3. Calculator Strategy | 2-3 種策略 (Linear, Fuel, Battery) | ✅ 完成 4 種 |
| 4. 前端逐步切換 | Feature flag 控制新/舊 API | ✅ 完成 (Phase 3) |
| 5. 清理舊表 | 確認所有功能走新架構後再 drop | ✅ 完成 (保留向後兼容) |

### Grok 總結

> 這份重構計畫 **不僅是必要的，更是超前部署的**。它解決了當前最嚴重的技術債，
> 同時為 MIRS 未來 2-3 年的功能增長預留了完美擴展點。
>
> **結論與 Gemini 完全一致：Strongly Recommended to Proceed.**

---

## 十二、實作進度追蹤

### Phase 0: 準備工作 ✅ 完成
- [x] 備份現有 SQLite 資料庫
- [x] 撰寫 `scripts/backup.py` 自動備份腳本
- [x] 建立 `scripts/migration_v1_to_v2.py` 框架

### Phase 1: 資料庫遷移 ✅ 完成
- [x] 建立 `equipment_types` 表 (9 種類型)
- [x] 新增 `equipment.type_code` 和 `equipment.capacity_override` 欄位
- [x] 建立 `v_equipment_status` View
- [x] 建立 `v_resilience_equipment` View
- [x] 遷移舊資料 (61 設備, 184 單位)
- [x] 驗證遷移正確性

### Phase 2: API 重構 ✅ 完成
- [x] 實作 Calculator Strategy 模式 (`services/capacity_calculator.py`)
  - LinearDepletionCalculator (電源站、氧氣瓶)
  - FuelBasedCalculator (發電機)
  - PowerDependentCalculator (氧氣濃縮機)
  - NoCapacityCalculator (一般設備)
- [x] 新增 `/api/v2/equipment-types`
- [x] 新增 `/api/v2/equipment`
- [x] 新增 `/api/v2/equipment/{id}`
- [x] 新增 `/api/v2/resilience/dashboard`
- [x] 新增 `/api/v2/equipment/units/{id}/check`
- [x] 新增 `/api/v2/equipment/units/{id}/reset`
- [x] 建立 `models/v2_models.py` (Pydantic models with JSON validators)
- [x] 建立 `scripts/rollback_v2_to_v1.py` 回滾腳本

### Phase 3: 前端重構 ✅ 完成
- [x] 設備管理 Tab 改用 v2 API
- [x] 韌性估算 Tab 改用 dashboard API
- [x] 移除 `refreshKey` 技巧
- [x] 實作 Optimistic UI 更新

### Phase 4: 測試與優化 ✅ 完成
- [x] 功能測試清單
- [x] 效能優化 (索引)
- [x] 文件更新
- [x] 清理舊欄位 (保留向後兼容)

---

## 十三、外部評審意見 (ChatGPT Review)

> 日期: 2025-12-17

### ✅ ChatGPT 確認結構正確的部分

1. **消除狀態冗餘**: 以 `equipment_units` 為唯一寫入點，透過 View + API 聚合
2. **Unit-Centric 設計**: 所有設備一律有 unit，包括單一設備
3. **v2 API 分層**: equipment / types / resilience dashboard 分層清晰

### ⚠️ Phase 3 前必須修正的關鍵問題

#### 1. SQLite DDL 移除 JSONB ✅ 已修正
```sql
-- 錯誤
capacity_config JSONB

-- 正確
capacity_config TEXT  -- SQLite 用 TEXT 儲存 JSON
```

#### 2. v_equipment_status GROUP BY 修正 ✅ 已修正
```sql
-- 錯誤: 只 GROUP BY e.id
GROUP BY e.id;

-- 正確: GROUP BY 所有非聚合欄位
GROUP BY e.id, e.name, e.type_code, et.type_name, et.category, et.resilience_category;
```

#### 3. DB 層 CHECK 約束 ✅ 已加入文件
```sql
level_percent INTEGER DEFAULT 100 CHECK(level_percent BETWEEN 0 AND 100),
status TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK(status <> ''),
unit_serial TEXT NOT NULL CHECK(unit_serial <> ''),
```

#### 4. 韌性時數只計入「可用」狀態 ✅ 已實作
```python
# services/capacity_calculator.py
AVAILABLE_STATUSES = {'AVAILABLE', 'IN_USE'}
EXCLUDED_STATUSES = {'OFFLINE', 'MAINTENANCE', 'EMPTY'}
WARNING_STATUSES = {'CHARGING'}  # 計入但顯示警告
```

#### 5. capacity_config 加入 schema_version ✅ 已實作
```json
{
  "schema_version": 1,
  "strategy": "LINEAR",
  "hours_per_100pct": 20
}
```

#### 6. 未知策略對韌性設備報錯 ✅ 已實作
```python
def validate_strategy(strategy: str, is_resilience: bool = False):
    if strategy not in _CALCULATORS and is_resilience:
        raise StrategyValidationError(f"未知策略: {strategy}")
```

### 📋 ChatGPT 建議但暫緩實作的項目 (已全部完成)

| 項目 | 狀態 | 完成情況 |
|------|------|------|
| history 改用 unit_id FK | ✅ 完成 | Phase 4 - 新增 unit_id 欄位 |
| API 回傳 dashboard delta | ✅ 完成 | Phase 3 - dashboard_delta 已實作 |
| timestamp 統一 UTC + Z | ✅ 完成 | Phase 3 - UTC+Z 格式已統一 |

### ChatGPT 總結

> 這份重構計畫結構正確，但 Phase 3 前端工作開始前必須先完成：
> 1. DDL 修正 (JSONB → TEXT)
> 2. GROUP BY 修正
> 3. CHECK 約束
> 4. 狀態過濾邏輯
> 5. schema_version 驗證
>
> **這些修正已全部完成。可以開始 Phase 3。**

---

## 十四、實作進度追蹤 (更新)

### Phase 0-2: ✅ 完成
詳見第十二節

### Phase 2.5: ChatGPT 建議修正 ✅ 完成
- [x] DDL 文件修正 (JSONB → TEXT)
- [x] v_equipment_status VIEW 重建 (GROUP BY 修正)
- [x] capacity_config 加入 schema_version
- [x] Calculator 加入狀態過濾 (EXCLUDED_STATUSES)
- [x] Calculator 加入策略驗證 (StrategyValidationError)
- [x] 文件記錄 ChatGPT 評審意見

### Phase 3: 前端重構 ✅ 完成
- [x] 設備管理 Tab 改用 v2 API (`loadEquipment()` → `/api/v2/equipment`)
- [x] 韌性估算 Tab 改用 dashboard API (`loadResilienceStatus()` → `/api/v2/resilience/dashboard`)
- [x] 移除 `refreshKey` 技巧，改用 Optimistic UI
- [x] 實作 Optimistic UI 更新 (`updateEquipmentFromResponse()`, `applyDashboardDelta()`)
- [x] 設備檢查 Modal 加入 Unit 選擇器
- [x] API 回傳 dashboard_delta 供增量更新
- [x] Timestamp 統一 UTC+Z 格式

### Phase 4: 測試與優化 ✅ 完成
- [x] 功能測試清單 (2025-12-17)
  - 驗證 v2 API endpoints
  - 測試 PER_UNIT 設備檢查流程
  - 確認 dashboard API 數據正確性
- [x] 效能優化 (索引)
  - `idx_equipment_units_last_check` - 加速檢查狀態查詢
  - `idx_equipment_type_code` - 加速類型查詢
  - `idx_equipment_types_resilience` - 加速韌性設備篩選
- [x] history 改用 unit_id FK
  - 新增 `unit_id` 欄位至 `equipment_check_history`
  - 遷移 26 筆既有記錄 (100% 匹配)
  - 建立 `idx_equipment_check_history_unit_id` 索引
- [x] 清理舊欄位
  - 保留 `capacity_wh`, `output_watts`, `fuel_rate_lph` 向後兼容
  - 確認程式碼已改用 `equipment_types.capacity_config`
  - 「重新計算」「套用」按鈕保留作為備援功能

---

## 十五、多站點架構技術債 (Phase 5 待處理)

> **狀態**: 📋 已記錄，待 PWA App 完成後處理
> **記錄日期**: 2025-12-17
> **關聯**: 站務與工作人員任務聯繫功能

### 15.1 目前 ID 格式的衝突風險

| 資料表 | 目前格式 | 多站衝突風險 | 建議修改 |
|--------|----------|-------------|----------|
| `equipment.id` | `RESP-001`, `UTIL-001` | ⚠️ 高 | `{STATION}-{TYPE}-{SEQ}` |
| `equipment_units.id` | `1, 2, 3...` (自增) | 🔴 極高 | 改用 UUID |
| `equipment_units.unit_serial` | `H-CYL-001` | ⚠️ 高 | 加 station 前綴 |
| `equipment_check_history.id` | `1, 2, 3...` (自增) | 🔴 極高 | 改用 UUID |

### 15.2 缺失的關鍵欄位

```sql
-- 需新增的欄位 (Phase 5)
ALTER TABLE equipment ADD COLUMN station_id TEXT;
ALTER TABLE equipment_units ADD COLUMN station_id TEXT;
```

### 15.3 Phase 5 待實作項目

| 項目 | 說明 | 優先級 |
|------|------|--------|
| station_id 欄位 | 為 equipment, equipment_units 加入站點識別 | P0 |
| UUID 改造 | equipment_units.id 改用 UUID | P0 |
| 設備增減 API | POST/DELETE /api/v2/equipment | P1 |
| 站點範本匯入 | 快速部署新站點 | P1 |
| 站點合併流程 | ID 衝突解決策略 | P2 |

### 15.4 建議的 ID 策略 (供 Phase 5 參考)

```yaml
equipment_types:
  id_format: "{TYPE_CODE}"           # 全域唯一
  scope: GLOBAL
  example: "POWER_STATION"

equipment:
  id_format: "{STATION_ID}-{TYPE}-{SEQ}"
  scope: STATION
  example: "BORP-DNO-01-RESP-001"

equipment_units:
  id_format: UUID
  scope: STATION
  example: "550e8400-e29b-41d4-a716-446655440000"
```

### 15.5 相關提案文件

- `/Users/QmoMBA/Downloads/CIRS_RESILIENCE_PROPOSAL.md` - CIRS 韌性估算提案
- `/Users/QmoMBA/Downloads/MIRS_DISASTER_SIMULATION_PROPOSAL.md` - MIRS 災害模擬提案

---

**文件狀態**: ✅ 已通過三重外部評審 (Gemini + Grok + ChatGPT)，Phase 1-4 全部完成

**完成日期**: 2025-12-17
**技術債記錄**: 2025-12-17 (Phase 5 多站點架構)
