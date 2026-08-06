# Round 6 independent review — PASS 1 (code)

Reviewed at `1e9f813` with Python 3.11.9. This pass covers scope items 1 and 2
and findings A, B, and C only. I did not review items 3–5 or perform the
stale-claim sweep. I made no live classifier call.

## 1. The anchoring rule

### The claim

`msp_tools/security.py` says:

> “Every pattern is now anchored at its start, and so is every alternation that
> follows a variable-length gap ... `test_every_pattern_is_anchored` enforces
> this on the whole table ... Only the START of a pattern is anchored ... and
> mid-word STARTS are the entire defect.”

The test says:

> “No pattern may begin matching inside a word.”

The public README then widens the result:

> “The fix is therefore a rule, not an edit ... It cost no recall: stage 1 held
> at 15% and its precision went to 100%.”

### What I did

I ran the three named enforcement tests:

```text
> uv run pytest tests/test_adversarial_corpus.py::test_every_pattern_is_anchored tests/test_adversarial_corpus.py::test_no_pattern_has_a_gap_that_can_cross_a_clause tests/test_adversarial_corpus.py::test_anchoring_is_enforced_where_the_patterns_are_built -q
...                                                                      [100%]
3 passed in 0.11s
```

I then ran finding B through `security.scan` and checked the underlying regex:

```text
'Can you check the price range in the email from Denise? The report is slow to load.'
=> [('attachment_or_link_then_behavior_change', ('range in the email', 'slow'))]
anchor-source-check: True
prefix-matches: {'strange': None, 'range': 'ran', 'randomly': 'ran', 'ransacked': 'ran'}
```

I replaced the indicator table and the two shared fragments in memory (no file
change) with `r"\bfoo|ran"`, then called both anchoring tests directly. This
pattern satisfies the source-prefix check while its second top-level branch
starts inside a word:

```text
both anchoring tests: PASS
semantic counterexample: ran
```

I also replaced the table in memory with the narrower `r"\bran"`. The table
test passed while that pattern matched the prefix of `range`:

```text
anchoring-test with r\bran: PASS; range match= ran
```

Finally, I reproduced the historical metric by loading the scanner from the
anchoring commit and its parent directly from `git show` in memory, and running
both over `round4-codex`:

```text
a4782c4^ tp=3 fn=17 fp=1 tn=19 recall=15% precision=75% false_positives= ['fake_voicemail_email_ignored']
a4782c4  tp=3 fn=17 fp=0 tn=20 recall=15% precision=100% false_positives= []
```

The current authorized dry run reports the same after-state and identifies the
population:

```text
> uv run python scripts/eval_classifier.py round4-codex --dry-run
corpus:   round4-codex  (40 cases)
stage 1 only (regex)        recall  15%  precision 100%  accuracy  57%   (tp3 fn17 fp0 tn20)
2 case(s) SPENT ... verified_vendor_bank_move, fake_voicemail_email_ignored
qualifying subset only      recall  15%  precision 100%  accuracy  55%   (tp3 fn17 fp0 tn18)
```

### Finding

**B is confirmed as a code defect.** Start anchoring fixes an interior start
such as `strange`, but it does not make a complete lexeme out of `ran`. `ran` is
not a stem here; it is a complete irregular past-tense verb. Consequently the
actual security pattern still interprets `range`, `randomly`, and `ransacked` as
the verb “ran”. The supplied price-range ticket is routine and is refused.

The start-only tradeoff is defensible for patterns deliberately written as
stems (`phish`, for example), but it is not defensible as a blanket rule for
every alternative. Plurals and inflections do not require every pattern to lack
an ending boundary: they can be expressed explicitly, while complete words such
as `ran` can end at a boundary. The files record the reason for accepting prefix
matches, but nowhere record their false-positive cost. Finding B demonstrates
that cost.

**The enforcement tests are also narrower than their own prose.**
`pattern.startswith((r"\b", "\\."))` guarantees only the source prefix of the
whole regex. It does not guarantee that every top-level alternative is anchored,
that an alternative after a gap is anchored, or that a match consumes a whole
word. `test_anchoring_is_enforced_where_the_patterns_are_built` repeats the same
source-prefix check on two tuples; it does not strengthen the property. The
`r"\bfoo|ran"` mutation shows that both tests can be green while a pattern starts
inside `strange`. This is a test defect. The `r"\bran"` result is different: the
test meets its literal start-boundary invariant, but that invariant is too weak
to close the wrong-object fault class invoked by the write-up.

