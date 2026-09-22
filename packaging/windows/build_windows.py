#!/usr/bin/env python3
"""Build self-contained Windows executables and an optional Inno Setup installer."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "njupt-autologin"


def _version() -> str:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([0-9]+(?:\.[0-9]+)+)"', project, re.MULTILINE)
    if match is None:
        raise RuntimeError("cannot read project version")
    return match.group(1)


def _copy_windows_package(destination: Path) -> None:
    source = ROOT / "src" / "njupt_autologin"
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "service.py"),
    )
    adapters = destination / "platform_services"
    included = {"__init__.py", "base.py", "windows.py"}
    for path in adapters.glob("*.py"):
        if path.name not in included:
            path.unlink()
    forbidden = (destination / "service.py", adapters / "linux.py")
    if any(path.exists() for path in forbidden):
        raise RuntimeError("Windows staging contains a Linux service module")


def _pyinstaller(
    entry: Path, name: str, staging: Path, work: Path, output: Path, *, windowed: bool,
) -> None:
    icon = staging / "njupt_autologin" / "app-icon.ico"
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--name", name, "--icon", str(icon),
        "--paths", str(staging),
        "--add-data", f"{staging / 'njupt_autologin' / 'app-icon.png'}{os.pathsep}njupt_autologin",
        "--add-data", f"{icon}{os.pathsep}njupt_autologin",
        "--distpath", str(output), "--workpath", str(work / name),
        "--specpath", str(work / "spec"),
    ]
    command.append("--windowed" if windowed else "--console")
    command.append(str(entry))
    subprocess.run(command, check=True)


def _find_iscc() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _build_installer(bin_dir: Path, output_dir: Path, version: str, work: Path) -> Path | None:
    iscc = _find_iscc()
    if iscc is None:
        return None
    script = work / "installer.iss"
    source = str(bin_dir).replace('"', '""')
    output = str(output_dir).replace('"', '""')
    script.write_text(
        f"""[Setup]
AppId=A43C6791-F359-4CD8-9C82-224C69D4B9B4
AppName=NJUPT Auto Login
AppVersion={version}
AppPublisher=RolixTesk
DefaultDirName={{localappdata}}\\Programs\\NJUPT Auto Login
DefaultGroupName=NJUPT Auto Login
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={output}
OutputBaseFilename=njupt-autologin-windows-{version}-x64-setup
SetupIconFile={source}\\app-icon.ico
UninstallDisplayIcon={{app}}\\njupt-autologin-gui.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{source}\\njupt-autologin.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{source}\\njupt-autologin-gui.exe"; DestDir: "{{app}}"; Flags: ignoreversion

[Icons]
Name: "{{group}}\\NJUPT 校园网自动登录"; Filename: "{{app}}\\njupt-autologin-gui.exe"
Name: "{{autodesktop}}\\NJUPT 校园网自动登录"; Filename: "{{app}}\\njupt-autologin-gui.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Run]
Filename: "{{app}}\\njupt-autologin-gui.exe"; Description: "启动 NJUPT 校园网自动登录"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{{app}}\\njupt-autologin.exe"; Parameters: "uninstall-service"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveNJUPTTask"
""",
        encoding="utf-8-sig",
    )
    subprocess.run([str(iscc), str(script)], check=True)
    return output_dir / f"njupt-autologin-windows-{version}-x64-setup.exe"


def build(output_dir: Path) -> tuple[Path, Path | None]:
    if sys.platform != "win32":
        raise RuntimeError("Windows packages must be built on Windows")
    version = _version()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="njupt-win-build-") as temporary:
        work = Path(temporary)
        staging = work / "src"
        package = staging / "njupt_autologin"
        _copy_windows_package(package)
        cli_entry = work / "cli_entry.py"
        gui_entry = work / "gui_entry.pyw"
        cli_entry.write_text(
            "from njupt_autologin.cli import main\nraise SystemExit(main())\n", encoding="utf-8",
        )
        gui_entry.write_text(
            "from njupt_autologin.gui import main\nraise SystemExit(main())\n", encoding="utf-8",
        )
        binaries = work / "bin"
        binaries.mkdir()
        _pyinstaller(cli_entry, "njupt-autologin", staging, work, binaries, windowed=False)
        _pyinstaller(gui_entry, "njupt-autologin-gui", staging, work, binaries, windowed=True)
        shutil.copy2(package / "app-icon.ico", binaries / "app-icon.ico")
        (binaries / "README.txt").write_text(
            "NJUPT 校园网自动登录\n\n"
            "运行 njupt-autologin-gui.exe 打开控制面板。程序仅使用 Windows 内置组件，"
            "不需要另行安装 Python。\n",
            encoding="utf-8-sig",
        )
        archive = output_dir / f"{PACKAGE}-windows-{version}-x64-portable.zip"
        archive.unlink(missing_ok=True)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(binaries.iterdir()):
                bundle.write(path, f"{PACKAGE}-{version}/{path.name}")
        installer = _build_installer(binaries, output_dir, version, work)
    return archive, installer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    archive, installer = build(args.output_dir.resolve())
    print(archive)
    if installer is not None:
        print(installer)
    else:
        print("Inno Setup not found; portable package created", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
