# 🏥 xIRS v1.0 Raspberry Pi 5 安裝說明

**社區韌性系統三合一｜CIRS + MIRS + HIRS 完整部署**

> **xIRS Hub-Satellite 架構**
> - **CIRS** (Port 8090)：社區物資管理 - 權威中心
> - **MIRS** (Port 8000)：醫療站庫存 - 麻醉/手術模組
> - **HIRS** (Port 8001)：家庭物資管理 - 民眾 PWA

> **📅 2026-01-16 更新**：整合三系統安裝流程，支援 Raspberry Pi OS Bookworm/Trixie

---

## 📦 需要準備的東西

### 硬體清單
- ✅ Raspberry Pi 5（4GB 或 8GB）
- ✅ microSD 卡（建議 32GB 以上，Class 10）
- ✅ USB-C 電源供應器（5V 5A，官方推薦）
- ✅ 散熱風扇或散熱片（建議）
- ✅ 乙太網路線（初次設定用，之後可拔除）

### 可選配件
- 📱 NFC 貼紙（NTAG215/216）- 讓手機一碰即連
- 🖨️ 印表機 - 列印 QR code 連線卡

### 系統架構

```
┌─────────────────────────────────────────────────┐
│  Raspberry Pi 5 (xIRS Hub-Satellite)            │
├─────────────────────────────────────────────────┤
│  Port 8090: CIRS Hub (社區管理 - 權威中心)       │
│    /lobby/     - Gateway Lobby (裝置配對)        │
│    /admin/     - 管理控制台                       │
│    /dashboard/ - Dashboard PWA (統計)            │
│    /station/   - 物資站 PWA                      │
│    /pharmacy/  - 藥局站 PWA                      │
│    /doctor/    - 醫師 PWA                        │
│    /nurse/     - 護理站 PWA                      │
│    /mobile/    - 志工手機 PWA                    │
│                                                  │
│  Port 8000: MIRS Satellite (醫療站模組)          │
│    /anesthesia - 麻醉記錄                        │
│    /emt        - 病患轉送                        │
│    /mobile     - 巡房助手                        │
│                                                  │
│  Port 8001: HIRS (家庭物資管理)                  │
│    - 離線優先 PWA，民眾可安裝到手機               │
└─────────────────────────────────────────────────┘
              ↑ WiFi Hotspot (10.0.0.1)
    ┌─────────┴─────────┐
    │  手機/平板 PWA    │
    └───────────────────┘
```

### 存取網址（連上 WiFi 熱點後）

| 系統 | 網址 | 說明 |
|------|------|------|
| **CIRS** | http://10.0.0.1:8090 | 社區管理中心 |
| CIRS Admin | http://10.0.0.1:8090/admin | 管理控制台 |
| CIRS Station | http://10.0.0.1:8090/station | 物資站 |
| CIRS Pharmacy | http://10.0.0.1:8090/pharmacy | 藥局站 |
| CIRS Doctor | http://10.0.0.1:8090/doctor | 醫師 |
| CIRS Nurse | http://10.0.0.1:8090/nurse | 護理站 |
| **MIRS** | http://10.0.0.1:8000 | 醫療站庫存 |
| MIRS Anesthesia | http://10.0.0.1:8000/anesthesia | 麻醉記錄 |
| MIRS EMT | http://10.0.0.1:8000/emt | 病患轉送 |
| **HIRS** | http://10.0.0.1:8001 | 家庭物資管理 |

> **💡 每台 Pi 的熱點 IP 都是 `10.0.0.1`**，因為每台 Pi 建立自己的獨立網路，不會衝突。

---

## 🚀 第一階段：Raspberry Pi 5 基本設定

### 步驟 1：安裝 Raspberry Pi OS

1. **下載 Raspberry Pi Imager**：https://www.raspberrypi.com/software/

