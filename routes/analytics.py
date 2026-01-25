"""
MIRS Analytics Dashboard API
============================

Provides aggregated statistics and analytics for:
- Case volume and duration
- Medication usage
- Equipment utilization
- Blood inventory (synced with Blood Bank PWA)

Version: 1.0
Date: 2026-01-25
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.7 (P2-02)
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Database path
DB_PATH = os.environ.get('MIRS_DB_PATH', 'medical_inventory.db')


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# Response Models
# =============================================================================

class CaseSummary(BaseModel):
    """Case statistics summary."""
    total_cases: int = 0
    by_status: Dict[str, int] = {}
    avg_anesthesia_duration_min: Optional[float] = None
    avg_surgery_duration_min: Optional[float] = None
    by_asa_class: Dict[str, int] = {}
    by_anesthesiologist: List[Dict[str, Any]] = []


class DailyStats(BaseModel):
    """Daily statistics entry."""
    date: str
    case_count: int
    avg_duration_min: Optional[float] = None
    medication_count: int = 0


class MedicationUsage(BaseModel):
    """Medication usage statistics."""
    drug_name: str
    administrations: int
    total_dose: Optional[float] = None
    unit: Optional[str] = None


class EquipmentUtilization(BaseModel):
    """Equipment utilization statistics."""
    equipment_id: str
    name: str
    total_claims: int
    current_status: str
    level_percent: Optional[float] = None


class DashboardSummary(BaseModel):
    """Main dashboard summary."""
    today_cases: int = 0
    week_cases: int = 0
    month_cases: int = 0
    active_cases: int = 0
    equipment_summary: Dict[str, int] = {}
    alerts: List[Dict[str, Any]] = []
    last_updated: str = ""


# =============================================================================
# Dashboard Endpoints
# =============================================================================

@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard_summary():
    """
    Get aggregated dashboard summary.

    Returns:
    - today/week/month case counts
    - active cases (IN_PROGRESS + PACU)
    - equipment status summary
    - alerts (low stock, expiring items)
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        month_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d')

        # Case counts
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN date(created_at) = ? THEN 1 END) as today,
                COUNT(CASE WHEN date(created_at) >= ? THEN 1 END) as week,
                COUNT(CASE WHEN date(created_at) >= ? THEN 1 END) as month,
                COUNT(CASE WHEN status IN ('IN_PROGRESS', 'PACU') THEN 1 END) as active
            FROM anesthesia_cases
        """, (today, week_ago, month_ago))
        row = cursor.fetchone()

        today_cases = row['today'] if row else 0
        week_cases = row['week'] if row else 0
        month_cases = row['month'] if row else 0
        active_cases = row['active'] if row else 0

        # Equipment summary
        equipment_summary = {}
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM equipment_units
            WHERE is_active = 1
            GROUP BY status
        """)
        for r in cursor.fetchall():
            equipment_summary[r['status']] = r['count']

        # Alerts
        alerts = []

        # Low oxygen alerts
        cursor.execute("""
            SELECT unit_label, level_percent, equipment_id
            FROM equipment_units
            WHERE level_percent <= 20 AND is_active = 1
            ORDER BY level_percent ASC
            LIMIT 5
        """)
        for r in cursor.fetchall():
            alerts.append({
                "type": "low_oxygen",
                "severity": "warning" if r['level_percent'] > 10 else "critical",
                "message": f"{r['unit_label']} low ({r['level_percent']}%)",
                "equipment_id": r['equipment_id']
            })

        # Blood expiry alerts (if blood bank module exists)
        try:
            cursor.execute("""
                SELECT blood_type, COUNT(*) as count,
                       MIN(expiry_date) as nearest_expiry
                FROM blood_units
                WHERE status = 'AVAILABLE'
                  AND expiry_date <= date('now', '+3 days')
                GROUP BY blood_type
            """)
            for r in cursor.fetchall():
                alerts.append({
                    "type": "blood_expiring",
                    "severity": "warning",
                    "message": f"Blood {r['blood_type']} expiring ({r['count']} units)",
                    "nearest_expiry": r['nearest_expiry']
                })
        except sqlite3.OperationalError:
            pass  # Blood bank table doesn't exist

        return DashboardSummary(
            today_cases=today_cases,
            week_cases=week_cases,
            month_cases=month_cases,
            active_cases=active_cases,
            equipment_summary=equipment_summary,
            alerts=alerts,
            last_updated=now.isoformat()
        )

    finally:
        conn.close()


