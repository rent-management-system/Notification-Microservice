from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.notification import Notification
from sqlalchemy import text, func
from app.core.logging import logger
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
from app.config import settings
from app.utils.retry import async_retry, CircuitBreaker, CircuitBreakerOpenException
import asyncio
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
import redis.asyncio as redis

# Initialize Circuit Breaker for SES calls
ses_circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60)

# Initialize Redis client for caching
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)

# Load notification templates from JSON file
def load_notification_templates():
    template_path = Path(__file__).parent.parent / "templates" / "notifications.json"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to load notification templates", error=str(e))
        return {}

NOTIFICATION_TEMPLATES = load_notification_templates()


# Mock SMS sending function
async def send_sms_mock(phone_number: str, message: str):
    logger.info("Mock SMS sent", phone_number=phone_number, message=message)
    await asyncio.sleep(0.1) # Simulate network delay
    return True

async def send_admin_alert_email(subject: str, body: str):
    ses_client = boto3.client(
        "ses",
        region_name=settings.AWS_REGION_NAME,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
    )
    try:
        response = ses_client.send_email(
            Source="no-reply@rental-system.com",
            Destination={'ToAddresses': [settings.ADMIN_EMAIL]},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': body}}
            }
        )
        message_id = response['MessageId']
        logger.info("Admin alert email sent via SES", message_id=message_id, recipient=settings.ADMIN_EMAIL)
        return message_id
    except ClientError as e:
        logger.error("Admin alert email send failed", error=str(e), recipient=settings.ADMIN_EMAIL)
        # Do not re-raise, as this is an alert for another failure, we don't want to block the retry process
        return None

@async_retry(tries=3, delay=2, backoff=2, circuit_breaker=ses_circuit_breaker)
async def send_email_ses(recipient_email: str, subject: str, body: str) -> str:
    ses_client = boto3.client(
        "ses",
        region_name=settings.AWS_REGION_NAME,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
    )
    try:
        response = ses_client.send_email(
            Source="no-reply@rental-system.com", # Replace with your verified SES email
            Destination={'ToAddresses': [recipient_email]},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': body}}
            }
        )
        message_id = response['MessageId']
        logger.info("Email sent via SES", message_id=message_id, recipient=recipient_email)
        return message_id
    except ClientError as e:
        logger.error("SES Email send failed", error=str(e), recipient=recipient_email)
        raise # Re-raise to trigger retry

async def get_user_details_from_user_management(user_id: UUID) -> Optional[Dict[str, Any]]:
    cache_key = f"user_details:{user_id}"
    cached_data = await redis_client.get(cache_key)

    if cached_data:
        logger.info("User details retrieved from cache", user_id=user_id)
        return json.loads(cached_data)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{settings.USER_MANAGEMENT_URL}/api/v1/users/{user_id}")
            response.raise_for_status()
            user_data = response.json()
            await redis_client.setex(cache_key, timedelta(hours=1), json.dumps(user_data))
            logger.info("User details fetched from User Management service and cached", user_id=user_id)
            return user_data
        except httpx.HTTPStatusError as e:
            logger.warning("User not found in User Management service", user_id=user_id, status_code=e.response.status_code)
            return None
        except httpx.RequestError as e:
            logger.error("User Management service unavailable", user_id=user_id, error=str(e))
            return None

def get_notification_template(event_type: str, preferred_language: str, context: dict) -> dict:
    template_data = NOTIFICATION_TEMPLATES.get(event_type)
    if not template_data:
        logger.warning("No template found for event_type, falling back to default", event_type=event_type)
        template_data = NOTIFICATION_TEMPLATES.get("payment_success", {}) # Fallback to a default

    lang = preferred_language if preferred_language in ["en", "am", "om"] else "en"

    subject_template = template_data.get("subject", {}).get(lang, template_data.get("subject", {}).get("en", "Notification"))
    body_template = template_data.get("body", {}).get(lang, template_data.get("body", {}).get("en", "No message provided."))

    # Format the message with context, handling missing keys gracefully
    formatted_subject = subject_template.format(**context)
    formatted_body = body_template.format(**context)

    return {"subject": formatted_subject, "body": formatted_body}

