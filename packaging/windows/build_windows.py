#!/usr/bin/env python3
"""Build self-contained Windows executables and an optional Inno Setup installer."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "njupt-autologin"


def _architecture(machine: str | None = None) -> str:
    normalized = (machine or platform.machine()).strip().lower()
    if normalized in {"amd64", "x86_64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    raise RuntimeError(f"unsupported Windows architecture: {normalized or 'unknown'}")


def _installer_architecture(architecture: str) -> str:
    if architecture == "x64":
        return "x64compatible and not arm64"
    if architecture == "arm64":
        return "arm64"
    raise RuntimeError(f"unsupported installer architecture: {architecture}")


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


def _build_installer(
    bin_dir: Path, output_dir: Path, version: str, architecture: str, work: Path,
) -> Path | None:
    iscc = _find_iscc()
    if iscc is None:
        return None
    script = work / "installer.iss"
    source = str(bin_dir).replace('"', '""')
    output = str(output_dir).replace('"', '""')
    installer_architecture = _installer_architecture(architecture)
    script.write_text(
        f"""[Setup]
AppId=A43C6791-F359-4CD8-9C82-224C69D4B9B4
AppName=NJUPT Auto Login
AppVersion={version}
AppPublisher=RolixTesk
DefaultDirName={{localappdata}}\\Programs\\NJUPT Auto Login
DefaultGroupName=NJUPT Auto Login
PrivilegesRequired=lowest
ArchitecturesAllowed={installer_architecture}
ArchitecturesInstallIn64BitMode={installer_architecture}
OutputDir={output}
OutputBaseFilename=njupt-autologin-windows-{version}-{architecture}-setup
SetupIconFile={source}\\app-icon.ico
UninstallDisplayIcon={{app}}\\njupt-autologin-gui.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes

[Files]
Source: "{source}\\njupt-autologin.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{source}\\njupt-autologin-gui.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{source}\\njupt-autologin-task.exe"; DestDir: "{{app}}"; Flags: ignoreversion

[Icons]
Name: "{{group}}\\NJUPT 校园网自动登录"; Filename: "{{app}}\\njupt-autologin-gui.exe"
Name: "{{autodesktop}}\\NJUPT 校园网自动登录"; Filename: "{{app}}\\njupt-autologin-gui.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："
Name: "addtopath"; Description: "将命令行工具添加到当前用户 PATH"; GroupDescription: "命令行："; Flags: unchecked

[Run]
Filename: "{{app}}\\njupt-autologin.exe"; Parameters: "install-service"; Flags: runhidden waituntilterminated; Check: ExistingAutoLoginTask
Filename: "{{app}}\\njupt-autologin-gui.exe"; Description: "启动 NJUPT 校园网自动登录"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{{app}}\\njupt-autologin.exe"; Parameters: "uninstall-service"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveNJUPTTask"

[Code]
function ExistingAutoLoginTask(): Boolean;
var
  ResultCode: Integer;
begin
  Result := RegValueExists(HKCU,
    'Software\\Microsoft\\Windows\\CurrentVersion\\Run', 'NJUPT Auto Login');
  if not Result then
    Result := Exec(ExpandConstant('{{sys}}\\schtasks.exe'),
      '/Query /TN "NJUPT Auto Login"', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function CanonicalPath(Value: String): String;
begin
  Value := Trim(Value);
  if (Length(Value) >= 2) and (Value[1] = '"') and
     (Value[Length(Value)] = '"') then
  begin
    Delete(Value, Length(Value), 1);
    Delete(Value, 1, 1);
  end;
  while (Length(Value) > 3) and (Value[Length(Value)] = '\\') do
    Delete(Value, Length(Value), 1);
  Result := Lowercase(Value);
end;

function PathContains(CurrentValue, Entry: String): Boolean;
var
  Part: String;
  Separator: Integer;
begin
  Result := False;
  while CurrentValue <> '' do
  begin
    Separator := Pos(';', CurrentValue);
    if Separator = 0 then
    begin
      Part := CurrentValue;
      CurrentValue := '';
    end
    else
    begin
      Part := Copy(CurrentValue, 1, Separator - 1);
      Delete(CurrentValue, 1, Separator);
    end;
    if CanonicalPath(Part) = CanonicalPath(Entry) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

procedure AddToUserPath;
var
  CurrentValue: String;
  AppDir: String;
begin
  AppDir := ExpandConstant('{{app}}');
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', CurrentValue) then
    CurrentValue := '';
  if not PathContains(CurrentValue, AppDir) then
  begin
    if (CurrentValue <> '') and (CurrentValue[Length(CurrentValue)] <> ';') then
      CurrentValue := CurrentValue + ';';
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', CurrentValue + AppDir);
  end;
end;

procedure RemoveFromUserPath;
var
  CurrentValue: String;
  NewValue: String;
  Part: String;
  Separator: Integer;
  AppDir: String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', CurrentValue) then
    Exit;
  AppDir := ExpandConstant('{{app}}');
  NewValue := '';
  while CurrentValue <> '' do
  begin
    Separator := Pos(';', CurrentValue);
    if Separator = 0 then
    begin
      Part := CurrentValue;
      CurrentValue := '';
    end
    else
    begin
      Part := Copy(CurrentValue, 1, Separator - 1);
      Delete(CurrentValue, 1, Separator);
    end;
    if (Trim(Part) <> '') and (CanonicalPath(Part) <> CanonicalPath(AppDir)) then
    begin
      if NewValue <> '' then
        NewValue := NewValue + ';';
      NewValue := NewValue + Part;
    end;
  end;
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', NewValue);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddToUserPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveFromUserPath;
end;
""",
        encoding="utf-8-sig",
    )
    subprocess.run([str(iscc), str(script)], check=True)
    return output_dir / f"njupt-autologin-windows-{version}-{architecture}-setup.exe"


def build(output_dir: Path, expected_architecture: str | None = None) -> tuple[Path, Path | None]:
    if sys.platform != "win32":
        raise RuntimeError("Windows packages must be built on Windows")
    architecture = _architecture()
    if expected_architecture is not None and architecture != expected_architecture:
        raise RuntimeError(
            f"build runner is {architecture}, expected {expected_architecture}; "
            "cross-architecture PyInstaller output is not supported"
        )
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
        _pyinstaller(cli_entry, "njupt-autologin-task", staging, work, binaries, windowed=True)
        shutil.copy2(package / "app-icon.ico", binaries / "app-icon.ico")
        (binaries / "README.txt").write_text(
            "NJUPT 校园网自动登录\n\n"
            "运行 njupt-autologin-gui.exe 打开控制面板。程序仅使用 Windows 内置组件，"
            "不需要另行安装 Python。\n",
            encoding="utf-8-sig",
        )
        archive = output_dir / f"{PACKAGE}-windows-{version}-{architecture}-portable.zip"
        archive.unlink(missing_ok=True)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(binaries.iterdir()):
                bundle.write(path, f"{PACKAGE}-{version}/{path.name}")
        installer = _build_installer(binaries, output_dir, version, architecture, work)
    return archive, installer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--architecture", choices=("x64", "arm64"))
    args = parser.parse_args()
    archive, installer = build(args.output_dir.resolve(), args.architecture)
    print(archive)
    if installer is not None:
        print(installer)
    else:
        print("Inno Setup not found; portable package created", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