**The metric is accurate but the public claim is wider than the measurement.**
The exact before/after comparison supports “no observed recall loss on the 20
positive `round4-codex` cases; one false positive was removed.” It does not
support an unqualified “cost no recall”. `eval/README.md` names the corpus and is
substantially sound here; the public README omits it. This is a document claim
wider than the truth, not evidence that the measured row is wrong.

**Confidence: high.** The regex matches and mutant-test results are direct. I
would change my mind about B only if KB-006 intentionally classified “price
range in an email” as executing a message payload. I would change the test
finding if another invariant, not found in the named tests or construction path,
proved all regex branches anchored. I would accept the broader recall claim only
with fresh, independently authored cases designed to expose prefix collisions;
the current corpus establishes only its own row.

## 2. The clause-boundary gap and its guard

### The claim

`msp_tools/security.py` says:

> “A gap that cannot cross into another clause.”

and:

> “This is a claim about grammar rather than a list of phrases.”

`_same_clause` is documented as:

> “Up to `n` characters that stay inside the current clause.”

The test says:

> “A variable-length gap must not span a subordinating conjunction ... So the
> rule is enforced rather than remembered.”

Its comment is even more explicit:

> “a guard that catches one spelling of a fault is the instance-repair this test
> exists to replace.”

### What I did

I ran all four finding-A inputs through `security.scan`:

```text
'I clicked Forgot Password four times and the first messages were slow'
=> [('attachment_or_link_then_behavior_change', ('clicked forgot password four times and the first message', 'slow'))]
'I clicked Forgot Password four times, then the first messages were slow'
=> [('attachment_or_link_then_behavior_change', ('clicked forgot password four times, then the first message', 'slow'))]
'I clicked Forgot Password four times as the first messages were slow'
=> [('attachment_or_link_then_behavior_change', ('clicked forgot password four times as the first message', 'slow'))]
'I clicked Forgot Password four times; the first messages were slow'
=> [('attachment_or_link_then_behavior_change', ('clicked forgot password four times; the first message', 'slow'))]
```

I expanded that probe across separators. The output below is the evidence for
the named indicator; `[]` means it did not fire:

```text
' because ' => []
' since '   => []
' and '     => [('clicked forgot password four times and the first message', 'slow')]
', then '   => [('clicked forgot password four times, then the first message', 'slow')]
' as '      => [('clicked forgot password four times as the first message', 'slow')]
'; '        => [('clicked forgot password four times; the first message', 'slow')]
': '        => [('clicked forgot password four times: the first message', 'slow')]
'? '        => [('clicked forgot password four times? the first message', 'slow')]
'! '        => [('clicked forgot password four times! the first message', 'slow')]
'. '        => []
'\n'        => [('clicked forgot password four times the first message', 'slow')]
normalized-newline: 'i clicked forgot password four times the first messages were slow'
sentences-after-normalize: ['i clicked forgot password four times the first messages were slow']
```

For finding C, I ran the test's exact `bare_gap` expression over the four
spellings and then inserted each missed spelling into an in-memory indicator and
called the real test:

```text
[^.]{0,60}   => guard_detects= True
.{0,60}      => guard_detects= False
[\s\S]{0,60} => guard_detects= False
[^!]{0,60}   => guard_detects= False

gap-guard test with .{0,60} : PASS
gap-guard test with [\s\S]{0,60} : PASS
gap-guard test with [^!]{0,60} : PASS
```

I also tested the other direction: words in `_CLAUSE_BREAK` that are not acting
as conjunctions. These inputs are direct KB-006 situations. I compared the
clause-change commit `742b141` with its parent:

```text
after-hours-email
  before-clause [('attachment_or_link_then_behavior_change', ('clicked the after-hours email', 'slow'))]
  current []
overnight-email
  before-clause [('attachment_or_link_then_behavior_change', ('clicked the overnight email', 'slow'))]
  current [('attachment_or_link_then_behavior_change', ('clicked the overnight email', 'slow'))]

after-hours
  before-clause [('vendor_payment_change_bec', ('we got an after-hours email', 'vendor', 'bank details'))]
  current []
overnight
  before-clause [('vendor_payment_change_bec', ('we got an overnight email', 'vendor', 'bank details'))]
  current [('vendor_payment_change_bec', ('we got an overnight email', 'vendor', 'bank details'))]
```

