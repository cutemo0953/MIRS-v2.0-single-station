# IRS Resilience Framework v1.0

> **Cross-System Specification for Endurance Calculation**
>
> Applies to: HIRS (Home), MIRS (Medical), CIRS (Community)
>
> Version: 1.0.0
> Date: 2025-12-15
> Status: Draft

---

## 1. Executive Summary

The IRS Resilience Framework provides a unified methodology for calculating **"Days/Hours of Supply (DoS)"** across all IRS-family systems. Instead of simply tracking inventory quantities, this framework converts static stock into actionable survival metrics.

### Core Question This Solves

| Before (Inventory) | After (Resilience) |
|--------------------|-------------------|
| "We have 5 oxygen cylinders" | "We can sustain 2 intubated patients for 11.5 hours" |
| "We have 80 CBC tests" | "Tests will expire in 3 days (even though we have enough volume for 10 days)" |
| "Generator fuel: 180 liters" | "Power for 60 hours, but oxygen concentrator stops when power stops" |

---

## 2. System Scope

| System | Target Users | Scale | Primary Endurance Items |
|--------|-------------|-------|------------------------|
| **HIRS** | Households | 1-10 persons | Water, Food, Power |
| **MIRS** | Medical stations | 1-50 patients | Oxygen, Generator Fuel, Reagents |
| **CIRS** | Evacuation shelters | 50-500 persons | Water, Food, Power, Medical supplies |

---

## 3. Core Concepts & Terminology

### 3.1 Glossary

| Term | Chinese | Definition | Example |
|------|---------|------------|---------|
| **Endurance Item** | 韌性物資 | Item requiring survival calculation | Oxygen, Water, Fuel |
| **Capacity** | 容量 | Usable content per unit | 1 H-type cylinder = 6,900 L |
| **Burn Rate** | 消耗率 | Consumption speed | 10 L/min, 3 L/hr |
| **Scenario Profile** | 情境設定 | Predefined consumption pattern | "2 intubated patients" |
| **Isolation Target** | 孤立天數 | Expected days without resupply | 5 days (typhoon) |
| **Status Level** | 警戒狀態 | SAFE / WARNING / CRITICAL | Based on vs isolation target |
| **Dependency** | 依賴項目 | Required resource for operation | O2 Concentrator → Power |
| **Weakest Link** | 最短木板 | Limiting factor for survival | MIN(volume_days, expiry_days) |

### 3.2 The Three Laws of Resilience Calculation

1. **Law of Capacity**: `Total Usable = Σ(quantity × capacity_per_unit)`
2. **Law of Dependency**: `Endurance(A) = MIN(Endurance(A), Endurance(Dependency_B))`
3. **Law of Weakest Link**: `Effective Days = MIN(volume_days, expiry_days)`

---

## 4. Data Schema (Shared)

### 4.1 Endurance Item Extension

```sql
-- Extension fields for any item table
ALTER TABLE items ADD COLUMN endurance_type TEXT;
-- Values: 'WATER', 'FOOD', 'POWER', 'OXYGEN', 'MEDICAL', 'REAGENT', NULL

ALTER TABLE items ADD COLUMN capacity_per_unit REAL;
-- The usable capacity per stock unit (liters, hours, servings)

ALTER TABLE items ADD COLUMN capacity_unit TEXT;
-- 'liters', 'hours', 'servings', 'tests'

ALTER TABLE items ADD COLUMN consumption_rate_type TEXT;
-- 'PER_PERSON_DAY', 'PER_PATIENT_HOUR', 'FIXED_RATE'

-- For perishables (reagents, opened items)
ALTER TABLE items ADD COLUMN valid_days_after_open INTEGER;
ALTER TABLE items ADD COLUMN opened_at DATETIME;
ALTER TABLE items ADD COLUMN tests_per_unit INTEGER;

-- ============================================================
-- CRITICAL: Resource Dependency
-- ============================================================
ALTER TABLE items ADD COLUMN depends_on_item_code TEXT;
-- If set, this item's endurance cannot exceed its dependency's endurance
-- Example: Oxygen Concentrator depends_on 'GEN-FUEL-001'

ALTER TABLE items ADD COLUMN dependency_note TEXT;
-- Human-readable explanation: "Requires generator power to operate"
```

