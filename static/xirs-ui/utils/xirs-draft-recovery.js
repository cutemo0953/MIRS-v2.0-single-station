/**
 * xIRS Draft Recovery v1.0
 *
 * 表單草稿自動儲存與恢復
 * - 防止意外關閉頁面造成資料遺失
 * - 使用 IndexedDB 儲存草稿
 * - 30 分鐘未更新自動清除
 *
 * Usage:
 *   // 初始化
 *   XIRS_DRAFT.init();
 *
 *   // 監控表單
 *   XIRS_DRAFT.watch('vital-signs-form', formData);
 *
 *   // 檢查是否有草稿
 *   const draft = await XIRS_DRAFT.get('vital-signs-form');
 *   if (draft) {
 *     // 顯示恢復對話框
 *   }
 *
 *   // 清除草稿
 *   XIRS_DRAFT.clear('vital-signs-form');
 */

const XIRS_DRAFT = {
  VERSION: '1.0.0',

  // 配置
  config: {
    dbName: 'xirs-drafts',
    storeName: 'drafts',
    maxAge: 30 * 60 * 1000,  // 30 分鐘
    debounceMs: 1000         // 儲存延遲
  },

  // 狀態
  state: {
    db: null,
    initialized: false,
    watchers: {},         // formId -> { timer, lastData }
    saveTimers: {}        // formId -> debounce timer
  },

  /**
   * 初始化
   */
  async init() {
    if (this.state.initialized) return;

    try {
      this.state.db = await this.openDB();
      this.state.initialized = true;

      // 清理過期草稿
      await this.cleanup();

      console.log('[xIRS Draft] Initialized');
    } catch (e) {
      console.error('[xIRS Draft] Init failed:', e);
    }
  },

  /**
   * 開啟 IndexedDB
   */
  openDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.config.dbName, 1);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);

      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(this.config.storeName)) {
          const store = db.createObjectStore(this.config.storeName, { keyPath: 'id' });
          store.createIndex('updatedAt', 'updatedAt', { unique: false });
        }
      };
    });
  },

  /**
   * 監控表單變更並自動儲存
   * @param {string} formId - 表單識別碼
   * @param {Object} getData - 取得表單資料的函數
   */
  watch(formId, getData) {
    if (typeof getData !== 'function') {
      console.error('[xIRS Draft] getData must be a function');
      return;
    }

    // 儲存 watcher
    this.state.watchers[formId] = {
      getData,
      lastData: null
    };

    // 定期檢查並儲存
    const checkAndSave = () => {
      const data = getData();
      const lastData = this.state.watchers[formId]?.lastData;

      // 檢查資料是否有變更
      if (JSON.stringify(data) !== JSON.stringify(lastData)) {
        this.state.watchers[formId].lastData = data;
        this.debouncedSave(formId, data);
      }
    };

    // 每 5 秒檢查一次
    const interval = setInterval(checkAndSave, 5000);

    // 頁面關閉時儲存
    window.addEventListener('beforeunload', () => {
      const data = getData();
      if (data && Object.keys(data).length > 0) {
        this.saveSync(formId, data);
      }
    });

    console.log(`[xIRS Draft] Watching: ${formId}`);

    // 返回清理函數
    return () => {
      clearInterval(interval);
      delete this.state.watchers[formId];
    };
  },

  /**
   * 防抖儲存
   */
  debouncedSave(formId, data) {
    // 清除之前的 timer
    if (this.state.saveTimers[formId]) {
      clearTimeout(this.state.saveTimers[formId]);
    }

    // 設定新的 timer
    this.state.saveTimers[formId] = setTimeout(async () => {
      await this.save(formId, data);
    }, this.config.debounceMs);
  },

  /**
   * 儲存草稿
   */
  async save(formId, data) {
    if (!this.state.db) await this.init();

    const draft = {
      id: formId,
      data: data,
      updatedAt: Date.now(),
      userId: this.getCurrentUserId()
    };

    return new Promise((resolve, reject) => {
      const tx = this.state.db.transaction(this.config.storeName, 'readwrite');
      const store = tx.objectStore(this.config.storeName);
      const request = store.put(draft);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        console.log(`[xIRS Draft] Saved: ${formId}`);
        resolve();
      };
    });
  },

  /**
   * 同步儲存 (用於 beforeunload)
   */
  saveSync(formId, data) {
    try {
      // Fallback to localStorage for sync save
      const key = `xirs-draft-${formId}`;
      const draft = {
        id: formId,
        data: data,
        updatedAt: Date.now(),
        userId: this.getCurrentUserId()
      };
      localStorage.setItem(key, JSON.stringify(draft));
    } catch (e) {
      console.warn('[xIRS Draft] Sync save failed:', e);
    }
  },

  /**
   * 取得草稿
   */
  async get(formId) {
    if (!this.state.db) await this.init();

    // 先檢查 localStorage (可能有 beforeunload 儲存的)
    const lsKey = `xirs-draft-${formId}`;
    const lsDraft = localStorage.getItem(lsKey);
    if (lsDraft) {
      try {
        const parsed = JSON.parse(lsDraft);
        // 如果有效，移到 IndexedDB 並清除 localStorage
        if (Date.now() - parsed.updatedAt < this.config.maxAge) {
          await this.save(formId, parsed.data);
          localStorage.removeItem(lsKey);
          return parsed;
        } else {
          localStorage.removeItem(lsKey);
        }
      } catch (e) {
        localStorage.removeItem(lsKey);
      }
    }

    return new Promise((resolve, reject) => {
      const tx = this.state.db.transaction(this.config.storeName, 'readonly');
      const store = tx.objectStore(this.config.storeName);
      const request = store.get(formId);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const draft = request.result;

        // 檢查是否過期
        if (draft && Date.now() - draft.updatedAt < this.config.maxAge) {
          resolve(draft);
        } else {
          // 過期，刪除並返回 null
          if (draft) this.clear(formId);
          resolve(null);
        }
      };
    });
  },

  /**
   * 清除草稿
   */
  async clear(formId) {
    if (!this.state.db) await this.init();

    // 清除 localStorage
    localStorage.removeItem(`xirs-draft-${formId}`);

    // 清除 watcher
    delete this.state.watchers[formId];
    if (this.state.saveTimers[formId]) {
      clearTimeout(this.state.saveTimers[formId]);
      delete this.state.saveTimers[formId];
    }

    return new Promise((resolve, reject) => {
      const tx = this.state.db.transaction(this.config.storeName, 'readwrite');
      const store = tx.objectStore(this.config.storeName);
      const request = store.delete(formId);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        console.log(`[xIRS Draft] Cleared: ${formId}`);
        resolve();
      };
    });
  },

  /**
   * 清理過期草稿
   */
  async cleanup() {
    if (!this.state.db) return;

    const cutoff = Date.now() - this.config.maxAge;

    return new Promise((resolve, reject) => {
      const tx = this.state.db.transaction(this.config.storeName, 'readwrite');
      const store = tx.objectStore(this.config.storeName);
      const index = store.index('updatedAt');
      const range = IDBKeyRange.upperBound(cutoff);
      const request = index.openCursor(range);

      request.onerror = () => reject(request.error);
      request.onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          console.log(`[xIRS Draft] Cleaning expired: ${cursor.value.id}`);
          cursor.delete();
          cursor.continue();
        } else {
          resolve();
        }
      };
    });
  },

  /**
   * 取得目前使用者 ID
   */
  getCurrentUserId() {
    try {
      const token = localStorage.getItem('token') || sessionStorage.getItem('token');
      if (!token) return 'anonymous';
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.sub || 'anonymous';
    } catch (e) {
      return 'anonymous';
    }
  },

  /**
   * 顯示恢復對話框
   */
  async showRecoveryDialog(formId, onRestore, onDiscard) {
    const draft = await this.get(formId);
    if (!draft) return false;

    const age = Math.round((Date.now() - draft.updatedAt) / 60000);
    const ageText = age < 1 ? '剛才' : `${age} 分鐘前`;

    return new Promise((resolve) => {
      const dialog = document.createElement('div');
      dialog.id = 'xirs-draft-recovery-dialog';
      dialog.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10000;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.5);
        animation: xirs-fade-in 0.2s ease-out;
      `;

      dialog.innerHTML = `
        <div style="
          background: white;
          border-radius: 16px;
          padding: 24px;
          max-width: 400px;
          width: 90%;
          box-shadow: 0 20px 40px rgba(0,0,0,0.2);
        ">
          <div style="
            width: 48px;
            height: 48px;
            margin: 0 auto 16px;
            background: #dbeafe;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
          ">
            <svg viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" style="width:24px;height:24px">
              <path d="M3 15v4c0 1.1.9 2 2 2h14a2 2 0 002-2v-4M17 8l-5-5-5 5M12 4.2v10.3"/>
            </svg>
          </div>

          <h3 style="
            font-size: 18px;
            font-weight: 700;
            text-align: center;
            margin: 0 0 8px;
            color: #1f2937;
          ">發現未儲存的草稿</h3>

          <p style="
            font-size: 14px;
            color: #6b7280;
            text-align: center;
            margin: 0 0 24px;
          ">
            您有 ${ageText} 編輯的草稿，是否要恢復？
          </p>

          <div style="display: flex; gap: 12px;">
            <button id="xirs-draft-discard" style="
              flex: 1;
              background: #f3f4f6;
              color: #374151;
              border: none;
              padding: 12px;
              border-radius: 8px;
              font-weight: 600;
              cursor: pointer;
            ">捨棄</button>

            <button id="xirs-draft-restore" style="
              flex: 1;
              background: #3b82f6;
              color: white;
              border: none;
              padding: 12px;
              border-radius: 8px;
              font-weight: 600;
              cursor: pointer;
            ">恢復草稿</button>
          </div>
        </div>
      `;

      document.body.appendChild(dialog);

      dialog.querySelector('#xirs-draft-discard').addEventListener('click', async () => {
        await this.clear(formId);
        dialog.remove();
        if (onDiscard) onDiscard();
        resolve(false);
      });

      dialog.querySelector('#xirs-draft-restore').addEventListener('click', () => {
        dialog.remove();
        if (onRestore) onRestore(draft.data);
        resolve(true);
      });
    });
  },

  /**
   * 列出所有草稿
   */
  async list() {
    if (!this.state.db) await this.init();

    return new Promise((resolve, reject) => {
      const tx = this.state.db.transaction(this.config.storeName, 'readonly');
      const store = tx.objectStore(this.config.storeName);
      const request = store.getAll();

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const now = Date.now();
        const valid = request.result.filter(d => now - d.updatedAt < this.config.maxAge);
        resolve(valid);
      };
    });
  }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = XIRS_DRAFT;
}

console.log('xIRS Draft Recovery v1.0.0 loaded');
