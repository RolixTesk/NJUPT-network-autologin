"""Windows desktop adapter backed by the current user's startup registry."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ..credentials import default_path, load_credentials
from ..errors import NetworkError
from ..network_interfaces import default_interfaces, valid_interface_name
from .base import ServiceError, ServiceStatus

try:
    import winreg
except ImportError:  # The module is absent while cross-platform tests run on Linux.
    winreg = None  # type: ignore[assignment]


STARTUP_NAME = "NJUPT Auto Login"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LEGACY_TASK_NAME = "NJUPT Auto Login"


def _run(command: list[str], *, check: bool = True, timeout: int = 20) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(f"cannot run {command[0]}") from exc
    if check and result.returncode:
        raise ServiceError(f"{Path(command[0]).name} failed ({result.returncode})")
    return result


def _pause_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home() / "AppData" / "Local"
    return base / "njupt-autologin" / "paused-this-boot"


def _startup_command(interface: str, credential: Path) -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("njupt-autologin-task.exe")
        if not executable.is_file():
            raise ServiceError("njupt-autologin-task.exe is missing beside the application")
        command = [str(executable)]
    else:
        python = Path(sys.executable)
        windowless = python.with_name("pythonw.exe")
        command = [str(windowless if windowless.is_file() else python), "-m", "njupt_autologin"]
    command.extend([
        "--interface", interface, "login", "--scheduled",
        "--startup-delay", "30", "--credentials-file", str(credential),
    ])
    return subprocess.list2cmdline(command)


def _read_startup_command() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, STARTUP_NAME)
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def _write_startup_command(command: str) -> None:
    if winreg is None:
        raise ServiceError("Windows startup registry is unavailable")
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, command)
    except OSError as exc:
        raise ServiceError("cannot update the current user's startup applications") from exc


def _delete_startup_command() -> None:
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, STARTUP_NAME)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ServiceError("cannot remove the current user's startup application") from exc


def _legacy_task_exists() -> bool:
    return _run(["schtasks.exe", "/Query", "/TN", LEGACY_TASK_NAME], check=False).returncode == 0


def _remove_legacy_task() -> None:
    if _legacy_task_exists():
        _run(["schtasks.exe", "/Delete", "/TN", LEGACY_TASK_NAME, "/F"])


class WindowsServiceAdapter:
    platform = "windows"

    def available_interfaces(self) -> tuple[str, ...]:
        try:
            return tuple(default_interfaces())
        except NetworkError:
            return ()

    def _startup_enabled(self) -> tuple[bool, bool]:
        if _read_startup_command() is not None:
            return True, True
        legacy = _legacy_task_exists()
        return legacy, legacy

    def status(self) -> ServiceStatus:
        installed, enabled = self._startup_enabled()
        return ServiceStatus(installed, enabled, False, enabled)

    def install(self, interface: str, credential_path: Path | None = None) -> None:
        if interface != "auto" and not valid_interface_name(interface):
            raise ServiceError("invalid interface name")
        credential = (credential_path or default_path()).expanduser().resolve()
        load_credentials(path=credential)
        _remove_legacy_task()
        _write_startup_command(_startup_command(interface, credential))
        self.resume()

    def uninstall(self, *, remove_credentials: bool = False) -> None:
        _delete_startup_command()
        _remove_legacy_task()
        try:
            _pause_path().unlink()
        except FileNotFoundError:
            pass
        if remove_credentials:
            try:
                default_path().unlink()
            except FileNotFoundError:
                pass

    def pause(self) -> bool:
        installed, enabled = self._startup_enabled()
        if not (installed and enabled):
            return False
        marker = _pause_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        # monotonic time resets on reboot, making one marker sufficient for the
        # current boot without persisting a machine identifier or wall clock.
        marker.write_text(f"{time.monotonic():.6f}\n", encoding="ascii")
        return True

    def resume(self) -> None:
        try:
            _pause_path().unlink()
        except FileNotFoundError:
            pass

    def scheduled_login_allowed(self) -> bool:
        marker = _pause_path()
        try:
            recorded = float(marker.read_text(encoding="ascii").strip())
        except FileNotFoundError:
            return True
        except (OSError, ValueError):
            try:
                marker.unlink()
            except OSError:
                pass
            return True
        if time.monotonic() >= recorded:
            return False
        # Windows uptime reset, so this marker belongs to an earlier boot.
        try:
            marker.unlink()
        except OSError:
            pass
        return True
