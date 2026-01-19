# 麻醉 PWA 時間軸 UI 規格書

**版本**: v1.4
**日期**: 2026-01-20
**狀態**: Implemented
**更新**: v1.4 里程碑時間選擇器、平滑拖曳、iOS 修復

---

## 1. 概述

### 1.1 現況問題

目前麻醉 PWA 的里程碑輸入需要手動鍵入數字（分鐘），與其他 PWA 的按鈕式操作不一致，使用者體驗不佳。

### 1.2 設計目標

- 以「時間軸」作為主要 UI 架構
- 點擊時間點可開啟模態窗輸入詳細資訊
- 支援定時 Vital Signs 記錄
- 符合標準麻醉記錄單格式

---

## 2. UI 架構

### 2.1 時間軸主視圖

```
┌──────────────────────────────────────────────────────────┐
│  麻醉記錄 - 王大明 (M/45) - 股骨頸骨折 ORIF             │
│  ═══════════════════════════════════════════════════     │
│                                                          │
│  ┌─ 時間軸 ──────────────────────────────────────────┐   │
│  │                                                    │   │
│  │  09:00 ●──────●──────●──────●──────●──────●─ NOW  │   │
│  │        │      │      │      │      │      │       │   │
│  │     入OR   誘導  劃刀  主術  縫合  醒來         │   │
│  │                                                    │   │
│  │  [+5min] [+10min] [+15min] [+30min] [自訂]        │   │
│  │                                                    │   │
│  └────────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─ Vitals ──────────────────────────────────────────┐   │
│  │  HR │ 72  78  82  85  80  76  74                  │   │
│  │  BP │120/80  125/85  130/90  128/88  ...          │   │
│  │  SpO2│ 99  99  98  99  99  99  98                 │   │
│  │  ─────────────────────────────────────────────     │   │
│  │     09:00  09:15  09:30  09:45  10:00  10:15       │   │
│  └────────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─ 事件 ────────────────────────────────────────────┐   │
│  │  09:05 Propofol 150mg IV                          │   │
│  │  09:06 Fentanyl 100mcg IV                         │   │
│  │  09:08 Rocuronium 50mg IV                         │   │
│  │  09:10 Intubation ETT 7.5                         │   │
│  │  09:12 Sevoflurane 2% start                       │   │
│  │  ...                                              │   │
│  └────────────────────────────────────────────────────┘   │
│                                                          │
│  [記錄 Vitals]  [記錄用藥]  [記錄事件]  [里程碑]        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 2.2 時間軸元件結構

```html
<!-- 時間軸容器 -->
<div class="timeline-container">
    <!-- 刻度軸 -->
    <div class="timeline-ruler">
        <!-- 每 5 分鐘一個刻度 -->
        <div class="tick" data-time="09:00">09:00</div>
        <div class="tick minor" data-time="09:05"></div>
        <div class="tick" data-time="09:10">09:10</div>
        ...
    </div>

    <!-- 里程碑軌道 -->
    <div class="timeline-track milestones">
        <div class="milestone" data-type="OR_IN" style="left: 0%">
            <span class="dot"></span>
            <span class="label">入OR</span>
        </div>
        <div class="milestone" data-type="INDUCTION" style="left: 10%">
            <span class="dot"></span>
            <span class="label">誘導</span>
        </div>
        ...
    </div>

    <!-- Vitals 軌道 -->
    <div class="timeline-track vitals">
        <svg class="vitals-chart">
            <!-- HR 折線 -->
            <polyline class="hr-line" points="..."/>
            <!-- BP 範圍 -->
            <path class="bp-area" d="..."/>
        </svg>
    </div>

    <!-- 事件軌道 -->
    <div class="timeline-track events">
        <div class="event" data-type="MEDICATION" style="left: 5%">
            <span class="icon"><svg class="w-4 h-4"><use href="#heroicon-beaker"/></svg></span>
        </div>
        ...
    </div>

    <!-- 當前時間指示器 -->
    <div class="now-indicator"></div>
</div>
```

---

## 3. 互動設計

### 3.1 點擊時間軸

**點擊空白處** → 開啟「新增事件」模態窗

```
┌────────────────────────────────┐
│  新增事件 @ 09:23              │
│  ───────────────────────────── │
│                                │
│  時間: [09:23] [調整]          │
│                                │
│  類型:                         │
│  ○ 里程碑  ○ 用藥  ○ Vitals   │
│  ○ 處置    ○ 備註              │
│                                │
│  [取消]           [確認]       │
│                                │
└────────────────────────────────┘
```

### 3.2 點擊已存在的事件

**點擊里程碑/事件** → 開啟「編輯事件」模態窗

```
┌────────────────────────────────┐
│  編輯: 誘導 (INDUCTION)        │
│  ───────────────────────────── │
│                                │
│  時間: [09:08] [調整]          │
│                                │
│  備註:                         │
│  ┌────────────────────────┐    │
│  │ RSI, smooth induction  │    │
│  └────────────────────────┘    │
│                                │
│  [刪除]  [取消]  [儲存]        │
│                                │
└────────────────────────────────┘
```

### 3.3 快速新增按鈕

畫面底部的快速操作按鈕：

| 按鈕 | 動作 |
|------|------|
| 記錄 Vitals | 開啟 Vitals 輸入模態窗 |
| 記錄用藥 | 開啟用藥輸入模態窗（含常用藥物快選）|
| 記錄事件 | 開啟事件輸入模態窗 |
| 里程碑 | 開啟里程碑快選面板 |

### 3.4 里程碑快選面板

```
┌──────────────────────────────────────┐
│  選擇里程碑                          │
│  ────────────────────────────────── │
│                                      │
│  ┌──────┐  ┌──────┐  ┌──────┐       │
│  │ 入OR │  │ 誘導 │  │ 劃刀 │       │
│  └──────┘  └──────┘  └──────┘       │
│  ┌──────┐  ┌──────┐  ┌──────┐       │
│  │ 主術 │  │ 縫合 │  │ 醒來 │       │
│  └──────┘  └──────┘  └──────┘       │
│  ┌──────┐  ┌──────┐                 │
│  │ 拔管 │  │ 出OR │                 │
│  └──────┘  └──────┘                 │
│                                      │
│  時間: [現在] / [自訂: ____]        │
│                                      │
│  [取消]                    [確認]    │
│                                      │
└──────────────────────────────────────┘
```

---

## 4. Vitals 記錄

### 4.1 Vitals 輸入模態窗

```
┌────────────────────────────────────┐
│  記錄 Vitals @ 09:30               │
│  ─────────────────────────────────│
│                                    │
│  HR:   [  78  ] bpm               │
│  BP:   [ 125 ]/[  82 ] mmHg       │
│  SpO2: [  99  ] %                 │
│  EtCO2:[  35  ] mmHg              │
│  Temp: [ 36.5 ] °C                │
│                                    │
│  ┌─ 快速輸入 ─────────────────┐    │
│  │ [+10] [-10] HR              │    │
│  │ [+10] [-10] SBP             │    │
│  └─────────────────────────────┘    │
│                                    │
│  [取消]              [儲存]        │
│                                    │
└────────────────────────────────────┘
```

### 4.2 自動記錄提醒

可設定每 5/10/15 分鐘提醒記錄 Vitals：

```javascript
// 設定自動提醒
vitalsReminderInterval: 15,  // 分鐘
lastVitalsTime: null,

