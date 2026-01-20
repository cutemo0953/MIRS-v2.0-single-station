"""
Anesthesia Billing Service
藥品計費、庫存扣減、管制藥驗證

Version: 1.2.0
Reference: DEV_SPEC_ANESTHESIA_BILLING_INTEGRATION_v1.2.md
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from enum import Enum
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass

import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

class InventoryTransactionType(str, Enum):
    """庫存交易類型 (Section 10.5)"""
    # 產生計費
    ADMINISTER = "ADMINISTER"

    # 不產生計費
    WITHDRAW = "WITHDRAW"
    WASTE = "WASTE"
    RETURN = "RETURN"
    TRANSFER = "TRANSFER"
    ADJUST = "ADJUST"
    EXPIRED = "EXPIRED"
    VOID_REVERSAL = "VOID_REVERSAL"


BILLABLE_TRANSACTIONS = {InventoryTransactionType.ADMINISTER}


class ControlledDrugLevel(int, Enum):
    """管制藥等級"""
    LEVEL_1 = 1  # 一級 (最嚴格)
    LEVEL_2 = 2  # 二級
    LEVEL_3 = 3  # 三級
    LEVEL_4 = 4  # 四級 (最寬鬆)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MedicationAdminRequest:
    """用藥記錄請求"""
    drug_code: str
    drug_name: str
    dose: float
    unit: str
    route: str
    is_controlled: bool = False
    witness_id: Optional[str] = None
    is_break_glass: bool = False
    break_glass_reason: Optional[str] = None
    case_id: Optional[str] = None
    actor_id: Optional[str] = None
    device_id: Optional[str] = None
    client_event_uuid: Optional[str] = None


@dataclass
class MedicationAdminResponse:
    """用藥記錄回應"""
    success: bool
    event_id: str
    inventory_txn_id: Optional[str]
    billing_quantity: float
    billing_unit: str
    estimated_price: Optional[float]
    warnings: List[str]
    controlled_log_id: Optional[str] = None
    witness_status: Optional[str] = None


@dataclass
class MedicineInfo:
    """藥品資訊"""
    medicine_code: str
    generic_name: str
    brand_name: Optional[str]
    unit: str
    nhi_price: float
    is_controlled_drug: bool
    controlled_level: Optional[int]
    content_per_unit: float
    content_unit: str
    billing_rounding: str
    current_stock: int


# =============================================================================
# Utility Functions
# =============================================================================

def generate_idempotency_key(case_id: str, client_event_uuid: str) -> str:
    """
    產生 idempotency key (Section 10.3)

    Args:
        case_id: 案件 ID
        client_event_uuid: 客戶端產生的事件 UUID

    Returns:
        SHA256 hash 前 32 字元
    """
    raw = f"{case_id}:{client_event_uuid}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def convert_to_base_unit(dose: float, unit: str) -> float:
    """
    將劑量換算為基本單位 (mg)

    Args:
        dose: 劑量
        unit: 單位 (mcg, mg, g, ml, etc.)

    Returns:
        等效 mg 劑量
    """
    unit_lower = unit.lower()

    # 重量單位轉換到 mg
    if unit_lower == 'mcg' or unit_lower == 'μg':
        return dose / 1000  # mcg -> mg
    elif unit_lower == 'mg':
        return dose
    elif unit_lower == 'g':
        return dose * 1000  # g -> mg
    elif unit_lower == 'ml':
        return dose  # 假設 ml = mg (濃度 1mg/ml)
    else:
        return dose  # 無法識別的單位，原值返回


def calculate_billing_quantity(
    clinical_dose: float,
    clinical_unit: str,
    content_per_unit: float,
    content_unit: str,
    billing_rounding: str = 'CEIL'
) -> Tuple[Decimal, Decimal]:
    """
    單位換算 (Section 10.4)

    Args:
        clinical_dose: 臨床劑量 (如 50 mcg)
        clinical_unit: 臨床單位 (如 'mcg')
        content_per_unit: 每單位含量 (如 0.1 for 0.1mg/amp)
        content_unit: 含量單位 (如 'mg')
        billing_rounding: 進位方式 (CEIL, FLOOR, ROUND, EXACT)

    Returns:
        (billing_quantity, inventory_deduct_quantity)

    Example:
        Fentanyl 50mcg IV:
        - content_per_unit = 0.1 mg/amp
        - 50 mcg = 0.05 mg
        - 0.05 mg / 0.1 mg = 0.5 amp
        - CEIL(0.5) = 1 amp
    """
    # 轉換為統一單位 (mg)
    dose_in_mg = convert_to_base_unit(clinical_dose, clinical_unit)
    content_in_mg = convert_to_base_unit(content_per_unit, content_unit.split('/')[0] if '/' in content_unit else content_unit)

    # 原始計算
    if content_in_mg and content_in_mg > 0:
        raw_quantity = Decimal(str(dose_in_mg)) / Decimal(str(content_in_mg))
    else:
        raw_quantity = Decimal(str(clinical_dose))

    # 計費數量 (保留2位小數)
    if billing_rounding == 'CEIL':
        billing_quantity = raw_quantity.quantize(Decimal('0.01'), rounding=ROUND_CEILING)
    elif billing_rounding == 'EXACT':
        billing_quantity = raw_quantity.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:  # 預設向上取整到整數
        billing_quantity = raw_quantity.quantize(Decimal('1'), rounding=ROUND_CEILING)

    # 庫存扣減 (向上取整到整數，開封即消耗)
    inventory_deduct_quantity = raw_quantity.quantize(Decimal('1'), rounding=ROUND_CEILING)

    return billing_quantity, inventory_deduct_quantity


# =============================================================================
# Database Functions
# =============================================================================

def get_db_connection(db_path: str = "database/mirs.db") -> sqlite3.Connection:
    """取得資料庫連線"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_medicine_info(cursor: sqlite3.Cursor, medicine_code: str) -> Optional[MedicineInfo]:
    """
    取得藥品資訊

    Args:
        cursor: 資料庫 cursor
        medicine_code: 藥品代碼

    Returns:
        MedicineInfo or None
    """
    cursor.execute("""
        SELECT
            medicine_code, generic_name, brand_name, unit,
            COALESCE(nhi_price, 0) as nhi_price,
            COALESCE(is_controlled_drug, 0) as is_controlled_drug,
            controlled_level, current_stock,
            COALESCE(content_per_unit, 1) as content_per_unit,
            COALESCE(content_unit, unit) as content_unit,
            COALESCE(billing_rounding, 'CEIL') as billing_rounding
        FROM medicines
        WHERE medicine_code = ?
    """, (medicine_code,))

    row = cursor.fetchone()
    if not row:
        return None

    # 解析 controlled_level
    controlled_level = None
    if row['controlled_level']:
        try:
            level_str = row['controlled_level']
            if level_str.startswith('LEVEL_'):
                controlled_level = int(level_str.split('_')[1])
        except:
            pass

    return MedicineInfo(
        medicine_code=row['medicine_code'],
        generic_name=row['generic_name'],
        brand_name=row['brand_name'],
        unit=row['unit'],
        nhi_price=float(row['nhi_price']),
        is_controlled_drug=bool(row['is_controlled_drug']),
        controlled_level=controlled_level,
        content_per_unit=float(row['content_per_unit']),
        content_unit=row['content_unit'],
        billing_rounding=row['billing_rounding'],
        current_stock=int(row['current_stock'])
    )


