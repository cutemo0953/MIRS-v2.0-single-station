-- ============================================================================
-- Migration: 麻醉計費整合欄位擴充
-- Version: 1.2.0
-- Date: 2026-01-20
-- Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md Section 10
-- ============================================================================

-- ============================================================================
-- 1. medicines 表擴充 - 計費相關欄位
-- ============================================================================

-- 每單位含量 (如 Propofol 200mg/20ml，content_per_unit = 10, content_unit = 'mg/ml')
ALTER TABLE medicines ADD COLUMN content_per_unit REAL;

-- 含量單位
ALTER TABLE medicines ADD COLUMN content_unit TEXT;

-- 計費進位方式: CEIL(無條件進位), FLOOR(無條件捨去), ROUND(四捨五入)
ALTER TABLE medicines ADD COLUMN billing_rounding TEXT DEFAULT 'CEIL';

-- ============================================================================
-- 2. controlled_drug_log 表擴充 - 浪費追蹤欄位 (Section 10.1)
-- ============================================================================

-- 實際給藥量 (administered_amount + waste_amount = 抽取總量)
ALTER TABLE controlled_drug_log ADD COLUMN administered_amount REAL;

-- 浪費量
ALTER TABLE controlled_drug_log ADD COLUMN waste_amount REAL;

-- 浪費見證人
ALTER TABLE controlled_drug_log ADD COLUMN wastage_witnessed_by TEXT;

-- 浪費見證時間
ALTER TABLE controlled_drug_log ADD COLUMN wastage_witnessed_at TIMESTAMP;

-- ============================================================================
-- 3. pharmacy_transactions 表擴充 - 交易類型擴充
-- ============================================================================

-- 先移除舊的 CHECK constraint（SQLite 不支援直接修改，需重建表或忽略）
-- 新增交易類型: WITHDRAW, ADMINISTER, WASTE, RETURN, TRANSFER, VOID

-- Idempotency key (Section 10.3)
ALTER TABLE pharmacy_transactions ADD COLUMN idempotency_key TEXT;

-- 計費數量 (可能與庫存扣減數量不同，使用 Decimal 精度)
ALTER TABLE pharmacy_transactions ADD COLUMN billing_quantity REAL;

-- 庫存扣減數量
ALTER TABLE pharmacy_transactions ADD COLUMN inventory_deduct_quantity REAL;

-- 關聯事件 UUID (來自 Anesthesia PWA)
ALTER TABLE pharmacy_transactions ADD COLUMN client_event_uuid TEXT;

-- 案件 ID
ALTER TABLE pharmacy_transactions ADD COLUMN case_id TEXT;

-- 價格簿版本 (Section 10.7)
ALTER TABLE pharmacy_transactions ADD COLUMN pricebook_version TEXT;

-- VOID 關聯 (Section 10.8)
ALTER TABLE pharmacy_transactions ADD COLUMN void_target_transaction_id TEXT;
ALTER TABLE pharmacy_transactions ADD COLUMN void_reason TEXT;

-- ============================================================================
-- 4. 建立索引
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_pharm_idempotency_key
    ON pharmacy_transactions(idempotency_key);

CREATE INDEX IF NOT EXISTS idx_pharm_client_event_uuid
    ON pharmacy_transactions(client_event_uuid);

CREATE INDEX IF NOT EXISTS idx_pharm_case_id
    ON pharmacy_transactions(case_id);

CREATE INDEX IF NOT EXISTS idx_ctrl_administered_amount
    ON controlled_drug_log(administered_amount);

CREATE INDEX IF NOT EXISTS idx_ctrl_waste_amount
    ON controlled_drug_log(waste_amount);

-- ============================================================================
-- 5. 更新 schema_version
-- ============================================================================

UPDATE station_metadata SET schema_version = '1.6.0' WHERE station_code IS NOT NULL;

-- ============================================================================
-- 完成
-- ============================================================================
