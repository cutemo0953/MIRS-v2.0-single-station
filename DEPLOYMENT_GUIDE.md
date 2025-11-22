# MIRS Deployment Guide
## For Windows .exe and macOS .dmg Installers

---

## Quick Start for Installer Packages

### For Windows (.exe) Installer

**Package Structure:**
```
MIRS_Installer_v1.0/
├── MIRS.exe                    # Main executable
├── config.ini                  # Configuration (copy from template)
├── database/
│   └── profiles/
│       └── government.sql      # Government pharmacy data
├── README.txt
└── LICENSE.txt
```

**Build Command:**
```bash
# Use PyInstaller or similar
pyinstaller --onefile --add-data "config.ini;." --add-data "database;database" main.py
```

### For macOS (.dmg) Installer

**Package Structure:**
```
MIRS.app/
└── Contents/
    ├── MacOS/
    │   └── MIRS
    ├── Resources/
    │   ├── config.ini
    │   └── database/
    │       └── profiles/
    │           └── government.sql
    └── Info.plist
```

**Build Command:**
```bash
# Use py2app
python3 setup.py py2app
```

---

## Configuration for Different Deployments

### 1. Government Compliance Build (Recommended for Distributors)

**Use Case:** Testing, demos, compliance verification

**config.ini:**
```ini
[database]
profile = government
auto_initialize = true
backup_on_start = false

[hospital]
hospital_id = DEMO-001
hospital_name = 示範站
station_id = DEMO-TC-01
```

**Included Data:**
- ✅ Taiwan government pharmacy list (15 medicines)
- ✅ Standard equipment (4 items)
- ❌ No hospital-specific items
- ❌ No test/sample data

**Size:** ~500KB database

---

### 2. Full Testing Build (For Training/Development)

**Use Case:** Staff training, feature demonstration

**config.ini:**
```ini
[database]
profile = testing
auto_initialize = true

[hospital]
hospital_id = TRAIN-001
hospital_name = 訓練醫院
```

**Included Data:**
- ✅ 150 sample items (gloves, gauze, etc.)
- ✅ 15 sample medicines
- ✅ 4 equipment items
- ✅ Sample procedure records
- ✅ Sample blood inventory

**Size:** ~2MB database

---

### 3. Minimal Build (For Custom Import)

**Use Case:** Hospitals with their own item lists

**config.ini:**
```ini
[database]
profile = minimal
auto_initialize = true

[data_import]
import_hospital_items = data/hospital_items.csv
import_custom_medicines = data/medicines.csv
```

**Included Data:**
- ✅ Schema only (no data)
- User imports their own CSV files

**Size:** ~50KB database

---

## Database Profile System

### Auto-Detection Priority

The system checks these sources in order:

1. **Command line:** `--db-profile=government`
2. **Environment variable:** `MIRS_DB_PROFILE=government`
3. **config/db_profile.txt:** Plain text file with profile name
4. **config.ini:** `[database] profile = government`
5. **Default:** `testing`

### Switching Profiles After Installation

**Safe method (with backup):**
```bash
python3 scripts/init_database.py --profile government --backup
```

**Force method (no confirmation):**
```bash
python3 scripts/init_database.py --profile government --force --no-backup
```

**List available profiles:**
```bash
python3 scripts/init_database.py --list
```

---

## Procedure Linking Feature

### What's New

Medications and blood bags can now be linked to procedure records:

**Database Changes:**
- ✅ Added `procedure_id` to `dispense_records`
- ✅ Added `procedure_id` to `blood_events`
- ✅ Created view `v_procedure_complete_summary`
- ✅ Created view `v_procedure_resources`

**UI Updates Coming:**
- Add "關聯處置記錄" dropdown in pharmacy dispense form
- Show "相關藥品" section in procedure details
- Display medication costs in procedure summary

### Usage Example

```python
# When dispensing medication during a procedure
dispense_data = {
    "medicineCode": "MED-001",
    "quantity": 2,
    "dispensedBy": "護理師-王小美",
    "procedure_id": 123,  # ← Link to procedure
    "stationCode": "TC-01"
}
```

### Query Linked Resources

