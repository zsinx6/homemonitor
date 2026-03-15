# Project Overview: "DigiMon(itor)" - Sysadmin V-Pet
**Target Hardware:** Raspberry Pi Zero 2 W (DietPi, 512MB RAM). Code MUST be extremely lightweight, utilizing asynchronous I/O to prevent memory bloat or CPU locking.
**Description:** A mobile-friendly web dashboard that acts as a Digimon-style virtual pet. The pet's health and EXP are directly tied to the uptime of self-hosted infrastructure (local and cloud) and the completion of sysadmin/personal tasks.

## Tech Stack
* **Backend:** Python + FastAPI + Uvicorn (lightweight, async).
* **Network I/O:** `httpx` (for async HTTP checks) and `aioping` (for ICMP/ping checks).
* **Database:** SQLite (using `aiosqlite` for async access).
* **Frontend:** Vanilla HTML/JS/CSS. (Use CSS Grid/Flexbox for a mobile-first layout. Optional: `NES.css` for an 8-bit retro aesthetic).

---

## 1. Database Schema (SQLite)
Create three tables:
1. **`pet_state`**: 
   * `id` (int, PK), `name` (str), `level` (int), `exp` (int), `max_exp` (int), `status` (str: happy, sad, injured), `last_backup_date` (datetime).
2. **`servers`**: 
   * `id` (int, PK), `name` (str), `address` (str - IP or URL), `port` (int, nullable), `type` (str: http or ping), `status` (str: UP or DOWN), `uptime_percent` (float), `total_checks` (int), `successful_checks` (int).
3. **`todos`**: 
   * `id` (int, PK), `task` (str), `is_completed` (bool), `created_at` (datetime).

---

## 2. Backend Architecture & Background Tasks
Implement a background task using `asyncio.sleep(60)` that runs every minute to check server statuses.

### Monitoring Logic:
* Loop through the `servers` table.
* If `type` is `http`: Use `httpx` to send a GET request. If HTTP 200-399, mark UP.
* If `type` is `ping` (local LAN like Raspberry Pi 5): Use `aioping` or `asyncio.create_subprocess_exec` to ping the IP/Port.
* Update `total_checks` and `successful_checks` to calculate `uptime_percent`.

### V-Pet Logic Engine (Runs hourly or based on state changes):
* **Good State:** If ALL servers are UP -> Pet gains +10 EXP.
* **Bad State:** If ANY server is DOWN -> Pet loses -5 EXP, state becomes 'injured'/'sad', and an error alert string is generated (e.g., "ALERT: ingressos.python.org.br is DOWN!").
* **Level Up:** If `exp` >= `max_exp`, increment `level`, reset `exp`, increase `max_exp`.
* **Phrases:** Provide an array of random Digimon-style phrases (e.g., "Systems nominal!", "I sense a disturbance in the LAN...", "Feed me more packets!").

---

## 3. REST API Endpoints
* `GET /api/pet` -> Returns pet state, current EXP, Level, and a random phrase.
* `POST /api/pet/interact` -> "Petting" the Digimon. Returns a happy phrase.
* `POST /api/pet/backup` -> Updates `last_backup_date` to now, grants +50 EXP.
* `GET /api/servers` -> Lists all servers and their current status/uptime bar data.
* `POST /api/servers` -> Add a new server (Name, Address, Port).
* `PUT /api/servers/{id}` -> Edit a server.
* `DELETE /api/servers/{id}` -> Delete a server.
* `GET /api/todos` -> List pending and recently completed tasks.
* `POST /api/todos` -> Add a task.
* `PUT /api/todos/{id}/complete` -> Mark task completed, grants +20 EXP to the pet.

---

## 4. Frontend UI/UX (Mobile-First SPA)
Create a single `index.html` file served by FastAPI. 

### Layout Structure (Critical constraint: Face always visible)
* **Sticky Header (The V-Pet):**
  * Fixed at the top of the viewport (`position: sticky; top: 0;`).
  * Displays an ASCII art or CSS-drawn Digimon face.
  * Face changes based on the `status` from the DB (Like pwanagotchi faces, but with digimon like features, all pixel art).
  * Shows Level, EXP Bar (CSS progress bar), and a speech bubble with the random phrase/error alerts.
  * Clicking the Digimon triggers the "Pet" API and shows a heart animation.
* **Scrollable Body (3 Tabs):**
  * **Tab 1: Infrastructure:** List of monitored servers. Shows Name, Address, Status indicator (Green/Red dot), and a visual Uptime Bar. Includes an "Add Server" form.
  * **Tab 2: Tasks:** A simple TODO list. Clicking a checkbox completes it and animates EXP flowing up to the sticky header.
  * **Tab 3: Maintenance:** Displays "Days since last backup". A big "RUN MONTHLY BACKUP" button that triggers the backup API and grants massive EXP.

---

## 5. Step-by-Step Execution Plan for Copilot
1. **Initialize:** Setup the Python virtual environment and create the FastAPI `main.py` scaffolding.
2. **Database Setup:** Create the `database.py` file using `aiosqlite` and initialize the schema. Populate the DB with a default pet.
3. **Background Worker:** Write the async monitoring loop that pings the servers and calculates the EXP/Health logic.
4. **API Routes:** Implement the CRUD routers for `/api/servers`, `/api/todos`, and the `/api/pet` endpoints.
5. **Frontend Core:** Create `static/index.html` with the mobile-first CSS layout. Ensure the V-Pet header is strictly fixed to the top.
6. **Frontend Integration:** Write the Vanilla JS `fetch()` calls to wire the UI to the FastAPI backend. Implement the visual EXP bar updates and server status polling (every 30 seconds).
