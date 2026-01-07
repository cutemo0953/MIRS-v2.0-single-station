# xIRS 架構定案 (Final Architecture)

**版本**: v1.0
**日期**: 2026-01-07
**狀態**: **APPROVED**
**整合來源**: Claude + ChatGPT + Gemini 審查

---

## 0. 核心決策

### 0.1 系統邊界

```
┌─────────────────────────────────────────────────────────────────────┐
│                      xIRS 臨床系統生態系                            │
│                                                                      │
│   ┌─────────────┐         ┌─────────────┐                           │
│   │  CIRS Hub   │◄───────►│MIRS Satellite│                          │
│   │ (臨床流程)  │   API   │ (物資引擎)   │                          │
│   └─────────────┘         └─────────────┘                           │
│          │                       │                                   │
│          └───────────┬───────────┘                                   │
│                      │                                               │
│        ┌─────────────┼─────────────┐                                │
│        │             │             │                                │
│        ▼             ▼             ▼                                │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐                            │
│   │Clinician│  │ Nursing │  │Logistics│  ... (Role PWAs)           │
│   │   PWA   │  │   PWA   │  │   PWA   │                            │
│   └─────────┘  └─────────┘  └─────────┘                            │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      HIRS (獨立產品線)                               │
│                                                                      │
│   定位: 個人/家庭韌性準備 + 行銷展示                                │
│   不屬於 xIRS 臨床系統                                              │
│   獨立開發、獨立部署、不共用資料                                    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 0.2 三大不可逆決策

| # | 決策 | 理由 |
|---|------|------|
| 1 | **MIRS 退居引擎** | Tab 只做管理/報表，不做臨床執行 |
| 2 | **Nursing PWA 工作站化** | 護理師是執行樞紐，串聯一切 |
| 3 | **執行才扣庫** | 開醫囑 ≠ 真相，執行確認才扣庫存 |

---

## 1. 權責邊界 (Authority Map)

### 1.1 系統權責

| 系統 | 權責範圍 | 說明 |
|------|----------|------|
| **CIRS Hub** | 病患身分、掛號、交班 | 臨床流程的真相來源 |
| **MIRS Engine** | 物資、庫存、管藥帳、麻醉事件 | 資源的真相來源 |

### 1.2 寫入合約 (Write Contract)

**死規則：每個 domain object 只有一條寫入路徑**

| 資料領域 | 唯一寫入者 | 寫入情境 | 禁止寫入者 |
|----------|-----------|----------|-----------|
| `registrations` | CIRS Admin | 掛號報到 | 其他所有 PWA |
| `orders` | Clinician PWA | 開立醫囑 | Nursing, MIRS |
| `executions` | Nursing PWA | 給藥、處置執行 | Doctor, MIRS Tab |
| `vital_signs` | Nursing/Anesthesia/EMT | 測量 VS | Doctor, Admin |
| `handoff_records` | CIRS (自動) + Nursing (補充) | 交班 | Doctor (只讀) |
| `anesthesia_events` | Anesthesia PWA | 麻醉記錄 | 其他所有 |
| `pio_*` | Anesthesia PWA | 問題-介入-結果 | 其他所有 |
| `inventory` | Logistics PWA (進貨) | 入庫 | 臨床 PWA |
| `resource_consume` | MIRS Engine (自動) | 扣庫 | 人工操作禁止 |
| `transfer_*` | Logistics/EMT PWA | 轉送 | 其他所有 |

### 1.3 違規處理

```
違規情境：Nursing PWA 直接改庫存數字
正確做法：Nursing PWA 確認執行 → 產生 execution → MIRS Engine 消費 → 自動扣庫

違規情境：MIRS Tab 讓使用者輸入「用了 3 個紗布」
正確做法：MIRS Tab 只顯示 execution 記錄（唯讀）
```

---

## 2. 閉環執行模型 (Closed-Loop Execution)

### 2.1 核心流程

```
                    閉環執行模型

    ┌──────────────────────────────────────────────────────────┐
    │                                                          │
    │  [Clinician PWA]                                        │
    │       │                                                  │
    │       │ 開立醫囑                                        │
    │       ▼                                                  │
    │  ┌─────────┐                                            │
    │  │ orders  │ ──────────────────┐                        │
    │  └─────────┘                   │                        │
    │                                │ 待執行                  │
    │                                ▼                        │
    │  [Nursing PWA]           ┌──────────┐                   │
    │       │                  │ 待辦清單  │                   │
    │       │ 執行確認         └──────────┘                   │
    │       ▼                        │                        │
    │  ┌──────────┐                  │                        │
    │  │executions│◄─────────────────┘                        │
    │  └──────────┘                                           │
    │       │                                                  │
    │       │ 產生 resource_intent                            │
    │       ▼                                                  │
    │  ┌──────────────┐                                       │
    │  │resource_intent│  (離線時 queue)                      │
    │  └──────────────┘                                       │
    │       │                                                  │
    │       │ MIRS Engine 消費                                │
    │       ▼                                                  │
    │  ┌──────────┐                                           │
    │  │ inventory │  (自動扣庫)                              │
    │  └──────────┘                                           │
    │                                                          │
    └──────────────────────────────────────────────────────────┘
