import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from njupt_autologin.client import NetworkStatus
from njupt_autologin.credentials import Credentials
from njupt_autologin.gui import ControlPanel, create_server


class FakePanel:
    def __init__(self):
        self.calls = []

    @staticmethod
    def state():
        return {
            "credentials": {"exists": True, "username": "student", "operator": "mobile"},
            "service": {
                "supported": True,
                "installed": True,
                "enabled": True,
                "active": True,
                "linger": True,
            },
            "platform": "linux",
        }

    def run(self, action, payload):
        self.calls.append((action, payload))
        return "done"


class GuiServerTests(unittest.TestCase):
    def setUp(self):
        self.panel = FakePanel()
        self.server = create_server(panel=self.panel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, *, payload=None, token=None, host=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["X-CSRF-Token"] = token
        if host is not None:
            headers["Host"] = host
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        return self.opener.open(request, timeout=3)

    def test_index_is_loopback_only_and_has_browser_security_headers(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with self.request("/") as response:
            body = response.read().decode()
            self.assertIn("NJUPT 校园网自动登录", body)
            self.assertNotIn("__CSRF_TOKEN__", body)
            self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        with self.request("/app-icon.svg") as response:
            self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
            self.assertIn(b"NJUPT", response.read())

    def test_state_never_contains_a_password_field(self):
        with self.request("/api/state") as response:
            body = response.read().decode()
            value = json.loads(body)
        self.assertTrue(value["ok"])
        self.assertNotIn("password", body.lower())

    def test_post_requires_csrf_token(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/save", payload={"username": "student"})
        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(self.panel.calls, [])

    def test_authorized_post_dispatches_action(self):
        payload = {"username": "student", "password": "example", "operator": "mobile"}
        with self.request("/api/save", payload=payload, token=self.server.csrf_token) as response:
            value = json.load(response)
        self.assertTrue(value["ok"])
        self.assertEqual(self.panel.calls, [("save", payload)])

    def test_rejects_non_loopback_host_header(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/state", host="example.invalid")
        self.assertEqual(raised.exception.code, 421)


class ControlPanelActionTests(unittest.TestCase):
    def test_login_does_not_load_credentials_when_campus_is_already_online(self):
        panel = ControlPanel()
        with (
            patch("njupt_autologin.gui.CampusClient.online_campus_interface", return_value="ens33"),
            patch.object(panel, "_credentials") as credentials,
        ):
            message = panel.run("login", {"interface": "auto"})
        credentials.assert_not_called()
        self.assertIn("ens33", message)
        self.assertIn("未重复", message)

    def test_login_authenticates_and_saves_credentials_after_success(self):
        panel = ControlPanel()
        client = Mock()
        client.interface = "ens33"
        client.probe.return_value = NetworkStatus("portal_detected", 302, "10.10.244.11")
        client.login.return_value = "login_success"
        credentials = Credentials("student", "secret", "mobile")
        with (
            patch("njupt_autologin.gui.CampusClient", return_value=client) as client_class,
            patch.object(panel, "_credentials", return_value=credentials),
            patch("njupt_autologin.gui.save_credentials") as save,
        ):
            client_class.online_campus_interface.return_value = None
            message = panel.run("login", {"interface": "auto"})
        client.login.assert_called_once_with(credentials)
        save.assert_called_once_with(credentials)
        self.assertIn("登录成功", message)

    def test_install_runs_immediate_login_after_enabling_service(self):
        panel = ControlPanel()
        credentials = Credentials("student", "secret", "mobile")
        payload = {"interface": "ens33"}
        with (
            patch.object(panel, "_credentials", return_value=credentials),
            patch.object(panel, "_login_now", return_value="校园网登录成功（接口 ens33）。") as login,
            patch("njupt_autologin.gui.save_credentials"),
            patch("njupt_autologin.gui.enable_linger"),
            patch("njupt_autologin.gui.install_service") as install,
        ):
            message = panel.run("install", payload)
        install.assert_called_once_with("ens33")
        login.assert_called_once_with(payload, credentials)
        self.assertIn("立即", message)


if __name__ == "__main__":
    unittest.main()
