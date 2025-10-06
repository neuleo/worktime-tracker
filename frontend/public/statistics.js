let activeCharts = [];

function renderStatisticsPage() {
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
    const defaultFrom = thirtyDaysAgo.toISOString().split('T')[0];
    const defaultTo = new Date().toISOString().split('T')[0];

    return `
        <div class="space-y-6">
            <div class="bg-white p-4 md:p-6 rounded-lg shadow-md">
                <h3 class="text-lg font-bold mb-4 text-gray-700">Zeitraum</h3>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                        <label for="from-date" class="block text-sm font-medium text-gray-700">Von</label>
                        <input type="date" id="from-date" value="${defaultFrom}" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                    </div>
                    <div>
                        <label for="to-date" class="block text-sm font-medium text-gray-700">Bis</label>
                        <input type="date" id="to-date" value="${defaultTo}" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                    </div>
                </div>
                <div class="mt-4 flex flex-wrap gap-2">
                    <button class="date-range-btn px-3 py-1 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600" data-range="last_week">Letzte Woche</button>
                    <button class="date-range-btn px-3 py-1 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600" data-range="last_month">Letzter Monat</button>
                    <button class="date-range-btn px-3 py-1 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600" data-range="3_months">3 Monate</button>
                    <button class="date-range-btn px-3 py-1 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600" data-range="6_months">6 Monate</button>
                    <button class="date-range-btn px-3 py-1 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600" data-range="last_year">Letztes Jahr</button>
                    <button class="date-range-btn px-3 py-1 text-sm text-white bg-blue-500 rounded-md hover:bg-blue-600" data-range="all">Alles</button>
                </div>
            </div>

            <div id="charts-container"></div>
        </div>
    `;
}

function setupStatisticsEventListeners() {
    const fromDateEl = document.getElementById('from-date');
    const toDateEl = document.getElementById('to-date');

    if (fromDateEl && toDateEl) {
        fromDateEl.addEventListener('change', renderCharts);
        toDateEl.addEventListener('change', renderCharts);
    }

    document.querySelectorAll('.date-range-btn').forEach(button => {
        button.addEventListener('click', (e) => {
            const range = e.target.dataset.range;
            setDateRange(range);
            renderCharts();
        });
    });
}

function setDateRange(range) {
    const fromDateEl = document.getElementById('from-date');
    const toDateEl = document.getElementById('to-date');
    const to = new Date();
    let from = new Date();

    switch (range) {
        case 'last_week':
            from.setDate(to.getDate() - 7);
            break;
        case 'last_month':
            from.setMonth(to.getMonth() - 1);
            break;
        case '3_months':
            from.setMonth(to.getMonth() - 3);
            break;
        case '6_months':
            from.setMonth(to.getMonth() - 6);
            break;
        case 'last_year':
            from.setFullYear(to.getFullYear() - 1);
            break;
        case 'all':
            from = new Date('2020-01-01');
            break;
    }

    fromDateEl.value = from.toISOString().split('T')[0];
    toDateEl.value = to.toISOString().split('T')[0];
}

function destroyCharts() {
    activeCharts.forEach(chart => {
        try {
            chart.destroy();
        } catch (e) {
            console.error("Error destroying chart:", e);
        }
    });
    activeCharts = [];
}

async function renderCharts() {
    destroyCharts();

    const fromDate = document.getElementById('from-date').value;
    const toDate = document.getElementById('to-date').value;
    const chartsContainer = document.getElementById('charts-container');

    if (!fromDate || !toDate) {
        chartsContainer.innerHTML = `<p class="text-red-500">Bitte Start- und Enddatum auswählen.</p>`;
        return;
    }

    chartsContainer.innerHTML = `
        <div class="text-center">
            <div class="loading-spinner w-8 h-8 border-4 border-blue-200 border-t-blue-600 rounded-full mx-auto mb-4"></div>
            <div class="text-gray-600">Lade Diagrammdaten...</div>
        </div>
    `;

    await loadStatistics(fromDate, toDate, routeAbortController.signal);

    if (!appState.statisticsData) {
        chartsContainer.innerHTML = `<p class="text-red-500">Fehler beim Laden der Diagrammdaten.</p>`;
        return;
    }

    chartsContainer.innerHTML = `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-white p-4 md:p-6 rounded-lg shadow-md">
                <h3 class="text-lg font-bold mb-4 text-gray-700">Gleitzeitverlauf</h3>
                <canvas id="overtime-chart"></canvas>
            </div>
            <div class="bg-white p-4 md:p-6 rounded-lg shadow-md">
                <h3 class="text-lg font-bold mb-4 text-gray-700">Wöchentliche Arbeitszeit</h3>
                <canvas id="weekly-work-chart"></canvas>
            </div>
            <div class="bg-white p-4 md:p-6 rounded-lg shadow-md">
                <h3 class="text-lg font-bold mb-4 text-gray-700">Tägliche Arbeitszeit</h3>
                <canvas id="daily-work-chart"></canvas>
            </div>
            <div class="bg-white p-4 md:p-6 rounded-lg shadow-md">
                <h3 class="text-lg font-bold mb-4 text-gray-700">Arbeitszeit Trend</h3>
                <canvas id="start-end-chart"></canvas>
                <div id="average-times-container" class="mt-4"></div>
            </div>
        </div>
    `;
    
    setTimeout(() => {
        renderOvertimeChart(appState.statisticsData.overtime_trend);
        renderWeeklyWorkChart(appState.statisticsData.weekly_summary);
        renderDailyWorkChart(appState.statisticsData.daily_summary);
        renderStartEndChart(appState.statisticsData.daily_summary);
    }, 0);
}

