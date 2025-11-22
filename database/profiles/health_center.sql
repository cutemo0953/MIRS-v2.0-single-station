-- ============================================================================
-- MIRS Database Profile: Health Center (衛生所)
-- Taiwan Government Standard Template
-- ============================================================================
-- Description: Government-compliant medical station with standard pharmacy
--              and equipment lists. Includes 7-day stock alerts.
-- Use Case: Testing, demos, compliance verification
-- Data Included: 15 medicines + 4 equipment items
-- ============================================================================

-- Read full schemas
.read database/schema_general_inventory.sql
.read database/schema_pharmacy.sql

-- ============================================================================
-- Station Metadata - Health Center Configuration
-- ============================================================================

INSERT OR REPLACE INTO station_metadata (
    station_code, station_name, station_type, admin_level,
    organization_code, organization_name, region_code, region_name,
    beds, daily_capacity, has_pharmacy, has_surgery, has_emergency,
    storage_capacity_m3, status
) VALUES (
    'HC-01', '衛生所示範站', 'FIRST_CLASS', 'DISTRICT',
    'MOHW', '衛生福利部', 'GOV', '政府標準',
    0, 30, 1, 0, 0,
    15.0, 'ACTIVE'
);

-- ============================================================================
-- Government Standard Medicine List (15 items)
-- ============================================================================

INSERT INTO medicines (medicine_code, generic_name, brand_name, dosage_form, strength, atc_code, therapeutic_class, is_controlled_drug, controlled_level, requires_prescription, unit, baseline_qty_7days, min_stock, max_stock, reorder_point, current_stock, reserved_stock, unit_cost, unit_price, nhi_price, currency, has_expiry, is_active, is_critical) VALUES
('MED-001', 'Paracetamol', 'Panadol', 'TABLET', '500mg', 'N02BE01', '解熱鎮痛', 0, NULL, 0, '顆', 100, 30, 500, 50, 300, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-002', 'Ibuprofen', 'Advil', 'TABLET', '400mg', 'M01AE01', '消炎止痛', 0, NULL, 0, '顆', 50, 20, 300, 30, 150, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-003', 'Amoxicillin', 'Amoxil', 'CAPSULE', '500mg', 'J01CA04', '抗生素', 0, NULL, 1, '顆', 40, 15, 200, 25, 100, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-004', 'Morphine', 'Morphine Sulfate', 'INJECTION', '10mg/ml', 'N02AA01', '強效止痛', 1, 'LEVEL_2', 1, 'ml', 10, 5, 50, 8, 30, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 1),
('MED-005', 'Epinephrine', 'Adrenaline', 'INJECTION', '1mg/ml', 'C01CA24', '急救藥品', 0, NULL, 1, 'ml', 20, 10, 100, 15, 60, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 1),
('MED-006', 'Diazepam', 'Valium', 'TABLET', '5mg', 'N05BA01', '鎮靜劑', 1, 'LEVEL_4', 1, '顆', 15, 5, 80, 10, 40, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-007', 'Aspirin', 'Aspirin', 'TABLET', '100mg', 'B01AC06', '抗血小板', 0, NULL, 1, '顆', 80, 30, 400, 50, 200, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-008', 'Cephalexin', 'Keflex', 'CAPSULE', '500mg', 'J01DB01', '抗生素', 0, NULL, 1, '顆', 30, 10, 150, 20, 80, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-009', 'Metformin', 'Glucophage', 'TABLET', '850mg', 'A10BA02', '降血糖藥', 0, NULL, 1, '顆', 50, 20, 250, 30, 150, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-010', 'Omeprazole', 'Losec', 'CAPSULE', '20mg', 'A02BC01', '胃藥', 0, NULL, 1, '顆', 40, 15, 200, 25, 120, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-011', 'Lorazepam', 'Ativan', 'TABLET', '1mg', 'N05BA06', '抗焦慮', 1, 'LEVEL_4', 1, '顆', 12, 5, 60, 8, 35, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-012', 'Furosemide', 'Lasix', 'TABLET', '40mg', 'C03CA01', '利尿劑', 0, NULL, 1, '顆', 25, 10, 120, 15, 70, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-013', 'Atorvastatin', 'Lipitor', 'TABLET', '20mg', 'C10AA05', '降血脂', 0, NULL, 1, '顆', 35, 15, 180, 25, 100, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-014', 'Tramadol', 'Ultram', 'CAPSULE', '50mg', 'N02AX02', '止痛劑', 1, 'LEVEL_4', 1, '顆', 20, 8, 100, 12, 60, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-015', 'Ceftriaxone', 'Rocephin', 'INJECTION', '1g', 'J01DD04', '抗生素', 0, NULL, 1, '支', 15, 5, 80, 10, 40, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 1);

-- ============================================================================
-- Government Standard Equipment List (4 items)
-- ============================================================================

-- Create equipment table (matching main.py schema with 'id' as primary key)
CREATE TABLE IF NOT EXISTS equipment (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT DEFAULT '其他',
    quantity INTEGER DEFAULT 1,
    status TEXT DEFAULT 'UNCHECKED',
    last_check TIMESTAMP,
    power_level INTEGER,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO equipment (id, name, category, quantity, status, last_check, remarks) VALUES
('HC-POWER-1', '行動電源站', '電力設備', 1, 'UNCHECKED', datetime('now'), '政府標準配備'),
('HC-PHOTO-1', '光觸媒', '空氣淨化', 1, 'UNCHECKED', datetime('now'), '政府標準配備'),
('HC-WATER-1', '淨水器', '水處理', 1, 'UNCHECKED', datetime('now'), '政府標準配備'),
('HC-FRIDGE-1', '行動冰箱', '冷藏設備', 1, 'UNCHECKED', datetime('now'), '政府標準配備');

-- ============================================================================
-- Blood Inventory Initialization (All blood types start at 0)
-- ============================================================================

INSERT OR REPLACE INTO blood_inventory (blood_type, quantity, station_id) VALUES
('A+', 0, 'HC-01'),
('A-', 0, 'HC-01'),
('B+', 0, 'HC-01'),
('B-', 0, 'HC-01'),
('O+', 0, 'HC-01'),
('O-', 0, 'HC-01'),
('AB+', 0, 'HC-01'),
('AB-', 0, 'HC-01');

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
('health_center', '1.0.0', 'Taiwan Government Standard Health Center Template');

-- ============================================================================
-- Profile initialization complete
-- ============================================================================
