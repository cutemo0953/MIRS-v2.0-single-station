# Blood Bank PWA DEV SPEC v2.6

**版本**: 2.6
**日期**: 2026-01-13
**狀態**: UI 改進完成 (仿原始 MIRS 血庫設計)
**基於**: v2.5 (P4 Pending Order + Reserve Timeout) + 使用者回饋

---

## v2.5 → v2.6 變更摘要

### UI/UX 改進 (仿原始 MIRS 血庫設計)

| 項目 | 狀態 | 說明 |
|------|------|------|
| **血型庫存統計區** | ✅ 完成 | 深紅色背景，8 血型大字顯示 (仿原始 MIRS) |
| **血品類型色塊系統** | ✅ 完成 | WB 深紅、PRBC 紅、FFP 琥珀、PLT 黃、CRYO 青 |
| **新增 WB (全血)** | ✅ 完成 | Whole Blood 支援緊急用血場景 |
| **血袋清單 UI 簡化** | ✅ 完成 | 左側狀態色條 + 清晰血型/血品顯示 |
| **列印標籤功能** | ✅ 完成 | 入庫時可列印血袋標籤 |
| **手動位置輸入** | ✅ 完成 | 發血時可直接輸入送血目的地 |
| **血品類型選擇** | ✅ 完成 | 發血時可選擇血品類型過濾 |

### 實作檔案

| 檔案 | 變更 |
|------|------|
| `frontend/blood/index.html` | +262 行 UI 改進 |

---

## 改進項目詳情

### 1. 庫存總覽 - 血型統計區

仿原始 MIRS 深紅色背景設計，提供一目了然的庫存總覽：

```
┌─────────────────────────────────────────────────────────────────┐
│  血型庫存統計                                                     │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐      │
│  │ O+ │ │ O- │ │ A+ │ │ A- │ │ B+ │ │ B- │ │AB+│ │AB-│      │
│  │ 12 │ │  3 │ │  8 │ │  2 │ │  5 │ │  1 │ │  4 │ │  0 │      │
│  │ 袋 │ │ 袋 │ │ 袋 │ │ 袋 │ │ 袋 │ │ 袋 │ │ 袋 │ │ 袋 │      │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘      │
└─────────────────────────────────────────────────────────────────┘
```

**技術實作**：
```javascript
// 按血型分組的庫存統計
get groupedByBloodType() {
    const bloodTypes = ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-'];
    return bloodTypes.map(bt => {
        const items = this.availability.filter(a => a.blood_type === bt);
        const total = items.reduce((sum, item) => sum + (item.available_count || 0), 0);
        return { blood_type: bt, total };
    });
}
```

### 2. 血品類型色塊系統

新增 5 種血品類型的顏色識別：

| 血品類型 | 顏色 | CSS 類別 | 說明 |
|----------|------|----------|------|
| **WB** (全血) | 深紅 #7f1d1d | `unit-type-wb` | 緊急用血 |
| **PRBC** (紅血球) | 紅 #dc2626 | `unit-type-prbc` | 最常用 |
| **FFP** (血漿) | 琥珀 #d97706 | `unit-type-ffp` | 凝血因子 |
| **PLT** (血小板) | 黃 #eab308 | `unit-type-plt` | 止血 |
| **CRYO** (冷沉澱) | 青 #0891b2 | `unit-type-cryo` | 纖維蛋白原 |

**CSS 定義**：
```css
.unit-type-wb { background-color: #7f1d1d; color: white; }
.unit-type-prbc { background-color: #dc2626; color: white; }
.unit-type-ffp { background-color: #d97706; color: white; }
.unit-type-plt { background-color: #eab308; color: #1f2937; }
.unit-type-cryo { background-color: #0891b2; color: white; }
```

### 3. 新增 WB (全血) 支援

**為什麼需要 WB**：
> 緊急時連到捐血中心拿血都有問題，甚至可能緊急捐血流程比較實際。

- 緊急大量傷患時，Walking Blood Bank (現場捐血) 是實際選項
- 全血包含所有成分，適合大量失血急救
- 減少分離/處理時間，直接輸注

**入庫預設改為 WB**：
```javascript
receiveForm: {
    blood_type: 'O+',
    unit_type: 'WB',  // v2.6: 預設全血
    expiry_date: '',
    donation_id: ''
}
```