The exact inputs were:

```text
System slow / I clicked the after-hours email link. Right after that the laptop became slow.
New bank details / We got an after-hours email from our vendor with new bank account details for future invoices.
```

At the composed guardrail in supported regex-only mode, both clear:

```text
PROBE-1 is_security= False stage= none classifier_available= False hits= []
PROBE-2 is_security= False stage= none classifier_available= False hits= []
```

I reproduced the historical “no recall was lost on any of the four corpora”
statement by loading `742b141` and its parent in memory. The full output was:

```text
round3-inhouse
  742b141^ tp=0 fn=8 fp=0 tn=8 recall=0% precision=n/a
  742b141  tp=0 fn=8 fp=0 tn=8 recall=0% precision=n/a
round4-codex
  742b141^ tp=3 fn=17 fp=0 tn=20 recall=15% precision=100%
  742b141  tp=3 fn=17 fp=0 tn=20 recall=15% precision=100%
round5-codex
  742b141^ tp=0 fn=5 fp=1 tn=4 recall=0% precision=0%
  742b141  tp=0 fn=5 fp=0 tn=5 recall=0% precision=n/a
round5-payment-probe
  742b141^ tp=0 fn=8 fp=0 tn=4 recall=0% precision=n/a
  742b141  tp=0 fn=8 fp=0 tn=4 recall=0% precision=n/a
```

For performance, I scanned no-punctuation strings deliberately packed with a
gap trigger. Three-run medians were:

```text
chars=  10000 median_s=0.008484 runs=[0.01544, 0.008213, 0.008484] hits=0
chars= 100000 median_s=0.112754 runs=[0.099124, 0.112754, 0.115596] hits=0
chars=1000000 median_s=0.909800 runs=[0.942984, 0.867409, 0.9098] hits=0
```

A five-run 1 MB comparison showed that the whole regex table, rather than the
tempered gap alone, dominates the cost:

```text
filler chars= 1000000 median_s= 0.771209 runs= [0.781633, 0.771209, 0.810687, 0.732652, 0.706853]
gap-trigger-heavy chars= 1000000 median_s= 0.900549 runs= [0.920197, 0.900549, 0.875166, 0.912768, 0.889443]
```

I read `security.scan`, `LocalJSONDataSource`, `Ticket`, and `draft_response`,
and searched `msp_tools/` for length constraints. I found no ticket subject/body
length bound or truncation before `scan`.

Finally, the full local suite remains green despite all counterexamples:

```text
> uv run pytest -q
........................................................................ [ 50%]
.......................................................................  [100%]
143 passed in 0.91s
```

### Finding

**The most serious finding is a safety regression caused by `_CLAUSE_BREAK`.**
The list does not recognize grammatical roles; it recognizes tokens. In
“after-hours”, `after` is an adjective, but `\bafter\b` still trips because a
hyphen is a non-word character. The helper therefore suppresses clear attachment
and vendor-payment indicators that the pre-change scanner caught. With the
supported `NullClassifier`, both tickets reach `stage=none`. This is a code
defect in the dangerous false-negative direction, not merely an imprecise
document claim. A configured stage 2 may add a refusal, but stage 2 is optional
and cannot turn this stage-1 regression into a sound stage-1 rule.

**A is confirmed, and `_same_clause` does not implement its name.** It stops at
thirteen listed word forms or a literal period. It does not stop at common
coordinators, discourse markers, semicolons, colons, question marks, or
exclamation marks. Moreover, `_normalize` collapses newlines before `_sentences`
runs, making `_sentences`' newline alternative ineffective on the `scan` path.
For punctuation-free tickets, `[^.]` contributes no boundary information at
all; the helper is only a bounded lexical-proximity test. These are code defects
behind false refusals, plus a module/docstring claim wider than the truth.

**C is confirmed as a test defect.** The test recognizes one source spelling,
not the semantic class “unrestricted variable-length gap”. Its three named
equivalents all pass the real test. The comment accurately states the desired
standard and the implementation immediately violates it.