2. **燒錄系統到 SD 卡**：
   - 選擇「Raspberry Pi OS (64-bit)」
   - 點擊「⚙️ 齒輪」進行進階設定：
     ```
     ✅ Set hostname: DNO-HC01（或你的站點編號）
     ✅ Enable SSH: 使用密碼驗證
     ✅ Set username and password:
        Username: dno（或你的使用者名稱）
        Password: 你的密碼
     ✅ Configure wireless LAN:
        SSID: (你的 WiFi 名稱，初次設定用)
        Password: (你的 WiFi 密碼)
        Country: TW
     ✅ Set locale settings:
        Time zone: Asia/Taipei
        Keyboard layout: us
     ```
   - 點擊「WRITE」開始燒錄

3. **啟動 Raspberry Pi**：插入 SD 卡、連接電源，等待開機

### 步驟 2：SSH 連線到 Pi

```bash
# 從你的電腦連線
ssh dno@DNO-HC01.local
# 或用 IP 位址
ssh dno@192.168.1.xxx
```

### 步驟 3：更新系統並安裝必要工具

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-pip python3-venv sqlite3
```

---

## 🏥 第二階段：安裝 xIRS 三合一系統

### 2.1 下載三個系統

```bash
cd ~
git clone https://github.com/cutemo0953/CIRS.git
git clone https://github.com/cutemo0953/MIRS-v2.0-single-station.git
git clone https://github.com/cutemo0953/HIRS.git
```

### 2.2 安裝 CIRS Hub

```bash
cd ~/CIRS

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝依賴
pip install --upgrade pip
cd backend
pip install -r requirements.txt

# 如果 Python 3.13 有相容性問題，使用：
# pip install fastapi>=0.115.0 uvicorn[standard] pydantic>=2.8.0 sqlalchemy aiosqlite bcrypt pynacl httpx

# 初始化資料庫
python init_db.py

# 測試啟動
uvicorn main:app --host 0.0.0.0 --port 8090
# 看到 "Application startup complete" 後按 Ctrl+C 停止
```

### 2.3 安裝 MIRS Satellite

```bash
cd ~/MIRS-v2.0-single-station

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝依賴
pip install --upgrade pip
pip install -r api/requirements.txt

# 如果 Python 3.13 有相容性問題，使用：
# pip install fastapi>=0.115.0 uvicorn[standard] pydantic>=2.8.0 reportlab qrcode[pil] pandas Pillow httpx

# 測試啟動
python3 main.py
# 看到 "服務位址: http://0.0.0.0:8000" 後按 Ctrl+C 停止
```

### 2.4 HIRS 無需安裝

HIRS 是純靜態網頁，clone 完成後即可使用，不需要安裝依賴。

---

## ⚡ 第三階段：設定開機自動啟動

### 3.1 建立 CIRS 服務

```bash
sudo nano /etc/systemd/system/cirs.service
```

貼上以下內容（將 `dno` 替換為你的使用者名稱）：

```ini
[Unit]
Description=CIRS Hub v3.5
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/CIRS/backend
Environment=PATH=/home/dno/CIRS/venv/bin:/usr/bin
ExecStart=/home/dno/CIRS/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3.2 建立 MIRS 服務

```bash
sudo nano /etc/systemd/system/mirs.service
```

貼上以下內容：

```ini
[Unit]
Description=MIRS Satellite v2.9.1
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/MIRS-v2.0-single-station
Environment=PATH=/home/dno/MIRS-v2.0-single-station/venv/bin:/usr/bin
ExecStart=/home/dno/MIRS-v2.0-single-station/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3.3 建立 HIRS 服務

```bash
sudo nano /etc/systemd/system/hirs.service
```

貼上以下內容：

```ini
[Unit]
Description=HIRS v2.5
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/HIRS
ExecStart=/usr/bin/python3 -m http.server 8001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 3.4 啟動所有服務

```bash
sudo systemctl daemon-reload
sudo systemctl enable cirs mirs hirs
sudo systemctl start cirs mirs hirs

# 檢查狀態（三個都應該顯示 active (running)）
sudo systemctl status cirs mirs hirs --no-pager
```

### 3.5 驗證服務

```bash
curl http://localhost:8090/api/health  # CIRS
curl http://localhost:8000/api/health  # MIRS
curl http://localhost:8001/ | head -1   # HIRS
```

