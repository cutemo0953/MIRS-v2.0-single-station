# EMT Transfer PWA 開發規格書

**版本**: 2.2.0
**日期**: 2026-01-04
**狀態**: Phase 2.2 完成

---

## 0. 摘要

EMT Transfer PWA 是 MIRS 的病患轉送任務管理模組，專為救護技術員 (EMT) 設計。

### v2.0 主要更新

1. **安全係數可調** (1-15×，預設 3×)
2. **氧氣 PSI 追蹤** (單瓶 PSI 而非瓶數)
3. **設備電量追蹤** (攜帶時記錄 %)
4. **三分離計量** (攜帶/歸還/消耗 分開記錄)
5. **韌性使用 available** (而非 on_hand)
6. **快捷輸入** (ETA/O2/IV 預設值 + 自訂)

主要功能：

- 物資需求計算（氧氣 L/min、輸液 mL/hr、設備電量 %）
- 安全係數 1-15× 備量（預設 3×）
- 離線優先架構 (IndexedDB + Background Sync)
- 庫存連動（Reserve → Issue → Return）
- 外帶物資入庫

---

## 0.1 設計原則

| 原則 | 說明 |
|------|------|
| **離線優先** | IndexedDB 本地儲存，背景同步 |
| **Event Sourcing** | Append-only event log，可重建狀態 |
| **安全係數** | 可調 1-15×（預設 3×），確保緊急狀況有備量 |
| **庫存連動** | Reserve/Issue/Return 事件連動主庫存 |
| **三分離計量** | 攜帶量、歸還量、消耗量 分開追蹤 |
| **PSI 追蹤** | 氧氣瓶記錄起始/結束 PSI，計算實際消耗 |

---

## 0.2 狀態機

```
PLANNING ──(confirm)──> READY ──(depart)──> EN_ROUTE ──(arrive)──> ARRIVED ──(finalize)──> COMPLETED
    │                      │                    │                      │
    └──────────────────────┴────────────────────┴──────────────────────┴──(abort)──> ABORTED
```

| 狀態 | 說明 | 庫存影響 |
|------|------|----------|
| PLANNING | 規劃中，可編輯 | 無 |
| READY | 已確認攜帶清單 | **RESERVE**: 扣住庫存 |
| EN_ROUTE | 轉送中 | **ISSUE**: 正式扣減 |
| ARRIVED | 已抵達，待結案 | 無 |
| COMPLETED | 結案 | **RETURN**: 歸還剩餘 |
| ABORTED | 中止 | **CANCEL_RESERVE**: 釋放扣住 |

---

## 0.3 UI 配色 (v2.2 更新)

### 主色系 (Header/按鈕)

| 用途 | Tailwind Class | HEX |
|------|----------------|-----|
| 主色 | `amber-500` | `#f59e0b` |
| 深色 | `amber-600` | `#d97706` |
| 淺色 | `amber-100` | `#fef3c7` |
| 背景 | `amber-50` | `#fffbeb` |

### 資源區塊配色 (v2.2 新增)

採用 MIRS 統一色系：

| 區塊 | 主色 | HEX | 對應 MIRS |
|------|------|-----|-----------|
| 藥物/耗材 | `dispense-purple-700` | `#7e2e83` | 藥局配藥 |
| 氧氣鋼瓶 | `amber-500` | `#f59e0b` | 韌性估算 |
| 設備電量 | `equipment-500` | `#6C7362` | 設備管理 |
| IV 輸液 | `teal-500` | `#14b8a6` | MIRS 主色 |

---

## 1. 資料庫 Schema

### 1.1 transfer_missions (v2.0 更新)