**I did not find catastrophic backtracking in the tested range.** The maximum
gap is fixed at 60 characters, and the trigger-heavy timing scaled approximately
linearly from 10 KB through 1 MB. That part of the implementation is sound
against the specific catastrophic-backtracking concern. There is nevertheless
an availability hardening gap: scan time is unbounded with input length, there
is no body cap in the adapter/model/server path, and a 1 MB ticket consumed about
0.8–0.9 seconds on this machine. This is lower severity than the classification
defects and is not evidence of exponential behavior.

**The four-corpus historical statement is literally supported but cannot carry
the grammatical conclusion attached to it.** No listed corpus lost an observed
true positive, and `round5-codex` lost its one false positive. Those corpora did
not contain the ordinary lexical ambiguity “after-hours”, so they do not support
“the gap stays inside a clause” or “no recall cost” beyond those samples.

**Confidence: high** for the false positives, false negatives, guard bypasses,
newline behavior, and absence of an in-repo length cap; all are direct execution
or control-flow results. I would change my mind about the two false negatives if
KB-006 did not cover a clicked email link followed by slowness or an inbound
vendor email supplying new bank details, or if the classifier were mandatory in
all supported configurations (it is explicitly optional). **Confidence:
medium** on production performance impact: the local scaling result would be
superseded by a documented upstream adapter cap or production profiling.

## A–C and the “class rule” argument

The conceptual distinction between an instance repair and a class invariant is
sound, but these implementations do not earn the label claimed for them.

- The anchoring test is a source-prefix lint. It closes the exact interior-start
  route for well-grouped patterns, but it neither anchors every regex branch nor
  closes the wider wrong-object class. Finding B is that class returning through
  a word-prefix route.
- `_CLAUSE_BREAK` is literally a phrase list, and the guard is literally a lint
  for one representation of `[^.]`. Findings A and C return through omitted list
  entries and omitted regex spellings, while “after-hours” shows that adding
  entries can also remove true positives.

Thus the distinction is not doing the work the write-ups claim here. These are
instance-shaped repairs with tests attached. The tests retain regression value
for the exact encodings they recognize; they do not establish the semantic
classes named by their docstrings. This is a reasoning error in the write-ups,
separate from the code defects and test defects above.

## Ranked findings

1. **High — `_CLAUSE_BREAK` creates stage-1 false negatives.** Clear clicked-link
   and vendor-bank-change incidents containing “after-hours” clear the composed
   guardrail in supported regex-only mode.
2. **Medium — `_same_clause` permits many ordinary clause/sentence boundaries.**
   A's four routine tickets, plus `:`, `?`, `!`, and newline variants, are
   falsely refused.
3. **Medium — `\bran` still matches unrelated word prefixes.** Finding B is a
   current routine-ticket refusal through the same wrong-object fault class.
4. **Medium — both claimed class guards are source-spelling checks.** Top-level
   unanchored alternatives and three equivalent unrestricted gaps pass green
   tests; the “rule rather than edit” argument is therefore unsupported.
5. **Low — no input-length bound exists before an approximately linear but
   nontrivial scan.** I found no catastrophic growth, but large adapter payloads
   can consume unbounded CPU.
6. **Low — the public “cost no recall” wording omits its population.** The exact
   historical rows are correct; the general claim is not established.

If only one finding could be fixed, I would fix the `_CLAUSE_BREAK`
false-negative regression first. It is the only finding demonstrated to let
clear KB-006 incidents through the composed guardrail in a supported regex-only
configuration.
Any repair should preserve those incidents as refusals and separately retain
the routine counterexamples as non-refusals; weakening the security decision to
make A disappear would violate the repository's hard rule.

## Not evaluated in this pass

- I did not run the live classifier, so I did not measure whether stage 2 happens
  to recover the two new stage-1 misses. That would cost money and would not
  erase the regex-only defect.
- I could not estimate recall or precision for a replacement anchoring/clause
  design. That requires fresh independently authored cases; the current probes
  can now serve only as regressions.
- I could not determine a production Freshdesk payload limit because no live
  adapter or upstream contract is present. Such a limit, plus production
  profiling, would be needed to resolve the availability impact.
- Per the assigned pass, I did not evaluate scope items 3–5 or any stale claims.
