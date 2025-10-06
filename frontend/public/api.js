// API Functions
async function apiCall(url, options = {}) {
    const cacheBuster = (options.method === 'GET' || !options.method) ? getCacheBuster(url) : '';
    const fullUrl = `${CONFIG.API_BASE}${url}${cacheBuster}`;
    
    const { signal, ...restOptions } = options;

    const headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        ...restOptions.headers
    };

    const response = await fetch(fullUrl, { ...restOptions, headers, signal });

    if (response.status === 401) {
        // If we get a 401, the token is invalid or expired.
        // We should clear the session and redirect to the login page.
        console.error('Authentication error (401). Redirecting to login.');
        localStorage.removeItem('loggedInUser');
        localStorage.removeItem('activeUser');
        window.location.href = '/login.html';
        // Throw an error to prevent the calling function from processing a bad response.
        throw new Error('Unauthorized');
    }

    return response;
}

// --- User and Settings --- 
async function loadUsers(signal) {
    try {
        const response = await apiCall('/users', { signal });
        if (!response.ok) throw new Error('Failed to load users');
        appState.allUsers = await response.json();
    } catch (error) {
        console.error(error.message);
        appState.allUsers = [];
    }
}

async function loadUserSettings(signal) {
    try {
        // Settings are for the currently viewed user
        const response = await apiCall(`/settings?user=${appState.activeUser}`, { signal });
        if (!response.ok) throw new Error('Failed to load settings');
        appState.settings = await response.json();
    } catch (error) {
        console.error('Failed to load settings:', error);
        appState.settings = null;
    }
}

