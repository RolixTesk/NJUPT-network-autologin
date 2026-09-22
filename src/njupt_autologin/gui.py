"""Compact native desktop UI for credentials and startup service management."""

from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from importlib import resources
from tkinter import messagebox, ttk

from .client import AuthenticationError, CampusClient, NetworkError, PortalError
from .credentials import CredentialError, Credentials, default_path, load_credentials, save_credentials
from .gui_actions import login_now, service_status_items
from .service import (
    ServiceError, ServiceStatus, enable_linger, install_service, pause_service,
    resume_service, service_status, uninstall_service,
)

OPERATORS = {"校园网": "campus", "中国电信": "telecom", "中国移动": "mobile"}
OPERATOR_LABELS = {
    "campus": "校园网", "校园网": "校园网", "校园用户": "校园网",
    "telecom": "中国电信", "电信": "中国电信", "中国电信": "中国电信", "@njxy": "中国电信",
    "mobile": "中国移动", "移动": "中国移动", "中国移动": "中国移动", "@cmcc": "中国移动",
}

BG, SURFACE, FIELD = "#F2F5FA", "#FFFFFF", "#F8FAFD"
PRIMARY, PRIMARY_HOVER = "#3154B4", "#27479F"
TEXT, MUTED, BORDER = "#17213B", "#68758C", "#D8E0EC"
SUCCESS, WARNING, DANGER = "#23875B", "#B57916", "#B13C4C"
EXPECTED_ERRORS = (
    AuthenticationError, CredentialError, NetworkError, PortalError,
    ServiceError, OSError, ValueError, json.JSONDecodeError,
)


