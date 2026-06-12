from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.accounts import AccountType


class AccountCreate(BaseModel):
    name: str
    account_number: Optional[str] = None
    account_type: AccountType
    parent_id: Optional[int] = None
    description: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_number: Optional[str] = None
    account_type: Optional[AccountType] = None
    parent_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AccountResponse(BaseModel):
    id: int
    name: str
    account_number: Optional[str]
    account_type: AccountType
    parent_id: Optional[int]
    description: Optional[str]
    is_active: bool
    is_system: bool
    balance: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
