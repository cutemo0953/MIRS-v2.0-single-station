# MIRS 麻醉紀錄 - IV/Foley 管理模組規格書

**版本**: 2.3
**日期**: 2026-01-24
**狀態**: 已整合至 MIRS
**審閱者**: 麻醉護理師, Gemini, ChatGPT
**檔案**: `/routes/anesthesia.py`

---

## 0. 摘要

本規格書定義 MIRS 麻醉 PWA 的 **IV 管路管理** 與 **監測器 (Foley/保溫毯)** 功能，對標**烏日林新醫院麻醉紀錄單 (M0073)**。

### 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-01-23 | 初版 - 根據護理師回饋新增 IV 管理、Foley、加溫毯欄位 |
| 1.1 | 2026-01-23 | **重大修正** - 整合 Gemini/ChatGPT 批評：<br>• case_id 改 UUIDv7 + case_code<br>• 移除所有 AUTOINCREMENT identity<br>• IV_lines/monitors 定義為可重建投影<br>• FLUID_GIVEN 必須帶 line_id<br>• 新增 ts_device/ts_server/hlc 時間戳<br>• 新增 Foley 尿量累計邏輯<br>• 新增 End Case 強制收斂 |
| 2.1 | 2026-01-23 | **整合至 MIRS** - 移自 CIRS 並整合到 MIRS 麻醉模組：<br>• 新增 `anesthesia_iv_lines` 資料表<br>• 新增 `anesthesia_monitors` 資料表<br>• 新增 `anesthesia_urine_outputs` 資料表<br>• 新增 11 個 API endpoints<br>• 新增 I/O Balance 計算端點 |
| 2.2 | 2026-01-24 | **PDF 輸出完成** - 完整實作麻醉紀錄 PDF 輸出功能：<br>• 實作 M0073 格式 PDF 生成<br>• Jinja2 + WeasyPrint 渲染流程<br>• SVG 生命徵象圖表 (Vercel 相容)<br>• Matplotlib 圖表 (本地/RPi5)<br>• 3 欄佈局：藥物 / 圖表+表格 / 監測面板<br>• 自動分頁 (每頁 24 筆 vitals)<br>• 示範資料生成器 (seeder_demo.py)<br>• 前端預覽/下載雙模式 |
| 2.3 | 2026-01-24 | **Lab/ABG 輸入功能** - 新增術中檢驗資料輸入與顯示：<br>• 前端 Lab Modal：支援 ABG/VBG/POC Hb/Glucose/ACT<br>• ABG 完整欄位：pH, PaO2, PaCO2, HCO3, BE, SaO2<br>• 電解質欄位：Na, K, Ca, Glucose<br>• 血液學欄位：Hb, Hct<br>• PDF Lab 表格擴充：從 4 欄位擴充至 11 欄位<br>• Seeder 新增 3 筆 ABG 測試資料 |

### 新增 API 端點 (v2.1)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/cases/{id}/iv-lines` | 插入 IV 管路 |
| GET | `/cases/{id}/iv-lines` | 取得 IV 管路列表 |
| PATCH | `/cases/{id}/iv-lines/{line_id}` | 更新 IV (滴速/移除) |
| POST | `/cases/{id}/iv-lines/{line_id}/fluids` | 經 IV 給予輸液 |
| POST | `/cases/{id}/monitors` | 啟動監測器 |
| GET | `/cases/{id}/monitors` | 取得監測器列表 |
| DELETE | `/cases/{id}/monitors/{monitor_id}` | 停止監測器 |
| POST | `/cases/{id}/urine-output` | 記錄尿量 |
| POST | `/cases/{id}/timeout` | Time Out 核對 |
| GET | `/cases/{id}/io-balance` | I/O 平衡計算 |
| GET | `/cases/{id}/pdf` | 生成麻醉紀錄 PDF (M0073) |
| GET | `/cases/{id}/pdf/preview` | 預覽 PDF (HTML 格式) |

### Walkaway 不變式 (v1.1 新增)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 麻醉模組 Walkaway 不變式                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ❶ 所有臨床事實都以事件追加；任何畫面/報表都由事件推導，禁止覆寫歷史          │
│                                                                              │
│  ❷ 離線可新增的資料其 ID 必須由 client 產生；不得依賴單一 RPi 生成號碼        │
│                                                                              │
│  ❸ 投影表可從事件 100% 重建；RPi 換機後 Lifeboat restore 必須能恢復完整狀態  │
│                                                                              │
│  ❹ 授權失效只能降級（浮水印），不可阻斷記錄/匯出/復原                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. 參考表單分析

(保留 v1.0 內容，略)

---

## 2. 資料模型 (Event Sourcing)

### 2.1 設計原則 (v1.1 強化)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Event Sourcing 唯一權威                                                      │
│                                                                              │
│   anesthesia_events (Append-Only)                                           │
│         │                                                                    │
│         ├──► anesthesia_cases_projection      (可重建)                      │
│         ├──► anesthesia_iv_lines_projection   (可重建)                      │
│         ├──► anesthesia_monitors_projection   (可重建)                      │
│         └──► PDF 輸出                          (純函式)                      │
│                                                                              │
│   禁止：直接 UPDATE/DELETE projection tables                                │
│   禁止：從 projection tables 渲染 PDF (必須從 events 重算)                   │
│                                                                              │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 資料表結構 (v1.1 修正)

