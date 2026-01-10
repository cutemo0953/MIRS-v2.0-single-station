"""
Migration 005: Ensure equipment_units has complete data
Extracted from seeder_demo._seed_equipment_units()
"""
from . import migration


@migration(5, "ensure_equipment_units")
def apply(cursor):
    """Ensure equipment_units table has complete data for PER_UNIT equipment"""

    # === Oxygen Cylinders ===
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

    # === Power Equipment ===
    power_stations = [
        ('UTIL-001', 'PS-001', '電源站1號', 95, 'IN_USE'),
        ('UTIL-001', 'PS-002', '電源站2號', 60, 'CHARGING'),
    ]
    generators = [
        ('UTIL-002', 'GEN-001', '發電機1號', 100, 'AVAILABLE'),
    ]

    # Insert all units (idempotent via INSERT OR IGNORE)
    all_units = h_cylinders + e_cylinders + power_stations + generators
    for eq_id, serial, label, level, status in all_units:
        cursor.execute("""
            INSERT OR IGNORE INTO equipment_units
            (equipment_id, unit_serial, unit_label, level_percent, status, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (eq_id, serial, label, level, status))

    # Ensure all existing units are marked as active
    cursor.execute("UPDATE equipment_units SET is_active = 1 WHERE is_active IS NULL")

    # Sync equipment quantity with actual unit count
    cursor.execute("UPDATE equipment SET quantity = 5 WHERE id = 'RESP-001'")
    cursor.execute("UPDATE equipment SET quantity = 4 WHERE id = 'EMER-EQ-006'")
    cursor.execute("UPDATE equipment SET quantity = 2 WHERE id = 'UTIL-001'")
    cursor.execute("UPDATE equipment SET quantity = 1 WHERE id = 'UTIL-002'")

    # Set PER_UNIT tracking mode for oxygen cylinders and power equipment
    cursor.execute("""
        UPDATE equipment SET tracking_mode = 'PER_UNIT'
        WHERE id IN ('RESP-001', 'EMER-EQ-006', 'UTIL-001', 'UTIL-002')
    """)

    # Create default units for equipment without any units
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
