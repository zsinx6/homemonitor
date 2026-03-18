"""Tests for context_service.build_snapshot."""
from __future__ import annotations

import pytest

from app.domain import constants as C


class TestContextService:
    async def test_snapshot_structure(self, client):
        """build_snapshot via GET /api/status returns all expected fields."""
        r = await client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) >= {"pet", "infrastructure", "tasks", "maintenance", "generated_at"}

    async def test_snapshot_pet_initial_state(self, client):
        pet = (await client.get("/api/status")).json()["pet"]
        assert pet["level"] == 1
        assert pet["hp"] == C.HP_MAX
        assert pet["exp"] == 0
        assert pet["is_dead"] is False
        assert pet["species"] == "Bitmon"
        assert pet["stage"] == "fresh"

    async def test_snapshot_infra_empty(self, client):
        infra = (await client.get("/api/status")).json()["infrastructure"]
        assert infra["servers_total"] == 0
        assert infra["servers_up"] == 0
        assert infra["servers_down"] == 0
        assert infra["down_servers"] == []

    async def test_snapshot_tasks_empty(self, client):
        tasks = (await client.get("/api/status")).json()["tasks"]
        assert tasks["pending"] == 0
        assert tasks["completed_total"] == 0

    async def test_snapshot_backup_never_run(self, client):
        maint = (await client.get("/api/status")).json()["maintenance"]
        assert maint["days_since_backup"] is None

    async def test_snapshot_reflects_new_server(self, client):
        await client.post("/api/servers", json={
            "name": "db", "address": "192.168.1.10", "type": "ping"
        })
        infra = (await client.get("/api/status")).json()["infrastructure"]
        assert infra["servers_total"] == 1

    async def test_snapshot_reflects_pending_task(self, client):
        await client.post("/api/tasks", json={"task": "Deploy nginx"})
        tasks = (await client.get("/api/status")).json()["tasks"]
        assert tasks["pending"] >= 1

    async def test_snapshot_to_prompt_text_not_empty(self, client):
        """Verify the prompt text helper produces meaningful output via the context service."""
        from app.services.context_service import ContextSnapshot
        from datetime import datetime, timezone
        snapshot = ContextSnapshot(
            pet_name="Bitmon", pet_level=1, pet_species="Bitmon", pet_stage="fresh",
            pet_hp=10, pet_hp_max=10, pet_exp=0, pet_max_exp=100,
            pet_status="happy", pet_is_dead=False, pet_mood="Energetic",
            servers_total=2, servers_up=1, servers_down=1, servers_maintenance=0,
            down_server_names=["nginx"], overall_uptime_pct=72.3,
            tasks_pending=3, tasks_completed_total=5,
            days_since_backup=2,
            generated_at=datetime.now(timezone.utc),
        )
        text = snapshot.to_prompt_text()
        assert "Bitmon" in text
        assert "nginx" in text
        assert "72.3" in text
        assert "3 pending" in text
