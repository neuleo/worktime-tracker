// Utility Functions
function getCacheBuster(url) {
    if (!CONFIG.CACHE_BUSTER_ENABLED) return '';
    const separator = url.includes('?') ? '&' : '?';
    return `${separator}cb=${Date.now()}`;
}

function formatTime(date) {
    return date.toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: 'Europe/Berlin'
    });
}

function formatTimeShort(date) {
    return date.toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'Europe/Berlin'
    });
}

function formatDuration(timeString) {
    if (timeString.startsWith('-')) {
        return `−${timeString.substring(1)}`;
    }
    return timeString;
}

function getOvertimeColor(overtime) {
    if (overtime.startsWith('-')) return 'text-red-500';
    if (overtime === '00:00') return 'text-gray-600';
    return 'text-green-500';
}

function getWeekNumber(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const dayNum = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil((((d.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
}

function groupSessionsByDate(sessions) {
    const grouped = {};
    sessions.forEach(session => {
        if (!grouped[session.date]) {
            grouped[session.date] = [];
        }
        grouped[session.date].push(session);
    });
    return grouped;
}

function secondsToTimeStr(seconds) {
    const isNegative = seconds < 0;
    const absSeconds = Math.abs(seconds);
    const hours = Math.floor(absSeconds / 3600);
    const minutes = Math.floor((absSeconds % 3600) / 60);
    const timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
    return isNegative ? `-${timeStr}` : timeStr;
}

function calculateDailyStatsJS(bookings, targetSeconds, options = {}) {
    if (!bookings || bookings.length === 0) {
        return { worked: '00:00', pause: '00:00', overtime: '00:00', netSeconds: 0, pauseSeconds: 0, overtimeSeconds: 0 };
    }

    const sortedBookings = bookings.sort((a, b) => {
        // Always use timestamp_iso for sorting if available.
        const timeA = a.timestamp_iso ? new Date(a.timestamp_iso) : new Date(`1970-01-01T${a.time || '00:00'}:00`);
        const timeB = b.timestamp_iso ? new Date(b.timestamp_iso) : new Date(`1970-01-01T${b.time || '00:00'}:00`);
        return timeA - timeB;
    });

    const getSecondsOfDay = (booking) => {
        if (booking.timestamp_iso) {
            const dt = new Date(booking.timestamp_iso);
            return dt.getHours() * 3600 + dt.getMinutes() * 60 + dt.getSeconds();
        }
        // Fallback for legacy or incomplete data.
        const [hours, minutes] = (booking.time || '00:00').split(':').map(Number);
        return (hours * 3600) + (minutes * 60);
    };

    const cutoff_start_seconds = (6 * 3600) + (30 * 60); // 6:30
    const cutoff_end_seconds = (18 * 3600) + (30 * 60); // 18:30

    const firstStampSeconds = getSecondsOfDay(sortedBookings[0]);
    const lastStampSeconds = getSecondsOfDay(sortedBookings[sortedBookings.length - 1]);

    const effective_first_stamp_seconds = Math.max(firstStampSeconds, cutoff_start_seconds);
    const effective_last_stamp_seconds = Math.min(lastStampSeconds, cutoff_end_seconds);

    // If the effective stamps create a negative duration, gross time is 0.
    const gross_session_seconds = Math.max(0, effective_last_stamp_seconds - effective_first_stamp_seconds);

    let manual_pause_seconds = 0;
    for (let i = 0; i < sortedBookings.length - 1; i++) {
        if (sortedBookings[i].action === 'out' && sortedBookings[i+1].action === 'in') {
            const pause_start = getSecondsOfDay(sortedBookings[i]);
            const pause_end = getSecondsOfDay(sortedBookings[i+1]);
            
            const effective_pause_start = Math.max(pause_start, effective_first_stamp_seconds);
            const effective_pause_end = Math.min(pause_end, effective_last_stamp_seconds);

            if (effective_pause_end > effective_pause_start) {
                manual_pause_seconds += (effective_pause_end - effective_pause_start);
            }
        }
    }

    // --- Pause Calculation Logic ---
    let statutory_break_seconds = 0;
    const SIX_HOURS_IN_SECONDS = 6 * 3600;
    const SIX_HOURS_30_MIN_IN_SECONDS = 6.5 * 3600;
    const NINE_HOURS_IN_SECONDS = 9 * 3600;
    const NINE_HOURS_15_MIN_IN_SECONDS = 9.25 * 3600;

    if (gross_session_seconds <= SIX_HOURS_IN_SECONDS) {
        statutory_break_seconds = 0;
    } else if (gross_session_seconds <= SIX_HOURS_30_MIN_IN_SECONDS) {
        statutory_break_seconds = gross_session_seconds - SIX_HOURS_IN_SECONDS;
    } else if (gross_session_seconds <= NINE_HOURS_IN_SECONDS) {
        statutory_break_seconds = 30 * 60;
    } else if (gross_session_seconds <= NINE_HOURS_15_MIN_IN_SECONDS) {
        statutory_break_seconds = (30 * 60) + (gross_session_seconds - NINE_HOURS_IN_SECONDS);
    } else {
        statutory_break_seconds = 45 * 60;
    }

    const paola_active = options.paola && manual_pause_seconds === 0;
    let total_deducted_pause_seconds = Math.max(manual_pause_seconds, statutory_break_seconds);

    if (paola_active) {
        const paola_pause_seconds = 50 * 60;
        total_deducted_pause_seconds = Math.max(total_deducted_pause_seconds, paola_pause_seconds);
    }
    
    let net_work_seconds = gross_session_seconds - total_deducted_pause_seconds;
    net_work_seconds = Math.max(0, net_work_seconds);

    const TEN_HOURS_SECONDS = 10 * 3600;
    const capped_net_worked_seconds = Math.min(net_work_seconds, TEN_HOURS_SECONDS);

    const overtime_seconds = capped_net_worked_seconds - targetSeconds;

    return {
        worked: secondsToTimeStr(capped_net_worked_seconds),
        pause: secondsToTimeStr(total_deducted_pause_seconds),
        overtime: secondsToTimeStr(overtime_seconds),
        netSeconds: capped_net_worked_seconds,
        pauseSeconds: total_deducted_pause_seconds,
        overtimeSeconds: overtime_seconds
    };
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    const bgColor = type === 'error' ? 'bg-red-500' : type === 'success' ? 'bg-green-500' : 'bg-blue-500';
    notification.className = `fixed top-4 right-4 ${bgColor} text-white px-4 py-2 rounded-lg shadow-lg z-50 notification hide`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.remove('hide');
        notification.classList.add('show');
    }, 100);
    
    setTimeout(() => {
        notification.classList.remove('show');
        notification.classList.add('hide');
        setTimeout(() => notification.remove(), 300);
    }, CONFIG.NOTIFICATION_DURATION);
}

// Create SVG icons
function createIcon(name, className = 'h-6 w-6') {
    const icons = {
        clock: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        play: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293H15M13 16h-1.586a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 008 13H7m8 3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        square: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        calendar: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>`,
        trending: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"></path></svg>`,
        menu: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>`,
        wifi: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0"></path></svg>`,
        wifioff: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" /></svg>`,
        trash: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`,
        edit: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" /></svg>`,
        settings: `<svg class="${className}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>`
    };
    return icons[name] || '';
}