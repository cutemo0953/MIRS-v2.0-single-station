# 醫療站庫存管理系統 (Medical Inventory Management System)

## 簡介 (Introduction)

醫療站庫存管理系統是一個為前線醫療站、備援手術站(BORP)、衛生所及壯闊台灣物資中心設計的完整庫存管理解決方案。

This is a comprehensive inventory management solution designed for frontline medical stations, BORP (Backup Operating Room Platform) surgical stations, health centers, and Taiwan logistics hubs.

## 版本 (Version)

**v1.4.5** - Single Station Edition

## 主要功能 (Key Features)

### 1. 物品管理 (Item Management)
- 物品查詢與篩選
- 即時庫存追蹤
- 低庫存警示
- 批次進貨登記

### 2. 血庫管理 (Blood Bank Management)
- 8種血型完整追蹤 (A+, A-, B+, B-, O+, O-, AB+, AB-)
- 血袋入庫/領用記錄
- Walking Blood Bank 支援
- 歷史記錄查詢

### 3. 設備管理 (Equipment Management)
- 電氣設備監控 (電力百分比追蹤)
- 手術包管理
- 每日自動檢查重置 (07:00am)
- 設備狀態追蹤 (正常/警告/錯誤/待檢查)

### 4. 處置記錄 (Treatment Records)
- 手術記錄管理
- 一般消耗登記
- 藥品領用系統 (MIRS v2.3)
- 緊急領用 (Break-the-Glass)

### 5. 同步管理 (Sync Management)
- 資料包匯出/匯入
- 離線作業支援
- 聯邦架構相容

## 技術架構 (Technical Stack)

### 後端 (Backend)
- **Framework**: FastAPI (Python 3.8+)
- **Database**: SQLite3
- **API**: RESTful API

### 前端 (Frontend)
- **Framework**: Alpine.js v3
- **Styling**: Tailwind CSS v3
- **Icons**: Heroicons

## 快速開始 (Quick Start)

### 系統需求 (Requirements)
- Python 3.8+
- Modern web browser (Chrome, Firefox, Safari, Edge)

### 安裝步驟 (Installation)

1. 安裝依賴套件 (Install dependencies)
```bash
pip install -r requirements_v1.4.5.txt
```

2. 啟動伺服器 (Start server)
```bash
python3 main.py
```

3. 開啟瀏覽器 (Open browser)
```
http://localhost:8000
```

## 設定說明 (Configuration)

### 站點類型 (Station Types)

系統支援以下站點類型:

1. **衛生所** (Health Center)
   - 一般醫療物資管理
   - 基本設備追蹤

2. **備援手術站 (BORP)** (Backup Operating Room Platform)
   - 完整手術包管理
   - 血庫管理
   - 電氣設備監控

3. **物資中心** (Logistics Hub / 壯闊台灣)
   - 大量物資管理
   - 多站點調撥

4. **自訂醫院** (Custom Hospital)
   - 彈性配置功能

### 初始化設定

首次使用時，系統會自動:
- 建立資料庫
- 初始化預設站點 (TC-01)
- 設定基本物資項目

## API文件 (API Documentation)

啟動伺服器後，可透過以下網址查看完整API文件:
```
http://localhost:8000/docs
```

## 目錄結構 (Directory Structure)

```
medical-inventory-system/
├── Index.html              # 前端主頁面
├── main.py                 # 後端主程式
├── medical_inventory.db    # SQLite 資料庫
├── config/                 # 設定檔案
├── database/              # 資料庫相關
├── exports/               # 匯出檔案
├── fonts/                 # 字型檔案
└── README.md              # 本文件
```

## 授權 (License)

© 2024 De Novo Orthopedics Inc. All rights reserved.

## 聯絡資訊 (Contact)

For support and inquiries, please contact De Novo Orthopedics Inc.

---

**醫療站庫存管理系統 v1.4.5**  
*Powered by De Novo Orthopedics Inc*
