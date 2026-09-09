from app.company_profile import EXAMPLE_TEMPLATES, build_system_prompt, default_greeting, greeting_cache_key


def test_build_system_prompt_mentions_company_and_no_real_data_rule():
    prompt = build_system_prompt("Acme Widgets", "Acme sells widgets. Support line: 555-0100.")
    assert "Acme Widgets" in prompt
    assert "555-0100" in prompt  # the supplied detail is actually included
    assert "human agent" in prompt.lower()  # the handoff rule survives


def test_build_system_prompt_works_for_any_company_not_just_examples():
    # The whole point of this module: no fixed list of supported
    # companies - anything the user types in produces a usable prompt.
    prompt = build_system_prompt("Zylo Airlines", "Zylo flies domestic routes. Baggage limit: 20kg.")
    assert "Zylo Airlines" in prompt
    assert "20kg" in prompt


def test_build_system_prompt_handles_empty_details_gracefully():
    prompt = build_system_prompt("Mystery Co", "")
    assert "Mystery Co" in prompt
    assert "no specific details" in prompt.lower()


def test_build_system_prompt_handles_empty_name_gracefully():
    prompt = build_system_prompt("", "Some details.")
    assert "this company" in prompt.lower()


def test_default_greeting_uses_company_name():
    assert default_greeting("Acme Widgets") == "Thank you for calling Acme Widgets. How can I help you today?"


def test_default_greeting_handles_empty_name():
    assert "our company" in default_greeting("").lower()


def test_greeting_cache_key_is_stable_and_case_insensitive():
    assert greeting_cache_key("Acme Widgets") == greeting_cache_key("acme widgets")
    assert greeting_cache_key("Acme Widgets") == greeting_cache_key("  Acme Widgets  ")


def test_greeting_cache_key_differs_for_different_names():
    assert greeting_cache_key("Acme Widgets") != greeting_cache_key("Zylo Airlines")


def test_example_templates_are_well_formed():
    assert len(EXAMPLE_TEMPLATES) >= 2
    for template in EXAMPLE_TEMPLATES:
        assert template["name"].strip()
        assert template["details"].strip()
