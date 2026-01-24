# xIRS 氧氣鋼瓶追蹤與跨裝置同步規格書

**版本**: 1.3
**日期**: 2026-01-24
**狀態**: ✅ 實作完成 (Phase 2-9) + 流速顯示修正
**審閱者**: Gemini, ChatGPT
**作者**: Claude Code (Opus 4.5)

---

## 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-01-24 | 初版 |
| 1.1 | 2026-01-24 | **重大架構修正** - 根據 Gemini/ChatGPT 審閱：<br>• 移除對 xIRS.Bus 的跨裝置依賴<br>• 氧氣事件併入主 events 表 (Walkaway 一致)<br>• 新增換瓶 (Swap) 工作流程<br>• 新增 2-RPi 測試計畫 |
| 1.2 | 2026-01-24 | **實作完成** - Phase 2-9 全部實作：<br>• `routes/oxygen_tracking.py` - 氧氣追蹤模組<br>• `shared/sdk/xirs-bus.js` - BroadcastChannel + SSE<br>• `main.py` - 路由註冊 |
| 1.3 | 2026-01-24 | **整合測試與修正** - 詳見 §13 問題解決歷程 |

---

## 1. 問題陳述

### 1.1 觀察到的問題

| # | 問題 | 影響 |
|---|------|------|
| 1 | BioMed 顯示 "H型2號" 而非 "E-CYL-002" | 無法識別實際鋼瓶 |
| 2 | 麻醉進行中，氧氣 % 不會自動扣減 | 無法即時掌握剩餘量 |
| 3 | iPad A (手術室) 更新，iPad B (設備庫) 看不到 | **跨裝置同步失敗** |

### 1.2 架構警訊 (Gemini 指出)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🚨 xIRS.Bus 的侷限性                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   BroadcastChannel 僅限「同一瀏覽器、同一裝置」                              │
│                                                                              │
│   ✅ 可運作: 同一台 iPad 開兩個分頁 (Anesthesia + BioMed)                    │
│   ❌ 不可運作: iPad A (手術室) ↔ iPad B (設備庫)                             │
│                                                                              │
│   結論: xIRS.Bus 只能做「本地 UI 刷新」，不能做「跨裝置資料同步」            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 正確架構 (ChatGPT 確認)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 正確的資料流                                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                        ┌─────────────┐                                      │
│                        │  MIRS Hub   │                                      │
│                        │  (RPi/後端)  │                                      │
│                        │             │                                      │
│                        │  events 表  │  ◄── 唯一權威 (Single Source of Truth)│
│                        │  projections│                                      │
│                        └──────┬──────┘                                      │
│                               │                                              │
│              ┌────────────────┼────────────────┐                            │
│              │                │                │                            │
│              ▼                ▼                ▼                            │
│      ┌───────────┐    ┌───────────┐    ┌───────────┐                       │
│      │  iPad A   │    │  iPad B   │    │   MIRS    │                       │
│      │ Anesthesia│    │  BioMed   │    │ Dashboard │                       │
│      └───────────┘    └───────────┘    └───────────┘                       │
│                                                                              │
│      POST events      GET projections   GET projections                     │
│      ───────────►     ◄───────────────  ◄───────────────                    │
│                                                                              │
│   xIRS.Bus: 只用於同裝置 UI 即時刷新 (錦上添花，非必要)                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 設計原則 (Non-Negotiables)

