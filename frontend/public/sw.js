const CACHE_NAME = 'arbeitszeit-v4';
const STATIC_CACHE = 'arbeitszeit-static-v4';

// Files to cache (excluding HTML files completely)
const STATIC_FILES = [
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

// Fetch event - NEVER cache HTML or API requests
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // NEVER cache HTML files - always go to network
  if (url.pathname === '/' || url.pathname.endsWith('.html')) {
    event.respondWith(
      fetch(request, {
        cache: 'no-cache',
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Pragma': 'no-cache'
        }
      }).catch(() => {
        // Only serve cached HTML as absolute last resort and show clear offline message
        return new Response(`
          <!DOCTYPE html>
          <html>
          <head>
            <title>Offline - Arbeitszeit Tracker</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
              body { 
                font-family: system-ui; 
                text-align: center; 
                padding: 2rem; 
                background: #f3f4f6; 
              }
              .offline { 
                background: white; 
                padding: 2rem; 
                border-radius: 1rem; 
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); 
                max-width: 400px; 
                margin: 0 auto;
              }
              .status { 
                color: #dc2626; 
                font-size: 1.125rem; 
                margin: 1rem 0; 
              }
              button { 
                background: #3b82f6; 
                color: white; 
                border: none; 
                padding: 0.75rem 1.5rem; 
                border-radius: 0.5rem; 
                cursor: pointer; 
              }
            </style>
          </head>
          <body>
            <div class="offline">
              <h1>📡 Offline</h1>
              <p class="status">Keine Internetverbindung</p>
              <p>Die Arbeitszeit-App benötigt eine Internetverbindung.</p>
              <button onclick="window.location.reload()">Erneut versuchen</button>
            </div>
          </body>
          </html>
        `, {
          headers: { 'Content-Type': 'text/html' }
        });
      })
    );
    return;
  }

  // Handle API requests (network first, no caching)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request, {
        cache: 'no-cache'
      }).catch(() => {
        // Return offline message for API requests
        if (request.method === 'POST') {
          return new Response(
            JSON.stringify({ 
              error: 'Offline - Bitte versuchen Sie es später erneut',
              detail: 'Keine Internetverbindung verfügbar'
            }), 
            {
              status: 503,
              statusText: 'Service Unavailable',
              headers: { 'Content-Type': 'application/json' }
            }
          );
        }
        
        return new Response(
          JSON.stringify({
            error: 'Offline',
            message: 'Keine Verbindung zum Server'
          }), 
          {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // Handle static files ONLY (manifest, icons)
  if (STATIC_FILES.includes(url.pathname)) {
    event.respondWith(
      caches.match(request).then((response) => {
        if (response) {
          return response;
        }
        
        return fetch(request).then((response) => {
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(STATIC_CACHE).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        });
      })
    );
    return;
  }

  // For everything else, just fetch from network
  event.respondWith(fetch(request));
});

// Message handling for cache updates
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    event.waitUntil(
      caches.keys().then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            console.log('Clearing cache:', cacheName);
            return caches.delete(cacheName);
          })
        );
      }).then(() => {
        console.log('All caches cleared');
        // Force reload all clients
        return self.clients.matchAll().then((clients) => {
          clients.forEach((client) => {
            client.postMessage({ type: 'CACHE_CLEARED' });
          });
        });
      })
    );
  }
});