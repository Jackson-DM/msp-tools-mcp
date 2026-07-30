"""Test-suite invariants that must not depend on the shell they run in.

WHY THIS FILE EXISTS
--------------------
`server.CLASSIFIER` is built at import time from `MSP_TOOLS_CLASSIFIER` and
`ANTHROPIC_API_KEY`. That is correct for the server and wrong for the tests: it
meant the suite's behaviour depended on ambient environment variables. Running
`uv run pytest` in a shell where the classifier had been enabled for an eval run
produced a different result from running it in a fresh shell — the suite made
live API calls, took 106s instead of seconds, and failed
`test_draft_discloses_regex_only_mode`, which asserts the regex-only disclosure
that a configured classifier correctly suppresses.

The README claimed the suite "makes no API calls, keeping the suite
deterministic". That was true by convention, not by construction, which is the
failure mode this whole repo argues against. So it is enforced here instead.

Tests that want stage 2 inject a `StubClassifier` explicitly, at the call site,
where a reader can see it.
"""

from __future__ import annotations

import pytest

from msp_tools import server
from msp_tools.classifier import NullClassifier


@pytest.fixture(autouse=True)
def _deterministic_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the server to regex-only for every test, whatever the environment says.

    Autouse and unconditional. An opt-in fixture would leave the default path
    environment-dependent, which is the bug.
    """
    monkeypatch.setattr(server, "CLASSIFIER", NullClassifier())


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt and braces: nothing constructed mid-test can reach the API either.

    A test that builds its own classifier from the environment gets a
    NullClassifier rather than a live client, so an accidental network call
    fails loudly at write time instead of quietly costing money and passing.
    """
    monkeypatch.delenv("MSP_TOOLS_CLASSIFIER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
