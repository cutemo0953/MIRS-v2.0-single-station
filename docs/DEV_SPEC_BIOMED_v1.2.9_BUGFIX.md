# BioMed PWA v1.2.6 ~ v1.2.14 Bug 修復記錄

**日期**: 2026-01-11
**版本**: v1.2.6 → v1.2.14
**問題來源**: RPi 實機測試 + Gemini 程式碼審查 + ChatGPT 架構分析

---

## 問題一覽

| 版本 | 問題 | 根因 | 修復 |
|------|------|------|------|
| v1.2.6 | 氧氣區域錯誤顯示呼吸器 | 過濾器用 category 包含「呼吸」| 改用名稱過濾，排除「呼吸器」|
| v1.2.6 | 韌性估算狀態只有 3 種 | 單位編輯 Modal 缺少 EMPTY | 新增 EMPTY 選項 |
| v1.2.7 | 設備確認後仍灰階顯示 | 灰階條件用 check_status，但舊 API 只更新 status | 條件改為 `check_status=UNCHECKED && status!=NORMAL` |
| v1.2.8 | Alpine undefined 錯誤 | resilienceStatus 初始為空物件 | 初始化包含空陣列 |
| v1.2.9 | v1.2.8 修復無效 | $nextTick 前的 reset 清空陣列 | reset 時也保留空陣列 |
| v1.2.10 | 確認後 UI 仍不更新 | API 成功但本地狀態未同步 | 樂觀更新 (Optimistic UI) |
| v1.2.11 | v1.2.10 樂觀更新無效 | loadResilienceStatus() 創建新陣列覆蓋更新 | 移除 loadResilienceStatus() 呼叫 |
| v1.2.12 | v1.2.11 仍無效 | Alpine.js 不偵測巢狀物件屬性變更 | 用 .map() 創建新陣列 |
| v1.2.13 | v1.2.12 仍無效 | 只替換子陣列不夠，需替換父物件 | 替換整個 resilienceStatus 物件 |
| **v1.2.14** | **v1.2.13 仍無效** | **checkEquipment() 用舊 API，不更新 equipment_units.last_check** | **改用 v2 unit-level API** |

---

## 問題一：設備確認後 UI 不更新 (v1.2.6 → v1.2.7)

### 症狀
- RPi 上點擊設備「確認」按鈕
- 系統顯示成功訊息
- 但設備列表仍顯示灰階 (未確認狀態)
- Vercel Demo 沒有此問題

### 根因分析

**兩種「狀態」欄位的混淆：**

| 欄位 | 來源 | 意義 | 值 |
|------|------|------|-----|
| `status` | equipment 表 | 設備操作狀態 | NORMAL, WARNING, ERROR, UNCHECKED |
| `check_status` | v_equipment_status 視圖 | 單位檢查狀態 | CHECKED, PARTIAL, UNCHECKED, NO_UNITS |

**API 行為差異：**

```python
# 舊版 checkEquipment() - /api/equipment/check/{id}
# 只更新 equipment 表
UPDATE equipment SET status = 'NORMAL', last_check = NOW()

# 新版 checkEquipmentUnit() - /api/v2/equipment/units/{id}/check
# 更新 equipment_units 表
UPDATE equipment_units SET last_check = NOW()
```

**視圖計算 check_status 的邏輯：**

```sql
CREATE VIEW v_equipment_status AS
SELECT
    CASE
        WHEN COUNT(u.id) = 0 THEN 'NO_UNITS'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0 THEN 'UNCHECKED'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id) THEN 'CHECKED'
        ELSE 'PARTIAL'
    END as check_status
FROM equipment e
LEFT JOIN equipment_units u ON e.id = u.equipment_id
```

**問題：**
- 舊 API 只更新 `equipment.status`
- 視圖的 `check_status` 基於 `equipment_units.last_check`
- 所以確認後 `status=NORMAL` 但 `check_status=UNCHECKED`

### 修復 (v1.2.7)

