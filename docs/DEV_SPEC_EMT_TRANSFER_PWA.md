# EMT Transfer PWA 開發規格書

**版本**: v1.0
**日期**: 2026-01-03
**狀態**: 規格定稿
**整合來源**: Claude + ChatGPT + Gemini

---

## 0. 架構決策 (Architecture Decision)

### 0.1 定位：MIRS 內建模組

```
┌─────────────────────────────────────────────────────────────┐
│  EMT Transfer = MIRS 子模組，非獨立產品                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  理由：                                                      │
│  • 終局動作是「庫存真相更新」→ system-of-record 必須是 MIRS  │
│  • 共用 RPi Backend + SQLite                                │
│  • 共用設備/藥品主檔                                         │
│                                                             │
│  部署：                                                      │
│  • RPi/MIRS 提供 /static/emt/ + /api/transfer/*             │
│  • Vercel 僅為 demo/training mirror，非庫存真相來源          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 0.2 檔案結構

```
MIRS-v2.0-single-station/
├── static/emt/
│   ├── index.html          # EMT Transfer PWA
│   ├── sw.js               # Service Worker (離線)
│   └── manifest.json       # PWA Manifest
├── routes/
│   └── transfer.py         # Transfer API Router
└── database/migrations/
    └── add_transfer_module.sql
```

---

## 1. 概述

### 1.1 目標
供 EMT 使用的離線優先 PWA，用於病患轉送任務的物資規劃、攜帶確認、途中追蹤、返站結案。

### 1.2 核心流程 (State Machine)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ PLANNING │───►│  READY   │───►│ EN_ROUTE │───►│ ARRIVED  │───►│COMPLETED │
│          │    │          │    │          │    │          │    │          │
│ 建立任務 │    │ 確認攜帶 │    │ 途中追蹤 │    │ Recheck  │    │ 結案歸檔 │
│ 計算物資 │    │ 扣庫存   │    │ (離線)   │    │ 外帶入庫 │    │ 回寫庫存 │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                     │                               │
                     ▼                               ▼
              ┌──────────┐                    ┌──────────┐
              │ ABORTED  │                    │ ABORTED  │
              └──────────┘                    └──────────┘
```

### 1.3 設計原則

| 原則 | 說明 |
|------|------|
| **離線優先** | Local-First，所有操作先寫 IndexedDB + Outbox |
| **Event Sourcing** | 庫存不可「編輯」，只能由事件推導 (Reserve/Issue/Return/Consume/Incoming) |
| **3× 安全係數** | 預設攜帶 3 倍計算量 |
| **確認優先於新增** | 預設操作是「確認建議清單」，手動新增是例外 |

---

## 2. 資料模型

### 2.1 Transfer Mission（轉送任務）

```sql
CREATE TABLE transfer_missions (
    mission_id TEXT PRIMARY KEY,           -- TRF-20260103-001

    -- 狀態機
    status TEXT DEFAULT 'PLANNING',        -- PLANNING, READY, EN_ROUTE, ARRIVED, COMPLETED, ABORTED

    -- 時間戳記
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ready_at TIMESTAMP,                    -- 確認攜帶時間
    departed_at TIMESTAMP,                 -- 出發時間
    arrived_at TIMESTAMP,                  -- 抵達時間
    finalized_at TIMESTAMP,                -- 結案時間

    -- 路程資訊
    origin_station TEXT NOT NULL,          -- 出發站點 (MIRS station_id)
    destination TEXT NOT NULL,             -- 目的地
    estimated_duration_min INTEGER NOT NULL, -- 預估時間（分鐘）
    actual_duration_min INTEGER,           -- 實際時間
    transport_mode TEXT DEFAULT 'GROUND',  -- GROUND, AIR, BOAT

    -- 病患資訊
    patient_id TEXT,                       -- 連結 CIRS 病患（可選）
    patient_condition TEXT,                -- CRITICAL, STABLE, INTUBATED
    patient_summary TEXT,                  -- 病況摘要

    -- 計算參數
    oxygen_requirement_lpm REAL DEFAULT 0, -- 氧氣需求 (L/min)
    iv_rate_mlhr REAL DEFAULT 0,           -- 輸液速度 (mL/hr)
    ventilator_required INTEGER DEFAULT 0, -- 是否需要呼吸器
    safety_factor REAL DEFAULT 3.0,        -- 安全係數

    -- 人員
    emt_id TEXT,                           -- 負責 EMT
    emt_name TEXT,
    device_id TEXT,                        -- 建立任務的裝置 ID

    notes TEXT
);
```