```sql
-- =============================================================================
-- anesthesia_cases: 麻醉案例主表 (PROJECTION, 可從 events 重建)
-- =============================================================================
CREATE TABLE anesthesia_cases (
    -- v1.1: 改用 UUIDv7，case_code 為顯示用
    id TEXT PRIMARY KEY,                    -- UUIDv7 (client 生成)
    case_code TEXT UNIQUE,                  -- 'ANES-YYYYMMDD-NNN' (顯示用)

    -- 病患資訊 (快照)
    person_id TEXT NOT NULL,                -- UUIDv7
    person_name TEXT NOT NULL,
    person_age INTEGER,
    person_gender TEXT,                     -- 'M' | 'F'
    medical_record_number TEXT,

    -- 手術資訊
    room TEXT,
    bed_number TEXT,
    diagnosis TEXT,
    operation TEXT,
    insurance_type TEXT,                    -- 'NHI' | 'SELF_PAY'

    -- 身體測量
    height_cm REAL,
    weight_kg REAL,

    -- 術前評估
    asa_class INTEGER,                      -- ASA 1-6
    pre_op_hb REAL,
    pre_op_ht REAL,
    pre_op_k REAL,
    pre_op_na REAL,

    -- 麻醉方式
    anes_method TEXT,                       -- 'GA', 'MASK', 'SA_EA', 'IV', 'N_BLOCK'
    pca_enabled BOOLEAN DEFAULT FALSE,
    iv_enabled BOOLEAN DEFAULT FALSE,
    ea_enabled BOOLEAN DEFAULT FALSE,

    -- 人員
    anesthesiologist_id TEXT,
    anesthesiologist_name TEXT,
    nurse_anesthetist_id TEXT,
    nurse_anesthetist_name TEXT,
    surgeon_name TEXT,
    cir_nurse_name TEXT,

    -- 備血
    estimated_blood_loss_ml INTEGER,
    blood_type TEXT,
    blood_prepared_units TEXT,              -- JSON

    -- 時間
    scheduled_time DATETIME,
    anesthesia_start DATETIME,
    surgery_start DATETIME,
    surgery_end DATETIME,
    anesthesia_end DATETIME,

    -- 結束資訊 (v1.1: 對應 M0073 右下角)
    destination TEXT,                       -- 'POR' | 'ICU' | 'WARD'
    exit_bp_systolic INTEGER,
    exit_bp_diastolic INTEGER,
    exit_hr INTEGER,
    exit_spo2 INTEGER,

    -- 狀態
    status TEXT DEFAULT 'PENDING',          -- 'PENDING' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED'

    -- 投影元資料
    last_event_id TEXT,                     -- 最後處理的事件
    materialized_at DATETIME,               -- 投影更新時間

    -- 時間戳 (本地)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- anesthesia_events: 麻醉事件表 (唯一權威, Append-Only)
-- =============================================================================
CREATE TABLE anesthesia_events (
    -- v1.1: 改用 UUIDv7，移除 AUTOINCREMENT
    event_id TEXT PRIMARY KEY,              -- UUIDv7 (client 生成)
    case_id TEXT NOT NULL,                  -- FK → anesthesia_cases.id (UUIDv7)

    -- 事件內容
    event_type TEXT NOT NULL,               -- 見 2.3 事件類型
    payload_json TEXT NOT NULL,             -- JSON

    -- 操作者
    actor_id TEXT,                          -- UUIDv7
    actor_name TEXT,
    actor_role TEXT,                        -- 'ANESTHESIOLOGIST' | 'NURSE_ANESTHETIST'
    device_id TEXT,                         -- client device ID

    -- v1.1: 三層時間戳 (Gemini/ChatGPT 建議)
    ts_device INTEGER NOT NULL,             -- Unix ms (裝置時間, 離線時記錄)
    ts_server INTEGER,                      -- Unix ms (同步時填入, 可 null)
    hlc TEXT,                               -- Hybrid Logical Clock (選配, 用於強排序)

    -- 同步狀態
    synced INTEGER DEFAULT 0,               -- 0=pending, 1=synced
    acknowledged INTEGER DEFAULT 0,         -- server ack

    -- Schema 版本
    schema_version TEXT DEFAULT '1.1',

    -- 本地時間 (僅供參考，排序用 ts_device)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- v1.1: 排序用 ts_device + event_id，不用 created_at
CREATE INDEX idx_anes_events_case ON anesthesia_events(case_id);
CREATE INDEX idx_anes_events_ts ON anesthesia_events(ts_device, event_id);
CREATE INDEX idx_anes_events_type ON anesthesia_events(event_type);
CREATE INDEX idx_anes_events_sync ON anesthesia_events(synced);

-- =============================================================================
-- anesthesia_iv_lines: 點滴管路表 (PROJECTION, 可從 events 重建)
-- =============================================================================
CREATE TABLE anesthesia_iv_lines (
    -- v1.1: 改用 UUIDv7
    line_id TEXT PRIMARY KEY,               -- UUIDv7 (client 生成)
    case_id TEXT NOT NULL,                  -- FK → anesthesia_cases.id

    -- 位置
    site TEXT NOT NULL,                     -- 'LEFT_HAND', 'RIGHT_HAND', etc.
    site_detail TEXT,

    -- 管路資訊
    catheter_gauge INTEGER,                 -- 14, 16, 18, 20, 22, 24
    catheter_type TEXT,                     -- 'PERIPHERAL', 'CENTRAL', 'PICC', 'ARTERIAL'

    -- 當前狀態
    current_rate_ml_hr INTEGER,
    current_fluid TEXT,

    -- 時間
    inserted_at INTEGER,                    -- Unix ms
    removed_at INTEGER,                     -- Unix ms (nullable)
    status TEXT DEFAULT 'ACTIVE',           -- 'ACTIVE', 'REMOVED', 'BLOCKED'

    -- 投影元資料
    last_event_id TEXT,
    materialized_at DATETIME
);

-- =============================================================================
-- anesthesia_monitors: 監測器狀態表 (PROJECTION, 可從 events 重建)
-- =============================================================================
CREATE TABLE anesthesia_monitors (
    case_id TEXT PRIMARY KEY,               -- FK → anesthesia_cases.id

    -- 標準監測器
    ekg BOOLEAN DEFAULT FALSE,
    nibp BOOLEAN DEFAULT FALSE,
    pulse_oximeter BOOLEAN DEFAULT FALSE,
    etco2 BOOLEAN DEFAULT FALSE,
    art_line BOOLEAN DEFAULT FALSE,
    cvp BOOLEAN DEFAULT FALSE,
    temp_probe BOOLEAN DEFAULT FALSE,

    -- 護理監測
    foley BOOLEAN DEFAULT FALSE,
    air_blanket BOOLEAN DEFAULT FALSE,
    air_blanket_temp INTEGER,               -- °C

    -- 投影元資料
    last_event_id TEXT,
    materialized_at DATETIME
);

-- =============================================================================
-- anesthesia_urine_output: 尿量記錄表 (PROJECTION, 可從 events 重建)
-- v1.1 新增: Gemini 建議的區間值累計邏輯
-- =============================================================================
CREATE TABLE anesthesia_urine_output (
    record_id TEXT PRIMARY KEY,             -- UUIDv7
    case_id TEXT NOT NULL,

    -- v1.1: 存區間值 (incremental)，前端顯示累計
    ts_start INTEGER NOT NULL,              -- 區間開始 Unix ms
    ts_end INTEGER NOT NULL,                -- 區間結束 Unix ms
    volume_ml INTEGER NOT NULL,             -- 該區間尿量

    -- 尿液性質
    appearance TEXT,                        -- 'CLEAR', 'CLOUDY', 'BLOODY', etc.
    has_blood BOOLEAN DEFAULT FALSE,

    -- 投影元資料
    last_event_id TEXT,
    materialized_at DATETIME
);
```

