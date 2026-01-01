# xIRS 就診流程改進規格書

**Version:** 1.1
**Date:** 2026-01-01
**Status:** 核准實作
**Review:** Gemini + ChatGPT 專家審閱通過

---

## 0. 設計審閱總結

### 0.1 核心設計確認 ✅

| 設計決策 | 審閱結果 |
|----------|----------|
| `status` 與 `needs_*` 分離 | **高度肯定** - 避免單一 status 欄位的狀態爆炸問題 |
| 醫囑驅動 (CPOE) | **正確方向** - 沒有醫囑就不應進入執行隊列 |
| 待處置/待麻醉雙清單 | **直接修復問題** - 病患可同時出現在兩個清單 |

### 0.2 關鍵補強 (v1.1 新增)

| 補強項目 | 說明 |
|----------|------|
| **角色化 Claim** | 新增 `registration_claims` 表，支援多角色並存 |
| **Hub-Satellite 合約升版** | `RegistrationStub` 必須包含 `needs_*` 欄位 |
| **Server-side 防繞過** | 後端強制驗證，不能只靠 UI |

---

## 1. 問題描述

### 1.1 現狀

目前的流程：

```
掛號 (CIRS)
    ↓
看診中 (Doctor PWA 選取病患)
    ↓
??? (完成看診後，狀態不明確)
```

**問題：**
1. 掛號後病患會出現在麻醉 PWA 的「新增麻醉案例」候診名單
2. 但一旦被 Doctor PWA 選為「看診中」，就從麻醉 PWA 消失
3. 沒有明確的「需處置」「需麻醉」標記機制
4. 處置記錄和麻醉案例的建立都是「新增」模式，沒有候診清單

### 1.2 期望流程

```
掛號 (CIRS)
    ↓
看診 (Doctor PWA)
    ↓
看診完成 → 標記：
    ├── ☑ 需處置 → 病患出現在「待處置」清單
    ├── ☑ 需麻醉 → 病患出現在「待麻醉」清單
    └── 預設只有開藥，不需額外標記
```

---

## 2. 提案：Registration Status 擴展

### 2.1 新增狀態欄位

```sql
-- registrations 表新增欄位
ALTER TABLE registrations ADD COLUMN needs_procedure INTEGER DEFAULT 0;
ALTER TABLE registrations ADD COLUMN needs_anesthesia INTEGER DEFAULT 0;
ALTER TABLE registrations ADD COLUMN consultation_completed_at TIMESTAMP;
ALTER TABLE registrations ADD COLUMN consultation_by TEXT;
```

### 2.2 狀態流轉

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Registration Status                   │
                    ├─────────────────────────────────────────────────────────┤
                    │                                                          │
   WAITING ──────▶ IN_CONSULTATION ──────▶ CONSULTATION_DONE                  │
      │                   │                       │                            │
      │                   │                       ├── needs_procedure = 1      │
      │                   │                       │   → 顯示在「待處置」        │
      │                   │                       │                            │
      │                   │                       ├── needs_anesthesia = 1     │
      │                   │                       │   → 顯示在「待麻醉」        │
      │                   │                       │                            │
      │                   │                       └── 兩者皆否                  │
      │                   │                           → 直接 COMPLETED          │
      │                   │                                                     │
      │                   │                                                     │
      │                   ▼                                                     │
      │            ┌──────────────┐                                            │
      │            │  Doctor PWA  │                                            │
      │            │  完成看診    │                                            │
      │            │  ☐ 需處置    │                                            │
      │            │  ☐ 需麻醉    │                                            │
      │            └──────────────┘                                            │
      │                                                                         │
      └─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 子狀態與 PWA 對應

| needs_procedure | needs_anesthesia | 顯示清單 | 處理站 |
|-----------------|------------------|----------|--------|
| 0 | 0 | （完成） | - |
| 1 | 0 | 待處置 | Station PWA / Procedure PWA |
| 0 | 1 | 待麻醉 | Anesthesia PWA |
| 1 | 1 | 待處置 + 待麻醉 | 兩者皆可選取 |

