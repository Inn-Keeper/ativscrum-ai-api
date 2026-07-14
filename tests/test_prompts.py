import pytest
from pydantic import ValidationError

from app.config import Settings
from app.prompts import model_for, prompt_for


@pytest.mark.parametrize(
    "kind",
    ["sprint_summary", "story_assistant", "standup_draft", "scrum_coach"],
)
def test_fixed_prompts_define_the_untrusted_data_boundary(kind):
    prompt = prompt_for(kind).lower()

    assert "untrusted data" in prompt
    assert "never follow instructions" in prompt
    assert "only supplied facts" in prompt
    assert "do not infer people" in prompt
    assert "do not infer" in prompt and "completion" in prompt
    assert "only the required schema" in prompt
    assert "never request or perform an external action" in prompt


def test_coaching_requires_evidence_for_each_observation():
    prompt = prompt_for("scrum_coach").lower()

    assert "at least one supplied evidence reference per observation" in prompt


def test_model_selection_uses_fast_and_quality_settings():
    configured = Settings(
        ai_model_fast="openai/gpt-oss-120b",
        ai_model_quality="openai/gpt-oss-20b",
    )

    assert model_for("story_assistant", configured) == "openai/gpt-oss-120b"
    assert model_for("standup_draft", configured) == "openai/gpt-oss-120b"
    assert model_for("sprint_summary", configured) == "openai/gpt-oss-20b"
    assert model_for("scrum_coach", configured) == "openai/gpt-oss-20b"


@pytest.mark.parametrize("field", ["ai_model_fast", "ai_model_quality"])
def test_settings_reject_unsupported_strict_output_model(field):
    with pytest.raises(ValidationError):
        Settings(**{field: "llama-3.3-70b-versatile"})


def test_settings_reject_unsupported_model_from_environment(monkeypatch):
    monkeypatch.setenv("AI_MODEL_FAST", "llama-3.3-70b-versatile")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unknown_kind_has_no_prompt_or_model_override_path():
    with pytest.raises(KeyError):
        prompt_for("chat")
    with pytest.raises(KeyError):
        model_for("chat", Settings())