### 4.2 Scenario Profiles Table

```sql
CREATE TABLE IF NOT EXISTS resilience_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,           -- '*' for global defaults
    endurance_type TEXT NOT NULL,       -- 'OXYGEN', 'POWER', 'WATER'
    profile_name TEXT NOT NULL,         -- Display name
    profile_name_en TEXT,               -- English name
    burn_rate REAL NOT NULL,            -- Consumption rate value
    burn_rate_unit TEXT NOT NULL,       -- 'L/min', 'L/hr', 'per_person_day'
    population_multiplier BOOLEAN DEFAULT 0, -- Rate × population?
    description TEXT,
    is_default BOOLEAN DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookup
CREATE INDEX idx_profiles_type ON resilience_profiles(endurance_type, station_id);
```

### 4.3 Station Resilience Configuration

```sql
CREATE TABLE IF NOT EXISTS resilience_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL UNIQUE,

    -- Isolation context
    isolation_target_days INTEGER DEFAULT 3,
    isolation_source TEXT DEFAULT 'manual', -- 'manual', 'weather_api'

    -- Population context
    population_count INTEGER DEFAULT 1,
    population_label TEXT,  -- '家庭人數', '收容人數', '插管患者數'

    -- Active profiles (foreign keys to resilience_profiles)
    oxygen_profile_id INTEGER,
    power_profile_id INTEGER,
    water_profile_id INTEGER,

    -- Alert thresholds (percentage of isolation target)
    threshold_safe REAL DEFAULT 1.2,      -- >=120% = SAFE
    threshold_warning REAL DEFAULT 1.0,   -- >=100% = WARNING
    -- Below 100% = CRITICAL

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);
```

### 4.4 Unit Standards Reference

```sql
CREATE TABLE IF NOT EXISTS unit_standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_type TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    display_name_en TEXT,
    capacity REAL NOT NULL,
    capacity_unit TEXT NOT NULL,
    category TEXT NOT NULL,  -- 'OXYGEN', 'FUEL', 'WATER'
    notes TEXT,
    region TEXT DEFAULT 'TW'  -- Regional standards
);

-- Taiwan common standards
INSERT INTO unit_standards VALUES
(1, 'O2_CYLINDER_E', 'E型氧氣瓶', 'E-Type O2 Cylinder', 680, 'liters', 'OXYGEN', '攜帶型，常見於救護車'),
(2, 'O2_CYLINDER_H', 'H型氧氣瓶', 'H-Type O2 Cylinder', 6900, 'liters', 'OXYGEN', '大型固定式'),
(3, 'O2_CYLINDER_D', 'D型氧氣瓶', 'D-Type O2 Cylinder', 400, 'liters', 'OXYGEN', '小型攜帶式'),
(4, 'FUEL_JERRY_20L', '20公升油桶', '20L Jerry Can', 20, 'liters', 'FUEL', '標準塑膠油桶'),
(5, 'FUEL_JERRY_10L', '10公升油桶', '10L Jerry Can', 10, 'liters', 'FUEL', '小型油桶'),
(6, 'FUEL_DRUM_200L', '200公升油桶', '200L Drum', 200, 'liters', 'FUEL', '大型儲油桶'),
(7, 'WATER_BOTTLE_2L', '2公升瓶裝水', '2L Water Bottle', 2, 'liters', 'WATER', '標準瓶裝'),
(8, 'WATER_BARREL_20L', '20公升桶裝水', '20L Water Barrel', 20, 'liters', 'WATER', '大桶裝');
```

---

## 5. Calculation Engine

### 5.1 Basic Endurance Formula

