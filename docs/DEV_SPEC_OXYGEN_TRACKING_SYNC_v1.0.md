# xIRS 氧氣鋼瓶追蹤與跨 PWA 同步規格書

**版本**: 1.0
**日期**: 2026-01-24
**狀態**: 草稿
**作者**: Claude Code (Opus 4.5)

---

## 1. 問題陳述

### 1.1 觀察到的問題

| # | 問題 | 影響 |
|---|------|------|
| 1 | 麻醉 PWA 認領 E-CYL-002 (90%)，BioMed 顯示 H型2號 (100%) | 資料不一致，無法追蹤實際氧氣消耗 |
| 2 | 麻醉進行中，氧氣瓶 % 不會自動扣減 | 無法即時掌握剩餘氧氣量 |
| 3 | xIRS.Bus 應該同步但似乎沒有作用 | 跨 PWA 狀態不一致 |

### 1.2 根本原因分析

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 問題根因                                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. 顯示邏輯問題 (BioMed)                                                    │
│     ─────────────────────                                                    │
│     BioMed 使用 idx+1 作為「幾號」，而非實際 unit_serial                     │
│     當 unit_label 為空時，E型也會被顯示為 H型                                │
│                                                                              │
│  2. 資料流問題                                                               │
│     ─────────────────────                                                    │
│     麻醉認領 → 更新 equipment_units.claimed_by_case_id                       │
│     但 level_percent 需要手動 RESOURCE_CHECK 才會更新                        │
│     沒有自動扣減機制                                                         │
│                                                                              │
│  3. xIRS.Bus 架構問題                                                        │
│     ─────────────────────                                                    │
│     • RPi 本地: Bus 應用 BroadcastChannel 跨 tab 同步                        │
│     • Vercel Demo: Bus 是 stub，emit/on 都是空函數                           │
│     • 跨裝置: 需要 WebSocket 或 Server-Sent Events                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 現有架構

### 2.1 氧氣鋼瓶資料模型

```sql
-- equipment_units 表 (BioMed 維護)
CREATE TABLE equipment_units (
    id INTEGER PRIMARY KEY,
    equipment_id TEXT,          -- 'EMER-EQ-006' (E型) 或 'RESP-001' (H型)
    unit_serial TEXT,           -- 'O2E-006-01', 'O2H-001-02'
    unit_label TEXT,            -- 'E瓶 #1', 'H瓶 #2'
    level_percent INTEGER,      -- 0-100
    status TEXT,                -- 'AVAILABLE', 'IN_USE', 'EMPTY', 'MAINTENANCE'
    claimed_by_case_id TEXT,    -- 麻醉案例 ID (認領時設定)
    claimed_at DATETIME,
    claimed_by_user_id TEXT,
    last_check DATETIME,
    is_active INTEGER DEFAULT 1
);
```

### 2.2 麻醉氧氣追蹤 (Event Sourcing)

```
RESOURCE_CLAIM → RESOURCE_CHECK → RESOURCE_CHECK → ... → RESOURCE_RELEASE
     │                  │                │                      │
     ▼                  ▼                ▼                      ▼
  認領鋼瓶          記錄 PSI          記錄 PSI              釋放鋼瓶
  initial_psi      current_psi      current_psi           final_psi
  flow_rate_lpm    flow_rate_lpm    flow_rate_lpm         consumed_L
```

### 2.3 xIRS.Bus 設計 (理想狀態)

```
┌──────────────────┐     emit('oxygen:claimed')     ┌──────────────────┐
│   Anesthesia     │ ─────────────────────────────► │     BioMed       │
│      PWA         │                                │      PWA         │
└──────────────────┘                                └──────────────────┘
         │                                                   │
         │          BroadcastChannel (同裝置)                │
         │          或 WebSocket (跨裝置)                    │
         ▼                                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         xIRS.Bus                                      │
│  • emit(event, data): 發送事件                                        │
│  • on(event, callback): 監聽事件                                      │
│  • off(event, callback): 取消監聽                                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 解決方案

### 3.1 Phase 1: 修正顯示邏輯 (立即)

**目標**: BioMed 正確顯示鋼瓶序號

**變更**:
```javascript
// frontend/biomed/index.html - 修正第 548 行

