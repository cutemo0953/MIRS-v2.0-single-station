# MIRS 開發議題與路線圖

> 記錄待解決問題、設計討論、與未來規劃

**更新日期**: 2026-01-25
**版本**: v0.7 (P2-01 HLC + P2-02 Analytics Dashboard 完成)

---

## 🎯 架構原則 (Gemini + ChatGPT 審核)

### 三大硬約束

| 約束 | 說明 | 來源 |
|------|------|------|
| **No DB Merge** | 併站不做 SQLite 合併，用「批量調撥 (Liquidation)」 | Gemini #2, ChatGPT #3 |
| **Idempotent Ensure** | Hotfix 必須轉成可重複執行的 ensure 函數 | Gemini #1, ChatGPT #1 |
| **Logic Lock > UI Hide** | 藥局站禁用角色切換是邏輯層鎖定，非隱藏按鈕 | Gemini #3, ChatGPT P0#3 |

### 系統邊界 (ChatGPT)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Gateway Lobby (唯一入口)                                 │
│    └── 配對閘門是權威來源，PWA 不再有第二套配對            │
│                                                             │
│ 2. Admin PWA (控制面)                                       │
│    └── 站點管理、人員名冊、韌性儀表板                      │
│    └── 不是存取閘門                                        │
│                                                             │
│ 3. 業務 PWA (執行面)                                        │
│    └── CIRS/MIRS/Pharmacy/Station                          │
│    └── 不維持第二套配對流程                                │
│    └── 只留 fallback guard (書籤/深連結)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 0. 2026-01-10 RPi 部署強化

### 0.0 手術包與韌性設備未顯示 ✅ 已解決

**問題描述**：
- 手術包 Tab 顯示 0 筆
- 韌性估算的電力/氧氣設備也未正確顯示
- 部分設備檢查時出現「請選擇要檢查的單位」

**根本原因**：
1. RPi 資料庫是用 SQL schema 手動建立，不是用 seeder
2. Seeder 檢查 `items` 表有資料就跳過完整 seeding
3. 手動建立的設備 ID（power-1, fridge-1 等）與 seeder 格式（UTIL-001, OTH-001）不同
4. 部分設備沒有對應的 `equipment_units` 記錄

**修復方法（現有 RPi）**：
```bash
# 補齊手術包和韌性設備
python3 -c "from seeder_demo import _ensure_surgical_packs, _ensure_resilience_equipment, _seed_equipment_units; import sqlite3; from datetime import datetime; conn = sqlite3.connect('medical_inventory.db'); cursor = conn.cursor(); now = datetime.now(); _ensure_resilience_equipment(cursor, now); _ensure_surgical_packs(cursor, now); _seed_equipment_units(cursor); conn.commit(); print('Done')"
```

**修復方法（新 RPi 部署）**：
- v2.8.5 新增自動 seed 功能：當 `equipment` 表為空時自動執行 seeder
- 新 RPi 只需 `git clone` + `python3 main.py` 即可

**清理重複設備**：
```bash
# 刪除舊格式設備 (power-1, fridge-1, photocatalyst-1, water-1)
python3 -c "import sqlite3; conn = sqlite3.connect('medical_inventory.db'); c = conn.cursor(); c.execute(\"DELETE FROM equipment WHERE id IN ('power-1', 'fridge-1', 'photocatalyst-1', 'water-1')\"); conn.commit(); print('Deleted:', c.rowcount)"
```

---

### 0.1 設備檢查狀態不更新 ✅ 已解決 (v2.8.4)

**問題描述**：
- 設備已檢查過（有 `last_check` 時間戳）
- 但 `status` 仍顯示 `UNCHECKED`

**根本原因**：
- 檢查 Modal 表單預填現有狀態
- 如果狀態是 `UNCHECKED`，使用者未手動更改就會提交 `UNCHECKED`

**修復內容** (Index.html:8165)：
```javascript
// 選擇單位時，UNCHECKED 自動改為 AVAILABLE
this.checkEquipmentForm.status = (unit.status === 'UNCHECKED' || !unit.status)
    ? 'AVAILABLE' : unit.status;
```

---

### 0.2 角色切換不持久 🔧 調查中 (v2.8.6)

**問題描述**：
- 切換角色後（如 EMT → NURSE）
- 重整頁面後仍顯示「後勤」

