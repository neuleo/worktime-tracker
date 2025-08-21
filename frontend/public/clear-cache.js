// clear-cache.js - Utility script for clearing browser caches
// Add this to your deployment process or run manually when updating

(function() {
    'use strict';
    
    console.log('🧹 Starting cache clearing process...');
    
    // Clear Service Worker caches
    if ('serviceWorker' in navigator && 'caches' in window) {
        caches.keys().then(function(cacheNames) {
            console.log('Found caches:', cacheNames);
            return Promise.all(
                cacheNames.map(function(cacheName) {
                    console.log('Deleting cache:', cacheName);
                    return caches.delete(cacheName);
                })
            );
        }).then(function() {
            console.log('✅ All caches cleared');
            
            // Unregister service worker
            return navigator.serviceWorker.getRegistrations();
        }).then(function(registrations) {
            return Promise.all(registrations.map(function(registration) {
                console.log('Unregistering service worker:', registration);
                return registration.unregister();
            }));
        }).then(function() {
            console.log('✅ Service workers unregistered');
            
            // Force reload after clearing everything
            setTimeout(function() {
                console.log('🔄 Force reloading page...');
                window.location.reload(true);
            }, 1000);
        }).catch(function(error) {
            console.error('❌ Error clearing caches:', error);
        });
    } else {
        console.log('📱 Service Worker not supported, just reloading...');
        window.location.reload(true);
    }
})();

// Alternative: Add this to your console for manual cache clearing
function clearAllCaches() {
    if ('serviceWorker' in navigator && 'caches' in window) {
        Promise.all([
            caches.keys().then(names => Promise.all(names.map(name => caches.delete(name)))),
            navigator.serviceWorker.getRegistrations().then(regs => Promise.all(regs.map(reg => reg.unregister())))
        ]).then(() => {
            console.log('All caches and service workers cleared');
            window.location.reload(true);
        });
    }
}