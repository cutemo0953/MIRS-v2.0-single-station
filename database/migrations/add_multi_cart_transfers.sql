-- ============================================================================
-- Migration: Multi-Cart & Drug Transfer System
-- Version: 1.1.0
-- Date: 2026-01-21
-- Reference: DEV_SPEC_MULTI_CART_DRUG_TRANSFER_v1.1.md
-- ============================================================================

-- ============================================================================
-- 1. 藥車類型定義表
-- ============================================================================

CREATE TABLE IF NOT EXISTS cart_types (
    type_code TEXT PRIMARY KEY,        -- OR, EMERGENCY, PACU, MOBILE
    type_name TEXT NOT NULL,
    description TEXT,
    default_inventory_template TEXT    -- JSON: 預設庫存配置
);

INSERT OR IGNORE INTO cart_types VALUES
    ('OR', '手術室藥車', '固定於特定手術室', '{"FENT": 10, "MIDA": 8, "PROP": 20}'),
    ('MOBILE', '流動藥車', '可跨手術室使用', '{"FENT": 5, "MIDA": 5, "PROP": 10}'),
    ('EMERGENCY', '急救藥車', '急救專用', '{"EPI": 10, "ATRO": 10, "AMIO": 5}'),
    ('PACU', '恢復室藥車', 'PACU 專用', '{"FENT": 5, "ONDAN": 10}');

-- ============================================================================
-- 2. 擴充 drug_carts 表 (若欄位不存在則新增)
-- ============================================================================

-- 注意: SQLite 不支援 ADD COLUMN IF NOT EXISTS，需用 pragma 檢查
-- 這裡假設是新建立或可以安全執行

-- 先嘗試建立完整的 drug_carts 表 (若不存在)
CREATE TABLE IF NOT EXISTS drug_carts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cart_type TEXT DEFAULT 'OR' REFERENCES cart_types(type_code),
    assigned_or TEXT,                  -- OR-01, OR-02, etc.
    location TEXT,
    status TEXT DEFAULT 'ACTIVE',
    is_active BOOLEAN DEFAULT 1,
    current_nurse_id TEXT,             -- 當前負責人
    assigned_to TEXT,                  -- 指派給誰 (legacy)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

-- 預設藥車資料
INSERT OR IGNORE INTO drug_carts (id, name, cart_type, assigned_or, location, status) VALUES
    ('CART-OR-01', 'OR-1 藥車', 'OR', 'OR-01', 'OR-1', 'ACTIVE'),
    ('CART-OR-02', 'OR-2 藥車', 'OR', 'OR-02', 'OR-2', 'ACTIVE'),
    ('CART-OR-03', 'OR-3 藥車', 'OR', 'OR-03', 'OR-3', 'ACTIVE'),
    ('CART-MOBILE-01', '流動藥車 #1', 'MOBILE', NULL, 'Storage', 'ACTIVE'),
    ('CART-ANES-001', '麻醉藥車 (Legacy)', 'OR', 'OR-01', 'OR-1', 'ACTIVE');

-- ============================================================================
-- 3. 藥品移轉記錄表
-- ============================================================================

CREATE TABLE IF NOT EXISTS drug_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 移轉識別
    transfer_id TEXT UNIQUE NOT NULL,      -- XFER-20260121-XXXX
    transfer_code TEXT UNIQUE,             -- 短代碼 XFER-7A3B (iOS用)
    transfer_type TEXT NOT NULL,           -- CASE_TO_CASE, CASE_TO_CART, etc.

    -- 來源
    from_type TEXT NOT NULL,               -- CASE, CART
    from_case_id TEXT,                     -- 若 from_type=CASE
    from_cart_id TEXT,                     -- 若 from_type=CART
    from_nurse_id TEXT NOT NULL,
    from_nurse_name TEXT,

    -- 目的
    to_type TEXT NOT NULL,                 -- CASE, CART
    to_case_id TEXT,                       -- 若 to_type=CASE
    to_cart_id TEXT,                       -- 若 to_type=CART
    to_nurse_id TEXT,                      -- 若 to_type=CASE
    to_nurse_name TEXT,

    -- 藥品資訊
    medicine_code TEXT NOT NULL,
    medicine_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit TEXT DEFAULT 'amp',

    -- 管制藥資訊
    is_controlled BOOLEAN DEFAULT 0,
    controlled_level INTEGER,

    -- 見證 (管制藥必填)
    witness_id TEXT,
    witness_name TEXT,
    witness_role TEXT,                     -- NURSE, PHARMACIST

    -- 狀態
    status TEXT DEFAULT 'PENDING',         -- PENDING, CONFIRMED, REJECTED, CANCELLED

    -- 雙方確認 (CASE_TO_CASE 需要)
    from_confirmed BOOLEAN DEFAULT 1,      -- 發起方自動確認
    from_confirmed_at TEXT,
    to_confirmed BOOLEAN DEFAULT 0,
    to_confirmed_at TEXT,

    -- 拒絕/取消原因
    reject_reason TEXT,

    -- v1.1: 合規聲明
    unopened_declared BOOLEAN NOT NULL DEFAULT 0,
    declaration_timestamp TEXT,

    -- 備註
    remarks TEXT,

    -- 時間戳
    initiated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    expires_at TEXT,                       -- QR Code/短代碼過期時間

    -- 約束
    CHECK(transfer_type IN ('CASE_TO_CASE', 'CASE_TO_CART', 'CART_TO_CASE', 'CART_TO_CART')),
    CHECK(from_type IN ('CASE', 'CART')),
    CHECK(to_type IN ('CASE', 'CART')),
    CHECK(status IN ('PENDING', 'CONFIRMED', 'REJECTED', 'CANCELLED')),
    CHECK(quantity > 0)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_transfers_from_case ON drug_transfers(from_case_id);
