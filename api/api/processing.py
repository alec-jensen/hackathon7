from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import asyncio
import aiohttp
import traceback
from collections import defaultdict
from google import genai
from google.genai import types as genai_types
from git import InvalidGitRepositoryError, GitCommandError, Repo
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

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

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN is not set in the environment variables")

async_slack_client = AsyncWebClient(token=SLACK_BOT_TOKEN)

async def slack_get_username_from_id(user_id: str) -> str | None:
    """
    Given a Slack user ID (e.g. 'U12345678'), return their display name.
    Returns None on error.
    """
    try:
        resp = await async_slack_client.users_info(user=user_id)
        if not resp["ok"]:
            print(f"Error fetching user info: {resp['error']}")
            return None

        user = resp.get("user")
        if user is None:
            print("Error fetching user info: user data is missing.")
            return None
        # The profile object holds display_name and real_name
        profile = user.get("profile", {})
        # Prefer the “display_name” (what they’ve set), fallback to real_name
        display_name = profile.get("display_name") or profile.get("real_name")
        return display_name

    except SlackApiError as e:
        print(f"Slack API Error: {e.response['error']}")
        traceback.print_exc()
        return None


async def get_slack_messages_for_user(
    user_id: str, start_time: datetime, end_time: datetime
) -> list[str]:
    """
    Fetch Slack messages for a user within a time range across all channels the bot is a member of.
    Returns a list of message texts.
    """
    # Convert datetimes to Slack timestamps (float seconds)
    # Ensure they are UTC-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    else:
        end_time = end_time.astimezone(timezone.utc)

    oldest = start_time.timestamp()
    latest = end_time.timestamp()

    user_messages: list[str] = []

    try:
        # 1) List all channels the bot is in
        channels = []
        cursor = None
        while True:
            resp = await async_slack_client.conversations_list(
                types="public_channel,private_channel,mpim,im",
                limit=200,
                cursor=cursor,
            )
            channels_data = resp.get("channels", [])
            channels.extend(channels_data)
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        # 2) For each channel, fetch history and filter
        for ch in channels:
            chan_id = ch["id"]
            chan_name = ch.get('name', 'N/A')
            # Check if the bot is a member of the channel before fetching history
            if not ch.get("is_member"):
                print(f"    DEBUG: Skipping channel {chan_id} ({chan_name}) - Bot is not a member.")
                continue

            print(f"    DEBUG: Checking channel {chan_id} ({chan_name}) - Bot is a member.") # Updated debug
            cursor_hist = None
            while True:
                try: # Add try-except block specifically for history fetching
                    history = await async_slack_client.conversations_history(
                        channel=chan_id,
                        oldest=str(oldest),
                        latest=str(latest),
                        limit=200,
                        cursor=cursor_hist,
                    )
                    for msg in history.get("messages", []):
                        # Only consider user messages (not bots) and matching user_id
                        print(f"    DEBUG: Processing message from user {msg.get('user', 'N/A')}: {msg.get('text', '[no text]')}")
                        if "text" in msg: # Check user ID match
                            # get slack username
                            username = await slack_get_username_from_id(msg["user"])
                            if username: # Ensure username was fetched
                                user_messages.append(f"{username}: {msg['text']}")

                    cursor_hist = history.get("response_metadata", {}).get("next_cursor")
                    if not cursor_hist:
                        break
                except SlackApiError as hist_err:
                    # Catch errors specific to fetching history for this channel
                    print(f"    ERROR fetching history for channel {chan_id} ({chan_name}): {hist_err.response['error']}")
                    break # Break inner loop for this channel on error

    except SlackApiError as e:
        # This catches errors from conversations_list primarily
        print(f"    ERROR fetching Slack channel list: {e.response['error']}")
        traceback.print_exc()

    # Deduplicate and return
    # (optional: you might want to preserve order or include timestamps)
    unique_msgs = list(dict.fromkeys(user_messages))
    print(f"    Fetched {len(unique_msgs)} Slack messages for user {user_id}.")
    print(f"    Unique messages: {unique_msgs}")
    return unique_msgs


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
                # Add fetch before pull for robustness
                try:
                    repo.remotes.origin.fetch()
                    repo.remotes.origin.pull()
                except GitCommandError as pull_err:
                    print(
                        f"    WARNING: Git pull/fetch failed for {repo_url}: {pull_err}. Proceeding with local history."
                    )
            else:
                os.makedirs(repo_path, exist_ok=True)
                repo = Repo.clone_from(repo_url, repo_path)

            # Ensure start_time and end_time are UTC-aware before comparison
            if start_time.tzinfo is None:
                print(f"    WARNING: start_time {start_time} was naive. Assuming UTC.")
                start_time = start_time.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC just to be certain it's the correct timezone object
                start_time = start_time.astimezone(timezone.utc)

            if end_time.tzinfo is None:
                print(f"    WARNING: end_time {end_time} was naive. Assuming UTC.")
                end_time = end_time.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC just to be certain it's the correct timezone object
                end_time = end_time.astimezone(timezone.utc)

            commits = repo.iter_commits()
            for commit in commits:
                # Ensure commit datetime is timezone-aware (UTC) for comparison
                commit_dt_aware = commit.authored_datetime
                if commit_dt_aware.tzinfo is not None:
                    commit_dt_utc = commit_dt_aware.astimezone(timezone.utc)
                else:
                    # Keep this warning as it indicates potential data issues
                    print(f"    WARNING: Commit {commit.hexsha} has naive datetime {commit_dt_aware}. Assuming UTC.")
                    commit_dt_utc = commit_dt_aware.replace(tzinfo=timezone.utc)

                # Compare using the UTC-aware datetime
                if (
                    commit_dt_utc < start_time
                    or commit_dt_utc > end_time
                ):
                    continue
                if commit.author.email == user_email:
                    commit_message = commit.message.strip()
                    all_commit_messages.append(commit_message)

        except InvalidGitRepositoryError:
            print(f"    ERROR: Invalid repository path: {repo_path} for URL {repo_url}")
        except GitCommandError as e:
            print(f"    ERROR: Git command failed for {repo_url}: {e}")
        except Exception as e:
            print(f"    ERROR: Unexpected error processing repo {repo_url}: {e}")
            traceback.print_exc()

    return all_commit_messages


