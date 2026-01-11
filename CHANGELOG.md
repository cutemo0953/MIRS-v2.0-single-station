# MIRS 更新日誌 (Changelog)

所有重大變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

---

## [2.9.4] - 2026-01-11

### 新增 (Added)
- **BioMed PWA v1.1.0 重構**
  - MIRS 風格 Tab 導覽（水平按鈕列取代邊框底線）
  - 表格式設備列表（編號/名稱/類別/數量/狀態/操作）
  - 設備分類顯示（耗電設備 vs 其他設備）
  - 設備 CRUD 操作（✓ 確認、✎ 編輯、✕ 刪除）
  - 新增/編輯設備 Modal
  - Header 動作按鈕（新增設備、重新載入）

### 修復 (Fixed)
- **`/api/equipment` API 格式**：返回陣列而非 `{"equipment": [...]}`
- **Gateway Lobby BioMed 卡片**：改用 Tailwind 類別取代 inline style

### 檔案變更
| 檔案 | 說明 |
|------|------|
| `frontend/biomed/index.html` | 完整重寫 v1.0.0 → v1.1.0 |
| `main.py` | 修正 /api/equipment 返回格式 |
| CIRS `frontend/lobby/index.html` | BioMed 卡片樣式修正 |

---

## [2.8.0-local-auth] - 2026-01-08

### 新增 (Added)
- **本地離線驗證模組** (`routes/local_auth.py`)
  - 從 CIRS Hub 同步 Policy Snapshot（權限快照）
  - 支援離線模式下的 PIN 驗證（bcrypt / SHA256 格式）
  - 簽發短效本地 Token（4 小時有效期）
  - Hub 連線狀態監控
  - 本地認證日誌追蹤

### API 端點
- `POST /api/local-auth/login` - 本地離線登入
- `POST /api/local-auth/sync-snapshot` - 同步 Policy Snapshot
- `GET /api/local-auth/snapshot-status` - 快照狀態查詢
- `GET /api/local-auth/verify-token` - 驗證本地 Token
- `GET /api/local-auth/hub-status` - CIRS Hub 連線狀態
- `GET /api/local-auth/auth-log` - 認證日誌

### 離線認證流程
1. 線上時：呼叫 `/sync-snapshot` 同步權限快照（24 小時有效）
2. 離線時：呼叫 `/login` 使用本地快照驗證 PIN
3. 本地 Token 4 小時內有效，用於 API 認證
4. 恢復連線後重新同步最新快照

### 修復 (Fixed)
- 修正 `datetime.utcnow().timestamp()` 時區 bug，改用 `time.time()`

---

## [2.9.3] - 2026-01-07

### 新增 (Added)
- **xIRS v3.0 架構定案文件**
  - `xIRS_USER_JOURNEY_JTBD.md` - 5 情境使用者旅程（輕傷/手術/轉送/補給/衛星站）
  - `xIRS_ARCHITECTURE_CONSOLIDATION.md` - 護理為核心串聯架構
  - `xIRS_FUNCTION_CONSOLIDATION.md` - Tab vs PWA 決策矩陣
  - `xIRS_ARCHITECTURE_FINAL.md` - 架構定案（三大不可逆決策）
  - `xIRS_SPRINT_BACKLOG.md` - v3.0 Sprint 任務分解

### 架構決策 (Architecture Decisions)
- **MIRS 退居引擎**：Tab 只做管理/報表，不做臨床執行
- **Nursing PWA 工作站化**：護理師是執行樞紐，串聯一切
- **執行才扣庫**：開醫囑 ≠ 真相，執行確認才扣庫存
- **HIRS 獨立產品線**：個人/家庭使用，不屬於 xIRS 臨床系統

---

## [2.9.2] - 2026-01-07

### 新增 (Added)
- **EMT 交班報告功能** (`static/emt/index.html` v3.3.1)
  - 轉送中可開啟「交班報告」模態窗
  - 顯示出發時 ISBAR/MIST 交班資訊
  - 可記錄途中事件（Vitals/用藥/O2調整/備註）
  - 途中事件自動同步至 CIRS Handoff addendum
