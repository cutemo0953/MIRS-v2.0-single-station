# MIRS 麻醉模組 PDF 輸出功能 - 開發成果報告

**日期**: 2026-01-24
**版本**: v2.2
**專案**: MIRS v2.0 Single Station
**模組**: 麻醉紀錄 PWA (Anesthesia Record)

---

## 1. 開發摘要

本次開發完成了 MIRS 麻醉模組的 **PDF 輸出功能**，可生成符合烏日林新醫院 **M0073 麻醉紀錄單**格式的 PDF 文件。

### 主要成就

| 項目 | 說明 |
|------|------|
| **PDF 生成 API** | `GET /api/anesthesia/cases/{id}/pdf` |
| **HTML 預覽** | `GET /api/anesthesia/cases/{id}/pdf/preview` |
| **環境適配** | 支援 Vercel (HTML) 與本地/RPi5 (PDF) |
| **Event Sourcing** | 從事件重建狀態再渲染，確保資料一致性 |
| **自動分頁** | 每頁 24 筆生命徵象，長手術自動多頁 |

---

## 2. Git 提交歷史 (2026-01-23 ~ 2026-01-24)

共 **20 次提交**，涵蓋 PDF 功能完整開發週期：

```
791ca0f Align chart data points with vitals table columns
4725d6c Fix PDF chart width and alignment with vitals table
e4328e2 Redesign PDF layout: 3-column with aligned chart/table
c857b7a Optimize PDF layout for better space utilization
17be49a Fix: use local date instead of UTC for case filtering
0bc99b8 Fix: use CLOSED status instead of COMPLETED
240c536 Fix PDF layout and add long surgery demo case
b760e71 feat(anesthesia): change PDF button to show preview first, add download option
d591483 fix(anesthesia): support multiple event type names in _rebuild_state_from_events
2df48d8 feat(anesthesia): add complete demo data with vitals, meds, IV, I/O (v2.1.2)
34d2222 fix(anesthesia): use recorded_at instead of created_at in events query
641cec6 feat(anesthesia): add seeder for demo patients (v2.1.1)
4af9f1a feat(anesthesia): add diagnosis and operation fields (v2.1.1)
39602fa fix(anesthesia): use Jinja2-safe string check for hospital_address
7ecbe33 fix(anesthesia): resolve M0073 display issues
eb93e89 feat(anesthesia): redesign M0073 layout with large SVG chart as main focus
6c5acfb fix(anesthesia): support both matplotlib (RPi5) and SVG (Vercel) charts
8e129f4 feat(anesthesia): replace matplotlib chart with SVG vital signs chart
7aab887 fix(anesthesia): add IS_VERCEL demo mode to PDF preview endpoint
6600f60 fix(vercel): add jinja2 and templates for PDF preview
```

---

## 3. 修改檔案清單

### 3.1 核心檔案

| 檔案 | 修改次數 | 說明 |
|------|----------|------|
| `routes/anesthesia.py` | 5 | PDF 生成邏輯、事件重建函式 |
| `templates/anesthesia_record_m0073.html` | 7 | PDF 模板、SVG 圖表、版面配置 |
| `seeder_demo.py` | 4 | 示範資料生成器 |
| `frontend/anesthesia/index.html` | 3 | 前端 UI 改進 |

### 3.2 新增檔案

- `templates/anesthesia_record_m0073.html` - M0073 PDF 模板 (726 行)

### 3.3 程式碼統計

| 檔案 | 行數 |
|------|------|
| `routes/anesthesia.py` | 8,752 行 |
| `templates/anesthesia_record_m0073.html` | 726 行 |
| `seeder_demo.py` | 57,091 字元 |

---

## 4. 功能細節

