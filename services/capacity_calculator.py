"""
Capacity Calculator Strategy Pattern
Based on: EQUIPMENT_ARCHITECTURE_REDESIGN.md

Provides pluggable calculation strategies for different equipment types,
avoiding eval() for security.

ChatGPT Review (2025-12-17):
- Added schema_version validation
- Added strict strategy validation for resilience equipment
- Added status filtering for availability
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ChatGPT: 定義可計入韌性時數的狀態
AVAILABLE_STATUSES: Set[str] = {'AVAILABLE', 'IN_USE'}
EXCLUDED_STATUSES: Set[str] = {'OFFLINE', 'MAINTENANCE', 'EMPTY'}
WARNING_STATUSES: Set[str] = {'CHARGING'}  # 計入但顯示警告

# Schema version for capacity_config
CURRENT_SCHEMA_VERSION = 1


class StrategyValidationError(Exception):
    """策略驗證錯誤 - 用於韌性設備的未知策略"""
    pass


@dataclass
class CalculationResult:
    """容量計算結果"""
    hours: float
    capacity_used: float
    capacity_total: float
    details: Dict[str, Any]
    excluded: bool = False  # ChatGPT: 標記是否因狀態被排除
    warning: Optional[str] = None  # ChatGPT: 警告訊息


class CapacityCalculator(ABC):
    """容量計算策略基類"""

    @abstractmethod
    def calculate_hours(self, level_percent: int, config: Dict[str, Any]) -> CalculationResult:
        """
        計算設備可用時數

        Args:
            level_percent: 當前存量百分比 (0-100)
            config: 設備類型的 capacity_config

        Returns:
            CalculationResult with hours and details
        """
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        """回傳策略名稱"""
        pass


class LinearDepletionCalculator(CapacityCalculator):
    """
    線性消耗計算 (電源站、氧氣瓶)

    公式: hours = hours_per_100pct × (level_percent / 100)

    適用於:
    - 行動電源站 (POWER_STATION)
    - 氧氣鋼瓶 (O2_CYLINDER_H, O2_CYLINDER_E)
    """

    def calculate_hours(self, level_percent: int, config: Dict[str, Any]) -> CalculationResult:
        hours_per_100pct = config.get('hours_per_100pct', 0)
        hours = hours_per_100pct * level_percent / 100

        # Calculate capacity details based on type
        if 'base_capacity_wh' in config:
            # Power station
            capacity_total = config['base_capacity_wh']
            capacity_used = capacity_total * level_percent / 100
            unit = 'Wh'
        elif 'capacity_liters' in config:
            # Oxygen cylinder
            capacity_total = config['capacity_liters']
            capacity_used = capacity_total * level_percent / 100
            unit = 'L'
        else:
            capacity_total = 100
            capacity_used = level_percent
            unit = '%'

        return CalculationResult(
            hours=round(hours, 2),
            capacity_used=round(capacity_used, 1),
            capacity_total=capacity_total,
            details={
                'strategy': 'LINEAR',
                'level_percent': level_percent,
                'hours_per_100pct': hours_per_100pct,
                'unit': unit
            }
        )

    def get_strategy_name(self) -> str:
        return 'LINEAR'


class FuelBasedCalculator(CapacityCalculator):
    """
    燃油消耗計算 (發電機)

    公式: hours = (tank_liters × level_percent / 100) / fuel_rate_lph

    適用於:
    - 發電機 (GENERATOR)
    """

    def calculate_hours(self, level_percent: int, config: Dict[str, Any]) -> CalculationResult:
        tank_liters = config.get('tank_liters', 0)
        fuel_rate_lph = config.get('fuel_rate_lph', 1)  # Avoid division by zero

        current_fuel = tank_liters * level_percent / 100
        hours = current_fuel / fuel_rate_lph if fuel_rate_lph > 0 else 0

        return CalculationResult(
            hours=round(hours, 2),
            capacity_used=round(current_fuel, 1),
            capacity_total=tank_liters,
            details={
                'strategy': 'FUEL_BASED',
                'level_percent': level_percent,
                'tank_liters': tank_liters,
                'fuel_rate_lph': fuel_rate_lph,
                'current_fuel_liters': round(current_fuel, 1),
                'unit': 'L'
            }
        )

    def get_strategy_name(self) -> str:
        return 'FUEL_BASED'


class PowerDependentCalculator(CapacityCalculator):
    """
    電力依賴計算 (氧氣濃縮機)

    本身無限供應，但受限於電力時數。
    實際時數需由外部提供電力時數。

    適用於:
    - 氧氣濃縮機 (O2_CONCENTRATOR)
    """

    def calculate_hours(self, level_percent: int, config: Dict[str, Any],
                        power_hours: Optional[float] = None) -> CalculationResult:
        # If power hours provided, use it as limit
        if power_hours is not None:
            hours = power_hours
        else:
            # Return infinity indicator (will be limited by power later)
            hours = float('inf')

        return CalculationResult(
            hours=hours if hours != float('inf') else 999999,
            capacity_used=level_percent,
            capacity_total=100,
            details={
                'strategy': 'POWER_DEPENDENT',
                'level_percent': level_percent,
                'requires_power': config.get('requires_power', True),
                'output_lpm': config.get('output_lpm', 5),
                'hours_unlimited': config.get('hours_unlimited', True),
                'power_limited_hours': power_hours,
                'unit': '%'
            }
        )

    def get_strategy_name(self) -> str:
        return 'POWER_DEPENDENT'


class NoCapacityCalculator(CapacityCalculator):
    """
    無容量計算 (一般設備)

    僅追蹤狀態，不計算時數。

    適用於:
    - 一般設備 (GENERAL, MONITOR, VENTILATOR, etc.)
    """

    def calculate_hours(self, level_percent: int, config: Dict[str, Any]) -> CalculationResult:
        return CalculationResult(
            hours=0,
            capacity_used=0,
            capacity_total=0,
            details={
                'strategy': 'NONE',
                'level_percent': level_percent,
                'note': 'Non-resilience equipment'
            }
        )

    def get_strategy_name(self) -> str:
        return 'NONE'


# =============================================================================
# Calculator Registry
# =============================================================================

_CALCULATORS: Dict[str, CapacityCalculator] = {
    'LINEAR': LinearDepletionCalculator(),
    'FUEL_BASED': FuelBasedCalculator(),
    'POWER_DEPENDENT': PowerDependentCalculator(),
    'NONE': NoCapacityCalculator(),
}


def get_calculator(strategy: str) -> CapacityCalculator:
    """
    取得對應策略的計算器

    Args:
        strategy: 策略名稱 (LINEAR, FUEL_BASED, POWER_DEPENDENT, NONE)

    Returns:
        CapacityCalculator instance
    """
    return _CALCULATORS.get(strategy.upper(), _CALCULATORS['NONE'])


def is_status_available(status: str) -> bool:
    """
    檢查狀態是否可計入韌性時數

    ChatGPT: 只有 AVAILABLE/IN_USE 才計入 hours
    """
    return status in AVAILABLE_STATUSES


def get_status_warning(status: str) -> Optional[str]:
    """
    取得狀態相關警告訊息

    ChatGPT: CHARGING 狀態需顯示警告
    """
    if status in WARNING_STATUSES:
        return f"設備狀態為 {status}，請於完成後更新"
    return None


def validate_strategy(strategy: str, is_resilience: bool = False) -> None:
    """
    驗證策略是否有效

    ChatGPT: 對韌性設備，未知策略應該報錯而非默默 fallback

    Args:
        strategy: 策略名稱
        is_resilience: 是否為韌性設備

    Raises:
        StrategyValidationError: 韌性設備使用未知策略時
    """
    if strategy.upper() not in _CALCULATORS:
        if is_resilience:
            raise StrategyValidationError(
                f"未知的計算策略: {strategy}。韌性設備必須使用已知策略 "
                f"({', '.join(_CALCULATORS.keys())})"
            )
        else:
            logger.warning(f"未知策略 {strategy}，將使用 NONE")


def calculate_equipment_hours(
    level_percent: int,
    capacity_config: Optional[str],
    power_hours: Optional[float] = None,
    status: Optional[str] = None,
    is_resilience: bool = False
) -> CalculationResult:
    """
    根據設備配置計算可用時數

    Args:
        level_percent: 當前存量百分比
        capacity_config: JSON 格式的容量配置
        power_hours: 電力可用時數 (用於 POWER_DEPENDENT 類型)
        status: 設備狀態 (ChatGPT: 用於判斷是否計入 hours)
        is_resilience: 是否為韌性設備 (ChatGPT: 用於嚴格策略驗證)

    Returns:
        CalculationResult
    """
    # ChatGPT: 檢查狀態是否應排除
    if status and status in EXCLUDED_STATUSES:
        return CalculationResult(
            hours=0,
            capacity_used=0,
            capacity_total=0,
            details={
                'strategy': 'EXCLUDED',
                'level_percent': level_percent,
                'status': status,
                'reason': f'狀態 {status} 不計入韌性時數'
            },
            excluded=True
        )

    if not capacity_config:
        return get_calculator('NONE').calculate_hours(level_percent, {})

    try:
        config = json.loads(capacity_config) if isinstance(capacity_config, str) else capacity_config
    except json.JSONDecodeError:
        return get_calculator('NONE').calculate_hours(level_percent, {})

    # ChatGPT: 驗證 schema_version
    schema_version = config.get('schema_version')
    if schema_version and schema_version > CURRENT_SCHEMA_VERSION:
        logger.warning(f"capacity_config schema_version {schema_version} > {CURRENT_SCHEMA_VERSION}")

    strategy = config.get('strategy', 'LINEAR')

    # ChatGPT: 對韌性設備嚴格驗證策略
    validate_strategy(strategy, is_resilience)

    calculator = get_calculator(strategy)

    # Special handling for POWER_DEPENDENT
    if strategy == 'POWER_DEPENDENT' and isinstance(calculator, PowerDependentCalculator):
        result = calculator.calculate_hours(level_percent, config, power_hours)
    else:
        result = calculator.calculate_hours(level_percent, config)

    # ChatGPT: 加入狀態警告
    if status:
        result.warning = get_status_warning(status)

    return result


# =============================================================================
# Aggregation Functions
# =============================================================================

def aggregate_unit_hours(
    units: list,
    capacity_config: Optional[str],
    power_hours: Optional[float] = None
) -> Dict[str, Any]:
    """
    聚合多個單位的總時數

    Args:
        units: 單位列表，每個單位需有 level_percent
        capacity_config: 設備類型的容量配置
        power_hours: 電力可用時數

    Returns:
        {
            'total_hours': float,
            'avg_level': float,
            'unit_count': int,
            'unit_details': list
        }
    """
    if not units:
        return {
            'total_hours': 0,
            'avg_level': 0,
            'unit_count': 0,
            'unit_details': []
        }

    unit_details = []
    total_hours = 0
    total_level = 0

    for unit in units:
        level = unit.get('level_percent', 0) or 0
        result = calculate_equipment_hours(level, capacity_config, power_hours)

        unit_details.append({
            'unit_id': unit.get('id'),
            'unit_serial': unit.get('unit_serial'),
            'unit_label': unit.get('unit_label'),
            'level_percent': level,
            'status': unit.get('status'),
            'hours': result.hours,
            'last_check': unit.get('last_check')
        })

        total_hours += result.hours
        total_level += level

    avg_level = total_level / len(units) if units else 0

    return {
        'total_hours': round(total_hours, 2),
        'avg_level': round(avg_level, 1),
        'unit_count': len(units),
        'unit_details': unit_details
    }
