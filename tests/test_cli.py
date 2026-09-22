import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from njupt_autologin.cli import EXIT_AUTH, main
from njupt_autologin.client import PortalError


class HelpAliasTests(unittest.TestCase):
    def test_main_help_alias_exits_successfully(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main(["-help"])
        self.assertEqual(result.exception.code, 0)
        self.assertIn("njupt-autologin", output.getvalue())
        self.assertIn("install-service", output.getvalue())

    def test_every_subcommand_accepts_help_alias(self):
        for command in (
            "status", "login", "logout", "configure",
            "install-service", "uninstall-service",
        ):
            with self.subTest(command=command):
                output = StringIO()
                with redirect_stdout(output), self.assertRaises(SystemExit) as result:
                    main([command, "-help"])
                self.assertEqual(result.exception.code, 0)
                self.assertIn(f"njupt-autologin {command}", output.getvalue())


class LoginPolicyTests(unittest.TestCase):
    def test_existing_campus_session_exits_without_loading_credentials(self):
        with (
            patch("njupt_autologin.cli.CampusClient.online_campus_interface", return_value="ens33"),
            patch("njupt_autologin.cli.load_credentials") as load,
            patch("njupt_autologin.cli._emit") as emit,
        ):
            result = main(["login"])
        self.assertEqual(result, 0)
        load.assert_not_called()
        emit.assert_called_once_with(False, "already_online", interface="ens33")

    def test_force_skips_global_online_session_check(self):
        client = Mock()
        client.interface = "ens38"
        client.authentication_status.return_value.state = "internet_ok"
        with (
            patch("njupt_autologin.cli.CampusClient.online_campus_interface") as global_check,
            patch("njupt_autologin.cli.CampusClient", return_value=client),
            patch("njupt_autologin.cli._emit") as emit,
        ):
            result = main(["login", "--force"])
        self.assertEqual(result, 0)
        global_check.assert_not_called()
        emit.assert_called_once_with(False, "already_online", interface="ens38")

    def test_logout_pauses_active_timer(self):
        client = Mock()
        client.interface = "ens33"
        client.logout.return_value = "logout_success"
        services = Mock()
        services.pause.return_value = True
        with (
            patch("njupt_autologin.cli.CampusClient", return_value=client),
            patch("njupt_autologin.cli.load_service_adapter", return_value=services),
            patch("njupt_autologin.cli._emit") as emit,
        ):
            result = main(["logout"])
        self.assertEqual(result, 0)
        services.pause.assert_called_once_with()
        services.resume.assert_not_called()
        emit.assert_called_once_with(
            False, "logout_success", interface="ens33", timer_paused=True
        )

    def test_logout_failure_restores_active_timer(self):
        client = Mock()
        client.logout.side_effect = PortalError("still online")
        services = Mock()
        services.pause.return_value = True
        with (
            patch("njupt_autologin.cli.CampusClient", return_value=client),
            patch("njupt_autologin.cli.load_service_adapter", return_value=services),
            redirect_stderr(StringIO()),
        ):
            result = main(["logout"])
        self.assertEqual(result, EXIT_AUTH)
        services.resume.assert_called_once_with()

    def test_scheduled_login_obeys_pause_marker_before_network_access(self):
        services = Mock()
        services.scheduled_login_allowed.return_value = False
        with (
            patch("njupt_autologin.cli.load_service_adapter", return_value=services),
            patch("njupt_autologin.cli.CampusClient") as client,
            patch("njupt_autologin.cli._emit") as emit,
        ):
            result = main(["login", "--scheduled"])
        self.assertEqual(result, 0)
        client.assert_not_called()
        emit.assert_called_once_with(False, "service_paused")


if __name__ == "__main__":
    unittest.main()
