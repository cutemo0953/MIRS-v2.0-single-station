# MIRS Vercel 部署指南 v1.4.6

## 概述

MIRS (Medical Inventory Resilience System) 可部署至 Vercel 作為線上展示版本。

**v1.4.6 新增 PostgreSQL 支援**:
- 設定 `DATABASE_URL` 環境變數可連接 Neon 雲端資料庫
- 資料持久保存，不受 Lambda 冷啟動影響
- 無 DATABASE_URL 時退回記憶體模式（資料會重置）

## 部署網址

- **Demo**: https://mirs-demo.vercel.app
- **GitHub**: https://github.com/cutemo0953/medical-inventory-system_v1.4.5 (branch: `v1.4.2-plus`)

## 檔案結構

```
MIRS-v2.0-single-station/
├── api/
│   ├── index.py          # Vercel serverless 入口
│   └── requirements.txt  # Python 依賴
├── vercel.json           # Vercel 配置
├── seeder_demo.py        # 展示資料植入
├── main.py               # FastAPI 主程式 (已修改支援 Vercel)
└── Index.html            # 前端 (已修改 API URL 偵測)
```

## 關鍵修改

### 1. 環境偵測 (`main.py`)

```python
IS_VERCEL = os.environ.get("VERCEL") == "1"
PROJECT_ROOT = Path(__file__).parent
```

### 2. 記憶體資料庫支援 (`main.py`)

```python
class Config:
    DATABASE_PATH = ":memory:" if IS_VERCEL else "medical_inventory.db"
```

### 3. NonClosingConnection 包裝器 (`main.py`)

解決記憶體模式下連接被關閉的問題：

```python
class NonClosingConnection:
    """包裝連接，忽略 close() 調用 (用於記憶體模式)"""
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def close(self):
        """忽略關閉請求"""
        pass

    # ... 其他方法委派給 _conn
```

### 4. API URL 偵測 (`Index.html`)

```javascript
const isVercelOrCloud = currentHost.includes('vercel.app') ||
                        currentHost.includes('.com') || !currentPort;
const apiBaseUrl = isVercelOrCloud ? '/api' : `http://${currentHost}:8000/api`;
```

## 部署時遇到的問題與解決方案

### 問題 1: FUNCTION_INVOCATION_FAILED

**症狀**: 500 錯誤，Function crashed

**原因**:
- 重複的路由處理器 (`@app.get("/")` 定義了兩次)
- 檔案路徑使用相對路徑而非 `PROJECT_ROOT`

**解決**:
- 移除重複路由
- 所有檔案路徑改用 `PROJECT_ROOT / "filename"`

### 問題 2: Cannot operate on a closed database

**症狀**: API 回傳 "Cannot operate on a closed database"

**原因**:
- 記憶體模式使用單例連接
- 各 API 方法在 `finally` 區塊中呼叫 `conn.close()`
- 關閉單例連接後，後續請求無法存取資料

**解決**:
- 建立 `NonClosingConnection` 包裝器類別
- 在記憶體模式下回傳包裝後的連接
- 包裝器的 `close()` 方法為空操作

### 問題 3: Seeder 欄位不匹配

**症狀**: 資料植入時 SQL 錯誤

**原因**: `seeder_demo.py` 使用的欄位名稱與實際 schema 不符

**解決**:
- `blood_bags`: `bag_id` → `bag_code`, `available` → `AVAILABLE`
- `equipment`: `equipment_id` → `id`, `location` → `category`
- `surgery_records`: 完全重寫欄位對應

### 問題 4: 前端 API 呼叫失敗

**症狀**: 頁面載入但資料清單空白

**原因**: 前端硬編碼 `http://${host}:8000/api`，Vercel 不使用 8000 端口

**解決**:
```javascript
const isVercelOrCloud = currentHost.includes('vercel.app') || !currentPort;
const apiBaseUrl = isVercelOrCloud ? '/api' : `http://${currentHost}:8000/api`;
```

### 問題 5: init_database() 關閉記憶體連接

**症狀**: 初始化後連接失效

**原因**: `init_database()` 在 `finally` 區塊關閉連接

**解決**:
```python
finally:
    if not self.is_memory:
        conn.close()
```

## 展示模式功能

### Demo Status API
```
GET /api/demo-status
Response: {"is_demo": true, "version": "1.4.2-plus-demo", ...}
```

### Demo Reset API
```
POST /api/demo/reset
Response: {"success": true, "message": "Demo data reset successfully"}
```

### Demo Banner
前端自動偵測展示模式並顯示警示橫幅，包含重置按鈕。

## 部署指令

```bash
# 登入 Vercel
npx vercel login

# 部署
cd ~/Downloads/MIRS-v2.0-single-station
npx vercel --prod --yes
```

## 注意事項

1. **資料暫存性**: 記憶體資料庫會在 Lambda 冷啟動時重置
2. **不支援功能**: 某些功能 (如 subprocess 呼叫) 在 Vercel 不可用
3. **靜態檔案**: 需在 `vercel.json` 中正確配置路由

## PostgreSQL/Neon 設定 (v1.4.6)

### 1. 建立 Neon 專案
```
1. 前往 https://neon.tech 註冊/登入
2. 建立新專案 (Region: 選最近的)
3. 複製 Connection String
```

### 2. 設定 Vercel 環境變數
```bash
# 在 Vercel 專案設定 > Environment Variables
DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
```

### 3. 執行資料庫 Migration
```bash
# 使用 Neon SQL Editor 或 psql 執行
# /tmp/neon_migration.sql 包含完整 schema
```

### 4. 驗證連線
```bash
curl https://mirs-demo.vercel.app/api/health
# 應回傳 {"status": "healthy", "database": "postgresql"}
```

## 相關文件

- [vercel.json](../vercel.json) - Vercel 配置
- [api/index.py](../api/index.py) - Serverless 入口
- [seeder_demo.py](../seeder_demo.py) - 展示資料
- [db_postgres.py](../db_postgres.py) - PostgreSQL 相容層 (v1.4.6)
