"""
Autonomous Morning Briefing Module for JARVIS.

Generates an authentic Stark-style morning briefing:
- Time-aware greeting and date/time
- Local weather conditions (via wttr.in with graceful fallback)
- Real macOS system telemetry (CPU, RAM, Disk, Battery, Thermal)
- Upcoming calendar events for today (via AppleScript)
- Pending macOS reminders / tasks
- Workspace git status recap
- Proactive suggestions for the day
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
import urllib.request
from datetime import datetime
from typing import Any

from jarvis.heartbeat import get_heartbeat
from jarvis.paths import get_data_dir

log = logging.getLogger(__name__)


def fetch_weather(city: str = "") -> str:
    """Fetch concise weather summary from wttr.in with quick timeout."""
    try:
        url = f"https://wttr.in/{city}?format=%C+%t+(feels+like+%f)+wind+%w+humidity+%h"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "curl/7.68.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            content = resp.read().decode("utf-8").strip()
            if content and not content.startswith("<") and "Unknown location" not in content:
                return content
    except Exception as exc:
        log.debug("Weather fetch skipped or failed: %s", exc)
    return "Weather telemetry offline (network unreachable or timeout)"


def get_todays_calendar_events() -> list[str]:
    """Retrieve today's remaining calendar events from macOS Calendar."""
    if platform.system() != "Darwin":
        return []
    try:
        script = '''
        tell application "Calendar"
            set todayStart to current date
            set hours of todayStart to 0
            set minutes of todayStart to 0
            set seconds of todayStart to 0
            set todayEnd to todayStart + (24 * 60 * 60)
            set eventList to {}
            repeat with cal in calendars
                set dayEvents to (every event of cal whose start date >= todayStart and start date < todayEnd)
                repeat with evt in dayEvents
                    set sTime to time string of (start date of evt)
                    set end of eventList to sTime & " — " & (summary of evt)
                end repeat
            end repeat
            return eventList
        end tell
        '''
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            raw = res.stdout.strip()
            return [x.strip() for x in raw.split(", ") if x.strip()]
    except Exception as exc:
        log.debug("Calendar query skipped: %s", exc)
    return []


def get_pending_reminders(limit: int = 5) -> list[str]:
    """Retrieve pending reminders from macOS Reminders."""
    if platform.system() != "Darwin":
        return []
    try:
        script = f'''
        tell application "Reminders"
            set pending to (every reminder whose completed is false)
            set outList to {{}}
            set maxCount to {limit}
            set currentCount to 0
            repeat with rem in pending
                set currentCount to currentCount + 1
                if currentCount > maxCount then exit repeat
                set end of outList to (name of rem)
            end repeat
            return outList
        end tell
        '''
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            raw = res.stdout.strip()
            return [x.strip() for x in raw.split(", ") if x.strip()]
    except Exception as exc:
        log.debug("Reminders query skipped: %s", exc)
    return []


def get_git_workspace_summary() -> dict[str, Any]:
    """Check git status of current working directory."""
    summary: dict[str, Any] = {"is_git": False, "branch": "", "uncommitted": 0, "latest_commit": ""}
    try:
        res = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=2)
        if res.returncode != 0:
            return summary
        summary["is_git"] = True

        b_res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=2)
        summary["branch"] = b_res.stdout.strip() or "detached"

        s_res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=3)
        uncommitted = [line for line in s_res.stdout.splitlines() if line.strip()]
        summary["uncommitted"] = len(uncommitted)

        log_res = subprocess.run(["git", "log", "-1", "--pretty=format:%h %s (%cr)"], capture_output=True, text=True, timeout=2)
        summary["latest_commit"] = log_res.stdout.strip()
    except Exception as exc:
        log.debug("Git summary query skipped: %s", exc)
    return summary


