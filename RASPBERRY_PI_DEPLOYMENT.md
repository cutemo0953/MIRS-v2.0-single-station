# MIRS v1.4.5 Raspberry Pi 部署指南

## 快速參考 (已部署的系統)

### 更新系統
```bash
sudo systemctl stop mirs.service
cd ~/mirs-v1.4.2-plus   # 或你的 MIRS 目錄名稱

# 如果有 log 檔案變更，先清除
git checkout -- medical_inventory.log 2>/dev/null

git pull origin v1.4.2-plus
sudo systemctl start mirs.service
sudo systemctl status mirs.service
```

### 常用指令
```bash
# 查看狀態
sudo systemctl status mirs.service

# 重新啟動
sudo systemctl restart mirs.service

# 查看日誌
sudo journalctl -u mirs.service -f

# 查看 IP 位址
hostname -I
```

---

## 首次部署步驟

此版本已修復所有 Raspberry Pi 相容性問題，可直接部署使用。

### 1. 在 Raspberry Pi 上複製專案

```bash
cd ~
git clone https://github.com/cutemo0953/medical-inventory-system_v1.4.5.git
cd medical-inventory-system_v1.4.5
```

### 2. 安裝 Python 依賴

```bash
# 使用 apt 安裝系統套件（推薦）
sudo apt update
sudo apt install -y python3-fastapi python3-uvicorn python3-qrcode python3-pil python3-pandas

# 或使用 pip（需要 --break-system-packages 標籤）
pip3 install --break-system-packages -r requirements_v1.4.5.txt
```

### 3. 驗證程式碼

```bash
# 檢查 Python 語法
python3 -m py_compile main.py

# 應該沒有任何輸出（表示成功）
```

### 4. 首次啟動測試

```bash
python3 main.py
```

應該會看到：
```
=================================
🏥 醫療站庫存管理系統 v1.4.5 啟動中...
=================================
📡 伺服器位址: http://0.0.0.0:8000
📖 API文件: http://localhost:8000/docs
📊 健康檢查: http://localhost:8000/api/health
...
```

按 Ctrl+C 停止測試。

### 5. 設定 WiFi 熱點（可選）

如果需要讓手機直接連接 Raspberry Pi：

```bash
# 停止可能衝突的服務
sudo systemctl stop dnsmasq
sudo systemctl disable dnsmasq
sudo systemctl stop hostapd
sudo systemctl disable hostapd

# 移除 wlan0 unmanaged 限制（如果存在）
sudo mv /etc/NetworkManager/conf.d/unmanage-wlan0.conf \
        /etc/NetworkManager/conf.d/unmanage-wlan0.conf.disabled 2>/dev/null

# 創建熱點（SSID: MedicalStation, 密碼: Medical2025）
sudo nmcli device wifi hotspot ifname wlan0 ssid MedicalStation password Medical2025

# 或讓系統自動生成密碼
sudo nmcli device wifi hotspot ifname wlan0 ssid MedicalStation
# 會顯示自動生成的密碼，記錄下來
```

熱點 IP 通常是 `10.42.0.1`，訪問 http://10.42.0.1:8000

### 6. 設定開機自動啟動

```bash
# 設定使用者名稱變數
MY_USER=$(whoami)
MIRS_DIR=~/medical-inventory-system_v1.4.5

# 創建 systemd 服務檔案 (使用 sudo bash -c 避免 heredoc 問題)
sudo bash -c "cat > /etc/systemd/system/mirs.service << 'ENDOFFILE'
[Unit]
Description=Medical Inventory Resource System
After=network.target NetworkManager.service

[Service]
Type=simple
User=${MY_USER}
WorkingDirectory=/home/${MY_USER}/medical-inventory-system_v1.4.5
ExecStart=/usr/bin/python3 /home/${MY_USER}/medical-inventory-system_v1.4.5/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
ENDOFFILE"

# 確認檔案內容正確
cat /etc/systemd/system/mirs.service

# 啟用並啟動服務
sudo systemctl daemon-reload
sudo systemctl enable mirs.service
sudo systemctl start mirs.service

# 檢查狀態
sudo systemctl status mirs.service

# 查看日誌
sudo journalctl -u mirs.service -f
```