| 欄位 | 類型 | 說明 | v2.0 |
|------|------|------|------|
| mission_id | TEXT PK | TRF-YYYYMMDD-NNN | |
| status | TEXT | PLANNING/READY/EN_ROUTE/ARRIVED/COMPLETED/ABORTED | |
| origin_station_id | TEXT | 出發站點 ID (FK → stations) | ✓ 新增 |
| origin_station | TEXT | 出發站點名稱 (denormalized) | |
| destination_text | TEXT | 目的地描述（自由文字） | ✓ 新增 |
| destination | TEXT | 目的地 (legacy alias) | |
| eta_min | INT | 預估抵達時間（分鐘） | ✓ 新增 |
| estimated_duration_min | INT | 預估往返時間（分鐘） | |
| actual_duration_min | INT | 實際時間 | |
| patient_condition | TEXT | CRITICAL/STABLE/INTUBATED | |
| o2_lpm | REAL | 氧氣需求 L/min | ✓ 新增 |
| oxygen_requirement_lpm | REAL | (legacy alias for o2_lpm) | |
| iv_mode | TEXT | NONE/KVO/BOLUS/CUSTOM | ✓ 新增 |
| iv_mlhr_override | REAL | 自訂輸液速率 mL/hr (iv_mode=CUSTOM) | ✓ 新增 |
| iv_rate_mlhr | REAL | 計算後輸液速率 mL/hr | |
| ventilator_required | INT | 是否需呼吸器 | |
| safety_factor | REAL | 安全係數 (1-15，預設 3.0) | ✓ 更新 |
| oxygen_cylinders_json | TEXT | 氧氣瓶詳情 JSON (見 1.1.1) | ✓ 新增 |
| equipment_battery_json | TEXT | 設備電量 JSON (見 1.1.2) | ✓ 新增 |
| emt_name | TEXT | EMT 姓名 | |
| confirmed_at | TIMESTAMP | 確認時間 | ✓ 新增 |
| departed_at | TIMESTAMP | 出發時間 | |
| arrived_at | TIMESTAMP | 抵達時間 | |
| finalized_at | TIMESTAMP | 結案時間 | ✓ 新增 |

#### 1.1.1 oxygen_cylinders_json 格式

每瓶氧氣獨立追蹤 PSI：

```json
[
  {
    "cylinder_id": "O2-E-001",
    "cylinder_type": "E",
    "capacity_liters": 660,
    "starting_psi": 2100,
    "ending_psi": null,
    "consumed_liters": null
  },
  {
    "cylinder_id": "O2-E-002",
    "cylinder_type": "E",
    "capacity_liters": 660,
    "starting_psi": 1800,
    "ending_psi": null,
    "consumed_liters": null
  }
]
```

**PSI → 升計算公式**:
```
consumed_liters = (starting_psi - ending_psi) / 2100 × capacity_liters
```

#### 1.1.2 equipment_battery_json 格式

記錄設備攜帶時電量：

```json
[
  {
    "equipment_id": "EQ-MONITOR-001",
    "equipment_name": "攜帶式監視器",
    "starting_battery_pct": 95,
    "ending_battery_pct": null
  },
  {
    "equipment_id": "EQ-VENT-001",
    "equipment_name": "呼吸器",
    "starting_battery_pct": 100,
    "ending_battery_pct": null
  }
]
```

### 1.2 transfer_items (三分離計量)

| 欄位 | 類型 | 說明 | 追蹤時機 |
|------|------|------|----------|
| id | INT PK | 自增 | |
| mission_id | TEXT FK | 任務 ID | |
| item_code | TEXT | 品項代碼 (FK → items/resources) | |
| item_type | TEXT | OXYGEN/IV_FLUID/MEDICATION/EQUIPMENT | |
| item_name | TEXT | 品項名稱 | |
| unit | TEXT | 單位 (瓶/袋/支/台) | |
| suggested_qty | REAL | 系統建議量 | PLANNING |
| **carried_qty** | REAL | 實際攜帶量 | READY (confirm) |
| **returned_qty** | REAL | 歸還量 | COMPLETED (finalize) |
| **consumed_qty** | REAL | 消耗量 (calculated) | COMPLETED |
| initial_status | TEXT | 攜帶時狀態 (PSI/電量%) | READY |
| final_status | TEXT | 返站時狀態 | COMPLETED |
| calculation_explain | TEXT | 計算說明 | |

