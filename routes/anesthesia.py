"""
MIRS Anesthesia Module - Phase A
Event-Sourced, Offline-First Architecture

Version: 1.5.3
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/anesthesia", tags=["anesthesia"])

# Vercel demo mode detection (moved to top for availability in all endpoints)
IS_VERCEL = os.environ.get("VERCEL") == "1"

def get_demo_anesthesia_cases():
    """Generate demo cases with current timestamp (avoids stale dates)"""
    now = datetime.now()
    return [
        {
            "id": "ANES-DEMO-001",
            "patient_id": "P-DEMO-001",
            "patient_name": "王大明",
            "status": "IN_PROGRESS",
            "context_mode": "STANDARD",
            "planned_technique": "GA_ETT",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "started_at": (now - timedelta(hours=1)).isoformat(),
            "actor_id": "demo-user"
        },
        {
            "id": "ANES-DEMO-002",
            "patient_id": "P-DEMO-002",
            "patient_name": "林小華",
            "status": "PREOP",
            "context_mode": "STANDARD",
            "planned_technique": "RA_SPINAL",
            "created_at": (now - timedelta(minutes=30)).isoformat(),
            "started_at": (now - timedelta(minutes=30)).isoformat(),
            "actor_id": "demo-user"
        },
        {
            "id": "ANES-DEMO-003",
            "patient_id": "P-DEMO-003",
            "patient_name": "張美玲",
            "status": "CLOSED",
            "context_mode": "STANDARD",
            "planned_technique": "GA_LMA",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "started_at": (now - timedelta(hours=3)).isoformat(),
            "actor_id": "demo-user"
        }
    ]


# =============================================================================
# Enums
# =============================================================================

class ContextMode(str, Enum):
    STANDARD = "STANDARD"
    BATTLEFIELD = "BATTLEFIELD"


class CaseStatus(str, Enum):
    PREOP = "PREOP"
    IN_PROGRESS = "IN_PROGRESS"
    PACU = "PACU"
    CLOSED = "CLOSED"


class AnesthesiaTechnique(str, Enum):
    GA_ETT = "GA_ETT"           # General Anesthesia with ETT
    GA_LMA = "GA_LMA"           # General Anesthesia with LMA
    GA_MASK = "GA_MASK"         # General Anesthesia with Mask
    RA_SPINAL = "RA_SPINAL"     # Regional - Spinal
    RA_EPIDURAL = "RA_EPIDURAL" # Regional - Epidural
    RA_NERVE = "RA_NERVE"       # Regional - Nerve Block
    LA = "LA"                   # Local Anesthesia
    SEDATION = "SEDATION"       # Monitored Anesthesia Care / Sedation


class EventType(str, Enum):
    # === 生命徵象 ===
    VITAL_SIGN = "VITAL_SIGN"

    # === 藥物 (v1.6.1 新增 VASOACTIVE) ===
    MEDICATION_ADMIN = "MEDICATION_ADMIN"
    VASOACTIVE_BOLUS = "VASOACTIVE_BOLUS"          # 昇壓劑/降壓劑 單次給藥
    VASOACTIVE_INFUSION = "VASOACTIVE_INFUSION"    # 昇壓劑 幫浦調整

    # === 輸液/輸血 (v1.6.1 新增 FLUID_BOLUS) ===
    FLUID_IN = "FLUID_IN"
    FLUID_BOLUS = "FLUID_BOLUS"                    # 輸液挑戰
    BLOOD_PRODUCT = "BLOOD_PRODUCT"
    FLUID_OUT = "FLUID_OUT"

    # === 呼吸/氣道 (v1.6.1 新增 VENT_SETTING_CHANGE) ===
    AIRWAY_EVENT = "AIRWAY_EVENT"
    VENT_SETTING_CHANGE = "VENT_SETTING_CHANGE"    # 呼吸器參數調整

    # === 麻醉深度 (v1.6.1 新增) ===
    ANESTHESIA_DEPTH_ADJUST = "ANESTHESIA_DEPTH_ADJUST"

    # === 里程碑 ===
    MILESTONE = "MILESTONE"

    # === 資源/設備 (v2.0 PSI Event Sourcing) ===
    RESOURCE_CLAIM = "RESOURCE_CLAIM"           # 認領資源 (O2, 設備)
    RESOURCE_CHECK = "RESOURCE_CHECK"           # 檢查 (PSI 讀數)
    RESOURCE_SWITCH = "RESOURCE_SWITCH"         # 換瓶 (原子操作)
    RESOURCE_RELEASE = "RESOURCE_RELEASE"       # 釋放資源
    EQUIPMENT_EVENT = "EQUIPMENT_EVENT"

    # === 其他記錄 (v1.6.1 新增) ===
    LAB_RESULT_POINT = "LAB_RESULT_POINT"          # POC 檢驗
    PROCEDURE_NOTE = "PROCEDURE_NOTE"              # 術中短註記
    POSITION_CHANGE = "POSITION_CHANGE"            # 姿勢調整
    NOTE = "NOTE"

    # === 生命週期 ===
    STATUS_CHANGE = "STATUS_CHANGE"
    STAFF_CHANGE = "STAFF_CHANGE"

    # === 更正 ===
    CORRECTION = "CORRECTION"


# v1.6.1: 補登原因
class LateEntryReason(str, Enum):
    EMERGENCY_HANDLING = "EMERGENCY_HANDLING"       # 緊急處理病人中
    EQUIPMENT_ISSUE = "EQUIPMENT_ISSUE"             # 設備/網路問題
    SHIFT_HANDOFF = "SHIFT_HANDOFF"                 # 交班補記
    DOCUMENTATION_CATCH_UP = "DOCUMENTATION_CATCH_UP"  # 文書補齊
    OTHER = "OTHER"                                 # 其他 (需填文字說明)


# =============================================================================
# v1.6.1: PIO Enums
# =============================================================================

class ProblemType(str, Enum):
    # 血行動力學
    HYPOTENSION = "HYPOTENSION"                     # MAP < 65 or SBP < 90
    HYPERTENSION = "HYPERTENSION"                   # SBP > 160 or MAP > 100
    BRADYCARDIA = "BRADYCARDIA"                     # HR < 50
    TACHYCARDIA = "TACHYCARDIA"                     # HR > 100
    ARRHYTHMIA = "ARRHYTHMIA"                       # AF, VT, VF, etc.

    # 呼吸
    HYPOXEMIA = "HYPOXEMIA"                         # SpO2 < 94%
    HYPERCAPNIA = "HYPERCAPNIA"                     # EtCO2 > 45
    AIRWAY_DIFFICULTY = "AIRWAY_DIFFICULTY"         # 困難氣道/重新插管

    # 出血
    BLEEDING_SUSPECTED = "BLEEDING_SUSPECTED"       # 出血量異常
    MASSIVE_TRANSFUSION = "MASSIVE_TRANSFUSION"     # 啟動大量輸血

    # 麻醉深度
    ANESTHESIA_TOO_LIGHT = "ANESTHESIA_TOO_LIGHT"   # 體動、awareness 跡象
    ANESTHESIA_TOO_DEEP = "ANESTHESIA_TOO_DEEP"     # BIS < 40, 血壓過低

    # 其他
    ALLERGIC_REACTION = "ALLERGIC_REACTION"         # 過敏反應
    MH_SUSPECTED = "MH_SUSPECTED"                   # 疑似惡性高熱
    HYPOTHERMIA = "HYPOTHERMIA"                     # Temp < 35°C
    EQUIPMENT_ISSUE_PIO = "EQUIPMENT_ISSUE_PIO"     # 設備問題
    OTHER_PIO = "OTHER_PIO"                         # 其他問題


class ProblemStatus(str, Enum):
    OPEN = "OPEN"               # 問題進行中
    WATCHING = "WATCHING"       # 觀察中 (已處置，等待反應)
    RESOLVED = "RESOLVED"       # 已解決
    ABANDONED = "ABANDONED"     # 放棄追蹤


class OutcomeType(str, Enum):
    IMPROVED = "IMPROVED"               # 改善
    NO_CHANGE = "NO_CHANGE"             # 無變化
    WORSENED = "WORSENED"               # 惡化
    ADVERSE_REACTION = "ADVERSE_REACTION"  # 不良反應


class OxygenSourceType(str, Enum):
    CENTRAL = "CENTRAL"
    CONCENTRATOR = "CONCENTRATOR"
    CYLINDER = "CYLINDER"


class PreopMode(str, Enum):
    STANDARD = "STANDARD"
    BATTLEFIELD = "BATTLEFIELD"


class PreopStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# Phase B: Drug Transaction Types
class DrugTxType(str, Enum):
    DISPENSE = "DISPENSE"   # 藥局核發
    ADMIN = "ADMIN"         # 給藥
    WASTE = "WASTE"         # 廢棄 (需見證)
    RETURN = "RETURN"       # 退回


class DrugRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISPENSED = "DISPENSED"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"


# =============================================================================
# Request/Response Models
# =============================================================================

class PatientSnapshot(BaseModel):
    """Patient data snapshot for offline resilience (Hub-Satellite sync)"""
    name: Optional[str] = None
    dob: Optional[str] = None
    sex: Optional[str] = None
    allergies: Optional[List[str]] = None
    weight_kg: Optional[float] = None
    blood_type: Optional[str] = None
    # Additional fields from CIRS
    triage_category: Optional[str] = None
    chief_complaint: Optional[str] = None


class CreateCaseRequest(BaseModel):
    surgery_case_id: Optional[str] = None
    patient_id: str
    patient_name: Optional[str] = None
    context_mode: ContextMode = ContextMode.STANDARD
    planned_technique: Optional[AnesthesiaTechnique] = None
    primary_anesthesiologist_id: Optional[str] = None
    primary_nurse_id: Optional[str] = None
    # Hub-Satellite sync fields
    cirs_registration_ref: Optional[str] = None
    patient_snapshot: Optional[PatientSnapshot] = None


class CaseResponse(BaseModel):
    id: str
    surgery_case_id: Optional[str]
    patient_id: str
    patient_name: Optional[str]
    context_mode: str
    planned_technique: Optional[str]
    primary_anesthesiologist_id: Optional[str]
    primary_nurse_id: Optional[str]
    oxygen_source_type: Optional[str]
    oxygen_source_id: Optional[str]
    status: str
    preop_completed_at: Optional[str]
    anesthesia_start_at: Optional[str]
    surgery_start_at: Optional[str]
    surgery_end_at: Optional[str]
    anesthesia_end_at: Optional[str]
    created_at: str
    created_by: str


class AddEventRequest(BaseModel):
    event_type: EventType
    clinical_time: Optional[datetime] = None  # If None, use current time
    clinical_time_offset_seconds: Optional[int] = None  # v1.6.1: 相對偏移 (-300 = 5分鐘前)
    payload: Dict[str, Any]
    device_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    is_correction: bool = False
    corrects_event_id: Optional[str] = None
    correction_reason: Optional[str] = None
    # v1.6.1: 補登相關
    late_entry_reason: Optional[LateEntryReason] = None
    late_entry_note: Optional[str] = None  # 當 reason=OTHER 時必填


class EventResponse(BaseModel):
    id: str
    case_id: str
    event_type: str
    clinical_time: str
    recorded_at: str
    payload: Dict[str, Any]
    actor_id: str
    device_id: Optional[str]
    idempotency_key: Optional[str]
    is_correction: bool
    corrects_event_id: Optional[str]


class VitalSignPayload(BaseModel):
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    etco2: Optional[int] = None
    temp: Optional[float] = None
    o2_flow_lpm: Optional[float] = None
    fio2: Optional[float] = None
    rr: Optional[int] = None  # Respiratory rate


class QuickVitalRequest(BaseModel):
    """One-tap vital sign entry"""
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    etco2: Optional[int] = None
    temp: Optional[float] = None
    o2_flow_lpm: Optional[float] = None
    device_id: Optional[str] = None
    # v1.6.1: 時間偏移支援
    clinical_time: Optional[datetime] = None
    clinical_time_offset_seconds: Optional[int] = None
    late_entry_reason: Optional[LateEntryReason] = None
    late_entry_note: Optional[str] = None


class QuickMedicationRequest(BaseModel):
    """Quick medication entry"""
    drug_code: str
    drug_name: str
    dose: float
    unit: str
    route: str = "IV"
    device_id: Optional[str] = None
    is_controlled: Optional[bool] = None
    # v1.6.1: 時間偏移支援
    clinical_time: Optional[datetime] = None
    clinical_time_offset_seconds: Optional[int] = None
    late_entry_reason: Optional[LateEntryReason] = None
    late_entry_note: Optional[str] = None


# =============================================================================
# v1.6.1: 新增事件 Payload Models
# =============================================================================

class VasoactiveBolusPayload(BaseModel):
    """VASOACTIVE_BOLUS 事件 payload"""
    drug_name: str                              # "Ephedrine", "Phenylephrine", "Atropine"
    dose: float
    unit: str                                   # "mg", "mcg"
    route: str = "IV"                           # "IV", "IM"
    indication: Optional[str] = None            # "Hypotension", "Bradycardia"
    linked_problem_id: Optional[str] = None     # PIO 連結


class VasoactiveInfusionPayload(BaseModel):
    """VASOACTIVE_INFUSION 事件 payload"""
    drug_name: str                              # "Norepinephrine", "Dopamine", "Nicardipine"
    action: str                                 # "START", "TITRATE", "STOP"
    rate_from: Optional[float] = None           # mcg/kg/min (titrate 時)
    rate_to: Optional[float] = None
    unit: str = "mcg/kg/min"
    target: Optional[str] = None                # "MAP > 65", "SBP < 140"
    linked_problem_id: Optional[str] = None


class BloodProductPayload(BaseModel):
    """BLOOD_PRODUCT 事件 payload (增強版)"""
    product_type: str                           # "PRBC", "FFP", "PLATELET", "CRYO", "WHOLE_BLOOD"
    unit_id: Optional[str] = None               # 血袋編號
    unit_count: int = 1
    action: str = "START"                       # "START", "COMPLETE", "REACTION"
    reaction_type: Optional[str] = None         # "FEBRILE", "ALLERGIC", "HEMOLYTIC", "NONE"
    linked_problem_id: Optional[str] = None
    inventory_deduct: bool = False              # 是否觸發 MIRS 庫存扣減


class VentSettingChangePayload(BaseModel):
    """VENT_SETTING_CHANGE 事件 payload"""
    parameter: str                              # "FIO2", "PEEP", "VT", "RR", "MODE", "PIP_LIMIT"
    from_value: str
    to_value: str
    reason: Optional[str] = None                # "Hypoxia", "Hypercarbia", "Recruitment"
    linked_problem_id: Optional[str] = None


class AnesthesiaDepthAdjustPayload(BaseModel):
    """ANESTHESIA_DEPTH_ADJUST 事件 payload"""
    action: str                                 # "DEEPEN", "LIGHTEN"
    method: str                                 # "VOLATILE", "IV_BOLUS", "IV_INFUSION"
    agent: Optional[str] = None                 # "Sevoflurane", "Propofol"
    mac_from: Optional[float] = None            # Volatile MAC
    mac_to: Optional[float] = None
    bolus_dose: Optional[str] = None            # "Propofol 30mg"
    infusion_rate_from: Optional[str] = None
    infusion_rate_to: Optional[str] = None
    reason: Optional[str] = None                # "Patient movement", "BP/HR spike"
    linked_problem_id: Optional[str] = None


class LabResultPointPayload(BaseModel):
    """LAB_RESULT_POINT 事件 payload (POC 檢驗)"""
    test_type: str                              # "ABG", "HB", "GLUCOSE", "ACT", "LACTATE"
    results: Dict[str, Any]                     # {"pH": 7.35, "pO2": 95, ...}
    specimen: Optional[str] = None              # "arterial", "venous"
    device: Optional[str] = None                # POC device name


class PositionChangePayload(BaseModel):
    """POSITION_CHANGE 事件 payload"""
    from_position: Optional[str] = None         # "SUPINE", "LATERAL", "PRONE"
    to_position: str                            # "SUPINE", "LATERAL", "PRONE", "TRENDELENBURG"
    reason: Optional[str] = None


# =============================================================================
# v1.6.1: PIO Request/Response Models
# =============================================================================

class CreateProblemRequest(BaseModel):
    """建立 PIO Problem"""
    problem_type: ProblemType
    severity: int = Field(default=2, ge=1, le=3)  # 1=輕, 2=中, 3=重
    detected_clinical_time: Optional[datetime] = None
    clinical_time_offset_seconds: Optional[int] = None
    trigger_event_id: Optional[str] = None
    note: Optional[str] = None


class CreateInterventionRequest(BaseModel):
    """建立 PIO Intervention - 必須有 event_ref_id"""
    problem_id: str
    event_ref_id: str                           # 必填！連結底層事件
    action_type: str                            # 事件類型 (冗餘)
    performed_clinical_time: Optional[datetime] = None
    clinical_time_offset_seconds: Optional[int] = None
    immediate_response: Optional[str] = None


class CreateOutcomeRequest(BaseModel):
    """建立 PIO Outcome"""
    problem_id: str
    outcome_type: OutcomeType
    evidence_event_ids: List[str]               # 必填！至少一個證據事件
    observed_clinical_time: Optional[datetime] = None
    clinical_time_offset_seconds: Optional[int] = None
    new_problem_status: Optional[ProblemStatus] = None
    note: Optional[str] = None


class UpdateProblemStatusRequest(BaseModel):
    """更新 Problem 狀態"""
    status: ProblemStatus
    resolved_clinical_time: Optional[datetime] = None
    note: Optional[str] = None


class ProblemResponse(BaseModel):
    """PIO Problem 回應"""
    problem_id: str
    case_id: str
    problem_type: str
    severity: int
    detected_clinical_time: str
    resolved_clinical_time: Optional[str]
    status: str
    trigger_event_id: Optional[str]
    note: Optional[str]
    created_by: str
    created_at: str
    interventions: List[Dict[str, Any]] = []
    outcomes: List[Dict[str, Any]] = []


# =============================================================================
# v1.6.1: Quick Scenario Bundle Models
# =============================================================================

class QuickInterventionItem(BaseModel):
    """Quick Scenario 中的單一處置"""
    intervention_type: str                      # "VASOACTIVE_BOLUS", "FLUID_BOLUS", etc.
    payload: Dict[str, Any]                     # 完整 payload


class QuickScenarioRequest(BaseModel):
    """Quick Scenario Bundle 請求 - 一鍵記錄 Problem + Events + Interventions"""
    scenario: ProblemType                       # 問題類型
    severity: int = Field(default=2, ge=1, le=3)
    detected_value: Optional[Dict[str, Any]] = None  # {"map": 55, "sbp": 75, "dbp": 45}
    trigger_event_id: Optional[str] = None      # 觸發此 scenario 的 VITAL 事件
    interventions: List[QuickInterventionItem]  # 選擇的處置列表
    clinical_time_offset_seconds: Optional[int] = None
    note: Optional[str] = None


# Quick Scenario 建議模板 (UI 可用此資料渲染選項)
QUICK_SCENARIO_TEMPLATES = {
    "HYPOTENSION": {
        "thresholds": {"map": 60, "sbp": 90},
        "suggested_interventions": [
            {"type": "VASOACTIVE_BOLUS", "label": "Ephedrine 5mg IV", "payload": {"drug_name": "Ephedrine", "dose": 5, "unit": "mg", "route": "IV"}},
            {"type": "VASOACTIVE_BOLUS", "label": "Phenylephrine 100mcg IV", "payload": {"drug_name": "Phenylephrine", "dose": 100, "unit": "mcg", "route": "IV"}},
            {"type": "FLUID_BOLUS", "label": "LR 250ml bolus", "payload": {"fluid_type": "LR", "volume": 250, "unit": "ml", "rate": "bolus"}},
            {"type": "ANESTHESIA_DEPTH_ADJUST", "label": "加深麻醉", "payload": {"action": "DEEPEN", "method": "VOLATILE", "reason": "Hypotension"}},
        ]
    },
    "HYPERTENSION": {
        "thresholds": {"map": 100, "sbp": 160},
        "suggested_interventions": [
            {"type": "VASOACTIVE_INFUSION", "label": "Nicardipine start", "payload": {"drug_name": "Nicardipine", "action": "START", "rate_to": 5, "unit": "mg/hr", "target": "SBP < 140"}},
            {"type": "ANESTHESIA_DEPTH_ADJUST", "label": "加深麻醉", "payload": {"action": "DEEPEN", "method": "VOLATILE", "reason": "Hypertension"}},
            {"type": "MEDICATION_ADMIN", "label": "Fentanyl 50mcg", "payload": {"drug_name": "Fentanyl", "dose": 50, "unit": "mcg", "route": "IV"}},
        ]
    },
    "BRADYCARDIA": {
        "thresholds": {"hr": 45},
        "suggested_interventions": [
            {"type": "VASOACTIVE_BOLUS", "label": "Atropine 0.5mg IV", "payload": {"drug_name": "Atropine", "dose": 0.5, "unit": "mg", "route": "IV"}},
            {"type": "VASOACTIVE_BOLUS", "label": "Ephedrine 5mg IV", "payload": {"drug_name": "Ephedrine", "dose": 5, "unit": "mg", "route": "IV"}},
            {"type": "ANESTHESIA_DEPTH_ADJUST", "label": "減淺麻醉", "payload": {"action": "LIGHTEN", "method": "VOLATILE", "reason": "Bradycardia"}},
        ]
    },
    "TACHYCARDIA": {
        "thresholds": {"hr": 120},
        "suggested_interventions": [
            {"type": "VASOACTIVE_BOLUS", "label": "Esmolol 20mg IV", "payload": {"drug_name": "Esmolol", "dose": 20, "unit": "mg", "route": "IV"}},
            {"type": "ANESTHESIA_DEPTH_ADJUST", "label": "加深麻醉", "payload": {"action": "DEEPEN", "method": "VOLATILE", "reason": "Tachycardia"}},
            {"type": "MEDICATION_ADMIN", "label": "Fentanyl 50mcg", "payload": {"drug_name": "Fentanyl", "dose": 50, "unit": "mcg", "route": "IV"}},
        ]
    },
    "HYPOXEMIA": {
        "thresholds": {"spo2": 90},
        "suggested_interventions": [
            {"type": "VENT_SETTING_CHANGE", "label": "FiO2 100%", "payload": {"parameter": "FIO2", "from_value": "50%", "to_value": "100%", "reason": "Hypoxemia"}},
            {"type": "VENT_SETTING_CHANGE", "label": "PEEP +5", "payload": {"parameter": "PEEP", "from_value": "5", "to_value": "10", "reason": "Hypoxemia"}},
            {"type": "PROCEDURE_NOTE", "label": "Suction", "payload": {"note": "Endotracheal suction performed"}},
            {"type": "PROCEDURE_NOTE", "label": "Recruitment maneuver", "payload": {"note": "Recruitment maneuver performed"}},
        ]
    },
    "BLEEDING_SUSPECTED": {
        "thresholds": {},
        "suggested_interventions": [
            {"type": "BLOOD_PRODUCT", "label": "PRBC 1U", "payload": {"product_type": "PRBC", "unit_count": 1, "action": "START"}},
            {"type": "FLUID_BOLUS", "label": "LR 500ml fast", "payload": {"fluid_type": "LR", "volume": 500, "unit": "ml", "rate": "fast"}},
            {"type": "PROCEDURE_NOTE", "label": "通知外科", "payload": {"note": "Notified surgeon about suspected bleeding"}},
        ]
    },
}


class ClaimOxygenRequest(BaseModel):
    cylinder_unit_id: int
    initial_pressure_psi: Optional[int] = None


# =============================================================================
# v2.0 PSI Event Sourcing Models
# =============================================================================

class ResourceClaimRequest(BaseModel):
    """認領資源 (O2 筒, 設備)"""
    resource_type: str = Field(default="O2_CYLINDER", description="O2_CYLINDER | MONITOR | PUMP")
    resource_id: str = Field(..., description="裝置序號 (E-001, M-002)")
    unit_id: Optional[int] = Field(None, description="equipment_units.id (內部關聯)")
    initial_psi: Optional[int] = Field(None, ge=0, le=3000, description="初始 PSI")
    capacity_liters: Optional[float] = Field(None, description="容量 (L)")
    flow_rate_lpm: Optional[float] = Field(None, ge=0, le=30, description="流量 (L/min)")
    note: Optional[str] = None


class ResourceCheckRequest(BaseModel):
    """記錄 PSI 讀數"""
    resource_id: str = Field(..., description="裝置序號")
    psi: int = Field(..., ge=0, le=3000, description="目前 PSI")
    flow_rate_lpm: Optional[float] = Field(None, ge=0, le=30, description="流量 (L/min)")
    note: Optional[str] = None


class ResourceSwitchRequest(BaseModel):
    """換瓶 (原子操作)"""
    old_resource_id: str = Field(..., description="舊筒序號")
    old_final_psi: int = Field(..., ge=0, description="舊筒最終 PSI")
    new_resource_id: str = Field(..., description="新筒序號")
    new_unit_id: Optional[int] = Field(None, description="新筒 equipment_units.id")
    new_initial_psi: int = Field(..., ge=0, le=3000, description="新筒初始 PSI")
    new_capacity_liters: Optional[float] = Field(None, description="新筒容量 (L)")
    flow_rate_lpm: Optional[float] = Field(None, ge=0, le=30, description="流量 (L/min)")
    note: Optional[str] = None


class ResourceReleaseRequest(BaseModel):
    """釋放資源"""
    resource_id: str = Field(..., description="裝置序號")
    final_psi: Optional[int] = Field(None, ge=0, description="最終 PSI")
    total_consumed_liters: Optional[float] = Field(None, description="總消耗量 (L)")
    note: Optional[str] = None


# PreOp Models
class BattlefieldQuickFlags(BaseModel):
    airway_risk: str = Field(..., pattern="^(NORMAL|DIFFICULT)$")
    hd_stable: str = Field(..., pattern="^(YES|NO|UNKNOWN)$")
    npo_status: str = Field(..., pattern="^(EMPTY|FULL_OR_UNKNOWN)$")
    hemorrhage_risk: str = Field(..., pattern="^(LOW|HIGH)$")
    estimated_duration: str = Field(..., pattern="^(SHORT|MEDIUM|LONG)$")
    critical_notes: Optional[str] = None


class CreatePreopRequest(BaseModel):
    mode: PreopMode = PreopMode.STANDARD

    # Standard mode fields
    asa_class: Optional[int] = Field(None, ge=1, le=6)
    asa_emergency: bool = False
    npo_hours: Optional[float] = None
    npo_status: Optional[str] = None
    allergies: Optional[List[str]] = None
    mallampati_score: Optional[int] = Field(None, ge=1, le=4)
    difficult_airway_anticipated: bool = False
    comorbidities: Optional[List[str]] = None

    # Battlefield mode
    quick_flags: Optional[BattlefieldQuickFlags] = None

    # Common
    planned_technique: Optional[str] = None
    special_considerations: Optional[str] = None


class PreopResponse(BaseModel):
    id: str
    case_id: str
    mode: str
    status: str
    asa_class: Optional[int]
    asa_emergency: bool
    npo_hours: Optional[float]
    allergies: Optional[List[str]]
    mallampati_score: Optional[int]
    difficult_airway_anticipated: bool
    quick_flags: Optional[Dict[str, Any]]
    planned_technique: Optional[str]
    assessed_by: str
    assessment_datetime: str


# =============================================================================
# Database Schema Initialization
# =============================================================================

def init_anesthesia_schema(cursor):
    """Initialize anesthesia module tables"""

    # Anesthesia Cases (Container)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_cases (
            id TEXT PRIMARY KEY,
            surgery_case_id TEXT,
            patient_id TEXT NOT NULL,
            patient_name TEXT,

            context_mode TEXT NOT NULL DEFAULT 'STANDARD',

            primary_anesthesiologist_id TEXT,
            primary_nurse_id TEXT,

            planned_technique TEXT,

            oxygen_source_type TEXT,
            oxygen_source_id TEXT,

            preop_completed_at DATETIME,
            anesthesia_start_at DATETIME,
            surgery_start_at DATETIME,
            surgery_end_at DATETIME,
            anesthesia_end_at DATETIME,
            pacu_admission_at DATETIME,
            pacu_discharge_at DATETIME,

            status TEXT NOT NULL DEFAULT 'PREOP',

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            CHECK(context_mode IN ('STANDARD', 'BATTLEFIELD')),
            CHECK(status IN ('PREOP', 'IN_PROGRESS', 'PACU', 'CLOSED'))
        )
    """)

    # Anesthesia Events (Append-Only)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_events (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,

            event_type TEXT NOT NULL,

            clinical_time DATETIME NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            payload TEXT NOT NULL,

            actor_id TEXT NOT NULL,
            device_id TEXT,

            idempotency_key TEXT UNIQUE,

            is_correction INTEGER DEFAULT 0,
            corrects_event_id TEXT,
            correction_reason TEXT,

            sync_status TEXT DEFAULT 'LOCAL',

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            FOREIGN KEY (corrects_event_id) REFERENCES anesthesia_events(id),
            CHECK(is_correction IN (0, 1)),
            CHECK(sync_status IN ('LOCAL', 'SYNCED', 'CONFLICT'))
        )
    """)

    # PreOp Assessments
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS preop_assessments (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL UNIQUE,

            mode TEXT NOT NULL DEFAULT 'STANDARD',

            asa_class INTEGER,
            asa_emergency INTEGER DEFAULT 0,

            npo_hours REAL,
            last_oral_intake DATETIME,
            npo_status TEXT,

            allergies TEXT,
            allergy_verified INTEGER DEFAULT 0,

            mallampati_score INTEGER,
            thyromental_distance TEXT,
            neck_mobility TEXT,
            mouth_opening TEXT,
            teeth_status TEXT,
            difficult_airway_history INTEGER DEFAULT 0,
            difficult_airway_anticipated INTEGER DEFAULT 0,

            comorbidities TEXT,
            current_medications TEXT,
            cardiac_risk_index INTEGER,

            quick_flags TEXT,

            planned_technique TEXT,
            backup_plan TEXT,
            special_considerations TEXT,

            assessed_by TEXT NOT NULL,
            assessment_datetime DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'PENDING',
            approved_by TEXT,
            approved_at DATETIME,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(mode IN ('STANDARD', 'BATTLEFIELD')),
            CHECK(asa_class IS NULL OR asa_class BETWEEN 1 AND 6),
            CHECK(mallampati_score IS NULL OR mallampati_score BETWEEN 1 AND 4),
            CHECK(status IN ('PENDING', 'APPROVED', 'NEEDS_REVIEW'))
        )
    """)

    # Indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_events_timeline
        ON anesthesia_events(case_id, clinical_time)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_events_type
        ON anesthesia_events(case_id, event_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_events_sync
        ON anesthesia_events(sync_status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anes_cases_status
        ON anesthesia_cases(status, created_at DESC)
    """)

    # Add O2 claim columns to equipment_units if not exist
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_case_id TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_at DATETIME")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE equipment_units ADD COLUMN claimed_by_user_id TEXT")
    except:
        pass

    # Phase C: Add patient snapshot columns for Hub-Satellite sync
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN patient_snapshot TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN cirs_registration_ref TEXT")
    except:
        pass

    # Phase A-6: WAL Sync Queue for offline-first operations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_sync_queue (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            payload TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            last_error TEXT,
            status TEXT DEFAULT 'PENDING',
            synced_at DATETIME,
            CHECK(status IN ('PENDING', 'SYNCING', 'SYNCED', 'FAILED'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_queue_status
        ON anesthesia_sync_queue(status, created_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_queue_device
        ON anesthesia_sync_queue(device_id, status)
    """)

    # =========================================================================
    # Phase B: Controlled Drugs Schema
    # =========================================================================

    # Drug Requests (申請單)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drug_requests (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,

            requester_id TEXT NOT NULL,
            requester_role TEXT NOT NULL,

            items TEXT NOT NULL,

            approver_id TEXT,
            approved_at DATETIME,

            status TEXT NOT NULL DEFAULT 'PENDING',

            offline_proof_artifact_id TEXT,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(status IN ('PENDING', 'APPROVED', 'DISPENSED', 'RECONCILED', 'REJECTED'))
        )
    """)

    # Drug Transactions (交易流水帳 - The Ledger)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drug_transactions (
            id TEXT PRIMARY KEY,
            request_id TEXT,
            case_id TEXT NOT NULL,

            drug_code TEXT NOT NULL,
            drug_name TEXT NOT NULL,
            schedule_class INTEGER NOT NULL DEFAULT 4,
            batch_number TEXT,

            tx_type TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL,

            actor_id TEXT NOT NULL,
            witness_id TEXT,
            witness_verified_at DATETIME,

            idempotency_key TEXT UNIQUE,
            device_id TEXT,
            local_seq INTEGER,

            tx_time DATETIME NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            sync_status TEXT DEFAULT 'LOCAL',
            notes TEXT,

            FOREIGN KEY (request_id) REFERENCES drug_requests(id),
            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(tx_type IN ('DISPENSE', 'ADMIN', 'WASTE', 'RETURN')),
            CHECK(quantity > 0),
            CHECK(sync_status IN ('LOCAL', 'SYNCED', 'CONFLICT'))
        )
    """)

    # Indexes for drug tables
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_drug_requests_case
        ON drug_requests(case_id, status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_drug_tx_case
        ON drug_transactions(case_id, drug_code)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_drug_tx_request
        ON drug_transactions(request_id)
    """)

    # =========================================================================
    # Phase C: PIO Schema (v1.6.1)
    # =========================================================================

    # PIO Problem (問題)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pio_problems (
            problem_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,

            -- 問題分類
            problem_type TEXT NOT NULL,
            severity INTEGER NOT NULL DEFAULT 2 CHECK(severity BETWEEN 1 AND 3),

            -- 時間
            detected_clinical_time DATETIME NOT NULL,
            resolved_clinical_time DATETIME,

            -- 狀態: OPEN, WATCHING, RESOLVED, ABANDONED
            status TEXT NOT NULL DEFAULT 'OPEN',

            -- 觸發事件 (通常是發現問題的那筆 VITAL)
            trigger_event_id TEXT,

            -- 備註
            note TEXT,

            -- 稽核
            created_by TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            FOREIGN KEY (trigger_event_id) REFERENCES anesthesia_events(id),
            CHECK(status IN ('OPEN', 'WATCHING', 'RESOLVED', 'ABANDONED'))
        )
    """)

    # PIO Intervention (處置) - 必須連結 Problem + Event
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pio_interventions (
            intervention_id TEXT PRIMARY KEY,
            problem_id TEXT NOT NULL,
            case_id TEXT NOT NULL,

            -- 底層事件引用 (必填)
            event_ref_id TEXT NOT NULL,

            -- 處置類型 (冗餘，方便查詢)
            action_type TEXT NOT NULL,

            -- 時間 (從 event 繼承，冗餘存放)
            performed_clinical_time DATETIME NOT NULL,

            -- 立即反應 (可選)
            immediate_response TEXT,

            -- 稽核
            performed_by TEXT NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (problem_id) REFERENCES pio_problems(problem_id),
            FOREIGN KEY (event_ref_id) REFERENCES anesthesia_events(id)
        )
    """)

    # PIO Outcome (結果) - 必須連結 Problem + Evidence Events
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pio_outcomes (
            outcome_id TEXT PRIMARY KEY,
            problem_id TEXT NOT NULL,

            -- 結果類型: IMPROVED, NO_CHANGE, WORSENED, ADVERSE_REACTION
            outcome_type TEXT NOT NULL,

            -- 證據事件 (JSON array)
            evidence_event_ids TEXT NOT NULL,

            -- 時間
            observed_clinical_time DATETIME NOT NULL,

            -- 狀態變更
            new_problem_status TEXT,

            -- 備註
            note TEXT,

            -- 稽核
            recorded_by TEXT NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (problem_id) REFERENCES pio_problems(problem_id),
            CHECK(outcome_type IN ('IMPROVED', 'NO_CHANGE', 'WORSENED', 'ADVERSE_REACTION'))
        )
    """)

    # PIO Indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pio_problems_case
        ON pio_problems(case_id, status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pio_interventions_problem
        ON pio_interventions(problem_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pio_outcomes_problem
        ON pio_outcomes(problem_id)
    """)

    logger.info("✓ Anesthesia schema initialized (Phase A + B + C-PIO)")


# =============================================================================
# Helper Functions
# =============================================================================

def generate_case_id() -> str:
    """Generate unique case ID: ANES-YYYYMMDD-XXX"""
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"ANES-{date_str}-{short_uuid}"


def generate_event_id() -> str:
    """Generate unique event ID"""
    return str(uuid.uuid4())


def generate_preop_id() -> str:
    """Generate unique preop ID"""
    return f"PREOP-{uuid.uuid4().hex[:8].upper()}"


def generate_problem_id(case_id: str) -> str:
    """Generate unique PIO problem ID: PIO-{case_id}-XXX"""
    short_uuid = uuid.uuid4().hex[:4].upper()
    return f"PIO-{case_id[-6:]}-{short_uuid}"


def generate_intervention_id() -> str:
    """Generate unique PIO intervention ID"""
    return f"INT-{uuid.uuid4().hex[:8].upper()}"


def generate_outcome_id() -> str:
    """Generate unique PIO outcome ID"""
    return f"OUT-{uuid.uuid4().hex[:8].upper()}"


# =============================================================================
# API Routes - Cases
# =============================================================================

def get_db_connection():
    """Get database connection - to be injected from main"""
    # This will be set by main.py
    from main import db
    return db.get_connection()


@router.post("/cases", response_model=CaseResponse)
async def create_case(request: CreateCaseRequest, actor_id: str = Query(...)):
    """Create a new anesthesia case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    case_id = generate_case_id()

    # Serialize patient snapshot if provided
    patient_snapshot_json = None
    if request.patient_snapshot:
        patient_snapshot_json = json.dumps(request.patient_snapshot.model_dump())

    try:
        cursor.execute("""
            INSERT INTO anesthesia_cases (
                id, surgery_case_id, patient_id, patient_name,
                context_mode, planned_technique,
                primary_anesthesiologist_id, primary_nurse_id,
                cirs_registration_ref, patient_snapshot,
                created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            request.surgery_case_id,
            request.patient_id,
            request.patient_name,
            request.context_mode.value,
            request.planned_technique.value if request.planned_technique else None,
            request.primary_anesthesiologist_id,
            request.primary_nurse_id,
            request.cirs_registration_ref,
            patient_snapshot_json,
            actor_id
        ))

        # Add STATUS_CHANGE event
        event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, ?, datetime('now'), ?, ?)
        """, (
            event_id, case_id, 'STATUS_CHANGE',
            json.dumps({"from": None, "to": "PREOP", "reason": "Case created"}),
            actor_id
        ))

        conn.commit()

        # v1.1: Notify CIRS to claim registration as ANESTHESIA (non-blocking)
        if request.cirs_registration_ref:
            try:
                async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
                    await client.post(
                        f"{CIRS_HUB_URL}/api/registrations/{request.cirs_registration_ref}/role-claim",
                        json={"role": "ANESTHESIA", "actor_id": actor_id}
                    )
                    logger.info(f"CIRS registration {request.cirs_registration_ref} claimed as ANESTHESIA")
            except Exception as e:
                logger.warning(f"Failed to notify CIRS of anesthesia claim: {e}")

        # Fetch and return
        cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
        row = cursor.fetchone()

        return CaseResponse(
            id=row['id'],
            surgery_case_id=row['surgery_case_id'],
            patient_id=row['patient_id'],
            patient_name=row['patient_name'],
            context_mode=row['context_mode'],
            planned_technique=row['planned_technique'],
            primary_anesthesiologist_id=row['primary_anesthesiologist_id'],
            primary_nurse_id=row['primary_nurse_id'],
            oxygen_source_type=row['oxygen_source_type'],
            oxygen_source_id=row['oxygen_source_id'],
            status=row['status'],
            preop_completed_at=row['preop_completed_at'],
            anesthesia_start_at=row['anesthesia_start_at'],
            surgery_start_at=row['surgery_start_at'],
            surgery_end_at=row['surgery_end_at'],
            anesthesia_end_at=row['anesthesia_end_at'],
            created_at=row['created_at'],
            created_by=row['created_by']
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create case: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases")
async def list_cases(
    status: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = Query(default=50, le=200)
):
    """List anesthesia cases"""
    # v1.5.3: Vercel demo mode - return demo cases with fresh timestamps
    if IS_VERCEL:
        demo_cases = get_demo_anesthesia_cases()
        # Filter by status if specified
        if status:
            demo_cases = [c for c in demo_cases if c["status"] == status]
        return {
            "cases": demo_cases[:limit],
            "count": len(demo_cases[:limit]),
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM anesthesia_cases WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if date:
        query += " AND date(created_at) = ?"
        params.append(date)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return {
        "cases": [dict(row) for row in rows],
        "count": len(rows)
    }


@router.get("/cases/{case_id}")
async def get_case(case_id: str):
    """Get case details"""
    # v1.5.3: Vercel demo mode with fresh timestamps
    if IS_VERCEL and case_id.startswith("ANES-DEMO"):
        demo_cases = get_demo_anesthesia_cases()
        demo_case = next((c for c in demo_cases if c["id"] == case_id), None)
        if demo_case:
            return demo_case  # started_at already included in function
        raise HTTPException(status_code=404, detail=f"Demo case not found: {case_id}")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    return dict(row)


@router.patch("/cases/{case_id}")
async def update_case_metadata(
    case_id: str,
    primary_anesthesiologist_id: Optional[str] = None,
    primary_nurse_id: Optional[str] = None,
    planned_technique: Optional[str] = None,
    actor_id: str = Query(...)
):
    """Update case metadata (non-event fields only)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if primary_anesthesiologist_id is not None:
        updates.append("primary_anesthesiologist_id = ?")
        params.append(primary_anesthesiologist_id)

    if primary_nurse_id is not None:
        updates.append("primary_nurse_id = ?")
        params.append(primary_nurse_id)

    if planned_technique is not None:
        updates.append("planned_technique = ?")
        params.append(planned_technique)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(case_id)

    try:
        cursor.execute(f"""
            UPDATE anesthesia_cases SET {', '.join(updates)} WHERE id = ?
        """, params)
        conn.commit()

        cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
        return dict(cursor.fetchone())

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# API Routes - Events (Append-Only)
# =============================================================================

@router.post("/cases/{case_id}/events")
async def add_event(case_id: str, request: AddEventRequest, actor_id: str = Query(...)):
    """Add event to case timeline (append-only)

    v1.6.1: 支援相對時間偏移和補登驗證
    - clinical_time_offset_seconds: 負數表示過去時間 (-300 = 5分鐘前)
    - 補登規則:
      - ≤ 5分鐘: 正常記錄
      - 5-30分鐘: 自動標記補登
      - 30-60分鐘: 必填 late_entry_reason
      - > 60分鐘: 必填 late_entry_reason + 標記需 PIN 確認
    """
    # Vercel demo mode: return fake success for demo cases
    if IS_VERCEL and case_id.startswith("ANES-DEMO"):
        return {
            "id": f"EVT-DEMO-{uuid.uuid4().hex[:8].upper()}",
            "case_id": case_id,
            "event_type": request.event_type.value,
            "clinical_time": datetime.now().isoformat(),
            "payload": request.payload,
            "actor_id": actor_id,
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot add events to closed case")

    event_id = generate_event_id()
    recorded_at = datetime.now()

    # v1.6.1: 計算 clinical_time
    if request.clinical_time:
        clinical_time = request.clinical_time
    elif request.clinical_time_offset_seconds is not None:
        # 相對偏移：recorded_at + offset (offset 為負數表示過去)
        from datetime import timedelta
        clinical_time = recorded_at + timedelta(seconds=request.clinical_time_offset_seconds)
    else:
        clinical_time = recorded_at

    # v1.6.1: 補登驗證
    delay_seconds = (recorded_at - clinical_time).total_seconds() if isinstance(clinical_time, datetime) else 0
    is_late_entry = delay_seconds > 300  # > 5 分鐘
    requires_pin_elevation = delay_seconds > 3600  # > 60 分鐘

    # 驗證補登規則
    if delay_seconds > 1800:  # > 30 分鐘
        if not request.late_entry_reason:
            raise HTTPException(
                status_code=400,
                detail=f"補登超過 30 分鐘需提供原因 (late_entry_reason). 延遲: {int(delay_seconds/60)} 分鐘"
            )
        if request.late_entry_reason == LateEntryReason.OTHER and not request.late_entry_note:
            raise HTTPException(
                status_code=400,
                detail="late_entry_reason=OTHER 時必須填寫 late_entry_note"
            )

    # 增強 payload 以包含補登資訊
    enhanced_payload = dict(request.payload)
    if is_late_entry:
        enhanced_payload['_late_entry'] = {
            'delay_seconds': int(delay_seconds),
            'reason': request.late_entry_reason.value if request.late_entry_reason else None,
            'note': request.late_entry_note,
            'requires_pin': requires_pin_elevation
        }

    idempotency_key = request.idempotency_key or f"{case_id}:{actor_id}:{event_id[:8]}"

    try:
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload,
                actor_id, device_id, idempotency_key,
                is_correction, corrects_event_id, correction_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            case_id,
            request.event_type.value,
            clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time,
            json.dumps(enhanced_payload),
            actor_id,
            request.device_id,
            idempotency_key,
            1 if request.is_correction else 0,
            request.corrects_event_id,
            request.correction_reason
        ))

        # Handle milestone events that update case timestamps
        if request.event_type == EventType.MILESTONE:
            milestone_type = request.payload.get('type')
            timestamp_field = {
                'ANESTHESIA_START': 'anesthesia_start_at',
                'SURGERY_START': 'surgery_start_at',
                'SURGERY_END': 'surgery_end_at',
                'ANESTHESIA_END': 'anesthesia_end_at'
            }.get(milestone_type)

            if timestamp_field:
                cursor.execute(f"""
                    UPDATE anesthesia_cases
                    SET {timestamp_field} = ?, updated_at = datetime('now')
                    WHERE id = ?
                """, (clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time, case_id))

            # Update status based on milestone
            if milestone_type == 'ANESTHESIA_START':
                cursor.execute("""
                    UPDATE anesthesia_cases SET status = 'IN_PROGRESS', updated_at = datetime('now')
                    WHERE id = ?
                """, (case_id,))

        conn.commit()

        # v1.6.1: 回傳包含補登資訊
        response = {
            "success": True,
            "event_id": event_id,
            "clinical_time": clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time,
            "recorded_at": recorded_at.isoformat()
        }
        if is_late_entry:
            response["is_late_entry"] = True
            response["delay_minutes"] = int(delay_seconds / 60)
            if requires_pin_elevation:
                response["requires_pin_elevation"] = True

        return response

    except Exception as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            # Idempotency: return existing event
            cursor.execute("""
                SELECT id FROM anesthesia_events WHERE idempotency_key = ?
            """, (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                return {"success": True, "event_id": existing['id'], "duplicate": True}
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/events")
async def get_events(
    case_id: str,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = Query(default=500, le=2000)
):
    """Get all events for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM anesthesia_events WHERE case_id = ?"
    params = [case_id]

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)

    if since:
        query += " AND clinical_time > ?"
        params.append(since)

    query += " ORDER BY clinical_time ASC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    events = []
    for row in rows:
        event = dict(row)
        event['payload'] = json.loads(event['payload']) if event['payload'] else {}
        events.append(event)

    return {"events": events, "count": len(events)}


@router.get("/cases/{case_id}/timeline")
async def get_timeline(case_id: str):
    """Get reconstructed timeline (grouped by type)"""
    # v1.5.3: Vercel demo mode - return demo timeline
    if IS_VERCEL and case_id.startswith("ANES-DEMO"):
        # Get case start time (1 hour ago for demo)
        demo_cases = get_demo_anesthesia_cases()
        demo_case = next((c for c in demo_cases if c["id"] == case_id), None)
        if demo_case:
            case_start = datetime.fromisoformat(demo_case["started_at"])
        else:
            case_start = datetime.now() - timedelta(hours=1)

        # Create timeline events relative to case start time
        demo_events = [
            {
                "id": f"{case_id}-evt-001",
                "case_id": case_id,
                "event_type": "VITAL_SIGN",
                "clinical_time": (case_start + timedelta(minutes=5)).isoformat(),
                "payload": {"bp_sys": 120, "bp_dia": 75, "hr": 72, "spo2": 99, "etco2": 35}
            },
            {
                "id": f"{case_id}-evt-002",
                "case_id": case_id,
                "event_type": "MILESTONE",
                "clinical_time": (case_start + timedelta(minutes=10)).isoformat(),
                "payload": {"type": "INTUBATION"}
            },
            {
                "id": f"{case_id}-evt-003",
                "case_id": case_id,
                "event_type": "VITAL_SIGN",
                "clinical_time": (case_start + timedelta(minutes=15)).isoformat(),
                "payload": {"bp_sys": 95, "bp_dia": 60, "hr": 85, "spo2": 98, "etco2": 38}
            },
            {
                "id": f"{case_id}-evt-004",
                "case_id": case_id,
                "event_type": "MEDICATION_ADMIN",
                "clinical_time": (case_start + timedelta(minutes=18)).isoformat(),
                "payload": {"drug_name": "Ephedrine", "dose": 5, "unit": "mg", "route": "IV"}
            },
            {
                "id": f"{case_id}-evt-005",
                "case_id": case_id,
                "event_type": "VITAL_SIGN",
                "clinical_time": (case_start + timedelta(minutes=25)).isoformat(),
                "payload": {"bp_sys": 110, "bp_dia": 70, "hr": 78, "spo2": 99, "etco2": 36}
            },
            {
                "id": f"{case_id}-evt-006",
                "case_id": case_id,
                "event_type": "MILESTONE",
                "clinical_time": (case_start + timedelta(minutes=30)).isoformat(),
                "payload": {"type": "INCISION"}
            },
            {
                "id": f"{case_id}-evt-007",
                "case_id": case_id,
                "event_type": "VITAL_SIGN",
                "clinical_time": (case_start + timedelta(minutes=40)).isoformat(),
                "payload": {"bp_sys": 115, "bp_dia": 72, "hr": 75, "spo2": 99, "etco2": 35}
            },
            {
                "id": f"{case_id}-evt-008",
                "case_id": case_id,
                "event_type": "VITAL_SIGN",
                "clinical_time": (case_start + timedelta(minutes=55)).isoformat(),
                "payload": {"bp_sys": 118, "bp_dia": 74, "hr": 70, "spo2": 100, "etco2": 34}
            },
        ]
        return {
            'vitals': [e for e in demo_events if e['event_type'] == 'VITAL_SIGN'],
            'medications': [e for e in demo_events if e['event_type'] == 'MEDICATION_ADMIN'],
            'vasoactive': [],
            'fluids': [],
            'airway': [],
            'anesthesia_depth': [],
            'milestones': [e for e in demo_events if e['event_type'] == 'MILESTONE'],
            'labs': [],
            'positioning': [],
            'notes': [],
            'all': demo_events,
            'demo_mode': True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM anesthesia_events
        WHERE case_id = ? AND is_correction = 0
        ORDER BY clinical_time ASC
    """, (case_id,))

    events = [dict(row) for row in cursor.fetchall()]

    # Parse payloads
    for event in events:
        event['payload'] = json.loads(event['payload']) if event['payload'] else {}

    # Group by type (v1.6.1: 擴充分組以支援新事件類型)
    timeline = {
        'vitals': [e for e in events if e['event_type'] == 'VITAL_SIGN'],
        'medications': [e for e in events if e['event_type'] == 'MEDICATION_ADMIN'],
        'vasoactive': [e for e in events if e['event_type'] in ('VASOACTIVE_BOLUS', 'VASOACTIVE_INFUSION')],
        'fluids': [e for e in events if e['event_type'] in ('FLUID_IN', 'FLUID_OUT', 'FLUID_BOLUS', 'BLOOD_PRODUCT')],
        'airway': [e for e in events if e['event_type'] in ('AIRWAY_EVENT', 'VENT_SETTING_CHANGE')],
        'anesthesia_depth': [e for e in events if e['event_type'] == 'ANESTHESIA_DEPTH_ADJUST'],
        'milestones': [e for e in events if e['event_type'] == 'MILESTONE'],
        'labs': [e for e in events if e['event_type'] == 'LAB_RESULT_POINT'],
        'positioning': [e for e in events if e['event_type'] == 'POSITION_CHANGE'],
        'notes': [e for e in events if e['event_type'] in ('NOTE', 'PROCEDURE_NOTE')],
        'all': events
    }

    return timeline


# =============================================================================
# API Routes - Quick Entry (One-Tap)
# =============================================================================

@router.post("/cases/{case_id}/vitals")
async def add_vital_sign(case_id: str, request: QuickVitalRequest, actor_id: str = Query(...)):
    """Quick vital sign entry (one-tap) - v1.6.1 支援時間偏移"""
    # 排除非 payload 欄位
    exclude_fields = {'device_id', 'clinical_time', 'clinical_time_offset_seconds', 'late_entry_reason', 'late_entry_note'}
    payload = {k: v for k, v in request.dict().items() if v is not None and k not in exclude_fields}

    event_request = AddEventRequest(
        event_type=EventType.VITAL_SIGN,
        payload=payload,
        device_id=request.device_id,
        # v1.6.1: 時間偏移
        clinical_time=request.clinical_time,
        clinical_time_offset_seconds=request.clinical_time_offset_seconds,
        late_entry_reason=request.late_entry_reason,
        late_entry_note=request.late_entry_note
    )

    return await add_event(case_id, event_request, actor_id)


@router.post("/cases/{case_id}/medication")
async def add_medication(case_id: str, request: QuickMedicationRequest, actor_id: str = Query(...)):
    """Quick medication entry - v1.6.1 支援時間偏移"""
    payload = {
        "drug_code": request.drug_code,
        "drug_name": request.drug_name,
        "dose": request.dose,
        "unit": request.unit,
        "route": request.route
    }
    if request.is_controlled is not None:
        payload["is_controlled"] = request.is_controlled

    event_request = AddEventRequest(
        event_type=EventType.MEDICATION_ADMIN,
        payload=payload,
        device_id=request.device_id,
        # v1.6.1: 時間偏移
        clinical_time=request.clinical_time,
        clinical_time_offset_seconds=request.clinical_time_offset_seconds,
        late_entry_reason=request.late_entry_reason,
        late_entry_note=request.late_entry_note
    )

    return await add_event(case_id, event_request, actor_id)


@router.post("/cases/{case_id}/milestone")
async def add_milestone(
    case_id: str,
    milestone_type: str = Query(..., regex="^(ANESTHESIA_START|INTUBATION|SURGERY_START|SURGERY_END|EXTUBATION|ANESTHESIA_END|INCISION|SKIN_CLOSE|PACU)$"),
    actor_id: str = Query(...),
    clinical_time: Optional[str] = Query(None),
    clinical_time_offset_seconds: Optional[int] = Query(None),
    late_entry_reason: Optional[str] = Query(None),
    late_entry_note: Optional[str] = Query(None)
):
    """Add milestone event"""
    # Parse clinical_time if provided
    parsed_clinical_time = None
    if clinical_time:
        from datetime import datetime as dt
        try:
            parsed_clinical_time = dt.fromisoformat(clinical_time.replace('Z', '+00:00'))
        except:
            parsed_clinical_time = None

    event_request = AddEventRequest(
        event_type=EventType.MILESTONE,
        payload={"type": milestone_type},
        clinical_time=parsed_clinical_time,
        clinical_time_offset_seconds=clinical_time_offset_seconds,
        late_entry_reason=late_entry_reason,
        late_entry_note=late_entry_note
    )

    return await add_event(case_id, event_request, actor_id)


# =============================================================================
# API Routes - PreOp
# =============================================================================

@router.post("/cases/{case_id}/preop")
async def create_preop(case_id: str, request: CreatePreopRequest, actor_id: str = Query(...)):
    """Create pre-op assessment"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if already exists
    cursor.execute("SELECT id FROM preop_assessments WHERE case_id = ?", (case_id,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="PreOp assessment already exists")

    preop_id = generate_preop_id()

    try:
        cursor.execute("""
            INSERT INTO preop_assessments (
                id, case_id, mode,
                asa_class, asa_emergency,
                npo_hours, npo_status,
                allergies, mallampati_score,
                difficult_airway_anticipated,
                comorbidities, quick_flags,
                planned_technique, special_considerations,
                assessed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            preop_id,
            case_id,
            request.mode.value,
            request.asa_class,
            1 if request.asa_emergency else 0,
            request.npo_hours,
            request.npo_status,
            json.dumps(request.allergies) if request.allergies else None,
            request.mallampati_score,
            1 if request.difficult_airway_anticipated else 0,
            json.dumps(request.comorbidities) if request.comorbidities else None,
            json.dumps(request.quick_flags.dict()) if request.quick_flags else None,
            request.planned_technique,
            request.special_considerations,
            actor_id
        ))

        conn.commit()

        cursor.execute("SELECT * FROM preop_assessments WHERE id = ?", (preop_id,))
        row = cursor.fetchone()
        result = dict(row)
        result['allergies'] = json.loads(result['allergies']) if result['allergies'] else []
        result['quick_flags'] = json.loads(result['quick_flags']) if result['quick_flags'] else None

        return result

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/preop")
async def get_preop(case_id: str):
    """Get pre-op assessment"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM preop_assessments WHERE case_id = ?", (case_id,))
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="PreOp assessment not found")

    result = dict(row)
    result['allergies'] = json.loads(result['allergies']) if result['allergies'] else []
    result['comorbidities'] = json.loads(result['comorbidities']) if result['comorbidities'] else []
    result['quick_flags'] = json.loads(result['quick_flags']) if result['quick_flags'] else None

    return result


@router.post("/cases/{case_id}/preop/approve")
async def approve_preop(case_id: str, actor_id: str = Query(...)):
    """Approve pre-op assessment"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE preop_assessments
            SET status = 'APPROVED', approved_by = ?, approved_at = datetime('now')
            WHERE case_id = ?
        """, (actor_id, case_id))

        cursor.execute("""
            UPDATE anesthesia_cases
            SET preop_completed_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        conn.commit()

        return {"success": True, "approved_by": actor_id}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase A-5: Battlefield Preop (Quick 5 Flags)
# =============================================================================

class BattlefieldPreopRequest(BaseModel):
    """Battlefield mode quick preop assessment"""
    is_allergic: bool = False
    is_full_stomach: bool = False
    is_difficult_airway: bool = False
    is_hemodynamically_unstable: bool = False
    is_high_risk: bool = False
    quick_note: Optional[str] = None


@router.post("/cases/{case_id}/battlefield-preop")
async def save_battlefield_preop(
    case_id: str,
    request: BattlefieldPreopRequest,
    actor_id: str = Query(...)
):
    """Save battlefield mode quick preop assessment (5 flags)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        # Check if preop_assessments record exists
        cursor.execute("SELECT id FROM preop_assessments WHERE case_id = ?", (case_id,))
        existing = cursor.fetchone()

        quick_flags = {
            "is_allergic": request.is_allergic,
            "is_full_stomach": request.is_full_stomach,
            "is_difficult_airway": request.is_difficult_airway,
            "is_hemodynamically_unstable": request.is_hemodynamically_unstable,
            "is_high_risk": request.is_high_risk,
            "quick_note": request.quick_note
        }

        if existing:
            cursor.execute("""
                UPDATE preop_assessments
                SET quick_flags = ?, assessment_datetime = datetime('now')
                WHERE case_id = ?
            """, (json.dumps(quick_flags), case_id))
        else:
            preop_id = generate_event_id()
            cursor.execute("""
                INSERT INTO preop_assessments (
                    id, case_id, quick_flags, mode, assessed_by, assessment_datetime
                ) VALUES (?, ?, ?, 'BATTLEFIELD', ?, datetime('now'))
            """, (preop_id, case_id, json.dumps(quick_flags), actor_id))

        conn.commit()

        return {
            "success": True,
            "quick_flags": quick_flags
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/battlefield-preop")
async def get_battlefield_preop(case_id: str):
    """Get battlefield preop quick flags"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT quick_flags FROM preop_assessments WHERE case_id = ?", (case_id,))
    row = cursor.fetchone()

    if not row or not row['quick_flags']:
        return {"battlefield_preop": None}

    return {
        "battlefield_preop": json.loads(row['quick_flags'])
    }


# =============================================================================
# API Routes - Oxygen Cylinder Claim
# =============================================================================

@router.post("/cases/{case_id}/claim-oxygen")
async def claim_oxygen_cylinder(case_id: str, request: ClaimOxygenRequest, actor_id: str = Query(...)):
    """Claim an oxygen cylinder for this case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check cylinder is available
    cursor.execute("""
        SELECT id, unit_serial, claimed_by_case_id, level_percent
        FROM equipment_units
        WHERE id = ? AND (is_active = 1 OR is_active IS NULL)
    """, (request.cylinder_unit_id,))

    unit = cursor.fetchone()
    if not unit:
        raise HTTPException(status_code=404, detail="Cylinder not found")

    if unit['claimed_by_case_id']:
        raise HTTPException(
            status_code=400,
            detail=f"此氧氣瓶已被 {unit['claimed_by_case_id']} 使用中"
        )

    try:
        # Claim the cylinder
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_case_id = ?, claimed_at = datetime('now'), claimed_by_user_id = ?
            WHERE id = ?
        """, (case_id, actor_id, request.cylinder_unit_id))

        # Update case
        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = 'CYLINDER', oxygen_source_id = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (str(request.cylinder_unit_id), case_id))

        # Add resource check event
        event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_CHECK', datetime('now'), ?, ?)
        """, (
            event_id, case_id,
            json.dumps({
                "resource": "O2_CYLINDER",
                "cylinder_id": unit['unit_serial'],
                "unit_id": request.cylinder_unit_id,
                "level_percent": unit['level_percent'],
                "pressure_psi": request.initial_pressure_psi,
                "action": "CLAIM"
            }),
            actor_id
        ))

        conn.commit()

        return {
            "success": True,
            "cylinder_serial": unit['unit_serial'],
            "level_percent": unit['level_percent']
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cases/{case_id}/claim-oxygen")
async def release_oxygen_cylinder(case_id: str, actor_id: str = Query(...)):
    """Release claimed oxygen cylinder"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT oxygen_source_id FROM anesthesia_cases WHERE id = ?
    """, (case_id,))
    case = cursor.fetchone()

    if not case or not case['oxygen_source_id']:
        raise HTTPException(status_code=400, detail="No cylinder claimed")

    try:
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_case_id = NULL, claimed_at = NULL, claimed_by_user_id = NULL
            WHERE id = ?
        """, (int(case['oxygen_source_id']),))

        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = NULL, oxygen_source_id = NULL, updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        conn.commit()

        return {"success": True}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/oxygen-status")
async def get_oxygen_status(case_id: str):
    """Get current oxygen status and estimate"""
    # Vercel demo mode
    if IS_VERCEL and case_id.startswith("ANES-DEMO"):
        return {
            "source_type": "CYLINDER",
            "cylinder_id": "CYL-DEMO-001",
            "cylinder_serial": "O2-DEMO-001",
            "level_percent": 75,
            "est_minutes_remaining": 180,
            "avg_flow_lpm": 2.5,
            "demo_mode": True
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT oxygen_source_type, oxygen_source_id FROM anesthesia_cases WHERE id = ?
    """, (case_id,))
    case = cursor.fetchone()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['oxygen_source_type'] != 'CYLINDER' or not case['oxygen_source_id']:
        return {
            "source_type": case['oxygen_source_type'] or "NONE",
            "cylinder_id": None,
            "est_minutes_remaining": None
        }

    # Get cylinder info
    cursor.execute("""
        SELECT u.unit_serial, u.level_percent, et.capacity_config
        FROM equipment_units u
        JOIN equipment e ON u.equipment_id = e.id
        LEFT JOIN equipment_types et ON e.type_code = et.type_code
        WHERE u.id = ?
    """, (int(case['oxygen_source_id']),))

    cylinder = cursor.fetchone()
    if not cylinder:
        return {"source_type": "CYLINDER", "error": "Cylinder not found"}

    # Get latest flow rate from vitals
    cursor.execute("""
        SELECT payload FROM anesthesia_events
        WHERE case_id = ? AND event_type = 'VITAL_SIGN'
        ORDER BY clinical_time DESC LIMIT 10
    """, (case_id,))

    vitals = cursor.fetchall()
    flow_rates = []
    for v in vitals:
        payload = json.loads(v['payload'])
        if payload.get('o2_flow_lpm'):
            flow_rates.append(payload['o2_flow_lpm'])

    avg_flow = sum(flow_rates) / len(flow_rates) if flow_rates else 2.0  # Default 2 L/min

    # Calculate estimate
    capacity_config = json.loads(cylinder['capacity_config']) if cylinder['capacity_config'] else {}
    hours_per_100 = capacity_config.get('hours_per_100pct', 8)  # Default 8 hours
    current_hours = (cylinder['level_percent'] / 100) * hours_per_100
    est_minutes = int(current_hours * 60)

    # Adjust for flow rate if we have it
    if avg_flow > 0:
        # Assuming default is 2 L/min
        adjustment = 2.0 / avg_flow
        est_minutes = int(est_minutes * adjustment)

    return {
        "source_type": "CYLINDER",
        "cylinder_serial": cylinder['unit_serial'],
        "level_percent": cylinder['level_percent'],
        "avg_flow_lpm": round(avg_flow, 1),
        "est_minutes_remaining": est_minutes,
        "est_hours_remaining": round(est_minutes / 60, 1)
    }


# =============================================================================
# API Routes - PSI Event Sourcing (v2.0)
# =============================================================================

def rebuild_resource_status(cursor, case_id: str) -> dict:
    """
    從 RESOURCE_* 事件重建資源狀態 (Event Sourcing)

    Returns:
        {
            "current": { id, initial_psi, current_psi, claimed_at, last_check, flow_rate_lpm },
            "history": [ { id, initial_psi, final_psi, ... }, ... ],
            "total_cylinders": int,
            "total_consumed_liters": float
        }
    """
    cursor.execute("""
        SELECT event_type, payload, clinical_time
        FROM anesthesia_events
        WHERE case_id = ? AND event_type LIKE 'RESOURCE_%'
        ORDER BY clinical_time ASC
    """, (case_id,))

    events = cursor.fetchall()

    current_resource = None
    resources_used = []
    total_consumed = 0.0

    for event in events:
        event_type = event['event_type']
        payload = json.loads(event['payload'])
        clinical_time = event['clinical_time']

        if event_type == 'RESOURCE_CLAIM':
            current_resource = {
                'resource_id': payload.get('resource_id'),
                'resource_type': payload.get('resource_type', 'O2_CYLINDER'),
                'initial_psi': payload.get('initial_psi'),
                'current_psi': payload.get('initial_psi'),
                'capacity_liters': payload.get('capacity_liters'),
                'flow_rate_lpm': payload.get('flow_rate_lpm', 2.0),
                'claimed_at': clinical_time,
                'last_check': clinical_time
            }

        elif event_type == 'RESOURCE_CHECK':
            if current_resource and payload.get('resource_id') == current_resource['resource_id']:
                current_resource['current_psi'] = payload.get('psi')
                current_resource['last_check'] = clinical_time
                if payload.get('flow_rate_lpm'):
                    current_resource['flow_rate_lpm'] = payload['flow_rate_lpm']

        elif event_type == 'RESOURCE_SWITCH':
            # Finalize old resource
            if current_resource:
                current_resource['final_psi'] = payload.get('old_final_psi')
                current_resource['released_at'] = clinical_time
                # Calculate consumed liters if we have capacity info
                if current_resource.get('initial_psi') and current_resource.get('final_psi'):
                    psi_diff = current_resource['initial_psi'] - current_resource['final_psi']
                    # Rough estimate: 660L / 2200 PSI ≈ 0.3 L/PSI
                    consumed = psi_diff * 0.3
                    current_resource['consumed_liters'] = consumed
                    total_consumed += consumed
                resources_used.append(current_resource)

            # Start new resource
            current_resource = {
                'resource_id': payload.get('new_resource_id'),
                'resource_type': 'O2_CYLINDER',
                'initial_psi': payload.get('new_initial_psi'),
                'current_psi': payload.get('new_initial_psi'),
                'capacity_liters': payload.get('new_capacity_liters'),
                'flow_rate_lpm': payload.get('flow_rate_lpm', 2.0),
                'claimed_at': clinical_time,
                'last_check': clinical_time
            }

        elif event_type == 'RESOURCE_RELEASE':
            if current_resource and payload.get('resource_id') == current_resource['resource_id']:
                current_resource['final_psi'] = payload.get('final_psi')
                current_resource['released_at'] = clinical_time
                if payload.get('total_consumed_liters'):
                    current_resource['consumed_liters'] = payload['total_consumed_liters']
                    total_consumed += payload['total_consumed_liters']
                elif current_resource.get('initial_psi') and current_resource.get('final_psi'):
                    psi_diff = current_resource['initial_psi'] - current_resource['final_psi']
                    consumed = psi_diff * 0.3
                    current_resource['consumed_liters'] = consumed
                    total_consumed += consumed
                resources_used.append(current_resource)
                current_resource = None

    return {
        'current': current_resource,
        'history': resources_used,
        'total_cylinders': len(resources_used) + (1 if current_resource else 0),
        'total_consumed_liters': round(total_consumed, 1)
    }


@router.post("/cases/{case_id}/resource/claim")
async def resource_claim(case_id: str, request: ResourceClaimRequest, actor_id: str = Query(...)):
    """
    認領資源 (O2 筒, 設備) - Event Sourcing

    產生 RESOURCE_CLAIM 事件
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if already has an active resource
    status = rebuild_resource_status(cursor, case_id)
    if status['current']:
        raise HTTPException(
            status_code=409,
            detail=f"已有使用中的資源: {status['current']['resource_id']}，請先釋放或使用換瓶"
        )

    try:
        event_id = generate_event_id()
        payload = {
            "resource_type": request.resource_type,
            "resource_id": request.resource_id,
            "unit_id": request.unit_id,
            "initial_psi": request.initial_psi,
            "capacity_liters": request.capacity_liters,
            "flow_rate_lpm": request.flow_rate_lpm,
            "note": request.note
        }

        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_CLAIM', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(payload), actor_id))

        # Update case tracking (for backwards compatibility)
        if request.resource_type == 'O2_CYLINDER' and request.unit_id:
            cursor.execute("""
                UPDATE anesthesia_cases
                SET oxygen_source_type = 'CYLINDER', oxygen_source_id = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (str(request.unit_id), case_id))

            # Claim the equipment unit
            cursor.execute("""
                UPDATE equipment_units
                SET claimed_by_case_id = ?, claimed_at = datetime('now'), claimed_by_user_id = ?
                WHERE id = ?
            """, (case_id, actor_id, request.unit_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "resource_id": request.resource_id,
            "initial_psi": request.initial_psi
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/resource/check")
async def resource_check(case_id: str, request: ResourceCheckRequest, actor_id: str = Query(...)):
    """
    記錄 PSI 讀數 - Event Sourcing

    產生 RESOURCE_CHECK 事件
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify current resource
    status = rebuild_resource_status(cursor, case_id)
    if not status['current']:
        raise HTTPException(status_code=400, detail="沒有使用中的資源")

    if status['current']['resource_id'] != request.resource_id:
        raise HTTPException(
            status_code=400,
            detail=f"資源 ID 不符: 目前使用 {status['current']['resource_id']}"
        )

    try:
        event_id = generate_event_id()
        payload = {
            "resource_id": request.resource_id,
            "psi": request.psi,
            "flow_rate_lpm": request.flow_rate_lpm,
            "note": request.note
        }

        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_CHECK', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(payload), actor_id))

        conn.commit()

        # Calculate estimate
        current_psi = request.psi
        flow_rate = request.flow_rate_lpm or status['current'].get('flow_rate_lpm', 2.0)
        # 660L at 2200 PSI, 0.3 L/PSI
        remaining_liters = current_psi * 0.3
        est_minutes = int(remaining_liters / flow_rate) if flow_rate > 0 else None

        return {
            "success": True,
            "event_id": event_id,
            "resource_id": request.resource_id,
            "current_psi": current_psi,
            "est_minutes_remaining": est_minutes
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/resource/switch")
async def resource_switch(case_id: str, request: ResourceSwitchRequest, actor_id: str = Query(...)):
    """
    換瓶 (原子操作) - Event Sourcing

    產生 RESOURCE_SWITCH 事件
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify current resource
    status = rebuild_resource_status(cursor, case_id)
    if not status['current']:
        raise HTTPException(status_code=400, detail="沒有使用中的資源")

    if status['current']['resource_id'] != request.old_resource_id:
        raise HTTPException(
            status_code=400,
            detail=f"資源 ID 不符: 目前使用 {status['current']['resource_id']}"
        )

    try:
        event_id = generate_event_id()
        payload = {
            "old_resource_id": request.old_resource_id,
            "old_final_psi": request.old_final_psi,
            "new_resource_id": request.new_resource_id,
            "new_unit_id": request.new_unit_id,
            "new_initial_psi": request.new_initial_psi,
            "new_capacity_liters": request.new_capacity_liters,
            "flow_rate_lpm": request.flow_rate_lpm,
            "note": request.note
        }

        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_SWITCH', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(payload), actor_id))

        # Update equipment tracking
        if request.new_unit_id:
            # Release old cylinder
            cursor.execute("""
                UPDATE equipment_units
                SET claimed_by_case_id = NULL, claimed_at = NULL, claimed_by_user_id = NULL
                WHERE claimed_by_case_id = ?
            """, (case_id,))

            # Claim new cylinder
            cursor.execute("""
                UPDATE equipment_units
                SET claimed_by_case_id = ?, claimed_at = datetime('now'), claimed_by_user_id = ?
                WHERE id = ?
            """, (case_id, actor_id, request.new_unit_id))

            cursor.execute("""
                UPDATE anesthesia_cases
                SET oxygen_source_id = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (str(request.new_unit_id), case_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "old_resource_id": request.old_resource_id,
            "old_final_psi": request.old_final_psi,
            "new_resource_id": request.new_resource_id,
            "new_initial_psi": request.new_initial_psi
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/resource/release")
async def resource_release(case_id: str, request: ResourceReleaseRequest, actor_id: str = Query(...)):
    """
    釋放資源 - Event Sourcing

    產生 RESOURCE_RELEASE 事件
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify current resource
    status = rebuild_resource_status(cursor, case_id)
    if not status['current']:
        raise HTTPException(status_code=400, detail="沒有使用中的資源")

    if status['current']['resource_id'] != request.resource_id:
        raise HTTPException(
            status_code=400,
            detail=f"資源 ID 不符: 目前使用 {status['current']['resource_id']}"
        )

    try:
        event_id = generate_event_id()
        payload = {
            "resource_id": request.resource_id,
            "final_psi": request.final_psi,
            "total_consumed_liters": request.total_consumed_liters,
            "note": request.note
        }

        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_RELEASE', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(payload), actor_id))

        # Clear equipment tracking
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_case_id = NULL, claimed_at = NULL, claimed_by_user_id = NULL
            WHERE claimed_by_case_id = ?
        """, (case_id,))

        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = NULL, oxygen_source_id = NULL, updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "resource_id": request.resource_id,
            "final_psi": request.final_psi
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/resource/status")
async def get_resource_status(case_id: str):
    """
    取得資源狀態 - Event Sourcing 重建

    從 RESOURCE_* 事件重建目前狀態
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    status = rebuild_resource_status(cursor, case_id)

    # Add estimate for current resource
    if status['current']:
        current = status['current']
        current_psi = current.get('current_psi') or current.get('initial_psi')
        flow_rate = current.get('flow_rate_lpm', 2.0)

        if current_psi and flow_rate > 0:
            remaining_liters = current_psi * 0.3
            est_minutes = int(remaining_liters / flow_rate)
            status['current']['est_minutes_remaining'] = est_minutes
            status['current']['est_hours_remaining'] = round(est_minutes / 60, 1)

    return status


# =============================================================================
# API Routes - Case Close
# =============================================================================

@router.post("/cases/{case_id}/close")
async def close_case(case_id: str, actor_id: str = Query(...)):
    """Close anesthesia case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status, oxygen_source_id, cirs_registration_ref FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Case already closed")

    try:
        # Release oxygen cylinder if claimed
        if case['oxygen_source_id']:
            cursor.execute("""
                UPDATE equipment_units
                SET claimed_by_case_id = NULL, claimed_at = NULL, claimed_by_user_id = NULL
                WHERE id = ?
            """, (int(case['oxygen_source_id']),))

        # Update case status
        cursor.execute("""
            UPDATE anesthesia_cases
            SET status = 'CLOSED', oxygen_source_type = NULL, oxygen_source_id = NULL,
                updated_at = datetime('now')
            WHERE id = ?
        """, (case_id,))

        # Add status change event
        event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'STATUS_CHANGE', datetime('now'), ?, ?)
        """, (
            event_id, case_id,
            json.dumps({"from": case['status'], "to": "CLOSED"}),
            actor_id
        ))

        conn.commit()

        # v1.1: Notify CIRS that anesthesia is done (non-blocking)
        if case['cirs_registration_ref']:
            try:
                async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
                    await client.post(
                        f"{CIRS_HUB_URL}/api/registrations/{case['cirs_registration_ref']}/anesthesia-done",
                        json={"actor_id": actor_id}
                    )
                    logger.info(f"CIRS registration {case['cirs_registration_ref']} marked anesthesia done")
            except Exception as e:
                logger.warning(f"Failed to notify CIRS of anesthesia completion: {e}")

        return {"success": True, "status": "CLOSED"}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase A-4: Quick Actions (One-Tap Medications & Vitals)
# =============================================================================

QUICK_DRUGS = [
    {"code": "PROP", "name": "Propofol", "default_dose": 100, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "FENT", "name": "Fentanyl", "default_dose": 100, "unit": "mcg", "route": "IV", "is_controlled": True},
    {"code": "ROCU", "name": "Rocuronium", "default_dose": 50, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "SUXI", "name": "Succinylcholine", "default_dose": 100, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "MIDA", "name": "Midazolam", "default_dose": 2, "unit": "mg", "route": "IV", "is_controlled": True},
    {"code": "ATRO", "name": "Atropine", "default_dose": 0.5, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "EPHE", "name": "Ephedrine", "default_dose": 10, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "PHEN", "name": "Phenylephrine", "default_dose": 100, "unit": "mcg", "route": "IV", "is_controlled": False},
    {"code": "STER", "name": "Sugammadex", "default_dose": 200, "unit": "mg", "route": "IV", "is_controlled": False},
    {"code": "NEOS", "name": "Neostigmine", "default_dose": 2.5, "unit": "mg", "route": "IV", "is_controlled": False},
]


@router.get("/quick-drugs")
async def get_quick_drugs():
    """Get list of quick drugs for one-tap administration"""
    return {"drugs": QUICK_DRUGS}


@router.post("/cases/{case_id}/quick-drug/{drug_code}")
async def quick_drug_admin(
    case_id: str,
    drug_code: str,
    dose: Optional[float] = Query(None, description="Custom dose (uses default if not provided)"),
    actor_id: str = Query(..., description="User ID administering the drug")
):
    """Quick one-tap drug administration"""
    drug = next((d for d in QUICK_DRUGS if d["code"] == drug_code), None)
    if not drug:
        raise HTTPException(status_code=404, detail=f"Drug code '{drug_code}' not in quick list")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    actual_dose = dose if dose is not None else drug["default_dose"]
    event_id = generate_event_id()

    payload = {
        "drug_code": drug["code"],
        "drug_name": drug["name"],
        "dose": actual_dose,
        "unit": drug["unit"],
        "route": drug["route"],
        "is_controlled": drug["is_controlled"],
        "quick_admin": True
    }

    try:
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'MEDICATION_ADMIN', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(payload), actor_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "drug": drug["name"],
            "dose": actual_dose,
            "unit": drug["unit"]
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# Quick vital signs templates
QUICK_VITALS_TEMPLATES = [
    {"name": "正常", "hr": 75, "sbp": 120, "dbp": 80, "spo2": 99, "rr": 14},
    {"name": "誘導中", "hr": 85, "sbp": 100, "dbp": 60, "spo2": 100, "rr": 0},
    {"name": "維持期", "hr": 70, "sbp": 110, "dbp": 70, "spo2": 100, "rr": 12},
    {"name": "甦醒", "hr": 80, "sbp": 130, "dbp": 85, "spo2": 98, "rr": 16},
]


@router.get("/quick-vitals-templates")
async def get_quick_vitals_templates():
    """Get predefined vital sign templates for quick entry"""
    return {"templates": QUICK_VITALS_TEMPLATES}


@router.post("/cases/{case_id}/quick-vitals")
async def quick_vitals(
    case_id: str,
    template: Optional[str] = Query(None, description="Template name (正常/誘導中/維持期/甦醒)"),
    hr: Optional[int] = Query(None, ge=0, le=300),
    sbp: Optional[int] = Query(None, ge=0, le=300),
    dbp: Optional[int] = Query(None, ge=0, le=200),
    spo2: Optional[int] = Query(None, ge=0, le=100),
    rr: Optional[int] = Query(None, ge=0, le=60),
    actor_id: str = Query(...)
):
    """Quick vital signs entry (supports templates or individual values)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    # Use template or provided values
    vitals = {}
    if template:
        tpl = next((t for t in QUICK_VITALS_TEMPLATES if t["name"] == template), None)
        if tpl:
            vitals = {k: v for k, v in tpl.items() if k != "name"}

    # Override with any provided values
    if hr is not None: vitals["hr"] = hr
    if sbp is not None: vitals["sbp"] = sbp
    if dbp is not None: vitals["dbp"] = dbp
    if spo2 is not None: vitals["spo2"] = spo2
    if rr is not None: vitals["rr"] = rr

    if not vitals:
        raise HTTPException(status_code=400, detail="No vital signs provided")

    event_id = generate_event_id()

    try:
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'VITAL_SIGN', datetime('now'), ?, ?)
        """, (event_id, case_id, json.dumps(vitals), actor_id))

        conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "vitals": vitals
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase A-6: WAL Sync API (Offline-First)
# =============================================================================

class SyncQueueItem(BaseModel):
    """Item to be synced from offline queue"""
    id: str
    device_id: str
    operation: str  # POST, PUT, DELETE
    endpoint: str   # e.g., /cases/{id}/events
    payload: Dict[str, Any]
    idempotency_key: str
    created_at: str


class SyncBatchRequest(BaseModel):
    """Batch sync request from offline client"""
    device_id: str
    items: List[SyncQueueItem]


class SyncStatusResponse(BaseModel):
    """Sync status for a device"""
    device_id: str
    pending_count: int
    last_sync: Optional[str]
    failed_items: List[str]


@router.post("/sync/batch")
async def sync_batch(request: SyncBatchRequest):
    """
    Process a batch of offline operations.
    Uses idempotency keys to prevent duplicates.
    Returns results for each item.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    results = []

    for item in request.items:
        try:
            # Check if already processed (idempotency)
            cursor.execute("""
                SELECT id, status FROM anesthesia_sync_queue
                WHERE idempotency_key = ?
            """, (item.idempotency_key,))
            existing = cursor.fetchone()

            if existing and existing['status'] == 'SYNCED':
                results.append({
                    "id": item.id,
                    "status": "duplicate",
                    "message": "Already synced"
                })
                continue

            # Record in sync queue
            if not existing:
                cursor.execute("""
                    INSERT INTO anesthesia_sync_queue (
                        id, device_id, operation, endpoint, payload,
                        idempotency_key, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'SYNCING')
                """, (
                    item.id, item.device_id, item.operation,
                    item.endpoint, json.dumps(item.payload),
                    item.idempotency_key
                ))
            else:
                cursor.execute("""
                    UPDATE anesthesia_sync_queue
                    SET status = 'SYNCING', retry_count = retry_count + 1
                    WHERE id = ?
                """, (existing['id'],))

            # Process the operation based on endpoint pattern
            success = False
            error_msg = None

            try:
                # Parse endpoint to determine action
                endpoint = item.endpoint
                payload = item.payload

                if endpoint.startswith("/cases/") and "/events" in endpoint:
                    # Event creation
                    case_id = endpoint.split("/")[2]
                    event_id = generate_event_id()
                    cursor.execute("""
                        INSERT INTO anesthesia_events (
                            id, case_id, event_type, clinical_time, payload,
                            actor_id, device_id, idempotency_key, sync_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SYNCED')
                    """, (
                        event_id, case_id, payload.get('event_type'),
                        payload.get('clinical_time', datetime.now().isoformat()),
                        json.dumps(payload.get('payload', {})),
                        payload.get('actor_id'), item.device_id,
                        item.idempotency_key
                    ))
                    success = True

                elif endpoint.startswith("/cases") and item.operation == "POST":
                    # Case creation - handled by main API
                    success = True

                else:
                    error_msg = f"Unknown endpoint: {endpoint}"

            except Exception as e:
                error_msg = str(e)

            # Update sync queue status
            if success:
                cursor.execute("""
                    UPDATE anesthesia_sync_queue
                    SET status = 'SYNCED', synced_at = datetime('now')
                    WHERE idempotency_key = ?
                """, (item.idempotency_key,))
                results.append({
                    "id": item.id,
                    "status": "synced",
                    "message": "OK"
                })
            else:
                cursor.execute("""
                    UPDATE anesthesia_sync_queue
                    SET status = 'FAILED', last_error = ?
                    WHERE idempotency_key = ?
                """, (error_msg, item.idempotency_key))
                results.append({
                    "id": item.id,
                    "status": "failed",
                    "message": error_msg
                })

        except Exception as e:
            results.append({
                "id": item.id,
                "status": "error",
                "message": str(e)
            })

    conn.commit()

    return {
        "processed": len(results),
        "results": results
    }


@router.get("/sync/status")
async def get_sync_status(device_id: str = Query(...)):
    """Get sync status for a specific device"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get pending count
    cursor.execute("""
        SELECT COUNT(*) as count FROM anesthesia_sync_queue
        WHERE device_id = ? AND status = 'PENDING'
    """, (device_id,))
    pending = cursor.fetchone()['count']

    # Get last sync time
    cursor.execute("""
        SELECT MAX(synced_at) as last_sync FROM anesthesia_sync_queue
        WHERE device_id = ? AND status = 'SYNCED'
    """, (device_id,))
    last_sync = cursor.fetchone()['last_sync']

    # Get failed items
    cursor.execute("""
        SELECT id FROM anesthesia_sync_queue
        WHERE device_id = ? AND status = 'FAILED'
        ORDER BY created_at DESC
        LIMIT 10
    """, (device_id,))
    failed = [row['id'] for row in cursor.fetchall()]

    return {
        "device_id": device_id,
        "pending_count": pending,
        "last_sync": last_sync,
        "failed_items": failed
    }


@router.get("/sync/pending")
async def get_pending_events(
    case_id: str = Query(...),
    since: Optional[str] = Query(None, description="ISO timestamp to get events after")
):
    """
    Get events that need to be synced to a device.
    Used for pulling updates from server to offline client.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if since:
        cursor.execute("""
            SELECT id, event_type, clinical_time, payload, actor_id,
                   recorded_at, idempotency_key
            FROM anesthesia_events
            WHERE case_id = ? AND recorded_at > ?
            ORDER BY clinical_time ASC
        """, (case_id, since))
    else:
        cursor.execute("""
            SELECT id, event_type, clinical_time, payload, actor_id,
                   recorded_at, idempotency_key
            FROM anesthesia_events
            WHERE case_id = ?
            ORDER BY clinical_time ASC
        """, (case_id,))

    events = []
    for row in cursor.fetchall():
        events.append({
            "id": row['id'],
            "event_type": row['event_type'],
            "clinical_time": row['clinical_time'],
            "payload": json.loads(row['payload']) if row['payload'] else {},
            "actor_id": row['actor_id'],
            "recorded_at": row['recorded_at'],
            "idempotency_key": row['idempotency_key']
        })

    return {
        "case_id": case_id,
        "events": events,
        "count": len(events),
        "server_time": datetime.now().isoformat()
    }


@router.delete("/sync/queue/{item_id}")
async def remove_from_queue(item_id: str):
    """Remove a synced or failed item from the queue"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM anesthesia_sync_queue
        WHERE id = ? AND status IN ('SYNCED', 'FAILED')
    """, (item_id,))

    conn.commit()

    return {"deleted": cursor.rowcount > 0}


# =============================================================================
# Phase B: Controlled Drugs API
# =============================================================================

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class DrugRequestItem(BaseModel):
    drug_code: str
    drug_name: str
    quantity: float
    unit: str
    schedule_class: int = 4  # 管制藥品級別 (1-4)


class CreateDrugRequestRequest(BaseModel):
    items: List[DrugRequestItem]


class DrugTransactionRequest(BaseModel):
    drug_code: str
    drug_name: str
    quantity: float
    unit: str
    tx_type: DrugTxType
    schedule_class: int = 4
    batch_number: Optional[str] = None
    witness_id: Optional[str] = None  # Required for WASTE
    notes: Optional[str] = None
    request_id: Optional[str] = None
    device_id: Optional[str] = None
    idempotency_key: Optional[str] = None


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def generate_request_id() -> str:
    """Generate unique drug request ID"""
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:4].upper()
    return f"REQ-{date_str}-{short_uuid}"


def generate_tx_id() -> str:
    """Generate unique transaction ID"""
    return f"TX-{uuid.uuid4().hex[:12].upper()}"


def calculate_drug_holdings(cursor, case_id: str) -> List[Dict]:
    """
    Calculate current drug holdings for a case.
    Balance = DISPENSE - (ADMIN + WASTE + RETURN)
    """
    cursor.execute("""
        SELECT
            drug_code,
            drug_name,
            unit,
            schedule_class,
            SUM(CASE WHEN tx_type = 'DISPENSE' THEN quantity ELSE 0 END) as dispensed,
            SUM(CASE WHEN tx_type = 'ADMIN' THEN quantity ELSE 0 END) as administered,
            SUM(CASE WHEN tx_type = 'WASTE' THEN quantity ELSE 0 END) as wasted,
            SUM(CASE WHEN tx_type = 'RETURN' THEN quantity ELSE 0 END) as returned
        FROM drug_transactions
        WHERE case_id = ?
        GROUP BY drug_code, drug_name, unit
    """, (case_id,))

    holdings = []
    for row in cursor.fetchall():
        dispensed = row['dispensed'] or 0
        administered = row['administered'] or 0
        wasted = row['wasted'] or 0
        returned = row['returned'] or 0
        balance = dispensed - administered - wasted - returned

        holdings.append({
            "drug_code": row['drug_code'],
            "drug_name": row['drug_name'],
            "unit": row['unit'],
            "schedule_class": row['schedule_class'],
            "dispensed": dispensed,
            "administered": administered,
            "wasted": wasted,
            "returned": returned,
            "balance": round(balance, 2)
        })

    return holdings


def get_total_balance(cursor, case_id: str) -> float:
    """Get total drug balance for a case (for validation)"""
    holdings = calculate_drug_holdings(cursor, case_id)
    return sum(h['balance'] for h in holdings)


# -----------------------------------------------------------------------------
# Drug Request API
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/drugs/request")
async def create_drug_request(
    case_id: str,
    request: CreateDrugRequestRequest,
    actor_id: str = Query(...),
    actor_role: str = Query("ANES_NA")
):
    """Create a new controlled drug request for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot request drugs for closed case")

    request_id = generate_request_id()

    try:
        cursor.execute("""
            INSERT INTO drug_requests (
                id, case_id, requester_id, requester_role, items, status
            ) VALUES (?, ?, ?, ?, ?, 'PENDING')
        """, (
            request_id,
            case_id,
            actor_id,
            actor_role,
            json.dumps([item.dict() for item in request.items])
        ))

        conn.commit()

        return {
            "request_id": request_id,
            "case_id": case_id,
            "status": "PENDING",
            "items": [item.dict() for item in request.items]
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/drugs/requests")
async def list_drug_requests(case_id: str):
    """List all drug requests for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, case_id, requester_id, requester_role, items,
               approver_id, approved_at, status, created_at
        FROM drug_requests
        WHERE case_id = ?
        ORDER BY created_at DESC
    """, (case_id,))

    requests = []
    for row in cursor.fetchall():
        requests.append({
            "id": row['id'],
            "case_id": row['case_id'],
            "requester_id": row['requester_id'],
            "requester_role": row['requester_role'],
            "items": json.loads(row['items']) if row['items'] else [],
            "approver_id": row['approver_id'],
            "approved_at": row['approved_at'],
            "status": row['status'],
            "created_at": row['created_at']
        })

    return {"requests": requests}


@router.post("/drugs/requests/{request_id}/approve")
async def approve_drug_request(
    request_id: str,
    actor_id: str = Query(...),
    actor_role: str = Query("PHARMACY")
):
    """Approve a drug request (Pharmacy or Supervisor)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM drug_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req['status'] != 'PENDING':
        raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

    try:
        cursor.execute("""
            UPDATE drug_requests
            SET status = 'APPROVED', approver_id = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (actor_id, request_id))

        conn.commit()

        return {"request_id": request_id, "status": "APPROVED"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drugs/requests/{request_id}/dispense")
async def dispense_drug_request(
    request_id: str,
    actor_id: str = Query(...),
    batch_numbers: Optional[Dict[str, str]] = None  # drug_code -> batch_number
):
    """
    Dispense drugs from an approved request.
    Creates DISPENSE transactions for each item.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM drug_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req['status'] not in ('APPROVED', 'PENDING'):
        raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

    items = json.loads(req['items'])
    case_id = req['case_id']
    tx_time = datetime.now().isoformat()

    try:
        # Create DISPENSE transactions for each item
        transactions = []
        for item in items:
            tx_id = generate_tx_id()
            batch = (batch_numbers or {}).get(item['drug_code'])

            cursor.execute("""
                INSERT INTO drug_transactions (
                    id, request_id, case_id,
                    drug_code, drug_name, schedule_class, batch_number,
                    tx_type, quantity, unit,
                    actor_id, tx_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DISPENSE', ?, ?, ?, ?)
            """, (
                tx_id, request_id, case_id,
                item['drug_code'], item['drug_name'], item.get('schedule_class', 4), batch,
                item['quantity'], item['unit'],
                actor_id, tx_time
            ))

            transactions.append({
                "tx_id": tx_id,
                "drug_code": item['drug_code'],
                "quantity": item['quantity']
            })

        # Update request status
        cursor.execute("""
            UPDATE drug_requests SET status = 'DISPENSED' WHERE id = ?
        """, (request_id,))

        conn.commit()

        return {
            "request_id": request_id,
            "status": "DISPENSED",
            "transactions": transactions
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Drug Transaction API (Direct Recording)
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/drugs/transaction")
async def record_drug_transaction(
    case_id: str,
    request: DrugTransactionRequest,
    actor_id: str = Query(...)
):
    """
    Record a drug transaction (ADMIN, WASTE, RETURN).
    WASTE requires witness_id.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists and is not closed
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot record transaction for closed case")

    # WASTE requires witness
    if request.tx_type == DrugTxType.WASTE and not request.witness_id:
        raise HTTPException(
            status_code=400,
            detail="Witness ID required for drug waste (管藥廢棄需要見證人)"
        )

    # Check for sufficient balance for ADMIN/WASTE/RETURN
    if request.tx_type in (DrugTxType.ADMIN, DrugTxType.WASTE, DrugTxType.RETURN):
        holdings = calculate_drug_holdings(cursor, case_id)
        drug_holding = next((h for h in holdings if h['drug_code'] == request.drug_code), None)
        current_balance = drug_holding['balance'] if drug_holding else 0

        if request.quantity > current_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient balance. Available: {current_balance} {request.unit}"
            )

    tx_id = generate_tx_id()
    tx_time = datetime.now().isoformat()

    # Handle idempotency
    if request.idempotency_key:
        cursor.execute(
            "SELECT id FROM drug_transactions WHERE idempotency_key = ?",
            (request.idempotency_key,)
        )
        existing = cursor.fetchone()
        if existing:
            return {"tx_id": existing['id'], "status": "DUPLICATE"}

    try:
        cursor.execute("""
            INSERT INTO drug_transactions (
                id, request_id, case_id,
                drug_code, drug_name, schedule_class, batch_number,
                tx_type, quantity, unit,
                actor_id, witness_id, witness_verified_at,
                device_id, idempotency_key, tx_time, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx_id,
            request.request_id,
            case_id,
            request.drug_code,
            request.drug_name,
            request.schedule_class,
            request.batch_number,
            request.tx_type.value,
            request.quantity,
            request.unit,
            actor_id,
            request.witness_id,
            datetime.now().isoformat() if request.witness_id else None,
            request.device_id,
            request.idempotency_key,
            tx_time,
            request.notes
        ))

        conn.commit()

        # Get updated holdings
        holdings = calculate_drug_holdings(cursor, case_id)

        return {
            "tx_id": tx_id,
            "tx_type": request.tx_type.value,
            "drug_code": request.drug_code,
            "quantity": request.quantity,
            "unit": request.unit,
            "actor_id": actor_id,
            "witness_id": request.witness_id,
            "holdings": holdings
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Drug Holdings API
# -----------------------------------------------------------------------------

@router.get("/cases/{case_id}/drugs/holdings")
async def get_drug_holdings(case_id: str):
    """Get current drug holdings (balance) for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    holdings = calculate_drug_holdings(cursor, case_id)
    total_balance = sum(h['balance'] for h in holdings)

    return {
        "case_id": case_id,
        "holdings": holdings,
        "total_balance": round(total_balance, 2),
        "is_reconciled": total_balance == 0
    }


@router.get("/cases/{case_id}/drugs/transactions")
async def list_drug_transactions(case_id: str):
    """List all drug transactions for a case"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, request_id, drug_code, drug_name, schedule_class,
               tx_type, quantity, unit, actor_id, witness_id,
               tx_time, recorded_at, notes
        FROM drug_transactions
        WHERE case_id = ?
        ORDER BY tx_time DESC
    """, (case_id,))

    transactions = []
    for row in cursor.fetchall():
        transactions.append({
            "id": row['id'],
            "request_id": row['request_id'],
            "drug_code": row['drug_code'],
            "drug_name": row['drug_name'],
            "schedule_class": row['schedule_class'],
            "tx_type": row['tx_type'],
            "quantity": row['quantity'],
            "unit": row['unit'],
            "actor_id": row['actor_id'],
            "witness_id": row['witness_id'],
            "tx_time": row['tx_time'],
            "recorded_at": row['recorded_at'],
            "notes": row['notes']
        })

    return {"transactions": transactions, "count": len(transactions)}


# -----------------------------------------------------------------------------
# Drug Reconciliation API
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/drugs/reconcile")
async def reconcile_drugs(
    case_id: str,
    actor_id: str = Query(...),
    actor_role: str = Query("ANES_MD")
):
    """
    Reconcile drugs for a case.
    Requires total balance = 0 and ANES_MD role.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify role
    if actor_role != "ANES_MD":
        raise HTTPException(
            status_code=403,
            detail="Only ANES_MD can reconcile drugs (需要麻醉醫師核准)"
        )

    # Verify case exists
    cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check balance
    total_balance = get_total_balance(cursor, case_id)
    if total_balance != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reconcile: balance is {total_balance}, must be 0"
        )

    # Update all pending requests to RECONCILED
    cursor.execute("""
        UPDATE drug_requests
        SET status = 'RECONCILED'
        WHERE case_id = ? AND status = 'DISPENSED'
    """, (case_id,))

    conn.commit()

    return {
        "case_id": case_id,
        "status": "RECONCILED",
        "reconciled_by": actor_id,
        "reconciled_at": datetime.now().isoformat()
    }


@router.get("/cases/{case_id}/drugs/can-close")
async def check_can_close_case(case_id: str):
    """Check if case can be closed (drug balance must be 0)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Case not found")

    total_balance = get_total_balance(cursor, case_id)
    holdings = calculate_drug_holdings(cursor, case_id)

    return {
        "case_id": case_id,
        "can_close": total_balance == 0,
        "total_balance": round(total_balance, 2),
        "holdings": holdings,
        "message": None if total_balance == 0 else f"Drug balance must be 0 (current: {total_balance})"
    }


# ============================================================
# CIRS Hub Proxy Endpoints (Hub-Satellite Architecture)
# ============================================================

import httpx
from fastapi.responses import JSONResponse

# CIRS Hub configuration
CIRS_HUB_URL = os.getenv("CIRS_HUB_URL", "http://localhost:8090")
CIRS_TIMEOUT = 5.0  # seconds

# xIRS Protocol Version (see DEV_SPEC Section I.2)
XIRS_PROTOCOL_VERSION = "1.0"
STATION_ID = os.getenv("MIRS_STATION_ID", "MIRS-UNKNOWN")

# Demo data for Vercel mode (simulated anesthesia waiting list)
DEMO_ANESTHESIA_PATIENTS = [
    {
        "registration_id": "REG-DEMO-001",
        "patient_id": "P-DEMO-001",
        "patient_ref": "D001",
        "name": "王大明",
        "age_group": "55-64",
        "sex": "M",
        "triage_category": "3",
        "priority": "ROUTINE",
        "chief_complaint": "右股骨頸骨折，需術前麻醉評估",
        "anesthesia_notes": "患者有高血壓病史，術前需確認血壓控制情況",
        "consultation_by": "陳醫師",
        "consultation_completed_at": None,
        "waiting_minutes": 45,
        "claimed_by": None,
        "claimed_at": None
    },
    {
        "registration_id": "REG-DEMO-002",
        "patient_id": "P-DEMO-002",
        "patient_ref": "D002",
        "name": "林小華",
        "age_group": "35-44",
        "sex": "F",
        "triage_category": "2",
        "priority": "URGENT",
        "chief_complaint": "急性闘尾炎，需緊急手術",
        "anesthesia_notes": "禁食6小時以上，無藥物過敏史",
        "consultation_by": "張醫師",
        "consultation_completed_at": None,
        "waiting_minutes": 15,
        "claimed_by": None,
        "claimed_at": None
    },
    {
        "registration_id": "REG-DEMO-003",
        "patient_id": "P-DEMO-003",
        "patient_ref": "D003",
        "name": "陳志明",
        "age_group": "45-54",
        "sex": "M",
        "triage_category": "2",
        "priority": "URGENT",
        "chief_complaint": "左脛骨開放性骨折 (Gustilo IIIA)，需行 ORIF 開放性復位內固定手術",
        "anesthesia_notes": "傷口已清創包紮，破傷風已施打；建議全身麻醉",
        "consultation_by": "李醫師",
        "consultation_completed_at": None,
        "waiting_minutes": 90,
        "claimed_by": None,
        "claimed_at": None
    }
]


def make_xirs_response(data: dict, hub_revision: int = 0) -> JSONResponse:
    """Create response with xIRS protocol headers."""
    return JSONResponse(
        content=data,
        headers={
            "X-XIRS-Protocol-Version": XIRS_PROTOCOL_VERSION,
            "X-XIRS-Hub-Revision": str(hub_revision),
            "X-XIRS-Station-Id": STATION_ID,
        }
    )


@router.get("/proxy/cirs/waiting-list")
async def get_cirs_waiting_list(
    status: Optional[str] = "waiting",
    limit: int = 50
):
    """
    Proxy endpoint to fetch waiting list from CIRS Hub.
    Returns patients waiting for procedures (for case creation).

    Gracefully handles offline scenarios by returning empty list with offline flag.

    Response Headers:
    - X-XIRS-Protocol-Version: Contract version (1.0)
    - X-XIRS-Hub-Revision: Latest Hub revision number
    - X-XIRS-Station-Id: This satellite's station ID
    """
    hub_revision = 0

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            # Use the waiting list endpoint (no auth required for Doctor PWA compatibility)
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/waiting/list"
            )

            # Extract hub revision from response headers if available
            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                data = response.json()
                # Transform CIRS data to MIRS format
                # CIRS waiting list format: reg_id, patient_ref, display_name, triage, priority, etc.
                patients = []
                for reg in data.get("registrations", data if isinstance(data, list) else []):
                    patients.append({
                        "registration_id": reg.get("reg_id") or reg.get("id") or reg.get("registration_id"),
                        "patient_id": reg.get("patient_id") or reg.get("person_id"),
                        "patient_ref": reg.get("patient_ref"),  # Masked patient reference
                        "name": reg.get("display_name") or reg.get("patient_name") or reg.get("name"),
                        "age_group": reg.get("age_group"),
                        "dob": reg.get("dob"),
                        "sex": reg.get("gender") or reg.get("sex"),
                        "allergies": reg.get("allergies", []),
                        "weight_kg": reg.get("weight_kg"),
                        "blood_type": reg.get("blood_type"),
                        "triage_category": reg.get("triage") or reg.get("triage_category"),
                        "priority": reg.get("priority"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "status": reg.get("status"),
                        "registered_at": reg.get("registered_at") or reg.get("created_at")
                    })

                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "patients": patients,
                    "count": len(patients),
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)
            else:
                logger.warning(f"CIRS Hub returned {response.status_code}")
                return make_xirs_response({
                    "online": False,
                    "source": "offline",
                    "patients": [],
                    "count": 0,
                    "error": f"CIRS returned status {response.status_code}",
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)

    except httpx.TimeoutException:
        logger.warning("CIRS Hub timeout - operating in offline mode")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub timeout",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except httpx.ConnectError:
        logger.info("CIRS Hub not reachable - operating in offline mode")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub not reachable",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except Exception as e:
        logger.error(f"CIRS proxy error: {e}")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "patients": [],
            "count": 0,
            "error": str(e),
            "protocol_version": XIRS_PROTOCOL_VERSION
        })


@router.get("/proxy/cirs/waiting-anesthesia")
async def get_cirs_waiting_anesthesia():
    """
    v1.1: 取得待麻醉清單 (使用新的 CIRS /waiting/anesthesia 端點)

    只返回:
    - status = CONSULTATION_DONE
    - needs_anesthesia = 1

    這是 v1.1 流程改進的核心：醫師完成看診後勾選「需麻醉」的病患才會出現。

    v1.5.2: 在 Vercel demo 模式下返回模擬資料供測試。
    """
    hub_revision = 0

    # v1.5.2: Vercel demo mode - return simulated patients
    if IS_VERCEL:
        return make_xirs_response({
            "online": True,
            "source": "demo",
            "queue": "ANESTHESIA",
            "patients": DEMO_ANESTHESIA_PATIENTS,
            "count": len(DEMO_ANESTHESIA_PATIENTS),
            "demo_mode": True,
            "demo_note": "這是展示用模擬資料，實際部署請連接 CIRS Hub",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            # v1.1: 使用新的 waiting/anesthesia 端點
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/waiting/anesthesia"
            )

            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                data = response.json()
                # Transform CIRS data to MIRS format
                patients = []
                for reg in data.get("items", []):
                    patients.append({
                        "registration_id": reg.get("reg_id"),
                        "patient_id": reg.get("person_id"),
                        "patient_ref": reg.get("patient_ref"),
                        "name": reg.get("display_name"),
                        "age_group": reg.get("age_group"),
                        "sex": reg.get("gender"),
                        "triage_category": reg.get("triage"),
                        "priority": reg.get("priority"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "anesthesia_notes": reg.get("anesthesia_notes"),
                        "consultation_by": reg.get("consultation_by"),
                        "consultation_completed_at": reg.get("consultation_completed_at"),
                        "waiting_minutes": reg.get("waiting_minutes"),
                        "claimed_by": reg.get("anesthesia_claimed_by"),
                        "claimed_at": reg.get("anesthesia_claimed_at")
                    })

                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "queue": "ANESTHESIA",
                    "patients": patients,
                    "count": len(patients),
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)
            else:
                logger.warning(f"CIRS Hub waiting/anesthesia returned {response.status_code}")
                return make_xirs_response({
                    "online": False,
                    "source": "offline",
                    "queue": "ANESTHESIA",
                    "patients": [],
                    "count": 0,
                    "error": f"CIRS returned status {response.status_code}",
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)

    except httpx.TimeoutException:
        logger.warning("CIRS Hub timeout for waiting/anesthesia")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "ANESTHESIA",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub timeout",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except httpx.ConnectError:
        logger.info("CIRS Hub not reachable for waiting/anesthesia")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "ANESTHESIA",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub not reachable",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })
    except Exception as e:
        logger.error(f"CIRS waiting/anesthesia proxy error: {e}")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "ANESTHESIA",
            "patients": [],
            "count": 0,
            "error": str(e),
            "protocol_version": XIRS_PROTOCOL_VERSION
        })


@router.get("/proxy/cirs/patient/{registration_id}")
async def get_cirs_patient_details(registration_id: str):
    """
    Fetch detailed patient info from CIRS Hub by registration ID.
    Used when creating a case to get full patient snapshot.

    Response Headers:
    - X-XIRS-Protocol-Version: Contract version (1.0)
    - X-XIRS-Hub-Revision: Latest Hub revision number
    - X-XIRS-Station-Id: This satellite's station ID
    """
    hub_revision = 0

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/{registration_id}"
            )

            # Extract hub revision from response headers if available
            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                reg = response.json()
                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "patient": {
                        "registration_id": reg.get("id") or reg.get("registration_id"),
                        "patient_id": reg.get("patient_id"),
                        "name": reg.get("patient_name") or reg.get("name"),
                        "dob": reg.get("dob"),
                        "sex": reg.get("sex"),
                        "allergies": reg.get("allergies", []),
                        "weight_kg": reg.get("weight_kg"),
                        "blood_type": reg.get("blood_type"),
                        "triage_category": reg.get("triage_category"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "medical_history": reg.get("medical_history"),
                        "current_medications": reg.get("current_medications"),
                        "status": reg.get("status")
                    },
                    "protocol_version": XIRS_PROTOCOL_VERSION
                }, hub_revision)
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Registration not found in CIRS")
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"CIRS Hub error: {response.status_code}"
                )

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="CIRS Hub timeout")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="CIRS Hub not reachable")
    except Exception as e:
        logger.error(f"CIRS patient fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hub/status")