@router.get("/cases/summary", response_model=CaseSummary)
async def get_case_summary(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)")
):
    """
    Get case statistics summary.

    Returns:
    - total cases
    - by status distribution
    - average durations
    - by ASA class
    - by anesthesiologist
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Build date filter
        date_filter = ""
        params = []
        if start_date:
            date_filter += " AND date(created_at) >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND date(created_at) <= ?"
            params.append(end_date)

        # Total and by status
        cursor.execute(f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'PREOP' THEN 1 END) as preop,
                COUNT(CASE WHEN status = 'IN_PROGRESS' THEN 1 END) as in_progress,
                COUNT(CASE WHEN status = 'PACU' THEN 1 END) as pacu,
                COUNT(CASE WHEN status = 'CLOSED' THEN 1 END) as closed,
                AVG(
                    CASE WHEN anesthesia_end_at IS NOT NULL AND anesthesia_start_at IS NOT NULL
                    THEN (julianday(anesthesia_end_at) - julianday(anesthesia_start_at)) * 24 * 60
                    END
                ) as avg_anesthesia_min,
                AVG(
                    CASE WHEN surgery_end_at IS NOT NULL AND surgery_start_at IS NOT NULL
                    THEN (julianday(surgery_end_at) - julianday(surgery_start_at)) * 24 * 60
                    END
                ) as avg_surgery_min
            FROM anesthesia_cases
            WHERE 1=1 {date_filter}
        """, params)
        row = cursor.fetchone()

        by_status = {
            "PREOP": row['preop'] if row else 0,
            "IN_PROGRESS": row['in_progress'] if row else 0,
            "PACU": row['pacu'] if row else 0,
            "CLOSED": row['closed'] if row else 0
        }

        # By ASA class
        cursor.execute(f"""
            SELECT asa_classification, COUNT(*) as count
            FROM anesthesia_cases
            WHERE asa_classification IS NOT NULL {date_filter}
            GROUP BY asa_classification
            ORDER BY count DESC
        """, params)
        by_asa = {r['asa_classification']: r['count'] for r in cursor.fetchall()}

        # By anesthesiologist (top 10)
        cursor.execute(f"""
            SELECT
                primary_anesthesiologist_name as name,
                COUNT(*) as case_count,
                AVG(
                    CASE WHEN anesthesia_end_at IS NOT NULL AND anesthesia_start_at IS NOT NULL
                    THEN (julianday(anesthesia_end_at) - julianday(anesthesia_start_at)) * 24 * 60
                    END
                ) as avg_duration
            FROM anesthesia_cases
            WHERE primary_anesthesiologist_name IS NOT NULL {date_filter}
            GROUP BY primary_anesthesiologist_name
            ORDER BY case_count DESC
            LIMIT 10
        """, params)
        by_anesthesiologist = [
            {"name": r['name'], "case_count": r['case_count'], "avg_duration": r['avg_duration']}
            for r in cursor.fetchall()
        ]

        return CaseSummary(
            total_cases=row['total'] if row else 0,
            by_status=by_status,
            avg_anesthesia_duration_min=row['avg_anesthesia_min'] if row else None,
            avg_surgery_duration_min=row['avg_surgery_min'] if row else None,
            by_asa_class=by_asa,
            by_anesthesiologist=by_anesthesiologist
        )

    finally:
        conn.close()


@router.get("/cases/daily", response_model=List[DailyStats])
async def get_daily_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days")
):
    """
    Get daily case statistics for trend analysis.

    Returns time-series data:
    - date
    - case count
    - average duration
    - medication count
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                date(created_at) as date,
                COUNT(*) as case_count,
                AVG(
                    CASE WHEN anesthesia_end_at IS NOT NULL AND anesthesia_start_at IS NOT NULL
                    THEN (julianday(anesthesia_end_at) - julianday(anesthesia_start_at)) * 24 * 60
                    END
                ) as avg_duration
            FROM anesthesia_cases
            WHERE created_at >= date('now', ?)
            GROUP BY date(created_at)
            ORDER BY date DESC
        """, (f'-{days} days',))

        results = []
        for row in cursor.fetchall():
            # Get medication count for this date
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM anesthesia_events
                WHERE event_type = 'MEDICATION_ADMIN'
                  AND date(clinical_time) = ?
            """, (row['date'],))
            med_row = cursor.fetchone()
            med_count = med_row['count'] if med_row else 0

            results.append(DailyStats(
                date=row['date'],
                case_count=row['case_count'],
                avg_duration_min=row['avg_duration'],
                medication_count=med_count
            ))

        return results

    finally:
        conn.close()


@router.get("/medications/usage", response_model=List[MedicationUsage])
async def get_medication_usage(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """
    Get medication usage statistics.

    Returns:
    - drug name
    - administration count
    - total dose
    - unit
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        date_filter = ""
        params = []
        if start_date:
            date_filter += " AND date(clinical_time) >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND date(clinical_time) <= ?"
            params.append(end_date)

        params.append(limit)

        cursor.execute(f"""
            SELECT
                json_extract(payload, '$.drug_name') as drug_name,
                COUNT(*) as administrations,
                SUM(CAST(json_extract(payload, '$.dose') as REAL)) as total_dose,
                json_extract(payload, '$.unit') as unit
            FROM anesthesia_events
            WHERE event_type = 'MEDICATION_ADMIN'
              AND json_extract(payload, '$.drug_name') IS NOT NULL
              {date_filter}
            GROUP BY drug_name, unit
            ORDER BY administrations DESC
            LIMIT ?
        """, params)

        return [
            MedicationUsage(
                drug_name=r['drug_name'],
                administrations=r['administrations'],
                total_dose=r['total_dose'],
                unit=r['unit']
            )
            for r in cursor.fetchall()
        ]

    finally:
        conn.close()