def _set_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.tk.call("tk", "appname", "njupt-autologin")
        root.title("NJUPT 校园网自动登录")
        root.iconname("NJUPT 校园网自动登录")
        root.configure(background=BG)
        root.resizable(False, False)
        root.option_add("*tearOff", False)
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.operator = tk.StringVar(value="中国移动")
        self.interface = tk.StringVar(value="auto")
        self.remove_credentials = tk.BooleanVar(value=False)
        self.operation_text = tk.StringVar(value="就绪，可以立即检查并连接校园网。")
        self.buttons: list[ttk.Button] = []
        self.status_values: list[tk.Label] = []
        self.icon_image: tk.PhotoImage | None = None
        self.header_icon: tk.PhotoImage | None = None
        self._configure_style()
        self._build()
        self._load_existing()
        root.update_idletasks()
        self._center_window()
        self.refresh_status()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.font_family = "Segoe UI" if sys.platform == "win32" else "Noto Sans CJK SC"
        self.root.option_add("*Font", (self.font_family, 10))
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Section.TLabel", background=SURFACE, foreground=TEXT, font=(self.font_family, 11, "bold"))
        style.configure(
            "Modern.TEntry", padding=(9, 6), fieldbackground=FIELD, foreground=TEXT,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, insertcolor=TEXT,
        )
        style.map("Modern.TEntry", bordercolor=[("focus", PRIMARY)])
        style.configure(
            "Modern.TCombobox", padding=(9, 5), fieldbackground=FIELD, foreground=TEXT,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, arrowcolor=PRIMARY,
        )
        style.map(
            "Modern.TCombobox", fieldbackground=[("readonly", FIELD)],
            foreground=[("readonly", TEXT)], bordercolor=[("focus", PRIMARY)],
        )
        style.configure(
            "Primary.TButton", background=PRIMARY, foreground="#FFFFFF", borderwidth=0,
            padding=(18, 9), font=(self.font_family, 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", PRIMARY_HOVER), ("pressed", "#203C8B"), ("disabled", "#AAB7D5")],
            foreground=[("disabled", "#F3F5FA")],
        )
        style.configure(
            "Secondary.TButton", background="#E9EEF8", foreground=PRIMARY,
            borderwidth=0, padding=(14, 7), font=(self.font_family, 9, "bold"),
        )
        style.map("Secondary.TButton", background=[("active", "#DAE3F4"), ("disabled", "#EEF1F6")])
        style.configure(
            "Quiet.TButton", background=SURFACE, foreground=TEXT, borderwidth=1,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(13, 6),
        )
        style.map("Quiet.TButton", background=[("active", FIELD), ("disabled", "#F5F6F8")])
        style.configure("Danger.TButton", background="#FCECEF", foreground=DANGER, borderwidth=0, padding=(13, 6))
        style.map("Danger.TButton", background=[("active", "#F7DDE2"), ("disabled", "#F5F1F2")])
        style.configure("Modern.TCheckbutton", background=SURFACE, foreground=MUTED)
        style.map("Modern.TCheckbutton", background=[("active", SURFACE)])
        style.configure("Slim.Horizontal.TProgressbar", troughcolor="#DFE5F0", background=PRIMARY, borderwidth=0)

    @staticmethod
    def _card(parent: tk.Misc) -> ttk.Frame:
        border = tk.Frame(parent, background=BORDER, padx=1, pady=1)
        content = ttk.Frame(border, style="Card.TFrame", padding=13)
        content.pack(fill="both", expand=True)
        return content

    def _build(self) -> None:
        main = ttk.Frame(self.root, style="App.TFrame", padding=14)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)

        header = ttk.Frame(main, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        try:
            icon_path = resources.files("njupt_autologin").joinpath("app-icon.png")
            self.icon_image = tk.PhotoImage(file=str(icon_path))
            self.header_icon = self.icon_image.subsample(2)
            self.root.iconphoto(True, self.icon_image)
            ttk.Label(header, image=self.header_icon, background=BG).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        except (OSError, tk.TclError):
            pass
        ttk.Label(
            header, text="NJUPT 校园网", background=BG, foreground=TEXT,
            font=(self.font_family, 18, "bold"),
        ).grid(row=0, column=1, sticky="sw")
        ttk.Label(
            header, text="自动登录与开机服务控制", background=BG, foreground=MUTED,
            font=(self.font_family, 9),
        ).grid(row=1, column=1, sticky="nw")

        connect = self._card(main)
        connect.master.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        connect.columnconfigure(0, weight=1)
        ttk.Label(connect, text="校园网连接", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            connect, text="已登录时不会重复认证，也不会额外占用设备名额。", style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        login_button = ttk.Button(
            connect, text="立即登录校园网", style="Primary.TButton", command=self.immediate_login,
        )
        login_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))
        self.buttons.append(login_button)

        credentials = self._card(main)
        credentials.master.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        credentials.columnconfigure(0, weight=1)
        credentials.columnconfigure(1, weight=1)
        ttk.Label(credentials, text="登录配置", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 7)
        )
        self._field(credentials, "账号", self.username, 1, 0)
        self._field(credentials, "密码", self.password, 1, 1, show="●")
        self._field(credentials, "运营商", self.operator, 3, 0, values=tuple(OPERATORS))
        self._field(credentials, "网络接口", self.interface, 3, 1)
        ttk.Label(
            credentials, text="接口使用 auto 可自动选择；密码留空时沿用已保存的密码。", style="Muted.TLabel",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 8))
        save_button = ttk.Button(credentials, text="保存登录信息", style="Quiet.TButton", command=self.save)
        install_button = ttk.Button(
            credentials, text="安装并启用开机自启", style="Secondary.TButton", command=self.install,
        )
        save_button.grid(row=6, column=0, sticky="ew", padx=(0, 5))
        install_button.grid(row=6, column=1, sticky="ew", padx=(5, 0))
        self.buttons.extend((save_button, install_button))

        status = self._card(main)
        status.master.grid(row=3, column=0, sticky="ew")
        for column in range(3):
            status.columnconfigure(column, weight=1, uniform="status")
        ttk.Label(status, text="服务状态", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        refresh_button = ttk.Button(status, text="刷新", style="Quiet.TButton", command=self.refresh_status)
        refresh_button.grid(row=0, column=2, sticky="e")
        self.buttons.append(refresh_button)
        for column, label in enumerate(("自动登录服务", "定时器", "开机运行")):
            tile = tk.Frame(status, background=FIELD, padx=12, pady=9)
            tile.grid(
                row=1, column=column, sticky="ew",
                padx=(0 if column == 0 else 4, 0 if column == 2 else 4), pady=(8, 8),
            )
            tk.Label(tile, text=label, background=FIELD, foreground=MUTED, font=(self.font_family, 9)).pack(anchor="w")
            value = tk.Label(
                tile, text="读取中…", background=FIELD, foreground=MUTED,
                font=(self.font_family, 10, "bold"),
            )
            value.pack(anchor="w", pady=(2, 0))
            self.status_values.append(value)

        self.operation_banner = tk.Frame(status, background="#EDF2FC", padx=12, pady=9)
        self.operation_banner.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.operation_dot = tk.Label(
            self.operation_banner, text="●", background="#EDF2FC", foreground=PRIMARY,
            font=(self.font_family, 9),
        )
        self.operation_dot.pack(side="left", padx=(0, 7))
        self.operation_label = tk.Label(
            self.operation_banner, textvariable=self.operation_text, background="#EDF2FC", foreground=TEXT,
            font=(self.font_family, 9), anchor="w", wraplength=530, justify="left",
        )
        self.operation_label.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(status, mode="indeterminate", style="Slim.Horizontal.TProgressbar")
        self.progress.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        self.progress.grid_remove()

        maintenance = ttk.Frame(status, style="Card.TFrame")
        maintenance.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        maintenance.columnconfigure(0, weight=1)
        maintenance.columnconfigure(1, weight=1)
        logout_button = ttk.Button(
            maintenance, text="注销当前会话", style="Quiet.TButton", command=self.logout,
        )
        remove_button = ttk.Button(
            maintenance, text="卸载开机自启服务", style="Danger.TButton", command=self.uninstall,
        )
        logout_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        remove_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ttk.Checkbutton(
            maintenance, text="卸载时同时删除保存的登录信息",
            variable=self.remove_credentials, style="Modern.TCheckbutton",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.buttons.extend((logout_button, remove_button))

    def _field(
        self, parent: ttk.Frame, label: str, variable: tk.StringVar,
        row: int, column: int, *, show: str | None = None,
        values: tuple[str, ...] | None = None,
    ) -> None:
        padx = (0 if column == 0 else 7, 7 if column == 0 else 0)
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w", padx=padx)
        if values is None:
            widget: ttk.Widget = ttk.Entry(
                parent, textvariable=variable, show=show or "", style="Modern.TEntry",
            )
        else:
            widget = ttk.Combobox(
                parent, textvariable=variable, values=values, state="readonly", style="Modern.TCombobox",
            )
        widget.grid(row=row + 1, column=column, sticky="ew", padx=padx, pady=(2, 5))

    def _center_window(self) -> None:
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _load_existing(self) -> None:
        try:
            credentials = load_credentials(path=default_path())
        except (CredentialError, json.JSONDecodeError, OSError):
            return
        self.username.set(credentials.username)
        self.operator.set(OPERATOR_LABELS.get(credentials.operator.strip().lower(), "中国移动"))

    @staticmethod
    def _credentials_from_values(username: str, password: str, operator: str) -> Credentials:
        if not password:
            try:
                password = load_credentials(path=default_path()).password
            except (CredentialError, json.JSONDecodeError, OSError) as exc:
                raise CredentialError("请输入密码") from exc
        return Credentials(username=username.strip(), password=password, operator=OPERATORS[operator])

    def _captured_credentials(self) -> tuple[str, str, str]:
        return self.username.get(), self.password.get(), self.operator.get()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self.buttons:
            button.configure(state=state)
        if busy:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _set_operation(self, message: str, kind: str = "neutral") -> None:
        background, accent = {
            "neutral": ("#EDF2FC", PRIMARY), "success": ("#EAF7F1", SUCCESS), "error": ("#FCECEF", DANGER),
        }[kind]
        self.operation_text.set(message)
        self.operation_banner.configure(background=background)
        self.operation_dot.configure(background=background, foreground=accent)
        self.operation_label.configure(background=background)

    def _run_async(self, action: Callable[[], str], progress_text: str) -> None:
        self._set_busy(True)
        self._set_operation(progress_text)
        self._background(action, self._finish_success, self._finish_error)

    def _background(
        self, action: Callable[[], object], on_success: Callable[[object], None],
        on_error: Callable[[str], None],
    ) -> None:
        results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result = action()
            except EXPECTED_ERRORS as exc:
                results.put((False, str(exc)))
            else:
                results.put((True, result))

        def poll() -> None:
            try:
                succeeded, value = results.get_nowait()
            except queue.Empty:
                self.root.after(50, poll)
                return
            on_success(value) if succeeded else on_error(str(value))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, poll)

    def _finish_error(self, message: str) -> None:
        self._set_busy(False)
        self._set_operation("操作失败：" + message, "error")

    def _finish_success(self, value: object) -> None:
        self.password.set("")
        self._set_busy(False)
        self._set_operation(str(value), "success")
        self.refresh_status(keep_message=True)

    def immediate_login(self) -> None:
        interface = self.interface.get().strip()
        username, password, operator = self._captured_credentials()
        self._run_async(
            lambda: login_now(interface, lambda: self._credentials_from_values(username, password, operator)),
            "正在检查校园网状态…",
        )

    def save(self) -> None:
        username, password, operator = self._captured_credentials()

        def action() -> str:
            save_credentials(self._credentials_from_values(username, password, operator))
            return "登录信息已保存。"

        self._run_async(action, "正在保存登录信息…")

    def install(self) -> None:
        interface = self.interface.get().strip()
        username, password, operator = self._captured_credentials()

        def action() -> str:
            credentials = self._credentials_from_values(username, password, operator)
            save_credentials(credentials)
            enable_linger()
            install_service(interface)
            try:
                message = login_now(interface, lambda: credentials)
            except EXPECTED_ERRORS as exc:
                raise ServiceError(f"服务已安装，但立即登录失败：{exc}") from exc
            return "开机自启服务已安装并启用；" + message

        self._run_async(action, "正在安装服务并检查校园网连接…")

    def uninstall(self) -> None:
        if not messagebox.askyesno("确认卸载", "确定要停用并卸载自动登录服务吗？", parent=self.root):
            return
        remove_credentials = self.remove_credentials.get()

        def action() -> str:
            uninstall_service(remove_credentials=remove_credentials)
            return "开机自启服务已卸载。"

        self._run_async(action, "正在卸载开机自启服务…")

    def logout(self) -> None:
        if not messagebox.askyesno(
            "确认注销", "确定要注销当前校园网会话吗？自动登录定时器将暂停，重启后恢复。", parent=self.root,
        ):
            return
        interface = self.interface.get().strip()

        def action() -> str:
            timer_was_active = pause_service()
            try:
                CampusClient(interface=interface).logout()
            except Exception:
                if timer_was_active:
                    resume_service()
                raise
            return "校园网会话已注销；正在运行的自动登录定时器已暂停。"

        self._run_async(action, "正在注销校园网会话…")

    def refresh_status(self, *, keep_message: bool = False) -> None:
        self._set_busy(True)
        if not keep_message:
            self._set_operation("正在读取服务状态…")
        self._background(
            service_status,
            lambda value: self._status_loaded(value, keep_message=keep_message),
            lambda value: self._status_error(value, keep_message=keep_message),
        )

    def _status_loaded(self, value: object, *, keep_message: bool) -> None:
        if not isinstance(value, ServiceStatus):
            self._status_error("服务返回了无效状态", keep_message=keep_message)
            return
        colors = {"muted": MUTED, "success": SUCCESS, "warning": WARNING}
        for widget, (text, kind) in zip(self.status_values, service_status_items(value), strict=True):
            widget.configure(text=text, foreground=colors[kind])
        self._set_busy(False)
        if not keep_message:
            self._set_operation("服务状态已更新。", "success")

    def _status_error(self, value: str, *, keep_message: bool) -> None:
        for widget in self.status_values:
            widget.configure(text="不可用", foreground=DANGER)
        self._set_busy(False)
        if not keep_message:
            self._set_operation("无法读取服务状态：" + value, "error")


def main() -> int:
    _set_windows_dpi_awareness()
    try:
        root = tk.Tk(className="NjuptAutologin")
    except tk.TclError as exc:
        print(f"Cannot start GUI: {exc}", file=sys.stderr)
        return 1
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
