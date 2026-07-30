"""Tests OF the test harness — that its isolation fixtures actually isolate.

WHY THIS FILE EXISTS
--------------------
`server.CLASSIFIER` is built at import time from `MSP_TOOLS_CLASSIFIER` and
`ANTHROPIC_API_KEY`. Running the suite in a shell where the classifier had been
enabled for an eval therefore made live API calls: 106 seconds instead of one,
non-deterministic results, and a failure in the test asserting regex-only
disclosure. In a clean shell everything passed, so the only visible symptom was
the runtime.

`tests/conftest.py` fixes that. This file makes sure it keeps working, because a
silently-regressed isolation fixture reproduces the original bug exactly — the
suite goes green, gets slow, and starts costing money.

It lives in its own module rather than beside the fixtures in `conftest.py`,
because pytest does not collect tests from `conftest.py` during a normal run. A
check that only fires when someone explicitly targets it is the same category of
mistake as the one it guards against: a rule that holds by habit.

The property is asserted directly rather than inferred from how long the suite
took. A wall-clock threshold is a proxy — it fails open on a slow runner, and it
passes for the wrong reason on a machine where the SDK cannot construct at all.
"""

from __future__ import annotations

import os

from msp_tools import server
from msp_tools.classifier import NullClassifier


def test_server_classifier_is_pinned_to_regex_only() -> None:
    assert isinstance(server.CLASSIFIER, NullClassifier), (
        f"server.CLASSIFIER is {type(server.CLASSIFIER).__name__}, not NullClassifier. "
        "The suite is talking to a live classifier: results are non-deterministic, "
        "slow, and billed. tests/conftest.py should have prevented this."
    )


def test_classifier_env_vars_are_invisible_to_tests() -> None:
    """Anything constructing a classifier mid-test must also get regex-only,
    not just the module-level instance the other fixture pins."""
    assert not os.environ.get("ANTHROPIC_API_KEY"), (
        "ANTHROPIC_API_KEY is visible to tests; a classifier built during a test "
        "could reach the API"
    )
    assert not os.environ.get("MSP_TOOLS_CLASSIFIER"), (
        "MSP_TOOLS_CLASSIFIER is visible to tests; build_default would return a "
        "live client"
    )


def test_build_default_returns_null_under_test() -> None:
    """The end-to-end version of the two above: whatever the ambient environment
    says, constructing a classifier from it inside a test yields regex-only."""
    from msp_tools.classifier import build_default

    assert isinstance(build_default(server.KB_DIR), NullClassifier)


def test_confirmation_store_starts_empty() -> None:
    """Pending write tokens must not leak between tests. The store is
    module-level so a token can outlive a single tool call, which is right for
    the server and would be a cross-test dependency here."""
    assert len(server.CONFIRMATIONS) == 0
