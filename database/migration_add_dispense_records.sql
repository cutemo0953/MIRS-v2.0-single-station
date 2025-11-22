-- ============================================================================
-- MIRS v2.3 - Emergency Dispense Feature Migration
-- File: migration_add_dispense_records.sql
-- Version: 1.0.0
-- Date: 2024-11-20
-- Purpose: Add dispense_records table for Break-the-Glass emergency dispensing
-- ============================================================================

-- ============================================================================
-- 1. Create dispense_records Table (領藥登記簿)
-- ============================================================================
-- This table is specifically for medication dispensing workflow
-- Separate from pharmacy_transactions for clarity and MIRS v2.3 spec compliance
-- ============================================================================

CREATE TABLE IF NOT EXISTS dispense_records (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Medication Information
    medicine_code TEXT NOT NULL,                 -- 藥品代碼 (links to medicines table)
    medicine_name TEXT NOT NULL,                 -- 藥品名稱 (denormalized for quick access)
    quantity INTEGER NOT NULL CHECK(quantity > 0), -- 數量
    unit TEXT NOT NULL DEFAULT '顆',             -- 單位

    -- Personnel Records (4-hands principle)
    dispensed_by TEXT NOT NULL,                  -- 領藥人 (nurse/doctor who took the medicine)
    approved_by TEXT,                            -- 審核人 (pharmacist who approved - NULL for emergency)

    -- Status Management (核心欄位)
    status TEXT NOT NULL DEFAULT 'PENDING',      -- 狀態: PENDING | APPROVED | EMERGENCY
    emergency_reason TEXT,                       -- 緊急原因 (required when status='EMERGENCY')

    -- Optional: Patient Reference (選填)
    patient_ref_id TEXT,                         -- 病患參考編號 (Triage Tag barcode)
    patient_name TEXT,                           -- 病患姓名 (optional, for reference)

    -- Station & Location
    station_code TEXT NOT NULL DEFAULT 'TC-01',  -- 站點代碼
    storage_location TEXT,                       -- 取藥位置 (optional)

    -- Batch & Expiry (for traceability)
    batch_number TEXT,                           -- 批號
    lot_number TEXT,                             -- 批次號
    expiry_date DATE,                            -- 效期

    -- Prescription Reference (optional)
    prescription_id TEXT,                        -- 處方ID (if applicable)

    -- Audit & Compliance
    approved_at TIMESTAMP,                       -- 審核時間 (when pharmacist reviews)
    pharmacist_notes TEXT,                       -- 藥師備註 (for emergency review)

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Cost Tracking (optional)
    unit_cost REAL DEFAULT 0,
    total_cost REAL GENERATED ALWAYS AS (quantity * unit_cost) VIRTUAL,

    -- Foreign Keys
    FOREIGN KEY (medicine_code) REFERENCES medicines(medicine_code) ON DELETE RESTRICT,

    -- Constraints
    CHECK (status IN ('PENDING', 'APPROVED', 'EMERGENCY')),
    CHECK (quantity > 0),
    CHECK (unit_cost >= 0),

    -- Business Logic Constraints
    -- Emergency status must have a reason (enforced in application layer)
    -- Approved status must have approved_by (enforced in application layer)
    CHECK (
        (status = 'EMERGENCY' AND emergency_reason IS NOT NULL AND LENGTH(emergency_reason) >= 5) OR
        (status != 'EMERGENCY')
    )
);

-- ============================================================================
-- 2. Create Indexes for Performance
-- ============================================================================

-- Primary lookup: find pending/emergency records
CREATE INDEX IF NOT EXISTS idx_dispense_status_date
ON dispense_records(status, created_at DESC);

-- Emergency dispensing audit trail
CREATE INDEX IF NOT EXISTS idx_dispense_emergency
ON dispense_records(status, created_at DESC)
WHERE status = 'EMERGENCY';

-- Find records by personnel
CREATE INDEX IF NOT EXISTS idx_dispense_by_person
ON dispense_records(dispensed_by, created_at DESC);

-- Find records by medicine
CREATE INDEX IF NOT EXISTS idx_dispense_medicine
ON dispense_records(medicine_code, created_at DESC);

-- Station-based queries
CREATE INDEX IF NOT EXISTS idx_dispense_station
ON dispense_records(station_code, status, created_at DESC);

-- Patient tracking
CREATE INDEX IF NOT EXISTS idx_dispense_patient
ON dispense_records(patient_ref_id)
WHERE patient_ref_id IS NOT NULL;

