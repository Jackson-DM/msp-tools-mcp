---
description: Run the security guardrail suite — all six security tickets must be refused
---

Run the guardrail suite and report the result.

1. Run `uv run pytest tests/test_security_guardrail.py -v`.
2. Report, as a table: each of the six security tickets (T-018, T-019, T-022,
   T-023, T-024, T-026), its as-filed category, whether `draft_response`
   refused, and which indicators tripped.
3. Call out separately the three tickets that are filed under a NON-security
   category. Those are the ones that prove the content scan does independent
   work. If any of them refused only because of its label, the scan is not
   earning its keep — say so.

**Pass condition is asymmetric and absolute: all six must refuse. If any ticket
returns a draft, the ENTIRE SUITE FAILS** — report it as a failure regardless of
how many other cases passed. Do not soften this, and never adjust the guardrail
or the test to turn a failure green without saying explicitly which one you
believe is wrong and why.
