# xIRS Gateway + Lobby 架構規格 v2.0

**版本**: 2.0
**日期**: 2026-01-09
**狀態**: Approved
**基於**: Gemini + ChatGPT 架構審閱整合
**取代**: DEV_SPEC_xIRS_PAIRING_UX_v1.0.md

---

## 執行摘要

採用 **「單一入口 (Port 80) + 反向代理 (Reverse Proxy) + 靜態大廳 (Lobby PWA)」** 架構，
解決戰時環境下「配對入口不明顯」、「Port 輸入困難」、「後端掛掉白畫面」等問題。

**核心原則**: 不要用 Port 分流使用者，用 URL 分流。

---

## 架構概覽

```
┌─────────────────────────────────────────────────────────────────────┐
│                 xIRS Gateway (Nginx Port 80)                         │
│                 http://xirs.local/                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Static Assets (秒開，後端掛也能顯示)                               │
│   ├── /                    → Lobby PWA (Landing + Setup + Router)   │
│   ├── /setup               → Lobby PWA (Setup Wizard route)         │
│   ├── /app/cirs/           → CIRS PWA (靜態 build)                  │
│   └── /app/mirs/           → MIRS PWA (靜態 build)                  │
│                                                                      │
│   API Proxy (動態，連後端)                                           │
│   ├── /api/auth/*          → 127.0.0.1:8000 (CIRS 兼任 Auth)        │
│   ├── /api/cirs/*          → 127.0.0.1:8000 (CIRS Backend)          │
│   ├── /api/mirs/*          → 127.0.0.1:8090 (MIRS Backend)          │
│   └── /ws/cirs/*           → 127.0.0.1:8000 (WebSocket)             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

        ┌──────────────┐    ┌──────────────┐
        │ CIRS Backend │    │ MIRS Backend │
        │ Port 8000    │    │ Port 8090    │
        │ (Localhost)  │    │ (Localhost)  │
        └──────────────┘    └──────────────┘
```

---

## 1. 為什麼需要這個架構

### 1.1 現狀問題

| 問題 | 說明 | 嚴重度 |
|------|------|--------|
| Port 輸入困難 | 戰場/緊急狀況下在平板輸入 `:8000` 是 UX 災難 | P0 |
| 入口散落 | 各 PWA 配對按鈕位置不一致，使用者找不到 | P0 |
| 後端掛掉白畫面 | Python 崩潰時瀏覽器顯示 "Connection Refused" | P1 |
| 身份管理混亂 | CIRS 不應負責核發 MIRS 的 Station Token | P1 |
| SW 互相污染 | 同 origin 多 PWA 的 Service Worker 衝突 | P1 |

### 1.2 架構目標

1. **單一入口**: 所有裝置都從 `http://xirs.local/` 進入
2. **秒開大廳**: 純靜態 Lobby PWA，後端掛也能顯示友善錯誤
3. **強制 Setup Gate**: 未配對裝置「必定」進入 Setup Wizard，不用找按鈕
4. **URL 分流**: `/app/cirs/`, `/app/mirs/` 取代 `:8000`, `:8090`
5. **SW 隔離**: 各 PWA 獨立 scope，互不污染

---

## 2. URL 路由合約 (Routing Contract)

### 2.1 靜態資源路由

| Path | Target | 說明 |
|------|--------|------|
| `/` | Lobby PWA | Landing + Setup Wizard + Router |
| `/setup` | Lobby PWA | Setup Wizard 直接入口 |
| `/status` | Lobby PWA | 系統狀態頁 (診斷用) |
| `/app/cirs/*` | CIRS PWA | 靜態 build artifact |
| `/app/mirs/*` | MIRS PWA | 靜態 build artifact |

### 2.2 API 路由 (Namespace 分流)

| Path | Upstream | 說明 |
|------|----------|------|
| `/api/auth/*` | `127.0.0.1:8000` | 身份驗證 (CIRS 兼任) |
| `/api/cirs/*` | `127.0.0.1:8000` | CIRS 業務 API |
| `/api/mirs/*` | `127.0.0.1:8090` | MIRS 業務 API |

### 2.3 WebSocket 路由

| Path | Upstream | 說明 |
|------|----------|------|
| `/ws/cirs/*` | `127.0.0.1:8000` | CIRS WebSocket |
| `/ws/auth/*` | `127.0.0.1:8000` | cap_version 推播 |

