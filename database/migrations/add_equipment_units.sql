-- ============================================================================
-- MIRS Equipment Units Tracking Migration
-- Version: 1.2.6
-- Purpose: Support per-unit tracking for consumable equipment (oxygen cylinders, etc.)
-- ============================================================================

-- ============================================================================
-- 1. Create equipment_units table for individual tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS equipment_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,           -- FK to equipment.id (e.g., 'RESP-001')
    unit_serial TEXT,                     -- 序號 (e.g., 'CYL-001', 'CYL-002')
    unit_label TEXT,                      -- 標籤 (e.g., '1號瓶', '2號瓶')
    level_percent INTEGER DEFAULT 100,    -- 充填/電量百分比 (0-100)
    status TEXT DEFAULT 'AVAILABLE',      -- AVAILABLE, IN_USE, EMPTY, MAINTENANCE
    last_check TIMESTAMP,
    checked_by TEXT,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);

CREATE INDEX IF NOT EXISTS idx_equipment_units_eq_id
ON equipment_units(equipment_id);

-- ============================================================================
-- 2. Seed example data for existing oxygen cylinders
-- ============================================================================

-- RESP-001 氧氣鋼瓶 (H型) - 5支
INSERT OR IGNORE INTO equipment_units (equipment_id, unit_serial, unit_label, level_percent, status) VALUES
('RESP-001', 'H-CYL-001', 'H型1號', 100, 'AVAILABLE'),
('RESP-001', 'H-CYL-002', 'H型2號', 100, 'AVAILABLE'),
('RESP-001', 'H-CYL-003', 'H型3號', 80, 'AVAILABLE'),
('RESP-001', 'H-CYL-004', 'H型4號', 50, 'IN_USE'),
('RESP-001', 'H-CYL-005', 'H型5號', 0, 'EMPTY');

-- EMER-EQ-006 氧氣瓶 (E型) - 4支
INSERT OR IGNORE INTO equipment_units (equipment_id, unit_serial, unit_label, level_percent, status) VALUES
('EMER-EQ-006', 'E-CYL-001', 'E型1號', 100, 'AVAILABLE'),
('EMER-EQ-006', 'E-CYL-002', 'E型2號', 100, 'AVAILABLE'),
('EMER-EQ-006', 'E-CYL-003', 'E型3號', 60, 'AVAILABLE'),
('EMER-EQ-006', 'E-CYL-004', 'E型4號', 20, 'IN_USE');

-- ============================================================================
-- 3. Add tracking_mode to equipment table
-- ============================================================================

-- tracking_mode: 'AGGREGATE' (default) or 'PER_UNIT'
ALTER TABLE equipment ADD COLUMN tracking_mode TEXT DEFAULT 'AGGREGATE';

-- Update oxygen cylinders to use PER_UNIT tracking
UPDATE equipment SET tracking_mode = 'PER_UNIT'
WHERE id IN ('RESP-001', 'EMER-EQ-006');

-- ============================================================================
-- 4. Create view for easy aggregate calculation
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_equipment_aggregate AS
SELECT
    e.id,
    e.name,
    e.category,
    e.quantity,
    e.tracking_mode,
    CASE
        WHEN e.tracking_mode = 'PER_UNIT' THEN
            (SELECT COUNT(*) FROM equipment_units u WHERE u.equipment_id = e.id)
        ELSE e.quantity
    END as actual_count,
    CASE
        WHEN e.tracking_mode = 'PER_UNIT' THEN
            (SELECT AVG(level_percent) FROM equipment_units u WHERE u.equipment_id = e.id)
        ELSE e.power_level
    END as avg_level,
    CASE
        WHEN e.tracking_mode = 'PER_UNIT' THEN
            (SELECT SUM(level_percent) FROM equipment_units u WHERE u.equipment_id = e.id)
        ELSE e.quantity * COALESCE(e.power_level, 100)
    END as total_level_sum
FROM equipment e;

-- ============================================================================
-- Migration complete
-- ============================================================================
