"""Discover route-preferred interfaces and validate their IPv4 routing."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import subprocess
import sys
import threading
import time

from .errors import NetworkError


WINDOWS_NETWORK_CACHE_SECONDS = 5.0
_WINDOWS_NETWORK_CACHE: tuple[float, list[dict[str, str]]] | None = None
_WINDOWS_NETWORK_LOCK = threading.Lock()
# Note 1: Route discovery is expensive on Windows because it starts PowerShell.
# The short cache covers one GUI refresh without hiding long-lived route changes.
# A monotonic timestamp is used because wall-clock corrections must not extend it.
# Copies leave the cache so callers cannot mutate the shared snapshot by accident.
# The lock also prevents simultaneous GUI tasks from launching duplicate queries.


def _powershell_json(script: str, error: str) -> object:
    """Run a non-interactive PowerShell query and decode its UTF-8 JSON result."""
# Note 2: EncodedCommand avoids quoting rules from two different command shells.
# PowerShell expects its encoded command as UTF-16LE, not UTF-8.
# Explicit UTF-8 output makes non-ASCII Windows interface aliases round-trip.
# NonInteractive and NoProfile keep local profiles from changing query behavior.
# The public error is stable while the original exception remains as its cause.
    encoded = base64.b64encode(
        (
            "$ProgressPreference='SilentlyContinue';"
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            + script
        ).encode("utf-16le")
    ).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            check=True,
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return json.loads(result.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NetworkError(error) from exc


def _windows_network_snapshot() -> list[dict[str, str]]:
    """Read route aliases and addresses once for one short GUI refresh cycle."""
# Note 3: This function captures route preference and address choice together.
# Splitting those queries could pair an old route with a newly assigned address.
# Holding the lock across the query favors consistency over parallel PowerShell.
# The query timeout bounds how long that deliberate serialization can last.
    global _WINDOWS_NETWORK_CACHE
    with _WINDOWS_NETWORK_LOCK:
        now = time.monotonic()
        if _WINDOWS_NETWORK_CACHE is not None:
            recorded, cached = _WINDOWS_NETWORK_CACHE
            if now - recorded < WINDOWS_NETWORK_CACHE_SECONDS:
                return [item.copy() for item in cached]
# Note 4: Find-NetRoute captures the route Windows gives to unbound applications.
# RouteMetric and InterfaceMetric order the remaining fallback candidates.
# Link-local and duplicate addresses cannot support the portal request path.
# Preferred addresses sort ahead of transitional addresses on the same adapter.
# De-duplication keeps one candidate per user-visible interface alias.
        script = r"""
$preferred = Find-NetRoute -RemoteIPAddress '1.1.1.1' -ErrorAction SilentlyContinue |
    Where-Object { $_.DestinationPrefix } |
    Select-Object -First 1 -ExpandProperty InterfaceAlias
$routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
    Where-Object { $_.InterfaceAlias -and $_.InterfaceAlias -ne 'Loopback Pseudo-Interface 1' } |
    Sort-Object @{Expression={$_.RouteMetric + $_.InterfaceMetric}}, ifIndex)
