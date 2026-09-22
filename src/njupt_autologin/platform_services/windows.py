"""Windows desktop adapter backed by the current user's Task Scheduler."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..client import CampusClient, NetworkError
from ..credentials import default_path, load_credentials
from .base import ServiceError, ServiceStatus


TASK_NAME = "NJUPT Auto Login"


def _run(command: list[str], *, check: bool = True, timeout: int = 20) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(f"cannot run {command[0]}") from exc
    if check and result.returncode:
        raise ServiceError(f"{Path(command[0]).name} failed ({result.returncode})")
    return result


def _powershell_json(script: str) -> object:
    prefix = (
        "$ProgressPreference='SilentlyContinue';"
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
    )
    encoded = base64.b64encode((prefix + script).encode("utf-16le")).decode("ascii")
    result = _run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    )
    try:
        return json.loads(result.stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceError("PowerShell returned invalid task information") from exc


def _pause_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home() / "AppData" / "Local"
    return base / "njupt-autologin" / "paused-this-boot"


def _task_command(interface: str, credential: Path) -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("njupt-autologin.exe")
        if not executable.is_file():
            raise ServiceError("njupt-autologin.exe is missing beside the GUI")
        command = [str(executable)]
    else:
        command = [sys.executable, "-m", "njupt_autologin"]
    command.extend([
        "--interface", interface, "login", "--scheduled",
        "--credentials-file", str(credential),
    ])
    return subprocess.list2cmdline(command)


class WindowsServiceAdapter:
    platform = "windows"

    def available_interfaces(self) -> tuple[str, ...]:
        try:
            return tuple(CampusClient._default_interfaces())
        except NetworkError:
            return ()

    def _task_enabled(self) -> tuple[bool, bool]:
        script = f"""
$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($null -eq $task) {{ ConvertTo-Json -Compress @{{installed=$false;enabled=$false}} }}
else {{ ConvertTo-Json -Compress @{{installed=$true;enabled=($task.State -ne 'Disabled')}} }}
"""
        try:
            value = _powershell_json(script)
        except ServiceError:
            query = _run(["schtasks.exe", "/Query", "/TN", TASK_NAME], check=False)
            return query.returncode == 0, query.returncode == 0
        if not isinstance(value, dict):
            raise ServiceError("Task Scheduler returned invalid state")
        return bool(value.get("installed")), bool(value.get("enabled"))

    def status(self) -> ServiceStatus:
        installed, enabled = self._task_enabled()
        allowed = self.scheduled_login_allowed()
        return ServiceStatus(installed, enabled, enabled and allowed, enabled)

    def install(self, interface: str, credential_path: Path | None = None) -> None:
        if interface != "auto" and not CampusClient._valid_interface_name(interface):
            raise ServiceError("invalid interface name")
        credential = (credential_path or default_path()).expanduser().resolve()
        load_credentials(path=credential)
        _run([
            "schtasks.exe", "/Create", "/SC", "MINUTE", "/MO", "2",
            "/TN", TASK_NAME, "/TR", _task_command(interface, credential), "/F",
        ])
        self.resume()

    def uninstall(self, *, remove_credentials: bool = False) -> None:
        installed, _enabled = self._task_enabled()
        if installed:
            _run(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
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
        installed, enabled = self._task_enabled()
        if not (installed and enabled):
            return False
        marker = _pause_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
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
