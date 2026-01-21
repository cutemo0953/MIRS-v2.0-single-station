# DEV_SPEC: Anesthesia PWA Inventory Integration v1.0

## Document Info
| Field | Value |
|-------|-------|
| **Version** | 1.0 |
| **Date** | 2026-01-21 |
| **Author** | Claude Opus 4.5 |
| **Status** | Draft |
| **Depends On** | DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md |

---

## 1. Executive Summary

### 1.1 Problem Statement

Anesthesia PWA 目前的庫存顯示有以下問題：

| 問題 | 現況 | 目標 |
|------|------|------|
| **Vercel Demo 無庫存** | 硬編碼 demo_drugs，非動態 | 啟動時預載完整藥品主檔 |
| **直接讀 medicines 表** | 顯示中央藥局庫存 | 讀取藥車/托盤庫存 |
| **管制藥餘額不顯示** | Holdings tab 空白 | 顯示持有餘額及交易歷史 |
| **調撥來源不明** | 不知道藥從哪來 | 顯示調撥來源及時間 |
| **庫存與用藥未關聯** | 用藥不扣藥車庫存 | 用藥時扣減藥車庫存 |

### 1.2 Solution Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MIRS Station                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐         ┌──────────────────────────────────┐ │
│  │   medicines      │         │      cart_inventory              │ │
│  │  (中央藥局主檔)   │ ──────> │     (藥車/托盤庫存)              │ │
│  │                  │  調撥    │                                  │ │
│  │  current_stock   │         │  cart_id: CART-ANES-001          │ │
│  │  = 權威總量      │         │  medicine_code: BC90567209       │ │
│  └──────────────────┘         │  quantity: 10 (持有量)           │ │
│                               │  source_dispatch_id: DISP-001    │ │
│                               └──────────────────────────────────┘ │
│                                          │                         │
│                                          │ 扣減                    │
│                                          ▼                         │
│                               ┌──────────────────────────────────┐ │
│                               │   Anesthesia PWA                 │ │
│                               │                                  │ │
│                               │  ┌─────────┐  ┌───────────────┐  │ │
│                               │  │ 給藥    │  │ 管制藥 Tab    │  │ │
│                               │  │         │  │               │  │ │
│                               │  │ 庫存:5  │  │ Fentanyl: 8支 │  │ │
│                               │  │ (藥車)  │  │ Midazolam: 5支│  │ │
│                               │  └─────────┘  └───────────────┘  │ │
│                               └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Schema

### 2.1 Existing Tables (from Phase 7)

```sql
-- 藥車/托盤定義 (Phase 7 已建立)
CREATE TABLE IF NOT EXISTS drug_carts (
    id TEXT PRIMARY KEY,              -- CART-ANES-001
    name TEXT NOT NULL,               -- 麻醉藥車 #1
    cart_type TEXT DEFAULT 'ANESTHESIA',  -- ANESTHESIA, EMERGENCY, WARD
    location TEXT,                    -- OR-01
    assigned_to TEXT,                 -- 負責人員 ID
    status TEXT DEFAULT 'ACTIVE',     -- ACTIVE, MAINTENANCE, RETIRED
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

-- 藥車庫存 (Phase 7 已建立)
CREATE TABLE IF NOT EXISTS cart_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id TEXT NOT NULL REFERENCES drug_carts(id),
    medicine_code TEXT NOT NULL REFERENCES medicines(medicine_code),
    quantity INTEGER NOT NULL DEFAULT 0,   -- 當前持有量
    min_quantity INTEGER DEFAULT 2,        -- 最低警戒量
    max_quantity INTEGER DEFAULT 20,       -- 最大容量
    last_replenish_at DATETIME,
    last_check_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    UNIQUE(cart_id, medicine_code)
);
```

### 2.2 New Table: Cart Inventory Transactions

