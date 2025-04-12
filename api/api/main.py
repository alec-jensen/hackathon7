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
collection = db["emotions"]

# Add a new collection for users
users_collection = db["users"]

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
    timestamp: float
    emotions: dict


# Pydantic models for user management
# Update the User and UserInDB models to include API keys
class User(BaseModel):
    username: str
    email: Optional[str] = None
    disabled: bool = False
    api_keys: list[str] = []  # Add api_keys field


class UserInDB(User):
    hashed_password: str


# Dependency
async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        if JWT_SECRET_KEY is None:
            raise ValueError("JWT_SECRET_KEY is not set in the environment variables")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials"
            )
        user = await users_collection.find_one({"username": username})
        if user is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials"
            )
        return UserInDB(**user)
    except JWTError:
        raise HTTPException(
            status_code=401, detail="Invalid authentication credentials"
        )


# Remove hardcoded API_KEY and validate against the database
@app.post("/emotions")
async def store_emotion_data(data: EmotionData, x_api_key: str = Header(...)):
    # Validate API key against the database
    user = await users_collection.find_one({"api_keys": x_api_key})
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # Add a server-side timestamp for when the data is received
        data_dict = data.model_dump()
        data_dict["received_at"] = time.time()
        await collection.insert_one(data_dict)  # Use await for async operation
        return {"message": "Emotion data stored successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

    existing_user = await users_collection.find_one({"username": username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = get_password_hash(password)
    user_data = {
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "api_keys": [],  # Initialize with no API keys
    }
    await users_collection.insert_one(user_data)
    return {"message": "User created successfully"}


# Add endpoint to get user details including API keys
@app.get("/users/me")
async def get_user_details(current_user: User = Depends(get_current_user)):
    user = await users_collection.find_one({"username": current_user.username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "username": user["username"],
        "email": user["email"],
        "api_keys": user["api_keys"],
    }


# Update user deletion to remove from the database
@app.delete("/users/me")
async def delete_user(current_user: User = Depends(get_current_user)):
    await users_collection.delete_one({"username": current_user.username})
    return {"message": "User deleted successfully"}


# Add endpoint to create API keys
@app.post("/users/me/api-keys")
async def create_api_key(current_user: User = Depends(get_current_user)):
    new_api_key = os.urandom(24).hex()  # Generate a random API key
    await users_collection.update_one(
        {"username": current_user.username}, {"$push": {"api_keys": new_api_key}}
    )
    return {"api_key": new_api_key}


@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
