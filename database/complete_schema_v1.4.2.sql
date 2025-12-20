CREATE TABLE items (
                    item_code TEXT PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    item_category TEXT,
                    category TEXT,
                    unit TEXT DEFAULT 'EA',
                    min_stock INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                , specification TEXT, endurance_type TEXT, capacity_per_unit REAL, capacity_unit TEXT, tests_per_unit INTEGER, valid_days_after_open INTEGER, depends_on_item_code TEXT, dependency_note TEXT);
CREATE TABLE medicines (
                    medicine_code TEXT PRIMARY KEY,
                    generic_name TEXT NOT NULL,
                    brand_name TEXT,
                    unit TEXT DEFAULT '顆',
                    min_stock INTEGER DEFAULT 100,
                    current_stock INTEGER DEFAULT 0,
                    is_controlled_drug INTEGER DEFAULT 0,
                    controlled_level TEXT,
                    is_active INTEGER DEFAULT 1,
                    station_id TEXT NOT NULL DEFAULT 'HC-000000',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(is_controlled_drug IN (0, 1)),
                    CHECK(is_active IN (0, 1))
                );
CREATE TABLE inventory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    item_code TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    batch_number TEXT,
                    expiry_date TEXT,
                    remarks TEXT,
                    station_id TEXT NOT NULL,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_code) REFERENCES items(item_code)
                );
CREATE TABLE sqlite_sequence(name,seq);
CREATE INDEX idx_inventory_events_item 
                ON inventory_events(item_code)
            ;
CREATE INDEX idx_inventory_events_timestamp 
                ON inventory_events(timestamp)
            ;
CREATE TABLE blood_inventory (
                    blood_type TEXT NOT NULL,
                    quantity INTEGER DEFAULT 0,
                    station_id TEXT NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (blood_type, station_id)
                );
CREATE TABLE blood_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    blood_type TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    station_id TEXT NOT NULL,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                , remarks TEXT);
CREATE TABLE emergency_blood_bags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    blood_bag_code TEXT UNIQUE NOT NULL,
                    blood_type TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    collection_date DATE NOT NULL,
                    expiry_date DATE NOT NULL,
                    volume_ml INTEGER DEFAULT 250,
                    status TEXT DEFAULT 'AVAILABLE',
                    station_id TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    patient_name TEXT,
                    usage_timestamp TIMESTAMP,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(status IN ('AVAILABLE', 'USED', 'EXPIRED', 'DISCARDED'))
                );
CREATE TABLE equipment (
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
                , power_watts INTEGER, capacity_wh REAL, output_watts INTEGER, fuel_rate_lph REAL, device_type TEXT, tracking_mode TEXT DEFAULT 'AGGREGATE', type_code TEXT REFERENCES equipment_types(type_code), capacity_override TEXT);
CREATE TABLE equipment_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equipment_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    power_level INTEGER,
                    remarks TEXT,
                    station_id TEXT NOT NULL,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
                );
CREATE TABLE surgery_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_number TEXT UNIQUE NOT NULL,
                    record_date DATE NOT NULL,
                    patient_name TEXT NOT NULL,
                    surgery_sequence INTEGER NOT NULL,
                    surgery_type TEXT NOT NULL,
                    surgeon_name TEXT NOT NULL,
                    anesthesia_type TEXT,
                    duration_minutes INTEGER,
                    remarks TEXT,
                    station_id TEXT NOT NULL,
                    status TEXT DEFAULT 'ONGOING',
                    patient_outcome TEXT,
                    archived_at TIMESTAMP,
                    archived_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, cirs_person_id TEXT,
                    CHECK(status IN ('ONGOING', 'COMPLETED', 'ARCHIVED', 'CANCELLED')),
                    CHECK(patient_outcome IS NULL OR patient_outcome IN ('DISCHARGED', 'TRANSFERRED', 'DECEASED'))
                );
CREATE TABLE surgery_consumptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    surgery_id INTEGER NOT NULL,
                    item_code TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit TEXT NOT NULL,
                    FOREIGN KEY (surgery_id) REFERENCES surgery_records(id) ON DELETE CASCADE,
                    FOREIGN KEY (item_code) REFERENCES items(item_code)
                );
