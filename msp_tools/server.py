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

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ClientCapabilities, ElicitationCapability, ToolAnnotations
from pydantic import BaseModel, Field as PydanticField

from msp_tools import classifier as classifier_module
from msp_tools import guardrail
from msp_tools import kb as kb_module
from msp_tools.adapters import LocalJSONDataSource
from msp_tools.confirmation import ConfirmationStore, ticket_version
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

# Stage 2 of the guardrail. Opt-in via MSP_TOOLS_CLASSIFIER + ANTHROPIC_API_KEY;
# otherwise the server runs on the deterministic floor alone and says so.
CLASSIFIER = classifier_module.build_default(KB_DIR)

MAX_LIMIT = 25
VALID_STATUS = {"open", "pending", "resolved"}
VALID_PRIORITY = {"low", "medium", "high", "critical"}

# Pending write previews. Module-level because the gate must outlive a single
# tool call but must not outlive the process — see confirmation.py.
CONFIRMATIONS = ConfirmationStore()

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
        notes=list(t.get("notes") or []),
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
`limit`. Combine filters freely; they AND together.

Omitting every filter returns the newest tickets of EVERY status, including
resolved ones — not open work. Pass `status="open"` if that is what you want.

WHAT IT DOES NOT DO
- Does not return ticket bodies. Call get_ticket for the full text of a
  specific ticket once you have narrowed to one. (draft_response also reads
  bodies internally, but does not return them to you.)
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
It is the only tool that returns ticket body text to you, and the only one that
returns the internal `notes` trail that update_ticket appends.

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

