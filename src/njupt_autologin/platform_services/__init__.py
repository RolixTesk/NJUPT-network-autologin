"""Select the desktop service adapter for the current operating system."""

from __future__ import annotations

import sys

from .base import DesktopServiceAdapter, ServiceError, ServiceStatus


def load_service_adapter() -> DesktopServiceAdapter:
    if sys.platform.startswith("linux"):
        from .linux import LinuxServiceAdapter

        return LinuxServiceAdapter()
    raise ServiceError(f"desktop service control is not available on {sys.platform}")


__all__ = ["DesktopServiceAdapter", "ServiceError", "ServiceStatus", "load_service_adapter"]