- **DEV SPEC 文件**
  - `DEV_SPEC_MIRS_ADMIN_PORTAL.md` - 管理入口規格
  - `DEV_SPEC_ANESTHESIA_TIMELINE_UI.md` - 麻醉時間軸 UI 規格
  - `DEV_SPEC_xIRS_PAIRING_SECURITY.md` - 統一配對與安全機制規格

### 修復 (Fixed)
- **血袋入庫列表不刷新**：入庫成功後新增 `loadBloodBags()` 呼叫
- **配對模態窗滑動開關不顯示**：新增 `.toggle-switch` CSS 類別取代 Tailwind peer modifier
  - RPi 的 tailwind.min.css 不包含 peer-checked 類別
  - 改用 Alpine `:class` 綁定 + 純 CSS 實作
- **血庫 pytz 模組缺失**：新增 `pytz>=2024.1` 至 `api/requirements.txt`
- **設備檢查「請選擇單位」問題**
  - 根因：`equipment` 表為空（只有 `equipment_types` 類型定義）
  - `equipment_units.equipment_id` 應對應 `equipment.id`，非 `equipment_types.type_code`
  - 文件化正確的資料庫初始化順序：先建 equipment → 再建 equipment_units

### 文件 (Documentation)
- 更新 `DEV_SPEC_EMT_HANDOFF_v1.0.md` 至 v3.3（交班報告 + 途中事件）

---

## [2.9.1] - 2026-01-05

### 修正 (Fixed)
- **術式代碼搜尋修正**：前端 `loadSurgeryCodes()` 現在正確使用 FTS5 搜尋端點
  - 有搜尋文字時呼叫 `/codes/search?q=...` (FTS5 全文搜尋)
  - 無搜尋文字時呼叫 `/codes?page=...` (分頁列表)
  - 先前版本錯誤地將 `q` 參數傳給不支援搜尋的 `/codes` 端點

---

## [2.9.0] - 2026-01-03

### 新增 (Added)
- **EMT Transfer PWA 模組** (`/api/transfer`)
  - 病患轉送任務管理（建立、確認、出發、抵達、結案）
  - 物資需求自動計算（氧氣瓶、輸液袋、設備電量）
  - 安全係數 ×3 備量公式
  - 返站 Recheck 剩餘量登記
  - 外帶物資入庫功能
- **EMT Transfer PWA 前端** (`/static/emt/`)
  - Amber 色系 UI（同韌性估算 Tab）
  - 離線優先架構（Service Worker + IndexedDB）
  - 4 步驟流程：設定 → 整備 → 轉送 → 結案
- **資料庫 Schema** (`database/migrations/add_transfer_module.sql`)
  - `transfer_missions`: 任務主表
  - `transfer_items`: 物資清單
  - `transfer_events`: 事件日誌 (Append-Only)
  - `transfer_incoming_items`: 外帶物資
  - `consumption_rates`: 消耗率設定
- **庫存連動** (Phase 2)
  - Reserve/Issue/Return 事件連動主庫存
  - 韌性估算使用 `available = on_hand - reserved`

### 變更 (Changed)
- `main.py`: 整合 transfer router 和 schema 初始化

---

## [2.8.0] - 2026-01-03

### 新增 (Added)
- **健保手術碼完整匯入**：整合健保署第七節手術碼 1,681 筆
  - 總計 1,687 筆術式代碼（原 255 + 新增 1,432）
  - 點數範圍：140 ~ 246,516 點
  - 保留骨科常用 17 筆 `is_common=1` 標記
- **NHI 萃取腳本**：`scripts/extract_nhi_surgery_codes.py`（從 PDF 萃取）
- **合併腳本**：`scripts/merge_nhi_surgery_codes.py`（合併到 surgery_codes）
- **資料包**：`data/packs/nhi_sec7/sec7_surgery_codes_points.csv`
- **EMT Transfer PWA 規格書**：`docs/DEV_SPEC_EMT_TRANSFER_PWA.md`
  - 病患轉送物資規劃（氧氣、輸液、設備電量）
  - 安全係數 ×3 計算
  - 返站 Recheck + 外帶物資入庫流程

