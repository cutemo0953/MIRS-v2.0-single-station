# MIRS 設備韌性整合規格 v1.4.8

> Updated: 2025-12-17
> Part of: MIRS v1.4.8 Single Station

---

## ⚠️ 架構重構計畫

> **重要**: 本規格將於 v2.0 進行重大架構重構，解決資料同步與擴展性問題。

詳見: **[EQUIPMENT_ARCHITECTURE_REDESIGN.md](./EQUIPMENT_ARCHITECTURE_REDESIGN.md)**

| 現況問題 | v2.0 解決方案 |
|---------|--------------|
| equipment / equipment_units 狀態不一致 | Single Source of Truth (只存 units) |
| AGGREGATE / PER_UNIT 雙軌邏輯 | Unit-Centric (全部統一為 units) |
| 設備類型硬編碼於程式碼 | equipment_types 表 + Calculator Strategy |
| 前端需 refreshKey 技巧 | API 回傳即時計算的聚合值 |

**狀態**: ✅ 已通過外部評審 (Gemini)，可開始實作

---

## Changelog

### v1.4.8 (2025-12-17)
- **架構重構計畫**: 新增 EQUIPMENT_ARCHITECTURE_REDESIGN.md
  - 解決 equipment / equipment_units 狀態同步問題
  - 設計 equipment_types 表支援可配置設備類型
  - 規劃 v2 API 與 Calculator Strategy 模式
  - 通過 Gemini 外部評審，確認可執行

### v1.4.7 (2025-12-16)
- **電力設備 PER_UNIT 追蹤**: 支援個別追蹤每台電源站/發電機
  - 電源站、發電機可設定 `tracking_mode = 'PER_UNIT'`
  - 個別單位有獨立電量/油量百分比和狀態
  - UI 顯示各單位進度條和狀態標籤
- **電力設備狀態選項**: 新增適合電力設備的狀態
  - `AVAILABLE` - 待命可用
  - `IN_USE` - 供電中 (綠色)
  - `CHARGING` - 充電中 (藍色，會計入容量但顯示提醒)
  - `MAINTENANCE` - 維護中 (橘色，不計入容量)
  - `OFFLINE` - 離線/故障 (紅色，不計入容量)
- **充電提醒**: CHARGING 狀態的設備會計入當前電量
  - API 回傳 `charging_warnings` 提醒用戶
  - 訊息：「請於充電完成後記得更新設備狀態」
- **電力設備編輯 Modal**: 新增專屬電力設備的編輯介面
  - 可調整電量/油量百分比
  - 可選擇 5 種狀態
  - 發電機顯示「油量百分比」，電源站顯示「電量百分比」
- **Seeder 更新**: Demo 資料新增電力設備單位
  - 行動電源站 ×2 (95% IN_USE, 60% CHARGING)
  - 發電機 ×1 (100% AVAILABLE)

### v1.4.6 (2025-12-16)
- **最弱環節修正**: 氧氣濃縮機不再覆蓋鋼瓶計算
  - 跳過「受依賴限制」的設備（如氧氣濃縮機受電力限制）
  - 避免重複計算，正確顯示瓶頸來源
- **UI 響應修正**: 設備檢查後灰黃變色不需切換 Tab
  - 使用 `lifelinesRefreshKey` 強制 DOM 重建
  - 簡化更新流程，提升可靠性
- **PostgreSQL 支援**: 新增 Neon 雲端資料庫連接
  - 新增 db_postgres.py 提供相容介面
  - 支援 Vercel 無伺服器部署

### v1.2.8 (2025-12-16)
- **檢查歷史記錄**: 新增 `equipment_check_history` 表，完整追蹤設備檢查記錄
  - 每次編輯自動記錄：變更前/後百分比、狀態、時間
  - 支援稽核需求，保留完整操作軌跡
- **每日檢查報表**: 新增「檢查報表」按鈕
  - 顯示每日檢查摘要：設備數、單位數、檢查次數
  - 可選擇日期查看歷史記錄
  - 支援 CSV 匯出供日後查核
- **未檢查灰顯**: 未檢查的分項以灰階+虛線邊框顯示
  - 已檢查：綠色勾勾 + 琥珀色進度條
  - 未檢查：時鐘圖示 + 灰色進度條
  - 顯示檢查進度 (n/m 已檢查)
- **重置檢查狀態**: 已檢查項目可重置為未檢查（保留歷史記錄）
  - 適用於誤點檢查或需要重新檢查的情況
  - 後台保留 RESET 記錄，報表只顯示最新狀態