### 2.2 Transfer Items（轉送物資清單）

```sql
CREATE TABLE transfer_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,

    -- 物資資訊
    item_type TEXT NOT NULL,               -- OXYGEN, IV_FLUID, MEDICATION, EQUIPMENT, CONSUMABLE
    item_code TEXT,                        -- 連結 MIRS 庫存 ID（可選）
    item_name TEXT NOT NULL,
    unit TEXT DEFAULT '個',

    -- 數量邏輯 (三階段)
    suggested_qty REAL,                    -- 系統計算建議量 (3×)
    carried_qty REAL,                      -- EMT 確認攜帶量 (扣庫基準)
    returned_qty REAL,                     -- 結案時帶回量
    consumed_qty REAL,                     -- 計算欄位: carried - returned

    -- 狀態追蹤
    initial_status TEXT,                   -- 出發時狀態 (如 "PSI: 2100")
    final_status TEXT,                     -- 返回時狀態 (如 "PSI: 500")

    -- 計算說明 (可稽核)
    calculation_explain TEXT,              -- "2 L/min × 2hr × 3 = 720L → 2瓶"

    -- Checklist
    checked INTEGER DEFAULT 0,
    checked_at TIMESTAMP,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);
```

### 2.3 Transfer Events（事件日誌 - Append-Only）

**關鍵表：解決離線同步 + 庫存互鎖 + 雙重扣除預防**

```sql
CREATE TABLE transfer_events (
    event_id TEXT PRIMARY KEY,             -- UUID
    mission_id TEXT NOT NULL,

    -- 事件類型
    type TEXT NOT NULL,
    -- CREATE      : 任務建立
    -- RESERVE     : 庫存預留 (READY)
    -- ISSUE       : 庫存扣除 (EN_ROUTE)
    -- CONSUME     : 途中消耗記錄
    -- RETURN      : 結案歸還
    -- INCOMING    : 外站物資入庫
    -- ADJUST      : 手動調整
    -- ABORT       : 任務中止

    -- 事件內容
    payload_json TEXT,                     -- 事件詳細資料 (JSON)

    -- 時間與來源
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id TEXT,                        -- 產生事件的裝置
    actor_id TEXT,                         -- 操作者

    -- 同步狀態
    synced INTEGER DEFAULT 0,              -- 是否已同步到 Server
    synced_at TIMESTAMP,
    server_seq INTEGER,                    -- Server 端序號 (monotonic)

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);

-- 索引
CREATE INDEX idx_transfer_events_mission ON transfer_events(mission_id);
CREATE INDEX idx_transfer_events_synced ON transfer_events(synced);
```

### 2.4 Transfer Incoming Items（外帶物資）

```sql
CREATE TABLE transfer_incoming_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,

    -- 物資資訊
    item_type TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT DEFAULT '個',

    -- 來源追蹤
    source_station TEXT,                   -- 來源站點
    source_notes TEXT,

    -- 狀態資訊
    condition TEXT DEFAULT 'GOOD',         -- GOOD, DAMAGED, EXPIRED
    oxygen_psi INTEGER,
    battery_percent INTEGER,
    lot_number TEXT,
    expiry_date TEXT,

    -- 入庫處理
    processed INTEGER DEFAULT 0,
    processed_at TIMESTAMP,
    inventory_id TEXT,                     -- 入庫後的 MIRS 庫存 ID

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);
```

### 2.5 Consumption Rates（消耗率設定）

