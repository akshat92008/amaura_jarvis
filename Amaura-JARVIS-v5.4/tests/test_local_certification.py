from pathlib import Path

from jarvis.amaura import local_certification

PASS_PTY = {
    "overall": "PASS",
    "single_mission_continuity": "PASS",
    "result_consistency": "PASS",
    "multi_mission_continuity": "PASS",
    "restart_test": "PASS",
}


def _make_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def _git_factory(
    *,
    git_toplevel: Path,
    head: str = "abc",
    origin: str = "abc",
    status: str = "",
):
    def fake_git(root, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(git_toplevel)
        if args[:3] == ("fetch", "--quiet", "origin"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return head
        if args == ("rev-parse", "origin/main"):
            return origin
        if args == ("status", "--porcelain"):
            return status
        raise AssertionError(f"Unexpected git args: {args}")

    return fake_git


def _doctor_ready(monkeypatch):
    monkeypatch.setattr(
        "jarvis.amaura.doctor.certify_release",
        lambda **_kwargs: {"ready": True, "source_certified": True, "production_ready": True},
    )


def test_local_certification_requires_all_authoritative_gates(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory(git_toplevel=root))
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: dict(PASS_PTY))
    _doctor_ready(monkeypatch)

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is True
    assert report["verdict"] == "READY_FOR_DAILY_USE"
    assert report["provenance"]["head_matches_origin_main"] is True
    assert report["provenance"]["worktree_clean"] is True


def test_local_certification_accepts_package_root_inside_git_checkout(tmp_path, monkeypatch):
    checkout = _make_checkout(tmp_path)
    package_root = checkout / "Amaura-JARVIS-v5.4"
    package_root.mkdir()
    monkeypatch.setattr(local_certification, "_git", _git_factory(git_toplevel=checkout))
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: dict(PASS_PTY))
    _doctor_ready(monkeypatch)

    report = local_certification.certify_local_runtime(package_root)

    assert report["ready"] is True
    assert report["provenance"]["git_toplevel"] == str(checkout.resolve())


def test_local_certification_fails_when_head_is_not_origin_main(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory(git_toplevel=root, head="local", origin="remote"))
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: dict(PASS_PTY))
    _doctor_ready(monkeypatch)

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_DAILY_USE"
    assert report["provenance"]["head_matches_origin_main"] is False


def test_local_certification_fails_when_pty_truth_checks_fail(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    pty = dict(PASS_PTY)
    pty["result_consistency"] = "FAIL"
    monkeypatch.setattr(local_certification, "_git", _git_factory(git_toplevel=root))
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: pty)
    _doctor_ready(monkeypatch)

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_DAILY_USE"


def test_local_certification_fails_when_production_doctor_fails(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory(git_toplevel=root))
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: dict(PASS_PTY))
    monkeypatch.setattr(
        "jarvis.amaura.doctor.certify_release",
        lambda **_kwargs: {"ready": False, "source_certified": True, "production_ready": False},
    )

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_DAILY_USE"
