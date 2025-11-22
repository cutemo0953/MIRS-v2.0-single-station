# 🔄 站間調撥功能開發計畫

## 📋 概述

**目的**: 實作完整的站點間資源調撥系統，支援緊急支援與資源平衡

**適用場景**:
- 🚨 緊急支援：前線站點資源短缺，需要其他站點快速支援
- ⚖️ 資源平衡：調整各站點庫存分配，避免資源閒置或短缺
- 🔄 定期調撥：根據戰況變化進行計畫性資源調度

**與站點合併的區別**:
- **調撥**: 臨時性資源轉移，兩站點繼續獨立運作
- **合併**: 永久性整合，兩站合併為一站，資料完全整合

---

## ✅ 已完成功能

### 1. 血袋站點轉移
**狀態**: ✅ 完成（前端 + 後端）

**後端 API**:
- `POST /api/blood/transfer` - 血袋站點轉移

**前端 UI**:
- 位置: Index.html 血袋分頁 → 「血袋站點轉移（調撥）」區塊
- 功能:
  - 來源/目標站點輸入
  - 血型選擇
  - 數量輸入
  - 操作人員與備註
- 驗證:
  - 站點不能相同
  - 來源站點庫存檢查
  - 自動記錄雙向事件日誌

---

## 🚧 待開發功能

### 2. 物資調撥 (Items Transfer)

**後端 API** - 需新增:
```python
POST /api/items/transfer
{
  "itemCode": "SURG-001",
  "quantity": 50,
  "sourceStationId": "TC-01",
  "targetStationId": "TC-02",
  "operator": "張醫師",
  "remarks": "緊急支援手術耗材"
}

Response:
{
  "success": true,
  "message": "成功轉移 50 件 外科縫合針",
  "source_station": "TC-01",
  "target_station": "TC-02",
  "source_remaining": 100,  // 來源站剩餘數量
  "target_new_total": 150   // 目標站新總量
}
```

**資料庫變更**:
- `transactions` 表新增事件類型: `TRANSFER_OUT`, `TRANSFER_IN`
- 記錄來源/目標站點資訊

**前端 UI**:
- 位置建議: 物品查詢分頁新增「站點調撥」按鈕
- 或新增獨立「調撥管理」分頁
- 功能:
  - 物品代碼選擇（下拉選單，顯示當前庫存）
  - 數量輸入（最大值 = 來源站庫存）
  - 來源/目標站點
  - 調撥原因必填

---

### 3. 設備調撥 (Equipment Transfer)

**後端 API** - 需新增:
```python
POST /api/equipment/transfer
{
  "equipmentId": "power-1",
  "sourceStationId": "TC-01",
  "targetStationId": "TC-02",
  "quantity": 1,  // 設備通常為整數件
  "operator": "王工程師",
  "remarks": "支援電力設備"
}

Response:
{
  "success": true,
  "message": "成功轉移 1 台 行動電源站",
  "equipment_id": "power-1",
  "source_station": "TC-01",
  "target_station": "TC-02"
}
```

**資料庫變更**:
- `equipment` 表考慮是否需要 `station_id` 欄位（目前可能沒有）
- 或建立 `equipment_assignment` 關聯表
- 記錄設備歷史位置

**前端 UI**:
- 位置: 設備管理分頁新增「調撥」按鈕
- 功能:
  - 設備選擇（顯示當前所在站點）
  - 目標站點選擇
  - 設備數量（某些設備可能有多台）
  - 調撥說明

---

### 4. 調撥管理統一介面

**建議**: 創建獨立的「調撥管理」分頁

**功能需求**:

#### 4.1 快速調撥面板
```
┌─────────────────────────────────────┐
│  🔄 快速調撥                        │
├─────────────────────────────────────┤
│  資源類型: [物資 ▼]                 │
│  來源站點: [TC-01 ▼]                │
│  目標站點: [TC-02 ▼]                │
│  資源選擇: [SURG-001 - 外科縫合針 ▼]│
│  數量:     [50] / 150 可用          │
│  操作人員: [張醫師]                 │
│  調撥原因: [緊急支援手術]           │
│                                     │
│       [執行調撥]  [重置]            │
└─────────────────────────────────────┘
```

#### 4.2 調撥歷史記錄
```
時間              | 類型 | 資源      | 數量 | 來源   | 目標   | 操作人
2025-11-12 14:30 | 物資 | 外科縫合針 | 50   | TC-01 | TC-02 | 張醫師
2025-11-12 13:15 | 血袋 | O+        | 10U  | TC-02 | TC-01 | 李護理師
2025-11-12 10:20 | 設備 | 行動電源站 | 1台  | TC-01 | TC-03 | 王工程師
```

**查詢功能**:
- 日期範圍篩選
- 站點篩選（來源/目標）
- 資源類型篩選
- 操作人員篩選
- 匯出 CSV

#### 4.3 站點資源總覽
顯示各站點的即時庫存狀況，方便決策調撥：

```
站點    | 關鍵物資 | 血袋總量 | 設備數量 | 警報數
TC-01  | 15 項    | 85 U    | 12 台   | 2 ⚠️
TC-02  | 18 項    | 120 U   | 10 台   | 0 ✅
TC-03  | 12 項    | 45 U    | 8 台    | 5 🚨
```

