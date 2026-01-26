# DEV_SPEC: MIRS Lifeboat (Walkaway Test) 實作

**版本**: 1.1
**日期**: 2026-01-26
**狀態**: 待實作
**優先級**: P0 (Critical)
**預估工時**: Phase 1: 6-8 小時

---

## 修訂記錄

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-01-26 | 初版 |
| 1.1 | 2026-01-26 | **重大修正** - 整合 Gemini/ChatGPT 審閱意見:<br>• G1: Snapshot + Events 雙軌還原<br>• G2: Admin PIN 保護<br>• G3: 批量交易<br>• C1-C8: 分頁/分批/hash驗證/雙寫/server_uuid 等 |

---

## 0. 重要警告：宣稱 vs 現實

### 0.1 目前狀態

| 宣稱 | 現實 | 修正 |
|------|------|------|
| "iPad 自動偵測並執行記憶倒灌" | ❌ MIRS 沒有這功能 | Phase 2 才實現 |
| "資料一筆不漏地回來" | ❌ 沒有 Lifeboat API | Phase 1 實現 |

### 0.2 對外說法建議

**Phase 1 完成前**：
> "系統具備完整的事件備份與還原 API，可透過指令完成災難復原"

**Phase 2 完成後**：
> "iPad 會自動偵測新主機並執行記憶倒灌"

---

## 1. 架構設計 (v1.1 重大更新)

### 1.1 Snapshot + Events 雙軌還原 (G1 修正)

**問題**：只存 events，UI 讀的是 patients/anesthesia_cases 表，會顯示空白。

**解決方案**：還原時同時傳送 **Snapshot (當前狀態)** 和 **Events (歷史軌跡)**。

```
/api/dr/restore Payload:
{
    "restore_session_id": "...",
    "source_device_id": "...",

    // 🆕 Snapshot: 讓 UI 立即可用
    "snapshot": {
        "anesthesia_cases": [...],  // 完整 JSON
        "patients": [...],
        "equipment": [...]
    },

    // Events: 保留完整歷史軌跡 (Walkaway 承諾)
    "events": [...],
    "events_count": 1000
}
```

**還原邏輯**：
```python
def restore(payload):
    with db.begin():  # G3: 單一交易
        # Step 1: UPSERT Snapshot (UI 立即可用)
        for table, rows in payload['snapshot'].items():
            for row in rows:
                db.execute(f"INSERT OR REPLACE INTO {table} ...")

        # Step 2: INSERT OR IGNORE Events (歷史軌跡)
        for event in payload['events']:
            # C3: Hash 比對
            existing = db.query("SELECT payload_hash FROM events WHERE event_id = ?")
            if existing:
                if existing.payload_hash != hash(event):
                    rejected += 1  # 記錄到 audit
                    continue
                already_present += 1
            else:
                db.execute("INSERT INTO events ...")
                inserted += 1
```

### 1.2 Admin PIN 保護 (G2 修正)

**問題**：MIRS 沒有登入機制，任何人可以呼叫 /api/dr/restore 覆蓋資料。

**解決方案**：敏感操作需要 Admin PIN。

```python
# routes/dr.py
ADMIN_PIN = os.environ.get('MIRS_ADMIN_PIN', '888888')

def require_admin_pin(request: Request):
    """驗證 Admin PIN"""
    pin = request.headers.get('X-MIRS-PIN')
    if not pin or pin != ADMIN_PIN:
        raise HTTPException(403, "Invalid or missing Admin PIN")

@router.post("/restore")
async def restore(request: Request, payload: RestoreRequest):
    require_admin_pin(request)  # 必須驗證 PIN
    # ... 還原邏輯
```

**PIN 設定**：
```bash
# /etc/systemd/system/mirs.service
Environment=MIRS_ADMIN_PIN=888888  # 預設值，建議修改
```

### 1.3 批量交易 (G3 修正)

**問題**：每筆 event 單獨 commit，SD 卡會卡死。

**解決方案**：單一批量交易。

```python
# ❌ 錯誤做法 (1000 次 I/O)
for event in events:
    db.add(event)
    db.commit()

# ✅ 正確做法 (1 次 I/O)
with db.begin():
    for event in events:
        db.add(event)
    # 自動 commit
```

**效能指標**：1000 events 必須在 < 2 秒內完成。

---

## 2. API 規格 (v1.1 更新)

### 2.1 GET /api/dr/export (C1: 分頁支援)

**Query Parameters**：

| 參數 | 說明 | 預設 |
|------|------|------|
| `since_hlc` | 只匯出此 HLC 之後的事件 | null |
| `limit` | 每頁最大數量 | 1000 |
| `include_snapshot` | 是否包含當前狀態快照 | false |

