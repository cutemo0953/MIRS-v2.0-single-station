"""
MIRS Demo Data Seeder
醫療站庫存管理系統展示資料植入
"""
import sqlite3
from datetime import datetime, timedelta
import random

def seed_mirs_demo(conn: sqlite3.Connection):
    """
    植入 MIRS 展示資料

    Args:
        conn: SQLite connection object
    """
    cursor = conn.cursor()
    now = datetime.now()

    # =========================================
    # 0. 確保韌性表格存在 (v1.2.8) - 必須先建立
    # =========================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resilience_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL UNIQUE,
            isolation_target_days REAL DEFAULT 3,
            isolation_source TEXT DEFAULT 'manual',
            population_count INTEGER DEFAULT 2,
            population_label TEXT DEFAULT '插管患者數',
            oxygen_profile_id INTEGER,
            power_profile_id INTEGER,
            reagent_profile_id INTEGER,
            threshold_safe REAL DEFAULT 1.2,
            threshold_warning REAL DEFAULT 1.0,
            oxygen_consumption_rate REAL DEFAULT 10.0,
            fuel_consumption_rate REAL DEFAULT 3.0,
            power_consumption_watts REAL DEFAULT 500.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id TEXT NOT NULL,
            unit_serial TEXT,
            unit_label TEXT,
            level_percent INTEGER DEFAULT 100,
            status TEXT DEFAULT 'AVAILABLE',
            last_check TIMESTAMP,
            checked_by TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id TEXT NOT NULL,
            unit_label TEXT,
            check_date DATE NOT NULL,
            check_time TIMESTAMP NOT NULL,
            checked_by TEXT,
            level_before INTEGER,
            level_after INTEGER,
            status_before TEXT,
            status_after TEXT,
            remarks TEXT,
            station_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # v1.4.2: resilience_profiles 表格 (消耗情境設定)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resilience_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            endurance_type TEXT NOT NULL,
            profile_name TEXT NOT NULL,
            profile_name_en TEXT,
            burn_rate REAL NOT NULL,
            burn_rate_unit TEXT NOT NULL,
            population_multiplier INTEGER DEFAULT 0,
            description TEXT,
            is_default INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # v1.4.2: reagent_open_records 表格 (試劑開封追蹤)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reagent_open_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT NOT NULL,
            batch_number TEXT,
            station_id TEXT NOT NULL,
            opened_at DATETIME NOT NULL,
            tests_remaining INTEGER,
            is_active INTEGER DEFAULT 1,
            notes TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # v1.4.2: Add missing columns to resilience_config (for existing tables)
    config_columns = [
        ("isolation_source", "TEXT DEFAULT 'manual'"),
        ("oxygen_profile_id", "INTEGER"),
        ("power_profile_id", "INTEGER"),
        ("reagent_profile_id", "INTEGER"),
        ("threshold_safe", "REAL DEFAULT 1.2"),
        ("threshold_warning", "REAL DEFAULT 1.0"),
        ("updated_by", "TEXT"),
    ]
    for col_name, col_def in config_columns:
        try:
            cursor.execute(f"ALTER TABLE resilience_config ADD COLUMN {col_name} {col_def}")
        except:
            pass  # Column already exists

    # v1.4.2: Add endurance columns to items table for resilience calculation
    items_columns = [
        ("endurance_type", "TEXT"),              # OXYGEN, POWER, REAGENT
        ("capacity_per_unit", "REAL"),           # Capacity per stock unit
        ("capacity_unit", "TEXT"),               # liters, hours, tests
        ("tests_per_unit", "INTEGER"),           # Tests per unit for reagents
        ("valid_days_after_open", "INTEGER"),    # Valid days after opening
        ("depends_on_item_code", "TEXT"),        # Dependency on other item
        ("dependency_note", "TEXT"),             # Dependency description
    ]
    for col_name, col_def in items_columns:
        try:
            cursor.execute(f"ALTER TABLE items ADD COLUMN {col_name} {col_def}")
        except:
            pass  # Column already exists
    conn.commit()

    # Check if already seeded
    cursor.execute("SELECT COUNT(*) FROM items")
    if cursor.fetchone()[0] > 0:
        print("[MIRS Seeder] Data already exists, ensuring resilience tables...")
        # 確保 resilience_config 有預設值
        cursor.execute("SELECT COUNT(*) FROM resilience_config WHERE station_id = 'BORP-DNO-01'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO resilience_config
                (station_id, isolation_target_days, oxygen_consumption_rate, fuel_consumption_rate, power_consumption_watts, population_count, population_label)
                VALUES ('BORP-DNO-01', 3, 10.0, 3.0, 500.0, 2, '插管患者數')
            """)
        # v1.4.6: 確保韌性關鍵設備存在
        _ensure_resilience_equipment(cursor, now)
        # 確保 equipment_units 有資料
        cursor.execute("SELECT COUNT(*) FROM equipment_units")
        if cursor.fetchone()[0] == 0:
            _seed_equipment_units(cursor)
        # v1.4.2: 確保 resilience_profiles 有預設資料
        cursor.execute("SELECT COUNT(*) FROM resilience_profiles")
        if cursor.fetchone()[0] == 0:
            _seed_resilience_profiles(cursor)
        # v1.4.2: 確保試劑資料存在
        cursor.execute("SELECT COUNT(*) FROM items WHERE endurance_type = 'REAGENT'")
        if cursor.fetchone()[0] == 0:
            _seed_reagent_items(cursor)
        # v1.4.2: 確保電力設備有正確的韌性參數
        _update_power_equipment(cursor)
        conn.commit()
        return

    print("[MIRS Seeder] Seeding demo data...")

    # =========================================
    # 1. 站點設定 (create config table if not exists)
    # =========================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    config_data = [
        ('station_name', '[DEMO] 台北備援手術站'),
        ('station_type', 'BORP'),
        ('station_org', 'DNO'),
        ('station_number', '001'),
        ('demo_mode', 'true'),
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, ?)",
        [(k, v, now.isoformat()) for k, v in config_data]
    )

    # =========================================
    # 2. 藥品資料 (pharmaceuticals)
    # =========================================
    medications = [
        # code, name, generic_name, unit, min_stock, current_stock, category, storage, controlled
        ("MED-ACE500", "Acetaminophen 500mg", "普拿疼", "Tab", 200, 500, "常用藥品", "常溫", "非管制"),
        ("MED-IBU400", "Ibuprofen 400mg", "布洛芬", "Tab", 150, 300, "常用藥品", "常溫", "非管制"),
        ("MED-AMX500", "Amoxicillin 500mg", "安莫西林", "Cap", 100, 200, "常用藥品", "常溫", "非管制"),
        ("MED-MET500", "Metformin 500mg", "Glucophage", "Tab", 100, 150, "常用藥品", "常溫", "非管制"),
        ("MED-AML5", "Amlodipine 5mg", "脈優", "Tab", 100, 200, "常用藥品", "常溫", "非管制"),
        ("MED-OME20", "Omeprazole 20mg", "胃潰寧", "Cap", 150, 250, "常用藥品", "常溫", "非管制"),
        ("MED-CET10", "Cetirizine 10mg", "驅特異", "Tab", 100, 150, "常用藥品", "常溫", "非管制"),
        ("MED-ATR1", "Atropine 1mg", "阿托品", "Amp", 30, 50, "急救藥品", "常溫", "非管制"),
        ("MED-EPI1", "Epinephrine 1mg", "腎上腺素", "Amp", 50, 80, "急救藥品", "冷藏", "非管制"),
        ("MED-LID2", "Lidocaine 2%", "利多卡因", "Amp", 50, 100, "麻醉藥品", "常溫", "非管制"),
        ("MED-PRO10", "Propofol 10mg/ml", "普弗洛", "Vial", 30, 50, "麻醉藥品", "冷藏", "非管制"),
        ("MED-FEN50", "Fentanyl 50mcg", "吩坦尼", "Amp", 20, 30, "麻醉藥品", "常溫", "二級"),
        ("MED-MOR10", "Morphine 10mg", "嗎啡", "Amp", 20, 30, "管制藥品", "常溫", "一級"),
        ("MED-NS500", "Normal Saline 500ml", "生理食鹽水", "Bag", 100, 200, "輸液", "常溫", "非管制"),
        ("MED-RL500", "Ringer Lactate 500ml", "林格氏液", "Bag", 80, 150, "輸液", "常溫", "非管制"),
    ]

    for med in medications:
        code, name, generic, unit, min_stock, current, cat, storage, controlled = med
        cursor.execute("""
            INSERT INTO pharmaceuticals
            (code, name, generic_name, unit, min_stock, current_stock, category, storage_condition, controlled_level, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (code, name, generic, unit, min_stock, current, cat, storage, controlled, now.isoformat()))

        # Add receive event
        cursor.execute("""
            INSERT INTO pharma_events (event_type, pharma_code, quantity, batch_number, expiry_date, operator, timestamp)
            VALUES ('RECEIVE', ?, ?, ?, ?, 'DEMO_SEED', ?)
        """, (code, current, f"DEMO-{code}", (now + timedelta(days=random.randint(180, 730))).strftime("%Y-%m-%d"), now.isoformat()))

    # =========================================
    # 3. 血袋資料 (blood_bags)
    # =========================================
    blood_types = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
    blood_weights = [25, 3, 20, 2, 30, 5, 10, 5]  # 相對數量

    bag_id = 1
    for bt, weight in zip(blood_types, blood_weights):
        qty = max(3, weight // 2)  # 至少 3 袋
        for i in range(qty):
            exp_date = now + timedelta(days=random.randint(7, 35))
            collect_date = now - timedelta(days=random.randint(1, 7))
            cursor.execute("""
                INSERT INTO blood_bags
                (bag_code, blood_type, volume_ml, status, collection_date, expiry_date, donor_id, created_at)
                VALUES (?, ?, 250, 'AVAILABLE', ?, ?, ?, ?)
            """, (
                f"BB-{bag_id:06d}",
                bt,
                collect_date.strftime("%Y-%m-%d"),
                exp_date.strftime("%Y-%m-%d"),
                f"DONOR-{random.randint(1000, 9999)}",
                now.isoformat()
            ))
            bag_id += 1

    # =========================================
    # 4. 設備資料 (equipment) - v1.4.6 新增韌性關鍵設備
    # =========================================
    # 先建立韌性關鍵設備 (氧氣、電力)
    resilience_equipment = [
        # (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type)
        ("RESP-001", "H型氧氣鋼瓶", "呼吸設備", "READY", 5, "PER_UNIT", None, None, None, None, None),
        ("EMER-EQ-006", "E型氧氣瓶", "急救設備", "READY", 4, "PER_UNIT", None, None, None, None, None),
        ("RESP-002", "氧氣濃縮機 5L", "呼吸設備", "READY", 1, "AGGREGATE", 350, None, None, None, "O2_CONCENTRATOR"),
        ("UTIL-001", "行動電源站", "電力設備", "READY", 1, "AGGREGATE", None, 2048, 2000, None, "POWER_STATION"),
        ("UTIL-002", "發電機 (備用)", "電力設備", "READY", 1, "AGGREGATE", None, None, 3000, 1.5, "GENERATOR"),
        ("RESP-003", "呼吸器", "呼吸設備", "READY", 2, "AGGREGATE", 100, None, None, None, None),
        ("OTH-001", "行動冰箱", "冷藏設備", "READY", 1, "AGGREGATE", 60, None, None, None, None),
        ("DIAG-001", "生理監視器", "診斷設備", "READY", 2, "AGGREGATE", 50, None, None, None, None),
        ("EMER-EQ-007", "抽吸機", "急救設備", "READY", 1, "AGGREGATE", 80, None, None, None, None),
        ("RESP-004", "呼吸器 (Transport)", "呼吸設備", "READY", 1, "AGGREGATE", 60, None, None, None, None),
        ("DIAG-002", "血氧機", "診斷設備", "READY", 2, "AGGREGATE", 5, None, None, None, None),
    ]

    for eq in resilience_equipment:
        eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type = eq
        cursor.execute("""
            INSERT INTO equipment
            (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, last_check, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, now.isoformat(), now.isoformat()))

    # 一般設備
    equipment = [
        ("EQ-OL-001", "手術燈 A", "手術室", "operational", "主手術燈"),
        ("EQ-OL-002", "手術燈 B", "手術室", "operational", "輔助手術燈"),
        ("EQ-AM-001", "麻醉機", "手術室", "operational", "Drager Fabius Plus"),
        ("EQ-VM-001", "生理監視器 A", "手術室", "operational", "Philips MX800"),
        ("EQ-VM-002", "生理監視器 B", "恢復室", "standby", "Philips MX500"),
        ("EQ-DF-001", "除顫器", "急診室", "operational", "Philips HeartStart"),
        ("EQ-US-001", "超音波儀", "診療室", "maintenance", "GE Logiq E10"),
        ("EQ-XR-001", "移動式X光", "放射科", "operational", "Siemens Mobilett"),
    ]

    for eq in equipment:
        eq_id, name, category, status, remarks = eq
        # Map status to schema values: UNCHECKED, READY, NEEDS_REPAIR
        status_map = {'operational': 'READY', 'standby': 'READY', 'maintenance': 'NEEDS_REPAIR'}
        mapped_status = status_map.get(status, 'UNCHECKED')
        cursor.execute("""
            INSERT INTO equipment
            (id, name, category, status, remarks, last_check, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (eq_id, name, category, mapped_status, remarks, now.isoformat(), now.isoformat()))

    # =========================================
    # 5. 一般耗材 (items)
    # =========================================
    items = [
        ("SUP-GLV-S", "手套 (S)", "耗材", "Box", 20, 50),
        ("SUP-GLV-M", "手套 (M)", "耗材", "Box", 20, 80),
        ("SUP-GLV-L", "手套 (L)", "耗材", "Box", 20, 60),
        ("SUP-MSK-N95", "N95 口罩", "耗材", "Box", 10, 30),
        ("SUP-MSK-SUR", "醫療口罩", "耗材", "Box", 20, 100),
        ("SUP-GWN-001", "手術衣", "耗材", "EA", 30, 80),
        ("SUP-SYR-3", "注射器 3ml", "耗材", "Box", 10, 50),
        ("SUP-SYR-5", "注射器 5ml", "耗材", "Box", 10, 40),
        ("SUP-SYR-10", "注射器 10ml", "耗材", "Box", 10, 30),
        ("SUP-NDL-22G", "針頭 22G", "耗材", "Box", 10, 40),
        ("SUP-NDL-18G", "針頭 18G", "耗材", "Box", 10, 30),
        ("SUP-GAZ-4x4", "紗布 4x4", "耗材", "Pack", 20, 100),
        ("SUP-BND-3", "繃帶 3吋", "耗材", "Roll", 20, 50),
        ("SUP-TPE-MED", "透氣膠帶", "耗材", "Roll", 20, 60),
        ("SUP-SUL-3-0", "縫線 3-0", "器械", "Box", 5, 20),
        ("SUP-SUL-4-0", "縫線 4-0", "器械", "Box", 5, 15),
        ("SUP-CAT-14", "導尿管 14Fr", "器械", "EA", 10, 25),
        ("SUP-CAT-16", "導尿管 16Fr", "器械", "EA", 10, 20),
        ("SUP-ETT-7", "氣管內管 7.0", "器械", "EA", 5, 15),
        ("SUP-ETT-7.5", "氣管內管 7.5", "器械", "EA", 5, 15),
    ]

    for item in items:
        code, name, cat, unit, min_stock, current = item
        cursor.execute("""
            INSERT INTO items
            (item_code, item_name, item_category, category, unit, min_stock, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (code, name, cat, cat, unit, min_stock, now.isoformat()))

        # Add inventory event
        cursor.execute("""
            INSERT INTO inventory_events
            (event_type, item_code, quantity, batch_number, operator, timestamp)
            VALUES ('RECEIVE', ?, ?, 'DEMO-INIT', 'DEMO_SEED', ?)
        """, (code, current, now.isoformat()))

    # =========================================
    # 5.5 試劑 (Reagents for resilience calculation)
    # =========================================
    # (code, name, category, unit, min_stock, current_stock, tests_per_unit, valid_days_after_open)
    reagents = [
        ("REA-CBC-001", "全血球計數試劑", "檢驗試劑", "Kit", 5, 8, 100, 28),
        ("REA-TROP-001", "心肌旋轉蛋白試劑", "檢驗試劑", "Kit", 3, 5, 25, 14),
        ("REA-GLU-001", "血糖試紙", "檢驗試劑", "Box", 10, 20, 50, None),  # 個別包裝無效期
        ("REA-ABG-001", "血氣分析試劑", "檢驗試劑", "Kit", 3, 4, 25, 7),
        ("REA-COVID-001", "COVID快篩試劑", "檢驗試劑", "Kit", 10, 25, 25, None),
        ("REA-CRP-001", "C反應蛋白試劑", "檢驗試劑", "Kit", 3, 6, 50, 30),
    ]

    for reagent in reagents:
        code, name, cat, unit, min_stock, current, tests_per, valid_days = reagent
        cursor.execute("""
            INSERT INTO items
            (item_code, item_name, item_category, category, unit, min_stock,
             endurance_type, tests_per_unit, valid_days_after_open, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'REAGENT', ?, ?, ?)
        """, (code, name, cat, cat, unit, min_stock, tests_per, valid_days, now.isoformat()))

        # Add inventory event
        cursor.execute("""
            INSERT INTO inventory_events
            (event_type, item_code, quantity, batch_number, operator, timestamp, station_id)
            VALUES ('RECEIVE', ?, ?, 'DEMO-INIT', 'DEMO_SEED', ?, 'BORP-DNO-01')
        """, (code, current, now.isoformat()))

    # =========================================
    # 6. 手術記錄範例
    # =========================================
    surgeries = [
        ("急性闘尾炎切除術", "陳醫師", "全身麻醉", 120, "病患A"),
        ("腹腔鏡膽囊切除術", "林醫師", "全身麻醉", 90, "病患B"),
        ("開放性骨折固定術", "張醫師", "局部麻醉", 180, "病患C"),
    ]

    for i, (surgery_type, surgeon, anesthesia, duration, patient) in enumerate(surgeries):
        surgery_date = (now - timedelta(days=i+1)).strftime("%Y-%m-%d")
        cursor.execute("""
            INSERT INTO surgery_records
            (record_number, record_date, patient_name, surgery_sequence, surgery_type, surgeon_name, anesthesia_type, duration_minutes, station_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BORP-DNO-01', 'COMPLETED', ?)
        """, (
            f"SRG-{surgery_date.replace('-', '')}-{i+1:03d}",
            surgery_date,
            patient,
            i + 1,
            surgery_type,
            surgeon,
            anesthesia,
            duration,
            now.isoformat()
        ))

    # =========================================
    # 7. 韌性資料 (v1.2.8) - 表格已在開頭建立
    # =========================================
    cursor.execute("""
        INSERT OR IGNORE INTO resilience_config
        (station_id, isolation_target_days, oxygen_consumption_rate, fuel_consumption_rate, power_consumption_watts, population_count, population_label)
        VALUES ('BORP-DNO-01', 3, 10.0, 3.0, 500.0, 2, '插管患者數')
    """)
    _seed_equipment_units(cursor)
    _seed_resilience_profiles(cursor)

    conn.commit()
    print(f"[MIRS Seeder] Demo data seeded successfully!")
    print(f"  - 15 pharmaceuticals")
    print(f"  - {bag_id-1} blood bags")
    print(f"  - 15 equipment items")
    print(f"  - 20 supply items")
    print(f"  - 3 surgery records")
    print(f"  - Resilience tables (v1.2.8)")
    print(f"  - 9 oxygen cylinder units")


def _ensure_resilience_equipment(cursor, now):
    """Helper: Ensure resilience equipment exists (v1.4.6)"""
    from datetime import datetime
    if now is None:
        now = datetime.now()

    resilience_equipment = [
        # (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type)
        ("RESP-001", "H型氧氣鋼瓶", "呼吸設備", "READY", 5, "PER_UNIT", None, None, None, None, None),
        ("EMER-EQ-006", "E型氧氣瓶", "急救設備", "READY", 4, "PER_UNIT", None, None, None, None, None),
        ("RESP-002", "氧氣濃縮機 5L", "呼吸設備", "READY", 1, "AGGREGATE", 350, None, None, None, "O2_CONCENTRATOR"),
        ("UTIL-001", "行動電源站", "電力設備", "READY", 1, "AGGREGATE", None, 2048, 2000, None, "POWER_STATION"),
        ("UTIL-002", "發電機 (備用)", "電力設備", "READY", 1, "AGGREGATE", None, None, 3000, 1.5, "GENERATOR"),
        ("RESP-003", "呼吸器", "呼吸設備", "READY", 2, "AGGREGATE", 100, None, None, None, None),
        ("OTH-001", "行動冰箱", "冷藏設備", "READY", 1, "AGGREGATE", 60, None, None, None, None),
        ("DIAG-001", "生理監視器", "診斷設備", "READY", 2, "AGGREGATE", 50, None, None, None, None),
    ]

    for eq in resilience_equipment:
        eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type = eq
        # Check if equipment exists
        cursor.execute("SELECT id FROM equipment WHERE id = ?", (eq_id,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO equipment
                (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, last_check, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, now.isoformat(), now.isoformat()))
        else:
            # Update existing equipment with resilience columns
            cursor.execute("""
                UPDATE equipment SET
                    tracking_mode = COALESCE(tracking_mode, ?),
                    power_watts = COALESCE(power_watts, ?),
                    capacity_wh = COALESCE(capacity_wh, ?),
                    output_watts = COALESCE(output_watts, ?),
                    fuel_rate_lph = COALESCE(fuel_rate_lph, ?),
                    device_type = COALESCE(device_type, ?)
                WHERE id = ?
            """, (tracking, pw, cap_wh, out_w, fuel, dev_type, eq_id))


def _seed_equipment_units(cursor):
    """Helper: Seed oxygen cylinder units"""
    h_cylinders = [
        ('RESP-001', 'H-CYL-001', 'H型1號', 100, 'AVAILABLE'),
        ('RESP-001', 'H-CYL-002', 'H型2號', 85, 'AVAILABLE'),
        ('RESP-001', 'H-CYL-003', 'H型3號', 70, 'IN_USE'),
        ('RESP-001', 'H-CYL-004', 'H型4號', 50, 'AVAILABLE'),
        ('RESP-001', 'H-CYL-005', 'H型5號', 15, 'EMPTY'),
    ]
    e_cylinders = [
        ('EMER-EQ-006', 'E-CYL-001', 'E型1號', 100, 'AVAILABLE'),
        ('EMER-EQ-006', 'E-CYL-002', 'E型2號', 90, 'AVAILABLE'),
        ('EMER-EQ-006', 'E-CYL-003', 'E型3號', 60, 'IN_USE'),
        ('EMER-EQ-006', 'E-CYL-004', 'E型4號', 30, 'AVAILABLE'),
    ]
    for eq_id, serial, label, level, status in h_cylinders + e_cylinders:
        cursor.execute("""
            INSERT OR IGNORE INTO equipment_units (equipment_id, unit_serial, unit_label, level_percent, status)
            VALUES (?, ?, ?, ?, ?)
        """, (eq_id, serial, label, level, status))

    # 同步 equipment 表的 quantity 與實際單位數量
    cursor.execute("""
        UPDATE equipment SET quantity = 5 WHERE id = 'RESP-001'
    """)  # H型 5瓶
    cursor.execute("""
        UPDATE equipment SET quantity = 4 WHERE id = 'EMER-EQ-006'
    """)  # E型 4瓶
    # Add resilience-related columns to equipment if not exist
    columns_to_add = [
        ("tracking_mode", "TEXT DEFAULT 'AGGREGATE'"),
        ("power_watts", "REAL"),           # Power consumption in watts
        ("capacity_wh", "REAL"),           # Battery capacity in watt-hours
        ("output_watts", "REAL"),          # Output power in watts
        ("fuel_rate_lph", "REAL"),         # Fuel consumption rate (liters/hour)
        ("device_type", "TEXT"),           # Device type for classification
    ]
    for col_name, col_def in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE equipment ADD COLUMN {col_name} {col_def}")
        except:
            pass  # Column already exists
    cursor.execute("UPDATE equipment SET tracking_mode = 'PER_UNIT' WHERE id IN ('RESP-001', 'EMER-EQ-006')")


def _seed_resilience_profiles(cursor):
    """Helper: Seed default resilience consumption profiles"""
    # Oxygen Profiles
    oxygen_profiles = [
        ('*', 'OXYGEN', '1位插管患者', '1 Intubated Patient', 10, 'L/min', 1, '標準機械通氣 10 L/min', 1, 1),
        ('*', 'OXYGEN', '2位插管患者', '2 Intubated Patients', 20, 'L/min', 0, '2位患者各10 L/min', 0, 2),
        ('*', 'OXYGEN', '3位插管患者', '3 Intubated Patients', 30, 'L/min', 0, '3位患者各10 L/min', 0, 3),
        ('*', 'OXYGEN', '面罩供氧(3人)', '3 Patients on Mask', 15, 'L/min', 0, '每人約 5 L/min', 0, 4),
        ('*', 'OXYGEN', '鼻導管(5人)', '5 Patients on Nasal', 10, 'L/min', 0, '每人約 2 L/min', 0, 5),
    ]
    # Power Profiles
    power_profiles = [
        ('*', 'POWER', '省電模式', 'Power Saving', 1.5, 'L/hr', 0, '僅照明+呼吸器', 0, 1),
        ('*', 'POWER', '標準運作', 'Normal Operation', 3.0, 'L/hr', 0, '照明+冷藏+基本設備', 1, 2),
        ('*', 'POWER', '全速運轉', 'Full Load', 5.0, 'L/hr', 0, '含空調+檢驗設備', 0, 3),
    ]
    # Reagent Profiles
    reagent_profiles = [
        ('*', 'REAGENT', '平時', 'Normal', 5, 'tests/day', 0, '日常檢驗量', 1, 1),
        ('*', 'REAGENT', '災時增量', 'Disaster Surge', 15, 'tests/day', 0, '災難期間增加', 0, 2),
        ('*', 'REAGENT', '大量傷患', 'Mass Casualty', 30, 'tests/day', 0, '大量傷患應變', 0, 3),
    ]

    all_profiles = oxygen_profiles + power_profiles + reagent_profiles
    for p in all_profiles:
        cursor.execute("""
            INSERT OR IGNORE INTO resilience_profiles
            (station_id, endurance_type, profile_name, profile_name_en, burn_rate, burn_rate_unit, population_multiplier, description, is_default, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, p)


def _seed_reagent_items(cursor):
    """Helper: Seed reagent items with endurance metadata"""
    from datetime import datetime
    now = datetime.now()

    # (code, name, category, unit, min_stock, current_stock, tests_per_unit, valid_days_after_open)
    reagents = [
        ("REA-CBC-001", "全血球計數試劑", "檢驗試劑", "Kit", 5, 8, 100, 28),
        ("REA-TROP-001", "心肌旋轉蛋白試劑", "檢驗試劑", "Kit", 3, 5, 25, 14),
        ("REA-GLU-001", "血糖試紙", "檢驗試劑", "Box", 10, 20, 50, None),
        ("REA-ABG-001", "血氣分析試劑", "檢驗試劑", "Kit", 3, 4, 25, 7),
        ("REA-COVID-001", "COVID快篩試劑", "檢驗試劑", "Kit", 10, 25, 25, None),
        ("REA-CRP-001", "C反應蛋白試劑", "檢驗試劑", "Kit", 3, 6, 50, 30),
    ]

    for reagent in reagents:
        code, name, cat, unit, min_stock, current, tests_per, valid_days = reagent
        cursor.execute("""
            INSERT OR IGNORE INTO items
            (item_code, item_name, item_category, category, unit, min_stock,
             endurance_type, tests_per_unit, valid_days_after_open, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'REAGENT', ?, ?, ?)
        """, (code, name, cat, cat, unit, min_stock, tests_per, valid_days, now.isoformat()))

        # Add inventory event with station_id
        cursor.execute("""
            INSERT OR IGNORE INTO inventory_events
            (event_type, item_code, quantity, batch_number, operator, timestamp, station_id)
            VALUES ('RECEIVE', ?, ?, 'DEMO-INIT', 'DEMO_SEED', ?, 'BORP-DNO-01')
        """, (code, current, now.isoformat()))


def _update_power_equipment(cursor):
    """Helper: Set power metadata for power equipment (generator, power station)"""
    # 行動電源站: 2000Wh capacity, 1000W output
    cursor.execute("""
        UPDATE equipment SET
            capacity_wh = 2000,
            output_watts = 1000,
            device_type = 'POWER_STATION'
        WHERE id = 'UTIL-001'
    """)

    # 發電機: 3.0 L/hr fuel consumption, 2000W output, 50L tank
    cursor.execute("""
        UPDATE equipment SET
            fuel_rate_lph = 3.0,
            output_watts = 2000,
            device_type = 'GENERATOR'
        WHERE id = 'UTIL-002'
    """)

    # 設定耗電設備的功率 (呼吸器、冰箱等)
    power_consumers = [
        ('RESP-002', 350),    # 氧氣濃縮機 350W
        ('RESP-003', 50),     # 呼吸器 50W
        ('OTH-001', 100),     # 冰箱 (藥品) 100W
        ('OTH-002', 150),     # 冰箱 (血液) 150W
        ('DIAG-006', 50),     # 心電圖機 50W
        ('EMER-EQ-007', 100), # 抽吸機 100W
    ]
    for eq_id, watts in power_consumers:
        cursor.execute("""
            UPDATE equipment SET power_watts = ? WHERE id = ?
        """, (watts, eq_id))


def clear_mirs_demo(conn: sqlite3.Connection):
    """清除所有資料 (用於 reset 功能)"""
    cursor = conn.cursor()

    # 清除資料表 (保留結構)
    tables = [
        'items', 'inventory_events',
        'pharmaceuticals', 'pharma_events',
        'blood_bags', 'blood_events',
        'equipment', 'equipment_checks',
        'surgery_records', 'surgery_consumptions',
        'config'
    ]

    for table in tables:
        try:
            cursor.execute(f"DELETE FROM {table}")
        except Exception as e:
            print(f"[MIRS Seeder] Warning: Could not clear {table}: {e}")

    conn.commit()
    print("[MIRS Seeder] All demo data cleared")
