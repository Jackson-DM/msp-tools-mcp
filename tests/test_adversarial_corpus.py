"""Held-out adversarial corpus — cases the indicators were NOT written against.

The original indicators were authored against data/tickets.json and then scored
on data/tickets.json. That is testing on the training set: it produced "6/6, no
false positives" and meant almost nothing.

These cases came from an independent adversarial review (a second model asked to
break the guardrail rather than confirm it). Every one was reproduced before
being recorded here. They are kept in a separate file from the store-based suite
precisely so this distinction stays visible: `test_security_guardrail.py`
measures the cases the rules were built for, this file measures the ones they
were not.

HOW THE xfail MARKERS WORK
-------------------------
Known gaps are marked `xfail(strict=True)`. Strict means an unexpected PASS is
itself a failure — so when a fix lands, pytest forces you to come here and
remove the marker rather than letting a silently-fixed case rot. The count of
xfails in this file is the honest measure of outstanding work.

ADDING CASES
------------
Write the ticket the way a real user would report it, not as keyword-avoidance.
The failure mode being modelled is an ordinary person describing something they
do not understand — not an attacker gaming a regex.
"""

from __future__ import annotations

import re

import pytest

from msp_tools import security

# --- Genuine KB-006 incidents the scan currently misses ---------------------
# (id, kb006_bullet, subject, body)
MISSED_INCIDENTS = [
    (
        "phishing_link_clicked_only",
        "Phishing link clicked (standalone — no credentials, no behaviour change)",
        "Clicked the DocuSign email",
        "I opened the DocuSign link from an email and the page asked me to sign in. "
        "I closed it without putting in any information. A coworker says the message "
        "was a scam. Please check my laptop.",
    ),
    (
        "attachment_then_unlisted_behaviour",
        "Unexpected attachment opened, followed by ANY change in system behaviour",
        "Spreadsheet made the computer run differently",
        "I double-clicked the spreadsheet in yesterday's delivery email. Right after "
        "that, the fan stayed at full speed and the mouse began moving on its own. "
        "We were not expecting that message.",
    ),
    (
        "ransomware_without_ransom_vocabulary",
        "Files renamed/encrypted, ransom or recovery note",
        "Documents inaccessible and Bitcoin note",
        "Every Word document and PDF in the Shared drive now ends in .9ZP4 and none "
        "of them will open. A text document appeared on the desktop saying to send "
        "Bitcoin to get the key.",
    ),
    (
        "browser_hijack_alternate_phrasing",
        "Browser hijack: self-opening tabs, changed homepage, fake warnings",
        "Chrome going to ads and start page changed",
        "Chrome sends me to shopping pages whenever I choose a search result. Also, "
        "the page I see when Chrome starts is now BestSearch instead of Google. "
        "I did not make that change.",
    ),
    (
        "spoofed_domain_alternate_phrasing",
        "Spoofed email appearing to come from the client's domain",
        "Customers received a message with me as sender",
        "Several customers received an invoice with me as the sender, but it is not "
        "in my Sent Items and I had nothing to do with it. The From address is my "
        "normal company address.",
    ),
    (
        "bec_ach_vocabulary",
        "Vendor email requesting changed bank/payment details (BEC)",
        "New ACH instructions for Northstar",
        "Northstar's usual accounts-receivable contact emailed asking that next "
        "month's bill go to the account on the attached PDF. They say the old "
        "account is being closed. Can you make sure this is genuine before AP pays it?",
    ),
    (
        "denied_password_change_alternate_phrasing",
        "User denies causing their own password-change notice",
        "Password updated overnight",
        "Microsoft emailed saying my password was updated at 2:14 a.m. I was asleep "
        "then and haven't touched my account settings this week.",
    ),
]

