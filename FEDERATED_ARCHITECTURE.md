# 🏥 聯邦式三層架構設計

## 📋 架構概述

### 設計原則
本架構針對戰時/災害情境下的醫療物資管理，考量以下實際需求：
- **網路受限**: 僅大站或醫院行政單位可透過軍警管道聯網
- **層級管理**: 中央指揮 → 醫院 → 醫療站三層架構
- **高頻內部協作**: 醫院內站點間頻繁同步與物資請求
- **複雜跨院請求**: 醫院間物資請求需審批流程
- **戰場適應性**: 支援完全離線運作與實體資料轉移

---

## 🏗️ 三層架構設計

```
┌─────────────────────────────────────────────────────────────────┐
│                     🏛️ 中央指揮層                                │
│              (衛福部 / 地方衛生局 / 戰區指揮部)                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Central Command Database (Master)                        │  │
│  │  • 全國/戰區總覽                                           │  │
│  │  • 接收各醫院狀態報告                                      │  │
│  │  • 審批跨醫院物資調撥                                      │  │
│  │  • 戰略資源調配決策                                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         ↕ (軍警專線/衛星通訊 - 定期狀態報告)
┌─────────────────────────────────────────────────────────────────┐
│                     🏥 醫院層 (Hospital Level)                   │
│              一個醫院統籌 5-40 個醫療站                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Hospital Aggregate Database                              │  │
│  │  • 整合所屬所有站點資料                                    │  │
│  │  • 醫院內物資調撥協調                                      │  │
│  │  • 向中央報告彙總狀態                                      │  │
│  │  • 處理跨醫院請求                                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  部署位置: 醫院行政核心單位 (有聯網權限)                         │
└─────────────────────────────────────────────────────────────────┘
         ↕ (院內網路/實體轉移 - 高頻同步)
┌─────────────────────────────────────────────────────────────────┐
│                   ⚕️ 醫療站層 (Station Level)                   │
│                      每個醫院 5-40 個站點                         │
│                                                                  │
│  ┌─────────────────────┐      ┌─────────────────────┐          │
│  │   🏥 大站 (Large)    │      │   🚑 小站 (Small)    │          │
│  │  • 可執行手術        │      │  • 簡易換藥止血      │          │
│  │  • 完整設備與人力     │      │  • 基礎物資         │          │
│  │  • 可能有聯網權限     │      │  • 通常無網路       │          │
│  │  ┌───────────────┐  │      │  ┌───────────────┐  │          │
│  │  │ Local DB      │  │      │  │ Local DB      │  │          │
│  │  │ (獨立運作)     │  │      │  │ (獨立運作)     │  │          │
│  │  └───────────────┘  │      │  └───────────────┘  │          │
│  └─────────────────────┘      └─────────────────────┘          │
│          ↕ (網路/USB)                 ↕ (USB/人力)              │
│  ┌─────────────────────────────────────────────────────┐       │
│  │              醫院彙總資料庫                          │       │
│  └─────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🗄️ 資料庫部署策略

### 方案：混合式聯邦架構

#### 1. 站點層資料庫 (Station-Level DB)
```
位置: 每個醫療站獨立運作
技術: SQLite (輕量、離線優先)
功能:
  ✓ 完全離線運作
  ✓ 本站物資、血袋、設備、手術記錄
  ✓ 生成同步封包 (sync packages)
  ✓ 匯入其他站點資料
```

**資料範圍:**
- 站點ID: `TC-01`, `TC-02`, ..., `TC-40`
- 醫院ID: `HOSP-001`
- 僅管理本站資源與記錄

#### 2. 醫院層資料庫 (Hospital-Level DB)
```
位置: 醫院行政核心單位 (有聯網權限)
技術: SQLite 或 PostgreSQL (支援更大資料量)
功能:
  ✓ 彙總所屬 5-40 個站點資料
  ✓ 醫院內物資調撥協調中心
  ✓ 接收站點同步封包
  ✓ 向中央報告彙總狀態
  ✓ 處理跨醫院請求審批
```

**資料範圍:**
- 醫院ID: `HOSP-001`
- 站點: `TC-01` ~ `TC-40`
- 包含所有站點的彙總資料

#### 3. 中央層資料庫 (Central-Level DB)
```
位置: 衛福部/地方衛生局/戰區指揮部
技術: PostgreSQL (高可用性、大規模)
功能:
  ✓ 全國/戰區總覽
  ✓ 接收各醫院狀態報告
  ✓ 審批跨醫院物資調撥
  ✓ 戰略資源調配決策
  ✓ 長期數據分析與統計
```

**資料範圍:**
- 所有醫院: `HOSP-001`, `HOSP-002`, ...
- 彙總資料，不包含每個站點的詳細記錄
- 接收醫院層的定期報告

---

## 🔄 同步機制設計

### 1. 院內同步 (Intra-Hospital Sync)

#### 頻率: 高頻 (每小時或更頻繁)

#### 場景 A: 大站 → 醫院彙總 (有網路)
```
流程:
1. 大站 TC-01 產生增量同步封包 (delta sync)
2. 透過院內網路 POST /api/hospital/sync/upload
3. 醫院彙總資料庫合併資料
4. 返回確認與其他站點更新