async def get_hub_status():
    """
    Returns Hub-Satellite sync status for this station.

    Response Headers:
    - X-XIRS-Protocol-Version: Contract version (1.0)
    - X-XIRS-Station-Id: This satellite's station ID
    """
    # Check CIRS Hub connectivity
    hub_online = False
    hub_revision = 0
    hub_error = None

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.get(f"{CIRS_HUB_URL}/api/health")
            if response.status_code == 200:
                hub_online = True
                hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))
    except Exception as e:
        hub_error = str(e)

    return make_xirs_response({
        "station_id": STATION_ID,
        "protocol_version": XIRS_PROTOCOL_VERSION,
        "hub_url": CIRS_HUB_URL,
        "hub_online": hub_online,
        "hub_revision": hub_revision,
        "hub_error": hub_error,
        "last_sync": None,  # TODO: Track last sync time
        "pending_ops": 0,   # TODO: Count pending operations
    }, hub_revision)


# =============================================================================
# v1.6.1: PIO API Routes
# =============================================================================

@router.post("/cases/{case_id}/pio/problems")
async def create_problem(case_id: str, request: CreateProblemRequest, actor_id: str = Query(...)):
    """建立 PIO Problem (問題識別)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists
    cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    # Calculate clinical_time
    recorded_at = datetime.now()
    if request.detected_clinical_time:
        clinical_time = request.detected_clinical_time
    elif request.clinical_time_offset_seconds is not None:
        from datetime import timedelta
        clinical_time = recorded_at + timedelta(seconds=request.clinical_time_offset_seconds)
    else:
        clinical_time = recorded_at

    # Verify trigger_event_id exists if provided
    if request.trigger_event_id:
        cursor.execute("SELECT id FROM anesthesia_events WHERE id = ?", (request.trigger_event_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Trigger event not found: {request.trigger_event_id}")

    problem_id = generate_problem_id(case_id)

    try:
        cursor.execute("""
            INSERT INTO pio_problems (
                problem_id, case_id, problem_type, severity,
                detected_clinical_time, trigger_event_id, note, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            problem_id,
            case_id,
            request.problem_type.value,
            request.severity,
            clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time,
            request.trigger_event_id,
            request.note,
            actor_id
        ))
        conn.commit()

        return {
            "success": True,
            "problem_id": problem_id,
            "problem_type": request.problem_type.value,
            "detected_clinical_time": clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/pio/problems")
async def list_problems(
    case_id: str,
    status: Optional[str] = None,
    include_details: bool = Query(default=True)
):
    """列出 case 的所有 PIO Problems"""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM pio_problems WHERE case_id = ?"
    params = [case_id]

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY detected_clinical_time DESC"

    cursor.execute(query, params)
    problems = [dict(row) for row in cursor.fetchall()]

    if include_details:
        for problem in problems:
            # Get interventions
            cursor.execute("""
                SELECT * FROM pio_interventions
                WHERE problem_id = ?
                ORDER BY performed_clinical_time ASC
            """, (problem['problem_id'],))
            problem['interventions'] = [dict(row) for row in cursor.fetchall()]

            # Get outcomes
            cursor.execute("""
                SELECT * FROM pio_outcomes
                WHERE problem_id = ?
                ORDER BY observed_clinical_time ASC
            """, (problem['problem_id'],))
            outcomes = []
            for row in cursor.fetchall():
                outcome = dict(row)
                outcome['evidence_event_ids'] = json.loads(outcome['evidence_event_ids']) if outcome['evidence_event_ids'] else []
                outcomes.append(outcome)
            problem['outcomes'] = outcomes

    return {"problems": problems, "count": len(problems)}


@router.get("/cases/{case_id}/pio/problems/{problem_id}")
async def get_problem(case_id: str, problem_id: str):
    """取得單一 PIO Problem 完整資訊"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM pio_problems WHERE problem_id = ? AND case_id = ?
    """, (problem_id, case_id))
    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Problem not found: {problem_id}")

    problem = dict(row)

    # Get interventions with linked events
    cursor.execute("""
        SELECT i.*, e.payload as event_payload, e.event_type as event_type
        FROM pio_interventions i
        LEFT JOIN anesthesia_events e ON i.event_ref_id = e.id
        WHERE i.problem_id = ?
        ORDER BY i.performed_clinical_time ASC
    """, (problem_id,))
    interventions = []
    for row in cursor.fetchall():
        intervention = dict(row)
        if intervention.get('event_payload'):
            intervention['event_payload'] = json.loads(intervention['event_payload'])
        interventions.append(intervention)
    problem['interventions'] = interventions

    # Get outcomes
    cursor.execute("""
        SELECT * FROM pio_outcomes WHERE problem_id = ?
        ORDER BY observed_clinical_time ASC
    """, (problem_id,))
    outcomes = []
    for row in cursor.fetchall():
        outcome = dict(row)
        outcome['evidence_event_ids'] = json.loads(outcome['evidence_event_ids']) if outcome['evidence_event_ids'] else []
        outcomes.append(outcome)
    problem['outcomes'] = outcomes

    # Get trigger event details
    if problem.get('trigger_event_id'):
        cursor.execute("SELECT * FROM anesthesia_events WHERE id = ?", (problem['trigger_event_id'],))
        trigger = cursor.fetchone()
        if trigger:
            trigger_dict = dict(trigger)
            trigger_dict['payload'] = json.loads(trigger_dict['payload']) if trigger_dict['payload'] else {}
            problem['trigger_event'] = trigger_dict

    return problem