**可能原因**：
1. `init()` 沒有重讀 localStorage 中的角色
2. 瀏覽器快取舊版 JS 檔案
3. localStorage 被其他程式碼清除

**修復內容** (mirs-role-badge.js v1.1)：
1. `init()` 新增重讀 localStorage 邏輯
2. 增加 console.log 除錯輸出
3. `confirmRoleSwitch()` 新增寫入驗證

**除錯方式**：
```javascript
// 在 RPi 瀏覽器 Console 執行：
console.log('mirs_active_role:', localStorage.getItem('mirs_active_role'));
console.log('mirs_user_name:', localStorage.getItem('mirs_user_name'));

// 切換角色後再次檢查
// 重整頁面前後對比
```

**臨時解決方案**：
```bash
# 強制清除瀏覽器快取 (Chromium on RPi)
rm -rf ~/.cache/chromium
```

---

## 1. 2025-12-20 樹莓派部署修復日誌

### 0.1 SQLite Schema 問題 ✅ 已解決

**問題描述**：
- 在樹莓派執行 `sqlite3 medical_inventory.db < database/complete_schema_v1.4.2.sql` 失敗
- 錯誤訊息：`object name reserved for internal use: sqlite_sequence`
- 錯誤訊息：`no such column: type_name_en`

**根本原因**：
- `sqlite_sequence` 是 SQLite 保留的系統表，不能手動建立
- `equipment_types` 表缺少 `type_name_en` 欄位

**修復內容**：
- 從 schema SQL 移除 `CREATE TABLE sqlite_sequence` 語句
- 在 `equipment_types` CREATE TABLE 加入 `type_name_en` 欄位

---

### 0.2 韌性估算電力/氧氣未顯示 ✅ 已解決

**問題描述**：
- 韌性估算頁面未偵測到電力/氧氣設備
- 設備狀態列和編輯按鈕未顯示

**根本原因**：
1. 設備 `tracking_mode` 為 AGGREGATE，需要 PER_UNIT 才有 unit 管理功能
2. 設備缺少 `capacity_wh`、`fuel_rate_lph` 等必要欄位
3. `capacity_config` 使用不支援的策略（如 BATTERY, CAPACITY_BASED）

**修復內容**：
- 更新 equipment 的 tracking_mode 為 PER_UNIT
- 設定正確的 capacity_wh、fuel_rate_lph、output_watts 值
- 更新 equipment_types.capacity_config 使用支援的策略（LINEAR, FUEL_BASED, POWER_DEPENDENT, NONE）

---

### 0.3 氧氣供應時數計算錯誤 ✅ 已解決

**問題描述**：
- 氧氣鋼瓶 152.8h + 氧氣濃縮機 41.5h（受電力限制）
- 系統顯示 41.5h（取最小值），應顯示 152.8h（鋼瓶獨立供應）

**根本原因**：
- `getOxygenHours()` 使用 `Math.min()` 取所有氧氣來源的最小值
- 未區分「獨立來源」與「依賴電力的來源」

**修復內容**：
- 修改 Index.html 的 `getOxygenHours()` 邏輯
- 排除 `dependency.is_limiting = true` 的來源
- 對獨立來源使用加總，非取最小值

---

### 0.4 人數不影響氧氣消耗 ✅ 已解決

**問題描述**：
- 調整插管患者人數，氧氣供應時數不變
- 電力供應時數會正確響應人數變化

**根本原因**：
- `resilience_profiles` 中氧氣相關的 `population_multiplier` 設為 0

**修復內容**：
- 更新 OXYGEN 類型 profile 的 `population_multiplier = 1`

---

### 0.5 PWA QR Code 無法產生 ✅ 已解決

**問題描述**：
- Hub 配對模態窗可選擇身分與功能開關
- QR Code 圖片無法顯示（404 錯誤）
- curl localhost 可以，curl 10.42.0.1 返回 404

**根本原因**：
- 缺少 `PyJWT` 套件
- 導致 `services/mobile/auth.py` import jwt 失敗
- 整個 mobile router 未載入，所有 `/api/mirs-mobile/v1/*` 端點返回 404

**修復內容**：
1. 安裝 PyJWT：`./venv/bin/pip install PyJWT`
2. 更新 requirements_v1.4.5.txt 加入 `PyJWT>=2.8.0`
3. 更新 api/requirements.txt 加入 `PyJWT>=2.8.0`

