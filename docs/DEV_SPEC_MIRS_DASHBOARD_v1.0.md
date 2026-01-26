# DEV_SPEC_MIRS_DASHBOARD_v1.0

MIRS 分析儀表板開發規格

**版本**: 1.0
**日期**: 2026-01-27
**狀態**: 已實作
**參考**: MASTER_ROADMAP_v1.1 P2-02

---

## 1. 概述

MIRS Analytics Dashboard 提供即時的麻醉作業統計與監控功能，包括：

- 案例統計 (今日/本週/本月/進行中)
- 案例趨勢圖表 (近30日)
- 狀態分布
- 常用藥物統計
- 設備使用狀態
- 系統警示 (低氧氣、血品過期)

---

## 2. 架構

```
┌─────────────────────────────────────────────────────────┐
│                    MIRS Dashboard                       │
│               /dashboard/index.html                     │
│                    (Alpine.js)                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Analytics API Endpoints                    │
│                 /api/analytics/*                        │
│              routes/analytics.py                        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              SQLite Database                            │
│           medical_inventory.db                          │
│  - anesthesia_cases                                     │
│  - anesthesia_events                                    │
│  - equipment_units                                      │
│  - blood_units (optional)                               │
└─────────────────────────────────────────────────────────┘
```

---

## 3. API 端點

### 3.1 `/api/analytics/dashboard`

**摘要儀表板資料**

Response:
```json
{
    "today_cases": 5,
    "week_cases": 23,
    "month_cases": 89,
    "active_cases": 2,
    "equipment_summary": {
        "AVAILABLE": 10,
        "IN_USE": 3,
        "EMPTY": 1
    },
    "alerts": [
        {
            "type": "low_oxygen",
            "severity": "warning",
            "message": "H型5號 low (15%)",
            "equipment_id": "..."
        }
    ],
    "last_updated": "2026-01-27T10:30:00"
}
```

### 3.2 `/api/analytics/cases/summary`

**案例統計摘要**

Query Parameters:
- `start_date` (optional): YYYY-MM-DD
- `end_date` (optional): YYYY-MM-DD

Response:
```json
{
    "total_cases": 89,
    "by_status": {
        "PREOP": 2,
        "IN_PROGRESS": 1,
        "PACU": 1,
        "CLOSED": 85
    },
    "avg_anesthesia_duration_min": 95.5,
    "avg_surgery_duration_min": 72.3,
    "by_asa_class": {
        "ASA-I": 45,
        "ASA-II": 30,
        "ASA-III": 14
    },
    "by_anesthesiologist": [
        {"name": "Dr. Chen", "case_count": 25, "avg_duration": 88.5},
        {"name": "Dr. Lin", "case_count": 20, "avg_duration": 92.1}
    ]
}
```

### 3.3 `/api/analytics/cases/daily`

**每日案例趨勢**

Query Parameters:
- `days` (default: 30): 1-365

Response:
```json
[
    {"date": "2026-01-27", "case_count": 5, "avg_duration_min": 95.5, "medication_count": 42},
    {"date": "2026-01-26", "case_count": 8, "avg_duration_min": 88.2, "medication_count": 65}
]
```

### 3.4 `/api/analytics/medications/usage`

**藥物使用統計**

Query Parameters:
- `start_date` (optional): YYYY-MM-DD
- `end_date` (optional): YYYY-MM-DD
- `limit` (default: 20): 1-100

Response:
```json
[
    {"drug_name": "Propofol", "administrations": 234, "total_dose": 4680.0, "unit": "mg"},
    {"drug_name": "Fentanyl", "administrations": 198, "total_dose": 9900.0, "unit": "mcg"}
]
```

### 3.5 `/api/analytics/equipment/utilization`

**設備使用率**

Response:
```json
[
    {
        "equipment_id": "H-001",
        "name": "H型氧氣鋼瓶",
        "total_claims": 45,
        "current_status": "AVAILABLE",
        "level_percent": 85.0
    }
]
```

### 3.6 `/api/analytics/oxygen/consumption`

**氧氣消耗統計**

Query Parameters:
- `days` (default: 30): 1-365

Response:
```json
{
    "by_type": {
        "H-type": {"usage_events": 45, "level_drop_percent": 120.5, "estimated_liters": 8314.5},
        "E-type": {"usage_events": 20, "level_drop_percent": 80.0, "estimated_liters": 544.0}
    },
    "total_liters": 8858.5,
    "period_days": 30
}
```

