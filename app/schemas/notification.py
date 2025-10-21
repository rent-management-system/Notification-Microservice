from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Dict, Any, Optional, List

class NotificationCreate(BaseModel):
    user_id: UUID
    event_type: str
    context: Dict[str, Any]

class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    event_type: str
    status: str
    sent_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    context: Dict[str, Any]

    class Config:
        from_attributes = True

class NotificationStatsResponse(BaseModel):
    total_notifications: int
    total_sent: int
    total_failed: int
    total_pending: int
    by_event_type: Dict[str, Dict[str, int]] # {event_type: {status: count}}
    by_status: Dict[str, int]
