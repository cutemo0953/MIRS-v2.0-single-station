# MIRS v2.0 設備單位管理功能規格書

**版本**: 1.1
**更新日期**: 2025-12-17
**狀態**: ✅ 已實作 (Phase 1, 2, 3)

---

## 變更記錄

| 版本 | 日期 | 變更摘要 |
|------|------|----------|
| 1.0 | 2025-12-17 | 初版 |
| 1.1 | 2025-12-17 | 架構重構：移除 quantity 冗餘、改用 soft-delete、序號設定移至 equipment_types、智慧縮減策略、獨立生命週期事件表 |
| 1.1.1 | 2025-12-17 | **Phase 1-3 實作完成**：DB migrations、7 個 API 端點、前端 UI |

---

## 1. 背景與動機

### 1.1 問題描述

目前 MIRS 系統的設備單位數量是在初始化時由 seeder 固定設定的。在實際演習場景中，需要能夠動態調整設備配置。

### 1.2 使用情境

1. **演習前準備**：根據實際站點配置調整設備數量
2. **演習中模擬**：模擬設備故障（移除）或支援到達（新增）
3. **站點差異化**：不同醫療站有不同的設備配置
4. **完全損失模擬**：模擬某類設備完全不可用（0 台）

### 1.3 設計原則

1. **單一真相來源 (SSOT)**：`equipment_units` 為權威資料，所有數量皆為衍生計算
2. **可追溯性**：所有變更皆可稽核，不丟失歷史關聯
3. **可擴展性**：設定與邏輯分離，新增設備類型無需改程式碼
4. **彈性規則**：業務規則（如最低數量）可配置，非硬編碼

---

## 2. 架構設計

### 2.1 核心原則：移除 `equipment.quantity` 的權威性

```
┌─────────────────────────────────────────────────────────────────┐
│                    SINGLE SOURCE OF TRUTH                        │
│                                                                   │
│   equipment_units (is_active = 1)                                │
│   └── COUNT(*) = 實際數量                                         │
│                                                                   │
│   equipment.quantity → DEPRECATED (僅供舊版相容，不可寫入)         │
│                                                                   │
│   v_equipment_status.unit_count → 計算值，非儲存值                 │
└─────────────────────────────────────────────────────────────────┘
```

**實作要點：**
- API 回傳的 `quantity` 皆為 `COUNT(equipment_units WHERE is_active=1)` 即時計算
- 移除所有對 `equipment.quantity` 的寫入操作
- 前端不可傳入 `quantity` 欄位

### 2.2 Soft Delete（軟刪除）架構

```
equipment_units
├── is_active: BOOLEAN DEFAULT 1     # 啟用狀態
├── removed_at: TIMESTAMP            # 移除時間
├── removed_by: TEXT                 # 操作者
└── removal_reason: TEXT             # 移除原因

狀態流轉：
  ACTIVE (is_active=1)
      │
      ▼ DELETE API
  INACTIVE (is_active=0, removed_at=NOW())
      │
      ▼ RESTORE API (選用)
  ACTIVE (is_active=1, removed_at=NULL)
```

**優點：**
- 歷史檢查紀錄保持關聯完整
- 可追溯設備去向與原因
- 支援誤刪恢復

### 2.3 序號生成設定移至資料表

```sql
equipment_types
├── type_code: TEXT PRIMARY KEY
├── unit_prefix: TEXT           # 新增：序號前綴 (H-CYL, PS, GEN)
├── label_template: TEXT        # 新增：標籤模板 ({prefix}{n}{suffix})
└── ...

範例資料：
┌──────────────────┬─────────────┬─────────────────┐
│ type_code        │ unit_prefix │ label_template  │
├──────────────────┼─────────────┼─────────────────┤
│ O2_CYLINDER_H    │ H-CYL       │ H型{n}號        │
│ O2_CYLINDER_E    │ E-CYL       │ E型{n}號        │
│ POWER_STATION    │ PS          │ 電源站{n}號     │
│ GENERATOR        │ GEN         │ 發電機{n}號     │
│ O2_CONCENTRATOR  │ O2C         │ 濃縮機{n}號     │
└──────────────────┴─────────────┴─────────────────┘
```

