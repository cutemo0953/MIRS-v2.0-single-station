# MIRS 更新日誌 (Changelog)

所有重大變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

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
