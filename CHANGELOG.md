# MIRS 更新日誌 (Changelog)

所有重大變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

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
