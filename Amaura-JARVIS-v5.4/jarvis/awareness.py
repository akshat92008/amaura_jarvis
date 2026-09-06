"""
Situational Awareness Engine for JARVIS.
Tracks active windows, time context, session duration, and user idle states.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from jarvis.paths import get_data_dir

log = logging.getLogger(__name__)

SESSION_STATE_FILE = get_data_dir() / "session_state.json"


@dataclass
class SituationalContext:
    # TimeAwareness
    period: str = ""
    hour: int = 0
    greeting: str = ""
    is_late_night: bool = False
    is_work_hours: bool = False
    
    # ActiveWindowTracker
    app: str = "unknown"
    title: str = "unknown"
    mode: str = "unknown"
    
    # SessionTracker
    session_duration_min: int = 0
    interactions_count: int = 0
    last_break_min_ago: int = 0
    needs_break: bool = False
    productivity_streak: int = 0
    
    # UserIdleDetector
    idle_seconds: float = 0.0
    is_away: bool = False


class ActiveWindowTracker:
    APP_MODES = {
        "coding": ["Visual Studio Code", "Xcode", "Terminal", "iTerm", "PyCharm", "IntelliJ", "Cursor", "Code"],
        "browsing": ["Google Chrome", "Chrome", "Safari", "Firefox", "Arc", "Microsoft Edge", "Edge"],
        "communicating": ["Slack", "Discord", "Messages", "Telegram", "WhatsApp", "Mail", "Apple Mail"],
        "designing": ["Figma", "Sketch", "Canva"],
        "media": ["Spotify", "Music", "Apple Music", "YouTube", "VLC", "Netflix"],
        "writing": ["Pages", "Notes", "Apple Notes", "Notion", "Obsidian", "Microsoft Word", "Word", "TextEdit"],
        "idle": ["Finder", "loginwindow", "ScreenSaverEngine"]
    }

    def _run_applescript(self, script: str) -> str:
        if platform.system() != "Darwin":
            return "unknown"
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return "unknown"
        except Exception:
            return "unknown"

    def get_active_app(self) -> dict[str, str]:
        if platform.system() != "Darwin":
            return {"app": "unknown", "title": "unknown", "mode": "unknown"}
            
        script = '''
        try
            tell application "System Events"
                set frontApp to name of first process whose frontmost is true
                set windowTitle to ""
                if (count of (windows of (first process whose frontmost is true))) > 0 then
                    set windowTitle to name of front window of (first process whose frontmost is true)
                end if
                return frontApp & "::" & windowTitle
            end tell
        on error
            return "unknown::unknown"
        end try
        '''
        res = self._run_applescript(script)
        if res == "unknown" or "::" not in res:
            return {"app": "unknown", "title": "unknown", "mode": "unknown"}
        
        parts = res.split("::", 1)
        app_name = parts[0]
        window_title = parts[1] if len(parts) > 1 else ""
        
        mode = "unknown"
        for m, apps in self.APP_MODES.items():
            if any(app.lower() in app_name.lower() for app in apps):
                mode = m
                break
                
        return {"app": app_name, "title": window_title, "mode": mode}


class TimeAwareness:
    def get_time_context(self) -> dict[str, Any]:
        now = datetime.now()
        hour = now.hour
        is_weekend = now.weekday() >= 5
        
        if 5 <= hour < 12:
            period = "morning"
            greeting = "Good morning, sir"
        elif 12 <= hour < 17:
            period = "afternoon"
            greeting = "Good afternoon, sir"
        elif 17 <= hour < 21:
            period = "evening"
            greeting = "Good evening, sir"
        else:
            period = "night"
            greeting = "Good evening, sir"
            
        is_late_night = hour >= 23 or hour < 4
        is_work_hours = not is_weekend and (9 <= hour < 18)
        
        return {
            "period": period,
            "hour": hour,
            "greeting": greeting,
            "is_late_night": is_late_night,
            "is_work_hours": is_work_hours
        }


class SessionTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.session_start = time.time()
        self.interactions_count = 0
        self.last_break_time = time.time()
        self.productivity_streak = 0
        self.load()

    def load(self):
        try:
            if SESSION_STATE_FILE.exists():
                with open(SESSION_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                last_active = data.get("last_active", time.time())
                now = time.time()
                
                # If idle for more than 2 hours, start a new session
                if now - last_active > 7200:
                    self.session_start = now
                    self.interactions_count = 0
                    self.last_break_time = now
                    # Keep streak if less than 24h
                    if now - last_active < 86400:
                        self.productivity_streak = data.get("productivity_streak", 0)
                    else:
                        self.productivity_streak = 0
                else:
                    self.session_start = data.get("session_start", now)
                    self.interactions_count = data.get("interactions_count", 0)
                    self.last_break_time = data.get("last_break_time", now)
                    self.productivity_streak = data.get("productivity_streak", 0)
        except Exception as e:
            log.warning(f"Failed to load session state: {e}")

    def save(self):
        with self._lock:
            try:
                SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "session_start": self.session_start,
                    "interactions_count": self.interactions_count,
                    "last_break_time": self.last_break_time,
                    "productivity_streak": self.productivity_streak,
                    "last_active": time.time()
                }
                with open(SESSION_STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                log.warning(f"Failed to save session state: {e}")

    def register_interaction(self):
        with self._lock:
            self.interactions_count += 1

    def register_break(self, duration_min: int):
        with self._lock:
            if duration_min >= 15:
                self.last_break_time = time.time()

    def get_session_context(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            duration_min = int((now - self.session_start) / 60)
            last_break_min_ago = int((now - self.last_break_time) / 60)
            
            # Needs break if > 90 mins active without 15 min gap
            needs_break = duration_min > 90 and last_break_min_ago > 90
            
            return {
                "session_duration_min": duration_min,
                "interactions_count": self.interactions_count,
                "last_break_min_ago": last_break_min_ago,
                "needs_break": needs_break,
                "productivity_streak": self.productivity_streak
            }


class UserIdleDetector:
    def get_idle_seconds(self) -> float:
        if platform.system() != "Darwin":
            return 0.0
            
        try:
            p1 = subprocess.Popen(["ioreg", "-c", "IOHIDSystem"], stdout=subprocess.PIPE, text=True)
            p2 = subprocess.Popen(["grep", "HIDIdleTime"], stdin=p1.stdout, stdout=subprocess.PIPE, text=True)
            if p1.stdout:
                p1.stdout.close()
            output, _ = p2.communicate(timeout=5)
            
            if output:
                # Format is usually: "HIDIdleTime" = 123456789
                parts = output.strip().split("=")
                if len(parts) == 2:
                    nanoseconds = int(parts[1].strip())
                    return nanoseconds / 1_000_000_000.0
        except Exception as e:
            log.warning(f"Failed to get idle time: {e}")
            
        return 0.0

    def is_user_away(self, threshold_minutes: int = 5) -> bool:
        idle_secs = self.get_idle_seconds()
        return idle_secs > (threshold_minutes * 60)


class SituationalAwareness:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.window_tracker = ActiveWindowTracker()
        self.time_awareness = TimeAwareness()
        self.session_tracker = SessionTracker()
        self.idle_detector = UserIdleDetector()
        
        self._running = True
        self._bg_thread = threading.Thread(target=self._background_loop, daemon=True)
        self._bg_thread.start()

    def _background_loop(self):
        last_idle = False
        while self._running:
            try:
                # Save session every 60s
                self.session_tracker.save()
                
                # Check for breaks
                is_idle = self.idle_detector.is_user_away(threshold_minutes=15)
                if not is_idle and last_idle:
                    # User returned after 15+ mins idle
                    self.session_tracker.register_break(duration_min=15)
                    
                last_idle = is_idle
                
            except Exception as e:
                log.error(f"Error in background awareness loop: {e}")
            
            time.sleep(60)

    @classmethod
    def get_awareness(cls) -> SituationalAwareness:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
            
    def get_full_context(self) -> SituationalContext:
        tc = self.time_awareness.get_time_context()
        wc = self.window_tracker.get_active_app()
        sc = self.session_tracker.get_session_context()
        idle_secs = self.idle_detector.get_idle_seconds()
        is_away = self.idle_detector.is_user_away()
        
        return SituationalContext(
            period=tc["period"],
            hour=tc["hour"],
            greeting=tc["greeting"],
            is_late_night=tc["is_late_night"],
            is_work_hours=tc["is_work_hours"],
            app=wc["app"],
            title=wc["title"],
            mode=wc["mode"],
            session_duration_min=sc["session_duration_min"],
            interactions_count=sc["interactions_count"],
            last_break_min_ago=sc["last_break_min_ago"],
            needs_break=sc["needs_break"],
            productivity_streak=sc["productivity_streak"],
            idle_seconds=idle_secs,
            is_away=is_away
        )

    def get_prompt_addon(self) -> str:
        ctx = self.get_full_context()
        now_str = datetime.now().strftime("%A, %I:%M %p")
        
        app_str = f"{ctx.app} ({ctx.title})" if ctx.title and ctx.title != "unknown" else ctx.app
        mode_str = ctx.mode.capitalize() if ctx.mode != "unknown" else "Active"
        
        status = "User is present and focused"
        if ctx.is_away:
            status = f"User is away (idle for {int(ctx.idle_seconds / 60)} minutes)"
        elif ctx.needs_break:
            status = "User is present, but needs a break"
            
        parts = [
            "[SITUATIONAL AWARENESS]",
            f"  Time: {ctx.greeting} ({now_str})",
            f"  User Activity: {mode_str} in {app_str}",
            f"  Session: {ctx.session_duration_min} minutes active, {ctx.interactions_count} interactions",
            f"  Status: {status}"
        ]
        return "\n".join(parts)


def get_awareness() -> SituationalAwareness:
    """Module-level singleton accessor for SituationalAwareness."""
    return SituationalAwareness.get_awareness()


def tool_get_situational_context() -> str:
    """Get the current situational awareness context as JSON string."""
    aw = SituationalAwareness.get_awareness()
    ctx = aw.get_full_context()
    return json.dumps(asdict(ctx), indent=2)

def tool_check_user_presence() -> str:
    """Check if the user is present and focused."""
    aw = SituationalAwareness.get_awareness()
    ctx = aw.get_full_context()
    if ctx.is_away:
        return f"User is currently away (idle for {int(ctx.idle_seconds / 60)} minutes)."
    return "User is present and active."


AWARENESS_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_situational_context",
            "description": "Get complete situational context including time, active window, session stats, and user idle state.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_user_presence",
            "description": "Check if the user is actively present at their computer or away/idle.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]

AWARENESS_DISPATCH = {
    "get_situational_context": tool_get_situational_context,
    "check_user_presence": tool_check_user_presence,
}