```

### 2.2 兩階段確認

```javascript
// 階段 1: 臨床記錄 (永遠允許，離線可做)
const execution = {
    order_id: 'ORD-001',
    action: 'ADMINISTERED',
    actual_dose: '5mg',
    executed_by: 'nurse001',
    event_time: Date.now(),
    recorded_at: Date.now()
};
await db.insert('executions', execution);

// 階段 2: 資源意圖 (queue，等待 MIRS 確認)
const intent = {
    execution_id: execution.id,
    items: [
        { item_code: 'MED-MORPH-10', quantity: 1 }
    ],
    status: 'PENDING_SYNC'
};
await resourceIntentQueue.push(intent);

// 上線時 MIRS Engine 消費
// 成功 → status = 'CONFIRMED'
// 失敗 → 進入 Incomplete Queue
```

### 2.3 UI 規則

| 狀態 | 顯示 | 意義 |
|------|------|------|
| `PENDING_SYNC` | 🟡 黃色 badge | 等待庫存確認 |
| `CONFIRMED` | ✓ 綠色 | 已扣庫存 |
| `FAILED` | 🔴 紅色 | 需人工處理 |
| `INCOMPLETE` | ⚠️ 橙色 | 缺必填欄位 |

---

## 3. PWA 矩陣 (Role-Based Apps)

### 3.1 最終矩陣

| PWA | 使用者 | 模式 | 寫入表 | 離線 |
|-----|--------|------|--------|------|
| **Clinician** | 醫師 | 急診/門診/查房 | orders | 中 |
| **Nursing** | 護理師 | 檢傷/急診/病房/交班 | executions, vital_signs, nursing_notes, handoff_records | **高** |
| **Anesthesia** | 麻醉科 | 術中/PACU | anesthesia_events, pio_*, vital_signs | **高** |
| **Logistics** | 庫房/EMT | 庫存/轉送 | inventory (進貨), transfer_* | **高** |
| **Pharmacy** | 藥師 | 調劑 | executions (DISPENSED) | 中 |
| **Admin** | 站長 | 管理 | system_config | 低 |
| **Dashboard** | 站長 | 總覽 | **無 (唯讀)** | 低 |

### 3.2 Nursing PWA 詳細設計

```
┌─────────────────────────────────────────────────────────────┐
│                    Nursing Workstation                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │  檢傷   │ │  急診   │ │  病房   │ │  交班   │          │
│  │ Triage │ │   ER    │ │  Ward   │ │ Handoff │          │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘          │
│       │           │           │           │                │
│  ┌────┴───────────┴───────────┴───────────┴────┐          │
│  │              共用核心功能                    │          │
│  ├─────────────────────────────────────────────┤          │
│  │                                             │          │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐    │          │
│  │  │ VS 採集 │  │給藥 MAR │  │消耗登記 │    │          │
│  │  │         │  │(掃碼確認)│  │         │    │          │
│  │  └─────────┘  └─────────┘  └─────────┘    │          │
│  │                                             │          │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐    │          │
│  │  │ 待辦事項│  │ 血袋操作│  │ 護理紀錄│    │          │
│  │  │(from    │  │(輸血確認)│  │         │    │          │
│  │  │ orders) │  │         │  │         │    │          │
│  │  └─────────┘  └─────────┘  └─────────┘    │          │
│  │                                             │          │
│  └─────────────────────────────────────────────┘          │
│                                                             │
│  ┌─────────────────────────────────────────────┐          │
│  │              模式特殊功能                    │          │
│  ├─────────────────────────────────────────────┤          │
│  │  檢傷: START 分流、優先序                   │          │
│  │  急診: 快速處置、警示                       │          │
│  │  病房: Q4H 提醒、I/O、傷口評估             │          │
│  │  交班: ISBAR 產生、待辦移交                │          │
│  └─────────────────────────────────────────────┘          │
│                                                             │
│  ┌─────────────────────────────────────────────┐          │
│  │            Incomplete Queue                  │          │
│  │  • 血品缺 unit_id                           │          │
│  │  • 資源待同步                               │          │
│  │  • 補登缺理由                               │          │
│  └─────────────────────────────────────────────┘          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. MIRS Tab 定位