**Response**：
```json
{
    "export_id": "...",
    "exported_at": 1737907200000,
    "server_uuid": "MIRS-550e8400-e29b-41d4-a716",  // C6: 持久化 UUID
    "db_fingerprint": "019beaab-ac13-7001",         // 最後一筆 event_id

    "events": [...],
    "events_count": 1000,

    "pagination": {
        "has_more": true,
        "next_cursor": "019beaab-ac13-7001-8000",  // C1: 游標
        "total_count": 5000
    },

    "snapshot": {  // 只在 include_snapshot=true 時
        "anesthesia_cases": [...],
        "patients": [...]
    }
}
```

### 2.2 POST /api/dr/restore (C2: 分批支援)

**Headers**：
```
X-MIRS-PIN: 888888  # G2: 必須
Content-Type: application/json
```

**Request**：
```json
{
    "restore_session_id": "019beaab-ac13-7000",
    "source_device_id": "iPad-Nurse-001",
    "batch_number": 1,        // C2: 第幾批
    "total_batches": 5,       // C2: 總批數
    "is_final_batch": false,  // C2: 是否最後一批

    "snapshot": {             // 只在第一批時傳送
        "anesthesia_cases": [...],
        "patients": [...]
    },

    "events": [...],
    "events_count": 1000
}
```

**Response**：
```json
{
    "status": "IN_PROGRESS",  // COMPLETED 只在 is_final_batch=true 時
    "restore_session_id": "...",
    "batch_number": 1,
    "events_received": 1000,
    "events_inserted": 950,
    "events_already_present": 45,
    "events_rejected": 5,      // C3: 內容 hash 不符
    "rejected_event_ids": ["..."],  // C3: 記錄被拒絕的 event_id
    "message": "Batch 1/5 processed"
}
```

### 2.3 冪等性 Hash 驗證 (C3)

```python
import hashlib
import json

def compute_event_hash(event: dict) -> str:
    """計算事件內容的 hash"""
    # 排除 synced/acknowledged 等狀態欄位
    hashable = {
        'event_id': event['event_id'],
        'entity_type': event['entity_type'],
        'entity_id': event['entity_id'],
        'event_type': event['event_type'],
        'payload': event['payload'],
        'ts_device': event['ts_device'],
        'hlc': event.get('hlc')
    }
    content = json.dumps(hashable, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def insert_event_idempotent(conn, event: dict) -> str:
    """冪等插入事件，返回狀態"""
    event_hash = compute_event_hash(event)

    existing = conn.execute(
        "SELECT payload_hash FROM events WHERE event_id = ?",
        (event['event_id'],)
    ).fetchone()

    if existing:
        if existing['payload_hash'] == event_hash:
            return 'ALREADY_PRESENT'
        else:
            # C3: 記錄到 audit
            conn.execute("""
                INSERT INTO restore_rejects
                (event_id, restore_session_id, reason, old_hash, new_hash)
                VALUES (?, ?, 'HASH_MISMATCH', ?, ?)
            """, (event['event_id'], session_id, existing['payload_hash'], event_hash))
            return 'REJECTED'

    # 插入新事件
    conn.execute("INSERT INTO events (..., payload_hash) VALUES (..., ?)",
                 (..., event_hash))
    return 'INSERTED'
```

---

## 3. 資料庫 Schema (v1.1 更新)

### 3.1 events 表 (新增 payload_hash)

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL DEFAULT 'main',
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_name TEXT,
    actor_role TEXT,
    device_id TEXT,
    ts_device INTEGER NOT NULL,
    ts_server INTEGER,
    hlc TEXT,
    event_type TEXT NOT NULL,
    schema_version TEXT DEFAULT '1.0',
    payload_json TEXT NOT NULL,
    payload_hash TEXT,              -- 🆕 C3: 內容 hash
    synced INTEGER DEFAULT 0,
    acknowledged INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX idx_events_hlc ON events(hlc);  -- 🆕 C1: 分頁用
```

### 3.2 restore_rejects 表 (新增，C3 審計)

```sql
CREATE TABLE IF NOT EXISTS restore_rejects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    restore_session_id TEXT NOT NULL,
    reason TEXT NOT NULL,           -- 'HASH_MISMATCH', 'INVALID_SCHEMA', etc.
    old_hash TEXT,
    new_hash TEXT,
    rejected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 system_config 表 (新增，C6 server_uuid)

