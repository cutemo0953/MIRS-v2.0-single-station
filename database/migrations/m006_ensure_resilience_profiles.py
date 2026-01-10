"""
Migration 006: Ensure resilience consumption profiles exist
Extracted from seeder_demo._seed_resilience_profiles()
"""
from . import migration


@migration(6, "ensure_resilience_profiles")
def apply(cursor):
    """Ensure default resilience consumption profiles exist"""

    # Oxygen Profiles
    # (station_id, endurance_type, profile_name, profile_name_en, burn_rate, burn_rate_unit, population_multiplier, description, is_default, sort_order)
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
        # Idempotent: INSERT OR IGNORE
        cursor.execute("""
            INSERT OR IGNORE INTO resilience_profiles
            (station_id, endurance_type, profile_name, profile_name_en, burn_rate, burn_rate_unit, population_multiplier, description, is_default, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, p)

    # Ensure resilience_config has default station entry
    cursor.execute("""
        INSERT OR IGNORE INTO resilience_config
        (station_id, isolation_target_days, oxygen_consumption_rate, fuel_consumption_rate, power_consumption_watts, population_count, population_label)
        VALUES ('BORP-DNO-01', 3, 10.0, 3.0, 500.0, 2, '插管患者數')
    """)
