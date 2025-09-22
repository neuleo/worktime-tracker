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
                <div class="flex flex-col md:flex-row gap-4">
                    <div>
                        <label for="from-date" class="block text-sm font-medium text-gray-700">Von</label>
                        <input type="date" id="from-date" value="${defaultFrom}" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                    </div>
                    <div>
                        <label for="to-date" class="block text-sm font-medium text-gray-700">Bis</label>
                        <input type="date" id="to-date" value="${defaultTo}" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                    </div>
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
}

function destroyCharts() {
    activeCharts.forEach(chart => chart.destroy());
    activeCharts = [];
}

async function renderCharts() {
    destroyCharts();
    setupStatisticsEventListeners();

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

    await loadStatistics(fromDate, toDate);

    if (!appState.statisticsData) {
        chartsContainer.innerHTML = `<p class="text-red-500">Fehler beim Laden der Diagrammdaten.</p>`;
        return;
    }

    chartsContainer.innerHTML = `
        <div class="space-y-6">
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
        </div>
    `;
    
    // Use setTimeout to ensure canvas is ready
    setTimeout(() => {
        renderOvertimeChart(appState.statisticsData.overtime_trend);
        renderWeeklyWorkChart(appState.statisticsData.weekly_summary);
        renderDailyWorkChart(appState.statisticsData.daily_summary);
    }, 0);
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