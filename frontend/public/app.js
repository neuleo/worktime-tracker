// App Logic and Event Handlers

// Menu functions
function openMenu() {
    const overlay = document.getElementById('menu-overlay');
    overlay.classList.remove('opacity-0', 'pointer-events-none');
    overlay.classList.add('opacity-100', 'menu-open');
}

function closeMenu() {
    const overlay = document.getElementById('menu-overlay');
    overlay.classList.add('opacity-0', 'pointer-events-none');
    overlay.classList.remove('opacity-100', 'menu-open');
}

function navigateTo(page) {
    appState.currentPage = page;
    closeMenu();
    
    // Load data for specific pages
    if (page === 'sessions') {
        loadSessions();
    } else if (page === 'timeinfo') {
        loadTimeInfo();
    } else if (page === 'flextime') {
        loadOvertimeData();
    }
    
    render();
}

function setActiveTab(tab) {
    appState.activeTab = tab;
    render();
}

function handleManualSubmit(event) {
    event.preventDefault();
    const date = document.getElementById('manual-date').value;
    const action = document.getElementById('manual-action').value;
    const time = document.getElementById('manual-time').value;

    if (!date || !action || !time) {
        showNotification('Bitte alle Felder ausfüllen', 'error');
        return;
    }

    createManualBooking(date, action, time);
}

function handleOvertimeSubmit(event) {
    event.preventDefault();
    const hoursInput = document.getElementById('overtime-hours');
    if (!hoursInput || !hoursInput.value) {
        showNotification('Bitte einen Wert eingeben', 'error');
        return;
    }
    
    const hours = parseFloat(hoursInput.value.replace(',', '.'));
    if (isNaN(hours)) {
        showNotification('Ungültiger Wert. Bitte eine Zahl eingeben.', 'error');
        return;
    }

    adjustOvertime(hours);
    closeOvertimeModal();
}

function handlePlannedDepartureChange(event) {
    const plannedTime = event.target.value;
    const resultEl = document.getElementById('what-if-result');

    if (!plannedTime || !appState.dayData) {
        resultEl.innerHTML = '';
        return;
    }

    // Deep copy today's bookings to avoid modifying the state directly
    let tempBookings = JSON.parse(JSON.stringify(appState.dayData.bookings));

    // Add the planned departure as a temporary 'out' booking
    tempBookings.push({ action: 'out', time: plannedTime });

    const stats = calculateDailyStatsJS(tempBookings);

    // Display the result
    const overtimeColor = getOvertimeColor(stats.overtime);
    resultEl.innerHTML = `
        <div class="text-center mt-4 p-4 bg-gray-50 rounded-lg">
            <p class="text-sm text-gray-600">Errechnete Überstunden:</p>
            <p class="font-mono text-2xl font-bold ${overtimeColor}">${formatDuration(stats.overtime)}</p>
        </div>
    `;
}

