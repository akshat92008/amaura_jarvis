import unittest
from types import SimpleNamespace
from unittest.mock import patch
from jarvis.tools.browser import (
    browser_navigate,
    browser_extract_content,
    browser_manage_tabs,
    browser_manage_session,
    browser_upload_file
)

class TestBrowser(unittest.TestCase):
    def test_navigate_and_extract(self):
        response = SimpleNamespace(
            text="<html><title>Example Domain</title><body><h1>Example Domain</h1></body></html>",
            status_code=200,
        )
        with patch("jarvis.tools.browser.httpx.get", return_value=response):
            res = browser_navigate("https://example.com", use_playwright=False)
            self.assertIn("Example Domain", res)
            extracted = browser_extract_content("https://example.com", selector="h1")
            self.assertIn("Example Domain", extracted)

    def test_tabs_management(self):
        tab_res = browser_manage_tabs("list")
        self.assertIn("Active Browser Tabs", tab_res)

        created = browser_manage_tabs("create", url="https://python.org")
        self.assertIn("Created Tab", created)

        closed = browser_manage_tabs("close", tab_index=0)
        self.assertIn("Closed Tab", closed)

    def test_session_management(self):
        session_info = browser_manage_session("info")
        self.assertIn("Browser Session & Auth Status", session_info)

        clear_res = browser_manage_session("clear")
        self.assertIn("Cleared", clear_res)

    def test_upload_missing_file_error(self):
        err = browser_upload_file("https://example.com", "input[type=file]", "/non/existent/path.txt")
        self.assertIn("does not exist", err)

if __name__ == "__main__":
    unittest.main()
