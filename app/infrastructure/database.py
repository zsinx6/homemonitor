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
    type              TEXT    NOT NULL CHECK(type IN ('http', 'ping', 'tcp', 'http_keyword', 'public_ip')),
    status            TEXT    NOT NULL DEFAULT 'UP' CHECK(status IN ('UP', 'DOWN')),
    uptime_percent    REAL    NOT NULL DEFAULT 100.0,
    total_checks      INTEGER NOT NULL DEFAULT 0,
    successful_checks INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    last_checked      TEXT,
    maintenance_mode  INTEGER NOT NULL DEFAULT 0,
    position          INTEGER NOT NULL DEFAULT 0,
    check_params      TEXT,
    last_response_ms  INTEGER,
    ssl_expiry_date   TEXT
);

CREATE TABLE IF NOT EXISTS server_daily_stats (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id         INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    date              TEXT    NOT NULL,
    total_checks      INTEGER NOT NULL DEFAULT 0,
    successful_checks INTEGER NOT NULL DEFAULT 0,
    uptime_percent    REAL    NOT NULL DEFAULT 0.0,
    avg_response_ms   REAL,
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


async def _rebuild_servers(
    db: aiosqlite.Connection,
    backup_name: str,
    create_sql: str,
    insert_sql: str,
    log_msg: str,
) -> None:
    """Atomically rebuild the servers table.

    Uses an explicit BEGIN EXCLUSIVE so that RENAME + CREATE TABLE + INSERT + DROP
    are all inside one SQLite transaction.  On any failure the whole transaction
    is rolled back, leaving the original 'servers' table untouched.
    """
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.execute("BEGIN EXCLUSIVE")
        await db.execute(f"ALTER TABLE servers RENAME TO {backup_name}")
        await db.execute(create_sql)
        await db.execute(insert_sql)
        await db.execute(f"DROP TABLE {backup_name}")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_servers_status ON servers(status)"
        )
        await db.execute("COMMIT")
        logger.debug("Migration done: %s", log_msg)
    except Exception:
        try:
            await db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


async def init_db(db: aiosqlite.Connection) -> None:
    """Create schema and seed the default pet row (idempotent)."""
    await db.executescript(_SCHEMA_SQL)

    # --- Recovery: restore data from orphaned backup tables left by a failed rebuild ---
    # If a previous migration renamed 'servers' → '_servers_vN' but then crashed
    # before the DROP, the real data is in the backup and 'servers' may be empty.
    for backup in ("_servers_v1", "_servers_v3"):
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (backup,)
        ) as cur:
            found = await cur.fetchone()
        if found is None:
            continue
        async with db.execute("SELECT COUNT(*) FROM servers") as cur:
            count = (await cur.fetchone())[0]
        if count == 0:
            logger.warning(
                "Recovering servers data from orphaned backup table %s", backup
            )
            await db.execute("DROP TABLE servers")
            await db.execute(f"ALTER TABLE {backup} RENAME TO servers")
        else:
            logger.warning("Dropping orphaned backup table %s (servers is non-empty)", backup)
            await db.execute(f"DROP TABLE {backup}")
        await db.commit()

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
    # Detected by absence of check_params in the DDL (the column this migration adds).
    try:
        async with db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='servers'"
        ) as cur:
            row = await cur.fetchone()
        table_sql = row[0] if row else ""
        if "check_params" not in table_sql:
            await _rebuild_servers(db, "_servers_v1", """
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
            """, """
                INSERT INTO servers
                SELECT id, name, address, port, type, status, uptime_percent,
                       total_checks, successful_checks, last_error, last_checked,
                       maintenance_mode, position, NULL
                FROM _servers_v1
            """, "servers table rebuilt with new check types + check_params")
    except Exception as exc:
        logger.warning("Migration (servers rebuild) failed: %s", exc)
    # Migration: add V3 dust/mood/focus columns to pet_state (each in its own guard)
    _v3_migrations = [
        ("dust_count",     "ALTER TABLE pet_state ADD COLUMN dust_count INTEGER NOT NULL DEFAULT 0"),
        ("last_dust_date", "ALTER TABLE pet_state ADD COLUMN last_dust_date TEXT"),
        ("current_mood",   "ALTER TABLE pet_state ADD COLUMN current_mood TEXT DEFAULT 'Energetic'"),
        ("last_mood_change", "ALTER TABLE pet_state ADD COLUMN last_mood_change TEXT"),
        ("last_focus_date",  "ALTER TABLE pet_state ADD COLUMN last_focus_date TEXT"),
    ]
    for col_name, sql in _v3_migrations:
        try:
            await db.execute(sql)
            await db.commit()
            logger.debug("Migration done: added column %s to pet_state", col_name)
        except aiosqlite.OperationalError:
            logger.debug("Migration skip: column %s already exists", col_name)
    # Migration: add latency and SSL columns to servers (nullable — safe ALTER TABLE)
    _server_v4_migrations = [
        ("last_response_ms", "ALTER TABLE servers ADD COLUMN last_response_ms INTEGER"),
        ("ssl_expiry_date",  "ALTER TABLE servers ADD COLUMN ssl_expiry_date TEXT"),
    ]
    for col_name, sql in _server_v4_migrations:
        try:
            await db.execute(sql)
            await db.commit()
            logger.debug("Migration done: added column %s to servers", col_name)
        except aiosqlite.OperationalError:
            logger.debug("Migration skip: column %s already exists in servers", col_name)
    # Migration: add avg_response_ms to server_daily_stats
    try:
        await db.execute(
            "ALTER TABLE server_daily_stats ADD COLUMN avg_response_ms REAL"
        )
        await db.commit()
        logger.debug("Migration done: added avg_response_ms to server_daily_stats")
    except aiosqlite.OperationalError:
        logger.debug("Migration skip: avg_response_ms already exists in server_daily_stats")
    # Migration: rebuild servers table to add public_ip to type CHECK constraint.
    # Detects by absence of 'public_ip' in the current table DDL.
    try:
        async with db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='servers'"
        ) as cur:
            row = await cur.fetchone()
        table_sql = row[0] if row else ""
        if "'public_ip'" not in table_sql:
            await _rebuild_servers(db, "_servers_v3", """
                CREATE TABLE servers (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    name              TEXT    NOT NULL,
                    address           TEXT    NOT NULL,
                    port              INTEGER,
                    type              TEXT    NOT NULL
                                      CHECK(type IN ('http', 'ping', 'tcp', 'http_keyword', 'public_ip')),
                    status            TEXT    NOT NULL DEFAULT 'UP'
                                      CHECK(status IN ('UP', 'DOWN')),
                    uptime_percent    REAL    NOT NULL DEFAULT 100.0,
                    total_checks      INTEGER NOT NULL DEFAULT 0,
                    successful_checks INTEGER NOT NULL DEFAULT 0,
                    last_error        TEXT,
                    last_checked      TEXT,
                    maintenance_mode  INTEGER NOT NULL DEFAULT 0,
                    position          INTEGER NOT NULL DEFAULT 0,
                    check_params      TEXT,
                    last_response_ms  INTEGER,
                    ssl_expiry_date   TEXT
                )
            """, """
                INSERT INTO servers
                SELECT id, name, address, port, type, status, uptime_percent,
                       total_checks, successful_checks, last_error, last_checked,
                       maintenance_mode, position, check_params,
                       last_response_ms, ssl_expiry_date
                FROM _servers_v3
            """, "servers table rebuilt with public_ip type + latency/SSL columns")
    except Exception as exc:
        logger.warning("Migration (servers rebuild for public_ip) failed: %s", exc)
