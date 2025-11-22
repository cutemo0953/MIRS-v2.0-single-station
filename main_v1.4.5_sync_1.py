#!/usr/bin/env python3
"""
醫療站庫存管理系統 - 後端 API
版本: v1.4.1
新增: 手術記錄管理、匯出功能
"""

import logging
import sys
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

from fastapi import FastAPI, HTTPException, status, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator
import uvicorn

# v1.4.5新增: 緊急功能相關套件
import qrcode
from io import BytesIO
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
# 日誌配置
# ============================================================================

def setup_logging():
    """設定日誌系統"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('medical_inventory.log', encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# ============================================================================
# 配置
# ============================================================================

class Config:
    """系統配置"""
    VERSION = "1.4.5"
    DATABASE_PATH = "medical_inventory.db"
    STATION_ID = "TC-01"
    DEBUG = True

    # 血型列表
    BLOOD_TYPES = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']

config = Config()


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
    stationId: str = Field(default="TC-01", description="站點ID")

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
    stationId: str = Field(default="TC-01", description="站點ID")


class BloodRequest(BaseModel):
    """血袋請求"""
    bloodType: str = Field(..., description="血型")
    quantity: int = Field(..., gt=0, description="數量(U)必須大於0")
    stationId: str = Field(default="TC-01", description="站點ID")

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
    stationId: str = Field(default="TC-01", description="站點ID")
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
    stationId: str = Field(default="TC-01", description="站點ID")
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
    surgeryType: str = Field(..., description="手術類型", min_length=1, max_length=200)
    surgeonName: str = Field(..., description="主刀醫師", min_length=1, max_length=100)
    anesthesiaType: Optional[str] = Field(None, description="麻醉方式", max_length=100)
    durationMinutes: Optional[int] = Field(None, ge=0, description="手術時長(分鐘)")
    remarks: Optional[str] = Field(None, description="手術備註", max_length=2000)
    consumptions: List[SurgeryConsumptionItem] = Field(..., description="使用耗材清單")
    stationId: str = Field(default="TC-01", description="站點ID")


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

class DatabaseManager:
    """資料庫管理器 - 處理所有資料庫操作"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        logger.info(f"初始化資料庫: {db_path}")
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """取得資料庫連接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """初始化資料庫結構"""
        logger.info("開始初始化資料庫結構...")
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 物品主檔
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    unit TEXT DEFAULT 'EA',
                    min_stock INTEGER DEFAULT 5,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
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
                    FOREIGN KEY (item_code) REFERENCES items(code)
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
            
            # 血袋庫存（支援多站點）
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
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

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

            # 設備主檔
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
                    FOREIGN KEY (item_code) REFERENCES items(code)
                )
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
                    FOREIGN KEY (item_code) REFERENCES items(code)
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

            # 醫院日報表（谷盺公司向中央回報用）
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

            # 初始化預設設備
            self._init_default_equipment(cursor)

            # 初始化預設醫院和站點（聯邦架構）
            self._init_hospitals_and_stations(cursor)

            # 初始化血型庫存
            for blood_type in config.BLOOD_TYPES:
                cursor.execute("""
                    INSERT OR IGNORE INTO blood_inventory (blood_type, quantity, station_id)
                    VALUES (?, 0, ?)
                """, (blood_type, config.STATION_ID))

            conn.commit()
            logger.info("資料庫初始化完成")
            
        except Exception as e:
            logger.error(f"資料庫初始化失敗: {e}")
            conn.rollback()
            raise
        finally:
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
        """初始化預設醫院和站點（聯邦架構）"""
        # 建立預設醫院 HOSP-001
        cursor.execute("""
            INSERT OR IGNORE INTO hospitals (
                hospital_id, hospital_name, hospital_type, command_level,
                network_access, total_stations, operational_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            'HOSP-001',
            '前線第一醫院',
            'FIELD_HOSPITAL',
            'LOCAL',
            'MILITARY',  # 醫院行政單位有軍警管道網路
            0,  # 初始值，後續會更新
            'ACTIVE'
        ))

        # 建立當前站點（從 config.STATION_ID 讀取）
        station_id = getattr(config, 'STATION_ID', 'TC-01')
        cursor.execute("""
            INSERT OR IGNORE INTO stations (
                station_id, station_name, hospital_id, station_type,
                network_access, operational_status, sync_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            station_id,
            f'醫療站 {station_id}',
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

        logger.info(f"已初始化預設醫院 HOSP-001 與站點 {station_id}")

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
                SELECT code FROM items 
                WHERE code LIKE ? 
                ORDER BY code DESC 
                LIMIT 1
            """, (f"{prefix}-%",))
            
            result = cursor.fetchone()
            
            if result:
                last_code = result['code']
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
                    record_number, record_date, patient_name, surgery_sequence,
                    surgery_type, surgeon_name, anesthesia_type, duration_minutes,
                    remarks, station_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_number,
                record_date,
                request.patientName,
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

    def get_stats(self) -> Dict[str, int]:
        """取得系統統計"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 品項總數
            cursor.execute("SELECT COUNT(*) as count FROM items")
            total_items = cursor.fetchone()['count']
            
            # 庫存警戒數
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM (
                    SELECT 
                        i.code,
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
                    ) stock ON i.code = stock.item_code
                ) t
                WHERE t.current_stock < t.min_stock
            """)
            low_stock = cursor.fetchone()['count']
            
            # 全血總量
            cursor.execute("SELECT SUM(quantity) as total FROM blood_inventory")
            total_blood = cursor.fetchone()['total'] or 0
            
            # 設備警戒數
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM equipment 
                WHERE status IN ('WARNING', 'ERROR')
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
            cursor.execute("SELECT name FROM items WHERE code = ?", (request.itemCode,))
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
                "message": f"物品 {item['name']} 進貨 {request.quantity} 已記錄"
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
            cursor.execute("SELECT name FROM items WHERE code = ?", (request.itemCode,))
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
                "message": f"物品 {item['name']} 消耗 {request.quantity} 已記錄"
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
        """血袋處理（支援多站點）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT quantity FROM blood_inventory WHERE blood_type = ? AND station_id = ?",
                (request.bloodType, request.stationId)
            )
            blood = cursor.fetchone()

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
            
            cursor.execute("""
                INSERT INTO blood_events 
                (event_type, blood_type, quantity, station_id)
                VALUES (?, ?, ?, ?)
            """, (event_type, request.bloodType, request.quantity, request.stationId))
            
            conn.commit()
            logger.info(f"血袋{action}記錄成功: {request.bloodType} {'+' if action=='receive' else '-'}{request.quantity}U")
            
            action_text = "入庫" if action == "receive" else "出庫"
            return {
                "success": True,
                "message": f"血袋 {request.bloodType} {action_text} {request.quantity}U 已記錄",
                "newQuantity": new_quantity
            }
        
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"血袋處理失敗: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()
    
    def get_blood_inventory(self, station_id: str = None) -> List[Dict]:
        """取得血袋庫存（支援多站點）"""
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
        """每日重置設備狀態（清空備註、重置為UNCHECKED）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE equipment
                SET status = 'UNCHECKED',
                    remarks = NULL,
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

    def get_equipment_status(self) -> List[Dict[str, Any]]:
        """取得所有設備狀態"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    id, name, category, quantity, status,
                    last_check, power_level, remarks
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
                    i.code, i.name, i.unit, i.min_stock, i.category,
                    COALESCE(stock.current_stock, 0) as current_stock
                FROM items i
                LEFT JOIN (
                    SELECT item_code,
                           SUM(CASE WHEN event_type = 'RECEIVE' THEN quantity
                                    WHEN event_type = 'CONSUME' THEN -quantity
                                    ELSE 0 END) as current_stock
                    FROM inventory_events
                    GROUP BY item_code
                ) stock ON i.code = stock.item_code
                ORDER BY i.category, i.name
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
                    e.id, e.event_type, e.item_code, i.name as item_name,
                    e.quantity, i.unit, e.batch_number, e.expiry_date,
                    e.remarks, e.station_id, e.operator, e.timestamp
                FROM inventory_events e
                LEFT JOIN items i ON e.item_code = i.code
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
                    cursor.execute(f"""
                        SELECT * FROM {table}
                        WHERE station_id = ? AND {timestamp_col} > ?
                        ORDER BY {timestamp_col}
                    """, (station_id, since_timestamp))

                    rows = cursor.fetchall()
                    for row in rows:
                        changes.append({
                            'table': table,
                            'operation': 'INSERT',
                            'data': dict(row),
                            'timestamp': row[timestamp_col]
                        })

            else:
                # 全量同步：收集所有資料
                # 庫存物品
                cursor.execute("SELECT * FROM items")
                for row in cursor.fetchall():
                    changes.append({
                        'table': 'items',
                        'operation': 'INSERT',
                        'data': dict(row),
                        'timestamp': row['updated_at'] if 'updated_at' in row.keys() else now.isoformat()
                    })

                # 所有事件記錄（僅本站點）
                cursor.execute("SELECT * FROM inventory_events WHERE station_id = ?", (station_id,))
                for row in cursor.fetchall():
                    changes.append({
                        'table': 'inventory_events',
                        'operation': 'INSERT',
                        'data': dict(row),
                        'timestamp': row['timestamp']
                    })

                cursor.execute("SELECT * FROM blood_events WHERE station_id = ?", (station_id,))
                for row in cursor.fetchall():
                    changes.append({
                        'table': 'blood_events',
                        'operation': 'INSERT',
                        'data': dict(row),
                        'timestamp': row['timestamp']
                    })

                cursor.execute("SELECT * FROM equipment_checks WHERE station_id = ?", (station_id,))
                for row in cursor.fetchall():
                    changes.append({
                        'table': 'equipment_checks',
                        'operation': 'INSERT',
                        'data': dict(row),
                        'timestamp': row['timestamp']
                    })

                cursor.execute("SELECT * FROM surgery_records WHERE station_id = ?", (station_id,))
                for row in cursor.fetchall():
                    changes.append({
                        'table': 'surgery_records',
                        'operation': 'INSERT',
                        'data': dict(row),
                        'timestamp': row['created_at']
                    })

            # 計算校驗碼
            package_content = json.dumps(changes, ensure_ascii=False, sort_keys=True)
            checksum = hashlib.sha256(package_content.encode('utf-8')).hexdigest()
            package_size = len(package_content.encode('utf-8'))

            # 記錄封包到資料庫
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
                'PENDING', package_size, checksum, len(changes), 'PENDING'
            ))

            conn.commit()

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

    def import_sync_package(self, package_id: str, changes: List[dict], checksum: str) -> dict:
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
                        # 建立 UPDATE 語句（暫時簡化實作）
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
                package_id, 'IMPORT', 'EXTERNAL', 'UNKNOWN',
                'STATION', 'LOCAL', 'HOSP-001',
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

    def upload_sync_package(self, station_id: str, package_id: str, changes: List[dict], checksum: str) -> dict:
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

        # 匯入變更（複用 import_sync_package 邏輯）
        result = self.import_sync_package(package_id, changes, checksum)

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

db = DatabaseManager(config.DATABASE_PATH)


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


@app.on_event("startup")
async def startup_event():
    """應用啟動時執行"""
    # 啟動每日設備重置背景任務
    asyncio.create_task(daily_equipment_reset())
    logger.info("✓ 每日設備重置背景任務已啟動 (07:00am)")


# ============================================================================
# API 端點
# ============================================================================

@app.get("/")
async def root():
    """根端點"""
    return {
        "name": "醫療站庫存管理系統 API",
        "version": config.VERSION,
        "station": config.STATION_ID,
        "docs": "/docs"
    }


@app.get("/api/health")
async def health_check():
    """健康檢查"""
    return {
        "status": "healthy",
        "version": config.VERSION,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/stats")
async def get_stats():
    """取得系統統計"""
    try:
        stats = db.get_stats()
        return stats
    except Exception as e:
        logger.error(f"取得統計失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 物品管理 API ==========

@app.get("/api/items")
async def get_items():
    """取得所有物品"""
    try:
        items = db.get_inventory_items()
        return {"items": items, "count": len(items)}
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
        if not request.code or request.code.strip() == '':
            item_code = db.generate_item_code(request.category)
        else:
            item_code = request.code
            cursor.execute("SELECT code FROM items WHERE code = ?", (item_code,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"物品代碼 {item_code} 已存在")
        
        cursor.execute("""
            INSERT INTO items (code, name, unit, min_stock, category)
            VALUES (?, ?, ?, ?, ?)
        """, (item_code, request.name, request.unit, request.minStock, request.category))
        
        conn.commit()
        
        return {
            "success": True,
            "message": f"物品 {request.name} 新增成功",
            "item": {
                "code": item_code,
                "name": request.name,
                "unit": request.unit,
                "minStock": request.minStock,
                "category": request.category
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.put("/api/items/{code}")
async def update_item(code: str, request: ItemUpdateRequest):
    """更新物品"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT code FROM items WHERE code = ?", (code,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"物品代碼 {code} 不存在")
        
        update_fields = []
        update_values = []
        
        if request.name: update_fields.append("name = ?"); update_values.append(request.name)
        if request.unit: update_fields.append("unit = ?"); update_values.append(request.unit)
        if request.minStock is not None: update_fields.append("min_stock = ?"); update_values.append(request.minStock)
        if request.category: update_fields.append("category = ?"); update_values.append(request.category)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="沒有提供要更新的欄位")
        
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_values.append(code)
        
        cursor.execute(f"UPDATE items SET {', '.join(update_fields)} WHERE code = ?", update_values)
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
        cursor.execute("SELECT name FROM items WHERE code = ?", (code,))
        item = cursor.fetchone()
        if not item:
            raise HTTPException(status_code=404, detail=f"物品代碼 {code} 不存在")
        
        cursor.execute("DELETE FROM items WHERE code = ?", (code,))
        conn.commit()
        
        return {"success": True, "message": f"物品 {item['name']} 已刪除"}
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
    """取得血袋庫存（支援多站點）"""
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
    station_id: str = Query("TC-01"),
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
    station_id: str = Query("TC-01", description="站點ID"),
    remarks: str = Query("", description="批號或備註")
):
    """取得一般血袋批次標籤 (HTML) - 用於列印"""
    try:
        from datetime import datetime

        # 生成批次編號
        now = datetime.now()
        batch_number = f"BATCH-{station_id}-{now.strftime('%Y%m%d-%H%M%S')}"

        # 生成HTML標籤
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>血袋批次標籤 - {blood_type}</title>
    <style>
        @media print {{
            @page {{ size: 10cm 6cm; margin: 0; }}
            body {{ margin: 0.5cm; }}
        }}
        body {{
            font-family: 'Microsoft JhengHei', 'SimHei', sans-serif;
            font-size: 12pt;
            line-height: 1.4;
        }}
        .label {{
            width: 9cm;
            height: 5cm;
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
            background-color: #f0f0f0;
        }}
        .blood-type {{
            font-size: 32pt;
            font-weight: bold;
            color: #d00;
            text-align: center;
            margin: 8px 0;
        }}
        .info {{
            font-size: 10pt;
            margin: 3px 0;
        }}
        .code {{
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 10pt;
        }}
        .quantity {{
            font-size: 18pt;
            font-weight: bold;
            color: #d00;
            text-align: center;
            margin: 5px 0;
        }}
        .warning {{
            color: #d00;
            font-weight: bold;
            font-size: 9pt;
            text-align: center;
            margin-top: 5px;
            border-top: 1px solid #000;
            padding-top: 3px;
        }}
    </style>