**三分離原則**:
```
consumed_qty = carried_qty - returned_qty
```

- **carried_qty**: 確認任務時記錄，觸發 RESERVE 事件
- **returned_qty**: 結案時由 EMT 輸入
- **consumed_qty**: 自動計算，觸發 ops_log 消耗記錄

### 1.3 transfer_events (Append-Only)

| 欄位 | 類型 | 說明 |
|------|------|------|
| event_id | TEXT PK | UUID |
| mission_id | TEXT FK | 任務 ID |
| type | TEXT | CREATE/RESERVE/ISSUE/CONSUME/RETURN/INCOMING/ABORT |
| payload_json | TEXT | 事件內容 |
| occurred_at | TIMESTAMP | 發生時間 |
| synced | INT | 是否已同步 |

### 1.4 transfer_incoming_items

外帶物資入庫記錄。

### 1.5 consumption_rates

消耗率設定（預設值）：

| item_type | condition | rate | rate_unit |
|-----------|-----------|------|-----------|
| OXYGEN | INTUBATED | 10.0 | L/min |
| OXYGEN | MASK | 6.0 | L/min |
| OXYGEN | NASAL | 2.0 | L/min |
| IV_FLUID | TRAUMA | 500.0 | mL/30min |
| IV_FLUID | MAINTAIN | 100.0 | mL/hr |
| BATTERY | MONITOR | 10.0 | %/hr |
| BATTERY | VENTILATOR | 20.0 | %/hr |

---

## 2. 計算邏輯

### 2.1 公式

```
建議量 = 消耗率 × 預估時間 × 安全係數
```

### 2.2 氧氣計算

```python
liters_needed = lpm × 60 × duration_hr × safety_factor
e_tanks = ceil(liters_needed / 660)  # E-tank = 660L
```

### 2.3 輸液計算

```python
ml_needed = iv_rate × duration_hr × safety_factor
bags = ceil(ml_needed / 500)  # 500mL 袋
```

### 2.4 設備電量

```python
min_battery = battery_drain_per_hr × duration_hr × safety_factor
# 確保設備電量 ≥ min_battery%
```

---

## 3. API 端點

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/transfer/missions` | 任務列表 |
| POST | `/api/transfer/missions` | 建立任務 |
| GET | `/api/transfer/missions/{id}` | 任務詳情 |
| POST | `/api/transfer/missions/{id}/calculate` | 重算物資 |
| POST | `/api/transfer/missions/{id}/confirm` | 確認清單 (→READY) |
| POST | `/api/transfer/missions/{id}/confirm/v2` | v2.0 確認 (含 PSI/電量) |
| POST | `/api/transfer/missions/{id}/depart` | 出發 (→EN_ROUTE) |
| POST | `/api/transfer/missions/{id}/arrive` | 抵達 (→ARRIVED) |
| POST | `/api/transfer/missions/{id}/recheck` | 返站確認剩餘量 |
| POST | `/api/transfer/missions/{id}/incoming` | 登記外帶物資 |
| POST | `/api/transfer/missions/{id}/finalize` | 結案 (→COMPLETED) |
| POST | `/api/transfer/missions/{id}/finalize/v2` | v2.0 結案 (含 PSI/電量) |
| POST | `/api/transfer/missions/{id}/abort` | 中止 (→ABORTED) |
| GET | `/api/transfer/consumption-rates` | 消耗率設定 |
| GET | `/api/transfer/available-cylinders` | v2.1 可認領氧氣鋼瓶 |

---

## 4. 庫存連動規格 (v2.0 更新)

### 4.1 事件契約

| 動作 | 時機 | 事件類型 | 庫存影響 |
|------|------|----------|----------|
| **confirm** | PLANNING → READY | `TRANSFER_RESERVE` | `reserved_qty += carried_qty` |
| **depart** | READY → EN_ROUTE | `TRANSFER_ISSUE` | `on_hand -= carried_qty`, `reserved_qty -= carried_qty` |
| **finalize** | ARRIVED → COMPLETED | `TRANSFER_RETURN` | `on_hand += returned_qty` |
| **abort** | 任意 → ABORTED | `TRANSFER_CANCEL` | 撤銷所有未完成事件 |

### 4.2 事件流程詳情

```
1. PLANNING → READY (confirm)
   ├─ 發射 TRANSFER_RESERVE 事件 (per item)
   ├─ resources.reserved_qty += carried_qty
   ├─ 記錄 oxygen_cylinders_json 起始 PSI
   └─ 記錄 equipment_battery_json 起始電量%

