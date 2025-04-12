from fastapi import APIRouter, HTTPException, Depends
from pydantic import HttpUrl, BaseModel  # Add BaseModel
from typing import Optional  # Add Optional
from ..models import Project
from ..auth import get_current_user
from ..database import projects_collection, users_collection, emotions_collection
import uuid
from git import Repo, GitCommandError
from datetime import datetime, timedelta, timezone  # Add timezone
from bson import ObjectId  # Import ObjectId

router = APIRouter()

class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    

@router.post("/")
async def create_project(name: str, current_user = Depends(get_current_user)):
    project_id = str(uuid.uuid4())
    project_data = {
        "project_id": project_id,
        "name": name,
        "owner_id": current_user.user_id,
        "members": [current_user.user_id],
    }
    await projects_collection.insert_one(project_data)
    return {"message": "Project created successfully", "project_id": project_id}

@router.post("/{project_id}/add-member")
async def add_member_to_project(project_id: str, email: str, current_user = Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["owner_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Only the project owner can add members")

    user = await users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User with the given email not found")

    if user["user_id"] in project["members"]:
        raise HTTPException(status_code=400, detail="User is already a member of the project")

    await projects_collection.update_one(
        {"project_id": project_id}, {"$push": {"members": user["user_id"]}}
    )
    return {"message": "Member added successfully"}

@router.post("/{project_id}/add-repo")
async def add_repo_to_project(project_id: str, repo_url: HttpUrl, current_user = Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(status_code=403, detail="Only project members can add repositories")

    if "repos" not in project:
        project["repos"] = []

    if repo_url in project["repos"]:
        raise HTTPException(status_code=400, detail="Repository already added to the project")

    # Validate the repository URL
    try:
        Repo.clone_from(str(repo_url), to_path="/tmp/validate_repo", depth=1)
    except GitCommandError:
        raise HTTPException(status_code=400, detail="Invalid Git repository URL")

    await projects_collection.update_one(
        {"project_id": project_id}, {"$push": {"repos": str(repo_url)}}
    )
    return {"message": "Repository added successfully"}

@router.get("/{project_id}")
async def get_project_details(project_id: str, current_user = Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(status_code=403, detail="Only project members can view project details")

    # Convert ObjectId to string before returning
    if "_id" in project and isinstance(project["_id"], ObjectId):
        project["_id"] = str(project["_id"])

    return project

@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    data: UpdateProjectRequest,  # Use the request model
    current_user = Depends(get_current_user)
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["owner_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Only the project owner can update the project")

    update_data = {}
    if data.name is not None:
        if not data.name.strip():  # Check if name is empty or just whitespace
            raise HTTPException(status_code=400, detail="Project name cannot be empty")
        update_data["name"] = data.name.strip()

    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    result = await projects_collection.update_one(
        {"project_id": project_id},
        {"$set": update_data}
    )

    if result.modified_count == 1:
        updated_project = await projects_collection.find_one({"project_id": project_id})
        # Convert ObjectId to string before returning
        if updated_project is not None and "_id" in updated_project and isinstance(updated_project["_id"], ObjectId):
            updated_project["_id"] = str(updated_project["_id"])
        return updated_project
    elif result.matched_count == 1:
        # Data provided was the same as existing data
        # Convert ObjectId to string before returning
        if "_id" in project and isinstance(project["_id"], ObjectId):
            project["_id"] = str(project["_id"])
        return project  # Return original project data
    else:
        # Should not happen if find_one succeeded initially
        raise HTTPException(status_code=404, detail="Project not found during update")  # Changed from 500 to 404

@router.delete("/{project_id}")
async def delete_project(project_id: str, current_user = Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["owner_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Only the project owner can delete the project")

    await projects_collection.delete_one({"project_id": project_id})
    return {"message": "Project deleted successfully"}

@router.get("/{project_id}/emotions")
async def get_project_emotions(
    project_id: str,
    start_time: int = 0,
    end_time: int = 0,
    current_user = Depends(get_current_user)
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(status_code=403, detail="Only project members can view emotions")

    # Convert Unix timestamps to datetime objects (assuming UTC)
    try:
        start_date = datetime.fromtimestamp(start_time, tz=timezone.utc)
        if end_time == 0:
            end_date = datetime.utcnow()
        else:
            end_date = datetime.fromtimestamp(end_time, tz=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Unix timestamp format")

    emotions_data = await emotions_collection.find({
        "user_id": {"$in": project["members"]},
        "timestamp": {"$gte": start_date, "$lte": end_date}  # Use converted dates
    }).to_list(length=None)

    # Also convert ObjectId in emotions data
    for emotion in emotions_data:
        if "_id" in emotion and isinstance(emotion["_id"], ObjectId):
            emotion["_id"] = str(emotion["_id"])

    return {"emotions": emotions_data}