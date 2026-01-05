# Dev Spec: 手術代碼與自費品項管理模組

**MIRS v2.9.1 - 處置代碼資料庫與自費品項建碼系統**

> **實作狀態**: Phase 1-3 已完成 (v2.7.0 ~ v2.9.1)

## 1. 背景與需求分析

### 1.1 現況

目前 MIRS 與 CIRS 系統在「處置/手術代碼」與「自費品項」方面缺乏完整的主檔管理：

| 系統 | 現況 | 問題 |
|------|------|------|
| MIRS | 無處置代碼主檔 | 無法記錄手術健保點數 |
| CIRS (CashDesk) | 有 billing 模組，但缺乏品項主檔 | 無法快速輸入代碼 |
| OrthoAssist | CSV 主檔已建立 | 需整合至系統 |

### 1.2 目標

1. **建立處置代碼資料庫**：支援健保手術代碼快速搜尋
2. **整合自費品項主檔**：讓 CashDesk 可快速建立收費項目
3. **支援健保點數計算**：自動計算多術式遞減規則
4. **高效能搜尋**：大量代碼下仍能快速回應（<100ms）

### 1.3 資料來源

```
/Users/QmoMBA/Downloads/OrthoAssistance/
├── 01_術式主檔_Surgeries.csv         # 256 筆健保手術碼
├── 02_自費項目主檔_SelfPayItems.csv  # 167 筆自費品項
└── 03_手術分類對照表_SurgeryCategories.csv  # 20 個分類
```

---

## 2. 系統架構

### 2.1 資料庫設計原則

為確保**不影響網頁效率**，採用以下策略：

```
┌─────────────────────────────────────────────────────────┐
│                    查詢效率優化                          │
├─────────────────────────────────────────────────────────┤
│ 1. FTS5 全文搜尋 - SQLite 原生支援，毫秒級回應           │
│ 2. 預計算索引 - 常用查詢建立複合索引                     │
│ 3. 分層載入 - 熱門項目優先載入，完整資料延遲載入          │
│ 4. 客戶端快取 - LocalStorage 快取常用項目               │
└─────────────────────────────────────────────────────────┘
```

### 2.2 資料庫 Schema

