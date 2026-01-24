/**
 * xIRS UI Stub for Vercel Demo
 * UI utilities disabled in demo mode
 */
window.xIRS = window.xIRS || {};
window.xIRS.UI = {
    toast: function(msg) { console.log('[xIRS.UI]', msg); },
    confirm: function() { return Promise.resolve(true); },
    isStub: true
};