### 2.1 單一事件權威 (與 Walkaway 一致)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ DIRECTIVE: 氧氣事件必須併入主 events 表                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   氧氣生命週期事件 = Walkaway event-sourcing 的一部分                        │
│                                                                              │
│   事件類型:                                                                  │
│   • OXYGEN_CLAIMED    - 認領鋼瓶                                            │
│   • OXYGEN_FLOW_CHANGE - 流量變更                                            │
│   • OXYGEN_CHECKED    - PSI/% 手動檢查                                       │
│   • OXYGEN_RELEASED   - 釋放鋼瓶                                             │
│   • OXYGEN_SWAPPED    - 換瓶 (原子操作)                                      │
│                                                                              │
│   entity_type = 'equipment_unit'                                            │
│   entity_id = unit.id (鋼瓶單位 ID)                                          │
│                                                                              │
│   效果:                                                                      │
│   • Lifeboat restore 後可重建一致狀態                                        │
│   • BioMed / MIRS / Anesthesia 都讀同一套 projections                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Transport 層級分離

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ DIRECTIVE: Transport 只搬運真相，不能生成真相                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   層級 1: 權威 (Authority)                                                   │
│   ─────────────────────────                                                  │
│   events 表 (MIRS Hub SQLite/PostgreSQL)                                    │
│   → 任何狀態變更必須先寫入這裡                                               │
│                                                                              │
│   層級 2: 投影 (Projections)                                                 │
│   ─────────────────────────                                                  │
│   equipment_units.level_percent, claimed_by_case_id, status                 │
│   → 從 events 重建，不允許多處 service 任意寫回                              │
│                                                                              │
│   層級 3: 通知 (Notifications)                                               │
│   ─────────────────────────                                                  │
│   xIRS.Bus (BroadcastChannel) - 同裝置 UI 刷新                               │
│   SSE / Polling - 跨裝置狀態同步                                             │
│   → 只是「通知有更新」，消費者仍以 projections 為準                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 查詢時計算 (Virtual Sensor)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ DIRECTIVE: 不要每分鐘寫事件扣減 %，改為讀取時動態計算                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   寫入時 (Anesthesia PWA):                                                   │
│   ────────────────────────                                                   │
│   只記錄「狀態變更事件」:                                                    │
│   • 10:00 OXYGEN_CLAIMED: initial_level=90%, flow_rate=2.0 L/min            │
│   • 10:30 OXYGEN_FLOW_CHANGE: flow_rate=4.0 L/min                           │
│   • 11:00 OXYGEN_RELEASED: final_level=45%                                   │
│                                                                              │
│   讀取時 (BioMed PWA / MIRS):                                                │
│   ────────────────────────                                                   │
│   後端根據「最後事件時間」與「當前時間」動態計算:                             │
│                                                                              │
│   current_level = last_known_level - (elapsed_minutes × flow_rate / capacity)│
│                                                                              │
│   優點:                                                                      │
│   • 資料庫只有 3 筆紀錄                                                      │
│   • BioMed 每秒看到的 % 都是最新的                                           │
│   • 不會塞滿垃圾事件                                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 事件定義 (Canonical Events)

### 3.1 OXYGEN_CLAIMED

```json
{
  "event_id": "019beaab-ac13-7001-8c90-3b0c6f17c6b3",
  "entity_type": "equipment_unit",
  "entity_id": "123",
  "event_type": "OXYGEN_CLAIMED",
  "ts_device": 1706083200000,
  "actor_id": "nurse-001",
  "payload": {
    "case_id": "ANES-2026-001",
    "unit_serial": "O2E-006-02",
    "equipment_id": "EMER-EQ-006",
    "cylinder_type": "E",
    "initial_level_percent": 90,
    "initial_psi": 1980,
    "capacity_liters": 680,
    "flow_rate_lpm": 2.0,
    "note": "手術開始認領"
  }
}
```

### 3.2 OXYGEN_FLOW_CHANGE

```json
{
  "event_type": "OXYGEN_FLOW_CHANGE",
  "entity_id": "123",
  "payload": {
    "case_id": "ANES-2026-001",
    "previous_flow_rate_lpm": 2.0,
    "new_flow_rate_lpm": 4.0,
    "reason": "病患需求增加"
  }
}
```

### 3.3 OXYGEN_CHECKED (手動 PSI 讀數)

```json
{
  "event_type": "OXYGEN_CHECKED",
  "entity_id": "123",
  "payload": {
    "case_id": "ANES-2026-001",
    "psi": 1650,
    "level_percent": 75,
    "flow_rate_lpm": 4.0
  }
}
```

### 3.4 OXYGEN_SWAPPED (換瓶 - 原子操作)

```json
{
  "event_type": "OXYGEN_SWAPPED",
  "entity_id": "123",
  "payload": {
    "case_id": "ANES-2026-001",
    "old_cylinder": {
      "unit_id": 123,
      "unit_serial": "O2E-006-02",
      "final_level_percent": 5,
      "final_psi": 110,
      "consumed_liters": 578,
      "new_status": "EMPTY"
    },
    "new_cylinder": {
      "unit_id": 456,
      "unit_serial": "O2E-006-03",
      "initial_level_percent": 100,
      "initial_psi": 2200,
      "capacity_liters": 680,
      "inherited_flow_rate_lpm": 4.0
    }
  }
}
```

### 3.5 OXYGEN_RELEASED

