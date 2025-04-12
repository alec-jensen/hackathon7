from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import CollectionInvalid
import os

# MongoDB connection setup
mongo_uri = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(mongo_uri)
db = client["emotion_data_db"]
users_collection = db["users"]
projects_collection = db["projects"]
emotions_collection = db["emotions"]

# Setup time series collection
async def setup_timeseries_collection():
    global collection
    try:
        collections = await db.list_collection_names()
        if "emotions" not in collections:
            timeseries_options = {
                "timeField": "timestamp",
                "metaField": "user_id",
                "granularity": "seconds"
            }
            collection = await db.create_collection("emotions", timeseries=timeseries_options)
            await collection.create_index([("user_id", 1)])
        else:
            collection = db["emotions"]
    except CollectionInvalid:
        collection = db["emotions"]
    except Exception as e:
        print(f"Error during time series setup: {e}")
        collection = db["emotions"]