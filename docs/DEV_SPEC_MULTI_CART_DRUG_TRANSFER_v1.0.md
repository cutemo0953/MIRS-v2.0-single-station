# DEV_SPEC: Multi-Cart & Drug Transfer v1.0

## Document Info
| Field | Value |
|-------|-------|
| **Version** | 1.0 |
| **Date** | 2026-01-21 |
| **Author** | Claude Opus 4.5 |
| **Status** | Draft |
| **Depends On** | DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.3.md, DEV_SPEC_ANESTHESIA_INVENTORY_INTEGRATION_v1.1.md |

---

## 1. Executive Summary

### 1.1 Problem Statement

目前 Anesthesia PWA 設計為「一次一台刀、一位麻護」的單人模式，在實務場景中存在以下問題：

| 問題 | 現況 | 影響 |
|------|------|------|
| **單藥車模型** | 所有案件共用 `CART-ANES-001` | 多人同時操作時庫存顯示不同步 |
| **無法追蹤藥車歸屬** | 案件未綁定特定藥車 | 無法區分 OR-1 和 OR-2 的藥品消耗 |
| **剩藥無法交換** | 只能銷毀或退回 | 造成浪費，不符實務 |
| **管制藥帳不平** | 移轉後無記錄 | Case A 結案時 balance ≠ 0 |
| **審計斷鏈** | 移轉過程無見證 | 管制藥追蹤失敗 |

### 1.2 Solution Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Multi-Cart Architecture                                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Layer 2: Station Pharmacy (medicines)                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │   中央藥局庫存                                                │  │
│  └───────────────────────────┬──────────────────────────────────┘  │
│                              │ DISPATCH                             │
│              ┌───────────────┼───────────────┐                      │
│              ▼               ▼               ▼                      │
│  Layer 3: Multiple Carts                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ CART-OR-01   │   │ CART-OR-02   │   │ CART-OR-03   │            │
│  │ OR-1 藥車    │   │ OR-2 藥車    │   │ OR-3 藥車    │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         │                  │                  │                     │
│         ▼                  ▼                  ▼                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ Case A       │   │ Case B       │   │ Case C       │            │
│  │ Nurse 張     │   │ Nurse 李     │   │ Nurse 王     │            │
│  └──────────────┘   └──────────────┘   └──────────────┘            │
│         │                  ▲                                        │
│         │    TRANSFER      │                                        │
│         └──────────────────┘                                        │
│         (剩藥移轉，需見證)                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Multi-Cart Model

### 2.1 藥車類型

```sql
-- 藥車類型定義
CREATE TABLE cart_types (
    type_code TEXT PRIMARY KEY,        -- OR, EMERGENCY, PACU, MOBILE
    type_name TEXT NOT NULL,
    description TEXT,
    default_inventory_template TEXT    -- JSON: 預設庫存配置
);

INSERT INTO cart_types VALUES
    ('OR', '手術室藥車', '固定於特定手術室', '{"FENT": 10, "MIDA": 8, "PROP": 20}'),
    ('MOBILE', '流動藥車', '可跨手術室使用', '{"FENT": 5, "MIDA": 5, "PROP": 10}'),
    ('EMERGENCY', '急救藥車', '急救專用', '{"EPI": 10, "ATRO": 10, "AMIO": 5}'),
    ('PACU', '恢復室藥車', 'PACU 專用', '{"FENT": 5, "ONDAN": 10}');
```

### 2.2 藥車表擴充

```sql
-- 擴充 drug_carts 表
ALTER TABLE drug_carts ADD COLUMN cart_type TEXT DEFAULT 'OR'
    REFERENCES cart_types(type_code);
ALTER TABLE drug_carts ADD COLUMN assigned_or TEXT;      -- OR-01, OR-02
ALTER TABLE drug_carts ADD COLUMN is_active BOOLEAN DEFAULT 1;
ALTER TABLE drug_carts ADD COLUMN current_nurse_id TEXT; -- 當前負責人

-- 範例資料
INSERT INTO drug_carts (id, name, cart_type, assigned_or, location, status) VALUES
    ('CART-OR-01', 'OR-1 藥車', 'OR', 'OR-01', 'OR-1', 'ACTIVE'),
    ('CART-OR-02', 'OR-2 藥車', 'OR', 'OR-02', 'OR-2', 'ACTIVE'),
    ('CART-OR-03', 'OR-3 藥車', 'OR', 'OR-03', 'OR-3', 'ACTIVE'),
    ('CART-MOBILE-01', '流動藥車 #1', 'MOBILE', NULL, 'Storage', 'ACTIVE');
```

