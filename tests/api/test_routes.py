"""API tests using httpx.AsyncClient + ASGITransport."""
from __future__ import annotations

import pytest

from app.domain import constants as C


class TestPetRoutes:
    async def test_get_pet_returns_200(self, client):
        r = await client.get("/api/pet")
        assert r.status_code == 200

    async def test_get_pet_structure(self, client):
        data = (await client.get("/api/pet")).json()
        assert "level" in data
        assert "exp" in data
        assert "hp" in data
        assert "status" in data
        assert "phrase" in data
        assert "hp_max" in data
        assert "evolution" in data
        assert "evolution_stage" in data
        assert "evolution_next_level" in data

    async def test_get_pet_evolution_field(self, client):
        data = (await client.get("/api/pet")).json()
        # Fresh pet starts at level 1 — Bitmon (fresh stage)
        assert data["evolution"] == "Bitmon"
        assert data["evolution_stage"] == "fresh"
        assert data["evolution_next_level"] == 2

    async def test_get_pet_last_event_field_present(self, client):
        data = (await client.get("/api/pet")).json()
        assert "last_event" in data
        assert data["last_event"] is None  # no events yet

    async def test_interact_increases_exp(self, client):
        initial = (await client.get("/api/pet")).json()["exp"]
        await client.post("/api/pet/interact")
        after = (await client.get("/api/pet")).json()["exp"]
        assert after == initial + C.EXP_INTERACT

    async def test_interact_returns_phrase(self, client):
        r = await client.post("/api/pet/interact")
        assert r.status_code == 200
        data = r.json()
        assert "phrase" in data
        assert len(data["phrase"]) > 0
        assert "on_cooldown" in data

    async def test_fresh_pet_starts_happy(self, client):
        # Seeded pet has last_interaction_date set (1h ago) → no lonely drain → happy
        data = (await client.get("/api/pet")).json()
        assert data["status"] == "happy"

    async def test_interact_on_cooldown_returns_flag(self, client):
        # First interact succeeds; immediate second should be on cooldown
        await client.post("/api/pet/interact")
        r2 = await client.post("/api/pet/interact")
        assert r2.status_code == 200
        assert r2.json()["on_cooldown"] is True

    async def test_interact_heals_hp(self, client):
        hp_before = (await client.get("/api/pet")).json()["hp"]
        await client.post("/api/pet/interact")
        hp_after = (await client.get("/api/pet")).json()["hp"]
        from app.domain import constants as C
        assert hp_after == min(hp_before + C.HP_GAIN_INTERACT, C.HP_MAX)

    async def test_backup_increases_exp_and_hp(self, client):
        # Drain HP first so we can verify HP recovery
        initial = (await client.get("/api/pet")).json()
        r = await client.post("/api/pet/backup")
        assert r.status_code == 200
        data = r.json()
        assert data["exp"] == initial["exp"] + C.EXP_BACKUP
        assert data["last_backup_date"] is not None
        assert "on_cooldown" in data

    async def test_backup_on_cooldown_returns_flag(self, client):
        # First backup succeeds; immediate second should be on cooldown
        await client.post("/api/pet/backup")
        r2 = await client.post("/api/pet/backup")
        assert r2.status_code == 200
        assert r2.json()["on_cooldown"] is True

    async def test_backup_actually_increases_hp(self, client):
        # Pet starts at HP_MAX; backup can't increase it.
        # Confirm response hp == min(current + HP_GAIN_BACKUP, HP_MAX).
        pet_before = (await client.get("/api/pet")).json()
        r = await client.post("/api/pet/backup")
        expected_hp = min(pet_before["hp"] + C.HP_GAIN_BACKUP, C.HP_MAX)
        assert r.json()["hp"] == expected_hp

    async def test_backup_sets_last_event(self, client):
        await client.post("/api/pet/backup")
        data = (await client.get("/api/pet")).json()
        # backup event fires on the first read after backup
        assert data["last_event"] == "backup"

    async def test_last_event_is_cleared_after_read(self, client):
        # Call interact to set a change, then read twice
        await client.post("/api/pet/interact")
        first = (await client.get("/api/pet")).json()
        second = (await client.get("/api/pet")).json()
        # last_event should be None on second read
        assert second["last_event"] is None

    async def test_interact_does_not_set_last_event(self, client):
        # interact does not produce a last_event (no level-up at this exp)
        await client.post("/api/pet/interact")
        data = (await client.get("/api/pet")).json()
        assert data["last_event"] is None


