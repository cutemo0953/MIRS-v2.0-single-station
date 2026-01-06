# MIRS Anesthesia Module v1.6.0 - 術中處置記錄與補登功能

**Version:** 1.6.0
**基於:** v1.5.1
**更新日期:** 2026-01-06
**狀態:** 規格草案

---

## Changelog

### v1.6.0 新增功能

| 功能 | 描述 | 來源 |
|------|------|------|
| **術中處置記錄 (Intervention)** | 術中遇到血壓變化等情況，可記錄原因+處置對應 | 麻醉護士回饋 |
| **時間補登 (Retrospective Entry)** | 先處理病人、後補記錄，可修改事件時間 | 麻醉護士回饋 |

---

## 1. 術中處置記錄 (Intraoperative Intervention)

### 1.1 問題描述

麻醉護士反映：手術當中如果做處置，也要可以記錄。例如：
- 血壓低 → 給昇壓劑或輸血
- 血壓高 → 給藥或麻藥調深
- SpO2 下降 → 調整 FiO2 或抽痰
- 心律不整 → 給予 Atropine

**現況問題:** 目前只有獨立的 `VITAL_SIGN` 和 `MEDICATION_ADMIN` 事件，無法清楚呈現「因為觀察到什麼 → 所以做了什麼」的因果關係。

### 1.2 解決方案：新增 `INTERVENTION` 事件類型

```typescript
// 新增 Event Type
type AnesthesiaEventType =
  // ... 既有類型 ...
  | 'INTERVENTION'    // 術中處置 (觸發原因 + 處置內容)
```

### 1.3 INTERVENTION Payload Schema

```typescript
interface InterventionPayload {
  // === 觸發原因 (Trigger) ===
  trigger_type: 'VITAL_CHANGE' | 'COMPLICATION' | 'SURGICAL_REQUEST' | 'ROUTINE' | 'OTHER';

  trigger_detail?: {
    // 生命徵象異常
    vital_type?: 'BP' | 'HR' | 'SPO2' | 'ETCO2' | 'TEMP' | 'RR';
    direction?: 'HIGH' | 'LOW' | 'ABNORMAL';
    observed_value?: string;  // "BP 80/50", "HR 120", "SpO2 88%"

    // 併發症
    complication_type?: string;  // "ARRHYTHMIA", "BRONCHOSPASM", "BLEEDING"
  };

  trigger_note?: string;  // 自由文字描述觸發原因

  // === 處置內容 (Actions) ===
  actions: InterventionAction[];

  // === 結果 (Outcome) ===
  outcome?: {
    resolved: boolean;
    follow_up_value?: string;  // "BP 恢復至 110/70"
    note?: string;
  };
}

interface InterventionAction {
  action_type: 'MEDICATION' | 'FLUID' | 'BLOOD' | 'VENTILATION' | 'ANESTHESIA_DEPTH' | 'OTHER';

  // 用藥處置
  medication?: {
    drug_code?: string;
    drug_name: string;
    dose: number;
    unit: string;
    route: string;  // IV, IM, Bolus, Infusion
  };

  // 輸液/輸血
  fluid?: {
    type: string;  // "NS", "LR", "PRBC", "FFP"
    volume_ml: number;
  };

  // 呼吸調整
  ventilation?: {
    adjustment: string;  // "FiO2 40%→60%", "Suction", "Reposition ETT"
  };

  // 麻醉深度調整
  anesthesia_depth?: {
    agent: string;  // "Sevoflurane", "Propofol"
    adjustment: string;  // "MAC 1.0→1.5", "增加 infusion rate"
  };

  // 其他
  other_action?: string;
}
```

### 1.4 預設處置範本 (Quick Actions)

為加速記錄，UI 提供常見處置範本：

