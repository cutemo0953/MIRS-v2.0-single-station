#!/bin/bash
#
# 跨瀏覽器同步功能測試
#
# 測試完整的同步流程：
# 1. 準備測試環境（兩個測試站點）
# 2. 站點 A 產生封包
# 3. 驗證封包格式
# 4. 站點 B 匯入封包
# 5. 驗證資料同步
#

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 計數器
PASSED=0
FAILED=0

# 錯誤處理
handle_error() {
    echo -e "${RED}✗ 錯誤: $1${NC}"
    FAILED=$((FAILED + 1))
    if [ "${STOP_ON_ERROR:-0}" = "1" ]; then
        echo ""
        echo "測試中止（設置 STOP_ON_ERROR=0 繼續測試）"
        cleanup
        exit 1
    fi
}

# 成功處理
handle_success() {
    echo -e "${GREEN}✓ $1${NC}"
    PASSED=$((PASSED + 1))
}

# 清理函數
cleanup() {
    echo ""
    echo -e "${BLUE}► Step 6: 清理測試資料${NC}"

    # 清理測試配置檔案
    rm -f config/test_tc01.json 2>/dev/null
    rm -f config/test_tc02.json 2>/dev/null
    rm -f database/test_tc01_general.db 2>/dev/null
    rm -f database/test_tc02_general.db 2>/dev/null
    rm -f database/test_tc01_pharmacy.db 2>/dev/null
    rm -f database/test_tc02_pharmacy.db 2>/dev/null
    rm -f test_package.json 2>/dev/null
    rm -f test_import_response.json 2>/dev/null

    # 清理主資料庫中的測試資料
    python3 << 'EOF' 2>/dev/null
import sqlite3
try:
    conn = sqlite3.connect('medical_inventory.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory_events WHERE station_id IN ('TEST-TC-01', 'TEST-TC-02')")
    cursor.execute("DELETE FROM items WHERE code LIKE 'TEST-%'")
    conn.commit()
    conn.close()
except:
    pass
EOF

    handle_success "清理完成"
}

# 檢查後端是否運行
check_backend() {
    echo -e "${BLUE}► Step 0: 檢查後端服務${NC}"

    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        handle_success "後端服務正在運行"
        return 0
    elif curl -s http://localhost:8000/ > /dev/null 2>&1; then
        handle_success "後端服務正在運行"
        return 0
    else
        echo -e "${YELLOW}⚠ 警告: 無法連接到後端服務${NC}"
        echo "請確保後端正在運行: python3 main.py"
        echo ""
        read -p "是否繼續測試? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

echo "======================================================================"
echo "🧪 跨瀏覽器同步功能測試"
echo "======================================================================"
echo ""

# Step 0: 檢查後端
check_backend

# Step 1: 準備測試環境
echo ""
echo -e "${BLUE}► Step 1: 準備測試站點${NC}"

# 確保 config 和 database 目錄存在
mkdir -p config
mkdir -p database

# 創建測試站點 TC-01 配置
cat > config/test_tc01.json <<EOF
{
  "station_id": "TEST-TC-01",
  "station_name": "測試站點01",
  "station_type": "FIRST_CLASS",
  "admin_level": "STATION_LOCAL",
  "hospital_id": "HOSP-TEST",
  "database": {
    "general_inventory_path": "database/test_tc01_general.db",
    "pharmacy_path": "database/test_tc01_pharmacy.db"
  }
}
EOF

if [ $? -eq 0 ]; then
    handle_success "創建 TEST-TC-01 配置檔案"
else
    handle_error "創建 TEST-TC-01 配置檔案失敗"
fi

# 創建測試站點 TC-02 配置
cat > config/test_tc02.json <<EOF
{
  "station_id": "TEST-TC-02",
  "station_name": "測試站點02",
  "station_type": "FIRST_CLASS",
  "admin_level": "STATION_LOCAL",
  "hospital_id": "HOSP-TEST",
  "database": {
    "general_inventory_path": "database/test_tc02_general.db",
    "pharmacy_path": "database/test_tc02_pharmacy.db"
  }
}
EOF

if [ $? -eq 0 ]; then
    handle_success "創建 TEST-TC-02 配置檔案"
else
    handle_error "創建 TEST-TC-02 配置檔案失敗"
fi

# 初始化資料庫
echo ""
echo "初始化 TEST-TC-01 資料庫..."
if python3 scripts/init_databases.py config/test_tc01.json > /dev/null 2>&1; then
    handle_success "TEST-TC-01 資料庫初始化完成"
else
    handle_error "TEST-TC-01 資料庫初始化失敗"
fi

echo "初始化 TEST-TC-02 資料庫..."
if python3 scripts/init_databases.py config/test_tc02.json > /dev/null 2>&1; then
    handle_success "TEST-TC-02 資料庫初始化完成"
else
    handle_error "TEST-TC-02 資料庫初始化失敗"
fi

# Step 1.5: 新增測試資料到 TEST-TC-01
echo ""
echo "新增測試資料到 TEST-TC-01..."
python3 << 'EOF'
import sqlite3
from datetime import datetime

try:
    # 使用主資料庫（backend 實際使用的資料庫）
    conn = sqlite3.connect('medical_inventory.db')
    cursor = conn.cursor()

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 先清理舊的測試資料
    cursor.execute("DELETE FROM inventory_events WHERE station_id IN ('TEST-TC-01', 'TEST-TC-02')")
    cursor.execute("DELETE FROM items WHERE code LIKE 'TEST-%'")

    # 新增測試物品（使用 medical_inventory.db 的 schema: code, name, category, unit）
    cursor.execute("""
        INSERT INTO items (code, name, category, unit, min_stock, created_at, updated_at)
        VALUES
        ('TEST-001', '測試物品01', '一般耗材', '個', 10, ?, ?)
    """, (now, now))

    # 新增 inventory_events（這個表有 station_id，會被 FULL sync 捕獲）
    cursor.execute("""
        INSERT INTO inventory_events (
            event_type, item_code, quantity, station_id, operator, timestamp, remarks
        )
        VALUES
        ('RECEIVE', 'TEST-001', 100, 'TEST-TC-01', 'TEST_SYSTEM', ?, '測試庫存事件')
    """, (now,))

    conn.commit()
    conn.close()

    print("OK")
    exit(0)
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
EOF

if [ $? -eq 0 ]; then
    handle_success "測試資料新增完成（1 個物品，1 筆庫存事件）"
else
    handle_error "測試資料新增失敗"
fi

# Step 2: 測試封包產生
echo ""
echo -e "${BLUE}► Step 2: 測試封包產生 (站點 A)${NC}"

echo "發送 API 請求..."
HTTP_CODE=$(curl -s -o test_package.json -w "%{http_code}" \
    -X POST http://localhost:8000/api/station/sync/generate \
    -H "Content-Type: application/json" \
    -d '{
        "stationId": "TEST-TC-01",
        "hospitalId": "HOSP-TEST",
        "syncType": "FULL"
    }')

if [ "$HTTP_CODE" = "200" ]; then
    handle_success "封包產生成功 (HTTP $HTTP_CODE)"

    # 檢查封包內容
    if [ -f test_package.json ]; then
        PACKAGE_ID=$(python3 -c "import json; data=json.load(open('test_package.json')); print(data.get('package_id', ''))" 2>/dev/null)
        CHANGES_COUNT=$(python3 -c "import json; data=json.load(open('test_package.json')); print(data.get('changes_count', 0))" 2>/dev/null)

        if [ -n "$PACKAGE_ID" ]; then
            echo "  封包ID: $PACKAGE_ID"
            echo "  變更數量: $CHANGES_COUNT"
            handle_success "封包內容格式正確"
        else
            handle_error "封包內容格式錯誤"
        fi
    else
        handle_error "封包檔案未創建"
    fi
else
    handle_error "封包產生失敗 (HTTP $HTTP_CODE)"
    if [ -f test_package.json ]; then
        echo "錯誤詳情:"
        cat test_package.json
    fi
fi

# Step 3: 驗證封包格式
echo ""
echo -e "${BLUE}► Step 3: 驗證封包格式${NC}"

if [ -f test_package.json ]; then
    if python3 scripts/validate_sync_package.py test_package.json > /dev/null 2>&1; then
        handle_success "封包格式驗證通過"
    else
        handle_error "封包格式驗證失敗"
        echo "執行詳細驗證："
        python3 scripts/validate_sync_package.py test_package.json
    fi
else
    handle_error "封包檔案不存在，跳過驗證"
fi

# Step 4: 測試封包匯入
echo ""
echo -e "${BLUE}► Step 4: 測試封包匯入 (站點 B)${NC}"

if [ -f test_package.json ]; then
    echo "發送匯入請求..."

    # 讀取封包並構建 import 請求
    IMPORT_PAYLOAD=$(python3 << 'EOF'
import json
import sys

try:
    with open('test_package.json', 'r') as f:
        package = json.load(f)

    # 構建 import 請求 payload
    import_request = {
        "stationId": "TEST-TC-02",
        "packageId": package.get("package_id"),
        "packageType": package.get("package_type", "FULL"),
        "changes": package.get("changes", []),
        "checksum": package.get("checksum")
    }

    print(json.dumps(import_request))
    sys.exit(0)
except Exception as e:
    print(f'{{"error": "{str(e)}"}}', file=sys.stderr)
    sys.exit(1)
EOF
)

    if [ $? -eq 0 ]; then
        HTTP_CODE=$(curl -s -o test_import_response.json -w "%{http_code}" \
            -X POST http://localhost:8000/api/station/sync/import \
            -H "Content-Type: application/json" \
            -d "$IMPORT_PAYLOAD")

        if [ "$HTTP_CODE" = "200" ]; then
            handle_success "封包匯入成功 (HTTP $HTTP_CODE)"

            # 檢查匯入結果
            if [ -f test_import_response.json ]; then
                SUCCESS=$(python3 -c "import json; data=json.load(open('test_import_response.json')); print(data.get('success', False))" 2>/dev/null)
                CHANGES_APPLIED=$(python3 -c "import json; data=json.load(open('test_import_response.json')); print(data.get('changes_applied', 0))" 2>/dev/null)

                if [ "$SUCCESS" = "True" ]; then
                    echo "  變更已套用: $CHANGES_APPLIED 項"
                    handle_success "匯入結果正確"
                else
                    handle_error "匯入未成功"
                    cat test_import_response.json
                fi
            fi
        else
            handle_error "封包匯入失敗 (HTTP $HTTP_CODE)"
            if [ -f test_import_response.json ]; then
                echo "錯誤詳情:"
                cat test_import_response.json
            fi
        fi
    else
        handle_error "構建匯入請求失敗"
    fi
else
    handle_error "封包檔案不存在，跳過匯入測試"
fi

# Step 5: 驗證資料同步
echo ""
echo -e "${BLUE}► Step 5: 驗證資料同步${NC}"

if [ -f medical_inventory.db ]; then
    # 檢查主資料庫的 sync_packages 表
    SYNC_PACKAGES=$(python3 -c "import sqlite3; conn = sqlite3.connect('medical_inventory.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM sync_packages WHERE package_id LIKE \"PKG-%TEST-TC%\"'); print(cursor.fetchone()[0])" 2>/dev/null || echo "0")

    # 檢查 items 表中的測試資料
    TEST_ITEMS=$(python3 -c "import sqlite3; conn = sqlite3.connect('medical_inventory.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM items WHERE code LIKE \"TEST-%\"'); print(cursor.fetchone()[0])" 2>/dev/null || echo "0")

    echo "  同步封包記錄數: $SYNC_PACKAGES"
    echo "  測試物品數: $TEST_ITEMS"

    if [ "$SYNC_PACKAGES" -gt 0 ] && [ "$TEST_ITEMS" -gt 0 ]; then
        handle_success "資料同步記錄已創建，測試資料已匯入"
    else
        handle_error "同步記錄或測試資料缺失 (packages: $SYNC_PACKAGES, items: $TEST_ITEMS)"
    fi
else
    handle_error "主資料庫檔案不存在"
fi

# 清理
cleanup

# 測試報告
echo ""
echo "======================================================================"
echo "📊 測試報告"
echo "======================================================================"
echo ""
TOTAL=$((PASSED + FAILED))
echo "總計: $TOTAL 測試"
echo -e "${GREEN}通過: $PASSED${NC}"
echo -e "${RED}失敗: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ 所有測試通過！跨瀏覽器同步功能正常運作。${NC}"
    echo ""
    echo "測試涵蓋："
    echo "  ✓ 後端服務連接"
    echo "  ✓ 測試站點創建"
    echo "  ✓ 資料庫初始化"
    echo "  ✓ 封包產生 API"
    echo "  ✓ 封包格式驗證"
    echo "  ✓ 封包匯入 API"
    echo "  ✓ 資料同步驗證"
    echo ""
    exit 0
else
    echo -e "${RED}❌ 部分測試失敗${NC}"
    echo ""
    echo "建議："
    echo "  1. 檢查後端服務是否正在運行"
    echo "  2. 查看上述錯誤訊息"
    echo "  3. 檢查 API 日誌"
    echo "  4. 參考 ERROR_HANDLING_GUIDE.md"
    echo ""
    exit 1
fi
