# MIRS RPi Deployment Troubleshooting Guide

Version: 1.0
Date: 2026-01-25
Reference: RPi5 Deployment Session

## Issue: "Hub Offline" Status & Modules Not Loading

### Symptoms

1. Web UI shows "Hub 離線" (Hub Offline) even though server responds to health check
2. Server logs show multiple modules disabled:
   ```
   WARNING - 麻醉模組未啟用
   WARNING - 手術代碼模組未啟用
   WARNING - EMT Transfer 模組未啟用
   WARNING - Inventory Engine 模組未啟用
   WARNING - Local Auth 模組未啟用
   WARNING - Blood Bank 模組未啟用
   WARNING - Oxygen Tracking 模組未啟用
   WARNING - OTA Update 模組未啟用
   ```
3. Health check returns OK but frontend reports offline status

### Root Cause

**Missing Python dependency: `httpx`**

The `routes/__init__.py` imports all route modules including `anesthesia.py`. The anesthesia module (line 4126) imports `httpx` for CIRS integration. When `httpx` is not installed:

1. `routes/anesthesia.py` fails to import → `ModuleNotFoundError: No module named 'httpx'`
2. This cascades to `routes/__init__.py` which imports anesthesia
3. All other route modules fail to load because they're imported through `__init__.py`
4. Modules that depend on these routes show as "disabled"
5. Without full module initialization, the frontend detects the hub as "offline"

### Solution

Install the missing dependency:

```bash
pip install httpx
sudo systemctl restart mirs
```

### Prevention

The `requirements_v1.4.5.txt` has been updated to include:

```
# HTTP 客戶端 (async, 用於 CIRS 整合)
httpx>=0.27.0

# PDF 合併/浮水印 (P1-02)
PyPDF2>=3.0.0
```

For fresh installations, always run:

```bash
pip install -r requirements_v1.4.5.txt
```

---

## Common Deployment Issues

### Issue: Port Already in Use

**Symptom:**
```
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8000): address already in use
```

**Cause:** Another process (or systemd service) is already running on that port.

**Solution:**
```bash
# Check what's using the port
sudo ss -tlnp | grep 8000
sudo lsof -i :8000

# If mirs.service is running
sudo systemctl stop mirs

# Then start manually or restart the service
uvicorn main:app --host 0.0.0.0 --port 8000
# OR
sudo systemctl start mirs
```

### Issue: Port Conflict After Multiple Start Attempts

**Symptom:** Port shows as in use but `ss` and `lsof` show nothing.

**Cause:** Socket in TIME_WAIT state or zombie process.

**Solution:**
```bash
# Kill any Python processes
pkill -9 python
pkill -9 uvicorn

# Wait 2 seconds
sleep 2

# Or reboot
sudo reboot
```

### Issue: Database Not Found

**Symptom:** Server starts but shows empty data.

**Cause:** Database file not in expected location.

**Solution:**
```bash
# Check if database exists
ls -la medical_inventory.db

# If missing, initialize
python -c "from main import init_database; init_database()"
```

---

## Deployment Checklist

### Fresh Installation

```bash
# 1. Clone repository
git clone https://github.com/cutemo0953/MIRS-v2.0-single-station.git
cd MIRS-v2.0-single-station

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install ALL dependencies
pip install --upgrade pip
pip install -r requirements_v1.4.5.txt

# 4. Create data directory
sudo mkdir -p /var/lib/mirs
sudo chown $USER:$USER /var/lib/mirs

# 5. Test manually first
uvicorn main:app --host 0.0.0.0 --port 8000

# 6. Verify all modules load
# Look for "已啟用" (enabled) not "未啟用" (disabled)

# 7. Configure systemd service
sudo systemctl enable mirs
sudo systemctl start mirs
```

### Updating Existing Installation

```bash
cd ~/MIRS-v2.0-single-station
source venv/bin/activate

# Pull latest code
git pull origin main

# Update dependencies (important!)
pip install -r requirements_v1.4.5.txt

# Restart service
sudo systemctl restart mirs

# Verify
sudo journalctl -u mirs -f
```

---

## Quick Diagnostic Commands

```bash
# Check service status
sudo systemctl status mirs

# View live logs
sudo journalctl -u mirs -f

# Check module status
sudo journalctl -u mirs --no-pager | grep -E "已啟用|未啟用"

# Test API health
curl -s http://localhost:8000/api/health | python3 -m json.tool

# Test specific module
python -c "from routes.anesthesia import router; print('Anesthesia OK')"
python -c "from routes.oxygen_tracking import router; print('Oxygen OK')"
python -c "from routes.ota import router; print('OTA OK')"

# Check Python dependencies
pip list | grep -E "httpx|PyPDF2|fastapi"
```

---

## Port Configuration

| Service | Default Port | Environment Variable |
|---------|-------------|---------------------|
| MIRS    | 8000        | (hardcoded in main.py) |
| CIRS    | 8090        | - |
| Update Server | 8080 | - |

To run on a different port:
```bash
uvicorn main:app --host 0.0.0.0 --port <PORT>
```

---

## Reference: Required Dependencies

Critical dependencies that must be installed:

| Package | Purpose | Required By |
|---------|---------|-------------|
| `httpx` | Async HTTP client | CIRS integration (anesthesia.py) |
| `PyPDF2` | PDF merging | Watermark feature (P1-02) |
| `reportlab` | PDF generation | All PDF exports |
| `weasyprint` | HTML to PDF | Anesthesia record PDF |
| `pynacl` | Cryptography | xIRS secure protocol |
| `PyJWT` | JWT tokens | Mobile API authentication |

If any module shows "未啟用", test imports to find the missing dependency:

```bash
python -c "from routes.<module_name> import router"
```
