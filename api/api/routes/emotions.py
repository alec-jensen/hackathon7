from fastapi import APIRouter, HTTPException, Header, Depends
from ..models import EmotionData
from ..auth import get_current_user
from ..database import setup_timeseries_collection, db
from datetime import datetime

router = APIRouter()

@router.post("/")
async def store_emotion_data(data: EmotionData, x_api_key: str = Header(...)):
    user = await db["users"].find_one({"api_keys": x_api_key})
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        data_dict = data.model_dump()
        data_dict["received_at"] = datetime.utcnow()
        data_dict["user_id"] = user["user_id"]

        collection = db["emotions"]
        await collection.insert_one(data_dict)
        return {"message": "Emotion data stored successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store emotion data: {e}")