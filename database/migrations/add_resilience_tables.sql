-- ============================================================================
-- MIRS Resilience Tables Migration
-- Version: 1.0.0
-- Based on: IRS_RESILIENCE_FRAMEWORK.md
-- Purpose: Support endurance calculation for oxygen, power, reagents
-- ============================================================================

-- ============================================================================
-- 1. Extend items table for endurance calculation
-- ============================================================================

-- Endurance type classification
ALTER TABLE items ADD COLUMN endurance_type TEXT;
-- Values: 'OXYGEN', 'POWER', 'REAGENT', 'WATER', 'FOOD', NULL (non-endurance item)

-- Capacity per stock unit (e.g., 6900 liters per H-type cylinder)
ALTER TABLE items ADD COLUMN capacity_per_unit REAL;

-- Capacity unit (e.g., 'liters', 'hours', 'tests')
ALTER TABLE items ADD COLUMN capacity_unit TEXT;

-- Tests per unit for reagents (e.g., 100 tests per CBC kit)
ALTER TABLE items ADD COLUMN tests_per_unit INTEGER;

-- Valid days after opening for reagents
ALTER TABLE items ADD COLUMN valid_days_after_open INTEGER;

-- Resource dependency (e.g., O2 Concentrator depends on generator power)
ALTER TABLE items ADD COLUMN depends_on_item_code TEXT;
ALTER TABLE items ADD COLUMN dependency_note TEXT;

-- ============================================================================
-- 2. Resilience Profiles Table (User-editable consumption scenarios)
-- ============================================================================

CREATE TABLE IF NOT EXISTS resilience_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,           -- '*' for global defaults
    endurance_type TEXT NOT NULL,       -- 'OXYGEN', 'POWER', 'REAGENT'
    profile_name TEXT NOT NULL,         -- Display name in Chinese
    profile_name_en TEXT,               -- English name
    burn_rate REAL NOT NULL,            -- Consumption rate value
    burn_rate_unit TEXT NOT NULL,       -- 'L/min', 'L/hr', 'tests/day'
    population_multiplier INTEGER DEFAULT 0, -- 1 = Rate × population
    description TEXT,
    is_default INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_profiles_type
    ON resilience_profiles(endurance_type, station_id);

-- ============================================================================
-- 3. Station Resilience Configuration
-- ============================================================================

CREATE TABLE IF NOT EXISTS resilience_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL UNIQUE,

    -- Isolation context
    isolation_target_days REAL DEFAULT 3,
    isolation_source TEXT DEFAULT 'manual', -- 'manual', 'weather_api'

    -- Population context
    population_count INTEGER DEFAULT 1,
    population_label TEXT DEFAULT '人數',

    -- Active profile IDs (foreign keys to resilience_profiles)
    oxygen_profile_id INTEGER,
    power_profile_id INTEGER,
    reagent_profile_id INTEGER,

    -- Alert thresholds (percentage of isolation target)
    threshold_safe REAL DEFAULT 1.2,      -- >=120% = SAFE
    threshold_warning REAL DEFAULT 1.0,   -- >=100% = WARNING
    -- Below 100% = CRITICAL

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,

    FOREIGN KEY (oxygen_profile_id) REFERENCES resilience_profiles(id),
    FOREIGN KEY (power_profile_id) REFERENCES resilience_profiles(id),
    FOREIGN KEY (reagent_profile_id) REFERENCES resilience_profiles(id)
);

-- ============================================================================
-- 4. Unit Standards Reference (for capacity lookup)
-- ============================================================================

CREATE TABLE IF NOT EXISTS unit_standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_type TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    display_name_en TEXT,
    capacity REAL NOT NULL,
    capacity_unit TEXT NOT NULL,
    category TEXT NOT NULL,  -- 'OXYGEN', 'FUEL', 'WATER'
    notes TEXT,
    region TEXT DEFAULT 'TW'
);

-- ============================================================================
-- 5. Reagent Open Tracking (for open-vial expiry)
-- ============================================================================