// 舊邏輯 (錯誤)
x-text="unit.unit_label || (unit.equipment_name?.includes('E') ? 'E型' : 'H型') + (idx + 1) + '號'"

// 新邏輯 (正確)
x-text="unit.unit_label || unit.unit_serial || ('未命名 #' + unit.id)"
```

**驗收**: 認領 E-CYL-002，BioMed 顯示 "E瓶 #2" 或 "O2E-006-02"

### 3.2 Phase 2: 實作 xIRS.Bus 跨 Tab 同步 (短期)

**目標**: 同一裝置上的 Anesthesia 和 BioMed 即時同步

**實作**:
```javascript
// shared/sdk/xirs-bus.js

class XIRSBus {
    constructor() {
        this.channel = new BroadcastChannel('xirs-bus');
        this.listeners = new Map();

        this.channel.onmessage = (event) => {
            const { type, data } = event.data;
            const callbacks = this.listeners.get(type) || [];
            callbacks.forEach(cb => cb(data));
        };
    }

    emit(type, data) {
        // 本地通知
        const callbacks = this.listeners.get(type) || [];
        callbacks.forEach(cb => cb(data));

        // 跨 Tab 通知
        this.channel.postMessage({ type, data });
    }

    on(type, callback) {
        if (!this.listeners.has(type)) {
            this.listeners.set(type, []);
        }
        this.listeners.get(type).push(callback);
    }

    off(type, callback) {
        const callbacks = this.listeners.get(type) || [];
        const index = callbacks.indexOf(callback);
        if (index > -1) callbacks.splice(index, 1);
    }
}

window.xIRS = window.xIRS || {};
window.xIRS.Bus = new XIRSBus();
```

**事件定義**:
```javascript
// 麻醉認領氧氣瓶
xIRS.Bus.emit('oxygen:claimed', {
    case_id: 'ANES-001',
    unit_id: 123,
    unit_serial: 'O2E-006-02',
    level_percent: 90,
    flow_rate_lpm: 2.0,
    claimed_at: '2026-01-24T10:30:00Z'
});

// 麻醉釋放氧氣瓶
xIRS.Bus.emit('oxygen:released', {
    case_id: 'ANES-001',
    unit_id: 123,
    final_level_percent: 45,
    consumed_liters: 300
});

// 氧氣瓶狀態更新 (PSI Check)
xIRS.Bus.emit('oxygen:updated', {
    unit_id: 123,
    level_percent: 75,
    psi: 1650,
    flow_rate_lpm: 2.5
});
```

**BioMed 監聽**:
```javascript
// frontend/biomed/index.html

init() {
    // 監聽氧氣瓶事件
    if (window.xIRS?.Bus?.on) {
        xIRS.Bus.on('oxygen:claimed', (data) => {
            console.log('[BioMed] Oxygen claimed:', data);
            this.updateOxygenUnit(data.unit_id, {
                status: 'IN_USE',
                claimed_by_case_id: data.case_id
            });
        });

        xIRS.Bus.on('oxygen:released', (data) => {
            console.log('[BioMed] Oxygen released:', data);
            this.updateOxygenUnit(data.unit_id, {
                status: 'AVAILABLE',
                level_percent: data.final_level_percent,
                claimed_by_case_id: null
            });
        });

        xIRS.Bus.on('oxygen:updated', (data) => {
            this.updateOxygenUnit(data.unit_id, {
                level_percent: data.level_percent
            });
        });
    }
}
```

### 3.3 Phase 3: 氧氣自動扣減 (中期)

**目標**: 麻醉進行中，根據流量自動計算剩餘氧氣

**設計決策**:

| 選項 | 優點 | 缺點 | 建議 |
|------|------|------|------|
| A. 前端計時器 | 簡單，即時 | 關閉 tab 就停止 | ❌ |
| B. 後端定時任務 | 可靠 | 需要 cron job | ⚠️ |
| C. 查詢時計算 | 無需背景任務 | 只有查詢才更新 | ✅ 推薦 |

**選項 C 實作**:
```python
# routes/anesthesia.py