checkVitalsReminder() {
    if (this.lastVitalsTime) {
        const elapsed = (Date.now() - this.lastVitalsTime) / 60000;
        if (elapsed >= this.vitalsReminderInterval) {
            this.showVitalsReminder();
        }
    }
}
```

---

## 5. 資料結構

### 5.1 Event Sourcing 整合

所有時間軸事件都是 `anesthesia_events` 表的一部分：

```sql
-- 現有 anesthesia_events 表結構
CREATE TABLE anesthesia_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 見下方類型
    event_time INTEGER NOT NULL,
    data TEXT,  -- JSON
    recorded_by TEXT,
    recorded_at INTEGER DEFAULT (strftime('%s', 'now'))
);
```

### 5.2 事件類型

| event_type | 說明 | data 內容 |
|------------|------|-----------|
| `MILESTONE` | 里程碑 | `{"type": "INDUCTION", "notes": "..."}` |
| `VITALS` | 生命徵象 | `{"hr": 78, "sbp": 120, "dbp": 80, "spo2": 99, ...}` |
| `MEDICATION` | 用藥 | `{"drug": "Propofol", "dose": 150, "unit": "mg", "route": "IV"}` |
| `PROCEDURE` | 處置 | `{"type": "INTUBATION", "details": "ETT 7.5"}` |
| `NOTE` | 備註 | `{"text": "Patient movement"}` |
| `RESOURCE_CLAIM` | PSI 佔用 | `{"psi_id": "...", "action": "claim"}` |

### 5.3 前端資料模型

```javascript
timelineData: {
    case_id: 'ANES-20260107-001',
    start_time: '2026-01-07T09:00:00',

    milestones: [
        { type: 'OR_IN', time: '09:00', notes: '' },
        { type: 'INDUCTION', time: '09:08', notes: 'RSI' },
        // ...
    ],

    vitals: [
        { time: '09:00', hr: 72, sbp: 120, dbp: 80, spo2: 99 },
        { time: '09:15', hr: 78, sbp: 125, dbp: 85, spo2: 99 },
        // ...
    ],

    medications: [
        { time: '09:05', drug: 'Propofol', dose: 150, unit: 'mg', route: 'IV' },
        // ...
    ],

    events: [
        { time: '09:10', type: 'PROCEDURE', data: { type: 'INTUBATION', details: 'ETT 7.5' }},
        // ...
    ]
}
```

---

## 6. 時間軸渲染 (v1.2 重大修正)

### 6.1 時間模型 - 固定視窗 (Fixed Viewport)

> **[!]** **v1.2 Critical Fix**: 移除 `Date.now()` 作為座標系終點的錯誤設計

**錯誤的舊模型 (已廢棄):**
```javascript
// ❌ 錯誤：座標系會隨時間推進而重新縮放
// 導致舊事件點位「漂移」，無法信任視覺位置
timeToPosition(time) {
    const end = Date.now();  // 每次呼叫都變！
    return (time - start) / (end - start) * 100;
}
```

**正確的新模型 (v1.2):**
```javascript
// ✅ 正確：使用固定視窗 (Viewport)
// 每頁 = 1 小時 = 固定 3600000ms

viewport: {
    startTime: null,       // 當前視窗起始時間 (固定)
    endTime: null,         // 當前視窗結束時間 (固定)
    duration: 3600000,     // 1 小時 = 3600000ms
    pixelWidth: 720,       // 視窗像素寬度 (每分鐘 12px)
},

// 初始化視窗 (進入某小時頁面時呼叫)
setViewport(hourIndex) {
    const caseStart = this.caseStartTime;
    this.viewport.startTime = caseStart + (hourIndex * 3600000);
    this.viewport.endTime = this.viewport.startTime + 3600000;
},

// 時間 → 像素位置 (固定座標系)
timeToX(timestamp) {
    const elapsed = timestamp - this.viewport.startTime;
    const ratio = elapsed / this.viewport.duration;
    return Math.round(ratio * this.viewport.pixelWidth);
},

// 像素位置 → 時間
xToTime(x) {
    const ratio = x / this.viewport.pixelWidth;
    return this.viewport.startTime + (ratio * this.viewport.duration);
},

// 判斷時間是否在當前視窗內
isInViewport(timestamp) {
    return timestamp >= this.viewport.startTime &&
           timestamp < this.viewport.endTime;
}
```

### 6.2 NOW 指示器 (獨立於座標系)

```javascript
// NOW 是一個浮動指示器，不是座標系的 end
nowIndicator: {
    visible: true,
    position: 0,  // 像素位置
},

updateNowIndicator() {
    const now = Date.now();
    if (this.isInViewport(now)) {
        this.nowIndicator.visible = true;
        this.nowIndicator.position = this.timeToX(now);
    } else {
        this.nowIndicator.visible = false;
    }
},

// 每秒更新 NOW 位置
startNowTimer() {
    setInterval(() => this.updateNowIndicator(), 1000);
}
```

### 6.3 分頁作為主要互動模型

> **v1.2 設計原則**: 分頁是 canonical layout，縮放只在頁內發生

```javascript
// 分頁狀態
pagination: {
    currentHour: 0,           // 當前頁 (0-indexed)
    hoursPerPage: 1,          // 每頁 1 小時 (標準麻醉單格式)
    zoomLevel: 1,             // 頁內縮放 (1 = 正常, 2 = 放大)
    maxZoom: 2,               // 最大縮放 (每頁最多顯示 30 分鐘)
    minZoom: 1,               // 最小縮放 (每頁顯示 1 小時)
},

