# BioMed PWA v1.2.6 ~ v1.2.9 Bug 修復記錄

**日期**: 2026-01-11
**版本**: v1.2.6 → v1.2.9
**問題來源**: RPi 實機測試

---

## 問題一覽

| 版本 | 問題 | 根因 | 修復 |
|------|------|------|------|
| v1.2.6 | 氧氣區域錯誤顯示呼吸器 | 過濾器用 category 包含「呼吸」| 改用名稱過濾，排除「呼吸器」|
| v1.2.6 | 韌性估算狀態只有 3 種 | 單位編輯 Modal 缺少 EMPTY | 新增 EMPTY 選項 |
| v1.2.7 | 設備確認後仍灰階顯示 | 灰階條件用 check_status，但舊 API 只更新 status | 條件改為 `check_status=UNCHECKED && status!=NORMAL` |
| v1.2.8 | Alpine undefined 錯誤 | resilienceStatus 初始為空物件 | 初始化包含空陣列 |
| v1.2.9 | v1.2.8 修復無效 | $nextTick 前的 reset 清空陣列 | reset 時也保留空陣列 |

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

---

**文件版本**: v1.0
**撰寫者**: Claude Code
**日期**: 2026-01-11
