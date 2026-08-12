"""Governed macOS communication and personal-productivity tools."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta

from jarvis.amaura.n8n import get_n8n_client

COMMUNICATION_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "send_imessage",
            "description": "Send a founder-approved iMessage to a phone number or email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient phone number or email."},
                    "message": {"type": "string", "description": "Message text to send."},
                },
                "required": ["to", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": "Add a reminder to Apple Reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Reminder title."},
                    "notes": {"type": "string", "description": "Additional notes."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reminders",
            "description": "Get current incomplete reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_calendar_event",
            "description": "Add a correctly timed Apple Calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title."},
                    "date": {"type": "string", "description": "ISO date/time, today at 3pm, or tomorrow at 15:00."},
                    "duration_hours": {"type": "number", "description": "Duration in hours."},
                    "notes": {"type": "string", "description": "Event notes."},
                },
                "required": ["title", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "automate_macos_app",
            "description": "Automate any macOS application by running dynamically generated AppleScript (e.g. Mail, Spotify, Music, System Settings). Use carefully.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "The raw AppleScript string to execute."},
                },
                "required": ["script"],
            },
        },
    },
]


def _run_applescript(script: str, *arguments: str) -> str:
    """Run static AppleScript source and bind user data through argv."""
    for app in ("Reminders", "Calendar", "Messages"):
        if f'tell application "{app}"' in script:
            try:
                subprocess.run(["open", "-a", app], timeout=3, capture_output=True, check=False)
            except Exception:
                pass
    try:
        result = subprocess.run(
            ["osascript", "-e", script, *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return f"❌ Error: {exc}"
    if result.returncode != 0:
        return f"❌ AppleScript error: {result.stderr.strip()}"
    return result.stdout.strip()


def send_imessage_local(to: str, message: str) -> str:
    recipient = to.strip()
    body = message.strip()
    if not recipient or len(recipient.encode()) > 320:
        return "❌ Invalid iMessage recipient"
    if not body or len(body.encode("utf-8")) > 20_000:
        return "❌ Invalid iMessage body"
    script = r'''
    on run argv
        set targetRecipient to item 1 of argv
        set targetMessage to item 2 of argv
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant targetRecipient of targetService
            send targetMessage to targetBuddy
        end tell
    end run
    '''
    result = _run_applescript(script, recipient, body)
    if result.startswith("❌"):
        return result
    return f"✅ iMessage sent to {recipient}"


def tool_send_imessage(to: str, message: str) -> str:
    """Break-glass direct tool; normal company delivery uses the durable outbox."""
    provider = os.environ.get("AMAURA_IMESSAGE_PROVIDER", "local").strip().lower()
    if provider == "n8n":
        client = get_n8n_client()
        result = client.send_message(to, message, idempotency_key="break-glass")
        return f"✅ iMessage sent to {to} via n8n" if result.get("status") == "success" else "❌ n8n delivery failed"
    if provider != "local":
        return "❌ AMAURA_IMESSAGE_PROVIDER must be local or n8n"
    return send_imessage_local(to, message)


def tool_add_reminder(title: str, notes: str = "") -> str:
    reminder_title = title.strip()
    reminder_notes = notes.strip()
    if not reminder_title or len(reminder_title.encode()) > 1_000:
        return "❌ Invalid reminder title"
    if len(reminder_notes.encode()) > 10_000:
        return "❌ Invalid reminder notes"
    script = r'''
    on run argv
        set reminderTitle to item 1 of argv
        set reminderNotes to item 2 of argv
        tell application "Reminders"
            launch
            set targetList to default list
            make new reminder at targetList with properties {name:reminderTitle, body:reminderNotes}
        end tell
    end run
    '''
    result = _run_applescript(script, reminder_title, reminder_notes)
    if result.startswith("❌"):
        fallback = r'''
        on run argv
            set reminderTitle to item 1 of argv
            set reminderNotes to item 2 of argv
            tell application "Reminders"
                launch
                set targetList to first list
                make new reminder at targetList with properties {name:reminderTitle, body:reminderNotes}
            end tell
        end run
        '''
        result = _run_applescript(fallback, reminder_title, reminder_notes)
    return result if result.startswith("❌") else f"✅ Reminder added: {reminder_title}"


def tool_get_reminders() -> str:
    script = '''
    tell application "Reminders"
        launch
        set reminderList to {}
        repeat with r in (reminders of default list whose completed is false)
            set end of reminderList to name of r
        end repeat
        return reminderList
    end tell
    '''
    result = _run_applescript(script)
    if result.startswith("❌"):
        fallback = '''
        tell application "Reminders"
            launch
            set reminderList to {}
            repeat with r in (reminders of first list whose completed is false)
                set end of reminderList to name of r
            end repeat
            return reminderList
        end tell
        '''
        result = _run_applescript(fallback)
    if result.startswith("❌"):
        return result
    if not result:
        return "No pending reminders."
    items = [item.strip() for item in result.split(",")]
    return f"Pending reminders ({len(items)}):\n" + "\n".join(f"  • {item}" for item in items)


def _parse_clock(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value.strip().lower())
    if not match:
        raise ValueError("time must look like 15:30 or 3:30pm")
    hour, minute = int(match.group(1)), int(match.group(2) or "0")
    meridiem = match.group(3)
    if minute > 59:
        raise ValueError("minute must be between 00 and 59")
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError("12-hour time must use 1 through 12")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif hour > 23:
        raise ValueError("hour must be between 0 and 23")
    return hour, minute


def _parse_calendar_datetime(value: str, *, now: datetime | None = None) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("calendar date is required")
    reference = (now or datetime.now()).replace(second=0, microsecond=0)
    relative = re.fullmatch(r"(today|tomorrow)(?:\s+at)?(?:\s+(.+))?", raw, flags=re.IGNORECASE)
    if relative:
        target = reference + timedelta(days=1 if relative.group(1).lower() == "tomorrow" else 0)
        hour, minute = _parse_clock(relative.group(2) or "09:00")
        return target.replace(hour=hour, minute=minute)
    date_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("use YYYY-MM-DD, YYYY-MM-DD HH:MM, today at 3pm, or tomorrow at 15:00") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    if date_only:
        parsed = parsed.replace(hour=9, minute=0)
    return parsed.replace(second=0, microsecond=0)


def tool_add_calendar_event(title: str, date: str, duration_hours: float = 1, notes: str = "") -> str:
    event_title, event_notes = title.strip(), notes.strip()
    if not event_title or len(event_title.encode()) > 1_000:
        return "❌ Invalid calendar event title"
    if len(event_notes.encode()) > 20_000:
        return "❌ Invalid calendar event notes"
    try:
        duration = float(duration_hours)
    except (TypeError, ValueError):
        return "❌ Calendar duration must be a number"
    if not 0 < duration <= 168:
        return "❌ Calendar duration must be greater than 0 and at most 168 hours"
    try:
        start = _parse_calendar_datetime(date)
    except ValueError as exc:
        return f"❌ Invalid calendar date: {exc}"
    script = r'''
    on run argv
        set eventTitle to item 1 of argv
        set eventNotes to item 2 of argv
        set eventYear to (item 3 of argv) as integer
        set eventMonth to (item 4 of argv) as integer
        set eventDay to (item 5 of argv) as integer
        set eventHour to (item 6 of argv) as integer
        set eventMinute to (item 7 of argv) as integer
        set eventDuration to (item 8 of argv) as integer
        set startDate to current date
        set year of startDate to eventYear
        set month of startDate to eventMonth
        set day of startDate to eventDay
        set time of startDate to 0
        set hours of startDate to eventHour
        set minutes of startDate to eventMinute
        set seconds of startDate to 0
        set endDate to startDate + eventDuration
        tell application "Calendar"
            tell calendar "Calendar"
                make new event with properties {summary:eventTitle, description:eventNotes, start date:startDate, end date:endDate}
            end tell
        end tell
    end run
    '''
    result = _run_applescript(
        script, event_title, event_notes, str(start.year), str(start.month), str(start.day),
        str(start.hour), str(start.minute), str(int(round(duration * 3600))),
    )
    return result if result.startswith("❌") else f"✅ Calendar event added: {event_title} on {start.isoformat(timespec='minutes')}"


def tool_automate_macos_app(script: str) -> str:
    """Run an arbitrary AppleScript string to control macOS apps."""
    if not script or not script.strip():
        return "❌ Empty AppleScript provided"
    return _run_applescript(script)


COMMUNICATION_DISPATCH = {
    "send_imessage": lambda **kw: tool_send_imessage(kw.get("to", ""), kw.get("message", "")),
    "add_reminder": lambda **kw: tool_add_reminder(kw.get("title", ""), kw.get("notes", "")),
    "get_reminders": lambda **kw: tool_get_reminders(),
    "add_calendar_event": lambda **kw: tool_add_calendar_event(
        kw.get("title", ""), kw.get("date", ""), kw.get("duration_hours", 1), kw.get("notes", "")
    ),
    "automate_macos_app": lambda **kw: tool_automate_macos_app(kw.get("script", "")),
}
