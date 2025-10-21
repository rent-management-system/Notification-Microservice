import pytest
from uuid import uuid4, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.notification import send_notification_service
from app.models.notification import Notification

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
    notification = await db_session.execute(
        "SELECT * FROM notifications WHERE user_id = :user_id",
        {"user_id": invalid_user_id}
    )
    notification = notification.first()
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

    # Import retry function here to avoid circular dependency issues at module level
    from app.services.notification import retry_failed_notifications
    await retry_failed_notifications(db_session)

    # Verify the notification is still FAILED and attempts is now 3
    updated_notification = await db_session.get(Notification, failed_notification.id)
    assert updated_notification.status == "FAILED"
    assert updated_notification.attempts == 3