/**
 * xIRS Offline Stub for Vercel Demo
 * Offline support disabled in demo mode
 */
window.xIRS = window.xIRS || {};
window.xIRS.Offline = {
    isOnline: function() { return navigator.onLine; },
    queue: function() {},
    sync: function() {},
    isStub: true
};
