# 🏥 多站點測試與管理指南

## 📋 目錄
1. [單機多站點測試方案](#1-單機多站點測試方案)
2. [資料庫架構修復](#2-資料庫架構修復)
3. [站點設定與切換](#3-站點設定與切換)
4. [權限管理（PIN碼）](#4-權限管理pin碼)

---

## 1. 單機多站點測試方案

### 🎯 測試目標
在單一電腦上模擬多個站點，測試調撥功能（如：TC-01 轉移血袋給 TC-02）

### 方案 A：**單一後端 + 多個前端分頁**（推薦）

#### 架構說明
```
┌──────────────────────────────────────────┐
│  SQLite 資料庫（共用）                    │
│  - 所有站點數據存在同一個 DB              │
│  - 通過 station_id 欄位區分               │
└──────────────────────────────────────────┘
                    ↑
                    │
┌──────────────────────────────────────────┐
│  FastAPI 後端服務 (localhost:8000)        │
│  - 單一實例                               │
│  - 處理所有站點請求                       │
└──────────────────────────────────────────┘
         ↑                        ↑
         │                        │
┌────────────────┐        ┌────────────────┐
│  瀏覽器分頁 1   │        │  瀏覽器分頁 2   │
│  站點: TC-01   │        │  站點: TC-02   │
│  血袋: 50U O+  │ ──調撥→ │  血袋: 30U O+  │
└────────────────┘        └────────────────┘
```

#### 操作步驟

**1. 啟動後端**：
```bash
cd /path/to/medical-inventory-system_v1.4.1
python main.py
```

**2. 開啟兩個瀏覽器分頁**：
- 分頁 1: `http://localhost:8000` → 設定為 TC-01
- 分頁 2: `http://localhost:8000` → 設定為 TC-02

**3. 在前端切換站點ID**（需實作站點切換功能）：
- 點擊頁面頂部「站點：TC-01」
- 彈出站點設定視窗
- 輸入新站點ID（如 TC-02）
- 保存（儲存在瀏覽器 localStorage）

**4. 測試調撥**：
- 在 TC-01 分頁：執行血袋入庫（O+ 50U）
- 切換到 TC-02 分頁：執行血袋入庫（O+ 30U）
- 在 TC-01 分頁：調撥 20U O+ 給 TC-02
- 切換到 TC-02 分頁：確認收到 20U（總量變成 50U）

**優點**：
- ✅ 簡單快速，無需多個後端實例
- ✅ 共用資料庫，符合實際使用情境
- ✅ 前端可以快速切換站點

**缺點**：
- ❌ 無法完全模擬獨立站點（共用同一資料庫實例）

---

### 方案 B：**多個後端實例 + 獨立資料庫**

#### 架構說明
```
┌────────────────┐        ┌────────────────┐
│   資料庫 TC-01  │        │   資料庫 TC-02  │
│  tc01.db       │        │  tc02.db       │
└────────────────┘        └────────────────┘
        ↑                          ↑
        │                          │
┌────────────────┐        ┌────────────────┐
│  後端實例 1     │        │  後端實例 2     │
│  port: 8001    │        │  port: 8002    │
└────────────────┘        └────────────────┘
        ↑                          ↑
        │                          │
┌────────────────┐        ┌────────────────┐
│  前端 TC-01    │        │  前端 TC-02    │
│  :8001         │        │  :8002         │
└────────────────┘        └────────────────┘
```

#### 操作步驟

**1. 建立配置檔案**：

`config_tc01.py`:
```python
STATION_ID = "TC-01"
DATABASE_PATH = "./database/tc01.db"
PORT = 8001
```

`config_tc02.py`:
```python
STATION_ID = "TC-02"
DATABASE_PATH = "./database/tc02.db"
PORT = 8002
```

**2. 啟動兩個後端實例**：

終端機 1:
```bash
PORT=8001 STATION_ID=TC-01 DB_PATH=./database/tc01.db python main.py
```

終端機 2:
```bash
PORT=8002 STATION_ID=TC-02 DB_PATH=./database/tc02.db python main.py
```

**3. 訪問不同站點**：
- TC-01: `http://localhost:8001`
- TC-02: `http://localhost:8002`

**4. 測試調撥**：
- **問題**：調撥無法直接運作！因為資料庫完全獨立
- **需要**：實作跨資料庫調撥API（較複雜）

**優點**：
- ✅ 完全獨立，模擬真實多站點環境
- ✅ 每個站點有獨立資料庫

**缺點**：
- ❌ 需要運行多個後端實例
- ❌ 調撥功能需要跨資料庫通訊（複雜）
- ❌ 測試較麻煩

---

### 🎯 推薦方案：**方案 A（單一後端 + 前端切換站點）**

**理由**：
1. 系統本來就設計為共用資料庫，通過 `station_id` 區分
2. 調撥功能可以直接運作（UPDATE 不同 station_id 的記錄）
3. 測試簡單快速
4. 符合實際部署架構（中央資料庫 + 多個前端終端機）

---

## 2. 資料庫架構修復

### ❌ 原始設計問題

**blood_inventory 表**：
```sql
CREATE TABLE blood_inventory (
    blood_type TEXT PRIMARY KEY,    -- ❌ 只用血型作主鍵
    quantity INTEGER,
    station_id TEXT NOT NULL         -- 無法支援多站點！
);
```

**問題**：
- TC-01 的 O+ 和 TC-02 的 O+ 會衝突（主鍵衝突）
- 無法在同一資料庫中儲存多個站點的血袋庫存

---

### ✅ 修復後的設計

**blood_inventory 表**：
```sql
CREATE TABLE blood_inventory (
    blood_type TEXT NOT NULL,
    quantity INTEGER DEFAULT 0,
    station_id TEXT NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (blood_type, station_id)  -- ✅ 複合主鍵
);
```

**效果**：
- TC-01 的 O+ 和 TC-02 的 O+ 可以共存
- 每個站點可以有獨立的血袋庫存記錄

---

### 🔄 資料庫遷移步驟

**⚠️ 重要**：如果你已經有現有資料，需要執行遷移！

#### 選項 1：刪除舊資料庫（測試環境）

```bash
# 備份舊資料庫
cp database/medical_inventory.db database/medical_inventory.db.bak

# 刪除舊資料庫
rm database/medical_inventory.db

# 重新啟動系統，會自動建立新結構
python main.py
```

#### 選項 2：遷移現有資料（生產環境）

**執行遷移腳本**：

```python
# migrate_blood_inventory.py
import sqlite3

def migrate_database(db_path="./database/medical_inventory.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("🔄 開始遷移 blood_inventory 表...")

    # 1. 創建臨時表（新結構）
    cursor.execute("""
        CREATE TABLE blood_inventory_new (
            blood_type TEXT NOT NULL,
            quantity INTEGER DEFAULT 0,
            station_id TEXT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (blood_type, station_id)
        )
    """)

    # 2. 檢查舊表是否有資料
    cursor.execute("SELECT COUNT(*) FROM blood_inventory")
    count = cursor.fetchone()[0]

    if count > 0:
        print(f"📊 發現 {count} 筆舊資料，開始遷移...")

        # 3. 複製資料（假設舊資料都屬於 TC-01）
        cursor.execute("""
            INSERT INTO blood_inventory_new (blood_type, quantity, station_id, last_updated)
            SELECT blood_type, quantity, 'TC-01', last_updated
            FROM blood_inventory
        """)
        print(f"✅ 已遷移 {count} 筆資料（站點設為 TC-01）")
    else:
        print("📭 舊表無資料，跳過資料遷移")

    # 4. 刪除舊表
    cursor.execute("DROP TABLE blood_inventory")
    print("🗑️  已刪除舊表")

    # 5. 重命名新表
    cursor.execute("ALTER TABLE blood_inventory_new RENAME TO blood_inventory")
    print("✅ 新表已啟用")

    conn.commit()
    conn.close()
    print("🎉 遷移完成！")

if __name__ == "__main__":
    migrate_database()
```

**執行**：
```bash
python migrate_blood_inventory.py
```

---

## 3. 站點設定與切換

### 🎯 前端站點切換功能設計

您建議在頁面頂部「站點：TC-01」處添加切換功能，這個建議非常合理！

#### UI 設計

**位置**：頁面頂部導航列

**現況**：
```html
<div class="flex justify-between items-center mb-6">
    <h1 class="text-2xl font-bold text-gray-800">
        站點：TC-01  <!-- 目前硬編碼 -->
    </h1>
    ...
</div>
```

**改進後**：
```html
<div class="flex justify-between items-center mb-6">
    <button @click="showStationSettingsModal = true"
            class="flex items-center gap-2 text-2xl font-bold text-gray-800 hover:text-blue-600 transition-colors">
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
        </svg>
        <span>站點：<span x-text="stationId" class="text-blue-600"></span></span>
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
        </svg>
    </button>
    ...
</div>
```

---

#### 站點設定模態窗

```html
<!-- 站點設定 Modal -->
<div x-show="showStationSettingsModal"
     class="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50">
    <div @click.away="showStationSettingsModal = false"
         class="bg-white rounded-2xl shadow-2xl p-6 max-w-md w-full mx-4">

        <!-- 標題 -->
        <div class="flex items-center justify-between mb-6">
            <h3 class="text-2xl font-bold text-gray-800 flex items-center gap-2">
                <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                </svg>
                站點設定
            </h3>
            <button @click="showStationSettingsModal = false" class="text-gray-400 hover:text-gray-600">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </div>

        <!-- 表單 -->
        <form @submit.prevent="saveStationSettings()" class="space-y-4">
            <!-- 站點ID -->
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">
                    站點ID *
                </label>
                <input type="text"
                       x-model="tempStationId"
                       required
                       class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                       placeholder="例：TC-01, TC-02">
                <p class="text-xs text-gray-500 mt-1">
                    設定後會儲存在瀏覽器中，下次開啟自動載入
                </p>
            </div>

            <!-- 站點名稱（選填） -->
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">
                    站點名稱（選填）
                </label>
                <input type="text"
                       x-model="tempStationName"
                       class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                       placeholder="例：台中榮總前線醫療站">
            </div>

            <!-- PIN碼（未來功能） -->
            <div class="bg-gray-100 rounded-lg p-3">
                <div class="flex items-center gap-2 text-sm text-gray-600">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                    </svg>
                    <span>權限管理（PIN碼）功能開發中...</span>
                </div>
            </div>

            <!-- 按鈕 -->
            <div class="flex gap-3">
                <button type="button"
                        @click="showStationSettingsModal = false"
                        class="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
                    取消
                </button>
                <button type="submit"
                        class="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    保存設定
                </button>
            </div>
        </form>

        <!-- 當前站點資訊 -->
        <div class="mt-6 pt-4 border-t border-gray-200">
            <p class="text-sm text-gray-600">
                當前站點：<span class="font-semibold" x-text="stationId"></span>
            </p>
            <p class="text-xs text-gray-500 mt-1">
                儲存位置：瀏覽器 localStorage
            </p>
        </div>
    </div>
</div>
```

---

#### JavaScript 實作

```javascript
// Alpine.js 資料模型
data() {
    return {
        // 站點設定
        stationId: 'TC-01',  // 預設值
        stationName: '',
        showStationSettingsModal: false,
        tempStationId: '',
        tempStationName: '',

        // ... 其他資料
    }
},

// 初始化時載入
async init() {
    // 從 localStorage 載入站點設定
    const savedStationId = localStorage.getItem('stationId');
    const savedStationName = localStorage.getItem('stationName');

    if (savedStationId) {
        this.stationId = savedStationId;
        console.log(`🏥 載入站點設定: ${this.stationId}`);
    }

    if (savedStationName) {
        this.stationName = savedStationName;
    }

    // 載入初始資料
    await this.loadStats();
    await this.loadBloodInventory();
    // ...
},

// 保存站點設定
saveStationSettings() {
    if (!this.tempStationId.trim()) {
        this.toast('請輸入站點ID', 'error');
        return;
    }

    // 保存到 localStorage
    localStorage.setItem('stationId', this.tempStationId);
    localStorage.setItem('stationName', this.tempStationName || '');

    // 更新當前設定
    this.stationId = this.tempStationId;
    this.stationName = this.tempStationName;

    // 關閉視窗
    this.showStationSettingsModal = false;

    this.toast(`站點已切換為：${this.stationId}`, 'success');

    // 重新載入資料
    this.loadStats();
    this.loadBloodInventory();
    this.loadInventory();
    this.loadEquipment();
},

// 開啟設定視窗時
openStationSettings() {
    // 複製當前設定到暫存
    this.tempStationId = this.stationId;
    this.tempStationName = this.stationName;
    this.showStationSettingsModal = true;
}
```

---

## 4. 權限管理（PIN碼）

### 🔐 設計方案

#### 需求分析
- 防止誤操作（如誤刪物資、錯誤調撥）
- 限制敏感功能訪問（如設備重置、緊急備份）
- 追蹤操作人員

#### PIN碼驗證流程

```
使用者點擊敏感操作（如：刪除物資）
           ↓
      彈出 PIN 碼輸入視窗
           ↓
      輸入 4 位數 PIN 碼
           ↓
    ┌──────驗證──────┐
    ↓               ↓
  正確             錯誤
    ↓               ↓
執行操作         顯示錯誤訊息
記錄操作人       （3次後鎖定）
```

#### 資料庫設計

```sql
-- PIN碼管理表
CREATE TABLE user_pins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,  -- 使用 SHA256 加密
    role TEXT DEFAULT 'OPERATOR',  -- ADMIN/MANAGER/OPERATOR
    station_id TEXT,  -- 可選：限制特定站點
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 操作日誌表
CREATE TABLE operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    action TEXT NOT NULL,  -- DELETE_ITEM/RESET_EQUIPMENT/BLOOD_TRANSFER 等
    details TEXT,
    station_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 前端實作（模態窗）

```html
<!-- PIN 碼驗證 Modal -->
<div x-show="showPinModal" class="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50">
    <div class="bg-white rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
        <h3 class="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
            <svg class="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
            </svg>
            需要權限驗證
        </h3>

        <p class="text-sm text-gray-600 mb-4" x-text="pinActionDescription"></p>

        <form @submit.prevent="submitPin()" class="space-y-4">
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">操作人員</label>
                <input type="text" x-model="pinOperator" required class="w-full px-4 py-2 border border-gray-300 rounded-lg">
            </div>

            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">PIN 碼</label>
                <input type="password"
                       x-model="pinCode"
                       maxlength="4"
                       pattern="[0-9]{4}"
                       required
                       class="w-full px-4 py-2 border border-gray-300 rounded-lg text-center text-2xl tracking-widest"
                       placeholder="••••">
            </div>

            <div class="flex gap-3">
                <button type="button" @click="cancelPin()" class="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                    取消
                </button>
                <button type="submit" class="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">
                    確認
                </button>
            </div>
        </form>
    </div>
</div>
```

**JavaScript**:
```javascript
// PIN 碼驗證
async requestPin(action, description) {
    this.pinAction = action;
    this.pinActionDescription = description;
    this.pinCode = '';
    this.pinOperator = '';
    this.showPinModal = true;
},

async submitPin() {
    try {
        const response = await fetch(`${this.apiUrl}/auth/verify-pin`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                operator: this.pinOperator,
                pin: this.pinCode,
                action: this.pinAction
            })
        });

        if (response.ok) {
            this.showPinModal = false;
            // 執行原本的操作
            this.executeProtectedAction();
            this.toast('驗證成功', 'success');
        } else {
            this.toast('PIN 碼錯誤', 'error');
        }
    } catch (error) {
        console.error('PIN 驗證失敗:', error);
        this.toast('驗證失敗', 'error');
    }
}
```

---

## 5. 總結與建議

### ✅ 已完成
- [x] 修復 `blood_inventory` 資料庫主鍵問題
- [x] 更新後端 API 支援多站點
- [x] 建立多站點測試方案文檔

### 🚧 待實作
- [ ] 前端站點切換UI
- [ ] localStorage 儲存站點設定
- [ ] PIN 碼驗證系統
- [ ] 操作日誌記錄
- [ ] 資料庫遷移腳本測試

### 💡 建議實作順序
1. **先實作前端站點切換功能**（最重要，影響測試）
2. **執行資料庫遷移**（確保多站點支援）
3. **測試調撥功能**（驗證多站點運作）
4. **實作 PIN 碼系統**（進階功能）

---

**版本**: v1.0
**建立日期**: 2025-11-12
**最後更新**: 2025-11-12