---

## 3. 角色化 Claim 機制 (v1.1 關鍵補強)

### 3.1 問題：單一 Claim 造成互斥

**現狀問題：**
- Doctor PWA claim 病患後，Anesthesia PWA 看不到
- 單一 `claimed_by` 欄位無法支援「同時需要處置與麻醉」

**解決方案：角色化 Claim (Role-Scoped Claims)**

### 3.2 新增 registration_claims 表

```sql
CREATE TABLE registration_claims (
    id TEXT PRIMARY KEY,
    registration_id TEXT NOT NULL,
    claim_role TEXT NOT NULL CHECK (claim_role IN ('DOCTOR', 'PROCEDURE', 'ANESTHESIA')),
    claimed_by TEXT NOT NULL,
    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,  -- TTL 機制，可選
    released_at TIMESTAMP,

    -- 唯一約束：同一 registration 的同一 role 只能有一個 active claim
    UNIQUE(registration_id, claim_role)
        WHERE released_at IS NULL AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
);
```

### 3.3 Claim 語義

| 角色 | Claim 時機 | 效果 |
|------|-----------|------|
| DOCTOR | Doctor PWA 選取病患看診 | 其他醫師不能同時看診 |
| PROCEDURE | Procedure PWA 開始處置 | 其他處置站不能同時處置 |
| ANESTHESIA | Anesthesia PWA 建立案例 | 其他麻醉站不能同時接案 |

**關鍵：** 三種 Claim 互不影響！
- Doctor claim 不會阻擋 Anesthesia/Procedure
- 同一病患可同時被 PROCEDURE 和 ANESTHESIA claim（但各只能一個）

### 3.4 Claim API

```
POST /api/registrations/{reg_id}/claim
```

**Request:**
```json
{
  "role": "ANESTHESIA",
  "actor_id": "ANES-DR-001",
  "ttl_seconds": 7200  // 可選，2 小時後自動過期
}
```

**Response (成功):**
```json
{
  "success": true,
  "claim_id": "CLM-20260101-001",
  "registration_id": "REG-20260101-001",
  "role": "ANESTHESIA",
  "expires_at": "2026-01-01T12:30:00Z"
}
```

**Response (衝突 - 409):**
```json
{
  "success": false,
  "error": "ALREADY_CLAIMED",
  "claimed_by": "ANES-DR-002",
  "claimed_at": "2026-01-01T10:15:00Z",
  "message": "此病患已被其他麻醉站接手"
}
```

### 3.5 Release API

```
POST /api/registrations/{reg_id}/release-claim
```

**Request:**
```json
{
  "role": "ANESTHESIA"
}
```

---

## 4. API 變更

### 4.1 Doctor PWA - 完成看診

**現有：** 沒有明確的「完成看診」API

**新增：**

```
POST /api/registrations/{reg_id}/complete-consultation
```

**Request:**
```json
{
  "needs_procedure": true,
  "needs_anesthesia": false,
  "notes": "右腿清創術"
}
```

**Response:**
```json
{
  "success": true,
  "registration_id": "REG-20260101-001",
  "status": "CONSULTATION_DONE",
  "needs_procedure": true,
  "needs_anesthesia": false,
  "queues_added": ["PROCEDURE"]
}
```

### 3.2 待處置清單

**新增：**

```
GET /api/registrations/waiting/procedure
```

**Response:**
```json
{
  "items": [
    {
      "registration_id": "REG-20260101-001",
      "patient_id": "P001",
      "patient_name": "王小明",
      "triage_category": "YELLOW",
      "chief_complaint": "右腿骨折",
      "consultation_by": "Dr. 李",
      "consultation_completed_at": "2026-01-01T10:30:00",
      "notes": "右腿清創術",
      "waiting_minutes": 15
    }
  ]
}
```