```json
{
  "event_type": "OXYGEN_RELEASED",
  "entity_id": "123",
  "payload": {
    "case_id": "ANES-2026-001",
    "final_level_percent": 45,
    "final_psi": 990,
    "total_consumed_liters": 306,
    "duration_minutes": 120,
    "new_status": "AVAILABLE"
  }
}
```

---

## 4. 鋼瓶狀態機 (Digital Twin)

```
                    OXYGEN_CLAIMED
        ┌───────────────────────────────────┐
        │                                   ▼
    ┌───────┐                         ┌──────────┐
    │ IDLE  │                         │  IN_USE  │
    │(庫存中)│                         │(使用中)   │
    └───┬───┘                         └────┬─────┘
        ▲                                  │
        │         OXYGEN_RELEASED          │
        │◄─────────────────────────────────┤
        │         (final > 10%)            │
        │                                  │
        │                                  │ OXYGEN_RELEASED
        │                                  │ (final <= 10%)
        │                                  │ 或 OXYGEN_SWAPPED
        │                                  ▼
        │                             ┌─────────┐
        │         手動補充             │  EMPTY  │
        └─────────────────────────────│ (空瓶)   │
                                      └─────────┘
```

**狀態定義**:
| 狀態 | 說明 | BioMed 顯示 |
|------|------|-------------|
| `IDLE` | 庫存中，可被認領 | 綠色，可點擊 |
| `IN_USE` | 掛在麻醉機上，正在消耗 | 橙色，顯示 case_id |
| `EMPTY` | 空瓶，待更換/補充 | 紅色，需要處理 |

---

## 5. API 端點

### 5.1 寫入端點 (Anesthesia PWA 呼叫)

```python
# POST /api/anesthesia/cases/{case_id}/oxygen/claim
# POST /api/anesthesia/cases/{case_id}/oxygen/flow-change
# POST /api/anesthesia/cases/{case_id}/oxygen/check
# POST /api/anesthesia/cases/{case_id}/oxygen/swap
# POST /api/anesthesia/cases/{case_id}/oxygen/release
```

**共通行為**:
1. 驗證請求
2. 建立 canonical event (寫入 events 表)
3. 更新 projection (equipment_units 表)
4. 回傳成功 + live_status

### 5.2 讀取端點 (BioMed / MIRS 呼叫)

```python
@router.get("/api/v2/equipment/units/{unit_id}/live-status")
async def get_unit_live_status(unit_id: int):
    """
    取得鋼瓶即時狀態 (含 Virtual Sensor 計算)

    Returns:
        - unit_serial, equipment_id, status
        - level_percent: DB 中的快取值
        - live_level_percent: 即時計算值 (如果 IN_USE)
        - consumed_liters, remaining_liters
        - flow_rate_lpm, claimed_by_case_id
        - time_to_empty_minutes: 預估耗盡時間
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT eu.*, e.capacity_liters, e.name as equipment_name
        FROM equipment_units eu
        JOIN equipment e ON eu.equipment_id = e.id
        WHERE eu.id = ?
    """, (unit_id,))

    unit = cursor.fetchone()
    if not unit:
        raise HTTPException(404, "Unit not found")

    result = dict(unit)

    # 如果正在使用中，計算即時消耗
    if unit['status'] == 'IN_USE' and unit['claimed_by_case_id']:
        live = calculate_virtual_sensor(cursor, unit_id, unit['claimed_by_case_id'])
        if live:
            result.update({
                'live_level_percent': live['current_level'],
                'consumed_liters': live['consumed_liters'],
                'remaining_liters': live['remaining_liters'],
                'flow_rate_lpm': live['flow_rate_lpm'],
                'time_to_empty_minutes': live['time_to_empty'],
                'is_live_calculation': True
            })

    return result


def calculate_virtual_sensor(cursor, unit_id: int, case_id: str) -> dict:
    """
    Virtual Sensor: 根據流量事件動態計算目前剩餘量

    Flow Rate 權威規則 (ChatGPT 建議):
    1. 最新 OXYGEN_CHECKED.flow_rate_lpm
    2. 否則 OXYGEN_FLOW_CHANGE.new_flow_rate_lpm
    3. 否則 OXYGEN_CLAIMED.flow_rate_lpm
    4. 最後才用 default (但 default 必須在 claim 時寫成明確值)
    """
    # 取得最新流量相關事件
    cursor.execute("""
        SELECT event_type, payload, ts_device
        FROM events
        WHERE entity_type = 'equipment_unit'
          AND entity_id = ?
          AND event_type IN ('OXYGEN_CLAIMED', 'OXYGEN_FLOW_CHANGE', 'OXYGEN_CHECKED')
        ORDER BY ts_device DESC
    """, (str(unit_id),))

    events = cursor.fetchall()
    if not events:
        return None

    # 找出 flow_rate (優先順序: CHECKED > FLOW_CHANGE > CLAIMED)
    flow_rate = None
    initial_level = None
    claim_time = None
    capacity = None

    for event in events:
        payload = json.loads(event['payload'])
        event_type = event['event_type']

        if event_type == 'OXYGEN_CHECKED' and flow_rate is None:
            flow_rate = payload.get('flow_rate_lpm')
        elif event_type == 'OXYGEN_FLOW_CHANGE' and flow_rate is None:
            flow_rate = payload.get('new_flow_rate_lpm')
        elif event_type == 'OXYGEN_CLAIMED':
            if flow_rate is None:
                flow_rate = payload.get('flow_rate_lpm', 2.0)
            initial_level = payload.get('initial_level_percent')
            claim_time = event['ts_device']
            capacity = payload.get('capacity_liters', 680)

    if not all([flow_rate, initial_level, claim_time, capacity]):
        return None

    # 計算已消耗量
    elapsed_ms = int(time.time() * 1000) - claim_time
    elapsed_minutes = elapsed_ms / 1000 / 60

    initial_liters = (initial_level / 100) * capacity
    consumed_liters = elapsed_minutes * flow_rate
    remaining_liters = max(0, initial_liters - consumed_liters)

    current_level = int(remaining_liters / capacity * 100)
    time_to_empty = int(remaining_liters / flow_rate) if flow_rate > 0 else None

    return {
        'current_level': max(0, min(100, current_level)),
        'consumed_liters': round(consumed_liters, 1),
        'remaining_liters': round(remaining_liters, 1),
        'flow_rate_lpm': flow_rate,
        'time_to_empty': time_to_empty,
        'elapsed_minutes': round(elapsed_minutes, 1)
    }
```

