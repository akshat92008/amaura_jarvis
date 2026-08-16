import unittest

from jarvis.fleet import (
    DaemonManager,
    check_system_watchdog,
    generate_morning_briefing,
    manage_daemon,
    run_nightly_auditor,
)


class TestFleet(unittest.TestCase):
    def test_briefing_and_watchdog(self):
        briefing = generate_morning_briefing()
        self.assertIn("Good morning, sir", briefing)

        watchdog = check_system_watchdog()
        self.assertIn("System Watchdog", watchdog)

        audit = run_nightly_auditor(".")
        self.assertIn("JARVIS Nightly Code Auditor Report", audit)

    def test_daemon_manager(self):
        mgr = DaemonManager()
        plist = mgr.generate_plist_content()
        self.assertIn("com.jarvis.daemon", plist)
        self.assertIn("RunAtLoad", plist)
        self.assertIn("KeepAlive", plist)

        status = manage_daemon("status")
        self.assertIn("Background Daemon Fleet Status", status)

        run_res = manage_daemon("run_once")
        self.assertIn("Daemon execution tick completed", run_res)


if __name__ == "__main__":
    unittest.main()