---

## 3. 資料庫變更

### 3.1 Schema 變更

```sql
-- 1. equipment_units 新增軟刪除欄位
ALTER TABLE equipment_units ADD COLUMN is_active BOOLEAN DEFAULT 1;
ALTER TABLE equipment_units ADD COLUMN removed_at TIMESTAMP;
ALTER TABLE equipment_units ADD COLUMN removed_by TEXT;
ALTER TABLE equipment_units ADD COLUMN removal_reason TEXT;

-- 2. equipment_units 唯一性約束（防止並發衝突）
CREATE UNIQUE INDEX IF NOT EXISTS idx_equipment_units_serial
ON equipment_units(equipment_id, unit_serial) WHERE is_active = 1;

-- 3. equipment_types 新增序號設定
ALTER TABLE equipment_types ADD COLUMN unit_prefix TEXT;
ALTER TABLE equipment_types ADD COLUMN label_template TEXT;

-- 4. 更新 equipment_types 設定資料
UPDATE equipment_types SET unit_prefix = 'H-CYL', label_template = 'H型{n}號'
WHERE type_code = 'O2_CYLINDER_H';

UPDATE equipment_types SET unit_prefix = 'E-CYL', label_template = 'E型{n}號'
WHERE type_code = 'O2_CYLINDER_E';

UPDATE equipment_types SET unit_prefix = 'PS', label_template = '電源站{n}號'
WHERE type_code = 'POWER_STATION';

UPDATE equipment_types SET unit_prefix = 'GEN', label_template = '發電機{n}號'
WHERE type_code = 'GENERATOR';

UPDATE equipment_types SET unit_prefix = 'O2C', label_template = '濃縮機{n}號'
WHERE type_code = 'O2_CONCENTRATOR';

-- 5. 新增生命週期事件表（獨立於 check_history）
CREATE TABLE IF NOT EXISTS equipment_lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER,                    -- 關聯的單位 ID
    equipment_id TEXT NOT NULL,         -- 關聯的設備 ID
    event_type TEXT NOT NULL,           -- CREATE, SOFT_DELETE, RESTORE, UPDATE
    actor TEXT,                         -- 操作者
    reason TEXT,                        -- 原因說明
    snapshot_json TEXT,                 -- 事件當下的狀態快照
    correlation_id TEXT,                -- 關聯 ID（批次操作）
    station_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CHECK(event_type IN ('CREATE', 'SOFT_DELETE', 'RESTORE', 'UPDATE'))
);

CREATE INDEX idx_lifecycle_equipment ON equipment_lifecycle_events(equipment_id);
CREATE INDEX idx_lifecycle_unit ON equipment_lifecycle_events(unit_id);
CREATE INDEX idx_lifecycle_time ON equipment_lifecycle_events(created_at DESC);

-- 6. 更新 v_equipment_status View（只計算 active units）
DROP VIEW IF EXISTS v_equipment_status;
CREATE VIEW v_equipment_status AS
SELECT
    e.id, e.name, e.type_code,
    et.type_name, et.category, et.resilience_category,
    et.unit_prefix, et.label_template,
    COUNT(u.id) as unit_count,
    ROUND(AVG(u.level_percent)) as avg_level,
    SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) as checked_count,
    MAX(u.last_check) as last_check,
    CASE
        WHEN COUNT(u.id) = 0 THEN 'NO_UNITS'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0 THEN 'UNCHECKED'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id) THEN 'CHECKED'
        ELSE 'PARTIAL'
    END as check_status
FROM equipment e
LEFT JOIN equipment_types et ON e.type_code = et.type_code
LEFT JOIN equipment_units u ON e.id = u.equipment_id AND u.is_active = 1
GROUP BY e.id;
```

