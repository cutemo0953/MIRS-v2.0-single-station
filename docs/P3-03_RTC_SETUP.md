# P3-03: RTC Hardware Integration

**版本**: v2.0
**更新日期**: 2026-02-02
**適用**: Raspberry Pi 4 / Pi 5

---

## Overview

RTC (Real-Time Clock) 確保系統斷電後仍能保持正確時間。
這對 OTA 更新的時間有效性檢查、License 驗證、Event 時間戳至關重要。

---

## RPi4 vs RPi5 RTC 比較

| 項目 | RPi4 (及更早) | RPi5 |
|------|---------------|------|
| **內建 RTC** | ❌ 無 | ✅ 有 (DA9091 PMIC) |
| **內建精度** | N/A | ~50 ppm (±5 秒/天) |
| **斷電保持** | 需外接模組 | 需 ML2020 電池 |
| **外接 DS3231** | ✅ 建議 | ⚠️ 可選 (需停用內建) |

### 選擇指南

| 使用情境 | RPi4 建議 | RPi5 建議 |
|----------|-----------|-----------|
| 一般 IoT / 家用 | DS3231 外接 | 內建 RTC + ML2020 電池 |
| 需要高精度 (資料記錄) | DS3231 | DS3231 (停用內建) |
| 離線長期運作 (>1週) | DS3231 | DS3231 (年誤差 <1 分鐘) |
| 醫療/工業應用 | DS3231 + NTP 雙校正 | DS3231 + NTP 雙校正 |

---

## 方案 A: RPi5 內建 RTC (推薦 - 一般用途)

### 硬體需求

| 項目 | 規格 | 參考價格 |
|------|------|----------|
| ML2020 充電電池 | 3V 鋰錳電池 | ~$5 USD |
| 或 ML2032 | 3V 鋰錳電池 (較大容量) | ~$6 USD |

> ⚠️ **重要**: 必須使用 **ML** 系列充電電池，不可使用 CR2032 (不可充電，會損壞)

### 安裝電池

1. 找到 RPi5 板上的 J5 電池座 (位於 USB-C 電源接口旁)
2. 插入 ML2020 電池 (正極朝上)

### 啟用電池充電

```bash
# 檢查目前 RTC 狀態
sudo hwclock -r

# 啟用電池充電 (預設關閉)
# 編輯 /boot/firmware/config.txt
sudo nano /boot/firmware/config.txt

# 加入以下設定
dtparam=rtc_bbat_vchg=3000000
# 3000000 = 3.0V 充電電壓，適用於 ML2020

# 重啟
sudo reboot
```

### 驗證

```bash
# 讀取 RTC 時間
sudo hwclock -r

# 檢查 RTC 裝置
ls /dev/rtc*
# 應顯示 /dev/rtc0

# 同步系統時間到 RTC
sudo hwclock -w

# 斷電測試 (拔電源 1 分鐘後重新開機)
date  # 應該正確
```

### RPi5 內建 RTC 規格

| 項目 | 規格 |
|------|------|
| 晶片 | DA9091 PMIC (Raspberry Pi 客製) |
| 晶振 | 外部 32.768 kHz |
| 精度 | ~50 ppm (±5 秒/天, ±30 分鐘/年) |
| 調校 | 無微調電容 |

---

## 方案 B: DS3231 外接模組 (高精度需求)

### 適用情境

- RPi4 或更早版本 (無內建 RTC)
- RPi5 但需要更高精度 (<5 ppm)
- 長期離線運作 (需年誤差 <1 分鐘)

### 硬體需求

| 項目 | 規格 | 參考價格 |
|------|------|----------|
| DS3231 RTC 模組 | I2C 介面, 含 CR2032 電池 | ~$3 USD |

### DS3231 規格

| 項目 | 規格 |
|------|------|
| 晶振 | 內建溫度補償 (TCXO) |
| 精度 | 2-5 ppm (~1 分鐘/年) |
| I2C 位址 | 0x68 |
| 工作電壓 | 2.3V - 5.5V |

### 硬體連接

```
DS3231 Pin   ->   RPi GPIO Pin
---------------------------------
VCC          ->   Pin 1 (3.3V)
GND          ->   Pin 6 (GND)
SDA          ->   Pin 3 (GPIO2/SDA)
SCL          ->   Pin 5 (GPIO3/SCL)
```

```
RPi GPIO Header (左上角 Pin 1):

   3.3V [1] [2]  5V
  SDA2 [3] [4]  5V
  SCL2 [5] [6]  GND
       ...
```

### 軟體設定

#### Step 1: 啟用 I2C

```bash
sudo raspi-config
# Interface Options -> I2C -> Yes

# 或直接加入 config.txt
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/firmware/config.txt
```

#### Step 2: 設定 RTC overlay

**RPi4 (及更早):**
```bash
echo "dtoverlay=i2c-rtc,ds3231" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

**RPi5 (需停用內建 RTC):**
```bash
# 編輯 config.txt
sudo nano /boot/firmware/config.txt

