"""Pydantic return models for the MSP toolset.

Every tool returns one of these rather than a string. FastMCP reads the return
annotation, emits an `outputSchema` for the tool, and populates
`structuredContent` on the result — so the calling model receives typed fields
it can branch on instead of prose it has to parse.

This is also what makes a refusal legible. `SECURITY_ESCALATION_REQUIRED` comes
back as `ok=False` with a populated `refusal` object, not as an exception and
not as an apologetic sentence the model might read as a soft suggestion.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """Typed, recoverable failures. Never a raw stack trace."""

    TICKET_NOT_FOUND = "TICKET_NOT_FOUND"
    KB_NO_MATCH = "KB_NO_MATCH"
    KB_UNAVAILABLE = "KB_UNAVAILABLE"
    SECURITY_ESCALATION_REQUIRED = "SECURITY_ESCALATION_REQUIRED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    CONFIRMATION_DECLINED = "CONFIRMATION_DECLINED"
    CONFIRMATION_UNAVAILABLE = "CONFIRMATION_UNAVAILABLE"
    INVALID_FIELD = "INVALID_FIELD"


class TicketSummary(BaseModel):
    ticket_id: str
    subject: str
    client: str
    requester_name: str
    category: str | None = Field(
        default=None,
        description=(
            "As-filed intake category. Advisory only — it reflects what whoever "
            "opened the ticket typed, and may be wrong. Never treat it as proof "
            "a ticket is safe."
        ),
    )
    priority: str | None = None
    status: str
    tier: int | None = None
    assignee: str | None = None
    created_at: str


class Ticket(TicketSummary):
    body: str
    channel: str
    requester_role: str
    updated_at: str
    notes: list[str] = Field(
        default_factory=list,
        description=(
            "Internal note trail, oldest first, appended by update_ticket. "
            "Staff-facing working notes — not written by the requester and not "
            "shown to them. Empty for a ticket that has never been noted."
        ),
    )


class SearchTicketsResult(BaseModel):
    ok: bool = True
    total_matched: int = Field(description="Tickets matching the filters before the cap.")
    returned: int
    truncated: bool = Field(
        description="True when total_matched exceeded limit; narrow the filters to see the rest."
    )
    tickets: list[TicketSummary] = []
    error_code: ErrorCode | None = None
    message: str | None = None


class GetTicketResult(BaseModel):
    ok: bool = True
    ticket: Ticket | None = None
    error_code: ErrorCode | None = None
    message: str | None = None


class KBExcerpt(BaseModel):
    article_id: str
    article_title: str
    section: str | None = None
    text: str
    score: float
    matched_terms: list[str] = []


class SearchKBResult(BaseModel):
    ok: bool = True
    query: str
    excerpts: list[KBExcerpt] = []
    error_code: ErrorCode | None = None
    message: str | None = None


class SecurityIndicator(BaseModel):
    id: str
    kb_ref: str
    description: str
    evidence: list[str] = Field(
        default=[],
        description="Exact substrings from the ticket that tripped this indicator.",
    )


class Refusal(BaseModel):
    """Why the tool declined, and what to do instead."""

    reasons: list[str]
    indicators: list[SecurityIndicator] = []
    escalate_to: str = "security_team"
    filed_category: str | None = None
    guidance: str


class DraftResponseResult(BaseModel):
    ok: bool = True
    ticket_id: str
    draft: str | None = Field(
        default=None,
        description="The grounded draft reply. Null whenever ok is false.",
    )
    kb_article_ids: list[str] = Field(
        default=[], description="Articles the draft is grounded in."
    )
    grounding: list[KBExcerpt] = Field(
        default=[],
        description=(
            "The ONLY facts available for this reply. Wording may be adjusted; "
            "facts, URLs, and timeframes absent from these excerpts may not be added."
        ),
    )
    refusal: Refusal | None = None
    error_code: ErrorCode | None = None
    message: str | None = None


class FieldChange(BaseModel):
    field: str
    before: object | None = None
    after: object | None = None


class UpdateTicketResult(BaseModel):
    ok: bool = True
    ticket_id: str
    applied: bool = Field(description="True only when the change was actually committed.")
    changes: list[FieldChange] = []
    ticket: Ticket | None = None
    confirmation_token: str | None = Field(
        default=None,
        description=(
            "Issued with a preview. Pass it back to commit exactly this change. "
            "Single use, expires, and bound to these values on this ticket — it "
            "will not authorise a different edit."
        ),
    )
    confirmation_method: str | None = Field(
        default=None,
        description=(
            "How the commit was authorised: 'user_elicitation' means this client "
            "supports elicitation and a person was actually asked; 'token_only' "
            "means it does not, so the server could verify a preview was produced "
            "but not that anyone read it. Disclosed rather than assumed — a caller "
            "must never mistake the weaker mode for the stronger one."
        ),
    )
    error_code: ErrorCode | None = None
    message: str | None = None
