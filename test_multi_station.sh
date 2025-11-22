#!/bin/bash
# 多站點測試輔助腳本

echo "================================================"
echo "🏥 醫療庫存管理系統 - 多站點測試工具"
echo "================================================"
echo ""

# 檢查依賴
echo "📋 檢查環境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安裝"
    exit 1
fi
echo "✅ Python3 已安裝: $(python3 --version)"

if ! command -v sqlite3 &> /dev/null; then
    echo "⚠️  SQLite3 未安裝（可選，用於資料庫檢查）"
    echo "   安裝: sudo apt-get install sqlite3"
else
    echo "✅ SQLite3 已安裝"
fi

echo ""
echo "================================================"
echo "請選擇操作："
echo "================================================"
echo "1. 啟動後端服務"
echo "2. 檢查資料庫狀態"
echo "3. 清空測試資料"
echo "4. 查看測試指南"
echo "5. 退出"
echo ""
read -p "請輸入選項 (1-5): " choice

case $choice in
    1)
        echo ""
        echo "🚀 啟動後端服務..."
        echo "================================================"
        echo "服務將在 http://localhost:8000 運行"
        echo "按 Ctrl+C 停止服務"
        echo "================================================"
        echo ""
        echo "📝 下一步："
        echo "1. 開啟瀏覽器訪問 http://localhost:8000"
        echo "2. 開啟開發者工具 (F12) -> Console"
        echo "3. 設定站點ID："
        echo "   localStorage.setItem('stationId', 'TC-01');"
        echo "   localStorage.setItem('stationName', '前線醫療站01');"
        echo "   location.reload();"
        echo ""
        python3 main.py
        ;;

    2)
        echo ""
        echo "🔍 檢查資料庫狀態..."
        echo "================================================"

        if [ ! -f "database/medical_inventory.db" ]; then
            echo "⚠️  資料庫尚未建立"
            echo "提示: 啟動服務後會自動建立資料庫"
        else
            if command -v sqlite3 &> /dev/null; then
                echo ""
                echo "📊 物資庫存統計："
                sqlite3 database/medical_inventory.db "SELECT station_id, COUNT(*) as 物品數量, SUM(quantity) as 總數量 FROM inventory GROUP BY station_id;"

                echo ""
                echo "📊 血袋庫存統計："
                sqlite3 database/medical_inventory.db "SELECT station_id, blood_type, SUM(quantity) as 數量 FROM blood_inventory GROUP BY station_id, blood_type;"

                echo ""
                echo "📊 調撥記錄統計："
                sqlite3 database/medical_inventory.db "SELECT source_station, target_station, COUNT(*) as 次數 FROM transfers GROUP BY source_station, target_station;"

                echo ""
                echo "✅ 資料庫檢查完成"
            else
                echo "⚠️  需要安裝 sqlite3 才能檢查資料庫"
                echo "安裝: sudo apt-get install sqlite3"
            fi
        fi
        ;;

    3)
        echo ""
        read -p "⚠️  確定要清空所有測試資料嗎? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            if [ -f "database/medical_inventory.db" ]; then
                rm database/medical_inventory.db
                echo "✅ 測試資料已清空"
                echo "提示: 重新啟動服務會建立新的空白資料庫"
            else
                echo "⚠️  資料庫檔案不存在"
            fi
        else
            echo "❌ 取消操作"
        fi
        ;;

    4)
        echo ""
        echo "📖 開啟測試指南..."
        if [ -f "QUICK_TEST_MULTI_STATION.md" ]; then
            if command -v less &> /dev/null; then
                less QUICK_TEST_MULTI_STATION.md
            else
                cat QUICK_TEST_MULTI_STATION.md
            fi
        else
            echo "⚠️  找不到測試指南檔案"
        fi
        ;;

    5)
        echo "👋 再見！"
        exit 0
        ;;

    *)
        echo "❌ 無效的選項"
        exit 1
        ;;
esac

echo ""
echo "================================================"
echo "按 Enter 返回..."
read
./test_multi_station.sh
