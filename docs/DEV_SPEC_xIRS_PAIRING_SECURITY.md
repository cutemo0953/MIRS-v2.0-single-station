# xIRS 配對與安全機制規格書

**版本**: v1.0
**日期**: 2026-01-07
**狀態**: Draft

---

## 1. 現況分析

### 1.1 目前 PWA 分佈

```
CIRS (臨床掛號系統)
├── Portal (Admin)
├── Doctor PWA
├── Nurse PWA (檢傷)
├── Pharmacy PWA
├── Cashdesk PWA
├── Runner PWA (志工)
└── Files PWA

MIRS (庫存韌性系統)
├── Index.html (主控台)
├── Mobile PWA (庫房人員)
├── Anesthesia PWA
└── EMT PWA (轉送)

HIRS (戶外救護系統)
└── Standalone PWA
```

### 1.2 問題點

| 問題 | 說明 |
|------|------|
| 配對不一致 | CIRS/MIRS 各自配對，無統一機制 |
| 安全層級混亂 | 有些需登入，有些直接存取 |
| Satellite 定義模糊 | Pharmacy 在 CIRS 但操作 MIRS 庫存 |
| 跨系統呼叫 | MIRS 麻醉需呼叫 CIRS handoff API |
| 離線認證 | 無網路時如何驗證身份？ |

---

## 2. 統一架構設計

### 2.1 Hub-Satellite 模型

```
                    ┌─────────────────┐
                    │   CIRS Hub      │
                    │   (Port 8090)   │
                    │                 │
                    │  - 病患掛號     │
                    │  - 使用者認證   │
                    │  - 跨站協調     │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
           ▼                 ▼                 ▼
    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │ MIRS Sat    │   │ HIRS Sat    │   │ MIRS Sat    │
    │ (Station A) │   │ (Field)     │   │ (Station B) │
    │ Port 8000   │   │ Standalone  │   │ Port 8000   │
    └──────┬──────┘   └─────────────┘   └─────────────┘
           │
    ┌──────┴──────┐
    │   PWAs      │
    │  - Mobile   │
    │  - Anes     │
    │  - EMT      │
    └─────────────┘
```

### 2.2 認證層級

| Level | 名稱 | 適用場景 | 認證方式 |
|:-----:|------|----------|----------|
| 0 | Public | 公開資訊（版本、狀態）| 無 |
| 1 | Paired | 已配對裝置 | Station Token |
| 2 | Session | 登入使用者 | User JWT |
| 3 | Elevated | 敏感操作 | Re-auth + Audit |

### 2.3 Token 架構

```
┌─────────────────────────────────────────────────────────┐
│ Station Token (配對後發給裝置)                          │
├─────────────────────────────────────────────────────────┤
│ {                                                       │
│   "type": "station",                                    │
│   "station_id": "MIRS-HC01",                           │
│   "device_id": "DEV-abc123",                           │
│   "scopes": ["inventory:read", "blood:write", ...],    │
│   "iat": 1736271200,                                    │
│   "exp": 1767807200  // 1 年                            │
│ }                                                       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ User JWT (登入後發給使用者)                             │
├─────────────────────────────────────────────────────────┤
│ {                                                       │
│   "type": "user",                                       │
│   "sub": "nurse001",                                    │
│   "role": "nurse",                                      │
│   "station_id": "MIRS-HC01",                           │
│   "iat": 1736271200,                                    │
│   "exp": 1736300000  // 8 小時                          │
│ }                                                       │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 統一配對流程

### 3.1 配對碼機制

```
[Hub 管理員]
     │
     ▼
[產生配對碼] ─────────────────────────┐
     │                               │
     │  Pairing Code:                │
     │  ┌──────────────────┐         │
     │  │  MIRS-7X2K-9P4M  │         │
     │  └──────────────────┘         │
     │  有效期: 15 分鐘              │
     │  可配對: 1 台裝置             │
     │                               │
     ▼                               │
[Satellite 輸入配對碼] ◀─────────────┘
     │
     ▼
