import subprocess
import unittest
from unittest.mock import Mock, patch

from njupt_autologin.client import CampusClient, NetworkError, NetworkStatus, PortalError, Response
from njupt_autologin.credentials import Credentials


class CredentialTests(unittest.TestCase):
    def test_key_style_file_ignores_vm_password(self):
        content = '''network login:
    username: campus-id
    password: campus-pass
    "运营商": 中国移动

VM Ubuntu:
    username: vm-user
    password: vm-pass
'''
        credential = Credentials.from_text(content)
        self.assertEqual(credential.account, "campus-id@cmcc")
        self.assertEqual(credential.password, "campus-pass")

    def test_username_suffix_must_match_operator(self):
        with self.assertRaises(ValueError):
            _ = Credentials("id@cmcc", "secret", "telecom").account


class ProtocolTests(unittest.TestCase):
    def test_jsonp_parser_rejects_executable_prefix(self):
        with self.assertRaises(PortalError):
            CampusClient._parse_jsonp(b'evil(); dr123({"result":1})', "dr123")
        self.assertEqual(CampusClient._parse_jsonp(b'dr123({"result":1});', "dr123")["result"], 1)

    def test_login_fields_match_observed_portal_request(self):
        fields = dict(CampusClient._login_fields(
            Credentials("student", "fake-pass", "mobile"),
            "10.0.0.2",
            {"ss4": "000000000000", "vid": 0},
            {"no_filter_accandpwd": 0, "rcn": "nonce123", "program_index": "program", "page_index": "page", "enable_r3": 0},
        ))
        observed = {
            "login_method", "is_base64encode", "user_account", "user_password",
            "wlan_user_ip", "wlan_user_ipv6", "wlan_user_mac", "wlan_vlan_id",
            "wlan_ac_ip", "wlan_ac_name", "authex_enable", "jsVersion",
            "terminal_type", "lang", "user_agent", "enable_r3", "mac_type",
            "rcn", "operate", "business_type", "program_index", "page_index",
        }
        self.assertEqual(set(fields), observed)
        self.assertEqual(fields["user_account"], ",0,student@cmcc")
        self.assertEqual(fields["user_password"], "fake-pass")
        self.assertEqual(fields["business_type"], "1")
        self.assertEqual(fields["rcn"], "nonce123")

    def test_probe_classifies_expected_response(self):
        client = object.__new__(CampusClient)
        client._request = lambda *_args, **_kwargs: Response(204, "", "", b"")
        self.assertEqual(client.probe().state, "internet_ok")
        client._request = lambda *_args, **_kwargs: Response(302, "", "http://10.10.244.11/a79.htm", b"")
        self.assertEqual(client.probe().state, "portal_detected")

    def test_logout_verifies_portal_transition(self):
        client = object.__new__(CampusClient)
        client.interface = "ens33"
        client.timeout = 5
        client.probe = Mock(side_effect=(
            NetworkStatus("internet_ok", 204),
            NetworkStatus("portal_detected", 302, "10.10.244.11"),
        ))
        client._request = Mock(return_value=Response(200, "text/html", "", b"failure marker"))
        with patch("njupt_autologin.client.time.sleep"):
            self.assertEqual(client.logout(), "logout_success")
        request = client._request.call_args
        self.assertEqual(request.args[:2], ("10.10.244.11", 801))
        self.assertIn("ACSetting&a=Logout", request.args[2])

    def test_logout_is_idempotent_when_portal_is_already_present(self):
        client = object.__new__(CampusClient)
        client.probe = Mock(return_value=NetworkStatus("portal_detected", 302))
        client._request = Mock()
        self.assertEqual(client.logout(), "already_offline")
        client._request.assert_not_called()


