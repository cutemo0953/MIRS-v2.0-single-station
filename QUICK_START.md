# 🚀 Quick Start - Emergency Dispense Feature

**MIRS v2.3 Break-the-Glass Implementation**

---

## ⚡ 5-Minute Quick Start

### Step 1: Start the Server
```bash
cd ~/Downloads/medical-inventory-system_5
python3 main.py
```

You should see:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

✅ **The database table is automatically created** - no manual SQL needed!

---

### Step 2: Test Emergency Dispense

Open a **new terminal** and run:

```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/emergency \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "GLOVE-7",
    "quantity": 2,
    "dispensedBy": "護理師-王小美",
    "emergencyReason": "大量傷患湧入，需要緊急物資",
    "stationCode": "TC-01"
  }'
```

**Expected Result:**
```json
{
  "success": true,
  "message": "緊急領用成功，已立即扣除庫存",
  "dispense_id": 1,
  "medicine_name": "手套 7",
  "quantity": 2,
  "unit": "EA",
  "remaining_stock": 48,
  "warning": "⚠️ 此為緊急領用，請藥師上班後盡快確認"
}
```

✅ **Stock deducted immediately!**

---

### Step 3: Check Pending List

```bash
curl http://localhost:8000/api/pharmacy/dispense/pending
```

**Expected Result:**
```json
{
  "records": [
    {
      "id": 1,
      "medicine_code": "GLOVE-7",
      "medicine_name": "手套 7",
      "quantity": 2,
      "dispensed_by": "護理師-王小美",
      "status": "EMERGENCY",
      "emergency_reason": "大量傷患湧入，需要緊急物資",
      "hours_pending": 0
    }
  ],
  "count": 1,
  "emergency_count": 1,
  "pending_count": 0
}
```

---

### Step 4: Pharmacist Approves

```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/approve \
  -H "Content-Type: application/json" \
  -d '{
    "dispenseId": 1,
    "approvedBy": "藥師-林大華",
    "pharmacistNotes": "緊急情況確認無誤",
    "pinCode": "1234"
  }'
```

**Expected Result:**
```json
{
  "success": true,
  "message": "緊急領用已確認",
  "dispense_id": 1,
  "approved_by": "藥師-林大華",
  "approved_at": "2024-11-20T15:30:00"
}
```

---

## ✅ That's It!

You've successfully:
1. ✅ Started the MIRS server with emergency dispense feature
2. ✅ Performed an emergency dispense (Break-the-Glass)
3. ✅ Checked the pending emergency list
4. ✅ Approved the emergency dispense as a pharmacist

---

## 📚 What to Read Next

### For Testing:
- **`EMERGENCY_DISPENSE_TESTING_GUIDE.md`** - Complete testing guide with 5 scenarios

### For Understanding:
- **`IMPLEMENTATION_SUMMARY.md`** - What was implemented and why

### For Development:
- **FastAPI Docs:** http://localhost:8000/docs (after starting server)

---

## 🆘 Troubleshooting

### Server won't start?
```bash
# Check Python version (need 3.9+)
python3 --version

# Check dependencies
pip3 install -r requirements_v1.4.5.txt
```

### Item not found?
```bash
# Check available items
curl http://localhost:8000/api/items

# Add a test item
curl -X POST http://localhost:8000/api/inventory/receive \
  -H "Content-Type: application/json" \
  -d '{
    "itemCode": "TEST-001",
    "quantity": 100,
    "stationId": "TC-01"
  }'
```

---

## 🎯 Next Steps

1. **Test all scenarios** in `EMERGENCY_DISPENSE_TESTING_GUIDE.md`
2. **Show to your nurse colleague** and get feedback
3. **Build frontend UI** (red emergency button)
4. **Deploy to production** with proper PIN code

---

**Questions? Check `IMPLEMENTATION_SUMMARY.md` for details!**

**Happy Testing! 🚀**
