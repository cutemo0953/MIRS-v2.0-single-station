-- ============================================================================
-- Migration: 麻醉計費完整 Schema
-- Version: 1.2.0
-- Date: 2026-01-20
-- Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md
-- ============================================================================

-- ============================================================================
-- 1. 藥品使用計費事件表 (Medication Usage Events)
-- ============================================================================
CREATE TABLE IF NOT EXISTS medication_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 唯一識別
    idempotency_key TEXT UNIQUE NOT NULL,       -- SHA256(case_id:client_event_uuid)[:32]

    -- 事件類型
    event_type TEXT NOT NULL DEFAULT 'ANESTHESIA_ADMIN',  -- ANESTHESIA_ADMIN, EMERGENCY, NURSE_ADMIN

    -- 藥品資訊
    medicine_code TEXT NOT NULL,
    medicine_name TEXT,

    -- 臨床劑量 (原始記錄)
    clinical_dose REAL NOT NULL,
    clinical_unit TEXT NOT NULL,

    -- 計費數量 (換算後)
    billing_quantity REAL NOT NULL,
    billing_unit TEXT NOT NULL,

    -- 庫存扣減數量 (可能與計費數量不同)
    inventory_deduct_quantity REAL,

    -- 給藥方式
    route TEXT,

    -- 案件關聯
    case_id TEXT,
    patient_id TEXT,

    -- 操作者
    operator_id TEXT NOT NULL,
    station_id TEXT,

    -- 來源追溯
    source_system TEXT NOT NULL,                -- ANESTHESIA_PWA, NURSE_PWA, EMT_PWA
    source_record_id TEXT,                      -- 原始 event_id

    -- 計費狀態
    billing_status TEXT DEFAULT 'PENDING',      -- PENDING, CALCULATED, EXPORTED, VOIDED

    -- 價格凍結 (Section 10.7)
    pricebook_version_id TEXT,
    unit_price_at_event REAL,
    effective_price_date TEXT,
    is_locked INTEGER DEFAULT 0,

    -- VOID 支援 (Section 10.8)
    is_voided INTEGER DEFAULT 0,
    voided_by TEXT,
    voided_at DATETIME,
    voided_reason TEXT,
    void_reference_id TEXT,                     -- 指向原事件

    -- 時間戳
    event_timestamp DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 約束
    CHECK(event_type IN ('ANESTHESIA_ADMIN', 'EMERGENCY', 'NURSE_ADMIN', 'VOID_REVERSAL')),
    CHECK(billing_status IN ('PENDING', 'CALCULATED', 'EXPORTED', 'VOIDED'))
);

CREATE INDEX IF NOT EXISTS idx_med_usage_case ON medication_usage_events(case_id);
CREATE INDEX IF NOT EXISTS idx_med_usage_status ON medication_usage_events(billing_status);
CREATE INDEX IF NOT EXISTS idx_med_usage_medicine ON medication_usage_events(medicine_code);
CREATE INDEX IF NOT EXISTS idx_med_usage_idempotency ON medication_usage_events(idempotency_key);

-- ============================================================================
-- 2. 麻醉處置費計費事件表 (Anesthesia Billing Events)
-- ============================================================================
CREATE TABLE IF NOT EXISTS anesthesia_billing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 唯一識別
    billing_id TEXT UNIQUE NOT NULL,
    case_id TEXT NOT NULL,

    -- ASA 分級
    asa_class INTEGER NOT NULL,                 -- 1-6
    asa_emergency INTEGER DEFAULT 0,            -- 是否急診 (E)

    -- 麻醉技術
    anesthesia_technique TEXT NOT NULL,         -- GA_ETT, GA_LMA, RA_SPINAL, etc.

    -- 時間計算
    anesthesia_start_time DATETIME,
    anesthesia_end_time DATETIME,
    anesthesia_duration_minutes INTEGER,

    -- 特殊技術 (JSON array)
    special_techniques TEXT,                    -- ["FIBER_OPTIC", "TEE", "NERVE_BLOCK"]

    -- 費用計算
    base_fee REAL DEFAULT 0,                    -- 基本費
    time_fee REAL DEFAULT 0,                    -- 時間加成
    asa_fee REAL DEFAULT 0,                     -- ASA 加成
    technique_fee REAL DEFAULT 0,               -- 特殊技術費
    emergency_fee REAL DEFAULT 0,               -- 急診加成
    total_fee REAL DEFAULT 0,

    -- 費率版本
    fee_schedule_version TEXT,

    -- 計費狀態
    billing_status TEXT DEFAULT 'PENDING',

    -- 時間戳
    calculated_at DATETIME,
    exported_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 約束
    CHECK(asa_class BETWEEN 1 AND 6),
    CHECK(billing_status IN ('PENDING', 'CALCULATED', 'EXPORTED', 'VOIDED'))
);

