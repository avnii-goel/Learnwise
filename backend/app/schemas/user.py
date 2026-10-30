from datetime import datetime
from typing import Literal
import email_validator
from pydantic import BaseModel, ConfigDict, EmailStr, Field

email_validator.TEST_ENVIRONMENT = True

class UserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["learner", "instructor"] = "learner"
    invite_code: str | None = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str 

class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)