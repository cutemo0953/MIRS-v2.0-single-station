# 前端同步功能測試指南

## 📋 改進摘要

已對 `Index.html` 的同步封包上傳和匯入邏輯進行了增強：

### ✅ 增強的功能

#### 1. 檔案上傳驗證 (`handleSyncFileUpload`)
- ✅ **檔案類型檢查**: 只接受 .json 檔案
- ✅ **JSON 格式驗證**: 確保檔案是有效的 JSON
- ✅ **必要欄位檢查**: 驗證 package_id, changes, checksum
- ✅ **changes 陣列驗證**: 確保 changes 是陣列類型
- ✅ **變更記錄格式檢查**: 驗證每筆變更包含 table, operation, data, timestamp
- ✅ **operation 值驗證**: 確保 operation 是 INSERT/UPDATE/DELETE
- ✅ **詳細日誌記錄**: 所有步驟都有 console.log 輸出
- ✅ **錯誤處理**: 具體的錯誤訊息

#### 2. 封包匯入增強 (`importSyncPackage`)
- ✅ **請求詳情記錄**: 記錄請求 URL、payload 大小
- ✅ **響應狀態記錄**: 記錄 HTTP 狀態碼和響應資料
- ✅ **進度提示**: 顯示「正在匯入封包...」
- ✅ **衝突警告**: 如果有衝突，顯示警告訊息
- ✅ **詳細錯誤日誌**: console.error 記錄完整錯誤資訊
- ✅ **錯誤堆疊追蹤**: 記錄 error.stack

## 🧪 測試步驟

### 準備工作

1. **啟動後端服務**:
   ```bash
   cd /home/user/medical-inventory-system_v1.4.1
   python3 main.py
   ```

2. **打開瀏覽器**:
   - 訪問 `http://localhost:8000`
   - 打開 DevTools (F12 或 Cmd+Option+I)
   - 切換到 Console 標籤

### 測試 1: 有效封包上傳和匯入

**步驟**:

1. **產生測試封包**:
   ```bash
   # 在專案目錄下執行
   python3 -c "
   import json
   import hashlib

   changes = [
       {
           'table': 'items',
           'operation': 'INSERT',
           'data': {'item_code': 'TEST001', 'item_name': '測試物品'},
           'timestamp': '2025-11-14T12:00:00'
       }
   ]

   package_content = json.dumps(changes, ensure_ascii=False, sort_keys=True)
   checksum = hashlib.sha256(package_content.encode('utf-8')).hexdigest()

   package = {
       'success': True,
       'package_id': 'PKG-TEST-FRONTEND-001',
       'package_type': 'DELTA',
       'package_size': len(package_content.encode('utf-8')),
       'checksum': checksum,
       'changes_count': len(changes),
       'changes': changes,
       'message': '測試封包'
   }

   with open('frontend_test_package.json', 'w', encoding='utf-8') as f:
       json.dump(package, f, ensure_ascii=False, indent=2)

   print(f'✓ 測試封包已創建: frontend_test_package.json')
   "
   ```

2. **在瀏覽器中上傳封包**:
   - 滾動到「匯入同步封包」區塊
   - 點擊「選擇封包檔案」
   - 選擇 `frontend_test_package.json`

3. **檢查 Console 日誌**:
   應該看到以下日誌（按順序）：
   ```
   [同步] 開始讀取封包檔案: frontend_test_package.json 大小: XXX bytes
   [同步] JSON 解析成功
   [同步] 封包包含 1 筆變更記錄
   [同步] 變更記錄格式驗證通過
   [同步] 封包已載入: {packageId: "PKG-TEST-FRONTEND-001", changesCount: 1, checksum: "..."}
   ```

4. **檢查 UI 提示**:
   - ✅ 應顯示綠色 toast: 「封包已載入：1 項變更」

5. **點擊「開始匯入」按鈕**

6. **檢查 Console 日誌**:
   ```
   [同步] 開始匯入封包: {packageId: "PKG-TEST-FRONTEND-001", changesCount: 1, stationId: "..."}
   [同步] 發送請求到 API: {url: "...", method: "POST", payloadSize: "... bytes", changesCount: 1}
   [同步] 收到響應: {status: 200, statusText: "OK", ok: true}
   [同步] 響應資料: {success: true, changes_applied: 1, ...}
   [同步] ✓ 匯入成功: {changesApplied: 1, conflicts: 0}
   ```

