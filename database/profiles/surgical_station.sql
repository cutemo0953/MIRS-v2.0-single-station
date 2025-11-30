-- ============================================================================
-- MIRS Database Profile: Surgical Station BORP (備援手術站)
-- Backup Operating Room Platform
-- ============================================================================
-- Description: Emergency surgical station with reusable surgical instruments
-- Use Case: Disaster response, field hospitals, emergency surgical operations
-- Data Included: 15 medicines + surgical instruments + normal consumables
-- ============================================================================

-- Read full schemas
.read database/schema_general_inventory.sql
.read database/schema_pharmacy.sql

-- ============================================================================
-- Station Metadata - BORP Configuration
-- ============================================================================
-- 注意：站點資訊不再預載，請在設定精靈中配置站點名稱與代碼
-- 建議配置（可依實際需求調整）：
--   站點代碼: BORP-XX (例如: WuriBORP-1, VGHBORP-3)
--   站點名稱: 自訂 (例如: 烏日手術站1號, 榮總備援手術站3號)
--   站點類型: THIRD_CLASS_BORP (三級備援手術站)
--   組織代碼: BORP
--   區域代碼: EMERG (緊急救援)
--
-- 站點資訊將在首次使用時透過「設定精靈」建立，自動綁定正確的站點配置

-- ============================================================================
-- Government Standard Medicine List (15 items) - Same as Health Center
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
-- BORP Surgical Instruments (Reusable Equipment)
-- 16 different surgical instrument sets
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
-- Orthopedic Instruments (BORP-01 station)
('BORP-SURG-ORTHO-01', '骨科包', '手術器械', 8, 'UNCHECKED', '可重複使用'),
('BORP-SURG-DRILL-01', '顱骨手搖鑽', '手術器械', 1, 'UNCHECKED', '神經外科專用'),
('BORP-SURG-DRILL-02', '鑽/切骨電動工具組', '手術器械', 1, 'UNCHECKED', '骨科專用'),
('BORP-SURG-DRILL-03', '電池式電動骨鑽', '手術器械', 1, 'UNCHECKED', '骨科專用'),
('BORP-SURG-SAW-01', '電池式電動骨鋸', '手術器械', 3, 'UNCHECKED', '骨科專用'),

-- Airway & Vascular Instruments
('BORP-SURG-TRACH-01', '氣切輔助包', '手術器械', 8, 'UNCHECKED', '緊急氣道管理'),
('BORP-SURG-CLAMP-01', 'Bull dog血管夾', '手術器械', 4, 'UNCHECKED', '血管手術專用'),

-- General Surgical Packs
('BORP-SURG-BASIC-01', '共同基本包（一）', '手術器械', 8, 'UNCHECKED', '一般手術器械'),
('BORP-SURG-BASIC-02', '共同基本包（二）', '手術器械', 8, 'UNCHECKED', '一般手術器械'),

-- Abdominal Surgery Instruments
('BORP-SURG-ABD-01', '開腹輔助包', '手術器械', 8, 'UNCHECKED', '腹部手術專用'),
('BORP-SURG-RETRACT-01', '腹部開創器', '手術器械', 8, 'UNCHECKED', '腹部手術專用'),

-- Thoracic & Cardiovascular Instruments
('BORP-SURG-THORAX-01', '開胸基本包', '手術器械', 1, 'UNCHECKED', '胸腔手術專用'),
('BORP-SURG-VASC-01', '血管包', '手術器械', 3, 'UNCHECKED', '血管手術專用'),
('BORP-SURG-CARDIAC-01', '心外基本包', '手術器械', 4, 'UNCHECKED', '心臟手術專用'),

-- Specialty Packs
('BORP-SURG-ASSET-01', 'ASSET包', '手術器械', 8, 'UNCHECKED', '緊急手術包'),
('BORP-SURG-SUTURE-01', '皮膚縫合包', '手術器械', 2, 'UNCHECKED', '傷口縫合專用'),

-- ============================================================================
-- Basic Equipment (BORP Configuration with unique IDs)
-- ============================================================================

('BORP-POWER-01', '行動電源站', '電力設備', 1, 'UNCHECKED', 'BORP標準配備'),
('BORP-PHOTO-01', '光觸媒', '空氣淨化', 1, 'UNCHECKED', 'BORP標準配備'),
('BORP-WATER-01', '淨水器', '水處理', 1, 'UNCHECKED', 'BORP標準配備'),
('BORP-FRIDGE-01', '行動冰箱', '冷藏設備', 2, 'UNCHECKED', 'BORP標準配備 (增量)');

-- ============================================================================
-- Sample Consumable Items (Can be customized)
-- ============================================================================

-- Basic surgical consumables
INSERT INTO items (item_code, item_name, item_category, category, unit, current_stock, min_stock) VALUES
('SURG-GLOVE-S', '無菌手套 Small', 'CONSUMABLE', '手術耗材', '雙', 200, 50),
('SURG-GLOVE-M', '無菌手套 Medium', 'CONSUMABLE', '手術耗材', '雙', 300, 50),
('SURG-GLOVE-L', '無菌手套 Large', 'CONSUMABLE', '手術耗材', '雙', 200, 50),
('SURG-GAUZE', '無菌紗布 4x4', 'CONSUMABLE', '手術耗材', '包', 500, 100),
('SURG-SWAB', '手術棉球', 'CONSUMABLE', '手術耗材', '包', 300, 60),
('SURG-DRAPE', '無菌手術巾', 'CONSUMABLE', '手術耗材', '片', 100, 20),
('SURG-GOWN', '無菌手術衣 L', 'CONSUMABLE', '手術耗材', '件', 80, 15),
('SURG-MASK', '外科口罩', 'CONSUMABLE', '防護用品', '盒', 50, 10),
('SURG-SUTURE-3-0', '縫線 3-0', 'CONSUMABLE', '縫合材料', '支', 150, 30),
('SURG-SUTURE-4-0', '縫線 4-0', 'CONSUMABLE', '縫合材料', '支', 150, 30),
('SURG-BLADE-15', '手術刀片 #15', 'CONSUMABLE', '手術器材', '片', 100, 20),
('SURG-SYRINGE-10', '注射器 10ml', 'CONSUMABLE', '注射用品', '支', 200, 40),
('SURG-NEEDLE-18G', '針頭 18G', 'CONSUMABLE', '注射用品', '支', 200, 40),
('SURG-TUBE-ETT7', '氣管內管 7.0', 'CONSUMABLE', '氣道管理', '支', 30, 5),
('SURG-TUBE-ETT8', '氣管內管 8.0', 'CONSUMABLE', '氣道管理', '支', 30, 5);

-- ============================================================================
-- Blood Inventory Initialization (BORP starts with emergency supply)
-- ============================================================================
-- 注意：血袋庫存不再預載，請在設定精靈完成後，透過「血庫管理」功能手動入庫
-- 建議初始數量（可依實際需求調整）：
--   A+: 10U, A-: 5U, B+: 10U, B-: 5U
--   O+: 15U, O-: 10U, AB+: 5U, AB-: 3U
--   總計：63U

-- 血袋庫存將在首次使用時透過 UI 建立，自動綁定正確的站點 ID

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
('surgical_station', '1.0.0', 'BORP Surgical Station with Reusable Surgical Instruments');

-- ============================================================================
-- Profile initialization complete
-- Total Equipment: 20 surgical instruments + 4 basic equipment = 24 items
-- Total Consumables: 15 surgical consumables
-- Total Medicines: 15 items
-- ============================================================================