```python
def calculate_basic_endurance(
    total_capacity: float,
    burn_rate: float,
    population: int = 1,
    rate_is_per_person: bool = False
) -> float:
    """
    Basic endurance calculation.

    Args:
        total_capacity: Total usable capacity (liters, tests, etc.)
        burn_rate: Consumption rate per time unit
        population: Number of people/patients
        rate_is_per_person: If True, multiply rate by population

    Returns:
        Hours or days remaining (float)
    """
    effective_rate = burn_rate * population if rate_is_per_person else burn_rate

    if effective_rate <= 0:
        return float('inf')  # No consumption = infinite endurance

    return total_capacity / effective_rate
```

### 5.2 Oxygen-Specific Calculation

```python
def calculate_oxygen_hours(
    total_liters: float,
    flow_rate_lpm: float  # Liters per minute
) -> float:
    """
    Oxygen endurance in HOURS.

    Formula: Hours = Total Liters / (L/min × 60)

    Example:
        - 2 H-type cylinders = 13,800 L
        - 2 intubated patients @ 10 L/min each = 20 L/min
        - Hours = 13,800 / (20 × 60) = 11.5 hours
    """
    if flow_rate_lpm <= 0:
        return float('inf')

    return total_liters / (flow_rate_lpm * 60)
```

### 5.3 Power/Fuel Calculation

```python
def calculate_power_hours(
    total_fuel_liters: float,
    consumption_lph: float  # Liters per hour
) -> float:
    """
    Generator fuel endurance in HOURS.

    Formula: Hours = Total Fuel / L/hr

    Example:
        - 8 jerry cans (20L) + tank (20L) = 180L
        - Normal operation = 3 L/hr
        - Hours = 180 / 3 = 60 hours
    """
    if consumption_lph <= 0:
        return float('inf')

    return total_fuel_liters / consumption_lph
```

### 5.4 Reagent Calculation (Weakest Link Logic)

```python
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

@dataclass
class ReagentEndurance:
    volume_days: float
    expiry_days: Optional[float]
    effective_days: float
    limited_by: str  # 'VOLUME' or 'EXPIRY'
    warning: Optional[str]

def calculate_reagent_endurance(
    tests_remaining: int,
    tests_per_day: float,
    opened_at: Optional[datetime],
    valid_days_after_open: Optional[int]
) -> ReagentEndurance:
    """
    Reagent endurance with open-vial expiry logic.

    The "Weakest Link" principle:
    Effective Days = MIN(volume_based_days, expiry_based_days)

    Example:
        - 80 tests remaining
        - Using 15 tests/day (disaster surge)
        - Volume days = 80/15 = 5.3 days
        - BUT: Opened 25 days ago, valid for 28 days
        - Expiry days = 28 - 25 = 3 days
        - Effective = MIN(5.3, 3) = 3 days (LIMITED BY EXPIRY)
    """
    # Volume-based calculation
    if tests_per_day > 0:
        volume_days = tests_remaining / tests_per_day
    else:
        volume_days = float('inf')

    # Expiry-based calculation (if opened)
    expiry_days = None
    if opened_at and valid_days_after_open:
        days_since_open = (datetime.now() - opened_at).days
        expiry_days = max(0, valid_days_after_open - days_since_open)

    # Determine effective days and limiting factor
    if expiry_days is not None:
        effective_days = min(volume_days, expiry_days)
        limited_by = 'EXPIRY' if expiry_days < volume_days else 'VOLUME'

        warning = None
        if limited_by == 'EXPIRY':
            warning = f"效期限制：試劑將於 {expiry_days:.0f} 天後失效（開封已 {days_since_open} 天）"
    else:
        effective_days = volume_days
        limited_by = 'VOLUME'
        warning = None

    return ReagentEndurance(
        volume_days=round(volume_days, 1),
        expiry_days=round(expiry_days, 1) if expiry_days else None,
        effective_days=round(effective_days, 1),
        limited_by=limited_by,
        warning=warning
    )
```

### 5.5 Dependency Chain Resolution (CRITICAL)

