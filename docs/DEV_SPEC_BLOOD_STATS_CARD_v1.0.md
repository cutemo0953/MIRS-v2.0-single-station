# MIRS/Blood Bank PWA 血庫即時統計卡片 DEV SPEC

**版本**: 1.2
**日期**: 2026-01-16
**狀態**: 實作中
**影響系統**: MIRS Index.html, Blood Bank PWA

---

## 問題描述

### 用戶報告
> 1. "為何 MIRS 無法像 Blood Bank PWA 看到各血型血袋的即時統計？"
> 2. "Blood Bank PWA 點選即時統計卡片可以選擇血型，下面又有一排按鈕選擇血型？"

### 現況分析

| 系統 | UI 顯示 | 資料來源 |
|------|---------|----------|
| **MIRS 主介面** | 只有總數（簡化版） | `stats.totalBlood` |
| **Blood Bank PWA** | 8 個血型卡片 + 可點擊篩選 | `groupedByBloodType` |

**後端 API 相同**：都使用 `/api/blood/availability`

**前端差異**：
- Blood Bank PWA 有完整的 `groupedByBloodType` 計算和 8 卡片 UI
- MIRS 主介面在 v2.8.1 簡化為只顯示總數

### 根因

MIRS `Index.html` 第 1582-1598 行：

```html
<!-- v2.8.1: 血袋即時統計 - 簡化版 (僅深紅底+總數) -->
<div class="bg-red-900 rounded-xl p-4 sm:p-6 mb-6 shadow-xl">
    <div class="text-3xl font-black text-yellow-300" x-text="stats.totalBlood"></div>
    <p class="text-red-200 text-sm mt-2">
        完整血袋清單請至 <a href="/blood/">Blood Bank PWA</a> 查看
    </p>
</div>
```

但 MIRS 其實已經有 `bloodInventory` 陣列（第 5084 行），包含各血型資料，只是 UI 沒使用它。

### 問題 2：Blood Bank PWA 雙重篩選 UI 衝突

Blood Bank PWA 目前有**兩套篩選 UI**，使用**不同的 state 變數**，造成混淆：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Blood Bank PWA 的 UI 衝突                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1️⃣ 統計卡片（第 187-188 行）                                        │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                                   │
│  │ O+  │ │ O-  │ │ A+  │ │ A-  │ ...                               │
│  └─────┘ └─────┘ └─────┘ └─────┘                                   │
│     ↓ @click="filterByBloodType(blood.blood_type)"                 │
│     ↓ 設定 dashboardFilter                                          │
│                                                                     │
│  2️⃣ 按鈕列（第 239-251 行）← 重複功能！                              │
│  [全部] [O+] [O-] [A+] [A-] [B+] [B-] [AB+] [AB-]                   │
│     ↓ @click="unitFilter = type"                                   │
│     ↓ 設定 unitFilter                                               │
│                                                                     │
│  ⚠️ 兩個 state 不同步！                                              │
│  - dashboardFilter → filteredByDashboard (availability 統計)       │
│  - unitFilter → filteredUnits (血袋清單)                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**程式碼證據**：

```javascript
// 第 1164-1165 行：兩個不同的 state
unitFilter: '',
dashboardFilter: '',  // v2.7: Dashboard blood type filter

// 第 1293-1296 行：血袋清單用 unitFilter
get filteredUnits() {
    if (!this.unitFilter) return this.units;
    return this.units.filter(u => u.blood_type === this.unitFilter);
},

// 第 1372-1374 行：統計用 dashboardFilter
get filteredByDashboard() {
    if (!this.dashboardFilter) return this.availability;
    return this.availability.filter(a => a.blood_type === this.dashboardFilter);
},
```

**結果**：點擊統計卡片不會篩選下方的血袋清單！用戶以為點了卡片會篩選，但實際上要點下面的按鈕才會。

---

## 解決方案