```sql
-- Migration: add_cart_inventory_transactions.sql

CREATE TABLE IF NOT EXISTS cart_inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 交易識別
    txn_id TEXT UNIQUE NOT NULL,          -- CITXN-20260121-XXXX
    txn_type TEXT NOT NULL,               -- DISPATCH, RETURN, USE, ADJUST, CHECK

    -- 藥車/藥品
    cart_id TEXT NOT NULL,
    medicine_code TEXT NOT NULL,

    -- 數量變化
    quantity_change INTEGER NOT NULL,     -- +10 (調撥入), -1 (使用)
    quantity_before INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL,

    -- 來源/目的
    source_type TEXT,                     -- PHARMACY, CASE, ADJUSTMENT
    source_id TEXT,                       -- 調撥單號 / 案件 ID / 調整單號

    -- 關聯
    case_id TEXT,                         -- 用於案件時的案件 ID
    medication_event_id TEXT,             -- 關聯的用藥事件 ID

    -- 管制藥追蹤
    controlled_drug_log_id INTEGER,       -- 關聯管制藥紀錄
    witness_id TEXT,                      -- 見證人 (管制藥)

    -- 人員
    actor_id TEXT NOT NULL,
    actor_name TEXT,

    -- 備註
    remarks TEXT,

    -- 時間戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 索引
    FOREIGN KEY (cart_id) REFERENCES drug_carts(id),
    FOREIGN KEY (medicine_code) REFERENCES medicines(medicine_code)
);

CREATE INDEX IF NOT EXISTS idx_cart_inv_txn_cart ON cart_inventory_transactions(cart_id);
CREATE INDEX IF NOT EXISTS idx_cart_inv_txn_medicine ON cart_inventory_transactions(medicine_code);
CREATE INDEX IF NOT EXISTS idx_cart_inv_txn_case ON cart_inventory_transactions(case_id);
CREATE INDEX IF NOT EXISTS idx_cart_inv_txn_type ON cart_inventory_transactions(txn_type);
CREATE INDEX IF NOT EXISTS idx_cart_inv_txn_created ON cart_inventory_transactions(created_at);
```

### 2.3 New Table: Dispatch Records

```sql
-- 調撥記錄 (中央藥局 -> 藥車)
CREATE TABLE IF NOT EXISTS inventory_dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    dispatch_id TEXT UNIQUE NOT NULL,     -- DISP-20260121-XXXX
    dispatch_type TEXT DEFAULT 'STANDARD', -- STANDARD, EMERGENCY, RETURN

    -- 來源/目的
    from_location TEXT DEFAULT 'PHARMACY', -- PHARMACY = 中央藥局
    to_cart_id TEXT NOT NULL,

    -- 狀態
    status TEXT DEFAULT 'PENDING',        -- PENDING, CONFIRMED, CANCELLED

    -- 人員
    requested_by TEXT NOT NULL,
    confirmed_by TEXT,

    -- 時間
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    confirmed_at DATETIME,

    remarks TEXT
);

-- 調撥明細
CREATE TABLE IF NOT EXISTS inventory_dispatch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_id TEXT NOT NULL,
    medicine_code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    lot_number TEXT,                      -- 批號
    expiry_date DATE,                     -- 效期

    FOREIGN KEY (dispatch_id) REFERENCES inventory_dispatches(dispatch_id),
    FOREIGN KEY (medicine_code) REFERENCES medicines(medicine_code)
);
```

---

## 3. API Endpoints

### 3.1 藥車庫存 API

