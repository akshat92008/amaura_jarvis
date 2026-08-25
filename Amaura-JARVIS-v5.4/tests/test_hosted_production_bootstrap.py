from __future__ import annotations

import json
from pathlib import Path

from jarvis.amaura.evaluation import evaluation_pack_status
from scripts import bootstrap_hosted_production as bootstrap


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


def test_upsert_replaces_legacy_local_profile_without_touching_authority_keys(tmp_path: Path) -> None:
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
            "AMAURA_MODEL_MODE": "cloud",
            "AMAURA_LOCAL_MODEL": "",
            "AMAURA_REVIEW_MODE": "cloud",
            "AMAURA_CLOUD_WORKER_MODEL": bootstrap.HOSTED_WORKER_MODEL,
        },
    )

    rendered = env.read_text(encoding="utf-8")
    assert "AMAURA_OPERATOR_KEY=operator-secret" in rendered
    assert "AMAURA_MODEL_MODE=cloud" in rendered
    assert "AMAURA_LOCAL_MODEL=\n" in rendered
    assert "nova:3b" not in rendered
    assert f"AMAURA_CLOUD_WORKER_MODEL={bootstrap.HOSTED_WORKER_MODEL}" in rendered


def test_runtime_setup_has_no_local_model_pull_path() -> None:
    setup = (bootstrap.ROOT / "Setup_Amaura_Runtime.command").read_text(encoding="utf-8").lower()

    assert "ollama pull" not in setup
    assert "nova:3b" not in setup
    assert "bootstrap_hosted_production.py" in setup