### 方案 A：將 Blood Bank PWA 的統計卡片移植到 MIRS（推薦）

把 Blood Bank PWA 的 8 血型卡片 UI 加回 MIRS 主介面。

**優點**：
- 用戶不需跳到另一個 PWA 就能看到各血型統計
- MIRS 已有 `bloodInventory` 資料，無需改後端

**實作步驟**：

1. 在 MIRS `Index.html` 的血袋 Tab 加入卡片 Grid
2. 支援點擊卡片篩選（複用 `filterBloodType`）

### 方案 B：保持現狀，只在 Blood Bank PWA 顯示

維持 MIRS 簡化版，用戶需要詳細資訊時跳到 Blood Bank PWA。

**優點**：
- 職責分離（MIRS = 總覽，Blood Bank PWA = 專業版）
- 減少 MIRS 主介面複雜度

### 問題 2 解決方案：Blood Bank PWA 雙重篩選 UI 統一

**目標**：統一 `dashboardFilter` 和 `unitFilter` 為單一 state `bloodTypeFilter`

**實作步驟**：

1. **刪除冗餘 state**：移除 `dashboardFilter` 和 `unitFilter`，新增 `bloodTypeFilter`
2. **更新 `filterByBloodType()`**：設定 `bloodTypeFilter`
3. **更新 `filteredUnits`**：使用 `bloodTypeFilter`
4. **移除冗餘按鈕列**：刪除第 239-252 行的按鈕列（功能由卡片取代）
5. **更新篩選狀態指示器**：使用 `bloodTypeFilter`

**程式碼變更**：

```javascript
// Before (兩個 state)
unitFilter: '',
dashboardFilter: '',

// After (單一 state)
bloodTypeFilter: '',  // v2.9: 統一篩選

// filterByBloodType() - 保持不變，只改變數名
filterByBloodType(bloodType) {
    if (this.bloodTypeFilter === bloodType) {
        this.bloodTypeFilter = '';
    } else {
        this.bloodTypeFilter = bloodType;
    }
},

// filteredUnits - 使用統一 state
get filteredUnits() {
    if (!this.bloodTypeFilter) return this.units;
    return this.units.filter(u => u.blood_type === this.bloodTypeFilter);
},
```

**UI 變更**：
- 刪除血型按鈕列（第 239-252 行）
- 點擊統計卡片即可篩選下方血袋清單
- 卡片高亮顯示當前篩選狀態

---

## 推薦實作（方案 A）

### UI 設計