-- ============================================================================
-- 3. Create Trigger for updated_at
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_dispense_records_timestamp
AFTER UPDATE ON dispense_records
FOR EACH ROW
BEGIN
    UPDATE dispense_records
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- ============================================================================
-- 4. Create Trigger for Automatic Stock Deduction
-- ============================================================================
-- When a dispense record is created with APPROVED or EMERGENCY status,
-- automatically deduct from medicine stock
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS auto_deduct_stock_on_dispense
AFTER INSERT ON dispense_records
FOR EACH ROW
WHEN NEW.status IN ('APPROVED', 'EMERGENCY')
BEGIN
    -- Deduct from current_stock in medicines table
    UPDATE medicines
    SET current_stock = current_stock - NEW.quantity,
        updated_at = CURRENT_TIMESTAMP
    WHERE medicine_code = NEW.medicine_code;

    -- Also create a pharmacy_transaction record for audit trail
    INSERT INTO pharmacy_transactions (
        transaction_id,
        transaction_type,
        medicine_code,
        generic_name,
        quantity,
        unit,
        station_code,
        operator,
        operator_role,
        verified_by,
        patient_id,
        patient_name,
        status,
        remarks,
        created_by
    ) SELECT
        'DISP-' || NEW.id || '-' || strftime('%Y%m%d%H%M%S', 'now'),
        'DISPENSE',
        NEW.medicine_code,
        m.generic_name,
        NEW.quantity,
        NEW.unit,
        NEW.station_code,
        NEW.dispensed_by,
        'NURSE',  -- Default role
        NEW.approved_by,
        NEW.patient_ref_id,
        NEW.patient_name,
        CASE
            WHEN NEW.status = 'EMERGENCY' THEN 'COMPLETED'
            ELSE 'COMPLETED'
        END,
        CASE
            WHEN NEW.status = 'EMERGENCY' THEN '緊急領用: ' || NEW.emergency_reason
            ELSE '正常領用'
        END,
        NEW.dispensed_by
    FROM medicines m
    WHERE m.medicine_code = NEW.medicine_code;
END;

-- ============================================================================
-- 5. Create View for Pending Emergency Reviews
-- ============================================================================
-- Pharmacists need to see all emergency dispenses that need review
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_pending_emergency_dispenses AS
SELECT
    dr.id,
    dr.medicine_code,
    dr.medicine_name,
    dr.quantity,
    dr.unit,
    dr.dispensed_by,
    dr.emergency_reason,
    dr.patient_ref_id,
    dr.patient_name,
    dr.station_code,
    dr.created_at,
    m.generic_name,
    m.brand_name,
    m.is_controlled_drug,
    m.controlled_level,
    -- Calculate how long it's been pending
    CAST((julianday('now') - julianday(dr.created_at)) * 24 AS INTEGER) AS hours_pending
FROM dispense_records dr
LEFT JOIN medicines m ON dr.medicine_code = m.medicine_code
WHERE dr.status = 'EMERGENCY'
ORDER BY dr.created_at ASC;

-- ============================================================================
-- 6. Create View for Daily Dispense Summary
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_daily_dispense_summary AS
SELECT
    DATE(created_at) AS dispense_date,
    station_code,
    status,
    COUNT(*) AS dispense_count,
    SUM(quantity) AS total_quantity,
    SUM(total_cost) AS total_cost,
    COUNT(CASE WHEN status = 'EMERGENCY' THEN 1 END) AS emergency_count,
    COUNT(CASE WHEN patient_ref_id IS NOT NULL THEN 1 END) AS patient_linked_count
FROM dispense_records
GROUP BY DATE(created_at), station_code, status
ORDER BY dispense_date DESC, station_code;

-- ============================================================================
-- 7. Insert Sample Data (for testing only - remove in production)
-- ============================================================================
-- Uncomment below to add test data
/*
INSERT INTO dispense_records (
    medicine_code, medicine_name, quantity, unit,
    dispensed_by, approved_by, status,
    station_code, created_at
) VALUES
    ('MED-001', 'Paracetamol 500mg', 10, '顆',
     '護理師-張小明', '藥師-李大華', 'APPROVED',
     'TC-01', datetime('now', '-2 hours')),

    ('MED-002', 'Morphine 10mg', 2, '顆',
     '護理師-王小美', NULL, 'EMERGENCY',
     'TC-01', datetime('now', '-1 hour'));

-- Add emergency reason for the second record
UPDATE dispense_records
SET emergency_reason = '大量傷患湧入，藥師不在現場，病患疼痛指數10/10'
WHERE id = 2;
*/

-- ============================================================================
-- 8. Verification Queries (run after migration)
-- ============================================================================
-- Use these to verify the migration was successful
-- ============================================================================

-- Check table structure
-- SELECT sql FROM sqlite_master WHERE name = 'dispense_records';

-- Check indexes
-- SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'dispense_records';

-- Check triggers
-- SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'dispense_records';

-- Check views
-- SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE '%dispense%';

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Next Steps:
-- 1. Run this migration: sqlite3 medical_inventory.db < migration_add_dispense_records.sql
-- 2. Verify: SELECT COUNT(*) FROM dispense_records;
-- 3. Test emergency dispense workflow
-- ============================================================================
