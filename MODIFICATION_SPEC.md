# 🎨 系統修改規格文件

## 版本資訊
- **修改日期**: 2025-11-13
- **修改範圍**: UI/UX 優化與功能修復
- **影響文件**: Index.html, setup_station.html, main.py

---

## 1. UI 風格統一調整 🎨

### 1.1 顏色方案重新定義

#### 新的顏色配置

| 功能模組 | 原配色 | 新配色 | Tailwind Class | 用途 |
|---------|--------|--------|----------------|------|
| **物品查詢/管理** | Sky Blue (天藍) | **Teal** | `bg-teal-500/600/700` | 庫存相關功能 |
| **進貨管理** | Teal | **Sky Blue (天藍)** | `bg-sky-500/600/700` | 進貨功能 |
| **血袋管理** | Blood Red (#D96754) | **保持不變** | `bg-blood-500` | 血液相關 |
| **設備管理** | Gray | **保持不變** | `bg-gray-500/600` | 設備功能 |
| **同步管理** | Purple (多種顏色混雜) | **Teal + 灰階** | `bg-teal-500/600` + `bg-gray-100/200/300` | 同步功能 |
| **Setup 頁面** | Blue/Purple 漸層 | **Teal 為主色** | `bg-teal-500/600` | 站點設定 |

#### 按鈕與元件特殊配色

| 元件 | 原配色 | 新配色 | 說明 |
|------|--------|--------|------|
| **列印標籤按鈕** | 藍色 (blue-600) | **紅框白底深紅字** | `border-2 border-red-600 bg-white text-red-700 hover:bg-red-50` |
| **血袋轉移按鈕** | 一般配色 | **Claude 紅色系** | `bg-red-500 hover:bg-red-600` 或 `bg-blood-500 hover:bg-blood-600` |

### 1.2 Icon 系統替換

**替換範圍**: 整個系統的所有頁面

**替換方式**:
- ❌ 移除: Unicode icons (如 🏥, ❤️, 📦 等)
- ✅ 使用: Heroicons SVG

**常用 Icon 對應表**:

| 功能 | Unicode | Heroicon SVG Path |
|------|---------|-------------------|
| 醫院/站點 | 🏥 | `<path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>` |
| 血液/心形 | ❤️ | `<path d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"/>` |
| 物品/盒子 | 📦 | `<path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>` |
| 同步/循環 | 🔄 | `<path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>` |
| 設定/齒輪 | ⚙️ | `<path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>` |
| 列印 | 🖨️ | `<path d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"/>` |

---

## 2. Logo 顯示修復 🖼️

### 問題
- De Novo Orthopedics logo 沒有顯示
- 愛復健 (iRehab) logo 沒有顯示

### 檢查項目
1. 確認 logo 文件是否存在於專案目錄
   - `guling_logo.png` (愛復健)
   - `iRehab_logo.png` (iRehab)
   - 是否還有其他 logo 文件？

2. 確認 Index.html 中的 logo 路徑
   - 使用相對路徑還是絕對路徑？
   - 路徑是否正確？

### 修復方案
**方案 A**: 使用 Base64 編碼嵌入圖片（推薦）
- 將 logo 轉換為 Base64 直接嵌入 HTML
- 優點：不需要額外的文件請求，確保顯示

**方案 B**: 修復文件路徑並通過 FastAPI 提供靜態文件服務
- 在 main.py 中添加 StaticFiles 路由
- 提供 `/static/` 或 `/images/` 路徑

**建議採用**: 方案 A（Base64 嵌入）

---

## 3. 站點 ID 顯示問題修復 🏥

### 問題描述
- 在 setup 頁面選擇了 TC-02
- 但主畫面仍顯示 TC-01

### 問題原因分析
可能的原因：
1. localStorage 設定成功，但前端沒有讀取
2. 前端有硬編碼的預設值 (TC-01)
3. Alpine.js 初始化時沒有正確讀取 localStorage

### 修復方案
**Index.html 修改**:
```javascript
// 初始化時讀取 localStorage
stationId: localStorage.getItem('stationId') || 'TC-01',
stationName: localStorage.getItem('stationName') || '醫療站-01',
```

**確保監聽 storage 事件**（跨分頁同步）:
```javascript
window.addEventListener('storage', (e) => {
    if (e.key === 'stationId') {
        this.stationId = e.newValue || 'TC-01';
    }
    if (e.key === 'stationName') {
        this.stationName = e.newValue || '醫療站-01';
    }
});
```

---

## 4. 同步封包產生功能修復 🔄

### 錯誤訊息
```
CHECK constraint failed: transfer_method IN ('NETWORK', 'USB', 'MANUAL', 'DRONE')
```

### 問題分析
- 資料庫欄位 `transfer_method` 有 CHECK 約束
- 目前程式碼傳入的值不在允許的範圍內
- 可能傳入了空值、null 或其他值

### 修復方案

**main.py 修改**:
1. 找到產生同步封包的函數
2. 確保 `transfer_method` 設定為允許的值之一
3. 建議預設使用 'MANUAL' 或 'USB'

```python
# 示例修復
transfer_method = request.transfer_method if hasattr(request, 'transfer_method') else 'MANUAL'
# 或
transfer_method = 'USB'  # 預設使用 USB
```

### UI 操作指示

**在同步管理頁面的「產生封包」卡片中添加說明**:

```markdown
📦 產生同步封包

1. 選擇傳輸方式：
   - USB: 透過 USB 隨身碟傳輸（推薦）
   - NETWORK: 透過網路傳輸
   - MANUAL: 手動匯出檔案
   - DRONE: 無人機傳輸（特殊場景）

2. 點擊「產生封包」按鈕

3. 封包會儲存至 exports/ 目錄

4. 將 USB 隨身碟插入電腦後複製封包檔案
```

**UI 元件修改**:
- 添加下拉選單讓使用者選擇 `transfer_method`
- 預設選擇 'USB'
- 添加說明文字

---

## 5. 血袋標籤列印格式修復 🏷️

### 問題描述
標籤內容跑到框框外面：
```
站點: TC-01
入庫時間: 2025-11-13 20:21
⚠ 使用前請確認血型 ⚠
```

### 問題原因
可能的原因：
1. CSS 布局問題（flex/grid 配置錯誤）
2. 容器寬度不足
3. 列印樣式 (@media print) 沒有正確設定

### 修復方案

**列印頁面 HTML 結構**:
```html
<div class="label-container" style="width: 100mm; padding: 10mm; border: 2px solid #000;">
    <div class="label-header">
        <!-- QR Code -->
    </div>
    <div class="label-content">
        <!-- 血袋資訊 -->
    </div>
    <div class="label-footer">
        <p>⚠ 使用前請確認血型 ⚠</p>
    </div>
</div>
```

**CSS 修復**:
```css
@media print {
    body * {
        visibility: hidden;
    }
    .label-container, .label-container * {
        visibility: visible;
    }
    .label-container {
        position: absolute;
        top: 0;
        left: 0;
        width: 100mm;
        height: 80mm;
    }
}
```

---

## 6. 設備檢查統計更新 📊

### 問題 1: 統計卡片沒有即時更新

**修復方案**:
- 在設備檢查完成後，重新調用 `loadStats()` 或類似函數
- 確保統計數據重新計算

```javascript
async function checkEquipment(equipmentId) {
    // ... 執行檢查
    await fetch(`/api/equipment/${equipmentId}/check`, ...);

    // 重新載入統計
    await this.loadStats();
    await this.loadEquipment();
}
```

### 問題 2: 每日重置時電力欄位處理

**需求**: 重置時將電力欄位改為 null 或 '--'

**main.py 修復**:
```python
def reset_equipment_daily():
    """每日重置設備狀態"""
    cursor.execute("""
        UPDATE equipment
        SET
            status = 'unchecked',
            last_check_time = NULL,
            battery_level = NULL  -- 或設為 0
        WHERE ...
    """)
```

**前端顯示修復**:
```javascript
// 顯示電力時
<span x-text="equipment.battery_level !== null ? equipment.battery_level + '%' : '--'"></span>
```

---

## 7. API Info 與 Health 頁面顯示修復 🔧

### 問題
- `/api/info` 沒有正常顯示
- `/api/health` 沒有正常顯示

### 預期行為
這兩個是 JSON API 端點，應該返回 JSON 格式數據，不是 HTML 頁面。

### 確認方案

**選項 A**: 保持 JSON 格式（推薦）
- 這些端點用於程式調用，返回 JSON
- 前端可以用 fetch 獲取數據
- 第三方監控工具可以調用

**選項 B**: 創建美化的 HTML 頁面
- 為這些端點創建友好的 HTML 介面
- 方便人工查看系統狀態

### 建議實作方式

**保持原有 JSON API**:
```python
@app.get("/api/info")
async def api_info():
    return JSONResponse({
        "name": "醫療站庫存管理系統 API",
        "version": config.VERSION,
        "station": config.STATION_ID,
        "docs": "/docs"
    })
```

**新增人類友好頁面**:
```python
@app.get("/info")
async def info_page():
    """系統資訊頁面 (HTML)"""
    return HTMLResponse(content="""
        <html>...</html>
    """)
```

---

## 8. 文件修改清單 📝

### 需要修改的文件

| 文件 | 修改項目 | 優先級 |
|------|---------|--------|
| **Index.html** | 1. 顏色調整（Teal化）<br>2. Icon 替換為 Heroicon<br>3. 站點 ID 讀取修復<br>4. 列印標籤按鈕樣式<br>5. 血袋轉移按鈕樣式<br>6. 同步頁面顏色簡化<br>7. Logo 顯示修復<br>8. 設備統計更新<br>9. 血袋標籤格式修復 | ⭐⭐⭐ 高 |
| **setup_station.html** | 1. 改為 Teal 主色調<br>2. Icon 替換為 Heroicon<br>3. 按鈕顏色調整 | ⭐⭐ 中 |
| **main.py** | 1. 同步封包 transfer_method 修復<br>2. 設備每日重置邏輯<br>3. API info/health 確認 | ⭐⭐⭐ 高 |

---

## 9. 詳細修改規格 🔍

### 9.1 Index.html - 顏色對照表

#### 導航標籤按鈕

| 標籤 | 原 Class | 新 Class |
|------|----------|----------|
| 物品查詢 | `bg-sky-600` | `bg-teal-600` |
| 進貨管理 | `bg-teal-600` | `bg-sky-600` |
| 血袋管理 | `bg-blood-500` | `bg-blood-500` (不變) |
| 設備管理 | `bg-gray-500` | `bg-gray-500` (不變) |
| 同步管理 | `bg-purple-600` | `bg-teal-600` |

#### 同步管理頁面內部元件

所有紫色、綠色、藍色元件改為：
- **主色**: `bg-teal-50/100/200/500/600`
- **輔助色**: `bg-gray-50/100/200/300`
- **邊框**: `border-teal-200/300`
- **文字**: `text-teal-600/700/800`

### 9.2 按鈕特殊樣式

#### 列印標籤按鈕
```html
<button class="border-2 border-red-600 bg-white text-red-700 hover:bg-red-50 hover:border-red-700 px-4 py-2 rounded-lg transition-colors">
    <svg>...</svg>
    <span>列印標籤</span>
</button>
```

#### 血袋轉移按鈕
```html
<button class="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg transition-colors">
    <!-- 或使用 -->
    bg-blood-500 hover:bg-blood-600
</button>
```

---

## 10. 測試檢查清單 ✅

### UI 測試
- [ ] 所有頁面使用 Teal 與灰階配色
- [ ] 所有 Unicode icons 已替換為 Heroicons
- [ ] 列印標籤按鈕為紅框白底深紅字
- [ ] 血袋轉移按鈕為紅色系
- [ ] 同步頁面只使用 Teal 與灰階

### 功能測試
- [ ] Logo 正常顯示（De Novo + 愛復健）
- [ ] Setup 選擇 TC-02 後，主畫面顯示 TC-02
- [ ] 產生同步封包功能正常（不再出現 CHECK 錯誤）
- [ ] 產生封包卡片有清楚的操作說明
- [ ] 血袋標籤列印格式正確（內容在框內）
- [ ] 設備檢查後統計卡片即時更新
- [ ] 每日重置後電力顯示為 '--' 或 null
- [ ] /api/info 返回正確 JSON
- [ ] /api/health 返回正確 JSON

---

## 11. 實作順序建議 📋

### Phase 1: 高優先級修復（先做）
1. ✅ 站點 ID 顯示修復（影響基本功能）
2. ✅ 同步封包 transfer_method 修復（阻塞功能）
3. ✅ 血袋標籤列印格式修復（使用體驗）

### Phase 2: UI 統一調整
4. ✅ Index.html 顏色調整為 Teal 系
5. ✅ 所有 Unicode icons 替換為 Heroicons
6. ✅ 列印標籤與轉移按鈕樣式調整
7. ✅ setup_station.html 調整為 Teal 系

### Phase 3: 細節優化
8. ✅ Logo 顯示修復
9. ✅ 設備統計即時更新
10. ✅ 電力欄位重置處理
11. ✅ API 端點確認

---

## 12. 需要確認的問題 ❓

### 請您確認以下問題：

1. **Logo 文件**:
   - De Novo Orthopedics 的 logo 文件名稱是什麼？
   - 是否在專案目錄中？
   - 是否需要我們先檢查文件存在狀態？

2. **顏色風格**:
   - Teal 色調是否指 Tailwind 的標準 Teal（青綠色）？
   - "進貨的 Teal" 是否有特定色碼？
   - "Claude 紅" 是否指 #D96754 或其他？

3. **血袋標籤格式**:
   - 標籤尺寸需求（如 100mm x 80mm）？
   - 是否需要特定的列印方向（橫向/縱向）？

4. **同步封包操作**:
   - 是否需要 UI 讓使用者選擇傳輸方式？
   - 還是直接預設為 'USB' 或 'MANUAL'？

5. **API 端點顯示**:
   - /api/info 和 /api/health 保持 JSON 格式即可？
   - 還是需要創建 HTML 美化頁面？

---

## 13. 預期完成時間 ⏱️

| Phase | 預估時間 | 包含項目 |
|-------|---------|---------|
| Phase 1 | 30 分鐘 | 功能修復 3 項 |
| Phase 2 | 60 分鐘 | UI 調整 4 項 |
| Phase 3 | 30 分鐘 | 細節優化 4 項 |
| **總計** | **約 2 小時** | 11 項修改 |

---

## 請確認 ✋

請您審閱以上規格，並回覆：
1. ✅ 同意所有規格，可以開始實作
2. 🔧 需要調整某些部分（請指出）
3. ❓ 需要我解答上述「需要確認的問題」

**確認後即可開始 coding！** 🚀