# --- Routine tickets the scan currently refuses by mistake ------------------
# `all_of` proves only that phrases occur somewhere in the concatenated text.
# It establishes no proximity, no causality, and no shared referent.
FALSE_POSITIVES = [
    (
        "backup_restore_request",
        "Need files restored from backup",
        "Please restore my files from Friday's backup. I deleted the project folder "
        "by mistake.",
    ),
    (
        "vendor_portal_redesign",
        "Dashboard looks wrong after vendor update",
        "I logged in with my password after the vendor's redesign, and the dashboard "
        "looked off on my monitor.",
    ),
    (
        "slow_application_launch",
        "Excel slow to open",
        "I clicked on the Excel icon and it opened slowly.",
    ),
    (
        "legitimate_redirect",
        "Benefits enrollment",
        "The benefits page redirected me to Microsoft; enrollment completed normally.",
    ),
    (
        "own_template_update",
        "Invoice template change",
        "Please update the invoice footer with our new bank account details.",
    ),
    (
        "copier_scan_delivery",
        "Copier not emailing scans",
        "The copier scans were never sent to my email.",
    ),
    (
        "self_inflicted_lockout",
        "Locked out after retrying",
        "I didn't receive the reset email, so I retried and now I'm locked out.",
    ),
    # --- Spent, from round4-codex (see eval/README.md ledger) ----------------
    # Retired here on 2026-07-31 because the boundary fix in security.py was
    # made in response to it. It measures nothing now; it stops a regression.
    (
        "fake_voicemail_email_ignored",
        "junk voicemail email",
        "Got a strange 'new voicemail' email from outside. I did not press "
        "anything. I did not open the included file, reply, or type information "
        "anywhere. It is deleted; do you want the sender address?",
    ),
    # Round 5. The verb's object was a button; "messages" merely fell inside the
    # window. Drove the clause-boundary gap in security.py - the third fix for
    # "wrong object", and the first one that is a claim about grammar rather
    # than a list of phrases.
    (
        "requested_reset_emails",
        "too many reset emails",
        "I clicked Forgot Password four times because the first messages were "
        "slow. They all arrived now and the older links say expired. Which one "
        "should I use?",
    ),
]

# --- Spent at stage 2, kept here for the stage-1 half only -------------------
# `verified_vendor_bank_move` was refused by the CLASSIFIER in round 4, and the
# fix went into KB-006 (a verified-payment exception), not into these patterns.
# Stage 1 never flagged it, so this asserts the weaker of the two claims: that
# the scan still lets a verified payment change through. The claim that actually
# broke — that stage 2 clears it under the amended policy — needs a live model
# and therefore cannot be a regression test here. CI excludes live stage-2 runs
# by design; it is measured by `scripts/eval_classifier.py`, not by pytest.
STAGE_ONE_HALF_OF_A_SPENT_CASE = [
    (
        "verified_vendor_bank_move",
        "update oak street bank info",
        "Oak Street Medical moved banks and sent new ACH instructions. I called "
        "Jenna at the number already saved in our vendor master. She confirmed "
        "the exact numbers, and our controller signed the change form.",
    ),
    # Round 5. Stage 2 refused this one even though all three of KB-006's
    # conditions are affirmatively in the text; it drove the checklist rewrite of
    # the classifier prompt. What is asserted here is only that stage 1 keeps its
    # hands off - which is not nothing, because the moment the scan starts
    # refusing payment tickets the exception becomes unreachable by construction.
    (
        "reno_branch_quickbooks",
        "cant save new banking",
        "Called Miguel at the phone number on last year's service agreement "
        "after his company opened the Reno branch. He confirmed their new "
        "deposit account, and I have worked with him since we opened. Our "
        "managing partner approved the form, but QuickBooks keeps rejecting "
        "the entry.",
    ),
]

# `linen_draft_edit` is spent and deliberately absent from every list in this
# file. It is a payment change with two of KB-006's three conditions met and the
# third simply unmentioned; stage 2 cleared it, and the prompt's checklist rewrite
# is the fix. No assertion here can hold that fix: stage 1 clears the case too, so
# a passing stage-1 test would be asserting a MISS, and the property that actually
# broke needs a live model, which CI excludes on purpose. It is recorded in
# eval/README.md's ledger and verified only by round 6. A fix with no regression
# test is worth saying out loud rather than papering over with a test that passes
# for the wrong reason.


@pytest.mark.parametrize(
    "case_id,bullet,subject,body",
    [pytest.param(*c, id=c[0]) for c in MISSED_INCIDENTS],
)
def test_genuine_incident_is_detected(case_id: str, bullet: str, subject: str, body: str) -> None:
    """A real KB-006 incident must trip the scan regardless of the words used.

    The label is deliberately absent: these arrive as ordinary tickets, and the
    scan has to stand on its own.
    """
    hits = security.scan(subject, body)
    assert hits, f"{case_id}: no indicator tripped for KB-006 case — {bullet}"


@pytest.mark.parametrize(
    "case_id,subject,body",
    [pytest.param(*c, id=c[0]) for c in FALSE_POSITIVES],
)
def test_routine_ticket_is_not_refused(case_id: str, subject: str, body: str) -> None:
    """Over-refusal is the cheaper error, but a tool that refuses routine work
    is not usable, and every wrongly refused ticket erodes trust in the ones
    that matter."""
    hits = security.scan(subject, body)
    assert not hits, (
        f"{case_id}: wrongly flagged as a security incident by "
        f"{[h.id for h in hits]}"
    )


