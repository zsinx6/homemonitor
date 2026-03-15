# DigiMon(itor) — Implementation Plan

## Concept
A Raspberry Pi Zero 2 W–hosted web dashboard where a Digimon-style V-Pet is your **living sysadmin companion**. It reacts visibly to every infrastructure event, notices when you complete tasks, and communicates through a dynamic speech bubble. The Digimon is not a passive status indicator — it is the interface. Monitoring, alerts, and task management all happen *in relation to it*. The interaction with the pet is as important as the server data it reflects.

---

## Resolved Design Decisions

### Monitoring
- Both **HTTP** and **ping** checks are in scope for v1.
- Ping uses `asyncio.create_subprocess_exec('ping', '-c', '1', '-W', '3', address)` — no extra dependency, no privilege issues on DietPi.
- HTTP check: status 200–399 = UP; timeout or error = DOWN.
- Monitoring cycle: every **60 seconds**, guarded by an `asyncio.Lock` to prevent overlap.
- Within each cycle, **all server checks run in parallel** via `asyncio.gather()` — critical for keeping cycle time short on a low-power device when monitoring many servers.
- Worker starts and stops via FastAPI **lifespan** context.
- Each cycle upserts a `server_daily_stats` row for the current date (drives the 7-day uptime grid).

### Performance on Raspberry Pi Zero 2 W
Async I/O is **ideal** for this workload on the Pi Zero 2 W:
- All monitoring is I/O-bound (network waits) — asyncio shines here, no thread overhead.
- `asyncio.gather()` for parallel checks means 10 servers complete in ~10s max instead of 100s.
- `httpx.AsyncClient` with connection pooling is lightweight in memory.
- Uvicorn with a single worker is correct for a 512 MB personal dashboard.
- The only CPU-bound work is response parsing — negligible at this scale.

### Pet Logic Cadence
- Pet EXP and HP are recalculated **after every monitoring cycle** (every 60 seconds).
- Rates are calibrated for per-minute ticks (not hourly).

### EXP and HP Rules
| Event | Effect |
|---|---|
| All servers UP (per cycle) | +1 EXP |
| Any server DOWN (per cycle) | −2 HP |
| Server recovers (DOWN → UP transition) | +1 HP (up to max), sets `last_event = "recovery"` |
| Complete a task | +20 EXP, +1 HP |
| Run backup | +50 EXP, +5 HP, sets `last_event = "backup"` |
| Pet the Digimon (interact) | +2 EXP, updates `last_interaction_date` |
| Backup overdue > 30 days | −1 HP per cycle (passive drain) |
| No interaction for > 24h | status shows `lonely` sub-state, unique phrase |

- **EXP floor: 0** (cannot go negative).
- **Level-up:** when `exp >= max_exp`, increment `level`, carry over excess (`exp = exp − max_exp`), scale `max_exp` ×1.5 rounded. Sets `last_event = "level_up"`.
- **HP max: 10**, floor: 0. Does not scale with level.
- Starting values: `level=1`, `exp=0`, `max_exp=100`, `hp=10`.
- HP recovery is **automatic** when a downed server returns UP.
- Completing a task grants +1 HP in addition to EXP.

### Pet Status State Machine
Status is **derived at read time** — not stored — from `hp`, current server states, and `last_interaction_date`.

| Condition | Status | Face |
|---|---|---|
| `hp >= 7`, no servers DOWN, interacted <24h | `happy` | Alert, energetic grin |
| `hp >= 7`, no servers DOWN, no interaction ≥24h | `lonely` | Droopy, waiting |
| `hp >= 4` OR any server DOWN | `sad` | Worried, brow furrowed |
| `hp <= 3` | `injured` | Strained, sweat drops |
| `hp == 0` | `critical` | System failure, static eyes |

### Digimon Face Design (pwnagotchi-inspired, Digimon DNA)
Inspired by pwnagotchi's minimalist ASCII-art expressions on e-ink, but with distinct Digimon features:

- **Structure**: text-art face using Unicode characters, displayed in a monospace font with NES.css for the 8-bit retro aesthetic (CSS-only, no JS, ~6KB).
- **Digimon DNA** (not pwnagotchi clone):
  - Spike/horn above the face: `▲` or `╱╲` — Digimon tend to be edgier and spikier.
  - Angular eye shapes using `◣ ◤` or `▰` pixels — more digital/square than organic.
  - "Digi-crest" glyph on the forehead: small flame/lightning symbol `⚡` or custom character.
  - Side guard marks: `╠═` `═╣` instead of simple `( )` — feels more armoured.
  - Energetic vs calm: Digimon expressions are more intense, less sleepy.
- **5 expressions** defined as CSS class variants:

```
happy     ▲              lonely    △              sad       ▽
        ╠══════╣                ╠══════╣                ╠══════╣
        ║ ◆  ◆ ║                ║ ─  ─ ║                ║ ╥  ╥ ║
        ║  ⚡  ║                ║  ...  ║                ║  ≈  ║
        ║  ᴗ   ║                ║  ___  ║                ║  ︵  ║
        ╚══════╝                ╚══════╝                ╚══════╝

injured   ▽                critical  ✕
        ╠══════╣                ╠══════╣
        ║ ×  × ║                ║ ✕  ✕ ║
        ║  ⚡  ║                ║  !!!  ║
        ║  _/‾ ║                ║  ___  ║
        ╚══════╝                ╚══════╝
```

- The face is a `<pre>` block inside the header, styled with NES.css font + CSS colour classes.
- Status-based CSS classes swap the character set; CSS `transition` on `color`/`opacity` for smooth changes.
- Idle animation: `@keyframes` — `translateY` bob; rate varies by status (energetic for happy, slow for sad).

### Context-Aware Speech Bubble (primary notification system)
The speech bubble is the **only** notification channel — no separate alert panels.

| Context | Example |
|---|---|
| All UP, happy | "All nodes nominal. I am UNSTOPPABLE." |
| Recovery after DOWN | "Phew! `nginx` is back. I was worried." |
| Server just went DOWN | "ALERT: `postgres` is DOWN! Deploying repair protocol..." |
| Multiple servers DOWN | "We're under siege! 3 services offline!" |
| HP critical | "I can't... take much more of this..." |
| Lonely | "Hey... you haven't checked in. Everything okay?" |
| Backup overdue | "My data is unprotected. Please run a backup." |
| Level up | "DIGIVOLUTION INITIATED. I am now LEVEL {n}!" |
| After petted | "Processing affection... efficiency +2%." |
| After backup | "Backup complete. I feel immortal." |
| After task done | "Task absorbed. EXP transferred." |

Phrases live in categorised arrays in `app/domain/phrases.py`, selected by a `PhraseSelector` via the `LLMInterface` — in v1 the default implementation picks from arrays.

### Interaction Workflow (Sysadmin Feedback Loop)
The engagement loop that makes the V-pet a real motivator:
1. Server goes DOWN → Digimon shows alert face, speech bubble names the server, HP drains.
2. User sees the alert → creates a task: "Fix `postgres` backup".
3. User fixes the server externally. Server returns UP → Digimon auto-recovers HP, sets `last_event = "recovery"`.
4. User marks task complete → Digimon gets +20 EXP +1 HP (double reward for closing the loop).
5. Regular backup run → big EXP + HP burst, celebration animation.

### LLM Interface (v1 placeholder, v2 ready)
- `LLMInterface` abstract base in `app/domain/llm_interface.py` with `async generate_phrase(context: PetContext) -> str`.
- v1 default: `StaticPhraseService` uses phrase arrays (satisfies the interface).
- v2: a `CloudLLMService` (e.g. OpenAI, Gemini) implements the same interface — swap in via config flag, zero other changes.
- `PhraseSelector` is injected via FastAPI dependency injection.

### Frontend
- Single `static/index.html` served at `GET /` via FastAPI `StaticFiles`.
- NES.css included as a CDN link (CSS-only, ~6KB gzipped, no JS).
- Digimon header: ~40% of mobile viewport height, always sticky.
- 5 text-art face expressions; 5 CSS animation states.
- 7-day GitHub-style uptime grid per server with CSS tooltip on mouseover.
- Pure CSS tab switching (`:checked` radio inputs, no JS).
- 30s polling; all animations on `transform`/`opacity` only (GPU compositing, no layout reflow).