```python
# routes/anesthesia.py

# ============================================================
# Phase 8: Cart Inventory Integration (藥車庫存整合)
# ============================================================

@router.get("/carts/{cart_id}/inventory")
async def get_cart_inventory(
    cart_id: str,
    include_zero: bool = Query(False, description="包含零庫存項目"),
    category: Optional[str] = Query(None, description="篩選類別: CONTROLLED, GENERAL")
):
    """
    取得藥車庫存清單

    Returns:
        - items: 庫存項目清單
        - summary: 統計摘要 (總品項、管制藥數、低庫存數)
    """
    pass

@router.get("/carts/{cart_id}/inventory/{medicine_code}")
async def get_cart_inventory_item(cart_id: str, medicine_code: str):
    """
    取得單一藥品在藥車的庫存詳情

    Returns:
        - quantity: 當前數量
        - transactions: 最近交易紀錄
        - dispatch_history: 調撥歷史
    """
    pass

@router.post("/carts/{cart_id}/inventory/use")
async def use_cart_inventory(
    cart_id: str,
    request: CartInventoryUseRequest
):
    """
    使用藥車庫存 (用藥時扣減)

    Args:
        medicine_code: 藥品代碼
        quantity: 使用數量
        case_id: 關聯案件
        medication_event_id: 關聯用藥事件
        actor_id: 執行人員
        witness_id: 見證人 (管制藥必填)

    Returns:
        - success: 是否成功
        - new_quantity: 扣減後數量
        - txn_id: 交易 ID
    """
    pass

@router.get("/carts/{cart_id}/inventory/controlled")
async def get_cart_controlled_drugs(cart_id: str):
    """
    取得藥車管制藥清單 (for Holdings Tab)

    Returns:
        - holdings: 管制藥持有清單
        - total_items: 管制藥品項數
        - recent_transactions: 最近管制藥交易
    """
    pass
```

### 3.2 調撥 API

```python
@router.post("/dispatches")
async def create_dispatch(request: DispatchRequest):
    """
    建立調撥申請 (中央藥局 -> 藥車)
    """
    pass

@router.post("/dispatches/{dispatch_id}/confirm")
async def confirm_dispatch(dispatch_id: str, actor_id: str):
    """
    確認調撥 (藥車收貨)
    - 更新 cart_inventory
    - 扣減 medicines.current_stock
    - 建立 cart_inventory_transactions
    """
    pass

@router.get("/dispatches")
async def list_dispatches(
    cart_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20
):
    """
    取得調撥記錄
    """
    pass
```

### 3.3 整合用藥 API (修改現有)

```python
@router.post("/cases/{case_id}/medication/with-cart")
async def add_medication_with_cart_deduction(
    case_id: str,
    request: MedicationWithCartRequest
):
    """
    用藥記錄 v2.0 - 整合藥車庫存扣減

    Flow:
    1. 記錄 timeline event
    2. 記錄 billing event
    3. 扣減 cart_inventory (非 medicines)
    4. 記錄 cart_inventory_transactions
    5. 管制藥: 記錄 controlled_drug_log

    Args:
        cart_id: 藥車 ID (必填)
        medicine_code: 藥品代碼
        dose: 劑量
        ... 其他欄位同 MedicationWithBillingRequest
    """
    pass
```

---

## 4. Anesthesia PWA UI Changes

### 4.1 給藥 Modal 修改

```javascript
// 現有: 顯示 medicines.current_stock
// 新增: 顯示 cart_inventory.quantity

async loadQuickDrugsWithCartInventory() {
    // 改用新 API，傳入當前藥車 ID
    const cartId = this.currentCartId || 'CART-ANES-001';
    const res = await apiFetch(`${API_BASE}/carts/${cartId}/inventory?category=ANESTHESIA`);

    // 返回格式:
    // {
    //   items: [
    //     {
    //       medicine_code: "BC90567209",
    //       medicine_name: "Fentanyl 100mcg/2mL",
    //       cart_quantity: 8,        // 藥車庫存
    //       central_stock: 50,       // 中央庫存 (參考)
    //       stock_status: "OK",
    //       is_controlled: true,
    //       last_dispatch: "2026-01-20T08:00:00Z"
    //     }
    //   ]
    // }
}
```

### 4.2 管制藥 Tab (Holdings Tab)