### 3.3 待麻醉清單

**新增：**

```
GET /api/registrations/waiting/anesthesia
```

**Response:** 同上結構

### 3.4 處置完成

**新增：**

```
POST /api/registrations/{reg_id}/procedure-done
```

**Request:**
```json
{
  "procedure_case_id": "PROC-20260101-001"
}
```

### 3.5 麻醉完成

**現有 Anesthesia API 已有案例關閉機制**

```
POST /api/anesthesia/cases/{case_id}/close
```

**變更：** 關閉案例時，自動更新 `registrations.needs_anesthesia = 0`

---

## 4. UI 變更

### 4.1 Doctor PWA - 完成看診

```
┌─────────────────────────────────────────────────────────────────┐
│  完成看診                                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  病患：王小明 (REG-20260101-001)                                 │
│  主訴：右腿骨折                                                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ ☐ 需處置                                                    ││
│  │   處置說明：[________________________]                       ││
│  │                                                              ││
│  │ ☐ 需麻醉                                                    ││
│  │   麻醉備註：[________________________]                       ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  已開立處方：                                                    │
│  - Cefazolin 1g IV q8h                                          │
│  - Tramadol 50mg PO PRN                                         │
│                                                                  │
│                                        [取消]  [完成看診]        │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Anesthesia PWA - 新增案例

**現有設計：** 「新增麻醉案例」按鈕，手動輸入病歷號

**新設計：**

```
┌─────────────────────────────────────────────────────────────────┐
│  新增麻醉案例                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 待麻醉清單                                            [重整]││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ 🟡 ***0042 王小明                                           ││
│  │    右腿骨折清創術 · 醫師：Dr. 李                             ││
│  │    等待 15 分鐘                                      [選取] ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ 🟢 ***0088 李小華                                           ││
│  │    腹部探查術 · 醫師：Dr. 陳                                 ││
│  │    等待 5 分鐘                                       [選取] ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ─────────────── 或 ───────────────                              │
│                                                                  │
│  [掃描傷票 QR]  [手動輸入（緊急）]                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Station/Procedure PWA - 待處置清單

類似設計，顯示 `needs_procedure = 1` 的病患

---

## 5. 資料流整合

### 5.1 完整流程圖

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  CIRS Admin                                                                  │
│  ┌─────────┐                                                                │
│  │  掛號   │ ───────▶ registrations (status: WAITING)                       │
│  └─────────┘                                                                │
│                           │                                                  │
│                           ▼                                                  │
│  Doctor PWA              GET /api/registrations/waiting/list                 │
│  ┌─────────┐              │                                                  │
│  │ 選取病患│ ◀────────────┘                                                  │
│  └─────────┘                                                                │
│       │                                                                      │
│       │ POST /api/registrations/{id}/claim                                  │
│       ▼                                                                      │
│  status: IN_CONSULTATION                                                     │
│       │                                                                      │
│       │ [看診中... 開藥、診斷]                                               │
│       │                                                                      │
│       │ POST /api/registrations/{id}/complete-consultation                  │
│       │ { needs_procedure: true, needs_anesthesia: true }                   │
│       ▼                                                                      │
│  status: CONSULTATION_DONE                                                   │
│  needs_procedure: 1                                                          │
│  needs_anesthesia: 1                                                         │
│       │                                                                      │
│       ├──────────────────────────────────────────────────────────┐          │
│       │                                                          │          │
│       ▼                                                          ▼          │
│  Procedure PWA                                            Anesthesia PWA     │
│  GET /api/registrations/waiting/procedure      GET /api/registrations/waiting/anesthesia
│       │                                                          │          │
│       │ [選取病患，建立處置]                        [選取病患，建立麻醉案例]  │
│       │                                                          │          │
│       │ POST /api/registrations/{id}/procedure-done              │          │
│       ▼                                                          │          │
│  needs_procedure: 0                                              │          │
│       │                                                          │          │
│       │                                    POST /api/anesthesia/cases/{id}/close
│       │                                                          │          │
│       │                                                          ▼          │
│       │                                                  needs_anesthesia: 0 │
│       │                                                          │          │
│       └──────────────────────────────────────────────────────────┘          │
│                                     │                                        │
│                                     ▼                                        │
│                           status: COMPLETED                                  │
│                           (當 needs_procedure = 0 AND needs_anesthesia = 0) │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Hub-Satellite 同步考量