CREATE TABLE dispense_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    medicine_code TEXT NOT NULL,
                    medicine_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    unit TEXT NOT NULL DEFAULT '顆',
                    dispensed_by TEXT NOT NULL,
                    approved_by TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    emergency_reason TEXT,
                    patient_ref_id TEXT,
                    patient_name TEXT,
                    station_code TEXT NOT NULL DEFAULT 'HC-000000',
                    storage_location TEXT,
                    batch_number TEXT,
                    lot_number TEXT,
                    expiry_date DATE,
                    prescription_id TEXT,
                    approved_at TIMESTAMP,
                    pharmacist_notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    unit_cost REAL DEFAULT 0,
                    CHECK (status IN ('PENDING', 'APPROVED', 'EMERGENCY')),
                    CHECK (unit_cost >= 0),
                    CHECK (
                        (status = 'EMERGENCY' AND emergency_reason IS NOT NULL AND LENGTH(emergency_reason) >= 5) OR
                        (status != 'EMERGENCY')
                    )
                );
CREATE INDEX idx_dispense_status_date
                ON dispense_records(status, created_at DESC)
            ;
CREATE INDEX idx_dispense_emergency
                ON dispense_records(status, created_at DESC)
                WHERE status = 'EMERGENCY'
            ;
CREATE INDEX idx_dispense_medicine
                ON dispense_records(medicine_code, created_at DESC)
            ;
CREATE TABLE station_merge_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_station_id TEXT NOT NULL,
                    target_station_id TEXT NOT NULL,
                    merge_type TEXT NOT NULL,
                    items_merged INTEGER DEFAULT 0,
                    blood_merged INTEGER DEFAULT 0,
                    equipment_merged INTEGER DEFAULT 0,
                    surgery_records_merged INTEGER DEFAULT 0,
                    merge_notes TEXT,
                    merged_by TEXT NOT NULL,
                    merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(merge_type IN ('FULL_MERGE', 'PARTIAL_MERGE', 'IMPORT_BACKUP'))
                );
CREATE TABLE inventory_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_number TEXT UNIQUE NOT NULL,
                    audit_type TEXT NOT NULL,
                    status TEXT DEFAULT 'IN_PROGRESS',
                    station_id TEXT NOT NULL,
                    started_by TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_by TEXT,
                    completed_at TIMESTAMP,
                    total_items INTEGER DEFAULT 0,
                    discrepancies INTEGER DEFAULT 0,
                    notes TEXT,
                    CHECK(audit_type IN ('ROUTINE', 'PRE_MERGE', 'POST_MERGE', 'EMERGENCY')),
                    CHECK(status IN ('IN_PROGRESS', 'COMPLETED', 'CANCELLED'))
                );
CREATE TABLE inventory_audit_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id INTEGER NOT NULL,
                    item_code TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    system_quantity INTEGER NOT NULL,
                    actual_quantity INTEGER NOT NULL,
                    discrepancy INTEGER NOT NULL,
                    remarks TEXT,
                    audited_by TEXT NOT NULL,
                    audited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (audit_id) REFERENCES inventory_audit(id) ON DELETE CASCADE,
                    FOREIGN KEY (item_code) REFERENCES items(item_code)
                );
CREATE INDEX idx_surgery_records_date
                ON surgery_records(record_date)
            ;
CREATE INDEX idx_surgery_records_patient
                ON surgery_records(patient_name)
            ;
CREATE INDEX idx_surgery_consumptions_surgery
                ON surgery_consumptions(surgery_id)
            ;
CREATE INDEX idx_items_category
                ON items(category)
            ;
CREATE INDEX idx_items_updated
                ON items(updated_at DESC)
            ;
CREATE INDEX idx_inventory_events_time
                ON inventory_events(timestamp DESC)
            ;
CREATE INDEX idx_blood_events_type
                ON blood_events(blood_type, timestamp DESC)
            ;
