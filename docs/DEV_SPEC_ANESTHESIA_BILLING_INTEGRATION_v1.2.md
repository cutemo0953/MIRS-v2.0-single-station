# Anesthesia PWA ↔ Billing Integration DEV SPEC v1.2

**版本**: 1.2.0
**日期**: 2026-01-20
**狀態**: DRAFT
**關聯**: schema_pharmacy.sql, DEV_SPEC_MEDICATION_FORMULARY_v1.2.md (CIRS), CashDesk Handoff
**審閱整合**: Gemini, ChatGPT feedback (v1.2 回饋整合完成)

> **v1.2 變更**: 整合 Gemini/ChatGPT 審閱回饋 - 管制藥殘餘量銷毀、時間計費防呆、三帳本強制綁定、VOID pattern 撤銷。
> **v1.1 變更**: 擴充計費範圍，從「藥品計費」擴展為「完整麻醉計費」，包含麻醉處置費、藥品費、耗材費。

---

## 修訂背景

經 Gemini 與 ChatGPT 審閱後，發現以下問題：

| 問題 | 現況 | 修正 |
|------|------|------|
| **Anesthesia PWA 不扣庫** | 只記錄 timeline event | 新增 inventory transaction |
| **Hub/Satellite 定義反轉** | 模糊不清 | 明確定義 CIRS=Hub, MIRS=Satellite |
| **臨床/庫存事件未分離** | 混在一起 | 分離：臨床先落地，庫存 ACK 後 commit |
| **單位換算未實作** | mg 直接記錄 | 換算為 vial/amp (ceiling) |
| **管制藥 break-glass 規則不清** | 只有 flag | 枚舉允許的 action types |

---

## 1. 架構定義

### 1.1 角色定義 (Role Definition)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    xIRS Medication Supply Chain                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  CIRS (Community IRS)                                        │    │
│  │  Role: MEDICATION_HUB                                        │    │
│  │  ─────────────────────────────────────────────────────────   │    │
│  │  • 權威庫存 (Authoritative Stock)                            │    │
│  │  • 採購、驗收、總量管理                                       │    │
│  │  • 發補給衛星站 (MED_DISPATCH)                                │    │
│  │  • 管制藥總帳管理                                            │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                             │                                        │
│                    MED_DISPATCH (補給)                               │
│                    ─────────────────                                 │
│                    • QR Code 調撥單                                  │
│                    • 批號、效期追蹤                                  │
│                             │                                        │
│                             ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  MIRS (Medical IRS) / BORP Station                           │    │
│  │  Role: SATELLITE_PHARMACY                                    │    │
│  │  ─────────────────────────────────────────────────────────   │    │
│  │  • 本地庫存 (Local Stock)                                    │    │
│  │  • 接收補給 (MED_RECEIPT)                                    │    │
│  │  • 供應消耗端點 (Anesthesia, Emergency)                       │    │
│  │  • 管制藥本地審計                                            │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                             │                                        │
│                    DISPENSE (調劑)                                   │
│                    ───────────────                                   │
│                    • 直接從本地庫存扣減                              │
│                    • 離線可運作                                      │
│                             │                                        │
│                             ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Anesthesia PWA                                              │    │
│  │  Role: CONSUMPTION_ENDPOINT                                  │    │
│  │  ─────────────────────────────────────────────────────────   │    │
│  │  • 臨床用藥記錄                                              │    │
│  │  • 觸發庫存扣減                                              │    │
│  │  • 管制藥審計來源                                            │    │
│  │  • 產生計費項目                                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 關鍵原則

| 原則 | 說明 |
|------|------|
| **Offline-First** | 斷網時手術繼續進行，庫存允許扣至負數 |
| **Event Separation** | 臨床事件立即落地，庫存事件可延遲 ACK |
| **Local Authority** | MIRS 本地庫存為 ground truth (offline 時) |
| **Eventual Consistency** | 上線後與 Hub 對帳同步 |
| **Audit Trail** | 所有操作可追溯，管制藥雙重審計 |

---

## 2. 資料流設計

### 2.1 用藥記錄流程 (Medication Administration Flow)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Medication Administration Flow                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. 麻醉醫師選擇藥物                                                 │
│     ────────────────────                                            │
│     Input: Propofol 150mg IV                                        │
│                                                                      │
│  2. 單位換算 (Unit Conversion)                                       │
│     ────────────────────────                                        │
│     • 查詢 medicines.content_per_unit = 200mg/vial                  │
│     • 計算: 150mg ÷ 200mg = 0.75 vial                               │
│     • 進位 (CEIL): 1 vial (開封即消耗)                               │
│                                                                      │
│  3. 事件分離 (Event Separation)                                      │
│     ────────────────────────                                        │
│     ┌─────────────────────┐     ┌─────────────────────┐            │
│     │ Clinical Event      │     │ Inventory Event     │            │
│     │ (立即寫入)          │     │ (ACK 後 commit)     │            │
│     ├─────────────────────┤     ├─────────────────────┤            │
│     │ case_events         │     │ pharmacy_transactions│            │
│     │ • event_type: MED   │     │ • type: DISPENSE    │            │
│     │ • drug_code         │     │ • quantity: 1       │            │
│     │ • clinical_dose     │     │ • unit: vial        │            │
│     │ • timestamp         │     │ • medicines -= 1    │            │
│     └─────────────────────┘     └─────────────────────┘            │
│              │                            │                         │
│              │                            │                         │
│              ▼                            ▼                         │
│     ┌─────────────────────┐     ┌─────────────────────┐            │
│     │ Timeline Display    │     │ Stock Update        │            │
│     │ (即時顯示)          │     │ (可能延遲)          │            │
│     └─────────────────────┘     └─────────────────────┘            │
│                                                                      │
│  4. 管制藥額外處理 (Controlled Drug)                                 │
│     ────────────────────────────────────                            │
│     If is_controlled_drug:                                          │
│       → INSERT controlled_drug_log                                  │
│       → Require witness_id (or mark PENDING_WITNESS)                │
│                                                                      │
│  5. 計費連動 (Billing Linkage)                                       │
│     ────────────────────────                                        │
│     → CREATE medication_usage_event (append-only)                   │
│     → billing_status = PENDING                                      │
│     → CashDesk 稍後讀取                                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 離線處理策略

```python
# 離線優先策略

class MedicationAdminStrategy:
    """
    臨床事件：立即落地 (local SQLite)
    庫存事件：本地扣減 + 同步佇列
    管制藥：本地審計 + 上線後對帳
    """

    CLINICAL_EVENT = "IMMEDIATE"      # 立即寫入，不等 ACK
    INVENTORY_EVENT = "LOCAL_FIRST"   # 本地扣減，佇列同步
    CONTROLLED_AUDIT = "DUAL_WRITE"   # 本地 + 同步佇列

    # 離線時允許庫存扣至負數
    ALLOW_NEGATIVE_STOCK = True

    # 負庫存警告閾值
    NEGATIVE_STOCK_ALERT_THRESHOLD = -5
```

---

## 3. 單位換算邏輯

### 3.1 換算規則

```python
# services/unit_conversion.py

import math
from typing import Tuple, Optional
from decimal import Decimal

# 單位轉換表
UNIT_CONVERSIONS = {
    ('mcg', 'mg'): 0.001,
    ('mg', 'mcg'): 1000,
    ('mg', 'g'): 0.001,
    ('g', 'mg'): 1000,
    ('mL', 'L'): 0.001,
    ('L', 'mL'): 1000,
}

# 進位規則
class RoundingMode:
    CEIL = 'CEIL'      # 開封即消耗 (麻醉藥預設)
    FLOOR = 'FLOOR'    # 向下取整 (特殊情境)
    EXACT = 'EXACT'    # 精確計算 (輸液等可分割)


def calculate_billing_quantity(
    clinical_dose: float,
    clinical_unit: str,
    content_per_unit: float,
    content_unit: str,
    billing_rounding: str = RoundingMode.CEIL
) -> Tuple[int, str]:
    """
    將臨床劑量換算為計費數量

    Args:
        clinical_dose: 臨床劑量 (如 150)
        clinical_unit: 臨床單位 (如 'mg')
        content_per_unit: 每單位含量 (如 200)
        content_unit: 含量單位 (如 'mg')
        billing_rounding: 進位規則

    Returns:
        (billing_quantity, billing_unit)

    Example:
        calculate_billing_quantity(150, 'mg', 200, 'mg', 'CEIL')
        → (1, 'vial')  # 0.75 vial 進位為 1 vial
    """

    # 單位轉換
    if clinical_unit != content_unit:
        conversion = UNIT_CONVERSIONS.get((clinical_unit, content_unit))
        if conversion:
            clinical_dose = clinical_dose * conversion
        else:
            raise ValueError(f"Cannot convert {clinical_unit} to {content_unit}")

    # 計算所需單位數
    raw_quantity = clinical_dose / content_per_unit

    # 依據進位規則處理
    if billing_rounding == RoundingMode.CEIL:
        billing_quantity = math.ceil(raw_quantity)
    elif billing_rounding == RoundingMode.FLOOR:
        billing_quantity = math.floor(raw_quantity)
    else:  # EXACT
        billing_quantity = round(raw_quantity, 2)

    return int(billing_quantity), 'unit'  # unit 從 medicines 表取得
```

### 3.2 常見麻醉藥換算範例

| 藥品 | 臨床輸入 | 規格 | 換算結果 | 計費 |
|------|----------|------|----------|------|
| Propofol | 150mg | 200mg/vial | 0.75 → 1 vial | 1 vial |
| Fentanyl | 75mcg | 100mcg/amp | 0.75 → 1 amp | 1 amp |
| Midazolam | 3mg | 5mg/amp | 0.6 → 1 amp | 1 amp |
| Rocuronium | 40mg | 50mg/vial | 0.8 → 1 vial | 1 vial |
| Ketamine | 80mg | 500mg/vial | 0.16 → 1 vial | 1 vial |

---

## 4. 管制藥 Break-Glass 政策

### 4.1 Action Type 與 Break-Glass 允許矩陣

| Action Type | 常態需雙人覆核 | 允許 Break-Glass | 事後補核時限 |
|-------------|----------------|------------------|--------------|
| `DISPENSE` | ✅ 一二級必須 | ❌ 不允許 | - |
| `ADMINISTER` | ✅ 一二級必須 | ✅ 救命情境 | 24 小時 |
| `WASTE` | ✅ 必須見證 | ❌ 不允許 | - |
| `RETURN` | ✅ 必須 | ❌ 不允許 | - |
| `TRANSFER` | ✅ 必須 | ❌ 不允許 | - |

### 4.2 Break-Glass 觸發條件

```python
class BreakGlassCondition:
    """允許 Break-Glass 的情境"""

    ALLOWED_REASONS = [
        'MTP_ACTIVATED',           # 大量輸血啟動
        'CARDIAC_ARREST',          # 心跳停止
        'ANAPHYLAXIS',             # 過敏性休克
        'AIRWAY_EMERGENCY',        # 呼吸道緊急
        'EXSANGUINATING_HEMORRHAGE', # 大量出血
        'NO_SECOND_STAFF',         # 無第二人員可協助
        'SYSTEM_OFFLINE',          # 系統離線
    ]

    ALLOWED_ACTIONS = ['ADMINISTER']  # 只允許給藥

    FORBIDDEN_ACTIONS = ['DISPENSE', 'WASTE', 'RETURN', 'TRANSFER']
```

### 4.3 審計記錄結構

```sql
-- controlled_drug_log 擴充欄位 (v1.0)

-- Break-glass 相關
is_break_glass BOOLEAN DEFAULT 0,
break_glass_reason TEXT,           -- 必填 if is_break_glass
break_glass_approved_by TEXT,      -- 事後補核准人
break_glass_approved_at TIMESTAMP, -- 補核准時間
break_glass_deadline TIMESTAMP,    -- 24hr 截止時間

-- 狀態
witness_status TEXT DEFAULT 'REQUIRED',
-- 'REQUIRED'       - 需要見證人
-- 'COMPLETED'      - 已完成見證
-- 'PENDING'        - 待補見證 (break-glass)
-- 'WAIVED'         - 免除 (三四級管制)

CHECK (is_break_glass = 0 OR break_glass_reason IS NOT NULL)
```