# =============================================================================
# Validation Functions
# =============================================================================

def validate_controlled_drug_requirements(
    medicine: MedicineInfo,
    witness_id: Optional[str],
    is_break_glass: bool,
    break_glass_reason: Optional[str]
) -> Tuple[bool, List[str]]:
    """
    驗證管制藥需求 (Section 10.6)

    Args:
        medicine: 藥品資訊
        witness_id: 見證人 ID
        is_break_glass: 是否為緊急授權
        break_glass_reason: 緊急授權原因

    Returns:
        (is_valid, errors)
    """
    errors = []

    if not medicine.is_controlled_drug:
        return True, []

    level = medicine.controlled_level or 4

    # 一二級管制藥必須有見證人或 break-glass
    if level in (1, 2):
        if not witness_id and not is_break_glass:
            errors.append("一二級管制藥需見證人 (witness_id) 或 break-glass 授權")

        # Break-glass 必須有原因
        if is_break_glass and not break_glass_reason:
            errors.append("Break-glass 必須提供原因 (break_glass_reason)")

    # 三四級管制藥建議但不強制要求見證人
    elif level in (3, 4):
        if not witness_id:
            # 這是 warning，不是 error
            pass

    return len(errors) == 0, errors


# =============================================================================
# Main Service Functions
# =============================================================================

