import os

import pytest
from fastapi.testclient import TestClient

from jarvis.server import app
from jarvis.tools.amaura import (
    create_campaign,
)


@pytest.fixture
def test_app(tmp_path):
    os.environ["AMAURA_DISABLE_CLOUD"] = "1"
    os.environ["AMAURA_LOCAL_MODEL"] = "test-model"
    os.environ["AMAURA_REVIEWER_KEYS"] = "qa_agent:qa-test-123,founder:founder-test-123"
    os.environ["AMAURA_OPERATOR_KEY"] = "founder-test-123"
    
    old_cwd = os.getcwd()
    os.chdir(str(tmp_path))
    from jarvis.tools.amaura import get_control_plane
    # init
    get_control_plane()
    yield app
    get_control_plane().close()
    
    import jarvis.tools.amaura
    jarvis.tools.amaura._CONTROL = None
    os.chdir(old_cwd)


def test_end_to_end_campaign_and_assets(test_app):
    client = TestClient(test_app)
    
    res = create_campaign(
        campaign_id="e2e-1",
        name="E2E Test Campaign",
        target_segment="Startups",
        offer="Test offer",
    )
    assert "e2e-1" in res

    response = client.post(
        "/api/amaura/revenue/leads",
        headers={"X-Amaura-Operator-Key": "founder-test-123"},
        json={
            "campaign_id": "e2e-1",
            "company_name": "Test Company",
            "domain": "testcompany.com",
            "source_url": "https://testcompany.com",
        }
    )
    assert response.status_code == 200, response.text
    assert response.json()["company_name"] == "Test Company"
    assert response.json()["campaign_id"] == "e2e-1"