| 觸發 | 處置範本 | 一鍵動作 |
|------|---------|---------|
| BP Low | Ephedrine 5mg IV | 記錄 INTERVENTION + MEDICATION_ADMIN |
| BP Low | Phenylephrine 100mcg IV | 同上 |
| BP Low | LR 250ml bolus | 記錄 INTERVENTION + FLUID_IN |
| BP High | Nicardipine 0.5mg IV | 記錄 INTERVENTION + MEDICATION_ADMIN |
| BP High | Deepen anesthesia | 記錄 INTERVENTION (麻藥調深) |
| HR Low | Atropine 0.5mg IV | 記錄 INTERVENTION + MEDICATION_ADMIN |
| SpO2 Low | FiO2 ↑ | 記錄 INTERVENTION |
| SpO2 Low | Suction | 記錄 INTERVENTION |

### 1.5 UI 設計：處置快捷區

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  麻醉記錄  │  Timeline  │  Vitals  │  管藥  │  處置  │                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  === 常見處置 (快捷按鈕) ===                                                 │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   BP Low        │  │   BP High       │  │   SpO2 Low      │             │
│  │   ▼             │  │   ▼             │  │   ▼             │             │
│  │ [Ephedrine 5mg] │  │ [Nicardipine]   │  │ [FiO2 ↑]        │             │
│  │ [Phenyl 100mcg] │  │ [Deepen Anes]   │  │ [Suction]       │             │
│  │ [LR 250ml]      │  │ [Labetalol]     │  │ [Reposition]    │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   HR Low        │  │   Bleeding      │  │   Other         │             │
│  │   ▼             │  │   ▼             │  │                 │             │
│  │ [Atropine 0.5]  │  │ [PRBC 1U]       │  │ [+ 自訂處置]    │             │
│  │ [Epinephrine]   │  │ [FFP 1U]        │  │                 │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  === 處置記錄 (時間軸) ===                                                   │
│                                                                              │
│  10:45  ⚠ BP Low (80/50) → Ephedrine 5mg IV → BP 恢復 105/65               │
│  11:20  ⚠ SpO2 88% → FiO2 40%→60% → SpO2 恢復 98%                          │
│  11:35  ⚠ 出血量增加 → PRBC 1U → 穩定中                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.6 API 端點

```
POST /api/anesthesia/cases/{id}/events
{
  "event_type": "INTERVENTION",
  "clinical_time": "2026-01-06T10:45:00",
  "payload": {
    "trigger_type": "VITAL_CHANGE",
    "trigger_detail": {
      "vital_type": "BP",
      "direction": "LOW",
      "observed_value": "80/50"
    },
    "actions": [
      {
        "action_type": "MEDICATION",
        "medication": {
          "drug_name": "Ephedrine",
          "dose": 5,
          "unit": "mg",
          "route": "IV"
        }
      }
    ],
    "outcome": {
      "resolved": true,
      "follow_up_value": "BP 105/65"
    }
  }
}
```

---

## 2. 時間補登功能 (Retrospective Entry)

### 2.1 問題描述

麻醉護士反映：目前時間無法改，但實際上有時要先處理病人、再回去補記錄。

**臨床場景:**
1. 病人血壓突然下降，護士立即處理
2. 穩定後才有時間記錄
3. 需要記錄**實際發生時間**（如 10:30），而非**記錄時間**（如 10:45）

### 2.2 現有架構分析

```sql
-- 現有 anesthesia_events 表已有兩個時間欄位:
clinical_time DATETIME NOT NULL,    -- 臨床事件實際發生時間
recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 系統記錄時間
```

**問題:** 目前 UI 未提供 `clinical_time` 編輯功能，預設為當前時間。

### 2.3 解決方案：允許設定過去時間

#### 2.3.1 時間輸入規則

| 規則 | 說明 |
|------|------|
| 允許過去時間 | `clinical_time` 可設為案例開始後的任意時間 |
| 禁止未來時間 | `clinical_time` 不可超過當前時間 |
| 禁止案例前時間 | `clinical_time` 不可早於 `anesthesia_start_at` |
| 記錄時間不可改 | `recorded_at` 永遠是系統當前時間 |
| 補登標記 | 若 `clinical_time` 與 `recorded_at` 差距 > 5分鐘，標記為「補登」 |

