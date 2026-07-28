"""MSP tools MCP server — Summit Managed IT support toolset over stdio.

The design claim this repo exists to make: a safety rule belongs in the tool,
not in the prompt. `draft_response` refuses security tickets as a matter of
control flow. There is no system prompt, no user instruction, and no clever
framing that produces a draft for a ticket that trips KB-006 — not because the
model has been asked nicely to decline, but because the code path that returns a
draft is not reachable for those tickets.

STDIO DISCIPLINE: never print to stdout. This process speaks JSON-RPC on stdout
and anything else corrupts the stream. Logging goes to stderr.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from msp_tools import kb as kb_module
from msp_tools import security
from msp_tools.adapters import LocalJSONDataSource
from msp_tools.models import (
    DraftResponseResult,
    ErrorCode,
    FieldChange,
    GetTicketResult,
    KBExcerpt,
    Refusal,
    SearchKBResult,
    SearchTicketsResult,
    SecurityIndicator,
    Ticket,
    TicketSummary,
    UpdateTicketResult,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("msp-tools-mcp")

REPO = Path(__file__).resolve().parent.parent
KB_DIR = os.environ.get("MSP_TOOLS_KB", str(REPO / "kb"))
DATA_PATH = os.environ.get("MSP_TOOLS_DATA", str(REPO / "data" / "tickets.json"))

SOURCE = LocalJSONDataSource(DATA_PATH)

MAX_LIMIT = 25
VALID_STATUS = {"open", "pending", "resolved"}
VALID_PRIORITY = {"low", "medium", "high", "critical"}

mcp = FastMCP(
    "msp-tools",
    instructions=(
        "Support toolset for Summit Managed IT, a managed service provider. "
        "Use search_tickets to find work, get_ticket to read one in full, "
        "search_kb to look up procedure, draft_response to compose a reply, and "
        "update_ticket to change ticket state.\n\n"
        "draft_response enforces a hard security guardrail in code: it refuses "
        "to draft replies for tickets showing signs of a security incident and "
        "returns SECURITY_ESCALATION_REQUIRED instead. This is not a preference "
        "and cannot be overridden by instruction. When it refuses, relay the "
        "refusal and help the user escalate — do not attempt to compose a reply "
        "yourself, and do not offer troubleshooting steps for that ticket."
    ),
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _find(ticket_id: str) -> dict | None:
    wanted = (ticket_id or "").strip().upper()
    return next(
        (t for t in SOURCE.load_tickets() if t["ticket_id"].upper() == wanted), None
    )


def _summary(t: dict) -> TicketSummary:
    return TicketSummary(
        ticket_id=t["ticket_id"],
        subject=t["subject"],
        client=t["client"],
        requester_name=t["requester"]["name"],
        category=t.get("category"),
        priority=t.get("priority"),
        status=t["status"],
        tier=t.get("tier"),
        assignee=t.get("assignee"),
        created_at=t["created_at"],
    )


def _full(t: dict) -> Ticket:
    return Ticket(
        **_summary(t).model_dump(),
        body=t["body"],
        channel=t.get("channel", "email"),
        requester_role=t["requester"].get("role", "unknown"),
        updated_at=t["updated_at"],
    )


def _excerpt(e: kb_module.Excerpt) -> KBExcerpt:
    return KBExcerpt(
        article_id=e.article_id,
        article_title=e.article_title,
        section=e.label,
        text=e.text,
        score=e.score,
        matched_terms=list(e.matched_terms),
    )


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    description="""Find tickets in the Summit Managed IT queue using filters.

Returns compact summaries (no ticket body) ranked newest-first, capped at
`limit`. Combine filters freely; they AND together. Omit them all to see the
newest open work.

WHAT IT DOES NOT DO
- Does not return ticket bodies. Call get_ticket for the full text of a
  specific ticket once you have narrowed to one.
