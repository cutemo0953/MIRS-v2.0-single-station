/**
 * MIRS Lifeboat Client Library
 *
 * Provides client-side Disaster Recovery (Walkaway Test) functionality:
 * - IndexedDB storage for event backup
 * - Periodic backup from server
 * - New host detection via server_uuid
 * - Auto-restore trigger
 *
 * Version: 1.0
 * Date: 2026-01-26
 * Reference: DEV_SPEC_LIFEBOAT_MIRS_v1.1
 */

class LifeboatClient {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api/dr';
        this.dbName = options.dbName || 'mirs-lifeboat';
        this.dbVersion = 1;
        this.backupIntervalMs = options.backupIntervalMs || 5 * 60 * 1000; // 5 minutes
        this.adminPin = options.adminPin || null;

        this.db = null;
        this.backupTimer = null;
        this.knownServerUuid = null;
        this.knownDbFingerprint = null;

        // Callbacks
        this.onNewHostDetected = options.onNewHostDetected || null;
        this.onRestoreNeeded = options.onRestoreNeeded || null;
        this.onBackupComplete = options.onBackupComplete || null;
        this.onRestoreComplete = options.onRestoreComplete || null;
        this.onError = options.onError || console.error;

        // State
        this.isInitialized = false;
        this.isRestoring = false;
    }

    // =========================================================================
    // Initialization
    // =========================================================================

    async init() {
        if (this.isInitialized) return;

        try {
            // Open IndexedDB
            this.db = await this._openDatabase();

            // Load known server identity
            const config = await this._getConfig();
            this.knownServerUuid = config.serverUuid;
            this.knownDbFingerprint = config.dbFingerprint;

            this.isInitialized = true;
            console.log('[Lifeboat] Initialized', {
                knownServerUuid: this.knownServerUuid,
                knownDbFingerprint: this.knownDbFingerprint
            });

            return true;
        } catch (error) {
            this.onError('[Lifeboat] Init failed:', error);
            return false;
        }
    }

    _openDatabase() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;

                // Events store - backup of all events
                if (!db.objectStoreNames.contains('events')) {
                    const eventsStore = db.createObjectStore('events', { keyPath: 'event_id' });
                    eventsStore.createIndex('entity', ['entity_type', 'entity_id'], { unique: false });
                    eventsStore.createIndex('hlc', 'hlc', { unique: false });
                    eventsStore.createIndex('ts_device', 'ts_device', { unique: false });
                }

                // Snapshot store - current state backup
                if (!db.objectStoreNames.contains('snapshot')) {
                    db.createObjectStore('snapshot', { keyPath: 'table' });
                }

                // Config store - server identity, backup timestamps
                if (!db.objectStoreNames.contains('config')) {
                    db.createObjectStore('config', { keyPath: 'key' });
                }
            };
        });
    }

    // =========================================================================
    // Config Management
    // =========================================================================

    async _getConfig() {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('config', 'readonly');
            const store = tx.objectStore('config');

            const config = {
                serverUuid: null,
                dbFingerprint: null,
                lastBackupAt: null,
                lastExportHlc: null
            };

            const request = store.openCursor();
            request.onerror = () => reject(request.error);
            request.onsuccess = (event) => {
                const cursor = event.target.result;
                if (cursor) {
                    config[cursor.key] = cursor.value.value;
                    cursor.continue();
                } else {
                    resolve(config);
                }
            };
        });
    }

    async _setConfig(key, value) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('config', 'readwrite');
            const store = tx.objectStore('config');
            const request = store.put({ key, value });
            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve();
        });
    }

    // =========================================================================
    // Server Health Check
    // =========================================================================

    async checkServerHealth() {
        try {
            const response = await fetch(`${this.apiBase}/health`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const health = await response.json();

            // Check for new host
            if (this.knownServerUuid && health.server_uuid !== this.knownServerUuid) {
                console.log('[Lifeboat] New host detected!', {
                    known: this.knownServerUuid,
                    current: health.server_uuid
                });

                if (this.onNewHostDetected) {
                    this.onNewHostDetected(health);
                }

                // Check if restore is needed (empty DB on new host)
                if (!health.db_fingerprint || health.events_count === 0) {
                    console.log('[Lifeboat] Empty database on new host - restore needed');
                    if (this.onRestoreNeeded) {
                        this.onRestoreNeeded(health);
                    }
                    return { needsRestore: true, health };
                }
            }

            // Update known identity
            if (health.server_uuid) {
                this.knownServerUuid = health.server_uuid;
                await this._setConfig('serverUuid', health.server_uuid);
            }
            if (health.db_fingerprint) {
                this.knownDbFingerprint = health.db_fingerprint;
                await this._setConfig('dbFingerprint', health.db_fingerprint);
            }

            return { needsRestore: false, health };

        } catch (error) {
            this.onError('[Lifeboat] Health check failed:', error);
            return { needsRestore: false, error };
        }
    }

    // =========================================================================
    // Backup (Export from Server to IndexedDB)
    // =========================================================================

    async startPeriodicBackup() {
        if (this.backupTimer) return;

        // Initial backup
        await this.backup();

        // Schedule periodic backups
        this.backupTimer = setInterval(() => {
            this.backup();
        }, this.backupIntervalMs);

        console.log(`[Lifeboat] Periodic backup started (interval: ${this.backupIntervalMs}ms)`);
    }

    stopPeriodicBackup() {
        if (this.backupTimer) {
            clearInterval(this.backupTimer);
            this.backupTimer = null;
            console.log('[Lifeboat] Periodic backup stopped');
        }
    }

    async backup() {
        if (!this.isInitialized) {
            console.warn('[Lifeboat] Not initialized, skipping backup');
            return false;
        }

        try {
            console.log('[Lifeboat] Starting backup...');

            // Get last export cursor
            const config = await this._getConfig();
            const sinceHlc = config.lastExportHlc;

            // Fetch events from server
            let url = `${this.apiBase}/export?limit=1000&include_snapshot=true`;
            if (sinceHlc) {
                url += `&since_hlc=${encodeURIComponent(sinceHlc)}`;
            }

            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const exportData = await response.json();

            // Store events
            if (exportData.events && exportData.events.length > 0) {
                await this._storeEvents(exportData.events);

                // Update cursor for next incremental backup
                const lastEvent = exportData.events[exportData.events.length - 1];
                if (lastEvent.hlc) {
                    await this._setConfig('lastExportHlc', lastEvent.hlc);
                }
            }

            // Store snapshot
            if (exportData.snapshot) {
                await this._storeSnapshot(exportData.snapshot);
            }

            // Update backup timestamp
            await this._setConfig('lastBackupAt', Date.now());

            // Update known server identity
            if (exportData.server_uuid) {
                this.knownServerUuid = exportData.server_uuid;
                await this._setConfig('serverUuid', exportData.server_uuid);
            }
            if (exportData.db_fingerprint) {
                this.knownDbFingerprint = exportData.db_fingerprint;
                await this._setConfig('dbFingerprint', exportData.db_fingerprint);
            }

            console.log('[Lifeboat] Backup complete', {
                events: exportData.events_count,
                hasMore: exportData.pagination?.has_more
            });

            if (this.onBackupComplete) {
                this.onBackupComplete(exportData);
            }

            // Continue fetching if there's more
            if (exportData.pagination?.has_more) {
                await this.backup(); // Recursive call to get all pages
            }

            return true;

        } catch (error) {
            this.onError('[Lifeboat] Backup failed:', error);
            return false;
        }
    }

    async _storeEvents(events) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('events', 'readwrite');
            const store = tx.objectStore('events');

            let completed = 0;
            const total = events.length;

            events.forEach(event => {
                const request = store.put(event);
                request.onsuccess = () => {
                    completed++;
                    if (completed === total) resolve(completed);
                };
                request.onerror = () => reject(request.error);
            });

            if (total === 0) resolve(0);
        });
    }

    async _storeSnapshot(snapshot) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('snapshot', 'readwrite');
            const store = tx.objectStore('snapshot');

            const tables = Object.keys(snapshot);
            let completed = 0;

            tables.forEach(table => {
                const request = store.put({
                    table,
                    rows: snapshot[table],
                    updatedAt: Date.now()
                });
                request.onsuccess = () => {
                    completed++;
                    if (completed === tables.length) resolve(completed);
                };
                request.onerror = () => reject(request.error);
            });

            if (tables.length === 0) resolve(0);
        });
    }

    // =========================================================================
    // Restore (Send from IndexedDB to Server)
    // =========================================================================

    async restore(options = {}) {
        if (!this.isInitialized) {
            throw new Error('Lifeboat not initialized');
        }

        if (this.isRestoring) {
            throw new Error('Restore already in progress');
        }

        const pin = options.pin || this.adminPin;
        if (!pin) {
            throw new Error('Admin PIN required for restore');
        }

        this.isRestoring = true;

        try {
            console.log('[Lifeboat] Starting restore...');

            // Get events and snapshot from IndexedDB
            const events = await this._getAllEvents();
            const snapshot = await this._getSnapshot();

            if (events.length === 0 && Object.keys(snapshot).length === 0) {
                console.warn('[Lifeboat] No data to restore');
                return { success: false, message: 'No backup data available' };
            }

            // Generate session ID
            const sessionId = `restore-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
            const deviceId = this._getDeviceId();

            // Send in batches
            const batchSize = 500;
            const batches = [];
            for (let i = 0; i < events.length; i += batchSize) {
                batches.push(events.slice(i, i + batchSize));
            }

            // If no events, still send one batch with snapshot
            if (batches.length === 0) {
                batches.push([]);
            }

            let totalInserted = 0;
            let totalRejected = 0;

            for (let i = 0; i < batches.length; i++) {
                const isFirst = i === 0;
                const isFinal = i === batches.length - 1;

                const payload = {
                    restore_session_id: sessionId,
                    source_device_id: deviceId,
                    batch_number: i + 1,
                    total_batches: batches.length,
                    is_final_batch: isFinal,
                    events: batches[i],
                    events_count: batches[i].length
                };

                // Include snapshot only in first batch
                if (isFirst) {
                    payload.snapshot = snapshot;
                }

                const response = await fetch(`${this.apiBase}/restore`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-MIRS-PIN': pin
                    },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || `HTTP ${response.status}`);
                }

                const result = await response.json();
                totalInserted += result.events_inserted;
                totalRejected += result.events_rejected;

                console.log(`[Lifeboat] Batch ${i + 1}/${batches.length} complete`, result);
            }

            // Update known server identity after restore
            const healthCheck = await this.checkServerHealth();

            console.log('[Lifeboat] Restore complete', {
                totalEvents: events.length,
                totalInserted,
                totalRejected
            });

            if (this.onRestoreComplete) {
                this.onRestoreComplete({
                    sessionId,
                    totalEvents: events.length,
                    totalInserted,
                    totalRejected
                });
            }

            return {
                success: true,
                sessionId,
                totalEvents: events.length,
                totalInserted,
                totalRejected
            };

        } catch (error) {
            this.onError('[Lifeboat] Restore failed:', error);
            throw error;
        } finally {
            this.isRestoring = false;
        }
    }

    async _getAllEvents() {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('events', 'readonly');
            const store = tx.objectStore('events');
            const request = store.getAll();
            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result || []);
        });
    }

    async _getSnapshot() {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction('snapshot', 'readonly');
            const store = tx.objectStore('snapshot');
            const request = store.getAll();
            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                const snapshot = {};
                (request.result || []).forEach(item => {
                    snapshot[item.table] = item.rows;
                });
                resolve(snapshot);
            };
        });
    }

    _getDeviceId() {
        let deviceId = localStorage.getItem('mirs-device-id');
        if (!deviceId) {
            deviceId = `PWA-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem('mirs-device-id', deviceId);
        }
        return deviceId;
    }

    // =========================================================================
    // Statistics
    // =========================================================================

    async getStats() {
        if (!this.isInitialized) return null;

        const config = await this._getConfig();
        const events = await this._getAllEvents();
        const snapshot = await this._getSnapshot();

        return {
            eventsCount: events.length,
            snapshotTables: Object.keys(snapshot).length,
            knownServerUuid: this.knownServerUuid,
            knownDbFingerprint: this.knownDbFingerprint,
            lastBackupAt: config.lastBackupAt,
            lastExportHlc: config.lastExportHlc
        };
    }

    // =========================================================================
    // Cleanup
    // =========================================================================

    async clearLocalBackup() {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(['events', 'snapshot', 'config'], 'readwrite');

            tx.objectStore('events').clear();
            tx.objectStore('snapshot').clear();
            tx.objectStore('config').clear();

            tx.oncomplete = () => {
                this.knownServerUuid = null;
                this.knownDbFingerprint = null;
                console.log('[Lifeboat] Local backup cleared');
                resolve();
            };
            tx.onerror = () => reject(tx.error);
        });
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { LifeboatClient };
}

// Also expose globally for script tag usage
if (typeof window !== 'undefined') {
    window.LifeboatClient = LifeboatClient;
}
