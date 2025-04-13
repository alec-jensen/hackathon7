from fastapi import APIRouter, HTTPException, Depends, Query  # Add Query
from pydantic import HttpUrl, BaseModel
from typing import Optional, List  # Add List
from ..models import Project
from ..auth import get_current_user
from ..database import (
    projects_collection,
    users_collection,
    emotions_collection,
    mood_reports_collection,
)  # Add mood_reports_collection
import uuid
from git import Repo, GitCommandError
from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId
import pymongo  # Import pymongo for sorting

router = APIRouter()


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None


@router.post("/")
async def create_project(name: str, current_user=Depends(get_current_user)):
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
async def add_member_to_project(
    project_id: str, email: str, current_user=Depends(get_current_user)
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["owner_id"] != current_user.user_id:
        raise HTTPException(
            status_code=403, detail="Only the project owner can add members"
        )

    user = await users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(
            status_code=404, detail="User with the given email not found"
        )

    if user["user_id"] in project["members"]:
        raise HTTPException(
            status_code=400, detail="User is already a member of the project"
        )

    await projects_collection.update_one(
        {"project_id": project_id}, {"$push": {"members": user["user_id"]}}
    )
    return {"message": "Member added successfully"}


@router.post("/{project_id}/add-repo")
async def add_repo_to_project(
    project_id: str, repo_url: HttpUrl, current_user=Depends(get_current_user)
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(
            status_code=403, detail="Only project members can add repositories"
        )

    if "repos" not in project:
        project["repos"] = []

    if repo_url in project["repos"]:
        raise HTTPException(
            status_code=400, detail="Repository already added to the project"
        )

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
async def get_project_details(project_id: str, current_user=Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(
            status_code=403, detail="Only project members can view project details"
        )

    # Convert ObjectId to string before returning
    if "_id" in project and isinstance(project["_id"], ObjectId):
        project["_id"] = str(project["_id"])

    return project


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    data: UpdateProjectRequest,  # Use the request model
    current_user=Depends(get_current_user),
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["owner_id"] != current_user.user_id:
        raise HTTPException(
            status_code=403, detail="Only the project owner can update the project"
        )

    update_data = {}
    if data.name is not None:
        if not data.name.strip():  # Check if name is empty or just whitespace
            raise HTTPException(status_code=400, detail="Project name cannot be empty")
        update_data["name"] = data.name.strip()

    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    result = await projects_collection.update_one(
        {"project_id": project_id}, {"$set": update_data}
    )

    if result.modified_count == 1:
        updated_project = await projects_collection.find_one({"project_id": project_id})
        # Convert ObjectId to string before returning
        if (
            updated_project is not None
            and "_id" in updated_project
            and isinstance(updated_project["_id"], ObjectId)
        ):
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
        raise HTTPException(
            status_code=404, detail="Project not found during update"
        )  # Changed from 500 to 404


@router.delete("/{project_id}")
async def delete_project(project_id: str, current_user=Depends(get_current_user)):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["owner_id"] != current_user.user_id:
        raise HTTPException(
            status_code=403, detail="Only the project owner can delete the project"
        )

    await projects_collection.delete_one({"project_id": project_id})
    return {"message": "Project deleted successfully"}


@router.get("/{project_id}/emotions")
async def get_project_emotions(
    project_id: str,
    start_time: int = 0,
    end_time: int = 0,
    current_user=Depends(get_current_user),
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(
            status_code=403, detail="Only project members can view emotions"
        )

    # Convert Unix timestamps to datetime objects (assuming UTC)
    try:
        start_date = datetime.fromtimestamp(start_time, tz=timezone.utc)
        if end_time == 0:
            end_date = datetime.utcnow()
        else:
            end_date = datetime.fromtimestamp(end_time, tz=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Unix timestamp format")

    emotions_data = await emotions_collection.find(
        {
            "user_id": {"$in": project["members"]},
            "timestamp": {"$gte": start_date, "$lte": end_date},  # Use converted dates
        }
    ).to_list(length=None)

    # Also convert ObjectId in emotions data
    for emotion in emotions_data:
        if "_id" in emotion and isinstance(emotion["_id"], ObjectId):
            emotion["_id"] = str(emotion["_id"])

    return {"emotions": emotions_data}


@router.get("/{project_id}/average-mood")
async def get_project_average_mood(
    project_id: str,
    start_time: int = 0,
    end_time: int = 0,
    current_user=Depends(get_current_user),
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(
            status_code=403, detail="Only project members can view average mood"
        )

    # Convert Unix timestamps to datetime objects (assuming UTC)
    try:
        start_date = datetime.fromtimestamp(start_time, tz=timezone.utc)
        if end_time == 0:
            end_date = datetime.now(timezone.utc)  # Use timezone-aware now
        else:
            end_date = datetime.fromtimestamp(end_time, tz=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Unix timestamp format")

    start_minute_bound = start_date.replace(second=0, microsecond=0)
    end_minute_bound = end_date.replace(second=0, microsecond=0)

    pipeline = [
        {
            "$match": {  # Match the project members and time range
                "user_id": {"$in": project["members"]},
                "received_at": {"$gte": start_date, "$lte": end_date},
            }
        },
        {
            "$set": {  # Set the interval to the start of the minute
                "interval": {
                    "$dateTrunc": {
                        "date": "$received_at",
                        "unit": "minute",
                        "binSize": 1,
                    }
                }
            }
        },
        {
            "$densify": {  # Fill in the gaps in the time series
                "field": "interval",
                "range": {
                    "step": 1,
                    "unit": "minute",
                    "bounds": [
                        start_minute_bound,
                        end_minute_bound,
                    ],  # Use the variables directly
                },
            }
        },
        {
            "$group": {  # Group by the interval and calculate the average mood
                "_id": "$interval",
                "average_angry": {"$avg": "$emotions.angry"},
                "average_disgust": {"$avg": "$emotions.disgust"},
                "average_fear": {"$avg": "$emotions.fear"},
                "average_happy": {"$avg": "$emotions.happy"},
                "average_sad": {"$avg": "$emotions.sad"},
                "average_surprise": {"$avg": "$emotions.surprise"},
                "average_neutral": {"$avg": "$emotions.neutral"},
            }
        },
        {
            "$project": {  # Project the results to include the interval and average emotions
                "_id": 0,
                "interval": "$_id",
                "average_emotions": {
                    "angry": "$average_angry",
                    "disgust": "$average_disgust",
                    "fear": "$average_fear",
                    "happy": "$average_happy",
                    "sad": "$average_sad",
                    "surprise": "$average_surprise",
                    "neutral": "$average_neutral",
                },
            }
        },
        {"$sort": {"interval": 1}},  # Sort by interval in ascending order
        {
            "$setWindowFields": { # Use $setWindowFields to compute first and last intervals
                "sortBy": {"interval": 1},
                "output": {
                    "firstInterval": {
                        "$first": "$interval",
                        "window": {"documents": ["unbounded", "unbounded"]},
                    },
                    "lastInterval": {
                        "$last": "$interval",
                        "window": {"documents": ["unbounded", "unbounded"]},
                    },
                },
            }
        },
        # keep docs where ANY emotion is non-null, OR it's the first/last interval
        {
            "$match": {
                "$expr": {
                    "$or": [
                        # at least one non-null emotion
                        {"$ne": ["$average_emotions.angry", None]},
                        {"$ne": ["$average_emotions.disgust", None]},
                        {"$ne": ["$average_emotions.fear", None]},
                        {"$ne": ["$average_emotions.happy", None]},
                        {"$ne": ["$average_emotions.sad", None]},
                        {"$ne": ["$average_emotions.surprise", None]},
                        {"$ne": ["$average_emotions.neutral", None]},
                        {"$eq": ["$interval", "$firstInterval"]},
                        {"$eq": ["$interval", "$lastInterval"]},
                    ]
                }
            }
        },
        # 3) drop the helper fields
        {"$project": {"firstInterval": 0, "lastInterval": 0}},
    ]

    # The result is now a list of interval averages
    aggregation_result = await emotions_collection.aggregate(pipeline).to_list(
        length=None
    )  # Use length=None

    # Format the timestamps in the result list
    for interval_data in aggregation_result:
        # Convert interval datetime to ISO format string for JSON serialization
        if "interval" in interval_data and isinstance(
            interval_data["interval"], datetime
        ):
            interval_data["interval"] = interval_data["interval"].isoformat()
        # Ensure average emotions are present and handle potential None values if needed
        if "average_emotions" in interval_data:
            for key, value in interval_data["average_emotions"].items():
                if value is None:
                    # Decide how to handle None values, e.g., replace with 0 or keep as None
                    interval_data["average_emotions"][
                        key
                    ] = 0  # Example: replace None with 0

    # Return the list of interval data
    return aggregation_result


@router.get("/{project_id}/reports/individual", response_model=List[dict])
async def get_individual_reports(
    project_id: str,
    user_id: str = Query(..., description="The ID of the user whose reports to fetch"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of reports per page"),
    current_user=Depends(get_current_user),
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(
            status_code=403, detail="Only project members can view reports"
        )

    # Optional: Check if the target user_id is also a member (or owner)
    if user_id not in project["members"]:
        raise HTTPException(
            status_code=404, detail=f"User {user_id} is not a member of this project"
        )

    skip = (page - 1) * page_size
    reports_cursor = (
        mood_reports_collection.find(
            {"project_id": project_id, "user_id": user_id, "report_type": "individual"}
        )
        .sort("report_timestamp", pymongo.DESCENDING)
        .skip(skip)
        .limit(page_size)
    )

    reports = await reports_cursor.to_list(length=page_size)

    # Convert ObjectId to string
    for report in reports:
        if "_id" in report and isinstance(report["_id"], ObjectId):
            report["_id"] = str(report["_id"])
        # Convert datetime objects to ISO format strings if needed for JSON serialization
        if "report_timestamp" in report and isinstance(
            report["report_timestamp"], datetime
        ):
            report["report_timestamp"] = report["report_timestamp"].isoformat()
        if "start_time" in report and isinstance(report["start_time"], datetime):
            report["start_time"] = report["start_time"].isoformat()
        if "end_time" in report and isinstance(report["end_time"], datetime):
            report["end_time"] = report["end_time"].isoformat()

    return reports


@router.get("/{project_id}/reports/group", response_model=List[dict])
async def get_group_reports(
    project_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of reports per page"),
    current_user=Depends(get_current_user),
):
    project = await projects_collection.find_one({"project_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.user_id not in project["members"]:
        raise HTTPException(
            status_code=403, detail="Only project members can view reports"
        )

    skip = (page - 1) * page_size
    reports_cursor = (
        mood_reports_collection.find({"project_id": project_id, "report_type": "group"})
        .sort("report_timestamp", pymongo.DESCENDING)
        .skip(skip)
        .limit(page_size)
    )

    reports = await reports_cursor.to_list(length=page_size)

    # Convert ObjectId to string
    for report in reports:
        if "_id" in report and isinstance(report["_id"], ObjectId):
            report["_id"] = str(report["_id"])
        # Convert datetime objects to ISO format strings if needed for JSON serialization
        if "report_timestamp" in report and isinstance(
            report["report_timestamp"], datetime
        ):
            report["report_timestamp"] = report["report_timestamp"].isoformat()
        if "start_time" in report and isinstance(report["start_time"], datetime):
            report["start_time"] = report["start_time"].isoformat()
        if "end_time" in report and isinstance(report["end_time"], datetime):
            report["end_time"] = report["end_time"].isoformat()

    return reports
