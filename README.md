# ⏰ Arbeitszeit-Tracking App

Eine moderne, leichtgewichtige und dennoch professionelle Arbeitszeit-Tracking-App.  
Komplett überarbeitet mit **Multi-Session-Support**, **Timezone-Korrektheit**,  
**mobile-optimiertem Frontend** und einer robusten **Docker-Infrastruktur**.

---

## 🚀 Features

### 🔧 Backend (main.py)
- **Zeitzone-Handling**  
  - Vollständige Umstellung auf `Europe/Berlin`  
  - Helper-Funktionen für timezone-aware Datumsberechnungen  
  - API-Responses immer in deutscher Zeit  

- **Multi-Session Support**  
  - Mehrere Arbeitsblöcke pro Tag möglich  
  - Automatische Summierung aller Sessions  
  - Offene Sessions werden korrekt berücksichtigt  

- **Neue API-Endpoints**  
  - `GET /sessions` – Alle Buchungen abrufen  
  - `POST /sessions` – Manuelle Buchung hinzufügen  
  - `DELETE /sessions/{id}` – Buchung löschen  
  - `GET /timeinfo` – Übersicht der heutigen Arbeitszeit  

- **Cache-Busting Middleware**  
  - Alle API-Responses mit `no-cache` Headers  

---

### 🎨 Frontend (index.html)
- **🍔 Hamburger-Menü**  
  - 4 Seiten, mobile-optimiert  
  - Smooth animations, kein externes Framework  

- **📱 Neue Seiten**  
  - **Dashboard** – Live-Timer mit Arbeitszeit-Tracking  
  - **Alle Buchungen** – Übersicht & Lösch-Funktion  
  - **Arbeitszeit-Info** – Verbleibende Zeit, Endzeit-Prognose & Meilensteine  
  - **Manuelle Buchung** – Nachträgliche Einträge mit Validation  

- **⏰ Live-Updates**  
  - Timer läuft live im Hintergrund  
  - Automatische Aktualisierung aller Ansichten  
  - Intelligente Timer-Logik (startet/stoppt dynamisch)  

- **🕐 Zeitzone-Korrektheit**  
  - Alle Anzeigen in deutscher Zeit  
  - Lokalisierte Formatierung (de_DE)  

- **💾 Cache-Busting**  
  - Timestamp-basierte API-Calls  
  - Kein veralteter Datenstand zwischen Geräten  

---

### 🛠️ Infrastruktur
- **🐳 Docker**  
  - Läuft via `docker-compose up --build`  
  - SQLite-Datenbank im `./data/` Volume  
  - Backend auf Port `8000`, Frontend auf Port `3001`  

- **🌐 Nginx**  
  - Anti-Caching Proxy für API  
  - Security-Header & Tailwind-Unterstützung  

- **⚡ Service Worker (sw.js)**  
  - Network-first für API  
  - Kein HTML-Caching → sofortige Updates  
  - Offline-Handling bleibt erhalten  

---

### 🆕 Wichtige neue Features
- **Alle Buchungen Seite**  
  - Gruppiert nach Tagen  
  - Session-Details (Start, Ende, Pausen, Überstunden)  
  - Aktive Sessions markiert  

- **Arbeitszeit-Info Seite**  
  - Live-Anzeige der gearbeiteten Zeit  
  - Prognose-Endzeit basierend auf aktuellem Stand  
  - Meilensteine (6h, 9h, 10h) mit Uhrzeit  
  - Farbkodierte Status-Indikatoren  

- **Manuelle Buchung**  
  - Formular für nachträgliche Einträge  
  - Gesetzeskonforme Pausenberechnung  
  - Validation (max. 10h, Endzeit > Startzeit)  
  - Sofortige Synchronisierung  

---

### 💡 Technische Highlights
- **Performance**  
  - Minimale DOM-Manipulationen  
  - Live-Updates nur wenn nötig  

- **Mobile-First**  
  - Responsives Design  
  - Touch-optimierte UI  

- **Robustheit**  
  - Error-Handling für API & Frontend  
  - Offline-Detection & fallback UI  
  - Input-Validation überall  

---

## 🔐 Security - NEU
Diese Anwendung ist jetzt durch ein Passwort geschützt. Bevor Sie die Anwendung starten, müssen Sie zwei Umgebungsvariablen konfigurieren.

**1. Erstellen Sie eine `.env`-Datei:**
Erstellen Sie eine Datei mit dem Namen `.env` im Hauptverzeichnis des Projekts (`/home/docker/worktime-tracker`).

**2. Fügen Sie die folgenden Variablen hinzu:**
```
# .env file
APP_PASSWORD=IhrSuperGeheimesPasswort
JWT_SECRET_KEY=ein_sehr_langer_zufälliger_string_zur_sicherheit
STAMP_WEBHOOK_SECRET=eine_andere_geheime_zeichenkette_für_den_webhook
```

-   `APP_PASSWORD`: Ersetzen Sie `IhrSuperGeheimesPasswort` durch das Passwort, das Sie für den Login verwenden möchten.
-   `JWT_SECRET_KEY`: Dies ist ein geheimer Schlüssel zur Absicherung der Sessions. Ersetzen Sie den Beispielwert durch eine lange, zufällige Zeichenkette.
-   `STAMP_WEBHOOK_SECRET`: Dies ist eine geheime Zeichenkette für den MacroDroid-Webhook. Ersetzen Sie den Wert ebenfalls durch eine lange, zufällige Zeichenkette.

    Sie können sichere Schlüssel mit dem folgenden Befehl generieren:
    ```bash
    openssl rand -hex 32
    ```

**3. Aktualisieren Sie `docker-compose.yml`:**
Stellen Sie sicher, dass Ihre `docker-compose.yml`-Datei die `.env`-Datei für den Backend-Service lädt:
```yaml
services:
  backend:
    # ... andere Konfigurationen
    env_file:
      - .env
```

## ⚙️ Installation & Deployment
Nachdem Sie die `.env`-Datei konfiguriert haben, starten Sie die Anwendung wie gewohnt:
```bash
docker-compose up --build
```