---

## 5. API 設計

### 5.1 Anesthesia 用藥 API (修訂版)

```python
# routes/anesthesia.py

class MedicationAdminRequest(BaseModel):
    """用藥記錄請求 (v1.0 擴充)"""
    drug_code: str
    drug_name: str
    dose: float
    unit: str                      # 臨床單位 (mg, mcg, mL)
    route: str                     # IV, IM, SC, PO, SL
    is_controlled: Optional[bool] = False

    # v1.0 新增
    witness_id: Optional[str] = None  # 管制藥見證人
    is_break_glass: Optional[bool] = False
    break_glass_reason: Optional[str] = None

    # 時間偏移 (既有)
    clinical_time: Optional[str] = None
    clinical_time_offset_seconds: Optional[int] = None


class MedicationAdminResponse(BaseModel):
    """用藥記錄回應 (v1.0 擴充)"""
    success: bool
    event_id: str                  # 臨床事件 ID

    # v1.0 新增
    inventory_txn_id: Optional[str] = None  # 庫存交易 ID
    billing_quantity: int          # 計費數量
    billing_unit: str              # 計費單位
    estimated_price: Optional[float] = None

    # 警告
    warnings: List[str] = []       # 如: "庫存不足", "效期將近"

    # 管制藥
    controlled_log_id: Optional[str] = None
    witness_status: Optional[str] = None  # COMPLETED, PENDING


@router.post("/cases/{case_id}/medication", response_model=MedicationAdminResponse)
async def add_medication_v2(
    case_id: str,
    request: MedicationAdminRequest,
    actor_id: str = Query(...)
):
    """
    用藥記錄 v1.0 - 整合庫存扣減

    Flow:
    1. 查詢藥品資訊 (medicines 表)
    2. 單位換算 (clinical dose → billing quantity)
    3. 寫入臨床事件 (case_events)
    4. 扣減庫存 (pharmacy_transactions + medicines)
    5. 管制藥審計 (controlled_drug_log)
    6. 產生計費項目 (medication_usage_events)
    """
    pass  # 實作見下方
```

### 5.2 實作邏輯

```python
@router.post("/cases/{case_id}/medication")
async def add_medication_v2(case_id: str, request: MedicationAdminRequest, actor_id: str = Query(...)):
    """用藥記錄 v1.0 - 整合庫存扣減"""

    warnings = []

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. 查詢藥品資訊
        cursor.execute("""
            SELECT medicine_code, generic_name, brand_name, unit,
                   is_controlled_drug, controlled_level,
                   current_stock, nhi_price,
                   -- v1.0 新增欄位 (若存在)
                   COALESCE(content_per_unit, 1) as content_per_unit,
                   COALESCE(content_unit, unit) as content_unit,
                   COALESCE(billing_rounding, 'CEIL') as billing_rounding
            FROM medicines
            WHERE medicine_code = ?
        """, (request.drug_code,))

        med = cursor.fetchone()
        if not med:
            # Fallback: 藥品不在主檔，仍記錄臨床事件 (離線容錯)
            med = {
                'medicine_code': request.drug_code,
                'generic_name': request.drug_name,
                'unit': request.unit,
                'is_controlled_drug': request.is_controlled,
                'content_per_unit': 1,
                'content_unit': request.unit,
                'billing_rounding': 'CEIL',
                'current_stock': 0,
                'nhi_price': 0
            }
            warnings.append("藥品不在主檔，僅記錄臨床事件")
        else:
            med = dict(med)

        # 2. 單位換算
        billing_qty, billing_unit = calculate_billing_quantity(
            clinical_dose=request.dose,
            clinical_unit=request.unit,
            content_per_unit=med['content_per_unit'],
            content_unit=med['content_unit'],
            billing_rounding=med['billing_rounding']
        )
        billing_unit = med['unit']  # 使用主檔單位

        # 3. 寫入臨床事件 (立即)
        event_id = f"MED-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        payload = {
            "drug_code": request.drug_code,
            "drug_name": request.drug_name,
            "clinical_dose": request.dose,
            "clinical_unit": request.unit,
            "billing_quantity": billing_qty,
            "billing_unit": billing_unit,
            "route": request.route,
            "is_controlled": med['is_controlled_drug']
        }

        cursor.execute("""
            INSERT INTO case_events (case_id, event_type, payload, actor_id, timestamp)
            VALUES (?, 'MEDICATION_ADMIN', ?, ?, ?)
        """, (case_id, json.dumps(payload), actor_id, datetime.now().isoformat()))

        # 4. 扣減庫存
        inventory_txn_id = None
        if med['medicine_code'] != request.drug_code or 'nhi_price' not in med:
            # 藥品不在主檔，跳過庫存扣減
            pass
        else:
            inventory_txn_id = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            # 檢查庫存
            new_stock = med['current_stock'] - billing_qty
            if new_stock < 0:
                warnings.append(f"庫存不足 (剩餘: {med['current_stock']}, 扣減: {billing_qty})")

            # 寫入交易記錄
            cursor.execute("""
                INSERT INTO pharmacy_transactions (
                    transaction_id, transaction_type, medicine_code, generic_name,
                    quantity, unit, station_code,
                    is_controlled_drug, controlled_level,
                    patient_id, prescription_id,
                    operator, operator_role, verified_by,
                    reason, status
                ) VALUES (?, 'DISPENSE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED')
            """, (
                inventory_txn_id, med['medicine_code'], med['generic_name'],
                billing_qty, billing_unit, 'MIRS-OR',
                med['is_controlled_drug'], med.get('controlled_level'),
                None,  # patient_id from case
                None,  # prescription_id
                actor_id, 'NURSE',
                request.witness_id,
                f"Anesthesia admin: {request.dose}{request.unit} {request.route}"
            ))

            # 更新庫存
            cursor.execute("""
                UPDATE medicines SET current_stock = current_stock - ? WHERE medicine_code = ?
            """, (billing_qty, med['medicine_code']))

        # 5. 管制藥審計
        controlled_log_id = None
        witness_status = None

        if med['is_controlled_drug']:
            controlled_log_id = f"CTRL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            # 判斷見證狀態
            if request.witness_id:
                witness_status = 'COMPLETED'
            elif request.is_break_glass:
                witness_status = 'PENDING'
                warnings.append("Break-glass: 需在 24 小時內補核准")
            else:
                witness_status = 'REQUIRED'
                warnings.append("管制藥需要見證人")

            # 注意: controlled_drug_log 由 trigger 自動寫入
            # 這裡只需確保 pharmacy_transactions 有正確的 verified_by

        # 6. 產生計費項目 (append-only)
        usage_event_id = f"USAGE-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        cursor.execute("""
            INSERT INTO medication_usage_events (
                idempotency_key, event_type, medicine_code,
                clinical_dose, clinical_unit,
                billing_quantity, billing_unit,
                route, patient_id, operator_id, station_id,
                source_system, source_record_id,
                billing_status, event_timestamp
            ) VALUES (?, 'ANESTHESIA_ADMIN', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ANESTHESIA_PWA', ?, 'PENDING', ?)
        """, (
            usage_event_id, med['medicine_code'],
            request.dose, request.unit,
            billing_qty, billing_unit,
            request.route, None, actor_id, 'MIRS-OR',
            event_id, datetime.now().isoformat()
        ))

        conn.commit()

    # 計算預估價格
    estimated_price = None
    if med.get('nhi_price'):
        estimated_price = float(med['nhi_price']) * billing_qty

    return MedicationAdminResponse(
        success=True,
        event_id=event_id,
        inventory_txn_id=inventory_txn_id,
        billing_quantity=billing_qty,
        billing_unit=billing_unit,
        estimated_price=estimated_price,
        warnings=warnings,
        controlled_log_id=controlled_log_id,
        witness_status=witness_status
    )
```

---

## 6. 前端修改

### 6.1 Anesthesia PWA 藥品選擇 UI 擴充

```javascript
// 顯示庫存狀態
async function loadMedicationInventory() {
    const medications = await apiFetch('/api/pharmacy/medications/quick-picks');

    return medications.map(med => ({
        ...med,
        stockDisplay: med.current_stock <= 0
            ? '⚠️ 缺貨'
            : med.current_stock <= med.min_stock
                ? `⚠️ ${med.current_stock}`
                : `${med.current_stock}`,
        stockClass: med.current_stock <= 0
            ? 'stock-out'
            : med.current_stock <= med.min_stock
                ? 'stock-low'
                : 'stock-ok'
    }));
}

// 藥品按鈕顯示庫存
function renderMedButton(med) {
    return `
        <button class="med-btn ${med.is_controlled ? 'controlled-drug' : ''}"
                onclick="selectMed('${med.medicine_code}', '${med.generic_name}', ${med.default_dose}, '${med.unit}', ${med.is_controlled})">
            <span class="med-name">${med.generic_name}</span>
            <span class="med-dose">${med.default_dose}${med.unit}</span>
            <span class="med-stock ${med.stockClass}">${med.stockDisplay}</span>
        </button>
    `;
}
```

### 6.2 管制藥見證人 UI

```html
<!-- 管制藥見證人區塊 (在確認給藥前顯示) -->
<div id="controlledDrugWitnessSection" style="display: none;">
    <div class="warning-banner">
        <span>⚠️ 管制藥品需要雙人覆核</span>
    </div>

    <div class="form-group">
        <label>見證人工號 *</label>
        <input type="text" id="witnessId" placeholder="掃描或輸入工號">
    </div>

    <div class="or-divider">或</div>

    <button class="btn btn-warning" onclick="showBreakGlassDialog()">
        ⚡ 緊急模式 (Break-Glass)
    </button>
</div>
```

### 6.3 ASA 分級與麻醉類型 (v1.1 已實作)

> **狀態**: ✅ 已實作 (2026-01-20)

#### 新增案例 Modal 擴充

```html
<!-- 麻醉方式下拉 (已更新) -->
<select id="newTechnique">
    <option value="GA">全身麻醉 (GA)</option>
    <option value="GA_ETT">全身麻醉 - 插管 (ETT)</option>
    <option value="GA_LMA">全身麻醉 - 喉罩 (LMA)</option>
    <option value="RA_SPINAL">脊椎麻醉 (Spinal)</option>
    <option value="RA_EPIDURAL">硬膜外麻醉 (Epidural)</option>
    <option value="RA_NERVE">神經阻斷 (Nerve Block)</option>
    <option value="MAC">監測麻醉照護 (MAC)</option>
    <option value="LA">局部麻醉 (Local)</option>
</select>

<!-- ASA 分級下拉 (新增) -->
<div style="display: flex; gap: 8px;">
    <select id="newAsaClass">
        <option value="I">ASA I - 健康</option>
        <option value="II">ASA II - 輕度全身疾病</option>
        <option value="III">ASA III - 嚴重全身疾病</option>
        <option value="IV">ASA IV - 危及生命</option>
        <option value="V">ASA V - 瀕死</option>
    </select>
    <label>
        <input type="checkbox" id="newAsaEmergency">
        <span style="color: var(--warning);">+E 急診</span>
    </label>
</div>
```

### 6.4 特殊技術記錄 Modal (v1.1 已實作)

> **狀態**: ✅ 已實作 (2026-01-20)

進階事件區塊新增「特殊技術」按鈕，點擊後展開可複選的技術清單：

