# P3-03: RTC Hardware Integration (DS3231)

## Overview

Raspberry Pi 沒有內建 RTC (Real-Time Clock)，斷電後系統時間會重置。
這對 OTA 更新的時間有效性檢查造成問題。

解決方案：安裝 DS3231 RTC 模組 (~$3 USD)

## 硬體需求

| 項目 | 規格 | 參考價格 |
|------|------|----------|
| DS3231 RTC 模組 | I2C 介面, 含電池 | ~$3 USD |

## 硬體連接

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

## 軟體設定

### 1. 啟用 I2C

```bash
sudo raspi-config
# Interface Options -> I2C -> Yes

# 或直接加入 config.txt
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/firmware/config.txt
```

### 2. 加載 RTC overlay

```bash
# 加入 DS3231 驅動
echo "dtoverlay=i2c-rtc,ds3231" | sudo tee -a /boot/firmware/config.txt

# 重啟
sudo reboot
```

### 3. 驗證 RTC 偵測

```bash
# 檢查 I2C 裝置 (應該看到 0x68 或 UU)
sudo i2cdetect -y 1

# 正確輸出:
#      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 60: -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- --
```

### 4. 移除 fake-hwclock

```bash
# RPi 預設用 fake-hwclock 模擬 RTC，需移除
sudo apt remove fake-hwclock -y
sudo update-rc.d -f fake-hwclock remove
sudo systemctl disable fake-hwclock
```

### 5. 設定 hwclock

```bash
# 編輯 hwclock 設定
sudo nano /lib/udev/hwclock-set

# 註解掉以下三行:
# if [ -e /run/systemd/system ] ; then
#     exit 0
# fi
```

### 6. 同步時間

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

## 驗證

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

## 相關檔案

| 檔案 | 說明 |
|------|------|
| `/boot/firmware/config.txt` | RPi 開機設定 |
| `/lib/udev/hwclock-set` | hwclock 啟動腳本 |
| `/etc/rc.local` | 開機自訂腳本 |

## 參考資料

- [RPi RTC Wiki](https://wiki.52pi.com/index.php/DS3231_Precision_RTC_SKU:Z-0089)
- [Adafruit DS3231 Guide](https://learn.adafruit.com/adding-a-real-time-clock-to-raspberry-pi)

---

*P3-03 RTC Setup v1.0 | 2026-01-26*
