"""
MIRS Anesthesia Module - Phase A
Event-Sourced, Offline-First Architecture

Version: 2.1.0
- Added: IV Line Management
- Added: Monitor Management (Foley, etc.)
- Added: I/O Balance Calculation
- Added: PDF Generation (M0073 with auto-pagination)
"""

import json
import os
import uuid
import base64
import io
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import logging
logger = logging.getLogger(__name__)

# PDF Generation imports (lazy load to handle missing deps)
# Jinja2 for HTML preview (works on Vercel)
try:
    from jinja2 import Environment, FileSystemLoader
    JINJA2_ENABLED = True
except ImportError:
    JINJA2_ENABLED = False
    logger.warning("HTML preview disabled: missing jinja2")

# WeasyPrint + Matplotlib for PDF generation (requires system deps, NOT on Vercel)
try:
    from weasyprint import HTML as WeasyHTML
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    PDF_ENABLED = True
except ImportError:
    PDF_ENABLED = False
    logger.warning("PDF generation disabled: missing weasyprint or matplotlib")

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
            "diagnosis": "膽結石併膽囊炎",
            "operation": "腹腔鏡膽囊切除術",
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
            "diagnosis": "右側腹股溝疝氣",
            "operation": "腹腔鏡疝氣修補術",
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
            "diagnosis": "子宮肌瘤",
            "operation": "腹腔鏡子宮肌瘤切除術",
            "status": "CLOSED",
            "context_mode": "STANDARD",
            "planned_technique": "GA_LMA",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "started_at": (now - timedelta(hours=3)).isoformat(),
            "actor_id": "demo-user"
        },
        # v2.3: 複雜長手術案例 - 黃志明 (4.5hr, 完整 PDF 展示用)
        {
            "id": "ANES-DEMO-006",
            "patient_id": "P-DEMO-006",
            "patient_name": "黃志明",
            "patient_gender": "M",
            "patient_age": 68,
            "patient_weight": 72.5,
            "patient_height": 168,
            "blood_type": "A+",
            "asa_class": "III",
            "diagnosis": "升主動脈瘤 (6.2cm)",
            "operation": "乙乙型主動脈置換術 (Bentall procedure)",
            "or_room": "OR-3",
            "surgeon_name": "陳心外醫師",
            "preop_hb": 13.2,
            "preop_ht": 39.6,
            "preop_k": 4.1,
            "preop_na": 141,
            "estimated_blood_loss": 1500,
            "blood_prepared": "PRBC",
            "blood_prepared_units": "4U",
            "status": "CLOSED",
            "context_mode": "STANDARD",
            "planned_technique": "GA_ETT",
            "primary_anesthesiologist_name": "李麻醉醫師",
            "primary_nurse_name": "王護理師",
            "created_at": (now - timedelta(hours=6)).isoformat(),
            "started_at": (now - timedelta(hours=6)).isoformat(),
            "anesthesia_start_at": (now - timedelta(hours=6)).isoformat(),
            "surgery_start_at": (now - timedelta(hours=5, minutes=30)).isoformat(),
            "surgery_end_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
            "anesthesia_end_at": (now - timedelta(hours=1)).isoformat(),
            "actor_id": "demo-user"
        }
    ]


def get_demo_complex_events(case_id: str, case_start: datetime):
    """Generate comprehensive demo events for complex case ANES-DEMO-006"""
    events = []
    evt_idx = 1

    def add_event(event_type, minutes, payload):
        nonlocal evt_idx
        events.append({
            "id": f"{case_id}-evt-{evt_idx:03d}",
            "case_id": case_id,
            "event_type": event_type,
            "clinical_time": (case_start + timedelta(minutes=minutes)).isoformat(),
            "payload": payload
        })
        evt_idx += 1

    # Milestones
    add_event("MILESTONE", 0, {"type": "ANESTHESIA_START"})
    add_event("MILESTONE", 15, {"type": "INTUBATION"})
    add_event("MILESTONE", 30, {"type": "SURGERY_START"})
    add_event("MILESTONE", 270, {"type": "SURGERY_END"})
    add_event("MILESTONE", 285, {"type": "EXTUBATION"})
    add_event("MILESTONE", 300, {"type": "ANESTHESIA_END"})

    # Vital signs every 10 minutes for 5 hours (31 readings)
    vital_data = [
        (0, 145, 85, 78, 99, 0),
        (10, 125, 75, 72, 100, 35),
        (20, 118, 70, 68, 99, 36),
        (30, 110, 65, 70, 99, 35),
        (40, 105, 62, 72, 98, 37),
        (50, 98, 58, 75, 98, 38),
        (60, 92, 55, 78, 97, 38),
        (70, 88, 52, 82, 97, 39),
        (80, 95, 58, 78, 98, 37),
        (90, 102, 62, 75, 98, 36),
        (100, 108, 65, 72, 99, 35),
        (110, 105, 63, 74, 98, 36),
        (120, 98, 58, 78, 97, 38),
        (130, 92, 55, 82, 97, 39),
        (140, 88, 52, 85, 96, 40),
        (150, 95, 58, 80, 97, 38),
        (160, 102, 62, 76, 98, 37),
        (170, 108, 65, 74, 98, 36),
        (180, 112, 68, 72, 99, 35),
        (190, 115, 70, 70, 99, 35),
        (200, 118, 72, 68, 99, 34),
        (210, 120, 74, 70, 99, 35),
        (220, 118, 72, 72, 99, 35),
        (230, 115, 70, 74, 98, 36),
        (240, 118, 72, 72, 99, 35),
        (250, 122, 75, 70, 99, 34),
        (260, 125, 78, 72, 99, 35),
        (270, 128, 80, 75, 99, 36),
        (280, 132, 82, 78, 100, 0),
        (290, 138, 85, 82, 99, 0),
        (300, 142, 88, 85, 98, 0),
    ]
    for mins, sys, dia, hr, spo2, etco2 in vital_data:
        payload = {"bp_sys": sys, "bp_dia": dia, "hr": hr, "spo2": spo2}
        if etco2 > 0:
            payload["etco2"] = etco2
        add_event("VITAL_SIGN", mins, payload)

    # Medications
    meds = [
        (5, "Fentanyl", 100, "mcg", "IV"),
        (8, "Propofol", 150, "mg", "IV"),
        (12, "Rocuronium", 50, "mg", "IV"),
        (55, "Ephedrine", 5, "mg", "IV"),
        (65, "Ephedrine", 5, "mg", "IV"),
        (75, "Phenylephrine", 100, "mcg", "IV"),
        (90, "Fentanyl", 50, "mcg", "IV"),
        (120, "Rocuronium", 20, "mg", "IV"),
        (145, "Phenylephrine", 100, "mcg", "IV"),
        (180, "Fentanyl", 50, "mcg", "IV"),
        (200, "Rocuronium", 10, "mg", "IV"),
        (240, "Morphine", 5, "mg", "IV"),
        (275, "Neostigmine", 2.5, "mg", "IV"),
        (275, "Glycopyrrolate", 0.4, "mg", "IV"),
    ]
    for mins, drug, dose, unit, route in meds:
        add_event("MEDICATION_ADMIN", mins, {
            "drug_name": drug, "dose": dose, "unit": unit, "route": route
        })

    # IV Lines
    add_event("IV_LINE_INSERTED", 3, {
        "site": "RIGHT_HAND", "gauge": 18, "drip_rate_ml_hr": 100, "catheter_type": "PERIPHERAL"
    })
    add_event("IV_LINE_INSERTED", 20, {
        "site": "RIGHT_NECK", "gauge": 7, "drip_rate_ml_hr": 0, "catheter_type": "CVC"
    })
    add_event("IV_LINE_INSERTED", 25, {
        "site": "LEFT_WRIST", "gauge": 20, "drip_rate_ml_hr": 0, "catheter_type": "ARTERIAL"
    })

    # Fluids
    add_event("FLUID_IN", 0, {"fluid_type": "NS", "volume_ml": 500})
    add_event("FLUID_IN", 60, {"fluid_type": "LR", "volume_ml": 1000})
    add_event("FLUID_IN", 120, {"fluid_type": "LR", "volume_ml": 1000})
    add_event("FLUID_IN", 150, {"fluid_type": "VOLUVEN", "volume_ml": 500})
    add_event("FLUID_IN", 180, {"fluid_type": "ALBUMIN", "volume_ml": 250})

    # Blood products
    add_event("BLOOD_ADMIN", 140, {"product_type": "PRBC", "unit_id": "PRBC-001", "action": "START"})
    add_event("BLOOD_ADMIN", 170, {"product_type": "PRBC", "unit_id": "PRBC-001", "action": "COMPLETE"})
    add_event("BLOOD_ADMIN", 175, {"product_type": "PRBC", "unit_id": "PRBC-002", "action": "START"})
    add_event("BLOOD_ADMIN", 205, {"product_type": "PRBC", "unit_id": "PRBC-002", "action": "COMPLETE"})
    add_event("BLOOD_ADMIN", 210, {"product_type": "FFP", "unit_id": "FFP-001", "action": "START"})
    add_event("BLOOD_ADMIN", 240, {"product_type": "FFP", "unit_id": "FFP-001", "action": "COMPLETE"})

    # Urine output
    add_event("URINE_OUTPUT", 60, {"volume_ml": 150})
    add_event("URINE_OUTPUT", 120, {"volume_ml": 200})
    add_event("URINE_OUTPUT", 180, {"volume_ml": 180})
    add_event("URINE_OUTPUT", 240, {"volume_ml": 220})
    add_event("URINE_OUTPUT", 300, {"volume_ml": 150})

    # Blood loss
    add_event("BLOOD_LOSS", 90, {"volume_ml": 300})
    add_event("BLOOD_LOSS", 150, {"volume_ml": 500})
    add_event("BLOOD_LOSS", 210, {"volume_ml": 400})
    add_event("BLOOD_LOSS", 270, {"volume_ml": 200})

    # ABG Labs
    add_event("LAB_RESULT_POINT", 30, {
        "test_type": "ABG", "specimen": "arterial",
        "ph": 7.38, "po2": 185, "pco2": 38, "hco3": 22.5, "be": -1.5,
        "na": 140, "k": 3.8, "ca": 9.2, "glucose": 128, "hb": 11.2, "hct": 33.6
    })
    add_event("LAB_RESULT_POINT", 150, {
        "test_type": "ABG", "specimen": "arterial",
        "ph": 7.32, "po2": 165, "pco2": 42, "hco3": 21.0, "be": -3.5,
        "na": 138, "k": 4.2, "ca": 8.8, "glucose": 145, "hb": 9.8, "hct": 29.4
    })
    add_event("LAB_RESULT_POINT", 240, {
        "test_type": "ABG", "specimen": "arterial",
        "ph": 7.36, "po2": 175, "pco2": 40, "hco3": 22.0, "be": -2.0,
        "na": 139, "k": 4.0, "ca": 9.0, "glucose": 135, "hb": 10.5, "hct": 31.5
    })

    # Monitors
    add_event("MONITOR_START", 5, {"monitor_type": "FOLEY", "foley_size": 16})
    add_event("MONITOR_START", 22, {"monitor_type": "CVP"})
    add_event("MONITOR_START", 26, {"monitor_type": "ARTERIAL_LINE"})

    return events


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
    SPECIAL_TECHNIQUE = "SPECIAL_TECHNIQUE"        # v1.1: 特殊技術 (計費用)
    NOTE = "NOTE"

    # === 生命週期 ===
    STATUS_CHANGE = "STATUS_CHANGE"
    STAFF_CHANGE = "STAFF_CHANGE"

    # === 更正 ===
    CORRECTION = "CORRECTION"

    # === IV 管路管理 (v2.1) ===
    IV_LINE_INSERTED = "IV_LINE_INSERTED"      # 建立 IV 管路
    IV_LINE_REMOVED = "IV_LINE_REMOVED"        # 移除 IV 管路
    IV_RATE_CHANGED = "IV_RATE_CHANGED"        # 調整滴速
    IV_FLUID_GIVEN = "IV_FLUID_GIVEN"          # 經 IV 給予輸液

    # === 監測器管理 (v2.1) ===
    MONITOR_STARTED = "MONITOR_STARTED"        # 啟動監測器 (Foley, 保溫毯等)
    MONITOR_STOPPED = "MONITOR_STOPPED"        # 停止監測器
    URINE_OUTPUT = "URINE_OUTPUT"              # 尿量記錄 (需 Foley)

    # === Time Out (v2.1) ===
    TIMEOUT_COMPLETED = "TIMEOUT_COMPLETED"    # Time Out 核對完成


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
    # v2.1.1: Surgery info
    diagnosis: Optional[str] = None
    operation: Optional[str] = None
    context_mode: ContextMode = ContextMode.STANDARD
    planned_technique: Optional[AnesthesiaTechnique] = None
    # v1.1: ASA Classification for billing
    asa_classification: Optional[str] = "II"  # I, II, III, IV, V
    is_emergency: Optional[bool] = False  # +E flag
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
    # v2.1.1: Surgery info
    diagnosis: Optional[str] = None
    operation: Optional[str] = None
    context_mode: str
    planned_technique: Optional[str]
    # v1.1: ASA Classification for billing
    asa_classification: Optional[str] = None
    is_emergency: Optional[bool] = None
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
    initial_level_percent: Optional[int] = Field(None, ge=0, le=100, description="初始剩餘 %")
    flow_rate_lpm: Optional[float] = Field(2.0, gt=0, description="流速 L/min (預設 2.0)")


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


# =============================================================================
# v2.1: IV Line Models (IV 管路管理)
# =============================================================================

class InsertIVLineRequest(BaseModel):
    """插入 IV 管路"""
    site: str = Field(..., description="部位: 左手背, 右手背, 左前臂, 右前臂, 頸部CVC, etc.")
    gauge: Optional[str] = Field(None, description="規格: 24G, 22G, 20G, 18G, 16G, CVC")
    catheter_type: str = Field("PERIPHERAL", pattern="^(PERIPHERAL|CVC|PICC|ARTERIAL)$")
    initial_fluid: Optional[str] = Field(None, description="初始輸液: N/S, L/R, D5W")
    rate_ml_hr: Optional[int] = Field(None, ge=0, description="初始滴速 (ml/hr)")


class UpdateIVLineRequest(BaseModel):
    """更新 IV 管路"""
    rate_ml_hr: Optional[int] = Field(None, ge=0, description="新滴速")
    removed: Optional[bool] = Field(None, description="設為 true 移除管路")


class GiveIVFluidRequest(BaseModel):
    """經 IV 給予輸液"""
    fluid_type: str = Field(..., description="輸液類型: N/S, L/R, D5W, pRBC, FFP, Albumin")
    amount_ml: int = Field(..., gt=0, description="劑量 (ml)")
    is_bolus: bool = Field(False, description="是否為 bolus")


# =============================================================================
# v2.1: Monitor Models (監測器管理)
# =============================================================================

class StartMonitorRequest(BaseModel):
    """啟動監測器"""
    monitor_type: str = Field(..., description="類型: EKG, SPO2, NIBP, IBP, CVP, FOLEY, AIR_BLANKET, BIS, ETCO2, NMT")
    settings: Optional[dict] = Field(None, description="設定 (如 Foley size, 保溫毯溫度)")
    notes: Optional[str] = None


class RecordUrineOutputRequest(BaseModel):
    """記錄尿量"""
    amount_ml: int = Field(..., gt=0, description="尿量 (ml)")


# =============================================================================
# v2.1: Time Out Model
# =============================================================================

