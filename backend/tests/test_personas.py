from app.personas import PERSONAS, get_persona


def test_known_personas_exist():
    assert "jazz" in PERSONAS
    assert "bank" in PERSONAS


def test_get_persona_unknown_returns_none():
    assert get_persona("nonexistent") is None


def test_system_prompt_mentions_company_and_no_real_data_rule():
    persona = get_persona("jazz")
    prompt = persona.system_prompt
    assert "Jazz" in prompt
    assert "demo" in prompt.lower()
    assert "*111#" in prompt  # a concrete grounded fact should be present
