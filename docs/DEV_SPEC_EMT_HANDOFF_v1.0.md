# EMT Transfer Handoff 開發規格書 (MIRS 端)

**版本**: 3.2
**日期**: 2026-01-05
**狀態**: Draft
**依賴**:
- DEV_SPEC_EMT_TRANSFER_PWA.md v2.2.4
- **CIRS: xIRS_UNIFIED_HANDOFF_SPEC_v1.4.md** ← 統一交班架構

---

## 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| 3.0 | 2026-01-05 | 重構為 CIRS 統一交班消費端 |
| 3.1 | 2026-01-05 | 新增手動建立交班單 (外站轉入)、GCS E/V/M 格式、ISBAR/MIST 選擇 |
| 3.2 | 2026-01-05 | 內部轉送也可填 ISBAR/MIST、站點名稱顯示、source_station/local_station |

---

## 0. 摘要

本規格書描述 **MIRS EMT PWA 如何消費 CIRS 統一交班系統**。

> **重要架構變更 (v3.0)**:
> - 交班資料統一由 CIRS `handoff_records` 管理
> - EMT PWA 從 CIRS 讀取交班（90% 只讀 + 10% 補充）
> - 不再於 EMT 端重複建立交班表單

### 使用情境

```
┌──────────────────┐                        ┌──────────────────┐
│  CIRS Doctor     │                        │  MIRS EMT PWA    │
│  (醫師站)         │                        │  (轉送模組)       │
│                  │                        │                  │
│  勾選「需轉送」   │                        │                  │
│       ↓          │                        │                  │
│  自動建立        │      handoff           │                  │
│  handoff_record  │ ───────────────────▶  │  讀取待接收      │
│  (PENDING)       │                        │       ↓          │
│                  │                        │  點擊「接收」     │
│                  │   ◀──────────────────  │       ↓          │
│  status=ACCEPTED │      POST /accept      │  自動填入任務     │
│                  │                        │  (90% 只讀)       │
└──────────────────┘                        └──────────────────┘
```

### 設計原則

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  交班 = 資料累積的快照 (由 CIRS 產生)                                         │
│                                                                              │
│  EMT PWA 職責：                                                              │
│  1. 讀取 CIRS 交班 (handoff_records)                                         │
│  2. 接收確認 (POST /accept)                                                  │
│  3. 執行物流任務 (物資整備、轉送、結案)                                        │
│  4. 補充途中事件 (append-only addenda)                                        │
│                                                                              │
│  原則：90% 自動帶入 (Read-only) + 10% 途中補充 (Write)                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 核心需求

| 需求 | 說明 | 狀態 |
|------|------|------|
| **O2 流量預設值** | 無/3/6/10/15 L/min 快選按鈕 | ✓ 已實作 (v1.1.0) |
| **讀取 CIRS 交班** | 從 handoff_records 自動帶入 | 本版新增 |
| **物資整備** | RESERVE/ISSUE/RETURN 正規化 | 本版強化 |
| **PSI 追蹤** | 氧氣瓶 PSI 記錄（同麻醉模組） | 本版新增 |

---

## 1. Step 流程重設計 (v3.0)

### 1.1 新版 Step 架構

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step 0           │  Step 1        │  Step 2      │  Step 3      │         │
│  接收交班         │  物資整備      │  轉送中      │  結案        │         │
│  (PLANNING)       │  (READY)       │  (EN_ROUTE)  │  (COMPLETED) │         │
│                   │                │              │              │         │
│  讀取 CIRS 交班   │  氧氣鋼瓶      │  即時追蹤    │  消耗統計    │         │
│  確認病患資訊     │  設備電量      │  途中事件    │  歸還物資    │         │
│  (90% 只讀)       │  藥物/耗材     │              │              │         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Step 變更對照

| 版本 | Step 0 | Step 1 | Step 2 | Step 3 |
|------|--------|--------|--------|--------|
| v1.x | 手動任務設定 | 物資確認 | 轉送中 | 結案 |
| v2.0 | 任務設定 | 交班輸入 (手動) | 物資整備 | 結案 |
| **v3.0** | **接收 CIRS 交班 (只讀)** | **物資整備** | **轉送中** | **結案** |

### 1.3 關鍵變更