7. **檢查 Network 標籤**:
   - 找到 `station/sync/import` 請求
   - 查看 Request Headers:
     - `Content-Type: application/json` ✅
   - 查看 Request Payload:
     ```json
     {
       "stationId": "TC-01",
       "packageId": "PKG-TEST-FRONTEND-001",
       "changes": [
         {
           "table": "items",
           "operation": "INSERT",
           "data": {...},
           "timestamp": "2025-11-14T12:00:00"
         }
       ],
       "checksum": "..."
     }
     ```
   - 查看 Response:
     - Status: 200 OK ✅
     - Response 包含 `success: true` ✅

### 測試 2: 無效封包處理

#### 2.1 非 JSON 檔案

**步驟**:
1. 創建一個文字檔案 `test.txt`
2. 嘗試上傳
3. **預期結果**:
   - ❌ 顯示錯誤 toast: 「請上傳 JSON 格式的封包檔案」

#### 2.2 缺少必要欄位

**步驟**:
1. 使用 `test_packages/missing_fields.json`:
   ```bash
   cp test_packages/missing_fields.json frontend_test_missing.json
   ```
2. 在瀏覽器中上傳
3. **預期結果**:
   - Console 顯示:
     ```
     [同步] 封包缺少必要欄位: ["package_type", "checksum"]
     ```
   - ❌ 顯示錯誤 toast: 「封包格式錯誤：缺少 package_type, checksum」

#### 2.3 無效的 operation

**步驟**:
1. 使用 `test_packages/invalid_operation.json`:
   ```bash
   cp test_packages/invalid_operation.json frontend_test_invalid_op.json
   ```
2. 在瀏覽器中上傳
3. **預期結果**:
   - Console 顯示:
     ```
     [同步] 無效的 operation: INVALID_OPERATION
     ```
   - ❌ 顯示錯誤 toast: 「無效的操作類型：INVALID_OPERATION」

#### 2.4 損壞的 JSON

**步驟**:
1. 創建損壞的 JSON 檔案:
   ```bash
   echo '{invalid json' > frontend_test_broken.json
   ```
2. 嘗試上傳
3. **預期結果**:
   - Console 顯示:
     ```
     [同步] 解析 JSON 失敗: SyntaxError: ...
     [同步] 錯誤堆疊: ...
     ```
   - ❌ 顯示錯誤 toast: 「檔案格式錯誤：...」

### 測試 3: Network 錯誤處理

**步驟**:
1. 上傳有效封包
2. 停止後端服務 (Ctrl+C)
3. 點擊「開始匯入」
4. **預期結果**:
   - Console 顯示:
     ```
     [同步] ✗ 匯入同步封包異常: TypeError: Failed to fetch
     [同步] 錯誤堆疊: ...
     ```
   - ❌ 顯示錯誤 toast: 「匯入同步封包失敗」

### 測試 4: 完整的端到端測試

**步驟**:

1. **在瀏覽器 A 產生封包**:
   - 選擇「增量同步」
   - 選擇起始時間（例如：今天 00:00）
   - 點擊「產生封包」
   - 點擊「下載 JSON」

2. **檢查 Console**:
   ```
   產生同步封包成功
   ```

3. **在瀏覽器 B 匯入封包**:
   - 上傳剛才下載的 JSON 檔案
   - 查看 Console 驗證日誌
   - 點擊「開始匯入」

4. **觀察完整流程**:
   - Console 中應該看到完整的日誌鏈
   - Network 標籤應該看到正確的請求格式
   - UI 應該顯示成功提示
   - 資料應該重新載入

## 🔍 調試技巧

### Console 日誌過濾

在 DevTools Console 中，使用過濾器只顯示同步相關日誌：

```
[同步]
```

這樣可以過濾出所有前端同步相關的日誌。

### 檢查請求 Payload

在 Network 標籤中：

1. 點擊 `station/sync/import` 請求
2. 切換到「Payload」或「Request」標籤
3. 檢查發送的資料結構：
   - ✅ stationId 是字串
   - ✅ packageId 是字串
   - ✅ changes 是陣列
   - ✅ changes[0] 包含 table, operation, data, timestamp
   - ✅ checksum 是字串

