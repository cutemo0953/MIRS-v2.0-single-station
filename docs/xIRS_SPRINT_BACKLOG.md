# xIRS v3.0 Sprint Backlog

**建立日期**: 2026-01-07
**更新日期**: 2026-01-07 (v1.3)
**架構依據**: `xIRS_ARCHITECTURE_FINAL.md`
**整合來源**: Claude + ChatGPT + Gemini 任務分解

---

## 進度摘要

| Sprint | 狀態 | 完成項目 |
|--------|------|----------|
| Sprint 1 | ✅ 完成 | D-01~D-05 ✓, A-01~A-05 ✓, M-01~M-04 ✓, S-01~S-02 ✓, Identity ✓ |
| Sprint 2 | ✅ 完成 | N-01~N-05 ✓, W-01~W-04 ✓, MAR-01~MAR-05 ✓, O-01~O-04 ✓ |
| Sprint 3 | ✅ 完成 | T-01~T-05 ✓, I-01~I-04 ✓, E2E-01~E2E-05 ✓ |
| Sprint 4 | ⬜ 待開始 | - |

---

## 遷移策略: Strangler Fig Pattern

> 舊功能 **不立即移除**，新功能 **並行運行**，待新功能穩定後，舊入口逐步導向新路徑。

```
Sprint 1-2: 新 API + Nursing PWA MVP (並行舊功能)
Sprint 3:   流量導向新路徑
Sprint 4:   舊功能 deprecate + 清理
```

---

## Sprint 1: 資料權威與 API 骨架 (v3.0-alpha)

### 目標
- 建立統一 execution 資料表
- 建立 resource_intent 管線
- 跨系統認證 (Station Token)

### 工作項

#### 1.1 資料層 (Data Authority)

| ID | 任務 | 優先 | 估計 |
|----|------|:----:|------|
| D-01 | 設計 `executions` 統一 schema | P0 | - |
| D-02 | 設計 `resource_intents` 表 | P0 | - |
| D-03 | CIRS 新增 migration SQL | P0 | - |
| D-04 | 建立 FTS5 索引 (offline search) | P1 | - |
| D-05 | 設計 bi-temporal 欄位 (event_time, recorded_at) | P0 | - |

**Schema 草案**:
```sql
-- CIRS: executions (臨床真相)
CREATE TABLE executions (
    id TEXT PRIMARY KEY,
    order_id TEXT,                      -- FK to orders (nullable)
    person_id TEXT NOT NULL,

    -- 時間
    event_time INTEGER NOT NULL,        -- 臨床發生時間 (ms)
    recorded_at INTEGER NOT NULL,       -- 輸入時間 (ms)
    time_source TEXT DEFAULT 'NOW',     -- NOW | BACKDATED | CORRECTED

    -- 執行內容
    action TEXT NOT NULL,               -- VERIFIED | DISPENSED | ADMINISTERED | HELD | REFUSED
    actual_dose TEXT,
    site TEXT,
    route TEXT,

    -- 執行者
    executed_by TEXT NOT NULL,
    witness_by TEXT,

    -- 修正
    corrected_from TEXT,
    correction_reason TEXT,

    -- Meta
    station_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- CIRS: resource_intents (資源意圖 queue)
CREATE TABLE resource_intents (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    item_code TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    lot TEXT,
    blood_unit_id TEXT,                 -- 血品專用

    -- 狀態
    status TEXT DEFAULT 'PENDING_SYNC', -- PENDING_SYNC | CONFIRMED | FAILED
    error_message TEXT,

    -- 確認
    confirmed_at INTEGER,
    mirs_ref TEXT,                      -- MIRS 回應 ref

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 1.2 API 合約 (CIRS)

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| A-01 | `POST /api/executions` - 新增執行記錄 | P0 | D-01 |
| A-02 | `GET /api/executions?person_id=` - 查詢 | P0 | D-01 |
| A-03 | `POST /api/executions/{id}/correct` - 修正 | P1 | A-01 |
| A-04 | `GET /api/resource-intents?status=PENDING_SYNC` | P0 | D-02 |
| A-05 | `PATCH /api/resource-intents/{id}` - 狀態更新 | P0 | D-02 |

**Endpoint 設計**:
```python
# routes/executions.py

