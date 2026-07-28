"""KB-006 security indicator scanning — the guardrail's independent judgment.

This module exists so `draft_response` never has to trust a label. A ticket's
as-filed category is intake metadata typed by whoever opened it; the realistic
failure mode is a genuine incident filed as "hardware" because the user did not
know what they were looking at. T-024 — "screen looks weird after I opened an
email attachment", filed as hardware — is exactly that ticket.

WHY THE RULES ARE CONJUNCTIVE
-----------------------------
KB-006's indicators are mostly compound conditions, not keywords. "Unexpected
attachments opened, followed by ANY change in system behavior" is an AND: the
word "attachment" alone appears in routine mail tickets all day and matching on
it would refuse half the queue. So an indicator may specify:

    any_of  — a single signal strong enough on its own (a ransom note)
    all_of  — groups of alternatives that must ALL be represented (attachment
              opened AND subsequent behaviour change)

FALSE POSITIVES ARE CHEAP, FALSE NEGATIVES ARE NOT
--------------------------------------------------
Carrying over Project 1's asymmetry: a wrongly refused ticket is awkward and a
human resolves it in a minute. A wrongly drafted response to an active
compromise can destroy forensic evidence or walk a user further into a fraud.
When a rule is borderline, it is written to fire.

This scanner is deliberately dumb, deterministic, and readable. It makes no API
calls and has no model in the loop — the guardrail must not itself depend on a
model's judgment, or it inherits the negotiability it exists to remove.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Indicator:
    """One KB-006 indicator pattern.

    Fires when any_of matches, or when every group in all_of has at least one
    matching alternative. Patterns are regexes matched against normalized
    (lowercased, whitespace-collapsed) ticket text.
    """

    id: str
    kb_ref: str
    description: str
    any_of: tuple[str, ...] = ()
    all_of: tuple[tuple[str, ...], ...] = ()


# --- KB-006 "Treat as a security incident (non-exhaustive)" ------------------
# Each indicator below maps to a bullet in kb/KB-006-security-incident-response.md.
# The KB list is explicitly non-exhaustive, so these rules are a floor, not a
# ceiling: matching nothing here is not evidence that a ticket is safe.

INDICATORS: tuple[Indicator, ...] = (
    Indicator(
        id="ransomware_or_file_encryption",
        kb_ref="KB-006",
        description="Files renamed or encrypted, or a ransom / recovery note present.",
        any_of=(
            r"how[\s_-]?to[\s_-]?recover",
            r"\bransom(ware)?\b",
            r"\bdecrypt(ed|ion)?\b",
            r"\brestore my files\b",
            r"files? (?:are|were|got|have been) (?:encrypted|renamed|locked)",
        ),
        all_of=(
            (r"\brenamed\b", r"\bextension\b", r"\.[a-z]{3,5}\b at the end"),
            (r"every file", r"all (?:my|the) files", r"documents folder", r"whole folder"),
        ),
    ),
    Indicator(
        id="credentials_entered_on_suspicious_site",
        kb_ref="KB-006",
        description="Credentials entered on a site the user later found suspicious.",
        all_of=(
            (
                r"\b(?:entered|typed|put in|submitted|gave|filled in)\b",
                r"\bre-?verif(?:y|ied)\b",
                r"\blogged? in\b",
            ),
            (
                r"\bpassword\b",
                r"\bcredentials?\b",
                r"\busername\b",
                r"\blogin\b",
            ),
            (
                r"looked? off",
                r"address (?:looked|looks|was) ",
                r"\bsuspicious\b",
                r"\bphish",
                r"\bfake\b",
                r"\bspoof",
                r"wasn'?t right",
                r"didn'?t look right",
                r"\bnot (?:our|the real)\b",
                r"looked like our",
            ),
        ),
    ),
    Indicator(
        id="attachment_or_link_then_behavior_change",
        kb_ref="KB-006",
        description=(
            "An unexpected attachment or link was opened and system behaviour "
            "changed afterwards."
        ),
        all_of=(
            (
                r"\battachment\b",
                r"\battached\b",
                r"opened (?:a|an|the) .{0,30}(?:file|email|link|notice)",
                r"clicked (?:a|an|the|on)",
                r"\bdownloaded\b",
            ),
            (
                r"\bslow(er|ly)?\b",
                r"\bflicker",
                r"\bfreez(e|es|ing)\b",
                r"\bcrash(es|ing|ed)?\b",
                r"\bpop-?ups?\b",
                r"\bweird\b",
                r"\bstrange\b",
                r"ever since",
                r"since then",
                r"\bwon'?t (?:start|boot|open)\b",
                r"acting (?:up|funny|strange)",
            ),
        ),
    ),
    Indicator(
        id="browser_hijack",
        kb_ref="KB-006",
        description="Browser hijack symptoms: self-opening tabs, changed homepage, fake warnings.",
        any_of=(
            r"opens? tabs? by itself",
            r"tabs? (?:open|opening) (?:by them|on their own|by itself)",
            r"homepage (?:changed|is different|got changed)",
            r"changed my homepage",
            r"fake[\s-]?looking virus",
            r"fake virus warning",
            r"\bredirect(?:ed|ing|s)? (?:me|my browser|to)\b",
            r"search (?:site|engine) i'?ve never",
        ),
    ),
    Indicator(
        id="vendor_payment_change_bec",
        kb_ref="KB-006",
        description=(
            "Request to change vendor bank or payment details — business email "
            "compromise / wire-fraud pattern."
        ),
        all_of=(
            (
                r"\bvendor\b",
                r"\bsupplier\b",
                r"\binvoices?\b",
                r"\bbilling\b",
                r"\bpayable",
            ),
            (
                r"bank (?:account|details)",
                r"payment (?:details|information|info)",
                r"\bwire\b",
                r"routing (?:number|details)",
                r"account (?:number|details)",
                r"\bremittance\b",
            ),
            (
                r"\bupdate\b",
                r"\bchange[ds]?\b",
                r"\bdifferent\b",
                r"\bnew\b",
                r"\bswitch(?:ed|ing)?\b",
            ),
        ),
    ),
    Indicator(
        id="spoofed_or_impersonated_email",
        kb_ref="KB-006",
        description="Mail appearing to come from the client's own domain that they did not send.",
        any_of=(
            r"\bspoof(?:ed|ing)?\b",
            r"never sent",
            r"(?:we|they) didn'?t send",
            r"appear(?:s|ed)? to come from",
            r"look like (?:ours|our emails)",
            r"emails? from us",
            r"pretending to be",
        ),
    ),
    Indicator(
        id="denied_account_change",
        kb_ref="KB-006",
        description=(
            "User denies causing their own lockout, password change, or MFA prompt."
        ),
        all_of=(
            (
                r"\bi didn'?t\b",
                r"i did not",
                r"\bi never\b",
                r"nobody (?:here|else)",
                r"wasn'?t me",
                r"no[- ]one (?:here|else)",
            ),
            (
                r"\block(?:ed|out)\b",
                r"password (?:reset|change)",
                r"reset my password",
                r"\bmfa\b",
                r"\btwo[- ]factor\b",
                r"verification (?:code|prompt)",
                r"\bsign[- ]?in (?:attempt|alert)\b",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class IndicatorHit:
    """A single tripped indicator, with the text that tripped it."""

    id: str
    kb_ref: str
    description: str
    evidence: tuple[str, ...] = field(default=())


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).lower()


def _first_match(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(0).strip() if m else None


def scan(subject: str, body: str) -> list[IndicatorHit]:
    """Scan ticket text for KB-006 indicators.

    Returns every tripped indicator with the substrings that tripped it, so the
    refusal can tell the caller precisely what was detected rather than
    asserting "this looks like security" and expecting to be believed.
    """
    text = _normalize(f"{subject} {body}")
    hits: list[IndicatorHit] = []

    for ind in INDICATORS:
        evidence: list[str] = []

        for pattern in ind.any_of:
            found = _first_match(pattern, text)
            if found:
                evidence.append(found)

        if not evidence and ind.all_of:
            group_evidence: list[str] = []
            for group in ind.all_of:
                matched = next(
                    (f for f in (_first_match(p, text) for p in group) if f), None
                )
                if matched is None:
                    group_evidence = []
                    break
                group_evidence.append(matched)
            evidence.extend(group_evidence)

        if evidence:
            hits.append(
                IndicatorHit(
                    id=ind.id,
                    kb_ref=ind.kb_ref,
                    description=ind.description,
                    evidence=tuple(dict.fromkeys(evidence)),
                )
            )

    return hits


def is_security_ticket(ticket: dict) -> tuple[bool, list[IndicatorHit], list[str]]:
    """Decide whether a ticket is a security incident.

    Two independent layers. The label is checked because a real helpdesk has one
    and ignoring a correct signal would be perverse — but it is never sufficient,
    and it is never required. The content scan can refuse a ticket the label
    calls "hardware", which is the whole reason it exists.

    Returns (is_security, indicator_hits, reasons).
    """
    reasons: list[str] = []

    if (ticket.get("category") or "").lower() == "security":
        reasons.append("ticket is filed under category 'security'")

    hits = scan(ticket.get("subject", ""), ticket.get("body", ""))
    if hits:
        filed = ticket.get("category") or "none"
        if filed.lower() != "security":
            reasons.append(
                f"content scan tripped {len(hits)} KB-006 indicator(s) despite the "
                f"ticket being filed as '{filed}'"
            )
        else:
            reasons.append(f"content scan tripped {len(hits)} KB-006 indicator(s)")

    return bool(reasons), hits, reasons
