from pathlib import Path

from jarvis.amaura.verification import SecureVerifierRunner


def test_macos_profile_allows_only_required_root_and_null_device_access(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    temp_home = tmp_path / "verify-home"
    workspace.mkdir()
    temp_home.mkdir()

    profile = SecureVerifierRunner._mac_profile(workspace, temp_home)

    assert '(allow file-read* (literal "/"))' in profile
    assert '(allow file-write* (literal "/dev/null"))' in profile

    # The compatibility repair must remain narrow: never replace it with
    # unrestricted recursive filesystem read/write permissions.
    assert "\n(allow file-read*)\n" not in f"\n{profile}\n"
    assert "\n(allow file-write*)\n" not in f"\n{profile}\n"

    assert "(deny network*)" in profile
    assert f'(allow file-write* (subpath "{workspace.resolve()}"))' in profile
    assert f'(allow file-read* (subpath "{workspace.resolve()}"))' in profile
