"""Load three user supplied login fields without embedding credentials in code."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class CredentialError(ValueError):
    pass


OPERATOR_SUFFIX = {
    "校园用户": "",
    "校园网": "",
    "campus": "",
    "中国电信": "@njxy",
    "电信": "@njxy",
    "telecom": "@njxy",
    "@njxy": "@njxy",
    "中国移动": "@cmcc",
    "移动": "@cmcc",
    "mobile": "@cmcc",
    "@cmcc": "@cmcc",
}


@dataclass(frozen=True, repr=False)
class Credentials:
    username: str
    password: str
    operator: str

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise CredentialError("username and password are required")
        if self.operator.strip().lower() not in OPERATOR_SUFFIX:
            raise CredentialError("unsupported operator; use campus, telecom, or mobile")

    @property
    def account(self) -> str:
        suffix = OPERATOR_SUFFIX[self.operator.strip().lower()]
        if "@" in self.username:
            if suffix and not self.username.endswith(suffix):
                raise CredentialError("username suffix and operator disagree")
            return self.username
        return self.username + suffix

    @classmethod
    def from_mapping(cls, value: dict[str, str]) -> "Credentials":
        return cls(
            username=str(value.get("username", "")).strip(),
            password=str(value.get("password", "")),
            operator=str(value.get("operator", value.get("运营商", ""))).strip(),
        )

    @classmethod
    def from_text(cls, raw: str) -> "Credentials":
        if raw.lstrip().startswith("{"):
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CredentialError("credential JSON must be an object")
            return cls.from_mapping(value)
        values: dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if line.lower().startswith("vm ubuntu"):
                break
            if ":" not in line and "：" not in line:
                continue
            key, value = line.replace("：", ":", 1).split(":", 1)
            key = key.strip().strip('"').lower()
            if key in ("username", "password", "operator", "运营商"):
                values[key] = value.strip().strip('"')
        return cls.from_mapping(values)


def default_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "njupt-autologin" / "credentials.json"
    return Path.home() / ".config" / "njupt-autologin" / "credentials.json"


def load_credentials(*, path: Path | None = None, stdin: bool = False) -> Credentials:
    if stdin:
        return Credentials.from_text(sys.stdin.read())
    if path is not None:
        return _read_file(path)
    env = {key: os.environ.get("NJUPT_" + key.upper()) for key in ("username", "password", "operator")}
    if all(env.values()):
        return Credentials.from_mapping(env)  # type: ignore[arg-type]
    return _read_file(default_path())


def _read_file(path: Path) -> Credentials:
    try:
        mode = path.stat().st_mode
        if sys.platform != "win32" and mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise CredentialError("credential file must be private (chmod 600)")
        if not stat.S_ISREG(mode):
            raise CredentialError("credential path must be a regular file")
        return Credentials.from_text(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CredentialError(f"credential file not found: {path}") from exc


def save_credentials(credentials: Credentials, path: Path | None = None) -> Path:
    target = path or default_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(target.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"username": credentials.username, "password": credentials.password, "operator": credentials.operator}, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if sys.platform != "win32":
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        if sys.platform == "win32":
            _secure_windows_file(target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def _secure_windows_file(path: Path) -> None:
    """Restrict a saved credential file to the current Windows identity."""
    try:
        identity = subprocess.run(
            ["whoami.exe"], check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if not identity:
            raise OSError("empty Windows identity")
        subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
            check=True, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            path.unlink()
        except OSError:
            pass
        raise CredentialError("cannot protect the Windows credential file") from exc
