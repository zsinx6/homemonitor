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
| `GET` | `/api/servers` | List all servers with 7-day uptime stats (sorted by position) |
| `POST` | `/api/servers` | Add a server `{"name", "address", "type": "http"\|"ping", "port"?}` |
| `PUT` | `/api/servers/{id}` | Edit server name / address / port / type |
| `DELETE` | `/api/servers/{id}` | Remove a server |
| `PATCH` | `/api/servers/{id}/maintenance` | Toggle maintenance mode (pauses HP damage) |
| `PATCH` | `/api/servers/{id}/move` | Reorder server `{"direction": "up"\|"down"}` |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tasks` | List tasks (pending sorted high→normal→low, then last 20 completed) |
| `POST` | `/api/tasks` | Add a task `{"task": "Fix nginx", "priority": "high"\|"normal"\|"low"}` |
| `PUT` | `/api/tasks/{id}/complete` | Complete a task (+20 EXP, +1 HP) |
| `DELETE` | `/api/tasks/{id}` | Delete a task |

### History & context

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memories?limit=25&offset=0` | Paginated event log with summary counts |
| `GET` | `/api/status` | Full context snapshot (used by LLM) |
| `POST` | `/api/chat` | Chat with the pet `{"message": "How are the servers?"}` |

### Export / Import

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/export` | Download full JSON snapshot (servers, tasks, memories, pet state) |
| `POST` | `/api/import` | Restore servers and pending tasks from export JSON |

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

## ntfy.sh push notifications

[ntfy.sh](https://ntfy.sh) delivers push alerts to your phone when servers go down or your pet dies — zero account required.

1. Install the ntfy app on your phone
2. Subscribe to a unique topic name (e.g. `my-homelab-alerts`)
3. Set it in `digimonitor.toml` or via env var:

```bash
export NTFY_TOPIC=https://ntfy.sh/my-homelab-alerts
# or self-hosted:
export NTFY_TOPIC=https://ntfy.yourserver.com/my-topic
```

Alerts are sent for:
- Server goes DOWN 🔴
- Pet DIES 💀
- Server recovers 🟢 (opt-in via `notify_on_recovery = true`)

---

## Gemini integration

Set `GEMINI_API_KEY` before starting the server.

- **Dynamic phrases** — the pet reacts to server events with context-aware one-liners (falls back to static phrases on timeout or missing key)
- **Free-form chat** — ask about your infrastructure, tasks, or just talk to your pet
- **Memory context** — the last 10 significant events are injected into every LLM prompt so the pet remembers what happened

No key? Everything works — phrases stay static and chat returns a friendly offline message.

---

## Configuration

Place a `digimonitor.toml` file in the project root to override defaults without editing source code.

```toml
[game]
exp_per_healthy_cycle = 1
hp_loss_per_down_cycle = 1
hp_max = 10
loneliness_hours = 24
backup_overdue_days = 30

[monitoring]
interval_seconds = 60
http_timeout_seconds = 10
ping_timeout_seconds = 3

[notifications]
# ntfy.sh push notifications — leave empty to disable
ntfy_topic = "https://ntfy.sh/my-homelab-alerts"
notify_on_recovery = false   # notify when a server comes back UP
notify_on_death = true       # notify when the pet dies
```

Environment variables take the highest priority:
- `NTFY_TOPIC` — overrides `notifications.ntfy_topic`
- `GEMINI_API_KEY` — enables the Gemini LLM integration

Individual constants can also still be edited in `app/domain/constants.py`.

---

## Development

```bash
# Install
pip install -r requirements.txt

# Run tests (273 tests, ~3 s)
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
    routers/        # FastAPI route handlers (pet, servers, tasks, chat, memories, export)
    models.py       # Pydantic request/response models
    dependencies.py
  main.py           # App factory + lifespan (DB init, worker start, config load)
  worker.py         # Background monitor loop (asyncio, 60 s interval)
  infrastructure/
    config.py       # TOML config loader — overrides constants + ntfy settings
    notifier.py     # ntfy.sh push notification client
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