**診斷指令**：
```bash
# 檢查 Mobile API 是否啟用
sudo journalctl -u mirs -n 50 | grep -i "mobile\|jwt"

# 應看到「✓ MIRS Mobile API v1 已啟用」
# 而非「WARNING - MIRS Mobile API 未啟用: No module named 'jwt'」
```

---

## 1. 當前待解決問題

### 1.1 PWA 設備檢查後載入緩慢 ✅ 已解決

**問題描述**：
- PWA 提交設備檢查後，重新載入設備列表時有明顯延遲

**原因分析**：
- 設備檢查後依序呼叫：
  1. `POST /equipment/{id}/check` - 提交檢查
  2. `GET /equipment` - 重載設備列表
  3. `checkAlerts()` - 檢查警示
- 網路延遲累加造成感知緩慢

**已實作解決方案** (2025-12-20)：
- [x] 本地狀態即時更新（Optimistic UI）
- [x] 背景靜默刷新，不阻塞 UI
- [x] Toast 提示取代 alert() 彈窗

---

### 1.2 設備電量/容量百分比輸入缺失 ✅ PWA 已完成

**問題描述**：
- 行動電源站、氧氣瓶等設備需要回報剩餘電量/容量百分比
- PWA 設備模態窗沒有電量輸入欄位
- Hub 設備管理也沒有編輯電量的功能

**影響範圍**：
- 韌性估算依賴準確的電量/容量資訊
- 目前只能透過「設備巡檢」的備註欄位手動填寫

**已實作解決方案** (2025-12-20)：
- [x] 在 PWA 設備模態窗加入電量滑桿（0-100%）+ 數字輸入
- [x] 區分設備類型：
  - 供電設備（發電機、UPS、電源站）→ 顯示「電量」
  - 供氧設備（氧氣瓶）→ 顯示「氧氣容量」
  - 發電機 → 顯示「油量」
  - 非耗電設備 → 不顯示電量欄位
- [x] 後端 API 支援 `level_percent` 參數
- [ ] Hub 設備編輯加入電量欄位（Phase 2.2）

**資料結構建議**：
```json
{
  "equipment_id": "UTIL-001",
  "status": "normal",
  "level_percent": 85,     // 新增：電量/容量百分比
  "level_type": "power",   // 新增：類型 (power/oxygen/none)
  "location": "急救區",     // 待討論
  "notes": ""
}
```

---

### 1.3 設備位置（Location）欄位設計

**問題描述**：
- PWA 設備模態窗有「位置」欄位
- Hub 設備管理沒有此欄位，也無法設定
- 位置資料該從哪裡來？

**現況**：
- CIRS 有「區域」概念，但是針對「人員報到區域」
- MIRS/CIRS 都沒有「設備區域」的設定

**設計選項**：

| 選項 | 說明 | 優點 | 缺點 |
|------|------|------|------|
| A. 手動輸入 | PWA 自由輸入位置文字 | 簡單、彈性 | 無法標準化查詢 |
| B. Hub 預設 | Hub 設備編輯時設定「預設位置」 | 可標準化 | 需改 Hub UI |
| C. 整合 CIRS 區域 | 從 CIRS 讀取區域清單 | 資料一致 | 需 CIRS-MIRS 整合 |
| D. MIRS 獨立區域 | MIRS 自己管理區域清單 | 獨立運作 | 可能與 CIRS 不一致 |

**建議**：
- 短期：選項 A（手動輸入），快速可用
- 中期：選項 B（Hub 設定預設位置）
- 長期：選項 C（整合 CIRS 區域資料庫）

---

### 1.4 MIRS-CIRS 資料整合現況

**問題**：MIRS 是否會向 CIRS 詢問病患資訊？

**現況答案**：
- 目前 MIRS 單站版是獨立運作
- 沒有實作 CIRS-MIRS 的資料共享
- 病患資訊（病歷號等）目前是手動輸入

**未來整合需求**：

| 資料類型 | 來源 | 整合方式 |
|---------|------|---------|
| 病患清單 | CIRS | MIRS 查詢 CIRS API |
| 區域/位置 | CIRS | 共用區域定義表 |
| 人員名冊 | CIRS | 共用人員資料庫 |
| 物資發放記錄 | CIRS | 獨立記錄，可匯總 |