`topic_hint` is optional and is NOT a filter. Its words are folded into your
query, so it can promote articles that already match — it never restricts
results to a topic, and a hit may match the hint alone. Passing a ticket's
as-filed category here is reasonable; treating the results as "articles in that
category" is not.

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
  KB_NO_MATCH — the corpus is fine, but nothing scored above threshold. Retry
  once with broader or different content words. If it still misses, the
  knowledge base does not cover the topic: say so plainly rather than answering
  from general knowledge.
  KB_UNAVAILABLE — the corpus could not be read at all. This is a server fault,
  not a bad query. Rephrasing will not help and neither will retrying. Report
  that the knowledge base is unavailable; do not answer from general knowledge
  and do not present it to the user as "nothing found".""",
)
def search_kb(query: str, topic_hint: str | None = None, limit: int = 3) -> SearchKBResult:
    limit = max(1, min(limit, 10))
    try:
        results = kb_module.search(query, KB_DIR, limit=limit, topic_hint=topic_hint)
    except FileNotFoundError as e:
        log.error("KB load failed: %s", e)
        return SearchKBResult(
            ok=False,
            query=query,
            error_code=ErrorCode.KB_UNAVAILABLE,
            message=(
                "The knowledge base corpus could not be read on the server. This is "
                "not a result about your query — do not retry it, and do not tell the "
                "user the knowledge base has nothing on the topic."
            ),
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
is made in two stages, and the order is a safety property rather than an
implementation detail.

STAGE 1 — deterministic, and final. Two independent routes:
  1. the ticket's as-filed category is "security"; or
  2. the ticket text trips a KB-006 indicator — among them: a phishing or
     scam link or attachment engaged with (sufficient on its own, before
     anything appears wrong and whether or not credentials were entered),
     credentials entered on a suspicious site, an attachment opened followed
     by changed system behaviour, files encrypted or a ransom note, browser
     hijack symptoms, a vendor requesting changed bank details, mail spoofing
     the client's own domain, or a user denying an account change they are
     recorded as making. KB-006's list is explicitly non-exhaustive and so is
     this one; do not treat an absence from it as a clearance.
Route 2 fires even when the ticket is filed as hardware, email, or anything
else. A non-security category is never sufficient to obtain a draft.

STAGE 2 — a model classifier, consulted ONLY when stage 1 finds nothing, and
able only to ADD a refusal. It can never clear a ticket stage 1 caught. Ticket
text is attacker-controlled — a phishing report contains the phisher's words —
so no path exists by which that text can reverse the deterministic layer.
Stage 2 fails closed: if it errors, the ticket is treated as an incident.

Stage 2 is optional. When it is not configured the server runs on stage 1
alone and SAYS SO in the result, because a clearance from the deterministic
scan by itself is weak evidence — that scan is a floor, and on independently
authored tickets it catches roughly one incident in eight. Do not read
"no indicators tripped" as "this ticket is safe". Read it as "nothing
unnegotiable fired". A refusal is strong; a clearance is not its mirror image.

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
  technician rather than answering from general knowledge.
  KB_UNAVAILABLE — the corpus could not be read at all. A server fault, not a
  gap in coverage. Do not compose a reply yourself; say the knowledge base is
  unavailable.""",
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
    a = guardrail.assess(t, CLASSIFIER)
    if a.is_security:
        log.warning(
            "draft_response REFUSED %s (filed as %s, stage=%s): %s",
            t["ticket_id"],
            t.get("category"),
            a.stage,
            ", ".join(h.id for h in a.hits) or a.stage,
        )
        indicators = [
            SecurityIndicator(
                id=h.id, kb_ref=h.kb_ref, description=h.description, evidence=list(h.evidence)
            )
            for h in a.hits
        ]
        # Stage 2 findings carry no regex id, so surface them in the same shape
        # rather than as an unexplained refusal.
        if a.stage == "classifier" and a.verdict is not None:
            indicators.append(
                SecurityIndicator(
                    id="classifier:" + (a.verdict.indicators[0] if a.verdict.indicators else "flagged"),
                    kb_ref="KB-006",
                    description=a.verdict.rationale or "Flagged by the security classifier.",
                    evidence=list(a.verdict.evidence),
                )
            )
        return DraftResponseResult(
            ok=False,
            ticket_id=t["ticket_id"],
            draft=None,
            error_code=ErrorCode.SECURITY_ESCALATION_REQUIRED,
            refusal=Refusal(
                reasons=a.reasons,
                filed_category=t.get("category"),
                indicators=indicators,
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
    try:
        results = kb_module.search(
            f"{t['subject']} {t['body']}",
            KB_DIR,
            limit=3,
            topic_hint=t.get("category"),
            include_internal=False,
        )
    except FileNotFoundError as e:
        # Previously this escaped as a raw FileNotFoundError, which reaches the
        # caller as a transport-level exception rather than something it can act
        # on. A missing corpus is an operational fault, not a crash, and it is
        # emphatically not "the KB has nothing on this" — reporting it as
        # KB_NO_MATCH would invite a reply composed from general knowledge.
        log.error("KB load failed while drafting %s: %s", t["ticket_id"], e)
        return DraftResponseResult(
            ok=False,
            ticket_id=t["ticket_id"],
            error_code=ErrorCode.KB_UNAVAILABLE,
            message=(
                "The knowledge base corpus could not be read, so no grounded reply "
                "can be composed. This is a server fault, not a gap in the knowledge "
                "base. Do not compose a reply from general knowledge; report that the "
                "knowledge base is unavailable."
            ),
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
            + (
                ""
                if a.classifier_available
                else " NOTE: the security classifier is not configured, so this "
                "ticket was cleared by the deterministic scan alone. That scan has "
                "high precision but limited recall on unfamiliar phrasing — treat "
                "clearance as weaker evidence than a refusal."
            )
        ),
    )


def _client_supports_elicitation(ctx: Context) -> bool:
    """Whether this client advertised elicitation during initialization.

    Checked rather than attempted, because a client that never declared the
    capability may not answer at all, and a write must not hang waiting on a
    prompt nobody will ever see. Any failure to determine it is treated as "no",
    which selects the weaker mode — and the weaker mode is disclosed, so
    answering conservatively here cannot silently downgrade anything.
    """
    try:
        return ctx.session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())
        )
    except Exception:  # pragma: no cover - depends on transport state
        return False


class _ConfirmUpdate(BaseModel):
    """Elicitation schema. Primitives only — the MCP spec allows nothing else."""

    approve: bool = PydanticField(
        description="Apply these changes to the ticket? Choose no to cancel; nothing has changed yet."
    )


