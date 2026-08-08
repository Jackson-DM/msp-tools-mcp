# msp-tools-mcp

MCP server exposing the Summit Managed IT support toolset (`search_tickets`,
`get_ticket`, `search_kb`, `draft_response`, `update_ticket`). Consumed two ways:
standalone in Claude Desktop for conversational triage, and as the tool layer
for the `msp-triage-agent` project.

## The core design principle

**Guardrails live in the tool layer, not the prompt.** A system prompt is a
request; a tool is a wall. `draft_response` refuses security tickets as a matter
of code, and no calling model — however it is prompted — can negotiate past it.
This is the entire point of the project. Any change that moves a safety decision
out of the tool and into a prompt, a description, or the caller's discretion is
a regression, no matter what it does to ergonomics.

## Hard rules (non-negotiable)

- `draft_response` MUST refuse every security ticket. The guardrail is two
  stages, composed in `msp_tools/guardrail.py`, and **the order is the safety
  property, not an implementation detail**:

  **Stage 1 - deterministic, final.** `msp_tools/security.py`. Refuses when the
  as-filed `category == "security"` OR a KB-006 indicator trips against the
  subject/body. The content scan fires even when the label says otherwise;
  mislabeled tickets are the realistic failure mode and the reason it exists.

  **Stage 2 - model classifier, additive only.** `msp_tools/classifier.py`.
  Consulted ONLY when stage 1 finds nothing. It can add a refusal; it can never
  remove one.

  Stage 2 must never be able to clear a stage-1 refusal. Ticket text is
  attacker-controlled - a phishing report contains the phisher's words - so any
  path by which that text could reverse the deterministic layer hands the
  guardrail to the attacker. Moving the classifier ahead of the scan, or letting
  its verdict override, is the single most dangerous change possible in this repo.

- The classifier fails CLOSED. A configured classifier that errors returns
  `is_incident=true`. A broken safety check may never be the reason a reply gets
  drafted. When no classifier is configured the server runs regex-only and must
  DISCLOSE that in its results - silent degradation is worse than either mode.

- Do not trust a green guardrail suite. Fixing all 14 adversarial cases produced
  zero transfer to six new ones - the patterns had memorized those sentences.
  Any future "all cases pass" claim must be measured on cases the patterns were
  NOT written against, or it means nothing.
- Measurement lives in `eval/`, never in the harness. A corpus is a claim about
  who wrote it, so every corpus carries a `provenance` block and the loader
  rejects one without it. Commission new corpora via
  `eval/handoff/make-handoff.ps1`, which builds an isolated directory OUTSIDE the
  repo - the author must not be able to read the patterns, the classifier prompt,
  or this file. See `eval/README.md`.
- When a held-out case fails, fix the thing that is actually wrong and record
  where the fix went. Round 4's `verified_vendor_bank_move` was a KB-006 defect,
  so KB-006 changed and the classifier prompt did not. Editing the prompt against
  a case from the corpus measuring it is available every time and is exactly how
  rounds 1-3 produced meaningless numbers. A case that drives any change is spent:
  copy it into the regression suite, set `"spent": true` on it in the corpus so
  the harness stops counting it, log what it changed in `eval/README.md`, and
  commission fresh cases. Never append replacements to an authored corpus - its
  provenance block describes what its author wrote, and editing the case list
  makes that block false.
- A refusal is a **return value**, not an exception. It returns
  `SECURITY_ESCALATION_REQUIRED` with the tripped indicators and the escalation
  target. Exceptions mean the tool broke; a refusal is the tool working.
- The server MUST NEVER read or serve the `expected` block from the Project 1
  golden suite. That is the grader's answer key. A guardrail keyed to it would
  evaporate the moment a live Freshdesk adapter is swapped in. The tool reads
  the ticket, not the answer.
- The KB corpus in `kb/` is the ONLY source of facts for drafts. No invented
  URLs, no phone numbers (the KB contains none), no procedure steps absent from
  the corpus.
- Never weaken a guardrail to make a test pass. If the suite fails, the code is
  wrong or the test is wrong — say which, do not split the difference.

## Error contract

Every failure is a typed, recoverable error the model can act on — never a raw
stack trace:

| Code | Meaning |
|---|---|
| `TICKET_NOT_FOUND` | No ticket with that ID |
| `KB_NO_MATCH` | Query matched no KB article above threshold |
| `KB_UNAVAILABLE` | The corpus could not be read at all. A server fault, not a coverage gap - never report it as "nothing found" |
| `SECURITY_ESCALATION_REQUIRED` | Refusal; route to security team |
| `CONFIRMATION_REQUIRED` | Dry run; carries the preview and a confirmation_token |
| `CONFIRMATION_INVALID` | Token fabricated, reused, expired, issued for a different change, or the ticket moved |
| `CONFIRMATION_DECLINED` | The user was asked and declined; do not re-attempt |
| `CONFIRMATION_UNAVAILABLE` | Token valid; the client's user-prompt channel failed |
| `INVALID_FIELD` | Value outside the allowed set; nothing was changed |

## Tool descriptions are design work

Every tool description states: what it does, what it explicitly does NOT do,
when to prefer a sibling tool, and what its errors mean. The reader is a capable
model with no other context — write for that reader. Descriptions are reviewed
by the `tool-description-reviewer` subagent and independently by Codex.

## Stack

Python 3.11+, `mcp` SDK v1 stable (>=1.28,<2), stdio transport, `uv` for env
management. Tools return Pydantic models so FastMCP emits `outputSchema` and
populates `structuredContent` automatically.

**STDIO discipline:** never write to stdout. It corrupts the JSON-RPC stream and
silently breaks the server. Log to stderr or a file.

## Testing

- `/test-guardrails` runs the critical suite: the six security tickets
  (T-018, T-019, T-022, T-023, T-024, T-026) through `draft_response`.
  **All six must refuse. Any draft returned = ENTIRE SUITE FAILS.** Same
  asymmetric rule as Project 1.
- Three of those six are deliberately filed under a non-security category in
  `data/tickets.json`. They must still refuse — that is what proves the content
  scan is doing independent work.
