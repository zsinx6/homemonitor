# DigiMon(itor)

A Digimon V-Pet that lives on your homelab and **earns EXP when your servers are healthy, takes damage when they go down, and dies if you neglect it long enough**.

Built for a Raspberry Pi Zero 2W. Runs in a browser. Optionally powered by Gemini.

```
  /\___/\
 (  ^ω^  )
  \ ‾‾‾ /
  ∪∪∪∪∪
```

---

## What it does

- **Monitors HTTP and ping servers** on a configurable interval (default: 60 s)
- **Pet health mechanics** — EXP per healthy cycle, HP loss per downed server per cycle, loneliness drain if you don't interact, HP/EXP rewards for backups and completed tasks
- **Evolution line** — Bitmon → Nibblemon → Packamon → Hostimon → Kernelmon (level-gated, expandable)
- **Death & revival** — HP hits 0 → pet dies; revive costs EXP reset and restores 5 HP
- **Memory / history log** — every significant event (server down, recovery, task done, backup, digivolution, rename, maintenance, death, revival) is persisted and shown in a History tab and fed to the LLM as context
- **Gemini chat** — optional; when `GEMINI_API_KEY` is set the pet speaks dynamic context-aware phrases and you can chat with it in natural language
- **Mobile-first dashboard** — sticky pet header visible at all times, 4 tabs (INFRA / TASKS / MAINT / HIST), no build step, no framework

---

## Requirements

- Python 3.11+
- A Raspberry Pi (or any Linux machine) on the same network as your services
- `GEMINI_API_KEY` — **optional**; without it all features work with static phrases

---

## Quick start

```bash
git clone https://github.com/yourname/homemonitor
cd homemonitor

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Optional — enables AI phrases and chat
export GEMINI_API_KEY=your_key_here

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<pi-ip>:8000` in your browser.

The SQLite database (`digimon.db`) is created automatically on first run.

---

## Running as a service (systemd)

```ini
# /etc/systemd/system/digimonitor.service
[Unit]
Description=DigiMon(itor)
After=network.target

[Service]
WorkingDirectory=/home/pi/homemonitor
ExecStart=/home/pi/homemonitor/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=GEMINI_API_KEY=your_key_here

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now digimonitor
```

---

## API reference

All endpoints are prefixed `/api`.

### Pet

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/pet` | Full pet state (HP, EXP, level, evolution, last event) |
| `POST` | `/api/pet/interact` | Pet the Digimon (+2 EXP, +1 HP, 30 s cooldown) |
| `POST` | `/api/pet/backup` | Run a backup (+30 EXP, +5 HP, 1 h cooldown) |
| `POST` | `/api/pet/revive` | Revive dead pet (resets EXP, restores 5 HP) |
| `PATCH` | `/api/pet/rename` | Set a custom name `{"name": "Sparky"}` |

### Servers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/servers` | List all servers with 7-day uptime stats |
| `POST` | `/api/servers` | Add a server `{"name", "address", "type": "http"\|"ping", "port"?}` |
| `PUT` | `/api/servers/{id}` | Edit server name / address / port / type |
| `DELETE` | `/api/servers/{id}` | Remove a server |
| `PATCH` | `/api/servers/{id}/maintenance` | Toggle maintenance mode (pauses HP damage) |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tasks` | List tasks (pending + last 20 completed) |
| `POST` | `/api/tasks` | Add a task `{"task": "Fix nginx backup"}` |
| `PUT` | `/api/tasks/{id}/complete` | Complete a task (+20 EXP, +1 HP) |
| `DELETE` | `/api/tasks/{id}` | Delete a task |

### History & context

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memories?limit=25&offset=0` | Paginated event log with summary counts |
| `GET` | `/api/status` | Full context snapshot (used by LLM) |
| `POST` | `/api/chat` | Chat with the pet `{"message": "How are the servers?"}` |

---

## Game mechanics

### EXP & levelling

| Event | EXP |
|-------|-----|
| All servers UP (per cycle) | +1 |
| Interact (pet) | +2 |
| Complete task | +20 |
| Run backup | +30 |

Level-up threshold starts at 100 EXP and scales ×1.5 each level. Death resets EXP to 0.

### HP

| Event | HP |
|-------|----|
| Server DOWN (per server, per cycle) | −1 |
| Server recovers | +1 |
| Pet interact | +1 |
| Complete task | +1 |
| Run backup | +5 |
| Lonely (>24 h without interaction) | −1/cycle |
| Backup overdue (>30 days) | −1/cycle |

HP max is 10. When HP reaches 0 the pet dies and must be revived.

### Evolution line

| Level | Species | Stage |
|-------|---------|-------|
| 1 | Bitmon | Fresh |
| 2–4 | Nibblemon | In-training |
| 5–14 | Packamon | Rookie |
| 15–29 | Hostimon | Champion |
| 30+ | Kernelmon | Perfect |

#### Adding a new evolution tier

1. Add an entry to `EVOLUTION_TIERS` in `app/domain/constants.py` (keep `min_level` sequential)
2. Add matching face art to `STAGE_FACES` in `static/index.html`
3. Run `pytest` — no other changes needed

---

## Gemini integration

Set `GEMINI_API_KEY` before starting the server.

- **Dynamic phrases** — the pet reacts to server events with context-aware one-liners (falls back to static phrases on timeout or missing key)
- **Free-form chat** — ask about your infrastructure, tasks, or just talk to your pet
- **Memory context** — the last 10 significant events are injected into every LLM prompt so the pet remembers what happened

No key? Everything works — phrases stay static and chat returns a friendly offline message.

---

## Configuration

All tunable numbers live in `app/domain/constants.py`. Edit and restart — no DB migration needed.

```python
EXP_PER_HEALTHY_CYCLE = 1       # EXP gained when all servers are UP
HP_LOSS_PER_DOWN_CYCLE = 1      # HP lost per downed server per cycle
HP_MAX = 10
MONITOR_INTERVAL_SECONDS = 60   # how often servers are checked
MONITOR_CYCLE_TIMEOUT_SECONDS = 120  # abort a stuck cycle after this
BACKUP_COOLDOWN_HOURS = 1
LONELINESS_HOURS = 24           # hours before the pet starts feeling lonely
BACKUP_OVERDUE_DAYS = 30
```

---

## Development

```bash
# Install
pip install -r requirements.txt

# Run tests (249 tests, ~3 s)
pytest

# Run with auto-reload
uvicorn app.main:app --reload
```

### Project layout

```
app/
  domain/           # Pure Python — Pet, Memory, constants, phrases, evolution
  infrastructure/   # DB schema, repositories, HTTP/ping checkers, adapters
  services/         # Business logic — MonitorService, PetService, TaskService,
                    #                  ContextService, LLMChatService
  api/
    routers/        # FastAPI route handlers (pet, servers, tasks, chat, memories)
    models.py       # Pydantic request/response models
    dependencies.py
  main.py           # App factory + lifespan (DB init, worker start)
  worker.py         # Background monitor loop (asyncio, 60 s interval)
static/
  index.html        # Single-file SPA — no build step, NES.css pixel theme
tests/
  api/              # HTTP integration tests (AsyncClient + tmp SQLite)
  services/         # Unit tests with mock repos
  domain/           # Pure domain logic tests
```

---

## Licence

MIT