CREATE INDEX idx_blood_events_time
                ON blood_events(timestamp DESC)
            ;
CREATE INDEX idx_emergency_blood_status
                ON emergency_blood_bags(status, collection_date DESC)
            ;
CREATE INDEX idx_emergency_blood_type
                ON emergency_blood_bags(blood_type, status)
            ;
CREATE INDEX idx_emergency_blood_expiry
                ON emergency_blood_bags(expiry_date)
            ;
CREATE INDEX idx_equipment_status
                ON equipment(status, last_check DESC)
            ;
CREATE INDEX idx_equipment_category
                ON equipment(category)
            ;
CREATE INDEX idx_equipment_checks_time
                ON equipment_checks(timestamp DESC)
            ;
CREATE INDEX idx_surgery_records_status
                ON surgery_records(status, record_date DESC)
            ;
CREATE INDEX idx_surgery_records_outcome
                ON surgery_records(patient_outcome)
            ;
CREATE INDEX idx_merge_history_station
                ON station_merge_history(target_station_id, merged_at DESC)
            ;
CREATE INDEX idx_audit_status
                ON inventory_audit(status, started_at DESC)
            ;
CREATE INDEX idx_audit_details_audit
                ON inventory_audit_details(audit_id)
            ;
CREATE TABLE hospitals (
                    hospital_id TEXT PRIMARY KEY,
                    hospital_name TEXT NOT NULL,
                    hospital_type TEXT NOT NULL DEFAULT 'FIELD_HOSPITAL',
                    command_level TEXT NOT NULL DEFAULT 'LOCAL',
                    latitude REAL,
                    longitude REAL,
                    contact_info TEXT,
                    network_access TEXT DEFAULT 'NONE',
                    total_stations INTEGER DEFAULT 0,
                    operational_status TEXT DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(hospital_type IN ('FIELD_HOSPITAL', 'CIVILIAN_HOSPITAL', 'MOBILE_HOSPITAL')),
                    CHECK(command_level IN ('CENTRAL', 'REGIONAL', 'LOCAL')),
                    CHECK(network_access IN ('NONE', 'MILITARY', 'SATELLITE', 'CIVILIAN')),
                    CHECK(operational_status IN ('ACTIVE', 'OFFLINE', 'EVACUATED', 'MERGED'))
                );
CREATE TABLE stations (
                    station_id TEXT PRIMARY KEY,
                    station_name TEXT NOT NULL,
                    hospital_id TEXT NOT NULL,
                    station_type TEXT DEFAULT 'SMALL',
                    latitude REAL,
                    longitude REAL,
                    network_access TEXT DEFAULT 'NONE',
                    operational_status TEXT DEFAULT 'ACTIVE',
                    last_sync_at TIMESTAMP,
                    sync_status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id),
                    CHECK(station_type IN ('LARGE', 'SMALL')),
                    CHECK(network_access IN ('NONE', 'INTRANET', 'MILITARY')),
                    CHECK(sync_status IN ('PENDING', 'SYNCING', 'SYNCED', 'FAILED')),
                    CHECK(operational_status IN ('ACTIVE', 'OFFLINE', 'EVACUATED', 'MERGED'))
                );
CREATE TABLE sync_packages (
                    package_id TEXT PRIMARY KEY,
                    package_type TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    destination_type TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    hospital_id TEXT NOT NULL,
                    transfer_method TEXT NOT NULL,
                    package_size INTEGER,
                    checksum TEXT NOT NULL,
                    changes_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    uploaded_at TIMESTAMP,
                    processed_at TIMESTAMP,
                    error_message TEXT,
                    CHECK(package_type IN ('DELTA', 'FULL', 'REPORT')),
                    CHECK(source_type IN ('STATION', 'HOSPITAL')),
                    CHECK(destination_type IN ('HOSPITAL', 'CENTRAL')),
                    CHECK(transfer_method IN ('NETWORK', 'USB', 'MANUAL', 'DRONE')),
                    CHECK(status IN ('PENDING', 'UPLOADED', 'PROCESSING', 'APPLIED', 'FAILED'))
                );