```python
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class EnduranceResult:
    item_code: str
    item_name: str
    endurance_type: str
    raw_hours: float           # Before dependency adjustment
    effective_hours: float     # After dependency adjustment
    depends_on: Optional[str]
    dependency_limited: bool
    dependency_warning: Optional[str]

def resolve_dependency_chain(
    items: Dict[str, dict],
    endurance_results: Dict[str, float]
) -> Dict[str, EnduranceResult]:
    """
    Resolve resource dependencies using the Dependency Law.

    Law: Endurance(A) = MIN(Endurance(A), Endurance(Dependency_B))

    Example:
        - Oxygen Concentrator: raw_hours = ∞ (as long as it has power)
        - Generator Fuel: endurance = 60 hours
        - Concentrator depends_on Generator
        - Effective Concentrator hours = MIN(∞, 60) = 60 hours

    This prevents the dangerous scenario where system shows
    "Oxygen: SAFE" when generator fuel will run out in 10 hours.
    """
    results = {}

    for item_code, item_data in items.items():
        raw_hours = endurance_results.get(item_code, float('inf'))
        depends_on = item_data.get('depends_on_item_code')

        effective_hours = raw_hours
        dependency_limited = False
        dependency_warning = None

        if depends_on and depends_on in endurance_results:
            dependency_hours = endurance_results[depends_on]

            if dependency_hours < raw_hours:
                effective_hours = dependency_hours
                dependency_limited = True
                dependency_warning = (
                    f"⚠️ 受限於 {items[depends_on]['item_name']}："
                    f"當 {items[depends_on]['item_name']} 耗盡時，"
                    f"{item_data['item_name']} 將同時停止運作"
                )

        results[item_code] = EnduranceResult(
            item_code=item_code,
            item_name=item_data['item_name'],
            endurance_type=item_data.get('endurance_type', 'OTHER'),
            raw_hours=raw_hours,
            effective_hours=effective_hours,
            depends_on=depends_on,
            dependency_limited=dependency_limited,
            dependency_warning=dependency_warning
        )

    return results
```

### 5.6 Status Level Determination

```python
from enum import Enum

class StatusLevel(Enum):
    SAFE = "SAFE"           # Green: Can survive with buffer
    WARNING = "WARNING"     # Yellow: Can survive, but tight
    CRITICAL = "CRITICAL"   # Red: Cannot survive isolation period
    UNKNOWN = "UNKNOWN"     # Gray: Cannot calculate

def determine_status(
    hours_remaining: float,
    isolation_hours: float,
    threshold_safe: float = 1.2,    # 120% = SAFE
    threshold_warning: float = 1.0  # 100% = WARNING
) -> StatusLevel:
    """
    Compare endurance against isolation target.

    Status Logic:
        - SAFE:     hours >= isolation × 1.2 (20% buffer)
        - WARNING:  hours >= isolation × 1.0 (can survive, but no buffer)
        - CRITICAL: hours < isolation (cannot survive)

    Example:
        - Isolation target: 120 hours (5 days)
        - Oxygen remaining: 11.5 hours
        - Ratio: 11.5 / 120 = 0.096 (9.6%)
        - Status: CRITICAL (cannot survive isolation period)
    """
    if isolation_hours <= 0:
        return StatusLevel.UNKNOWN

    ratio = hours_remaining / isolation_hours

    if ratio >= threshold_safe:
        return StatusLevel.SAFE
    elif ratio >= threshold_warning:
        return StatusLevel.WARNING
    else:
        return StatusLevel.CRITICAL
```

---

## 6. API Response Format (Shared)

### 6.1 Standard Resilience Status Response