```
┌─────────────────────────────────────────────────────────────────────┐
│  血庫即時統計                                                 28 袋  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐  │
│  │ O+  │ │ O-  │ │ A+  │ │ A-  │ │ B+  │ │ B-  │ │ AB+ │ │ AB- │  │
│  │ 8U  │ │ 5U  │ │ 6U  │ │ 2U  │ │ 4U  │ │ 1U  │ │ 2U  │ │ 0U  │  │
│  │ ⚠1  │ │     │ │     │ │     │ │ ⚠1  │ │     │ │     │ │     │  │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘  │
│                                                                     │
│  [點擊卡片可篩選下方血袋清單]                                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 互動行為

1. **預設**：顯示全部血袋（無篩選）
2. **點擊卡片**：篩選該血型，卡片高亮
3. **再次點擊**：取消篩選
4. **即期警示**：如果該血型有即期血袋，卡片顯示 ⚠ 警示

### 程式碼變更

#### 1. 新增 Template（替換第 1582-1598 行）

```html
<!-- v2.9: 血袋即時統計 - 各血型卡片 -->
<div class="bg-red-900 rounded-xl p-4 sm:p-6 mb-6 shadow-xl">
    <div class="flex items-center justify-between mb-4">
        <h3 class="text-white text-lg font-bold flex items-center gap-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
            </svg>
            血庫即時統計
        </h3>
        <div class="text-right">
            <div class="text-3xl font-black text-yellow-300" x-text="stats.totalBlood"></div>
            <div class="text-sm text-red-200">袋</div>
        </div>
    </div>

    <!-- 8 血型卡片 Grid -->
    <div class="grid grid-cols-4 sm:grid-cols-8 gap-2 sm:gap-3">
        <template x-for="blood in bloodInventory" :key="blood.blood_type">
            <div @click="toggleBloodFilter(blood.blood_type)"
                 class="cursor-pointer rounded-lg p-2 sm:p-3 transition-all duration-200 text-center"
                 :class="{
                     'bg-red-800 hover:bg-red-700 ring-2 ring-yellow-400': filterBloodType === blood.blood_type,
                     'bg-red-800/50 hover:bg-red-700/50': filterBloodType !== blood.blood_type && blood.quantity > 0,
                     'bg-gray-700/50': blood.quantity === 0
                 }">
                <!-- 血型 -->
                <div class="text-xl sm:text-2xl font-black text-white" x-text="blood.blood_type"></div>
                <!-- 數量 -->
                <div class="text-lg sm:text-xl font-bold"
                     :class="blood.quantity > 0 ? 'text-yellow-300' : 'text-gray-500'">
                    <span x-text="blood.quantity"></span>U
                </div>
                <!-- 即期警示 -->
                <div x-show="blood.expiring_soon > 0" class="text-xs text-amber-400 flex items-center justify-center gap-1 mt-1">
                    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                    </svg>
                    <span x-text="blood.expiring_soon"></span>
                </div>
            </div>
        </template>
    </div>

    <!-- 篩選狀態 -->
    <div x-show="filterBloodType" class="mt-3 flex items-center justify-between bg-red-800/50 rounded-lg p-2">
        <span class="text-red-200 text-sm">
            篩選中: <span class="font-bold text-white" x-text="filterBloodType"></span>
        </span>
        <button @click="filterBloodType = ''" class="text-red-200 text-sm underline hover:text-white">清除篩選</button>
    </div>
</div>
```

#### 2. 新增 Method（約第 7380 行）

```javascript
toggleBloodFilter(bloodType) {
    if (this.filterBloodType === bloodType) {
        this.filterBloodType = '';  // 再次點擊清除
    } else {
        this.filterBloodType = bloodType;
    }
},
```

#### 3. 修改血袋清單篩選邏輯

確保血袋清單使用 `filterBloodType` 進行篩選（如果尚未實作）。

---

## 測試計畫

```gherkin
Scenario: 各血型卡片顯示正確數量
  Given MIRS 主介面載入完成
  When 血袋 Tab 顯示
  Then 應看到 8 個血型卡片
  And 每個卡片顯示正確的數量和即期數

Scenario: 點擊卡片篩選
  Given 血袋清單有多種血型
  When 點擊 "O+" 卡片
  Then 該卡片應高亮（黃色邊框）
  And 下方血袋清單只顯示 O+ 血袋
  When 再次點擊 "O+" 卡片
  Then 篩選應取消
  And 顯示全部血袋

Scenario: 即期警示
  Given O+ 有 2 袋即期血袋
  When 查看 O+ 卡片
  Then 應顯示 ⚠ 圖示和 "2" 數字
```

---

## 相關檔案

| 檔案 | 變更 |
|------|------|
| `Index.html` | 新增血型卡片 Grid UI |
| `routes/blood.py` | 不需變更（API 已完整） |
| `frontend/blood/index.html` | 參考實作（已有完整功能） |

---

## 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-01-16 | 初版 |
| 1.1 | 2026-01-16 | 新增問題 2：Blood Bank PWA 雙重篩選 UI 衝突分析 |
| 1.2 | 2026-01-16 | 新增問題 2 解決方案：統一 filter state |

---

**文件版本**: 1.2
**撰寫者**: Claude Code
**日期**: 2026-01-16