### 2.3 事件類型定義 (v1.1 更新)

| event_type | 說明 | payload 結構 |
|------------|------|--------------|
| `CASE_CREATED` | 建立案例 | `{case_code, person_id, ...header fields}` |
| `CASE_STARTED` | 開始麻醉 | `{start_time}` |
| `VITAL_RECORDED` | 記錄生命徵象 | `{bp_s, bp_d, hr, spo2, etco2, temp, ebl}` |
| `IV_LINE_INSERTED` | 建立管路 | `{line_id, site, gauge, type, rate, fluid}` |
| `IV_LINE_UPDATED` | 更新管路 | `{line_id, rate?, fluid?}` |
| `IV_LINE_REMOVED` | 移除管路 | `{line_id}` |
| `FLUID_GIVEN` | 給予輸液 | `{line_id, fluid_type, volume_ml}` ← **v1.1: 必須帶 line_id** |
| `BLOOD_GIVEN` | 輸血 | `{line_id, product, units, volume_ml}` ← **v1.1: 必須帶 line_id** |
| `MEDICATION_GIVEN` | 給藥 | `{drug, dose, unit, route, line_id?}` |
| `MONITOR_TOGGLED` | 切換監測器 | `{monitor, enabled, settings?}` |
| `VENTILATOR_SET` | 設定呼吸器 | `{mode, fio2, peep, tv, rate}` |
| `GAS_ADJUSTED` | 調整氣體 | `{o2_lpm, air_lpm, des_pct?, sevo_pct?}` |
| `URINE_RECORDED` | 記錄尿量 | `{record_id, ts_start, ts_end, volume_ml, appearance}` ← **v1.1: 區間值** |
| `EBL_RECORDED` | 記錄失血量 | `{volume_ml, cumulative_ml}` |
| `LAB_RECORDED` | 記錄檢驗值 | `{type, values}` |
| `RESOURCE_CLAIM` | 認領氧氣瓶 | `{cylinder_id, psi}` |
| `RESOURCE_CHECK` | 更新 PSI | `{psi}` |
| `RESOURCE_RELEASE` | 釋放氧氣瓶 | `{ending_psi}` |
| `CASE_ENDED` | 結束麻醉 | `{destination, exit_bp_s, exit_bp_d, exit_hr, exit_spo2}` ← **v1.1: 強制收斂** |
| `ADDENDUM_ADDED` | 補充記錄 | `{note}` (case 結束後唯一可追加的事件) |