---

## Architecture

Clean separation of concerns — each layer independently testable:

```
app/
  domain/                       # Pure Python. No FastAPI, no DB, no I/O.
    pet.py                      # Pet dataclass + EXP/HP rules, level-up, status derivation
    server.py                   # Server entity: uptime calc, DOWN→UP transition detection
    phrases.py                  # Phrase arrays + PhraseSelector class
    llm_interface.py            # Abstract async LLMInterface (v2 seam)
    static_phrase_service.py    # Default impl: selects from phrase arrays
    constants.py                # ALL tunable numbers in one place

  services/                     # Orchestration. Depends on domain + repo interfaces.
    monitor_service.py          # Runs checks in parallel, calls pet domain, persists
    pet_service.py              # interact, backup → pet domain → persist
    task_service.py             # create, complete → pet domain → persist

  infrastructure/
    database.py                 # aiosqlite init, schema creation, seed
    repositories/
      pet_repo.py               # DB read/write for pet_state
      server_repo.py            # DB read/write for servers + server_daily_stats
      task_repo.py              # DB read/write for tasks
    checkers/
      base.py                   # Abstract ServerChecker interface
      http_checker.py           # httpx.AsyncClient implementation
      ping_checker.py           # asyncio.create_subprocess_exec implementation

  api/
    routers/
      pet.py                    # /api/pet routes
      servers.py                # /api/servers routes
      tasks.py                  # /api/tasks routes
    models.py                   # Pydantic request/response models
    dependencies.py             # FastAPI DI: DB connection, services, phrase selector

  worker.py                     # asyncio.Lock + asyncio.gather + monitor_service loop
  main.py                       # FastAPI app, lifespan, static mount

static/
  index.html                    # Entire SPA: HTML + CSS (NES.css CDN) + vanilla JS

tests/
  domain/
    test_pet.py                 # EXP/HP rules, level-up overflow, status derivation
    test_server.py              # Uptime calc, state transition detection
    test_phrases.py             # Phrase context selection, correct category chosen
  services/
    test_monitor_service.py     # Mock checkers → verify pet updates
    test_pet_service.py         # Interact/backup EXP/HP effects
    test_task_service.py        # Task completion effects
  api/
    test_pet_routes.py          # Async HTTP responses + EXP/HP side effects
    test_server_routes.py       # CRUD + daily stats
    test_task_routes.py         # CRUD + complete endpoint
  conftest.py                   # Shared fixtures: in-memory aiosqlite DB, mock checkers
```

---

## Schema (SQLite via aiosqlite)

### `pet_state`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | always row 1 |
| `name` | TEXT | default "Agumon" |
| `level` | INTEGER | starts at 1 |
| `exp` | INTEGER | starts at 0, floor 0 |
| `max_exp` | INTEGER | starts at 100 |
| `hp` | INTEGER | starts at 10, max 10, floor 0 |
| `last_backup_date` | DATETIME | nullable |
| `last_interaction_date` | DATETIME | updated on every `/api/pet/interact` |
| `last_event` | TEXT | nullable; one-shot: cleared after being read by GET /api/pet |
| `last_updated` | DATETIME | updated each cycle |

### `servers`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | |
| `address` | TEXT | IP or URL |
| `port` | INTEGER | nullable |
| `type` | TEXT | `http` or `ping` |
| `status` | TEXT | `UP` or `DOWN` |
| `uptime_percent` | REAL | computed from all-time check counts |
| `total_checks` | INTEGER | |
| `successful_checks` | INTEGER | |
| `last_error` | TEXT | nullable |
| `last_checked` | DATETIME | |

### `server_daily_stats`
Drives the 7-day GitHub-style uptime grid.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `server_id` | INTEGER FK → servers.id | |
| `date` | TEXT | YYYY-MM-DD |
| `total_checks` | INTEGER | |
| `successful_checks` | INTEGER | |
| `uptime_percent` | REAL | |