```javascript
// 修復前 (只看 check_status)
'opacity-50 grayscale': eq.check_status === 'UNCHECKED' || eq.check_status === 'NO_UNITS'

// 修復後 (同時看 check_status 和 status)
'opacity-50 grayscale': (eq.check_status === 'UNCHECKED' || eq.check_status === 'NO_UNITS') && eq.status !== 'NORMAL'
```

---

## 問題二：Alpine undefined 錯誤 (v1.2.8 → v1.2.9)

### 症狀

```
Alpine Expression Error: Cannot read properties of undefined (reading 'filter')
Expression: "resilienceStatus.oxygenUnits.filter(u => u.last_check).length + '/' + ..."
```

### 根因分析

**時序問題：**

```
1. 頁面載入，Alpine 初始化
2. resilienceStatus = {} (空物件)
3. 模板嘗試渲染 resilienceStatus.oxygenUnits.filter(...)
4. oxygenUnits 是 undefined → 錯誤！
5. loadResilienceStatus() 完成，設定 oxygenUnits
6. 但錯誤已經發生
```

### v1.2.8 修復 (不完整)

```javascript
// 初始化時設定空陣列
resilienceStatus: { oxygenUnits: [], powerUnits: [], ... }
```

**為何無效？**

```javascript
// loadResilienceStatus() 中的程式碼
this.resilienceStatus = {};  // ← 這行會清掉初始化的空陣列！
await this.$nextTick();
this.resilienceStatus = { oxygenUnits: oxygenUnits, ... };
```

### v1.2.9 修復 (完整)

```javascript
// v1.2.9: $nextTick 前的 reset 也保留空陣列
this.resilienceStatus = { oxygenUnits: [], powerUnits: [], oxygenResources: [], powerResources: [] };
await this.$nextTick();
this.resilienceStatus = { oxygenUnits: oxygenUnits, ... };
```

加上模板安全檢查：

```html
<!-- 使用 (xxx || []) 避免 undefined -->
x-text="(resilienceStatus.oxygenUnits || []).filter(u => u.last_check).length"
```

---

## 問題三：氧氣區域顯示呼吸器 (v1.2.6)

### 症狀
- RPi 韌性估算的「氧氣鋼瓶」區域出現「呼吸器」設備
- Vercel Demo 沒有此問題

### 根因

```javascript
// 修復前：用 category 過濾
const isOxygen = category?.includes('呼吸');  // ← 會匹配「呼吸設備」類別

// 呼吸設備類別包含：
// - 氧氣鋼瓶 ✓
// - 氧氣濃縮機 ✓
// - 呼吸器 ✗ (不是氧氣來源)
```

### 修復

```javascript
// v1.2.6: 改用名稱過濾
const isOxygen = name.includes('氧氣') || name.includes('O2') ||
                name.includes('鋼瓶') || name.includes('氧瓶');
const isConcentrator = name.includes('濃縮機');
const isVentilator = name.includes('呼吸器') || name.includes('ventilator');
return isOxygen && !isConcentrator && !isVentilator;
```

---

## 版本變更摘要

| 版本 | 變更類型 | 檔案 |
|------|----------|------|
| v1.2.6 | 過濾修復 + EMPTY 狀態 | index.html |
| v1.2.7 | 灰階邏輯修復 | index.html |
| v1.2.8 | Alpine 初始化修復 | index.html |
| v1.2.9 | $nextTick 修復 | index.html |
| v1.2.10 | 樂觀更新 (Gemini 建議) | index.html |
| v1.2.11 | 移除 loadResilienceStatus() 呼叫 | index.html |
| v1.2.12 | 用 .map() 創建新陣列觸發響應式 | index.html |
| v1.2.13 | 替換整個 resilienceStatus 物件 | index.html |
| **v1.2.14** | **改用 v2 unit-level API (根因修復)** | index.html, service-worker.js |

---

## 問題四：前端狀態與後端資料脫鉤 (v1.2.10)

### 症狀
- v1.2.9 後仍然有問題
- 按確認後 API 成功，但 UI 不更新
- Vercel 和 RPi 都有同樣問題

### Gemini 分析

