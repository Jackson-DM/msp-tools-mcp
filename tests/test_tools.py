"""Tool-level tests: filters, error paths, grounding hygiene, the write gate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from msp_tools.models import ErrorCode
from msp_tools.server import (
    draft_response,
    get_ticket,
    search_kb,
    search_tickets,
    update_ticket,
)

REPO = Path(__file__).resolve().parent.parent
SECURITY_TICKETS = {"T-018", "T-019", "T-022", "T-023", "T-024", "T-026"}

# Staff-facing articles. KB-006 is incident-response policy, KB-000 is the
# triage priority matrix — neither is customer-facing prose.
INTERNAL_ARTICLES = {"KB-000", "KB-006"}


def run(coro):
    """Drive an async tool from a sync test.

    `update_ticket` is async because it may call ctx.elicit(). Rather than take a
    dependency on pytest-asyncio for one tool, tests drive the coroutine
    directly — explicit, and it keeps the dev requirements at pytest alone.
    """
    return asyncio.run(coro)


def _tickets() -> list[dict]:
    return json.loads((REPO / "data" / "tickets.json").read_text(encoding="utf-8"))["tickets"]


# --- search_tickets ---------------------------------------------------------

def test_search_returns_summaries_without_bodies() -> None:
    r = search_tickets(limit=5)
    assert r.ok and r.returned == 5
    assert not hasattr(r.tickets[0], "body")


def test_filters_and_together() -> None:
    r = search_tickets(status="open", client="Bayline", limit=25)
    assert all(t.status == "open" and "bayline" in t.client.lower() for t in r.tickets)


def test_empty_result_is_not_an_error() -> None:
    """No match is a fact about the queue, not a failure to recover from."""
    r = search_tickets(client="Nonexistent Corp")
    assert r.ok is True and r.total_matched == 0 and r.error_code is None


def test_truncation_is_reported() -> None:
    r = search_tickets(limit=3)
    assert r.returned == 3 and r.truncated is True and r.total_matched > 3


def test_limit_is_capped() -> None:
    r = search_tickets(limit=9999)
    assert r.returned <= 25


# --- get_ticket -------------------------------------------------------------

def test_get_ticket_returns_body() -> None:
    r = get_ticket("T-001")
    assert r.ok and r.ticket is not None and r.ticket.body


def test_get_ticket_id_is_case_insensitive() -> None:
    assert get_ticket("t-001").ok is True


def test_get_ticket_unknown_id() -> None:
    r = get_ticket("T-999")
    assert r.ok is False and r.error_code is ErrorCode.TICKET_NOT_FOUND


# --- search_kb --------------------------------------------------------------

def test_search_kb_ranks_the_right_article() -> None:
    r = search_kb("account lockout reset", limit=3)
    assert r.ok and r.excerpts[0].article_id == "KB-001"


def test_search_kb_no_match_is_typed() -> None:
    r = search_kb("xyzzy plugh nonexistent")
    assert r.ok is False and r.error_code is ErrorCode.KB_NO_MATCH


def test_search_kb_still_serves_internal_policy() -> None:
    """Technicians must be able to look up escalation policy directly."""
    r = search_kb("security incident escalation", limit=3)
    assert r.ok and any(e.article_id == "KB-006" for e in r.excerpts)


# --- draft grounding hygiene ------------------------------------------------

@pytest.mark.parametrize(
    "ticket_id", [t["ticket_id"] for t in _tickets() if t["ticket_id"] not in SECURITY_TICKETS]
)
def test_drafts_never_ground_in_internal_articles(ticket_id: str) -> None:
    """A customer reply must not quote staff policy.

    Regression: the lockout draft once opened with KB-006's "Treat as a
    security incident" checklist, because that block contains the words
    "account lockout" and outranked the actual lockout runbook.
    """
    r = draft_response(ticket_id)
    if r.draft is None:
        return
    leaked = INTERNAL_ARTICLES & set(r.kb_article_ids)
    assert not leaked, f"{ticket_id} grounded a customer draft in {leaked}"


@pytest.mark.parametrize(
    "ticket_id", [t["ticket_id"] for t in _tickets() if t["ticket_id"] not in SECURITY_TICKETS]
)
def test_drafts_do_not_leak_staff_instructions(ticket_id: str) -> None:
    r = draft_response(ticket_id)
    if r.draft is None:
        return
    low = r.draft.lower()
    for phrase in ("never issue", "never advise", "escalate per", "per kb-", "rules for support"):
        assert phrase not in low, f"{ticket_id} leaked staff instruction {phrase!r}"


def test_draft_carries_required_facts_verbatim() -> None:
    """Project 1 requires these exact facts on T-001; paraphrase is a defect."""
    r = draft_response("T-001")
    assert r.ok and r.draft is not None
    assert "15 minutes" in r.draft
    assert "reset.summitmit.example" in r.draft


def test_draft_returns_its_grounding() -> None:
    r = draft_response("T-001")
    assert r.grounding and r.kb_article_ids
    for excerpt in r.grounding:
        assert excerpt.text in r.draft, "draft contains text not present in grounding"


def test_draft_unknown_ticket() -> None:
    r = draft_response("T-999")
    assert r.ok is False and r.error_code is ErrorCode.TICKET_NOT_FOUND


# --- update_ticket write gate -----------------------------------------------
# The gate itself is tested adversarially in test_confirmation_gate.py. These
# cover the ordinary paths.

def test_update_dry_run_changes_nothing() -> None:
    before = get_ticket("T-002").ticket
    r = run(update_ticket("T-002", status="resolved"))
    assert r.ok is False
    assert r.applied is False
    assert r.error_code is ErrorCode.CONFIRMATION_REQUIRED
    assert r.changes[0].field == "status"
    assert r.confirmation_token
    assert get_ticket("T-002").ticket.status == before.status


def test_update_commits_with_the_issued_token() -> None:
    preview = run(update_ticket("T-003", tier=2))
    r = run(update_ticket("T-003", tier=2, confirmation_token=preview.confirmation_token))
    assert r.ok and r.applied is True
    assert get_ticket("T-003").ticket.tier == 2
    # No elicitation-capable client in tests, so the weaker mode must be stated.
    assert r.confirmation_method == "token_only"
    assert "does not support elicitation" in (r.message or "")


def test_update_rejects_invalid_values() -> None:
    for kwargs in ({"status": "banana"}, {"priority": "urgent"}, {"tier": 7}):
        r = run(update_ticket("T-004", **kwargs))
        assert r.ok is False and r.error_code is ErrorCode.INVALID_FIELD
        assert r.applied is False


def test_update_noop_is_not_a_confirmation_prompt() -> None:
    current = get_ticket("T-005").ticket
    r = run(update_ticket("T-005", status=current.status))
    assert r.ok is True and r.applied is False and r.changes == []
    assert r.confirmation_token is None


def test_update_unknown_ticket() -> None:
    r = run(update_ticket("T-999", status="open"))
    assert r.ok is False and r.error_code is ErrorCode.TICKET_NOT_FOUND
