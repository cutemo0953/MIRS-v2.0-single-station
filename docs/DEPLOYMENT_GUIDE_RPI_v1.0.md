# MIRS RPi 部署指南

**版本**: 1.0
**日期**: 2026-01-26
**適用**: Raspberry Pi 5 (ARM64)

---

## 目錄

1. [硬體需求](#1-硬體需求)
2. [作業系統安裝](#2-作業系統安裝)
3. [首次部署 (開發模式)](#3-首次部署-開發模式)
4. [生產模式部署](#4-生產模式部署)
5. [OTA 自動更新設定](#5-ota-自動更新設定)
6. [多站點部署](#6-多站點部署)
7. [維護與監控](#7-維護與監控)
8. [故障排除](#8-故障排除)

---

## 1. 硬體需求

### 1.1 最低配置

| 項目 | 規格 |
|------|------|
| 機型 | Raspberry Pi 5 |
| RAM | 4GB (8GB 建議) |
| 儲存 | 32GB microSD (64GB 建議) |
| 電源 | 官方 27W USB-C 電源 |
| 散熱 | 主動散熱風扇 (建議) |

### 1.2 選配

| 項目 | 用途 |
|------|------|
| RTC 模組 (DS3231) | 斷電保持時間 |
| UPS 電池模組 | 停電保護 |
| 外接 SSD | 更高 I/O 效能 |

---

## 2. 作業系統安裝

### 2.1 下載 Raspberry Pi OS

使用 [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

1. 選擇 **Raspberry Pi OS (64-bit)** (Debian Bookworm)
2. 進階設定:
   - 主機名稱: `DNO-HC01` (或自訂)
   - 使用者: `dno` / 密碼: `<設定強密碼>`
   - SSH: 啟用
   - Wi-Fi: 設定診所網路 (或使用有線)
   - 時區: `Asia/Taipei`

### 2.2 首次開機設定

```bash
# SSH 連線
ssh dno@DNO-HC01.local
# 或使用 IP
ssh dno@10.0.0.1

# 更新系統
sudo apt update && sudo apt upgrade -y

# 安裝必要套件
sudo apt install -y git python3-pip python3-venv \
    build-essential libffi-dev libssl-dev \
    fonts-noto-cjk  # 中文字型 (PDF 需要)
```

### 2.3 設定固定 IP (選用)

```bash
sudo nmcli con mod "Wired connection 1" \
    ipv4.addresses 10.0.0.1/24 \
    ipv4.gateway 10.0.0.254 \
    ipv4.dns 8.8.8.8 \
    ipv4.method manual

sudo nmcli con up "Wired connection 1"
```

---

## 3. 首次部署 (開發模式)

開發模式使用 Python 原始碼運行，方便調試。

### 3.1 Clone 專案

```bash
cd ~
git clone https://github.com/cutemo0953/MIRS-v2.0-single-station.git
cd MIRS-v2.0-single-station
```

### 3.2 安裝 Python 依賴

```bash
# Python 3.12+ 需要 --break-system-packages
pip3 install --user --break-system-packages -r requirements.txt

# PDF 相關 (可選)
pip3 install --user --break-system-packages weasyprint matplotlib
```

### 3.3 建立 Systemd Service

```bash
sudo tee /etc/systemd/system/mirs.service > /dev/null << 'EOF'
[Unit]
Description=Medical Inventory Resilience System (MIRS) - Development
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/MIRS-v2.0-single-station

# Development mode (Python source)
ExecStart=/usr/bin/python3 /home/dno/MIRS-v2.0-single-station/main.py

# Environment
Environment=MIRS_PORT=8000
Environment=MIRS_DB_PATH=/home/dno/MIRS-v2.0-single-station/data/medical_inventory.db

# OTA disabled in development
Environment=MIRS_OTA_AUTO_UPDATE=false

# Restart policy
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mirs

[Install]
WantedBy=multi-user.target
EOF
```

### 3.4 啟動服務

```bash
sudo systemctl daemon-reload
sudo systemctl enable mirs
sudo systemctl start mirs

# 確認狀態
sudo systemctl status mirs
curl http://localhost:8000/api/health
```

### 3.5 開發階段更新流程

```bash
# 從 Mac 同步代碼
# (在 Mac 上執行)
./scripts/sync_to_rpi.sh

# 在 RPi 上重啟
sudo systemctl restart mirs
```

---

## 4. 生產模式部署

生產模式使用 Nuitka 編譯的 ARM64 Binary，啟動更快且無需 Python 環境。

### 4.1 編譯 Binary

```bash
cd ~/MIRS-v2.0-single-station

# 確保代碼是最新的
git pull

# 執行編譯 (約 20-40 分鐘)
./scripts/build_on_rpi.sh

# 確認產出
ls -la dist/mirs-server
# 預期: ~85MB
```

### 4.2 設定生產環境

```bash
# 執行生產設定腳本
sudo ./scripts/setup_production.sh
```

此腳本會:
1. 建立 `/app` 目錄結構
2. 安裝 Binary 到 `/app/versions/{version}/`
3. 建立 `/app/mirs-server` symlink
4. 更新 systemd service 使用 binary
5. 啟用 OTA 自動更新

### 4.3 生產環境目錄結構

```
/app/
├── mirs-server -> versions/2.4.0/mirs-server  # 當前版本 symlink
├── mirs-server.backup -> versions/2.3.0/...   # 備份版本 (回滾用)
└── versions/
    ├── 2.4.0/
    │   └── mirs-server
    └── 2.3.0/
        └── mirs-server

/var/lib/mirs/
├── medical_inventory.db   # 資料庫
├── ota/
│   ├── cache/             # 下載快取
│   └── state/             # 更新狀態

/etc/mirs/
├── license.json           # 授權檔案 (選用)
└── ota_pubkey.pub         # OTA 簽章公鑰
```

### 4.4 驗證生產部署

```bash
# 服務狀態
systemctl status mirs

# 健康檢查
curl http://localhost:8000/api/health

# OTA 狀態
curl http://localhost:8000/api/ota/status

# 查看 logs
journalctl -u mirs -f
```

---

## 5. OTA 自動更新設定

### 5.1 環境變數

生產模式的 systemd service 包含以下 OTA 設定:

```ini
Environment=MIRS_OTA_AUTO_UPDATE=true
Environment=MIRS_OTA_REQUIRE_SIGNATURE=true
Environment=MIRS_GITHUB_REPO=cutemo0953/xirs-releases
Environment=MIRS_OTA_SCHEDULER_ENABLED=true
Environment=MIRS_OTA_WINDOW_START=02:00
Environment=MIRS_OTA_WINDOW_END=05:00
```

### 5.2 部署公鑰

```bash
# 從開發機複製公鑰
scp ~/.minisign/ota_pubkey.pub dno@10.0.0.1:/tmp/

# 在 RPi 上安裝
sudo mkdir -p /etc/mirs
sudo mv /tmp/ota_pubkey.pub /etc/mirs/
sudo chmod 644 /etc/mirs/ota_pubkey.pub
```

### 5.3 OTA 更新時機

| 條件 | 行為 |
|------|------|
| 每小時檢查 | 自動檢查 GitHub Releases |
| 02:00-05:00 | 自動安裝更新 |
| 有進行中案件 | **不更新** (手術保護) |
| 簽章驗證失敗 | **不更新** |
| Health Check 失敗 | 自動回滾 |

### 5.4 手動觸發更新

```bash
# 檢查更新
curl http://localhost:8000/api/ota/check

# 立即更新 (跳過時段限制)
curl -X POST http://localhost:8000/api/ota/scheduler/apply-now

# 查看更新狀態
curl http://localhost:8000/api/ota/status
```

---

## 6. 多站點部署

### 6.1 站點識別

每台 RPi 需要唯一的 `station_id`:

```bash
# 編輯 config
sudo nano /etc/mirs/config.json
```

```json
{
    "station_id": "BORP-DNO-02",
    "station_type": "BORP",
    "station_name": "手術室 2 號站"
}
```

### 6.2 第二台 RPi 快速部署

```bash
# 1. 安裝 OS (同 §2)

# 2. Clone 專案
git clone https://github.com/cutemo0953/MIRS-v2.0-single-station.git
cd MIRS-v2.0-single-station

# 3. 複製已編譯的 binary (從第一台或開發機)
scp dno@10.0.0.1:/home/dno/MIRS-v2.0-single-station/dist/mirs-server ./dist/

# 4. 執行生產設定
sudo ./scripts/setup_production.sh

# 5. 部署公鑰
sudo mkdir -p /etc/mirs
scp dno@10.0.0.1:/etc/mirs/ota_pubkey.pub /tmp/
sudo mv /tmp/ota_pubkey.pub /etc/mirs/

# 6. 設定站點 ID
sudo nano /etc/mirs/config.json
# 修改 station_id

# 7. 重啟
sudo systemctl restart mirs
```

### 6.3 授權部署

每台 RPi 需要獨立的 license:

```bash
# 複製授權檔案
scp license-station-02.json dno@10.0.0.2:/tmp/
sudo mv /tmp/license-station-02.json /etc/mirs/license.json
```

---

## 7. 維護與監控

### 7.1 日常監控 (不需 SSH)

```bash
# 健康檢查
curl http://RPi-IP:8000/api/health

# OTA 狀態
curl http://RPi-IP:8000/api/ota/status

# Analytics Dashboard
open http://RPi-IP:8000/dashboard/
```

### 7.2 資料庫備份

```bash
# 手動備份
scp dno@10.0.0.1:/var/lib/mirs/medical_inventory.db ./backup/

# 自動備份 (cron)
0 3 * * * scp dno@10.0.0.1:/var/lib/mirs/medical_inventory.db /backup/mirs-$(date +\%Y\%m\%d).db
```

### 7.3 日誌查看

```bash
# 即時日誌
journalctl -u mirs -f

# 最近 100 行
journalctl -u mirs -n 100 --no-pager

# 特定時間範圍
journalctl -u mirs --since "2026-01-26 08:00" --until "2026-01-26 12:00"
```

### 7.4 系統資源

```bash
# CPU/記憶體
htop

# 磁碟空間
df -h

# 資料庫大小
ls -lh /var/lib/mirs/medical_inventory.db
```

---

## 8. 故障排除

### 8.1 服務無法啟動

```bash
# 查看錯誤
journalctl -u mirs -n 50 --no-pager

# 常見問題:
# 1. 資料庫路徑錯誤
# 2. Port 被佔用
# 3. Python 依賴缺失
```

### 8.2 OTA 更新失敗

```bash
# 查看 OTA 日誌
journalctl -u mirs | grep -i ota

# 常見問題:
# 1. 簽章驗證失敗 -> 檢查公鑰
# 2. 下載失敗 -> 檢查網路
# 3. 磁碟空間不足 -> 清理舊版本
```

### 8.3 手動回滾

```bash
# 查看可用版本
ls /app/versions/

# 手動切換版本
sudo systemctl stop mirs
sudo ln -sf /app/versions/2.3.0/mirs-server /app/mirs-server
sudo systemctl start mirs
```

### 8.4 重置為開發模式

```bash
# 停止生產服務
sudo systemctl stop mirs

# 恢復開發模式 service
sudo tee /etc/systemd/system/mirs.service > /dev/null << 'EOF'
[Unit]
Description=MIRS - Development
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/MIRS-v2.0-single-station
ExecStart=/usr/bin/python3 /home/dno/MIRS-v2.0-single-station/main.py
Environment=MIRS_PORT=8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start mirs
```

### 8.5 常用除錯命令

```bash
# 測試 binary 直接執行
cd /app && ./mirs-server

# 檢查 port 占用
sudo lsof -i :8000

# 檢查 systemd 設定
systemctl cat mirs

# 重新載入 systemd
sudo systemctl daemon-reload
```

---

## 附錄 A: 環境變數參考

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `MIRS_PORT` | 8000 | HTTP 服務 port |
| `MIRS_DB_PATH` | `./data/medical_inventory.db` | 資料庫路徑 |
| `MIRS_DATA_DIR` | `/var/lib/mirs` | 資料目錄 |
| `MIRS_APP_DIR` | `/app` | 應用程式目錄 |
| `MIRS_OTA_AUTO_UPDATE` | false | 自動更新開關 |
| `MIRS_OTA_REQUIRE_SIGNATURE` | true | 強制簽章驗證 |
| `MIRS_GITHUB_REPO` | `cutemo0953/xirs-releases` | 更新源 |
| `MIRS_OTA_WINDOW_START` | 02:00 | 更新時段開始 |
| `MIRS_OTA_WINDOW_END` | 05:00 | 更新時段結束 |

---

## 附錄 B: 快速檢查清單

### 開發模式

- [ ] Git clone 成功
- [ ] Python 依賴安裝完成
- [ ] systemd service 建立
- [ ] `curl /api/health` 返回 healthy
- [ ] 可從 Mac 同步代碼

### 生產模式

- [ ] Binary 編譯成功 (~85MB)
- [ ] `setup_production.sh` 執行成功
- [ ] OTA 公鑰已部署
- [ ] `curl /api/ota/status` 顯示 enabled
- [ ] 更新時段設定正確

### 多站點

- [ ] 每站唯一 station_id
- [ ] 每站獨立 license (如需)
- [ ] 網路互通性測試

---

*MIRS RPi Deployment Guide v1.0*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
