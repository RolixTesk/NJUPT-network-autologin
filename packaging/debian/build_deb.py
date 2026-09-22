#!/usr/bin/env python3
"""Build an architecture-independent Debian package with only the standard library."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "njupt-autologin"


def _write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _copy_package(destination: Path) -> None:
    source = ROOT / "src" / "njupt_autologin"
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for path in destination.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    destination.chmod(0o755)


def build(output_dir: Path) -> Path:
    if not shutil.which("dpkg-deb"):
        raise RuntimeError("dpkg-deb is required to build the Debian package")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(r'^version\s*=\s*"([0-9]+(?:\.[0-9]+)+)"', project, re.MULTILINE)
    if version_match is None:
        raise RuntimeError("cannot read project version")
    version = version_match.group(1)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{PACKAGE}_{version}_all.deb"
    output.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="njupt-deb-") as temporary:
        tree = Path(temporary) / f"{PACKAGE}_{version}_all"
        module_dir = tree / "usr" / "lib" / "python3" / "dist-packages" / "njupt_autologin"
        _copy_package(module_dir)

        _write(
            tree / "usr" / "bin" / "njupt-autologin",
            "#!/usr/bin/python3 -s\nfrom njupt_autologin.cli import main\nraise SystemExit(main())\n",
            0o755,
        )
        _write(
            tree / "usr" / "bin" / "njupt-autologin-gui",
            "#!/usr/bin/python3 -s\nfrom njupt_autologin.gui import main\nraise SystemExit(main())\n",
            0o755,
        )
        for name in ("njupt-autologin.service", "njupt-autologin.timer"):
            target = tree / "usr" / "lib" / "systemd" / "user" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "packaging" / "debian" / name, target)
            target.chmod(0o644)
        icon = tree / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "njupt-autologin.svg"
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src" / "njupt_autologin" / "app-icon.svg", icon)
        icon.chmod(0o644)

        _write(
            tree / "usr" / "share" / "applications" / "njupt-autologin.desktop",
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=NJUPT Auto Login\n"
            "Name[zh_CN]=NJUPT 校园网自动登录\n"
            "Comment=Configure campus login and startup service\n"
            "Exec=/usr/bin/njupt-autologin-gui\n"
            "Icon=njupt-autologin\n"
            "Terminal=false\n"
            "Categories=Network;\n",
        )
        _write(
            tree / "usr" / "share" / "doc" / PACKAGE / "copyright",
            "NJUPT Auto Login\n\n"
            "This package contains the project files from the source repository.\n",
        )
        installed_size = sum(
            path.stat().st_size for path in tree.rglob("*") if path.is_file()
        ) // 1024 + 1
        _write(
            tree / "DEBIAN" / "control",
            f"Package: {PACKAGE}\n"
            f"Version: {version}\n"
            "Section: net\n"
            "Priority: optional\n"
            "Architecture: all\n"
            "Maintainer: RolixTesk\n"
            "Depends: python3 (>= 3.10), iproute2, systemd, pkexec\n"
            "Recommends: xdg-utils\n"
            f"Installed-Size: {installed_size}\n"
            "Description: NJUPT wired network automatic login\n"
            " A dependency-free Python client, local web control panel, and user\n"
            " systemd timer for the NJUPT wired network portal.\n",
        )
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = env.get("SOURCE_DATE_EPOCH", "0")
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(output)],
            check=True,
            env=env,
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(build(args.output_dir).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
