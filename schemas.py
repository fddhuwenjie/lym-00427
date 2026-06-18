from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class UserBase(BaseModel):
    name: str
    email: Optional[str] = ""


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AssignmentRuleBase(BaseModel):
    user_id: int
    source: Optional[str] = ""
    region: Optional[str] = ""
    priority: Optional[str] = ""
    priority_order: Optional[int] = 0


class AssignmentRuleCreate(AssignmentRuleBase):
    pass


class AssignmentRuleResponse(AssignmentRuleBase):
    id: int
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True


class ClueBase(BaseModel):
    title: str
    customer_name: Optional[str] = ""
    phone: Optional[str] = ""
    source: Optional[str] = ""
    region: Optional[str] = ""
    priority: Optional[str] = "medium"
    description: Optional[str] = ""


class ClueCreate(ClueBase):
    pass


class ClueUpdate(BaseModel):
    title: Optional[str] = None
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    region: Optional[str] = None
    priority: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


class ClueResponse(ClueBase):
    id: int
    stage: str
    status: str
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_followup_at: Optional[datetime] = None
    next_followup_at: Optional[datetime] = None
    is_overdue: bool = False

    class Config:
        from_attributes = True


class ClueDetailResponse(ClueResponse):
    followups: List["FollowupRecordResponse"] = []


class FollowupRecordBase(BaseModel):
    content: str
    stage_after: Optional[str] = ""
    next_followup_at: Optional[datetime] = None
    created_by: Optional[str] = ""


class FollowupRecordCreate(FollowupRecordBase):
    pass


class FollowupRecordResponse(FollowupRecordBase):
    id: int
    clue_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ReassignRequest(BaseModel):
    target_user_id: int
    reason: Optional[str] = ""


class DailyReportResponse(BaseModel):
    date: str
    total_clues: int
    new_clues: int
    followed_up: int
    overdue_clues: int
    by_stage: dict
    by_user: dict
    clues: List[ClueResponse]


ClueDetailResponse.model_rebuild()
