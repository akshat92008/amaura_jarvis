import subprocess

from jarvis.tools.communication import tool_automate_macos_app

apps_to_test = [
    ("Mail", 'tell application "Mail" to return version'),
    ("Calendar", 'tell application "Calendar" to return version'),
    ("Notes", 'tell application "Notes" to return version'),
    ("Safari", 'tell application "Safari" to return version'),
]

print("=== Testing macOS App Integrations ===")
for app, script in apps_to_test:
    print(f"\nTesting {app}...")
    result = tool_automate_macos_app(script)
    print(f"Result: {result}")

# List all apps
print("\n=== Available Applications in /Applications ===")
apps = subprocess.run(["ls", "-1", "/Applications"], capture_output=True, text=True).stdout.strip().split("\n")
print(f"Found {len(apps)} apps. Sample:")
for app in apps[:10]:
    if app.endswith(".app"):
        print(f"  - {app}")
