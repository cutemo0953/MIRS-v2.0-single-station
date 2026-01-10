"""
Migration 003: Ensure resilience equipment exists
Extracted from seeder_demo._ensure_resilience_equipment()
"""
from datetime import datetime
from . import migration


@migration(3, "ensure_resilience_equipment")
def apply(cursor):
    """Ensure resilience-critical equipment exists with correct metadata"""
    now = datetime.now().isoformat()

    # Resilience equipment definitions
    # (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, type_code)
    resilience_equipment = [
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
        ("UTIL-003", "光觸媒空氣清淨機", "環境設備", "READY", 1, "AGGREGATE", 10, None, None, None, None, "GENERAL"),
        ("UTIL-004", "淨水器", "環境設備", "READY", 1, "AGGREGATE", None, None, None, None, None, "GENERAL"),
    ]

    for eq in resilience_equipment:
        eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, type_code = eq

        # Check if equipment exists
        cursor.execute("SELECT id FROM equipment WHERE id = ?", (eq_id,))
        if cursor.fetchone() is None:
            # Insert new equipment
            cursor.execute("""
                INSERT INTO equipment
                (id, name, category, status, quantity, tracking_mode, power_watts, capacity_wh, output_watts, fuel_rate_lph, device_type, type_code, last_check, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (eq_id, name, category, status, qty, tracking, pw, cap_wh, out_w, fuel, dev_type, type_code, now, now))
        else:
            # Update existing equipment with resilience columns (force set type_code)
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
