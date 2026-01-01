# MIRS 處置功能 CIRS 整合規格書

**Version:** 1.0
**Date:** 2026-01-01
**Status:** 待核准

---

## 0. 摘要

將 MIRS 主站的「處置記錄」功能與 CIRS Hub 的 v1.1 就診流程整合，使醫師在 Doctor PWA 勾選「需處置」後，病患會出現在 MIRS 的「待處置清單」。

### 0.1 設計決策

| 議題 | 決策 | 理由 |
|------|------|------|
| Doctor PWA 是否顯示待處置清單？ | **否** | 醫師角色是「標記」，不是「執行」 |
| MIRS 處置功能是否移除？ | **否，增強** | 保留手動輸入作為緊急/離線備援 |
| 是否建立獨立 Procedure PWA？ | **否** | 直接增強 MIRS 主站即可 |

---

## 1. 問題描述

### 1.1 現狀

```
Doctor PWA                        MIRS 主站
┌─────────────────┐              ┌─────────────────┐
│ 完成看診        │              │ 處置記錄        │
│ ☑ 需處置       │──── ✗ ───────│ (純手動輸入)   │
│ ☑ 需麻醉       │──── ✓ ───────│ Anesthesia PWA │
└─────────────────┘              └─────────────────┘
```

**問題：**
1. 醫師勾選「需處置」後，CIRS 有記錄 (`needs_procedure=1`)
2. 但 MIRS 處置功能沒有讀取 CIRS 待處置清單
3. 處置人員無法知道哪些病患需要處置

### 1.2 期望流程

```
Doctor PWA                        MIRS 主站
┌─────────────────┐              ┌─────────────────────────┐
│ 完成看診        │              │ 處置管理                │
│ ☑ 需處置       │──── ✓ ───────│ ┌─────────────────────┐ │
│ ☑ 需麻醉       │              │ │ 待處置清單 (CIRS)   │ │
└─────────────────┘              │ │ ○ 王小明 - 右腿清創 │ │
                                 │ │ ○ 李大華 - 腹部縫合 │ │
                                 │ └─────────────────────┘ │
                                 │ [手動新增] (緊急/離線) │
                                 └─────────────────────────┘
```

---

## 2. 架構設計

### 2.1 整體架構

```
┌─────────────────────────────────────────────────────────────┐
│                     CIRS Hub (Port 8090)                    │
├─────────────────────────────────────────────────────────────┤
│  /api/registrations/waiting/procedure                       │
│  → 回傳 needs_procedure=1 且 status=CONSULTATION_DONE       │
│                                                             │
│  /api/registrations/{id}/role-claim                         │
│  → 接收 role=PROCEDURE 的 claim                             │
│                                                             │
│  /api/registrations/{id}/procedure-done                     │
│  → 標記處置完成，清除 needs_procedure                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 MIRS Satellite (Port 8000)                  │
├─────────────────────────────────────────────────────────────┤
│  /api/procedure/proxy/cirs/waiting-procedure                │
│  → 代理 CIRS /waiting/procedure，判斷連線狀態               │
│                                                             │
│  /api/surgery/record (現有)                                 │
│  → 建立處置記錄時，自動通知 CIRS (如有 cirs_registration_ref)│
└─────────────────────────────────────────────────────────────┘
```

### 2.2 資料流

```
1. 醫師完成看診，勾選「需處置」
   Doctor PWA → POST /complete-consultation { needs_procedure: true }

2. CIRS 記錄 needs_procedure=1

3. MIRS 處置頁面每 30 秒輪詢待處置清單
   MIRS → GET /proxy/cirs/waiting-procedure

4. 處置人員從清單選取病患
   → 自動帶入病患資料到處置表單

5. 處置人員完成處置記錄
   → POST /surgery/record { cirs_registration_ref: "REG-xxx" }
   → 後端自動 POST CIRS /role-claim { role: "PROCEDURE" }
   → 後端自動 POST CIRS /procedure-done
```

---

## 3. API 變更

### 3.1 新增 MIRS 端點

