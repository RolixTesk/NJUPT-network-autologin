"""Linux desktop adapter backed by iproute2 and systemd user services."""

from __future__ import annotations

from pathlib import Path

from ..errors import NetworkError
from ..network_interfaces import default_interfaces
from ..service import (
    enable_linger,
    install_service,
    pause_service,
    resume_service,
    service_status,
    uninstall_service,
)
from .base import ServiceStatus


class LinuxServiceAdapter:
    platform = "linux"

    def available_interfaces(self) -> tuple[str, ...]:
        try:
            return tuple(default_interfaces())
        except NetworkError:
            return ()

    def status(self) -> ServiceStatus:
        return service_status()

    def install(self, interface: str, credential_path: Path | None = None) -> None:
        enable_linger()
        install_service(interface, credential_path)

    def uninstall(self, *, remove_credentials: bool = False) -> None:
        uninstall_service(remove_credentials=remove_credentials)

    def pause(self) -> bool:
        return pause_service()

    def resume(self) -> None:
        resume_service()

    def scheduled_login_allowed(self) -> bool:
        return True
