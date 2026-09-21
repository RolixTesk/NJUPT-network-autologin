"""Install a user timer that periodically checks and logs in when needed."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .credentials import default_path, load_credentials


class ServiceError(RuntimeError):
    pass


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def install_service(interface: str, credential_path: Path | None = None) -> tuple[Path, Path]:
    if sys.platform != "linux":
        raise ServiceError("systemd installation is supported only on Linux")
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
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = unit_dir / "njupt-autologin.service"
    timer = unit_dir / "njupt-autologin.timer"
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
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ServiceError(f"systemctl --user failed ({result.returncode})")
    return service, timer