```sql
-- =============================================================================
-- 健保處置代碼主檔
-- =============================================================================
CREATE TABLE nhi_procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 代碼與名稱
    code TEXT UNIQUE NOT NULL,           -- '64028C'
    name_zh TEXT NOT NULL,               -- '股骨幹骨折開放性復位術'
    name_en TEXT,                        -- 'ORIF of femoral shaft fracture'

    -- 分類
    category_code TEXT NOT NULL,         -- '3' (筋骨)
    category_name TEXT,                  -- '筋骨'
    subcategory TEXT,                    -- '骨折復位'

    -- 點數
    points INTEGER NOT NULL,             -- 11000

    -- 搜尋輔助
    keywords TEXT,                       -- '股骨,骨折,ORIF' (逗號分隔)
    pinyin TEXT,                         -- 'guganguzhekaifangfuweishu' (拼音)

    -- 使用頻率（僅標記，不動態計數）
    is_common BOOLEAN DEFAULT FALSE,     -- 常用標記（由管理者手動設定）
    -- 註：use_count/last_used 已移除，改由 ops log 統計

    -- 狀態
    is_active BOOLEAN DEFAULT TRUE,
    valid_from DATE,                     -- 健保生效日
    valid_to DATE,                       -- 健保失效日

    -- 備註
    notes TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 全文搜尋索引
CREATE VIRTUAL TABLE nhi_procedures_fts USING fts5(
    code,
    name_zh,
    name_en,
    keywords,
    content='nhi_procedures',
    content_rowid='id'
);

-- 觸發器：同步 FTS 索引
CREATE TRIGGER nhi_procedures_ai AFTER INSERT ON nhi_procedures BEGIN
    INSERT INTO nhi_procedures_fts(rowid, code, name_zh, name_en, keywords)
    VALUES (new.id, new.code, new.name_zh, new.name_en, new.keywords);
END;

CREATE TRIGGER nhi_procedures_ad AFTER DELETE ON nhi_procedures BEGIN
    INSERT INTO nhi_procedures_fts(nhi_procedures_fts, rowid, code, name_zh, name_en, keywords)
    VALUES ('delete', old.id, old.code, old.name_zh, old.name_en, old.keywords);
END;

CREATE TRIGGER nhi_procedures_au AFTER UPDATE ON nhi_procedures BEGIN
    INSERT INTO nhi_procedures_fts(nhi_procedures_fts, rowid, code, name_zh, name_en, keywords)
    VALUES ('delete', old.id, old.code, old.name_zh, old.name_en, old.keywords);
    INSERT INTO nhi_procedures_fts(rowid, code, name_zh, name_en, keywords)
    VALUES (new.id, new.code, new.name_zh, new.name_en, new.keywords);
END;

-- =============================================================================
-- 健保分類對照表
-- =============================================================================
CREATE TABLE nhi_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,           -- '3', '16', 'RD'
    name TEXT NOT NULL,                  -- '筋骨', '神經外科', '放射線診療'
    code_range TEXT,                     -- '64001-64283'
    sort_order INTEGER,
    notes TEXT
);

-- =============================================================================
-- 自費品項主檔
-- =============================================================================
CREATE TABLE selfpay_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 品項代碼與名稱
    item_code TEXT UNIQUE NOT NULL,      -- 'WD10157-1'
    name TEXT NOT NULL,                  -- '"史耐輝"縫合錨釘'

    -- 分類
    category TEXT NOT NULL,              -- '5-縫合錨釘'
    category_code TEXT,                  -- '5'
    subcategory TEXT,

    -- 定價
    unit_price INTEGER NOT NULL,         -- 40600
    unit TEXT DEFAULT '組',              -- '組', '支', 'cc'

    -- 關聯
    related_procedures TEXT,             -- JSON: ['64219B', '64121B'] 相關手術碼
    vendor_id TEXT,                      -- 供應商代碼
    vendor_name TEXT,

    -- 庫存連動
    inventory_sku TEXT,                  -- 連動 MIRS 庫存 SKU
    min_stock INTEGER,                   -- 最低庫存警示

    -- 使用頻率（僅標記，不動態計數）
    is_common BOOLEAN DEFAULT FALSE,     -- 常用標記（由管理者手動設定）
    -- 註：use_count/last_used 已移除，改由 ops log 統計

    -- 狀態
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER,

    -- 備註
    notes TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 自費品項 FTS 搜尋
CREATE VIRTUAL TABLE selfpay_items_fts USING fts5(
    item_code,
    name,
    category,
    content='selfpay_items',
    content_rowid='id'
);

-- 觸發器（同上）...

-- =============================================================================
-- 手術案例處置記錄
-- =============================================================================
CREATE TABLE surgery_procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,               -- 關聯手術案例

    -- 處置資訊
    -- 註：「最多3筆」為 UI 限制，Schema 不設硬性限制以保留彈性
    procedure_order INTEGER NOT NULL,    -- 順序（第4筆以後給付0%）
    procedure_code TEXT NOT NULL,        -- 健保代碼
    procedure_name TEXT,                 -- 處置名稱

    -- 點數計算
    base_points INTEGER NOT NULL,        -- 原始點數
    discount_rate REAL DEFAULT 1.0,      -- 遞減比例 (1.0, 0.5, 0)
    adjusted_points INTEGER,             -- 調整後點數

    -- 分類（用於同類/不同類判斷）
    category_code TEXT,

    -- 簽核
    recorded_by TEXT,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id)
);

-- =============================================================================
-- 手術案例自費項目記錄
-- =============================================================================
CREATE TABLE surgery_selfpay_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,

    -- 品項
    item_code TEXT NOT NULL,
    item_name TEXT,
    unit_price INTEGER,
    quantity INTEGER DEFAULT 1,
    subtotal INTEGER,                    -- unit_price * quantity

    -- 稅務（v1.1 修正：使用 tax_type 取代 is_taxable）
    tax_type TEXT DEFAULT 'TAXABLE',     -- 'TAXABLE' | 'EXEMPT' | 'ZERO_RATED'
    tax_rate REAL DEFAULT 0.05,          -- 5% VAT（當 tax_type='TAXABLE'）
    tax_amount INTEGER,                  -- 應以整數運算計算，避免浮點誤差

    -- 狀態
    status TEXT DEFAULT 'PENDING',       -- 'PENDING', 'BILLED', 'PAID', 'WAIVED'

    recorded_by TEXT,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (case_id) REFERENCES surgery_cases(id)
);

-- =============================================================================
-- 索引優化
-- =============================================================================

-- 處置代碼查詢
CREATE INDEX idx_nhi_procedures_category ON nhi_procedures(category_code);
CREATE INDEX idx_nhi_procedures_common ON nhi_procedures(is_common DESC);
CREATE INDEX idx_nhi_procedures_points ON nhi_procedures(points DESC);

-- 自費品項查詢
CREATE INDEX idx_selfpay_category ON selfpay_items(category_code, display_order);
CREATE INDEX idx_selfpay_common ON selfpay_items(is_common DESC);
CREATE INDEX idx_selfpay_price ON selfpay_items(unit_price);

-- 案例查詢
CREATE INDEX idx_surgery_procedures_case ON surgery_procedures(case_id, procedure_order);
CREATE INDEX idx_surgery_selfpay_case ON surgery_selfpay_items(case_id, status);
```

