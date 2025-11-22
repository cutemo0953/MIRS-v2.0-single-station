#!/bin/bash
# 醫療站庫存系統 - 快速啟動腳本
# 用於 Raspberry Pi 5 部署

echo "======================================"
echo "醫療站庫存管理系統 v1.3.2"
echo "快速啟動腳本"
echo "======================================"
echo ""

# 檢查 Python 版本
echo "檢查 Python 環境..."
python3 --version
echo ""

# 檢查必要套件
echo "檢查必要套件..."
pip3 list | grep -E "fastapi|uvicorn|pydantic" > /dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  警告: 缺少必要套件"
    echo "正在安裝..."
    pip3 install fastapi uvicorn pydantic --break-system-packages
fi
echo "✓ 套件檢查完成"
echo ""

# 檢查資料庫
if [ ! -f "medical_inventory.db" ]; then
    echo "📁 首次運行 - 將建立資料庫"
    echo ""
fi

# 詢問是否導入物資主檔
if [ -f "import_items.py" ]; then
    echo "❓ 是否要導入物資主檔？"
    echo "   (如果是首次部署或需要重新載入物品，請選擇 Y)"
    read -p "   導入物資? (Y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        echo "正在導入物資主檔..."
        # 先啟動後端以初始化資料庫
        python3 main.py &
        BACKEND_PID=$!
        sleep 3
        # 導入物資
        python3 import_items.py
        # 停止暫時啟動的後端
        kill $BACKEND_PID 2>/dev/null
        echo ""
    fi
fi

# 啟動後端
echo "🚀 啟動後端 API..."
echo "   監聽: http://0.0.0.0:8000"
echo "   日誌: medical_inventory.log"
echo ""
echo "提示: 使用 Ctrl+C 停止服務"
echo "======================================"
echo ""

# 啟動 FastAPI
python3 main.py

# 清理
echo ""
echo "系統已停止"