---

## 3. IV 管路與輸液綁定 (v1.1 新增)

### 3.1 問題背景 (Gemini 批評)

> 臨床場景：麻醉醫師打了 CVP 和一條周邊 IV。掛上輸血 (PRBC) 時，一定會指定要走哪一條路。
> 如果不綁定，PDF 無法正確繪製「液體流向」，且計算流速時會失真。

### 3.2 解決方案：FLUID_GIVEN 必須帶 line_id

```typescript
// v1.1: FLUID_GIVEN payload 必須包含 line_id
interface FluidGivenPayload {
    line_id: string;            // 必填! 指定走哪條管路
    fluid_type: 'NS' | 'LR' | 'D5W' | 'COLLOID' | 'PRBC' | 'FFP' | 'PLT';
    volume_ml: number;
    rate_ml_hr?: number;        // 可選：該袋輸液的流速
    start_time?: number;        // 可選：開始時間
    end_time?: number;          // 可選：結束時間
}

// 驗證邏輯
function validateFluidGiven(payload: FluidGivenPayload, caseId: string): void {
    if (!payload.line_id) {
        throw new Error('FLUID_GIVEN 必須指定 line_id');
    }

    // 檢查 line_id 存在且為 ACTIVE
    const line = getIVLine(caseId, payload.line_id);
    if (!line || line.status !== 'ACTIVE') {
        throw new Error(`IV line ${payload.line_id} 不存在或已移除`);
    }
}
```

### 3.3 UI 行為

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 給予輸液                                                               [X]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  【選擇管路】 ← v1.1: 必填                                                   │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ ○ #1 左手 (20G) - NS @ 120 mL/hr                    ← 目前使用中      │  │
│  │ ● #2 右臂 CVC (16G) - 空閒                          ← 選擇此管路      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  【輸液類型】                                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PRBC (紅血球濃厚液)                                             ▼   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  【容量】 [250] mL                                                           │
│                                                                              │
│  【流速】 [100] mL/hr (選填)                                                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         [確認給予]                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Foley 尿量累計邏輯 (v1.1 新增)

### 4.1 問題背景 (Gemini 批評)

> 尿量是「累計值」還是「區間值」？
> 後端存 incremental_value，前端顯示時要有 Total Output 的即時計算。

### 4.2 解決方案：存區間值，算累計

```typescript
// URINE_RECORDED payload: 存區間值
interface UrineRecordedPayload {
    record_id: string;          // UUIDv7
    ts_start: number;           // 區間開始 (Unix ms)
    ts_end: number;             // 區間結束 (Unix ms)
    volume_ml: number;          // 該區間尿量 (incremental)
    appearance?: 'CLEAR' | 'CLOUDY' | 'BLOODY' | 'TEA_COLORED';
    has_blood?: boolean;
}

// 計算累計尿量
function calculateTotalUrine(events: AnesthesiaEvent[]): number {
    return events
        .filter(e => e.event_type === 'URINE_RECORDED')
        .reduce((total, e) => {
            const payload = JSON.parse(e.payload_json);
            return total + payload.volume_ml;
        }, 0);
}

// 計算尿量率 (mL/hr) - 評估腎灌流
function calculateUrineRate(events: AnesthesiaEvent[]): number {
    const urineEvents = events.filter(e => e.event_type === 'URINE_RECORDED');
    if (urineEvents.length === 0) return 0;

    const firstEvent = urineEvents[0];
    const lastEvent = urineEvents[urineEvents.length - 1];

    const totalVolume = calculateTotalUrine(events);
    const durationMs = JSON.parse(lastEvent.payload_json).ts_end -
                       JSON.parse(firstEvent.payload_json).ts_start;
    const durationHours = durationMs / (1000 * 60 * 60);

    return durationHours > 0 ? Math.round(totalVolume / durationHours) : 0;
}
```

### 4.3 UI 顯示

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Foley 導尿管                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  【尿量記錄】                                                                │
│                                                                              │
│  時間區間          尿量 (mL)    累計 (mL)    性質                           │
│  ─────────────────────────────────────────────────────────────────────────  │
│  09:30 - 10:00       50           50        清澈                            │
│  10:00 - 10:30       80          130        清澈                            │
│  10:30 - 11:00       70          200        清澈                            │
│  11:00 - 11:30       40          240        淡黃                            │
│                                                                              │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│  總尿量: 240 mL                尿量率: 160 mL/hr                             │
│                                ↑ 即時計算，評估腎灌流                        │
│                                                                              │
│  【新增記錄】                                                                │
│  區間: 11:30 - [____]    尿量: [____] mL    性質: [清澈 ▼]                  │
│                                                                              │
│                                              [記錄]                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 投影重建程序 (v1.1 新增)

