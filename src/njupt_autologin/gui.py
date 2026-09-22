"""Dependency-free local web control panel for credentials and service management."""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import urlsplit

from .client import AuthenticationError, CampusClient, NetworkError, PortalError
from .credentials import CredentialError, Credentials, default_path, load_credentials, save_credentials
from .service import (
    ServiceError,
    enable_linger,
    install_service,
    pause_service,
    resume_service,
    service_status,
    uninstall_service,
)


LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
MAX_BODY = 16_384
EXPECTED_ERRORS = (
    AuthenticationError,
    CredentialError,
    NetworkError,
    PortalError,
    ServiceError,
    OSError,
    ValueError,
    json.JSONDecodeError,
)
OPERATOR_KEYS = {
    "campus": "campus",
    "校园网": "campus",
    "校园用户": "campus",
    "telecom": "telecom",
    "中国电信": "telecom",
    "电信": "telecom",
    "@njxy": "telecom",
    "mobile": "mobile",
    "中国移动": "mobile",
    "移动": "mobile",
    "@cmcc": "mobile",
}


def _operator_key(value: str) -> str:
    return OPERATOR_KEYS.get(value.strip().lower(), "mobile")


class ControlPanel:
    """Platform-neutral actions exposed to the local browser UI."""

    @staticmethod
    def _credentials(payload: dict[str, Any]) -> Credentials:
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        operator = str(payload.get("operator", "")).strip()
        if not password:
            password = load_credentials(path=default_path()).password
        return Credentials(username=username, password=password, operator=operator)

    @staticmethod
    def state() -> dict[str, Any]:
        credential_state: dict[str, Any] = {"exists": False, "username": "", "operator": "mobile"}
        try:
            credentials = load_credentials(path=default_path())
        except (CredentialError, json.JSONDecodeError, OSError):
            pass
        else:
            credential_state = {
                "exists": True,
                "username": credentials.username,
                "operator": _operator_key(credentials.operator),
            }

        service: dict[str, Any] = {
            "supported": sys.platform == "linux",
            "installed": False,
            "enabled": False,
            "active": False,
            "linger": False,
        }
        if service["supported"]:
            try:
                value = service_status()
            except ServiceError as exc:
                service["error"] = str(exc)
            else:
                service.update(
                    installed=value.installed,
                    enabled=value.enabled,
                    active=value.active,
                    linger=value.linger,
                )
        return {
            "credentials": credential_state,
            "service": service,
            "platform": sys.platform,
        }

    def run(self, action: str, payload: dict[str, Any]) -> str:
        if action == "save":
            save_credentials(self._credentials(payload))
            return "登录信息已保存。"
        if action == "install":
            credentials = self._credentials(payload)
            interface = str(payload.get("interface", "auto")).strip()
            save_credentials(credentials)
            enable_linger()
            install_service(interface)
            return "开机自启服务已安装并启用。"
        if action == "uninstall":
            uninstall_service(remove_credentials=payload.get("remove_credentials") is True)
            return "开机自启服务已卸载。"
        if action == "logout":
            interface = str(payload.get("interface", "auto")).strip()
            timer_was_active = pause_service()
            try:
                CampusClient(interface=interface).logout()
            except Exception:
                if timer_was_active:
                    resume_service()
                raise
            return "校园网会话已注销；正在运行的自动登录定时器已暂停。"
        raise ValueError("unknown control panel action")


class ControlPanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], panel: ControlPanel | None = None) -> None:
        self.panel = panel or ControlPanel()
        self.csrf_token = secrets.token_urlsafe(32)
        self.csp_nonce = secrets.token_urlsafe(18)
        template = resources.files("njupt_autologin").joinpath("webui.html").read_text(encoding="utf-8")
        self.index = (
            template.replace("__CSRF_TOKEN__", json.dumps(self.csrf_token))
            .replace("__CSP_NONCE__", self.csp_nonce)
            .encode("utf-8")
        )
        super().__init__(address, ControlPanelHandler)


class ControlPanelHandler(BaseHTTPRequestHandler):
    server: ControlPanelServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        parsed = urlsplit("//" + host)
        return parsed.hostname in LOOPBACK_HOSTS

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or urlsplit(origin).hostname in LOOPBACK_HOSTS

    def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", (
            "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            f"style-src 'nonce-{self.server.csp_nonce}'; script-src 'nonce-{self.server.csp_nonce}'; "
            "connect-src 'self'"
        ))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def _bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._bytes(status, body, "application/json; charset=utf-8")

    def _reject_bad_host(self) -> bool:
        if self._host_allowed():
            return False
        self._json(HTTPStatus.MISDIRECTED_REQUEST, {"ok": False, "error": "invalid host"})
        return True

    def do_GET(self) -> None:
        if self._reject_bad_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._bytes(HTTPStatus.OK, self.server.index, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._json(HTTPStatus.OK, {"ok": True, "state": self.server.panel.state()})
            return
        if path == "/favicon.ico":
            self._bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def _read_payload(self) -> dict[str, Any]:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("request must use application/json")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("request length is required")
        length = int(raw_length)
        if not 0 <= length <= MAX_BODY:
            raise ValueError("request is too large")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def do_POST(self) -> None:
        if self._reject_bad_host():
            return
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid origin"})
            return
        supplied = self.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(supplied, self.server.csrf_token):
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid request token"})
            return
        path = urlsplit(self.path).path
        if path == "/api/shutdown":
            self._json(HTTPStatus.OK, {"ok": True, "message": "控制面板已关闭。"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if not path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
            payload = self._read_payload()
            message = self.server.panel.run(path.removeprefix("/api/"), payload)
            state = self.server.panel.state()
        except EXPECTED_ERRORS as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal error"})
            return
        self._json(HTTPStatus.OK, {"ok": True, "message": message, "state": state})


def create_server(port: int = 0, panel: ControlPanel | None = None) -> ControlPanelServer:
    if not 0 <= port <= 65_535:
        raise ValueError("port must be between 0 and 65535")
    return ControlPanelServer(("127.0.0.1", port), panel)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="njupt-autologin-gui")
    parser.add_argument("--port", type=int, default=0, help="loopback port; 0 chooses a free port")
    parser.add_argument("--no-browser", action="store_true", help="print the URL without opening a browser")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        server = create_server(args.port)
    except (OSError, ValueError) as exc:
        print(f"Cannot start control panel: {exc}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"NJUPT control panel: {url}", flush=True)
    if not args.no_browser:
        opener = threading.Timer(0.15, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