### 3.2 資料遷移

```sql
-- 為現有 equipment_units 設定 is_active = 1
UPDATE equipment_units SET is_active = 1 WHERE is_active IS NULL;
```

---

## 4. API 設計

### 4.1 新增設備單位

```
POST /api/v2/equipment/{equipment_id}/units
```

**Request Body:**
```json
{
  "level_percent": 100,           // 選填，預設 100
  "status": "AVAILABLE",          // 選填，預設 AVAILABLE
  "reason": "演習新增設備"         // 選填，記錄原因
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "unit": {
    "id": 15,
    "equipment_id": "RESP-001",
    "unit_serial": "H-CYL-006",
    "unit_label": "H型6號",
    "level_percent": 100,
    "status": "AVAILABLE",
    "is_active": true
  },
  "equipment_summary": {
    "equipment_id": "RESP-001",
    "name": "H型氧氣鋼瓶",
    "active_unit_count": 6,
    "total_hours": 52.3
  },
  "event_id": 123,
  "message": "已新增 H型6號，目前共 6 支"
}
```

**驗證規則:**
- `equipment_id` 必須存在
- 該設備的 `tracking_mode` 必須為 `PER_UNIT`
- `level_percent` 必須在 0-100 之間
- 生成的 `unit_serial` 不可與現有 active unit 重複

**並發處理:**
```python
MAX_RETRY = 3
for attempt in range(MAX_RETRY):
    try:
        serial = generate_next_serial(equipment_id)
        cursor.execute("INSERT INTO equipment_units ...")
        break
    except sqlite3.IntegrityError:  # UNIQUE constraint failed
        if attempt == MAX_RETRY - 1:
            raise HTTPException(409, "序號生成衝突，請重試")
        continue
```

### 4.2 移除設備單位（Soft Delete）

```
DELETE /api/v2/equipment/units/{unit_id}
```

**Request Body (選填):**
```json
{
  "reason": "設備故障送修",
  "actor": "operator_001"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "removed_unit": {
    "id": 15,
    "unit_serial": "H-CYL-006",
    "unit_label": "H型6號",
    "level_percent": 100,
    "removed_at": "2025-12-17T15:30:00Z",
    "removal_reason": "設備故障送修"
  },
  "equipment_summary": {
    "equipment_id": "RESP-001",
    "name": "H型氧氣鋼瓶",
    "active_unit_count": 5,
    "total_hours": 45.2
  },
  "event_id": 124,
  "message": "已移除 H型6號，目前剩餘 5 支"
}
```

**行為說明:**
- 執行 `UPDATE equipment_units SET is_active=0, removed_at=NOW(), ...`
- 不執行 `DELETE`，保留歷史關聯
- 允許移除到 0 個單位（完全損失模擬）

### 4.3 恢復已移除單位（選用）

```
POST /api/v2/equipment/units/{unit_id}/restore
```

**Response (200 OK):**
```json
{
  "success": true,
  "restored_unit": {
    "id": 15,
    "unit_serial": "H-CYL-006",
    "unit_label": "H型6號"
  },
  "equipment_summary": {
    "equipment_id": "RESP-001",
    "active_unit_count": 6
  },
  "message": "已恢復 H型6號"
}
```

### 4.4 批次調整數量（智慧縮減）

```
PUT /api/v2/equipment/{equipment_id}/quantity
```

**Request Body:**
```json
{
  "target_quantity": 3,
  "default_level_percent": 100,
  "default_status": "AVAILABLE",
  "reason": "演習情境調整"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "equipment_id": "RESP-001",
  "previous_quantity": 5,
  "new_quantity": 3,
  "action": "shrink",
  "units_removed": [
    {"id": 5, "label": "H型5號", "level_percent": 15, "reason": "最低電量"},
    {"id": 4, "label": "H型4號", "level_percent": 50, "reason": "次低電量"}
  ],
  "units_added": [],
  "equipment_summary": {
    "active_unit_count": 3,
    "total_hours": 32.1
  },
  "correlation_id": "batch-abc123",
  "message": "已從 5 支調整為 3 支（移除 2 支低電量單位）"
}
```

