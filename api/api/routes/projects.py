from fastapi import APIRouter, HTTPException, Depends
from pydantic import HttpUrl
from ..models import Project
from ..auth import get_current_user
from ..database import projects_collection, users_collection, emotions_collection
import uuid
from git import Repo, GitCommandError
from datetime import datetime, timedelta

router = APIRouter()

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

    return project

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
async def get_project_emotions(project_id: str, days: int = 7, current_user = Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(status_code=403, detail="Only project members can view emotions")

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    emotions_data = await emotions_collection.find({
        "user_id": {"$in": project["members"]},
        "timestamp": {"$gte": start_date, "$lte": end_date}
    }).to_list(length=None)

    return {"emotions": emotions_data}