CREATE TABLE IF NOT EXISTS reagent_open_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT NOT NULL,
    batch_number TEXT,
    station_id TEXT NOT NULL,
    opened_at DATETIME NOT NULL,
    tests_remaining INTEGER,
    is_active INTEGER DEFAULT 1,  -- 1 = current open kit
    notes TEXT,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (item_code) REFERENCES items(item_code)
);

CREATE INDEX IF NOT EXISTS idx_reagent_open_active
    ON reagent_open_records(item_code, station_id, is_active);

-- ============================================================================
-- 6. Seed Data: Unit Standards (Taiwan)
-- ============================================================================

INSERT OR IGNORE INTO unit_standards (unit_type, display_name, display_name_en, capacity, capacity_unit, category, notes) VALUES
-- Oxygen Cylinders
('O2_CYLINDER_E', 'E型氧氣瓶', 'E-Type O2 Cylinder', 680, 'liters', 'OXYGEN', '攜帶型，常見於救護車'),
('O2_CYLINDER_H', 'H型氧氣瓶', 'H-Type O2 Cylinder', 6900, 'liters', 'OXYGEN', '大型固定式'),
('O2_CYLINDER_D', 'D型氧氣瓶', 'D-Type O2 Cylinder', 400, 'liters', 'OXYGEN', '小型攜帶式'),
-- Fuel Containers
('FUEL_JERRY_20L', '20公升油桶', '20L Jerry Can', 20, 'liters', 'FUEL', '標準塑膠油桶'),
('FUEL_JERRY_10L', '10公升油桶', '10L Jerry Can', 10, 'liters', 'FUEL', '小型油桶'),
('FUEL_DRUM_200L', '200公升油桶', '200L Drum', 200, 'liters', 'FUEL', '大型儲油桶'),
-- Water
('WATER_BOTTLE_2L', '2公升瓶裝水', '2L Water Bottle', 2, 'liters', 'WATER', '標準瓶裝'),
('WATER_BARREL_20L', '20公升桶裝水', '20L Water Barrel', 20, 'liters', 'WATER', '大桶裝');

-- ============================================================================
-- 7. Seed Data: Default Resilience Profiles
-- ============================================================================

-- Oxygen Profiles (MIRS specific)
INSERT OR IGNORE INTO resilience_profiles
(station_id, endurance_type, profile_name, profile_name_en, burn_rate, burn_rate_unit, description, is_default, sort_order) VALUES
('*', 'OXYGEN', '1位插管患者', '1 Intubated Patient', 10, 'L/min', '標準機械通氣 10 L/min', 1, 1),
('*', 'OXYGEN', '2位插管患者', '2 Intubated Patients', 20, 'L/min', '2位患者各10 L/min', 0, 2),
('*', 'OXYGEN', '3位插管患者', '3 Intubated Patients', 30, 'L/min', '3位患者各10 L/min', 0, 3),
('*', 'OXYGEN', '面罩供氧(3人)', '3 Patients on Mask', 15, 'L/min', '每人約 5 L/min', 0, 4),
('*', 'OXYGEN', '鼻導管(5人)', '5 Patients on Nasal', 10, 'L/min', '每人約 2 L/min', 0, 5);

-- Power Profiles
INSERT OR IGNORE INTO resilience_profiles
(station_id, endurance_type, profile_name, profile_name_en, burn_rate, burn_rate_unit, description, is_default, sort_order) VALUES
('*', 'POWER', '省電模式', 'Power Saving', 1.5, 'L/hr', '僅照明+呼吸器', 0, 1),
('*', 'POWER', '標準運作', 'Normal Operation', 3.0, 'L/hr', '照明+冷藏+基本設備', 1, 2),
('*', 'POWER', '全速運轉', 'Full Load', 5.0, 'L/hr', '含空調+檢驗設備', 0, 3);

