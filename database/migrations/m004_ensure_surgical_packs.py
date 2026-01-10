"""
Migration 004: Ensure BORP surgical packs exist
Extracted from seeder_demo._ensure_surgical_packs()
"""
from datetime import datetime
from . import migration


@migration(4, "ensure_surgical_packs")
def apply(cursor):
    """Ensure BORP surgical packs exist"""
    now = datetime.now().isoformat()

    # BORP surgical pack definitions
    # (id, name, category, quantity, remarks, type_code)
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

        # Idempotent: only insert if not exists
        cursor.execute("SELECT id FROM equipment WHERE id = ?", (pack_id,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO equipment
                (id, name, category, quantity, status, remarks, type_code, last_check, created_at)
                VALUES (?, ?, ?, ?, 'READY', ?, ?, ?, ?)
            """, (pack_id, name, category, qty, remarks, type_code, now, now))