CREATE INDEX IF NOT EXISTS idx_anes_billing_case ON anesthesia_billing_events(case_id);
CREATE INDEX IF NOT EXISTS idx_anes_billing_status ON anesthesia_billing_events(billing_status);

-- ============================================================================
-- 3. 手術處置費計費事件表 (Surgical Billing Events)
-- ============================================================================
CREATE TABLE IF NOT EXISTS surgical_billing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 唯一識別
    billing_id TEXT UNIQUE NOT NULL,
    case_id TEXT NOT NULL,

    -- 手術資訊
    surgery_code TEXT,                          -- NHI 手術碼
    surgery_name TEXT,

    -- 手術時間
    surgery_start_time DATETIME,
    surgery_end_time DATETIME,
    surgery_duration_minutes INTEGER,

    -- 人員
    surgeon_id TEXT,
    assistant_ids TEXT,                         -- JSON array

    -- 費用計算
    surgeon_fee REAL DEFAULT 0,
    assistant_fee REAL DEFAULT 0,
    total_fee REAL DEFAULT 0,

    -- 費率版本
    fee_schedule_version TEXT,

    -- 計費狀態
    billing_status TEXT DEFAULT 'PENDING',

    -- 時間戳
    calculated_at DATETIME,
    exported_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CHECK(billing_status IN ('PENDING', 'CALCULATED', 'EXPORTED', 'VOIDED'))
);

CREATE INDEX IF NOT EXISTS idx_surg_billing_case ON surgical_billing_events(case_id);

-- ============================================================================
-- 4. 麻醉費率表 (Anesthesia Fee Schedule)
-- ============================================================================
CREATE TABLE IF NOT EXISTS anesthesia_fee_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    schedule_version TEXT NOT NULL,
    effective_date DATE NOT NULL,

    -- 基本費
    base_fee_ga REAL DEFAULT 3000,              -- 全身麻醉基本費
    base_fee_ra REAL DEFAULT 2000,              -- 區域麻醉基本費
    base_fee_sedation REAL DEFAULT 1500,        -- 鎮靜麻醉基本費

    -- 時間加成 (每30分鐘)
    time_fee_per_30min REAL DEFAULT 500,
    time_fee_start_after_minutes INTEGER DEFAULT 60,  -- 超過60分鐘開始計時

    -- ASA 加成
    asa_3_multiplier REAL DEFAULT 1.2,
    asa_4_multiplier REAL DEFAULT 1.5,
    asa_5_multiplier REAL DEFAULT 2.0,

    -- 急診加成
    emergency_multiplier REAL DEFAULT 1.3,

    -- 特殊技術費
    technique_fiber_optic REAL DEFAULT 2000,
    technique_tee REAL DEFAULT 3000,
    technique_nerve_block REAL DEFAULT 1500,
    technique_arterial_line REAL DEFAULT 800,
    technique_cvp REAL DEFAULT 1200,

    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 插入預設費率
INSERT OR IGNORE INTO anesthesia_fee_schedule (
    schedule_version, effective_date
) VALUES ('v1.0', '2026-01-01');

-- ============================================================================
-- 5. 麻醉藥車表 (Anesthesia Carts) - Phase 7
-- ============================================================================
CREATE TABLE IF NOT EXISTS anesthesia_carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cart_id TEXT UNIQUE NOT NULL,
    cart_name TEXT NOT NULL,
    cart_location TEXT,

    -- 狀態
    status TEXT DEFAULT 'ACTIVE',               -- ACTIVE, INACTIVE, MAINTENANCE

    -- 負責人
    assigned_to TEXT,
    assigned_at DATETIME,

    -- 最後清點
    last_inventory_check DATETIME,
    last_checked_by TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CHECK(status IN ('ACTIVE', 'INACTIVE', 'MAINTENANCE'))
);

