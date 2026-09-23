"""Application use cases shared by command-line and desktop front ends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .client import CampusClient
from .credentials import Credentials
from .errors import NetworkError


@dataclass(frozen=True)
class LoginOutcome:
# Note 1: Front ends receive one neutral result instead of duplicating login policy.
# The chosen interface is returned because automatic selection may change the input.
# Credentials are hidden from repr so accidental diagnostic output omits secrets.
# They are returned only after success, allowing the GUI to save confirmed values.
    state: str
    interface: str
    credentials: Credentials | None = field(default=None, repr=False)


def login_once(
    interface: str,
    credential_factory: Callable[[], Credentials],
    *,
    timeout: float = 10.0,
    force: bool = False,
) -> LoginOutcome:
    """Authenticate only when no suitable existing session can be reused."""
# Note 2: The global session check protects limited campus device allocations.
# Force skips only that global guard; it does not repeat login on an online NIC.
# The credential callback delays secret access until authentication is necessary.
# That delay also lets CLI and GUI share policy without sharing storage details.
    if not force:
        online_interface = CampusClient.online_campus_interface(timeout)
        if online_interface:
            return LoginOutcome("already_online", online_interface)

    client = CampusClient(interface=interface, timeout=timeout, prefer_portal=force)
    current = client.authentication_status()
# Note 3: The selected interface is assessed once before any credential is loaded.
# Passing this evidence to login removes a duplicate set of network probes.
# The protocol layer still checks the portal session immediately before submission.
# This split improves latency without weakening the final credential-safety boundary.
    if current.state == "internet_ok":
        return LoginOutcome("already_online", client.interface)
    if current.state != "portal_detected":
        raise NetworkError(f"cannot authenticate from state {current.state}")

    # Reading the secret is deliberately delayed until the selected interface is
    # known to require authentication. The login method reuses this assessment,
    # while its protocol request still verifies that the portal reports offline.
    credentials = credential_factory()
    state = client.login(credentials, initial_status=current)
    return LoginOutcome(state, client.interface, credentials if state == "login_success" else None)