class AutoInterfaceTests(unittest.TestCase):
    def test_default_interfaces_are_unique_and_sorted_by_metric(self):
        output = (
            "default via 192.0.2.1 dev wlan0 metric 600\n"
            "default via 10.0.0.1 dev ens33 metric 100\n"
            "default via 10.0.0.2 dev ens33 metric 200\n"
        )
        result = subprocess.CompletedProcess([], 0, output, "")
        with patch("njupt_autologin.client.subprocess.run", return_value=result):
            self.assertEqual(CampusClient._default_interfaces(), ["ens33", "wlan0"])

    def test_auto_uses_the_only_default_interface(self):
        with (
            patch.object(CampusClient, "_default_interfaces", return_value=["ens33"]),
            patch.object(CampusClient, "_interface_ip", return_value="10.0.0.2"),
            patch.object(CampusClient, "_require_route"),
        ):
            client = CampusClient("auto")
        self.assertEqual(client.interface, "ens33")

    def test_auto_prefers_known_njupt_portal(self):
        def probe(client, attempts=2):
            del attempts
            if client.interface == "ens33":
                return NetworkStatus("portal_detected", 302, "10.10.244.11")
            return NetworkStatus("internet_ok", 204)

        with (
            patch.object(CampusClient, "_default_interfaces", return_value=["wlan0", "ens33"]),
            patch.object(CampusClient, "_interface_ip", side_effect=lambda interface: {"wlan0": "192.0.2.2", "ens33": "10.0.0.2"}[interface]),
            patch.object(CampusClient, "_require_route"),
            patch.object(CampusClient, "probe", probe),
            patch.object(CampusClient, "_status_data", side_effect=PortalError("not campus")),
        ):
            client = CampusClient("auto")
        self.assertEqual(client.interface, "ens33")

    def test_auto_prefers_confirmed_online_campus_by_default(self):
        def probe(client, attempts=2):
            del attempts
            if client.interface == "ens38":
                return NetworkStatus("portal_detected", 302, "10.10.244.11")
            return NetworkStatus("internet_ok", 204)

        def status_data(client):
            if client.interface == "ens33":
                return {"result": 1}
            raise PortalError("not online")

        common = (
            patch.object(CampusClient, "_default_interfaces", return_value=["ens33", "ens38"]),
            patch.object(CampusClient, "_interface_ip", return_value="10.0.0.2"),
            patch.object(CampusClient, "_require_route"),
            patch.object(CampusClient, "probe", probe),
            patch.object(CampusClient, "_status_data", status_data),
        )
        with common[0], common[1], common[2], common[3], common[4]:
            client = CampusClient("auto")
        self.assertEqual(client.interface, "ens33")

    def test_force_prefers_waiting_portal_over_online_campus(self):
        def probe(client, attempts=2):
            del attempts
            if client.interface == "ens38":
                return NetworkStatus("portal_detected", 302, "10.10.244.11")
            return NetworkStatus("internet_ok", 204)

        def status_data(client):
            if client.interface == "ens33":
                return {"result": 1}
            raise PortalError("not online")

        with (
            patch.object(CampusClient, "_default_interfaces", return_value=["ens33", "ens38"]),
            patch.object(CampusClient, "_interface_ip", return_value="10.0.0.2"),
            patch.object(CampusClient, "_require_route"),
            patch.object(CampusClient, "probe", probe),
            patch.object(CampusClient, "_status_data", status_data),
        ):
            client = CampusClient("auto", prefer_portal=True)
        self.assertEqual(client.interface, "ens38")

    def test_online_campus_interface_returns_route_preferred_session(self):
        def probe(client, attempts=2):
            del attempts
            state = "internet_ok" if client.interface == "ens33" else "portal_detected"
            return NetworkStatus(state)

        with (
            patch.object(CampusClient, "_default_interfaces", return_value=["ens33", "ens38"]),
            patch.object(CampusClient, "_interface_ip", return_value="10.0.0.2"),
            patch.object(CampusClient, "_require_route"),
            patch.object(CampusClient, "probe", probe),
            patch.object(CampusClient, "_status_data", return_value={"result": 1}),
        ):
            self.assertEqual(CampusClient.online_campus_interface(), "ens33")

    def test_auto_rejects_ambiguous_online_interfaces(self):
        with (
            patch.object(CampusClient, "_default_interfaces", return_value=["wlan0", "eth0"]),
            patch.object(CampusClient, "_interface_ip", return_value="192.0.2.2"),
            patch.object(CampusClient, "_require_route"),
            patch.object(CampusClient, "probe", return_value=NetworkStatus("internet_ok", 204)),
            patch.object(CampusClient, "_status_data", side_effect=PortalError("not campus")),
        ):
            with self.assertRaises(NetworkError):
                CampusClient("auto")

    def test_auto_uses_route_order_when_both_interfaces_are_confirmed_campus(self):
        with (
            patch.object(CampusClient, "_default_interfaces", return_value=["eth0", "wlan0"]),
            patch.object(CampusClient, "_interface_ip", return_value="192.0.2.2"),
            patch.object(CampusClient, "_require_route"),
            patch.object(CampusClient, "probe", return_value=NetworkStatus("internet_ok", 204)),
            patch.object(CampusClient, "_status_data", return_value={"result": 1}),
        ):
            client = CampusClient("auto")
        self.assertEqual(client.interface, "eth0")


if __name__ == "__main__":
    unittest.main()
