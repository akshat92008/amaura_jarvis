import pytest
import uuid
from jarvis.amaura.store import CompanyStore
from jarvis.amaura.content_factory import ContentFactory
from jarvis.amaura.models import GovernanceError, ContentCampaign, ContentAsset

@pytest.fixture
def store():
    db = CompanyStore(":memory:")
    db._migrate()
    return db

@pytest.fixture
def factory(store):
    return ContentFactory(store=store)

def test_campaign_schema_validation(factory, store):
    """Test that campaign creation enforces schema."""
    campaign_id = "test_campaign_1"
    # Should work
    campaign = factory.create_campaign(
        campaign_id=campaign_id,
        title="Test Campaign",
        audience="Engineers",
        business_objective="Adopt Amaura"
    )
    assert campaign["id"] == campaign_id
    assert campaign["audience"] == "Engineers"
    
    with pytest.raises(GovernanceError, match="are required"):
        factory.create_campaign(
            campaign_id="c2",
            title="T",
            audience="",
            business_objective="Obj"
        )

def test_asset_schema_validation(factory, store):
    """Test that asset registration enforces schema."""
    campaign_id = "test_campaign_asset"
    factory.create_campaign(
        campaign_id=campaign_id,
        title="Test Campaign",
        audience="Engineers",
        business_objective="Adopt Amaura"
    )

    # Valid asset
    asset = factory.register_asset(
        campaign_id=campaign_id,
        asset_type="blog_post",
        uri="file:///tmp/blog.md",
        content=b"Hello World",
        creator="jarvis"
    )
    assert asset["asset_type"] == "blog_post"
    assert asset["creator"] == "jarvis"

    # Missing campaign should fail at get_content_campaign
    with pytest.raises(KeyError):
        factory.register_asset(
            campaign_id="invalid",
            asset_type="blog_post",
            uri="file:///tmp/blog.md",
            content=b"Hello"
        )

    # Invalid status should fail
    with pytest.raises(GovernanceError, match="Invalid content asset status"):
        factory.register_asset(
            campaign_id=campaign_id,
            asset_type="blog_post",
            uri="file:///tmp/blog2.md",
            content=b"Hello2",
            status="unknown_status"
        )