-- Reagent Profiles
INSERT OR IGNORE INTO resilience_profiles
(station_id, endurance_type, profile_name, profile_name_en, burn_rate, burn_rate_unit, description, is_default, sort_order) VALUES
('*', 'REAGENT', '平時', 'Normal', 5, 'tests/day', '日常檢驗量', 1, 1),
('*', 'REAGENT', '災時增量', 'Disaster Surge', 15, 'tests/day', '災難期間增加', 0, 2),
('*', 'REAGENT', '大量傷患', 'Mass Casualty', 30, 'tests/day', '大量傷患應變', 0, 3);

-- ============================================================================
-- 8. Update existing items with endurance metadata
-- ============================================================================

-- Oxygen Cylinders
UPDATE items SET
    endurance_type = 'OXYGEN',
    capacity_per_unit = 6900,
    capacity_unit = 'liters'
WHERE item_code = 'O2-CYL-H';

UPDATE items SET
    endurance_type = 'OXYGEN',
    capacity_per_unit = 680,
    capacity_unit = 'liters'
WHERE item_code = 'O2-CYL-E';

UPDATE items SET
    endurance_type = 'OXYGEN',
    capacity_per_unit = 400,
    capacity_unit = 'liters'
WHERE item_code = 'O2-CYL-D';

-- Oxygen Concentrator (depends on power)
UPDATE items SET
    endurance_type = 'OXYGEN',
    capacity_per_unit = NULL,  -- Continuous as long as power available
    capacity_unit = 'L/min',
    depends_on_item_code = 'GEN-FUEL-20L',
    dependency_note = '需要發電機電力才能運作'
WHERE item_code IN ('O2-CONC-5L', 'O2-CONC-10L');

-- Fuel
UPDATE items SET
    endurance_type = 'POWER',
    capacity_per_unit = 20,
    capacity_unit = 'liters'
WHERE item_code = 'GEN-FUEL-20L';

UPDATE items SET
    endurance_type = 'POWER',
    capacity_per_unit = 10,
    capacity_unit = 'liters'
WHERE item_code = 'GEN-FUEL-10L';

UPDATE items SET
    endurance_type = 'POWER',
    capacity_per_unit = 20,
    capacity_unit = 'liters'
WHERE item_code = 'GEN-TANK';

-- Reagents
UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 100,
    valid_days_after_open = 28
WHERE item_code = 'REA-CBC-001';

UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 25,
    valid_days_after_open = 14
WHERE item_code IN ('REA-TROP-001', 'REA-BNP-001', 'REA-DDIM-001', 'REA-PCT-001');

UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 50,
    valid_days_after_open = 30
WHERE item_code IN ('REA-LAC-001', 'REA-CRP-001', 'REA-COAG-001', 'REA-CREA-001');

UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 50,
    valid_days_after_open = NULL  -- Strips are individually sealed
WHERE item_code = 'REA-GLU-001';

UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 100,
    valid_days_after_open = NULL
WHERE item_code IN ('REA-URI-001', 'REA-ELEC-001');

UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 25,
    valid_days_after_open = 7
WHERE item_code = 'REA-ABG-001';

UPDATE items SET
    endurance_type = 'REAGENT',
    tests_per_unit = 25,
    valid_days_after_open = NULL
WHERE item_code IN ('REA-FLU-001', 'REA-COVID-001');

-- ============================================================================
-- 9. Create default station config
-- ============================================================================

INSERT OR IGNORE INTO resilience_config (station_id, isolation_target_days, population_count, population_label)
SELECT station_id, 5, 2, '插管患者數' FROM stations LIMIT 1;

-- ============================================================================
-- 10. Enable population_multiplier for default oxygen profile
-- ============================================================================

-- Set population_multiplier = 1 for the default oxygen profile so that
-- changing population_count dynamically affects oxygen burn rate
UPDATE resilience_profiles
SET population_multiplier = 1
WHERE endurance_type = 'OXYGEN' AND is_default = 1;

-- ============================================================================
-- Migration complete
-- ============================================================================