```sql
CREATE TABLE consumption_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    condition TEXT,                        -- 病患狀況 (INTUBATED, MASK, STABLE)
    rate REAL NOT NULL,
    rate_unit TEXT NOT NULL,               -- 'L/min', 'mL/hr', '%/hr'
    notes TEXT
);

-- 預設資料
INSERT INTO consumption_rates (item_type, condition, rate, rate_unit, notes) VALUES
('OXYGEN', 'INTUBATED', 10.0, 'L/min', '插管病患'),
('OXYGEN', 'MASK', 6.0, 'L/min', '面罩給氧'),
('OXYGEN', 'NASAL', 2.0, 'L/min', '鼻導管'),
('IV_FLUID', 'TRAUMA', 500.0, 'mL/30min', '創傷輸液'),
('IV_FLUID', 'MAINTAIN', 100.0, 'mL/hr', '維持輸液'),
('IV_FLUID', 'KVO', 30.0, 'mL/hr', 'Keep Vein Open'),
('BATTERY', 'MONITOR', 10.0, '%/hr', '監視器'),
('BATTERY', 'VENTILATOR', 20.0, '%/hr', '呼吸器'),
('BATTERY', 'SUCTION', 15.0, '%/hr', '抽吸器');
```

---

## 3. 庫存連動規則 (Inventory Interlock)

### 3.1 三段式結算

```
┌─────────────────────────────────────────────────────────────┐
│  庫存狀態轉移                                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐    │
│  │ Available│──RESERVE──►│ Reserved │──ISSUE───►│  Issued  │    │
│  │ (可用)   │         │ (預留)   │         │ (已發出) │    │
│  └──────────┘         └──────────┘         └──────────┘    │
│       ▲                                          │         │
│       │                                          │         │
│       │              ┌───────────────────────────┘         │
│       │              │                                     │
│       │         ┌────┴────┐                                │
│       │         │ FINALIZE │                               │
│       │         └────┬────┘                                │
│       │              │                                     │
│       │    ┌─────────┼─────────┐                          │
│       │    ▼         ▼         ▼                          │
│       │ RETURN   CONSUME   INCOMING                       │
│       │ (歸還)   (消耗)    (入庫)                          │
│       │    │         │         │                          │
│       └────┘         ▼         ▼                          │
│                  (扣除)    (新增)                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 事件與庫存對應

| 狀態轉移 | 事件類型 | 庫存動作 | 說明 |
|----------|----------|----------|------|
| PLANNING → READY | `RESERVE` | Available → Reserved | 預留，不扣 on-hand |
| READY → EN_ROUTE | `ISSUE` | Reserved → Issued | 正式扣除庫存 |
| EN_ROUTE (途中) | `CONSUME` | 記錄消耗 | 僅記錄，不改庫存 |
| ARRIVED → COMPLETED | `RETURN` | Issued → Available | 剩餘歸還 |
| ARRIVED → COMPLETED | `CONSUME` | Issued → (消耗) | 確認消耗量 |
| ARRIVED → COMPLETED | `INCOMING` | → Available | 外站物資入庫 |

### 3.3 關鍵規則

```python
# 庫存不可用「編輯」修改，只能由事件推導
# 所有庫存變動必須產生 ops_log 記錄

def process_finalize(mission_id):
    """
    結案時的庫存處理 (唯一寫庫存的交易邊界)
    """
    items = get_transfer_items(mission_id)

    for item in items:
        consumed = item.carried_qty - item.returned_qty

        if item.returned_qty > 0:
            # 歸還
            emit_event('RETURN', item, item.returned_qty)
            inventory.return_item(item.item_code, item.returned_qty)

        if consumed > 0:
            # 消耗
            emit_event('CONSUME', item, consumed)
            # 已在 ISSUE 時扣除，此處只記錄

    # 處理外帶入庫
    incoming = get_incoming_items(mission_id)
    for item in incoming:
        emit_event('INCOMING', item, item.quantity)
        inventory.add_item(item, source='TRANSFER_INCOMING')
