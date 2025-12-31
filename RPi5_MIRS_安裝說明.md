# 🏥 MIRS v1.5.1 Raspberry Pi 5 安裝說明

**專為壯闊台灣醫療站設計｜讓護理人員 3 分鐘完成安裝**

> **v1.5.1 新功能**：麻醉模組 + CIRS Hub 整合（Hub-Satellite 架構）

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

### 網路架構選擇

| 模式 | 說明 | 適用場景 |
|------|------|----------|
| **獨立模式** | MIRS 單機運作，無需 CIRS | 野外醫療站、無網路環境 |
| **Hub-Satellite** | MIRS 連接 CIRS Hub 同步病患資料 | 有網路的醫療站 |

---

## 🚀 第一階段：Raspberry Pi 5 基本設定

### 步驟 1：安裝 Raspberry Pi OS

**方法 A：使用 Raspberry Pi Imager（推薦）**

1. **下載 Imager** 到你的電腦：
   - 前往：https://www.raspberrypi.com/software/
   - 下載 Windows/Mac 版本

2. **燒錄系統到 SD 卡**：
   - 插入 microSD 卡到電腦
   - 開啟 Raspberry Pi Imager
   - 選擇「Operating System」→「Raspberry Pi OS (64-bit)」
   - 選擇「Storage」→ 你的 SD 卡
   - 點擊「⚙️ 齒輪」進行進階設定：
     ```
     ✅ Set hostname: medical-tc01
     ✅ Enable SSH: 使用密碼驗證
     ✅ Set username and password:
        Username: medical
        Password: Medical2025
     ✅ Configure wireless LAN:
        SSID: (你的 WiFi 名稱)
        Password: (你的 WiFi 密碼)
        Country: TW
     ✅ Set locale settings:
        Time zone: Asia/Taipei
        Keyboard layout: us
     ```
   - 點擊「WRITE」開始燒錄（約 5-10 分鐘）

3. **啟動 Raspberry Pi**：
   - 將 SD 卡插入 Pi
   - 連接電源
   - 等待綠色 LED 閃爍（約 1-2 分鐘開機）

### 步驟 2：SSH 連線到 Pi

**從你的電腦連線（Windows/Mac 都可以）**

```bash
# 開啟終端機 (Terminal) 或命令提示字元 (CMD)
ssh medical@medical-tc01.local

# 如果上面不行，試試用 IP 位址
ssh medical@192.168.1.xxx

# 密碼: Medical2025
```

**找不到 IP？**
```bash
# 在 Pi 上查詢 IP（需接螢幕鍵盤）
hostname -I

# 或在電腦上掃描網路
# Windows: 使用 Advanced IP Scanner
# Mac: 使用 Angry IP Scanner
```

### 步驟 3：更新系統

```bash
# 連線到 Pi 後執行
sudo apt update && sudo apt upgrade -y

# 安裝必要工具
sudo apt install -y git python3-pip python3-venv sqlite3
```

---

## 🏥 第二階段：安裝 MIRS v1.5.1 系統

### 步驟 1：下載系統程式

```bash
# 切換到家目錄
cd ~

# 從 GitHub 下載系統（v1.5.1 含麻醉模組）
git clone https://github.com/cutemo0953/MIRS-v2.0-single-station.git

# 進入系統目錄
cd MIRS-v2.0-single-station
```

### 步驟 2：安裝 Python 套件

```bash
# 建立虛擬環境（推薦）
python3 -m venv venv

# 啟動虛擬環境
source venv/bin/activate

# ⚠️ 重要：檢查 Python 版本
python3 --version

# 如果顯示 Python 3.13，需要先修正相容性問題
# 編輯 requirements 檔案
nano api/requirements.txt
```

**如果是 Python 3.13，請修改以下兩行：**
```
# 找到這兩行：
pydantic==2.5.0
# 改成：
pydantic>=2.8.0

# 找到這行：
fastapi==0.104.1
# 改成：
fastapi>=0.115.0
```

**儲存後繼續安裝：**
```bash
# Ctrl+O 儲存，Ctrl+X 離開

# 安裝套件
pip install -r api/requirements.txt

# 如果還是失敗，使用手動安裝（保證成功）：
pip install fastapi>=0.115.0 uvicorn[standard]==0.24.0 pydantic>=2.8.0 reportlab>=4.0.0 qrcode[pil]>=7.4.2 pandas>=2.0.0 Pillow>=10.0.0 httpx>=0.25.0
```

