"""Data-source adapter — the only way tickets reach the tools.

Carried over from Project 1's rule: nothing outside this module may assume
tickets come from a JSON file. The live Freshdesk adapter slots in here by
implementing the same Protocol, and no tool changes.

This is also why the security guardrail cannot key off the grader's `expected`
block: that field is an artifact of one adapter. A guardrail is only real if it
survives the adapter swap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class DataSource(Protocol):
    def load_tickets(self) -> list[dict]: ...

    def save_ticket(self, ticket: dict) -> None: ...


class LocalJSONDataSource:
    """Serves the synthetic Summit Managed IT queue from a JSON file on disk.

    Writes are held in memory for the life of the process. `update_ticket` is a
    demonstration of a state-changing tool with a confirmation gate, not a
    persistence layer — a synthetic store that rewrites itself on disk would
    make the eval suite non-reproducible.
    """

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._cache: list[dict] | None = None

    def load_tickets(self) -> list[dict]:
        if self._cache is None:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._cache = data["tickets"]
        return self._cache

    def save_ticket(self, ticket: dict) -> None:
        tickets = self.load_tickets()
        for i, existing in enumerate(tickets):
            if existing["ticket_id"] == ticket["ticket_id"]:
                tickets[i] = ticket
                return
        raise KeyError(ticket["ticket_id"])
