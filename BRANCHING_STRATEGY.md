# MIRS Branching & Release Strategy

## 🎯 Business Model

### Open Source Branch (Public)
**Repository:** `MIRS-Community` (Public GitHub)
**License:** MIT License
**Target Users:** 壯闊台灣, volunteer organizations, research institutions

**Features:**
- ✅ Single-station mode
- ✅ Basic inventory management
- ✅ Blood bank tracking
- ✅ Equipment management
- ✅ Offline-first operation
- ✅ Local SQLite database
- ✅ CSV export/import
- ✅ Master catalog system
- ✅ 4 station profile templates

**Limitations:**
- ❌ No multi-station sync
- ❌ No central server
- ❌ No real-time updates across stations
- ❌ Basic reporting only

---

### Commercial Branch (Private)
**Repository:** `MIRS-Enterprise` (Private GitHub)
**License:** Proprietary
**Target Users:** VGH-Taichung, large hospitals, military

**Additional Features:**
- ✅ **Multi-station synchronization**
  - Real-time sync across 40+ stations
  - Conflict resolution
  - Central server dashboard
- ✅ **Advanced Analytics**
  - Hospital-wide inventory reports
  - Predictive restocking
  - Usage pattern analysis
- ✅ **Enterprise Management**
  - Role-based access control (RBAC)
  - Audit trails
  - Compliance reports
- ✅ **Integration APIs**
  - HIS (Hospital Information System) integration
  - PACS integration
  - HL7/FHIR support
- ✅ **Priority Support**
  - 24/7 technical support
  - Custom feature development
  - On-site training

**Pricing Model:**
- Station license: NT$50,000/year per station
- Hospital package (40 stations): NT$1,500,000/year
- Includes updates, support, and training

---

## 📋 Repository Structure

```
MIRS-Community/ (Public - GitHub)
├── main.py (single-station only)
├── database/
│   ├── schema_general_inventory.sql
│   ├── schema_pharmacy.sql
│   ├── master_catalog.sql
│   └── profiles/
│       ├── health_center.sql
│       ├── surgical_station.sql
│       ├── logistics_hub.sql
│       └── hospital_custom.sql
├── Index.html (no sync features)
├── setup_wizard.html
├── README.md (open source info)
└── LICENSE (MIT)

MIRS-Enterprise/ (Private - GitLab/Bitbucket)
├── main.py (with multi-station features)
├── sync_server.py (central sync server)
├── database/
│   ├── ... (inherits from Community)
│   └── schema_federation.sql (multi-station)
├── Index.html (with sync UI)
├── admin_dashboard.html
├── enterprise/
│   ├── rbac.py
│   ├── analytics.py
│   ├── his_integration.py
│   └── audit_trail.py
└── LICENSE (Proprietary)
```

---

## 🔄 Development Workflow

### Community Branch Development
```bash
# Main development happens here
git checkout main
git commit -m "feat: Add master catalog system"
git push origin main

# Public release
git tag v1.5.0-community
git push --tags
```

### Enterprise Branch Development
```bash
# Periodically merge community improvements
git checkout enterprise
git merge main  # Get latest community features

# Add enterprise-only features
git commit -m "feat: Multi-station sync server"
git push origin enterprise

# Private release
git tag v1.5.0-enterprise
```

### Release Cycle
- **Community:** Monthly releases (open development)
- **Enterprise:** Quarterly releases (stable + enterprise features)

---

## 📦 Installer Distribution

### Community Installers (Free Download)
**macOS:**
```
MIRS-Community-v1.5.0-macOS.dmg
├── Single station only
├── 10MB download
└── https://github.com/your-org/MIRS-Community/releases
```

**Windows:**
```
MIRS-Community-v1.5.0-Windows.exe
├── Single station only
├── 30MB download
└── https://github.com/your-org/MIRS-Community/releases
```

### Enterprise Installers (Licensed)
**Server Package:**
```
MIRS-Enterprise-Server-v1.5.0.exe
├── Central sync server
├── Admin dashboard
├── Requires license key
└── Delivered via secure download link
```

**Client Package:**
```
MIRS-Enterprise-Client-v1.5.0.exe
├── Station client with sync
├── Connects to central server
├── Requires station license
└── Auto-update from server
```

---

## 🎯 Migration Path

### From Community to Enterprise

**Step 1: Export Data**
```python
# Community edition
python3 main.py export --format enterprise
# Creates: station_data_export.json
```

**Step 2: Import to Enterprise**
```python
# Enterprise edition
python3 enterprise_main.py import station_data_export.json
# Preserves all inventory, transactions, equipment
```

**Step 3: Configure Sync**
```bash
# Set central server URL
MIRS_SERVER_URL=https://vgh-tc-sync.example.com
```

---

## 📝 Current Status

### ✅ Community Edition (Ready)
- [x] Single-station core completed
- [x] Master catalog system
- [x] 4 station profiles
- [x] Offline operation
- [x] Basic reporting
- [x] Existing installers (needs update to v1.5)

### 🚧 Enterprise Edition (In Development)
- [ ] Multi-station sync protocol
- [ ] Central server implementation
- [ ] RBAC system
- [ ] Advanced analytics
- [ ] HIS integration APIs
- [ ] Enterprise installer

---

## 🚀 Next Steps

### This Week: Community Edition Polish
1. Update existing installers to v1.5
2. Add master catalog
3. Fix remaining UI bugs
4. Prepare for 壯闊台灣 sharing

### Next Month: Enterprise Development
1. Design sync protocol
2. Build central server
3. Implement RBAC
4. VGH-TC pilot testing

---

## 📄 License Comparison

| Feature | Community (MIT) | Enterprise (Proprietary) |
|---------|----------------|--------------------------|
| Single station | ✅ Free | ✅ Included |
| Multiple stations | ❌ | ✅ Licensed |
| Source code | ✅ Public | ❌ Private |
| Commercial use | ✅ Allowed | ✅ Licensed |
| Support | Community | ✅ Priority 24/7 |
| Updates | ✅ Free | ✅ Included in license |
| Customization | ✅ Fork freely | 🔒 By contract |

---

## 🤝 Contribution Guidelines

### Community Edition
- Anyone can contribute
- Pull requests welcome
- Open issue tracker
- Public roadmap

### Enterprise Edition
- Internal team only
- Private issue tracker
- Confidential roadmap
- NDA required

---

*Last Updated: 2025-11-23*
*Version: 1.0*
*Status: Active Strategy*
