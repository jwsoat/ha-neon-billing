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

If ``pytest_socket`` is not installed (it ships transitively via
``pytest-homeassistant-custom-component``; not pinned directly in our dev
deps) the workaround silently no-ops — no other code in this repo relies on
it.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from custom_components.neon_billing.api import NeonClient


def pytest_configure() -> None:
    """Neutralise pytest-socket so HA's per-test disable does nothing.

    Also strips any non-filesystem entries (e.g. editable-install path hooks
    like ``__editable__.ha_neon_billing-0.1.0.finder.__path_hook__``) from the
    ``custom_components`` namespace ``__path__`` so HA's loader, which iterates
    the path with ``pathlib.Path.iterdir``, doesn't choke on them.
    """
    try:
        import pytest_socket
    except ImportError:
        pass
    else:
        def _noop_disable(*_args: object, **_kwargs: object) -> None:
            return None

        pytest_socket.disable_socket = _noop_disable  # type: ignore[assignment]
        pytest_socket.enable_socket()

    import os

    import custom_components

    # _NamespacePath supports list-like mutation; rebuild it as a plain list of
    # real, deduplicated directories so HA's _get_custom_components walk works.
    real_paths: list[str] = []
    seen: set[str] = set()
    for entry in list(custom_components.__path__):
        if not isinstance(entry, str):
            continue
        if not os.path.isdir(entry):
            continue
        norm = os.path.normcase(os.path.abspath(entry))
        if norm in seen:
            continue
        seen.add(norm)
        real_paths.append(entry)
    custom_components.__path__ = real_paths  # type: ignore[assignment]


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
async def neon_client(http_client: httpx.AsyncClient) -> NeonClient:
    return NeonClient(http=http_client, api_key="test-key")