### 3.7 `/api/analytics/health`

**模組健康檢查**

Response:
```json
{
    "status": "healthy",
    "module": "analytics",
    "version": "1.0",
    "timestamp": "2026-01-27T10:30:00"
}
```

---

## 4. 前端實作

### 4.1 技術堆疊

| 項目 | 選擇 | 原因 |
|------|------|------|
| Framework | Alpine.js 3.x | 輕量、無需編譯 |
| Charts | Pure CSS Bars | 無外部依賴 |
| Styling | CSS Variables | 主題一致性 |
| State | Alpine.js reactive | 即時更新 |

### 4.2 檔案結構

```
frontend/dashboard/
├── index.html      # 主頁面 (含 Alpine.js 邏輯)
└── manifest.json   # PWA manifest
```

### 4.3 UI 結構

```
┌─────────────────────────────────────────────────────────┐
│  MIRS 分析儀表板                        [重新整理]       │
│  最後更新: 10:30:00                                     │
├─────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│ │ 今日    │ │ 本週    │ │ 本月    │ │ 進行中  │        │
│ │   5     │ │   23    │ │   89    │ │    2    │        │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘        │
├─────────────────────────────────────────────────────────┤
│ 案例趨勢 (近30日)          │ 狀態分布                   │
│ ▄▄▄█▄▄▄▄█▄▄▄▄▄█▄▄▄▄       │ ● 已結案: 85              │
│                            │ ● 恢復室: 2               │
│                            │ ● 進行中: 1               │
│                            │ ● 術前準備: 1             │
├─────────────────────────────────────────────────────────┤
│ 常用藥物              │ 設備狀態                        │
│ Propofol      [234]   │ H型氧氣鋼瓶   85%              │
│ Fentanyl      [198]   │ E型氧氣瓶     72%              │
│ Rocuronium    [167]   │ 呼吸器        AVAILABLE        │
├─────────────────────────────────────────────────────────┤
│ 警示                                                    │
│ ⚠️ H型5號 low (15%)                                     │
│ ⚠️ Blood O- expiring (2 days)                           │
├─────────────────────────────────────────────────────────┤
│ 快速連結                                                │
│ [麻醉紀錄] [血庫管理] [藥局] [設備管理] [CIRS儀表板→]   │
└─────────────────────────────────────────────────────────┘
```

### 4.4 自動更新

```javascript
// 每 60 秒自動更新
setInterval(() => this.refresh(), 60000);
```

---

## 5. 資料表依賴

| 資料表 | 用途 | 必要 |
|--------|------|------|
| `anesthesia_cases` | 案例統計 | ✓ |
| `anesthesia_events` | 藥物、事件統計 | ✓ |
| `equipment_units` | 設備狀態 | ✓ |
| `equipment` | 設備名稱 | ✓ |
| `blood_units` | 血品警示 | Optional |

---

## 6. 已知限制

1. **無資料時顯示空白**: 若資料庫無資料，圖表和列表會顯示空白
2. **無分頁**: 設備和藥物列表最多顯示 5-6 筆
3. **無匯出功能**: 目前無法匯出報表

---

## 7. 未來擴展 (P4)

- [ ] PDF 報表匯出
- [ ] 日期範圍選擇器
- [ ] 更多圖表類型 (圓餅圖、折線圖)
- [ ] 人員工作量統計
- [ ] 與 CIRS 資料整合

---

## 8. 相關檔案

| 檔案 | 說明 |
|------|------|
| `routes/analytics.py` | API 端點實作 |
| `frontend/dashboard/index.html` | 前端 UI |
| `frontend/dashboard/manifest.json` | PWA 設定 |
| `main.py:3449-3452` | Dashboard 掛載 |
| `main.py:127-133` | Analytics router 載入 |

---

## 9. 測試方式

```bash
# 啟動 MIRS Server
cd /path/to/MIRS-v2.0-single-station
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# 測試 API
curl -s http://localhost:8000/api/analytics/dashboard | python3 -m json.tool
curl -s http://localhost:8000/api/analytics/health | python3 -m json.tool

# 訪問儀表板
open http://localhost:8000/dashboard/
```

---

## 10. 版本歷史

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-01-27 | 初始版本 |

---

*DEV_SPEC_MIRS_DASHBOARD_v1.0*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