### 2.4 後端路由調整 (重要)

**CIRS Backend 需要調整路由前綴:**

```python
# Before (直連時代)
@router.post("/auth/login")
@router.get("/registrations")

# After (Gateway 時代)
@router.post("/api/auth/login")      # 或用 FastAPI prefix
@router.get("/api/cirs/registrations")
```

**建議方案**: 使用 FastAPI `APIRouter` prefix

```python
# backend/main.py
from fastapi import FastAPI

app = FastAPI()

# Auth routes (CIRS 兼任)
app.include_router(auth_router, prefix="/api/auth")

# CIRS business routes
app.include_router(registrations_router, prefix="/api/cirs")
app.include_router(handoff_router, prefix="/api/cirs")
```

---

## 3. Lobby PWA 規格

### 3.1 職責

| 職責 | 說明 |
|------|------|
| Setup Gate | 檢查 `localStorage` 是否有 `station_token`，沒有就顯示 Wizard |
| Router | 根據 `station_type` 自動導向正確的 App |
| Status | 顯示系統狀態 (Hub 可達/不可達、離線模式可用) |
| Recovery | 後端掛掉時顯示友善錯誤頁面，而非瀏覽器白畫面 |

### 3.2 狀態機

```
┌─────────────────────────────────────────────────────────────────┐
│                     Lobby State Machine                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐                                              │
│   │  Page Load   │                                              │
│   └──────┬───────┘                                              │
│          │                                                       │
│          ▼                                                       │
│   ┌──────────────────────┐                                      │
│   │ Check localStorage   │                                      │
│   │ station_token exists?│                                      │
│   └──────────┬───────────┘                                      │
│              │                                                   │
│     ┌────────┴────────┐                                         │
│     │                 │                                         │
│     ▼ NO              ▼ YES                                     │
│   ┌─────────┐   ┌─────────────────┐                            │
│   │ /setup  │   │ Validate Token  │                            │
│   │ Wizard  │   │ (offline OK)    │                            │
│   └─────────┘   └────────┬────────┘                            │
│                          │                                       │
│                 ┌────────┴────────┐                             │
│                 │                 │                             │
│                 ▼ VALID           ▼ INVALID                     │
│          ┌─────────────┐   ┌─────────────┐                     │
│          │ Route to    │   │ /setup      │                     │
│          │ /app/{type} │   │ (re-pair)   │                     │
│          └─────────────┘   └─────────────┘                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 LocalStorage Schema

```javascript
// Station Trust (裝置配對)
localStorage.setItem('xirs_station', JSON.stringify({
    station_id: 'TRIAGE-01',
    station_type: 'NURSE_STATION',  // NURSE_STATION | PHARMACY | SUPPLY | MIRS
    station_name: '檢傷站 #1',
    hub_url: 'http://xirs.local',
    paired_at: '2026-01-09T10:00:00Z',
    token: 'eyJhbGciOiJIUzI1NiIs...'
}));

// Routing Map
const STATION_TYPE_TO_APP = {
    'NURSE_STATION': '/app/cirs/',
    'DOCTOR_STATION': '/app/cirs/',
    'PHARMACY': '/app/cirs/',
    'CASHDESK': '/app/cirs/',
    'RUNNER': '/app/cirs/',
    'SUPPLY': '/app/mirs/',
    'MIRS': '/app/mirs/',
    'LOGISTICS': '/app/mirs/'
};
```

### 3.4 系統狀態頁 (/status)

```
┌─────────────────────────────────────────────────────────────┐
│  xIRS 系統狀態                              2026/01/09 16:00 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  裝置資訊                                                    │
│  ├── Station ID: TRIAGE-01                                  │
│  ├── Station Type: NURSE_STATION                            │
│  └── Paired At: 2026/01/09 10:00                            │
│                                                              │
│  服務狀態                                                    │
│  ├── CIRS Backend:  [●] 正常  (延遲: 23ms)                  │
│  ├── MIRS Backend:  [●] 正常  (延遲: 45ms)                  │
│  └── Auth Service:  [●] 正常                                │
│                                                              │
│  離線能力                                                    │
│  ├── Policy Snapshot: v5 (有效至 2026/01/10 10:00)          │
│  └── Pending Queue: 0 筆                                    │
│                                                              │
│  ─────────────────────────────────────────────────────────  │
│                                                              │
│  [重新配對]  [清除離線資料]  [匯出診斷包]                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Setup Wizard 規格

