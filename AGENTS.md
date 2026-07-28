# msp-tools-mcp — agent instructions

**Single source of truth: [`.claude/CLAUDE.md`](.claude/CLAUDE.md).**

This file is an entry point for agents that look for `AGENTS.md` (Codex and
others). To avoid drift, the project rules, guardrail constraints, and stack
notes are maintained in one place — `.claude/CLAUDE.md` — rather than
duplicated here. Read that file before doing any work in this repo.

## If you are reviewing (Codex)

The security guardrail in `msp_tools/security.py` and `draft_response` in
`msp_tools/server.py` are the parts worth your attention. Review them
adversarially: your job is to find the ticket that should be refused and isn't.
See `.claude/CLAUDE.md` for the hard rules the guardrail must satisfy.
