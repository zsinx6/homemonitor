"""Tests for phrase selection and LLM interface."""
import pytest

from app.domain.phrases import PhraseContext, PhraseSelector
from app.domain.static_phrase_service import StaticPhraseService


@pytest.fixture
def selector() -> PhraseSelector:
    return StaticPhraseService()


class TestPhraseContextPriority:
    """PhraseSelector.select() should return a non-empty string for every context."""

    @pytest.mark.parametrize("context", list(PhraseContext))
    async def test_returns_string_for_all_contexts(self, selector, context):
        phrase = await selector.select(context, variables={})
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    async def test_alert_includes_server_name(self, selector):
        phrase = await selector.select(
            PhraseContext.SERVER_DOWN, variables={"server_name": "postgres"}
        )
        assert "postgres" in phrase

    async def test_level_up_includes_level(self, selector):
        phrase = await selector.select(
            PhraseContext.LEVEL_UP, variables={"level": 5}
        )
        assert "5" in phrase

    async def test_recovery_includes_server_name(self, selector):
        phrase = await selector.select(
            PhraseContext.RECOVERY, variables={"server_name": "nginx"}
        )
        assert "nginx" in phrase

    async def test_happy_phrase_not_empty(self, selector):
        phrase = await selector.select(PhraseContext.HAPPY, variables={})
        assert len(phrase) > 0