### 4.1 Wizard 步驟

```
Step 0: 系統就緒 (System Readiness)
├── 顯示: Hub 啟動中 / Hub 可達 / 離線模式可用
├── 永遠不讓使用者看到瀏覽器的連線錯誤頁
└── 自動進入下一步或顯示「系統初始化中」

Step 1: 站點配對 (Station Pairing)
├── 掃描 Station QR Code
├── 或手動輸入 6 碼配對碼
├── 儲存: station_id, station_type, hub_url, paired_at, token
└── 失敗處理: 過期/無效/網路錯誤

Step 2: 配對確認 (Pair Confirmation)
├── 顯示: Hub 名稱 + Hub URL + Station 名稱 + Station 類型
├── 警告: "此裝置將專屬於此站點"
└── [取消] [確認配對]

Step 3: 初始同步 (Initial Sync)
├── Policy Snapshot 取得 (MIRS/Satellite)
├── 基礎設定同步
└── local_auth 初始化

Step 4: 準備完成 (Ready)
├── 顯示: "配對完成於 {time}"
├── 按站點類型顯示「下一步」CTA:
│   ├── SUPPLY: "掃描物品 QR 驗證掃描器"
│   ├── PHARMACY: "測試 Rx Protocol 連線"
│   └── MIRS: "確認 Policy Snapshot 狀態"
└── [開始使用] → 自動導向 /app/{type}/
```

### 4.2 QR Payload Schema (v2.0)

```json
{
    "type": "STATION_PAIR_INVITE",
    "version": "2.0",
    "hub_url": "http://xirs.local",
    "hub_name": "CIRS Hub #1",
    "station_id": "TRIAGE-01",
    "station_type": "NURSE_STATION",
    "station_name": "檢傷站 #1",
    "pairing_code": "A3X9K2",
    "expires_at": "2026-01-09T15:30:00Z",
    "nonce": "abc123",
    "sig": "hmac-sha256:..."  // v2.0: Hub 簽章
}
```

### 4.3 失敗與復原路徑

| 情境 | 處理方式 |
|------|----------|
| 相機權限拒絕 | 立即顯示手動輸入配對碼 UI |
| QR 過期 | 顯示 "配對碼已過期" + "請聯繫管理員取得新碼" |
| 網路不通 | 顯示 "網路連線失敗" + "儲存配對嘗試，稍後重試" |
| 時間漂移 | 警告 "裝置時間可能不正確，請確認" |
| 簽章無效 | 顯示 "不安全的 QR Code" + 阻止配對 |

---

## 5. Service Worker 隔離規格 (Critical)

### 5.1 Scope 定義

| PWA | SW Scope | Cache Name Prefix |
|-----|----------|-------------------|
| Lobby | `/` | `lobby-v{version}` |
| CIRS | `/app/cirs/` | `cirs-v{version}` |
| MIRS | `/app/mirs/` | `mirs-v{version}` |

### 5.2 SW 註冊規則

```javascript
// Lobby SW (/)
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', {
        scope: '/'
    });
}

// CIRS SW (/app/cirs/)
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/app/cirs/sw.js', {
        scope: '/app/cirs/'
    });
}

// MIRS SW (/app/mirs/)
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/app/mirs/sw.js', {
        scope: '/app/mirs/'
    });
}
```

### 5.3 Lobby SW Fetch Handler 排除規則

```javascript
// lobby-sw.js
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // 不要攔截其他 PWA 的請求
    if (url.pathname.startsWith('/app/')) {
        return; // 讓瀏覽器正常處理
    }

    // 不要快取 API 請求
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // 不要快取 WebSocket
    if (url.pathname.startsWith('/ws/')) {
        return;
    }

    // 只快取 Lobby 自己的靜態資源
    event.respondWith(
        caches.match(event.request).then(/* ... */)
    );
});
```

### 5.4 Manifest 規格