### 2.3 案件-藥車關聯

```sql
-- 擴充 anesthesia_cases 表
ALTER TABLE anesthesia_cases ADD COLUMN cart_id TEXT REFERENCES drug_carts(id);
ALTER TABLE anesthesia_cases ADD COLUMN nurse_id TEXT;
ALTER TABLE anesthesia_cases ADD COLUMN nurse_name TEXT;

-- 案件開始時自動綁定
-- 規則: 根據 OR 編號自動選擇對應藥車，或手動指定
```

### 2.4 藥車選擇邏輯

```python
def get_cart_for_case(or_room: str, nurse_id: str) -> str:
    """
    根據手術室和護理師決定使用哪台藥車

    規則:
    1. 優先使用該 OR 的固定藥車
    2. 若固定藥車不可用，使用流動藥車
    3. 若護理師已在使用某藥車，沿用該藥車
    """
    # 1. 檢查護理師是否已有進行中案件
    existing = get_nurse_active_cases(nurse_id)
    if existing:
        return existing[0].cart_id  # 沿用現有藥車

    # 2. 嘗試使用 OR 固定藥車
    or_cart = get_cart_by_or(or_room)
    if or_cart and or_cart.status == 'ACTIVE':
        return or_cart.id

    # 3. Fallback 到流動藥車
    mobile_cart = get_available_mobile_cart()
    if mobile_cart:
        return mobile_cart.id

    raise CartNotAvailableError(f"No cart available for {or_room}")
```

---

## 3. Drug Transfer System

### 3.1 移轉類型

| 類型 | 說明 | 管制藥見證 |
|------|------|-----------|
| `CASE_TO_CASE` | 案件間移轉 (最常見) | 必須 |
| `CASE_TO_CART` | 退回藥車 (部分使用) | 必須 |
| `CART_TO_CASE` | 從藥車補領 | 必須 |
| `CART_TO_CART` | 藥車間調撥 | 必須 |

### 3.2 Database Schema

```sql
-- ============================================================================
-- 藥品移轉記錄表
-- ============================================================================

CREATE TABLE drug_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 移轉識別
    transfer_id TEXT UNIQUE NOT NULL,      -- XFER-20260121-XXXX
    transfer_type TEXT NOT NULL,           -- CASE_TO_CASE, CASE_TO_CART, etc.

    -- 來源
    from_type TEXT NOT NULL,               -- CASE, CART
    from_case_id TEXT,                     -- 若 from_type=CASE
    from_cart_id TEXT,                     -- 若 from_type=CART
    from_nurse_id TEXT NOT NULL,
    from_nurse_name TEXT,

    -- 目的
    to_type TEXT NOT NULL,                 -- CASE, CART
    to_case_id TEXT,                       -- 若 to_type=CASE
    to_cart_id TEXT,                       -- 若 to_type=CART
    to_nurse_id TEXT,                      -- 若 to_type=CASE
    to_nurse_name TEXT,

    -- 藥品資訊
    medicine_code TEXT NOT NULL,
    medicine_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit TEXT DEFAULT 'amp',

    -- 管制藥資訊
    is_controlled BOOLEAN DEFAULT 0,
    controlled_level INTEGER,

    -- 見證 (管制藥必填)
    witness_id TEXT,
    witness_name TEXT,
    witness_role TEXT,                     -- NURSE, PHARMACIST

    -- 狀態
    status TEXT DEFAULT 'PENDING',         -- PENDING, CONFIRMED, REJECTED, CANCELLED

    -- 雙方確認 (CASE_TO_CASE 需要)
    from_confirmed BOOLEAN DEFAULT 0,
    from_confirmed_at TEXT,
    to_confirmed BOOLEAN DEFAULT 0,
    to_confirmed_at TEXT,

    -- 拒絕/取消原因
    reject_reason TEXT,

    -- 備註
    remarks TEXT,

    -- 時間戳
    initiated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,

    -- 約束
    CHECK(transfer_type IN ('CASE_TO_CASE', 'CASE_TO_CART', 'CART_TO_CASE', 'CART_TO_CART')),
    CHECK(from_type IN ('CASE', 'CART')),
    CHECK(to_type IN ('CASE', 'CART')),
    CHECK(status IN ('PENDING', 'CONFIRMED', 'REJECTED', 'CANCELLED'))
);

-- 索引
CREATE INDEX idx_transfers_from_case ON drug_transfers(from_case_id);
CREATE INDEX idx_transfers_to_case ON drug_transfers(to_case_id);
CREATE INDEX idx_transfers_status ON drug_transfers(status);
CREATE INDEX idx_transfers_medicine ON drug_transfers(medicine_code);
CREATE INDEX idx_transfers_initiated ON drug_transfers(initiated_at);

-- ============================================================================
-- 移轉通知表 (推播/即時通知用)
-- ============================================================================

CREATE TABLE transfer_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    transfer_id TEXT NOT NULL REFERENCES drug_transfers(transfer_id),

    -- 通知對象
    target_nurse_id TEXT NOT NULL,
    target_type TEXT NOT NULL,             -- SENDER, RECEIVER

    -- 通知狀態
    notification_type TEXT NOT NULL,       -- TRANSFER_REQUEST, TRANSFER_CONFIRMED, TRANSFER_REJECTED
    is_read BOOLEAN DEFAULT 0,
    read_at TEXT,

    -- 時間
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notifications_nurse ON transfer_notifications(target_nurse_id, is_read);
```