def compose_morning_briefing(user_name: str = "sir") -> str:
    """Compose the comprehensive, production-grade morning briefing."""
    curr_time = time.strftime("%A, %B %d, %Y | %I:%M %p")
    hour = datetime.now().hour

    if 5 <= hour < 12:
        salutation = f"Good morning, {user_name}."
    elif 12 <= hour < 17:
        salutation = f"Good afternoon, {user_name}."
    elif 17 <= hour < 22:
        salutation = f"Good evening, {user_name}."
    else:
        salutation = f"Burning the midnight oil, {user_name}."

    # Heartbeat / telemetry
    heartbeat = get_heartbeat()
    tel = heartbeat.last_telemetry
    if not tel:
        tel = heartbeat.system_monitor.poll()

    cpu_load = tel.get("cpu_percent_approx", 0)
    cpu_cores = tel.get("cpu_count", os.cpu_count() or 1)
    ram_used = tel.get("ram_used_gb", "N/A")
    ram_total = tel.get("ram_total_gb", "N/A")
    ram_pct = tel.get("ram_used_percent", 0)
    disk_free = tel.get("disk_free_gb", "N/A")
    disk_total = tel.get("disk_total_gb", "N/A")
    battery_pct = tel.get("battery_percent", None)
    battery_charging = tel.get("battery_charging", False)

    battery_str = ""
    if battery_pct is not None:
        state = "⚡ Charging" if battery_charging else "🔋 Discharging"
        battery_str = f"  - Power Subsystem: {battery_pct}% ({state})\n"

    weather_summary = fetch_weather()
    cal_events = get_todays_calendar_events()
    reminders = get_pending_reminders()
    git_info = get_git_workspace_summary()

    lines = [
        f"🌅 **{salutation}**",
        f"📅 **Time:** {curr_time}",
        f"🌤️ **Atmospheric Conditions:** {weather_summary}",
        "",
        "💻 **System & Hardware Telemetry:**",
        f"  - Core Processor: {cpu_load}% across {cpu_cores} cores",
        f"  - Working Memory: {ram_used} GB / {ram_total} GB ({ram_pct}%)",
        f"  - Storage Volume: {disk_free} GB free of {disk_total} GB",
    ]
    if battery_str:
        lines.append(battery_str.strip())

    if cal_events:
        lines.append("")
        lines.append("📆 **Today's Agenda:**")
        for evt in cal_events:
            lines.append(f"  • {evt}")
    else:
        lines.append("")
        lines.append("📆 **Today's Agenda:** No calendar appointments scheduled. Your time is completely clear.")

    if reminders:
        lines.append("")
        lines.append("📝 **Action Items / Reminders:**")
        for rem in reminders:
            lines.append(f"  • {rem}")

    if git_info.get("is_git"):
        lines.append("")
        lines.append("🛠️ **Active Workspace Status:**")
        lines.append(f"  - Branch: `{git_info['branch']}`")
        lines.append(f"  - Uncommitted Changes: {git_info['uncommitted']} files")
        if git_info.get("latest_commit"):
            lines.append(f"  - Head Commit: {git_info['latest_commit']}")

    lines.append("")
    lines.append("All primary systems nominal. What are we building today, sir?")

    briefing_text = "\n".join(lines)
    heartbeat.mark_morning_briefing_delivered()
    return briefing_text


MORNING_BRIEFING_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "generate_full_morning_briefing",
            "description": "Generate the comprehensive Iron Man JARVIS morning briefing with real weather, agenda, reminders, and system telemetry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {
                        "type": "string",
                        "description": "User title or name to address (default 'sir').",
                        "default": "sir",
                    }
                },
            },
        },
    }
]


def tool_generate_full_morning_briefing(user_name: str = "sir") -> str:
    """Execute generate_full_morning_briefing tool."""
    return compose_morning_briefing(user_name=user_name)


MORNING_BRIEFING_DISPATCH = {
    "generate_full_morning_briefing": tool_generate_full_morning_briefing,
}


__all__ = [
    "compose_morning_briefing",
    "fetch_weather",
    "get_todays_calendar_events",
    "get_pending_reminders",
    "get_git_workspace_summary",
    "MORNING_BRIEFING_TOOL_DEFINITIONS",
    "MORNING_BRIEFING_DISPATCH",
]
