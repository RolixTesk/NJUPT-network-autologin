"""Bound-interface, browser-free client for the observed NJUPT portal."""

from __future__ import annotations

import base64
import json
import re
import secrets
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit

from .credentials import Credentials
from .errors import AuthenticationError, NetworkError, PortalError
from .network_interfaces import default_interfaces, interface_ip, require_route, valid_interface_name
from .status_policy import NetworkStatus, status_with_session
from .transport import BoundHttpTransport, Response


PORTAL_HOST = "p.njupt.edu.cn"
PORTAL_IP = "10.10.244.11"
CONNECTIVITY_HOST = "connect.rom.miui.com"
EXTERNAL_CHECK_HOST = "www.baidu.com"
EXTERNAL_CHECK_PATH = "/favicon.ico"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0"
JS_VERSION = "4.5"


class CampusClient:
    def __init__(
        self, interface: str = "auto", timeout: float = 10.0, *, prefer_portal: bool = False
    ) -> None:
        if not 0 < timeout <= 60:
            raise ValueError("timeout must be between 0 and 60 seconds")
        if interface == "auto":
            interface = self._detect_interface(timeout, prefer_portal=prefer_portal)
        if not valid_interface_name(interface):
            raise ValueError("invalid interface name")
        self.interface = interface
        self.timeout = timeout
        self.local_ip = interface_ip(interface)
        self._transport = BoundHttpTransport(interface, self.local_ip, timeout)
        self._require_route("1.1.1.1")

    @classmethod
    def _detect_interface(cls, timeout: float, *, prefer_portal: bool = False) -> str:
        candidates = default_interfaces()
        if len(candidates) == 1:
            return candidates[0]
        def score(interface: str) -> int:
            try:
                client = cls(interface=interface, timeout=min(timeout, 4.0))
                try:
                    status = client.campus_status(attempts=1)
                    campus_confirmed = True
                except (NetworkError, PortalError):
                    status = client.probe(attempts=1)
                    campus_confirmed = False
                if status.state == "portal_detected" and status.portal_host in (PORTAL_HOST, PORTAL_IP):
                    return 5 if prefer_portal else 4
                elif status.state == "portal_detected":
                    return 2
                elif status.state == "internet_ok":
                    return (4 if prefer_portal else 5) if campus_confirmed else 1
                return 0
            except (NetworkError, PortalError):
                return 0

        with ThreadPoolExecutor(max_workers=min(3, len(candidates))) as pool:
            scores = list(pool.map(score, candidates))
        scored = list(zip(scores, candidates))
        best = max(score for score, _interface in scored)
        winners = [interface for score, interface in scored if score == best]
        # Candidates already follow route preference, so the first high-confidence
        # winner is deterministic. Weak evidence must still be unambiguous.
        if best >= 4:
            return winners[0]
        if best > 0 and len(winners) == 1:
            return winners[0]
        raise NetworkError("cannot uniquely detect the campus interface; specify --interface")

    @classmethod
    def online_campus_interface(cls, timeout: float = 10.0) -> str | None:
        """Return the first route-preferred interface with a confirmed online NJUPT session."""
        interfaces, results = cls._online_campus_results(timeout)
        return next((interface for interface, online in zip(interfaces, results) if online), None)

    @classmethod
    def online_campus_interfaces(cls, timeout: float = 10.0) -> list[str]:
        """Return every default-route interface with a confirmed online NJUPT session."""
        interfaces, results = cls._online_campus_results(timeout)
        return [interface for interface, online in zip(interfaces, results) if online]

    @classmethod
    def _online_campus_results(cls, timeout: float) -> tuple[list[str], list[bool]]:
        """Probe interfaces concurrently while preserving route order in returned results."""
        interfaces = default_interfaces()

        def is_online(interface: str) -> bool:
            try:
                client = cls(interface=interface, timeout=min(timeout, 4.0))
                return client.campus_status(attempts=1).state == "internet_ok"
            except (NetworkError, PortalError):
                return False

        with ThreadPoolExecutor(max_workers=min(3, len(interfaces))) as pool:
            results = list(pool.map(is_online, interfaces))
        return interfaces, results

    def _require_route(self, destination: str) -> None:
        require_route(self.interface, self.local_ip, destination)

    def _request(self, host: str, port: int, path: str, *, secure: bool = True) -> Response:
        return self._transport.request(
            host,
            port,
            path,
            secure=secure,
            headers={
                "Accept": "*/*",
                "Referer": f"https://{PORTAL_HOST}/a79.htm",
                "User-Agent": USER_AGENT,
            },
        )

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

    def _session_state(self) -> str:
        result = str(self._status_data().get("result"))
        if result in ("1", "ok"):
            return "online"
        if result == "0":
            return "offline"
        raise PortalError("portal returned an unknown session state")

    def _external_access_status(self) -> NetworkStatus:
        """Check a regular HTTPS site that is not a captive-portal connectivity exception."""
        try:
            response = self._request(EXTERNAL_CHECK_HOST, 443, EXTERNAL_CHECK_PATH, secure=True)
        except (NetworkError, PortalError):
            return NetworkStatus("network_unavailable")
        if response.status == 200:
            return NetworkStatus("internet_ok", 200)
        return NetworkStatus("unexpected_response", response.status)

    def _internet_access_status(self, attempts: int = 2) -> NetworkStatus:
        """Check direct Internet access without interpreting the portal session marker."""
        connectivity = self.probe(attempts=attempts)
        if connectivity.state != "internet_ok":
            return connectivity
        return self._external_access_status()

    def campus_status(self, attempts: int = 2) -> NetworkStatus:
        """Confirm the NJUPT endpoint plus domestic 204 and ordinary HTTPS access."""
        connectivity = self.probe(attempts=attempts)
        return status_with_session(
            connectivity, self._session_state(), self._external_access_status, portal_host=PORTAL_HOST
        )

    def authentication_status(self, attempts: int = 2) -> NetworkStatus:
        """Return campus status, falling back to connectivity on non-NJUPT networks."""
        connectivity = self.probe(attempts=attempts)
        try:
            session = self._session_state()
        except (NetworkError, PortalError):
            return connectivity
        return status_with_session(
            connectivity, session, self._external_access_status, portal_host=PORTAL_HOST
        )

    @staticmethod
    def _parse_jsonp(body: bytes, callback: str) -> dict[str, object]:
        """Parse only the callback generated for this request, never executable prefixes."""
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
        # These values describe the only protocol variant observed and tested.
        # Refuse a changed portal instead of sending a secret with unknown semantics.
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

    def login(
        self, credentials: Credentials, *, initial_status: NetworkStatus | None = None
    ) -> str:
        initial = initial_status or self.authentication_status()
        if initial.state == "internet_ok":
            return "already_online"
        if initial.state != "portal_detected":
            raise NetworkError(f"cannot authenticate from state {initial.state}")
        try:
            portal_ip = socket.gethostbyname(PORTAL_HOST)
        except OSError:
            raise NetworkError("cannot resolve the portal host") from None
        self._require_route(portal_ip)
        result = self._submit_login(credentials)
        if str(result.get("result")) not in ("1", "ok") and str(result.get("ret_code")) == "2":
            self._clear_stale_online_record()
            result = self._submit_login(credentials)
        if str(result.get("result")) not in ("1", "ok"):
            # Never include server messages: some deployments echo credentials.
            if str(result.get("ret_code")) == "2":
                raise AuthenticationError(
                    "portal still has an online record for this IP after one cleanup attempt"
                )
            raise AuthenticationError("portal rejected the credentials or account state")
        for delay in (0, 2, 4):
            if delay:
                time.sleep(delay)
            # A successful login response is the missing context that makes direct
            # connectivity useful even when chkstatus remains stale at "offline".
            if self._internet_access_status(attempts=1).state == "internet_ok":
                return "login_success"
        raise AuthenticationError("portal accepted login, but internet check still fails")

    def _submit_login(self, credentials: Credentials) -> dict[str, object]:
        status = self._status_data()
        if str(status.get("result")) != "0":
            raise PortalError("portal state is not offline")
        config = self._config()
        return self._jsonp(
            804, "/eportal/portal/login",
            self._login_fields(credentials, self.local_ip, status, config), lang="en",
        )

    def _clear_stale_online_record(self) -> None:
        response = self._request(
            PORTAL_IP, 801,
            "/eportal/?c=ACSetting&a=Logout&ver=1.0&url=drappall",
            secure=False,
        )
        if response.status != 200:
            raise PortalError(f"stale-session cleanup returned HTTP {response.status}")
        time.sleep(2)

    def logout(self) -> str:
        initial = self.authentication_status(attempts=1)
        if initial.state != "internet_ok" and self._session_state() == "offline":
            return "already_offline"
        response = self._request(
            PORTAL_IP, 801,
            "/eportal/?c=ACSetting&a=Logout&ver=1.0&url=drappall",
            secure=False,
        )
        if response.status != 200:
            raise PortalError(f"logout endpoint returned HTTP {response.status}")
        # The configured AC endpoint and chkstatus can both report stale values,
        # so the bound interface's domestic connectivity transition is authoritative.
        for delay in (0.5, 1.0, 2.0, 4.0):
            time.sleep(delay)
            if self.authentication_status(attempts=1).state == "portal_detected":
                return "logout_success"
        raise PortalError("logout request completed, but the interface remains online")