[交換公鑰 + 驗證]
     │
     ▼
[發放 Station Token]
     │
     ▼
[配對完成 ✓]
```

### 3.2 配對碼格式

```
格式: {SYSTEM}-{4CHAR}-{4CHAR}

SYSTEM:
  - CIRS: 臨床系統
  - MIRS: 庫存系統
  - HIRS: 戶外系統

範例:
  - CIRS-7X2K-9P4M
  - MIRS-3A8B-2C4D
  - HIRS-5E6F-7G8H
```

### 3.3 配對 API

```
POST /api/pairing/generate
Request: { "system": "MIRS", "scopes": [...], "expires_in": 900 }
Response: { "code": "MIRS-7X2K-9P4M", "expires_at": "..." }

POST /api/pairing/verify
Request: { "code": "MIRS-7X2K-9P4M", "device_info": {...} }
Response: { "station_token": "...", "hub_url": "...", "station_id": "..." }

POST /api/pairing/revoke
Request: { "station_id": "MIRS-HC01" }
Response: { "revoked": true }
```

---

## 4. PWA 權限範圍

### 4.1 Scope 定義

```
# 格式: {system}:{resource}:{action}

# CIRS Scopes
cirs:registration:read      # 讀取掛號
cirs:registration:write     # 新增/編輯掛號
cirs:patient:read           # 讀取病患資料
cirs:handoff:read           # 讀取交班
cirs:handoff:write          # 新增交班

# MIRS Scopes
mirs:inventory:read         # 讀取庫存
mirs:inventory:write        # 入出庫操作
mirs:equipment:read         # 讀取設備
mirs:equipment:check        # 設備檢查
mirs:blood:read             # 讀取血庫
mirs:blood:write            # 血袋操作
mirs:anesthesia:read        # 讀取麻醉記錄
mirs:anesthesia:write       # 新增麻醉記錄
mirs:transfer:read          # 讀取轉送
mirs:transfer:write         # 新增轉送

# Admin Scopes
admin:users:manage          # 使用者管理
admin:settings:write        # 系統設定
admin:audit:read            # 操作日誌
```

### 4.2 PWA 預設權限

| PWA | 所屬系統 | 預設 Scopes |
|-----|----------|-------------|
| Doctor | CIRS | `cirs:registration:*`, `cirs:handoff:write` |
| Nurse | CIRS | `cirs:registration:read`, `cirs:triage:write` |
| Pharmacy | CIRS | `cirs:prescription:*`, `mirs:inventory:read` |
| Cashdesk | CIRS | `cirs:billing:*`, `cirs:registration:read` |
| Runner | CIRS | `cirs:queue:read`, `cirs:handoff:read` |
| Mobile | MIRS | `mirs:inventory:*`, `mirs:equipment:check` |
| Anesthesia | MIRS | `mirs:anesthesia:*`, `cirs:handoff:*` |
| EMT | MIRS | `mirs:transfer:*`, `cirs:handoff:*` |
| HIRS | Standalone | `hirs:*` (本地) |

---

## 5. 認證流程

### 5.1 Level 1: 裝置配對驗證

```javascript
// 每次 API 請求
fetch('/api/inventory', {
    headers: {
        'X-Station-Token': localStorage.getItem('station_token')
    }
});

// 後端驗證
@app.middleware("http")
async def verify_station(request, call_next):
    token = request.headers.get('X-Station-Token')
    if not token:
        return JSONResponse({"error": "Unpaired device"}, 401)

    payload = jwt.decode(token, SECRET_KEY)
    request.state.station_id = payload['station_id']
    request.state.scopes = payload['scopes']
    return await call_next(request)
```

### 5.2 Level 2: 使用者登入

```javascript
// 登入
const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: {
        'X-Station-Token': stationToken,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({ username, password })
});

const { user_token } = await response.json();
localStorage.setItem('user_token', user_token);