```

---

## 4. 計算引擎

### 4.1 核心公式

```
建議量 = 消耗率 × 預估時間 × 安全係數
```

### 4.2 計算範例

```python
def calculate_supplies(mission) -> List[SupplySuggestion]:
    """
    計算轉送任務所需物資
    輸出必須包含 calculation_explain 供稽核
    """
    duration_hr = mission.estimated_duration_min / 60
    safety = mission.safety_factor  # 預設 3.0

    supplies = []

    # 1. 氧氣計算
    if mission.oxygen_requirement_lpm > 0:
        lpm = mission.oxygen_requirement_lpm
        liters_needed = lpm * 60 * duration_hr * safety

        # E-tank: 660L, D-tank: 350L
        e_tanks = math.ceil(liters_needed / 660)

        supplies.append({
            'item_type': 'OXYGEN',
            'item_name': 'E-Tank 氧氣鋼瓶',
            'suggested_qty': e_tanks,
            'unit': '瓶',
            'calculation_explain': f'{lpm} L/min × {duration_hr:.1f}hr × {safety} = {liters_needed:.0f}L → {e_tanks}瓶',
            'assumptions': {
                'rate': f'{lpm} L/min',
                'duration': f'{duration_hr:.1f} hr',
                'safety_factor': safety,
                'tank_capacity': '660L (E-Tank)'
            }
        })

    # 2. 輸液計算
    if mission.iv_rate_mlhr > 0:
        rate = mission.iv_rate_mlhr
        ml_needed = rate * duration_hr * safety
        bags = math.ceil(ml_needed / 500)  # 500mL 袋

        supplies.append({
            'item_type': 'IV_FLUID',
            'item_name': 'NS 500mL',
            'suggested_qty': bags,
            'unit': '袋',
            'calculation_explain': f'{rate} mL/hr × {duration_hr:.1f}hr × {safety} = {ml_needed:.0f}mL → {bags}袋'
        })

    # 3. 設備電量門檻
    battery_drain = 10  # %/hr (監視器)
    min_battery = min(100, battery_drain * duration_hr * safety)

    supplies.append({
        'item_type': 'EQUIPMENT',
        'item_name': '生理監視器',
        'min_battery_percent': min_battery,
        'calculation_explain': f'{battery_drain}%/hr × {duration_hr:.1f}hr × {safety} = {min_battery:.0f}%'
    })

    return supplies
```

### 4.3 氧氣鋼瓶參考

| 規格 | 容量 (L) | PSI 係數 | 重量 (kg) |
|------|----------|----------|-----------|
| E-Tank | 660 | 0.28 | 8 |
| D-Tank | 350 | 0.16 | 5 |
| C-Tank | 240 | 0.10 | 4 |

**剩餘時間計算：**
```
可用時間 (min) = (剩餘 PSI × 容量係數) / 流量 (L/min)
```

---

## 5. 離線同步 (Offline-First)

### 5.1 Outbox Pattern

```
┌─────────────────────────────────────────────────────────────┐
│  離線同步架構                                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐                    ┌─────────────┐        │
│  │ EMT Device  │                    │ MIRS Server │        │
│  │ (IndexedDB) │                    │ (SQLite)    │        │
│  └──────┬──────┘                    └──────┬──────┘        │
│         │                                  │               │
│         │  1. 操作產生 Event               │               │
│         │     └─► 寫入 Local outbox        │               │
│         │                                  │               │
│         │  2. 網路恢復                     │               │
│         │     POST /api/transfer/sync ────►│               │
│         │     (unsent events)              │               │
│         │                                  │               │
│         │  3. Server 處理                  │               │
│         │     ◄──── acked_event_ids ───────│               │
│         │           server_seq_highwater   │               │
│         │                                  │               │
│         │  4. 標記已同步                   │               │
│         │     synced = 1                   │               │
│         │                                  │               │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 同步 API

```
POST /api/transfer/sync

Request:
{
  "device_id": "EMT-DEVICE-001",
  "events": [
    {
      "event_id": "uuid-1",
      "mission_id": "TRF-20260103-001",
      "type": "RESERVE",
      "payload_json": "{...}",
      "occurred_at": "2026-01-03T10:00:00Z"
    }
  ],
  "last_known_seq": 42
}

Response:
{
  "acked_event_ids": ["uuid-1"],
  "rejected_events": [],
  "server_seq_highwater": 43,
  "new_events": []  // 從其他裝置來的事件
}
```

### 5.3 衝突規則

```python
# 事件以 event_id 做 idempotent
# Server 拒絕非法狀態轉移

VALID_TRANSITIONS = {
    'PLANNING': ['READY', 'ABORTED'],
    'READY': ['EN_ROUTE', 'ABORTED'],
    'EN_ROUTE': ['ARRIVED', 'ABORTED'],
    'ARRIVED': ['COMPLETED'],
    'COMPLETED': [],
    'ABORTED': []
}

def validate_event(event):
    if event.type == 'ISSUE' and mission.status != 'READY':
        raise InvalidTransition("Must be READY before ISSUE")
    if event.type == 'CONSUME' and mission.status not in ['EN_ROUTE', 'ARRIVED']:
        raise InvalidTransition("Must be EN_ROUTE or ARRIVED before CONSUME")
```