同步內容:
  • 物資異動記錄
  • 血袋收發記錄
  • 設備狀態變更
  • 新增手術記錄
```

#### 場景 B: 小站 → 醫院彙總 (無網路，需實體轉移)
```
流程:
1. 小站 TC-05 產生同步封包 (.sync 檔案)
2. 醫護人員巡迴時以 USB 收集
3. 送至醫院行政單位
4. 匯入: POST /api/hospital/sync/import (multipart/form-data)
5. 醫院產生回傳封包 (其他站點更新)
6. 下次巡迴時 USB 送回小站

同步封包格式:
{
  "hospital_id": "HOSP-001",
  "station_id": "TC-05",
  "sync_timestamp": "2025-11-12T14:30:00",
  "changes": [
    {
      "table": "transactions",
      "operation": "INSERT",
      "data": {...}
    },
    {
      "table": "blood_inventory",
      "operation": "UPDATE",
      "data": {...}
    }
  ],
  "checksum": "sha256_hash"
}
```

### 2. 跨院同步 (Inter-Hospital Sync)

#### 頻率: 低頻 (每日或按需)

#### 場景: 醫院 A 請求醫院 B 支援物資
```
流程:
1. HOSP-001 (醫院A) 發起請求
   POST /api/central/transfer-request
   {
     "from_hospital": "HOSP-002",
     "to_hospital": "HOSP-001",
     "resource_type": "ITEM",
     "item_code": "SURG-001",
     "quantity": 100,
     "urgency": "HIGH",
     "reason": "大量傷患，外科耗材短缺"
   }

2. 中央指揮部審批
   - 自動審批 (符合預設規則)
   - 人工審批 (複雜情況)

3. 審批通過後通知 HOSP-002
   GET /api/central/pending-requests (HOSP-002 定期查詢)

4. HOSP-002 確認執行
   POST /api/central/transfer-confirm
   {
     "request_id": "REQ-20251112-001",
     "status": "APPROVED",
     "actual_quantity": 100,
     "expected_delivery": "2025-11-12T18:00:00"
   }

5. 實體運送 + 資料同步
   - 物資透過軍警管道運送
   - 同時產生調撥記錄同步到中央
   - 中央通知 HOSP-001 物資已發出

6. HOSP-001 收到物資後確認
   POST /api/central/transfer-received
   {
     "request_id": "REQ-20251112-001",
     "received_quantity": 100,
     "received_at": "2025-11-12T17:45:00"
   }
```

### 3. 向中央報告 (Reporting to Central)

#### 頻率: 定期 (每日) + 緊急 (即時)

#### 定期狀態報告
```
醫院每日彙總報告:
POST /api/central/report/daily

{
  "hospital_id": "HOSP-001",
  "report_date": "2025-11-12",
  "summary": {
    "total_stations": 25,
    "operational_stations": 23,
    "offline_stations": 2,
    "total_patients_treated": 147,
    "critical_patients": 12,
    "surgeries_performed": 8,
    "blood_inventory": {
      "O+": 150,
      "O-": 45,
      "A+": 120,
      "A-": 30,
      "B+": 90,
      "B-": 25,
      "AB+": 40,
      "AB-": 15
    },
    "critical_shortages": [
      {
        "item_code": "SURG-001",
        "item_name": "外科縫合針",
        "current_quantity": 15,
        "threshold": 50,
        "urgency": "HIGH"
      }
    ],
    "equipment_status": {
      "operational": 45,
      "maintenance_needed": 3,
      "broken": 2
    }
  },
  "alerts": [
    {
      "type": "SHORTAGE",
      "severity": "HIGH",
      "message": "外科縫合針庫存低於安全值"
    }
  ]
}
```

#### 緊急通報
```
POST /api/central/report/emergency

