/**
 * MIRS Role Badge & Quick Lock Component v1.1
 *
 * v1.1: 修復角色切換後重整頁面不持久的問題
 *       - 增加 debug 日誌
 *       - 修復 init() 沒有重讀 localStorage 的問題
 *
 * 用途：
 * - Active Role Badge: 永久顯示目前角色
 * - Quick Lock: 共享裝置快速鎖定
 * - Role Switcher: 角色切換 (需 PIN)
 *
 * 使用方式：
 * 1. 引入此檔案: <script src="/static/js/mirs-role-badge.js"></script>
 * 2. 在 Alpine.js app 中加入: ...mirsRoleBadge()
 * 3. 在 HTML 中加入: <div x-html="roleBadgeHTML"></div>
 *
 * 依賴：
 * - Alpine.js
 */

// Role color mapping
const MIRS_ROLE_COLORS = {
  ADMIN: { bg: 'bg-purple-600', text: 'text-white', label: '管理員' },
  NURSE: { bg: 'bg-pink-600', text: 'text-white', label: '護理師' },
  DOCTOR: { bg: 'bg-blue-600', text: 'text-white', label: '醫師' },
  EMT: { bg: 'bg-orange-600', text: 'text-white', label: '救護員' },
  ANESTHESIA: { bg: 'bg-indigo-600', text: 'text-white', label: '麻醉師' },
  SURGEON: { bg: 'bg-teal-600', text: 'text-white', label: '外科醫師' },
  SUPPLY: { bg: 'bg-cyan-600', text: 'text-white', label: '供應' },
  LOGISTICS: { bg: 'bg-amber-600', text: 'text-white', label: '後勤' },
  VOLUNTEER: { bg: 'bg-gray-600', text: 'text-white', label: '志工' },
  DEFAULT: { bg: 'bg-gray-600', text: 'text-white', label: '使用者' }
};

