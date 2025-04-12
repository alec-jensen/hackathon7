from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional

# Pydantic models for user management
class User(BaseModel):
    user_id: str
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email: Optional[EmailStr] = None
    disabled: bool = False
    api_keys: list[str] = []

class UserInDB(User):
    hashed_password: str

# Pydantic model for creating a user with validation
class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[EmailStr] = None

# Pydantic model for emotion data
class EmotionData(BaseModel):
    timestamp: datetime
    emotions: dict

# Pydantic model for project management
class Project(BaseModel):
    project_id: str
    name: str = Field(..., min_length=3, max_length=100)
    owner_id: str
    members: list[str] = []