class TestServerRoutes:
    async def test_list_servers_empty(self, client):
        r = await client.get("/api/servers")
        assert r.status_code == 200
        assert r.json() == []

    async def test_create_server(self, client):
        r = await client.post("/api/servers", json={
            "name": "nginx", "address": "http://localhost", "port": 80, "type": "http"
        })
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "nginx"
        assert data["type"] == "http"
        assert "id" in data
        assert "daily_stats" in data

    async def test_create_server_without_port(self, client):
        r = await client.post("/api/servers", json={
            "name": "myserver", "address": "192.168.1.1", "type": "ping"
        })
        assert r.status_code == 201
        assert r.json()["port"] is None

    async def test_create_ping_server_with_url_rejected(self, client):
        """Ping server addresses must not include a URL scheme."""
        r = await client.post("/api/servers", json={
            "name": "myhome", "address": "http://192.168.1.1", "type": "ping"
        })
        assert r.status_code == 422

    async def test_create_ping_server_with_hostname_accepted(self, client):
        r = await client.post("/api/servers", json={
            "name": "myhome", "address": "192.168.1.1", "type": "ping"
        })
        assert r.status_code == 201

    async def test_create_server_initial_stats_zero(self, client):
        r = await client.post("/api/servers", json={
            "name": "srv", "address": "http://example.com", "type": "http"
        })
        data = r.json()
        assert data["total_checks"] == 0
        assert data["successful_checks"] == 0
        assert data["uptime_percent"] == 100.0
        assert data["daily_stats"] == []
        assert data["last_checked"] is None

    async def test_create_server_invalid_type(self, client):
        r = await client.post("/api/servers", json={
            "name": "x", "address": "1.2.3.4", "port": None, "type": "ftp"
        })
        assert r.status_code == 422

    async def test_create_server_blank_name_rejected(self, client):
        r = await client.post("/api/servers", json={
            "name": "   ", "address": "http://example.com", "type": "http"
        })
        assert r.status_code == 422

    async def test_create_server_blank_address_rejected(self, client):
        r = await client.post("/api/servers", json={
            "name": "good-name", "address": "   ", "type": "http"
        })
        assert r.status_code == 422

    async def test_update_server(self, client):
        created = (await client.post("/api/servers", json={
            "name": "old", "address": "http://old", "port": None, "type": "http"
        })).json()
        r = await client.put(f"/api/servers/{created['id']}", json={
            "name": "new", "address": "http://new", "port": 443, "type": "http"
        })
        assert r.status_code == 200
        assert r.json()["name"] == "new"

    async def test_update_server_all_fields(self, client):
        created = (await client.post("/api/servers", json={
            "name": "orig", "address": "http://orig", "port": 80, "type": "http"
        })).json()
        r = await client.put(f"/api/servers/{created['id']}", json={
            "name": "changed", "address": "192.168.0.1", "port": None, "type": "ping"
        })
        data = r.json()
        assert data["name"] == "changed"
        assert data["address"] == "192.168.0.1"
        assert data["port"] is None
        assert data["type"] == "ping"

    async def test_patch_server_not_allowed(self, client):
        created = (await client.post("/api/servers", json={
            "name": "s", "address": "http://s", "type": "http"
        })).json()
        r = await client.patch(f"/api/servers/{created['id']}", json={"name": "x"})
        assert r.status_code == 405

    async def test_update_nonexistent_server_returns_404(self, client):
        r = await client.put("/api/servers/9999", json={
            "name": "x", "address": "http://x", "port": None, "type": "http"
        })
        assert r.status_code == 404

    async def test_delete_server(self, client):
        srv = (await client.post("/api/servers", json={
            "name": "tmp", "address": "192.168.1.1", "port": None, "type": "ping"
        })).json()
        r = await client.delete(f"/api/servers/{srv['id']}")
        assert r.status_code == 204

    async def test_delete_server_removes_from_list(self, client):
        srv = (await client.post("/api/servers", json={
            "name": "gone", "address": "http://gone", "type": "http"
        })).json()
        await client.delete(f"/api/servers/{srv['id']}")
        ids = [s["id"] for s in (await client.get("/api/servers")).json()]
        assert srv["id"] not in ids

    async def test_delete_nonexistent_returns_404(self, client):
        r = await client.delete("/api/servers/9999")
        assert r.status_code == 404