function renderStartEndChart(data) {
    const ctx = document.getElementById('start-end-chart')?.getContext('2d');
    if (!ctx) return;

    const validEntries = data.filter(d => d.start_time && d.end_time);

    const chartData = validEntries.map(d => {
        const [startH, startM] = d.start_time.split(':').map(Number);
        const start = startH + (startM / 60);
        
        const [endH, endM] = d.end_time.split(':').map(Number);
        const end = endH + (endM / 60);

        return [start, end];
    });

    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: validEntries.map(d => new Date(d.date).toLocaleDateString('de-DE', { day: 'numeric', month: 'numeric' })),
            datasets: [{
                label: 'Arbeitszeit',
                data: chartData,
                backgroundColor: '#3b82f6',
                borderWidth: 1,
                borderRadius: 5,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            indexAxis: 'x',
            scales: {
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Uhrzeit' },
                    min: 6,
                    max: 19,
                    ticks: { stepSize: 1 }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const start = context.raw[0];
                            const end = context.raw[1];
                            return `Start: ${start.toFixed(2).replace('.', ':')} - Ende: ${end.toFixed(2).replace('.', ':')}`;
                        }
                    }
                }
            }
        }
    });
    activeCharts.push(chart);

    // Calculate and display average times
    const totalStartMinutes = validEntries.reduce((acc, d) => {
        const [hours, minutes] = d.start_time.split(':').map(Number);
        return acc + (hours * 60) + minutes;
    }, 0);
    const totalEndMinutes = validEntries.reduce((acc, d) => {
        const [hours, minutes] = d.end_time.split(':').map(Number);
        return acc + (hours * 60) + minutes;
    }, 0);

    const avgStartMinutes = totalStartMinutes / validEntries.length;
    const avgEndMinutes = totalEndMinutes / validEntries.length;

    const formatMinutes = (mins) => {
        if (isNaN(mins)) return '--:--';
        const h = Math.floor(mins / 60).toString().padStart(2, '0');
        const m = Math.round(mins % 60).toString().padStart(2, '0');
        return `${h}:${m}`;
    };

    const avgContainer = document.getElementById('average-times-container');
    if (avgContainer) {
        avgContainer.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t">
                <div class="bg-gray-50 p-4 rounded-lg shadow-inner text-center">
                    <p class="text-sm text-gray-600">Ø Startzeit</p>
                    <p class="text-2xl font-bold text-gray-800">${formatMinutes(avgStartMinutes)}</p>
                </div>
                <div class="bg-gray-50 p-4 rounded-lg shadow-inner text-center">
                    <p class="text-sm text-gray-600">Ø Endzeit</p>
                    <p class="text-2xl font-bold text-gray-800">${formatMinutes(avgEndMinutes)}</p>
                </div>
            </div>
        `;
    }
}

function renderOvertimeChart(data) {
    const ctx = document.getElementById('overtime-chart')?.getContext('2d');
    if (!ctx) return;

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => d.date),
            datasets: [{
                label: 'Gleitzeit (Stunden)',
                data: data.map(d => d.overtime_hours),
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            scales: {
                x: { type: 'time', time: { unit: 'day', tooltipFormat: 'dd.MM.yyyy' }, title: { display: true, text: 'Datum' } },
                y: { title: { display: true, text: 'Stunden' } }
            }
        }
    });
    activeCharts.push(chart);
}

function renderWeeklyWorkChart(data) {
    const ctx = document.getElementById('weekly-work-chart')?.getContext('2d');
    if (!ctx) return;

    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(d => d.week),
            datasets: [
                { label: 'Gearbeitet (Stunden)', data: data.map(d => d.worked_hours), backgroundColor: '#3b82f6' },
                { label: 'Soll (Stunden)', data: data.map(d => d.target_hours), backgroundColor: '#a5b4fc' }
            ]
        },
        options: { responsive: true, scales: { y: { beginAtZero: true, title: { display: true, text: 'Stunden' } } } }
    });
    activeCharts.push(chart);
}

function renderDailyWorkChart(data) {
    const ctx = document.getElementById('daily-work-chart')?.getContext('2d');
    if (!ctx) return;

    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(d => new Date(d.date).toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'numeric' })),
            datasets: [
                { label: 'Gearbeitet (Stunden)', data: data.map(d => d.worked_hours), backgroundColor: '#3b82f6' },
                { label: 'Soll (Stunden)', data: data.map(d => d.target_hours), backgroundColor: '#a5b4fc' }
            ]
        },
        options: { responsive: true, scales: { y: { beginAtZero: true, title: { display: true, text: 'Stunden' } } } }
    });
    activeCharts.push(chart);
}