### 3.3 移轉狀態機

```
┌─────────────────────────────────────────────────────────────────────┐
│  Drug Transfer State Machine                                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐                                                       │
│  │ PENDING  │ ◄─── 發起移轉 (from_confirmed=true)                   │
│  └────┬─────┘                                                       │
│       │                                                             │
│       ├─────────────────────┐                                       │
│       │                     │                                       │
│       ▼                     ▼                                       │
│  ┌──────────┐         ┌──────────┐                                  │
│  │CONFIRMED │         │ REJECTED │                                  │
│  │          │         │          │                                  │
│  │ 接收方   │         │ 接收方   │                                  │
│  │ 確認     │         │ 拒絕     │                                  │
│  └────┬─────┘         └──────────┘                                  │
│       │                     ▲                                       │
│       │                     │                                       │
│       │               ┌──────────┐                                  │
│       │               │CANCELLED │ ◄─── 發起方在 PENDING 時取消     │
│       │               └──────────┘                                  │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ 帳務更新:                                                     │  │
│  │ - From Case/Cart: holdings -= quantity                        │  │
│  │ - To Case/Cart: holdings += quantity                          │  │
│  │ - cart_inventory_transactions: TRANSFER_OUT, TRANSFER_IN      │  │
│  │ - controlled_drug_log: 管制藥審計記錄                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Endpoints

### 4.1 藥車管理 API

```python
# routes/anesthesia.py

# ============================================================================
# Phase 9: Multi-Cart Management
# ============================================================================

@router.get("/carts")
async def list_carts(
    cart_type: Optional[str] = None,
    status: Optional[str] = Query("ACTIVE"),
    assigned_or: Optional[str] = None
):
    """
    列出所有藥車

    Args:
        cart_type: 篩選類型 (OR, MOBILE, EMERGENCY)
        status: 篩選狀態 (ACTIVE, MAINTENANCE)
        assigned_or: 篩選指定 OR
    """
    pass

@router.get("/carts/available")
async def get_available_carts(or_room: str):
    """
    取得指定 OR 可用的藥車

    Returns:
        primary_cart: 該 OR 的固定藥車
        mobile_carts: 可用的流動藥車
    """
    pass

@router.post("/carts/{cart_id}/assign")
async def assign_cart_to_nurse(
    cart_id: str,
    nurse_id: str = Query(...),
    nurse_name: str = Query(...)
):
    """
    將藥車指派給護理師
    """
    pass

@router.post("/carts/{cart_id}/release")
async def release_cart(cart_id: str, nurse_id: str = Query(...)):
    """
    護理師釋放藥車 (交班或下班)
    """
    pass
```

### 4.2 藥品移轉 API

```python
# ============================================================================
# Phase 9: Drug Transfer API
# ============================================================================

class TransferRequest(BaseModel):
    transfer_type: str                    # CASE_TO_CASE, CASE_TO_CART, etc.

    # 來源
    from_case_id: Optional[str] = None
    from_cart_id: Optional[str] = None

    # 目的
    to_case_id: Optional[str] = None
    to_cart_id: Optional[str] = None
    to_nurse_id: Optional[str] = None

    # 藥品
    medicine_code: str
    quantity: int

    # 見證 (管制藥必填)
    witness_id: Optional[str] = None
    witness_name: Optional[str] = None

    remarks: Optional[str] = None