> 這是一個典型的 **「前端狀態與後端資料脫鉤 (State Desync)」** 問題。
>
> 問題出在：**你按了按鈕，API 送出了，但前端畫面上的「那個變數」沒有被更新，
> 或者更新了但沒有觸發重新渲染 (Re-render)。**

### 根因

```javascript
// 錯誤寫法 (只送不改)
async confirmOxygenUnit(unit) {
    await fetch('/api/...');
    // 結束了。前端沒有修改 local 的 unit 資料。
    // UI 依賴 last_check，但這個變數還是 null。
    await this.loadResilienceStatus();  // 重新載入，但可能有延遲
}
```

### 修復 (樂觀更新 Optimistic UI)

```javascript
// v1.2.10: 正確寫法 - 樂觀更新
async confirmOxygenUnit(unit) {
    const res = await fetch('/api/...');
    if (res.ok) {
        // [關鍵] 立即更新本地資料，不等重新載入
        unit.last_check = new Date().toISOString();
        unit.status = 'AVAILABLE';

        this.showToast('已確認', 'success');
        // 仍然重新載入以確保同步，但 UI 已經先更新了
        await this.loadResilienceStatus();
    }
}
```

### 關鍵概念

**樂觀更新 (Optimistic UI)**:
1. 使用者點擊按鈕
2. **立即更新 UI** (假設 API 會成功)
3. 發送 API 請求
4. API 成功 → 保持 UI 狀態
5. API 失敗 → 回滾 UI 狀態 + 顯示錯誤

這樣使用者體驗更好，不需要等待網路延遲。

---

## 問題五：樂觀更新被 loadResilienceStatus() 覆蓋 (v1.2.11)

### 症狀
- v1.2.10 的樂觀更新仍然無效
- 確認後 API 成功，unit.last_check 有設定，但 UI 仍顯示「未檢」
- console log 顯示 loadResilienceStatus() 完成後 oxygenUnits 陣列被重置

### 根因分析

**問題在於 JavaScript 陣列參照：**

```javascript
// v1.2.10 的錯誤寫法
async confirmOxygenUnit(unit) {
    const res = await fetch('/api/...');
    if (res.ok) {
        // 樂觀更新 - 修改了 this.resilienceStatus.oxygenUnits[n]
        unit.last_check = new Date().toISOString();
        unit.status = 'AVAILABLE';

        this.showToast('已確認', 'success');
        // 問題！loadResilienceStatus() 創建全新陣列
        await this.loadResilienceStatus();  // ← 這行會覆蓋我們的更新！
        this.resilienceRefreshKey++;
    }
}
```

**為什麼 loadResilienceStatus() 會覆蓋更新？**

```javascript
async loadResilienceStatus() {
    // ...
    // 這裡創建了全新的 oxygenUnits 陣列
    this.resilienceStatus = {
        oxygenUnits: oxygenUnits,    // ← 新陣列，覆蓋舊的
        powerUnits: powerUnits,       // ← 新陣列，覆蓋舊的
        oxygenResources: [...],
        powerResources: [...]
    };
}
```

當我們修改 `unit` 物件時，我們修改的是舊陣列中的元素。
但 `loadResilienceStatus()` 創建了**全新的陣列**，舊陣列（包含我們的更新）被丟棄了。

### 修復 (v1.2.11)

```javascript
// v1.2.11: 移除 loadResilienceStatus() 呼叫
async confirmOxygenUnit(unit) {
    const res = await fetch('/api/...');
    if (res.ok) {
        // 樂觀更新
        unit.last_check = new Date().toISOString();
        unit.status = 'AVAILABLE';

        this.showToast('已確認', 'success');
        // v1.2.11: 不呼叫 loadResilienceStatus()，只觸發重新渲染
        this.resilienceRefreshKey++;
    }
}
```

### 關鍵差異

| 版本 | 做法 | 結果 |
|------|------|------|
| v1.2.10 | 樂觀更新 + loadResilienceStatus() | 更新被覆蓋 |
| v1.2.11 | 樂觀更新 + resilienceRefreshKey++ | 更新保留 |