**智慧縮減優先序（Removal Priority）:**

```python
def get_removal_priority(unit) -> tuple:
    """
    回傳排序 tuple，值越小越優先移除

    優先序：
    1. 狀態：EMPTY > MAINTENANCE > IN_USE > CHARGING > AVAILABLE
    2. 電量：level_percent 由低到高
    3. 檢查時間：last_check 越舊越優先
    4. 序號：serial 數字越大越優先（tie-breaker）
    """
    status_priority = {
        'EMPTY': 0,
        'MAINTENANCE': 1,
        'IN_USE': 2,
        'CHARGING': 3,
        'AVAILABLE': 4
    }

    return (
        status_priority.get(unit.status, 5),
        unit.level_percent,
        unit.last_check or datetime.min,  # NULL 視為最舊
        -extract_serial_number(unit.unit_serial)  # 負號讓大序號優先
    )

# 排序後取前 N 個移除
units_to_remove = sorted(active_units, key=get_removal_priority)[:remove_count]
```

### 4.5 更新單位屬性

```
PATCH /api/v2/equipment/units/{unit_id}
```

**Request Body:**
```json
{
  "level_percent": 85,
  "status": "AVAILABLE",
  "unit_label": "H型1號(主力)"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "unit": {
    "id": 1,
    "unit_serial": "H-CYL-001",
    "unit_label": "H型1號(主力)",
    "level_percent": 85,
    "status": "AVAILABLE"
  },
  "changes": {
    "level_percent": {"from": 100, "to": 85},
    "unit_label": {"from": "H型1號", "to": "H型1號(主力)"}
  }
}
```

### 4.6 取得設備單位列表

```
GET /api/v2/equipment/{equipment_id}/units?include_inactive=false
```

**Query Parameters:**
- `include_inactive`: 是否包含已移除單位（預設 false）

**Response (200 OK):**
```json
{
  "equipment_id": "RESP-001",
  "equipment_name": "H型氧氣鋼瓶",
  "type_code": "O2_CYLINDER_H",
  "unit_prefix": "H-CYL",
  "label_template": "H型{n}號",
  "active_count": 5,
  "inactive_count": 1,
  "units": [
    {
      "id": 1,
      "unit_serial": "H-CYL-001",
      "unit_label": "H型1號",
      "level_percent": 100,
      "status": "AVAILABLE",
      "is_active": true,
      "last_check": "2025-12-17T10:30:00Z",
      "hours_remaining": 11.7
    },
    // ... active units
  ],
  "inactive_units": [
    {
      "id": 15,
      "unit_serial": "H-CYL-006",
      "unit_label": "H型6號",
      "is_active": false,
      "removed_at": "2025-12-17T15:30:00Z",
      "removal_reason": "設備故障送修"
    }
  ]
}
```

---

## 5. 序號生成邏輯

### 5.1 從 equipment_types 讀取設定

```python
def generate_next_serial(cursor, equipment_id: str) -> tuple[str, str]:
    """
    生成下一個序號和標籤

    Returns:
        (unit_serial, unit_label)
    """
    # 1. 查詢設備的 type_code 和序號設定
    cursor.execute("""
        SELECT e.type_code, et.unit_prefix, et.label_template
        FROM equipment e
        JOIN equipment_types et ON e.type_code = et.type_code
        WHERE e.id = ?
    """, (equipment_id,))

    row = cursor.fetchone()
    if not row:
        raise ValueError(f"找不到設備 {equipment_id} 或其類型設定")

    type_code, prefix, template = row

    # 2. 找出該設備現有的最大序號
    cursor.execute("""
        SELECT unit_serial FROM equipment_units
        WHERE equipment_id = ?
        ORDER BY unit_serial DESC
    """, (equipment_id,))

    existing_serials = [r[0] for r in cursor.fetchall()]

    # 3. 計算下一個序號
    max_num = 0
    for serial in existing_serials:
        if serial and serial.startswith(prefix):
            try:
                num = int(serial.split('-')[-1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass

    next_num = max_num + 1
    unit_serial = f"{prefix}-{next_num:03d}"

    # 4. 根據模板生成標籤
    # 模板格式: "H型{n}號" → "H型6號"
    unit_label = template.replace('{n}', str(next_num))

    return unit_serial, unit_label
```