2. READY → EN_ROUTE (depart)
   ├─ 發射 TRANSFER_ISSUE 事件
   ├─ resources.on_hand_qty -= carried_qty
   ├─ resources.reserved_qty -= carried_qty
   └─ equipment.status → 'IN_TRANSFER'

3. ARRIVED → COMPLETED (finalize)
   ├─ EMT 輸入各項 returned_qty
   ├─ EMT 輸入氧氣瓶 ending_psi
   ├─ EMT 輸入設備 ending_battery_pct
   ├─ 發射 TRANSFER_RETURN 事件
   ├─ resources.on_hand_qty += returned_qty
   ├─ consumed_qty = carried_qty - returned_qty
   ├─ 寫入 ops_log (CONSUME 記錄)
   └─ equipment.status → 'AVAILABLE'

4. ABORTED (任意狀態)
   ├─ 發射 TRANSFER_CANCEL 事件
   ├─ if status >= READY: resources.reserved_qty -= carried_qty
   └─ equipment.status → 'AVAILABLE'
```

### 4.3 庫存公式 (Invariant)

```
available = on_hand - reserved
```

**重要**: 韌性估算 **必須** 使用 `available`，**不可** 使用 `on_hand`。

因為 `on_hand` 不反映正在轉送中的物資，會導致韌性估算過度樂觀。

### 4.4 氧氣雙軌追蹤 (v2.0 改進)

| 層級 | 追蹤對象 | 單位 | v1.x | v2.0 |
|------|----------|------|------|------|
| 資產 | 鋼瓶 (cylinder) | 瓶 | ✓ | ✓ |
| 消耗 | 氣體 (gas) | L | 估算 | **PSI 實測** |

**v2.0 改進**: 不再只用瓶數估算，改為單瓶 PSI 追蹤：

```
鋼瓶類型容量參考:
- E-tank: 660L @ 2100 PSI
- D-tank: 350L @ 2100 PSI
- H-tank: 6900L @ 2200 PSI

計算公式:
consumed_liters = (starting_psi - ending_psi) / full_psi × capacity_liters
```

任務 loadout 記錄 (每瓶獨立):
- cylinder_id: 鋼瓶資產 ID
- cylinder_type: E/D/H
- starting_psi: 開始 PSI (confirm 時記錄)
- ending_psi: 結束 PSI (finalize 時輸入)
- consumed_liters: 自動計算消耗量

---

## 5. 配對機制

### 5.1 裝置類別

```json
{
  "deviceClass": "EMT_TRANSFER",
  "allowedScopes": ["TRANSFER_*", "RESOURCE_RESERVE", "RESOURCE_ISSUE", "RESOURCE_RETURN"],
  "forbiddenScopes": ["ADMIN_*", "CONTROLLED_DRUG_*", "INVENTORY_EDIT"]
}
```

### 5.2 離線 Grace Window

- 預設: 14 天
- 戰時: 30 天
- 過期後需重新配對

---

## 6. UI 規格 (v2.0)

### 6.0 iOS Safari 相容性 (v2.2 新增)

**問題**: iOS Safari 對 `overflow-y: auto` + `max-height: 90vh` 的 Modal 不支援觸控滾動。

**解決方案**: 採用全螢幕頁面式 Modal：

```html
<!-- 全螢幕 Modal 模式 -->
<div class="fixed inset-0 bg-white z-50 overflow-y-auto ios-scroll">
    <!-- Sticky Header -->
    <div class="sticky top-0 bg-amber-500 text-white px-4 py-3 shadow-lg z-10">
        <button @click="closeModal">✕</button>
        <h2>標題</h2>
    </div>
    <!-- 內容自然滾動 -->
    <div class="p-4 pb-24">
        <!-- Modal 內容 -->
    </div>