def calculate_current_level(unit_id: int, case_id: str) -> dict:
    """
    根據認領時間和流量，計算目前剩餘氧氣量

    公式:
    elapsed_minutes = now - claimed_at
    consumed_liters = elapsed_minutes × flow_rate_lpm
    remaining_liters = initial_liters - consumed_liters
    level_percent = remaining_liters / capacity_liters × 100
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 取得認領資訊
    cursor.execute("""
        SELECT eu.level_percent as initial_level,
               eu.claimed_at,
               e.capacity_liters
        FROM equipment_units eu
        JOIN equipment e ON eu.equipment_id = e.id
        WHERE eu.id = ? AND eu.claimed_by_case_id = ?
    """, (unit_id, case_id))

    unit = cursor.fetchone()
    if not unit or not unit['claimed_at']:
        return None

    # 取得最新流量
    cursor.execute("""
        SELECT payload FROM anesthesia_events
        WHERE case_id = ? AND event_type IN ('RESOURCE_CLAIM', 'RESOURCE_CHECK')
        ORDER BY clinical_time DESC LIMIT 1
    """, (case_id,))

    event = cursor.fetchone()
    payload = json.loads(event['payload']) if event else {}
    flow_rate = payload.get('flow_rate_lpm', 2.0)  # 預設 2 L/min

    # 計算已消耗量
    claimed_at = datetime.fromisoformat(unit['claimed_at'])
    elapsed_minutes = (datetime.now() - claimed_at).total_seconds() / 60

    initial_liters = (unit['initial_level'] / 100) * unit['capacity_liters']
    consumed_liters = elapsed_minutes * flow_rate
    remaining_liters = max(0, initial_liters - consumed_liters)

    current_level = int(remaining_liters / unit['capacity_liters'] * 100)

    return {
        'level_percent': current_level,
        'consumed_liters': round(consumed_liters, 1),
        'remaining_liters': round(remaining_liters, 1),
        'flow_rate_lpm': flow_rate,
        'elapsed_minutes': round(elapsed_minutes, 1)
    }
```

**API 端點**:
```python
@router.get("/api/v2/equipment/units/{unit_id}/live-status")
async def get_unit_live_status(unit_id: int):
    """取得單位即時狀態 (含自動扣減計算)"""

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM equipment_units WHERE id = ?
    """, (unit_id,))
    unit = cursor.fetchone()

    if not unit:
        raise HTTPException(404, "Unit not found")

    result = dict(unit)

    # 如果正在使用中，計算即時消耗
    if unit['claimed_by_case_id']:
        live = calculate_current_level(unit_id, unit['claimed_by_case_id'])
        if live:
            result['live_level_percent'] = live['level_percent']
            result['consumed_liters'] = live['consumed_liters']
            result['remaining_liters'] = live['remaining_liters']
            result['is_live_calculation'] = True

    return result
