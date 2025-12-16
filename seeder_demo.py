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

    # Check if already seeded
    cursor.execute("SELECT COUNT(*) FROM items")
    if cursor.fetchone()[0] > 0:
        print("[MIRS Seeder] Data already exists, skipping...")
        return

    print("[MIRS Seeder] Seeding demo data...")
    now = datetime.now()

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
    # 4. 設備資料 (equipment)
    # =========================================
    equipment = [
        ("EQ-OL-001", "手術燈 A", "手術室", "operational", "主手術燈"),
        ("EQ-OL-002", "手術燈 B", "手術室", "operational", "輔助手術燈"),
        ("EQ-AM-001", "麻醉機", "手術室", "operational", "Drager Fabius Plus"),
        ("EQ-VM-001", "生理監視器 A", "手術室", "operational", "Philips MX800"),
        ("EQ-VM-002", "生理監視器 B", "恢復室", "standby", "Philips MX500"),
        ("EQ-DF-001", "除顫器", "急診室", "operational", "Philips HeartStart"),
        ("EQ-VT-001", "呼吸器 #1", "ICU", "operational", "Hamilton C6"),
        ("EQ-VT-002", "呼吸器 #2", "ICU", "standby", "Hamilton C3"),
        ("EQ-US-001", "超音波儀", "診療室", "maintenance", "GE Logiq E10"),
        ("EQ-XR-001", "移動式X光", "放射科", "operational", "Siemens Mobilett"),
        ("EQ-SC-001", "抽痰機 A", "病房", "operational", "日本住友"),
        ("EQ-SC-002", "抽痰機 B", "病房", "operational", "日本住友"),
        ("EQ-IF-001", "輸液幫浦 A", "病房", "operational", "Terumo TE-171"),
        ("EQ-IF-002", "輸液幫浦 B", "病房", "standby", "Terumo TE-171"),
        ("EQ-EC-001", "心電圖機", "診療室", "operational", "GE MAC 2000"),
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
    # 7. 韌性設定表 (v1.2.8)
    # =========================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resilience_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            isolation_target_days INTEGER DEFAULT 3,
            oxygen_consumption_rate REAL DEFAULT 10.0,
            fuel_consumption_rate REAL DEFAULT 3.0,
            power_consumption_watts REAL DEFAULT 500.0,
            population_count INTEGER DEFAULT 2,
            population_label TEXT DEFAULT '插管患者數',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO resilience_config
        (station_id, isolation_target_days, oxygen_consumption_rate, fuel_consumption_rate, power_consumption_watts, population_count, population_label)
        VALUES ('BORP-DNO-01', 3, 10.0, 3.0, 500.0, 2, '插管患者數')
    """)

    # =========================================
    # 8. 設備分項追蹤表 (v1.2.8)
    # =========================================
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
    # Seed oxygen cylinder units
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

    # Add tracking_mode column to equipment if not exists
    try:
        cursor.execute("ALTER TABLE equipment ADD COLUMN tracking_mode TEXT DEFAULT 'AGGREGATE'")
    except:
        pass  # Column already exists
    cursor.execute("UPDATE equipment SET tracking_mode = 'PER_UNIT' WHERE id IN ('RESP-001', 'EMER-EQ-006')")

    # =========================================
    # 9. 檢查歷史表 (v1.2.8)
    # =========================================
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

    conn.commit()
    print(f"[MIRS Seeder] Demo data seeded successfully!")
    print(f"  - 15 pharmaceuticals")
    print(f"  - {bag_id-1} blood bags")
    print(f"  - 15 equipment items")
    print(f"  - 20 supply items")
    print(f"  - 3 surgery records")
    print(f"  - Resilience tables (v1.2.8)")
    print(f"  - 9 oxygen cylinder units")


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
