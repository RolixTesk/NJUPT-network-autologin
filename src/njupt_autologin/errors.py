"""Shared exception types for network, portal, and credential-safe failures."""


class NetworkError(RuntimeError):
    """The operating system or remote network could not complete an operation."""


class PortalError(RuntimeError):
    """The remote portal response did not match the supported protocol."""


class AuthenticationError(RuntimeError):
    """The portal rejected or failed to establish an authenticated session."""
