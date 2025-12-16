-- ============================================================================
-- MIRS Master Catalog - Centralized Item Database
-- Version: 1.0.0
-- Purpose: Standardized item codes and definitions for all stations
-- ============================================================================
--
-- USAGE:
-- - This catalog contains ALL possible items that any station might use
-- - Station profiles SELECT subsets from this catalog
-- - Users CANNOT create custom codes - they must use catalog codes
-- - Admins can update this catalog to add new standardized items
--
-- ============================================================================

-- ============================================================================
-- CONSUMABLES - 耗材類
-- ============================================================================

-- Medical Gloves (Sizes)
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('PPE-GLOVE-XS', '醫療手套 XS', 'CONSUMABLE', '防護用品', '盒', '100入/盒'),
('PPE-GLOVE-S', '醫療手套 Small', 'CONSUMABLE', '防護用品', '盒', '100入/盒'),
('PPE-GLOVE-M', '醫療手套 Medium', 'CONSUMABLE', '防護用品', '盒', '100入/盒'),
('PPE-GLOVE-L', '醫療手套 Large', 'CONSUMABLE', '防護用品', '盒', '100入/盒'),
('PPE-GLOVE-XL', '醫療手套 XL', 'CONSUMABLE', '防護用品', '盒', '100入/盒');

-- Gauze & Dressings
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('GAUZE-2X2', '紗布 2x2', 'CONSUMABLE', '醫療耗材', '包', '200片/包'),
('GAUZE-4X4', '紗布 4x4', 'CONSUMABLE', '醫療耗材', '包', '200片/包'),
('GAUZE-8X8', '紗布 8x8', 'CONSUMABLE', '醫療耗材', '包', '100片/包'),
('BAND-2IN', '彈性繃帶 2吋', 'CONSUMABLE', '醫療耗材', '捲', '4.5m/捲'),
('BAND-3IN', '彈性繃帶 3吋', 'CONSUMABLE', '醫療耗材', '捲', '4.5m/捲'),
('BAND-4IN', '彈性繃帶 4吋', 'CONSUMABLE', '醫療耗材', '捲', '4.5m/捲'),
('ADHESIVE-TAPE-1IN', '醫療膠帶 1吋', 'CONSUMABLE', '醫療耗材', '捲', '9.1m/捲'),
('ADHESIVE-TAPE-2IN', '醫療膠帶 2吋', 'CONSUMABLE', '醫療耗材', '捲', '9.1m/捲');

-- Syringes & Needles
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('SYRINGE-1ML', '注射器 1ml', 'CONSUMABLE', '注射用品', '支', '一次性使用'),
('SYRINGE-3ML', '注射器 3ml', 'CONSUMABLE', '注射用品', '支', '一次性使用'),
('SYRINGE-5ML', '注射器 5ml', 'CONSUMABLE', '注射用品', '支', '一次性使用'),
('SYRINGE-10ML', '注射器 10ml', 'CONSUMABLE', '注射用品', '支', '一次性使用'),
('SYRINGE-20ML', '注射器 20ml', 'CONSUMABLE', '注射用品', '支', '一次性使用'),
('NEEDLE-18G', '針頭 18G', 'CONSUMABLE', '注射用品', '支', '1.2x38mm'),
('NEEDLE-20G', '針頭 20G', 'CONSUMABLE', '注射用品', '支', '0.9x38mm'),
('NEEDLE-21G', '針頭 21G', 'CONSUMABLE', '注射用品', '支', '0.8x38mm'),
('NEEDLE-23G', '針頭 23G', 'CONSUMABLE', '注射用品', '支', '0.6x25mm'),
('NEEDLE-25G', '針頭 25G', 'CONSUMABLE', '注射用品', '支', '0.5x16mm'),
('NEEDLE-27G', '針頭 27G', 'CONSUMABLE', '注射用品', '支', '0.4x13mm');

-- IV Supplies
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('IV-SET-STANDARD', '點滴套組 標準型', 'CONSUMABLE', '注射用品', '組', '含調節器'),
('IV-SET-MICRO', '點滴套組 微滴型', 'CONSUMABLE', '注射用品', '組', '60滴/ml'),
('IV-CATH-14G', '靜脈留置針 14G', 'CONSUMABLE', '注射用品', '支', '橘色'),
('IV-CATH-16G', '靜脈留置針 16G', 'CONSUMABLE', '注射用品', '支', '灰色'),
('IV-CATH-18G', '靜脈留置針 18G', 'CONSUMABLE', '注射用品', '支', '綠色'),
('IV-CATH-20G', '靜脈留置針 20G', 'CONSUMABLE', '注射用品', '支', '粉色'),
('IV-CATH-22G', '靜脈留置針 22G', 'CONSUMABLE', '注射用品', '支', '藍色'),
('IV-CATH-24G', '靜脈留置針 24G', 'CONSUMABLE', '注射用品', '支', '黃色');