def process_medication_admin(
    request: MedicationAdminRequest,
    db_path: str = "database/mirs.db"
) -> MedicationAdminResponse:
    """
    處理用藥記錄 (Phase 3: 整合庫存扣減)

    流程:
    1. 查詢藥品主檔
    2. 單位換算
    3. 管制藥驗證
    4. 寫入臨床事件
    5. 扣減庫存
    6. 產生計費項目

    Args:
        request: 用藥記錄請求
        db_path: 資料庫路徑

    Returns:
        MedicationAdminResponse
    """
    warnings = []

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 1. 查詢藥品主檔
        medicine = get_medicine_info(cursor, request.drug_code)

        if not medicine:
            # Fallback: 藥品不在主檔，仍記錄臨床事件 (離線容錯)
            medicine = MedicineInfo(
                medicine_code=request.drug_code,
                generic_name=request.drug_name,
                brand_name=None,
                unit=request.unit,
                nhi_price=0,
                is_controlled_drug=request.is_controlled,
                controlled_level=None,
                content_per_unit=1,
                content_unit=request.unit,
                billing_rounding='CEIL',
                current_stock=0
            )
            warnings.append("藥品不在主檔，僅記錄臨床事件")

        # 2. 單位換算
        billing_qty, inventory_deduct_qty = calculate_billing_quantity(
            clinical_dose=request.dose,
            clinical_unit=request.unit,
            content_per_unit=medicine.content_per_unit,
            content_unit=medicine.content_unit,
            billing_rounding=medicine.billing_rounding
        )

        # 3. 管制藥驗證
        if medicine.is_controlled_drug:
            is_valid, errors = validate_controlled_drug_requirements(
                medicine=medicine,
                witness_id=request.witness_id,
                is_break_glass=request.is_break_glass,
                break_glass_reason=request.break_glass_reason
            )

            if not is_valid:
                # 返回錯誤，但如果是 break-glass 則允許繼續
                if not request.is_break_glass:
                    return MedicationAdminResponse(
                        success=False,
                        event_id="",
                        inventory_txn_id=None,
                        billing_quantity=float(billing_qty),
                        billing_unit=medicine.unit,
                        estimated_price=None,
                        warnings=errors
                    )
                else:
                    warnings.extend(errors)

        # 4. 產生事件 ID
        event_id = f"MED-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        # 5. 產生 idempotency key
        client_event_uuid = request.client_event_uuid or str(uuid.uuid4())
        case_id = request.case_id or "UNKNOWN"
        idempotency_key = generate_idempotency_key(case_id, client_event_uuid)

        # 6. 扣減庫存
        inventory_txn_id = None

        if medicine.nhi_price > 0:  # 只有主檔藥品才扣庫存
            inventory_txn_id = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            # 檢查庫存
            new_stock = medicine.current_stock - int(inventory_deduct_qty)
            if new_stock < 0:
                warnings.append(f"庫存不足 (剩餘: {medicine.current_stock}, 扣減: {int(inventory_deduct_qty)})")

            # 寫入交易記錄
            cursor.execute("""
                INSERT INTO pharmacy_transactions (
                    transaction_id, transaction_type, medicine_code, generic_name,
                    quantity, unit, station_code,
                    is_controlled_drug, controlled_level,
                    patient_id, prescription_id,
                    operator, operator_role, verified_by,
                    reason, status,
                    idempotency_key, billing_quantity, inventory_deduct_quantity,
                    client_event_uuid, case_id
                ) VALUES (?, 'DISPENSE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?)
            """, (
                inventory_txn_id,
                medicine.medicine_code,
                medicine.generic_name,
                int(inventory_deduct_qty),
                medicine.unit,
                'MIRS-OR',
                1 if medicine.is_controlled_drug else 0,
                f"LEVEL_{medicine.controlled_level}" if medicine.controlled_level else None,
                None,  # patient_id from case
                None,  # prescription_id
                request.actor_id,
                'DOCTOR',  # Anesthesiologist = Doctor role
                request.witness_id,
                f"Anesthesia admin: {request.dose}{request.unit} {request.route}",
                idempotency_key,
                float(billing_qty),
                float(inventory_deduct_qty),
                client_event_uuid,
                case_id
            ))

            # 更新庫存
            cursor.execute("""
                UPDATE medicines
                SET current_stock = current_stock - ?, updated_at = ?
                WHERE medicine_code = ?
            """, (int(inventory_deduct_qty), datetime.now().isoformat(), medicine.medicine_code))

        # 7. 產生計費項目
        cursor.execute("""
            INSERT INTO medication_usage_events (
                idempotency_key, event_type, medicine_code, medicine_name,
                clinical_dose, clinical_unit,
                billing_quantity, billing_unit, inventory_deduct_quantity,
                route, case_id, operator_id, station_id,
                source_system, source_record_id,
                unit_price_at_event, billing_status, event_timestamp
            ) VALUES (?, 'ANESTHESIA_ADMIN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ANESTHESIA_PWA', ?, ?, 'PENDING', ?)
        """, (
            idempotency_key,
            medicine.medicine_code,
            medicine.generic_name,
            request.dose,
            request.unit,
            float(billing_qty),
            medicine.unit,
            float(inventory_deduct_qty),
            request.route,
            case_id,
            request.actor_id,
            'MIRS-OR',
            event_id,
            medicine.nhi_price,
            datetime.now().isoformat()
        ))

        # 8. 管制藥審計
        controlled_log_id = None
        witness_status = None

        if medicine.is_controlled_drug:
            controlled_log_id = f"CTRL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            if request.witness_id:
                witness_status = 'COMPLETED'
            elif request.is_break_glass:
                witness_status = 'PENDING_APPROVAL'
                warnings.append("Break-glass: 需在 24 小時內補核准")
            else:
                witness_status = 'REQUIRED'
                if medicine.controlled_level in (3, 4):
                    warnings.append("建議管制藥使用時有見證人")

        conn.commit()

        # 計算預估價格
        estimated_price = None
        if medicine.nhi_price > 0:
            estimated_price = medicine.nhi_price * float(billing_qty)

        return MedicationAdminResponse(
            success=True,
            event_id=event_id,
            inventory_txn_id=inventory_txn_id,
            billing_quantity=float(billing_qty),
            billing_unit=medicine.unit,
            estimated_price=estimated_price,
            warnings=warnings,
            controlled_log_id=controlled_log_id,
            witness_status=witness_status
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"process_medication_admin error: {e}")
        raise

    finally:
        conn.close()


