# xIRS Dev Spec 待完成項目總覽

**建立日期**: 2026-01-20
**目的**: 追蹤 CIRS/MIRS 各 Dev Spec 中的待完成項目，避免遺忘

---

## MIRS 待完成項目

### Blood Chain of Custody v1.1 (Phase 4)
> 檔案: `DEV_SPEC_BLOOD_CHAIN_OF_CUSTODY_v1.1.md`

- [ ] 稽核報表 (Emergency 高亮) - API ready, UI pending
- [ ] 主管簽核 UI - pending
- [ ] Operational Dashboard - pending

### Anesthesia Billing Integration v1.2 ✅ 大部分完成
> 檔案: `DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md`

**Phase 1-3: 基礎架構** ✅ 完成
- [x] 新增 `medicines` 表擴充欄位 (content_per_unit, content_unit, billing_rounding)
- [x] 實作 `calculate_billing_quantity()` 函數 (`services/anesthesia_billing.py`)
- [x] 修改 `/cases/{id}/medication` API 加入庫存扣減
- [x] 新增 `medication_usage_events` 表
- [x] 實作管制藥驗證邏輯
- [x] Anesthesia PWA 藥品選擇顯示庫存

**Phase 4: 管制藥品流程** ✅ 完成
- [x] 管制藥驗證邏輯
- [x] Break-glass 緊急流程 (`is_break_glass`, `break_glass_reason`)
- [x] 事後補核准 API (`/api/anesthesia/break-glass/{id}/approve`)

**Phase 5: Anesthesia PWA UI 整合** 🟡 部分完成
- [x] 藥品選擇顯示庫存
- [ ] 管制藥見證人 UI
- [ ] Break-glass 對話框
- [x] 扣庫結果顯示

**Phase 6: 離線支援** ✅ 完成
- [x] 離線佇列機制 (`enqueue_offline_event`, `process_offline_queue`)
- [x] 上線後同步 (`/api/anesthesia/offline-queue/process`)
- [x] 衝突處理 (`offline_conflicts` table, `mark_event_conflict`)

**Phase 5 & 6: 完整計費整合** ✅ 完成
- [x] 建立 `anesthesia_billing_events` 表
- [x] 建立 `surgical_billing_events` 表
- [x] 實作 `calculate_anesthesia_fee()` 邏輯
- [x] 實作 `calculate_surgical_fee()` 邏輯
- [x] 整合手術結案觸發 (`on_case_closed`, `/api/anesthesia/cases/{id}/close`)
- [x] 實作 `CashDeskHandoffPackage` 資料結構 (`generate_cashdesk_handoff()`)
- [x] 實作 `/cases/{id}/billing/handoff` API
- [x] 實作 `/cases/{id}/billing/export-to-cashdesk` API (`export_to_cashdesk()`)
- [x] 費率表設定 (anesthesia_fee_schedule, surgical_fee_schedule)

**Phase 7: 麻醉藥車調撥** ✅ 完成
- [x] 建立 `anesthesia_carts` 表
- [x] 建立 `cart_inventory` 表
- [x] 實作藥車調撥 API (`MED_DISPATCH` to cart)
- [x] 實作交班清點 API
- [x] 差異報告與藥師核對流程
- [ ] PWA 藥車選擇 UI

### Blood Bank PWA v2.4 (P3 優先項目)
> 檔案: `DEV_SPEC_BLOOD_BANK_PWA_v2.4.md`

- [ ] 掃碼時彈窗警示 (P3)
- [ ] 強制選擇 FIFO 建議 (可選)
- [ ] Reserve timeout → 自動釋放回 AVAILABLE (P3 排程任務)
- [ ] CIRS 重複發送 blood_issued → 只處理一次 (待 CIRS 整合)
- [ ] 24h 後未補單 → 產生待補單任務 (P3)
- [ ] 掃描非 FIFO 血袋 → 彈窗警示 (P3)