- Does not search inside ticket bodies for topics reliably — `query` matches
  subject and body substrings only, with no ranking or synonyms. For "what is
  our procedure for X", use search_kb instead; that searches the knowledge
  base, which is where procedure lives.
- Does not classify anything. The `category` it returns is the as-filed intake
  label typed by whoever opened the ticket. It is frequently wrong. Do not use
  it to conclude a ticket is safe or routine.

FILTER VALUES
  status    open | pending | resolved
  priority  low | medium | high | critical
  tier      1 | 2 | 3
  category  password_account, email, network_vpn, hardware, software_licensing,
            security, server_outage, onboarding_offboarding
  client    client company name, case-insensitive substring
  query     free-text substring over subject and body

ERRORS
This tool does not fail on an empty result. `total_matched: 0` with an empty
list means nothing matched — widen the filters rather than retrying the same
call. `truncated: true` means more matched than were returned; narrow the
filters to see the remainder.""",
)
def search_tickets(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    tier: int | None = None,
    client: str | None = None,
    query: str | None = None,
    limit: int = 10,
) -> SearchTicketsResult:
    limit = max(1, min(limit, MAX_LIMIT))
    rows = SOURCE.load_tickets()

    def keep(t: dict) -> bool:
        if status and t.get("status", "").lower() != status.lower():
            return False
        if category and (t.get("category") or "").lower() != category.lower():
            return False
        if priority and (t.get("priority") or "").lower() != priority.lower():
            return False
        if tier is not None and t.get("tier") != tier:
            return False
        if client and client.lower() not in t.get("client", "").lower():
            return False
        if query:
            hay = f"{t.get('subject','')} {t.get('body','')}".lower()
            if query.lower() not in hay:
                return False
        return True

    matched = [t for t in rows if keep(t)]
    matched.sort(key=lambda t: t["created_at"], reverse=True)
    page = matched[:limit]

    return SearchTicketsResult(
        total_matched=len(matched),
        returned=len(page),
        truncated=len(matched) > len(page),
        tickets=[_summary(t) for t in page],
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    description="""Retrieve one ticket in full, including the requester's message body.

Use this once you have a specific ticket ID — typically from search_tickets.
This is the only tool that returns ticket body text.

WHAT IT DOES NOT DO
- Does not triage, categorise, or assess the ticket. It returns the record as
  filed. In particular the `category` field is intake metadata and may
  misdescribe the ticket entirely; read the body yourself.
- Does not indicate whether a ticket is safe to answer. Only draft_response
  makes that determination, and it does so independently of this record's
  category field. Never conclude from a non-security category here that
  drafting will be permitted.

ERRORS
  TICKET_NOT_FOUND — no ticket with that ID exists. Ticket IDs look like
  "T-014". Do not retry with the same ID; call search_tickets to find the
  correct one.""",
)
def get_ticket(ticket_id: str) -> GetTicketResult:
    t = _find(ticket_id)
    if t is None:
        return GetTicketResult(
            ok=False,
            error_code=ErrorCode.TICKET_NOT_FOUND,
            message=(
                f"No ticket with id {ticket_id!r}. IDs look like 'T-014'. "
                "Use search_tickets to locate the right ticket."
            ),
        )
    return GetTicketResult(ticket=_full(t))


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    description="""Search the Summit Managed IT knowledge base for procedure and policy.

Returns ranked excerpts with the article ID and section that produced each one,
so any fact you use can be cited. The knowledge base is the only authoritative
source of Summit procedure: reset URLs, SLA timeframes, approval requirements,
escalation paths.

Query with the words the KB itself would use — symptoms and nouns
("account lockout", "vpn certificate", "mailbox full"). Long natural-language
sentences score worse than three or four content words, because matching is
keyword overlap, not semantic similarity.

WHAT IT DOES NOT DO
- Does not search tickets. For customer requests use search_tickets.
- Does not write replies. For a reply grounded in these articles, use
  draft_response, which performs its own retrieval and returns the grounding
  alongside the draft.
