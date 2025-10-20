from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from typing import List, Optional
from app.schemas.notification import NotificationCreate, NotificationResponse
from app.services.notification import send_notification_service, get_notification_by_id, get_notifications_filtered, retry_failed_notifications
from app.dependencies.auth import get_admin_or_internal_user, get_admin_user
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import get_db

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

@router.post("/send", response_model=NotificationResponse, status_code=status.HTTP_202_ACCEPTED)
async def send_notification_endpoint(
    notification: NotificationCreate,
    current_user: dict = Depends(get_admin_or_internal_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a notification (email/SMS) for a specific event to a user."""
    try:
        notification_record = await send_notification_service(db, notification.user_id, notification.event_type, notification.context)
        return NotificationResponse.model_validate(notification_record)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send notification: {e}")

@router.get("/{id}", response_model=NotificationResponse)
async def get_notification(id: UUID, current_user: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """Retrieve details of a specific notification by ID."""
    notification = await get_notification_by_id(db, id)
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return NotificationResponse.model_validate(notification)

@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    current_user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None),
    event_type: Optional[str] = Query(None)
):
    """Retrieve a list of notifications, with optional filtering by user_id and event_type."""
    notifications = await get_notifications_filtered(db, user_id=user_id, event_type=event_type)
    return [NotificationResponse.model_validate(n) for n in notifications]

@router.post("/retry", status_code=status.HTTP_200_OK)
async def retry_notifications_endpoint(
    current_user: dict = Depends(get_admin_or_internal_user), # Can be called by internal services or admin
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger retry for failed notifications. (Typically run by scheduler)."""
    await retry_failed_notifications(db)
    return {"message": "Attempted to retry failed notifications."}