# Updated placeholder for LLM call to include commits, slack messages, and check for alarms
async def get_mood_summary_from_llm(
    session: aiohttp.ClientSession,
    avg_emotions: dict,
    commits: list[str],
    slack_messages: list[str], # Add slack_messages parameter
    report_type: str = "Individual",
    previous_reports: list[dict] | None = None,
    individual_summaries: list[tuple[str, str]] | None = None,
) -> tuple[str | None, bool, str | None]:
    """
    Generates a mood summary using an LLM, potentially checking for alarms based on previous reports
    or synthesizing group mood from individual summaries. Includes commit and Slack context. Returns None for summary on failure.

    Returns:
        tuple[str | None, bool, str | None]: (summary, is_alarm, alarm_message) - summary is None on LLM failure.
    """
    commit_log = (
        "\n".join(f"- {msg}" for msg in commits)
        if commits
        else "No recent commits found."
    )
    # Add Slack message log
    slack_log = (
        "\n".join(f"- {msg}" for msg in slack_messages)
        if slack_messages
        else "No recent Slack messages found."
    )

    # --- Prompt Construction ---
    prompt_sections = [
        "Role: You are an AI assistant helping understand developer well-being.",
        "Goal: Provide a concise, easy-to-understand mood summary in a natural, conversational tone. Focus on the main feeling (dominant emotion). For individual reports with history, your *main job* is to spot *significant negative shifts* compared *only* to the *immediate previous report* (the temporal baseline). However, use the *entire provided history* of previous reports to understand the broader context and overall trend. Use the Neutral Mood Reference Baseline just for general context. For group reports, summarize the team's overall vibe.",
        "\nInput Data:",
        f"- Report Type: {report_type}",
    ]
    if "Group" in report_type:
        prompt_sections.append(f"- Group Average Emotions (Scale 0-1): {avg_emotions}")
        prompt_sections.append(f"- All Recent Commits (Group):\n{commit_log}")
        # Note: Not including raw slack messages in group prompt for brevity/focus
        if individual_summaries:
            prompt_sections.append("- Individual Summaries:")
            for username, summary in individual_summaries:
                clean_summary = summary.split('\n')[0]
                if clean_summary.startswith("ALARM: "):
                    clean_summary = clean_summary[len("ALARM: "):].strip()
                prompt_sections.append(f"  - {username}: {clean_summary}")
    else: # Individual report
        prompt_sections.append(f"- Current Average Emotions (Scale 0-1): {avg_emotions}")
        prompt_sections.append(f"- Recent Commits:\n{commit_log}")
        prompt_sections.append(f"- Recent Slack Messages:\n{slack_log}") # Add Slack messages here

    analysis_tasks = ["\nAnalysis Task:"]
    output_instructions = ["\nOutput Instructions:"]

    if previous_reports and "Individual" in report_type:
        # ... (rest of the individual report prompt logic remains largely the same) ...
        # Modify analysis tasks slightly to include Slack context
        analysis_tasks.extend([
            "1. **Identify Temporal Baseline:** Use the 'Immediate Temporal Baseline' (most recent previous report) Avg Emotions as the reference point for *alarm change detection*.",
            "2. **Analyze Current State:** Look at the 'Current Average Emotions'. What's the main feeling (highest score)? How does the overall mood compare to the 'Neutral Mood Reference Baseline' generally? Use 'Recent Commits' and 'Recent Slack Messages' for context.", # Added Slack context
            "3. **Analyze Trend:** How have things changed between the Current state and the *Immediate Temporal Baseline*? Also, consider the *Full Provided History* to understand the longer-term trend.",
            "4. **Check for ALARM Condition (Based *only* on Change from *Immediate* Temporal Baseline):**",
            # ... (alarm conditions remain the same) ...
        ])
        # Modify output instructions slightly
        output_instructions = [
            # ... (alarm output remains the same) ...
            "- **ELSE (No Alarm: Mood is Stable, Improved, or Minor Change from *Immediate* Temporal Baseline):**",
            "  - Write a brief (2-3 sentence) summary of how the developer seems to be feeling *currently*, in a natural, conversational way. *Highlight the main emotion(s)*.",
            "  - Mention the *overall trend* considering the *Full Provided History* (e.g., 'Mood seems pretty stable compared to last time, continuing an upward trend observed over the past few reports...', 'While slightly better than the last report, the overall trend across the provided history has been somewhat negative...', 'Looks like things have improved since the last report...').",
            "  - Briefly relate the current state to the Neutral Mood Reference Baseline (e.g., '...which is generally within the neutral range.', '...still a bit higher than the neutral baseline.').",
            "  - Weave in insights from emotions, commits, and Slack messages if they add helpful context.", # Added Slack context
            "- **Constraint:** Alarm decision is based *strictly* on the change from the *Immediate* Temporal Baseline. For non-alarm summaries, describe the current mood naturally, mention the trend based on the *full history provided*, compare generally to the Neutral Baseline, *focus on the dominant feeling(s)*, and consider commit/Slack context.", # Added Slack context
        ]
    elif "Group" in report_type:
        # ... (group report prompt logic remains the same) ...
        analysis_tasks.extend([
            "1. Synthesize Group Vibe: Based on 'Group Average Emotions', 'All Recent Commits', and 'Individual Summaries', what's the overall team mood? Pay attention to the main group feeling(s).",
            "2. Contextualize: How does the 'Group Average Emotions' generally compare to the 'Neutral Mood Reference Baseline'?",
            "3. Identify Themes: Any common threads, differences, or trends popping up?",
        ])
        output_instructions = [
            # ... (group output instructions remain the same) ...
        ]
    else: # Individual report without history
        analysis_tasks.append("1. Evaluate Current State: What's the main feeling based on 'Current Average Emotions'? *Highlight the dominant emotion(s)*. How does it generally compare to the 'Neutral Mood Reference Baseline'? Use 'Recent Commits' and 'Recent Slack Messages' for extra context.") # Added Slack context
        output_instructions.append("- Write a brief (2-3 sentence) summary of how the developer seems to be feeling right now, in a natural, conversational tone. Draw a main conclusion that *highlights the dominant emotion(s)*. Relate the mood generally to the Neutral Mood Reference Baseline. Weave in insights from emotions, commits, and Slack messages if helpful.") # Added Slack context

    prompt_sections.extend(analysis_tasks)
    prompt_sections.extend(output_instructions)
    prompt_sections.append("\nSummary:")
    prompt = "\n".join(prompt_sections)

    # --- System Instruction Update ---
    system_instruction_text = (
        "You are an AI assistant helping understand developer well-being. Your goal is to provide summaries that sound natural and human-written, not robotic or overly analytical. Use the 'Neutral Mood Reference Baseline' (with +/- 0.15 buffer) just for general context. Always focus on and emphasize the dominant (highest scoring) emotion(s) in your summary. Use provided commit logs and Slack messages for additional context when assessing individual mood. " # Added Slack context mention
        "For individual reports *with history*, your primary task is to detect *significant negative shifts* compared *strictly* to the *immediate previous report* (Temporal Baseline). "
        "Trigger an alarm *ONLY* if negative emotions substantially *increase* OR positive emotions substantially *decrease* relative to that *immediate* Temporal Baseline. "
        "**CRITICAL: DO NOT trigger an alarm based on deviation from the Neutral Reference Baseline, or if the mood is stable or improved compared to the *immediate* Temporal Baseline.** "
        "When describing the mood trend in non-alarm summaries, consider the *entire provided history* of reports for context. "
        "For group reports, summarize the overall team vibe conversationally, referencing the Neutral Baseline for context and highlighting dominant emotions. For all non-alarm summaries, mention the trend (using full history if available), relate the current state generally to the Neutral Reference Baseline, emphasize the dominant emotion(s) in a natural way, and consider commit/Slack context." # Added Slack context mention
    )
    config = genai_types.GenerateContentConfig(
        system_instruction=system_instruction_text,
        temperature=0.5
    )

    print(f"    Sending prompt to LLM (length: {len(prompt)} chars)")
    try:
        response = await gemini_client.aio.models.generate_content(
            model="gemini-2.0-flash-thinking-exp-01-21",
            contents=prompt,
            config=config
        )
        full_response = response.text
        if not full_response:
            print("    ERROR: LLM returned an empty response.")
            return None, False, None
        print(f"    LLM response: {full_response}")
    except Exception as e:
        print(f"    ERROR: LLM request failed: {e}")
        traceback.print_exc()
        return None, False, None

    is_alarm = False
    alarm_message = None
    summary = full_response
    alarm_prefix = "ALARM: "
    if full_response.startswith(alarm_prefix) and previous_reports and "Individual" in report_type:
        is_alarm = True
        alarm_message = full_response[len(alarm_prefix):].strip().split('\n')[0]
        print(f"    ALARM DETECTED: {alarm_message}")

    if not previous_reports or "Group" in report_type:
        if is_alarm:
            print("    INFO: Correcting wrongly set alarm flag (no previous reports or group report).")
            is_alarm = False
            alarm_message = None
        if summary.startswith(alarm_prefix):
             summary = summary[len(alarm_prefix):].lstrip()

    return summary, is_alarm, alarm_message


