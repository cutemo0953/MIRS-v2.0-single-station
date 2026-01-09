# xIRS 配對流程 UX 整合規格 v1.0

**版本**: 1.0
**日期**: 2026-01-09
**狀態**: Planning
**範圍**: CIRS + MIRS 所有 PWA 配對入口統一

---

## 現況分析

### CIRS PWA 清單

| PWA | 路徑 | 配對需求 | 現狀 |
|-----|------|----------|------|
| Admin | `/admin/` | 不需配對 (Hub 本機) | ✅ 正常 |
| Dashboard | `/dashboard/` | 不需配對 | ✅ 正常 |
| Doctor | `/doctor/` | PIN 登入 | ✅ 有 Wizard |
| Nurse | `/nurse/` | PIN 登入 | ✅ 有 Wizard |
| Pharmacy | `/pharmacy/` | Satellite 配對 | ⚠️ 入口不明顯 |
| Cashdesk | `/cashdesk/` | PIN 登入 | ✅ 有 Wizard |
| Runner | `/runner/` | PIN 登入 | ✅ 有 Wizard |
| Station (物資站) | `/station/` | Satellite 配對 | ⚠️ 獨立流程 |
| Mobile | `/mobile/` | QR 配對 | ⚠️ 入口不明顯 |

### MIRS PWA 清單

| PWA | 路徑 | 配對需求 | 現狀 |
|-----|------|----------|------|
| Main (Index) | `/` | 不需配對 | ✅ 正常 |
| Mobile | `/static/mobile/` | CIRS Hub 配對 | ⚠️ 流程不明 |
| Anesthesia | `/frontend/anesthesia/` | CIRS Hub 配對 | ⚠️ 流程不明 |

---

## 使用者旅程 (JTBD)

### Job 1: 初次設置 Satellite 站點
**When** 我剛收到物資站/藥局站設備
**I want to** 快速完成配對設定
**So that** 可以開始使用

**現狀問題**:
1. 不知道要開哪個 URL
2. 不知道配對碼從哪裡來
3. 配對後不知道下一步

### Job 2: 工作人員初次使用
**When** 我是新進的醫護人員
**I want to** 用簡單的方式登入系統
**So that** 不需要記複雜的密碼

**現狀問題**:
1. PIN 登入流程沒有 onboarding
2. 不知道自己的 PIN 碼
3. 忘記 PIN 沒有重設流程

### Job 3: 管理員設置新站點
**When** 我要新增一個物資站或藥局站
**I want to** 產生配對碼並完成配對
**So that** 新站點可以加入系統

**現狀問題**:
1. Admin UI 配對碼產生功能不明顯
2. QR Code 掃描指引不足
3. 配對成功後沒有確認通知

---

## 統一配對架構

### 配對類型

```
┌─────────────────────────────────────────────────────────────┐
│                    xIRS 配對類型                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Type A: Hub 本機 (不需配對)                                 │
│  ├── Admin PWA                                              │
│  └── Dashboard                                              │
│                                                             │
│  Type B: PIN 登入 (Hub 內部 PWA)                            │
│  ├── Doctor      → identity/pin-login                       │
│  ├── Nurse       → identity/pin-login                       │
│  ├── Cashdesk    → identity/pin-login                       │
│  └── Runner      → identity/pin-login                       │
│                                                             │
│  Type C: Satellite 配對 (獨立設備)                          │
│  ├── Station (物資站)  → /api/satellite/pair                │
│  ├── Pharmacy (藥局站) → /api/satellite/pair                │
│  └── MIRS              → /api/satellite/pair                │
│                                                             │
│  Type D: Mobile 配對 (個人裝置)                             │
│  ├── CIRS Mobile  → /api/mobile/pair                        │
│  └── MIRS Mobile  → /api/mobile/pair                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: 統一 Wizard UI 元件

### 1.1 xirs-setup-wizard.js

```javascript
/**
 * xIRS Setup Wizard v1.0
 * 統一所有 PWA 的初次設置流程
 */

