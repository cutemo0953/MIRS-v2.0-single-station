# 醫療站庫存系統 v1.3.2 - 快速參考

## 📦 檔案清單

1. **Index-v1.3.2.html** - 前端介面（新版）
2. **import_items.py** - 物資主檔導入工具
3. **start.sh** - 快速啟動腳本（Pi 專用）
4. **README-v1.3.2.md** - 詳細說明文檔

## 🎯 五大改進

### 1️⃣ Unicode → Heroicons
- 所有圖示都使用專業的 Heroicons
- 視覺更一致、更現代

### 2️⃣ 設備檢查功能
- Modal 彈窗式檢查清單
- 檢查狀態追蹤
- 最後檢查時間顯示
- 未檢查設備數即時統計

### 3️⃣ 淡雅 Teal 背景
```
從 teal → 藍 → 紫 → 白 的漸變
不再是單調純白背景
```

### 4️⃣ Logo 展示
- 左下: iRehab 愛復健（主要）
- 右下: 谷盺生物科技（次要）

### 5️⃣ 品項資料完整
- 內建 45+ 常用醫療物資
- 支援自訂導入
- 分類清晰（手術耗材、注射器材、止血劑等）

## 🚀 快速部署（3 步驟）

### 在 Raspberry Pi 5 上：

```bash
# 1. 確保所有檔案在同一目錄
ls
# 應該看到: main.py, Index-v1.3.2.html, import_items.py, start.sh

# 2. 執行啟動腳本
bash start.sh
# 或
./start.sh

# 3. 開啟瀏覽器
# 訪問: http://[Pi的IP]:8000
# 或在 Pi 本地: http://localhost:8000
```

前端檔案放在與 main.py 同目錄，或配置為靜態檔案。

## 🔍 品項空白問題？

### 檢查清單：
- [ ] 後端有啟動嗎？ `ps aux | grep main.py`
- [ ] 資料庫有建立嗎？ `ls -lh medical_inventory.db`
- [ ] 物資有導入嗎？ `python3 import_items.py list`
- [ ] API 有回應嗎？ `curl http://localhost:8000/items`
- [ ] 瀏覽器 Console 有錯誤嗎？ (按 F12 查看)

### 快速修復：
```bash
# 停止舊的後端
pkill -f main.py

# 重新導入物資
python3 import_items.py

# 重啟後端
python3 main.py
```

## 📱 前端功能導覽

### 進貨標籤 (綠色)
1. 選擇品項
2. 輸入數量
3. 加入暫存
4. 提交進貨

### 消耗標籤 (紫色)
同進貨流程，用於記錄消耗

### 血庫標籤 (紅色)
1. 選擇血型 (A+, A-, B+, B-, O+, O-, AB+, AB-)
2. 輸入數量 (單位: U)
3. 選擇入庫或出庫

### 設備標籤 (灰綠)
1. 查看設備狀態
2. 點擊「執行檢查」
3. 完成檢查清單
4. 確認完成

## 🎨 UI 配色方案

```
進貨: #2C7471 (深青綠)
消耗: #4E5488 (深紫藍)
血庫: #D96754 (橘紅)
設備: #CFDCD2 (灰綠)
背景: teal-blue-purple 漸變
統計: 灰階（不搶眼）
```

## 🔧 自訂物資主檔

### 方法 1: 編輯 import_items.py
```python
items_master = [
    ('YOUR-CODE', '物品名稱', '單位', 最小庫存, '類別'),
    # 添加更多...
]
```

### 方法 2: 從 Excel 匯入
```python
import pandas as pd
df = pd.read_excel('物資主檔.xlsx', sheet_name='物資主檔')
# 轉換格式後導入
```

## 📊 物資分類示例

內建分類：
- 手術耗材 (手套、紗布、口罩)
- 注射器材 (針頭、空針)
- 手術器械 (刀片、縫線、電燒)
- 沖洗用品 (生理食鹽水)
- 止血劑 (止血紗布、止血粉、止血帶)
- 敷料 (繃帶、膠布、傷口敷料)
- 消毒用品 (酒精、優碘、雙氧水)
- 急救用品 (夾板、頸圈、冰袋)
- IV用品 (留置針、輸液套組)
- 藥品 (腎上腺素、嗎啡、抗生素、止痛藥)

## 🆘 常見問題

### Q: 品項下拉選單是空的？
A: 執行 `python3 import_items.py` 導入物資

### Q: 無法連接後端？
A: 檢查 main.py 是否在運行，確認 API URL

### Q: 設備檢查後沒更新？
A: 重新載入頁面，或檢查 API 連線

### Q: Logo 沒有顯示？
A: 確認圖片檔案路徑正確，與 HTML 在同目錄

### Q: 如何在 Pi 上自動啟動？
A: 使用 systemd service 或加入 crontab

## 📞 技術規格

- **前端**: HTML5 + TailwindCSS + Alpine.js
- **後端**: FastAPI + SQLite
- **平台**: Raspberry Pi 5 / Linux
- **瀏覽器**: Chrome, Firefox, Safari (現代瀏覽器)

## 🎓 學習資源

- Alpine.js: https://alpinejs.dev/
- TailwindCSS: https://tailwindcss.com/
- Heroicons: https://heroicons.com/
- FastAPI: https://fastapi.tiangolo.com/

---

**需要協助？** 檢查 README-v1.3.2.md 獲取完整文檔