---

## 🔐 權限控制（未來考慮）

**建議**:
- 一般人員: 可查看調撥記錄，不能執行
- 物資管理員: 可執行物資調撥
- 護理長/醫師: 可執行血袋調撥
- 設備管理員: 可執行設備調撥
- 站長/指揮官: 可執行所有調撥

---

## 📊 資料庫架構建議

### 新增統一的調撥記錄表

```sql
CREATE TABLE transfer_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_number TEXT UNIQUE NOT NULL,  -- 調撥單號: TRF-YYMMDD-SEQ
    transfer_type TEXT NOT NULL,           -- ITEM/BLOOD/EQUIPMENT
    resource_id TEXT NOT NULL,             -- 資源ID（物品代碼/血型/設備ID）
    resource_name TEXT NOT NULL,           -- 資源名稱
    quantity INTEGER NOT NULL,             -- 數量
    unit TEXT,                             -- 單位
    source_station_id TEXT NOT NULL,       -- 來源站點
    target_station_id TEXT NOT NULL,       -- 目標站點
    operator TEXT NOT NULL,                -- 操作人員
    remarks TEXT,                          -- 備註
    status TEXT DEFAULT 'COMPLETED',       -- PENDING/COMPLETED/CANCELLED
    transferred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK(transfer_type IN ('ITEM', 'BLOOD', 'EQUIPMENT')),
    CHECK(status IN ('PENDING', 'COMPLETED', 'CANCELLED'))
);

CREATE INDEX idx_transfer_stations ON transfer_history(source_station_id, target_station_id);
CREATE INDEX idx_transfer_date ON transfer_history(transferred_at DESC);
CREATE INDEX idx_transfer_type ON transfer_history(transfer_type);
```

**優點**:
- 統一管理所有類型的調撥記錄
- 便於查詢與統計
- 支援未來擴展（例如：審批流程）

---

## 🎯 開發優先順序建議

### Phase 1: 基礎調撥（本階段）
- ✅ 血袋調撥（已完成）
- 🔄 物資調撥（下一步）
- 🔄 設備調撥

### Phase 2: 管理介面
- 統一調撥面板
- 調撥歷史查詢
- 站點資源總覽

### Phase 3: 進階功能
- 調撥審批流程
- 批次調撥（一次調撥多項資源）
- 自動化建議（AI 推薦調撥方案）
- 權限管理

---

## 🧪 測試場景

### 場景 1: 緊急血袋支援
```
情境: TC-03 站發生大量傷患，O+ 血袋用盡
操作:
1. TC-03 請求支援
2. TC-01 確認庫存充足（O+ 50U）
3. 執行調撥：TC-01 → TC-03, O+, 20U
4. 系統記錄雙向事件
5. 更新兩站點庫存
6. 發送通知給相關人員
```

### 場景 2: 物資平衡調撥
```
情境: 定期檢查發現 TC-01 手術耗材過量，TC-02 短缺
操作:
1. 查看站點資源總覽
2. 選擇需要調撥的物資（外科縫合針）
3. 執行調撥：TC-01 → TC-02, 100 件
4. 記錄調撥原因：「資源平衡調整」
5. 更新庫存並通知
```

### 場景 3: 設備支援
```
情境: TC-02 停電，需要行動電源
操作:
1. 緊急請求設備支援
2. 查詢哪個站點有可用行動電源
3. TC-01 有 2 台，調撥 1 台給 TC-02
4. 記錄設備轉移歷史
5. 更新設備所在位置
```

---

## 📝 API 端點總覽

| 端點 | 方法 | 狀態 | 說明 |
|------|------|------|------|
| `/api/blood/transfer` | POST | ✅ 完成 | 血袋站點轉移 |
| `/api/items/transfer` | POST | ❌ 待開發 | 物資站點轉移 |
| `/api/equipment/transfer` | POST | ❌ 待開發 | 設備站點轉移 |
| `/api/transfer/history` | GET | ❌ 待開發 | 查詢調撥歷史 |
| `/api/transfer/stations-overview` | GET | ❌ 待開發 | 站點資源總覽 |
| `/api/transfer/export` | GET | ❌ 待開發 | 匯出調撥記錄 |

---

## 🔍 與站點合併的對照

| 功能 | 調撥 (Transfer) | 合併 (Merge) |
|------|----------------|--------------|
| **目的** | 臨時資源轉移 | 永久站點整合 |
| **站點狀態** | 兩站獨立運作 | 合併為一站 |
| **資料處理** | 簡單加減 | 複雜整合 |
| **可逆性** | 可反向調撥 | 不可逆 |
| **審批** | 快速執行 | 需要審批 |
| **記錄** | 調撥記錄 | 合併歷史 |
| **使用頻率** | 高（日常） | 低（特殊情況） |

---

## 💡 實作建議

1. **先完成後端 API**，確保資料邏輯正確
2. **再實作前端 UI**，提供友好操作介面
3. **分階段部署**，先上線基礎功能，再逐步完善
4. **充分測試**，特別是庫存數量的正確性
5. **日誌記錄**，所有調撥操作都要有完整日誌

---

**版本**: v1.0
**建立日期**: 2025-11-12
**最後更新**: 2025-11-12
