# 麻醉氧氣 PSI 追蹤開發規格書

**版本**: 2.0.0
**日期**: 2026-01-04
**狀態**: 規格定案

---

## 0. 摘要

將麻醉 PWA 的氧氣追蹤從「百分比」升級為「PSI 追蹤」，與 EMT Transfer 模組對齊。

### 主要改進

| 現況 (v1.x) | 目標 (v2.0) |
|-------------|-------------|
| level_percent (0-100%) | PSI 實測值 (0-2200) |
| 估算剩餘時間誤差大 | PSI → L 精確計算 |
| 無歷史追蹤 | 事件驅動完整記錄 |
| 手動選擇鋼瓶 | 認領/釋放/換瓶完整流程 |

### 設計原則 (v2.0 修正)

**Event Sourcing First** - 所有資源操作都是事件，狀態由事件推導

| ❌ 舊設計 (v1.0) | ✅ 新設計 (v2.0) |
|------------------|------------------|
| `ALTER TABLE anesthesia_cases` 加欄位 | 不修改 case 表 |
| 可變欄位 `oxygen_starting_psi` | 事件 `RESOURCE_CLAIM` |
| 可變欄位 `oxygen_ending_psi` | 事件 `RESOURCE_RELEASE` |
| 分散儲存 | 單一事件表 `anesthesia_events` |

---

## 1. Event Sourcing 架構

### 1.1 設計理念

```
┌─────────────────────────────────────────────────────────────────┐
│ Event Sourcing: State = f(Events)                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Commands (輸入)           Events (記錄)         View (查詢)   │
│   ─────────────────         ───────────────       ───────────   │
│   claimOxygen()     ───►   RESOURCE_CLAIM   ◄───  getO2Status() │
│   updatePsi()       ───►   RESOURCE_CHECK   ◄───  getPsiHistory()│
│   switchCylinder()  ───►   RESOURCE_SWITCH  ◄───  getConsumption()│
│   releaseOxygen()   ───►   RESOURCE_RELEASE │                   │
│                                                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ anesthesia_events (Append-only Event Store)              │  │
│   │ ──────────────────────────────────────────────────────── │  │
│   │ id | case_id | event_type | payload (JSON) | created_at │  │
│   │ ──────────────────────────────────────────────────────── │  │
│   │ 1  | ANES-01 | RESOURCE_CLAIM   | {cyl:"E-01",psi:2100} │  │
│   │ 2  | ANES-01 | RESOURCE_CHECK   | {psi:1800}            │  │
│   │ 3  | ANES-01 | RESOURCE_CHECK   | {psi:1500}            │  │
│   │ 4  | ANES-01 | RESOURCE_RELEASE | {psi:500}             │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│   State Reconstruction:                                         │
│   ─────────────────────                                         │
│   currentState = events.reduce((state, event) => {             │
│       switch(event.type) {                                      │
│           case 'RESOURCE_CLAIM':   return {...state, claimed};  │
│           case 'RESOURCE_CHECK':   return {...state, psi};      │
│           case 'RESOURCE_RELEASE': return {...state, released}; │
│       }                                                         │
│   }, initialState);                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 為什麼使用 Event Sourcing

| 優點 | 說明 |
|------|------|
| **完整歷史** | 每個 PSI 更新都有記錄，可重建任意時間點狀態 |
| **審計追蹤** | 誰在何時做了什麼操作，一目瞭然 |
| **無損資料** | 從不修改、只追加，避免覆蓋造成資料遺失 |
| **跨模組一致** | CIRS/MIRS 已採用此模式，架構統一 |
| **易於擴展** | 新增事件類型不影響既有資料 |

---

## 2. 事件類型定義

### 2.1 資源事件類型 (Resource Events)

| event_type | 觸發時機 | payload 結構 |
|------------|----------|--------------|
| `RESOURCE_CLAIM` | 認領鋼瓶 | `{cylinder_id, cylinder_type, initial_psi}` |
| `RESOURCE_CHECK` | 更新 PSI | `{psi, notes?}` |
| `RESOURCE_SWITCH` | 更換鋼瓶 | `{old_cylinder_id, old_ending_psi, new_cylinder_id, new_initial_psi}` |
| `RESOURCE_RELEASE` | 釋放鋼瓶 | `{ending_psi, consumed_liters?}` |

### 2.2 Payload Schema

```typescript
// RESOURCE_CLAIM
interface ResourceClaimPayload {
  cylinder_id: number;        // equipment_units.id
  cylinder_type: 'E' | 'D' | 'M' | 'H';
  cylinder_serial: string;    // unit_label 如 "O2-E-001"
  initial_psi: number;        // 0-2200
}