const WIZARD_STEPS = {
    // Type B: PIN 登入
    PIN_LOGIN: [
        { id: 'welcome', title: '歡迎', component: 'WelcomeStep' },
        { id: 'role', title: '選擇角色', component: 'RoleSelectStep' },
        { id: 'pin', title: 'PIN 登入', component: 'PinLoginStep' },
        { id: 'ready', title: '準備完成', component: 'ReadyStep' }
    ],

    // Type C: Satellite 配對
    SATELLITE_PAIR: [
        { id: 'welcome', title: '歡迎', component: 'WelcomeStep' },
        { id: 'scan', title: '掃描 QR', component: 'QRScanStep' },
        { id: 'confirm', title: '確認配對', component: 'PairConfirmStep' },
        { id: 'sync', title: '同步資料', component: 'SyncStep' },
        { id: 'ready', title: '準備完成', component: 'ReadyStep' }
    ],

    // Type D: Mobile 配對
    MOBILE_PAIR: [
        { id: 'welcome', title: '歡迎', component: 'WelcomeStep' },
        { id: 'scan', title: '掃描 QR', component: 'QRScanStep' },
        { id: 'pin', title: 'PIN 登入', component: 'PinLoginStep' },
        { id: 'ready', title: '準備完成', component: 'ReadyStep' }
    ]
};
```

### 1.2 統一 UI 風格

```
┌─────────────────────────────────────────┐
│  [Logo]  xIRS 物資站設定精靈            │
├─────────────────────────────────────────┤
│                                         │
│  ○ ─── ● ─── ○ ─── ○                   │
│  歡迎   掃描   確認   完成              │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │                                 │   │
│  │     [Step Content Area]         │   │
│  │                                 │   │
│  │                                 │   │
│  └─────────────────────────────────┘   │
│                                         │
│         [上一步]      [下一步]          │
│                                         │
└─────────────────────────────────────────┘
```

---

## Phase 2: Admin 配對管理強化

### 2.1 配對碼管理頁面

位置: Admin PWA → 「站點管理」Tab

```
┌─────────────────────────────────────────────────────────────┐
│  站點管理                                     [+ 新增站點]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ 物資站 #1   │  │ 藥局站 #1   │  │ + 新增      │        │
│  │ ✅ 已配對   │  │ ⏳ 待配對   │  │             │        │
│  │ 最後同步:   │  │ 配對碼:     │  │             │        │
│  │ 10 分鐘前   │  │ A3X9K2      │  │             │        │
│  │ [管理]      │  │ [QR] [複製] │  │             │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 配對碼產生流程

```python
# POST /api/auth/pairing/generate
{
    "station_type": "SUPPLY" | "PHARMACY" | "MIRS",
    "station_name": "物資站 A",
    "expires_minutes": 30  # 配對碼有效時間
}

# Response
{
    "pairing_code": "A3X9K2",
    "qr_data": "{\"type\":\"STATION_PAIR_INVITE\",...}",
    "expires_at": "2026-01-09T15:00:00Z"
}
```

### 2.3 QR Code 顯示 Modal

```
┌─────────────────────────────────────┐
│  配對物資站 #2                   [X] │
├─────────────────────────────────────┤
│                                     │
│         ┌───────────────┐          │
│         │               │          │
│         │   [QR CODE]   │          │
│         │               │          │
│         └───────────────┘          │
│                                     │
│         配對碼: A3X9K2              │
│         有效期: 29:45               │
│                                     │
│  使用物資站設備掃描此 QR Code       │
│  或手動輸入配對碼                   │
│                                     │
│         [複製配對碼]                │
│                                     │
└─────────────────────────────────────┘
```

---

## Phase 3: Station/Pharmacy PWA Wizard 強化

### 3.1 歡迎頁面

```
┌─────────────────────────────────────┐
│                                     │
│         [xIRS Logo]                 │
│                                     │
│     歡迎使用 xIRS 物資站            │
│                                     │
│  本系統將協助您管理醫療物資         │
│  首次使用請完成配對設定              │
│                                     │
│         [開始設定]                  │
│                                     │
│  ─────────────────────────────────  │
│  已有配對？ [匯入設定檔]            │
│                                     │
└─────────────────────────────────────┘
```

### 3.2 掃描 QR 頁面

