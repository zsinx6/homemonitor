"""Database initialisation: schema creation and default seed data.

All schema changes live here. Run ``await init_db(db)`` once at startup.
"""
from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pet_state (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT    NOT NULL DEFAULT 'Agumon',
    level                 INTEGER NOT NULL DEFAULT 1,
    exp                   INTEGER NOT NULL DEFAULT 0,
    max_exp               INTEGER NOT NULL DEFAULT 100,
    hp                    INTEGER NOT NULL DEFAULT 10,
    is_dead               INTEGER NOT NULL DEFAULT 0,
    last_backup_date      TEXT,
    last_interaction_date TEXT,
    last_event            TEXT,
    last_updated          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS servers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    address           TEXT    NOT NULL,
    port              INTEGER,
    type              TEXT    NOT NULL CHECK(type IN ('http', 'ping', 'tcp', 'http_keyword')),
    status            TEXT    NOT NULL DEFAULT 'UP' CHECK(status IN ('UP', 'DOWN')),
    uptime_percent    REAL    NOT NULL DEFAULT 100.0,
    total_checks      INTEGER NOT NULL DEFAULT 0,
    successful_checks INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    last_checked      TEXT,
    maintenance_mode  INTEGER NOT NULL DEFAULT 0,
    position          INTEGER NOT NULL DEFAULT 0,
    check_params      TEXT
);

CREATE TABLE IF NOT EXISTS server_daily_stats (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id         INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    date              TEXT    NOT NULL,
    total_checks      INTEGER NOT NULL DEFAULT 0,
    successful_checks INTEGER NOT NULL DEFAULT 0,
    uptime_percent    REAL    NOT NULL DEFAULT 0.0,
    UNIQUE(server_id, date)
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task         TEXT    NOT NULL,
    is_completed INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL,
    completed_at TEXT,
    priority     TEXT    NOT NULL DEFAULT 'normal'
);

CREATE INDEX IF NOT EXISTS idx_servers_status ON servers(status);
CREATE INDEX IF NOT EXISTS idx_server_daily_stats ON server_daily_stats(server_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(is_completed);

CREATE TABLE IF NOT EXISTS pet_memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT    NOT NULL,
    detail      TEXT,
    occurred_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_occurred ON pet_memories(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type ON pet_memories(event_type);
"""

_SEED_PET_SQL = """
INSERT OR IGNORE INTO pet_state (id, name, level, exp, max_exp, hp, last_interaction_date, last_updated)
VALUES (1, 'Bitmon', 1, 0, 100, 10, datetime('now', '-1 hour'), datetime('now'));
"""


async def apply_initial_name_async(db: aiosqlite.Connection, initial_name: str | None) -> None:
    """Apply the configured initial_name to the pet if it still has the default name.

    Called once at startup after init_db(). Safe to call on every restart —
    only renames if the current name is the default 'Bitmon' seed value.
    """
    if not initial_name:
        return
    await db.execute(
        "UPDATE pet_state SET name = ? WHERE id = 1 AND name = 'Bitmon'",
        (initial_name,),
    )
    await db.commit()


async def init_db(db: aiosqlite.Connection) -> None:
    """Create schema and seed the default pet row (idempotent)."""
    await db.executescript(_SCHEMA_SQL)
    # Migration: add is_dead column to existing databases that pre-date it
    try:
        await db.execute(
            "ALTER TABLE pet_state ADD COLUMN is_dead INTEGER NOT NULL DEFAULT 0"
        )
        await db.commit()
    except aiosqlite.OperationalError:
        logger.debug("Migration skip: is_dead column already exists")
    await db.execute(_SEED_PET_SQL)
    await db.commit()
    # Migration: add maintenance_mode column to existing databases
    try:
        await db.execute(
            "ALTER TABLE servers ADD COLUMN maintenance_mode INTEGER NOT NULL DEFAULT 0"
        )
        await db.commit()
    except aiosqlite.OperationalError:
        logger.debug("Migration skip: maintenance_mode column already exists")
    # Migration: add position column for server ordering
    try:
        await db.execute(
            "ALTER TABLE servers ADD COLUMN position INTEGER NOT NULL DEFAULT 0"
        )
        await db.commit()
        # Initialise positions from current id order so existing data is sane
        await db.execute(
            "UPDATE servers SET position = id"
        )
        await db.commit()
    except aiosqlite.OperationalError:
        logger.debug("Migration skip: position column already exists")
    # Migration: add priority column to tasks
    try:
        await db.execute(
            "ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'"
        )
        await db.commit()
    except aiosqlite.OperationalError:
        logger.debug("Migration skip: priority column already exists")
    # Migration: rebuild servers table to support new check types and add check_params column.
    # We detect the old schema by checking its DDL for the restricted type CHECK constraint.
    try:
        async with db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='servers'"
        ) as cur:
            row = await cur.fetchone()
        table_sql = row[0] if row else ""
        if "'http', 'ping'" in table_sql:
            # Disable FK enforcement during table rebuild to avoid constraint errors
            await db.execute("PRAGMA foreign_keys = OFF")
            await db.execute("ALTER TABLE servers RENAME TO _servers_v1")
            await db.execute("""
                CREATE TABLE servers (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    name              TEXT    NOT NULL,
                    address           TEXT    NOT NULL,
                    port              INTEGER,
                    type              TEXT    NOT NULL
                                      CHECK(type IN ('http', 'ping', 'tcp', 'http_keyword')),
                    status            TEXT    NOT NULL DEFAULT 'UP'
                                      CHECK(status IN ('UP', 'DOWN')),
                    uptime_percent    REAL    NOT NULL DEFAULT 100.0,
                    total_checks      INTEGER NOT NULL DEFAULT 0,
                    successful_checks INTEGER NOT NULL DEFAULT 0,
                    last_error        TEXT,
                    last_checked      TEXT,
                    maintenance_mode  INTEGER NOT NULL DEFAULT 0,
                    position          INTEGER NOT NULL DEFAULT 0,
                    check_params      TEXT
                )
            """)
            await db.execute("""
                INSERT INTO servers
                SELECT id, name, address, port, type, status, uptime_percent,
                       total_checks, successful_checks, last_error, last_checked,
                       maintenance_mode, position, NULL
                FROM _servers_v1
            """)
            await db.execute("DROP TABLE _servers_v1")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_servers_status ON servers(status)"
            )
            await db.execute("PRAGMA foreign_keys = ON")
            await db.commit()
            logger.debug("Migration done: servers table rebuilt with new check types + check_params")
    except Exception as exc:
        logger.warning("Migration (servers rebuild) failed: %s", exc)
        try:
            await db.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
    # Migration: add V3 dust/mood columns to pet_state
    try:
        await db.execute(
            "ALTER TABLE pet_state ADD COLUMN dust_count INTEGER NOT NULL DEFAULT 0"
        )
        await db.execute(
            "ALTER TABLE pet_state ADD COLUMN last_dust_date TEXT"
        )
        await db.execute(
            "ALTER TABLE pet_state ADD COLUMN current_mood TEXT DEFAULT 'Energetic'"
        )
        await db.execute(
            "ALTER TABLE pet_state ADD COLUMN last_mood_change TEXT"
        )
        await db.commit()
        logger.debug("Migration done: added V3 dust/mood columns to pet_state")
    except aiosqlite.OperationalError:
        logger.debug("Migration skip: V3 columns already exist")
