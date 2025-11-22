-- ============================================================================
-- MIRS Database Profile: Hospital Custom (醫院自訂)
-- Minimal Schema for Custom Data Import
-- ============================================================================
-- Description: Empty schema only - hospitals can import their own item lists
-- Use Case: Hospitals with existing item codes and inventory systems
-- Data Included: Schema only (no preloaded data)
-- ============================================================================

-- Read full schemas
.read database/schema_general_inventory.sql
.read database/schema_pharmacy.sql

-- ============================================================================
-- Station Metadata - Hospital Custom Configuration
-- ============================================================================

INSERT OR REPLACE INTO station_metadata (
    station_code, station_name, station_type, admin_level,
    organization_code, organization_name, region_code, region_name,
    beds, daily_capacity, has_pharmacy, has_surgery, has_emergency,
    storage_capacity_m3, status
) VALUES (
    'HOSP-01', '自訂醫療機構', 'FIRST_CLASS', 'STATION_LOCAL',
    'CUSTOM', '待設定醫療機構', 'CUSTOM', '待設定區域',
    0, 0, 1, 0, 0,
    50.0, 'ACTIVE'
);

-- ============================================================================
-- Empty tables ready for custom data import
-- ============================================================================

-- No preloaded data - tables are created by schema files
-- Users can import their own data using:
--   1. CSV import scripts
--   2. SQL INSERT statements
--   3. Data migration tools

-- ============================================================================
-- Import Templates (Comment guide for users)
-- ============================================================================

-- IMPORT TEMPLATE: Items (General Consumables)
-- CSV Format: code, name, category, unit, stock, min_stock, location, remarks
-- Example:
-- INSERT INTO items (code, name, category, unit, stock, min_stock) VALUES
-- ('001', '手套', '耗材', '盒', 100, 20);

-- IMPORT TEMPLATE: Medicines (Pharmacy)
-- CSV Format: medicine_code, generic_name, brand_name, dosage_form, strength, unit, min_stock, current_stock
-- Example:
-- INSERT INTO medicines (medicine_code, generic_name, brand_name, dosage_form, strength, unit, min_stock, current_stock, is_active) VALUES
-- ('001', 'Acetaminophen', '乙醯胺酚', 'TABLET', '500mg', '顆', 30, 100, 1);

-- IMPORT TEMPLATE: Equipment
-- CSV Format: code, name, category, quantity, check_status, location
-- Example:
-- INSERT INTO equipment (code, name, category, quantity, check_status) VALUES
-- ('EQ001', '超音波機', '診斷設備', 1, 'UNCHECKED');

-- ============================================================================
-- Blood Inventory Initialization (Hospital starts at 0)
-- ============================================================================

INSERT OR REPLACE INTO blood_inventory (blood_type, quantity, station_id) VALUES
('A+', 0, 'HOSP-01'),
('A-', 0, 'HOSP-01'),
('B+', 0, 'HOSP-01'),
('B-', 0, 'HOSP-01'),
('O+', 0, 'HOSP-01'),
('O-', 0, 'HOSP-01'),
('AB+', 0, 'HOSP-01'),
('AB-', 0, 'HOSP-01');

-- ============================================================================
-- Profile Metadata
-- ============================================================================

CREATE TABLE IF NOT EXISTS profile_metadata (
    profile_name TEXT PRIMARY KEY,
    profile_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

INSERT OR REPLACE INTO profile_metadata (profile_name, profile_version, description) VALUES
('hospital_custom', '1.0.0', 'Minimal Schema for Hospital Custom Data Import');

-- ============================================================================
-- Next Steps for Hospital Deployment
-- ============================================================================

-- 1. Prepare your data in CSV format
-- 2. Use import scripts:
--    python3 scripts/import_data.py --type items --file hospital_items.csv
--    python3 scripts/import_data.py --type medicines --file hospital_medicines.csv
--
-- 3. Or use SQL INSERT statements:
--    sqlite3 medical_inventory.db < hospital_data.sql
--
-- 4. Update station metadata with your hospital details:
--    UPDATE station_metadata SET
--      station_name = '您的醫院名稱',
--      organization_code = '醫院代碼',
--      organization_name = '醫院全名'
--    WHERE station_code = 'HOSP-01';

-- ============================================================================
-- Profile initialization complete
-- ============================================================================
