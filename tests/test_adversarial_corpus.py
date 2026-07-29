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
]


@pytest.mark.parametrize(
    "case_id,bullet,subject,body",
    [pytest.param(*c, id=c[0]) for c in MISSED_INCIDENTS],
)
@pytest.mark.xfail(
    strict=True,
    reason="Known gap from adversarial review — indicator vocabulary too narrow. "
    "When fixed, remove this marker.",
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
@pytest.mark.xfail(
    strict=True,
    reason="Known gap from adversarial review — all_of matches co-occurrence "
    "without proximity or causality. When fixed, remove this marker.",
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