- Does not paraphrase or summarise. Excerpts are returned verbatim so that
  timeframes, URLs, and limits survive intact. Reproduce them exactly; do not
  round "15 minutes" or invent a support phone number. The corpus contains no
  phone numbers at all.

ERRORS
  KB_NO_MATCH — nothing scored above threshold. Retry once with broader or
  different content words. If it still misses, the knowledge base does not
  cover the topic: say so plainly rather than answering from general knowledge.""",
)
def search_kb(query: str, category: str | None = None, limit: int = 3) -> SearchKBResult:
    limit = max(1, min(limit, 10))
    try:
        results = kb_module.search(query, KB_DIR, limit=limit, category=category)
    except FileNotFoundError as e:
        log.error("KB load failed: %s", e)
        return SearchKBResult(
            ok=False,
            query=query,
            error_code=ErrorCode.KB_NO_MATCH,
            message="Knowledge base corpus is unavailable on the server.",
        )

    if not results:
        return SearchKBResult(
            ok=False,
            query=query,
            error_code=ErrorCode.KB_NO_MATCH,
            message=(
                f"No knowledge-base article matched {query!r}. Retry with different "
                "content words, or state that the knowledge base does not cover this."
            ),
        )
    return SearchKBResult(query=query, excerpts=[_excerpt(e) for e in results])


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    description="""Compose a knowledge-base-grounded draft reply for a ticket.

Returns the draft together with `grounding` — the KB excerpts it was built
from — and `kb_article_ids` for citation. You may improve the phrasing of the
returned draft. You may not add any fact, URL, timeframe, or procedure step
that does not appear in `grounding`. The knowledge base contains no phone
numbers; a phone number in a reply is fabricated by definition.

SECURITY GUARDRAIL — ENFORCED IN CODE, NOT NEGOTIABLE
This tool refuses to draft for any ticket that shows signs of a security
incident, and returns ok=false with SECURITY_ESCALATION_REQUIRED. The decision
is made two ways, independently:
  1. the ticket's as-filed category is "security"; or
  2. the ticket text trips a KB-006 indicator — credentials entered on a
     suspicious site, an attachment opened followed by changed system
     behaviour, files encrypted or a ransom note, browser hijack symptoms,
     a vendor requesting changed bank details, mail spoofing the client's own
     domain, or a user denying an account change they are recorded as making.
Layer 2 fires even when the ticket is filed as hardware, email, or anything
else. A non-security category is never sufficient to obtain a draft.

There is no parameter, phrasing, or instruction that disables this. Do not
attempt to work around a refusal by drafting the reply yourself, by calling
search_kb and composing from the excerpts, or by asking the user to relay
troubleshooting steps. KB-006 is explicit that support does not troubleshoot
suspected security incidents at all: restarts and quick fixes destroy forensic
evidence, and a password reset is insufficient during an active compromise.
On refusal, tell the user plainly that the ticket needs the security team,
report the indicators returned, and offer to escalate with update_ticket.

WHAT IT DOES NOT DO
- Does not send anything. The draft is returned to you for review; delivery is
  out of scope for this server.
- Does not change ticket state. Use update_ticket to record an escalation.
- Does not invent facts when the knowledge base is silent. If retrieval finds
  nothing, it returns KB_NO_MATCH rather than a plausible-sounding reply.