async def send_notification_service(db: AsyncSession, user_id: UUID, event_type: str, context: dict) -> Notification:
    notification_id = uuid4()
    status = "PENDING"
    attempts = 0
    sent_at = None
    
    user = await get_user_details_from_user_management(user_id)
    if not user:
        logger.error("User not found for notification, marking as FAILED", user_id=user_id, event_type=event_type)
        notification_record = Notification(
            id=notification_id,
            user_id=user_id,
            event_type=event_type,
            status="FAILED",
            attempts=attempts,
            context=context,
            sent_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(notification_record)
        await db.commit()
        await db.refresh(notification_record)
        raise ValueError(f"User with ID {user_id} not found.")

    try:
        template = get_notification_template(event_type, user.get("preferred_language", "en"), context)
        subject = template["subject"]
        body = template["body"]
        
        ses_message_id = None
        # Send email
        if user.get("email"):
            ses_message_id = await send_email_ses(user["email"], subject, body)

        # Send SMS (mocked)
        if user.get("phone_number"):
            await send_sms_mock(user["phone_number"], body)

        status = "SENT"
        sent_at = datetime.utcnow()
        if ses_message_id:
            context["ses_message_id"] = ses_message_id
        template_version = NOTIFICATION_TEMPLATES.get("version", "unknown")
        logger.info("Notification successfully sent", notification_id=notification_id, user_id=user_id, event_type=event_type, template_version=template_version)

    except Exception as e:
        status = "FAILED"
        logger.error("Failed to send notification after retries", notification_id=notification_id, user_id=user_id, event_type=event_type, error=str(e))

    notification_record = Notification(
        id=notification_id,
        user_id=user_id,
        event_type=event_type,
        status=status,
        attempts=attempts,
        context=context,
        sent_at=sent_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(notification_record)
    await db.commit()
    await db.refresh(notification_record)
    return notification_record

async def get_notification_by_id(db: AsyncSession, notification_id: UUID) -> Optional[Notification]:
    result = await db.execute(select(Notification).filter(Notification.id == notification_id))
    return result.scalar_one_or_none()

async def get_notifications_filtered(db: AsyncSession, user_id: Optional[UUID] = None, event_type: Optional[str] = None) -> List[Notification]:
    query = select(Notification)
    if user_id:
        query = query.filter(Notification.user_id == user_id)
    if event_type:
        query = query.filter(Notification.event_type == event_type)
    result = await db.execute(query)
    return result.scalars().all()

async def retry_failed_notifications(db: AsyncSession):
    logger.info("Attempting to retry failed notifications...")
    stmt = select(Notification).filter(
        Notification.status == "FAILED",
        Notification.attempts < 3
    ).limit(10)

    result = await db.execute(stmt)
    failed_notifications = result.scalars().all()

    for notification in failed_notifications:
        # Idempotency check: if already sent and MessageId exists, skip
        if notification.context.get("ses_message_id"):
            if notification.status == "SENT":
                logger.info("Notification already sent and has SES MessageId, skipping retry", notification_id=notification.id)
                continue
            elif notification.status == "FAILED":
                # If SES MessageId exists but status is FAILED, it means the email was sent but DB update failed.
                # Mark as SENT and skip resending.
                notification.status = "SENT"
                notification.sent_at = datetime.utcnow()
                notification.updated_at = datetime.utcnow()
                db.add(notification)
                await db.commit()
                await db.refresh(notification)
                logger.info("Notification found with SES MessageId but FAILED status, updated to SENT", notification_id=notification.id)
                continue

        notification.attempts += 1
        notification.updated_at = datetime.utcnow()
        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        logger.info("Retrying notification", notification_id=notification.id, attempts=notification.attempts)
        try:
            user = await get_user_details_from_user_management(notification.user_id)
            if not user:
                logger.error("User not found during retry, cannot send notification", notification_id=notification.id)
                if notification.attempts >= 3:
                    logger.critical("Notification permanently failed after 3 retries due to user not found", notification_id=notification.id)
                    await send_admin_alert_email(
                        subject=f"CRITICAL: Notification {notification.id} permanently failed",
                        body=f"Notification {notification.id} for user {notification.user_id} (event: {notification.event_type}) permanently failed after 3 retries. Reason: User not found."
                    )
                continue

            template = get_notification_template(notification.event_type, user.get("preferred_language", "en"), notification.context)
            subject = template["subject"]
            body = template["body"]
            
            ses_message_id = None
            if user.get("email"):
                ses_message_id = await send_email_ses(user["email"], subject, body)
            if user.get("phone_number"):
                await send_sms_mock(user["phone_number"], body)

            notification.status = "SENT"
            notification.sent_at = datetime.utcnow()
            notification.updated_at = datetime.utcnow()
            if ses_message_id:
                notification.context["ses_message_id"] = ses_message_id
            db.add(notification)
            await db.commit()
            await db.refresh(notification)
            logger.info("Notification successfully resent", notification_id=notification.id)

        except Exception as e:
            logger.error("Failed to resend notification", notification_id=notification.id, error=str(e))
            if notification.attempts >= 3:
                logger.critical("Notification permanently failed after 3 retries", notification_id=notification.id)
                await send_admin_alert_email(
                    subject=f"CRITICAL: Notification {notification.id} permanently failed",
                    body=f"Notification {notification.id} for user {notification.user_id} (event: {notification.event_type}) permanently failed after 3 retries. Reason: {e}"
                )

    logger.info("Finished attempting to retry failed notifications.")

async def get_notification_stats(db: AsyncSession) -> dict:
    """
    Retrieves aggregated statistics about notifications.
    """
    logger.info("Fetching notification stats")

    # Main stats query
    main_stats_query = text("""
        SELECT
            COUNT(*) AS total_notifications,
            COUNT(*) FILTER (WHERE status = 'SENT') AS total_sent,
            COUNT(*) FILTER (WHERE status = 'FAILED') AS total_failed,
            COUNT(*) FILTER (WHERE status = 'PENDING') AS total_pending
        FROM notifications
    """)
    main_stats_result = await db.execute(main_stats_query)
    main_stats = main_stats_result.first()

    # Stats by status
    by_status_query = text("""
        SELECT status, COUNT(*) as count
        FROM notifications
        GROUP BY status
    """)
    by_status_result = await db.execute(by_status_query)
    by_status = {row.status: row.count for row in by_status_result}

    # Stats by event type and status
    by_event_type_query = text("""
        SELECT event_type, status, COUNT(*) as count
        FROM notifications
        GROUP BY event_type, status
    """)
    by_event_type_result = await db.execute(by_event_type_query)

    by_event_type = {}
    for row in by_event_type_result:
        if row.event_type not in by_event_type:
            by_event_type[row.event_type] = {"SENT": 0, "FAILED": 0, "PENDING": 0}
        by_event_type[row.event_type][row.status] = row.count

    # Ensure all event types have all statuses
    all_event_types_query = text("SELECT DISTINCT event_type FROM notifications")
    all_event_types_result = await db.execute(all_event_types_query)
    all_event_types = [row.event_type for row in all_event_types_result]

    for event_type in all_event_types:
        if event_type not in by_event_type:
            by_event_type[event_type] = {"SENT": 0, "FAILED": 0, "PENDING": 0}

    stats = {
        "total_notifications": main_stats.total_notifications or 0,
        "total_sent": main_stats.total_sent or 0,
        "total_failed": main_stats.total_failed or 0,
        "total_pending": main_stats.total_pending or 0,
        "by_status": by_status,
        "by_event_type": by_event_type,
    }
    
    logger.info("Notification stats retrieved", **stats)
    return stats