---

## 2. 新增 Spec 需求

### 2.1 建站/關站/轉移/併站流程 Spec

**需求背景**：
- 災害應變時需要快速建立新站點
- 站點可能需要轉移、併站
- 資料如何遷移？設備如何重新分配？

**🚨 硬約束：No DB Merge (Gemini 建議)**

> **千萬不要碰 DB Merge**，請用「批量調撥」的業務邏輯來解決撤站問題。
>
> 試圖將 A 站的 SQLite 檔案 merge 進 B 站，會遇到：
> - Primary Key Collision (主鍵衝突)
> - WAL 序列錯亂
> - Audit Log 語意崩壞

**✅ 替代方案：Liquidation Pattern (清算模式)**

```
併站流程 (A站 → B站)：

1. 清算 (Liquidation)
   └── A 站執行「撤站程序」
   └── 系統自動產生「全庫存調撥單 (Transfer All)」
   └── 目標設為 B 站（或 Hub）

2. 關閉 (Shutdown)
   └── A 站上傳調撥單後
   └── Token 失效
   └── 資料庫鎖定為唯讀

3. 接收 (Reception)
   └── B 站收到調撥單
   └── 執行「入庫 (Stock In)」
   └── 歷史紀錄留在 Hub 查詢
```

**優點**：
- 完全復用現有的「調撥 (Stock Transfer)」邏輯
- 不需要寫任何一行危險的 DB Merge 程式碼
- Audit Log 保持完整，可從 Hub 查詢

**建議文件結構**：

```
STATION_LIFECYCLE_SPEC.md
├── 1. 建站流程
│   ├── 1.1 硬體準備（Pi、網路、電源）
│   ├── 1.2 軟體初始化（Idempotent Migrations）
│   ├── 1.3 與 CIRS Hub 連線（配對閘門）
│   ├── 1.4 區域定義導入（從 CIRS 或手動）
│   └── 1.5 設備登記與初始庫存
│
├── 2. 關站流程 (Liquidation)
│   ├── 2.1 自動產生「全庫存調撥單」
│   ├── 2.2 上傳至 Hub 或目標站點
│   ├── 2.3 Token 失效 + DB 唯讀鎖定
│   └── 2.4 站點標記為「已關閉」
│
├── 3. 轉移流程（A站 → B站）
│   ├── 3.1 執行 Liquidation 流程
│   ├── 3.2 B 站接收調撥單
│   ├── 3.3 B 站執行 Stock In
│   └── 3.4 歷史紀錄保留在 Hub
│
├── 4. 硬約束
│   └── ⚠️ 禁止 SQLite 檔案合併
│   └── ⚠️ 禁止跨站點 PK 重複使用
│   └── ⚠️ WAL 序列由 Hub 統一管理
│
└── 5. CIRS 整合考量
    ├── 5.1 區域資料共享
    ├── 5.2 病患資料查詢
    └── 5.3 人員名冊同步
```

---

## 3. 設計討論待決

### 3.1 PWA 同步時機

**選項**：

| 時機 | 說明 | 適用場景 |
|------|------|---------|
| 即時同步 | 操作完成後立即同步 | 網路穩定環境 |
| 手動同步 | 使用者點擊「同步」按鈕 | 網路不穩環境 |
| 混合模式 | 線上即時、離線暫存 | 目前實作 |

**目前實作**：混合模式
- 線上時：操作完成立即 POST 到 Hub
- 離線時：暫存到 pendingActions，恢復連線後自動同步

---

### 3.2 設備 Level 輸入方式

**選項**：

| 方式 | UI 元件 | 精確度 |
|------|---------|--------|
| 滑桿 | `<input type="range">` | 5-10% 級距 |
| 數字輸入 | `<input type="number">` | 精確到 1% |
| 快速按鈕 | 25% / 50% / 75% / 100% | 粗略快速 |
| 混合 | 滑桿 + 數字顯示 | 兼顧速度與精確 |

**建議**：混合模式（滑桿 + 數字顯示）

---

## 4. 路線圖