- **一鍵下載增強**: 緊急備份新增 CSV 檔案
  - equipment_units.csv - 設備分項 (氧氣瓶充填%)
  - equipment_check_history.csv - 檢查歷史記錄
- **自動同步**: 分項編輯後自動計算平均值同步至設備表
  - 所有分項檢查完成後，設備狀態自動變為 NORMAL
- **UI 即時刷新**: 修復編輯後需刷新頁面的問題

### v1.2.7 (2025-12-16)
- **UI 配色統一**: 韌性估算 Tab 改用 amber/gray 雙色系
  - 移除紅黃綠狀態色，改用圖示區分狀態
  - 主色: amber-500/600，次色: gray-400/500
- **單位編輯功能**: 韌性設備明細支援個別單位編輯
  - 點擊編輯按鈕開啟 Modal
  - 可調整充填%和狀態
  - 新增 API `/api/equipment/units/update`
- **電力/氧氣雙區顯示**: 生命線改為左右對照設計，一目瞭然

### v1.2.6 (2025-12-16)
- **個別鋼瓶追蹤**: 新增 `equipment_units` 表，支援每支氧氣瓶獨立追蹤充填百分比
  - tracking_mode: `AGGREGATE`(預設) 或 `PER_UNIT`(個別追蹤)
  - 有效容量 = Σ(單位容量 × 充填%)
- **樹狀展開介面**: 韌性設備明細支援展開/收合，一目瞭然各單位狀態
  - 進度條顯示充填%，顏色區分: amber (統一)
  - 狀態標籤: 備用(AVAILABLE) / 使用中(IN_USE) / 空瓶(EMPTY) / 維護中
- **氧氣濃縮機公式**: 新增製造機+電力依賴計算說明

### v1.2.5 (2025-12-16)
- **電力計算重構**: 改用設備瓦數累計計算
  - 總負載 = Σ(設備.power_watts)
  - 電源站時數 = capacity_wh × (power_level%) ÷ 總負載
  - 發電機時數 = (油箱 + 備用油料) ÷ fuel_rate_lph
- **氧氣鋼瓶設備導向**: 移除庫存表的氧氣鋼瓶項目 (O2-CYL-*)，統一用設備管理
- **備用油料追蹤**: 新增 FUEL-001 備用油桶設備類型 (device_type='FUEL_RESERVE')
- **電力來源明細**: API 回應新增 `sources` 陣列，顯示各電源貢獻時數

### v1.2.4 (2025-12-16)
- **氧氣濃縮機容量修正**: API 回應現在正確包含 `capacity_each: null` 欄位，避免前端顯示 "undefinedL"
- **小數人數輸入**: 支援輸入 0.6、0.3 等小數值，換算面罩/鼻導管氧氣需求
- **等效人數說明**: UI 新增「插管=1.0 | 面罩≈0.6 | 鼻導管≈0.3」提示
- **設備清理**: 移除重複設備 EQ-010（與 UTIL-001 行動電源站重複）
- **容量對照表更新**: 移除已刪除的 EQ-010，簡化電力設備映射

### v1.2.3 (2025-12-16)
- **文件更新**: 同步 IRS_RESILIENCE_FRAMEWORK.md 實作說明
- **人數為零處理**: 支援 population_count=0 時氧氣需求為 0（無插管病患情境）
- **等效人數換算**: UI 公式說明新增非插管病患的氧氣用量換算提示

### v1.2.2 (2025-12-15)
- **設備連動韌性**: 韌性計算改用「設備管理」表的數量，而非「庫存」表
- **power_level 影響**: 設備檢查的 % 會影響有效容量（例如 80% 鋼瓶 = 80% 容量）
- **新增容量對照表**: RESP-001=6900L, EMER-EQ-006=680L, UTIL-002=50L

### v1.2.1 (2025-12-15)
- **人數連動**: 插管人數變更時，氧氣韌性時數即時更新
- **視覺回饋**: 設定變更後顯示 toast 通知，確認更新成功
- **公式文件**: 新增「韌性計算公式說明」供站務人員參考
- **icon修正**: 可獨立運作統計卡片 icon 改為灰色

### v1.2 (2025-12-15)
- **顏色統一**: 設備 Tab 所有區塊統一使用 equipment 色系
- **庫存試劑 Tab**: 顏色與藥品/耗材一致 (移除紫色)
- **韌性設備**: 改為表格式設計，支援新增/刪除/檢查
- **即時統計卡片**: 新增「可獨立運作」統計 (顯示最短韌性時數)
- **瓶頸顯示**: 移至韌性估算 Tab 內，不在頂部統計卡片
- **即時更新**: 設備檢查後自動更新生命線卡片