CREATE TABLE hospital_daily_reports (
                    report_id TEXT PRIMARY KEY,
                    hospital_id TEXT NOT NULL,
                    report_date DATE NOT NULL,
                    total_stations INTEGER NOT NULL,
                    operational_stations INTEGER NOT NULL,
                    offline_stations INTEGER NOT NULL,
                    total_patients_treated INTEGER DEFAULT 0,
                    critical_patients INTEGER DEFAULT 0,
                    surgeries_performed INTEGER DEFAULT 0,
                    blood_inventory_json TEXT,
                    critical_shortages_json TEXT,
                    equipment_status_json TEXT,
                    alerts_json TEXT,
                    submitted_by TEXT NOT NULL,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    received_by_central BOOLEAN DEFAULT FALSE,
                    received_at TIMESTAMP,
                    UNIQUE(hospital_id, report_date),
                    FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id)
                );
CREATE INDEX idx_stations_hospital
                ON stations(hospital_id)
            ;
CREATE INDEX idx_sync_packages_status
                ON sync_packages(status)
            ;
CREATE INDEX idx_sync_packages_hospital
                ON sync_packages(hospital_id)
            ;
CREATE INDEX idx_sync_packages_date
                ON sync_packages(created_at DESC)
            ;
CREATE INDEX idx_hospital_reports_date
                ON hospital_daily_reports(report_date DESC)
            ;
CREATE INDEX idx_hospital_reports_hospital
                ON hospital_daily_reports(hospital_id)
            ;
CREATE TABLE blood_bags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bag_code TEXT UNIQUE NOT NULL,
    blood_type TEXT NOT NULL,
    volume_ml INTEGER DEFAULT 250,
    collection_date DATE,
    expiry_date DATE,
    status TEXT DEFAULT 'AVAILABLE',
    donor_id TEXT,
    donor_info TEXT,
    batch_number TEXT,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    used_at TIMESTAMP,
    used_for TEXT,
    CHECK(status IN ('AVAILABLE', 'RESERVED', 'USED', 'EXPIRED', 'DISCARDED'))
);
CREATE TABLE resilience_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,           -- '*' for global defaults
    endurance_type TEXT NOT NULL,       -- 'OXYGEN', 'POWER', 'REAGENT'
    profile_name TEXT NOT NULL,         -- Display name in Chinese
    profile_name_en TEXT,               -- English name
    burn_rate REAL NOT NULL,            -- Consumption rate value
    burn_rate_unit TEXT NOT NULL,       -- 'L/min', 'L/hr', 'tests/day'
    population_multiplier INTEGER DEFAULT 0, -- 1 = Rate × population
    description TEXT,
    is_default INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_profiles_type
    ON resilience_profiles(endurance_type, station_id);
CREATE TABLE resilience_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL UNIQUE,

    -- Isolation context
    isolation_target_days REAL DEFAULT 3,
    isolation_source TEXT DEFAULT 'manual', -- 'manual', 'weather_api'

    -- Population context
    population_count INTEGER DEFAULT 1,
    population_label TEXT DEFAULT '人數',

    -- Active profile IDs (foreign keys to resilience_profiles)
    oxygen_profile_id INTEGER,
    power_profile_id INTEGER,
    reagent_profile_id INTEGER,

    -- Alert thresholds (percentage of isolation target)
    threshold_safe REAL DEFAULT 1.2,      -- >=120% = SAFE
    threshold_warning REAL DEFAULT 1.0,   -- >=100% = WARNING
    -- Below 100% = CRITICAL

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,

    FOREIGN KEY (oxygen_profile_id) REFERENCES resilience_profiles(id),
    FOREIGN KEY (power_profile_id) REFERENCES resilience_profiles(id),
    FOREIGN KEY (reagent_profile_id) REFERENCES resilience_profiles(id)
);
CREATE TABLE unit_standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_type TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    display_name_en TEXT,
    capacity REAL NOT NULL,
    capacity_unit TEXT NOT NULL,
    category TEXT NOT NULL,  -- 'OXYGEN', 'FUEL', 'WATER'
    notes TEXT,
    region TEXT DEFAULT 'TW'
);
CREATE TABLE reagent_open_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT NOT NULL,
    batch_number TEXT,
    station_id TEXT NOT NULL,
    opened_at DATETIME NOT NULL,
    tests_remaining INTEGER,
    is_active INTEGER DEFAULT 1,  -- 1 = current open kit
    notes TEXT,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (item_code) REFERENCES items(item_code)
);
CREATE INDEX idx_reagent_open_active
    ON reagent_open_records(item_code, station_id, is_active);
