-- ============================================================================
-- Migration: Surgery Codes & Self-Pay Items Module
-- Version: 1.0.0
-- Date: 2026-01-02
-- Description: 手術代碼與自費品項管理模組 - 含 FTS5 全文搜尋
-- ============================================================================

-- 1. Provenance: 主檔匯入記錄
CREATE TABLE IF NOT EXISTS master_data_imports (
    pack_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    effective_date TEXT,
    applied_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    actor_id TEXT,
    seed INTEGER DEFAULT 0,
    notes TEXT
);

-- 2. 手術分類對照表 (20 筆)
CREATE TABLE IF NOT EXISTS surgery_categories (
    category_code TEXT PRIMARY KEY,
    category_name TEXT NOT NULL,
    code_range TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. 術式主檔 (256 筆)
CREATE TABLE IF NOT EXISTS surgery_codes (
    code TEXT PRIMARY KEY,
    name_zh TEXT NOT NULL,
    name_en TEXT,
    category_code TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
    keywords TEXT,
    is_common INTEGER DEFAULT 0 CHECK (is_common IN (0, 1)),
    is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_code) REFERENCES surgery_categories(category_code)
);

-- 4. 術式 FTS5 全文搜尋索引
CREATE VIRTUAL TABLE IF NOT EXISTS surgery_codes_fts USING fts5(
    code,
    name_zh,
    name_en,
    keywords,
    content='surgery_codes',
    content_rowid='rowid'
);

-- FTS5 同步觸發器 - INSERT
CREATE TRIGGER IF NOT EXISTS surgery_codes_fts_ai AFTER INSERT ON surgery_codes BEGIN
    INSERT INTO surgery_codes_fts(rowid, code, name_zh, name_en, keywords)
    VALUES (NEW.rowid, NEW.code, NEW.name_zh, NEW.name_en, NEW.keywords);
END;

-- FTS5 同步觸發器 - DELETE
CREATE TRIGGER IF NOT EXISTS surgery_codes_fts_ad AFTER DELETE ON surgery_codes BEGIN
    INSERT INTO surgery_codes_fts(surgery_codes_fts, rowid, code, name_zh, name_en, keywords)
    VALUES ('delete', OLD.rowid, OLD.code, OLD.name_zh, OLD.name_en, OLD.keywords);
END;

-- FTS5 同步觸發器 - UPDATE
CREATE TRIGGER IF NOT EXISTS surgery_codes_fts_au AFTER UPDATE ON surgery_codes BEGIN
    INSERT INTO surgery_codes_fts(surgery_codes_fts, rowid, code, name_zh, name_en, keywords)
    VALUES ('delete', OLD.rowid, OLD.code, OLD.name_zh, OLD.name_en, OLD.keywords);
    INSERT INTO surgery_codes_fts(rowid, code, name_zh, name_en, keywords)
    VALUES (NEW.rowid, NEW.code, NEW.name_zh, NEW.name_en, NEW.keywords);
END;

-- 5. 自費項目主檔 (167 筆)
CREATE TABLE IF NOT EXISTS selfpay_items (
    item_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price REAL NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    unit TEXT DEFAULT '組',
    is_common INTEGER DEFAULT 0 CHECK (is_common IN (0, 1)),
    display_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. 自費項目 FTS5 全文搜尋索引
CREATE VIRTUAL TABLE IF NOT EXISTS selfpay_items_fts USING fts5(
    item_id,
    name,
    category,
    notes,
    content='selfpay_items',
    content_rowid='rowid'
);

-- FTS5 同步觸發器 - INSERT
CREATE TRIGGER IF NOT EXISTS selfpay_items_fts_ai AFTER INSERT ON selfpay_items BEGIN
    INSERT INTO selfpay_items_fts(rowid, item_id, name, category, notes)
    VALUES (NEW.rowid, NEW.item_id, NEW.name, NEW.category, NEW.notes);
END;

-- FTS5 同步觸發器 - DELETE
CREATE TRIGGER IF NOT EXISTS selfpay_items_fts_ad AFTER DELETE ON selfpay_items BEGIN
    INSERT INTO selfpay_items_fts(selfpay_items_fts, rowid, item_id, name, category, notes)
    VALUES ('delete', OLD.rowid, OLD.item_id, OLD.name, OLD.category, OLD.notes);
END;

-- FTS5 同步觸發器 - UPDATE
CREATE TRIGGER IF NOT EXISTS selfpay_items_fts_au AFTER UPDATE ON selfpay_items BEGIN
    INSERT INTO selfpay_items_fts(selfpay_items_fts, rowid, item_id, name, category, notes)
    VALUES ('delete', OLD.rowid, OLD.item_id, OLD.name, OLD.category, OLD.notes);
    INSERT INTO selfpay_items_fts(rowid, item_id, name, category, notes)
    VALUES (NEW.rowid, NEW.item_id, NEW.name, NEW.category, NEW.notes);
END;

-- 7. 索引優化
CREATE INDEX IF NOT EXISTS idx_surgery_codes_category ON surgery_codes(category_code);
CREATE INDEX IF NOT EXISTS idx_surgery_codes_common ON surgery_codes(is_common) WHERE is_common = 1;
CREATE INDEX IF NOT EXISTS idx_surgery_codes_active ON surgery_codes(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_surgery_codes_points ON surgery_codes(points DESC);

CREATE INDEX IF NOT EXISTS idx_selfpay_items_category ON selfpay_items(category);
CREATE INDEX IF NOT EXISTS idx_selfpay_items_common ON selfpay_items(is_common) WHERE is_common = 1;
CREATE INDEX IF NOT EXISTS idx_selfpay_items_order ON selfpay_items(category, display_order);
CREATE INDEX IF NOT EXISTS idx_selfpay_items_price ON selfpay_items(unit_price DESC);

-- 8. 更新時間戳觸發器
CREATE TRIGGER IF NOT EXISTS surgery_codes_updated_at AFTER UPDATE ON surgery_codes
BEGIN
    UPDATE surgery_codes SET updated_at = CURRENT_TIMESTAMP WHERE rowid = NEW.rowid;
END;

CREATE TRIGGER IF NOT EXISTS selfpay_items_updated_at AFTER UPDATE ON selfpay_items
BEGIN
    UPDATE selfpay_items SET updated_at = CURRENT_TIMESTAMP WHERE rowid = NEW.rowid;
END;

CREATE TRIGGER IF NOT EXISTS surgery_categories_updated_at AFTER UPDATE ON surgery_categories
BEGIN
    UPDATE surgery_categories SET updated_at = CURRENT_TIMESTAMP WHERE rowid = NEW.rowid;
END;

-- 9. 記錄 migration (如果 schema_migrations 存在)
-- INSERT OR IGNORE INTO schema_migrations (migration_name, description) VALUES
-- ('add_surgery_codes_selfpay_v1', 'Add surgery_codes, selfpay_items tables with FTS5 search');