{
  "hospital_id": "HOSP-001",
  "emergency_type": "MASS_CASUALTY",
  "severity": "CRITICAL",
  "message": "大量傷患湧入，O型血袋緊急短缺",
  "resource_needs": [
    {
      "resource_type": "BLOOD",
      "blood_type": "O+",
      "quantity_needed": 50,
      "urgency": "IMMEDIATE"
    }
  ],
  "timestamp": "2025-11-12T15:30:00"
}
```

---

## 📊 資料庫架構擴充

### 1. 新增醫院實體

```sql
-- 醫院基本資料
CREATE TABLE hospitals (
    hospital_id TEXT PRIMARY KEY,           -- HOSP-001, HOSP-002
    hospital_name TEXT NOT NULL,            -- 前線第一醫院
    hospital_type TEXT NOT NULL,            -- FIELD_HOSPITAL, CIVILIAN_HOSPITAL
    command_level TEXT NOT NULL,            -- CENTRAL, REGIONAL, LOCAL
    latitude REAL,                          -- GPS 座標
    longitude REAL,
    contact_info TEXT,                      -- 聯絡資訊
    network_access TEXT DEFAULT 'NONE',    -- NONE, MILITARY, SATELLITE
    total_stations INTEGER DEFAULT 0,       -- 所屬站點總數
    operational_status TEXT DEFAULT 'ACTIVE', -- ACTIVE, OFFLINE, EVACUATED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK(hospital_type IN ('FIELD_HOSPITAL', 'CIVILIAN_HOSPITAL', 'MOBILE_HOSPITAL')),
    CHECK(command_level IN ('CENTRAL', 'REGIONAL', 'LOCAL')),
    CHECK(network_access IN ('NONE', 'MILITARY', 'SATELLITE', 'CIVILIAN')),
    CHECK(operational_status IN ('ACTIVE', 'OFFLINE', 'EVACUATED', 'MERGED'))
);

-- 站點基本資料 (擴充現有 stations 表)
ALTER TABLE stations ADD COLUMN hospital_id TEXT REFERENCES hospitals(hospital_id);
ALTER TABLE stations ADD COLUMN station_type TEXT DEFAULT 'SMALL';
  -- LARGE (可手術), SMALL (基礎照護)
ALTER TABLE stations ADD COLUMN network_access TEXT DEFAULT 'NONE';
  -- NONE, INTRANET, MILITARY
ALTER TABLE stations ADD COLUMN last_sync_at TIMESTAMP;
  -- 上次同步時間
ALTER TABLE stations ADD COLUMN sync_status TEXT DEFAULT 'PENDING';
  -- PENDING, SYNCING, SYNCED, FAILED
```

### 2. 跨院調撥請求表

```sql
CREATE TABLE inter_hospital_requests (
    request_id TEXT PRIMARY KEY,                  -- REQ-YYMMDD-SEQ
    request_type TEXT NOT NULL,                   -- TRANSFER, SUPPORT, MERGE
    from_hospital_id TEXT NOT NULL,               -- 來源醫院
    to_hospital_id TEXT NOT NULL,                 -- 目標醫院
    resource_type TEXT NOT NULL,                  -- ITEM, BLOOD, EQUIPMENT, PERSONNEL
    resource_id TEXT NOT NULL,                    -- 資源ID
    resource_name TEXT NOT NULL,                  -- 資源名稱
    quantity_requested INTEGER NOT NULL,          -- 請求數量
    quantity_approved INTEGER,                    -- 審批數量
    quantity_delivered INTEGER,                   -- 實際送達數量
    urgency TEXT NOT NULL,                        -- LOW, MEDIUM, HIGH, CRITICAL
    reason TEXT NOT NULL,                         -- 請求原因
    status TEXT DEFAULT 'PENDING',                -- PENDING, APPROVED, REJECTED, IN_TRANSIT, COMPLETED, CANCELLED
    requested_by TEXT NOT NULL,                   -- 請求人
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_by TEXT,                             -- 審批人
    approved_at TIMESTAMP,
    approval_notes TEXT,                          -- 審批備註
    delivered_at TIMESTAMP,                       -- 送達時間
    received_by TEXT,                             -- 接收人
    completion_notes TEXT,                        -- 完成備註
    CHECK(request_type IN ('TRANSFER', 'SUPPORT', 'MERGE')),
    CHECK(resource_type IN ('ITEM', 'BLOOD', 'EQUIPMENT', 'PERSONNEL')),
    CHECK(urgency IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'IN_TRANSIT', 'COMPLETED', 'CANCELLED'))
);

CREATE INDEX idx_inter_hospital_requests_status ON inter_hospital_requests(status);
CREATE INDEX idx_inter_hospital_requests_hospitals ON inter_hospital_requests(from_hospital_id, to_hospital_id);
CREATE INDEX idx_inter_hospital_requests_date ON inter_hospital_requests(requested_at DESC);
```

### 3. 同步封包追蹤表

```sql
CREATE TABLE sync_packages (
    package_id TEXT PRIMARY KEY,                  -- PKG-YYMMDD-HHMMSS-SEQ
    package_type TEXT NOT NULL,                   -- DELTA, FULL, REPORT
    source_type TEXT NOT NULL,                    -- STATION, HOSPITAL
    source_id TEXT NOT NULL,                      -- TC-01, HOSP-001
    destination_type TEXT NOT NULL,               -- HOSPITAL, CENTRAL
    destination_id TEXT NOT NULL,                 -- HOSP-001, CENTRAL-01
    hospital_id TEXT NOT NULL,                    -- 所屬醫院
    transfer_method TEXT NOT NULL,                -- NETWORK, USB, MANUAL
    package_size INTEGER,                         -- 封包大小 (bytes)
    checksum TEXT NOT NULL,                       -- SHA-256 校驗碼
    changes_count INTEGER DEFAULT 0,              -- 變更記錄數
    status TEXT DEFAULT 'PENDING',                -- PENDING, UPLOADED, PROCESSING, APPLIED, FAILED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_at TIMESTAMP,
    processed_at TIMESTAMP,
    error_message TEXT,                           -- 錯誤訊息
    CHECK(package_type IN ('DELTA', 'FULL', 'REPORT')),
    CHECK(source_type IN ('STATION', 'HOSPITAL')),
    CHECK(destination_type IN ('HOSPITAL', 'CENTRAL')),
    CHECK(transfer_method IN ('NETWORK', 'USB', 'MANUAL', 'DRONE')),
    CHECK(status IN ('PENDING', 'UPLOADED', 'PROCESSING', 'APPLIED', 'FAILED'))
);

