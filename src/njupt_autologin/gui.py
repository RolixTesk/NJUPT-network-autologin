"""Small Tkinter front end for credentials and startup service management."""

from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from .client import AuthenticationError, CampusClient, NetworkError, PortalError
from .credentials import CredentialError, Credentials, default_path, load_credentials, save_credentials
from .service import (
    ServiceError,
    ServiceStatus,
    enable_linger,
    install_service,
    pause_service,
    resume_service,
    service_status,
    uninstall_service,
)


OPERATORS = {
    "校园网": "campus",
    "中国电信": "telecom",
    "中国移动": "mobile",
}
OPERATOR_LABELS = {
    "campus": "校园网",
    "校园网": "校园网",
    "校园用户": "校园网",
    "telecom": "中国电信",
    "电信": "中国电信",
    "中国电信": "中国电信",
    "@njxy": "中国电信",
    "mobile": "中国移动",
    "移动": "中国移动",
    "中国移动": "中国移动",
    "@cmcc": "中国移动",
}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NJUPT 校园网自动登录")
        self.root.resizable(False, False)
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.operator = tk.StringVar(value="中国移动")
        self.interface = tk.StringVar(value="auto")
        self.remove_credentials = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="正在读取服务状态…")
        self.buttons: list[ttk.Button] = []
        self._build()
        self._load_existing()
        self.refresh_status()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="校园网登录信息", font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        ttk.Label(frame, text="账号").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=5)
        ttk.Entry(frame, textvariable=self.username, width=32).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="密码").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=5)
        ttk.Entry(frame, textvariable=self.password, width=32, show="●").grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="运营商").grid(row=3, column=0, sticky="e", padx=(0, 10), pady=5)
        ttk.Combobox(
            frame, textvariable=self.operator, values=tuple(OPERATORS), state="readonly", width=29
        ).grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="校园网接口").grid(row=4, column=0, sticky="e", padx=(0, 10), pady=5)
        ttk.Entry(frame, textvariable=self.interface, width=32).grid(row=4, column=1, sticky="ew", pady=5)
        ttk.Label(
            frame,
            text="接口填 auto 可自动选择。密码留空时沿用已保存的密码。凭据保存在当前用户的私有配置目录。",
            foreground="#555555",
            wraplength=390,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 14))

        save_button = ttk.Button(frame, text="保存登录信息", command=self.save)
        install_button = ttk.Button(frame, text="安装并启用开机自启", command=self.install)
        save_button.grid(row=6, column=0, sticky="ew", padx=(0, 5))
        install_button.grid(row=6, column=1, sticky="ew", padx=(5, 0))
        self.buttons.extend((save_button, install_button))

        logout_button = ttk.Button(frame, text="注销当前校园网会话", command=self.logout)
        logout_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.buttons.append(logout_button)

        ttk.Separator(frame).grid(row=8, column=0, columnspan=2, sticky="ew", pady=16)
        ttk.Label(frame, text="服务状态", font=("TkDefaultFont", 11, "bold")).grid(
            row=9, column=0, sticky="w"
        )
        ttk.Label(frame, textvariable=self.status_text, wraplength=390).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(7, 10)
        )
        ttk.Checkbutton(
            frame, text="卸载时同时删除保存的登录信息", variable=self.remove_credentials
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 8))
        remove_button = ttk.Button(frame, text="卸载开机自启服务", command=self.uninstall)
        refresh_button = ttk.Button(frame, text="刷新状态", command=self.refresh_status)
        remove_button.grid(row=12, column=0, sticky="ew", padx=(0, 5))
        refresh_button.grid(row=12, column=1, sticky="ew", padx=(5, 0))
        self.buttons.extend((remove_button, refresh_button))
        frame.columnconfigure(1, weight=1)

    def _load_existing(self) -> None:
        try:
            credentials = load_credentials(path=default_path())
        except (CredentialError, json.JSONDecodeError):
            return
        self.username.set(credentials.username)
        self.operator.set(OPERATOR_LABELS.get(credentials.operator.strip().lower(), "中国移动"))

    def _credentials(self) -> Credentials:
        password = self.password.get()
        if not password:
            try:
                password = load_credentials(path=default_path()).password
            except (CredentialError, json.JSONDecodeError) as exc:
                raise CredentialError("请输入密码") from exc
        return Credentials(
            username=self.username.get().strip(),
            password=password,
            operator=OPERATORS[self.operator.get()],
        )

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self.buttons:
            button.configure(state=state)

    def _run_async(self, action: Callable[[], None], success: str) -> None:
        self._set_busy(True)
        self.status_text.set("正在处理…")

        self._background(
            action,
            lambda _result: self._finish_success(success),
            self._finish_error,
        )

    def _background(
        self,
        action: Callable[[], object],
        on_success: Callable[[object], None],
        on_error: Callable[[str], None],
    ) -> None:
        results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result = action()
            except (
                AuthenticationError, CredentialError, NetworkError,
                PortalError, ServiceError, OSError, ValueError,
            ) as exc:
                results.put((False, str(exc)))
            else:
                results.put((True, result))

        def poll() -> None:
            try:
                succeeded, value = results.get_nowait()
            except queue.Empty:
                self.root.after(50, poll)
                return
            if succeeded:
                on_success(value)
            else:
                on_error(str(value))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, poll)

    def _finish_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_text.set("操作失败")
        messagebox.showerror("操作失败", message, parent=self.root)
        self.refresh_status()

    def _finish_success(self, message: str) -> None:
        self.password.set("")
        self._set_busy(False)
        messagebox.showinfo("完成", message, parent=self.root)
        self.refresh_status()

    def save(self) -> None:
        try:
            credentials = self._credentials()
        except (CredentialError, KeyError) as exc:
            messagebox.showerror("登录信息无效", str(exc), parent=self.root)
            return
        self._run_async(lambda: save_credentials(credentials), "登录信息已保存。")

    def install(self) -> None:
        try:
            credentials = self._credentials()
            interface = self.interface.get().strip()
        except (CredentialError, KeyError) as exc:
            messagebox.showerror("登录信息无效", str(exc), parent=self.root)
            return

        def action() -> None:
            save_credentials(credentials)
            enable_linger()
            install_service(interface)

        self._run_async(action, "开机自启服务已安装并启用。")

    def uninstall(self) -> None:
        if not messagebox.askyesno("确认卸载", "确定要停用并卸载自动登录服务吗？", parent=self.root):
            return
        remove_credentials = self.remove_credentials.get()
        self._run_async(
            lambda: uninstall_service(remove_credentials=remove_credentials),
            "开机自启服务已卸载。",
        )

    def logout(self) -> None:
        if not messagebox.askyesno(
            "确认注销",
            "确定要注销当前校园网会话吗？自动登录定时器将暂停，重启后恢复。",
            parent=self.root,
        ):
            return
        interface = self.interface.get().strip()

        def action() -> None:
            timer_was_active = pause_service()
            try:
                CampusClient(interface=interface).logout()
            except Exception:
                if timer_was_active:
                    resume_service()
                raise

        self._run_async(action, "校园网会话已注销；正在运行的自动登录定时器已暂停。")

    @staticmethod
    def _format_status(status: ServiceStatus) -> str:
        if not status.installed:
            return "未安装"
        parts = ["定时器已启用" if status.enabled else "定时器未启用"]
        parts.append("正在运行" if status.active else "当前未运行")
        parts.append("支持开机启动" if status.linger else "尚未启用开机用户服务")
        return "；".join(parts)

    def refresh_status(self) -> None:
        self._set_busy(True)
        self.status_text.set("正在读取服务状态…")
        self._background(
            service_status,
            self._status_loaded,
            self._status_error,
        )

    def _status_loaded(self, value: object) -> None:
        if not isinstance(value, ServiceStatus):
            self._status_error("服务返回了无效状态")
            return
        self._status_ready(self._format_status(value))

    def _status_ready(self, value: str) -> None:
        self.status_text.set(value)
        self._set_busy(False)

    def _status_error(self, value: str) -> None:
        self.status_text.set("无法读取服务状态：" + value)
        self._set_busy(False)


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Cannot start GUI: {exc}", file=sys.stderr)
        return 1
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