### 4.1 Tab 歸屬

| Tab | 定位 | 可操作 | 禁止操作 |
|-----|------|--------|----------|
| 庫存查詢 | 主檔/查詢 | 新增品項、編輯屬性 | 直接改庫存數量 |
| 進貨 | 入庫登記 | 登記進貨 | - |
| 處置 | **報表/稽核** | 查看 execution 記錄 | **輸入任何消耗** |
| 血庫 | 入庫管理 | 血袋入庫、效期管理 | 直接改數量 |
| 設備 | 資產管理 | 設備主檔、維護記錄 | - |
| 韌性估算 | 決策支援 | 查看、報表 | - |

### 4.2 處置 Tab 改版

```
舊版（作廢）:
┌─────────────────────────────────────┐
│ 處置 Tab                            │
├─────────────────────────────────────┤
│ ○ 處置耗材記錄  ← 可輸入           │
│ ○ 一般消耗      ← 可輸入 (移除)    │
│ ○ 藥品領用      ← 可輸入 (移除)    │
└─────────────────────────────────────┘

新版:
┌─────────────────────────────────────┐
│ 處置報表 Tab                        │
├─────────────────────────────────────┤
│ 執行記錄列表 (唯讀)                 │
│ ├─ 來源: Nursing PWA executions    │
│ ├─ 篩選: 日期、類型、執行者        │
│ └─ 匯出: CSV                        │
│                                     │
│ 資源對帳狀態                        │
│ ├─ CONFIRMED: 123 筆               │
│ ├─ PENDING: 5 筆                   │
│ └─ FAILED: 2 筆 [查看詳情]         │
│                                     │
│ [開啟 Nursing PWA 執行操作]         │
└─────────────────────────────────────┘
```

---

## 5. HIRS 定位 (獨立產品線)

### 5.1 明確切割

```
HIRS ≠ xIRS

HIRS 是獨立產品:
├── 目標用戶: 個人/家庭
├── 用途: 準備度評估、物資管理、行銷展示
├── 部署: 獨立 (不與 CIRS/MIRS 連動)
├── 資料: 不共用
└── 開發: 獨立 repo、獨立 roadmap
```

### 5.2 功能範圍

| 功能 | HIRS | xIRS 是否有 |
|------|:----:|:-----------:|
| 個人物資清單 | ✓ | ✗ |
| 家庭準備度評估 | ✓ | ✗ |
| 急救指引範本 | ✓ | (不同) |
| 完全離線運作 | ✓ | ✓ |
| 病患掛號 | ✗ | ✓ |
| 醫囑執行 | ✗ | ✓ |
| 庫存扣減 | ✗ | ✓ |

---

## 6. 資料合約 (Data Contracts)

### 6.1 共用 Schema

```typescript
// shared/schema/execution.ts
interface Execution {
    id: string;
    order_id?: string;           // 關聯醫囑 (可選)
    person_id: string;

    // 時間
    event_time: number;          // 臨床發生時間
    recorded_at: number;         // 輸入時間
    time_source: 'NOW' | 'BACKDATED' | 'CORRECTED';

    // 執行內容
    action: 'VERIFIED' | 'DISPENSED' | 'ADMINISTERED' | 'HELD' | 'REFUSED';
    actual_dose?: string;
    site?: string;
    route?: string;

    // 資源連動
    resource_intents: ResourceIntent[];

    // 執行者
    executed_by: string;
    witness_by?: string;

    // 稽核
    corrected_from?: string;
    correction_reason?: string;
}

interface ResourceIntent {
    item_code: string;
    quantity: number;
    lot?: string;
    blood_unit_id?: string;      // 血品專用
    status: 'PENDING_SYNC' | 'CONFIRMED' | 'FAILED';
    confirmed_at?: number;
    mirs_ref?: string;
}
```

### 6.2 事件類型

```typescript
// 統一事件類型
type ClinicalEventType =
    | 'ORDER_CREATED'
    | 'ORDER_CANCELLED'
    | 'EXECUTION_CONFIRMED'
    | 'RESOURCE_DEDUCTED'       // MIRS Engine 產生
    | 'HANDOFF_INITIATED'
    | 'HANDOFF_ACCEPTED'
    | 'VITALS_RECORDED'
    | 'NURSING_NOTE_ADDED'
    | 'ANESTHESIA_EVENT'
    | 'PIO_PROBLEM_CREATED'
    | 'PIO_INTERVENTION_ADDED'
    | 'PIO_OUTCOME_LOGGED';
```