CREATE INDEX idx_sync_packages_status ON sync_packages(status);
CREATE INDEX idx_sync_packages_source ON sync_packages(source_type, source_id);
CREATE INDEX idx_sync_packages_destination ON sync_packages(destination_type, destination_id);
CREATE INDEX idx_sync_packages_hospital ON sync_packages(hospital_id);
CREATE INDEX idx_sync_packages_date ON sync_packages(created_at DESC);
```

### 4. 醫院彙總報表

```sql
CREATE TABLE hospital_daily_reports (
    report_id TEXT PRIMARY KEY,                   -- RPT-YYMMDD-HOSP-001
    hospital_id TEXT NOT NULL,
    report_date DATE NOT NULL,
    total_stations INTEGER NOT NULL,
    operational_stations INTEGER NOT NULL,
    offline_stations INTEGER NOT NULL,
    total_patients_treated INTEGER DEFAULT 0,
    critical_patients INTEGER DEFAULT 0,
    surgeries_performed INTEGER DEFAULT 0,
    blood_inventory_json TEXT,                    -- JSON: {"O+": 150, "A+": 120, ...}
    critical_shortages_json TEXT,                 -- JSON: [{"item_code": "...", "urgency": "HIGH"}]
    equipment_status_json TEXT,                   -- JSON: {"operational": 45, "broken": 2}
    alerts_json TEXT,                             -- JSON: [{"type": "SHORTAGE", "severity": "HIGH"}]
    submitted_by TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    received_by_central BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMP,
    UNIQUE(hospital_id, report_date)
);

CREATE INDEX idx_hospital_reports_date ON hospital_daily_reports(report_date DESC);
CREATE INDEX idx_hospital_reports_hospital ON hospital_daily_reports(hospital_id);
```

---

## 🔌 API 設計

### 站點層 API (Station-Level APIs)

#### 1. 產生同步封包
```http
POST /api/station/sync/generate
Content-Type: application/json

{
  "station_id": "TC-01",
  "hospital_id": "HOSP-001",
  "sync_type": "DELTA",        // DELTA (增量) / FULL (全量)
  "since_timestamp": "2025-11-12T10:00:00"  // 增量同步起始時間
}

Response:
{
  "success": true,
  "package_id": "PKG-20251112-143000-001",
  "package_file": "/downloads/sync/PKG-20251112-143000-001.sync",
  "package_size": 45678,
  "checksum": "abc123...",
  "changes_count": 23,
  "message": "同步封包已產生，可下載或上傳"
}
```

#### 2. 匯入同步封包 (從醫院下載)
```http
POST /api/station/sync/import
Content-Type: multipart/form-data

package_file: (binary .sync file)

Response:
{
  "success": true,
  "package_id": "PKG-20251112-143000-002",
  "changes_applied": 15,
  "conflicts_detected": 2,
  "conflicts": [
    {
      "table": "items",
      "item_code": "SURG-001",
      "conflict_type": "QUANTITY_MISMATCH",
      "local_value": 50,
      "remote_value": 48,
      "resolution": "KEEP_HIGHER"
    }
  ],
  "message": "同步完成，已套用15項變更"
}
```

---

### 醫院層 API (Hospital-Level APIs)

#### 1. 接收站點同步上傳
```http
POST /api/hospital/sync/upload
Content-Type: application/json

{
  "station_id": "TC-01",
  "package_id": "PKG-20251112-143000-001",
  "changes": [
    {
      "table": "transactions",
      "operation": "INSERT",
      "data": {
        "transaction_type": "CONSUME",
        "item_code": "SURG-001",
        "quantity": 5,
        "station_id": "TC-01",
        "timestamp": "2025-11-12T14:00:00"
      }
    }
  ],
  "checksum": "abc123..."
}

Response:
{
  "success": true,
  "package_id": "PKG-20251112-143000-001",
  "status": "APPLIED",
  "changes_applied": 23,
  "conflicts": 0,
  "response_package_id": "PKG-20251112-143500-002",  // 回傳封包（其他站點更新）
  "message": "同步完成，已產生回傳封包"
}
```

#### 2. 院內物資調撥協調
```http
POST /api/hospital/transfer/coordinate
Content-Type: application/json

