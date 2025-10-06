Ich habe das Frontend systematisch analysiert. Hier ist eine detaillierte Bug-Liste für den Programmierer:

## **KRITISCHE BUGS**

### 1. **Memory Leak in statistics.js**
**Datei:** `frontend/public/statistics.js`  
**Funktion:** `setupStatisticsEventListeners()`  
**Problem:** Event Listeners werden bei jedem `renderCharts()` Aufruf neu hinzugefügt, aber nie entfernt.  
```javascript
// Zeile ~48-49
fromDateEl.addEventListener('change', renderCharts);
toDateEl.addEventListener('change', renderCharts);
```
**Lösung:** Event Listeners vor dem Hinzufügen entfernen oder nur einmal registrieren.

---

### 2. **Doppeltes Chart-Rendering**
**Datei:** `frontend/public/app.js`  
**Zeilen:** ~287 + statistics.js  
**Problem:** Charts werden doppelt gerendert:
```javascript
// In render():
if (currentPage === 'stats') {
    setTimeout(renderCharts, 0); // 1. Aufruf
}

// In renderCharts():
async function renderCharts() {
    destroyCharts();
    setupStatisticsEventListeners(); // Fügt Listeners hinzu, die renderCharts nochmal aufrufen
    // ...
}
```
**Lösung:** Entweder die setTimeout-Logik entfernen oder die Event-Listener-Logik überarbeiten.

---

### 3. **Cache-Busting in index.html funktioniert nicht**
**Datei:** `frontend/public/index.html`  
**Zeilen:** 28, 48  
**Problem:** Template-Strings werden in statischem HTML nicht aufgelöst:
```html
<link rel="stylesheet" href="/styles.css?v=${Date.now()}">
<script src="/config.js?v=${Date.now()}"></script>
```
Das `${Date.now()}` bleibt als String stehen.  
**Lösung:** Inline-Script verwenden oder Template-Engine einsetzen.

---

### 4. **Fehlende ui-components.js**
**Datei:** `frontend/public/app.js`  
**Zeilen:** 285, 301, 304  
**Problem:** Folgende Funktionen werden aufgerufen, existieren aber nicht in den bereitgestellten Dateien:
- `renderDesktopMenu()`
- `renderUserSwitcher()`
- `renderDashboard()`
- `renderSessions()`
- `renderTimeInfo()`
- `renderManualBooking()`
- `renderFlextimePage()`
- `renderSettingsPage()`
- `renderMobileMenu()`

**Lösung:** ui-components.js muss eingebunden werden oder diese Funktionen müssen implementiert werden.

---

## **LOGIK-FEHLER**

### 5. **Timer-Management beim Seitenwechsel**
**Datei:** `frontend/public/app.js`  
**Funktion:** `router()`  
**Problem:** Timer werden gelöscht, aber nicht für alle Seiten korrekt neu gestartet:
```javascript
// Zeile ~18-19
if (timers.liveUpdate) clearInterval(timers.liveUpdate);
if (timers.timeInfoLiveUpdate) clearInterval(timers.timeInfoLiveUpdate);

// ...
else if (page === 'dashboard') {
    setupLiveUpdates(); // Nur hier wird Timer neu gestartet
}
```
**Auswirkung:** Wenn User eingestempelt ist und zu einer anderen Seite wechselt und dann zurück zu Dashboard geht, läuft der Live-Timer nicht mehr.  
**Lösung:** Timer-Status prüfen und bei Dashboard immer neu starten.

---

### 6. **setupLiveUpdates() startet doppelte Timer**
**Datei:** `frontend/public/app.js`  
**Funktion:** `setupLiveUpdates()`  
**Problem:** Kein Check, ob bereits ein Timer läuft:
```javascript
function setupLiveUpdates() {
    if (timers.liveUpdate) clearInterval(timers.liveUpdate); // Gut!
    if (appState.status.status === 'in') {
        timers.liveUpdate = setInterval(updateLiveDuration, CONFIG.LIVE_UPDATE_INTERVAL);
    }
}
```
**Aber:** Diese Funktion wird mehrfach aufgerufen (in `handleStamp()`, `router()`, `init()`), was zu Timing-Problemen führen kann.  
**Lösung:** Zentralisierte Timer-Verwaltung.