1. **移除手動交班輸入**: Step 0 不再需要 EMT 手動填寫 ISBAR/MIST
2. **自動帶入**: 從 CIRS `handoff_records.snapshot` 讀取完整資料
3. **EMT 只需補充**: 途中事件、實際消耗、備註

---

## 2. Step 0: 接收 CIRS 交班 (只讀)

### 2.1 待接收交班列表

EMT PWA 啟動後，從 CIRS 取得 `target_role=EMT` 的待處理交班：

```
┌─────────────────────────────────────────────────────────────┐
│ 待接收交班                                    [重新整理]     │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 🔴 URGENT                          10:32 建立           │ │
│ │ 王大明 45M  右股骨開放性骨折 ORIF                       │ │
│ │ 目的地: 後送醫院 A                                      │ │
│ │ O2: 6 L/min    格式: MIST                              │ │
│ │                                        [接收此交班]    │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ○ NORMAL                           09:45 建立           │ │
│ │ 陳志明 62M  TKA 術後                                    │ │
│ │ 目的地: 後送醫院 B                                      │ │
│ │ O2: 無        格式: ISBAR                              │ │
│ │                                        [接收此交班]    │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 接收交班流程

```javascript
async acceptHandoff(handoffId) {
    // 1. 向 CIRS 發送接受請求
    const resp = await fetch(`${CIRS_HUB_URL}/api/handoff/${handoffId}/accept`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${this.token}` }
    });

    // 2. 獲取交班詳情 (含 snapshot)
    const handoff = await resp.json();

    // 3. 本地建立 transfer_mission
    this.currentMission = {
        mission_id: `TM-${Date.now()}`,
        cirs_handoff_id: handoff.handoff_id,
        patient_snapshot: handoff.snapshot,  // 鎖定版本
        vital_signs_snapshot: handoff.vital_signs_snapshot,
        content: handoff.content,  // ISBAR/MIST 內容
        format: handoff.format,
        status: 'PLANNING'
    };

    // 4. 進入 Step 1 (物資整備)
    this.goToStep(1);
}

async rejectHandoff(handoffId, reason, code) {
    // v1.1: 拒絕交班
    await fetch(`${CIRS_HUB_URL}/api/handoff/${handoffId}/reject`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.token}`
        },
        body: JSON.stringify({
            rejector_id: this.emtId,
            rejector_name: this.emtName,
            rejection_code: code,  // PATIENT_UNSTABLE | NO_CAPACITY | OTHER
            rejection_reason: reason
        })
    });
    // 重新載入待接收列表
    await this.loadPendingHandoffs();
}
```

### 2.4 抵達重測 Vital Signs (v1.1 新增)

EMT 抵達病患處時，應重測 Vital Signs 並記錄為 addendum：

```
┌─────────────────────────────────────────────────────────────┐
│ 抵達確認                                                     │
├─────────────────────────────────────────────────────────────┤
│ 病患: 王大明 45M                                            │
│ 交班 VS (10:30): BP 150/90, HR 88, SpO2 96%                │
│                                                             │
│ ⚠ 建議重測生命徵象 (保護 EMT 責任)                          │
│                                                             │
│ 【抵達時重測】                                               │
│ BP: [145/85]  HR: [92]  SpO2: [97]  GCS: [E4V5M6]          │
│                                                             │
│ 備註: [病患意識清醒，願意配合轉送________________]          │
│                                                             │
│ [ ] 跳過重測 (不建議)                                       │
└─────────────────────────────────────────────────────────────┘
│                                                             │
│  [拒絕此交班]                        [確認接收，進入物資]   │
└─────────────────────────────────────────────────────────────┘
```

```javascript
async recordArrivalVitals(vitals, note) {
    // 1. 記錄到 CIRS handoff_addenda
    await fetch(`${CIRS_HUB_URL}/api/handoff/${this.currentMission.cirs_handoff_id}/addendum`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.token}`
        },
        body: JSON.stringify({
            addendum_type: 'ARRIVAL_VITALS',
            source: 'EMT',
            recorded_by: this.emtId,
            content: {
                note: note,
                vital_signs: vitals
            }
        })
    });

    // 2. 本地也記錄一份 (離線用)
    await this.appendMissionEvent({
        event_type: 'ARRIVAL_VITALS',
        data: { vitals, note },
        timestamp: new Date().toISOString()
    });
}
```

> **法律保護**: 抵達重測的 VS 記錄在 `handoff_addenda`，證明 EMT 接手時的真實狀態。
> 與原 snapshot 對比可顯示時間差內的病情變化。

### 2.5 手動建立交班單 (v3.1 新增)

適用情境：
- 外站轉送過來的病患（不在 CIRS 系統中）
- 自行前來的創傷病患需立即轉送
- 現場急救後需要後送

#### 2.5.1 UI 設計

```
┌─────────────────────────────────────────────────────────────┐
│ 新增轉送任務                                   [CIRS | 手動] │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  【報告格式】                                                │
│  ┌────────────────┐  ┌────────────────┐                     │
│  │ 📋 ISBAR      │  │ 🚑 MIST        │                     │
│  │ 一般/內科     │  │ 外傷/創傷      │                     │
│  │      ●        │  │                │                     │
│  └────────────────┘  └────────────────┘                     │
│                                                              │
│  ─────────── 病患基本資料 ───────────                       │
│                                                              │
│  姓名: [________]   年齡: [__]   性別: ○男 ●女             │
│  身高(cm): [___]    體重(kg): [___]                         │
│  過敏: [________________________]                            │
│                                                              │
│  ─────────── 生命徵象 ───────────                           │
│                                                              │
│  BP: [___/___]  HR: [___]  SpO2: [___%]  Temp: [__._]      │
│                                                              │
│  GCS:  E [1-4]  V [1-5]  M [1-6]  = 15                      │
│        [  4 ]   [  5 ]   [  6 ]                              │
│                                                              │
│  ─────────── ISBAR 內容 ───────────                         │
│                                                              │
│  S - 現況說明:                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│  B - 病史背景:                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│  A - 評估:                                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│  R - 建議:                                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ─────────── 轉送資訊 ───────────                           │
│                                                              │
│  目的地: [________________________]                          │
│  O2 需求: [無] [3] [6] [10] [15] L/min                      │
│  優先序: ○ NORMAL  ● URGENT                                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
│                                                              │
│  [取消]                               [建立並進入物資整備]   │
└─────────────────────────────────────────────────────────────┘
```

#### 2.5.2 資料結構

```javascript
// 手動交班單 (source_type = 'EXTERNAL')
const manualHandoff = {
    source_type: 'EXTERNAL',  // 非 CIRS 來源
    format: 'ISBAR',          // 或 'MIST'

    // 病患資料 (手動輸入)
    patient: {
        name: '外站病患',
        age: 45,
        gender: 'M',
        height_cm: 170,
        weight_kg: 70,
        allergies: ''
    },

    // 生命徵象 (GCS 採用 E/V/M 格式)
    vital_signs: {
        bp_sys: 120,
        bp_dia: 80,
        hr: 75,
        spo2: 98,
        temp: 36.5,
        gcs_e: 4,
        gcs_v: 5,
        gcs_m: 6
    },

    // ISBAR 內容
    content: {
        situation: '',
        background: '',
        assessment: '',
        recommendation: ''
    },

    // 轉送資訊
    destination: '',
    o2_flow: 0,
    priority: 'NORMAL'
};
```

#### 2.5.3 API

```http
POST /api/transfer/handoff/manual
Content-Type: application/json

{
    "source_type": "EXTERNAL",
    "format": "ISBAR",
    "patient": { ... },
    "vital_signs": { ... },
    "content": { ... },
    "destination": "後送醫院 A",
    "o2_flow": 6,
    "priority": "URGENT"
}
```

**回應**:
```json
{
    "handoff_id": "HO-20260105-EXT-001",
    "mission_id": "TM-1736065432000",
    "status": "PLANNING"
}
```

### 2.6 交班詳情顯示 (只讀)

```
┌─────────────────────────────────────────────────────────────┐
│ 交班詳情                                    MIST (外傷)     │
├─────────────────────────────────────────────────────────────┤
│ 【病患資料】                                                 │
│ 姓名: 王大明    年齡: 45    性別: 男                        │
│ 身高: 175 cm   體重: 72 kg   BMI: 23.5                     │
│ 過敏: Penicillin                                            │
│                                                             │
│ ─────────────────────────────────────────────────────────   │
│ M - 受傷機轉                                                │
│     車禍: 機車對撞，時速約 60 km/h                          │
│                                                             │
│ I - 傷勢發現                                                │
│     [●] 四肢  右股骨開放性骨折，約 15cm 傷口                │
│                                                             │
│ S - 生命徵象 (CIRS 最新記錄)                                │
│     BP: 110/70  HR: 100  SpO2: 98%  GCS: E4V5M6            │
│                                                             │
│ T - 已處置                                                  │
│     止血帶、夾板固定、TXA 1g、IV access                     │
│ ─────────────────────────────────────────────────────────   │
│                                                             │
│ 【轉送資訊】                                                 │
│ 目的地: 後送醫院 A - 創傷中心                               │
│ O2: 6 L/min    ETA: 45 min                                 │
│                                                             │
│ 建立者: 李醫師    建立時間: 2026-01-05 10:32               │
└─────────────────────────────────────────────────────────────┘
│                                                             │
│  [取消]                          [確認接收，進入物資整備]   │
└─────────────────────────────────────────────────────────────┘
```

> **重要**: 以上資料皆為**只讀**，來自 CIRS `handoff_records.snapshot`

---

## 3. Step 1: 物資整備

v3.0 架構下，Step 1 專注於**物資準備**，交班資料已在 Step 0 接收完成。

### 3.1 物資整備 UI

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1/3: 物資整備                                          │
├─────────────────────────────────────────────────────────────┤
│ 【病患摘要】(來自交班)                                       │
│ 王大明 45M | MIST (外傷) | O2: 6 L/min                      │
│ 目的地: 後送醫院 A                                          │
├─────────────────────────────────────────────────────────────┤
│ 【氧氣鋼瓶】                                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ E 瓶 #E-042                                    [選擇]  │ │
│ │ 初始 PSI: [1800]   容量: 682L   預估 1.9 小時           │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 【攜帶設備】                                                │
│ [✓] 心電圖監測器     電量: 87%                              │
│ [✓] 抽吸機           電量: 100%                             │
│ [ ] 除顫器                                                  │
│ [+] 新增設備...                                             │
│                                                             │
│ 【攜帶藥物/耗材】                                            │
│ [✓] TXA 1g × 2                                             │
│ [✓] Morphine 10mg × 1                                      │
│ [✓] NS 500mL × 2                                           │
│ [+] 新增藥物/耗材...                                        │
│                                                             │
│ 【物資發放】                                 [RESERVE 全部]  │
└─────────────────────────────────────────────────────────────┘
│                                                             │
│  [返回 Step 0]                      [開始轉送 (Step 2)]     │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 PSI 估算 (同麻醉模組)

```javascript
// 預估可用時間
function estimateO2Duration(psi, flowRate) {
    // E 瓶: 0.379 L/PSI
    const E_CYLINDER_FACTOR = 0.379;
    const litersAvailable = psi * E_CYLINDER_FACTOR;
    const durationMinutes = litersAvailable / flowRate;
    return {
        liters: litersAvailable.toFixed(0),
        hours: (durationMinutes / 60).toFixed(1),
        safetyMargin: durationMinutes > 120 ? 'SAFE' : durationMinutes > 60 ? 'CAUTION' : 'LOW'
    };
}
```

### 3.3 物資操作 Event Sourcing

```javascript
// RESERVE: 預留物資 (離開前)
async reserveResources() {
    for (const item of this.selectedResources) {
        await this.appendMissionEvent({
            event_type: 'RESOURCE_RESERVE',
            resource_type: item.type,  // O2_CYLINDER | EQUIPMENT | MEDICATION
            resource_id: item.id,
            quantity: item.qty,
            initial_value: item.initial_psi || null
        });
    }
}

// ISSUE: 實際發放 (開始轉送時)
async issueResources() {
    for (const item of this.reservedResources) {
        await this.appendMissionEvent({
            event_type: 'RESOURCE_ISSUE',
            resource_id: item.id,
            quantity: item.qty
        });
    }
}
```

---

## 4. Step 2: 轉送中

### 4.1 轉送中 UI

```
┌─────────────────────────────────────────────────────────────┐
│ Step 2/3: 轉送中                           ⏱ 00:23:45       │
├─────────────────────────────────────────────────────────────┤
│ 【即時狀態】                                                 │
│ O2 剩餘: 1420 PSI (約 1.4 小時)  ████████░░ 79%             │
│                                                             │
│ 生命徵象最新: 10:55                                          │
│ BP: 115/72  HR: 92  SpO2: 99%  (穩定)                       │
│                                    [記錄新 Vital Signs]     │
├─────────────────────────────────────────────────────────────┤
│ 【途中事件】                                                 │
│ 10:35  開始轉送                                              │
│ 10:42  更換 O2 流量 6→10 L/min (SpO2 下降至 94%)            │
│ 10:48  給予 Morphine 5mg IV                                 │
│ 10:55  Vital signs 穩定                                     │
│                                                             │
│                                    [+] 記錄途中事件          │
├─────────────────────────────────────────────────────────────┤
│ 【快速操作】                                                 │
│ [O2 調整] [給藥] [Vital Signs] [緊急事件]                   │
└─────────────────────────────────────────────────────────────┘
│                                                             │
│  [中止任務]                               [抵達目的地]       │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 途中事件 (Addenda)

EMT 在轉送途中**只寫 addenda**，不修改原交班內容：

```javascript
async addTransitEvent(eventType, data) {
    await this.appendMissionEvent({
        event_type: 'TRANSIT_EVENT',
        sub_type: eventType,  // VITALS | O2_ADJUST | MEDICATION | EMERGENCY | NOTE
        data: data,
        timestamp: new Date().toISOString(),
        recorded_by: this.currentUser.id
    });

    // 同時記錄到 CIRS (如果有網路)
    if (navigator.onLine && this.currentMission.cirs_handoff_id) {
        await fetch(`${CIRS_HUB_URL}/api/handoff/${this.currentMission.cirs_handoff_id}/addendum`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.token}`
            },
            body: JSON.stringify({
                source: 'EMT',
                event_type: eventType,
                data: data
            })
        });
    }
}
```

### 4.3 O2 流量調整

```
┌─────────────────────────────────────────────────────────────┐
│ 調整 O2 流量                                                 │
├─────────────────────────────────────────────────────────────┤
│ 目前: 6 L/min                                               │
│                                                             │
│ [無] [3] [6] [10] [15]                                      │
│                  ●                                          │
│                                                             │
│ 調整原因:                                                    │
│ ○ SpO2 下降     ○ 病患穩定     ○ 其他: [________]          │
│                                                             │
│ 目前 SpO2: [94] %                                           │
└─────────────────────────────────────────────────────────────┘
│                               [取消]      [確認調整]         │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Step 3: 結案

### 5.1 結案 UI

```
┌─────────────────────────────────────────────────────────────┐
│ Step 3/3: 結案                                              │
├─────────────────────────────────────────────────────────────┤
│ 【轉送摘要】                                                 │
│ 病患: 王大明 45M                                            │
│ 目的地: 後送醫院 A                                          │
│ 轉送時間: 10:35 ~ 11:02 (27 分鐘)                           │
├─────────────────────────────────────────────────────────────┤
│ 【物資消耗統計】                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 氧氣 E 瓶 #E-042                                        │ │
│ │ 初始: 1800 PSI → 結束: 1420 PSI                         │ │
│ │ 消耗: 380 PSI (約 144L)                                 │ │
│ │ 結束 PSI: [1420]                              [更新]   │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 藥物/耗材消耗:                                               │
│ [✓] TXA 1g × 1 (使用 1，歸還 1)                            │
│ [✓] Morphine 10mg × 1 (使用 1，歸還 0)                     │
│ [✓] NS 500mL × 1 (使用 1，歸還 1)                          │
│                                                             │
│ 設備歸還:                                                    │
│ [✓] 心電圖監測器     電量: 72%                              │
│ [✓] 抽吸機           電量: 85%                              │
├─────────────────────────────────────────────────────────────┤
│ 【結案備註】                                                 │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 病患順利交接至急診，意識清醒，生命徵象穩定             │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
│                                                             │
│  [返回 Step 2]                      [確認結案]              │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 結案流程

```javascript
async completeMission() {
    // 1. 記錄最終 PSI
    await this.appendMissionEvent({
        event_type: 'RESOURCE_RETURN',
        resource_type: 'O2_CYLINDER',
        resource_id: this.currentMission.o2_cylinder_id,
        final_psi: this.endingPsi,
        consumed_psi: this.startingPsi - this.endingPsi
    });

    // 2. 記錄物資歸還
    for (const item of this.resourceSummary) {
        await this.appendMissionEvent({
            event_type: 'RESOURCE_RETURN',
            resource_id: item.id,
            used_qty: item.used,
            returned_qty: item.returned
        });
    }

    // 3. 更新任務狀態
    this.currentMission.status = 'COMPLETED';
    this.currentMission.completed_at = new Date().toISOString();

    // 4. 通知 CIRS 交班完成
    if (this.currentMission.cirs_handoff_id) {
        await fetch(`${CIRS_HUB_URL}/api/handoff/${this.currentMission.cirs_handoff_id}/complete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.token}`
            },
            body: JSON.stringify({
                completed_at: this.currentMission.completed_at,
                final_notes: this.closingNotes,
                resource_summary: this.resourceSummary
            })
        });
    }

    // 5. 儲存並重置
    await this.saveMission();
    this.showCompletionSummary();
}
```

---

## 6. 資料模型 (v3.0)

### 6.1 MIRS transfer_missions (簡化版)

v3.0 移除重複的交班欄位，改為參照 CIRS：

```sql
CREATE TABLE transfer_missions (
    mission_id TEXT PRIMARY KEY,

    -- CIRS 參照 (唯一真相來源)
    cirs_handoff_id TEXT,           -- FK → CIRS handoff_records
    patient_snapshot JSON,          -- 接收時鎖定的快照副本

    -- 本地任務資料
    status TEXT DEFAULT 'PLANNING', -- PLANNING | READY | EN_ROUTE | COMPLETED | CANCELLED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- 物資 (透過 events 追蹤)
    -- 途中事件 (透過 events 追蹤)

    closing_notes TEXT
);

-- 事件日誌 (Event Sourcing)
CREATE TABLE transfer_mission_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    -- RESOURCE_RESERVE | RESOURCE_ISSUE | RESOURCE_RETURN
    -- TRANSIT_EVENT | STATUS_CHANGE
    data JSON,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    recorded_by TEXT
);
```

### 6.2 與 CIRS handoff_records 的關係

```
┌─────────────────────────────────────────────────────────────┐
│  CIRS (Hub)                        MIRS (Satellite)         │
├─────────────────────────────────────────────────────────────┤
│  handoff_records          ───▶     transfer_missions        │
│    ├─ handoff_id                     ├─ mission_id          │
│    ├─ snapshot (locked)              ├─ cirs_handoff_id ────┤
│    ├─ content (ISBAR/MIST)           ├─ patient_snapshot    │
│    └─ status                         └─ status              │
│                                                             │
│  handoff_addenda          ◀───     mission_events           │
│    (來自 EMT 的補充)                   (途中事件)            │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Alpine.js 資料結構

### 7.1 主要資料物件

```javascript
// EMT PWA: emtTransfer()
return {
    // 連線狀態
    cirsConnected: false,
    cirsHubUrl: localStorage.getItem('cirs_hub_url') || '',

    // 待接收交班列表
    pendingHandoffs: [],

    // 目前任務
    currentMission: null,
    currentStep: 0,  // 0=接收交班, 1=物資整備, 2=轉送中, 3=結案

    // 物資選擇
    selectedO2Cylinder: null,
    selectedEquipment: [],
    selectedMedications: [],

    // 途中事件
    transitEvents: [],

    // 結案資料
    endingPsi: null,
    resourceSummary: [],
    closingNotes: '',

    // 方法
    async init() {
        await this.checkCirsConnection();
        await this.loadPendingHandoffs();
    },

    async loadPendingHandoffs() {
        if (!this.cirsConnected) return;
        const resp = await fetch(`${this.cirsHubUrl}/api/handoff/pending?target_role=EMT`, {
            headers: { 'Authorization': `Bearer ${this.token}` }
        });
        this.pendingHandoffs = await resp.json();
    },

    async acceptHandoff(handoffId) {
        // ... (如 Section 2.2)
    },

    async addTransitEvent(type, data) {
        // ... (如 Section 4.2)
    },

    async completeMission() {
        // ... (如 Section 5.2)
    }
}
```

### 7.2 顯示交班內容 (只讀)

```javascript
// 從 snapshot 解析顯示
get patientInfo() {
    const s = this.currentMission?.patient_snapshot;
    if (!s) return null;
    return {
        name: s.person?.name,
        age: s.person?.age,
        gender: s.person?.gender === 'M' ? '男' : '女',
        bmi: s.person?.height_cm && s.person?.weight_kg
            ? (s.person.weight_kg / Math.pow(s.person.height_cm/100, 2)).toFixed(1)
            : '-',
        allergies: s.person?.allergies || '無'
    };
},

get handoffContent() {
    const c = this.currentMission?.content;
    if (!c) return null;

    // 根據 format 解析
    if (c.format === 'MIST') {
        return {
            format: 'MIST',
            mechanism: c.mechanism,
            injuries: c.injuries,
            signs: c.signs,
            treatment: c.treatment
        };
    } else {
        return {
            format: 'ISBAR',
            situation: c.situation,
            background: c.background,
            assessment: c.assessment,
            recommendation: c.recommendation
        };
    }
}
```

---

## 8. O2 流量預設值 (已實作 v1.1.0)

### 8.1 按鈕配置

```
[無] [3] [6] [10] [15]
```

### 8.2 對照表

| 選項 | L/min | 適用情境 |
|------|-------|----------|
| 無 | 0 | 無氧氣需求 |
| 3 | 3 | 鼻導管低流量 |
| 6 | 6 | 鼻導管中流量 |
| 10 | 10 | 面罩 / NRB |
| 15 | 15 | NRB 高流量 / BVM |

---

## 9. 實作順序

### Phase 1: O2 流量快選 ✓ (v1.1.0 已完成)

### Phase 2: CIRS 統一交班 API (CIRS 端)

> 詳見 `CIRS/docs/xIRS_UNIFIED_HANDOFF_SPEC_v1.0.md`

| 步驟 | 變更 |
|------|------|
| 2.1 | 新增 `handoff_records` 表 |
| 2.2 | 新增 `/api/handoff` API 路由 |
| 2.3 | Doctor PWA 整合「建立交班」 |

### Phase 3: EMT PWA Step 重構 (MIRS 端)

| 步驟 | 檔案 | 變更 |
|------|------|------|
| 3.1 | `static/emt/index.html` | Step 0 待接收交班列表 |
| 3.2 | `static/emt/index.html` | Step 1 物資整備 UI |
| 3.3 | `static/emt/index.html` | Step 2 轉送中 + 途中事件 |
| 3.4 | `static/emt/index.html` | Step 3 結案 UI |
| 3.5 | `database/` | 簡化 transfer_missions schema |
| 3.6 | `routes/transfer.py` | Event sourcing API |

### Phase 4: CIRS/MIRS 雙向同步

| 步驟 | 變更 |
|------|------|
| 4.1 | EMT → CIRS: POST addendum (途中事件) |
| 4.2 | EMT → CIRS: POST complete (結案通知) |
| 4.3 | 離線佇列 + 恢復同步 |

---

## 10. 注意事項

### 10.1 Snapshot 鎖定原則

- EMT 接收交班時，`snapshot` 即鎖定，之後不隨 CIRS 更新
- 醫療法律責任以 snapshot 版本為準
- 如需修改，醫師須在 CIRS 建立新版交班

### 10.2 離線處理

- 交班 snapshot 本地儲存於 IndexedDB
- 途中事件先寫本地，恢復連線後 sync
- 物資操作即時記錄，不依賴網路

### 10.3 隱私保護

- 病患資料只在任務期間保存
- 結案後保留統計摘要，清除詳細病歷
- 符合 HIPAA/GDPR 要求

---

## 附錄 A: ISBAR/MIST 格式參考

### A.1 ISBAR 格式 (一般/內科)

| 欄位 | 英文 | 說明 | 範例 |
|------|------|------|------|
| **I** | Identify | 身份辨識 | 王小明，45歲，男性 |
| **S** | Situation | 現況說明 | 胸痛 2 小時，需轉送心導管室 |
| **B** | Background | 病史背景 | HTN, DM, 過敏: Penicillin |
| **A** | Assessment | 評估狀況 | BP 150/90, HR 88, SpO2 98% |
| **R** | Recommendation | 建議事項 | 監測心電圖，準備 NTG |

### A.2 MIST 格式 (外傷)

| 欄位 | 英文 | 說明 | 範例 |
|------|------|------|------|
| **M** | Mechanism | 受傷機轉 | 機車對撞，時速約 60 |
| **I** | Injuries | 傷勢發現 | 右股骨開放性骨折，右胸挫傷 |
| **S** | Signs | 生命徵象 | GCS 15, BP 110/70, HR 100 |
| **T** | Treatment | 已處置 | 止血帶、夾板固定、TXA 1g |

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*文件版本: v3.0*
*更新日期: 2026-01-05*
