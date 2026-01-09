/**
 * xIRS Offline Banner v1.0
 *
 * 離線狀態指示器，含倒數計時與顏色心理學
 *
 * 狀態:
 * - ONLINE: 線上 (不顯示)
 * - OFFLINE_SAFE: 離線 > 4h (綠)
 * - OFFLINE_CAUTION: 離線 < 1h (黃)
 * - OFFLINE_WARNING: 離線 < 15m (橙)
 * - OFFLINE_EXPIRED: 已過期 (紅，全屏阻擋)
 *
 * Usage:
 *   XIRS_OFFLINE.init({ offlineExp: token.offline_exp });
 *   XIRS_OFFLINE.setPendingCount(3);
 */

const XIRS_OFFLINE = {
  VERSION: '1.0.0',

  // 狀態
  state: {
    isOnline: navigator.onLine,
    offlineExp: null,           // Unix timestamp
    pendingCount: 0,
    lastSyncTime: null
  },

  // DOM 元素
  elements: {
    banner: null,
    expiredBlock: null
  },

  // 計時器
  countdownInterval: null,

  /**
   * 初始化
   */
  init(options = {}) {
    if (options.offlineExp) {
      this.state.offlineExp = options.offlineExp;
    }
    if (options.lastSyncTime) {
      this.state.lastSyncTime = options.lastSyncTime;
    }

    // 監聽網路狀態
    window.addEventListener('online', () => this.handleOnline());
    window.addEventListener('offline', () => this.handleOffline());

    // 建立 DOM 元素
    this.createBanner();
    this.createExpiredBlock();

    // 初始狀態
    this.state.isOnline = navigator.onLine;
    this.update();

    // 啟動倒數
    this.startCountdown();

    console.log('[xIRS Offline] Initialized', {
      isOnline: this.state.isOnline,
      offlineExp: this.state.offlineExp
    });
  },

  /**
   * 建立 Banner
   */
  createBanner() {
    if (this.elements.banner) return;

    const banner = document.createElement('div');
    banner.id = 'xirs-offline-banner';
    banner.setAttribute('data-testid', 'offline-banner');
    banner.setAttribute('role', 'status');
    banner.setAttribute('aria-live', 'polite');
    banner.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 9998;
      display: none;
      align-items: center;
      justify-content: center;
      gap: 12px;
      padding: 8px 16px;
      font-size: 14px;
      font-weight: 500;
      transition: all 0.3s ease;
    `;

    document.body.appendChild(banner);
    this.elements.banner = banner;
  },

  /**
   * 建立過期阻擋畫面
   */
  createExpiredBlock() {
    if (this.elements.expiredBlock) return;

    const block = document.createElement('div');
    block.id = 'xirs-offline-expired-block';
    block.setAttribute('data-testid', 'offline-expired-block');
    block.setAttribute('role', 'alertdialog');
    block.setAttribute('aria-modal', 'true');
    block.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 10000;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(220, 38, 38, 0.95);
      color: white;
      flex-direction: column;
      gap: 24px;
      padding: 32px;
    `;

    block.innerHTML = `
      <div style="font-size: 64px;">&#9940;</div>
      <h1 style="font-size: 24px; font-weight: bold; margin: 0;">離線授權已過期</h1>
      <p style="font-size: 16px; text-align: center; max-width: 400px; margin: 0; opacity: 0.9;">
        您的離線操作權限已到期。<br>
        為確保資料安全，請連接網路後重新登入。
      </p>
      <button
        onclick="XIRS_OFFLINE.handleReconnect()"
        style="
          background: white;
          color: #dc2626;
          border: none;
          padding: 12px 32px;
          font-size: 16px;
          font-weight: bold;
          border-radius: 8px;
          cursor: pointer;
          transition: transform 0.2s;
        "
        onmouseover="this.style.transform='scale(1.05)'"
        onmouseout="this.style.transform='scale(1)'"
      >
        重新連線
      </button>
    `;

    document.body.appendChild(block);
    this.elements.expiredBlock = block;
  },

  /**
   * 更新顯示
   */
  update() {
    const { isOnline, offlineExp, pendingCount } = this.state;

    // 線上：隱藏 Banner
    if (isOnline) {
      this.hideBanner();
      this.hideExpiredBlock();
      return;
    }

    // 離線：檢查是否過期
    const now = Date.now() / 1000;
    const remainingSeconds = offlineExp ? offlineExp - now : Infinity;

    if (offlineExp && remainingSeconds <= 0) {
      // 已過期：全屏阻擋
      this.showExpiredBlock();
      return;
    }

    // 離線但未過期：顯示 Banner
    this.hideExpiredBlock();
    this.showBanner(remainingSeconds, pendingCount);
  },

  /**
   * 顯示 Banner
   */
  showBanner(remainingSeconds, pendingCount) {
    if (!this.elements.banner) return;

    const style = this.getTimerStyle(remainingSeconds);
    const timeStr = this.formatTime(remainingSeconds);

    this.elements.banner.style.cssText += `
      display: flex;
      background: ${style.bgColor};
      color: ${style.textColor};
      ${style.animation ? `animation: ${style.animation} 1s ease-in-out infinite;` : ''}
    `;

    let html = `
      <span>${style.icon}</span>
      <span>離線模式</span>
    `;

    if (remainingSeconds !== Infinity) {
      html += `<span style="font-weight: bold;">|</span>`;
      html += `<span>授權剩餘 <strong>${timeStr}</strong></span>`;
    }

    if (pendingCount > 0) {
      html += `<span style="font-weight: bold;">|</span>`;
      html += `<span>${pendingCount} 筆待同步</span>`;
    }

    if (remainingSeconds < 15 * 60 && remainingSeconds > 0) {
      html += `
        <button
          onclick="XIRS_OFFLINE.handleReconnect()"
          style="
            background: rgba(255,255,255,0.3);
            border: none;
            padding: 4px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            color: inherit;
            margin-left: 8px;
          "
        >立即連線</button>
      `;
    }

    this.elements.banner.innerHTML = html;

    // 震動回饋 (< 15分鐘)
    if (style.vibrate && navigator.vibrate) {
      navigator.vibrate(200);
    }
  },

  /**
   * 隱藏 Banner
   */
  hideBanner() {
    if (this.elements.banner) {
      this.elements.banner.style.display = 'none';
    }
  },

  /**
   * 顯示過期阻擋
   */
  showExpiredBlock() {
    if (this.elements.expiredBlock) {
      this.elements.expiredBlock.style.display = 'flex';
      this.elements.expiredBlock.classList.add('xirs-animate-pulse');
    }
    // 隱藏 Banner
    this.hideBanner();
  },

  /**
   * 隱藏過期阻擋
   */
  hideExpiredBlock() {
    if (this.elements.expiredBlock) {
      this.elements.expiredBlock.style.display = 'none';
    }
  },

  /**
   * 取得計時器樣式 (顏色心理學)
   */
  getTimerStyle(remainingSeconds) {
    const hours = remainingSeconds / 3600;

    if (remainingSeconds <= 0) {
      return {
        bgColor: '#dc2626',  // red-600
        textColor: 'white',
        animation: 'xirs-pulse',
        vibrate: true,
        icon: '&#9940;'  // ⛔
      };
    } else if (hours < 0.25) { // < 15 分鐘
      return {
        bgColor: '#f97316',  // orange-500
        textColor: 'white',
        animation: 'xirs-pulse-slow',
        vibrate: false,
        icon: '&#9888;'  // ⚠
      };
    } else if (hours < 1) { // < 1 小時
      return {
        bgColor: '#f59e0b',  // amber-500
        textColor: '#1f2937',
        animation: null,
        vibrate: false,
        icon: '&#9888;'  // ⚠
      };
    } else {
      return {
        bgColor: '#10b981',  // green-500
        textColor: 'white',
        animation: null,
        vibrate: false,
        icon: '&#128268;'  // 🔌 (離線但安全)
      };
    }
  },

  /**
   * 格式化時間
   */
  formatTime(seconds) {
    if (seconds === Infinity) return '--:--:--';
    if (seconds <= 0) return '00:00:00';

    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  },

  /**
   * 啟動倒數計時
   */
  startCountdown() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval);
    }

    this.countdownInterval = setInterval(() => {
      this.update();
    }, 1000);
  },

  /**
   * 停止倒數計時
   */
  stopCountdown() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval);
      this.countdownInterval = null;
    }
  },

  /**
   * 處理上線
   */
  handleOnline() {
    console.log('[xIRS Offline] Online');
    this.state.isOnline = true;
    this.update();

    // 通知 (如果有待同步)
    if (this.state.pendingCount > 0 && typeof XIRS_TOAST !== 'undefined') {
      XIRS_TOAST.success(`網路已恢復，${this.state.pendingCount} 筆操作同步中...`);
    }

    // 觸發同步事件
    window.dispatchEvent(new CustomEvent('xirs:online', {
      detail: { pendingCount: this.state.pendingCount }
    }));
  },

  /**
   * 處理離線
   */
  handleOffline() {
    console.log('[xIRS Offline] Offline');
    this.state.isOnline = false;
    this.update();

    // 觸發離線事件
    window.dispatchEvent(new CustomEvent('xirs:offline'));
  },

  /**
   * 處理重新連線按鈕
   */
  handleReconnect() {
    // 嘗試重新載入
    window.location.reload();
  },

  /**
   * 設定離線過期時間
   */
  setOfflineExp(timestamp) {
    this.state.offlineExp = timestamp;
    this.update();
  },

  /**
   * 設定待同步數量
   */
  setPendingCount(count) {
    this.state.pendingCount = count;
    if (!this.state.isOnline) {
      this.update();
    }
  },

  /**
   * 增加待同步數量
   */
  incrementPending() {
    this.state.pendingCount++;
    if (!this.state.isOnline) {
      this.update();
    }
  },

  /**
   * 減少待同步數量
   */
  decrementPending() {
    this.state.pendingCount = Math.max(0, this.state.pendingCount - 1);
    if (!this.state.isOnline) {
      this.update();
    }
  },

  /**
   * 檢查是否過期
   */
  isExpired() {
    if (!this.state.offlineExp) return false;
    return Date.now() / 1000 > this.state.offlineExp;
  },

  /**
   * 取得剩餘秒數
   */
  getRemainingSeconds() {
    if (!this.state.offlineExp) return Infinity;
    return Math.max(0, this.state.offlineExp - Date.now() / 1000);
  }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = XIRS_OFFLINE;
}

console.log('xIRS Offline Banner v1.0.0 loaded');
