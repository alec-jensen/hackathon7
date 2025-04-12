from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import timedelta, datetime
import time
from dotenv import load_dotenv
import os
from typing import Optional
import uuid
from pymongo.errors import CollectionInvalid  # Import CollectionInvalid

# Load environment variables from .env file
load_dotenv()

# Fetch the MongoDB URI from the environment variables
mongo_uri = os.getenv("MONGO_URI")

# Load JWT_SECRET_KEY from environment variables
JWT_SECRET_KEY: str | None = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY is not set in the environment variables")

# Initialize FastAPI app
app = FastAPI()

# MongoDB connection setup
client = AsyncIOMotorClient(mongo_uri)
db = client["emotion_data_db"]
users_collection = db["users"]

# --- Add Startup Event to Configure Time Series Collection ---
@app.on_event("startup")
async def setup_timeseries_collection():
    global collection  # Use global collection variable
    try:
        # Check if collection exists
        collections = await db.list_collection_names()
        if "emotions" not in collections:
            # Create the time series collection if it doesn't exist
            timeseries_options = {
                "timeField": "timestamp",
                "metaField": "user_id",
                "granularity": "seconds"  # Adjust granularity as needed
            }
            collection = await db.create_collection("emotions", timeseries=timeseries_options)
            print("Time series collection 'emotions' created.")
            # Optional: Create index on metaField for faster user-specific queries
            await collection.create_index([("user_id", 1)])
            print("Index created on 'user_id'.")
        else:
            # Collection exists, assign it
            collection = db["emotions"]
            print("Collection 'emotions' already exists.")
    except CollectionInvalid as e:
        print(f"Could not create collection 'emotions' (may already exist with different options): {e}")
        collection = db["emotions"]  # Assign existing collection
    except Exception as e:
        print(f"An error occurred during time series setup: {e}")
        collection = db["emotions"]

# Ensure 'collection' is assigned before routes use it
collection = db["emotions"]

# Security configurations
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


# Helper functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    if JWT_SECRET_KEY is None:
        raise ValueError("JWT_SECRET_KEY is not set in the environment variables")
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# Pydantic model for emotion data
# The emotions are a running average of the last 10 seconds
class EmotionData(BaseModel):
    timestamp: datetime  # Change type from float to datetime
    emotions: dict


# Pydantic models for user management
# Update the User and UserInDB models to include user_id
class User(BaseModel):
    user_id: str  # Add user_id field
    username: str
    email: Optional[str] = None
    disabled: bool = False
    api_keys: list[str] = []


class UserInDB(User):
    hashed_password: str


# Dependency
async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        if JWT_SECRET_KEY is None:
            raise ValueError("JWT_SECRET_KEY is not set in the environment variables")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")  # Get user_id from token
        if user_id is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials (no user_id)"
            )
        # Find user by user_id
        user = await users_collection.find_one({"user_id": user_id})
        if user is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials (user not found)"
            )
        # Add check for disabled status
        if user.get("disabled", False):
            raise HTTPException(status_code=400, detail="Inactive user")
        return UserInDB(**user)
    except JWTError as e:
        print(f"JWTError: {e}")  # Add logging for debugging
        raise HTTPException(
            status_code=401, detail="Invalid authentication credentials (JWTError)"
        )
    except Exception as e:
        print(f"Unexpected error in get_current_user: {e}")  # Add logging for debugging
        raise HTTPException(
            status_code=500, detail="Internal server error during authentication"
        )


# Remove hardcoded API_KEY and validate against the database
@app.post("/emotions")
async def store_emotion_data(data: EmotionData, x_api_key: str = Header(...)):
    # Validate API key against the database
    user = await users_collection.find_one({"api_keys": x_api_key})
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # Pydantic v2 model_dump should preserve datetime objects by default
        data_dict = data.model_dump()
        # Add a server-side timestamp for when the data is received
        data_dict["received_at"] = datetime.utcnow()  # Use datetime for received_at as well
        data_dict["user_id"] = user["user_id"]  # Associate data with the user_id

        # Ensure the collection variable is available (assigned during startup)
        if collection is None:
            raise HTTPException(status_code=500, detail="Emotion collection not initialized")

        # The 'timestamp' field in data_dict should now be a datetime object
        # due to the model definition.
        await collection.insert_one(data_dict)
        return {"message": "Emotion data stored successfully"}
    except Exception as e:
        print(f"Error storing emotion data: {e}")  # Keep detailed logging
        # Provide a more specific error message if possible, otherwise generic
        raise HTTPException(status_code=500, detail=f"Failed to store emotion data: {e}")


# Update user creation to store in the database
class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None  # Make email optional


@app.post("/users")
async def create_user(data: CreateUserRequest):
    username = data.username
    password = data.password
    email = data.email

    if not username or not password:
        raise HTTPException(
            status_code=400, detail="Username and password are required"
        )

    # Keep username check for login purposes
    existing_user = await users_collection.find_one({"username": username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = get_password_hash(password)
    user_id = str(uuid.uuid4())  # Generate user_id
    user_data = {
        "user_id": user_id,  # Store user_id
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "api_keys": [],
        "disabled": False,  # Explicitly set disabled status
    }
    await users_collection.insert_one(user_data)
    return {"message": "User created successfully", "user_id": user_id}  # Return user_id


# Add endpoint to get user details including API keys
@app.get("/users/me", response_model=User)  # Use User model for response
async def get_user_details(current_user: UserInDB = Depends(get_current_user)):
    # current_user already contains the necessary data fetched by user_id
    # No need to query again unless fetching extra data not in UserInDB
    return current_user


# Update user deletion to remove from the database
@app.delete("/users/me")
async def delete_user(current_user: UserInDB = Depends(get_current_user)):
    # Use user_id from the authenticated user context
    result = await users_collection.delete_one({"user_id": current_user.user_id})
    if result.deleted_count == 1:
        return {"message": "User deleted successfully"}
    else:
        # This case should ideally not happen if get_current_user works correctly
        raise HTTPException(status_code=404, detail="User not found")


# Add endpoint to create API keys
@app.post("/users/me/api-keys")
async def create_api_key(current_user: UserInDB = Depends(get_current_user)):
    new_api_key = os.urandom(24).hex()  # Generate a random API key
    # Use user_id from the authenticated user context
    await users_collection.update_one(
        {"user_id": current_user.user_id}, {"$push": {"api_keys": new_api_key}}
    )
    return {"api_key": new_api_key}


@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    # Login still uses username
    user = await users_collection.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Check if user is disabled
    if user.get("disabled", False):
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Create token with user_id in 'sub' claim
    access_token = create_access_token(
        data={"sub": user["user_id"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