-- ============================================================================
-- 6. 藥車庫存表 (Cart Inventory) - Phase 7
-- ============================================================================
CREATE TABLE IF NOT EXISTS cart_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cart_id TEXT NOT NULL,
    medicine_code TEXT NOT NULL,

    -- 數量
    quantity INTEGER NOT NULL DEFAULT 0,
    min_quantity INTEGER DEFAULT 2,
    max_quantity INTEGER DEFAULT 10,

    -- 批號效期
    batch_number TEXT,
    expiry_date DATE,

    -- 最後補充
    last_replenished_at DATETIME,
    last_replenished_by TEXT,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cart_id) REFERENCES anesthesia_carts(cart_id),
    FOREIGN KEY (medicine_code) REFERENCES medicines(medicine_code),
    UNIQUE(cart_id, medicine_code)
);

CREATE INDEX IF NOT EXISTS idx_cart_inv_cart ON cart_inventory(cart_id);
CREATE INDEX IF NOT EXISTS idx_cart_inv_medicine ON cart_inventory(medicine_code);

-- ============================================================================
-- 7. 藥車調撥記錄表 (Cart Dispatch Records) - Phase 7
-- ============================================================================
CREATE TABLE IF NOT EXISTS cart_dispatch_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    dispatch_id TEXT UNIQUE NOT NULL,

    -- 類型
    dispatch_type TEXT NOT NULL,                -- REPLENISH, RETURN, HANDOFF

    -- 來源/目標
    from_location TEXT NOT NULL,                -- 'PHARMACY' or cart_id
    to_location TEXT NOT NULL,                  -- cart_id or 'PHARMACY'

    -- 內容 (JSON)
    items TEXT NOT NULL,                        -- [{"medicine_code": "...", "quantity": 5}]

    -- 操作者
    dispatcher_id TEXT NOT NULL,
    receiver_id TEXT,
    receiver_verified_at DATETIME,

    -- 藥師核對
    pharmacist_id TEXT,
    pharmacist_verified_at DATETIME,

    -- 狀態
    status TEXT DEFAULT 'PENDING',              -- PENDING, IN_TRANSIT, RECEIVED, VERIFIED

    -- 差異報告
    discrepancy_report TEXT,                    -- JSON if any discrepancy

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CHECK(dispatch_type IN ('REPLENISH', 'RETURN', 'HANDOFF')),
    CHECK(status IN ('PENDING', 'IN_TRANSIT', 'RECEIVED', 'VERIFIED'))
);

CREATE INDEX IF NOT EXISTS idx_cart_dispatch_status ON cart_dispatch_records(status);
CREATE INDEX IF NOT EXISTS idx_cart_dispatch_cart ON cart_dispatch_records(to_location);

-- ============================================================================
-- 8. Triggers
-- ============================================================================

-- 禁止修改已鎖定的計費記錄
CREATE TRIGGER IF NOT EXISTS prevent_locked_med_usage_update
BEFORE UPDATE ON medication_usage_events
WHEN OLD.is_locked = 1 AND NEW.is_voided = 0
BEGIN
    SELECT RAISE(ABORT, 'Cannot modify locked billing record. Use VOID pattern.');
END;

-- EXPORTED 後自動鎖定
CREATE TRIGGER IF NOT EXISTS lock_med_usage_on_export
AFTER UPDATE ON medication_usage_events
WHEN NEW.billing_status = 'EXPORTED' AND OLD.billing_status != 'EXPORTED'
BEGIN
    UPDATE medication_usage_events SET is_locked = 1 WHERE id = NEW.id;
END;

-- ============================================================================
-- 9. 更新 schema version
-- ============================================================================
UPDATE station_metadata SET schema_version = '1.7.0' WHERE station_code IS NOT NULL;

-- ============================================================================
-- 完成
-- ============================================================================
