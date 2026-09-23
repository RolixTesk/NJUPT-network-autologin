"""GUI actions that can be tested without loading the platform UI toolkit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .client import CampusClient
from .credentials import Credentials, save_credentials
from .operations import login_once
from .platform_services.base import ServiceStatus


@dataclass(frozen=True)
class ConnectionSnapshot:
    state: str
    interface: str
    online_interfaces: tuple[str, ...]


def connection_status(interface: str) -> ConnectionSnapshot:
    """Read campus authentication and external connectivity without credentials."""
    online = tuple(CampusClient.online_campus_interfaces())
    if online:
        return ConnectionSnapshot("campus_online", online[0], online)
    client = CampusClient(interface=interface, prefer_portal=True)
    current = client.authentication_status()
    state = "internet_only" if current.state == "internet_ok" else current.state
    return ConnectionSnapshot(state, client.interface, ())


def connection_status_text(snapshot: ConnectionSnapshot) -> tuple[str, str, str]:
    """Map a connection snapshot to title, detail, and semantic color."""
    if snapshot.state == "campus_online":
        return "校园网已登录", f"接口 {snapshot.interface} 已认证，外部网络可访问。", "success"
    if snapshot.state == "internet_only":
        return "网络可用", f"接口 {snapshot.interface} 可访问外网，未确认校园网会话。", "warning"
    if snapshot.state == "portal_detected":
        return "等待校园网登录", f"接口 {snapshot.interface} 已连接，但尚未通过校园网认证。", "warning"
    if snapshot.state == "network_unavailable":
        return "网络不可用", f"接口 {snapshot.interface} 暂时无法访问校园网或外部网络。", "error"
    return "连接状态异常", f"接口 {snapshot.interface} 返回了无法识别的网络状态。", "error"


def login_now(interface: str, credential_factory: Callable[[], Credentials]) -> str:
    """Log in only when no existing NJUPT session can be found."""
    outcome = login_once(interface, credential_factory)
    if outcome.state == "login_success":
        if outcome.credentials is None:
            raise RuntimeError("login outcome omitted the credentials used")
        save_credentials(outcome.credentials)
        return f"校园网登录成功（接口 {outcome.interface}）。"
    return f"校园网已经在线（接口 {outcome.interface}），未重复提交登录。"


def service_status_items(status: ServiceStatus) -> tuple[tuple[str, str], ...]:
    """Map service state to the three concise values used by the native UI."""
    if not status.installed:
        return (
            ("未安装", "muted"),
            ("未启用", "muted"),
            (
                "已启用" if status.startup_ready else "未启用",
                "success" if status.startup_ready else "muted",
            ),
        )
    timer = "运行中" if status.active else ("已启用" if status.enabled else "未启用")
    return (
        ("已安装", "success"),
        (timer, "success" if status.enabled else "warning"),
        (
            "已启用" if status.startup_ready else "未启用",
            "success" if status.startup_ready else "warning",
        ),
    )
