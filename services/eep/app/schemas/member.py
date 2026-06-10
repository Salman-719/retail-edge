import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


VALID_PERMISSIONS = {
    "view_alerts", "view_analytics", "view_heatmaps", "view_employees",
    "view_audit_log", "receive_notifications", "manage_employees", "manage_shifts",
}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str
    permissions: dict[str, bool] = {}

    def validate_role(self) -> None:
        if self.role not in ("manager", "viewer"):
            raise ValueError("Role must be manager or viewer")


class InviteResponse(BaseModel):
    invitation_id: uuid.UUID
    expires_at: datetime
    token: str  # included so dev can test without email; remove/hide in prod


class MemberPermissions(BaseModel):
    view_alerts: bool = False
    view_analytics: bool = False
    view_heatmaps: bool = False
    view_employees: bool = False
    view_audit_log: bool = False
    receive_notifications: bool = False
    manage_employees: bool = False
    manage_shifts: bool = False


class MemberListItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    role: str
    permissions: list[str]
    last_active_at: datetime | None = None
    created_at: datetime


class InvitationListItem(BaseModel):
    id: uuid.UUID
    invited_email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class PatchMemberRequest(BaseModel):
    role: str | None = None
    permissions: dict[str, bool] | None = None