#### 2.3.2 補登識別邏輯

```python
def is_retrospective_entry(event) -> bool:
    """判斷是否為補登記錄"""
    time_diff = event.recorded_at - event.clinical_time
    return time_diff.total_seconds() > 300  # > 5 分鐘視為補登

def get_entry_badge(event) -> str:
    """取得記錄標籤"""
    if is_retrospective_entry(event):
        return "補登"  # 顯示於 UI
    return ""
```

### 2.4 UI 設計：時間選擇器

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  記錄 Vitals                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  === 事件時間 ===                                                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ○ 現在 (11:45)                                                      │    │
│  │  ● 指定時間 [ 11 : 30 ]  ← 時間選擇器                               │    │
│  │                                                                      │    │
│  │  快捷: [5分鐘前] [10分鐘前] [15分鐘前] [30分鐘前]                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ⚠ 此記錄將標記為「補登」(記錄時間: 11:45, 事件時間: 11:30)               │
│                                                                              │
│  === Vitals 數值 ===                                                         │
│                                                                              │
│  BP: [___]/[___]  HR: [___]  SpO2: [___]%  ...                             │
│                                                                              │
│                                                    [取消]  [確認記錄]        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.5 時間選擇器元件

```html
<!-- 時間選擇器元件 -->
<div class="time-selector" x-data="{ mode: 'now', customTime: null }">
    <label class="flex items-center gap-2 p-2 rounded cursor-pointer"
           :class="mode === 'now' ? 'bg-indigo-100' : 'bg-gray-50'"
           @click="mode = 'now'">
        <input type="radio" x-model="mode" value="now">
        <span>現在</span>
        <span class="text-gray-500" x-text="currentTime"></span>
    </label>

    <label class="flex items-center gap-2 p-2 rounded cursor-pointer"
           :class="mode === 'custom' ? 'bg-indigo-100' : 'bg-gray-50'"
           @click="mode = 'custom'">
        <input type="radio" x-model="mode" value="custom">
        <span>指定時間</span>
        <input type="time"
               x-model="customTime"
               :disabled="mode !== 'custom'"
               class="ml-2 px-2 py-1 border rounded">
    </label>

    <!-- 快捷按鈕 -->
    <div class="flex gap-2 mt-2" x-show="mode === 'custom'">
        <button @click="setTimeOffset(5)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">5分鐘前</button>
        <button @click="setTimeOffset(10)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">10分鐘前</button>
        <button @click="setTimeOffset(15)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">15分鐘前</button>
        <button @click="setTimeOffset(30)"
                class="px-3 py-1 bg-gray-100 rounded text-sm">30分鐘前</button>
    </div>

    <!-- 補登提示 -->
    <div x-show="mode === 'custom'"
         class="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-sm">
        <span class="text-amber-700">
            此記錄將標記為「補登」
        </span>
    </div>
</div>
```

### 2.6 Timeline 顯示補登標記

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Timeline                                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  11:45  ● Vitals: BP 120/75, HR 68, SpO2 99%                               │
│                                                                              │
│  11:30  ● Vitals: BP 85/55, HR 95, SpO2 94%  [補登 11:45]                  │
│         │                                     ↑ 顯示實際記錄時間            │
│         │                                                                   │
│  11:30  ⚠ INTERVENTION: BP Low → Ephedrine 5mg  [補登 11:45]               │
│                                                                              │
│  11:15  ● Vitals: BP 115/70, HR 72, SpO2 98%                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.7 API 請求範例

