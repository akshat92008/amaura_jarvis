from __future__ import annotations

import json
from pathlib import Path

from jarvis.amaura import ready_cli


def _env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env.amaura"
    path.write_text("AMAURA_MODEL_MODE=local\nAMAURA_AUDIT_HMAC_KEY=" + "k" * 48 + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _ready_report() -> dict[str, object]:
    return {
        "ready": True,
        "verdict": "READY_FOR_DAILY_USE",
        "production_gate": {"production_ready": True},
        "real_pty": {
            "overall": "PASS",
            "single_mission_continuity": "PASS",
            "result_consistency": "PASS",
            "multi_mission_continuity": "PASS",
            "restart_test": "PASS",
        },
    }


def _cached() -> dict[str, object]:
    return {
        "ready": True,
        "verdict": "READY_FOR_DAILY_USE",
        "head": "abc",
        "certified_at": "2026-08-23T00:00:00+00:00",
    }


def test_ready_cli_refuses_missing_environment(tmp_path):
    missing = tmp_path / "missing.env"
    assert ready_cli.main(["--env-file", str(missing), "--check-only"]) == 2


def test_ready_cli_check_only_requires_authoritative_ready_report(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(ready_cli, "_load_valid_cache", lambda _env: (None, "cache_missing"))
    monkeypatch.setattr(
        "jarvis.amaura.local_certification.certify_local_runtime",
        lambda _root: {"ready": False, "verdict": "NOT_READY_FOR_DAILY_USE"},
    )

    assert ready_cli.main(["--env-file", str(env_path), "--check-only"]) == 1


def test_ready_cli_check_only_writes_certificate_after_full_pass(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    written: dict[str, object] = {}
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(ready_cli, "_load_valid_cache", lambda _env: (None, "cache_missing"))
    monkeypatch.setattr("jarvis.amaura.local_certification.certify_local_runtime", lambda _root: _ready_report())

    def fake_write(_env: Path, _report: dict[str, object]) -> dict[str, object]:
        written["called"] = True
        return _cached()

    monkeypatch.setattr(ready_cli, "_write_cache", fake_write)

    assert ready_cli.main(["--env-file", str(env_path), "--check-only"]) == 0
    assert written["called"] is True


def test_ready_cli_cached_start_skips_expensive_certification(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(ready_cli, "_load_valid_cache", lambda _env: (_cached(), "cache_valid"))

    def must_not_run(_root):
        raise AssertionError("full certification must not run when cache is valid")

    monkeypatch.setattr("jarvis.amaura.local_certification.certify_local_runtime", must_not_run)

    assert ready_cli.main(["--env-file", str(env_path), "--check-only"]) == 0


def test_ready_cli_recertify_forces_full_qualification(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    calls = {"certify": 0}
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(ready_cli, "_load_valid_cache", lambda _env: (_cached(), "cache_valid"))

    def certify(_root):
        calls["certify"] += 1
        return _ready_report()

    monkeypatch.setattr("jarvis.amaura.local_certification.certify_local_runtime", certify)
    monkeypatch.setattr(ready_cli, "_write_cache", lambda _env, _report: _cached())

    assert ready_cli.main(["--env-file", str(env_path), "--check-only", "--recertify"]) == 0
    assert calls["certify"] == 1


def test_ready_cli_launches_hardened_runtime_from_valid_cache(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(ready_cli, "_load_valid_cache", lambda _env: (_cached(), "cache_valid"))

    def fake_execv(executable: str, argv: list[str]) -> None:
        captured["executable"] = executable
        captured["argv"] = argv

    monkeypatch.setattr(ready_cli.os, "execv", fake_execv)

    result = ready_cli.main(
        [
            "--env-file",
            str(env_path),
            "--model",
            "test-model",
            "--working-dir",
            str(tmp_path),
        ]
    )

    assert result == 0
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[1:3] == ["-m", "jarvis.runtime_entry"]
    assert "--no-web" in argv
    assert argv[argv.index("--model") + 1] == "test-model"
    assert argv[argv.index("--working-dir") + 1] == str(tmp_path.resolve())


def test_cache_is_hmac_signed_and_invalidates_on_input_change(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    cache_path = tmp_path / "certificate.json"
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", "k" * 48)
    monkeypatch.setattr(ready_cli, "_cache_path", lambda: cache_path)

    inputs = {
        "head": "head-a",
        "git_toplevel": str(tmp_path),
        "worktree_clean": True,
        "env_sha256": "env-a",
        "runtime_sha256": "runtime-a",
    }
    monkeypatch.setattr(ready_cli, "_certification_inputs", lambda _env: dict(inputs))

    written = ready_cli._write_cache(env_path, _ready_report())
    assert written["signature"]
    assert cache_path.stat().st_mode & 0o077 == 0

    cached, reason = ready_cli._load_valid_cache(env_path)
    assert cached is not None
    assert reason == "cache_valid"

    inputs["head"] = "head-b"
    cached, reason = ready_cli._load_valid_cache(env_path)
    assert cached is None
    assert reason == "cache_head_changed"


def test_tampered_cache_is_rejected(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    cache_path = tmp_path / "certificate.json"
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", "k" * 48)
    monkeypatch.setattr(ready_cli, "_cache_path", lambda: cache_path)
    monkeypatch.setattr(
        ready_cli,
        "_certification_inputs",
        lambda _env: {
            "head": "head-a",
            "git_toplevel": str(tmp_path),
            "worktree_clean": True,
            "env_sha256": "env-a",
            "runtime_sha256": "runtime-a",
        },
    )

    ready_cli._write_cache(env_path, _ready_report())
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["head"] = "forged-head"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    cache_path.chmod(0o600)

    cached, reason = ready_cli._load_valid_cache(env_path)
    assert cached is None
    assert reason == "cache_signature_invalid"
