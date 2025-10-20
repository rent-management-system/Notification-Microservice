from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Dict, Any, Optional

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