@router.post("/transfers")
async def initiate_transfer(
    request: TransferRequest,
    actor_id: str = Query(..., description="發起人 ID"),
    actor_name: str = Query(None, description="發起人姓名")
):
    """
    發起藥品移轉

    Flow:
    1. 驗證來源有足夠藥品
    2. 驗證管制藥有見證人
    3. 建立移轉記錄 (status=PENDING)
    4. 發送通知給接收方
    5. 發起方自動確認 (from_confirmed=true)

    Returns:
        transfer_id: 移轉單號
        status: PENDING
        notification_sent: 是否已通知接收方
    """
    pass


@router.post("/transfers/{transfer_id}/confirm")
async def confirm_transfer(
    transfer_id: str,
    actor_id: str = Query(..., description="確認人 ID")
):
    """
    接收方確認移轉

    Flow:
    1. 驗證 actor_id 是接收方
    2. 更新 to_confirmed = true
    3. 執行帳務異動:
       - 扣減來源 holdings
       - 增加目的 holdings
       - 寫入 cart_inventory_transactions
       - 管制藥寫入 controlled_drug_log
    4. 更新 status = CONFIRMED

    Returns:
        status: CONFIRMED
        from_holdings_after: 來源方剩餘
        to_holdings_after: 接收方持有
    """
    pass


@router.post("/transfers/{transfer_id}/reject")
async def reject_transfer(
    transfer_id: str,
    actor_id: str = Query(...),
    reason: str = Query(..., description="拒絕原因")
):
    """
    接收方拒絕移轉

    Flow:
    1. 驗證 actor_id 是接收方
    2. 更新 status = REJECTED
    3. 記錄拒絕原因
    4. 通知發起方

    Returns:
        status: REJECTED
        reason: 拒絕原因
    """
    pass


@router.post("/transfers/{transfer_id}/cancel")
async def cancel_transfer(
    transfer_id: str,
    actor_id: str = Query(...)
):
    """
    發起方取消移轉 (僅 PENDING 狀態可取消)

    Returns:
        status: CANCELLED
    """
    pass


