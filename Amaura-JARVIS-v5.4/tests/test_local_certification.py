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


def _make_nested_checkout(tmp_path):
    checkout_root = tmp_path / "amaura_jarivs"
    checkout_root.mkdir()
    (checkout_root / ".git").mkdir()
    package_root = checkout_root / "Amaura-JARVIS-v5.4"
    package_root.mkdir()
    return checkout_root, package_root


def _git_factory(*, checkout_root=None, head: str = "abc", origin: str = "abc", status: str = ""):
    def fake_git(root, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(checkout_root or root)
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


def _install_passing_runtime(monkeypatch):
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: dict(PASS_PTY))
    monkeypatch.setattr(
        "jarvis.amaura.doctor.certify_release",
        lambda **_kwargs: {"ready": True, "source_certified": True, "production_ready": True},
    )


def test_local_certification_requires_all_authoritative_gates(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory())
    _install_passing_runtime(monkeypatch)

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is True
    assert report["verdict"] == "READY_FOR_DAILY_USE"
    assert report["provenance"]["head_matches_origin_main"] is True
    assert report["provenance"]["worktree_clean"] is True


def test_local_certification_accepts_package_nested_below_git_root(tmp_path, monkeypatch):
    checkout_root, package_root = _make_nested_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory(checkout_root=checkout_root))
    _install_passing_runtime(monkeypatch)

    report = local_certification.certify_local_runtime(package_root)

    assert report["ready"] is True
    assert report["repository_root"] == str(package_root.resolve())
    assert report["provenance"]["checkout_root"] == str(checkout_root.resolve())


def test_local_certification_ignores_dirty_sibling_outside_runtime_package(tmp_path, monkeypatch):
    checkout_root, package_root = _make_nested_checkout(tmp_path)
    monkeypatch.setattr(
        local_certification,
        "_git",
        _git_factory(checkout_root=checkout_root, status="?? unrelated-scratch.txt"),
    )
    _install_passing_runtime(monkeypatch)

    report = local_certification.certify_local_runtime(package_root)

    assert report["ready"] is True
    assert report["provenance"]["worktree_clean"] is True
    assert report["provenance"]["runtime_dirty_entries"] == []
    assert report["provenance"]["outside_runtime_dirty_entries"] == ["?? unrelated-scratch.txt"]


def test_local_certification_blocks_dirty_runtime_package(tmp_path, monkeypatch):
    checkout_root, package_root = _make_nested_checkout(tmp_path)
    dirty = " M Amaura-JARVIS-v5.4/jarvis/cli.py"
    monkeypatch.setattr(
        local_certification,
        "_git",
        _git_factory(checkout_root=checkout_root, status=dirty),
    )
    _install_passing_runtime(monkeypatch)

    report = local_certification.certify_local_runtime(package_root)

    assert report["ready"] is False
    assert report["provenance"]["worktree_clean"] is False
    assert report["provenance"]["runtime_dirty_entries"] == [dirty]


def test_local_certification_fails_when_head_is_not_origin_main(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory(head="local", origin="remote"))
    _install_passing_runtime(monkeypatch)

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_DAILY_USE"
    assert report["provenance"]["head_matches_origin_main"] is False


def test_local_certification_fails_when_pty_truth_checks_fail(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    pty = dict(PASS_PTY)
    pty["result_consistency"] = "FAIL"
    monkeypatch.setattr(local_certification, "_git", _git_factory())
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: pty)
    monkeypatch.setattr(
        "jarvis.amaura.doctor.certify_release",
        lambda **_kwargs: {"ready": True, "source_certified": True, "production_ready": True},
    )

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_DAILY_USE"


def test_local_certification_fails_when_production_doctor_fails(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(local_certification, "_git", _git_factory())
    monkeypatch.setattr(local_certification, "_load_pty_qualifier", lambda _root: lambda: dict(PASS_PTY))
    monkeypatch.setattr(
        "jarvis.amaura.doctor.certify_release",
        lambda **_kwargs: {"ready": False, "source_certified": True, "production_ready": False},
    )

    report = local_certification.certify_local_runtime(root)

    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_DAILY_USE"