---

## 📱 第四階段：設定 WiFi 熱點

讓 Raspberry Pi 變成 WiFi 熱點，手機可以直接連線存取 xIRS。

### 4.1 使用 NetworkManager 建立熱點（Bookworm/Trixie）

```bash
# 一鍵建立熱點
sudo nmcli device wifi hotspot ifname wlan0 ssid "DNO-HC01" password "xirs2025"

# 設定固定 IP（重要！）
sudo nmcli con modify Hotspot ipv4.addresses 10.0.0.1/24
sudo nmcli con modify Hotspot 802-11-wireless.channel 6

# 重新啟動熱點
sudo nmcli con down Hotspot && sudo nmcli con up Hotspot
```

### 4.2 設定 NAT（讓熱點可上網）

```bash
# 開啟 IP 轉發
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf

# 設定 NAT
sudo nft add table nat
sudo nft add chain nat postrouting { type nat hook postrouting priority 100 \; }
sudo nft add rule nat postrouting oifname "eth0" masquerade

# 永久保存
sudo nft list ruleset | sudo tee /etc/nftables.conf
sudo systemctl enable nftables
```

### 4.3 WiFi 穩定性優化

```bash
# 關閉省電模式（重要！）
sudo iw dev wlan0 set power_save off

# 永久關閉省電
echo 'ACTION=="add", SUBSYSTEM=="net", KERNEL=="wlan0", RUN+="/usr/sbin/iw dev wlan0 set power_save off"' | sudo tee /etc/udev/rules.d/70-wifi-powersave.rules

# 設定台灣區域
sudo iw reg set TW
```

### 4.4 驗證熱點

```bash
# 檢查 IP
ip addr show wlan0
# 應顯示: inet 10.0.0.1/24

# 檢查熱點狀態
nmcli con show --active
```

---

## 📋 第五階段：建立 QR Code 連線卡

### 5.1 產生 WiFi 和系統 QR Code

```bash
cd ~
source ~/CIRS/venv/bin/activate
pip install qrcode[pil] pillow

python3 << 'EOF'
import qrcode

# WiFi QR Code
wifi = "WIFI:T:WPA;S:DNO-HC01;P:xirs2025;;"
qr = qrcode.make(wifi)
qr.save("wifi_qr.png")
print("WiFi QR Code: ~/wifi_qr.png")

# xIRS URLs
for name, url in [("CIRS", "http://10.0.0.1:8090"),
                  ("MIRS", "http://10.0.0.1:8000"),
                  ("HIRS", "http://10.0.0.1:8001")]:
    qr = qrcode.make(url)
    qr.save(f"{name.lower()}_qr.png")
    print(f"{name} QR Code: ~/{name.lower()}_qr.png")
EOF
```

### 5.2 下載 QR Code 到電腦

```bash
# 在你的電腦執行
scp dno@DNO-HC01.local:~/*.png ~/Desktop/
```

列印並護貝，張貼在設備旁邊。

---

## 👩‍⚕️ 第六階段：使用流程

### 手機連線步驟

1. **開啟 WiFi 設定**，連接 `DNO-HC01`
2. **輸入密碼**：`xirs2025`
3. **開啟瀏覽器**，輸入網址：
   - 社區管理：`http://10.0.0.1:8090`
   - 醫療站：`http://10.0.0.1:8000`
   - 家庭物資：`http://10.0.0.1:8001`
4. **加入主畫面**（Safari 分享 → 加入主畫面）

### HIRS 民眾使用場景

連上 WiFi 後，民眾可以：
1. 開啟 `http://10.0.0.1:8001`
2. 點擊「加入主畫面」安裝 HIRS PWA
3. **即使離開熱點，HIRS 也能離線使用**

### 預設帳號

**CIRS 預設帳號**（PIN 皆為 `1234`）：

| ID | 名稱 | 角色 |
|---|---|---|
| `admin001` | 管理員 | admin |
| `staff001` | 志工小明 | staff |
| `medic001` | 醫護小華 | medic |