</div>
```

```css
.ios-scroll {
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
}
```

**關鍵**:
- 移除 `max-h-[90vh]` 限制
- 使用 `fixed inset-0` 全覆蓋
- Header 使用 `sticky top-0`
- 內容區域自然頁面滾動

### 6.1 入口

**位置**: MIRS Index.html Header 按鈕 (橘色閃電圖示) → 開啟 `/emt` PWA

### 6.2 建立任務畫面 (v2.0 改進)

採用「預設值快捷按鈕 + 自訂數字輸入」模式：

#### ETA 預估時間

| 快捷鈕 | 分鐘 |
|--------|------|
| 30 min | 30 |
| 1 hr | 60 |
| 2 hr | 120 |
| 自訂 | [數字輸入框] |

#### 氧氣需求 (L/min)

| 快捷鈕 | L/min | 適用情境 |
|--------|-------|----------|
| 2 | 2 | 鼻導管 |
| 6 | 6 | 面罩 |
| 10 | 10 | 插管/呼吸器 |
| 自訂 | [數字輸入框] | |

#### 輸液模式

| 選項 | 速率 | 說明 |
|------|------|------|
| 無 (NONE) | 0 mL/hr | 不需輸液 |
| KVO | 30 mL/hr | Keep Vein Open |
| BOLUS | 500 mL/30min | 快速補液 |
| 自訂 (CUSTOM) | [數字輸入框] mL/hr | |

#### 安全係數

滑桿或數字輸入，範圍 **1-15**，預設 **3**：

```
安全係數: [----●---------] 3×
         1              15