CREATE TABLE pharmaceuticals (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    generic_name TEXT,
                    unit TEXT DEFAULT 'Tab',
                    min_stock INTEGER DEFAULT 50,
                    current_stock INTEGER DEFAULT 0,
                    category TEXT DEFAULT '常用藥品',
                    storage_condition TEXT DEFAULT '常溫',
                    controlled_level TEXT DEFAULT '非管制',
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(category IN ('常用藥品', '急救藥品', '麻醉藥品', '管制藥品', '輸液')),
                    CHECK(storage_condition IN ('常溫', '冷藏', '冷凍')),
                    CHECK(controlled_level IN ('非管制', '一級', '二級', '三級', '四級')),
                    CHECK(is_active IN (0, 1))
                );
CREATE TABLE pharma_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    pharma_code TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    batch_number TEXT,
                    expiry_date TEXT,
                    remarks TEXT,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (pharma_code) REFERENCES pharmaceuticals(code),
                    CHECK(event_type IN ('RECEIVE', 'CONSUME', 'ADJUST', 'EXPIRE'))
                );
CREATE INDEX idx_pharma_category
                ON pharmaceuticals(category)
            ;
CREATE INDEX idx_pharma_events_code
                ON pharma_events(pharma_code, timestamp DESC)
            ;
CREATE INDEX idx_blood_bags_type_status
                ON blood_bags(blood_type, status)
            ;
CREATE INDEX idx_blood_bags_expiry
                ON blood_bags(expiry_date)
            ;
CREATE INDEX idx_surgery_cirs_person ON surgery_records(cirs_person_id);
CREATE TABLE power_load_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    profile_name_en TEXT,
    description TEXT,
    total_watts INTEGER NOT NULL,
    is_default INTEGER DEFAULT 0,
    equipment_list TEXT,  -- JSON array of equipment IDs included
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE equipment_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,           -- FK to equipment.id (e.g., 'RESP-001')
    unit_serial TEXT,                     -- 序號 (e.g., 'CYL-001', 'CYL-002')
    unit_label TEXT,                      -- 標籤 (e.g., '1號瓶', '2號瓶')
    level_percent INTEGER DEFAULT 100,    -- 充填/電量百分比 (0-100)
    status TEXT DEFAULT 'AVAILABLE',      -- AVAILABLE, IN_USE, EMPTY, MAINTENANCE
    last_check TIMESTAMP,
    checked_by TEXT,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_active INTEGER DEFAULT 1, removed_at TIMESTAMP, removed_by TEXT, removal_reason TEXT,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);
CREATE INDEX idx_equipment_units_eq_id
ON equipment_units(equipment_id);
CREATE VIEW v_equipment_aggregate AS
SELECT
    e.id,
    e.name,
    e.category,
    e.quantity,
    e.tracking_mode,
    CASE
        WHEN e.tracking_mode = 'PER_UNIT' THEN
            (SELECT COUNT(*) FROM equipment_units u WHERE u.equipment_id = e.id)
        ELSE e.quantity
    END as actual_count,
    CASE
        WHEN e.tracking_mode = 'PER_UNIT' THEN
            (SELECT AVG(level_percent) FROM equipment_units u WHERE u.equipment_id = e.id)
        ELSE e.power_level
    END as avg_level,
    CASE
        WHEN e.tracking_mode = 'PER_UNIT' THEN
            (SELECT SUM(level_percent) FROM equipment_units u WHERE u.equipment_id = e.id)
        ELSE e.quantity * COALESCE(e.power_level, 100)
    END as total_level_sum
