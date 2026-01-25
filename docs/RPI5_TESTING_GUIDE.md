# MIRS Raspberry Pi 5 測試指南

**版本**: 1.0
**日期**: 2026-01-25
**適用**: Raspberry Pi 5 (4GB/8GB) + Bookworm OS

---

## 目錄

1. [前置準備](#1-前置準備)
2. [方式 A: 原始碼部署](#2-方式-a-原始碼部署)
3. [方式 B: Binary 部署](#3-方式-b-binary-部署)
4. [方式 C: Docker 部署](#4-方式-c-docker-部署)
5. [驗證測試](#5-驗證測試)
6. [效能基準測試](#6-效能基準測試)
7. [故障排除](#7-故障排除)

---

## 1. 前置準備

### 1.1 硬體需求

| 項目 | 最低需求 | 建議規格 |
|------|----------|----------|
| 設備 | Raspberry Pi 5 | Raspberry Pi 5 8GB |
| 記憶體 | 4GB | 8GB |
| 儲存 | 32GB microSD | 64GB+ NVMe SSD |
| 網路 | WiFi | 有線乙太網路 |
| 電源 | 5V/3A USB-C | 官方 27W 電源 |

### 1.2 作業系統

```bash
# 確認系統版本
cat /etc/os-release
# 預期: Debian GNU/Linux 12 (bookworm)

# 確認架構
uname -m
# 預期: aarch64
```

### 1.3 系統更新

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    git \
    curl \
    python3-pip \
    python3-venv \
    build-essential \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libcairo2
```

### 1.4 建立工作目錄

```bash
mkdir -p ~/MIRS
mkdir -p /var/lib/mirs
sudo chown $USER:$USER /var/lib/mirs
```

---

## 2. 方式 A: 原始碼部署

最簡單的方式，適合開發測試。

### 2.1 下載程式碼

```bash
cd ~
git clone <your-repo-url> MIRS
cd MIRS
```

### 2.2 建立虛擬環境

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements_v1.4.5.txt
```

### 2.3 初始化資料庫

```bash
mkdir -p data
# 資料庫會在首次啟動時自動建立
```

### 2.4 啟動服務

```bash
# 前景執行 (測試用)
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# 背景執行
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
```

### 2.5 驗證

```bash
curl http://localhost:8000/api/health
# 預期: {"status": "ok", ...}
```

---

## 3. 方式 B: Binary 部署

使用預編譯的 ARM64 binary，適合生產環境。

### 3.1 從開發機傳輸 (如果已編譯)

```bash
# 在開發機上 (Mac/Linux with Docker)
cd /path/to/MIRS
./scripts/build_protected.sh --export

# 傳輸到 RPi
scp dist/mirs-rpi-*.tar.gz pi@<rpi-ip>:~/
```

### 3.2 在 RPi 上編譯 (替代方案)

```bash
cd ~/MIRS

# 安裝 Nuitka
pip3 install --user nuitka ordered-set zstandard

# 執行編譯 (約 15-30 分鐘)
./scripts/build_on_rpi.sh
```

### 3.3 部署 Binary

```bash
# 解壓縮 (如果從開發機傳輸)
cd ~
tar -xzf mirs-rpi-*.tar.gz
cd mirs-rpi-*

# 或使用本地編譯的 binary
cd ~/MIRS
mkdir -p deploy
cp dist/mirs-hub deploy/
cp -r templates static frontend fonts deploy/
```

### 3.4 設定啟動腳本

```bash
cat > ~/MIRS/deploy/start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
export MIRS_DB_PATH=./data/medical_inventory.db
export MIRS_EVENTS_DB=./data/mirs.db
export MIRS_DATA_DIR=/var/lib/mirs
export TZ=Asia/Taipei
mkdir -p data exports backups
./mirs-hub
EOF

chmod +x ~/MIRS/deploy/start.sh
```

### 3.5 啟動

```bash
cd ~/MIRS/deploy
./start.sh
```

### 3.6 設定 Systemd 服務 (開機自動啟動)

```bash
# 複製服務檔
sudo cp ~/MIRS/build/mirs.service /etc/systemd/system/

# 修改路徑 (如果需要)
sudo nano /etc/systemd/system/mirs.service

# 啟用服務
sudo systemctl daemon-reload
sudo systemctl enable mirs
sudo systemctl start mirs

# 檢查狀態
sudo systemctl status mirs
```

---

## 4. 方式 C: Docker 部署

適合需要隔離環境的場景。

### 4.1 安裝 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登入以生效
```

### 4.2 載入 Image

```bash
# 從開發機傳輸
scp mirs-hub-prod.tar.gz pi@<rpi-ip>:~/

# 載入
docker load < mirs-hub-prod.tar.gz
```

### 4.3 執行

```bash
docker run -d \
    --name mirs \
    --restart unless-stopped \
    -p 8000:8000 \
    -v /var/lib/mirs:/app/data \
    -e TZ=Asia/Taipei \
    mirs-hub:prod
```

### 4.4 管理

```bash
# 查看日誌
docker logs -f mirs

# 停止
docker stop mirs

# 更新
docker pull mirs-hub:prod
docker stop mirs && docker rm mirs
# 重新 docker run ...
```

---

## 5. 驗證測試

### 5.1 基本健康檢查

```bash
# API 健康
curl -s http://localhost:8000/api/health | python3 -m json.tool

# OTA 狀態
curl -s http://localhost:8000/api/ota/status | python3 -m json.tool

# License 狀態
curl -s http://localhost:8000/api/anesthesia/license/status | python3 -m json.tool
```

### 5.2 功能測試腳本

```bash
#!/bin/bash
# test_basic.sh - 基本功能測試

BASE_URL="http://localhost:8000"

echo "=== MIRS 基本功能測試 ==="

# 1. Health Check
echo -n "1. Health Check: "
if curl -sf "$BASE_URL/api/health" > /dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# 2. Equipment List
echo -n "2. Equipment List: "
if curl -sf "$BASE_URL/api/equipment" > /dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# 3. Anesthesia Cases
echo -n "3. Anesthesia API: "
if curl -sf "$BASE_URL/api/anesthesia/cases" > /dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# 4. Oxygen Units
echo -n "4. Oxygen Tracking: "
if curl -sf "$BASE_URL/api/oxygen/units" > /dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# 5. OTA Status
echo -n "5. OTA Service: "
if curl -sf "$BASE_URL/api/ota/status" > /dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

echo "=== 測試完成 ==="
```

### 5.3 完整自動化測試

```bash
# 如果有 pytest 測試
cd ~/MIRS
source venv/bin/activate
pip install pytest requests

# 執行測試 (需要服務運行中)
pytest tests/ -v
```

---

## 6. 效能基準測試

### 6.1 啟動時間

```bash
# 測量啟動時間
time ./mirs-hub &
sleep 10
curl -s http://localhost:8000/api/health
pkill mirs-hub

# 預期:
# - Source mode: 3-5 秒
# - Binary mode: 1-2 秒
```

### 6.2 記憶體使用

```bash
# 啟動後檢查記憶體
ps aux | grep mirs
# 或
htop

# 預期:
# - 閒置: 100-200 MB
# - 負載: 200-400 MB
```

### 6.3 API 響應時間

```bash
# 安裝 ab (Apache Bench)
sudo apt install apache2-utils

# 測試 health endpoint (100 requests, 10 concurrent)
ab -n 100 -c 10 http://localhost:8000/api/health

# 預期:
# - 平均響應: < 50ms
# - 99%: < 200ms
```

### 6.4 PDF 生成測試

```bash
# 建立測試案例
CASE_ID=$(curl -s -X POST http://localhost:8000/api/anesthesia/cases \
    -H "Content-Type: application/json" \
    -d '{"patient_name":"測試病患","procedure":"測試手術"}' | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('case_id',''))")

# 測試 PDF 生成
time curl -s "http://localhost:8000/api/anesthesia/cases/$CASE_ID/pdf" -o test.pdf

# 預期: < 5 秒
```

---

## 7. 故障排除

### 7.1 服務無法啟動

```bash
# 檢查日誌
journalctl -u mirs -f

# 常見原因:
# - 端口被佔用: lsof -i :8000
# - 權限問題: ls -la /var/lib/mirs
# - 依賴缺失: pip install -r requirements_v1.4.5.txt
```

### 7.2 Binary 無法執行

```bash
# 檢查架構
file ./mirs-hub
# 預期: ELF 64-bit LSB executable, ARM aarch64

# 檢查依賴
ldd ./mirs-hub

# 如果缺少 libpango 等
sudo apt install libpango-1.0-0 libpangocairo-1.0-0
```

### 7.3 記憶體不足

```bash
# 增加 swap
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# 設定 CONF_SWAPSIZE=2048
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### 7.4 資料庫錯誤

```bash
# 檢查資料庫檔案
ls -la data/*.db

# 重建資料庫 (會清除資料!)
rm data/*.db
./mirs-hub  # 重新啟動會自動建立
```

### 7.5 網路問題

```bash
# 檢查防火牆
sudo ufw status
sudo ufw allow 8000

# 檢查監聽
netstat -tlnp | grep 8000
```

---

## 附錄: 快速部署 Checklist

```
[ ] RPi 5 已安裝 Bookworm OS
[ ] 系統已更新 (apt upgrade)
[ ] 依賴已安裝 (libpango, etc.)
[ ] 程式碼/Binary 已部署
[ ] 資料目錄已建立 (/var/lib/mirs)
[ ] 服務可啟動
[ ] Health check 通過
[ ] Systemd 服務已設定
[ ] 防火牆已開放 8000 port
[ ] 效能測試通過
```

---

## 回報問題

如遇到無法解決的問題，請提供：
1. `uname -a` 輸出
2. `journalctl -u mirs --no-pager` 日誌
3. 重現步驟

回報至: https://github.com/xirs/mirs/issues
