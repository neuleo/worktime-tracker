// App Logic and Event Handlers

// --- ROUTER ---
const routes = ['dashboard', 'sessions', 'timeinfo', 'manual', 'flextime'];

function router() {
    const page = window.location.hash.substring(1) || 'dashboard';
    
    if (!routes.includes(page)) {
        console.warn(`Unknown route: ${page}, redirecting to dashboard.`);
        navigateTo('dashboard');
        return;
    }

    // Clear all specific page timers first to avoid conflicts
    if (timers.liveUpdate) clearInterval(timers.liveUpdate);
    if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);

    // Clear page-specific state
    if (appState.currentPage === 'timeinfo') {
        appState.plannedDepartureTime = '';
    }

    appState.currentPage = page;
    closeMenu();
    
    // Load data for specific pages and set up live updates
    if (page === 'sessions') {
        loadSessions();
    } else if (page === 'timeinfo') {
        loadTimeInfo(); // Initial load
        setupTimeInfoLiveUpdates(); // Start periodic updates
    } else if (page === 'flextime') {
        loadOvertimeData();
    } else if (page === 'dashboard') {
        // Dashboard data is loaded by init and periodic refresh, live updates are handled by setupLiveUpdates
        // Ensure live updates are running if we navigate here
        setupLiveUpdates();
    }
    
    render();
}

function navigateTo(page) {
    window.location.hash = page;
}


// --- MENU ---
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

// --- UI HANDLERS ---
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
    appState.plannedDepartureTime = plannedTime; // Store value in state

    const resultEl = document.getElementById('what-if-result');

    if (!plannedTime || plannedTime.length < 5 || !appState.dayData || !appState.dayData.bookings) {
        resultEl.innerHTML = '';
        return;
    }

    let tempBookings = JSON.parse(JSON.stringify(appState.dayData.bookings));
    tempBookings.push({ action: 'out', time: plannedTime });

    const stats = calculateDailyStatsJS(tempBookings);
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

function handleEditBookingSubmit(event) {
    event.preventDefault();
    const id = document.getElementById('edit-booking-id').value;
    const date = document.getElementById('edit-booking-date').value;
    const action = document.getElementById('edit-booking-action').value;
    const time = document.getElementById('edit-booking-time').value;

    if (!id || !date || !action || !time) {
        showNotification('Bitte alle Felder ausfüllen', 'error');
        return;
    }

    updateBooking(id, date, action, time);
}

// --- LIVE UPDATES ---
function setupLiveUpdates() {
    if (timers.liveUpdate) clearInterval(timers.liveUpdate);
    if (appState.status.status === 'in') {
        timers.liveUpdate = setInterval(updateLiveDuration, CONFIG.LIVE_UPDATE_INTERVAL);
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
        
        const durationEl = document.getElementById('live-duration');
        if (durationEl) {
            durationEl.textContent = durationStr;
        }
    }
}

function setupTimeInfoLiveUpdates() {
    if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);
    if (appState.currentPage === 'timeinfo') {
        timers.timeInfoLiveUpdate = setInterval(loadTimeInfo, CONFIG.LIVE_UPDATE_INTERVAL);
    }
}

function pauseTimeInfoUpdates() {
    if (timers.timeInfoLiveUpdate) {
        clearInterval(timers.timeInfoLiveUpdate);
        timers.timeInfoLiveUpdate = null;
        console.log('Time Info updates paused');
    }
}

function startClock() {
    if (timers.clock) clearInterval(timers.clock);
    timers.clock = setInterval(() => {
        appState.currentTime = new Date();
        const timeEl = document.querySelector('.current-time-display');
        if (timeEl) {
            timeEl.textContent = formatTime(appState.currentTime);
        }
    }, CONFIG.CLOCK_UPDATE_INTERVAL);
}

// --- RENDER ---
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
            <header class="bg-white shadow-sm border-b sticky top-0 z-10">
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
                            <span class="text-sm font-mono text-gray-600 current-time-display">${formatTime(currentTime)}</span>
                        </div>
                    </div>
                </div>
            </header>

            <main class="max-w-md mx-auto px-4 py-6">
                ${pageContent}
            </main>
        </div>
    `;
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

// --- EVENT LISTENERS ---
function setupEventListeners() {
    window.addEventListener('hashchange', router);

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

    document.addEventListener('click', (e) => {
        const overlay = document.getElementById('menu-overlay');
        if (e.target === overlay) {
            closeMenu();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeMenu();
        }
        if (e.key === ' ' && appState.currentPage === 'dashboard') {
            e.preventDefault();
            handleStamp();
        }
    });
}

// --- INITIALIZE APP ---
function init() {
    console.log('🚀 Arbeitszeit Tracker starting...');
    
    appState.isOnline = navigator.onLine;
    
    setupEventListeners();
    
    Promise.all([
        loadStatus(),
        loadTodayData(),
        loadWeekData()
    ]).then(() => {
        console.log('✅ Initial data loaded');
        router(); // Initial route handling
    }).catch((error) => {
        console.error('❌ Failed to load initial data:', error);
        showNotification('Fehler beim Laden der Daten', 'error');
        router(); // Route even if data load fails
    });
    
    startClock();
    
    console.log('✅ Arbeitszeit Tracker initialized');
}

// --- LIFECYCLE ---
window.addEventListener('beforeunload', () => {
    console.log('🧹 Cleaning up timers...');
    if (timers.liveUpdate) clearInterval(timers.liveUpdate);
    if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);
    if (timers.clock) clearInterval(timers.clock);
});

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        if (appState.isOnline) {
            console.log('📱 Page visible - refreshing data');
            loadStatus();
            router(); // Re-run router logic to refresh data for current page
        }
    } else {
        if (timers.liveUpdate) clearInterval(timers.liveUpdate);
        if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);
    }
});

// Start the app
init();