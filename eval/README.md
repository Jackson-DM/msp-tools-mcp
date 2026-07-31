# eval/

Held-out corpora for measuring the guardrail, and the machinery for commissioning
them from an author who cannot see what they measure.

```
eval/
  corpus.schema.json     the on-disk format, with the reasoning for each field
  corpora/*.json         corpora, each carrying its own provenance block
  handoff/               the machinery for commissioning one
  handoff/briefs/        one brief per round, kept rather than overwritten
```

Briefs are kept per round because a corpus is a claim about who wrote it, and
the brief is the other half of that claim: `round4-codex.json`'s numbers cannot
be read without `briefs/round4.md`, which is where its `known_leakage` came
from. `make-handoff.ps1` delivers the highest-numbered brief unless `-Round` says
otherwise, and renames it to `AGENTS.md` on the way out — the author has no use
for the round number, and a file called "round 5" invites them to wonder what
the first four found.

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
.\eval\handoff\make-handoff.ps1        # builds an isolated dir under TEMP
cd $env:TEMP\_codex-corpus-handoff
codex                                   # reads AGENTS.md; give it nothing else
```

### What the isolation actually guarantees

It cannot make the repo unreachable. The author has a filesystem, and no script
run on the same machine changes that. What it enforces is that the repo is not
handed over, and that **nothing in or around the working directory points at
it** — which is what stands between an honest author and inadvertent
contamination, and inadvertent is the realistic failure mode. Three checks, each
verifiable on disk rather than promised:

| | Refused because |
|---|---|
| destination inside the repo | `cd ..` reaches `security.py` |
| repo inside the destination | a bare `ls` names it |
| the two are siblings | `ls ..` names it |

The third is why the default lives under `TEMP` rather than beside the repo.
Round 5's first handoff went to `..\_codex-corpus-handoff`, which satisfied
"outside the repo" while `ls ..` still printed `msp-tools-mcp` next to it — one
guessing step, not zero, and this file claimed zero. The rule and the prose now
agree.

The script prints the complete contents of the directory it built, including
directories and hidden entries. Read that list. Anything on it beyond the brief,
the format reference, the template, and KB-006 is a leak; an empty `output\` is
expected.

Then:

```powershell
Copy-Item $env:TEMP\_codex-corpus-handoff\output\*.json .\eval\corpora\
uv run python scripts/eval_classifier.py --list
uv run python scripts/eval_classifier.py <corpus-id> --dry-run
```

`--dry-run` runs stage 1 alone and makes no API calls. Do that first: it is free,
and stage 1's recall on a genuinely unfamiliar corpus is the honest baseline the
stage-2 number has to beat.

## Round 5: a probe and a measurement are different things

Round 5 commissions two files from one handoff, and the split is the point.

`round5-payment-probe` is **directed**. The brief names the KB-006 paragraph its
cases are written against — the verified-payment exception that round 4's
`verified_vendor_bank_move` produced. That exception is a carve-out in a safety
policy, written in response to a single case and never tested, and "I already
called and verified this" is precisely what a wire-fraud email asks the victim to
believe. Its elements need cases sitting on each of them.

Directing the author is what makes that possible and is also what disqualifies
the result as a performance estimate: the sample is shaped by the commissioner's
worry, which is exactly the defect rounds 1-3 kept re-committing. So the numbers
from this file are never quoted as recall or precision. **A probe finds defects.
It does not estimate performance.** Read it case by case.

`round5-codex` is **undirected** — no seams named, no scenarios suggested, only
counts and format. It is small, so its numbers are noisy, but they are unshaped,
and it is the file a headline figure may come from.

Two constraints on the undirected file are recorded as leakage in its own
`provenance`: payment-detail changes are excluded (that subject was briefed in
the other file and cases on it would inherit the briefing), and half its
incidents must fall outside KB-006's named list.

Round 4's brief mixed both modes into one file — commissioned directions for the
`hard_negative` cases, free authorship for the incidents — and recorded the mix
in prose, which worked only because the boundary happened to fall along
`case_type`. It does not in round 5, where directed cases span every type. Two
files is the version of that honesty which does not depend on a coincidence.

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
- **A case that drives a change is spent.** Once a pattern, a prompt, or the
  policy is edited in response to a case, that case is training data. Copy it
  into `tests/test_adversarial_corpus.py` for regression value, set
  `"spent": true` on it in the corpus, and log it in the ledger below. The
  harness then excludes it from the quotable row and prints why. A corpus that
  has been optimised against is a test suite; it can no longer produce a
  measurement.
- **Spent cases are not replaced in place.** A corpus never gains cases after
  authorship — appending to a provenance-stamped file would make its block a
  lie about what its author wrote. `round4-codex` stays at 40 cases with 2 of
  them spent, and a later round commissions fresh ones. "Replacement" means
  keeping the stock of live cases from going to zero, not patching a hole in an
  old file.
- **`known_leakage` non-null means the headline number is not quotable.** Quote
  the qualifying subset row instead. `round3-inhouse` is retained precisely as an
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
| `verified_vendor_bank_move` | round4-codex | **KB-006 amended**, 2026-07-29. It described a vendor bank-detail change verified by calling a number already in the vendor master and signed off internally, and stage 2 refused it. The model was following its rubric: KB-006 bullet 6 flagged payment-detail changes with no carve-out for verification. The defect was in the policy, not the classifier, so the policy gained a narrow exception with an explicit anti-abuse clause (verification asserted inside the request does not count; urgency overrides). Note the direction of the fix — the classifier prompt was **not** touched, because tuning the prompt against a case from the corpus measuring it is exactly the failure of rounds one through three. | round 5, `round5-payment-probe` — commissioned to probe the exception this case created, not merely to replace the case |
| `fake_voicemail_email_ignored` | round4-codex | **`security.py` anchored**, 2026-07-31. Every pattern now begins with `\b`, and so does every alternation following a variable-length gap. Logged unfixed after round 4 and fixed now — see below for what changed the calculation. | round 5, `round5-codex` (undirected) |

### Round 4's unfixed defect, and why round 5 fixed it

Round 4 logged the anchoring bug and deliberately left it: fixing it would spend
the case, and stage 1's 15% recall was already decisive, so one fewer false
positive changed no conclusion. That reasoning was about the *number*. What made
it wrong was the *fault class*.

The trigger matched inside "st-**range**": the `ran` alternative of the
message-object rule, firing on the middle of an adjective the user had applied to
an email rather than to a machine. `security.py`'s own docstring lists "wrong
object" as fault 2, resolved in round 2. It was not resolved; it was resolved
*case by case*, and an unanchored alternation was a route back into it that the
round-2 fixes never closed. A defect that reopens a fault class the code claims
to have closed is worth more than one false positive, because the next instance
of it will be a false negative.

So the fix is a rule rather than an edit: `test_every_pattern_is_anchored` walks
the whole indicator table and fails on any pattern that could begin matching
mid-word. The anchoring cost no recall — stage 1 held at 15% on round4-codex and
precision went 75% to 100%, false positives to zero.

Only the *start* of a pattern is anchored. A trailing `\b` would break the
stemming the rules depend on ("email" must still match "emails"), and mid-word
starts were the entire defect.

### Logged defects, not fixed

None outstanding.