// 後續請求帶兩個 token
fetch('/api/blood/receive', {
    headers: {
        'X-Station-Token': stationToken,
        'Authorization': `Bearer ${userToken}`
    }
});
```

### 5.3 Level 3: 敏感操作

```javascript
// 刪除血袋 - 需要重新驗證
async function deleteBloodBag(bagId) {
    // 1. 彈出確認密碼對話框
    const password = await showReauthDialog();

    // 2. 驗證密碼
    const verified = await fetch('/api/auth/verify-password', {
        method: 'POST',
        body: JSON.stringify({ password })
    });

    if (!verified.ok) {
        toast('密碼錯誤', 'error');
        return;
    }

    // 3. 執行刪除（帶 re-auth token）
    await fetch(`/api/blood-bags/${bagId}`, {
        method: 'DELETE',
        headers: {
            'X-Reauth-Token': verified.reauth_token
        }
    });
}
```

---

## 6. 離線認證

### 6.1 離線 Token 快取

```javascript
// 配對時儲存離線認證資料
const offlineAuth = {
    station_token: stationToken,
    station_id: 'MIRS-HC01',
    cached_users: [
        {
            user_id: 'nurse001',
            password_hash: 'bcrypt_hash...',
            role: 'nurse',
            scopes: [...]
        }
    ],
    cached_at: Date.now(),
    valid_until: Date.now() + 7 * 24 * 60 * 60 * 1000  // 7 天
};

localStorage.setItem('offline_auth', JSON.stringify(offlineAuth));
```

### 6.2 離線登入驗證

```javascript
async function offlineLogin(username, password) {
    const offlineAuth = JSON.parse(localStorage.getItem('offline_auth'));

    if (!offlineAuth || Date.now() > offlineAuth.valid_until) {
        throw new Error('離線認證已過期，請連線更新');
    }

    const user = offlineAuth.cached_users.find(u => u.user_id === username);
    if (!user) {
        throw new Error('使用者不存在');
    }

    // 本地驗證密碼 (使用 bcrypt.js)
    const valid = await bcrypt.compare(password, user.password_hash);
    if (!valid) {
        throw new Error('密碼錯誤');
    }

    // 產生本地 session
    return {
        user_id: user.user_id,
        role: user.role,
        scopes: user.scopes,
        is_offline: true
    };
}
```

### 6.3 離線操作同步

```javascript
// 離線操作存入 IndexedDB
const offlineOps = {
    id: crypto.randomUUID(),
    timestamp: Date.now(),
    user_id: 'nurse001',
    action: 'blood:receive',
    data: { bloodType: 'A+', quantity: 2 },
    synced: false
};

await idb.add('offline_operations', offlineOps);

// 上線時同步
window.addEventListener('online', async () => {
    const pending = await idb.getAll('offline_operations', { synced: false });

    for (const op of pending) {
        try {
            await syncOperation(op);
            op.synced = true;
            await idb.put('offline_operations', op);
        } catch (e) {
            console.error('Sync failed:', op.id, e);
        }
    }
});
```

---

## 7. 跨系統呼叫

### 7.1 MIRS → CIRS 呼叫

```javascript
// 麻醉 PWA 通知 CIRS 完成
async function notifyCirsAnesthesiaDone(registrationId) {
    const cirsHubUrl = localStorage.getItem('cirs_hub_url');
    const stationToken = localStorage.getItem('station_token');

    // 使用 Station Token 呼叫 CIRS
    // CIRS 驗證此 token 屬於已配對的 MIRS station
    await fetch(`${cirsHubUrl}/api/handoff/${registrationId}/anesthesia-done`, {
        method: 'POST',
        headers: {
            'X-Station-Token': stationToken,
            'X-Source-System': 'MIRS'
        }
    });
}
```

### 7.2 CIRS → MIRS 呼叫

```javascript
// Pharmacy 查詢 MIRS 庫存
async function queryMirsInventory(itemCode) {
    const mirsUrl = localStorage.getItem('mirs_satellite_url');
    const stationToken = localStorage.getItem('station_token');

    // Pharmacy 的 station token 應包含 mirs:inventory:read scope
    const response = await fetch(`${mirsUrl}/api/inventory/${itemCode}`, {
        headers: {
            'X-Station-Token': stationToken
        }
    });

    return response.json();
}
```

### 7.3 Token Scope 驗證

```python
# 後端驗證跨系統呼叫
def require_scope(scope: str):
    def decorator(func):
        async def wrapper(request, *args, **kwargs):
            token_scopes = request.state.scopes

            if scope not in token_scopes:
                raise HTTPException(403, f"Missing scope: {scope}")

            return await func(request, *args, **kwargs)
        return wrapper
    return decorator