@router.patch("/cases/{case_id}/pio/problems/{problem_id}/status")
async def update_problem_status(
    case_id: str,
    problem_id: str,
    request: UpdateProblemStatusRequest,
    actor_id: str = Query(...)
):
    """更新 Problem 狀態"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify problem exists
    cursor.execute("""
        SELECT status FROM pio_problems WHERE problem_id = ? AND case_id = ?
    """, (problem_id, case_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail=f"Problem not found: {problem_id}")

    try:
        update_fields = ["status = ?"]
        params = [request.status.value]

        if request.resolved_clinical_time:
            update_fields.append("resolved_clinical_time = ?")
            params.append(request.resolved_clinical_time.isoformat())
        elif request.status == ProblemStatus.RESOLVED:
            # Auto-set resolved time if not provided
            update_fields.append("resolved_clinical_time = ?")
            params.append(datetime.now().isoformat())

        if request.note:
            update_fields.append("note = COALESCE(note, '') || ? || ?")
            params.extend(['\n---\n', request.note])

        params.append(problem_id)

        cursor.execute(f"""
            UPDATE pio_problems SET {', '.join(update_fields)}
            WHERE problem_id = ?
        """, params)
        conn.commit()

        return {"success": True, "problem_id": problem_id, "new_status": request.status.value}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/pio/interventions")
async def create_intervention(case_id: str, request: CreateInterventionRequest, actor_id: str = Query(...)):
    """建立 PIO Intervention (處置) - 必須連結底層事件

    **硬規則**: event_ref_id 必填，拒絕沒有底層事件的處置記錄
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify problem exists
    cursor.execute("""
        SELECT case_id FROM pio_problems WHERE problem_id = ?
    """, (request.problem_id,))
    problem = cursor.fetchone()
    if not problem:
        raise HTTPException(status_code=404, detail=f"Problem not found: {request.problem_id}")

    if problem['case_id'] != case_id:
        raise HTTPException(status_code=400, detail="Problem does not belong to this case")

    # v1.6.1 硬規則: 驗證 event_ref_id 存在
    cursor.execute("""
        SELECT id, clinical_time, event_type FROM anesthesia_events WHERE id = ?
    """, (request.event_ref_id,))
    event = cursor.fetchone()
    if not event:
        raise HTTPException(
            status_code=400,
            detail=f"Event not found: {request.event_ref_id}. Intervention MUST reference an existing event."
        )

    # Calculate clinical_time (default from linked event)
    if request.performed_clinical_time:
        clinical_time = request.performed_clinical_time
    elif request.clinical_time_offset_seconds is not None:
        from datetime import timedelta
        clinical_time = datetime.now() + timedelta(seconds=request.clinical_time_offset_seconds)
    else:
        clinical_time = event['clinical_time']

    intervention_id = generate_intervention_id()

    try:
        cursor.execute("""
            INSERT INTO pio_interventions (
                intervention_id, problem_id, case_id,
                event_ref_id, action_type, performed_clinical_time,
                immediate_response, performed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            intervention_id,
            request.problem_id,
            case_id,
            request.event_ref_id,
            request.action_type or event['event_type'],
            clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time,
            request.immediate_response,
            actor_id
        ))

        # Update problem status to WATCHING if still OPEN
        cursor.execute("""
            UPDATE pio_problems SET status = 'WATCHING'
            WHERE problem_id = ? AND status = 'OPEN'
        """, (request.problem_id,))

        conn.commit()

        return {
            "success": True,
            "intervention_id": intervention_id,
            "problem_id": request.problem_id,
            "event_ref_id": request.event_ref_id
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/pio/outcomes")
async def create_outcome(case_id: str, request: CreateOutcomeRequest, actor_id: str = Query(...)):
    """建立 PIO Outcome (結果) - 必須有證據事件"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify problem exists
    cursor.execute("""
        SELECT case_id FROM pio_problems WHERE problem_id = ?
    """, (request.problem_id,))
    problem = cursor.fetchone()
    if not problem:
        raise HTTPException(status_code=404, detail=f"Problem not found: {request.problem_id}")

    if problem['case_id'] != case_id:
        raise HTTPException(status_code=400, detail="Problem does not belong to this case")

    # Verify evidence events exist
    if not request.evidence_event_ids:
        raise HTTPException(status_code=400, detail="At least one evidence event is required")

    for event_id in request.evidence_event_ids:
        cursor.execute("SELECT id FROM anesthesia_events WHERE id = ?", (event_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Evidence event not found: {event_id}")

    # Calculate clinical_time
    recorded_at = datetime.now()
    if request.observed_clinical_time:
        clinical_time = request.observed_clinical_time
    elif request.clinical_time_offset_seconds is not None:
        from datetime import timedelta
        clinical_time = recorded_at + timedelta(seconds=request.clinical_time_offset_seconds)
    else:
        clinical_time = recorded_at

    outcome_id = generate_outcome_id()

    try:
        cursor.execute("""
            INSERT INTO pio_outcomes (
                outcome_id, problem_id, outcome_type,
                evidence_event_ids, observed_clinical_time,
                new_problem_status, note, recorded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            outcome_id,
            request.problem_id,
            request.outcome_type.value,
            json.dumps(request.evidence_event_ids),
            clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time,
            request.new_problem_status.value if request.new_problem_status else None,
            request.note,
            actor_id
        ))

        # Update problem status if specified
        if request.new_problem_status:
            update_fields = ["status = ?"]
            params = [request.new_problem_status.value]

            if request.new_problem_status == ProblemStatus.RESOLVED:
                update_fields.append("resolved_clinical_time = ?")
                params.append(clinical_time.isoformat() if isinstance(clinical_time, datetime) else clinical_time)

            params.append(request.problem_id)
            cursor.execute(f"""
                UPDATE pio_problems SET {', '.join(update_fields)}
                WHERE problem_id = ?
            """, params)

        conn.commit()

        return {
            "success": True,
            "outcome_id": outcome_id,
            "problem_id": request.problem_id,
            "outcome_type": request.outcome_type.value,
            "new_problem_status": request.new_problem_status.value if request.new_problem_status else None
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/pio/timeline")
async def get_pio_timeline(case_id: str):
    """取得 PIO 因果鏈時間軸視圖

    返回所有 problems 及其關聯的 interventions/outcomes，
    並包含底層事件資料以便 UI 渲染完整時間軸。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all problems
    cursor.execute("""
        SELECT * FROM pio_problems WHERE case_id = ?
        ORDER BY detected_clinical_time ASC
    """, (case_id,))
    problems = []

    for row in cursor.fetchall():
        problem = dict(row)

        # Get trigger event
        if problem.get('trigger_event_id'):
            cursor.execute("SELECT * FROM anesthesia_events WHERE id = ?", (problem['trigger_event_id'],))
            trigger = cursor.fetchone()
            if trigger:
                t = dict(trigger)
                t['payload'] = json.loads(t['payload']) if t['payload'] else {}
                problem['trigger_event'] = t

        # Get interventions with linked events
        cursor.execute("""
            SELECT i.*, e.payload as event_payload
            FROM pio_interventions i
            LEFT JOIN anesthesia_events e ON i.event_ref_id = e.id
            WHERE i.problem_id = ?
            ORDER BY i.performed_clinical_time ASC
        """, (problem['problem_id'],))
        interventions = []
        for irow in cursor.fetchall():
            intervention = dict(irow)
            if intervention.get('event_payload'):
                intervention['event_payload'] = json.loads(intervention['event_payload'])
            interventions.append(intervention)
        problem['interventions'] = interventions

        # Get outcomes with evidence events
        cursor.execute("""
            SELECT * FROM pio_outcomes WHERE problem_id = ?
            ORDER BY observed_clinical_time ASC
        """, (problem['problem_id'],))
        outcomes = []
        for orow in cursor.fetchall():
            outcome = dict(orow)
            evidence_ids = json.loads(outcome['evidence_event_ids']) if outcome['evidence_event_ids'] else []
            outcome['evidence_event_ids'] = evidence_ids

            # Fetch evidence events
            if evidence_ids:
                placeholders = ','.join(['?'] * len(evidence_ids))
                cursor.execute(f"""
                    SELECT * FROM anesthesia_events WHERE id IN ({placeholders})
                """, evidence_ids)
                evidence_events = []
                for erow in cursor.fetchall():
                    e = dict(erow)
                    e['payload'] = json.loads(e['payload']) if e['payload'] else {}
                    evidence_events.append(e)
                outcome['evidence_events'] = evidence_events

            outcomes.append(outcome)
        problem['outcomes'] = outcomes

        problems.append(problem)

    return {
        "case_id": case_id,
        "problems": problems,
        "count": len(problems)
    }


# =============================================================================
# v1.6.1: Quick Scenario Bundle API
# =============================================================================

@router.get("/pio/templates")
async def get_scenario_templates():
    """取得 Quick Scenario 建議模板

    UI 可用此資料渲染情境快速卡片的處置選項
    """
    return {
        "templates": QUICK_SCENARIO_TEMPLATES,
        "available_scenarios": list(QUICK_SCENARIO_TEMPLATES.keys())
    }


@router.post("/cases/{case_id}/pio/quick")
async def create_quick_scenario(
    case_id: str,
    request: QuickScenarioRequest,
    actor_id: str = Query(...)
):
    """Quick Scenario Bundle - 一鍵記錄 Problem + Events + Interventions

    **流程**:
    1. 建立 PIO Problem
    2. 為每個選擇的處置建立 anesthesia_event
    3. 為每個事件建立 PIO Intervention 連結

    **範例請求**:
    ```json
    {
      "scenario": "HYPOTENSION",
      "severity": 2,
      "detected_value": {"map": 55, "sbp": 75, "dbp": 45},
      "trigger_event_id": "evt-vital-123",
      "interventions": [
        {"intervention_type": "VASOACTIVE_BOLUS", "payload": {"drug_name": "Ephedrine", "dose": 5, "unit": "mg", "route": "IV"}}
      ],
      "clinical_time_offset_seconds": -120
    }
    ```
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify case exists and is not closed
    cursor.execute("SELECT status FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
    if case['status'] == 'CLOSED':
        raise HTTPException(status_code=400, detail="Cannot add to closed case")

    # Calculate clinical_time
    recorded_at = datetime.now()
    if request.clinical_time_offset_seconds is not None:
        from datetime import timedelta
        clinical_time = recorded_at + timedelta(seconds=request.clinical_time_offset_seconds)
    else:
        clinical_time = recorded_at

    # Verify trigger_event_id if provided
    if request.trigger_event_id:
        cursor.execute("SELECT id FROM anesthesia_events WHERE id = ?", (request.trigger_event_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Trigger event not found: {request.trigger_event_id}")

    # Validate interventions
    if not request.interventions:
        raise HTTPException(status_code=400, detail="At least one intervention is required")

    try:
        # Step 1: Create PIO Problem
        problem_id = generate_problem_id(case_id)
        cursor.execute("""
            INSERT INTO pio_problems (
                problem_id, case_id, problem_type, severity,
                detected_clinical_time, trigger_event_id, note, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            problem_id,
            case_id,
            request.scenario.value,
            request.severity,
            clinical_time.isoformat(),
            request.trigger_event_id,
            request.note,
            actor_id
        ))

        created_events = []
        created_interventions = []

        # Step 2 & 3: For each intervention, create Event + Intervention link
        for item in request.interventions:
            # Create anesthesia_event
            event_id = generate_event_id()
            event_type = item.intervention_type

            # Enhance payload with problem link
            enhanced_payload = dict(item.payload)
            enhanced_payload['linked_problem_id'] = problem_id
            enhanced_payload['indication'] = request.scenario.value
            if request.detected_value:
                enhanced_payload['trigger_values'] = request.detected_value

            cursor.execute("""
                INSERT INTO anesthesia_events (
                    id, case_id, event_type, clinical_time, payload, actor_id
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                case_id,
                event_type,
                clinical_time.isoformat(),
                json.dumps(enhanced_payload),
                actor_id
            ))
            created_events.append({
                "event_id": event_id,
                "event_type": event_type,
                "payload": enhanced_payload
            })

            # Create PIO Intervention
            intervention_id = generate_intervention_id()
            cursor.execute("""
                INSERT INTO pio_interventions (
                    intervention_id, problem_id, case_id,
                    event_ref_id, action_type, performed_clinical_time,
                    performed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                intervention_id,
                problem_id,
                case_id,
                event_id,
                event_type,
                clinical_time.isoformat(),
                actor_id
            ))
            created_interventions.append({
                "intervention_id": intervention_id,
                "event_ref_id": event_id,
                "action_type": event_type
            })

        # Update problem status to WATCHING
        cursor.execute("""
            UPDATE pio_problems SET status = 'WATCHING' WHERE problem_id = ?
        """, (problem_id,))

        conn.commit()

        return {
            "success": True,
            "problem_id": problem_id,
            "scenario": request.scenario.value,
            "clinical_time": clinical_time.isoformat(),
            "events_created": len(created_events),
            "interventions_created": len(created_interventions),
            "details": {
                "problem": {
                    "problem_id": problem_id,
                    "problem_type": request.scenario.value,
                    "severity": request.severity,
                    "status": "WATCHING"
                },
                "events": created_events,
                "interventions": created_interventions
            }
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/pio/quick-outcome")
async def create_quick_outcome(
    case_id: str,
    problem_id: str = Query(...),
    outcome_type: OutcomeType = Query(...),
    close_problem: bool = Query(default=False),
    actor_id: str = Query(...)
):
    """快速記錄 Outcome (使用最近的 VITAL 事件作為證據)

    **用途**: 護士觀察到改善/惡化後，快速記錄結果
    - 自動抓取最近 5 分鐘內的 VITAL_SIGN 事件作為證據
    - 可選擇是否同時關閉 Problem
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify problem exists
    cursor.execute("""
        SELECT case_id FROM pio_problems WHERE problem_id = ? AND case_id = ?
    """, (problem_id, case_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail=f"Problem not found: {problem_id}")

    # Find recent VITAL_SIGN events (last 5 minutes)
    cursor.execute("""
        SELECT id FROM anesthesia_events
        WHERE case_id = ? AND event_type = 'VITAL_SIGN'
        AND clinical_time > datetime('now', '-5 minutes')
        ORDER BY clinical_time DESC
        LIMIT 3
    """, (case_id,))
    recent_vitals = [row['id'] for row in cursor.fetchall()]

    if not recent_vitals:
        # Fallback: get the most recent VITAL
        cursor.execute("""
            SELECT id FROM anesthesia_events
            WHERE case_id = ? AND event_type = 'VITAL_SIGN'
            ORDER BY clinical_time DESC
            LIMIT 1
        """, (case_id,))
        row = cursor.fetchone()
        if row:
            recent_vitals = [row['id']]
        else:
            raise HTTPException(
                status_code=400,
                detail="No VITAL_SIGN events found to use as evidence"
            )

    outcome_id = generate_outcome_id()
    clinical_time = datetime.now()
    new_status = ProblemStatus.RESOLVED if close_problem else None

    try:
        cursor.execute("""
            INSERT INTO pio_outcomes (
                outcome_id, problem_id, outcome_type,
                evidence_event_ids, observed_clinical_time,
                new_problem_status, recorded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            outcome_id,
            problem_id,
            outcome_type.value,
            json.dumps(recent_vitals),
            clinical_time.isoformat(),
            new_status.value if new_status else None,
            actor_id
        ))

        if close_problem:
            cursor.execute("""
                UPDATE pio_problems
                SET status = 'RESOLVED', resolved_clinical_time = ?
                WHERE problem_id = ?
            """, (clinical_time.isoformat(), problem_id))

        conn.commit()

        return {
            "success": True,
            "outcome_id": outcome_id,
            "problem_id": problem_id,
            "outcome_type": outcome_type.value,
            "evidence_event_ids": recent_vitals,
            "problem_closed": close_problem
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# v1.6.1 Phase 4: Enhanced Timeline + Inventory Linkage
# =============================================================================

@router.get("/cases/{case_id}/enhanced-timeline")
async def get_enhanced_timeline(
    case_id: str,
    include_pio_groups: bool = Query(default=True),
    filter_type: Optional[str] = Query(default=None, description="Filter by event type")
):
    """增強版時間軸 - 支援 PIO 分組和 collapsible 視圖

    返回格式:
    - 獨立事件 (非 PIO 相關) 按時間排序
    - PIO 相關事件分組為 collapsible 區塊
    - 每個 PIO 區塊包含: problem → interventions → outcomes

    **UI 渲染建議**:
    - PIO 區塊預設收合，只顯示摘要 (狀態、處置數、持續時間)
    - 展開後顯示完整事件序列
    - 補登事件顯示 [補登 HH:MM] 標記
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all events
    query = """
        SELECT * FROM anesthesia_events
        WHERE case_id = ? AND is_correction = 0
    """
    params = [case_id]

    if filter_type:
        query += " AND event_type = ?"
        params.append(filter_type)

    query += " ORDER BY clinical_time ASC"
    cursor.execute(query, params)

    all_events = []
    for row in cursor.fetchall():
        event = dict(row)
        event['payload'] = json.loads(event['payload']) if event['payload'] else {}
        all_events.append(event)

    if not include_pio_groups:
        return {"timeline": all_events, "count": len(all_events)}

    # Get PIO problems
    cursor.execute("""
        SELECT * FROM pio_problems WHERE case_id = ?
        ORDER BY detected_clinical_time ASC
    """, (case_id,))
    problems = {row['problem_id']: dict(row) for row in cursor.fetchall()}

    # Get interventions grouped by problem
    cursor.execute("""
        SELECT * FROM pio_interventions WHERE case_id = ?
    """, (case_id,))
    interventions_by_problem = {}
    event_to_problem = {}  # Map event_id to problem_id
    for row in cursor.fetchall():
        pid = row['problem_id']
        if pid not in interventions_by_problem:
            interventions_by_problem[pid] = []
        interventions_by_problem[pid].append(dict(row))
        event_to_problem[row['event_ref_id']] = pid

    # Get outcomes grouped by problem
    cursor.execute("""
        SELECT * FROM pio_outcomes WHERE problem_id IN (
            SELECT problem_id FROM pio_problems WHERE case_id = ?
        )
    """, (case_id,))
    outcomes_by_problem = {}
    for row in cursor.fetchall():
        pid = row['problem_id']
        if pid not in outcomes_by_problem:
            outcomes_by_problem[pid] = []
        outcome = dict(row)
        outcome['evidence_event_ids'] = json.loads(outcome['evidence_event_ids']) if outcome['evidence_event_ids'] else []
        outcomes_by_problem[pid].append(outcome)

    # Build enhanced timeline
    timeline_items = []
    pio_event_ids = set(event_to_problem.keys())

    # Collect PIO trigger events
    for pid, problem in problems.items():
        if problem.get('trigger_event_id'):
            pio_event_ids.add(problem['trigger_event_id'])

    # Build PIO groups
    pio_groups = {}
    for pid, problem in problems.items():
        interventions = interventions_by_problem.get(pid, [])
        outcomes = outcomes_by_problem.get(pid, [])

        # Calculate duration
        start_time = problem['detected_clinical_time']
        end_time = problem.get('resolved_clinical_time') or datetime.now().isoformat()

        # Get linked events
        linked_events = []
        for event in all_events:
            if event['id'] in [i['event_ref_id'] for i in interventions]:
                linked_events.append(event)
            elif event['id'] == problem.get('trigger_event_id'):
                linked_events.append(event)

        pio_groups[pid] = {
            "type": "pio_group",
            "problem_id": pid,
            "problem_type": problem['problem_type'],
            "severity": problem['severity'],
            "status": problem['status'],
            "detected_time": start_time,
            "resolved_time": problem.get('resolved_clinical_time'),
            "intervention_count": len(interventions),
            "outcome_count": len(outcomes),
            "trigger_event_id": problem.get('trigger_event_id'),
            "summary": f"{problem['problem_type']} - {len(interventions)} interventions",
            "details": {
                "problem": problem,
                "interventions": interventions,
                "outcomes": outcomes,
                "linked_events": linked_events
            }
        }

    # Build timeline: mix standalone events and PIO groups
    added_pio_groups = set()
    for event in all_events:
        # Check if event is part of a PIO group
        problem_id = event_to_problem.get(event['id'])
        if not problem_id:
            # Check if it's a trigger event
            for pid, problem in problems.items():
                if problem.get('trigger_event_id') == event['id']:
                    problem_id = pid
                    break

        if problem_id and problem_id not in added_pio_groups:
            # Insert PIO group at the position of first related event
            timeline_items.append(pio_groups[problem_id])
            added_pio_groups.add(problem_id)
        elif event['id'] not in pio_event_ids:
            # Standalone event
            event_item = {
                "type": "event",
                "event_id": event['id'],
                "event_type": event['event_type'],
                "clinical_time": event['clinical_time'],
                "payload": event['payload'],
                "actor_id": event['actor_id'],
                "is_late_entry": event['payload'].get('_late_entry') is not None,
                "late_entry_info": event['payload'].get('_late_entry')
            }
            timeline_items.append(event_item)

    # Sort by time
    def get_time(item):
        if item['type'] == 'pio_group':
            return item['detected_time']
        return item['clinical_time']

    timeline_items.sort(key=get_time)

    return {
        "case_id": case_id,
        "timeline": timeline_items,
        "total_events": len(all_events),
        "pio_groups": len(pio_groups),
        "standalone_events": len([i for i in timeline_items if i['type'] == 'event'])
    }


@router.get("/cases/{case_id}/open-problems")
async def get_open_problems(case_id: str):
    """取得目前 OPEN 或 WATCHING 的問題 (供 UI 連結新事件用)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT problem_id, problem_type, severity, status, detected_clinical_time
        FROM pio_problems
        WHERE case_id = ? AND status IN ('OPEN', 'WATCHING')
        ORDER BY detected_clinical_time DESC
    """, (case_id,))

    problems = [dict(row) for row in cursor.fetchall()]
    return {"problems": problems, "count": len(problems)}


# =============================================================================
# v1.6.1 Phase 4: Inventory Linkage
# =============================================================================

async def trigger_inventory_deduction(
    event_type: str,
    payload: Dict[str, Any],
    case_id: str,
    actor_id: str
):
    """觸發庫存扣減 (非同步，失敗不影響事件記錄)

    支援的事件類型:
    - BLOOD_PRODUCT: 扣減血品庫存
    - VASOACTIVE_BOLUS: 扣減藥品庫存 (非管制)
    - FLUID_BOLUS: 扣減輸液庫存 (可選)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if event_type == "BLOOD_PRODUCT" and payload.get('inventory_deduct'):
            # Blood product deduction
            product_type = payload.get('product_type')
            unit_id = payload.get('unit_id')
            unit_count = payload.get('unit_count', 1)

            # Log the deduction request (actual inventory logic depends on blood bank module)
            logger.info(f"[Inventory] Blood product deduction: {product_type} x{unit_count}, unit_id={unit_id}, case={case_id}")

            # Try to update blood inventory if table exists
            try:
                cursor.execute("""
                    UPDATE inventory_items
                    SET current_quantity = current_quantity - ?
                    WHERE category = 'blood' AND item_code = ?
                """, (unit_count, product_type))
                conn.commit()
            except Exception as e:
                logger.warning(f"[Inventory] Blood deduction failed (table may not exist): {e}")

        elif event_type == "VASOACTIVE_BOLUS":
            # Medication deduction (non-controlled)
            drug_name = payload.get('drug_name')
            dose = payload.get('dose')
            unit = payload.get('unit')

            logger.info(f"[Inventory] Vasoactive deduction: {drug_name} {dose}{unit}, case={case_id}")

            # Try to update medication inventory
            try:
                cursor.execute("""
                    UPDATE inventory_items
                    SET current_quantity = current_quantity - ?
                    WHERE category = 'medication' AND name LIKE ?
                """, (1, f"%{drug_name}%"))
                conn.commit()
            except Exception as e:
                logger.warning(f"[Inventory] Medication deduction failed: {e}")

        elif event_type == "FLUID_BOLUS" and payload.get('inventory_deduct'):
            # Fluid deduction (optional)
            fluid_type = payload.get('fluid_type')
            volume = payload.get('volume')

            logger.info(f"[Inventory] Fluid deduction: {fluid_type} {volume}ml, case={case_id}")

    except Exception as e:
        logger.error(f"[Inventory] Deduction error: {e}")
        # Don't raise - inventory failure shouldn't block event creation


@router.post("/cases/{case_id}/events-with-inventory")
async def add_event_with_inventory(
    case_id: str,
    request: AddEventRequest,
    actor_id: str = Query(...),
    trigger_inventory: bool = Query(default=True)
):
    """新增事件並觸發庫存連動

    當 trigger_inventory=true 且事件類型支援庫存連動時:
    - BLOOD_PRODUCT + inventory_deduct=true → 扣減血品
    - VASOACTIVE_BOLUS → 扣減藥品
    - FLUID_BOLUS + inventory_deduct=true → 扣減輸液
    """
    # First create the event using existing endpoint
    result = await add_event(case_id, request, actor_id)

    # Then trigger inventory deduction if applicable
    if trigger_inventory and result.get('success'):
        await trigger_inventory_deduction(
            request.event_type.value,
            request.payload,
            case_id,
            actor_id
        )
        result['inventory_triggered'] = True

    return result


@router.get("/cases/{case_id}/summary")
async def get_case_summary(case_id: str):
    """取得案例摘要 (用於儀表板或報告)

    包含:
    - 基本案例資訊
    - 事件統計
    - PIO 統計
    - 時間軸摘要
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Case info
    cursor.execute("SELECT * FROM anesthesia_cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    case_info = dict(case)

    # Event statistics
    cursor.execute("""
        SELECT event_type, COUNT(*) as count
        FROM anesthesia_events
        WHERE case_id = ? AND is_correction = 0
        GROUP BY event_type
    """, (case_id,))
    event_stats = {row['event_type']: row['count'] for row in cursor.fetchall()}

    # Total events
    total_events = sum(event_stats.values())

    # PIO statistics
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM pio_problems
        WHERE case_id = ?
        GROUP BY status
    """, (case_id,))
    problem_stats = {row['status']: row['count'] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT COUNT(*) as count FROM pio_interventions WHERE case_id = ?
    """, (case_id,))
    intervention_count = cursor.fetchone()['count']

    # Late entries
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM anesthesia_events
        WHERE case_id = ? AND payload LIKE '%_late_entry%'
    """, (case_id,))
    late_entry_count = cursor.fetchone()['count']

    # Duration calculation
    duration_minutes = None
    if case_info.get('anesthesia_start_at') and case_info.get('anesthesia_end_at'):
        try:
            start = datetime.fromisoformat(case_info['anesthesia_start_at'])
            end = datetime.fromisoformat(case_info['anesthesia_end_at'])
            duration_minutes = int((end - start).total_seconds() / 60)
        except:
            pass

    return {
        "case_id": case_id,
        "status": case_info['status'],
        "patient_name": case_info.get('patient_name'),
        "context_mode": case_info.get('context_mode'),
        "planned_technique": case_info.get('planned_technique'),
        "duration_minutes": duration_minutes,
        "statistics": {
            "total_events": total_events,
            "events_by_type": event_stats,
            "problems": problem_stats,
            "total_problems": sum(problem_stats.values()),
            "total_interventions": intervention_count,
            "late_entries": late_entry_count
        },
        "timestamps": {
            "created_at": case_info.get('created_at'),
            "preop_completed_at": case_info.get('preop_completed_at'),
            "anesthesia_start_at": case_info.get('anesthesia_start_at'),
            "surgery_start_at": case_info.get('surgery_start_at'),
            "surgery_end_at": case_info.get('surgery_end_at'),
            "anesthesia_end_at": case_info.get('anesthesia_end_at')
        }
    }
