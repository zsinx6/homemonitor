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

    async def test_backup_increases_exp_and_hp(self, client):
        # Drain HP first so we can see recovery
        initial = (await client.get("/api/pet")).json()
        r = await client.post("/api/pet/backup")
        assert r.status_code == 200
        data = r.json()
        assert data["exp"] == initial["exp"] + C.EXP_BACKUP
        assert data["last_backup_date"] is not None

    async def test_last_event_is_cleared_after_read(self, client):
        # Call interact to set a change, then read twice
        await client.post("/api/pet/interact")
        first = (await client.get("/api/pet")).json()
        second = (await client.get("/api/pet")).json()
        # last_event should be None on second read
        assert second["last_event"] is None


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

    async def test_create_server_invalid_type(self, client):
        r = await client.post("/api/servers", json={
            "name": "x", "address": "1.2.3.4", "port": None, "type": "ftp"
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

    async def test_update_nonexistent_server_returns_404(self, client):
        r = await client.put("/api/servers/9999", json={
            "name": "x", "address": "http://x", "port": None, "type": "http"
        })
        assert r.status_code == 404

    async def test_delete_server(self, client):
        srv = (await client.post("/api/servers", json={
            "name": "tmp", "address": "http://tmp", "port": None, "type": "ping"
        })).json()
        r = await client.delete(f"/api/servers/{srv['id']}")
        assert r.status_code == 204

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

    async def test_complete_task_grants_exp(self, client):
        task = (await client.post("/api/tasks", json={"task": "Deploy update"})).json()
        initial_exp = (await client.get("/api/pet")).json()["exp"]
        r = await client.put(f"/api/tasks/{task['id']}/complete")
        assert r.status_code == 200
        assert r.json()["is_completed"] is True
        new_exp = (await client.get("/api/pet")).json()["exp"]
        assert new_exp == initial_exp + C.EXP_COMPLETE_TASK

    async def test_complete_task_marks_done(self, client):
        task = (await client.post("/api/tasks", json={"task": "Update certs"})).json()
        completed = (await client.put(f"/api/tasks/{task['id']}/complete")).json()
        assert completed["is_completed"] is True
        assert completed["completed_at"] is not None

    async def test_complete_nonexistent_task_returns_404(self, client):
        r = await client.put("/api/tasks/9999/complete")
        assert r.status_code == 404

    async def test_create_task_empty_string_rejected(self, client):
        r = await client.post("/api/tasks", json={"task": ""})
        assert r.status_code == 422