// 縮放只在頁內生效，不影響分頁邊界
zoomIn() {
    this.pagination.zoomLevel = Math.min(
        this.pagination.maxZoom,
        this.pagination.zoomLevel * 1.5
    );
    this.renderCurrentPage();
},

zoomOut() {
    this.pagination.zoomLevel = Math.max(
        this.pagination.minZoom,
        this.pagination.zoomLevel / 1.5
    );
    this.renderCurrentPage();
}
```

### 6.4 手勢支援

| 手勢 | 動作 | 說明 |
|------|------|------|
| 左右滑動 | 切換小時頁 | 主要導航方式 |
| 雙指縮放 | 頁內縮放 | 1x - 2x 範圍 |
| 長按 | 快速新增選單 | 在觸碰位置新增事件 |
| 點擊 NOW 按鈕 | 跳到當前小時 | 快速回到現在 |

---

## 7. Vitals 圖表 (v1.2 更新)

### 7.1 標準麻醉記錄單格式

麻醉記錄單的核心是**生命徵象趨勢圖 (Vital Signs Trend)**，採用國際標準符號：

```
符號標準 (Anesthesia Chart Symbols)
─────────────────────────────────
  V  = 收縮壓 (SBP)
  ^  = 舒張壓 (DBP)
  ●  = 心跳 (HR)
  ○  = 血氧 (SpO2)
  ×  = 呼吸次數 (RR)
```

> **[!]** **v1.2 設計原則**: 符號 + 形狀作為主要識別，顏色作為輔助 (Shape + Label Redundancy)

### 7.2 可主題化顏色系統 (Themable Colors)

> **xIRS 整合**: 繼承 `xirs-colors.css` 統一色彩系統，擴展麻醉專用變數

```css
/* 引入 xIRS 統一色彩 */
@import '/shared/xirs-ui/core/xirs-colors.css';

/* 麻醉專用變數 - 繼承 xIRS 顏色 */
:root {
    /* === Vital Signs === */
    --vital-sbp: var(--xirs-emergency);       /* #dc2626 紅色系 */
    --vital-dbp: var(--xirs-emergency);       /* #dc2626 同 SBP */
    --vital-hr: var(--xirs-role-doctor);      /* #2563eb 藍色系 */
    --vital-spo2: var(--xirs-success);        /* #10b981 綠色系 */
    --vital-rr: var(--xirs-role-anesthesia);  /* #7c3aed 紫色系 */

    /* === 警戒等級 (繼承 xIRS 狀態色) === */
    --vital-warning: var(--xirs-warning);     /* #f59e0b 黃 */
    --vital-critical: var(--xirs-emergency);  /* #dc2626 紅 */

    /* === 事件類型 === */
    --event-medication: var(--xirs-info);     /* #3b82f6 藍 */
    --event-procedure: var(--xirs-role-admin); /* #7c3aed 紫 */
    --event-milestone: var(--xirs-hirs-primary); /* #0d9488 青綠 */
    --event-stat: var(--xirs-priority-urgent); /* #dc2626 緊急紅 */

    /* === 網格與背景 === */
    --grid-line: var(--xirs-gray-200);        /* #e5e7eb */
    --text-muted: var(--xirs-gray-500);       /* #6b7280 */
}

/* 高對比主題 (無障礙) */
[data-theme="high-contrast"] {
    --vital-sbp: #ff0000;
    --vital-hr: #0000ff;
    --vital-spo2: #00ff00;
    --vital-rr: #ff00ff;
    --grid-line: #000000;
}
```

**xIRS 顏色對照表:**

| 用途 | 麻醉變數 | xIRS 變數 | 值 |
|------|---------|----------|-----|
| 血壓 | `--vital-sbp/dbp` | `--xirs-emergency` | #dc2626 |
| 心率 | `--vital-hr` | `--xirs-role-doctor` | #2563eb |
| 血氧 | `--vital-spo2` | `--xirs-success` | #10b981 |
| 呼吸 | `--vital-rr` | `--xirs-role-anesthesia` | #7c3aed |
| 警告 | `--vital-warning` | `--xirs-warning` | #f59e0b |
| 危急 | `--vital-critical` | `--xirs-emergency` | #dc2626 |

### 7.3 趨勢圖視覺設計

```
┌──────────────────────────────────────────────────────────────┐
│  mmHg/bpm                                                     │
│  200 ─┼─────────────────────────────────────────────────────  │
│       │                                                       │
│  180 ─┼─────────────────────────────────────────────────────  │
│       │                                                       │
│  160 ─┼─────────────────────────────────────────────────────  │
│       │                                                       │
│  140 ─┼───────V───────────────────V─────────────────────────  │
│       │      /│\                  │                           │
│  120 ─┼─────V─┼─V───V───V───V────V──V───V───────────────────  │ ← SBP (V)
│       │       │   \   \   /   \       \                       │
│  100 ─┼───────●───●───●───●────●──●────●────────────────────  │ ← HR (●)
│       │       │                                               │
│   80 ─┼───────^───^───^───^────^──^────^────────────────────  │ ← DBP (^)
│       │                                                       │
│   60 ─┼─────────────────────────────────────────────────────  │
│       │                                                       │
│   40 ─┼─────────────────────────────────────────────────────  │
│       │                                                       │
│   20 ─┼─────────────────────────────────────────────────────  │
│       │                                                       │
│    0 ─┼─────────────────────────────────────────────────────  │
│       └──┬──────┬──────┬──────┬──────┬──────┬──────┬────────  │
│        09:00  09:05  09:10  09:15  09:20  09:25  09:30        │
│                                                               │
│  ══════════════════════════════════════════════════════════  │
│  事件列 (Heroicons)：                                         │
│   09:05 [beaker] Propofol 150mg                              │
│   09:08 [arrow-down] Intubation ETT 7.5                      │
│   09:12 [cloud] Sevoflurane 2%                               │
└──────────────────────────────────────────────────────────────┘
```

### 7.4 渲染策略：Canvas + DOM 混合 (v1.2)

> **[!]** **v1.2 效能考量**: SVG polyline 在長手術 (每 5 分鐘一點 × 5 條線 × 10 小時 = 600+ 點) 會導致行動裝置效能下降

**推薦架構：**
```
┌─────────────────────────────────────────┐
│  Y-Axis Labels (DOM)                    │
├─────────────────────────────────────────┤
│  ┌───────────────────────────────────┐  │
│  │                                   │  │
│  │   Vitals Canvas (Canvas 2D)      │  │ ← 高效能繪圖
│  │   - Grid lines                    │  │
│  │   - SBP/DBP/HR/SpO2/RR points    │  │
│  │   - Trend lines                   │  │
│  │                                   │  │
│  └───────────────────────────────────┘  │
├─────────────────────────────────────────┤
│  Events Track (DOM + SVG Icons)         │ ← 可點擊互動
│  NOW Indicator (DOM)                    │ ← 獨立更新
├─────────────────────────────────────────┤
│  X-Axis Labels (DOM)                    │
└─────────────────────────────────────────┘
```

```javascript
// Canvas 繪圖器
class VitalsCanvasRenderer {
    constructor(canvasElement) {
        this.canvas = canvasElement;
        this.ctx = canvasElement.getContext('2d');
        this.dpr = window.devicePixelRatio || 1;
        this.setupHighDPI();
    }

