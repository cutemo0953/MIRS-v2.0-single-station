-- ============================================================================
-- MIRS Equipment Check History Migration
-- Version: 1.2.8
-- Purpose: Track equipment check history for audit and reporting
-- ============================================================================

-- ============================================================================
-- 1. Create equipment_check_history table
-- ============================================================================

CREATE TABLE IF NOT EXISTS equipment_check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,           -- FK to equipment.id or equipment_units
    unit_label TEXT,                      -- 個別單位標籤 (nullable for AGGREGATE mode)
    check_date DATE NOT NULL,             -- 檢查日期
    check_time TIMESTAMP NOT NULL,        -- 檢查時間
    checked_by TEXT,                      -- 檢查人員
    level_before INTEGER,                 -- 檢查前百分比
    level_after INTEGER,                  -- 檢查後百分比
    status_before TEXT,                   -- 檢查前狀態
    status_after TEXT,                    -- 檢查後狀態
    remarks TEXT,                         -- 備註
    station_id TEXT,                      -- 站點 ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_check_history_date
ON equipment_check_history(check_date);

CREATE INDEX IF NOT EXISTS idx_check_history_equipment
ON equipment_check_history(equipment_id);

-- ============================================================================
-- 2. Create daily check summary view
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_daily_check_summary AS
SELECT
    check_date,
    station_id,
    COUNT(DISTINCT equipment_id) as equipment_checked,
    COUNT(*) as total_checks,
    COUNT(DISTINCT unit_label) as units_checked,
    GROUP_CONCAT(DISTINCT checked_by) as checkers,
    MIN(check_time) as first_check,
    MAX(check_time) as last_check
FROM equipment_check_history
GROUP BY check_date, station_id;

-- ============================================================================
-- Migration complete
-- ============================================================================
