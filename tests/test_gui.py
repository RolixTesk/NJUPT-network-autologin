import unittest
from unittest.mock import Mock, patch

from njupt_autologin.client import NetworkStatus
from njupt_autologin.credentials import Credentials
from njupt_autologin.gui_actions import login_now, service_status_items
from njupt_autologin.service import ServiceStatus


class ImmediateLoginTests(unittest.TestCase):
    def test_existing_campus_session_does_not_read_credentials(self):
        credential_factory = Mock()
        with patch("njupt_autologin.gui_actions.CampusClient.online_campus_interface", return_value="ens33"):
            message = login_now("auto", credential_factory)
        credential_factory.assert_not_called()
        self.assertIn("ens33", message)
        self.assertIn("未重复", message)

    def test_portal_authenticates_and_saves_credentials(self):
        client = Mock()
        client.interface = "ens33"
        client.probe.return_value = NetworkStatus("portal_detected", 302, "10.10.244.11")
        client.login.return_value = "login_success"
        credentials = Credentials("student", "secret", "mobile")
        credential_factory = Mock(return_value=credentials)
        with (
            patch("njupt_autologin.gui_actions.CampusClient", return_value=client) as client_class,
            patch("njupt_autologin.gui_actions.save_credentials") as save,
        ):
            client_class.online_campus_interface.return_value = None
            message = login_now("auto", credential_factory)
        credential_factory.assert_called_once_with()
        client.login.assert_called_once_with(credentials)
        save.assert_called_once_with(credentials)
        self.assertIn("登录成功", message)


class ServiceStatusLabelTests(unittest.TestCase):
    def test_installed_active_service_has_three_positive_values(self):
        labels = service_status_items(ServiceStatus(True, True, True, True))
        self.assertEqual(labels, (("已安装", "success"), ("运行中", "success"), ("已启用", "success")))

    def test_uninstalled_service_is_clear(self):
        labels = service_status_items(ServiceStatus(False, False, False, False))
        self.assertEqual(labels[0], ("未安装", "muted"))
        self.assertEqual(labels[1], ("未启用", "muted"))


if __name__ == "__main__":
    unittest.main()
