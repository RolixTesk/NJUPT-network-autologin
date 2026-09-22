"""Platform neutral contracts used by the native GUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceStatus:
    installed: bool
    enabled: bool
    active: bool
    linger: bool


class DesktopServiceAdapter(Protocol):
    """Operations the GUI needs from an operating-system backend."""

    platform: str

    def available_interfaces(self) -> tuple[str, ...]: ...

    def status(self) -> ServiceStatus: ...

    def install(self, interface: str) -> None: ...

    def uninstall(self, *, remove_credentials: bool = False) -> None: ...

    def pause(self) -> bool: ...

    def resume(self) -> None: ...