// Role Badge HTML template
function getMirsRoleBadgeHTML(role, userName, isLocked, showSwitcher, availableRoles) {
  const roleConfig = MIRS_ROLE_COLORS[role] || MIRS_ROLE_COLORS.DEFAULT;
  const roleLabel = roleConfig.label || role;

  return `
    <!-- Active Role Badge (右上角) -->
    <div class="fixed top-2 right-2 z-[9998]" x-show="!_roleBadge.isLocked">
      <div class="flex items-center gap-2 px-3 py-1.5 rounded-full ${roleConfig.bg} ${roleConfig.text} text-sm font-medium shadow-lg cursor-pointer hover:opacity-90 transition"
           @click="_roleBadge.showRoleSwitcher = true"
           title="點擊切換角色">
        <!-- Role Icon -->
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
        </svg>
        <!-- Role Name -->
        <span>${roleLabel}</span>
        <!-- Switch Icon -->
        <svg class="w-3 h-3 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </div>
    </div>

    <!-- Quick Lock Button (右下角) -->
    <button @click="_roleBadge.lockScreen()"
            x-show="!_roleBadge.isLocked && _roleBadge.enableQuickLock"
            class="fixed bottom-4 right-4 z-[9998] p-3 rounded-full bg-red-600 text-white shadow-lg hover:bg-red-700 transition"
            title="快速鎖定">
      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
      </svg>
    </button>

    <!-- Lock Screen Overlay -->
    <div x-show="_roleBadge.isLocked"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         class="fixed inset-0 bg-gray-900 z-[9999] flex items-center justify-center">
      <div class="text-center p-8">
        <div class="text-6xl mb-4">&#128274;</div>
        <p class="text-white text-xl mb-2">螢幕已鎖定</p>
        <p class="text-gray-400 text-sm mb-6" x-text="_roleBadge.userName || '使用者'"></p>
        <input type="password"
               x-ref="pinInput"
               placeholder="輸入 PIN 解鎖"
               maxlength="6"
               @keyup.enter="_roleBadge.unlockWithPin($event.target.value)"
               class="px-4 py-3 rounded-lg text-center text-2xl tracking-widest w-48 bg-gray-800 text-white border border-gray-700 focus:border-blue-500 focus:outline-none">
        <p class="text-red-400 text-sm mt-2" x-show="_roleBadge.lockError" x-text="_roleBadge.lockError"></p>
        <p class="text-gray-500 text-xs mt-4">預設 PIN: 1234</p>
      </div>
    </div>

    <!-- Role Switcher Modal -->
    <div x-show="_roleBadge.showRoleSwitcher"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         class="fixed inset-0 bg-black/50 z-[9999] flex items-start justify-center pt-20"
         @click.self="_roleBadge.showRoleSwitcher = false">
      <div class="bg-white rounded-xl shadow-2xl max-w-sm w-full mx-4 overflow-hidden"
           @click.stop>
        <div class="p-4 border-b bg-gray-50">
          <h3 class="text-lg font-bold text-gray-800">切換角色</h3>
          <p class="text-sm text-gray-500">選擇要切換的角色</p>
        </div>

        <div class="p-4 space-y-2 max-h-64 overflow-y-auto">
          <template x-for="r in _roleBadge.availableRoles" :key="r.code">
            <button @click="_roleBadge.selectRoleToSwitch(r.code)"
                    class="w-full p-3 border rounded-lg text-left hover:bg-gray-50 transition flex items-center gap-3"
                    :class="r.code === _roleBadge.activeRole ? 'ring-2 ring-blue-500 bg-blue-50' : ''">
              <div class="w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-bold"
                   :class="r.color || 'bg-gray-500'"
                   x-text="r.label.charAt(0)"></div>
              <div class="flex-1">
                <div class="font-medium text-gray-800" x-text="r.label"></div>
                <div class="text-xs text-gray-500" x-text="r.description || ''"></div>
              </div>
              <svg x-show="r.code === _roleBadge.activeRole" class="w-5 h-5 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
              </svg>
            </button>
          </template>
        </div>

        <!-- PIN Input for Role Switch -->
        <div x-show="_roleBadge.pendingRoleSwitch" class="p-4 border-t bg-gray-50">
          <p class="text-sm text-gray-600 mb-2">
            切換至 <span class="font-bold" x-text="_roleBadge.pendingRoleSwitchLabel"></span> 需要驗證 PIN
          </p>
          <input type="password"
                 x-model="_roleBadge.switchPin"
                 placeholder="輸入 PIN"
                 maxlength="6"
                 @keyup.enter="_roleBadge.confirmRoleSwitch()"
                 class="w-full px-4 py-2 rounded-lg text-center text-xl tracking-widest border focus:border-blue-500 focus:outline-none">
          <p class="text-red-500 text-xs mt-1" x-show="_roleBadge.switchError" x-text="_roleBadge.switchError"></p>
        </div>

        <div class="p-4 border-t flex gap-2">
          <button @click="_roleBadge.showRoleSwitcher = false; _roleBadge.pendingRoleSwitch = null;"
                  class="flex-1 py-2 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200">
            取消
          </button>
          <button x-show="_roleBadge.pendingRoleSwitch"
                  @click="_roleBadge.confirmRoleSwitch()"
                  class="flex-1 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700">
            確認切換
          </button>
        </div>
      </div>
    </div>
  `;
}