```html
<!-- 特殊技術 Modal -->
<div class="technique-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
    <label class="technique-toggle">
        <input type="checkbox" value="CVP">
        <div class="technique-card">
            <div class="technique-name">CVP</div>
            <div class="technique-desc">中央靜脈導管</div>
        </div>
    </label>
    <label class="technique-toggle">
        <input type="checkbox" value="ART">
        <div class="technique-card">
            <div class="technique-name">A-Line</div>
            <div class="technique-desc">動脈導管</div>
        </div>
    </label>
    <!-- ... TEE, BIS, ULTRASOUND, FIBER_INTUB, DLT, NERVE_BLOCK ... -->
</div>
```

#### 後端 API

```python
# EventType 新增
SPECIAL_TECHNIQUE = "SPECIAL_TECHNIQUE"  # v1.1: 特殊技術 (計費用)

# 事件 payload
{
    "event_type": "SPECIAL_TECHNIQUE",
    "payload": {
        "techniques": ["CVP", "ART", "BIS"],  # 可複選
        "action": "UPDATE"
    }
}
```

#### 資料庫欄位擴充

```sql
-- anesthesia_cases 新增欄位
ALTER TABLE anesthesia_cases ADD COLUMN asa_classification TEXT DEFAULT 'II';
ALTER TABLE anesthesia_cases ADD COLUMN is_emergency INTEGER DEFAULT 0;
```

---

## 7. 完整計費項目 (Complete Billing Items)

> **v1.1 新增**: 擴充計費範圍，從藥品延伸至麻醉處置、手術處置、耗材等完整計費項目。

### 7.1 計費項目類型

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MIRS 手術計費項目全覽                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  1. 麻醉處置費 (Anesthesia Procedure Fees)                       │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │  • 麻醉基本費 (Base Fee)                                        │   │
│  │  • 麻醉時間費 (Time-Based Fee)                                  │   │
│  │  • ASA 分級加成 (ASA Classification Modifier)                   │   │
│  │  • 特殊技術加成 (Special Technique Modifier)                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  2. 手術處置費 (Surgical Procedure Fees)                         │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │  • 手術費 (Surgeon Fee)                                         │   │
│  │  • 助手費 (Assistant Fee)                                       │   │
│  │  • 特殊技術加成                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  3. 藥品費 (Medication Fees) - 已涵蓋於 Section 2-5              │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │  • 麻醉用藥                                                      │   │
│  │  • 急救用藥                                                      │   │
│  │  • 術中用藥                                                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  4. 耗材費 (Supply/Material Fees)                                │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │  • 手術耗材 (套包、縫線、植入物)                                  │   │
│  │  • 麻醉耗材 (氣管管、IV套件)                                     │   │
│  │  • 特殊材料 (骨科植入物、骨水泥)                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  5. 血品費 (Blood Product Fees)                                  │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │  • 紅血球濃厚液                                                  │   │
│  │  • 新鮮冷凍血漿                                                  │   │
│  │  • 血小板濃厚液                                                  │   │
│  │  • (已整合至 Blood Chain of Custody)                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 麻醉處置費結構 (Anesthesia Fee Structure)

#### 7.2.1 費用組成公式

```
麻醉總費 = 基本費 + (時間費 × 時間單位) + ASA加成 + 特殊技術加成

其中:
- 基本費: 依麻醉類型 (全身/區域/局部/鎮靜)
- 時間費: 每 15 分鐘一單位
- ASA加成: ASA III-V 有額外加成
- 特殊技術: 如侵入性監測、神經阻斷等
```

#### 7.2.2 麻醉類型與基本費

| 代碼 | 麻醉類型 | 英文 | 基本費等級 | 說明 |
|------|----------|------|------------|------|
| `GA` | 全身麻醉 | General Anesthesia | A | 插管/喉罩 |
| `RA-S` | 脊椎麻醉 | Spinal Anesthesia | B | 腰椎穿刺 |
| `RA-E` | 硬膜外麻醉 | Epidural Anesthesia | B | 連續輸注 |
| `RA-N` | 神經阻斷 | Nerve Block | C | 超音波導引 |
| `MAC` | 監測麻醉 | Monitored Anesthesia Care | D | 鎮靜監測 |
| `LA` | 局部麻醉 | Local Anesthesia | E | 局部浸潤 |

#### 7.2.3 ASA 分級加成

| ASA 等級 | 定義 | 加成比例 |
|----------|------|----------|
| ASA I | 健康病人 | 0% (基準) |
| ASA II | 輕度全身性疾病 | 0% |
| ASA III | 嚴重全身性疾病 | +20% |
| ASA IV | 持續危及生命的全身性疾病 | +40% |
| ASA V | 不手術預期無法存活 | +50% |
| +E | 急診手術 | +10% (累加) |

#### 7.2.4 特殊技術加成

| 代碼 | 技術項目 | 加成 |
|------|----------|------|
| `CVP` | 中央靜脈導管 | 定額 |
| `ART` | 動脈導管 | 定額 |
| `TEE` | 經食道心臟超音波 | 定額 |
| `BIS` | 腦電雙頻指數監測 | 定額 |
| `ULTRASOUND` | 超音波導引穿刺 | 定額 |
| `FIBER_INTUB` | 纖維支氣管鏡插管 | 定額 |
| `DLT` | 雙腔氣管內管 | 定額 |

### 7.3 資料結構

#### 7.3.1 麻醉計費事件表

```sql
-- anesthesia_billing_events (麻醉計費事件)
CREATE TABLE IF NOT EXISTS anesthesia_billing_events (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    patient_id TEXT,

    -- 麻醉資訊
    anesthesia_type TEXT NOT NULL,        -- GA, RA-S, RA-E, RA-N, MAC, LA
    asa_classification TEXT NOT NULL,     -- I, II, III, IV, V
    is_emergency BOOLEAN DEFAULT 0,       -- +E 標記

    -- 時間
    anesthesia_start_time TEXT,           -- 麻醉開始時間
    anesthesia_end_time TEXT,             -- 麻醉結束時間
    total_minutes INTEGER,                -- 總時間 (分鐘)
    billable_time_units INTEGER,          -- 計費時間單位 (每15分鐘)

    -- 人員
    anesthesiologist_id TEXT NOT NULL,    -- 主麻醫師
    anesthesiologist_name TEXT,
    assistant_id TEXT,                    -- 麻醉護理師/助手

    -- 特殊技術 (JSON array)
    special_techniques TEXT,              -- ["CVP", "ART", "BIS"]

    -- 計費
    base_fee REAL,                        -- 基本費
    time_fee REAL,                        -- 時間費
    asa_modifier_fee REAL,                -- ASA 加成
    technique_fees REAL,                  -- 特殊技術費
    total_anesthesia_fee REAL,            -- 麻醉總費

    -- 狀態
    billing_status TEXT DEFAULT 'PENDING', -- PENDING, CALCULATED, EXPORTED, BILLED
    exported_at TEXT,                      -- 匯出至 CashDesk 時間
    cashdesk_reference TEXT,               -- CashDesk 收據號

    -- 審計
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT,

    FOREIGN KEY (case_id) REFERENCES cases(case_id)
);

CREATE INDEX idx_anesthesia_billing_case ON anesthesia_billing_events(case_id);
CREATE INDEX idx_anesthesia_billing_status ON anesthesia_billing_events(billing_status);
```

#### 7.3.2 手術計費事件表

```sql
-- surgical_billing_events (手術計費事件)
CREATE TABLE IF NOT EXISTS surgical_billing_events (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    patient_id TEXT,

    -- 手術資訊
    procedure_code TEXT NOT NULL,         -- 手術代碼
    procedure_name TEXT,                  -- 手術名稱
    procedure_category TEXT,              -- 手術分類

    -- 時間
    surgery_start_time TEXT,              -- 手術開始 (劃刀)
    surgery_end_time TEXT,                -- 手術結束 (關刀)
    total_minutes INTEGER,

    -- 人員
    surgeon_id TEXT NOT NULL,             -- 主刀醫師
    surgeon_name TEXT,
    assistant_surgeon_id TEXT,            -- 助手醫師
    assistant_surgeon_name TEXT,

    -- 計費
    surgeon_fee REAL,                     -- 手術費
    assistant_fee REAL,                   -- 助手費
    special_technique_fee REAL,           -- 特殊技術費
    total_surgical_fee REAL,              -- 手術總費

    -- 狀態
    billing_status TEXT DEFAULT 'PENDING',
    exported_at TEXT,
    cashdesk_reference TEXT,

    -- 審計
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT,

    FOREIGN KEY (case_id) REFERENCES cases(case_id)
);

CREATE INDEX idx_surgical_billing_case ON surgical_billing_events(case_id);
```

### 7.4 計費事件產生流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    手術計費事件產生流程                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  手術進行中 (Timeline Events)                                           │
│  ────────────────────────────                                          │
│                                                                         │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐           │
│  │ ANESTHESIA   │     │ MEDICATION   │     │ INCISION     │           │
│  │ _START       │────▶│ _ADMIN       │────▶│ _START       │──── ...   │
│  └──────────────┘     └──────────────┘     └──────────────┘           │
│                              │                                         │
│                              ▼                                         │
│                    medication_usage_events                             │
│                    (藥品計費 - 即時產生)                                 │
│                                                                         │
│  ────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  手術結束 (Case Closed)                                                 │
│  ─────────────────────                                                 │
│                                                                         │
│  ┌──────────────┐     ┌──────────────┐                                │
│  │ SURGERY_END  │────▶│ ANESTHESIA   │                                │
│  │              │     │ _END         │                                │
│  └──────────────┘     └──────────────┘                                │
│          │                    │                                        │
│          ▼                    ▼                                        │
│  ┌────────────────┐  ┌────────────────┐                               │
│  │ 計算手術處置費  │  │ 計算麻醉處置費  │                               │
│  │ surgical_      │  │ anesthesia_    │                               │
│  │ billing_events │  │ billing_events │                               │
│  └────────────────┘  └────────────────┘                               │
│          │                    │                                        │
│          └──────────┬─────────┘                                        │
│                     ▼                                                  │
│          ┌─────────────────────┐                                       │
│          │ CashDesk Handoff    │                                       │
│          │ Package             │                                       │
│          └─────────────────────┘                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.5 CashDesk Handoff Package

#### 7.5.1 整合介面

```python
# routes/billing.py

class CashDeskHandoffPackage(BaseModel):
    """CashDesk 收費系統交接包"""
    case_id: str
    patient_id: str
    patient_name: str

    # 手術基本資訊
    surgery_date: str
    procedure_name: str
    surgeon_name: str
    anesthesiologist_name: str

    # 分項明細
    items: List[BillingItem]

    # 小計
    subtotals: BillingSubtotals

    # 總計
    grand_total: float

    # 中繼資料
    generated_at: str
    generated_by: str
    mirs_version: str


class BillingItem(BaseModel):
    """計費項目"""
    category: str            # ANESTHESIA, SURGERY, MEDICATION, SUPPLY, BLOOD
    item_code: str
    item_name: str
    quantity: float
    unit: str
    unit_price: float
    subtotal: float
    nhi_code: Optional[str]  # 健保碼
    notes: Optional[str]


class BillingSubtotals(BaseModel):
    """分類小計"""
    anesthesia_fee: float    # 麻醉處置費
    surgery_fee: float       # 手術處置費
    medication_fee: float    # 藥品費
    supply_fee: float        # 耗材費
    blood_fee: float         # 血品費
```

#### 7.5.2 Handoff API

```python
@router.get("/cases/{case_id}/billing/handoff")
async def generate_cashdesk_handoff(
    case_id: str,
    include_details: bool = True
) -> CashDeskHandoffPackage:
    """
    產生 CashDesk 收費系統交接包

    觸發條件:
    - 手術結案 (Case Status = COMPLETED)
    - 手動觸發 (管理員)

    回傳:
    - 完整計費明細
    - 可直接匯入 CashDesk
    """
    pass


@router.post("/cases/{case_id}/billing/export-to-cashdesk")
async def export_to_cashdesk(
    case_id: str,
    actor_id: str = Query(...)
) -> dict:
    """
    匯出計費資料至 CashDesk

    Actions:
    1. 產生 Handoff Package
    2. 呼叫 CashDesk API (若整合)
    3. 更新 billing_status = EXPORTED
    4. 記錄 cashdesk_reference
    """
    pass
```

