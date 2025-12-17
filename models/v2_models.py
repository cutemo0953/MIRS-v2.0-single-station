"""
MIRS v2 API Models
Based on: EQUIPMENT_ARCHITECTURE_REDESIGN.md

Provides Pydantic models with proper JSON handling for SQLite TEXT columns.
Addresses Grok's feedback on type safety.
"""

import json
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum


# =============================================================================
# Enums
# =============================================================================

class ResilienceCategory(str, Enum):
    POWER = "POWER"
    OXYGEN = "OXYGEN"
    NONE = None


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    CHARGING = "CHARGING"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"
    EMPTY = "EMPTY"


class CheckStatus(str, Enum):
    CHECKED = "CHECKED"
    PARTIAL = "PARTIAL"
    UNCHECKED = "UNCHECKED"


class OverallStatus(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# =============================================================================
# Capacity Config Models (for JSON validation)
# =============================================================================

class LoadProfile(BaseModel):
    """負載情境設定 - Grok 建議的未來擴展結構"""
    low: float = Field(description="低負載消耗率")
    medium: float = Field(description="中負載消耗率")
    high: float = Field(description="高負載消耗率")


class CapacityConfig(BaseModel):
    """設備容量配置 - 支援多種計算策略"""
    strategy: str = Field(default="LINEAR", description="計算策略: LINEAR, FUEL_BASED, POWER_DEPENDENT, NONE")

    # Linear depletion (Power Station, O2 Cylinder)
    hours_per_100pct: Optional[float] = Field(None, description="100%存量可用時數")
    base_capacity_wh: Optional[float] = Field(None, description="電池容量 (Wh)")
    capacity_liters: Optional[float] = Field(None, description="氣體容量 (L)")
    flow_rate_lpm: Optional[float] = Field(None, description="流量 (L/min)")
    output_watts: Optional[float] = Field(None, description="輸出功率 (W)")

    # Fuel based (Generator)
    tank_liters: Optional[float] = Field(None, description="油箱容量 (L)")
    fuel_rate_lph: Optional[float] = Field(None, description="耗油率 (L/h)")

    # Power dependent (O2 Concentrator)
    requires_power: Optional[bool] = Field(None, description="是否需要電力")
    output_lpm: Optional[float] = Field(None, description="氧氣輸出 (L/min)")
    hours_unlimited: Optional[bool] = Field(None, description="無限供應（受限於電力）")

    # Future: Load profiles (Grok's suggestion)
    load_profiles: Optional[LoadProfile] = Field(None, description="負載情境配置")

    class Config:
        extra = "allow"  # Allow additional fields for extensibility


# =============================================================================
# Equipment Type Models
# =============================================================================

class EquipmentType(BaseModel):
    """設備類型定義"""
    type_code: str
    type_name: str
    category: str
    resilience_category: Optional[str] = None
    unit_label: str = "%"
    capacity_config: Optional[CapacityConfig] = None
    status_options: List[str] = []
    icon: Optional[str] = None
    color: Optional[str] = None

    @validator('capacity_config', pre=True)
    def parse_capacity_config(cls, v):
        """Parse JSON string to dict if needed (Grok's suggestion)"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    @validator('status_options', pre=True)
    def parse_status_options(cls, v):
        """Parse JSON string to list if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v or []


# =============================================================================
# Equipment Unit Models
# =============================================================================

class EquipmentUnit(BaseModel):
    """設備單位"""
    id: int
    equipment_id: str
    unit_serial: str
    unit_label: Optional[str] = None
    level_percent: int = Field(ge=0, le=100)
    status: str = "AVAILABLE"
    last_check: Optional[datetime] = None
    checked_by: Optional[str] = None
    remarks: Optional[str] = None
    hours: Optional[float] = None  # Calculated field


class EquipmentUnitCreate(BaseModel):
    """建立設備單位請求"""
    unit_serial: str
    unit_label: Optional[str] = None
    level_percent: int = Field(default=100, ge=0, le=100)
    status: str = "AVAILABLE"


class EquipmentUnitCheck(BaseModel):
    """設備單位檢查請求"""
    level_percent: int = Field(..., ge=0, le=100)
    status: str = Field(default="AVAILABLE")
    remarks: Optional[str] = None


# =============================================================================
# Equipment Models
# =============================================================================

class Equipment(BaseModel):
    """設備（含聚合狀態）"""
    id: str
    name: str
    type_code: str
    type_name: Optional[str] = None
    category: Optional[str] = None
    resilience_category: Optional[str] = None
    unit_count: int = 0
    avg_level: float = 0
    checked_count: int = 0
    last_check: Optional[datetime] = None
    check_status: str = "UNCHECKED"


class EquipmentDetail(Equipment):
    """設備詳情（含所有單位）"""
    capacity_config: Optional[CapacityConfig] = None
    status_options: List[str] = []
    remarks: Optional[str] = None
    units: List[EquipmentUnit] = []

    @validator('capacity_config', pre=True)
    def parse_capacity_config(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    @validator('status_options', pre=True)
    def parse_status_options(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v or []


# =============================================================================
# Resilience Dashboard Models
# =============================================================================

class CheckProgress(BaseModel):
    """檢查進度"""
    total: int
    checked: int
    percentage: int


class DashboardSummary(BaseModel):
    """儀表板摘要"""
    overall_status: str
    min_hours: float
    min_days: float
    limiting_factor: Optional[str] = None
    isolation_target_days: float
    check_progress: CheckProgress


class LifelineItem(BaseModel):
    """生命線項目"""
    equipment_id: str
    name: str
    type_code: str
    check_status: str
    units: List[Dict[str, Any]]


class Lifeline(BaseModel):
    """生命線（電力/氧氣）"""
    category: str
    name: str
    status: str
    total_hours: float
    items: List[LifelineItem]
    charging_warnings: List[str] = []


class ResilienceDashboard(BaseModel):
    """韌性儀表板完整回應"""
    station_id: str
    summary: DashboardSummary
    lifelines: List[Lifeline]


# =============================================================================
# API Response Models
# =============================================================================

class EquipmentTypesResponse(BaseModel):
    """設備類型列表回應"""
    types: List[EquipmentType]
    count: int


class EquipmentListResponse(BaseModel):
    """設備列表回應"""
    equipment: List[Equipment]
    count: int


class UnitCheckResponse(BaseModel):
    """單位檢查回應"""
    success: bool
    unit: EquipmentUnit
    equipment_aggregate: Dict[str, Any]


class UnitResetResponse(BaseModel):
    """單位重置回應"""
    success: bool
    unit_id: int
    equipment_id: str
    message: str