---

## 🔧 第七階段：系統管理與維護

### 檢查服務狀態

```bash
sudo systemctl status cirs mirs hirs --no-pager
```

### 重新啟動服務

```bash
sudo systemctl restart cirs mirs hirs
```

### 查看日誌

```bash
sudo journalctl -u cirs -f   # CIRS 日誌
sudo journalctl -u mirs -f   # MIRS 日誌
```

### 更新系統

```bash
# 更新 CIRS
cd ~/CIRS && git pull
cd backend && source ../venv/bin/activate && pip install -r requirements.txt
python init_db.py
sudo systemctl restart cirs

# 更新 MIRS
cd ~/MIRS-v2.0-single-station && git pull
source venv/bin/activate && pip install -r api/requirements.txt
sudo systemctl restart mirs

# 更新 HIRS
cd ~/HIRS && git pull
# HIRS 是靜態網頁，不需重啟
```

### 備份資料庫

```bash
# CIRS 資料庫
cp ~/CIRS/backend/data/xirs_hub.db ~/backup_cirs_$(date +%Y%m%d).db

# MIRS 資料庫
cp ~/MIRS-v2.0-single-station/medical_inventory.db ~/backup_mirs_$(date +%Y%m%d).db
```

---

## 🚨 常見問題排除

### 問題 1：服務啟動失敗 (status=217/USER)

```
mirs.service: Failed at step USER spawning
```

**原因**：服務檔案中的 `User=xxx` 與實際使用者不符

**解決**：
```bash
whoami  # 確認使用者名稱
sudo nano /etc/systemd/system/mirs.service
# 修改 User= 和所有路徑中的使用者名稱
sudo systemctl daemon-reload
sudo systemctl restart mirs
```

### 問題 2：服務啟動失敗 (status=200/CHDIR)

**原因**：`WorkingDirectory` 目錄不存在

**解決**：
```bash
ls -la ~/CIRS  # 確認目錄存在
# 如果不存在，重新 clone
git clone https://github.com/cutemo0953/CIRS.git
```

### 問題 3：WiFi 熱點找不到

```bash
# 檢查熱點狀態
nmcli con show --active

# 重新啟動熱點
sudo nmcli con up Hotspot
```

### 問題 4：連上 WiFi 但無法開網頁

```bash
# 檢查服務是否在監聽
ss -tlnp | grep -E '8000|8001|8090'

# 應該看到三行 LISTEN
```

### 問題 5：WiFi 連線不穩定

```bash
# 確認省電模式已關閉
iw dev wlan0 get power_save
# 應顯示: Power save: off

# 嘗試換頻道
sudo nmcli con modify Hotspot 802-11-wireless.channel 1
sudo nmcli con down Hotspot && sudo nmcli con up Hotspot
```

### 問題 6：pip 安裝失敗 (Python 3.13)

```bash
# 直接安裝相容版本
pip install fastapi>=0.115.0 uvicorn[standard] pydantic>=2.8.0
```

### 問題 7：SSH Host key verification failed

```bash
# 移除舊的 SSH key
ssh-keygen -R DNO-HC01.local
ssh-keygen -R 192.168.1.xxx
```

---

## 📋 安裝檢查清單

完成所有步驟後，請確認：

- [ ] ✅ Raspberry Pi 可以正常開機
- [ ] ✅ SSH 可以連線
- [ ] ✅ CIRS 服務運行中 (port 8090)
- [ ] ✅ MIRS 服務運行中 (port 8000)
- [ ] ✅ HIRS 服務運行中 (port 8001)
- [ ] ✅ WiFi 熱點可以找到
- [ ] ✅ 手機可以連上熱點
- [ ] ✅ 手機可以開啟三個系統
- [ ] ✅ QR Code 連線卡已產生
- [ ] ✅ 重開機後服務自動啟動

**全部打勾 = 安裝成功！🎉**

---

**🏥 xIRS v1.0 - 社區韌性系統三合一**

*De Novo Orthopedics Inc. © 2024-2026*
