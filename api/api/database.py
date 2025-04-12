from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import CollectionInvalid
import os
from dotenv import load_dotenv # Import load_dotenv

# Load environment variables at the start of the module
load_dotenv()

# MongoDB connection setup
mongo_uri = os.getenv("MONGO_URI")
# Add a check to ensure MONGO_URI is loaded
if not mongo_uri:
    raise ValueError("MONGO_URI is not set or not loaded from .env")

client = AsyncIOMotorClient(mongo_uri)
db = client["emotion_data_db"]
users_collection = db["users"]
projects_collection = db["projects"]
emotions_collection = db["emotions"] # This is the collection object
mood_reports_collection = db["mood_reports"] # Add the new collection

# Setup time series collection
async def setup_timeseries_collection():
    try:
        collections = await db.list_collection_names()
        if "emotions" not in collections:
            timeseries_options = {
                "timeField": "timestamp",
                "metaField": "user_id",
                "granularity": "seconds"
            }
            # Use the existing emotions_collection directly
            await db.create_collection("emotions", timeseries=timeseries_options)
            # Ensure index is created on the correct collection object
            await emotions_collection.create_index([("user_id", 1)])
            print("Time series collection 'emotions' created and index added.")
        else:
            # Optionally ensure index exists even if collection exists
            existing_indexes = await emotions_collection.index_information()
            if "user_id_1" not in existing_indexes:
                 await emotions_collection.create_index([("user_id", 1)])
                 print("Index on 'user_id' created for existing collection.")

    except CollectionInvalid:
        # This might happen if it exists but not as a timeseries collection with these options
        print("Collection 'emotions' exists but might have different options or is not a timeseries collection.")
        # Decide how to handle this case, maybe log an error or try to adapt?
        # For now, just print the message.
        pass # emotions_collection is already assigned
    except Exception as e:
        print(f"Error during time series setup: {e}")
        # emotions_collection is already assigned, but setup might be incomplete