**常見問題**：
- 如果出現 `Failed to determine user credentials`，檢查 `User=` 的使用者名稱是否正確
- 如果出現 `No such file or directory`，檢查 `WorkingDirectory` 和 `ExecStart` 路徑
- 使用 `whoami` 確認你的使用者名稱

## 修復內容說明

此版本已包含以下修復，**無需手動修改**：

### ✅ 資料庫結構修復
- 修復 items 表欄位名稱：`code` → `item_code`，`name` → `item_name`
- 新增 `item_category` 欄位
- 修復所有外鍵參照

### ✅ 編碼相容性修復
- 替換所有全角括號 `（）` 為半-width括號 `()`
- 確保跨平台相容性

### ✅ 測試驗證
- ✓ 資料庫初始化成功
- ✓ Schema 驗證通過
- ✓ SQL 查詢測試成功
- ✓ Python 語法驗證通過

## 常見問題

### Q: 如何查看運行日誌？

```bash
# 即時查看服務日誌
sudo journalctl -u mirs.service -f

# 查看最近的錯誤
sudo journalctl -u mirs.service --no-pager | grep -i error
```

### Q: 如何重新啟動服務？

```bash
sudo systemctl restart mirs.service
```

### Q: 如何停止服務？

```bash
sudo systemctl stop mirs.service
```

### Q: WiFi 熱點無法連接？

1. 檢查 NetworkManager 狀態：
```bash
sudo systemctl status NetworkManager
```

2. 查看熱點連接資訊：
```bash
nmcli connection show
```

3. 重新創建熱點：
```bash
sudo nmcli connection delete Hotspot
sudo nmcli device wifi hotspot ifname wlan0 ssid MedicalStation password Medical2025
```

### Q: 如何更新到最新版本？

**快速更新 (有網路)：**
```bash
# 1. 停止服務
sudo systemctl stop mirs.service

# 2. 備份資料庫
cp ~/medical-inventory-system_v1.4.5/medical_inventory.db \
   ~/medical-inventory-system_v1.4.5/backup_$(date +%Y%m%d_%H%M%S).db

# 3. 拉取最新程式碼
cd ~/medical-inventory-system_v1.4.5
git fetch origin
git pull origin main

# 4. 更新依賴 (如有)
pip3 install --break-system-packages -r requirements_v1.4.5.txt

# 5. 重新啟動
sudo systemctl start mirs.service

# 6. 驗證
sudo systemctl status mirs.service
curl -s http://localhost:8000/api/health
```

**從 USB 更新 (離線環境)：**
```bash
# 1. 停止服務
sudo systemctl stop mirs.service

# 2. 備份資料庫
cp ~/medical-inventory-system_v1.4.5/medical_inventory.db \
   ~/backup_db_$(date +%Y%m%d_%H%M%S).db

# 3. 複製新版程式碼
cp -r /media/pi/USB_DRIVE/MIRS/* ~/medical-inventory-system_v1.4.5/
# 注意：若要保留資料，先把 medical_inventory.db 備份出來再還原

# 4. 還原資料庫
cp ~/backup_db_*.db ~/medical-inventory-system_v1.4.5/medical_inventory.db

# 5. 重新啟動
sudo systemctl start mirs.service
```

**回滾到舊版本：**
```bash
sudo systemctl stop mirs.service
cp ~/backup_db_YYYYMMDD_HHMMSS.db ~/medical-inventory-system_v1.4.5/medical_inventory.db
cd ~/medical-inventory-system_v1.4.5 && git checkout <commit-hash>
sudo systemctl start mirs.service
```

## 部署檢查清單

部署完成後，請確認以下項目：

- [ ] Python 依賴已安裝
- [ ] `python3 main.py` 可以成功啟動
- [ ] 可以訪問 http://localhost:8000
- [ ] 資料庫自動創建（medical_inventory.db）
- [ ] WiFi 熱點已創建（如需要）
- [ ] 手機可以連接熱點並訪問系統
- [ ] systemd 服務已啟用並運行
- [ ] 重開機後服務自動啟動

## 支援

如遇到問題，請檢查：

1. 服務日誌：`sudo journalctl -u mirs.service -n 50`
2. Python 錯誤：`python3 main.py` 直接運行查看錯誤訊息
3. 網路連接：`ip addr show` 查看 IP 位址

---

**此版本已通過完整測試，可直接部署到多台 Raspberry Pi 而無需額外修改。**

🤖 Generated with Claude Code
