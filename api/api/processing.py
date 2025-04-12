from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import asyncio
import aiohttp
from collections import defaultdict
from google import genai
from git import InvalidGitRepositoryError, GitCommandError, Repo
from .database import (
    projects_collection,
    users_collection,
    emotions_collection,
    mood_reports_collection,
)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in the environment variables")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# Function to fetch commits for a specific user in a project within a time range
async def get_commits_for_user(
    project_id: str, user_email: str, start_time: datetime, end_time: datetime
) -> list[str]:
    """Fetch commit messages for a user within a project and time range."""
    project = await projects_collection.find_one({"project_id": project_id})
    if not project or "repos" not in project:
        return []

    all_commit_messages = []
    repo_base_path = f"/tmp/git_repos/{project_id}"  # Base path for clones

    for repo_url in project["repos"]:
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        repo_path = os.path.join(repo_base_path, repo_name)

        try:
            # Clone or pull the repo
            if os.path.exists(repo_path):
                repo = Repo(repo_path)
                print(f"    Fetching updates for repo: {repo_path}")
                repo.remotes.origin.pull()
            else:
                print(f"    Cloning repo: {repo_url} to {repo_path}")
                os.makedirs(repo_path, exist_ok=True)
                repo = Repo.clone_from(repo_url, repo_path)

            # Iterate through commits and filter
            commits = repo.iter_commits(
                since=start_time.isoformat(), until=end_time.isoformat()
            )
            for commit in commits:
                if commit.author.email == user_email:
                    all_commit_messages.append(commit.message.strip())

        except InvalidGitRepositoryError:
            print(f"    ERROR: Invalid repository path: {repo_path} for URL {repo_url}")
        except GitCommandError as e:
            print(f"    ERROR: Git command failed for {repo_url}: {e}")
        except Exception as e:
            print(f"    ERROR: Unexpected error processing repo {repo_url}: {e}")

    return all_commit_messages


# Updated placeholder for LLM call to include commits and check for alarms
async def get_mood_summary_from_llm(
    session: aiohttp.ClientSession,
    avg_emotions: dict,
    commits: list[str],
    report_type: str = "Individual",
    previous_reports: list[dict] | None = None,
) -> tuple[str, bool, str | None]:
    """
    Generates a mood summary using an LLM, potentially checking for alarms based on previous reports.

    Returns:
        tuple[str, bool, str | None]: (summary, is_alarm, alarm_message)
    """
    commit_log = (
        "\n".join(f"- {msg}" for msg in commits)
        if commits
        else "No recent commits found."
    )

    prompt_sections = [
        f"Report Type: {report_type}",
        f"Current Average Emotions:\n{avg_emotions}\n",
        f"Recent Commits:\n{commit_log}\n",
    ]

    if previous_reports:
        prompt_sections.append("Previous Mood States:")
        for i, report in enumerate(previous_reports):
            prev_avg_emotions = report.get("average_emotions", {})
            prev_summary = report.get("mood_summary", "N/A")
            prev_time = report.get("end_time", "N/A")
            prompt_sections.append(
                f"  Report {i+1} (ended {prev_time}): Avg Emotions: {prev_avg_emotions}, Summary: {prev_summary}"
            )
        prompt_sections.append(
            "\nInstruction: Analyze the mood progression from previous reports to the current state. "
            "If you detect a significant negative trend or rapid decline, start your response *exactly* with 'ALARM: ' "
            "followed by a concise explanation (max 30 words). Otherwise, provide only the regular mood summary based on the current data."
        )
    else:
        prompt_sections.append(
            "\nInstruction: Provide a brief mood summary based on the current data."
        )

    prompt_sections.append("\nSummary:")
    prompt = "\n".join(prompt_sections)

    print(f"    Sending prompt to LLM: {prompt}")
    try:
        response = await gemini_client.aio.models.generate_content(
            model="gemini-2.0-flash-lite", contents=prompt
        )
        full_response = response.text
        if not full_response:
            raise ValueError("Empty response from LLM.")
        print(f"    LLM response: {full_response}")
    except Exception as e:
        print(f"    ERROR: LLM request failed: {e}")
        return "Error generating mood summary.", False, None

    # Parse response for alarm
    is_alarm = False
    alarm_message = None
    summary = full_response
    alarm_prefix = "ALARM: "
    if full_response.startswith(alarm_prefix):
        is_alarm = True
        # Extract alarm message and potentially clean the summary
        parts = full_response.split("\n", 1)
        alarm_message = parts[0][len(alarm_prefix) :].strip()
        # Decide if the rest of the response should be part of the main summary
        # For now, let's keep the full response as the 'summary' field might show context
        # If you want a clean summary without the alarm prefix/message:
        # summary = parts[1].strip() if len(parts) > 1 else "Alarm triggered."
        print(f"    ALARM DETECTED: {alarm_message}")

    return summary, is_alarm, alarm_message