---

## 3. 健保點數計算邏輯

### 3.1 遞減規則

依「全民健康保險醫療服務給付項目及支付標準」第二部第二章第七節通則第六條：

```python
def calculate_nhi_points(procedures: List[dict]) -> List[dict]:
    """
    計算健保給付點數

    規則：
    - 術式需按點數由高到低排列
    - 同類手術：100% → 50% → 50% → 0%
    - 不同類手術：100% → 100% → 50% → 0%
    """

    # 1. 依點數排序（降序）
    sorted_procs = sorted(procedures, key=lambda x: x['points'], reverse=True)

    # 2. 分組：判斷同類/不同類
    categories_seen = set()
    results = []

    for i, proc in enumerate(sorted_procs):
        cat = proc['category_code']

        if i == 0:
            # 第一項：100%
            rate = 1.0
        elif cat in categories_seen:
            # 同類
            if i == 1 or i == 2:
                rate = 0.5
            else:
                rate = 0.0
        else:
            # 不同類
            if i == 1:
                rate = 1.0
            elif i == 2:
                rate = 0.5
            else:
                rate = 0.0

        categories_seen.add(cat)

        results.append({
            **proc,
            'order': i + 1,
            'discount_rate': rate,
            'adjusted_points': int(proc['points'] * rate)
        })

    return results
```

### 3.2 API 計算範例

```json
// POST /api/billing/procedures/calculate
{
  "procedures": ["64028C", "64031C", "64160B"]
}

// Response
{
  "procedures": [
    {
      "code": "64160B",
      "name": "脊椎骨折開放性復位術",
      "category_code": "3",
      "base_points": 13190,
      "order": 1,
      "discount_rate": 1.0,
      "adjusted_points": 13190
    },
    {
      "code": "64028C",
      "name": "股骨幹骨折開放性復位術",
      "category_code": "3",
      "base_points": 11000,
      "order": 2,
      "discount_rate": 0.5,
      "adjusted_points": 5500
    },
    {
      "code": "64031C",
      "name": "脛骨骨折開放性復位術",
      "category_code": "3",
      "base_points": 10000,
      "order": 3,
      "discount_rate": 0.5,
      "adjusted_points": 5000
    }
  ],
  "total_base_points": 34190,
  "total_adjusted_points": 23690,
  "discount_summary": "同類手術遞減：-10500 點"
}
```

---

## 4. API 設計

### 4.0 實際 API 端點 (v2.9.1 實作)

> **重要**: 以下為實際實作的端點，位於 `routes/surgery_codes.py`

```
# 術式代碼
GET  /api/surgery-codes/categories       # 分類列表
GET  /api/surgery-codes/codes            # 列表（分頁，不支援搜尋）
GET  /api/surgery-codes/codes/search?q=  # FTS5 全文搜尋 ← 搜尋必須用此端點
GET  /api/surgery-codes/codes/{code}     # 單筆詳情
POST /api/surgery-codes/codes            # 新增
PUT  /api/surgery-codes/codes/{code}     # 更新
DELETE /api/surgery-codes/codes/{code}   # 刪除

# 自費項目
GET  /api/surgery-codes/selfpay          # 列表
GET  /api/surgery-codes/selfpay/search?q=# FTS5 全文搜尋
GET  /api/surgery-codes/selfpay/{id}     # 單筆詳情
POST /api/surgery-codes/selfpay          # 新增
PUT  /api/surgery-codes/selfpay/{id}     # 更新
DELETE /api/surgery-codes/selfpay/{id}   # 刪除

# 點數計算
POST /api/surgery-codes/calculate-points # 計算遞減點數
```

#### 搜尋端點注意事項

