-- ============================================================================
-- 藥局資料庫 Schema (Pharmacy Database)
-- Version: 1.5.0
-- 用途: 藥品、管制藥品管理
-- ============================================================================

-- ============================================================================
-- 1. 站點後設資料表 (Station Metadata) - 與 general_inventory 同步
-- ============================================================================
CREATE TABLE IF NOT EXISTS station_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 基本資訊
    station_uuid TEXT UNIQUE,                    -- 站點全域唯一識別碼
    station_code TEXT NOT NULL UNIQUE,           -- 站點代碼 (如: TC-01)
    station_name TEXT NOT NULL,                  -- 站點名稱

    -- 站點分類
    station_type TEXT NOT NULL,                  -- 站點類型: FIRST_CLASS, SECOND_CLASS, THIRD_CLASS_BORP
    admin_level TEXT NOT NULL,                   -- 管理層級: STATION_LOCAL, DISTRICT, COUNTY, MOHW
    parent_node TEXT,                            -- 上級節點站點代碼

    -- 組織資訊
    organization_code TEXT,                      -- 組織代碼
    organization_name TEXT,                      -- 組織名稱
    region_code TEXT,                            -- 區域代碼
    region_name TEXT,                            -- 區域名稱

    -- 能力配置（藥局特定）
    beds INTEGER DEFAULT 0,                      -- 床位數
    daily_capacity INTEGER DEFAULT 0,            -- 每日門診量
    has_pharmacy BOOLEAN DEFAULT 1,              -- 是否有藥局（藥局DB預設為1）
    has_surgery BOOLEAN DEFAULT 0,               -- 是否有手術室
    has_emergency BOOLEAN DEFAULT 0,             -- 是否有急診
    storage_capacity_m3 REAL DEFAULT 0,          -- 儲存空間（立方公尺）

    -- 藥局認證
    pharmacy_license TEXT,                       -- 藥局執照號碼
    pharmacist_license TEXT,                     -- 藥師執照號碼
    controlled_drug_permit TEXT,                 -- 管制藥品許可證號碼
    permit_expiry_date DATE,                     -- 許可證效期

    -- 狀態與時間戳
    status TEXT DEFAULT 'ACTIVE',                -- 狀態: ACTIVE, INACTIVE, MAINTENANCE
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_sync_at TIMESTAMP,                      -- 最後同步時間

    -- 版本控制
    schema_version TEXT DEFAULT '1.5.0',
    data_version INTEGER DEFAULT 1,

    -- 索引
    CHECK (station_type IN ('FIRST_CLASS', 'SECOND_CLASS', 'THIRD_CLASS_BORP')),
    CHECK (admin_level IN ('STATION_LOCAL', 'DISTRICT', 'COUNTY', 'MOHW')),
    CHECK (status IN ('ACTIVE', 'INACTIVE', 'MAINTENANCE'))
);

CREATE INDEX IF NOT EXISTS idx_pharm_station_code ON station_metadata(station_code);
CREATE INDEX IF NOT EXISTS idx_pharm_station_type ON station_metadata(station_type);

