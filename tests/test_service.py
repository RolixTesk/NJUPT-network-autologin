import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from njupt_autologin.service import (
    ServiceError,
    enable_linger,
    install_service,
    pause_service,
    service_status,
    uninstall_service,
)


def completed(command, returncode=0):
    return subprocess.CompletedProcess(command, returncode, "", "")


class ServiceTests(unittest.TestCase):
    def test_install_writes_units_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            credential = home / "credentials.json"
            credential.write_text("secret-content", encoding="utf-8")
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                return completed(command)

            with (
                patch("njupt_autologin.service.Path.home", return_value=home),
                patch("njupt_autologin.service.default_path", return_value=credential),
                patch("njupt_autologin.service.load_credentials"),
                patch("njupt_autologin.service._run", side_effect=fake_run),
            ):
                service, timer = install_service("ens33")

            service_text = service.read_text(encoding="utf-8")
            self.assertIn('--interface "ens33"', service_text)
            self.assertNotIn("secret-content", service_text)
            self.assertTrue(timer.is_file())
            self.assertEqual(commands[-1][-2:], ["--now", "njupt-autologin.timer"])

    def test_install_rejects_invalid_interface(self):
        with self.assertRaises(ServiceError):
            install_service("ens33;shutdown")

    def test_uninstall_removes_service_but_keeps_credentials_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            unit_dir = home / ".config" / "systemd" / "user"
            unit_dir.mkdir(parents=True)
            for name in ("njupt-autologin.service", "njupt-autologin.timer"):
                (unit_dir / name).write_text("unit", encoding="utf-8")
            app = home / ".local" / "share" / "njupt-autologin" / "app"
            app.mkdir(parents=True)
            credential = home / "credentials.json"
            credential.write_text("secret", encoding="utf-8")
            with (
                patch("njupt_autologin.service.Path.home", return_value=home),
                patch("njupt_autologin.service.default_path", return_value=credential),
                patch("njupt_autologin.service._run", side_effect=lambda command, **_kwargs: completed(command)),
            ):
                uninstall_service()

            self.assertFalse((unit_dir / "njupt-autologin.service").exists())
            self.assertFalse((unit_dir / "njupt-autologin.timer").exists())
            self.assertFalse(app.parent.exists())
            self.assertTrue(credential.exists())

    def test_uninstall_can_remove_credentials_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            credential = home / "credentials.json"
            credential.write_text("secret", encoding="utf-8")
            with (
                patch("njupt_autologin.service.Path.home", return_value=home),
                patch("njupt_autologin.service.default_path", return_value=credential),
                patch("njupt_autologin.service._run", side_effect=lambda command, **_kwargs: completed(command)),
            ):
                uninstall_service(remove_credentials=True)
            self.assertFalse(credential.exists())

    def test_enable_linger_uses_privilege_helper_when_needed(self):
        with (
            patch("njupt_autologin.service._linger_enabled", side_effect=(False, True)),
            patch("njupt_autologin.service.shutil.which", return_value="/usr/bin/pkexec"),
            patch("njupt_autologin.service._run") as run,
        ):
            enable_linger()
        self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/pkexec", "loginctl"])

    def test_pause_service_stops_an_active_timer(self):
        responses = iter((completed([], 0), completed([], 0)))
        with patch("njupt_autologin.service._run", side_effect=lambda *_args, **_kwargs: next(responses)) as run:
            self.assertTrue(pause_service())
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["stop", "njupt-autologin.timer"])

    def test_enabled_packaged_timer_counts_as_installed_for_user(self):
        with tempfile.TemporaryDirectory() as directory:
            responses = iter((completed([], 0), completed([], 3)))
            with (
                patch("njupt_autologin.service.Path.home", return_value=Path(directory)),
                patch("njupt_autologin.service._run", side_effect=lambda *_args, **_kwargs: next(responses)),
                patch("njupt_autologin.service._linger_enabled", return_value=True),
            ):
                status = service_status()
        self.assertTrue(status.installed)
        self.assertTrue(status.enabled)
        self.assertFalse(status.active)
        self.assertTrue(status.linger)


if __name__ == "__main__":
    unittest.main()
