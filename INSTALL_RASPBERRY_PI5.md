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

## 第四階段：設定 WiFi 熱點 (AP Mode)

> 讓手機/平板可以直接連到 Pi，不需要外部 WiFi 路由器

### 步驟 1：安裝 NetworkManager (通常已預裝)

```bash
sudo apt install -y network-manager
```

### 步驟 2：建立 WiFi 熱點

```bash
# 建立熱點設定
sudo nmcli device wifi hotspot ssid "DNO-HC01" password "mirs2025"
```

> 📱 **連線資訊**：
> - WiFi 名稱: `MIRS-BORP01`
> - 密碼: `mirs2024`
> - 系統網址: `http://10.42.0.1:8000`

### 步驟 3：設定開機自動啟動熱點

```bash
# 查看連線名稱 (通常是 Hotspot)
nmcli connection show

# 設定自動連線
sudo nmcli connection modify Hotspot connection.autoconnect yes
sudo nmcli connection modify Hotspot connection.autoconnect-priority 100
```

### 步驟 4：測試熱點

```bash
# 啟動熱點
sudo nmcli connection up Hotspot

# 確認熱點狀態
nmcli device status
```

用手機連接 `MIRS-BORP01` WiFi，然後開啟瀏覽器輸入 `http://10.42.0.1:8000`

### (選用) 自訂熱點名稱和密碼

```bash
# 修改 WiFi 名稱
sudo nmcli connection modify Hotspot 802-11-wireless.ssid "你的WiFi名稱"

# 修改密碼
sudo nmcli connection modify Hotspot wifi-sec.psk "你的新密碼"

# 重新啟動熱點
sudo nmcli connection down Hotspot
sudo nmcli connection up Hotspot
```

### (選用) 同時連接外部 WiFi 和開啟熱點

如果 Pi 有乙太網路或第二張 WiFi 網卡，可以同時：
- 用乙太網路連接外部網路
- 用內建 WiFi 開啟熱點給手機連

```bash
# 確認乙太網路已連接
nmcli device status

# 啟動熱點 (會使用 WiFi，乙太網路保持外部連線)
sudo nmcli connection up Hotspot
```

---

## 第五階段：設定開機自動啟動

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

### 重置資料庫 (載入最新預設資料)

> ⚠️ **警告**：此操作會清除所有現有資料！請先備份！

```bash
# 停止服務
sudo systemctl stop mirs

# 進入目錄
cd ~/mirs-v1.4.2-plus

# 備份現有資料庫
cp medical_inventory.db backup_before_reset_$(date +%Y%m%d_%H%M%S).db

# 刪除資料庫 (重啟時會自動重建)
rm medical_inventory.db

# 重新啟動服務 (會自動載入 preload_data.py 的資料)
sudo systemctl start mirs

# 確認服務正常運作
sudo systemctl status mirs
```

### 手動更新設備資料 (不刪除資料庫)

如果只想更新設備清單，不想刪除其他資料：

