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
    {
        "type": "function",
        "function": {
            "name": "publish_instagram_post",
            "description": "Publish an image or reel to Instagram via Meta Graph API (or assisted browser).",
            "parameters": {
                "type": "object",
                "properties": {
                    "media_url": {"type": "string", "description": "Public HTTPS URL of the image or video reel to post."},
                    "caption": {"type": "string", "description": "Caption text and hashtags for the Instagram post."},
                    "media_type": {"type": "string", "enum": ["IMAGE", "REELS"], "default": "IMAGE"},
                },
                "required": ["media_url", "caption"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_linkedin_post",
            "description": "Publish a text post or article update to LinkedIn via official API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Content of the post to publish on LinkedIn."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_facebook_post",
            "description": "Publish a post to Facebook Page feed via Meta Graph API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Post text to publish to Facebook Page."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_telegram_notification",
            "description": "Send a real-time message or notification to the founder's Telegram account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Message to send via Telegram."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_social_outreach",
            "description": "Prepare an assisted outreach message for Instagram, WhatsApp, LinkedIn, Facebook, or Email with a one-click browser launcher.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": ["instagram", "whatsapp", "linkedin", "facebook", "email"]},
                    "recipient": {"type": "string", "description": "Recipient profile URL, phone number, or email."},
                    "body": {"type": "string", "description": "Message body to send."},
                    "subject": {"type": "string", "description": "Optional subject.", "default": ""},
                    "open_browser": {"type": "boolean", "description": "Whether to auto-open the chat in browser.", "default": True},
                },
                "required": ["channel", "recipient", "body"],
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
    script = r"""
    on run argv
        set targetRecipient to item 1 of argv
        set targetMessage to item 2 of argv
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant targetRecipient of targetService
            send targetMessage to targetBuddy
        end tell
    end run
    """
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
    script = r"""
    on run argv
        set reminderTitle to item 1 of argv
        set reminderNotes to item 2 of argv
        tell application "Reminders"
            launch
            set targetList to default list
            make new reminder at targetList with properties {name:reminderTitle, body:reminderNotes}
        end tell
    end run
    """
    result = _run_applescript(script, reminder_title, reminder_notes)
    if result.startswith("❌"):
        fallback = r"""
        on run argv
            set reminderTitle to item 1 of argv
            set reminderNotes to item 2 of argv
            tell application "Reminders"
                launch
                set targetList to first list
                make new reminder at targetList with properties {name:reminderTitle, body:reminderNotes}
            end tell
        end run
        """
        result = _run_applescript(fallback, reminder_title, reminder_notes)
    return result if result.startswith("❌") else f"✅ Reminder added: {reminder_title}"


def tool_get_reminders() -> str:
    script = """
    tell application "Reminders"
        launch
        set reminderList to {}
        repeat with r in (reminders of default list whose completed is false)
            set end of reminderList to name of r
        end repeat
        return reminderList
    end tell
    """
    result = _run_applescript(script)
    if result.startswith("❌"):
        fallback = """
        tell application "Reminders"
            launch
            set reminderList to {}
            repeat with r in (reminders of first list whose completed is false)
                set end of reminderList to name of r
            end repeat
            return reminderList
        end tell
        """
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
    script = r"""
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
    """
    result = _run_applescript(
        script,
        event_title,
        event_notes,
        str(start.year),
        str(start.month),
        str(start.day),
        str(start.hour),
        str(start.minute),
        str(int(round(duration * 3600))),
    )
    return (
        result
        if result.startswith("❌")
        else f"✅ Calendar event added: {event_title} on {start.isoformat(timespec='minutes')}"
    )


def tool_automate_macos_app(script: str) -> str:
    """Run an arbitrary AppleScript string to control macOS apps."""
    if not script or not script.strip():
        return "❌ Empty AppleScript provided"
    return _run_applescript(script)


def tool_publish_instagram_post(media_url: str, caption: str, media_type: str = "IMAGE") -> str:
    """Publish an image or reel to Instagram via Meta Graph API or assisted browser."""
    from jarvis.amaura.channels import MetaPublicationAdapter
    adapter = MetaPublicationAdapter()
    if not adapter.instagram_configured:
        return (
            "⚠️ Instagram API is not yet configured.\n"
            "To enable direct automated Instagram publishing, add these to .env.amaura:\n"
            "  AMAURA_META_ACCESS_TOKEN=<your-meta-access-token>\n"
            "  AMAURA_INSTAGRAM_ACCOUNT_ID=<your-instagram-account-id>\n"
            "  AMAURA_META_GRAPH_VERSION=23.0\n\n"
            "Alternatively, use Playwright browser automation (`browser_navigate`) to manage Instagram directly!"
        )
    import secrets
    idempotency_key = f"ig-{secrets.token_hex(8)}"
    try:
        receipt = adapter.publish_instagram_media(
            media_url=media_url,
            caption=caption,
            idempotency_key=idempotency_key,
            media_type=media_type,
        )
        return f"✅ Instagram post published successfully!\n   Post ID: {receipt.external_id}\n   Status: {receipt.status}"
    except Exception as exc:
        return f"❌ Instagram publication failed: {exc}"


def tool_publish_linkedin_post(text: str) -> str:
    """Publish a post to LinkedIn via official API."""
    from jarvis.amaura.channels import LinkedInPublicationAdapter
    adapter = LinkedInPublicationAdapter()
    if not adapter.configured:
        return (
            "⚠️ LinkedIn API is not yet configured.\n"
            "To enable direct automated LinkedIn publishing, add these to .env.amaura:\n"
            "  AMAURA_LINKEDIN_ACCESS_TOKEN=<your-linkedin-access-token>\n"
            "  AMAURA_LINKEDIN_AUTHOR_URN=urn:li:person:<your-urn-or-org>\n"
            "  AMAURA_LINKEDIN_VERSION=202401"
        )
    import secrets
    idempotency_key = f"li-{secrets.token_hex(8)}"
    try:
        receipt = adapter.publish_text(text=text, idempotency_key=idempotency_key)
        return f"✅ LinkedIn post published successfully!\n   Post ID: {receipt.external_id}\n   Status: {receipt.status}"
    except Exception as exc:
        return f"❌ LinkedIn publication failed: {exc}"


def tool_publish_facebook_post(text: str) -> str:
    """Publish a post to Facebook Page feed via Meta Graph API."""
    from jarvis.amaura.channels import MetaPublicationAdapter
    adapter = MetaPublicationAdapter()
    if not adapter.facebook_configured:
        return (
            "⚠️ Facebook Page API is not yet configured.\n"
            "To enable direct Facebook Page publishing, add these to .env.amaura:\n"
            "  AMAURA_META_ACCESS_TOKEN=<your-meta-access-token>\n"
            "  AMAURA_FACEBOOK_PAGE_ID=<your-page-id>\n"
            "  AMAURA_META_GRAPH_VERSION=23.0"
        )
    import secrets
    idempotency_key = f"fb-{secrets.token_hex(8)}"
    try:
        receipt = adapter.publish_facebook_text(text=text, idempotency_key=idempotency_key)
        return f"✅ Facebook post published successfully!\n   Post ID: {receipt.external_id}\n   Status: {receipt.status}"
    except Exception as exc:
        return f"❌ Facebook publication failed: {exc}"


def tool_send_telegram_notification(text: str) -> str:
    """Send a real-time message or notification to the founder's Telegram account."""
    from jarvis.amaura.channels import TelegramNotificationAdapter
    adapter = TelegramNotificationAdapter()
    if not adapter.configured:
        return (
            "⚠️ Telegram Bot is not yet configured.\n"
            "To enable Telegram alerts, add these to .env.amaura:\n"
            "  TELEGRAM_BOT_TOKEN=<your-bot-token-from-@BotFather>\n"
            "  TELEGRAM_USER_ID=<your-telegram-numeric-user-id>"
        )
    import secrets
    idempotency_key = f"tg-{secrets.token_hex(8)}"
    try:
        receipt = adapter.send(text=text, idempotency_key=idempotency_key)
        return f"✅ Telegram notification sent!\n   Message ID: {receipt.external_id}"
    except Exception as exc:
        return f"❌ Telegram notification failed: {exc}"


def tool_prepare_social_outreach(
    channel: str, recipient: str, body: str, subject: str = "", open_browser: bool = True
) -> str:
    """Prepare an assisted outreach message for Instagram, WhatsApp, LinkedIn, Facebook, or Email with a one-click browser launcher."""
    from jarvis.amaura.channels import AssistedOutreachAdapter
    adapter = AssistedOutreachAdapter()
    import secrets
    idempotency_key = f"outreach-{secrets.token_hex(8)}"
    try:
        receipt = adapter.prepare(
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
            open_browser=open_browser,
        )
        return (
            f"✅ Assisted outreach packet prepared for {channel.title()}!\n"
            f"   Recipient: {recipient}\n"
            f"   Packet ID: {receipt.external_id}\n"
            f"   Browser Launch: {'Opened in default browser' if open_browser else 'URL prepared'}"
        )
    except Exception as exc:
        return f"❌ Failed to prepare assisted outreach: {exc}"


COMMUNICATION_DISPATCH = {
    "send_imessage": lambda **kw: tool_send_imessage(kw.get("to", ""), kw.get("message", "")),
    "add_reminder": lambda **kw: tool_add_reminder(kw.get("title", ""), kw.get("notes", "")),
    "get_reminders": lambda **kw: tool_get_reminders(),
    "add_calendar_event": lambda **kw: tool_add_calendar_event(
        kw.get("title", ""), kw.get("date", ""), kw.get("duration_hours", 1), kw.get("notes", "")
    ),
    "automate_macos_app": lambda **kw: tool_automate_macos_app(kw.get("script", "")),
    "publish_instagram_post": lambda **kw: tool_publish_instagram_post(
        kw.get("media_url", ""), kw.get("caption", ""), kw.get("media_type", "IMAGE")
    ),
    "publish_linkedin_post": lambda **kw: tool_publish_linkedin_post(kw.get("text", "")),
    "publish_facebook_post": lambda **kw: tool_publish_facebook_post(kw.get("text", "")),
    "send_telegram_notification": lambda **kw: tool_send_telegram_notification(kw.get("text", "")),
    "prepare_social_outreach": lambda **kw: tool_prepare_social_outreach(
        kw.get("channel", "instagram"),
        kw.get("recipient", ""),
        kw.get("body", ""),
        kw.get("subject", ""),
        kw.get("open_browser", True),
    ),
}

