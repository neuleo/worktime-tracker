const CACHE_NAME = 'arbeitszeit-v1';
const STATIC_CACHE = 'arbeitszeit-static-v1';

// Files to cache
const STATIC_FILES = [
  '/',
  '/static/js/bundle.js',
  '/static/css/main.css',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

// Install event
self.addEventListener('install', (event) => {
  console.log('Service Worker installing...');
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      console.log('Caching static files');
      return cache.addAll(STATIC_FILES).catch((error) => {
        console.warn('Failed to cache some files:', error);
      });
    })
  );
  self.skipWaiting();
});

// Activate event
self.addEventListener('activate', (event) => {
  console.log('Service Worker activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME && cacheName !== STATIC_CACHE) {
            console.log('Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch event - Network First for API, Cache First for static files
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Handle API requests (network first)
  if (url.pathname.startsWith('/stamp') || 
      url.pathname.startsWith('/status') || 
      url.pathname.startsWith('/day') || 
      url.pathname.startsWith('/week')) {
    
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Cache successful API responses
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          // Return cached version if available
          return caches.match(request).then((response) => {
            if (response) {
              return response;
            }
            // Return offline message for POST requests (stamp)
            if (request.method === 'POST') {
              return new Response(
                JSON.stringify({ error: 'Offline - Aktion wird später ausgeführt' }), 
                {
                  status: 503,
                  statusText: 'Service Unavailable',
                  headers: { 'Content-Type': 'application/json' }
                }
              );
            }
            throw new Error('Network error and no cached version available');
          });
        })
    );
    return;
  }

  // Handle static files (cache first)
  event.respondWith(
    caches.match(request).then((response) => {
      if (response) {
        return response;
      }
      
      return fetch(request).then((response) => {
        // Cache new static files
        if (response.ok && request.method === 'GET') {
          const responseClone = response.clone();
          caches.open(STATIC_CACHE).then((cache) => {
            cache.put(request, responseClone);
          });
        }
        return response;
      });
    })
  );
});

// Background sync for offline stamp actions (advanced feature)
self.addEventListener('sync', (event) => {
  if (event.tag === 'stamp-sync') {
    event.waitUntil(
      // Here you would implement queued stamp actions
      // For now, just log
      console.log('Background sync triggered for stamp actions')
    );
  }
});

// Push notifications (future feature)
self.addEventListener('push', (event) => {
  if (event.data) {
    const data = event.data.json();
    const options = {
      body: data.body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      vibrate: [200, 100, 200],
      actions: [
        {
          action: 'view',
          title: 'Öffnen'
        }
      ]
    };
    
    event.waitUntil(
      self.registration.showNotification(data.title, options)
    );
  }
});

// Notification click
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  
  event.waitUntil(
    clients.openWindow('/')
  );
});