**未來整合**
- [ ] CIRS 輸血醫囑整合 (transfusion_order)
- [ ] BioMed 冰箱溫度連動 (斷電自動 Quarantine)
- [ ] Reserve Timeout 排程 (4h 自動釋放)
- [ ] 待補單追蹤機制 (Emergency Release 24h 追蹤)
- [ ] Hash Chain 簽章 (Event Sourcing 強化)
- [ ] Barcode 實際掃描整合 (ZXing/QuaggaJS)

### xIRS Gateway Lobby v2.0
> 檔案: `DEV_SPEC_xIRS_GATEWAY_LOBBY_v2.0.md`

**驗收測試**
- [ ] 新裝置開啟 `xirs.local` 自動進入 Setup Wizard
- [ ] 已配對裝置開啟 `xirs.local` 自動路由到正確 App
- [ ] 後端掛掉時 Lobby 仍能顯示友善錯誤頁面
- [ ] `/status` 頁面顯示所有服務狀態

**PWA 隔離**
- [ ] 安裝 Lobby PWA 後，CIRS PWA 仍可獨立安裝
- [ ] CIRS 離線快取不會被 Lobby 快取策略覆蓋
- [ ] 各 PWA 有獨立的 manifest 和 start_url

**向後相容**
- [ ] 訪問 `xirs.local:8000` 自動重導向到 `/app/cirs/`
- [ ] 舊的 Home Screen Icon 仍可正常使用
- [ ] 已存在的 localStorage 配對資訊被保留

**配對流程**
- [ ] QR 掃描 + 手動輸入配對碼都能正常配對
- [ ] QR 過期/無效時顯示明確錯誤訊息
- [ ] 配對完成後自動路由到正確 App

### xIRS Pairing Security
> 檔案: `DEV_SPEC_xIRS_PAIRING_SECURITY.md`

**開放問題**
- [ ] 是否需要 TOTP/2FA？
- [ ] 配對碼是否用 QR Code 取代手動輸入？
- [ ] HIRS 獨立運作時如何與 CIRS/MIRS 同步？
- [ ] 多 Hub 環境如何處理？（未來擴展）

### BioMed PWA v1.2
> 檔案: `DEV_SPEC_BIOMED_PWA_v1.2.md`

- [ ] 確認後設備清單狀態即時更新
- [ ] manifest.json 路由 (目前 404)
- [ ] 離線模式運作
- [ ] 新增 `import xxx`
- [ ] 更新 `api/requirements.txt`
- [ ] 本地 `VERCEL=1` 模式測試通過

### MIRS Admin Portal
> 檔案: `DEV_SPEC_MIRS_ADMIN_PORTAL.md`

**開放問題**
- [ ] 是否與 CIRS 共用帳號？（SSO）
- [ ] 是否需要 2FA？（戰時環境可能無網路）
- [ ] 離線模式下的認證策略？

### MIRS Mobile PWA
> 檔案: `MIRS_MOBILE_PWA_SPEC.md`

**庫存管理**
- [ ] 庫存項目詳情模態窗
- [ ] 血袋入庫功能（報到區接收捐血中心血袋、現場捐血站）
- [ ] 試劑效期追蹤
- [ ] 氧氣瓶個別追蹤
- [ ] WebSocket 即時更新
- [ ] 耗材快速消耗登記（非藥品）

**測試情境**
- [ ] 配對流程（正常 / 過期 / 錯誤碼）
- [ ] 設備檢查流程（線上 / 離線 / 手動輸入）
- [ ] 緊急發藥流程（含管制藥、未知病患）
- [ ] 離線→線上同步（ACCEPTED / ADJUSTED / REJECTED）
- [ ] 裝置撤銷流程

**裝置測試**
- [ ] iPhone Safari (iOS 15+)
- [ ] Android Chrome (Android 8+)
- [ ] iPad Safari
- [ ] Android 平板

