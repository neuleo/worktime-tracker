// API Functions
async function apiCall(url, options = {}) {
    const cacheBuster = options.method === 'GET' ? getCacheBuster() : '';
    const fullUrl = `${CONFIG.API_BASE}${url}${cacheBuster}`;
    
    return fetch(fullUrl, {
        ...options,
        headers: {
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            ...options.headers
        }
    });
}

async function loadStatus() {
    try {
        const response = await apiCall(`/status?user=${CONFIG.USER}`);
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
        const response = await apiCall(`/day/${today}?user=${CONFIG.USER}`);
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
        const response = await apiCall(`/week/${year}/${week}?user=${CONFIG.USER}`);
        const data = await response.json();
        appState.weekData = data;
        render();
    } catch (error) {
        console.error('Failed to load week data:', error);
    }
}

async function loadSessions() {
    try {
        const response = await apiCall(`/sessions?user=${CONFIG.USER}&limit=500`);
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
        const response = await apiCall(`/timeinfo?user=${CONFIG.USER}${paolaParam}`);
        const data = await response.json();
        console.log('Data received for Time-Info page:', data);
        appState.timeInfo = data;
        render();
    } catch (error) {
        console.error('Failed to load time info:', error);
    }
}

async function loadOvertimeData() {
    try {
        const response = await apiCall(`/overtime?user=${CONFIG.USER}`);
        if (!response.ok) {
            throw new Error('Failed to load overtime data');
        }
        const data = await response.json();
        appState.overtimeData = data;
        render();
    } catch (error) {
        console.error(error.message);
        appState.overtimeData = { total_overtime_str: 'Fehler', free_days: 0 };
        render();
    }
}

async function adjustOvertime(hours) {
    try {
        const response = await apiCall('/overtime', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user: CONFIG.USER,
                hours: hours
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to adjust overtime');
        }

        showNotification('Gleitzeit erfolgreich angepasst', 'success');
        await loadOvertimeData(); // Refresh data

    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function handleStamp() {
    if (!appState.isOnline) {
        showNotification('Keine Internetverbindung! Bitte versuche es später erneut.', 'error');
        return;
    }
    
    appState.isLoading = true;
    render();
    
    try {
        const response = await apiCall('/stamp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user: CONFIG.USER })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Stamp failed');
        }
        
        const data = await response.json();
        
        // Refresh all data
        await Promise.all([
            loadStatus(),
            loadTodayData(),
            loadWeekData()
        ]);
        
        const action = data.status === 'in' ? 'Eingestempelt' : 'Ausgestempelt';
        const time = new Date(data.timestamp).toLocaleTimeString('de-DE', {
            hour: '2-digit',
            minute: '2-digit',
            timeZone: 'Europe/Berlin'
        });
        
        showNotification(`${action} um ${time}`, 'success');
        
        if ('vibrate' in navigator) {
            const vibration = data.status === 'in' ? CONFIG.VIBRATION.STAMP_IN : CONFIG.VIBRATION.STAMP_OUT;
            navigator.vibrate(vibration);
        }
        
        // Start/stop live updates
        setupLiveUpdates();
        
    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    } finally {
        appState.isLoading = false;
        render();
    }
}

async function deleteSession(sessionId) {
    if (!confirm('Möchten Sie diese Buchung wirklich löschen?')) {
        return;
    }

    try {
        const response = await apiCall(`/sessions/${sessionId}?user=${CONFIG.USER}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Failed to delete session');
        }

        showNotification('Buchung erfolgreich gelöscht', 'success');
        await loadSessions();
        await loadTodayData();
        await loadWeekData();

    } catch (error) {
        showNotification(`Fehler beim Löschen: ${error.message}`, 'error');
    }
}

async function createManualBooking(date, action, time) {
    try {
        const response = await apiCall('/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user: CONFIG.USER,
                date: date,
                action: action,
                time: time
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create booking');
        }

        showNotification('Buchung erfolgreich erstellt', 'success');
        
        // Clear form
        document.getElementById('manual-date').value = new Date().toISOString().split('T')[0];
        document.getElementById('manual-action').value = 'in';
        document.getElementById('manual-time').value = '';
        
        // Refresh data
        await Promise.all([
            loadTodayData(),
            loadWeekData(),
            loadSessions()
        ]);

    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function updateBooking(id, date, action, time) {
    try {
        const response = await apiCall(`/sessions/${id}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user: CONFIG.USER,
                    date: date,
                    action: action,
                    time: time
                })
            });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update booking');
        }

        showNotification('Buchung erfolgreich aktualisiert', 'success');
        await loadSessions();
        await loadTodayData();
        await loadWeekData();
        closeEditBookingModal();

    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}

async function adjustBookingTime(id, seconds) {
    try {
        const response = await apiCall(`/sessions/${id}/adjust_time`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user: CONFIG.USER,
                seconds: seconds
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to adjust time');
        }

        showNotification('Zeit erfolgreich angepasst', 'success');
        await loadSessions();
        await loadTodayData();
        await loadWeekData();

    } catch (error) {
        showNotification(`Fehler: ${error.message}`, 'error');
    }
}
