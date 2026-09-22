"""GUI actions that can be tested without loading the platform UI toolkit."""

from __future__ import annotations

from collections.abc import Callable

from .client import CampusClient, NetworkError
from .credentials import Credentials, save_credentials
from .service import ServiceStatus


def login_now(interface: str, credential_factory: Callable[[], Credentials]) -> str:
    """Log in only when no existing NJUPT session can be found."""
    online_interface = CampusClient.online_campus_interface()
    if online_interface:
        return f"校园网已经在线（接口 {online_interface}），未重复提交登录。"
    client = CampusClient(interface=interface, prefer_portal=True)
    current = client.authentication_status()
    if current.state == "internet_ok":
        return f"网络已经在线（接口 {client.interface}），未重复提交登录。"
    if current.state != "portal_detected":
        raise NetworkError(f"cannot authenticate from state {current.state}")
    credentials = credential_factory()
    result = client.login(credentials)
    if result == "login_success":
        save_credentials(credentials)
        return f"校园网登录成功（接口 {client.interface}）。"
    return f"校园网已经在线（接口 {client.interface}）。"


def service_status_items(status: ServiceStatus) -> tuple[tuple[str, str], ...]:
    """Map service state to the three concise values used by the native UI."""
    if not status.installed:
        return (
            ("未安装", "muted"),
            ("未启用", "muted"),
            ("已启用" if status.linger else "未启用", "success" if status.linger else "muted"),
        )
    timer = "运行中" if status.active else ("已启用" if status.enabled else "未启用")
    return (
        ("已安装", "success"),
        (timer, "success" if status.active else "warning" if status.enabled else "muted"),
        ("已启用" if status.linger else "未启用", "success" if status.linger else "warning"),
    )
