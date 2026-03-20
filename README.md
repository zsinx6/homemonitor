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

- **Monitors HTTP, HTTP+keyword, TCP, and ping servers** on a configurable interval (default: 10 min)
- **Pet health mechanics** — EXP per healthy cycle, HP loss per downed server per cycle, loneliness drain if you don't interact, HP/EXP rewards for backups and completed tasks
- **Evolution line** — Bitmon → Nibblemon → Packamon → Hostimon → Kernelmon (level-gated, expandable)
- **Death & revival** — HP hits 0 → pet dies; revive costs EXP reset and restores 5 HP
- **Memory / history log** — every significant event (server down, recovery, task done, backup, digivolution, rename, maintenance, death, revival) is persisted and shown in a History tab and fed to the LLM as context
- **Gemini chat** — optional; when `GEMINI_API_KEY` is set you can chat with the pet in natural language; the last 10 significant events are injected as context so the pet remembers what happened
- **Digital Dust** — the pet accumulates dust every 5 hours (max 5); clean it with `POST /api/pet/clean` (+2 EXP) or HP drains at max dust
- **Focus sessions** — complete a Pomodoro-style work block with `POST /api/pet/focus_reward` (+15 EXP, +2 HP, 30-min cooldown)
- **Daily Mood** — the pet cycles through moods (Energetic, Melancholy, Rebellious, Philosophical, Anxious, Zen) that influence its phrases; returned as `current_mood` in `GET /api/pet`
- **Mobile-first dashboard** — sticky pet header visible at all times, 4 tabs (INFRA / TASKS / MAINT / HIST), no build step, no framework

---

## Requirements

- Python 3.11+
- A Raspberry Pi (or any Linux machine) on the same network as your services
- `GEMINI_API_KEY` — **optional**; without it all features work with static phrases

---

## First-run setup

Run the interactive wizard before starting the server for the first time:

```bash
python scripts/setup.py
```

It will ask you to configure:
- **Pet name** — what you call your Digimon (saved as `initial_name` in the config; applied once on first DB init)
- **Personality tone** — `serious` | `sarcastic` | `cheerful` | `grumpy` | `cryptic`
- **Backstory** — a short paragraph injected into every LLM prompt so the pet's voice is consistent
- **Speech quirks** — catchphrases or jargon patterns that colour all responses
- **ntfy.sh topic** — optional push notification URL

The wizard writes (or updates) `digimonitor.toml`. Re-running is safe — existing values are shown as defaults.

```bash
# Update config at any time
python scripts/setup.py

# Use a custom path
python scripts/setup.py --config /etc/digimonitor.toml
```

> **Gemini API key** is intentionally not stored in the file — set it as an environment variable instead:
> `export GEMINI_API_KEY=your_key_here`

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
| `POST` | `/api/pet/clean` | Clean accumulated dust (+2 EXP, resets dust counter) |
| `POST` | `/api/pet/focus_reward` | Complete a focus session (+15 EXP, +2 HP, 30-min cooldown) |

### Servers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/servers` | List all servers with 7-day uptime stats (sorted by position) |
| `POST` | `/api/servers` | Add a server `{"name", "address", "type": "http"\|"http_keyword"\|"tcp"\|"ping", "port"?, "check_params"?}` |
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
| `POST` | `/api/pet/chat` | Chat with the pet `{"message": "How are the servers?"}` |

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
| Clean dust | +2 |
| Complete task | +20 |
| Run backup | +30 |
| Complete focus session | +15 |

Level-up threshold starts at 100 EXP and scales ×1.5 each level. Death resets EXP to 0.

### HP

| Event | HP |
|-------|----|
| Server DOWN (per server, per cycle) | −1 |
| Server recovers | +1 |
| Pet interact | +1 |
| Complete task | +1 |
| Run backup | +5 |
| Complete focus session | +2 |
| Lonely (>24 h without interaction) | −1/cycle |
| Backup overdue (>30 days) | −1/cycle |
| Dust at max (5 units), every 3rd cycle | −1/cycle |

HP max is 10. When HP reaches 0 the pet dies and must be revived.

### Digital Dust

The pet passively accumulates dust over time (+1 unit every 5 hours, max 5). At maximum dust, the pet loses −1 HP every third monitor cycle until cleaned.

Use `POST /api/pet/clean` to clean the dust (+2 EXP, resets the counter). The `dust_count` field is returned by `GET /api/pet`.

### Focus Sessions

Reward yourself (and your pet) for completing a focused work block — a Pomodoro sprint or any uninterrupted session.

`POST /api/pet/focus_reward` → +15 EXP, +2 HP, 30-minute cooldown enforced server-side.

### Daily Mood

Each monitor cycle the pet is assigned one of six moods: **Energetic**, **Melancholy**, **Rebellious**, **Philosophical**, **Anxious**, or **Zen**. Mood influences the pet's phrases and is returned as `current_mood` in `GET /api/pet`.

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

- **Free-form chat** — ask about your infrastructure, tasks, or just talk to your pet (`POST /api/pet/chat`)
- **Memory context** — the last 10 significant events are injected into every prompt so the pet remembers what happened

No key? Everything works — chat returns a friendly offline message and the pet uses static phrases.

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
interval_seconds = 600
http_timeout_seconds = 10
ping_timeout_seconds = 3

[personality]
# Easiest to set via: python scripts/setup.py
initial_name = "Sparky"              # applied once on first DB init
tone = "sarcastic"                   # serious | sarcastic | cheerful | grumpy | cryptic
backstory = "Born from a kernel panic at 3am, hardened by years of silent uptime."
quirks = "References Linux kernel internals. Uses syscall names as expressions."

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

# Run tests
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
  worker.py         # Background monitor loop (asyncio, 10 min interval)
  infrastructure/
    config.py       # TOML config loader — overrides constants + personality + ntfy settings
    notifier.py     # ntfy.sh push notification client
scripts/
  setup.py          # Interactive first-run wizard — writes digimonitor.toml
static/
  index.html        # Single-file SPA — no build step, Inter font, dark theme
tests/
  api/              # HTTP integration tests (AsyncClient + tmp SQLite)
  services/         # Unit tests with mock repos
  domain/           # Pure domain logic tests
```

---

## Licence

MIT
