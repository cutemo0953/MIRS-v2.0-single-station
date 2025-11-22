# 🚨 Emergency Dispense Feature - Testing Guide
**MIRS v2.3 - Break-the-Glass Implementation**
**Version:** 1.0.0
**Date:** 2024-11-20

---

## 📋 Table of Contents
1. [Quick Start](#quick-start)
2. [Testing Workflow](#testing-workflow)
3. [API Endpoints](#api-endpoints)
4. [Test Scenarios](#test-scenarios)
5. [Troubleshooting](#troubleshooting)

---

## 🚀 Quick Start

### Step 1: Initialize Database
```bash
# Make sure you're in the project directory
cd ~/Downloads/medical-inventory-system_5

# Start the backend server
python3 main.py
```

The server will:
- Automatically create the `dispense_records` table
- Initialize indexes
- Be ready to accept requests

### Step 2: Verify Server is Running
```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{
  "status": "healthy",
  ...
}
```

---

## 🧪 Testing Workflow

### Complete Test Flow
```
1. Add test items (medicine) to inventory
2. Test emergency dispense (Break-the-Glass)
3. Check pending emergency dispenses
4. Pharmacist approves emergency dispense
5. Verify stock deduction
```

---

## 📡 API Endpoints

### 1. Emergency Dispense (Break-the-Glass)
**Endpoint:** `POST /api/pharmacy/dispense/emergency`
**Purpose:** Emergency medication dispensing without pharmacist PIN

**Request:**
```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/emergency \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "MED-001",
    "quantity": 2,
    "dispensedBy": "護理師-王小美",
    "emergencyReason": "大量傷患湧入，病患疼痛指數10/10，藥師不在現場",
    "patientRefId": "T001",
    "patientName": "張三",
    "stationCode": "TC-01"
  }'
```

**Success Response (201):**
```json
{
  "success": true,
  "message": "緊急領用成功，已立即扣除庫存",
  "dispense_id": 1,
  "medicine_name": "Morphine 10mg",
  "quantity": 2,
  "unit": "顆",
  "remaining_stock": 48,
  "warning": "⚠️ 此為緊急領用，請藥師上班後盡快確認"
}
```

**Error Response (400) - Insufficient Stock:**
```json
{
  "detail": "庫存不足！當前庫存: 1 顆, 需要: 2 顆"
}
```

---

### 2. Normal Dispense (需審核)
**Endpoint:** `POST /api/pharmacy/dispense/normal`
**Purpose:** Normal dispensing with pharmacist approval

**Request:**
```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/normal \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "MED-002",
    "quantity": 5,
    "dispensedBy": "護理師-李小華",
    "patientRefId": "T002",
    "patientName": "李四",
    "prescriptionId": "RX-20241120-001",
    "stationCode": "TC-01"
  }'
```

**Success Response (201):**
```json
{
  "success": true,
  "message": "領用請求已建立，等待藥師審核",
  "dispense_id": 2,
  "status": "PENDING",
  "medicine_name": "Paracetamol 500mg",
  "quantity": 5,
  "unit": "顆"
}
```

---

### 3. Approve Dispense (藥師審核)
**Endpoint:** `POST /api/pharmacy/dispense/approve`
**Purpose:** Pharmacist approves pending or confirms emergency dispense

**Request:**
```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/approve \
  -H "Content-Type: application/json" \
  -d '{
    "dispenseId": 1,
    "approvedBy": "藥師-林大華",
    "pharmacistNotes": "緊急情況確認無誤，已核對病患用藥記錄",
    "pinCode": "1234"
  }'
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "緊急領用已確認",
  "dispense_id": 1,
  "approved_by": "藥師-林大華",
  "approved_at": "2024-11-20T15:30:00"
}
```

**Error Response (401) - Wrong PIN:**
```json
{
  "detail": "PIN 碼錯誤，拒絕審核"
}
```

---

### 4. Get Pending Dispenses
**Endpoint:** `GET /api/pharmacy/dispense/pending`
**Purpose:** List all pending and emergency dispenses

**Request:**
```bash
# Get all pending and emergency dispenses
curl http://localhost:8000/api/pharmacy/dispense/pending

# Get only emergency dispenses
curl http://localhost:8000/api/pharmacy/dispense/pending?status=EMERGENCY

# Get only pending (awaiting approval)
curl http://localhost:8000/api/pharmacy/dispense/pending?status=PENDING
```

**Success Response (200):**
```json
{
  "records": [
    {
      "id": 1,
      "medicine_code": "MED-001",
      "medicine_name": "Morphine 10mg",
      "quantity": 2,
      "unit": "顆",
      "dispensed_by": "護理師-王小美",
      "approved_by": null,
      "status": "EMERGENCY",
      "emergency_reason": "大量傷患湧入，病患疼痛指數10/10，藥師不在現場",
      "patient_ref_id": "T001",
      "patient_name": "張三",
      "station_code": "TC-01",
      "created_at": "2024-11-20 14:30:00",
      "hours_pending": 1
    }
  ],
  "count": 1,
  "emergency_count": 1,
  "pending_count": 0
}
```

---

### 5. Get Dispense History
**Endpoint:** `GET /api/pharmacy/dispense/history`
**Purpose:** Query historical dispense records

**Request:**
```bash
# Get all records
curl http://localhost:8000/api/pharmacy/dispense/history

# Filter by date range
curl "http://localhost:8000/api/pharmacy/dispense/history?start_date=2024-11-01&end_date=2024-11-30"

# Filter by medicine
curl "http://localhost:8000/api/pharmacy/dispense/history?medicine_code=MED-001"

# Filter by status
curl "http://localhost:8000/api/pharmacy/dispense/history?status=EMERGENCY"

# Combine filters
curl "http://localhost:8000/api/pharmacy/dispense/history?status=EMERGENCY&start_date=2024-11-20&limit=20"
```

**Success Response (200):**
```json
{
  "records": [
    {
      "id": 1,
      "medicine_code": "MED-001",
      "medicine_name": "Morphine 10mg",
      "quantity": 2,
      "status": "APPROVED",
      "emergency_reason": "大量傷患湧入...",
      "dispensed_by": "護理師-王小美",
      "approved_by": "藥師-林大華",
      "created_at": "2024-11-20 14:30:00",
      "approved_at": "2024-11-20 15:30:00"
    }
  ],
  "count": 1
}
```

---

## 🧪 Test Scenarios

### Scenario 1: Emergency Dispense - Happy Path
**目的：** 測試緊急領用基本流程

```bash
# 1. 先確認有庫存 (假設你已經有物品 GLOVE-7)
curl http://localhost:8000/api/stock

# 2. 執行緊急領用
curl -X POST http://localhost:8000/api/pharmacy/dispense/emergency \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "GLOVE-7",
    "quantity": 5,
    "dispensedBy": "護理師-測試",
    "emergencyReason": "測試緊急領用功能，大量傷患湧入需要手套",
    "stationCode": "TC-01"
  }'

# 預期結果: 201 Created, 庫存立即扣除

# 3. 確認待處理清單
curl http://localhost:8000/api/pharmacy/dispense/pending

# 預期結果: 看到一筆 EMERGENCY 狀態記錄

# 4. 藥師確認
curl -X POST http://localhost:8000/api/pharmacy/dispense/approve \
  -H "Content-Type: application/json" \
  -d '{
    "dispenseId": 1,
    "approvedBy": "藥師-測試",
    "pharmacistNotes": "確認無誤",
    "pinCode": "1234"
  }'

# 預期結果: 200 OK, 狀態改為 APPROVED
```

---

### Scenario 2: Insufficient Stock
**目的：** 測試庫存不足時的錯誤處理

```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/emergency \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "GLOVE-7",
    "quantity": 999999,
    "dispensedBy": "護理師-測試",
    "emergencyReason": "測試庫存不足的錯誤處理",
    "stationCode": "TC-01"
  }'

# 預期結果: 400 Bad Request
# 訊息: "庫存不足！當前庫存: X, 需要: 999999"
```

---

### Scenario 3: Invalid Emergency Reason (Too Short)
**目的：** 測試緊急原因驗證

```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/emergency \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "GLOVE-7",
    "quantity": 1,
    "dispensedBy": "護理師-測試",
    "emergencyReason": "急",
    "stationCode": "TC-01"
  }'

# 預期結果: 422 Unprocessable Entity
# 訊息: "緊急原因必須至少5個字，防止濫用"
```

---

### Scenario 4: Wrong PIN Code
**目的：** 測試PIN碼驗證

```bash
curl -X POST http://localhost:8000/api/pharmacy/dispense/approve \
  -H "Content-Type: application/json" \
  -d '{
    "dispenseId": 1,
    "approvedBy": "藥師-測試",
    "pharmacistNotes": "測試",
    "pinCode": "9999"
  }'

# 預期結果: 401 Unauthorized
# 訊息: "PIN 碼錯誤，拒絕審核"
```

---

### Scenario 5: Normal Dispense Flow
**目的：** 測試正常領用流程

```bash
# 1. 建立正常領用請求
curl -X POST http://localhost:8000/api/pharmacy/dispense/normal \
  -H "Content-Type: application/json" \
  -d '{
    "medicineCode": "GLOVE-7",
    "quantity": 3,
    "dispensedBy": "護理師-測試",
    "patientName": "測試病患",
    "stationCode": "TC-01"
  }'

# 預期結果: 201 Created, status=PENDING, 庫存未扣除

# 2. 藥師審核通過
curl -X POST http://localhost:8000/api/pharmacy/dispense/approve \
  -H "Content-Type: application/json" \
  -d '{
    "dispenseId": 2,
    "approvedBy": "藥師-測試",
    "pinCode": "1234"
  }'

# 預期結果: 200 OK, 庫存扣除
```

---

## 🔍 Troubleshooting

### Issue 1: Server won't start
**症狀:** `python3 main.py` 失敗

**解決方案:**
```bash
# 檢查 Python 版本 (需要 3.9+)
python3 --version

# 檢查依賴套件
pip3 list | grep -E "fastapi|uvicorn|pydantic"

# 重新安裝依賴
pip3 install -r requirements_v1.4.5.txt
```

---

### Issue 2: Table not found
**症狀:** `no such table: dispense_records`

**解決方案:**
```bash
# 方法 1: 重啟服務器 (會自動建表)
# Ctrl+C 停止服務器
python3 main.py

# 方法 2: 手動執行 migration (如果問題仍存在)
sqlite3 medical_inventory.db < database/migration_add_dispense_records.sql
```

---

### Issue 3: Medicine/Item not found
**症狀:** `藥品/物品代碼 XXX 不存在`

**解決方案:**
```bash
# 檢查現有物品
curl http://localhost:8000/api/items

# 新增測試物品
curl -X POST http://localhost:8000/api/inventory/receive \
  -H "Content-Type: application/json" \
  -d '{
    "itemCode": "TEST-MED-001",
    "quantity": 100,
    "batchNumber": "BATCH-001",
    "expiryDate": "2025-12-31",
    "remarks": "測試藥品",
    "stationId": "TC-01"
  }'
```

---

### Issue 4: Port 8000 already in use
**症狀:** `Address already in use`

**解決方案:**
```bash
# 找出佔用端口的進程
lsof -i :8000

# 殺掉進程
kill -9 <PID>

# 或使用不同端口 (修改 main.py 最後一行)
# uvicorn.run(app, host="0.0.0.0", port=8001)
```

---

## 📊 Verification Checklist

After testing, verify the following:

### Database Verification
```bash
# Check dispense_records table exists
sqlite3 medical_inventory.db "SELECT name FROM sqlite_master WHERE type='table' AND name='dispense_records';"

# Check if emergency dispenses were recorded
sqlite3 medical_inventory.db "SELECT * FROM dispense_records WHERE status='EMERGENCY';"

# Check stock was deducted
sqlite3 medical_inventory.db "SELECT * FROM inventory_events WHERE remarks LIKE '%緊急領用%';"
```

### API Verification
- [ ] Emergency dispense creates record with status=EMERGENCY
- [ ] Emergency dispense deducts stock immediately
- [ ] Normal dispense creates record with status=PENDING
- [ ] Normal dispense does NOT deduct stock until approved
- [ ] Pharmacist approval with wrong PIN fails
- [ ] Pharmacist approval with correct PIN succeeds
- [ ] Pending list shows EMERGENCY and PENDING records
- [ ] History query returns correct records

---

## 🎯 Next Steps

### For Production Deployment:
1. **Change PIN code** in `main.py` (line ~3399)
   - Move to config file or environment variable
   - Consider password hashing

2. **Add authentication**
   - Implement proper user authentication
   - Role-based access control (RBAC)

3. **Add audit logging**
   - Log all dispense actions
   - Track who accessed emergency dispense

4. **Frontend UI**
   - Create emergency dispense button (red, prominent)
   - Add pending dispense dashboard for pharmacist
   - Show visual alerts for unapproved emergencies

5. **Monitoring**
   - Set up alerts for emergency dispenses
   - Daily/weekly reports of Break-the-Glass usage

---

## 📞 Support

If you encounter issues:
1. Check logs: `tail -f medical_inventory.log`
2. Check database: `sqlite3 medical_inventory.db`
3. Verify server status: `curl http://localhost:8000/api/health`

---

**測試愉快！ Happy Testing! 🚀**

---

**Document Version:** 1.0.0
**Last Updated:** 2024-11-20
**Author:** MIRS Development Team
