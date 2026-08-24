"""Shared fixtures: a frozen clock, a canonical test generator, and a socket guard.

Determinism is a testing standard, not a preference
(testing standards §4). Two rules bite in this package specifically:

* **No test reads the wall clock.** Every timestamp comes from :func:`frozen_clock` or
  :func:`fixed_now`, so a canonical-output assertion compares bytes rather than hoping two calls
  land in the same millisecond.
* **No test opens a socket.** SetSpec has no network code at all, so a connection attempt means a
  dependency grew one; the guard turns that into a failure rather than a slow test.

The standards also ask for a guard against naive ``datetime.now()`` calls. Here that is ruff's
``DTZ`` rule set, enabled in ``pyproject.toml`` and enforced in CI: this package never calls a
clock outside an injected ``Clock`` parameter, so a static check catches the mistake at the point
it is written rather than the moment it happens to run.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest

from setspec import GeneratorInfo

if TYPE_CHECKING:
    from collections.abc import Iterator

    from baseaicore import Clock

# A fixed instant with a non-zero millisecond component, so truncation bugs show up as a changed
# string rather than hiding behind a round number.
_FIXED_INSTANT: Final[datetime] = datetime(2026, 8, 22, 14, 3, 11, 250_000, tzinfo=UTC)


@pytest.fixture
def fixed_now() -> datetime:
    """Return the instant every test in this suite treats as "now"."""
    return _FIXED_INSTANT


@pytest.fixture
def frozen_clock(fixed_now: datetime) -> Clock:
    """Return a :data:`baseaicore.Clock` that always reports :func:`fixed_now`."""
    return lambda: fixed_now


@pytest.fixture
def generator() -> GeneratorInfo:
    """Return the generator identity used by documents built in tests."""
    return GeneratorInfo(name="setspec", version="0.1.0")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail any test that opens a real socket.

    SetSpec is a schema package: it parses bytes it is handed and never fetches anything, and its
    JSON Schema documents are static package data rather than remote references (spec §14). A
    socket therefore means either a new dependency reaching out or a test that stopped being a
    unit test, and both are worth failing on.
    """

    def _refuse(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(
            "A test tried to open a network connection. SetSpec performs no I/O; if a dependency "
            "now does, that is the thing to investigate rather than to allow here."
        )

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    yield