{
  "hospital_id": "HOSP-001",
  "from_station_id": "TC-01",
  "to_station_id": "TC-05",
  "resource_type": "ITEM",
  "item_code": "SURG-001",
  "quantity": 20,
  "operator": "張護理長",
  "reason": "TC-05 緊急手術需求"
}

Response:
{
  "success": true,
  "transfer_id": "TRF-20251112-001",
  "from_station_id": "TC-01",
  "to_station_id": "TC-05",
  "resource_type": "ITEM",
  "item_code": "SURG-001",
  "quantity": 20,
  "status": "PENDING_PICKUP",  // 等待 TC-05 下次同步時接收
  "message": "調撥已登記，TC-05 下次同步時會收到物資記錄"
}
```

#### 3. 向中央提交日報
```http
POST /api/hospital/report/daily
Content-Type: application/json

{
  "hospital_id": "HOSP-001",
  "report_date": "2025-11-12",
  "summary": {
    "total_stations": 25,
    "operational_stations": 23,
    "offline_stations": 2,
    "total_patients_treated": 147,
    "critical_patients": 12,
    "surgeries_performed": 8,
    "blood_inventory": {...},
    "critical_shortages": [...],
    "equipment_status": {...}
  },
  "alerts": [...]
}

Response:
{
  "success": true,
  "report_id": "RPT-20251112-HOSP-001",
  "submitted_at": "2025-11-12T18:00:00",
  "received_by_central": true,
  "message": "日報已提交至中央指揮部"
}
```

---

### 中央層 API (Central-Level APIs)

#### 1. 接收醫院日報
```http
GET /api/central/reports/hospitals?date=2025-11-12&hospital_id=HOSP-001

Response:
{
  "reports": [
    {
      "report_id": "RPT-20251112-HOSP-001",
      "hospital_id": "HOSP-001",
      "hospital_name": "前線第一醫院",
      "report_date": "2025-11-12",
      "summary": {...},
      "alerts": [...],
      "submitted_at": "2025-11-12T18:00:00"
    }
  ],
  "count": 1
}
```

#### 2. 跨院調撥請求
```http
POST /api/central/transfer-request
Content-Type: application/json

{
  "from_hospital_id": "HOSP-002",
  "to_hospital_id": "HOSP-001",
  "resource_type": "ITEM",
  "item_code": "SURG-001",
  "quantity_requested": 100,
  "urgency": "HIGH",
  "reason": "大量傷患，外科耗材短缺",
  "requested_by": "HOSP-001 院長"
}

Response:
{
  "success": true,
  "request_id": "REQ-20251112-001",
  "status": "PENDING_APPROVAL",
  "message": "請求已提交，等待中央審批"
}
```

#### 3. 審批跨院請求
```http
POST /api/central/transfer-request/{request_id}/approve
Content-Type: application/json

{
  "approved_by": "中央指揮官",
  "quantity_approved": 100,
  "approval_notes": "同意支援，請於今日18:00前送達",
  "delivery_method": "MILITARY_CONVOY"  // 軍事車隊運送
}

Response:
{
  "success": true,
  "request_id": "REQ-20251112-001",
  "status": "APPROVED",
  "from_hospital_id": "HOSP-002",
  "to_hospital_id": "HOSP-001",
  "quantity_approved": 100,
  "message": "已審批通過，已通知 HOSP-002 準備物資"
}
```

#### 4. 全國資源總覽
```http
GET /api/central/overview/resources?resource_type=BLOOD