---

## [2.7.4] - 2026-01-03

### 新增 (Added)
- **處置耗材記錄表單 Queue 介面**：
  - 術式代碼：可搜尋、多選、自動計算遞減點數
  - 自費項目：可搜尋、多選、調整數量、顯示總計
  - 移除舊版「處置類型」文字輸入欄位

### 修復 (Fixed)
- **自費項目搜尋**：修正使用 `/selfpay/search` FTS 端點（原錯誤使用不支援搜尋的 `/selfpay`）
- **點數計算器 UI**：改用 API 計算並顯示正確的遞減比例（100%/50%/0%）

---

## [2.7.3] - 2026-01-03

### 新增 (Added)
- **自費項目 Queue 功能**：自費項目子 Tab 新增雙欄式介面
  - 左側：可點擊的品項列表（點擊加入 Queue）
  - 右側：費用清單（可調整數量、刪除、顯示總計）
  - 為未來庫存連動預留介面

### 修復 (Fixed)
- **健保點數遞減規則**：修正同類手術遞減為 100% → 50% → 50% → 0%（原錯誤為 100% → 50% → 0%）
- **分類下拉選單**：修正術式主檔快查區塊初始化，正確載入術式分類與自費分類
- **領用登記顯示問題**：修正 HTML 結構，領用登記表單現只在「藥品領用」模式顯示

---

## [2.7.0] - 2026-01-03

### 新增 (Added)
- **術中用藥功能**：在「新增處置耗材記錄」表單新增術中用藥區塊
  - 常用藥物快選：Morphine、Ketorolac、Triamcinolone、Xylocaine、Marcaine
  - 自訂藥物輸入：藥物名稱、劑量、單位
  - 表單驗證：至少需有耗材或術中用藥其一