### v1.1 (2025-12-15)
- 設備 Tab 重新分類 (供電/耗電/非耗電/手術包)
- 韌性估算 Tab 新增韌性設備區塊
- 移除試劑監控列表 (已有獨立 Tab)

---

## 問題分析

### 1. 設備檢查欄位不一致 ✅ (已修正)
目前所有設備都使用 `power_level` 欄位，但不同設備需要不同指標：

| 設備類型 | 目前欄位 | 應改為 | 單位 | 韌性影響 |
|---------|---------|-------|------|---------|
| 氧氣鋼瓶 (RESP-001) | power_level | **gas_level** | PSI 或 % | 氧氣供應時數 |
| 氧氣瓶 E size (EMER-EQ-006) | power_level | **gas_level** | PSI 或 % | 氧氣供應時數 |
| 發電機 (UTIL-002) | power_level | **fuel_level** | % | 電力供應時數 |
| 行動電源站 (UTIL-001) | power_level | **battery_level** | % | 電力供應時數 |
| AED (EMER-EQ-001) | power_level | **battery_level** | % | 急救能力 |
| 冰箱/冷凍櫃 | N/A | **temperature** | °C | 藥品/血液保存 |
| 電池式骨鋸/骨鑽 | N/A | **battery_level** | % | 手術執行 |

### 2. 庫存分類建議 ✅ (已修正)
依醫院管理模式，應區分：

| 分類 | 管理單位 | UI Tab | 前綴 |
|------|---------|--------|------|
| 耗材 | 護理部 | 耗材 | 其他 |
| 藥品 | 藥劑科 | 藥品 | MED- |
| **檢驗試劑** | **檢驗科** | **試劑** | REA- |

### 3. 設備 Tab 分類混亂 (新問題)
目前「電氣設備」區塊包含太多不同類型設備，不易一眼找到韌性關鍵設備：

**現狀問題：**
- 供電設備 (發電機、電源站) 與耗電設備混在一起
- 韌性關鍵設備 (氧氣、電力) 難以快速識別
- 韌性估算 Tab 移除試劑列表後空間浪費

### 4. 韌性估算 Tab 內容重複 (新問題)
- 試劑列表已有獨立 Tab，韌性估算 Tab 不需重複顯示
- 韌性設備應從設備 Tab 移至韌性估算 Tab 集中管理

---

## 改進方案 v1.2

### Phase 0: UI 重組 (Frontend) - 本次實作

#### 0.1 設備 Tab 重新分類 ✅ → v1.2 顏色統一
```
設備管理 Tab (全部使用 equipment 色系)
├── 供電設備 (equipment 色系，漸層：左上淡→右下濃)
│   ├── 發電機
│   ├── 行動電源站
│   └── UPS
├── 耗電設備 (equipment 色系，同上漸層)
│   ├── 冰箱/冷凍櫃
│   ├── 呼吸器
│   ├── 監視器
│   └── 其他插電設備
├── 非耗電設備 (equipment 色系，同上漸層)
│   ├── 手動設備
│   ├── 擔架/輪椅
│   └── 診斷工具 (聽診器等)
└── 手術包 (equipment 色系，同上漸層)
```

#### 0.2 韌性估算 Tab 重組 ✅ → v1.2 改進
```
韌性估算 Tab
├── 整體狀態 (大數字，不含瓶頸)
├── 瓶頸提示 (移至 Tab 內顯示)
├── 生命線卡片 (簡潔版，即時更新)
├── 韌性設備 (表格式，amber/orange/gray 色系)
│   ├── 表格欄位：編號、名稱、存量、韌性時數、狀態、操作
│   ├── 操作：檢查、編輯、刪除
│   └── 新增按鈕
└── [移除] 試劑監控列表
```

#### 0.3 即時統計卡片 ✅ → v1.2 新增
```
頂部統計卡片
├── 庫存物品數
├── 血庫庫存
├── 待確認設備
└── 可獨立運作 ← 新增 (顯示最短韌性時數，如 26.4h)
```

#### 0.4 庫存 Tab 試劑 Filter ✅ → v1.2 顏色修正
```
庫存 Tab Filters
├── 全部 (gray)
├── 藥品 (teal, selected: teal-600)
├── 耗材 (teal, selected: teal-600)
└── 試劑 (teal, selected: teal-600) ← 移除紫色，統一色系
```