**進階功能**
- [ ] 覆核佇列功能
- [ ] 後補病患流程
- [ ] 稽核日誌完整性

### MIRS Pharmacy Dispatch v1.1
> 檔案: `MIRS_PHARMACY_DISPATCH_SPEC_v1.1.md`

**Database**
- [ ] Add `reserved_qty` to `medication_inventory`
- [ ] Update `pharmacy_dispatch_orders` with new columns
- [ ] Add `pharmacy_dispatch_items.reserved_qty`
- [ ] Create indexes

**API**
- [ ] `POST /dispatch` - Create DRAFT
- [ ] `POST /dispatch/{id}/reserve` - Reserve inventory
- [ ] `GET /dispatch/{id}/qr` - Get QR codes
- [ ] `POST /dispatch/{id}/confirm` - Confirm & deduct (idempotent)
- [ ] `POST /dispatch/receipt` - Ingest receipt QR
- [ ] `DELETE /dispatch/{id}` - Cancel & release
- [ ] `GET /dispatch` - List with status filter

**MIRS Hub UI**
- [ ] Add "撥發給藥局" button
- [ ] Dispatch modal with target selection
- [ ] Show "可用庫存" (current - reserved)
- [ ] Two-step: Draft → Reserve → QR
- [ ] Confirm dispatch action
- [ ] Receipt scanner modal

**CIRS Pharmacy PWA**
- [ ] Handle `MED_DISPATCH` type
- [ ] **Mandatory** signature verification
- [ ] **Mandatory** target binding check
- [ ] Quarantine inbox for failed validation
- [ ] Add to local inventory on accept
- [ ] Generate `MED_RECEIPT` QR
- [ ] Track received dispatches (replay protection)

**Shared**
- [ ] Add `MED_RECEIPT` to xirs-protocol.js packet types
- [ ] Add receipt generation to xirs-qr.js

### Anesthesia Timeline UI
> 檔案: `DEV_SPEC_ANESTHESIA_TIMELINE_UI.md`

**開放問題**
- [ ] 時間軸是否需要垂直模式（手機直式）？
- [ ] 是否需要語音輸入？
- [ ] 離線時的時間同步策略？
- [ ] 與 CIRS 病歷的整合方式？

### Equipment Architecture Redesign
> 檔案: `EQUIPMENT_ARCHITECTURE_REDESIGN.md`

**Phase 1: 資料準備**
- [ ] 備份現有 SQLite 資料庫
- [ ] 撰寫 `backup.py` 自動備份腳本
- [ ] 建立 `migration_v1_to_v2.py` 框架

**Phase 2: Schema 遷移**
- [ ] 建立新表 (`equipment_types`, 新版 `equipment_units`)
- [ ] 建立 View (`v_equipment_status`, `v_resilience_equipment`)
- [ ] 遷移舊資料 (`equipment.quantity` → 對應數量的 `equipment_units`)
- [ ] 驗證遷移正確性

**Phase 3: API 開發**
- [ ] 實作 Calculator Strategy 模式
- [ ] 新增 `/api/v2/resilience/dashboard` (前端最需要)
- [ ] 新增 `/api/v2/equipment` 系列端點
- [ ] 保留 v1 API 相容層

**Phase 4: 前端整合**
- [ ] 設備管理 Tab 改用 v2 API
- [ ] 韌性估算 Tab 改用 dashboard API
- [ ] 移除 `refreshKey` 技巧
- [ ] 實作 Optimistic UI 更新

**Phase 5: 收尾**
- [ ] 功能測試清單
- [ ] 效能優化 (索引)
- [ ] 文件更新

### IRS Resilience Framework
> 檔案: `IRS_RESILIENCE_FRAMEWORK.md`