</head>
<body onload="window.print();">
    <div class="label">
        <div class="header">血袋批次標籤 BLOOD BAG BATCH</div>
        <div class="blood-type">{blood_type}</div>
        <div class="quantity">數量: {quantity} U</div>
        <div class="info">批號: <span class="code">{batch_number}</span></div>
        <div class="info">站點: {station_id}</div>
        <div class="info">入庫時間: {now.strftime('%Y-%m-%d %H:%M')}</div>
        {f'<div class="info">備註: {remarks}</div>' if remarks else ''}
        <div class="warning">⚠ 使用前請確認血型 ⚠</div>
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

        # 4. 在目標站點增加血袋（如果不存在則新增）
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
async def get_equipment_status():
    """取得所有設備狀態"""
    try:
        status = db.get_equipment_status()
        return {"equipment": status, "count": len(status)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/equipment")
async def get_equipment():
    """取得所有設備"""
    return await get_equipment_status()


@app.post("/api/equipment/check/{equipment_id}")
async def check_equipment(equipment_id: str, request: EquipmentCheckRequest):
    """設備檢查"""
    return db.check_equipment(equipment_id, request)


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


# ========== 庫存事件查詢與匯出 API (新增) ==========

@app.get("/api/inventory/events")
async def get_inventory_events(
    event_type: Optional[str] = Query(None, description="事件類型 RECEIVE/CONSUME"),
    start_date: Optional[str] = Query(None, description="開始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="結束日期 YYYY-MM-DD"),
    item_code: Optional[str] = Query(None, description="物品代碼(模糊搜尋)"),
    limit: int = Query(100, ge=1, le=1000, description="最大回傳筆數")
):
    """查詢庫存事件記錄（進貨/消耗）"""
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
  - inventory.csv     庫存清單
  - blood_inventory.csv  血袋庫存
  - equipment.csv     設備清單
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


@app.get("/api/emergency/info")
async def get_emergency_info():
    """取得緊急資訊（用於QR Code掃描後顯示）"""
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
    """緊急資訊顯示頁面（QR Code掃描後跳轉）"""
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
        # 獲取請求的主機名稱（支持手機掃描）
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
    - stationId: 站點ID (e.g., TC-01)
    - hospitalId: 所屬醫院ID (e.g., HOSP-001)
    - syncType: DELTA (增量) 或 FULL (全量)
    - sinceTimestamp: 增量同步起始時間 (可選)

    返回:
    - package_id: 封包ID
    - checksum: SHA-256 校驗碼
    - changes: 變更記錄清單
    """
    try:
        result = db.generate_sync_package(
            station_id=request.stationId,
            hospital_id=request.hospitalId,
            sync_type=request.syncType,
            since_timestamp=request.sinceTimestamp
        )
        logger.info(f"同步封包已產生: {result['package_id']} ({result['changes_count']} 項變更)")
        return result
    except Exception as e:
        logger.error(f"產生同步封包失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/station/sync/import")
async def import_station_sync_package(request: SyncPackageUpload):
    """
    【站點層】匯入同步封包

    站點匯入從醫院層收到的同步封包（通常包含其他站點的更新）

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
        result = db.import_sync_package(
            package_id=request.packageId,
            changes=request.changes,
            checksum=request.checksum
        )
        logger.info(f"同步封包已匯入: {request.packageId} ({result['changes_applied']} 項變更)")
        return result
    except Exception as e:
        logger.error(f"匯入同步封包失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/hospital/sync/upload")
async def upload_hospital_sync(request: SyncPackageUpload):
    """
    【醫院層】接收站點同步上傳

    醫院層接收站點上傳的同步封包（谷盺公司使用）

    參數:
    - stationId: 站點ID
    - packageId: 封包ID
    - changes: 變更記錄清單
    - checksum: 校驗碼

    返回:
    - changes_applied: 成功套用的變更數
    - response_package_id: 回傳封包ID（包含其他站點更新）
    """
    try:
        result = db.upload_sync_package(
            station_id=request.stationId,
            package_id=request.packageId,
            changes=request.changes,
            checksum=request.checksum
        )
        logger.info(f"醫院層已接收同步: {request.stationId} - {request.packageId}")
        return result
    except Exception as e:
        logger.error(f"醫院層接收同步失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/hospital/transfer/coordinate")
async def coordinate_hospital_transfer(request: HospitalTransferCoordinate):
    """
    【醫院層】院內調撥協調 (Phase 2)

    醫院層協調站點間物資調撥（谷盺公司使用）

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
# 啟動
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print(f"🏥 醫療站庫存管理系統 API v{config.VERSION}")
    print("=" * 70)
    print(f"📁 資料庫: {config.DATABASE_PATH}")
    print(f"🏢 站點ID: {config.STATION_ID}")
    print(f"🌐 服務位址: http://0.0.0.0:8000")
    print(f"📖 API文件: http://localhost:8000/docs")
    print(f"📊 健康檢查: http://localhost:8000/api/health")
    print("=" * 70)
    print("✨ v1.4.5 新功能:")
    print("   - UI 全面重構（Heroicons + 新色系）")
    print("   - 處置標籤頁整合（手術記錄 + 一般消耗）")
    print("   - 血庫管理增強（病患資訊 + 歷史記錄）")
    print("   - 設備自動刷新機制（每日 07:00am）")
    print("   - 響應式設計優化")
    print("=" * 70)
    print("按 Ctrl+C 停止服務")
    print("=" * 70)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