```

### 6.3 攜帶確認畫面 (v2.0 新增)

確認任務時，對每項物資記錄：

**消耗品**:
- 攜帶數量 (carried_qty)

**氧氣瓶** (每瓶獨立):
- 選擇鋼瓶 (從 equipment 選擇)
- 記錄起始 PSI

**設備**:
- 選擇設備 (從 equipment 選擇)
- 記錄起始電量 %

### 6.4 藥物/耗材區塊 (v2.2 更新)

Step 2 整備畫面新增獨立區塊，採用 **紫紅色系** (`dispense-purple`)：

```
┌─────────────────────────────────────┐
│ 藥物/耗材 (紫紅色)          + 新增項目 │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ Epinephrine 1mg        ☑ 已確認 │ │
│ │ 數量: [2] 支                    │ │
│ └─────────────────────────────────┘ │
│                                     │
│ 快捷: [Epi] [Atropine] [Morphine]  │
│       [Ketamine] [TXA] [止血帶]     │
└─────────────────────────────────────┘
```

**快捷按鈕預設值**:

| 快捷鈕 | 藥物名稱 | 預設數量 | 單位 |
|--------|----------|----------|------|
| Epi | Epinephrine 1mg | 2 | 支 |
| Atropine | Atropine 0.5mg | 2 | 支 |
| Morphine | Morphine 10mg | 1 | 支 |
| Ketamine | Ketamine 500mg | 1 | 瓶 |
| TXA | TXA 1g | 2 | 支 |
| 止血帶 | 止血帶 | 2 | 條 |
| 胸封貼 | 胸腔封閉貼 | 1 | 片 |

### 6.5 氧氣鋼瓶認領+手動 (v2.1 新增)

氧氣鋼瓶區塊採用 Tab 切換模式：

```
┌─────────────────────────────────────┐
│ 氧氣鋼瓶                  2 已認領  │
├─────────────────────────────────────┤
│  [ 認領 (庫存) ]  [ 手動輸入 ]      │
├─────────────────────────────────────┤
│ 從庫存認領的鋼瓶會影響韌性估算      │
│                                     │
│ ┌──────────────────────────┐        │
│ │ E-001 (E) 2100 PSI (100%)│[認領]  │
│ └──────────────────────────┘        │
│ ┌──────────────────────────┐        │
│ │ E-002 (E) 1785 PSI (85%) │[已認領]│
│ └──────────────────────────┘        │
├─────────────────────────────────────┤
│ 已選鋼瓶 (2)                        │
│ ┌──────────────────────────┐        │
│ │ [庫存] E-001 (E)         │ [x]    │
│ │ 起始 PSI: [2100] / 2100  │        │
│ │ 可用: 660 L              │        │
│ │ ☑ 已確認                 │        │
│ └──────────────────────────┘        │
│ ┌──────────────────────────┐        │
│ │ [手動] E [___] 編號      │ [x]    │
│ │ 起始 PSI: [2100] / 2100  │        │
│ │ 可用: 660 L              │        │
│ │ ☐ 已確認                 │        │
│ └──────────────────────────┘        │
└─────────────────────────────────────┘
```

**認領 vs 手動 差異**:

| 模式 | cylinder_id | 韌性影響 | PSI 來源 | 可編輯 |
|------|-------------|----------|----------|--------|
| 認領 | equipment_unit.id | ✓ 會影響 | 自動帶入 | 唯讀 |
| 手動 | null | ✗ 不影響 | 手動輸入 | 可編輯 |

### 6.6 結案畫面 (v2.0 改進)

EMT 輸入返站後各項剩餘：

**消耗品**:
- 歸還數量 (returned_qty)
- 系統自動計算消耗量

**氧氣瓶** (每瓶):
- 輸入結束 PSI
- 系統自動計算消耗升數

**設備**:
- 輸入結束電量 %

### 6.5 韌性估算整合

韌性估算 Tab 顯示摘要連結：
> "影響 O2 runway 的轉送任務: X 筆" → 點擊跳轉

**重要**: 韌性計算必須使用 `available = on_hand - reserved`

---

## 7. 檔案清單

| 檔案 | 說明 |
|------|------|
| `database/migrations/add_transfer_module.sql` | Schema |
| `routes/transfer.py` | API Router |
| `static/emt/index.html` | PWA 主頁 |
| `static/emt/manifest.json` | PWA Manifest |
| `static/emt/sw.js` | Service Worker |

---

## 8. 實作進度

### v1.x (已完成)

| Phase | 內容 | 狀態 |
|-------|------|------|
| 1.1 | Schema + API + PWA 骨架 | ✅ 完成 |
| 1.2 | 基本 UI (建立/出發/抵達/結案) | ✅ 完成 |
| 1.3 | 任務狀態機 | ✅ 完成 |

### v2.0 (已完成 2026-01-04)

| Phase | 內容 | 狀態 |
|-------|------|------|
| 2.1 | Schema 升級 (PSI/電量欄位) | ✅ 完成 |
| 2.2 | 庫存連動 (Reserve/Issue/Return) | ✅ 完成 |
| 2.3 | UI 改進 (預設值快捷 + PSI 輸入) | ✅ 完成 |
| 2.4 | 三分離計量 (攜帶/歸還/消耗) | ✅ 完成 |
| 2.5 | 韌性整合 (使用 available) | ✅ 完成 |

#### v2.0 實作細節

- **2.1 Schema**: `database/migrations/transfer_v2_upgrade.sql`
  - 新增 `transfer_oxygen_cylinders` 表 (單瓶 PSI 追蹤)
  - 新增 `transfer_equipment_battery` 表 (設備電量追蹤)
  - 新增 `oxygen_cylinder_types` 參考表 (E/D/M/H-Tank 容量)
  - 新增 `iv_mode_presets` 參考表 (NONE/KVO/BOLUS/MAINTENANCE/CUSTOM)

- **2.2 庫存連動**: `routes/transfer.py` v2.0.0
  - `reserve_cylinders_v2()`: 記錄起始 PSI
  - `reserve_equipment_v2()`: 記錄起始電量
  - `finalize_cylinders_v2()`: 記錄結束 PSI，計算消耗公升數
  - `finalize_equipment_v2()`: 記錄結束電量，計算消耗百分比
  - API 端點: `/confirm/v2`, `/finalize/v2`

- **2.3 UI**: `static/emt/index.html`
  - IV 模式快捷選項 (NONE/KVO/MAINTENANCE/BOLUS/CUSTOM)
  - O2 LPM 擴充 (0/2/4/6/10/15)
  - ETA 單程時間欄位
  - 氧氣鋼瓶 PSI 輸入 (支援多鋼瓶)
  - 設備電量追蹤 (監視器/呼吸器/抽吸機)
  - 結束 PSI/電量輸入 + 消耗可視化

- **2.4 三分離**: 後端已實作 `consumed_qty = carried_qty - returned_qty`

- **2.5 韌性整合**: `services/resilience_service.py`
  - 排除 `claimed_by_mission_id IS NOT NULL` 的設備
  - 排除 `claimed_by_case_id IS NOT NULL` 的設備

### v2.1 (已完成 2026-01-04)

| Phase | 內容 | 狀態 |
|-------|------|------|
| 2.6 | 藥物/耗材手動增減 | ✅ 完成 |
| 2.7 | 氧氣鋼瓶認領+手動雙軌模式 | ✅ 完成 |
| 2.8 | 可認領鋼瓶 API (`/available-cylinders`) | ✅ 完成 |

#### v2.1 實作細節

- **2.6 藥物/耗材手動增減**: `static/emt/index.html`
  - Step 2 新增「藥物/耗材」區塊 (紫紅色系 `dispense-purple`)
  - 快捷按鈕: Epinephrine, Atropine, Morphine, Ketamine, TXA, 止血帶, 胸封貼
  - 可自訂藥物名稱、數量、單位
  - `customMedications[]` 陣列，合併至 `confirmLoadoutV2()` 送出

- **2.7 氧氣鋼瓶認領+手動雙軌**: `static/emt/index.html`
  - Tab 切換: 「認領 (庫存)」vs「手動輸入」
  - **認領模式**: 從庫存選擇可用鋼瓶，帶入 PSI 資訊
    - 認領的鋼瓶會影響韌性估算 (`claimed_by_mission_id`)
    - 帶有 `cylinder_id` 連結 equipment_units
  - **手動模式**: 直接輸入鋼瓶類型/編號/PSI
    - 不影響韌性估算 (無庫存連結)
  - 區分標籤: 「庫存」(藍底) / 「手動」(灰底)

- **2.8 可認領鋼瓶 API**: `routes/transfer.py`
  ```
  GET /api/transfer/available-cylinders
  ```
  回傳格式:
  ```json
  {
    "cylinders": [
      {
        "id": "equipment_unit_id",
        "unit_label": "E-001",
        "cylinder_type": "E",
        "level_percent": 100,
        "estimated_psi": 2100
      }
    ]
  }
  ```
  篩選條件:
  - `equipment.name LIKE '%氧氣%' OR '%O2%' OR '%E-Tank%'`
  - `status IN ('OK', 'CHECKED', 'UNCHECKED')`
  - `is_active = 1`
  - `claimed_by_case_id IS NULL`
  - `claimed_by_mission_id IS NULL`

### v3.0 (未來)

| Phase | 內容 | 狀態 |
|-------|------|------|
| 3.1 | 配對機制 (EMT_TRANSFER 裝置類別) | ⏳ 待開發 |
| 3.2 | 離線同步 (IndexedDB + Background Sync) | ⏳ 待開發 |
| 3.3 | 多站點同步 | ⏳ 待開發 |

---

## 9. 測試案例 (v2.0)

### 9.1 建立任務

```bash
curl -X POST http://localhost:8000/api/transfer/missions \
  -H "Content-Type: application/json" \
  -d '{
    "destination_text": "第二野戰醫院",
    "eta_min": 90,
    "patient_condition": "STABLE",
    "o2_lpm": 6,
    "iv_mode": "KVO",
    "safety_factor": 3
  }'
