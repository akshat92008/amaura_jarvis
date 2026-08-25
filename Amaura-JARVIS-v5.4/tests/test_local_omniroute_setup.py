import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "Setup_Amaura_OmniRoute.command"


def test_setup_defaults_to_local_omniroute_gateway() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'default="http://localhost:20128/v1"' in text
    assert 'default="https://api.omniroute.ai/v1"' not in text


def test_setup_accepts_dashboard_client_keys_and_fails_closed_without_models() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "if not api_key:" in text
    assert "if len(api_key) < 8" not in text
    assert "advertises zero models" in text
    assert "connect at least one provider" in text


def test_setup_discovers_models_before_asking_for_routes() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    discovery = text.index('Step 4/5 — Live gateway model discovery')
    route_selection = text.index('Step 5/5 — Production model routes')
    probe = text.index("probe = _probe_omniroute(base_url, api_key)")
    primary_prompt = text.index('Primary worker/reasoning model')
    assert discovery < probe < route_selection < primary_prompt
    assert "mistral-large-latest" not in text
    assert "z-ai/glm-5.2" not in text


def test_setup_filters_dynamic_aliases_from_governed_choices() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "def _concrete_models" in text
    assert "not _dynamic_selector(model)" in text
    assert "At least two concrete model IDs are required" in text
    assert "Dynamic auto/best/default aliases cannot serve as the independent reviewer" in text


def test_setup_uses_numbered_live_model_picker() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "def _resolve_model_choice" in text
    assert "number or exact ID" in text
    assert "Select concrete routes by number" in text
    assert "Independent reviewer must differ from every worker route" in text


def test_setup_verifies_selected_routes_exist_before_writing_config() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "missing = [model for model in selected if model not in models]" in text
    assert "Every selected production route exists in the live gateway" in text
    assert text.index("missing = [model for model in selected if model not in models]") < text.index(
        "env_path = _write_env"
    )
