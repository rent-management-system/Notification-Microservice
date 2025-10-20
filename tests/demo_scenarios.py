import pytest
from httpx import AsyncClient
from uuid import UUID
import json

# This file is for demonstrating error scenarios, not comprehensive unit tests.
# It uses the client fixture to interact with the FastAPI app.

@pytest.mark.asyncio
async def test_demo_send_notification_invalid_user_id(client: AsyncClient, mock_user_management_verify):
    """Demonstrates sending a notification for a non-existent user, resulting in FAILED status."""
    invalid_user_id = UUID("00000000-0000-0000-0000-000000000000") # A user ID that won't be found
    event_type = "payment_success"
    context = {"property_title": "Demo Property", "location": "Demo Location", "amount": 999}

    # Mock user management to return 404 for this specific user ID
    mock_user_management_verify.json.return_value = None
    mock_user_management_verify.status_code = 404

    response = await client.post(
        "/api/v1/notifications/send",
        headers=
            "Authorization": "Bearer test_token"
        },
        json={
            "user_id": str(invalid_user_id),
            "event_type": event_type,
            "context": context
        }
    )

    assert response.status_code == 404
    assert "User with ID" in response.json()["detail"]
    print(f"\nDEMO SCENARIO: Send notification for invalid user_id. Response: {response.json()}")

@pytest.mark.asyncio
async def test_demo_send_notification_ses_failure(client: AsyncClient, mock_user_management_verify, mock_ses_send_email, mock_sms_send):
    """Demonstrates sending a notification where SES fails, leading to FAILED status and retry."""
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    event_type = "listing_approved"
    context = {"property_title": "SES Fail Demo", "location": "Cloud City"}

    # Simulate SES failure
    mock_ses_send_email.send_email.side_effect = Exception("Mock SES API Error")

    response = await client.post(
        "/api/v1/notifications/send",
        headers={
            "Authorization": "Bearer test_token"
        },
        json={
            "user_id": str(user_id),
            "event_type": event_type,
            "context": context
        }
    )

    assert response.status_code == 500 # Internal server error due to send failure
    assert "Failed to send notification" in response.json()["detail"]
    print(f"\nDEMO SCENARIO: Send notification with SES failure. Response: {response.json()}")

    # Reset mock for subsequent tests if any
    mock_ses_send_email.send_email.side_effect = None

@pytest.mark.asyncio
async def test_demo_rate_limit_exceeded(client: AsyncClient, mock_user_management_verify, mocker):
    """Demonstrates hitting the rate limit on the /send endpoint."""
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    event_type = "payment_success"
    context = {"property_title": "Rate Limit Demo", "location": "Fast Lane", "amount": 100}

    # Mock the rate limiter to immediately hit the limit for testing purposes
    # This is a bit hacky for a demo, in real tests you'd send many requests.
    # For demonstration, we'll mock the limiter's check function.
    mocker.patch("fastapi_limiter.FastAPILimiter.check", return_value=False)

    # Mock the logger to capture calls
    mock_logger_warning = mocker.patch("app.main.logger.warning")

    response = await client.post(
        "/api/v1/notifications/send",
        headers={
            "Authorization": "Bearer test_token"
        },
        json={
            "user_id": str(user_id),
            "event_type": event_type,
            "context": context
        }
    )

    assert response.status_code == 429 # Too Many Requests
    assert "Too Many Requests" in response.json()["detail"]
    mock_logger_warning.assert_called_once_with(
        "Rate limit exceeded",
        ip_address=mocker.ANY,
        pkey=mocker.ANY,
        event="rate_limit_exceeded"
    )
    print(f"\nDEMO SCENARIO: Rate limit exceeded. Response: {response.json()}")

    # Reset mock
    mocker.patch("fastapi_limiter.FastAPILimiter.check").stop()
    mock_logger_warning.stop() # Stop the logger mock