### 5.3 事件訂閱端點 (跨裝置同步)

```python
@router.get("/api/events/stream")
async def event_stream(
    entity_type: str = Query(None),
    since_event_id: str = Query(None)
):
    """
    Server-Sent Events (SSE) 端點

    BioMed / MIRS 可訂閱此端點接收即時事件通知
    """
    async def generate():
        last_id = since_event_id
        while True:
            # 查詢新事件
            events = get_events_since(last_id, entity_type)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                last_id = event['event_id']

            await asyncio.sleep(1)  # 1 秒輪詢間隔

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"}
    )
```

---

## 6. Projection 更新規則

### 6.1 equipment_units 表更新

```python
def update_oxygen_projection(conn, event: dict):
    """
    根據氧氣事件更新 equipment_units projection

    規則 (ChatGPT 建議):
    - level_percent 只能由 projection 更新，不允許多處 service 任意寫回
    - RELEASED 時以事件的 final_level_percent 為準
    """
    cursor = conn.cursor()
    unit_id = int(event['entity_id'])
    payload = json.loads(event['payload']) if isinstance(event['payload'], str) else event['payload']
    event_type = event['event_type']

    if event_type == 'OXYGEN_CLAIMED':
        cursor.execute("""
            UPDATE equipment_units SET
                status = 'IN_USE',
                claimed_by_case_id = ?,
                claimed_at = datetime('now'),
                last_flow_rate_lpm = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload['case_id'], payload.get('flow_rate_lpm', 2.0), unit_id))

    elif event_type == 'OXYGEN_FLOW_CHANGE':
        cursor.execute("""
            UPDATE equipment_units SET
                last_flow_rate_lpm = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload['new_flow_rate_lpm'], unit_id))

    elif event_type == 'OXYGEN_CHECKED':
        # 手動檢查更新快取值
        cursor.execute("""
            UPDATE equipment_units SET
                level_percent = ?,
                last_flow_rate_lpm = COALESCE(?, last_flow_rate_lpm),
                last_check = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload['level_percent'], payload.get('flow_rate_lpm'), unit_id))

    elif event_type == 'OXYGEN_RELEASED':
        cursor.execute("""
            UPDATE equipment_units SET
                status = ?,
                level_percent = ?,
                claimed_by_case_id = NULL,
                claimed_at = NULL,
                last_flow_rate_lpm = NULL,
                updated_at = datetime('now')
            WHERE id = ?
        """, (payload.get('new_status', 'AVAILABLE'), payload['final_level_percent'], unit_id))

    elif event_type == 'OXYGEN_SWAPPED':
        old = payload['old_cylinder']
        new = payload['new_cylinder']

        # 舊瓶標記為空
        cursor.execute("""
            UPDATE equipment_units SET
                status = ?,
                level_percent = ?,
                claimed_by_case_id = NULL,
                claimed_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
        """, (old['new_status'], old['final_level_percent'], old['unit_id']))

        # 新瓶標記為使用中
        cursor.execute("""
            UPDATE equipment_units SET
                status = 'IN_USE',
                level_percent = ?,
                claimed_by_case_id = ?,
                claimed_at = datetime('now'),
                last_flow_rate_lpm = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (new['initial_level_percent'], payload['case_id'],
              new['inherited_flow_rate_lpm'], new['unit_id']))

    conn.commit()
```