```sql
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 首次啟動時生成
INSERT OR IGNORE INTO system_config (key, value)
VALUES ('server_uuid', 'MIRS-' || lower(hex(randomblob(8))));
```

---

## 4. 雙寫策略 (C4)

### 4.1 Phase 1: 雙寫過渡

**寫入路徑**：
```python
async def add_anesthesia_event(case_id: str, event_type: str, payload: dict):
    with db.begin():
        # 1. 寫入現有 anesthesia_events (維持現有功能)
        db.execute("INSERT INTO anesthesia_events ...")

        # 2. 🆕 同時寫入 events (DR 用)
        db.execute("INSERT INTO events ...")
```

**讀取路徑**：維持現有 (從 anesthesia_events/anesthesia_cases 讀取)

### 4.2 Phase 2: 切換讀路徑

等 rebuild_projections 穩定後：
1. 讀取改為從 events 重建
2. anesthesia_events 變成 view

### 4.3 裁決規則

> **如果 events 與 anesthesia_events 不一致，以誰為準？**

| 情境 | 權威來源 |
|------|----------|
| 平時臨床 UI | anesthesia_events (Phase 1) |
| 災難還原後 | events → rebuild → anesthesia_cases |
| Walkaway 匯出 | events |

---

## 5. Server UUID (C6)

### 5.1 問題

原本用 `/api/health` 的 `device_id`，但語義不明（硬體序號？映像？部署時寫死？）。

### 5.2 解決方案

使用持久化的 `server_uuid`：

```python
def get_server_uuid(conn) -> str:
    """取得或生成 server_uuid"""
    row = conn.execute(
        "SELECT value FROM system_config WHERE key = 'server_uuid'"
    ).fetchone()

    if row:
        return row['value']

    # 首次啟動生成
    import uuid
    server_uuid = f"MIRS-{uuid.uuid4().hex[:16]}"
    conn.execute(
        "INSERT INTO system_config (key, value) VALUES ('server_uuid', ?)",
        (server_uuid,)
    )
    return server_uuid
```

### 5.3 PWA 偵測邏輯 (Phase 2)

```javascript
const response = await fetch('/api/dr/health');
const data = await response.json();

const knownUUID = localStorage.getItem('known_server_uuid');
const knownFingerprint = localStorage.getItem('known_db_fingerprint');

if (data.server_uuid !== knownUUID || data.db_fingerprint === null) {
    // 新主機或空資料庫 → 觸發還原
    await triggerRestore();
}

localStorage.setItem('known_server_uuid', data.server_uuid);
localStorage.setItem('known_db_fingerprint', data.db_fingerprint);
```

---

## 6. License Bypass (C7)

### 6.1 路由層級保證

```python
# routes/dr.py
from fastapi import APIRouter

router = APIRouter(
    prefix="/api/dr",
    tags=["Disaster Recovery"],
    # 🆕 明確標記：不受 License 限制
    dependencies=[]  # 不加入 license_dependency
)

# 在 main.py 中，License middleware 必須 allowlist /api/dr/*
LICENSE_EXEMPT_PATHS = [
    "/api/dr/",
    "/api/health",
    "/api/ota/"
]
```

### 6.2 測試案例

| # | 測試 | 預期結果 |
|---|------|----------|
| L-DR-01 | TRIAL 模式下 export | ✅ 成功 |
| L-DR-02 | BASIC_MODE 下 export | ✅ 成功 |
| L-DR-03 | 無 license 下 restore | ✅ 成功 (需 PIN) |

---

## 7. Time Validity Gate (C8)

### 7.1 問題

RPi 斷電後時間重置，HLC/UUIDv7 可能產生過去的時間戳。

### 7.2 解決方案

```python
# services/id_service.py

BUILD_DATE_TS = 1737849600000  # 2026-01-26 00:00:00 UTC

def validate_time():
    """驗證系統時間有效性"""
    now = int(time.time() * 1000)
    if now < BUILD_DATE_TS:
        raise TimeValidityError(
            f"System time ({now}) is before build date ({BUILD_DATE_TS}). "
            "Please sync time via NTP or RTC."
        )

def generate_uuidv7() -> str:
    validate_time()  # 🆕 先驗證時間
    # ... 原有邏輯
```

### 7.3 應對措施

1. **RTC 模組**：安裝 DS3231，斷電保持時間
2. **NTP 同步**：開機時自動同步（如有網路）
3. **手動校時 API**：`POST /api/system/set-time` (需 Admin PIN)

---

## 8. Phase 分期與驗收

### 8.1 Phase 1: 核心 API (本週)

