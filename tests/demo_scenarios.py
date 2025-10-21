import pytest
from uuid import uuid4, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.notification import send_notification_service, retry_failed_notifications
from app.models.notification import Notification
from datetime import datetime

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
    mocker.patch("boto3.client.send_email", side_effect=Exception("Rate limit exceeded"))

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
    mocker.patch("boto3.client.send_email", side_effect=Exception("Permanent SES failure"))

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
async def test_idempotency_retry_with_ses_message_id(db_session: AsyncSession, mocker):
    """
    Tests that retry_failed_notifications skips sending if ses_message_id is already present
    and status is SENT, simulating a successful send but failed status update.
    """
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    mock_ses_message_id = "mock-ses-message-id-123"

    # Create a notification that was 'SENT' but its context was updated with ses_message_id
    # This simulates a scenario where SES sent successfully, but our DB update failed.
    # For this test, we'll set status to FAILED to ensure it's picked up by retry_failed_notifications
    # but then verify it's skipped due to the ses_message_id in context.
    notification_id = uuid4()
    failed_but_sent_notification = Notification(
        id=notification_id,
        user_id=user_id,
        event_type="payment_success",
        status="FAILED", # It's FAILED in our DB, but we assume SES already sent it.
        attempts=0,
        context={"amount": 1000, "ses_message_id": mock_ses_message_id},
        created_at=datetime.utcnow()
    )
    db_session.add(failed_but_sent_notification)
    await db_session.commit()
    await db_session.refresh(failed_but_sent_notification)

    # Mock SES to ensure it's NOT called if idempotency works
    mock_ses = mocker.patch("app.services.notification.send_email_ses", return_value="new-mock-message-id")
    mock_sms = mocker.patch("app.services.notification.send_sms_mock", return_value=True)

    await retry_failed_notifications(db_session)

    # Verify SES and SMS were NOT called
    mock_ses.assert_not_called()
    mock_sms.assert_not_called()

    # Verify notification status is still FAILED (as it was skipped)
    updated_notification = await db_session.get(Notification, notification_id)
    assert updated_notification.status == "FAILED" # Should remain FAILED as it was skipped
    assert updated_notification.attempts == 1 # Attempts should still increment as it was processed by the loop
    assert updated_notification.context.get("ses_message_id") == mock_ses_message_id