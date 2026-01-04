-- =============================================================================
-- EMT Transfer Module v2.0 Schema Upgrade
-- Version: 2.0.0
-- Date: 2026-01-04
-- =============================================================================

-- Add v2.0 columns to transfer_missions
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE, handled in Python

-- 1. origin_station_id (FK reference, denormalized for offline use)
ALTER TABLE transfer_missions ADD COLUMN origin_station_id TEXT;

-- 2. destination_text (free text, more flexible than destination)
ALTER TABLE transfer_missions ADD COLUMN destination_text TEXT;

-- 3. eta_min (ETA in minutes, separate from round-trip duration)
ALTER TABLE transfer_missions ADD COLUMN eta_min INTEGER;

-- 4. iv_mode (NONE/KVO/BOLUS/CUSTOM)
ALTER TABLE transfer_missions ADD COLUMN iv_mode TEXT DEFAULT 'NONE';

-- 5. iv_mlhr_override (custom mL/hr when iv_mode=CUSTOM)
ALTER TABLE transfer_missions ADD COLUMN iv_mlhr_override REAL;

-- 6. oxygen_cylinders_json (per-cylinder PSI tracking)
-- Format: [{"cylinder_id": "O2-E-001", "cylinder_type": "E", "capacity_liters": 660,
--           "starting_psi": 2100, "ending_psi": null, "consumed_liters": null}]
ALTER TABLE transfer_missions ADD COLUMN oxygen_cylinders_json TEXT;

-- 7. equipment_battery_json (per-equipment battery tracking)
-- Format: [{"equipment_id": "EQ-001", "equipment_name": "Monitor",
--           "starting_battery_pct": 95, "ending_battery_pct": null}]
ALTER TABLE transfer_missions ADD COLUMN equipment_battery_json TEXT;

-- 8. confirmed_at (when loadout was confirmed, distinct from ready_at)
ALTER TABLE transfer_missions ADD COLUMN confirmed_at TIMESTAMP;

-- 9. o2_lpm (alias for oxygen_requirement_lpm, for v2.0 API compatibility)
-- Note: Use existing oxygen_requirement_lpm, no new column needed

-- =============================================================================
-- Cylinder Types Reference Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS oxygen_cylinder_types (
    type_code TEXT PRIMARY KEY,      -- E, D, H, M, etc.
    name TEXT NOT NULL,
    capacity_liters REAL NOT NULL,
    full_psi INTEGER NOT NULL,
    weight_empty_kg REAL,
    weight_full_kg REAL,
    is_portable INTEGER DEFAULT 1
);

-- Seed cylinder types
INSERT OR IGNORE INTO oxygen_cylinder_types (type_code, name, capacity_liters, full_psi, weight_empty_kg, weight_full_kg, is_portable) VALUES
('E', 'E-Tank (攜帶型)', 660, 2100, 5.9, 8.0, 1),
('D', 'D-Tank (小型)', 350, 2100, 4.5, 5.5, 1),
('M', 'M-Tank (中型)', 3000, 2200, 29.5, 34.0, 0),
('H', 'H-Tank (大型)', 6900, 2200, 54.4, 61.0, 0),
('Jumbo-D', 'Jumbo D-Tank', 640, 2200, 8.0, 10.0, 1);

-- =============================================================================
-- IV Mode Reference
-- =============================================================================
CREATE TABLE IF NOT EXISTS iv_mode_presets (
    mode TEXT PRIMARY KEY,
    name_zh TEXT NOT NULL,
    rate_mlhr REAL NOT NULL,
    description TEXT
);

INSERT OR IGNORE INTO iv_mode_presets (mode, name_zh, rate_mlhr, description) VALUES
('NONE', '無', 0, '不需輸液'),
('KVO', '維持通路', 30, 'Keep Vein Open'),
('BOLUS', '快速補液', 1000, '500mL/30min 等效'),
('MAINTENANCE', '維持輸液', 100, '一般維持'),
('CUSTOM', '自訂', 0, '使用 iv_mlhr_override');

-- =============================================================================
-- Transfer Oxygen Cylinders (per-mission cylinder tracking)
-- Alternative to JSON field for better querying
-- =============================================================================
CREATE TABLE IF NOT EXISTS transfer_oxygen_cylinders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,

    -- Cylinder identification
    cylinder_id TEXT,                 -- Equipment unit ID if linked
    cylinder_type TEXT NOT NULL,      -- E, D, H, etc.
    unit_label TEXT,                  -- Physical label on cylinder

    -- PSI tracking
    starting_psi INTEGER,
    ending_psi INTEGER,

    -- Calculated consumption
    consumed_liters REAL,

    -- Status
    status TEXT DEFAULT 'ASSIGNED',   -- ASSIGNED, IN_USE, RETURNED, CONSUMED

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);

CREATE INDEX IF NOT EXISTS idx_transfer_oxygen_mission ON transfer_oxygen_cylinders(mission_id);

-- =============================================================================
-- Transfer Equipment Battery (per-mission battery tracking)
-- =============================================================================
CREATE TABLE IF NOT EXISTS transfer_equipment_battery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,

    -- Equipment identification
    equipment_id TEXT,                -- Equipment unit ID
    equipment_name TEXT NOT NULL,
    equipment_type TEXT,              -- MONITOR, VENTILATOR, SUCTION, etc.

    -- Battery tracking
    starting_battery_pct INTEGER,
    ending_battery_pct INTEGER,

    -- Calculated drain
    battery_drain_pct INTEGER,

    -- Status
    status TEXT DEFAULT 'ASSIGNED',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);

CREATE INDEX IF NOT EXISTS idx_transfer_battery_mission ON transfer_equipment_battery(mission_id);
