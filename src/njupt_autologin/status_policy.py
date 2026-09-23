"""Pure policy for reconciling portal session and connectivity evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkStatus:
# Note 1: Status is immutable evidence, not a command to change the connection.
# Optional HTTP and portal fields preserve context for both CLI and GUI rendering.
# String states remain compatible with the existing public output format.
    state: str
    http_status: int | None = None
    portal_host: str | None = None


def status_with_session(
    connectivity: NetworkStatus,
    session: str,
    external_access: Callable[[], NetworkStatus],
    *,
    portal_host: str,
) -> NetworkStatus:
    """Resolve conflicting evidence without trusting a captive-portal allowlist."""
# Note 2: Captive portals may allow selected connectivity probes before login.
# A second ordinary HTTPS check makes that single allowlisted response insufficient.
# The external callback is lazy, so slower HTTPS work runs only after a 204 success.
# A working 204 plus ordinary HTTPS path is stronger than stale Portal bookkeeping.
# Portal offline still identifies the login page when either real check is blocked.
# Keeping this policy pure makes every evidence combination cheap to unit test.
    if connectivity.state == "internet_ok":
        external = external_access()
        if external.state == "internet_ok":
            return external
        if session == "offline":
            return NetworkStatus("portal_detected", connectivity.http_status, portal_host)
        return external
    if session == "offline":
        return NetworkStatus("portal_detected", connectivity.http_status, portal_host)
    return connectivity