Unique constraint on `(server_id, date)`. Worker upserts each cycle with `INSERT OR REPLACE`.

### `tasks`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `task` | TEXT | |
| `is_completed` | INTEGER | 0 or 1 |
| `created_at` | DATETIME | |
| `completed_at` | DATETIME | nullable |

---

## REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pet` | Pet state + derived status + context phrase + last_event (then cleared) |
| `POST` | `/api/pet/interact` | +2 EXP, updates last_interaction_date |
| `POST` | `/api/pet/backup` | +50 EXP, +5 HP, sets last_backup_date |
| `GET` | `/api/servers` | All servers with uptime + last 7 days of daily stats per server |
| `POST` | `/api/servers` | Add server (name, address, port, type) |
| `PUT` | `/api/servers/{id}` | Edit server |
| `DELETE` | `/api/servers/{id}` | Delete server |
| `GET` | `/api/tasks` | Pending tasks + last 20 completed |
| `POST` | `/api/tasks` | Add task |
| `PUT` | `/api/tasks/{id}/complete` | Complete task, +20 EXP, +1 HP |

---

## Implementation Phases

### Phase 1 — Domain Layer (TDD first)
- Create project layout: `app/`, `tests/`, `static/`.
- Write `domain/constants.py` first — all numbers in one place.
- **TDD cycle for each domain module**:
  - Write `tests/domain/test_pet.py` first, then `domain/pet.py` until tests pass.
  - Write `tests/domain/test_server.py` then `domain/server.py`.
  - Write `tests/domain/test_phrases.py` then `domain/phrases.py`, `llm_interface.py`, `static_phrase_service.py`.
- All domain tests have **zero external dependencies** — pure function calls, run in milliseconds.
- Configure `pytest.ini` / `pyproject.toml` with `asyncio_mode = "auto"` for pytest-asyncio.

### Phase 2 — Infrastructure Layer
- Write `infrastructure/database.py`: async schema creation + seed (default pet row on first run).
- Write repos (`pet_repo`, `server_repo`, `task_repo`) as thin async functions over aiosqlite.
- Write `checkers/http_checker.py` and `checkers/ping_checker.py`.
- Repos accept an injected `aiosqlite.Connection` — makes them mockable for service tests.

### Phase 3 — Services and Worker
- Write `services/monitor_service.py`: accepts checker list + repos, runs all checks with `asyncio.gather()`, calls domain logic, persists. Test with mock checkers.
- Write `services/pet_service.py` and `services/task_service.py` with test coverage.
- Write `worker.py`: asyncio loop + `asyncio.Lock` + calls `monitor_service`.
- Write `main.py`: FastAPI app, lifespan wires up DB + worker, `StaticFiles` mount, DI in `api/dependencies.py`.

### Phase 4 — API Layer
- Write router files and `models.py` (Pydantic v2).
- Write `tests/api/` using **`httpx.AsyncClient` + `ASGITransport`** — fully async, no sync wrappers:

```python
# tests/conftest.py
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import create_app

@pytest_asyncio.fixture
async def client(in_memory_db):
    app = create_app(db=in_memory_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
```

- Verify all routes: correct status codes, EXP/HP side effects, derived pet status, `last_event` one-shot clear.

### Phase 5 — Frontend (The Living Digimon)

#### 5a — Hero Header
- Sticky, ~40% of mobile viewport. Always visible.
- **Face**: `<pre>` block with NES.css monospace font. Five CSS class variants swap the character set (the ASCII-art faces defined above). `transition: color 0.3s` for smooth status changes.
- **Idle animation** (`@keyframes`): 2s vertical bob (`happy`), slow 4s breath (`sad`), 0.5s tremor (`injured`), frozen for `critical`.
- **Event animations** (JS adds CSS class, removes after animation ends):
  - `anim-hit`: red colour flash + `translateX` shake → triggered by `last_event === "server_down"`.
  - `anim-levelup`: golden glow + big bounce → triggered by `last_event === "level_up"`.
  - `anim-recovery`: green flash + upward bounce → triggered by `last_event === "recovery"`.
  - `anim-backup`: rainbow flash + celebrate → triggered by `last_event === "backup"`.
