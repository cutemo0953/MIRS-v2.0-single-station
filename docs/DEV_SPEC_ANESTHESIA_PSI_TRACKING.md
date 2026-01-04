# 麻醉氧氣 PSI 追蹤開發規格書

**版本**: 1.0.0
**日期**: 2026-01-04
**狀態**: 規格撰寫中

---

## 0. 摘要

將麻醉 PWA 的氧氣追蹤從「百分比」升級為「PSI 追蹤」，與 EMT Transfer 模組對齊。

### 主要改進

| 現況 (v1.x) | 目標 (v2.0) |
|-------------|-------------|
| level_percent (0-100%) | PSI 實測值 (0-2200) |
| 估算剩餘時間誤差大 | PSI → L 精確計算 |
| 無歷史追蹤 | PSI 記錄隨 vitals 存檔 |
| 手動選擇鋼瓶 | 認領時輸入起始 PSI |

---

## 1. 背景與動機

### 1.1 現有問題

1. **不精確**: `level_percent` 來自設備狀態，可能不準確或過期
2. **無法計算消耗**: 百分比不知道鋼瓶類型/容量
3. **與 EMT 不一致**: EMT 已使用 PSI 追蹤，麻醉仍用百分比

### 1.2 目標

- 認領鋼瓶時記錄起始 PSI (EMT 模式)
- 術中定期記錄當前 PSI (可選)
- 結案時記錄結束 PSI
- 計算實際消耗升數

---

## 2. Schema 變更

### 2.1 anesthesia_cases 表新增欄位

```sql
ALTER TABLE anesthesia_cases ADD COLUMN oxygen_starting_psi INTEGER;
ALTER TABLE anesthesia_cases ADD COLUMN oxygen_ending_psi INTEGER;
ALTER TABLE anesthesia_cases ADD COLUMN oxygen_cylinder_type TEXT DEFAULT 'E';
```

### 2.2 anesthesia_vitals 表新增欄位 (可選)

```sql
ALTER TABLE anesthesia_vitals ADD COLUMN oxygen_psi INTEGER;
```

記錄每次 vitals 時的當前 PSI (可選輸入)。

### 2.3 新增表: anesthesia_oxygen_log (事件記錄)

```sql
CREATE TABLE IF NOT EXISTS anesthesia_oxygen_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,     -- CLAIM, PSI_UPDATE, RELEASE, CYLINDER_CHANGE
    cylinder_unit_id INTEGER,
    cylinder_type TEXT,
    psi_value INTEGER,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor_id TEXT,
    notes TEXT,
    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);
```

---

## 3. 計算公式

### 3.1 鋼瓶容量參考

| Type | 名稱 | 容量 (L) | 滿瓶 PSI |
|------|------|----------|----------|
| E | E-Tank (攜帶型) | 660 | 2100 |
| D | D-Tank (小型) | 350 | 2100 |
| M | M-Tank (中型) | 3000 | 2200 |
| H | H-Tank (大型) | 6900 | 2200 |

### 3.2 PSI → 升數轉換

```python
available_liters = (current_psi / full_psi) * capacity_liters
```

範例 (E-Tank):
- 2100 PSI → 660L
- 1500 PSI → (1500/2100) × 660 = 471L
- 500 PSI → (500/2100) × 660 = 157L

### 3.3 剩餘時間估算

```python
remaining_minutes = available_liters / o2_flow_lpm
```

範例:
- 471L / 6 L/min = 78.5 min

### 3.4 消耗計算

```python
consumed_liters = ((starting_psi - ending_psi) / full_psi) * capacity_liters
```

---

## 4. API 變更

### 4.1 認領鋼瓶 (修改)

**Endpoint**: `POST /api/anesthesia/cases/{case_id}/claim-oxygen`

**Request (v2.0)**:
```json
{
  "cylinder_unit_id": 123,
  "cylinder_type": "E",
  "initial_psi": 2100
}
```

**變更**:
- 新增 `cylinder_type` (E/D/M/H)
- `initial_pressure_psi` → `initial_psi` (命名對齊 EMT)
- 儲存到 `anesthesia_cases.oxygen_starting_psi`
- 寫入 `anesthesia_oxygen_log` (event_type=CLAIM)

### 4.2 更新 PSI (新增)

**Endpoint**: `PUT /api/anesthesia/cases/{case_id}/oxygen-psi`

**Request**:
```json
{
  "current_psi": 1500
}
```

