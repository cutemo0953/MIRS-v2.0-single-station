/**
 * xIRS Fallback Guard v1.0
 *
 * Station pairing verification for PWAs.
 * Redirects unpaired devices to Lobby setup.
 *
 * Usage: Include this script in <head> BEFORE other scripts.
 * It will automatically check on DOMContentLoaded.
 *
 * Optional: Call window.xirsFallbackGuard.verify() manually.
 */

(function() {
    'use strict';

    const STORAGE_KEY = 'xirs_station';
    const SETUP_URL = '/setup';
    const VERIFY_API = '/api/auth/provision/verify-token';

    // Get current PWA name from URL path
    function getCurrentPWA() {
        const path = window.location.pathname;
        const match = path.match(/\/app\/(\w+)\/(\w+)?/);
        if (match) {
            return match[2] || match[1]; // sub-app or main app
        }
        // Fallback: check for known patterns
        if (path.includes('/doctor/')) return 'doctor';
        if (path.includes('/nurse/')) return 'nurse';
        if (path.includes('/pharmacy/')) return 'pharmacy';
        if (path.includes('/cashdesk/')) return 'cashdesk';
        if (path.includes('/runner/')) return 'runner';
        if (path.includes('/admin/')) return 'admin';
        return 'cirs';
    }

    // Load station from localStorage
    function loadStation() {
        try {
            const data = localStorage.getItem(STORAGE_KEY);
            return data ? JSON.parse(data) : null;
        } catch (e) {
            console.warn('[FallbackGuard] Failed to load station:', e);
            return null;
        }
    }

    // Redirect to setup with reason
    function redirectToSetup(reason) {
        const pwa = getCurrentPWA();
        const url = `${SETUP_URL}?from=${pwa}&reason=${reason}`;
        console.log(`[FallbackGuard] Redirecting to setup: ${url}`);
        window.location.href = url;
    }

    // Verify token with server (async, optional)
    async function verifyWithServer(token) {
        try {
            const resp = await fetch(VERIFY_API, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!resp.ok) {
                const err = await resp.json();
                return { valid: false, error: err.detail?.error || 'INVALID_TOKEN' };
            }

            return { valid: true, data: await resp.json() };
        } catch (e) {
            // Network error - allow offline
            console.warn('[FallbackGuard] Server verify failed (offline?):', e);
            return { valid: true, offline: true };
        }
    }

    // Main verification function
    async function verify(options = {}) {
        const {
            requireServerCheck = false,  // Set true to require online verification
            onVerified = null,           // Callback when verified
            onFailed = null              // Callback when failed (before redirect)
        } = options;

        const station = loadStation();

        // Check 1: Station data exists
        if (!station) {
            console.log('[FallbackGuard] No station data found');
            if (onFailed) onFailed('NO_STATION');
            redirectToSetup('not_paired');
            return false;
        }

        // Check 2: Token exists
        if (!station.token) {
            console.log('[FallbackGuard] No token in station data');
            if (onFailed) onFailed('NO_TOKEN');
            redirectToSetup('no_token');
            return false;
        }

        // Check 3: Token expiry (client-side quick check)
        try {
            const payload = JSON.parse(atob(station.token.split('.')[1]));
            if (payload.exp && payload.exp * 1000 < Date.now()) {
                console.log('[FallbackGuard] Token expired');
                if (onFailed) onFailed('TOKEN_EXPIRED');
                redirectToSetup('token_expired');
                return false;
            }
        } catch (e) {
            console.warn('[FallbackGuard] Failed to parse token:', e);
        }

        // Check 4: Server verification (if online and required)
        if (requireServerCheck && navigator.onLine) {
            const result = await verifyWithServer(station.token);
            if (!result.valid) {
                console.log('[FallbackGuard] Server rejected token:', result.error);
                if (onFailed) onFailed(result.error);
                redirectToSetup('token_invalid');
                return false;
            }
        }

        // All checks passed
        console.log('[FallbackGuard] Station verified:', station.station_id);
        if (onVerified) onVerified(station);
        return true;
    }

    // Auto-run on DOMContentLoaded (can be disabled via data attribute)
    document.addEventListener('DOMContentLoaded', function() {
        // Check if auto-guard is disabled
        const script = document.currentScript ||
            document.querySelector('script[src*="xirs-fallback-guard"]');

        if (script && script.dataset.autoGuard === 'false') {
            console.log('[FallbackGuard] Auto-guard disabled');
            return;
        }

        // Skip for Lobby itself
        const path = window.location.pathname;
        if (path === '/' || path === '/setup' || path === '/status' || path.startsWith('/lobby')) {
            console.log('[FallbackGuard] Skipping for Lobby path');
            return;
        }

        // Run verification
        verify();
    });

    // Expose API globally
    window.xirsFallbackGuard = {
        verify: verify,
        loadStation: loadStation,
        getCurrentPWA: getCurrentPWA,
        STORAGE_KEY: STORAGE_KEY
    };

    console.log('[FallbackGuard] Loaded v1.0');
})();