```sql
-- Get all resources used in a procedure
SELECT * FROM v_procedure_resources WHERE procedure_id = 123;

-- Get procedure summary with costs
SELECT * FROM v_procedure_complete_summary WHERE id = 123;
```

---

## For Installer Developers

### Creating Government Profile

**Extract government data:**
```bash
# From existing database
sqlite3 medical_inventory.db ".dump medicines" > database/profiles/government.sql

# Add schema
cat database/schema_pharmacy.sql >> database/profiles/government.sql
```

### Testing Your Installer

**1. Test database initialization:**
```bash
# Remove existing database
rm medical_inventory.db

# Test auto-init
python3 main.py
```

**2. Verify profile loaded:**
```bash
sqlite3 medical_inventory.db "SELECT COUNT(*) FROM medicines"
# Should return 15 for government profile
```

**3. Test procedure linking:**
```bash
sqlite3 medical_inventory.db "PRAGMA table_info(dispense_records)" | grep procedure_id
# Should show: procedure_id column
```

### Including in Installer Package

**Windows (PyInstaller spec file):**
```python
a = Analysis(
    ['main.py'],
    datas=[
        ('config.ini', '.'),
        ('database/profiles/government.sql', 'database/profiles'),
    ],
)
```

**macOS (setup.py for py2app):**
```python
APP = ['main.py']
DATA_FILES = [
    ('config.ini', ['.']) ,
    ('database/profiles', ['database/profiles/government.sql']),
]

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
)
```

---

## User Instructions for Different Scenarios

### Scenario 1: First-Time User (Demo/Testing)

**Steps:**
1. Install MIRS
2. Launch application
3. System auto-creates database with government data
4. Start using immediately

**No manual setup required!**

---

### Scenario 2: Hospital Deployment

**Steps:**
1. Install MIRS
2. Prepare your hospital's item list (CSV format)
3. Run: `python3 scripts/import_data.py --file hospital_items.csv`
4. Customize config.ini with hospital details
5. Start server

---

### Scenario 3: Multi-Station Deployment

**For each station:**
1. Copy MIRS to station computer
2. Edit `config.ini`:
   ```ini
   [hospital]
   station_id = TC-02  # Unique per station
   station_name = 檢傷站2號
   ```
3. Use same database profile (government)
4. Sync data using built-in sync feature

---

## Troubleshooting

### Database Already Exists

**Symptom:** "Database already exists" warning

**Solution:**
```bash
# Option 1: Keep existing data
python3 main.py  # Just use what's there

# Option 2: Reset to profile
python3 scripts/init_database.py --profile government --force
```

### Wrong Profile Loaded

**Check current profile:**
```bash
sqlite3 medical_inventory.db "SELECT COUNT(*) FROM medicines"
# 0 = minimal
# 15 = government
# 150+ = testing
```

**Fix:**
```bash
python3 scripts/init_database.py --profile government --backup
```

### Missing Procedure Links

**Symptom:** `procedure_id` column not found

**Fix:**
```bash
sqlite3 medical_inventory.db < database/migrations/add_procedure_links.sql
```

---

## Best Practices

### For Beta/Testing Distribution
- ✅ Use `government` profile
- ✅ Enable auto-initialize
- ✅ Include README with test credentials
- ✅ Set deployment_type = demo

### For Production Deployment
- ✅ Use `minimal` or `production` profile
- ✅ Provide CSV import templates
- ✅ Change pharmacist PIN
- ✅ Disable debug mode
- ✅ Set deployment_type = production

### For Training Packages
- ✅ Use `testing` profile
- ✅ Include sample data
- ✅ Provide training guide
- ✅ Set deployment_type = testing

---

## Support & Customization

**Need a custom profile?**

Create `database/profiles/custom_hospital.sql` with your data.

**Need to merge multiple sources?**

```bash
python3 scripts/merge_databases.py \
  --source1 government.sql \
  --source2 hospital_items.csv \
  --output custom_profile.sql
```

---

## Version Compatibility

| MIRS Version | Min Profile Version | Migration Required |
|--------------|--------------------|--------------------|
| v1.4.5       | Any                | ✅ add_procedure_links |
| v1.5.0       | government v2      | TBD                 |

---

**Questions?** Check `database/README_DATABASE_PROFILES.md` for detailed profile documentation.