#### 7.5.3 Handoff Package 範例

```json
{
  "case_id": "CASE-20260120-001",
  "patient_id": "P12345",
  "patient_name": "王大明",
  "surgery_date": "2026-01-20",
  "procedure_name": "右膝全人工關節置換術",
  "surgeon_name": "李醫師",
  "anesthesiologist_name": "陳醫師",

  "items": [
    {
      "category": "ANESTHESIA",
      "item_code": "ANES-GA-001",
      "item_name": "全身麻醉基本費",
      "quantity": 1,
      "unit": "次",
      "unit_price": 5000,
      "subtotal": 5000,
      "nhi_code": "96001A"
    },
    {
      "category": "ANESTHESIA",
      "item_code": "ANES-TIME-15",
      "item_name": "麻醉時間費 (每15分鐘)",
      "quantity": 8,
      "unit": "單位",
      "unit_price": 300,
      "subtotal": 2400,
      "nhi_code": "96002A"
    },
    {
      "category": "ANESTHESIA",
      "item_code": "ANES-ASA3",
      "item_name": "ASA III 加成 (20%)",
      "quantity": 1,
      "unit": "次",
      "unit_price": 1480,
      "subtotal": 1480,
      "notes": "基本費+時間費之20%"
    },
    {
      "category": "ANESTHESIA",
      "item_code": "ANES-ART",
      "item_name": "動脈導管置入",
      "quantity": 1,
      "unit": "次",
      "unit_price": 800,
      "subtotal": 800,
      "nhi_code": "96021A"
    },
    {
      "category": "SURGERY",
      "item_code": "SURG-TKA-001",
      "item_name": "全人工膝關節置換術 - 主刀",
      "quantity": 1,
      "unit": "次",
      "unit_price": 35000,
      "subtotal": 35000,
      "nhi_code": "64164B"
    },
    {
      "category": "SURGERY",
      "item_code": "SURG-ASST-001",
      "item_name": "手術助手費",
      "quantity": 1,
      "unit": "次",
      "unit_price": 7000,
      "subtotal": 7000
    },
    {
      "category": "MEDICATION",
      "item_code": "MED-PROP-200",
      "item_name": "Propofol 200mg/vial",
      "quantity": 3,
      "unit": "vial",
      "unit_price": 450,
      "subtotal": 1350,
      "nhi_code": "BC26328100"
    },
    {
      "category": "MEDICATION",
      "item_code": "MED-FENT-100",
      "item_name": "Fentanyl 100mcg/amp",
      "quantity": 5,
      "unit": "amp",
      "unit_price": 85,
      "subtotal": 425,
      "nhi_code": "N01AH01"
    },
    {
      "category": "SUPPLY",
      "item_code": "SUP-ETT-75",
      "item_name": "氣管內管 7.5mm",
      "quantity": 1,
      "unit": "支",
      "unit_price": 250,
      "subtotal": 250
    },
    {
      "category": "SUPPLY",
      "item_code": "SUP-TKA-IMP",
      "item_name": "膝關節假體系統",
      "quantity": 1,
      "unit": "組",
      "unit_price": 85000,
      "subtotal": 85000
    },
    {
      "category": "BLOOD",
      "item_code": "BLOOD-PRBC",
      "item_name": "紅血球濃厚液 (Leukocyte-reduced)",
      "quantity": 2,
      "unit": "U",
      "unit_price": 950,
      "subtotal": 1900
    }
  ],

  "subtotals": {
    "anesthesia_fee": 9680,
    "surgery_fee": 42000,
    "medication_fee": 1775,
    "supply_fee": 85250,
    "blood_fee": 1900
  },

  "grand_total": 140605,

  "generated_at": "2026-01-20T18:30:00+08:00",
  "generated_by": "SYSTEM",
  "mirs_version": "2.0.0"
}
```

### 7.6 自動計費觸發

```python
# services/billing_calculator.py

async def on_case_closed(case_id: str, actor_id: str):
    """
    案例結案時自動計算處置費

    Trigger: Case Status → COMPLETED
    """

    # 1. 計算麻醉處置費
    anesthesia_billing = await calculate_anesthesia_fee(case_id)

    # 2. 計算手術處置費
    surgical_billing = await calculate_surgical_fee(case_id)

    # 3. 彙總藥品費 (已在用藥時產生)
    medication_total = await sum_medication_fees(case_id)

    # 4. 彙總耗材費
    supply_total = await sum_supply_fees(case_id)

    # 5. 彙總血品費
    blood_total = await sum_blood_fees(case_id)

    # 6. 產生 Handoff Package (待匯出)
    await create_handoff_package(
        case_id=case_id,
        anesthesia=anesthesia_billing,
        surgical=surgical_billing,
        medication=medication_total,
        supply=supply_total,
        blood=blood_total
    )

    logger.info(f"Case {case_id} billing calculated, ready for CashDesk export")


async def calculate_anesthesia_fee(case_id: str) -> dict:
    """計算麻醉處置費"""

    with get_db() as conn:
        # 取得麻醉時間
        events = conn.execute("""
            SELECT event_type, timestamp, payload
            FROM case_events
            WHERE case_id = ? AND event_type IN ('ANESTHESIA_START', 'ANESTHESIA_END')
            ORDER BY timestamp
        """, (case_id,)).fetchall()

        # 計算時間
        start_time = None
        end_time = None
        for e in events:
            if e['event_type'] == 'ANESTHESIA_START':
                start_time = datetime.fromisoformat(e['timestamp'])
            elif e['event_type'] == 'ANESTHESIA_END':
                end_time = datetime.fromisoformat(e['timestamp'])

        if not start_time or not end_time:
            return None

        total_minutes = (end_time - start_time).total_seconds() / 60
        time_units = math.ceil(total_minutes / 15)  # 每 15 分鐘一單位

        # 取得 case 資訊 (ASA, 麻醉類型)
        case = conn.execute("""
            SELECT asa_classification, anesthesia_type
            FROM cases WHERE case_id = ?
        """, (case_id,)).fetchone()

        # 計算費用 (lookup fee schedule)
        base_fee = get_base_fee(case['anesthesia_type'])
        time_fee = get_time_fee() * time_units
        asa_modifier = get_asa_modifier(case['asa_classification'])

        total = (base_fee + time_fee) * (1 + asa_modifier)

        return {
            'base_fee': base_fee,
            'time_fee': time_fee,
            'time_units': time_units,
            'asa_modifier': asa_modifier,
            'total': total
        }
```

---

## 8. 實作計劃

### Phase 1: 後端基礎 - 藥品庫存

- [x] 新增 `medicines` 表擴充欄位 (content_per_unit, content_unit, billing_rounding)
- [x] 實作 `calculate_billing_quantity()` 函數 (services/anesthesia_billing.py)
- [x] 修改 `/cases/{id}/medication` API 加入庫存扣減
- [x] 新增 `medication_usage_events` 表 (add_anesthesia_billing_schema.sql)

### Phase 2: 管制藥處理

- [x] 實作管制藥驗證邏輯 (process_medication_admin)
- [ ] Break-glass 流程
- [ ] 事後補核准 API

### Phase 3: 前端整合 - 藥品

- [x] 藥品選擇顯示庫存 (loadQuickDrugsWithInventory)
- [ ] 管制藥見證人 UI
- [ ] Break-glass 對話框
- [x] 扣庫結果顯示 (stock badge)

### Phase 4: 離線處理

- [ ] 離線佇列機制
- [ ] 上線後同步
- [ ] 衝突處理

### Phase 5: 處置費計費 (v1.1 新增)

- [x] 建立 `anesthesia_billing_events` 表
- [x] 建立 `surgical_billing_events` 表
- [x] 實作 `calculate_anesthesia_fee()` 邏輯
- [ ] 實作 `calculate_surgical_fee()` 邏輯
- [ ] 整合手術結案觸發 (`on_case_closed`)

### Phase 6: CashDesk 整合 (v1.1 新增)

- [x] 實作 `CashDeskHandoffPackage` 資料結構 (generate_cashdesk_handoff)
- [x] 實作 `/cases/{id}/billing/handoff` API
- [x] 實作 `/cases/{id}/billing/export-to-cashdesk` API
- [x] 費率表設定 (anesthesia_fee_schedule, surgical_fee_schedule)

### Phase 7: 麻醉藥車調撥 (v1.1 新增)

- [x] 建立 `anesthesia_carts` 表
- [x] 建立 `cart_inventory` 表
- [x] 實作藥車調撥 API (`MED_DISPATCH` to cart)
- [x] 實作交班清點 API (POST /carts/{id}/inventory/check)
- [x] 差異報告與藥師核對流程 (DispatchReceive, DispatchVerify)
- [ ] PWA 藥車選擇 UI

---

## 9. 麻醉藥車調撥流程 (Anesthesia Drug Cart)

> **v1.1 新增**: 定義 MIRS 藥庫與麻醉藥車之間的藥品調撥、使用、交班清點流程。

### 9.1 流程概覽

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    麻醉藥車調撥工作流程                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  【每日/每班開始】                                                       │
│  ┌─────────────────┐         ┌─────────────────────┐                   │
│  │  MIRS Pharmacy  │ ──────▶ │  Anesthesia Cart    │                   │
│  │  (權威庫存)      │  調撥    │  (麻醉藥車/托盤)    │                   │
│  └─────────────────┘         └─────────────────────┘                   │
│         │                              │                               │
│         │ MED_DISPATCH                 │ 藥師清點簽收                   │
│         │ (類似 MIRS→CIRS)             │ 麻醉護理師接收                  │
│         ▼                              ▼                               │
│  ┌─────────────────┐         ┌─────────────────────┐                   │
│  │ 調撥記錄:        │         │ 藥車內容:           │                   │
│  │ - Fentanyl x10  │         │ - Fentanyl 10 amp   │                   │
│  │ - Midazolam x5  │         │ - Midazolam 5 amp   │                   │
│  │ - Propofol x20  │         │ - Propofol 20 vial  │                   │
│  │ - Ketamine x5   │         │ - Ketamine 5 vial   │                   │
│  └─────────────────┘         └─────────────────────┘                   │
│                                       │                                │
│  【術中使用】                          ▼                                │
│                              ┌─────────────────────┐                   │
│                              │ Anesthesia PWA      │                   │
│                              │ 記錄用藥             │                   │
│                              │ - case A: Fent 3amp │                   │
│                              │ - case B: Fent 2amp │                   │
│                              │ - case B: Mida 1amp │                   │
│                              └─────────────────────┘                   │
│                                       │                                │
│  【每日/每班結束】                      ▼                                │
│                              ┌─────────────────────┐                   │
│                              │ 交班清點 (Reconcile) │                   │
│                              │                     │                   │
│                              │ 預期剩餘: Fent 5 amp│                   │
│                              │ 實際清點: Fent 5 amp ✓│                  │
│                              │                     │                   │
│                              │ 預期剩餘: Mida 4 amp│                   │
│                              │ 實際清點: Mida 3 amp ⚠️│                 │
│                              │ → 差異需藥師複核    │                   │
│                              └─────────────────────┘                   │
│                                       │                                │
│                        ┌──────────────┴──────────────┐                 │
│                        ▼                             ▼                 │
│               ┌─────────────────┐         ┌─────────────────┐          │
│               │ 退還 Pharmacy   │         │ 差異報告        │          │
│               │ (未用完歸庫)    │         │ → 藥師核對      │          │
│               └─────────────────┘         └─────────────────┘          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.2 資料結構

#### 9.2.1 麻醉藥車表

