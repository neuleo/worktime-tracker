// UI Components and Render Functions

function renderDashboard() {
    const { status, dayData, weekData, isLoading, currentTime, isOnline, activeTab } = appState;
    
    return `
        <div class="space-y-6">
            <!-- Status Card -->
            <div class="bg-white rounded-xl shadow-sm border p-6">
                <div class="text-center space-y-4">
                    <div class="inline-flex items-center px-4 py-2 rounded-full ${
                        status.status === 'in' 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-gray-100 text-gray-800'
                    }">
                        ${createIcon(status.status === 'in' ? 'play' : 'square', 'h-4 w-4 mr-2')}
                        ${status.status === 'in' ? 'Eingestempelt' : 'Ausgestempelt'}
                    </div>

                    ${status.status === 'in' && status.since ? `
                        <div class="text-sm text-gray-600">
                            <div>Seit: ${new Date(status.since).toLocaleTimeString('de-DE', {
                                hour: '2-digit',
                                minute: '2-digit',
                                timeZone: 'Europe/Berlin'
                            })}</div>
                            <div id="live-duration" class="font-mono text-lg mt-1">${status.duration || '00:00:00'}</div>
                        </div>
                    ` : ''}

                    <button 
                        onclick="handleStamp()" 
                        ${isLoading || !isOnline ? 'disabled' : ''}
                        class="w-full py-4 px-6 rounded-xl font-semibold text-lg transition-all ${
                            status.status === 'in'
                                ? 'bg-red-500 hover:bg-red-600 text-white shadow-lg hover:shadow-xl'
                                : 'bg-blue-500 hover:bg-blue-600 text-white shadow-lg hover:shadow-xl'
                        } ${isLoading || !isOnline ? 'opacity-50 cursor-not-allowed' : ''}"
                    >
                        ${isLoading ? '...' : status.status === 'in' ? 'Ausstempeln' : 'Einstempeln'}
                    </button>

                    ${!isOnline ? '<p class="text-sm text-red-500">Offline - Keine Verbindung</p>' : ''}
                </div>
            </div>

            <!-- Tabs -->
            <div class="bg-white rounded-xl shadow-sm border overflow-hidden">
                <div class="flex">
                    <button
                        onclick="setActiveTab('today')"
                        class="flex-1 py-3 px-4 text-sm font-medium transition-colors ${
                            activeTab === 'today'
                                ? 'bg-blue-50 text-blue-600 border-b-2 border-blue-600'
                                : 'text-gray-500 hover:text-gray-700'
                        }"
                    >
                        ${createIcon('calendar', 'h-4 w-4 inline mr-2')}
                        Heute
                    </button>
                    <button
                        onclick="setActiveTab('week')"
                        class="flex-1 py-3 px-4 text-sm font-medium transition-colors ${
                            activeTab === 'week'
                                ? 'bg-blue-50 text-blue-600 border-b-2 border-blue-600'
                                : 'text-gray-500 hover:text-gray-700'
                        }"
                    >
                        ${createIcon('trending', 'h-4 w-4 inline mr-2')}
                        Woche
                    </button>
                </div>

                <!-- Tab Content -->
                <div class="p-6">
                    ${activeTab === 'today' && dayData ? renderTodayTab(dayData) : ''}
                    ${activeTab === 'week' && weekData ? renderWeekTab(weekData) : ''}
                    ${(!dayData && activeTab === 'today') || (!weekData && activeTab === 'week') ? renderLoadingState() : ''}
                </div>
            </div>

            <!-- PWA Install Hint -->
            ${renderPWAHint()}
        </div>
    `;
}

