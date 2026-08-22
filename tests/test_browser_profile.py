import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc import cli
from reddit_voc.browser_profile import build_chrome_launch_command, init_browser_profile, inspect_browser_profile


def run_cli(argv):
    stream = StringIO()
    with redirect_stdout(stream):
        rc = cli.main(argv)
    return rc, json.loads(stream.getvalue())


class BrowserProfileTests(unittest.TestCase):
    def test_init_profile_outside_workspace_is_ready_for_manual_login(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            profile = Path(tmp) / "chrome-profile"

            result = init_browser_profile(profile, workspace_root=workspace)

            self.assertEqual(result["status"], "ready_for_manual_login")
            self.assertTrue(profile.exists())
            self.assertFalse(result["inside_workspace"])
            self.assertFalse(result["provider_call"])
            self.assertFalse(result["live_send"])
            self.assertFalse(result["reddit_write"])

    def test_profile_inside_workspace_is_blocked(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            profile = workspace / "chrome-profile"
            workspace.mkdir()

            result = init_browser_profile(profile, workspace_root=workspace)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "profile_inside_workspace")
            self.assertTrue(result["inside_workspace"])
            self.assertFalse(profile.exists())

    def test_status_uses_cookie_store_existence_without_reading_content(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            profile = Path(tmp) / "chrome-profile"
            cookies = profile / "Default" / "Network" / "Cookies"
            workspace.mkdir()
            cookies.parent.mkdir(parents=True)
            cookies.write_text("opaque", encoding="utf-8")

            status = inspect_browser_profile(profile, workspace_root=workspace)

            self.assertTrue(status.has_cookie_store)
            self.assertEqual(status.login_state, "profile_present_login_unverified")

    def test_launch_command_uses_dedicated_user_data_dir(self):
        command = build_chrome_launch_command("/tmp/reddit-voc-profile", start_url="https://www.reddit.com/login/")

        self.assertEqual(command[:4], ["open", "-na", "Google Chrome", "--args"])
        self.assertIn(f"--user-data-dir={Path('/tmp/reddit-voc-profile').resolve()}", command)
        self.assertIn("https://www.reddit.com/login/", command)

    def test_launch_command_can_enable_remote_debugging(self):
        command = build_chrome_launch_command(
            "/tmp/reddit-voc-profile",
            start_url="https://www.reddit.com/login/",
            remote_debug_port=9333,
        )

        self.assertIn("--remote-debugging-port=9333", command)
        self.assertLess(command.index("--remote-debugging-port=9333"), command.index("https://www.reddit.com/login/"))

    def test_cli_profile_launch_command_is_secret_safe(self):
        with TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"

            rc, result = run_cli(
                [
                    "browser-profile-launch-command",
                    "--profile-dir",
                    str(profile),
                    "--start-url",
                    "https://www.reddit.com/login/",
                    "--remote-debug-port",
                    "9333",
                ]
            )

            serialized = json.dumps(result)
            self.assertEqual(rc, 0)
            self.assertEqual(result["status"], "ready")
            self.assertIn("--user-data-dir=", serialized)
            self.assertEqual(result["browser_cdp_url"], "http://127.0.0.1:9333")
            self.assertNotIn("token", serialized.lower())
            self.assertNotIn("password", serialized.lower())


if __name__ == "__main__":
    unittest.main()