# =============================================================================
# Fee Calculation Functions (Phase 5)
# =============================================================================

def calculate_anesthesia_fee(
    case_id: str,
    asa_class: int,
    asa_emergency: bool,
    technique: str,
    start_time: datetime,
    end_time: datetime,
    special_techniques: List[str] = None,
    db_path: str = "database/mirs.db"
) -> Dict[str, Any]:
    """
    計算麻醉處置費 (Phase 5)

    Args:
        case_id: 案件 ID
        asa_class: ASA 分級 (1-6)
        asa_emergency: 是否急診
        technique: 麻醉技術 (GA_ETT, RA_SPINAL, etc.)
        start_time: 開始時間
        end_time: 結束時間
        special_techniques: 特殊技術列表

    Returns:
        費用明細
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 取得費率表
        cursor.execute("""
            SELECT * FROM anesthesia_fee_schedule
            WHERE is_active = 1
            ORDER BY effective_date DESC
            LIMIT 1
        """)
        schedule = cursor.fetchone()

        if not schedule:
            raise ValueError("No active fee schedule found")

        # 計算時間 (分鐘)
        duration_minutes = int((end_time - start_time).total_seconds() / 60)

        # 1. 基本費
        if technique.startswith('GA'):
            base_fee = float(schedule['base_fee_ga'])
        elif technique.startswith('RA'):
            base_fee = float(schedule['base_fee_ra'])
        else:
            base_fee = float(schedule['base_fee_sedation'])

        # 2. 時間加成
        time_fee = 0
        time_start = int(schedule['time_fee_start_after_minutes'])
        if duration_minutes > time_start:
            extra_periods = (duration_minutes - time_start) // 30
            time_fee = extra_periods * float(schedule['time_fee_per_30min'])

        # 3. ASA 加成
        asa_multiplier = 1.0
        if asa_class == 3:
            asa_multiplier = float(schedule['asa_3_multiplier'])
        elif asa_class == 4:
            asa_multiplier = float(schedule['asa_4_multiplier'])
        elif asa_class >= 5:
            asa_multiplier = float(schedule['asa_5_multiplier'])

        asa_fee = base_fee * (asa_multiplier - 1)

        # 4. 急診加成
        emergency_fee = 0
        if asa_emergency:
            emergency_fee = base_fee * (float(schedule['emergency_multiplier']) - 1)

        # 5. 特殊技術費
        technique_fee = 0
        if special_techniques:
            technique_map = {
                'FIBER_OPTIC': float(schedule['technique_fiber_optic']),
                'TEE': float(schedule['technique_tee']),
                'NERVE_BLOCK': float(schedule['technique_nerve_block']),
                'ARTERIAL_LINE': float(schedule['technique_arterial_line']),
                'CVP': float(schedule['technique_cvp']),
            }
            for tech in special_techniques:
                technique_fee += technique_map.get(tech, 0)

        # 總計
        total_fee = base_fee + time_fee + asa_fee + emergency_fee + technique_fee

        # 寫入計費事件
        billing_id = f"ANES-BILL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        cursor.execute("""
            INSERT INTO anesthesia_billing_events (
                billing_id, case_id, asa_class, asa_emergency,
                anesthesia_technique, anesthesia_start_time, anesthesia_end_time,
                anesthesia_duration_minutes, special_techniques,
                base_fee, time_fee, asa_fee, technique_fee, emergency_fee, total_fee,
                fee_schedule_version, billing_status, calculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CALCULATED', ?)
        """, (
            billing_id, case_id, asa_class, 1 if asa_emergency else 0,
            technique, start_time.isoformat(), end_time.isoformat(),
            duration_minutes, json.dumps(special_techniques) if special_techniques else None,
            base_fee, time_fee, asa_fee, technique_fee, emergency_fee, total_fee,
            schedule['schedule_version'], datetime.now().isoformat()
        ))

        conn.commit()

        return {
            "billing_id": billing_id,
            "case_id": case_id,
            "duration_minutes": duration_minutes,
            "base_fee": base_fee,
            "time_fee": time_fee,
            "asa_fee": asa_fee,
            "technique_fee": technique_fee,
            "emergency_fee": emergency_fee,
            "total_fee": total_fee,
            "fee_schedule_version": schedule['schedule_version']
        }

    finally:
        conn.close()


def calculate_surgical_fee(
    case_id: str,
    surgery_code: str,
    surgery_name: str,
    surgery_grade: str,  # A, B, C, D
    surgeon_id: str,
    start_time: datetime,
    end_time: datetime,
    assistant_ids: Optional[List[str]] = None,
    db_path: str = "database/mirs.db"
) -> Dict[str, Any]:
    """
    計算手術處置費 (Phase 5)

    Args:
        case_id: 案件 ID
        surgery_code: 手術代碼 (NHI code)
        surgery_name: 手術名稱
        surgery_grade: 手術等級 (A, B, C, D)
        surgeon_id: 主刀醫師 ID
        start_time: 手術開始時間
        end_time: 手術結束時間
        assistant_ids: 助手醫師 ID 列表

    Returns:
        費用明細
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 取得費率表
        cursor.execute("""
            SELECT * FROM surgical_fee_schedule
            WHERE is_active = 1
            ORDER BY effective_date DESC
            LIMIT 1
        """)
        schedule = cursor.fetchone()

        if not schedule:
            # Fallback to default values
            schedule = {
                'schedule_version': 'default',
                'surgeon_fee_grade_a': 20000,
                'surgeon_fee_grade_b': 12000,
                'surgeon_fee_grade_c': 6000,
                'surgeon_fee_grade_d': 3000,
                'assistant_fee_ratio': 0.35,
                'overtime_fee_per_30min': 1000,
                'overtime_start_grade_a': 180,
                'overtime_start_grade_b': 120,
                'overtime_start_grade_c': 60,
                'overtime_start_grade_d': 30,
            }

        # 計算時間 (分鐘)
        duration_minutes = int((end_time - start_time).total_seconds() / 60)

        # 1. 主刀費用 (依手術等級)
        grade_upper = surgery_grade.upper() if surgery_grade else 'C'
        surgeon_fee_map = {
            'A': float(schedule['surgeon_fee_grade_a']),
            'B': float(schedule['surgeon_fee_grade_b']),
            'C': float(schedule['surgeon_fee_grade_c']),
            'D': float(schedule['surgeon_fee_grade_d']),
        }
        surgeon_fee = surgeon_fee_map.get(grade_upper, surgeon_fee_map['C'])

        # 2. 超時加成
        overtime_fee = 0
        overtime_start_map = {
            'A': int(schedule['overtime_start_grade_a']),
            'B': int(schedule['overtime_start_grade_b']),
            'C': int(schedule['overtime_start_grade_c']),
            'D': int(schedule['overtime_start_grade_d']),
        }
        overtime_threshold = overtime_start_map.get(grade_upper, 60)

        if duration_minutes > overtime_threshold:
            extra_periods = (duration_minutes - overtime_threshold) // 30
            overtime_fee = extra_periods * float(schedule['overtime_fee_per_30min'])

        # 3. 助手費用
        assistant_fee = 0
        assistant_count = len(assistant_ids) if assistant_ids else 0
        if assistant_count > 0:
            assistant_fee = surgeon_fee * float(schedule['assistant_fee_ratio']) * assistant_count

        # 總計
        total_fee = surgeon_fee + overtime_fee + assistant_fee

        # 寫入計費事件
        billing_id = f"SURG-BILL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        cursor.execute("""
            INSERT INTO surgical_billing_events (
                billing_id, case_id, surgery_code, surgery_name,
                surgery_start_time, surgery_end_time, surgery_duration_minutes,
                surgeon_id, assistant_ids,
                surgeon_fee, assistant_fee, total_fee,
                fee_schedule_version, billing_status, calculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CALCULATED', ?)
        """, (
            billing_id, case_id, surgery_code, surgery_name,
            start_time.isoformat(), end_time.isoformat(), duration_minutes,
            surgeon_id, json.dumps(assistant_ids) if assistant_ids else None,
            surgeon_fee, assistant_fee, total_fee,
            schedule['schedule_version'] if isinstance(schedule, dict) else schedule.get('schedule_version', 'default'),
            datetime.now().isoformat()
        ))

        conn.commit()

        return {
            "billing_id": billing_id,
            "case_id": case_id,
            "surgery_code": surgery_code,
            "surgery_name": surgery_name,
            "surgery_grade": grade_upper,
            "duration_minutes": duration_minutes,
            "surgeon_fee": surgeon_fee,
            "overtime_fee": overtime_fee,
            "assistant_fee": assistant_fee,
            "assistant_count": assistant_count,
            "total_fee": total_fee,
            "fee_schedule_version": schedule['schedule_version'] if isinstance(schedule, dict) else schedule.get('schedule_version', 'default')
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"calculate_surgical_fee error: {e}")
        raise

    finally:
        conn.close()


# =============================================================================
# CashDesk Handoff (Phase 6)
# =============================================================================

def generate_cashdesk_handoff(
    case_id: str,
    db_path: str = "database/mirs.db"
) -> Dict[str, Any]:
    """
    產生 CashDesk Handoff Package (Phase 6)

    Args:
        case_id: 案件 ID

    Returns:
        完整的計費封包
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 1. 藥品費
        cursor.execute("""
            SELECT
                medicine_code, medicine_name,
                SUM(billing_quantity) as total_quantity,
                billing_unit, unit_price_at_event,
                SUM(billing_quantity * unit_price_at_event) as total_price
            FROM medication_usage_events
            WHERE case_id = ? AND billing_status != 'VOIDED' AND is_voided = 0
            GROUP BY medicine_code
        """, (case_id,))

        medication_items = []
        medication_total = 0
        for row in cursor.fetchall():
            item = {
                "medicine_code": row['medicine_code'],
                "medicine_name": row['medicine_name'],
                "quantity": float(row['total_quantity']),
                "unit": row['billing_unit'],
                "unit_price": float(row['unit_price_at_event'] or 0),
                "total_price": float(row['total_price'] or 0)
            }
            medication_items.append(item)
            medication_total += item['total_price']

        # 2. 麻醉處置費
        cursor.execute("""
            SELECT * FROM anesthesia_billing_events
            WHERE case_id = ? AND billing_status != 'VOIDED'
            ORDER BY calculated_at DESC
            LIMIT 1
        """, (case_id,))

        anesthesia_row = cursor.fetchone()
        anesthesia_fee = None
        if anesthesia_row:
            anesthesia_fee = {
                "billing_id": anesthesia_row['billing_id'],
                "asa_class": anesthesia_row['asa_class'],
                "asa_emergency": bool(anesthesia_row['asa_emergency']),
                "technique": anesthesia_row['anesthesia_technique'],
                "duration_minutes": anesthesia_row['anesthesia_duration_minutes'],
                "base_fee": float(anesthesia_row['base_fee']),
                "time_fee": float(anesthesia_row['time_fee']),
                "asa_fee": float(anesthesia_row['asa_fee']),
                "technique_fee": float(anesthesia_row['technique_fee']),
                "emergency_fee": float(anesthesia_row['emergency_fee']),
                "total_fee": float(anesthesia_row['total_fee'])
            }

        # 3. 手術處置費
        cursor.execute("""
            SELECT * FROM surgical_billing_events
            WHERE case_id = ? AND billing_status != 'VOIDED'
            ORDER BY calculated_at DESC
            LIMIT 1
        """, (case_id,))

        surgery_row = cursor.fetchone()
        surgical_fee = None
        if surgery_row:
            surgical_fee = {
                "billing_id": surgery_row['billing_id'],
                "surgery_code": surgery_row['surgery_code'],
                "surgery_name": surgery_row['surgery_name'],
                "duration_minutes": surgery_row['surgery_duration_minutes'],
                "surgeon_fee": float(surgery_row['surgeon_fee']),
                "assistant_fee": float(surgery_row['assistant_fee']),
                "total_fee": float(surgery_row['total_fee'])
            }

        # 總計
        grand_total = medication_total
        if anesthesia_fee:
            grand_total += anesthesia_fee['total_fee']
        if surgical_fee:
            grand_total += surgical_fee['total_fee']

        handoff_package = {
            "case_id": case_id,
            "generated_at": datetime.now().isoformat(),
            "medication_items": medication_items,
            "medication_total": medication_total,
            "anesthesia_fee": anesthesia_fee,
            "surgical_fee": surgical_fee,
            "grand_total": grand_total,
            "status": "READY_FOR_EXPORT"
        }

        return handoff_package

    finally:
        conn.close()


def export_to_cashdesk(
    case_id: str,
    db_path: str = "database/mirs.db"
) -> Dict[str, Any]:
    """
    匯出到 CashDesk 並鎖定記錄

    Args:
        case_id: 案件 ID

    Returns:
        匯出結果
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        export_time = datetime.now().isoformat()

        # 更新藥品計費狀態
        cursor.execute("""
            UPDATE medication_usage_events
            SET billing_status = 'EXPORTED', is_locked = 1
            WHERE case_id = ? AND billing_status = 'PENDING'
        """, (case_id,))
        med_count = cursor.rowcount

        # 更新麻醉計費狀態
        cursor.execute("""
            UPDATE anesthesia_billing_events
            SET billing_status = 'EXPORTED', exported_at = ?
            WHERE case_id = ? AND billing_status = 'CALCULATED'
        """, (export_time, case_id))
        anes_count = cursor.rowcount

        # 更新手術計費狀態
        cursor.execute("""
            UPDATE surgical_billing_events
            SET billing_status = 'EXPORTED', exported_at = ?
            WHERE case_id = ? AND billing_status = 'CALCULATED'
        """, (export_time, case_id))
        surg_count = cursor.rowcount

        conn.commit()

        return {
            "success": True,
            "case_id": case_id,
            "exported_at": export_time,
            "medication_items_exported": med_count,
            "anesthesia_fee_exported": anes_count,
            "surgical_fee_exported": surg_count
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"export_to_cashdesk error: {e}")
        raise

    finally:
        conn.close()


# =============================================================================
# Quick Drugs List
# =============================================================================

def get_quick_drugs_with_inventory(db_path: str = "database/mirs.db") -> List[Dict[str, Any]]:
    """
    取得快速用藥清單含庫存資訊 (Phase 3)

    Returns:
        藥品清單含庫存狀態
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 常用麻醉藥物清單
        quick_drug_codes = [
            'BC90567209',  # Fentanyl
            'BC80456209',  # Morphine
            'BC11001209',  # Propofol
            'BC01678209',  # Ketamine
            'BC60234209',  # Diazepam (INJ)
            'AC34567209',  # Lidocaine
            'AC06775209',  # Epinephrine
            'AC12790209',  # Atropine
            'AC12380209',  # Neostigmine
            'BC11007209',  # Neostigmine (我們的版本)
        ]

        placeholders = ','.join(['?'] * len(quick_drug_codes))
        cursor.execute(f"""
            SELECT
                medicine_code, generic_name, brand_name, unit,
                nhi_price, is_controlled_drug, controlled_level,
                current_stock, min_stock,
                content_per_unit, content_unit
            FROM medicines
            WHERE medicine_code IN ({placeholders}) AND is_active = 1
            ORDER BY generic_name
        """, quick_drug_codes)

        drugs = []
        for row in cursor.fetchall():
            # 庫存狀態
            stock = row['current_stock']
            min_stock = row['min_stock'] or 2
            if stock <= 0:
                stock_status = 'OUT_OF_STOCK'
                stock_display = '缺貨'
            elif stock <= min_stock:
                stock_status = 'LOW_STOCK'
                stock_display = f'⚠️ {stock}'
            else:
                stock_status = 'OK'
                stock_display = str(stock)

            drugs.append({
                "medicine_code": row['medicine_code'],
                "generic_name": row['generic_name'],
                "brand_name": row['brand_name'],
                "unit": row['unit'],
                "nhi_price": float(row['nhi_price'] or 0),
                "is_controlled": bool(row['is_controlled_drug']),
                "controlled_level": row['controlled_level'],
                "current_stock": stock,
                "stock_status": stock_status,
                "stock_display": stock_display,
                "content_per_unit": float(row['content_per_unit'] or 1),
                "content_unit": row['content_unit']
            })

        return drugs

    finally:
        conn.close()


# =============================================================================
# Break-Glass Approval (Phase 4)
# =============================================================================

# 允許的 Break-glass 理由 (Section 4.2)
ALLOWED_BREAK_GLASS_REASONS = [
    'MTP_ACTIVATED',              # 大量輸血啟動
    'CARDIAC_ARREST',             # 心跳停止
    'ANAPHYLAXIS',                # 過敏性休克
    'AIRWAY_EMERGENCY',           # 呼吸道緊急
    'EXSANGUINATING_HEMORRHAGE',  # 大量出血
    'NO_SECOND_STAFF',            # 無第二人員可協助
    'SYSTEM_OFFLINE',             # 系統離線
    'OTHER',                      # 其他 (需說明)
]


@dataclass
class BreakGlassApprovalRequest:
    """Break-glass 事後核准請求"""
    event_id: str
    approver_id: str
    notes: Optional[str] = None


@dataclass
class BreakGlassApprovalResponse:
    """Break-glass 事後核准回應"""
    success: bool
    event_id: str
    approved_by: str
    approved_at: str
    message: str


def get_pending_break_glass_events(
    db_path: str = "database/mirs.db",
    hours_limit: int = 24
) -> List[Dict[str, Any]]:
    """
    取得待核准的 Break-glass 事件清單

    Args:
        db_path: 資料庫路徑
        hours_limit: 小時限制 (預設 24 小時內)

    Returns:
        待核准事件清單
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 查詢 controlled_drug_log 中待核准的記錄
        cursor.execute("""
            SELECT
                cdl.id,
                cdl.case_id,
                cdl.medicine_code,
                cdl.medicine_name,
                cdl.administered_amount,
                cdl.witness_status,
                cdl.is_break_glass,
                cdl.break_glass_reason,
                cdl.break_glass_deadline,
                cdl.operator_id,
                cdl.event_timestamp,
                cdl.created_at,
                ac.patient_name
            FROM controlled_drug_log cdl
            LEFT JOIN anesthesia_cases ac ON cdl.case_id = ac.id
            WHERE cdl.is_break_glass = 1
              AND cdl.witness_status = 'PENDING'
              AND cdl.break_glass_approved_by IS NULL
              AND cdl.created_at >= datetime('now', '-{} hours')
            ORDER BY cdl.created_at DESC
        """.format(hours_limit))

        events = []
        for row in cursor.fetchall():
            deadline = row['break_glass_deadline']
            is_overdue = False
            if deadline:
                deadline_dt = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                is_overdue = datetime.now() > deadline_dt

            events.append({
                "id": row['id'],
                "case_id": row['case_id'],
                "patient_name": row['patient_name'],
                "medicine_code": row['medicine_code'],
                "medicine_name": row['medicine_name'],
                "administered_amount": row['administered_amount'],
                "break_glass_reason": row['break_glass_reason'],
                "operator_id": row['operator_id'],
                "event_timestamp": row['event_timestamp'],
                "deadline": deadline,
                "is_overdue": is_overdue,
                "hours_remaining": None if not deadline else max(0, (deadline_dt - datetime.now()).total_seconds() / 3600)
            })

        return events

    finally:
        conn.close()


def approve_break_glass(
    request: BreakGlassApprovalRequest,
    db_path: str = "database/mirs.db"
) -> BreakGlassApprovalResponse:
    """
    核准 Break-glass 事件

    Args:
        request: 核准請求
        db_path: 資料庫路徑

    Returns:
        核准結果
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 確認記錄存在且待核准
        cursor.execute("""
            SELECT id, is_break_glass, witness_status, break_glass_approved_by
            FROM controlled_drug_log
            WHERE id = ?
        """, (request.event_id,))

        row = cursor.fetchone()
        if not row:
            return BreakGlassApprovalResponse(
                success=False,
                event_id=request.event_id,
                approved_by="",
                approved_at="",
                message="找不到該事件記錄"
            )

        if not row['is_break_glass']:
            return BreakGlassApprovalResponse(
                success=False,
                event_id=request.event_id,
                approved_by="",
                approved_at="",
                message="該記錄不是 Break-glass 事件"
            )

        if row['break_glass_approved_by']:
            return BreakGlassApprovalResponse(
                success=False,
                event_id=request.event_id,
                approved_by=row['break_glass_approved_by'],
                approved_at="",
                message="該事件已經被核准"
            )

        # 執行核准
        approved_at = datetime.now().isoformat()
        cursor.execute("""
            UPDATE controlled_drug_log
            SET witness_status = 'COMPLETED',
                break_glass_approved_by = ?,
                break_glass_approved_at = ?
            WHERE id = ?
        """, (request.approver_id, approved_at, request.event_id))

        # 記錄稽核日誌
        cursor.execute("""
            INSERT INTO audit_log (
                action, table_name, record_id, actor_id, details, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            'BREAK_GLASS_APPROVED',
            'controlled_drug_log',
            request.event_id,
            request.approver_id,
            json.dumps({"notes": request.notes}),
            approved_at
        ))

        conn.commit()

        return BreakGlassApprovalResponse(
            success=True,
            event_id=request.event_id,
            approved_by=request.approver_id,
            approved_at=approved_at,
            message="Break-glass 事件已核准"
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"approve_break_glass error: {e}")
        return BreakGlassApprovalResponse(
            success=False,
            event_id=request.event_id,
            approved_by="",
            approved_at="",
            message=f"核准失敗: {str(e)}"
        )

    finally:
        conn.close()


def get_break_glass_stats(
    db_path: str = "database/mirs.db",
    days: int = 30
) -> Dict[str, Any]:
    """
    取得 Break-glass 統計資訊

    Args:
        db_path: 資料庫路徑
        days: 統計天數

    Returns:
        統計資訊
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 總數與待核准數
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN break_glass_approved_by IS NULL THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN break_glass_approved_by IS NOT NULL THEN 1 ELSE 0 END) as approved
            FROM controlled_drug_log
            WHERE is_break_glass = 1
              AND created_at >= datetime('now', '-{} days')
        """.format(days))

        row = cursor.fetchone()

        # 按原因分類
        cursor.execute("""
            SELECT break_glass_reason, COUNT(*) as count
            FROM controlled_drug_log
            WHERE is_break_glass = 1
              AND created_at >= datetime('now', '-{} days')
            GROUP BY break_glass_reason
            ORDER BY count DESC
        """.format(days))

        by_reason = {r['break_glass_reason']: r['count'] for r in cursor.fetchall()}

        # 逾期未核准數
        cursor.execute("""
            SELECT COUNT(*) as overdue
            FROM controlled_drug_log
            WHERE is_break_glass = 1
              AND witness_status = 'PENDING'
              AND break_glass_approved_by IS NULL
              AND break_glass_deadline < datetime('now')
        """)
        overdue_row = cursor.fetchone()

        return {
            "period_days": days,
            "total": row['total'] or 0,
            "pending": row['pending'] or 0,
            "approved": row['approved'] or 0,
            "overdue": overdue_row['overdue'] or 0,
            "by_reason": by_reason
        }

    finally:
        conn.close()
