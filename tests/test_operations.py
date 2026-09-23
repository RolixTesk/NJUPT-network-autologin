import unittest
from unittest.mock import Mock, patch

from njupt_autologin.client import NetworkStatus
from njupt_autologin.credentials import Credentials
from njupt_autologin.operations import login_once


class LoginOperationTests(unittest.TestCase):
    def test_existing_session_does_not_read_credentials(self):
        credential_factory = Mock()
        with patch(
            "njupt_autologin.operations.CampusClient.online_campus_interface",
            return_value="ens33",
        ):
            outcome = login_once("auto", credential_factory)
        self.assertEqual(outcome.state, "already_online")
        self.assertEqual(outcome.interface, "ens33")
        credential_factory.assert_not_called()

    def test_portal_assessment_is_reused_by_login(self):
        current = NetworkStatus("portal_detected", 302, "10.10.244.11")
        client = Mock(interface="ens38")
        client.authentication_status.return_value = current
        client.login.return_value = "login_success"
        credentials = Credentials("student", "secret", "mobile")
        with patch("njupt_autologin.operations.CampusClient", return_value=client) as factory:
            factory.online_campus_interface.return_value = None
            outcome = login_once("auto", lambda: credentials)
        client.authentication_status.assert_called_once_with()
        client.login.assert_called_once_with(credentials, initial_status=current)
        self.assertEqual(outcome.credentials, credentials)

    def test_force_skips_global_session_search(self):
        current = NetworkStatus("internet_ok", 200)
        client = Mock(interface="ens38")
        client.authentication_status.return_value = current
        with patch("njupt_autologin.operations.CampusClient", return_value=client) as factory:
            outcome = login_once("auto", Mock(), force=True)
        factory.online_campus_interface.assert_not_called()
        self.assertEqual(outcome, outcome.__class__("already_online", "ens38"))


if __name__ == "__main__":
    unittest.main()