@router.get("/transfers")
async def list_transfers(
    case_id: Optional[str] = None,
    cart_id: Optional[str] = None,
    nurse_id: Optional[str] = None,
    status: Optional[str] = None,
    direction: Optional[str] = Query(None, description="IN, OUT, ALL"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    查詢移轉記錄

    Args:
        case_id: 篩選特定案件的移轉
        cart_id: 篩選特定藥車的移轉
        nurse_id: 篩選特定護理師的移轉
        status: 篩選狀態
        direction: IN=轉入, OUT=轉出, ALL=全部
    """
    pass


@router.get("/transfers/{transfer_id}")
async def get_transfer(transfer_id: str):
    """
    取得移轉詳情
    """
    pass


@router.get("/transfers/pending")
async def get_pending_transfers(nurse_id: str = Query(...)):
    """
    取得待處理的移轉 (for 通知 badge)

    Returns:
        incoming: 待接收的移轉
        outgoing: 待對方確認的移轉
        total_pending: 總待處理數
    """
    pass
```

### 4.3 帳務整合 API

```python
@router.get("/cases/{case_id}/holdings/with-transfers")
async def get_case_holdings_with_transfers(case_id: str):
    """
    取得案件持有量 (含移轉記錄)

    Returns:
        holdings: [
            {
                drug_code, drug_name, controlled_level,
                issued: 原始領用,
                used: 已使用,
                transferred_out: 移轉出,
                transferred_in: 移轉入,
                balance: 餘額
            }
        ]
        transfers: 相關移轉記錄
        is_reconcilable: 是否可結案 (balance=0)
    """
    pass


@router.get("/cases/{case_id}/reconciliation/preview")
async def preview_reconciliation(case_id: str):
    """
    預覽結案狀態 (檢查是否有未完成移轉)

    Returns:
        can_close: 是否可結案
        pending_transfers: 待處理移轉
        unbalanced_drugs: 帳不平的藥品
        warnings: 警告訊息
    """
    pass
```

---

## 5. UI Design

### 5.1 案件開始 - 藥車選擇

```html
<!-- 案件開始時的藥車選擇 Modal -->
<div class="cart-select-modal">
    <h3>選擇藥車</h3>

    <!-- 自動建議 -->
    <div class="suggested-cart">
        <div class="cart-card recommended">
            <span class="badge">建議</span>
            <h4>OR-1 藥車</h4>
            <p>固定於 OR-1</p>
            <div class="inventory-preview">
                <span>Fentanyl: 10</span>
                <span>Midazolam: 8</span>
            </div>
            <button class="btn-primary" onclick="selectCart('CART-OR-01')">
                使用此藥車
            </button>
        </div>
    </div>

    <!-- 其他可用藥車 -->
    <div class="other-carts">
        <h4>其他可用藥車</h4>
        <div class="cart-card">
            <h4>流動藥車 #1</h4>
            <p>目前位於儲藏室</p>
            <button onclick="selectCart('CART-MOBILE-01')">選擇</button>
        </div>
    </div>
</div>
```

### 5.2 剩藥處理介面

```html
<!-- 案件結束時的剩藥處理 -->
<div class="leftover-drugs-modal">
    <h3>剩藥處理</h3>
    <p class="case-info">Case: ANES-2026-001 | 護理師: 張小華</p>

    <!-- 剩藥清單 -->
    <div class="leftover-list">
        <div class="leftover-item controlled">
            <div class="drug-info">
                <span class="controlled-badge">Level 2</span>
                <span class="drug-name">Fentanyl 100mcg/2mL</span>
                <span class="quantity">剩餘: 1 支</span>
            </div>

            <div class="actions">
                <button class="btn-danger" onclick="showWasteModal('FENT')">
                    🗑️ 銷毀
                </button>
                <button class="btn-secondary" onclick="returnToCart('FENT')">
                    📦 退回藥車
                </button>
                <button class="btn-primary" onclick="showTransferModal('FENT')">
                    ➡️ 移轉
                </button>
            </div>
        </div>

        <div class="leftover-item">
            <div class="drug-info">
                <span class="drug-name">Propofol 200mg/20mL</span>
                <span class="quantity">剩餘: 2 支</span>
            </div>
            <div class="actions">
                <button onclick="returnToCart('PROP')">📦 退回藥車</button>
                <button onclick="showTransferModal('PROP')">➡️ 移轉</button>
            </div>
        </div>
    </div>
</div>
```

### 5.3 移轉發起介面

```html
<!-- 移轉 Modal -->
<div class="transfer-modal">
    <h3>移轉藥品</h3>

    <div class="transfer-drug">
        <span class="controlled-badge">Level 2</span>
        <span>Fentanyl 100mcg/2mL</span>
        <input type="number" value="1" min="1" max="3" id="transferQty">
        <span>支</span>
    </div>

    <!-- 選擇接收方 -->
    <div class="transfer-to">
        <h4>移轉給</h4>

        <!-- 進行中的案件 -->
        <div class="active-cases">
            <h5>進行中案件</h5>
            <div class="case-option" onclick="selectRecipient('ANES-2026-002', 'nurse-002')">
                <div class="case-info">
                    <span class="case-id">ANES-2026-002</span>
                    <span class="patient">王大明 / ORIF</span>
                </div>
                <div class="nurse-info">
                    <span>李小美</span>
                    <span class="or">OR-2</span>
                </div>
            </div>
            <div class="case-option" onclick="selectRecipient('ANES-2026-003', 'nurse-003')">
                <div class="case-info">
                    <span class="case-id">ANES-2026-003</span>
                    <span class="patient">陳小花 / TKR</span>
                </div>
                <div class="nurse-info">
                    <span>王小華</span>
                    <span class="or">OR-3</span>
                </div>
            </div>
        </div>

        <!-- 或退回藥車 -->
        <div class="cart-option">
            <h5>或退回藥車</h5>
            <div class="cart-select" onclick="selectRecipient(null, null, 'CART-OR-01')">
                <span>OR-1 藥車</span>
            </div>
        </div>
    </div>

    <!-- 管制藥見證人 (必填) -->
    <div class="witness-section required">
        <h4>見證人 <span class="required-mark">*</span></h4>
        <p class="hint">管制藥移轉需要見證人</p>
        <select id="witnessSelect">
            <option value="">選擇見證人</option>
            <option value="nurse-004">陳護理師 (OR-4)</option>
            <option value="nurse-005">林護理師 (PACU)</option>
            <option value="pharm-001">藥師 黃小明</option>
        </select>
    </div>

    <!-- 備註 -->
    <div class="remarks">
        <h4>備註</h4>
        <textarea placeholder="選填"></textarea>
    </div>

    <div class="actions">
        <button class="btn-secondary" onclick="closeModal()">取消</button>
        <button class="btn-primary" onclick="submitTransfer()">確認移轉</button>
    </div>
</div>
```

### 5.4 接收通知介面

```html
<!-- 收到移轉通知 (Toast/Modal) -->
<div class="transfer-notification incoming">
    <div class="notification-header">
        <span class="icon">📦</span>
        <span class="title">收到藥品移轉</span>
        <span class="time">剛剛</span>
    </div>

    <div class="notification-body">
        <div class="from-info">
            <span>來自: 張小華 (ANES-2026-001)</span>
        </div>
        <div class="drug-info">
            <span class="controlled-badge">Level 2</span>
            <span>Fentanyl 100mcg/2mL × 1 支</span>
        </div>
        <div class="witness-info">
            <span>見證人: 陳護理師</span>
        </div>
    </div>

    <div class="notification-actions">
        <button class="btn-danger" onclick="rejectTransfer('XFER-001')">
            拒絕
        </button>
        <button class="btn-primary" onclick="confirmTransfer('XFER-001')">
            確認接收
        </button>
    </div>
</div>
```

### 5.5 Holdings Tab 更新

```html
<!-- 管制藥 Holdings Tab (含移轉記錄) -->
<div class="holdings-tab">
    <h3>管制藥持有</h3>

    <div class="holdings-list">
        <div class="holding-item">
            <div class="drug-header">
                <span class="level">Level 2</span>
                <span class="name">Fentanyl 100mcg/2mL</span>
            </div>

            <div class="holding-breakdown">
                <div class="row">
                    <span>領用</span>
                    <span class="qty">3 支</span>
                </div>
                <div class="row">
                    <span>使用</span>
                    <span class="qty negative">-2 支</span>
                </div>
                <div class="row transfer-out">
                    <span>移轉出 → ANES-002</span>
                    <span class="qty negative">-1 支</span>
                </div>
                <div class="row transfer-in">
                    <span>移轉入 ← ANES-003</span>
                    <span class="qty positive">+1 支</span>
                </div>
                <div class="row balance">
                    <span>餘額</span>
                    <span class="qty">1 支</span>
                </div>
            </div>
        </div>
    </div>

    <!-- 移轉歷史 -->
    <div class="transfer-history">
        <h4>移轉記錄</h4>
        <div class="transfer-item out">
            <span class="direction">➡️ 轉出</span>
            <span class="drug">Fentanyl × 1</span>
            <span class="target">→ 李小美 (ANES-002)</span>
            <span class="time">10:30</span>
            <span class="status confirmed">已確認</span>
        </div>
        <div class="transfer-item in">
            <span class="direction">⬅️ 轉入</span>
            <span class="drug">Fentanyl × 1</span>
            <span class="source">← 王小華 (ANES-003)</span>
            <span class="time">11:15</span>
            <span class="status confirmed">已確認</span>
        </div>
    </div>
</div>
```

---

## 6. Controlled Drug Audit Trail

### 6.1 審計記錄擴充

```sql
-- 擴充 controlled_drug_log 支援移轉
ALTER TABLE controlled_drug_log ADD COLUMN transaction_type TEXT DEFAULT 'USE';
-- transaction_type: ISSUE, USE, WASTE, TRANSFER_OUT, TRANSFER_IN, RETURN

ALTER TABLE controlled_drug_log ADD COLUMN transfer_id TEXT;
ALTER TABLE controlled_drug_log ADD COLUMN counterparty_case_id TEXT;
ALTER TABLE controlled_drug_log ADD COLUMN counterparty_nurse_id TEXT;
```

### 6.2 移轉審計範例

```
移轉審計紀錄:

Case A (ANES-001) - 護理師 張小華:
┌─────────────────────────────────────────────────────────────────────┐
│ Time       │ Type         │ Drug     │ Qty │ Witness │ Note        │
├────────────┼──────────────┼──────────┼─────┼─────────┼─────────────┤
│ 08:30:00   │ ISSUE        │ Fentanyl │ +3  │ 藥師王  │ 領用        │
│ 09:15:00   │ USE          │ Fentanyl │ -1  │ 陳護理  │ Induction   │
│ 10:00:00   │ USE          │ Fentanyl │ -1  │ 陳護理  │ Maintenance │
│ 10:30:00   │ TRANSFER_OUT │ Fentanyl │ -1  │ 陳護理  │ → ANES-002  │
│            │              │          │ =0  │         │ Balance OK  │
└─────────────────────────────────────────────────────────────────────┘

Case B (ANES-002) - 護理師 李小美:
┌─────────────────────────────────────────────────────────────────────┐
│ Time       │ Type         │ Drug     │ Qty │ Witness │ Note        │
├────────────┼──────────────┼──────────┼─────┼─────────┼─────────────┤
│ 08:45:00   │ ISSUE        │ Fentanyl │ +2  │ 藥師王  │ 領用        │
│ 09:30:00   │ USE          │ Fentanyl │ -1  │ 林護理  │ Induction   │
│ 10:30:00   │ TRANSFER_IN  │ Fentanyl │ +1  │ 陳護理  │ ← ANES-001  │
│ 11:00:00   │ USE          │ Fentanyl │ -1  │ 林護理  │ Maintenance │
│ 11:30:00   │ USE          │ Fentanyl │ -1  │ 林護理  │ Emergence   │
│            │              │          │ =0  │         │ Balance OK  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Real-time Sync (WebSocket)

### 7.1 即時事件

```javascript
// WebSocket 事件類型
const WS_EVENTS = {
    // 庫存變更
    CART_INVENTORY_UPDATED: 'cart.inventory.updated',

    // 移轉相關
    TRANSFER_INITIATED: 'transfer.initiated',      // 收到移轉請求
    TRANSFER_CONFIRMED: 'transfer.confirmed',      // 移轉已確認
    TRANSFER_REJECTED: 'transfer.rejected',        // 移轉被拒絕
    TRANSFER_CANCELLED: 'transfer.cancelled',      // 移轉已取消

    // 通知
    NOTIFICATION_NEW: 'notification.new',
};

// 接收移轉通知
socket.on('transfer.initiated', (data) => {
    // data: { transfer_id, from_nurse, drug_name, quantity, ... }
    showTransferNotification(data);
    playNotificationSound();
    updatePendingBadge();
});
```

### 7.2 離線處理

```javascript
// 離線時的移轉處理
class OfflineTransferQueue {
    async queueTransfer(transferData) {
        // 1. 儲存到 IndexedDB
        await this.db.offlineTransfers.add({
            ...transferData,
            queued_at: new Date().toISOString(),
            sync_status: 'PENDING'
        });

        // 2. 本地預扣
        await this.localDeductHoldings(transferData);

        // 3. 顯示「待同步」標記
        this.showPendingSyncBadge();
    }

    async syncWhenOnline() {
        const pending = await this.db.offlineTransfers
            .where('sync_status').equals('PENDING')
            .toArray();

        for (const transfer of pending) {
            try {
                const result = await api.post('/transfers', transfer);
                await this.db.offlineTransfers.update(transfer.id, {
                    sync_status: 'SYNCED',
                    server_transfer_id: result.transfer_id
                });
            } catch (error) {
                await this.db.offlineTransfers.update(transfer.id, {
                    sync_status: 'CONFLICT',
                    error_message: error.message
                });
                this.showConflictAlert(transfer);
            }
        }
    }
}
```

---

## 8. Implementation Phases

### Phase 9.1: Multi-Cart Foundation (Day 1-2)

- [ ] 擴充 `drug_carts` 表 (cart_type, assigned_or, current_nurse_id)
- [ ] 擴充 `anesthesia_cases` 表 (cart_id, nurse_id)
- [ ] 實作藥車選擇邏輯
- [ ] 更新案件開始 API
- [ ] 藥車選擇 UI

### Phase 9.2: Transfer Database & API (Day 2-3)

- [ ] 建立 `drug_transfers` 表
- [ ] 建立 `transfer_notifications` 表
- [ ] 實作 `POST /transfers` (發起移轉)
- [ ] 實作 `POST /transfers/{id}/confirm` (確認)
- [ ] 實作 `POST /transfers/{id}/reject` (拒絕)
- [ ] 實作 `GET /transfers` (查詢)

### Phase 9.3: Holdings Integration (Day 3-4)

- [ ] 更新 `calculate_drug_holdings` 納入移轉
- [ ] 擴充 `controlled_drug_log` 支援移轉類型
- [ ] 實作 `GET /cases/{id}/holdings/with-transfers`
- [ ] 更新結案檢查邏輯

### Phase 9.4: UI Implementation (Day 4-5)

- [ ] 藥車選擇 Modal
- [ ] 剩藥處理介面
- [ ] 移轉發起 Modal
- [ ] 接收通知 UI
- [ ] Holdings Tab 更新

### Phase 9.5: Real-time & Offline (Day 5-6)

- [ ] WebSocket 事件整合
- [ ] 離線移轉佇列
- [ ] 衝突處理

### Phase 9.6: Testing & Demo (Day 6)

- [ ] Vercel demo 資料
- [ ] 整合測試
- [ ] 多裝置測試

---

## 9. Edge Cases & Error Handling

### 9.1 併發問題

| 情境 | 處理方式 |
|------|---------|
| 兩人同時從同藥車扣減 | Database transaction + optimistic locking |
| 移轉時對方已結案 | 拒絕移轉，通知發起方 |
| 移轉確認時來源不足 | 拒絕確認，需重新發起 |
| 離線時發起移轉 | 本地佇列，上線後同步 |

### 9.2 驗證規則

```python
def validate_transfer(request: TransferRequest) -> List[str]:
    errors = []

    # 1. 管制藥必須有見證人
    if is_controlled(request.medicine_code):
        if not request.witness_id:
            errors.append("管制藥移轉需要見證人")

    # 2. 來源必須有足夠數量
    from_holdings = get_holdings(request.from_case_id, request.medicine_code)
    if from_holdings.balance < request.quantity:
        errors.append(f"持有不足 (剩餘: {from_holdings.balance})")

    # 3. 不能移轉給自己
    if request.from_case_id == request.to_case_id:
        errors.append("不能移轉給同一案件")

    # 4. 目標案件必須是進行中
    if request.to_case_id:
        to_case = get_case(request.to_case_id)
        if to_case.status != 'ACTIVE':
            errors.append("目標案件已結束")

    return errors
```

### 9.3 錯誤碼

| Code | Message | Description |
|------|---------|-------------|
| `TRANSFER_INSUFFICIENT_HOLDINGS` | 持有不足 | 來源 holdings < 移轉數量 |
| `TRANSFER_WITNESS_REQUIRED` | 管制藥需見證人 | 管制藥未提供 witness_id |
| `TRANSFER_TARGET_CASE_CLOSED` | 目標案件已結束 | to_case_id 狀態非 ACTIVE |
| `TRANSFER_ALREADY_PROCESSED` | 移轉已處理 | 重複確認/拒絕 |
| `TRANSFER_NOT_RECIPIENT` | 非接收方 | 非目標護理師嘗試確認 |
| `TRANSFER_CANNOT_CANCEL` | 無法取消 | 非 PENDING 狀態嘗試取消 |

---

## 10. Vercel Demo Data

```python
# Demo multi-cart setup
DEMO_CARTS = [
    {"id": "CART-OR-01", "name": "OR-1 藥車", "cart_type": "OR", "assigned_or": "OR-01"},
    {"id": "CART-OR-02", "name": "OR-2 藥車", "cart_type": "OR", "assigned_or": "OR-02"},
    {"id": "CART-MOBILE-01", "name": "流動藥車 #1", "cart_type": "MOBILE"},
]

# Demo active cases with cart assignment
DEMO_CASES_WITH_CARTS = [
    {
        "id": "ANES-DEMO-001",
        "cart_id": "CART-OR-01",
        "nurse_id": "NURSE-DEMO-A",
        "nurse_name": "張小華",
        "or_room": "OR-01"
    },
    {
        "id": "ANES-DEMO-002",
        "cart_id": "CART-OR-02",
        "nurse_id": "NURSE-DEMO-B",
        "nurse_name": "李小美",
        "or_room": "OR-02"
    }
]

# Demo pending transfer
DEMO_TRANSFERS = [
    {
        "transfer_id": "XFER-DEMO-001",
        "transfer_type": "CASE_TO_CASE",
        "from_case_id": "ANES-DEMO-001",
        "from_nurse_name": "張小華",
        "to_case_id": "ANES-DEMO-002",
        "to_nurse_name": "李小美",
        "medicine_code": "FENT",
        "medicine_name": "Fentanyl 100mcg/2mL",
        "quantity": 1,
        "is_controlled": True,
        "controlled_level": 2,
        "witness_name": "陳護理師",
        "status": "PENDING"
    }
]
```

---

## 11. Migration Notes

### 11.1 現有資料遷移

```sql
-- 為現有案件指定預設藥車
UPDATE anesthesia_cases
SET cart_id = 'CART-OR-01'
WHERE cart_id IS NULL AND status = 'ACTIVE';

-- 為現有藥車設定類型
UPDATE drug_carts
SET cart_type = 'OR'
WHERE cart_type IS NULL;
```

### 11.2 向下相容

- 未指定 `cart_id` 的 API 呼叫自動使用 `CART-OR-01`
- Holdings API 不含 transfers 欄位時，維持現有格式

---

## Appendix A: Glossary

| 術語 | 英文 | 說明 |
|------|------|------|
| 移轉 | Transfer | 藥品在案件/藥車間的轉移 |
| 持有 | Holdings | 案件目前持有的藥品數量 |
| 領用 | Issue | 從藥車/藥局取出藥品 |
| 銷毀 | Waste | 丟棄剩餘藥品 (需見證) |
| 結案 | Reconcile | 確認所有藥品帳務平衡 |
| 見證 | Witness | 管制藥操作的第二人確認 |

---

*Document End*
