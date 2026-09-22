"""Linux desktop adapter backed by iproute2 and systemd user services."""

from __future__ import annotations

from ..client import CampusClient, NetworkError
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
            return tuple(CampusClient._default_interfaces())
        except NetworkError:
            return ()

    def status(self) -> ServiceStatus:
        return service_status()

    def install(self, interface: str) -> None:
        enable_linger()
        install_service(interface)

    def uninstall(self, *, remove_credentials: bool = False) -> None:
        uninstall_service(remove_credentials=remove_credentials)

    def pause(self) -> bool:
        return pause_service()

    def resume(self) -> None:
        resume_service()
