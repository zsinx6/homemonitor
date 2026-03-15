"""Tests for app/domain/server.py — uptime calculation and state transitions."""
from app.domain.server import (
    compute_uptime_percent,
    detect_state_transitions,
    ServerCheckResult,
)


class TestComputeUptimePercent:
    def test_all_successful(self):
        assert compute_uptime_percent(total=100, successful=100) == 100.0

    def test_none_successful(self):
        assert compute_uptime_percent(total=100, successful=0) == 0.0

    def test_partial(self):
        assert compute_uptime_percent(total=10, successful=9) == 90.0

    def test_zero_total_returns_zero(self):
        assert compute_uptime_percent(total=0, successful=0) == 0.0

    def test_rounds_to_two_decimals(self):
        result = compute_uptime_percent(total=3, successful=2)
        assert result == round(2 / 3 * 100, 2)


class TestDetectStateTransitions:
    """
    detect_state_transitions(previous_statuses, current_statuses) returns
    (newly_down: list[str], newly_up: list[str])
    where keys are server names and values are "UP" or "DOWN".
    """

    def test_no_change(self):
        prev = {"nginx": "UP", "db": "UP"}
        curr = {"nginx": "UP", "db": "UP"}
        down, up = detect_state_transitions(prev, curr)
        assert down == []
        assert up == []

    def test_server_goes_down(self):
        prev = {"nginx": "UP"}
        curr = {"nginx": "DOWN"}
        down, up = detect_state_transitions(prev, curr)
        assert "nginx" in down
        assert up == []

    def test_server_recovers(self):
        prev = {"nginx": "DOWN"}
        curr = {"nginx": "UP"}
        down, up = detect_state_transitions(prev, curr)
        assert "nginx" in up
        assert down == []

    def test_mixed_transitions(self):
        prev = {"nginx": "UP", "db": "DOWN", "redis": "UP"}
        curr = {"nginx": "DOWN", "db": "UP", "redis": "UP"}
        down, up = detect_state_transitions(prev, curr)
        assert "nginx" in down
        assert "db" in up
        assert "redis" not in down
        assert "redis" not in up

    def test_new_server_already_down_is_not_transition(self):
        prev = {}
        curr = {"nginx": "DOWN"}
        down, up = detect_state_transitions(prev, curr)
        assert down == []

    def test_returns_lists_not_sets(self):
        prev = {"a": "UP"}
        curr = {"a": "DOWN"}
        down, up = detect_state_transitions(prev, curr)
        assert isinstance(down, list)
        assert isinstance(up, list)


class TestServerCheckResult:
    def test_up_result(self):
        r = ServerCheckResult(server_id=1, name="nginx", is_up=True, error=None)
        assert r.is_up is True
        assert r.error is None

    def test_down_result_has_error(self):
        r = ServerCheckResult(server_id=1, name="nginx", is_up=False, error="timeout")
        assert r.is_up is False
        assert r.error == "timeout"