---

### 7. **Planned Departure Time wird nicht persistiert**
**Datei:** `frontend/public/app.js`  
**Funktion:** `handlePlannedDepartureChange()`, `router()`  
**Problem:** 
```javascript
// In router():
if (appState.currentPage === 'timeinfo') {
    appState.plannedDepartureTime = ''; // Wird gelöscht!
}
```
Wenn User zur timeinfo-Seite geht, geplante Zeit eingibt, dann wegnavigiert und zurückkommt, ist die Eingabe weg.  
**Lösung:** State persistieren oder nicht beim Routing löschen.

---

### 8. **Time Format Parsing in renderStartEndChart**
**Datei:** `frontend/public/statistics.js`  
**Zeilen:** ~115-119  
**Problem:** Zeitformat wird falsch konvertiert:
```javascript
const start = parseFloat(d.start_time.replace(':', '.')); // "09:30" -> 9.3 ❌
const end = parseFloat(d.end_time.replace(':', '.'));     // "17:45" -> 17.45 ❌
```
Sollte sein: "09:30" -> 9.5 (9 Stunden + 30 Minuten = 9.5)  
**Lösung:** Korrekte Umrechnung:
```javascript
const [h, m] = d.start_time.split(':').map(Number);
const start = h + (m / 60);
```

---

### 9. **User-Wechsel resettet Timer nicht**
**Datei:** `frontend/public/app.js`  
**Funktion:** `switchActiveUser()`  
**Problem:** Timer werden nicht neu initialisiert:
```javascript
async function switchActiveUser(username) {
    // ... Daten laden ...
    router(); // Ruft router auf, aber Timer-State bleibt von vorherigem User
}
```
**Auswirkung:** Wenn User A eingestempelt ist und man zu User B wechselt (der nicht eingestempelt ist), läuft der Timer trotzdem weiter.  
**Lösung:** Timer explizit stoppen/starten basierend auf neuem User-Status.

---

## **RACE CONDITIONS**

### 10. **Parallele API-Calls bei schnellem Seitenwechsel**
**Datei:** `frontend/public/app.js`  
**Funktion:** `router()`  
**Problem:** Bei schnellem Navigation können mehrere API-Calls parallel laufen:
```javascript
if (page === 'sessions') {
    await Promise.all([loadSessions(), loadUserSettings()]);
}
// User wechselt sofort zur nächsten Seite -> alte Promises laufen noch
```
**Lösung:** AbortController für API-Calls verwenden.

---

### 11. **Render während API-Call**
**Datei:** `frontend/public/app.js`  
**Funktion:** `loadStatus()`, `loadTodayData()`, etc.  
**Problem:** Diese Funktionen rufen `render()` auf, nachdem Daten geladen wurden:
```javascript
async function loadStatus() {
    // ...
    appState.status = data;
    render(); // ⚠️ Kann zu inkonsistentem UI führen
}
```
Wenn mehrere Daten gleichzeitig geladen werden, wird mehrfach gerendert.  
**Lösung:** Rendering batch-wise oder nur nach allen Loads.

---

## **FEHLENDE ERROR HANDLING**

### 12. **Login ohne Response-Validierung**
**Datei:** `frontend/public/login.js`  
**Zeilen:** ~19-23  
**Problem:** Keine Überprüfung des Response-Body:
```javascript
if (response.ok) {
    const data = await response.json();
    localStorage.setItem('loggedInUser', data.user); // Was wenn data.user undefined?
    localStorage.setItem('activeUser', data.user);
    window.location.href = '/';
}
```
**Lösung:** Validierung hinzufügen:
```javascript
if (!data || !data.user) throw new Error('Invalid response');
```

---

### 13. **Chart-Destroy ohne Error Handling**
**Datei:** `frontend/public/statistics.js`  
**Funktion:** `destroyCharts()`  
**Problem:**
```javascript
function destroyCharts() {
    activeCharts.forEach(chart => chart.destroy()); // Kein try-catch
    activeCharts = [];
}
```
Wenn ein Chart korrupt ist, crasht die ganze Funktion.  
**Lösung:** Try-catch um jeden destroy-Call.

---

