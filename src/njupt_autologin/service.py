"""Install a user timer that periodically checks and logs in when needed."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .credentials import default_path, load_credentials
from .platform_services.base import ServiceError, ServiceStatus

try:
    import pwd
except ImportError:  # Windows has no pwd module; the GUI can still load there.
    pwd = None  # type: ignore[assignment]


SERVICE_NAME = "njupt-autologin.service"
TIMER_NAME = "njupt-autologin.timer"


def _run(command: list[str], *, check: bool = True, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(f"cannot run {command[0]}") from exc
    if check and result.returncode:
        raise ServiceError(f"{command[0]} failed ({result.returncode})")
    return result


def _unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _linger_enabled() -> bool:
    if sys.platform != "linux" or pwd is None:
        return False
    username = pwd.getpwuid(os.getuid()).pw_name
    result = _run(["loginctl", "show-user", username, "-p", "Linger", "--value"], check=False)
    return result.returncode == 0 and result.stdout.strip().lower() == "yes"


def enable_linger() -> None:
    """Enable the user manager at boot, using the desktop privilege prompt if needed."""
    if sys.platform != "linux" or pwd is None:
        raise ServiceError("systemd startup is supported only on Linux")
    if _linger_enabled():
        return
    username = pwd.getpwuid(os.getuid()).pw_name
    helper = shutil.which("pkexec")
    if not helper:
        raise ServiceError("pkexec is required to enable startup before login")
    _run([helper, "loginctl", "enable-linger", username], timeout=120)
    if not _linger_enabled():
        raise ServiceError("loginctl did not enable startup before login")


def service_status() -> ServiceStatus:
    if sys.platform != "linux":
        return ServiceStatus(False, False, False, False)
    unit_dir = _unit_dir()
    enabled = _run(["systemctl", "--user", "is-enabled", TIMER_NAME], check=False).returncode == 0
    active = _run(["systemctl", "--user", "is-active", TIMER_NAME], check=False).returncode == 0
    local_units = (unit_dir / SERVICE_NAME).is_file() and (unit_dir / TIMER_NAME).is_file()
    installed = local_units or enabled or active
    return ServiceStatus(installed, enabled, active, _linger_enabled())


def pause_service() -> bool:
    """Stop the active timer and return whether it must be restored after a failure."""
    if sys.platform != "linux":
        raise ServiceError("systemd service control is supported only on Linux")
    active = _run(["systemctl", "--user", "is-active", TIMER_NAME], check=False).returncode == 0
    if active:
        _run(["systemctl", "--user", "stop", TIMER_NAME])
    return active


def resume_service() -> None:
    if sys.platform != "linux":
        raise ServiceError("systemd service control is supported only on Linux")
    _run(["systemctl", "--user", "start", TIMER_NAME])


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def install_service(interface: str = "auto", credential_path: Path | None = None) -> tuple[Path, Path]:
    if sys.platform != "linux":
        raise ServiceError("systemd installation is supported only on Linux")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface):
        raise ServiceError("invalid interface name")
    credential = (credential_path or default_path()).expanduser().resolve()
    load_credentials(path=credential)  # Verify the secret file and its permissions.
    home = Path.home()
    app_root = home / ".local" / "share" / "njupt-autologin" / "app"
    package_source = Path(__file__).resolve().parent
    package_target = app_root / "njupt_autologin"
    app_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        package_source, package_target, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    unit_dir = _unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = unit_dir / SERVICE_NAME
    timer = unit_dir / TIMER_NAME
    service.write_text(
        "[Unit]\n"
        "Description=NJUPT wired network login\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "TimeoutStartSec=55\n"
        f"Environment={_quote('PYTHONPATH=' + str(app_root))}\n"
        f"ExecStart={_quote(sys.executable)} -m njupt_autologin --interface {_quote(interface)} login --credentials-file {_quote(str(credential))}\n",
        encoding="utf-8",
    )
    timer.write_text(
        "[Unit]\n"
        "Description=Check NJUPT wired network login periodically\n\n"
        "[Timer]\n"
        "OnStartupSec=30s\n"
        "OnUnitActiveSec=2min\n"
        "Persistent=true\n"
        "Unit=njupt-autologin.service\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    for command in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", timer.name],
    ):
        _run(command)
    return service, timer


def uninstall_service(*, remove_credentials: bool = False) -> None:
    if sys.platform != "linux":
        raise ServiceError("systemd installation is supported only on Linux")
    unit_dir = _unit_dir()
    units_present = any((unit_dir / name).is_file() for name in (SERVICE_NAME, TIMER_NAME))
    _run(["systemctl", "--user", "disable", "--now", TIMER_NAME], check=units_present)
    for unit in (unit_dir / SERVICE_NAME, unit_dir / TIMER_NAME):
        try:
            unit.unlink()
        except FileNotFoundError:
            pass
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "reset-failed", SERVICE_NAME], check=False)
    app_root = Path.home() / ".local" / "share" / "njupt-autologin"
    if app_root.is_dir():
        shutil.rmtree(app_root)
    if remove_credentials:
        try:
            default_path().unlink()
        except FileNotFoundError:
            pass