Response:
{
  "resource_type": "BLOOD",
  "total_hospitals": 15,
  "total_inventory": {
    "O+": 2340,
    "O-": 567,
    "A+": 1890,
    "A-": 456,
    "B+": 1234,
    "B-": 345,
    "AB+": 678,
    "AB-": 234
  },
  "hospitals": [
    {
      "hospital_id": "HOSP-001",
      "hospital_name": "前線第一醫院",
      "inventory": {
        "O+": 150,
        "O-": 45,
        ...
      },
      "shortages": ["O+", "AB-"],
      "last_reported": "2025-11-12T18:00:00"
    },
    ...
  ],
  "critical_shortages": [
    {
      "hospital_id": "HOSP-003",
      "blood_type": "O+",
      "current_quantity": 5,
      "urgency": "CRITICAL"
    }
  ]
}
```

---

## 🚀 實作階段

### Phase 0: 資料庫與基礎架構 (1-2 週)

#### 0.1 資料庫擴充
- [ ] 建立 `hospitals` 表
- [ ] 擴充 `stations` 表 (新增 hospital_id, station_type, network_access)
- [ ] 建立 `inter_hospital_requests` 表
- [ ] 建立 `sync_packages` 表
- [ ] 建立 `hospital_daily_reports` 表

#### 0.2 基礎 API
- [ ] 醫院管理 API (CRUD)
- [ ] 站點分類與醫院歸屬設定

---

### Phase 1: 院內同步機制 (2-3 週)

#### 1.1 站點層功能
- [ ] 同步封包產生 API
- [ ] 同步封包匯入 API
- [ ] 增量變更追蹤機制
- [ ] 衝突檢測與解決

#### 1.2 醫院層功能
- [ ] 接收站點同步上傳 API
- [ ] 彙總多站點資料
- [ ] 產生回傳封包（其他站點更新）

#### 1.3 前端 UI
- [ ] 站點設定頁：選擇所屬醫院
- [ ] 同步管理頁：上傳/下載同步封包
- [ ] 同步狀態顯示（上次同步時間、待同步變更數）

---

### Phase 2: 院內調撥協調 (1-2 週)

#### 2.1 調撥協調 API
- [ ] 醫院層調撥協調 API
- [ ] 調撥記錄查詢
- [ ] 調撥狀態追蹤

#### 2.2 前端 UI
- [ ] 醫院資源總覽儀表板（僅醫院行政單位可見）
- [ ] 院內調撥協調介面
- [ ] 站點間調撥記錄查詢

---

### Phase 3: 跨院請求與審批 (2-3 週)

#### 3.1 跨院請求 API
- [ ] 提交跨院調撥請求 API
- [ ] 查詢待審批請求 API
- [ ] 審批/拒絕請求 API
- [ ] 確認送達 API

#### 3.2 前端 UI
- [ ] 跨院請求提交表單（醫院層）
- [ ] 待審批請求列表（中央層）
- [ ] 審批操作介面
- [ ] 跨院調撥追蹤看板

---

### Phase 4: 中央指揮層 (2-3 週)

#### 4.1 報告系統
- [ ] 接收醫院日報 API
- [ ] 緊急通報 API
- [ ] 報告查詢與統計

#### 4.2 資源總覽
- [ ] 全國/戰區資源總覽 API
- [ ] 關鍵短缺警報系統
- [ ] 戰略調配建議系統

#### 4.3 前端 UI (中央指揮介面)
- [ ] 全國資源地圖視覺化
- [ ] 醫院狀態儀表板
- [ ] 緊急警報列表
- [ ] 跨院調撥審批工作流程

---

### Phase 5: 離線與實體轉移優化 (1-2 週)

#### 5.1 離線模式增強
- [ ] 完全離線運作支援
- [ ] 本地變更佇列
- [ ] 自動衝突解決策略

#### 5.2 實體轉移工具
- [ ] USB 同步封包自動偵測
- [ ] 批次匯入多個封包
- [ ] 封包完整性驗證工具

---

## ⚠️ 關鍵設計考量

### 1. 網路限制適應

**設計原則:**
- 預設所有站點無網路
- 大站「可能」有網路（透過軍警管道）
- 醫院行政單位「應該」有網路
- 中央指揮部「必須」有網路

**適應策略:**
- 站點層：完全離線優先，同步封包設計
- 醫院層：定期拉取站點更新，推送彙總報告
- 中央層：接收被動報告，發出主動指令

### 2. 資料一致性

**場景：站點 A 與站點 B 離線期間都消耗了同一批物資**

**解決方案:**
- 每個站點獨立管理庫存
- 同步時以「事件日誌」為準，而非「最終狀態」
- 醫院層彙總時加總所有站點消耗，不做逆向修正
- 定期盤點 (inventory audit) 校正誤差

### 3. 衝突解決策略

| 衝突類型 | 解決策略 |
|---------|---------|
| 物資數量不一致 | 以實際消耗事件為準，加總計算 |
| 血袋庫存衝突 | 同上，以事件日誌為準 |
| 手術記錄重複 | 以 record_number 為唯一鍵，後到的忽略 |
| 設備狀態衝突 | 以時間戳較新的為準 |
| 站點資訊衝突 | 以醫院層資料為準（視為權威來源）|

### 4. 審批流程

**自動審批規則:**
- 同一醫院內的站間調撥：自動批准
- 緊急程度 CRITICAL + 數量 < 閾值：自動批准
- 血袋調撥（任何數量）：需人工審批
- 設備調撥：需人工審批

**人工審批流程:**
1. 請求方提交申請
2. 中央指揮部審核
3. 供給方確認可提供
4. 中央下達調撥指令
5. 實體運送
6. 接收方確認收到

### 5. 安全與權限

**三層權限設計:**

| 層級 | 角色 | 權限 |
|-----|------|-----|
| 站點層 | 醫護人員 | 管理本站物資、記錄手術 |
| 站點層 | 站長 | + 提交同步封包、請求院內支援 |
| 醫院層 | 物資管理員 | 查看所有站點庫存、協調院內調撥 |
| 醫院層 | 院長/指揮官 | + 提交跨院請求、產生日報 |
| 中央層 | 資料分析員 | 查看所有報告與統計 |
| 中央層 | 指揮官 | + 審批跨院請求、下達調配指令 |

---

## 📱 前端架構建議

### 站點層介面 (Station UI)
```
Index.html (現有)
  ├─ 物資管理
  ├─ 血袋管理
  ├─ 設備管理
  ├─ 手術記錄
  └─ [新增] 同步管理
       ├─ 產生同步封包 (下載 .sync 檔案)
       ├─ 匯入同步封包 (上傳 .sync 檔案)
       ├─ 同步狀態 (上次同步時間、待同步變更數)
       └─ 同步歷史記錄
