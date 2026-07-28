"""Generate data/tickets.json — the helpdesk ticket store the MCP server serves.

Source: the 26-case golden suite from msp-triage-agent. Each golden case has an
`input` block (what actually arrived from the requester) and an `expected` block
(the grader's answer key).

THE LINE THIS SCRIPT DRAWS
--------------------------
Only `input` becomes a served ticket. The `expected` block never reaches
data/tickets.json and the MCP server never sees it. That matters for two
reasons:

  1. A real Freshdesk ticket has no `expected` field. A guardrail keyed to one
     would evaporate the instant a live adapter is swapped in — which is exactly
     what Project 1's data-source adapter rule exists to prevent.
  2. If `draft_response` refused by reading the answer key, the refusal would
     prove nothing. The tool has to reach its own conclusion from the ticket.

Everything else on the record is *intake metadata*: what a front-line queue
would have recorded when the ticket was filed. It is generated here, at build
time, and it is deliberately imperfect.

THE MISLABELS ARE THE POINT
---------------------------
Three of the six security tickets are filed under a non-security category,
because that is the realistic intake failure — nobody files their own incident
as "security". They are the cases that prove the content scan in
msp_tools/security.py does independent work rather than reading a label:

    T-018  ransomware ("files have a weird extension")     filed: software_licensing
    T-022  browser hijack ("annoying popups everywhere")   filed: software_licensing
    T-024  post-attachment compromise ("screen looks weird") filed: hardware

Consequence, and the demo beat: `search_tickets(category="security")` returns
three tickets. `draft_response` refuses six.

Run:  uv run python scripts/build_tickets.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO.parent / "msp-triage-agent" / "evals" / "golden_tickets.json"
OUT = REPO / "data" / "tickets.json"

# Security tickets deliberately filed under the wrong category at intake.
MISFILED: dict[str, str] = {
    "T-018": "software_licensing",
    "T-022": "software_licensing",
    "T-024": "hardware",
}

TECHS = ["priya.raman", "marcus.hale", "j.okonkwo", "sara.lindqvist"]

# Deterministic build — the committed file must be reproducible.
SEED = 20260727
# Ticket clock anchored to a fixed date so regenerating does not churn the diff.
NOW = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


def build() -> dict:
    if not GOLDEN.exists():
        raise SystemExit(
            f"golden suite not found at {GOLDEN}\n"
            "Expected msp-triage-agent to sit beside this repo. Adjust GOLDEN if it moved."
        )

    rng = random.Random(SEED)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    tickets = []

    for i, case in enumerate(golden["tickets"]):
        tid = case["id"]
        src = case["input"]
        sender = src.get("sender", {})

        # As-filed category: intake metadata, not ground truth. For non-security
        # tickets the golden category is a fine stand-in for what a queue would
        # have recorded. For the three misfiled security tickets it is wrong on
        # purpose. Read at BUILD time only — never served, never at runtime.
        true_category = case["expected"].get("category")
        filed_category = MISFILED.get(tid, true_category)

        # Status/tier/assignee are generated from queue state, never from the
        # answer key — expected.tier and expected.priority are decisions the
        # agent is supposed to make, so copying them would leak the answer.
        roll = rng.random()
        if roll < 0.6:
            status, assignee = "open", None
        elif roll < 0.85:
            status, assignee = "pending", rng.choice(TECHS)
        else:
            status, assignee = "resolved", rng.choice(TECHS)

        # Front-line intake lands everything at tier 1; only worked tickets have
        # been moved up by a human.
        tier = 1 if status == "open" else rng.choice([1, 2])

        # As-filed priority reflects what intake typed in, which is noisy by
        # nature — users mark everything urgent.
        filed_priority = rng.choice(["low", "medium", "medium", "high"])

        created = NOW - timedelta(hours=rng.randint(2, 96), minutes=rng.randint(0, 59))
        updated = created + timedelta(minutes=rng.randint(5, 600))

        tickets.append(
            {
                "ticket_id": tid,
                "client": sender.get("company", "unknown"),
                "requester": {
                    "name": sender.get("name", "unknown"),
                    "role": sender.get("role", "unknown"),
                },
                "channel": src.get("channel", "email"),
                "subject": src.get("subject", "(no subject)"),
                "body": src.get("body", ""),
                "category": filed_category,
                "priority": filed_priority,
                "status": status,
                "tier": tier,
                "assignee": assignee,
                "created_at": created.isoformat().replace("+00:00", "Z"),
                "updated_at": updated.isoformat().replace("+00:00", "Z"),
            }
        )

    tickets.sort(key=lambda t: t["ticket_id"])
    return {
        "store": "summit-managed-it-synthetic",
        "version": "1.0",
        "generated_from": "msp-triage-agent/evals/golden_tickets.json (input blocks only)",
        "note": (
            "Category/priority/tier/status are as-filed intake metadata and are "
            "not authoritative. Three security tickets are misfiled on purpose; "
            "see scripts/build_tickets.py. The grader's expected block is never "
            "included here."
        ),
        "tickets": tickets,
    }


def main() -> None:
    store = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")

    n = len(store["tickets"])
    filed_sec = sum(1 for t in store["tickets"] if t["category"] == "security")
    print(f"wrote {OUT.relative_to(REPO)}  ({n} tickets)")
    print(f"  filed as security: {filed_sec}")
    print(f"  misfiled security: {len(MISFILED)}  -> {', '.join(sorted(MISFILED))}")
    print(f"  actual security:   {filed_sec + len(MISFILED)}")


if __name__ == "__main__":
    main()
