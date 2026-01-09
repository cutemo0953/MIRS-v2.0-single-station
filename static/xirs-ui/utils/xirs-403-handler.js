/**
 * xIRS 403 Handler v1.0
 *
 * 統一處理 403 Forbidden 錯誤
 * - 顯示友善錯誤訊息
 * - 提供 Break-Glass 選項 (如有權限)
 * - 記錄稽核事件
 *
 * Usage:
 *   XIRS_403.init({
 *     onBreakGlass: (action, reason) => {...},
 *     allowBreakGlass: true
 *   });
 *
 *   // 在 fetch wrapper 中使用
 *   if (response.status === 403) {
 *     const result = await XIRS_403.handle(response, { action: 'create_order' });
 *   }
 */

const XIRS_403 = {
  VERSION: '1.0.0',

  // 錯誤類型對照
  ERROR_TYPES: {
    CAPABILITY_DENIED: {
      title: '權限不足',
      message: '您沒有執行此操作的權限。',
      icon: 'shield-x',
      allowBreakGlass: true
    },
    CAPABILITY_STALE: {
      title: '權限已變更',
      message: '您的權限已被更新，請重新登入以取得最新權限。',
      icon: 'refresh',
      allowBreakGlass: false,
      action: 'relogin'
    },
    OFFLINE_EXPIRED: {
      title: '離線授權過期',
      message: '您的離線操作權限已到期，請連接網路後重新登入。',
      icon: 'wifi-off',
      allowBreakGlass: false,
      action: 'reconnect'
    },
    TOKEN_EXPIRED: {
      title: '登入已過期',
      message: '您的登入已過期，請重新登入。',
      icon: 'clock',
      allowBreakGlass: false,
      action: 'relogin'
    },
    ASSIGNMENT_INVALID: {
      title: '派工無效',
      message: '您目前沒有有效的派工。請聯繫管理員。',
      icon: 'user-x',
      allowBreakGlass: false
    },
    UNKNOWN: {
      title: '存取被拒',
      message: '您沒有權限執行此操作。',
      icon: 'alert-circle',
      allowBreakGlass: false
    }
  },

  // 能力代碼友善名稱
  CAPABILITY_NAMES: {
    'CAP_VITAL_SIGNS_WRITE': '記錄生命徵象',
    'CAP_HANDOFF_ACCEPT': '接收病患交班',
    'CAP_HANDOFF_CREATE': '發起病患交班',
    'CAP_ORDER_CREATE': '開立醫囑',
    'CAP_MEDICATION_DISPENSE': '發放藥品',
    'CAP_CONTROLLED_MED': '管制藥品操作',
    'CAP_INVENTORY_DEDUCT': '扣減庫存',
    'CAP_INVENTORY_RECEIVE': '收貨入庫',
    'CAP_BILLING_FINALIZE': '結帳收款',
    'CAP_ADMIN_USERS': '管理使用者',
    'CAP_STATION_MANAGE': '管理站點設定'
  },

  // 配置
  config: {
    allowBreakGlass: false,
    onBreakGlass: null,
    onRelogin: null,
    onReconnect: null
  },

  // DOM 元素
  elements: {
    modal: null
  },

  /**
   * 初始化
   */
  init(options = {}) {
    this.config.allowBreakGlass = options.allowBreakGlass || false;
    this.config.onBreakGlass = options.onBreakGlass;
    this.config.onRelogin = options.onRelogin || (() => window.location.href = '/login');
    this.config.onReconnect = options.onReconnect || (() => window.location.reload());

    console.log('[xIRS 403] Initialized', {
      allowBreakGlass: this.config.allowBreakGlass
    });
  },

  /**
   * 處理 403 錯誤
   * @param {Response|Object} response - fetch Response 或解析後的 JSON
   * @param {Object} context - 上下文資訊
   * @returns {Promise<Object>} - { handled, breakGlass, retry }
   */
  async handle(response, context = {}) {
    let errorData;

    if (response instanceof Response) {
      try {
        errorData = await response.json();
      } catch {
        errorData = { error: 'UNKNOWN' };
      }
    } else {
      errorData = response;
    }

    const errorType = errorData.error || 'UNKNOWN';
    const errorInfo = this.ERROR_TYPES[errorType] || this.ERROR_TYPES.UNKNOWN;
    const requiredCap = errorData.required_capability || context.requiredCapability;

    // 顯示錯誤 Modal
    return this.showErrorModal({
      ...errorInfo,
      errorType,
      errorData,
      context,
      requiredCap
    });
  },

  /**
   * 顯示錯誤 Modal
   */
  showErrorModal(options) {
    return new Promise((resolve) => {
      const {
        title,
        message,
        icon,
        allowBreakGlass,
        action,
        errorType,
        errorData,
        context,
        requiredCap
      } = options;

      // 建立 Modal
      let modal = document.getElementById('xirs-403-modal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'xirs-403-modal';
        modal.setAttribute('role', 'alertdialog');
        modal.setAttribute('aria-modal', 'true');
        document.body.appendChild(modal);
        this.elements.modal = modal;
      }

      const showBreakGlass = allowBreakGlass && this.config.allowBreakGlass;
      const capName = requiredCap ? (this.CAPABILITY_NAMES[requiredCap] || requiredCap) : '';

      modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10001;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.6);
        animation: xirs-fade-in 0.2s ease-out;
      `;

      modal.innerHTML = `
        <div style="
          background: white;
          border-radius: 16px;
          padding: 32px;
          max-width: 400px;
          width: 90%;
          box-shadow: 0 20px 40px rgba(0,0,0,0.3);
          text-align: center;
        ">
          <!-- Icon -->
          <div style="
            width: 64px;
            height: 64px;
            margin: 0 auto 16px;
            background: #fee2e2;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
          ">
            ${this.getIcon(icon)}
          </div>

          <!-- Title -->
          <h2 style="
            font-size: 20px;
            font-weight: 700;
            color: #1f2937;
            margin: 0 0 8px;
          ">${title}</h2>

          <!-- Message -->
          <p style="
            font-size: 14px;
            color: #6b7280;
            margin: 0 0 16px;
            line-height: 1.5;
          ">${message}</p>

          ${requiredCap ? `
            <p style="
              font-size: 12px;
              color: #9ca3af;
              margin: 0 0 24px;
            ">
              需要權限: <strong>${capName}</strong>
            </p>
          ` : ''}

          <!-- Actions -->
          <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
            ${action === 'relogin' ? `
              <button id="xirs-403-relogin" style="
                background: #3b82f6;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
              ">重新登入</button>
            ` : ''}

            ${action === 'reconnect' ? `
              <button id="xirs-403-reconnect" style="
                background: #10b981;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
              ">重新連線</button>
            ` : ''}

            ${showBreakGlass ? `
              <button id="xirs-403-breakglass" style="
                background: #dc2626;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
              ">緊急破窗</button>
            ` : ''}

            <button id="xirs-403-close" style="
              background: #f3f4f6;
              color: #374151;
              border: none;
              padding: 12px 24px;
              border-radius: 8px;
              font-size: 14px;
              font-weight: 600;
              cursor: pointer;
            ">關閉</button>
          </div>

          ${showBreakGlass ? `
            <p style="
              font-size: 11px;
              color: #9ca3af;
              margin: 16px 0 0;
            ">
              緊急破窗將被最高級別稽核記錄
            </p>
          ` : ''}
        </div>
      `;

      // 綁定事件
      modal.querySelector('#xirs-403-close')?.addEventListener('click', () => {
        this.hideModal();
        resolve({ handled: true, breakGlass: false, retry: false });
      });

      modal.querySelector('#xirs-403-relogin')?.addEventListener('click', () => {
        this.hideModal();
        if (this.config.onRelogin) this.config.onRelogin();
        resolve({ handled: true, breakGlass: false, retry: false, action: 'relogin' });
      });

      modal.querySelector('#xirs-403-reconnect')?.addEventListener('click', () => {
        this.hideModal();
        if (this.config.onReconnect) this.config.onReconnect();
        resolve({ handled: true, breakGlass: false, retry: false, action: 'reconnect' });
      });

      modal.querySelector('#xirs-403-breakglass')?.addEventListener('click', () => {
        this.hideModal();
        this.showBreakGlassDialog(context).then((result) => {
          resolve({ handled: true, breakGlass: result.confirmed, retry: result.confirmed, reason: result.reason });
        });
      });

      // ESC 關閉
      const escHandler = (e) => {
        if (e.key === 'Escape') {
          this.hideModal();
          document.removeEventListener('keydown', escHandler);
          resolve({ handled: true, breakGlass: false, retry: false });
        }
      };
      document.addEventListener('keydown', escHandler);
    });
  },

  /**
   * 顯示 Break-Glass 對話框
   */
  showBreakGlassDialog(context) {
    return new Promise((resolve) => {
      let dialog = document.getElementById('xirs-breakglass-dialog');
      if (!dialog) {
        dialog = document.createElement('div');
        dialog.id = 'xirs-breakglass-dialog';
        document.body.appendChild(dialog);
      }

      dialog.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10002;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(220, 38, 38, 0.95);
        animation: xirs-fade-in 0.2s ease-out;
      `;

      dialog.innerHTML = `
        <div style="
          background: #1f2937;
          border: 4px solid #f87171;
          border-radius: 16px;
          padding: 32px;
          max-width: 450px;
          width: 90%;
          color: white;
        ">
          <h2 style="
            font-size: 24px;
            font-weight: 700;
            margin: 0 0 16px;
            display: flex;
            align-items: center;
            gap: 12px;
          ">
            <span style="font-size: 32px;">&#9888;</span>
            緊急破窗操作
          </h2>

          <p style="
            font-size: 14px;
            color: #d1d5db;
            margin: 0 0 24px;
            line-height: 1.6;
          ">
            您即將執行<strong>緊急破窗</strong>操作，繞過正常權限檢查。
            <br><br>
            此操作將被<strong style="color: #f87171;">最高級別稽核記錄</strong>，
            包含您的身分、時間、操作內容及原因。
          </p>

          <label style="
            display: block;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 8px;
          ">請說明緊急原因 (必填)</label>

          <textarea id="xirs-breakglass-reason"
                    placeholder="例: 主治醫師昏倒，需立即處理病患..."
                    style="
                      width: 100%;
                      min-height: 80px;
                      padding: 12px;
                      border: 2px solid #374151;
                      border-radius: 8px;
                      font-size: 14px;
                      background: #111827;
                      color: white;
                      resize: vertical;
                      box-sizing: border-box;
                    "></textarea>

          <p style="
            font-size: 12px;
            color: #9ca3af;
            margin: 8px 0 24px;
          ">
            濫用破窗機制將面臨紀律處分
          </p>

          <div style="display: flex; gap: 12px;">
            <button id="xirs-breakglass-cancel" style="
              flex: 1;
              background: #374151;
              color: white;
              border: none;
              padding: 12px;
              border-radius: 8px;
              font-size: 14px;
              font-weight: 600;
              cursor: pointer;
            ">取消</button>

            <button id="xirs-breakglass-confirm" style="
              flex: 1;
              background: #dc2626;
              color: white;
              border: none;
              padding: 12px;
              border-radius: 8px;
              font-size: 14px;
              font-weight: 700;
              cursor: pointer;
            ">確認破窗執行</button>
          </div>
        </div>
      `;

      const reasonInput = dialog.querySelector('#xirs-breakglass-reason');

      dialog.querySelector('#xirs-breakglass-cancel').addEventListener('click', () => {
        dialog.style.display = 'none';
        resolve({ confirmed: false });
      });

      dialog.querySelector('#xirs-breakglass-confirm').addEventListener('click', () => {
        const reason = reasonInput.value.trim();
        if (!reason) {
          reasonInput.style.borderColor = '#f87171';
          reasonInput.focus();
          return;
        }

        dialog.style.display = 'none';

        // 呼叫 Break-Glass callback
        if (this.config.onBreakGlass) {
          this.config.onBreakGlass(context.action, reason);
        }

        resolve({ confirmed: true, reason });
      });
    });
  },

  /**
   * 隱藏 Modal
   */
  hideModal() {
    if (this.elements.modal) {
      this.elements.modal.style.display = 'none';
    }
  },

  /**
   * 取得圖示 SVG
   */
  getIcon(icon) {
    const icons = {
      'shield-x': `<svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" style="width:32px;height:32px">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <line x1="9" y1="9" x2="15" y2="15"/>
        <line x1="15" y1="9" x2="9" y2="15"/>
      </svg>`,
      'refresh': `<svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" style="width:32px;height:32px">
        <polyline points="23,4 23,10 17,10"/>
        <polyline points="1,20 1,14 7,14"/>
        <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
      </svg>`,
      'wifi-off': `<svg viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2" style="width:32px;height:32px">
        <line x1="1" y1="1" x2="23" y2="23"/>
        <path d="M16.72 11.06A10.94 10.94 0 0119 12.55"/>
        <path d="M5 12.55a10.94 10.94 0 015.17-2.39"/>
        <path d="M10.71 5.05A16 16 0 0122.58 9"/>
        <path d="M1.42 9a15.91 15.91 0 014.7-2.88"/>
        <path d="M8.53 16.11a6 6 0 016.95 0"/>
        <line x1="12" y1="20" x2="12.01" y2="20"/>
      </svg>`,
      'clock': `<svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" style="width:32px;height:32px">
        <circle cx="12" cy="12" r="10"/>
        <polyline points="12,6 12,12 16,14"/>
      </svg>`,
      'user-x': `<svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" style="width:32px;height:32px">
        <path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/>
        <circle cx="8.5" cy="7" r="4"/>
        <line x1="18" y1="8" x2="23" y2="13"/>
        <line x1="23" y1="8" x2="18" y2="13"/>
      </svg>`,
      'alert-circle': `<svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" style="width:32px;height:32px">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>`
    };
    return icons[icon] || icons['alert-circle'];
  },

  /**
   * Fetch Wrapper - 自動處理 403
   */
  async fetch(url, options = {}) {
    const response = await fetch(url, options);

    if (response.status === 403) {
      const result = await this.handle(response, {
        action: options.action || url,
        method: options.method || 'GET'
      });

      if (result.retry && result.breakGlass) {
        // 重試請求，加入 break-glass header
        const retryOptions = {
          ...options,
          headers: {
            ...options.headers,
            'X-Break-Glass': 'true',
            'X-Break-Glass-Reason': result.reason
          }
        };
        return fetch(url, retryOptions);
      }

      return result;
    }

    return response;
  }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = XIRS_403;
}

console.log('xIRS 403 Handler v1.0.0 loaded');
