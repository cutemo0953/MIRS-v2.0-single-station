/**
 * xIRS Bus v1.1 - Local UI Refresh (BroadcastChannel)
 *
 * DEV_SPEC_OXYGEN_TRACKING_SYNC_v1.1 defines:
 * - xIRS.Bus is ONLY for same-device UI refresh (not cross-device sync)
 * - Cross-device sync uses SSE endpoint (/api/oxygen/events/stream)
 *
 * Usage Pattern:
 * 1. Write to Backend (authority)
 * 2. THEN emit to Bus (notification)
 * 3. Consumers refetch from API (not trust Bus data)
 *
 * @author Claude Code (Opus 4.5)
 * @date 2026-01-24
 */

(function() {
    'use strict';

    window.xIRS = window.xIRS || {};

    class XIRSBus {
        constructor() {
            this.listeners = new Map();
            this.channel = null;
            this.isStub = false;

            // Initialize BroadcastChannel if available
            if (typeof BroadcastChannel !== 'undefined') {
                try {
                    this.channel = new BroadcastChannel('xirs-bus');
                    this.channel.onmessage = (event) => {
                        const { type, data } = event.data;
                        this._notify(type, data);
                    };
                    console.log('[xIRS.Bus] BroadcastChannel initialized');
                } catch (e) {
                    console.warn('[xIRS.Bus] BroadcastChannel failed:', e);
                    this.isStub = true;
                }
            } else {
                console.warn('[xIRS.Bus] BroadcastChannel not supported - stub mode');
                this.isStub = true;
            }
        }

        /**
         * Emit an event to all listeners (local + cross-tab on same device)
         *
         * IMPORTANT: This is NOT the authority!
         * Always write to backend BEFORE calling emit().
         *
         * @param {string} type - Event type (e.g., 'oxygen:claimed', 'oxygen:released')
         * @param {object} data - Event data (minimal - consumers should refetch)
         */
        emit(type, data) {
            // Local notification
            this._notify(type, data);

            // Cross-tab notification (same device only)
            if (this.channel) {
                try {
                    this.channel.postMessage({ type, data });
                } catch (e) {
                    console.warn('[xIRS.Bus] postMessage failed:', e);
                }
            }
        }

        /**
         * Subscribe to an event type
         *
         * @param {string} type - Event type to listen for
         * @param {function} callback - Function to call when event fires
         * @returns {function} Unsubscribe function
         */
        on(type, callback) {
            if (!this.listeners.has(type)) {
                this.listeners.set(type, []);
            }
            this.listeners.get(type).push(callback);

            // Return unsubscribe function
            return () => this.off(type, callback);
        }

        /**
         * Unsubscribe from an event type
         *
         * @param {string} type - Event type
         * @param {function} callback - The callback to remove
         */
        off(type, callback) {
            if (!this.listeners.has(type)) return;

            const callbacks = this.listeners.get(type);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }

        /**
         * Internal: Notify all listeners of an event
         */
        _notify(type, data) {
            const callbacks = this.listeners.get(type) || [];
            callbacks.forEach(cb => {
                try {
                    cb(data);
                } catch (e) {
                    console.error('[xIRS.Bus] Callback error:', e);
                }
            });

            // Also notify wildcard listeners
            const wildcardCallbacks = this.listeners.get('*') || [];
            wildcardCallbacks.forEach(cb => {
                try {
                    cb({ type, data });
                } catch (e) {
                    console.error('[xIRS.Bus] Wildcard callback error:', e);
                }
            });
        }

        /**
         * Destroy the bus (cleanup)
         */
        destroy() {
            if (this.channel) {
                this.channel.close();
                this.channel = null;
            }
            this.listeners.clear();
        }
    }

    // Create singleton instance
    window.xIRS.Bus = new XIRSBus();

    // =========================================================================
    // SSE Client Helper for Cross-Device Sync
    // =========================================================================

    /**
     * SSE Client for cross-device sync
     *
     * Usage:
     *   const sse = xIRS.SSE.connect('/api/oxygen/events/stream');
     *   sse.on('OXYGEN_CLAIMED', (data) => { ... });
     */
    class XIRSEventSource {
        constructor(url) {
            this.url = url;
            this.eventSource = null;
            this.listeners = new Map();
            this.reconnectAttempts = 0;
            this.maxReconnectAttempts = 10;
            this.reconnectDelay = 1000;
        }

        connect() {
            if (this.eventSource) {
                this.eventSource.close();
            }

            this.eventSource = new EventSource(this.url);

            this.eventSource.onopen = () => {
                console.log('[xIRS.SSE] Connected to', this.url);
                this.reconnectAttempts = 0;
            };

            this.eventSource.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);

                    if (data.type === 'heartbeat') {
                        return; // Ignore heartbeats
                    }

                    if (data.type === 'event' && data.event_type) {
                        // Notify specific event type listeners
                        this._notify(data.event_type, data);

                        // Also emit to xIRS.Bus for local UI refresh
                        const busType = data.event_type.toLowerCase().replace('_', ':');
                        xIRS.Bus.emit(busType, data);
                    }

                    // Notify wildcard listeners
                    this._notify('*', data);

                } catch (err) {
                    console.error('[xIRS.SSE] Parse error:', err);
                }
            };

            this.eventSource.onerror = (e) => {
                console.error('[xIRS.SSE] Error:', e);

                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
                    console.log(`[xIRS.SSE] Reconnecting in ${delay}ms...`);
                    setTimeout(() => this.connect(), delay);
                }
            };

            return this;
        }

        on(eventType, callback) {
            if (!this.listeners.has(eventType)) {
                this.listeners.set(eventType, []);
            }
            this.listeners.get(eventType).push(callback);
            return this;
        }

        _notify(type, data) {
            const callbacks = this.listeners.get(type) || [];
            callbacks.forEach(cb => {
                try {
                    cb(data);
                } catch (e) {
                    console.error('[xIRS.SSE] Callback error:', e);
                }
            });
        }

        disconnect() {
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            console.log('[xIRS.SSE] Disconnected');
        }
    }

    window.xIRS.SSE = {
        connect: (url) => new XIRSEventSource(url).connect()
    };

    console.log('[xIRS.Bus] v1.1 loaded - BroadcastChannel:', !window.xIRS.Bus.isStub);

})();