async function saveUserSettings(settings) {
    try {
        const response = await apiCall('/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        if (!response.ok) throw new Error('Failed to save settings');
        showNotification('Einstellungen erfolgreich gespeichert', 'success');
        await loadUserSettings(); // Refresh settings state
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

// --- Data Loading ---
async function loadStatus(signal) {
    try {
        const response = await apiCall(`/status?user=${appState.activeUser}`, { signal });
        const data = await response.json();
        appState.status = data;
    } catch (error) {
        console.error('Failed to load status:', error);
    }
}

async function loadTodayData(signal) {
    try {
        const today = new Date().toLocaleDateString('sv-SE'); // YYYY-MM-DD format
        const response = await apiCall(`/day/${today}?user=${appState.activeUser}`, { signal });
        const data = await response.json();
        appState.dayData = data;
    } catch (error) {
        console.error('Failed to load day data:', error);
    }
}

async function loadWeekData(signal) {
    try {
        const now = new Date();
        const year = now.getFullYear();
        const week = getWeekNumber(now);
        const response = await apiCall(`/week/${year}/${week}?user=${appState.activeUser}`, { signal });
        const data = await response.json();
        appState.weekData = data;
    } catch (error) {
        console.error('Failed to load week data:', error);
    }
}

async function loadSessions(signal) {
    try {
        const response = await apiCall(`/sessions?user=${appState.activeUser}&limit=500`, { signal });
        const data = await response.json();
        appState.sessions = data;
    } catch (error) {
        console.error('Failed to load sessions:', error);
    }
}

async function loadTimeInfo(signal) {
    try {
        const paolaParam = appState.paolaButtonActive ? '&paola=true' : '';
        const response = await apiCall(`/timeinfo?user=${appState.activeUser}${paolaParam}`, { signal });
        const data = await response.json();
        appState.timeInfo = data;
    } catch (error) {
        console.error('Failed to load time info:', error);
    }
}

async function loadOvertimeData(signal) {
    try {
        const response = await apiCall(`/overtime?user=${appState.activeUser}`, { signal });
        if (!response.ok) throw new Error('Failed to load overtime data');
        const data = await response.json();
        appState.overtimeData = data;
    } catch (error) {
        console.error(error.message);
        appState.overtimeData = { total_overtime_str: 'Fehler', free_days: 0 };
    }
}

async function loadAllData(signal) {
    try {
        const response = await apiCall(`/all-data?user=${appState.activeUser}`, { signal });
        if (!response.ok) throw new Error('Failed to load all data');
        const data = await response.json();
        appState.allData = data;
    } catch (error) {
        console.error(error.message);
        showNotification('Fehler beim Laden der Statistikdaten', 'error');
    }
}

async function loadStatistics(fromDate, toDate, signal) {
    try {
        const response = await apiCall(`/statistics?user=${appState.activeUser}&from_date=${fromDate}&to_date=${toDate}`, { signal });
        if (!response.ok) throw new Error('Failed to load statistics data');
        const data = await response.json();
        appState.statisticsData = data;
    } catch (error) {
        console.error(error.message);
        showNotification('Fehler beim Laden der Statistikdaten', 'error');
    }
}

// --- Actions ---
async function adjustOvertime(adjustmentData) {
    try {
        // NOTE: This action is performed by the LOGGED IN user, not the ACTIVE user.
        const response = await apiCall('/overtime', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(adjustmentData)
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to adjust overtime');
        showNotification('Gleitzeit erfolgreich angepasst', 'success');
        await loadOvertimeData(); // Refresh data
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function handleStamp() {
    if (!appState.isOnline) {
        showNotification('Keine Internetverbindung!', 'error');
        return;
    }
    if (appState.loggedInUser !== appState.activeUser) {
        showNotification('Stempeln nur für den eingeloggten Benutzer möglich.', 'error');
        return;
    }
    
    appState.isLoading = true;
    
    try {
        const response = await apiCall('/stamp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}) // User is implicit
        });
        
        if (!response.ok) throw new Error((await response.json()).detail || 'Stamp failed');
        const data = await response.json();
        
        // Use a local controller to ensure these loads can be cancelled if another stamp happens
        const loadController = new AbortController();
        const signal = loadController.signal;

        await Promise.all([loadStatus(signal), loadTodayData(signal), loadWeekData(signal)]);
        
        const action = data.status === 'in' ? 'Eingestempelt' : 'Ausgestempelt';
        const time = new Date(data.timestamp).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' });
        showNotification(`${action} um ${time}`, 'success');
        
        if ('vibrate' in navigator) {
            navigator.vibrate(data.status === 'in' ? CONFIG.VIBRATION.STAMP_IN : CONFIG.VIBRATION.STAMP_OUT);
        }
        
        setupLiveUpdates();
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    } finally {
        appState.isLoading = false;
        render();
    }
}

async function deleteSession(sessionId) {
    if (appState.loggedInUser !== appState.activeUser) {
        showNotification('Löschen nur für den eingeloggten Benutzer möglich.', 'error');
        return;
    }
    if (!confirm('Möchten Sie diese Buchung wirklich löschen?')) return;

    try {
        const response = await apiCall(`/sessions/${sessionId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete session');
        showNotification('Buchung erfolgreich gelöscht', 'success');
        await Promise.all([loadSessions(routeAbortController.signal), loadTodayData(routeAbortController.signal), loadWeekData(routeAbortController.signal)]);
    } catch (error) {
        showNotification(`Fehler beim Löschen: ${error.message}`, 'error');
    }
}

async function createManualBooking(date, action, time) {
    if (appState.loggedInUser !== appState.activeUser) {
        showNotification('Manuelle Buchung nur für den eingeloggten Benutzer möglich.', 'error');
        return;
    }
    try {
        const response = await apiCall('/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date, action, time })
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to create booking');
        showNotification('Buchung erfolgreich erstellt', 'success');
        
        document.getElementById('manual-date').value = new Date().toISOString().split('T')[0];
        document.getElementById('manual-action').value = 'in';
        document.getElementById('manual-time').value = '';
        
        await Promise.all([loadTodayData(routeAbortController.signal), loadWeekData(routeAbortController.signal), loadSessions(routeAbortController.signal)]);
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function updateBooking(id, date, action, time) {
    if (appState.loggedInUser !== appState.activeUser) {
        showNotification('Ändern nur für den eingeloggten Benutzer möglich.', 'error');
        return;
    }
    try {
        const response = await apiCall(`/sessions/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date, action, time })
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to update booking');
        showNotification('Buchung erfolgreich aktualisiert', 'success');
        await Promise.all([loadSessions(routeAbortController.signal), loadTodayData(routeAbortController.signal), loadWeekData(routeAbortController.signal)]);
        closeEditBookingModal();
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function adjustBookingTime(id, seconds) {
    if (appState.loggedInUser !== appState.activeUser) {
        showNotification('Anpassen nur für den eingeloggten Benutzer möglich.', 'error');
        return;
    }
    try {
        const response = await apiCall(`/sessions/${id}/adjust_time`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ seconds: seconds })
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to adjust time');
        showNotification('Zeit erfolgreich angepasst', 'success');
        await Promise.all([loadSessions(routeAbortController.signal), loadTodayData(routeAbortController.signal), loadWeekData(routeAbortController.signal)]);
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function changePassword(oldPassword, newPassword) {
    try {
        const response = await apiCall('/user/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to change password');
        showNotification('Passwort erfolgreich geändert', 'success');
        // Clear form
        document.getElementById('old-password').value = '';
        document.getElementById('new-password').value = '';
        document.getElementById('confirm-password').value = '';
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}