### 4. 血袋清單 UI 簡化

原本設計過於複雜，顏色混亂。v2.6 改用左側狀態色條：

```
┌─────────────────────────────────────────────────────────────────┐
│ ▌ O+   [紅血球]  [FIFO]                        剩 48h          │
│ ▌綠    BU-1705123456-abcd1234                                   │
│ └──────────────────────────────────────────────────────────────│
│   [    發血    ]  [   預約   ]                                  │
└─────────────────────────────────────────────────────────────────┘
```

**狀態色條**：
- 綠色：可用 (AVAILABLE)
- 藍色：已預約 (RESERVED)
- 琥珀色：即將過期 (EXPIRING_SOON)
- 紅色：已過期 (EXPIRED)

### 5. 列印標籤功能

參考原始 MIRS 的列印標籤功能，新增入庫時可列印血袋標籤：

```javascript
printBloodLabel() {
    // 產生 60mm x 40mm 標籤
    // 顯示：血品類型、血型、效期、捐血編號、列印時間
    // 顏色依血品類型變化
}
```

**標籤樣式**：
```
┌────────────────────────────────────────┐
│ ███ 紅血球 PRBC ███                    │
│                                        │
│           O+                           │
│                                        │
│ 效期: 2026-02-15                       │
│ 捐血編號: D-12345678                   │
│ 列印時間: 2026-01-13 10:30             │
│                                        │
│ BU-1705123456-abcd1234                 │
└────────────────────────────────────────┘
```

### 6. 發血改進

**新增手動位置輸入**：
- 當無法查詢病患位置時，可直接輸入送血目的地
- 例如：ER-05, ICU-01, OR-2, WARD-305

**新增血品類型選擇**：
- 發血時可選擇血品類型 (WB/PRBC/FFP/PLT/CRYO)
- 系統會自動過濾符合條件的血袋

```javascript
issueFlow: {
    ...
    manualLocation: '',  // v2.6: 手動輸入位置
    unitType: '',        // v2.6: 血品類型
    ...
}
```

---

## 技術實作細節

### 新增 JavaScript 輔助函數

```javascript
// 血品類型 CSS 類別
getUnitTypeClass(unitType) {
    const classes = {
        'WB': 'unit-type-wb',
        'PRBC': 'unit-type-prbc',
        'FFP': 'unit-type-ffp',
        'PLT': 'unit-type-plt',
        'CRYO': 'unit-type-cryo'
    };
    return classes[unitType] || 'bg-gray-500 text-white';
}

// 血品類型邊框顏色
getUnitTypeBorderClass(unitType) {
    const classes = {
        'WB': 'border-red-900',
        'PRBC': 'border-red-500',
        'FFP': 'border-amber-500',
        'PLT': 'border-yellow-400',
        'CRYO': 'border-cyan-500'
    };
    return classes[unitType] || 'border-gray-300';
}

// 血品類型標籤
getUnitTypeLabel(unitType) {
    const labels = {
        'WB': '全血',
        'PRBC': '紅血球',
        'FFP': '血漿',
        'PLT': '血小板',
        'CRYO': '冷沉澱'
    };
    return labels[unitType] || unitType;
}
```

### processIssue 更新

```javascript
async processIssue() {
    // v2.6: 優先使用病患位置，否則使用手動輸入位置
    const finalLocation = patientLocation || manualLocation;

    // v2.6: Auto-select units by blood type AND unit type (FIFO)
    if (unitType) {
        apiUrl += `&unit_type=${unitType}`;
    }

    // v2.6: 更新 issueResult 使用合併的位置
    this.issueResult = {
        location: finalLocation,
        locationName: patientLocationName || (manualLocation ? '手動輸入' : ''),
        bloodInfo: `${bloodType} ${unitTypeLabel} x ${issuedUnits.length} 單位`,
        ...
    };
}
```

---

## 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| v2.5 | 2026-01-12 | P4: 待補單追蹤 + 預約逾時自動釋放 |
| v2.6 | 2026-01-13 | UI 改進: 仿原始 MIRS 血庫設計、血品色塊、WB 支援、列印標籤 |

---

**文件完成**
**撰寫者**: Claude Code
**日期**: 2026-01-13