| 端點 | 用途 | 支援 `q` 參數 |
|------|------|---------------|
| `/codes` | 分頁列表 | **否** |
| `/codes/search` | FTS5 搜尋 | **是** |
| `/selfpay` | 分頁列表 | **否** |
| `/selfpay/search` | FTS5 搜尋 | **是** |

**前端呼叫邏輯** (v2.9.1 修正):
```javascript
async loadSurgeryCodes() {
    let url;
    if (this.surgeryCodeSearchText?.trim()) {
        // 有搜尋文字 → FTS5 搜尋端點
        url = `/api/surgery-codes/codes/search?q=${encodeURIComponent(this.surgeryCodeSearchText)}`;
    } else {
        // 無搜尋文字 → 分頁列表端點
        url = `/api/surgery-codes/codes?page=${this.page}&page_size=${this.pageSize}`;
    }
    // ...
}
```

---

### 4.1 處置代碼 API (原始設計，供參考)

```
# 搜尋（核心功能）
GET  /api/procedures/search?q={query}&limit=20
     # query 支援：代碼、中文、英文、關鍵字
     # 回傳：依相關性 + 使用頻率排序

# CRUD
GET  /api/procedures                    # 列表（分頁）
GET  /api/procedures/{code}             # 單筆詳情
POST /api/procedures                    # 新增（管理者）
PUT  /api/procedures/{code}             # 更新
DELETE /api/procedures/{code}           # 停用

# 常用
GET  /api/procedures/common             # 常用清單（前20筆）
POST /api/procedures/{code}/use         # 記錄使用（更新 use_count）

# 計算
POST /api/procedures/calculate          # 計算遞減點數

# 批次匯入
POST /api/procedures/import             # CSV 匯入
GET  /api/procedures/export             # CSV 匯出
```

### 4.2 自費品項 API

```
# 搜尋
GET  /api/selfpay/search?q={query}&category={cat}

# CRUD
GET  /api/selfpay                       # 列表
GET  /api/selfpay/{item_code}           # 詳情
POST /api/selfpay                       # 新增
PUT  /api/selfpay/{item_code}           # 更新
DELETE /api/selfpay/{item_code}         # 停用

# 分類
GET  /api/selfpay/categories            # 分類清單

# 常用
GET  /api/selfpay/common                # 常用品項

# 批次
POST /api/selfpay/import                # CSV 匯入
GET  /api/selfpay/export                # CSV 匯出
```

### 4.3 案例記錄 API

```
# 處置記錄
POST /api/cases/{case_id}/procedures        # 新增處置
GET  /api/cases/{case_id}/procedures        # 取得處置
PUT  /api/cases/{case_id}/procedures        # 更新處置
DELETE /api/cases/{case_id}/procedures/{id} # 刪除

# 自費記錄
POST /api/cases/{case_id}/selfpay           # 新增自費
GET  /api/cases/{case_id}/selfpay           # 取得自費
PUT  /api/cases/{case_id}/selfpay/{id}      # 更新
DELETE /api/cases/{case_id}/selfpay/{id}    # 刪除

# 帳單摘要
GET  /api/cases/{case_id}/billing-summary   # 帳單總覽
POST /api/cases/{case_id}/finalize          # 確認帳單
```

---

## 5. PWA 設計

### 5.1 整合方式

建議以「功能模組」方式整合至現有 PWA，而非獨立 PWA：

| 整合位置 | 功能 | 說明 |
|----------|------|------|
| **MIRS /admin** | 主檔管理 | 處置碼/自費品項 CRUD |
| **MIRS /station** | 手術處置登錄 | 術中記錄處置代碼 |
| **CIRS /cashdesk** | 收費建單 | 自費品項選取 + 計價 |
| **CIRS /doctor** | 醫師站 | 處置代碼快速輸入 |

### 5.2 UI 設計：處置代碼搜尋