@router.post("/executions")
async def create_execution(
    execution: ExecutionCreate,
    current_user: User = Depends(get_current_user)
):
    """
    建立執行記錄 + 產生 resource_intents

    寫入合約: 只有 Nursing/Anesthesia/EMT 可呼叫
    """
    # 1. 驗證 role
    if current_user.role not in ['nurse', 'anesthesia', 'emt']:
        raise HTTPException(403, "只有護理人員可建立執行記錄")

    # 2. 建立 execution
    exec_id = generate_id('EXEC')
    # ...

    # 3. 產生 resource_intents (queue)
    for item in execution.items:
        intent = ResourceIntent(
            execution_id=exec_id,
            item_code=item.code,
            quantity=item.quantity,
            status='PENDING_SYNC'
        )
        # ...

    return {"id": exec_id, "intents_count": len(execution.items)}
```

#### 1.3 API 合約 (MIRS Engine)

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| M-01 | `POST /api/inventory/consume` - 消費端點 | P0 | - |
| M-02 | Consume API 驗證 Station Token | P0 | S-01 |
| M-03 | Consume 成功後回報 CIRS | P0 | A-05 |
| M-04 | 庫存不足時回報 FAILED | P1 | M-01 |

**Endpoint 設計**:
```python
# routes/inventory.py (MIRS)

@router.post("/inventory/consume")
async def consume_inventory(
    intent: ConsumeRequest,
    station_token: str = Header(...)
):
    """
    MIRS Engine 消費 API

    只接受來自 CIRS 的 Station Token
    """
    # 1. 驗證 Station Token
    if not verify_station_token(station_token):
        raise HTTPException(401, "Invalid station token")

    # 2. 扣庫存
    try:
        result = deduct_inventory(intent.item_code, intent.quantity, intent.lot)
    except InsufficientStock:
        return {"status": "FAILED", "error": "INSUFFICIENT_STOCK"}

    # 3. 回報
    return {
        "status": "CONFIRMED",
        "mirs_ref": result.ref,
        "confirmed_at": now_ms()
    }
```

#### 1.4 跨系統認證

| ID | 任務 | 優先 | 說明 |
|----|------|:----:|------|
| S-01 | Station Token 驗證機制 | P0 | 複用現有 pairing |
| S-02 | CIRS→MIRS 請求簽章 | P1 | HMAC |
| S-03 | Token 過期自動刷新 | P2 | - |

---

## Sprint 2: Nursing PWA MVP (v3.0-beta)

### 目標
- Nursing PWA 基礎功能
- Ward Mode + MAR 給藥確認
- 離線 + 同步機制

### 工作項

#### 2.1 Nursing PWA 骨架

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| N-01 | 建立 `frontend/nursing/` 目錄結構 | P0 | - |
| N-02 | PWA manifest + service worker | P0 | - |
| N-03 | 共用元件: VS 輸入 | P0 | - |
| N-04 | 共用元件: 病患卡片 | P0 | - |
| N-05 | 共用元件: 掃碼確認 | P1 | - |

**目錄結構**:
```
frontend/nursing/
├── index.html              # PWA 主頁
├── service-worker.js       # 離線快取
├── manifest.json           # PWA manifest
├── css/
│   └── nursing.css
└── js/
    ├── app.js              # Alpine.js 主 app
    ├── modes/
    │   ├── triage.js       # 檢傷模式
    │   ├── er.js           # 急診模式
    │   ├── ward.js         # 病房模式
    │   └── handoff.js      # 交班模式
    └── components/
        ├── vs-input.js     # VS 輸入
        ├── patient-card.js # 病患卡片
        └── scanner.js      # 掃碼
