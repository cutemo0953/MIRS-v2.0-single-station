-- Migration: Add procedure linking to medications and blood consumption
-- Date: 2025-11-21
-- Purpose: Link dispense_records and blood_events to surgery_records

-- ============================================
-- 1. Add procedure_id to dispense_records
-- ============================================

-- Check if column already exists (SQLite doesn't have IF NOT EXISTS for ALTER TABLE)
-- We'll use a safe approach

-- Add procedure_id column to link medications to procedures
ALTER TABLE dispense_records ADD COLUMN procedure_id INTEGER;

-- Add index for fast procedure lookup
CREATE INDEX IF NOT EXISTS idx_dispense_procedure ON dispense_records(procedure_id);

-- Add foreign key comment (SQLite doesn't enforce FK by default)
-- This references surgery_records(id)

-- ============================================
-- 2. Add procedure_id to blood_events
-- ============================================

ALTER TABLE blood_events ADD COLUMN procedure_id INTEGER;

-- Add index for fast procedure lookup
CREATE INDEX IF NOT EXISTS idx_blood_procedure ON blood_events(procedure_id);

-- ============================================
-- 3. Create view for procedure summary with costs
-- ============================================

CREATE VIEW IF NOT EXISTS v_procedure_complete_summary AS
SELECT
    sr.id,
    sr.patient_name,
    sr.surgery_type,
    sr.surgeon_name,
    sr.start_time,
    sr.end_time,
    sr.status,

    -- Consumable summary
    (SELECT COUNT(*) FROM surgery_consumptions WHERE surgery_id = sr.id) as consumable_count,
    (SELECT SUM(quantity) FROM surgery_consumptions WHERE surgery_id = sr.id) as total_consumables,

    -- Medication summary
    (SELECT COUNT(*) FROM dispense_records WHERE procedure_id = sr.id) as medication_count,
    (SELECT SUM(quantity) FROM dispense_records WHERE procedure_id = sr.id) as total_medications,
    (SELECT COUNT(*) FROM dispense_records WHERE procedure_id = sr.id AND status = 'EMERGENCY') as emergency_med_count,

    -- Blood summary
    (SELECT COUNT(*) FROM blood_events WHERE procedure_id = sr.id) as blood_event_count,
    (SELECT SUM(quantity) FROM blood_events WHERE procedure_id = sr.id AND event_type = 'CONSUME') as blood_units_used,

    sr.remarks
FROM surgery_records sr;

-- ============================================
-- 4. Create view for procedure resource details
-- ============================================

CREATE VIEW IF NOT EXISTS v_procedure_resources AS
SELECT
    sr.id as procedure_id,
    sr.patient_name,
    sr.surgery_type,
    'CONSUMABLE' as resource_type,
    i.name as resource_name,
    sc.quantity,
    i.unit,
    sc.timestamp as used_at,
    NULL as notes
FROM surgery_records sr
JOIN surgery_consumptions sc ON sr.id = sc.surgery_id
JOIN items i ON sc.item_code = i.code

UNION ALL

SELECT
    sr.id as procedure_id,
    sr.patient_name,
    sr.surgery_type,
    'MEDICATION' as resource_type,
    dr.medicine_name as resource_name,
    dr.quantity,
    dr.unit,
    dr.created_at as used_at,
    dr.emergency_reason as notes
FROM surgery_records sr
JOIN dispense_records dr ON sr.id = dr.procedure_id
WHERE dr.procedure_id IS NOT NULL

UNION ALL

SELECT
    sr.id as procedure_id,
    sr.patient_name,
    sr.surgery_type,
    'BLOOD' as resource_type,
    be.blood_type as resource_name,
    be.quantity,
    'U' as unit,
    be.timestamp as used_at,
    be.remarks as notes
FROM surgery_records sr
JOIN blood_events be ON sr.id = be.procedure_id
WHERE be.procedure_id IS NOT NULL AND be.event_type = 'CONSUME';

-- ============================================
-- 5. Migration completion marker
-- ============================================

-- Create migrations tracking table if not exists
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Record this migration
INSERT OR IGNORE INTO schema_migrations (migration_name, description) VALUES
('add_procedure_links', 'Add procedure_id to dispense_records and blood_events for resource tracking');

-- ============================================
-- Success message
-- ============================================
SELECT 'Migration completed successfully!' as status,
       'Added procedure_id to dispense_records and blood_events' as changes,
       'Created views: v_procedure_complete_summary, v_procedure_resources' as new_objects;
