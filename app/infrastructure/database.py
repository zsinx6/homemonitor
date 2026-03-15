"""Database initialisation: schema creation and default seed data.

All schema changes live here. Run ``await init_db(db)`` once at startup.
"""
from __future__ import annotations

import aiosqlite

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
    type              TEXT    NOT NULL CHECK(type IN ('http', 'ping')),
    status            TEXT    NOT NULL DEFAULT 'UP' CHECK(status IN ('UP', 'DOWN')),
    uptime_percent    REAL    NOT NULL DEFAULT 100.0,
    total_checks      INTEGER NOT NULL DEFAULT 0,
    successful_checks INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    last_checked      TEXT
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
    completed_at TEXT
);
"""

_SEED_PET_SQL = """
INSERT OR IGNORE INTO pet_state (id, name, level, exp, max_exp, hp, last_interaction_date, last_updated)
VALUES (1, 'Bitmon', 1, 0, 100, 10, datetime('now', '-1 hour'), datetime('now'));
"""


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
        pass  # column already exists
    await db.execute(_SEED_PET_SQL)
    await db.commit()