-- Protective Equipment
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('PPE-MASK-SURGICAL', '外科口罩', 'CONSUMABLE', '防護用品', '盒', '50入/盒'),
('PPE-MASK-N95', 'N95口罩', 'CONSUMABLE', '防護用品', '盒', '20入/盒'),
('PPE-GOWN-ISOLATION', '隔離衣', 'CONSUMABLE', '防護用品', '件', '一次性'),
('PPE-GOWN-SURGICAL', '手術衣', 'CONSUMABLE', '防護用品', '件', '無菌'),
('PPE-FACE-SHIELD', '面罩', 'CONSUMABLE', '防護用品', '個', '可重複使用'),
('PPE-GOGGLES', '護目鏡', 'CONSUMABLE', '防護用品', '個', '防霧'),
('PPE-CAP-DISPOSABLE', '拋棄式頭帽', 'CONSUMABLE', '防護用品', '個', '100入/包'),
('PPE-SHOE-COVER', '鞋套', 'CONSUMABLE', '防護用品', '雙', '100入/包');

-- Disinfection & Sanitation
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('CLEAN-ALCOHOL-75', '75%酒精', 'CONSUMABLE', '清潔用品', '瓶', '500ml'),
('CLEAN-ALCOHOL-95', '95%酒精', 'CONSUMABLE', '清潔用品', '瓶', '500ml'),
('CLEAN-SANITIZER', '乾洗手液', 'CONSUMABLE', '清潔用品', '瓶', '300ml'),
('CLEAN-BLEACH', '漂白水', 'CONSUMABLE', '清潔用品', '瓶', '1000ml'),
('CLEAN-IODINE', '優碘', 'CONSUMABLE', '清潔用品', '瓶', '500ml'),
('CLEAN-CHLORHEXIDINE', 'Chlorhexidine', 'CONSUMABLE', '清潔用品', '瓶', '500ml');

-- ============================================================================
-- MEDICINES - 藥品類 (Basic Emergency Medications)
-- ============================================================================

-- Pain Relief
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('MED-PARACETAMOL-500', 'Paracetamol 500mg', 'CONSUMABLE', '藥品', '顆', '普拿疼'),
('MED-IBUPROFEN-400', 'Ibuprofen 400mg', 'CONSUMABLE', '藥品', '顆', '布洛芬'),
('MED-ASPIRIN-100', 'Aspirin 100mg', 'CONSUMABLE', '藥品', '顆', '阿斯匹靈'),
('MED-MORPHINE-10MG', 'Morphine 10mg/ml', 'CONSUMABLE', '藥品', 'ml', '嗎啡注射液'),
('MED-TRAMADOL-50', 'Tramadol 50mg', 'CONSUMABLE', '藥品', '顆', '曲馬多');

-- Antibiotics
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('MED-AMOXICILLIN-500', 'Amoxicillin 500mg', 'CONSUMABLE', '藥品', '顆', '安莫西林'),
('MED-CEPHALEXIN-500', 'Cephalexin 500mg', 'CONSUMABLE', '藥品', '顆', '頭孢氨苄'),
('MED-AZITHROMYCIN-250', 'Azithromycin 250mg', 'CONSUMABLE', '藥品', '顆', '阿奇黴素'),
('MED-CEFTRIAXONE-1G', 'Ceftriaxone 1g', 'CONSUMABLE', '藥品', '支', '頭孢曲松注射');

-- Emergency Medications
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('MED-EPINEPHRINE-1MG', 'Epinephrine 1mg/ml', 'CONSUMABLE', '藥品', 'ml', '腎上腺素'),
('MED-ATROPINE-1MG', 'Atropine 1mg/ml', 'CONSUMABLE', '藥品', 'ml', '阿托品'),
('MED-LIDOCAINE-2PCT', 'Lidocaine 2%', 'CONSUMABLE', '藥品', 'ml', '利多卡因'),
('MED-DIAZEPAM-5MG', 'Diazepam 5mg', 'CONSUMABLE', '藥品', '顆', '地西泮'),
('MED-NALOXONE-04MG', 'Naloxone 0.4mg/ml', 'CONSUMABLE', '藥品', 'ml', '納洛酮');

-- IV Fluids
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('MED-NS-500ML', 'Normal Saline 0.9% 500ml', 'CONSUMABLE', '藥品', '瓶', '生理食鹽水'),
('MED-NS-1000ML', 'Normal Saline 0.9% 1000ml', 'CONSUMABLE', '藥品', '瓶', '生理食鹽水'),
('MED-D5W-500ML', 'Dextrose 5% 500ml', 'CONSUMABLE', '藥品', '瓶', '5%葡萄糖'),
('MED-LR-500ML', 'Lactated Ringers 500ml', 'CONSUMABLE', '藥品', '瓶', '林格氏液'),
('MED-LR-1000ML', 'Lactated Ringers 1000ml', 'CONSUMABLE', '藥品', '瓶', '林格氏液');