```html
<!-- 管制藥持有清單 -->
<div id="controlledDrugsTab" class="tab-content">
    <div class="holdings-header">
        <h3>管制藥持有餘額</h3>
        <span class="cart-badge">藥車: CART-ANES-001</span>
    </div>

    <div class="holdings-list" id="holdingsList">
        <!-- Dynamic content -->
        <div class="holding-item">
            <div class="holding-drug">
                <span class="drug-name">Fentanyl 100mcg/2mL</span>
                <span class="drug-level">Level 2</span>
            </div>
            <div class="holding-balance">
                <span class="balance-qty">8</span>
                <span class="balance-unit">支</span>
            </div>
            <div class="holding-actions">
                <button onclick="showHoldingHistory('BC90567209')">歷史</button>
            </div>
        </div>
    </div>

    <!-- 最近交易 -->
    <div class="recent-transactions">
        <h4>最近交易</h4>
        <div id="recentControlledTxns">
            <!-- Dynamic content -->
        </div>
    </div>
</div>
```

### 4.3 庫存來源顯示

```html
<!-- 給藥按鈕增加調撥資訊 tooltip -->
<button class="med-btn"
        :title="`庫存: ${drug.cart_quantity} (最後調撥: ${drug.last_dispatch})`">
    <span class="med-name">${drug.medicine_name}</span>
    <span class="med-stock">${drug.cart_quantity}</span>
    <span class="med-source" v-if="drug.last_dispatch">
        📦 ${formatDate(drug.last_dispatch)}
    </span>
</button>
```

---

## 5. Vercel Demo Seeder

### 5.1 啟動時預載藥品庫存

```python
# main.py 修改

IS_VERCEL = os.environ.get("VERCEL") == "1"

if IS_VERCEL:
    # ... existing init ...

    # Phase 8: Seed cart inventory for demo
    try:
        seed_demo_cart_inventory()
        print("[MIRS] Demo cart inventory seeded")
    except Exception as e:
        print(f"[MIRS] Cart inventory seed warning: {e}")
```

### 5.2 Demo Cart Inventory Seeder

```python
# seeder_cart_inventory.py

def seed_demo_cart_inventory():
    """
    為 Vercel Demo 預載藥車庫存
    """

    # 建立 Demo 藥車
    demo_cart = {
        "id": "CART-ANES-DEMO",
        "name": "麻醉藥車 Demo",
        "cart_type": "ANESTHESIA",
        "location": "OR-DEMO",
        "status": "ACTIVE"
    }

    # Demo 庫存
    demo_inventory = [
        {"medicine_code": "PROP", "quantity": 20, "is_controlled": False},
        {"medicine_code": "FENT", "quantity": 10, "is_controlled": True},
        {"medicine_code": "MIDA", "quantity": 8, "is_controlled": True},
        {"medicine_code": "KETA", "quantity": 5, "is_controlled": True},
        {"medicine_code": "ROCU", "quantity": 15, "is_controlled": False},
        {"medicine_code": "SUXI", "quantity": 10, "is_controlled": False},
        {"medicine_code": "ATRO", "quantity": 25, "is_controlled": False},
        {"medicine_code": "EPHE", "quantity": 20, "is_controlled": False},
        {"medicine_code": "PHEN", "quantity": 15, "is_controlled": False},
        {"medicine_code": "SUGA", "quantity": 6, "is_controlled": False},
        {"medicine_code": "NEOS", "quantity": 20, "is_controlled": False},
        {"medicine_code": "LIDO", "quantity": 30, "is_controlled": False},
    ]

    # 建立初始調撥記錄
    demo_dispatch = {
        "dispatch_id": "DISP-DEMO-001",
        "dispatch_type": "STANDARD",
        "to_cart_id": "CART-ANES-DEMO",
        "status": "CONFIRMED",
        "requested_by": "DEMO-PHARMACY",
        "confirmed_by": "DEMO-ANES-001",
        "confirmed_at": datetime.now().isoformat()
    }

    # Insert into database...
```

---