---

## 問題六：Alpine.js 響應式不偵測巢狀屬性變更 (v1.2.12)

### 症狀
- v1.2.11 修復後 RPi 和 Vercel 仍然無效
- 編輯電量、確認狀態後，系統顯示成功訊息
- 但回到前端 UI 完全沒更新，連電量都沒改變
- 清除瀏覽器快取、強制刷新仍無效

### 根因分析

**Alpine.js 響應式限制：**

Alpine.js (和 Vue.js) 的響應式系統無法偵測到**巢狀物件屬性**的變更：

```javascript
// 這樣 Alpine 不會偵測到變更！
unit.level_percent = 50;
unit.status = 'AVAILABLE';
unit.last_check = new Date().toISOString();
```

雖然我們修改了物件的屬性，但物件的**參照 (reference)** 沒有改變，Alpine 認為「這還是同一個物件」所以不重新渲染。

### v1.2.11 的問題

```javascript
// v1.2.11: 直接修改物件屬性
const updateUnit = (units) => {
    const unit = units?.find(u => u.id === this.unitEditForm.id);
    if (unit) {
        unit.level_percent = this.unitEditForm.level_percent;  // ← Alpine 不偵測
        unit.status = this.unitEditForm.status;                 // ← Alpine 不偵測
        unit.last_check = new Date().toISOString();             // ← Alpine 不偵測
    }
};
```

### 修復 (v1.2.12)

**用 `.map()` 創建新陣列，強制 Alpine 偵測變更：**

```javascript
// v1.2.12: 創建新陣列觸發 Alpine 響應式
const updateUnitInArray = (units) => {
    if (!units) return units;
    return units.map(u => {
        if (u.id === this.unitEditForm.id) {
            // 返回全新的物件 → Alpine 偵測到變更！
            return {
                ...u,
                level_percent: this.unitEditForm.level_percent,
                status: this.unitEditForm.status,
                last_check: new Date().toISOString(),
                psi: Math.round(this.unitEditForm.level_percent / 100 * 2200)
            };
        }
        return u;
    });
};

// 用新陣列取代舊陣列 → 觸發重新渲染
this.resilienceStatus.oxygenUnits = updateUnitInArray(this.resilienceStatus.oxygenUnits);
this.resilienceStatus.powerUnits = updateUnitInArray(this.resilienceStatus.powerUnits);
```

### 關鍵差異

| 版本 | 做法 | 結果 |
|------|------|------|
| v1.2.11 | `unit.prop = value` (修改屬性) | Alpine 不偵測 |
| v1.2.12 | `array.map()` (創建新陣列) | Alpine 偵測到 |

### 驗證方式

Console 會顯示：
```
[BioMed] v1.2.12: Updating unit xxx level: 50
```

如果看到這行 log 且 UI 沒更新，表示還有其他問題需調查。

---

## 問題七：v1.2.12 仍無效 - 只替換子陣列不夠 (v1.2.13)

### 症狀
- v1.2.12 部署後問題依舊
- Console 有顯示 log，但 UI 不更新
- RPi 和 Vercel 都一樣

### MIRS vs BioMed 程式碼比較

**為什麼 MIRS 可以正常運作，BioMed 不行？**

#### MIRS 的做法 (Index.html)

```javascript
// MIRS submitCheckEquipment() - 第 8211-8224 行
if (response.ok) {
    // 1. 從 API 回應更新設備
    this.updateEquipmentFromResponse(data);

    // 2. 更新韌性狀態
    if (data.dashboard_delta) {
        this.applyDashboardDelta(data.dashboard_delta);
    } else {
        // fallback: 重新載入
        await this.loadResilienceStatus();
    }
}

// MIRS updateEquipmentFromResponse() - 第 8237-8257 行
updateEquipmentFromResponse(data) {
    const idx = this.equipment.findIndex(e => e.id === eqId);
    // 替換整個物件
    this.equipment[idx] = {
        ...this.equipment[idx],
        unit_count: data.equipment_aggregate.unit_count,
        avg_level: data.equipment_aggregate.avg_level,
        check_status: data.equipment_aggregate.check_status,
        // ...
    };
}
```