```

預期結果：
- 氧氣: 6 L/min × 90 min × 3 = 1620L → 3 瓶 E-tank
- 輸液: 30 mL/hr × 1.5 hr × 3 = 135mL → 1 袋

### 9.2 確認攜帶 (v2.0 含 PSI)

```bash
curl -X POST http://localhost:8000/api/transfer/missions/TRF-20260103-001/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"item_code": "NS-500", "carried_qty": 1}
    ],
    "oxygen_cylinders": [
      {"cylinder_id": "O2-E-001", "cylinder_type": "E", "starting_psi": 2100},
      {"cylinder_id": "O2-E-002", "cylinder_type": "E", "starting_psi": 1800}
    ],
    "equipment": [
      {"equipment_id": "EQ-MONITOR-001", "starting_battery_pct": 95}
    ]
  }'
```

### 9.3 結案 (v2.0 含 PSI 結束值)

```bash
curl -X POST http://localhost:8000/api/transfer/missions/TRF-20260103-001/finalize \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"item_code": "NS-500", "returned_qty": 0}
    ],
    "oxygen_cylinders": [
      {"cylinder_id": "O2-E-001", "ending_psi": 1200},
      {"cylinder_id": "O2-E-002", "ending_psi": 1500}
    ],
    "equipment": [
      {"equipment_id": "EQ-MONITOR-001", "ending_battery_pct": 70}
    ]
  }'
