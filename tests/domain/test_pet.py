"""Tests for app/domain/pet.py — pure pet logic, zero I/O."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import constants as C
from app.domain.pet import (
    Pet,
    apply_monitor_cycle,
    apply_interact,
    apply_complete_task,
    apply_backup,
    derive_status,
    LevelUpResult,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pet(**kwargs) -> Pet:
    defaults = dict(
        id=1,
        name="Agumon",
        level=1,
        exp=0,
        max_exp=C.INITIAL_MAX_EXP,
        hp=C.HP_MAX,
        last_backup_date=None,
        last_interaction_date=_now(),
        last_event=None,
        last_updated=_now(),
    )
    defaults.update(kwargs)
    return Pet(**defaults)


# ---------------------------------------------------------------------------
# derive_status
# ---------------------------------------------------------------------------

class TestDeriveStatus:
    def test_happy_when_healthy_and_servers_up_and_interacted_recently(self):
        pet = _pet(hp=C.HP_HAPPY_THRESHOLD)
        assert derive_status(pet, any_server_down=False) == "happy"

    def test_lonely_when_healthy_but_no_recent_interaction(self):
        old = _now() - timedelta(hours=C.LONELINESS_HOURS + 1)
        pet = _pet(hp=C.HP_HAPPY_THRESHOLD, last_interaction_date=old)
        assert derive_status(pet, any_server_down=False) == "lonely"

    def test_lonely_when_no_interaction_at_all(self):
        pet = _pet(hp=C.HP_HAPPY_THRESHOLD, last_interaction_date=None)
        assert derive_status(pet, any_server_down=False) == "lonely"

    def test_sad_when_any_server_down_regardless_of_hp(self):
        pet = _pet(hp=C.HP_MAX)
        assert derive_status(pet, any_server_down=True) == "sad"

    def test_sad_when_hp_in_mid_range(self):
        pet = _pet(hp=C.HP_SAD_THRESHOLD)
        assert derive_status(pet, any_server_down=False) == "sad"

    def test_injured_when_hp_low(self):
        pet = _pet(hp=3)
        assert derive_status(pet, any_server_down=False) == "injured"

    def test_critical_when_hp_zero(self):
        pet = _pet(hp=0)
        assert derive_status(pet, any_server_down=False) == "critical"

    def test_injured_overrides_server_down_check(self):
        """Injured/critical status should take priority over 'sad'."""
        pet = _pet(hp=1)
        assert derive_status(pet, any_server_down=True) == "injured"


# ---------------------------------------------------------------------------
# apply_monitor_cycle
# ---------------------------------------------------------------------------

class TestApplyMonitorCycle:
    def test_gains_exp_when_all_up(self):
        pet = _pet(exp=0, hp=C.HP_MAX)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert result.exp == C.EXP_PER_HEALTHY_CYCLE

    def test_loses_hp_when_any_down(self):
        pet = _pet(hp=C.HP_MAX)
        result = apply_monitor_cycle(pet, down_server_names=["nginx"], recovered_server_names=[])
        assert result.hp == C.HP_MAX - C.HP_LOSS_PER_DOWN_CYCLE

    def test_no_exp_gain_when_server_down(self):
        pet = _pet(exp=0, hp=C.HP_MAX)
        result = apply_monitor_cycle(pet, down_server_names=["db"], recovered_server_names=[])
        assert result.exp == 0

    def test_hp_does_not_go_below_minimum(self):
        pet = _pet(hp=1)
        result = apply_monitor_cycle(pet, down_server_names=["x", "y"], recovered_server_names=[])
        assert result.hp == C.HP_MIN

    def test_recovery_grants_hp(self):
        pet = _pet(hp=5)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=["nginx"])
        assert result.hp == 5 + C.HP_GAIN_ON_RECOVERY

    def test_recovery_does_not_exceed_hp_max(self):
        pet = _pet(hp=C.HP_MAX)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=["nginx"])
        assert result.hp == C.HP_MAX

    def test_recovery_sets_last_event(self):
        pet = _pet(hp=5)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=["x"])
        assert result.last_event == "recovery"

    def test_server_down_sets_last_event(self):
        pet = _pet(hp=C.HP_MAX)
        result = apply_monitor_cycle(pet, down_server_names=["db"], recovered_server_names=[])
        assert result.last_event == "server_down"

    def test_exp_does_not_go_below_minimum(self):
        pet = _pet(exp=0)
        result = apply_monitor_cycle(pet, down_server_names=["x"], recovered_server_names=[])
        assert result.exp == C.EXP_MIN

    def test_backup_overdue_drains_hp(self):
        overdue = _now() - timedelta(days=C.BACKUP_OVERDUE_DAYS + 1)
        pet = _pet(hp=C.HP_MAX, last_backup_date=overdue)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        # All UP gives +1 EXP; overdue backup drains HP
        assert result.hp == C.HP_MAX - C.HP_DRAIN_BACKUP_OVERDUE

    def test_no_backup_drain_when_recent(self):
        recent = _now() - timedelta(days=C.BACKUP_OVERDUE_DAYS - 1)
        pet = _pet(hp=C.HP_MAX, last_backup_date=recent)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert result.hp == C.HP_MAX


# ---------------------------------------------------------------------------
# Level-up logic
# ---------------------------------------------------------------------------

class TestLevelUp:
    def test_level_up_when_exp_reaches_max(self):
        pet = _pet(level=1, exp=C.INITIAL_MAX_EXP - 1, max_exp=C.INITIAL_MAX_EXP)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert result.level == 2

    def test_level_up_carries_over_excess_exp(self):
        # Starting exp is 5 above the trigger point.
        # After gaining 1 EXP: total = max_exp + excess → carry-over = excess.
        excess = 5
        pet = _pet(level=1, exp=C.INITIAL_MAX_EXP - C.EXP_PER_HEALTHY_CYCLE + excess,
                   max_exp=C.INITIAL_MAX_EXP)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert result.level == 2
        assert result.exp == excess

    def test_level_up_scales_max_exp(self):
        pet = _pet(level=1, exp=C.INITIAL_MAX_EXP - C.EXP_PER_HEALTHY_CYCLE,
                   max_exp=C.INITIAL_MAX_EXP)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        expected_new_max = round(C.INITIAL_MAX_EXP * C.LEVEL_UP_SCALE)
        assert result.max_exp == expected_new_max

    def test_level_up_sets_last_event(self):
        pet = _pet(level=1, exp=C.INITIAL_MAX_EXP - C.EXP_PER_HEALTHY_CYCLE,
                   max_exp=C.INITIAL_MAX_EXP)
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert result.last_event == "level_up"

    def test_level_up_result_carries_excess(self):
        pet = _pet(level=1, exp=C.INITIAL_MAX_EXP - 1, max_exp=C.INITIAL_MAX_EXP)
        # gain 1 → total = max_exp → carried over = 0
        result = apply_monitor_cycle(pet, down_server_names=[], recovered_server_names=[])
        assert result.exp == 0

    def test_carry_over_large_gain(self):
        pet = _pet(level=1, exp=0, max_exp=10)
        # Manually apply large EXP gain
        result = apply_interact(pet)
        # EXP_INTERACT=2, max_exp=10 → should not level up
        assert result.level == 1
        assert result.exp == C.EXP_INTERACT


# ---------------------------------------------------------------------------
# apply_interact
# ---------------------------------------------------------------------------

class TestApplyInteract:
    def test_gains_exp(self):
        pet = _pet(exp=0)
        result = apply_interact(pet)
        assert result.exp == C.EXP_INTERACT

    def test_updates_last_interaction_date(self):
        old = _now() - timedelta(hours=48)
        pet = _pet(last_interaction_date=old)
        result = apply_interact(pet)
        assert result.last_interaction_date > old

    def test_exp_floor_respected(self):
        pet = _pet(exp=0)
        result = apply_interact(pet)
        assert result.exp >= C.EXP_MIN


# ---------------------------------------------------------------------------
# apply_complete_task
# ---------------------------------------------------------------------------

class TestApplyCompleteTask:
    def test_gains_exp(self):
        pet = _pet(exp=0)
        result = apply_complete_task(pet)
        assert result.exp == C.EXP_COMPLETE_TASK

    def test_gains_hp(self):
        pet = _pet(hp=5)
        result = apply_complete_task(pet)
        assert result.hp == 5 + C.HP_GAIN_COMPLETE_TASK

    def test_hp_does_not_exceed_max(self):
        pet = _pet(hp=C.HP_MAX)
        result = apply_complete_task(pet)
        assert result.hp == C.HP_MAX


# ---------------------------------------------------------------------------
# apply_backup
# ---------------------------------------------------------------------------

class TestApplyBackup:
    def test_gains_exp(self):
        pet = _pet(exp=0)
        result = apply_backup(pet)
        assert result.exp == C.EXP_BACKUP

    def test_gains_hp(self):
        pet = _pet(hp=0)
        result = apply_backup(pet)
        assert result.hp == min(C.HP_GAIN_BACKUP, C.HP_MAX)

    def test_hp_does_not_exceed_max(self):
        pet = _pet(hp=C.HP_MAX)
        result = apply_backup(pet)
        assert result.hp == C.HP_MAX

    def test_sets_backup_date(self):
        pet = _pet(last_backup_date=None)
        result = apply_backup(pet)
        assert result.last_backup_date is not None

    def test_sets_last_event(self):
        pet = _pet()
        result = apply_backup(pet)
        assert result.last_event == "backup"