```

#### 2.2 Ward Mode 實作

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| W-01 | 我的病患列表 | P0 | N-04 |
| W-02 | 待辦事項 (from orders) | P0 | A-02 |
| W-03 | VS 採集 (Q4H 提醒) | P1 | N-03 |
| W-04 | 護理紀錄 | P1 | - |
| W-05 | I/O 記錄 | P2 | - |

#### 2.3 MAR 給藥確認

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| MAR-01 | 給藥待辦列表 | P0 | W-02 |
| MAR-02 | 病人手圈掃碼 | P1 | N-05 |
| MAR-03 | 藥品條碼掃碼 | P1 | N-05 |
| MAR-04 | 雙重核對 UI | P1 | MAR-02, MAR-03 |
| MAR-05 | 執行確認 → 呼叫 executions API | P0 | A-01 |

**UI Flow**:
```
[待辦列表] → 選擇給藥項目 → [掃病人手圈] → [掃藥品] →
→ [確認畫面: 藥名、劑量、途徑] → [執行] →
→ execution 建立 + resource_intent PENDING
```

#### 2.4 離線 + 同步

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| O-01 | IndexedDB 本地儲存 | P0 | - |
| O-02 | 離線狀態偵測 | P0 | - |
| O-03 | 離線執行記錄暫存 | P0 | O-01 |
| O-04 | 上線自動同步 | P0 | O-02, O-03 |
| O-05 | 同步衝突處理 | P2 | O-04 |

**離線儲存結構**:
```javascript
// IndexedDB stores
const DB_SCHEMA = {
    patients: { keyPath: 'person_id' },           // 病患快取
    orders: { keyPath: 'id' },                    // 醫囑快取
    executions_local: { keyPath: 'local_id' },   // 本地執行 (待同步)
    sync_queue: { keyPath: 'id' }                 // 同步佇列
};
```

---

## Sprint 3: 流量導向與整合測試 (v3.1)

### 目標
- MIRS Tab 降級為唯讀
- 流量導向 Nursing PWA
- 整合測試

### 工作項

#### 3.1 MIRS 處置 Tab 改版

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| T-01 | 移除「一般消耗」輸入區塊 | P0 | - |
| T-02 | 移除「藥品領用」輸入區塊 | P0 | - |
| T-03 | 處置耗材改為唯讀列表 | P0 | - |
| T-04 | 新增「資源對帳狀態」區塊 | P1 | - |
| T-05 | 新增「開啟 Nursing PWA」按鈕 | P0 | - |

**Before/After**:
```html
<!-- BEFORE (移除) -->
<div x-show="treatmentSubTab === 'general'">
  <input type="text" x-model="generalConsumption.item">
  <input type="number" x-model="generalConsumption.quantity">
  <button @click="submitGeneralConsumption">提交</button>
</div>

<!-- AFTER -->
<div x-show="treatmentSubTab === 'general'">
  <div class="alert alert-info">
    一般消耗已移至 Nursing PWA。
    <a href="/nursing/" class="btn btn-primary">開啟 Nursing PWA</a>
  </div>

  <h3>執行記錄 (唯讀)</h3>
  <table>
    <template x-for="exec in executions">
      <tr>
        <td x-text="exec.event_time"></td>
        <td x-text="exec.action"></td>
        <td x-text="exec.executed_by"></td>
        <td>
          <span x-show="exec.sync_status === 'CONFIRMED'" class="badge bg-green">✓</span>
          <span x-show="exec.sync_status === 'PENDING'" class="badge bg-yellow">🟡</span>
        </td>
      </tr>
    </template>
  </table>