CREATE INDEX IF NOT EXISTS idx_transfers_to_case ON drug_transfers(to_case_id);
CREATE INDEX IF NOT EXISTS idx_transfers_status ON drug_transfers(status);
CREATE INDEX IF NOT EXISTS idx_transfers_medicine ON drug_transfers(medicine_code);
CREATE INDEX IF NOT EXISTS idx_transfers_initiated ON drug_transfers(initiated_at);
CREATE INDEX IF NOT EXISTS idx_transfers_code ON drug_transfers(transfer_code);
CREATE INDEX IF NOT EXISTS idx_transfers_expires ON drug_transfers(expires_at);

-- ============================================================================
-- 4. 移轉通知表
-- ============================================================================

CREATE TABLE IF NOT EXISTS transfer_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    transfer_id TEXT NOT NULL,

    -- 通知對象
    target_nurse_id TEXT NOT NULL,
    target_type TEXT NOT NULL,             -- SENDER, RECEIVER

    -- 通知狀態
    notification_type TEXT NOT NULL,       -- TRANSFER_REQUEST, TRANSFER_CONFIRMED, TRANSFER_REJECTED
    is_read BOOLEAN DEFAULT 0,
    read_at TEXT,

    -- 時間
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (transfer_id) REFERENCES drug_transfers(transfer_id)
);

CREATE INDEX IF NOT EXISTS idx_notifications_nurse ON transfer_notifications(target_nurse_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_transfer ON transfer_notifications(transfer_id);

-- ============================================================================
-- 5. SQLite Triggers (DB-Level 強制約束)
-- ============================================================================

-- 1. 管制藥移轉必須有見證人
DROP TRIGGER IF EXISTS enforce_controlled_witness;
CREATE TRIGGER enforce_controlled_witness
BEFORE INSERT ON drug_transfers
WHEN NEW.is_controlled = 1 AND NEW.witness_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'COMPLIANCE_ERROR: 管制藥移轉需要見證人');
END;

-- 2. CASE_TO_CASE 必須有目標案件和護理師
DROP TRIGGER IF EXISTS enforce_case_transfer_fields;
CREATE TRIGGER enforce_case_transfer_fields
BEFORE INSERT ON drug_transfers
WHEN NEW.transfer_type = 'CASE_TO_CASE'
     AND (NEW.to_case_id IS NULL OR NEW.to_nurse_id IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'VALIDATION_ERROR: Case-to-case transfer requires to_case_id and to_nurse_id');
END;

-- 3. CART_TO_CART 必須有藥車 ID
DROP TRIGGER IF EXISTS enforce_cart_transfer_fields;
CREATE TRIGGER enforce_cart_transfer_fields
BEFORE INSERT ON drug_transfers
WHEN NEW.transfer_type = 'CART_TO_CART'
     AND (NEW.from_cart_id IS NULL OR NEW.to_cart_id IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'VALIDATION_ERROR: Cart-to-cart transfer requires cart IDs');
END;

-- 4. 未開封聲明必須為 true
DROP TRIGGER IF EXISTS enforce_unopened_declaration;
CREATE TRIGGER enforce_unopened_declaration
BEFORE INSERT ON drug_transfers
WHEN NEW.unopened_declared != 1
BEGIN
    SELECT RAISE(ABORT, 'COMPLIANCE_ERROR: 必須聲明藥品未開封');
END;

-- ============================================================================
-- 6. 更新 schema version
-- ============================================================================

UPDATE station_metadata SET schema_version = '1.8.0' WHERE station_code IS NOT NULL;

-- ============================================================================
-- 完成
-- ============================================================================