FROM equipment e
/* v_equipment_aggregate(id,name,category,quantity,tracking_mode,actual_count,avg_level,total_level_sum) */;
CREATE TABLE equipment_check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,           -- FK to equipment.id or equipment_units
    unit_label TEXT,                      -- 個別單位標籤 (nullable for AGGREGATE mode)
    check_date DATE NOT NULL,             -- 檢查日期
    check_time TIMESTAMP NOT NULL,        -- 檢查時間
    checked_by TEXT,                      -- 檢查人員
    level_before INTEGER,                 -- 檢查前百分比
    level_after INTEGER,                  -- 檢查後百分比
    status_before TEXT,                   -- 檢查前狀態
    status_after TEXT,                    -- 檢查後狀態
    remarks TEXT,                         -- 備註
    station_id TEXT,                      -- 站點 ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, unit_id INTEGER REFERENCES equipment_units(id));
CREATE INDEX idx_check_history_date
ON equipment_check_history(check_date);
CREATE INDEX idx_check_history_equipment
ON equipment_check_history(equipment_id);
CREATE VIEW v_daily_check_summary AS
SELECT
    check_date,
    station_id,
    COUNT(DISTINCT equipment_id) as equipment_checked,
    COUNT(*) as total_checks,
    COUNT(DISTINCT unit_label) as units_checked,
    GROUP_CONCAT(DISTINCT checked_by) as checkers,
    MIN(check_time) as first_check,
    MAX(check_time) as last_check
FROM equipment_check_history
GROUP BY check_date, station_id
/* v_daily_check_summary(check_date,station_id,equipment_checked,total_checks,units_checked,checkers,first_check,last_check) */;
CREATE TABLE equipment_types (
    type_code       TEXT PRIMARY KEY,
    type_name       TEXT NOT NULL,
    category        TEXT NOT NULL,
    resilience_category TEXT,
    unit_label      TEXT,
    capacity_config TEXT,
    status_options  TEXT DEFAULT '["AVAILABLE", "IN_USE", "MAINTENANCE"]',
    icon            TEXT,
    color           TEXT DEFAULT 'gray',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, unit_prefix TEXT, label_template TEXT);
CREATE VIEW v_resilience_equipment AS
SELECT
    e.id as equipment_id,
    e.name,
    et.type_code,
    et.type_name,
    et.resilience_category,
    et.capacity_config,
    e.capacity_override,
    u.id as unit_id,
    u.unit_serial,
    u.unit_label,
    u.level_percent,
    u.status,
    u.last_check,
    u.level_percent as effective_percent
FROM equipment e
JOIN equipment_types et ON e.type_code = et.type_code
JOIN equipment_units u ON e.id = u.equipment_id
WHERE et.resilience_category IS NOT NULL
ORDER BY et.resilience_category, e.id, u.unit_serial
/* v_resilience_equipment(equipment_id,name,type_code,type_name,resilience_category,capacity_config,capacity_override,unit_id,unit_serial,unit_label,level_percent,status,last_check,effective_percent) */;
CREATE INDEX idx_equipment_units_last_check ON equipment_units(last_check);
CREATE INDEX idx_equipment_type_code ON equipment(type_code);
CREATE INDEX idx_equipment_types_resilience ON equipment_types(resilience_category);
CREATE TABLE equipment_check_history_backup_20251217(
  id INT,
  equipment_id TEXT,
  unit_label TEXT,
  check_date NUM,
  check_time NUM,
  checked_by TEXT,
  level_before INT,
  level_after INT,
  status_before TEXT,
  status_after TEXT,
  remarks TEXT,
  station_id TEXT,
  created_at NUM
);
CREATE INDEX idx_equipment_check_history_unit_id ON equipment_check_history(unit_id);
CREATE TABLE equipment_lifecycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    unit_id INTEGER,
                    equipment_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('CREATE', 'SOFT_DELETE', 'RESTORE', 'UPDATE')),
                    actor TEXT,
                    reason TEXT,
                    snapshot_json TEXT,
                    correlation_id TEXT,
                    station_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
