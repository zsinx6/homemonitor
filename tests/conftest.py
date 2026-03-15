"""Shared test fixtures: in-memory aiosqlite DB and async HTTP client."""
from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite
from httpx import AsyncClient, ASGITransport

from app.infrastructure.database import init_db
from app.main import create_app


@pytest.fixture(autouse=True)
def restore_constants():
    """Snapshot and restore app.domain.constants after each test.

    This prevents load_config() calls in one test from bleeding numeric
    overrides into subsequent tests.
    """
    import app.domain.constants as C  # noqa: PLC0415
    snapshot = {k: getattr(C, k) for k in dir(C) if k.isupper() and not k.startswith("_")}
    yield
    for k, v in snapshot.items():
        setattr(C, k, v)


@pytest_asyncio.fixture
async def db():
    """In-memory aiosqlite DB, schema created and pet seeded."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        yield conn


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client backed by a temp-file SQLite DB (needed for lifespan)."""
    db_path = str(tmp_path / "test.db")
    # Pre-initialise the DB so the app lifespan just opens it
    async with aiosqlite.connect(db_path) as conn:
        await init_db(conn)

    app = create_app(db_path=db_path)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
