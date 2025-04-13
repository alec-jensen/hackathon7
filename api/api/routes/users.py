from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..models import User
from ..auth import get_current_user, get_password_hash
from ..database import users_collection, projects_collection
import uuid
import os
from typing import Optional, List  # Add List
from bson.objectid import ObjectId  # Import ObjectId

class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    # Note: Password updates might require a separate endpoint or current password verification

class PublicUserInfo(BaseModel):
    username: str

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

@router.get("/{user_id}", response_model=PublicUserInfo)
async def get_public_user_info(user_id: str):
    user_data = await users_collection.find_one({"user_id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    return PublicUserInfo(username=user_data["username"])

@router.get("/me", response_model=User)
async def get_user_details(current_user: User = Depends(get_current_user)):
    return current_user

@router.patch("/me", response_model=User)
async def update_user_details(
    data: UpdateUserRequest, current_user: User = Depends(get_current_user)
):
    update_data = {}
    if data.username is not None:
        # Check if the new username is already taken by another user
        existing_user = await users_collection.find_one(
            {"username": data.username, "user_id": {"$ne": current_user.user_id}}
        )
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already taken")
        update_data["username"] = data.username

    if data.email is not None:
        # Optional: Add email format validation if needed
        update_data["email"] = data.email

    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    result = await users_collection.update_one(
        {"user_id": current_user.user_id}, {"$set": update_data}
    )

    if result.modified_count == 1:
        updated_user_data = await users_collection.find_one({"user_id": current_user.user_id})
        if not updated_user_data:
            raise HTTPException(status_code=404, detail="User not found after update")
        # Ensure the returned user data conforms to the User model (excluding password)
        return User(
            user_id=updated_user_data.get("user_id", current_user.user_id),
            username=updated_user_data.get("username", current_user.username),
            email=updated_user_data.get("email", current_user.email),
            api_keys=updated_user_data.get("api_keys", current_user.api_keys),
            disabled=updated_user_data.get("disabled", current_user.disabled),
        )
    elif result.matched_count == 1:
         # No fields were actually changed (e.g., provided same username)
        return current_user
    else:
        # This case should ideally not happen if the user is authenticated
        raise HTTPException(status_code=404, detail="User not found")

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
    projects_cursor = projects_collection.find({"members": current_user.user_id})
    projects_list = await projects_cursor.to_list(length=None)

    # Convert ObjectId to string for each project
    for project in projects_list:
        if "_id" in project and isinstance(project["_id"], ObjectId):
            project["_id"] = str(project["_id"])

    return {"projects": projects_list}