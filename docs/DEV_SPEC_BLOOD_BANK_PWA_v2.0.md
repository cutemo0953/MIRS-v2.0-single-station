# Blood Bank PWA DEV SPEC v2.0

**版本**: 2.0
**日期**: 2026-01-12
**狀態**: Planning
**基於**: Gemini + ChatGPT 第二輪審閱 + BioMed PWA 經驗教訓

---

## 執行摘要

Blood Bank PWA 將從 MIRS 主站剝離成獨立 PWA，採用與 BioMed PWA 相同的架構模式（MIRS 後台 + SQLite + PWA 連動）。血品管理具有最高臨床風險：**「發錯血會死人，沒血也會死人」**。

v2.0 新增：
- **雙軌並行**：MIRS Tab + Blood PWA 共存
- **緊急發血**：戰時 Break-Glass 機制
- **原子預約**：409 CONFLICT 防止雙重預約
- **Event Sourcing**：完整稽核鏈

---

## 一、v1.0 → v2.0 差異

### 1.1 ChatGPT 第二輪意見

| 議題 | v1.0 狀態 | v2.0 修正 |
|------|----------|----------|
| **Reservation 原子性** | 未定義 | ✅ 新增 409 CONFLICT + guard update |
| **訂單履約欄位** | 缺失 | ✅ 新增 `reserved_quantity`, `issued_quantity` |
| **狀態機硬規則** | 只列狀態 | ✅ 定義允許轉移 + API 強制 |
| **Event Sourcing** | 只有 crossmatch_log | ✅ 新增 `blood_unit_events` 表 |
| **Idempotency** | 未定義 | ✅ CIRS 回呼帶 idempotency_key |
| **驗收標準** | 基礎 | ✅ 擴展並發/衝突測試 |

### 1.2 Gemini 第二輪意見

| 議題 | v1.0 狀態 | v2.0 修正 |
|------|----------|----------|
| **緊急發血** | 缺失 | ✅ 新增 Emergency Release + Break-Glass |
| **歸還/取消** | 缺失 | ✅ 新增 Unreserve / Return API |
| **Barcode 強制掃描** | 未定義 | ✅ 出庫必須掃碼 + FIFO 警示 |
| **批次報廢** | 未定義 | ✅ 新增 Batch Update 功能 |
| **View 過濾過期** | Bug | ✅ 修正 physical_count 定義 |
| **雙軌並行** | 未定義 | ✅ MIRS Tab + PWA 共存 |

---

## 二、雙軌並行架構

### 2.1 設計原則