### 步驟 3：測試系統

```bash
# 啟動系統
python3 main.py

# 看到以下訊息就成功了：
# 🏥 醫療站庫存管理系統 API v1.5.1
# 🌐 服務位址: http://0.0.0.0:8090
# ✓ MIRS Anesthesia Module v1.5.1 已啟用 (/api/anesthesia)
```

**測試連線**：
- 主系統：http://medical-tc01.local:8090
- 麻醉模組：http://medical-tc01.local:8090/anesthesia
- 應該會看到 MIRS 登入畫面

**測試成功！按 Ctrl+C 停止，繼續下一步**

---

## 📱 第三階段：設定 WiFi 熱點（手機直連）

這個步驟讓 Raspberry Pi 變成 WiFi 熱點，手機可以直接連線，不需要路由器。

### 步驟 1：安裝熱點套件

```bash
# 安裝必要套件
sudo apt install -y hostapd dnsmasq

# 停止服務（等等手動設定）
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq
```

### 步驟 2：設定固定 IP

```bash
# 編輯網路設定
sudo nano /etc/dhcpcd.conf

# 在檔案最後加入以下內容：
```

**貼上以下設定**：
```
# WiFi 熱點固定 IP
interface wlan0
    static ip_address=10.0.0.1/24
    nohook wpa_supplicant
```

**儲存**：按 `Ctrl+O` → `Enter` → `Ctrl+X`

### 步驟 3：設定 DHCP 服務

```bash
# 備份原始設定
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.backup

# 建立新設定
sudo nano /etc/dnsmasq.conf
```

**貼上以下內容**：
```
# DHCP 設定
interface=wlan0
dhcp-range=10.0.0.2,10.0.0.20,255.255.255.0,24h

# DNS 設定
address=/#/10.0.0.1
```

**儲存並離開**

### 步驟 4：設定 WiFi 熱點

```bash
# 建立熱點設定檔
sudo nano /etc/hostapd/hostapd.conf
```

**貼上以下內容**（請修改 ssid 站點編號）：
```
# WiFi 熱點設定
interface=wlan0
driver=nl80211

# WiFi 名稱（請改成你的站點編號，例如：TC-02, BORP-01）
ssid=Medical-TC01

# 頻道設定
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0

# WiFi 密碼設定
wpa=2
wpa_passphrase=Medical2025
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
```

**儲存並離開**

```bash
# 告訴系統設定檔位置
sudo nano /etc/default/hostapd
```

找到 `#DAEMON_CONF=""` 這一行，改成：
```
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

**儲存並離開**

### 步驟 5：啟動熱點服務

```bash
# 重新載入網路設定
sudo systemctl restart dhcpcd

# 啟動服務
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl start hostapd
sudo systemctl enable dnsmasq
sudo systemctl start dnsmasq

# 檢查狀態
sudo systemctl status hostapd
sudo systemctl status dnsmasq
```

**應該看到綠色的 `active (running)`**

### 步驟 6：測試熱點

1. **用手機搜尋 WiFi**
2. **找到「Medical-TC01」**
3. **輸入密碼：`Medical2025`**
4. **連線成功！**

---

## 🎯 第四階段：設定系統自動啟動

### 步驟 1：建立啟動腳本

```bash
# 建立啟動腳本
nano ~/MIRS-v2.0-single-station/start_mirs.sh
```

**貼上以下內容**：
```bash
#!/bin/bash

# MIRS 系統啟動腳本
cd /home/medical/MIRS-v2.0-single-station

# 啟動虛擬環境
source venv/bin/activate

# 啟動系統
python3 main.py
```

**儲存並設定執行權限**：
```bash
chmod +x ~/MIRS-v2.0-single-station/start_mirs.sh
```

### 步驟 2：建立 systemd 服務

```bash
sudo nano /etc/systemd/system/mirs.service
```

**貼上以下內容**：
```ini
[Unit]
Description=Medical Inventory Resource System (MIRS)
After=network.target

[Service]
Type=simple
User=medical
WorkingDirectory=/home/medical/MIRS-v2.0-single-station
ExecStart=/home/medical/MIRS-v2.0-single-station/venv/bin/python3 main.py
Restart=always
RestartSec=10