@mcp.tool(
    annotations=ToolAnnotations(
        # idempotentHint is False: `note` appends, so repeating an identical call
        # appends a second note. The other fields are idempotent; the tool as a
        # whole is not, and the annotation describes the tool.
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    ),
    description="""Change ticket state: status, tier, priority, assignee, or an appended note.

WRITE OPERATION — TWO CALLS, ALWAYS
Call 1, without `confirmation_token`: a dry run. Nothing changes. The result
carries `applied: false`, a `changes` list showing exactly which fields would
move from what to what, a `confirmation_token`, and CONFIRMATION_REQUIRED.

Call 2, passing that `confirmation_token` back: commits.

There is no single-call form. The token is minted by the server and cannot be
constructed, guessed, or reused, so the commit path is not reachable without
first producing a preview. This is enforced in code — it is not a convention you
are being asked to follow, and there is no parameter that skips it.

A token authorises exactly the change it previewed. If you alter any field, any
value, or the ticket between the two calls, it is refused and you must preview
again. Do not hold tokens or reuse them across tickets.

Show the preview to the user between the two calls. Where the client supports
elicitation the server will also ask the user directly and abort if they
decline; `confirmation_method` in the result tells you which happened. When it
reads `token_only`, no human was asked by the server — you are the only thing
standing between the user and a silent write.

Pass only the fields you intend to change. Omitted fields are left alone.
Passing `note` appends to the ticket's note trail; it never replaces it.
Batching several fields into one preview is fine and preferred — the gate is
about confirmation, not about doing one field at a time.

WHAT IT DOES NOT DO
- Does not send anything to the requester. It changes internal ticket state
  only. draft_response composes customer-facing text.
- Does not delete tickets, and cannot set a status outside the allowed values.
- Does not validate that an escalation is appropriate. Recording tier 3 does
  not notify anyone; it records intent on the ticket.
- Does not prove a human read the preview when `confirmation_method` is
  `token_only`. It proves a preview was produced and that this commit matches it.

FIELD VALUES
  status    open | pending | resolved
  priority  low | medium | high | critical
  tier      1 | 2 | 3
  assignee  technician username to assign the ticket to
  unassign  true to clear the assignee. Omitting `assignee` means "leave it
            alone", so there is no value of `assignee` that means "nobody" —
            this is the separate flag that does it. Passing both `assignee` and
            `unassign=true` is contradictory and is rejected.
  note      free text appended to the ticket's note trail. Read it back with
            get_ticket, which returns the trail as `notes`.

ERRORS
  TICKET_NOT_FOUND — no such ticket.
  CONFIRMATION_REQUIRED — expected on call 1. Not a failure: it carries the
  preview and the token. Show the preview, then call again with the token.
  CONFIRMATION_INVALID — the token was fabricated, already used, expired, issued
  for a different change, or the ticket moved since the preview. Nothing was
  changed. Re-run the dry run; do not retry the same token.
  CONFIRMATION_DECLINED — the user was asked and said no. Nothing was changed.
  Do not re-attempt this write. Ask what they want instead.
  CONFIRMATION_UNAVAILABLE — your token was valid, but the client's user-prompt
  channel failed, so nothing was changed. Not a token problem; a fresh token
  will fail the same way. Tell the user the change could not be confirmed.
  INVALID_FIELD — a value outside the allowed set; nothing was changed. Fix the
  value and retry.""",
)
async def update_ticket(
    ticket_id: str,
    status: str | None = None,
    tier: int | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    unassign: bool = False,
    note: str | None = None,
    confirmation_token: str | None = None,
    ctx: Context | None = None,
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
    if unassign and assignee is not None:
        # Refused rather than resolved by precedence. Either order of priority
        # would silently discard half of a contradictory instruction, and the
        # caller would not learn which half.
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            error_code=ErrorCode.INVALID_FIELD,
            message=(
                f"Contradictory: unassign=true clears the assignee, but assignee="
                f"{assignee!r} sets one. Nothing was changed. Pass one or the other."
            ),
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
    if unassign and t.get("assignee") is not None:
        proposed.append(FieldChange(field="assignee", before=t.get("assignee"), after=None))
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

    summary = "; ".join(f"{c.field}: {c.before!r} -> {c.after!r}" for c in proposed)
    triples = [(c.field, c.before, c.after) for c in proposed]
    version = ticket_version(t)

    # --- call 1: preview only. This is the only place a token is minted. -----
    if not confirmation_token:
        token = CONFIRMATIONS.issue(t["ticket_id"], triples, version)
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            changes=proposed,
            ticket=_full(t),
            confirmation_token=token,
            error_code=ErrorCode.CONFIRMATION_REQUIRED,
            message=(
                f"Dry run — nothing has changed. Proposed: {summary}. Show this to "
                "the user, then call again with this confirmation_token to commit. "
                "The token authorises only this exact change."
            ),
        )

    # --- call 2: redeem. Consumes the token whatever the outcome. -----------
    check = CONFIRMATIONS.redeem(
        confirmation_token, t["ticket_id"], triples, version, current_version=ticket_version(t)
    )
    if not check.ok:
        log.warning(
            "update_ticket rejected token for %s: %s", t["ticket_id"], check.rejection
        )
        return UpdateTicketResult(
            ok=False,
            ticket_id=t["ticket_id"],
            applied=False,
            changes=proposed,
            ticket=_full(t),
            error_code=ErrorCode.CONFIRMATION_INVALID,
            message=check.message,
        )

    # --- ask the actual human, where the client can. ------------------------
    # A valid token proves a preview existed and that this commit matches it. It
    # cannot prove anyone read it. Elicitation closes that gap where the client
    # supports it; where it does not, the weaker mode is disclosed rather than
    # quietly substituted — same rule the classifier follows in regex-only mode.
    method = "token_only"
    if ctx is not None and _client_supports_elicitation(ctx):
        try:
            answer = await ctx.elicit(
                message=(
                    f"Apply these changes to {t['ticket_id']} ({t.get('subject', '')})?\n\n"
                    + "\n".join(f"  {c.field}: {c.before!r} -> {c.after!r}" for c in proposed)
                ),
                schema=_ConfirmUpdate,
            )
        except Exception as e:
            # Fail closed: an unusable confirmation channel must never be the
            # reason a write lands unreviewed.
            log.error("elicitation failed, refusing the write: %s", e)
            return UpdateTicketResult(
                ok=False,
                ticket_id=t["ticket_id"],
                applied=False,
                changes=proposed,
                ticket=_full(t),
                # Deliberately NOT CONFIRMATION_INVALID. The token was fine; the
                # channel for asking the user broke. A caller told its token was
                # invalid would mint a new one and retry into the same failure.
                error_code=ErrorCode.CONFIRMATION_UNAVAILABLE,
                message=(
                    "Your confirmation_token was valid, but the client's user-prompt "
                    f"channel failed ({type(e).__name__}), so nothing was changed. "
                    "This is not a problem with the token and retrying will not fix "
                    "it. Tell the user the change could not be confirmed."
                ),
            )

        if answer.action != "accept" or not answer.data.approve:
            log.info("update_ticket declined by user for %s", t["ticket_id"])
            return UpdateTicketResult(
                ok=False,
                ticket_id=t["ticket_id"],
                applied=False,
                changes=proposed,
                ticket=_full(t),
                error_code=ErrorCode.CONFIRMATION_DECLINED,
                message=(
                    f"The user declined this change to {t['ticket_id']}. Nothing was "
                    "changed. Do not re-attempt it; ask what they would like instead."
                ),
            )
        method = "user_elicitation"

    for c in proposed:
        if c.field == "note":
            t.setdefault("notes", []).append(c.after)
        else:
            t[c.field] = c.after
    SOURCE.save_ticket(t)
    log.info("update_ticket applied %s (%s): %s", t["ticket_id"], method, proposed)

    return UpdateTicketResult(
        ticket_id=t["ticket_id"],
        applied=True,
        changes=proposed,
        ticket=_full(t),
        confirmation_method=method,
        message=(
            f"Applied {len(proposed)} change(s) to {t['ticket_id']}."
            + (
                ""
                if method == "user_elicitation"
                else " NOTE: this client does not support elicitation, so the server "
                "verified that a preview was issued for exactly this change but could "
                "not ask anyone to approve it. Treat the write as reviewed only if you "
                "actually showed the preview to the user."
            )
        ),
    )


def main() -> None:
    log.info("msp-tools-mcp starting (kb=%s, data=%s)", KB_DIR, DATA_PATH)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