// Alpine.js mixin for Role Badge
function mirsRoleBadge(options = {}) {
  const defaultOptions = {
    enableQuickLock: true,
    lockOnIdle: false,
    idleTimeout: 5 * 60 * 1000, // 5 minutes
    defaultPin: '1234',
    onRoleSwitch: null, // callback(oldRole, newRole)
    onLock: null,
    onUnlock: null
  };

  const config = { ...defaultOptions, ...options };

  return {
    _roleBadge: {
      // State
      activeRole: localStorage.getItem('mirs_active_role') || 'DEFAULT',
      userName: localStorage.getItem('mirs_user_name') || '',
      userId: localStorage.getItem('mirs_user_id') || '',
      isLocked: false,
      lockError: '',
      showRoleSwitcher: false,
      enableQuickLock: config.enableQuickLock,

      // Role Switch
      availableRoles: [],
      pendingRoleSwitch: null,
      pendingRoleSwitchLabel: '',
      switchPin: '',
      switchError: '',

      // Idle tracking
      idleTimer: null,

      // Initialize
      init() {
        // v1.1: 重讀 localStorage 確保狀態正確
        const savedRole = localStorage.getItem('mirs_active_role');
        const savedName = localStorage.getItem('mirs_user_name');
        const savedId = localStorage.getItem('mirs_user_id');

        console.log('[MIRS Role Badge] init() - localStorage:', {
          mirs_active_role: savedRole,
          mirs_user_name: savedName,
          mirs_user_id: savedId
        });

        // 如果 localStorage 有值，更新狀態
        if (savedRole) {
          this.activeRole = savedRole;
          console.log('[MIRS Role Badge] Restored role from localStorage:', savedRole);
        }
        if (savedName) this.userName = savedName;
        if (savedId) this.userId = savedId;

        // Load available roles
        this.loadAvailableRoles();

        // Setup idle tracking if enabled
        if (config.lockOnIdle) {
          this.setupIdleTracking();
        }

        // Listen for auth changes
        window.addEventListener('mirs-auth-change', (e) => {
          if (e.detail) {
            this.activeRole = e.detail.role || 'DEFAULT';
            this.userName = e.detail.name || '';
            this.userId = e.detail.id || '';
          }
        });
      },

      loadAvailableRoles() {
        // Try to load from localStorage or use defaults
        const storedRoles = localStorage.getItem('mirs_available_roles');
        if (storedRoles) {
          try {
            this.availableRoles = JSON.parse(storedRoles);
          } catch (e) {
            this.availableRoles = this.getDefaultRoles();
          }
        } else {
          this.availableRoles = this.getDefaultRoles();
        }
      },

      getDefaultRoles() {
        return [
          { code: 'SURGEON', label: '外科醫師', color: 'bg-teal-600', description: '手術執刀' },
          { code: 'ANESTHESIA', label: '麻醉師', color: 'bg-indigo-600', description: '麻醉監控' },
          { code: 'NURSE', label: '護理師', color: 'bg-pink-600', description: '臨床護理' },
          { code: 'EMT', label: '救護員', color: 'bg-orange-600', description: '緊急救護' },
          { code: 'SUPPLY', label: '供應', color: 'bg-cyan-600', description: '器材供應' },
          { code: 'LOGISTICS', label: '後勤', color: 'bg-amber-600', description: '庫存管理' }
        ];
      },

      // Lock Screen
      lockScreen() {
        this.isLocked = true;
        this.lockError = '';
        if (config.onLock) config.onLock();

        // Focus PIN input after transition
        setTimeout(() => {
          const pinInput = document.querySelector('[x-ref="pinInput"]');
          if (pinInput) {
            pinInput.focus();
          }
        }, 250);
      },

      unlockWithPin(pin) {
        // In production, verify against server
        // For now, use local PIN
        const userPin = localStorage.getItem('mirs_user_pin') || config.defaultPin;

        if (pin === userPin) {
          this.isLocked = false;
          this.lockError = '';
          if (config.onUnlock) config.onUnlock();
        } else {
          this.lockError = 'PIN 錯誤，請重試';
          // Log failed attempt
          console.warn('[MIRS] Failed unlock attempt');
        }
      },

      // Role Switch
      selectRoleToSwitch(roleCode) {
        if (roleCode === this.activeRole) {
          this.showRoleSwitcher = false;
          return;
        }

        const role = this.availableRoles.find(r => r.code === roleCode);
        this.pendingRoleSwitch = roleCode;
        this.pendingRoleSwitchLabel = role ? role.label : roleCode;
        this.switchPin = '';
        this.switchError = '';
      },

      confirmRoleSwitch() {
        if (!this.pendingRoleSwitch) return;

        // Verify PIN
        const userPin = localStorage.getItem('mirs_user_pin') || config.defaultPin;

        if (this.switchPin !== userPin) {
          this.switchError = 'PIN 錯誤';
          return;
        }

        const oldRole = this.activeRole;
        const newRole = this.pendingRoleSwitch;

        console.log('[MIRS Role Badge] Switching role:', oldRole, '->', newRole);

        // Update role
        this.activeRole = newRole;
        localStorage.setItem('mirs_active_role', newRole);

        // v1.1: 驗證 localStorage 是否成功寫入
        const savedRole = localStorage.getItem('mirs_active_role');
        console.log('[MIRS Role Badge] Saved to localStorage:', savedRole);
        if (savedRole !== newRole) {
          console.error('[MIRS Role Badge] localStorage write FAILED!');
        }

        // Log role switch event
        this.logRoleSwitch(oldRole, newRole);

        // Callback
        if (config.onRoleSwitch) {
          config.onRoleSwitch(oldRole, newRole);
        }

        // Dispatch event
        window.dispatchEvent(new CustomEvent('mirs-role-switch', {
          detail: { oldRole, newRole, userId: this.userId }
        }));

        // Reset and close
        this.pendingRoleSwitch = null;
        this.switchPin = '';
        this.showRoleSwitcher = false;
      },

      logRoleSwitch(oldRole, newRole) {
        // Log to console (in production, send to server)
        const event = {
          type: 'AUTH_ROLE_SWITCH',
          timestamp: new Date().toISOString(),
          userId: this.userId,
          userName: this.userName,
          oldRole,
          newRole,
          device: navigator.userAgent
        };

        console.log('[MIRS] Role switch:', event);

        // Store in local audit log
        const auditLog = JSON.parse(localStorage.getItem('mirs_audit_log') || '[]');
        auditLog.push(event);
        // Keep last 100 events
        if (auditLog.length > 100) auditLog.shift();
        localStorage.setItem('mirs_audit_log', JSON.stringify(auditLog));
      },

      // Idle Tracking
      setupIdleTracking() {
        const resetTimer = () => {
          clearTimeout(this.idleTimer);
          this.idleTimer = setTimeout(() => {
            if (!this.isLocked) {
              this.lockScreen();
            }
          }, config.idleTimeout);
        };

        ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart'].forEach(event => {
          document.addEventListener(event, resetTimer, { passive: true });
        });

        resetTimer();
      },

      // Helper: Set role programmatically
      setRole(roleCode, userName = '', userId = '') {
        this.activeRole = roleCode;
        this.userName = userName;
        this.userId = userId;
        localStorage.setItem('mirs_active_role', roleCode);
        if (userName) localStorage.setItem('mirs_user_name', userName);
        if (userId) localStorage.setItem('mirs_user_id', userId);
      },

      // Helper: Get role display info
      getRoleInfo() {
        return MIRS_ROLE_COLORS[this.activeRole] || MIRS_ROLE_COLORS.DEFAULT;
      }
    },

    // Computed HTML for role badge
    get roleBadgeHTML() {
      return getMirsRoleBadgeHTML(
        this._roleBadge.activeRole,
        this._roleBadge.userName,
        this._roleBadge.isLocked,
        this._roleBadge.showRoleSwitcher,
        this._roleBadge.availableRoles
      );
    },

    // Initialize on mount
    initRoleBadge() {
      this._roleBadge.init();
    }
  };
}

// Export for use
if (typeof window !== 'undefined') {
  window.mirsRoleBadge = mirsRoleBadge;
  window.MIRS_ROLE_COLORS = MIRS_ROLE_COLORS;
}
