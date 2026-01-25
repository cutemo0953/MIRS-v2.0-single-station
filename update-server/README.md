# xIRS Update Server

OTA 更新管理伺服器，為 MIRS 部署提供版本檢查和下載服務。

## 功能

- 版本檢查 (stable/beta/dev channels)
- Binary 下載
- 更新統計追蹤
- 管理員 API

## 快速開始

### 本地執行

```bash
cd update-server
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

### Docker 執行

```bash
cd update-server
docker build -t mirs-update-server .
docker run -d \
    -p 8080:8080 \
    -v $(pwd)/data:/app/data \
    -e UPDATE_SERVER_ADMIN_KEY=your-secret-key \
    mirs-update-server
```

## API 端點

### 公開 API

| 端點 | 說明 |
|------|------|
| `GET /api/v1/updates/{channel}/latest` | 檢查最新版本 |
| `GET /api/v1/updates/{channel}/all` | 列出所有版本 |
| `GET /api/v1/downloads/{filename}` | 下載 binary |
| `GET /health` | 健康檢查 |

### 管理員 API (需要 X-API-Key header)

| 端點 | 說明 |
|------|------|
| `POST /api/v1/admin/releases` | 建立新版本 |
| `POST /api/v1/admin/releases/{version}/upload` | 上傳 binary |
| `GET /api/v1/admin/stats` | 查看統計 |
| `DELETE /api/v1/admin/releases/{version}` | 停用版本 |

## 使用範例

### 檢查更新

```bash
curl "http://localhost:8080/api/v1/updates/stable/latest?current_version=2.4.0&platform=arm64"
```

回應:
```json
{
  "available": true,
  "version": "2.5.0",
  "release_notes": "Bug fixes and improvements",
  "download_url": "/api/v1/downloads/mirs-hub-2.5.0-arm64",
  "checksum": "sha256...",
  "size_bytes": 52428800,
  "breaking_changes": false
}
```

### 建立新版本 (管理員)

```bash
# 1. 建立版本記錄
curl -X POST "http://localhost:8080/api/v1/admin/releases" \
    -H "X-API-Key: your-secret-key" \
    -H "Content-Type: application/json" \
    -d '{
        "version": "2.5.0",
        "channel": "stable",
        "release_notes": "New features and bug fixes"
    }'

# 2. 上傳 binary
curl -X POST "http://localhost:8080/api/v1/admin/releases/2.5.0/upload" \
    -H "X-API-Key: your-secret-key" \
    -F "file=@dist/mirs-hub"
```

### 查看統計 (管理員)

```bash
curl "http://localhost:8080/api/v1/admin/stats" \
    -H "X-API-Key: your-secret-key"
```

## 配置

| 環境變數 | 預設值 | 說明 |
|---------|--------|------|
| `UPDATE_SERVER_DATA` | `./data` | 資料目錄 |
| `UPDATE_SERVER_ADMIN_KEY` | `dev-admin-key` | 管理員 API Key |

## 部署建議

### 生產環境 Checklist

- [ ] 設定強密碼 `UPDATE_SERVER_ADMIN_KEY`
- [ ] 使用 HTTPS (建議用 Cloudflare 或 nginx proxy)
- [ ] 備份 `data/` 目錄
- [ ] 設定監控 (health endpoint)
- [ ] 考慮使用 CDN 加速下載

### 架構建議

```
                    ┌─────────────────┐
                    │   Cloudflare    │
                    │   (CDN + SSL)   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Update Server  │
                    │   (this app)    │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
     ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
     │   RPi #1    │  │   RPi #2    │  │   RPi #N    │
     │   (MIRS)    │  │   (MIRS)    │  │   (MIRS)    │
     └─────────────┘  └─────────────┘  └─────────────┘
```

## 整合 MIRS OTA

在 MIRS 端設定環境變數:

```bash
export MIRS_UPDATE_SERVER=https://updates.example.com
```

或在 `/var/lib/mirs/config.json`:

```json
{
  "update_server": "https://updates.example.com"
}
```

## 資料結構

```
data/
├── updates.db          # SQLite 資料庫
└── releases/           # Binary 檔案
    ├── mirs-hub-2.4.0-arm64
    └── mirs-hub-2.5.0-arm64
```

## 開發

```bash
# 安裝開發依賴
pip install -r requirements.txt

# 執行測試
pytest tests/

# 啟動開發伺服器 (自動重載)
uvicorn main:app --reload --port 8080
```
