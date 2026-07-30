"""The write gate, tested the way the security guardrail is tested: adversarially.

WHY THIS FILE EXISTS
--------------------
`update_ticket` used to gate commits behind `confirm: bool`. An independent
review pointed out that this is caller policy, not a code gate — `confirm=true`
on a first call committed immediately, and the tool description asking the model
not to do that was a request. In a repo whose entire argument is that a safety
rule must live in the tool rather than the prompt, that was the one remaining
claim the code did not back.

So these tests are written from the position of a caller trying to commit a
change without producing a preview. Every one of them must fail to do so.

The asymmetry from the guardrail suite carries over: a test that lets an
unpreviewed write land is a failure of the whole file, regardless of how many
others pass.

WHAT THE GATE DOES NOT CLAIM
----------------------------
It does not prove a human read the preview. It proves a preview was issued by
this server and that the commit is byte-identical to it. Where the client
supports elicitation the server also asks the user; that path is tested here
too, including the case where they say no.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from msp_tools.confirmation import ConfirmationStore, Rejection, ticket_version
from msp_tools.models import ErrorCode
from msp_tools.server import get_ticket, update_ticket


def run(coro):
    return asyncio.run(coro)


# --- the core property ------------------------------------------------------

def test_no_token_never_commits() -> None:
    """The only way to reach the commit path is a token, and only a dry run mints one."""
    before = get_ticket("T-006").ticket
    r = run(update_ticket("T-006", status="pending"))
    assert r.applied is False
    assert r.error_code is ErrorCode.CONFIRMATION_REQUIRED
    assert get_ticket("T-006").ticket.status == before.status


def test_fabricated_token_is_refused() -> None:
    """A caller cannot construct a token, however plausible it looks."""
    before = get_ticket("T-007").ticket
    for fake in ("chg_" + "a" * 32, "true", "confirmed", ""):
        r = run(update_ticket("T-007", status="pending", confirmation_token=fake))
        assert r.applied is False, f"{fake!r} committed a write"
        assert get_ticket("T-007").ticket.status == before.status


def test_token_is_single_use() -> None:
    """Replaying a token must not commit a second time."""
    preview = run(update_ticket("T-008", note="first"))
    ok = run(update_ticket("T-008", note="first", confirmation_token=preview.confirmation_token))
    assert ok.applied is True

    replay = run(
        update_ticket("T-008", note="first", confirmation_token=preview.confirmation_token)
    )
    assert replay.applied is False
    assert replay.error_code is ErrorCode.CONFIRMATION_INVALID


def test_token_does_not_authorise_a_different_change() -> None:
    """The attack the binding exists to stop.

    Preview something innocuous, then try to spend that approval on something
    else. If this passed, the preview would be theatre: a user could approve a
    note and have a status change committed against their agreement.
    """
    before = get_ticket("T-009").ticket
    preview = run(update_ticket("T-009", note="just a note"))

    swapped = run(
        update_ticket("T-009", status="resolved", confirmation_token=preview.confirmation_token)
    )
    assert swapped.applied is False
    assert swapped.error_code is ErrorCode.CONFIRMATION_INVALID
    assert get_ticket("T-009").ticket.status == before.status


def test_token_does_not_carry_across_tickets() -> None:
    before = get_ticket("T-011").ticket
    preview = run(update_ticket("T-010", status="pending"))
    r = run(update_ticket("T-011", status="pending", confirmation_token=preview.confirmation_token))
    assert r.applied is False
    assert r.error_code is ErrorCode.CONFIRMATION_INVALID
    assert get_ticket("T-011").ticket.status == before.status


def test_same_values_still_need_their_own_preview() -> None:
    """Two identical edits are two decisions. One approval does not cover both."""
    first = run(update_ticket("T-012", note="ping"))
    run(update_ticket("T-012", note="ping", confirmation_token=first.confirmation_token))

    reuse = run(update_ticket("T-012", note="ping", confirmation_token=first.confirmation_token))
    assert reuse.applied is False


# --- store-level behaviour, with an injected clock --------------------------

def _triples(*changes: tuple[str, Any, Any]) -> list[tuple[str, Any, Any]]:
    return list(changes)


def test_expiry_is_enforced() -> None:
    now = [1000.0]
    store = ConfirmationStore(ttl_seconds=300.0, clock=lambda: now[0])
    changes = _triples(("status", "open", "pending"))
    token = store.issue("T-001", changes, "v1")

    now[0] += 301.0
    result = store.redeem(token, "T-001", changes, "v1", current_version="v1")
    assert result.ok is False
    assert result.rejection is Rejection.EXPIRED


def test_expired_token_reports_expired_not_unknown() -> None:
    """Regression. The first implementation swept expired tokens at the top of
    redeem(), which deleted the token being looked up and reported EXPIRED as
    UNKNOWN. Those imply different recovery — "your preview went stale" versus
    "that never existed" — and a caller that cannot tell them apart retries the
    wrong one."""
    now = [0.0]
    store = ConfirmationStore(ttl_seconds=10.0, clock=lambda: now[0])
    changes = _triples(("status", "open", "pending"))
    token = store.issue("T-001", changes, "v1")

    now[0] += 11.0
    assert store.redeem(token, "T-001", changes, "v1", "v1").rejection is Rejection.EXPIRED


def test_issue_sweeps_stale_entries() -> None:
    """Housekeeping lives on the issue path, so the store cannot grow without
    bound from previews nobody ever confirms."""
    now = [0.0]
    store = ConfirmationStore(ttl_seconds=10.0, clock=lambda: now[0])
    for i in range(5):
        store.issue(f"T-{i}", _triples(("tier", 1, 2)), "v1")
    now[0] += 11.0
    store.issue("T-fresh", _triples(("tier", 1, 2)), "v1")
    assert len(store) == 1


def test_stale_preview_is_refused_when_the_ticket_moved() -> None:
    """The user approved a before/after. If the ticket moved, that no longer
    describes reality, and committing would apply an approval to a state the
    approver never saw."""
    store = ConfirmationStore()
    changes = _triples(("tier", 1, 3))
    token = store.issue("T-001", changes, "v1")

    result = store.redeem(token, "T-001", changes, "v1", current_version="v2-someone-else-edited")
    assert result.ok is False
    assert result.rejection is Rejection.TICKET_MOVED


def test_mismatched_token_is_consumed_not_left_to_probe() -> None:
    """A rejected-but-genuine token must be burned, or a caller could hold one
    and try it against change sets until something validates."""
    store = ConfirmationStore()
    token = store.issue("T-001", _triples(("tier", 1, 2)), "v1")

    first = store.redeem(token, "T-001", _triples(("tier", 1, 3)), "v1", current_version="v1")
    assert first.rejection is Rejection.CHANGE_MISMATCH

    second = store.redeem(token, "T-001", _triples(("tier", 1, 2)), "v1", current_version="v1")
    assert second.rejection is Rejection.UNKNOWN


def test_ticket_version_tracks_only_mutable_state() -> None:
    base = {"status": "open", "tier": 1, "priority": "low", "assignee": None, "subject": "x"}
    assert ticket_version(base) == ticket_version({**base, "subject": "rewritten"})
    assert ticket_version(base) != ticket_version({**base, "status": "resolved"})
    assert ticket_version(base) != ticket_version({**base, "notes": ["added"]})


# --- elicitation path -------------------------------------------------------

@dataclass
class _Answer:
    action: str
    data: Any = None


class _Approve:
    approve = True


class _Reject:
    approve = False


class _FakeSession:
    def __init__(self, supports: bool):
        self._supports = supports

    def check_client_capability(self, _capability) -> bool:
        return self._supports


class _FakeContext:
    """Stands in for an elicitation-capable client. No transport, no network."""

    def __init__(self, supports: bool = True, action: str = "accept", approve: bool = True):
        self.session = _FakeSession(supports)
        self._action = action
        self._approve = approve
        self.prompts: list[str] = []

    async def elicit(self, message: str, schema):
        self.prompts.append(message)
        return _Answer(self._action, _Approve() if self._approve else _Reject())


class _ExplodingContext(_FakeContext):
    async def elicit(self, message: str, schema):
        raise RuntimeError("client went away mid-prompt")


def test_declining_the_prompt_blocks_the_write() -> None:
    before = get_ticket("T-013").ticket
    preview = run(update_ticket("T-013", status="resolved"))
    ctx = _FakeContext(supports=True, approve=False)

    r = run(
        update_ticket(
            "T-013",
            status="resolved",
            confirmation_token=preview.confirmation_token,
            ctx=ctx,
        )
    )
    assert r.applied is False
    assert r.error_code is ErrorCode.CONFIRMATION_DECLINED
    assert get_ticket("T-013").ticket.status == before.status
    assert ctx.prompts and "T-013" in ctx.prompts[0]


def test_cancelling_the_prompt_blocks_the_write() -> None:
    before = get_ticket("T-014").ticket
    preview = run(update_ticket("T-014", status="resolved"))
    r = run(
        update_ticket(
            "T-014",
            status="resolved",
            confirmation_token=preview.confirmation_token,
            ctx=_FakeContext(action="cancel"),
        )
    )
    assert r.applied is False
    assert r.error_code is ErrorCode.CONFIRMATION_DECLINED
    assert get_ticket("T-014").ticket.status == before.status


def test_approval_commits_and_reports_the_stronger_mode() -> None:
    preview = run(update_ticket("T-015", tier=3))
    r = run(update_ticket("T-015", tier=3, confirmation_token=preview.confirmation_token, ctx=_FakeContext()))
    assert r.applied is True
    assert r.confirmation_method == "user_elicitation"
    # The stronger mode must not carry the weaker mode's disclaimer.
    assert "does not support elicitation" not in (r.message or "")
    assert get_ticket("T-015").ticket.tier == 3


def test_client_without_elicitation_gets_the_weaker_mode_disclosed() -> None:
    preview = run(update_ticket("T-016", tier=2))
    r = run(
        update_ticket(
            "T-016",
            tier=2,
            confirmation_token=preview.confirmation_token,
            ctx=_FakeContext(supports=False),
        )
    )
    assert r.applied is True
    assert r.confirmation_method == "token_only"
    assert "could not ask anyone to approve it" in (r.message or "")


def test_elicitation_failure_fails_closed() -> None:
    """A broken confirmation channel must never be the reason a write lands.

    And it must not be reported as a bad token. A caller told CONFIRMATION_INVALID
    mints a fresh token and retries straight into the same failure; the distinct
    code tells it the retry is pointless.
    """
    before = get_ticket("T-017").ticket
    preview = run(update_ticket("T-017", status="resolved"))
    r = run(
        update_ticket(
            "T-017",
            status="resolved",
            confirmation_token=preview.confirmation_token,
            ctx=_ExplodingContext(),
        )
    )
    assert r.applied is False
    assert r.error_code is ErrorCode.CONFIRMATION_UNAVAILABLE
    assert get_ticket("T-017").ticket.status == before.status


# --- the description must not outrun the code -------------------------------

def test_tool_description_does_not_promise_human_review() -> None:
    """The failure mode this whole item exists to fix was a description claiming
    a guarantee the code did not provide. Guard against reintroducing it."""
    from msp_tools.server import mcp  # noqa: PLC0415

    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "update_ticket")
    desc = tool.description or ""
    assert "confirm=true" not in desc, "description still references the removed boolean"
    assert "token_only" in desc, "description must explain the weaker mode"
    assert "Does not prove a human read the preview" in desc


def test_confirm_boolean_is_gone_from_the_schema() -> None:
    """A caller-set boolean cannot gate anything. Its absence is the fix."""
    from msp_tools.server import mcp  # noqa: PLC0415

    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "update_ticket")
    props = tool.inputSchema.get("properties", {})
    assert "confirm" not in props
    assert "confirmation_token" in props
    # Context is injected by the framework, never supplied by the caller.
    assert "ctx" not in props