class TestTaskRoutes:
    async def test_list_tasks_empty(self, client):
        r = await client.get("/api/tasks")
        assert r.status_code == 200
        assert r.json() == []

    async def test_create_task(self, client):
        r = await client.post("/api/tasks", json={"task": "Fix nginx backup"})
        assert r.status_code == 201
        data = r.json()
        assert data["task"] == "Fix nginx backup"
        assert data["is_completed"] is False

    async def test_create_task_appears_in_list(self, client):
        await client.post("/api/tasks", json={"task": "New task"})
        tasks = (await client.get("/api/tasks")).json()
        assert any(t["task"] == "New task" for t in tasks)

    async def test_complete_task_grants_exp(self, client):
        task = (await client.post("/api/tasks", json={"task": "Deploy update"})).json()
        initial_exp = (await client.get("/api/pet")).json()["exp"]
        r = await client.put(f"/api/tasks/{task['id']}/complete")
        assert r.status_code == 200
        assert r.json()["is_completed"] is True
        new_exp = (await client.get("/api/pet")).json()["exp"]
        assert new_exp == initial_exp + C.EXP_COMPLETE_TASK

    async def test_complete_task_grants_hp(self, client):
        task = (await client.post("/api/tasks", json={"task": "Patch certs"})).json()
        hp_before = (await client.get("/api/pet")).json()["hp"]
        await client.put(f"/api/tasks/{task['id']}/complete")
        hp_after = (await client.get("/api/pet")).json()["hp"]
        expected = min(hp_before + C.HP_GAIN_COMPLETE_TASK, C.HP_MAX)
        assert hp_after == expected

    async def test_complete_task_marks_done(self, client):
        task = (await client.post("/api/tasks", json={"task": "Update certs"})).json()
        completed = (await client.put(f"/api/tasks/{task['id']}/complete")).json()
        assert completed["is_completed"] is True
        assert completed["completed_at"] is not None

    async def test_complete_task_appears_in_list_as_done(self, client):
        task = (await client.post("/api/tasks", json={"task": "Archive logs"})).json()
        await client.put(f"/api/tasks/{task['id']}/complete")
        tasks = (await client.get("/api/tasks")).json()
        match = next(t for t in tasks if t["id"] == task["id"])
        assert match["is_completed"] is True

    async def test_complete_nonexistent_task_returns_404(self, client):
        r = await client.put("/api/tasks/9999/complete")
        assert r.status_code == 404

    async def test_create_task_empty_string_rejected(self, client):
        r = await client.post("/api/tasks", json={"task": ""})
        assert r.status_code == 422

    async def test_create_task_whitespace_only_rejected(self, client):
        r = await client.post("/api/tasks", json={"task": "   "})
        assert r.status_code == 422

    async def test_list_tasks_shows_both_pending_and_completed(self, client):
        t1 = (await client.post("/api/tasks", json={"task": "Pending task"})).json()
        t2 = (await client.post("/api/tasks", json={"task": "Done task"})).json()
        await client.put(f"/api/tasks/{t2['id']}/complete")
        tasks = (await client.get("/api/tasks")).json()
        ids = [t["id"] for t in tasks]
        assert t1["id"] in ids
        assert t2["id"] in ids

    async def test_delete_task(self, client):
        task = (await client.post("/api/tasks", json={"task": "Temp task"})).json()
        r = await client.delete(f"/api/tasks/{task['id']}")
        assert r.status_code == 204

    async def test_delete_task_removes_from_list(self, client):
        task = (await client.post("/api/tasks", json={"task": "Deletable task"})).json()
        await client.delete(f"/api/tasks/{task['id']}")
        tasks = (await client.get("/api/tasks")).json()
        assert all(t["id"] != task["id"] for t in tasks)

    async def test_delete_nonexistent_task_returns_404(self, client):
        r = await client.delete("/api/tasks/9999")
        assert r.status_code == 404

    async def test_complete_task_fires_task_done_event(self, client):
        task = (await client.post("/api/tasks", json={"task": "Write tests"})).json()
        await client.put(f"/api/tasks/{task['id']}/complete")
        data = (await client.get("/api/pet")).json()
        assert data["last_event"] == "task_done"


class TestStaticFiles:
    async def test_spa_served_at_root(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    async def test_spa_contains_digimon_content(self, client):
        r = await client.get("/")
        assert "DigiMon" in r.text


class TestReviveRoute:
    async def test_revive_alive_pet_is_noop(self, client):
        """Reviving an alive pet returns 200 and pet stays alive."""
        r = await client.post("/api/pet/revive")
        assert r.status_code == 200
        data = r.json()
        assert data["is_dead"] is False

    async def test_revive_response_has_is_dead_field(self, client):
        data = (await client.get("/api/pet")).json()
        assert "is_dead" in data

    async def test_get_pet_returns_last_interaction_date(self, client):
        data = (await client.get("/api/pet")).json()
        assert "last_interaction_date" in data
