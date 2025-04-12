from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..models import User
from ..auth import get_current_user, get_password_hash
from ..database import users_collection, projects_collection
import uuid
import os
from typing import Optional

class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

router = APIRouter()

@router.post("/")
async def create_user(data: CreateUserRequest):
    username = data.username
    password = data.password
    email = data.email

    if not username or not password:
        raise HTTPException(
            status_code=400, detail="Username and password are required"
        )

    existing_user = await users_collection.find_one({"username": username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = get_password_hash(password)
    user_id = str(uuid.uuid4())
    user_data = {
        "user_id": user_id,
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "api_keys": [],
        "disabled": False,
    }
    await users_collection.insert_one(user_data)
    return {"message": "User created successfully", "user_id": user_id}

@router.get("/me", response_model=User)
async def get_user_details(current_user: User = Depends(get_current_user)):
    return current_user

@router.delete("/me")
async def delete_user(current_user: User = Depends(get_current_user)):
    result = await users_collection.delete_one({"user_id": current_user.user_id})
    if result.deleted_count == 1:
        return {"message": "User deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found")

@router.post("/me/api-keys")
async def create_api_key(current_user: User = Depends(get_current_user)):
    new_api_key = os.urandom(24).hex()
    await users_collection.update_one(
        {"user_id": current_user.user_id}, {"$push": {"api_keys": new_api_key}}
    )
    return {"api_key": new_api_key}

@router.delete("/me/api-keys/{api_key}")
async def delete_api_key(api_key: str, current_user: User = Depends(get_current_user)):
    result = await users_collection.update_one(
        {"user_id": current_user.user_id}, {"$pull": {"api_keys": api_key}}
    )
    if result.modified_count == 1:
        return {"message": "API key deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="API key not found")

@router.get("/me/api-keys")
async def get_api_keys(current_user: User = Depends(get_current_user)):
    user = await users_collection.find_one({"user_id": current_user.user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"api_keys": user["api_keys"]}

@router.get("/me/projects")
async def get_user_projects(current_user: User = Depends(get_current_user)):
    projects = await projects_collection.find({"members": current_user.user_id}).to_list(length=None)
    return {"projects": projects}