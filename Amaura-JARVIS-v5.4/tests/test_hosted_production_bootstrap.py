from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.amaura.evaluation import evaluation_pack_status
from scripts import bootstrap_hosted_production as bootstrap


def _omniroute_profile() -> dict[str, str]:
    return {
        "AMAURA_OMNIROUTE_BASE_URL": "https://api.omniroute.ai/v1",
        "AMAURA_OMNIROUTE_API_KEY": "omni-test-secret",
        "AMAURA_OMNIROUTE_MODEL": "mistral-large-latest",
        "AMAURA_OMNIROUTE_CHAT_MODEL": "mistral-large-latest",
        "AMAURA_OMNIROUTE_REVIEW_MODEL": "z-ai/glm-5.2",
        "AMAURA_OMNIROUTE_FALLBACK_MODEL": "",
        "AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL": "",
    }


def test_private_eval_pack_is_authenticated_and_unseen(tmp_path: Path) -> None:
    key = "k" * 48
    target = tmp_path / "private-eval.json"

    result = bootstrap._ensure_private_eval_pack(target, key)

    assert result["authenticated"] is True
    assert result["cases"] >= 20
    assert result["created"] is True
    status = evaluation_pack_status(target, key=key)
    assert status["authenticated"] is True
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 30
    assert all(case["id"].startswith("private_") for case in payload["cases"])
    assert len({case["prompt"] for case in payload["cases"]}) == 30


def test_private_eval_pack_is_stable_once_created(tmp_path: Path) -> None:
    key = "z" * 48
    target = tmp_path / "private-eval.json"
    bootstrap._ensure_private_eval_pack(target, key)
    first = target.read_bytes()

    result = bootstrap._ensure_private_eval_pack(target, key)

    assert result["created"] is False
    assert target.read_bytes() == first


def test_production_route_requires_explicit_independent_reviewer() -> None:
    profile = _omniroute_profile()
    profile["AMAURA_OMNIROUTE_REVIEW_MODEL"] = ""

    with pytest.raises(RuntimeError, match="AMAURA_OMNIROUTE_REVIEW_MODEL"):
        bootstrap._production_route(profile)


def test_production_route_rejects_worker_reviewer_collision() -> None:
    profile = _omniroute_profile()
    profile["AMAURA_OMNIROUTE_REVIEW_MODEL"] = profile["AMAURA_OMNIROUTE_MODEL"]

    with pytest.raises(RuntimeError, match="reviewer route is not independently safe"):
        bootstrap._production_route(profile)


def test_production_route_accepts_explicit_omniroute_profile() -> None:
    route = bootstrap._production_route(_omniroute_profile())

    assert route["base_url"] == "https://api.omniroute.ai/v1"
    assert route["worker"] == "mistral-large-latest"
    assert route["reviewer"] == "z-ai/glm-5.2"
    assert route["chat"] == "mistral-large-latest"


def test_upsert_replaces_legacy_nova_profile_without_touching_authority_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env.amaura"
    env.write_text(
        "AMAURA_OPERATOR_KEY=operator-secret\n"
        "AMAURA_MODEL_MODE=local\n"
        "AMAURA_LOCAL_MODEL=nova:3b\n"
        "AMAURA_REVIEW_MODE=local\n",
        encoding="utf-8",
    )

    bootstrap._upsert(
        env,
        {
            "AMAURA_MODEL_MODE": "omniroute",
            "AMAURA_MODEL_PROVIDER": "omniroute",
            "AMAURA_LOCAL_MODEL": "",
            "AMAURA_REVIEW_MODE": "omniroute",
        },
    )

    rendered = env.read_text(encoding="utf-8")
    assert "AMAURA_OPERATOR_KEY=operator-secret" in rendered
    assert "AMAURA_MODEL_MODE=omniroute" in rendered
    assert "AMAURA_MODEL_PROVIDER=omniroute" in rendered
    assert "AMAURA_LOCAL_MODEL=\n" in rendered
    assert "AMAURA_REVIEW_MODE=omniroute" in rendered
    assert "nova:3b" not in rendered


def test_runtime_setup_has_no_local_model_pull_or_direct_provider_bootstrap() -> None:
    setup = (bootstrap.ROOT / "Setup_Amaura_Runtime.command").read_text(encoding="utf-8").lower()

    assert "ollama pull" not in setup
    assert "nova:3b" not in setup
    assert "bootstrap_hosted_production.py" in setup
    assert "omniroute production readiness preflight" in setup


def test_fresh_installer_finishes_before_provider_setup() -> None:
    installer = (bootstrap.ROOT / "Install_Amaura.command").read_text(encoding="utf-8").lower()

    assert "nova:3b" not in installer
    assert "ollama pull" not in installer
    assert "setup_amaura_omniroute.command" in installer
    assert "setup_amaura_antigravity.command" in installer
    assert "deployment_gate" in installer


def test_omniroute_setup_writes_all_production_routing_contracts() -> None:
    setup = (bootstrap.ROOT / "Setup_Amaura_OmniRoute.command").read_text(encoding="utf-8")

    for marker in (
        '"AMAURA_MODEL_MODE": "omniroute"',
        '"AMAURA_MODEL_PROVIDER": "omniroute"',
        '"AMAURA_REVIEW_MODE": "omniroute"',
        '"AMAURA_JARVIS_PROVIDER": "omniroute"',
        '"AMAURA_OMNIROUTE_REVIEW_MODEL": reviewer_model',
        '"AMAURA_LOCAL_MODEL": ""',
        '"AMAURA_JARVIS_ALLOW_OLLAMA": "0"',
    ):
        assert marker in setup