- **HP pips**: 10 NES.css-styled squares; red flash on damage, green flash on heal.
- **EXP bar**: NES.css progress widget; `transition: width 0.4s ease`; resets + re-fills on level-up.
- **Speech bubble**: NES.css `nes-balloon` style; `opacity` transition on text change.
- **Click/tap**: calls `POST /api/pet/interact`; spawns `❤️` elements that `translateY` upward then fade.

#### 5b — Tab Navigation
- Pure CSS tab switching (`:checked` radio buttons + adjacent sibling selectors).
- **Infrastructure tab**:
  - Responsive server card grid (NES.css container styling).
  - Each card: server name, address, status dot (pulsing green or red), all-time uptime %.
  - **7-day uptime grid**: 7 squares colour-coded by daily uptime % (green ≥95%, yellow ≥70%, red <70%, grey = no data). Pure CSS tooltip on `:hover` → shows `YYYY-MM-DD · uptime%`.
  - Downed server card: red border with a pulse animation.
  - "Add Server" form at tab bottom (NES.css form styling).
- **Tasks tab**:
  - Pending tasks listed first. NES.css checkbox style.
  - Checking off: calls `PUT /api/tasks/{id}/complete`, plays `+20 EXP` text rising to header, slides item out after 1.5s.
  - "Add task" inline form at bottom.
  - Last 20 completed tasks shown below a divider (greyed, strikethrough).
- **Maintenance tab**:
  - Days-since-backup counter (NES.css styled; turns red if >30 days).
  - Big "FEED BACKUP" NES.css button → calls `/api/pet/backup`, triggers `anim-backup` celebration.

#### 5c — Polling and Live Updates
- On load: immediate fetch. Then `setInterval` at 30s.
- Each poll: diff new state against previous; trigger animation class if changed.
- `last_event` triggers animation once, then cleared in local JS state (not re-triggered on next poll).
- **Optimistic updates**: every action immediately updates local EXP/HP display. Reverts on API error.
- All animations: `transform` + `opacity` only. No `width`/`height`/`top` in keyframes.
- Single JS state object; zero JS framework; zero build step.

### Phase 6 — Hardening
- Run full `pytest` suite; fix all failures.
- Verify worker runs cleanly with zero servers in DB.
- Smoke-test all endpoints with `curl`.
- Test the sysadmin feedback loop end-to-end (add server → it goes DOWN → create task → mark done → all states transition correctly).
- Profile memory and CPU on a Pi Zero 2 W–class device.

---

## Testing Strategy

- **pytest** + **pytest-asyncio** (`asyncio_mode = "auto"`) + **httpx** for all tests.
- Domain tests: zero external dependencies, run in milliseconds.
- Service tests: injected mock repos + mock checkers (no DB, no network).
- API tests: `httpx.AsyncClient` + `ASGITransport` + in-memory aiosqlite fixture.
- All numeric constants imported from `domain/constants.py` — tests never hardcode numbers.
- `tests/conftest.py` provides: `in_memory_db` fixture (creates schema, seeds pet) and `async_client` fixture.

### Dev dependencies to add
```
pytest
pytest-asyncio
anyio[trio]   # pytest-asyncio backend
```
(httpx is already in requirements.txt)

---

## Open Question
1. Should completed tasks be retained in DB forever (display cap at 20) or hard-deleted after 30 days?

---

## Notes
- `aioping` is **not used**. Subprocess ping covers ICMP without privilege issues.
- DB table is named `tasks` to avoid tooling name conflicts.
- All EXP/HP constants in `domain/constants.py` — one place to tune everything.
- `asyncio.gather()` in `monitor_service` is key for Pi Zero 2 W performance with multiple servers.
- NES.css is CSS-only (no JS), ~6KB gzipped — negligible footprint, big aesthetic win.
- The `LLMInterface` seam allows v2 to add real Digimon dialogue with a single new implementation class and a config flag — no other changes needed.