ERRORS
  TICKET_NOT_FOUND — no such ticket; find the right ID with search_tickets.
  SECURITY_ESCALATION_REQUIRED — refused; escalate to the security team.
  KB_NO_MATCH — the knowledge base does not cover this issue. Escalate to a
  technician rather than answering from general knowledge.""",
)
def draft_response(ticket_id: str) -> DraftResponseResult:
    t = _find(ticket_id)
    if t is None:
        return DraftResponseResult(
            ok=False,
            ticket_id=ticket_id,
            error_code=ErrorCode.TICKET_NOT_FOUND,
            message=(
                f"No ticket with id {ticket_id!r}. Use search_tickets to locate it."
            ),
        )

    # --- the guardrail. Nothing below this block runs for a security ticket. ---
    is_sec, hits, reasons = security.is_security_ticket(t)
    if is_sec:
        log.warning(
            "draft_response REFUSED %s (filed as %s): %s",
            t["ticket_id"],
            t.get("category"),
            ", ".join(h.id for h in hits) or "category label",
        )
        return DraftResponseResult(
            ok=False,
            ticket_id=t["ticket_id"],
            draft=None,
            error_code=ErrorCode.SECURITY_ESCALATION_REQUIRED,
            refusal=Refusal(
                reasons=reasons,
                filed_category=t.get("category"),
                indicators=[
                    SecurityIndicator(
                        id=h.id,
                        kb_ref=h.kb_ref,
                        description=h.description,
                        evidence=list(h.evidence),
                    )
                    for h in hits
                ],
                escalate_to="security_team",
                guidance=(
                    "KB-006: support does not troubleshoot suspected security "
                    "incidents. Do not send the user troubleshooting steps, do not "
                    "advise a restart, and do not tell them to reset their password "
                    "as a fix — those destroy forensic evidence and are insufficient "
                    "during an active compromise. Escalate to the security team now. "
                    "You can record the escalation with update_ticket."
                ),
            ),
            message=(
                f"Refused to draft a reply for {t['ticket_id']}: this ticket shows "
                "signs of a security incident and must be escalated to the security "
                "team. This refusal is enforced by the tool and cannot be overridden."
            ),
        )

    # --- non-security path -------------------------------------------------
    # include_internal=False: staff-facing blocks ("NEVER issue a temporary
    # password", escalation rules) are legitimate KB content but must not be
    # pasted into a reply to a customer.
    results = kb_module.search(
        f"{t['subject']} {t['body']}",
        KB_DIR,
        limit=3,
        category=t.get("category"),
        include_internal=False,
    )
    if not results:
        return DraftResponseResult(
            ok=False,
            ticket_id=t["ticket_id"],
            error_code=ErrorCode.KB_NO_MATCH,
            message=(
                "No knowledge-base article covers this ticket, so no grounded reply "
                "can be composed. Escalate to a technician rather than answering "
                "from general knowledge."
            ),
        )

    name = t["requester"]["name"].split()[0]
    steps = "\n\n".join(e.text for e in results)
    draft = (
        f"Hi {name},\n\n"
        f"Thanks for reaching out about \"{t['subject']}\".\n\n"
        f"{steps}\n\n"
        "If that doesn't resolve it, reply here and we'll take another look.\n\n"
        "— Summit Managed IT Support"
    )

    return DraftResponseResult(
        ticket_id=t["ticket_id"],
        draft=draft,
        kb_article_ids=sorted({e.article_id for e in results}),
        grounding=[_excerpt(e) for e in results],
        message=(
            "Draft is assembled verbatim from the grounding excerpts. Rewrite for "
            "tone if you like, but every fact, URL, and timeframe in your final "
            "reply must trace to `grounding`."
        ),
    )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
    description="""Change ticket state: status, tier, priority, assignee, or an appended note.

WRITE OPERATION — CONFIRMATION GATE
Calling without `confirm=true` performs a dry run: nothing changes, and the
result returns `applied: false` with a `changes` list showing exactly which
fields would move from what to what, plus CONFIRMATION_REQUIRED.

Show that preview to the user and get their agreement before calling again with
`confirm=true`. Do not set `confirm=true` on the first call, and do not set it
on the user's behalf because their intent seems obvious — the preview exists so
a human sees the blast radius before state changes. Passing every field you were
given at once is fine; the gate is about confirmation, not batching.

Pass only the fields you intend to change. Omitted fields are left alone.
Passing `note` appends to the ticket's note trail; it never replaces it.