```
┌─────────────────────────────────────────────────────────────────┐
│                     雙軌並行架構                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 MIRS Backend (SQLite)                    │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────────────────┐    │   │
│  │  │          /api/blood/* (統一 API)                 │    │   │
│  │  │  - 所有邏輯在此                                   │    │   │
│  │  │  - 兩種 UI 呼叫同一組 API                         │    │   │
│  │  └─────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌────────────────┐    ┌────────────────────────────┐   │   │
│  │  │ blood_units    │    │ v_blood_availability       │   │   │
│  │  │ blood_events   │    │ v_blood_unit_status        │   │   │
│  │  │ transfusion_   │    │                            │   │   │
│  │  │   orders       │    │ (Single Source of Truth)   │   │   │
│  │  └────────────────┘    └────────────────────────────┘   │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│         ┌─────────────────┴─────────────────┐                  │
│         │                                   │                  │
│         ▼                                   ▼                  │
│  ┌─────────────────────┐         ┌─────────────────────────┐  │
│  │  MIRS Tab (簡易版)   │         │   Blood PWA (專業版)     │  │
│  │                     │         │                         │  │
│  │  適用場景：          │         │  適用場景：               │  │
│  │  - 單人診所         │         │  - 專職血庫技師           │  │
│  │  - 總覽模式         │         │  - 大型醫院              │  │
│  │  - 緊急備援         │         │  - 分工精細              │  │
│  │                     │         │                         │  │
│  │  功能：             │         │  功能：                   │  │
│  │  - 庫存總覽         │         │  - 完整出入庫流程         │  │
│  │  - 簡易扣庫         │         │  - Barcode 掃描          │  │
│  │  - 緊急發血按鈕     │         │  - 配血流程              │  │
│  │                     │         │  - 稽核報表              │  │
│  └─────────────────────┘         └─────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 功能分級表

| 功能 | **Blood PWA (專業模式)** | **MIRS Tab (單兵模式)** |
|------|--------------------------|------------------------|
| **適用場景** | 專職血庫技師、大型醫院 | 醫師兼藥師、前線救護站 |
| **庫存檢視** | 詳細 (效期、血型、預約單號) | 簡易 (血型總量 A/B/O/AB) |
| **一般發血** | 掃描 Barcode + 核對醫囑 | 點擊「-1」按鈕 (簡易扣庫) |
| **緊急領血** | **完整流程** (驗證+掃碼+警示) | **簡易按鈕** (快速扣庫) |
| **效期阻擋** | **強制阻擋** (不可出庫) | **視覺警示** (亮紅燈但允許) |
| **配血流程** | 完整交叉配血記錄 | 不支援 (直接發血) |
| **預約管理** | 支援 Reserve/Unreserve | 不支援 |
| **離線支援** | Service Worker | 依賴 MIRS 主站 |

---

## 三、緊急發血 (Emergency Release)

### 3.1 場景

大量傷患湧入，休克病人在門口。醫生來不及開單、來不及做 Crossmatch。

### 3.2 機制

```
┌─────────────────────────────────────────────────────────────┐
│                   緊急發血流程 (Break-Glass)                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  觸發條件：                                                  │
│  - 庫存有 O 型血                                            │
│  - 無需 Order ID                                            │
│  - 無需 Crossmatch                                          │
│                                                             │
│  流程：                                                      │
│  1. 點擊「緊急發血」(大紅按鈕)                               │
│  2. 選擇血型 (O+ / O-)                                      │
│  3. 輸入理由 (必填)                                         │
│  4. 確認發血                                                │
│                                                             │
│  後端處理：                                                  │
│  - 跳過 Order ID 驗證                                       │
│  - 直接扣庫存                                               │
│  - 標記 is_emergency_release = true                         │
│  - 標記 is_uncrossmatched = true                            │
│  - 觸發 Break-Glass 稽核事件                                │
│  - 通知所有 Admin                                           │
│                                                             │
│  事後：                                                      │
│  - 產生「待補單」任務                                        │
│  - 24h 內補齊 Order ID                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 API

```python
@router.post("/api/blood/emergency-release")
async def emergency_release(
    blood_type: str,       # O+ 或 O-
    quantity: int,         # 通常為 1
    reason: str,           # 必填理由
    requester_id: str      # 請求者 (醫師/護理師)
):
    """
    緊急發血 - 繞過正常流程
    """
    # 1. 驗證血型 (只允許 O 型)
    if blood_type not in ['O+', 'O-']:
        raise HTTPException(400, "緊急發血僅限 O 型血")

    # 2. 查詢可用血袋 (FIFO)
    cursor.execute("""
        SELECT id FROM blood_units
        WHERE blood_type = ? AND status = 'AVAILABLE'
        AND expiry_date > DATE('now', 'localtime')
        ORDER BY expiry_date ASC
        LIMIT ?
    """, (blood_type, quantity))

    units = cursor.fetchall()
    if len(units) < quantity:
        raise HTTPException(409, "庫存不足")

    # 3. 原子更新
    unit_ids = [u['id'] for u in units]
    for unit_id in unit_ids:
        cursor.execute("""
            UPDATE blood_units
            SET status = 'ISSUED',
                issued_at = CURRENT_TIMESTAMP,
                issued_by = ?,
                is_emergency_release = 1,
                is_uncrossmatched = 1
            WHERE id = ? AND status = 'AVAILABLE'
        """, (requester_id, unit_id))

        if cursor.rowcount == 0:
            raise HTTPException(409, "血袋狀態已變更")

    # 4. Break-Glass 稽核
    cursor.execute("""
        INSERT INTO blood_unit_events (
            id, unit_id, event_type, actor, reason, severity
        ) VALUES (?, ?, 'EMERGENCY_RELEASE', ?, ?, 'CRITICAL')
    """, (str(uuid.uuid4()), ','.join(unit_ids), requester_id, reason))

    # 5. 通知 Admin (如有 WebSocket)
    await notify_admins({
        "type": "EMERGENCY_RELEASE",
        "blood_type": blood_type,
        "quantity": quantity,
        "requester": requester_id,
        "reason": reason
    })

    return {
        "success": True,
        "unit_ids": unit_ids,
        "warning": "緊急發血已記錄，請於 24h 內補齊醫囑"
    }
```