**交付物**：
- [x] events 表 + 雙寫邏輯
- [x] /api/dr/export (分頁)
- [x] /api/dr/restore (分批 + Snapshot)
- [x] Admin PIN 保護
- [x] server_uuid
- [x] 批量交易
- [x] Hash 冪等驗證

**驗收標準**：
```bash
# 1. Export 成功
curl http://localhost:8000/api/dr/export?include_snapshot=true | jq .

# 2. Restore 成功 (需 PIN)
curl -X POST http://localhost:8000/api/dr/restore \
  -H "X-MIRS-PIN: 888888" \
  -H "Content-Type: application/json" \
  -d '{"restore_session_id":"test","source_device_id":"test","snapshot":{},"events":[],"events_count":0,"is_final_batch":true}'

# 3. 無 PIN 被拒
curl -X POST http://localhost:8000/api/dr/restore \
  -d '{}'
# → 403 Forbidden

# 4. License 過期仍可用
# (設定 BASIC_MODE 後測試上述指令)
```

**效能指標**：
- Export 10000 events: < 5 秒
- Restore 1000 events: < 2 秒

### 8.2 Phase 2: PWA 自動化 (下週)

**交付物**：
- [ ] PWA 定期備份到 IndexedDB
- [ ] PWA 新主機偵測
- [ ] PWA 自動觸發還原

**驗收標準**：
- 換一台空 RPi，iPad 自動還原資料

---

## 9. 檔案清單

### 9.1 新增檔案

| 檔案 | 行數 | 說明 |
|------|------|------|
| `services/id_service.py` | ~450 | UUIDv7 + HLC + Time Gate |
| `services/event_service.py` | ~500 | Event CRUD + Restore |
| `routes/dr.py` | ~350 | DR API |
| `database/migrations/m009_walkaway.py` | ~100 | Schema |

### 9.2 修改檔案

| 檔案 | 變更 |
|------|------|
| `main.py` | 引入 dr_router, License exempt |
| `routes/anesthesia.py` | 雙寫到 events |
| `services/ota_safety.py` | 已有 time validity |

---

## 10. 風險與緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| Snapshot 太大 | 傳輸/存儲壓力 | 壓縮 (gzip)，分表傳送 |
| 雙寫不一致 | 資料分裂 | 裁決規則 (§4.3) |
| PIN 被猜 | 資料被覆蓋 | 限制嘗試次數 + audit log |
| 時間錯誤 | HLC 亂序 | Time Gate + RTC |

---

## 附錄 A: 完整 Restore 流程

```
Client (iPad)                          Server (RPi)
     │                                      │
     │  1. GET /api/dr/health               │
     │  ─────────────────────────────────▶  │
     │  ◀───────────── server_uuid ─────────│
     │                                      │
     │  [偵測到新主機]                       │
     │                                      │
     │  2. 從 IndexedDB 讀取備份             │
     │                                      │
     │  3. POST /api/dr/restore (batch 1)   │
     │     Header: X-MIRS-PIN: 888888       │
     │     Body: { snapshot: {...},         │
     │             events: [...1000],       │
     │             batch_number: 1,         │
     │             is_final_batch: false }  │
     │  ─────────────────────────────────▶  │
     │                                      │  [驗證 PIN]
     │                                      │  [UPSERT snapshot]
     │                                      │  [INSERT events]
     │  ◀───────────── IN_PROGRESS ─────────│
     │                                      │
     │  4. POST /api/dr/restore (batch 2-N) │
     │     ...                              │
     │                                      │
     │  5. POST /api/dr/restore (final)     │
     │     Body: { is_final_batch: true }   │
     │  ─────────────────────────────────▶  │
     │                                      │  [Rebuild projections]
     │  ◀───────────── COMPLETED ───────────│
     │                                      │
     │  6. 更新 localStorage                 │
     │     known_server_uuid = xxx          │
     │                                      │
```

---

## 附錄 B: MIRS 認證策略 (Gemini 建議)

MIRS 不需要登入，但需要「戰術性身分鎖定」：

| Layer | 機制 | 保護對象 |
|-------|------|----------|
| Layer 1 | Gateway Token | API 存取 |
| Layer 2 | 角色選擇 | 簽章歸屬 |
| Layer 3 | Admin PIN | 系統重置、Lifeboat |
| Layer 3 | User PIN | 管制藥品給藥 |

**原則**：
- 看病歷、寫紀錄 → Gateway Token 即可
- 刪庫、改設定、打嗎啡 → 要求 PIN

---

*DEV_SPEC_LIFEBOAT_MIRS_v1.1*
*Reviewed by: Gemini, ChatGPT*
*De Novo Orthopedics Inc.*
