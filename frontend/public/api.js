// API Functions
async function apiCall(url, options = {}) {
    const cacheBuster = (options.method === 'GET' || !options.method) ? getCacheBuster(url) : '';
    const fullUrl = `${CONFIG.API_BASE}${url}${cacheBuster}`;
    
    // Use default headers for non-caching
    const headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        ...options.headers
    };

    return fetch(fullUrl, { ...options, headers });
}

// --- User and Settings --- 
async function loadUsers() {
    try {
        const response = await apiCall('/users');
        if (!response.ok) throw new Error('Failed to load users');
        appState.allUsers = await response.json();
    } catch (error) {
        console.error(error.message);
        appState.allUsers = [];
    }
}

async function loadUserSettings() {
    try {
        // Settings are for the currently viewed user
        const response = await apiCall(`/settings?user=${appState.activeUser}`);
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
async function loadStatus() {
    try {
        const response = await apiCall(`/status?user=${appState.activeUser}`);
        const data = await response.json();
        appState.status = data;
        render();
    } catch (error) {
        console.error('Failed to load status:', error);
    }
}

async function loadTodayData() {
    try {
        const today = new Date().toLocaleDateString('sv-SE'); // YYYY-MM-DD format
        const response = await apiCall(`/day/${today}?user=${appState.activeUser}`);
        const data = await response.json();
        appState.dayData = data;
        render();
    } catch (error) {
        console.error('Failed to load day data:', error);
    }
}

async function loadWeekData() {
    try {
        const now = new Date();
        const year = now.getFullYear();
        const week = getWeekNumber(now);
        const response = await apiCall(`/week/${year}/${week}?user=${appState.activeUser}`);
        const data = await response.json();
        appState.weekData = data;
        render();
    } catch (error) {
        console.error('Failed to load week data:', error);
    }
}

async function loadSessions() {
    try {
        const response = await apiCall(`/sessions?user=${appState.activeUser}&limit=500`);
        const data = await response.json();
        appState.sessions = data;
        render();
    } catch (error) {
        console.error('Failed to load sessions:', error);
    }
}

async function loadTimeInfo() {
    try {
        const paolaParam = appState.paolaButtonActive ? '&paola=true' : '';
        const response = await apiCall(`/timeinfo?user=${appState.activeUser}${paolaParam}`);
        const data = await response.json();
        appState.timeInfo = data;
        render();
    } catch (error) {
        console.error('Failed to load time info:', error);
    }
}

async function loadOvertimeData() {
    try {
        const response = await apiCall(`/overtime?user=${appState.activeUser}`);
        if (!response.ok) throw new Error('Failed to load overtime data');
        const data = await response.json();
        appState.overtimeData = data;
        render();
    } catch (error) {
        console.error(error.message);
        appState.overtimeData = { total_overtime_str: 'Fehler', free_days: 0 };
        render();
    }
}

async function loadAllData() {
    try {
        const response = await apiCall(`/all-data?user=${appState.activeUser}`);
        if (!response.ok) throw new Error('Failed to load all data');
        const data = await response.json();
        appState.allData = data;
        render(); // Re-render to show the new data
    } catch (error) {
        console.error(error.message);
        showNotification('Fehler beim Laden der Statistikdaten', 'error');
    }
}

async function loadStatistics(fromDate, toDate) {
    try {
        const response = await apiCall(`/statistics?user=${appState.activeUser}&from_date=${fromDate}&to_date=${toDate}`);
        if (!response.ok) throw new Error('Failed to load statistics data');
        const data = await response.json();
        appState.statisticsData = data;
    } catch (error) {
        console.error(error.message);
        showNotification('Fehler beim Laden der Statistikdaten', 'error');
    }
}

// --- Actions ---
async function adjustOvertime(hours) {
    try {
        // NOTE: This action is performed by the LOGGED IN user, not the ACTIVE user.
        const response = await apiCall('/overtime', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hours: hours })
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
    render();
    
    try {
        const response = await apiCall('/stamp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}) // User is implicit
        });
        
        if (!response.ok) throw new Error((await response.json()).detail || 'Stamp failed');
        const data = await response.json();
        
        await Promise.all([loadStatus(), loadTodayData(), loadWeekData()]);
        
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
        await Promise.all([loadSessions(), loadTodayData(), loadWeekData()]);
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
        
        await Promise.all([loadTodayData(), loadWeekData(), loadSessions()]);
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
        await Promise.all([loadSessions(), loadTodayData(), loadWeekData()]);
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
        await Promise.all([loadSessions(), loadTodayData(), loadWeekData()]);
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