```json
{
  "system": "MIRS",
  "version": "1.0",
  "station_id": "LANYU-HC-01",
  "station_name": "蘭嶼衛生所",
  "calculated_at": "2025-12-15T14:30:00+08:00",

  "context": {
    "isolation_target_days": 5,
    "isolation_target_hours": 120,
    "isolation_source": "manual",
    "population": {
      "count": 3,
      "label": "插管患者數"
    }
  },

  "lifelines": [
    {
      "item_code": "O2-SUPPLY",
      "name": "氧氣供應",
      "type": "OXYGEN",
      "inventory": {
        "items": [
          {"name": "H型氧氣瓶", "qty": 2, "capacity_each": 6900, "unit": "liters"}
        ],
        "total_capacity": 13800,
        "capacity_unit": "liters"
      },
      "consumption": {
        "profile_name": "2位插管患者",
        "burn_rate": 20,
        "burn_rate_unit": "L/min",
        "burn_rate_display": "20 L/min"
      },
      "endurance": {
        "raw_hours": 11.5,
        "effective_hours": 11.5,
        "effective_days": 0.48
      },
      "dependency": null,
      "status": "CRITICAL",
      "vs_isolation": {
        "ratio": 0.096,
        "can_survive": false,
        "gap_hours": 108.5,
        "gap_display": "缺口 108.5 小時"
      },
      "message": "氧氣僅剩 11.5 小時，無法撐過 5 天斷航期"
    },
    {
      "item_code": "GEN-POWER",
      "name": "發電機電力",
      "type": "POWER",
      "inventory": {
        "items": [
          {"name": "20L油桶", "qty": 8, "capacity_each": 20, "unit": "liters"},
          {"name": "發電機油箱", "qty": 1, "capacity_each": 20, "unit": "liters"}
        ],
        "total_capacity": 180,
        "capacity_unit": "liters"
      },
      "consumption": {
        "profile_name": "標準運作",
        "burn_rate": 3.0,
        "burn_rate_unit": "L/hr",
        "burn_rate_display": "3.0 L/hr"
      },
      "endurance": {
        "raw_hours": 60,
        "effective_hours": 60,
        "effective_days": 2.5
      },
      "dependency": null,
      "status": "WARNING",
      "vs_isolation": {
        "ratio": 0.5,
        "can_survive": false,
        "gap_hours": 60,
        "gap_display": "缺口 60 小時"
      },
      "message": "油料可撐 60 小時 (2.5天)，建議補充"
    },
    {
      "item_code": "O2-CONCENTRATOR",
      "name": "氧氣製造機",
      "type": "OXYGEN",
      "inventory": {
        "items": [
          {"name": "氧氣製造機 5L/min", "qty": 1, "capacity_each": null, "unit": "device"}
        ],
        "total_capacity": null,
        "note": "Continuous supply while powered"
      },
      "consumption": {
        "profile_name": "持續供氧",
        "burn_rate": 5,
        "burn_rate_unit": "L/min",
        "burn_rate_display": "5 L/min (continuous)"
      },
      "endurance": {
        "raw_hours": "Infinity",
        "effective_hours": 60,
        "effective_days": 2.5
      },
      "dependency": {
        "depends_on": "GEN-POWER",
        "dependency_name": "發電機電力",
        "is_limiting": true,
        "warning": "⚠️ 受限於發電機電力：當油料耗盡時，氧氣製造機將停止運作"
      },
      "status": "WARNING",
      "vs_isolation": {
        "ratio": 0.5,
        "can_survive": false
      },
      "message": "製造機本身無限供氧，但受限於發電機（60小時）"
    }
  ],

  "reagents": [
    {
      "item_code": "REA-CBC-001",
      "name": "CBC 試劑組",
      "inventory": {
        "kits_remaining": 3,
        "tests_per_kit": 50,
        "tests_remaining": 80,
        "opened_at": "2025-11-20T09:00:00",
        "valid_days_after_open": 28
      },
      "consumption": {
        "profile_name": "災時增量",
        "tests_per_day": 15
      },
      "endurance": {
        "days_by_volume": 5.3,
        "days_by_expiry": 3,
        "effective_days": 3,
        "limited_by": "EXPIRY"
      },
      "status": "WARNING",
      "alert": "⚠️ 效期限制：試劑將於 3 天後失效（開封已 25 天，雖仍有 80 次測試量）"
    }
  ],

  "summary": {
    "overall_status": "CRITICAL",
    "weakest_link": {
      "item": "氧氣供應",
      "hours": 11.5,
      "type": "OXYGEN"
    },
    "can_survive_isolation": false,
    "critical_items": ["O2-SUPPLY"],
    "warning_items": ["GEN-POWER", "O2-CONCENTRATOR", "REA-CBC-001"],
    "recommendation": "緊急請求氧氣鋼瓶補給，缺口約 109 小時用量（約 9 瓶 H 型）"
  }
}
```