// RESOURCE_CHECK
interface ResourceCheckPayload {
  psi: number;                // 當前 PSI
  source?: 'VITALS' | 'MANUAL';  // 來源
  notes?: string;
}

// RESOURCE_SWITCH
interface ResourceSwitchPayload {
  old_cylinder_id: number;
  old_cylinder_serial: string;
  old_ending_psi: number;
  new_cylinder_id: number;
  new_cylinder_type: string;
  new_cylinder_serial: string;
  new_initial_psi: number;
  reason?: string;            // 換瓶原因
}

// RESOURCE_RELEASE
interface ResourceReleasePayload {
  ending_psi: number;
  consumed_liters?: number;   // 計算後回填
}
```

---

## 3. Schema 設計

### 3.1 使用既有 anesthesia_events 表

**不新增表格**，複用現有 Event Store：

```sql
-- anesthesia_events 已存在，新增事件類型即可
-- 結構:
CREATE TABLE IF NOT EXISTS anesthesia_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT,                    -- JSON
    actor_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id)
);

CREATE INDEX IF NOT EXISTS idx_anes_events_case_type
    ON anesthesia_events(case_id, event_type);
```

### 3.2 ❌ 不需要的 Schema 變更

以下變更在 v2.0 中**移除**：

```sql
-- ❌ 刪除：不再修改 anesthesia_cases 表
-- ALTER TABLE anesthesia_cases ADD COLUMN oxygen_starting_psi INTEGER;
-- ALTER TABLE anesthesia_cases ADD COLUMN oxygen_ending_psi INTEGER;
-- ALTER TABLE anesthesia_cases ADD COLUMN oxygen_cylinder_type TEXT;

-- ❌ 刪除：不需要獨立的 oxygen_log 表
-- CREATE TABLE anesthesia_oxygen_log (...)
```

**理由**：
1. 違反 Event Sourcing 的「單一真相來源」原則
2. 可變欄位會與事件狀態不同步
3. 增加維護複雜度

---

## 4. 狀態推導 (State Projection)

### 4.1 Python 實作

```python
# routes/anesthesia.py

from typing import Optional, List
from dataclasses import dataclass

@dataclass
class OxygenState:
    """從事件推導的氧氣狀態"""
    is_claimed: bool = False
    cylinder_id: Optional[int] = None
    cylinder_type: Optional[str] = None
    cylinder_serial: Optional[str] = None
    initial_psi: Optional[int] = None
    current_psi: Optional[int] = None
    psi_history: List[dict] = None

    def __post_init__(self):
        if self.psi_history is None:
            self.psi_history = []

def project_oxygen_state(events: List[dict]) -> OxygenState:
    """
    從事件列表推導氧氣狀態

    Event Sourcing 核心邏輯:
    state = events.reduce(apply_event, initial_state)
    """
    state = OxygenState()

    for event in events:
        event_type = event['event_type']
        payload = json.loads(event.get('payload', '{}'))
        timestamp = event['created_at']

        if event_type == 'RESOURCE_CLAIM':
            state.is_claimed = True
            state.cylinder_id = payload.get('cylinder_id')
            state.cylinder_type = payload.get('cylinder_type')
            state.cylinder_serial = payload.get('cylinder_serial')
            state.initial_psi = payload.get('initial_psi')
            state.current_psi = payload.get('initial_psi')
            state.psi_history = [{
                'psi': payload.get('initial_psi'),
                'timestamp': timestamp,
                'type': 'CLAIM'
            }]

        elif event_type == 'RESOURCE_CHECK':
            state.current_psi = payload.get('psi')
            state.psi_history.append({
                'psi': payload.get('psi'),
                'timestamp': timestamp,
                'type': 'CHECK'
            })

        elif event_type == 'RESOURCE_SWITCH':
            # 記錄舊瓶結束
            state.psi_history.append({
                'psi': payload.get('old_ending_psi'),
                'timestamp': timestamp,
                'type': 'SWITCH_OUT'
            })
            # 切換到新瓶
            state.cylinder_id = payload.get('new_cylinder_id')
            state.cylinder_type = payload.get('new_cylinder_type')
            state.cylinder_serial = payload.get('new_cylinder_serial')
            state.initial_psi = payload.get('new_initial_psi')
            state.current_psi = payload.get('new_initial_psi')
            state.psi_history.append({
                'psi': payload.get('new_initial_psi'),
                'timestamp': timestamp,
                'type': 'SWITCH_IN'
            })

        elif event_type == 'RESOURCE_RELEASE':
            state.current_psi = payload.get('ending_psi')
            state.psi_history.append({
                'psi': payload.get('ending_psi'),
                'timestamp': timestamp,
                'type': 'RELEASE'
            })
            state.is_claimed = False

    return state