## 6. Implementation Phases

### Phase 8.1: Database Schema (Day 1)

- [ ] 建立 `cart_inventory_transactions` 表
- [ ] 建立 `inventory_dispatches` 表
- [ ] 建立 `inventory_dispatch_items` 表
- [ ] Migration script: `add_cart_inventory_transactions.sql`

### Phase 8.2: Cart Inventory API (Day 1-2)

- [ ] `GET /carts/{id}/inventory` - 藥車庫存清單
- [ ] `GET /carts/{id}/inventory/{code}` - 單一藥品詳情
- [ ] `POST /carts/{id}/inventory/use` - 使用庫存
- [ ] `GET /carts/{id}/inventory/controlled` - 管制藥清單

### Phase 8.3: Dispatch API (Day 2)

- [ ] `POST /dispatches` - 建立調撥
- [ ] `POST /dispatches/{id}/confirm` - 確認調撥
- [ ] `GET /dispatches` - 調撥清單

### Phase 8.4: Medication API v2 (Day 2-3)

- [ ] 修改 `add_medication_with_billing` 整合藥車扣減
- [ ] 新增 `add_medication_with_cart` endpoint
- [ ] 更新 `quick-drugs-with-inventory` 讀取藥車庫存

### Phase 8.5: Anesthesia PWA UI (Day 3-4)

- [ ] 修改給藥 Modal 顯示藥車庫存
- [ ] 實作管制藥 Tab (Holdings)
- [ ] 新增庫存來源 tooltip
- [ ] 新增交易歷史 Modal

### Phase 8.6: Vercel Demo Seeder (Day 4)

- [ ] 建立 `seeder_cart_inventory.py`
- [ ] 修改 `main.py` 啟動時調用
- [ ] 測試 Vercel demo 庫存顯示

---

## 7. Data Flow Diagrams

### 7.1 用藥流程 (含藥車扣減)

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ Anesthesia  │     │    Backend      │     │    Database      │
│    PWA      │     │    API          │     │                  │
└──────┬──────┘     └────────┬────────┘     └────────┬─────────┘
       │                     │                       │
       │ POST /medication/   │                       │
       │   with-cart         │                       │
       │ ─────────────────>  │                       │
       │                     │                       │
       │                     │ 1. Validate cart      │
       │                     │ ─────────────────────>│
       │                     │                       │
       │                     │ 2. Check cart_inventory
       │                     │ ─────────────────────>│
       │                     │    quantity >= dose   │
       │                     │ <─────────────────────│
       │                     │                       │
       │                     │ 3. INSERT timeline    │
       │                     │ ─────────────────────>│
       │                     │                       │
       │                     │ 4. INSERT billing     │
       │                     │ ─────────────────────>│
       │                     │                       │
       │                     │ 5. UPDATE cart_inv    │
       │                     │    quantity -= dose   │
       │                     │ ─────────────────────>│
       │                     │                       │
       │                     │ 6. INSERT cart_inv_txn│
       │                     │ ─────────────────────>│
       │                     │                       │
       │                     │ 7. (管制藥) INSERT    │
       │                     │    controlled_drug_log│
       │                     │ ─────────────────────>│
       │                     │                       │
       │    Response         │                       │
       │ <─────────────────  │                       │
       │                     │                       │
```

### 7.2 調撥流程

```
┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  Pharmacy │    │ Pharmacy  │    │Anesthesia │    │  Database │
│   Staff   │    │   PWA     │    │   PWA     │    │           │
└─────┬─────┘    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
      │                │                │                │
      │ Create dispatch│                │                │
      │ ──────────────>│                │                │
      │                │                │                │
      │                │ POST /dispatches               │
      │                │ ─────────────────────────────> │
      │                │                │                │
      │                │ status=PENDING │                │
      │                │ <───────────────────────────── │
      │                │                │                │
      │                │   Notify       │                │
      │                │ ─────────────> │                │
      │                │                │                │
      │                │                │ Receive goods  │
      │                │                │ ──────────────>│
      │                │                │                │
      │                │                │ POST /confirm  │
      │                │                │ ──────────────>│
      │                │                │                │
      │                │                │  - UPDATE cart_inventory
      │                │                │  - UPDATE medicines
      │                │                │  - INSERT txn  │
      │                │                │ <──────────────│
      │                │                │                │