### 4.1 PDF 生成流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      PDF 生成流程                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. API 請求                                                     │
│     GET /api/anesthesia/cases/{case_id}/pdf?preview=false       │
│                           │                                      │
│                           ▼                                      │
│  2. 依賴檢查                                                     │
│     ├─ Jinja2 (必要)                                            │
│     └─ WeasyPrint + Matplotlib (PDF 模式必要)                   │
│                           │                                      │
│                           ▼                                      │
│  3. 環境判斷                                                     │
│     ├─ IS_VERCEL=true  → 返回示範資料 HTML                      │
│     └─ IS_VERCEL=false → 查詢真實資料庫                         │
│                           │                                      │
│                           ▼                                      │
│  4. 資料擷取                                                     │
│     ├─ anesthesia_cases (病例基本資訊)                          │
│     └─ anesthesia_events (所有事件記錄)                         │
│                           │                                      │
│                           ▼                                      │
│  5. 事件重建 (_rebuild_state_from_events)                       │
│     ├─ vitals[]     - 生命徵象                                  │
│     ├─ drugs[]      - 用藥記錄                                  │
│     ├─ iv_lines[]   - IV 管路                                   │
│     ├─ monitors[]   - 監測器                                    │
│     ├─ io_balance   - 進出量平衡                                │
│     └─ times        - 麻醉/手術時間                             │
│                           │                                      │
│                           ▼                                      │
│  6. 分頁處理                                                     │
│     └─ 每頁 VITALS_PER_PAGE = 24 筆                             │
│                           │                                      │
│                           ▼                                      │
│  7. 圖表生成                                                     │
│     ├─ SVG (Vercel/瀏覽器渲染)                                  │
│     └─ Matplotlib PNG (本地/RPi5)                               │
│                           │                                      │
│                           ▼                                      │
│  8. Jinja2 渲染                                                  │
│     └─ anesthesia_record_m0073.html                             │
│                           │                                      │
│                           ▼                                      │
│  9. 輸出                                                         │
│     ├─ preview=true  → StreamingResponse(HTML)                  │
│     └─ preview=false → WeasyPrint → PDF                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 M0073 PDF 版面

```
┌─────────────────────────────────────────────────────────────────┐
│ 烏日林新醫院      麻醉紀錄 ANESTHETIC RECORD        M0073 p1/1  │
├─────────────────────────────────────────────────────────────────┤
│ 姓名:王大明 性別:男 年齡:45  │ Dx: Appendicitis               │
│ 體重:70kg 身高:170cm ASA:II  │ Op: Lap. Appendectomy          │
│ 血型:A+ OR:OR-01             │ Hb:14 Ht:42% K:4.0 Na:140      │
│ ☑GA(ETT) ☐Spinal ☐Epidural  │ 預估失血:200mL 備血:PRBC 2U    │
├─────────┬───────────────────────────────────┬───────────────────┤
│ 藥物     │              中央區域              │    監測面板       │
│ Drugs    │  ┌───────────────────────────┐   │ ┌───────────────┐ │
│          │  │    SVG 生命徵象圖表        │   │ │   Monitors    │ │
│ 08:30    │  │  ━━━ SBP  ━━━ DBP  ▪▪▪ HR │   │ │ ☑EKG ☑NIBP   │ │
│ Propofol │  └───────────────────────────┘   │ │ ☑SpO2 ☑ETCO2 │ │
│ 150mg    │  ┌───────────────────────────┐   │ └───────────────┘ │
│          │  │ Hr │08│08│09│09│10│10│   │   │ ┌───────────────┐ │
│ 08:31    │  │:mm │30│45│00│15│00│15│   │   │ │   IV Lines    │ │
│ Fentanyl │  │SBP │120│115│110│108│122│125│  │   │ │ #1 右手 20G   │ │
│ 100mcg   │  │DBP │80│75│70│68│78│80│   │   │ └───────────────┘ │
│          │  │HR  │72│68│65│62│72│75│   │   │ ┌───────────────┐ │
├─────────┤  │SpO2│99│100│100│99│100│99│ │   │ │  I/O Balance  │ │
│ Agents   │  │CO2 │35│34│33│34│35│36│   │   │ │ 晶體: 1000ml  │ │
│ O2  Sevo │  │T°  │36.5│36.4│36.3│...│  │   │ │ 膠體:    0ml  │ │
│ 2L  2%   │  └───────────────────────────┘   │ │ 血品:    0ml  │ │
│          │                                   │ │ In:   1000ml  │ │
│          │                                   │ │ 尿量:  300ml  │ │
│          │                                   │ │ 失血:  100ml  │ │
│          │                                   │ │ Out:   400ml  │ │
│          │                                   │ │ Net:  +600ml  │ │
└─────────┴───────────────────────────────────┴───────────────────┤
│ 麻醉: 08:30-11:00 │ 手術: 09:00-10:30 │ 麻醉醫師: │ 護理師:     │
│                  Generated by MIRS v2.2 | 2026-01-24 01:00:00   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 圖表與表格對齊技術 (v2.2.1)

使用 **固定寬度 wrapper** 確保 Matplotlib/SVG 圖表與表格完美對齊：

```
┌──────────────────────────────────────────────────────────────────┐
│  chart-wrapper / vitals-table                                     │
│  ┌────────┬─────────────────────────────────────────────────────┐ │
│  │ 28px   │  flex:1 (資料區域)                                   │ │
│  │ 固定   │  每欄寬度 = 100% / N                                 │ │
│  │ Y軸    │  資料點 X = (i + 0.5) * col_width                    │ │
│  └────────┴─────────────────────────────────────────────────────┘ │
│  ┌────────┬─────────────────────────────────────────────────────┐ │
│  │ row-   │  :07 | :17 | :27 | :37 | ... (時間)                 │ │
│  │ header │  120 | 115 | 110 | 108 | ... (SBP)                  │ │
│  │ 28px   │  80  | 75  | 70  | 68  | ... (DBP)                  │ │
│  └────────┴─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**對齊原理：**
- Y 軸標籤區域 = row-header 寬度 = 28px 固定
- 資料區域使用 flex:1 填滿剩餘空間
- 欄位寬度 = 100% / N (N = vitals 數量)
- 資料點 X 座標 = (i + 0.5) / N * 100% (欄位中心)