---

## 6. API 設計

### 6.1 端點清單

| 端點 | 方法 | 功能 |
|------|------|------|
| `/api/transfer/missions` | GET | 任務列表 |
| `/api/transfer/missions` | POST | 建立任務 |
| `/api/transfer/missions/{id}` | GET | 任務詳情 |
| `/api/transfer/missions/{id}/calculate` | POST | 計算物資需求 |
| `/api/transfer/missions/{id}/confirm` | POST | 確認攜帶 (RESERVE) |
| `/api/transfer/missions/{id}/depart` | POST | 出發 (ISSUE) |
| `/api/transfer/missions/{id}/arrive` | POST | 抵達 |
| `/api/transfer/missions/{id}/recheck` | POST | 返站確認剩餘量 |
| `/api/transfer/missions/{id}/incoming` | POST | 外帶物資登記 |
| `/api/transfer/missions/{id}/finalize` | POST | 結案 (寫庫存) |
| `/api/transfer/missions/{id}/abort` | POST | 中止任務 |
| `/api/transfer/sync` | POST | 離線事件同步 |
| `/api/transfer/consumption-rates` | GET | 消耗率設定 |

---

## 7. UI 設計

### 7.1 核心原則

```
┌─────────────────────────────────────────────────────────────┐
│  UX 規則：確認優先於新增                                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✓ 預設操作：確認系統建議的攜帶清單                          │
│  ✓ 手動新增：隱藏在「+ 特殊物資」，產生 ADJUST 事件          │
│                                                             │
│  目的：減少 EMT 認知負擔，緊急情況下快速操作                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 五步驟流程

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ 1. 設定  │──►│ 2. 整備  │──►│ 3. 出發  │──►│ 4. 抵達  │──►│ 5. 結案  │
│          │   │          │   │          │   │          │   │          │
│ 目的地   │   │ 建議清單 │   │ 途中儀表 │   │ Recheck  │   │ 庫存更新 │
│ 預估時間 │   │ 確認攜帶 │   │ (離線)   │   │ 外帶入庫 │   │ 歸檔     │
│ 病患狀況 │   │ Checklist│   │ 剩餘估算 │   │          │   │          │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

### 7.3 Step 1: 任務設定

```
┌─────────────────────────────────────────┐
│  新增轉送任務                            │
├─────────────────────────────────────────┤
│                                         │
│  目的地 ────────────────────────────    │
│  ┌─────────────────────────────────┐   │
│  │ 國軍台中總醫院                   │   │
│  └─────────────────────────────────┘   │
│                                         │
│  預估路程 ──────────────────────────    │
│  ┌────┐                                │
│  │ 2  │ 小時     [30min] ────●──── [4hr]│
│  └────┘                                │
│                                         │
│  病患狀況 ──────────────────────────    │
│  ● 插管 (INTUBATED)  ○ 面罩  ○ 穩定    │
│                                         │
│  氧氣流量                               │
│  ┌────┐                                │
│  │ 10 │ L/min  (插管預設)              │
│  └────┘                                │
│                                         │
│  輸液速度                               │
│  ○ 無  ● 維持 (100mL/hr)  ○ 快速       │
│                                         │
│  安全係數                               │
│  ┌────┐                                │
│  │ 3× │  ← 建議維持                    │
│  └────┘                                │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │         計算物資需求 →           │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### 7.4 Step 2: 物資整備