class TimeOutRequest(BaseModel):
    """Time Out 核對"""
    patient_id_confirmed: bool = Field(True, description="病患身分確認")
    procedure_confirmed: bool = Field(True, description="手術部位確認")
    consent_confirmed: bool = Field(True, description="同意書確認")
    allergies_confirmed: bool = Field(True, description="過敏史確認")
    equipment_ready: bool = Field(True, description="設備備妥")
    notes: Optional[str] = None


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

            -- v2.2: Patient demographics for PDF
            patient_gender TEXT,
            patient_age INTEGER,
            patient_weight REAL,
            patient_height REAL,
            blood_type TEXT,
            asa_class TEXT,

            -- v2.1.1: Surgery info
            diagnosis TEXT,
            operation TEXT,
            or_room TEXT,
            surgeon_name TEXT,

            -- v2.2: Preop labs
            preop_hb REAL,
            preop_ht REAL,
            preop_k REAL,
            preop_na REAL,

            -- v2.2: Blood preparation
            estimated_blood_loss INTEGER,
            blood_prepared TEXT,
            blood_prepared_units TEXT,

            context_mode TEXT NOT NULL DEFAULT 'STANDARD',

            primary_anesthesiologist_id TEXT,
            primary_anesthesiologist_name TEXT,
            primary_nurse_id TEXT,
            primary_nurse_name TEXT,

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

    # v1.1: Add ASA classification columns for billing integration
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN asa_classification TEXT DEFAULT 'II'")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN is_emergency INTEGER DEFAULT 0")
    except:
        pass

    # v2.1.1: Add diagnosis and operation columns
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN diagnosis TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE anesthesia_cases ADD COLUMN operation TEXT")
    except:
        pass

    # v2.2: Add preop data columns for comprehensive PDF
    preop_columns = [
        ("preop_hb", "REAL"),
        ("preop_ht", "REAL"),
        ("preop_k", "REAL"),
        ("preop_na", "REAL"),
        ("estimated_blood_loss", "INTEGER"),
        ("blood_prepared", "TEXT"),
        ("blood_prepared_units", "TEXT"),
    ]
    for col_name, col_type in preop_columns:
        try:
            cursor.execute(f"ALTER TABLE anesthesia_cases ADD COLUMN {col_name} {col_type}")
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

    # =========================================================================
    # v2.1: IV Lines Table (IV 管路管理)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_iv_lines (
            line_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            line_number INTEGER NOT NULL,

            -- 位置與規格
            site TEXT NOT NULL,
            gauge TEXT,
            catheter_type TEXT DEFAULT 'PERIPHERAL',

            -- 狀態
            inserted_at DATETIME NOT NULL,
            inserted_by TEXT NOT NULL,
            removed_at DATETIME,
            removed_by TEXT,

            -- 當前滴速
            current_rate_ml_hr INTEGER DEFAULT 0,
            current_fluid_type TEXT,

            -- 累計輸液量
            total_volume_ml INTEGER DEFAULT 0,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(catheter_type IN ('PERIPHERAL', 'CVC', 'PICC', 'ARTERIAL'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_iv_lines_case
        ON anesthesia_iv_lines(case_id, removed_at)
    """)

    # =========================================================================
    # v2.1: Monitors Table (監測器管理 - Foley, 保溫毯等)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_monitors (
            monitor_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,

            monitor_type TEXT NOT NULL,
            settings TEXT,

            started_at DATETIME NOT NULL,
            started_by TEXT NOT NULL,
            stopped_at DATETIME,
            stopped_by TEXT,

            notes TEXT,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            CHECK(monitor_type IN ('EKG', 'SPO2', 'NIBP', 'IBP', 'CVP', 'FOLEY', 'AIR_BLANKET', 'BIS', 'ETCO2', 'NMT', 'TEMP', 'OTHER'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_monitors_case
        ON anesthesia_monitors(case_id, stopped_at)
    """)

    # =========================================================================
    # v2.1: Urine Outputs Table (尿量記錄)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anesthesia_urine_outputs (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            monitor_id TEXT NOT NULL,

            amount_ml INTEGER NOT NULL,
            recorded_at DATETIME NOT NULL,
            recorded_by TEXT NOT NULL,

            cumulative_ml INTEGER DEFAULT 0,

            FOREIGN KEY (case_id) REFERENCES anesthesia_cases(id),
            FOREIGN KEY (monitor_id) REFERENCES anesthesia_monitors(monitor_id)
        )
    """)

    logger.info("✓ Anesthesia schema initialized (Phase A + B + C-PIO + D-IV/Foley)")


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
                diagnosis, operation,
                context_mode, planned_technique,
                asa_classification, is_emergency,
                primary_anesthesiologist_id, primary_nurse_id,
                cirs_registration_ref, patient_snapshot,
                created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            request.surgery_case_id,
            request.patient_id,
            request.patient_name,
            request.diagnosis,
            request.operation,
            request.context_mode.value,
            request.planned_technique.value if request.planned_technique else None,
            request.asa_classification,
            1 if request.is_emergency else 0,
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
            diagnosis=row['diagnosis'] if 'diagnosis' in row.keys() else None,
            operation=row['operation'] if 'operation' in row.keys() else None,
            context_mode=row['context_mode'],
            planned_technique=row['planned_technique'],
            asa_classification=row['asa_classification'] if 'asa_classification' in row.keys() else None,
            is_emergency=bool(row['is_emergency']) if 'is_emergency' in row.keys() else None,
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


class UpdateCaseRequest(BaseModel):
    """v2.1.1: 更新案例請求 (支援 ASA + 診斷/術式)"""
    primary_anesthesiologist_id: Optional[str] = None
    primary_nurse_id: Optional[str] = None
    planned_technique: Optional[str] = None
    asa_classification: Optional[str] = None
    is_emergency: Optional[bool] = None
    # v2.1.1: Surgery info
    diagnosis: Optional[str] = None
    operation: Optional[str] = None


@router.patch("/cases/{case_id}")
@router.put("/cases/{case_id}")
async def update_case_metadata(
    case_id: str,
    request: UpdateCaseRequest,
    actor_id: str = Query(...)
):
    """Update case metadata (non-event fields only)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if request.primary_anesthesiologist_id is not None:
        updates.append("primary_anesthesiologist_id = ?")
        params.append(request.primary_anesthesiologist_id)

    if request.primary_nurse_id is not None:
        updates.append("primary_nurse_id = ?")
        params.append(request.primary_nurse_id)

    if request.planned_technique is not None:
        updates.append("planned_technique = ?")
        params.append(request.planned_technique)

    # v1.1: ASA Classification
    if request.asa_classification is not None:
        updates.append("asa_classification = ?")
        params.append(request.asa_classification)

    if request.is_emergency is not None:
        updates.append("is_emergency = ?")
        params.append(1 if request.is_emergency else 0)

    # v2.1.1: Surgery info
    if request.diagnosis is not None:
        updates.append("diagnosis = ?")
        params.append(request.diagnosis)

    if request.operation is not None:
        updates.append("operation = ?")
        params.append(request.operation)

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
        row = cursor.fetchone()

        # Return with proper ASA fields
        result = dict(row)
        if 'asa_classification' in row.keys():
            result['asa_classification'] = row['asa_classification']
        if 'is_emergency' in row.keys():
            result['is_emergency'] = bool(row['is_emergency'])

        return result

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
    # v2.3: Vercel demo mode
    if IS_VERCEL and case_id.startswith("ANES-DEMO"):
        demo_cases = get_demo_anesthesia_cases()
        demo_case = next((c for c in demo_cases if c["id"] == case_id), None)
        if demo_case:
            case_start = datetime.fromisoformat(demo_case["started_at"])
        else:
            case_start = datetime.now() - timedelta(hours=1)

        if case_id == "ANES-DEMO-006":
            demo_events = get_demo_complex_events(case_id, case_start)
        else:
            # Simple demo events for other cases
            demo_events = [
                {"id": f"{case_id}-evt-001", "case_id": case_id, "event_type": "VITAL_SIGN",
                 "clinical_time": (case_start + timedelta(minutes=5)).isoformat(),
                 "payload": {"bp_sys": 120, "bp_dia": 75, "hr": 72, "spo2": 99, "etco2": 35}},
                {"id": f"{case_id}-evt-002", "case_id": case_id, "event_type": "MILESTONE",
                 "clinical_time": (case_start + timedelta(minutes=10)).isoformat(),
                 "payload": {"type": "INTUBATION"}},
                {"id": f"{case_id}-evt-003", "case_id": case_id, "event_type": "VITAL_SIGN",
                 "clinical_time": (case_start + timedelta(minutes=15)).isoformat(),
                 "payload": {"bp_sys": 95, "bp_dia": 60, "hr": 85, "spo2": 98, "etco2": 38}},
            ]

        # Filter by event_type if specified
        if event_type:
            demo_events = [e for e in demo_events if e['event_type'] == event_type]

        return {"events": demo_events, "count": len(demo_events), "demo_mode": True}

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
        # Get case start time from demo cases
        demo_cases = get_demo_anesthesia_cases()
        demo_case = next((c for c in demo_cases if c["id"] == case_id), None)
        if demo_case:
            case_start = datetime.fromisoformat(demo_case["started_at"])
        else:
            case_start = datetime.now() - timedelta(hours=1)

        # For complex case ANES-DEMO-006, use comprehensive event generator
        if case_id == "ANES-DEMO-006":
            demo_events = get_demo_complex_events(case_id, case_start)
        else:
            # Simple demo events for other cases
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
            'fluids': [e for e in demo_events if e['event_type'] in ('FLUID_IN', 'IV_FLUID_GIVEN', 'FLUID_BOLUS')],
            'blood': [e for e in demo_events if e['event_type'] == 'BLOOD_ADMIN'],
            'airway': [],
            'anesthesia_depth': [],
            'milestones': [e for e in demo_events if e['event_type'] == 'MILESTONE'],
            'labs': [e for e in demo_events if e['event_type'] == 'LAB_RESULT_POINT'],
            'positioning': [],
            'notes': [],
            'iv_lines': [e for e in demo_events if e['event_type'] == 'IV_LINE_INSERTED'],
            'monitors': [e for e in demo_events if e['event_type'] == 'MONITOR_START'],
            'urine': [e for e in demo_events if e['event_type'] == 'URINE_OUTPUT'],
            'blood_loss': [e for e in demo_events if e['event_type'] == 'BLOOD_LOSS'],
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
    """
    Claim an oxygen cylinder for this case

    v3.2: 新增 flow_rate_lpm 參數，整合 oxygen tracking 模組
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check cylinder is available
    cursor.execute("""
        SELECT eu.id, eu.unit_serial, eu.claimed_by_case_id, eu.level_percent,
               e.name as equipment_name
        FROM equipment_units eu
        LEFT JOIN equipment e ON eu.equipment_id = e.id
        WHERE eu.id = ? AND (eu.is_active = 1 OR eu.is_active IS NULL)
    """, (request.cylinder_unit_id,))

    unit = cursor.fetchone()
    if not unit:
        raise HTTPException(status_code=404, detail="Cylinder not found")

    if unit['claimed_by_case_id']:
        raise HTTPException(
            status_code=400,
            detail=f"此氧氣瓶已被 {unit['claimed_by_case_id']} 使用中"
        )

    # 使用請求中的 level_percent，或從 unit 取得
    initial_level = request.initial_level_percent if request.initial_level_percent is not None else (unit['level_percent'] or 100)
    flow_rate = request.flow_rate_lpm or 2.0

    # 判斷鋼瓶類型和容量 (E型=680L, H型=6900L)
    equip_name = unit['equipment_name'] or ''
    cylinder_type = 'E' if 'E' in equip_name or 'E型' in equip_name else 'H'
    capacity = 680 if cylinder_type == 'E' else 6900

    try:
        # Claim the cylinder (basic fields first)
        cursor.execute("""
            UPDATE equipment_units
            SET claimed_by_case_id = ?,
                claimed_at = datetime('now'),
                claimed_by_user_id = ?,
                status = 'IN_USE'
            WHERE id = ?
        """, (case_id, actor_id, request.cylinder_unit_id))

        # Try to update last_flow_rate_lpm (column may not exist in older DBs)
        try:
            cursor.execute("""
                UPDATE equipment_units SET last_flow_rate_lpm = ? WHERE id = ?
            """, (flow_rate, request.cylinder_unit_id))
        except Exception:
            pass  # Column doesn't exist, skip

        # Update case
        cursor.execute("""
            UPDATE anesthesia_cases
            SET oxygen_source_type = 'CYLINDER', oxygen_source_id = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (str(request.cylinder_unit_id), case_id))

        # Try to add OXYGEN_CLAIMED event to main events table (for Virtual Sensor)
        # This table may not exist if oxygen_tracking module hasn't initialized
        import time
        try:
            event_id = generate_event_id()
            ts_device = int(time.time() * 1000)
            cursor.execute("""
                INSERT INTO events (id, event_id, entity_type, entity_id, event_type, ts_device, actor_id, payload)
                VALUES (?, ?, 'equipment_unit', ?, 'OXYGEN_CLAIMED', ?, ?, ?)
            """, (
                event_id, event_id, str(request.cylinder_unit_id), ts_device, actor_id,
                json.dumps({
                    "case_id": case_id,
                    "unit_serial": unit['unit_serial'],
                    "cylinder_type": cylinder_type,
                    "initial_level_percent": initial_level,
                    "initial_psi": request.initial_pressure_psi,
                    "capacity_liters": capacity,
                    "flow_rate_lpm": flow_rate
                })
            ))
        except Exception as e:
            logger.warning(f"Could not write to events table: {e}")

        # Also add to anesthesia_events (backwards compatibility)
        anes_event_id = generate_event_id()
        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'RESOURCE_CHECK', datetime('now'), ?, ?)
        """, (
            anes_event_id, case_id,
            json.dumps({
                "resource": "O2_CYLINDER",
                "cylinder_id": unit['unit_serial'],
                "unit_id": request.cylinder_unit_id,
                "level_percent": initial_level,
                "pressure_psi": request.initial_pressure_psi,
                "flow_rate_lpm": flow_rate,
                "action": "CLAIM"
            }),
            actor_id
        ))

        conn.commit()

        return {
            "success": True,
            "cylinder_serial": unit['unit_serial'],
            "level_percent": initial_level,
            "flow_rate_lpm": flow_rate,
            "capacity_liters": capacity,
            "cylinder_type": cylinder_type
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
    # Vercel demo mode
    if IS_VERCEL and case_id.startswith("ANES-DEMO"):
        demo_holdings = [
            {"drug_code": "FENT", "drug_name": "Fentanyl 100mcg/2mL", "schedule_class": 2, "total_issued": 3, "total_used": 2, "total_wasted": 0, "balance": 1, "unit": "amp"},
            {"drug_code": "MIDA", "drug_name": "Midazolam 5mg/mL", "schedule_class": 4, "total_issued": 2, "total_used": 1, "total_wasted": 0, "balance": 1, "unit": "amp"},
        ]
        return {
            "case_id": case_id,
            "holdings": demo_holdings,
            "total_balance": 2,
            "is_reconciled": False,
            "demo_mode": True
        }

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


# =============================================================================
# v1.2: Billing Integration APIs (Phase 1-6)
# Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md
# =============================================================================

# Try to import billing service
try:
    from services.anesthesia_billing import (
        get_quick_drugs_with_inventory,
        process_medication_admin,
        calculate_anesthesia_fee,
        calculate_surgical_fee,  # Phase 5 新增
        generate_cashdesk_handoff,
        export_to_cashdesk,
        MedicationAdminRequest,
        # Break-glass approval (Phase 4)
        get_pending_break_glass_events,
        approve_break_glass,
        get_break_glass_stats,
        BreakGlassApprovalRequest,
        ALLOWED_BREAK_GLASS_REASONS,
        # Case closure (Phase 5)
        on_case_closed,
        validate_case_for_closure,
        CaseClosureResult,
        # Offline queue (Phase 6)
        create_offline_queue_table,
        enqueue_offline_event,
        get_pending_offline_events,
        process_offline_queue,
        get_offline_queue_stats,
        OfflineEvent,
        OfflineEventType
    )
    BILLING_SERVICE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Billing service not available: {e}")
    BILLING_SERVICE_AVAILABLE = False


class MedicationWithBillingRequest(BaseModel):
    """用藥記錄請求 (含計費)"""
    drug_code: str
    drug_name: str
    dose: float
    unit: str
    route: str
    is_controlled: bool = False
    witness_id: Optional[str] = None
    is_break_glass: bool = False
    break_glass_reason: Optional[str] = None
    device_id: Optional[str] = None
    client_event_uuid: Optional[str] = None


class CalculateAnesthesiaFeeRequest(BaseModel):
    """計算麻醉處置費請求"""
    asa_class: int = Field(..., ge=1, le=6)
    asa_emergency: bool = False
    technique: str
    start_time: str  # ISO format
    end_time: str    # ISO format
    special_techniques: Optional[List[str]] = None


@router.get("/quick-drugs-with-inventory")
async def get_quick_drugs_inventory():
    """
    取得快速用藥清單含庫存資訊 (Phase 3)

    Returns:
        藥品清單含庫存狀態 (current_stock, stock_status)
    """
    # Vercel demo 模式或 Billing 服務不可用時，返回模擬資料
    if IS_VERCEL or not BILLING_SERVICE_AVAILABLE:
        demo_drugs = [
            {"medicine_code": "PROP", "medicine_name": "Propofol 200mg/20mL", "generic_name": "Propofol", "default_dose": 100, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 20, "stock_status": "OK", "stock_display": "20"},
            {"medicine_code": "FENT", "medicine_name": "Fentanyl 100mcg/2mL", "generic_name": "Fentanyl", "default_dose": 100, "default_unit": "mcg", "unit": "mcg", "route": "IV", "is_controlled": True, "controlled_level": 2, "current_stock": 15, "stock_status": "OK", "stock_display": "15"},
            {"medicine_code": "ROCU", "medicine_name": "Rocuronium 50mg/5mL", "generic_name": "Rocuronium", "default_dose": 50, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 10, "stock_status": "OK", "stock_display": "10"},
            {"medicine_code": "SUXI", "medicine_name": "Succinylcholine 100mg/2mL", "generic_name": "Succinylcholine", "default_dose": 100, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 8, "stock_status": "OK", "stock_display": "8"},
            {"medicine_code": "MIDA", "medicine_name": "Midazolam 5mg/mL", "generic_name": "Midazolam", "default_dose": 2, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": True, "controlled_level": 4, "current_stock": 12, "stock_status": "OK", "stock_display": "12"},
            {"medicine_code": "ATRO", "medicine_name": "Atropine 0.5mg/mL", "generic_name": "Atropine", "default_dose": 0.5, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 25, "stock_status": "OK", "stock_display": "25"},
            {"medicine_code": "EPHE", "medicine_name": "Ephedrine 30mg/mL", "generic_name": "Ephedrine", "default_dose": 10, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 18, "stock_status": "OK", "stock_display": "18"},
            {"medicine_code": "PHEN", "medicine_name": "Phenylephrine 10mg/mL", "generic_name": "Phenylephrine", "default_dose": 100, "default_unit": "mcg", "unit": "mcg", "route": "IV", "is_controlled": False, "current_stock": 15, "stock_status": "OK", "stock_display": "15"},
            {"medicine_code": "SUGA", "medicine_name": "Sugammadex 200mg/2mL", "generic_name": "Sugammadex", "default_dose": 200, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 6, "stock_status": "OK", "stock_display": "6"},
            {"medicine_code": "NEOS", "medicine_name": "Neostigmine 0.5mg/mL", "generic_name": "Neostigmine", "default_dose": 2.5, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 20, "stock_status": "OK", "stock_display": "20"},
            {"medicine_code": "KETA", "medicine_name": "Ketamine 500mg/10mL", "generic_name": "Ketamine", "default_dose": 50, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": True, "controlled_level": 3, "current_stock": 5, "stock_status": "OK", "stock_display": "5"},
            {"medicine_code": "LIDO", "medicine_name": "Lidocaine 2% 20mL", "generic_name": "Lidocaine", "default_dose": 100, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 30, "stock_status": "OK", "stock_display": "30"},
        ]
        return {"drugs": demo_drugs, "inventory_available": True, "demo_mode": True}

    try:
        drugs = get_quick_drugs_with_inventory()
        return {"drugs": drugs, "inventory_available": True}
    except Exception as e:
        logger.error(f"get_quick_drugs_inventory error: {e}")
        # 錯誤時也返回格式正確的 demo 資料
        demo_drugs = [
            {"medicine_code": "PROP", "medicine_name": "Propofol 200mg/20mL", "generic_name": "Propofol", "default_dose": 100, "default_unit": "mg", "unit": "mg", "route": "IV", "is_controlled": False, "current_stock": 20, "stock_status": "OK", "stock_display": "20"},
            {"medicine_code": "FENT", "medicine_name": "Fentanyl 100mcg/2mL", "generic_name": "Fentanyl", "default_dose": 100, "default_unit": "mcg", "unit": "mcg", "route": "IV", "is_controlled": True, "controlled_level": 2, "current_stock": 15, "stock_status": "OK", "stock_display": "15"},
        ]
        return {"drugs": demo_drugs, "inventory_available": False, "error": str(e)}


@router.post("/cases/{case_id}/medication/with-billing")
async def add_medication_with_billing(
    case_id: str,
    request: MedicationWithBillingRequest,
    actor_id: str = Query(...)
):
    """
    用藥記錄含計費整合 (Phase 3-4)

    功能:
    1. 記錄臨床事件
    2. 單位換算
    3. 管制藥驗證
    4. 扣減庫存
    5. 產生計費項目

    Returns:
        - event_id: 臨床事件 ID
        - inventory_txn_id: 庫存交易 ID
        - billing_quantity: 計費數量
        - estimated_price: 預估價格
        - warnings: 警告訊息
    """
    if not BILLING_SERVICE_AVAILABLE:
        # Fallback: 只記錄事件，不扣庫存
        return await add_medication(case_id, QuickMedicationRequest(
            drug_code=request.drug_code,
            drug_name=request.drug_name,
            dose=request.dose,
            unit=request.unit,
            route=request.route,
            is_controlled=request.is_controlled,
            device_id=request.device_id
        ), actor_id)

    try:
        # 使用 billing service
        admin_request = MedicationAdminRequest(
            drug_code=request.drug_code,
            drug_name=request.drug_name,
            dose=request.dose,
            unit=request.unit,
            route=request.route,
            is_controlled=request.is_controlled,
            witness_id=request.witness_id,
            is_break_glass=request.is_break_glass,
            break_glass_reason=request.break_glass_reason,
            case_id=case_id,
            actor_id=actor_id,
            device_id=request.device_id,
            client_event_uuid=request.client_event_uuid
        )

        result = process_medication_admin(admin_request)

        if not result.success:
            raise HTTPException(status_code=422, detail=result.warnings[0] if result.warnings else "Validation failed")

        # 同時記錄到 anesthesia_events 表 (保持相容性)
        conn = get_db_connection()
        cursor = conn.cursor()

        payload = {
            "drug_code": request.drug_code,
            "drug_name": request.drug_name,
            "dose": request.dose,
            "unit": request.unit,
            "route": request.route,
            "is_controlled": request.is_controlled,
            "billing_quantity": result.billing_quantity,
            "billing_unit": result.billing_unit,
            "estimated_price": result.estimated_price,
            "inventory_txn_id": result.inventory_txn_id
        }

        if result.controlled_log_id:
            payload["controlled_log_id"] = result.controlled_log_id
            payload["witness_status"] = result.witness_status

        cursor.execute("""
            INSERT INTO anesthesia_events (
                id, case_id, event_type, clinical_time, payload, actor_id
            ) VALUES (?, ?, 'MEDICATION_ADMIN', datetime('now'), ?, ?)
        """, (result.event_id, case_id, json.dumps(payload), actor_id))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "event_id": result.event_id,
            "inventory_txn_id": result.inventory_txn_id,
            "billing_quantity": result.billing_quantity,
            "billing_unit": result.billing_unit,
            "estimated_price": result.estimated_price,
            "warnings": result.warnings,
            "controlled_log_id": result.controlled_log_id,
            "witness_status": result.witness_status
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_medication_with_billing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/billing/calculate-anesthesia-fee")
async def api_calculate_anesthesia_fee(
    case_id: str,
    request: CalculateAnesthesiaFeeRequest
):
    """
    計算麻醉處置費 (Phase 5)

    Args:
        case_id: 案件 ID
        request: 計算參數 (ASA, 技術, 時間, 特殊技術)

    Returns:
        費用明細 (base_fee, time_fee, asa_fee, technique_fee, total_fee)
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        start_time = datetime.fromisoformat(request.start_time.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(request.end_time.replace('Z', '+00:00'))

        result = calculate_anesthesia_fee(
            case_id=case_id,
            asa_class=request.asa_class,
            asa_emergency=request.asa_emergency,
            technique=request.technique,
            start_time=start_time,
            end_time=end_time,
            special_techniques=request.special_techniques
        )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"calculate_anesthesia_fee error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class CalculateSurgicalFeeRequest(BaseModel):
    """計算手術處置費請求"""
    surgery_code: str = Field(..., description="手術代碼 (NHI)")
    surgery_name: str = Field(..., description="手術名稱")
    surgery_grade: str = Field(..., description="手術等級 (A/B/C/D)")
    surgeon_id: str = Field(..., description="主刀醫師 ID")
    start_time: str = Field(..., description="手術開始時間 (ISO format)")
    end_time: str = Field(..., description="手術結束時間 (ISO format)")
    assistant_ids: Optional[List[str]] = None


@router.post("/cases/{case_id}/billing/calculate-surgical-fee")
async def api_calculate_surgical_fee(case_id: str, request: CalculateSurgicalFeeRequest):
    """
    計算手術處置費 (Phase 5)

    Args:
        case_id: 案件 ID
        request: 手術計費參數

    Returns:
        - surgeon_fee: 主刀費
        - assistant_fee: 助手費
        - overtime_fee: 超時加成
        - total_fee: 總計
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        start_time = datetime.fromisoformat(request.start_time.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(request.end_time.replace('Z', '+00:00'))

        result = calculate_surgical_fee(
            case_id=case_id,
            surgery_code=request.surgery_code,
            surgery_name=request.surgery_name,
            surgery_grade=request.surgery_grade,
            surgeon_id=request.surgeon_id,
            start_time=start_time,
            end_time=end_time,
            assistant_ids=request.assistant_ids
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"calculate_surgical_fee error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/billing/handoff")
async def api_get_billing_handoff(case_id: str):
    """
    取得 CashDesk Handoff Package (Phase 6)

    返回完整計費封包:
    - medication_items: 藥品費明細
    - anesthesia_fee: 麻醉處置費
    - surgical_fee: 手術處置費
    - grand_total: 總計
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        handoff = generate_cashdesk_handoff(case_id)
        return handoff

    except Exception as e:
        logger.error(f"get_billing_handoff error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/billing/export-to-cashdesk")
async def api_export_to_cashdesk(case_id: str):
    """
    匯出到 CashDesk 並鎖定記錄 (Phase 6)

    WARNING: 匯出後記錄將被鎖定，無法修改
    如需修改，必須使用 VOID pattern

    Returns:
        匯出結果 (exported counts)
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        result = export_to_cashdesk(case_id)
        return result

    except Exception as e:
        logger.error(f"export_to_cashdesk error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/billing/summary")
async def get_billing_summary(case_id: str):
    """
    取得案件計費摘要

    Returns:
        - medication_count: 藥品筆數
        - medication_total: 藥品總費用
        - anesthesia_fee_calculated: 是否已計算麻醉費
        - surgical_fee_calculated: 是否已計算手術費
        - export_status: 匯出狀態
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 藥品統計
        cursor.execute("""
            SELECT
                COUNT(*) as count,
                SUM(billing_quantity * COALESCE(unit_price_at_event, 0)) as total
            FROM medication_usage_events
            WHERE case_id = ? AND billing_status != 'VOIDED' AND is_voided = 0
        """, (case_id,))
        med_row = cursor.fetchone()
        medication_count = med_row['count'] or 0
        medication_total = float(med_row['total'] or 0)

        # 麻醉費
        cursor.execute("""
            SELECT billing_status, total_fee FROM anesthesia_billing_events
            WHERE case_id = ? ORDER BY calculated_at DESC LIMIT 1
        """, (case_id,))
        anes_row = cursor.fetchone()
        anesthesia_fee = float(anes_row['total_fee']) if anes_row else 0
        anesthesia_status = anes_row['billing_status'] if anes_row else 'NOT_CALCULATED'

        # 手術費
        cursor.execute("""
            SELECT billing_status, total_fee FROM surgical_billing_events
            WHERE case_id = ? ORDER BY calculated_at DESC LIMIT 1
        """, (case_id,))
        surg_row = cursor.fetchone()
        surgical_fee = float(surg_row['total_fee']) if surg_row else 0
        surgical_status = surg_row['billing_status'] if surg_row else 'NOT_CALCULATED'

        # 總計
        grand_total = medication_total + anesthesia_fee + surgical_fee

        # 匯出狀態
        cursor.execute("""
            SELECT COUNT(*) as exported FROM medication_usage_events
            WHERE case_id = ? AND billing_status = 'EXPORTED'
        """, (case_id,))
        exported_count = cursor.fetchone()['exported']

        export_status = 'NOT_EXPORTED'
        if exported_count > 0:
            if exported_count == medication_count:
                export_status = 'FULLY_EXPORTED'
            else:
                export_status = 'PARTIALLY_EXPORTED'

        return {
            "case_id": case_id,
            "medication": {
                "count": medication_count,
                "total": medication_total
            },
            "anesthesia_fee": {
                "status": anesthesia_status,
                "total": anesthesia_fee
            },
            "surgical_fee": {
                "status": surgical_status,
                "total": surgical_fee
            },
            "grand_total": grand_total,
            "export_status": export_status
        }

    finally:
        conn.close()


# =============================================================================
# Phase 4: Break-Glass Approval APIs (緊急授權事後核准)
# =============================================================================

class BreakGlassApproveRequest(BaseModel):
    """Break-glass 核准請求"""
    approver_id: str = Field(..., description="核准人 ID")
    notes: Optional[str] = None


@router.get("/break-glass/pending")
async def get_pending_break_glass():
    """
    取得待核准的 Break-glass 事件清單

    Returns:
        - events: 待核准事件清單
        - total: 總數
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        events = get_pending_break_glass_events()
        return {
            "events": events,
            "total": len(events)
        }
    except Exception as e:
        logger.error(f"get_pending_break_glass error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/break-glass/{event_id}/approve")
async def approve_break_glass_event(
    event_id: str,
    request: BreakGlassApproveRequest
):
    """
    核准 Break-glass 事件

    Args:
        event_id: 事件 ID (controlled_drug_log.id)
        request: 核准請求

    Returns:
        核准結果
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        approval_request = BreakGlassApprovalRequest(
            event_id=event_id,
            approver_id=request.approver_id,
            notes=request.notes
        )
        result = approve_break_glass(approval_request)

        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)

        return {
            "success": True,
            "event_id": result.event_id,
            "approved_by": result.approved_by,
            "approved_at": result.approved_at,
            "message": result.message
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"approve_break_glass_event error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/break-glass/stats")
async def get_break_glass_statistics(days: int = Query(30, ge=1, le=365)):
    """
    取得 Break-glass 統計資訊

    Args:
        days: 統計天數 (預設 30 天)

    Returns:
        統計資訊
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        stats = get_break_glass_stats(days=days)
        return stats
    except Exception as e:
        logger.error(f"get_break_glass_statistics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/break-glass/reasons")
async def get_break_glass_reasons():
    """
    取得允許的 Break-glass 原因清單

    Returns:
        原因清單 (用於前端下拉選單)
    """
    if not BILLING_SERVICE_AVAILABLE:
        return {"reasons": [
            {"code": "MTP_ACTIVATED", "label": "大量輸血啟動"},
            {"code": "CARDIAC_ARREST", "label": "心跳停止"},
            {"code": "ANAPHYLAXIS", "label": "過敏性休克"},
            {"code": "AIRWAY_EMERGENCY", "label": "呼吸道緊急"},
            {"code": "EXSANGUINATING_HEMORRHAGE", "label": "大量出血"},
            {"code": "NO_SECOND_STAFF", "label": "無第二人員可協助"},
            {"code": "SYSTEM_OFFLINE", "label": "系統離線"},
            {"code": "OTHER", "label": "其他"},
        ]}

    return {"reasons": [
        {"code": reason, "label": {
            "MTP_ACTIVATED": "大量輸血啟動",
            "CARDIAC_ARREST": "心跳停止",
            "ANAPHYLAXIS": "過敏性休克",
            "AIRWAY_EMERGENCY": "呼吸道緊急",
            "EXSANGUINATING_HEMORRHAGE": "大量出血",
            "NO_SECOND_STAFF": "無第二人員可協助",
            "SYSTEM_OFFLINE": "系統離線",
            "OTHER": "其他",
        }.get(reason, reason)}
        for reason in ALLOWED_BREAK_GLASS_REASONS
    ]}


# =============================================================================
# Phase 5: Case Closure APIs (案件關帳)
# =============================================================================

class CaseCloseRequest(BaseModel):
    """案件關帳請求"""
    actor_id: str = Field(..., description="執行者 ID")
    surgery_code: Optional[str] = Field(None, description="手術代碼")
    surgery_name: Optional[str] = Field(None, description="手術名稱")
    surgery_grade: Optional[str] = Field("C", description="手術等級 (A/B/C/D)")
    surgeon_id: Optional[str] = Field(None, description="主刀醫師 ID")
    assistant_ids: Optional[List[str]] = Field(None, description="助手醫師 IDs")
    force: bool = Field(False, description="強制關帳 (忽略驗證警告)")


@router.get("/cases/{case_id}/close/validate")
async def validate_case_closure(case_id: str):
    """
    驗證案件是否可以關帳

    檢查項目:
    - 案件狀態是否允許關帳
    - 是否有未處理的 Break-glass 事件
    - 是否有未同步的離線事件
    - 管制藥品用量是否配平

    Returns:
        - can_close: 是否可以關帳
        - warnings: 警告清單 (可忽略)
        - errors: 錯誤清單 (必須解決)
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        result = validate_case_for_closure(case_id)
        return result
    except Exception as e:
        logger.error(f"validate_case_closure error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/close")
