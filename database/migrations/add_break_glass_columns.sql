-- ============================================================================
-- Migration: Break-Glass 緊急授權欄位
-- Version: 1.2.1
-- Date: 2026-01-20
-- Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md Section 4.3
-- ============================================================================

-- ============================================================================
-- 1. controlled_drug_log 表擴充 - Break-glass 欄位
-- ============================================================================

-- Break-glass 標記
ALTER TABLE controlled_drug_log ADD COLUMN is_break_glass INTEGER DEFAULT 0;

-- Break-glass 原因 (MTP_ACTIVATED, CARDIAC_ARREST, etc.)
ALTER TABLE controlled_drug_log ADD COLUMN break_glass_reason TEXT;

-- 事後補核准人
ALTER TABLE controlled_drug_log ADD COLUMN break_glass_approved_by TEXT;

-- 補核准時間
ALTER TABLE controlled_drug_log ADD COLUMN break_glass_approved_at DATETIME;

-- 24hr 截止時間
ALTER TABLE controlled_drug_log ADD COLUMN break_glass_deadline DATETIME;

-- 見證人狀態 (REQUIRED, COMPLETED, PENDING, WAIVED)
-- REQUIRED = 需要見證人
-- COMPLETED = 已完成見證
-- PENDING = 待補見證 (break-glass)
-- WAIVED = 免除 (三四級管制)
ALTER TABLE controlled_drug_log ADD COLUMN witness_status TEXT DEFAULT 'REQUIRED';

-- ============================================================================
-- 2. 建立索引
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_ctrl_drug_break_glass
    ON controlled_drug_log(is_break_glass);

CREATE INDEX IF NOT EXISTS idx_ctrl_drug_witness_status
    ON controlled_drug_log(witness_status);

CREATE INDEX IF NOT EXISTS idx_ctrl_drug_break_glass_pending
    ON controlled_drug_log(is_break_glass, witness_status, break_glass_approved_by);

-- ============================================================================
-- 3. 建立稽核日誌表 (如果不存在)
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id TEXT,
    actor_id TEXT NOT NULL,
    details TEXT,  -- JSON
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(table_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log(created_at);

-- ============================================================================
-- 4. 更新 controlled_drug_log Trigger (Break-glass deadline)
-- ============================================================================

-- Trigger: Break-glass 記錄自動設定 24hr deadline
CREATE TRIGGER IF NOT EXISTS set_break_glass_deadline
AFTER INSERT ON controlled_drug_log
WHEN NEW.is_break_glass = 1
BEGIN
    UPDATE controlled_drug_log
    SET break_glass_deadline = datetime(NEW.created_at, '+24 hours')
    WHERE id = NEW.id;
END;

-- ============================================================================
-- 5. 更新 schema version
-- ============================================================================

UPDATE station_metadata SET schema_version = '1.7.1' WHERE station_code IS NOT NULL;

-- ============================================================================
-- 完成
-- ============================================================================