$seen = @{}
$items = @()
foreach ($route in $routes) {
    $name = [string]$route.InterfaceAlias
    if ($seen.ContainsKey($name)) { continue }
    $seen[$name] = $true
    $address = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $name -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.AddressState -ne 'Duplicate' } |
        Sort-Object @{Expression={if ($_.AddressState -eq 'Preferred') { 0 } else { 1 }}}, PrefixLength |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($address) { $items += [pscustomobject]@{name=$name; address=[string]$address} }
}
ConvertTo-Json -Compress -InputObject ([pscustomobject]@{preferred=[string]$preferred; items=@($items)})
"""
        value = _powershell_json(script, "cannot inspect default routes")
        if not isinstance(value, dict):
            raise NetworkError("cannot inspect default routes")
        preferred = value.get("preferred")
        raw_items = value.get("items")
        values = [raw_items] if isinstance(raw_items, dict) else raw_items
# Note 5: ConvertTo-Json returns an object for one item and an array for many.
# Normalizing both shapes here keeps the public API consistently list-based.
# Every field is checked before entering the cache because later code trusts it.
# An empty snapshot is an operational network error, not a valid empty result.
# Validation here prevents obscure type failures in interface selection later.
        if not isinstance(values, list):
            raise NetworkError("cannot inspect default routes")
        snapshot: list[dict[str, str]] = []
        for item in values:
            if not isinstance(item, dict):
                raise NetworkError("cannot inspect default routes")
            name, address = item.get("name"), item.get("address")
            if not isinstance(name, str) or not isinstance(address, str):
                raise NetworkError("cannot inspect default routes")
            snapshot.append({"name": name, "address": address})
        if not snapshot:
            raise NetworkError("no IPv4 default-route interface is available")
        if isinstance(preferred, str) and preferred:
            snapshot.sort(key=lambda item: item["name"] != preferred)
        _WINDOWS_NETWORK_CACHE = (now, snapshot)
        return [item.copy() for item in snapshot]


def default_interfaces() -> list[str]:
    """Return unique IPv4 default-route interfaces in routing preference order."""
# Note 6: Only default-route interfaces are candidates for Internet login.
# This excludes host-only and loopback links that should never carry credentials.
# Linux keeps command output order as a stable tie-break after route metric.
# dict.fromkeys removes repeated routes without changing the preferred order.
# Missing metrics behave like metric zero, matching the kernel's usual default.
    if sys.platform == "win32":
        return [item["name"] for item in _windows_network_snapshot()]
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "route", "show", "default"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkError("cannot inspect default routes") from exc
    candidates: list[tuple[int, int, str]] = []
    for order, line in enumerate(result.stdout.splitlines()):
        device = re.search(r"\bdev (\S+)", line)
        if not device or device.group(1) == "lo":
            continue
        metric = re.search(r"\bmetric (\d+)", line)
        candidates.append((int(metric.group(1)) if metric else 0, order, device.group(1)))
    interfaces = list(dict.fromkeys(interface for _metric, _order, interface in sorted(candidates)))
    if not interfaces:
        raise NetworkError("no IPv4 default-route interface is available")
    return interfaces


def interface_ip(interface: str) -> str:
    """Return the selected interface's preferred non-link-local IPv4 address."""
# Note 7: Parsing through IPv4Address validates input and normalizes its spelling.
# The address must belong to the same snapshot used for Windows route selection.
# Linux asks iproute2 for only the named device to avoid choosing another NIC.
# A missing address fails closed before any portal credential can be submitted.
    if sys.platform == "win32":
        for item in _windows_network_snapshot():
            if item["name"] == interface:
                try:
                    return str(ipaddress.IPv4Address(item["address"]))
                except ValueError as exc:
                    raise NetworkError("campus interface has no valid IPv4 address") from exc
        raise NetworkError("campus interface has no IPv4 address")
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", interface],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkError("cannot inspect the campus interface") from exc
    match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)/", result.stdout)
    if not match:
        raise NetworkError("campus interface has no IPv4 address")
    return str(ipaddress.IPv4Address(match.group(1)))


def require_route(interface: str, local_ip: str, destination: str) -> None:
    """Reject an interface when the OS would route a destination elsewhere."""
# Note 8: Source and output-interface constraints test the exact intended path.
# This guards multi-homed hosts where the ordinary default route uses another NIC.
# Windows already derives candidates from a combined default-route snapshot.
# Linux can ask the kernel for a destination-specific route, so it does so here.
# The check is separate from socket binding because both express useful invariants.
    if sys.platform == "win32":
        if interface not in default_interfaces():
            raise NetworkError("default internet route does not use the campus interface")
        return
    try:
        result = subprocess.run(
            ["ip", "-4", "route", "get", destination, "from", local_ip, "oif", interface],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkError("cannot inspect the campus route") from exc
    match = re.search(r"\bdev (\S+)", result.stdout)
    if not match or match.group(1) != interface:
        raise NetworkError("default internet route does not use the campus interface")


def valid_interface_name(interface: str) -> bool:
    """Allow user-visible interface aliases while rejecting control characters."""
# Note 9: Windows aliases may contain spaces, so a shell-style token rule is wrong.
# The value is passed as process data rather than interpolated into a shell command.
# Rejecting control characters keeps logs, configuration, and command output intact.
# The length cap prevents unreasonable values from crossing platform boundaries.
    return bool(interface and len(interface) <= 256 and not any(ord(char) < 32 for char in interface))