### 檢查響應

在 Network 標籤中：

1. 點擊 `station/sync/import` 請求
2. 切換到「Response」標籤
3. 檢查響應格式：
   ```json
   {
     "success": true,
     "changes_applied": 1,
     "conflicts": []
   }
   ```

## ✅ 驗證清單

完成以下檢查，確保前端邏輯正確：

- [ ] 上傳 .json 檔案成功
- [ ] 上傳非 .json 檔案被拒絕
- [ ] 上傳有效封包顯示正確的日誌
- [ ] 上傳無效封包顯示具體的錯誤訊息
- [ ] Console 日誌清晰易讀
- [ ] Network 請求 Content-Type 是 application/json
- [ ] Network 請求 Payload 格式正確
- [ ] 匯入成功後顯示正確的提示
- [ ] 匯入失敗後顯示錯誤訊息
- [ ] changes 陣列正確傳遞（不重複 parse）
- [ ] 響應 200 OK 時處理成功
- [ ] 響應 4xx/5xx 時顯示錯誤
- [ ] Network 錯誤時有適當處理

## 🐛 常見問題排查

### 問題 1: 「封包格式錯誤」但檔案看起來正確

**檢查**:
1. 打開 Console，查看具體錯誤
2. 確認 JSON 語法正確（使用 jsonlint.com）
3. 確認包含所有必要欄位

### 問題 2: 匯入時 Network 錯誤

**檢查**:
1. 確認後端服務正在運行
2. 確認 API URL 正確
3. 查看 Console 的錯誤堆疊

### 問題 3: 匯入後沒有效果

**檢查**:
1. 查看 Console 的響應資料
2. 確認 `success: true`
3. 確認 `changes_applied > 0`
4. 查看後端日誌

## 📊 預期日誌輸出範例

### 成功的上傳

```
[同步] 開始讀取封包檔案: PKG-20251114-120000-TC01.json 大小: 12345 bytes
[同步] JSON 解析成功
[同步] 封包包含 150 筆變更記錄
[同步] 變更記錄格式驗證通過
[同步] 封包已載入: {packageId: "PKG-20251114-120000-TC01", changesCount: 150, checksum: "abc123..."}
```

### 成功的匯入

```
[同步] 開始匯入封包: {packageId: "PKG-20251114-120000-TC01", changesCount: 150, stationId: "TC-01"}
[同步] 發送請求到 API: {url: "http://localhost:8000/api/station/sync/import", method: "POST", payloadSize: "54321 bytes", changesCount: 150}
[同步] 收到響應: {status: 200, statusText: "OK", ok: true}
[同步] 響應資料: {success: true, package_id: "PKG-20251114-120000-TC01", changes_applied: 150, conflicts: []}
[同步] ✓ 匯入成功: {changesApplied: 150, conflicts: 0}
```

### 錯誤的上傳

```
[同步] 開始讀取封包檔案: invalid.json 大小: 123 bytes
[同步] JSON 解析成功
[同步] 封包缺少必要欄位: ["checksum"]
```

### 錯誤的匯入

```
[同步] 開始匯入封包: {...}
[同步] 發送請求到 API: {...}
[同步] 收到響應: {status: 400, statusText: "Bad Request", ok: false}
[同步] ✗ API 錯誤: {status: 400, detail: "封包格式錯誤：變更記錄清單為空", error: {...}}
```

## 📝 總結

前端邏輯改進後：

✅ **更強的驗證**: 5 層驗證（檔案類型、JSON 格式、必要欄位、陣列類型、變更記錄格式）
✅ **詳細的日誌**: 所有關鍵步驟都有 console.log
✅ **清晰的錯誤**: 具體的錯誤訊息，不是泛泛的「失敗」
✅ **符合規範**: JSON.parse 只執行一次，fetch 使用正確的 Content-Type
✅ **易於調試**: 所有日誌都有 [同步] 前綴，易於過濾

## 🚀 下一步

完成測試後：

1. 確認所有測試案例都通過
2. 在實際環境中測試端到端流程
3. 收集用戶反饋
4. 如有需要，進一步優化
