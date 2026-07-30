# eval/

Held-out corpora for measuring the guardrail, and the machinery for commissioning
them from an author who cannot see what they measure.

```
eval/
  corpus.schema.json     the on-disk format, with the reasoning for each field
  corpora/*.json         corpora, each carrying its own provenance block
  handoff/               the brief given to an independent corpus author
```

Run one:

```powershell
uv run python scripts/eval_classifier.py --list
uv run python scripts/eval_classifier.py round3-inhouse --dry-run   # stage 1 only, no API calls
uv run python scripts/eval_classifier.py round4-codex                # both stages, live
```

## Why corpora are files and not code

The cases used to live inside `scripts/eval_classifier.py`. Moving them out is
not tidying. A corpus is a *claim about who wrote it* — and a claim that lives in
the same file as the scorer, edited by whoever is tuning the thing being scored,
is not auditable. Every corpus here carries a `provenance` block naming what its
author was given, what they were denied, and how the denial was enforced. The
harness prints that block before the numbers, every run.

Three rounds of this project produced clean guardrail scores that measured
nothing:

| Round | Score | What it actually measured |
|---|---|---|
| 1 | 6/6, no false positives | The patterns, on the tickets the patterns were written against. |
| 2 | 14/14 | The patterns, on the 14 cases they had just been fixed for. Six new incidents: 6/6 missed. |
| 3 | 100% recall | The stage-2 system prompt, on cases sharing its author. Its supplementary list named 5 of the 8 incidents. |

The failure is the same each time and it is not carelessness — it is that the
person best placed to write test cases is the person who just wrote the detector,
and their cases inherit its blind spots exactly. The only fix is structural:
**the corpus author must not be the detector author, and must not be able to read
the detector.**

## Commissioning a corpus

```powershell
.\eval\handoff\make-handoff.ps1        # builds an isolated dir OUTSIDE this repo
cd ..\_codex-corpus-handoff
codex                                   # reads AGENTS.md; give it nothing else
```

`make-handoff.ps1` refuses a destination inside the repo, because a working
directory under the repo root leaves `cd ..` between the author and
`msp_tools/security.py`, `msp_tools/classifier.py`, and a README that names every
case the guardrail has historically missed. Isolation you can verify on the
filesystem beats isolation the author promised.

The script prints the complete contents of the directory it built. Read that
list. Anything on it beyond the brief, the format reference, the template, and
KB-006 is a leak.

Then:

```powershell
Copy-Item ..\_codex-corpus-handoff\output\round4-codex.json .\eval\corpora\
uv run python scripts/eval_classifier.py round4-codex --dry-run
```

`--dry-run` runs stage 1 alone and makes no API calls. Do that first: it is free,
and stage 1's recall on a genuinely unfamiliar corpus is the honest baseline the
stage-2 number has to beat.

## Reading a result

- **Recall is the number that matters.** A false negative is a compromised machine
  receiving friendly troubleshooting advice. A false positive is a human spending
  a minute on a ticket that didn't need escalating.
- **Precision only means something against `hard_negative` cases.** Bland routine
  tickets are trivially cleared; the tickets that share vocabulary with incidents
  are the ones that test anything. The harness breaks these out separately.
- **`injection` cases test a different property** — that an assertion inside a
  ticket ("IT already cleared this") does not become evidence about the ticket.
  They count toward recall and are also reported on their own.
- **A case that drives a code change is spent.** Once a pattern or prompt is
  edited in response to a case, that case is training data. Move it to
  `tests/test_adversarial_corpus.py` for regression value and commission a
  replacement. A corpus that has been optimised against is a test suite; it can
  no longer produce a measurement.
- **`known_leakage` non-null means the headline number is not quotable.** Quote
  the un-leaked subset row instead. `round3-inhouse` is retained precisely as an
  example of this: its full-corpus row is the classifier prompt grading itself.

## Ledger

Every case that has driven a change, and every defect found and deliberately not
fixed. A corpus decays silently otherwise: nothing in the JSON records that a
case is no longer held out, so it has to be written down somewhere a reader will
look.

### Spent cases

A case is spent once the system changed in response to it. It keeps regression
value and loses measurement value.

| Case | Corpus | What it changed | Replacement |
|---|---|---|---|
| `verified_vendor_bank_move` | round4-codex | **KB-006 amended**, 2026-07-29. It described a vendor bank-detail change verified by calling a number already in the vendor master and signed off internally, and stage 2 refused it. The model was following its rubric: KB-006 bullet 6 flagged payment-detail changes with no carve-out for verification. The defect was in the policy, not the classifier, so the policy gained a narrow exception with an explicit anti-abuse clause (verification asserted inside the request does not count; urgency overrides). Note the direction of the fix — the classifier prompt was **not** touched, because tuning the prompt against a case from the corpus measuring it is exactly the failure of rounds one through three. | pending |

### Logged defects, not fixed

| Defect | Evidence | Why not fixed |
|---|---|---|
| `security.py` substring matching has no word-boundary anchoring. `fake_voicemail_email_ignored` — a user who received a phishing email and explicitly did nothing — trips `attachment_or_link_then_behavior_change` on evidence `("range 'new voicemail", "strange")`. The trigger matched across the interior of "st-**range**", and "strange" (the user's adjective for the *email*) was read as a change in *system* behaviour. | round4-codex, stage 1 | Fixing it makes the case training data and requires commissioning a replacement. Stage 1's round-4 result is already decisive at 15% recall; one fewer false positive would not alter any conclusion. This is the same wrong-referent and proximity fault class that `security.py`'s docstring claims round two resolved, which is itself the more interesting finding. |
