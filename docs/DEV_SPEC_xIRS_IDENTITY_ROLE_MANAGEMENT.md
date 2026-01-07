# xIRS Identity & Role Management Specification

**版本**: v1.0
**日期**: 2026-01-07
**狀態**: DRAFT
**依據**: xIRS_ARCHITECTURE_FINAL.md, Gemini/ChatGPT 審查回饋

---

## 0. 問題陳述

### 護理人員的提問

> 「如果角色改變（如護理/志工/庫房），PWA 使用上與安全性會不會有問題？
> 我們改成 PWA 為核心，角色管理是否更複雜？或我們根本沒有做角色管理？」

### 現況分析

| 層面 | 現狀 | 風險 |
|------|------|------|
| **裝置信任** | ✓ 配對碼 + Station Token | 已實作 |
| **人員識別** | △ 部分 (pairing 時記錄 staff_id) | 無法追蹤「現在是誰在操作」 |
| **角色切換** | ✗ 未實作 | 志工拿到護理平板可執行給藥 |
| **敏感操作** | △ 管藥需見證 | 無系統化再驗證機制 |
| **稽核追蹤** | △ 有 ops_log 但不完整 | 離線操作難以證明 |

### 結論

**PWA 為核心後，角色管理確實更複雜**，因為不能再依賴「一台機器只有一個功能」。
但若正確實作，**安全性反而更高**（每次寫入都強制通過驗證）。

---

## 1. 三層信任模型