</div>
```

#### 3.2 Incomplete Queue

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| I-01 | Incomplete Queue UI (Nursing PWA) | P0 | - |
| I-02 | 缺必填欄位偵測 | P0 | - |
| I-03 | 補登功能 | P0 | I-02 |
| I-04 | 補登後重新同步 | P0 | I-03 |

**Incomplete 類型**:
```javascript
const INCOMPLETE_TYPES = {
    'BLOOD_MISSING_UNIT': '血品缺 unit_id',
    'CONTROLLED_MISSING_WITNESS': '管藥缺見證者',
    'RESOURCE_SYNC_FAILED': '資源同步失敗',
    'BACKDATED_MISSING_REASON': '補登缺理由'
};
```

#### 3.3 整合測試

| ID | 任務 | 優先 | 依賴 |
|----|------|:----:|------|
| E2E-01 | 醫囑→執行→扣庫 完整流程 | P0 | - |
| E2E-02 | 離線執行→上線同步 | P0 | - |
| E2E-03 | 管藥雙重確認流程 | P1 | - |
| E2E-04 | 血品輸血確認流程 | P1 | - |
| E2E-05 | Incomplete 補登流程 | P1 | - |

---

## Sprint 4: 清理與文件 (v3.2)

### 目標
- 淘汰舊功能
- Dashboard PWA
- 文件更新

### 工作項

#### 4.1 舊功能清理

| ID | 任務 | 優先 |
|----|------|:----:|
| C-01 | 移除 MIRS 處置 Tab 輸入相關 Alpine 方法 | P1 |
| C-02 | 移除未使用的 API endpoints | P1 |
| C-03 | 資料庫 deprecated 欄位標記 | P2 |

#### 4.2 Dashboard PWA

| ID | 任務 | 優先 |
|----|------|:----:|
| DB-01 | Dashboard PWA 骨架 | P1 |
| DB-02 | 即時統計 (病患數、待辦數) | P1 |
| DB-03 | 資源對帳狀態總覽 | P1 |
| DB-04 | 異常警示 | P2 |

#### 4.3 文件更新

| ID | 任務 | 優先 |
|----|------|:----:|
| DOC-01 | 更新 README | P0 |
| DOC-02 | 更新 INSTALL 指南 | P0 |
| DOC-03 | 新增 Nursing PWA 使用手冊 | P1 |
| DOC-04 | API 文件更新 | P1 |
| DOC-05 | 架構圖更新 | P1 |

---

## 驗收準則 (Definition of Done)

### Sprint 1 完成標準
- [x] `executions` 表存在且可 CRUD
- [x] `resource_intents` 表存在且可 CRUD
- [x] MIRS `/api/inventory/consume` 可呼叫並扣庫
- [x] Station Token 驗證通過
- [x] Identity & Role Management (PIN, Session, Audit)

### Sprint 2 完成標準
- [x] Nursing PWA 可離線開啟
- [x] Ward Mode 可顯示我的病患
- [x] MAR 可完成給藥確認
- [x] 離線執行 + 上線同步正常

### Sprint 3 完成標準
- [x] MIRS 處置 Tab 無輸入功能 (T-01~T-05)
- [x] Incomplete Queue 可補登 (I-01~I-04)
- [x] E2E 測試腳本 (E2E-01~E2E-05) - scripts/e2e_sprint3_tests.py

### Sprint 4 完成標準
- [ ] 舊輸入功能已移除
- [ ] 文件已更新
- [ ] Dashboard 可顯示總覽

---

## 風險與緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| 離線資料衝突 | 資料不一致 | Last-write-wins + 人工審核 |
| Station Token 洩漏 | 非授權存取 | Token 綁定 IP + 短效期 |
| 使用者習慣改變 | 抗拒新流程 | 並行期間保留舊入口 |
| 掃碼裝置不穩 | 流程中斷 | 手動輸入備案 |

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 - 整合 Claude/ChatGPT/Gemini 任務分解 |
| v1.1 | 2026-01-07 | Sprint 1 完成 - executions/resource_intents API, Identity Management |
| v1.2 | 2026-01-07 | Sprint 2 完成 - Nursing PWA, Ward Mode, MAR, Offline Sync |
| v1.3 | 2026-01-07 | Sprint 3 完成 - 處置 Tab 改版, Incomplete Queue, E2E 測試腳本 |