---

## 7. xIRS.Bus 角色重新定義

### 7.1 定位：本地 UI 刷新 (錦上添花)

```javascript
// shared/sdk/xirs-bus.js

class XIRSBus {
    constructor() {
        // 只用 BroadcastChannel (同裝置)
        this.channel = new BroadcastChannel('xirs-bus');
        this.listeners = new Map();

        this.channel.onmessage = (event) => {
            const { type, data } = event.data;
            this._notify(type, data);
        };
    }

    /**
     * 發送事件
     *
     * 注意：這只是「通知」，不是「權威」
     * 呼叫前必須確保已經透過 API 寫入 events 表
     */
    emit(type, data) {
        // 本地通知
        this._notify(type, data);

        // 跨 Tab 通知 (同裝置)
        this.channel.postMessage({ type, data });
    }

    on(type, callback) {
        if (!this.listeners.has(type)) {
            this.listeners.set(type, []);
        }
        this.listeners.get(type).push(callback);
    }

    _notify(type, data) {
        const callbacks = this.listeners.get(type) || [];
        callbacks.forEach(cb => {
            try { cb(data); } catch (e) { console.error(e); }
        });
    }
}
```

### 7.2 使用模式

```javascript
// Anesthesia PWA - 認領氧氣瓶後

async function claimOxygen(unitId, flowRate) {
    // 1. 先寫入 Backend (權威)
    const res = await fetch(`/api/anesthesia/cases/${caseId}/oxygen/claim`, {
        method: 'POST',
        body: JSON.stringify({ unit_id: unitId, flow_rate_lpm: flowRate })
    });

    if (!res.ok) throw new Error('Claim failed');

    const data = await res.json();

    // 2. 發送 Bus 通知 (只是「有更新」的訊號)
    if (window.xIRS?.Bus) {
        xIRS.Bus.emit('oxygen:claimed', {
            unit_id: unitId,
            case_id: caseId,
            // 不傳完整資料，讓 consumer 自己 refetch
        });
    }

    return data;
}

// BioMed PWA - 監聽通知

init() {
    // 監聽 Bus (同裝置即時刷新)
    if (window.xIRS?.Bus) {
        xIRS.Bus.on('oxygen:claimed', (data) => {
            console.log('[BioMed] Oxygen claimed notification');
            this.loadResilienceStatus();  // 重新從 API 載入
        });

        xIRS.Bus.on('oxygen:released', () => {
            this.loadResilienceStatus();
        });
    }

    // 同時設定 Polling (跨裝置同步)
    setInterval(() => {
        this.loadResilienceStatus();
    }, 30000);  // 每 30 秒輪詢
}
```

---

## 8. 2-RPi 測試計畫 (Walkaway 延伸)

### 8.1 測試環境

```
┌─────────────────┐                    ┌─────────────────┐
│     RPi-A       │                    │     RPi-B       │
│  (Primary Hub)  │                    │ (DR Target)     │
│                 │                    │                 │
│  - events 表    │   Lifeboat        │  - 空 DB        │
│  - projections  │  ─────────────►   │                 │
│                 │                    │                 │
└─────────────────┘                    └─────────────────┘
```

### 8.2 測試腳本 (API 驅動，無 UI)