-- ============================================================================
-- 2. 藥品主檔表 (Medicines Master)
-- ============================================================================
CREATE TABLE IF NOT EXISTS medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 基本資訊
    medicine_code TEXT NOT NULL UNIQUE,          -- 藥品代碼
    generic_name TEXT NOT NULL,                  -- 學名（重點欄位）
    brand_name TEXT,                             -- 商品名（重點欄位）
    medicine_name_en TEXT,                       -- 英文名稱

    -- 劑型與劑量
    dosage_form TEXT NOT NULL,                   -- 劑型（重點欄位）: TABLET（錠劑）, CAPSULE（膠囊）, INJECTION（注射劑）, SYRUP（糖漿）, CREAM（藥膏）等
    strength TEXT NOT NULL,                      -- 劑量強度（重點欄位）: 如 "500mg", "10mg/ml"
    strength_value REAL,                         -- 劑量數值
    strength_unit TEXT,                          -- 劑量單位

    -- 分類與編碼
    atc_code TEXT,                               -- ATC 分類碼（重點欄位）
    therapeutic_class TEXT,                      -- 治療分類
    pharmacological_class TEXT,                  -- 藥理分類

    -- 管制藥品資訊（重點欄位）
    is_controlled_drug BOOLEAN DEFAULT 0,        -- 是否為管制藥品（重點欄位）
    controlled_level TEXT,                       -- 管制等級（重點欄位）: LEVEL_1, LEVEL_2, LEVEL_3, LEVEL_4, NULL
    dea_schedule TEXT,                           -- DEA 管制級別（國際參考）

    -- 處方管理
    requires_prescription BOOLEAN DEFAULT 1,     -- 是否需處方
    prescription_type TEXT,                      -- 處方類型: REGULAR, CONTROLLED, OTC
    max_daily_dose REAL,                         -- 最大日劑量
    max_single_dose REAL,                        -- 最大單次劑量

    -- 規格與包裝
    specification TEXT,                          -- 規格說明
    package_type TEXT,                           -- 包裝類型
    package_size INTEGER DEFAULT 1,              -- 包裝數量
    unit TEXT NOT NULL DEFAULT '顆',             -- 單位

    -- 儲存條件
    storage_location TEXT,                       -- 儲存位置
    storage_temp_min REAL,                       -- 最低儲存溫度（℃）
    storage_temp_max REAL,                       -- 最高儲存溫度（℃）
    storage_humidity_max INTEGER,                -- 最高儲存濕度（%）
    requires_refrigeration BOOLEAN DEFAULT 0,    -- 是否需冷藏
    requires_freezing BOOLEAN DEFAULT 0,         -- 是否需冷凍
    light_sensitive BOOLEAN DEFAULT 0,           -- 是否避光

    -- 庫存管理
    baseline_qty_7days INTEGER DEFAULT 0,        -- 7天標準儲備量
    min_stock INTEGER DEFAULT 0,                 -- 最低庫存量
    max_stock INTEGER DEFAULT 0,                 -- 最高庫存量
    reorder_point INTEGER DEFAULT 0,             -- 再訂購點
    current_stock INTEGER DEFAULT 0,             -- 當前庫存
    reserved_stock INTEGER DEFAULT 0,            -- 保留庫存
    available_stock INTEGER GENERATED ALWAYS AS (current_stock - reserved_stock) VIRTUAL,

    -- 供應商資訊
    supplier_code TEXT,                          -- 供應商代碼
    supplier_name TEXT,                          -- 供應商名稱
    manufacturer TEXT,                           -- 製造商
    country_of_origin TEXT,                      -- 產地
    import_drug_permit TEXT,                     -- 藥品輸入許可證號

    -- 成本與價格
    unit_cost REAL DEFAULT 0,                    -- 單位成本
    unit_price REAL DEFAULT 0,                   -- 單位售價
    nhi_price REAL DEFAULT 0,                    -- 健保價
    currency TEXT DEFAULT 'TWD',                 -- 幣別

    -- 效期管理
    has_expiry BOOLEAN DEFAULT 1,                -- 是否有效期（藥品預設有效期）
    default_shelf_life_days INTEGER,             -- 預設保存期限（天）
    nearest_expiry_date DATE,                    -- 最近效期

    -- 追溯與標籤
    barcode TEXT,                                -- 條碼
    qr_code TEXT,                                -- QR Code
    lot_number TEXT,                             -- 批號
    is_traceable BOOLEAN DEFAULT 1,              -- 是否需追溯（藥品預設需追溯）

    -- 藥品許可
    drug_permit_number TEXT,                     -- 藥品許可證號
    permit_holder TEXT,                          -- 許可證持有者
    permit_expiry_date DATE,                     -- 許可證效期

    -- 用藥安全
    is_high_alert BOOLEAN DEFAULT 0,             -- 是否為高警訊藥品
    is_lasa BOOLEAN DEFAULT 0,                   -- 是否為 LASA（外觀/音似藥品）
    requires_double_check BOOLEAN DEFAULT 0,     -- 是否需雙人核對
    black_box_warning TEXT,                      -- 黑框警語

    -- 適應症與禁忌
    indications TEXT,                            -- 適應症
    contraindications TEXT,                      -- 禁忌症
    side_effects TEXT,                           -- 副作用
    drug_interactions TEXT,                      -- 藥物交互作用

    -- 狀態與標記
    is_active BOOLEAN DEFAULT 1,                 -- 是否啟用
    is_critical BOOLEAN DEFAULT 0,               -- 是否為關鍵藥品
    is_emergency_stock BOOLEAN DEFAULT 0,        -- 是否為緊急備用藥

    -- 備註
    description TEXT,                            -- 描述
    usage_instructions TEXT,                     -- 用法說明
    storage_notes TEXT,                          -- 儲存說明
    remarks TEXT,                                -- 備註

    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    updated_by TEXT,

    -- 約束
    CHECK (dosage_form IN ('TABLET', 'CAPSULE', 'INJECTION', 'SYRUP', 'CREAM', 'OINTMENT', 'SUPPOSITORY', 'PATCH', 'INHALER', 'DROPS', 'POWDER', 'SOLUTION', 'SUSPENSION')),
    CHECK (controlled_level IN ('LEVEL_1', 'LEVEL_2', 'LEVEL_3', 'LEVEL_4') OR controlled_level IS NULL),
    CHECK (prescription_type IN ('REGULAR', 'CONTROLLED', 'OTC')),
    CHECK (current_stock >= 0),
    CHECK (reserved_stock >= 0),
    CHECK (unit_cost >= 0),
    CHECK (unit_price >= 0)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_medicine_code ON medicines(medicine_code);
