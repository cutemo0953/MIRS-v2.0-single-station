# Blood Bank PWA DEV SPEC v2.2

**版本**: 2.2
**日期**: 2026-01-12
**狀態**: P0/P1/P2 Completed, P3 In Progress
**基於**: Gemini + ChatGPT 第二輪審閱 + BioMed PWA 經驗教訓 + Claude 實作反饋

---

## v2.1 → v2.2 變更摘要

| 項目 | 狀態 | 說明 |
|------|------|------|
| Gateway Entry Point | ✅ 完成 | BLOOD_BANK 站台加入 CIRS Gateway |
| 輸血時機定義 | ✅ 新增 | 檢傷 vs 收治 流程定義 |
| CIRS 整合流程圖 | ✅ 新增 | 正常輸血 + 緊急發血流程 |
| MIRS Tab 按鈕顏色 | ✅ 修正 | 改用 blood-600 (#B85D42) |

---

## v2.0 → v2.1 變更摘要

| 項目 | 狀態 | 說明 |
|------|------|------|
| P0 契約與架構 | ✅ 完成 | Tables, Views, routes/blood.py |
| P1 核心流程 | ✅ 完成 | Receive, List, Reserve, Issue, Return, Expiry blocking |
| P2 緊急與進階 | ✅ 完成 | Emergency Release, FIFO 警示, Batch Update, Events |
| P3 雙軌整合 | 🔄 進行中 | Blood PWA UI 基礎完成, 進階功能待補 |

---

## 執行摘要

Blood Bank PWA 將從 MIRS 主站剝離成獨立 PWA，採用與 BioMed PWA 相同的架構模式（MIRS 後台 + SQLite + PWA 連動）。血品管理具有最高臨床風險：**「發錯血會死人，沒血也會死人」**。

v2.1 更新：
- **P0/P1/P2 實作完成**：API 已全部上線
- **雙軌並行**：MIRS Tab + Blood PWA 共存
- **緊急發血**：戰時 Break-Glass 機制
- **原子預約**：409 CONFLICT 防止雙重預約
- **Event Sourcing**：完整稽核鏈
- **新增 SimpleBatchReceive**：簡化 MIRS Tab 入庫流程

---

## Claude 實作意見與建議

### 1. 架構決策回顧

#### 1.1 雙軌並行的價值驗證 ✅

實作後確認雙軌架構是正確決策：
- **MIRS Tab**：診所 / 單兵模式，一目了然看庫存總量
- **Blood PWA**：專業血庫技師，需要完整出入庫流程

**建議保留**：兩者 API 完全共用，只是 UI 粒度不同。

#### 1.2 SimpleBatchReceive 的必要性 ✅

原本 v2.0 規格假設入庫需要掃描每袋血品的 Barcode（donation_id），但戰時場景：
- 血袋可能來自臨時捐血站，沒有標準 Barcode
- 操作員可能需要一次入庫 10 袋 O+ PRBC

**實作調整**：
```python
class SimpleBatchReceive(BaseModel):
    """簡易批次入庫 (MIRS Tab 使用)"""
    blood_type: str           # A+, B-, O+...
    quantity: int = 1         # 一次入庫幾袋
    unit_type: str = "PRBC"   # 預設紅血球
    expiry_days: int = 35     # 自動計算效期
```

**自動產生**：
- Unit ID: `BU-{timestamp}-{uuid[:8]}`
- Expiry Date: `today + expiry_days`

### 2. 效期管理的三層防護

#### 2.1 設計回顧 ✅

三層防護架構經實測有效：

```
Layer 1: View 過濾
└─ v_blood_availability 只算 expiry_date > today

Layer 2: UI 顯示
└─ display_status = 'EXPIRED' → 紅色標籤 + 不可點擊

Layer 3: API Guard
└─ Reserve/Issue API 再次檢查 expiry_date
```

**實測結果**：
- Demo 模式動態生成效期（today + random days）
- 過期血品正確顯示在 "expired_pending_count"
- UI 正確顯示 FIFO 警告 Banner

#### 2.2 建議優化

**短期**（P3 可做）：
- 過期血品 → 自動排程任務提醒報廢
- FIFO 警示 → 目前只有 Banner，可加強到掃碼時彈窗

**長期**（P4 可考慮）：
- 與 BioMed PWA 血庫冰箱溫度連動
- 冰箱斷電 → 自動觸發 Batch Quarantine

### 3. Emergency Release 機制評估

#### 3.1 設計合理性 ✅

緊急發血 API 設計符合戰時需求：
- 只允許 O 型血（萬能供血）
- 必須填寫理由
- 自動標記 `is_emergency_release = 1`, `is_uncrossmatched = 1`
- 產生 CRITICAL 級別稽核事件

#### 3.2 實測結果

```bash
# 測試緊急發血
curl -X POST /api/blood/emergency-release \
  -d '{"blood_type": "O+", "quantity": 1, "reason": "大量傷患湧入"}'

# 回應
{
  "success": true,
  "issued_units": ["BU-1736668800-abc12345"],
  "warning": "緊急發血已記錄，請於 24h 內補齊醫囑"
}
```

#### 3.3 建議補強

1. **待補單追蹤**（P3）：
   - 目前只有 warning 文字，建議加 `pending_orders` 表追蹤
   - 超過 24h 未補單 → 顯示在 Admin Dashboard

2. **O- 優先邏輯**（可選）：
   - 緊急發血時，O- 比 O+ 更安全（Rh 陰性萬能）
   - 但 O- 稀少，需權衡庫存

### 4. Event Sourcing 稽核鏈

#### 4.1 設計驗證 ✅

`blood_unit_events` 表正確記錄所有操作：

| event_type | 觸發時機 |
|------------|----------|
| RECEIVE | 入庫 |
| RESERVE | 預約 |
| UNRESERVE | 取消預約 |
| ISSUE | 出庫 |
| RETURN | 退庫 |
| EMERGENCY_RELEASE | 緊急發血 |
| BATCH_QUARANTINE | 批次隔離 |
| BATCH_WASTE | 批次報廢 |

#### 4.2 建議優化

1. **Hash Chain**（P4）：
   - 目前 `prev_hash`, `event_hash` 欄位存在但未實作
   - 建議參考 xIRS v3.4 的 Signed Audit Chain 設計

2. **Event 查詢 API**：
   - 已實作 `GET /api/blood/events`
   - 建議加入 `GET /api/blood/units/{id}/timeline` 方便追蹤單一血袋歷史

### 5. 與 CIRS 整合注意事項

#### 5.1 Gateway Entry Point (v2.1 新增)

Blood PWA 現在可透過 xIRS Gateway 配對進入：

```
CIRS Gateway → 配對 BLOOD_BANK 站台 → 導向 MIRS:8000/blood/
```

**Admin UI 設定**：
- Station Type: `BLOOD_BANK`
- 圖示: droplet (血滴)
- 顏色: blood-600 (#B85D42)
- 路由: `/blood/` (MIRS port 8000)

**實作檔案**：
- `CIRS/backend/routes/auth.py`: STATION_TYPES 新增 BLOOD_BANK
- `CIRS/lobby/index.html`: 路由對應
- `CIRS/frontend/admin/index.html`: UI 設定

#### 5.2 輸血時機定義 (Claude 建議)

**核心問題**：檢傷處即可輸血，還是要收住院/處置/ICU？

**建議設計**：

```
┌─────────────────────────────────────────────────────────────────┐
│                   輸血觸發時機 (Clinical Context)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 正常流程 (Normal Transfusion)                            │   │
│  │                                                          │   │
│  │ 前提條件：                                               │   │
│  │ - 病患已收治 (admission_status != 'TRIAGE_ONLY')        │   │
│  │ - 已有床位/處置位置 (bed_id IS NOT NULL)                 │   │
│  │ - 醫師已開立輸血醫囑 (transfusion_order EXISTS)          │   │
│  │                                                          │   │
│  │ 適用情境：                                               │   │
│  │ - 住院病患                                               │   │
│  │ - ICU 病患                                               │   │
│  │ - 手術中病患                                             │   │
│  │ - 門診處置 (ambulatory transfusion)                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 緊急發血 (Emergency Release) - 已實作                     │   │
│  │                                                          │   │
│  │ 前提條件：                                               │   │
│  │ - 無需 admission_status                                  │   │
│  │ - 無需 bed_id                                            │   │
│  │ - 無需 transfusion_order                                 │   │
│  │ - 只能發 O 型血                                          │   │
│  │                                                          │   │
│  │ 適用情境：                                               │   │
│  │ - 檢傷處休克病患                                         │   │
│  │ - 戰時大量傷患                                           │   │
│  │ - 來不及開單/配血                                        │   │
│  │                                                          │   │
│  │ 限制：                                                   │   │
│  │ - 觸發 Break-Glass 稽核                                  │   │
│  │ - 24h 內必須補齊醫囑                                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  結論：                                                        │
│  ✅ 檢傷處「可以」輸血，但只能用緊急發血流程                    │
│  ✅ 正常輸血需要收治後（有 admission / procedure context）       │
│  ✅ MIRS 獨立運作時，不強制 CIRS admission 狀態                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**為什麼這樣設計**：

1. **戰時現實**：檢傷處可能大量傷患，來不及完成收治流程
2. **安全平衡**：正常流程要求收治，緊急流程有稽核追蹤
3. **系統獨立**：MIRS 可離線運作，不硬性依賴 CIRS 狀態
4. **事後合規**：緊急發血後強制補單，維持稽核完整性

#### 5.3 目前狀態

- MIRS 是獨立系統，Blood Bank API 在 MIRS 後端
- 與 CIRS 的整合依賴 `notify_cirs()` callback（目前為 TODO）
- **Gateway 配對**：✅ 已實作 (v2.1)

#### 5.4 Idempotency Key

- `issue_blood()` 回傳 `idempotency_key`
- CIRS 可用來去重

#### 5.5 Order ID 對應

- `reserved_for_order` 可存 CIRS 的 `transfusion_order_id`
- 但目前 Demo 模式不連 CIRS，Order ID 為 mock

#### 5.6 未來整合流程 (當 CIRS 加入輸血模組時)

```
┌─────────────────────────────────────────────────────────────────┐
│                   CIRS ↔ MIRS 整合流程                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [正常輸血流程]                                                  │
│                                                                 │
│  CIRS (醫師)                    MIRS (血庫)                      │
│       │                              │                          │
│       │ 1. 開立輸血醫囑               │                          │
│       │    (transfusion_order)       │                          │
│       │                              │                          │
│       │ 2. POST /api/blood/reserve   │                          │
│       │─────────────────────────────▶│                          │
│       │                              │ 3. 原子預約血袋            │
│       │                              │    (409 if conflict)     │
│       │◀─────────────────────────────│                          │
│       │    {unit_id, reserved}       │                          │
│       │                              │                          │
│       │ 4. 配血完成通知               │                          │
│       │                              │                          │
│       │ 5. POST /api/blood/issue     │                          │
│       │─────────────────────────────▶│                          │
│       │                              │ 6. 發血 + Event           │
│       │◀─────────────────────────────│                          │
│       │    {idempotency_key}         │                          │
│       │                              │                          │
│       │ 7. 更新醫囑狀態               │                          │
│       │    (BLOOD_ISSUED)            │                          │
│       │                              │                          │
│                                                                 │
│  [緊急發血流程]                                                  │
│                                                                 │
│  MIRS (血庫)                    CIRS (事後)                      │
│       │                              │                          │
│       │ 1. Emergency Release         │                          │
│       │    (Break-Glass)             │                          │
│       │                              │                          │
│       │ 2. notify_cirs() callback ──▶│                          │
│       │                              │ 3. 建立待補單任務          │
│       │                              │                          │
│       │◀──────────────────────────── │                          │
│       │ 4. 醫師 24h 內補醫囑          │                          │
│       │                              │                          │
│       │ 5. 關聯 order_id             │                          │
│       │                              │                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 一、v1.0 → v2.0 差異

### 1.1 ChatGPT 第二輪意見

| 議題 | v1.0 狀態 | v2.0 修正 | v2.1 實作狀態 |
|------|----------|----------|---------------|
| **Reservation 原子性** | 未定義 | ✅ 新增 409 CONFLICT + guard update | ✅ 已實作 |
| **訂單履約欄位** | 缺失 | ✅ 新增 `reserved_quantity`, `issued_quantity` | ✅ 已實作 |
| **狀態機硬規則** | 只列狀態 | ✅ 定義允許轉移 + API 強制 | ✅ 已實作 |
| **Event Sourcing** | 只有 crossmatch_log | ✅ 新增 `blood_unit_events` 表 | ✅ 已實作 |
| **Idempotency** | 未定義 | ✅ CIRS 回呼帶 idempotency_key | ✅ 已預留 |
| **驗收標準** | 基礎 | ✅ 擴展並發/衝突測試 | ⚠️ 部分測試 |

### 1.2 Gemini 第二輪意見

| 議題 | v1.0 狀態 | v2.0 修正 | v2.1 實作狀態 |
|------|----------|----------|---------------|
| **緊急發血** | 缺失 | ✅ 新增 Emergency Release + Break-Glass | ✅ 已實作 |
| **歸還/取消** | 缺失 | ✅ 新增 Unreserve / Return API | ✅ 已實作 |
| **Barcode 強制掃描** | 未定義 | ✅ 出庫必須掃碼 + FIFO 警示 | ⚠️ PWA 端待完善 |
| **批次報廢** | 未定義 | ✅ 新增 Batch Update 功能 | ✅ 已實作 |
| **View 過濾過期** | Bug | ✅ 修正 physical_count 定義 | ✅ 已修正 |
| **雙軌並行** | 未定義 | ✅ MIRS Tab + PWA 共存 | ✅ 已實作 |

### 1.3 Claude 實作意見 (v2.1 新增)

| 議題 | 建議 | 優先級 |
|------|------|--------|
| **SimpleBatchReceive** | 新增簡易批次入庫 API，無需 Barcode | ✅ P1 已實作 |
| **動態 Demo 資料** | 效期應基於 today 計算，非固定日期 | ✅ 已修正 |
| **unit_type 預設** | 99% 情況是 PRBC，應預設 | ✅ 已調整 |
| **待補單追蹤** | Emergency Release 後應有追蹤機制 | P3 建議 |
| **Hash Chain** | Event Sourcing 加入簽章 | P4 建議 |
| **BioMed 連動** | 冰箱斷電自動 Quarantine | P4 建議 |

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

| 功能 | **Blood PWA (專業模式)** | **MIRS Tab (單兵模式)** | v2.1 狀態 |
|------|--------------------------|------------------------|-----------|
| **適用場景** | 專職血庫技師、大型醫院 | 醫師兼藥師、前線救護站 | - |
| **庫存檢視** | 詳細 (效期、血型、預約單號) | 簡易 (血型總量 A/B/O/AB) | ✅ |
| **一般發血** | 掃描 Barcode + 核對醫囑 | 點擊「-1」按鈕 (簡易扣庫) | ✅ |
| **緊急領血** | **完整流程** (驗證+掃碼+警示) | **簡易按鈕** (快速扣庫) | ✅ |
| **效期阻擋** | **強制阻擋** (不可出庫) | **視覺警示** (亮紅燈但允許) | ✅ |
| **配血流程** | 完整交叉配血記錄 | 不支援 (直接發血) | P3 |
| **預約管理** | 支援 Reserve/Unreserve | 不支援 | ✅ |
| **離線支援** | Service Worker | 依賴 MIRS 主站 | ✅ |

---

## 三、緊急發血 (Emergency Release) ✅ 已實作

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

### 3.3 API (✅ 已實作)

```python
@router.post("/api/blood/emergency-release")
async def emergency_release(data: EmergencyReleaseRequest):
    """
    緊急發血 - 繞過正常流程
    v2.1: 已完整實作
    """
    # 1. 驗證血型 (只允許 O 型)
    # 2. 查詢可用血袋 (FIFO)
    # 3. 原子更新 + Guard Update
    # 4. Break-Glass 稽核事件
    # 5. 回傳 issued_units + warning
```

---

## 四、歸還/取消機制 ✅ 已實作

### 4.1 Unreserve (取消預約)

```python
@router.post("/api/blood/units/{unit_id}/unreserve")
# v2.1: 已實作
```

### 4.2 Return (退庫)

```python
@router.post("/api/blood/units/{unit_id}/return")
# v2.1: 已實作，含冷鏈檢查 (30 分鐘)
```

---

## 五、原子預約與狀態機 ✅ 已實作

### 5.1 狀態機定義

```
                     ┌──────────────┐
                     │   RECEIVED   │ ← 入庫
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
            ┌───────▶│  AVAILABLE   │◀────────┐
            │        └──────┬───────┘         │
            │               │                 │
    Unreserve/Timeout       │ Reserve       Return
            │               ▼                 │
            │        ┌──────────────┐         │
            └────────│   RESERVED   │─────────┘
                     └──────┬───────┘
                            │
                            │ Issue
                            ▼
                     ┌──────────────┐
                     │    ISSUED    │ ← 不可逆
                     └──────────────┘

  側邊狀態：
  ┌────────────┐  ┌────────────┐  ┌────────────┐
  │  EXPIRED   │  │   WASTE    │  │ QUARANTINE │
  │ (計算得出)  │  │  (報廢)    │  │   (隔離)   │
  └────────────┘  └────────────┘  └────────────┘
```

### 5.2 允許的轉移 (✅ API 已強制)

```python
ALLOWED_TRANSITIONS = {
    'RECEIVED': ['AVAILABLE', 'QUARANTINE', 'WASTE'],
    'AVAILABLE': ['RESERVED', 'ISSUED', 'WASTE', 'QUARANTINE'],
    'RESERVED': ['AVAILABLE', 'ISSUED', 'WASTE'],
    'ISSUED': [],  # 不可逆
    'QUARANTINE': ['AVAILABLE', 'WASTE'],
    'WASTE': [],  # 不可逆
    'EXPIRED': [],  # 計算狀態
}
```

---

## 六、資料庫設計 (v2.1 驗證完成)

### 6.1 血袋單位表 ✅

```sql
CREATE TABLE IF NOT EXISTS blood_units (
    id TEXT PRIMARY KEY,
    blood_type TEXT NOT NULL,
    unit_type TEXT NOT NULL DEFAULT 'PRBC',
    volume_ml INTEGER DEFAULT 250,
    donation_id TEXT,
    collection_date DATE,
    expiry_date DATE NOT NULL,
    status TEXT DEFAULT 'AVAILABLE',
    -- ... 完整欄位已實作
);
```

### 6.2 血袋事件表 ✅

```sql
CREATE TABLE IF NOT EXISTS blood_unit_events (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    metadata TEXT,
    severity TEXT DEFAULT 'INFO',
    ts_server INTEGER DEFAULT (strftime('%s', 'now')),
    -- ... Hash Chain 欄位已預留
);
```

### 6.3 View 定義 ✅

```sql
CREATE VIEW IF NOT EXISTS v_blood_availability AS
-- v2.1: 已驗證效期過濾正確
SELECT
    blood_type,
    unit_type,
    physical_valid_count,
    reserved_count,
    available_count,
    expiring_soon_count,
    expired_pending_count,
    nearest_expiry
FROM blood_units
-- ... 完整邏輯已實作
```

---

## 七、Barcode 掃描與 FIFO 警示 ⚠️ 部分實作

### 7.1 掃碼出庫流程

- [x] API 端 FIFO 優先級計算
- [x] PWA UI FIFO 警告 Banner
- [ ] 掃碼時彈窗警示（P3）
- [ ] 強制選擇 FIFO 建議（可選）

### 7.2 FIFO 警示 UI ✅

```html
<!-- 已實作：頂部警告 Banner -->
<div x-show="expiringSoonCount > 0" class="bg-yellow-100 border-l-4 border-yellow-500 p-4">
    <p class="text-yellow-700">
        有 <span x-text="expiringSoonCount"></span> 袋血品即將過期
    </p>
</div>
```

---

## 八、批次報廢 (Batch Update) ✅ 已實作

### 8.1 API

```python
@router.post("/api/blood/batch-update")
async def batch_update_blood(data: BatchUpdateRequest):
    # v2.1: 已實作
    # 支援批次 QUARANTINE / WASTE
```

---

## 九、CIRS 整合與 Idempotency ⚠️ 預留

### 9.1 發血回呼

```python
# idempotency_key 已在 issue 回應中預留
# notify_cirs() 為 TODO，等 CIRS 輸血模組上線
```

---

## 十、驗收標準 (v2.1 狀態)

### 10.1 並發/衝突測試

- [x] 兩台設備同時 reserve 同一血袋 → 只有一台成功，另一台 409
- [x] 血型/成分不符醫囑 → API 必須拒絕
- [x] 已被其他 order reserve 的血袋 → issue 必須拒絕
- [ ] reserve timeout → 自動釋放回 AVAILABLE（P3 排程任務）
- [ ] CIRS 重複發送 blood_issued → 只處理一次（待 CIRS 整合）

### 10.2 緊急發血測試 ✅

- [x] 無 Order 情況下可發 O 型血
- [x] 緊急發血觸發 Break-Glass 稽核
- [ ] 24h 後未補單 → 產生待補單任務（P3）
- [x] 緊急發血記錄可追溯

### 10.3 歸還/冷鏈測試 ✅

- [x] 離開冰箱 <30 分鐘 → 可退回 AVAILABLE
- [x] 離開冰箱 >30 分鐘 → 自動標記 WASTE
- [x] 歸還事件正確記錄

### 10.4 FIFO 與效期測試 ✅

- [x] View 的 available_count 不含過期品
- [x] UI 顯示即將過期警示 Banner
- [ ] 掃描非 FIFO 血袋 → 彈窗警示（P3）
- [x] 掃描過期血袋 → API 拒絕 + UI 阻擋

### 10.5 雙軌並行測試 ✅

- [x] PWA 發血 → MIRS Tab 刷新後庫存正確
- [x] MIRS Tab 簡易扣庫 → PWA 顯示正確
- [x] 兩者同時操作不衝突（單一 SQLite + View）

---

## 十一、實作階段 (v2.1 狀態)

### P0: 契約與架構 ✅ 完成

- [x] 建立欄位契約表
- [x] 建立 blood_units, transfusion_orders, blood_unit_events 表
- [x] 建立 v_blood_availability, v_blood_unit_status View
- [x] 新增 routes/blood.py 骨架
- [x] 狀態機轉移驗證

### P1: 核心流程 ✅ 完成

- [x] 血袋入庫 (Receive) + SimpleBatchReceive
- [x] 可用性/效期清單 (List)
- [x] 原子預約 (Reserve) + 409 CONFLICT
- [x] 出庫 (Issue)
- [x] 歸還 (Return) + 冷鏈檢查
- [x] 效期阻擋三層防護

### P2: 緊急與進階 ✅ 完成

- [x] 緊急發血 (Emergency Release)
- [x] FIFO 警示 Banner
- [x] 批次報廢 (Batch Update)
- [x] Event Sourcing 完整稽核

### P3: 雙軌整合 🔄 進行中

- [x] Blood PWA 基礎 UI
- [x] MIRS Tab 簡易版 UI
- [x] Service Worker 隔離
- [ ] Barcode 掃碼整合
- [ ] 配血流程 UI
- [ ] 稽核報表 UI

### P4: 進階整合（未來）

- [ ] CIRS 輸血醫囑整合
- [ ] BioMed 冰箱溫度連動
- [ ] Reserve Timeout 排程
- [ ] 待補單追蹤機制
- [ ] Hash Chain 簽章

---

## 附錄 A: API 一覽 (v2.1 實作狀態)

| Endpoint | Method | 描述 | v2.1 狀態 |
|----------|--------|------|-----------|
| `/api/blood/units` | GET | 列表查詢 | ✅ |
| `/api/blood/units` | POST | 入庫 (單筆) | ✅ |
| `/api/blood/units/batch` | POST | 入庫 (批次) | ✅ v2.1 新增 |
| `/api/blood/units/{id}` | GET | 單筆查詢 | ✅ |
| `/api/blood/units/{id}/reserve` | POST | 預約 | ✅ |
| `/api/blood/units/{id}/unreserve` | POST | 取消預約 | ✅ |
| `/api/blood/units/{id}/issue` | POST | 出庫 | ✅ |
| `/api/blood/units/{id}/return` | POST | 退庫 | ✅ |
| `/api/blood/units/{id}/waste` | POST | 報廢 | ✅ |
| `/api/blood/emergency-release` | POST | 緊急發血 | ✅ |
| `/api/blood/batch-update` | POST | 批次更新 | ✅ |
| `/api/blood/availability` | GET | 可用性總覽 | ✅ |
| `/api/blood/events` | GET | 事件查詢 | ✅ |

---

## 附錄 B: 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-12 | 初版：基礎架構、效期阻擋 |
| v2.0 | 2026-01-12 | 緊急發血、原子預約、歸還機制、雙軌並行、Event Sourcing |
| v2.1 | 2026-01-12 | P0/P1/P2 完成標記、Claude 實作意見、SimpleBatchReceive |
| v2.2 | 2026-01-12 | Gateway Entry Point、輸血時機定義、CIRS 整合流程圖 |

---

**文件完成**
**撰寫者**: Claude Code
**審閱者**: Gemini + ChatGPT (第二輪) + Claude (實作回饋)
**日期**: 2026-01-12