**功能**:
- 隨時更新當前 PSI
- 可在記錄 vitals 時一起送
- 寫入 `anesthesia_oxygen_log` (event_type=PSI_UPDATE)

### 4.3 氧氣狀態 (修改)

**Endpoint**: `GET /api/anesthesia/cases/{case_id}/oxygen-status`

**Response (v2.0)**:
```json
{
  "source_type": "CYLINDER",
  "cylinder_serial": "O2-E-001",
  "cylinder_type": "E",
  "starting_psi": 2100,
  "current_psi": 1500,
  "available_liters": 471,
  "remaining_minutes": 78,
  "avg_flow_lpm": 6.0,
  "consumed_liters": 189,
  "consumption_rate_lph": 360,
  "low_warning": false,
  "critical_warning": false
}
```

**新增欄位**:
- `starting_psi`, `current_psi`
- `consumed_liters`
- `consumption_rate_lph` (每小時消耗升數)

### 4.4 釋放鋼瓶 (修改)

**Endpoint**: `DELETE /api/anesthesia/cases/{case_id}/claim-oxygen`

**Request (v2.0)**:
```json
{
  "ending_psi": 500
}
```

**變更**:
- 新增 `ending_psi` 參數
- 儲存到 `anesthesia_cases.oxygen_ending_psi`
- 計算並儲存 `consumed_liters`
- 寫入 `anesthesia_oxygen_log` (event_type=RELEASE)

### 4.5 結案 (修改)

**Endpoint**: `POST /api/anesthesia/cases/{case_id}/close`

**變更**:
- 如有認領鋼瓶且未記錄 `ending_psi`，提示輸入
- 計算總消耗量
- 更新 `equipment_units.level_percent` 根據 `ending_psi`

---

## 5. UI 變更

### 5.1 氧氣認領 Modal

```
┌─────────────────────────────────────┐
│ 氧氣管理                        [x] │
├─────────────────────────────────────┤
│ 目前狀態: [已認領 E-001]            │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ 鋼瓶編號: E-001                 │ │
│ │ 類型: E-Tank (660L)             │ │
│ │                                 │ │
│ │ 起始 PSI: 2100                  │ │
│ │ 目前 PSI: [1500] ← 可更新       │ │
│ │                                 │ │
│ │ ████████░░░░ 71%                │ │
│ │ 可用: 471L                      │ │
│ │ 預估: 78 min (@ 6 L/min)        │ │
│ │                                 │ │
│ │ 已消耗: 189L (28%)              │ │
│ └─────────────────────────────────┘ │
│                                     │
│ [更新 PSI] [釋放鋼瓶]               │
├─────────────────────────────────────┤
│ 可用氧氣瓶 (庫存)        [重新整理] │
│                                     │
│ ┌──────────────────────────────┐    │
│ │ E-002 (E) 2100 PSI (100%)    │    │
│ │ [認領]                       │    │
│ └──────────────────────────────┘    │
└─────────────────────────────────────┘
```

### 5.2 認領時輸入起始 PSI

```
┌─────────────────────────────────────┐
│ 認領氧氣瓶                      [x] │
├─────────────────────────────────────┤
│ 鋼瓶: E-001 (E-Tank)                │
│                                     │
│ 鋼瓶類型: [E ▼]                     │
│           (E-Tank 660L)             │
│                                     │
│ 起始 PSI: [2100] / 2100             │
│           ████████████ 100%         │
│           可用: 660 L               │
│                                     │
│         [確認認領]                  │
└─────────────────────────────────────┘
```

### 5.3 釋放時輸入結束 PSI

```
┌─────────────────────────────────────┐
│ 釋放氧氣瓶                      [x] │
├─────────────────────────────────────┤
│ 鋼瓶: E-001 (E-Tank)                │
│                                     │
│ 起始 PSI: 2100                      │
│ 結束 PSI: [500] / 2100              │
│           ██░░░░░░░░░░ 24%          │
│                                     │
│ 消耗: 1600 PSI → 502 L              │
│                                     │
│         [確認釋放]                  │
└─────────────────────────────────────┘
```

### 5.4 Vitals 記錄整合 (可選)

在 vitals 輸入區新增「O2 PSI」欄位：

```
┌─────────────────────────────────────┐
│ 生命徵象                            │
├─────────────────────────────────────┤
│ HR [70] | SBP [120] | DBP [80]      │
│ SpO2 [99] | EtCO2 [35]              │
│ O2 Flow [6] L/min                   │
│ O2 PSI [1500] ← 新增 (可選)         │
└─────────────────────────────────────┘
```