```

---

## 8. Testing Checklist

### 8.1 Unit Tests

- [ ] `test_cart_inventory_deduction` - 藥車庫存扣減
- [ ] `test_controlled_drug_witness_required` - 管制藥見證
- [ ] `test_dispatch_confirm_updates_stock` - 調撥確認更新庫存
- [ ] `test_negative_cart_inventory_warning` - 負庫存警告

### 8.2 Integration Tests

- [ ] 完整用藥流程 (PWA -> API -> DB)
- [ ] 調撥流程 (Pharmacy -> Cart)
- [ ] 管制藥交易歷史追溯

### 8.3 Vercel Demo Tests

- [ ] 藥車庫存正確顯示
- [ ] 給藥後庫存減少
- [ ] 管制藥 Tab 顯示餘額
- [ ] 交易歷史可查詢

---

## 9. Migration Notes

### 9.1 從現有系統遷移

1. **現有 `medicines` 庫存**: 保留作為「中央藥局」庫存
2. **新增 `cart_inventory`**: 作為「藥車」庫存
3. **歷史用藥記錄**: 不影響，維持現有 `timeline_events`
4. **計費記錄**: 不影響，維持現有 `anesthesia_billing_events`

### 9.2 Breaking Changes

| 變更 | 影響 | 處理方式 |
|------|------|---------|
| 用藥需指定 cart_id | PWA 需更新 | 新增 cart selector |
| 庫存從 cart_inventory 讀取 | API response 格式變更 | 向下相容，同時返回兩者 |

---

## 10. Future Considerations

### 10.1 Phase 9: 藥車交班

- 交班時清點藥車庫存
- 產生交班報表
- 差異處理 (溢缺)

### 10.2 Phase 10: 效期管理

- 效期警告 (到期前 30 天)
- 近效期優先使用 (FEFO)
- 過期藥品報廢流程

### 10.3 Phase 11: 多藥車支援

- 一人管多車
- 藥車間調撥
- 動態藥車分配

---

## Appendix A: Demo Data Structure

```json
{
  "cart": {
    "id": "CART-ANES-DEMO",
    "name": "麻醉藥車 Demo",
    "type": "ANESTHESIA"
  },
  "inventory": [
    {
      "medicine_code": "FENT",
      "medicine_name": "Fentanyl 100mcg/2mL",
      "quantity": 10,
      "min_quantity": 2,
      "is_controlled": true,
      "controlled_level": 2,
      "last_dispatch": "2026-01-20T08:00:00Z",
      "dispatch_id": "DISP-DEMO-001"
    }
  ],
  "recent_transactions": [
    {
      "txn_id": "CITXN-20260121-0001",
      "txn_type": "DISPATCH",
      "medicine_code": "FENT",
      "quantity_change": 10,
      "created_at": "2026-01-20T08:00:00Z"
    }
  ]
}
```

---

## Appendix B: Error Codes

| Code | Message | Description |
|------|---------|-------------|
| `CART_NOT_FOUND` | 藥車不存在 | cart_id 無效 |
| `INSUFFICIENT_CART_STOCK` | 藥車庫存不足 | quantity < requested |
| `CONTROLLED_WITNESS_REQUIRED` | 管制藥需見證人 | is_controlled=true 但無 witness_id |
| `DISPATCH_ALREADY_CONFIRMED` | 調撥已確認 | 重複確認 |
| `MEDICINE_NOT_IN_CART` | 藥品不在藥車 | cart_inventory 無此藥品 |

---

*Document End*
