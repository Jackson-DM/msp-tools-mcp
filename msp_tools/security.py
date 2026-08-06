"""KB-006 security indicator scanning — the guardrail's independent judgment.

This module exists so `draft_response` never has to trust a label. A ticket's
as-filed category is intake metadata typed by whoever opened it; the realistic
failure mode is a genuine incident filed as "hardware" because the user did not
know what they were looking at.

DESIGN, AND WHY IT CHANGED
--------------------------
The first version matched keyword groups anywhere in the ticket text. An
independent adversarial review broke it in both directions: 7 realistic
incidents went undetected, and 7 routine tickets were wrongly refused. See
tests/test_adversarial_corpus.py. Four distinct faults, addressed here:

1. NO PROXIMITY. "attachment ... slow" matched even when the two words belonged
   to unrelated sentences. KB-006 says "attachments opened, FOLLOWED BY any
   change in system behavior" — a temporal relation, not co-occurrence. Rules
   now match within a sliding window of consecutive sentences (`window`).

2. WRONG OBJECT. "I clicked on the Excel icon and it opened slowly" satisfied a
   rule about email attachments. Trigger patterns now require the object to be
   a message, attachment, or link — not any click at all.

3. NO EXCULPATORY CONTEXT. "Please restore my files from Friday's backup" read
   as ransomware. Indicators may declare `unless_any` — context that suppresses
   a weak match. It cannot suppress a strong one (see below), because an
   incident report often contains innocent-sounding phrases too.

4. A MISSING RULE. KB-006's first bullet is a DISJUNCTION — "phishing link
   clicked, OR credentials entered on a suspicious site" — and only the second
   half was implemented. A user who clicked a phishing link but entered nothing
   received a cheerful draft. That was the most serious defect found.

5. NO WORD BOUNDARIES (round 4, fixed 2026-07-31). Patterns were substrings, so
   a trigger could match across the interior of an unrelated word: the `ran`
   alternative of the message-object rule matched inside "st-RAN-ge", and a user
   who received a phishing email and correctly ignored it was refused on the
   evidence "range 'new voicemail". Note that this is fault 2 again — the wrong
   object — arriving through a mechanism the round-2 fix did not close, which is
   the more interesting half of the finding: the rules were corrected case by
   case, so a new route to the same fault stayed open.

   Every pattern is now anchored at its start, and so is every alternation that
   follows a variable-length gap (`\b(?:from|in)\b`, or "in" matches inside
   "information"). `test_every_pattern_is_anchored` enforces this on the whole
   table, because the lesson above is that fixing the instances found is not the
   same as closing the class. Only the START of a pattern is anchored: trailing
   boundaries would break plural and inflected matches ("emails", "clicking"),
   and mid-word STARTS are the entire defect.

STRONG VS WEAK EVIDENCE
-----------------------
`any_of` is strong: one match is sufficient on its own, and no exculpatory
context can suppress it. A ransom note is a ransom note.

`all_of` is weak: every group must be represented within the window, and
`unless_any` can suppress it. This asymmetry matters — otherwise a genuine
incident that happens to mention a backup would be silenced.

FALSE POSITIVES ARE CHEAP, FALSE NEGATIVES ARE NOT
--------------------------------------------------
A wrongly refused ticket is awkward and a human resolves it in a minute. A
wrongly drafted reply to an active compromise can destroy forensic evidence or
walk a user further into a fraud. Borderline rules are written to fire. But
"refuse everything" is not a guardrail either — a tool that cries wolf trains
people to route around it, which costs more than it saves.

This scanner is deliberately deterministic, with no model in the loop: a
guardrail that asked a model for a verdict would inherit the negotiability it
exists to remove. Its known limitation is the flip side of that — it reasons
about vocabulary, not meaning, and KB-006's list is explicitly non-exhaustive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Default proximity: a group may match in this many consecutive sentences.
# Two, because users routinely split cause and effect across a sentence break —
# "I opened the attachment. Right after that, the fan came on."
DEFAULT_WINDOW = 2


@dataclass(frozen=True)
class Indicator:
    """One KB-006 indicator pattern.

    Fires when any_of matches (strong, unsuppressable), or when every group in
    all_of matches within `window` consecutive sentences and no unless_any
    pattern is present (weak, suppressable).
    """

    id: str
    kb_ref: str
    description: str
    any_of: tuple[str, ...] = ()
    all_of: tuple[tuple[str, ...], ...] = ()
    unless_any: tuple[str, ...] = ()
    window: int = DEFAULT_WINDOW


# Reusable fragments -------------------------------------------------------

# A gap that cannot cross into another clause.
#
# Round 5 (fault 2 again, third sighting). "I clicked Forgot Password four times
# because the first messages were slow" refused a routine ticket: the verb's
# object was a BUTTON, and "messages" merely happened to fall inside the
# sixty-character window. Proximity had been standing in for the object
# relation, which works until a subordinate clause supplies a second noun.
#
# So the gap now refuses to span a clause boundary. "clicked the link in the
# email" and "double-clicked the spreadsheet in yesterday's delivery email" are
# one clause and still match; anything reached only by crossing a "because",
# "when", "after" no longer does. This is a claim about grammar rather than a
# list of phrases, which is the point - the previous two fixes for this fault
# each closed one route and left the next one open.
_CLAUSE_BREAK = (
    r"because|since|when|after|before|so that|but|while|although|unless|if"
    r"|though|whereas|until"
)


def _same_clause(n: int) -> str:
    """Up to `n` characters that stay inside the current clause."""
    return rf"(?:(?!\b(?:{_CLAUSE_BREAK})\b)[^.]){{0,{n}}}?"


# The object must be a message or its payload. Bare "clicked" is not enough:
# people click icons, buttons, and links inside your own product all day.
_MESSAGE_OBJECT = (
    r"\battachment\b",
    r"\battached\b",
    # `\bran` matters here specifically: unanchored, it matched inside "strange".
    r"\b(?:clicked|opened|double-?clicked|ran|downloaded)" + _same_clause(60)
    + r"\b(?:e-?mail|message|attachment|link|invite)",
    # `\b(?:from|in)\b` needs BOTH sides: "in" otherwise matches inside
    # "information", so "the document with the pricing information in my email"
    # satisfied a rule about attachments.
    r"\b(?:link|file|invoice|notice|document)" + _same_clause(30)
    + r"\b(?:from|in)\b" + _same_clause(30)
    + r"\b(?:e-?mail|message)",
)

# Any change in system behaviour, per KB-006's "ANY change".
_BEHAVIOUR_CHANGE = (
    r"\bslow(?:er|ly)?\b",
    r"\bflicker",
    r"\bfreez(?:e|es|ing)\b",
    r"\bcrash(?:es|ing|ed)?\b",
    r"\bpop-?ups?\b",
    r"\bweird\b",
    r"\bstrange\b",
    r"\bfan\b",
    r"\bfull speed",
    r"\bon (?:its|their) own",
    r"\bby itself",
    r"\brun(?:s|ning)? differently",
    r"\bever since",
    r"\bright after",
    r"\bsince then",
    r"\bwon'?t (?:start|boot|open)\b",
    r"\bacting (?:up|funny|strange)",
    r"\bunresponsive\b",
)


INDICATORS: tuple[Indicator, ...] = (
    Indicator(
        id="ransomware_or_file_encryption",
        kb_ref="KB-006",
        description="Files renamed or encrypted, or a ransom / recovery demand present.",
        any_of=(
            r"\bhow[\s_-]?to[\s_-]?recover",
            r"\bransom(?:ware)?\b",
            r"\bdecrypt(?:ed|ion)?\b",
            r"\bbitcoin\b",
            r"\bcrypto(?:currency)?\b",
            r"\b(?:pay|send)\b" + _same_clause(30) + r"\b(?:to (?:get|recover|unlock)|for the key)",
            r"\bget the key",
            r"\bfiles? (?:are|were|got|have been) (?:encrypted|locked)",
        ),
        all_of=(
            (
                r"\brenamed\b",
                r"\bextension\b",
                r"\b(?:end|ends|ending) (?:in|with) \.?[a-z0-9]{2,6}\b",
                r"\.[a-z0-9]{2,6}\b at the end",
            ),
            (
                r"\bevery file",
                r"\bevery (?:word )?document",
                r"\ball (?:my|the) files",
                r"\bdocuments folder",
                r"\bshared drive",
                r"\bnone of them will open",
                r"\binaccessible\b",
                r"\bwon'?t open",
            ),
        ),
        # A user restoring a folder they deleted is not an incident. Cannot
        # suppress any_of — an actual ransom note outranks any of this.
        unless_any=(
            r"\bfrom (?:friday'?s?|last night'?s?|the|our|a) backup",
            r"\brestore (?:it |them )?from backup",
            r"\bi deleted\b",
            r"\bby mistake",
            r"\baccidentally\b",
        ),
    ),
    Indicator(
        id="phishing_link_or_message_engaged",
        kb_ref="KB-006",
        description=(
            "A link or attachment from a suspected phishing / scam message was "
            "opened. KB-006 treats this as sufficient on its own — credentials "
            "need not have been entered, and nothing need appear wrong yet."
        ),
        all_of=(
            _MESSAGE_OBJECT,
            (
                r"\bphish",
                r"\bscam\b",
                r"\bfraudulent\b",
                r"\bsuspicious\b",
                r"\bfake\b",
                r"\bspoof",
                r"\bnot legitimate",
                r"\blooked like (?:our|a)",
                r"\bpretend(?:ing|ed) to be",
                r"\basked me to (?:sign in|log ?in|verify|re-?verify)",
                r"\bimpersonat",
            ),
        ),
        # Whole-ticket window: the user often names the scam in a later
        # sentence ("a coworker says the message was a scam").
        window=0,
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
            # The suspicious thing must be the SITE, not the user's monitor.
            # "the dashboard looked off on my monitor" is a UI complaint.
            (
                r"\b(?:web )?address (?:looked|looks|was|seemed)",
                # `web ?site` is listed before `site` because anchoring the
                # alternation would otherwise drop "the website looked wrong":
                # `\bsite` cannot match inside "website".
                r"\b(?:url|domain|web ?site|site|web ?page|link) "
                r"(?:looked|looks|was|seemed)",
                r"\bphish",
                r"\bscam\b",
                r"\bspoof",
                r"\bfake\b",
                r"\bnot (?:our|the real|the actual)",
                r"\blooked like our",
                r"\bwasn'?t (?:our|the real|right)",
            ),
        ),
        window=0,
    ),
    Indicator(
        id="attachment_or_link_then_behavior_change",
        kb_ref="KB-006",
        description=(
            "An unexpected attachment or link was opened and system behaviour "
            "changed afterwards."
        ),
        all_of=(_MESSAGE_OBJECT, _BEHAVIOUR_CHANGE),
    ),
    Indicator(
        id="browser_hijack",
        kb_ref="KB-006",
        description="Browser hijack: self-opening tabs, changed homepage/start page, fake warnings.",
        any_of=(
            r"\bopens? tabs? by itself",
            r"\btabs? (?:open|opening) (?:by them|on their own|by itself)",
            r"\b(?:home ?page|start ?page) (?:changed|is different|got changed|is now)",
            r"\bchanged my (?:home ?page|start ?page)",
            r"\bfake[\s-]?looking virus",
            r"\bfake virus warning",
            r"\binstead of (?:google|bing|our)",
            r"\bsearch (?:site|engine) i'?ve never",
        ),
        all_of=(
            (
                r"\bredirect(?:ed|ing|s)?\b",
                r"\bsends me to",
                r"\btakes me to",
                r"\bgoing to\b",
            ),
            (
                r"\bads?\b",
                r"\badvertis",
                r"\bshopping (?:pages?|sites?)",
                r"\bsearch results?",
                r"\bnever heard of",
                r"\bpop-?ups?\b",
            ),
        ),
        # A benefits portal legitimately redirecting to Microsoft SSO is not a
        # hijack when the user says it worked.
        unless_any=(
            r"\bcompleted normally",
            r"\bworked (?:fine|normally|as expected)",
            r"\bthat'?s expected",
        ),
    ),
    Indicator(
        id="vendor_payment_change_bec",
        kb_ref="KB-006",
        description=(
            "An inbound request to change vendor bank or payment details — "
            "business email compromise / wire-fraud pattern."
        ),
        all_of=(
            # Must be an INBOUND request from outside. Editing your own invoice
            # template is routine work, not fraud.
            (
                # `\bask` on both sides: unanchored it matched inside "task",
                # so "the vendor emailed about the invoice task" was a wire fraud.
                r"\b(?:emailed|e-?mail|message|contacted|called)" + _same_clause(40) + r"\bask",
                r"\bask(?:ing|ed)" + _same_clause(40) + r"\b(?:update|change|send|pay|go to)",
                r"\b(?:we|they) (?:got|received)" + _same_clause(30) + r"(?:an? )?e-?mail",
                r"\brequest(?:ing|ed) (?:that |we |us )?(?:update|change|pay)",
                r"\bthey say",
                r"\binstructions for",
            ),
            (
                r"\bvendor\b",
                r"\bsupplier\b",
                r"\binvoices?\b",
                r"\bbilling\b",
                r"\bpayable\b",
                r"\baccounts?-?receivable",
                r"\bap\b",
            ),
            (
                r"\bbank (?:account|details)",
                r"\bpayment (?:details|information|info)",
                r"\bwire\b",
                r"\bach\b",
                r"\brouting (?:number|details)",
                r"\baccount (?:number|details)",
                r"\bremittance\b",
                r"\bbill go to\b",
            ),
        ),
        window=0,
    ),
    Indicator(
        id="spoofed_or_impersonated_email",
        kb_ref="KB-006",
        description="Mail appearing to come from the client's own domain that they did not send.",
        any_of=(
            r"\bspoof(?:ed|ing)?\b",
            r"\bappear(?:s|ed)? to come from",
            r"\bpretending to be",
            r"\bwith me as (?:the )?sender",
            r"\bnot in my sent items",
        ),
        all_of=(
            # Someone ELSE received it. "The copier scans were never sent to my
            # email" is a delivery fault, not impersonation.
            (
                r"\b(?:customers?|clients?|recipients?|people|someone|vendors?)"
                + _same_clause(40)
                + r"\b(?:received|got|getting|called|reported)",
                r"\breceived" + _same_clause(30) + r"\bfrom (?:us|our)",
                r"\bemails? from us",
            ),
            (
                r"\bnever sent",
                r"\b(?:we|they|i) didn'?t send",
                r"\bnot from us",
                r"\bnothing to do with it",
                r"\bwe never",
                r"\blook like ours",
            ),
        ),
        window=0,
    ),
    Indicator(
        id="denied_account_change",
        kb_ref="KB-006",
        description=(
            "User denies causing their own lockout, password change, or MFA prompt."
        ),
        all_of=(
            # Denial of CAUSATION. "I didn't receive the reset email" is a
            # delivery complaint, and the user who retried and locked themselves
            # out has admitted the cause.
            (
                r"\bi didn'?t (?:do|change|reset|request|authori[sz]e|make|touch)\b",
                r"\bi did not (?:do|change|reset|request|authori[sz]e|make|touch)",
                r"\bi never (?:changed|reset|requested|authori[sz]ed|did)\b",
                r"\bwasn'?t me",
                r"\bno[- ]?(?:one|body) (?:here|else)",
                r"\bi was asleep",
                r"\bhaven'?t touched",
                r"\bdidn'?t make that change",
                r"\bi don'?t recogni[sz]e",
            ),
            (
                r"\block(?:ed|out)\b",
                r"\bpassword (?:was )?(?:reset|change|changed|updated)",
                r"\breset my password",
                r"\bmfa\b",
                r"\btwo[- ]factor\b",
                r"\bverification (?:code|prompt)",
                r"\bsign[- ]?in (?:attempt|alert)",
                r"\baccount settings",
            ),
        ),
        window=0,
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


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    return parts or [text]


def _first_match(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(0).strip() if m else None


def _match_groups(groups: tuple[tuple[str, ...], ...], text: str) -> list[str] | None:
    """Every group must have at least one matching alternative in `text`."""
    evidence: list[str] = []
    for group in groups:
        found = next((f for f in (_first_match(p, text) for p in group) if f), None)
        if found is None:
            return None
        evidence.append(found)
    return evidence


def _match_windowed(ind: Indicator, sents: list[str], whole: str) -> list[str] | None:
    """Match all_of groups within `window` consecutive sentences.

    window=0 means the whole ticket, used where the corroborating detail
    routinely lands far from the trigger ("a coworker says it was a scam").
    """
    if ind.window <= 0 or len(sents) <= ind.window:
        return _match_groups(ind.all_of, whole)

    for start in range(len(sents) - ind.window + 1):
        chunk = " ".join(sents[start : start + ind.window])
        found = _match_groups(ind.all_of, chunk)
        if found is not None:
            return found
    return None


def scan(subject: str, body: str) -> list[IndicatorHit]:
    """Scan ticket text for KB-006 indicators.

    Returns every tripped indicator with the substrings that tripped it, so a
    refusal can state precisely what was detected rather than asserting "this
    looks like security" and expecting to be believed.
    """
    whole = _normalize(f"{subject}. {body}")
    sents = _sentences(whole)
    hits: list[IndicatorHit] = []

    for ind in INDICATORS:
        evidence: list[str] = []
        strong = False

        for pattern in ind.any_of:
            found = _first_match(pattern, whole)
            if found:
                evidence.append(found)
                strong = True

        if not strong and ind.all_of:
            found = _match_windowed(ind, sents, whole)
            if found is not None:
                # Weak matches only. Exculpatory context can never suppress a
                # ransom note, only a circumstantial pattern.
                suppressed = any(re.search(p, whole) for p in ind.unless_any)
                if not suppressed:
                    evidence.extend(found)

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
