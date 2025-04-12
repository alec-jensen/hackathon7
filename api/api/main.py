from fastapi import FastAPI, Depends
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from dotenv import load_dotenv
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import time

from .routes import users, emotions, projects
from .processing import process_emotions_and_repos
from .database import setup_timeseries_collection as db_setup_timeseries, db, users_collection
from .auth import (
    verify_password,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_user,
    UserInDB
)
from fastapi import HTTPException

app = FastAPI()

app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(emotions.router, prefix="/emotions", tags=["emotions"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])

load_dotenv()

MONGO_URI: str | None = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI is not set in the environment variables")

JWT_SECRET_KEY: str | None = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY is not set in the environment variables")

@app.on_event("startup")
async def startup_event():
    start = time.perf_counter()
    print("Starting up database...")
    await db_setup_timeseries()
    print("Database setup completed.")
    print("Starting up scheduler...")
    await start_scheduler()
    end = time.perf_counter()
    print(f"Startup completed in {end - start:.2f} seconds.")

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.get("disabled", False):
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["user_id"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

scheduler = AsyncIOScheduler()

scheduler.add_job(
    process_emotions_and_repos,
    trigger=IntervalTrigger(seconds=300),
    id="process_emotions_and_repos",
    replace_existing=True,
)

async def start_scheduler():
    scheduler.start()
    print("Scheduler started.")

@app.on_event("shutdown")
async def shutdown_scheduler():
    scheduler.shutdown()
    print("Scheduler shut down.")
