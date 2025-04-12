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

# for model in gemini_client.models.list():
#     print(f"Available model: {model.name}")


# Function to fetch commits for a specific user in a project within a time range
async def get_commits_for_user(
    project_id: str, user_email: str, start_time: datetime, end_time: datetime
) -> list[str]:
    """Fetch commit messages for a user within a project and time range."""
    print(
        f"    DEBUG: Searching commits for user '{user_email}' in project '{project_id}' between {start_time} and {end_time}"
    )
    project = await projects_collection.find_one({"project_id": project_id})
    if not project or "repos" not in project:
        print(f"    DEBUG: Project '{project_id}' not found or has no repos.")
        return []

    all_commit_messages = []
    repo_base_path = f"/tmp/git_repos/{project_id}"  # Base path for clones

    for repo_url in project["repos"]:
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        repo_path = os.path.join(repo_base_path, repo_name)
        print(f"    DEBUG: Processing repo URL: {repo_url} at path: {repo_path}")

        try:
            # Clone or pull the repo
            if os.path.exists(repo_path):
                repo = Repo(repo_path)
                print(f"    DEBUG: Fetching updates for existing repo: {repo_path}")
                # Add fetch before pull for robustness
                try:
                    repo.remotes.origin.fetch()
                    repo.remotes.origin.pull()
                except GitCommandError as pull_err:
                    print(
                        f"    WARNING: Git pull/fetch failed for {repo_url}: {pull_err}. Proceeding with local history."
                    )
            else:
                print(f"    DEBUG: Cloning repo: {repo_url} to {repo_path}")
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

            print(
                f"    DEBUG: Iterating commits (using UTC range: {start_time} to {end_time})"
            )
            commits = repo.iter_commits()
            commit_count_in_range = 0
            found_user_commits = 0
            for commit in commits:
                commit_count_in_range += 1
                # Ensure commit datetime is timezone-aware (UTC) for comparison
                commit_dt_aware = commit.authored_datetime
                if commit_dt_aware.tzinfo is not None:
                    commit_dt_utc = commit_dt_aware.astimezone(timezone.utc)
                else:
                    print(f"    WARNING: Commit {commit.hexsha} has naive datetime {commit_dt_aware}. Assuming UTC.")
                    commit_dt_utc = commit_dt_aware.replace(tzinfo=timezone.utc)

                print(
                    f"    DEBUG: Checking commit {commit.hexsha} by {commit.author.email} at {commit_dt_utc}"
                )
                print(
                    f"    DEBUG: Author email matches: {commit.author.email == user_email}"
                )

                # Compare using the UTC-aware datetime
                if (
                    commit_dt_utc < start_time
                    or commit_dt_utc > end_time
                ):
                    print(f"    DEBUG: Commit {commit.hexsha} ({commit_dt_utc}) not in range ({start_time} to {end_time}).")
                    continue
                if commit.author.email == user_email:
                    found_user_commits += 1
                    commit_message = commit.message.strip()
                    all_commit_messages.append(commit_message)
                    print(
                        f"    DEBUG: Found commit by {user_email}: {commit.hexsha[:7]} - '{commit_message[:50]}...'"
                    )

            print(
                f"    DEBUG: Checked {commit_count_in_range} commits for repo {repo_name}. Found {found_user_commits} matching user {user_email} within time range."
            )

        except InvalidGitRepositoryError:
            print(f"    ERROR: Invalid repository path: {repo_path} for URL {repo_url}")
        except GitCommandError as e:
            print(f"    ERROR: Git command failed for {repo_url}: {e}")
        except Exception as e:
            print(f"    ERROR: Unexpected error processing repo {repo_url}: {e}")
            traceback.print_exc()

    print(
        f"    DEBUG: Total commits found for {user_email} in project {project_id}: {len(all_commit_messages)}"
    )
    return all_commit_messages