CREATE INDEX idx_lifecycle_equipment ON equipment_lifecycle_events(equipment_id);
CREATE INDEX idx_lifecycle_unit ON equipment_lifecycle_events(unit_id);
CREATE INDEX idx_lifecycle_time ON equipment_lifecycle_events(created_at DESC);
CREATE UNIQUE INDEX idx_equipment_units_active_serial
                ON equipment_units(equipment_id, unit_serial) WHERE is_active = 1
            ;
CREATE TABLE mirs_mobile_pairing_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    expires_at DATETIME NOT NULL,
                    allowed_roles TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    used INTEGER DEFAULT 0,
                    used_by_device TEXT,
                    used_at DATETIME
                );
CREATE TABLE mirs_mobile_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT UNIQUE NOT NULL,
                    device_name TEXT,
                    staff_id TEXT NOT NULL,
                    staff_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    paired_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen DATETIME,
                    revoked INTEGER DEFAULT 0,
                    revoked_at DATETIME,
                    revoked_reason TEXT
                );
CREATE TABLE mirs_mobile_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT UNIQUE NOT NULL,
                    action_type TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    staff_id TEXT NOT NULL,
                    patient_id TEXT,
                    payload TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    hub_received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'PENDING',
                    adjustment_note TEXT,
                    review_status TEXT DEFAULT 'NOT_REQUIRED',
                    reviewer_staff_id TEXT,
                    reviewed_at DATETIME,
                    station_id TEXT NOT NULL
                );
CREATE INDEX idx_pairing_code ON mirs_mobile_pairing_codes(code);
CREATE INDEX idx_device_id ON mirs_mobile_devices(device_id);
CREATE INDEX idx_action_id ON mirs_mobile_actions(action_id);
CREATE INDEX idx_action_device ON mirs_mobile_actions(device_id);
CREATE VIEW v_equipment_status AS
            SELECT
                e.id, e.name, e.type_code,
                et.type_name, et.category, et.resilience_category,
                et.unit_prefix, et.label_template,
                COUNT(u.id) as unit_count,
                ROUND(AVG(u.level_percent)) as avg_level,
                SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) as checked_count,
                MAX(u.last_check) as last_check,
                CASE
                    WHEN COUNT(u.id) = 0 THEN 'NO_UNITS'
                    WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0 THEN 'UNCHECKED'
                    WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id) THEN 'CHECKED'
                    ELSE 'PARTIAL'
                END as check_status
            FROM equipment e
            LEFT JOIN equipment_types et ON e.type_code = et.type_code
            LEFT JOIN equipment_units u ON e.id = u.equipment_id AND (u.is_active = 1 OR u.is_active IS NULL)
            GROUP BY e.id
/* v_equipment_status(id,name,type_code,type_name,category,resilience_category,unit_prefix,label_template,unit_count,avg_level,checked_count,last_check,check_status) */;

-- ============================================
-- 預設設備類型
-- ============================================
INSERT OR IGNORE INTO equipment_types (type_code, type_name, type_name_en, category, resilience_category, tracking_mode, capacity_config, sort_order) VALUES
('POWER_STATION', '行動電源站', 'Portable Power Station', '電力設備', 'POWER', 'PER_UNIT', '{"strategy":"BATTERY","hours_per_100pct":8}', 1),
('GENERATOR', '發電機', 'Generator', '電力設備', 'POWER', 'PER_UNIT', '{"strategy":"FUEL_BASED","tank_liters":20,"fuel_rate_lph":2}', 2),
('UPS', '不斷電系統', 'UPS', '電力設備', 'POWER', 'PER_UNIT', '{"strategy":"BATTERY","hours_per_100pct":2}', 3),
('O2_CYLINDER_H', 'H型氧氣鋼瓶', 'H-type O2 Cylinder', '呼吸設備', 'OXYGEN', 'PER_UNIT', '{"strategy":"CAPACITY_BASED","hours_per_100pct":24}', 10),
('O2_CYLINDER_E', 'E型氧氣鋼瓶', 'E-type O2 Cylinder', '呼吸設備', 'OXYGEN', 'PER_UNIT', '{"strategy":"CAPACITY_BASED","hours_per_100pct":6}', 11),
('O2_CONCENTRATOR', '氧氣濃縮機', 'O2 Concentrator', '呼吸設備', 'OXYGEN', 'AGGREGATE', '{"strategy":"CONTINUOUS"}', 12),
('VENTILATOR', '呼吸器', 'Ventilator', '呼吸設備', NULL, 'AGGREGATE', NULL, 20),
('MONITOR', '監視器', 'Patient Monitor', '監控設備', NULL, 'AGGREGATE', NULL, 30),
('GENERAL', '一般設備', 'General Equipment', '一般設備', NULL, 'AGGREGATE', NULL, 99);

