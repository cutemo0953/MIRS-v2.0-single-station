# MIRS Deployment Guide

## Quick Start (RPi)

### 1. Initial Setup

```bash
# Clone repository
cd /opt
sudo git clone https://github.com/cutemo0953/xirs-releases.git mirs
cd mirs

# Install dependencies
pip3 install -r requirements.txt

# Make scripts executable
chmod +x scripts/*.sh
```

### 2. Manual Service Setup

```bash
# Copy systemd files
sudo cp deploy/systemd/mirs.service /etc/systemd/system/
sudo cp deploy/systemd/mirs-update.service /etc/systemd/system/
sudo cp deploy/systemd/mirs-update.timer /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable mirs
sudo systemctl start mirs

# Enable auto-update timer
sudo systemctl enable mirs-update.timer
sudo systemctl start mirs-update.timer
```

### 3. Verify

```bash
# Check service status
sudo systemctl status mirs

# Check auto-update timer
sudo systemctl list-timers | grep mirs

# Test API
curl http://localhost:8000/api/dr/health
```

---

## Auto-Update System

### How It Works

```
┌──────────────────────────────────────────────────────────────┐
│  mirs-update.timer (hourly)                                   │
│       │                                                       │
│       ▼                                                       │
│  mirs-update.service                                          │
│       │                                                       │
│       ▼                                                       │
│  scripts/auto-update.sh                                       │
│       │                                                       │
│       ├── 1. git fetch (check for updates)                   │
│       ├── 2. Safety checks (update window, active cases)      │
│       ├── 3. git pull (apply update)                         │
│       ├── 4. systemctl restart mirs                          │
│       ├── 5. Health check (/api/dr/health)                   │
│       └── 6. Rollback if health check fails                  │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Configuration

Edit `/etc/systemd/system/mirs-update.service`:

```ini
[Service]
Environment=MIRS_UPDATE_WINDOW_START=02:00
Environment=MIRS_UPDATE_WINDOW_END=05:00
```

### Manual Update

```bash
# Check for updates only
/opt/mirs/scripts/auto-update.sh --check

# Force update now (ignore time window)
/opt/mirs/scripts/auto-update.sh --force

# View update logs
tail -f /var/log/mirs-update.log
```

### Safety Features

| Feature | Description |
|---------|-------------|
| **Update Window** | Only updates between 02:00-05:00 (configurable) |
| **Active Case Guard** | Won't update if surgeries are in progress |
| **Backup Tags** | Creates git tag before update for rollback |
| **Health Check** | Verifies API responds after restart |
| **Auto-Rollback** | Rolls back if health check fails |

---

## Lifeboat (Disaster Recovery)

All PWAs automatically backup data to iPad's IndexedDB:

- Anesthesia PWA: `/anesthesia/`
- Biomed PWA: `/biomed/`
- Blood Bank PWA: `/blood/`
- Pharmacy PWA: `/pharmacy/`

If RPi is replaced, PWAs will:
1. Detect new `server_uuid`
2. Prompt to restore from local backup
3. Require Admin PIN (default: `888888`)

---

## Troubleshooting

### Service won't start
```bash
# Check logs
journalctl -u mirs -f

# Check port
lsof -i :8000
```

### Update fails
```bash
# Check update log
cat /var/log/mirs-update.log

# Manual rollback
cd /opt/mirs
git tag -l 'backup-*'  # List backup tags
git reset --hard backup-YYYYMMDD-HHMMSS
sudo systemctl restart mirs
```

### Reset to clean state
```bash
cd /opt/mirs
git fetch origin main
git reset --hard origin/main
sudo systemctl restart mirs
```