```

### 4.2 JavaScript 實作 (PWA)

```javascript
// static/shared/xirs-resource.js

/**
 * xIRS 資源管理共用模組
 * Event Sourcing 狀態推導 + PSI 計算
 */
const XIRSResource = {
    // 鋼瓶規格
    CYLINDER_SPECS: {
        'E': { name: 'E-Tank', capacity_liters: 660, full_psi: 2100 },
        'D': { name: 'D-Tank', capacity_liters: 350, full_psi: 2100 },
        'M': { name: 'M-Tank', capacity_liters: 3000, full_psi: 2200 },
        'H': { name: 'H-Tank', capacity_liters: 6900, full_psi: 2200 }
    },

    /**
     * 從事件推導氧氣狀態
     * @param {Array} events - 事件列表 (已依 created_at 排序)
     * @returns {Object} 氧氣狀態
     */
    projectOxygenState(events) {
        const initialState = {
            isClaimed: false,
            cylinderId: null,
            cylinderType: null,
            cylinderSerial: null,
            initialPsi: null,
            currentPsi: null,
            psiHistory: []
        };

        return events
            .filter(e => e.event_type.startsWith('RESOURCE_'))
            .reduce((state, event) => {
                const payload = typeof event.payload === 'string'
                    ? JSON.parse(event.payload)
                    : event.payload;
                const ts = event.created_at;

                switch (event.event_type) {
                    case 'RESOURCE_CLAIM':
                        return {
                            ...state,
                            isClaimed: true,
                            cylinderId: payload.cylinder_id,
                            cylinderType: payload.cylinder_type,
                            cylinderSerial: payload.cylinder_serial,
                            initialPsi: payload.initial_psi,
                            currentPsi: payload.initial_psi,
                            psiHistory: [{ psi: payload.initial_psi, ts, type: 'CLAIM' }]
                        };

                    case 'RESOURCE_CHECK':
                        return {
                            ...state,
                            currentPsi: payload.psi,
                            psiHistory: [...state.psiHistory, { psi: payload.psi, ts, type: 'CHECK' }]
                        };

                    case 'RESOURCE_SWITCH':
                        return {
                            ...state,
                            cylinderId: payload.new_cylinder_id,
                            cylinderType: payload.new_cylinder_type,
                            cylinderSerial: payload.new_cylinder_serial,
                            initialPsi: payload.new_initial_psi,
                            currentPsi: payload.new_initial_psi,
                            psiHistory: [
                                ...state.psiHistory,
                                { psi: payload.old_ending_psi, ts, type: 'SWITCH_OUT' },
                                { psi: payload.new_initial_psi, ts, type: 'SWITCH_IN' }
                            ]
                        };

                    case 'RESOURCE_RELEASE':
                        return {
                            ...state,
                            isClaimed: false,
                            currentPsi: payload.ending_psi,
                            psiHistory: [...state.psiHistory, { psi: payload.ending_psi, ts, type: 'RELEASE' }]
                        };

                    default:
                        return state;
                }
            }, initialState);
    },

    /**
     * PSI 轉換為升數
     */
    psiToLiters(psi, cylinderType) {
        const spec = this.CYLINDER_SPECS[cylinderType];
        if (!spec) return 0;
        return Math.round((psi / spec.full_psi) * spec.capacity_liters);
    },

    /**
     * 計算剩餘分鐘數
     */
    estimateMinutes(currentPsi, cylinderType, flowLpm) {
        const liters = this.psiToLiters(currentPsi, cylinderType);
        if (flowLpm <= 0) return Infinity;
        return Math.round(liters / flowLpm);
    },

    /**
     * 計算消耗升數
     */
    calculateConsumption(startPsi, endPsi, cylinderType) {
        const spec = this.CYLINDER_SPECS[cylinderType];
        if (!spec) return 0;
        return Math.round(((startPsi - endPsi) / spec.full_psi) * spec.capacity_liters);
    },

    /**
     * 取得 PSI 狀態等級
     */
    getPsiLevel(psi, cylinderType) {
        const spec = this.CYLINDER_SPECS[cylinderType];
        if (!spec) return 'unknown';
        const percent = psi / spec.full_psi;
        if (percent > 0.38) return 'normal';    // > 800 PSI for E
        if (percent > 0.19) return 'warning';   // > 400 PSI for E
        return 'critical';                       // < 400 PSI
    }
};