#### 0.5 設備分類定義 (v1.2 更新)
```javascript
const EQUIPMENT_GROUPS = {
    'power_supply': {
        label: '供電設備',
        color: 'equipment',  // v1.2: 統一色系
        ids: ['UTIL-001', 'UTIL-002']  // v1.2.4: 移除重複的 EQ-010
    },
    'power_consuming': {
        label: '耗電設備',
        color: 'equipment',  // v1.2: 統一色系
        categories: ['儲存設備', '冷藏設備', '監測設備', '呼吸設備', '輸液設備', '手術設備', '麻醉設備']
    },
    'non_electric': {
        label: '非耗電設備',
        color: 'equipment',  // v1.2: 統一色系
        categories: ['搬運設備', '診斷設備', '急救設備']
    },
    'surgical_packs': {
        label: '手術包',
        color: 'equipment',
        filter: (eq) => eq.id.includes('-SURG-') || eq.id.startsWith('SURG-')
    },
    'resilience': {
        label: '韌性設備',
        color: 'amber',  // 韌性專用色系
        ids: ['RESP-001', 'RESP-002', 'EMER-EQ-006', 'UTIL-001', 'UTIL-002']  // v1.2.4: 移除 EQ-010
    }
};
```

#### 0.6 即時更新機制
```javascript
// 設備檢查後觸發
async submitCheckEquipment() {
    // ... existing code ...
    await this.loadEquipment();
    await this.loadResilienceStatus();  // v1.2: 重新載入韌性狀態
    await this.loadStats();
}
```

---

## 改進方案 (原 Phase 1-3 保留)

### Phase 1: 設備欄位多態化 (Backend)

#### 1.1 資料庫 Schema 修改
```sql
ALTER TABLE equipment ADD COLUMN metric_type TEXT DEFAULT 'power';
-- metric_type: 'power' | 'gas' | 'fuel' | 'battery' | 'temperature'

ALTER TABLE equipment ADD COLUMN metric_value REAL;
-- 統一數值欄位，取代 power_level

ALTER TABLE equipment ADD COLUMN metric_unit TEXT;
-- 'percent' | 'PSI' | 'celsius'
```

#### 1.2 設備類型對照表
```python
EQUIPMENT_METRICS = {
    'RESP-001': {'type': 'gas', 'unit': 'percent', 'label': '氣體存量'},
    'RESP-002': {'type': 'power', 'unit': 'percent', 'label': '運作狀態'},  # 氧氣濃縮機用電
    'EMER-EQ-006': {'type': 'gas', 'unit': 'percent', 'label': '氣體存量'},
    'UTIL-002': {'type': 'fuel', 'unit': 'percent', 'label': '燃油存量'},
    'UTIL-001': {'type': 'battery', 'unit': 'percent', 'label': '電量'},  # v1.2.4: 移除 EQ-010
    'EMER-EQ-001': {'type': 'battery', 'unit': 'percent', 'label': '電池電量'},
    'OTH-001': {'type': 'temperature', 'unit': 'celsius', 'label': '溫度'},
    'OTH-002': {'type': 'temperature', 'unit': 'celsius', 'label': '溫度'},
}
```

### Phase 2: 設備-韌性連動 (Backend)

#### 2.1 韌性計算整合
```python
def calculate_equipment_resilience(equipment_list):
    """
    從設備狀態計算韌性時數
    """
    resilience = {}

    # 氧氣: 合計所有氧氣設備
    o2_equipment = ['RESP-001', 'EMER-EQ-006']
    o2_hours = sum([
        calc_o2_hours(eq) for eq in equipment_list
        if eq['id'] in o2_equipment
    ])
    resilience['oxygen'] = o2_hours

    # 電力: 發電機 + 電源站
    power_equipment = ['UTIL-002', 'UTIL-001']  # v1.2.4: 移除 EQ-010
    power_hours = sum([
        calc_power_hours(eq) for eq in equipment_list
        if eq['id'] in power_equipment
    ])
    resilience['power'] = power_hours

    return resilience
```

