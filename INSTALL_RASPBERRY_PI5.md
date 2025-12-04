# MIRS v1.4.2-plus Raspberry Pi 5 安裝指南

> 專為 Raspberry Pi 5 + Bookworm 64-bit 設計的單站版醫療站庫存管理系統

---

## 硬體需求

- **Raspberry Pi 5** (4GB 或 8GB RAM)
- **MicroSD 卡** 32GB 以上 (建議 Class 10 或更快)
- **電源供應器** 官方 27W USB-C 電源
- **網路** WiFi 或乙太網路
- **螢幕/鍵盤** (初次設定用，之後可無頭運作)

---

## 第一階段：燒錄系統

### 步驟 1：下載 Raspberry Pi Imager

前往 https://www.raspberrypi.com/software/ 下載並安裝

### 步驟 2：燒錄設定

1. 開啟 Raspberry Pi Imager
2. **選擇裝置**: Raspberry Pi 5
3. **選擇作業系統**: Raspberry Pi OS (64-bit) - Bookworm
4. **選擇儲存裝置**: 你的 MicroSD 卡

5. **點擊齒輪圖示進入進階設定**：
   - ✅ Set hostname: `dno-hc01`
   - ✅ Enable SSH: Use password authentication
   - ✅ Set username and password:
     - Username: `dno`
     - Password: `你的密碼`
   - ✅ Configure WiFi:
     - SSID: `你的WiFi名稱`
     - Password: `WiFi密碼`
     - Country: `TW`
   - ✅ Set locale:
     - Timezone: `Asia/Taipei`
     - Keyboard layout: `us`

6. 點擊 **Write** 開始燒錄

### 步驟 3：首次開機

1. 將 MicroSD 卡插入 Raspberry Pi 5
2. 連接電源，等待開機完成 (約 2-3 分鐘)
3. 從另一台電腦透過 SSH 連線：
   ```bash
   ssh dno@dno-hc01.local
   ```
   或使用 IP 位址：
   ```bash
   ssh dno@192.168.x.x
   ```

---

## 第二階段：系統環境設定

### 步驟 1：更新系統

```bash
sudo apt update && sudo apt upgrade -y
```

### 步驟 2：安裝必要套件

```bash
# 安裝 Python 虛擬環境與 Git
sudo apt install -y python3-venv python3-pip git

# 安裝 SQLite (通常已預裝)
sudo apt install -y sqlite3
```

### 步驟 3：設定固定 IP (建議)

```bash
# 編輯網路設定
sudo nmtui
```

選擇 "Edit a connection" → 選擇你的網路 → 設定固定 IP

---

## 第三階段：安裝 MIRS

### 步驟 1：下載程式碼

```bash
cd ~

# 重要：指定 v1.4.2-plus 分支
git clone -b v1.4.2-plus https://github.com/paul0728/MIRS.git mirs-v1.4.2-plus
```

> ⚠️ **注意**：必須加上 `-b v1.4.2-plus` 才能下載單站版分支

### 步驟 2：建立虛擬環境

```bash
cd ~/mirs-v1.4.2-plus

# 建立虛擬環境
python3 -m venv venv

# 啟動虛擬環境
source venv/bin/activate
```

### 步驟 3：安裝依賴套件

```bash
# 確保在虛擬環境中 (提示符號前會顯示 (venv))
pip install --upgrade pip
pip install -r requirements_v1.4.5.txt
```

### 步驟 4：測試執行

```bash
python3 main.py
```

成功啟動後會顯示：
```
====================================
🏥 MIRS v1.4.2-plus 單站版
====================================
📍 站點 ID: BORP-DNO-01
📍 站點名稱: 谷盺備援手術室 01
🌐 服務位址: http://0.0.0.0:8000
====================================
```

用瀏覽器開啟 `http://dno-hc01.local:8000` 或 `http://[Pi的IP]:8000` 測試

按 `Ctrl+C` 停止測試

---

## 第四階段：設定開機自動啟動

### 步驟 1：建立 systemd 服務

```bash
sudo nano /etc/systemd/system/mirs.service
```

貼上以下內容 (注意將 `dno` 改成你的使用者名稱)：