| 資料 | 權威來源 | 同步方向 |
|------|----------|----------|
| registrations.needs_procedure | CIRS Hub | Hub → MIRS Satellite |
| registrations.needs_anesthesia | CIRS Hub | Hub → MIRS Satellite |
| registration_claims | CIRS Hub | Hub → MIRS Satellite |
| procedure_cases | MIRS Satellite | Satellite → Hub (完成通知) |
| anesthesia_cases | MIRS Satellite | Satellite → Hub (完成通知) |

### 5.3 Hub-Satellite 合約升版 (v1.1 關鍵補強)

**必須更新 `RegistrationStub` 定義：**

```python
# xIRS-Contracts v1.1.0 (2026-01-01)
class RegistrationStub(BaseModel):
    """Hub → Satellite: 掛號資料快照"""
    registration_id: str               # REG-YYYYMMDD-XXX
    patient_id: Optional[str] = None
    triage_category: Optional[str] = None  # RED/YELLOW/GREEN/BLACK
    chief_complaint: Optional[str] = None
    location: Optional[str] = None     # Station ID
    status: str = "WAITING"
    hub_revision: int = 0

    # v1.1 新增欄位 - 分流標記
    needs_procedure: bool = False
    needs_anesthesia: bool = False
    consultation_completed_at: Optional[str] = None
    consultation_by: Optional[str] = None
```

**版本相容：**
| Hub Version | Satellite Version | 相容性 |
|-------------|-------------------|--------|
| v1.0 | v1.0 | ✅ Full (無 needs_* 欄位) |
| v1.1 | v1.0 | ⚠️ Partial (Satellite 收不到分流指令) |
| v1.1 | v1.1 | ✅ Full (完整分流支援) |

**衝突規則：** Hub wins (Satellite 只能透過 ops 提案變更)

---

## 6. 遷移計畫

### 6.1 Phase 1：資料庫變更

```sql
-- CIRS database
ALTER TABLE registrations ADD COLUMN needs_procedure INTEGER DEFAULT 0;
ALTER TABLE registrations ADD COLUMN needs_anesthesia INTEGER DEFAULT 0;
ALTER TABLE registrations ADD COLUMN consultation_completed_at TIMESTAMP;
ALTER TABLE registrations ADD COLUMN consultation_by TEXT;
ALTER TABLE registrations ADD COLUMN procedure_notes TEXT;
ALTER TABLE registrations ADD COLUMN anesthesia_notes TEXT;
```

### 6.2 Phase 2：API 實作

1. `POST /api/registrations/{id}/complete-consultation`
2. `GET /api/registrations/waiting/procedure`
3. `GET /api/registrations/waiting/anesthesia`
4. `POST /api/registrations/{id}/procedure-done`
5. 修改 Anesthesia case close 邏輯

### 6.3 Phase 3：UI 更新

1. Doctor PWA：新增「完成看診」對話框
2. Anesthesia PWA：修改「新增案例」為「待麻醉清單」優先
3. Station/Procedure PWA：新增「待處置」清單

### 6.4 Phase 4：Hub-Satellite 同步

1. 同步 `needs_procedure` / `needs_anesthesia` 欄位
2. 處置/麻醉完成通知 Hub

---

## 7. Server-side 防繞過 (v1.1 關鍵補強)

### 7.1 必須在後端強制驗證

**原則：** UI 只是 hint，真正的權限控制在 server-side。

### 7.2 Invariant 檢查清單