@router.get("/equipment/utilization", response_model=List[EquipmentUtilization])
async def get_equipment_utilization():
    """
    Get equipment utilization statistics.

    Returns:
    - equipment ID and name
    - total claims (times used)
    - current status
    - current level
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Get equipment units with claim counts
        cursor.execute("""
            SELECT
                eu.equipment_id,
                e.name,
                eu.unit_label,
                eu.status,
                eu.level_percent,
                (
                    SELECT COUNT(*)
                    FROM anesthesia_events ae
                    WHERE ae.event_type = 'RESOURCE_CLAIM'
                      AND json_extract(ae.payload, '$.unit_id') = CAST(eu.id as TEXT)
                ) as claim_count
            FROM equipment_units eu
            JOIN equipment e ON eu.equipment_id = e.id
            WHERE eu.is_active = 1
            ORDER BY claim_count DESC, eu.equipment_id
        """)

        return [
            EquipmentUtilization(
                equipment_id=r['equipment_id'],
                name=r['name'] or r['unit_label'],
                total_claims=r['claim_count'],
                current_status=r['status'],
                level_percent=r['level_percent']
            )
            for r in cursor.fetchall()
        ]

    finally:
        conn.close()


@router.get("/oxygen/consumption")
async def get_oxygen_consumption(
    days: int = Query(30, ge=1, le=365)
):
    """
    Get oxygen consumption statistics.

    Returns:
    - by cylinder type (H-type, E-type)
    - estimated liters consumed
    - usage trends
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        # H-type: 6900L capacity, E-type: 680L capacity
        CYLINDER_CAPACITY = {
            'H': 6900,
            'E': 680
        }

        results = {
            'by_type': {},
            'total_liters': 0,
            'period_days': days
        }

        # Get consumption by cylinder type
        cursor.execute("""
            SELECT
                CASE
                    WHEN eu.unit_serial LIKE 'H-%' THEN 'H-type'
                    WHEN eu.unit_serial LIKE 'E-%' THEN 'E-type'
                    ELSE 'Other'
                END as cylinder_type,
                COUNT(DISTINCT ae.id) as usage_events,
                SUM(
                    CAST(json_extract(ae.payload, '$.level_before') as REAL) -
                    CAST(json_extract(ae.payload, '$.level_after') as REAL)
                ) as level_drop_percent
            FROM anesthesia_events ae
            JOIN equipment_units eu ON CAST(eu.id as TEXT) = json_extract(ae.payload, '$.unit_id')
            WHERE ae.event_type IN ('RESOURCE_CHECK', 'RESOURCE_RELEASE')
              AND ae.clinical_time >= date('now', ?)
            GROUP BY cylinder_type
        """, (f'-{days} days',))

        for row in cursor.fetchall():
            cyl_type = row['cylinder_type']
            capacity_key = 'H' if 'H' in cyl_type else 'E'
            capacity = CYLINDER_CAPACITY.get(capacity_key, 680)

            level_drop = row['level_drop_percent'] or 0
            liters = (level_drop / 100) * capacity

            results['by_type'][cyl_type] = {
                'usage_events': row['usage_events'],
                'level_drop_percent': level_drop,
                'estimated_liters': round(liters, 1)
            }
            results['total_liters'] += liters

        results['total_liters'] = round(results['total_liters'], 1)
        return results

    finally:
        conn.close()


# =============================================================================
# Health Check
# =============================================================================

@router.get("/health")
async def analytics_health():
    """Analytics module health check."""
    return {
        "status": "healthy",
        "module": "analytics",
        "version": "1.0",
        "timestamp": datetime.now().isoformat()
    }