#### GET /api/procedure/proxy/cirs/waiting-procedure

代理 CIRS Hub 的待處置清單。

**Response (連線成功):**
```json
{
  "online": true,
  "count": 2,
  "patients": [
    {
      "registration_id": "REG-20260101-001",
      "patient_id": "P0042",
      "name": "王小明",
      "chief_complaint": "右腿骨折",
      "procedure_notes": "需清創術",
      "consultation_by": "DR-001",
      "waiting_minutes": 15,
      "priority": "URGENT",
      "triage_category": "YELLOW"
    }
  ]
}
```

**Response (離線):**
```json
{
  "online": false,
  "count": 0,
  "patients": [],
  "message": "CIRS Hub 未連線"
}
```

### 3.2 修改現有端點

#### POST /api/surgery/record

**新增參數：**
```json
{
  "patientName": "王小明",
  "surgeryType": "清創術",
  "surgeonName": "DR-001",
  "consumptions": [...],

  // v1.1 新增
  "cirs_registration_ref": "REG-20260101-001"  // 可選，從待處置清單選取時帶入
}
```

**後端邏輯變更：**
```python
@router.post("/surgery/record")
async def create_surgery_record(request: SurgeryRecordRequest):
    # 1. 建立處置記錄（現有邏輯）
    record_id = create_record(...)

    # 2. v1.1: 如果有 CIRS 參照，通知 Hub
    if request.cirs_registration_ref:
        actor_id = get_actor_id()  # 從 session 或 request 取得

        # 2a. Claim PROCEDURE 角色
        await notify_cirs_claim(
            request.cirs_registration_ref,
            role="PROCEDURE",
            actor_id=actor_id
        )

        # 2b. 標記處置完成
        await notify_cirs_procedure_done(
            request.cirs_registration_ref,
            procedure_record_id=record_id
        )

    return {"success": True, "record_id": record_id}
```

### 3.3 CIRS 端點（已存在，確認規格）

#### POST /api/registrations/{id}/procedure-done

**Request:**
```json
{
  "procedure_record_id": "PROC-20260101-001",  // MIRS 處置記錄 ID
  "actor_id": "PROC-STATION-01"
}
```

**行為：**
1. 設定 `needs_procedure = 0`
2. 釋放 PROCEDURE claim
3. 如果 `needs_procedure=0 AND needs_anesthesia=0`，設定 `status = COMPLETED`

---

## 4. UI 變更

### 4.1 MIRS 處置頁面改版

```
┌─────────────────────────────────────────────────────────────────────┐
│  處置管理                                                [處置記錄 ▾]│
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  CIRS 待處置清單                               [●] 連線 (2位) │ │
│  ├───────────────────────────────────────────────────────────────┤ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │  🟡 ***0042 王小明                          等待 15 分鐘 │ │ │
│  │  │  右腿骨折 · 需清創術                                     │ │ │
│  │  │  醫師：DR-001                                   [選取]  │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │  🟢 ***0088 李大華                           等待 5 分鐘 │ │ │
│  │  │  腹部撕裂傷 · 需縫合                                     │ │ │
│  │  │  醫師：DR-002                                   [選取]  │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  │                                                               │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ─────────────────────── 或 ───────────────────────                │
│                                                                     │
│  [手動新增處置記錄]  ← 緊急/離線時使用                              │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  今日處置記錄                                                       │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 日期       │ 病患     │ 處置類型   │ 醫師     │ 狀態          │ │
│  ├───────────────────────────────────────────────────────────────┤ │
│  │ 10:30     │ 陳小花   │ 骨折固定   │ DR-001  │ [詳情]        │ │
│  │ 09:15     │ 張大明   │ 清創縫合   │ DR-002  │ [詳情]        │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 選取病患後自動帶入

當使用者從待處置清單選取病患：

1. 自動填入：
   - 病患姓名
   - Triage Tag ID (如有)
   - 處置類型（從 procedure_notes）
   - cirs_registration_ref（隱藏欄位）

2. 使用者需填入：
   - 執刀醫師
   - 消耗品項
   - 備註

3. 送出時：
   - 建立 MIRS 處置記錄
   - 自動通知 CIRS 處置完成

---

## 5. 資料庫變更

### 5.1 MIRS surgery_records 表

**新增欄位：**
```sql
ALTER TABLE surgery_records ADD COLUMN cirs_registration_ref TEXT;
ALTER TABLE surgery_records ADD COLUMN cirs_notified INTEGER DEFAULT 0;
```

| 欄位 | 類型 | 說明 |
|------|------|------|
| cirs_registration_ref | TEXT | CIRS 掛號編號 (REG-xxx) |
| cirs_notified | INTEGER | 是否已通知 CIRS (0/1) |

---

## 6. 錯誤處理

### 6.1 CIRS 離線

| 情境 | 處理 |
|------|------|
| 載入待處置清單失敗 | 顯示「CIRS 未連線」，提供手動新增按鈕 |
| 通知 CIRS 失敗 | 記錄 cirs_notified=0，稍後重試 |
| 離線期間建立的記錄 | 恢復連線後批次同步 |

### 6.2 重試機制

```python
# 背景任務：重試未通知的記錄
async def retry_pending_notifications():
    records = get_unnotified_records()
    for record in records:
        try:
            await notify_cirs_procedure_done(record.cirs_registration_ref)
            mark_as_notified(record.id)
        except Exception:
            continue  # 下次再試