### 5.1 重建函式 (Lifeboat 必要)

```python
# backend/anesthesia/projections.py

def rebuild_anesthesia_projections(conn: sqlite3.Connection, case_id: str) -> dict:
    """
    從 events 重建所有麻醉相關投影表

    用途：
    - Lifeboat restore (RPi 換機)
    - 資料驗證
    - 投影修復

    Returns:
        {
            'case': True/False,
            'iv_lines': count,
            'monitors': True/False,
            'urine_records': count
        }
    """
    result = {}

    # 1. 取得該 case 所有事件 (按 ts_device 排序)
    events = conn.execute("""
        SELECT event_id, event_type, payload_json, ts_device
        FROM anesthesia_events
        WHERE case_id = ?
        ORDER BY ts_device ASC, event_id ASC
    """, (case_id,)).fetchall()

    # 2. 重建 case projection
    result['case'] = rebuild_case_projection(conn, case_id, events)

    # 3. 重建 IV lines projection
    result['iv_lines'] = rebuild_iv_lines_projection(conn, case_id, events)

    # 4. 重建 monitors projection
    result['monitors'] = rebuild_monitors_projection(conn, case_id, events)

    # 5. 重建 urine output projection
    result['urine_records'] = rebuild_urine_projection(conn, case_id, events)

    return result


def rebuild_case_projection(conn, case_id: str, events: list) -> bool:
    """重建 anesthesia_cases 投影"""

    # 初始狀態
    state = {
        'id': case_id,
        'status': 'PENDING',
        'last_event_id': None
    }

    for event_id, event_type, payload_json, ts_device in events:
        payload = json.loads(payload_json)
        state['last_event_id'] = event_id

        if event_type == 'CASE_CREATED':
            state.update({
                'case_code': payload.get('case_code'),
                'person_id': payload.get('person_id'),
                'person_name': payload.get('person_name'),
                # ... 其他欄位
            })

        elif event_type == 'CASE_STARTED':
            state['status'] = 'ACTIVE'
            state['anesthesia_start'] = payload.get('start_time')

        elif event_type == 'CASE_ENDED':
            state['status'] = 'COMPLETED'
            state['anesthesia_end'] = payload.get('end_time')
            state['destination'] = payload.get('destination')
            state['exit_bp_systolic'] = payload.get('exit_bp_s')
            state['exit_bp_diastolic'] = payload.get('exit_bp_d')
            state['exit_hr'] = payload.get('exit_hr')
            state['exit_spo2'] = payload.get('exit_spo2')

    # UPSERT
    conn.execute("""
        INSERT OR REPLACE INTO anesthesia_cases
        (id, case_code, person_id, person_name, status, anesthesia_start, anesthesia_end,
         destination, exit_bp_systolic, exit_bp_diastolic, exit_hr, exit_spo2,
         last_event_id, materialized_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (
        state['id'], state.get('case_code'), state.get('person_id'),
        state.get('person_name'), state['status'], state.get('anesthesia_start'),
        state.get('anesthesia_end'), state.get('destination'),
        state.get('exit_bp_systolic'), state.get('exit_bp_diastolic'),
        state.get('exit_hr'), state.get('exit_spo2'), state['last_event_id']
    ))

    return True


def rebuild_iv_lines_projection(conn, case_id: str, events: list) -> int:
    """重建 anesthesia_iv_lines 投影"""

    # 清空該 case 的 IV lines
    conn.execute("DELETE FROM anesthesia_iv_lines WHERE case_id = ?", (case_id,))

    lines = {}  # line_id → state

    for event_id, event_type, payload_json, ts_device in events:
        payload = json.loads(payload_json)

        if event_type == 'IV_LINE_INSERTED':
            line_id = payload['line_id']
            lines[line_id] = {
                'line_id': line_id,
                'case_id': case_id,
                'site': payload.get('site'),
                'site_detail': payload.get('site_detail'),
                'catheter_gauge': payload.get('gauge'),
                'catheter_type': payload.get('type'),
                'current_rate_ml_hr': payload.get('rate'),
                'current_fluid': payload.get('fluid'),
                'inserted_at': ts_device,
                'status': 'ACTIVE',
                'last_event_id': event_id
            }

        elif event_type == 'IV_LINE_UPDATED':
            line_id = payload['line_id']
            if line_id in lines:
                if 'rate' in payload:
                    lines[line_id]['current_rate_ml_hr'] = payload['rate']
                if 'fluid' in payload:
                    lines[line_id]['current_fluid'] = payload['fluid']
                lines[line_id]['last_event_id'] = event_id

        elif event_type == 'IV_LINE_REMOVED':
            line_id = payload['line_id']
            if line_id in lines:
                lines[line_id]['status'] = 'REMOVED'
                lines[line_id]['removed_at'] = ts_device
                lines[line_id]['last_event_id'] = event_id

    # 寫入投影表
    for line in lines.values():
        conn.execute("""
            INSERT INTO anesthesia_iv_lines
            (line_id, case_id, site, site_detail, catheter_gauge, catheter_type,
             current_rate_ml_hr, current_fluid, inserted_at, removed_at, status,
             last_event_id, materialized_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            line['line_id'], line['case_id'], line['site'], line.get('site_detail'),
            line.get('catheter_gauge'), line.get('catheter_type'),
            line.get('current_rate_ml_hr'), line.get('current_fluid'),
            line.get('inserted_at'), line.get('removed_at'), line['status'],
            line['last_event_id']
        ))

    return len(lines)
```