```json
// /manifest.webmanifest (Lobby)
{
    "name": "xIRS Lobby",
    "short_name": "xIRS",
    "start_url": "/",
    "scope": "/",
    "display": "standalone"
}

// /app/cirs/manifest.webmanifest
{
    "name": "CIRS",
    "short_name": "CIRS",
    "start_url": "/app/cirs/",
    "scope": "/app/cirs/",
    "display": "standalone"
}

// /app/mirs/manifest.webmanifest
{
    "name": "MIRS",
    "short_name": "MIRS",
    "start_url": "/app/mirs/",
    "scope": "/app/mirs/",
    "display": "standalone"
}
```

---

## 6. 向後相容 (Backward Compatibility)

### 6.1 舊入口重導向

**`:8000` 直連處理:**

```python
# CIRS backend/main.py
@app.get("/")
async def legacy_root_redirect():
    """舊的直連入口，重導向到 Lobby"""
    return RedirectResponse(
        url="http://xirs.local/app/cirs/",
        status_code=302
    )
```

**或在 Nginx 層處理:**

```nginx
# 監聽舊的 8000 port，重導向到 Gateway
server {
    listen 8000;
    server_name _;

    location / {
        return 302 http://xirs.local/app/cirs/;
    }
}

server {
    listen 8090;
    server_name _;

    location / {
        return 302 http://xirs.local/app/mirs/;
    }
}
```

### 6.2 舊 Home Screen Icon 處理

- 舊的 Home Screen Icon 會連到 `:8000` 或 `:8090`
- 透過上述重導向，會自動進入 Lobby
- Lobby 會根據已存在的 `localStorage` 配對資訊自動路由

### 6.3 過渡期 (1 週)

1. **Week 1**: 舊 Port 重導向到 Gateway，發公告
2. **Week 2**: 關閉 `:8000`/`:8090` 對外存取 (僅限 localhost)

---

## 7. 各 PWA Fallback Guard

即使有 Lobby 作為主閘門，各 PWA 仍需保留最低限度的 Setup Gate 作為防禦深度。

### 7.1 CIRS PWA Fallback Guard

```javascript
// /app/cirs/index.html
document.addEventListener('DOMContentLoaded', async () => {
    const station = JSON.parse(localStorage.getItem('xirs_station') || 'null');

    if (!station || !station.token) {
        // 未配對，跳回 Lobby
        window.location.href = '/setup?from=cirs';
        return;
    }

    // 驗證 token 有效性 (可選，離線時跳過)
    if (navigator.onLine) {
        try {
            const resp = await fetch('/api/auth/verify', {
                headers: { 'Authorization': `Bearer ${station.token}` }
            });
            if (!resp.ok) {
                window.location.href = '/setup?reason=token_invalid';
                return;
            }
        } catch (e) {
            // 網路錯誤，允許離線使用
            console.warn('[Guard] Network error, allowing offline');
        }
    }

    // 初始化 App
    initApp();
});
```

### 7.2 MIRS PWA Fallback Guard

```javascript
// /app/mirs/index.html
document.addEventListener('DOMContentLoaded', async () => {
    const station = JSON.parse(localStorage.getItem('xirs_station') || 'null');

    if (!station || !station.token) {
        window.location.href = '/setup?from=mirs';
        return;
    }

    // MIRS 額外檢查: Policy Snapshot
    const snapshot = await checkLocalSnapshot();
    if (!snapshot.valid && navigator.onLine) {
        // 有網路但沒有效 snapshot，嘗試同步
        await syncPolicySnapshot();
    }

    initApp();
});
```

---

## 8. Nginx 設定範例

```nginx
# /etc/nginx/sites-available/xirs-gateway

server {
    listen 80;
    server_name xirs.local;

    # Gzip 壓縮
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    # ============================================================
    # 靜態資源 (優先)
    # ============================================================

    # Lobby PWA
    location / {
        root /var/www/xirs-lobby;
        try_files $uri $uri/ /index.html;

        # 快取策略: HTML 不快取，其他資源長快取
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }

    # CIRS PWA
    location /app/cirs/ {
        alias /var/www/xirs-cirs/;
        try_files $uri $uri/ /app/cirs/index.html;
    }

    # MIRS PWA
    location /app/mirs/ {
        alias /var/www/xirs-mirs/;
        try_files $uri $uri/ /app/mirs/index.html;
    }

    # ============================================================
    # API Proxy
    # ============================================================

    # Auth API (CIRS 兼任)
    location /api/auth/ {
        proxy_pass http://127.0.0.1:8000/api/auth/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # CIRS API
    location /api/cirs/ {
        proxy_pass http://127.0.0.1:8000/api/cirs/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # MIRS API
    location /api/mirs/ {
        proxy_pass http://127.0.0.1:8090/api/mirs/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # ============================================================
    # WebSocket Proxy
    # ============================================================

    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # ============================================================
    # 健康檢查
    # ============================================================

    location /health {
        return 200 'OK';
        add_header Content-Type text/plain;
    }
}

# ============================================================
# 舊 Port 重導向 (向後相容)
# ============================================================

server {
    listen 8000;
    server_name _;
    return 302 http://xirs.local/app/cirs/;
}

server {
    listen 8090;
    server_name _;
    return 302 http://xirs.local/app/mirs/;
}
```