function openOvertimeModal() {
    const modal = document.getElementById('overtime-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

function closeOvertimeModal() {
    const modal = document.getElementById('overtime-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// Live updates for timer display
function setupLiveUpdates() {
    // Clear existing timer
    if (timers.liveUpdate) clearInterval(timers.liveUpdate);
    
    // Only start live updates if user is stamped in
    if (appState.status.status === 'in') {
        timers.liveUpdate = setInterval(() => {
            updateLiveDuration();
        }, CONFIG.LIVE_UPDATE_INTERVAL);
    }
}

function updateLiveDuration() {
    if (appState.status.status === 'in' && appState.status.since) {
        const startTime = new Date(appState.status.since);
        const now = new Date();
        const durationSeconds = Math.floor((now - startTime) / 1000);
        
        const hours = Math.floor(durationSeconds / 3600);
        const minutes = Math.floor((durationSeconds % 3600) / 60);
        const seconds = durationSeconds % 60;
        const durationStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        
        // Update the duration display
        const durationEl = document.getElementById('live-duration');
        if (durationEl) {
            durationEl.textContent = durationStr;
        }
    }
}

// Update clock every second
function startClock() {
    if (timers.clock) clearInterval(timers.clock);
    timers.clock = setInterval(() => {
        appState.currentTime = new Date();
        // Only update the time display, not full render
        const timeEl = document.querySelector('.text-sm.font-mono.text-gray-600');
        if (timeEl) {
            timeEl.textContent = formatTime(appState.currentTime);
        }
    }, CONFIG.CLOCK_UPDATE_INTERVAL);
}

// Main render function
function render() {
    const { currentTime, isOnline, currentPage } = appState;
    
    const rootEl = document.getElementById('root');
    
    let pageContent = '';
    switch (currentPage) {
        case 'dashboard':
            pageContent = renderDashboard();
            break;
        case 'sessions':
            pageContent = renderSessions();
            break;
        case 'timeinfo':
            pageContent = renderTimeInfo();
            break;
        case 'manual':
            pageContent = renderManualBooking();
            break;
        case 'flextime':
            pageContent = renderFlextimePage();
            break;
        default:
            pageContent = renderDashboard();
    }
    
    rootEl.innerHTML = `
        <div class="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 status-bar-safe">
            <!-- Header -->
            <div class="bg-white shadow-sm border-b">
                <div class="max-w-md mx-auto px-4 py-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <button onclick="openMenu()" class="p-1 hover:bg-gray-100 rounded transition-colors">
                                ${createIcon('menu', 'h-6 w-6 text-gray-600')}
                            </button>
                            ${createIcon('clock', 'h-6 w-6 text-blue-600')}
                            <h1 class="text-xl font-bold text-gray-900">
                                ${getPageTitle(currentPage)}
                            </h1>
                        </div>
                        <div class="flex items-center space-x-2">
                            ${createIcon(isOnline ? 'wifi' : 'wifioff', `h-4 w-4 ${isOnline ? 'text-green-500' : 'text-red-500'}`)}
                            <span class="text-sm font-mono text-gray-600">${formatTime(currentTime)}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="max-w-md mx-auto px-4 py-6">
                ${pageContent}
            </div>
        </div>
    `;

    // Setup live updates after render if stamped in and on dashboard
    if (currentPage === 'dashboard') {
        setupLiveUpdates();
    }
}

function getPageTitle(page) {
    const titles = {
        'dashboard': 'Arbeitszeit',
        'sessions': 'Buchungen',
        'timeinfo': 'Info',
        'manual': 'Buchung',
        'flextime': 'Gleitzeit'
    };
    return titles[page] || 'Arbeitszeit';
}

// Event listeners
function setupEventListeners() {
    // Online/Offline status
    window.addEventListener('online', () => {
        appState.isOnline = true;
        showNotification('Verbindung wiederhergestellt', 'success');
        render();
    });
    
    window.addEventListener('offline', () => {
        appState.isOnline = false;
        showNotification('Offline - Keine Internetverbindung', 'error');
        render();
    });

    // Close menu when clicking outside
    document.addEventListener('click', (e) => {
        const overlay = document.getElementById('menu-overlay');
        if (e.target === overlay) {
            closeMenu();
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // ESC to close menu
        if (e.key === 'Escape') {
            closeMenu();
        }
        
        // Space to stamp (only on dashboard)
        if (e.key === ' ' && appState.currentPage === 'dashboard') {
            e.preventDefault();
            handleStamp();
        }
    });

    // Prevent pull-to-refresh on mobile
    document.addEventListener('touchstart', (e) => {
        if (e.touches.length > 1) {
            e.preventDefault();
        }
    }, { passive: false });

    let lastTouchEnd = 0;
    document.addEventListener('touchend', (e) => {
        const now = (new Date()).getTime();
        if (now - lastTouchEnd <= 300) {
            e.preventDefault();
        }
        lastTouchEnd = now;
    }, false);
}

// Initialize app
function init() {
    console.log('🚀 Arbeitszeit Tracker starting...');
    
    appState.isOnline = navigator.onLine;
    
    // Setup event listeners
    setupEventListeners();
    
    // Load initial data
    Promise.all([
        loadStatus(),
        loadTodayData(),
        loadWeekData()
    ]).then(() => {
        console.log('✅ Initial data loaded');
    }).catch((error) => {
        console.error('❌ Failed to load initial data:', error);
        showNotification('Fehler beim Laden der Daten', 'error');
    });
    
    // Initial render
    render();
    
    // Start clock
    startClock();
    
    console.log('✅ Arbeitszeit Tracker initialized');
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    console.log('🧹 Cleaning up timers...');
    if (timers.liveUpdate) clearInterval(timers.liveUpdate);
    if (timers.clock) clearInterval(timers.clock);
});

// Handle page visibility changes (for mobile browsers)
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        // Page became visible - refresh data if online
        if (appState.isOnline) {
            console.log('📱 Page visible - refreshing data');
            loadStatus();
            if (appState.currentPage === 'dashboard') {
                loadTodayData();
                loadWeekData();
            }
        }
    }
});

// Handle focus/blur for better mobile experience
window.addEventListener('focus', () => {
    if (appState.isOnline) {
        loadStatus();
    }
});

// Periodic data refresh (every 5 minutes when online and active)
setInterval(() => {
    if (appState.isOnline && !document.hidden) {
        console.log('🔄 Periodic data refresh');
        loadStatus();
        if (appState.currentPage === 'dashboard') {
            loadTodayData();
            loadWeekData();
        }
    }
}, 5 * 60 * 1000); // 5 minutes

// Start the app
init();