```bash
#!/bin/bash
# tests/oxygen_sync_test.sh

RPI_A="http://rpi-a.local:8000"
RPI_B="http://rpi-b.local:8000"

echo "=== O2 Sync Test Suite ==="

# 1. Seed equipment_units on RPi-A
echo "[1] Seeding equipment..."
curl -X POST "$RPI_A/api/seed/equipment" -d '{"type": "oxygen_cylinders"}'

# 2. Create anesthesia case
echo "[2] Creating case..."
CASE_ID=$(curl -s -X POST "$RPI_A/api/anesthesia/cases" \
    -H "Content-Type: application/json" \
    -d '{"patient_name": "O2 Test Patient"}' | jq -r '.id')

# 3. Claim oxygen cylinder
echo "[3] Claiming oxygen..."
curl -X POST "$RPI_A/api/anesthesia/cases/$CASE_ID/oxygen/claim" \
    -H "Content-Type: application/json" \
    -d '{
        "unit_id": 1,
        "initial_level_percent": 90,
        "flow_rate_lpm": 2.0
    }'

# 4. Verify projection on RPi-A
echo "[4] Verifying RPi-A projection..."
STATUS_A=$(curl -s "$RPI_A/api/v2/equipment/units/1/live-status")
echo "RPi-A status: $STATUS_A"

# 5. Wait 5 minutes (simulate usage)
echo "[5] Waiting 5 minutes..."
sleep 300

# 6. Check live_level_percent
echo "[6] Checking live status..."
LIVE_A=$(curl -s "$RPI_A/api/v2/equipment/units/1/live-status" | jq '.live_level_percent')
echo "Live level after 5min: $LIVE_A%"
# Expected: ~88.5% (90 - 5min * 2L/min / 680L * 100)

# 7. Export events from RPi-A
echo "[7] Exporting events..."
curl -s "$RPI_A/api/dr/export" > /tmp/events_backup.json

# 8. Restore to RPi-B (Lifeboat)
echo "[8] Restoring to RPi-B..."
curl -X POST "$RPI_B/api/dr/restore" \
    -H "Content-Type: application/json" \
    -d @/tmp/events_backup.json

# 9. Verify projection on RPi-B
echo "[9] Verifying RPi-B projection..."
STATUS_B=$(curl -s "$RPI_B/api/v2/equipment/units/1/live-status")
echo "RPi-B status: $STATUS_B"

# 10. Assert match
LEVEL_A=$(echo $STATUS_A | jq '.level_percent')
LEVEL_B=$(echo $STATUS_B | jq '.level_percent')

if [ "$LEVEL_A" == "$LEVEL_B" ]; then
    echo "✅ PASS: Projections match after Lifeboat restore"
else
    echo "❌ FAIL: Projection mismatch (A=$LEVEL_A, B=$LEVEL_B)"
    exit 1
fi

echo "=== Test Complete ==="
```

### 8.3 驗收矩陣

| # | 測試 | 預期結果 | Walkaway 相容 |
|---|------|----------|---------------|
| O2-01 | 認領鋼瓶 | status=IN_USE, claimed_by_case_id 正確 | ✅ |
| O2-02 | 5 分鐘後查 live_level | ~88.5% (虛擬感測器計算) | ✅ |
| O2-03 | 換瓶 | 舊瓶 EMPTY，新瓶 IN_USE | ✅ |
| O2-04 | 釋放鋼瓶 | status=AVAILABLE/EMPTY | ✅ |
| O2-05 | Lifeboat restore | 投影與 RPi-A 一致 | ✅ |
| O2-06 | 重建投影 | 從 events 重建後狀態一致 | ✅ |

---

## 9. 實作優先順序

| Phase | 工作項目 | 狀態 | 實作檔案 |
|-------|----------|------|----------|
| 1 | ✅ 修正 BioMed 顯示邏輯 (unit_serial) | 完成 | `frontend/biomed/index.html` |
| 2 | ✅ 定義氧氣 canonical events schema | 完成 | `routes/oxygen_tracking.py:init_oxygen_events_schema()` |
| 3 | ✅ 實作 /oxygen/claim, release 端點 | 完成 | `routes/oxygen_tracking.py:claim_oxygen()`, `release_oxygen()` |
| 4 | ✅ 實作 calculate_virtual_sensor() | 完成 | `routes/oxygen_tracking.py:calculate_virtual_sensor()` |
| 5 | ✅ 實作 /live-status 端點 | 完成 | `routes/oxygen_tracking.py:get_unit_live_status()` |
| 6 | ✅ 實作 Projection 更新邏輯 | 完成 | `routes/oxygen_tracking.py:update_oxygen_projection()` |
| 7 | ✅ 實作換瓶 (swap) 工作流程 | 完成 | `routes/oxygen_tracking.py:swap_cylinder()` |
| 8 | ✅ 升級 xIRS.Bus (非阻塞通知) | 完成 | `shared/sdk/xirs-bus.js` |
| 9 | ✅ 實作 SSE 端點 (跨裝置) | 完成 | `routes/oxygen_tracking.py:event_stream()` |
| 10 | 🔲 2-RPi 測試腳本 | 待測試 | `tests/oxygen_sync_test.sh` |