# Updated placeholder for LLM call to include commits and check for alarms
async def get_mood_summary_from_llm(
    session: aiohttp.ClientSession,
    avg_emotions: dict,
    commits: list[str],
    report_type: str = "Individual",
    previous_reports: list[dict] | None = None,
    individual_summaries: list[tuple[str, str]] | None = None,
) -> tuple[str | None, bool, str | None]:
    """
    Generates a mood summary using an LLM, potentially checking for alarms based on previous reports
    or synthesizing group mood from individual summaries. Returns None for summary on failure.

    Returns:
        tuple[str | None, bool, str | None]: (summary, is_alarm, alarm_message) - summary is None on LLM failure.
    """
    commit_log = (
        "\n".join(f"- {msg}" for msg in commits)
        if commits
        else "No recent commits found."
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
        if individual_summaries:
            prompt_sections.append("- Individual Summaries:")
            for username, summary in individual_summaries:
                clean_summary = summary.split('\n')[0]
                if clean_summary.startswith("ALARM: "):
                    clean_summary = clean_summary[len("ALARM: "):].strip()
                prompt_sections.append(f"  - {username}: {clean_summary}")
    else:
        prompt_sections.append(f"- Current Average Emotions (Scale 0-1): {avg_emotions}")
        prompt_sections.append(f"- Recent Commits:\n{commit_log}")

    analysis_tasks = ["\nAnalysis Task:"]
    output_instructions = ["\nOutput Instructions:"]

    if previous_reports and "Individual" in report_type:
        previous_reports.sort(key=lambda r: r.get('end_time', datetime.min.replace(tzinfo=timezone.utc)), reverse=False)
        baseline_report = previous_reports[-1]
        baseline_avg_emotions = baseline_report.get("average_emotions", {})
        baseline_summary = baseline_report.get("mood_summary", "N/A").split('\n')[0]
        baseline_time = baseline_report.get("end_time", "N/A")
        prompt_sections.append(f"- Immediate Temporal Baseline (Most Recent Previous Report, ended {baseline_time}): Avg Emotions: {baseline_avg_emotions}, Prev Summary: {baseline_summary}")
        prompt_sections.append("- Full Provided History (Oldest to Newest):")
        for i, report in enumerate(previous_reports):
            report_time = report.get("end_time", "N/A")
            report_avg_emotions = report.get("average_emotions", {})
            report_summary = report.get("mood_summary", "N/A").split('\n')[0]
            prompt_sections.append(f"  - Report {i+1} (ended {report_time}): Avg Emotions: {report_avg_emotions}, Prev Summary: {report_summary}")

        analysis_tasks.extend([
            "1. **Identify Temporal Baseline:** Use the 'Immediate Temporal Baseline' (most recent previous report) Avg Emotions as the reference point for *alarm change detection*.",
            "2. **Analyze Current State:** Look at the 'Current Average Emotions'. What's the main feeling (highest score)? How does the overall mood compare to the 'Neutral Mood Reference Baseline' generally?",
            "3. **Analyze Trend:** How have things changed between the Current state and the *Immediate Temporal Baseline*? Also, consider the *Full Provided History* to understand the longer-term trend.",
            "4. **Check for ALARM Condition (Based *only* on Change from *Immediate* Temporal Baseline):**",
            "   - **Trigger ALARM *ONLY IF*:** There's a *clear and substantial WORSENING* compared to the *Immediate* Temporal Baseline. This means:",
            "     - A *noticeable INCREASE* (e.g., >0.1 absolute increase) in 'anger', 'sadness', or 'fear'.",
            "     - *OR* a *noticeable DECREASE* (e.g., >0.1 absolute decrease) in 'happy'.",
            "   - ***DO NOT TRIGGER ALARM IF:***",
            "     - The change from the *Immediate* Temporal Baseline is small (e.g., <0.05 absolute difference for key emotions).",
            "     - The Current State shows *ANY improvement* compared to the *Immediate* Temporal Baseline.",
            "     - There is no Temporal Baseline report provided.",
            "   - The comparison to the Neutral Mood Reference Baseline is for context, *not* for triggering alarms.",
        ])
        output_instructions = [
            "- **IF ALARM Condition is met (Significant Negative Shift from *Immediate* Temporal Baseline):**",
            "  - Start response *exactly* with `ALARM: `.",
            "  - Briefly state the *specific negative change* from the *Immediate* Temporal Baseline causing the alarm (e.g., 'Seems like sadness has increased notably since the last check-in.'). Keep it short (max 20 words).",
            "  - *Do not* add any other summary after the alarm line.",
            "- **ELSE (No Alarm: Mood is Stable, Improved, or Minor Change from *Immediate* Temporal Baseline):**",
            "  - Write a brief (2-3 sentence) summary of how the developer seems to be feeling *currently*, in a natural, conversational way. *Highlight the main emotion(s)*.",
            "  - Mention the *overall trend* considering the *Full Provided History* (e.g., 'Mood seems pretty stable compared to last time, continuing an upward trend observed over the past few reports...', 'While slightly better than the last report, the overall trend across the provided history has been somewhat negative...', 'Looks like things have improved since the last report...').",
            "  - Briefly relate the current state to the Neutral Mood Reference Baseline (e.g., '...which is generally within the neutral range.', '...still a bit higher than the neutral baseline.').",
            "  - Weave in insights from emotions and commits if they add helpful context.",
            "- **Constraint:** Alarm decision is based *strictly* on the change from the *Immediate* Temporal Baseline. For non-alarm summaries, describe the current mood naturally, mention the trend based on the *full history provided*, compare generally to the Neutral Baseline, and *focus on the dominant feeling(s)*.",
        ]
    elif "Group" in report_type:
        analysis_tasks.extend([
            "1. Synthesize Group Vibe: Based on 'Group Average Emotions', 'All Recent Commits', and 'Individual Summaries', what's the overall team mood? Pay attention to the main group feeling(s).",
            "2. Contextualize: How does the 'Group Average Emotions' generally compare to the 'Neutral Mood Reference Baseline'?",
            "3. Identify Themes: Any common threads, differences, or trends popping up?",
        ])
        output_instructions = [
            "- Write a brief (3-4 sentence) summary of the team's overall mood in a natural, conversational tone. *Highlight the main group feeling(s)*.",
            "- Mention how the group average generally compares to the Neutral Mood Reference Baseline.",
            "- Mention any interesting trends, common feelings, or big differences you noticed.",
            "- Keep it a high-level overview.",
            "- *Do not* use the `ALARM:` prefix for group reports.",
        ]
    else:
        analysis_tasks.append("1. Evaluate Current State: What's the main feeling based on 'Current Average Emotions'? *Highlight the dominant emotion(s)*. How does it generally compare to the 'Neutral Mood Reference Baseline'? Use 'Recent Commits' for extra context.")
        output_instructions.append("- Write a brief (2-3 sentence) summary of how the developer seems to be feeling right now, in a natural, conversational tone. Draw a main conclusion that *highlights the dominant emotion(s)*. Relate the mood generally to the Neutral Mood Reference Baseline. Weave in insights from emotions and commits if helpful.")

    prompt_sections.extend(analysis_tasks)
    prompt_sections.extend(output_instructions)
    prompt_sections.append("\nSummary:")
    prompt = "\n".join(prompt_sections)

    system_instruction_text = (
        "You are an AI assistant helping understand developer well-being. Your goal is to provide summaries that sound natural and human-written, not robotic or overly analytical. Use the 'Neutral Mood Reference Baseline' (with +/- 0.15 buffer) just for general context. Always focus on and emphasize the dominant (highest scoring) emotion(s) in your summary. "
        "For individual reports *with history*, your primary task is to detect *significant negative shifts* compared *strictly* to the *immediate previous report* (Temporal Baseline). "
        "Trigger an alarm *ONLY* if negative emotions substantially *increase* OR positive emotions substantially *decrease* relative to that *immediate* Temporal Baseline. "
        "**CRITICAL: DO NOT trigger an alarm based on deviation from the Neutral Reference Baseline, or if the mood is stable or improved compared to the *immediate* Temporal Baseline.** "
        "When describing the mood trend in non-alarm summaries, consider the *entire provided history* of reports for context. "
        "For group reports, summarize the overall team vibe conversationally, referencing the Neutral Baseline for context and highlighting dominant emotions. For all non-alarm summaries, mention the trend (using full history if available), relate the current state generally to the Neutral Reference Baseline, and emphasize the dominant emotion(s) in a natural way."
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
        print("RAW RESPONSE:", response.model_dump_json())
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
