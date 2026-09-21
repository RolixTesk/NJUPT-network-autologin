import unittest

from njupt_autologin.client import CampusClient, PortalError, Response
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


if __name__ == "__main__":
    unittest.main()
