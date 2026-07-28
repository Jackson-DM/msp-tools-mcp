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

- `draft_response` MUST refuse every security ticket. Refusal is decided by
  two independent layers, and **the category label alone is never sufficient**:
  1. the ticket's as-filed `category == "security"`, OR
  2. the content scan in `msp_tools/security.py` trips a KB-006 indicator
     against the subject/body.
  Layer 2 fires even when the label says otherwise. Mislabeled tickets are the
  realistic failure mode and the reason the scan exists.
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
| `SECURITY_ESCALATION_REQUIRED` | Refusal; route to security team |
| `CONFIRMATION_REQUIRED` | Write attempted without `confirm=True` |

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