```sql
-- anesthesia_carts (麻醉藥車)
CREATE TABLE IF NOT EXISTS anesthesia_carts (
    id TEXT PRIMARY KEY,                    -- CART-OR1-001
    cart_name TEXT NOT NULL,                -- OR1 麻醉藥車
    location TEXT,                          -- OR1

    -- 狀態
    status TEXT DEFAULT 'AVAILABLE',        -- AVAILABLE, IN_USE, MAINTENANCE
    current_shift_id TEXT,                  -- 當前班次 ID
    assigned_nurse_id TEXT,                 -- 負責的麻醉護理師

    -- 審計
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    CHECK(status IN ('AVAILABLE', 'IN_USE', 'MAINTENANCE'))
);

-- cart_inventory (藥車庫存)
CREATE TABLE IF NOT EXISTS cart_inventory (
    id TEXT PRIMARY KEY,
    cart_id TEXT NOT NULL,
    medicine_code TEXT NOT NULL,
    medicine_name TEXT,

    -- 數量
    quantity INTEGER NOT NULL DEFAULT 0,
    unit TEXT NOT NULL,                     -- amp, vial, etc.

    -- 管制藥
    is_controlled BOOLEAN DEFAULT 0,
    controlled_level INTEGER,               -- 1-4 級

    -- 批號效期 (選填，管制藥必填)
    lot_number TEXT,
    expiry_date TEXT,

    -- 審計
    last_count_at TEXT,
    last_count_by TEXT,
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (cart_id) REFERENCES anesthesia_carts(id),
    UNIQUE(cart_id, medicine_code, lot_number)
);

CREATE INDEX idx_cart_inventory_cart ON cart_inventory(cart_id);
CREATE INDEX idx_cart_inventory_controlled ON cart_inventory(is_controlled);
```

#### 9.2.2 藥車調撥記錄表

```sql
-- cart_dispatch_records (藥車調撥記錄)
CREATE TABLE IF NOT EXISTS cart_dispatch_records (
    id TEXT PRIMARY KEY,
    cart_id TEXT NOT NULL,
    shift_id TEXT,                          -- 班次 ID

    -- 調撥類型
    dispatch_type TEXT NOT NULL,            -- DISPATCH (調出), RETURN (歸還), ADJUST (調整)

    -- 時間
    dispatched_at TEXT DEFAULT (datetime('now')),

    -- 人員
    pharmacist_id TEXT NOT NULL,            -- 調撥藥師
    pharmacist_name TEXT,
    receiver_id TEXT,                       -- 接收人 (麻醉護理師)
    receiver_name TEXT,

    -- 明細 (JSON array)
    items TEXT NOT NULL,                    -- [{"medicine_code": "...", "quantity": 10, ...}]

    -- 狀態
    status TEXT DEFAULT 'PENDING',          -- PENDING, RECEIVED, VERIFIED
    received_at TEXT,
    verified_at TEXT,
    verified_by TEXT,

    -- 備註
    notes TEXT,

    FOREIGN KEY (cart_id) REFERENCES anesthesia_carts(id),
    CHECK(dispatch_type IN ('DISPATCH', 'RETURN', 'ADJUST')),
    CHECK(status IN ('PENDING', 'RECEIVED', 'VERIFIED'))
);
```

#### 9.2.3 班次清點記錄表

```sql
-- cart_shift_reconciliation (班次清點記錄)
CREATE TABLE IF NOT EXISTS cart_shift_reconciliation (
    id TEXT PRIMARY KEY,
    cart_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,

    -- 班次時間
    shift_start TEXT NOT NULL,
    shift_end TEXT,

    -- 人員
    nurse_id TEXT NOT NULL,                 -- 負責護理師
    nurse_name TEXT,
    handover_to_id TEXT,                    -- 交班給
    handover_to_name TEXT,

    -- 清點結果
    reconciliation_status TEXT DEFAULT 'PENDING',  -- PENDING, MATCHED, DISCREPANCY, REVIEWED

    -- 初始庫存 (班次開始時)
    initial_inventory TEXT,                 -- JSON snapshot

    -- 用藥記錄彙總
    usage_summary TEXT,                     -- JSON: [{"medicine_code": "...", "total_used": 5}]

    -- 預期剩餘
    expected_remaining TEXT,                -- JSON: calculated from initial - usage

    -- 實際清點
    actual_count TEXT,                      -- JSON: from physical count
    counted_at TEXT,

    -- 差異
    discrepancies TEXT,                     -- JSON: [{medicine_code, expected, actual, diff}]

    -- 藥師核對 (如有差異)
    pharmacist_review_required BOOLEAN DEFAULT 0,
    pharmacist_id TEXT,
    pharmacist_reviewed_at TEXT,
    pharmacist_notes TEXT,
    resolution TEXT,                        -- APPROVED, INVESTIGATED, LOSS_REPORTED

    -- 審計
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (cart_id) REFERENCES anesthesia_carts(id),
    CHECK(reconciliation_status IN ('PENDING', 'MATCHED', 'DISCREPANCY', 'REVIEWED'))
);
```

### 9.3 API 設計

#### 9.3.1 藥車管理

```python
# 取得可用藥車
@router.get("/carts")
async def list_carts(status: Optional[str] = None) -> List[CartResponse]:
    pass

# 取得藥車庫存
@router.get("/carts/{cart_id}/inventory")
async def get_cart_inventory(cart_id: str) -> CartInventoryResponse:
    pass

# 認領藥車 (班次開始)
@router.post("/carts/{cart_id}/claim")
async def claim_cart(cart_id: str, nurse_id: str = Query(...)) -> CartResponse:
    """麻醉護理師認領藥車開始班次"""
    pass
```

#### 9.3.2 藥品調撥

```python
class DispatchItem(BaseModel):
    medicine_code: str
    medicine_name: str
    quantity: int
    unit: str
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = None
    is_controlled: bool = False
    controlled_level: Optional[int] = None


class CartDispatchRequest(BaseModel):
    cart_id: str
    dispatch_type: str  # DISPATCH, RETURN
    items: List[DispatchItem]
    notes: Optional[str] = None


@router.post("/pharmacy/cart-dispatch")
async def dispatch_to_cart(
    request: CartDispatchRequest,
    pharmacist_id: str = Query(...)
) -> DispatchRecordResponse:
    """
    藥師調撥藥品到藥車

    1. 從 MIRS pharmacy 扣減庫存
    2. 增加藥車庫存
    3. 記錄 controlled_drug_log (管制藥)
    4. 產生調撥單待接收
    """
    pass


@router.post("/carts/{cart_id}/receive-dispatch/{dispatch_id}")
async def receive_dispatch(
    cart_id: str,
    dispatch_id: str,
    receiver_id: str = Query(...)
) -> DispatchRecordResponse:
    """麻醉護理師確認接收調撥藥品"""
    pass
```

#### 9.3.3 交班清點

```python
class CountItem(BaseModel):
    medicine_code: str
    actual_quantity: int


class ReconciliationRequest(BaseModel):
    cart_id: str
    counted_items: List[CountItem]
    handover_to_id: Optional[str] = None
    notes: Optional[str] = None


@router.post("/carts/{cart_id}/reconcile")
async def reconcile_shift(
    cart_id: str,
    request: ReconciliationRequest,
    nurse_id: str = Query(...)
) -> ReconciliationResponse:
    """
    交班清點流程:

    1. 計算預期剩餘 = 初始庫存 - 用藥記錄
    2. 比對實際清點
    3. 無差異 → 狀態 = MATCHED, 自動關閉班次
    4. 有差異 → 狀態 = DISCREPANCY, 需藥師核對
    """
    pass


@router.post("/carts/reconciliation/{recon_id}/pharmacist-review")
async def pharmacist_review_reconciliation(
    recon_id: str,
    pharmacist_id: str = Query(...),
    resolution: str = Query(...),  # APPROVED, INVESTIGATED, LOSS_REPORTED
    notes: str = Query(None)
) -> ReconciliationResponse:
    """藥師核對差異"""
    pass
```

### 9.4 Anesthesia PWA 用藥流程修改

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    用藥流程 (含藥車概念)                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 班次開始                                                            │
│     ├─ 麻醉護理師認領藥車 (claim cart)                                   │
│     ├─ 確認接收藥師調撥的藥品                                           │
│     └─ PWA 顯示當前藥車庫存                                             │
│                                                                         │
│  2. 術中用藥                                                            │
│     ├─ 從藥車庫存選擇藥品                                               │
│     ├─ 記錄用藥 → 扣減藥車庫存 (非 pharmacy)                            │
│     ├─ 管制藥需見證人 / break-glass                                     │
│     └─ 產生 medication_usage_event (計費用)                             │
│                                                                         │
│  3. 班次結束                                                            │
│     ├─ 執行「交班清點」                                                 │
│     ├─ 逐項清點藥車剩餘數量                                             │
│     ├─ 系統比對預期 vs 實際                                             │
│     │   ├─ 相符 → 自動關閉班次                                          │
│     │   └─ 差異 → 標記待藥師核對                                        │
│     └─ 未用完藥品可選擇歸還或留置                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.5 管制藥特殊處理

| 操作 | 管制藥要求 |
|------|-----------|
| **調撥出庫** | 藥師 + 見證人雙簽 |
| **接收** | 麻醉護理師確認清點 |
| **術中使用** | 一二級需見證人或 break-glass |
| **交班清點** | 逐瓶/逐 amp 核對 |
| **差異處理** | 必須藥師核對 + 調查報告 |
| **歸還** | 藥師確認入庫 + 雙簽 |

### 9.6 離線支援

```python
class OfflineCartStrategy:
    """
    離線時藥車操作策略
    """

    # 用藥記錄: 允許離線操作
    MEDICATION_USAGE = "ALLOWED_OFFLINE"

    # 藥車認領: 需上線 (初始化藥車庫存)
    CART_CLAIM = "ONLINE_REQUIRED"

    # 交班清點: 允許離線清點，上線後同步
    RECONCILIATION = "ALLOWED_OFFLINE_SYNC_LATER"

    # 調撥接收: 允許離線確認，上線後同步
    DISPATCH_RECEIVE = "ALLOWED_OFFLINE_SYNC_LATER"
```

---

## 10. v1.2 審閱回饋整合 (Gemini + ChatGPT)

> **2026-01-20 更新**: 整合 Gemini 與 ChatGPT 的審閱回饋，補充 Critical 缺漏項目。

### 10.1 管制藥「殘餘量銷毀」記錄 (Wastage Tracking)

**問題**: 醫師打了 150mg Propofol (200mg/vial)，系統只記錄使用 1 vial，剩下 50mg「流向不明」。在法律上可能被懷疑私吞。

**修正**: 明確記錄 `administered_amount` 與 `waste_amount`：

```sql
-- controlled_drug_log 新增欄位
ALTER TABLE controlled_drug_log ADD COLUMN administered_amount REAL;  -- 實際給藥量 (150mg)
ALTER TABLE controlled_drug_log ADD COLUMN waste_amount REAL;         -- 銷毀量 (50mg)
ALTER TABLE controlled_drug_log ADD COLUMN wastage_witnessed_by TEXT; -- 銷毀見證人
ALTER TABLE controlled_drug_log ADD COLUMN wastage_timestamp TEXT;    -- 銷毀時間

-- 計算邏輯
-- waste_amount = (unit_size × billing_quantity) - administered_amount
-- 例: (200mg × 1 vial) - 150mg = 50mg 待銷毀
```

**UI 修正**: 見證人簽名提示改為：
```
「見證給藥 150mg 並銷毀 50mg」
"Witnessing administration of 150mg AND wastage of 50mg"
```

### 10.2 時間計費防呆 (Max Duration Guard)

**問題**: 醫師忘記按 `ANESTHESIA_END`，系統持續計費至天價。

**修正**: 實作「逾時保護 (Sanity Check)」：

