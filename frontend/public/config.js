// App Configuration
const CONFIG = {
    API_BASE: '/api',
    USER: 'leon',
    CACHE_BUSTER_ENABLED: true,
    LIVE_UPDATE_INTERVAL: 1000, // 1 second
    CLOCK_UPDATE_INTERVAL: 1000, // 1 second
    NOTIFICATION_DURATION: 3000, // 3 seconds
    VIBRATION: {
        STAMP_IN: [100],
        STAMP_OUT: [100, 50, 100]
    }
};

// Global App State
let appState = {
    status: { status: 'out' },
    dayData: null,
    weekData: null,
    sessions: [],
    timeInfo: null,
    overtimeData: null,
    isLoading: false,
    currentTime: new Date(),
    isOnline: navigator.onLine,
    activeTab: 'today',
    currentPage: 'dashboard',
    plannedDepartureTime: ''
};

// Timer management
let timers = {
    liveUpdate: null,
    clock: null,
    timeInfoLiveUpdate: null
};