-- ============================================================================
-- EQUIPMENT - 設備類
-- ============================================================================

-- Power & Environmental
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('EQUIP-POWER-STATION', '行動電源站', 'EQUIPMENT', '電力設備', '台', '可充電式'),
('EQUIP-GENERATOR', '備用發電機', 'EQUIPMENT', '電力設備', '台', '汽油發電'),
('EQUIP-PHOTOCATALYST', '光觸媒', 'EQUIPMENT', '空氣淨化', '台', '空氣清淨'),
('EQUIP-WATER-PURIFIER', '淨水器', 'EQUIPMENT', '水處理', '台', 'RO逆滲透'),
('EQUIP-FRIDGE-PORTABLE', '行動冰箱', 'EQUIPMENT', '冷藏設備', '台', '車用12V'),
('EQUIP-FREEZER', '冷凍櫃', 'EQUIPMENT', '冷藏設備', '台', '-20°C'),
('EQUIP-TEMP-MONITOR', '溫濕度監控', 'EQUIPMENT', '監控設備', '台', '藍牙連線');

-- Surgical Instruments (BORP Specific)
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('SURG-ASSET-PKG', 'ASSET包', 'EQUIPMENT', '手術器械', '包', '緊急手術包'),
('SURG-BULLDOG-CLAMP', 'Bull dog血管夾', 'EQUIPMENT', '手術器械', '支', '血管手術'),
('SURG-SCALPEL-HANDLE', '手術刀柄 #3', 'EQUIPMENT', '手術器械', '支', '可重複使用'),
('SURG-SCALPEL-HANDLE4', '手術刀柄 #4', 'EQUIPMENT', '手術器械', '支', '可重複使用'),
('SURG-BLADE-10', '手術刀片 #10', 'CONSUMABLE', '手術器械', '片', '一次性'),
('SURG-BLADE-11', '手術刀片 #11', 'CONSUMABLE', '手術器械', '片', '一次性'),
('SURG-BLADE-15', '手術刀片 #15', 'CONSUMABLE', '手術器械', '片', '一次性'),
('SURG-FORCEPS-ADSON', 'Adson鑷子', 'EQUIPMENT', '手術器械', '支', '有齒/無齒'),
('SURG-FORCEPS-KELLY', 'Kelly止血鉗', 'EQUIPMENT', '手術器械', '支', '直/彎'),
('SURG-SCISSORS-MAYO', 'Mayo剪', 'EQUIPMENT', '手術器械', '支', '直/彎'),
('SURG-RETRACTOR-ARMY', 'Army-Navy拉勾', 'EQUIPMENT', '手術器械', '支', '雙頭'),
('SURG-NEEDLE-HOLDER', '持針器', 'EQUIPMENT', '手術器械', '支', 'Mayo-Hegar'),
('SURG-SUTURE-3-0', '縫線 3-0 Vicryl', 'CONSUMABLE', '手術器械', '包', '可吸收'),
('SURG-SUTURE-4-0', '縫線 4-0 Vicryl', 'CONSUMABLE', '手術器械', '包', '可吸收'),
('SURG-SUTURE-5-0', '縫線 5-0 Nylon', 'CONSUMABLE', '手術器械', '包', '不可吸收');

-- Diagnostic Equipment
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('DIAG-BP-MONITOR', '血壓計', 'EQUIPMENT', '診斷設備', '台', '電子式'),
('DIAG-STETHOSCOPE', '聽診器', 'EQUIPMENT', '診斷設備', '支', 'Littmann'),
('DIAG-THERMOMETER', '體溫計', 'EQUIPMENT', '診斷設備', '支', '額溫槍'),
('DIAG-OXIMETER', '血氧機', 'EQUIPMENT', '診斷設備', '台', '指夾式'),
('DIAG-GLUCOMETER', '血糖機', 'EQUIPMENT', '診斷設備', '台', '含試紙'),
('DIAG-ECG-PORTABLE', '攜帶式心電圖機', 'EQUIPMENT', '診斷設備', '台', '12導程');

-- ============================================================================
-- REAGENTS - 檢驗試劑 (Life-Threatening Condition Related)
-- ============================================================================

-- Cardiac Emergency Reagents
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('REA-TROP-001', '心肌肌鈣蛋白 Troponin I 快篩試劑', 'REAGENT', '檢驗試劑', '組', '25 tests/kit, 心肌梗塞診斷'),
('REA-BNP-001', 'BNP/NT-proBNP 心衰竭試劑', 'REAGENT', '檢驗試劑', '組', '25 tests/kit, 心衰竭診斷');