### Phase 2.1（優先）✅ 已完成
- [x] 修正 PWA 設備檢查後的載入效能（Optimistic UI）
- [x] PWA 設備模態窗加入電量/容量百分比輸入（滑桿+數字）
- [x] PWA 錯誤回報 UX 優化
- [x] Hub 配對記錄查詢功能
- [x] Hub 庫存盤點記錄顏色簡化

### Phase 2.5 (P0 - Gemini/ChatGPT 建議) 🔥 新增
> **先做配對穩定化，再做任何 UI overhaul**

- [x] **Idempotent Migrations** ✅ 已完成 (v2.8.6)
  - [x] 建立 `database/migrations/` 目錄結構
  - [x] `_ensure_resilience_equipment()` 升格為 m003
  - [x] `_ensure_surgical_packs()` 升格為 m004
  - [x] `_seed_equipment_units()` 升格為 m005
  - [x] `_seed_resilience_profiles()` 升格為 m006
  - [x] 引入 `_mirs_migrations` 版本追蹤表
  - [x] `main.py` 啟動時自動執行 migrations

- [x] **Service Worker Scope 隔離** ✅ 已完成
  - [x] 各 PWA 使用獨立 CACHE_NAME (xirs-pharmacy-*, xirs-station-*, etc.)
  - [x] SW 位於各自目錄下，瀏覽器自動限制 scope
  - [x] 無快取衝突風險

- [ ] **藥局站邏輯鎖定** ✅ 已完成 (CIRS Phase 3)
  - [x] `station_type === 'PHARMACY'` 時禁用角色切換
  - [x] 保留 Factory Reset 後門

### Phase 2.8 (P2 - Commercial Appliance) ✅ 已完成 (v2.9.0)

- [x] **P2-01: HLC (Hybrid Logical Clock) 時間同步**
  - [x] `services/hlc.py` - HLC 實作
  - [x] `database/migrations/m008_hlc.py` - HLC 欄位遷移
  - [x] `routes/anesthesia.py` 整合 HLC 到 xIRS headers
  - [x] `X-XIRS-HLC` header 格式: `{physical_ms}.{logical_counter}.{node_id}`
  - [x] RPi 測試通過

- [x] **P2-02: Analytics Dashboard 進階分析儀表板**
  - [x] `routes/analytics.py` - 分析 API endpoints
    - `/api/analytics/dashboard` - 總覽
    - `/api/analytics/cases/summary` - 案例統計
    - `/api/analytics/cases/daily` - 每日趨勢
    - `/api/analytics/medications/usage` - 用藥統計
    - `/api/analytics/equipment/utilization` - 設備使用率
    - `/api/analytics/oxygen/consumption` - 氧氣消耗
  - [x] `frontend/dashboard/index.html` - Dashboard PWA (Alpine.js)
  - [x] 掛載於 `/dashboard/`
  - [x] RPi 測試通過

**MIRS Dashboard vs CIRS Dashboard**:
| CIRS | MIRS |
|------|------|
| 即時作戰控制 | 歷史分析統計 |
| 病患流量、資源同步 | 案例量、用藥、設備 |
| 醫護人員用 | 管理者用 |

### Phase 2.6
- [ ] Hub 設備管理加入「預設位置」欄位
- [ ] PWA 位置欄位改為下拉選單（從 Hub 設定讀取）
- [x] Hub 同步通知功能

### Phase 2.7 (Station Lifecycle)
- [ ] 撰寫 STATION_LIFECYCLE_SPEC.md
  - [ ] 建站流程 (Idempotent Init)
  - [ ] 關站流程 (Liquidation Pattern)
  - [ ] 轉移流程 (Bulk Transfer)
  - [ ] **硬約束：No DB Merge**
- [ ] 實作「撤站」API + UI

### Phase 3（未來 - 配對穩定後才做）
> ⚠️ 在配對與 reference data 穩定前啟動整合，會把所有錯誤混成同一團

- [ ] CIRS 區域資料共享
- [ ] 病患資料查詢整合
- [ ] 多站點資料同步

---

## 附錄：相關文件

- `MIRS_MOBILE_PWA_SPEC.md` - PWA 主要規格
- `EQUIPMENT_RESILIENCE_SPEC.md` - 設備韌性估算
- `xIRS_SECURE_EXCHANGE_SPEC_v2.md` - 站點間安全交換協議

---

*Document Created: 2025-12-20*
*Author: De Novo Orthopedics Inc.*