async def process_emotions_and_repos():
    """
    Processes new emotion data and commits for each user in each project since their last mood report,
    generates individual and group mood summaries using an LLM, and stores the reports.
    """
    async with aiohttp.ClientSession() as session:
        print(f"Processing emotions for reports at {datetime.now(timezone.utc)}...")

        projects = await projects_collection.find({}).to_list(length=None)
        if not projects:
            print("No projects found.")
            return

        for project in projects:
            project_id = project["project_id"]
            members = project.get("members", [])
            if not members:
                print(f"Project {project_id} has no members.")
                continue

            print(f"Processing project: {project_id} ({project.get('name', 'N/A')})")

            # Data aggregation for the group report
            project_all_emotion_entries = []
            project_all_commit_messages = []
            project_min_start_time = None
            project_max_end_time = None
            processed_user_count = 0

            for user_id in members:
                print(f"  Processing user: {user_id}")
                # Fetch user data to get email for commit filtering
                user_data = await users_collection.find_one({"user_id": user_id})
                if not user_data or not user_data.get("email"):
                    print(
                        f"    Skipping user {user_id}: No email found for commit filtering."
                    )
                    continue
                user_email = user_data["email"]
                print(f"    User email: {user_email}")

                # Find the timestamp of the last report for this user and project
                last_report = await mood_reports_collection.find_one(
                    {
                        "user_id": user_id,
                        "project_id": project_id,
                    },  # Filter for individual report
                    sort=[("report_timestamp", -1)],
                )
                last_report_time = (
                    last_report["end_time"]
                    if last_report
                    else datetime.min.replace(tzinfo=timezone.utc)
                )
                print(f"    Last individual report end time: {last_report_time}")

                # Define the end time for the current processing window
                current_processing_time = datetime.now(timezone.utc)

                # Find new emotion data since the last report ended up to now
                new_emotions_cursor = emotions_collection.find(
                    {
                        "user_id": user_id,
                        "timestamp": {
                            "$gt": last_report_time,
                            "$lte": current_processing_time,
                        },
                    }
                ).sort("timestamp", 1)
                new_emotions_data = await new_emotions_cursor.to_list(length=None)

                if not new_emotions_data:
                    print(
                        f"    No new emotion data found for user {user_id} in project {project_id} since last report."
                    )
                    continue

                processed_user_count += 1
                print(f"    Found {len(new_emotions_data)} new emotion entries.")

                # Determine start and end time of the new data period
                start_time = new_emotions_data[0]["timestamp"]
                end_time = new_emotions_data[-1]["timestamp"]

                # Update project time window
                if (
                    project_min_start_time is None
                    or start_time < project_min_start_time
                ):
                    project_min_start_time = start_time
                if project_max_end_time is None or end_time > project_max_end_time:
                    project_max_end_time = end_time

                # Aggregate data for group report
                project_all_emotion_entries.extend(new_emotions_data)

                # Calculate average emotions for the new period
                emotion_sums = defaultdict(float)
                emotion_counts = defaultdict(int)
                total_entries = len(new_emotions_data)
                for entry in new_emotions_data:
                    for emotion, value in entry.get("emotions", {}).items():
                        if isinstance(value, (int, float)):
                            emotion_sums[emotion] += value
                            emotion_counts[emotion] += 1
                average_emotions = {
                    emotion: emotion_sums[emotion] / emotion_counts[emotion]
                    for emotion in emotion_sums
                    if emotion_counts[emotion] > 0
                }
                print(f"    Calculated individual average emotions: {average_emotions}")

                # Fetch commit messages for the user in this project during the report period
                print(
                    f"    Fetching commits for {user_email} between {start_time} and {end_time}"
                )
                commit_messages = await get_commits_for_user(
                    project_id, user_email, start_time, end_time
                )
                print(f"    Found {len(commit_messages)} relevant commits.")
                project_all_commit_messages.extend(commit_messages)  # Aggregate commits

                # Fetch previous reports for alarm checking
                previous_reports = (
                    await mood_reports_collection.find(
                        {
                            "user_id": user_id,
                            "project_id": project_id,
                            "report_type": "individual",
                        },
                        sort=[("end_time", -1)],
                    )
                    .limit(2)
                    .to_list(length=2)
                )  # Fetch last 2 reports
                print(
                    f"    Fetched {len(previous_reports)} previous reports for alarm check."
                )

                # Generate mood summary using LLM, including commits and previous reports for alarm check
                mood_summary, is_alarm, alarm_message = await get_mood_summary_from_llm(
                    session,
                    average_emotions,
                    commit_messages,
                    report_type=f"Individual for {user_data.get('username', 'Unknown')}",
                    previous_reports=previous_reports,  # Pass previous reports
                )
                print(f"    Generated individual mood summary: {mood_summary}")
                if is_alarm:
                    print(f"    ALARM TRIGGERED for user {user_id}: {alarm_message}")

                # Store the new report
                report_timestamp = datetime.now(timezone.utc)
                new_report_data = {
                    "user_id": user_id,  # Individual user ID
                    "project_id": project_id,
                    "report_timestamp": report_timestamp,
                    "start_time": start_time,
                    "end_time": end_time,
                    "average_emotions": average_emotions,
                    "mood_summary": mood_summary,  # Store the full summary (may include ALARM prefix)
                    "processed_entries": total_entries,
                    "commit_count": len(commit_messages),
                    "report_type": "individual",
                    "is_alarm": is_alarm,  # Store alarm status
                    "alarm_message": alarm_message,  # Store alarm message (if any)
                }
                await mood_reports_collection.insert_one(new_report_data)
                print(
                    f"    Stored new individual mood report for user {user_id} in project {project_id}."
                )

            # After processing all users in the project, generate group report if data was found
            if processed_user_count > 0 and project_all_emotion_entries:
                print(f"  Generating group report for project {project_id}...")

                # Calculate overall average emotions for the project group
                group_emotion_sums = defaultdict(float)
                group_emotion_counts = defaultdict(int)
                for entry in project_all_emotion_entries:
                    for emotion, value in entry.get("emotions", {}).items():
                        if isinstance(value, (int, float)):
                            group_emotion_sums[emotion] += value
                            group_emotion_counts[emotion] += 1

                group_average_emotions = {
                    emotion: group_emotion_sums[emotion] / group_emotion_counts[emotion]
                    for emotion in group_emotion_sums
                    if group_emotion_counts[emotion] > 0
                }
                print(
                    f"    Calculated group average emotions: {group_average_emotions}"
                )
                print(
                    f"    Total group commits considered: {len(project_all_commit_messages)}"
                )

                # Generate group mood summary using LLM
                group_mood_summary, _, _ = await get_mood_summary_from_llm(
                    session,
                    group_average_emotions,
                    project_all_commit_messages,
                    report_type="Group",
                )
                print(f"    Generated group mood summary: {group_mood_summary}")

                # Store the group report
                group_report_timestamp = datetime.now(timezone.utc)
                group_report_data = {
                    "user_id": None,  # Indicate group report
                    "project_id": project_id,
                    "report_timestamp": group_report_timestamp,
                    "start_time": project_min_start_time,  # Use aggregated start time
                    "end_time": project_max_end_time,  # Use aggregated end time
                    "average_emotions": group_average_emotions,
                    "mood_summary": group_mood_summary,
                    "processed_entries": len(project_all_emotion_entries),
                    "commit_count": len(project_all_commit_messages),
                    "processed_user_count": processed_user_count,  # Add count of users included
                    "report_type": "group",  # Add report type
                    "is_alarm": False,  # Default for group reports
                    "alarm_message": None,  # Default for group reports
                }
                await mood_reports_collection.insert_one(group_report_data)
                print(f"    Stored new group mood report for project {project_id}.")
            else:
                print(
                    f"  Skipping group report for project {project_id}: No new data processed."
                )

        print("Finished processing emotions for reports.")
