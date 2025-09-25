from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from tests.stubs import StubConnection


@pytest.fixture
def make_db_session(monkeypatch: pytest.MonkeyPatch):
    """Patch a module's db_session to use a stub connection."""

    def _maker(module: Any, connection: StubConnection) -> StubConnection:
        class _Session:
            async def __aenter__(self_inner) -> StubConnection:  # type: ignore[misc]
                return connection

            async def __aexit__(self_inner, exc_type, exc, tb) -> None:
                await connection.close()

        monkeypatch.setattr(module, "db_session", lambda: _Session())
        return connection

    return _maker


@pytest.fixture
def frozen_now() -> datetime:
    return datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def patch_now(monkeypatch: pytest.MonkeyPatch, frozen_now: datetime):
    def _apply(module: Any, dt: datetime = frozen_now) -> datetime:
        monkeypatch.setattr(module, "_now", lambda: dt)
        return dt

    return _apply