```
┌─────────────────────────────────────────────────────────┐
│ 🔍 輸入代碼或關鍵字搜尋                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ ORIF 股骨                                     [🎤]  │ │
│ └─────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│ ⭐ 常用                                                  │
│ ┌─────────────┬─────────────┬─────────────┐             │
│ │ 64028C      │ 64031C      │ 64160B      │             │
│ │ 股骨幹ORIF  │ 脛骨ORIF    │ 脊椎ORIF    │             │
│ │ 11,000點    │ 10,000點    │ 13,190點    │             │
│ └─────────────┴─────────────┴─────────────┘             │
├─────────────────────────────────────────────────────────┤
│ 搜尋結果 (3)                                             │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 64028C │ 股骨幹骨折開放性復位術         │ 11,000點  │ │
│ ├─────────────────────────────────────────────────────┤ │
│ │ 64029B │ 股骨頸骨折開放性復位術         │ 12,000點  │ │
│ ├─────────────────────────────────────────────────────┤ │
│ │ 64030B │ 股骨頸骨折開放性復位術(帶血管) │ 14,000點  │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 5.3 UI 設計：自費品項購物車

```
┌─────────────────────────────────────────────────────────┐
│ 🛒 自費項目清單                              病歷#12345 │
├─────────────────────────────────────────────────────────┤
│ 分類：[全部▼] [關節鏡] [止血] [骨移植] [縫合] [骨板]    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ ☐ WD10157-1 "史耐輝"縫合錨釘                 $40,600 x1 │
│ ☑ D10241-1  邦美傑格 迷你縫合錨釘            $35,000 x2 │
│ ☑ A21867-1  Surgiflo止血基質組               $37,500 x1 │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                        小計：$107,500                   │
│                        稅額：$5,375                     │
│                        ─────────────                    │
│                        總計：$112,875                   │
├─────────────────────────────────────────────────────────┤
│           [清空] [儲存草稿] [確認送出]                   │
└─────────────────────────────────────────────────────────┘
```

---

## 6. 資料匯入

### 6.1 初始資料載入

```python
import csv

def load_procedures_from_csv(csv_path: str, db):
    """從 CSV 載入處置代碼"""
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.execute("""
                INSERT OR REPLACE INTO nhi_procedures
                (code, name_zh, name_en, category_code, category_name,
                 points, keywords, is_common)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['code'],
                row['name_zh'],
                row.get('name_en', ''),
                row['category_code'],
                row['category'],
                int(row['points']),
                row.get('keywords', ''),
                row.get('is_common', 'FALSE').upper() == 'TRUE'
            ))


def load_selfpay_from_csv(csv_path: str, db):
    """從 CSV 載入自費品項"""
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.execute("""
                INSERT OR REPLACE INTO selfpay_items
                (item_code, name, category, unit_price, unit,
                 is_common, display_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row['item_id'],
                row['name'],
                row['category'],
                int(row['unit_price']),
                row.get('unit', '組'),
                row.get('is_common', 'FALSE').upper() == 'TRUE',
                int(row.get('display_order', 0))
            ))
```

### 6.2 資料維護策略

```
┌─────────────────────────────────────────────────────────┐
│ 資料更新流程                                             │
├─────────────────────────────────────────────────────────┤
│ 1. 健保署公告更新 → 下載新版支付標準                     │
│ 2. Admin 介面 → 批次匯入 CSV                            │
│ 3. 系統比對差異 → 顯示新增/修改/停用項目                │
│ 4. 管理者確認 → 套用更新                                │
│ 5. 舊代碼自動標記停用，保留歷史記錄                      │
└─────────────────────────────────────────────────────────┘
```

---

## 7. 效能優化

### 7.1 搜尋效能

```python
async def search_procedures(query: str, limit: int = 20) -> List[dict]:
    """
    高效搜尋處置代碼
    目標：<100ms 回應時間
    """

    # 1. 優先：完全匹配代碼
    if query.upper().startswith(('6', '3', '8')):  # 常見代碼開頭
        exact = await db.fetch_one(
            "SELECT * FROM nhi_procedures WHERE code = ?",
            (query.upper(),)
        )
        if exact:
            return [exact]

    # 2. FTS5 全文搜尋
    results = await db.fetch_all("""
        SELECT p.*,
               bm25(nhi_procedures_fts) as relevance
        FROM nhi_procedures p
        JOIN nhi_procedures_fts fts ON p.id = fts.rowid
        WHERE nhi_procedures_fts MATCH ?
        ORDER BY
            p.is_common DESC,
            relevance
        LIMIT ?
    """, (f'"{query}"*', limit))

    return results
```

### 7.2 客戶端快取

```javascript
// LocalStorage 快取常用項目
const CACHE_KEY = 'mirs_procedures_cache';
const CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours

