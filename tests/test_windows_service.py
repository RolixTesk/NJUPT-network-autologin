import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from njupt_autologin.platform_services.windows import WindowsServiceAdapter


class WindowsServiceTests(unittest.TestCase):
    def test_pause_marker_blocks_only_the_current_boot(self):
        adapter = WindowsServiceAdapter()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pause"
            with (
                patch("njupt_autologin.platform_services.windows._pause_path", return_value=marker),
                patch.object(adapter, "_task_enabled", return_value=(True, True)),
                patch("njupt_autologin.platform_services.windows.time.monotonic", return_value=200.0),
            ):
                self.assertTrue(adapter.pause())
                self.assertFalse(adapter.scheduled_login_allowed())
            with (
                patch("njupt_autologin.platform_services.windows._pause_path", return_value=marker),
                patch("njupt_autologin.platform_services.windows.time.monotonic", return_value=10.0),
            ):
                self.assertTrue(adapter.scheduled_login_allowed())
                self.assertFalse(marker.exists())

    def test_install_keeps_credentials_out_of_the_task_command(self):
        adapter = WindowsServiceAdapter()
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "credentials.json"
            credential.write_text("private", encoding="utf-8")
            with (
                patch("njupt_autologin.platform_services.windows.load_credentials"),
                patch("njupt_autologin.platform_services.windows._run") as run,
                patch.object(adapter, "resume"),
            ):
                adapter.install("Ethernet 2", credential)
            command = run.call_args.args[0]
            task_action = command[command.index("/TR") + 1]
            self.assertIn(str(credential.resolve()), task_action)
            self.assertNotIn("private", task_action)
            self.assertIn("--scheduled", task_action)


if __name__ == "__main__":
    unittest.main()