### 5.2 Fallback 機制

若 `equipment_types` 缺少 `unit_prefix` 設定，使用預設邏輯：

```python
DEFAULT_PREFIX = "UNIT"
DEFAULT_TEMPLATE = "單位{n}號"

if not prefix:
    prefix = DEFAULT_PREFIX
if not template:
    template = DEFAULT_TEMPLATE
```

---

## 6. 事件記錄

### 6.1 生命週期事件類型

| event_type | 觸發時機 | snapshot 內容 |
|------------|----------|---------------|
| CREATE | 新增單位 | 完整 unit 資料 |
| SOFT_DELETE | 移除單位 | 移除前的完整狀態 |
| RESTORE | 恢復單位 | 恢復後的狀態 |
| UPDATE | 更新屬性 | 變更前後的 diff |

### 6.2 記錄範例

```json
{
  "id": 123,
  "unit_id": 15,
  "equipment_id": "RESP-001",
  "event_type": "SOFT_DELETE",
  "actor": "operator_001",
  "reason": "設備故障送修",
  "snapshot_json": {
    "unit_serial": "H-CYL-006",
    "unit_label": "H型6號",
    "level_percent": 100,
    "status": "AVAILABLE",
    "last_check": "2025-12-17T10:00:00Z"
  },
  "correlation_id": null,
  "created_at": "2025-12-17T15:30:00Z"
}
```

### 6.3 批次操作關聯

批次調整數量時，所有相關事件共用同一個 `correlation_id`：

```json
// 事件 1
{"id": 124, "event_type": "SOFT_DELETE", "correlation_id": "batch-abc123", ...}
// 事件 2
{"id": 125, "event_type": "SOFT_DELETE", "correlation_id": "batch-abc123", ...}
```

---

## 7. 業務規則配置

### 7.1 可配置規則

不再硬編碼「至少保留 1 個單位」，改為可配置：

```python
# config.py 或資料庫配置
EQUIPMENT_RULES = {
    'min_units': 0,                    # 最小單位數（0 = 允許完全移除）
    'max_units': 99,                   # 最大單位數
    'allow_remove_when_in_use': False, # 是否允許移除 IN_USE 狀態的單位
    'require_removal_reason': True,    # 移除時是否必須填寫原因
}
```

### 7.2 0 單位處理

當設備降至 0 個 active unit：

```json
{
  "equipment_id": "RESP-001",
  "name": "H型氧氣鋼瓶",
  "active_unit_count": 0,
  "availability_state": "NOT_AVAILABLE",
  "resilience_hours": 0,
  "warning": "此設備目前無可用單位"
}
```

韌性儀表板顯示：
```
💨 氧氣供應: 0 小時
   ⚠️ H型氧氣鋼瓶: 無可用單位
   ✓ E型氧氣瓶: 4 支 (6.8 小時)
```

---

## 8. API 端點總覽

| Method | Endpoint | 用途 |
|--------|----------|------|
| GET | `/api/v2/equipment/{id}/units` | 取得單位列表 |
| POST | `/api/v2/equipment/{id}/units` | 新增單位 |
| PATCH | `/api/v2/equipment/units/{id}` | 更新單位屬性 |
| DELETE | `/api/v2/equipment/units/{id}` | 移除單位 (soft delete) |
| POST | `/api/v2/equipment/units/{id}/restore` | 恢復已移除單位 |
| PUT | `/api/v2/equipment/{id}/quantity` | 批次調整數量 |
| GET | `/api/v2/equipment/lifecycle-events` | 查詢生命週期事件 |