// 匯出供其他模組使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = XIRSResource;
}
```

---

## 5. API 設計

### 5.1 認領鋼瓶

**Endpoint**: `POST /api/anesthesia/cases/{case_id}/oxygen/claim`

```python
@router.post("/cases/{case_id}/oxygen/claim")
async def claim_oxygen(case_id: str, request: ClaimOxygenRequest, actor_id: str = Query(...)):
    """
    認領氧氣鋼瓶

    1. 驗證鋼瓶可用
    2. 寫入 RESOURCE_CLAIM 事件
    3. 更新庫存狀態 (設定 claimed_by_case_id)
    """
    # 驗證 case 存在
    case = get_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    # 驗證鋼瓶可用
    cylinder = get_equipment_unit(request.cylinder_id)
    if cylinder['claimed_by_case_id']:
        raise HTTPException(409, f"Cylinder already claimed by {cylinder['claimed_by_case_id']}")

    # 寫入事件
    payload = {
        "cylinder_id": request.cylinder_id,
        "cylinder_type": request.cylinder_type,
        "cylinder_serial": cylinder['unit_label'],
        "initial_psi": request.initial_psi
    }

    append_event(case_id, 'RESOURCE_CLAIM', payload, actor_id)

    # 更新庫存
    update_equipment_claimed(request.cylinder_id, case_id)

    return {"status": "claimed", "event_type": "RESOURCE_CLAIM", "payload": payload}
```

**Request**:
```json
{
  "cylinder_id": 123,
  "cylinder_type": "E",
  "initial_psi": 2100
}
```

### 5.2 更新 PSI

**Endpoint**: `POST /api/anesthesia/cases/{case_id}/oxygen/check`

```python
@router.post("/cases/{case_id}/oxygen/check")
async def check_oxygen_psi(case_id: str, request: CheckPsiRequest, actor_id: str = Query(...)):
    """
    記錄當前 PSI (可在 vitals 時一併呼叫)
    """
    payload = {
        "psi": request.psi,
        "source": request.source or "MANUAL",
        "notes": request.notes
    }

    append_event(case_id, 'RESOURCE_CHECK', payload, actor_id)

    return {"status": "recorded", "event_type": "RESOURCE_CHECK", "psi": request.psi}
```

### 5.3 更換鋼瓶

**Endpoint**: `POST /api/anesthesia/cases/{case_id}/oxygen/switch`

```python
@router.post("/cases/{case_id}/oxygen/switch")
async def switch_oxygen_cylinder(case_id: str, request: SwitchCylinderRequest, actor_id: str = Query(...)):
    """
    更換鋼瓶 (舊瓶釋放 + 新瓶認領，原子操作)
    """
    # 取得當前狀態
    events = get_events(case_id)
    state = project_oxygen_state(events)

    if not state.is_claimed:
        raise HTTPException(400, "No cylinder currently claimed")

    payload = {
        "old_cylinder_id": state.cylinder_id,
        "old_cylinder_serial": state.cylinder_serial,
        "old_ending_psi": request.old_ending_psi,
        "new_cylinder_id": request.new_cylinder_id,
        "new_cylinder_type": request.new_cylinder_type,
        "new_cylinder_serial": get_equipment_unit(request.new_cylinder_id)['unit_label'],
        "new_initial_psi": request.new_initial_psi,
        "reason": request.reason
    }

    # 單一事件，確保原子性
    append_event(case_id, 'RESOURCE_SWITCH', payload, actor_id)

    # 更新庫存
    release_equipment(state.cylinder_id, request.old_ending_psi)
    claim_equipment(request.new_cylinder_id, case_id)

    return {"status": "switched", "event_type": "RESOURCE_SWITCH", "payload": payload}