# CIRS Hub 連線設定（Hub-Satellite 架構）
# 如果要連接 CIRS Hub，取消註解並設定 Hub 的 IP
#Environment="CIRS_HUB_URL=http://192.168.1.100:8000"

[Install]
WantedBy=multi-user.target
```

> **Hub-Satellite 模式**：如果要連接 CIRS Hub，設定 `CIRS_HUB_URL` 環境變數。
> 若不設定，MIRS 會以獨立模式運作（離線時自動切換）。

**儲存並啟動服務**：
```bash
# 重新載入服務設定
sudo systemctl daemon-reload

# 啟動服務
sudo systemctl enable mirs
sudo systemctl start mirs

# 檢查狀態
sudo systemctl status mirs
```

### 步驟 3：測試自動啟動

```bash
# 重新開機測試
sudo reboot

# 等待 1-2 分鐘後，用手機連線測試
```

---

## 📲 第五階段：建立 QR Code 連線卡

### 步驟 1：安裝 QR Code 生成工具

```bash
# SSH 回到 Pi
ssh medical@medical-tc01.local

# 安裝套件
pip install qrcode[pil] pillow
```

### 步驟 2：建立自動生成腳本

```bash
# 建立腳本
nano ~/generate_connection_card.py
```

**貼上以下完整腳本**：

```python
#!/usr/bin/env python3
"""
MIRS 連線卡自動生成工具
為護理人員產生 QR Code 連線卡片
"""

import qrcode
from PIL import Image, ImageDraw, ImageFont
import socket

def get_station_info():
    """讀取站點資訊"""
    try:
        with open('/home/medical/MIRS-v2.0-single-station/config/station_config.json', 'r', encoding='utf-8') as f:
            import json
            config = json.load(f)
            return config.get('station_id', 'TC-01'), config.get('station_name', '醫療站')
    except:
        return 'TC-01', '醫療站'

def get_wifi_ssid():
    """讀取 WiFi SSID"""
    try:
        with open('/etc/hostapd/hostapd.conf', 'r') as f:
            for line in f:
                if line.startswith('ssid='):
                    return line.split('=')[1].strip()
    except:
        return 'Medical-TC01'