**Phase 1: MIRS 實作**
- [ ] Database schema migration
- [ ] Unit standards seed data (oxygen cylinders, fuel containers)
- [ ] Default profiles seed data
- [ ] Calculation service with dependency resolution
- [ ] API endpoints (`GET /api/resilience/status`, etc.)
- [ ] Dashboard tab UI
- [ ] Profile management UI
- [ ] Manual "Mark as Opened" for reagents
- [ ] Integration tests

**Phase 2: HIRS 對齊**
- [ ] Align data model with framework
- [ ] Add scenario profile support (simplified: 2 options)
- [ ] Add isolation target input
- [ ] Update survivalDays calculation to use new engine
- [ ] Update dashboard UI to show status levels
- [ ] Translation updates (zh-TW, en, ja)

### Database Deployment
> 檔案: `DATABASE_DEPLOYMENT_SPEC.md`

**Phase 1**
- [ ] 建立 `scripts/init_database.py` 完整初始化腳本
- [ ] 更新 `seeder_demo.py` 包含所有必要表格
- [ ] 在樹莓派測試完整流程

**Phase 2**
- [ ] 建立 schema version 機制
- [ ] 建立遷移腳本框架
- [ ] 更新 README 部署文件

**Phase 3**
- [ ] CI/CD 自動測試 schema 完整性
- [ ] 自動遷移檢測工具

### xIRS User Journey JTBD
> 檔案: `xIRS_USER_JOURNEY_JTBD.md`

**Phase 2**
- [ ] 統一庫存扣減 API（CIRS Pharmacy 呼叫 MIRS）
- [ ] 處置耗材記錄整合（Doctor 開單 → MIRS 執行）
- [ ] Runner PWA 擴充任務追蹤功能
- [ ] 確認 Cashdesk 在災難情境的角色

**Phase 3**
- [ ] 設計 Satellite 同步協議
- [ ] 新增 Ward PWA 或擴充 Doctor PWA
- [ ] 完善離線優先架構
- [ ] 統一配對與安全機制（參考 xIRS_PAIRING_SECURITY.md）

**Phase 4+**
- [ ] 多站點彙整報表
- [ ] 跨站調撥流程自動化
- [ ] AI 輔助資源調度建議

### MIRS Issues and Roadmap
> 檔案: `MIRS_ISSUES_AND_ROADMAP.md`

**Phase 2.2**
- [ ] Hub 設備編輯加入電量欄位
- [ ] Hub 設備管理加入「預設位置」欄位
- [ ] PWA 位置欄位改為下拉選單（從 Hub 設定讀取）

**Phase 3: 站台生命週期**
- [ ] 撰寫 STATION_LIFECYCLE_SPEC.md
- [ ] 實作「撤站」API + UI

**Phase 4: 整合**
- [ ] CIRS 區域資料共享
- [ ] 病患資料查詢整合
- [ ] 多站點資料同步

---

## CIRS 待完成項目

### CashDesk NHI Points v1.0
> 檔案: `DEV_SPEC_CASHDESK_NHI_POINTS_v1.0.md`

**Phase 1: Schema**
- [ ] 擴充 pricebook schema 加入 NHI 欄位
- [ ] 建立 NHI catalog 資料表
- [ ] 匯入健保支付標準檔

**Phase 2: 計算引擎**
- [ ] 實作部分負擔計算引擎
- [ ] 實作藥品部分負擔計算
- [ ] 實作免部分負擔判斷

**Phase 3: UI**
- [ ] Cashdesk PWA 收費畫面改版
- [ ] 健保項目搜尋 UI
- [ ] 明細列印格式調整

**Phase 4: 申報**
- [ ] 健保申報檔產生 (XML)
- [ ] 申報資料驗證
- [ ] 申報狀態追蹤

### CashDesk Auth
> 檔案: `DEV_SPEC_CASHDESK_AUTH.md`