```json
// POST /api/anesthesia/cases/{id}/events
{
  "event_type": "VITAL_SIGN",
  "clinical_time": "2026-01-06T11:30:00",  // 實際發生時間 (可設為過去)
  "payload": {
    "bp_sys": 85,
    "bp_dia": 55,
    "hr": 95,
    "spo2": 94
  }
}

// 回應
{
  "id": "evt-xxx",
  "event_type": "VITAL_SIGN",
  "clinical_time": "2026-01-06T11:30:00",
  "recorded_at": "2026-01-06T11:45:23",    // 系統自動設定
  "is_retrospective": true,                 // 補登標記
  "payload": { ... }
}
```

---

## 3. Schema 變更

### 3.1 無需修改現有表格

現有 `anesthesia_events` 表已支援 `clinical_time` 和 `recorded_at` 分離，無需 ALTER TABLE。

### 3.2 建議新增 View

```sql
-- 方便查詢補登記錄
CREATE VIEW retrospective_entries AS
SELECT
    id,
    case_id,
    event_type,
    clinical_time,
    recorded_at,
    (julianday(recorded_at) - julianday(clinical_time)) * 24 * 60 as delay_minutes,
    CASE
        WHEN (julianday(recorded_at) - julianday(clinical_time)) * 24 * 60 > 5
        THEN 1
        ELSE 0
    END as is_retrospective,
    payload,
    actor_id
FROM anesthesia_events
WHERE recorded_at > clinical_time;
```

---

## 4. 實作優先順序

| 優先級 | 功能 | 預估工時 |
|--------|------|----------|
| **P0** | 時間選擇器 UI | 2-3 小時 |
| **P0** | API 接受過去時間 + 驗證 | 1 小時 |
| **P0** | Timeline 補登標記顯示 | 1 小時 |
| **P1** | INTERVENTION 事件類型 | 2-3 小時 |
| **P1** | 處置快捷按鈕 UI | 3-4 小時 |
| **P2** | 處置範本管理 (Admin) | 2 小時 |

---

## 5. 驗收測試

| 測試案例 | 預期結果 |
|----------|----------|
| 記錄 Vitals 選擇「10分鐘前」 | `clinical_time` = now - 10min, 顯示「補登」標籤 |
| 記錄 Vitals 選擇「現在」 | `clinical_time` ≈ `recorded_at`, 無補登標籤 |
| 輸入未來時間 | 顯示錯誤「時間不可超過現在」 |
| 輸入案例開始前時間 | 顯示錯誤「時間不可早於麻醉開始」 |
| 點擊「BP Low → Ephedrine」快捷 | 同時建立 INTERVENTION + MEDICATION_ADMIN 事件 |
| 處置記錄含 outcome | Timeline 顯示「→ 恢復至 xxx」 |

---

## 6. 安全與稽核考量

### 6.1 補登的法律效力

| 考量 | 措施 |
|------|------|
| 補登記錄的真實性 | 保留 `recorded_at` 做為稽核證據 |
| 防止濫用 | 報表可篩選補登記錄，異常延遲可被審查 |
| 時間限制 | 考慮限制最大補登間隔 (如 2 小時內) |

### 6.2 補登報表

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  補登記錄報表 (案例: ANES-20260106-001)                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  總事件數: 45                                                                │
│  補登記錄: 8 (17.8%)                                                         │
│  平均延遲: 12.3 分鐘                                                         │
│  最大延遲: 28 分鐘                                                           │
│                                                                              │
│  明細:                                                                       │
│  ┌──────────┬────────────┬────────────┬────────────┬───────────┐           │
│  │ 事件類型  │ 事件時間   │ 記錄時間   │ 延遲(分鐘) │ 記錄者    │           │
│  ├──────────┼────────────┼────────────┼────────────┼───────────┤           │
│  │ VITAL    │ 11:30      │ 11:45      │ 15         │ 護士A     │           │
│  │ INTERVEN │ 11:30      │ 11:47      │ 17         │ 護士A     │           │
│  │ VITAL    │ 11:35      │ 11:48      │ 13         │ 護士A     │           │
│  └──────────┴────────────┴────────────┴────────────┴───────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*Version: 1.6.0*
*Last Updated: 2026-01-06*
*Status: 規格草案，待實作*
