from datetime import datetime
from dotenv import load_dotenv
import os
import aiohttp
import git
from git import InvalidGitRepositoryError, GitCommandError
from .database import (
    setup_timeseries_collection,
    projects_collection,
    users_collection,
    emotions_collection,
)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in the environment variables")


async def process_emotions_and_repos():
    """curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=GEMINI_API_KEY" \
-H 'Content-Type: application/json' \
-X POST \
-d '{
  "contents": [{
    "parts":[{"text": "Explain how AI works"}]
    }]
   }'
    """
    async with aiohttp.ClientSession() as session:
        print(f"Processing emotions and repositories at {datetime.utcnow()}...")

        commits = await get_commits_from_repos()
        if not commits:
            print("No commits found.")
            return
        print(f"Found {len(commits)} commits.")
        print(commits)
        pass


async def get_commits_from_repos():
    """Fetch commits from all repositories in the projects."""
    async with aiohttp.ClientSession() as session:
        projects = await projects_collection.find({}).to_list(length=None)
        commits = []
        for project in projects:
            if "repos" in project:
                for repo_url in project["repos"]:
                    try:
                        repo = git.Repo(repo_url)
                    except InvalidGitRepositoryError:
                        print(f"Invalid repository: {repo_url}")
                    except GitCommandError as e:
                        print(f"Git command error: {e}")

        return commits