| API | 必須滿足條件 | 否則回應 |
|-----|-------------|---------|
| `GET /waiting/anesthesia` | 只回 `status=CONSULTATION_DONE AND needs_anesthesia=1` | (永不違反，純查詢) |
| `POST /complete-consultation` | `status=IN_CONSULTATION` AND 持有 DOCTOR claim | 403 Forbidden |
| `POST /claim` (PROCEDURE) | `status=CONSULTATION_DONE AND needs_procedure=1` | 400 Bad Request |
| `POST /claim` (ANESTHESIA) | `status=CONSULTATION_DONE AND needs_anesthesia=1` | 400 Bad Request |
| `POST /procedure-done` | 持有 PROCEDURE claim | 403 Forbidden |
| `POST /anesthesia/cases` | 持有 ANESTHESIA claim | 403 Forbidden |

### 7.3 實作範例

```python
@router.post("/registrations/{reg_id}/complete-consultation")
async def complete_consultation(reg_id: str, req: CompleteConsultationRequest, actor: Actor):
    # 1. 驗證 status
    reg = get_registration(reg_id)
    if reg.status != "IN_CONSULTATION":
        raise HTTPException(400, "只能在看診中完成看診")

    # 2. 驗證 claim
    claim = get_active_claim(reg_id, role="DOCTOR")
    if not claim or claim.claimed_by != actor.id:
        raise HTTPException(403, "您未持有此病患的看診權限")

    # 3. 執行更新
    update_registration(reg_id,
        status="CONSULTATION_DONE",
        needs_procedure=req.needs_procedure,
        needs_anesthesia=req.needs_anesthesia,
        consultation_completed_at=now(),
        consultation_by=actor.id
    )

    # 4. 自動釋放 DOCTOR claim
    release_claim(reg_id, role="DOCTOR")

    return {"success": True}
```

---

## 8. 驗收測試 (Must-Pass)

### 8.1 修復驗證

| 測試 | 預期結果 |
|------|---------|
| Doctor claim 後查詢 `/waiting/anesthesia` | 病患**不應**消失（因為麻醉隊列不取 WAITING） |
| Doctor claim 後 Anesthesia PWA 可選取 | ✅ 成功（只要 needs_anesthesia=1） |

### 8.2 分流正確性

| 測試 | 預期結果 |
|------|---------|
| 完成看診，兩個 box 都不勾 | 病患不出現在任何待處置/待麻醉清單 |
| 完成看診，只勾「需麻醉」 | 只出現在 `/waiting/anesthesia` |
| 完成看診，兩個都勾 | 同時出現在兩個清單 |

### 8.3 互斥測試

| 測試 | 預期結果 |
|------|---------|
| 兩個麻醉站同時 claim 同一病患 | 一個成功，另一個收到 409 Conflict |
| 麻醉站 claim 後，處置站 claim 同一病患 | 兩個都成功（角色不同） |

### 8.4 離線 72 小時

| 測試 | 預期結果 |
|------|---------|
| 離線期間完成 10 次分流 + 5 個麻醉案例 | 連線後全量對齊，無資料遺失 |
| 重複送出相同 ops | Hub 以 idempotency key 去重，狀態不變 |

---

## 9. 待討論問題

### 🎯 問題 1：多重需求處理順序

若 `needs_procedure = 1` 且 `needs_anesthesia = 1`：
- 是否需要指定順序？（例如：先麻醉再處置）
- 或者由操作人員自行判斷？

### 🎯 問題 2：緊急插隊機制

急診病患可能需要跳過看診，直接進入麻醉/處置：
- 是否需要「緊急通道」？
- 如何記錄跳過看診的原因？

### 🎯 問題 3：取消機制

若醫師標記「需處置」後，病患改變主意：
- 如何取消？
- 是否需要記錄取消原因？

### 🎯 問題 4：離線時的清單同步

MIRS Satellite 離線時：
- 是否快取最近的待處置/待麻醉清單？
- 如何處理清單過期的問題？

