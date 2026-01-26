# DEV_SPEC: MIRS Lifeboat (Walkaway Test) 實作

**版本**: 1.0
**日期**: 2026-01-26
**狀態**: 待實作
**優先級**: P0 (Critical)
**預估工時**: 4-6 小時

---

## 1. 問題陳述

### 1.1 現況

MIRS 目前 **缺乏** Lifeboat 災難復原機制：

| 功能 | CIRS | MIRS |
|------|------|------|
| `/api/dr/restore` | ✅ | ❌ |
| `/api/dr/export` | ✅ | ❌ |
| `services/event_service.py` | ✅ | ❌ |
| `services/id_service.py` | ✅ | ❌ |
| 統一 `events` 表 | ✅ | ❌ |
| `restore_log` 表 | ✅ | ❌ |

### 1.2 社群貼文宣稱 vs 現實

社群貼文宣稱：
> "萬一主機 (RPi) 被雷擊損毀，只要換一台空機插上去，iPad 會自動偵測並執行「記憶倒灌」"

**此功能在 MIRS 中不存在，需要實作後才能如此宣稱。**

### 1.3 目標

實作完整的 Lifeboat 機制，確保：
1. 資料可完整匯出 (`/api/dr/export`)
2. 資料可冪等還原 (`/api/dr/restore`)
3. 授權過期不影響 DR 操作 (Directive #4)
4. 支援 PWA 作為備份來源 (Edge → Hub 反向還原)

---

## 2. 架構設計

### 2.1 核心元件

```
┌─────────────────────────────────────────────────────────┐
│                      MIRS Server (RPi)                   │
├─────────────────────────────────────────────────────────┤
│  routes/                                                 │
│  └── dr.py                  # Disaster Recovery API      │
│                                                          │
│  services/                                               │
│  ├── id_service.py          # UUIDv7 + HLC              │
│  └── event_service.py       # Event Sourcing + Restore   │
│                                                          │
│  database/                                               │
│  └── migrations/            # events + restore_log 表    │
└─────────────────────────────────────────────────────────┘
          ↑↓ HTTP
┌─────────────────────────────────────────────────────────┐
│                    PWA Client (iPad)                     │
│  - 定期呼叫 /api/dr/export 備份到 IndexedDB             │
│  - 偵測新主機時呼叫 /api/dr/restore 倒灌資料            │
└─────────────────────────────────────────────────────────┘
```

### 2.2 資料流

```
正常運作:
  iPad ─── events ───▶ RPi (events 表)
                         │
                         ▼
              iPad ◀─── /api/dr/export (定期備份)
                         │
                         ▼
                    IndexedDB (本地快取)

災難復原:
  RPi 損毀 → 新 RPi 上線
                         │
                         ▼
  iPad 偵測新主機 (device_id 改變)
                         │
                         ▼
  iPad ─── POST /api/dr/restore ───▶ 新 RPi
           (從 IndexedDB 讀取事件)
                         │
                         ▼
              INSERT OR IGNORE (冪等)
                         │
                         ▼
              rebuild_projections()
```

---

## 3. 實作規格

### 3.1 資料庫 Schema

**檔案**: `database/migrations/m009_walkaway_events.py`

```sql
-- ============================================
-- Unified Events Table (Walkaway Test)
-- ============================================
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,              -- UUIDv7 (client-generated)
    site_id TEXT NOT NULL DEFAULT 'main',   -- Site identifier
    entity_type TEXT NOT NULL,              -- 'anesthesia_case', 'equipment', etc.
    entity_id TEXT NOT NULL,                -- FK to entity
    actor_id TEXT NOT NULL,                 -- Who performed the action
    actor_name TEXT,                        -- Display name (denormalized)
    actor_role TEXT,                        -- Role at time of action
    device_id TEXT,                         -- Source device
    ts_device INTEGER NOT NULL,             -- Unix ms (device time)
    ts_server INTEGER,                      -- Unix ms (server time)
    hlc TEXT,                               -- Hybrid Logical Clock
    event_type TEXT NOT NULL,               -- Domain-specific event type
    schema_version TEXT DEFAULT '1.0',
    payload_json TEXT NOT NULL,             -- JSON payload
    synced INTEGER DEFAULT 0,               -- 0=pending, 1=synced
    acknowledged INTEGER DEFAULT 0,         -- Server acknowledged
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_device);
CREATE INDEX IF NOT EXISTS idx_events_synced ON events(synced);

-- ============================================
-- Restore Log (Audit Trail)
-- ============================================
CREATE TABLE IF NOT EXISTS restore_log (
    restore_session_id TEXT PRIMARY KEY,
    source_device_id TEXT NOT NULL,
    source_device_name TEXT,
    events_received INTEGER,
    events_inserted INTEGER,
    events_already_present INTEGER,
    events_rejected INTEGER,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status TEXT DEFAULT 'IN_PROGRESS'       -- IN_PROGRESS, COMPLETED, PARTIAL, FAILED
);

CREATE INDEX IF NOT EXISTS idx_restore_log_status ON restore_log(status);
```

### 3.2 id_service.py

**檔案**: `services/id_service.py`

從 CIRS 複製，主要功能：

| 函數 | 用途 |
|------|------|
| `generate_uuidv7()` | 生成時序 UUID (RFC 9562) |
| `parse_uuidv7()` | 解析 UUIDv7 取得時間戳 |
| `hlc_send()` | 建立本地事件時生成 HLC |
| `hlc_receive()` | 接收遠端事件時更新 HLC |
| `event_sort_key()` | 事件排序 key 函數 |
| `ts_device_now()` | 當前時間 (毫秒) |

### 3.3 event_service.py

**檔案**: `services/event_service.py`

從 CIRS 複製，主要功能：

| 函數 | 用途 |
|------|------|
| `create_event()` | 建立並插入事件 |
| `get_events_for_entity()` | 查詢實體的所有事件 |
| `get_unsynced_events()` | 取得未同步事件 |
| `lifeboat_restore()` | 冪等災難還原 |
| `rebuild_projections()` | 重建投影表 |

### 3.4 dr.py (API Routes)

**檔案**: `routes/dr.py`

| Endpoint | Method | 說明 |
|----------|--------|------|
| `/api/dr/export` | GET | 匯出所有事件 |
| `/api/dr/export/entity/{type}/{id}` | GET | 匯出特定實體事件 |
| `/api/dr/restore` | POST | Lifeboat 還原 |
| `/api/dr/restore/{session_id}/status` | GET | 查詢還原狀態 |
| `/api/dr/stats` | GET | DR 統計 |
| `/api/dr/health` | GET | DR 健康檢查 |

---

## 4. API 規格

### 4.1 POST /api/dr/restore

**Request:**
```json
{
    "restore_session_id": "019beaab-ac13-7000-8000-000000000001",
    "source_device_id": "iPad-Nurse-001",
    "source_device_name": "護理師 iPad",
    "events": [
        {
            "event_id": "019beaab-ac13-7001-8000-000000000001",
            "entity_type": "anesthesia_case",
            "entity_id": "ANES-2026-0001",
            "actor_id": "U001",
            "event_type": "VITAL_RECORDED",
            "ts_device": 1737907200000,
            "hlc": "019beaabac13.0001",
            "payload": {"sbp": 120, "dbp": 80, "hr": 72}
        }
    ],
    "events_count": 1
}
```

**Response:**
```json
{
    "status": "COMPLETED",
    "restore_session_id": "019beaab-ac13-7000-8000-000000000001",
    "events_received": 1,
    "events_inserted": 1,
    "events_already_present": 0,
    "events_rejected": 0,
    "projections_rebuilt": ["anesthesia_case"],
    "message": "Restore completed successfully"
}
```

### 4.2 GET /api/dr/export

**Query Parameters:**
- `entity_type`: 篩選實體類型 (optional)
- `since_ts`: 只匯出此時間後的事件 (optional)
- `limit`: 最大事件數 (default: 10000)

**Response:**
```json
{
    "export_id": "019beaab-ac13-7000-8000-000000000002",
    "exported_at": 1737907200000,
    "events_count": 500,
    "events": [...],
    "site_id": "BORP-DNO-01",
    "device_id": "RPi-Main-001"
}
```

---

## 5. 實作步驟

### Step 1: 複製核心服務 (30 min)

```bash
# 從 CIRS 複製
cp ~/Downloads/CIRS/backend/services/id_service.py \
   ~/Downloads/MIRS-v2.0-single-station/services/

cp ~/Downloads/CIRS/backend/services/event_service.py \
   ~/Downloads/MIRS-v2.0-single-station/services/
```

**修改 import paths**:
- 移除 CIRS 特定的 imports
- 調整 database 連接方式

### Step 2: 建立資料庫遷移 (30 min)

建立 `database/migrations/m009_walkaway_events.py`:
- `events` 表
- `restore_log` 表
- 相關索引

### Step 3: 實作 DR API (1 hr)

建立 `routes/dr.py`:
- `/api/dr/export`
- `/api/dr/restore`
- `/api/dr/stats`
- `/api/dr/health`

### Step 4: 整合到 main.py (15 min)

```python
# main.py
from routes.dr import router as dr_router

app.include_router(dr_router)
```

### Step 5: 測試 (1 hr)

```bash
# 1. 匯出測試
curl http://localhost:8000/api/dr/export | jq .

# 2. 還原測試 (模擬)
curl -X POST http://localhost:8000/api/dr/restore \
  -H "Content-Type: application/json" \
  -d '{"restore_session_id":"test-001","source_device_id":"test","events":[],"events_count":0}'

# 3. 健康檢查
curl http://localhost:8000/api/dr/health
```

---

## 6. 測試案例

### 6.1 Walkaway Tests

| # | 測試 | 預期結果 |
|---|------|----------|
| WK-01 | 匯出空資料庫 | events_count: 0 |
| WK-02 | 匯出有資料 | events_count > 0, events 完整 |
| WK-03 | 還原空事件 | COMPLETED, inserted: 0 |
| WK-04 | 還原新事件 | COMPLETED, inserted: N |
| WK-05 | 重複還原 (冪等) | already_present: N, inserted: 0 |
| WK-06 | 並發還原 | 第二個請求返回 409 |

### 6.2 License Tests

| # | 測試 | 預期結果 |
|---|------|----------|
| L-DR-01 | TRIAL 下匯出 | 成功 (License 不阻擋) |
| L-DR-02 | BASIC_MODE 下匯出 | 成功 |
| L-DR-03 | TRIAL 下還原 | 成功 |
| L-DR-04 | BASIC_MODE 下還原 | 成功 |

---

## 7. 與現有系統整合

### 7.1 anesthesia_events 表

MIRS 已有 `anesthesia_events` 表，需要決定：

**選項 A: 雙軌運行 (建議)**
- 保留 `anesthesia_events` (現有功能不變)
- 新增 `events` 表 (統一事件源)
- 寫入時同步寫入兩邊
- 未來逐步遷移

**選項 B: 遷移 anesthesia_events**
- 將 `anesthesia_events` 資料遷移到 `events`
- 修改所有讀寫程式碼
- 風險較高，工時較長

### 7.2 Projection Rebuilder

需實作 anesthesia 投影重建器：

```python
@register_projection_rebuilder('anesthesia_case')
def rebuild_anesthesia_projections(conn, events_by_entity):
    """
    從 events 重建 anesthesia_cases 表
    """
    for case_id, events in events_by_entity.items():
        # 1. 刪除現有投影
        conn.execute("DELETE FROM anesthesia_cases WHERE id = ?", (case_id,))

        # 2. 從事件重建狀態
        state = {}
        for event in events:
            apply_event_to_state(state, event)

        # 3. 插入新投影
        conn.execute("INSERT INTO anesthesia_cases (...) VALUES (...)", state)
```

---

## 8. PWA 端變更 (Phase 2)

PWA 需要新增功能：

### 8.1 自動備份

```javascript
// 每 5 分鐘備份
setInterval(async () => {
    const lastTs = await getLastBackupTs();
    const response = await fetch(`/api/dr/export?since_ts=${lastTs}`);
    const data = await response.json();
    await saveToIndexedDB(data.events);
}, 5 * 60 * 1000);
```

### 8.2 新主機偵測

```javascript
// 比對 device_id
const serverInfo = await fetch('/api/health').then(r => r.json());
const knownDeviceId = localStorage.getItem('known_device_id');

if (serverInfo.device_id !== knownDeviceId) {
    // 新主機！觸發還原流程
    const events = await loadFromIndexedDB();
    await fetch('/api/dr/restore', {
        method: 'POST',
        body: JSON.stringify({
            restore_session_id: generateUUID(),
            source_device_id: getDeviceId(),
            events: events,
            events_count: events.length
        })
    });

    // 更新已知主機
    localStorage.setItem('known_device_id', serverInfo.device_id);
}
```

---

## 9. 風險與緩解

| 風險 | 影響 | 緩解措施 |
|------|------|----------|
| 大量事件還原耗時 | API timeout | 分批還原，增加 timeout |
| IndexedDB 空間限制 | 備份不完整 | 只保留最近 30 天 |
| 並發還原競爭 | 資料不一致 | 使用 file lock |
| 投影重建失敗 | 資料不可用 | 允許部分成功，記錄錯誤 |

---

## 10. 驗收標準

### 必須通過

- [ ] `curl /api/dr/health` 返回 healthy
- [ ] `curl /api/dr/export` 返回正確事件
- [ ] `POST /api/dr/restore` 成功插入事件
- [ ] 重複還原不產生重複資料 (冪等)
- [ ] License 過期時 DR 操作正常

### 選擇性 (Phase 2)

- [ ] PWA 自動備份到 IndexedDB
- [ ] PWA 偵測新主機自動還原

---

## 11. 時程

| 階段 | 工作項目 | 預估 |
|------|----------|------|
| Phase 1 | id_service + event_service 移植 | 1 hr |
| Phase 1 | 資料庫遷移 | 30 min |
| Phase 1 | dr.py API 實作 | 1 hr |
| Phase 1 | 整合測試 | 1 hr |
| Phase 2 | PWA 自動備份 | 2 hr |
| Phase 2 | PWA 新主機偵測 | 2 hr |

**Phase 1 總計: 3.5 - 4 小時**
**Phase 2 總計: 4 小時**

---

## 12. 相關文件

- `CIRS/backend/services/id_service.py` - 參考實作
- `CIRS/backend/services/event_service.py` - 參考實作
- `CIRS/backend/routes/dr.py` - 參考實作
- `CIRS/docs/PROGRESS_REPORT_WALKAWAY_v1.0.md` - CIRS 進度報告
- `DEV_SPEC_IMPLEMENTATION_DIRECTIVES_v1.0.md` - 實作指令

---

*DEV_SPEC_LIFEBOAT_MIRS_v1.0*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
