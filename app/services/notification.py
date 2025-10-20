from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.notification import Notification
from sqlalchemy import text
from app.core.logging import logger
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from app.config import settings
from app.utils.retry import async_retry
import asyncio

# Mock SMS sending function
async def send_sms_mock(phone_number: str, message: str):
    logger.info("Mock SMS sent", phone_number=phone_number, message=message)
    await asyncio.sleep(0.1) # Simulate network delay
    return True

@async_retry(tries=3, delay=2, backoff=2)
async def send_email_ses(recipient_email: str, subject: str, body: str):
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
        logger.info("Email sent via SES", message_id=response['MessageId'], recipient=recipient_email)
        return True
    except ClientError as e:
        logger.error("SES Email send failed", error=str(e), recipient=recipient_email)
        raise # Re-raise to trigger retry

async def get_user_details_from_db(db: AsyncSession, user_id: UUID):
    # This assumes a 'Users' table exists in the same database and schema
    # In a real microservice architecture, this might be an HTTP call to User Management Service
    # For this project, we're simulating a direct DB join as per requirements.
    try:
        result = await db.execute(
            select(Notification).from_statement(
                text(f"SELECT email, phone_number, preferred_language FROM Users WHERE id = :user_id")
            ).params(user_id=user_id)
        )
        user = result.first()
        if not user:
            logger.warning("User not found in DB for notification", user_id=user_id)
            return None
        return user
    except Exception as e:
        logger.error("Error fetching user details from DB", user_id=user_id, error=str(e))
        return None

def get_notification_template(event_type: str, preferred_language: str, context: dict) -> dict:
    templates = {
        "payment_success": {
            "en": f"Your payment for '{{property_title}}' in {{location}} of {{amount}} ETB was successful. Thank you!",
            "am": f"ክፍያዎ ለ'{{property_title}}' በ{{location}} {{amount}} ብር ተሳክቷል። እናመሰግናለን!",
            "om": f"Kaffaltiin keessan '{{property_title}}' {{location}} keessatti {{amount}} qarshii milkaa'eera. Galatoomaa!"
        },
        "payment_failed": {
            "en": f"Your payment for '{{property_title}}' in {{location}} of {{amount}} ETB failed. Please try again.",
            "am": f"ክፍያዎ ለ'{{property_title}}' በ{{location}} {{amount}} ብር አልተሳካም። እባክዎ እንደገና ይሞክሩ።",
            "om": f"Kaffaltiin keessan '{{property_title}}' {{location}} keessatti {{amount}} qarshii hin milkoofne. Irra deebi'aa yaalaa."
        },
        "listing_approved": {
            "en": f"Your listing '{{property_title}}' in {{location}} has been approved and is now live!",
            "am": f"የእርስዎ ዝርዝር '{{property_title}}' በ{{location}} ጸድቋል እና አሁን ቀጥታ ነው።",
            "om": f"Tarreen keessan '{{property_title}}' {{location}} keessatti mirkanaa'ee jira, amma online jira!"
        },
        "tenant_update": {
            "en": f"Update for your listing '{{property_title}}': A tenant named {{tenant_name}} is interested.",
            "am": f"ለዝርዝርዎ '{{property_title}}' ማሻሻያ: {{tenant_name}} የሚባል ተከራይ ፍላጎት አለው።",
            "om": f"Tarree keessan '{{property_title}}' irratti odeeffannoo haaraa: Kirreessaan maqaan isaa {{tenant_name}} jedhamu fedhii qaba."
        }
    }

    subject_templates = {
        "payment_success": {"en": "Payment Successful", "am": "ክፍያ ተሳክቷል", "om": "Kaffaltiin Milkaa'eera"},
        "payment_failed": {"en": "Payment Failed", "am": "ክፍያ አልተሳካም", "om": "Kaffaltiin Hin Milkoofne"},
        "listing_approved": {"en": "Listing Approved", "am": "ዝርዝር ጸድቋል", "om": "Tarreen Mirkanoofte"},
        "tenant_update": {"en": "Tenant Update", "am": "የተከራይ ማሻሻያ", "om": "Odeeffannoo Kirreessaa"}
    }

    lang = preferred_language if preferred_language in ["en", "am", "om"] else "en"

    message_template = templates.get(event_type, {}).get(lang, templates["payment_success"]["en"])
    subject_template = subject_templates.get(event_type, {}).get(lang, subject_templates["payment_success"]["en"])

    # Format the message with context, handling missing keys gracefully
    formatted_message = message_template.format(**context)
    formatted_subject = subject_template.format(**context)

    return {"subject": formatted_subject, "body": formatted_message}

async def send_notification_service(db: AsyncSession, user_id: UUID, event_type: str, context: dict) -> Notification:
    notification_id = uuid4()
    status = "PENDING"
    attempts = 0
    sent_at = None

    user = await get_user_details_from_db(db, user_id)
    if not user:
        # Log and store as FAILED if user not found
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
        template = get_notification_template(event_type, user.preferred_language, context)
        subject = template["subject"]
        body = template["body"]

        # Send email
        if user.email:
            await send_email_ses(user.email, subject, body)

        # Send SMS (mocked)
        if user.phone_number:
            await send_sms_mock(user.phone_number, body)

        status = "SENT"
        sent_at = datetime.utcnow()
        logger.info("Notification successfully sent", notification_id=notification_id, user_id=user_id, event_type=event_type)

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
    # Select failed notifications with less than 3 attempts
    stmt = select(Notification).filter(
        Notification.status == "FAILED",
        Notification.attempts < 3
    ).limit(10) # Process a batch of 10 at a time

    result = await db.execute(stmt)
    failed_notifications = result.scalars().all()

    for notification in failed_notifications:
        notification.attempts += 1
        notification.updated_at = datetime.utcnow()
        db.add(notification) # Mark for update
        await db.commit()
        await db.refresh(notification)

        logger.info("Retrying notification", notification_id=notification.id, attempts=notification.attempts)
        try:
            user = await get_user_details_from_db(db, notification.user_id)
            if not user:
                logger.error("User not found during retry, cannot send notification", notification_id=notification.id)
                continue # Skip to next notification

            template = get_notification_template(notification.event_type, user.preferred_language, notification.context)
            subject = template["subject"]
            body = template["body"]

            if user.email:
                await send_email_ses(user.email, subject, body)
            if user.phone_number:
                await send_sms_mock(user.phone_number, body)

            notification.status = "SENT"
            notification.sent_at = datetime.utcnow()
            notification.updated_at = datetime.utcnow()
            db.add(notification)
            await db.commit()
            await db.refresh(notification)
            logger.info("Notification successfully resent", notification_id=notification.id)

        except Exception as e:
            logger.error("Failed to resend notification", notification_id=notification.id, error=str(e))
            # If attempts reach 3, notify admin (this part would be another notification send)
            if notification.attempts >= 3:
                logger.critical("Notification permanently failed after 3 retries", notification_id=notification.id)
                # TODO: Implement admin notification here

    logger.info("Finished attempting to retry failed notifications.")
