# Blood Bank PWA DEV SPEC v1.0

**版本**: 1.0
**日期**: 2026-01-12
**狀態**: Planning
**基於**: Gemini + ChatGPT 建議 + BioMed PWA 經驗教訓

---

## 執行摘要

Blood Bank PWA 將從 MIRS 主站剝離成獨立 PWA，採用與 BioMed PWA 相同的架構模式（MIRS 後台 + SQLite + PWA 連動）。但血品管理具有更高的臨床風險，需要額外的「預約邏輯」和「效期阻擋」機制。

---

## 一、Gemini vs ChatGPT 意見統整

### 1.1 共識點

| 議題 | Gemini | ChatGPT | 結論 |
|------|--------|---------|------|
| **欄位契約** | 引入 `reserved_quantity` | 單一 `display_status` | ✅ 兩者都對，需同時實作 |
| **效期控管** | 阻擋過期血品出庫 | 高風險域設計 | ✅ 必須是 Blocker 而非 Warning |
| **API 版本** | - | 從 Day 0 釘死 | ✅ 避免 v1/v2 混亂 |
| **SW 隔離** | - | 獨立 manifest/scope | ✅ 必須，避免快取污染 |
| **職責邊界** | Order-driven 模式 | 鎖死臨床邊界 | ✅ Doctor 開單 → Blood 執行 → Nurse 輸血 |

### 1.2 差異點

| 議題 | Gemini 建議 | ChatGPT 建議 | Claude 意見 |
|------|------------|-------------|-------------|
| **病患資訊** | 不同步病患，用 Order ID 驅動 | 未明確提及 | ✅ 採用 Gemini：Order-driven 更安全 |
| **FIFO 提示** | UI 標示「優先使用」血袋 | 未明確提及 | ✅ 採用：降低過期風險 |
| **Lobby 路由** | 未明確提及 | BLOOD_STATION 一級站點 | ✅ 採用 ChatGPT：但 Blood 屬於 MIRS 子站 |

---

## 二、Claude 意見：BioMed 經驗教訓

### 2.1 必須避免的錯誤

基於 BioMed PWA 13 版迭代的教訓（v1.2.6 → v1.2.18）：

| BioMed 錯誤 | 根因 | Blood PWA 預防措施 |
|-------------|------|-------------------|
| UI 狀態分裂腦 | `status` vs `check_status` 混用 | **欄位契約表**：UI 只綁定 View 欄位 |
| API 更新錯表 | v1 API 更新 `equipment.status`，View 讀 `equipment_units.last_check` | **API→欄位映射表**：明確記錄每個 endpoint 更新哪些欄位 |
| 樂觀更新被覆蓋 | `loadResilienceStatus()` 重新載入覆蓋本地狀態 | **狀態更新策略**：樂觀更新 + 延遲 reload |
| Alpine 響應性問題 | 嵌套屬性修改不觸發重繪 | **使用 `.map()` 創建新陣列** |

### 2.2 黃金模式

```
前端樂觀更新 + 後端 View 狀態聚合 + 單一狀態來源
```

---

## 三、架構設計

### 3.1 職責邊界（Gemini + ChatGPT 共識）

```
┌─────────────────────────────────────────────────────────────────┐
│                      輸血流程職責矩陣                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [CIRS Doctor PWA]                                              │
│       │                                                         │
│       ├─→ 開立輸血醫囑 (Order)                                   │
│       │   - 產生 Order ID: TX-YYYYMMDD-NNN                      │
│       │   - 指定血型、數量、優先級                                │
│       │                                                         │
│       ↓                                                         │
│  [MIRS Blood PWA] ← 本次開發目標                                 │
│       │                                                         │
│       ├─→ 接收配血請求 (by Order ID)                             │
│       ├─→ 執行交叉配血                                           │
│       ├─→ 預約血袋 (Reserve)                                     │
│       ├─→ 發血出庫 (Issue)                                       │
│       │                                                         │
│       ↓                                                         │
│  [CIRS Nurse/Anesthesia PWA]                                    │
│       │                                                         │
│       ├─→ 床邊核對 (Patient ID + Blood Unit ID)                  │
│       ├─→ 執行輸血                                               │
│       └─→ 輸血反應紀錄                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 資料流（Order-Driven 模式）

```
CIRS                              MIRS Blood PWA
  │                                     │
  │  POST /api/orders/transfusion       │
  │  { blood_type, quantity, priority } │
  │ ──────────────────────────────────→ │
  │                                     │
  │  Order ID: TX-20260112-001          │
  │ ←────────────────────────────────── │
  │                                     │
  │                                     │  (Blood PWA 查詢)
  │                                     │  GET /proxy/cirs/orders/{id}
  │                                     │  → 取得血型、數量需求
  │                                     │
  │                                     │  (Blood PWA 執行)
  │                                     │  - 配血
  │                                     │  - 預約血袋
  │                                     │  - 發血
  │                                     │
  │  Webhook: blood_issued              │
  │ ←────────────────────────────────── │
  │                                     │
