#!/usr/bin/env python3
"""
醫療站庫存管理系統 - 後端 API
版本: v1.5.0
新增: 藥品分流管理、血袋標籤列印、政府標準預載資料庫
v1.4.8: 樹莓派部署修復、韌性估算修正、PWA 配對修正
v1.4.9: 藥局撥發 API (Pharmacy Dispatch v1.1) - 庫存保留、撥發確認、收貨回執
v1.5.0: 麻醉模組 (Anesthesia Module v1.5.1) - Event-Sourced 架構
"""

import logging
import sys
import socket
from datetime import datetime, timedelta, time
from typing import Optional, List, Dict, Any
from pathlib import Path
import sqlite3
import json
import csv
import io
import zipfile
import shutil
import hashlib
import asyncio
import os
import secrets
import base64
import binascii
from enum import Enum

# ============================================================================
# Vercel 環境偵測
# ============================================================================
IS_VERCEL = os.environ.get("VERCEL") == "1"
PROJECT_ROOT = Path(__file__).parent

from fastapi import FastAPI, HTTPException, status, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
import uvicorn

# v1.4.5新增: 緊急功能相關套件
import qrcode
from io import BytesIO

# v1.5.1新增: 麻醉模組
try:
    from routes.anesthesia import router as anesthesia_router, init_anesthesia_schema
    ANESTHESIA_MODULE_AVAILABLE = True
except ImportError as e:
    ANESTHESIA_MODULE_AVAILABLE = False
    anesthesia_router = None
    init_anesthesia_schema = None


# ============================================================================
# 日誌配置
# ============================================================================

def setup_logging():
    """設定日誌系統"""
    handlers = [logging.StreamHandler(sys.stdout)]

    # Only add file handler for non-Vercel environments
    if not IS_VERCEL:
        try:
            handlers.append(logging.FileHandler('medical_inventory.log', encoding='utf-8'))
        except Exception:
            pass  # Skip file logging if not writable

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================================
# 選用套件載入 (需在 logger 初始化後)
# ============================================================================

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("Pandas not available, some export features will be limited")

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("ReportLab not available, PDF generation will be limited")


# ============================================================================
# 配置
# ============================================================================

class StationType(str, Enum):
    """站點類型枚舉"""
    HC = "HC"           # Health Center 衛生所
    BORP = "BORP"       # Backup Operating Room Point 備援手術室
    LOG_HUB = "LOG-HUB" # Logistic Hub 物資中心
    HOSP = "HOSP"       # Hospital Custom 醫院自訂

class Config:
    """系統配置 - v1.4.8 穩定單站點架構"""
    VERSION = "1.5.0-demo" if IS_VERCEL else "1.5.0"
    DATABASE_PATH = ":memory:" if IS_VERCEL else "medical_inventory.db"
    TEMPLATES_PATH = str(PROJECT_ROOT / "templates")

    # ========== 站點配置 (三層結構) ==========
    # TYPE: 決定載入的資料庫 Template
    STATION_TYPE: str = os.getenv("MIRS_STATION_TYPE", "BORP")

    # ORG: 機構識別碼
    STATION_ORG: str = os.getenv("MIRS_STATION_ORG", "DNO")

    # NUMBER: 站點編號
    STATION_NUMBER: str = os.getenv("MIRS_STATION_NUMBER", "01")

    # 組合成完整站點 ID
    @classmethod
    def get_station_id(cls) -> str:
        return f"{cls.STATION_TYPE}-{cls.STATION_ORG}-{cls.STATION_NUMBER}"

    # ========== 站點顯示名稱 ==========
    STATION_NAME: str = os.getenv("MIRS_STATION_NAME", "谷盺備援手術室 01")

    @classmethod
    def get_station_name(cls) -> str:
        """取得站點顯示名稱，如果未設定則自動生成"""
        if cls.STATION_NAME:
            return cls.STATION_NAME

        type_names = {
            "HC": "衛生所",
            "BORP": "備援手術室",
            "LOG-HUB": "物資中心",
            "HOSP": "醫院站"
        }
        type_name = type_names.get(cls.STATION_TYPE, "站點")
        return f"{cls.STATION_ORG} {type_name} {cls.STATION_NUMBER}"

    # ========== 組織配置 ==========
    ORG_CODE: str = os.getenv("MIRS_ORG_CODE", "DNO")
    ORG_NAME: str = os.getenv("MIRS_ORG_NAME", "De Novo Orthopedics")

    # ========== 系統配置 ==========
    DEBUG: bool = os.getenv("MIRS_DEBUG", "false").lower() == "true"
    TIMEZONE: str = "Asia/Taipei"

    # 血型列表
    BLOOD_TYPES = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']

    # ========== Template 對應表 ==========
    TEMPLATE_MAP = {
        "HC": "template_hc.sql",
        "BORP": "template_borp.sql",
        "LOG-HUB": "template_log.sql",
        "HOSP": "template_hosp.sql"
    }

    @classmethod
    def get_template_path(cls) -> Optional[Path]:
        """取得對應的 Template 檔案路徑"""
        template_file = cls.TEMPLATE_MAP.get(cls.STATION_TYPE)
        if template_file:
            template_path = Path(cls.TEMPLATES_PATH) / template_file
            if template_path.exists():
                return template_path
        return None

    @classmethod
    def load_from_file(cls, config_path: str = "config/station_config.json"):
        """從配置檔案載入站點設定"""
        config_file = Path(config_path)
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # 載入站點配置
                    if 'station' in data:
                        station = data['station']
                        cls.STATION_TYPE = station.get('type', cls.STATION_TYPE)
                        cls.STATION_ORG = station.get('org', cls.STATION_ORG)
                        cls.STATION_NUMBER = station.get('number', cls.STATION_NUMBER)
                        cls.STATION_NAME = station.get('name', cls.STATION_NAME)

                    # 載入組織配置
                    if 'organization' in data:
                        org = data['organization']
                        cls.ORG_CODE = org.get('code', cls.ORG_CODE)
                        cls.ORG_NAME = org.get('name', cls.ORG_NAME)

                    logger.info(f"✓ 配置載入成功: {cls.get_station_id()}")

            except Exception as e:
                logger.warning(f"無法載入配置檔案: {e}，使用預設值")
        else:
            logger.info(f"配置檔案不存在: {config_path}，使用預設值")

        return cls

# 初始化配置
config = Config.load_from_file()

# 為了向下相容，設定 STATION_ID 屬性
Config.STATION_ID = Config.get_station_id()


# ============================================================================
# Pydantic Models - 請求模型
# ============================================================================

class ReceiveRequest(BaseModel):
    """進貨請求"""
    itemCode: str = Field(..., description="物品代碼", min_length=1)
    quantity: int = Field(..., gt=0, description="數量必須大於0")
    batchNumber: Optional[str] = Field(None, description="批號")
    expiryDate: Optional[str] = Field(None, description="效期 (YYYY-MM-DD)")
    remarks: Optional[str] = Field(None, description="備註", max_length=500)
    stationId: str = Field(default="HC-000000", description="站點ID")

    @field_validator('expiryDate')
    @classmethod
    def validate_expiry_date(cls, v):
        """驗證效期格式"""
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
            except ValueError:
                raise ValueError('效期格式必須為 YYYY-MM-DD')
        return v


class ConsumeRequest(BaseModel):
    """消耗請求"""
    itemCode: str = Field(..., description="物品代碼", min_length=1)
    quantity: int = Field(..., gt=0, description="數量必須大於0")
    purpose: str = Field(..., description="用途說明", min_length=1, max_length=500)
    stationId: str = Field(default="HC-000000", description="站點ID")


class BloodRequest(BaseModel):
    """血袋請求"""
    bloodType: str = Field(..., description="血型")
    quantity: int = Field(..., gt=0, description="數量(U)必須大於0")
    stationId: str = Field(default="HC-000000", description="站點ID")

    @field_validator('bloodType')
    @classmethod
    def validate_blood_type(cls, v):
        """驗證血型"""
        if v not in config.BLOOD_TYPES:
            raise ValueError(f'血型必須為以下之一: {", ".join(config.BLOOD_TYPES)}')
        return v


class BloodTransferRequest(BaseModel):
    """血袋併站轉移請求"""
    bloodType: str = Field(..., description="血型")
    quantity: int = Field(..., gt=0, description="數量(U)必須大於0")
    sourceStationId: str = Field(..., description="來源站點ID")
    targetStationId: str = Field(..., description="目標站點ID")
    operator: str = Field(default="SYSTEM", description="操作人員")
    remarks: Optional[str] = Field(None, description="備註")

    @field_validator('bloodType')
    @classmethod
    def validate_blood_type(cls, v):
        """驗證血型"""
        if v not in config.BLOOD_TYPES:
            raise ValueError(f'血型必須為以下之一: {", ".join(config.BLOOD_TYPES)}')
        return v


class EmergencyBloodBagRequest(BaseModel):
    """緊急血袋登記請求 (v1.4.5)"""
    bloodType: str = Field(..., description="血型 (A+/A-/B+/B-/O+/O-/AB+/AB-)")
    productType: str = Field(..., description="血品類型 (WHOLE_BLOOD/PLATELET/FROZEN_PLASMA/RBC_CONCENTRATE)")
    collectionDate: str = Field(..., description="採集日期 (YYYY-MM-DD)")
    volumeMl: int = Field(default=250, ge=50, le=500, description="容量 (ml)")
    stationId: str = Field(default="HC-000000", description="站點ID")
    operator: str = Field(..., description="操作人員", min_length=1)
    orgCode: str = Field(default="DNO", description="組織代碼", max_length=4)
    remarks: Optional[str] = Field(None, description="備註", max_length=500)

    @field_validator('bloodType')
    @classmethod
    def validate_blood_type(cls, v):
        if v not in config.BLOOD_TYPES:
            raise ValueError(f'血型必須為以下之一: {", ".join(config.BLOOD_TYPES)}')
        return v

    @field_validator('productType')
    @classmethod
    def validate_product_type(cls, v):
        valid_types = ["WHOLE_BLOOD", "PLATELET", "FROZEN_PLASMA", "RBC_CONCENTRATE"]
        if v not in valid_types:
            raise ValueError(f'血品類型必須為以下之一: {", ".join(valid_types)}')
        return v


class EmergencyBloodBagUseRequest(BaseModel):
    """緊急血袋使用請求 (v1.4.5)"""
    bloodBagCode: str = Field(..., description="血袋編號")
    patientName: str = Field(..., description="病患姓名", min_length=1, max_length=100)
    operator: str = Field(..., description="操作人員", min_length=1)


class EquipmentCheckRequest(BaseModel):
    """設備檢查請求"""
    stationId: str = Field(default="HC-000000", description="站點ID")
    status: str = Field(default="NORMAL", description="設備狀態")
    powerLevel: Optional[int] = Field(None, ge=0, le=100, description="電力等級 (0-100%)")
    remarks: Optional[str] = Field(None, description="備註", max_length=500)


class EquipmentCreateRequest(BaseModel):
    """設備新增請求"""
    name: str = Field(..., description="設備名稱", min_length=1, max_length=200)
    category: str = Field(default="其他", description="設備分類", max_length=100)
    quantity: int = Field(default=1, ge=1, description="數量")
    remarks: Optional[str] = Field(None, description="備註", max_length=500)


class EquipmentUpdateRequest(BaseModel):
    """設備更新請求"""
    name: Optional[str] = Field(None, description="設備名稱", min_length=1, max_length=200)
    category: Optional[str] = Field(None, description="設備分類", max_length=100)
    quantity: Optional[int] = Field(None, ge=0, description="數量")
    status: Optional[str] = Field(None, description="設備狀態")
    remarks: Optional[str] = Field(None, description="備註", max_length=500)


# ============================================================================
# v2.1 設備單位管理 API 請求模型
# ============================================================================

class UnitAddRequest(BaseModel):
    """新增設備單位請求 (v2.1)"""
    level_percent: int = Field(default=100, ge=0, le=100, description="電量/充填百分比")
    status: str = Field(default="AVAILABLE", description="狀態")
    reason: Optional[str] = Field(None, description="新增原因", max_length=500)


class UnitRemoveRequest(BaseModel):
    """移除設備單位請求 (v2.1 Soft Delete)"""
    reason: Optional[str] = Field(None, description="移除原因", max_length=500)
    actor: Optional[str] = Field(None, description="操作者", max_length=100)


class UnitUpdateRequest(BaseModel):
    """更新設備單位屬性請求 (v2.1)"""
    level_percent: Optional[int] = Field(None, ge=0, le=100, description="電量/充填百分比")
    status: Optional[str] = Field(None, description="狀態")
    unit_label: Optional[str] = Field(None, description="單位標籤", max_length=100)


class BatchQuantityRequest(BaseModel):
    """批次調整數量請求 (v2.1)"""
    target_quantity: int = Field(..., ge=0, description="目標數量")
    default_level_percent: int = Field(default=100, ge=0, le=100, description="新增單位預設電量")
    default_status: str = Field(default="AVAILABLE", description="新增單位預設狀態")
    reason: Optional[str] = Field(None, description="調整原因", max_length=500)


class ItemCreateRequest(BaseModel):
    """物品新增請求"""
    code: Optional[str] = Field(None, description="物品代碼(留空自動生成)", max_length=50)
    name: str = Field(..., description="物品名稱", min_length=1, max_length=200)
    unit: str = Field(default="EA", description="單位", max_length=20)
    minStock: int = Field(default=10, ge=0, description="最小庫存")
    category: str = Field(default="其他", description="分類", max_length=100)


class ItemUpdateRequest(BaseModel):
    """物品更新請求"""
    name: Optional[str] = Field(None, description="物品名稱", min_length=1, max_length=200)
    unit: Optional[str] = Field(None, description="單位", max_length=20)
    minStock: Optional[int] = Field(None, ge=0, description="最小庫存")
    category: Optional[str] = Field(None, description="分類", max_length=100)


class SurgeryConsumptionItem(BaseModel):
    """手術耗材項目"""
    itemCode: str = Field(..., description="物品代碼")
    itemName: str = Field(..., description="物品名稱")
    quantity: int = Field(..., gt=0, description="數量")
    unit: str = Field(..., description="單位")


class SurgeryRecordRequest(BaseModel):
    """手術記錄請求"""
    patientName: str = Field(..., description="病患姓名", min_length=1, max_length=100)
    cirsPersonId: Optional[str] = Field(None, description="CIRS 人員序號 (如 P0001)，用於關聯 CIRS 系統", max_length=20)
    surgeryType: str = Field(..., description="手術類型", min_length=1, max_length=200)
    surgeonName: str = Field(..., description="主刀醫師", min_length=1, max_length=100)
    anesthesiaType: Optional[str] = Field(None, description="麻醉方式", max_length=100)
    durationMinutes: Optional[int] = Field(None, ge=0, description="手術時長(分鐘)")
    remarks: Optional[str] = Field(None, description="手術備註", max_length=2000)
    consumptions: List[SurgeryConsumptionItem] = Field(..., description="使用耗材清單")
    stationId: str = Field(default="HC-000000", description="站點ID")


# ============================================================================
# MIRS v2.3 - Emergency Dispense Models (Break-the-Glass Feature)
# ============================================================================

class EmergencyDispenseRequest(BaseModel):
    """緊急領用請求 (Break-the-Glass) - MIRS v2.3 Section 4.1"""
    medicineCode: str = Field(..., description="藥品代碼", min_length=1)
    quantity: int = Field(..., gt=0, description="數量必須大於0")
    dispensedBy: str = Field(..., description="領藥人", min_length=1, max_length=100)
    emergencyReason: str = Field(..., description="緊急原因 (5-50字)", min_length=5, max_length=200)
    patientRefId: Optional[str] = Field(None, description="病患參考編號 (Triage Tag)", max_length=50)
    patientName: Optional[str] = Field(None, description="病患姓名", max_length=100)
    stationCode: str = Field(default="HC-000000", description="站點代碼")

    @field_validator('emergencyReason')
    @classmethod
    def validate_emergency_reason(cls, v):
        """驗證緊急原因不能為空或過短"""
        if not v or len(v.strip()) < 5:
            raise ValueError('緊急原因必須至少5個字，防止濫用')
        return v.strip()


class NormalDispenseRequest(BaseModel):
    """正常領用請求 (需藥師審核)"""
    medicineCode: str = Field(..., description="藥品代碼", min_length=1)
    quantity: int = Field(..., gt=0, description="數量必須大於0")
    dispensedBy: str = Field(..., description="領藥人", min_length=1, max_length=100)
    patientRefId: Optional[str] = Field(None, description="病患參考編號 (Triage Tag)", max_length=50)
    patientName: Optional[str] = Field(None, description="病患姓名", max_length=100)
    prescriptionId: Optional[str] = Field(None, description="處方ID", max_length=50)
    stationCode: str = Field(default="HC-000000", description="站點代碼")


class DispenseApprovalRequest(BaseModel):
    """藥師審核請求 (用於審核 PENDING 或確認 EMERGENCY 記錄)"""
    dispenseId: int = Field(..., description="領用記錄ID", gt=0)
    approvedBy: str = Field(..., description="審核藥師", min_length=1, max_length=100)
    pharmacistNotes: Optional[str] = Field(None, description="藥師備註", max_length=500)
    pinCode: str = Field(..., description="藥師PIN碼", min_length=4, max_length=6)

    @field_validator('pinCode')
    @classmethod
    def validate_pin(cls, v):
        """驗證PIN碼格式"""
        if not v.isdigit():
            raise ValueError('PIN碼必須為數字')
        return v


class DispenseRecordResponse(BaseModel):
    """領用記錄回應"""
    id: int
    medicineCode: str
    medicineName: str
    quantity: int
    unit: str
    dispensedBy: str
    approvedBy: Optional[str]
    status: str
    emergencyReason: Optional[str]
    patientRefId: Optional[str]
    patientName: Optional[str]
    stationCode: str
    createdAt: str
    updatedAt: str
    approvedAt: Optional[str]
    hoursPending: Optional[int] = None


# ============================================================================
# 聯邦架構 - 同步封包 Models (Phase 1)
# ============================================================================

class SyncChangeRecord(BaseModel):
    """同步變更記錄"""
    table: str = Field(..., description="資料表名稱")
    operation: str = Field(..., description="操作類型: INSERT, UPDATE, DELETE")
    data: dict = Field(..., description="資料內容")
    timestamp: str = Field(..., description="變更時間戳")


class SyncPackageGenerate(BaseModel):
    """產生同步封包請求"""
    stationId: str = Field(..., description="站點ID")
    hospitalId: str = Field(..., description="所屬醫院ID")
    syncType: str = Field(default="DELTA", description="同步類型: DELTA (增量) / FULL (全量)")
    sinceTimestamp: Optional[str] = Field(None, description="增量同步起始時間 (ISO 8601 格式)")


class SyncPackageUpload(BaseModel):
    """站點同步上傳請求"""
    stationId: str = Field(..., description="站點ID")
    packageId: str = Field(..., description="封包ID")
    packageType: str = Field(default="FULL", description="封包類型：DELTA 或 FULL")
    changes: List[SyncChangeRecord] = Field(..., description="變更記錄清單")
    checksum: str = Field(..., description="封包校驗碼 (SHA-256)")


class HospitalTransferCoordinate(BaseModel):
    """醫院層院內調撥協調請求 (Phase 2)"""
    hospitalId: str = Field(..., description="醫院ID")
    fromStationId: str = Field(..., description="來源站點ID")
    toStationId: str = Field(..., description="目標站點ID")
    resourceType: str = Field(..., description="資源類型: ITEM, BLOOD, EQUIPMENT")
    resourceId: str = Field(..., description="資源ID (item_code, blood_type, equipment_id)")
    resourceName: str = Field(..., description="資源名稱")
    quantity: int = Field(..., gt=0, description="數量")
    operator: str = Field(default="SYSTEM", description="操作人員")
    reason: Optional[str] = Field(None, description="調撥原因")


# ============================================================================
# 資料庫管理器
# ============================================================================

class NonClosingConnection:
    """包裝連接，忽略 close() 調用 (用於記憶體模式)"""
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        """忽略關閉請求"""
        pass

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