-- ============================================
-- 預設韌性設定
-- ============================================
INSERT OR IGNORE INTO resilience_config (station_id, isolation_target_days, population_count, population_label) VALUES
('BORP-DNO-01', 3, 2, '插管患者數');

-- ============================================
-- 預設消耗情境
-- ============================================
INSERT OR IGNORE INTO resilience_profiles (station_id, endurance_type, profile_name, burn_rate, burn_rate_unit, is_default, sort_order) VALUES
('BORP-DNO-01', 'OXYGEN', '低流量 (2L/min)', 2, 'L/min', 1, 1),
('BORP-DNO-01', 'OXYGEN', '中流量 (5L/min)', 5, 'L/min', 0, 2),
('BORP-DNO-01', 'OXYGEN', '高流量 (10L/min)', 10, 'L/min', 0, 3),
('BORP-DNO-01', 'POWER', '基本負載 (500W)', 500, 'W', 1, 1),
('BORP-DNO-01', 'POWER', '手術負載 (2000W)', 2000, 'W', 0, 2);

-- ============================================
-- 展示設備
-- ============================================
INSERT OR IGNORE INTO equipment (id, name, type_code, category, status) VALUES
('UTIL-001', '行動電源站', 'POWER_STATION', '電力設備', 'UNCHECKED'),
('UTIL-002', '發電機 (備用)', 'GENERATOR', '電力設備', 'UNCHECKED'),
('RESP-001', '氧氣鋼瓶', 'O2_CYLINDER_H', '呼吸設備', 'UNCHECKED'),
('EMER-EQ-006', '氧氣瓶 (E size)', 'O2_CYLINDER_E', '呼吸設備', 'UNCHECKED'),
('RESP-002', '氧氣濃縮機', 'O2_CONCENTRATOR', '呼吸設備', 'UNCHECKED'),
('DIAG-001', '血壓計 (電子式)', 'MONITOR', '監控設備', 'UNCHECKED'),
('EMER-EQ-001', 'AED 自動體外除顫器', 'GENERAL', '急救設備', 'UNCHECKED');

-- ============================================
-- 展示設備單位
-- ============================================
INSERT OR IGNORE INTO equipment_units (equipment_id, unit_serial, unit_label, level_percent, status, is_active) VALUES
('UTIL-001', 'PWR-001', '電源站1號', 100, 'AVAILABLE', 1),
('UTIL-001', 'PWR-002', '電源站2號', 85, 'AVAILABLE', 1),
('UTIL-002', 'GEN-001', '發電機1號', 100, 'AVAILABLE', 1),
('RESP-001', 'O2H-001', 'H型1號', 100, 'AVAILABLE', 1),
('RESP-001', 'O2H-002', 'H型2號', 75, 'AVAILABLE', 1),
('RESP-001', 'O2H-003', 'H型3號', 50, 'AVAILABLE', 1),
('EMER-EQ-006', 'O2E-001', 'E型1號', 100, 'AVAILABLE', 1),
('EMER-EQ-006', 'O2E-002', 'E型2號', 60, 'AVAILABLE', 1);