```

---

## 四、資料庫設計

### 4.1 新增表格

```sql
-- 血品庫存 (已存在於 inventory，但需擴展)
-- inventory 表已有 blood 類型項目

-- 血袋單位表 (類似 equipment_units)
CREATE TABLE IF NOT EXISTS blood_units (
    id TEXT PRIMARY KEY,
    blood_type TEXT NOT NULL,          -- A+, A-, B+, B-, O+, O-, AB+, AB-
    unit_type TEXT NOT NULL,           -- PRBC, FFP, PLT, CRYO
    volume_ml INTEGER DEFAULT 250,
    donation_id TEXT,                  -- 捐血編號
    collection_date DATE,
    expiry_date DATE NOT NULL,
    status TEXT DEFAULT 'AVAILABLE',   -- AVAILABLE, RESERVED, ISSUED, EXPIRED, DISPOSED

    -- 預約資訊
    reserved_for_order TEXT,           -- Order ID (FK to transfusion_orders)
    reserved_at TIMESTAMP,
    reserved_by TEXT,

    -- 出庫資訊
    issued_at TIMESTAMP,
    issued_by TEXT,
    issued_to_order TEXT,

    -- 稽核
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 輸血醫囑表 (接收 CIRS 訂單)
CREATE TABLE IF NOT EXISTS transfusion_orders (
    id TEXT PRIMARY KEY,               -- TX-YYYYMMDD-NNN
    cirs_order_id TEXT,                -- CIRS 端的原始 Order ID
    patient_id TEXT,                   -- 只存 ID，不存病患詳細資料
    blood_type TEXT NOT NULL,
    unit_type TEXT DEFAULT 'PRBC',
    quantity INTEGER NOT NULL,
    priority TEXT DEFAULT 'ROUTINE',   -- STAT, URGENT, ROUTINE
    status TEXT DEFAULT 'PENDING',     -- PENDING, CROSSMATCHED, RESERVED, ISSUED, CANCELLED

    -- 配血資訊
    crossmatch_result TEXT,            -- COMPATIBLE, INCOMPATIBLE
    crossmatch_by TEXT,
    crossmatch_at TIMESTAMP,

    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 配血紀錄表 (稽核用)
CREATE TABLE IF NOT EXISTS crossmatch_log (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    blood_unit_id TEXT NOT NULL,
    result TEXT NOT NULL,              -- COMPATIBLE, INCOMPATIBLE
    performed_by TEXT NOT NULL,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);
```

### 4.2 View 定義（單一狀態來源）

```sql
-- 血品可用性 View（Gemini 建議）
CREATE VIEW IF NOT EXISTS v_blood_availability AS
SELECT
    blood_type,
    unit_type,

    -- 物理庫存
    COUNT(*) AS physical_count,

    -- 已預約數量
    SUM(CASE WHEN status = 'RESERVED' THEN 1 ELSE 0 END) AS reserved_count,

    -- 可用庫存 = 物理 - 預約
    SUM(CASE WHEN status = 'AVAILABLE' THEN 1 ELSE 0 END) AS available_count,

    -- 即將過期 (3天內)
    SUM(CASE
        WHEN status = 'AVAILABLE'
        AND expiry_date <= DATE('now', '+3 days', 'localtime')
        AND expiry_date > DATE('now', 'localtime')
        THEN 1 ELSE 0
    END) AS expiring_soon_count,

    -- 已過期
    SUM(CASE
        WHEN expiry_date < DATE('now', 'localtime')
        THEN 1 ELSE 0
    END) AS expired_count,

    -- 最近效期 (FIFO 用)
    MIN(CASE WHEN status = 'AVAILABLE' THEN expiry_date END) AS nearest_expiry

FROM blood_units
WHERE status NOT IN ('DISPOSED', 'ISSUED')
GROUP BY blood_type, unit_type;

-- 單一血袋狀態 View（UI 綁定用）
CREATE VIEW IF NOT EXISTS v_blood_unit_status AS
SELECT
    bu.id,
    bu.blood_type,
    bu.unit_type,
    bu.volume_ml,
    bu.expiry_date,
    bu.status,
    bu.reserved_for_order,

    -- 計算顯示狀態（單一來源！）
    CASE
        WHEN bu.expiry_date < DATE('now', 'localtime') THEN 'EXPIRED'
        WHEN bu.status = 'RESERVED' THEN 'RESERVED'
        WHEN bu.expiry_date <= DATE('now', '+3 days', 'localtime') THEN 'EXPIRING_SOON'
        WHEN bu.status = 'AVAILABLE' THEN 'AVAILABLE'
        ELSE bu.status
    END AS display_status,

    -- 效期倒數（小時）
    CAST((julianday(bu.expiry_date) - julianday('now', 'localtime')) * 24 AS INTEGER) AS hours_until_expiry,

    -- FIFO 優先級（效期越近越優先）
    ROW_NUMBER() OVER (
        PARTITION BY bu.blood_type, bu.unit_type
        ORDER BY bu.expiry_date ASC
    ) AS fifo_priority

FROM blood_units bu
WHERE bu.status NOT IN ('DISPOSED', 'ISSUED');
```

---

## 五、欄位契約表（ChatGPT 建議）

### 5.1 UI 元素 ↔ 欄位綁定

| UI 元素 | 綁定欄位 | 來源 | 顏色規則 |
|---------|---------|------|----------|
| 血袋狀態 Badge | `display_status` | `v_blood_unit_status` | AVAILABLE=綠, RESERVED=藍, EXPIRING_SOON=橘, EXPIRED=紅 |
| 可用數量 | `available_count` | `v_blood_availability` | >5=綠, 1-5=橘, 0=紅 |
| 效期倒數 | `hours_until_expiry` | `v_blood_unit_status` | >72h=綠, 24-72h=橘, <24h=紅 |
| FIFO 標籤 | `fifo_priority` | `v_blood_unit_status` | priority=1 顯示「優先使用」 |
| 庫存總覽 | `physical_count`, `reserved_count` | `v_blood_availability` | 格式：「可用 X (庫存 Y, 保留 Z)」 |

### 5.2 API → 欄位更新映射

| API Endpoint | HTTP | 更新表格 | 更新欄位 |
|--------------|------|---------|----------|
| `POST /api/blood/units` | POST | `blood_units` | 新增記錄 |
| `POST /api/blood/units/{id}/reserve` | POST | `blood_units` | `status`, `reserved_for_order`, `reserved_at`, `reserved_by` |
| `POST /api/blood/units/{id}/issue` | POST | `blood_units` | `status`, `issued_at`, `issued_by`, `issued_to_order` |
| `POST /api/blood/units/{id}/dispose` | POST | `blood_units` | `status` → DISPOSED |
| `POST /api/blood/crossmatch` | POST | `crossmatch_log`, `transfusion_orders` | 配血結果 |

---

## 六、效期阻擋機制（Gemini 建議）

### 6.1 三層防護

```
┌─────────────────────────────────────────────────────────────┐
│                     效期阻擋三層防護                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: View 過濾                                          │
│  ─────────────────                                          │
│  v_blood_unit_status 自動標記 display_status = 'EXPIRED'    │
│  UI 列表預設過濾掉 EXPIRED 血袋                              │
│                                                             │
│  Layer 2: 掃碼阻擋                                           │
│  ─────────────────                                          │
│  掃描血袋條碼時，若 hours_until_expiry < 0：                 │
│  - 全螢幕紅色 Modal                                          │
│  - 震動 + 警報聲                                             │
│  - 必須手動關閉，無法繞過                                    │
│                                                             │
│  Layer 3: API 拒絕                                           │
│  ─────────────────                                          │
│  POST /api/blood/units/{id}/issue：                         │
│  - 檢查 expiry_date < now → 返回 403 BLOOD_EXPIRED          │
│  - 記錄到 audit_log                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 UI 實作

```javascript
// 掃碼時的效期檢查
async function onBloodUnitScanned(unitId) {
    const unit = await fetchBloodUnit(unitId);

    if (unit.display_status === 'EXPIRED') {
        // Layer 2: 全螢幕阻擋
        showExpiryBlocker({
            title: '血品已過期',
            message: `血袋 ${unitId} 已於 ${unit.expiry_date} 過期，禁止發出`,
            unitInfo: unit,
            requireManualDismiss: true,
            playAlertSound: true,
            vibrate: true
        });
        return; // 阻擋後續流程
    }

    if (unit.display_status === 'EXPIRING_SOON') {
        // 警告但不阻擋
        showExpiryWarning({
            title: '血品即將過期',
            message: `剩餘 ${unit.hours_until_expiry} 小時`,
            allowProceed: true
        });
    }

    // 繼續正常流程
    proceedWithIssue(unit);
}
```

---

## 七、PWA 結構

### 7.1 目錄結構

```
/Users/QmoMBA/Downloads/MIRS-v2.0-single-station/
├── frontend/
│   ├── biomed/           # 既有 BioMed PWA
│   └── blood/            # 新增 Blood PWA
│       ├── index.html
│       ├── manifest.json
│       ├── service-worker.js
│       └── icons/
│           ├── icon-192x192.png
│           └── icon-512x512.png
├── routes/
│   └── blood.py          # Blood API routes
└── main.py               # 新增 Blood PWA 路由掛載
```

### 7.2 Service Worker Scope 隔離

```javascript
// blood/service-worker.js
const CACHE_NAME = 'mirs-blood-v1.0.0';
const SCOPE = '/blood/';  // 獨立 scope，不與其他 PWA 衝突

// manifest.json
{
    "name": "MIRS Blood Bank",
    "short_name": "Blood",
    "scope": "/blood/",
    "start_url": "/blood/",
    ...
}
```

---

## 八、實作階段（Strangler Pattern）

### P0: 契約與路由（1 天）

- [ ] 建立欄位契約表（本文件 Section 5）
- [ ] 建立 API→欄位映射表（本文件 Section 5.2）
- [ ] 建立 blood_units, transfusion_orders 表
- [ ] 建立 v_blood_availability, v_blood_unit_status View
- [ ] 新增 routes/blood.py 骨架
- [ ] main.py 掛載 /blood/ 路由

### P1: 最小可用 Blood PWA（2 天）

- [ ] 血袋入庫 (Receive)
- [ ] 可用性/效期清單 (List)
- [ ] 基本出庫 (Issue)
- [ ] 效期阻擋機制
- [ ] Service Worker + 離線支援

### P2: 臨床流程整合（2 天）

- [ ] 接收 CIRS 輸血醫囑 (Order)
- [ ] 配血執行 (Crossmatch)
- [ ] 預約血袋 (Reserve)
- [ ] FIFO 優先提示

### P3: MIRS 主站血品 Tab 遷移（1 天）

- [ ] MIRS Index.html 血品 Tab → 導向 Blood PWA
- [ ] 資料遷移腳本
- [ ] 驗證與清理

---

## 九、驗收標準

### 9.1 功能驗收

- [ ] 新裝置開啟 /blood/ 正確載入 Blood PWA
- [ ] 血袋入庫後，available_count 正確增加
- [ ] 預約血袋後，available_count 減少，reserved_count 增加
- [ ] 過期血袋無法出庫（三層阻擋皆生效）
- [ ] FIFO 標籤正確標示「優先使用」血袋

### 9.2 BioMed 教訓驗收

- [ ] UI 只綁定 View 欄位（`display_status`），不混用 `status`
- [ ] API 更新後，View 聚合狀態正確反映
- [ ] 樂觀更新不被 reload 覆蓋
- [ ] 多 PWA 安裝不互相污染 SW 快取

### 9.3 臨床安全驗收

- [ ] 過期血袋掃碼時顯示全螢幕阻擋
- [ ] 即將過期血袋（<72h）顯示橘色警告
- [ ] 庫存顯示格式：「可用 X (庫存 Y, 保留 Z)」

---

## 十、風險與緩解

| 風險 | 等級 | 緩解措施 |
|------|------|----------|
| 效期時區問題 | P0 | View 統一使用 `DATE('now', 'localtime')` |
| 預約未釋放 | P1 | 新增 `reserve_expires_at` 欄位，定時釋放過期預約 |
| CIRS 訂單同步失敗 | P1 | 離線 Queue + 重試機制 |
| 欄位契約違反 | P0 | Code Review Checklist + 自動化測試 |

---

## 附錄 A: 與 BioMed PWA 的對比

| 維度 | BioMed PWA | Blood PWA |
|------|------------|-----------|
| 核心邏輯 | 每日檢查 (Check) | 預約與發放 (Reserve/Issue) |
| 狀態複雜度 | 簡單 (CHECKED/UNCHECKED) | 複雜 (AVAILABLE/RESERVED/ISSUED/EXPIRED) |
| 效期處理 | 警示 | 阻擋 |
| 跨系統整合 | 無 | CIRS Order 整合 |
| 臨床風險 | 中 | 高 |

---

## 附錄 B: 參考文件

- `docs/DEV_SPEC_BIOMED_v1.2.9_BUGFIX.md` - BioMed 欄位契約問題修復
- `docs/DEV_SPEC_FALLBACK_GUARD_v1.1.md` - PWA 配對機制
- `docs/xIRS_CLINICAL_WORKFLOW_SPEC_v1.0.md` - 臨床流程規格

---

**文件完成**
**撰寫者**: Claude Code
**審閱者**: Gemini + ChatGPT (意見整合)
**日期**: 2026-01-12
