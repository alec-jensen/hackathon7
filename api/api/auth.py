from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import timedelta, datetime
from passlib.context import CryptContext
from .models import UserInDB
from .database import users_collection
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Security configurations
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 43800  # 30 days
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY is not set in the environment variables")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

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
        raise ValueError("JWT_SECRET_KEY is not set")
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if JWT_SECRET_KEY is None:
        raise ValueError("JWT_SECRET_KEY is not set")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials (no user_id)"
            )
        user = await users_collection.find_one({"user_id": user_id})
        if user is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials (user not found)"
            )
        if user.get("disabled", False):
            raise HTTPException(status_code=400, detail="Inactive user")
        return UserInDB(**user)
    except JWTError:
        raise HTTPException(
            status_code=401, detail="Invalid authentication credentials (JWTError)"
        )