    setupHighDPI() {
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = rect.width * this.dpr;
        this.canvas.height = rect.height * this.dpr;
        this.ctx.scale(this.dpr, this.dpr);
    }

    render(vitalsData, viewport) {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.drawGrid();
        this.drawVitals(vitalsData, viewport);
    }

    drawVitals(vitalsData, viewport) {
        // 只繪製當前視窗內的點
        const visibleVitals = vitalsData.filter(v =>
            v.time >= viewport.startTime && v.time < viewport.endTime
        );

        // 批量繪製每種類型
        this.drawVitalType(visibleVitals, 'SBP', 'V');
        this.drawVitalType(visibleVitals, 'DBP', '^');
        this.drawVitalType(visibleVitals, 'HR', '●');
        this.drawVitalType(visibleVitals, 'SpO2', '○');
    }
}
```

### 7.5 事件圖標：Heroicons (v1.2)

> **v1.2**: 使用 [Heroicons](https://heroicons.com/) 作為標準圖標庫，確保跨平台一致性

**圖標對照表：**

| 事件類型 | Heroicon 名稱 | 樣式 | 說明 |
|---------|---------------|------|------|
| 用藥 (Medication) | `beaker` | outline | 藥物給予 |
| 處置 (Procedure) | `wrench-screwdriver` | outline | 醫療處置 |
| 插管 (Intubation) | `arrow-down-on-square` | solid | 氣管內管 |
| 吸入麻醉 (Gas) | `cloud` | outline | 氣體麻醉劑 |
| 里程碑 (Milestone) | `flag` | solid | 手術階段 |
| 緊急 (STAT) | `bolt` | solid | 緊急用藥 |
| 備註 (Note) | `chat-bubble-left` | outline | 文字記錄 |

**使用方式 (Heroicons SVG)：**

```html
<!-- 方式 1: 直接嵌入 SVG (推薦，離線可用) -->
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
     stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
  <!-- beaker (用藥) -->
  <path stroke-linecap="round" stroke-linejoin="round"
        d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23-.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
</svg>

<!-- 方式 2: Tailwind CSS + heroicons (需要 npm 安裝) -->
<!-- npm install @heroicons/react -->
<script>
import { BeakerIcon, WrenchScrewdriverIcon, CloudIcon } from '@heroicons/react/24/outline';
import { BoltIcon, FlagIcon } from '@heroicons/react/24/solid';
</script>
```

**事件圖標 CSS 類別：**

```css
/* 事件圖標容器 */
.event-icon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
}