```

### 醫院層介面 (Hospital UI)
```
Hospital.html (新建)
  ├─ 醫院總覽儀表板
  │    ├─ 所屬站點地圖
  │    ├─ 各站點運作狀態
  │    └─ 物資總量統計
  ├─ 站點管理
  │    ├─ 站點列表 (25 個站點)
  │    ├─ 站點詳情 (庫存、設備、人員)
  │    └─ 站點同步狀態
  ├─ 院內調撥協調
  │    ├─ 快速調撥 (站點A → 站點B)
  │    ├─ 調撥記錄查詢
  │    └─ 待處理請求
  ├─ 跨院請求
  │    ├─ 提交支援請求
  │    ├─ 我的請求狀態
  │    └─ 收到的支援請求
  └─ 日報管理
       ├─ 產生日報 (自動彙總)
       ├─ 提交中央
       └─ 歷史日報查詢
```

### 中央層介面 (Central UI)
```
Central.html (新建)
  ├─ 全國資源地圖
  │    ├─ 地理位置視覺化
  │    ├─ 各醫院狀態標記
  │    └─ 緊急警報圖標
  ├─ 醫院狀態總覽
  │    ├─ 所有醫院列表
  │    ├─ 關鍵指標 (運作站點數、傷患數、庫存)
  │    └─ 日報接收狀態
  ├─ 跨院調撥審批
  │    ├─ 待審批請求列表
  │    ├─ 審批操作介面
  │    └─ 調撥進度追蹤
  ├─ 資源總覽
  │    ├─ 全國血袋庫存
  │    ├─ 關鍵物資庫存
  │    ├─ 設備分布統計
  │    └─ 短缺警報列表
  └─ 報告與統計
       ├─ 每日彙總報告
       ├─ 趨勢分析圖表
       └─ 資料匯出
```

---

## 🧪 測試場景

### 場景 1: 院內小站請求大站支援 (無網路)

```
初始狀態:
  TC-01 (大站, 有網路): 外科縫合針 100 支
  TC-05 (小站, 無網路): 外科縫合針 5 支

流程:
1. TC-05 記錄緊急消耗 5 支縫合針，庫存歸零
2. TC-05 護理師產生同步封包 PKG-001.sync (包含消耗記錄)
3. 巡迴醫護人員 USB 收集 PKG-001.sync
4. 送至醫院行政單位，上傳到醫院彙總資料庫
5. 醫院系統發現 TC-05 縫合針短缺警報
6. 物資管理員協調：TC-01 → TC-05 調撥 20 支
7. 醫院產生回傳封包 PKG-002.sync (包含調撥記錄)
8. 下次巡迴時 USB 送回 TC-05
9. TC-05 匯入 PKG-002.sync，庫存更新為 20 支

驗證:
  ✓ TC-05 庫存更新正確
  ✓ TC-01 庫存扣除正確
  ✓ 調撥記錄完整
  ✓ 事件日誌雙向記錄
```

### 場景 2: 跨院緊急血袋支援

```
初始狀態:
  HOSP-001 TC-01: O+ 血袋 10 U
  HOSP-002 TC-01: O+ 血袋 150 U

流程:
1. HOSP-001 發生大量傷患，O+ 血袋消耗殆盡
2. HOSP-001 院長提交緊急請求:
   POST /api/central/transfer-request
   {
     "from_hospital_id": "HOSP-002",
     "to_hospital_id": "HOSP-001",
     "resource_type": "BLOOD",
     "blood_type": "O+",
     "quantity_requested": 50,
     "urgency": "CRITICAL",
     "reason": "大量出血傷患，血袋耗盡"
   }

3. 中央指揮部收到請求 (urgency=CRITICAL, resource=BLOOD)
   → 自動通知值班指揮官

4. 指揮官審批:
   POST /api/central/transfer-request/REQ-001/approve
   {
     "approved_by": "中央指揮官",
     "quantity_approved": 50,
     "delivery_method": "HELICOPTER"  // 直升機緊急運送
   }

5. HOSP-002 收到通知 (下次同步或有網路時)
   GET /api/central/pending-requests
   → 看到 REQ-001 已審批

6. HOSP-002 準備 50U O+ 血袋，確認發出:
   POST /api/central/transfer-confirm
   {
     "request_id": "REQ-001",
     "status": "IN_TRANSIT",
     "actual_quantity": 50,
     "expected_delivery": "2025-11-12T16:00:00"
   }

7. 直升機運送 (實體轉移)

8. HOSP-001 收到血袋，確認:
   POST /api/central/transfer-received
   {
     "request_id": "REQ-001",
     "received_quantity": 50,
     "received_at": "2025-11-12T15:55:00"
   }

