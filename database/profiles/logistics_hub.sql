-- ============================================================================
-- MIRS Database Profile: Logistics Hub (物資中繼站)
-- Supply Depot and Distribution Center
-- ============================================================================
-- Description: Logistics station for storing and distributing supplies
--              No medical personnel, no procedures. Larger stock quantities.
-- Use Case: Supply warehousing, inter-station distribution, backup storage
-- Data Included: 15 medicines (bulk storage) + basic equipment + consumables
-- ============================================================================

-- Read full schemas
.read database/schema_general_inventory.sql
.read database/schema_pharmacy.sql

-- ============================================================================
-- Station Metadata - Logistics Hub Configuration
-- ============================================================================

INSERT OR REPLACE INTO station_metadata (
    station_code, station_name, station_type, admin_level,
    organization_code, organization_name, region_code, region_name,
    beds, daily_capacity, has_pharmacy, has_surgery, has_emergency,
    storage_capacity_m3, status
) VALUES (
    'LOG-01', '物資中繼站', 'SECOND_CLASS', 'DISTRICT',
    'LOGISTICS', '後勤補給中心', 'SUPPLY', '補給區域',
    0, 0, 1, 0, 0,
    200.0, 'ACTIVE'
);

-- ============================================================================
-- Medicine List - BULK STORAGE (Larger Quantities)
-- Minimum stock: 3x normal, Current stock: 5x normal
-- ============================================================================

