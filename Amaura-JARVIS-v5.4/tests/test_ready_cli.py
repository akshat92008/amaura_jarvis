from __future__ import annotations

from pathlib import Path

from jarvis.amaura import ready_cli


def _env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env.amaura"
    path.write_text("AMAURA_MODEL_MODE=local\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_ready_cli_refuses_missing_environment(tmp_path):
    missing = tmp_path / "missing.env"
    assert ready_cli.main(["--env-file", str(missing), "--check-only"]) == 2


def test_ready_cli_check_only_requires_authoritative_ready_report(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(
        "jarvis.amaura.local_certification.certify_local_runtime",
        lambda _root: {"ready": False, "verdict": "NOT_READY_FOR_DAILY_USE"},
    )

    assert ready_cli.main(["--env-file", str(env_path), "--check-only"]) == 1


def test_ready_cli_check_only_passes_only_on_ready_report(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(
        "jarvis.amaura.local_certification.certify_local_runtime",
        lambda _root: {"ready": True, "verdict": "READY_FOR_DAILY_USE"},
    )

    assert ready_cli.main(["--env-file", str(env_path), "--check-only"]) == 0


def test_ready_cli_launches_hardened_runtime_after_certification(tmp_path, monkeypatch):
    env_path = _env_file(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr("jarvis.amaura.runtime.load_amaura_env", lambda *_args, **_kwargs: env_path)
    monkeypatch.setattr(
        "jarvis.amaura.local_certification.certify_local_runtime",
        lambda _root: {"ready": True, "verdict": "READY_FOR_DAILY_USE"},
    )

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