```python
# 配置
MAX_ANESTHESIA_DURATION_HOURS = 12  # 可設定閾值

async def check_open_anesthesia_cases():
    """
    排程任務: 每小時檢查未結案麻醉案例
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # 找出有 ANESTHESIA_START 但無 ANESTHESIA_END 的案例
        cursor.execute("""
            SELECT c.case_id, ce.timestamp as start_time
            FROM anesthesia_cases c
            JOIN case_events ce ON c.case_id = ce.case_id
            WHERE ce.event_type = 'ANESTHESIA_START'
              AND c.case_id NOT IN (
                SELECT case_id FROM case_events WHERE event_type = 'ANESTHESIA_END'
              )
              AND c.case_status NOT IN ('CANCELLED', 'BILLING_REVIEW_NEEDED')
        """)

        for row in cursor.fetchall():
            start_time = datetime.fromisoformat(row['start_time'])
            elapsed_hours = (datetime.now() - start_time).total_seconds() / 3600

            if elapsed_hours > MAX_ANESTHESIA_DURATION_HOURS:
                # 標記需審查，暫停自動計費
                cursor.execute("""
                    UPDATE anesthesia_cases
                    SET case_status = 'BILLING_REVIEW_NEEDED',
                        billing_review_reason = 'DURATION_EXCEEDED'
                    WHERE case_id = ?
                """, (row['case_id'],))

                # 發送通知
                await notify_anesthesiologist(row['case_id'],
                    f"麻醉時間超過 {MAX_ANESTHESIA_DURATION_HOURS} 小時，請確認是否結案")
```

### 10.3 三帳本強制綁定 (Three-Ledger Binding)

**問題**: 臨床記錄、庫存、計費三套帳本可能因重試/離線導致不一致。

**修正**: 定義「複合交易 ID」(Composite Transaction ID) 綁定三帳本：

```python
from dataclasses import dataclass
from typing import Optional
import hashlib

@dataclass
class MedicationCompositeTransaction:
    """
    一次用藥產生三個關聯記錄
    """
    # 共享識別碼 (Deterministic)
    idempotency_key: str  # hash(case_id + client_event_uuid)

    # 三帳本記錄 ID
    timeline_event_id: str           # case_events.event_id
    inventory_txn_id: Optional[str]  # pharmacy_transactions.transaction_id
    billing_item_id: str             # medication_usage_events.id

    # 關聯
    source_record_id: str            # 原始來源 (client_event_uuid)


def generate_idempotency_key(case_id: str, client_event_uuid: str) -> str:
    """
    決定性產生冪等鍵 (Deterministic Idempotency Key)

    規則: hash(case_id + client_event_uuid)

    客戶端必須在 enqueue 前先 persist client_event_uuid，
    確保重送時 key 不變。
    """
    raw = f"{case_id}:{client_event_uuid}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

**Server-Side Atomic Operation**:

```python
@router.post("/cases/{case_id}/medication")
async def add_medication_atomic(case_id: str, request: MedicationAdminRequest):
    """
    原子性用藥記錄 - 確保三帳本同步
    """
    idempotency_key = generate_idempotency_key(case_id, request.client_event_uuid)

    # 1. 冪等性檢查
    existing = get_by_idempotency_key(idempotency_key)
    if existing:
        return existing  # 返回已存在記錄，不重複建立

    # 2. 原子交易
    with get_db() as conn:
        conn.execute("BEGIN TRANSACTION")
        try:
            # 2a. 臨床事件
            timeline_event_id = insert_timeline_event(conn, ...)

            # 2b. 庫存扣減
            inventory_txn_id = insert_inventory_txn(conn, ...)

            # 2c. 計費項目
            billing_item_id = insert_billing_item(conn, ...)

            # 2d. 寫入複合交易記錄
            conn.execute("""
                INSERT INTO medication_composite_txn
                (idempotency_key, timeline_event_id, inventory_txn_id, billing_item_id)
                VALUES (?, ?, ?, ?)
            """, (idempotency_key, timeline_event_id, inventory_txn_id, billing_item_id))

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
```

### 10.4 單位換算修正 (Decimal Precision)

**問題**: `int(billing_quantity)` 會截斷小數，輸液、infusion 會算錯。

**修正**: 使用 `Decimal`，分離 `billing_quantity` 與 `inventory_deduct_quantity`：

```python
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

def calculate_billing_quantity_v2(
    clinical_dose: Decimal,
    clinical_unit: str,
    content_per_unit: Decimal,
    content_unit: str,
    billing_rounding: str
) -> tuple[Decimal, Decimal]:
    """
    Returns:
        (billing_quantity, inventory_deduct_quantity)

    Note: 這兩個值可能不同
    - billing_quantity: 計費用 (可能是小數，如 2.5 units)
    - inventory_deduct_quantity: 庫存扣減用 (通常是整數，開封即消耗)
    """
    # 單位轉換
    dose_normalized = normalize_unit(clinical_dose, clinical_unit, content_unit)

    # 計算原始數量
    raw_quantity = dose_normalized / content_per_unit

    # 計費數量 (保留小數)
    if billing_rounding == 'CEIL':
        billing_quantity = raw_quantity.quantize(Decimal('0.01'), rounding=ROUND_CEILING)
    elif billing_rounding == 'EXACT':
        billing_quantity = raw_quantity.quantize(Decimal('0.01'))
    else:
        billing_quantity = raw_quantity.quantize(Decimal('1'), rounding=ROUND_CEILING)

    # 庫存扣減 (通常向上取整，開封即消耗)
    inventory_deduct_quantity = raw_quantity.quantize(Decimal('1'), rounding=ROUND_CEILING)

    return billing_quantity, inventory_deduct_quantity
```

### 10.5 交易類型分類 (Transaction Taxonomy)

**問題**: 需明確定義哪些操作產生計費、哪些只是庫存移動。

**修正**: 定義標準交易類型：

```python
class InventoryTransactionType(str, Enum):
    """
    庫存交易類型 (統一定義)
    """
    # === 產生計費 ===
    ADMINISTER = "ADMINISTER"      # 臨床給藥 → 計費

    # === 不產生計費 ===
    WITHDRAW = "WITHDRAW"          # 從藥櫃取出 (到藥車/case)
    WASTE = "WASTE"                # 銷毀 (管制藥需見證)
    RETURN = "RETURN"              # 歸還未用完
    TRANSFER = "TRANSFER"          # 站點間調撥 (DISPATCH/RECEIPT)
    ADJUST = "ADJUST"              # 盤點調整
    EXPIRED = "EXPIRED"            # 過期報廢


# 計費規則
BILLABLE_TRANSACTIONS = {InventoryTransactionType.ADMINISTER}

def should_create_billing_item(txn_type: InventoryTransactionType) -> bool:
    return txn_type in BILLABLE_TRANSACTIONS
```

### 10.6 管制藥 Server-Side 強制

**問題**: 雙人覆核只在 UI 層，可被繞過。

**修正**: Server-side 強制驗證：

```python
@router.post("/cases/{case_id}/medication")
async def add_medication_with_validation(case_id: str, request: MedicationAdminRequest):
    """
    管制藥 Server-Side 驗證
    """
    med = get_medicine(request.drug_code)

    if med.is_controlled_drug and med.controlled_level in (1, 2):
        # 一二級管制藥必須有見證人或 break-glass
        if not request.witness_id and not request.is_break_glass:
            raise HTTPException(
                status_code=422,
                detail="一二級管制藥需見證人 (witness_id) 或 break-glass 授權"
            )

        # Break-glass 必須有原因
        if request.is_break_glass and not request.break_glass_reason:
            raise HTTPException(
                status_code=422,
                detail="Break-glass 必須提供原因 (break_glass_reason)"
            )

    # 驗證通過後才執行
    return await execute_medication_admin(case_id, request)


# 結案時強制檢查
async def validate_case_closure(case_id: str):
    """
    結案前驗證: 管制藥 reconciliation 必須完成
    """
    pending_controlled = get_pending_controlled_reconciliation(case_id)

    if pending_controlled:
        raise HTTPException(
            status_code=422,
            detail=f"管制藥 reconciliation 未完成: {pending_controlled}"
        )
```

### 10.7 價格凍結與 EXPORTED 鎖定

**問題**: 計費後價格變動可能導致帳務不一致。

**修正**: 計費時凍結價格版本，EXPORTED 後鎖定：

```sql
-- medication_usage_events 新增欄位
ALTER TABLE medication_usage_events ADD COLUMN pricebook_version_id TEXT;
ALTER TABLE medication_usage_events ADD COLUMN effective_price_date TEXT;
ALTER TABLE medication_usage_events ADD COLUMN is_locked BOOLEAN DEFAULT 0;

-- EXPORTED 後自動鎖定
CREATE TRIGGER lock_on_export
AFTER UPDATE ON medication_usage_events
WHEN NEW.billing_status = 'EXPORTED' AND OLD.billing_status != 'EXPORTED'
BEGIN
    UPDATE medication_usage_events
    SET is_locked = 1
    WHERE id = NEW.id;
END;

-- 禁止修改已鎖定記錄 (需用 VOID + 補償)
CREATE TRIGGER prevent_locked_update
BEFORE UPDATE ON medication_usage_events
WHEN OLD.is_locked = 1 AND NEW.is_locked = 1
BEGIN
    SELECT RAISE(ABORT, 'Cannot modify locked billing record. Use VOID + compensating transaction.');
END;
```

### 10.8 撤銷操作 = 反向事件 (VOID Pattern)

**問題**: 直接刪除會破壞審計軌跡。

**修正**: 撤銷操作產生反向事件：

```python
@router.delete("/cases/{case_id}/medication/{event_id}")
async def void_medication_event(case_id: str, event_id: str, reason: str, actor_id: str):
    """
    撤銷用藥記錄 (VOID Pattern)

    不真正刪除，而是:
    1. 保留原事件
    2. 新增 MEDICATION_ADMIN_VOID 反向事件
    3. 新增庫存補償交易
    4. 新增計費補償項目
    """
    original_event = get_medication_event(event_id)

    if original_event.billing_status == 'EXPORTED':
        raise HTTPException(400, "已匯出 CashDesk 的記錄無法撤銷，請聯繫財務處理")

    with get_db() as conn:
        conn.execute("BEGIN TRANSACTION")

        # 1. 標記原事件為 VOIDED
        conn.execute("""
            UPDATE case_events SET voided = 1, voided_reason = ?, voided_by = ?, voided_at = ?
            WHERE event_id = ?
        """, (reason, actor_id, datetime.now().isoformat(), event_id))

        # 2. 新增 VOID 事件 (審計用)
        void_event_id = f"VOID-{event_id}"
        conn.execute("""
            INSERT INTO case_events (event_id, case_id, event_type, payload, actor_id, timestamp)
            VALUES (?, ?, 'MEDICATION_ADMIN_VOID', ?, ?, ?)
        """, (void_event_id, case_id, json.dumps({
            "original_event_id": event_id,
            "reason": reason
        }), actor_id, datetime.now().isoformat()))

        # 3. 庫存補償 (回補)
        conn.execute("""
            INSERT INTO pharmacy_transactions (transaction_type, medicine_code, quantity, reason)
            VALUES ('VOID_REVERSAL', ?, ?, ?)
        """, (original_event.drug_code, original_event.billing_quantity,
              f"Void reversal for {event_id}"))

        conn.execute("""
            UPDATE medicines SET current_stock = current_stock + ? WHERE medicine_code = ?
        """, (original_event.billing_quantity, original_event.drug_code))

        # 4. 計費補償
        conn.execute("""
            INSERT INTO medication_usage_events (case_id, medicine_code, quantity, billing_status, reference_event_id)
            VALUES (?, ?, ?, 'VOIDED', ?)
        """, (case_id, original_event.drug_code, -original_event.billing_quantity, event_id))

        conn.commit()

    return {"voided_event_id": event_id, "void_reference": void_event_id}