---

## 7. Domain-Specific Configurations

### 7.1 HIRS (Home Inventory Resilience System)

```yaml
system: HIRS
target_users: Households
scale: 1-10 persons

endurance_types:
  - WATER
  - FOOD
  - POWER

default_profiles:
  WATER:
    - name: "正常用水"
      burn_rate: 3
      burn_rate_unit: "liters/person/day"
      population_multiplier: true
    - name: "節約用水"
      burn_rate: 2
      burn_rate_unit: "liters/person/day"
      population_multiplier: true

  FOOD:
    - name: "正常飲食"
      burn_rate: 3
      burn_rate_unit: "meals/person/day"
      population_multiplier: true
    - name: "配給制"
      burn_rate: 2
      burn_rate_unit: "meals/person/day"
      population_multiplier: true

default_isolation_days: 3  # Taiwan disaster preparedness standard
population_label: "家庭人數"

ui_simplification:
  - Hide advanced profile editing
  - Show only 2 scenario options: "正常生活" vs "求生模式"
  - Pre-calculate everything based on family size
```

### 7.2 MIRS (Medical Inventory Resilience System)

```yaml
system: MIRS
target_users: Medical stations, Island health centers
scale: 1-50 patients

endurance_types:
  - OXYGEN
  - POWER
  - REAGENT

default_profiles:
  OXYGEN:
    - name: "1位插管患者"
      burn_rate: 10
      burn_rate_unit: "L/min"
      description: "標準機械通氣 10 L/min"
    - name: "2位插管患者"
      burn_rate: 20
      burn_rate_unit: "L/min"
    - name: "3位插管患者"
      burn_rate: 30
      burn_rate_unit: "L/min"
    - name: "面罩供氧(3人)"
      burn_rate: 15
      burn_rate_unit: "L/min"
      description: "每人約 5 L/min"
    - name: "自訂流速"
      burn_rate: null  # User input
      burn_rate_unit: "L/min"

  POWER:
    - name: "省電模式"
      burn_rate: 1.5
      burn_rate_unit: "L/hr"
      description: "僅照明+呼吸器"
    - name: "標準運作"
      burn_rate: 3.0
      burn_rate_unit: "L/hr"
      description: "照明+冷藏+基本設備"
    - name: "全速運轉"
      burn_rate: 5.0
      burn_rate_unit: "L/hr"
      description: "含空調+檢驗設備"
    - name: "自訂油耗"
      burn_rate: null
      burn_rate_unit: "L/hr"

  REAGENT:
    - name: "平時"
      tests_per_day: 5
    - name: "災時增量"
      tests_per_day: 15
    - name: "大量傷患"
      tests_per_day: 30

default_isolation_days: 5  # Island isolation typical duration
population_label: "插管患者數"

special_features:
  - Resource dependency tracking (O2 concentrator → Power)
  - Open-vial expiry tracking for reagents
  - User-editable profiles per station
```

### 7.3 CIRS (Community Inventory Resilience System)

```yaml
system: CIRS
target_users: Evacuation shelters, Community distribution hubs
scale: 50-500 persons

endurance_types:
  - WATER
  - FOOD
  - POWER
  - MEDICAL

default_profiles:
  WATER:
    - name: "標準配給"
      burn_rate: 3
      burn_rate_unit: "liters/person/day"
      population_multiplier: true
    - name: "節約配給"
      burn_rate: 2
      burn_rate_unit: "liters/person/day"
      population_multiplier: true

  FOOD:
    - name: "三餐配給"
      burn_rate: 3
      burn_rate_unit: "meals/person/day"
      population_multiplier: true
    - name: "兩餐配給"
      burn_rate: 2
      burn_rate_unit: "meals/person/day"
      population_multiplier: true

  POWER:
    - name: "避難所基本"
      burn_rate: 5.0
      burn_rate_unit: "L/hr"
      description: "照明+充電站+廣播"
    - name: "避難所全開"
      burn_rate: 10.0
      burn_rate_unit: "L/hr"
      description: "含空調+熱食設備"

default_isolation_days: 3
population_label: "收容人數"

special_features:
  - Dynamic population tracking (evacuees arriving/leaving)
  - Integration with HIRS for household-level tracking
  - Distribution QR code generation
```