@app.get("/api/inventory/{code}")
@require_scope("mirs:inventory:read")
async def get_inventory(code: str, request: Request):
    ...
```

---

## 8. 配對管理 UI

### 8.1 Hub 端管理

```
┌─────────────────────────────────────────────────────────┐
│  配對管理                                               │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  ┌─ 已配對裝置 ─────────────────────────────────────┐   │
│  │                                                   │   │
│  │  ● MIRS-HC01  (活躍)                             │   │
│  │    IP: 10.42.0.45                                │   │
│  │    配對時間: 2026-01-01 09:00                    │   │
│  │    最後活動: 2 分鐘前                            │   │
│  │    Scopes: inventory:*, equipment:*, blood:*     │   │
│  │    [編輯權限] [撤銷配對]                         │   │
│  │                                                   │   │
│  │  ● MIRS-HC02  (離線)                             │   │
│  │    IP: 10.42.0.46                                │   │
│  │    配對時間: 2026-01-02 14:00                    │   │
│  │    最後活動: 3 小時前                            │   │
│  │    [編輯權限] [撤銷配對]                         │   │
│  │                                                   │   │
│  └───────────────────────────────────────────────────┘   │
│                                                         │
│  [+ 產生新配對碼]                                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 8.2 Satellite 端配對

```
┌─────────────────────────────────────────────────────────┐
│  系統配對                                               │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  目前狀態: ● 未配對                                     │
│                                                         │
│  請輸入配對碼:                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  MIRS - [____] - [____]                         │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  或掃描 QR Code:                                        │
│  ┌───────────────┐                                     │
│  │   [開啟相機]  │                                     │
│  └───────────────┘                                     │
│                                                         │
│  [配對]                                                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 9. 安全考量

### 9.1 Token 安全

| 風險 | 對策 |
|------|------|
| Token 洩露 | HTTPS、短效期 User Token |
| Token 竊取 | httpOnly cookie（可選）|
| 暴力破解 | 登入失敗鎖定 |
| 重放攻擊 | Token 含 jti、nonce |

### 9.2 配對安全

| 風險 | 對策 |
|------|------|
| 配對碼洩露 | 短效期（15分鐘）、一次性 |
| 中間人攻擊 | TLS、公鑰交換 |
| 偽造 Satellite | 裝置指紋驗證 |

### 9.3 離線安全

| 風險 | 對策 |
|------|------|
| 離線資料竊取 | 加密 IndexedDB |
| 過期 Token 濫用 | 離線認證有效期限制 |
| 離線操作偽造 | 操作簽章 |

---

## 10. 實作計畫

### Phase 1: 統一配對機制
1. 定義統一配對碼格式
2. 實作 `/api/pairing/*` API
3. 更新 CIRS/MIRS 配對 UI

### Phase 2: Token 系統
1. Station Token 發放與驗證
2. User JWT 認證
3. Scope 權限檢查

### Phase 3: 跨系統呼叫
1. MIRS → CIRS API 呼叫驗證
2. CIRS → MIRS API 呼叫驗證
3. 操作日誌記錄

### Phase 4: 離線認證
1. 離線 Token 快取
2. 本地密碼驗證
3. 離線操作同步

---

## 11. 未決問題

- [ ] 是否需要 TOTP/2FA？
- [ ] 配對碼是否用 QR Code 取代手動輸入？
- [ ] HIRS 獨立運作時如何與 CIRS/MIRS 同步？
- [ ] 多 Hub 環境如何處理？（未來擴展）

---

## Changelog

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-01-07 | 初版 |
