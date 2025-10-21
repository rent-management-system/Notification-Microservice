import pytest
from uuid import uuid4, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.notification import send_notification_service, retry_failed_notifications
from app.models.notification import Notification
from datetime import datetime
from sqlalchemy import select

@pytest.mark.asyncio
async def test_send_notification_invalid_user_id(db_session: AsyncSession):
    """
    Tests that sending a notification to a non-existent user ID
    results in a ValueError and a FAILED notification record.
    """
    invalid_user_id = uuid4()
    with pytest.raises(ValueError, match=f"User with ID {invalid_user_id} not found."):
        await send_notification_service(
            db_session,
            invalid_user_id,
            "payment_success",
            {"amount": 100, "property_title": "Apartment", "location": "Bole"}
        )

    # Verify that a FAILED notification was logged
    result = await db_session.execute(
        select(Notification).filter(Notification.user_id == invalid_user_id)
    )
    notification = result.scalar_one_or_none()
    assert notification is not None
    assert notification.status == "FAILED"

@pytest.mark.asyncio
async def test_send_notification_ses_failure(db_session: AsyncSession, mocker):
    """
    Tests that a notification is marked as FAILED if AWS SES fails to send the email.
    """
    # Mock the SES client to raise an exception
    mocker.patch("app.services.notification.send_email_ses", side_effect=Exception("Rate limit exceeded"))

    # Use a valid user ID from conftest.py
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")

    notification = await send_notification_service(
        db_session,
        user_id,
        "listing_approved",
        {"property_title": "Apartment", "location": "Bole"}
    )

    assert notification.status == "FAILED"
    assert notification.user_id == user_id

@pytest.mark.asyncio
async def test_retry_notification_permanent_failure(db_session: AsyncSession, mocker):
    """
    Tests that a notification permanently fails after 3 retry attempts.
    """
    # Mock the SES client to always fail
    mocker.patch("app.services.notification.send_email_ses", side_effect=Exception("Permanent SES failure"))

    # Create a failed notification with 2 attempts already
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    failed_notification = Notification(
        id=uuid4(),
        user_id=user_id,
        event_type="payment_failed",
        status="FAILED",
        attempts=2,
        context={"amount": 500}
    )
    db_session.add(failed_notification)
    await db_session.commit()
    await db_session.refresh(failed_notification)

    await retry_failed_notifications(db_session)

    # Verify the notification is still FAILED and attempts is now 3
    updated_notification = await db_session.get(Notification, failed_notification.id)
    assert updated_notification.status == "FAILED"
    assert updated_notification.attempts == 3

@pytest.mark.asyncio
async def test_idempotency_retry_with_ses_message_id_updates_status(db_session: AsyncSession, mocker):
    """
    Tests that if a notification has an ses_message_id in its context but is marked as FAILED,
    the retry mechanism updates its status to SENT without re-sending the email.
    This simulates a scenario where SES sent successfully, but the DB update failed.
    """
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    mock_ses_message_id = "mock-ses-message-id-123"

    # Create a notification that was 'SENT' by SES but marked as 'FAILED' in our DB
    notification_id = uuid4()
    failed_but_sent_notification = Notification(
        id=notification_id,
        user_id=user_id,
        event_type="payment_success",
        status="FAILED",
        attempts=0,
        context={"amount": 1000, "ses_message_id": mock_ses_message_id}, # SES ID exists
        created_at=datetime.utcnow()
    )
    db_session.add(failed_but_sent_notification)
    await db_session.commit()
    await db_session.refresh(failed_but_sent_notification)

    # Mock SES and SMS to ensure they are NOT called
    mock_ses = mocker.patch("app.services.notification.send_email_ses")
    mock_sms = mocker.patch("app.services.notification.send_sms_mock")
    
    # Mock get_user_details_from_user_management to succeed
    mocker.patch("app.services.notification.get_user_details_from_user_management", return_value={
        "email": "test@example.com", "phone_number": "+251911123456", "preferred_language": "en"
    })

    await retry_failed_notifications(db_session)

    # Verify SES and SMS were NOT called
    mock_ses.assert_not_called()
    mock_sms.assert_not_called()

    # Verify notification status is updated to SENT
    updated_notification = await db_session.get(Notification, notification_id)
    assert updated_notification.status == "SENT"
    assert updated_notification.attempts == 1 # Attempts should still increment
    assert updated_notification.context.get("ses_message_id") == mock_ses_message_id
    assert updated_notification.sent_at is not None

@pytest.mark.asyncio
async def test_idempotency_retry_skips_already_sent(db_session: AsyncSession, mocker):
    """
    Tests that if a notification has an ses_message_id in its context and is already SENT,
    the retry mechanism skips it entirely.
    """
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    mock_ses_message_id = "mock-ses-message-id-456"

    # Create a notification that is already SENT and has an SES ID
    notification_id = uuid4()
    already_sent_notification = Notification(
        id=notification_id,
        user_id=user_id,
        event_type="listing_approved",
        status="SENT",
        attempts=0,
        context={"property_title": "Test Property", "ses_message_id": mock_ses_message_id},
        created_at=datetime.utcnow(),
        sent_at=datetime.utcnow()
    )
    db_session.add(already_sent_notification)
    await db_session.commit()
    await db_session.refresh(already_sent_notification)

    # Mock SES and SMS to ensure they are NOT called
    mock_ses = mocker.patch("app.services.notification.send_email_ses")
    mock_sms = mocker.patch("app.services.notification.send_sms_mock")
    
    # Mock get_user_details_from_user_management to succeed
    mocker.patch("app.services.notification.get_user_details_from_user_management", return_value={
        "email": "test@example.com", "phone_number": "+251911123456", "preferred_language": "en"
    })

    await retry_failed_notifications(db_session)

    # Verify SES and SMS were NOT called
    mock_ses.assert_not_called()
    mock_sms.assert_not_called()

    # Verify notification status and attempts remain unchanged
    updated_notification = await db_session.get(Notification, notification_id)
    assert updated_notification.status == "SENT"
    assert updated_notification.attempts == 0
    assert updated_notification.context.get("ses_message_id") == mock_ses_message_id