CREATE INDEX IF NOT EXISTS idx_generic_name ON medicines(generic_name);
CREATE INDEX IF NOT EXISTS idx_brand_name ON medicines(brand_name);
CREATE INDEX IF NOT EXISTS idx_atc_code ON medicines(atc_code);
CREATE INDEX IF NOT EXISTS idx_dosage_form ON medicines(dosage_form);
CREATE INDEX IF NOT EXISTS idx_is_controlled ON medicines(is_controlled_drug);
CREATE INDEX IF NOT EXISTS idx_controlled_level ON medicines(controlled_level);
CREATE INDEX IF NOT EXISTS idx_is_active_med ON medicines(is_active);
CREATE INDEX IF NOT EXISTS idx_barcode_med ON medicines(barcode);

-- ============================================================================
-- 3. 藥品交易記錄表 (Pharmacy Transactions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pharmacy_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 交易基本資訊
    transaction_id TEXT NOT NULL UNIQUE,         -- 交易唯一識別碼
    transaction_type TEXT NOT NULL,              -- 交易類型: IN（入庫）, OUT（出庫）, DISPENSE（調劑）, TRANSFER（調撥）, ADJUST（調整）, RETURN（退貨）, DESTROY（銷毀）
    transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 藥品資訊
    medicine_code TEXT NOT NULL,                 -- 藥品代碼
    generic_name TEXT NOT NULL,                  -- 學名
    brand_name TEXT,                             -- 商品名
    dosage_form TEXT,                            -- 劑型
    strength TEXT,                               -- 劑量強度

    -- 管制藥品標記
    is_controlled_drug BOOLEAN DEFAULT 0,        -- 是否為管制藥品
    controlled_level TEXT,                       -- 管制等級

    -- 數量與單位
    quantity INTEGER NOT NULL,                   -- 數量
    unit TEXT NOT NULL,                          -- 單位

    -- 站點資訊
    station_code TEXT NOT NULL,                  -- 站點代碼
    from_station TEXT,                           -- 來源站點（調撥用）
    to_station TEXT,                             -- 目標站點（調撥用）

    -- 批次與效期
    batch_number TEXT,                           -- 批號
    lot_number TEXT,                             -- 批次號
    expiry_date DATE,                            -- 效期

    -- 處方資訊
    prescription_id TEXT,                        -- 處方ID
    prescriber_id TEXT,                          -- 處方醫師ID
    prescriber_name TEXT,                        -- 處方醫師姓名
    patient_id TEXT,                             -- 病患ID
    patient_name TEXT,                           -- 病患姓名

    -- 成本與價格
    unit_cost REAL DEFAULT 0,                    -- 單位成本
    total_cost REAL GENERATED ALWAYS AS (quantity * unit_cost) VIRTUAL,

    -- 儲存位置
    storage_location TEXT,                       -- 儲存位置

    -- 原因與用途
    reason TEXT,                                 -- 交易原因
    purpose TEXT,                                -- 用途
    destruction_reason TEXT,                     -- 銷毀原因（銷毀時）

    -- 參考資料
    reference_doc TEXT,                          -- 參考單據號碼
    related_transaction_id TEXT,                 -- 關聯交易ID

    -- 操作者資訊（重點欄位）
    operator TEXT NOT NULL,                      -- 操作人員
    operator_role TEXT,                          -- 操作人員角色（重點欄位）: PHARMACIST, PHARMACY_ASSISTANT, NURSE, DOCTOR
    verified_by TEXT,                            -- 核對人員（重點欄位）- 管制藥需雙人核對
    approved_by TEXT,                            -- 核准人員

    -- 核對時間
    verified_at TIMESTAMP,                       -- 核對時間

    -- 狀態
    status TEXT DEFAULT 'COMPLETED',             -- 狀態: PENDING, COMPLETED, CANCELLED, REVERSED

    -- 備註
    remarks TEXT,                                -- 備註

    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,

    -- 外鍵
    FOREIGN KEY (medicine_code) REFERENCES medicines(medicine_code) ON DELETE RESTRICT,

    -- 約束
    CHECK (transaction_type IN ('IN', 'OUT', 'DISPENSE', 'TRANSFER', 'ADJUST', 'RETURN', 'DESTROY')),
    CHECK (operator_role IN ('PHARMACIST', 'PHARMACY_ASSISTANT', 'NURSE', 'DOCTOR', 'TECHNICIAN')),
    CHECK (quantity > 0),
    CHECK (status IN ('PENDING', 'COMPLETED', 'CANCELLED', 'REVERSED'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_pharm_trans_id ON pharmacy_transactions(transaction_id);
CREATE INDEX IF NOT EXISTS idx_pharm_trans_type ON pharmacy_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_pharm_trans_date ON pharmacy_transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_pharm_medicine_code ON pharmacy_transactions(medicine_code);
CREATE INDEX IF NOT EXISTS idx_pharm_station_code ON pharmacy_transactions(station_code);
CREATE INDEX IF NOT EXISTS idx_pharm_is_controlled ON pharmacy_transactions(is_controlled_drug);
CREATE INDEX IF NOT EXISTS idx_pharm_operator ON pharmacy_transactions(operator);
CREATE INDEX IF NOT EXISTS idx_pharm_verified_by ON pharmacy_transactions(verified_by);
CREATE INDEX IF NOT EXISTS idx_pharm_status ON pharmacy_transactions(status);
CREATE INDEX IF NOT EXISTS idx_prescription_id ON pharmacy_transactions(prescription_id);

-- ============================================================================
-- 4. 管制藥品登記簿 (Controlled Drug Log)
-- ============================================================================
CREATE TABLE IF NOT EXISTS controlled_drug_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 基本資訊
    log_id TEXT NOT NULL UNIQUE,                 -- 登記唯一識別碼
    log_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,-- 登記時間

    -- 藥品資訊
    medicine_code TEXT NOT NULL,                 -- 藥品代碼
    generic_name TEXT NOT NULL,                  -- 學名
    brand_name TEXT,                             -- 商品名
    controlled_level TEXT NOT NULL,              -- 管制等級（重點欄位）
    dosage_form TEXT,                            -- 劑型
    strength TEXT,                               -- 劑量強度

    -- 交易類型
    transaction_type TEXT NOT NULL,              -- 交易類型: IN, OUT, DISPENSE, TRANSFER, ADJUST, DESTROY
    transaction_id TEXT,                         -- 關聯的交易ID

    -- 數量變動
    quantity INTEGER NOT NULL,                   -- 異動數量
    unit TEXT NOT NULL,                          -- 單位
    balance_before INTEGER NOT NULL,             -- 異動前結存（重點欄位）
    balance_after INTEGER NOT NULL,              -- 異動後結存（重點欄位）

    -- 站點資訊
    station_code TEXT NOT NULL,                  -- 站點代碼
    from_station TEXT,                           -- 來源站點
    to_station TEXT,                             -- 目標站點

    -- 批次與效期
    batch_number TEXT,                           -- 批號
    lot_number TEXT,                             -- 批次號
    expiry_date DATE,                            -- 效期

    -- 處方與病患資訊
    prescription_id TEXT,                        -- 處方ID
    prescriber_id TEXT,                          -- 處方醫師ID
    prescriber_name TEXT,                        -- 處方醫師姓名
    prescriber_license TEXT,                     -- 醫師執照號碼
    patient_id TEXT,                             -- 病患ID（已去識別化）
    patient_name_masked TEXT,                    -- 病患姓名（遮罩）

    -- 用途與原因
    purpose TEXT,                                -- 用途
    reason TEXT,                                 -- 原因
    destruction_method TEXT,                     -- 銷毀方式（銷毀時）
    destruction_witness TEXT,                    -- 銷毀見證人（銷毀時）

    -- 操作與核對人員（重點欄位）
    operator TEXT NOT NULL,                      -- 操作人員
    operator_license TEXT,                       -- 操作人員執照號碼
    operator_role TEXT NOT NULL,                 -- 操作人員角色
    verified_by TEXT NOT NULL,                   -- 核對人員（重點欄位）- 必填
    verified_by_license TEXT,                    -- 核對人員執照號碼
    verified_at TIMESTAMP,                       -- 核對時間
    approved_by TEXT,                            -- 核准人員
    approved_at TIMESTAMP,                       -- 核准時間

    -- 儲存位置
    storage_location TEXT,                       -- 儲存位置（需詳細記錄）

    -- 文件與證明
    reference_doc TEXT,                          -- 參考單據
    permit_number TEXT,                          -- 許可證號碼
    authority_notification TEXT,                 -- 主管機關通報編號

    -- 稽核追蹤
    audit_trail TEXT,                            -- 稽核軌跡（JSON格式）
    is_audited BOOLEAN DEFAULT 0,                -- 是否已稽核
    audited_by TEXT,                             -- 稽核人員
    audited_at TIMESTAMP,                        -- 稽核時間

    -- 異常標記
    is_discrepancy BOOLEAN DEFAULT 0,            -- 是否有差異
    discrepancy_reason TEXT,                     -- 差異原因
    resolved BOOLEAN DEFAULT 0,                  -- 是否已解決
    resolved_by TEXT,                            -- 解決人員
    resolved_at TIMESTAMP,                       -- 解決時間

    -- 備註
    remarks TEXT,                                -- 備註
    confidential_notes TEXT,                     -- 機密備註（加密儲存）

    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,

    -- 外鍵
    FOREIGN KEY (medicine_code) REFERENCES medicines(medicine_code) ON DELETE RESTRICT,
    FOREIGN KEY (transaction_id) REFERENCES pharmacy_transactions(transaction_id) ON DELETE SET NULL,

    -- 約束
    CHECK (controlled_level IN ('LEVEL_1', 'LEVEL_2', 'LEVEL_3', 'LEVEL_4')),
    CHECK (transaction_type IN ('IN', 'OUT', 'DISPENSE', 'TRANSFER', 'ADJUST', 'DESTROY')),
    CHECK (operator_role IN ('PHARMACIST', 'PHARMACY_ASSISTANT', 'NURSE', 'DOCTOR')),
    CHECK (balance_after = balance_before + CASE WHEN transaction_type IN ('IN') THEN quantity ELSE -quantity END)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_ctrl_log_id ON controlled_drug_log(log_id);
CREATE INDEX IF NOT EXISTS idx_ctrl_medicine_code ON controlled_drug_log(medicine_code);
CREATE INDEX IF NOT EXISTS idx_ctrl_controlled_level ON controlled_drug_log(controlled_level);
CREATE INDEX IF NOT EXISTS idx_ctrl_log_date ON controlled_drug_log(log_date);
CREATE INDEX IF NOT EXISTS idx_ctrl_transaction_type ON controlled_drug_log(transaction_type);
CREATE INDEX IF NOT EXISTS idx_ctrl_station_code ON controlled_drug_log(station_code);
CREATE INDEX IF NOT EXISTS idx_ctrl_operator ON controlled_drug_log(operator);
CREATE INDEX IF NOT EXISTS idx_ctrl_verified_by ON controlled_drug_log(verified_by);
CREATE INDEX IF NOT EXISTS idx_ctrl_prescription_id ON controlled_drug_log(prescription_id);
CREATE INDEX IF NOT EXISTS idx_ctrl_is_discrepancy ON controlled_drug_log(is_discrepancy);

-- ============================================================================
-- 觸發器 (Triggers)
-- ============================================================================

-- 更新 medicines 的 updated_at
CREATE TRIGGER IF NOT EXISTS update_medicines_timestamp
AFTER UPDATE ON medicines
FOR EACH ROW
BEGIN
    UPDATE medicines SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- 更新 station_metadata 的 updated_at
CREATE TRIGGER IF NOT EXISTS update_pharm_station_metadata_timestamp
AFTER UPDATE ON station_metadata
FOR EACH ROW
BEGIN
    UPDATE station_metadata SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- 管制藥品交易自動記錄到登記簿
CREATE TRIGGER IF NOT EXISTS auto_log_controlled_drug
AFTER INSERT ON pharmacy_transactions
FOR EACH ROW
WHEN NEW.is_controlled_drug = 1
BEGIN
    INSERT INTO controlled_drug_log (
        log_id, medicine_code, generic_name, brand_name, controlled_level,
        dosage_form, strength, transaction_type, transaction_id,
        quantity, unit, station_code, from_station, to_station,
        batch_number, lot_number, expiry_date,
        prescription_id, prescriber_id, prescriber_name,
        patient_id, purpose, reason,
        operator, operator_role, verified_by,
        balance_before, balance_after,
        storage_location, reference_doc, remarks,
        created_by
    ) SELECT
        'LOG-' || NEW.transaction_id,
        NEW.medicine_code, NEW.generic_name, NEW.brand_name, NEW.controlled_level,
        NEW.dosage_form, NEW.strength, NEW.transaction_type, NEW.transaction_id,
        NEW.quantity, NEW.unit, NEW.station_code, NEW.from_station, NEW.to_station,
        NEW.batch_number, NEW.lot_number, NEW.expiry_date,
        NEW.prescription_id, NEW.prescriber_id, NEW.prescriber_name,
        NEW.patient_id, NEW.purpose, NEW.reason,
        NEW.operator, NEW.operator_role, NEW.verified_by,
        -- Calculate balance_before: get current stock after the transaction, then subtract the change
        CASE
            WHEN NEW.transaction_type IN ('IN', 'RETURN') THEN m.current_stock - NEW.quantity
            WHEN NEW.transaction_type IN ('OUT', 'DISPENSE', 'TRANSFER', 'DESTROY') THEN m.current_stock + NEW.quantity
            ELSE m.current_stock
        END as balance_before,
        m.current_stock as balance_after,
        NEW.storage_location, NEW.reference_doc, NEW.remarks,
        NEW.created_by
    FROM medicines m
    WHERE m.medicine_code = NEW.medicine_code;
END;

-- ============================================================================
-- 初始資料 (Initial Data)
-- ============================================================================

-- 插入預設站點資料（如果不存在）- 與 general_inventory 同步
INSERT OR IGNORE INTO station_metadata (
    station_code, station_name, station_type, admin_level,
    organization_code, organization_name, region_code, region_name,
    beds, daily_capacity, has_pharmacy, has_surgery, has_emergency,
    storage_capacity_m3, status
) VALUES (
    'TC-01', '前線醫療站01', 'THIRD_CLASS_BORP', 'STATION_LOCAL',
    'DNO', 'De Novo Orthopedics', 'TC', '桃園地區',
    20, 50, 1, 0, 1,
    20.0, 'ACTIVE'
);

-- ============================================================================
-- 視圖 (Views)
-- ============================================================================

-- 藥品庫存狀態視圖
CREATE VIEW IF NOT EXISTS v_medicine_inventory_status AS
SELECT
    m.medicine_code,
    m.generic_name,
    m.brand_name,
    m.dosage_form,
    m.strength,
    m.is_controlled_drug,
    m.controlled_level,
    m.unit,
    m.current_stock,
    m.reserved_stock,
    m.available_stock,
    m.baseline_qty_7days,
    m.min_stock,
    m.reorder_point,
    CASE
        WHEN m.current_stock <= 0 THEN 'OUT_OF_STOCK'
        WHEN m.current_stock <= m.min_stock THEN 'LOW_STOCK'
        WHEN m.current_stock <= m.reorder_point THEN 'REORDER'
        ELSE 'NORMAL'
    END AS stock_status,
    m.nearest_expiry_date,
    m.is_active,
    m.is_critical,
    m.is_high_alert
FROM medicines m
WHERE m.is_active = 1;

-- 管制藥品庫存監控視圖
CREATE VIEW IF NOT EXISTS v_controlled_drug_inventory AS
SELECT
    m.medicine_code,
    m.generic_name,
    m.brand_name,
    m.controlled_level,
    m.dosage_form,
    m.strength,
    m.current_stock,
    m.min_stock,
    m.storage_location,
    m.nearest_expiry_date,
    (
        SELECT COUNT(*)
        FROM controlled_drug_log cdl
        WHERE cdl.medicine_code = m.medicine_code
        AND DATE(cdl.log_date) = DATE('now')
    ) AS today_transactions
FROM medicines m
WHERE m.is_controlled_drug = 1 AND m.is_active = 1;

-- 藥品交易統計視圖
CREATE VIEW IF NOT EXISTS v_pharmacy_transaction_summary AS
SELECT
    pt.station_code,
    pt.transaction_type,
    pt.operator_role,
    DATE(pt.transaction_date) AS transaction_date,
    COUNT(*) AS transaction_count,
    SUM(pt.quantity) AS total_quantity,
    SUM(pt.total_cost) AS total_cost,
    SUM(CASE WHEN pt.is_controlled_drug = 1 THEN 1 ELSE 0 END) AS controlled_drug_count
FROM pharmacy_transactions pt
WHERE pt.status = 'COMPLETED'
GROUP BY pt.station_code, pt.transaction_type, pt.operator_role, DATE(pt.transaction_date);

-- ============================================================================
-- 結束
-- ============================================================================
