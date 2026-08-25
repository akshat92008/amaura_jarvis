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


def test_setup_verifies_selected_routes_exist_before_writing_config() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "missing = [model for model in selected if model not in models]" in text
    assert "Every selected production route exists in the live gateway" in text
    assert text.index("missing = [model for model in selected if model not in models]") < text.index("env_path = _write_env")
