from __future__ import annotations

from types import SimpleNamespace

from jarvis.amaura import company_daemon


class _FakeControl:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class _FakeRuntime:
    instances = []

    def __init__(self, control):
        self.control = control
        self.calls = []
        type(self).instances.append(self)

    def run_forever(self, **kwargs):
        self.calls.append(kwargs)


def test_daemon_loads_private_env_and_caps_heavy_work(monkeypatch, tmp_path):
    loaded = []
    monkeypatch.setattr(company_daemon, "load_amaura_env", lambda path, **kwargs: loaded.append((path, kwargs)))
    monkeypatch.setattr(company_daemon, "AmauraControlPlane", _FakeControl)
    monkeypatch.setattr(company_daemon, "AutonomousCompanyRuntime", _FakeRuntime)
    monkeypatch.setattr(company_daemon.signal, "signal", lambda *_args, **_kwargs: None)
    _FakeRuntime.instances.clear()
    env_file = tmp_path / ".env.amaura"

    rc = company_daemon.main(
        [
            "--env-file",
            str(env_file),
            "--poll-seconds",
            "1",
            "--max-work-units",
            "99",
            "--max-dynamic-goals",
            "7",
        ]
    )

    assert rc == 0
    assert loaded == [(str(env_file), {"require_private_permissions": True})]
    call = _FakeRuntime.instances[-1].calls[-1]
    assert call["poll_seconds"] == 5.0
    assert call["max_work_units"] == 2
    assert call["max_dynamic_goals"] == 7


def test_daemon_defaults_to_one_heavy_execution_slot(monkeypatch):
    monkeypatch.setattr(company_daemon, "load_amaura_env", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(company_daemon, "AmauraControlPlane", _FakeControl)
    monkeypatch.setattr(company_daemon, "AutonomousCompanyRuntime", _FakeRuntime)
    monkeypatch.setattr(company_daemon.signal, "signal", lambda *_args, **_kwargs: None)
    _FakeRuntime.instances.clear()

    assert company_daemon.main([]) == 0
    call = _FakeRuntime.instances[-1].calls[-1]
    assert call["max_work_units"] == 1
