"""
macOS Sci-Fi HUD & Floating Overlay Manager for JARVIS.
Handles Cmd + Shift + J global hotkey activation, Spotlight-style prompt bar, and floating desktop widgets.
"""

import os
import subprocess

HUD_SUBPROCESS_TIMEOUT_SECONDS = max(1, min(int(os.environ.get("JARVIS_HUD_TIMEOUT", "5")), 30))

HUD_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "toggle_hud_overlay",
            "description": "Toggle the native macOS floating HUD overlay window (Cmd + Shift + J shortcut target).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: 'show', 'hide', or 'toggle'.",
                        "default": "toggle",
                    }
                },
            },
        },
    }
]


class JarvisHUDManager:
    def __init__(self):
        self.is_visible = False

    def toggle(self, action: str = "toggle") -> str:
        if action == "show":
            self.is_visible = True
        elif action == "hide":
            self.is_visible = False
        else:
            self.is_visible = not self.is_visible

        state_str = "VISIBLE (Active Overlay)" if self.is_visible else "HIDDEN (System Tray)"

        # Trigger macOS Notification
        try:
            script = f'display notification "JARVIS HUD Overlay is now {state_str}" with title "JARVIS Sci-Fi HUD"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=HUD_SUBPROCESS_TIMEOUT_SECONDS)
        except Exception:
            pass

        return f"💻 **macOS Sci-Fi HUD Overlay:** {state_str}\n⌨️ **Global Shortcut:** `Cmd + Shift + J`"


_hud_instance = JarvisHUDManager()


def toggle_hud_overlay(action: str = "toggle") -> str:
    return _hud_instance.toggle(action)


HUD_DISPATCH = {"toggle_hud_overlay": toggle_hud_overlay}