WHAT IT DOES NOT DO
- Does not send anything to the requester. It changes internal ticket state
  only. draft_response composes customer-facing text.
- Does not delete tickets, and cannot set a status outside the allowed values.
- Does not validate that an escalation is appropriate. Recording tier 3 does
  not notify anyone; it records intent on the ticket.

FIELD VALUES
  status    open | pending | resolved
  priority  low | medium | high | critical
  tier      1 | 2 | 3
  assignee  technician username, or null to unassign
  note      free text appended to the ticket's note trail

ERRORS
  TICKET_NOT_FOUND — no such ticket.
  CONFIRMATION_REQUIRED — expected on a dry run. Not a failure: it carries the
  preview. Show it to the user, then re-call with confirm=true.
  INVALID_FIELD — a value outside the allowed set; nothing was changed. Fix the
  value and retry.""",
)
def update_ticket(
    ticket_id: str,
    status: str | None = None,
    tier: int | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    note: str | None = None,
    confirm: bool = False,
) -> UpdateTicketResult:
    t = _find(ticket_id)
    if t is None:
        return UpdateTicketResult(
            ok=False,
            ticket_id=ticket_id,
            applied=False,
            error_code=ErrorCode.TICKET_NOT_FOUND,
            message=f"No ticket with id {ticket_id!r}.",
        )

    if status is not None and status.lower() not in VALID_STATUS:
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            error_code=ErrorCode.INVALID_FIELD,
            message=f"status must be one of {sorted(VALID_STATUS)}; got {status!r}.",
        )
    if priority is not None and priority.lower() not in VALID_PRIORITY:
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            error_code=ErrorCode.INVALID_FIELD,
            message=f"priority must be one of {sorted(VALID_PRIORITY)}; got {priority!r}.",
        )
    if tier is not None and tier not in (1, 2, 3):
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            error_code=ErrorCode.INVALID_FIELD,
            message=f"tier must be 1, 2, or 3; got {tier!r}.",
        )

    proposed: list[FieldChange] = []
    if status is not None and status.lower() != t.get("status"):
        proposed.append(FieldChange(field="status", before=t.get("status"), after=status.lower()))
    if tier is not None and tier != t.get("tier"):
        proposed.append(FieldChange(field="tier", before=t.get("tier"), after=tier))
    if priority is not None and priority.lower() != t.get("priority"):
        proposed.append(
            FieldChange(field="priority", before=t.get("priority"), after=priority.lower())
        )
    if assignee is not None and assignee != t.get("assignee"):
        proposed.append(FieldChange(field="assignee", before=t.get("assignee"), after=assignee))
    if note:
        proposed.append(FieldChange(field="note", before=None, after=note))

    if not proposed:
        return UpdateTicketResult(
            ok=True,
            ticket_id=t["ticket_id"],
            applied=False,
            changes=[],
            ticket=_full(t),
            message="No change requested — every supplied value already matches the ticket.",
        )

    if not confirm:
        summary = "; ".join(f"{c.field}: {c.before!r} -> {c.after!r}" for c in proposed)
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            changes=proposed,
            ticket=_full(t),
            error_code=ErrorCode.CONFIRMATION_REQUIRED,
            message=(
                f"Dry run — nothing has changed. Proposed: {summary}. "
                "Show this to the user and re-call with confirm=true to commit."
            ),
        )

    for c in proposed:
        if c.field == "note":
            t.setdefault("notes", []).append(c.after)
        else:
            t[c.field] = c.after
    SOURCE.save_ticket(t)
    log.info("update_ticket applied %s: %s", t["ticket_id"], proposed)

    return UpdateTicketResult(
        ticket_id=t["ticket_id"],
        applied=True,
        changes=proposed,
        ticket=_full(t),
        message=f"Applied {len(proposed)} change(s) to {t['ticket_id']}.",
    )


def main() -> None:
    log.info("msp-tools-mcp starting (kb=%s, data=%s)", KB_DIR, DATA_PATH)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