---

## 8. 附錄：現有相關規格

- `docs/DEV_SPEC_ANESTHESIA_v1.5.1.md` - 麻醉模組規格
- `CIRS/docs/xIRS_REGISTRATION_SPEC_v1.2.md` - 掛號規格
- `docs/xIRS_HUB_SATELLITE_INTEGRATION_v0.1.md` - Hub-Satellite 架構

---

---

## 10. 實作優先順序 (Action Plan)

根據 Gemini/ChatGPT 建議，降低 rework 風險：

| 順序 | 任務 | 說明 |
|------|------|------|
| 1 | CIRS DB 遷移 | `ALTER TABLE registrations` + 新增 `registration_claims` 表 |
| 2 | CIRS API | `/complete-consultation`, `/waiting/procedure`, `/waiting/anesthesia` |
| 3 | 角色化 Claim 機制 | `/claim` 支援 role 參數，避免日後 rework |
| 4 | Doctor PWA | 新增「完成看診」對話框 + 分流勾選 |
| 5 | Anesthesia PWA | 改為讀取 `/waiting/anesthesia`，保留手動 fallback |
| 6 | Procedure PWA | 改為讀取 `/waiting/procedure` |
| 7 | Hub-Satellite 合約升版 | 更新 `RegistrationStub`，確保 MIRS 能同步分流指令 |

---

---

## 11. 實作狀態 (Implementation Status)

### 11.1 已完成 (2026-01-01)

| 項目 | 狀態 | 說明 |
|------|------|------|
| CIRS DB 遷移 | ✅ 完成 | `registrations` 表新增 `needs_procedure`, `needs_anesthesia`, `consultation_completed_at`, `consultation_by`, `procedure_notes`, `anesthesia_notes` 欄位 |
| CIRS `/complete-consultation` API | ✅ 完成 | 支援 `needs_procedure`, `needs_anesthesia` 標記 |
| CIRS `/waiting/anesthesia` API | ✅ 完成 | 回傳 `needs_anesthesia=1` 且尚未被 ANESTHESIA claim 的病患 |
| CIRS `/waiting/procedure` API | ✅ 完成 | 回傳 `needs_procedure=1` 的病患 |
| CIRS 角色化 Claim | ✅ 完成 | `registration_claims` 表支援 DOCTOR/PROCEDURE/ANESTHESIA 三種角色並存 |
| Doctor PWA 完成看診 | ✅ 完成 | 新增「完成看診」對話框，含「需處置」「需麻醉」勾選 |
| Anesthesia PWA 候診清單 | ✅ 完成 | 使用 `/waiting/anesthesia` 端點，只顯示需麻醉病患 |
| Anesthesia PWA 案例過濾 | ✅ 完成 | 結案後從「我的案例」清單移除 |
| MIRS → CIRS 通知 | ✅ 完成 | 建立/結案時通知 Hub 執行 role-claim / anesthesia-done |

### 11.2 待實作

| 項目 | 優先順序 | 說明 |
|------|----------|------|
| Procedure PWA 候診清單 | P1 | 使用 `/waiting/procedure` 端點 |
| Hub-Satellite 合約升版 | P2 | `RegistrationStub` 包含 `needs_*` 欄位 |
| 離線 72 小時測試 | P2 | 驗證離線期間分流操作的同步 |

### 11.3 關鍵 Commits

**CIRS:**
- `34a0ba2` - feat: Doctor PWA 完成看診對話框 (needs_procedure/needs_anesthesia)
- `xxxxxxx` - feat: v1.1 角色化 Claim 機制 (registration_claims 表)

**MIRS:**
- `279a148` - feat: 麻醉建案/結案時通知 CIRS Hub
- `86ff7c2` - fix: 結案後從我的案例清單移除 (v1.1)

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**
*Version: 1.1*
*Last Updated: 2026-01-01*
*Review: Gemini + ChatGPT*
