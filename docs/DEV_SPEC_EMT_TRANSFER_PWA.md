# EMT Transfer PWA 開發規格書

**版本**: 1.1.0
**日期**: 2026-01-03
**狀態**: Phase 1 完成, Phase 2 進行中

---

## 0. 摘要

EMT Transfer PWA 是 MIRS 的病患轉送任務管理模組，專為救護技術員 (EMT) 設計。主要功能包括：

- 物資需求計算（氧氣、輸液、設備電量）
- 安全係數 ×3 備量
- 離線優先架構
- 庫存連動（Reserve → Issue → Return）
- 外帶物資入庫

---

## 0.1 設計原則

| 原則 | 說明 |
|------|------|
| **離線優先** | IndexedDB 本地儲存，背景同步 |
| **Event Sourcing** | Append-only event log，可重建狀態 |
| **安全係數** | 預設 3×，確保緊急狀況有備量 |
| **庫存連動** | Reserve/Issue/Return 事件連動主庫存 |

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

## 0.3 UI 配色

採用 Amber 色系（同韌性估算 Tab）：

| 用途 | Tailwind Class | HEX |
|------|----------------|-----|
| 主色 | `amber-500` | `#f59e0b` |
| 深色 | `amber-600` | `#d97706` |
| 淺色 | `amber-100` | `#fef3c7` |
| 背景 | `amber-50` | `#fffbeb` |

---

## 1. 資料庫 Schema

### 1.1 transfer_missions

| 欄位 | 類型 | 說明 |
|------|------|------|
| mission_id | TEXT PK | TRF-YYYYMMDD-NNN |
| status | TEXT | PLANNING/READY/EN_ROUTE/ARRIVED/COMPLETED/ABORTED |
| origin_station | TEXT | 出發站點 |
| destination | TEXT | 目的地 |
| estimated_duration_min | INT | 預估時間（分鐘） |
| actual_duration_min | INT | 實際時間 |
| oxygen_requirement_lpm | REAL | 氧氣需求 L/min |
| iv_rate_mlhr | REAL | 輸液速率 mL/hr |
| ventilator_required | INT | 是否需呼吸器 |
| safety_factor | REAL | 安全係數（預設 3.0） |
| patient_condition | TEXT | CRITICAL/STABLE/INTUBATED |
| emt_name | TEXT | EMT 姓名 |

### 1.2 transfer_items

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INT PK | 自增 |
| mission_id | TEXT FK | 任務 ID |
| item_type | TEXT | OXYGEN/IV_FLUID/MEDICATION/EQUIPMENT |
| item_name | TEXT | 品項名稱 |
| suggested_qty | REAL | 系統建議量 |
| carried_qty | REAL | 實際攜帶量 |
| returned_qty | REAL | 歸還量 |
| consumed_qty | REAL | 消耗量 |
| calculation_explain | TEXT | 計算說明 |

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
| POST | `/api/transfer/missions/{id}/depart` | 出發 (→EN_ROUTE) |
| POST | `/api/transfer/missions/{id}/arrive` | 抵達 (→ARRIVED) |
| POST | `/api/transfer/missions/{id}/recheck` | 返站確認剩餘量 |
| POST | `/api/transfer/missions/{id}/incoming` | 登記外帶物資 |
| POST | `/api/transfer/missions/{id}/finalize` | 結案 (→COMPLETED) |
| POST | `/api/transfer/missions/{id}/abort` | 中止 (→ABORTED) |
| GET | `/api/transfer/consumption-rates` | 消耗率設定 |

---

## 4. 庫存連動規格

### 4.1 事件流程

```
1. PLANNING → READY (confirm)
   └─ 發射 RESERVE 事件
   └─ resources.reserved_qty += carried_qty
   └─ 韌性計算使用 available = on_hand - reserved

2. READY → EN_ROUTE (depart)
   └─ 發射 ISSUE 事件
   └─ resources.on_hand_qty -= carried_qty
   └─ resources.reserved_qty -= carried_qty
   └─ 設備狀態 → IN_TRANSFER

3. EN_ROUTE → ARRIVED → COMPLETED (finalize)
   └─ 發射 RETURN 事件
   └─ resources.on_hand_qty += returned_qty
   └─ consumed_qty = carried_qty - returned_qty
   └─ 設備狀態 → AVAILABLE

4. ABORTED (any state)
   └─ 發射 CANCEL_RESERVE 事件
   └─ resources.reserved_qty -= carried_qty (if was reserved)
```

### 4.2 Invariant

```
available = on_hand - reserved - issued_out
```

韌性估算必須使用 `available`，而非 `on_hand`。

### 4.3 氧氣雙軌追蹤

| 層級 | 追蹤對象 | 單位 |
|------|----------|------|
| 資產 | 鋼瓶 (cylinder) | 瓶 |
| 消耗 | 氣體 (gas) | L 或 PSI |

任務 loadout 記錄：
- cylinder_type: E/D/H
- starting_psi: 開始 PSI
- ending_psi: 結束 PSI (finalize 時輸入)
- consumed_liters: 計算消耗量

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

## 6. UI 入口

**建議位置**: MIRS 主頁獨立模組，非韌性估算 Tab 內。

```
MIRS 主頁
├── 庫存總覽
├── 藥品管理
├── 設備管理
├── 韌性估算
├── Transfer (EMT)  ← 新增
│   ├── 建立任務
│   ├── 進行中任務
│   └── 歷史記錄
└── ...
```

韌性估算 Tab 只顯示摘要連結：
> "影響 O2 runway 的轉送任務: X 筆" → 點擊跳轉

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

| Phase | 內容 | 狀態 |
|-------|------|------|
| 1 | Schema + API + PWA 骨架 | ✅ 完成 |
| 2 | 庫存連動 (Reserve/Issue/Return) | 🔄 進行中 |
| 3 | 配對機制 | ⏳ 待開發 |
| 4 | 離線同步 (IndexedDB + Background Sync) | ⏳ 待開發 |

---

## 9. 測試案例

### 9.1 建立任務

```bash
curl -X POST http://localhost:8000/api/transfer/missions \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "第二野戰醫院",
    "estimated_duration_min": 90,
    "oxygen_requirement_lpm": 6,
    "iv_rate_mlhr": 100,
    "safety_factor": 3.0
  }'
```

預期結果：
- 氧氣: 6 × 60 × 1.5 × 3 = 1620L → 3 瓶 E-tank
- 輸液: 100 × 1.5 × 3 = 450mL → 1 袋

### 9.2 確認清單

```bash
curl -X POST http://localhost:8000/api/transfer/missions/TRF-20260103-001/confirm \
  -H "Content-Type: application/json" \
  -d '[{"item_id": 1, "carried_qty": 3, "initial_status": "PSI: 2100"}]'
```

---

## 10. 參考資料

- ChatGPT 架構建議 (2026-01-03)
- Gemini Event Sourcing 建議
- MIRS Anesthesia Module 實作模式