```
┌─────────────────────────────────────┐
│  ○ ─── ● ─── ○ ─── ○               │
│                                     │
│     請掃描管理員提供的 QR Code      │
│                                     │
│  ┌─────────────────────────────┐   │
│  │                             │   │
│  │     [Camera Preview]        │   │
│  │                             │   │
│  └─────────────────────────────┘   │
│                                     │
│  ─────── 或 ───────                │
│                                     │
│  手動輸入配對碼:                    │
│  ┌─────────────────────────────┐   │
│  │  [  ] [  ] [  ] [  ] [  ] [  ] │   │
│  └─────────────────────────────┘   │
│                                     │
│         [下一步]                    │
│                                     │
└─────────────────────────────────────┘
```

### 3.3 配對確認頁面

```
┌─────────────────────────────────────┐
│  ○ ─── ○ ─── ● ─── ○               │
│                                     │
│     確認配對資訊                    │
│                                     │
│  Hub: CIRS 主控台                   │
│  URL: https://cirs.local:8090      │
│  站點名稱: 物資站 A                 │
│  站點類型: SUPPLY                   │
│                                     │
│  ⚠️ 配對後此設備將專屬於此 Hub     │
│                                     │
│     [取消]      [確認配對]          │
│                                     │
└─────────────────────────────────────┘
```

---

## Phase 4: MIRS 配對入口

### 4.1 MIRS Index.html 新增配對入口

在 MIRS 主頁面新增「Hub 配對」按鈕：

```
┌─────────────────────────────────────────────────────────────┐
│  MIRS v2.8 物資管理系統               [Hub: 未配對] [設定]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [Tab: 庫存] [Tab: 術式] [Tab: ...] [Tab: Hub 配對]        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Hub 配對 Tab 內容

```
┌─────────────────────────────────────────────────────────────┐
│  Hub 配對設定                                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  目前狀態: ⚠️ 未配對                                        │
│                                                             │
│  配對 CIRS Hub 後可使用：                                   │
│  • 處方即時傳送 (Rx Protocol)                               │
│  • 病患轉送接收 (Handoff)                                   │
│  • 統一身份驗證 (PIN 登入)                                  │
│  • 離線權限快照 (Policy Snapshot)                           │
│                                                             │
│              [掃描 QR 配對]                                 │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  手動設定:                                                  │
│  Hub URL: [________________________]                        │
│  配對碼:  [______]                                          │
│              [連線測試]  [配對]                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 5: Mobile PWA 配對強化

### 5.1 CIRS Mobile (/mobile/)

現狀: 需要掃描 QR 但入口不明顯

改善:
- 首次開啟顯示 Wizard
- 掃描 Hub 產生的 Mobile QR Code
- 完成 PIN 登入

### 5.2 MIRS Mobile (/static/mobile/)

現狀: 需要先配對 CIRS Hub

改善:
- 增加「設定 Hub」按鈕
- 支援離線使用 (Policy Snapshot)

---

## 實作順序

```
Week 1: xirs-setup-wizard.js 元件
├── Day 1-2: Wizard 核心元件 + Step 架構
├── Day 3-4: PIN Login Step 整合
└── Day 5: Satellite Pair Step 整合

Week 2: Admin 配對管理
├── Day 1-2: 站點管理 Tab UI
├── Day 3: QR 產生 Modal
└── Day 4-5: 配對狀態即時更新

Week 3: Station/Pharmacy Wizard
├── Day 1-2: 歡迎頁面 + QR 掃描
├── Day 3: 配對確認 + 同步
└── Day 4-5: 離線設定檔匯入

Week 4: MIRS Hub 配對
├── Day 1-2: Index.html Hub 配對 Tab
├── Day 3: Policy Snapshot 同步
└── Day 4-5: 離線驗證整合
```

---

## 檔案變更清單

| 系統 | 操作 | 檔案 |
|------|------|------|
| CIRS | 新增 | `shared/xirs-ui/patterns/xirs-setup-wizard.js` |
| CIRS | 修改 | `frontend/admin/index.html` (站點管理 Tab) |
| CIRS | 修改 | `frontend/station/index.html` (Wizard 強化) |
| CIRS | 修改 | `frontend/pharmacy/index.html` (Wizard 強化) |
| CIRS | 修改 | `frontend/mobile/index.html` (Wizard 強化) |
| MIRS | 修改 | `Index.html` (Hub 配對 Tab) |
| MIRS | 新增 | `routes/local_auth.py` (Phase 9 Policy Snapshot) |

---

**文件版本**: v1.0
**撰寫者**: Claude Code
**日期**: 2026-01-09
