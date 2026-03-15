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


class TestPersonalityConfig:
    """PersonalityConfig.to_prompt() shapes LLM system prompts."""

    def test_imports_without_error(self):
        from app.infrastructure.config import PersonalityConfig  # noqa: F401

    def test_default_tone_is_serious(self):
        from app.infrastructure.config import PersonalityConfig
        p = PersonalityConfig()
        assert p.tone == "serious"

    def test_to_prompt_contains_tone_description(self):
        from app.infrastructure.config import PersonalityConfig
        p = PersonalityConfig(tone="cheerful")
        prompt = p.to_prompt()
        assert "cheerful" in prompt or "upbeat" in prompt

    def test_to_prompt_contains_backstory(self):
        from app.infrastructure.config import PersonalityConfig
        p = PersonalityConfig(backstory="Born in a kernel panic.")
        assert "kernel panic" in p.to_prompt()

    def test_to_prompt_contains_quirks(self):
        from app.infrastructure.config import PersonalityConfig
        p = PersonalityConfig(quirks="Always says 'sudo'.")
        assert "sudo" in p.to_prompt()

    def test_to_prompt_all_tones_valid(self):
        from app.infrastructure.config import PersonalityConfig, TONE_DESCRIPTIONS
        for tone in TONE_DESCRIPTIONS:
            p = PersonalityConfig(tone=tone)
            prompt = p.to_prompt()
            assert len(prompt) > 20

    def test_initial_name_defaults_none(self):
        from app.infrastructure.config import PersonalityConfig
        assert PersonalityConfig().initial_name is None

    def test_initial_name_can_be_set(self):
        from app.infrastructure.config import PersonalityConfig
        p = PersonalityConfig(initial_name="Sparky")
        assert p.initial_name == "Sparky"


class TestLoadConfigPersonality:
    """load_config() populates AppConfig.personality correctly."""

    def test_default_personality_when_no_file(self, tmp_path):
        from app.infrastructure.config import load_config, PersonalityConfig
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert isinstance(cfg.personality, PersonalityConfig)
        assert cfg.personality.tone == "serious"

    def test_personality_loaded_from_toml(self, tmp_path):
        toml = tmp_path / "test.toml"
        toml.write_text(
            '[personality]\ntone = "grumpy"\nbackstory = "From the void."\n',
            encoding="utf-8",
        )
        from app.infrastructure.config import load_config
        cfg = load_config(toml)
        assert cfg.personality.tone == "grumpy"
        assert cfg.personality.backstory == "From the void."

    def test_personality_initial_name_loaded(self, tmp_path):
        toml = tmp_path / "test.toml"
        toml.write_text('[personality]\ninitial_name = "Sparky"\n', encoding="utf-8")
        from app.infrastructure.config import load_config
        cfg = load_config(toml)
        assert cfg.personality.initial_name == "Sparky"

    def test_missing_personality_section_uses_defaults(self, tmp_path):
        toml = tmp_path / "test.toml"
        toml.write_text("[game]\nhp_max = 20\n", encoding="utf-8")
        from app.infrastructure.config import load_config
        cfg = load_config(toml)
        assert cfg.personality.tone == "serious"
