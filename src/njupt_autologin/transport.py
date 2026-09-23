"""Small HTTP transport whose sockets stay on one selected IPv4 interface."""

from __future__ import annotations

import http.client
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import NetworkError, PortalError


MAX_RESPONSE = 262_144


@dataclass(frozen=True)
class Response:
# Note 1: This small value object prevents protocol code from owning a live socket.
# Only fields used by portal decisions cross the transport boundary.
# Freezing the object makes captured network evidence safe to share between checks.
# The bounded body remains bytes so each protocol parser chooses its own decoding.
    status: int
    content_type: str
    location: str
    body: bytes


class BoundHttpTransport:
    """Issue HTTP requests through one interface without changing global routes."""
# Note 2: Binding is per request and never rewrites the machine's routing table.
# That matters when a management interface must stay reachable during login.
# The selected source address and device together constrain multi-homed routing.
# Keeping timeout state here gives every DNS, connect, and HTTP step one policy.
# Portal protocol code can now be tested without duplicating socket mechanics.

    def __init__(self, interface: str, local_ip: str, timeout: float) -> None:
        self.interface = interface
        self.local_ip = local_ip
        self.timeout = timeout

    def request(
        self,
        host: str,
        port: int,
        path: str,
        *,
        secure: bool = True,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
# Note 3: http.client retains standard framing, TLS verification, and header parsing.
# Only socket creation is replaced because the standard API lacks a public hook.
# Assigning the instance hook limits this private API dependency to one module.
# HTTPS still uses the default trust store and verifies the requested host name.
# The connection closes in all paths so repeated probes do not leak descriptors.
        try:
            connection_type = http.client.HTTPSConnection if secure else http.client.HTTPConnection
            options: dict[str, object] = {"timeout": self.timeout}
            if secure:
                options["context"] = ssl.create_default_context()
            connection = connection_type(host, port, **options)
            # http.client has no public socket-factory hook. Replacing this hook
            # keeps its HTTP/TLS implementation while enforcing interface binding.
            connection._create_connection = self._open_socket
            try:
                connection.request("GET", path, headers=dict(headers or {}))
                response = connection.getresponse()
                body = response.read(MAX_RESPONSE + 1)
# Note 4: Reading one extra byte distinguishes an exact limit from an overflow.
# A hard cap prevents a broken portal from consuming memory without bound.
# Login failures expose only exception types because request paths may hold secrets.
# The original low-level message is intentionally omitted from the public error.
                if len(body) > MAX_RESPONSE:
                    raise PortalError("portal response exceeds the size limit")
                return Response(
                    status=response.status,
                    content_type=response.getheader("Content-Type", ""),
                    location=response.getheader("Location", ""),
                    body=body,
                )
            finally:
                connection.close()
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            # Some low-level exception strings contain the requested URL. Portal
            # login URLs contain secrets, so expose only the exception type.
            raise NetworkError(f"request failed ({type(exc).__name__})") from None

    def _open_socket(
        self,
        address: tuple[str, int],
        timeout: object = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
# Note 5: getaddrinfo is restricted to IPv4 to match route and source validation.
# Each candidate gets a new socket because a failed connect may poison that socket.
# SO_BINDTODEVICE is applied where the platform supports it.
# Source-address binding is still required when device binding is unavailable.
# The kernel chooses an ephemeral source port after the address is constrained.
# Failed candidates close immediately, preventing descriptor growth during retries.
# Re-raising the last error preserves its useful category for request translation.
        del timeout, source_address
        last_error: OSError | None = None
        for family, socktype, protocol, _canonname, sockaddr in socket.getaddrinfo(
            address[0], address[1], socket.AF_INET, socket.SOCK_STREAM
        ):
            connection = socket.socket(family, socktype, protocol)
            try:
                connection.settimeout(self.timeout)
                if hasattr(socket, "SO_BINDTODEVICE"):
                    connection.setsockopt(
                        socket.SOL_SOCKET,
                        socket.SO_BINDTODEVICE,
                        self.interface.encode() + b"\0",
                    )
                connection.bind((self.local_ip, 0))
                connection.connect(sockaddr)
                return connection
            except OSError as exc:
                last_error = exc
                connection.close()
        if last_error is not None:
            raise last_error
        raise OSError("no IPv4 address found for destination")