---

## 10. 開放問題 (已解決)

| 問題 | 決策 |
|------|------|
| 釋放時是否更新 equipment_units.level_percent? | ✅ 是，由 projection 更新 |
| 流量預設值? | ✅ claim 時必須明確寫入，不用隱性 default |
| xIRS.Bus 角色? | ✅ 降級為本地 UI 刷新，跨裝置用 Polling/SSE |

---

## 11. 相關文件

**規格文件:**
- `DEV_SPEC_IMPLEMENTATION_DIRECTIVES_v1.0.md` - 實作指令書
- `DEV_SPEC_ANESTHESIA_PSI_TRACKING.md` - PSI 追蹤規格
- `PROGRESS_REPORT_WALKAWAY_v1.0.md` - Event Sourcing 進度

**實作檔案:**
- `routes/oxygen_tracking.py` - 氧氣追蹤模組 (1,270+ 行)
- `shared/sdk/xirs-bus.js` - xIRS.Bus v1.1 + SSE Client
- `main.py` - 路由註冊 (OXYGEN_TRACKING_AVAILABLE)

---

## 12. API 端點總覽

| 方法 | 端點 | 說明 |
|------|------|------|
| POST | `/api/oxygen/cases/{case_id}/claim` | 認領氧氣瓶 |
| POST | `/api/oxygen/cases/{case_id}/flow-change` | 流量變更 |
| POST | `/api/oxygen/cases/{case_id}/check` | 手動 PSI/% 檢查 |
| POST | `/api/oxygen/cases/{case_id}/swap` | 換瓶 (原子操作) |
| POST | `/api/oxygen/cases/{case_id}/release` | 釋放氧氣瓶 |
| GET | `/api/oxygen/units/{unit_id}/live-status` | 即時狀態 (含 Virtual Sensor) |
| GET | `/api/oxygen/units` | 列出所有氧氣瓶單位 |
| GET | `/api/oxygen/units/{unit_id}/events` | 單位事件歷史 |
| GET | `/api/oxygen/events/stream` | SSE 跨裝置同步 |

---

## 13. 問題解決歷程 (v1.3)

### 13.1 藥物列表問題

**問題**: 麻醉 PWA 給藥列表顯示藥物數量遠少於 Vercel demo

**根因**: `services/anesthesia_billing.py` 的 `get_quick_drugs_with_inventory()` 使用硬編碼的 `medicine_code` 查詢，但 RPi 資料庫中藥品沒有這些 code

**解決**: 改用 `generic_name` 查詢並加入 16 種常用麻醉藥物的 fallback 預設值

**檔案**: `services/anesthesia_billing.py`

---

### 13.2 氧氣認領失敗 - events 表不存在

**問題**: 認領氧氣時回傳 `Internal Server Error`

**錯誤訊息**:
```
sqlite3.OperationalError: no such table: events
```

**根因**: 氧氣追蹤模組依賴 `events` 表 (與 Walkaway Event Sourcing 一致)，但該表未在 RPi 建立

**解決**: 在 `main.py` startup 加入 migration:
```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        ts_device INTEGER NOT NULL,
        actor_id TEXT,
        payload TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
```

---

### 13.3 氧氣認領失敗 - equipment_units 欄位不存在

**問題**: events 表建立後仍失敗

**錯誤訊息**:
```
sqlite3.OperationalError: no such column: claimed_by_case_id
```

**根因**: `equipment_units` 表缺少氧氣追蹤所需欄位

**解決**: 加入 migration 新增欄位:
```sql
ALTER TABLE equipment_units ADD COLUMN claimed_by_case_id TEXT;
ALTER TABLE equipment_units ADD COLUMN claimed_at DATETIME;
ALTER TABLE equipment_units ADD COLUMN claimed_by_user_id TEXT;
ALTER TABLE equipment_units ADD COLUMN last_flow_rate_lpm REAL;
ALTER TABLE equipment_units ADD COLUMN is_active INTEGER DEFAULT 1;
```