---

## 8. UI/UX Guidelines

### 8.1 Dashboard Layout (Shared Pattern)

```
┌─────────────────────────────────────────────────────────────┐
│  🩺 韌性估算 Resilience Calculator                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🌪️ 預估孤立天數: [  5  ] 天    👥 人數: [  3  ] 人         │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  🔴 警示：氧氣存量無法撐過孤立期！                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │   🫁 氧氣         │  │   ⚡ 電力        │                │
│  │   ████░░░░░░░░░  │  │   ██████░░░░░░░  │                │
│  │                  │  │                  │                │
│  │   11.5 小時      │  │   60 小時        │                │
│  │   🔴 CRITICAL    │  │   🟡 WARNING     │                │
│  │                  │  │                  │                │
│  │   [2位插管患者▾] │  │   [標準運作  ▾]  │                │
│  │   20 L/min      │  │   3.0 L/hr      │                │
│  │                  │  │                  │                │
│  │   ⚠️ 需補: 9瓶H型 │  │   ⚠️ 缺口: 60hr  │                │
│  └──────────────────┘  └──────────────────┘                │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  🧪 試劑/耗材監控                                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 項目      庫存   用量天數  效期天數  有效天數  狀態   │   │
│  │ CBC試劑   80次   5.3天    ⚠️3天    3天      🟡     │   │
│  │ 血糖試紙  200次  12天     —        12天     🟢     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 Color Coding (Universal)

| Status | Color | Hex | Meaning |
|--------|-------|-----|---------|
| SAFE | Green | `#10B981` | Supply > 120% of isolation target |
| WARNING | Yellow | `#F59E0B` | Supply 100-120% of isolation target |
| CRITICAL | Red | `#EF4444` | Supply < 100% of isolation target |
| UNKNOWN | Gray | `#6B7280` | Cannot calculate |

### 8.3 Dependency Warning Display

When an item is limited by its dependency, show:

```
┌──────────────────────────────────────┐
│  🫁 氧氣製造機                        │
│  ⚠️ 受限於：發電機電力                │
│                                      │
│  製造機容量: ∞ (持續供氧)             │
│  有效時數: 60 小時 ← 取決於油料       │
│                                      │
│  💡 當發電機停止，製造機也會停止      │
└──────────────────────────────────────┘
```

---

## 9. Implementation Priority

| Phase | System | Scope | Priority |
|-------|--------|-------|----------|
| **P1** | MIRS | Full implementation with dependency logic | 🔴 Critical |
| **P2** | HIRS | Retrofit existing survivalDays, simplified UI | 🟡 High |
| **P3** | CIRS | Design phase, population tracking | 🟢 Future |

### P1: MIRS Implementation Checklist

- [ ] Database schema migration
- [ ] Unit standards seed data (oxygen cylinders, fuel containers)
- [ ] Default profiles seed data
- [ ] Calculation service with dependency resolution
- [ ] API endpoints (`GET /api/resilience/status`, etc.)
- [ ] Dashboard tab UI
- [ ] Profile management UI
- [ ] Manual "Mark as Opened" for reagents
- [ ] Integration tests

### P2: HIRS Retrofit Checklist

- [ ] Align data model with framework
- [ ] Add scenario profile support (simplified: 2 options)
- [ ] Add isolation target input
- [ ] Update survivalDays calculation to use new engine
- [ ] Update dashboard UI to show status levels
- [ ] Translation updates (zh-TW, en, ja)

---

## 10. MIRS Implementation Notes (v1.2.2)

> This section documents the actual implementation in MIRS v1.4.2-plus single-station system.

### 10.1 Equipment-Based vs Inventory-Based Calculation

