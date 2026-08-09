from pathlib import Path

from scripts.build_release import forbidden


def test_release_builder_rejects_runtime_state_and_secrets():
    assert forbidden(Path(".amaura-data/company.db"))
    assert forbidden(Path("jarvis/__pycache__/x.pyc"))
    assert forbidden(Path(".env.amaura"))
    assert forbidden(Path("backup.sqlite3"))


def test_release_builder_allows_template_and_source():
    assert forbidden(Path(".env.amaura.example")) is None
    assert forbidden(Path("jarvis/amaura/store.py")) is None
