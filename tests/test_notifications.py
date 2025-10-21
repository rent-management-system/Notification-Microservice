import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.models.notification import Notification
from app.schemas.notification import NotificationResponse
from app.services.notification import send_notification_service, get_notification_by_id, get_notifications_filtered, retry_failed_notifications
from datetime import datetime, timedelta
import json
import logging

@pytest.mark.asyncio
async def test_send_notification_success(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify, mock_ses_send_email, mock_sms_send):
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    event_type = "payment_success"
    context = {"property_title": "Test Property", "location": "Test Location", "amount": 1000}

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

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "SENT"
    assert "id" in data

    # Verify notification was logged in DB
    notification = await db_session.get(Notification, UUID(data["id"]))
    assert notification is not None
    assert notification.user_id == user_id
    assert notification.event_type == event_type
    assert notification.status == "SENT"
    assert notification.context == context
    assert notification.sent_at is not None

    # Verify SES and SMS mocks were called with correct content from JSON template
    with open("app/templates/notifications.json", "r", encoding="utf-8") as f:
        templates = json.load(f)
    expected_subject = templates["payment_success"]["subject"]["en"].format(**context)
    expected_body = templates["payment_success"]["body"]["en"].format(**context)

    mock_ses_send_email.send_email.assert_called_once_with(
        Source="no-reply@rental-system.com",
        Destination={'ToAddresses': ["test@example.com"]},
        Message={'Subject': {'Data': expected_subject}, 'Body': {'Text': {'Data': expected_body}}}
    )
    mock_sms_send.assert_called_once_with("+251911123456", expected_body)

@pytest.mark.asyncio
async def test_send_notification_new_listing_amharic(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify, mock_ses_send_email, mock_sms_send):
    user_id = UUID("123e4567-e89b-12d3-a456-426614174001") # Amharic user
    event_type = "new_listing"
    context = {"property_title": "Brand New Apartment", "location": "Bole, Addis Ababa"}

    # Mock user management to return Amharic user
    mock_user_management_verify.json.return_value = {
        "user_id": str(user_id),
        "role": "Tenant",
        "email": "amharic@example.com",
        "phone_number": "+251911123457",
        "preferred_language": "am"
    }

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

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "SENT"

    with open("app/templates/notifications.json", "r", encoding="utf-8") as f:
        templates = json.load(f)
    expected_subject = templates["new_listing"]["subject"]["am"].format(**context)
    expected_body = templates["new_listing"]["body"]["am"].format(**context)

    mock_ses_send_email.send_email.assert_called_once_with(
        Source="no-reply@rental-system.com",
        Destination={'ToAddresses': ["amharic@example.com"]},
        Message={'Subject': {'Data': expected_subject}, 'Body': {'Text': {'Data': expected_body}}}
    )
    mock_sms_send.assert_called_once_with("+251911123457", expected_body)

@pytest.mark.asyncio
async def test_send_notification_user_not_found(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify, mock_ses_send_email, mock_sms_send):
    user_id = UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a99") # Non-existent user
    event_type = "payment_success"
    context = {"property_title": "Test Property", "location": "Test Location", "amount": 1000}

    # Mock user management to return 404 for this user
    mock_user_management_verify.json.return_value = None
    mock_user_management_verify.status_code = 404

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

    assert response.status_code == 404
    assert "User with ID" in response.json()["detail"]

    # Verify notification was logged as FAILED
    notifications = await get_notifications_filtered(db_session, user_id=user_id, event_type=event_type)
    assert len(notifications) == 1
    assert notifications[0].status == "FAILED"
    assert notifications[0].sent_at is None

    # Verify SES and SMS mocks were NOT called
    mock_ses_send_email.send_email.assert_not_called()
    mock_sms_send.assert_not_called()