/* 圖標顏色 (使用 CSS 變數) */
.event-icon--medication { color: var(--event-medication, #3b82f6); }
.event-icon--procedure  { color: var(--event-procedure, #8b5cf6); }
.event-icon--milestone  { color: var(--event-milestone, #14b8a6); }
.event-icon--stat       { color: var(--vital-critical, #dc2626); }
.event-icon--note       { color: var(--text-muted, #6b7280); }
```

### 7.6 SVG 網格實作 (輕量 DOM)

```html
<div class="vitals-canvas-container">
    <!-- Y軸標籤 -->
    <div class="y-axis">
        <span>200</span>
        <span>160</span>
        <span>120</span>
        <span>80</span>
        <span>40</span>
        <span>0</span>
    </div>

    <!-- 主繪圖區 -->
    <svg class="vitals-canvas" viewBox="0 0 720 300" preserveAspectRatio="none">
        <!-- 網格線 -->
        <defs>
            <pattern id="grid" width="60" height="30" patternUnits="userSpaceOnUse">
                <path d="M 60 0 L 0 0 0 30" fill="none" stroke="#e5e7eb" stroke-width="0.5"/>
            </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)"/>

        <!-- SBP 折線 (V 符號) -->
        <g class="sbp-layer">
            <polyline class="sbp-line" points="..." fill="none" stroke="#dc2626" stroke-width="1.5"/>
            <!-- V 符號標記 -->
            <text x="60" y="90" class="vital-symbol sbp">V</text>
            <text x="120" y="85" class="vital-symbol sbp">V</text>
            ...
        </g>

        <!-- DBP 折線 (^ 符號) -->
        <g class="dbp-layer">
            <polyline class="dbp-line" points="..." fill="none" stroke="#dc2626" stroke-width="1"/>
            <text x="60" y="165" class="vital-symbol dbp">^</text>
            ...
        </g>

        <!-- HR 折線 (● 符號) -->
        <g class="hr-layer">
            <polyline class="hr-line" points="..." fill="none" stroke="#2563eb" stroke-width="1.5"/>
            <circle cx="60" cy="150" r="4" fill="#2563eb"/>
            <circle cx="120" cy="145" r="4" fill="#2563eb"/>
            ...
        </g>

        <!-- SpO2 (○ 符號) - 頂部區域 -->
        <g class="spo2-layer">
            <polyline class="spo2-line" points="..." fill="none" stroke="#16a34a" stroke-width="1"/>
            <circle cx="60" cy="15" r="3" fill="none" stroke="#16a34a"/>
            ...
        </g>

        <!-- 事件標記 (垂直線 + 圖標) -->
        <g class="events-layer">
            <line x1="60" y1="0" x2="60" y2="300" stroke="#f59e0b" stroke-width="1" stroke-dasharray="4"/>
            <use href="#heroicon-beaker" x="52" y="280" width="16" height="16"/>
        </g>
    </svg>

    <!-- X軸時間標籤 -->
    <div class="x-axis">
        <span>09:00</span>
        <span>09:05</span>
        <span>09:10</span>
        ...
    </div>
</div>
```

### 7.4 座標轉換函數

```javascript
// Y軸：0-220 mmHg/bpm -> SVG 0-300px (倒置)
valueToY(value, maxValue = 220) {
    return 300 - (value / maxValue) * 300;
}

// X軸：時間 -> SVG 像素 (每分鐘 12px)
timeToX(time) {
    const elapsed = (time - this.hourStartTime) / 60000; // 分鐘數
    return elapsed * 12; // 每分鐘 12px = 1小時 720px
}

// 繪製 Vitals 點
plotVital(time, type, value) {
    const x = this.timeToX(time);
    const y = this.valueToY(value);
    const symbol = this.getSymbol(type);

    // 根據類型繪製不同符號
    switch(type) {
        case 'SBP':
            this.drawText(x, y, 'V', '#dc2626');
            break;
        case 'DBP':
            this.drawText(x, y, '^', '#dc2626');
            break;
        case 'HR':
            this.drawCircle(x, y, 4, '#2563eb', true);
            break;
        case 'SpO2':
            this.drawCircle(x, y, 3, '#16a34a', false);
            break;
        case 'RR':
            this.drawText(x, y, '×', '#7c3aed');
            break;
    }
}
```

### 7.5 異常值警示

```javascript
// 異常值定義
VITAL_LIMITS: {
    HR:   { low: 50,  high: 120, critical_low: 40,  critical_high: 150 },
    SBP:  { low: 90,  high: 160, critical_low: 70,  critical_high: 200 },
    DBP:  { low: 50,  high: 100, critical_low: 40,  critical_high: 120 },
    SpO2: { low: 94,  high: 100, critical_low: 90,  critical_high: 100 },
    RR:   { low: 10,  high: 24,  critical_low: 8,   critical_high: 30 }
},

// 檢查異常並標色
getVitalColor(type, value) {
    const limits = this.VITAL_LIMITS[type];
    if (value <= limits.critical_low || value >= limits.critical_high) {
        return '#dc2626';  // 紅色 - 危急
    }
    if (value <= limits.low || value >= limits.high) {
        return '#f59e0b';  // 黃色 - 警告
    }
    return this.DEFAULT_COLORS[type];  // 正常顏色
}
```

---

## 8. 標準里程碑

### 8.1 全身麻醉 (GA)

| 順序 | 代碼 | 中文 | 英文 |
|:----:|------|------|------|
| 1 | OR_IN | 入OR | OR In |
| 2 | INDUCTION | 誘導 | Induction |
| 3 | INTUBATION | 插管 | Intubation |
| 4 | INCISION | 劃刀 | Incision |
| 5 | MAIN_PROCEDURE | 主術 | Main Procedure |
| 6 | CLOSURE | 縫合 | Closure |
| 7 | EMERGENCE | 醒來 | Emergence |
| 8 | EXTUBATION | 拔管 | Extubation |
| 9 | OR_OUT | 出OR | OR Out |

### 8.2 區域麻醉 (RA)

| 順序 | 代碼 | 中文 |
|:----:|------|------|
| 1 | OR_IN | 入OR |
| 2 | BLOCK_START | 開始阻斷 |
| 3 | BLOCK_COMPLETE | 阻斷完成 |
| 4 | INCISION | 劃刀 |
| 5 | MAIN_PROCEDURE | 主術 |
| 6 | CLOSURE | 縫合 |
| 7 | OR_OUT | 出OR |

---

## 9. 庫存與計費連動 (v1.2 Event Sourcing 模型)

### 9.1 設計理念

> **「麻醉醫師只管救人，系統自動算錢與庫存」**

當麻醉師在時間軸上記錄用藥事件，系統自動完成：
1. MIRS 庫存消費事件
2. CashDesk 計費事件
3. 管制藥品雙重驗證

### 9.2 Event Sourcing 架構 (v1.2 核心變更)

> **[!]** **v1.2 Critical**: 所有操作都是**不可變事件 (Immutable Events)**，禁止直接修改/刪除

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Event Sourcing 資料流                             │
│                                                                     │
│   ┌──────────────┐                                                  │
│   │ Anes PWA     │                                                  │
│   │ 記錄給藥     │                                                  │
│   └──────┬───────┘                                                  │
│          │                                                          │
│          ▼                                                          │
│   ┌──────────────────────────────────────────────────────────────┐ │
│   │  MedicationAdministeredEvent (不可變)                         │ │
│   │  ─────────────────────────────────────────────────────────── │ │
│   │  event_id: "EVT-20260119-001" (冪等鍵)                       │ │
│   │  case_id: "ANES-001"                                         │ │
│   │  drug_code: "PROP-200"                                       │ │
│   │  dose: 200, unit: "mg", route: "IV"                          │ │
│   │  lot_number: "LOT-2026-001" (管制藥必填)                     │ │
│   │  expiry_date: "2026-06-30" (管制藥必填)                      │ │
│   │  performed_by: "DR-WANG"                                     │ │
│   │  performed_at: 1705654800000                                 │ │
│   │  witness_by: "NS-LEE" (管制藥必填)                           │ │
│   └──────────────────────────────────────────────────────────────┘ │
│          │                                                          │
│          │ Event 觸發 (每個事件只被消費一次)                         │
│          ├─────────────────────────┬────────────────────────────┐  │
│          ▼                         ▼                            ▼  │
│   ┌─────────────┐          ┌─────────────┐          ┌─────────────┐│
│   │ Inventory   │          │ Billing     │          │ Audit       ││
│   │ Consumer    │          │ Consumer    │          │ Consumer    ││
│   └─────────────┘          └─────────────┘          └─────────────┘│
│          │                         │                            │  │
│          ▼                         ▼                            ▼  │
│   ┌─────────────┐          ┌─────────────┐          ┌─────────────┐│
│   │ Inventory   │          │ Billing     │          │ Audit       ││
│   │ ConsumedEvt │          │ ChargeEvt   │          │ LogEvent    ││
│   └─────────────┘          └─────────────┘          └─────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### 9.3 事件結構定義

#### 9.3.1 MedicationAdministeredEvent (給藥事件)

```typescript
interface MedicationAdministeredEvent {
    // === 冪等性 ===
    event_id: string;           // UUID，前端生成，確保重試不重複
    idempotency_key: string;    // 同上，API 層使用

    // === 病例關聯 ===
    case_id: string;
    patient_id: string;

    // === 藥物資訊 ===
    drug_code: string;          // 對應 pharmacy_items.item_code
    drug_name: string;
    dose: number;
    unit: string;               // mg, mcg, ml, etc.
    route: string;              // IV, IM, PO, INH, SC, etc.

    // === 管制藥品必填欄位 ===
    lot_number?: string;        // 批號 (管制藥必填)
    expiry_date?: string;       // 效期 (管制藥必填)
    witness_by?: string;        // 見證人 (管制藥必填)

    // === 執行資訊 ===
    performed_by: string;       // 執行者 ID
    performed_at: number;       // 執行時間 (timestamp)
    recorded_at: number;        // 記錄時間 (timestamp)

    // === 狀態標記 ===
    is_stat: boolean;           // 緊急用藥
    is_controlled: boolean;     // 管制藥品
}
```

#### 9.3.2 MedicationReversedEvent (撤銷事件)

> **[!]** **v1.2**: 不使用 DELETE，改用補償事件 (Compensating Event)

```typescript
interface MedicationReversedEvent {
    event_id: string;           // 新的事件 ID
    original_event_id: string;  // 被撤銷的事件 ID
    case_id: string;

    // === 撤銷資訊 ===
    reversal_reason: string;    // 必填：為什麼撤銷
    reversal_type: 'ERROR' | 'DUPLICATE' | 'NOT_GIVEN' | 'OTHER';

    // === 執行資訊 ===
    reversed_by: string;
    reversed_at: number;
    witness_by?: string;        // 管制藥品撤銷也需要見證
}
```

### 9.4 API 設計 (v1.2)

#### 9.4.1 新增用藥事件 (Idempotent)

```javascript
// POST /api/anesthesia/events/medication
// Header: X-Idempotency-Key: {client-generated-uuid}

async recordMedication(caseId, medication) {
    const eventId = xIRS.API.generateIdempotencyKey();

    const payload = {
        event_id: eventId,
        case_id: caseId,
        drug_code: medication.drugCode,
        drug_name: medication.drugName,
        dose: medication.dose,
        unit: medication.unit,
        route: medication.route,
        performed_at: medication.time,

        // 管制藥品必填
        lot_number: medication.lotNumber || null,
        expiry_date: medication.expiryDate || null,
        witness_by: medication.witnessId || null,

        is_stat: medication.isStat || false,
        is_controlled: medication.isControlled || false
    };

    const response = await xIRS.API.post(
        '/api/anesthesia/events/medication',
        payload,
        { idempotencyKey: eventId }
    );

    // 回應
    // {
    //     event_id: "EVT-20260119-001",
    //     status: "RECORDED",
    //     downstream_events: {
    //         inventory_consumed_event_id: "INV-EVT-001",
    //         billing_charge_event_id: "BL-EVT-001"
    //     }
    // }
}
```

#### 9.4.2 撤銷用藥事件 (Compensating Event)

```javascript
// POST /api/anesthesia/events/medication/reverse
// 注意：是 POST 不是 DELETE

async reverseEvent(originalEventId, reason, reversalType) {
    const payload = {
        original_event_id: originalEventId,
        reversal_reason: reason,
        reversal_type: reversalType,  // 'ERROR' | 'DUPLICATE' | 'NOT_GIVEN' | 'OTHER'
        witness_by: this.currentWitness || null
    };

    const response = await xIRS.API.post(
        '/api/anesthesia/events/medication/reverse',
        payload
    );

    // 回應
    // {
    //     reversal_event_id: "REV-EVT-001",
    //     original_event_id: "EVT-20260119-001",
    //     status: "REVERSED",
    //     downstream_events: {
    //         inventory_restored_event_id: "INV-EVT-002",
    //         billing_void_event_id: "BL-EVT-002"
    //     }
    // }

    // 原始事件保留在 event stream 中，只是被標記為已撤銷
}
```

### 9.4 管制藥品處理

管制藥品 (Controlled Drugs) 需要額外驗證：

```javascript
// 管制藥品類別
CONTROLLED_DRUG_CLASSES: {
    'CLASS_1': ['Morphine', 'Fentanyl', 'Pethidine'],
    'CLASS_2': ['Ketamine', 'Midazolam'],
    'CLASS_3': ['Diazepam', 'Lorazepam']
},

// UI：管制藥品紅框標示
isControlledDrug(drugCode) {
    const drugInfo = this.drugDatabase.find(d => d.code === drugCode);
    return drugInfo?.controlled_class != null;
}

// UI：新增管制藥品需要確認
async addControlledDrugEvent(medication) {
    const confirmed = await this.showConfirmDialog({
        title: '**[!]** 管制藥品確認',
        message: `即將記錄 ${medication.drugName} ${medication.dose}${medication.unit}`,
        confirmText: '確認無誤',
        cancelText: '取消',
        requireDoubleCheck: true  // 需要勾選確認框
    });

    if (confirmed) {
        await this.recordMedication(this.caseId, medication);
    }
}
```

### 9.5 用藥選單設計

```
┌────────────────────────────────────────┐
│  記錄用藥 @ 09:15                       │
│  ─────────────────────────────────────│
│                                        │
│  ┌─ 常用藥物 ──────────────────────┐   │
│  │  [Propofol]  [Fentanyl]         │   │
│  │  [Rocuronium] [Sevoflurane]     │   │
│  │  [Midazolam]  [Ketamine] **[!]**     │   │
│  └──────────────────────────────────┘   │
│                                        │
│  藥物: [Propofol           ▼]          │
│  劑量: [200    ] [mg  ▼]               │
│  途徑: [IV     ▼]                      │
│                                        │
│  ┌─ 庫存資訊 ────────────────────┐     │
│  │  現有庫存: 8 支                │     │
│  │  批號: LOT-2026-001           │     │
│  │  效期: 2026-06-30             │     │
│  └────────────────────────────────┘     │
│                                        │
│  [取消]              [記錄用藥]        │
└────────────────────────────────────────┘
```

### 9.6 計費項目對照表

| 麻醉藥物 | drug_code | 對應 pricebook item_code | 健保點數 |
|---------|-----------|-------------------------|---------|
| Propofol 200mg | PROP-200 | MED-PROP-200 | 150 |
| Fentanyl 100mcg | FENT-100 | MED-FENT-100 | 85 |
| Rocuronium 50mg | ROCU-50 | MED-ROCU-50 | 280 |
| Sevoflurane (per hr) | SEVO-HR | MED-SEVO-HR | 450 |
| Ketamine 100mg | KET-100 | MED-KET-100 | 120 |

---

## 10. 分頁與捲動機制 (v1.1 新增)

### 10.1 設計原則

標準麻醉紀錄單一張紙約 1-2 小時。針對長時間手術 (8-12 小時)，採用**分頁機制**而非無限捲動。

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  ◀ 第 2 小時 (09:00 - 10:00)                    ▶      │
│    ════════════════════════════════════════════         │
│                                                         │
│  [01] [02] [03] [04] [05] [06] [07] [08] ... [現在]    │
│                                                         │
│  ┌───────────────────────────────────────────────┐     │
│  │                                               │     │
│  │           (Vitals 趨勢圖)                     │     │
│  │                                               │     │
│  └───────────────────────────────────────────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 10.2 分頁狀態管理

```javascript
pagination: {
    hourDuration: 60,              // 每頁顯示 60 分鐘
    currentHour: 0,                // 當前顯示的小時索引 (0 = 第一小時)
    totalHours: 1,                 // 總手術時數
    caseStartTime: null,           // 手術開始時間
},

// 計算總頁數
get totalPages() {
    const elapsed = Date.now() - this.pagination.caseStartTime;
    return Math.ceil(elapsed / (60 * 60 * 1000));
},

// 切換到指定小時
goToHour(hourIndex) {
    this.pagination.currentHour = Math.max(0, Math.min(hourIndex, this.totalPages - 1));
    this.renderCurrentHour();
},

// 前一小時
prevHour() {
    if (this.pagination.currentHour > 0) {
        this.goToHour(this.pagination.currentHour - 1);
    }
},

// 下一小時
nextHour() {
    if (this.pagination.currentHour < this.totalPages - 1) {
        this.goToHour(this.pagination.currentHour + 1);
    }
},

// 跳到「現在」
goToNow() {
    this.goToHour(this.totalPages - 1);
}
```

### 10.3 小時選擇器 UI

```html
<!-- 小時選擇器 -->
<div class="hour-selector flex items-center gap-2 p-2 bg-gray-100">
    <button @click="prevHour()" :disabled="pagination.currentHour === 0"
            class="p-2 rounded-lg hover:bg-gray-200 disabled:opacity-50">
        ◀
    </button>

    <div class="flex-1 flex items-center justify-center gap-1 overflow-x-auto">
        <template x-for="hour in totalPages" :key="hour">
            <button @click="goToHour(hour - 1)"
                    :class="pagination.currentHour === hour - 1 ? 'bg-blue-600 text-white' : 'bg-white'"
                    class="w-8 h-8 rounded-full text-sm font-medium">
                <span x-text="hour"></span>
            </button>
        </template>
    </div>

    <button @click="nextHour()" :disabled="pagination.currentHour >= totalPages - 1"
            class="p-2 rounded-lg hover:bg-gray-200 disabled:opacity-50">
        ▶
    </button>

    <button @click="goToNow()" class="px-3 py-1 bg-red-600 text-white rounded-lg text-sm">
        現在
    </button>
</div>
```

### 10.4 手勢支援

```javascript
// Touch 手勢：左右滑動切換小時
initSwipeGesture() {
    let startX = 0;
    const container = this.$refs.timelineContainer;

    container.addEventListener('touchstart', (e) => {
        startX = e.touches[0].clientX;
    });

    container.addEventListener('touchend', (e) => {
        const endX = e.changedTouches[0].clientX;
        const diff = endX - startX;

        if (Math.abs(diff) > 50) {  // 滑動超過 50px
            if (diff > 0) {
                this.prevHour();  // 右滑 → 前一小時
            } else {
                this.nextHour();  // 左滑 → 下一小時
            }
        }
    });
}
```

---

## 11. 緊急操作 (v1.1 新增)

### 11.1 Code Blue / Stat 按鈕

緊急情況下，醫師無法慢慢填表單。提供一鍵記錄功能：

```html
<!-- 緊急按鈕 (常駐於畫面右下角) -->
<div class="fixed bottom-20 right-4 z-50">
    <button @click="showStatMenu = true"
            class="w-14 h-14 rounded-full bg-red-600 text-white shadow-lg
                   flex items-center justify-center text-2xl
                   active:scale-95 transition-transform">
        ⚡
    </button>
</div>

<!-- Stat 快選選單 -->
<div x-show="showStatMenu" x-cloak
     class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
    <div class="bg-white rounded-2xl p-6 max-w-sm w-full mx-4">
        <h3 class="text-lg font-bold text-red-600 mb-4">⚡ 緊急用藥</h3>

        <div class="grid grid-cols-2 gap-3">
            <button @click="statDrug('Epinephrine', 1, 'mg')"
                    class="p-4 bg-red-100 text-red-800 rounded-xl font-bold">
                Epinephrine 1mg
            </button>
            <button @click="statDrug('Atropine', 0.5, 'mg')"
                    class="p-4 bg-red-100 text-red-800 rounded-xl font-bold">
                Atropine 0.5mg
            </button>
            <button @click="statDrug('Ephedrine', 10, 'mg')"
                    class="p-4 bg-amber-100 text-amber-800 rounded-xl font-bold">
                Ephedrine 10mg
            </button>
            <button @click="statDrug('Phenylephrine', 100, 'mcg')"
                    class="p-4 bg-amber-100 text-amber-800 rounded-xl font-bold">
                Neo 100mcg
            </button>
        </div>

        <button @click="showStatMenu = false"
                class="w-full mt-4 py-3 bg-gray-200 rounded-xl">
            取消
        </button>
    </div>
</div>
```

### 11.2 Stat 用藥函數

```javascript
// 一鍵記錄緊急用藥 (時間 = 現在)
async statDrug(drugName, dose, unit) {
    const now = Date.now();

    // 直接記錄，跳過確認對話框
    await this.recordMedication(this.caseId, {
        time: now,
        drugCode: this.getDrugCode(drugName),
        drugName: drugName,
        dose: dose,
        unit: unit,
        route: 'IV',
        isStat: true  // 標記為緊急用藥
    });

    this.showStatMenu = false;

    // 震動回饋 (如果支援)
    if (navigator.vibrate) {
        navigator.vibrate(100);
    }

    // Toast 通知
    XIRS_TOAST.success(`已記錄 ${drugName} ${dose}${unit}`);
}
```

---

## 12. CSS 樣式

```css
/* 時間軸容器 */
.timeline-container {
    position: relative;
    width: 100%;
    height: 200px;
    overflow-x: auto;
    overflow-y: hidden;
}

/* 刻度軸 */
.timeline-ruler {
    display: flex;
    height: 24px;
    border-bottom: 1px solid #e5e7eb;
}

.timeline-ruler .tick {
    position: absolute;
    font-size: 10px;
    color: #6b7280;
}

.timeline-ruler .tick.minor::before {
    content: '';
    position: absolute;
    bottom: 0;
    width: 1px;
    height: 4px;
    background: #d1d5db;
}

/* 里程碑 */
.milestone {
    position: absolute;
    display: flex;
    flex-direction: column;
    align-items: center;
    cursor: pointer;
}

.milestone .dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #14b8a6;
    border: 2px solid white;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.milestone .label {
    font-size: 10px;
    margin-top: 4px;
    white-space: nowrap;
}

/* 事件標記 */
.event {
    position: absolute;
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    cursor: pointer;
}

/* 當前時間指示器 */
.now-indicator {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: #ef4444;
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
```

---

## 13. 實作計畫 (v1.1 更新)

### Phase 1: 基礎時間軸
1. 時間軸容器 + 刻度軸
2. 里程碑顯示
3. 點擊里程碑編輯

### Phase 2: Vitals 趨勢圖 * (v1.1)
1. SVG Canvas 網格繪製
2. 標準符號 (V/^/●/○/×) 繪製
3. 異常值自動標色
4. X軸與時間軸同步捲動

### Phase 3: 事件記錄
1. 新增事件模態窗
2. Vitals 輸入模態窗
3. 用藥輸入模態窗（含常用藥物快選）

### Phase 4: 庫存與計費連動 * (v1.1)
1. MIRS 庫存扣減 API
2. CashDesk 計費項目生成
3. 管制藥品雙重驗證
4. 事件刪除 → 庫存回補

### Phase 5: 分頁與 UX * (v1.1)
1. 每小時分頁顯示
2. 小時選擇器 UI
3. 左右滑動手勢
4. Code Blue / Stat 緊急按鈕

### Phase 6: 進階功能
1. 自動 Vitals 提醒
2. 列印/匯出
3. 離線支援

---

## 14. 未決問題

- [x] ~~Vitals 異常值是否自動標紅？~~ → v1.1 已定義
- [ ] 時間軸是否需要垂直模式（手機直式）？
- [ ] 是否需要語音輸入？
- [ ] 離線時的時間同步策略？
- [ ] 與 CIRS 病歷的整合方式？

---

## 15. 系統整合關係圖

```
┌─────────────────────────────────────────────────────────────────┐
│                         xIRS 系統整合                            │
│                                                                 │
│   ┌───────────┐                                                 │
│   │ Anes PWA  │ ──────────────────────────────────────────┐    │
│   │ 時間軸 UI  │                                           │    │
│   └─────┬─────┘                                           │    │
│         │                                                  │    │
│         │ 用藥事件                                         │    │
│         ▼                                                  ▼    │
│   ┌───────────┐     ┌───────────┐     ┌───────────┐           │
│   │   MIRS    │────▶│ Pharmacy  │────▶│ CashDesk  │           │
│   │  Backend  │     │ Inventory │     │  Billing  │           │
│   └───────────┘     └───────────┘     └───────────┘           │
│         │                                    │                 │
│         │                                    │                 │
│         ▼                                    ▼                 │
│   ┌───────────┐                       ┌───────────┐           │
│   │   CIRS    │◄──────────────────────│  Handoff  │           │
│   │  病歷系統  │   Handoff Package     │  Package  │           │
│   └───────────┘                       └───────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 |
| v1.1 | 2026-01-19 | 新增：(1) 標準麻醉記錄單趨勢圖 (V/^/●/○ 符號) (2) 庫存與計費連動 API (3) 分頁機制 (每小時一頁) (4) Code Blue 緊急按鈕 (5) 管制藥品處理流程 |
| v1.2 | 2026-01-19 | **Critical Fixes** (Based on ChatGPT review)：(1) 時間模型改為固定視窗 (Fixed Viewport)，移除 Date.now() 作為座標系終點的錯誤 (2) 分頁作為主要互動模型 (canonical layout) (3) Vitals 渲染改用 Canvas + DOM 混合架構 (4) 事件圖標改用 SVG，禁止 Emoji (5) 顏色系統改為 CSS 變數可主題化 (6) 庫存連動改為 Event Sourcing 模型，用補償事件取代 DELETE (7) 給藥事件加入冪等性、批號效期、見證人欄位 |
| v1.3 | 2026-01-20 | 列表視圖設為預設、時間軸視圖切換按鈕 |
| v1.4 | 2026-01-20 | **UX 改進**：(1) 里程碑記錄改為兩步驟流程：選擇類型 → 確認/調整時間 (2) 時間偏移選擇器：現在/-1分/-3分/-5分/自訂，>5分需填遲補原因 (3) 平滑拖曳時間軸 (touchmove/mousemove)，取代僅小時跳轉 (4) iOS Safari NOW 指示器修復 (-webkit-transform、獨立 label 元素) (5) 圖表視圖改回預設 (符合傳統麻醉記錄習慣) (6) 事件類型顯示中文化 (生命徵象/給藥/里程碑) |