---

## 6. End Case 強制收斂 (v1.1 新增)

### 6.1 問題背景 (ChatGPT 批評)

> 紙本有 POR/ICU、時間、BP/HR/SpO2。需實作「End Case」彈窗，必填上述欄位，一次產生 CASE_ENDED。結束後 case 轉唯讀。

### 6.2 End Case Modal

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 結束麻醉                                                               [X]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  王小明 (45歲/男)                                ANES-20260123-001          │
│  Dx: Appendicitis    Op: Laparoscopic Appendectomy                          │
│                                                                              │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│  【結束時間】                                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 2026-01-23  11:45                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  【送往】 ← 必填                                                             │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐                  │
│  │ ● POR          │ │ ○ ICU          │ │ ○ 病房         │                  │
│  │   (恢復室)      │ │   (加護病房)    │ │   (WARD)       │                  │
│  └────────────────┘ └────────────────┘ └────────────────┘                  │
│                                                                              │
│  【結束生命徵象】 ← 必填 (對應 M0073 右下角)                                  │
│                                                                              │
│  血壓: [120] / [78] mmHg    心率: [72] bpm    SpO2: [99] %                  │
│                                                                              │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│  【統計摘要】                                                                │
│                                                                              │
│  麻醉時間: 2 小時 15 分                                                      │
│  總輸入:   2,050 mL (晶體 800 + 膠體 500 + 血品 750)                         │
│  總輸出:   400 mL (尿量 240 + EBL 150 + 其他 10)                             │
│  淨平衡:   +1,650 mL                                                        │
│                                                                              │
│  ⚠️ 結束後案例將轉為唯讀，僅能追加補充說明 (Addendum)                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      [確認結束麻醉]                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 結束後唯讀規則

```python
def can_add_event(case_id: str, event_type: str) -> bool:
    """檢查是否可新增事件"""

    case = get_case_projection(case_id)

    if case['status'] == 'COMPLETED':
        # 結束後只能追加 ADDENDUM
        return event_type == 'ADDENDUM_ADDED'

    return True
```

---

## 7. PDF 輸出 (v2.2 完成實作)

### 7.1 純函式渲染原則

```
┌────────────────────────────────────────────────────────────────────────────┐
│ PDF = f(events)                                                             │
│                                                                              │
│ 禁止：直接從 projection tables 渲染                                         │
│ 必須：從 events 重算 canonical state 後渲染                                  │
│                                                                              │
│ 流程:                                                                        │
│   1. 讀取 events (WHERE case_id = ?)                                        │
│   2. 重建 canonical state (_rebuild_state_from_events)                      │
│   3. 生成圖表 (SVG 或 Matplotlib)                                           │
│   4. 渲染 HTML 模板 (Jinja2)                                                │
│   5. 轉換 PDF (WeasyPrint) 或回傳 HTML 預覽                                 │
│                                                                              │
└────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 環境適配

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 多環境支援                                                                   │
│                                                                              │
│ Vercel (無系統依賴):                                                         │
│   ├─ 僅支援 HTML 預覽                                                        │
│   ├─ 使用示範資料 (IS_VERCEL flag)                                          │
│   ├─ SVG 圖表 (瀏覽器渲染)                                                  │
│   └─ Jinja2 渲染                                                            │
│                                                                              │
│ 本地/RPi5 (完整功能):                                                        │
│   ├─ 完整 PDF 生成                                                          │
│   ├─ WeasyPrint + Matplotlib                                                │
│   ├─ 真實資料庫查詢                                                         │
│   └─ 支援預覽 (preview=true) 或下載 (preview=false)                         │
│                                                                              │
└────────────────────────────────────────────────────────────────────────────┘
```

### 7.3 PDF 生成 API (已實作)