9. HOSP-001 TC-01 入庫 50U O+ 血袋

驗證:
  ✓ 跨院請求記錄完整
  ✓ 審批流程正確
  ✓ 雙方庫存變更正確
  ✓ 中央可追蹤調撥進度
  ✓ 事件時間軸完整
```

### 場景 3: 醫院日報提交與中央總覽

```
流程:
1. 每日 18:00，HOSP-001 醫院系統自動彙總:
   - 所屬 25 個站點資料
   - 當日統計 (傷患數、手術數)
   - 當前庫存 (物資、血袋、設備)
   - 警報事項 (短缺、設備故障)

2. 產生日報 RPT-20251112-HOSP-001

3. 提交至中央:
   POST /api/central/report/daily
   (包含完整彙總資料)

4. 中央系統接收後:
   - 更新 HOSP-001 在全國地圖上的狀態
   - 檢查短缺警報 → 發現 HOSP-001 外科縫合針嚴重短缺
   - 自動通知鄰近醫院 (HOSP-002, HOSP-003)
   - 指揮官查看全國資源總覽儀表板

5. 中央指揮官決策:
   - HOSP-003 有充足外科縫合針庫存
   - 主動建議 HOSP-001 向 HOSP-003 請求支援

驗證:
  ✓ 日報彙總正確
  ✓ 中央接收成功
  ✓ 全國總覽更新
  ✓ 短缺警報正確觸發
  ✓ 決策支援資訊完整
```

---

## 📐 架構比較

### 之前的「集中式+離線備份」架構
```
優點:
  ✓ 實作簡單
  ✓ 資料一致性容易保證
  ✓ 適合小規模部署

缺點:
  ✗ 不符合實際醫院組織結構
  ✗ 無法處理頻繁的院內協作
  ✗ 跨院請求缺乏審批機制
  ✗ 中央指揮無法有效監控全局
```

### 現在的「聯邦式三層」架構
```
優點:
  ✓ 符合實際醫院組織結構
  ✓ 支援頻繁院內同步與調撥
  ✓ 跨院請求有完整審批流程
  ✓ 中央可有效監控與決策
  ✓ 網路限制下依然可運作
  ✓ 各層級權責分明

缺點:
  ✗ 實作複雜度較高
  ✗ 需要更多資料庫設計
  ✗ 同步機制較複雜
  ✗ 需要三套不同的前端介面
```

---

## 💡 實作建議

### 1. 漸進式遷移

**不要一次全部重構！** 建議分階段：

**Step 1:** 保持現有單站功能，新增 hospital_id 欄位
**Step 2:** 實作同步封包機制（先測試兩個站點）
**Step 3:** 實作醫院層彙總功能
**Step 4:** 實作跨院請求與審批
**Step 5:** 實作中央指揮層介面

### 2. 資料遷移腳本

```python
# migration_to_federated.py

def migrate_to_federated():
    # 1. 建立預設醫院
    cursor.execute("""
        INSERT INTO hospitals (hospital_id, hospital_name, hospital_type, command_level)
        VALUES ('HOSP-001', '前線第一醫院', 'FIELD_HOSPITAL', 'LOCAL')
    """)

    # 2. 將現有站點歸屬到預設醫院
    cursor.execute("""
        UPDATE stations
        SET hospital_id = 'HOSP-001',
            station_type = CASE
                WHEN station_id IN ('TC-01', 'TC-02') THEN 'LARGE'
                ELSE 'SMALL'
            END
    """)

    # 3. 建立初始同步基準點
    cursor.execute("""
        INSERT INTO sync_packages (package_id, source_type, source_id, destination_type, destination_id, hospital_id, transfer_method, status)
        SELECT
            'PKG-INITIAL-' || station_id,
            'STATION',
            station_id,
            'HOSPITAL',
            'HOSP-001',
            'HOSP-001',
            'INITIAL',
            'APPLIED'
        FROM stations
    """)

    conn.commit()
```

### 3. 測試策略

**單機測試環境:**
1. 啟動一個 main.py (8000 port)
2. 開啟多個瀏覽器分頁:
   - 分頁 1: TC-01 (大站)
   - 分頁 2: TC-05 (小站)
   - 分頁 3: HOSP-001 (醫院層介面)
   - 分頁 4: CENTRAL (中央層介面)
3. 模擬同步封包產生與匯入流程

---

## 📞 後續支援

如有問題或需要進一步設計細節，請提出。

**關鍵決策點需要確認:**
1. 是否採用此聯邦式三層架構？
2. 優先實作哪個 Phase？
3. 中央層是否需要獨立部署（不同伺服器）？
4. 是否需要多語言支援（英文/中文）？

---

**版本**: v2.0-FEDERATED
**建立日期**: 2025-11-12
**最後更新**: 2025-11-12
**架構類型**: 聯邦式三層 (Federated Three-Tier)
