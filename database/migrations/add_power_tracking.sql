-- ============================================================================
-- MIRS Power Tracking Enhancement Migration
-- Version: 1.3.0
-- Purpose: Support detailed power capacity and consumption tracking
-- ============================================================================

-- ============================================================================
-- 1. Add power tracking columns to equipment table
-- ============================================================================

-- 設備耗電瓦數 (for medical equipment)
ALTER TABLE equipment ADD COLUMN power_watts INTEGER;

-- 電源站/電池總容量 Wh (for power stations)
ALTER TABLE equipment ADD COLUMN capacity_wh REAL;

-- 發電機/電源站輸出瓦數 (for generators/power stations)
ALTER TABLE equipment ADD COLUMN output_watts INTEGER;

-- 發電機耗油率 L/hr (for fuel generators)
ALTER TABLE equipment ADD COLUMN fuel_rate_lph REAL;

-- 設備型號/類別代碼 (for grouping similar devices)
ALTER TABLE equipment ADD COLUMN device_type TEXT;

-- ============================================================================
-- 2. Update existing equipment with estimated values
-- ============================================================================

-- 行動電源站 (typical values)
UPDATE equipment SET
    capacity_wh = 2048,
    output_watts = 2000,
    device_type = 'POWER_STATION'
WHERE name LIKE '%行動電源%' OR name LIKE '%電源站%';

-- 發電機 (typical 3kW generator)
UPDATE equipment SET
    output_watts = 3000,
    fuel_rate_lph = 1.5,
    device_type = 'GENERATOR'
WHERE name LIKE '%發電機%';

-- 氧氣濃縮機 (5L model ~350W, 10L model ~500W)
UPDATE equipment SET
    power_watts = 350,
    device_type = 'O2_CONCENTRATOR'
WHERE name LIKE '%氧氣%' AND name LIKE '%5L%';

UPDATE equipment SET
    power_watts = 500,
    device_type = 'O2_CONCENTRATOR'
WHERE name LIKE '%氧氣%' AND name LIKE '%10L%';

-- 呼吸器 (typical ~150W)
UPDATE equipment SET
    power_watts = 150,
    device_type = 'VENTILATOR'
WHERE name LIKE '%呼吸器%' OR name LIKE '%BiPAP%' OR name LIKE '%CPAP%';

-- 監視器 (typical ~50W)
UPDATE equipment SET
    power_watts = 50,
    device_type = 'MONITOR'
WHERE name LIKE '%監視器%' OR name LIKE '%生理監視%';

-- 抽吸機 (typical ~100W)
UPDATE equipment SET
    power_watts = 100,
    device_type = 'SUCTION'
WHERE name LIKE '%抽吸%';

-- 冰箱 (typical ~150W average)
UPDATE equipment SET
    power_watts = 150,
    device_type = 'REFRIGERATOR'
WHERE name LIKE '%冰箱%' OR name LIKE '%冷藏%';

-- ============================================================================
-- 3. Create power_load_profiles table for scenario planning
-- ============================================================================

CREATE TABLE IF NOT EXISTS power_load_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    profile_name_en TEXT,
    description TEXT,
    total_watts INTEGER NOT NULL,
    is_default INTEGER DEFAULT 0,
    equipment_list TEXT,  -- JSON array of equipment IDs included
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 4. Seed default power load profiles
-- ============================================================================

INSERT OR IGNORE INTO power_load_profiles
(station_id, profile_name, profile_name_en, description, total_watts, is_default, sort_order) VALUES
('*', '最低運作', 'Minimum', '僅照明+製氧機', 500, 0, 1),
('*', '標準運作', 'Normal', '照明+製氧機+監視器+冰箱', 1000, 1, 2),
('*', '全負載', 'Full Load', '全部設備運轉', 2000, 0, 3);

-- ============================================================================
-- Migration complete
-- ============================================================================