```bash
# 進入目錄並啟動虛擬環境
cd ~/mirs-v1.4.2-plus
source venv/bin/activate

# 執行 Python 重載設備
python3 -c "
from preload_data import EQUIPMENT_DATA
import sqlite3

conn = sqlite3.connect('medical_inventory.db')
cursor = conn.cursor()

# 取得站點 ID
cursor.execute('SELECT value FROM system_config WHERE key = \"station_id\"')
row = cursor.fetchone()
station_id = row[0] if row else 'BORP-01'

# 清除舊設備並重新載入
cursor.execute('DELETE FROM equipment WHERE station_id = ?', (station_id,))
for eq in EQUIPMENT_DATA:
    cursor.execute('''
        INSERT OR REPLACE INTO equipment (equipment_id, name, category, status, station_id, quantity)
        VALUES (?, ?, ?, 'PENDING', ?, ?)
    ''', (eq['id'], eq['name'], eq['category'], station_id, eq['quantity']))

conn.commit()
conn.close()
print(f'✅ 已載入 {len(EQUIPMENT_DATA)} 項設備到站點 {station_id}')
"

# 重新啟動服務
sudo systemctl restart mirs
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

### 問題 5：設備檢查顯示「請選擇單位」/ 韌性估算電力氧氣為 0

**根因**：`equipment` 表為空（只有類型定義沒有實際設備）

**診斷**：
```bash
cd ~/MIRS-v2.0-single-station
sqlite3 medical_inventory.db "SELECT COUNT(*) FROM equipment WHERE type_code LIKE '%O2%' OR type_code LIKE '%POWER%';"
# 如果回傳 0，就是這個問題
```

**解決方法**：
```bash
sqlite3 medical_inventory.db "
-- 新增設備 (equipment)
INSERT OR IGNORE INTO equipment (id, name, category, type_code, quantity) VALUES
('EQ-O2-E', 'E型氧氣瓶', '呼吸設備', 'O2_CYLINDER_E', 5),
('EQ-O2-H', 'H型氧氣瓶', '呼吸設備', 'O2_CYLINDER_H', 3),
('EQ-O2-CONC', '氧氣濃縮機', '呼吸設備', 'O2_CONCENTRATOR', 2),
('EQ-PWR-STA', '行動電源站', '電力設備', 'POWER_STATION', 3),
('EQ-GEN', '發電機', '電力設備', 'GENERATOR', 1);

-- 清除錯誤的 equipment_units（如果有）
DELETE FROM equipment_units WHERE equipment_id NOT IN (SELECT id FROM equipment);

-- 新增設備單位 (equipment_units)
INSERT INTO equipment_units (equipment_id, unit_serial, unit_label, level_percent, status, is_active) VALUES
('EQ-O2-E', 1, 'E型1號', 100, 'UNCHECKED', 1),
('EQ-O2-E', 2, 'E型2號', 100, 'UNCHECKED', 1),
('EQ-O2-E', 3, 'E型3號', 100, 'UNCHECKED', 1),
('EQ-O2-E', 4, 'E型4號', 100, 'UNCHECKED', 1),
('EQ-O2-E', 5, 'E型5號', 100, 'UNCHECKED', 1),
('EQ-O2-H', 1, 'H型1號', 100, 'UNCHECKED', 1),
('EQ-O2-H', 2, 'H型2號', 100, 'UNCHECKED', 1),
('EQ-O2-H', 3, 'H型3號', 100, 'UNCHECKED', 1),
('EQ-O2-CONC', 1, '濃縮機1號', 100, 'UNCHECKED', 1),
('EQ-O2-CONC', 2, '濃縮機2號', 100, 'UNCHECKED', 1),
('EQ-PWR-STA', 1, '電源站1號', 100, 'UNCHECKED', 1),
('EQ-PWR-STA', 2, '電源站2號', 100, 'UNCHECKED', 1),
('EQ-PWR-STA', 3, '電源站3號', 100, 'UNCHECKED', 1),
('EQ-GEN', 1, '發電機1號', 100, 'UNCHECKED', 1);
"
```

重新整理網頁即可看到設備。

### 問題 6：血庫入庫失敗 (pytz module 缺失)

**解決方法**：
```bash
# 確認 mirs.service 使用的 Python 路徑
sudo systemctl cat mirs | grep ExecStart

# 在該 venv 安裝 pytz
/path/to/venv/bin/pip install pytz

# 重啟服務
sudo systemctl restart mirs
```

### 問題 7：配對模態窗滑動開關不顯示

**原因**：RPi 的 tailwind.min.css 不包含 `peer-checked` 類別

**解決方法**：
```bash
cd ~/MIRS-v2.0-single-station
git pull origin main
```

然後重新整理網頁（v2.9.2+ 已使用純 CSS 實作）

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

- **GitHub Issues**: https://github.com/cutemo0953//issues
- **Email**: tom@denovortho.com

---

*De Novo Orthopedics Inc. © 2024*