```

### 3.4 Phase 4: 跨裝置同步 (長期)

**目標**: 不同裝置 (iPad A, iPad B, RPi) 之間即時同步

**選項**:

| 方案 | 複雜度 | 即時性 | 離線支援 |
|------|--------|--------|----------|
| WebSocket | 高 | 即時 | 需重連邏輯 |
| Server-Sent Events | 中 | 即時 | 自動重連 |
| 輪詢 (Polling) | 低 | 延遲 | 簡單 |
| Event Sourcing + Sync | 高 | 最終一致 | 完整支援 |

**推薦**: Event Sourcing + Sync (與現有 Walkaway 架構一致)

```
┌────────────┐    ┌────────────┐    ┌────────────┐
│  iPad A    │    │  iPad B    │    │    RPi     │
│ Anesthesia │    │  BioMed    │    │   Hub      │
└─────┬──────┘    └─────┬──────┘    └─────┬──────┘
      │                 │                 │
      │  POST /events   │                 │
      │────────────────────────────────► │
      │                 │                 │
      │                 │  GET /events    │
      │                 │ ◄────────────── │
      │                 │  (polling or SSE)
      │                 │                 │
      ▼                 ▼                 ▼
  ┌─────────────────────────────────────────────┐
  │              events 表 (權威)                │
  │  event_type = 'OXYGEN_CLAIMED'              │
  │  entity_type = 'equipment_unit'             │
  │  entity_id = '123'                          │
  │  payload = { case_id, flow_rate_lpm, ... }  │
  └─────────────────────────────────────────────┘
```

---

## 4. 實作優先順序

| Phase | 工作項目 | 預估時間 | 優先級 |
|-------|----------|----------|--------|
| 1 | 修正 BioMed 顯示邏輯 | 30 分鐘 | P0 |
| 2a | 實作 xIRS.Bus (BroadcastChannel) | 2 小時 | P1 |
| 2b | Anesthesia emit 氧氣事件 | 1 小時 | P1 |
| 2c | BioMed 監聽並更新 UI | 1 小時 | P1 |
| 3 | 查詢時自動扣減計算 | 2 小時 | P2 |
| 4 | 跨裝置 Event Sync | 1 週 | P3 |

---

## 5. 驗收測試

### 5.1 Phase 1 驗收

| # | 測試 | 預期結果 |
|---|------|----------|
| 1.1 | 麻醉認領 E-CYL-002 | BioMed 顯示 "O2E-006-02" 或 "E瓶 #2" |
| 1.2 | 麻醉認領 H-CYL-003 | BioMed 顯示 "O2H-001-03" 或 "H瓶 #3" |

### 5.2 Phase 2 驗收

| # | 測試 | 預期結果 |
|---|------|----------|
| 2.1 | 同裝置開啟 Anesthesia + BioMed | BioMed 即時顯示認領狀態 |
| 2.2 | 麻醉認領後 BioMed 不重新整理 | 狀態自動更新為 "使用中" |
| 2.3 | 麻醉釋放後 BioMed 不重新整理 | 狀態自動更新為 "可用" |

### 5.3 Phase 3 驗收

| # | 測試 | 預期結果 |
|---|------|----------|
| 3.1 | 認領 90% 鋼瓶，流量 2 L/min，等 30 分鐘 | 顯示約 85% (消耗 60L / ~680L) |
| 3.2 | 查看 BioMed 韌性計算 | 使用 live_level_percent 計算 |

---

## 6. 開放問題

1. **Vercel Demo 如何處理?**
   - 選項 A: 繼續用 stub (不同步)
   - 選項 B: 用 localStorage 模擬
   - 選項 C: 用 Vercel KV 作為跨 tab 狀態

2. **流量預設值?**
   - 目前預設 2 L/min
   - 是否需要在認領時強制輸入?

3. **釋放時是否更新 equipment_units.level_percent?**
   - 目前只記錄在 events
   - 是否需要寫回 equipment_units 以便 BioMed 顯示?

---

## 7. 相關文件

- `DEV_SPEC_ANESTHESIA_PSI_TRACKING.md` - PSI 追蹤規格
- `DEV_SPEC_IMPLEMENTATION_DIRECTIVES_v1.0.md` - 實作指令書
- `PROGRESS_REPORT_WALKAWAY_v1.0.md` - Event Sourcing 進度

---

*xIRS Oxygen Tracking & Sync Specification v1.0*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
