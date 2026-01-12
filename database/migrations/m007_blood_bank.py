"""
MIRS Blood Bank Migration (m007)
================================

Based on DEV_SPEC_BLOOD_BANK_PWA_v2.0:
- blood_units: 血袋單位表
- transfusion_orders: 輸血醫囑表
- blood_unit_events: 血袋事件表 (Event Sourcing)
- v_blood_availability: 可用性 View
- v_blood_unit_status: 單位狀態 View

All migrations are idempotent.
"""

import sqlite3
from . import migration


@migration(7, "blood_bank_tables_and_views")
def m007_blood_bank(cursor: sqlite3.Cursor):
    """Create Blood Bank tables and views"""

    # =========================================================================
    # Table 1: blood_units (血袋單位表)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blood_units (
            id TEXT PRIMARY KEY,
            blood_type TEXT NOT NULL,          -- A+, A-, B+, B-, O+, O-, AB+, AB-
            unit_type TEXT NOT NULL DEFAULT 'PRBC',  -- PRBC, FFP, PLT, CRYO
            volume_ml INTEGER DEFAULT 250,
            donation_id TEXT,                  -- 捐血編號
            collection_date DATE,
            expiry_date DATE NOT NULL,
            status TEXT DEFAULT 'AVAILABLE',   -- RECEIVED, AVAILABLE, RESERVED, ISSUED, WASTE, QUARANTINE

            -- 預約資訊
            reserved_for_order TEXT,
            reserved_at TIMESTAMP,
            reserved_by TEXT,
            reserve_expires_at TIMESTAMP,

            -- 出庫資訊
            issued_at TIMESTAMP,
            issued_by TEXT,
            issued_to_order TEXT,

            -- 緊急發血標記
            is_emergency_release INTEGER DEFAULT 0,
            is_uncrossmatched INTEGER DEFAULT 0,

            -- 報廢/隔離資訊
            waste_reason TEXT,
            quarantine_reason TEXT,

            -- 存放位置 (可選，與 BioMed 聯動)
            refrigerator_id TEXT,

            -- 稽核
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes for blood_units
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_units_type
        ON blood_units(blood_type, unit_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_units_status
        ON blood_units(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_units_expiry
        ON blood_units(expiry_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_units_order
        ON blood_units(reserved_for_order)
    """)

    # =========================================================================
    # Table 2: transfusion_orders (輸血醫囑表)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transfusion_orders (
            id TEXT PRIMARY KEY,               -- TX-YYYYMMDD-NNN
            cirs_order_id TEXT,                -- CIRS 端的原始 Order ID
            patient_id TEXT,                   -- 只存 ID，不存病患詳細資料
            blood_type TEXT NOT NULL,
            unit_type TEXT DEFAULT 'PRBC',
            quantity INTEGER NOT NULL,
            priority TEXT DEFAULT 'ROUTINE',   -- STAT, URGENT, ROUTINE
            status TEXT DEFAULT 'PENDING',     -- PENDING, CROSSMATCHED, RESERVED, ISSUED, CANCELLED

            -- 履約追蹤 (v2.0 新增)
            reserved_quantity INTEGER DEFAULT 0,
            issued_quantity INTEGER DEFAULT 0,
            fulfilled_at TIMESTAMP,
            cancel_reason TEXT,

            -- 配血資訊
            crossmatch_result TEXT,            -- COMPATIBLE, INCOMPATIBLE
            crossmatch_by TEXT,
            crossmatch_at TIMESTAMP,

            -- 時間戳
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfusion_orders_status
        ON transfusion_orders(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfusion_orders_priority
        ON transfusion_orders(priority)
    """)

    # =========================================================================
    # Table 3: blood_unit_events (血袋事件表 - Event Sourcing)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blood_unit_events (
            id TEXT PRIMARY KEY,
            unit_id TEXT NOT NULL,
            order_id TEXT,
            event_type TEXT NOT NULL,
            -- RECEIVE, RESERVE, UNRESERVE, CROSSMATCH, ISSUE,
            -- RETURN, WASTE, QUARANTINE, RELEASE_QUARANTINE,
            -- EMERGENCY_RELEASE, BLOCK_EXPIRED_ATTEMPT

            actor TEXT NOT NULL,
            reason TEXT,
            metadata TEXT,                     -- JSON
            severity TEXT DEFAULT 'INFO',      -- INFO, WARNING, CRITICAL

            ts_client INTEGER,
            ts_server INTEGER DEFAULT (strftime('%s', 'now')),

            -- 鏈結構 (可選)
            prev_hash TEXT,
            event_hash TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_events_unit
        ON blood_unit_events(unit_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_events_type
        ON blood_unit_events(event_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_blood_events_ts
        ON blood_unit_events(ts_server)
    """)

    # =========================================================================
    # Table 4: crossmatch_log (配血紀錄表)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crossmatch_log (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            blood_unit_id TEXT NOT NULL,
            result TEXT NOT NULL,              -- COMPATIBLE, INCOMPATIBLE
            performed_by TEXT NOT NULL,
            performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_crossmatch_order
        ON crossmatch_log(order_id)
    """)

    # =========================================================================
    # View 1: v_blood_availability (可用性總覽)
    # =========================================================================
    # Drop and recreate to ensure latest definition
    cursor.execute("DROP VIEW IF EXISTS v_blood_availability")
    cursor.execute("""
        CREATE VIEW v_blood_availability AS
        SELECT
            blood_type,
            unit_type,

            -- 物理有效庫存 (不含過期/報廢)
            SUM(CASE
                WHEN status IN ('AVAILABLE', 'RESERVED')
                AND expiry_date > DATE('now', 'localtime')
                THEN 1 ELSE 0
            END) AS physical_valid_count,

            -- 已預約數量
            SUM(CASE
                WHEN status = 'RESERVED'
                AND expiry_date > DATE('now', 'localtime')
                THEN 1 ELSE 0
            END) AS reserved_count,

            -- 真正可用數量 = 物理有效 - 預約
            SUM(CASE
                WHEN status = 'AVAILABLE'
                AND expiry_date > DATE('now', 'localtime')
                THEN 1 ELSE 0
            END) AS available_count,

            -- 即將過期 (3天內)
            SUM(CASE
                WHEN status = 'AVAILABLE'
                AND expiry_date <= DATE('now', '+3 days', 'localtime')
                AND expiry_date > DATE('now', 'localtime')
                THEN 1 ELSE 0
            END) AS expiring_soon_count,

            -- 已過期 (待處理)
            SUM(CASE
                WHEN expiry_date < DATE('now', 'localtime')
                AND status NOT IN ('WASTE', 'ISSUED')
                THEN 1 ELSE 0
            END) AS expired_pending_count,

            -- 最近效期 (FIFO 用)
            MIN(CASE
                WHEN status = 'AVAILABLE'
                AND expiry_date > DATE('now', 'localtime')
                THEN expiry_date
            END) AS nearest_expiry

        FROM blood_units
        WHERE status NOT IN ('WASTE', 'ISSUED')
        GROUP BY blood_type, unit_type
    """)

    # =========================================================================
    # View 2: v_blood_unit_status (單一血袋狀態 - UI 綁定用)
    # =========================================================================
    cursor.execute("DROP VIEW IF EXISTS v_blood_unit_status")
    cursor.execute("""
        CREATE VIEW v_blood_unit_status AS
        SELECT
            bu.id,
            bu.blood_type,
            bu.unit_type,
            bu.volume_ml,
            bu.expiry_date,
            bu.status,
            bu.reserved_for_order,
            bu.reserved_at,
            bu.reserved_by,
            bu.is_emergency_release,
            bu.is_uncrossmatched,
            bu.refrigerator_id,
            bu.created_at,

            -- 計算顯示狀態（單一來源！）
            CASE
                WHEN bu.expiry_date < DATE('now', 'localtime') THEN 'EXPIRED'
                WHEN bu.status = 'RESERVED' THEN 'RESERVED'
                WHEN bu.expiry_date <= DATE('now', '+3 days', 'localtime') THEN 'EXPIRING_SOON'
                WHEN bu.status = 'AVAILABLE' THEN 'AVAILABLE'
                ELSE bu.status
            END AS display_status,

            -- 效期倒數（小時）
            CAST((julianday(bu.expiry_date) - julianday('now', 'localtime')) * 24 AS INTEGER) AS hours_until_expiry,

            -- FIFO 優先級（效期越近越優先）
            ROW_NUMBER() OVER (
                PARTITION BY bu.blood_type, bu.unit_type
                ORDER BY bu.expiry_date ASC
            ) AS fifo_priority

        FROM blood_units bu
        WHERE bu.status NOT IN ('WASTE', 'ISSUED')
    """)

    # =========================================================================
    # Trigger: 自動更新 updated_at
    # =========================================================================
    cursor.execute("DROP TRIGGER IF EXISTS trg_blood_units_updated_at")
    cursor.execute("""
        CREATE TRIGGER trg_blood_units_updated_at
        AFTER UPDATE ON blood_units
        FOR EACH ROW
        BEGIN
            UPDATE blood_units SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END
    """)

    cursor.execute("DROP TRIGGER IF EXISTS trg_transfusion_orders_updated_at")
    cursor.execute("""
        CREATE TRIGGER trg_transfusion_orders_updated_at
        AFTER UPDATE ON transfusion_orders
        FOR EACH ROW
        BEGIN
            UPDATE transfusion_orders SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END
    """)