**手動 Migration 指令** (RPi 上執行):
```bash
sqlite3 /home/xirs/mirs/database/mirs.db "ALTER TABLE equipment_units ADD COLUMN claimed_by_case_id TEXT; ALTER TABLE equipment_units ADD COLUMN claimed_at DATETIME; ALTER TABLE equipment_units ADD COLUMN claimed_by_user_id TEXT; ALTER TABLE equipment_units ADD COLUMN last_flow_rate_lpm REAL; ALTER TABLE equipment_units ADD COLUMN is_active INTEGER DEFAULT 1;"
```

---

### 13.4 氧氣認領失敗 - capacity_liters 欄位不存在

**問題**: 欄位新增後仍失敗

**錯誤訊息**:
```
sqlite3.OperationalError: no such column: e.capacity_liters
```

**根因**: 查詢引用 `equipment.capacity_liters`，但該欄位不存在於 RPi 資料庫

**解決**: 移除查詢中的 `e.capacity_liters`，改用硬編碼容量:
```python
# 根據鋼瓶類型設定容量
if 'H' in unit_serial.upper():
    capacity_liters = 6900  # H 型
else:
    capacity_liters = 680   # E 型 (預設)
```

---

### 13.5 流速顯示錯誤

**問題**: 認領時設定 3 L/min，但氧氣模態窗顯示 2 L/min

**根因**: `routes/anesthesia.py` 的 `get_oxygen_status()` 從 vitals 事件計算平均流速，而非讀取 `equipment_units.last_flow_rate_lpm`

**原始程式碼**:
```python
# Get latest flow rate from vitals
cursor.execute("""
    SELECT payload FROM anesthesia_events
    WHERE case_id = ? AND event_type = 'VITAL_SIGN'
    ORDER BY clinical_time DESC LIMIT 10
""", (case_id,))

vitals = cursor.fetchall()
flow_rates = []
for v in vitals:
    payload = json.loads(v['payload'])
    if payload.get('o2_flow_lpm'):
        flow_rates.append(payload['o2_flow_lpm'])

avg_flow = sum(flow_rates) / len(flow_rates) if flow_rates else 2.0  # Default 2 L/min
```

**修正後**:
```python
# Get cylinder info including claimed flow rate
cursor.execute("""
    SELECT u.unit_serial, u.level_percent, u.last_flow_rate_lpm, et.capacity_config
    FROM equipment_units u
    JOIN equipment e ON u.equipment_id = e.id
    LEFT JOIN equipment_types et ON e.type_code = et.type_code
    WHERE u.id = ?
""", (int(case['oxygen_source_id']),))

cylinder = cursor.fetchone()

# Use claimed flow rate from equipment_units, fall back to vitals or default
avg_flow = cylinder['last_flow_rate_lpm'] if cylinder['last_flow_rate_lpm'] else None

if avg_flow is None:
    # Fallback: try to get from vitals
    # ... (原本的 vitals 查詢邏輯)
```

**關鍵改變**: 優先讀取 `equipment_units.last_flow_rate_lpm` (認領時寫入)，僅在未設定時才 fallback 到 vitals 計算

---

### 13.6 問題解決總結

| # | 問題 | 根因 | 解決方案 | 檔案 |
|---|------|------|----------|------|
| 1 | 藥物列表過少 | 硬編碼 medicine_code | 改用 generic_name + fallback | `services/anesthesia_billing.py` |
| 2 | events 表不存在 | 未建表 | main.py startup migration | `main.py` |
| 3 | claimed_by_case_id 不存在 | 缺欄位 | ALTER TABLE 新增欄位 | `main.py` + 手動 migration |
| 4 | capacity_liters 不存在 | 查詢引用不存在欄位 | 移除欄位，用鋼瓶類型判斷 | `routes/anesthesia.py` |
| 5 | 流速顯示 2 L/min | 從 vitals 計算而非 DB | 讀取 last_flow_rate_lpm | `routes/anesthesia.py` |

---

### 13.7 學習心得

1. **Schema 一致性**: Vercel demo 與 RPi 的資料庫 schema 可能不同步，需要 migration 策略
2. **Fallback 設計**: 在查詢時應考慮欄位可能不存在，使用 try/except 或 COALESCE
3. **權威資料來源**: 流速應該從「認領時寫入的值」讀取，而非「間接計算」
4. **手動 Migration**: 對於已部署的 RPi，需要提供單行 sqlite3 指令供現場執行

---

*xIRS Oxygen Tracking & Cross-Device Sync Specification v1.3*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