**MIRS 關鍵特點**：
1. API 回傳 `equipment_aggregate` 和 `dashboard_delta`
2. 用 `this.equipment[idx] = {...}` 替換整個物件
3. 有 fallback: 如果沒有 delta，就 `loadResilienceStatus()`

#### BioMed 的問題

BioMed 的狀態結構更深層：

```
MIRS:
this.equipment[idx].check_status = 'CHECKED'  // 一層

BioMed:
this.resilienceStatus.oxygenUnits[idx].last_check = '...'  // 兩層
```

在 Alpine.js 中，巢狀越深，響應式越不可靠。

### v1.2.12 失敗原因分析

```javascript
// v1.2.12: 只替換子陣列
this.resilienceStatus.oxygenUnits = [...].map(u => ...);
// ^ 這只替換了 oxygenUnits 陣列，但 resilienceStatus 物件本身沒變
```

Alpine 可能沒有追蹤到 `resilienceStatus` 物件內部屬性的變更。

### v1.2.13 修復

**替換整個父物件**：

```javascript
// v1.2.13: 替換整個 resilienceStatus 物件
this.resilienceStatus = {
    ...this.resilienceStatus,  // 複製現有屬性
    oxygenUnits: (this.resilienceStatus.oxygenUnits || []).map(u =>
        u.id === targetId ? { ...u, last_check: newLastCheck, status: 'AVAILABLE' } : u
    ),
    powerUnits: (this.resilienceStatus.powerUnits || []).map(mapUnit)
};
```

這樣 `resilienceStatus` 本身是新物件，Alpine 一定會偵測到。

### 調試 Console Log

v1.2.13 新增更多 log：
```
[BioMed] v1.2.13: Updating unit xxx level: 50 status: AVAILABLE
[BioMed] v1.2.13: resilienceStatus replaced, refreshKey: 1
```

如果看到這些 log 但 UI 還是不更新，問題可能在：
1. 模板綁定有誤
2. 其他地方覆蓋了 resilienceStatus
3. Service Worker 快取問題

---

## MIRS vs BioMed 架構差異總結

| 項目 | MIRS | BioMed |
|------|------|--------|
| 狀態深度 | 1 層 (`this.equipment[idx]`) | 2 層 (`this.resilienceStatus.oxygenUnits[idx]`) |
| API 回傳 | `equipment_aggregate` + `dashboard_delta` | 只有成功/失敗 |
| 更新策略 | `array[idx] = {...}` 替換物件 | 需替換整個 `resilienceStatus` |
| Fallback | 有 `loadResilienceStatus()` | v1.2.11 移除了 |
| 樣板 key | 用 `eq.id` | 用 `unit.id + '-' + resilienceRefreshKey` |

### 為什麼 MIRS 直接修改屬性也能運作？

看 MIRS `applyDashboardDelta()` 第 8275-8279 行：
```javascript
ll.total_hours = delta.total_hours;
if (ll.endurance) {
    ll.endurance.effective_hours = delta.total_hours >= 999999 ? '∞' : ...;
}
```

MIRS 這裡也是直接修改屬性，為什麼能運作？

**可能原因**：
1. MIRS 的 `lifelines` 結構比較簡單
2. MIRS 的模板綁定不依賴 `lifelines` 的深層屬性
3. MIRS 有其他機制觸發重新渲染

**結論**：BioMed 的 `resilienceStatus.oxygenUnits[idx].last_check` 太深層，必須替換整個父物件。

---

## 教訓與最佳實踐

### 1. Alpine.js 響應式陣列初始化

```javascript
// 錯誤：初始化為空物件
data: { items: {} }

// 正確：明確初始化所有陣列屬性
data: { items: { list: [], filtered: [] } }
```

### 2. $nextTick 使用注意

```javascript
// 錯誤：reset 時清空陣列
this.state = {};
await this.$nextTick();

// 正確：reset 時保留空陣列結構
this.state = { items: [] };
await this.$nextTick();
```