async function getCommonProcedures() {
    const cached = localStorage.getItem(CACHE_KEY);
    if (cached) {
        const { data, timestamp } = JSON.parse(cached);
        if (Date.now() - timestamp < CACHE_TTL) {
            return data;
        }
    }

    const response = await fetch('/api/procedures/common');
    const data = await response.json();

    localStorage.setItem(CACHE_KEY, JSON.stringify({
        data,
        timestamp: Date.now()
    }));

    return data;
}
```

---

## 8. 與 CashDesk 整合

### 8.1 整合點

```
CIRS CashDesk                           MIRS 主檔
┌──────────────┐                    ┌──────────────┐
│ 新增帳單     │ ───────────────▶  │ selfpay_items│
│ 選擇品項     │ ◀───────────────  │ (搜尋 API)   │
├──────────────┤                    ├──────────────┤
│ 處置代碼     │ ───────────────▶  │ nhi_procedures
│ 計算點數     │ ◀───────────────  │ (計算 API)   │
├──────────────┤                    └──────────────┘
│ 生成帳單     │
│ 收款確認     │
└──────────────┘
```

### 8.2 跨系統 API 呼叫

如果 CIRS 與 MIRS 是獨立部署：

```python
# CIRS 呼叫 MIRS API
import httpx

class MIRSClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def search_selfpay(self, query: str):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/selfpay/search",
                params={"q": query}
            )
            return resp.json()

    async def calculate_nhi_points(self, codes: List[str]):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/api/procedures/calculate",
                json={"procedures": codes}
            )
            return resp.json()
```

如果同一部署（建議）：

```python
# 共享資料庫，直接 import
from mirs.services.procedure_service import ProcedureService
from mirs.services.selfpay_service import SelfpayService
```

---

## 9. 實作順序

### Phase 1: 資料庫與基礎 API (Week 1)

1. Schema 建立（含 FTS5）
2. CSV 匯入腳本
3. 基本 CRUD API
4. 搜尋 API（含效能測試）

### Phase 2: 點數計算 (Week 2)

1. 遞減規則實作
2. 計算 API
3. 單元測試

### Phase 3: UI 整合 (Week 3)

1. MIRS Admin 主檔管理介面
2. 處置代碼搜尋元件
3. 自費品項購物車元件

### Phase 4: CashDesk 整合 (Week 4)

1. CIRS CashDesk 整合
2. 帳單生成流程
3. 報表功能

---

## 10. 開放問題

1. **MIRS 與 CIRS 是否共用資料庫？**
   - 建議：共用 `procedures` 與 `selfpay` 主檔
   - 交易資料各自存放

2. **是否需要多院區支援？**
   - 目前設計為單院區
   - 多院區需增加 `hospital_id` 欄位

3. **健保支付標準更新頻率？**
   - 約每季更新
   - 建議保留版本歷史

4. **語音輸入支援？**
   - Web Speech API 可做，但辨識率需測試
   - 列為 v2.0 規劃

---

## 附錄 A: 資料範例

### 處置代碼 CSV 格式

```csv
code,name_zh,name_en,category,category_code,points,keywords,is_common
64028C,股骨幹骨折開放性復位術,ORIF of femoral shaft,筋骨,3,11000,"股骨,骨折,ORIF",TRUE
64031C,脛骨骨折開放性復位術,ORIF of tibia,筋骨,3,10000,"脛骨,骨折,ORIF",TRUE
```

### 自費品項 CSV 格式

```csv
item_id,name,category,unit_price,unit,is_common,display_order
WD10157-1,"史耐輝"縫合錨釘,5-縫合錨釘,40600,組,TRUE,89
D10241-1,邦美傑格 迷你縫合錨釘,5-縫合錨釘,35000,組,TRUE,93
```

---

**De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司**

*文件版本: v2.9.1*
*更新日期: 2026-01-05*

### 修訂紀錄
| 版本 | 日期 | 變更 |
|------|------|------|
| 2.9.1 | 2026-01-05 | 新增 4.0 實際 API 端點文件；修正搜尋端點說明 (`/codes` vs `/codes/search`) |
| 2.8.0 | 2026-01-03 | 整合健保第七節手術碼 1,681 筆；新增 NHI 合併腳本 |
| 2.7.0 | 2026-01-02 | Phase 1-3 實作完成；FTS5 搜尋；點數遞減計算器 |
| 1.1 | 2026-01-02 | 移除 use_count/last_used (改由 ops log 統計)；is_taxable → tax_type；「3筆」限制移至 UI 層 |
| 1.0 | 2025-12-29 | 初版 |