# 加入以下兩行 (順序重要)
dtparam=rtc=off
dtoverlay=i2c-rtc,ds3231

# 重啟
sudo reboot
```

> ⚠️ **RPi5 重要**: 必須加入 `dtparam=rtc=off` 停用內建 RTC，否則會產生 rtc0/rtc1 衝突，導致 hwclock 無法正常運作。

#### Step 3: 驗證 RTC 偵測

```bash
# 檢查 I2C 裝置 (應該看到 0x68 或 UU)
sudo i2cdetect -y 1

# 正確輸出:
#      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 60: -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- --
```

#### Step 4: 移除 fake-hwclock

```bash
# RPi 預設用 fake-hwclock 模擬 RTC，需移除
sudo apt remove fake-hwclock -y
sudo update-rc.d -f fake-hwclock remove
sudo systemctl disable fake-hwclock
```

#### Step 5: 設定 hwclock

```bash
# 編輯 hwclock 設定
sudo nano /lib/udev/hwclock-set

# 註解掉以下三行:
# if [ -e /run/systemd/system ] ; then
#     exit 0
# fi
```

#### Step 6: 同步時間

```bash
# 從網路同步系統時間
sudo timedatectl set-ntp true

# 等待 NTP 同步 (確認 System clock synchronized: yes)
timedatectl status

# 將系統時間寫入 RTC
sudo hwclock -w

# 驗證 RTC 時間
sudo hwclock -r
```

---

## 開機自動設定

建立開機腳本確保時間正確：

```bash
sudo nano /etc/rc.local
```

在 `exit 0` 前加入：

```bash
# Sync time from RTC at boot
/sbin/hwclock -s
logger "System time set from RTC: $(date)"
```

---

## 驗證測試

### 測試 1: 讀取 RTC 時間

```bash
sudo hwclock -r
# 應顯示正確時間
```

### 測試 2: 斷電測試

1. 關機：`sudo poweroff`
2. 拔掉電源，等待 1 分鐘
3. 重新接電開機
4. 檢查時間：`date`
5. 時間應該正確（誤差 < 1 分鐘）

### 測試 3: MIRS OTA 時間檢查

```bash
curl -s http://localhost:8000/api/ota/safety/check | python3 -m json.tool
# 應顯示 time_validity: checked
```

---

## 故障排除

### 問題: i2cdetect 看不到裝置

```bash
# 檢查 I2C 是否啟用
ls /dev/i2c*

# 檢查連接
# - 確認 VCC 接 3.3V (不是 5V)
# - 確認 SDA/SCL 沒有接反
```

### 問題: hwclock 讀取失敗

```bash
# 手動載入模組
sudo modprobe rtc-ds1307
echo ds3231 0x68 | sudo tee /sys/class/i2c-adapter/i2c-1/new_device

# 重試
sudo hwclock -r
```

### 問題: 時間每次開機都不對

```bash
# 確認 fake-hwclock 已移除
dpkg -l | grep fake-hwclock

# 確認 hwclock-set 有修改
cat /lib/udev/hwclock-set
```

### 問題: RPi5 使用 DS3231 但時間錯亂

```bash
# 檢查是否有多個 RTC
ls /dev/rtc*
# 如果顯示 rtc0 和 rtc1，表示內建 RTC 未停用

# 確認 config.txt 設定
grep -E "rtc|ds3231" /boot/firmware/config.txt
# 應顯示:
# dtparam=rtc=off
# dtoverlay=i2c-rtc,ds3231

# 重啟後確認只有一個 RTC
sudo reboot
ls /dev/rtc*
# 應只顯示 /dev/rtc0
```

### 問題: RPi5 內建 RTC 電池耗盡

```bash
# 檢查電池充電狀態
cat /sys/class/power_supply/rpi_bat/status
# 應顯示 Charging 或 Full

# 確認充電已啟用
grep rtc_bbat /boot/firmware/config.txt
# 應有 dtparam=rtc_bbat_vchg=3000000
```

---

## 相關檔案

| 檔案 | 說明 |
|------|------|
| `/boot/firmware/config.txt` | RPi 開機設定 |
| `/lib/udev/hwclock-set` | hwclock 啟動腳本 |
| `/etc/rc.local` | 開機自訂腳本 |
| `/dev/rtc0` | RTC 裝置節點 |

---

## 參考資料

- [Raspberry Pi 5 RTC Documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#real-time-clock-rtc)
- [RPi Forums: RPi5 RTC Specs](https://forums.raspberrypi.com/viewtopic.php?t=356991)
- [RPi Forums: DS3231 on RPi5](https://forums.raspberrypi.com/viewtopic.php?t=361813)
- [Adafruit DS3231 Guide](https://learn.adafruit.com/adding-a-real-time-clock-to-raspberry-pi)

---

## 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-01-26 | 初版 - DS3231 for RPi4 |
| 2.0 | 2026-02-02 | 新增 RPi5 內建 RTC 支援、DS3231 on RPi5 設定 |

---

*P3-03 RTC Setup v2.0 | De Novo Orthopedics Inc.*
