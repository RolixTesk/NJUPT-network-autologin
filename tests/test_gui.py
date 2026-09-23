import unittest
from unittest.mock import Mock, patch

from njupt_autologin.client import NetworkStatus
from njupt_autologin.credentials import Credentials
from njupt_autologin.gui_actions import (
    ConnectionSnapshot,
    connection_status,
    connection_status_text,
    login_now,
    service_status_items,
)
from njupt_autologin.operations import LoginOutcome
from njupt_autologin.service import ServiceStatus


class ImmediateLoginTests(unittest.TestCase):
    def test_existing_campus_session_does_not_read_credentials(self):
        credential_factory = Mock()
        with patch(
            "njupt_autologin.gui_actions.login_once",
            return_value=LoginOutcome("already_online", "ens33"),
        ):
            message = login_now("auto", credential_factory)
        credential_factory.assert_not_called()
        self.assertIn("ens33", message)
        self.assertIn("未重复", message)

    def test_portal_authenticates_and_saves_credentials(self):
        credentials = Credentials("student", "secret", "mobile")
        credential_factory = Mock(return_value=credentials)
        with (
            patch(
                "njupt_autologin.gui_actions.login_once",
                return_value=LoginOutcome("login_success", "ens33", credentials),
            ) as login,
            patch("njupt_autologin.gui_actions.save_credentials") as save,
        ):
            message = login_now("auto", credential_factory)
        login.assert_called_once_with("auto", credential_factory)
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

    def test_enabled_but_paused_timer_is_not_a_warning(self):
        labels = service_status_items(ServiceStatus(True, True, False, True))
        self.assertEqual(labels[1], ("已启用", "success"))


class ConnectionStatusTests(unittest.TestCase):
    def test_all_online_campus_interfaces_are_preserved_for_warning(self):
        with patch(
            "njupt_autologin.gui_actions.CampusClient.online_campus_interfaces",
            return_value=["ens33", "wlan0"],
        ):
            snapshot = connection_status("auto")
        self.assertEqual(snapshot, ConnectionSnapshot("campus_online", "ens33", ("ens33", "wlan0")))
        title, detail, kind = connection_status_text(snapshot)
        self.assertEqual(title, "校园网已登录")
        self.assertIn("ens33", detail)
        self.assertEqual(kind, "success")

    def test_portal_state_reports_selected_interface(self):
        client = Mock(interface="ens33")
        client.authentication_status.return_value = NetworkStatus("portal_detected", 302)
        with patch("njupt_autologin.gui_actions.CampusClient", return_value=client) as client_class:
            client_class.online_campus_interfaces.return_value = []
            snapshot = connection_status("auto")
        self.assertEqual(snapshot.state, "portal_detected")
        self.assertEqual(snapshot.interface, "ens33")


if __name__ == "__main__":
    unittest.main()