---

## 9. 測試計畫

### 9.1 單元測試

```python
# 基本 CRUD
def test_add_unit_success():
    """新增單位成功，active_count +1"""

def test_add_unit_auto_serial_from_type():
    """序號從 equipment_types.unit_prefix 生成"""

def test_remove_unit_soft_delete():
    """移除單位使用 soft delete，row 保留"""

def test_remove_unit_allows_zero():
    """允許移除到 0 個單位"""

def test_restore_unit_success():
    """恢復已移除單位"""

# 智慧縮減
def test_batch_shrink_priority_empty_first():
    """批次縮減優先移除 EMPTY 狀態"""

def test_batch_shrink_priority_low_level():
    """批次縮減優先移除低電量"""

def test_batch_shrink_returns_removed_list():
    """批次縮減回傳移除清單"""

# 並發處理
def test_serial_generation_concurrent():
    """並發生成序號不衝突（retry 機制）"""

def test_unique_constraint_active_serial():
    """active unit 的 serial 唯一約束"""

# 韌性計算
def test_add_unit_increases_hours():
    """新增單位增加韌性小時數"""

def test_remove_unit_decreases_hours():
    """移除單位減少韌性小時數"""

def test_zero_units_shows_warning():
    """0 單位顯示警告而非錯誤"""

# 稽核追蹤
def test_lifecycle_event_created():
    """操作產生生命週期事件"""

def test_batch_operation_correlation_id():
    """批次操作共用 correlation_id"""

def test_history_maintains_unit_reference():
    """soft delete 後歷史紀錄仍可關聯"""
```

### 9.2 整合測試

1. 完整流程：新增 → 檢查 → 移除 → 恢復 → 驗證歷史
2. 韌性儀表板數值隨單位變更即時更新
3. 批次調整大量單位（壓力測試）
4. 前端 optimistic UI 與後端同步

---

## 10. 實作計畫

### Phase 1: 資料庫遷移 ✅
- [x] 新增 `is_active`, `removed_at` 等欄位到 `equipment_units`
- [x] 新增 `unit_prefix`, `label_template` 到 `equipment_types`
- [x] 建立 `equipment_lifecycle_events` 表
- [x] 更新 `v_equipment_status` View
- [x] 資料遷移腳本

### Phase 2: 後端 API ✅
- [x] `GET /api/v2/equipment/{id}/units`
- [x] `POST /api/v2/equipment/{id}/units`
- [x] `PATCH /api/v2/equipment/units/{id}`
- [x] `DELETE /api/v2/equipment/units/{id}`
- [x] `PUT /api/v2/equipment/{id}/quantity`
- [x] `POST /api/v2/equipment/units/{id}/restore`
- [x] `GET /api/v2/equipment/lifecycle-events`

### Phase 3: 前端 UI ✅
- [x] 單位管理彈窗
- [x] 快速數量調整控制項
- [x] 確認對話框（含移除原因輸入）
- [x] 已移除單位檢視/恢復

### Phase 4: 進階功能
- [ ] 生命週期事件查詢介面
- [ ] 批次匯入/匯出
- [ ] 設備範本（預設配置）

---

## 11. 附錄

### 11.1 與現有 API 的相容性

現有 `/api/equipment` 和 `/api/equipment/units/update` 維持不變，新功能使用 `/api/v2/` 前綴。

### 11.2 相關文件

- [EQUIPMENT_ARCHITECTURE_REDESIGN.md](./EQUIPMENT_ARCHITECTURE_REDESIGN.md)
- [IRS_RESILIENCE_FRAMEWORK.md](./IRS_RESILIENCE_FRAMEWORK.md)

---

**文件版本**: 1.1
**建立日期**: 2025-12-17
**更新日期**: 2025-12-17
**作者**: Claude Code
**審閱**: ChatGPT, Gemini
**狀態**: 待審核