def generate_connection_card():
    """產生連線卡"""
    
    # 取得站點資訊
    station_id, station_name = get_station_info()
    wifi_ssid = get_wifi_ssid()
    wifi_password = "Medical2025"
    system_url = "http://10.0.0.1:8090"
    
    # 建立畫布 (A5 size, 300 DPI)
    width, height = 1748, 2480  # A5 at 300 DPI
    card = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(card)
    
    # 顏色定義
    teal = '#70a2ac'
    dark_gray = '#2d3748'
    light_gray = '#f7fafc'
    
    # 標題區塊
    draw.rectangle([(0, 0), (width, 400)], fill=teal)
    
    try:
        title_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 80)
        subtitle_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 50)
        body_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 45)
        small_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 35)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        body_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    
    # 標題文字
    draw.text((width//2, 120), "🏥 醫療站庫存系統", fill='white', 
              font=title_font, anchor='mm')
    draw.text((width//2, 220), f"{station_name} ({station_id})", fill='white',
              font=subtitle_font, anchor='mm')
    draw.text((width//2, 310), "MIRS v1.5.1", fill='white',
              font=small_font, anchor='mm')
    
    # WiFi QR Code
    wifi_string = f"WIFI:T:WPA;S:{wifi_ssid};P:{wifi_password};;"
    qr_wifi = qrcode.QRCode(version=1, box_size=15, border=2)
    qr_wifi.add_data(wifi_string)
    qr_wifi.make(fit=True)
    img_wifi = qr_wifi.make_image(fill_color=teal, back_color='white')
    
    # 調整 QR Code 大小
    qr_size = 600
    img_wifi = img_wifi.resize((qr_size, qr_size))
    
    # 貼上 WiFi QR Code
    qr_x = (width - qr_size) // 2
    qr_y = 500
    card.paste(img_wifi, (qr_x, qr_y))
    
    # WiFi 說明
    y_pos = qr_y + qr_size + 50
    draw.text((width//2, y_pos), "📶 步驟 1：掃描連線 WiFi", 
              fill=dark_gray, font=body_font, anchor='mm')
    draw.text((width//2, y_pos + 80), f"WiFi 名稱：{wifi_ssid}", 
              fill=dark_gray, font=small_font, anchor='mm')
    draw.text((width//2, y_pos + 140), f"WiFi 密碼：{wifi_password}", 
              fill=dark_gray, font=small_font, anchor='mm')
    
    # 分隔線
    y_pos += 250
    draw.line([(200, y_pos), (width-200, y_pos)], fill=teal, width=3)
    
    # URL QR Code
    y_pos += 100
    qr_url = qrcode.QRCode(version=1, box_size=15, border=2)
    qr_url.add_data(system_url)
    qr_url.make(fit=True)
    img_url = qr_url.make_image(fill_color=teal, back_color='white')
    img_url = img_url.resize((qr_size, qr_size))
    
    card.paste(img_url, (qr_x, y_pos))
    
    # URL 說明
    y_pos = y_pos + qr_size + 50
    draw.text((width//2, y_pos), "🌐 步驟 2：掃描開啟系統", 
              fill=dark_gray, font=body_font, anchor='mm')
    draw.text((width//2, y_pos + 80), system_url, 
              fill=dark_gray, font=small_font, anchor='mm')
    
    # 底部說明
    y_pos += 200
    draw.rectangle([(0, y_pos), (width, height)], fill=light_gray)
    
    instructions = [
        "✅ 用手機相機掃描上方 QR Code",
        "✅ 先掃 WiFi → 連線成功後 → 再掃網址",
        "✅ 或手動輸入網址到瀏覽器",
        "📞 問題？聯繫 IT 支援"
    ]
    
    y_text = y_pos + 60
    for instruction in instructions:
        draw.text((width//2, y_text), instruction, 
                  fill=dark_gray, font=small_font, anchor='mm')
        y_text += 70
    
    # 儲存檔案
    filename = f'/home/medical/MIRS_Connection_Card_{station_id}.png'
    card.save(filename, 'PNG', dpi=(300, 300))
    
    print(f"✅ 連線卡已產生: {filename}")
    print(f"📱 WiFi SSID: {wifi_ssid}")
    print(f"🔑 WiFi 密碼: {wifi_password}")
    print(f"🌐 系統網址: {system_url}")
    print(f"\n💡 請列印此檔案並護貝，張貼在醫療站明顯處")

if __name__ == '__main__':
    generate_connection_card()
```

**儲存並設定執行權限**：
```bash
chmod +x ~/generate_connection_card.py
```

### 步驟 3：產生連線卡

```bash
# 執行腳本
python3 ~/generate_connection_card.py

# 會產生 PNG 檔案在：
# /home/medical/MIRS_Connection_Card_TC-01.png
```

### 步驟 4：下載並列印

**方法 A：用 SCP 下載到電腦**
```bash
# 在你的電腦執行（不是 Pi）
scp medical@medical-tc01.local:/home/medical/MIRS_Connection_Card_TC-01.png ~/Desktop/
```

**方法 B：用 USB 隨身碟**
```bash
# 在 Pi 上複製到 USB
sudo cp /home/medical/MIRS_Connection_Card_TC-01.png /media/usb/
```

### 步驟 5：列印與護貝

1. **列印**：用彩色印表機列印（建議 A5 或 A4 大小）
2. **護貝**：到影印店護貝（防水防髒）
3. **張貼**：貼在 Raspberry Pi 旁邊或醫療站明顯處

---

## 👩‍⚕️ 護理人員使用流程

### 📱 手機連線（第一次使用）

**方式 A：掃描 QR Code（推薦）**

1. **開啟手機相機**
2. **掃描「WiFi QR Code」**（上面那個）
3. **點擊通知 → 加入網路**
4. **等待連線成功（約 5 秒）**
5. **掃描「網址 QR Code」**（下面那個）
6. **瀏覽器自動開啟系統**
7. **完成！**

**總時間：30 秒**

---

**方式 B：手動連線**

1. **打開手機 WiFi 設定**
2. **找到並連接「Medical-TC01」**
3. **輸入密碼：`Medical2025`**
4. **開啟瀏覽器**
5. **輸入網址：`http://10.0.0.1:8090`**
6. **完成！**

**總時間：60 秒**

---

### 📱 手機連線（第二次之後）

1. **開啟手機 WiFi**（系統會自動連上）
2. **開啟瀏覽器**
3. **點擊書籤或輸入：`http://10.0.0.1:8090`**
4. **完成！**

**總時間：10 秒**

---

### 💡 加入瀏覽器書籤（建議）

**iPhone Safari：**
1. 連線到系統後
2. 點擊下方「分享」按鈕
3. 選擇「加入書籤」或「加到主畫面」
4. 命名：「醫療站庫存」
5. 完成！以後一點就開

**Android Chrome：**
1. 連線到系統後
2. 點擊右上角「⋮」選單
3. 選擇「加入書籤」或「新增至主畫面」
4. 命名：「醫療站庫存」
5. 完成！以後一點就開

---

## 🔧 系統管理與維護

### 檢查系統狀態

```bash
# SSH 連線到 Pi
ssh medical@medical-tc01.local

# 檢查 MIRS 系統
sudo systemctl status mirs

# 檢查 WiFi 熱點
sudo systemctl status hostapd

# 檢查 DHCP 服務
sudo systemctl status dnsmasq

# 查看系統日誌
sudo journalctl -u mirs -f
```

### 重新啟動服務

```bash
# 重啟 MIRS 系統
sudo systemctl restart mirs

# 重啟 WiFi 熱點
sudo systemctl restart hostapd

# 重啟 DHCP
sudo systemctl restart dnsmasq

# 重啟整台 Pi
sudo reboot
```

### 更新系統版本

```bash
# 停止服務
sudo systemctl stop mirs

# 進入系統目錄
cd ~/MIRS-v2.0-single-station

# 備份資料庫
cp medical_inventory.db medical_inventory.db.backup

# 拉取最新版本
git pull origin main

# 更新套件
source venv/bin/activate
pip install -r api/requirements.txt --upgrade

# 重新啟動
sudo systemctl start mirs
```

### 備份資料庫

```bash
# 手動備份
cp ~/MIRS-v2.0-single-station/medical_inventory.db \
   ~/backup_$(date +%Y%m%d).db

# 下載到電腦（在你的電腦執行）
scp medical@medical-tc01.local:~/backup_*.db ~/Desktop/
```

### 自動每日備份（可選）

```bash
# 建立備份腳本
nano ~/backup_mirs.sh
```

**貼上內容**：
```bash
#!/bin/bash
BACKUP_DIR="/home/medical/backups"
mkdir -p $BACKUP_DIR
cp ~/MIRS-v2.0-single-station/medical_inventory.db \
   $BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).db

# 保留最近 7 天的備份
find $BACKUP_DIR -name "backup_*.db" -mtime +7 -delete
```

```bash
# 設定權限
chmod +x ~/backup_mirs.sh

# 加入 crontab（每天凌晨 3 點備份）
crontab -e

# 加入這一行：
0 3 * * * /home/medical/backup_mirs.sh
```

---

## 🚨 常見問題排除

### 問題 0：pip 安裝失敗 (Python 3.13 相容性)

**錯誤訊息**：
```
ERROR: Failed building wheel for pydantic-core
TypeError: ForwardRef._evaluate() missing 1 required keyword-only argument
```

**原因**：
- Raspberry Pi OS 最新版使用 Python 3.13
- 舊版 pydantic (2.5.0) 不支援 Python 3.13

**解決方法（選一）**：

**方法 A：升級套件版本（推薦）**
```bash
# 直接安裝相容的新版本
pip install fastapi>=0.115.0 uvicorn[standard]==0.24.0 pydantic>=2.8.0 reportlab>=4.0.0 qrcode[pil]>=7.4.2 pandas>=2.0.0 Pillow>=10.0.0
```

**方法 B：修改 requirements 檔案**
```bash
nano api/requirements.txt

# 修改這兩行：
pydantic==2.5.0  → pydantic>=2.8.0
fastapi==0.104.1 → fastapi>=0.115.0

# 儲存後再執行
pip install -r api/requirements.txt
```

**方法 C：使用 Python 3.11**
```bash
# 安裝 Python 3.11
sudo apt install python3.11 python3.11-venv

# 使用 Python 3.11 建立虛擬環境
python3.11 -m venv venv
source venv/bin/activate

# 安裝原版 requirements
pip install -r api/requirements.txt
```

### 問題 1：手機找不到 WiFi

**可能原因**：
- Pi 沒有開機
- WiFi 熱點服務沒啟動

**解決方法**：
```bash
# 檢查 Pi 電源指示燈（紅燈恆亮）
# 檢查熱點服務
sudo systemctl status hostapd

# 如果沒啟動，重啟服務
sudo systemctl restart hostapd
```

### 問題 2：連上 WiFi 但打不開網頁

**可能原因**：
- MIRS 系統沒啟動
- IP 位址錯誤

**解決方法**：
```bash
# 檢查 MIRS 服務
sudo systemctl status mirs

# 重啟服務
sudo systemctl restart mirs

# 檢查 IP 設定
ip addr show wlan0 | grep inet
# 應該顯示：inet 10.0.0.1/24
```

### 問題 3：QR Code 掃不到

**可能原因**：
- 列印品質不佳
- 光線不足
- 相機對焦問題

**解決方法**：
- 確保 QR Code 清晰可見
- 在光線充足處掃描
- 手機離 QR Code 約 15-20 公分
- 或直接手動輸入網址

### 問題 4：系統運作緩慢

**可能原因**：
- Pi 過熱
- 記憶體不足
- 資料庫過大

**解決方法**：
```bash
# 檢查溫度
vcgencmd measure_temp

# 檢查記憶體使用
free -h

# 清理舊的備份
rm ~/backups/backup_*.db.old

# 重啟 Pi
sudo reboot
```

### 問題 5：忘記 WiFi 密碼

**解決方法**：
```bash
# SSH 連線到 Pi（用乙太網路）
ssh medical@medical-tc01.local

# 查看密碼
sudo grep "wpa_passphrase" /etc/hostapd/hostapd.conf

# 修改密碼
sudo nano /etc/hostapd/hostapd.conf
# 找到 wpa_passphrase= 這一行修改
# 儲存後重啟
sudo systemctl restart hostapd
```

---

## 📋 檢查清單

完成所有安裝步驟後，請確認：

- [ ] ✅ Raspberry Pi 5 可以正常開機
- [ ] ✅ 可以透過 SSH 連線
- [ ] ✅ Python 套件都安裝完成
- [ ] ✅ MIRS 系統可以手動啟動
- [ ] ✅ WiFi 熱點 可以找到
- [ ] ✅ 手機可以連上 WiFi
- [ ] ✅ 手機可以開啟系統網頁
- [ ] ✅ MIRS 服務自動啟動
- [ ] ✅ QR Code 連線卡已產生
- [ ] ✅ 連線卡已列印並護貝
- [ ] ✅ 已設定每日自動備份
- [ ] ✅ 已測試所有功能正常

**全部打勾 = 安裝成功！🎉**

---

## 📞 技術支援

**問題回報**：
- GitHub Issues: https://github.com/cutemo0953/MIRS-v2.0-single-station/issues
- Email: tom@denovortho.com

**文件回饋**：
- 如果這份安裝說明有任何不清楚的地方，請回報讓我們改進

---

## 🎯 下一步

完成安裝後，建議：

1. **📚 閱讀使用手冊**：查看 GitHub README.md 了解所有功能
2. **👥 訓練護理人員**：示範如何用手機連線與操作
3. **🔄 定期備份**：每週手動檢查備份檔案
4. **📊 監控運作**：每日檢查系統日誌
5. **🆙 保持更新**：定期檢查是否有新版本

---

---

## 🔗 第六階段：CIRS Hub 連線設定（選用）

如果要啟用 Hub-Satellite 架構，讓 MIRS 從 CIRS Hub 取得病患資料：

### 步驟 1：確認網路連線

```bash
# 確認可以連到 CIRS Hub（替換成實際 IP）
ping 192.168.1.100

# 測試 CIRS API
curl http://192.168.1.100:8000/api/health
```

### 步驟 2：設定 CIRS Hub URL

```bash
# 編輯 systemd 服務
sudo nano /etc/systemd/system/mirs.service

# 取消 Environment 那行的註解，並設定 CIRS Hub IP
# Environment="CIRS_HUB_URL=http://192.168.1.100:8000"

# 重新載入並重啟
sudo systemctl daemon-reload
sudo systemctl restart mirs
```

### 步驟 3：驗證連線

開啟麻醉模組（http://10.0.0.1:8090/anesthesia），點擊「開始新案例」，
應該會看到 CIRS 候診名單顯示「🟢 連線」狀態。

> **離線模式**：若 CIRS Hub 無法連線，系統會自動切換為離線模式，
> 仍可手動輸入病患資料繼續操作。

---

**🏥 MIRS v1.5.1 - 專為壯闊台灣醫療站設計**

*De Novo Orthopedics Inc. © 2024-2025*