---

## 四、歸還/取消機制

### 4.1 Unreserve (取消預約)

```python
@router.post("/api/blood/units/{unit_id}/unreserve")
async def unreserve_blood(unit_id: str, reason: str = None):
    """
    取消血袋預約 (預約後未使用)
    """
    cursor.execute("""
        UPDATE blood_units
        SET status = 'AVAILABLE',
            reserved_for_order = NULL,
            reserved_at = NULL,
            reserved_by = NULL
        WHERE id = ? AND status = 'RESERVED'
    """, (unit_id,))

    if cursor.rowcount == 0:
        raise HTTPException(409, "血袋非預約狀態")

    # 記錄事件
    log_blood_event(unit_id, 'UNRESERVE', reason)
    return {"success": True}
```

### 4.2 Return (退庫)

```python
@router.post("/api/blood/units/{unit_id}/return")
async def return_blood(
    unit_id: str,
    out_of_refrigerator_minutes: int,  # 離開冰箱時間
    reason: str
):
    """
    血品退庫 (已發出但未使用)
    """
    # 冷鏈檢查
    COLD_CHAIN_LIMIT_MINUTES = 30

    if out_of_refrigerator_minutes > COLD_CHAIN_LIMIT_MINUTES:
        # 冷鏈中斷，不可退回庫存
        cursor.execute("""
            UPDATE blood_units
            SET status = 'WASTE',
                waste_reason = 'COLD_CHAIN_BREAK'
            WHERE id = ?
        """, (unit_id,))

        log_blood_event(unit_id, 'WASTE', f'冷鏈中斷 ({out_of_refrigerator_minutes} 分鐘)')

        return {
            "success": True,
            "status": "WASTE",
            "warning": f"血袋離開冰箱 {out_of_refrigerator_minutes} 分鐘，超過 {COLD_CHAIN_LIMIT_MINUTES} 分鐘限制，已標記為報廢"
        }
    else:
        # 可退回庫存
        cursor.execute("""
            UPDATE blood_units
            SET status = 'AVAILABLE',
                issued_at = NULL,
                issued_by = NULL,
                issued_to_order = NULL
            WHERE id = ? AND status = 'ISSUED'
        """, (unit_id,))

        log_blood_event(unit_id, 'RETURN', reason)
        return {"success": True, "status": "AVAILABLE"}
```

---

## 五、原子預約與狀態機

### 5.1 狀態機定義

```
┌─────────────────────────────────────────────────────────────┐
│                     血袋狀態轉移圖                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                     ┌──────────────┐                        │
│                     │   RECEIVED   │ ← 入庫                 │
│                     └──────┬───────┘                        │
│                            │                                │
│                            ▼                                │
│                     ┌──────────────┐                        │
│            ┌───────▶│  AVAILABLE   │◀────────┐              │
│            │        └──────┬───────┘         │              │
│            │               │                 │              │
│    Unreserve/Timeout       │ Reserve       Return           │
│            │               ▼                 │              │
│            │        ┌──────────────┐         │              │
│            └────────│   RESERVED   │─────────┘              │
│                     └──────┬───────┘                        │
│                            │                                │
│                            │ Issue                          │
│                            ▼                                │
│                     ┌──────────────┐                        │
│                     │    ISSUED    │ ← 不可逆                │
│                     └──────────────┘                        │
│                                                             │
│  側邊狀態：                                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │  EXPIRED   │  │   WASTE    │  │ QUARANTINE │             │
│  │ (計算得出)  │  │  (報廢)    │  │   (隔離)   │             │
│  └────────────┘  └────────────┘  └────────────┘             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 允許的轉移 (API 強制)

```python
ALLOWED_TRANSITIONS = {
    'RECEIVED': ['AVAILABLE', 'QUARANTINE', 'WASTE'],
    'AVAILABLE': ['RESERVED', 'ISSUED', 'WASTE', 'QUARANTINE'],
    'RESERVED': ['AVAILABLE', 'ISSUED', 'WASTE'],  # AVAILABLE = unreserve/timeout
    'ISSUED': [],  # 不可逆
    'QUARANTINE': ['AVAILABLE', 'WASTE'],
    'WASTE': [],  # 不可逆
    'EXPIRED': [],  # 計算狀態，不可手動轉移
}

