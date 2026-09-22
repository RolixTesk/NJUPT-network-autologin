import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from njupt_autologin.platform_services.windows import WindowsServiceAdapter


class WindowsServiceTests(unittest.TestCase):
    def test_registry_startup_is_enabled_without_being_a_running_service(self):
        adapter = WindowsServiceAdapter()
        with patch(
            "njupt_autologin.platform_services.windows._read_startup_command",
            return_value="njupt-autologin-task.exe login --scheduled",
        ):
            status = adapter.status()
        self.assertTrue(status.installed)
        self.assertTrue(status.enabled)
        self.assertFalse(status.active)
        self.assertTrue(status.linger)

    def test_pause_marker_blocks_only_the_current_boot(self):
        adapter = WindowsServiceAdapter()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pause"
            with (
                patch("njupt_autologin.platform_services.windows._pause_path", return_value=marker),
                patch.object(adapter, "_startup_enabled", return_value=(True, True)),
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

    def test_install_keeps_credentials_out_of_the_startup_command(self):
        adapter = WindowsServiceAdapter()
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "credentials.json"
            credential.write_text("private", encoding="utf-8")
            with (
                patch("njupt_autologin.platform_services.windows.load_credentials"),
                patch("njupt_autologin.platform_services.windows._remove_legacy_task") as remove_legacy,
                patch("njupt_autologin.platform_services.windows._write_startup_command") as write,
                patch.object(adapter, "resume"),
            ):
                adapter.install("Ethernet 2", credential)
            startup_command = write.call_args.args[0]
            remove_legacy.assert_called_once_with()
            self.assertIn(str(credential.resolve()), startup_command)
            self.assertNotIn("private", startup_command)
            self.assertIn("--scheduled", startup_command)
            self.assertIn("--startup-delay 30", startup_command)


if __name__ == "__main__":
    unittest.main()