**Key Insight**: In MIRS, resilience equipment (oxygen cylinders, generators) are tracked in the **equipment** table, not the **inventory** table. The v1.2.2 update changed the resilience calculation to use equipment data as the primary source.

```
┌─────────────────────────────────────────────────────────────┐
│  Before v1.2.2 (Inventory-based)                            │
├─────────────────────────────────────────────────────────────┤
│  Resilience → inventory table → stock quantity              │
│  Problem: Equipment quantities ≠ Inventory quantities       │
│  User changed equipment, resilience didn't update           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  After v1.2.2 (Equipment-based)                             │
├─────────────────────────────────────────────────────────────┤
│  Resilience → equipment table → quantity × power_level%     │
│  Changes in equipment quantities immediately affect hours   │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 Equipment Capacity Mapping

The `EQUIPMENT_CAPACITY_MAP` constant in `resilience_service.py` maps equipment IDs to their capacities:

```python
EQUIPMENT_CAPACITY_MAP = {
    # Oxygen equipment
    'RESP-001': (6900, 'liters', 'H型氧氣瓶', 'OXYGEN'),      # H-type cylinder
    'EMER-EQ-006': (680, 'liters', 'E型氧氣瓶', 'OXYGEN'),    # E-type cylinder
    'RESP-002': (None, 'L/min', '氧氣濃縮機', 'OXYGEN'),      # Concentrator (infinite with power)
    # Power equipment
    'UTIL-002': (50, 'liters', '發電機油箱', 'POWER'),        # Generator tank (50L default)
    'UTIL-001': (20, 'liters', '行動電源站備用油', 'POWER'),  # Mobile power station
    'EQ-010': (20, 'liters', '備用油桶', 'POWER'),            # Reserve fuel
}
```

### 10.3 Power Level Affects Effective Capacity

Equipment's `power_level` field (used for equipment checks) now affects the effective capacity calculation:

```
Effective Capacity = Unit Capacity × Quantity × (power_level / 100)
```

**Example**:
- 5 H-type cylinders (RESP-001) with 95% check status
- Effective = 6,900L × 5 × 0.95 = **32,775L**

### 10.4 Population Zero Handling

When `population_count = 0` (no intubated patients):
- Oxygen burn rate = 0 L/min
- Oxygen hours = ∞ (infinite)
- This allows modeling scenarios without oxygen-dependent patients

### 10.5 Data Flow

```
User changes equipment quantity or power_level
           ↓
equipment table updated
           ↓
User views Resilience tab (or clicks refresh)
           ↓
_get_equipment_stock() reads equipment table
           ↓
EQUIPMENT_CAPACITY_MAP lookup for capacity
           ↓
Applies power_level percentage
           ↓
Calculates hours with burn rate × population
           ↓
UI displays updated resilience hours
```

---

## 11. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-15 | Initial framework specification |
| 1.0.1 | 2025-12-16 | Added MIRS v1.2.2 implementation notes |

---

## Appendix A: Oxygen Flow Rate Reference

| Patient Condition | Typical Flow Rate | Notes |
|-------------------|-------------------|-------|
| Nasal Cannula | 1-6 L/min | Low-flow oxygen |
| Simple Face Mask | 5-10 L/min | Moderate oxygen needs |
| Non-Rebreather Mask | 10-15 L/min | High-flow oxygen |
| Mechanical Ventilation | 8-15 L/min | Varies by FiO2 setting |
| CPAP/BiPAP | 10-20 L/min | Continuous positive airway |

## Appendix B: Generator Fuel Consumption Reference

| Load Type | Typical Consumption | Example Equipment |
|-----------|---------------------|-------------------|
| Minimal | 1-2 L/hr | Lights + Ventilator only |
| Normal | 3-4 L/hr | + Refrigerator + Basic equipment |
| Heavy | 5-8 L/hr | + Air conditioning + Lab equipment |
| Full | 8-12 L/hr | Operating room level load |

---

*Document maintained by IRS Development Team*
*For questions: [dev@irs-system.org]*