async def close_case_and_calculate_billing(
    case_id: str,
    request: CaseCloseRequest
):
    """
    關閉案件並自動計算計費

    此 API 會:
    1. 驗證案件狀態
    2. 計算麻醉費用 (根據時間和技術)
    3. 計算手術費用 (如提供手術資訊)
    4. 計算藥品總費用
    5. 更新案件狀態為 CLOSED

    Args:
        case_id: 案件 ID
        request: 關帳請求 (包含手術資訊)

    Returns:
        CaseClosureResult - 包含所有計費結果和警告
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        result: CaseClosureResult = on_case_closed(
            case_id=case_id,
            actor_id=request.actor_id,
            surgery_code=request.surgery_code,
            surgery_name=request.surgery_name,
            surgery_grade=request.surgery_grade,
            surgeon_id=request.surgeon_id,
            assistant_ids=request.assistant_ids,
            force=request.force
        )

        if not result.success and result.errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "案件關帳失敗",
                    "errors": result.errors,
                    "warnings": result.warnings
                }
            )

        return {
            "success": result.success,
            "case_id": result.case_id,
            "billing": {
                "anesthesia_billing_id": result.anesthesia_billing_id,
                "surgical_billing_id": result.surgical_billing_id,
                "medication_total": result.medication_total,
                "grand_total": result.grand_total
            },
            "warnings": result.warnings,
            "message": "案件已關帳，計費完成"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"close_case_and_calculate_billing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase 6: Offline Queue APIs (離線佇列)
# =============================================================================

class OfflineEventRequest(BaseModel):
    """離線事件入列請求"""
    event_type: str = Field(..., description="事件類型: MEDICATION_ADMIN, VITAL_SIGN, CONTROLLED_DRUG, INVENTORY_DEDUCT")
    case_id: Optional[str] = Field(None, description="關聯案件 ID")
    payload: Dict[str, Any] = Field(..., description="事件內容")
    client_timestamp: str = Field(..., description="客戶端時間戳 (ISO 8601)")
    client_uuid: str = Field(..., description="客戶端產生的 UUID (用於冪等性)")


@router.post("/offline-queue/enqueue")
async def enqueue_offline_event_api(request: OfflineEventRequest):
    """
    將事件加入離線佇列

    當裝置離線時，前端應將事件暫存並在恢復連線後透過此 API 同步

    Args:
        request: 離線事件請求

    Returns:
        - success: 是否成功入列
        - event_id: 產生的事件 ID
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        # 驗證 event_type
        try:
            event_type = OfflineEventType(request.event_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_type: {request.event_type}. Must be one of: {[e.value for e in OfflineEventType]}"
            )

        event = OfflineEvent(
            event_type=event_type,
            case_id=request.case_id,
            payload=request.payload,
            client_timestamp=request.client_timestamp,
            client_uuid=request.client_uuid
        )

        success = enqueue_offline_event(event)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to enqueue event")

        return {
            "success": True,
            "event_id": event.event_id,
            "client_uuid": event.client_uuid,
            "message": "事件已加入離線佇列"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"enqueue_offline_event error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/offline-queue")
async def get_offline_queue(
    status: Optional[str] = Query(None, description="篩選狀態: PENDING, SYNCING, SYNCED, CONFLICT, FAILED"),
    case_id: Optional[str] = Query(None, description="篩選案件 ID"),
    limit: int = Query(100, ge=1, le=500)
):
    """
    取得離線佇列事件清單

    Args:
        status: 篩選狀態
        case_id: 篩選案件
        limit: 最多回傳筆數

    Returns:
        - events: 事件清單
        - total: 總數
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        events = get_pending_offline_events(limit=limit)

        # 額外篩選
        if status:
            events = [e for e in events if e.get('sync_status') == status]
        if case_id:
            events = [e for e in events if e.get('case_id') == case_id]

        return {
            "events": events,
            "total": len(events)
        }

    except Exception as e:
        logger.error(f"get_offline_queue error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/offline-queue/process")
async def process_offline_queue_api():
    """
    處理離線佇列中的待同步事件

    此 API 會:
    1. 取得所有 PENDING 狀態的事件
    2. 依序處理每個事件
    3. 更新同步狀態
    4. 記錄處理結果

    Returns:
        處理結果統計
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        result = process_offline_queue()
        return result

    except Exception as e:
        logger.error(f"process_offline_queue error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/offline-queue/stats")