#### 2.2 設備容量設定表
```python
EQUIPMENT_CAPACITY = {
    'RESP-001': {  # 氧氣鋼瓶
        'full_capacity': 6000,  # 6000L
        'burn_rate': 5,  # 5 L/min (高流量)
        'unit': 'liters'
    },
    'EMER-EQ-006': {  # 氧氣瓶 E size
        'full_capacity': 680,  # 680L
        'burn_rate': 5,
        'unit': 'liters'
    },
    'UTIL-002': {  # 發電機
        'full_capacity': 50,  # 50L 油箱
        'burn_rate': 2.5,  # 2.5 L/hr
        'unit': 'liters'
    },
    'UTIL-001': {  # 行動電源站
        'full_capacity': 2000,  # 2000Wh
        'burn_rate': 100,  # 100W 平均消耗
        'unit': 'Wh'
    }
}
```

### Phase 3: UI 改進 (Frontend)

#### 3.1 設備檢查 Modal 動態化
```javascript
// 根據設備類型顯示不同輸入欄位
function getMetricLabel(equipmentId) {
    const metrics = {
        'RESP-001': '氣體存量 (%)',
        'EMER-EQ-006': '氣體存量 (%)',
        'UTIL-002': '燃油存量 (%)',
        'UTIL-001': '電池電量 (%)',
        'OTH-001': '溫度 (°C)',
    };
    return metrics[equipmentId] || '狀態 (%)';
}
```

#### 3.2 設備表格顯示韌性影響
```html
<td class="text-center">
    <div x-text="eq.metric_value + '%'"></div>
    <div class="text-xs text-amber-600" x-show="eq.resilience_hours">
        ≈<span x-text="eq.resilience_hours"></span>h
    </div>
</td>
```

#### 3.3 庫存 Tab 新增「試劑」
```html
<button @click="inventoryFilter = 'reagent'"
        :class="inventoryFilter === 'reagent' ? 'bg-purple-500 text-white' : ''">
    試劑
</button>
```

---

## 韌性計算公式說明 (v1.2.2)

> 供站務人員參考，了解「可獨立運作 N 小時」的計算邏輯

### 資料來源 (v1.2.2 更新)

韌性計算現在使用「**設備管理**」表的數量，而非「庫存」表：

| 設備 ID | 設備名稱 | 單位容量 | 類型 | 備註 |
|---------|---------|---------|------|------|
| RESP-001 | 氧氣鋼瓶 (H型) | 6,900 L | OXYGEN | |
| EMER-EQ-006 | 氧氣瓶 (E size) | 680 L | OXYGEN | |
| RESP-002 | 氧氣濃縮機 | ∞ (需電力) | OXYGEN | 受限於發電機電力 |
| UTIL-002 | 發電機 | 50 L 油箱 | POWER | 含燃油計算 |
| UTIL-001 | 行動電源站 | 2048 Wh | POWER | 電池式，不耗油 |

### 基本公式

#### 氧氣韌性 (OXYGEN)

##### 鋼瓶供氧 (有限容量)
```
可用時數 = 總容量(L) ÷ (消耗速率 × 60)

其中：
- 總容量 = Σ (設備容量 × 設備數量 × 檢查%/100)
- 消耗速率 = 基準速率 × 等效人數
- 基準速率 = 10 L/min
```

**v1.2.6 個別追蹤** (PER_UNIT 模式)：
```
有效容量 = Σ (單位容量 × 個別充填%/100)

範例：RESP-001 氧氣鋼瓶 (每支 6,900L)
├─ H型1號: 100% → 6,900L
├─ H型2號: 100% → 6,900L
├─ H型3號:  80% → 5,520L
├─ H型4號:  50% → 3,450L
└─ H型5號:   0% →     0L
總有效容量 = 22,770L (平均 66%)
```

**範例**：
- 設備：RESP-001 氧氣鋼瓶 × 3 支，檢查狀態 80%
- 有效容量 = 6,900 × 3 × 0.8 = 16,560 L
- 等效人數 = 2 人
- 消耗速率 = 10 × 2 = 20 L/min
- **可用時數 = 16,560 ÷ (20 × 60) = 13.8 小時**

##### 氧氣濃縮機 + 電力依賴 (v1.2.6)

> 氧氣濃縮機本身無限供氧，但必須依賴電力運作

```
製造機氧氣時數 = MIN(∞, 電力時數)
               = 電力時數

依賴鏈：
  氧氣濃縮機 (RESP-002)
      ↓ depends on
  電力供應 (POWER-TOTAL)
      ↓
  實際時數 = 電源站時數 + 發電機時數
```

**計算範例**：
- 氧氣濃縮機：2 台 (5L/min 持續供氧)
- 本身容量：∞ (無限)
- 電力時數：75.6h (電源站 2.3h + 發電機 73.3h)
- **製造機有效時數 = MIN(∞, 75.6) = 75.6h**