### 3. 多欄位狀態判斷

當有多個來源的「狀態」欄位時，UI 應該考慮所有相關欄位：

```javascript
// 只看一個欄位可能不夠
isGray: item.check_status === 'UNCHECKED'

// 應該綜合判斷
isGray: item.check_status === 'UNCHECKED' && item.status !== 'NORMAL'
```

### 4. 樂觀更新 (Optimistic UI)

API 成功後，**先更新本地狀態**，再重新載入：

```javascript
// 錯誤：只送不改
async confirmItem(item) {
    await api.post('/check');
    await this.reload();  // UI 可能有延遲
}

// 正確：樂觀更新
async confirmItem(item) {
    const res = await api.post('/check');
    if (res.ok) {
        item.status = 'CHECKED';           // 立即更新
        item.last_check = new Date().toISOString();
        await this.reload();               // 背景同步
    }
}
```

### 5. 樂觀更新後不要立即重新載入

樂觀更新的關鍵是**相信本地狀態**，不要立即重新載入覆蓋它：

```javascript
// 錯誤：樂觀更新 + 立即重新載入
async confirm(item) {
    const res = await api.post('/check');
    if (res.ok) {
        item.status = 'CHECKED';           // 樂觀更新
        await this.loadAllItems();          // ← 這會覆蓋！
    }
}

// 正確：樂觀更新 + 觸發重新渲染
async confirm(item) {
    const res = await api.post('/check');
    if (res.ok) {
        item.status = 'CHECKED';           // 樂觀更新
        this.refreshKey++;                  // 觸發 Alpine 重新渲染
    }
}
```

### 6. Alpine.js 響應式更新巢狀物件

Alpine.js 不會偵測巢狀物件屬性變更，必須創建新物件：

```javascript
// 錯誤：直接修改屬性
item.value = newValue;  // Alpine 不偵測

// 正確：用 .map() 創建新陣列
this.items = this.items.map(i =>
    i.id === targetId
        ? { ...i, value: newValue }  // 新物件
        : i
);
```

### 7. Alpine.js 深層響應式 - 替換父物件

當狀態結構超過一層時，替換整個父物件最可靠：

```javascript
// 錯誤：只替換子陣列
this.parentObj.childArray = this.parentObj.childArray.map(item => ...);

// 正確：替換整個父物件
this.parentObj = {
    ...this.parentObj,
    childArray: this.parentObj.childArray.map(item => ...)
};
```

---

## 問題八：checkEquipment() 使用錯誤的 API 端點 (v1.2.14) 🎯 根因修復

### 症狀
- v1.2.13 的 Alpine 響應式修復仍然無效
- 設備確認後 API 回應 200 成功
- 但 `check_status` 仍然是 `UNCHECKED`
- RPi 和 Vercel 都有同樣問題

### Gemini + ChatGPT 關鍵分析

> **ChatGPT 批判點**:
> BioMed 的 `checkEquipment()` 函數（第 1473 行）使用的是**舊的 API 端點**：
> ```javascript
> fetch(`/api/equipment/check/${eq.id}`)
> ```
> 這個舊 API 只更新 `equipment.status`，**不會更新 `equipment_units.last_check`**！
>
> 而 `v_equipment_status` 視圖計算 `check_status` 是根據 `equipment_units.last_check`。
> 所以舊 API 執行後，`equipment.status = 'NORMAL'`，但 `check_status` 仍然是 `UNCHECKED`！

### 根因分析

**兩個 API 的差異：**

| API | 更新什麼 | 影響 check_status |
|-----|---------|-------------------|
| `/api/equipment/check/{id}` (舊) | `equipment.status` | ❌ 不影響 |
| `/api/v2/equipment/units/{id}/check` (v2) | `equipment_units.last_check` | ✅ 會更新 |

**v_equipment_status 視圖的計算邏輯：**

