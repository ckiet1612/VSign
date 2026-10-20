from typing import Literal, Optional
from uuid import UUID
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TeamRole = Literal['admin', 'operator', 'reviewer', 'viewer']
TEAM_PRIVATE_EVENTS = (
    'permission.member_updated', 'permission.invitation_created',
    'permission.invitation_revoked', 'permission.invitation_accepted',
)


class TeamRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


class UpdateMemberRequest(TeamRequest):
    expected_revision: int = Field(ge=0)
    role: Optional[TeamRole] = None
    status: Optional[Literal['active', 'suspended', 'removed']] = None

    @model_validator(mode='after')
    def changed_fields(self):
        if self.role is None and self.status is None:
            raise ValueError('Cần chọn vai trò hoặc trạng thái')
        if any(getattr(self, key) is None for key in self.model_fields_set - {'request_id', 'expected_revision'}):
            raise ValueError('Không nhận giá trị null')
        return self


class CreateInvitationRequest(TeamRequest):
    email: str = Field(min_length=3, max_length=320)
    role: TeamRole
    expires_in_days: int = Field(default=7, ge=1, le=14)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value) or any(ord(c) < 33 for c in value):
            raise ValueError('Email không hợp lệ')
        return value


class InspectInvitationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=32, max_length=128, repr=False)


class AcceptInvitationRequest(InspectInvitationRequest):
    request_id: UUID
    password: str = Field(min_length=1, max_length=256, repr=False)
    display_name: str = Field(default='', max_length=120)
