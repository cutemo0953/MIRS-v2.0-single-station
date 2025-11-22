# 🏗️ 部署架構與離線同步方案

## 📋 目錄
1. [當前架構分析](#當前架構分析)
2. [實戰場景需求](#實戰場景需求)
3. [改進方案](#改進方案)
4. [實作步驟](#實作步驟)
5. [操作流程](#操作流程)

---

## 當前架構分析

### ✅ 現有設計

**架構模式**：統一資料庫 + station_id 區分

```
┌─────────────────────────────────┐
│      中央資料庫                  │
│  ┌────────────────────────┐     │
│  │ SQLite / PostgreSQL    │     │
│  │                        │     │
│  │ Items (所有站點共用)   │     │
│  │ Blood (station_id 區分) │    │
│  │ Equipment (station_id)  │    │
│  └────────────────────────┘     │
└─────────────────────────────────┘
         ↑   ↑   ↑   ↑
         │   │   │   │
    各站點通過網路訪問
    (瀏覽器/終端機)
```

**適用場景**：
- ✅ 網路穩定的醫院環境
- ✅ 中央需要即時監控
- ✅ 站點間頻繁調撥

**限制**：
- ❌ 依賴持續網路連接
- ❌ 斷網即無法運作
- ❌ 無離線模式

---

## 實戰場景需求

### 場景 A：正常運作（網路穩定）

```
中央指揮中心（衛福部/地方衛生局）
         ↓ 即時查詢
   ┌──────────────────┐
   │  統一資料庫      │
   │  - TC-01: 物資   │
   │  - TC-02: 血袋   │
   │  - TC-03: 設備   │
   └──────────────────┘
         ↑
    所有站點連接
```

**需求**：
- 中央可查詢所有站點狀況
- 即時監控物資庫存
- 快速協調調撥

**當前架構**：✅ 完全符合

---

### 場景 B：部分斷網（災害初期）

```
Day 1 10:00 - 地震發生
    中央 ← 網路正常 → TC-01 ✓
                       TC-02 ✓
                       TC-03 ✗ (基地台倒塌)

TC-03 需求：
1. 離線繼續記錄物資消耗
2. 記錄傷患處置
3. 記錄血袋使用
4. 等待網路恢復後同步
```

**當前架構**：❌ 不支援
- 無本地資料庫
- 無離線模式
- 無同步機制

---

### 場景 C：完全斷網 + 物理傳輸（戰時）

```
戰況惡化，所有通訊中斷

Day 1-3:
  各站點獨立運作
  記錄所有變更

Day 4:
  ┌──────┐
  │ USB  │ ← TC-01 備份
  └──────┘
     ↓ 人力/無人機
  中央指揮中心

Day 5:
  中央匯入 TC-01 資料
  了解前線狀況
  規劃物資支援
```

**當前架構檢查**：
- ✅ 備份功能：`GET /api/emergency/download-all`
- ❌ 匯入功能：**無**
- ❌ 衝突處理：**無**
- ❌ 變更合併：**無**

---

## 改進方案

### 🎯 方案一：混合架構（推薦）

#### 設計理念
**在線優先 + 離線備援 + 自動同步**

#### 架構圖

```
┌─────────────────────────────────────────┐
│          中央指揮中心                    │
│  ┌────────────────────────────┐         │
│  │  主資料庫 (PostgreSQL)     │         │
│  │  - 彙整所有站點資料        │         │
│  │  - 提供中央查詢介面        │         │
│  └────────────────────────────┘         │
│  ┌────────────────────────────┐         │
│  │  同步服務 API              │         │
│  │  - 接收站點上傳            │         │
│  │  - 提供變更下載            │         │
│  │  - 處理衝突                │         │
│  └────────────────────────────┘         │
└─────────────────────────────────────────┘
              ↕
         網路同步（雙向）
              ↕
┌─────────────────────────────────────────┐
│       前線站點 TC-01                    │
│                                         │
│  ┌───────────────┐  ┌────────────────┐ │
│  │ 本地資料庫     │←→│ 同步模組       │ │
│  │ (SQLite)      │  │                │ │
│  │               │  │ 狀態檢測:      │ │
│  │ - 即時操作    │  │ • 在線模式     │ │
│  │ - 離線快取    │  │ • 離線模式     │ │
│  │ - 待同步佇列  │  │ • 同步中       │ │
│  └───────────────┘  └────────────────┘ │
│                                         │
│  前端介面（瀏覽器）                     │
│  └→ 顯示當前模式（在線/離線）           │
└─────────────────────────────────────────┘
```

#### 運作模式

**1. 在線模式（網路正常）**
```
使用者操作 → 本地資料庫 → 立即同步到中央
                           ↓
                     成功：標記已同步
                     失敗：加入待同步佇列
```

**2. 離線模式（網路中斷）**
```
使用者操作 → 本地資料庫 → 加入待同步佇列
                           ↓
                     顯示「離線模式」標記
                     所有操作正常運作
```

**3. 恢復同步（網路恢復）**
```
偵測網路恢復
    ↓
讀取待同步佇列
    ↓
批次上傳變更到中央
    ↓
處理衝突（如有）
    ↓
標記同步完成
```

---

### 🗄️ 資料庫設計

#### 新增同步追蹤表

```sql
-- 同步佇列（記錄離線期間的所有變更）
CREATE TABLE sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,           -- INSERT/UPDATE/DELETE
    table_name TEXT NOT NULL,          -- 哪個表
    record_key TEXT NOT NULL,          -- 記錄主鍵
    data_json TEXT NOT NULL,           -- 完整資料（JSON格式）
    station_id TEXT NOT NULL,          -- 站點ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMP,               -- 同步時間
    sync_status TEXT DEFAULT 'PENDING', -- PENDING/SYNCED/CONFLICT/FAILED
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    CHECK(operation IN ('INSERT', 'UPDATE', 'DELETE')),
    CHECK(sync_status IN ('PENDING', 'SYNCED', 'CONFLICT', 'FAILED'))
);

-- 索引
CREATE INDEX idx_sync_queue_status ON sync_queue(sync_status, created_at);
CREATE INDEX idx_sync_queue_station ON sync_queue(station_id);

-- 同步歷史（記錄每次同步結果）
CREATE TABLE sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    sync_type TEXT NOT NULL,           -- UPLOAD/DOWNLOAD/MERGE/IMPORT
    direction TEXT NOT NULL,           -- TO_CENTRAL/FROM_CENTRAL
    records_sent INTEGER DEFAULT 0,
    records_received INTEGER DEFAULT 0,
    conflicts_count INTEGER DEFAULT 0,
    success BOOLEAN DEFAULT TRUE,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds INTEGER,
    notes TEXT,
    CHECK(sync_type IN ('UPLOAD', 'DOWNLOAD', 'MERGE', 'IMPORT')),
    CHECK(direction IN ('TO_CENTRAL', 'FROM_CENTRAL', 'BIDIRECTIONAL'))
);

-- 衝突記錄（需要人工處理的衝突）
CREATE TABLE sync_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_key TEXT NOT NULL,
    local_data TEXT NOT NULL,          -- 本地版本（JSON）
    central_data TEXT NOT NULL,        -- 中央版本（JSON）
    conflict_type TEXT NOT NULL,       -- UPDATE_CONFLICT/DELETE_CONFLICT
    station_id TEXT NOT NULL,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    resolution TEXT,                   -- USE_LOCAL/USE_CENTRAL/MERGE/MANUAL
    resolved_by TEXT,
    CHECK(conflict_type IN ('UPDATE_CONFLICT', 'DELETE_CONFLICT')),
    CHECK(resolution IN ('USE_LOCAL', 'USE_CENTRAL', 'MERGE', 'MANUAL'))
);
```

---

### 📡 API 端點設計

#### 1. 同步狀態查詢

```http
GET /api/sync/status?station_id=TC-01

Response:
{
    "station_id": "TC-01",
    "mode": "ONLINE",  // ONLINE/OFFLINE/SYNCING
    "last_sync": "2025-11-12T14:30:00",
    "pending_changes": 0,
    "conflicts": 0,
    "network_available": true
}
```

#### 2. 上傳變更到中央

```http
POST /api/sync/upload
Content-Type: application/json

{
    "station_id": "TC-01",
    "changes": [
        {
            "operation": "INSERT",
            "table": "blood_events",
            "data": {
                "event_type": "RECEIVE",
                "blood_type": "O+",
                "quantity": 20,
                "station_id": "TC-01",
                "timestamp": "2025-11-12T10:30:00"
            },
            "timestamp": "2025-11-12T10:30:00"
        },
        {
            "operation": "UPDATE",
            "table": "blood_inventory",
            "key": {"blood_type": "O+", "station_id": "TC-01"},
            "data": {
                "quantity": 70,
                "last_updated": "2025-11-12T10:30:00"
            },
            "timestamp": "2025-11-12T10:30:00"
        }
    ]
}

Response:
{
    "success": true,
    "processed": 2,
    "conflicts": 0,
    "sync_id": "SYNC-20251112-001"
}
```

#### 3. 下載中央變更

```http
GET /api/sync/download?station_id=TC-01&after=2025-11-12T08:00:00

Response:
{
    "station_id": "TC-01",
    "changes": [
        {
            "operation": "INSERT",
            "table": "items",
            "data": {...},
            "timestamp": "2025-11-12T12:00:00"
        }
    ],
    "count": 1,
    "last_timestamp": "2025-11-12T12:00:00"
}
```

#### 4. 匯入備份檔案（USB傳輸）

```http
POST /api/sync/import
Content-Type: multipart/form-data

backup_file: (binary .zip file)
station_id: TC-01
merge_strategy: AUTO  // AUTO/MANUAL
override_conflicts: false

Response:
{
    "success": true,
    "import_id": "IMPORT-20251112-001",
    "summary": {
        "items_imported": 150,
        "blood_events_imported": 45,
        "equipment_checks_imported": 12,
        "conflicts_detected": 3,
        "conflicts_auto_resolved": 2,
        "conflicts_need_manual": 1
    },
    "conflicts": [
        {
            "type": "UPDATE_CONFLICT",
            "table": "blood_inventory",
            "record": "O+, TC-01",
            "local_value": 50,
            "imported_value": 55,
            "suggested_resolution": "USE_LATEST"
        }
    ]
}
```

---

### 🔀 衝突處理策略

#### 自動處理規則

**1. 時間戳優先**
```
本地: quantity=50, updated_at="2025-11-12T10:00:00"
中央: quantity=55, updated_at="2025-11-12T11:00:00"

解決: 使用較新的版本（中央 55）
```

**2. 加法合併**
```
本地離線期間: +20U (入庫)
中央同期間: +15U (其他站調入)

解決: 累加變更 (50 + 20 + 15 = 85U)
```

**3. 無衝突操作**
```
本地: INSERT 新記錄
中央: 無此記錄

解決: 直接插入
```

#### 需要人工處理

**1. 刪除衝突**
```
本地: DELETE (認為已用完)
中央: UPDATE quantity=10 (其他站調入)

需要人工決定: 保留或刪除？
```

**2. 數據不一致**
```
本地: 血袋 O+ 50U
中央: 血袋 O+ 30U
離線期間無明確事件記錄

需要人工確認實際庫存
```

---

## 實作步驟

### Phase 1: 基礎離線支援

**目標**：單一站點可離線運作

**實作項目**：
1. [ ] 前端新增離線偵測
2. [ ] 建立 sync_queue 表
3. [ ] 攔截所有資料庫操作，記錄到佇列
4. [ ] UI 顯示在線/離線狀態

**前端實作**：
```javascript
// 偵測網路狀態
window.addEventListener('online', () => {
    app.networkStatus = 'online';
    app.syncPendingChanges();
});

window.addEventListener('offline', () => {
    app.networkStatus = 'offline';
    app.toast('已切換到離線模式', 'warning');
});
```

---

### Phase 2: 同步機制

**目標**：網路恢復後自動同步

**實作項目**：
1. [ ] 實作 `/api/sync/upload` 端點
2. [ ] 實作 `/api/sync/download` 端點
3. [ ] 背景定時同步
4. [ ] 同步進度顯示

---

### Phase 3: 備份匯入

**目標**：支援 USB/物理介質傳輸

**實作項目**：
1. [ ] 實作 `/api/sync/import` 端點
2. [ ] 備份檔案格式標準化
3. [ ] 衝突偵測與處理
4. [ ] 匯入結果報表

---

### Phase 4: 中央管理介面

**目標**：中央可查看所有站點

**實作項目**：
1. [ ] 中央儀表板（所有站點總覽）
2. [ ] 物資總量統計
3. [ ] 站點在線狀態監控
4. [ ] 同步狀態追蹤

---

## 操作流程

### 流程 1: 正常同步（網路穩定）

```
1. 使用者在 TC-01 操作
   ├→ 血袋入庫 20U O+
   └→ 物資消耗 10 件手術刀

2. 系統處理
   ├→ 寫入本地資料庫
   ├→ 偵測網路狀態（在線）
   └→ 立即同步到中央

3. 中央資料庫更新
   ├→ TC-01 血袋 O+ +20U
   └→ TC-01 手術刀 -10 件

4. 其他站點查詢
   └→ 可立即看到 TC-01 最新狀態
```

---

### 流程 2: 離線運作 + 恢復同步

```
Day 1 10:00 - 地震，TC-01 斷網

1. 系統偵測
   ├→ 網路中斷
   ├→ 切換到離線模式
   └→ 顯示「⚠️ 離線模式」標記

2. 離線期間操作（10:00 - 18:00）
   ├→ 血袋入庫 50U
   ├→ 處置 15 位傷患
   ├→ 物資消耗 200 件
   └→ 所有操作記錄到 sync_queue

3. Day 1 18:00 - 網路恢復

4. 自動同步
   ├→ 偵測網路恢復
   ├→ 讀取 sync_queue（200 筆變更）
   ├→ 批次上傳到中央
   ├→ 中央檢查衝突
   ├→ 自動處理（195 筆）
   ├→ 標記待人工處理（5 筆）
   └→ 完成同步

5. 通知中央
   └→ "TC-01 已恢復連線，同步 200 筆變更"
```

---

### 流程 3: 物理傳輸（戰時）

```
戰況惡化，所有通訊中斷

Day 1-5: TC-01 獨立運作
   ├→ 記錄所有變更
   └→ 累積 500 筆未同步資料

Day 6 08:00 - 產生備份
   └→ POST /api/emergency/download-all
       └→ 下載 TC-01_20251112.zip

Day 6 10:00 - 物理傳輸
   ┌────────┐
   │  USB   │ ← 插入 TC-01 電腦
   └────────┘
       ↓ 複製備份檔
   ┌────────┐
   │ 無人機  │ ← 掛載 USB
   └────────┘
       ↓ 飛行 2 小時
   中央指揮中心

Day 6 14:00 - 中央匯入
   1. 上傳備份檔案
      └→ POST /api/sync/import

   2. 系統處理
      ├→ 解壓縮 ZIP
      ├→ 讀取 SQLite 資料庫
      ├→ 偵測衝突（10 筆）
      ├→ 自動處理（8 筆）
      └→ 標記人工審核（2 筆）

   3. 完成匯入
      ├→ 中央看到 TC-01 狀況
      ├→ 規劃物資支援
      └→ 派遣補給

Day 6 16:00 - 產生回傳資料
   1. 中央準備支援資料
      ├→ 物資調撥計畫
      ├→ 中央指令
      └→ 打包成 CENTRAL_TO_TC01.zip

   2. 物理傳輸回 TC-01
      └→ 無人機回程

Day 6 20:00 - TC-01 匯入中央指令
   └→ 收到物資支援通知
```

---

## 技術挑戰與解決

### 挑戰 1: 時間同步

**問題**：各站點時鐘可能不同步

**解決**：
- 使用 UTC 時間
- 記錄事件順序號（sequence number）
- 衝突時以 sequence 為準

---

### 挑戰 2: 資料完整性

**問題**：離線期間可能關機/斷電

**解決**：
- SQLite WAL 模式（防止損毀）
- 定期備份到多個 USB
- 資料驗證機制

---

### 挑戰 3: 頻寬限制

**問題**：戰時網路頻寬極低

**解決**：
- 差異同步（只傳變更）
- 資料壓縮
- 批次上傳
- 優先級佇列（重要資料先傳）

---

## 最佳實踐建議

### 1. 定期備份
```
每日自動備份：
- 23:00 自動產生備份檔
- 儲存到本地 + USB + 雲端
- 保留最近 7 天
```

### 2. 冗餘傳輸
```
重要資料多重備份：
- USB x 3（分別由不同人員攜帶）
- 無人機 x 2（備用機制）
- 衛星電話（緊急文字摘要）
```

### 3. 訓練演練
```
定期演練斷網場景：
- 模擬網路中斷
- 測試離線運作
- 驗證同步流程
- 檢討改進
```

---

## 總結

### 當前架構評估

**優點**：
- ✅ 簡潔高效（網路正常時）
- ✅ 中央可即時監控
- ✅ 站點間調撥方便

**限制**：
- ❌ 依賴持續網路
- ❌ 無離線模式
- ❌ 無同步機制

### 建議改進優先級

**P0（緊急）**：
1. 新增備份匯入功能
2. 建立衝突處理機制

**P1（重要）**：
3. 實作離線模式
4. 建立同步佇列

**P2（進階）**：
5. 自動同步機制
6. 中央管理介面

### 最終目標

**建立韌性系統**：
- 在線時：即時協同
- 斷網時：獨立運作
- 恢復時：自動同步
- 戰時：物理傳輸

---

**版本**: v1.0
**建立日期**: 2025-11-12
**最後更新**: 2025-11-12