```sql
CREATE VIEW v_equipment_status AS
SELECT
    CASE
        WHEN COUNT(u.id) = 0 THEN 'NO_UNITS'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0 THEN 'UNCHECKED'
        WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id) THEN 'CHECKED'
        ELSE 'PARTIAL'
    END as check_status
FROM equipment e
LEFT JOIN equipment_units u ON e.id = u.equipment_id
```

視圖只看 `equipment_units.last_check`，完全不管 `equipment.status`！

### 為什麼其他函數可以運作？

BioMed 中的其他確認函數都使用正確的 v2 API：

```javascript
// confirmOxygenUnit() - 第 1408 行 ✅
fetch(`/api/v2/equipment/units/${unit.id}/check`, ...)

// checkUnit() - 第 1989 行 ✅
fetch(`/api/v2/equipment/units/${unit.id}/check`, ...)

// updateUnitStatus() - 第 2015 行 ✅
fetch(`/api/v2/equipment/units/${unit.id}/check`, ...)
```

只有 `checkEquipment()` 用舊 API！

### v1.2.14 修復

**重構 `checkEquipment()` 函數：**

1. 先取得該設備的所有 units
2. 對每個 unit 呼叫 v2 API
3. 如果設備沒有 units，先建立一個

```javascript
// v1.2.14: 修正 checkEquipment 使用 v2 unit-level API
async checkEquipment(eq) {
    console.log('[BioMed] v1.2.14: checkEquipment for', eq.id, eq.name);

    // Step 1: 取得該設備的所有 units
    const unitsRes = await fetch(`/api/v2/equipment/${eq.id}/units`);
    const unitsData = await unitsRes.json();
    const units = unitsData.units || [];

    if (units.length === 0) {
        // 沒有 units，需要先建立一個
        const createRes = await fetch(`/api/v2/equipment/${eq.id}/units`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level_percent: 100, status: 'AVAILABLE' })
        });
        const newUnit = await createRes.json();
        units.push({ id: newUnit.unit_id });
    }

    // Step 2: 對每個 unit 呼叫 v2 check API
    for (const unit of units) {
        await fetch(`/api/v2/equipment/units/${unit.id}/check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                level_percent: unit.level_percent || 100,
                status: 'AVAILABLE'
            })
        });
    }

    // Step 3: 樂觀更新 + 重新載入
    this.equipment[idx] = { ...this.equipment[idx], check_status: 'CHECKED' };
    await this.loadEquipment();
    await this.loadResilienceStatus();
}
```

### 關鍵差異

| 項目 | v1.2.13 (之前) | v1.2.14 (修復) |
|------|----------------|----------------|
| API 端點 | `/api/equipment/check/{id}` | `/api/v2/equipment/units/{id}/check` |
| 更新的欄位 | `equipment.status` | `equipment_units.last_check` |
| 視圖計算 | `check_status` 不變 | `check_status` 變為 CHECKED |
| 沒有 units 時 | 無法運作 | 自動建立 unit |

### 為什麼花了 8 個版本才找到根因？

1. **症狀誤導**：UI 不更新 → 以為是 Alpine 響應式問題
2. **API 成功**：舊 API 回傳 200 OK → 以為後端正常
3. **多重原因**：確實有 Alpine 響應式問題，但不是主因
4. **測試環境差異**：Vercel Demo 資料不完整，難以驗證

### 教訓

1. **API 文件化**：每個 API 應該清楚說明它更新哪些欄位
2. **視圖依賴**：視圖計算邏輯應該與 API 行為一致
3. **統一 API 版本**：新舊 API 不應該共存太久
4. **從資料流追查**：UI 問題不一定是前端問題，要追溯整個資料流

---

## 修復完成確認清單

| 項目 | v1.2.14 狀態 |
|------|-------------|
| checkEquipment() 使用 v2 API | ✅ |
| 處理沒有 units 的設備 | ✅ (自動建立) |
| Service Worker 版本更新 | ✅ v1.2.14 |
| DEV SPEC 文件更新 | ✅ |

---

**文件版本**: v1.5
**撰寫者**: Claude Code + Gemini (程式碼審查) + ChatGPT (架構分析)
**日期**: 2026-01-11