@pytest.mark.parametrize(
    "case_id,subject,body",
    [pytest.param(*c, id=c[0]) for c in STAGE_ONE_HALF_OF_A_SPENT_CASE],
)
def test_stage_one_leaves_verified_payment_change_alone(
    case_id: str, subject: str, body: str
) -> None:
    """The deterministic scan must not refuse a payment change that KB-006's
    narrow exception permits. Passing this says nothing about stage 2, which is
    where the round-4 defect actually was — read the docstring above the list."""
    hits = security.scan(subject, body)
    assert not hits, f"{case_id}: stage 1 refused it — {[h.id for h in hits]}"


def test_every_pattern_is_anchored() -> None:
    """No pattern may begin matching inside a word.

    Round 4 found `ran` matching the middle of "st-RAN-ge", which turned a user
    who ignored a phishing email into a refused ticket. The instance was easy to
    fix; the class was not, because nothing stopped the next pattern from being
    written the same way. This test is that stop.

    Anchoring the START only is deliberate. A trailing `\\b` would break the
    stemming the patterns rely on ("email" must match "emails", "ask" must match
    "asked"), and a mid-word start is the whole defect.

    A pattern beginning with an escaped literal `\\.` is allowed: a dot cannot
    begin inside a word in the sense that matters, and one pattern legitimately
    starts with the file extension it is looking for.
    """
    offenders: list[str] = []

    for indicator in security.INDICATORS:
        patterns = (
            list(indicator.any_of)
            + [p for group in indicator.all_of for p in group]
            + list(indicator.unless_any)
        )
        for pattern in patterns:
            if not pattern.startswith((r"\b", "\\.")):
                offenders.append(f"{indicator.id}: {pattern!r}")

    assert not offenders, (
        "unanchored pattern(s) — prefix each with \\b so it cannot match "
        "mid-word:\n  " + "\n  ".join(offenders)
    )


def test_no_pattern_has_a_gap_that_can_cross_a_clause() -> None:
    """A variable-length gap must not span a subordinating conjunction.

    Round 5's false positive — "clicked Forgot Password four times BECAUSE the
    first messages were slow" — was proximity standing in for the object
    relation. `_same_clause()` fixes that, but nothing stopped the next pattern
    from being written with a bare `[^.]{0,60}` gap and reopening it, and six
    such gaps were still in the table when the first one was fixed.

    So the rule is enforced rather than remembered, exactly as with anchoring.
    This is the third fix for the wrong-object fault and the second one written
    as a property of the whole table instead of a repair to the instance found;
    the first two were repairs, and a fresh corpus reopened the fault both times.
    """
    # Every quantifier, not just the braced one this file happens to use today.
    # `[^.]{0,60}` was the spelling that caused the defect, but `[^.]*` and
    # `[^.]+` are the same unrestricted gap, and a guard that catches one
    # spelling of a fault is the instance-repair this test exists to replace.
    # `_same_clause()`'s own output is not caught: its `[^.]` is followed by a
    # closing paren, the quantifier sitting outside the tempered group.
    bare_gap = re.compile(r"\[\^\.\]\s*[{*+]")
    offenders: list[str] = []

    for indicator in security.INDICATORS:
        patterns = (
            list(indicator.any_of)
            + [p for group in indicator.all_of for p in group]
            + list(indicator.unless_any)
        )
        for pattern in patterns:
            if bare_gap.search(pattern):
                offenders.append(f"{indicator.id}: {pattern!r}")

    assert not offenders, (
        "pattern(s) with an unrestricted gap — wrap the gap in "
        "security._same_clause(n) so it cannot reach across a clause "
        "boundary:\n  " + "\n  ".join(offenders)
    )


def test_anchoring_is_enforced_where_the_patterns_are_built() -> None:
    """The reusable fragments are shared by several indicators and are the ones
    that actually broke, so they are checked directly rather than only through
    the indicators that happen to use them today."""
    unanchored = [
        pattern
        for group in (security._MESSAGE_OBJECT, security._BEHAVIOUR_CHANGE)
        for pattern in group
        if not pattern.startswith(r"\b")
    ]
    assert not unanchored, f"unanchored shared fragment(s): {unanchored}"


def test_architectural_claim_still_holds() -> None:
    """What the adversarial review did NOT break.

    Once the scan trips, no instruction embedded in the ticket produces a draft.
    The reviewer confirmed this is a property of the code rather than a request.
    This test guards the claim the project actually rests on.
    """
    from msp_tools.models import ErrorCode
    from msp_tools.server import draft_response

    result = draft_response("T-024")
    assert result.ok is False
    assert result.draft is None
    assert result.error_code is ErrorCode.SECURITY_ESCALATION_REQUIRED