### 5.5 氧氣 Tab 整合

氧氣 Tab 顯示 PSI 歷史圖表：

```
┌─────────────────────────────────────┐
│ 氧氣追蹤                            │
├─────────────────────────────────────┤
│ PSI History                         │
│ 2100│●                              │
│ 1800│  ●                            │
│ 1500│    ●                          │
│ 1200│      ●                        │
│  900│        ●                      │
│     └─────────────────────────      │
│       09:00  09:30  10:00           │
│                                     │
│ 預估剩餘: 45 min (@ 6 L/min)        │
│ 消耗速率: 360 L/hr                  │
│                                     │
│ [低 PSI 警示設定]                   │
│ 警告: [800] PSI                     │
│ 危急: [400] PSI                     │
└─────────────────────────────────────┘
```

---

## 6. 警示機制

### 6.1 PSI 閾值

| 等級 | PSI 閾值 | 預估剩餘 | 動作 |
|------|----------|----------|------|
| 正常 | > 800 | > 25 min | 無 |
| 警告 | 400-800 | 12-25 min | 黃色閃爍 |
| 危急 | < 400 | < 12 min | 紅色閃爍 + 音效 |

### 6.2 UI 指示

```css
.o2-status-normal { background: var(--success); }
.o2-status-warning { background: var(--warning); animation: pulse 1s infinite; }
.o2-status-critical { background: var(--danger); animation: pulse 0.5s infinite; }
```

---

## 7. 與製氧機整合 (未來)

如果使用製氧機而非鋼瓶：

```json
{
  "source_type": "CONCENTRATOR",
  "concentrator_id": "OC-001",
  "output_lpm": 10,
  "power_status": "AC",
  "battery_percent": null
}
```

製氧機不追蹤 PSI，改追蹤：
- 輸出流量 (output_lpm)
- 電源狀態 (AC/DC)
- 電池電量 (如有)

---

## 8. 庫存連動

### 8.1 認領 (CLAIM)

```sql
UPDATE equipment_units SET
  claimed_by_case_id = ?,
  status = 'IN_USE'
WHERE id = ?
```

### 8.2 釋放 (RELEASE)

```sql
UPDATE equipment_units SET
  claimed_by_case_id = NULL,
  status = 'OK',
  level_percent = ?,  -- 根據 ending_psi 計算
  last_used_at = datetime('now')
WHERE id = ?
```

### 8.3 韌性估算

排除 `claimed_by_case_id IS NOT NULL` 的設備。

---

## 9. 實作順序

| Phase | 內容 | 優先級 |
|-------|------|--------|
| 9.1 | Schema 升級 (新增 PSI 欄位) | P0 |
| 9.2 | API 修改 (claim/release 含 PSI) | P0 |
| 9.3 | UI 修改 (PSI 輸入/顯示) | P0 |
| 9.4 | oxygen_log 事件記錄 | P1 |
| 9.5 | Vitals 整合 PSI 輸入 | P2 |
| 9.6 | PSI 歷史圖表 | P2 |
| 9.7 | 警示機制 | P1 |
| 9.8 | 製氧機支援 | P3 |

---

## 10. 測試案例

### 10.1 認領鋼瓶

```bash
curl -X POST "http://localhost:8000/api/anesthesia/cases/ANES-001/claim-oxygen?actor_id=DR001" \
  -H "Content-Type: application/json" \
  -d '{
    "cylinder_unit_id": 123,
    "cylinder_type": "E",
    "initial_psi": 2100
  }'
```

### 10.2 更新 PSI

```bash
curl -X PUT "http://localhost:8000/api/anesthesia/cases/ANES-001/oxygen-psi?actor_id=DR001" \
  -H "Content-Type: application/json" \
  -d '{"current_psi": 1500}'
```

### 10.3 釋放鋼瓶

```bash
curl -X DELETE "http://localhost:8000/api/anesthesia/cases/ANES-001/claim-oxygen?actor_id=DR001" \
  -H "Content-Type: application/json" \
  -d '{"ending_psi": 500}'
```

預期計算：
- 起始: 2100 PSI
- 結束: 500 PSI
- 消耗: (2100-500)/2100 × 660 = 502L

---

## 11. 參考資料

- EMT Transfer PWA DEV_SPEC (PSI 追蹤實作)
- MIRS Resilience Service (設備排除邏輯)
- 標準鋼瓶容量規格

---

## 12. 變更記錄

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| 1.0.0 | 2026-01-04 | 初版規格撰寫 |