---

## 5. 前端改進

### 5.1 PDF 預覽/下載按鈕

```javascript
// 預覽 (新視窗開啟 HTML)
window.open(`/api/anesthesia/cases/${caseId}/pdf?preview=true`, '_blank');

// 下載 (觸發 PDF 下載)
window.location.href = `/api/anesthesia/cases/${caseId}/pdf`;
```

### 5.2 日期篩選修正

修正 UTC/本地時區問題，確保日期篩選使用本地時間：

```javascript
// 修正前 (UTC)
const today = new Date().toISOString().split('T')[0];

// 修正後 (本地時區)
const today = new Date();
const localDate = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
```

---

## 6. 示範資料

`seeder_demo.py` 新增完整示範資料：

| 資料類型 | 內容 |
|----------|------|
| 病患 | 王大明 (45歲/男) |
| 手術 | 腹腔鏡膽囊切除術 |
| 生命徵象 | 每 15 分鐘一筆，共 9-24+ 筆 |
| 用藥 | Propofol, Fentanyl, Rocuronium, Sevoflurane, Ondansetron |
| IV 管路 | #1 右手背 20G |
| I/O 平衡 | In: 1000ml, Out: 400ml, Net: +600ml |
| 長手術案例 | 3+ 小時，>24 vitals，測試分頁 |

---

## 7. 技術債與未來改進

### 7.1 已知限制

| 項目 | 說明 |
|------|------|
| WeasyPrint | Vercel 不支援，僅能 HTML 預覽 |
| 字體 | 需安裝 Noto Sans TC 才能正確顯示繁體中文 |
| 浮水印 | 授權失效浮水印尚未實作 |

### 7.2 建議未來改進

1. **簽章功能** - 整合電子簽章 (E-Signature)
2. **浮水印** - 授權過期自動加浮水印
3. **批次匯出** - 支援多案例批次 PDF 匯出
4. **列印佇列** - RPi5 直接列印支援

---

## 8. 測試驗證

### 8.1 已通過測試

| 測試項目 | 結果 |
|----------|------|
| HTML 預覽 (Vercel) | ✅ 通過 |
| HTML 預覽 (本地) | ✅ 通過 |
| PDF 下載 (本地) | ✅ 通過 |
| 示範資料渲染 | ✅ 通過 |
| 真實資料渲染 | ✅ 通過 |
| 自動分頁 (>24 vitals) | ✅ 通過 |
| SVG 圖表對齊 | ✅ 通過 |
| 日期篩選 (本地時區) | ✅ 通過 |

### 8.2 測試 URL

```bash
# 本地預覽
http://localhost:8000/api/anesthesia/cases/ANES-DEMO-001/pdf?preview=true

# 本地下載
http://localhost:8000/api/anesthesia/cases/ANES-DEMO-001/pdf

# Vercel 預覽
https://mirs-v2.vercel.app/api/anesthesia/cases/ANES-DEMO-001/pdf?preview=true
```

---

## 9. 結論

MIRS 麻醉模組 PDF 輸出功能已完成開發，實現：

- **Event Sourcing 架構** - 從事件重建狀態，確保資料一致性
- **多環境適配** - Vercel (HTML) / 本地 (PDF) 雙模式支援
- **M0073 格式** - 符合烏日林新醫院麻醉紀錄單規範
- **自動分頁** - 長手術案例自動多頁輸出
- **SVG 圖表** - 資料點與表格欄位精確對齊

下一步建議：整合電子簽章功能，完成麻醉紀錄的完整數位化流程。

---

*報告產生時間: 2026-01-24*
*MIRS Anesthesia Module v2.2*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