function renderTodayTab(dayData) {
    return `
        <div class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
                <div class="text-center">
                    <div class="text-2xl font-bold text-gray-900 font-mono">
                        ${dayData.start || '--:--'}
                    </div>
                    <div class="text-sm text-gray-500">Start</div>
                </div>
                <div class="text-center">
                    <div class="text-2xl font-bold text-gray-900 font-mono">
                        ${dayData.end || '--:--'}
                    </div>
                    <div class="text-sm text-gray-500">Ende</div>
                </div>
            </div>

            <div class="border-t pt-4 space-y-3">
                <div class="flex justify-between items-center">
                    <span class="text-gray-600">Pause:</span>
                    <span class="font-mono text-orange-600">${dayData.pause}</span>
                </div>
                <div class="flex justify-between items-center">
                    <span class="text-gray-600">Gearbeitet:</span>
                    <span class="font-mono text-blue-600">${dayData.worked}</span>
                </div>
                <div class="flex justify-between items-center">
                    <span class="text-gray-600">Soll:</span>
                    <span class="font-mono text-gray-600">${dayData.target}</span>
                </div>
                <div class="flex justify-between items-center pt-2 border-t">
                    <span class="font-medium text-gray-700">Überstunden:</span>
                    <span class="font-mono font-bold ${getOvertimeColor(dayData.overtime)}">
                        ${formatDuration(dayData.overtime)}
                    </span>
                </div>
            </div>

            <!-- Today's Bookings -->
            ${dayData.bookings && dayData.bookings.length > 0 ? `
                <div class="border-t pt-4">
                    <h4 class="font-medium text-gray-700 mb-3">Heutige Buchungen:</h4>
                    <div class="space-y-2">
                        ${dayData.bookings.map(booking => `
                            <div class="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg">
                                <div class="flex items-center space-x-3">
                                    <div class="w-2 h-2 rounded-full ${booking.action === 'in' ? 'bg-green-500' : 'bg-red-500'}"></div>
                                    <span class="text-sm font-medium">
                                        ${booking.action === 'in' ? 'Gekommen' : 'Gegangen'}
                                    </span>
                                    <span class="font-mono text-sm">${booking.time}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
        </div>
    `;
}

function renderWeekTab(weekData) {
    return `
        <div class="space-y-4">
            <div class="text-center mb-4">
                <div class="text-lg font-semibold text-gray-900">${weekData.week}</div>
            </div>

            <div class="space-y-3">
                <div class="flex justify-between items-center">
                    <span class="text-gray-600">Gearbeitet:</span>
                    <span class="font-mono text-blue-600">${weekData.worked_total}</span>
                </div>
                <div class="flex justify-between items-center">
                    <span class="text-gray-600">Soll:</span>
                    <span class="font-mono text-gray-600">${weekData.target_total}</span>
                </div>
                <div class="flex justify-between items-center pt-2 border-t">
                    <span class="font-medium text-gray-700">Überstunden:</span>
                    <span class="font-mono font-bold ${getOvertimeColor(weekData.overtime_total)}">
                        ${formatDuration(weekData.overtime_total)}
                    </span>
                </div>
            </div>
        </div>
    `;
}

function renderLoadingState() {
    return `
        <div class="text-center text-gray-500 py-8">
            <div class="loading-spinner w-6 h-6 border-2 border-gray-200 border-t-blue-600 rounded-full mx-auto mb-2"></div>
            Lade Daten...
        </div>
    `;
}

function renderPWAHint() {
    return `
        <div class="bg-blue-50 border border-blue-200 rounded-xl p-4">
            <div class="flex items-start space-x-3">
                <svg class="h-5 w-5 text-blue-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a1 1 0 001-1V4a1 1 0 00-1-1H8a1 1 0 00-1 1v16a1 1 0 001 1z"></path>
                </svg>
                <div class="text-sm">
                    <div class="font-medium text-blue-900 mb-1">App installieren</div>
                    <div class="text-blue-700">
                        Über das Browser-Menü → "Zum Startbildschirm hinzufügen" 
                        für schnellen Zugriff
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderSessions() {
    const { sessions } = appState;
    const groupedSessions = groupSessionsByDate(sessions);
    const sortedDates = Object.keys(groupedSessions).sort().reverse();

    return `
        <div class="space-y-6">
            <div class="bg-white rounded-xl shadow-sm border">
                <div class="p-6 border-b">
                    <h2 class="text-lg font-bold text-gray-900">Alle Buchungen</h2>
                    <p class="text-sm text-gray-600 mt-1">Übersicht aller Buchungen</p>
                </div>
                
                <div class="max-h-96 overflow-y-auto scrollbar-hide">
                    ${sortedDates.length === 0 ? renderEmptySessionsState() : sortedDates.map(renderBookingsByDate).join('')}
                </div>
            </div>
        </div>
    `;
}

function renderEmptySessionsState() {
    return `
        <div class="p-6 text-center text-gray-500">
            <div class="text-lg mb-2">Keine Buchungen gefunden</div>
            <div class="text-sm">Stempel dich ein, um Buchungen zu erstellen</div>
        </div>
    `;
}

function renderBookingsByDate(date) {
    const { sessions } = appState;
    const groupedSessions = groupSessionsByDate(sessions);
    const dayBookings = groupedSessions[date];
    const dateObj = new Date(date + 'T12:00:00');
    const formattedDate = dateObj.toLocaleDateString('de-DE', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });

    // Calculate daily overtime for this date
    const dayOvertimeData = calculateDayOvertimeFromBookings(dayBookings);
    
    return `
        <div class="border-b last:border-b-0">
            <div class="p-4 bg-gray-50 flex justify-between items-center">
                <h3 class="font-semibold text-gray-900">${formattedDate}</h3>
                <div class="text-sm">
                    <span class="text-gray-600">Überstunden: </span>
                    <span class="font-mono ${getOvertimeColor(dayOvertimeData.overtime)}">
                        ${formatDuration(dayOvertimeData.overtime)}
                    </span>
                </div>
            </div>
            <div class="divide-y">
                ${dayBookings.map(renderBookingItem).join('')}
            </div>
        </div>
    `;
}

function renderBookingItem(booking) {
    const actionText = booking.action === 'in' ? 'Gekommen' : 'Gegangen';
    const actionColor = booking.action === 'in' ? 'text-green-600' : 'text-red-600';
    const dotColor = booking.action === 'in' ? 'bg-green-500' : 'bg-red-500';
    
    return `
        <div class="p-4 hover:bg-gray-50 transition-colors">
            <div class="flex justify-between items-center">
                <div class="flex items-center space-x-3">
                    <div class="w-3 h-3 rounded-full ${dotColor}"></div>
                    <div class="space-y-1">
                        <div class="flex items-center space-x-3">
                            <span class="font-medium ${actionColor}">${actionText}</span>
                            <span class="font-mono text-lg font-bold">${booking.time}</span>
                        </div>
                    </div>
                </div>
                <button 
                    onclick="deleteSession(${booking.id})"
                    class="p-2 text-red-500 hover:bg-red-50 rounded transition-colors"
                    title="Buchung löschen"
                >
                    ${createIcon('trash', 'h-4 w-4')}
                </button>
            </div>
        </div>
    `;
}

function renderTimeInfo() {
    const { timeInfo } = appState;
    
    if (!timeInfo) {
        return renderLoadingState();
    }

    return `
        <div class="space-y-6">
            <div class="bg-white rounded-xl shadow-sm border">
                <div class="p-6 border-b">
                    <h2 class="text-lg font-bold text-gray-900">Arbeitszeit-Info</h2>
                    <p class="text-sm text-gray-600 mt-1">Aktuelle Zeit: ${timeInfo.current_time}</p>
                </div>
                
                <div class="p-6 space-y-4">
                    ${renderTimeInfoStats(timeInfo)}
                    
                    <div class="space-y-4 pt-4 border-t">
                        ${timeInfo.estimated_end_time ? renderEstimatedEndTime(timeInfo.estimated_end_time) : ''}
                        
                        <div>
                            <label for="planned-departure" class="block text-sm font-medium text-gray-700 mb-2">
                                Geplantes Arbeitsende für heute
                            </label>
                            <input 
                                type="time" 
                                id="planned-departure" 
                                onchange="handlePlannedDepartureChange(event)"
                                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                            >
                            <div id="what-if-result"></div>
                        </div>
                    </div>

                    ${renderTimeInfoMilestones(timeInfo)}
                    ${renderPauseRulesInfo()}
                </div>
            </div>
        </div>
    `;
}

function renderTimeInfoStats(timeInfo) {
    return `
        <div class="grid grid-cols-2 gap-4 mb-6">
            <div class="text-center p-4 bg-blue-50 rounded-lg">
                <div class="text-2xl font-bold text-blue-600 font-mono">${timeInfo.time_worked_today}</div>
                <div class="text-sm text-gray-600">Heute gearbeitet</div>
            </div>
            <div class="text-center p-4 bg-orange-50 rounded-lg">
                <div class="text-2xl font-bold text-orange-600 font-mono">${timeInfo.time_remaining}</div>
                <div class="text-sm text-gray-600">Noch zu arbeiten</div>
            </div>
        </div>
    `;
}

function renderEstimatedEndTime(estimatedEndTime) {
    return `
        <div class="bg-green-50 border border-green-200 rounded-lg p-4">
            <div class="flex items-center space-x-2 mb-2">
                <svg class="h-5 w-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <span class="font-medium text-green-900">Voraussichtliches Ende</span>
            </div>
            <div class="text-2xl font-bold text-green-700 font-mono">${estimatedEndTime}</div>
            <div class="text-sm text-green-600 mt-1">Um 7h48min zu erreichen</div>
        </div>
    `;
}

function renderTimeInfoMilestones(timeInfo) {
    return `
        <div class="space-y-3">
            <h3 class="font-semibold text-gray-900">Anwesenheitszeit erreicht um:</h3>
            
            ${renderMilestone('6 Stunden Anwesenheit', timeInfo.time_to_6h, 'yellow')}
            ${renderMilestone('9 Stunden Anwesenheit', timeInfo.time_to_9h, 'orange')}
            ${renderMilestone('10 Stunden Maximum', timeInfo.time_to_10h, 'red')}
        </div>
    `;
}

function renderMilestone(label, time, color) {
    const bgColor = time ? `bg-${color}-50` : 'bg-gray-50';
    const textColor = time ? `text-${color}-700` : 'text-gray-500';
    const displayTime = time || 'Bereits erreicht';
    
    return `
        <div class="flex justify-between items-center p-3 ${bgColor} rounded-lg">
            <span class="text-gray-700">${label}:</span>
            <span class="font-mono font-bold ${textColor}">${displayTime}</span>
        </div>
    `;
}

function renderPauseRulesInfo() {
    return `
        <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mt-6">
            <h4 class="font-medium text-blue-900 mb-2">Pausenregeln:</h4>
            <ul class="text-sm text-blue-800 space-y-1">
                <li>• Bis 6h: Keine Pause erforderlich</li>
                <li>• 6h bis 9h: Mindestens 30min Pause</li>
                <li>• Über 9h: Mindestens 45min Pause</li>
            </ul>
        </div>
    `;
}

function renderManualBooking() {
    const today = new Date().toISOString().split('T')[0];
    
    return `
        <div class="space-y-6">
            <div class="bg-white rounded-xl shadow-sm border">
                <div class="p-6 border-b">
                    <h2 class="text-lg font-bold text-gray-900">Manuelle Buchung</h2>
                    <p class="text-sm text-gray-600 mt-1">Einzelne Buchung nachträglich eintragen</p>
                </div>
                
                ${renderManualBookingForm(today)}
            </div>

            ${renderManualBookingInfo()}
        </div>
    `;
}

function renderManualBookingForm(today) {
    return `
        <form onsubmit="handleManualSubmit(event)" class="p-6 space-y-4">
            <div>
                <label for="manual-date" class="block text-sm font-medium text-gray-700 mb-2">
                    Datum
                </label>
                <input 
                    type="date" 
                    id="manual-date" 
                    value="${today}"
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    max="${today}"
                >
            </div>

            <div>
                <label for="manual-action" class="block text-sm font-medium text-gray-700 mb-2">
                    Buchungstyp
                </label>
                <select 
                    id="manual-action" 
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                    <option value="in">Kommen (Einstempeln)</option>
                    <option value="out">Gehen (Ausstempeln)</option>
                </select>
            </div>

            <div>
                <label for="manual-time" class="block text-sm font-medium text-gray-700 mb-2">
                    Uhrzeit
                </label>
                <input 
                    type="time" 
                    id="manual-time" 
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
            </div>

            <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <div class="flex items-start space-x-2">
                    <svg class="h-5 w-5 text-yellow-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.728-.833-2.498 0L4.316 16.5c-.77.833.192 2.5 1.732 2.5z"></path>
                    </svg>
                    <div class="text-sm">
                        <div class="font-medium text-yellow-900 mb-1">Hinweis</div>
                        <div class="text-yellow-800">
                            Einzelne Buchung für Kommen oder Gehen. 
                            Pausen werden automatisch nach den gesetzlichen Regelungen berechnet.
                        </div>
                    </div>
                </div>
            </div>

            <button 
                type="submit"
                class="w-full py-3 px-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-lg transition-colors"
            >
                Buchung erstellen
            </button>
        </form>
    `;
}

function renderManualBookingInfo() {
    return `
        <div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h4 class="font-medium text-blue-900 mb-2">Automatische Pausenberechnung:</h4>
            <ul class="text-sm text-blue-800 space-y-1">
                <li>• Bis 6h Anwesenheit: Keine Pause</li>
                <li>• 6h bis 9h Anwesenheit: 30min Pause</li>
                <li>• Über 9h Anwesenheit: 45min Pause</li>
                <li>• Zielarbeitszeit: 7h 48min pro Tag</li>
                <li>• Maximum: 10h Anwesenheit pro Tag</li>
            </ul>
        </div>
    `;
}

function renderFlextimePage() {
    const { overtimeData } = appState;

    if (!overtimeData) {
        return renderLoadingState();
    }

    const overtimeColor = getOvertimeColor(overtimeData.total_overtime_str);

    return `
        <div class="space-y-6">
            <!-- Overtime Status -->
            <div class="bg-white rounded-xl shadow-sm border p-6 relative">
                <div class="flex justify-between items-start">
                    <h2 class="text-lg font-bold text-gray-900 mb-4">Gleitzeit-Übersicht</h2>
                    <button onclick="openOvertimeModal()" class="p-2 text-gray-500 hover:bg-gray-100 rounded-full">
                        ${createIcon('settings', 'h-5 w-5')}
                    </button>
                </div>
                <div class="text-center space-y-4">
                    <div>
                        <div class="text-4xl font-bold ${overtimeColor} font-mono">${formatDuration(overtimeData.total_overtime_str)}</div>
                        <div class="text-sm text-gray-500">Stunden</div>
                    </div>
                    <div>
                        <div class="text-2xl font-bold text-blue-600">${overtimeData.free_days}</div>
                        <div class="text-sm text-gray-500">Tage (à 7.8h)</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Modal for adjustment -->
        <div id="overtime-modal" class="fixed inset-0 bg-black bg-opacity-60 z-50 hidden items-center justify-center p-4">
            <div class="bg-white rounded-xl shadow-2xl w-full max-w-sm mx-auto">
                <div class="p-6 border-b flex justify-between items-center">
                    <h3 class="font-semibold text-lg text-gray-800">Gleitzeit anpassen</h3>
                    <button onclick="closeOvertimeModal()" class="p-2 text-gray-400 hover:bg-gray-100 rounded-full">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>
                <form onsubmit="handleOvertimeSubmit(event)" class="p-6 space-y-4">
                    <div>
                        <label for="overtime-hours" class="block text-sm font-medium text-gray-700 mb-2">
                            Neuer Gleitzeit-Stand (in Dezimalstunden)
                        </label>
                        <input 
                            type="number" 
                            step="0.01" 
                            id="overtime-hours" 
                            placeholder="z.B. 6.8 oder -2.5"
                            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono"
                        >
                    </div>
                    <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                        <p class="text-xs text-yellow-800">
                            <b>Hinweis:</b> Hiermit wird eine Korrektur-Buchung erstellt, um den aktuellen Stand auf den von dir eingegebenen Wert zu ändern.
                        </p>
                    </div>
                    <button 
                        type="submit"
                        class="w-full py-3 px-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-lg transition-colors"
                    >
                        Gleitzeit anpassen
                    </button>
                </form>
            </div>
        </div>
    `;
}