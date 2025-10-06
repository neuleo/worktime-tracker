// App Logic and Event Handlers

let routeAbortController = new AbortController();

// --- ROUTER ---
const routes = ['dashboard', 'sessions', 'timeinfo', 'manual', 'flextime', 'stats', 'settings'];

async function router() {
    // Abort any ongoing API calls from the previous route
    routeAbortController.abort();
    routeAbortController = new AbortController();
    const signal = routeAbortController.signal;

    const page = window.location.hash.substring(1) || 'dashboard';
    
    if (!routes.includes(page)) {
        console.warn(`Unknown route: ${page}, redirecting to dashboard.`);
        navigateTo('dashboard');
        return;
    }

    // Clear all specific page timers first to avoid conflicts
    if (timers.liveUpdate) clearInterval(timers.liveUpdate);
    if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);

    appState.currentPage = page;
    closeMenu();
    
    // Load data for specific pages and set up live updates
    if (page === 'sessions') {
        await Promise.all([loadSessions(signal), loadUserSettings(signal)]);
    } else if (page === 'timeinfo') {
        await Promise.all([loadTimeInfo(signal), loadUserSettings(signal)]); // Load settings as well
        setupTimeInfoLiveUpdates(); // Start periodic updates
    } else if (page === 'flextime') {
        await loadOvertimeData(signal);
    } else if (page === 'stats') {
        // Data is loaded by renderCharts in statistics.js, which needs the signal
    } else if (page === 'settings') {
        await loadUserSettings(signal);
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

async function switchActiveUser(username) {
    console.log(`Switching active user to: ${username}`);
    appState.activeUser = username;
    localStorage.setItem('activeUser', username);

    // Abort previous calls and get a new signal for the new user's data
    routeAbortController.abort();
    routeAbortController = new AbortController();
    const signal = routeAbortController.signal;

    // Reload all data for the new user
    await Promise.all([
        loadStatus(signal),
        loadTodayData(signal),
        loadWeekData(signal),
        loadUserSettings(signal)
    ]);

    // Re-route to the current page to force a full re-render with new data
    router();
}


// --- MENU ---
function openMenu() {
    const overlay = document.getElementById('menu-overlay');
    overlay.classList.remove('opacity-0', 'pointer-events-none');
    overlay.classList.add('opacity-100', 'menu-open');
}

function closeMenu() {
    const overlay = document.getElementById('menu-overlay');
    if (overlay) {
        overlay.classList.add('opacity-0', 'pointer-events-none');
        overlay.classList.remove('opacity-100', 'menu-open');
    }
}

// --- UI HANDLERS ---
function togglePaolaButton() {
    appState.paolaButtonActive = !appState.paolaButtonActive;
    render(); // Re-render the UI immediately with the new paola state
    loadTimeInfo(); // Fetch updated data from the backend
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

function switchOvertimeInputMode(mode) {
    appState.overtimeInputMode = mode;
    const container = document.getElementById('overtime-input-container');
    const decimalBtn = document.getElementById('ot-mode-decimal');
    const timeBtn = document.getElementById('ot-mode-time');

    if (mode === 'decimal') {
        container.innerHTML = `
            <input 
                type="number" 
                step="0.01" 
                id="overtime-hours-decimal" 
                placeholder="z.B. 6.8 oder -2.5"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono"
            >
        `;
        decimalBtn.classList.add('bg-blue-500', 'text-white');
        decimalBtn.classList.remove('bg-white', 'text-gray-700');
        timeBtn.classList.add('bg-white', 'text-gray-700');
        timeBtn.classList.remove('bg-blue-500', 'text-white');
    } else {
        container.innerHTML = `
            <input 
                type="time" 
                id="overtime-hours-time" 
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono"
            >
        `;
        timeBtn.classList.add('bg-blue-500', 'text-white');
        timeBtn.classList.remove('bg-white', 'text-gray-700');
        decimalBtn.classList.add('bg-white', 'text-gray-700');
        decimalBtn.classList.remove('bg-blue-500', 'text-white');
    }
}

function handleOvertimeSubmit(event) {
    event.preventDefault();
    
    let hours;
    if (appState.overtimeInputMode === 'decimal') {
        const decimalInput = document.getElementById('overtime-hours-decimal');
        if (!decimalInput || !decimalInput.value) {
            showNotification('Bitte einen Wert eingeben', 'error');
            return;
        }
        hours = parseFloat(decimalInput.value.replace(',', '.'));
    } else {
        const timeInput = document.getElementById('overtime-hours-time');
        if (!timeInput || !timeInput.value) {
            showNotification('Bitte eine Zeit eingeben', 'error');
            return;
        }
        const [h, m] = timeInput.value.split(':').map(Number);
        hours = h + (m / 60);
    }

    if (isNaN(hours)) {
        showNotification('Ungültiger Wert. Bitte eine Zahl oder Zeit eingeben.', 'error');
        return;
    }

    const dateInput = document.getElementById('overtime-date');
    const adjustmentData = {
        hours: hours,
        date: dateInput.value || null
    };

    adjustOvertime(adjustmentData);
    closeOvertimeModal();
}

function handleSettingsSubmit(event) {
    event.preventDefault();
    const targetHours = document.getElementById('setting-target-hours').value;
    const startTime = document.getElementById('setting-start-time').value;
    const endTime = document.getElementById('setting-end-time').value;
    const shortBreakLogic = document.getElementById('setting-short-break-logic').checked;
    const paolaPause = document.getElementById('setting-paola-pause').checked;
    const timeOffset = parseInt(document.getElementById('setting-time-offset').value, 10) || 0;

    const [h, m] = targetHours.split(':').map(Number);
    const targetSeconds = h * 3600 + m * 60;

    const newSettings = {
        target_work_seconds: targetSeconds,
        work_start_time_str: startTime,
        work_end_time_str: endTime,
        short_break_logic_enabled: shortBreakLogic,
        paola_pause_enabled: paolaPause,
        time_offset_seconds: timeOffset
    };

    saveUserSettings(newSettings);
}

function handlePlannedDepartureChange(event) {
    const plannedTime = event.target.value;
    appState.plannedDepartureTime = plannedTime; // Store value in state

    const resultEl = document.getElementById('what-if-result');

    if (!plannedTime || plannedTime.length < 5 || !appState.dayData || !appState.dayData.bookings || appState.dayData.bookings.length === 0) {
        resultEl.innerHTML = '';
        return;
    }

    let tempBookings = JSON.parse(JSON.stringify(appState.dayData.bookings));
    const todayDate = appState.dayData.date; // "YYYY-MM-DD"
    const plannedTimestampIso = `${todayDate}T${plannedTime}:00`;
    tempBookings.push({ action: 'out', time: plannedTime, timestamp_iso: plannedTimestampIso });

    const options = {
        paola: appState.paolaButtonActive,
        short_break_logic: appState.settings.short_break_logic_enabled,
        work_start_time_str: appState.settings.work_start_time_str,
        work_end_time_str: appState.settings.work_end_time_str
    };
    const stats = calculateDailyStatsJS(tempBookings, appState.settings.target_work_seconds, options);
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
        const dateInput = document.getElementById('overtime-date');
        if(dateInput) {
            dateInput.value = new Date().toISOString().split('T')[0];
        }
        modal.classList.remove('hidden');
        switchOvertimeInputMode('decimal'); // Default to decimal mode
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

function handlePasswordChangeSubmit(event) {
    event.preventDefault();
    const oldPassword = document.getElementById('old-password').value;
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;

    if (newPassword !== confirmPassword) {
        showNotification('Die neuen Passwörter stimmen nicht überein.', 'error');
        return;
    }
    if (!newPassword) {
        showNotification('Das neue Passwort darf nicht leer sein.', 'error');
        return;
    }

    changePassword(oldPassword, newPassword);
}

function handleSyncTime() {
    const offsetInput = document.getElementById('setting-time-offset');
    const targetSeconds = parseInt(offsetInput.value, 10);

    if (isNaN(targetSeconds) || targetSeconds < 0 || targetSeconds > 59) {
        showNotification('Bitte eine Sekunde zwischen 0 und 59 eingeben', 'error');
        return;
    }

    const now = new Date();
    const currentSeconds = now.getSeconds();
    
    // Calculate the difference
    let offset = targetSeconds - currentSeconds;

    // Update the input field with the new offset
    offsetInput.value = offset;

    // Trigger the form submission to save all settings
    handleSettingsSubmit(new Event('submit'));
    showNotification(`Zeit-Offset auf ${offset}s gesetzt und gespeichert`, 'success');
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
        const offset = appState.settings?.time_offset_seconds || 0;
        appState.currentTime = new Date(new Date().getTime() + offset * 1000);
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
        case 'stats':
            pageContent = renderStatisticsPage();
            break;
        case 'settings':
            pageContent = renderSettingsPage();
            break;
        default:
            pageContent = renderDashboard();
    }
    
    rootEl.innerHTML = `
        <div class="lg:flex">
            <!-- Static Sidebar for large screens -->
            <div class="hidden lg:block lg:w-80 lg:flex-shrink-0">
                ${renderDesktopMenu()} 
            </div>

            <div class="flex-1 min-w-0">
                <div class="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 status-bar-safe">
                    <header class="bg-white shadow-sm border-b sticky top-0 z-10">
                        <div class="max-w-md lg:max-w-4xl mx-auto px-4 py-4">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center space-x-3">
                                    <button onclick="openMenu()" class="lg:hidden p-1 hover:bg-gray-100 rounded transition-colors">
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

                    <main class="max-w-md lg:max-w-4xl mx-auto px-4 py-6">
                        ${pageContent}
                    </main>
                </div>
            </div>
        </div>
    `;

    // Render dynamic parts after main render
    if (currentPage === 'stats') {
        setupStatisticsEventListeners();
        setTimeout(renderCharts, 0); // Use setTimeout to ensure DOM is updated
    }
    
    // The user switcher is rendered in two places, so we need to populate both.
    const desktopUserSwitcher = document.getElementById('desktop-user-switcher');
    if (desktopUserSwitcher) {
        desktopUserSwitcher.innerHTML = renderUserSwitcher();
    }
    const mobileUserSwitcher = document.getElementById('mobile-user-switcher');
    if (mobileUserSwitcher) {
        mobileUserSwitcher.innerHTML = renderUserSwitcher();
    }
}

function getPageTitle(page) {
    const titles = {
        'dashboard': 'Arbeitszeit',
        'sessions': 'Buchungen',
        'timeinfo': 'Info',
        'manual': 'Buchung',
        'flextime': 'Gleitzeit',
        'stats': 'Statistik',
        'settings': 'Einstellungen'
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
        if (e.key === ' ' && appState.currentPage === 'dashboard' && appState.loggedInUser === appState.activeUser) {
            e.preventDefault();
            handleStamp();
        }
    });

    window.addEventListener('unhandledrejection', (event) => {
        console.error('Unhandled rejection:', event.reason);
        // Avoid showing a notification for AbortError, which is expected
        if (event.reason && event.reason.name !== 'AbortError') {
            showNotification('Ein unerwarteter Fehler ist aufgetreten', 'error');
        }
    });
}

// --- INITIALIZE APP ---
async function init() {
    console.log('🚀 Arbeitszeit Tracker starting...');
    
    // One-time render of the mobile menu into its own root
    document.getElementById('menu-root').innerHTML = renderMobileMenu();

    appState.isOnline = navigator.onLine;
    
    setupEventListeners();

    // Check if user is logged in
    if (!appState.loggedInUser) {
        window.location.href = '/login.html';
        return;
    }

    // Set active user if not set
    if (!appState.activeUser) {
        appState.activeUser = appState.loggedInUser;
        localStorage.setItem('activeUser', appState.activeUser);
    }
    
    const signal = routeAbortController.signal;
    
    // Load initial data
    await loadUsers(signal); // Load all users for the switcher
    
    Promise.all([
        loadStatus(signal),
        loadTodayData(signal),
        loadWeekData(signal),
        loadUserSettings(signal)
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
            // Reload data for the current active user
            Promise.all([
                loadStatus(),
                loadTodayData(),
                loadWeekData()
            ]).then(() => router());
        }
    } else {
        if (timers.liveUpdate) clearInterval(timers.liveUpdate);
        if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);
    }
});

// Start the app
init();