```

---

## 7. 實作計畫

### 7.1 Phase 1：後端 API (2 小時)

| 順序 | 任務 | 檔案 |
|------|------|------|
| 1 | 新增 MIRS proxy 端點 | `routes/procedure.py` |
| 2 | 修改 surgery_record 加入 CIRS 通知 | `routes/surgery.py` |
| 3 | 資料庫 migration | `main.py` |

### 7.2 Phase 2：前端 UI (3 小時)

| 順序 | 任務 | 檔案 |
|------|------|------|
| 1 | 新增待處置清單區塊 | `Index.html` |
| 2 | 選取病患自動帶入邏輯 | `Index.html` |
| 3 | 連線狀態指示器 | `Index.html` |

### 7.3 Phase 3：測試 (1 小時)

| 測試 | 預期結果 |
|------|---------|
| Doctor 標記需處置 | 出現在 MIRS 待處置清單 |
| 從清單選取並完成處置 | CIRS needs_procedure 變為 0 |
| CIRS 離線時手動新增 | 可正常建立記錄 |
| 恢復連線後同步 | 離線記錄通知 CIRS |

---

## 8. 決策記錄

### 8.1 為何不讓 Doctor PWA 顯示待處置清單？

**結論：** Doctor PWA 不顯示待處置清單

**理由：**
1. **角色分工**：醫師負責診斷與開醫囑，不負責執行處置
2. **流程設計**：醫師標記「需要什麼」，處置站「執行」
3. **一致性**：與麻醉流程一致（醫師標記需麻醉，Anesthesia PWA 執行）

### 8.2 為何不移除 MIRS 處置功能？

**結論：** 保留並增強

**理由：**
1. **緊急備援**：戰場環境可能無法連線 CIRS
2. **離線運作**：MIRS 設計為可獨立運作的 Satellite
3. **手動輸入**：緊急病患可能未經正式掛號

### 8.3 為何不建立獨立 Procedure PWA？

**結論：** 直接增強 MIRS 主站

**理由：**
1. **功能已存在**：MIRS 已有完整的處置記錄功能
2. **庫存整合**：處置需要消耗品追蹤，MIRS 已有此功能
3. **減少複雜度**：不需要額外的 PWA 維護

---

## 9. 附錄：現有相關規格

- [DEV_SPEC_ENCOUNTER_WORKFLOW_v1.1.md](DEV_SPEC_ENCOUNTER_WORKFLOW_v1.1.md) - 就診流程規格
- [DEV_SPEC_ANESTHESIA_v1.5.1.md](DEV_SPEC_ANESTHESIA_v1.5.1.md) - 麻醉模組規格

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**
*Version: 1.0*
*Last Updated: 2026-01-01*
