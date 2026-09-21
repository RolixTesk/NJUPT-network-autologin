"""Bound-interface, browser-free client for the observed NJUPT portal."""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from .credentials import Credentials


PORTAL_HOST = "p.njupt.edu.cn"
CONNECTIVITY_HOST = "connectivitycheck.gstatic.com"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0"
JS_VERSION = "4.5"
MAX_RESPONSE = 262_144


class NetworkError(RuntimeError):
    pass


class PortalError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    location: str
    body: bytes


@dataclass(frozen=True)
class NetworkStatus:
    state: str
    http_status: int | None = None
    portal_host: str | None = None


class CampusClient:
    def __init__(self, interface: str = "ens33", timeout: float = 10.0) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface):
            raise ValueError("invalid interface name")
        if not 0 < timeout <= 60:
            raise ValueError("timeout must be between 0 and 60 seconds")
        self.interface = interface
        self.timeout = timeout
        self.local_ip = self._interface_ip(interface)
        self._require_route("1.1.1.1")

    @staticmethod
    def _interface_ip(interface: str) -> str:
        try:
            result = subprocess.run(
                ["ip", "-4", "-o", "addr", "show", "dev", interface],
                check=True, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NetworkError("cannot inspect the campus interface") from exc
        match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)/", result.stdout)
        if not match:
            raise NetworkError("campus interface has no IPv4 address")
        return str(ipaddress.IPv4Address(match.group(1)))

    def _require_route(self, destination: str) -> None:
        try:
            result = subprocess.run(
                ["ip", "-4", "route", "get", destination],
                check=True, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NetworkError("cannot inspect the campus route") from exc
        match = re.search(r"\bdev (\S+)", result.stdout)
        if not match or match.group(1) != self.interface:
            raise NetworkError("default internet route does not use the campus interface")

    def _request(self, host: str, port: int, path: str, *, secure: bool = True) -> Response:
        try:
            cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
            options: dict[str, object] = {"timeout": self.timeout, "source_address": (self.local_ip, 0)}
            if secure:
                options["context"] = ssl.create_default_context()
            connection = cls(host, port, **options)
            try:
                connection.request("GET", path, headers={
                    "Accept": "*/*",
                    "Referer": f"https://{PORTAL_HOST}/a79.htm",
                    "User-Agent": USER_AGENT,
                })
                response = connection.getresponse()
                body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    raise PortalError("portal response exceeds the size limit")
                return Response(
                    status=response.status,
                    content_type=response.getheader("Content-Type", ""),
                    location=response.getheader("Location", ""),
                    body=body,
                )
            finally:
                connection.close()
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            # Exception messages can include a URL containing credentials.
            raise NetworkError(f"request failed ({type(exc).__name__})") from None

    def probe(self, attempts: int = 2) -> NetworkStatus:
        if not 1 <= attempts <= 3:
            raise ValueError("attempts must be between 1 and 3")
        for index in range(attempts):
            try:
                response = self._request(CONNECTIVITY_HOST, 80, "/generate_204", secure=False)
                break
            except NetworkError:
                if index == attempts - 1:
                    return NetworkStatus("network_unavailable")
                time.sleep(1)
        if response.status == 204:
            return NetworkStatus("internet_ok", 204)
        if response.status in (301, 302, 303, 307, 308):
            return NetworkStatus("portal_detected", response.status, urlsplit(response.location).hostname)
        if response.status == 200 and "text/html" in response.content_type.lower():
            return NetworkStatus("portal_detected", 200)
        return NetworkStatus("unexpected_response", response.status)

    @staticmethod
    def _parse_jsonp(body: bytes, callback: str) -> dict[str, object]:
        text = body.decode("utf-8", errors="strict").strip()
        match = re.fullmatch(r"([A-Za-z_$][\w$]*)\((.*)\);?", text, re.S)
        if not match or match.group(1) != callback:
            raise PortalError("invalid JSONP response")
        try:
            result = json.loads(match.group(2))
        except json.JSONDecodeError as exc:
            raise PortalError("invalid portal JSON") from exc
        if not isinstance(result, dict):
            raise PortalError("invalid portal object")
        return result

    def _jsonp(self, port: int, route: str, fields: list[tuple[str, str]], *, lang: str = "zh") -> dict[str, object]:
        callback = "dr" + secrets.token_hex(4)
        pairs = [("callback", callback), *fields, ("v", str(secrets.randbelow(10_000) + 500)), ("lang", lang)]
        response = self._request(PORTAL_HOST, port, route + "?" + urlencode(pairs))
        if response.status != 200:
            raise PortalError(f"portal endpoint returned HTTP {response.status}")
        return self._parse_jsonp(response.body, callback)

    def _status_data(self) -> dict[str, object]:
        result = self._jsonp(443, "/drcom/chkstatus", [("jsVersion", JS_VERSION)])
        if result.get("ss5") != self.local_ip:
            raise PortalError("portal client IP differs from the campus interface")
        return result

    def _config(self) -> dict[str, object]:
        fields = [
            ("program_index", ""), ("page_index", ""), ("wlan_vlan_id", "0"),
            ("wlan_user_ip", base64.b64encode(self.local_ip.encode()).decode()),
            ("wlan_user_ipv6", ""), ("wlan_user_ssid", ""), ("wlan_user_areaid", ""),
            ("wlan_ac_ip", ""), ("wlan_ap_mac", "000000000000"),
            ("gw_id", "000000000000"), ("jsVersion", JS_VERSION),
        ]
        result = self._jsonp(804, "/eportal/portal/page/loadConfig", fields)
        data = result.get("data")
        if result.get("code") != 1 or not isinstance(data, dict):
            raise PortalError("portal configuration unavailable")
        expected = {
            "login_method": "1", "en_md5": "0", "enable_slide_verify": "0",
            "enable_login_verify": "0", "account_prefix": "1", "en_perceive": "0",
        }
        if any(str(data.get(key)) != value for key, value in expected.items()):
            raise PortalError("portal authentication settings changed")
        if str(data.get("no_filter_accandpwd")) not in ("0", "1"):
            raise PortalError("unsupported account encoding setting")
        if not all(data.get(key) for key in ("program_index", "page_index", "rcn")):
            raise PortalError("portal configuration lacks required fields")
        return data

    @staticmethod
    def _login_fields(credentials: Credentials, local_ip: str, status: dict[str, object], config: dict[str, object]) -> list[tuple[str, str]]:
        account = credentials.account
        encoded = str(config["no_filter_accandpwd"]) == "1"
        user_account = ",0," + account
        user_password = credentials.password
        if encoded:
            user_account = base64.b64encode(user_account.encode()).decode()
            user_password = base64.b64encode(user_password.encode()).decode()
        return [
            ("login_method", "1"), ("is_base64encode", "1" if encoded else "0"),
            ("user_account", user_account), ("user_password", user_password),
            ("wlan_user_ip", local_ip), ("wlan_user_ipv6", ""),
            ("wlan_user_mac", str(status.get("ss4", "000000000000"))),
            ("wlan_vlan_id", str(status.get("vid", 0))),
            ("wlan_ac_ip", ""), ("wlan_ac_name", ""),
            ("authex_enable", ""), ("jsVersion", JS_VERSION),
            ("terminal_type", "1"), ("lang", "en"), ("user_agent", USER_AGENT),
            ("enable_r3", str(config.get("enable_r3", 0))), ("mac_type", "0"),
            ("rcn", str(config["rcn"])), ("operate", "portal_login"),
            ("business_type", "1"),
            ("program_index", str(config["program_index"])),
            ("page_index", str(config["page_index"])),
        ]

    def login(self, credentials: Credentials) -> str:
        initial = self.probe()
        if initial.state == "internet_ok":
            return "already_online"
        if initial.state != "portal_detected":
            raise NetworkError(f"cannot authenticate from state {initial.state}")
        try:
            portal_ip = socket.gethostbyname(PORTAL_HOST)
        except OSError:
            raise NetworkError("cannot resolve the portal host") from None
        self._require_route(portal_ip)
        status = self._status_data()
        if str(status.get("result")) != "0":
            raise PortalError("portal state is not offline")
        config = self._config()
        result = self._jsonp(
            804, "/eportal/portal/login",
            self._login_fields(credentials, self.local_ip, status, config), lang="en",
        )
        if str(result.get("result")) not in ("1", "ok"):
            # Never include server messages: some deployments echo credentials.
            raise AuthenticationError("portal rejected the credentials or account state")
        for delay in (0, 2, 4):
            if delay:
                time.sleep(delay)
            if self.probe(attempts=1).state == "internet_ok":
                return "login_success"
        raise AuthenticationError("portal accepted login, but internet check still fails")