async def get_offline_queue_statistics():
    """
    取得離線佇列統計資訊

    Returns:
        - total: 總事件數
        - by_status: 依狀態統計
        - by_type: 依類型統計
        - oldest_pending: 最早的待處理事件時間
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        stats = get_offline_queue_stats()
        return stats

    except Exception as e:
        logger.error(f"get_offline_queue_stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/offline-queue/init")
async def initialize_offline_queue_table():
    """
    初始化離線佇列表 (建立資料表)

    首次使用離線功能前需要呼叫此 API 確保資料表存在

    Returns:
        - success: 是否成功
    """
    if not BILLING_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing service not available")

    try:
        create_offline_queue_table()
        return {
            "success": True,
            "message": "離線佇列表已初始化"
        }

    except Exception as e:
        logger.error(f"initialize_offline_queue_table error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase 7: Drug Cart Management APIs (藥車管理)
# =============================================================================

class CartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MAINTENANCE = "MAINTENANCE"


class DispatchType(str, Enum):
    REPLENISH = "REPLENISH"   # 藥局 → 藥車
    RETURN = "RETURN"         # 藥車 → 藥局
    HANDOFF = "HANDOFF"       # 藥車 → 藥車 (交班)


class DispatchStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"


# --- Pydantic Models ---
class CartCreate(BaseModel):
    cart_id: str = Field(..., description="藥車編號")
    cart_name: str = Field(..., description="藥車名稱")
    cart_location: Optional[str] = None


class CartUpdate(BaseModel):
    cart_name: Optional[str] = None
    cart_location: Optional[str] = None
    status: Optional[CartStatus] = None
    assigned_to: Optional[str] = None


class CartInventoryItem(BaseModel):
    medicine_code: str
    quantity: int
    min_quantity: int = 2
    max_quantity: int = 10
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None


class DispatchItem(BaseModel):
    medicine_code: str
    quantity: int


class DispatchCreate(BaseModel):
    dispatch_type: DispatchType
    from_location: str = Field(..., description="來源: 'PHARMACY' 或 cart_id")
    to_location: str = Field(..., description="目標: cart_id 或 'PHARMACY'")
    items: List[DispatchItem]


class DispatchReceive(BaseModel):
    receiver_id: str
    discrepancy_report: Optional[Dict] = None


class DispatchVerify(BaseModel):
    pharmacist_id: str


# --- Cart CRUD ---
@router.get("/carts")
async def list_carts(
    status: Optional[CartStatus] = None,
    assigned_to: Optional[str] = None
):
    """列出所有藥車"""
    if IS_VERCEL:
        return {"carts": [
            {"cart_id": "CART-001", "cart_name": "1號藥車", "status": "ACTIVE", "cart_location": "OR-1"},
            {"cart_id": "CART-002", "cart_name": "2號藥車", "status": "ACTIVE", "cart_location": "OR-2"}
        ]}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM anesthesia_carts WHERE 1=1"
        params = []

        if status:
            sql += " AND status = ?"
            params.append(status.value)
        if assigned_to:
            sql += " AND assigned_to = ?"
            params.append(assigned_to)

        sql += " ORDER BY cart_id"
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        return {"carts": [dict(row) for row in rows]}
    finally:
        conn.close()


@router.post("/carts")
async def create_cart(
    cart: CartCreate,
    actor_id: str = Query(..., description="操作者 ID")
):
    """建立新藥車"""
    if IS_VERCEL:
        return {"cart_id": cart.cart_id, "status": "created"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO anesthesia_carts (cart_id, cart_name, cart_location, status)
            VALUES (?, ?, ?, 'ACTIVE')
        """, (cart.cart_id, cart.cart_name, cart.cart_location))
        conn.commit()

        return {
            "cart_id": cart.cart_id,
            "cart_name": cart.cart_name,
            "status": "ACTIVE",
            "message": "藥車建立成功"
        }
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=409, detail="藥車編號已存在")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/carts/{cart_id}")
async def get_cart(cart_id: str):
    """取得藥車詳情與庫存 (Layer 3 - cart_inventory)"""
    if IS_VERCEL:
        # Demo cart inventory aligned with Three-Layer Ledger architecture
        demo_cart_inventory = [
            {"medicine_code": "PROP", "medicine_name": "Propofol 200mg/20mL", "quantity": 20, "min_quantity": 5, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "FENT", "medicine_name": "Fentanyl 100mcg/2mL", "quantity": 10, "min_quantity": 3, "is_controlled": True, "controlled_level": 2, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "MIDA", "medicine_name": "Midazolam 5mg/mL", "quantity": 8, "min_quantity": 3, "is_controlled": True, "controlled_level": 4, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "KETA", "medicine_name": "Ketamine 50mg/mL", "quantity": 5, "min_quantity": 2, "is_controlled": True, "controlled_level": 3, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "ROCU", "medicine_name": "Rocuronium 50mg/5mL", "quantity": 15, "min_quantity": 5, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "SUXI", "medicine_name": "Succinylcholine 200mg/10mL", "quantity": 10, "min_quantity": 3, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "ATRO", "medicine_name": "Atropine 0.5mg/mL", "quantity": 25, "min_quantity": 10, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "EPHE", "medicine_name": "Ephedrine 50mg/mL", "quantity": 20, "min_quantity": 5, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "PHEN", "medicine_name": "Phenylephrine 10mg/mL", "quantity": 15, "min_quantity": 5, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "SUGA", "medicine_name": "Sugammadex 200mg/2mL", "quantity": 6, "min_quantity": 2, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "NEOS", "medicine_name": "Neostigmine 0.5mg/mL", "quantity": 20, "min_quantity": 5, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
            {"medicine_code": "LIDO", "medicine_name": "Lidocaine 2% 20mL", "quantity": 30, "min_quantity": 10, "is_controlled": False, "last_dispatch": "2026-01-20T08:00:00Z"},
        ]
        return {
            "cart": {
                "cart_id": cart_id,
                "cart_name": "麻醉藥車 Demo",
                "cart_type": "ANESTHESIA",
                "location": "OR-DEMO",
                "status": "ACTIVE",
                "layer": "Layer 3 - Anesthesia Cart"
            },
            "inventory": demo_cart_inventory,
            "summary": {
                "total_items": len(demo_cart_inventory),
                "controlled_items": len([i for i in demo_cart_inventory if i.get("is_controlled")]),
                "low_stock_items": len([i for i in demo_cart_inventory if i["quantity"] <= i["min_quantity"]])
            },
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 藥車基本資訊
        cursor.execute("SELECT * FROM anesthesia_carts WHERE cart_id = ?", (cart_id,))
        cart = cursor.fetchone()
        if not cart:
            raise HTTPException(status_code=404, detail="藥車不存在")

        # 藥車庫存
        cursor.execute("""
            SELECT ci.*, m.medicine_name, m.is_controlled
            FROM cart_inventory ci
            LEFT JOIN medicines m ON ci.medicine_code = m.medicine_code
            WHERE ci.cart_id = ?
            ORDER BY m.medicine_name
        """, (cart_id,))
        inventory = cursor.fetchall()

        return {
            "cart": dict(cart),
            "inventory": [dict(row) for row in inventory]
        }
    finally:
        conn.close()


@router.patch("/carts/{cart_id}")
async def update_cart(
    cart_id: str,
    update: CartUpdate,
    actor_id: str = Query(..., description="操作者 ID")
):
    """更新藥車資訊"""
    if IS_VERCEL:
        return {"cart_id": cart_id, "status": "updated"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        updates = []
        params = []
        if update.cart_name:
            updates.append("cart_name = ?")
            params.append(update.cart_name)
        if update.cart_location is not None:
            updates.append("cart_location = ?")
            params.append(update.cart_location)
        if update.status:
            updates.append("status = ?")
            params.append(update.status.value)
        if update.assigned_to is not None:
            updates.append("assigned_to = ?")
            params.append(update.assigned_to)
            updates.append("assigned_at = ?")
            params.append(datetime.now().isoformat())

        if not updates:
            raise HTTPException(status_code=400, detail="無更新欄位")

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(cart_id)

        cursor.execute(f"""
            UPDATE anesthesia_carts SET {', '.join(updates)}
            WHERE cart_id = ?
        """, params)
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="藥車不存在")

        return {"cart_id": cart_id, "message": "藥車更新成功"}
    finally:
        conn.close()


# --- Cart Inventory Management ---
@router.put("/carts/{cart_id}/inventory")
async def set_cart_inventory(
    cart_id: str,
    items: List[CartInventoryItem],
    actor_id: str = Query(..., description="操作者 ID")
):
    """設定藥車庫存 (批量)"""
    if IS_VERCEL:
        return {"cart_id": cart_id, "items_count": len(items)}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 檢查藥車存在
        cursor.execute("SELECT 1 FROM anesthesia_carts WHERE cart_id = ?", (cart_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="藥車不存在")

        for item in items:
            cursor.execute("""
                INSERT INTO cart_inventory (cart_id, medicine_code, quantity, min_quantity, max_quantity, batch_number, expiry_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cart_id, medicine_code) DO UPDATE SET
                    quantity = excluded.quantity,
                    min_quantity = excluded.min_quantity,
                    max_quantity = excluded.max_quantity,
                    batch_number = excluded.batch_number,
                    expiry_date = excluded.expiry_date,
                    updated_at = CURRENT_TIMESTAMP
            """, (cart_id, item.medicine_code, item.quantity, item.min_quantity, item.max_quantity, item.batch_number, item.expiry_date))

        conn.commit()
        return {"cart_id": cart_id, "items_updated": len(items), "message": "藥車庫存已更新"}
    finally:
        conn.close()


@router.post("/carts/{cart_id}/inventory/check")
async def check_cart_inventory(
    cart_id: str,
    actor_id: str = Query(..., description="清點者 ID")
):
    """執行藥車庫存清點"""
    if IS_VERCEL:
        return {"cart_id": cart_id, "checked_at": datetime.now().isoformat()}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE anesthesia_carts
            SET last_inventory_check = ?, last_checked_by = ?, updated_at = ?
            WHERE cart_id = ?
        """, (datetime.now().isoformat(), actor_id, datetime.now().isoformat(), cart_id))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="藥車不存在")

        return {
            "cart_id": cart_id,
            "checked_by": actor_id,
            "checked_at": datetime.now().isoformat(),
            "message": "藥車清點完成"
        }
    finally:
        conn.close()


# --- Cart Dispatch (調撥) ---
@router.post("/cart-dispatch")
async def create_dispatch(
    dispatch: DispatchCreate,
    actor_id: str = Query(..., description="調撥發起者 ID")
):
    """建立藥品調撥單"""
    if IS_VERCEL:
        return {"dispatch_id": f"DSP-{uuid.uuid4().hex[:8].upper()}", "status": "PENDING"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        dispatch_id = f"DSP-{uuid.uuid4().hex[:8].upper()}"

        items_json = json.dumps([{"medicine_code": i.medicine_code, "quantity": i.quantity} for i in dispatch.items])

        cursor.execute("""
            INSERT INTO cart_dispatch_records (
                dispatch_id, dispatch_type, from_location, to_location, items, dispatcher_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
        """, (dispatch_id, dispatch.dispatch_type.value, dispatch.from_location, dispatch.to_location, items_json, actor_id))
        conn.commit()

        return {
            "dispatch_id": dispatch_id,
            "dispatch_type": dispatch.dispatch_type.value,
            "from_location": dispatch.from_location,
            "to_location": dispatch.to_location,
            "items_count": len(dispatch.items),
            "status": "PENDING",
            "message": "調撥單已建立"
        }
    finally:
        conn.close()


@router.get("/cart-dispatch")
async def list_dispatches(
    status: Optional[DispatchStatus] = None,
    cart_id: Optional[str] = None,
    limit: int = Query(20, le=100)
):
    """列出調撥單"""
    if IS_VERCEL:
        return {"dispatches": []}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM cart_dispatch_records WHERE 1=1"
        params = []

        if status:
            sql += " AND status = ?"
            params.append(status.value)
        if cart_id:
            sql += " AND (from_location = ? OR to_location = ?)"
            params.extend([cart_id, cart_id])

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        dispatches = []
        for row in rows:
            d = dict(row)
            d['items'] = json.loads(d['items']) if d['items'] else []
            dispatches.append(d)

        return {"dispatches": dispatches}
    finally:
        conn.close()


@router.get("/cart-dispatch/{dispatch_id}")
async def get_dispatch(dispatch_id: str):
    """取得調撥單詳情"""
    if IS_VERCEL:
        return {"dispatch_id": dispatch_id, "status": "PENDING"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cart_dispatch_records WHERE dispatch_id = ?", (dispatch_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="調撥單不存在")

        d = dict(row)
        d['items'] = json.loads(d['items']) if d['items'] else []
        return d
    finally:
        conn.close()


@router.post("/cart-dispatch/{dispatch_id}/transit")
async def mark_dispatch_in_transit(
    dispatch_id: str,
    actor_id: str = Query(..., description="操作者 ID")
):
    """標記調撥單為運送中"""
    if IS_VERCEL:
        return {"dispatch_id": dispatch_id, "status": "IN_TRANSIT"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cart_dispatch_records SET status = 'IN_TRANSIT'
            WHERE dispatch_id = ? AND status = 'PENDING'
        """, (dispatch_id,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=400, detail="調撥單狀態無法變更")

        return {"dispatch_id": dispatch_id, "status": "IN_TRANSIT", "message": "已標記為運送中"}
    finally:
        conn.close()


@router.post("/cart-dispatch/{dispatch_id}/receive")
async def receive_dispatch(
    dispatch_id: str,
    receive: DispatchReceive
):
    """接收調撥單 - 更新藥車庫存"""
    if IS_VERCEL:
        return {"dispatch_id": dispatch_id, "status": "RECEIVED"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 取得調撥單
        cursor.execute("SELECT * FROM cart_dispatch_records WHERE dispatch_id = ?", (dispatch_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="調撥單不存在")

        dispatch = dict(row)
        if dispatch['status'] not in ('PENDING', 'IN_TRANSIT'):
            raise HTTPException(status_code=400, detail="調撥單狀態無法接收")

        items = json.loads(dispatch['items']) if dispatch['items'] else []
        to_location = dispatch['to_location']
        from_location = dispatch['from_location']
        dispatch_type = dispatch['dispatch_type']

        # 更新藥車庫存
        if dispatch_type == 'REPLENISH':
            # 藥局 → 藥車: 增加藥車庫存
            for item in items:
                cursor.execute("""
                    UPDATE cart_inventory SET quantity = quantity + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE cart_id = ? AND medicine_code = ?
                """, (item['quantity'], to_location, item['medicine_code']))

                # 如果不存在，則新增
                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO cart_inventory (cart_id, medicine_code, quantity)
                        VALUES (?, ?, ?)
                    """, (to_location, item['medicine_code'], item['quantity']))

        elif dispatch_type == 'RETURN':
            # 藥車 → 藥局: 減少藥車庫存
            for item in items:
                cursor.execute("""
                    UPDATE cart_inventory SET quantity = MAX(0, quantity - ?), updated_at = CURRENT_TIMESTAMP
                    WHERE cart_id = ? AND medicine_code = ?
                """, (item['quantity'], from_location, item['medicine_code']))

        elif dispatch_type == 'HANDOFF':
            # 藥車 → 藥車: 從來源減少，目標增加
            for item in items:
                # 來源減少
                cursor.execute("""
                    UPDATE cart_inventory SET quantity = MAX(0, quantity - ?), updated_at = CURRENT_TIMESTAMP
                    WHERE cart_id = ? AND medicine_code = ?
                """, (item['quantity'], from_location, item['medicine_code']))
                # 目標增加
                cursor.execute("""
                    UPDATE cart_inventory SET quantity = quantity + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE cart_id = ? AND medicine_code = ?
                """, (item['quantity'], to_location, item['medicine_code']))
                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO cart_inventory (cart_id, medicine_code, quantity)
                        VALUES (?, ?, ?)
                    """, (to_location, item['medicine_code'], item['quantity']))

        # 更新調撥單狀態
        discrepancy_json = json.dumps(receive.discrepancy_report) if receive.discrepancy_report else None
        cursor.execute("""
            UPDATE cart_dispatch_records
            SET status = 'RECEIVED', receiver_id = ?, receiver_verified_at = ?, discrepancy_report = ?
            WHERE dispatch_id = ?
        """, (receive.receiver_id, datetime.now().isoformat(), discrepancy_json, dispatch_id))
        conn.commit()

        return {
            "dispatch_id": dispatch_id,
            "status": "RECEIVED",
            "received_by": receive.receiver_id,
            "items_processed": len(items),
            "message": "調撥已接收，庫存已更新"
        }
    finally:
        conn.close()


@router.post("/cart-dispatch/{dispatch_id}/verify")
async def verify_dispatch(
    dispatch_id: str,
    verify: DispatchVerify
):
    """藥師核對調撥單"""
    if IS_VERCEL:
        return {"dispatch_id": dispatch_id, "status": "VERIFIED"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cart_dispatch_records
            SET status = 'VERIFIED', pharmacist_id = ?, pharmacist_verified_at = ?
            WHERE dispatch_id = ? AND status = 'RECEIVED'
        """, (verify.pharmacist_id, datetime.now().isoformat(), dispatch_id))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=400, detail="調撥單狀態無法核對 (需先接收)")

        return {
            "dispatch_id": dispatch_id,
            "status": "VERIFIED",
            "verified_by": verify.pharmacist_id,
            "message": "藥師核對完成"
        }
    finally:
        conn.close()


# --- Cart Low Stock Alert ---
@router.get("/carts/{cart_id}/low-stock")
async def get_cart_low_stock(cart_id: str):
    """取得藥車低庫存警示"""
    if IS_VERCEL:
        return {"cart_id": cart_id, "alerts": []}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ci.*, m.medicine_name, m.is_controlled
            FROM cart_inventory ci
            LEFT JOIN medicines m ON ci.medicine_code = m.medicine_code
            WHERE ci.cart_id = ? AND ci.quantity <= ci.min_quantity
            ORDER BY ci.quantity ASC
        """, (cart_id,))
        rows = cursor.fetchall()

        alerts = []
        for row in rows:
            alerts.append({
                "medicine_code": row['medicine_code'],
                "medicine_name": row['medicine_name'],
                "current_quantity": row['quantity'],
                "min_quantity": row['min_quantity'],
                "is_controlled": bool(row['is_controlled']),
                "severity": "CRITICAL" if row['quantity'] == 0 else "WARNING"
            })

        return {
            "cart_id": cart_id,
            "alerts_count": len(alerts),
            "alerts": alerts
        }
    finally:
        conn.close()


# --- Cart Controlled Drugs Inventory (Holdings Tab) ---
@router.get("/carts/{cart_id}/controlled-drugs")
async def get_cart_controlled_drugs(cart_id: str):
    """
    取得藥車管制藥清單 (for Holdings Tab)
    Layer 3 - Anesthesia Cart controlled drugs inventory

    Returns:
        holdings: 管制藥持有清單
        total_items: 管制藥品項數
        recent_transactions: 最近管制藥交易
    """
    if IS_VERCEL:
        # Demo controlled drugs for Holdings tab
        demo_controlled = [
            {
                "medicine_code": "FENT",
                "medicine_name": "Fentanyl 100mcg/2mL",
                "controlled_level": 2,
                "quantity": 10,
                "unit": "amp",
                "last_dispatch": "2026-01-20T08:00:00Z",
                "last_use": "2026-01-21T09:30:00Z"
            },
            {
                "medicine_code": "MIDA",
                "medicine_name": "Midazolam 5mg/mL",
                "controlled_level": 4,
                "quantity": 8,
                "unit": "amp",
                "last_dispatch": "2026-01-20T08:00:00Z",
                "last_use": "2026-01-21T10:15:00Z"
            },
            {
                "medicine_code": "KETA",
                "medicine_name": "Ketamine 50mg/mL",
                "controlled_level": 3,
                "quantity": 5,
                "unit": "vial",
                "last_dispatch": "2026-01-20T08:00:00Z",
                "last_use": None
            }
        ]
        demo_transactions = [
            {"txn_id": "CITXN-DEMO-001", "txn_type": "DISPATCH", "medicine_code": "FENT", "quantity_change": 10, "created_at": "2026-01-20T08:00:00Z"},
            {"txn_id": "CITXN-DEMO-002", "txn_type": "USE", "medicine_code": "FENT", "quantity_change": -1, "case_id": "ANES-DEMO-001", "created_at": "2026-01-21T09:30:00Z"},
            {"txn_id": "CITXN-DEMO-003", "txn_type": "DISPATCH", "medicine_code": "MIDA", "quantity_change": 8, "created_at": "2026-01-20T08:00:00Z"},
        ]
        return {
            "cart_id": cart_id,
            "holdings": demo_controlled,
            "total_items": len(demo_controlled),
            "recent_transactions": demo_transactions,
            "layer": "Layer 3 - Anesthesia Cart",
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get controlled drugs in cart
        cursor.execute("""
            SELECT ci.medicine_code, ci.quantity, ci.last_replenish_at,
                   m.medicine_name, m.controlled_level, m.unit
            FROM cart_inventory ci
            JOIN medicines m ON ci.medicine_code = m.medicine_code
            WHERE ci.cart_id = ? AND m.is_controlled = 1
            ORDER BY m.controlled_level, m.medicine_name
        """, (cart_id,))
        holdings = []
        for row in cursor.fetchall():
            holdings.append({
                "medicine_code": row['medicine_code'],
                "medicine_name": row['medicine_name'],
                "controlled_level": row['controlled_level'],
                "quantity": row['quantity'],
                "unit": row['unit'] or 'amp',
                "last_dispatch": row['last_replenish_at']
            })

        # Get recent transactions for controlled drugs
        cursor.execute("""
            SELECT txn_id, txn_type, medicine_code, quantity_change, case_id, created_at
            FROM cart_inventory_transactions
            WHERE cart_id = ? AND medicine_code IN (
                SELECT medicine_code FROM medicines WHERE is_controlled = 1
            )
            ORDER BY created_at DESC
            LIMIT 10
        """, (cart_id,))
        transactions = [dict(row) for row in cursor.fetchall()]

        return {
            "cart_id": cart_id,
            "holdings": holdings,
            "total_items": len(holdings),
            "recent_transactions": transactions,
            "layer": "Layer 3 - Anesthesia Cart"
        }
    finally:
        conn.close()


# =============================================================================
# Phase 9: Drug Transfer System (Multi-Cart & Drug Transfer v1.1)
# =============================================================================

import secrets
import string
import hashlib
import hmac

# Base32 字元集 (排除 0OIL 避免混淆)
TRANSFER_CODE_CHARS = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
TRANSFER_CODE_SECRET = os.environ.get('TRANSFER_CODE_SECRET', 'mirs-transfer-secret-key')


def generate_transfer_code() -> str:
    """Generate short transfer code for iOS (XFER-XXXX)"""
    code = ''.join(secrets.choice(TRANSFER_CODE_CHARS) for _ in range(4))
    return f"XFER-{code}"


def generate_transfer_id() -> str:
    """Generate unique transfer ID"""
    return f"XFER-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


class TransferRequest(BaseModel):
    transfer_type: str  # CASE_TO_CASE, CASE_TO_CART, CART_TO_CASE, CART_TO_CART

    # 來源
    from_case_id: Optional[str] = None
    from_cart_id: Optional[str] = None

    # 目的
    to_case_id: Optional[str] = None
    to_cart_id: Optional[str] = None
    to_nurse_id: Optional[str] = None
    to_nurse_name: Optional[str] = None

    # 藥品
    medicine_code: str
    medicine_name: Optional[str] = None
    quantity: int
    unit: str = 'amp'

    # 管制藥
    is_controlled: bool = False
    controlled_level: Optional[int] = None

    # 見證
    witness_id: Optional[str] = None
    witness_name: Optional[str] = None

    # 合規聲明
    unopened_declared: bool = False

    remarks: Optional[str] = None


@router.post("/transfers")
async def initiate_transfer(
    request: TransferRequest,
    actor_id: str = Query(..., description="發起人 ID"),
    actor_name: str = Query(None, description="發起人姓名")
):
    """
    發起藥品移轉 (Immediate Debit Model)

    v1.1: 發起時立即扣減來源庫存，避免 Double-Spend
    """
    # Vercel demo mode
    if IS_VERCEL:
        transfer_id = generate_transfer_id()
        transfer_code = generate_transfer_code()
        expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()
        return {
            "transfer_id": transfer_id,
            "transfer_code": transfer_code,
            "status": "PENDING",
            "expires_at": expires_at,
            "message": "移轉已發起，來源庫存已扣減",
            "immediate_debit": True,
            "demo_mode": True
        }

    # Validation
    if not request.unopened_declared:
        raise HTTPException(status_code=400, detail="必須聲明藥品未開封")

    if request.is_controlled and not request.witness_id:
        raise HTTPException(status_code=400, detail="管制藥移轉需要見證人")

    if request.quantity <= 0:
        raise HTTPException(status_code=400, detail="數量必須大於 0")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION")

        transfer_id = generate_transfer_id()
        transfer_code = generate_transfer_code()
        expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()

        # Determine from_type
        from_type = 'CASE' if request.from_case_id else 'CART'
        to_type = 'CASE' if request.to_case_id else 'CART'

        # v1.1 Immediate Debit: 立即扣減來源庫存
        if from_type == 'CASE' and request.from_case_id:
            # 從案件 holdings 扣減 - 需要實作 case holdings 表
            # 暫時記錄交易
            pass
        elif from_type == 'CART' and request.from_cart_id:
            # 從藥車庫存扣減
            cursor.execute("""
                UPDATE cart_inventory
                SET quantity = quantity - ?, updated_at = ?
                WHERE cart_id = ? AND medicine_code = ?
            """, (request.quantity, datetime.now().isoformat(),
                  request.from_cart_id, request.medicine_code))

            # 記錄交易
            txn_id = f"CITXN-XFER-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
            cursor.execute("""
                INSERT INTO cart_inventory_transactions (
                    txn_id, txn_type, cart_id, medicine_code,
                    quantity_change, quantity_before, quantity_after,
                    source_type, source_id, actor_id, remarks
                ) VALUES (?, 'TRANSFER_OUT_PENDING', ?, ?, ?, 0, 0, 'TRANSFER', ?, ?, ?)
            """, (txn_id, request.from_cart_id, request.medicine_code,
                  -request.quantity, transfer_id, actor_id,
                  f"Transfer to {request.to_case_id or request.to_cart_id}"))

        # 建立移轉記錄
        cursor.execute("""
            INSERT INTO drug_transfers (
                transfer_id, transfer_code, transfer_type,
                from_type, from_case_id, from_cart_id, from_nurse_id, from_nurse_name,
                to_type, to_case_id, to_cart_id, to_nurse_id, to_nurse_name,
                medicine_code, medicine_name, quantity, unit,
                is_controlled, controlled_level,
                witness_id, witness_name,
                status, from_confirmed, from_confirmed_at,
                unopened_declared, declaration_timestamp,
                remarks, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 1, ?, 1, ?, ?, ?)
        """, (
            transfer_id, transfer_code, request.transfer_type,
            from_type, request.from_case_id, request.from_cart_id, actor_id, actor_name,
            to_type, request.to_case_id, request.to_cart_id, request.to_nurse_id, request.to_nurse_name,
            request.medicine_code, request.medicine_name, request.quantity, request.unit,
            request.is_controlled, request.controlled_level,
            request.witness_id, request.witness_name,
            datetime.now().isoformat(), datetime.now().isoformat(),
            request.remarks, expires_at
        ))

        # 建立通知 (給接收方)
        if request.to_nurse_id:
            cursor.execute("""
                INSERT INTO transfer_notifications (
                    transfer_id, target_nurse_id, target_type, notification_type
                ) VALUES (?, ?, 'RECEIVER', 'TRANSFER_REQUEST')
            """, (transfer_id, request.to_nurse_id))

        conn.commit()

        return {
            "transfer_id": transfer_id,
            "transfer_code": transfer_code,
            "status": "PENDING",
            "expires_at": expires_at,
            "message": "移轉已發起，來源庫存已扣減 (Immediate Debit)",
            "immediate_debit": True
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/transfers/{transfer_id}/confirm")
async def confirm_transfer(
    transfer_id: str,
    actor_id: str = Query(..., description="確認人 ID")
):
    """
    接收方確認移轉

    v1.1: 來源已在發起時扣減，此處只需入帳目的方
    """
    if IS_VERCEL:
        return {
            "transfer_id": transfer_id,
            "status": "CONFIRMED",
            "message": "移轉已確認，藥品已入帳",
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 查詢移轉記錄
        cursor.execute("SELECT * FROM drug_transfers WHERE transfer_id = ?", (transfer_id,))
        transfer = cursor.fetchone()

        if not transfer:
            raise HTTPException(status_code=404, detail="移轉記錄不存在")

        if transfer['status'] != 'PENDING':
            raise HTTPException(status_code=400, detail=f"移轉狀態無法確認: {transfer['status']}")

        # 檢查是否過期
        if transfer['expires_at'] and datetime.fromisoformat(transfer['expires_at']) < datetime.now():
            raise HTTPException(status_code=400, detail="移轉已過期")

        cursor.execute("BEGIN TRANSACTION")

        # 入帳目的方
        if transfer['to_type'] == 'CART' and transfer['to_cart_id']:
            cursor.execute("""
                UPDATE cart_inventory
                SET quantity = quantity + ?, updated_at = ?
                WHERE cart_id = ? AND medicine_code = ?
            """, (transfer['quantity'], datetime.now().isoformat(),
                  transfer['to_cart_id'], transfer['medicine_code']))

            # 記錄入帳交易
            txn_id = f"CITXN-XFERIN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
            cursor.execute("""
                INSERT INTO cart_inventory_transactions (
                    txn_id, txn_type, cart_id, medicine_code,
                    quantity_change, quantity_before, quantity_after,
                    source_type, source_id, actor_id, remarks
                ) VALUES (?, 'TRANSFER_IN', ?, ?, ?, 0, 0, 'TRANSFER', ?, ?, ?)
            """, (txn_id, transfer['to_cart_id'], transfer['medicine_code'],
                  transfer['quantity'], transfer_id, actor_id,
                  f"Transfer from {transfer['from_case_id'] or transfer['from_cart_id']}"))

        # 更新移轉狀態
        cursor.execute("""
            UPDATE drug_transfers
            SET status = 'CONFIRMED', to_confirmed = 1, to_confirmed_at = ?, completed_at = ?
            WHERE transfer_id = ?
        """, (datetime.now().isoformat(), datetime.now().isoformat(), transfer_id))

        # 更新通知
        cursor.execute("""
            INSERT INTO transfer_notifications (
                transfer_id, target_nurse_id, target_type, notification_type
            ) VALUES (?, ?, 'SENDER', 'TRANSFER_CONFIRMED')
        """, (transfer_id, transfer['from_nurse_id']))

        conn.commit()

        return {
            "transfer_id": transfer_id,
            "status": "CONFIRMED",
            "message": "移轉已確認，藥品已入帳"
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/transfers/{transfer_id}/reject")
async def reject_transfer(
    transfer_id: str,
    actor_id: str = Query(...),
    reason: str = Query(..., description="拒絕原因")
):
    """
    接收方拒絕移轉

    v1.1: 回補來源庫存 (Immediate Debit Reversal)
    """
    if IS_VERCEL:
        return {
            "transfer_id": transfer_id,
            "status": "REJECTED",
            "reason": reason,
            "message": "移轉已拒絕，來源庫存已回補",
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM drug_transfers WHERE transfer_id = ?", (transfer_id,))
        transfer = cursor.fetchone()

        if not transfer:
            raise HTTPException(status_code=404, detail="移轉記錄不存在")

        if transfer['status'] != 'PENDING':
            raise HTTPException(status_code=400, detail=f"移轉狀態無法拒絕: {transfer['status']}")

        cursor.execute("BEGIN TRANSACTION")

        # v1.1: 回補來源庫存
        if transfer['from_type'] == 'CART' and transfer['from_cart_id']:
            cursor.execute("""
                UPDATE cart_inventory
                SET quantity = quantity + ?, updated_at = ?
                WHERE cart_id = ? AND medicine_code = ?
            """, (transfer['quantity'], datetime.now().isoformat(),
                  transfer['from_cart_id'], transfer['medicine_code']))

            # 記錄回補交易
            txn_id = f"CITXN-XFERREV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
            cursor.execute("""
                INSERT INTO cart_inventory_transactions (
                    txn_id, txn_type, cart_id, medicine_code,
                    quantity_change, quantity_before, quantity_after,
                    source_type, source_id, actor_id, remarks
                ) VALUES (?, 'TRANSFER_REVERSAL', ?, ?, ?, 0, 0, 'TRANSFER', ?, ?, ?)
            """, (txn_id, transfer['from_cart_id'], transfer['medicine_code'],
                  transfer['quantity'], transfer_id, actor_id,
                  f"Transfer rejected: {reason}"))

        # 更新移轉狀態
        cursor.execute("""
            UPDATE drug_transfers
            SET status = 'REJECTED', reject_reason = ?, completed_at = ?
            WHERE transfer_id = ?
        """, (reason, datetime.now().isoformat(), transfer_id))

        # 通知發起方
        cursor.execute("""
            INSERT INTO transfer_notifications (
                transfer_id, target_nurse_id, target_type, notification_type
            ) VALUES (?, ?, 'SENDER', 'TRANSFER_REJECTED')
        """, (transfer_id, transfer['from_nurse_id']))

        conn.commit()

        return {
            "transfer_id": transfer_id,
            "status": "REJECTED",
            "reason": reason,
            "message": "移轉已拒絕，來源庫存已回補"
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/transfers/{transfer_id}/cancel")
async def cancel_transfer(
    transfer_id: str,
    actor_id: str = Query(...)
):
    """
    發起方取消移轉 (僅 PENDING 狀態可取消)

    v1.1: 回補來源庫存
    """
    if IS_VERCEL:
        return {
            "transfer_id": transfer_id,
            "status": "CANCELLED",
            "message": "移轉已取消，來源庫存已回補",
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM drug_transfers WHERE transfer_id = ?", (transfer_id,))
        transfer = cursor.fetchone()

        if not transfer:
            raise HTTPException(status_code=404, detail="移轉記錄不存在")

        if transfer['status'] != 'PENDING':
            raise HTTPException(status_code=400, detail="只能取消 PENDING 狀態的移轉")

        if transfer['from_nurse_id'] != actor_id:
            raise HTTPException(status_code=403, detail="只有發起人可以取消移轉")

        cursor.execute("BEGIN TRANSACTION")

        # 回補來源庫存
        if transfer['from_type'] == 'CART' and transfer['from_cart_id']:
            cursor.execute("""
                UPDATE cart_inventory
                SET quantity = quantity + ?, updated_at = ?
                WHERE cart_id = ? AND medicine_code = ?
            """, (transfer['quantity'], datetime.now().isoformat(),
                  transfer['from_cart_id'], transfer['medicine_code']))

            txn_id = f"CITXN-XFERCAN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
            cursor.execute("""
                INSERT INTO cart_inventory_transactions (
                    txn_id, txn_type, cart_id, medicine_code,
                    quantity_change, quantity_before, quantity_after,
                    source_type, source_id, actor_id, remarks
                ) VALUES (?, 'TRANSFER_REVERSAL', ?, ?, ?, 0, 0, 'TRANSFER', ?, ?, 'Transfer cancelled by sender')
            """, (txn_id, transfer['from_cart_id'], transfer['medicine_code'],
                  transfer['quantity'], transfer_id, actor_id))

        cursor.execute("""
            UPDATE drug_transfers
            SET status = 'CANCELLED', completed_at = ?
            WHERE transfer_id = ?
        """, (datetime.now().isoformat(), transfer_id))

        conn.commit()

        return {
            "transfer_id": transfer_id,
            "status": "CANCELLED",
            "message": "移轉已取消，來源庫存已回補"
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/transfers")
async def list_transfers(
    case_id: Optional[str] = None,
    cart_id: Optional[str] = None,
    nurse_id: Optional[str] = None,
    status: Optional[str] = None,
    direction: Optional[str] = Query(None, description="IN, OUT, ALL"),
    limit: int = Query(50, ge=1, le=200)
):
    """查詢移轉記錄"""
    if IS_VERCEL:
        demo_transfers = [
            {
                "transfer_id": "XFER-DEMO-001",
                "transfer_code": "XFER-7A3B",
                "transfer_type": "CASE_TO_CASE",
                "from_nurse_name": "張小華",
                "to_nurse_name": "李小美",
                "medicine_name": "Fentanyl 100mcg/2mL",
                "quantity": 1,
                "is_controlled": True,
                "status": "CONFIRMED",
                "initiated_at": (datetime.now() - timedelta(hours=1)).isoformat()
            }
        ]
        return {"transfers": demo_transfers, "total": len(demo_transfers)}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        query = "SELECT * FROM drug_transfers WHERE 1=1"
        params = []

        if case_id:
            if direction == 'IN':
                query += " AND to_case_id = ?"
            elif direction == 'OUT':
                query += " AND from_case_id = ?"
            else:
                query += " AND (from_case_id = ? OR to_case_id = ?)"
                params.append(case_id)
            params.append(case_id)

        if cart_id:
            if direction == 'IN':
                query += " AND to_cart_id = ?"
            elif direction == 'OUT':
                query += " AND from_cart_id = ?"
            else:
                query += " AND (from_cart_id = ? OR to_cart_id = ?)"
                params.append(cart_id)
            params.append(cart_id)

        if nurse_id:
            query += " AND (from_nurse_id = ? OR to_nurse_id = ?)"
            params.extend([nurse_id, nurse_id])

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY initiated_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        transfers = [dict(row) for row in cursor.fetchall()]

        return {"transfers": transfers, "total": len(transfers)}

    finally:
        conn.close()


@router.get("/transfers/pending")
async def get_pending_transfers(nurse_id: str = Query(...)):
    """取得待處理的移轉 (for 通知 badge)"""
    if IS_VERCEL:
        return {
            "incoming": [
                {
                    "transfer_id": "XFER-DEMO-002",
                    "from_nurse_name": "王小華",
                    "medicine_name": "Midazolam 5mg/mL",
                    "quantity": 1,
                    "initiated_at": datetime.now().isoformat()
                }
            ],
            "outgoing": [],
            "total_pending": 1,
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 待接收
        cursor.execute("""
            SELECT * FROM drug_transfers
            WHERE to_nurse_id = ? AND status = 'PENDING'
            ORDER BY initiated_at DESC
        """, (nurse_id,))
        incoming = [dict(row) for row in cursor.fetchall()]

        # 待對方確認
        cursor.execute("""
            SELECT * FROM drug_transfers
            WHERE from_nurse_id = ? AND status = 'PENDING'
            ORDER BY initiated_at DESC
        """, (nurse_id,))
        outgoing = [dict(row) for row in cursor.fetchall()]

        return {
            "incoming": incoming,
            "outgoing": outgoing,
            "total_pending": len(incoming) + len(outgoing)
        }

    finally:
        conn.close()


@router.get("/transfers/by-code/{code}")
async def get_transfer_by_code(code: str):
    """
    透過短代碼查詢移轉 (iOS 用)

    code 格式: XFER-7A3B
    """
    if IS_VERCEL:
        if code.upper().startswith("XFER-"):
            return {
                "transfer_id": "XFER-DEMO-001",
                "transfer_code": code.upper(),
                "transfer_type": "CASE_TO_CASE",
                "from_nurse_name": "張小華",
                "from_case_id": "ANES-DEMO-001",
                "medicine_code": "FENT",
                "medicine_name": "Fentanyl 100mcg/2mL",
                "quantity": 1,
                "is_controlled": True,
                "witness_name": "陳護理師",
                "status": "PENDING",
                "expires_at": (datetime.now() + timedelta(minutes=3)).isoformat(),
                "demo_mode": True
            }
        raise HTTPException(status_code=404, detail="移轉代碼不存在")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM drug_transfers
            WHERE transfer_code = ? AND status = 'PENDING'
        """, (code.upper(),))
        transfer = cursor.fetchone()

        if not transfer:
            raise HTTPException(status_code=404, detail="移轉代碼不存在或已過期")

        # 檢查是否過期
        if transfer['expires_at'] and datetime.fromisoformat(transfer['expires_at']) < datetime.now():
            raise HTTPException(status_code=400, detail="移轉代碼已過期")

        return dict(transfer)

    finally:
        conn.close()


@router.get("/transfers/{transfer_id}")
async def get_transfer(transfer_id: str):
    """取得移轉詳情"""
    if IS_VERCEL:
        return {
            "transfer_id": transfer_id,
            "transfer_type": "CASE_TO_CASE",
            "status": "PENDING",
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM drug_transfers WHERE transfer_id = ?", (transfer_id,))
        transfer = cursor.fetchone()

        if not transfer:
            raise HTTPException(status_code=404, detail="移轉記錄不存在")

        return dict(transfer)

    finally:
        conn.close()


# --- Cart Assignment APIs ---
@router.get("/carts/available")
async def get_available_carts(or_room: str = Query(None)):
    """取得可用藥車"""
    if IS_VERCEL:
        return {
            "primary_cart": {"cart_id": f"CART-{or_room or 'OR-01'}", "name": f"{or_room or 'OR-01'} 藥車"},
            "mobile_carts": [
                {"cart_id": "CART-MOBILE-01", "name": "流動藥車 #1", "location": "Storage"}
            ]
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        primary_cart = None
        if or_room:
            cursor.execute("""
                SELECT * FROM drug_carts
                WHERE assigned_or = ? AND status = 'ACTIVE'
            """, (or_room,))
            row = cursor.fetchone()
            if row:
                primary_cart = dict(row)

        cursor.execute("""
            SELECT * FROM drug_carts
            WHERE cart_type = 'MOBILE' AND status = 'ACTIVE'
            AND (current_nurse_id IS NULL OR current_nurse_id = '')
        """)
        mobile_carts = [dict(row) for row in cursor.fetchall()]

        return {
            "primary_cart": primary_cart,
            "mobile_carts": mobile_carts
        }

    finally:
        conn.close()


@router.post("/carts/{cart_id}/assign")
async def assign_cart_to_nurse(
    cart_id: str,
    nurse_id: str = Query(...),
    nurse_name: str = Query(None)
):
    """將藥車指派給護理師"""
    if IS_VERCEL:
        return {"cart_id": cart_id, "nurse_id": nurse_id, "status": "assigned"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE drug_carts
            SET current_nurse_id = ?, updated_at = ?
            WHERE id = ?
        """, (nurse_id, datetime.now().isoformat(), cart_id))
        conn.commit()

        return {"cart_id": cart_id, "nurse_id": nurse_id, "status": "assigned"}

    finally:
        conn.close()


@router.post("/carts/{cart_id}/release")
async def release_cart(cart_id: str, nurse_id: str = Query(...)):
    """護理師釋放藥車"""
    if IS_VERCEL:
        return {"cart_id": cart_id, "status": "released"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE drug_carts
            SET current_nurse_id = NULL, updated_at = ?
            WHERE id = ? AND current_nurse_id = ?
        """, (datetime.now().isoformat(), cart_id, nurse_id))
        conn.commit()

        return {"cart_id": cart_id, "status": "released"}

    finally:
        conn.close()


# =============================================================================
# v2.1: IV Line Management (IV 管路管理)
# =============================================================================

@router.post("/cases/{case_id}/iv-lines")
async def insert_iv_line(case_id: str, req: InsertIVLineRequest, actor_id: str = Query(...)):
    """
    插入 IV 管路

    POST /api/anesthesia/cases/{case_id}/iv-lines
    """
    if IS_VERCEL:
        line_id = f"IV-{uuid.uuid4().hex[:8].upper()}"
        return {
            "line_id": line_id,
            "line_number": 1,
            "site": req.site,
            "gauge": req.gauge,
            "inserted_at": datetime.now().isoformat(),
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 驗證 case 存在
        cursor.execute("SELECT id, status FROM anesthesia_cases WHERE id = ?", (case_id,))
        case = cursor.fetchone()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # 取得下一個 line_number
        cursor.execute("SELECT COALESCE(MAX(line_number), 0) + 1 FROM anesthesia_iv_lines WHERE case_id = ?", (case_id,))
        line_number = cursor.fetchone()[0]

        line_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        # 插入 IV line
        cursor.execute("""
            INSERT INTO anesthesia_iv_lines (line_id, case_id, line_number, site, gauge, catheter_type,
                                             inserted_at, inserted_by, current_rate_ml_hr, current_fluid_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (line_id, case_id, line_number, req.site, req.gauge, req.catheter_type,
              now, actor_id, req.rate_ml_hr or 0, req.initial_fluid))

        # 記錄事件
        event_id = str(uuid.uuid4())
        payload = {
            "line_id": line_id,
            "site": req.site,
            "gauge": req.gauge,
            "catheter_type": req.catheter_type,
            "initial_fluid": req.initial_fluid,
            "rate_ml_hr": req.rate_ml_hr
        }
        cursor.execute("""
            INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, case_id, "IV_LINE_INSERTED", now, json.dumps(payload), actor_id))

        conn.commit()

        return {
            "line_id": line_id,
            "line_number": line_number,
            "site": req.site,
            "gauge": req.gauge,
            "inserted_at": now
        }

    finally:
        conn.close()


@router.get("/cases/{case_id}/iv-lines")
async def get_iv_lines(case_id: str, include_removed: bool = False):
    """取得案例的 IV 管路列表"""
    if IS_VERCEL:
        return {"iv_lines": [
            {"line_id": "IV-DEMO-001", "line_number": 1, "site": "右手背", "gauge": "20G", "catheter_type": "PERIPHERAL", "current_rate_ml_hr": 100, "current_fluid_type": "N/S", "total_volume_ml": 500, "inserted_at": datetime.now().isoformat()},
        ], "demo_mode": True}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        if include_removed:
            cursor.execute("SELECT * FROM anesthesia_iv_lines WHERE case_id = ? ORDER BY line_number", (case_id,))
        else:
            cursor.execute("SELECT * FROM anesthesia_iv_lines WHERE case_id = ? AND removed_at IS NULL ORDER BY line_number", (case_id,))

        lines = [dict(row) for row in cursor.fetchall()]
        return {"iv_lines": lines}

    finally:
        conn.close()


@router.patch("/cases/{case_id}/iv-lines/{line_id}")
async def update_iv_line(case_id: str, line_id: str, req: UpdateIVLineRequest, actor_id: str = Query(...)):
    """
    更新 IV 管路 (調整滴速或移除)

    PATCH /api/anesthesia/cases/{case_id}/iv-lines/{line_id}
    """
    if IS_VERCEL:
        return {"success": True, "line_id": line_id, "demo_mode": True}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 驗證 line 存在
        cursor.execute("SELECT * FROM anesthesia_iv_lines WHERE line_id = ? AND case_id = ?", (line_id, case_id))
        line = cursor.fetchone()
        if not line:
            raise HTTPException(status_code=404, detail="IV line not found")

        now = datetime.now().isoformat()

        if req.removed:
            # 移除管路
            cursor.execute("""
                UPDATE anesthesia_iv_lines SET removed_at = ?, removed_by = ? WHERE line_id = ?
            """, (now, actor_id, line_id))

            event_id = str(uuid.uuid4())
            payload = {"line_id": line_id, "site": line["site"]}
            cursor.execute("""
                INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_id, case_id, "IV_LINE_REMOVED", now, json.dumps(payload), actor_id))

        elif req.rate_ml_hr is not None:
            # 調整滴速
            old_rate = line["current_rate_ml_hr"]
            cursor.execute("""
                UPDATE anesthesia_iv_lines SET current_rate_ml_hr = ? WHERE line_id = ?
            """, (req.rate_ml_hr, line_id))

            event_id = str(uuid.uuid4())
            payload = {"line_id": line_id, "old_rate": old_rate, "new_rate": req.rate_ml_hr}
            cursor.execute("""
                INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_id, case_id, "IV_RATE_CHANGED", now, json.dumps(payload), actor_id))

        conn.commit()
        return {"success": True, "line_id": line_id}

    finally:
        conn.close()


@router.post("/cases/{case_id}/iv-lines/{line_id}/fluids")
async def give_iv_fluid(case_id: str, line_id: str, req: GiveIVFluidRequest, actor_id: str = Query(...)):
    """
    經 IV 給予輸液

    POST /api/anesthesia/cases/{case_id}/iv-lines/{line_id}/fluids
    """
    if IS_VERCEL:
        return {
            "success": True,
            "line_id": line_id,
            "fluid_type": req.fluid_type,
            "amount_ml": req.amount_ml,
            "cumulative_ml": req.amount_ml + 500,
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 驗證 line 存在且未移除
        cursor.execute("SELECT * FROM anesthesia_iv_lines WHERE line_id = ? AND case_id = ? AND removed_at IS NULL", (line_id, case_id))
        line = cursor.fetchone()
        if not line:
            raise HTTPException(status_code=404, detail="Active IV line not found")

        now = datetime.now().isoformat()

        # 更新累計量
        new_total = (line["total_volume_ml"] or 0) + req.amount_ml
        cursor.execute("""
            UPDATE anesthesia_iv_lines SET total_volume_ml = ?, current_fluid_type = ? WHERE line_id = ?
        """, (new_total, req.fluid_type, line_id))

        # 記錄事件
        event_id = str(uuid.uuid4())
        payload = {
            "line_id": line_id,
            "fluid_type": req.fluid_type,
            "amount_ml": req.amount_ml,
            "is_bolus": req.is_bolus,
            "cumulative_ml": new_total
        }
        cursor.execute("""
            INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, case_id, "IV_FLUID_GIVEN", now, json.dumps(payload), actor_id))

        conn.commit()

        return {
            "success": True,
            "line_id": line_id,
            "fluid_type": req.fluid_type,
            "amount_ml": req.amount_ml,
            "cumulative_ml": new_total
        }

    finally:
        conn.close()


# =============================================================================
# v2.1: Monitor Management (監測器管理 - Foley, 保溫毯等)
# =============================================================================

@router.post("/cases/{case_id}/monitors")
async def start_monitor(case_id: str, req: StartMonitorRequest, actor_id: str = Query(...)):
    """
    啟動監測器

    POST /api/anesthesia/cases/{case_id}/monitors
    """
    if IS_VERCEL:
        monitor_id = f"MON-{uuid.uuid4().hex[:8].upper()}"
        return {
            "monitor_id": monitor_id,
            "monitor_type": req.monitor_type,
            "started_at": datetime.now().isoformat(),
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 驗證 case 存在
        cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Case not found")

        monitor_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO anesthesia_monitors (monitor_id, case_id, monitor_type, settings, started_at, started_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (monitor_id, case_id, req.monitor_type, json.dumps(req.settings) if req.settings else None,
              now, actor_id, req.notes))

        # 記錄事件
        event_id = str(uuid.uuid4())
        payload = {
            "monitor_id": monitor_id,
            "monitor_type": req.monitor_type,
            "settings": req.settings
        }
        cursor.execute("""
            INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, case_id, "MONITOR_STARTED", now, json.dumps(payload), actor_id))

        conn.commit()

        return {
            "monitor_id": monitor_id,
            "monitor_type": req.monitor_type,
            "started_at": now
        }

    finally:
        conn.close()


@router.get("/cases/{case_id}/monitors")
async def get_monitors(case_id: str, include_stopped: bool = False):
    """取得案例的監測器列表"""
    if IS_VERCEL:
        return {"monitors": [
            {"monitor_id": "MON-DEMO-001", "monitor_type": "EKG", "started_at": datetime.now().isoformat()},
            {"monitor_id": "MON-DEMO-002", "monitor_type": "SPO2", "started_at": datetime.now().isoformat()},
            {"monitor_id": "MON-DEMO-003", "monitor_type": "NIBP", "started_at": datetime.now().isoformat()},
        ], "demo_mode": True}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        if include_stopped:
            cursor.execute("SELECT * FROM anesthesia_monitors WHERE case_id = ? ORDER BY started_at", (case_id,))
        else:
            cursor.execute("SELECT * FROM anesthesia_monitors WHERE case_id = ? AND stopped_at IS NULL ORDER BY started_at", (case_id,))

        monitors = []
        for row in cursor.fetchall():
            m = dict(row)
            if m.get("settings"):
                m["settings"] = json.loads(m["settings"])

            # 如果是 Foley，取得尿量記錄
            if m["monitor_type"] == "FOLEY":
                cursor.execute("""
                    SELECT SUM(amount_ml) as total_urine FROM anesthesia_urine_outputs WHERE monitor_id = ?
                """, (m["monitor_id"],))
                urine_row = cursor.fetchone()
                m["total_urine_ml"] = urine_row["total_urine"] or 0 if urine_row else 0

            monitors.append(m)

        return {"monitors": monitors}

    finally:
        conn.close()


@router.delete("/cases/{case_id}/monitors/{monitor_id}")
async def stop_monitor(case_id: str, monitor_id: str, actor_id: str = Query(...)):
    """
    停止監測器

    DELETE /api/anesthesia/cases/{case_id}/monitors/{monitor_id}
    """
    if IS_VERCEL:
        return {"success": True, "monitor_id": monitor_id, "stopped_at": datetime.now().isoformat(), "demo_mode": True}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM anesthesia_monitors WHERE monitor_id = ? AND case_id = ?", (monitor_id, case_id))
        monitor = cursor.fetchone()
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")

        now = datetime.now().isoformat()

        cursor.execute("""
            UPDATE anesthesia_monitors SET stopped_at = ?, stopped_by = ? WHERE monitor_id = ?
        """, (now, actor_id, monitor_id))

        # 記錄事件
        event_id = str(uuid.uuid4())
        payload = {"monitor_id": monitor_id, "monitor_type": monitor["monitor_type"]}
        cursor.execute("""
            INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, case_id, "MONITOR_STOPPED", now, json.dumps(payload), actor_id))

        conn.commit()
        return {"success": True, "monitor_id": monitor_id, "stopped_at": now}

    finally:
        conn.close()


@router.post("/cases/{case_id}/urine-output")
async def record_urine_output(case_id: str, req: RecordUrineOutputRequest, actor_id: str = Query(...)):
    """
    記錄尿量 (需要有 Foley 監測器)

    POST /api/anesthesia/cases/{case_id}/urine-output
    """
    if IS_VERCEL:
        return {
            "success": True,
            "amount_ml": req.amount_ml,
            "cumulative_ml": req.amount_ml + 200,
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 找到活躍的 Foley 監測器
        cursor.execute("""
            SELECT monitor_id FROM anesthesia_monitors
            WHERE case_id = ? AND monitor_type = 'FOLEY' AND stopped_at IS NULL
        """, (case_id,))
        foley = cursor.fetchone()
        if not foley:
            raise HTTPException(status_code=400, detail="No active Foley catheter found")

        monitor_id = foley["monitor_id"]
        now = datetime.now().isoformat()

        # 計算累計尿量
        cursor.execute("SELECT COALESCE(SUM(amount_ml), 0) FROM anesthesia_urine_outputs WHERE case_id = ?", (case_id,))
        prev_total = cursor.fetchone()[0]
        cumulative = prev_total + req.amount_ml

        # 插入尿量記錄
        record_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO anesthesia_urine_outputs (id, case_id, monitor_id, amount_ml, recorded_at, recorded_by, cumulative_ml)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (record_id, case_id, monitor_id, req.amount_ml, now, actor_id, cumulative))

        # 記錄事件
        event_id = str(uuid.uuid4())
        payload = {"amount_ml": req.amount_ml, "cumulative_ml": cumulative}
        cursor.execute("""
            INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, case_id, "URINE_OUTPUT", now, json.dumps(payload), actor_id))

        conn.commit()

        return {
            "success": True,
            "amount_ml": req.amount_ml,
            "cumulative_ml": cumulative
        }

    finally:
        conn.close()


# =============================================================================
# v2.1: Time Out
# =============================================================================

@router.post("/cases/{case_id}/timeout")
async def complete_timeout(case_id: str, req: TimeOutRequest, actor_id: str = Query(...)):
    """
    完成 Time Out 核對

    POST /api/anesthesia/cases/{case_id}/timeout
    """
    if IS_VERCEL:
        return {"success": True, "completed_at": datetime.now().isoformat(), "demo_mode": True}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM anesthesia_cases WHERE id = ?", (case_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Case not found")

        now = datetime.now().isoformat()

        # 記錄事件
        event_id = str(uuid.uuid4())
        payload = {
            "patient_id_confirmed": req.patient_id_confirmed,
            "procedure_confirmed": req.procedure_confirmed,
            "consent_confirmed": req.consent_confirmed,
            "allergies_confirmed": req.allergies_confirmed,
            "equipment_ready": req.equipment_ready,
            "notes": req.notes
        }
        cursor.execute("""
            INSERT INTO anesthesia_events (id, case_id, event_type, clinical_time, payload, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, case_id, "TIMEOUT_COMPLETED", now, json.dumps(payload), actor_id))

        conn.commit()

        return {"success": True, "completed_at": now}

    finally:
        conn.close()


# =============================================================================
# v2.1: I/O Balance Calculation
# =============================================================================

@router.get("/cases/{case_id}/io-balance")
async def get_io_balance(case_id: str):
    """
    取得 I/O Balance (輸入/輸出平衡)

    GET /api/anesthesia/cases/{case_id}/io-balance
    """
    if IS_VERCEL:
        return {
            "input": {
                "crystalloid_ml": 1000,
                "colloid_ml": 0,
                "blood_ml": 0,
                "total_ml": 1000
            },
            "output": {
                "urine_ml": 300,
                "blood_loss_ml": 100,
                "total_ml": 400
            },
            "balance_ml": 600,
            "demo_mode": True
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 取得所有相關事件
        cursor.execute("""
            SELECT event_type, payload FROM anesthesia_events
            WHERE case_id = ? AND event_type IN ('IV_FLUID_GIVEN', 'FLUID_IN', 'FLUID_BOLUS', 'BLOOD_PRODUCT', 'FLUID_OUT', 'URINE_OUTPUT')
            ORDER BY clinical_time
        """, (case_id,))

        events = cursor.fetchall()

        # 分類計算
        input_crystalloid = 0
        input_colloid = 0
        input_blood = 0
        output_urine = 0
        output_blood_loss = 0

        crystalloid_types = ['N/S', 'NS', 'L/R', 'LR', 'D5W', 'D5S', 'RINGER', 'LACTATED RINGER']
        colloid_types = ['ALBUMIN', 'VOLUVEN', 'HETASTARCH', 'DEXTRAN', 'GELATIN']
        blood_types = ['PRBC', 'pRBC', 'FFP', 'PLATELET', 'CRYOPRECIPITATE', 'WHOLE BLOOD']

        for event in events:
            payload = json.loads(event["payload"]) if event["payload"] else {}
            event_type = event["event_type"]

            if event_type in ('IV_FLUID_GIVEN', 'FLUID_IN', 'FLUID_BOLUS'):
                fluid_type = (payload.get("fluid_type") or "").upper()
                amount = payload.get("amount_ml") or payload.get("volume") or 0

                if any(t in fluid_type for t in blood_types):
                    input_blood += amount
                elif any(t in fluid_type for t in colloid_types):
                    input_colloid += amount
                else:
                    input_crystalloid += amount

            elif event_type == 'BLOOD_PRODUCT':
                amount = payload.get("volume_ml") or payload.get("amount_ml") or 0
                input_blood += amount

            elif event_type == 'URINE_OUTPUT':
                amount = payload.get("amount_ml") or 0
                output_urine += amount

            elif event_type == 'FLUID_OUT':
                amount = payload.get("volume_ml") or payload.get("amount_ml") or 0
                fluid_type = (payload.get("type") or "").upper()
                if 'BLOOD' in fluid_type or 'EBL' in fluid_type:
                    output_blood_loss += amount
                else:
                    # Other fluid out (drain, etc.) - count as blood loss for simplicity
                    output_blood_loss += amount

        total_input = input_crystalloid + input_colloid + input_blood
        total_output = output_urine + output_blood_loss
        balance = total_input - total_output

        return {
            "input": {
                "crystalloid_ml": input_crystalloid,
                "colloid_ml": input_colloid,
                "blood_ml": input_blood,
                "total_ml": total_input
            },
            "output": {
                "urine_ml": output_urine,
                "blood_loss_ml": output_blood_loss,
                "total_ml": total_output
            },
            "balance_ml": balance
        }

    finally:
        conn.close()


# =============================================================================
# v2.1: PDF Generation (M0073 Anesthesia Record)
# =============================================================================

VITALS_PER_PAGE = 24  # M0073 form has ~24-30 time columns; use 24 for readability


def _generate_vitals_chart(vitals: List[Dict], page_start: int, page_end: int) -> str:
    """
    Generate Matplotlib chart for BP/HR trends.
    Returns base64-encoded PNG image.

    Chart is designed to align with vitals table below:
    - Table has fixed 28px row-header + equal-width data columns
    - Chart uses same structure: Y-axis area + data area
    - Data points centered in each column
    - No X-axis labels (table shows time below)
    """
    if not PDF_ENABLED:
        return ""

    page_vitals = vitals[page_start:page_end]
    if not page_vitals:
        return ""

    n_cols = len(page_vitals)

    # Extract data - X position at column center (0.5, 1.5, 2.5, ...)
    x_positions = []
    sbp_values = []
    dbp_values = []
    hr_values = []

    for i, v in enumerate(page_vitals):
        x_positions.append(i + 0.5)  # Center of each column
        sbp_values.append(v.get('sbp') or None)
        dbp_values.append(v.get('dbp') or None)
        hr_values.append(v.get('hr') or None)

    # Create figure - wide aspect ratio to match table width
    fig_width = 12  # Wide figure for better resolution
    fig_height = 1.8
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=150)

    # Set X-axis to match table columns (0 to n_cols)
    ax.set_xlim(0, n_cols)
    ax.set_ylim(0, 200)

    # Plot BP (red/blue) and HR (green) with data points at column centers
    if any(v is not None for v in sbp_values):
        ax.plot(x_positions, sbp_values, 'r-', marker='o', markersize=4, linewidth=1.2, label='SBP')
    if any(v is not None for v in dbp_values):
        ax.plot(x_positions, dbp_values, 'b-', marker='o', markersize=4, linewidth=1.2, label='DBP')
    if any(v is not None for v in hr_values):
        ax.plot(x_positions, hr_values, 'g--', marker='s', markersize=4, linewidth=1.2, label='HR')

    # Vertical grid lines at column boundaries for alignment reference
    for i in range(n_cols + 1):
        ax.axvline(x=i, color='#e0e0e0', linestyle='-', linewidth=0.3)

    # Horizontal grid lines at Y values
    for y in [50, 100, 150]:
        ax.axhline(y=y, color='#e0e0e0', linestyle='-', linewidth=0.3)
    ax.axhline(y=100, color='#ccc', linestyle='--', linewidth=0.5)  # 100 reference line

    # Remove X-axis completely (table shows time)
    ax.set_xticks([])
    ax.set_xticklabels([])
    ax.tick_params(axis='x', length=0)

    # Y-axis: show ticks inside the plot area
    ax.set_yticks([50, 100, 150, 200])
    ax.tick_params(axis='y', labelsize=8, direction='in', pad=-22)
    ax.yaxis.set_tick_params(labelleft=True)

    # Remove Y-axis label (external label in HTML)
    ax.set_ylabel('')

    # Remove spines for cleaner look
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_linewidth(0.5)
    ax.spines['left'].set_linewidth(0.5)

    # Legend inside the plot area, upper right
    ax.legend(fontsize=8, loc='upper right', framealpha=0.9, edgecolor='none')

    # Zero margins - Y-axis label is external (in HTML wrapper)
    # This makes the chart data area align with table data columns
    plt.subplots_adjust(left=0.001, right=0.999, top=0.95, bottom=0.02)

    # Convert to base64 PNG
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=150, facecolor='#fafafa', edgecolor='none')
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')


def _rebuild_state_from_events(events: List[Dict]) -> Dict:
    """
    Pure function: Rebuild complete case state from events.
    This is the core of event sourcing - PDF = f(events)
    """
    state = {
        "vitals": [],
        "drugs": [],
        "iv_lines": [],
        "monitors": [],
        "vent_settings": [],      # 呼吸器設定
        "agent_settings": [],     # 吸入麻醉劑設定
        "lab_data": [],           # 實驗室數據
        "patient": {},
        "surgery": {},
        "technique": None,
        "times": {},
        "io_balance": {
            "input": {"crystalloid_ml": 0, "colloid_ml": 0, "blood_ml": 0, "total_ml": 0},
            "output": {"urine_ml": 0, "blood_loss_ml": 0, "total_ml": 0},
            "balance_ml": 0
        },
        "anesthesiologist": None,
        "nurse": None
    }

    crystalloid_types = ['N/S', 'NS', 'L/R', 'LR', 'D5W', 'D5S', 'RINGER', 'LACTATED']
    colloid_types = ['ALBUMIN', 'VOLUVEN', 'HETASTARCH', 'DEXTRAN', 'GELATIN']
    blood_types = ['PRBC', 'pRBC', 'FFP', 'PLATELET', 'CRYOPRECIPITATE', 'WHOLE BLOOD']

    for event in events:
        event_type = event.get("event_type", "")
        payload = json.loads(event["payload"]) if event.get("payload") else {}
        clinical_time = event.get("clinical_time", "")

        # Vitals (支援 VITAL_SIGN 和 VITAL_SIGNS)
        if event_type in ("VITAL_SIGN", "VITAL_SIGNS"):
            state["vitals"].append({
                "time": clinical_time,
                "sbp": payload.get("sbp") or payload.get("bp_sys"),
                "dbp": payload.get("dbp") or payload.get("bp_dia"),
                "hr": payload.get("hr"),
                "spo2": payload.get("spo2"),
                "etco2": payload.get("etco2"),
                "rr": payload.get("rr"),
                "temp": payload.get("temp"),
                "fio2": payload.get("fio2"),
                "mac": payload.get("mac"),
                "events": None
            })

        # Drug Administration (支援多種事件類型)
        elif event_type in ("DRUG_GIVEN", "DRUG_DRAW", "MEDICATION_ADMIN"):
            state["drugs"].append({
                "time": clinical_time,
                "name": payload.get("drug_name") or payload.get("drug"),
                "dose": f"{payload.get('amount', payload.get('dose', ''))} {payload.get('unit', '')}".strip(),
                "route": payload.get("route", "IV")
            })

        # IV Lines (支援 IV_ACCESS 和 IV_LINE_INSERTED)
        elif event_type in ("IV_LINE_INSERTED", "IV_ACCESS"):
            state["iv_lines"].append({
                "line_number": len(state["iv_lines"]) + 1,
                "site": payload.get("site"),
                "gauge": payload.get("gauge"),
                "catheter_type": payload.get("catheter_type", "PERIPHERAL")
            })

        # IV Fluids (支援 FLUID_IN, IV_FLUID_GIVEN, FLUID_BOLUS)
        elif event_type in ("IV_FLUID_GIVEN", "FLUID_IN", "FLUID_BOLUS"):
            fluid_type = (payload.get("fluid_type") or payload.get("type") or "").upper()
            # 支援多種欄位名稱: volume_ml, amount_ml, volume, amount
            amount = payload.get("volume_ml") or payload.get("amount_ml") or payload.get("volume") or payload.get("amount", 0)
            if any(t in fluid_type for t in blood_types):
                state["io_balance"]["input"]["blood_ml"] += amount
            elif any(t in fluid_type for t in colloid_types):
                state["io_balance"]["input"]["colloid_ml"] += amount
            else:
                state["io_balance"]["input"]["crystalloid_ml"] += amount

        # Blood Products
        elif event_type == "BLOOD_PRODUCT":
            amount = payload.get("volume_ml") or payload.get("amount_ml", 0)
            state["io_balance"]["input"]["blood_ml"] += amount

        # Urine Output / Blood Loss (支援 OUTPUT 和 URINE_OUTPUT)
        elif event_type in ("URINE_OUTPUT", "OUTPUT"):
            output_type = payload.get("output_type", "urine").lower()
            amount = payload.get("volume_ml") or payload.get("amount_ml") or payload.get("amount", 0)
            if "urine" in output_type:
                state["io_balance"]["output"]["urine_ml"] += amount
            elif "blood" in output_type:
                state["io_balance"]["output"]["blood_loss_ml"] += amount

        # Blood Loss (explicit)
        elif event_type == "FLUID_OUT":
            state["io_balance"]["output"]["blood_loss_ml"] += payload.get("volume_ml") or payload.get("amount_ml", 0)

        # Monitor Started (track Foley, etc.)
        elif event_type == "MONITOR_STARTED":
            state["monitors"].append({
                "type": payload.get("monitor_type"),
                "location": payload.get("location"),
                "started_at": clinical_time
            })

        # Ventilator Settings
        elif event_type == "VENT_SETTING_CHANGE":
            state["vent_settings"].append({
                "time": clinical_time,
                "mode": payload.get("mode"),
                "fio2": payload.get("fio2"),
                "peep": payload.get("peep"),
                "tv": payload.get("tv"),
                "rr": payload.get("rr")
            })

        # Agent/Gas Settings (Sevoflurane, Desflurane, O2, Air)
        elif event_type == "AGENT_SETTING":
            state["agent_settings"].append({
                "time": clinical_time,
                "o2_flow": payload.get("o2_flow"),
                "air_flow": payload.get("air_flow"),
                "sevo_percent": payload.get("sevo_percent"),
                "des_percent": payload.get("des_percent")
            })

        # Lab Results (ABG, CBC, etc.)
        elif event_type == "LAB_RESULT_POINT":
            state["lab_data"].append({
                "time": clinical_time,
                "hb": payload.get("hb"),
                "hct": payload.get("hct"),
                "ph": payload.get("ph"),
                "pco2": payload.get("pco2"),
                "po2": payload.get("po2"),
                "hco3": payload.get("hco3"),
                "be": payload.get("be"),
                "na": payload.get("na"),
                "k": payload.get("k"),
                "ca": payload.get("ca"),
                "glucose": payload.get("glucose")
            })

        # Timeline Events - extract HH:MM from ISO datetime
        elif event_type == "ANESTHESIA_START":
            if clinical_time and "T" in clinical_time:
                state["times"]["anesthesia_start"] = clinical_time.split("T")[1][:5]
            elif clinical_time:
                state["times"]["anesthesia_start"] = clinical_time[:5]
        elif event_type == "ANESTHESIA_END":
            if clinical_time and "T" in clinical_time:
                state["times"]["anesthesia_end"] = clinical_time.split("T")[1][:5]
            elif clinical_time:
                state["times"]["anesthesia_end"] = clinical_time[:5]
        elif event_type == "SURGERY_START":
            if clinical_time and "T" in clinical_time:
                state["times"]["surgery_start"] = clinical_time.split("T")[1][:5]
            elif clinical_time:
                state["times"]["surgery_start"] = clinical_time[:5]
        elif event_type == "SURGERY_END":
            if clinical_time and "T" in clinical_time:
                state["times"]["surgery_end"] = clinical_time.split("T")[1][:5]
            elif clinical_time:
                state["times"]["surgery_end"] = clinical_time[:5]

        # Technique
        elif event_type == "TECHNIQUE_SET":
            state["technique"] = payload.get("technique")

        # Staff Assignment
        elif event_type == "STAFF_ASSIGNED":
            role = payload.get("role", "").upper()
            name = payload.get("name") or payload.get("staff_name")
            if "ANESTHESIOLOGIST" in role or "DOCTOR" in role or "DR" in role:
                state["anesthesiologist"] = name
            elif "NURSE" in role or "RN" in role:
                state["nurse"] = name

    # Calculate I/O totals
    io_in = state["io_balance"]["input"]
    io_out = state["io_balance"]["output"]
    io_in["total_ml"] = io_in["crystalloid_ml"] + io_in["colloid_ml"] + io_in["blood_ml"]
    io_out["total_ml"] = io_out["urine_ml"] + io_out["blood_loss_ml"]
    state["io_balance"]["balance_ml"] = io_in["total_ml"] - io_out["total_ml"]

    return state


@router.get("/cases/{case_id}/pdf")
async def generate_pdf(
    case_id: str,
    preview: bool = Query(False, description="If true, return HTML preview instead of PDF"),
    hospital_name: str = Query("谷盺生技責任醫院", description="Hospital name for header"),
    hospital_address: str = Query("", description="Hospital address (optional)")
):
    """
    Generate PDF Anesthesia Record (M0073)

    GET /api/anesthesia/cases/{case_id}/pdf

    Pure function rendering: PDF = f(events)
    - Fetches all events for the case
    - Rebuilds state from events (event sourcing)
    - Generates Matplotlib chart for BP/HR trends (if available)
    - Renders Jinja2 HTML template
    - Converts to PDF with WeasyPrint (or returns HTML preview)
    - Auto-paginates when vitals > 24

    On Vercel: Only HTML preview is available (preview=True)
    On RPi5/Local: Full PDF generation with WeasyPrint
    """
    # Vercel always returns HTML preview (no WeasyPrint available)
    if IS_VERCEL:
        preview = True

    # Check dependencies based on mode
    if preview:
        # HTML preview only needs Jinja2
        if not JINJA2_ENABLED:
            raise HTTPException(
                status_code=503,
                detail="HTML preview not available. Install: pip install jinja2"
            )
    else:
        # PDF generation needs WeasyPrint + Matplotlib
        if not PDF_ENABLED:
            raise HTTPException(
                status_code=503,
                detail="PDF generation not available. Install: pip install weasyprint jinja2 matplotlib"
            )

    # Vercel Demo Mode: Generate demo preview based on case_id
    if IS_VERCEL:
        demo_cases = get_demo_anesthesia_cases()
        demo_case = next((c for c in demo_cases if c["id"] == case_id), None)
        if not demo_case:
            raise HTTPException(status_code=404, detail=f"Demo case not found: {case_id}")

        now = datetime.now()
        case_start = datetime.fromisoformat(demo_case["started_at"])

        # Build patient info from demo case
        patient_info = {
            "name": demo_case.get("patient_name", "未知"),
            "chart_no": demo_case.get("patient_id", ""),
            "gender": "男" if demo_case.get("patient_gender") == "M" else "女" if demo_case.get("patient_gender") == "F" else "",
            "age": str(demo_case.get("patient_age", "")),
            "weight": str(demo_case.get("patient_weight", "")),
            "height": str(demo_case.get("patient_height", "")),
            "blood_type": demo_case.get("blood_type", ""),
            "asa_class": demo_case.get("asa_class", "")
        }

        surgery_info = {
            "name": demo_case.get("operation", ""),
            "procedure": demo_case.get("operation", ""),
            "date": case_start.strftime("%Y-%m-%d"),
            "or_room": demo_case.get("or_room", "OR-01"),
            "surgeon": demo_case.get("surgeon_name", "")
        }

        # For complex case ANES-DEMO-006, use comprehensive events
        if case_id == "ANES-DEMO-006":
            demo_events = get_demo_complex_events(case_id, case_start)

            # Extract vitals from events
            vitals = []
            prev_hour = None
            for e in demo_events:
                if e["event_type"] == "VITAL_SIGN":
                    p = e["payload"]
                    t = datetime.fromisoformat(e["clinical_time"])
                    hour_str = t.strftime("%H")
                    show_hour = (hour_str != prev_hour)
                    prev_hour = hour_str
                    vitals.append({
                        "time_display": t.strftime("%H:%M"),
                        "hour": hour_str,
                        "minute": t.strftime("%M"),
                        "show_hour": show_hour,
                        "sbp": p.get("bp_sys", 0),
                        "dbp": p.get("bp_dia", 0),
                        "hr": p.get("hr", 0),
                        "spo2": p.get("spo2", 0),
                        "etco2": p.get("etco2", 0),
                        "rr": 12,
                        "temp": "36.5",
                        "fio2": "50%",
                        "mac": "1.0"
                    })

            # Extract drugs from events
            drugs = []
            for e in demo_events:
                if e["event_type"] == "MEDICATION_ADMIN":
                    p = e["payload"]
                    t = datetime.fromisoformat(e["clinical_time"])
                    drugs.append({
                        "time": t.strftime("%H:%M"),
                        "name": p.get("drug_name", ""),
                        "dose": f"{p.get('dose', '')} {p.get('unit', '')}",
                        "route": p.get("route", "IV")
                    })

            # Extract IV lines
            iv_lines = []
            line_num = 1
            for e in demo_events:
                if e["event_type"] == "IV_LINE_INSERTED":
                    p = e["payload"]
                    site_map = {"RIGHT_HAND": "右手背", "RIGHT_NECK": "右頸", "LEFT_WRIST": "左腕"}
                    iv_lines.append({
                        "line_number": line_num,
                        "site": site_map.get(p.get("site"), p.get("site", "")),
                        "gauge": f"{p.get('gauge', '')}G",
                        "catheter_type": p.get("catheter_type", "PERIPHERAL")
                    })
                    line_num += 1

            # Extract labs
            lab_data = []
            for e in demo_events:
                if e["event_type"] == "LAB_RESULT_POINT":
                    p = e["payload"]
                    t = e["clinical_time"]
                    lab_data.append({
                        "time": t,
                        "hb": p.get("hb"),
                        "hct": p.get("hct"),
                        "ph": p.get("ph"),
                        "po2": p.get("po2"),
                        "pco2": p.get("pco2"),
                        "hco3": p.get("hco3"),
                        "be": p.get("be"),
                        "na": p.get("na"),
                        "k": p.get("k"),
                        "ca": p.get("ca"),
                        "glucose": p.get("glucose")
                    })

            # Calculate I/O balance
            io_in = {"crystalloid_ml": 0, "colloid_ml": 0, "blood_ml": 0, "total_ml": 0}
            io_out = {"urine_ml": 0, "blood_loss_ml": 0, "total_ml": 0}
            for e in demo_events:
                if e["event_type"] == "FLUID_IN":
                    p = e["payload"]
                    fluid_type = p.get("fluid_type", "").upper()
                    vol = p.get("volume_ml", 0)
                    if fluid_type in ("NS", "LR", "D5W"):
                        io_in["crystalloid_ml"] += vol
                    elif fluid_type in ("VOLUVEN", "ALBUMIN"):
                        io_in["colloid_ml"] += vol
                elif e["event_type"] == "BLOOD_ADMIN" and e["payload"].get("action") == "COMPLETE":
                    io_in["blood_ml"] += 250  # approx per unit
                elif e["event_type"] == "URINE_OUTPUT":
                    io_out["urine_ml"] += e["payload"].get("volume_ml", 0)
                elif e["event_type"] == "BLOOD_LOSS":
                    io_out["blood_loss_ml"] += e["payload"].get("volume_ml", 0)
            io_in["total_ml"] = io_in["crystalloid_ml"] + io_in["colloid_ml"] + io_in["blood_ml"]
            io_out["total_ml"] = io_out["urine_ml"] + io_out["blood_loss_ml"]

            # Paginate vitals (24 per page)
            VITALS_PER_PAGE_DEMO = 24
            total_vitals = len(vitals)
            total_pages = max(1, (total_vitals + VITALS_PER_PAGE_DEMO - 1) // VITALS_PER_PAGE_DEMO)

            pages = []
            for page_num in range(total_pages):
                start_idx = page_num * VITALS_PER_PAGE_DEMO
                end_idx = min(start_idx + VITALS_PER_PAGE_DEMO, total_vitals)
                page_vitals = vitals[start_idx:end_idx]
                page_drugs = drugs if page_num == 0 else []  # drugs on first page only
                pages.append({
                    "page_number": page_num + 1,
                    "vitals": page_vitals,
                    "drugs": page_drugs,
                    "chart_image": ""
                })

            times = {
                "anesthesia_start": case_start.strftime("%H:%M"),
                "anesthesia_end": (case_start + timedelta(hours=5)).strftime("%H:%M"),
                "surgery_start": (case_start + timedelta(minutes=30)).strftime("%H:%M"),
                "surgery_end": (case_start + timedelta(hours=4, minutes=30)).strftime("%H:%M")
            }

        else:
            # Simple demo for other cases
            vitals = [
                {"time_display": "08:30", "hour": "08", "minute": "30", "show_hour": True, "sbp": 120, "dbp": 80, "hr": 72, "spo2": 99, "etco2": 35, "rr": 14, "temp": "36.5", "fio2": "50%", "mac": "1.0"},
                {"time_display": "08:45", "hour": "08", "minute": "45", "show_hour": False, "sbp": 115, "dbp": 75, "hr": 68, "spo2": 100, "etco2": 34, "rr": 12, "temp": "36.4", "fio2": "50%", "mac": "1.2"},
                {"time_display": "09:00", "hour": "09", "minute": "00", "show_hour": True, "sbp": 110, "dbp": 70, "hr": 65, "spo2": 100, "etco2": 33, "rr": 12, "temp": "36.3", "fio2": "45%", "mac": "1.0"},
            ]
            drugs = [
                {"time": "08:30", "name": "Propofol", "dose": "150 mg", "route": "IV"},
                {"time": "08:31", "name": "Fentanyl", "dose": "100 mcg", "route": "IV"},
                {"time": "08:32", "name": "Rocuronium", "dose": "50 mg", "route": "IV"},
            ]
            iv_lines = [{"line_number": 1, "site": "右手背", "gauge": "20G", "catheter_type": "PERIPHERAL"}]
            lab_data = []
            io_in = {"crystalloid_ml": 1000, "colloid_ml": 0, "blood_ml": 0, "total_ml": 1000}
            io_out = {"urine_ml": 300, "blood_loss_ml": 100, "total_ml": 400}
            pages = [{"page_number": 1, "vitals": vitals, "drugs": drugs, "chart_image": ""}]
            total_pages = 1
            times = {"anesthesia_start": "08:30", "anesthesia_end": "11:00", "surgery_start": "09:00", "surgery_end": "10:30"}

        demo_context = {
            "hospital_name": hospital_name,
            "hospital_address": hospital_address,
            "case_id": case_id,
            "patient": patient_info,
            "surgery": surgery_info,
            "diagnosis": demo_case.get("diagnosis", ""),
            "operation": demo_case.get("operation", ""),
            "preop_hb": demo_case.get("preop_hb"),
            "preop_ht": demo_case.get("preop_ht"),
            "preop_k": demo_case.get("preop_k"),
            "preop_na": demo_case.get("preop_na"),
            "estimated_blood_loss": demo_case.get("estimated_blood_loss"),
            "blood_prepared": demo_case.get("blood_prepared"),
            "blood_prepared_units": demo_case.get("blood_prepared_units"),
            "technique": demo_case.get("planned_technique", "GA_ETT"),
            "iv_lines": iv_lines,
            "lab_data": lab_data if case_id == "ANES-DEMO-006" else [],
            "io_balance": {
                "input": io_in,
                "output": io_out,
                "balance_ml": io_in["total_ml"] - io_out["total_ml"]
            },
            "times": times,
            "anesthesiologist": demo_case.get("primary_anesthesiologist_name", "李麻醉醫師"),
            "nurse": demo_case.get("primary_nurse_name", "林護理師"),
            "pages": pages,
            "total_pages": total_pages,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S") + " (Demo)"
        }

        # Render demo template
        template_dir = Path(__file__).parent.parent / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("anesthesia_record_m0073.html")
        html_content = template.render(**demo_context)

        return StreamingResponse(
            io.BytesIO(html_content.encode('utf-8')),
            media_type="text/html",
            headers={"Content-Disposition": f"inline; filename=anesthesia_{case_id}_demo.html"}
        )

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Get case info
        cursor.execute("""
            SELECT * FROM anesthesia_cases WHERE id = ?
        """, (case_id,))
        case = cursor.fetchone()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        case_dict = dict(case)

        # 2. Get all events (chronological order)
        cursor.execute("""
            SELECT * FROM anesthesia_events
            WHERE case_id = ?
            ORDER BY clinical_time ASC, recorded_at ASC
        """, (case_id,))
        events = [dict(row) for row in cursor.fetchall()]

        # 3. Rebuild state from events (pure function)
        state = _rebuild_state_from_events(events)

        # 4. Get IV lines from projection table (for additional details)
        cursor.execute("""
            SELECT * FROM anesthesia_iv_lines WHERE case_id = ? ORDER BY line_number
        """, (case_id,))
        iv_lines = [dict(row) for row in cursor.fetchall()]
        if iv_lines:
            state["iv_lines"] = [{
                "line_number": iv.get("line_number", i+1),
                "site": iv.get("site"),
                "gauge": iv.get("gauge"),
                "catheter_type": iv.get("catheter_type", "PERIPHERAL")
            } for i, iv in enumerate(iv_lines)]

        # 5. Paginate vitals (24 per page)
        vitals = state["vitals"]
        total_vitals = len(vitals)
        total_pages = max(1, (total_vitals + VITALS_PER_PAGE - 1) // VITALS_PER_PAGE)

        pages = []
        for page_num in range(total_pages):
            start_idx = page_num * VITALS_PER_PAGE
            end_idx = min(start_idx + VITALS_PER_PAGE, total_vitals)
            page_vitals = vitals[start_idx:end_idx]

            # Format time display for each vital (compact format)
            prev_hour = None
            for i, v in enumerate(page_vitals):
                if v.get("time"):
                    try:
                        t = datetime.fromisoformat(v["time"].replace("Z", "+00:00"))
                        hour = t.strftime("%H")
                        minute = t.strftime("%M")
                        v["time_display"] = t.strftime("%H:%M")
                        v["hour"] = hour
                        v["minute"] = f":{minute}"
                        # Show hour only when it changes
                        v["show_hour"] = (hour != prev_hour)
                        prev_hour = hour
                    except:
                        v["time_display"] = v["time"][:5] if len(v["time"]) >= 5 else v["time"]
                        v["hour"] = ""
                        v["minute"] = v["time_display"]
                        v["show_hour"] = True
                else:
                    v["time_display"] = ""
                    v["hour"] = ""
                    v["minute"] = ""
                    v["show_hour"] = False

            # Generate chart for this page's vitals
            chart_image = _generate_vitals_chart(vitals, start_idx, end_idx) if page_vitals else ""

            # Drugs for this page (max 12 per page to prevent overflow)
            DRUGS_PER_PAGE = 12
            if page_num == 0:
                page_drugs = state["drugs"][:DRUGS_PER_PAGE]
            else:
                remaining_drugs = state["drugs"][DRUGS_PER_PAGE:]
                drug_start = (page_num - 1) * DRUGS_PER_PAGE
                page_drugs = remaining_drugs[drug_start:drug_start + DRUGS_PER_PAGE]

            # Format drug times
            for d in page_drugs:
                if d.get("time"):
                    try:
                        t = datetime.fromisoformat(d["time"].replace("Z", "+00:00"))
                        d["time"] = t.strftime("%H:%M")
                    except:
                        d["time"] = d["time"][:5] if len(d["time"]) >= 5 else d["time"]

            pages.append({
                "page_number": page_num + 1,
                "vitals": page_vitals,
                "drugs": page_drugs,
                "chart_image": chart_image
            })

        # 6. Prepare template context
        context = {
            "hospital_name": hospital_name,
            "hospital_address": hospital_address,
            "case_id": case_id,
            "patient": {
                "name": case_dict.get("patient_name", ""),
                "chart_no": case_dict.get("patient_id", ""),
                "gender": case_dict.get("patient_gender", ""),
                "age": case_dict.get("patient_age", ""),
                "weight": case_dict.get("patient_weight", ""),
                "height": case_dict.get("patient_height", ""),
                "blood_type": case_dict.get("blood_type", ""),
                "asa_class": case_dict.get("asa_class", "")
            },
            "surgery": {
                "name": case_dict.get("surgery_name", ""),
                "procedure": case_dict.get("procedure", ""),
                "date": case_dict.get("created_at", "")[:10] if case_dict.get("created_at") else "",
                "or_room": case_dict.get("or_room", ""),
                "surgeon": case_dict.get("surgeon_name", "")
            },
            "technique": state["technique"] or case_dict.get("planned_technique"),
            "iv_lines": state["iv_lines"],
            "monitors": state["monitors"],
            "vent_settings": state["vent_settings"],
            "agent_settings": state["agent_settings"],
            "lab_data": state["lab_data"],
            "io_balance": state["io_balance"],
            "times": state["times"],
            "anesthesiologist": state["anesthesiologist"],
            "nurse": state["nurse"],
            "diagnosis": case_dict.get("diagnosis", ""),
            "operation": case_dict.get("operation", ""),
            "preop_hb": case_dict.get("preop_hb"),
            "preop_ht": case_dict.get("preop_ht"),
            "preop_k": case_dict.get("preop_k"),
            "preop_na": case_dict.get("preop_na"),
            "estimated_blood_loss": case_dict.get("estimated_blood_loss"),
            "blood_prepared": case_dict.get("blood_prepared"),
            "blood_prepared_units": case_dict.get("blood_prepared_units"),
            "pages": pages,
            "total_pages": total_pages,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 7. Render Jinja2 template
        template_dir = Path(__file__).parent.parent / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("anesthesia_record_m0073.html")
        html_content = template.render(**context)

        # 8. Return HTML preview or PDF
        if preview:
            return StreamingResponse(
                io.BytesIO(html_content.encode('utf-8')),
                media_type="text/html",
                headers={"Content-Disposition": f"inline; filename=anesthesia_{case_id}.html"}
            )

        # 9. Convert to PDF with WeasyPrint
        pdf_buffer = io.BytesIO()
        WeasyHTML(string=html_content, base_url=str(template_dir)).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=M0073_anesthesia_{case_id}.pdf"
            }
        )

    finally:
        conn.close()


@router.get("/cases/{case_id}/pdf/preview")
async def preview_pdf(
    case_id: str,
    hospital_name: str = Query("谷盺生技責任醫院", description="Hospital name for header")
):
    """
    Preview PDF as HTML (alias for /pdf?preview=true)

    GET /api/anesthesia/cases/{case_id}/pdf/preview
    """
    return await generate_pdf(case_id, preview=True, hospital_name=hospital_name)