```python
@router.get("/api/anesthesia/cases/{case_id}/pdf")
async def generate_pdf(
    case_id: str,
    preview: bool = Query(False),           # 預覽模式返回 HTML
    hospital_name: str = Query("烏日林新醫院"),
    hospital_address: str = Query("")
):
    """
    生成麻醉紀錄 PDF (M0073)

    - preview=True  → 返回 HTML 預覽
    - preview=False → 返回 PDF 附件
    - 自動分頁 (VITALS_PER_PAGE = 24)
    """

    # 1. 依賴檢查
    if not preview and not PDF_ENABLED:
        raise HTTPException(503, "PDF generation not available")

    # 2. Vercel Demo Mode
    if IS_VERCEL:
        return render_demo_preview()

    # 3. 從 events 讀取
    events = get_events_for_case(case_id)

    # 4. 重建 canonical state
    state = _rebuild_state_from_events(events)

    # 5. 分頁處理
    pages = paginate_vitals(state["vitals"], VITALS_PER_PAGE)

    # 6. 渲染 Jinja2 模板
    html = render_template("anesthesia_record_m0073.html", context)

    # 7. 返回 HTML 或 PDF
    if preview:
        return StreamingResponse(html, media_type="text/html")
    else:
        pdf = WeasyHTML(string=html).write_pdf()
        return StreamingResponse(pdf, media_type="application/pdf")
```

### 7.4 M0073 PDF 版面配置

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 【Header】 醫院名稱 / 麻醉紀錄 ANESTHETIC RECORD / M0073 / 頁碼            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 【Info Bar】 (僅第一頁)                                                      │
│ ┌─────────────────────────────────┐ ┌─────────────────────────────────────┐ │
│ │ 姓名/性別/年齡/ASA/體重/身高    │ │ Dx/Op/Hb/Ht/K/Na/預估失血/備血     │ │
│ │ 血型/OR | 麻醉方式勾選          │ │                                     │ │
│ └─────────────────────────────────┘ └─────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ 【Main Content - 3 Columns】                                                 │
│ ┌─────────┐ ┌─────────────────────────────────────────┐ ┌─────────────────┐ │
│ │ 藥物     │ │              中央區域                    │ │   監測面板      │ │
│ │ Drugs    │ │ ┌─────────────────────────────────────┐ │ │ ┌─────────────┐ │ │
│ │          │ │ │        SVG 生命徵象圖表             │ │ │ │  Monitors   │ │ │
│ │ 08:30    │ │ │    SBP(紅) DBP(藍) HR(綠)          │ │ │ │  EKG NIBP   │ │ │
│ │ Propofol │ │ │    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━     │ │ │ │  SpO2 ETCO2 │ │ │
│ │ 150mg    │ │ └─────────────────────────────────────┘ │ │ └─────────────┘ │ │
│ │          │ │ ┌─────────────────────────────────────┐ │ │ ┌─────────────┐ │ │
│ │ 08:31    │ │ │         生命徵象表格                │ │ │ │  IV Lines   │ │ │
│ │ Fentanyl │ │ │  Hr │08│08│08│09│09│09│10│10│10│  │ │ │ │  #1 右手 20G│ │ │
│ │ 100mcg   │ │ │ :mm│30│45│00│15│30│45│00│15│30│  │ │ │ └─────────────┘ │ │
│ │          │ │ │ SBP│120│115│...                    │ │ │ ┌─────────────┐ │ │
│ ├─────────┤ │ │ DBP│80│75│...                      │ │ │ │ I/O Balance │ │ │
│ │ Agents  │ │ │ HR │72│68│...                      │ │ │ │ In:  1000ml │ │ │
│ │ O2 Sevo │ │ │ SpO2│99│100│...                    │ │ │ │ Out:  400ml │ │ │
│ │ ...     │ │ │ CO2│35│34│...                      │ │ │ │ Net: +600ml │ │ │
│ │         │ │ │ T° │36.5│36.4│...                  │ │ │ └─────────────┘ │ │
│ └─────────┘ │ └─────────────────────────────────────┘ │ └─────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ 【Footer】 (僅最後一頁)                                                      │
│ 麻醉時間 / 手術時間 / 麻醉醫師簽名 / 護理師簽名                              │
│                         Generated by MIRS v2.2                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.5 SVG 圖表與表格對齊

v2.2 實作了 SVG 圖表資料點與表格欄位精確對齊：

```html
{# 計算欄位位置以對齊表格 #}
{% set vc = page.vitals|length %}
{% set yaxis_pct = 4 %}      {# Y軸標籤佔 4% #}
{% set data_pct = 96 %}      {# 資料區域佔 96% #}
{% set col_pct = data_pct / vc %}  {# 每欄寬度 #}

{# 資料點置於欄位中心 #}
{% set xp = yaxis_pct + loop.index0 * col_pct + col_pct/2 %}
```

### 7.6 依賴項目

| 依賴 | 功能 | 必要性 |
|------|------|--------|
| `Jinja2` | HTML 模板渲染 | 必要 (HTML 預覽) |
| `WeasyPrint` | HTML→PDF 轉換 | 選用 (PDF 輸出) |
| `Matplotlib` | 圖表生成 (PNG) | 選用 (本地環境) |
| `SVG` | 圖表生成 (向量) | 內建 (Vercel 相容) |

---

## 8. 驗收測試 (v1.1 更新)