**UI 顯示**：
```
氧氣濃縮機        ∞h (本身)  →  75.6h (受限電力)
                 │
                 └── ⚠️ 受限於發電機電力：當油料耗盡時，氧氣濃縮機將停止運作
```

**綜合氧氣時數**：
```
總氧氣時數 = MAX(鋼瓶時數, 製造機有效時數)
           = MAX(25.7h, 75.6h)
           = 75.6h (製造機為主，電力耗盡後切換鋼瓶)

實際運作順序：
1. 優先使用氧氣濃縮機 (耗電但無限供氧)
2. 電力耗盡後，切換至備用鋼瓶
3. 鋼瓶耗盡 = 氧氣供應中斷
```

#### 電力韌性 (POWER) - v1.2.5 重構

```
總負載(W) = Σ(設備.power_watts)

電源站時數 = capacity_wh × (power_level%) ÷ 總負載
發電機時數 = (油箱 + 備用油料) ÷ fuel_rate_lph
總時數 = 電源站時數 + 發電機時數 (依序使用)
```

**範例** (實際資料):
- 耗電設備：生理監視器(50W) + 呼吸器(150W) + 冰箱×2(300W) + 抽吸機(100W)...
- **總負載 = 900W**

- 電源站：行動電源站 2048Wh @100%
- **電源站時數 = 2048 ÷ 900 = 2.3h**

- 發電機：油箱 50L @100% + 備用油桶 3×20L = 110L
- 油耗率：1.5 L/hr
- **發電機時數 = 110 ÷ 1.5 = 73.3h**

- **總時數 = 2.3 + 73.3 = 75.6h (3.2天)**

### 狀態判定

```
狀態 = 可用時數 ÷ 目標時數 (孤立天數 × 24)

- SAFE (綠色): ≥ 120%
- WARNING (黃色): 100% ~ 120%
- CRITICAL (紅色): < 100%
```

**範例** (目標 3 天 = 72 小時)：
- 可用 80 小時 → 80/72 = 111% → WARNING
- 可用 90 小時 → 90/72 = 125% → SAFE
- 可用 60 小時 → 60/72 = 83% → CRITICAL

### 最弱環節原則

> **可獨立運作時數 = MIN(氧氣時數, 電力時數)**

如果氧氣可撐 26 小時，電力可撐 33 小時，則系統顯示「可獨立運作 26 小時」，瓶頸為氧氣。

### 改變設定的影響

| 改變項目 | 對可用時數的影響 |
|---------|-----------------|
| 孤立天數 | 不變（影響狀態顏色） |
| 插管人數 | 氧氣時數 ÷ N（人數越多，時數越少） |
| 情境選擇 | 依選擇的消耗速率重新計算 |

### 人數為零的情境 (v1.2.3)

當 `population_count = 0` 時：
- 氧氣消耗率 = 0 L/min
- 氧氣時數 = ∞（無限大）
- 適用情境：無插管病患，但仍需追蹤設備狀態

### 等效人數換算 (v1.2.4)

> 支援小數輸入，換算不同氧氣供應方式的需求

| 供氧方式 | 流量 | 等效人數 |
|---------|------|---------|
| 插管 (Ventilator) | 10 L/min | 1.0 |
| 面罩 (Mask) | ~6 L/min | 0.6 |
| 鼻導管 (Nasal Cannula) | ~3 L/min | 0.3 |

**範例**：
- 1 位插管 + 2 位面罩 = 1.0 + 0.6 + 0.6 = **2.2 等效人**
- 純鼻導管供氧 3 人 = 0.3 × 3 = **0.9 等效人**

UI 輸入框現支援 `step="0.1"` 小數輸入。

---

## 優先順序

| Priority | Task | Impact |
|----------|------|--------|
| P0 | 設備 Modal 欄位名稱修正 (氧氣瓶顯示「氣體存量」) | UX 修正 |
| P1 | 庫存 Tab 新增「試劑」filter | 分類清晰 |
| P2 | 設備-韌性計算連動 | 數據準確性 |
| P3 | 設備容量設定 API | 進階功能 |

---

## 相關文件
- [IRS_RESILIENCE_FRAMEWORK.md](./IRS_RESILIENCE_FRAMEWORK.md)
- [Database Schema](../database/migrations/)

---

*Created: 2025-12-15*
*Updated: 2025-12-17*
*Author: Claude Code*