INSERT INTO medicines (medicine_code, generic_name, brand_name, dosage_form, strength, atc_code, therapeutic_class, is_controlled_drug, controlled_level, requires_prescription, unit, baseline_qty_7days, min_stock, max_stock, reorder_point, current_stock, reserved_stock, unit_cost, unit_price, nhi_price, currency, has_expiry, is_active, is_critical) VALUES
('MED-001', 'Paracetamol', 'Panadol', 'TABLET', '500mg', 'N02BE01', '解熱鎮痛', 0, NULL, 0, '顆', 500, 150, 2500, 250, 1500, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-002', 'Ibuprofen', 'Advil', 'TABLET', '400mg', 'M01AE01', '消炎止痛', 0, NULL, 0, '顆', 250, 100, 1500, 150, 750, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-003', 'Amoxicillin', 'Amoxil', 'CAPSULE', '500mg', 'J01CA04', '抗生素', 0, NULL, 1, '顆', 200, 75, 1000, 125, 500, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-004', 'Morphine', 'Morphine Sulfate', 'INJECTION', '10mg/ml', 'N02AA01', '強效止痛', 1, 'LEVEL_2', 1, 'ml', 50, 25, 250, 40, 150, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 1),
('MED-005', 'Epinephrine', 'Adrenaline', 'INJECTION', '1mg/ml', 'C01CA24', '急救藥品', 0, NULL, 1, 'ml', 100, 50, 500, 75, 300, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 1),
('MED-006', 'Diazepam', 'Valium', 'TABLET', '5mg', 'N05BA01', '鎮靜劑', 1, 'LEVEL_4', 1, '顆', 75, 25, 400, 50, 200, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-007', 'Aspirin', 'Aspirin', 'TABLET', '100mg', 'B01AC06', '抗血小板', 0, NULL, 1, '顆', 400, 150, 2000, 250, 1000, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-008', 'Cephalexin', 'Keflex', 'CAPSULE', '500mg', 'J01DB01', '抗生素', 0, NULL, 1, '顆', 150, 50, 750, 100, 400, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-009', 'Metformin', 'Glucophage', 'TABLET', '850mg', 'A10BA02', '降血糖藥', 0, NULL, 1, '顆', 250, 100, 1250, 150, 750, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-010', 'Omeprazole', 'Losec', 'CAPSULE', '20mg', 'A02BC01', '胃藥', 0, NULL, 1, '顆', 200, 75, 1000, 125, 600, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-011', 'Lorazepam', 'Ativan', 'TABLET', '1mg', 'N05BA06', '抗焦慮', 1, 'LEVEL_4', 1, '顆', 60, 25, 300, 40, 175, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-012', 'Furosemide', 'Lasix', 'TABLET', '40mg', 'C03CA01', '利尿劑', 0, NULL, 1, '顆', 125, 50, 600, 75, 350, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-013', 'Atorvastatin', 'Lipitor', 'TABLET', '20mg', 'C10AA05', '降血脂', 0, NULL, 1, '顆', 175, 75, 900, 125, 500, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-014', 'Tramadol', 'Ultram', 'CAPSULE', '50mg', 'N02AX02', '止痛劑', 1, 'LEVEL_4', 1, '顆', 100, 40, 500, 60, 300, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 0),
('MED-015', 'Ceftriaxone', 'Rocephin', 'INJECTION', '1g', 'J01DD04', '抗生素', 0, NULL, 1, '支', 75, 25, 400, 50, 200, 0, 0.0, 0.0, 0.0, 'TWD', 1, 1, 1);

-- ============================================================================
-- Equipment - Warehouse & Storage Equipment
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

INSERT INTO equipment (id, name, category, quantity, status, remarks) VALUES
-- Power & Environmental Control (LOG- prefix for unique IDs)
('LOG-POWER-1', '行動電源站', '電力設備', 3, 'UNCHECKED', 'Logistics Hub 增量配備'),
('LOG-POWER-2', '備用發電機', '電力設備', 1, 'UNCHECKED', 'Logistics Hub'),
('LOG-PHOTO-1', '光觸媒', '空氣淨化', 2, 'UNCHECKED', 'Logistics Hub 增量配備'),

-- Refrigeration & Temperature Control
('LOG-FRIDGE-1', '行動冰箱', '冷藏設備', 5, 'UNCHECKED', 'Logistics Hub 增量配備'),
('LOG-FRIDGE-2', '冷凍櫃', '冷藏設備', 2, 'UNCHECKED', 'Logistics Hub'),
('LOG-TEMP-1', '溫濕度監控系統', '監控設備', 4, 'UNCHECKED', 'Logistics Hub'),

-- Water & Sanitation
('LOG-WATER-1', '淨水器', '水處理', 2, 'UNCHECKED', 'Logistics Hub 增量配備'),

-- Material Handling
('LOG-FORK-1', '堆高機', '搬運設備', 2, 'UNCHECKED', 'Logistics Hub'),
('LOG-PALLET-1', '手動托板車', '搬運設備', 5, 'UNCHECKED', 'Logistics Hub'),
('LOG-SHELF-1', '貨架系統', '儲存設備', 20, 'UNCHECKED', 'Logistics Hub');

-- ============================================================================
-- Consumable Items - BULK STORAGE (Larger Quantities)
-- ============================================================================

INSERT INTO items (item_code, item_name, item_category, category, unit, current_stock, min_stock) VALUES
-- Medical Gloves (5x normal)
('GLOVE-S', '醫療手套 Small', 'CONSUMABLE', '防護用品', '盒', 500, 100),
('GLOVE-M', '醫療手套 Medium', 'CONSUMABLE', '防護用品', '盒', 750, 150),
('GLOVE-L', '醫療手套 Large', 'CONSUMABLE', '防護用品', '盒', 500, 100),

-- Gauze & Dressings (5x normal)
('GAUZE-4X4', '紗布 4x4', 'CONSUMABLE', '醫療耗材', '包', 2500, 500),
('GAUZE-8X8', '紗布 8x8', 'CONSUMABLE', '醫療耗材', '包', 1500, 300),
('BANDAGE-2IN', '彈性繃帶 2吋', 'CONSUMABLE', '醫療耗材', '捲', 1000, 200),
('BANDAGE-3IN', '彈性繃帶 3吋', 'CONSUMABLE', '醫療耗材', '捲', 1000, 200),

-- Syringes & Needles (5x normal)
('SYRINGE-3ML', '注射器 3ml', 'CONSUMABLE', '注射用品', '支', 2500, 500),
('SYRINGE-5ML', '注射器 5ml', 'CONSUMABLE', '注射用品', '支', 2500, 500),
('SYRINGE-10ML', '注射器 10ml', 'CONSUMABLE', '注射用品', '支', 1500, 300),
('NEEDLE-21G', '針頭 21G', 'CONSUMABLE', '注射用品', '支', 2500, 500),
('NEEDLE-23G', '針頭 23G', 'CONSUMABLE', '注射用品', '支', 2500, 500),
('NEEDLE-25G', '針頭 25G', 'CONSUMABLE', '注射用品', '支', 2000, 400),

-- IV Supplies (5x normal)
('IV-SET', '點滴套組', 'CONSUMABLE', '注射用品', '組', 1500, 300),
('IV-CATH-22G', '靜脈留置針 22G', 'CONSUMABLE', '注射用品', '支', 1000, 200),
('IV-CATH-20G', '靜脈留置針 20G', 'CONSUMABLE', '注射用品', '支', 1000, 200),

-- Protective Equipment (5x normal)
('MASK-SURGICAL', '外科口罩', 'CONSUMABLE', '防護用品', '盒', 500, 100),
('MASK-N95', 'N95口罩', 'CONSUMABLE', '防護用品', '盒', 250, 50),
('GOWN-ISOLATION', '隔離衣', 'CONSUMABLE', '防護用品', '件', 1000, 200),
('FACE-SHIELD', '面罩', 'CONSUMABLE', '防護用品', '個', 500, 100),

-- Disinfection & Sanitation (5x normal)
('ALCOHOL-75', '75%酒精', 'CONSUMABLE', '清潔用品', '瓶', 1000, 200),
('HAND-SANITIZER', '乾洗手液', 'CONSUMABLE', '清潔用品', '瓶', 750, 150),
('BLEACH', '漂白水', 'CONSUMABLE', '清潔用品', '瓶', 500, 100);

-- ============================================================================
-- Blood Inventory Initialization (Logistics Hub - bulk storage)
-- ============================================================================

INSERT OR REPLACE INTO blood_inventory (blood_type, quantity, station_id) VALUES
('A+', 50, 'LOG-01'),
('A-', 25, 'LOG-01'),
('B+', 50, 'LOG-01'),
('B-', 25, 'LOG-01'),
('O+', 75, 'LOG-01'),
('O-', 50, 'LOG-01'),
('AB+', 25, 'LOG-01'),
('AB-', 15, 'LOG-01');

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
('logistics_hub', '1.0.0', 'Logistics Hub for Bulk Storage and Distribution');

-- ============================================================================
-- Profile initialization complete
-- Total Equipment: 10 logistics equipment
-- Total Consumables: 23 items (5x normal quantities)
-- Total Medicines: 15 items (5x normal quantities)
--
-- Note: This station does NOT perform medical procedures
--       It only stores and distributes supplies to other stations
-- ============================================================================
