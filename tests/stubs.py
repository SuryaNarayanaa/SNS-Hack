from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


@dataclass
class StubConnection:
    """Lightweight asyncpg.Connection stub for tests."""

    fetch_results: List[Any] = field(default_factory=list)
    fetchrow_results: List[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fetch_results = _ensure_list(self.fetch_results)
        self.fetchrow_results = _ensure_list(self.fetchrow_results)
        self.fetch_calls: List[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: List[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: List[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    async def fetch(self, query: str, *params: Any) -> Any:
        self.fetch_calls.append((query, params))
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []

    async def fetchrow(self, query: str, *params: Any) -> Any:
        self.fetchrow_calls.append((query, params))
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def execute(self, query: str, *params: Any) -> None:
        self.execute_calls.append((query, params))

    async def close(self) -> None:
        self.closed = True
