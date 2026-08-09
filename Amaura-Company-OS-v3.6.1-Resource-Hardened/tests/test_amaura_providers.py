import pytest
from unittest.mock import patch, MagicMock
from jarvis.amaura.integrations import (
    ProviderMatrix,
    ProviderReceipt,
    GovernanceError,
    verify_provider_receipt,
)

def test_provider_matrix_dispatch_gmail():
    matrix = ProviderMatrix()
    matrix.gmail = MagicMock()
    matrix.gmail.configured = True
    matrix.n8n = MagicMock()
    matrix.n8n.configured = False

    expected_receipt = ProviderReceipt.issue(
        provider="gmail",
        operation="send_email",
        external_id="msg_123",
        idempotency_key="idemp_1",
        payload={"recipient": "test@example.com", "subject": "S", "body": "B"},
        status="sent",
        key="test_key_which_must_be_thirty_two_bytes_long"
    )
    matrix.gmail.send.return_value = expected_receipt

    event = {
        "provider": "auto",
        "operation": "send_email",
        "payload": {"recipient": "test@example.com", "subject": "S", "body": "B"},
        "idempotency_key": "idemp_1"
    }
    
    receipt = matrix.dispatch(event)
    assert receipt.provider == "gmail"
    assert receipt.external_id == "msg_123"
    assert receipt.status == "sent"
    
    # Verify the receipt logic works on it
    verify_provider_receipt(
        receipt,
        expected_operation="send_email",
        expected_idempotency_key="idemp_1",
        expected_payload={"recipient": "test@example.com", "subject": "S", "body": "B"},
        key="test_key_which_must_be_thirty_two_bytes_long"
    )

def test_provider_matrix_dispatch_n8n():
    matrix = ProviderMatrix()
    matrix.gmail = MagicMock()
    matrix.gmail.configured = True
    matrix.n8n = MagicMock()
    matrix.n8n.configured = True  # n8n should take precedence if both are configured and provider="auto"

    expected_receipt = ProviderReceipt.issue(
        provider="n8n",
        operation="send_email",
        external_id="n8n_123",
        idempotency_key="idemp_2",
        payload={"recipient": "test2@example.com", "subject": "S2", "body": "B2"},
        status="sent",
        key="test_key_which_must_be_thirty_two_bytes_long"
    )
    matrix.n8n.send.return_value = expected_receipt

    event = {
        "provider": "auto",
        "operation": "send_email",
        "payload": {"recipient": "test2@example.com", "subject": "S2", "body": "B2"},
        "idempotency_key": "idemp_2"
    }
    
    receipt = matrix.dispatch(event)
    assert receipt.provider == "n8n"
    assert receipt.external_id == "n8n_123"

def test_provider_matrix_dispatch_private_publication():
    matrix = ProviderMatrix()
    matrix.private_pub = MagicMock()
    matrix.private_pub.configured = True

    expected_receipt = ProviderReceipt.issue(
        provider="private-publication",
        operation="create_private_draft",
        external_id="draft_123",
        idempotency_key="idemp_3",
        payload={"title": "Draft 1", "visibility": "private"},
        status="private",
        key="test_key_which_must_be_thirty_two_bytes_long"
    )
    matrix.private_pub.create_private_draft.return_value = expected_receipt

    event = {
        "provider": "private-publication",
        "operation": "create_private_draft",
        "payload": {"title": "Draft 1", "visibility": "private"},
        "idempotency_key": "idemp_3"
    }
    
    receipt = matrix.dispatch(event)
    assert receipt.operation == "create_private_draft"
    assert receipt.external_id == "draft_123"