```ini
[Unit]
Description=Medical Inventory Resource System (MIRS) v1.4.2-plus
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/mirs-v1.4.2-plus
ExecStart=/home/dno/mirs-v1.4.2-plus/venv/bin/python3 /home/dno/mirs-v1.4.2-plus/main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

按 `Ctrl+X`，然後 `Y`，然後 `Enter` 儲存

### 步驟 2：啟用服務

```bash
# 重新載入 systemd
sudo systemctl daemon-reload

# 啟用開機自動啟動
sudo systemctl enable mirs

# 立即啟動服務
sudo systemctl start mirs

# 檢查狀態
sudo systemctl status mirs
```

### 步驟 3：測試自動啟動

```bash
# 重新開機
sudo reboot
```

等待 1-2 分鐘後，用瀏覽器連線 `http://dno-hc01.local:8000` 確認系統已自動啟動

---

## 常用指令

### 服務管理

```bash
# 查看服務狀態
sudo systemctl status mirs

# 停止服務
sudo systemctl stop mirs

# 啟動服務
sudo systemctl start mirs

# 重新啟動服務
sudo systemctl restart mirs

# 查看即時日誌
sudo journalctl -u mirs -f

# 查看最近 100 行日誌
sudo journalctl -u mirs -n 100
```

### 更新程式碼

```bash
# 停止服務
sudo systemctl stop mirs

# 進入目錄
cd ~/mirs-v1.4.2-plus

# 拉取最新程式碼
git pull origin v1.4.2-plus

# 啟動虛擬環境並更新套件 (如有新增)
source venv/bin/activate
pip install -r requirements_v1.4.5.txt

# 重新啟動服務
sudo systemctl start mirs
```

### 資料庫備份

```bash
# 停止服務
sudo systemctl stop mirs

# 備份資料庫
cp ~/mirs-v1.4.2-plus/medical_inventory.db ~/backup_$(date +%Y%m%d).db

# 重新啟動服務
sudo systemctl start mirs
```

### 查看 IP 位址

```bash
hostname -I
```

---

## 疑難排解

### 問題 1：SSH 連線失敗

**可能原因**：
- WiFi 設定錯誤
- 密碼輸入錯誤
- SSH 未啟用

**解決方法**：
1. 接上螢幕鍵盤直接操作
2. 檢查網路連線：`ip addr`
3. 重設密碼：`passwd`
4. 確認 SSH 啟用：`sudo systemctl status ssh`

### 問題 2：服務啟動失敗

**檢查方法**：
```bash
sudo journalctl -u mirs -n 50
```

**常見原因**：
- 路徑錯誤 → 確認 `/home/dno/mirs-v1.4.2-plus` 存在
- 缺少套件 → 執行 `pip install -r requirements_v1.4.5.txt`
- 權限問題 → 確認檔案擁有者是正確的使用者

### 問題 3：網頁打不開

**檢查方法**：
```bash
# 確認服務正在運行
sudo systemctl status mirs

# 確認 port 8000 有在監聽
sudo lsof -i :8000
```

**解決方法**：
- 確認防火牆未阻擋：`sudo ufw status`
- 確認用正確的 IP 或 hostname 連線

### 問題 4：時間不對

**解決方法**：
```bash
# 設定時區
sudo timedatectl set-timezone Asia/Taipei

# 確認時間
date
```

---

## 站點設定

站點設定檔位於 `config/station_config.json`：

```json
{
  "version": "1.4.2-plus",
  "station": {
    "type": "BORP",
    "org": "DNO",
    "number": "01",
    "name": "谷盺備援手術室 01"
  },
  "organization": {
    "code": "DNO",
    "name": "De Novo Orthopedics"
  },
  "system": {
    "timezone": "Asia/Taipei",
    "language": "zh-TW",
    "auto_backup_enabled": true
  }
}
```

修改後重新啟動服務：
```bash
sudo systemctl restart mirs
```

---

## 版本資訊

- **MIRS 版本**: v1.4.2-plus (單站版)
- **適用硬體**: Raspberry Pi 5
- **作業系統**: Raspberry Pi OS Bookworm (64-bit)
- **Python**: 3.11+

---

## 支援

- **GitHub Issues**: https://github.com/paul0728/MIRS/issues
- **Email**: tom@denovortho.com

---

*De Novo Orthopedics Inc. © 2024*
