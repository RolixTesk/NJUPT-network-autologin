"""Compact native desktop UI for campus login and startup service management."""

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
from .gui_actions import (
    ConnectionSnapshot,
    connection_status,
    connection_status_text,
    login_now,
    service_status_items,
)
from .platform_services import DesktopServiceAdapter, ServiceError, ServiceStatus, load_service_adapter

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
    def __init__(self, root: tk.Tk, services: DesktopServiceAdapter | None = None) -> None:
        self.root = root
        self.services = services or load_service_adapter()
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
        self.connection_operation_text = tk.StringVar(value="连接操作就绪。")
        self.service_operation_text = tk.StringVar(value="服务管理就绪。")
        self.connection_title = tk.StringVar(value="正在检测连接…")
        self.connection_detail = tk.StringVar(value="正在核对校园网会话和外部网络连通性。")
        self.multi_interface_text = tk.StringVar()
        self.buttons: list[ttk.Button] = []
        self.status_values: list[tk.Label] = []
        self.icon_image: tk.PhotoImage | None = None
        self.header_icon: tk.PhotoImage | None = None
        self.current_connection_interface: str | None = None
        self._busy_scope = "connection"
        self._animation_job: str | None = None
        self._credentials_visible = False
        self._has_credentials = self._load_existing()
        try:
            self.interface_values = ("auto", *self.services.available_interfaces())
        except EXPECTED_ERRORS:
            self.interface_values = ("auto",)

        self._configure_style()
        self._build()
        root.update_idletasks()
        self._credentials_height = self.credentials_card.winfo_reqheight() + 8
        self._set_credentials_visible(not self._has_credentials, animate=False)
        root.update_idletasks()
        self._center_window()
        self.refresh_all()

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
        style.configure("Danger.TButton", background="#FCECEF", foreground=DANGER, borderwidth=0, padding=(13, 7))
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
        self.main = ttk.Frame(self.root, style="App.TFrame", padding=14)
        self.main.grid(row=0, column=0, sticky="nsew")
        self.main.columnconfigure(0, weight=1, minsize=508)

        header = ttk.Frame(self.main, style="App.TFrame")
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
            header, text="认证、连通性与开机服务", background=BG, foreground=MUTED,
            font=(self.font_family, 9),
        ).grid(row=1, column=1, sticky="nw")

        self.credentials_shell = tk.Frame(self.main, background=BG, height=1)
        self.credentials_shell.grid(row=1, column=0, sticky="ew")
        self.credentials_shell.grid_propagate(False)
        credentials = self._card(self.credentials_shell)
        self.credentials_card = credentials.master
        self.credentials_card.place(x=0, y=0, relwidth=1)
        credentials.columnconfigure(0, weight=1)
        credentials.columnconfigure(1, weight=1)
        ttk.Label(credentials, text="登录配置", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 7)
        )
        self._field(credentials, "账号", self.username, 1, 0)
        self._field(credentials, "密码", self.password, 1, 1, show="●")
        self._field(credentials, "运营商", self.operator, 3, 0, values=tuple(OPERATORS))
        self.interface_box = self._field(
            credentials, "网络接口", self.interface, 3, 1, values=self.interface_values,
        )
        ttk.Label(
            credentials, text="auto 会自动选择可用设备；密码留空时沿用已保存的密码。", style="Muted.TLabel",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 8))
        save_button = ttk.Button(credentials, text="保存登录信息", style="Quiet.TButton", command=self.save)
        install_button = ttk.Button(
            credentials, text="安装并启用开机自启", style="Secondary.TButton", command=self.install,
        )
        save_button.grid(row=6, column=0, sticky="ew", padx=(0, 5))
        install_button.grid(row=6, column=1, sticky="ew", padx=(5, 0))
        self.buttons.extend((save_button, install_button))

        connection = self._card(self.main)
        connection.master.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        connection.columnconfigure(0, weight=1)
        ttk.Label(connection, text="登录状态", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        refresh_button = ttk.Button(connection, text="刷新", style="Quiet.TButton", command=self.refresh_all)
        refresh_button.grid(row=0, column=1, sticky="e", padx=(8, 6))
        self.config_button = ttk.Button(
            connection, text="登录配置", style="Secondary.TButton", command=self.toggle_credentials,
        )
        self.config_button.grid(row=0, column=2, sticky="e")
        self.buttons.extend((refresh_button, self.config_button))

        connection_panel = tk.Frame(connection, background=FIELD, padx=12, pady=10)
        connection_panel.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 8))
        connection_panel.columnconfigure(1, weight=1)
        self.connection_dot = tk.Label(
            connection_panel, text="●", background=FIELD, foreground=MUTED,
            font=(self.font_family, 12),
        )
        self.connection_dot.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 9))
        self.connection_title_label = tk.Label(
            connection_panel, textvariable=self.connection_title, background=FIELD, foreground=TEXT,
            font=(self.font_family, 11, "bold"), anchor="w",
        )
        self.connection_title_label.grid(row=0, column=1, sticky="ew")
        tk.Label(
            connection_panel, textvariable=self.connection_detail, background=FIELD, foreground=MUTED,
            font=(self.font_family, 9), anchor="w", justify="left", wraplength=455,
        ).grid(row=1, column=1, sticky="ew", pady=(2, 0))

        self.multi_interface_banner = tk.Frame(connection, background="#FCECEF", padx=10, pady=7)
        tk.Label(
            self.multi_interface_banner, text="!", background="#FCECEF", foreground=DANGER,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left", padx=(0, 7))
        tk.Label(
            self.multi_interface_banner, textvariable=self.multi_interface_text,
            background="#FCECEF", foreground=DANGER, font=(self.font_family, 9),
            anchor="w", justify="left", wraplength=460,
        ).pack(side="left", fill="x", expand=True)
        self.multi_interface_banner.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self.multi_interface_banner.grid_remove()

        self.connection_operation_banner = tk.Frame(connection, background="#EDF2FC", padx=12, pady=9)
        self.connection_operation_banner.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.connection_operation_dot = tk.Label(
            self.connection_operation_banner, text="●", background="#EDF2FC", foreground=PRIMARY,
            font=(self.font_family, 9),
        )
        self.connection_operation_dot.pack(side="left", padx=(0, 7))
        self.connection_operation_label = tk.Label(
            self.connection_operation_banner, textvariable=self.connection_operation_text,
            background="#EDF2FC", foreground=TEXT, font=(self.font_family, 9),
            anchor="w", wraplength=480, justify="left",
        )
        self.connection_operation_label.pack(side="left", fill="x", expand=True)
        self.connection_progress_slot = tk.Frame(connection, background=SURFACE, height=10)
        self.connection_progress_slot.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.connection_progress_slot.grid_propagate(False)
        self.connection_progress = ttk.Progressbar(
            self.connection_progress_slot, mode="indeterminate", style="Slim.Horizontal.TProgressbar",
        )

        connection_actions = ttk.Frame(connection, style="Card.TFrame")
        connection_actions.grid(row=5, column=0, columnspan=3, sticky="ew")
        connection_actions.columnconfigure(0, weight=1)
        connection_actions.columnconfigure(1, weight=1)
        login_button = ttk.Button(
            connection_actions, text="立即登录校园网", style="Primary.TButton", command=self.immediate_login,
        )
        logout_button = ttk.Button(
            connection_actions, text="注销当前会话", style="Quiet.TButton", command=self.logout,
        )
        login_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        logout_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.buttons.extend((login_button, logout_button))

        status = self._card(self.main)
        status.master.grid(row=3, column=0, sticky="ew")
        for column in range(3):
            status.columnconfigure(column, weight=1, uniform="status")
        ttk.Label(status, text="服务状态", style="Section.TLabel").grid(row=0, column=0, sticky="w")
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

        self.service_operation_banner = tk.Frame(status, background="#EDF2FC", padx=12, pady=9)
        self.service_operation_banner.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.service_operation_dot = tk.Label(
            self.service_operation_banner, text="●", background="#EDF2FC", foreground=PRIMARY,
            font=(self.font_family, 9),
        )
        self.service_operation_dot.pack(side="left", padx=(0, 7))
        self.service_operation_label = tk.Label(
            self.service_operation_banner, textvariable=self.service_operation_text,
            background="#EDF2FC", foreground=TEXT,
            font=(self.font_family, 9), anchor="w", wraplength=480, justify="left",
        )
        self.service_operation_label.pack(side="left", fill="x", expand=True)
        self.service_progress_slot = tk.Frame(status, background=SURFACE, height=10)
        self.service_progress_slot.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.service_progress_slot.grid_propagate(False)
        self.service_progress = ttk.Progressbar(
            self.service_progress_slot, mode="indeterminate", style="Slim.Horizontal.TProgressbar",
        )

        maintenance = ttk.Frame(status, style="Card.TFrame")
        maintenance.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        maintenance.columnconfigure(0, weight=1)
        remove_button = ttk.Button(
            maintenance, text="卸载开机自启服务", style="Danger.TButton", command=self.uninstall,
        )
        remove_button.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(
            maintenance, text="卸载时同时删除保存的登录信息",
            variable=self.remove_credentials, style="Modern.TCheckbutton",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.buttons.append(remove_button)

    def _field(
        self, parent: ttk.Frame, label: str, variable: tk.StringVar,
        row: int, column: int, *, show: str | None = None,
        values: tuple[str, ...] | None = None,
    ) -> ttk.Widget:
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
        return widget

    def _center_window(self) -> None:
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _load_existing(self) -> bool:
        try:
            credentials = load_credentials(path=default_path())
        except (CredentialError, json.JSONDecodeError, OSError):
            return False
        self.username.set(credentials.username)
        self.operator.set(OPERATOR_LABELS.get(credentials.operator.strip().lower(), "中国移动"))
        return True

    def _refresh_interface_choices(self) -> None:
        try:
            interfaces = self.services.available_interfaces()
        except EXPECTED_ERRORS:
            interfaces = ()
        values = ("auto", *interfaces)
        self.interface_values = tuple(dict.fromkeys(values))
        self.interface_box.configure(values=self.interface_values)
        if self.interface.get() not in self.interface_values:
            self.interface.set("auto")

    def toggle_credentials(self) -> None:
        self._set_credentials_visible(not self._credentials_visible, animate=True)

    def _set_credentials_visible(self, visible: bool, *, animate: bool) -> None:
        if visible:
            self._refresh_interface_choices()
        if self._animation_job is not None:
            self.root.after_cancel(self._animation_job)
            self._animation_job = None
        self._credentials_visible = visible
        self.config_button.configure(text="收起配置" if visible else "登录配置")
        target = self._credentials_height if visible else 1
        start = self.credentials_shell.winfo_height()
        if not animate or start == target:
            self.credentials_shell.configure(height=target)
            return

        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        window_x, window_y = self.root.winfo_x(), self.root.winfo_y()
        steps = 10

        def frame(index: int) -> None:
            progress = index / steps
            eased = 1 - (1 - progress) ** 3
            height = round(start + (target - start) * eased)
            self.credentials_shell.configure(height=height)
            new_window_height = window_height + height - start
            self.root.geometry(f"{window_width}x{new_window_height}+{window_x}+{window_y}")
            if index < steps:
                self._animation_job = self.root.after(16, frame, index + 1)
            else:
                self._animation_job = None

        frame(1)

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

    def _set_busy(self, busy: bool, *, scope: str = "connection") -> None:
        state = "disabled" if busy else "normal"
        for button in self.buttons:
            button.configure(state=state)
        for progress in (self.connection_progress, self.service_progress):
            progress.stop()
            progress.place_forget()
        if busy:
            self._busy_scope = scope
            progress = self.connection_progress if scope == "connection" else self.service_progress
            progress.place(x=0, y=7, relwidth=1, height=3)
            progress.start(12)

    def _set_operation(self, message: str, kind: str = "neutral", *, scope: str = "connection") -> None:
        background, accent = {
            "neutral": ("#EDF2FC", PRIMARY), "success": ("#EAF7F1", SUCCESS), "error": ("#FCECEF", DANGER),
        }[kind]
        if scope == "connection":
            text, banner, dot, label = (
                self.connection_operation_text, self.connection_operation_banner,
                self.connection_operation_dot, self.connection_operation_label,
            )
        else:
            text, banner, dot, label = (
                self.service_operation_text, self.service_operation_banner,
                self.service_operation_dot, self.service_operation_label,
            )
        text.set(message)
        banner.configure(background=background)
        dot.configure(background=background, foreground=accent)
        label.configure(background=background)

    def _run_async(
        self, action: Callable[[], str], progress_text: str,
        *, scope: str = "connection", after_success: Callable[[], None] | None = None,
    ) -> None:
        self._set_busy(True, scope=scope)
        self._set_operation(progress_text, scope=scope)
        self._background(
            action,
            lambda value: self._finish_success(value, scope=scope, after_success=after_success),
            lambda message: self._finish_error(message, scope=scope),
        )

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
            except Exception as exc:  # Keep a failed backend from leaving the GUI permanently busy.
                results.put((False, f"{type(exc).__name__}: {exc}"))
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

    def _finish_error(self, message: str, *, scope: str) -> None:
        self._set_busy(False)
        self._set_operation("操作失败：" + message, "error", scope=scope)

    def _finish_success(
        self, value: object, *, scope: str,
        after_success: Callable[[], None] | None = None,
    ) -> None:
        self.password.set("")
        self._set_busy(False)
        self._set_operation(str(value), "success", scope=scope)
        if after_success is not None:
            after_success()
        self.refresh_all(keep_message=True)

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

        self._run_async(
            action, "正在保存登录信息…",
            after_success=lambda: self._set_credentials_visible(False, animate=True),
        )

    def install(self) -> None:
        interface = self.interface.get().strip()
        username, password, operator = self._captured_credentials()

        def action() -> str:
            credentials = self._credentials_from_values(username, password, operator)
            save_credentials(credentials)
            self.services.install(interface)
            try:
                message = login_now(interface, lambda: credentials)
            except EXPECTED_ERRORS as exc:
                raise ServiceError(f"服务已安装，但立即登录失败：{exc}") from exc
            return "开机自启服务已安装并启用；" + message

        self._run_async(
            action, "正在安装服务并检查校园网连接…",
            scope="service",
            after_success=lambda: self._set_credentials_visible(False, animate=True),
        )

    def uninstall(self) -> None:
        if not messagebox.askyesno("确认卸载", "确定要停用并卸载自动登录服务吗？", parent=self.root):
            return
        remove_credentials = self.remove_credentials.get()

        def action() -> str:
            self.services.uninstall(remove_credentials=remove_credentials)
            return "开机自启服务已卸载。"

        self._run_async(action, "正在卸载开机自启服务…", scope="service")

    def logout(self) -> None:
        if not messagebox.askyesno(
            "确认注销", "确定要注销当前校园网会话吗？自动登录定时器将暂停，重启后恢复。", parent=self.root,
        ):
            return
        interface = self.current_connection_interface or self.interface.get().strip()

        def action() -> str:
            timer_was_active = self.services.pause()
            try:
                CampusClient(interface=interface).logout()
            except Exception:
                if timer_was_active:
                    self.services.resume()
                raise
            return "校园网会话已注销；正在运行的自动登录定时器已暂停。"

        self._run_async(action, "正在注销校园网会话…")

    def refresh_all(self, *, keep_message: bool = False) -> None:
        interface = self.interface.get().strip()
        self._set_busy(True, scope="connection")
        if not keep_message:
            self._set_operation("正在检测校园网与服务状态…", scope="connection")

        def action() -> tuple[ConnectionSnapshot | str, ServiceStatus | str]:
            try:
                connection: ConnectionSnapshot | str = connection_status(interface)
            except EXPECTED_ERRORS as exc:
                connection = str(exc)
            try:
                service: ServiceStatus | str = self.services.status()
            except EXPECTED_ERRORS as exc:
                service = str(exc)
            return connection, service

        self._background(
            action,
            lambda value: self._all_status_loaded(value, keep_message=keep_message),
            lambda value: self._all_status_error(value, keep_message=keep_message),
        )

    def _all_status_loaded(self, value: object, *, keep_message: bool) -> None:
        if not isinstance(value, tuple) or len(value) != 2:
            self._all_status_error("状态模块返回了无效数据", keep_message=keep_message)
            return
        connection, service = value
        connection_ok = isinstance(connection, ConnectionSnapshot)
        service_ok = isinstance(service, ServiceStatus)
        if connection_ok:
            self._show_connection(connection)
        else:
            self._show_connection_error(str(connection))
        if service_ok:
            self._show_service(service)
        else:
            self._show_service_error()
        self._set_busy(False)
        if not keep_message:
            if connection_ok:
                self._set_operation("校园网状态已更新。", "success", scope="connection")
            else:
                self._set_operation("连接状态不可用：" + str(connection), "error", scope="connection")
            if not service_ok:
                self._set_operation("服务状态不可用：" + str(service), "error", scope="service")
        self._fit_window_to_content()

    def _show_connection(self, snapshot: ConnectionSnapshot) -> None:
        title, detail, kind = connection_status_text(snapshot)
        color = {"success": SUCCESS, "warning": WARNING, "error": DANGER}[kind]
        self.current_connection_interface = snapshot.interface
        self.connection_title.set(title)
        self.connection_detail.set(detail)
        self.connection_dot.configure(foreground=color)
        self.connection_title_label.configure(foreground=color)
        if len(snapshot.online_interfaces) > 1:
            interfaces = "、".join(snapshot.online_interfaces)
            self.multi_interface_text.set(f"检测到多个网卡已登录校园网：{interfaces}。建议只保留一个会话。")
            self.multi_interface_banner.grid()
        else:
            self.multi_interface_banner.grid_remove()

    def _show_connection_error(self, message: str) -> None:
        self.current_connection_interface = None
        self.connection_title.set("连接状态不可用")
        self.connection_detail.set(message)
        self.connection_dot.configure(foreground=DANGER)
        self.connection_title_label.configure(foreground=DANGER)
        self.multi_interface_banner.grid_remove()

    def _show_service(self, status: ServiceStatus) -> None:
        colors = {"muted": MUTED, "success": SUCCESS, "warning": WARNING}
        for widget, (text, kind) in zip(self.status_values, service_status_items(status), strict=True):
            widget.configure(text=text, foreground=colors[kind])

    def _show_service_error(self) -> None:
        for widget in self.status_values:
            widget.configure(text="不可用", foreground=DANGER)

    def _all_status_error(self, value: str, *, keep_message: bool) -> None:
        self._show_connection_error(value)
        self._show_service_error()
        self._set_busy(False)
        if not keep_message:
            self._set_operation("无法读取连接状态：" + value, "error", scope="connection")
            self._set_operation("无法读取服务状态：" + value, "error", scope="service")
        self._fit_window_to_content()

    def _fit_window_to_content(self) -> None:
        """Resize after a conditional warning is added or removed."""
        if self._animation_job is not None:
            return
        self.root.update_idletasks()
        width = max(self.root.winfo_width(), self.root.winfo_reqwidth())
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")


def main() -> int:
    _set_windows_dpi_awareness()
    try:
        root = tk.Tk(className="NjuptAutologin")
        services = load_service_adapter()
    except (tk.TclError, ServiceError) as exc:
        print(f"Cannot start GUI: {exc}", file=sys.stderr)
        return 1
    App(root, services)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