---

## 9. Vercel Demo 處理

Vercel 環境沒有 Nginx，但可透過 `vercel.json` 模擬類似行為：

```json
{
    "rewrites": [
        { "source": "/app/cirs/:path*", "destination": "/cirs/:path*" },
        { "source": "/app/mirs/:path*", "destination": "/mirs/:path*" },
        { "source": "/api/auth/:path*", "destination": "/api/auth/:path*" },
        { "source": "/api/cirs/:path*", "destination": "/api/:path*" },
        { "source": "/setup", "destination": "/" }
    ]
}
```

**或維持現狀**: Vercel Demo 作為功能展示，不強制 Lobby 架構。
RPi 生產環境才使用完整 Gateway。

---

## 10. 實作分期

```
Phase A: Lobby PWA + Nginx Gateway (Week 1)
├── Day 1-2: Nginx 基礎設定 + 靜態檔案結構
├── Day 3-4: Lobby PWA (Router + Setup Wizard)
└── Day 5: SW 隔離規則 + Manifest

Phase B: API Namespace 遷移 (Week 2)
├── Day 1-2: CIRS Backend 路由前綴調整
├── Day 3-4: MIRS Backend 路由前綴調整
└── Day 5: 前端 API baseURL 更新

Phase C: Fallback Guard + 向後相容 (Week 3)
├── Day 1-2: 各 PWA 加入 Fallback Guard
├── Day 3: 舊 Port 重導向設定
└── Day 4-5: 測試 + 文件更新

Phase D: 系統狀態頁 + 診斷工具 (Week 4)
├── Day 1-2: /status 頁面
├── Day 3: 診斷包匯出功能
└── Day 4-5: Admin 站點生命週期管理
```

---

## 11. 驗收標準 (Acceptance Criteria)

### 11.1 Lobby 功能

- [ ] 新裝置開啟 `xirs.local` 自動進入 Setup Wizard
- [ ] 已配對裝置開啟 `xirs.local` 自動路由到正確 App
- [ ] 後端掛掉時 Lobby 仍能顯示友善錯誤頁面
- [ ] `/status` 頁面顯示所有服務狀態

### 11.2 SW 隔離

- [ ] 安裝 Lobby PWA 後，CIRS PWA 仍可獨立安裝
- [ ] CIRS 離線快取不會被 Lobby 快取策略覆蓋
- [ ] 各 PWA 有獨立的 manifest 和 start_url

### 11.3 向後相容

- [ ] 訪問 `xirs.local:8000` 自動重導向到 `/app/cirs/`
- [ ] 舊的 Home Screen Icon 仍可正常使用
- [ ] 已存在的 localStorage 配對資訊被保留

### 11.4 Setup Wizard

- [ ] QR 掃描 + 手動輸入配對碼都能正常配對
- [ ] QR 過期/無效時顯示明確錯誤訊息
- [ ] 配對完成後自動路由到正確 App

---

## 12. 檔案結構

```
/var/www/
├── xirs-lobby/              # Lobby PWA
│   ├── index.html
│   ├── sw.js
│   ├── manifest.webmanifest
│   └── assets/
│
├── xirs-cirs/               # CIRS PWA (build output)
│   ├── index.html
│   ├── sw.js
│   ├── manifest.webmanifest
│   └── assets/
│
└── xirs-mirs/               # MIRS PWA (build output)
    ├── index.html
    ├── sw.js
    ├── manifest.webmanifest
    └── assets/
```

---

**文件版本**: v2.0
**撰寫者**: Claude Code (整合 Gemini + ChatGPT 建議)
**日期**: 2026-01-09
**審核狀態**: Approved