```

預期計算：
- 鋼瓶 1: (2100-1200)/2100 × 660 = 283L 消耗
- 鋼瓶 2: (1800-1500)/2100 × 660 = 94L 消耗
- 監視器: 95% - 70% = 25% 電量消耗

---

## 10. 參考資料

- ChatGPT 架構建議 (2026-01-03)
- Gemini Event Sourcing 建議
- MIRS Anesthesia Module 實作模式
- EMT 實地測試回饋 (2026-01-03)

---

## 11. 變更記錄

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| 1.0.0 | 2026-01-02 | 初版規格 |
| 1.1.0 | 2026-01-03 | Phase 1 完成，新增狀態機 |
| 2.0.0 | 2026-01-03 | 規格更新：安全係數可調、PSI 追蹤、三分離計量 |
| 2.0.0 | 2026-01-04 | Phase 2 完成：Schema 升級、庫存連動、UI 改進、三分離計量、韌性整合 |
| **2.1.0** | **2026-01-04** | **Phase 2.1 完成**：<br>- 2.6 藥物/耗材手動增減 (快捷按鈕 + 自訂)<br>- 2.7 氧氣鋼瓶認領+手動雙軌模式<br>- 2.8 可認領鋼瓶 API (`/available-cylinders`) |
| **2.2.0** | **2026-01-04** | **UI/UX 改進**：<br>- **iOS Safari 滾動修復**: 全螢幕頁面式 Modal (移除 `max-h-[90vh]`)<br>- **MIRS 配色統一**: 藥物/耗材→紫紅色、氧氣→amber、設備→equipment 色系<br>- 新增 sticky header 支援觸控滾動 |