### 變更 (Changed)
- **Tab 重組**：移除獨立「術式主檔」Tab，整合至第二位置（原「領用登記」位置）
- **處置記錄重命名**：「處置記錄」→「處置耗材記錄」，更明確標示用途
- **配色統一**：術式主檔改用 treatment 色系 (#4E5488)，與處置 Tab 一致

### 修復 (Fixed)
- **樹莓派 CSS 問題**：補齊完整 treatment 色階 (50-700) 到 `mirs-colors.css`
- **Pharma 顏色類別**：新增 `border-pharma-200`、`focus:ring-pharma-500` 等

---

## [2.5.6] - 2026-01-02

### 修復 (Fixed)
- **主頁面顏色顯示問題**：補齊 tailwind.min.css 缺少的標準顏色類別
  - 配對按鈕 (`bg-teal-600`) 現在正確顯示
  - 韌性估算 tab (`bg-amber-500`) 現在正確顯示黃色
  - 新增 Teal, Amber, Cyan, Sky, Orange, Indigo 完整色系

---

## [2.5.5] - 2026-01-02

### 修復 (Fixed)
- **Mobile PWA 離線支援**：移除 Tailwind CDN，改用本地靜態檔案
  - `static/mobile/index.html` 使用 `/static/css/tailwind.min.css`
  - 新增 primary 色系到 `mirs-colors.css`（支援 primary-50 ~ primary-900）

---

## [2.5.4] - 2026-01-01

### 新增 (Added)
- **v1.1 就診流程整合**：與 CIRS Hub 完整對接
  - Anesthesia PWA 使用新 `/waiting/anesthesia` 端點，只顯示醫師看診後勾選「需麻醉」的病患
  - 建立麻醉案例時自動通知 CIRS Hub 執行 role-claim (ANESTHESIA)
  - 結案時自動通知 CIRS Hub 清除 needs_anesthesia 標記
  - 結案後案例從「我的案例」清單移除（filter CLOSED status）
- **CSS 狀態指示器**：取代 emoji，使用純 CSS 狀態圓點

### 修復 (Fixed)
- **CIRS_HUB_URL 預設值**：改為 `http://localhost:8090` 符合 RPi 部署配置

---

## [2.5.3] - 2026-01-01

### 新增 (Added)
- **xIRS Hub-Satellite 架構**：MIRS 可作為 CIRS Hub 的 Satellite 運行（連接埠 8000）
- **完整資料庫遷移**：自動建立所有必要表格與視圖
  - `v_resilience_equipment` 視圖 - 韌性設備資料彙整
  - `equipment_types.status_options` 欄位 - 設備狀態選項
- **試劑預載**：6 種常用檢驗試劑（REA- 前綴）
- **相對路徑 API**：前端使用 `/api` 相對路徑，支援任意連接埠

### 修復 (Fixed)
- **設備檢查失敗**：修正「載入詳情失敗」錯誤
  - 新增 `equipment_types.status_options` 欄位遷移
  - 自動為韌性設備建立 `equipment_units` 記錄
- **製氧機無法確認狀態**：修正 `v_resilience_equipment` 視圖缺失
- **氧氣韌性計算**：
  - 氧氣供應取各來源的最大值（濃縮機有電時可持續供氧）
  - 新增 `summary.oxygen_hours` 和 `summary.power_hours`
  - 正確反映濃縮機+電力組合時數（而非只取鋼瓶時數）
- **Raspberry Pi 離線模式**：WiFi 熱點模式可正常運作

### 變更 (Changed)
- MIRS 預設連接埠從 8000 改為 8090（避免與 CIRS Hub 衝突）
- README 更新 xIRS 架構說明

---

## [1.4.8] - 2025-12-20

### 修復 (Fixed)

#### 樹莓派部署問題
- **SQLite Schema 錯誤**：移除 `sqlite_sequence` 保留表建立語句，修正 `equipment_types` 缺少的欄位
- **韌性估算電力/氧氣未偵測**：
  - 修正設備 `tracking_mode` 為 PER_UNIT
  - 補齊 `capacity_wh`、`fuel_rate_lph`、`output_watts` 欄位值
  - 更新 `capacity_config` 使用支援的策略（LINEAR, FUEL_BASED, POWER_DEPENDENT）
- **氧氣供應時數計算**：修正 `getOxygenHours()` 邏輯，排除受電力限制的來源，對獨立來源加總
- **人數不影響氧氣消耗**：修正 `resilience_profiles.population_multiplier` 為 1
- **PWA QR Code 404 錯誤**：新增遺漏的 `PyJWT` 依賴套件

### 新增 (Added)
- `PyJWT>=2.8.0` 加入 requirements_v1.4.5.txt 和 api/requirements.txt
- 樹莓派部署修復日誌加入 MIRS_ISSUES_AND_ROADMAP.md

### 變更 (Changed)
- DATABASE_DEPLOYMENT_SPEC.md 更新部署流程說明

---

## [1.4.7] - 2025-12-18

### 新增 (Added)
- **xIRS 安全資料交換協議 v2.0**
  - 端對端加密（Curve25519 + XSalsa20-Poly1305）
  - 數位簽章（Ed25519）防竄改
  - 防重放攻擊機制

---

## [1.4.6] - 2025-12-16

### 新增 (Added)
- **韌性估算系統**：計算站點可獨立運作時數（氧氣、電力、試劑）
- **氧氣瓶個別追蹤**：每支鋼瓶獨立追蹤充填%與狀態
- **每日設備檢查**：灰階提醒未檢查項目，自動重置（07:00am）
- **PostgreSQL 支援**：可連接 Neon 雲端資料庫
- **Vercel 部署**：支援無伺服器部署

### 修復 (Fixed)
- 氧氣濃縮機重複計算問題
- 設備檢查後 UI 響應更新

---

## [1.4.5] - 2024-11-25

### 新增 (Added)
- 多站點切換功能（TC/BORP/LOG）
- 自動範本載入（新站點自動複製設備清單）
- 手術器械命名標準化

### 修復 (Fixed)
- 處置標籤頁搜尋功能
- dispense_records 資料表結構
- 設備過濾邏輯

---

*完整版本歷史請參閱 README.md*