-- Metabolic Emergency Reagents
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('REA-GLU-001', '血糖試紙', 'REAGENT', '檢驗試劑', '盒', '50 strips/box, DKA/低血糖'),
('REA-ELEC-001', '電解質分析試劑 (Na/K/Cl)', 'REAGENT', '檢驗試劑', '組', '100 tests/kit, 心律不整/脫水'),
('REA-ABG-001', '血液氣體分析卡匣', 'REAGENT', '檢驗試劑', '盒', '25 cartridges/box, 呼吸衰竭');

-- Sepsis/Infection Reagents
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('REA-CBC-001', 'CBC 全血球計數試劑組', 'REAGENT', '檢驗試劑', '組', '100 tests/kit, 28天開封效期'),
('REA-LAC-001', '乳酸 Lactate 試劑', 'REAGENT', '檢驗試劑', '組', '50 tests/kit, 敗血症休克'),
('REA-CRP-001', 'CRP 發炎指數試劑', 'REAGENT', '檢驗試劑', '組', '50 tests/kit, 感染嚴重度'),
('REA-PCT-001', '降鈣素原 Procalcitonin 試劑', 'REAGENT', '檢驗試劑', '組', '25 tests/kit, 細菌感染');

-- Thrombosis/Bleeding Reagents
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('REA-DDIM-001', 'D-Dimer 二聚體試劑', 'REAGENT', '檢驗試劑', '組', '25 tests/kit, 肺栓塞/DVT'),
('REA-COAG-001', 'PT/INR 凝血試劑', 'REAGENT', '檢驗試劑', '組', '50 tests/kit, 出血/抗凝監測');

-- Renal Emergency Reagents
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('REA-URI-001', '尿液分析試紙', 'REAGENT', '檢驗試劑', '盒', '100 strips/box, UTI/腎病/糖尿'),
('REA-CREA-001', '肌酸酐 Creatinine 試劑', 'REAGENT', '檢驗試劑', '組', '50 tests/kit, 急性腎損傷');

-- Rapid Diagnostic Tests
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('REA-FLU-001', '流感快篩試劑 A+B', 'REAGENT', '檢驗試劑', '盒', '25 tests/box'),
('REA-COVID-001', 'COVID-19 快篩試劑', 'REAGENT', '檢驗試劑', '盒', '25 tests/box');

-- ============================================================================
-- RESILIENCE ITEMS - 韌性物資 (Oxygen & Power)
-- ============================================================================

-- Oxygen Supply
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('O2-CYL-E', 'E型氧氣瓶', 'EQUIPMENT', '氧氣供應', '瓶', '680L capacity, 攜帶型'),
('O2-CYL-H', 'H型氧氣瓶', 'EQUIPMENT', '氧氣供應', '瓶', '6900L capacity, 固定式'),
('O2-CYL-D', 'D型氧氣瓶', 'EQUIPMENT', '氧氣供應', '瓶', '400L capacity, 小型'),
('O2-CONC-5L', '氧氣製造機 5L', 'EQUIPMENT', '氧氣供應', '台', '5 L/min, 需電力'),
('O2-CONC-10L', '氧氣製造機 10L', 'EQUIPMENT', '氧氣供應', '台', '10 L/min, 需電力');

-- Generator & Fuel
INSERT OR IGNORE INTO items (item_code, item_name, item_category, category, unit, specification) VALUES
('GEN-FUEL-20L', '發電機油桶 20L', 'CONSUMABLE', '電力設備', '桶', '20L 汽油'),
('GEN-FUEL-10L', '發電機油桶 10L', 'CONSUMABLE', '電力設備', '桶', '10L 汽油'),
('GEN-TANK', '發電機油箱(滿)', 'CONSUMABLE', '電力設備', '次', '約20L, 現有油量');

-- ============================================================================
-- METADATA
-- ============================================================================

-- Track catalog version
CREATE TABLE IF NOT EXISTS catalog_metadata (
    version TEXT PRIMARY KEY,
    item_count INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

INSERT OR REPLACE INTO catalog_metadata (version, item_count, description) VALUES
('1.1.0', 130, 'Added reagents & resilience items - Oxygen/Power/Reagents for endurance calculation');

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- To use this catalog in a station profile:
--
-- 1. Load the catalog (creates items in master list)
-- 2. Station profile selects subset by item_code:
--
--    -- Example: Health Center Profile
--    UPDATE items SET current_stock = 0 WHERE item_code NOT IN (
--        'PPE-GLOVE-M', 'PPE-GLOVE-L',
--        'GAUZE-4X4', 'BAND-2IN',
--        'MED-PARACETAMOL-500', 'MED-IBUPROFEN-400',
--        'EQUIP-POWER-STATION', 'EQUIP-PHOTOCATALYST'
--    );
--
-- 3. Station manager can activate/deactivate items via UI
--
-- ============================================================================