| # | 測試 | 預期結果 |
|---|------|----------|
| **Walkaway Tests** | | |
| W-01 | 離線建立麻醉案例 | case_id (UUIDv7) 不衝突 |
| W-02 | 離線新增 IV 管路 | line_id (UUIDv7) 不衝突 |
| W-03 | RPi 換機後 Lifeboat restore | 投影可 100% 重建 |
| W-04 | 授權失效後匯出 PDF | PDF 可生成 (有浮水印) |
| **IV/Fluid Tests** | | |
| IV-01 | 給予輸液不帶 line_id | 應被拒絕 (validation error) |
| IV-02 | 給予輸液帶有效 line_id | 事件記錄成功，I/O 更新 |
| IV-03 | 兩條管路同時給水 | 可分別追蹤流向 |
| **Urine Tests** | | |
| UR-01 | 記錄三次尿量 (區間值) | 累計正確計算 |
| UR-02 | 計算尿量率 | mL/hr 正確 |
| **End Case Tests** | | |
| EC-01 | End Case 不填 destination | 應被拒絕 |
| EC-02 | End Case 完成 | status = COMPLETED |
| EC-03 | COMPLETED 後新增 VITAL_RECORDED | 應被拒絕 |
| EC-04 | COMPLETED 後新增 ADDENDUM | 允許 |
| **PDF Tests** | | |
| PDF-01 | 生成 PDF | 包含 IV 管路流向資訊 |
| PDF-02 | 從 events 重建後生成 PDF | 與原 PDF 一致 |
| **PDF Tests (v2.2 新增)** | | |
| PDF-03 | HTML 預覽 (/pdf?preview=true) | 返回可瀏覽 HTML |
| PDF-04 | PDF 下載 (/pdf?preview=false) | 返回 M0073.pdf 附件 |
| PDF-05 | Vercel 環境示範資料 | 自動切換 demo mode |
| PDF-06 | 超過 24 筆 vitals 自動分頁 | 產生多頁 PDF |
| PDF-07 | SVG 圖表與表格對齊 | 資料點對應表格欄位 |
| PDF-08 | 前端預覽/下載按鈕 | UI 支援雙模式操作 |

---

## 9. 相關文件

| 文件 | 說明 |
|------|------|
| `DEV_SPEC_ANESTHESIA_PSI_TRACKING.md` | 氧氣 PSI 追蹤規格 |
| `DEV_SPEC_COMMERCIAL_APPLIANCE_v1.1.md` | 商業化架構 (含 Grace Period) |
| `DEV_SPEC_WALKAWAY_MIGRATION_v1.0.md` | Walkaway 遷移計畫 |

---

---

## 10. 已完成功能清單 (v2.2)

### 10.1 後端 API (routes/anesthesia.py)

| 功能 | 端點 | 狀態 |
|------|------|------|
| PDF 生成 | `GET /cases/{id}/pdf` | ✅ 完成 |
| PDF 預覽 | `GET /cases/{id}/pdf/preview` | ✅ 完成 |
| 事件重建 | `_rebuild_state_from_events()` | ✅ 完成 |
| SVG 圖表 | 內嵌於 Jinja2 模板 | ✅ 完成 |
| Matplotlib 圖表 | `_generate_vitals_chart()` | ✅ 完成 |
| 自動分頁 | `VITALS_PER_PAGE = 24` | ✅ 完成 |
| Vercel Demo | `IS_VERCEL` 自動偵測 | ✅ 完成 |

### 10.2 前端 UI (frontend/anesthesia/index.html)

| 功能 | 狀態 |
|------|------|
| PDF 預覽按鈕 (新視窗開啟) | ✅ 完成 |
| PDF 下載按鈕 | ✅ 完成 |
| 日期篩選 (使用本地時區) | ✅ 完成 |
| 病例狀態顯示 | ✅ 完成 |

### 10.3 示範資料 (seeder_demo.py)

| 功能 | 狀態 |
|------|------|
| 完整 vitals 資料 (每 15 分鐘) | ✅ 完成 |
| 用藥記錄 (propofol, fentanyl 等) | ✅ 完成 |
| IV 管路資料 | ✅ 完成 |
| I/O 平衡資料 | ✅ 完成 |
| 長時間手術案例 (3+ 小時, >24 vitals) | ✅ 完成 |

### 10.4 PDF 模板 (templates/anesthesia_record_m0073.html)

| 功能 | 狀態 |
|------|------|
| A4 橫向紙張 | ✅ 完成 |
| 3 欄佈局 | ✅ 完成 |
| 繁體中文字體 (Noto Sans TC) | ✅ 完成 |
| 分頁機制 | ✅ 完成 |
| SVG 圖表對齊 | ✅ 完成 |
| 醫院/病患資訊區 | ✅ 完成 |
| 生命徵象表格 | ✅ 完成 |
| 用藥清單 | ✅ 完成 |
| I/O Balance 面板 | ✅ 完成 |
| 監測器面板 | ✅ 完成 |
| 簽名欄 | ✅ 完成 |

---

*MIRS Anesthesia Record PWA - v2.2*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
