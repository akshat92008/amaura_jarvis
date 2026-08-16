from jarvis.agent import JarvisAgent
from jarvis.amaura.runtime import load_amaura_env

load_amaura_env(require_private_permissions=True)


def main():
    agent = JarvisAgent()
    print("Sending request to JARVIS...")

    # We must ensure legacy tools are enabled for this test because
    # automate_macos_app was added to GOVERNED_ONLY_TOOLS, and the test CLI
    # might not have the right mode by default.
    import os

    os.environ["JARVIS_ENABLE_LEGACY_DIRECT_TOOLS"] = "1"

    response = agent.run_non_interactive(
        "Use your automate_macos_app tool to write an AppleScript that returns the version of Mail. You must actually use the tool."
    )
    print("\nJARVIS Response:")
    print(response)


if __name__ == "__main__":
    main()
