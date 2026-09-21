import unittest
from unittest.mock import Mock, patch

from njupt_autologin.cli import main


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
        client.probe.return_value.state = "internet_ok"
        with (
            patch("njupt_autologin.cli.CampusClient.online_campus_interface") as global_check,
            patch("njupt_autologin.cli.CampusClient", return_value=client),
            patch("njupt_autologin.cli._emit") as emit,
        ):
            result = main(["login", "--force"])
        self.assertEqual(result, 0)
        global_check.assert_not_called()
        emit.assert_called_once_with(False, "already_online", interface="ens38")


if __name__ == "__main__":
    unittest.main()
