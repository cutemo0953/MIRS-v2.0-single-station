# MIRS Admin Portal 規格書

**版本**: v1.0
**日期**: 2026-01-07
**狀態**: Draft

---

## 1. 概述

### 1.1 目的
MIRS 目前缺乏統一的管理入口。本規格定義 Admin Portal 的認證機制、功能範圍與 UI 架構。

### 1.2 與 CIRS 的差異

| 項目 | CIRS | MIRS |
|------|------|------|
| 定位 | 臨床掛號系統 | 庫存韌性系統 |
| 使用者 | 醫護、行政 | 庫房、護理長、麻醉 |
| 敏感度 | 病患資料 (PHI) | 庫存、設備、血庫 |
| 認證需求 | 必須 | 建議（設備/血庫操作追蹤）|

---

## 2. 認證機制

### 2.1 使用者角色

| 角色 | 代碼 | 權限範圍 |
|------|------|---------|
| Admin | `admin` | 全系統設定、報表、使用者管理 |
| Warehouse | `warehouse` | 庫存管理、入出庫、盤點 |
| Nurse | `nurse` | 設備檢查、血庫操作 |
| Anesthesia | `anesthesia` | 麻醉記錄、PSI 追蹤 |
| Viewer | `viewer` | 唯讀（儀表板、報表）|

### 2.2 認證選項

#### Option A: 簡易 PIN 模式（推薦用於單機部署）

```
┌─────────────────────────────┐
│   MIRS 管理系統             │
│                             │
│   請輸入管理員 PIN          │
│   ┌─────────────────────┐   │
│   │  ● ● ● ●            │   │
│   └─────────────────────┘   │
│                             │
│   [1] [2] [3]               │
│   [4] [5] [6]               │
│   [7] [8] [9]               │
│   [C] [0] [✓]               │
│                             │
└─────────────────────────────┘
```

- PIN 儲存於 `config.json` (bcrypt hash)
- 適用於：信任環境、單一據點
- 缺點：無法區分個人操作

#### Option B: 帳號密碼模式（推薦用於多站點）

```
┌─────────────────────────────┐
│   MIRS 管理系統             │
│                             │
│   帳號: [____________]      │
│   密碼: [____________]      │
│                             │
│   [登入]                    │
│                             │
│   ─ 或 ─                    │
│   [使用 CIRS 帳號登入]      │
│                             │
└─────────────────────────────┘
```

- 本地 SQLite `users` 表
- 或 SSO 至 CIRS Hub（共用帳號）
- JWT Token 有效期 8 小時

### 2.3 Session 管理

```python
# JWT Payload
{
    "sub": "admin001",
    "role": "admin",
    "station_id": "MIRS-HC01",
    "exp": 1736300000,
    "iat": 1736271200
}
```

- Token 存 `localStorage`
- 閒置 30 分鐘自動登出
- 關鍵操作需重新驗證（刪除、設定變更）

---

## 3. Portal 功能架構

### 3.1 導航結構

```
MIRS Admin Portal
├── 儀表板 (Dashboard)
│   ├── 即時庫存狀態
│   ├── 設備檢查進度
│   ├── 血庫警示
│   └── 韌性指數
│
├── 庫存管理 (Inventory)
│   ├── 物資總覽
│   ├── 入庫作業
│   ├── 出庫作業
│   ├── 盤點作業
│   └── 低量警示設定
│
├── 設備管理 (Equipment)
│   ├── 設備清單
│   ├── 新增/編輯設備
│   ├── 檢查排程
│   └── 維護記錄
│
├── 血庫 (Blood Bank)
│   ├── 血袋庫存
│   ├── 入庫作業
│   ├── 使用記錄
│   └── 效期預警
│
├── 麻醉 (Anesthesia) [if enabled]
│   ├── 案例列表
│   ├── PSI 追蹤
│   └── 術後報告
│
├── 報表 (Reports)
│   ├── 庫存異動
│   ├── 設備使用率
│   ├── 血庫統計
│   └── 韌性趨勢
│
├── 系統設定 (Settings)
│   ├── 站點資訊
│   ├── CIRS 配對
│   ├── 使用者管理
│   ├── 資料備份
│   └── 關於
│
└── 操作日誌 (Audit Log)
    ├── 依使用者篩選
    ├── 依操作類型
    └── 匯出
```

### 3.2 權限對照

| 功能 | Admin | Warehouse | Nurse | Anesthesia | Viewer |
|------|:-----:|:---------:|:-----:|:----------:|:------:|
| 儀表板 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 庫存 - 檢視 | ✓ | ✓ | ✓ | ○ | ✓ |
| 庫存 - 編輯 | ✓ | ✓ | ○ | ○ | ✗ |
| 設備 - 檢視 | ✓ | ✓ | ✓ | ○ | ✓ |
| 設備 - 編輯 | ✓ | ✓ | ○ | ○ | ✗ |
| 血庫 - 檢視 | ✓ | ○ | ✓ | ✓ | ✓ |
| 血庫 - 操作 | ✓ | ○ | ✓ | ○ | ✗ |
| 麻醉 | ✓ | ✗ | ○ | ✓ | ○ |
| 報表 | ✓ | ✓ | ○ | ○ | ✓ |
| 設定 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 操作日誌 | ✓ | ○ | ✗ | ✗ | ✗ |