def validate_status_transition(current: str, target: str) -> bool:
    """驗證狀態轉移是否合法"""
    return target in ALLOWED_TRANSITIONS.get(current, [])
```

### 5.3 原子預約 (Guard Update)

```python
@router.post("/api/blood/units/{unit_id}/reserve")
async def reserve_blood(unit_id: str, order_id: str, reserver_id: str):
    """
    預約血袋 - 原子操作，防止雙重預約
    """
    # Guard Update: 只有 AVAILABLE 才能被預約
    cursor.execute("""
        UPDATE blood_units
        SET status = 'RESERVED',
            reserved_for_order = ?,
            reserved_at = CURRENT_TIMESTAMP,
            reserved_by = ?
        WHERE id = ?
        AND status = 'AVAILABLE'
        AND expiry_date > DATE('now', 'localtime')
    """, (order_id, reserver_id, unit_id))

    if cursor.rowcount == 0:
        # 檢查失敗原因
        cursor.execute("SELECT status, expiry_date FROM blood_units WHERE id = ?", (unit_id,))
        unit = cursor.fetchone()

        if not unit:
            raise HTTPException(404, "血袋不存在")
        elif unit['status'] == 'RESERVED':
            raise HTTPException(409, "CONFLICT: 血袋已被其他訂單預約")
        elif unit['expiry_date'] < date.today().isoformat():
            raise HTTPException(403, "BLOOD_EXPIRED: 血袋已過期")
        else:
            raise HTTPException(409, f"血袋狀態為 {unit['status']}，無法預約")

    log_blood_event(unit_id, 'RESERVE', f"訂單: {order_id}")
    return {"success": True, "reserved_until": calculate_reserve_expiry()}
