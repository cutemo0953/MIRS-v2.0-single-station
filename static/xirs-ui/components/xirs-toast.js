/**
 * xIRS Toast Component v1.0
 *
 * 統一 Toast 通知元件
 *
 * Usage:
 *   XIRS_TOAST.success('操作成功');
 *   XIRS_TOAST.error('發生錯誤');
 *   XIRS_TOAST.warning('請注意');
 *   XIRS_TOAST.info('提示訊息');
 */

const XIRS_TOAST = {
  VERSION: '1.0.0',

  // 配置
  config: {
    position: 'top-center',  // top-center | top-right | bottom-center
    duration: 3000,          // 預設顯示時間
    maxToasts: 3,            // 最多同時顯示
    gap: 8                   // Toast 間距
  },

  // Toast 容器
  container: null,

  // 目前顯示的 Toasts
  toasts: [],

  /**
   * 初始化
   */
  init() {
    if (this.container) return;

    this.container = document.createElement('div');
    this.container.id = 'xirs-toast-container';
    this.container.setAttribute('aria-live', 'polite');
    this.container.setAttribute('aria-label', 'Notifications');

    // 根據位置設定樣式
    const positionStyles = {
      'top-center': 'top: 16px; left: 50%; transform: translateX(-50%);',
      'top-right': 'top: 16px; right: 16px;',
      'bottom-center': 'bottom: 16px; left: 50%; transform: translateX(-50%);'
    };

    this.container.style.cssText = `
      position: fixed;
      ${positionStyles[this.config.position] || positionStyles['top-center']}
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: ${this.config.gap}px;
      pointer-events: none;
    `;

    document.body.appendChild(this.container);
  },

  /**
   * 顯示 Toast
   */
  show(message, type = 'info', options = {}) {
    this.init();

    const duration = options.duration || this.config.duration;
    const action = options.action; // { text, onClick }

    // 移除超過最大數量的 Toast
    while (this.toasts.length >= this.config.maxToasts) {
      this.dismiss(this.toasts[0].id);
    }

    const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // 圖示對照
    const icons = {
      success: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
      </svg>`,
      error: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
      </svg>`,
      warning: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
      </svg>`,
      info: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>`
    };

    // 樣式對照
    const styles = {
      success: 'background: #10b981; color: white;',
      error: 'background: #ef4444; color: white;',
      warning: 'background: #f59e0b; color: #1f2937;',
      info: 'background: #3b82f6; color: white;'
    };

    // 建立 Toast 元素
    const toast = document.createElement('div');
    toast.id = id;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('data-testid', 'toast');
    toast.style.cssText = `
      ${styles[type] || styles.info}
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 16px;
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      font-size: 14px;
      font-weight: 500;
      pointer-events: auto;
      animation: xirs-slide-down 0.3s ease-out;
      max-width: 400px;
      min-width: 200px;
    `;

    // 內容
    let html = `
      <span style="flex-shrink: 0;">${icons[type] || icons.info}</span>
      <span style="flex: 1;">${this.escapeHtml(message)}</span>
    `;

    // 可選的動作按鈕
    if (action) {
      html += `
        <button
          onclick="XIRS_TOAST.handleAction('${id}', '${action.callback}')"
          style="
            background: rgba(255,255,255,0.2);
            border: none;
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            color: inherit;
          "
        >${this.escapeHtml(action.text)}</button>
      `;
    }

    // 關閉按鈕
    html += `
      <button
        onclick="XIRS_TOAST.dismiss('${id}')"
        style="
          background: none;
          border: none;
          padding: 4px;
          cursor: pointer;
          opacity: 0.7;
          color: inherit;
        "
        aria-label="關閉"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width: 16px; height: 16px;">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    `;

    toast.innerHTML = html;
    this.container.appendChild(toast);

    // 記錄
    const toastData = { id, element: toast, timer: null };
    this.toasts.push(toastData);

    // 自動關閉
    if (duration > 0) {
      toastData.timer = setTimeout(() => {
        this.dismiss(id);
      }, duration);
    }

    return id;
  },

  /**
   * 關閉 Toast
   */
  dismiss(id) {
    const index = this.toasts.findIndex(t => t.id === id);
    if (index === -1) return;

    const toastData = this.toasts[index];

    // 清除計時器
    if (toastData.timer) {
      clearTimeout(toastData.timer);
    }

    // 動畫移除
    toastData.element.style.animation = 'xirs-fade-out 0.2s ease-out forwards';
    toastData.element.style.opacity = '0';

    setTimeout(() => {
      toastData.element.remove();
    }, 200);

    // 從陣列移除
    this.toasts.splice(index, 1);
  },

  /**
   * 處理動作按鈕點擊
   */
  handleAction(id, callbackName) {
    if (window[callbackName] && typeof window[callbackName] === 'function') {
      window[callbackName]();
    }
    this.dismiss(id);
  },

  /**
   * HTML 跳脫
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  // ========================================
  // 便捷方法
  // ========================================

  success(message, options = {}) {
    return this.show(message, 'success', options);
  },

  error(message, options = {}) {
    return this.show(message, 'error', { duration: 5000, ...options });
  },

  warning(message, options = {}) {
    return this.show(message, 'warning', options);
  },

  info(message, options = {}) {
    return this.show(message, 'info', options);
  },

  /**
   * 清除所有 Toast
   */
  clear() {
    [...this.toasts].forEach(t => this.dismiss(t.id));
  }
};

// CSS for fade-out animation
const style = document.createElement('style');
style.textContent = `
  @keyframes xirs-fade-out {
    from { opacity: 1; transform: translateY(0); }
    to { opacity: 0; transform: translateY(-10px); }
  }
`;
document.head.appendChild(style);

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = XIRS_TOAST;
}

console.log('xIRS Toast v1.0.0 loaded');
