-- ============================================================================
-- Migration: 離線佇列表
-- Version: 1.2.2
-- Date: 2026-01-20
-- Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md Phase 6
-- ============================================================================

-- ============================================================================
-- 1. 離線事件佇列表 (Offline Event Queue)
-- ============================================================================

CREATE TABLE IF NOT EXISTS offline_event_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 事件識別
    event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,              -- MEDICATION_ADMIN, VITAL_SIGN, CONTROLLED_DRUG, INVENTORY_DEDUCT

    -- 案件關聯
    case_id TEXT,

    -- 事件內容 (JSON)
    payload TEXT NOT NULL,

    -- 客戶端資訊
    client_timestamp TEXT NOT NULL,        -- 客戶端事件時間
    client_uuid TEXT NOT NULL,             -- 客戶端產生的 UUID (用於 idempotency)

    -- 同步狀態
    sync_status TEXT DEFAULT 'PENDING',    -- PENDING, SYNCING, SYNCED, CONFLICT, FAILED
    retry_count INTEGER DEFAULT 0,
    last_retry_at TEXT,
    error_message TEXT,
    synced_at TEXT,

    -- 時間戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 約束
    CHECK(sync_status IN ('PENDING', 'SYNCING', 'SYNCED', 'CONFLICT', 'FAILED'))
);

-- ============================================================================
-- 2. 建立索引
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_offline_queue_status
    ON offline_event_queue(sync_status);

CREATE INDEX IF NOT EXISTS idx_offline_queue_case
    ON offline_event_queue(case_id);

CREATE INDEX IF NOT EXISTS idx_offline_queue_client_uuid
    ON offline_event_queue(client_uuid);

CREATE INDEX IF NOT EXISTS idx_offline_queue_created
    ON offline_event_queue(created_at);

-- ============================================================================
-- 3. 衝突事件表 (需人工處理的衝突)
-- ============================================================================

CREATE TABLE IF NOT EXISTS offline_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 原始事件
    original_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    case_id TEXT,

    -- 衝突詳情
    conflict_type TEXT NOT NULL,           -- DUPLICATE, VERSION_MISMATCH, DATA_CONFLICT
    conflict_details TEXT,                 -- JSON

    -- 解決狀態
    resolution_status TEXT DEFAULT 'PENDING',  -- PENDING, RESOLVED, IGNORED
    resolved_by TEXT,
    resolved_at TEXT,
    resolution_notes TEXT,

    -- 時間戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CHECK(resolution_status IN ('PENDING', 'RESOLVED', 'IGNORED'))
);

CREATE INDEX IF NOT EXISTS idx_offline_conflicts_status
    ON offline_conflicts(resolution_status);

-- ============================================================================
-- 4. 更新 schema version
-- ============================================================================

UPDATE station_metadata SET schema_version = '1.7.2' WHERE station_code IS NOT NULL;

-- ============================================================================
-- 完成
-- ============================================================================
