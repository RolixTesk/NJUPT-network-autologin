"""Command line interface with explicit status and failure exit codes."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .client import AuthenticationError, CampusClient, NetworkError, PortalError
from .credentials import CredentialError, Credentials, load_credentials, save_credentials
from .service import ServiceError, install_service, uninstall_service


EXIT_PORTAL = 2
EXIT_NETWORK = 3
EXIT_AUTH = 4
EXIT_CONFIG = 5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="njupt-autologin")
    parser.add_argument("--interface", default="auto", help="campus interface or auto (default: auto)")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds per network request")
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="check campus internet/portal state")
    login = commands.add_parser("login", help="authenticate only if a portal is present")
    sources = login.add_mutually_exclusive_group()
    sources.add_argument("--credentials-file", type=Path, help="private JSON or key-style credential file")
    sources.add_argument("--credentials-stdin", action="store_true", help="read JSON or key-style credentials from stdin")
    configure = commands.add_parser("configure", help="write a private local credential file")
    inputs = configure.add_mutually_exclusive_group()
    inputs.add_argument("--from-file", type=Path, help="import a private credential file")
    inputs.add_argument("--credentials-stdin", action="store_true", help="read credentials from stdin")
    configure.add_argument("--output", type=Path, help="destination credential file")
    service = commands.add_parser("install-service", help="install and enable the user systemd timer")
    service.add_argument("--credentials-file", type=Path, help="private credential file to use")
    remove = commands.add_parser("uninstall-service", help="disable and remove the user systemd timer")
    remove.add_argument("--remove-credentials", action="store_true", help="also delete saved credentials")
    return parser


def _emit(as_json: bool, state: str, **extra: object) -> None:
    if as_json:
        print(json.dumps({"state": state, **extra}, ensure_ascii=False))
    else:
        labels = {
            "internet_ok": "Internet OK",
            "already_online": "Internet OK (already online)",
            "portal_detected": "Portal detected",
            "network_unavailable": "Network unavailable",
            "unexpected_response": "Unexpected HTTP response",
            "login_success": "Login successful; Internet OK",
            "configured": "Credentials saved",
            "service_installed": "User service and timer installed",
            "service_uninstalled": "User service and timer removed",
        }
        message = labels.get(state, state)
        if extra.get("interface"):
            message += f" (interface: {extra['interface']})"
        print(message)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "configure":
            if args.credentials_stdin:
                credentials = load_credentials(stdin=True)
            elif args.from_file:
                credentials = load_credentials(path=args.from_file)
            else:
                credentials = Credentials(
                    username=input("Campus username: ").strip(),
                    password=getpass.getpass("Campus password: "),
                    operator=input("Operator (campus/telecom/mobile): ").strip(),
                )
            saved = save_credentials(credentials, args.output)
            _emit(args.json, "configured", path=str(saved))
            return 0
        if args.command == "install-service":
            service, timer = install_service(args.interface, args.credentials_file)
            _emit(args.json, "service_installed", service=str(service), timer=str(timer))
            return 0
        if args.command == "uninstall-service":
            uninstall_service(remove_credentials=args.remove_credentials)
            _emit(args.json, "service_uninstalled")
            return 0
        client = CampusClient(interface=args.interface, timeout=args.timeout)
        if args.command == "status":
            status = client.probe()
            _emit(
                args.json, status.state, interface=client.interface,
                http_status=status.http_status, portal_host=status.portal_host,
            )
            return {
                "internet_ok": 0,
                "portal_detected": EXIT_PORTAL,
                "network_unavailable": EXIT_NETWORK,
                "unexpected_response": EXIT_NETWORK,
            }[status.state]
        # Check first so an already connected client needs no credential access.
        current = client.probe()
        if current.state == "internet_ok":
            _emit(args.json, "already_online", interface=client.interface)
            return 0
        if current.state != "portal_detected":
            _emit(args.json, current.state, interface=client.interface)
            return EXIT_NETWORK
        credentials = load_credentials(path=args.credentials_file, stdin=args.credentials_stdin)
        result = client.login(credentials)
        _emit(args.json, result, interface=client.interface)
        return 0
    except (CredentialError, ServiceError, ValueError, json.JSONDecodeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except NetworkError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return EXIT_NETWORK
    except (PortalError, AuthenticationError) as exc:
        print(f"Authentication error: {exc}", file=sys.stderr)
        return EXIT_AUTH


if __name__ == "__main__":
    raise SystemExit(main())