### 14. **Keine globale Error Boundary**
**Datei:** Alle  
**Problem:** Unbehandelte Promise-Rejections können die App crashen lassen.  
**Lösung:** Global Error Handler:
```javascript
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled rejection:', event.reason);
    showNotification('Ein unerwarteter Fehler ist aufgetreten', 'error');
});
```

---

## **UI/UX BUGS**

### 15. **Modal-Close fehlt für Edit-Booking**
**Datei:** `frontend/public/app.js`  
**Funktion:** `handleEditBookingSubmit()`  
**Problem:** Es wird `closeEditBookingModal()` aufgerufen, aber diese Funktion ist nicht definiert.  
**Lösung:** Funktion implementieren oder umbenennen in vorhandene Funktion.

---

### 16. **Overtime Modal Toggle-Buttons nicht synchron**
**Datei:** `frontend/public/app.js`  
**Funktion:** `switchOvertimeInputMode()`  
**Problem:** Button-States werden manuell umgeschaltet - fehleranfällig.  
**Lösung:** State-basiertes Rendering.

---

### 17. **Menu-Overlay Close ohne Null-Check**
**Datei:** `frontend/public/app.js`  
**Funktion:** `closeMenu()`  
**Problem:**
```javascript
function closeMenu() {
    const overlay = document.getElementById('menu-overlay');
    overlay.classList.add(...); // Kein Check, ob overlay existiert
}
```
**Lösung:** Null-Check hinzufügen.

---

## **PERFORMANCE-PROBLEME**

### 18. **Gesamte Seite wird bei jedem Render neu gerendert**
**Datei:** `frontend/public/app.js`  
**Funktion:** `render()`  
**Problem:**
```javascript
rootEl.innerHTML = `...`; // Komplette Seite wird ersetzt
```
**Auswirkung:** Verlust von Scroll-Position, Form-State, Event-Listeners müssen neu gebunden werden.  
**Lösung:** Komponentisierung oder gezieltes DOM-Update.

---

### 19. **Live-Timer aktualisiert zu häufig**
**Datei:** `frontend/public/config.js`, `app.js`  
**Problem:** Timer läuft jede Sekunde:
```javascript
LIVE_UPDATE_INTERVAL: 1000, // 1 second
```
**Auswirkung:** Unnötiger Battery-Drain auf Mobile.  
**Empfehlung:** Auf 10 Sekunden erhöhen für Live-Duration.

---

## **INKONSISTENZEN**

### 20. **Port-Mismatch in nginx.conf**
**Datei:** `frontend/nginx.conf`  
**Zeile:** 2  
**Problem:**
```nginx
listen 3000;
```
Aber in `docker-compose.yml`:
```yaml
ports:
  - "3001:3000"
```
**Auswirkung:** Verwirrung bei direktem Container-Zugriff.  
**Empfehlung:** Kommentar hinzufügen oder Port angleichen.

---

### 21. **formatDuration verwendet falsches Minus-Zeichen**
**Datei:** `frontend/public/utils.js`  
**Funktion:** `formatDuration()`  
**Problem:**
```javascript
return `−${timeString.substring(1)}`; // Unicode U+2212 (MINUS SIGN)
```
Könnte zu Problemen bei String-Vergleichen führen.  
**Empfehlung:** Normalen Bindestrich `-` (U+002D) verwenden.

---

## **ZUSAMMENFASSUNG NACH PRIORITÄT**

**🔴 KRITISCH (sofort beheben):**
1. Memory Leak in statistics.js (#1)
2. Fehlende ui-components.js (#4)
3. Cache-Busting in index.html (#3)
4. Time Format Parsing (#8)

**🟡 HOCH (zeitnah beheben):**
5. Doppeltes Chart-Rendering (#2)
6. Timer-Management (#5, #6, #9)
7. Race Conditions (#10, #11)
8. Error Handling (#12, #13, #14)

**🟢 MITTEL (bei Gelegenheit):**
9. Planned Departure Persistenz (#7)
10. Modal-Close Funktion (#15)
11. Performance-Optimierungen (#18, #19)
12. Inkonsistenzen (#20, #21)

**Geschätzte Behebungszeit:** 8-12 Stunden für alle kritischen und hohen Bugs.