---

## 7. 驗收測試

### 7.1 閉環執行

```gherkin
Scenario: 醫囑到執行到扣庫閉環
  Given 醫師開立 "Morphine 5mg IV STAT"
  When 護理師在 Nursing PWA 看到待辦
    And 護理師掃描病人手圈
    And 護理師掃描藥品條碼
    And 護理師確認給藥
  Then orders.status = 'ADMINISTERED'
    And executions 有一筆 ADMINISTERED 記錄
    And resource_intent.status = 'PENDING_SYNC'
  When MIRS Engine 消費 intent
  Then resource_intent.status = 'CONFIRMED'
    And inventory 數量減少 1
```

### 7.2 離線執行

```gherkin
Scenario: 離線執行，上線同步
  Given 網路斷線
  When 護理師在 Nursing PWA 確認給藥
  Then execution 建立成功 (本地)
    And resource_intent.status = 'PENDING_SYNC'
    And UI 顯示 🟡 黃色 badge
  When 網路恢復
  Then resource_intent 自動同步至 MIRS
    And status 變為 'CONFIRMED'
    And UI 顯示 ✓ 綠色
```

### 7.3 寫入合約違規

```gherkin
Scenario: MIRS Tab 不能直接改庫存
  Given 使用者在 MIRS 處置 Tab
  Then 沒有「新增消耗」按鈕
    And 沒有「編輯數量」欄位
    And 只有「查看詳情」連結
    And 有「開啟 Nursing PWA」按鈕
```

### 7.4 Incomplete Queue

```gherkin
Scenario: 血品缺 unit_id 進入 Incomplete
  Given 護理師記錄輸血
  When 未輸入血袋條碼
  Then 該記錄進入 Incomplete Queue
    And 顯示「血品缺 unit_id」警示
    And 無法結案直到補齊
```

---

## 8. 遷移路徑

### Phase 0: 準備 (現在)
```
✓ 架構文件定案
✓ 寫入合約定義
□ 團隊共識確認
```

### Phase 1: API 合約 (v3.0)
```
□ 建立 /api/executions (統一執行)
□ 建立 /api/resource-intents (資源意圖)
□ MIRS /api/inventory/consume (引擎消費)
□ 跨系統認證 (Station Token)
```

### Phase 2: Nursing PWA (v3.1)
```
□ Ward Mode 實作
□ MAR 給藥確認 (掃碼)
□ Incomplete Queue
□ 離線 + 同步機制
```

### Phase 3: MIRS Tab 降級 (v3.2)
```
□ 處置 Tab 改為唯讀
□ 移除一般消耗/藥品領用輸入
□ 新增「開啟 Nursing PWA」導向
□ 新增資源對帳狀態顯示
```

### Phase 4: Dashboard + 清理 (v3.3)
```
□ Dashboard PWA (唯讀總覽)
□ 淘汰重複功能
□ 文件更新
□ 訓練材料
```

---

## 9. 附錄

### 9.1 決策記錄

| 日期 | 決策 | 理由 | 決策者 |
|------|------|------|--------|
| 2026-01-07 | MIRS 退居引擎 | Tab 只做管理/報表 | Claude+GPT+Gemini |
| 2026-01-07 | Nursing 工作站化 | 護理是執行樞紐 | Claude+GPT+Gemini |
| 2026-01-07 | 執行才扣庫 | 開單≠真相 | Claude+GPT+Gemini |
| 2026-01-07 | HIRS 獨立產品線 | 定位不同，不共用 | User |

### 9.2 相關文件

- `xIRS_USER_JOURNEY_JTBD.md` - 使用者旅程
- `xIRS_ARCHITECTURE_CONSOLIDATION.md` - 架構整合 (護理為核心)
- `xIRS_FUNCTION_CONSOLIDATION.md` - 功能整併分析
- `DEV_SPEC_MIRS_ADMIN_PORTAL.md` - Admin 規格
- `DEV_SPEC_ANESTHESIA_TIMELINE_UI.md` - 麻醉 UI 規格
- `DEV_SPEC_xIRS_PAIRING_SECURITY.md` - 安全機制

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 - 整合 Claude/ChatGPT/Gemini 審查 + User 確認 |
