-- =============================================================================
-- EMT Transfer Module Schema
-- Version: 1.0.0
-- =============================================================================

-- 1. Transfer Missions (轉送任務)
CREATE TABLE IF NOT EXISTS transfer_missions (
    mission_id TEXT PRIMARY KEY,           -- TRF-20260103-001

    -- 狀態機
    status TEXT DEFAULT 'PLANNING',        -- PLANNING, READY, EN_ROUTE, ARRIVED, COMPLETED, ABORTED

    -- 時間戳記
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ready_at TIMESTAMP,
    departed_at TIMESTAMP,
    arrived_at TIMESTAMP,
    finalized_at TIMESTAMP,

    -- 路程資訊
    origin_station TEXT NOT NULL,
    destination TEXT NOT NULL,
    estimated_duration_min INTEGER NOT NULL,
    actual_duration_min INTEGER,
    transport_mode TEXT DEFAULT 'GROUND',  -- GROUND, AIR, BOAT

    -- 病患資訊
    patient_id TEXT,
    patient_condition TEXT,                -- CRITICAL, STABLE, INTUBATED
    patient_summary TEXT,

    -- 計算參數
    oxygen_requirement_lpm REAL DEFAULT 0,
    iv_rate_mlhr REAL DEFAULT 0,
    ventilator_required INTEGER DEFAULT 0,
    safety_factor REAL DEFAULT 3.0,

    -- 人員
    emt_id TEXT,
    emt_name TEXT,
    device_id TEXT,

    notes TEXT
);

-- 2. Transfer Items (轉送物資清單)
CREATE TABLE IF NOT EXISTS transfer_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,

    -- 物資資訊
    item_type TEXT NOT NULL,               -- OXYGEN, IV_FLUID, MEDICATION, EQUIPMENT, CONSUMABLE
    item_code TEXT,
    item_name TEXT NOT NULL,
    unit TEXT DEFAULT '個',

    -- 數量邏輯 (三階段)
    suggested_qty REAL,
    carried_qty REAL,
    returned_qty REAL,
    consumed_qty REAL,

    -- 狀態追蹤
    initial_status TEXT,
    final_status TEXT,

    -- 計算說明 (可稽核)
    calculation_explain TEXT,

    -- Checklist
    checked INTEGER DEFAULT 0,
    checked_at TIMESTAMP,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);

-- 3. Transfer Events (事件日誌 - Append-Only)
CREATE TABLE IF NOT EXISTS transfer_events (
    event_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,

    -- 事件類型: CREATE, RESERVE, ISSUE, CONSUME, RETURN, INCOMING, ADJUST, ABORT
    type TEXT NOT NULL,

    -- 事件內容
    payload_json TEXT,

    -- 時間與來源
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id TEXT,
    actor_id TEXT,

    -- 同步狀態
    synced INTEGER DEFAULT 0,
    synced_at TIMESTAMP,
    server_seq INTEGER,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);

-- 4. Transfer Incoming Items (外帶物資)
CREATE TABLE IF NOT EXISTS transfer_incoming_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,

    item_type TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT DEFAULT '個',

    source_station TEXT,
    source_notes TEXT,

    condition TEXT DEFAULT 'GOOD',         -- GOOD, DAMAGED, EXPIRED
    oxygen_psi INTEGER,
    battery_percent INTEGER,
    lot_number TEXT,
    expiry_date TEXT,

    processed INTEGER DEFAULT 0,
    processed_at TIMESTAMP,
    inventory_id TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (mission_id) REFERENCES transfer_missions(mission_id)
);

-- 5. Consumption Rates (消耗率設定)
CREATE TABLE IF NOT EXISTS consumption_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    condition TEXT,
    rate REAL NOT NULL,
    rate_unit TEXT NOT NULL,
    notes TEXT
);

-- Seed default consumption rates
INSERT OR IGNORE INTO consumption_rates (item_type, condition, rate, rate_unit, notes) VALUES
('OXYGEN', 'INTUBATED', 10.0, 'L/min', '插管病患'),
('OXYGEN', 'MASK', 6.0, 'L/min', '面罩給氧'),
('OXYGEN', 'NASAL', 2.0, 'L/min', '鼻導管'),
('IV_FLUID', 'TRAUMA', 500.0, 'mL/30min', '創傷輸液'),
('IV_FLUID', 'MAINTAIN', 100.0, 'mL/hr', '維持輸液'),
('IV_FLUID', 'KVO', 30.0, 'mL/hr', 'Keep Vein Open'),
('BATTERY', 'MONITOR', 10.0, '%/hr', '監視器'),
('BATTERY', 'VENTILATOR', 20.0, '%/hr', '呼吸器'),
('BATTERY', 'SUCTION', 15.0, '%/hr', '抽吸器');

-- 6. Add claimed_by_mission_id to equipment_units (for transfer interlock)
-- Note: This is a migration, so we use ALTER TABLE IF NOT EXISTS pattern
-- SQLite doesn't support IF NOT EXISTS for columns, so we handle in Python

-- Indexes
CREATE INDEX IF NOT EXISTS idx_transfer_missions_status ON transfer_missions(status);
CREATE INDEX IF NOT EXISTS idx_transfer_items_mission ON transfer_items(mission_id);
CREATE INDEX IF NOT EXISTS idx_transfer_events_mission ON transfer_events(mission_id);
CREATE INDEX IF NOT EXISTS idx_transfer_events_synced ON transfer_events(synced);

-- 7. Transfer Item Links (連結到實際庫存)
CREATE TABLE IF NOT EXISTS transfer_item_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_item_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL,           -- EQUIPMENT_UNIT, PHARMA, IV_FLUID
    resource_id TEXT NOT NULL,             -- equipment_units.id or pharma code
    reserved_qty REAL DEFAULT 0,
    issued_qty REAL DEFAULT 0,
    returned_qty REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transfer_item_id) REFERENCES transfer_items(id)
);
CREATE INDEX IF NOT EXISTS idx_transfer_item_links_item ON transfer_item_links(transfer_item_id);
CREATE INDEX IF NOT EXISTS idx_transfer_item_links_resource ON transfer_item_links(resource_type, resource_id);
