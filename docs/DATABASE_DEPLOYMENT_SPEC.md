# MIRS 資料庫部署規範

> 解決本地開發、Vercel Demo、樹莓派部署的資料庫不一致問題

**建立日期**: 2025-12-20
**版本**: v1.0

---

## 1. 問題摘要

### 1.1 現況問題

| 環境 | 資料庫 | 問題 |
|------|--------|------|
| 本地開發 | `medical_inventory.db` (SQLite) | 完整 schema，累積所有功能 |
| Vercel Demo | Serverless (無狀態) | 使用 in-memory 或 mock data |
| 樹莓派 | `medical_inventory.db` (舊版) | Schema 不完整，缺少新表/欄位 |

### 1.2 根本原因

1. **Git 不追蹤資料庫檔案**：`.gitignore` 排除 `*.db`
2. **Schema 演進未版本控制**：新功能加表/欄位，但沒有遷移腳本
3. **seeder_demo.py 不完整**：只建立部分表格，缺少 Mobile API、Views 等
4. **多環境架構差異**：Vercel serverless vs 樹莓派 persistent storage

---

## 2. 資料庫表格完整清單

### 2.1 核心業務表格

| 表格 | 用途 | 必要性 |
|------|------|--------|
| `items` | 庫存品項 | 必要 |
| `equipment` | 設備主檔 | 必要 |
| `equipment_types` | 設備類型定義 | 必要 |
| `equipment_units` | 設備個體追蹤 (v2) | 必要 |
| `equipment_checks` | 設備檢查記錄 (legacy) | 相容性 |
| `equipment_check_history` | 設備檢查歷史 (v2) | 必要 |
| `medicines` | 藥品 | 必要 |
| `blood_bags` / `blood_inventory` | 血袋管理 | 選用 |

### 2.2 韌性估算表格 (Resilience)

| 表格 | 用途 | 必要性 |
|------|------|--------|
| `resilience_config` | 站點韌性設定 | 必要 |
| `resilience_profiles` | 消耗情境設定 | 必要 |
| `reagent_open_records` | 試劑開封追蹤 | 選用 |
| `power_load_profiles` | 電力負載設定 | 選用 |

### 2.3 Mobile API 表格

| 表格 | 用途 | 必要性 |
|------|------|--------|
| `mirs_mobile_devices` | 配對裝置 | PWA 必要 |
| `mirs_mobile_pairing_codes` | 配對碼 | PWA 必要 |
| `mirs_mobile_actions` | 離線操作記錄 | PWA 必要 |

### 2.4 視圖 (Views)

| 視圖 | 用途 |
|------|------|
| `v_equipment_status` | 設備狀態彙總 |
| `v_equipment_aggregate` | 設備聚合統計 |
| `v_resilience_equipment` | 韌性設備計算 |
| `v_daily_check_summary` | 每日檢查摘要 |

---

## 3. 解決方案

### 3.1 統一初始化腳本

建立 `scripts/init_database.py`：

```python
# 完整資料庫初始化
# 1. 建立所有必要表格
# 2. 建立所有視圖
# 3. 插入預設資料（設備類型、韌性設定等）
# 4. 可選：植入展示資料
```

### 3.2 Schema 版本控制

在資料庫中記錄 schema 版本：

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
```

### 3.3 遷移腳本流程

```
database/
├── schema/
│   ├── 001_core_tables.sql
│   ├── 002_equipment_v2.sql
│   ├── 003_resilience.sql
│   ├── 004_mobile_api.sql
│   └── 005_views.sql
├── migrations/
│   ├── migrate_001_to_002.sql
│   └── migrate_002_to_003.sql
└── seeds/
    ├── equipment_types.sql
    ├── resilience_defaults.sql
    └── demo_data.sql
```

---

## 4. 樹莓派部署流程

### 4.1 全新安裝

```bash
# 1. Clone repository
git clone https://github.com/cutemo0953/medical-inventory-system_v1.4.5.git mirs
cd mirs
git checkout v1.4.2-plus

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 初始化資料庫
python3 scripts/init_database.py --with-demo-data

# 4. 設定 systemd service
sudo cp deploy/mirs.service /etc/systemd/system/
sudo systemctl enable mirs
sudo systemctl start mirs
```

### 4.2 升級現有系統

```bash
# 1. 備份資料庫
cp medical_inventory.db medical_inventory.db.backup.$(date +%Y%m%d)

# 2. 拉取新程式碼
git pull origin v1.4.2-plus

# 3. 執行資料庫遷移
python3 scripts/migrate_database.py

# 4. 重啟服務
sudo systemctl restart mirs
```

### 4.3 重建資料庫（資料可丟棄）

```bash
# 備份後刪除
mv medical_inventory.db medical_inventory.db.old
python3 scripts/init_database.py --with-demo-data
sudo systemctl restart mirs
```

---

## 5. Vercel Demo 策略

由於 Vercel serverless 無法持久化 SQLite：

1. **in-memory 資料**：每次請求載入預設資料
2. **外部資料庫**：使用 PostgreSQL (Supabase/Neon) - 未來考慮
3. **Static Demo**：純前端展示，API 返回固定資料

目前採用策略 1，在 `main.py` 中：
- 偵測 `VERCEL` 環境變數
- 使用 `:memory:` 資料庫
- 啟動時自動載入 demo data

---

## 6. 實作優先順序

### Phase 1: 緊急修復（今日）
- [x] 建立此規範文件
- [ ] 建立 `scripts/init_database.py` 完整初始化腳本
- [ ] 更新 `seeder_demo.py` 包含所有必要表格
- [ ] 在樹莓派測試完整流程

### Phase 2: 標準化（本週）
- [ ] 建立 schema version 機制
- [ ] 建立遷移腳本框架
- [ ] 更新 README 部署文件

### Phase 3: 自動化（未來）
- [ ] CI/CD 自動測試 schema 完整性
- [ ] 自動遷移檢測工具

---

## 附錄：常見錯誤對照

| 錯誤訊息 | 缺少的項目 | 解決方案 |
|---------|-----------|---------|
| `no such table: equipment_units` | equipment_units 表 | 執行 init_database.py |
| `no such table: resilience_config` | resilience_config 表 | 執行 init_database.py |
| `no such column: et.status_options` | equipment_types.status_options 欄位 | ALTER TABLE 或重建 |
| `no such column: endurance_type` | resilience_profiles.endurance_type 欄位 | ALTER TABLE 或重建 |
| `請選擇要檢查的單位` | equipment_units 資料為空 | 插入設備單位資料 |

---

*Document Created: 2025-12-20*
*Author: De Novo Orthopedics Inc.*