```
┌─────────────────────────────────────────────────────────────────────┐
│                     xIRS Identity Architecture                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Layer 3: ELEVATION (敏感操作)                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  • 管制藥品給藥                                              │   │
│   │  • 血品發放/退回                                             │   │
│   │  • 作廢/修正臨床記錄                                         │   │
│   │  → 需要: PIN 再驗證 或 雙人授權                              │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│                              │ 提升權限                              │
│                              │                                       │
│   Layer 2: USER SESSION (人員登入)                                   │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  • 輸入 PIN 碼 / 掃描識別證                                  │   │
│   │  • 取得 User JWT (8-12 小時, 班次週期)                       │   │
│   │  • 決定可用的 PWA 與功能                                     │   │
│   │  → Token: { sub, roles[], active_role, shift_id }            │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│                              │ 人員登入                              │
│                              │                                       │
│   Layer 1: STATION TRUST (裝置配對)                                  │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  • 掃描 Admin 配對碼                                         │   │
│   │  • 取得 Station Token (長效, 存 IDB)                         │   │
│   │  • 限制: 此裝置可連哪些 API、開哪些 PWA                      │   │
│   │  → Token: { station_id, device_id, allowed_pwas, scopes }    │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer 1: 裝置配對 (Station Trust)

### 2.1 Station Profile (Server-side)

```sql
CREATE TABLE station_profiles (
    station_id TEXT PRIMARY KEY,
    station_name TEXT NOT NULL,
    station_type TEXT NOT NULL,      -- 'TRIAGE' | 'ER' | 'OR' | 'LOGISTICS' | 'ADMIN'

    -- PWA 白名單
    allowed_pwas TEXT NOT NULL,       -- JSON: ["nursing", "logistics"]

    -- 權限範圍
    station_scopes TEXT NOT NULL,     -- JSON: ["cirs:patient:read", "mirs:inventory:read"]

    -- 安全設定
    idle_lock_minutes INTEGER DEFAULT 5,
    require_pin_on_launch INTEGER DEFAULT 1,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 Station Token 結構

```typescript
interface StationToken {
    station_id: string;           // "TRIAGE-01"
    device_id: string;            // UUID
    station_type: string;         // "TRIAGE"

    // 白名單 (關鍵!)
    allowed_pwas: string[];       // ["nursing", "logistics"]
    station_scopes: string[];     // ["cirs:patient:read", ...]

    // 時效
    iat: number;
    exp: number;                  // 長效: 30-90 天
}
```

### 2.3 關鍵規則

```
❌ 錯誤: Station Token 繼承使用者的 role scopes
✓ 正確: Station Token scopes = station_profile.station_scopes (與使用者無關)
```

**這條規則防止**：護理師的 iPad 不會因為她的角色包含 admin scope，就讓這台 iPad 變成 admin 終端。

---

## 3. Layer 2: 人員登入 (User Session)

### 3.1 登入方式

| 方式 | 使用情境 | 安全等級 |
|------|----------|----------|
| **PIN 碼 (4-6 位)** | 日常快速登入 | 中 |
| **識別證 QR** | 掃描識別證背面 QR | 中 |
| **帳號密碼** | 首次設定 / Admin | 高 |
| **生物辨識** | 支援 WebAuthn 的裝置 | 高 |

### 3.2 User JWT 結構

```typescript
interface UserToken {
    sub: string;                  // staff_id
    name: string;                 // 顯示名稱

    // 角色系統
    allowed_roles: Role[];        // 此人擁有的所有角色
    active_role: Role;            // 目前啟用的角色

    // 班次追蹤
    shift_id: string;             // "SHIFT-20260107-A"
    station_id: string;           // 從哪台裝置登入

    // 時效
    iat: number;
    exp: number;                  // 班次結束 (8-12 小時)
}

type Role = 'NURSE' | 'DOCTOR' | 'ANESTHESIA' | 'VOLUNTEER' | 'LOGISTICS' | 'PHARMACY' | 'ADMIN';
```

### 3.3 有效權限計算

```typescript
// 三層交集 = 實際可執行的權限
effective_scopes = station_scopes ∩ role_scopes(active_role) ∩ pwa_context_scopes

// 範例:
// station_scopes = ["cirs:patient:*", "mirs:inventory:read"]
// role_scopes(NURSE) = ["cirs:patient:*", "cirs:execution:write", "mirs:inventory:read"]
// pwa_context(nursing) = ["cirs:patient:*", "cirs:execution:write"]
//
// effective = ["cirs:patient:*"] (交集結果)
```

### 3.4 閒置鎖定策略

| PWA | 閒置鎖定 | 說明 |
|-----|----------|------|
| Nursing | 2-5 分鐘 | 共用裝置，高風險 |
| Anesthesia | 5 分鐘 | 術中可能需要快速查看 |
| EMT/Logistics | 5-10 分鐘 | 移動中較不方便 |
| Admin/CashDesk | 1-2 分鐘 | 財務敏感 |
| Doctor | 5 分鐘 | 看診中可能頻繁操作 |

### 3.5 Lock vs Logout

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Lock (鎖定)                                   │
├─────────────────────────────────────────────────────────────────────┤
│  • 顯示鎖定畫面 (模糊背景)                                          │
│  • 保留本地狀態 (未完成的表單等)                                    │
│  • 隱藏 PHI (病患資訊)                                              │
│  • 解鎖: 輸入 PIN 即可恢復                                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       Logout (登出)                                  │
├─────────────────────────────────────────────────────────────────────┤
│  • 必須清除:                                                         │
│    - 病患清單快取                                                    │
│    - 搜尋歷史                                                        │
│    - 最近開啟的 encounter context                                   │
│    - 交班快照                                                        │
│    - 任何含 PHI 的 localStorage/IDB 資料                            │
│  • 保留:                                                             │
│    - Station Token (裝置層級)                                        │
│    - PWA 快取 (Service Worker)                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Layer 3: 敏感操作提升 (Elevation)

### 4.1 需要提升權限的操作

```typescript
const ELEVATION_REQUIRED: Record<string, ElevationPolicy> = {
    // 管制藥品
    'controlled_drug_administer': {
        method: 'PIN_REAUTH',
        timeout_minutes: 5,
        audit_required: true
    },
    'controlled_drug_approve': {
        method: 'DUAL_AUTH',           // 雙人授權
        timeout_minutes: 0,            // 一次性
        audit_required: true
    },

    // 血品
    'blood_issue': {
        method: 'PIN_REAUTH',
        timeout_minutes: 5,
        audit_required: true
    },
    'blood_return_override': {
        method: 'DUAL_AUTH',
        timeout_minutes: 0,
        audit_required: true
    },

    // 臨床記錄
    'execution_void': {
        method: 'PIN_REAUTH',
        timeout_minutes: 0,
        audit_required: true,
        reason_required: true
    },
    'execution_correct': {
        method: 'PIN_REAUTH',
        timeout_minutes: 5,
        audit_required: true,
        reason_required: true
    },

    // 財務
    'invoice_void': {
        method: 'DUAL_AUTH',
        timeout_minutes: 0,
        audit_required: true,
        reason_required: true
    },
    'refund_process': {
        method: 'PIN_REAUTH',
        timeout_minutes: 5,
        audit_required: true
    },

    // 系統管理
    'patient_merge': {
        method: 'DUAL_AUTH',
        timeout_minutes: 0,
        audit_required: true
    },
    'station_unpair': {
        method: 'PIN_REAUTH',
        timeout_minutes: 0,
        audit_required: true
    }
};

type ElevationMethod = 'PIN_REAUTH' | 'DUAL_AUTH' | 'BIOMETRIC';
```

### 4.2 Elevation Token

```typescript
interface ElevationToken {
    elevation_id: string;
    user_id: string;
    action: string;                   // 被授權的操作
    method: ElevationMethod;

    // 雙人授權
    authorizer_id?: string;           // 第二授權者
    authorizer_role?: Role;

    // 時效
    granted_at: number;
    expires_at: number;               // 短效: 0-5 分鐘
}
```

### 4.3 離線雙人授權

```typescript
// 離線時無法即時驗證第二授權者
// 解法: 產生「待確認」事件，上線後由 supervisor 補簽

interface OfflineDualAuthProof {
    action: string;
    operator_id: string;
    operator_pin_hash: string;        // 操作者 PIN hash

    // 第二授權者聲明 (離線時由操作者代輸)
    claimed_authorizer_id: string;
    claimed_authorizer_pin_hash: string;

    // 稽核
    offline_proof_id: string;
    created_at: number;
    pending_verification: true;
}

// 上線後自動發送給 supervisor 確認
```

---

## 5. 角色與能力包 (Role ↔ Capability Bundles)

### 5.1 設計原則

```
❌ 錯誤思維: 「志工不能做 X」(否定式)
✓ 正確思維: 「志工可以做 A, B, C」(肯定式，白名單)
```

### 5.2 角色能力對照表

```typescript
const ROLE_CAPABILITIES: Record<Role, Capability[]> = {
    'VOLUNTEER': [
        // 最小權限
        'logistics:transfer:view',
        'logistics:transfer:confirm_pickup',
        'logistics:transfer:confirm_dropoff',
        'patient:minimal_identity',      // 只能看姓名、床號，不看完整病歷
    ],

    'LOGISTICS': [
        ...ROLE_CAPABILITIES['VOLUNTEER'],
        'inventory:view',
        'inventory:receive',
        'inventory:count',
        'transfer:create',
        'transfer:manage',
    ],

    'NURSE': [
        'patient:full_identity',
        'patient:vital_signs:write',
        'execution:medication:write',
        'execution:procedure:write',
        'execution:transfusion:write',
        'handoff:create',
        'handoff:accept',
        // 可讀庫存但不能入庫
        'inventory:view',
    ],

    'DOCTOR': [
        ...ROLE_CAPABILITIES['NURSE'],
        'order:create',
        'order:cancel',
        'diagnosis:write',
        // 可核准管制藥品
        'controlled_drug:approve',
    ],

    'ANESTHESIA': [
        ...ROLE_CAPABILITIES['NURSE'],
        'anesthesia:*',
        'controlled_drug:administer',
        'controlled_drug:approve',
    ],

    'PHARMACY': [
        'patient:minimal_identity',
        'order:view',
        'execution:dispense:write',
        'controlled_drug:dispense',
        'inventory:pharma:*',
    ],

    'ADMIN': [
        '*',  // 完整權限 (僅限 Admin Console)
    ],
};
```

### 5.3 ABAC 限制 (少量高槓桿)

```typescript
const ABAC_CONSTRAINTS = [
    {
        role: 'VOLUNTEER',
        constraint: 'patient:minimal_identity',
        description: '志工只能看姓名、床號，不能看完整病歷'
    },
    {
        role: 'LOGISTICS',
        constraint: 'cannot_modify_diagnosis',
        description: '庫房人員不能修改診斷'
    },
    {
        role: 'NURSE',
        constraint: 'controlled_drug_needs_approval',
        description: '護理師可執行管藥但不可自行核准'
    },
    {
        role: 'PHARMACY',
        constraint: 'dispense_only',
        description: '藥師只能調劑，不能執行給藥'
    },
];
```

---

## 6. 角色切換 UX

### 6.1 UI Header 設計

```
┌─────────────────────────────────────────────────────────────────────┐
│  🏥 TRIAGE-01  │  👤 王小明 (護理師)  │  🔄  │  🔒              │
│  Station        │  User + Active Role  │ Switch │ Lock             │
└─────────────────────────────────────────────────────────────────────┘

顏色視覺識別:
  護理師 = 粉色
  醫師 = 藍色
  志工 = 綠色
  庫房 = 橙色
  藥師 = 紫色
  Admin = 紅色
```

### 6.2 角色切換流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                     角色切換 (同一人多重角色)                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  情境: 護理師 A 需要臨時幫忙搬庫存                                  │
│                                                                      │
│  1. 點擊 Header 的 「🔄 Switch」                                    │
│                                                                      │
│  2. 顯示角色選單:                                                    │
│     ┌────────────────────────────────┐                              │
│     │  您的角色:                      │                              │
│     │  ● 護理師 (目前)               │                              │
│     │  ○ 庫房人員                     │                              │
│     └────────────────────────────────┘                              │
│                                                                      │
│  3. 選擇「庫房人員」                                                │
│                                                                      │
│  4. 系統檢查:                                                        │
│     - 此人是否有 LOGISTICS 角色? ✓                                  │
│     - 此裝置是否允許 logistics PWA? ✓                               │
│     - 是否需要 PIN 重驗證?                                          │
│       → 同級或降級: 不需要                                          │
│       → 升級 (volunteer→nurse): 需要                                │
│                                                                      │
│  5. 切換成功                                                         │
│     - Header 變色: 粉色 → 橙色                                      │
│     - 顯示: 👤 王小明 (庫房人員)                                     │
│     - Logistics PWA 可用                                             │
│     - Nursing PWA 的敏感功能隱藏                                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.3 裝置交接流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                     裝置交接 (換人使用)                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  情境: 護理師 A 把平板交給志工 B                                    │
│                                                                      │
│  1. 護理師 A 點擊「🔒 Lock」或「Logout」                            │
│                                                                      │
│  2. 如果選「Lock」:                                                  │
│     - 畫面模糊 + 鎖定                                                │
│     - 顯示: 「輸入 PIN 解鎖」                                       │
│     - 志工 B 輸入自己的 PIN                                         │
│     - 系統識別為新使用者 → 強制 Logout A → Login B                  │
│                                                                      │
│  3. 如果選「Logout」:                                                │
│     - 清除所有 PHI 快取                                              │
│     - 顯示登入畫面                                                   │
│     - 志工 B 輸入 PIN                                                │
│                                                                      │
│  4. 志工 B 登入後:                                                   │
│     - 系統識別角色: VOLUNTEER                                        │
│     - 自動隱藏 Nursing PWA 的給藥功能                                │
│     - 只顯示允許的功能: 搬運確認、物資查看                          │
│                                                                      │
│  5. 若志工誤觸給藥按鈕:                                             │
│     - 顯示: 「您的角色不允許此操作」                                │
│     - 記錄稽核事件 (嘗試越權)                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. 稽核追蹤 (Audit Trail)

### 7.1 統一稽核事件

```typescript
interface AuditEvent {
    // 識別
    event_id: string;                 // UUID
    event_type: AuditEventType;

    // 裝置層
    station_id: string;
    device_id: string;

    // 人員層
    operator_id: string;
    operator_name: string;
    active_role: Role;
    shift_id: string;

    // 提升層 (如有)
    elevation_proof?: 'NONE' | 'PIN' | 'DUAL_AUTH' | 'OFFLINE_PROOF';
    authorizer_id?: string;

    // 時間
    ts_client: number;                // 客戶端時間
    ts_server?: number;               // 伺服器時間 (同步後補)

    // 操作內容
    action: string;
    target_type?: string;             // 'patient' | 'execution' | 'inventory'
    target_id?: string;
    details_json?: string;

    // 鏈式稽核 (可選)
    prev_hash?: string;
}

type AuditEventType =
    | 'SESSION_LOGIN'
    | 'SESSION_LOGOUT'
    | 'SESSION_LOCK'
    | 'SESSION_UNLOCK'
    | 'ROLE_SWITCH'
    | 'ELEVATION_GRANTED'
    | 'ELEVATION_DENIED'
    | 'ACTION_EXECUTED'
    | 'ACTION_DENIED'
    | 'OFFLINE_DUAL_AUTH';
```

### 7.2 離線稽核保護

```typescript
// 離線時稽核事件存入 IndexedDB
// 每筆事件包含前一筆的 hash，形成鏈式結構
// 上線同步時，server 驗證鏈是否完整

function createAuditEvent(event: Partial<AuditEvent>): AuditEvent {
    const lastEvent = await idb.getLastAuditEvent();

    return {
        ...event,
        event_id: uuid(),
        ts_client: Date.now(),
        prev_hash: lastEvent ? sha256(JSON.stringify(lastEvent)) : null
    };
}
```

---

## 8. 共享儲存策略

### 8.1 Same Origin 要求

```
所有 PWA 必須部署在相同 Origin，才能共享 Session:

✓ 正確:
  http://mirs-pi.local:8090/apps/nursing/
  http://mirs-pi.local:8090/apps/logistics/
  http://mirs-pi.local:8090/apps/anesthesia/

✗ 錯誤 (不同 port = 不同 origin):
  http://mirs-pi.local:8090/nursing/
  http://mirs-pi.local:8000/logistics/   ← 不能共享 Session!
```

### 8.2 Nginx 反向代理設定

```nginx
# /etc/nginx/sites-available/xirs

server {
    listen 80;
    server_name mirs-pi.local;

    # CIRS Hub (port 8090)
    location /api/ {
        proxy_pass http://127.0.0.1:8090/api/;
    }

    # MIRS Engine (port 8000)
    location /mirs-api/ {
        proxy_pass http://127.0.0.1:8000/api/;
    }

    # PWA Static Files
    location /apps/nursing/ {
        alias /opt/xirs/frontend/nursing/;
        try_files $uri $uri/ /apps/nursing/index.html;
    }

    location /apps/logistics/ {
        alias /opt/xirs/frontend/logistics/;
        try_files $uri $uri/ /apps/logistics/index.html;
    }

    location /apps/anesthesia/ {
        alias /opt/xirs/frontend/anesthesia/;
        try_files $uri $uri/ /apps/anesthesia/index.html;
    }

    # Admin Console
    location /admin/ {
        alias /opt/xirs/frontend/admin/;
        try_files $uri $uri/ /admin/index.html;
    }
}
```

### 8.3 共享函式庫

```typescript
// /shared/js/xirs-auth.js

const XIRS_AUTH = {
    // Session 儲存 key
    STATION_TOKEN_KEY: 'xirs_station_token',
    USER_TOKEN_KEY: 'xirs_user_token',
    USER_SESSION_KEY: 'xirs_user_session',

    /**
     * 取得目前 Session
     */
    getSession(): UserSession | null {
        const token = localStorage.getItem(this.USER_TOKEN_KEY);
        if (!token) return null;

        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            if (payload.exp < Date.now() / 1000) {
                this.logout();
                return null;
            }
            return payload;
        } catch {
            return null;
        }
    },

    /**
     * 檢查是否可存取特定 PWA
     */
    canAccessPWA(pwa: string): boolean {
        const station = this.getStationToken();
        const session = this.getSession();

        if (!station || !session) return false;

        // 裝置允許 + 角色允許
        return station.allowed_pwas.includes(pwa) &&
               this.roleCanAccessPWA(session.active_role, pwa);
    },

    /**
     * 檢查是否可執行特定操作
     */
    canPerform(action: string): boolean {
        const station = this.getStationToken();
        const session = this.getSession();

        if (!station || !session) return false;

        // 計算有效權限 (三層交集)
        const roleScopes = ROLE_SCOPES[session.active_role] || [];
        const effectiveScopes = this.intersectScopes(
            station.station_scopes,
            roleScopes
        );

        return this.scopeAllows(effectiveScopes, action);
    },

    /**
     * 要求權限提升
     */
    async requestElevation(action: string): Promise<ElevationResult> {
        const policy = ELEVATION_REQUIRED[action];
        if (!policy) return { granted: true };

        if (policy.method === 'PIN_REAUTH') {
            return this.showPinDialog(action);
        } else if (policy.method === 'DUAL_AUTH') {
            return this.showDualAuthDialog(action);
        }

        return { granted: false, reason: 'Unknown elevation method' };
    },

    /**
     * 登出 (清除 PHI)
     */
    logout(): void {
        // 清除 user token
        localStorage.removeItem(this.USER_TOKEN_KEY);
        localStorage.removeItem(this.USER_SESSION_KEY);

        // 清除 PHI 快取
        localStorage.removeItem('patient_list_cache');
        localStorage.removeItem('search_history');
        localStorage.removeItem('recent_encounters');
        localStorage.removeItem('handoff_snapshots');

        // 清除 IndexedDB 中的 PHI
        this.clearPHIFromIDB();
    },

    /**
     * 鎖定 (不清除狀態)
     */
    lock(): void {
        sessionStorage.setItem('xirs_locked', 'true');
        document.body.classList.add('xirs-locked');
    }
};
```

---

## 9. 實作優先順序

### Phase 1: 基礎建設 (Sprint 1-2)

| 優先 | 任務 | 說明 |
|:----:|------|------|
| P0 | Nginx 反向代理設定 | 統一 Origin |
| P0 | xirs-auth.js 共用函式庫 | Session 管理基礎 |
| P0 | station_profiles 表 | 裝置權限定義 |
| P1 | PIN 登入 UI | 快速登入 |
| P1 | Lock/Unlock UI | 閒置保護 |

### Phase 2: 角色系統 (Sprint 2-3)

| 優先 | 任務 | 說明 |
|:----:|------|------|
| P0 | 角色能力對照表 | ROLE_CAPABILITIES |
| P0 | 有效權限計算 | 三層交集 |
| P1 | 角色切換 UI | Header + Dialog |
| P1 | 閒置自動降級 | 麻醉已有範例 |

### Phase 3: 敏感操作 (Sprint 3-4)

| 優先 | 任務 | 說明 |
|:----:|------|------|
| P0 | ELEVATION_REQUIRED 表 | 哪些操作需要提升 |
| P0 | PIN 再驗證 UI | 敏感操作確認 |
| P1 | 雙人授權 UI | 管藥/血品/作廢 |
| P1 | 離線雙人授權 | 待確認機制 |

### Phase 4: 稽核強化 (Sprint 4)

| 優先 | 任務 | 說明 |
|:----:|------|------|
| P1 | 統一 AuditEvent | 所有 PWA 共用 |
| P1 | 鏈式稽核 | prev_hash |
| P2 | 稽核報表 | Admin Console |

---

## 10. 安全性總結

| 威脅 | 防護機制 |
|------|----------|
| 志工誤觸給藥 | 角色白名單 + UI 隱藏 + 後端拒絕 |
| 離線越權 | 離線操作仍需 PIN + 事後稽核 |
| Session 洩漏 | 短效 token + 閒置鎖定 + Logout 清 PHI |
| 裝置遺失 | Station Token 可遠端撤銷 |
| 偽造操作 | 鏈式稽核 + 雙人授權 |

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 - 回應護理人員角色管理疑問 |