class DatabaseManager:
    """資料庫管理器 - 處理所有資料庫操作"""

    # Singleton connection for in-memory mode
    _memory_connection = None

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.is_memory = (db_path == ":memory:")
        logger.info(f"初始化資料庫: {db_path} (in-memory: {self.is_memory})")
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        """取得資料庫連接"""
        if self.is_memory:
            # For in-memory mode, reuse singleton connection wrapped to ignore close()
            if DatabaseManager._memory_connection is None:
                DatabaseManager._memory_connection = sqlite3.connect(
                    self.db_path, check_same_thread=False
                )
                DatabaseManager._memory_connection.row_factory = sqlite3.Row
            return NonClosingConnection(DatabaseManager._memory_connection)
        else:
            # For file-based mode, create new connection
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

    def close_connection(self, conn: sqlite3.Connection):
        """安全關閉連接 - 記憶體模式下不關閉"""
        if not self.is_memory:
            conn.close()

    def reset_memory_db(self):
        """Reset in-memory database (for demo reset feature)"""
        if not self.is_memory:
            return False
        if DatabaseManager._memory_connection:
            try:
                DatabaseManager._memory_connection.close()
            except:
                pass
            DatabaseManager._memory_connection = None
        self.init_database()
        return True
    
    def init_database(self):
        """初始化資料庫結構"""
        logger.info("開始初始化資料庫結構...")
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 物品主檔
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    item_code TEXT PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    item_category TEXT,
                    category TEXT,
                    unit TEXT DEFAULT 'EA',
                    min_stock INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 藥品主檔 (v2.3新增 - Emergency Dispense功能)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS medicines (
                    medicine_code TEXT PRIMARY KEY,
                    generic_name TEXT NOT NULL,
                    brand_name TEXT,
                    unit TEXT DEFAULT '顆',
                    min_stock INTEGER DEFAULT 100,
                    current_stock INTEGER DEFAULT 0,
                    is_controlled_drug INTEGER DEFAULT 0,
                    controlled_level TEXT,
                    is_active INTEGER DEFAULT 1,
                    station_id TEXT NOT NULL DEFAULT 'HC-000000',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(is_controlled_drug IN (0, 1)),
                    CHECK(is_active IN (0, 1))
                )
            """)

            # ========== v1.4.2-plus 新增: 藥品分流管理 ==========
            # 藥品主檔 (pharmaceuticals) - 獨立於一般耗材
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pharmaceuticals (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    generic_name TEXT,
                    unit TEXT DEFAULT 'Tab',
                    min_stock INTEGER DEFAULT 50,
                    current_stock INTEGER DEFAULT 0,
                    category TEXT DEFAULT '常用藥品',
                    storage_condition TEXT DEFAULT '常溫',
                    controlled_level TEXT DEFAULT '非管制',
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(category IN ('常用藥品', '急救藥品', '麻醉藥品', '管制藥品', '輸液')),
                    CHECK(storage_condition IN ('常溫', '冷藏', '冷凍')),
                    CHECK(controlled_level IN ('非管制', '一級', '二級', '三級', '四級')),
                    CHECK(is_active IN (0, 1))
                )
            """)

            # 藥品庫存事件 (pharma_events)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pharma_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    pharma_code TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    batch_number TEXT,
                    expiry_date TEXT,
                    remarks TEXT,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (pharma_code) REFERENCES pharmaceuticals(code),
                    CHECK(event_type IN ('RECEIVE', 'CONSUME', 'ADJUST', 'EXPIRE'))
                )
            """)

            # 藥品索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pharma_category
                ON pharmaceuticals(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pharma_events_code
                ON pharma_events(pharma_code, timestamp DESC)
            """)

            # ========== v1.4.2-plus 新增: 血袋個別追蹤 ==========
            # 血袋主檔 (blood_bags) - 每袋獨立編號
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blood_bags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bag_code TEXT UNIQUE NOT NULL,
                    blood_type TEXT NOT NULL,
                    volume_ml INTEGER DEFAULT 250,
                    collection_date DATE,
                    expiry_date DATE,
                    status TEXT DEFAULT 'AVAILABLE',
                    donor_id TEXT,
                    donor_info TEXT,
                    batch_number TEXT,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_at TIMESTAMP,
                    used_for TEXT,
                    station_id TEXT,
                    CHECK(status IN ('AVAILABLE', 'RESERVED', 'USED', 'EXPIRED', 'DISCARDED'))
                )
            """)

            # v1.4.2-plus: 確保 donor_info 欄位存在 (支援既有資料庫升級)
            try:
                cursor.execute("ALTER TABLE blood_bags ADD COLUMN donor_info TEXT")
            except:
                pass  # 欄位已存在則忽略

            # v1.5.1: 確保 station_id 欄位存在 (修復血袋站點追蹤 bug)
            try:
                cursor.execute("ALTER TABLE blood_bags ADD COLUMN station_id TEXT")
            except:
                pass  # 欄位已存在則忽略

            # 血袋索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_blood_bags_type_status
                ON blood_bags(blood_type, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_blood_bags_expiry
                ON blood_bags(expiry_date)
            """)

            # 庫存事件記錄
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    item_code TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    batch_number TEXT,
                    expiry_date TEXT,
                    remarks TEXT,
                    station_id TEXT NOT NULL,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_code) REFERENCES items(item_code)
                )
            """)
            
            # 為事件表建立索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_inventory_events_item 
                ON inventory_events(item_code)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_inventory_events_timestamp 
                ON inventory_events(timestamp)
            """)
            
            # 血袋庫存(支援多站點)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blood_inventory (
                    blood_type TEXT NOT NULL,
                    quantity INTEGER DEFAULT 0,
                    station_id TEXT NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (blood_type, station_id)
                )
            """)
            
            # 血袋事件記錄
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blood_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    blood_type TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    station_id TEXT NOT NULL,
                    operator TEXT DEFAULT 'SYSTEM',
                    remarks TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # v1.4.2-plus: 確保 remarks 欄位存在 (支援既有資料庫升級)
            try:
                cursor.execute("ALTER TABLE blood_events ADD COLUMN remarks TEXT")
            except:
                pass  # 欄位已存在則忽略

            # 緊急血袋登記 (v1.4.5新增)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS emergency_blood_bags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    blood_bag_code TEXT UNIQUE NOT NULL,
                    blood_type TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    collection_date DATE NOT NULL,
                    expiry_date DATE NOT NULL,
                    volume_ml INTEGER DEFAULT 250,
                    status TEXT DEFAULT 'AVAILABLE',
                    station_id TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    patient_name TEXT,
                    usage_timestamp TIMESTAMP,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(status IN ('AVAILABLE', 'USED', 'EXPIRED', 'DISCARDED'))
                )
            """)

            # 設備主檔 (v2.0 新增 type_code, tracking_mode 等韌性欄位)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS equipment (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT DEFAULT '其他',
                    quantity INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'UNCHECKED',
                    last_check TIMESTAMP,
                    power_level INTEGER,
                    remarks TEXT,
                    type_code TEXT,
                    tracking_mode TEXT DEFAULT 'AGGREGATE',
                    device_type TEXT,
                    power_watts REAL,
                    capacity_wh REAL,
                    output_watts REAL,
                    fuel_rate_lph REAL,
                    capacity_override TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 設備檢查記錄
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS equipment_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equipment_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    power_level INTEGER,
                    remarks TEXT,
                    station_id TEXT NOT NULL,
                    operator TEXT DEFAULT 'SYSTEM',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
                )
            """)
            
            # 手術記錄主檔 (新增)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS surgery_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_number TEXT UNIQUE NOT NULL,
                    record_date DATE NOT NULL,
                    patient_name TEXT NOT NULL,
                    surgery_sequence INTEGER NOT NULL,
                    surgery_type TEXT NOT NULL,
                    surgeon_name TEXT NOT NULL,
                    anesthesia_type TEXT,
                    duration_minutes INTEGER,
                    remarks TEXT,
                    station_id TEXT NOT NULL,
                    status TEXT DEFAULT 'ONGOING',
                    patient_outcome TEXT,
                    archived_at TIMESTAMP,
                    archived_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(status IN ('ONGOING', 'COMPLETED', 'ARCHIVED', 'CANCELLED')),
                    CHECK(patient_outcome IS NULL OR patient_outcome IN ('DISCHARGED', 'TRANSFERRED', 'DECEASED'))
                )
            """)
            
            # 手術耗材明細 (新增)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS surgery_consumptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    surgery_id INTEGER NOT NULL,
                    item_code TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit TEXT NOT NULL,
                    FOREIGN KEY (surgery_id) REFERENCES surgery_records(id) ON DELETE CASCADE,
                    FOREIGN KEY (item_code) REFERENCES items(item_code)
                )
            """)

            # 領藥記錄 (MIRS v2.3 - Emergency Dispense / Break-the-Glass)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dispense_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    medicine_code TEXT NOT NULL,
                    medicine_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    unit TEXT NOT NULL DEFAULT '顆',
                    dispensed_by TEXT NOT NULL,
                    approved_by TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    emergency_reason TEXT,
                    patient_ref_id TEXT,
                    patient_name TEXT,
                    station_code TEXT NOT NULL DEFAULT 'HC-000000',
                    storage_location TEXT,
                    batch_number TEXT,
                    lot_number TEXT,
                    expiry_date DATE,
                    prescription_id TEXT,
                    approved_at TIMESTAMP,
                    pharmacist_notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    unit_cost REAL DEFAULT 0,
                    CHECK (status IN ('PENDING', 'APPROVED', 'EMERGENCY')),
                    CHECK (unit_cost >= 0),
                    CHECK (
                        (status = 'EMERGENCY' AND emergency_reason IS NOT NULL AND LENGTH(emergency_reason) >= 5) OR
                        (status != 'EMERGENCY')
                    )
                )
            """)

            # 領藥記錄索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dispense_status_date
                ON dispense_records(status, created_at DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dispense_emergency
                ON dispense_records(status, created_at DESC)
                WHERE status = 'EMERGENCY'
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dispense_medicine
                ON dispense_records(medicine_code, created_at DESC)
            """)

            # 站點合併歷史 (v1.4.5新增 - 合併功能)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS station_merge_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_station_id TEXT NOT NULL,
                    target_station_id TEXT NOT NULL,
                    merge_type TEXT NOT NULL,
                    items_merged INTEGER DEFAULT 0,
                    blood_merged INTEGER DEFAULT 0,
                    equipment_merged INTEGER DEFAULT 0,
                    surgery_records_merged INTEGER DEFAULT 0,
                    merge_notes TEXT,
                    merged_by TEXT NOT NULL,
                    merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(merge_type IN ('FULL_MERGE', 'PARTIAL_MERGE', 'IMPORT_BACKUP'))
                )
            """)

            # 盤點記錄 (v1.4.5新增 - 清點功能)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_number TEXT UNIQUE NOT NULL,
                    audit_type TEXT NOT NULL,
                    status TEXT DEFAULT 'IN_PROGRESS',
                    station_id TEXT NOT NULL,
                    started_by TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_by TEXT,
                    completed_at TIMESTAMP,
                    total_items INTEGER DEFAULT 0,
                    discrepancies INTEGER DEFAULT 0,
                    notes TEXT,
                    CHECK(audit_type IN ('ROUTINE', 'PRE_MERGE', 'POST_MERGE', 'EMERGENCY')),
                    CHECK(status IN ('IN_PROGRESS', 'COMPLETED', 'CANCELLED'))
                )
            """)

            # 盤點明細 (v1.4.5新增)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory_audit_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id INTEGER NOT NULL,
                    item_code TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    system_quantity INTEGER NOT NULL,
                    actual_quantity INTEGER NOT NULL,
                    discrepancy INTEGER NOT NULL,
                    remarks TEXT,
                    audited_by TEXT NOT NULL,
                    audited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (audit_id) REFERENCES inventory_audit(id) ON DELETE CASCADE,
                    FOREIGN KEY (item_code) REFERENCES items(item_code)
                )
            """)

            # ========== 資料庫索引優化 (v1.4.5) ==========
            # 手術記錄索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_surgery_records_date
                ON surgery_records(record_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_surgery_records_patient
                ON surgery_records(patient_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_surgery_consumptions_surgery
                ON surgery_consumptions(surgery_id)
            """)

            # CIRS Integration: 新增 cirs_person_id 欄位 (v2.0.1)
            # 用於關聯 CIRS 社區韌性系統的人員 ID (如 P0001)
            try:
                cursor.execute("ALTER TABLE surgery_records ADD COLUMN cirs_person_id TEXT")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_surgery_cirs_person ON surgery_records(cirs_person_id)")
            except:
                pass  # 欄位已存在則忽略

            # 庫存物品索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_category
                ON items(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_updated
                ON items(updated_at DESC)
            """)

            # 庫存事件索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_inventory_events_item
                ON inventory_events(item_code, timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_inventory_events_time
                ON inventory_events(timestamp DESC)
            """)

            # 血袋事件索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_blood_events_type
                ON blood_events(blood_type, timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_blood_events_time
                ON blood_events(timestamp DESC)
            """)

            # 緊急血袋索引 (v1.4.5新增)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_emergency_blood_status
                ON emergency_blood_bags(status, collection_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_emergency_blood_type
                ON emergency_blood_bags(blood_type, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_emergency_blood_expiry
                ON emergency_blood_bags(expiry_date)
            """)

            # 設備索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_equipment_status
                ON equipment(status, last_check DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_equipment_category
                ON equipment(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_equipment_checks_time
                ON equipment_checks(timestamp DESC)
            """)

            # 手術記錄狀態索引 (v1.4.5新增 - 封存功能)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_surgery_records_status
                ON surgery_records(status, record_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_surgery_records_outcome
                ON surgery_records(patient_outcome)
            """)

            # 站點合併索引 (v1.4.5新增)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_merge_history_station
                ON station_merge_history(target_station_id, merged_at DESC)
            """)

            # 盤點記錄索引 (v1.4.5新增)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_status
                ON inventory_audit(status, started_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_details_audit
                ON inventory_audit_details(audit_id)
            """)
            # ========== 索引優化結束 ==========

            # ========== 聯邦式架構表格 (Phase 0) ==========
            # 醫院基本資料
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hospitals (
                    hospital_id TEXT PRIMARY KEY,
                    hospital_name TEXT NOT NULL,
                    hospital_type TEXT NOT NULL DEFAULT 'FIELD_HOSPITAL',
                    command_level TEXT NOT NULL DEFAULT 'LOCAL',
                    latitude REAL,
                    longitude REAL,
                    contact_info TEXT,
                    network_access TEXT DEFAULT 'NONE',
                    total_stations INTEGER DEFAULT 0,
                    operational_status TEXT DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(hospital_type IN ('FIELD_HOSPITAL', 'CIVILIAN_HOSPITAL', 'MOBILE_HOSPITAL')),
                    CHECK(command_level IN ('CENTRAL', 'REGIONAL', 'LOCAL')),
                    CHECK(network_access IN ('NONE', 'MILITARY', 'SATELLITE', 'CIVILIAN')),
                    CHECK(operational_status IN ('ACTIVE', 'OFFLINE', 'EVACUATED', 'MERGED'))
                )
            """)

            # 站點基本資料
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stations (
                    station_id TEXT PRIMARY KEY,
                    station_name TEXT NOT NULL,
                    hospital_id TEXT NOT NULL,
                    station_type TEXT DEFAULT 'SMALL',
                    latitude REAL,
                    longitude REAL,
                    network_access TEXT DEFAULT 'NONE',
                    operational_status TEXT DEFAULT 'ACTIVE',
                    last_sync_at TIMESTAMP,
                    sync_status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id),
                    CHECK(station_type IN ('LARGE', 'SMALL')),
                    CHECK(network_access IN ('NONE', 'INTRANET', 'MILITARY')),
                    CHECK(sync_status IN ('PENDING', 'SYNCING', 'SYNCED', 'FAILED')),
                    CHECK(operational_status IN ('ACTIVE', 'OFFLINE', 'EVACUATED', 'MERGED'))
                )
            """)

            # 同步封包追蹤表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_packages (
                    package_id TEXT PRIMARY KEY,
                    package_type TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    destination_type TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    hospital_id TEXT NOT NULL,
                    transfer_method TEXT NOT NULL,
                    package_size INTEGER,
                    checksum TEXT NOT NULL,
                    changes_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    uploaded_at TIMESTAMP,
                    processed_at TIMESTAMP,
                    error_message TEXT,
                    CHECK(package_type IN ('DELTA', 'FULL', 'REPORT')),
                    CHECK(source_type IN ('STATION', 'HOSPITAL')),
                    CHECK(destination_type IN ('HOSPITAL', 'CENTRAL')),
                    CHECK(transfer_method IN ('NETWORK', 'USB', 'MANUAL', 'DRONE')),
                    CHECK(status IN ('PENDING', 'UPLOADED', 'PROCESSING', 'APPLIED', 'FAILED'))
                )
            """)

            # 醫院日報表(谷盺公司向中央回報用)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hospital_daily_reports (
                    report_id TEXT PRIMARY KEY,
                    hospital_id TEXT NOT NULL,
                    report_date DATE NOT NULL,
                    total_stations INTEGER NOT NULL,
                    operational_stations INTEGER NOT NULL,
                    offline_stations INTEGER NOT NULL,
                    total_patients_treated INTEGER DEFAULT 0,
                    critical_patients INTEGER DEFAULT 0,
                    surgeries_performed INTEGER DEFAULT 0,
                    blood_inventory_json TEXT,
                    critical_shortages_json TEXT,
                    equipment_status_json TEXT,
                    alerts_json TEXT,
                    submitted_by TEXT NOT NULL,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    received_by_central BOOLEAN DEFAULT FALSE,
                    received_at TIMESTAMP,
                    UNIQUE(hospital_id, report_date),
                    FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id)
                )
            """)

            # 聯邦架構索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_stations_hospital
                ON stations(hospital_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sync_packages_status
                ON sync_packages(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sync_packages_hospital
                ON sync_packages(hospital_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sync_packages_date
                ON sync_packages(created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_hospital_reports_date
                ON hospital_daily_reports(report_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_hospital_reports_hospital
                ON hospital_daily_reports(hospital_id)
            """)
            # ========== 聯邦式架構結束 ==========

            # v2.0: 載入站點資訊到資料庫
            self._init_hospitals_and_stations(cursor)

            # v2.0: 根據站點類型載入 Template 資料
            self._load_template_data(cursor)

            # 初始化血型庫存
            for blood_type in config.BLOOD_TYPES:
                cursor.execute("""
                    INSERT OR IGNORE INTO blood_inventory (blood_type, quantity, station_id)
                    VALUES (?, 0, ?)
                """, (blood_type, config.get_station_id()))

            # v1.5.1: 初始化麻醉模組 schema
            if ANESTHESIA_MODULE_AVAILABLE and init_anesthesia_schema:
                try:
                    init_anesthesia_schema(cursor)
                except Exception as e:
                    logger.warning(f"麻醉模組 schema 初始化失敗: {e}")

            conn.commit()
            logger.info(f"✓ 資料庫初始化完成: {config.get_station_id()}")

        except Exception as e:
            logger.error(f"資料庫初始化失敗: {e}")
            conn.rollback()
            raise
        finally:
            # Don't close in-memory connection (would destroy data)
            if not self.is_memory:
                conn.close()
    
    def _init_default_equipment(self, cursor):
        """初始化預設設備"""
        default_equipment = [
            ('power-1', '行動電源站', '電力設備'),
            ('photocatalyst-1', '光觸媒', '空氣淨化'),
            ('water-1', '淨水器', '水處理'),
            ('fridge-1', '行動冰箱', '冷藏設備')
        ]

        for eq_id, eq_name, eq_category in default_equipment:
            cursor.execute("""
                INSERT OR IGNORE INTO equipment (id, name, category, quantity, status)
                VALUES (?, ?, ?, 1, 'UNCHECKED')
            """, (eq_id, eq_name, eq_category))

    def _init_hospitals_and_stations(self, cursor):
        """初始化預設醫院和站點(聯邦架構) - v2.0"""
        # 建立預設醫院 HOSP-001
        cursor.execute("""
            INSERT OR IGNORE INTO hospitals (
                hospital_id, hospital_name, hospital_type, command_level,
                network_access, total_stations, operational_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            'HOSP-001',
            config.ORG_NAME,
            'FIELD_HOSPITAL',
            'LOCAL',
            'MILITARY',  # 醫院行政單位有軍警管道網路
            0,  # 初始值，後續會更新
            'ACTIVE'
        ))

        # v2.0: 建立當前站點(從 config 讀取)
        station_id = config.get_station_id()
        cursor.execute("""
            INSERT OR REPLACE INTO stations (
                station_id, station_name, hospital_id, station_type,
                network_access, operational_status, sync_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            station_id,
            config.get_station_name(),
            'HOSP-001',
            'SMALL',  # 預設為小站，可後續手動調整為 LARGE
            'NONE',   # 預設無網路
            'ACTIVE',
            'PENDING'
        ))

        # 更新醫院的站點總數
        cursor.execute("""
            UPDATE hospitals
            SET total_stations = (
                SELECT COUNT(*) FROM stations WHERE hospital_id = 'HOSP-001'
            )
            WHERE hospital_id = 'HOSP-001'
        """)

        logger.info(f"✓ 已初始化站點: {station_id} ({config.get_station_name()})")

    def _load_template_data(self, cursor):
        """v1.4.2-plus: 統一預載所有藥品/耗材/設備 (藥品使用 MED- 前綴整合到 items 表)"""
        try:
            from preload_data import get_all_items, EQUIPMENT_DATA

            # 檢查是否已有 MED- 開頭的藥品資料 (避免重複載入)
            cursor.execute("SELECT COUNT(*) FROM items WHERE item_code LIKE 'MED-%'")
            med_count = cursor.fetchone()[0]

            if med_count == 0:
                logger.info("首次執行，開始預載政府標準資料庫...")

                # 預載所有 items (藥品 + 耗材 + 試劑，藥品用 MED- 前綴，試劑用 REA- 前綴)
                all_items = get_all_items()
                for item in all_items:
                    # 試劑有額外欄位
                    if item['code'].startswith('REA-'):
                        cursor.execute("""
                            INSERT OR IGNORE INTO items
                            (item_code, item_name, category, unit, min_stock, endurance_type, tests_per_unit, valid_days_after_open)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (item['code'], item['name'], item['category'], item['unit'], item['min_stock'],
                              item.get('endurance_type'), item.get('tests_per_unit'), item.get('valid_days_after_open')))
                    else:
                        cursor.execute("""
                            INSERT OR IGNORE INTO items
                            (item_code, item_name, category, unit, min_stock)
                            VALUES (?, ?, ?, ?, ?)
                        """, (item['code'], item['name'], item['category'], item['unit'], item['min_stock']))

                # 統計藥品、耗材和試劑數量
                medicines = [i for i in all_items if i['code'].startswith('MED-')]
                reagents = [i for i in all_items if i['code'].startswith('REA-')]
                consumables = [i for i in all_items if not i['code'].startswith('MED-') and not i['code'].startswith('REA-')]
                logger.info(f"✓ 預載 {len(medicines)} 種藥品 (MED- 前綴)")
                logger.info(f"✓ 預載 {len(consumables)} 種耗材")
                logger.info(f"✓ 預載 {len(reagents)} 種試劑 (REA- 前綴)")

                # 預載設備 (v2.0 新增 type_code)
                for e in EQUIPMENT_DATA:
                    cursor.execute("""
                        INSERT OR IGNORE INTO equipment
                        (id, name, category, quantity, status, type_code)
                        VALUES (?, ?, ?, ?, 'UNCHECKED', ?)
                    """, (e['id'], e['name'], e['category'], e['quantity'], e.get('type_code', 'GENERAL')))

                logger.info(f"✓ 預載 {len(EQUIPMENT_DATA)} 種設備")
                logger.info("✓ 政府標準資料庫預載完成")
            else:
                logger.info(f"資料庫已存在 {med_count} 種藥品，跳過預載")

        except ImportError:
            logger.warning("preload_data.py 不存在，使用空白資料庫")
            self._init_default_equipment(cursor)
        except Exception as e:
            logger.warning(f"預載資料失敗: {e}")
            self._init_default_equipment(cursor)

    def generate_item_code(self, category: str) -> str:
        """根據分類自動生成物品代碼"""
        CATEGORY_PREFIXES = {
            '手術耗材': 'SURG',
            '急救物資': 'EMER',
            '藥品': 'MED',
            '防護用品': 'PPE',
            '醫療設備': 'EQUIP',
            '其他': 'OTHER'
        }
        
        prefix = CATEGORY_PREFIXES.get(category, 'OTHER')
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT item_code FROM items
                WHERE item_code LIKE ?
                ORDER BY item_code DESC
                LIMIT 1
            """, (f"{prefix}-%",))

            result = cursor.fetchone()

            if result:
                last_code = result['item_code']
                try:
                    last_number = int(last_code.split('-')[1])
                    new_number = last_number + 1
                except (IndexError, ValueError):
                    new_number = 1
            else:
                new_number = 1
            
            new_code = f"{prefix}-{new_number:03d}"
            logger.info(f"為分類 '{category}' 生成代碼: {new_code}")
            return new_code
            
        finally:
            conn.close()
    
    def generate_equipment_id(self, category: str) -> str:
        """根據分類自動生成設備ID"""
        CATEGORY_PREFIXES = {
            '電力設備': 'PWR',
            '空氣淨化': 'AIR',
            '水處理': 'WTR',
            '冷藏設備': 'COOL',
            '通訊設備': 'COMM',
            '照明設備': 'LIGHT',
            '其他': 'MISC'
        }
        
        prefix = CATEGORY_PREFIXES.get(category, 'MISC')
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id FROM equipment 
                WHERE id LIKE ? 
                ORDER BY id DESC 
                LIMIT 1
            """, (f"{prefix}-%",))
            
            result = cursor.fetchone()
            
            if result:
                last_id = result['id']
                try:
                    last_number = int(last_id.split('-')[1])
                    new_number = last_number + 1
                except (IndexError, ValueError):
                    new_number = 1
            else:
                new_number = 1
            
            new_id = f"{prefix}-{new_number:03d}"
            logger.info(f"為分類 '{category}' 生成設備ID: {new_id}")
            return new_id
            
        finally:
            conn.close()
    
    def generate_surgery_record_number(self, record_date: str, patient_name: str, sequence: int) -> str:
        """
        生成手術記錄編號
        格式: YYYYMMDD-PatientName-N
        例如: 20251104-王小明-1
        """
        date_str = record_date.replace('-', '')
        record_number = f"{date_str}-{patient_name}-{sequence}"
        return record_number
    
    def get_daily_surgery_sequence(self, record_date: str, station_id: str) -> int:
        """取得當日手術序號"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT MAX(surgery_sequence) as max_seq
                FROM surgery_records
                WHERE record_date = ? AND station_id = ?
            """, (record_date, station_id))
            
            result = cursor.fetchone()
            max_seq = result['max_seq'] if result['max_seq'] else 0
            return max_seq + 1
            
        finally:
            conn.close()
    
    def create_surgery_record(self, request: SurgeryRecordRequest) -> dict:
        """建立手術記錄"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 取得今天日期
            record_date = datetime.now().strftime('%Y-%m-%d')
            
            # 取得當日手術序號
            sequence = self.get_daily_surgery_sequence(record_date, request.stationId)
            
            # 生成記錄編號
            record_number = self.generate_surgery_record_number(
                record_date, 
                request.patientName, 
                sequence
            )
            
            # 插入手術記錄
            cursor.execute("""
                INSERT INTO surgery_records (
                    record_number, record_date, patient_name, cirs_person_id, surgery_sequence,
                    surgery_type, surgeon_name, anesthesia_type, duration_minutes,
                    remarks, station_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_number,
                record_date,
                request.patientName,
                request.cirsPersonId,  # CIRS Integration
                sequence,
                request.surgeryType,
                request.surgeonName,
                request.anesthesiaType,
                request.durationMinutes,
                request.remarks,
                request.stationId
            ))
            
            surgery_id = cursor.lastrowid
            
            # 插入耗材明細
            for item in request.consumptions:
                cursor.execute("""
                    INSERT INTO surgery_consumptions (
                        surgery_id, item_code, item_name, quantity, unit
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    surgery_id,
                    item.itemCode,
                    item.itemName,
                    item.quantity,
                    item.unit
                ))
                
                # 同時記錄庫存消耗
                cursor.execute("""
                    INSERT INTO inventory_events (
                        event_type, item_code, quantity, remarks, station_id
                    )
                    VALUES ('CONSUME', ?, ?, ?, ?)
                """, (
                    item.itemCode,
                    item.quantity,
                    f"手術使用 - {record_number}",
                    request.stationId
                ))
            
            conn.commit()
            logger.info(f"手術記錄建立成功: {record_number}")
            
            return {
                "success": True,
                "message": f"手術記錄 {record_number} 建立成功",
                "recordNumber": record_number,
                "surgeryId": surgery_id,
                "sequence": sequence
            }
        
        except Exception as e:
            conn.rollback()
            logger.error(f"建立手術記錄失敗: {e}")
            raise HTTPException(status_code=500, detail=f"建立手術記錄失敗: {str(e)}")
        finally:
            conn.close()
    
    def get_surgery_records(
        self, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        patient_name: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """查詢手術記錄"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 構建查詢條件
            where_clauses = []
            params = []
            
            if start_date:
                where_clauses.append("record_date >= ?")
                params.append(start_date)
            
            if end_date:
                where_clauses.append("record_date <= ?")
                params.append(end_date)
            
            if patient_name:
                where_clauses.append("patient_name LIKE ?")
                params.append(f"%{patient_name}%")
            
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            params.append(limit)
            
            # 查詢手術記錄 (v1.4.5更新：新增status和patient_outcome欄位)
            cursor.execute(f"""
                SELECT
                    id, record_number, record_date, patient_name, surgery_sequence,
                    surgery_type, surgeon_name, anesthesia_type, duration_minutes,
                    remarks, station_id, status, patient_outcome, archived_at, archived_by, created_at
                FROM surgery_records
                WHERE {where_sql}
                ORDER BY record_date DESC, surgery_sequence DESC
                LIMIT ?
            """, params)
            
            records = []
            for row in cursor.fetchall():
                record = dict(row)
                
                # 查詢耗材明細
                cursor.execute("""
                    SELECT item_code, item_name, quantity, unit
                    FROM surgery_consumptions
                    WHERE surgery_id = ?
                """, (record['id'],))
                
                record['consumptions'] = [dict(c) for c in cursor.fetchall()]
                records.append(record)
            
            return records
            
        finally:
            conn.close()
    
    def export_surgery_records_csv(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """匯出手術記錄為 CSV"""
        records = self.get_surgery_records(start_date, end_date, limit=10000)
        
        # 建立 CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 寫入標題
        writer.writerow([
            '記錄編號', '日期', '病患姓名', '當日第N台',
            '手術類型', '主刀醫師', '麻醉方式', '手術時長(分)',
            '耗材代碼', '耗材名稱', '數量', '單位',
            '備註', '建立時間'
        ])
        
        # 寫入資料
        for record in records:
            for consumption in record['consumptions']:
                writer.writerow([
                    record['record_number'],
                    record['record_date'],
                    record['patient_name'],
                    record['surgery_sequence'],
                    record['surgery_type'],
                    record['surgeon_name'],
                    record.get('anesthesia_type', ''),
                    record.get('duration_minutes', ''),
                    consumption['item_code'],
                    consumption['item_name'],
                    consumption['quantity'],
                    consumption['unit'],
                    record.get('remarks', ''),
                    record['created_at']
                ])
        
        return output.getvalue()

    # ========== 手術記錄封存功能 (v1.4.5新增) ==========

    def archive_surgery_record(self, record_number: str, patient_outcome: str, archived_by: str, notes: str = None) -> dict:
        """封存手術記錄"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 檢查記錄是否存在
            cursor.execute("""
                SELECT id, status, patient_name
                FROM surgery_records
                WHERE record_number = ?
            """, (record_number,))

            record = cursor.fetchone()
            if not record:
                raise HTTPException(status_code=404, detail=f"手術記錄 {record_number} 不存在")

            if record['status'] == 'ARCHIVED':
                raise HTTPException(status_code=400, detail="該記錄已封存，無法再次封存")

            # 更新記錄狀態
            cursor.execute("""
                UPDATE surgery_records
                SET status = 'ARCHIVED',
                    patient_outcome = ?,
                    archived_at = CURRENT_TIMESTAMP,
                    archived_by = ?,
                    remarks = CASE
                        WHEN remarks IS NULL OR remarks = '' THEN ?
                        ELSE remarks || ' | ' || ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE record_number = ?
            """, (patient_outcome, archived_by, notes or '', notes or '', record_number))

            conn.commit()
            logger.info(f"手術記錄已封存: {record_number} - {patient_outcome}")

            outcome_text = {
                'DISCHARGED': '康復出院',
                'TRANSFERRED': '轉院',
                'DECEASED': '死亡'
            }.get(patient_outcome, patient_outcome)

            return {
                "success": True,
                "record_number": record_number,
                "patient_name": record['patient_name'],
                "status": "ARCHIVED",
                "patient_outcome": patient_outcome,
                "outcome_text": outcome_text,
                "message": f"手術記錄已封存：病患{record['patient_name']} - {outcome_text}"
            }

        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"封存手術記錄失敗: {e}")
            raise HTTPException(status_code=500, detail=f"封存失敗: {str(e)}")
        finally:
            conn.close()

    def get_archived_records(self, outcome: str = None, limit: int = 50) -> List[Dict]:
        """查詢已封存的手術記錄"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            where_clauses = ["status = 'ARCHIVED'"]
            params = []

            if outcome:
                where_clauses.append("patient_outcome = ?")
                params.append(outcome)

            where_sql = " AND ".join(where_clauses)
            params.append(limit)

            cursor.execute(f"""
                SELECT
                    record_number, record_date, patient_name, surgery_type,
                    surgeon_name, status, patient_outcome, archived_at, archived_by, remarks
                FROM surgery_records
                WHERE {where_sql}
                ORDER BY archived_at DESC
                LIMIT ?
            """, params)

            return [dict(row) for row in cursor.fetchall()]

        finally:
            conn.close()

    # ========== 封存功能結束 ==========

    def get_stats(self, station_id: str = None) -> Dict[str, int]:
        """取得系統統計(支援站點過濾)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 品項總數(不需站點過濾，物品是共用的)
            cursor.execute("SELECT COUNT(*) as count FROM items")
            total_items = cursor.fetchone()['count']

            # 庫存警戒數(依站點過濾)
            # 短期方案：使用 INNER JOIN 只統計有進貨記錄的品項
            # v2.0 multi-station 將改為 LEFT JOIN + 自動初始化 + 設置精靈
            if station_id:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM (
                        SELECT
                            i.item_code,
                            i.min_stock,
                            stock.current_stock
                        FROM items i
                        INNER JOIN (
                            SELECT item_code,
                                   SUM(CASE WHEN event_type = 'RECEIVE' THEN quantity
                                            WHEN event_type = 'CONSUME' THEN -quantity
                                            ELSE 0 END) as current_stock
                            FROM inventory_events
                            WHERE station_id = ?
                            GROUP BY item_code
                        ) stock ON i.item_code = stock.item_code
                    ) t
                    WHERE t.current_stock < t.min_stock
                """, (station_id,))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM (
                        SELECT
                            i.item_code,
                            i.min_stock,
                            COALESCE(stock.current_stock, 0) as current_stock
                        FROM items i
                        LEFT JOIN (
                            SELECT item_code,
                                   SUM(CASE WHEN event_type = 'RECEIVE' THEN quantity
                                            WHEN event_type = 'CONSUME' THEN -quantity
                                            ELSE 0 END) as current_stock
                            FROM inventory_events
                            GROUP BY item_code
                        ) stock ON i.item_code = stock.item_code
                    ) t
                    WHERE t.current_stock < t.min_stock
                """)
            low_stock = cursor.fetchone()['count']

            # 全血總量(依站點過濾)
            if station_id:
                cursor.execute("SELECT SUM(quantity) as total FROM blood_inventory WHERE station_id = ?", (station_id,))
            else:
                cursor.execute("SELECT SUM(quantity) as total FROM blood_inventory")
            total_blood = cursor.fetchone()['total'] or 0

            # 設備警戒數(包含待檢查 + 警告 + 錯誤)
            # v1.4.5 單站版本：equipment 表無 station_id 欄位
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM equipment
                WHERE status IN ('UNCHECKED', 'WARNING', 'ERROR')
            """)
            equipment_alerts = cursor.fetchone()['count']

            return {
                "totalItems": total_items,
                "lowStockItems": low_stock,
                "totalBlood": total_blood,
                "equipmentAlerts": equipment_alerts
            }
        finally:
            conn.close()
    
    def receive_item(self, request: ReceiveRequest) -> dict:
        """進貨處理"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT item_name FROM items WHERE item_code = ?", (request.itemCode,))
            item = cursor.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail=f"物品代碼 {request.itemCode} 不存在")
            
            cursor.execute("""
                INSERT INTO inventory_events 
                (event_type, item_code, quantity, batch_number, expiry_date, remarks, station_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                'RECEIVE',
                request.itemCode,
                request.quantity,
                request.batchNumber,
                request.expiryDate,
                request.remarks,
                request.stationId
            ))
            
            conn.commit()
            logger.info(f"進貨記錄成功: {request.itemCode} +{request.quantity}")

            return {
                "success": True,
                "message": f"物品 {item['item_name']} 進貨 {request.quantity} 已記錄"
            }
        
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"進貨處理失敗: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()
    
    def consume_item(self, request: ConsumeRequest) -> dict:
        """消耗處理"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT item_name FROM items WHERE item_code = ?", (request.itemCode,))
            item = cursor.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail=f"物品代碼 {request.itemCode} 不存在")
            
            cursor.execute("""
                SELECT SUM(CASE WHEN event_type = 'RECEIVE' THEN quantity
                               WHEN event_type = 'CONSUME' THEN -quantity
                               ELSE 0 END) as current_stock
                FROM inventory_events
                WHERE item_code = ?
            """, (request.itemCode,))
            
            result = cursor.fetchone()
            current_stock = result['current_stock'] if result['current_stock'] else 0
            
            if current_stock < request.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"庫存不足: 目前庫存 {current_stock},需求 {request.quantity}"
                )
            
            cursor.execute("""
                INSERT INTO inventory_events 
                (event_type, item_code, quantity, remarks, station_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                'CONSUME',
                request.itemCode,
                request.quantity,
                request.purpose,
                request.stationId
            ))
            
            conn.commit()
            logger.info(f"消耗記錄成功: {request.itemCode} -{request.quantity}")

            return {
                "success": True,
                "message": f"物品 {item['item_name']} 消耗 {request.quantity} 已記錄"
            }
        
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"消耗處理失敗: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()
    
    def process_blood(self, action: str, request: BloodRequest) -> dict:
        """血袋處理(支援多站點) - v1.4.2-plus: 入庫時自動建立個別血袋追蹤"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT quantity FROM blood_inventory WHERE blood_type = ? AND station_id = ?",
                (request.bloodType, request.stationId)
            )
            blood = cursor.fetchone()

            created_bag_codes = []  # 記錄建立的血袋編號

            if action == 'receive':
                # 入庫：如果記錄不存在則新增
                if not blood:
                    new_quantity = request.quantity
                    cursor.execute("""
                        INSERT INTO blood_inventory (blood_type, quantity, station_id)
                        VALUES (?, ?, ?)
                    """, (request.bloodType, new_quantity, request.stationId))
                else:
                    current_quantity = blood['quantity']
                    new_quantity = current_quantity + request.quantity
                    cursor.execute("""
                        UPDATE blood_inventory
                        SET quantity = ?, last_updated = CURRENT_TIMESTAMP
                        WHERE blood_type = ? AND station_id = ?
                    """, (new_quantity, request.bloodType, request.stationId))
                event_type = 'RECEIVE'

                # v1.4.2-plus: 自動建立個別血袋追蹤記錄
                from datetime import datetime, timedelta
                import pytz
                tw_tz = pytz.timezone('Asia/Taipei')
                now = datetime.now(tw_tz)
                date_str = now.strftime("%y%m%d")
                tw_now_str = now.strftime('%Y-%m-%d %H:%M:%S')

                # 血型代碼映射
                blood_type_codes = {
                    'A+': 'AP', 'A-': 'AN', 'B+': 'BP', 'B-': 'BN',
                    'O+': 'OP', 'O-': 'ON', 'AB+': 'ABP', 'AB-': 'ABN'
                }
                bt_code = blood_type_codes.get(request.bloodType, request.bloodType.replace('+', 'P').replace('-', 'N'))

                # 取得當天已有的血袋數量來產生序號
                cursor.execute("""
                    SELECT COUNT(*) FROM blood_bags
                    WHERE bag_code LIKE ?
                """, (f"BB-{bt_code}-{date_str}-%",))
                existing_count = cursor.fetchone()[0]

                # 計算效期 (預設7天)
                expiry_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
                collection_date = now.strftime("%Y-%m-%d")

                # 為每袋血建立追蹤記錄
                for i in range(request.quantity):
                    seq = existing_count + i + 1
                    bag_code = f"BB-{bt_code}-{date_str}-{seq:03d}"

                    # 取得來源資訊 (如果有)
                    source_info = getattr(request, 'source', 'blood_center')
                    donor_info = ""
                    if source_info == 'walking_donor':
                        donor_name = getattr(request, 'donorName', '')
                        if donor_name:
                            donor_info = f"WBB: {donor_name}"

                    cursor.execute("""
                        INSERT INTO blood_bags
                        (bag_code, blood_type, volume_ml, collection_date, expiry_date, donor_info, status, created_at, station_id)
                        VALUES (?, ?, 250, ?, ?, ?, 'AVAILABLE', ?, ?)
                    """, (bag_code, request.bloodType, collection_date, expiry_date, donor_info, tw_now_str, request.stationId))

                    created_bag_codes.append(bag_code)

                logger.info(f"🩸 建立 {len(created_bag_codes)} 袋血袋追蹤: {created_bag_codes}")

            else:
                # 出庫：記錄必須存在且庫存足夠
                if not blood:
                    raise HTTPException(status_code=404, detail=f"站點 {request.stationId} 無此血型 {request.bloodType}")

                current_quantity = blood['quantity']
                if current_quantity < request.quantity:
                    raise HTTPException(
                        status_code=400,
                        detail=f"血袋庫存不足: 目前 {current_quantity}U,需求 {request.quantity}U"
                    )
                new_quantity = current_quantity - request.quantity
                cursor.execute("""
                    UPDATE blood_inventory
                    SET quantity = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE blood_type = ? AND station_id = ?
                """, (new_quantity, request.bloodType, request.stationId))
                event_type = 'CONSUME'

            # 記錄血袋事件 - 使用台灣時區
            if 'tw_now_str' not in dir():
                from datetime import datetime
                import pytz
                tw_tz = pytz.timezone('Asia/Taipei')
                tw_now_str = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

            # 入庫時記錄血袋編號
            remarks = ""
            if event_type == 'RECEIVE' and created_bag_codes:
                remarks = f"血袋: {', '.join(created_bag_codes)}"

            cursor.execute("""
                INSERT INTO blood_events
                (event_type, blood_type, quantity, station_id, remarks, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_type, request.bloodType, request.quantity, request.stationId, remarks, tw_now_str))

            conn.commit()
            logger.info(f"血袋{action}記錄成功: {request.bloodType} {'+' if action=='receive' else '-'}{request.quantity}U")

            action_text = "入庫" if action == "receive" else "出庫"
            result = {
                "success": True,
                "message": f"血袋 {request.bloodType} {action_text} {request.quantity}U 已記錄",
                "newQuantity": new_quantity
            }

            # 如果有建立血袋，回傳編號
            if created_bag_codes:
                result["bag_codes"] = created_bag_codes
                result["message"] += f" (已建立 {len(created_bag_codes)} 袋追蹤)"

            return result
        
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"血袋處理失敗: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()
    
    def get_blood_inventory(self, station_id: str = None) -> List[Dict]:
        """取得血袋庫存(支援多站點)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if station_id:
                # 查詢特定站點
                cursor.execute("""
                    SELECT blood_type, quantity, station_id, last_updated
                    FROM blood_inventory
                    WHERE station_id = ?
                    ORDER BY blood_type
                """, (station_id,))
            else:
                # 查詢所有站點
                cursor.execute("""
                    SELECT blood_type, quantity, station_id, last_updated
                    FROM blood_inventory
                    ORDER BY station_id, blood_type
                """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ========== 緊急血袋管理 (v1.4.5新增) ==========

    def generate_emergency_blood_code(self, blood_type: str, collection_date: str, org_code: str = "DNO") -> str:
        """生成緊急血袋編號 {ORG}-{YYMMDD}-{BLOOD_TYPE}-{SEQ}"""
        # 讀取血型代碼映射
        blood_type_codes = {
            "A+": "AP", "A-": "AN",
            "B+": "BP", "B-": "BN",
            "O+": "OP", "O-": "ON",
            "AB+": "ABP", "AB-": "ABN"
        }
        blood_code = blood_type_codes.get(blood_type, "XX")

        # 解析日期為YYMMDD格式
        from datetime import datetime
        date_obj = datetime.strptime(collection_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%y%m%d")

        # 查詢當天該血型的序號
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM emergency_blood_bags
                WHERE blood_type = ?
                AND collection_date = ?
            """, (blood_type, collection_date))
            count = cursor.fetchone()['count']
            seq = count + 1

            # 生成完整編號
            blood_bag_code = f"{org_code}-{date_str}-{blood_code}-{seq:03d}"
            return blood_bag_code
        finally:
            conn.close()

    def calculate_expiry_date(self, collection_date: str, product_type: str) -> str:
        """計算血袋效期"""
        from datetime import datetime, timedelta

        expiry_days = {
            "WHOLE_BLOOD": 35,
            "PLATELET": 5,
            "FROZEN_PLASMA": 365,
            "RBC_CONCENTRATE": 42
        }

        days = expiry_days.get(product_type, 35)
        collection = datetime.strptime(collection_date, "%Y-%m-%d")
        expiry = collection + timedelta(days=days)
        return expiry.strftime("%Y-%m-%d")

    def register_emergency_blood_bag(self, data: dict) -> dict:
        """登記緊急血袋"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 生成血袋編號
            blood_bag_code = self.generate_emergency_blood_code(
                data['blood_type'],
                data['collection_date'],
                data.get('org_code', 'DNO')
            )

            # 計算效期
            expiry_date = self.calculate_expiry_date(
                data['collection_date'],
                data['product_type']
            )

            # 插入記錄
            cursor.execute("""
                INSERT INTO emergency_blood_bags
                (blood_bag_code, blood_type, product_type, collection_date, expiry_date,
                 volume_ml, station_id, operator, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                blood_bag_code,
                data['blood_type'],
                data['product_type'],
                data['collection_date'],
                expiry_date,
                data.get('volume_ml', 250),
                data['station_id'],
                data['operator'],
                data.get('remarks', '')
            ))

            conn.commit()
            logger.info(f"緊急血袋登記成功: {blood_bag_code}")

            return {
                "success": True,
                "blood_bag_code": blood_bag_code,
                "expiry_date": expiry_date,
                "message": f"血袋 {blood_bag_code} 登記成功"
            }

        except Exception as e:
            conn.rollback()
            logger.error(f"緊急血袋登記失敗: {e}")
            raise HTTPException(status_code=500, detail=f"登記失敗: {str(e)}")
        finally:
            conn.close()

    def get_emergency_blood_bags(self, status: str = None) -> List[Dict]:
        """取得緊急血袋清單"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if status:
                cursor.execute("""
                    SELECT * FROM emergency_blood_bags
                    WHERE status = ?
                    ORDER BY collection_date DESC, blood_bag_code
                """, (status,))
            else:
                cursor.execute("""
                    SELECT * FROM emergency_blood_bags
                    ORDER BY collection_date DESC, blood_bag_code
                """)

            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def use_emergency_blood_bag(self, blood_bag_code: str, patient_name: str, operator: str) -> dict:
        """使用緊急血袋"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 檢查血袋是否存在且可用
            cursor.execute("""
                SELECT * FROM emergency_blood_bags
                WHERE blood_bag_code = ?
            """, (blood_bag_code,))

            bag = cursor.fetchone()
            if not bag:
                raise HTTPException(status_code=404, detail=f"血袋編號 {blood_bag_code} 不存在")

            if bag['status'] != 'AVAILABLE':
                raise HTTPException(status_code=400, detail=f"血袋狀態為 {bag['status']}，無法使用")

            # 更新血袋狀態
            cursor.execute("""
                UPDATE emergency_blood_bags
                SET status = 'USED',
                    patient_name = ?,
                    usage_timestamp = CURRENT_TIMESTAMP
                WHERE blood_bag_code = ?
            """, (patient_name, blood_bag_code))

            conn.commit()
            logger.info(f"緊急血袋使用記錄: {blood_bag_code} -> {patient_name}")

            return {
                "success": True,
                "message": f"血袋 {blood_bag_code} 已用於病患 {patient_name}"
            }

        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"血袋使用記錄失敗: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()

    # ========== 緊急血袋管理結束 ==========

    def check_equipment(self, equipment_id: str, request: EquipmentCheckRequest) -> dict:
        """設備檢查"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT name FROM equipment WHERE id = ?", (equipment_id,))
            equipment = cursor.fetchone()
            if not equipment:
                raise HTTPException(status_code=404, detail=f"設備ID {equipment_id} 不存在")
            
            cursor.execute("""
                UPDATE equipment 
                SET status = ?,
                    last_check = CURRENT_TIMESTAMP,
                    power_level = ?,
                    remarks = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (request.status, request.powerLevel, request.remarks, equipment_id))
            
            cursor.execute("""
                INSERT INTO equipment_checks 
                (equipment_id, status, power_level, remarks, station_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                equipment_id,
                request.status,
                request.powerLevel,
                request.remarks,
                request.stationId
            ))
            
            conn.commit()
            logger.info(f"設備檢查記錄成功: {equipment_id} - {request.status}")
            
            return {
                "success": True,
                "message": f"設備 {equipment['name']} 檢查完成",
                "status": request.status
            }
        
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"設備檢查失敗: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()

    def reset_equipment_daily(self) -> int:
        """每日重置設備狀態(清空備註、電力、重置為UNCHECKED)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE equipment
                SET status = 'UNCHECKED',
                    remarks = NULL,
                    power_level = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status != 'UNCHECKED'
            """)

            affected_rows = cursor.rowcount
            conn.commit()

            if affected_rows > 0:
                logger.info(f"設備每日重置完成: {affected_rows} 個設備已重置")

            return affected_rows

        except Exception as e:
            conn.rollback()
            logger.error(f"設備每日重置失敗: {e}")
            return 0
        finally:
            conn.close()

    def get_equipment_status(self, station_id: str = None) -> List[Dict[str, Any]]:
        """取得所有設備狀態 (v2.0 新增 type_code 與韌性相關欄位)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # v2.0: 使用 v_equipment_status 視圖取得設備狀態 (含 type_code 與韌性分類)
            cursor.execute("""
                SELECT
                    v.id, v.name, v.type_code, v.type_name, v.category,
                    v.resilience_category, v.unit_count, v.avg_level,
                    v.checked_count, v.last_check, v.check_status,
                    e.quantity, e.status, e.power_level, e.remarks
                FROM v_equipment_status v
                LEFT JOIN equipment e ON v.id = e.id
                ORDER BY v.resilience_category DESC NULLS LAST, v.category, v.name
            """)

            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            # 降級到舊版查詢 (如果 view 不存在)
            logger.warning(f"v_equipment_status 視圖查詢失敗，使用降級查詢: {e}")
            cursor.execute("""
                SELECT
                    id, name, category, quantity, status,
                    last_check, power_level, remarks, type_code
                FROM equipment
                ORDER BY name
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_inventory_items(self) -> List[Dict]:
        """取得所有物品及庫存"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    i.item_code as code, i.item_name as name, i.unit, i.min_stock, i.category,
                    COALESCE(stock.current_stock, 0) as current_stock
                FROM items i
                LEFT JOIN (
                    SELECT item_code,
                           SUM(CASE WHEN event_type = 'RECEIVE' THEN quantity
                                    WHEN event_type = 'CONSUME' THEN -quantity
                                    ELSE 0 END) as current_stock
                    FROM inventory_events
                    GROUP BY item_code
                ) stock ON i.item_code = stock.item_code
                ORDER BY i.category, i.item_name
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_inventory_events(
        self,
        event_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        item_code: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """查詢庫存事件記錄"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            where_clauses = []
            params = []

            if event_type:
                where_clauses.append("e.event_type = ?")
                params.append(event_type)

            if start_date:
                where_clauses.append("DATE(e.timestamp) >= ?")
                params.append(start_date)

            if end_date:
                where_clauses.append("DATE(e.timestamp) <= ?")
                params.append(end_date)

            if item_code:
                where_clauses.append("e.item_code LIKE ?")
                params.append(f"%{item_code}%")

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            params.append(limit)

            cursor.execute(f"""
                SELECT
                    e.id, e.event_type, e.item_code, i.item_name,
                    e.quantity, i.unit, e.batch_number, e.expiry_date,
                    e.remarks, e.station_id, e.operator, e.timestamp
                FROM inventory_events e
                LEFT JOIN items i ON e.item_code = i.item_code
                WHERE {where_sql}
                ORDER BY e.timestamp DESC
                LIMIT ?
            """, params)

            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def export_inventory_csv(self) -> str:
        """匯出庫存資料為 CSV"""
        items = self.get_inventory_items()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            '物品代碼', '物品名稱', '分類', '單位',
            '當前庫存', '最小庫存', '庫存狀態'
        ])

        for item in items:
            status = '正常' if item['current_stock'] >= item['min_stock'] else '警戒'
            writer.writerow([
                item['code'],
                item['name'],
                item['category'],
                item['unit'],
                item['current_stock'],
                item['min_stock'],
                status
            ])

        return output.getvalue()

    def export_inventory_events_csv(
        self,
        event_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """匯出庫存事件記錄為 CSV"""
        events = self.get_inventory_events(event_type, start_date, end_date, limit=10000)

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            '事件ID', '事件類型', '物品代碼', '物品名稱', '數量', '單位',
            '批號', '效期', '備註', '站點', '操作員', '時間'
        ])

        for event in events:
            event_type_text = '進貨' if event['event_type'] == 'RECEIVE' else '消耗'
            writer.writerow([
                event['id'],
                event_type_text,
                event['item_code'],
                event['item_name'],
                event['quantity'],
                event['unit'],
                event.get('batch_number', ''),
                event.get('expiry_date', ''),
                event.get('remarks', ''),
                event['station_id'],
                event['operator'],
                event['timestamp']
            ])

        return output.getvalue()

    # ========== 聯邦架構 - 同步封包方法 (Phase 1) ==========

    def generate_sync_package(self, station_id: str, hospital_id: str, sync_type: str = "DELTA", since_timestamp: str = None) -> dict:
        """產生同步封包"""
        import hashlib
        import json
        from datetime import datetime

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 產生封包ID
            now = datetime.now()
            package_id = f"PKG-{now.strftime('%Y%m%d-%H%M%S')}-{station_id}"

            # 收集變更記錄
            changes = []

            if sync_type == "DELTA" and since_timestamp:
                # 增量同步：收集自 since_timestamp 以來的變更
                tables_to_sync = {
                    'inventory_events': 'timestamp',
                    'blood_events': 'timestamp',
                    'equipment_checks': 'timestamp',
                    'surgery_records': 'created_at',
                    'emergency_blood_bags': 'created_at'
                }

                for table, timestamp_col in tables_to_sync.items():
                    try:
                        cursor.execute(f"""
                            SELECT * FROM {table}
                            WHERE station_id = ? AND {timestamp_col} > ?
                            ORDER BY {timestamp_col}
                        """, (station_id, since_timestamp))

                        rows = cursor.fetchall()
                        logger.info(f"查詢表 {table}: 找到 {len(rows)} 筆變更記錄")

                        for idx, row in enumerate(rows):
                            try:
                                row_dict = dict(row)
                                change_dict = {
                                    'table': table,
                                    'operation': 'INSERT',
                                    'data': row_dict,
                                    'timestamp': row[timestamp_col]
                                }
                                changes.append(change_dict)
                            except Exception as e:
                                logger.error(f"無法序列化記錄 {table}[{idx}]: {str(e)}")
                                logger.error(f"Record type: {type(row)}")
                                logger.error(f"Record keys: {row.keys() if hasattr(row, 'keys') else 'N/A'}")
                                raise
                    except Exception as e:
                        logger.error(f"查詢表 {table} 失敗: {str(e)}")
                        raise

            else:
                # 全量同步：收集所有資料
                logger.info(f"開始全量同步: station_id={station_id}")

                # 定義需要同步的表及其時間戳欄位
                full_sync_tables = [
                    ('items', None, 'updated_at'),  # (table, filter_col, timestamp_col)
                    ('inventory_events', 'station_id', 'timestamp'),
                    ('blood_events', 'station_id', 'timestamp'),
                    ('equipment_checks', 'station_id', 'timestamp'),
                    ('surgery_records', 'station_id', 'created_at'),
                ]

                for table, filter_col, timestamp_col in full_sync_tables:
                    try:
                        # 建立查詢
                        if filter_col:
                            query = f"SELECT * FROM {table} WHERE {filter_col} = ?"
                            cursor.execute(query, (station_id,))
                        else:
                            query = f"SELECT * FROM {table}"
                            cursor.execute(query)

                        rows = cursor.fetchall()
                        logger.info(f"查詢表 {table}: 找到 {len(rows)} 筆記錄")

                        for idx, row in enumerate(rows):
                            try:
                                row_dict = dict(row)
                                # 獲取時間戳
                                timestamp = row[timestamp_col] if timestamp_col in row.keys() else now.isoformat()

                                change_dict = {
                                    'table': table,
                                    'operation': 'INSERT',
                                    'data': row_dict,
                                    'timestamp': timestamp
                                }
                                changes.append(change_dict)
                            except Exception as e:
                                logger.error(f"無法序列化記錄 {table}[{idx}]: {str(e)}")
                                logger.error(f"Record type: {type(row)}")
                                logger.error(f"Record keys: {row.keys() if hasattr(row, 'keys') else 'N/A'}")
                                raise
                    except Exception as e:
                        logger.error(f"查詢表 {table} 失敗: {str(e)}")
                        raise

            # 計算校驗碼
            logger.info(f"成功收集 {len(changes)} 筆變更記錄")

            try:
                logger.debug("開始 JSON 序列化...")
                package_content = json.dumps(changes, ensure_ascii=False, sort_keys=True)
                logger.info(f"JSON 序列化成功，封包大小: {len(package_content)} bytes")
            except TypeError as e:
                logger.error(f"JSON 序列化失敗: {str(e)}")
                logger.error(f"Changes count: {len(changes)}")
                # 找出無法序列化的變更
                for idx, change in enumerate(changes):
                    try:
                        json.dumps(change)
                    except TypeError:
                        logger.error(f"無法序列化的變更 [{idx}]: table={change.get('table')}, data_type={type(change.get('data'))}")
                raise

            checksum = hashlib.sha256(package_content.encode('utf-8')).hexdigest()
            package_size = len(package_content.encode('utf-8'))
            logger.debug(f"校驗碼: {checksum}")

            # 記錄封包到資料庫
            try:
                cursor.execute("""
                    INSERT INTO sync_packages (
                        package_id, package_type, source_type, source_id,
                        destination_type, destination_id, hospital_id,
                        transfer_method, package_size, checksum, changes_count, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    package_id, sync_type, 'STATION', station_id,
                    'HOSPITAL', hospital_id, hospital_id,
                    'MANUAL', package_size, checksum, len(changes), 'PENDING'  # transfer_method 改為 'MANUAL'
                ))
                logger.info(f"封包記錄已保存到資料庫: {package_id}")
            except Exception as e:
                logger.error(f"保存封包記錄失敗: {str(e)}")
                raise

            conn.commit()

            logger.info(f"同步封包產生完成: {package_id} ({len(changes)} 項變更, {package_size} bytes)")

            return {
                "success": True,
                "package_id": package_id,
                "package_type": sync_type,
                "package_size": package_size,
                "checksum": checksum,
                "changes_count": len(changes),
                "changes": changes,
                "message": f"同步封包已產生，包含 {len(changes)} 項變更"
            }

        except Exception as e:
            conn.rollback()
            logger.error(f"產生同步封包失敗: {e}")
            raise
        finally:
            conn.close()

    def import_sync_package(self, package_id: str, changes: List[dict], checksum: str, package_type: str = "FULL") -> dict:
        """匯入同步封包"""
        import hashlib
        import json

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 驗證校驗碼
            package_content = json.dumps(changes, ensure_ascii=False, sort_keys=True)
            calculated_checksum = hashlib.sha256(package_content.encode('utf-8')).hexdigest()

            if calculated_checksum != checksum:
                return {
                    "success": False,
                    "error": "校驗碼不符，封包可能已損毀",
                    "expected": checksum,
                    "actual": calculated_checksum
                }

            # 套用變更
            changes_applied = 0
            conflicts = []

            for change in changes:
                table = change['table']
                operation = change['operation']
                data = change['data']

                try:
                    if operation == 'INSERT':
                        # 建立 INSERT 語句
                        columns = ', '.join(data.keys())
                        placeholders = ', '.join(['?' for _ in data.keys()])
                        query = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"
                        cursor.execute(query, list(data.values()))
                        changes_applied += 1

                    elif operation == 'UPDATE':
                        # 建立 UPDATE 語句(暫時簡化實作)
                        set_clause = ', '.join([f"{k} = ?" for k in data.keys() if k != 'id'])
                        query = f"UPDATE {table} SET {set_clause} WHERE id = ?"
                        values = [v for k, v in data.items() if k != 'id'] + [data.get('id')]
                        cursor.execute(query, values)
                        changes_applied += 1

                    elif operation == 'DELETE':
                        # 建立 DELETE 語句
                        cursor.execute(f"DELETE FROM {table} WHERE id = ?", (data.get('id'),))
                        changes_applied += 1

                except Exception as e:
                    conflicts.append({
                        'table': table,
                        'operation': operation,
                        'error': str(e),
                        'data': data
                    })
                    logger.warning(f"套用變更失敗: {table} - {e}")

            # 記錄封包處理狀態
            cursor.execute("""
                INSERT OR REPLACE INTO sync_packages (
                    package_id, package_type, source_type, source_id,
                    destination_type, destination_id, hospital_id,
                    transfer_method, checksum, changes_count, status, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                package_id, package_type, 'STATION', 'UNKNOWN',
                'HOSPITAL', 'LOCAL', 'HOSP-001',
                'USB', checksum, len(changes), 'APPLIED'
            ))

            conn.commit()

            return {
                "success": True,
                "package_id": package_id,
                "changes_applied": changes_applied,
                "conflicts_detected": len(conflicts),
                "conflicts": conflicts,
                "message": f"同步完成，已套用 {changes_applied} 項變更"
            }

        except Exception as e:
            conn.rollback()
            logger.error(f"匯入同步封包失敗: {e}")
            raise
        finally:
            conn.close()

    def upload_sync_package(self, station_id: str, package_id: str, changes: List[dict], checksum: str, package_type: str = "FULL") -> dict:
        """醫院層接收站點同步上傳"""
        import hashlib
        import json

        # 驗證校驗碼
        package_content = json.dumps(changes, ensure_ascii=False, sort_keys=True)
        calculated_checksum = hashlib.sha256(package_content.encode('utf-8')).hexdigest()

        if calculated_checksum != checksum:
            return {
                "success": False,
                "error": "校驗碼不符",
                "expected": checksum,
                "actual": calculated_checksum
            }

        # 匯入變更(複用 import_sync_package 邏輯)
        result = self.import_sync_package(package_id, changes, checksum, package_type)

        if result['success']:
            # 更新站點同步狀態
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE stations
                    SET last_sync_at = CURRENT_TIMESTAMP,
                        sync_status = 'SYNCED'
                    WHERE station_id = ?
                """, (station_id,))
                conn.commit()
            except Exception as e:
                logger.warning(f"更新站點同步狀態失敗: {e}")
            finally:
                conn.close()

        return {
            **result,
            "station_id": station_id,
            "response_package_id": f"PKG-RESPONSE-{package_id}"
        }


# ============================================================================
# FastAPI 應用
# ============================================================================

app = FastAPI(
    title="醫療站庫存管理系統 API",
    version=config.VERSION,
    description="醫療站物資、血袋、設備、手術記錄管理系統"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# First-Run Detection & Setup Wizard Routes
# ============================================================================

from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    """
    首頁路由 - 檢查是否需要執行設定精靈

    如果資料庫未初始化，重新導向至 setup_wizard.html
    否則重新導向至 Index.html

    Vercel 模式下，直接返回 Index.html (已預載展示資料)
    """
    # On Vercel, always serve Index.html directly (demo data is pre-seeded)
    if IS_VERCEL:
        try:
            with open(PROJECT_ROOT / "Index.html", "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        except FileNotFoundError:
            return {"error": "Index.html not found", "mode": "vercel_demo"}

    try:
        db_path = PROJECT_ROOT / "medical_inventory.db"

        # Check if database exists and has data
        needs_setup = True
        if db_path.exists():
            try:
                conn = db.get_connection()
                cursor = conn.cursor()

                # Check if any core table has data
                cursor.execute("SELECT COUNT(*) FROM items")
                item_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM medicines")
                med_count = cursor.fetchone()[0]

                conn.close()

                # If database has data, no setup needed
                if item_count > 0 or med_count > 0:
                    needs_setup = False
            except:
                needs_setup = True

        if needs_setup:
            logger.info("首次啟動，重新導向至設定精靈")
            return RedirectResponse(url="/setup_wizard.html")
        else:
            return RedirectResponse(url="/Index.html")

    except Exception as e:
        logger.error(f"首頁路由錯誤: {e}")
        # On error, redirect to Index.html anyway
        return RedirectResponse(url="/Index.html")


@app.get("/setup")
async def manual_setup():
    """
    手動進入設定精靈 - 用於重新配置或變更任務類型
    """
    return RedirectResponse(url="/setup_wizard.html")


@app.get("/setup_wizard.html")
async def serve_setup_wizard():
    """Serve setup wizard HTML file"""
    wizard_file = PROJECT_ROOT / "setup_wizard.html"
    if wizard_file.exists():
        return FileResponse(wizard_file)
    else:
        raise HTTPException(status_code=404, detail="Setup wizard not found")


@app.get("/Index.html")
async def serve_index():
    """Serve main Index.html file"""
    index_file = PROJECT_ROOT / "Index.html"
    if index_file.exists():
        return FileResponse(index_file)
    else:
        raise HTTPException(status_code=404, detail="Index.html not found")


@app.get("/test_data.html")
async def serve_test_data():
    """Serve test data HTML file for API debugging"""
    test_file = PROJECT_ROOT / "test_data.html"
    if test_file.exists():
        return FileResponse(test_file)
    else:
        raise HTTPException(status_code=404, detail="test_data.html not found")


@app.get("/init_borp_station.html")
async def serve_init_borp():
    """Serve BORP station initialization HTML"""
    init_file = PROJECT_ROOT / "init_borp_station.html"
    if init_file.exists():
        return FileResponse(init_file)
    else:
        raise HTTPException(status_code=404, detail="init_borp_station.html not found")


@app.get("/debug.html")
async def serve_debug():
    """
    Serve debug HTML for Alpine.js and API testing
    """
    debug_file = PROJECT_ROOT / "debug.html"
    if debug_file.exists():
        return FileResponse(debug_file)
    else:
        raise HTTPException(status_code=404, detail="debug.html not found")


@app.get("/mobile")
@app.get("/mobile/")
async def serve_mobile_pwa():
    """
    Serve MIRS Mobile PWA (巡房助手)
    """
    mobile_file = PROJECT_ROOT / "static" / "mobile" / "index.html"
    if mobile_file.exists():
        return FileResponse(
            mobile_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    else:
        raise HTTPException(status_code=404, detail="Mobile PWA not found")


@app.get("/mobile/manifest.json")
async def serve_mobile_manifest():
    """Serve PWA manifest"""
    manifest_file = PROJECT_ROOT / "static" / "mobile" / "manifest.json"
    if manifest_file.exists():
        return FileResponse(manifest_file, media_type="application/manifest+json")
    raise HTTPException(status_code=404)


@app.get("/mobile/icons/{filename}")
async def serve_mobile_icon(filename: str):
    """Serve PWA icons"""
    icon_file = PROJECT_ROOT / "static" / "mobile" / "icons" / filename
    if icon_file.exists() and icon_file.suffix in ['.png', '.svg', '.ico']:
        media_type = "image/png" if filename.endswith('.png') else "image/svg+xml"
        return FileResponse(icon_file, media_type=media_type)
    raise HTTPException(status_code=404)


# ============================================================================
# v1.5.1: Anesthesia PWA Routes (麻醉站)
# ============================================================================

@app.get("/anesthesia")
@app.get("/anesthesia/")
async def serve_anesthesia_pwa():
    """
    Serve MIRS Anesthesia PWA (麻醉站)
    """
    anes_file = PROJECT_ROOT / "frontend" / "anesthesia" / "index.html"
    if anes_file.exists():
        return FileResponse(
            anes_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    else:
        raise HTTPException(status_code=404, detail="Anesthesia PWA not found")


@app.get("/anesthesia/manifest.json")
async def serve_anesthesia_manifest():
    """Serve Anesthesia PWA manifest"""
    manifest_file = PROJECT_ROOT / "frontend" / "anesthesia" / "manifest.json"
    if manifest_file.exists():
        return FileResponse(manifest_file, media_type="application/manifest+json")
    raise HTTPException(status_code=404)


@app.get("/anesthesia/icons/{filename}")
async def serve_anesthesia_icon(filename: str):
    """Serve Anesthesia PWA icons"""
    icon_file = PROJECT_ROOT / "frontend" / "anesthesia" / "icons" / filename
    if icon_file.exists() and icon_file.suffix in ['.png', '.svg', '.ico']:
        media_type = "image/png" if filename.endswith('.png') else "image/svg+xml"
        return FileResponse(icon_file, media_type=media_type)
    # Fallback to mobile icons if anesthesia-specific ones don't exist
    fallback = PROJECT_ROOT / "static" / "mobile" / "icons" / filename
    if fallback.exists() and fallback.suffix in ['.png', '.svg', '.ico']:
        media_type = "image/png" if filename.endswith('.png') else "image/svg+xml"
        return FileResponse(fallback, media_type=media_type)
    raise HTTPException(status_code=404)


# 掛載靜態文件(Logo圖片等)
# Mount static files with pathlib for cross-platform path safety
_static_dir = PROJECT_ROOT / "static"
if _static_dir.exists() and not IS_VERCEL:
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ============================================================================
# 資料庫初始化 - 支援 PostgreSQL (Neon) 或 SQLite
# ============================================================================
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = DATABASE_URL is not None and IS_VERCEL

if USE_POSTGRES:
    # 使用 PostgreSQL (Neon)
    try:
        from db_postgres import PostgresDatabaseManager
        db = PostgresDatabaseManager(DATABASE_URL)
        logger.info("✓ [MIRS] Using PostgreSQL (Neon) database")
    except Exception as e:
        logger.error(f"PostgreSQL initialization failed: {e}, falling back to SQLite")
        db = DatabaseManager(config.DATABASE_PATH)
        USE_POSTGRES = False
else:
    # 使用 SQLite
    db = DatabaseManager(config.DATABASE_PATH)

# Vercel: 如果使用 SQLite (in-memory)，初始化 demo 資料
if IS_VERCEL and not USE_POSTGRES:
    from seeder_demo import seed_mirs_demo
    _conn = db.get_connection()
    seed_mirs_demo(_conn)
    logger.info("✓ [MIRS] Demo mode initialized with SQLite (module load)")
elif IS_VERCEL and USE_POSTGRES:
    logger.info("✓ [MIRS] Using Neon PostgreSQL - data persisted")


# ========== 背景任務：每日設備重置 (v1.4.5) ==========

async def daily_equipment_reset():
    """每日07:00重置設備狀態"""
    while True:
        try:
            now = datetime.now()
            target_time = datetime.combine(now.date(), time(7, 0))

            # 如果已經過了今天的07:00，設定為明天的07:00
            if now >= target_time:
                target_time += timedelta(days=1)

            # 計算到下次執行的秒數
            wait_seconds = (target_time - now).total_seconds()
            logger.info(f"下次設備重置時間: {target_time.strftime('%Y-%m-%d %H:%M:%S')} (等待 {wait_seconds/3600:.1f} 小時)")

            # 等待到目標時間
            await asyncio.sleep(wait_seconds)

            # 執行重置
            affected = db.reset_equipment_daily()
            logger.info(f"✓ 設備每日重置已執行 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}): {affected} 個設備已重置")

        except Exception as e:
            logger.error(f"設備每日重置任務錯誤: {e}")
            # 發生錯誤時等待1小時後重試
            await asyncio.sleep(3600)


def run_migrations():
    """執行資料庫遷移 - 確保 schema 更新"""
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        # v2.5.2: 確保 items 表有韌性計算相關欄位
        cursor.execute("PRAGMA table_info(items)")
        item_columns = [col[1] for col in cursor.fetchall()]
        if item_columns:
            # 試劑欄位
            if 'endurance_type' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN endurance_type TEXT")
                logger.info("✓ Migration: 新增 items.endurance_type 欄位")
            if 'tests_per_unit' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN tests_per_unit INTEGER")
                logger.info("✓ Migration: 新增 items.tests_per_unit 欄位")
            if 'valid_days_after_open' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN valid_days_after_open INTEGER")
                logger.info("✓ Migration: 新增 items.valid_days_after_open 欄位")
            # 韌性容量欄位
            if 'capacity_per_unit' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN capacity_per_unit REAL")
                logger.info("✓ Migration: 新增 items.capacity_per_unit 欄位")
            if 'capacity_unit' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN capacity_unit TEXT")
                logger.info("✓ Migration: 新增 items.capacity_unit 欄位")
            # 依賴關係欄位
            if 'depends_on_item_code' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN depends_on_item_code TEXT")
                logger.info("✓ Migration: 新增 items.depends_on_item_code 欄位")
            if 'dependency_note' not in item_columns:
                cursor.execute("ALTER TABLE items ADD COLUMN dependency_note TEXT")
                logger.info("✓ Migration: 新增 items.dependency_note 欄位")

        # v2.5.2: 確保 resilience_config 表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='resilience_config'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE resilience_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id TEXT NOT NULL UNIQUE,
                    isolation_target_days REAL DEFAULT 3,
                    isolation_source TEXT DEFAULT 'manual',
                    population_count INTEGER DEFAULT 2,
                    population_label TEXT DEFAULT '插管患者數',
                    oxygen_profile_id INTEGER,
                    power_profile_id INTEGER,
                    reagent_profile_id INTEGER,
                    threshold_safe REAL DEFAULT 1.2,
                    threshold_warning REAL DEFAULT 1.0,
                    oxygen_consumption_rate REAL DEFAULT 10.0,
                    fuel_consumption_rate REAL DEFAULT 3.0,
                    power_consumption_watts REAL DEFAULT 500.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT
                )
            """)
            logger.info("✓ Migration: 建立 resilience_config 表")

        # v2.5.2: 確保 resilience_profiles 表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='resilience_profiles'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE resilience_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id TEXT NOT NULL,
                    endurance_type TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    profile_name_en TEXT,
                    burn_rate REAL NOT NULL,
                    burn_rate_unit TEXT NOT NULL,
                    population_multiplier INTEGER DEFAULT 0,
                    description TEXT,
                    is_default INTEGER DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✓ Migration: 建立 resilience_profiles 表")

        # v2.5.2: 確保 reagent_open_records 表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reagent_open_records'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE reagent_open_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_code TEXT NOT NULL,
                    batch_number TEXT,
                    station_id TEXT NOT NULL,
                    opened_at DATETIME NOT NULL,
                    tests_remaining INTEGER,
                    expiry_date DATE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✓ Migration: 建立 reagent_open_records 表")

        # Phase 4.3: 確保 equipment_check_history 有 unit_id 欄位
        cursor.execute("PRAGMA table_info(equipment_check_history)")
        columns = [col[1] for col in cursor.fetchall()]
        if columns and 'unit_id' not in columns:
            cursor.execute("ALTER TABLE equipment_check_history ADD COLUMN unit_id INTEGER")
            logger.info("✓ Migration: 新增 equipment_check_history.unit_id 欄位")

        # v2: 確保 equipment_types 表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipment_types'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE equipment_types (
                    type_code TEXT PRIMARY KEY,
                    type_name TEXT NOT NULL,
                    category TEXT,
                    resilience_category TEXT,
                    tracking_mode TEXT DEFAULT 'PER_UNIT',
                    capacity_config TEXT,
                    unit_prefix TEXT,
                    label_template TEXT,
                    icon TEXT,
                    color TEXT DEFAULT 'gray',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.executemany("""
                INSERT OR IGNORE INTO equipment_types (type_code, type_name, category, resilience_category, capacity_config, unit_prefix, label_template) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                ('POWER_STATION', '行動電源站', '電力設備', 'POWER', '{"strategy":"LINEAR","hours_per_100pct":8,"base_capacity_wh":2000}', 'PS', '電源站{n}號'),
                ('GENERATOR', '發電機', '電力設備', 'POWER', '{"strategy":"FUEL_BASED","tank_liters":20,"fuel_rate_lph":2}', 'GEN', '發電機{n}號'),
                ('O2_CYLINDER_H', 'H型氧氣鋼瓶', '呼吸設備', 'OXYGEN', '{"strategy":"LINEAR","hours_per_100pct":8,"capacity_liters":7000}', 'H-CYL', 'H型{n}號'),
                ('O2_CYLINDER_E', 'E型氧氣鋼瓶', '呼吸設備', 'OXYGEN', '{"strategy":"LINEAR","hours_per_100pct":2,"capacity_liters":680}', 'E-CYL', 'E型{n}號'),
                ('O2_CONCENTRATOR', '氧氣濃縮機', '呼吸設備', 'OXYGEN', '{"strategy":"POWER_DEPENDENT","output_lpm":5,"requires_power":true}', 'O2C', '濃縮機{n}號'),
                ('GENERAL', '一般設備', '一般設備', None, '{"strategy":"NONE"}', 'UNIT', '單位{n}號'),
                ('MONITOR', '監視器', '監控設備', None, '{"strategy":"NONE"}', 'MON', '監視器{n}號'),
                ('VENTILATOR', '呼吸器', '呼吸設備', None, '{"strategy":"NONE"}', 'VENT', '呼吸器{n}號'),
            ])
            logger.info("✓ Migration: 建立 equipment_types 表")

        # v2.1: 確保 equipment_types 有 unit_prefix 和 label_template 欄位
        cursor.execute("PRAGMA table_info(equipment_types)")
        et_columns = [col[1] for col in cursor.fetchall()]
        if et_columns and 'unit_prefix' not in et_columns:
            cursor.execute("ALTER TABLE equipment_types ADD COLUMN unit_prefix TEXT")
            cursor.execute("ALTER TABLE equipment_types ADD COLUMN label_template TEXT")
            # 更新現有資料
            prefix_data = [
                ('O2_CYLINDER_H', 'H-CYL', 'H型{n}號'),
                ('O2_CYLINDER_E', 'E-CYL', 'E型{n}號'),
                ('POWER_STATION', 'PS', '電源站{n}號'),
                ('GENERATOR', 'GEN', '發電機{n}號'),
                ('O2_CONCENTRATOR', 'O2C', '濃縮機{n}號'),
                ('VENTILATOR', 'VENT', '呼吸器{n}號'),
                ('MONITOR', 'MON', '監視器{n}號'),
                ('GENERAL', 'UNIT', '單位{n}號'),
            ]
            for type_code, prefix, template in prefix_data:
                cursor.execute(
                    "UPDATE equipment_types SET unit_prefix = ?, label_template = ? WHERE type_code = ?",
                    (prefix, template, type_code)
                )
            logger.info("✓ Migration: 新增 equipment_types.unit_prefix/label_template 欄位")

        # v2: 確保 equipment 有 type_code 欄位
        cursor.execute("PRAGMA table_info(equipment)")
        eq_columns = [col[1] for col in cursor.fetchall()]
        if eq_columns and 'type_code' not in eq_columns:
            cursor.execute("ALTER TABLE equipment ADD COLUMN type_code TEXT")
            logger.info("✓ Migration: 新增 equipment.type_code 欄位")
        if eq_columns and 'capacity_override' not in eq_columns:
            cursor.execute("ALTER TABLE equipment ADD COLUMN capacity_override TEXT")
            logger.info("✓ Migration: 新增 equipment.capacity_override 欄位")

        # v2: 設定 equipment 的 type_code (根據 id 直接映射，確保總是正確)
        # 關鍵韌性設備：直接根據 ID 設定 type_code
        type_code_by_id = [
            ('UTIL-001', 'POWER_STATION'),
            ('UTIL-002', 'GENERATOR'),
            ('RESP-001', 'O2_CYLINDER_H'),
            ('EMER-EQ-006', 'O2_CYLINDER_E'),
            ('RESP-002', 'O2_CONCENTRATOR'),
            ('RESP-003', 'VENTILATOR'),
            ('RESP-004', 'VENTILATOR'),
        ]
        for eq_id, tc in type_code_by_id:
            cursor.execute("UPDATE equipment SET type_code = ? WHERE id = ?", (tc, eq_id))
        # 其他設備根據模式設定
        cursor.execute("UPDATE equipment SET type_code = 'MONITOR' WHERE (id LIKE 'DIAG-%' OR name LIKE '%監視器%') AND type_code IS NULL")
        cursor.execute("UPDATE equipment SET type_code = 'GENERAL' WHERE type_code IS NULL")
        logger.info("✓ Migration: 設定 equipment.type_code 對應")

        # v2.1: 確保 equipment_units 有 soft-delete 欄位
        cursor.execute("PRAGMA table_info(equipment_units)")
        eu_columns = [col[1] for col in cursor.fetchall()]
        if eu_columns and 'is_active' not in eu_columns:
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN is_active INTEGER DEFAULT 1")
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN removed_at TIMESTAMP")
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN removed_by TEXT")
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN removal_reason TEXT")
            # 設定現有資料為 active
            cursor.execute("UPDATE equipment_units SET is_active = 1 WHERE is_active IS NULL")
            logger.info("✓ Migration: 新增 equipment_units soft-delete 欄位")

        # v2.1.1: Add O2 claim columns for anesthesia module
        # Re-check columns after potential additions above
        cursor.execute("PRAGMA table_info(equipment_units)")
        eu_columns = [col[1] for col in cursor.fetchall()]
        if eu_columns and 'claimed_by_case_id' not in eu_columns:
            try:
                cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_case_id TEXT")
                cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_at TIMESTAMP")
                cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_user_id TEXT")
                logger.info("✓ Migration: 新增 equipment_units O2 claim 欄位")
            except Exception as e:
                logger.warning(f"O2 claim columns may already exist: {e}")

        # v2.5.2: 確保 equipment_units 有 updated_at 欄位
        cursor.execute("PRAGMA table_info(equipment_units)")
        eu_columns = [col[1] for col in cursor.fetchall()]
        if eu_columns and 'updated_at' not in eu_columns:
            cursor.execute("ALTER TABLE equipment_units ADD COLUMN updated_at TIMESTAMP")
            logger.info("✓ Migration: 新增 equipment_units.updated_at 欄位")

        # v2.1: 建立 equipment_lifecycle_events 表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipment_lifecycle_events'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE equipment_lifecycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    unit_id INTEGER,
                    equipment_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('CREATE', 'SOFT_DELETE', 'RESTORE', 'UPDATE')),
                    actor TEXT,
                    reason TEXT,
                    snapshot_json TEXT,
                    correlation_id TEXT,
                    station_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_equipment ON equipment_lifecycle_events(equipment_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_unit ON equipment_lifecycle_events(unit_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_time ON equipment_lifecycle_events(created_at DESC)")
            logger.info("✓ Migration: 建立 equipment_lifecycle_events 表")

        # v2.1: 建立唯一約束（防止並發衝突）- 只對 active 的單位
        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_equipment_units_active_serial
                ON equipment_units(equipment_id, unit_serial) WHERE is_active = 1
            """)
        except Exception:
            pass  # SQLite 版本可能不支援 partial index

        # v2.1: 建立 v_equipment_status 視圖 (只計算 active units)
        cursor.execute("DROP VIEW IF EXISTS v_equipment_status")
        cursor.execute("""
            CREATE VIEW v_equipment_status AS
            SELECT
                e.id, e.name, e.type_code,
                et.type_name, et.category, et.resilience_category,
                et.unit_prefix, et.label_template,
                COUNT(u.id) as unit_count,
                ROUND(AVG(u.level_percent)) as avg_level,
                SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) as checked_count,
                MAX(u.last_check) as last_check,
                CASE
                    WHEN COUNT(u.id) = 0 THEN 'NO_UNITS'
                    WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = 0 THEN 'UNCHECKED'
                    WHEN SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) = COUNT(u.id) THEN 'CHECKED'
                    ELSE 'PARTIAL'
                END as check_status
            FROM equipment e
            LEFT JOIN equipment_types et ON e.type_code = et.type_code
            LEFT JOIN equipment_units u ON e.id = u.equipment_id AND (u.is_active = 1 OR u.is_active IS NULL)
            GROUP BY e.id
        """)
        logger.info("✓ Migration: 建立 v_equipment_status 視圖 (含 is_active 過濾)")

        # v1.4.3: 新增 medicines.reserved_qty 欄位 (庫存保留)
        cursor.execute("PRAGMA table_info(medicines)")
        med_columns = [col[1] for col in cursor.fetchall()]
        if med_columns and 'reserved_qty' not in med_columns:
            cursor.execute("ALTER TABLE medicines ADD COLUMN reserved_qty INTEGER DEFAULT 0")
            logger.info("✓ Migration: 新增 medicines.reserved_qty 欄位")

        # v1.4.3: 建立 pharmacy_dispatch_orders 表 (藥局撥發單)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pharmacy_dispatch_orders'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE pharmacy_dispatch_orders (
                    dispatch_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    target_station_id TEXT,
                    target_station_name TEXT,
                    target_unbound INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'DRAFT',
                    dispatch_method TEXT DEFAULT 'QR',
                    total_items INTEGER NOT NULL,
                    total_quantity INTEGER NOT NULL,
                    has_controlled INTEGER DEFAULT 0,
                    reserved_at TEXT,
                    dispatched_at TEXT,
                    dispatched_by TEXT,
                    received_at TEXT,
                    received_by TEXT,
                    receiver_station_id TEXT,
                    receipt_signature TEXT,
                    notes TEXT,
                    signature TEXT,
                    qr_chunks INTEGER DEFAULT 1,
                    CHECK (status IN ('DRAFT', 'RESERVED', 'DISPATCHED', 'RECEIVED', 'CANCELLED'))
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_status ON pharmacy_dispatch_orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_target ON pharmacy_dispatch_orders(target_station_id)")
            logger.info("✓ Migration: 建立 pharmacy_dispatch_orders 表")

        # v1.4.3: 建立 pharmacy_dispatch_items 表 (撥發單明細)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pharmacy_dispatch_items'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE pharmacy_dispatch_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dispatch_id TEXT NOT NULL,
                    medicine_code TEXT NOT NULL,
                    medicine_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    reserved_qty INTEGER DEFAULT 0,
                    unit TEXT DEFAULT '單位',
                    batch_number TEXT,
                    expiry_date TEXT,
                    is_controlled INTEGER DEFAULT 0,
                    FOREIGN KEY (dispatch_id) REFERENCES pharmacy_dispatch_orders(dispatch_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_items_order ON pharmacy_dispatch_items(dispatch_id)")
            logger.info("✓ Migration: 建立 pharmacy_dispatch_items 表")

        conn.commit()
    except Exception as e:
        logger.warning(f"Migration warning: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


@app.on_event("startup")
async def startup_event():
    """應用啟動時執行"""
    # 執行資料庫遷移
    run_migrations()

    # Seed demo data if running on Vercel
    if IS_VERCEL:
        from seeder_demo import seed_mirs_demo
        conn = db.get_connection()
        seed_mirs_demo(conn)
        logger.info("✓ [MIRS] Demo mode initialized with sample data")
    else:
        # 只在非 Vercel 環境啟動背景任務
        asyncio.create_task(daily_equipment_reset())
        logger.info("✓ 每日設備重置背景任務已啟動 (07:00am)")


# ============================================================================
# API 端點
# ============================================================================

def get_local_ip():
    """取得本機區網 IP 位址"""
    try:
        # 建立一個 UDP socket 連到外部 IP (不會真的發送封包)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # 備用方法：嘗試透過 hostname
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip.startswith("127."):
                return None
            return local_ip
        except Exception:
            return None


@app.get("/api/info")
async def api_info():
    """API 資訊端點 - 包含伺服器 IP"""
    local_ip = get_local_ip()
    return {
        "name": "醫療站庫存管理系統 API",
        "version": config.VERSION,
        "station": config.STATION_ID,
        "docs": "/docs",
        "server_ip": local_ip,
        "server_url": f"http://{local_ip}:8090/api" if local_ip else None
    }


@app.get("/api/health")
async def health_check():
    """健康檢查 - 包含站點資訊"""
    return {
        "status": "healthy",
        "version": config.VERSION,
        "station_id": config.get_station_id(),
        "station_type": config.STATION_TYPE,
        "timestamp": datetime.now().isoformat(),
        "demo_mode": IS_VERCEL
    }


# ========== Demo Mode Endpoints ==========

@app.get("/api/demo-status")
async def get_demo_status():
    """Get demo mode status"""
    return {
        "is_demo": IS_VERCEL,
        "version": config.VERSION,
        "message": "此為線上展示版，資料將在頁面重整後重置" if IS_VERCEL else None,
        "github_url": "https://github.com/cutemo0953/MIRS"
    }


@app.post("/api/demo/reset")
async def reset_demo():
    """Reset demo database (only available in Vercel mode)"""
    if not IS_VERCEL:
        raise HTTPException(
            status_code=403,
            detail="Reset is only available in demo mode"
        )

    try:
        # Reset the in-memory database
        db.reset_memory_db()

        # Re-seed with demo data
        from seeder_demo import seed_mirs_demo
        conn = db.get_connection()
        seed_mirs_demo(conn)

        return {
            "success": True,
            "message": "Demo data has been reset successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset demo: {str(e)}"
        )


# ========== 站點資訊 API (v2.0 新增) ==========

@app.get("/api/station/info")
async def get_station_info():
    """取得當前站點完整資訊 - 前端初始化時呼叫"""
    return {
        "station": {
            "id": config.get_station_id(),
            "type": config.STATION_TYPE,
            "type_name": {
                "HC": "衛生所",
                "BORP": "備援手術室",
                "LOG-HUB": "物資中心",
                "HOSP": "醫院自訂"
            }.get(config.STATION_TYPE, "站點"),
            "org": config.STATION_ORG,
            "number": config.STATION_NUMBER,
            "name": config.get_station_name()
        },
        "organization": {
            "code": config.ORG_CODE,
            "name": config.ORG_NAME
        },
        "system": {
            "version": config.VERSION,
            "timezone": config.TIMEZONE
        }
    }

@app.get("/api/station/types")
async def get_station_types():
    """取得所有站點類型定義"""
    return {
        "types": [
            {
                "code": "HC",
                "name": "衛生所",
                "name_en": "Health Center",
                "description": "基礎醫療物資、常用藥品"
            },
            {
                "code": "BORP",
                "name": "備援手術室",
                "name_en": "Backup Operating Room Point",
                "description": "手術耗材、麻醉藥品、手術器械"
            },
            {
                "code": "LOG-HUB",
                "name": "物資中心",
                "name_en": "Logistic Hub",
                "description": "大量物資管理、配送追蹤"
            },
            {
                "code": "HOSP",
                "name": "醫院自訂",
                "name_en": "Hospital Custom",
                "description": "空白模板，由醫院自行設定"
            }
        ]
    }


@app.get("/api/stats")
async def get_stats(station_id: str = None):
    """取得系統統計(支援站點過濾)"""
    try:
        stats = db.get_stats(station_id)
        return stats
    except Exception as e:
        logger.error(f"取得統計失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 物品管理 API ==========

@app.get("/api/items")
async def get_items():
    """取得所有物品 (包含一般物品與藥品)"""
    try:
        # Get general inventory items
        items = db.get_inventory_items()

        # Get medicines from pharmacy database
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                medicine_code as code,
                COALESCE(brand_name, generic_name) as name,
                unit,
                current_stock,
                min_stock,
                '藥品' as category,
                is_controlled_drug,
                controlled_level
            FROM medicines
            WHERE is_active = 1
            ORDER BY medicine_code
        """)

        medicines = [dict(row) for row in cursor.fetchall()]

        # Combine items and medicines
        all_items = items + medicines

        return {"items": all_items, "count": len(all_items)}
    except Exception as e:
        logger.error(f"取得物品列表失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/items")
async def create_item(request: ItemCreateRequest):
    """新增物品"""
    logger.info(f"新增物品: {request.name}")
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # Auto-generate code if empty
        if not request.code or request.code.strip() == '':
            item_code = db.generate_item_code(request.category)
        else:
            item_code = request.code
            # Check for duplicates using correct column name
            cursor.execute("SELECT item_code FROM items WHERE item_code = ?", (item_code,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"物品代碼 {item_code} 已存在")

        # Determine item_category based on user's category selection
        # Most user-added items are consumables, but allow for equipment
        if request.category in ['醫療設備', '診斷設備']:
            item_category = 'EQUIPMENT'
        else:
            item_category = 'CONSUMABLE'

        # Insert with correct column names
        cursor.execute("""
            INSERT INTO items (item_code, item_name, item_category, category, unit, min_stock)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (item_code, request.name, item_category, request.category, request.unit or '個', request.minStock or 0))

        conn.commit()

        return {
            "success": True,
            "message": f"物品 {request.name} 新增成功",
            "item": {
                "code": item_code,
                "name": request.name,
                "unit": request.unit or '個',
                "minStock": request.minStock or 0,
                "category": request.category
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"新增物品失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.put("/api/items/{code}")
async def update_item(code: str, request: ItemUpdateRequest):
    """更新物品"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT item_code FROM items WHERE item_code = ?", (code,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"物品代碼 {code} 不存在")

        update_fields = []
        update_values = []

        if request.name: update_fields.append("item_name = ?"); update_values.append(request.name)
        if request.unit: update_fields.append("unit = ?"); update_values.append(request.unit)
        if request.minStock is not None: update_fields.append("min_stock = ?"); update_values.append(request.minStock)
        if request.category: update_fields.append("category = ?"); update_values.append(request.category)

        if not update_fields:
            raise HTTPException(status_code=400, detail="沒有提供要更新的欄位")

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_values.append(code)

        cursor.execute(f"UPDATE items SET {', '.join(update_fields)} WHERE item_code = ?", update_values)
        conn.commit()
        
        return {"success": True, "message": f"物品 {code} 更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.delete("/api/items/{code}")
async def delete_item(code: str):
    """刪除物品"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT item_name FROM items WHERE item_code = ?", (code,))
        item = cursor.fetchone()
        if not item:
            raise HTTPException(status_code=404, detail=f"物品代碼 {code} 不存在")

        cursor.execute("DELETE FROM items WHERE item_code = ?", (code,))
        conn.commit()

        return {"success": True, "message": f"物品 {item['item_name']} 已刪除"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ========== 庫存操作 API ==========

@app.post("/api/receive")
async def receive_item(request: ReceiveRequest):
    """進貨"""
    return db.receive_item(request)


@app.post("/api/consume")
async def consume_item(request: ConsumeRequest):
    """消耗"""
    return db.consume_item(request)


# ========== 血袋管理 API ==========

@app.get("/api/blood/inventory")
async def get_blood_inventory(station_id: str = Query(None, description="站點ID，留空則查詢所有站點")):
    """取得血袋庫存(支援多站點)"""
    try:
        inventory = db.get_blood_inventory(station_id)
        return {"bloodInventory": inventory, "station_id": station_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/blood/receive")
async def receive_blood(request: BloodRequest):
    """血袋入庫"""
    return db.process_blood('receive', request)


@app.post("/api/blood/consume")
async def consume_blood(request: BloodRequest):
    """血袋出庫"""
    return db.process_blood('consume', request)


@app.get("/api/blood/events")
async def get_blood_events(
    station_id: str = Query("HC-000000"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    blood_type: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500)
):
    """取得血袋入庫出庫歷史記錄"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 建立查詢條件
        where_clauses = ["station_id = ?"]
        params = [station_id]

        if start_date:
            where_clauses.append("DATE(timestamp) >= ?")
            params.append(start_date)

        if end_date:
            where_clauses.append("DATE(timestamp) <= ?")
            params.append(end_date)

        if blood_type:
            where_clauses.append("blood_type = ?")
            params.append(blood_type)

        if event_type:
            where_clauses.append("event_type = ?")
            params.append(event_type)

        where_sql = " AND ".join(where_clauses)
        params.append(limit)

        cursor.execute(f"""
            SELECT
                id,
                event_type,
                blood_type,
                quantity,
                station_id,
                operator,
                timestamp
            FROM blood_events
            WHERE {where_sql}
            ORDER BY timestamp DESC
            LIMIT ?
        """, params)

        events = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return {"status": "success", "data": events, "count": len(events)}
    except Exception as e:
        logger.error(f"取得血袋歷史記錄失敗: {e}")
        return {"status": "error", "message": str(e)}


# ========== 緊急血袋管理 API (v1.4.5) ==========

@app.post("/api/blood/emergency/register")
async def register_emergency_blood_bag(request: EmergencyBloodBagRequest):
    """登記緊急血袋"""
    try:
        data = {
            'blood_type': request.bloodType,
            'product_type': request.productType,
            'collection_date': request.collectionDate,
            'volume_ml': request.volumeMl,
            'station_id': request.stationId,
            'operator': request.operator,
            'org_code': request.orgCode,
            'remarks': request.remarks or ''
        }
        return db.register_emergency_blood_bag(data)
    except Exception as e:
        logger.error(f"緊急血袋登記失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/blood/emergency/list")
async def get_emergency_blood_bags(status: Optional[str] = Query(None, description="狀態篩選 (AVAILABLE/USED/EXPIRED/DISCARDED)")):
    """取得緊急血袋清單"""
    try:
        bags = db.get_emergency_blood_bags(status)
        return {
            "bloodBags": bags,
            "count": len(bags)
        }
    except Exception as e:
        logger.error(f"取得緊急血袋清單失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/blood/emergency/use")
async def use_emergency_blood_bag(request: EmergencyBloodBagUseRequest):
    """使用緊急血袋"""
    try:
        return db.use_emergency_blood_bag(
            request.bloodBagCode,
            request.patientName,
            request.operator
        )
    except Exception as e:
        logger.error(f"緊急血袋使用失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/blood/emergency/label/{blood_bag_code}")
async def get_emergency_blood_bag_label(blood_bag_code: str):
    """取得緊急血袋標籤 (HTML)"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM emergency_blood_bags
            WHERE blood_bag_code = ?
        """, (blood_bag_code,))

        bag = cursor.fetchone()
        conn.close()

        if not bag:
            raise HTTPException(status_code=404, detail=f"血袋編號 {blood_bag_code} 不存在")

        # 生成HTML標籤
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>緊急血袋標籤 - {bag['blood_bag_code']}</title>
    <style>
        @media print {{
            @page {{ size: 10cm 5cm; margin: 0; }}
            body {{ margin: 0.5cm; }}
        }}
        body {{
            font-family: 'Microsoft JhengHei', 'SimHei', sans-serif;
            font-size: 12pt;
            line-height: 1.4;
        }}
        .label {{
            width: 9cm;
            height: 4cm;
            border: 2px solid #000;
            padding: 0.3cm;
            box-sizing: border-box;
        }}
        .header {{
            text-align: center;
            font-weight: bold;
            font-size: 14pt;
            border-bottom: 2px solid #000;
            padding-bottom: 3px;
            margin-bottom: 5px;
        }}
        .blood-type {{
            font-size: 28pt;
            font-weight: bold;
            color: #d00;
            text-align: center;
            margin: 5px 0;
        }}
        .info {{
            font-size: 10pt;
            margin: 2px 0;
        }}
        .code {{
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 11pt;
        }}
        .warning {{
            color: #d00;
            font-weight: bold;
            font-size: 9pt;
            text-align: center;
            margin-top: 3px;
        }}
    </style>
</head>
<body onload="window.print();">
    <div class="label">
        <div class="header">緊急血袋標籤 EMERGENCY BLOOD BAG</div>
        <div class="blood-type">{bag['blood_type']}</div>
        <div class="info">編號: <span class="code">{bag['blood_bag_code']}</span></div>
        <div class="info">血品: {bag['product_type']}</div>
        <div class="info">容量: {bag['volume_ml']} ml</div>
        <div class="info">採集: {bag['collection_date']}</div>
        <div class="info">效期: {bag['expiry_date']}</div>
        <div class="warning">⚠ 使用前請確認血型與效期 ⚠</div>
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成血袋標籤失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/blood/label")
async def get_blood_batch_label(
    blood_type: str = Query(..., description="血型"),
    quantity: int = Query(..., ge=1, description="數量"),
    station_id: str = Query("HC-000000", description="站點ID"),
    remarks: str = Query("", description="批號或備註")
):
    """取得一般血袋批次標籤 (HTML) - 用於列印 - 多標籤排列在 A4 紙上"""
    try:
        from datetime import datetime

        # 生成批次基礎編號
        now = datetime.now()
        batch_base = f"BATCH-{station_id}-{now.strftime('%Y%m%d-%H%M%S')}"

        # 為每一袋血生成獨立標籤
        labels_html = []
        for i in range(1, quantity + 1):
            bag_number = f"{batch_base}-{i:03d}"
            label_number = f"{i}/{quantity}"

            label_html = f"""
        <div class="label">
            <div class="header">血袋標籤 {label_number}</div>
            <div class="blood-type">{blood_type}</div>
            <div class="volume">1 U</div>
            <div class="info">編號: <span class="code">{bag_number}</span></div>
            <div class="info">站點: {station_id}</div>
            <div class="info">入庫: {now.strftime('%Y-%m-%d %H:%M')}</div>
            {f'<div class="info">備註: {remarks}</div>' if remarks else ''}
            <div class="warning">⚠ 使用前請確認血型 ⚠</div>
        </div>"""
            labels_html.append(label_html)

        # 生成可列印的 HTML 頁面 - 多標籤排列在 A4 上
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>血袋標籤 - {blood_type} ({quantity}張)</title>
    <style>
        @media print {{
            @page {{
                size: A4;
                margin: 5mm;
            }}
            body {{ margin: 0; }}
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Microsoft JhengHei', 'SimHei', Arial, sans-serif;
            margin: 5mm;
            padding: 0;
        }}
        .labels-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 2mm;
            justify-content: flex-start;
        }}
        .label {{
            width: 50mm;
            height: 70mm;
            border: 1.5px solid #000;
            padding: 2mm;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            background: white;
            page-break-inside: avoid;
        }}
        .header {{
            text-align: center;
            font-weight: bold;
            font-size: 9pt;
            border-bottom: 1.5px solid #000;
            padding-bottom: 2px;
            margin-bottom: 3px;
            background-color: #f0f0f0;
        }}
        .blood-type {{
            font-size: 28pt;
            font-weight: bold;
            color: #cc0000;
            text-align: center;
            margin: 5px 0;
            line-height: 1.1;
        }}
        .volume {{
            font-size: 14pt;
            font-weight: bold;
            color: #cc0000;
            text-align: center;
            margin: 2px 0;
        }}
        .info {{
            font-size: 8pt;
            margin: 2px 0;
            line-height: 1.3;
        }}
        .code {{
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 7pt;
        }}
        .warning {{
            color: #cc0000;
            font-weight: bold;
            font-size: 7pt;
            text-align: center;
            margin-top: auto;
            border-top: 1px solid #000;
            padding-top: 2px;
        }}
        .print-info {{
            text-align: center;
            margin-bottom: 10px;
            font-size: 10pt;
            color: #666;
        }}
        @media print {{
            .print-info {{ display: none; }}
        }}
    </style>
</head>
<body onload="window.print();">
    <div class="print-info">共 {quantity} 張標籤 ({blood_type}) - 建議使用 A4 紙列印</div>
    <div class="labels-container">
        {''.join(labels_html)}
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"生成血袋批次標籤失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/blood/transfer")
async def transfer_blood(request: BloodTransferRequest):
    """血袋併站轉移 - 從來源站點轉移血袋到目標站點"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 1. 檢查來源站點是否有足夠血袋
        cursor.execute("""
            SELECT quantity FROM blood_inventory
            WHERE blood_type = ? AND station_id = ?
        """, (request.bloodType, request.sourceStationId))

        source_result = cursor.fetchone()
        if not source_result:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"來源站點 {request.sourceStationId} 無此血型 {request.bloodType}"
            )

        source_quantity = source_result[0]
        if source_quantity < request.quantity:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"來源站點血袋不足: 需要 {request.quantity}U, 僅有 {source_quantity}U"
            )

        # 2. 從來源站點減少血袋
        cursor.execute("""
            UPDATE blood_inventory
            SET quantity = quantity - ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE blood_type = ? AND station_id = ?
        """, (request.quantity, request.bloodType, request.sourceStationId))

        # 3. 記錄來源站點的出庫事件
        cursor.execute("""
            INSERT INTO blood_events
            (event_type, blood_type, quantity, station_id, operator, remarks)
            VALUES ('TRANSFER_OUT', ?, ?, ?, ?, ?)
        """, (
            request.bloodType,
            request.quantity,
            request.sourceStationId,
            request.operator,
            f"轉移至 {request.targetStationId}. {request.remarks or ''}"
        ))

        # 4. 在目標站點增加血袋(如果不存在則新增)
        cursor.execute("""
            INSERT INTO blood_inventory (blood_type, quantity, station_id)
            VALUES (?, ?, ?)
            ON CONFLICT(blood_type, station_id) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                last_updated = CURRENT_TIMESTAMP
        """, (request.bloodType, request.quantity, request.targetStationId))

        # 5. 記錄目標站點的入庫事件
        cursor.execute("""
            INSERT INTO blood_events
            (event_type, blood_type, quantity, station_id, operator, remarks)
            VALUES ('TRANSFER_IN', ?, ?, ?, ?, ?)
        """, (
            request.bloodType,
            request.quantity,
            request.targetStationId,
            request.operator,
            f"來自 {request.sourceStationId}. {request.remarks or ''}"
        ))

        conn.commit()
        conn.close()

        logger.info(
            f"血袋併站轉移成功: {request.bloodType} {request.quantity}U "
            f"從 {request.sourceStationId} -> {request.targetStationId}"
        )

        return {
            "success": True,
            "message": f"成功轉移 {request.quantity}U {request.bloodType} 血袋",
            "source_station": request.sourceStationId,
            "target_station": request.targetStationId,
            "blood_type": request.bloodType,
            "quantity": request.quantity,
            "operator": request.operator
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"血袋併站轉移失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 設備管理 API ==========

@app.get("/api/equipment/status")
async def get_equipment_status(station_id: str = None):
    """取得所有設備狀態"""
    try:
        status = db.get_equipment_status(station_id)
        return {"equipment": status, "count": len(status)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/equipment")
async def get_equipment(station_id: str = None):
    """取得所有設備"""
    return await get_equipment_status(station_id)


@app.post("/api/equipment/check/{equipment_id}")
async def check_equipment(equipment_id: str, request: EquipmentCheckRequest):
    """設備檢查"""
    return db.check_equipment(equipment_id, request)


# v1.2.7: 更新設備單位 (個別鋼瓶追蹤)
class EquipmentUnitUpdateRequest(BaseModel):
    equipment_id: str
    unit_label: str
    level_percent: int = Field(ge=0, le=100)
    status: str = "AVAILABLE"


@app.post("/api/equipment/units/update")
async def update_equipment_unit(request: EquipmentUnitUpdateRequest):
    """更新設備單位狀態 (v1.2.8) - 含自動同步設備表 + 檢查記錄"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 0. 取得更新前的狀態 (用於歷史記錄)
        cursor.execute("""
            SELECT id, level_percent, status
            FROM equipment_units
            WHERE equipment_id = ? AND unit_label = ?
        """, (request.equipment_id, request.unit_label))
        old_state = cursor.fetchone()
        if not old_state:
            raise HTTPException(status_code=404, detail=f"找不到單位 {request.unit_label}")

        unit_id = old_state['id']
        level_before = old_state['level_percent']
        status_before = old_state['status']

        # 1. 更新 equipment_units 表
        cursor.execute("""
            UPDATE equipment_units
            SET level_percent = ?, status = ?, last_check = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE equipment_id = ? AND unit_label = ?
        """, (request.level_percent, request.status, request.equipment_id, request.unit_label))

        # 2. 記錄檢查歷史
        cursor.execute("""
            INSERT INTO equipment_check_history
            (equipment_id, unit_label, unit_id, check_date, check_time, level_before, level_after, status_before, status_after, station_id)
            VALUES (?, ?, ?, DATE('now'), CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
        """, (request.equipment_id, request.unit_label, unit_id, level_before, request.level_percent,
              status_before, request.status, config.get_station_id()))

        # 3. 計算該設備所有單位的平均 level
        cursor.execute("""
            SELECT AVG(level_percent) as avg_level,
                   COUNT(*) as total,
                   SUM(CASE WHEN last_check IS NOT NULL THEN 1 ELSE 0 END) as checked
            FROM equipment_units
            WHERE equipment_id = ?
        """, (request.equipment_id,))
        stats = cursor.fetchone()
        avg_level = round(stats['avg_level']) if stats['avg_level'] else 0
        all_checked = stats['checked'] == stats['total']

        # 4. 同步更新 equipment 表的 power_level 和 status
        new_status = 'NORMAL' if all_checked else 'PENDING'
        cursor.execute("""
            UPDATE equipment
            SET power_level = ?, status = ?, last_check = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (avg_level, new_status, request.equipment_id))

        conn.commit()

        return {
            "success": True,
            "message": f"單位 {request.unit_label} 已更新為 {request.level_percent}% ({request.status})",
            "avg_level": avg_level,
            "equipment_status": new_status,
            "checked_count": stats['checked'],
            "total_count": stats['total']
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Update unit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class UnitResetRequest(BaseModel):
    equipment_id: str
    unit_label: str


@app.post("/api/equipment/units/reset-check")
async def reset_unit_check(request: UnitResetRequest):
    """重置單位檢查狀態 (v1.2.8) - 設為未檢查，但保留歷史記錄"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 1. 取得目前狀態
        cursor.execute("""
            SELECT id, level_percent, status, last_check
            FROM equipment_units
            WHERE equipment_id = ? AND unit_label = ?
        """, (request.equipment_id, request.unit_label))
        current = cursor.fetchone()
        if not current:
            raise HTTPException(status_code=404, detail=f"找不到單位 {request.unit_label}")

        # 2. 記錄重置操作到歷史 (status_after = 'RESET')
        cursor.execute("""
            INSERT INTO equipment_check_history
            (equipment_id, unit_label, unit_id, check_date, check_time, level_before, level_after, status_before, status_after, station_id, remarks)
            VALUES (?, ?, ?, DATE('now'), CURRENT_TIMESTAMP, ?, ?, ?, 'RESET', ?, '檢查狀態重置')
        """, (request.equipment_id, request.unit_label, current['id'], current['level_percent'], current['level_percent'],
              current['status'], config.get_station_id()))

        # 3. 清除 last_check (設為未檢查)
        cursor.execute("""
            UPDATE equipment_units
            SET last_check = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE equipment_id = ? AND unit_label = ?
        """, (request.equipment_id, request.unit_label))

        # 4. 重新計算設備狀態
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN last_check IS NOT NULL THEN 1 ELSE 0 END) as checked
            FROM equipment_units
            WHERE equipment_id = ?
        """, (request.equipment_id,))
        stats = cursor.fetchone()
        all_checked = stats['checked'] == stats['total']
        new_status = 'NORMAL' if all_checked else 'PENDING'

        cursor.execute("""
            UPDATE equipment
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, request.equipment_id))

        conn.commit()

        return {
            "success": True,
            "message": f"單位 {request.unit_label} 已重置為未檢查",
            "checked_count": stats['checked'],
            "total_count": stats['total']
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Reset unit check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# v1.2.8: 檢查歷史報表 API
@app.get("/api/equipment/check-history")
async def get_check_history(
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD"),
    equipment_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500)
):
    """取得設備檢查歷史記錄"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT h.*, e.name as equipment_name
            FROM equipment_check_history h
            LEFT JOIN equipment e ON h.equipment_id = e.id
            WHERE 1=1
        """
        params = []

        if date:
            query += " AND h.check_date = ?"
            params.append(date)
        if equipment_id:
            query += " AND h.equipment_id = ?"
            params.append(equipment_id)

        query += " ORDER BY h.check_time DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return {
            "success": True,
            "records": [dict(row) for row in rows],
            "total": len(rows)
        }
    except Exception as e:
        logger.error(f"Get check history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/equipment/check-summary")
async def get_check_summary(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    """取得每日檢查摘要"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT
                check_date,
                COUNT(DISTINCT equipment_id) as equipment_checked,
                COUNT(*) as total_checks,
                COUNT(DISTINCT unit_label) as units_checked,
                MIN(check_time) as first_check,
                MAX(check_time) as last_check
            FROM equipment_check_history
            WHERE 1=1
        """
        params = []

        if start_date:
            query += " AND check_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND check_date <= ?"
            params.append(end_date)

        query += " GROUP BY check_date ORDER BY check_date DESC LIMIT 30"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return {
            "success": True,
            "summaries": [dict(row) for row in rows]
        }
    except Exception as e:
        logger.error(f"Get check summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/equipment/check-report/{date}")
async def get_daily_check_report(date: str):
    """取得特定日期的完整檢查報表 (v1.2.8: 只顯示每單位最新狀態)"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 取得當日每單位的最新檢查記錄 (排除 RESET，只取最新)
        cursor.execute("""
            SELECT h.*, e.name as equipment_name
            FROM equipment_check_history h
            LEFT JOIN equipment e ON h.equipment_id = e.id
            INNER JOIN (
                SELECT equipment_id, unit_label, MAX(check_time) as max_time
                FROM equipment_check_history
                WHERE check_date = ? AND status_after != 'RESET'
                GROUP BY equipment_id, unit_label
            ) latest ON h.equipment_id = latest.equipment_id
                    AND h.unit_label = latest.unit_label
                    AND h.check_time = latest.max_time
            WHERE h.check_date = ? AND h.status_after != 'RESET'
            ORDER BY h.equipment_id, h.unit_label
        """, (date, date))
        records = [dict(row) for row in cursor.fetchall()]

        # 取得當日檢查的設備統計 (排除 RESET)
        cursor.execute("""
            SELECT
                equipment_id,
                COUNT(DISTINCT unit_label) as units_checked,
                MIN(level_after) as min_level,
                MAX(level_after) as max_level,
                AVG(level_after) as avg_level
            FROM equipment_check_history
            WHERE check_date = ? AND status_after != 'RESET'
            GROUP BY equipment_id
        """, (date,))
        equipment_stats = [dict(row) for row in cursor.fetchall()]

        # 取得總計 (排除 RESET)
        cursor.execute("""
            SELECT
                COUNT(DISTINCT equipment_id) as equipment_count,
                COUNT(DISTINCT equipment_id || '-' || unit_label) as check_count,
                COUNT(DISTINCT unit_label) as unit_count,
                MIN(check_time) as first_check,
                MAX(check_time) as last_check
            FROM equipment_check_history
            WHERE check_date = ? AND status_after != 'RESET'
        """, (date,))
        summary = dict(cursor.fetchone())

        return {
            "success": True,
            "date": date,
            "station_id": config.get_station_id(),
            "summary": summary,
            "equipment_stats": equipment_stats,
            "records": records
        }
    except Exception as e:
        logger.error(f"Get daily report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/equipment")
async def create_equipment(request: EquipmentCreateRequest):
    """新增設備"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        equipment_id = db.generate_equipment_id(request.category)
        
        cursor.execute("""
            INSERT INTO equipment (id, name, category, quantity, status, remarks)
            VALUES (?, ?, ?, ?, 'UNCHECKED', ?)
        """, (equipment_id, request.name, request.category, request.quantity, request.remarks))
        
        conn.commit()
        
        return {
            "success": True,
            "message": f"設備 {request.name} 新增成功",
            "equipment": {
                "id": equipment_id,
                "name": request.name,
                "category": request.category,
                "quantity": request.quantity
            }
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.put("/api/equipment/{equipment_id}")
async def update_equipment(equipment_id: str, request: EquipmentUpdateRequest):
    """更新設備"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id FROM equipment WHERE id = ?", (equipment_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"設備ID {equipment_id} 不存在")
        
        update_fields = []
        update_values = []
        
        if request.name: update_fields.append("name = ?"); update_values.append(request.name)
        if request.category: update_fields.append("category = ?"); update_values.append(request.category)
        if request.quantity is not None: update_fields.append("quantity = ?"); update_values.append(request.quantity)
        if request.status: update_fields.append("status = ?"); update_values.append(request.status)
        if request.remarks: update_fields.append("remarks = ?"); update_values.append(request.remarks)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="沒有提供要更新的欄位")
        
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_values.append(equipment_id)
        
        cursor.execute(f"UPDATE equipment SET {', '.join(update_fields)} WHERE id = ?", update_values)
        conn.commit()
        
        return {"success": True, "message": f"設備 {equipment_id} 更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.delete("/api/equipment/{equipment_id}")
async def delete_equipment(equipment_id: str):
    """刪除設備"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT name FROM equipment WHERE id = ?", (equipment_id,))
        equipment = cursor.fetchone()
        if not equipment:
            raise HTTPException(status_code=404, detail=f"設備ID {equipment_id} 不存在")
        
        cursor.execute("DELETE FROM equipment WHERE id = ?", (equipment_id,))
        conn.commit()
        
        return {"success": True, "message": f"設備 {equipment['name']} 已刪除"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ========== 手術記錄 API (新增) ==========

@app.post("/api/surgery/record")
async def create_surgery_record(request: SurgeryRecordRequest):
    """建立手術記錄"""
    return db.create_surgery_record(request)


@app.get("/api/surgery/records")
async def get_surgery_records(
    start_date: Optional[str] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="結束日期 YYYY-MM-DD"),
    patient_name: Optional[str] = Query(None, description="病患姓名"),
    limit: int = Query(50, ge=1, le=1000, description="最大回傳筆數")
):
    """查詢手術記錄"""
    try:
        records = db.get_surgery_records(start_date, end_date, patient_name, limit)
        return {"records": records, "count": len(records)}
    except Exception as e:
        logger.error(f"查詢手術記錄失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/surgery/export/csv")
async def export_surgery_csv(
    start_date: Optional[str] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="結束日期 YYYY-MM-DD")
):
    """匯出手術記錄 CSV"""
    try:
        csv_content = db.export_surgery_records_csv(start_date, end_date)

        filename = f"surgery_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"匯出 CSV 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MIRS v0.7 - Inventory Check API (PWA盤點核對)
# ============================================================================

# 全域變數儲存盤點記錄（正式環境應存入資料庫）
_inventory_check_records = []

@app.post("/api/inventory-check")
async def submit_inventory_check(request: dict):
    """
    接收 PWA 盤點核對結果
    """
    try:
        check_id = f"CHK-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{len(_inventory_check_records)+1:03d}"

        check_record = {
            "check_id": check_id,
            "station_id": request.get("station_id", "STATION-001"),
            "checker_id": request.get("checker_id"),
            "checker_name": request.get("checker_name"),
            "checked_at": request.get("checked_at", datetime.now().isoformat()),
            "total_items": request.get("total_items", 0),
            "confirmed_count": request.get("confirmed_count", 0),
            "error_count": request.get("error_count", 0),
            "errors": request.get("errors", []),
            "errors_pending": len(request.get("errors", [])),
            "received_at": datetime.now().isoformat()
        }

        _inventory_check_records.append(check_record)

        # 也存到 localStorage 供後續查詢
        logger.info(f"✓ 盤點記錄已接收: {check_id}, 確認: {check_record['confirmed_count']}, 錯誤: {check_record['error_count']}")

        return {
            "status": "ACCEPTED",
            "check_id": check_id,
            "station_id": check_record["station_id"],
            "checker_name": check_record["checker_name"],
            "summary": {
                "total": check_record["total_items"],
                "confirmed": check_record["confirmed_count"],
                "errors": check_record["error_count"]
            },
            "errors_queued": check_record["error_count"],
            "received_at": check_record["received_at"]
        }
    except Exception as e:
        logger.error(f"盤點記錄提交失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inventory-check/history")
async def get_inventory_check_history(
    station_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50)
):
    """
    查詢盤點記錄歷史
    """
    try:
        checks = _inventory_check_records.copy()

        # 篩選
        if station_id:
            checks = [c for c in checks if c.get("station_id") == station_id]

        if from_date:
            checks = [c for c in checks if c.get("checked_at", "")[:10] >= from_date]

        if to_date:
            checks = [c for c in checks if c.get("checked_at", "")[:10] <= to_date]

        if status == "has_errors":
            checks = [c for c in checks if c.get("error_count", 0) > 0]
        elif status == "all_confirmed":
            checks = [c for c in checks if c.get("error_count", 0) == 0]

        # 排序（最新的在前）
        checks = sorted(checks, key=lambda x: x.get("checked_at", ""), reverse=True)[:limit]

        return {
            "checks": checks,
            "total_count": len(checks)
        }
    except Exception as e:
        logger.error(f"查詢盤點記錄失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/inventory-check/resolve-error")
async def resolve_inventory_error(request: dict):
    """
    處理盤點錯誤項目
    """
    try:
        check_id = request.get("check_id")
        item_code = request.get("item_code")
        resolution = request.get("resolution", "ADJUSTED")
        resolver_name = request.get("resolver_name")
        notes = request.get("notes", "")

        # 找到對應的盤點記錄並更新
        for check in _inventory_check_records:
            if check["check_id"] == check_id:
                for error in check.get("errors", []):
                    if error.get("item_code") == item_code:
                        error["resolved"] = True
                        error["resolution"] = resolution
                        error["resolver_name"] = resolver_name
                        error["resolved_at"] = datetime.now().isoformat()
                        error["resolution_notes"] = notes

                # 更新待處理數量
                check["errors_pending"] = len([e for e in check.get("errors", []) if not e.get("resolved")])
                break

        logger.info(f"✓ 錯誤項目已處理: {check_id}/{item_code} by {resolver_name}")

        return {
            "status": "RESOLVED",
            "check_id": check_id,
            "item_code": item_code,
            "resolution": resolution,
            "resolved_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"處理錯誤項目失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inventory-check/export/csv")
async def export_inventory_check_csv(
    station_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None)
):
    """
    匯出盤點記錄 CSV
    """
    try:
        checks = _inventory_check_records.copy()

        if station_id:
            checks = [c for c in checks if c.get("station_id") == station_id]
        if from_date:
            checks = [c for c in checks if c.get("checked_at", "")[:10] >= from_date]
        if to_date:
            checks = [c for c in checks if c.get("checked_at", "")[:10] <= to_date]

        # 建立 CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["盤點ID", "盤點時間", "盤點人員", "總項目", "已確認", "錯誤", "待處理"])

        for check in checks:
            writer.writerow([
                check.get("check_id", ""),
                check.get("checked_at", ""),
                check.get("checker_name", ""),
                check.get("total_items", 0),
                check.get("confirmed_count", 0),
                check.get("error_count", 0),
                check.get("errors_pending", 0)
            ])

        csv_content = output.getvalue()
        filename = f"inventory_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"匯出盤點記錄失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MIRS v2.3 - Emergency Dispense API (Break-the-Glass Feature)
# ============================================================================

@app.post("/api/pharmacy/dispense/emergency", status_code=201)
async def emergency_dispense(request: EmergencyDispenseRequest):
    """
    緊急領用藥品 (Break-the-Glass)
    - 不需要藥師 PIN 碼
    - 立即扣庫存
    - 記錄緊急原因
    - 狀態設為 EMERGENCY
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. 檢查藥品是否存在 (先查 medicines 表，再查 items 表)
        # 先查 medicines 表
        cursor.execute("""
            SELECT medicine_code, generic_name, brand_name, unit, current_stock
            FROM medicines
            WHERE medicine_code = ? AND is_active = 1
        """, (request.medicineCode,))

        medicine = cursor.fetchone()

        # 如果不在 medicines 表，查 items 表
        if not medicine:
            cursor.execute("""
                SELECT code as medicine_code, name as generic_name, name as brand_name, unit,
                       (SELECT SUM(CASE WHEN event_type='RECEIVE' THEN quantity ELSE -quantity END)
                        FROM inventory_events WHERE item_code = code) as current_stock
                FROM items
                WHERE code = ?
            """, (request.medicineCode,))
            medicine = cursor.fetchone()

        if not medicine:
            raise HTTPException(status_code=404, detail=f"藥品/物品代碼 {request.medicineCode} 不存在")

        current_stock = medicine['current_stock'] or 0

        # 2. 檢查庫存是否足夠
        if current_stock < request.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"庫存不足！當前庫存: {current_stock} {medicine['unit']}, 需要: {request.quantity} {medicine['unit']}"
            )

        # 3. 建立緊急領用記錄
        medicine_name = medicine['brand_name'] or medicine['generic_name']

        cursor.execute("""
            INSERT INTO dispense_records (
                medicine_code, medicine_name, quantity, unit,
                dispensed_by, status, emergency_reason,
                patient_ref_id, patient_name, station_code,
                created_at
            ) VALUES (?, ?, ?, ?, ?, 'EMERGENCY', ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            request.medicineCode,
            medicine_name,
            request.quantity,
            medicine['unit'],
            request.dispensedBy,
            request.emergencyReason,
            request.patientRefId,
            request.patientName,
            request.stationCode
        ))

        dispense_id = cursor.lastrowid

        # 4. 立即記錄庫存消耗事件
        cursor.execute("""
            INSERT INTO inventory_events (
                event_type, item_code, quantity, remarks, station_id, operator, timestamp
            ) VALUES ('CONSUME', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            request.medicineCode,
            request.quantity,
            f"🚨 緊急領用: {request.emergencyReason}",
            request.stationCode,
            request.dispensedBy
        ))

        # 5. 如果是 medicines 表的藥品，更新 current_stock
        cursor.execute("SELECT medicine_code FROM medicines WHERE medicine_code = ?", (request.medicineCode,))
        if cursor.fetchone():
            cursor.execute("""
                UPDATE medicines
                SET current_stock = current_stock - ?
                WHERE medicine_code = ?
            """, (request.quantity, request.medicineCode))

        conn.commit()

        new_stock = current_stock - request.quantity
        logger.info(f"🚨 緊急領用成功: 藥品={medicine_name}, 數量={request.quantity}, 領用人={request.dispensedBy}, 原因={request.emergencyReason}")

        return {
            "success": True,
            "message": "緊急領用成功，已立即扣除庫存",
            "dispense_id": dispense_id,
            "medicine_name": medicine_name,
            "quantity": request.quantity,
            "unit": medicine['unit'],
            "remaining_stock": new_stock,
            "warning": "⚠️ 此為緊急領用，請藥師上班後盡快確認"
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"緊急領用失敗: {e}")
        raise HTTPException(status_code=500, detail=f"緊急領用失敗: {str(e)}")
    finally:
        conn.close()


@app.post("/api/pharmacy/dispense/normal", status_code=201)
async def normal_dispense(request: NormalDispenseRequest):
    """
    正常領用藥品 (需藥師審核)
    - 建立 PENDING 狀態記錄
    - 不立即扣庫存
    - 等待藥師 PIN 碼審核
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 檢查藥品/物品是否存在 (先查 medicines 表，再查 items 表)
        # 先查 medicines 表
        cursor.execute("""
            SELECT medicine_code, generic_name, brand_name, unit, current_stock
            FROM medicines
            WHERE medicine_code = ? AND is_active = 1
        """, (request.medicineCode,))

        medicine = cursor.fetchone()

        # 如果不在 medicines 表，查 items 表
        if not medicine:
            cursor.execute("""
                SELECT code as medicine_code, name as generic_name, name as brand_name, unit,
                       (SELECT SUM(CASE WHEN event_type='RECEIVE' THEN quantity ELSE -quantity END)
                        FROM inventory_events WHERE item_code = code) as current_stock
                FROM items
                WHERE code = ?
            """, (request.medicineCode,))
            medicine = cursor.fetchone()

        if not medicine:
            raise HTTPException(status_code=404, detail=f"藥品/物品代碼 {request.medicineCode} 不存在")

        current_stock = medicine['current_stock'] or 0

        # 預檢查庫存
        if current_stock < request.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"庫存不足！當前庫存: {current_stock} {medicine['unit']}, 需要: {request.quantity} {medicine['unit']}"
            )

        # 建立待審核領用記錄
        medicine_name = medicine['brand_name'] or medicine['generic_name']

        cursor.execute("""
            INSERT INTO dispense_records (
                medicine_code, medicine_name, quantity, unit,
                dispensed_by, status,
                patient_ref_id, patient_name, prescription_id,
                station_code, created_at
            ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            request.medicineCode,
            medicine_name,
            request.quantity,
            medicine['unit'],
            request.dispensedBy,
            request.patientRefId,
            request.patientName,
            request.prescriptionId,
            request.stationCode
        ))

        dispense_id = cursor.lastrowid
        conn.commit()

        logger.info(f"📋 正常領用請求建立: 藥品={medicine_name}, 數量={request.quantity}, 領用人={request.dispensedBy}")

        return {
            "success": True,
            "message": "領用請求已建立，等待藥師審核",
            "dispense_id": dispense_id,
            "status": "PENDING",
            "medicine_name": medicine_name,
            "quantity": request.quantity,
            "unit": medicine['unit']
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"建立領用請求失敗: {e}")
        raise HTTPException(status_code=500, detail=f"建立領用請求失敗: {str(e)}")
    finally:
        conn.close()


@app.post("/api/pharmacy/dispense/approve")
async def approve_dispense(request: DispenseApprovalRequest):
    """
    藥師審核領用 (使用 PIN 碼)
    - 審核 PENDING 記錄 → 扣庫存
    - 確認 EMERGENCY 記錄 → 不扣庫存(已扣過)
    """
    # TODO: PIN 碼應該從配置或資料庫讀取
    PHARMACIST_PIN = "1234"  # 暫時寫死

    if request.pinCode != PHARMACIST_PIN:
        raise HTTPException(status_code=401, detail="PIN 碼錯誤，拒絕審核")

    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 查詢領用記錄
        cursor.execute("SELECT * FROM dispense_records WHERE id = ?", (request.dispenseId,))
        record = cursor.fetchone()

        if not record:
            raise HTTPException(status_code=404, detail=f"領用記錄 ID {request.dispenseId} 不存在")

        if record['status'] == 'APPROVED':
            raise HTTPException(status_code=400, detail="此領用記錄已經審核過了")

        # 如果是 PENDING，需要扣庫存
        if record['status'] == 'PENDING':
            # 先查 medicines 表
            cursor.execute("""
                SELECT current_stock FROM medicines
                WHERE medicine_code = ? AND is_active = 1
            """, (record['medicine_code'],))

            med_result = cursor.fetchone()

            if med_result:
                # 是 medicines 表的藥品
                current_stock = med_result['current_stock'] or 0
            else:
                # 是 items 表的物品
                cursor.execute("""
                    SELECT (SELECT SUM(CASE WHEN event_type='RECEIVE' THEN quantity ELSE -quantity END)
                            FROM inventory_events WHERE item_code = ?) as current_stock
                """, (record['medicine_code'],))
                result = cursor.fetchone()
                current_stock = result['current_stock'] or 0

            if current_stock < record['quantity']:
                raise HTTPException(status_code=400, detail=f"庫存不足！當前庫存: {current_stock}")

            # 記錄庫存消耗
            cursor.execute("""
                INSERT INTO inventory_events (
                    event_type, item_code, quantity, remarks, station_id, operator, timestamp
                ) VALUES ('CONSUME', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                record['medicine_code'],
                record['quantity'],
                f"正常領用 (藥師審核)",
                record['station_code'],
                request.approvedBy
            ))

            # 如果是 medicines 表的藥品，更新 current_stock
            if med_result:
                cursor.execute("""
                    UPDATE medicines
                    SET current_stock = current_stock - ?
                    WHERE medicine_code = ?
                """, (record['quantity'], record['medicine_code']))

        # 更新領用記錄為 APPROVED
        cursor.execute("""
            UPDATE dispense_records
            SET status = 'APPROVED',
                approved_by = ?,
                approved_at = CURRENT_TIMESTAMP,
                pharmacist_notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (request.approvedBy, request.pharmacistNotes, request.dispenseId))

        conn.commit()

        status_desc = "緊急領用已確認" if record['status'] == 'EMERGENCY' else "領用審核通過"
        logger.info(f"✅ {status_desc}: ID={request.dispenseId}, 審核人={request.approvedBy}")

        return {
            "success": True,
            "message": status_desc,
            "dispense_id": request.dispenseId,
            "approved_by": request.approvedBy,
            "approved_at": datetime.now().isoformat()
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"審核領用失敗: {e}")
        raise HTTPException(status_code=500, detail=f"審核領用失敗: {str(e)}")
    finally:
        conn.close()


@app.get("/api/pharmacy/dispense/pending")
async def get_pending_dispenses(
    status: Optional[str] = Query(None, description="狀態篩選: PENDING | EMERGENCY | APPROVED"),
    limit: int = Query(50, ge=1, le=200, description="最大回傳筆數")
):
    """
    查詢待處理領用記錄
    - 預設顯示所有 PENDING 和 EMERGENCY
    - 藥師可以看到需要確認的緊急領用
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        if status:
            cursor.execute("""
                SELECT
                    dr.*,
                    CAST((julianday('now') - julianday(dr.created_at)) * 24 AS INTEGER) AS hours_pending
                FROM dispense_records dr
                WHERE dr.status = ?
                ORDER BY dr.created_at ASC
                LIMIT ?
            """, (status, limit))
        else:
            # 預設顯示 PENDING 和 EMERGENCY
            cursor.execute("""
                SELECT
                    dr.*,
                    CAST((julianday('now') - julianday(dr.created_at)) * 24 AS INTEGER) AS hours_pending
                FROM dispense_records dr
                WHERE dr.status IN ('PENDING', 'EMERGENCY')
                ORDER BY dr.created_at ASC
                LIMIT ?
            """, (limit,))

        records = [dict(row) for row in cursor.fetchall()]

        return {
            "records": records,
            "count": len(records),
            "emergency_count": sum(1 for r in records if r['status'] == 'EMERGENCY'),
            "pending_count": sum(1 for r in records if r['status'] == 'PENDING')
        }

    except Exception as e:
        logger.error(f"查詢待處理領用失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/pharmacy/dispense/history")
async def get_dispense_history(
    start_date: Optional[str] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="結束日期 YYYY-MM-DD"),
    medicine_code: Optional[str] = Query(None, description="藥品代碼"),
    status: Optional[str] = Query(None, description="狀態"),
    limit: int = Query(100, ge=1, le=500, description="最大回傳筆數")
):
    """查詢領用歷史記錄"""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        query = "SELECT * FROM dispense_records WHERE 1=1"
        params = []

        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date)

        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date)

        if medicine_code:
            query += " AND medicine_code = ?"
            params.append(medicine_code)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        records = [dict(row) for row in cursor.fetchall()]

        return {
            "records": records,
            "count": len(records)
        }

    except Exception as e:
        logger.error(f"查詢領用歷史失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================================
# Pharmacy Dispatch API (藥局撥發 v1.1)
# ============================================================================

class DispatchItemRequest(BaseModel):
    medicine_code: str
    quantity: int

class CreateDispatchRequest(BaseModel):
    items: List[DispatchItemRequest]
    target_station_id: Optional[str] = None
    target_station_name: Optional[str] = None
    notes: Optional[str] = None
    created_by: str

class ReserveDispatchRequest(BaseModel):
    reserved_by: str

class ConfirmDispatchRequest(BaseModel):
    dispatched_by: str

class IngestReceiptRequest(BaseModel):
    receipt_data: str


def generate_dispatch_id() -> str:
    """Generate unique dispatch ID"""
    today = datetime.now().strftime('%Y%m%d')
    conn = sqlite3.connect(config.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM pharmacy_dispatch_orders WHERE dispatch_id LIKE ?",
        (f"DISP-{today}-%",)
    )
    count = cursor.fetchone()[0] + 1
    conn.close()
    return f"DISP-{today}-{count:03d}"


@app.post("/api/pharmacy/dispatch", status_code=201)
async def create_dispatch(request: CreateDispatchRequest):
    """
    建立撥發單 (DRAFT)
    - 驗證管制藥是否有 target_station_id
    - 不扣庫存，只建立草稿
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        dispatch_id = generate_dispatch_id()
        now = datetime.now().isoformat()
        total_items = len(request.items)
        total_quantity = sum(item.quantity for item in request.items)
        has_controlled = False

        # 驗證藥品並收集資訊 (使用 items + inventory_events 系統)
        dispatch_items = []
        for item in request.items:
            # 從 items 表取得藥品資訊
            cursor.execute(
                "SELECT item_code, item_name, unit, category FROM items WHERE item_code = ?",
                (item.medicine_code,)
            )
            med_item = cursor.fetchone()
            if not med_item:
                raise HTTPException(status_code=404, detail=f"找不到藥品: {item.medicine_code}")

            # 計算庫存 (從 inventory_events)
            cursor.execute("""
                SELECT COALESCE(SUM(CASE
                    WHEN event_type = 'RECEIVE' THEN quantity
                    WHEN event_type = 'CONSUME' THEN -quantity
                    WHEN event_type = 'DISPATCH_RESERVE' THEN -quantity
                    WHEN event_type = 'DISPATCH_RELEASE' THEN quantity
                    ELSE 0 END), 0) as current_stock
                FROM inventory_events WHERE item_code = ?
            """, (item.medicine_code,))
            stock_row = cursor.fetchone()
            current_stock = stock_row['current_stock'] if stock_row else 0

            # 檢查是否為管制藥 (從 medicines 資料表查詢)
            cursor.execute("""
                SELECT is_controlled_drug, controlled_level
                FROM medicines
                WHERE medicine_code = ?
            """, (item.medicine_code,))
            med_info = cursor.fetchone()
            is_controlled = bool(med_info and med_info[0]) if med_info else False
            # 備用: 如果資料庫沒有，檢查藥品代碼是否包含 CTRL
            if not is_controlled:
                is_controlled = 'CTRL' in item.medicine_code.upper()

            available = current_stock
            if item.quantity > available:
                raise HTTPException(
                    status_code=409,
                    detail=f"庫存不足: {med_item['item_name']} 可用 {available}, 需求 {item.quantity}"
                )

            if is_controlled:
                has_controlled = True

            dispatch_items.append({
                'medicine_code': med_item['item_code'],
                'medicine_name': med_item['item_name'],
                'quantity': item.quantity,
                'unit': med_item['unit'] or 'EA',
                'is_controlled': is_controlled
            })

        # 管制藥必須有 target_station_id
        if has_controlled and not request.target_station_id:
            raise HTTPException(
                status_code=400,
                detail="含管制藥品必須指定目標站點 (target_station_id)"
            )

        target_unbound = 1 if not request.target_station_id else 0

        # 建立撥發單
        cursor.execute("""
            INSERT INTO pharmacy_dispatch_orders (
                dispatch_id, created_at, created_by,
                target_station_id, target_station_name, target_unbound,
                status, total_items, total_quantity, has_controlled, notes
            ) VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
        """, (
            dispatch_id, now, request.created_by,
            request.target_station_id, request.target_station_name, target_unbound,
            total_items, total_quantity, 1 if has_controlled else 0, request.notes
        ))

        # 建立撥發明細
        for item in dispatch_items:
            cursor.execute("""
                INSERT INTO pharmacy_dispatch_items (
                    dispatch_id, medicine_code, medicine_name, quantity, unit, is_controlled
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                dispatch_id, item['medicine_code'], item['medicine_name'],
                item['quantity'], item['unit'], item['is_controlled']
            ))

        conn.commit()

        return {
            "success": True,
            "dispatch_id": dispatch_id,
            "status": "DRAFT",
            "total_items": total_items,
            "total_quantity": total_quantity,
            "has_controlled": has_controlled,
            "message": "撥發單已建立 (草稿)"
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"建立撥發單失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/pharmacy/dispatch/{dispatch_id}/reserve")
async def reserve_dispatch(dispatch_id: str, request: ReserveDispatchRequest):
    """
    保留庫存 (DRAFT → RESERVED)
    - 檢查可用庫存
    - 增加 reserved_qty
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 檢查撥發單狀態
        cursor.execute("SELECT * FROM pharmacy_dispatch_orders WHERE dispatch_id = ?", (dispatch_id,))
        dispatch = cursor.fetchone()
        if not dispatch:
            raise HTTPException(status_code=404, detail="找不到撥發單")

        if dispatch['status'] == 'RESERVED':
            return {"success": True, "dispatch_id": dispatch_id, "status": "RESERVED", "message": "庫存已保留 (冪等)"}

        if dispatch['status'] != 'DRAFT':
            raise HTTPException(status_code=400, detail=f"狀態 {dispatch['status']} 不允許保留")

        # 取得撥發明細
        cursor.execute("SELECT * FROM pharmacy_dispatch_items WHERE dispatch_id = ?", (dispatch_id,))
        items = cursor.fetchall()

        # 檢查並保留庫存 (使用 inventory_events)
        shortages = []
        for item in items:
            # 計算現有庫存
            cursor.execute("""
                SELECT COALESCE(SUM(CASE
                    WHEN event_type = 'RECEIVE' THEN quantity
                    WHEN event_type = 'CONSUME' THEN -quantity
                    WHEN event_type = 'DISPATCH_RESERVE' THEN -quantity
                    WHEN event_type = 'DISPATCH_RELEASE' THEN quantity
                    ELSE 0 END), 0) as current_stock
                FROM inventory_events WHERE item_code = ?
            """, (item['medicine_code'],))
            stock_row = cursor.fetchone()
            available = stock_row['current_stock'] if stock_row else 0

            if item['quantity'] > available:
                shortages.append({
                    "code": item['medicine_code'],
                    "name": item['medicine_name'],
                    "requested": item['quantity'],
                    "available": available,
                    "shortage": item['quantity'] - available
                })

        if shortages:
            raise HTTPException(status_code=409, detail={
                "error": "INSUFFICIENT_STOCK",
                "shortages": shortages,
                "message": "庫存不足，無法保留"
            })

        # 執行保留 (建立 DISPATCH_RESERVE 事件)
        for item in items:
            cursor.execute("""
                INSERT INTO inventory_events (item_code, event_type, quantity, batch_number, remarks, station_id, operator)
                VALUES (?, 'DISPATCH_RESERVE', ?, ?, ?, ?, ?)
            """, (item['medicine_code'], item['quantity'], dispatch_id, f"撥發保留: {dispatch_id}", config.STATION_ID, request.reserved_by))
            cursor.execute(
                "UPDATE pharmacy_dispatch_items SET reserved_qty = ? WHERE dispatch_id = ? AND medicine_code = ?",
                (item['quantity'], dispatch_id, item['medicine_code'])
            )

        # 更新撥發單狀態
        now = datetime.now().isoformat()
        cursor.execute(
            "UPDATE pharmacy_dispatch_orders SET status = 'RESERVED', reserved_at = ? WHERE dispatch_id = ?",
            (now, dispatch_id)
        )

        conn.commit()

        return {
            "success": True,
            "dispatch_id": dispatch_id,
            "status": "RESERVED",
            "reserved_at": now,
            "message": "庫存已保留"
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"保留庫存失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/pharmacy/dispatch/{dispatch_id}/qr")
async def get_dispatch_qr(dispatch_id: str):
    """
    取得撥發單 QR Code (XIR1 格式)
    - 狀態必須是 RESERVED 或 DISPATCHED
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM pharmacy_dispatch_orders WHERE dispatch_id = ?", (dispatch_id,))
        dispatch = cursor.fetchone()
        if not dispatch:
            raise HTTPException(status_code=404, detail="找不到撥發單")

        if dispatch['status'] not in ('RESERVED', 'DISPATCHED'):
            raise HTTPException(status_code=400, detail=f"狀態 {dispatch['status']} 無法產生 QR")

        cursor.execute("SELECT * FROM pharmacy_dispatch_items WHERE dispatch_id = ?", (dispatch_id,))
        items = cursor.fetchall()

        # 建立 MED_DISPATCH payload
        payload = {
            "type": "MED_DISPATCH",
            "v": "1.1",
            "dispatch_id": dispatch_id,
            "source_station": config.get_station_id(),
            "target_station": dispatch['target_station_id'],
            "target_unbound": bool(dispatch['target_unbound']),
            "items": [
                {
                    "code": item['medicine_code'],
                    "name": item['medicine_name'],
                    "qty": item['quantity'],
                    "unit": item['unit'],
                    "controlled": bool(item['is_controlled'])
                }
                for item in items
            ],
            "total_items": dispatch['total_items'],
            "total_qty": dispatch['total_quantity'],
            "has_controlled": bool(dispatch['has_controlled']),
            "ts": int(datetime.now().timestamp()),
            "nonce": secrets.token_hex(12)
        }

        # TODO: Add Ed25519 signature
        # payload['signature'] = sign_payload(payload)

        # Generate XIR1 chunks
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        payload_b64 = base64.b64encode(payload_json.encode('utf-8')).decode('ascii')

        # CRC32 checksum
        checksum = format(binascii.crc32(payload_b64.encode()) & 0xFFFFFFFF, '08x')

        # Single chunk for now (max 800 chars)
        MAX_CHUNK_SIZE = 700  # Leave room for protocol overhead
        chunks = []
        if len(payload_b64) <= MAX_CHUNK_SIZE:
            chunks = [f"XIR1|MF|1/1|{payload_b64}|{checksum}"]
        else:
            # Multi-chunk
            total = (len(payload_b64) + MAX_CHUNK_SIZE - 1) // MAX_CHUNK_SIZE
            for i in range(total):
                start = i * MAX_CHUNK_SIZE
                end = min(start + MAX_CHUNK_SIZE, len(payload_b64))
                chunk_data = payload_b64[start:end]
                chunk_crc = format(binascii.crc32(chunk_data.encode()) & 0xFFFFFFFF, '08x')
                chunks.append(f"XIR1|MF|{i+1}/{total}|{chunk_data}|{chunk_crc}")

        # Update qr_chunks count
        cursor.execute(
            "UPDATE pharmacy_dispatch_orders SET qr_chunks = ? WHERE dispatch_id = ?",
            (len(chunks), dispatch_id)
        )
        conn.commit()

        return {
            "dispatch_id": dispatch_id,
            "status": dispatch['status'],
            "chunks": len(chunks),
            "qr_data": chunks,
            "payload": payload  # For debugging
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"產生 QR 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/pharmacy/dispatch/{dispatch_id}/confirm")
async def confirm_dispatch(dispatch_id: str, request: ConfirmDispatchRequest):
    """
    確認發出 (RESERVED → DISPATCHED)
    - 釋放 reserved_qty
    - 扣除 current_stock
    - 冪等操作
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM pharmacy_dispatch_orders WHERE dispatch_id = ?", (dispatch_id,))
        dispatch = cursor.fetchone()
        if not dispatch:
            raise HTTPException(status_code=404, detail="找不到撥發單")

        # 冪等: 已經是 DISPATCHED 直接返回成功
        if dispatch['status'] == 'DISPATCHED':
            return {
                "success": True,
                "dispatch_id": dispatch_id,
                "status": "DISPATCHED",
                "dispatched_at": dispatch['dispatched_at'],
                "message": "已確認發出 (冪等)"
            }

        if dispatch['status'] != 'RESERVED':
            raise HTTPException(status_code=400, detail=f"狀態 {dispatch['status']} 不允許確認發出")

        cursor.execute("SELECT * FROM pharmacy_dispatch_items WHERE dispatch_id = ?", (dispatch_id,))
        items = cursor.fetchall()

        # 注意: 使用 inventory_events 系統，DISPATCH_RESERVE 事件已經扣除可用庫存
        # 確認發出時不需要額外操作，只更新狀態即可
        # (DISPATCH_RESERVE 已經使該數量從 available 中扣除)

        # 更新撥發單狀態
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE pharmacy_dispatch_orders SET
                status = 'DISPATCHED',
                dispatched_at = ?,
                dispatched_by = ?
            WHERE dispatch_id = ?
        """, (now, request.dispatched_by, dispatch_id))

        conn.commit()

        return {
            "success": True,
            "dispatch_id": dispatch_id,
            "status": "DISPATCHED",
            "dispatched_at": now,
            "message": "已確認發出，庫存已扣除"
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"確認發出失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/pharmacy/dispatch/receipt")
async def ingest_receipt(request: IngestReceiptRequest):
    """
    匯入收貨回執 (DISPATCHED → RECEIVED)
    - 解析 XIR1 格式回執
    - 驗證簽章
    - 冪等操作
    """
    try:
        # Parse XIR1 receipt
        receipt_data = request.receipt_data.strip()

        if not receipt_data.startswith('XIR1|'):
            raise HTTPException(status_code=400, detail="無效的 XIR1 格式")

        parts = receipt_data.split('|')
        if len(parts) != 5:
            raise HTTPException(status_code=400, detail="XIR1 格式錯誤")

        _, packet_type, seq_total, payload_b64, checksum = parts

        # Verify CRC32
        expected_crc = format(binascii.crc32(payload_b64.encode()) & 0xFFFFFFFF, '08x')
        if checksum != expected_crc:
            raise HTTPException(status_code=400, detail="CRC32 校驗失敗")

        # Decode payload
        try:
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            receipt = json.loads(payload_json)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"解碼失敗: {e}")

        if receipt.get('type') != 'MED_RECEIPT':
            raise HTTPException(status_code=400, detail=f"非收貨回執: {receipt.get('type')}")

        dispatch_id = receipt.get('dispatch_id')
        if not dispatch_id:
            raise HTTPException(status_code=400, detail="缺少 dispatch_id")

        # TODO: Verify signature

        # Update dispatch order
        conn = sqlite3.connect(config.DATABASE_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT status FROM pharmacy_dispatch_orders WHERE dispatch_id = ?", (dispatch_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="找不到撥發單")

            # 冪等
            if row[0] == 'RECEIVED':
                return {
                    "success": True,
                    "dispatch_id": dispatch_id,
                    "status": "RECEIVED",
                    "message": "回執已匯入 (冪等)"
                }

            if row[0] != 'DISPATCHED':
                raise HTTPException(status_code=400, detail=f"狀態 {row[0]} 不允許匯入回執")

            now = datetime.now().isoformat()
            cursor.execute("""
                UPDATE pharmacy_dispatch_orders SET
                    status = 'RECEIVED',
                    received_at = ?,
                    received_by = ?,
                    receiver_station_id = ?,
                    receipt_signature = ?
                WHERE dispatch_id = ?
            """, (
                now,
                receipt.get('received_by'),
                receipt.get('receiver_station'),
                receipt.get('signature'),
                dispatch_id
            ))
            conn.commit()

            return {
                "success": True,
                "dispatch_id": dispatch_id,
                "status": "RECEIVED",
                "received_at": now,
                "received_by": receipt.get('received_by'),
                "receiver_station": receipt.get('receiver_station'),
                "message": "收貨回執已確認"
            }

        finally:
            conn.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"匯入回執失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pharmacy/dispatch")
async def list_dispatches(
    status: Optional[str] = Query(None, description="狀態篩選"),
    limit: int = Query(50, ge=1, le=200)
):
    """列出撥發單"""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        if status:
            cursor.execute(
                "SELECT * FROM pharmacy_dispatch_orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM pharmacy_dispatch_orders ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )

        dispatches = [dict(row) for row in cursor.fetchall()]

        # 加入明細
        for d in dispatches:
            cursor.execute("SELECT * FROM pharmacy_dispatch_items WHERE dispatch_id = ?", (d['dispatch_id'],))
            d['items'] = [dict(row) for row in cursor.fetchall()]

        return {
            "dispatches": dispatches,
            "count": len(dispatches)
        }

    except Exception as e:
        logger.error(f"列出撥發單失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.delete("/api/pharmacy/dispatch/{dispatch_id}")
async def cancel_dispatch(dispatch_id: str):
    """
    取消撥發單
    - 只能取消 DRAFT 或 RESERVED
    - RESERVED 需釋放保留庫存
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM pharmacy_dispatch_orders WHERE dispatch_id = ?", (dispatch_id,))
        dispatch = cursor.fetchone()
        if not dispatch:
            raise HTTPException(status_code=404, detail="找不到撥發單")

        if dispatch['status'] not in ('DRAFT', 'RESERVED'):
            raise HTTPException(status_code=400, detail=f"狀態 {dispatch['status']} 不允許取消")

        # 如果是 RESERVED，釋放保留 (建立 DISPATCH_RELEASE 事件)
        if dispatch['status'] == 'RESERVED':
            cursor.execute("SELECT * FROM pharmacy_dispatch_items WHERE dispatch_id = ?", (dispatch_id,))
            items = cursor.fetchall()
            for item in items:
                cursor.execute("""
                    INSERT INTO inventory_events (item_code, event_type, quantity, batch_number, remarks, station_id, operator)
                    VALUES (?, 'DISPATCH_RELEASE', ?, ?, ?, ?, 'SYSTEM')
                """, (item['medicine_code'], item['reserved_qty'] or item['quantity'], dispatch_id, f"撥發取消釋放: {dispatch_id}", config.STATION_ID))

        # 更新狀態
        cursor.execute(
            "UPDATE pharmacy_dispatch_orders SET status = 'CANCELLED' WHERE dispatch_id = ?",
            (dispatch_id,)
        )

        conn.commit()

        return {
            "success": True,
            "dispatch_id": dispatch_id,
            "status": "CANCELLED",
            "message": "撥發單已取消" + ("，保留庫存已釋放" if dispatch['status'] == 'RESERVED' else "")
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"取消撥發單失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ========== 庫存事件查詢與匯出 API (新增) ==========

@app.get("/api/inventory/events")
async def get_inventory_events(
    event_type: Optional[str] = Query(None, description="事件類型 RECEIVE/CONSUME"),
    start_date: Optional[str] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="結束日期 YYYY-MM-DD"),
    item_code: Optional[str] = Query(None, description="物品代碼(模糊搜尋)"),
    limit: int = Query(100, ge=1, le=1000, description="最大回傳筆數")
):
    """查詢庫存事件記錄(進貨/消耗)"""
    try:
        events = db.get_inventory_events(event_type, start_date, end_date, item_code, limit)
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error(f"查詢庫存事件失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inventory/export/csv")
async def export_inventory_csv():
    """匯出庫存清單 CSV"""
    try:
        csv_content = db.export_inventory_csv()

        filename = f"inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv;charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"匯出庫存 CSV 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inventory/export/json")
async def export_inventory_json():
    """匯出庫存清單 JSON"""
    try:
        items = db.get_inventory_items()

        filename = f"inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        return StreamingResponse(
            iter([json.dumps(items, ensure_ascii=False, indent=2)]),
            media_type="application/json;charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"匯出庫存 JSON 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inventory/events/export/csv")
async def export_inventory_events_csv(
    event_type: Optional[str] = Query(None, description="事件類型 RECEIVE/CONSUME"),
    start_date: Optional[str] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="結束日期 YYYY-MM-DD")
):
    """匯出庫存事件記錄 CSV"""
    try:
        csv_content = db.export_inventory_events_csv(event_type, start_date, end_date)

        filename = f"inventory_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv;charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"匯出事件記錄 CSV 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 緊急功能 API (v1.4.5新增)
# ============================================================================

@app.get("/api/emergency/quick-backup")
async def emergency_quick_backup():
    """
    緊急快速備份 - 直接下載資料庫檔案

    戰時緊急撤離使用：最快速的資料保全方式
    """
    try:
        db_path = Path(config.DATABASE_PATH)

        if not db_path.exists():
            raise HTTPException(status_code=404, detail="資料庫檔案不存在")

        # 生成檔名: {STATION_ID}_{TIMESTAMP}.db
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{config.STATION_ID}_{timestamp}.db"

        logger.info(f"緊急快速備份: {filename}")

        return FileResponse(
            path=str(db_path),
            media_type="application/octet-stream",
            filename=filename
        )

    except Exception as e:
        logger.error(f"快速備份失敗: {e}")
        raise HTTPException(status_code=500, detail=f"備份失敗: {str(e)}")


@app.get("/api/emergency/download-all")
async def emergency_download_all():
    """
    緊急完整備份 - 生成包含所有資料的ZIP包

    包含內容：
    - database/: 完整資料庫
    - exports/: CSV + JSON 分類資料
    - config/: 站點設定檔
    - README.txt: 使用說明
    - manifest.json: 檔案清單與檢查碼
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"emergency_backup_{config.STATION_ID}_{timestamp}.zip"
        zip_path = Path("exports") / zip_filename

        # 確保exports目錄存在
        zip_path.parent.mkdir(exist_ok=True)

        logger.info(f"開始生成完整備份包: {zip_filename}")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. 加入資料庫
            db_path = Path(config.DATABASE_PATH)
            if db_path.exists():
                zipf.write(db_path, f"database/{db_path.name}")
                logger.info("✓ 資料庫已加入")

            # 2. 導出CSV資料
            exports_dir = Path("exports/temp")
            exports_dir.mkdir(exist_ok=True, parents=True)

            # 初始化變數
            inventory_data = []
            blood_data = []
            equipment = []

            try:
                # 導出庫存清單
                inventory_data = db.get_inventory_items()
                if inventory_data:
                    csv_path = exports_dir / "inventory.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=inventory_data[0].keys())
                        writer.writeheader()
                        writer.writerows([dict(item) for item in inventory_data])
                    zipf.write(csv_path, "exports/inventory.csv")
                    logger.info("✓ 庫存清單已導出")

                # 導出血袋庫存
                blood_data = db.get_blood_inventory()
                if blood_data:
                    csv_path = exports_dir / "blood_inventory.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=['blood_type', 'quantity', 'station_id'])
                        writer.writeheader()
                        writer.writerows([dict(b) for b in blood_data])
                    zipf.write(csv_path, "exports/blood_inventory.csv")
                    logger.info("✓ 血袋庫存已導出")

                # 導出設備清單
                conn = db.get_connection()
                cursor = conn.cursor()
                equipment = cursor.execute("SELECT * FROM equipment").fetchall()
                if equipment:
                    csv_path = exports_dir / "equipment.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=[desc[0] for desc in cursor.description])
                        writer.writeheader()
                        writer.writerows([dict(zip([desc[0] for desc in cursor.description], row)) for row in equipment])
                    zipf.write(csv_path, "exports/equipment.csv")
                    logger.info("✓ 設備清單已導出")

                # v1.2.8: 導出設備分項 (equipment_units)
                try:
                    units = cursor.execute("SELECT * FROM equipment_units").fetchall()
                    if units:
                        csv_path = exports_dir / "equipment_units.csv"
                        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                            writer = csv.DictWriter(f, fieldnames=[desc[0] for desc in cursor.description])
                            writer.writeheader()
                            writer.writerows([dict(zip([desc[0] for desc in cursor.description], row)) for row in units])
                        zipf.write(csv_path, "exports/equipment_units.csv")
                        logger.info("✓ 設備分項已導出")
                except Exception as e:
                    logger.warning(f"設備分項導出失敗: {e}")

                # v1.2.8: 導出檢查歷史 (equipment_check_history)
                try:
                    history = cursor.execute("SELECT * FROM equipment_check_history ORDER BY check_time DESC LIMIT 1000").fetchall()
                    if history:
                        csv_path = exports_dir / "equipment_check_history.csv"
                        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                            writer = csv.DictWriter(f, fieldnames=[desc[0] for desc in cursor.description])
                            writer.writeheader()
                            writer.writerows([dict(zip([desc[0] for desc in cursor.description], row)) for row in history])
                        zipf.write(csv_path, "exports/equipment_check_history.csv")
                        logger.info("✓ 檢查歷史已導出")
                except Exception as e:
                    logger.warning(f"檢查歷史導出失敗: {e}")

            except Exception as e:
                logger.warning(f"部分資料導出失敗: {e}")

            # 3. 加入配置文件
            config_path = Path("config/station_config.json")
            if config_path.exists():
                zipf.write(config_path, "config/station_config.json")
                logger.info("✓ 配置文件已加入")

            # 4. 生成README
            readme_content = f"""
==============================================
醫療站庫存系統 - 緊急備份包
==============================================

備份時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
站點ID: {config.STATION_ID}
系統版本: {config.VERSION}

目錄結構:
-----------------------
database/          完整資料庫檔案
exports/           CSV格式資料
  - inventory.csv           庫存清單
  - blood_inventory.csv     血袋庫存
  - equipment.csv           設備清單
  - equipment_units.csv     設備分項 (氧氣瓶充填%)
  - equipment_check_history.csv  檢查歷史記錄
config/            站點設定檔
README.txt         本說明文件
manifest.json      檔案清單與檢查碼

使用方式:
-----------------------
1. 恢復資料庫:
   將database/*.db複製到新系統的database目錄

2. 查看資料:
   使用Excel或文字編輯器開啟exports/*.csv

3. 重新部署:
   參考config/station_config.json設定新系統

緊急聯絡:
-----------------------
如有問題請聯繫系統管理員

==============================================
此為自動生成的緊急備份包
請妥善保管並定期更新
==============================================
"""
            zipf.writestr("README.txt", readme_content.encode('utf-8'))
            logger.info("✓ README已生成")

            # 5. 生成manifest
            manifest = {
                "backup_time": datetime.now().isoformat(),
                "station_id": config.STATION_ID,
                "version": config.VERSION,
                "files": {},
                "statistics": {
                    "total_items": len(inventory_data) if inventory_data else 0,
                    "total_blood_types": len(blood_data) if blood_data else 0,
                    "total_equipment": len(equipment) if equipment else 0
                }
            }

            # 計算檔案檢查碼
            for item in zipf.filelist:
                if item.filename != "manifest.json":
                    manifest["files"][item.filename] = {
                        "size": item.file_size,
                        "compressed_size": item.compress_size
                    }

            zipf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            logger.info("✓ Manifest已生成")

        # 清理臨時目錄
        if exports_dir.exists():
            shutil.rmtree(exports_dir)

        logger.info(f"完整備份包生成成功: {zip_filename}")

        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=zip_filename
        )

    except Exception as e:
        logger.error(f"完整備份失敗: {e}")
        raise HTTPException(status_code=500, detail=f"備份失敗: {str(e)}")


@app.get("/api/export/upgrade-package")
async def export_upgrade_package():
    """
    匯出升級至多站版所需的完整資料包

    用途：讓使用者從單站版升級至多站版時，匯出所有資料

    包含內容：
    - database/: 完整資料庫
    - exports/: CSV + JSON 分類資料
    - config/: 站點設定檔
    - upgrade_info.json: 升級相容性資訊
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"mirs_upgrade_{config.STATION_ID}_{timestamp}.zip"
        zip_path = Path("exports") / zip_filename

        # 確保exports目錄存在
        zip_path.parent.mkdir(exist_ok=True)

        logger.info(f"開始生成升級資料包: {zip_filename}")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. 加入資料庫
            db_path = Path(config.DATABASE_PATH)
            if db_path.exists():
                zipf.write(db_path, f"database/{db_path.name}")
                logger.info("✓ 資料庫已加入")

            # 2. 導出CSV資料
            exports_dir = Path("exports/temp_upgrade")
            exports_dir.mkdir(exist_ok=True, parents=True)

            inventory_data = []
            blood_data = []
            equipment = []
            surgery_records = []
            blood_bags = []

            try:
                conn = db.get_connection()
                cursor = conn.cursor()

                # 導出庫存清單
                inventory_data = db.get_inventory_items()
                if inventory_data:
                    csv_path = exports_dir / "items.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=inventory_data[0].keys())
                        writer.writeheader()
                        writer.writerows([dict(item) for item in inventory_data])
                    zipf.write(csv_path, "exports/items.csv")

                # 導出血袋庫存
                blood_data = db.get_blood_inventory()
                if blood_data:
                    csv_path = exports_dir / "blood_inventory.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=['blood_type', 'quantity', 'station_id'])
                        writer.writeheader()
                        writer.writerows([dict(b) for b in blood_data])
                    zipf.write(csv_path, "exports/blood_inventory.csv")

                # 導出設備清單
                equipment = cursor.execute("SELECT * FROM equipment").fetchall()
                if equipment:
                    csv_path = exports_dir / "equipment.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        cols = [desc[0] for desc in cursor.description]
                        writer = csv.DictWriter(f, fieldnames=cols)
                        writer.writeheader()
                        writer.writerows([dict(zip(cols, row)) for row in equipment])
                    zipf.write(csv_path, "exports/equipment.csv")

                # 導出處置記錄
                surgery_records = cursor.execute("SELECT * FROM surgery_records").fetchall()
                if surgery_records:
                    csv_path = exports_dir / "surgery_records.csv"
                    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        cols = [desc[0] for desc in cursor.description]
                        writer = csv.DictWriter(f, fieldnames=cols)
                        writer.writeheader()
                        writer.writerows([dict(zip(cols, row)) for row in surgery_records])
                    zipf.write(csv_path, "exports/surgery_records.csv")

                # 導出血袋明細 (v1.4.2-plus)
                try:
                    blood_bags = cursor.execute("SELECT * FROM blood_bags").fetchall()
                    if blood_bags:
                        csv_path = exports_dir / "blood_bags.csv"
                        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                            cols = [desc[0] for desc in cursor.description]
                            writer = csv.DictWriter(f, fieldnames=cols)
                            writer.writeheader()
                            writer.writerows([dict(zip(cols, row)) for row in blood_bags])
                        zipf.write(csv_path, "exports/blood_bags.csv")
                except:
                    pass  # 舊版本可能沒有這張表

                # 導出領藥記錄
                try:
                    dispense_records = cursor.execute("SELECT * FROM dispense_records").fetchall()
                    if dispense_records:
                        csv_path = exports_dir / "dispense_records.csv"
                        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                            cols = [desc[0] for desc in cursor.description]
                            writer = csv.DictWriter(f, fieldnames=cols)
                            writer.writeheader()
                            writer.writerows([dict(zip(cols, row)) for row in dispense_records])
                        zipf.write(csv_path, "exports/dispense_records.csv")
                except:
                    pass

            except Exception as e:
                logger.warning(f"部分資料導出失敗: {e}")

            # 3. 加入配置文件
            config_path = Path("config/station_config.json")
            if config_path.exists():
                zipf.write(config_path, "config/station_config.json")

            # 4. 生成升級資訊
            upgrade_info = {
                "export_time": datetime.now().isoformat(),
                "source_version": config.VERSION,
                "source_station_id": config.STATION_ID,
                "target_version": "2.0",
                "compatibility": {
                    "min_target_version": "2.0",
                    "export_format": "v1"
                },
                "statistics": {
                    "total_items": len(inventory_data) if inventory_data else 0,
                    "total_blood_types": len(blood_data) if blood_data else 0,
                    "total_equipment": len(equipment) if equipment else 0,
                    "total_surgery_records": len(surgery_records) if surgery_records else 0,
                    "total_blood_bags": len(blood_bags) if blood_bags else 0
                },
                "tables_exported": [
                    "items", "blood_inventory", "equipment",
                    "surgery_records", "blood_bags", "dispense_records"
                ]
            }
            zipf.writestr("upgrade_info.json", json.dumps(upgrade_info, ensure_ascii=False, indent=2))

            # 5. 生成 README
            readme_content = f"""
================================================
MIRS 升級資料包 - 單站版 → 多站版
================================================

匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
來源站點: {config.STATION_ID}
來源版本: v{config.VERSION}
目標版本: v2.0 Multi-Station

目錄結構:
------------------------------------------------
database/           完整資料庫檔案
exports/            CSV格式資料
  - items.csv           物品清單
  - blood_inventory.csv 血袋庫存
  - equipment.csv       設備清單
  - surgery_records.csv 處置記錄
  - blood_bags.csv      血袋明細
  - dispense_records.csv 領藥記錄
config/             站點設定檔
upgrade_info.json   升級相容性資訊
README.txt          本說明文件

升級步驟:
------------------------------------------------
1. 安裝 MIRS v2.0 Multi-Station
2. 在多站版系統中選擇「匯入資料」
3. 上傳此 ZIP 檔案
4. 輸入授權碼完成升級
5. 驗證資料完整性

注意事項:
------------------------------------------------
- 此檔案包含敏感資料，請妥善保管
- 建議升級前先備份多站版資料庫
- 匯入時會覆蓋多站版現有資料

技術支援:
------------------------------------------------
Email: tom@denovortho.com
GitHub: https://github.com/cutemo0953/MIRS_v2.0_multi-station

================================================
De Novo Orthopedics Inc. © 2024
================================================
"""
            zipf.writestr("README.txt", readme_content.encode('utf-8'))

        # 清理臨時目錄
        if exports_dir.exists():
            shutil.rmtree(exports_dir)

        logger.info(f"升級資料包生成成功: {zip_filename}")

        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=zip_filename
        )

    except Exception as e:
        logger.error(f"升級資料包生成失敗: {e}")
        raise HTTPException(status_code=500, detail=f"匯出失敗: {str(e)}")


@app.get("/api/emergency/info")
async def get_emergency_info():
    """取得緊急資訊(用於QR Code掃描後顯示)"""
    try:
        stats = db.get_stats()
        blood_inventory = db.get_blood_inventory()
        equipment = db.get_equipment_status()

        total_blood = sum(b['quantity'] for b in blood_inventory)
        equipment_alerts = sum(1 for e in equipment if e['status'] not in ['NORMAL', 'UNCHECKED'])

        return {
            "station_id": config.STATION_ID,
            "timestamp": datetime.now().isoformat(),
            "version": config.VERSION,
            "stats": {
                "total_items": stats.get('total_items', 0),
                "low_stock_items": stats.get('low_stock_items', 0),
                "total_blood_units": total_blood,
                "equipment_alerts": equipment_alerts
            },
            "blood_inventory": blood_inventory,
            "equipment_status": [
                {"id": e['id'], "name": e['name'], "status": e['status']}
                for e in equipment
            ]
        }
    except Exception as e:
        logger.error(f"取得緊急資訊失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emergency/view")
async def view_emergency_info():
    """緊急資訊顯示頁面 (QR Code掃描後跳轉)"""
    try:
        stats = db.get_stats()
        blood_inventory = db.get_blood_inventory()
        equipment = db.get_equipment_status()

        total_blood = sum(b['quantity'] for b in blood_inventory)
        equipment_alerts = sum(1 for e in equipment if e['status'] not in ['NORMAL', 'UNCHECKED'])
        now = datetime.now()

        # 建立血袋庫存表格
        blood_rows = ""
        for b in blood_inventory:
            blood_rows += f"""
                <tr>
                    <td class="blood-type">{b['blood_type']}</td>
                    <td class="quantity">{b['quantity']} U</td>
                </tr>
            """

        # 建立設備狀態表格
        equipment_rows = ""
        for e in equipment:
            status_class = "status-normal" if e['status'] == 'NORMAL' else "status-alert"
            status_text = {
                'NORMAL': '正常',
                'WARNING': '警告',
                'CRITICAL': '嚴重',
                'UNCHECKED': '未檢查'
            }.get(e['status'], e['status'])

            equipment_rows += f"""
                <tr>
                    <td>{e['name']}</td>
                    <td class="{status_class}">{status_text}</td>
                </tr>
            """

        html_content = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>緊急資訊 - {config.STATION_ID}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Microsoft JhengHei', 'SimHei', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 30px 20px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        .station-id {{
            font-size: 20px;
            font-weight: bold;
            opacity: 0.95;
        }}
        .timestamp {{
            font-size: 14px;
            opacity: 0.85;
            margin-top: 5px;
        }}
        .content {{
            padding: 20px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 36px;
            font-weight: bold;
            margin: 10px 0;
        }}
        .stat-label {{
            font-size: 14px;
            opacity: 0.9;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        .section-title {{
            font-size: 20px;
            font-weight: bold;
            color: #333;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: bold;
            color: #333;
        }}
        .blood-type {{
            font-weight: bold;
            color: #d32f2f;
            font-size: 18px;
        }}
        .quantity {{
            font-weight: bold;
            color: #1976d2;
        }}
        .status-normal {{
            color: #2e7d32;
            font-weight: bold;
        }}
        .status-alert {{
            color: #d32f2f;
            font-weight: bold;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 14px;
            border-top: 1px solid #eee;
        }}
        .alert {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
        .alert-critical {{
            background: #f8d7da;
            border-left: 4px solid #dc3545;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏥 緊急醫療站資訊</h1>
            <div class="station-id">站點ID: {config.STATION_ID}</div>
            <div class="timestamp">更新時間: {now.strftime('%Y-%m-%d %H:%M:%S')}</div>
        </div>

        <div class="content">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">總物資項目</div>
                    <div class="stat-value">{stats.get('total_items', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">低庫存警示</div>
                    <div class="stat-value">{stats.get('low_stock_items', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">血袋庫存</div>
                    <div class="stat-value">{total_blood} U</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">設備警示</div>
                    <div class="stat-value">{equipment_alerts}</div>
                </div>
            </div>

            {f'<div class="alert alert-critical">⚠ 低庫存警示: {stats.get("low_stock_items", 0)} 項物資庫存不足</div>' if stats.get('low_stock_items', 0) > 0 else ''}
            {f'<div class="alert">⚠ 設備警示: {equipment_alerts} 個設備需要注意</div>' if equipment_alerts > 0 else ''}

            <div class="section">
                <div class="section-title">🩸 血袋庫存</div>
                <table>
                    <thead>
                        <tr>
                            <th>血型</th>
                            <th>數量</th>
                        </tr>
                    </thead>
                    <tbody>
                        {blood_rows}
                    </tbody>
                </table>
            </div>

            <div class="section">
                <div class="section-title">⚙ 設備狀態</div>
                <table>
                    <thead>
                        <tr>
                            <th>設備名稱</th>
                            <th>狀態</th>
                        </tr>
                    </thead>
                    <tbody>
                        {equipment_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="footer">
            醫療站庫存管理系統 v{config.VERSION}<br>
            此資訊由系統自動生成，僅供緊急參考使用
        </div>
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"顯示緊急資訊頁面失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/emergency/qr-code")
async def emergency_qr_code(request: Request):
    """
    生成緊急QR Code - 掃描後跳轉到資訊頁面

    QR Code內容為URL，掃描後可直接在手機上查看:
    - 站點代碼
    - 關鍵物資統計
    - 血袋庫存統計
    - 設備狀態
    """
    try:
        # 獲取請求的主機名稱 (支持手機掃描)
        # 優先使用環境變數，否則使用請求的 Host header
        host = config.BASE_URL if hasattr(config, 'BASE_URL') and config.BASE_URL else request.headers.get("host", "localhost:8000")
        protocol = "https" if request.url.scheme == "https" else "http"
        qr_url = f"{protocol}://{host}/emergency/view"

        # 生成QR Code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)

        # 生成圖片
        img = qr.make_image(fill_color="black", back_color="white")

        # 保存到BytesIO
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)

        logger.info("緊急QR Code已生成")

        # 返回圖片
        return StreamingResponse(
            img_io,
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename=emergency_qr_{config.STATION_ID}.png"}
        )

    except Exception as e:
        logger.error(f"QR Code生成失敗: {e}")
        raise HTTPException(status_code=500, detail=f"QR Code生成失敗: {str(e)}")


# ========== 聯邦架構 - 同步封包 API (Phase 1 & 2) ==========

@app.post("/api/station/sync/generate")
async def generate_station_sync_package(request: SyncPackageGenerate):
    """
    【站點層】產生同步封包

    站點產生包含所有變更的同步封包，可用於:
    - 網路上傳到醫院層
    - 匯出為檔案供 USB 實體轉移

    參數:
    - stationId: 站點ID (e.g., HC-000000)
    - hospitalId: 所屬醫院ID (e.g., HOSP-001)
    - syncType: DELTA (增量) 或 FULL (全量)
    - sinceTimestamp: 增量同步起始時間 (可選)

    返回:
    - package_id: 封包ID
    - checksum: SHA-256 校驗碼
    - changes: 變更記錄清單
    """
    try:
        logger.info(f"開始產生同步封包: station={request.stationId}, type={request.syncType}, since={request.sinceTimestamp}")

        # 驗證參數
        if request.syncType not in ["DELTA", "FULL"]:
            logger.error(f"無效的同步類型: {request.syncType}")
            raise HTTPException(status_code=400, detail=f"無效的同步類型: {request.syncType}")

        if request.syncType == "DELTA" and not request.sinceTimestamp:
            logger.warning("增量同步未提供 sinceTimestamp，將使用全量同步")

        result = db.generate_sync_package(
            station_id=request.stationId,
            hospital_id=request.hospitalId,
            sync_type=request.syncType,
            since_timestamp=request.sinceTimestamp
        )

        logger.info(f"✓ 同步封包已產生: {result['package_id']} ({result['changes_count']} 項變更, {result['package_size']} bytes)")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"✗ 產生同步封包失敗: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"產生同步封包失敗: {str(e)}")


@app.post("/api/station/sync/import")
async def import_station_sync_package(request: SyncPackageUpload):
    """
    【站點層】匯入同步封包

    站點匯入從醫院層收到的同步封包 (通常包含其他站點的更新)

    參數:
    - stationId: 站點ID
    - packageId: 封包ID
    - changes: 變更記錄清單
    - checksum: 校驗碼

    返回:
    - changes_applied: 成功套用的變更數
    - conflicts: 衝突記錄
    """
    try:
        logger.info(f"開始匯入同步封包: package_id={request.packageId}, station={request.stationId}")

        # 驗證封包格式
        if not request.changes:
            logger.error("封包格式錯誤：changes 清單為空")
            raise HTTPException(status_code=400, detail="封包格式錯誤：變更記錄清單為空")

        if not request.packageId:
            logger.error("封包格式錯誤：缺少 packageId")
            raise HTTPException(status_code=400, detail="封包格式錯誤：缺少封包ID")

        if not request.checksum:
            logger.error("封包格式錯誤：缺少 checksum")
            raise HTTPException(status_code=400, detail="封包格式錯誤：缺少校驗碼")

        logger.info(f"準備匯入 {len(request.changes)} 筆變更")

        # 將 Pydantic 模型轉換為 dict 以支援 JSON 序列化
        changes_dict = []
        for i, change in enumerate(request.changes):
            try:
                change_dict = change.dict()
                # 驗證必要欄位
                if 'table' not in change_dict or 'operation' not in change_dict or 'data' not in change_dict:
                    logger.error(f"變更 {i+1} 格式錯誤: 缺少必要欄位")
                    raise ValueError(f"變更 {i+1} 缺少必要欄位 (table/operation/data)")

                changes_dict.append(change_dict)
                logger.debug(f"處理變更 {i+1}/{len(request.changes)}: table={change_dict.get('table')}, operation={change_dict.get('operation')}")
            except Exception as e:
                logger.error(f"處理變更 {i+1} 失敗: {str(e)}")
                logger.error(f"變更內容: {change}")
                raise

        logger.info(f"變更記錄轉換完成，共 {len(changes_dict)} 筆")

        result = db.import_sync_package(
            package_id=request.packageId,
            changes=changes_dict,
            checksum=request.checksum,
            package_type=request.packageType
        )

        if result.get('success'):
            logger.info(f"✓ 同步封包匯入成功: {request.packageId} ({result['changes_applied']} 項變更)")
            if result.get('conflicts'):
                logger.warning(f"發現 {len(result['conflicts'])} 項衝突")
        else:
            logger.error(f"✗ 同步封包匯入失敗: {result.get('error', 'Unknown error')}")

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"✗ 封包驗證失敗: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"✗ 匯入同步封包失敗: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"匯入同步封包失敗: {str(e)}")


@app.post("/api/hospital/sync/upload")
async def upload_hospital_sync(request: SyncPackageUpload):
    """
    【醫院層】接收站點同步上傳

    醫院層接收站點上傳的同步封包 (谷盺公司使用)

    參數:
    - stationId: 站點ID
    - packageId: 封包ID
    - changes: 變更記錄清單
    - checksum: 校驗碼

    返回:
    - changes_applied: 成功套用的變更數
    - response_package_id: 回傳封包ID (包含其他站點更新)
    """
    try:
        logger.info(f"醫院層接收同步上傳: station={request.stationId}, package={request.packageId}")

        # 驗證封包格式
        if not request.changes:
            logger.error("封包格式錯誤：changes 清單為空")
            raise HTTPException(status_code=400, detail="封包格式錯誤：變更記錄清單為空")

        if not request.stationId:
            logger.error("封包格式錯誤：缺少 stationId")
            raise HTTPException(status_code=400, detail="封包格式錯誤：缺少站點ID")

        if not request.packageId:
            logger.error("封包格式錯誤：缺少 packageId")
            raise HTTPException(status_code=400, detail="封包格式錯誤：缺少封包ID")

        if not request.checksum:
            logger.error("封包格式錯誤：缺少 checksum")
            raise HTTPException(status_code=400, detail="封包格式錯誤：缺少校驗碼")

        logger.info(f"準備處理來自站點 {request.stationId} 的 {len(request.changes)} 筆變更")

        # 將 Pydantic 模型轉換為 dict 以支援 JSON 序列化
        changes_dict = []
        for i, change in enumerate(request.changes):
            try:
                change_dict = change.dict()
                # 驗證必要欄位
                if 'table' not in change_dict or 'operation' not in change_dict or 'data' not in change_dict:
                    logger.error(f"變更 {i+1} 格式錯誤: 缺少必要欄位")
                    raise ValueError(f"變更 {i+1} 缺少必要欄位 (table/operation/data)")

                changes_dict.append(change_dict)
                logger.debug(f"處理變更 {i+1}/{len(request.changes)}: table={change_dict.get('table')}, operation={change_dict.get('operation')}")
            except Exception as e:
                logger.error(f"處理變更 {i+1} 失敗: {str(e)}")
                logger.error(f"變更內容: {change}")
                raise

        logger.info(f"變更記錄轉換完成，共 {len(changes_dict)} 筆")

        result = db.upload_sync_package(
            station_id=request.stationId,
            package_id=request.packageId,
            changes=changes_dict,
            checksum=request.checksum,
            package_type=request.packageType
        )

        if result.get('success'):
            logger.info(f"✓ 醫院層已接收同步: {request.stationId} - {request.packageId} ({result.get('changes_applied', 0)} 項變更)")
            if result.get('response_package_id'):
                logger.info(f"已產生回傳封包: {result['response_package_id']}")
        else:
            logger.error(f"✗ 醫院層接收同步失敗: {result.get('error', 'Unknown error')}")

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"✗ 封包驗證失敗: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"✗ 醫院層接收同步失敗: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"醫院層接收同步失敗: {str(e)}")


@app.post("/api/hospital/transfer/coordinate")
async def coordinate_hospital_transfer(request: HospitalTransferCoordinate):
    """
    【醫院層】院內調撥協調 (Phase 2)

    醫院層協調站點間物資調撥 (谷盺公司使用)

    參數:
    - hospitalId: 醫院ID
    - fromStationId: 來源站點ID
    - toStationId: 目標站點ID
    - resourceType: 資源類型 (ITEM, BLOOD, EQUIPMENT)
    - resourceId: 資源ID
    - quantity: 數量
    - operator: 操作人員
    - reason: 調撥原因

    返回:
    - transfer_id: 調撥記錄ID
    - status: 調撥狀態
    """
    try:
        # Phase 2 實作：院內調撥協調邏輯
        # 暫時返回基本資訊
        from datetime import datetime
        transfer_id = f"TRF-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        logger.info(f"院內調撥協調: {request.fromStationId} → {request.toStationId} ({request.resourceType})")

        return {
            "success": True,
            "transfer_id": transfer_id,
            "from_station_id": request.fromStationId,
            "to_station_id": request.toStationId,
            "resource_type": request.resourceType,
            "resource_id": request.resourceId,
            "quantity": request.quantity,
            "status": "PENDING_PICKUP",
            "message": f"調撥已登記，{request.toStationId} 下次同步時會收到物資記錄"
        }
    except Exception as e:
        logger.error(f"院內調撥協調失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Setup Wizard API Endpoints
# ============================================================================

class SetupInitializeRequest(BaseModel):
    """設定初始化請求"""
    profile: str  # health_center, hospital_custom, surgical_station, logistics_hub

@app.post("/api/setup/initialize")
async def initialize_setup(request: SetupInitializeRequest):
    """
    初始化資料庫 - Setup Wizard Step 2

    根據選擇的站點類型建立資料庫

    參數:
    - profile: 站點類型 (health_center, hospital_custom, surgical_station, logistics_hub)

    返回:
    - success: 是否成功
    - message: 訊息
    - profile: 使用的 profile
    - stats: 資料統計
    """
    try:
        import subprocess
        from pathlib import Path

        logger.info(f"開始初始化資料庫，Profile: {request.profile}")

        # Validate profile
        valid_profiles = ['health_center', 'hospital_custom', 'surgical_station', 'logistics_hub']
        if request.profile not in valid_profiles:
            raise HTTPException(
                status_code=400,
                detail=f"無效的 profile: {request.profile}. 有效選項: {', '.join(valid_profiles)}"
            )

        # Skip on Vercel (serverless doesn't support subprocess)
        if IS_VERCEL:
            raise HTTPException(status_code=503, detail="此功能在展示模式下不可用")

        # Check if profile file exists
        profile_file = PROJECT_ROOT / "database" / "profiles" / f"{request.profile}.sql"
        if not profile_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Profile 檔案不存在: {profile_file}"
            )

        # Run initialization script
        result = subprocess.run(
            [
                "python3",
                str(PROJECT_ROOT / "scripts" / "init_database.py"),
                "--profile", request.profile,
                "--force",
                "--no-backup"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            logger.error(f"資料庫初始化失敗: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"資料庫初始化失敗: {result.stderr}"
            )

        # Get database stats
        conn = db.get_connection()
        cursor = conn.cursor()

        stats = {}
        for table in ['items', 'medicines', 'equipment']:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                stats[table] = count
            except:
                stats[table] = 0

        conn.close()

        logger.info(f"資料庫初始化成功: {stats}")

        return {
            "success": True,
            "message": "資料庫初始化成功",
            "profile": request.profile,
            "stats": stats
        }

    except subprocess.TimeoutExpired:
        logger.error("資料庫初始化超時")
        raise HTTPException(status_code=500, detail="初始化超時，請重試")
    except Exception as e:
        logger.error(f"資料庫初始化失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/setup/status")
async def get_setup_status():
    """
    檢查設定狀態

    返回:
    - is_initialized: 資料庫是否已初始化
    - has_station_info: 是否已設定站點資訊
    - needs_setup: 是否需要執行設定
    """
    try:
        # On Vercel, always return demo mode status
        if IS_VERCEL:
            return {
                "initialized": True,
                "has_data": True,
                "demo_mode": True,
                "message": "展示模式 - 使用預載資料"
            }

        db_path = PROJECT_ROOT / "medical_inventory.db"
        is_initialized = db_path.exists()

        # Check if database has data
        has_data = False
        if is_initialized:
            try:
                conn = db.get_connection()
                cursor = conn.cursor()

                # Check if any core table has data
                cursor.execute("SELECT COUNT(*) FROM items")
                item_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM medicines")
                med_count = cursor.fetchone()[0]

                has_data = (item_count > 0 or med_count > 0)

                conn.close()
            except:
                has_data = False

        # Determine if setup is needed
        needs_setup = not (is_initialized and has_data)

        return {
            "is_initialized": is_initialized,
            "has_data": has_data,
            "needs_setup": needs_setup
        }

    except Exception as e:
        logger.error(f"檢查設定狀態失敗: {e}")
        return {
            "is_initialized": False,
            "has_data": False,
            "needs_setup": True
        }


class SetupStationRequest(BaseModel):
    """設定站點資訊請求"""
    station_code: str
    station_name: str
    station_type: str

@app.post("/api/setup/station")
async def setup_station(request: SetupStationRequest):
    """
    設定站點資訊 - Setup Wizard Step 3

    更新 station_metadata 表中的站點資訊
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Update the first station record (should be the only one after profile init)
        cursor.execute("""
            UPDATE station_metadata
            SET station_code = ?,
                station_name = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = (SELECT MIN(id) FROM station_metadata)
        """, (request.station_code, request.station_name))

        conn.commit()
        conn.close()

        logger.info(f"站點資訊已更新: {request.station_code} - {request.station_name}")

        return {
            "success": True,
            "message": "站點資訊已儲存",
            "station_code": request.station_code,
            "station_name": request.station_name
        }

    except Exception as e:
        logger.error(f"儲存站點資訊失敗: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"儲存站點資訊失敗: {str(e)}"
        )


@app.post("/api/setup/reload-config")
async def reload_config():
    """
    重新載入站點配置 - Setup Wizard 完成後調用

    當設定精靈完成站點配置後，重新從資料庫載入站點 ID，
    確保後端使用正確的站點資訊過濾資料
    """
    try:
        # v2.0: 配置在啟動時已載入，無需重新載入
        # config.load_station_id_from_db()

        logger.info(f"✓ 配置已重新載入，當前站點 ID: {config.get_station_id()}")

        return {
            "success": True,
            "station_id": config.STATION_ID,
            "message": "站點配置已重新載入"
        }

    except Exception as e:
        logger.error(f"重新載入配置失敗: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"重新載入配置失敗: {str(e)}"
        )


# ============================================================================
# v1.4.2-plus: 藥品管理 API (Pharmaceuticals)
# ============================================================================

class PharmaReceiveRequest(BaseModel):
    """藥品進貨請求"""
    pharmaCode: str = Field(..., description="藥品代碼", min_length=1)
    quantity: int = Field(..., gt=0, description="數量必須大於0")
    batchNumber: Optional[str] = Field(None, description="批號")
    expiryDate: Optional[str] = Field(None, description="效期 (YYYY-MM-DD)")
    remarks: Optional[str] = Field(None, description="備註", max_length=500)


class PharmaConsumeRequest(BaseModel):
    """藥品消耗請求"""
    pharmaCode: str = Field(..., description="藥品代碼", min_length=1)
    quantity: int = Field(..., gt=0, description="數量必須大於0")
    purpose: str = Field(..., description="用途說明", min_length=1, max_length=500)


@app.get("/api/pharma/list")
async def get_pharmaceuticals(
    category: Optional[str] = Query(None, description="分類篩選"),
    search: Optional[str] = Query(None, description="搜尋關鍵字"),
    show_inactive: bool = Query(False, description="顯示停用藥品")
):
    """取得藥品清單"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT p.*,
                   COALESCE(
                       (SELECT SUM(CASE WHEN event_type IN ('RECEIVE', 'ADJUST') THEN quantity
                                        WHEN event_type IN ('CONSUME', 'EXPIRE') THEN -quantity END)
                        FROM pharma_events WHERE pharma_code = p.code), 0
                   ) + p.current_stock AS calculated_stock
            FROM pharmaceuticals p
            WHERE 1=1
        """
        params = []

        if not show_inactive:
            query += " AND p.is_active = 1"

        if category:
            query += " AND p.category = ?"
            params.append(category)

        if search:
            query += " AND (p.code LIKE ? OR p.name LIKE ? OR p.generic_name LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])

        query += " ORDER BY p.category, p.code"

        cursor.execute(query, params)
        items = [dict(row) for row in cursor.fetchall()]

        # 統計各分類數量
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM pharmaceuticals WHERE is_active = 1
            GROUP BY category
        """)
        category_stats = {row['category']: row['count'] for row in cursor.fetchall()}

        return {
            "items": items,
            "count": len(items),
            "category_stats": category_stats
        }

    except Exception as e:
        logger.error(f"查詢藥品失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/pharma/receive")
async def receive_pharmaceutical(request: PharmaReceiveRequest):
    """藥品進貨"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 檢查藥品是否存在
        cursor.execute("SELECT * FROM pharmaceuticals WHERE code = ?", (request.pharmaCode,))
        pharma = cursor.fetchone()

        if not pharma:
            raise HTTPException(status_code=404, detail=f"藥品 {request.pharmaCode} 不存在")

        # 記錄進貨事件
        cursor.execute("""
            INSERT INTO pharma_events (event_type, pharma_code, quantity, batch_number, expiry_date, remarks)
            VALUES ('RECEIVE', ?, ?, ?, ?, ?)
        """, (request.pharmaCode, request.quantity, request.batchNumber, request.expiryDate, request.remarks))

        # 更新庫存
        cursor.execute("""
            UPDATE pharmaceuticals
            SET current_stock = current_stock + ?, updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
        """, (request.quantity, request.pharmaCode))

        conn.commit()

        logger.info(f"💊 藥品進貨: {pharma['name']} x {request.quantity}")

        return {
            "success": True,
            "message": f"進貨成功: {pharma['name']} x {request.quantity} {pharma['unit']}",
            "pharma_code": request.pharmaCode,
            "quantity": request.quantity
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"藥品進貨失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/pharma/consume")
async def consume_pharmaceutical(request: PharmaConsumeRequest):
    """藥品消耗"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 檢查藥品是否存在
        cursor.execute("SELECT * FROM pharmaceuticals WHERE code = ?", (request.pharmaCode,))
        pharma = cursor.fetchone()

        if not pharma:
            raise HTTPException(status_code=404, detail=f"藥品 {request.pharmaCode} 不存在")

        # 檢查庫存
        if pharma['current_stock'] < request.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"庫存不足！{pharma['name']} 目前庫存: {pharma['current_stock']}"
            )

        # 記錄消耗事件
        cursor.execute("""
            INSERT INTO pharma_events (event_type, pharma_code, quantity, remarks)
            VALUES ('CONSUME', ?, ?, ?)
        """, (request.pharmaCode, request.quantity, request.purpose))

        # 更新庫存
        cursor.execute("""
            UPDATE pharmaceuticals
            SET current_stock = current_stock - ?, updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
        """, (request.quantity, request.pharmaCode))

        conn.commit()

        logger.info(f"💊 藥品消耗: {pharma['name']} x {request.quantity} ({request.purpose})")

        return {
            "success": True,
            "message": f"消耗成功: {pharma['name']} x {request.quantity} {pharma['unit']}",
            "pharma_code": request.pharmaCode,
            "quantity": request.quantity,
            "remaining_stock": pharma['current_stock'] - request.quantity
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"藥品消耗失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/pharma/events")
async def get_pharma_events(
    pharma_code: Optional[str] = Query(None, description="藥品代碼"),
    event_type: Optional[str] = Query(None, description="事件類型"),
    limit: int = Query(100, ge=1, le=500)
):
    """查詢藥品事件記錄"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT pe.*, p.name as pharma_name, p.unit
            FROM pharma_events pe
            JOIN pharmaceuticals p ON pe.pharma_code = p.code
            WHERE 1=1
        """
        params = []

        if pharma_code:
            query += " AND pe.pharma_code = ?"
            params.append(pharma_code)

        if event_type:
            query += " AND pe.event_type = ?"
            params.append(event_type)

        query += " ORDER BY pe.timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        events = [dict(row) for row in cursor.fetchall()]

        return {"events": events, "count": len(events)}

    except Exception as e:
        logger.error(f"查詢藥品事件失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/pharma/low-stock")
async def get_low_stock_pharma():
    """取得庫存不足的藥品"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT * FROM pharmaceuticals
            WHERE is_active = 1 AND current_stock < min_stock
            ORDER BY (current_stock * 1.0 / min_stock) ASC
        """)
        items = [dict(row) for row in cursor.fetchall()]

        return {"items": items, "count": len(items)}

    except Exception as e:
        logger.error(f"查詢低庫存藥品失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================================
# v1.4.2-plus: 血袋標籤管理 API (Blood Bags)
# ============================================================================

class BloodBagCreateRequest(BaseModel):
    """血袋入庫請求"""
    bloodType: str = Field(..., description="血型")
    quantity: int = Field(..., gt=0, le=20, description="數量 (1-20)")
    volumeMl: int = Field(default=250, ge=50, le=500, description="容量 ml")
    collectionDate: Optional[str] = Field(None, description="採集日期")
    expiryDate: Optional[str] = Field(None, description="效期")
    batchNumber: Optional[str] = Field(None, description="批號")
    remarks: Optional[str] = Field(None, description="備註")


class BloodBagUseRequest(BaseModel):
    """血袋使用請求"""
    bagCode: str = Field(..., description="血袋編號")
    usedFor: str = Field(..., description="使用對象/用途", min_length=1)


@app.post("/api/blood-bags/create")
async def create_blood_bags(request: BloodBagCreateRequest):
    """
    血袋入庫 - 自動生成獨立編號
    格式: BB-{血型}-{YYMMDD}-{序號}
    例如: BB-A+-251201-001
    """
    if request.bloodType not in config.BLOOD_TYPES:
        raise HTTPException(status_code=400, detail=f"無效血型: {request.bloodType}")

    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        today = datetime.now().strftime("%y%m%d")
        blood_type_code = request.bloodType.replace('+', 'P').replace('-', 'N')

        # 取得今日該血型最大序號
        cursor.execute("""
            SELECT bag_code FROM blood_bags
            WHERE bag_code LIKE ?
            ORDER BY bag_code DESC LIMIT 1
        """, (f"BB-{blood_type_code}-{today}-%",))

        result = cursor.fetchone()
        if result:
            last_seq = int(result['bag_code'].split('-')[-1])
            start_seq = last_seq + 1
        else:
            start_seq = 1

        # 計算效期 (預設 35 天)
        collection_date = request.collectionDate or datetime.now().strftime("%Y-%m-%d")
        if request.expiryDate:
            expiry_date = request.expiryDate
        else:
            expiry_date = (datetime.strptime(collection_date, "%Y-%m-%d") + timedelta(days=35)).strftime("%Y-%m-%d")

        # v1.5.1: 取得站點 ID 用於血袋追蹤
        station_id = config.get_station_id()

        created_bags = []
        for i in range(request.quantity):
            seq = start_seq + i
            bag_code = f"BB-{blood_type_code}-{today}-{seq:03d}"

            cursor.execute("""
                INSERT INTO blood_bags
                (bag_code, blood_type, volume_ml, collection_date, expiry_date, batch_number, remarks, station_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (bag_code, request.bloodType, request.volumeMl, collection_date,
                  expiry_date, request.batchNumber, request.remarks, station_id))

            created_bags.append({
                "bag_code": bag_code,
                "blood_type": request.bloodType,
                "volume_ml": request.volumeMl,
                "expiry_date": expiry_date
            })

        # 同步更新 blood_inventory
        cursor.execute("""
            INSERT INTO blood_inventory (blood_type, quantity, station_id)
            VALUES (?, ?, ?)
            ON CONFLICT(blood_type, station_id) DO UPDATE SET
                quantity = quantity + ?,
                last_updated = CURRENT_TIMESTAMP
        """, (request.bloodType, request.quantity, station_id, request.quantity))

        conn.commit()

        logger.info(f"🩸 血袋入庫: {request.bloodType} x {request.quantity}U")

        return {
            "success": True,
            "message": f"入庫成功: {request.bloodType} x {request.quantity}U",
            "bags": created_bags,
            "count": len(created_bags)
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"血袋入庫失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/blood-bags/list")
async def get_blood_bags(
    blood_type: Optional[str] = Query(None, description="血型篩選"),
    status: str = Query("AVAILABLE", description="狀態篩選")
):
    """取得血袋清單"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        query = "SELECT * FROM blood_bags WHERE status = ?"
        params = [status]

        if blood_type:
            query += " AND blood_type = ?"
            params.append(blood_type)

        query += " ORDER BY expiry_date ASC, created_at ASC"

        cursor.execute(query, params)
        bags = [dict(row) for row in cursor.fetchall()]

        # 統計各血型數量
        cursor.execute("""
            SELECT blood_type, COUNT(*) as count
            FROM blood_bags WHERE status = 'AVAILABLE'
            GROUP BY blood_type
        """)
        type_stats = {row['blood_type']: row['count'] for row in cursor.fetchall()}

        return {
            "bags": bags,
            "count": len(bags),
            "type_stats": type_stats
        }

    except Exception as e:
        logger.error(f"查詢血袋失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/blood-bags/use")
async def use_blood_bag(request: BloodBagUseRequest):
    """使用血袋"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 檢查血袋是否存在且可用
        cursor.execute("""
            SELECT * FROM blood_bags WHERE bag_code = ? AND status = 'AVAILABLE'
        """, (request.bagCode,))
        bag = cursor.fetchone()

        if not bag:
            raise HTTPException(status_code=404, detail=f"血袋 {request.bagCode} 不存在或已使用")

        # 更新血袋狀態
        cursor.execute("""
            UPDATE blood_bags
            SET status = 'USED', used_at = CURRENT_TIMESTAMP, used_for = ?
            WHERE bag_code = ?
        """, (request.usedFor, request.bagCode))

        # 同步更新 blood_inventory
        station_id = config.get_station_id()
        cursor.execute("""
            UPDATE blood_inventory
            SET quantity = quantity - 1, last_updated = CURRENT_TIMESTAMP
            WHERE blood_type = ? AND station_id = ?
        """, (bag['blood_type'], station_id))

        # 記錄血袋事件
        cursor.execute("""
            INSERT INTO blood_events (event_type, blood_type, quantity, station_id, operator)
            VALUES ('CONSUME', ?, 1, ?, ?)
        """, (bag['blood_type'], station_id, request.usedFor))

        conn.commit()

        logger.info(f"🩸 血袋使用: {request.bagCode} -> {request.usedFor}")

        return {
            "success": True,
            "message": f"血袋 {request.bagCode} 已標記為已使用",
            "bag_code": request.bagCode,
            "blood_type": bag['blood_type'],
            "used_for": request.usedFor
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"使用血袋失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class BloodBagDiscardRequest(BaseModel):
    """血袋丟棄請求"""
    bagCode: str
    reason: str = "expired"  # expired, damaged, other


class BloodBagConsumeRequest(BaseModel):
    """血袋出庫請求 (v1.4.2-plus)"""
    bagCodes: List[str]  # 要出庫的血袋編號列表
    patientName: str
    patientId: str = ""
    purpose: str = ""
    stationId: str


@app.post("/api/blood-bags/discard")
async def discard_blood_bag(request: BloodBagDiscardRequest):
    """丟棄血袋 (過期/損壞)"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 檢查血袋是否存在且可用
        cursor.execute("""
            SELECT * FROM blood_bags WHERE bag_code = ? AND status = 'AVAILABLE'
        """, (request.bagCode,))
        bag = cursor.fetchone()

        if not bag:
            raise HTTPException(status_code=404, detail=f"血袋 {request.bagCode} 不存在或已處理")

        # 更新血袋狀態為 DISCARDED
        cursor.execute("""
            UPDATE blood_bags
            SET status = 'DISCARDED', used_at = CURRENT_TIMESTAMP, used_for = ?
            WHERE bag_code = ?
        """, (f"丟棄原因: {request.reason}", request.bagCode))

        # 同步更新 blood_inventory (減少庫存)
        # v1.5.1: 使用血袋本身的 station_id，若無則使用目前站點
        bag_station_id = bag['station_id'] if bag['station_id'] else config.get_station_id()
        cursor.execute("""
            UPDATE blood_inventory
            SET quantity = quantity - 1, last_updated = CURRENT_TIMESTAMP
            WHERE blood_type = ? AND station_id = ?
        """, (bag['blood_type'], bag_station_id))

        # 記錄血袋事件
        cursor.execute("""
            INSERT INTO blood_events (event_type, blood_type, quantity, station_id, operator)
            VALUES ('DISCARD', ?, 1, ?, ?)
        """, (bag['blood_type'], station_id, request.reason))

        conn.commit()

        logger.info(f"🩸 血袋丟棄: {request.bagCode} -> {request.reason}")

        return {
            "success": True,
            "message": f"血袋 {request.bagCode} 已標記為丟棄",
            "bag_code": request.bagCode,
            "blood_type": bag['blood_type'],
            "reason": request.reason
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"丟棄血袋失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/blood-bags/consume")
async def consume_blood_bags(request: BloodBagConsumeRequest):
    """批次出庫血袋 (v1.4.2-plus) - 連動個別血袋狀態與庫存"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        if not request.bagCodes:
            raise HTTPException(status_code=400, detail="請選擇要出庫的血袋")

        consumed_bags = []
        blood_type_counts = {}  # 記錄各血型消耗數量
        blood_type_bag_codes = {}  # 記錄各血型的血袋編號

        # 取得台灣時區時間
        from datetime import datetime
        import pytz
        tw_tz = pytz.timezone('Asia/Taipei')
        tw_now = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

        for bag_code in request.bagCodes:
            # 檢查血袋是否存在且可用
            cursor.execute("""
                SELECT * FROM blood_bags WHERE bag_code = ? AND status = 'AVAILABLE'
            """, (bag_code,))
            bag = cursor.fetchone()

            if not bag:
                raise HTTPException(status_code=404, detail=f"血袋 {bag_code} 不存在或已使用")

            # 更新血袋狀態為 USED
            used_for = f"病患: {request.patientName}"
            if request.patientId:
                used_for += f" ({request.patientId})"
            if request.purpose:
                used_for += f" - {request.purpose}"

            cursor.execute("""
                UPDATE blood_bags
                SET status = 'USED', used_at = ?, used_for = ?
                WHERE bag_code = ?
            """, (tw_now, used_for, bag_code))

            consumed_bags.append({
                "bag_code": bag_code,
                "blood_type": bag['blood_type'],
                "volume_ml": bag['volume_ml']
            })

            # 統計各血型消耗數量與血袋編號
            bt = bag['blood_type']
            blood_type_counts[bt] = blood_type_counts.get(bt, 0) + 1
            if bt not in blood_type_bag_codes:
                blood_type_bag_codes[bt] = []
            blood_type_bag_codes[bt].append(bag_code)

        # 更新 blood_inventory (減少庫存)
        for blood_type, count in blood_type_counts.items():
            cursor.execute("""
                UPDATE blood_inventory
                SET quantity = quantity - ?, last_updated = ?
                WHERE blood_type = ? AND station_id = ?
            """, (count, tw_now, blood_type, request.stationId))

            # 記錄血袋出庫事件 - 包含具體血袋編號
            bag_codes_str = ", ".join(blood_type_bag_codes[blood_type])
            remarks = f"血袋: {bag_codes_str}"
            if request.purpose:
                remarks += f" | 用途: {request.purpose}"

            cursor.execute("""
                INSERT INTO blood_events (event_type, blood_type, quantity, station_id, operator, remarks, timestamp)
                VALUES ('CONSUME', ?, ?, ?, ?, ?, ?)
            """, (blood_type, count, request.stationId, request.patientName, remarks, tw_now))

        conn.commit()

        logger.info(f"🩸 血袋出庫: {len(consumed_bags)} 袋 -> {request.patientName}")

        return {
            "success": True,
            "message": f"成功出庫 {len(consumed_bags)} 袋血袋",
            "consumed_bags": consumed_bags,
            "patient": request.patientName
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"血袋出庫失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/blood-bags/print-labels/{bag_codes}")
async def print_blood_bag_labels(bag_codes: str):
    """
    生成血袋標籤列印頁面 (HTML) - 多標籤排列在 A4 紙上
    bag_codes: 逗號分隔的血袋編號，例如 "BB-AP-251201-001,BB-AP-251201-002"
    標籤尺寸: 5cm x 7cm，每頁可排 4列 x 3行 = 12 張標籤
    """
    codes = [c.strip() for c in bag_codes.split(",")]

    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        placeholders = ",".join(["?" for _ in codes])
        cursor.execute(f"""
            SELECT * FROM blood_bags WHERE bag_code IN ({placeholders})
        """, codes)

        bags = [dict(row) for row in cursor.fetchall()]

        if not bags:
            raise HTTPException(status_code=404, detail="找不到指定的血袋")

        # 生成每個標籤的 HTML
        labels_html = []
        for bag in bags:
            label_html = f"""
        <div class="label">
            <div class="header">血袋標籤 BLOOD BAG</div>
            <div class="blood-type">{bag['blood_type']}</div>
            <div class="volume">{bag['volume_ml']} ml</div>
            <div class="info">編號: <span class="code">{bag['bag_code']}</span></div>
            <div class="info">採集: {bag['collection_date'] or '-'}</div>
            <div class="info"><strong>效期: {bag['expiry_date'] or '-'}</strong></div>
            <div class="warning">⚠ 使用前請確認血型與效期 ⚠</div>
        </div>"""
            labels_html.append(label_html)

        # 生成可列印的 HTML 頁面 - 多標籤排列在 A4 上
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>血袋標籤 ({len(bags)}張)</title>
    <style>
        @media print {{
            @page {{
                size: A4;
                margin: 5mm;
            }}
            body {{ margin: 0; }}
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Microsoft JhengHei', 'SimHei', Arial, sans-serif;
            margin: 5mm;
            padding: 0;
        }}
        .labels-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 2mm;
            justify-content: flex-start;
        }}
        .label {{
            width: 50mm;
            height: 70mm;
            border: 1.5px solid #000;
            padding: 2mm;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            background: white;
            page-break-inside: avoid;
        }}
        .header {{
            text-align: center;
            font-weight: bold;
            font-size: 9pt;
            border-bottom: 1.5px solid #000;
            padding-bottom: 2px;
            margin-bottom: 3px;
            background-color: #f0f0f0;
        }}
        .blood-type {{
            font-size: 28pt;
            font-weight: bold;
            color: #cc0000;
            text-align: center;
            margin: 5px 0;
            line-height: 1.1;
        }}
        .volume {{
            font-size: 14pt;
            font-weight: bold;
            color: #cc0000;
            text-align: center;
            margin: 2px 0;
        }}
        .info {{
            font-size: 8pt;
            margin: 2px 0;
            line-height: 1.3;
        }}
        .code {{
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 7pt;
        }}
        .warning {{
            color: #cc0000;
            font-weight: bold;
            font-size: 7pt;
            text-align: center;
            margin-top: auto;
            border-top: 1px solid #000;
            padding-top: 2px;
        }}
        .print-info {{
            text-align: center;
            margin-bottom: 10px;
            font-size: 10pt;
            color: #666;
        }}
        @media print {{
            .print-info {{ display: none; }}
        }}
    </style>
</head>
<body onload="window.print();">
    <div class="print-info">共 {len(bags)} 張標籤 - 建議使用 A4 紙列印</div>
    <div class="labels-container">
        {''.join(labels_html)}
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成標籤失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/blood-bags/expiring")
async def get_expiring_blood_bags(days: int = Query(7, ge=1, le=30)):
    """取得即將過期的血袋"""
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        expiry_threshold = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT * FROM blood_bags
            WHERE status = 'AVAILABLE' AND expiry_date <= ?
            ORDER BY expiry_date ASC
        """, (expiry_threshold,))

        bags = [dict(row) for row in cursor.fetchall()]

        return {
            "bags": bags,
            "count": len(bags),
            "threshold_date": expiry_threshold
        }

    except Exception as e:
        logger.error(f"查詢即將過期血袋失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================================
# 韌性估算 API (Resilience Calculation)
# Based on: IRS_RESILIENCE_FRAMEWORK.md v1.0
# ============================================================================

from services.resilience_service import ResilienceService, StatusLevel

# Initialize resilience service with shared DatabaseManager (critical for in-memory mode)
resilience_service = ResilienceService(db)

# ============================================================================
# MIRS Mobile API v1
# ============================================================================

try:
    from services.mobile import mobile_router, init_mobile_services

    # Initialize mobile services with shared resources
    init_mobile_services(
        db_path=config.DATABASE_PATH,
        resilience_service=resilience_service,
        db_manager=db
    )

    # Include mobile router
    app.include_router(mobile_router)
    logger.info("✓ MIRS Mobile API v1 已啟用 (/api/mirs-mobile/v1)")
except ImportError as e:
    logger.warning(f"MIRS Mobile API 未啟用: {e}")
except Exception as e:
    logger.error(f"MIRS Mobile API 初始化失敗: {e}")

# v1.5.1: 麻醉模組路由
if ANESTHESIA_MODULE_AVAILABLE and anesthesia_router:
    app.include_router(anesthesia_router)
    logger.info("✓ MIRS Anesthesia Module v1.5.1 已啟用 (/api/anesthesia)")
else:
    logger.warning("麻醉模組未啟用")


class ResilienceConfigUpdate(BaseModel):
    """韌性設定更新請求"""
    isolation_target_days: Optional[float] = Field(None, ge=1, le=30, description="預估孤立天數")
    population_count: Optional[float] = Field(None, ge=0, le=100, description="等效插管人數 (插管=1.0, 面罩≈0.6, 鼻導管≈0.3)")
    population_label: Optional[str] = Field(None, description="人數標籤")
    oxygen_profile_id: Optional[int] = Field(None, description="氧氣情境設定ID")
    power_profile_id: Optional[int] = Field(None, description="電力情境設定ID")
    reagent_profile_id: Optional[int] = Field(None, description="試劑情境設定ID")
    threshold_safe: Optional[float] = Field(None, ge=1.0, le=2.0, description="安全閾值")
    threshold_warning: Optional[float] = Field(None, ge=0.5, le=1.5, description="警告閾值")


class ProfileCreate(BaseModel):
    """情境設定建立請求"""
    endurance_type: str = Field(..., description="類型: OXYGEN/POWER/REAGENT")
    profile_name: str = Field(..., description="情境名稱")
    profile_name_en: Optional[str] = Field(None, description="英文名稱")
    burn_rate: float = Field(..., gt=0, description="消耗率")
    burn_rate_unit: str = Field(..., description="單位: L/min, L/hr, tests/day")
    population_multiplier: Optional[int] = Field(0, description="是否乘以人數")
    description: Optional[str] = Field(None, description="說明")


class ReagentOpenRequest(BaseModel):
    """試劑開封請求"""
    item_code: str = Field(..., description="試劑代碼")
    batch_number: Optional[str] = Field(None, description="批號")
    tests_remaining: Optional[int] = Field(None, description="剩餘測試數")


@app.get("/api/resilience/status")
async def get_resilience_status(station_id: Optional[str] = Query(None)):
    """
    取得站點韌性狀態

    計算氧氣、電力、試劑的維持時數/天數，
    並與孤立天數目標比較，回傳警戒狀態。
    """
    try:
        sid = station_id or config.get_station_id()
        result = resilience_service.calculate_resilience_status(sid)
        return result
    except Exception as e:
        logger.error(f"韌性狀態計算失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/resilience/config")
async def get_resilience_config(station_id: Optional[str] = Query(None)):
    """取得站點韌性設定"""
    try:
        sid = station_id or config.get_station_id()
        return resilience_service.get_config(sid)
    except Exception as e:
        logger.error(f"取得韌性設定失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/resilience/config")
async def update_resilience_config(
    update: ResilienceConfigUpdate,
    station_id: Optional[str] = Query(None)
):
    """更新站點韌性設定"""
    try:
        sid = station_id or config.get_station_id()
        config_dict = update.model_dump(exclude_none=True)
        config_dict['updated_by'] = 'API'

        resilience_service.update_config(sid, config_dict)
        return {"success": True, "message": "設定已更新"}
    except Exception as e:
        logger.error(f"更新韌性設定失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/resilience/profiles")
async def get_resilience_profiles(
    endurance_type: str = Query(..., description="類型: OXYGEN/POWER/REAGENT"),
    station_id: Optional[str] = Query(None)
):
    """取得情境設定列表"""
    try:
        sid = station_id or config.get_station_id()
        profiles = resilience_service.get_profiles(endurance_type, sid)
        return {"profiles": profiles, "count": len(profiles)}
    except Exception as e:
        logger.error(f"取得情境設定失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/resilience/profiles")
async def create_resilience_profile(
    profile: ProfileCreate,
    station_id: Optional[str] = Query(None)
):
    """建立自訂情境設定"""
    try:
        sid = station_id or config.get_station_id()
        profile_dict = profile.model_dump()
        profile_dict['station_id'] = sid

        profile_id = resilience_service.create_profile(profile_dict)
        return {"success": True, "profile_id": profile_id}
    except Exception as e:
        logger.error(f"建立情境設定失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/resilience/reagent/open")
async def mark_reagent_opened(
    request: ReagentOpenRequest,
    station_id: Optional[str] = Query(None)
):
    """標記試劑已開封（啟動效期倒數）"""
    try:
        sid = station_id or config.get_station_id()
        record_id = resilience_service.mark_reagent_opened(
            station_id=sid,
            item_code=request.item_code,
            batch_number=request.batch_number,
            tests_remaining=request.tests_remaining
        )
        return {
            "success": True,
            "record_id": record_id,
            "message": f"試劑 {request.item_code} 已標記為開封"
        }
    except Exception as e:
        logger.error(f"標記試劑開封失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/resilience/summary")
async def get_resilience_summary(station_id: Optional[str] = Query(None)):
    """
    取得韌性摘要（簡化版，適合Dashboard顯示）
    """
    try:
        sid = station_id or config.get_station_id()
        full_status = resilience_service.calculate_resilience_status(sid)

        # Extract summary
        return {
            "station_id": sid,
            "overall_status": full_status['summary']['overall_status'],
            "can_survive": full_status['summary']['can_survive_isolation'],
            "weakest_link": full_status['summary']['weakest_link'],
            "isolation_target_days": full_status['context']['isolation_target_days'],
            "critical_count": len(full_status['summary']['critical_items']),
            "warning_count": len(full_status['summary']['warning_items']),
            "lifeline_count": len(full_status['lifelines']),
            "reagent_count": len(full_status['reagents'])
        }
    except Exception as e:
        logger.error(f"韌性摘要計算失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# API v2: 設備架構重構 (Equipment Architecture v2)
# Based on: EQUIPMENT_ARCHITECTURE_REDESIGN.md
# ============================================================================

from services.capacity_calculator import (
    calculate_equipment_hours,
    aggregate_unit_hours,
    get_calculator
)

@app.get("/api/v2/equipment-types")
async def get_equipment_types_v2():
    """
    取得所有設備類型定義

    Returns:
        List of equipment types with capacity configurations
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT type_code, type_name, category, resilience_category,
                   unit_label, capacity_config, status_options, icon, color
            FROM equipment_types
            ORDER BY resilience_category DESC, category, type_name
        """)

        types = []
        for row in cursor.fetchall():
            types.append({
                "type_code": row[0],
                "type_name": row[1],
                "category": row[2],
                "resilience_category": row[3],
                "unit_label": row[4],
                "capacity_config": json.loads(row[5]) if row[5] else None,
                "status_options": json.loads(row[6]) if row[6] else [],
                "icon": row[7],
                "color": row[8]
            })

        return {"types": types, "count": len(types)}
    except Exception as e:
        logger.error(f"取得設備類型失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/equipment")
async def get_equipment_v2():
    """
    取得所有設備及其聚合狀態 (使用 v_equipment_status View)

    Returns:
        List of equipment with aggregated status from units
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, name, type_code, type_name, category, resilience_category,
                   unit_count, avg_level, checked_count, last_check, check_status
            FROM v_equipment_status
            ORDER BY resilience_category DESC, category, name
        """)

        equipment = []
        for row in cursor.fetchall():
            equipment.append({
                "id": row[0],
                "name": row[1],
                "type_code": row[2],
                "type_name": row[3],
                "category": row[4],
                "resilience_category": row[5],
                "unit_count": row[6],
                "avg_level": row[7],
                "checked_count": row[8],
                "last_check": row[9],
                "check_status": row[10]
            })

        return {"equipment": equipment, "count": len(equipment)}
    except Exception as e:
        logger.error(f"取得設備列表失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/equipment/{equipment_id}")
async def get_equipment_detail_v2(equipment_id: str):
    """
    取得單一設備詳情及其所有單位

    Args:
        equipment_id: 設備ID

    Returns:
        Equipment details with all units
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get equipment with type info
        cursor.execute("""
            SELECT e.id, e.name, e.type_code, et.type_name, et.category,
                   et.resilience_category, et.capacity_config, et.status_options,
                   e.remarks
            FROM equipment e
            LEFT JOIN equipment_types et ON e.type_code = et.type_code
            WHERE e.id = ?
        """, (equipment_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"設備不存在: {equipment_id}")

        equipment = {
            "id": row[0],
            "name": row[1],
            "type_code": row[2],
            "type_name": row[3],
            "category": row[4],
            "resilience_category": row[5],
            "capacity_config": json.loads(row[6]) if row[6] else None,
            "status_options": json.loads(row[7]) if row[7] else [],
            "remarks": row[8]
        }

        # Get units
        cursor.execute("""
            SELECT id, unit_serial, unit_label, level_percent, status,
                   last_check, checked_by, remarks
            FROM equipment_units
            WHERE equipment_id = ?
            ORDER BY unit_serial
        """, (equipment_id,))

        units = []
        for unit_row in cursor.fetchall():
            # Calculate hours for this unit
            hours_result = calculate_equipment_hours(
                unit_row[3] or 0,
                row[6]  # capacity_config
            )

            units.append({
                "id": unit_row[0],
                "unit_serial": unit_row[1],
                "unit_label": unit_row[2],
                "level_percent": unit_row[3],
                "status": unit_row[4],
                "last_check": unit_row[5],
                "checked_by": unit_row[6],
                "remarks": unit_row[7],
                "hours": hours_result.hours
            })

        equipment["units"] = units
        equipment["unit_count"] = len(units)

        # Calculate aggregated hours
        if units:
            total_hours = sum(u["hours"] for u in units)
            avg_level = sum(u["level_percent"] or 0 for u in units) / len(units)
            equipment["total_hours"] = round(total_hours, 2)
            equipment["avg_level"] = round(avg_level, 1)

        return equipment
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取得設備詳情失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/resilience/dashboard")
async def get_resilience_dashboard_v2(station_id: Optional[str] = Query(None)):
    """
    韌性儀表板 API (v2)

    提供預先計算好的韌性數據，前端可直接使用。
    使用 v_resilience_equipment View 和 Calculator Strategy。

    Returns:
        {
            summary: { overall_status, min_hours, check_progress },
            lifelines: [ { category, name, total_hours, items: [...] } ]
        }
    """
    try:
        sid = station_id or config.get_station_id()
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get resilience config
        cursor.execute("""
            SELECT isolation_target_days, population_count
            FROM resilience_config WHERE station_id = ?
        """, (sid,))
        config_row = cursor.fetchone()

        isolation_days = config_row[0] if config_row else 3
        population_count = config_row[1] if config_row else 1

        # Get all resilience equipment from view
        cursor.execute("""
            SELECT equipment_id, name, type_code, type_name, resilience_category,
                   capacity_config, unit_id, unit_serial, unit_label,
                   level_percent, status, last_check
            FROM v_resilience_equipment
        """)

        # Organize by category and equipment
        categories = {}
        equipment_map = {}

        for row in cursor.fetchall():
            eq_id = row[0]
            category = row[4]
            capacity_config = row[5]

            if category not in categories:
                categories[category] = {
                    "category": category,
                    "name": "電力供應" if category == "POWER" else "氧氣供應",
                    "items": []
                }

            if eq_id not in equipment_map:
                equipment_map[eq_id] = {
                    "equipment_id": eq_id,
                    "name": row[1],
                    "type_code": row[2],
                    "type_name": row[3],
                    "capacity_config": capacity_config,
                    "units": [],
                    "category": category
                }

            # Add unit
            level = row[9] or 0
            hours_result = calculate_equipment_hours(level, capacity_config)

            # Phase 3.4b: Normalize timestamp to UTC+Z format
            last_check_raw = row[11]
            last_check_utc = None
            if last_check_raw:
                try:
                    # Parse and convert to UTC+Z format
                    if isinstance(last_check_raw, str):
                        dt = datetime.fromisoformat(last_check_raw.replace('Z', '+00:00'))
                        last_check_utc = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    else:
                        last_check_utc = last_check_raw
                except:
                    last_check_utc = last_check_raw

            equipment_map[eq_id]["units"].append({
                "unit_id": row[6],
                "serial": row[7],
                "label": row[8],
                "level_percent": level,
                "status": row[10],
                "hours": hours_result.hours,
                "last_check": last_check_utc  # UTC+Z format
            })

        # Calculate totals per category
        lifelines = []
        total_checked = 0
        total_units = 0

        for category, cat_data in categories.items():
            cat_hours = 0
            cat_items = []
            charging_warnings = []

            for eq_id, eq_data in equipment_map.items():
                if eq_data["category"] != category:
                    continue

                eq_hours = sum(u["hours"] for u in eq_data["units"])
                checked = sum(1 for u in eq_data["units"] if u["last_check"])

                # Check for charging units
                charging_units = [u for u in eq_data["units"] if u["status"] == "CHARGING"]
                if charging_units:
                    charging_warnings.append(
                        f"{eq_data['name']} 有 {len(charging_units)} 台充電中，請於充電完成後更新狀態"
                    )

                cat_items.append({
                    "equipment_id": eq_id,
                    "name": eq_data["name"],
                    "type_code": eq_data["type_code"],
                    "check_status": "CHECKED" if checked == len(eq_data["units"]) else (
                        "PARTIAL" if checked > 0 else "UNCHECKED"
                    ),
                    "units": eq_data["units"]
                })

                cat_hours += eq_hours
                total_checked += checked
                total_units += len(eq_data["units"])

            # Determine status
            target_hours = isolation_days * 24
            if cat_hours >= target_hours * 1.2:
                status = "SAFE"
            elif cat_hours >= target_hours:
                status = "WARNING"
            else:
                status = "CRITICAL"

            lifelines.append({
                "category": category,
                "name": cat_data["name"],
                "status": status,
                "total_hours": round(cat_hours, 2),
                "items": cat_items,
                "charging_warnings": charging_warnings
            })

        # Calculate overall status
        if lifelines:
            min_hours = min(ll["total_hours"] for ll in lifelines)
            limiting = min(lifelines, key=lambda x: x["total_hours"])

            if all(ll["status"] == "SAFE" for ll in lifelines):
                overall_status = "SAFE"
            elif any(ll["status"] == "CRITICAL" for ll in lifelines):
                overall_status = "CRITICAL"
            else:
                overall_status = "WARNING"
        else:
            min_hours = 0
            limiting = None
            overall_status = "UNKNOWN"

        return {
            "station_id": sid,
            "summary": {
                "overall_status": overall_status,
                "min_hours": round(min_hours, 2),
                "min_days": round(min_hours / 24, 1),
                "limiting_factor": limiting["category"] if limiting else None,
                "isolation_target_days": isolation_days,
                "check_progress": {
                    "total": total_units,
                    "checked": total_checked,
                    "percentage": round(total_checked / total_units * 100) if total_units else 0
                }
            },
            "lifelines": lifelines
        }
    except Exception as e:
        logger.error(f"韌性儀表板計算失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UnitCheckRequest(BaseModel):
    level_percent: int = Field(..., ge=0, le=100)
    status: str = Field(default="AVAILABLE")
    remarks: Optional[str] = None


@app.post("/api/v2/equipment/units/{unit_id}/check")
async def check_equipment_unit_v2(unit_id: int, request: UnitCheckRequest):
    """
    檢查/更新設備單位狀態 (v2)

    自動記錄歷史並回傳更新後的聚合狀態。

    Args:
        unit_id: 單位ID
        request: { level_percent, status, remarks }

    Returns:
        Updated unit and equipment aggregate status
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get current unit info
        cursor.execute("""
            SELECT u.equipment_id, u.unit_serial, u.level_percent, u.status,
                   e.name, et.capacity_config
            FROM equipment_units u
            JOIN equipment e ON u.equipment_id = e.id
            LEFT JOIN equipment_types et ON e.type_code = et.type_code
            WHERE u.id = ?
        """, (unit_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"單位不存在: {unit_id}")

        equipment_id = row[0]
        unit_serial = row[1]
        old_level = row[2]
        old_status = row[3]
        equipment_name = row[4]
        capacity_config = row[5]

        # Record history
        cursor.execute("""
            INSERT INTO equipment_check_history
            (equipment_id, unit_label, unit_id, check_date, check_time, level_before, level_after,
             status_before, status_after, remarks)
            VALUES (?, ?, ?, date('now'), datetime('now'), ?, ?, ?, ?, ?)
        """, (
            equipment_id, unit_serial, unit_id,
            old_level, request.level_percent,
            old_status, request.status,
            request.remarks
        ))

        # Update unit
        cursor.execute("""
            UPDATE equipment_units
            SET level_percent = ?, status = ?, last_check = datetime('now'),
                remarks = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (request.level_percent, request.status, request.remarks, unit_id))

        conn.commit()

        # Calculate new hours
        hours_result = calculate_equipment_hours(request.level_percent, capacity_config)

        # Get updated equipment aggregate
        cursor.execute("""
            SELECT unit_count, avg_level, checked_count, check_status
            FROM v_equipment_status
            WHERE id = ?
        """, (equipment_id,))
        agg_row = cursor.fetchone()

        # Phase 3.4a: Calculate dashboard delta for optimistic UI
        dashboard_delta = None
        cursor.execute("""
            SELECT et.resilience_category
            FROM equipment e
            JOIN equipment_types et ON e.type_code = et.type_code
            WHERE e.id = ?
        """, (equipment_id,))
        cat_row = cursor.fetchone()

        if cat_row and cat_row[0]:  # If resilience equipment
            resilience_category = cat_row[0]

            # Calculate updated total hours for this category
            cursor.execute("""
                SELECT SUM(
                    CASE
                        WHEN u.status IN ('AVAILABLE', 'IN_USE') THEN
                            json_extract(et.capacity_config, '$.hours_per_100pct') * u.level_percent / 100.0
                        ELSE 0
                    END
                ) as total_hours,
                COUNT(DISTINCT e.id) as equipment_count,
                SUM(CASE WHEN u.last_check IS NOT NULL THEN 1 ELSE 0 END) as checked_count,
                COUNT(u.id) as total_units
                FROM equipment e
                JOIN equipment_types et ON e.type_code = et.type_code
                JOIN equipment_units u ON e.id = u.equipment_id
                WHERE et.resilience_category = ?
            """, (resilience_category,))
            delta_row = cursor.fetchone()

            dashboard_delta = {
                "category": resilience_category,
                "total_hours": round(delta_row[0] or 0, 2),
                "equipment_count": delta_row[1] or 0,
                "checked_count": delta_row[2] or 0,
                "total_units": delta_row[3] or 0
            }

        # Phase 3.4b: Use UTC timestamp with Z suffix
        now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "success": True,
            "unit": {
                "id": unit_id,
                "equipment_id": equipment_id,
                "level_percent": request.level_percent,
                "status": request.status,
                "hours": hours_result.hours,
                "last_check": now_utc  # UTC+Z format
            },
            "equipment_aggregate": {
                "equipment_id": equipment_id,
                "name": equipment_name,
                "unit_count": agg_row[0] if agg_row else 0,
                "avg_level": agg_row[1] if agg_row else 0,
                "checked_count": agg_row[2] if agg_row else 0,
                "check_status": agg_row[3] if agg_row else "UNKNOWN"
            },
            "dashboard_delta": dashboard_delta  # Phase 3.4a: For optimistic UI
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新設備單位失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/equipment/units/{unit_id}/reset")
async def reset_equipment_unit_v2(unit_id: int):
    """
    重置設備單位檢查狀態

    Args:
        unit_id: 單位ID

    Returns:
        Updated unit status
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get current unit info
        cursor.execute("""
            SELECT equipment_id, unit_serial, level_percent, status
            FROM equipment_units WHERE id = ?
        """, (unit_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"單位不存在: {unit_id}")

        equipment_id = row[0]
        unit_serial = row[1]

        # Record reset in history
        cursor.execute("""
            INSERT INTO equipment_check_history
            (equipment_id, unit_label, unit_id, check_date, check_time, level_before, level_after,
             status_before, status_after, remarks)
            VALUES (?, ?, ?, date('now'), datetime('now'), ?, ?, ?, ?, 'RESET')
        """, (
            equipment_id, unit_serial, unit_id,
            row[2], row[2],
            row[3], row[3]
        ))

        # Reset last_check
        cursor.execute("""
            UPDATE equipment_units
            SET last_check = NULL, updated_at = datetime('now')
            WHERE id = ?
        """, (unit_id,))

        conn.commit()

        return {
            "success": True,
            "unit_id": unit_id,
            "equipment_id": equipment_id,
            "message": "檢查狀態已重置"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置設備單位失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# v2.1 設備單位管理 API (Unit Management with Soft Delete)
# ============================================================================

def _generate_next_serial(cursor, equipment_id: str) -> tuple:
    """
    生成下一個序號和標籤

    Returns:
        (unit_serial, unit_label)
    """
    # 1. 查詢設備的 type_code 和序號設定
    cursor.execute("""
        SELECT e.type_code, et.unit_prefix, et.label_template
        FROM equipment e
        LEFT JOIN equipment_types et ON e.type_code = et.type_code
        WHERE e.id = ?
    """, (equipment_id,))

    row = cursor.fetchone()
    if not row:
        raise ValueError(f"找不到設備 {equipment_id} 或其類型設定")

    type_code = row[0]
    prefix = row[1] or "UNIT"
    template = row[2] or "單位{n}號"

    # 2. 找出該設備現有的最大序號（包含已移除的，避免重複）
    cursor.execute("""
        SELECT unit_serial FROM equipment_units
        WHERE equipment_id = ?
        ORDER BY unit_serial DESC
    """, (equipment_id,))

    existing_serials = [r[0] for r in cursor.fetchall()]

    # 3. 計算下一個序號
    max_num = 0
    for serial in existing_serials:
        if serial and prefix in serial:
            try:
                # 處理格式如 "H-CYL-001" 或 "PS-001"
                parts = serial.split('-')
                num = int(parts[-1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass

    next_num = max_num + 1
    unit_serial = f"{prefix}-{next_num:03d}"

    # 4. 根據模板生成標籤
    unit_label = template.replace('{n}', str(next_num))

    return unit_serial, unit_label


def _get_equipment_summary(cursor, equipment_id: str) -> dict:
    """取得設備摘要資訊"""
    cursor.execute("""
        SELECT e.id, e.name, et.type_name, et.resilience_category, et.capacity_config,
               COUNT(u.id) as active_count
        FROM equipment e
        LEFT JOIN equipment_types et ON e.type_code = et.type_code
        LEFT JOIN equipment_units u ON e.id = u.equipment_id AND u.is_active = 1
        WHERE e.id = ?
        GROUP BY e.id
    """, (equipment_id,))
    row = cursor.fetchone()
    if not row:
        return None

    # 計算韌性小時數
    total_hours = 0
    if row[4]:  # capacity_config
        try:
            config = json.loads(row[4])
            cursor.execute("""
                SELECT SUM(level_percent) FROM equipment_units
                WHERE equipment_id = ? AND is_active = 1
            """, (equipment_id,))
            total_level = cursor.fetchone()[0] or 0
            hours_per_100 = config.get('hours_per_100pct', 0)
            total_hours = round((total_level / 100) * hours_per_100, 1)
        except:
            pass

    return {
        "equipment_id": row[0],
        "name": row[1],
        "type_name": row[2],
        "resilience_category": row[3],
        "active_unit_count": row[5],
        "total_hours": total_hours
    }


def _record_lifecycle_event(cursor, unit_id: int, equipment_id: str, event_type: str,
                            actor: str = None, reason: str = None, snapshot: dict = None,
                            correlation_id: str = None):
    """記錄生命週期事件"""
    cursor.execute("""
        INSERT INTO equipment_lifecycle_events
        (unit_id, equipment_id, event_type, actor, reason, snapshot_json, correlation_id, station_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        unit_id, equipment_id, event_type, actor, reason,
        json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
        correlation_id, config.get_station_id()
    ))
    return cursor.lastrowid


def _get_removal_priority(unit: dict) -> tuple:
    """
    計算移除優先順序，值越小越優先移除

    優先序：
    1. 狀態：EMPTY > MAINTENANCE > IN_USE > CHARGING > AVAILABLE
    2. 電量：由低到高
    3. 序號：數字越大越優先
    """
    status_priority = {
        'EMPTY': 0,
        'MAINTENANCE': 1,
        'IN_USE': 2,
        'CHARGING': 3,
        'AVAILABLE': 4
    }

    # 提取序號數字
    serial_num = 0
    if unit.get('unit_serial'):
        try:
            serial_num = int(unit['unit_serial'].split('-')[-1])
        except:
            pass

    return (
        status_priority.get(unit.get('status', 'AVAILABLE'), 5),
        unit.get('level_percent', 100),
        -serial_num  # 負號讓大序號優先移除
    )


@app.get("/api/v2/equipment/{equipment_id}/units")
async def get_equipment_units_v2(
    equipment_id: str,
    include_inactive: bool = Query(default=False, description="是否包含已移除單位")
):
    """
    取得設備單位列表 (v2.1)

    Args:
        equipment_id: 設備ID
        include_inactive: 是否包含已移除單位

    Returns:
        設備單位列表及摘要
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 檢查設備是否存在
        cursor.execute("""
            SELECT e.id, e.name, e.type_code, et.unit_prefix, et.label_template
            FROM equipment e
            LEFT JOIN equipment_types et ON e.type_code = et.type_code
            WHERE e.id = ?
        """, (equipment_id,))
        eq_row = cursor.fetchone()
        if not eq_row:
            raise HTTPException(status_code=404, detail=f"設備不存在: {equipment_id}")

        # 取得 active units (including O2 claim columns)
        cursor.execute("""
            SELECT id, unit_serial, unit_label, level_percent, status,
                   last_check, checked_by, remarks, is_active,
                   claimed_by_case_id, claimed_at, claimed_by_user_id
            FROM equipment_units
            WHERE equipment_id = ? AND (is_active = 1 OR is_active IS NULL)
            ORDER BY unit_serial
        """, (equipment_id,))
        active_units = [dict(row) for row in cursor.fetchall()]

        # 取得 inactive units
        inactive_units = []
        if include_inactive:
            cursor.execute("""
                SELECT id, unit_serial, unit_label, level_percent, status,
                       is_active, removed_at, removed_by, removal_reason
                FROM equipment_units
                WHERE equipment_id = ? AND is_active = 0
                ORDER BY removed_at DESC
            """, (equipment_id,))
            inactive_units = [dict(row) for row in cursor.fetchall()]

        return {
            "equipment_id": eq_row[0],
            "equipment_name": eq_row[1],
            "type_code": eq_row[2],
            "unit_prefix": eq_row[3],
            "label_template": eq_row[4],
            "active_count": len(active_units),
            "inactive_count": len(inactive_units) if include_inactive else None,
            "units": active_units,
            "inactive_units": inactive_units if include_inactive else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取得設備單位列表失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/equipment/{equipment_id}/units", status_code=201)
async def add_equipment_unit_v2(equipment_id: str, request: UnitAddRequest):
    """
    新增設備單位 (v2.1)

    Args:
        equipment_id: 設備ID
        request: 新增請求

    Returns:
        新增的單位資訊及設備摘要
    """
    MAX_RETRY = 3

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 檢查設備是否存在
        cursor.execute("SELECT id, name FROM equipment WHERE id = ?", (equipment_id,))
        eq_row = cursor.fetchone()
        if not eq_row:
            raise HTTPException(status_code=404, detail=f"設備不存在: {equipment_id}")

        # 生成序號（含重試機制）
        unit_serial = None
        unit_label = None
        for attempt in range(MAX_RETRY):
            try:
                unit_serial, unit_label = _generate_next_serial(cursor, equipment_id)

                cursor.execute("""
                    INSERT INTO equipment_units
                    (equipment_id, unit_serial, unit_label, level_percent, status, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, datetime('now'))
                """, (equipment_id, unit_serial, unit_label, request.level_percent, request.status))

                break
            except sqlite3.IntegrityError:
                if attempt == MAX_RETRY - 1:
                    raise HTTPException(status_code=409, detail="序號生成衝突，請重試")
                continue

        unit_id = cursor.lastrowid

        # 記錄生命週期事件
        event_id = _record_lifecycle_event(
            cursor, unit_id, equipment_id, 'CREATE',
            reason=request.reason,
            snapshot={
                'unit_serial': unit_serial,
                'unit_label': unit_label,
                'level_percent': request.level_percent,
                'status': request.status
            }
        )

        conn.commit()

        # 取得設備摘要
        summary = _get_equipment_summary(cursor, equipment_id)

        return {
            "success": True,
            "unit": {
                "id": unit_id,
                "equipment_id": equipment_id,
                "unit_serial": unit_serial,
                "unit_label": unit_label,
                "level_percent": request.level_percent,
                "status": request.status,
                "is_active": True
            },
            "equipment_summary": summary,
            "event_id": event_id,
            "message": f"已新增 {unit_label}，目前共 {summary['active_unit_count']} 支"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"新增設備單位失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/v2/equipment/units/{unit_id}")
async def update_equipment_unit_v2(unit_id: int, request: UnitUpdateRequest):
    """
    更新設備單位屬性 (v2.1)

    Args:
        unit_id: 單位ID
        request: 更新請求

    Returns:
        更新後的單位資訊及變更紀錄
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 取得現有單位資訊
        cursor.execute("""
            SELECT equipment_id, unit_serial, unit_label, level_percent, status, is_active
            FROM equipment_units WHERE id = ?
        """, (unit_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"單位不存在: {unit_id}")

        if row[5] == 0:
            raise HTTPException(status_code=400, detail="無法更新已移除的單位")

        equipment_id = row[0]
        old_values = {
            'unit_label': row[2],
            'level_percent': row[3],
            'status': row[4]
        }

        # 建構更新語句
        updates = []
        params = []
        changes = {}

        if request.level_percent is not None and request.level_percent != old_values['level_percent']:
            updates.append("level_percent = ?")
            params.append(request.level_percent)
            changes['level_percent'] = {'from': old_values['level_percent'], 'to': request.level_percent}

        if request.status is not None and request.status != old_values['status']:
            updates.append("status = ?")
            params.append(request.status)
            changes['status'] = {'from': old_values['status'], 'to': request.status}

        if request.unit_label is not None and request.unit_label != old_values['unit_label']:
            updates.append("unit_label = ?")
            params.append(request.unit_label)
            changes['unit_label'] = {'from': old_values['unit_label'], 'to': request.unit_label}

        if not updates:
            return {
                "success": True,
                "unit": {
                    "id": unit_id,
                    "unit_serial": row[1],
                    "unit_label": old_values['unit_label'],
                    "level_percent": old_values['level_percent'],
                    "status": old_values['status']
                },
                "changes": {},
                "message": "無變更"
            }

        updates.append("updated_at = datetime('now')")
        params.append(unit_id)

        cursor.execute(f"""
            UPDATE equipment_units SET {', '.join(updates)} WHERE id = ?
        """, params)

        # 記錄生命週期事件
        _record_lifecycle_event(
            cursor, unit_id, equipment_id, 'UPDATE',
            snapshot={'changes': changes}
        )

        conn.commit()

        # 取得更新後的資料
        cursor.execute("""
            SELECT unit_serial, unit_label, level_percent, status
            FROM equipment_units WHERE id = ?
        """, (unit_id,))
        new_row = cursor.fetchone()

        return {
            "success": True,
            "unit": {
                "id": unit_id,
                "unit_serial": new_row[0],
                "unit_label": new_row[1],
                "level_percent": new_row[2],
                "status": new_row[3]
            },
            "changes": changes
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新設備單位失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v2/equipment/units/{unit_id}")
async def remove_equipment_unit_v2(unit_id: int, request: UnitRemoveRequest = None):
    """
    移除設備單位 (Soft Delete) (v2.1)

    Args:
        unit_id: 單位ID
        request: 移除請求（可選，包含原因和操作者）

    Returns:
        移除的單位資訊及設備摘要
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 取得現有單位資訊
        cursor.execute("""
            SELECT equipment_id, unit_serial, unit_label, level_percent, status, is_active
            FROM equipment_units WHERE id = ?
        """, (unit_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"單位不存在: {unit_id}")

        if row[5] == 0:
            raise HTTPException(status_code=400, detail="單位已被移除")

        equipment_id = row[0]
        reason = request.reason if request else None
        actor = request.actor if request else None

        # 執行 soft delete
        cursor.execute("""
            UPDATE equipment_units
            SET is_active = 0, removed_at = datetime('now'),
                removed_by = ?, removal_reason = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (actor, reason, unit_id))

        # 記錄生命週期事件
        event_id = _record_lifecycle_event(
            cursor, unit_id, equipment_id, 'SOFT_DELETE',
            actor=actor, reason=reason,
            snapshot={
                'unit_serial': row[1],
                'unit_label': row[2],
                'level_percent': row[3],
                'status': row[4]
            }
        )

        conn.commit()

        # 取得設備摘要
        summary = _get_equipment_summary(cursor, equipment_id)

        return {
            "success": True,
            "removed_unit": {
                "id": unit_id,
                "unit_serial": row[1],
                "unit_label": row[2],
                "level_percent": row[3],
                "removed_at": datetime.now().isoformat(),
                "removal_reason": reason
            },
            "equipment_summary": summary,
            "event_id": event_id,
            "message": f"已移除 {row[2]}，目前剩餘 {summary['active_unit_count']} 支"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移除設備單位失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/equipment/units/{unit_id}/restore")
async def restore_equipment_unit_v2(unit_id: int):
    """
    恢復已移除的設備單位 (v2.1)

    Args:
        unit_id: 單位ID

    Returns:
        恢復的單位資訊及設備摘要
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 取得現有單位資訊
        cursor.execute("""
            SELECT equipment_id, unit_serial, unit_label, level_percent, status, is_active
            FROM equipment_units WHERE id = ?
        """, (unit_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"單位不存在: {unit_id}")

        if row[5] == 1 or row[5] is None:
            raise HTTPException(status_code=400, detail="單位未被移除，無需恢復")

        equipment_id = row[0]

        # 恢復單位
        cursor.execute("""
            UPDATE equipment_units
            SET is_active = 1, removed_at = NULL, removed_by = NULL,
                removal_reason = NULL, updated_at = datetime('now')
            WHERE id = ?
        """, (unit_id,))

        # 記錄生命週期事件
        _record_lifecycle_event(
            cursor, unit_id, equipment_id, 'RESTORE',
            snapshot={
                'unit_serial': row[1],
                'unit_label': row[2]
            }
        )

        conn.commit()

        # 取得設備摘要
        summary = _get_equipment_summary(cursor, equipment_id)

        return {
            "success": True,
            "restored_unit": {
                "id": unit_id,
                "unit_serial": row[1],
                "unit_label": row[2]
            },
            "equipment_summary": summary,
            "message": f"已恢復 {row[2]}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢復設備單位失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v2/equipment/{equipment_id}/quantity")
async def batch_adjust_quantity_v2(equipment_id: str, request: BatchQuantityRequest):
    """
    批次調整設備數量（智慧縮減）(v2.1)

    Args:
        equipment_id: 設備ID
        request: 批次調整請求

    Returns:
        調整結果，包含新增/移除的單位清單
    """
    import uuid
    correlation_id = f"batch-{uuid.uuid4().hex[:8]}"

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 檢查設備是否存在
        cursor.execute("SELECT id, name FROM equipment WHERE id = ?", (equipment_id,))
        eq_row = cursor.fetchone()
        if not eq_row:
            raise HTTPException(status_code=404, detail=f"設備不存在: {equipment_id}")

        # 取得目前 active 單位
        cursor.execute("""
            SELECT id, unit_serial, unit_label, level_percent, status, last_check
            FROM equipment_units
            WHERE equipment_id = ? AND (is_active = 1 OR is_active IS NULL)
            ORDER BY unit_serial
        """, (equipment_id,))
        active_units = [dict(row) for row in cursor.fetchall()]
        current_quantity = len(active_units)

        target = request.target_quantity
        units_added = []
        units_removed = []

        if target > current_quantity:
            # 需要新增
            add_count = target - current_quantity
            for _ in range(add_count):
                unit_serial, unit_label = _generate_next_serial(cursor, equipment_id)
                cursor.execute("""
                    INSERT INTO equipment_units
                    (equipment_id, unit_serial, unit_label, level_percent, status, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, datetime('now'))
                """, (equipment_id, unit_serial, unit_label,
                      request.default_level_percent, request.default_status))

                unit_id = cursor.lastrowid
                _record_lifecycle_event(
                    cursor, unit_id, equipment_id, 'CREATE',
                    reason=request.reason,
                    snapshot={'unit_serial': unit_serial, 'unit_label': unit_label,
                              'level_percent': request.default_level_percent},
                    correlation_id=correlation_id
                )
                units_added.append({
                    "id": unit_id,
                    "label": unit_label,
                    "level_percent": request.default_level_percent
                })

        elif target < current_quantity:
            # 需要移除（智慧縮減）
            remove_count = current_quantity - target

            # 根據優先順序排序
            sorted_units = sorted(active_units, key=_get_removal_priority)
            to_remove = sorted_units[:remove_count]

            for unit in to_remove:
                # 決定移除原因
                if unit['status'] == 'EMPTY':
                    reason_note = "空瓶優先移除"
                elif unit['level_percent'] < 30:
                    reason_note = "低電量優先移除"
                else:
                    reason_note = "依排序移除"

                cursor.execute("""
                    UPDATE equipment_units
                    SET is_active = 0, removed_at = datetime('now'),
                        removal_reason = ?, updated_at = datetime('now')
                    WHERE id = ?
                """, (f"批次調整: {reason_note}", unit['id']))

                _record_lifecycle_event(
                    cursor, unit['id'], equipment_id, 'SOFT_DELETE',
                    reason=f"批次調整: {request.reason or '數量調整'}",
                    snapshot={
                        'unit_serial': unit['unit_serial'],
                        'level_percent': unit['level_percent'],
                        'status': unit['status']
                    },
                    correlation_id=correlation_id
                )

                units_removed.append({
                    "id": unit['id'],
                    "label": unit['unit_label'],
                    "level_percent": unit['level_percent'],
                    "reason": reason_note
                })

        conn.commit()

        # 取得設備摘要
        summary = _get_equipment_summary(cursor, equipment_id)

        action = "expand" if target > current_quantity else ("shrink" if target < current_quantity else "no_change")

        return {
            "success": True,
            "equipment_id": equipment_id,
            "previous_quantity": current_quantity,
            "new_quantity": target,
            "action": action,
            "units_added": units_added,
            "units_removed": units_removed,
            "equipment_summary": summary,
            "correlation_id": correlation_id,
            "message": f"已從 {current_quantity} 支調整為 {target} 支"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批次調整數量失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/equipment/lifecycle-events")
async def get_lifecycle_events_v2(
    equipment_id: Optional[str] = Query(None, description="設備ID篩選"),
    unit_id: Optional[int] = Query(None, description="單位ID篩選"),
    event_type: Optional[str] = Query(None, description="事件類型篩選"),
    limit: int = Query(default=50, le=200, description="筆數限制"),
    offset: int = Query(default=0, ge=0, description="偏移量")
):
    """
    查詢設備生命週期事件 (v2.1)

    Args:
        equipment_id: 設備ID篩選
        unit_id: 單位ID篩選
        event_type: 事件類型篩選 (CREATE, SOFT_DELETE, RESTORE, UPDATE)
        limit: 筆數限制
        offset: 偏移量

    Returns:
        生命週期事件列表
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # 建構查詢
        conditions = []
        params = []

        if equipment_id:
            conditions.append("equipment_id = ?")
            params.append(equipment_id)
        if unit_id:
            conditions.append("unit_id = ?")
            params.append(unit_id)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 計算總數
        cursor.execute(f"SELECT COUNT(*) FROM equipment_lifecycle_events {where_clause}", params)
        total = cursor.fetchone()[0]

        # 取得資料
        params.extend([limit, offset])
        cursor.execute(f"""
            SELECT id, unit_id, equipment_id, event_type, actor, reason,
                   snapshot_json, correlation_id, station_id, created_at
            FROM equipment_lifecycle_events
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params)

        events = []
        for row in cursor.fetchall():
            snapshot = None
            if row[6]:
                try:
                    snapshot = json.loads(row[6])
                except:
                    snapshot = row[6]

            events.append({
                "id": row[0],
                "unit_id": row[1],
                "equipment_id": row[2],
                "event_type": row[3],
                "actor": row[4],
                "reason": row[5],
                "snapshot": snapshot,
                "correlation_id": row[7],
                "station_id": row[8],
                "created_at": row[9]
            })

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": events
        }
    except Exception as e:
        logger.error(f"查詢生命週期事件失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 啟動
# ============================================================================

if __name__ == "__main__":
    # v1.4.8 單站版

    print("=" * 70)
    print(f"🏥 BORP備援手術站庫存管理系統（單站版）v{config.VERSION}")
    print("=" * 70)
    print(f"📁 資料庫: {config.DATABASE_PATH}")
    print(f"🏢 站點ID: {config.get_station_id()}")
    print(f"🏷️  站點名稱: {config.get_station_name()}")
    print(f"🏥 組織: {config.ORG_NAME}")
    print(f"🌐 服務位址: http://0.0.0.0:8090")
    print(f"📖 API文件: http://localhost:8090/docs")
    print(f"📊 健康檢查: http://localhost:8090/api/health")
    print("=" * 70)
    print("✨ v1.4.8 功能:")
    print("   - 藥品整合至庫存查詢 (MED- 前綴區分)")
    print("   - 庫存查詢分類篩選 (全部/藥品/耗材)")
    print("   - 血袋標籤多張排列列印 (A4紙 ~12張/頁)")
    print("   - 動態 API URL (支援遠端存取)")
    print("   - 單站版簡化架構")
    print("   - 📱 Mobile API v1 (巡房助手 PWA)")
    print("=" * 70)
    print("📱 Mobile API: http://localhost:8090/api/mirs-mobile/v1/info")
    print("=" * 70)
    print("按 Ctrl+C 停止服務")
    print("=" * 70)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8090,
        log_level="info",
        access_log=True
    )
