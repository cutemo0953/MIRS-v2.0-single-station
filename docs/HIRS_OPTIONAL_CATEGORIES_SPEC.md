# HIRS Feature Spec: Optional Categories & Custom Gear Tags

**Version**: 1.0
**Date**: 2025-12-17
**Status**: Approved for Development

---

## 1. Overview

### 1.1 User Feedback
Users want to track items beyond the core 5 categories (Water, Food, Power, Medical, Gear), specifically:
- Pet supplies
- Baby/infant items
- Hygiene/sanitation products
- Important documents

### 1.2 Design Principles
1. **UI Consistency**: System-defined icons, no user-uploaded images
2. **Controlled Flexibility**: Optional categories are toggleable, not freeform
3. **Calculation Integrity**: Only appropriate categories affect resilience scores
4. **Gear Expandability**: "備 (Gear)" allows custom sub-tags for personal organization

---

## 2. Category Architecture

### 2.1 Category Types

| Type | Calculation | Examples |
|------|-------------|----------|
| `consumable` | Days = Quantity ÷ Daily Rate | Water, Food, Pet Food, Diapers |
| `equipment` | Binary (Have/Don't Have) | Flashlight, Radio, First Aid Kit |
| `checklist` | Completion % only | Documents, Certificates |

### 2.2 Category Definitions

```typescript
// constants/categories.ts

export type CategoryType = 'consumable' | 'equipment' | 'checklist';

export interface CategoryDefinition {
  id: string;
  label: I18nLabel;
  icon: string;              // Heroicon name
  isCore: boolean;           // true = always visible, cannot disable
  type: CategoryType;
  default: boolean;          // For optional categories: show by default?
  dailyConsumption?: {       // Only for consumables
    perPerson?: number;      // Per person per day
    perUnit?: number;        // Per pet/baby per day
    unitLabel?: I18nLabel;   // "隻", "位"
  };
  allowCustomTags?: boolean; // Only "gear" has this = true
}

export interface I18nLabel {
  'zh-TW': string;
  'zh-CN': string;
  'en': string;
}

export const CATEGORY_DEFINITIONS: Record<string, CategoryDefinition> = {
  // ═══════════════════════════════════════════════════════════
  // CORE CATEGORIES (Always visible, cannot disable)
  // ═══════════════════════════════════════════════════════════

  water: {
    id: 'water',
    label: { 'zh-TW': '水', 'zh-CN': '水', 'en': 'Water' },
    icon: 'Droplet',         // Heroicons: water drop
    isCore: true,
    type: 'consumable',
    default: true,
    dailyConsumption: {
      perPerson: 3,          // 3 liters per person per day
    }
  },

  food: {
    id: 'food',
    label: { 'zh-TW': '糧', 'zh-CN': '粮', 'en': 'Food' },
    icon: 'Cube',
    isCore: true,
    type: 'consumable',
    default: true,
    dailyConsumption: {
      perPerson: 2000,       // 2000 kcal per person per day (items need calorie field)
    }
  },

  power: {
    id: 'power',
    label: { 'zh-TW': '電', 'zh-CN': '电', 'en': 'Power' },
    icon: 'Bolt',
    isCore: true,
    type: 'equipment',
    default: true,
  },

  medical: {
    id: 'medical',
    label: { 'zh-TW': '醫', 'zh-CN': '医', 'en': 'Medical' },
    icon: 'Heart',
    isCore: true,
    type: 'equipment',
    default: true,
  },

  gear: {
    id: 'gear',
    label: { 'zh-TW': '備', 'zh-CN': '备', 'en': 'Gear' },
    icon: 'Cog6Tooth',
    isCore: true,
    type: 'equipment',
    default: true,
    allowCustomTags: true,   // ← Only gear allows custom sub-tags
  },

  // ═══════════════════════════════════════════════════════════
  // OPTIONAL CATEGORIES (User can toggle on/off in Settings)
  // ═══════════════════════════════════════════════════════════

  pets: {
    id: 'pets',
    label: { 'zh-TW': '寵', 'zh-CN': '宠', 'en': 'Pets' },
    icon: 'PawPrint',        // Custom or use a suitable alternative
    isCore: false,
    type: 'consumable',
    default: false,
    dailyConsumption: {
      perUnit: 0.3,          // 0.3 kg per pet per day (average)
      unitLabel: { 'zh-TW': '隻', 'zh-CN': '只', 'en': 'pet(s)' }
    }
  },

  baby: {
    id: 'baby',
    label: { 'zh-TW': '嬰', 'zh-CN': '婴', 'en': 'Baby' },
    icon: 'Baby',            // Custom icon needed
    isCore: false,
    type: 'consumable',
    default: false,
    dailyConsumption: {
      perUnit: null,         // Complex: diapers, formula calculated separately
      unitLabel: { 'zh-TW': '位', 'zh-CN': '位', 'en': 'infant(s)' }
    }
  },

  hygiene: {
    id: 'hygiene',
    label: { 'zh-TW': '衛', 'zh-CN': '卫', 'en': 'Hygiene' },
    icon: 'Sparkles',
    isCore: false,
    type: 'checklist',       // ← Does NOT affect resilience days
    default: false,
  },

  docs: {
    id: 'docs',
    label: { 'zh-TW': '文', 'zh-CN': '文', 'en': 'Docs' },
    icon: 'DocumentText',
    isCore: false,
    type: 'checklist',       // ← Does NOT affect resilience days
    default: false,
  },
};
```

---

## 3. Custom Tags for Gear (備)

### 3.1 Purpose
Allow users to organize their gear into sub-categories without affecting the main category structure.

### 3.2 Predefined Tag Templates

```typescript
// constants/gearTags.ts

export interface GearTagTemplate {
  id: string;
  label: I18nLabel;
  icon: string;           // Heroicon name
  isSystem: boolean;      // true = predefined, false = user-created
}

export const GEAR_TAG_TEMPLATES: GearTagTemplate[] = [
  // --- Predefined (System) ---
  {
    id: 'camping',
    label: { 'zh-TW': '露營', 'zh-CN': '露营', 'en': 'Camping' },
    icon: 'Fire',
    isSystem: true
  },
  {
    id: 'hiking',
    label: { 'zh-TW': '登山', 'zh-CN': '登山', 'en': 'Hiking' },
    icon: 'Mountain',      // Custom or MapPin
    isSystem: true
  },
  {
    id: 'car',
    label: { 'zh-TW': '車載', 'zh-CN': '车载', 'en': 'Vehicle' },
    icon: 'Truck',
    isSystem: true
  },
  {
    id: 'office',
    label: { 'zh-TW': '辦公室', 'zh-CN': '办公室', 'en': 'Office' },
    icon: 'Briefcase',
    isSystem: true
  },
  {
    id: 'communication',
    label: { 'zh-TW': '通訊', 'zh-CN': '通讯', 'en': 'Comms' },
    icon: 'Radio',
    isSystem: true
  },
  {
    id: 'tools',
    label: { 'zh-TW': '工具', 'zh-CN': '工具', 'en': 'Tools' },
    icon: 'Wrench',
    isSystem: true
  },
  {
    id: 'lighting',
    label: { 'zh-TW': '照明', 'zh-CN': '照明', 'en': 'Lighting' },
    icon: 'Flashlight',    // Or LightBulb
    isSystem: true
  },
  {
    id: 'shelter',
    label: { 'zh-TW': '避難', 'zh-CN': '避难', 'en': 'Shelter' },
    icon: 'Home',
    isSystem: true
  },
];

// Icon options for user-created tags
export const AVAILABLE_TAG_ICONS = [
  'Star', 'Heart', 'Flag', 'Bookmark', 'Tag',
  'Folder', 'Archive', 'Box', 'Package',
  'Key', 'Lock', 'Shield',
  'Sun', 'Moon', 'Cloud',
  'Map', 'Compass', 'Globe',
  'Camera', 'Phone', 'Laptop',
  'Music', 'Gift', 'Puzzle'
];
```

### 3.3 User Settings Storage

```typescript
// stores/settings.ts

interface UserSettings {
  // ... existing settings ...

  // Active categories (IDs of enabled optional categories)
  activeCategories: string[];  // Default: ['water','food','power','medical','gear']

  // Custom gear tags created by user
  customGearTags: CustomGearTag[];

  // Number of pets (for calculation)
  petCount: number;           // Default: 0

  // Number of infants (for calculation)
  infantCount: number;        // Default: 0
}

interface CustomGearTag {
  id: string;                 // UUID
  label: string;              // User-defined name (current language only)
  icon: string;               // Selected from AVAILABLE_TAG_ICONS
  createdAt: string;
}
```

---

## 4. UI Design

### 4.1 Category Filter Bar (Top of Inventory)

```
┌─────────────────────────────────────────────────────────────────┐
│  [全部]  [💧水]  [🍚糧]  [⚡電]  [❤️醫]  [⚙️備▾]  [🐕寵]  [📄文]  │
│                                          ↑                      │
│                                    Dark bg, expandable          │
└─────────────────────────────────────────────────────────────────┘
```

**Design Rules:**
- Core categories: Light background, colored icon
- **Gear (備)**: Dark background (`bg-gray-800`), white icon, with dropdown indicator `▾`
- Optional categories: Same style as core, but only shown if enabled
- Tapping "備" expands sub-tag dropdown

### 4.2 Gear Sub-Tag Dropdown

```
┌─────────────────────────────────────────────────────────────────┐
│                              ┌──────────────────────────┐       │
│  [全部] [💧水] [🍚糧] [⚡電] │  ⚙️ 備 ▾                  │ [🐕寵] │
│                              ├──────────────────────────┤       │
│                              │  全部備品 (23)           │       │
│                              │  ─────────────────────   │       │
│                              │  🏕️ 露營 (8)             │       │
│                              │  🚗 車載 (5)             │       │
│                              │  🔦 照明 (4)             │       │
│                              │  📻 通訊 (3)             │       │
│                              │  🔧 工具 (3)             │       │
│                              │  ─────────────────────   │       │
│                              │  ⭐ 我的收藏 (2) [自訂]   │       │
│                              │  ─────────────────────   │       │
│                              │  ＋ 新增標籤...           │       │
│                              └──────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Settings Page - Category Configuration

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚙️ 設定                                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📂 分類顯示設定                                                 │
│  ───────────────────────────────────────────────────────────    │
│                                                                 │
│  核心分類 (無法關閉)                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 💧 水    🍚 糧    ⚡ 電    ❤️ 醫    ⚙️ 備               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  選用分類                                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 🐕 寵物        [====○    ]  OFF                         │   │
│  │    追蹤寵物糧食天數                                       │   │
│  │    寵物數量: [ 2 ] 隻                                    │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ 👶 嬰幼兒      [    ○====]  ON                          │   │
│  │    追蹤尿布、奶粉等消耗品                                  │   │
│  │    嬰幼兒數量: [ 1 ] 位                                  │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ 🧹 衛生        [====○    ]  OFF                         │   │
│  │    追蹤衛生用品 (不計入韌性天數)                           │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ 📄 文件        [====○    ]  OFF                         │   │
│  │    追蹤重要文件備份 (不計入韌性天數)                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 Create Custom Gear Tag Modal

```
┌─────────────────────────────────────────────────────────────────┐
│  ✕                        新增標籤                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  標籤名稱                                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 我的收藏                                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  選擇圖示                                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ [⭐] [❤️] [🚩] [🔖] [🏷️] [📁] [📦] [🔑] [🛡️]          │   │
│  │ [☀️] [🌙] [☁️] [🗺️] [🧭] [🌐] [📷] [📱] [💻]          │   │
│  │ [🎵] [🎁] [🧩]                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│                                        [取消]  [建立]           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Resilience Calculation Display

### 5.1 Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🏠 家庭韌性總覽                                      [ℹ️ 說明]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                    最短維生天數                            │ │
│  │                                                           │ │
│  │                      ⚠️ 5 天                              │ │
│  │                   (受限於: 寵物糧)                         │ │
│  │                                                           │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  👨‍👩‍👧 人員維生 (3人)                                    7 天    │
│  ├─ 💧 飲用水     ████████████░░░░░░░░  12 天                  │
│  └─ 🍚 糧食       ███████░░░░░░░░░░░░░  7 天  ← 人員最短       │
│                                                                 │
│  🐕 寵物維生 (2隻)                                    5 天 ⚠️   │
│  └─ 🦴 寵物糧     █████░░░░░░░░░░░░░░░  5 天  ← 整體最短       │
│                                                                 │
│  👶 嬰幼兒 (1位)                                      8 天      │
│  ├─ 🍼 奶粉       ██████████░░░░░░░░░░  10 天                  │
│  └─ 🧷 尿布       ████████░░░░░░░░░░░░  8 天                   │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│  📋 其他準備狀態                                                 │
│  ├─ ⚡ 電力設備    ████████████████████  100% 備妥              │
│  ├─ ❤️ 醫療用品    ██████████████░░░░░░  70%                    │
│  ├─ ⚙️ 備用裝備    ████████████████░░░░  80%                    │
│  ├─ 🧹 衛生用品    ██████████░░░░░░░░░░  50%  (不計入天數)      │
│  └─ 📄 重要文件    ████████████████████  100% (不計入天數)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Calculation Explanation Modal (ℹ️ 說明)

```
┌─────────────────────────────────────────────────────────────────┐
│  ✕                      韌性計算說明                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📊 維生天數計算方式                                             │
│  ───────────────────────────────────────────────────────────    │
│                                                                 │
│  💧 水                                                          │
│  公式: 總水量 (L) ÷ 人數 ÷ 3 (L/人/天)                          │
│  範例: 27L ÷ 3人 ÷ 3 = 3 天                                     │
│                                                                 │
│  🍚 糧食                                                         │
│  公式: 總熱量 (kcal) ÷ 人數 ÷ 2000 (kcal/人/天)                 │
│  範例: 42000kcal ÷ 3人 ÷ 2000 = 7 天                            │
│                                                                 │
│  🐕 寵物糧                                                       │
│  公式: 總重量 (kg) ÷ 寵物數 ÷ 0.3 (kg/隻/天)                    │
│  範例: 3kg ÷ 2隻 ÷ 0.3 = 5 天                                   │
│                                                                 │
│  👶 嬰幼兒用品                                                   │
│  • 奶粉: 總重量 ÷ 嬰兒數 ÷ 0.1 (kg/位/天)                       │
│  • 尿布: 總數量 ÷ 嬰兒數 ÷ 8 (片/位/天)                         │
│  ───────────────────────────────────────────────────────────    │
│                                                                 │
│  📋 不計入天數的分類                                             │
│  ───────────────────────────────────────────────────────────    │
│  以下分類以「完成度 %」顯示，不影響維生天數計算:                   │
│  • ⚡ 電力設備 - 有/無，非消耗品                                 │
│  • ❤️ 醫療用品 - 有/無，非每日消耗                               │
│  • ⚙️ 備用裝備 - 有/無                                          │
│  • 🧹 衛生用品 - 清單追蹤                                        │
│  • 📄 重要文件 - 清單追蹤                                        │
│                                                                 │
│  ⚠️ 最短天數警示                                                 │
│  ───────────────────────────────────────────────────────────    │
│  系統會自動找出所有消耗品中最短的天數，並以此作為                   │
│  「整體維生能力」的參考值。請優先補充最短天數的品項。               │
│                                                                 │
│                                              [了解]             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Model Updates

### 6.1 Item Schema Update

```typescript
// types/item.ts

interface InventoryItem {
  id: string;
  name: string;
  category: string;          // 'water' | 'food' | 'gear' | 'pets' | ...

  // Quantity & Unit
  quantity: number;
  unit: string;              // 'L', 'kg', 'pcs', 'kcal'

  // For consumables: nutritional/consumption data
  caloriesPerUnit?: number;  // For food items
  litersPerUnit?: number;    // For water/drinks

  // For gear items only: custom tags
  gearTags?: string[];       // Array of tag IDs

  // Status
  expiryDate?: string;
  lastChecked?: string;

  // Meta
  notes?: string;
  createdAt: string;
  updatedAt: string;
}
```

### 6.2 Calculation Service

```typescript
// services/resilienceCalculator.ts

interface ResilienceResult {
  // Per-group breakdown
  human: {
    days: number;
    limitingFactor: string;   // 'water' | 'food'
    breakdown: {
      water: { days: number; quantity: number; daily: number; };
      food: { days: number; calories: number; daily: number; };
    }
  };

  pets?: {
    days: number;
    count: number;
    breakdown: { food: { days: number; kg: number; daily: number; } }
  };

  baby?: {
    days: number;
    count: number;
    breakdown: {
      formula: { days: number; kg: number; daily: number; };
      diapers: { days: number; count: number; daily: number; };
    }
  };

  // Equipment readiness (percentage)
  equipment: {
    power: { percentage: number; checkedItems: number; totalItems: number; };
    medical: { percentage: number; checkedItems: number; totalItems: number; };
    gear: { percentage: number; checkedItems: number; totalItems: number; };
  };

  // Checklist completion (percentage only, no days)
  checklists: {
    hygiene?: { percentage: number; checkedItems: number; totalItems: number; };
    docs?: { percentage: number; checkedItems: number; totalItems: number; };
  };

  // Overall
  overallMinDays: number;
  limitingCategory: string;  // The category causing the minimum
}

function calculateResilience(
  items: InventoryItem[],
  settings: UserSettings
): ResilienceResult {
  const { householdSize, petCount, infantCount } = settings;

  // ... calculation logic ...
}
```

---

## 7. i18n Strings

### 7.1 Category Labels

```json
{
  "categories": {
    "water": { "zh-TW": "水", "zh-CN": "水", "en": "Water" },
    "food": { "zh-TW": "糧", "zh-CN": "粮", "en": "Food" },
    "power": { "zh-TW": "電", "zh-CN": "电", "en": "Power" },
    "medical": { "zh-TW": "醫", "zh-CN": "医", "en": "Medical" },
    "gear": { "zh-TW": "備", "zh-CN": "备", "en": "Gear" },
    "pets": { "zh-TW": "寵", "zh-CN": "宠", "en": "Pets" },
    "baby": { "zh-TW": "嬰", "zh-CN": "婴", "en": "Baby" },
    "hygiene": { "zh-TW": "衛", "zh-CN": "卫", "en": "Hygiene" },
    "docs": { "zh-TW": "文", "zh-CN": "文", "en": "Docs" }
  }
}
```

### 7.2 Settings Page

```json
{
  "settings": {
    "categorySettings": {
      "title": {
        "zh-TW": "分類顯示設定",
        "zh-CN": "分类显示设置",
        "en": "Category Settings"
      },
      "coreCategories": {
        "zh-TW": "核心分類 (無法關閉)",
        "zh-CN": "核心分类 (无法关闭)",
        "en": "Core Categories (Cannot disable)"
      },
      "optionalCategories": {
        "zh-TW": "選用分類",
        "zh-CN": "可选分类",
        "en": "Optional Categories"
      },
      "petCount": {
        "zh-TW": "寵物數量",
        "zh-CN": "宠物数量",
        "en": "Number of pets"
      },
      "infantCount": {
        "zh-TW": "嬰幼兒數量",
        "zh-CN": "婴幼儿数量",
        "en": "Number of infants"
      }
    }
  }
}
```

### 7.3 Resilience Explanation

```json
{
  "resilience": {
    "explanation": {
      "title": {
        "zh-TW": "韌性計算說明",
        "zh-CN": "韧性计算说明",
        "en": "Resilience Calculation Guide"
      },
      "waterFormula": {
        "zh-TW": "總水量 (L) ÷ 人數 ÷ 3 (L/人/天)",
        "zh-CN": "总水量 (L) ÷ 人数 ÷ 3 (L/人/天)",
        "en": "Total water (L) ÷ People ÷ 3 (L/person/day)"
      },
      "foodFormula": {
        "zh-TW": "總熱量 (kcal) ÷ 人數 ÷ 2000 (kcal/人/天)",
        "zh-CN": "总热量 (kcal) ÷ 人数 ÷ 2000 (kcal/人/天)",
        "en": "Total calories (kcal) ÷ People ÷ 2000 (kcal/person/day)"
      },
      "petFormula": {
        "zh-TW": "總重量 (kg) ÷ 寵物數 ÷ 0.3 (kg/隻/天)",
        "zh-CN": "总重量 (kg) ÷ 宠物数 ÷ 0.3 (kg/只/天)",
        "en": "Total weight (kg) ÷ Pets ÷ 0.3 (kg/pet/day)"
      },
      "notCountedNote": {
        "zh-TW": "以下分類以「完成度 %」顯示，不影響維生天數計算",
        "zh-CN": "以下分类以「完成度 %」显示，不影响维生天数计算",
        "en": "These categories show completion % only and do not affect survival days"
      },
      "minDaysWarning": {
        "zh-TW": "系統會自動找出所有消耗品中最短的天數，請優先補充最短天數的品項。",
        "zh-CN": "系统会自动找出所有消耗品中最短的天数，请优先补充最短天数的品项。",
        "en": "The system identifies the shortest duration among all consumables. Prioritize restocking items with the shortest supply."
      }
    }
  }
}
```

### 7.4 Gear Tag Templates

```json
{
  "gearTags": {
    "camping": { "zh-TW": "露營", "zh-CN": "露营", "en": "Camping" },
    "hiking": { "zh-TW": "登山", "zh-CN": "登山", "en": "Hiking" },
    "car": { "zh-TW": "車載", "zh-CN": "车载", "en": "Vehicle" },
    "office": { "zh-TW": "辦公室", "zh-CN": "办公室", "en": "Office" },
    "communication": { "zh-TW": "通訊", "zh-CN": "通讯", "en": "Comms" },
    "tools": { "zh-TW": "工具", "zh-CN": "工具", "en": "Tools" },
    "lighting": { "zh-TW": "照明", "zh-CN": "照明", "en": "Lighting" },
    "shelter": { "zh-TW": "避難", "zh-CN": "避难", "en": "Shelter" },
    "addNew": { "zh-TW": "新增標籤...", "zh-CN": "新增标签...", "en": "Add tag..." }
  }
}
```

---

## 8. Implementation Checklist

### Phase 1: Data & Settings (Priority: High)
- [ ] Define `CATEGORY_DEFINITIONS` constant with i18n labels
- [ ] Define `GEAR_TAG_TEMPLATES` constant with i18n labels
- [ ] Update UserSettings store to include `activeCategories`, `customGearTags`, `petCount`, `infantCount`
- [ ] Add migration for existing users (default to core categories only)

### Phase 2: Settings UI (Priority: High)
- [ ] Create "Category Settings" section in Settings page
- [ ] Implement toggle switches for optional categories
- [ ] Add pet/infant count inputs (shown conditionally)
- [ ] Add i18n strings for all 3 languages

### Phase 3: Category Filter Bar (Priority: High)
- [ ] Refactor filter bar to use `activeCategories` from settings
- [ ] Style "Gear" button with dark background
- [ ] Implement gear sub-tag dropdown
- [ ] Add "Create custom tag" modal

### Phase 4: Resilience Dashboard (Priority: Medium)
- [ ] Update calculation service to handle pets/baby categories
- [ ] Create grouped display (Human / Pets / Baby)
- [ ] Add "Calculation Explanation" modal
- [ ] Separate "days" calculation from "percentage" display

### Phase 5: Item Management (Priority: Medium)
- [ ] Update Add/Edit Item modal to show active categories only
- [ ] Add gear tag multi-select for gear items
- [ ] Handle edge case: item in disabled category

### Phase 6: Testing & Polish
- [ ] Test all 3 languages
- [ ] Test category toggle edge cases
- [ ] Test calculation accuracy
- [ ] Performance test with many custom tags

---

## 9. Edge Cases & Notes

### 9.1 Item in Disabled Category
If user creates a "Pet" item and later disables the Pet category:
- Item still exists in database
- Item appears in "All" view
- Item does NOT appear in category filter
- **No data loss**, user can re-enable category to see it again

### 9.2 Zero Pet/Infant Count
If user enables Pets category but sets count to 0:
- Show warning: "請設定寵物數量以計算維生天數"
- Days calculation shows "N/A" instead of infinity

### 9.3 Gear Tags on Non-Gear Items
- Custom tags only available for `category: 'gear'`
- Tag selector hidden for other categories

---

**End of Specification**
