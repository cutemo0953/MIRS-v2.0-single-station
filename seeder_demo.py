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
            is_active INTEGER DEFAULT 1,
            removed_at TIMESTAMP,
            removed_by TEXT,
            removal_reason TEXT,
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
        # v2.5.7: 確保手術包存在
        _ensure_surgical_packs(cursor, now)
        # v2.8: 確保 equipment_units 有完整資料 (不只是空表，而是所有必要單位)
        # 使用 INSERT OR IGNORE，即使已有部分資料也會補齊缺失的單位
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
    # 4. 設備資料 (equipment) - v1.4.6 新增韌性關鍵設備, v2.0 新增 type_code
    # =========================================
    # 先建立韌性關鍵設備 (氧氣、電力)
    resilience_equipment = [
        # (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, type_code)
        ("RESP-001", "H型氧氣鋼瓶", "呼吸設備", "READY", 5, "PER_UNIT", None, None, None, None, None, "O2_CYLINDER_H"),
        ("EMER-EQ-006", "E型氧氣瓶", "急救設備", "READY", 4, "PER_UNIT", None, None, None, None, None, "O2_CYLINDER_E"),
        ("RESP-002", "氧氣濃縮機 5L", "呼吸設備", "READY", 1, "AGGREGATE", 350, None, None, None, "O2_CONCENTRATOR", "O2_CONCENTRATOR"),
        ("UTIL-001", "行動電源站", "電力設備", "READY", 2, "PER_UNIT", None, 2048, 2000, None, "POWER_STATION", "POWER_STATION"),
        ("UTIL-002", "發電機 (備用)", "電力設備", "READY", 1, "PER_UNIT", None, None, 3000, 1.5, "GENERATOR", "GENERATOR"),
        ("RESP-003", "呼吸器", "呼吸設備", "READY", 2, "AGGREGATE", 100, None, None, None, None, "VENTILATOR"),
        ("OTH-001", "行動冰箱", "冷藏設備", "READY", 1, "AGGREGATE", 60, None, None, None, None, "GENERAL"),
        ("DIAG-001", "生理監視器", "診斷設備", "READY", 2, "AGGREGATE", 50, None, None, None, None, "MONITOR"),
        ("EMER-EQ-007", "抽吸機", "急救設備", "READY", 1, "AGGREGATE", 80, None, None, None, None, "GENERAL"),
        ("RESP-004", "呼吸器 (Transport)", "呼吸設備", "READY", 1, "AGGREGATE", 60, None, None, None, None, "VENTILATOR"),
        ("DIAG-002", "血氧機", "診斷設備", "READY", 2, "AGGREGATE", 5, None, None, None, None, "MONITOR"),
        # v2.8.5: BORP 環境設備
        ("UTIL-003", "光觸媒空氣清淨機", "環境設備", "READY", 1, "AGGREGATE", 10, None, None, None, None, "GENERAL"),  # USB-C 供電
        ("UTIL-004", "淨水器", "環境設備", "READY", 1, "AGGREGATE", None, None, None, None, None, "GENERAL"),  # 非耗電
    ]

    # 確保 equipment 表有 type_code 欄位
    try:
        cursor.execute("ALTER TABLE equipment ADD COLUMN type_code TEXT")
    except:
        pass  # Column already exists

    for eq in resilience_equipment:
        eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, type_code = eq
        cursor.execute("""
            INSERT INTO equipment
            (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, type_code, last_check, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, type_code, now.isoformat(), now.isoformat()))

    # 一般設備 (v2.0 新增 type_code)
    equipment = [
        ("EQ-OL-001", "手術燈 A", "手術室", "operational", "主手術燈", "GENERAL"),
        ("EQ-OL-002", "手術燈 B", "手術室", "operational", "輔助手術燈", "GENERAL"),
        ("EQ-AM-001", "麻醉機", "手術室", "operational", "Drager Fabius Plus", "GENERAL"),
        ("EQ-VM-001", "生理監視器 A", "手術室", "operational", "Philips MX800", "MONITOR"),
        ("EQ-VM-002", "生理監視器 B", "恢復室", "standby", "Philips MX500", "MONITOR"),
        ("EQ-DF-001", "除顫器", "急診室", "operational", "Philips HeartStart", "GENERAL"),
        ("EQ-US-001", "超音波儀", "診療室", "maintenance", "GE Logiq E10", "GENERAL"),
        ("EQ-XR-001", "移動式X光", "放射科", "operational", "Siemens Mobilett", "GENERAL"),
    ]

    # ========== BORP 手術包 (v2.5.7) ==========
    surgical_packs = [
        ("BORP-SURG-001", "共同基本包 (一)", "手術器械", 8, "可重複使用", "GENERAL"),
        ("BORP-SURG-002", "共同基本包 (二)", "手術器械", 8, "可重複使用", "GENERAL"),
        ("BORP-SURG-003", "骨科包", "手術器械", 8, "可重複使用", "GENERAL"),
        ("BORP-SURG-004", "開腹輔助包", "手術器械", 8, "腹部手術專用", "GENERAL"),
        ("BORP-SURG-005", "腹部開創器", "手術器械", 8, "腹部手術專用", "GENERAL"),
        ("BORP-SURG-006", "開胸基本包", "手術器械", 1, "胸腔手術專用", "GENERAL"),
        ("BORP-SURG-007", "血管包", "手術器械", 3, "血管手術專用", "GENERAL"),
        ("BORP-SURG-008", "心外基本包", "手術器械", 4, "心臟手術專用", "GENERAL"),
        ("BORP-SURG-009", "ASSET包", "手術器械", 8, "緊急手術包", "GENERAL"),
        ("BORP-SURG-010", "皮膚縫合包", "手術器械", 2, "傷口縫合專用", "GENERAL"),
        ("BORP-SURG-011", "氣切輔助包", "手術器械", 8, "緊急氣道管理", "GENERAL"),
        ("BORP-SURG-012", "Bull dog血管夾", "手術器械", 4, "血管手術專用", "GENERAL"),
        ("BORP-SURG-013", "顱骨手搖鑽", "手術器械", 1, "神經外科專用", "GENERAL"),
        ("BORP-SURG-014", "鑽/切骨電動工具組", "手術器械", 1, "骨科專用", "GENERAL"),
        ("BORP-SURG-015", "電池式電動骨鑽", "手術器械", 1, "骨科專用", "GENERAL"),
        ("BORP-SURG-016", "電池式電動骨鋸", "手術器械", 3, "骨科專用", "GENERAL"),
    ]
    for pack in surgical_packs:
        pack_id, name, category, qty, remarks, type_code = pack
        cursor.execute("""
            INSERT INTO equipment
            (id, name, category, quantity, status, remarks, type_code, last_check, created_at)
            VALUES (?, ?, ?, ?, 'READY', ?, ?, ?, ?)
        """, (pack_id, name, category, qty, remarks, type_code, now.isoformat(), now.isoformat()))

    for eq in equipment:
        eq_id, name, category, status, remarks, type_code = eq
        # Map status to schema values: UNCHECKED, READY, NEEDS_REPAIR
        status_map = {'operational': 'READY', 'standby': 'READY', 'maintenance': 'NEEDS_REPAIR'}
        mapped_status = status_map.get(status, 'UNCHECKED')
        cursor.execute("""
            INSERT INTO equipment
            (id, name, category, status, remarks, type_code, last_check, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (eq_id, name, category, mapped_status, remarks, type_code, now.isoformat(), now.isoformat()))

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
    print(f"  - 31 equipment items (including 16 surgical packs)")
    print(f"  - 20 supply items")
    print(f"  - 3 surgery records")
    print(f"  - Resilience tables (v1.2.8)")
    print(f"  - 9 oxygen cylinder units")


def _ensure_resilience_equipment(cursor, now):
    """Helper: Ensure resilience equipment exists (v1.4.6, v2.0 新增 type_code)"""
    from datetime import datetime
    if now is None:
        now = datetime.now()

    # 先確保 equipment 表有必要的欄位
    columns_to_add = [
        ("tracking_mode", "TEXT DEFAULT 'AGGREGATE'"),
        ("power_watts", "REAL"),
        ("capacity_wh", "REAL"),
        ("output_watts", "REAL"),
        ("fuel_rate_lph", "REAL"),
        ("device_type", "TEXT"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("type_code", "TEXT"),
    ]
    for col_name, col_def in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE equipment ADD COLUMN {col_name} {col_def}")
        except:
            pass  # Column already exists

    resilience_equipment = [
        # (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, type_code)
        ("RESP-001", "H型氧氣鋼瓶", "呼吸設備", "READY", 5, "PER_UNIT", None, None, None, None, None, "O2_CYLINDER_H"),
        ("EMER-EQ-006", "E型氧氣瓶", "急救設備", "READY", 4, "PER_UNIT", None, None, None, None, None, "O2_CYLINDER_E"),
        ("RESP-002", "氧氣濃縮機 5L", "呼吸設備", "READY", 1, "AGGREGATE", 350, None, None, None, "O2_CONCENTRATOR", "O2_CONCENTRATOR"),
        ("UTIL-001", "行動電源站", "電力設備", "READY", 2, "PER_UNIT", None, 2048, 2000, None, "POWER_STATION", "POWER_STATION"),
        ("UTIL-002", "發電機 (備用)", "電力設備", "READY", 1, "PER_UNIT", None, None, 3000, 1.5, "GENERATOR", "GENERATOR"),
        ("RESP-003", "呼吸器", "呼吸設備", "READY", 2, "AGGREGATE", 100, None, None, None, None, "VENTILATOR"),
        ("OTH-001", "行動冰箱", "冷藏設備", "READY", 1, "AGGREGATE", 60, None, None, None, None, "GENERAL"),
        ("DIAG-001", "生理監視器", "診斷設備", "READY", 2, "AGGREGATE", 50, None, None, None, None, "MONITOR"),
    ]

    for eq in resilience_equipment:
        eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, type_code = eq
        # Check if equipment exists
        cursor.execute("SELECT id FROM equipment WHERE id = ?", (eq_id,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO equipment
                (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, type_code, last_check, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, type_code, now.isoformat(), now.isoformat()))
        else:
            # Update existing equipment with resilience columns - force set type_code
            cursor.execute("""
                UPDATE equipment SET
                    tracking_mode = COALESCE(tracking_mode, ?),
                    power_watts = COALESCE(power_watts, ?),
                    capacity_wh = COALESCE(capacity_wh, ?),
                    output_watts = COALESCE(output_watts, ?),
                    fuel_rate_lph = COALESCE(fuel_rate_lph, ?),
                    device_type = COALESCE(device_type, ?),
                    type_code = ?
                WHERE id = ?
            """, (tracking, pw, cap_wh, out_w, fuel, dev_type, type_code, eq_id))


def _seed_equipment_units(cursor):
    """Helper: Seed oxygen cylinder units and power equipment units (v1.4.7)"""
    # === 氧氣鋼瓶單位 ===
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

    # === v1.4.7: 電力設備單位 ===
    # 行動電源站 (2台，各 2048Wh)
    power_stations = [
        ('UTIL-001', 'PS-001', '電源站1號', 95, 'IN_USE'),      # 95% 供電中
        ('UTIL-001', 'PS-002', '電源站2號', 60, 'CHARGING'),    # 60% 充電中
    ]
    # 發電機 (1台，50L油箱)
    generators = [
        ('UTIL-002', 'GEN-001', '發電機1號', 100, 'AVAILABLE'),  # 油箱滿
    ]

    # 插入所有單位 (v2.1: 加入 is_active)
    all_units = h_cylinders + e_cylinders + power_stations + generators
    for eq_id, serial, label, level, status in all_units:
        cursor.execute("""
            INSERT OR IGNORE INTO equipment_units (equipment_id, unit_serial, unit_label, level_percent, status, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (eq_id, serial, label, level, status))
    # 確保所有現有單位都標記為 active
    cursor.execute("UPDATE equipment_units SET is_active = 1 WHERE is_active IS NULL")

    # 同步 equipment 表的 quantity 與實際單位數量
    cursor.execute("UPDATE equipment SET quantity = 5 WHERE id = 'RESP-001'")   # H型 5瓶
    cursor.execute("UPDATE equipment SET quantity = 4 WHERE id = 'EMER-EQ-006'")  # E型 4瓶
    cursor.execute("UPDATE equipment SET quantity = 2 WHERE id = 'UTIL-001'")   # 電源站 2台
    cursor.execute("UPDATE equipment SET quantity = 1 WHERE id = 'UTIL-002'")   # 發電機 1台

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

    # v1.4.7: 設定 PER_UNIT 追蹤模式 (氧氣鋼瓶 + 電力設備)
    cursor.execute("""
        UPDATE equipment SET tracking_mode = 'PER_UNIT'
        WHERE id IN ('RESP-001', 'EMER-EQ-006', 'UTIL-001', 'UTIL-002')
    """)

    # v2.8.5: 為所有缺少 units 的設備建立預設 unit
    cursor.execute("""
        SELECT e.id, e.name, e.quantity
        FROM equipment e
        LEFT JOIN equipment_units u ON e.id = u.equipment_id
        GROUP BY e.id
        HAVING COUNT(u.id) = 0
    """)
    missing_units = cursor.fetchall()
    for eq_id, name, qty in missing_units:
        qty = qty if qty and qty > 0 else 1
        for i in range(qty):
            unit_serial = f'{eq_id}-{i+1:02d}'
            unit_label = f'{name} #{i+1}' if qty > 1 else name
            cursor.execute("""
                INSERT OR IGNORE INTO equipment_units
                (equipment_id, unit_serial, unit_label, level_percent, status, is_active)
                VALUES (?, ?, ?, 100, 'UNCHECKED', 1)
            """, (eq_id, unit_serial, unit_label))


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


def _ensure_surgical_packs(cursor, now):
    """Helper: Ensure BORP surgical packs exist (v2.5.7)"""
    from datetime import datetime
    if now is None:
        now = datetime.now()

    surgical_packs = [
        ("BORP-SURG-001", "共同基本包 (一)", "手術器械", 8, "可重複使用", "GENERAL"),
        ("BORP-SURG-002", "共同基本包 (二)", "手術器械", 8, "可重複使用", "GENERAL"),
        ("BORP-SURG-003", "骨科包", "手術器械", 8, "可重複使用", "GENERAL"),
        ("BORP-SURG-004", "開腹輔助包", "手術器械", 8, "腹部手術專用", "GENERAL"),
        ("BORP-SURG-005", "腹部開創器", "手術器械", 8, "腹部手術專用", "GENERAL"),
        ("BORP-SURG-006", "開胸基本包", "手術器械", 1, "胸腔手術專用", "GENERAL"),
        ("BORP-SURG-007", "血管包", "手術器械", 3, "血管手術專用", "GENERAL"),
        ("BORP-SURG-008", "心外基本包", "手術器械", 4, "心臟手術專用", "GENERAL"),
        ("BORP-SURG-009", "ASSET包", "手術器械", 8, "緊急手術包", "GENERAL"),
        ("BORP-SURG-010", "皮膚縫合包", "手術器械", 2, "傷口縫合專用", "GENERAL"),
        ("BORP-SURG-011", "氣切輔助包", "手術器械", 8, "緊急氣道管理", "GENERAL"),
        ("BORP-SURG-012", "Bull dog血管夾", "手術器械", 4, "血管手術專用", "GENERAL"),
        ("BORP-SURG-013", "顱骨手搖鑽", "手術器械", 1, "神經外科專用", "GENERAL"),
        ("BORP-SURG-014", "鑽/切骨電動工具組", "手術器械", 1, "骨科專用", "GENERAL"),
        ("BORP-SURG-015", "電池式電動骨鑽", "手術器械", 1, "骨科專用", "GENERAL"),
        ("BORP-SURG-016", "電池式電動骨鋸", "手術器械", 3, "骨科專用", "GENERAL"),
    ]

    for pack in surgical_packs:
        pack_id, name, category, qty, remarks, type_code = pack
        cursor.execute("SELECT id FROM equipment WHERE id = ?", (pack_id,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO equipment
                (id, name, category, quantity, status, remarks, type_code, last_check, created_at)
                VALUES (?, ?, ?, ?, 'READY', ?, ?, ?, ?)
            """, (pack_id, name, category, qty, remarks, type_code, now.isoformat(), now.isoformat()))


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


def seed_anesthesia_demo(conn: sqlite3.Connection):
    """
    植入麻醉模組測試資料 (v2.1.2)
    包含完整的 vital signs、藥物、IV 等事件資料

    Args:
        conn: SQLite connection object

    Usage:
        python -c "import sqlite3; from seeder_demo import seed_anesthesia_demo; conn = sqlite3.connect('medical_inventory.db'); seed_anesthesia_demo(conn)"
    """
    import json
    import uuid

    cursor = conn.cursor()
    now = datetime.now()

    # Check if anesthesia_cases table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='anesthesia_cases'")
    if cursor.fetchone() is None:
        print("[Anesthesia Seeder] anesthesia_cases table not found. Please start MIRS first to initialize tables.")
        return

    # Check if already seeded
    cursor.execute("SELECT COUNT(*) FROM anesthesia_cases WHERE id LIKE 'ANES-SEED-%'")
    if cursor.fetchone()[0] > 0:
        print("[Anesthesia Seeder] Demo cases already exist. Use clear_anesthesia_demo() first to re-seed.")
        return

    print("[Anesthesia Seeder] Seeding anesthesia demo cases with events...")

    def gen_event_id():
        return f"EVT-{uuid.uuid4().hex[:12].upper()}"

    # === Case 1: 進行中案例 (有完整資料) ===
    case1_start = now - timedelta(hours=2)
    case1_id = "ANES-SEED-001"

    cursor.execute("""
        INSERT INTO anesthesia_cases
        (id, patient_id, patient_name, diagnosis, operation,
         context_mode, planned_technique, asa_classification,
         status, anesthesia_start_at, surgery_start_at,
         created_at, created_by)
        VALUES (?, ?, ?, ?, ?, 'STANDARD', ?, ?, 'IN_PROGRESS', ?, ?, ?, 'SEED')
    """, (
        case1_id, "P-TEST-001", "陳大明",
        "急性闘尾炎", "腹腔鏡闘尾切除術",
        "GA_ETT", "II",
        (case1_start).isoformat(),
        (case1_start + timedelta(minutes=30)).isoformat(),
        now.isoformat()
    ))

    # Vital signs (每 15 分鐘)
    vitals_data = [
        (0, 120, 80, 72, 99, 35, 36.5),
        (15, 115, 75, 68, 100, 34, 36.4),
        (30, 110, 70, 65, 100, 33, 36.3),
        (45, 108, 68, 62, 99, 34, 36.2),
        (60, 112, 72, 64, 100, 35, 36.2),
        (75, 118, 76, 68, 99, 34, 36.3),
        (90, 122, 78, 72, 100, 35, 36.4),
        (105, 125, 80, 75, 99, 36, 36.5),
    ]
    for mins, sbp, dbp, hr, spo2, etco2, temp in vitals_data:
        event_time = case1_start + timedelta(minutes=mins)
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'VITAL_SIGN', ?, ?, 'SEED')
        """, (
            gen_event_id(), case1_id, event_time.isoformat(),
            json.dumps({"bp_sys": sbp, "bp_dia": dbp, "hr": hr, "spo2": spo2, "etco2": etco2, "temp": temp})
        ))

    # Medications
    meds = [
        (0, "Propofol", "150", "mg", "IV"),
        (1, "Fentanyl", "100", "mcg", "IV"),
        (2, "Rocuronium", "50", "mg", "IV"),
        (5, "Sevoflurane", "2", "%", "INH"),
        (45, "Fentanyl", "50", "mcg", "IV"),
        (90, "Ondansetron", "4", "mg", "IV"),
    ]
    for mins, drug, dose, unit, route in meds:
        event_time = case1_start + timedelta(minutes=mins)
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'MEDICATION_ADMIN', ?, ?, 'SEED')
        """, (
            gen_event_id(), case1_id, event_time.isoformat(),
            json.dumps({"drug_name": drug, "dose": dose, "unit": unit, "route": route})
        ))

    # IV Line
    cursor.execute("""
        INSERT INTO anesthesia_events
        (id, case_id, event_type, clinical_time, payload, actor_id)
        VALUES (?, ?, 'IV_ACCESS', ?, ?, 'SEED')
    """, (
        gen_event_id(), case1_id, case1_start.isoformat(),
        json.dumps({"line_number": 1, "site": "右手背", "gauge": "20G", "catheter_type": "PERIPHERAL"})
    ))

    # I/O Balance
    cursor.execute("""
        INSERT INTO anesthesia_events
        (id, case_id, event_type, clinical_time, payload, actor_id)
        VALUES (?, ?, 'FLUID_IN', ?, ?, 'SEED')
    """, (
        gen_event_id(), case1_id, (case1_start + timedelta(minutes=30)).isoformat(),
        json.dumps({"fluid_type": "crystalloid", "fluid_name": "Normal Saline", "volume_ml": 500})
    ))
    cursor.execute("""
        INSERT INTO anesthesia_events
        (id, case_id, event_type, clinical_time, payload, actor_id)
        VALUES (?, ?, 'FLUID_IN', ?, ?, 'SEED')
    """, (
        gen_event_id(), case1_id, (case1_start + timedelta(minutes=90)).isoformat(),
        json.dumps({"fluid_type": "crystalloid", "fluid_name": "Lactated Ringer", "volume_ml": 500})
    ))
    cursor.execute("""
        INSERT INTO anesthesia_events
        (id, case_id, event_type, clinical_time, payload, actor_id)
        VALUES (?, ?, 'OUTPUT', ?, ?, 'SEED')
    """, (
        gen_event_id(), case1_id, (case1_start + timedelta(minutes=100)).isoformat(),
        json.dumps({"output_type": "urine", "volume_ml": 200})
    ))

    # === Case 2-5: PREOP 案例 (待開刀) ===
    preop_cases = [
        ("ANES-SEED-002", "P-TEST-002", "林小華", "膽結石併膽囊炎", "腹腔鏡膽囊切除術", "GA_LMA", "II"),
        ("ANES-SEED-003", "P-TEST-003", "張美玲", "右側腹股溝疝氣", "腹腔鏡疝氣修補術", "RA_SPINAL", "I"),
        ("ANES-SEED-004", "P-TEST-004", "王建國", "右側股骨頸骨折", "人工髖關節置換術", "RA_SPINAL", "III"),
        ("ANES-SEED-005", "P-TEST-005", "李淑芬", "子宮肌瘤", "腹腔鏡子宮肌瘤切除術", "GA_ETT", "II"),
    ]

    for case_id, patient_id, name, dx, op, tech, asa in preop_cases:
        cursor.execute("""
            INSERT INTO anesthesia_cases
            (id, patient_id, patient_name, diagnosis, operation,
             context_mode, planned_technique, asa_classification,
             status, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, 'STANDARD', ?, ?, 'PREOP', ?, 'SEED')
        """, (case_id, patient_id, name, dx, op, tech, asa, now.isoformat()))

    # === Case 6: 長時間手術 (4.5小時，測試多頁 PDF) ===
    # 完整的 AAA 修補手術案例，包含所有欄位
    case6_start = now - timedelta(hours=5)
    case6_id = "ANES-SEED-006"

    cursor.execute("""
        INSERT INTO anesthesia_cases
        (id, patient_id, patient_name,
         patient_gender, patient_age, patient_weight, patient_height, blood_type, asa_class,
         diagnosis, operation, or_room, surgeon_name,
         preop_hb, preop_ht, preop_k, preop_na,
         estimated_blood_loss, blood_prepared, blood_prepared_units,
         context_mode, planned_technique,
         primary_anesthesiologist_name, primary_nurse_name,
         status, anesthesia_start_at, surgery_start_at, surgery_end_at, anesthesia_end_at,
         created_at, created_by)
        VALUES (?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                'STANDARD', ?,
                ?, ?,
                'CLOSED', ?, ?, ?, ?, ?, 'SEED')
    """, (
        case6_id, "P-TEST-006", "黃志明",
        "M", 68, 72.5, 168, "A+", "III",
        "主動脈瘤 (AAA)", "開腹主動脈瘤修補術 + 雙側髂動脈人工血管置換", "OR-3", "張心外醫師",
        13.5, 40, 4.0, 140,
        1500, "A+", "4U pRBC, 4U FFP, 6U PLT",
        "GA_ETT",
        "李麻醉醫師", "王護理師",
        case6_start.isoformat(),
        (case6_start + timedelta(minutes=30)).isoformat(),
        (case6_start + timedelta(hours=4, minutes=30)).isoformat(),
        (case6_start + timedelta(hours=5)).isoformat(),
        now.isoformat()
    ))

    # Vital signs 每 10 分鐘, 共 30 筆 (5小時)
    import random
    long_vitals = []
    for i in range(31):  # 0, 10, 20, ... 300 分鐘
        mins = i * 10
        # 模擬手術中血壓波動
        if mins < 30:  # 誘導期
            sbp = 130 - (mins // 10) * 8
            dbp = 85 - (mins // 10) * 5
            hr = 75 - (mins // 10) * 3
        elif mins < 120:  # 手術早期穩定
            sbp = 105 + random.randint(-5, 5)
            dbp = 65 + random.randint(-3, 3)
            hr = 60 + random.randint(-3, 5)
        elif mins < 180:  # 主動脈鉗夾期 - 血壓上升
            sbp = 140 + random.randint(-8, 8)
            dbp = 85 + random.randint(-5, 5)
            hr = 70 + random.randint(-5, 8)
        elif mins < 240:  # 解除鉗夾期 - 血壓下降風險
            sbp = 95 + random.randint(-10, 15)
            dbp = 55 + random.randint(-5, 8)
            hr = 85 + random.randint(-5, 10)
        else:  # 恢復期
            sbp = 115 + random.randint(-5, 10)
            dbp = 70 + random.randint(-3, 5)
            hr = 72 + random.randint(-3, 5)

        spo2 = 99 if random.random() > 0.1 else 98
        etco2 = 34 + random.randint(-2, 2)
        temp = 36.0 + (mins / 600)  # 體溫慢慢下降後回升
        if temp < 35.5:
            temp = 35.5
        if mins > 200:
            temp = 36.2 + random.random() * 0.3

        long_vitals.append((mins, sbp, dbp, hr, spo2, etco2, round(temp, 1)))

    for mins, sbp, dbp, hr, spo2, etco2, temp in long_vitals:
        event_time = case6_start + timedelta(minutes=mins)
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'VITAL_SIGN', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, event_time.isoformat(),
            json.dumps({"bp_sys": sbp, "bp_dia": dbp, "hr": hr, "spo2": spo2, "etco2": etco2, "temp": temp})
        ))

    # 長手術藥物 (多次追加)
    long_meds = [
        (0, "Propofol", "200", "mg", "IV"),
        (1, "Fentanyl", "150", "mcg", "IV"),
        (2, "Rocuronium", "60", "mg", "IV"),
        (5, "Sevoflurane", "2", "%", "INH"),
        (30, "Fentanyl", "50", "mcg", "IV"),
        (60, "Rocuronium", "20", "mg", "IV"),
        (90, "Fentanyl", "50", "mcg", "IV"),
        (120, "Rocuronium", "20", "mg", "IV"),  # 鉗夾前
        (125, "Mannitol", "100", "g", "IV"),     # 腎臟保護
        (130, "Heparin", "5000", "U", "IV"),     # 抗凝
        (150, "Fentanyl", "50", "mcg", "IV"),
        (180, "Rocuronium", "20", "mg", "IV"),
        (185, "Protamine", "50", "mg", "IV"),    # 解抗凝
        (200, "Norepinephrine", "4", "mcg/min", "IV"),  # 升壓
        (210, "Fentanyl", "50", "mcg", "IV"),
        (230, "Calcium gluconate", "1", "g", "IV"),  # 輸血後
        (250, "Ondansetron", "8", "mg", "IV"),
        (270, "Sugammadex", "200", "mg", "IV"),  # 逆轉肌鬆
    ]
    for mins, drug, dose, unit, route in long_meds:
        event_time = case6_start + timedelta(minutes=mins)
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'MEDICATION_ADMIN', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, event_time.isoformat(),
            json.dumps({"drug_name": drug, "dose": dose, "unit": unit, "route": route})
        ))

    # IV Lines (雙路 + 中央靜脈)
    ivs = [
        (0, 1, "左手背", "18G", "PERIPHERAL"),
        (5, 2, "右前臂", "16G", "PERIPHERAL"),
        (25, 3, "右頸內靜脈", "7Fr", "CENTRAL"),
    ]
    for mins, line_num, site, gauge, ctype in ivs:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'IV_ACCESS', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"line_number": line_num, "site": site, "gauge": gauge, "catheter_type": ctype})
        ))

    # I/O Balance (大手術大量輸液)
    # fluid_type 需使用可識別的關鍵字: NS, LR, D5W (晶體), VOLUVEN, ALBUMIN (膠體), PRBC, FFP, PLT (血品)
    fluids_in = [
        (30, "NS", "Normal Saline 0.9%", 1000),
        (60, "LR", "Lactated Ringer", 1000),
        (100, "LR", "Lactated Ringer", 500),
        (140, "VOLUVEN", "Voluven 6%", 500),
        (180, "LR", "Lactated Ringer", 1000),
        (200, "PRBC", "pRBC Unit 1 (A+)", 280),
        (215, "PRBC", "pRBC Unit 2 (A+)", 280),
        (220, "LR", "Lactated Ringer", 500),
        (240, "PRBC", "pRBC Unit 3 (A+)", 280),
        (250, "FFP", "FFP Unit 1 (A+)", 220),
        (260, "FFP", "FFP Unit 2 (A+)", 220),
        (275, "ALBUMIN", "Albumin 20% 100mL", 100),
    ]
    for mins, ftype, fname, vol in fluids_in:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'FLUID_IN', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"fluid_type": ftype, "fluid_name": fname, "volume_ml": vol})
        ))

    # 輸出: 尿量 + 失血
    outputs = [
        (60, "urine", 100),
        (120, "urine", 150),
        (150, "blood_loss", 300),  # 手術中失血
        (180, "blood_loss", 400),
        (200, "urine", 100),
        (210, "blood_loss", 200),
        (240, "urine", 200),
        (280, "urine", 150),
    ]
    for mins, otype, vol in outputs:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'OUTPUT', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"output_type": otype, "volume_ml": vol})
        ))

    # === 新增：呼吸器設定 (VENT_SETTING_CHANGE) ===
    vent_settings = [
        (5, "VCV", 50, 5, 500, 12),    # 誘導後: VCV, FiO2 50%, PEEP 5, TV 500, RR 12
        (60, "VCV", 45, 5, 500, 12),   # 穩定: 降 FiO2
        (120, "VCV", 50, 8, 500, 14),  # 鉗夾期: 增 PEEP/RR
        (180, "VCV", 60, 10, 500, 16), # 解鉗夾: 增 FiO2
        (240, "VCV", 45, 5, 500, 12),  # 恢復
        (280, "CPAP", 40, 5, None, None),  # 準備拔管
    ]
    for mins, mode, fio2, peep, tv, rr in vent_settings:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'VENT_SETTING_CHANGE', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"mode": mode, "fio2": fio2, "peep": peep, "tv": tv, "rr": rr})
        ))

    # === 新增：吸入麻醉劑設定 (Agents - 用 AGENT_SETTING 事件) ===
    agent_settings = [
        (5, 2, 2.0, 0),      # O2 2L, Sevo 2%, Air 0
        (30, 2, 1.5, 1),     # 維持: Sevo 降到 1.5%
        (60, 2, 1.2, 1),
        (120, 2, 1.5, 1),    # 鉗夾期: 稍增
        (180, 2, 1.0, 1),    # 解鉗夾
        (240, 2, 0.8, 1),    # 準備醒
        (270, 2, 0.5, 2),    # 甦醒期
        (290, 3, 0, 0),      # 停 Sevo, 純氧
    ]
    for mins, o2_flow, sevo_percent, air_flow in agent_settings:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'AGENT_SETTING', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"o2_flow": o2_flow, "sevo_percent": sevo_percent, "air_flow": air_flow, "des_percent": 0})
        ))

    # === 新增：監測器啟動 (MONITOR_STARTED) ===
    monitors = [
        (0, "EKG", "5-lead"),
        (0, "NIBP", "左上臂"),
        (0, "SpO2", "右食指"),
        (0, "TEMP", "鼻咽"),
        (5, "ETCO2", "主流式"),
        (25, "ART", "左橈動脈"),
        (25, "CVP", "右頸內靜脈"),
        (30, "FOLEY", "14Fr"),
        (30, "AIR_BLANKET", "上半身"),
    ]
    for mins, monitor_type, location in monitors:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'MONITOR_STARTED', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"monitor_type": monitor_type, "location": location})
        ))

    # === 新增：實驗室數據 (LAB_RESULT_POINT) ===
    lab_data = [
        # (mins, hb, hct, ph, pco2, po2, hco3, be, na, k, ca, glucose)
        (0, 13.5, 40, None, None, None, None, None, 140, 4.0, 2.2, 110),  # 術前
        (60, 12.8, 38, 7.38, 42, 180, 24, -1, 139, 4.2, 2.1, 125),        # ABG #1
        (150, 10.2, 30, 7.32, 38, 220, 20, -4, 138, 4.8, 1.9, 145),       # 失血後
        (220, 9.8, 29, 7.28, 35, 250, 18, -6, 136, 5.2, 2.0, 160),        # 輸血中
        (280, 11.5, 34, 7.35, 40, 200, 22, -2, 138, 4.5, 2.1, 140),       # 輸血後
    ]
    for mins, hb, hct, ph, pco2, po2, hco3, be, na, k, ca, glucose in lab_data:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'LAB_RESULT_POINT', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({
                "hb": hb, "hct": hct, "ph": ph, "pco2": pco2, "po2": po2,
                "hco3": hco3, "be": be, "na": na, "k": k, "ca": ca, "glucose": glucose
            })
        ))

    # === 新增：麻醉/手術時間事件 ===
    time_events = [
        (0, "ANESTHESIA_START"),
        (30, "SURGERY_START"),
        (270, "SURGERY_END"),
        (300, "ANESTHESIA_END"),
    ]
    for mins, etype in time_events:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, etype, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"time": (case6_start + timedelta(minutes=mins)).isoformat()})
        ))

    # === 新增：人員指派事件 ===
    staff_events = [
        (0, "ANESTHESIOLOGIST", "李麻醉醫師"),
        (0, "NURSE", "王護理師"),
    ]
    for mins, role, name in staff_events:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'STAFF_ASSIGNED', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps({"role": role, "name": name})
        ))

    # === 新增：Lab/ABG 檢驗結果事件 ===
    lab_events = [
        # (分鐘, ABG 資料)
        (30, {  # 插管後 ABG
            "test_type": "ABG",
            "specimen": "arterial",
            "ph": 7.38, "po2": 185, "pco2": 38,
            "hco3": 22.5, "be": -1.5,
            "na": 140, "k": 3.8, "ca": 9.2, "glucose": 128,
            "hb": 11.2, "hct": 33.6
        }),
        (150, {  # 輸血中 ABG
            "test_type": "ABG",
            "specimen": "arterial",
            "ph": 7.32, "po2": 165, "pco2": 42,
            "hco3": 21.0, "be": -3.5,
            "na": 138, "k": 4.2, "ca": 8.8, "glucose": 145,
            "hb": 9.8, "hct": 29.4
        }),
        (240, {  # 手術結束前 ABG
            "test_type": "ABG",
            "specimen": "arterial",
            "ph": 7.36, "po2": 175, "pco2": 40,
            "hco3": 22.0, "be": -2.0,
            "na": 139, "k": 4.0, "ca": 9.0, "glucose": 135,
            "hb": 10.5, "hct": 31.5
        }),
    ]
    for mins, lab_data in lab_events:
        cursor.execute("""
            INSERT INTO anesthesia_events
            (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, 'LAB_RESULT_POINT', ?, ?, 'SEED')
        """, (
            gen_event_id(), case6_id, (case6_start + timedelta(minutes=mins)).isoformat(),
            json.dumps(lab_data)
        ))

    conn.commit()
    print(f"[Anesthesia Seeder] Created 6 demo cases:")
    print(f"  - ANES-SEED-001: 陳大明 (IN_PROGRESS, 8 vitals, 6 meds, IV, I/O)")
    print(f"  - ANES-SEED-002: 林小華 (PREOP)")
    print(f"  - ANES-SEED-003: 張美玲 (PREOP)")
    print(f"  - ANES-SEED-004: 王建國 (PREOP)")
    print(f"  - ANES-SEED-005: 李淑芬 (PREOP)")
    print(f"  - ANES-SEED-006: 黃志明 (CLOSED, 4.5hr長手術, 31 vitals, 18 meds, 3 ABG, 3 IV lines, 血品輸注)")


def clear_anesthesia_demo(conn: sqlite3.Connection):
    """清除麻醉測試資料"""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM anesthesia_events WHERE case_id LIKE 'ANES-SEED-%'")
    cursor.execute("DELETE FROM anesthesia_cases WHERE id LIKE 'ANES-SEED-%'")
    conn.commit()
    print("[Anesthesia Seeder] Demo cases cleared")