```

### 5.4 釋放鋼瓶

**Endpoint**: `POST /api/anesthesia/cases/{case_id}/oxygen/release`

```python
@router.post("/cases/{case_id}/oxygen/release")
async def release_oxygen(case_id: str, request: ReleaseOxygenRequest, actor_id: str = Query(...)):
    """
    釋放鋼瓶，計算消耗
    """
    events = get_events(case_id)
    state = project_oxygen_state(events)

    if not state.is_claimed:
        raise HTTPException(400, "No cylinder to release")

    # 計算消耗
    consumed = calculate_consumption(state.initial_psi, request.ending_psi, state.cylinder_type)

    payload = {
        "ending_psi": request.ending_psi,
        "consumed_liters": consumed
    }

    append_event(case_id, 'RESOURCE_RELEASE', payload, actor_id)

    # 更新庫存
    release_equipment(state.cylinder_id, request.ending_psi)

    return {"status": "released", "event_type": "RESOURCE_RELEASE", "consumed_liters": consumed}
```

### 5.5 查詢氧氣狀態

**Endpoint**: `GET /api/anesthesia/cases/{case_id}/oxygen/status`

```python
@router.get("/cases/{case_id}/oxygen/status")
async def get_oxygen_status(case_id: str):
    """
    從事件推導當前氧氣狀態
    """
    events = get_events(case_id)
    state = project_oxygen_state(events)

    if not state.is_claimed:
        return {"status": "not_claimed"}

    spec = CYLINDER_SPECS[state.cylinder_type]
    available_liters = (state.current_psi / spec['full_psi']) * spec['capacity_liters']

    return {
        "status": "claimed",
        "cylinder_id": state.cylinder_id,
        "cylinder_serial": state.cylinder_serial,
        "cylinder_type": state.cylinder_type,
        "initial_psi": state.initial_psi,
        "current_psi": state.current_psi,
        "available_liters": round(available_liters),
        "psi_history": state.psi_history,
        "level": get_psi_level(state.current_psi, state.cylinder_type)
    }
```

---

## 6. 鋼瓶規格參考

| Type | 名稱 | 容量 (L) | 滿瓶 PSI |
|------|------|----------|----------|
| E | E-Tank (攜帶型) | 660 | 2100 |
| D | D-Tank (小型) | 350 | 2100 |
| M | M-Tank (中型) | 3000 | 2200 |
| H | H-Tank (大型) | 6900 | 2200 |

### PSI → 升數轉換

```
available_liters = (current_psi / full_psi) × capacity_liters
```

範例 (E-Tank):
- 2100 PSI → 660 L (100%)
- 1500 PSI → 471 L (71%)
- 500 PSI → 157 L (24%)

---

## 7. UI 設計

### 7.1 氧氣管理 Modal

```
┌─────────────────────────────────────────────────────────────┐
│ 氧氣管理                                                [x] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 已認領: O2-E-001 (E-Tank 660L)                      │   │
│  │                                                     │   │
│  │   起始 PSI: 2100                                    │   │
│  │   目前 PSI: [1500]  ◄── 可更新                      │   │
│  │                                                     │   │
│  │   ████████████░░░░░░ 71%                            │   │
│  │                                                     │   │
│  │   可用: 471 L                                       │   │
│  │   預估: 78 min @ 6 L/min                            │   │
│  │   已消耗: 189 L                                     │   │
│  │                                                     │   │
│  │   [更新 PSI]  [換瓶]  [釋放]                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  PSI 歷史                                                   │
│  ────────────────────────────────────────                   │
│  09:00  CLAIM     2100 PSI                                  │
│  09:30  CHECK     1800 PSI  (-300)                          │
│  10:00  CHECK     1500 PSI  (-300)                          │
│                                                             │
│  ────────────────────────────────────────                   │
│  可用鋼瓶                                    [重新整理]     │
│                                                             │
│  ┌───────────────────────────────────────────────────┐     │
│  │ O2-E-002 (E) 2100 PSI (100%)  [認領]              │     │
│  │ O2-E-003 (E) 1800 PSI (86%)   [認領]              │     │
│  └───────────────────────────────────────────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 認領確認

```
┌─────────────────────────────────────┐
│ 認領氧氣瓶                      [x] │
├─────────────────────────────────────┤
│                                     │
│ 鋼瓶: O2-E-001                      │
│ 類型: E-Tank (660L)                 │
│                                     │
│ 起始 PSI: [2100] / 2100             │
│           ████████████████ 100%     │
│           可用: 660 L               │
│                                     │
│ ⚠️ 請確認壓力表讀數                  │
│                                     │
│         [確認認領]  [取消]          │
└─────────────────────────────────────┘
```

