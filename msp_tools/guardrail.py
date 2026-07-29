"""Composes the two guardrail stages into one decision.

    stage 1  deterministic KB-006 scan   (security.py)   — the floor
    stage 2  model classifier            (classifier.py) — the recall layer

ORDER IS THE SAFETY PROPERTY
----------------------------
Stage 1 runs first and is final. Stage 2 is consulted only when stage 1 found
nothing, and its only possible effect is to add a refusal.

This is what keeps attacker-controlled ticket text out of the decision that
matters. A phishing report necessarily contains the phisher's words; if those
words could reach a component whose output could clear a ticket, the guardrail
would be handed to the attacker. Here the worst a successful injection achieves
is failing to escalate something the regex already missed — it cannot reverse a
refusal, and there is no path from ticket text to a draft.

The category label is checked too, but is neither necessary nor sufficient: a
ticket filed as "security" refuses, and a ticket filed as "hardware" still
refuses when either stage flags it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from msp_tools import security
from msp_tools.classifier import Classifier, NullClassifier, Verdict
from msp_tools.security import IndicatorHit


@dataclass(frozen=True)
class Assessment:
    is_security: bool
    hits: list[IndicatorHit] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    stage: str = "none"
    """Which stage decided: 'label', 'scan', 'classifier', or 'none'."""
    classifier_available: bool = False
    """False means regex-only mode — recall is materially lower. Disclose it."""
    verdict: Verdict | None = None


def assess(ticket: dict, classifier: Classifier | None = None) -> Assessment:
    """Decide whether a ticket is a security incident."""
    classifier = classifier or NullClassifier()

    # --- stage 1: label + deterministic scan. Final if it fires. -----------
    is_sec, hits, reasons = security.is_security_ticket(ticket)
    if is_sec:
        stage = "scan" if hits else "label"
        return Assessment(
            is_security=True,
            hits=hits,
            reasons=reasons,
            stage=stage,
            classifier_available=not isinstance(classifier, NullClassifier),
        )

    # --- stage 2: recall layer. Can only add a refusal. --------------------
    verdict = classifier.classify(ticket.get("subject", ""), ticket.get("body", ""))

    if verdict.is_incident:
        if verdict.failed:
            reason = (
                "security classifier was unavailable; refusing by default because a "
                "broken safety check must never be the reason a reply gets drafted"
            )
        else:
            detail = "; ".join(verdict.indicators) or verdict.rationale
            reason = (
                "deterministic scan found nothing, but the security classifier "
                f"flagged this ticket: {detail}"
            )
        return Assessment(
            is_security=True,
            hits=[],
            reasons=[reason],
            stage="classifier",
            classifier_available=verdict.available,
            verdict=verdict,
        )

    return Assessment(
        is_security=False,
        stage="none",
        classifier_available=verdict.available,
        verdict=verdict,
    )
