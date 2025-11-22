# Database Initialization Profiles

## Overview

MIRS supports multiple database initialization profiles for different deployment scenarios.

## Available Profiles

### 1. **minimal** - Bare Minimum
- Empty database with schema only
- No sample data
- For custom manual import
- Size: ~50KB

### 2. **government** - Government Standards
- Taiwan government pharmacy list
- Standard equipment list
- No hospital-specific items
- For compliance testing
- Size: ~500KB

### 3. **testing** - Full Test Data
- Example items (150)
- Sample medicines (15)
- Test equipment (4)
- Sample procedures and blood records
- For development and training
- Size: ~2MB

### 4. **production** - Hospital Deployment
- Government pharmacy list
- Hospital-specific inventory
- Real equipment list
- No test data
- For live deployment

## Usage

### Method 1: Environment Variable

```bash
# Windows
set MIRS_DB_PROFILE=government
python main.py

# macOS/Linux
export MIRS_DB_PROFILE=government
python3 main.py
```

### Method 2: Config File

Create `config/db_profile.txt`:
```
government
```

### Method 3: Command Line

```bash
python3 main.py --db-profile=government
```

### Method 4: Installer Configuration

For `.exe` and `.dmg` installers, include a `config.ini`:

```ini
[database]
profile = government
auto_initialize = true
backup_on_start = false

[hospital]
hospital_id = HOSP-001
hospital_name = 示範醫院
station_id = TC-01
station_name = 急診檢傷站
```

## Profile File Structure

```
database/
├── profiles/
│   ├── minimal.sql          # Empty schema only
│   ├── government.sql       # Gov data
│   ├── testing.sql          # Full test data
│   └── production.sql       # Hospital template
├── data/
│   ├── gov_pharmacy.sql     # Government medicine list
│   ├── gov_equipment.sql    # Standard equipment
│   └── samples/
│       ├── hospital_items_template.csv
│       └── import_hospital_data.py
└── migrations/
    └── add_procedure_links.sql
```

## Switching Profiles

### Safe Profile Switch (with backup):

```bash
python3 scripts/switch_profile.py --profile=government --backup
```

This will:
1. Backup current database
2. Clear all tables
3. Load new profile
4. Verify integrity

### Import Additional Data:

```bash
# Import hospital-specific items
python3 scripts/import_data.py --file=hospital_items.csv --table=items

# Import custom medicines
python3 scripts/import_data.py --file=hospital_meds.csv --table=medicines
```

## For Installer Packages

### Windows (.exe)

Include these files:
```
MIRS_Installer/
├── medical_inventory.exe
├── config.ini              # Profile selection
├── database/
│   └── profiles/
│       ├── government.sql  # Default for installers
│       └── testing.sql     # Optional
└── README.txt
```

### macOS (.dmg)

```
MIRS.app/
└── Contents/
    └── Resources/
        ├── config.ini
        └── database/
            └── profiles/
                └── government.sql
```

## Best Practices

1. **Testing Builds**: Use `testing` profile
2. **Demo/Compliance**: Use `government` profile
3. **Production**: Use `production` profile + hospital CSV import
4. **Development**: Use `testing` profile

## Customization

Users can create custom profiles in `database/profiles/custom_*.sql`

Profile priority:
1. Command line `--db-profile`
2. Environment variable `MIRS_DB_PROFILE`
3. `config/db_profile.txt`
4. `config.ini`
5. Default: `testing`

## Migration Between Profiles

```bash
# Export current data
python3 scripts/export_data.py --output=backup.sql

# Switch profile
python3 scripts/switch_profile.py --profile=government

# Import saved data (merge)
python3 scripts/import_data.py --file=backup.sql --merge
```