@pytest.mark.asyncio
async def test_get_notification_by_id(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify):
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    notification_id = UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
    notification_data = Notification(
        id=notification_id,
        user_id=user_id,
        event_type="test_event",
        status="SENT",
        context={'key': 'value'},
        sent_at=datetime.utcnow()
    )
    db_session.add(notification_data)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/notifications/{notification_id}",
        headers={
            "Authorization": "Bearer test_token"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(notification_id)
    assert data["event_type"] == "test_event"
    assert data["status"] == "SENT"

@pytest.mark.asyncio
async def test_get_notification_not_found(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify):
    non_existent_id = UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a99")
    response = await client.get(
        f"/api/v1/notifications/{non_existent_id}",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_get_notifications_filtered(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify):
    user_id_1 = UUID("123e4567-e89b-12d3-a456-426614174000")
    user_id_2 = UUID("123e4567-e89b-12d3-a456-426614174001")

    # Add some test data
    n1 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380b01"), user_id=user_id_1, event_type="event_A", status="SENT", context={})
    n2 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380b02"), user_id=user_id_1, event_type="event_B", status="PENDING", context={})
    n3 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380b03"), user_id=user_id_2, event_type="event_A", status="FAILED", context={})
    db_session.add_all([n1, n2, n3])
    await db_session.commit()

    # Test filter by user_id
    response = await client.get(
        f"/api/v1/notifications?user_id={user_id_1}",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(item["user_id"] == str(user_id_1) for item in data)

    # Test filter by event_type
    response = await client.get(
        f"/api/v1/notifications?event_type=event_A",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(item["event_type"] == "event_A" for item in data)

    # Test filter by both
    response = await client.get(
        f"/api/v1/notifications?user_id={user_id_1}&event_type=event_B",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["user_id"] == str(user_id_1)
    assert data[0]["event_type"] == "event_B"

@pytest.mark.asyncio
async def test_retry_failed_notifications(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify, mock_ses_send_email, mock_sms_send):
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    # Create a failed notification
    failed_notification = Notification(
        id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380c01"),
        user_id=user_id,
        event_type="payment_failed",
        status="FAILED",
        attempts=0,
        context={'property_title': 'Failed Property', 'location': 'Failed Location', 'amount': 500},
        created_at=datetime.utcnow() - timedelta(hours=1)
    )
    db_session.add(failed_notification)
    await db_session.commit()

    # Ensure mocks are reset for this test
    mock_ses_send_email.send_email.reset_mock()
    mock_sms_send.reset_mock()

    response = await client.post(
        "/api/v1/notifications/retry",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Attempted to retry failed notifications."}

    # Verify notification status updated to SENT and attempts increased
    updated_notification = await db_session.get(Notification, failed_notification.id)
    assert updated_notification.status == "SENT"
    assert updated_notification.attempts == 1
    assert updated_notification.sent_at is not None

    # Verify SES and SMS mocks were called for the retry
    mock_ses_send_email.send_email.assert_called_once()
    mock_sms_send.assert_called_once()

@pytest.mark.asyncio
async def test_retry_failed_notifications_max_attempts(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify, mock_ses_send_email, mock_sms_send):
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    # Create a failed notification with max attempts
    failed_notification = Notification(
        id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380d01"),
        user_id=user_id,
        event_type="payment_failed",
        status="FAILED",
        attempts=3,
        context={'property_title': 'Max Attempt Property', 'location': 'Max Attempt Location', 'amount': 700},
        created_at=datetime.utcnow() - timedelta(hours=1)
    )
    db_session.add(failed_notification)
    await db_session.commit()

    mock_ses_send_email.send_email.reset_mock()
    mock_sms_send.reset_called()

    response = await client.post(
        "/api/v1/notifications/retry",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 200

    # Verify notification status remains FAILED and attempts not increased (as it's already maxed)
    updated_notification = await db_session.get(Notification, failed_notification.id)
    assert updated_notification.status == "FAILED"
    assert updated_notification.attempts == 3 # Should not increase beyond 3 for retry logic

    # Verify SES and SMS mocks were NOT called
    mock_ses_send_email.send_email.assert_not_called()
    mock_sms_send.assert_not_called()

@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify):
    # Mock user management to return a non-admin role
    mock_user_management_verify.json.return_value = {
        "user_id": "123e4567-e89b-12d3-a456-426614174000",
        "role": "Tenant", # Not Admin or Internal
        "email": "tenant@example.com",
        "phone_number": "+251911123456",
        "preferred_language": "en"
    }

    # Test /send endpoint (requires Admin or Internal)
    response = await client.post(
        "/api/v1/notifications/send",
        headers={
            "Authorization": "Bearer test_token"
        },
        json={
            "user_id": str(UUID("123e4567-e89b-12d3-a456-426614174000")),
            "event_type": "payment_success",
            "context": {}
        }
    )
    assert response.status_code == 403

    # Test /get endpoint (requires Admin)
    response = await client.get(
        f"/api/v1/notifications/{UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")}",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 403

    # Test /retry endpoint (requires Admin or Internal)
    response = await client.post(
        "/api/v1/notifications/retry",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_get_notification_stats(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify):
    user_id_1 = UUID("123e4567-e89b-12d3-a456-426614174000")
    user_id_2 = UUID("123e4567-e89b-12d3-a456-426614174001")

    # Add some test data for stats
    n1 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380e01"), user_id=user_id_1, event_type="payment_success", status="SENT", context={}, sent_at=datetime.utcnow())
    n2 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380e02"), user_id=user_id_1, event_type="payment_success", status="FAILED", context={})
    n3 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380e03"), user_id=user_id_2, event_type="listing_approved", status="SENT", context={}, sent_at=datetime.utcnow())
    n4 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380e04"), user_id=user_id_2, event_type="listing_approved", status="PENDING", context={})
    n5 = Notification(id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380e05"), user_id=user_id_1, event_type="tenant_update", status="SENT", context={}, sent_at=datetime.utcnow())
    db_session.add_all([n1, n2, n3, n4, n5])
    await db_session.commit()

    response = await client.get(
        "/api/v1/notifications/stats",
        headers={
            "Authorization": "Bearer test_token"
        }
    )

    assert response.status_code == 200
    stats = response.json()

    assert stats["total_notifications"] == 5
    assert stats["total_sent"] == 3
    assert stats["total_failed"] == 1
    assert stats["total_pending"] == 1

    assert stats["by_status"] == {"SENT": 3, "FAILED": 1, "PENDING": 1}

    assert stats["by_event_type"]["payment_success"] == {"SENT": 1, "FAILED": 1, "PENDING": 0}
    assert stats["by_event_type"]["listing_approved"] == {"SENT": 1, "FAILED": 0, "PENDING": 1}
    assert stats["by_event_type"]["tenant_update"] == {"SENT": 1, "FAILED": 0, "PENDING": 0}

@pytest.mark.asyncio
async def test_get_notification_stats_unauthorized(client: AsyncClient, db_session: AsyncSession, mock_user_management_verify):
    # Mock user management to return a non-admin role
    mock_user_management_verify.json.return_value = {
        "user_id": "123e4567-e89b-12d3-a456-426614174000",
        "role": "Tenant", # Not Admin
        "email": "tenant@example.com",
        "phone_number": "+251911123456",
        "preferred_language": "en"
    }

    response = await client.get(
        "/api/v1/notifications/stats",
        headers={
            "Authorization": "Bearer test_token"
        }
    )
    assert response.status_code == 403