async def process_emotions_and_repos():
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

            project_all_emotion_entries = []
            project_all_commit_messages = []
            project_min_start_time = None
            project_max_end_time = None
            processed_user_count = 0
            individual_summaries_for_group: list[tuple[str, str]] = []

            for user_id in members:
                print(f"  Processing user: {user_id}")
                user_data = await users_collection.find_one({"user_id": user_id})
                if not user_data or not user_data.get("email"):
                    print(
                        f"    Skipping user {user_id}: No email found for commit filtering."
                    )
                    continue
                user_email = user_data["email"]
                print(f"    User email: {user_email}")

                last_report = await mood_reports_collection.find_one(
                    {
                        "user_id": user_id,
                        "project_id": project_id,
                        "report_type": "individual",
                    },
                    sort=[("report_timestamp", -1)],
                )
                last_report_time = (
                    last_report["end_time"]
                    if last_report
                    else datetime.min.replace(tzinfo=timezone.utc)
                )
                print(f"    Last individual report end time: {last_report_time}")

                current_processing_time = datetime.now(timezone.utc)

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

                start_time = last_report_time if last_report else new_emotions_data[0]["timestamp"]
                end_time = new_emotions_data[-1]["timestamp"]
                print(f"    Processing window: {start_time} -> {end_time}")

                data_start_time = new_emotions_data[0]["timestamp"]
                data_end_time = new_emotions_data[-1]["timestamp"]

                if (
                    project_min_start_time is None
                    or data_start_time < project_min_start_time
                ):
                    project_min_start_time = data_start_time
                if project_max_end_time is None or data_end_time > project_max_end_time:
                    project_max_end_time = data_end_time

                project_all_emotion_entries.extend(new_emotions_data)

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

                print(
                    f"    Fetching commits for {user_email} between {start_time} and {end_time}"
                )
                commit_messages = await get_commits_for_user(
                    project_id, user_email, start_time, end_time
                )
                print(f"    Found {len(commit_messages)} relevant commits.")
                project_all_commit_messages.extend(commit_messages)

                # Fetch Slack messages for the user in the same time window
                slack_messages = await get_slack_messages_for_user(
                    user_id, start_time, end_time
                )
                # Note: project_all_slack_messages is not aggregated for group report simplicity

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
                )
                print(
                    f"    Fetched {len(previous_reports)} previous reports for alarm check."
                )

                username = user_data.get('username', 'Unknown')
                mood_summary, is_alarm, alarm_message = await get_mood_summary_from_llm(
                    session,
                    average_emotions,
                    commit_messages,
                    slack_messages, # Pass fetched slack messages
                    report_type=f"Individual for {username}",
                    previous_reports=previous_reports,
                    individual_summaries=None
                )

                if mood_summary is None:
                    print(f"    ERROR: Failed to generate mood summary for user {user_id}. Skipping report save.")
                    continue

                print(f"    Generated individual mood summary: {mood_summary}")
                if is_alarm:
                    print(f"    ALARM TRIGGERED for user {user_id}: {alarm_message}")

                individual_summaries_for_group.append((username, mood_summary))

                report_timestamp = datetime.now(timezone.utc)
                new_report_data = {
                    "user_id": user_id,
                    "project_id": project_id,
                    "report_timestamp": report_timestamp,
                    "start_time": start_time,
                    "end_time": end_time,
                    "average_emotions": average_emotions,
                    "mood_summary": mood_summary,
                    "processed_entries": total_entries,
                    "commit_count": len(commit_messages),
                    "report_type": "individual",
                    "is_alarm": is_alarm,
                    "alarm_message": alarm_message,
                }
                await mood_reports_collection.insert_one(new_report_data)
                print(
                    f"    Stored new individual mood report for user {user_id} in project {project_id}."
                )

            if processed_user_count > 0 and project_all_emotion_entries:
                print(f"  Generating group report for project {project_id}...")

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

                group_mood_summary, _, _ = await get_mood_summary_from_llm(
                    session,
                    group_average_emotions,
                    project_all_commit_messages,
                    [], # Pass empty list for slack messages for group report
                    report_type="Group",
                    previous_reports=None,
                    individual_summaries=individual_summaries_for_group
                )

                if group_mood_summary is None:
                    print(f"    ERROR: Failed to generate group mood summary for project {project_id}. Skipping report save.")
                    continue

                print(f"    Generated group mood summary: {group_mood_summary}")

                group_report_timestamp = datetime.now(timezone.utc)
                group_report_data = {
                    "user_id": None,
                    "project_id": project_id,
                    "report_timestamp": group_report_timestamp,
                    "start_time": project_min_start_time,
                    "end_time": project_max_end_time,
                    "average_emotions": group_average_emotions,
                    "mood_summary": group_mood_summary,
                    "processed_entries": len(project_all_emotion_entries),
                    "commit_count": len(project_all_commit_messages),
                    "processed_user_count": processed_user_count,
                    "report_type": "group",
                    "is_alarm": False,
                    "alarm_message": None,
                }
                await mood_reports_collection.insert_one(group_report_data)
                print(f"    Stored new group mood report for project {project_id}.")
            else:
                print(
                    f"  Skipping group report for project {project_id}: No new data processed or only failed individual reports."
                )

        print("Finished processing emotions for reports.")