```

### 10.9 Handoff Package 完整性

**問題**: Handoff 只包含藥品費，漏掉麻醉/手術處置費 (這是最大筆的款項！)。

**修正**: 明確定義 Handoff 必須包含所有計費類別：

```python
@router.get("/cases/{case_id}/billing/handoff")
async def generate_handoff_package(case_id: str):
    """
    產生 CashDesk Handoff Package

    CRITICAL: 必須包含所有計費類別
    - anesthesia_fees: 麻醉處置費 (Base + Time + ASA)
    - surgical_fees: 手術處置費 (主刀 + 助手)
    - medication_fees: 藥品費
    - supply_fees: 耗材費
    - blood_fees: 血品費
    """

    # 1. 麻醉處置費 (最重要!)
    anesthesia = await calculate_anesthesia_fee(case_id)
    if not anesthesia:
        raise HTTPException(400, "麻醉處置費計算失敗，請確認 ANESTHESIA_START/END 已記錄")

    # 2. 手術處置費
    surgical = await calculate_surgical_fee(case_id)

    # 3. 藥品費 (from medication_usage_events)
    medications = await get_medication_billing_items(case_id)

    # 4. 耗材費
    supplies = await get_supply_billing_items(case_id)

    # 5. 血品費
    blood = await get_blood_billing_items(case_id)

    # 組合 Handoff Package
    handoff = CashDeskHandoffPackage(
        case_id=case_id,
        generated_at=datetime.now().isoformat(),

        # 所有計費項目
        billable_items=[
            # 麻醉處置費
            BillableItem(
                code=anesthesia['nhi_code'],  # 如 96005C
                name=anesthesia['name'],       # 全身麻醉
                qty=1,
                unit_price=anesthesia['total'],
                category='ANESTHESIA_FEE'
            ),
            # 手術處置費
            *[BillableItem(
                code=s['nhi_code'],
                name=s['name'],
                qty=1,
                unit_price=s['fee'],
                category='SURGICAL_FEE'
            ) for s in surgical['items']],
            # 藥品
            *[BillableItem(
                code=m['medicine_code'],
                name=m['generic_name'],
                qty=m['quantity'],
                unit_price=m['unit_price'],
                category='MEDICATION'
            ) for m in medications],
            # 耗材
            *supplies,
            # 血品
            *blood
        ],

        # 分項小計
        subtotals={
            'anesthesia': anesthesia['total'],
            'surgical': sum(s['fee'] for s in surgical['items']),
            'medication': sum(m['total'] for m in medications),
            'supply': sum(s.unit_price * s.qty for s in supplies),
            'blood': sum(b.unit_price * b.qty for b in blood)
        },

        grand_total=...,

        # 驗證簽章
        checksum=calculate_checksum(...)
    )

    return handoff
```

### 10.10 Phase 8: 審閱回饋實作 (v1.2 新增)

- [x] 管制藥殘餘量記錄 (`waste_amount`, `wastage_witnessed_by`) - schema added
- [ ] 時間計費防呆 (MAX_DURATION_HOURS 檢查 + 通知)
- [ ] 三帳本複合交易 (`medication_composite_txn` 表)
- [x] 冪等鍵產生規則 (`generate_idempotency_key`) - SHA256(case_id:client_event_uuid)[:32]
- [x] 單位換算 Decimal 修正 (convert_to_base_unit)
- [ ] 交易類型分類 (`InventoryTransactionType` enum)
- [x] 管制藥 Server-side 強制驗證 (process_medication_admin)
- [x] 價格凍結 + EXPORTED 鎖定 (is_locked trigger)
- [x] VOID pattern 撤銷流程 (is_voided, voided_by, void_reference_id)
- [x] Handoff Package 完整性驗證 (generate_cashdesk_handoff)

---

## 11. 驗收標準

| 項目 | 驗收條件 |
|------|----------|
| **藥品庫存** | |
| 用藥記錄 | 點擊藥品 → 記錄 timeline + 扣庫存 |
| 單位換算 | 150mg Propofol → 計費 1 vial |
| 庫存顯示 | 藥品選擇時顯示剩餘數量 |
| 負庫存 | 庫存不足仍可記錄，顯示警告 |
| 管制藥 | 一二級需見證人或 break-glass |
| Break-glass | 可單人操作，24hr 內需補核准 |
| 藥品計費 | 產生 medication_usage_events |
| 離線 | 斷網時可操作，上線後同步 |
| **處置費 (v1.1)** | |
| 麻醉處置費 | 手術結案 → 自動計算麻醉費 (基本費+時間費+ASA加成) |
| 手術處置費 | 手術結案 → 自動計算手術費 (主刀+助手) |
| 時間計算 | ANESTHESIA_START → ANESTHESIA_END → 計算時間單位 |
| ASA 加成 | ASA III +20%, ASA IV +40%, +E +10% |
| **CashDesk 整合 (v1.1)** | |
| Handoff Package | `/billing/handoff` 回傳完整計費明細 JSON |
| 分項小計 | 正確顯示 anesthesia/surgery/medication/supply/blood 小計 |
| 匯出功能 | `export-to-cashdesk` 更新 billing_status = EXPORTED |

---

## 12. 藥品主檔資料同步策略 (Medication Data Sync)

> **v1.2 新增**: 定義 MIRS ↔ CIRS 藥品主檔資料的同步方式。

### 12.1 資料架構

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    藥品主檔資料流向                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────┐                              │
│  │  resilience_formulary.json            │                              │
│  │  (共用藥品主檔 - 急救 + 麻醉)          │                              │
│  │  位置: CIRS/shared/data/              │                              │
│  │       MIRS/shared/data/ (複製)        │                              │
│  └───────────────────────────────────────┘                              │
│                         │                                               │
│          ┌──────────────┴──────────────┐                                │
│          ▼                             ▼                                │
│  ┌─────────────────────┐     ┌─────────────────────┐                    │
│  │  MIRS                │     │  CIRS                │                   │
│  │  medicines 表        │     │  medication_identity │                   │
│  │  (權威庫存)          │────▶│  _snapshot (快照)    │                   │
│  │                      │ 同步 │                     │                   │
│  │  + current_stock     │     │  medication_billing  │                   │
│  │  + pharmacy_txns     │     │  _snapshot (計價)    │                   │
│  └─────────────────────┘     └─────────────────────┘                    │
│          │                             │                                │
│          ▼                             ▼                                │
│  ┌─────────────────────┐     ┌─────────────────────┐                    │
│  │  Anesthesia PWA     │     │  CashDesk PWA       │                    │
│  │  (用藥記錄)          │     │  (計費查詢)          │                   │
│  └─────────────────────┘     └─────────────────────┘                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 12.2 資料來源: resilience_formulary.json

**位置**: `CIRS/shared/data/resilience_formulary.json`
**格式**: JSON with 100+ medications (急救 + 麻醉)

```json
{
  "medications": [
    {
      "nhi_code": "AC06775209",           // 健保碼 → medicine_code
      "anesthesia_code": "EPI",           // 麻醉短碼 (可選)
      "name_en": "Epinephrine Inj 1mg/1ml",
      "name_zh": "腎上腺素注射液",
      "spec": "1mg/1mL",
      "dosage_form": "INJ",
      "route": "IV/IM/SC",
      "controlled_level": 0,               // 0=非管制, 1-4=管制等級
      "category": "EMERGENCY",
      "nhi_points": 18,                    // 健保點數 → nhi_price
      "billing_unit": "支",                // → unit
      "content_per_unit": 1.0,             // 每單位含量
      "content_unit": "mg",                // 含量單位
      "billing_rounding": "CEIL"           // 進位規則
    }
  ]
}
```

### 12.3 MIRS Seeder 實作

**檔案**: `seeder_medications.py`

```python
#!/usr/bin/env python3
"""
藥品主檔 Seeder - 從 resilience_formulary.json 匯入 MIRS medicines 表
"""

import json
import sqlite3
from pathlib import Path

FORMULARY_PATH = Path(__file__).parent / "shared/data/resilience_formulary.json"
DB_PATH = Path(__file__).parent / "database/mirs.db"