```
┌─────────────────────────────────────────┐
│  物資整備                    TRF-001    │
├─────────────────────────────────────────┤
│  2 小時 × 3 倍安全係數                  │
├─────────────────────────────────────────┤
│                                         │
│  氧氣                                   │
│  ┌─────────────────────────────────┐   │
│  │  E-Tank 氧氣鋼瓶                │   │
│  │  ─────────────────────────────  │   │
│  │  計算: 10 L/min × 2hr × 3       │   │
│  │        = 3,600L → 6 瓶          │   │
│  │  ─────────────────────────────  │   │
│  │  確認攜帶: [ 6 ] 瓶  ✓          │   │
│  │  [掃描鋼瓶條碼]                 │   │
│  └─────────────────────────────────┘   │
│                                         │
│  輸液                                   │
│  ┌─────────────────────────────────┐   │
│  │  NS 500mL                       │   │
│  │  計算: 100 mL/hr × 2hr × 3      │   │
│  │        = 600mL → 2 袋           │   │
│  │  確認攜帶: [ 2 ] 袋  ✓          │   │
│  └─────────────────────────────────┘   │
│                                         │
│  設備電量                               │
│  ┌─────────────────────────────────┐   │
│  │  監視器 [████████░░] 85%  ✓     │   │
│  │  需求: > 60%                    │   │
│  └─────────────────────────────────┘   │
│                                         │
│  [+ 特殊物資]  ← 手動新增 (ADJUST)      │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │      ✓ 確認攜帶，準備出發        │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### 7.5 Step 3: 途中儀表板

```
┌─────────────────────────────────────────┐
│  轉送中                      TRF-001    │
│  ══════════════════════════════════════│
│                                         │
│  目的地: 國軍台中總醫院                  │
│  已行駛: 45 min / 預估 2 hr             │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │  氧氣剩餘估算                   │   │
│  │  ████████████░░░░░░ 68%        │   │
│  │  預估可用: 1hr 22min            │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │  監視器電量                     │   │
│  │  ██████████████░░░░ 72%        │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ── 快速操作 ──                         │
│  ┌─────────┐  ┌─────────┐              │
│  │ 記錄    │  │ 給藥    │              │
│  │ 生命徵象│  │         │              │
│  └─────────┘  └─────────┘              │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │         抵達目的地 →             │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ⚠️ 離線模式 - 資料已儲存於本機         │
│                                         │
└─────────────────────────────────────────┘
```

### 7.6 Step 4-5: Recheck + 結案

(同原 spec 的 10.2 和 10.3 畫面)

---

## 8. 實作階段

### Phase 1: MVP (核心流程)

- [ ] 資料庫 Schema (missions, items, events)
- [ ] 建立/編輯任務 API
- [ ] 3× 計算引擎 (含 calculation_explain)
- [ ] PWA UI (設定、整備、Checklist)
- [ ] IndexedDB 離線儲存
- [ ] Service Worker

**驗收條件：**
- 可在離線狀態建立任務、確認攜帶
- 計算結果包含可稽核的 explain 字串

### Phase 2: 庫存連動

- [ ] CONFIRM → RESERVE 事件
- [ ] DEPART → ISSUE 事件 (扣庫存)
- [ ] Recheck UI + RETURN/CONSUME 事件
- [ ] INCOMING 外帶入庫流程
- [ ] FINALIZE 產生 ops_log

**驗收條件：**
- 結案產生 deterministic 庫存 delta
- 所有庫存變動有 ops_log 記錄

### Phase 3: 同步與整合

- [ ] /api/transfer/sync 離線同步
- [ ] 途中氧氣剩餘時間即時估算
- [ ] CIRS 整合 (病患資料拉取)
- [ ] 歷史任務分析

---

## 9. 整合邊界

| 系統 | 必要性 | 整合內容 |
|------|--------|----------|
| **MIRS** | 必要 | 設備/藥品主檔、庫存更新、ops_log |
| **CIRS** | 可選 | 病患基本資料、轉院通知 |

---

## 附錄 A: 氧氣計算快速參考

| 流量 | 1hr 用量 | E-Tank 可用時間 (2000 PSI) |
|------|----------|---------------------------|
| 2 L/min | 120 L | 5.5 hr |
| 6 L/min | 360 L | 1.8 hr |
| 10 L/min | 600 L | 1.1 hr |
| 15 L/min | 900 L | 0.7 hr |

## 附錄 B: 狀態機轉移表

| From | To | Trigger | Event |
|------|----|---------|-------|
| PLANNING | READY | confirm | RESERVE |
| PLANNING | ABORTED | abort | ABORT |
| READY | EN_ROUTE | depart | ISSUE |
| READY | ABORTED | abort | ABORT |
| EN_ROUTE | ARRIVED | arrive | - |
| EN_ROUTE | ABORTED | abort | ABORT |
| ARRIVED | COMPLETED | finalize | RETURN + CONSUME + INCOMING |

---

*文件結束*