### 7.3 換瓶確認

```
┌─────────────────────────────────────┐
│ 更換鋼瓶                        [x] │
├─────────────────────────────────────┤
│                                     │
│ 舊瓶: O2-E-001                      │
│ 結束 PSI: [200] / 2100              │
│                                     │
│ 新瓶: O2-E-002                      │
│ 起始 PSI: [2100] / 2100             │
│                                     │
│ 換瓶原因: [氧氣不足 ▼]              │
│                                     │
│         [確認換瓶]  [取消]          │
└─────────────────────────────────────┘
```

---

## 8. 警示機制

### 8.1 PSI 閾值 (E-Tank 為例)

| 等級 | PSI 閾值 | 百分比 | 動作 |
|------|----------|--------|------|
| 正常 | > 800 | > 38% | 無 |
| 警告 | 400-800 | 19-38% | 黃色閃爍 |
| 危急 | < 400 | < 19% | 紅色閃爍 + 音效 |

### 8.2 視覺指示

```css
.o2-normal   { background: var(--success); }
.o2-warning  { background: var(--warning); animation: pulse 1s infinite; }
.o2-critical { background: var(--danger); animation: pulse 0.5s infinite; }
```

---

## 9. 實作順序

| Phase | 內容 | 優先級 |
|-------|------|--------|
| 9.1 | 共用模組 `xirs-resource.js` | P0 |
| 9.2 | API: claim, check, release | P0 |
| 9.3 | UI: 認領/更新/釋放流程 | P0 |
| 9.4 | API: switch (換瓶) | P1 |
| 9.5 | PSI 歷史圖表 | P2 |
| 9.6 | 警示機制 | P1 |

---

## 10. 測試案例

### 10.1 完整流程測試

```bash
# 1. 認領鋼瓶
curl -X POST "http://localhost:8000/api/anesthesia/cases/ANES-001/oxygen/claim?actor_id=DR001" \
  -H "Content-Type: application/json" \
  -d '{"cylinder_id": 123, "cylinder_type": "E", "initial_psi": 2100}'

# 2. 更新 PSI (術中)
curl -X POST "http://localhost:8000/api/anesthesia/cases/ANES-001/oxygen/check?actor_id=DR001" \
  -H "Content-Type: application/json" \
  -d '{"psi": 1500}'

# 3. 查詢狀態
curl "http://localhost:8000/api/anesthesia/cases/ANES-001/oxygen/status"

# 4. 釋放鋼瓶
curl -X POST "http://localhost:8000/api/anesthesia/cases/ANES-001/oxygen/release?actor_id=DR001" \
  -H "Content-Type: application/json" \
  -d '{"ending_psi": 500}'
```

### 10.2 預期結果

步驟 3 應回傳:
```json
{
  "status": "claimed",
  "cylinder_serial": "O2-E-001",
  "cylinder_type": "E",
  "initial_psi": 2100,
  "current_psi": 1500,
  "available_liters": 471,
  "psi_history": [
    {"psi": 2100, "ts": "2026-01-04T09:00:00", "type": "CLAIM"},
    {"psi": 1500, "ts": "2026-01-04T09:30:00", "type": "CHECK"}
  ],
  "level": "normal"
}
```

步驟 4 應回傳:
```json
{
  "status": "released",
  "event_type": "RESOURCE_RELEASE",
  "consumed_liters": 502
}
```

---

## 11. 與 EMT Transfer 對比

| 項目 | EMT Transfer | Anesthesia |
|------|--------------|------------|
| 資料儲存 | JSON 欄位 (transfer_records) | 事件表 (anesthesia_events) |
| 多瓶支援 | ✅ 陣列 | 單一 (換瓶用 SWITCH) |
| PSI 歷史 | 僅起始/結束 | 完整時間序列 |
| 狀態推導 | 直接讀取 | Event Sourcing |

---

## 12. 變更記錄

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| 1.0.0 | 2026-01-04 | 初版規格 (含 ALTER TABLE) |
| 2.0.0 | 2026-01-04 | **重構為 Event Sourcing 架構**<br>- 移除 `ALTER TABLE anesthesia_cases`<br>- 定義 `RESOURCE_*` 事件類型<br>- 新增 `xirs-resource.js` 共用模組<br>- 新增 `RESOURCE_SWITCH` 換瓶事件<br>- API 重新設計為事件導向 |

---

*MIRS Anesthesia PSI Tracking - Event Sourcing Edition*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