✓ = 完整存取, ○ = 部分存取, ✗ = 無權限

---

## 4. UI 設計

### 4.1 響應式佈局

```
Desktop (≥1024px)         Mobile (<768px)
┌────┬────────────────┐   ┌──────────────┐
│    │                │   │ ☰ MIRS Admin │
│ N  │   Content      │   ├──────────────┤
│ A  │                │   │              │
│ V  │                │   │   Content    │
│    │                │   │              │
│    │                │   │              │
│    ├────────────────┤   ├──────────────┤
│    │ Footer         │   │ Bottom Nav   │
└────┴────────────────┘   └──────────────┘
```

### 4.2 入口點

**方案 A: 獨立 Portal 頁面**
- URL: `/admin/` 或 `/portal/`
- 獨立 HTML，與主 Index.html 分離
- 優點：程式碼分離、載入快
- 缺點：維護兩套 UI

**方案 B: Index.html 內嵌（推薦）**
- 新增 Tab「管理」
- 點擊時檢查認證狀態
- 優點：統一 UI、共用元件
- 缺點：Index.html 更大

### 4.3 登入流程

```
[使用者開啟 MIRS]
        │
        ▼
[檢查 localStorage token]
        │
   有效？─────否────▶ [顯示登入畫面]
        │                    │
       是                    │
        │                    ▼
        ▼              [輸入認證資訊]
[載入使用者權限]             │
        │                    ▼
        ▼              [驗證 API]
[顯示對應功能]               │
                        成功？
                        │   │
                       是   否
                        │   │
                        ▼   ▼
                   [發 JWT] [錯誤訊息]
```

---

## 5. 資料庫 Schema

### 5.1 使用者表（本地認證）

```sql
CREATE TABLE IF NOT EXISTS mirs_users (
    user_id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,  -- bcrypt
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'viewer',
    is_active INTEGER DEFAULT 1,
    last_login INTEGER,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    created_by TEXT
);

-- 預設 Admin（首次啟動時建立）
-- 密碼: admin123 (需首次登入後強制變更)
```

### 5.2 操作日誌表

```sql
CREATE TABLE IF NOT EXISTS mirs_audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER DEFAULT (strftime('%s', 'now')),
    user_id TEXT,
    action TEXT NOT NULL,  -- LOGIN, LOGOUT, CREATE, UPDATE, DELETE
    resource TEXT,         -- inventory, equipment, blood, etc.
    resource_id TEXT,
    old_value TEXT,        -- JSON
    new_value TEXT,        -- JSON
    ip_address TEXT,
    user_agent TEXT
);

CREATE INDEX idx_audit_timestamp ON mirs_audit_log(timestamp);
CREATE INDEX idx_audit_user ON mirs_audit_log(user_id);
```

---

## 6. API 端點

### 6.1 認證 API

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/auth/login` | POST | 登入 |
| `/api/auth/logout` | POST | 登出 |
| `/api/auth/refresh` | POST | 刷新 Token |
| `/api/auth/me` | GET | 目前使用者資訊 |
| `/api/auth/change-password` | POST | 變更密碼 |

### 6.2 使用者管理 API（Admin only）

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/users` | GET | 使用者列表 |
| `/api/users` | POST | 新增使用者 |
| `/api/users/{id}` | PUT | 編輯使用者 |
| `/api/users/{id}` | DELETE | 停用使用者 |
| `/api/users/{id}/reset-password` | POST | 重設密碼 |

### 6.3 操作日誌 API

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/audit-log` | GET | 查詢日誌 |
| `/api/audit-log/export` | GET | 匯出 CSV |

---

## 7. 實作建議

### 7.1 Phase 1: 基礎認證
1. 新增 `mirs_users` 表 + 預設 admin
2. `/api/auth/*` 端點
3. JWT middleware
4. 登入 UI（PIN 或帳密）

### 7.2 Phase 2: 權限控制
1. 角色權限檢查 middleware
2. 前端權限過濾（隱藏無權限元素）
3. 操作日誌記錄

### 7.3 Phase 3: Portal UI
1. 管理 Tab 或獨立頁面
2. 使用者管理介面
3. 報表介面

---

## 8. 安全考量

1. **密碼規則**: 最少 8 字元，含數字
2. **暴力破解防護**: 5 次失敗鎖定 15 分鐘
3. **HTTPS**: 生產環境必須
4. **Token 安全**: httpOnly cookie 或 localStorage + XSS 防護
5. **敏感操作**: 需重新輸入密碼

---

## 9. 未決問題

- [ ] 是否與 CIRS 共用帳號？（SSO）
- [ ] 是否需要 2FA？（戰時環境可能無網路）
- [ ] 離線模式下的認證策略？

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 |