def seed_medications():
    """匯入藥品主檔"""

    # 讀取 JSON
    with open(FORMULARY_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for med in data['medications']:
        # 轉換欄位
        medicine_code = med.get('nhi_code')  # 使用健保碼作為 medicine_code
        controlled_level = None
        if med.get('controlled_level', 0) > 0:
            controlled_level = f"LEVEL_{med['controlled_level']}"

        # 轉換 dosage_form
        dosage_form_map = {
            'INJ': 'INJECTION',
            'TAB': 'TABLET',
            'CAP': 'CAPSULE',
            'SOL': 'SOLUTION',
            'INFUSION': 'SOLUTION'
        }
        dosage_form = dosage_form_map.get(med.get('dosage_form'), 'INJECTION')

        # 插入或更新
        cursor.execute("""
            INSERT OR REPLACE INTO medicines (
                medicine_code, generic_name, brand_name,
                dosage_form, strength, unit,
                is_controlled_drug, controlled_level,
                nhi_price,
                content_per_unit, content_unit, billing_rounding,
                current_stock, min_stock, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            medicine_code,
            med.get('name_zh'),
            med.get('name_en'),
            dosage_form,
            med.get('spec'),
            med.get('billing_unit', '支'),
            1 if med.get('controlled_level', 0) > 0 else 0,
            controlled_level,
            med.get('nhi_points', 0),
            med.get('content_per_unit'),
            med.get('content_unit'),
            med.get('billing_rounding', 'CEIL'),
            10,  # 預設庫存
            2,   # 最低庫存
            1    # is_active
        ))

    conn.commit()
    print(f"Seeded {len(data['medications'])} medications")
    conn.close()


if __name__ == "__main__":
    seed_medications()
```

### 12.4 Schema 擴充 (v1.2 新增欄位)

```sql
-- 新增 medicines 表單位換算欄位
ALTER TABLE medicines ADD COLUMN content_per_unit REAL;
ALTER TABLE medicines ADD COLUMN content_unit TEXT;
ALTER TABLE medicines ADD COLUMN billing_rounding TEXT DEFAULT 'CEIL';

-- 新增索引
CREATE INDEX IF NOT EXISTS idx_medicines_content ON medicines(content_per_unit, content_unit);
```

### 12.5 同步策略

| 方向 | 觸發時機 | 內容 |
|------|----------|------|
| **JSON → MIRS** | 啟動時 / 手動 | 完整匯入 medicines 表 |
| **JSON → CIRS** | 啟動時 / 手動 | 匯入 medication_identity_snapshot |
| **MIRS → CIRS** | 定時 (5min) / 事件 | 庫存變動同步 (future) |

### 12.6 實作步驟

**Phase 0: 資料準備**

- [x] 複製 `resilience_formulary.json` 到 MIRS (`shared/data/`)
- [x] 新增 `content_per_unit`, `content_unit`, `billing_rounding` 欄位到 medicines 表 (migration)
- [x] 建立 `seeder_medications.py` 腳本
- [x] 執行 seeder 匯入藥品主檔 (44 medications, 7 controlled)
- [x] 驗證 Anesthesia PWA 可讀取藥品清單 (GET /quick-drugs-with-inventory)

### 12.7 藥物流程架構說明 (Medication Flow Architecture)

> **2026-01-20 架構決策 (Gemini/ChatGPT 審閱確認)**:
> - 使用「實體庫存層級 (Inventory Hierarchy)」觀點，非「軟體 PWA」觀點
> - CIRS = Hub (權威庫存)，MIRS = Satellite (衛星庫)
> - Anesthesia PWA = Consumer (消耗端點)，**直接扣 MIRS 庫存，非調撥對象**

```
┌─────────────────────────────────────────────────────────────────────────┐
│              Inventory Hierarchy (實體庫存層級觀點)                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  LEVEL 1: CIRS Main Inventory (總庫/Hub)                        │    │
│  │  ───────────────────────────────────────────────────────────    │    │
│  │  • 權威庫存 (Authoritative Stock)                               │    │
│  │  • 採購、驗收、總量治理                                          │    │
│  │  • 管制藥總帳 (符合法規)                                         │    │
│  │  • 操作者: CIRS Pharmacy PWA (Hub control-plane)                │    │
│  └──────────────────────────┬──────────────────────────────────────┘    │
│                             │                                           │
│                     MED_DISPATCH (調撥發貨)                              │
│                     • QR Code 調撥單                                    │
│                     • 批號、效期追蹤                                     │
│                             │                                           │
│                             ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  LEVEL 2: MIRS Satellite Inventory (衛星庫)                     │    │
│  │  ───────────────────────────────────────────────────────────    │    │
│  │  • 本地庫存 (Ground Truth when offline)                         │    │
│  │  • 接收調撥 (MED_RECEIPT)                                       │    │
│  │  • 臨床消耗的庫存邊界 (Inventory Boundary)                       │    │
│  │  • 操作者: MIRS Pharmacy PWA (Satellite control-plane)          │    │
│  └──────────────────────────┬──────────────────────────────────────┘    │
│                             │                                           │
│                     DIRECT DEDUCTION (直接扣庫)                          │
│                     ※ 非調撥！消耗端點直接扣減 MIRS 庫存                   │
│                             │                                           │
│                             ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  LEVEL 3: Consumption Endpoints (消耗端點)                      │    │
│  │  ───────────────────────────────────────────────────────────    │    │
│  │  • Anesthesia PWA: 臨床用藥記錄、觸發庫存扣減                    │    │
│  │  • EMT PWA: 急救藥物使用                                        │    │
│  │  • 產生事件: CTRL_WITHDRAW / USAGE / WASTE / RETURN             │    │
│  │  ※ 這些不是庫存點，是消耗端                                      │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════    │
│  CANONICAL CHAIN (標準路徑):                                            │
│  CIRS (Hub) ──[MED_DISPATCH]──▶ MIRS (Satellite) ◀──[DEDUCT]── PWA     │
│  ═══════════════════════════════════════════════════════════════════    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**角色定義 (Role Definition)**:

| 層級 | 實體 | 角色 | 操作者 | 職責 |
|------|------|------|--------|------|
| L1 | CIRS 總庫 | MEDICATION_HUB | CIRS Pharmacy PWA | 採購/驗收/調撥發貨/管制藥總帳 |
| L2 | MIRS 衛星庫 | SATELLITE_PHARMACY | MIRS Pharmacy PWA | 接收調撥/本地庫存管理/扣庫 |
| L3 | Anesthesia | CONSUMPTION_ENDPOINT | Anesthesia PWA | 臨床用藥記錄/觸發扣庫 |
| L3 | EMT | CONSUMPTION_ENDPOINT | EMT PWA | 急救藥物使用/觸發扣庫 |

**重要澄清**:
- ❌ 錯誤理解：「MIRS 調撥給 Anesthesia PWA」
- ✅ 正確理解：「Anesthesia PWA 直接扣減 MIRS 庫存」（無調撥，直接扣庫）

### 12.8 藥師稽核功能位置 (Pharmacist Audit Location)

> **核心原則 (Gemini/ChatGPT 審閱確認)**:
> - **Capture locally; Audit centrally** (本地記錄，中央稽核)
> - 現場產生不可否認證據，藥師集中複核
> - Safety-II: 斷網時前線必須能獨立結案

#### 12.8.1 雙層稽核模型 (Two-Layer Audit Model)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Two-Layer Audit Architecture                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  LAYER A: Point-of-Care Capture (現場證據記錄)                  │    │
│  │  位置: MIRS / Anesthesia PWA                                    │    │
│  │  ───────────────────────────────────────────────────────────    │    │
│  │  • 產生不可否認的臨床/管制藥交易證據                             │    │
│  │  • 雙人覆核 (Dual Signature)                                    │    │
│  │  • 見證簽章 (Witness)                                           │    │
│  │  • Break-glass 緊急授權                                         │    │
│  │  • Case-end 對帳 (退回/銷毀)                                    │    │
│  │  • ✓ 離線可運作                                                 │    │
│  └──────────────────────────┬──────────────────────────────────────┘    │
│                             │                                           │
│                      SYNC (同步)                                         │
│                      POST /api/audit/sync                               │
│                             │                                           │
│                             ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  LAYER B: Central Audit Review (中央稽核複核)                   │    │
│  │  位置: CIRS Pharmacy PWA + CIRS Hub                             │    │
│  │  ───────────────────────────────────────────────────────────    │    │
│  │  • 藥師複核 (Pharmacist Review)                                 │    │
│  │  • 例外處理 (Exception Handling)                                │    │
│  │  • 跨站對帳 (Cross-Site Reconciliation)                         │    │
│  │  • 合規報表輸出 (Compliance Export)                             │    │
│  │  • ✗ 需網路連線                                                 │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 12.8.2 Pharmacy PWA Context-Aware 模式

> **Universal Fleet 設計**: Pharmacy PWA 根據連線的系統自動切換功能。

```typescript
// Pharmacy PWA - Context-Aware Mode Switching
interface PharmacyPWAContext {
  connectedSystem: 'CIRS' | 'MIRS';
  availableFeatures: string[];
}

function getContextFeatures(context: PharmacyPWAContext): string[] {
  if (context.connectedSystem === 'CIRS') {
    // ══════════════════════════════════════════════════════════
    // CIRS MODE - Hub Operations (總庫操作)
    // ══════════════════════════════════════════════════════════
    return [
      'MED_DISPATCH',              // 調撥發貨
      'RECEIVING_VERIFICATION',    // 廠商進貨驗收
      'CONTROLLED_DRUG_LEDGER',    // 管制藥總帳
      'GLOBAL_AUDIT_REPORT',       // 全站稽核報表 (唯讀)
      'CROSS_SITE_RECONCILIATION', // 跨站對帳
      'COMPLIANCE_EXPORT',         // 合規報表輸出
    ];
  }

  if (context.connectedSystem === 'MIRS') {
    // ══════════════════════════════════════════════════════════
    // MIRS MODE - Satellite Operations (衛星庫操作)
    // ══════════════════════════════════════════════════════════
    return [
      'MED_RECEIPT',               // 接收調撥
      'LOCAL_INVENTORY',           // 本地庫存管理
      'LOCAL_AUDIT',               // 本地稽核 (可簽核)
      'CONTROLLED_DRUG_SIGN',      // 管制藥雙簽
      'WASTAGE_WITNESS',           // 銷毀見證
      'CASE_END_RECONCILIATION',   // Case-end 對帳
    ];
  }

  return [];
}
```

**功能對照表**:

| 功能 | CIRS Mode | MIRS Mode | 說明 |
|------|:---------:|:---------:|------|
| 調撥發貨 (MED_DISPATCH) | ✓ | ✗ | Hub 發貨給 Satellite |
| 接收調撥 (MED_RECEIPT) | ✗ | ✓ | Satellite 接收 Hub 發貨 |
| 廠商進貨驗收 | ✓ | ✗ | 只有 Hub 對外採購 |
| 管制藥總帳 | ✓ | ✗ | Hub 維護權威總帳 |
| 本地稽核 (可簽核) | ✗ | ✓ | 現場簽核、銷毀見證 |
| 全站稽核報表 | ✓ (唯讀) | ✗ | 中央查看所有站點 |
| 跨站對帳 | ✓ | ✗ | Hub 負責跨站 reconciliation |
| Case-end 對帳 | ✗ | ✓ | 手術結束後現場對帳 |

#### 12.8.3 責任切割矩陣 (Responsibility Matrix)

| 職責 | 系統 | 操作者 | 離線支援 | 備註 |
|------|------|--------|:--------:|------|
| 採購/驗收/總量治理 | CIRS Hub | CIRS Pharmacy PWA | ✗ | Hub 職責 |
| 調撥發貨 | CIRS Hub | CIRS Pharmacy PWA | ✗ | MED_DISPATCH |
| 接收調撥 | MIRS Satellite | MIRS Pharmacy PWA | ✓ | MED_RECEIPT |
| 臨床用藥記錄 | MIRS | Anesthesia PWA | ✓ | 直接扣庫 |
| 管制藥雙簽 | MIRS | Anesthesia/Pharmacy PWA | ✓ | 現場雙人覆核 |
| 銷毀見證 | MIRS | Pharmacy PWA (MIRS Mode) | ✓ | 現場見證簽章 |
| 本地稽核簽核 | MIRS | Pharmacy PWA (MIRS Mode) | ✓ | 斷網可結案 |
| 管制藥總帳 | CIRS Hub | CIRS Pharmacy PWA | ✗ | 權威帳本 |
| 合規報表輸出 | CIRS Hub | CIRS Pharmacy PWA | ✗ | 法規報表 |
| 跨站異常分析 | CIRS Hub | CIRS Pharmacy PWA | ✗ | 全域視圖 |

#### 12.8.4 實作建議

**Phase 1: 現場證據記錄 (MIRS Side)**

- [ ] Anesthesia PWA 產生 `controlled_drug_event` 記錄
- [ ] 新增欄位: `dual_signature`, `witness_id`, `break_glass_reason`
- [ ] 實作 Case-end reconciliation UI (退回/銷毀確認)
- [ ] 本地 SQLite 儲存，支援離線

**Phase 2: Context-Aware Pharmacy PWA**

- [x] 實作 `getContextFeatures()` 根據連線系統切換功能 (setContextMode)
- [x] MIRS Mode: 新增 `LocalAudit` tab (本地稽核)
- [x] CIRS Mode: 新增 `GlobalAudit` tab (全域稽核儀表板)
- [ ] 新增 `WastageWitness.vue` (銷毀見證模組)

**Phase 3: 同步與中央報表**

- [ ] 實作 `POST /api/audit/sync` 同步 API
- [ ] 稽核記錄表新增欄位: `audit_source = 'MIRS_LOCAL' | 'CIRS_CENTRAL'`
- [ ] CIRS Hub 接收同步後僅供「查看」，不重新簽核
- [ ] 建立合規報表產生器 (Compliance Report Generator)

---

## 附錄

### A. 與 CIRS Spec 的關係

| 項目 | CIRS Spec (v1.2) | 本 Spec (MIRS v1.0) |
|------|------------------|---------------------|
| 架構 | 分佈式 (Hub → Satellite) | 單站 (直接扣庫) |
| 同步 | Event-driven sync | 離線佇列 + 上線同步 |
| Snapshot | 5 分鐘同步 | 不需要 (直接讀本地) |
| 價格解析 | 3-tier precedence | 直接讀 nhi_price |

### B. 修訂歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-20 | 初版 - 整合 Gemini/ChatGPT 審閱回饋 |
| v1.1 | 2026-01-20 | 擴充計費範圍: 新增麻醉處置費、手術處置費、CashDesk Handoff |
| v1.1 | 2026-01-20 | 新增 Section 9: 麻醉藥車調撥流程、交班清點、藥師核對機制 |
| v1.2 | 2026-01-20 | Section 10: Gemini/ChatGPT 審閱回饋整合 - 管制藥殘餘量、時間防呆、三帳本綁定、VOID pattern |
| v1.2 | 2026-01-20 | Section 12: 藥品主檔資料同步策略 - CIRS/MIRS formulary JSON 共用、seeder 實作 |
| v1.2 | 2026-01-20 | Section 12.7: 藥物流程架構說明 - CIRS進藥→MIRS調撥→消耗端點 |
| v1.2 | 2026-01-20 | Section 12.8: 藥師稽核功能位置建議 - 稽核 UI 下放 Pharmacy PWA，主站做合規報表 |
| v1.2 | 2026-01-20 | Migration: add_anesthesia_billing_columns.sql - 浪費追蹤、idempotency_key、VOID pattern |
| v1.2 | 2026-01-20 | **Gemini/ChatGPT 二次審閱**: Section 12.7/12.8 重構 - Inventory Hierarchy 觀點、Context-Aware PWA、Two-Layer Audit、責任切割矩陣 |

---

*De Novo Orthopedics Inc. © 2026*