**Phase 1: 基礎**
- [ ] 新增 `cashdesk_operators` 表
- [ ] 新增 `cashdesk_shifts` 表
- [ ] `/api/cashdesk/auth/login` 端點
- [ ] 前端登入畫面 + PIN pad
- [ ] 開班/關班流程
- [ ] ops_log 記錄 operator_id

**Phase 2: 授權**
- [ ] 主管 PIN 驗證
- [ ] 退費金額閾值 ($1000)
- [ ] 發票作廢授權

### Medication Formulary v1.2
> 檔案: `DEV_SPEC_MEDICATION_FORMULARY_v1.2.md`

*(需另行確認具體項目)*

### Pricebook Management UI v1.1
> 檔案: `DEV_SPEC_PRICEBOOK_MANAGEMENT_UI_v1.1.md`

*(需另行確認具體項目)*

### CashDesk Billing v2.1
> 檔案: `DEV_SPEC_CASHDESK_BILLING_v2.1.md`

*(需另行確認具體項目)*

---

## HIRS 待完成項目

### Optional Categories
> 檔案: `HIRS_OPTIONAL_CATEGORIES_SPEC.md`

**Phase 1: Data Model**
- [ ] Define `CATEGORY_DEFINITIONS` constant with i18n labels
- [ ] Define `GEAR_TAG_TEMPLATES` constant with i18n labels
- [ ] Update UserSettings store to include `activeCategories`, `customGearTags`, `petCount`, `infantCount`
- [ ] Add migration for existing users (default to core categories only)

**Phase 2: Settings UI**
- [ ] Create "Category Settings" section in Settings page
- [ ] Implement toggle switches for optional categories
- [ ] Add pet/infant count inputs (shown conditionally)
- [ ] Add i18n strings for all 3 languages

**Phase 3: Filter Bar**
- [ ] Refactor filter bar to use `activeCategories` from settings
- [ ] Style "Gear" button with dark background
- [ ] Implement gear sub-tag dropdown
- [ ] Add "Create custom tag" modal

**Phase 4: Dashboard**
- [ ] Update calculation service to handle pets/baby categories
- [ ] Create grouped display (Human / Pets / Baby)
- [ ] Add "Calculation Explanation" modal
- [ ] Separate "days" calculation from "percentage" display

**Phase 5: Item Modal**
- [ ] Update Add/Edit Item modal to show active categories only
- [ ] Add gear tag multi-select for gear items
- [ ] Handle edge case: item in disabled category

**Phase 6: Testing**
- [ ] Test all 3 languages
- [ ] Test category toggle edge cases
- [ ] Test calculation accuracy
- [ ] Performance test with many custom tags

---

## 跨系統整合待完成

| 整合項目 | 狀態 | 說明 |
|----------|------|------|
| CIRS → MIRS 藥品調撥 | 🟡 Spec Done | MED_DISPATCH protocol |
| MIRS → CashDesk Handoff | 🟡 Spec Done | Billing handoff package |
| Anesthesia → Blood Bank | ✅ 已實作 | Chain of Custody v1.1 |
| Blood Bank → CIRS 訂單 | ⏳ Pending | transfusion_order 整合 |
| BioMed → Blood Bank | ⏳ Pending | 冰箱溫度連動 |
| HIRS ↔ xIRS 同步 | ⏳ Pending | 獨立運作時同步策略 |

---

## 優先級建議

### P0 (阻斷性)
1. Anesthesia Billing Integration - 直接影響收費
2. CashDesk Auth - 收費系統安全性

### P1 (核心功能)
1. Blood Bank CIRS 整合
2. MIRS Pharmacy Dispatch
3. Equipment Architecture Redesign

### P2 (增強功能)
1. HIRS Optional Categories
2. xIRS Gateway Lobby
3. BioMed PWA 完善

### P3 (未來規劃)
1. 多站點同步
2. AI 資源調度
3. 健保申報整合

---

**文件維護**: 請在完成項目後更新此清單，標記為 `[x]`
**最後更新**: 2026-01-21
