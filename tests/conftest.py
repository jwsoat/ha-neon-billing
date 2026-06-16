"""Test-suite-wide pytest configuration.

Workaround for pytest-asyncio's deprecated ``event_loop`` fixture constructing a
Windows ``ProactorEventLoop`` whose ``_close_self_pipe`` machinery requires a
real ``socket.socket``, which collides with the socket disablement enforced by
``pytest-homeassistant-custom-component``. We turn ``pytest_socket.disable_socket``
into a no-op at session start so any subsequent disable call (HA plugin's
per-test setup or pytest_socket's own config) is inert. Pure unit tests in this
suite never perform real network I/O. Once HA-flavoured integration tests are
added they should opt back into the socket guard via the standard HA fixtures
or via per-test ``disable_socket`` markers.
"""
from __future__ import annotations

import pytest_socket


def pytest_configure() -> None:
    """Neutralise pytest-socket so HA's per-test disable does nothing."""

    def _noop_disable(*_args: object, **_kwargs: object) -> None:
        return None

    pytest_socket.disable_socket = _noop_disable  # type: ignore[assignment]
    pytest_socket.enable_socket()