```

---

## 六、資料庫設計 (v2.0 更新)

### 6.1 血袋單位表 (更新)

```sql
CREATE TABLE IF NOT EXISTS blood_units (
    id TEXT PRIMARY KEY,
    blood_type TEXT NOT NULL,          -- A+, A-, B+, B-, O+, O-, AB+, AB-
    unit_type TEXT NOT NULL,           -- PRBC, FFP, PLT, CRYO
    volume_ml INTEGER DEFAULT 250,
    donation_id TEXT,
    collection_date DATE,
    expiry_date DATE NOT NULL,
    status TEXT DEFAULT 'AVAILABLE',   -- RECEIVED, AVAILABLE, RESERVED, ISSUED, WASTE, QUARANTINE

    -- 預約資訊
    reserved_for_order TEXT,
    reserved_at TIMESTAMP,
    reserved_by TEXT,
    reserve_expires_at TIMESTAMP,      -- v2.0: 預約過期時間

    -- 出庫資訊
    issued_at TIMESTAMP,
    issued_by TEXT,
    issued_to_order TEXT,

    -- v2.0: 緊急發血標記
    is_emergency_release INTEGER DEFAULT 0,
    is_uncrossmatched INTEGER DEFAULT 0,

    -- v2.0: 報廢/隔離資訊
    waste_reason TEXT,
    quarantine_reason TEXT,

    -- 稽核
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 狀態檢查約束
-- SQLite 3.25+ 支援 CHECK 約束
```

### 6.2 輸血醫囑表 (更新)

```sql
CREATE TABLE IF NOT EXISTS transfusion_orders (
    id TEXT PRIMARY KEY,
    cirs_order_id TEXT,
    patient_id TEXT,
    blood_type TEXT NOT NULL,
    unit_type TEXT DEFAULT 'PRBC',
    quantity INTEGER NOT NULL,
    priority TEXT DEFAULT 'ROUTINE',
    status TEXT DEFAULT 'PENDING',

    -- v2.0: 履約追蹤 (ChatGPT 建議)
    reserved_quantity INTEGER DEFAULT 0,
    issued_quantity INTEGER DEFAULT 0,
    fulfilled_at TIMESTAMP,
    cancel_reason TEXT,

    -- 配血資訊
    crossmatch_result TEXT,
    crossmatch_by TEXT,
    crossmatch_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 6.3 血袋事件表 (v2.0 新增)

```sql
-- Event Sourcing: 完整稽核鏈
CREATE TABLE IF NOT EXISTS blood_unit_events (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    order_id TEXT,
    event_type TEXT NOT NULL,
    -- RECEIVE, RESERVE, UNRESERVE, CROSSMATCH, ISSUE,
    -- RETURN, WASTE, QUARANTINE, RELEASE_QUARANTINE,
    -- EMERGENCY_RELEASE, BLOCK_EXPIRED_ATTEMPT

    actor TEXT NOT NULL,
    reason TEXT,
    metadata TEXT,                     -- JSON
    severity TEXT DEFAULT 'INFO',      -- INFO, WARNING, CRITICAL

    ts_client INTEGER,
    ts_server INTEGER DEFAULT (strftime('%s', 'now')),

    -- 鏈結構 (可選)
    prev_hash TEXT,
    event_hash TEXT
);

CREATE INDEX idx_blood_events_unit ON blood_unit_events(unit_id);
CREATE INDEX idx_blood_events_type ON blood_unit_events(event_type);
CREATE INDEX idx_blood_events_ts ON blood_unit_events(ts_server);
```

### 6.4 View 定義 (v2.0 修正)

```sql
-- v2.0: 修正 physical_count 必須排除過期
CREATE VIEW IF NOT EXISTS v_blood_availability AS
SELECT
    blood_type,
    unit_type,

    -- 物理有效庫存 (不含過期/報廢)
    SUM(CASE
        WHEN status IN ('AVAILABLE', 'RESERVED')
        AND expiry_date > DATE('now', 'localtime')
        THEN 1 ELSE 0
    END) AS physical_valid_count,

    -- 已預約數量
    SUM(CASE
        WHEN status = 'RESERVED'
        AND expiry_date > DATE('now', 'localtime')
        THEN 1 ELSE 0
    END) AS reserved_count,

    -- 真正可用數量 = 物理有效 - 預約
    SUM(CASE
        WHEN status = 'AVAILABLE'
        AND expiry_date > DATE('now', 'localtime')
        THEN 1 ELSE 0
    END) AS available_count,

    -- 即將過期 (3天內)
    SUM(CASE
        WHEN status = 'AVAILABLE'
        AND expiry_date <= DATE('now', '+3 days', 'localtime')
        AND expiry_date > DATE('now', 'localtime')
        THEN 1 ELSE 0
    END) AS expiring_soon_count,

    -- 已過期 (待處理)
    SUM(CASE
        WHEN expiry_date < DATE('now', 'localtime')
        AND status NOT IN ('WASTE', 'ISSUED')
        THEN 1 ELSE 0
    END) AS expired_pending_count,

    -- 最近效期 (FIFO 用)
    MIN(CASE
        WHEN status = 'AVAILABLE'
        AND expiry_date > DATE('now', 'localtime')
        THEN expiry_date
    END) AS nearest_expiry

FROM blood_units
WHERE status NOT IN ('WASTE', 'ISSUED')
GROUP BY blood_type, unit_type;
```

---

## 七、Barcode 掃描與 FIFO 警示

### 7.1 掃碼出庫流程

```javascript
async function onBloodUnitScanned(barcode) {
    // 1. 查詢血袋資訊
    const unit = await fetchBloodUnit(barcode);

    // 2. 效期阻擋 (Layer 2)
    if (unit.display_status === 'EXPIRED') {
        showFullScreenBlocker({
            type: 'error',
            title: '血品已過期',
            message: `血袋 ${barcode} 已於 ${unit.expiry_date} 過期`,
            cannotBypass: true
        });
        logBlockedAttempt(barcode, 'EXPIRED');
        return;
    }

    // 3. FIFO 警示 (Gemini 建議)
    if (unit.fifo_priority > 1) {
        const recommended = await fetchRecommendedUnit(unit.blood_type, unit.unit_type);
        const proceed = await showFIFOWarning({
            scanned: unit,
            recommended: recommended,
            message: `建議優先使用效期較近的血袋 ${recommended.id}（剩 ${recommended.hours_until_expiry}h）`
        });

        if (!proceed) {
            return; // 使用者選擇改掃建議血袋
        }
        // 使用者堅持使用此血袋，記錄原因
        logFIFOOverride(barcode, recommended.id);
    }

    // 4. 繼續正常出庫流程
    proceedWithIssue(unit);
}
```

### 7.2 FIFO 警示 UI

```html
<!-- FIFO 警示 Modal -->
<div class="bg-yellow-50 border-l-4 border-yellow-400 p-4">
    <div class="flex">
        <div class="flex-shrink-0">
            <!-- 警告圖示 -->
        </div>
        <div class="ml-3">
            <p class="text-sm text-yellow-700">
                您掃描的血袋 <strong>不是</strong> 效期最近的血袋
            </p>
            <p class="mt-2 text-sm text-yellow-700">
                建議優先使用：<br>
                血袋 <span x-text="recommended.id"></span>
                (剩 <span x-text="recommended.hours_until_expiry"></span> 小時)
            </p>
            <div class="mt-4 flex gap-2">
                <button @click="useFIFO()"
                        class="bg-yellow-500 text-white px-4 py-2 rounded">
                    改用建議血袋
                </button>
                <button @click="proceedAnyway()"
                        class="bg-gray-200 px-4 py-2 rounded">
                    繼續使用此血袋
                </button>
            </div>
        </div>
    </div>
</div>
```

---

## 八、批次報廢 (Batch Update)

### 8.1 場景

- BioMed 偵測到血庫冰箱斷電 4 小時
- 需要一次標記該冰箱所有血袋為隔離/報廢

### 8.2 API

```python
@router.post("/api/blood/batch-update")
async def batch_update_blood(
    filter_criteria: dict,     # {"refrigerator_id": "R001"}
    target_status: str,        # QUARANTINE 或 WASTE
    reason: str
):
    """
    批次更新血袋狀態 (冰箱斷電等情況)
    """
    # 1. 查詢符合條件的血袋
    cursor.execute("""
        SELECT id FROM blood_units
        WHERE refrigerator_id = ?
        AND status IN ('AVAILABLE', 'RESERVED')
    """, (filter_criteria.get('refrigerator_id'),))

    units = cursor.fetchall()
    affected_ids = [u['id'] for u in units]

    # 2. 批次更新
    cursor.execute("""
        UPDATE blood_units
        SET status = ?,
            quarantine_reason = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id IN ({})
    """.format(','.join('?' * len(affected_ids))),
        (target_status, reason, *affected_ids))

    # 3. 批次記錄事件
    for unit_id in affected_ids:
        log_blood_event(unit_id, f'BATCH_{target_status}', reason)

    return {
        "success": True,
        "affected_count": len(affected_ids),
        "affected_ids": affected_ids
    }
```

---

## 九、CIRS 整合與 Idempotency

### 9.1 發血回呼

```python
@router.post("/api/blood/units/{unit_id}/issue")
async def issue_blood(unit_id: str, order_id: str, issuer_id: str):
    """
    發血出庫
    """
    # ... 原子更新 ...

    # 回呼 CIRS (帶 idempotency_key)
    idempotency_key = f"{order_id}:{unit_id}:{int(datetime.utcnow().timestamp())}"

    await notify_cirs({
        "type": "blood_issued",
        "order_id": order_id,
        "unit_id": unit_id,
        "blood_type": unit['blood_type'],
        "issued_at": datetime.utcnow().isoformat(),
        "idempotency_key": idempotency_key
    })

    return {"success": True, "idempotency_key": idempotency_key}
```

### 9.2 CIRS 端處理

```python
# CIRS: backend/routes/blood_callback.py

@router.post("/api/blood-callback/issued")
async def handle_blood_issued(payload: dict):
    """
    處理 MIRS 發血回呼
    """
    idempotency_key = payload.get('idempotency_key')

    # 檢查是否已處理
    cursor.execute("""
        SELECT 1 FROM processed_callbacks WHERE idempotency_key = ?
    """, (idempotency_key,))

    if cursor.fetchone():
        # 重複請求，靜默成功
        return {"success": True, "duplicate": True}

    # 記錄已處理
    cursor.execute("""
        INSERT INTO processed_callbacks (idempotency_key, processed_at)
        VALUES (?, CURRENT_TIMESTAMP)
    """, (idempotency_key,))

    # 更新訂單狀態
    # ...

    return {"success": True}
```

---

## 十、驗收標準 (v2.0 擴展)

### 10.1 並發/衝突測試 (ChatGPT 建議)

- [ ] 兩台設備同時 reserve 同一血袋 → 只有一台成功，另一台 409
- [ ] 血型/成分不符醫囑 → API 必須拒絕
- [ ] 已被其他 order reserve 的血袋 → issue 必須拒絕
- [ ] reserve timeout → 自動釋放回 AVAILABLE
- [ ] CIRS 重複發送 blood_issued → 只處理一次

### 10.2 緊急發血測試 (Gemini 建議)

- [ ] 無 Order 情況下可發 O 型血
- [ ] 緊急發血觸發 Break-Glass 稽核
- [ ] 24h 後未補單 → 產生待補單任務
- [ ] 緊急發血記錄可追溯

### 10.3 歸還/冷鏈測試

- [ ] 離開冰箱 <30 分鐘 → 可退回 AVAILABLE
- [ ] 離開冰箱 >30 分鐘 → 自動標記 WASTE
- [ ] 歸還事件正確記錄

### 10.4 FIFO 與效期測試

- [ ] 掃描非 FIFO 血袋 → 黃色警示
- [ ] 掃描過期血袋 → 全螢幕阻擋
- [ ] View 的 available_count 不含過期品

### 10.5 雙軌並行測試

- [ ] PWA 發血 → MIRS Tab 刷新後庫存正確
- [ ] MIRS Tab 簡易扣庫 → PWA 顯示正確
- [ ] 兩者同時操作不衝突

---

## 十一、實作階段 (v2.0 更新)

### P0: 契約與架構 (1 天)

- [ ] 建立欄位契約表
- [ ] 建立 blood_units, transfusion_orders, blood_unit_events 表
- [ ] 建立 v_blood_availability, v_blood_unit_status View
- [ ] 新增 routes/blood.py 骨架
- [ ] 狀態機轉移驗證

### P1: 核心流程 (2 天)

- [ ] 血袋入庫 (Receive)
- [ ] 可用性/效期清單 (List)
- [ ] 原子預約 (Reserve) + 409 CONFLICT
- [ ] 出庫 (Issue) + Barcode 掃描
- [ ] 歸還 (Return) + 冷鏈檢查
- [ ] 效期阻擋三層防護

### P2: 緊急與進階 (2 天)

- [ ] 緊急發血 (Emergency Release)
- [ ] FIFO 警示
- [ ] 批次報廢 (Batch Update)
- [ ] CIRS 訂單整合 + Idempotency
- [ ] Event Sourcing 完整稽核

### P3: 雙軌整合 (1 天)

- [ ] Blood PWA 完整 UI
- [ ] MIRS Tab 簡易版 UI
- [ ] 狀態同步驗證
- [ ] Service Worker 隔離

---

## 附錄 A: API 一覽

| Endpoint | Method | 描述 | 特殊處理 |
|----------|--------|------|----------|
| `/api/blood/units` | GET | 列表查詢 | View 驅動 |
| `/api/blood/units` | POST | 入庫 | - |
| `/api/blood/units/{id}` | GET | 單筆查詢 | View 驅動 |
| `/api/blood/units/{id}/reserve` | POST | 預約 | 409 CONFLICT |
| `/api/blood/units/{id}/unreserve` | POST | 取消預約 | - |
| `/api/blood/units/{id}/issue` | POST | 出庫 | 效期阻擋 |
| `/api/blood/units/{id}/return` | POST | 退庫 | 冷鏈檢查 |
| `/api/blood/units/{id}/waste` | POST | 報廢 | - |
| `/api/blood/emergency-release` | POST | 緊急發血 | Break-Glass |
| `/api/blood/batch-update` | POST | 批次更新 | - |
| `/api/blood/availability` | GET | 可用性總覽 | View 驅動 |

---

## 附錄 B: 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-12 | 初版：基礎架構、效期阻擋 |
| v2.0 | 2026-01-12 | 緊急發血、原子預約、歸還機制、雙軌並行、Event Sourcing |

---

**文件完成**
**撰寫者**: Claude Code
**審閱者**: Gemini + ChatGPT (第二輪)
**日期**: 2026-01-12
