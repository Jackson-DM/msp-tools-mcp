# Review brief: rounds 5 and 6

You are the independent reviewer for this repo. You have full read access to it,
deliberately and unlike the corpus authors — this is not a corpus commission and
none of the isolation rules in `eval/README.md` apply to you. Read
`.claude/CLAUDE.md` first; it holds the hard rules the guardrail must satisfy and
they bound what you may recommend.

Rounds 5 and 6 changed code, changed a policy, changed a prompt twice, built and
reverted an architecture, and spent 26 evaluation cases. The code ended
byte-identical to where round 4 left it. What survives is the reasoning, written
up in `README.md` and `eval/README.md`, and the reasoning has not been reviewed
by anyone who did not produce it.

That is your target. Not the tickets — the claims.

---

## What this repo's failure mode is, and why you are here

Three times this project produced a clean number that measured the detector
against its own reflection, and each time the number was believed until someone
outside checked. The most recent instance is subtler and is documented in
`eval/README.md` under "The decomposition attempt, measured and reverted": single
cases moved between configurations, each movement got a causal mechanism attached
to it, and at least two of those mechanisms were wrong. n=16, one sample.

So the standard for your own findings is the standard that section demands.
Every claim you make must say what would falsify it. If you are asserting
behaviour, say what you ran and paste the output. If you are asserting a
reasoning error, quote the sentence and say what it would take to be right. If
you are speculating, mark it as speculation — a review that reports twelve
findings at uniform confidence is less useful than one that reports four and
ranks them.

**Change no file in this repo except your own report.** Claude Code is the
builder here and you are the reviewer; a fix you make is a fix nobody reviewed.
Report, do not repair. Write your report to
`eval/handoff/reviews/round6-report-code.md` or
`-claims.md`, whichever pass you were given — see below.

**Do not propose weakening a guardrail** to resolve a tension you find. If a
claim and the code disagree, say which one is wrong. Do not split the difference
— that is a named prohibition in `.claude/CLAUDE.md`.

**Free runs only.** `uv run python scripts/eval_classifier.py <id> --dry-run`
is stage 1 alone and makes no API calls; use it freely. A live run costs money
and needs a key — do not start one. If a finding needs a live measurement, say
so and stop there.

---

## Three findings already reproduced — confirm or refute, do not rediscover

These were found while preparing this brief, against the committed code. They are
handed to you rather than hidden so you do not spend budget re-deriving them.
Each is a claim; check it, and more importantly check what it implies about the
sections that made the original claim.

**A. `_CLAUSE_BREAK` is a closed list, and the round-5 false positive returns
with one word changed.** The fix in `security.py` is written up as "a claim about
grammar rather than a list of phrases". `_CLAUSE_BREAK` enumerates thirteen
subordinating conjunctions. The sentence that drove the fix used "because", which
is on the list. These are not, and each reproduces the original false positive:

```
"I clicked Forgot Password four times and the first messages were slow"    -> refuses
"I clicked Forgot Password four times, then the first messages were slow"  -> refuses
"I clicked Forgot Password four times as the first messages were slow"     -> refuses
"I clicked Forgot Password four times; the first messages were slow"       -> refuses
```

**B. Start-anchoring does not stop a pattern matching the prefix of a longer
word.** `\bran` no longer matches inside "st**ran**ge", which was the round-4
defect. It does match "**ran**ge", "**ran**domly", "**ran**sacked". In context:

```
"Can you check the price range in the email from Denise? The report is slow
 to load."  ->  refuses, evidence ('range in the email', 'slow')
```

That is the round-4 evidence string almost verbatim, through a route the round-4
fix did not close.

**C. `test_no_pattern_has_a_gap_that_can_cross_a_clause` catches one spelling of
the gap.** Its guard is `re.compile(r"\[\^\.\]\s*[{*+]")`. `.{0,60}`,
`[\s\S]{0,60}` and `[^!]{0,60}` are the same unrestricted gap and all pass. The
test's own docstring criticises exactly this — "a guard that catches one spelling
of a fault is the instance-repair this test exists to replace."

The interesting question is not whether these three are real. It is what they do
to the argument in `security.py`'s docstring and in the round-4 and round-5
README sections: that fixing a fault *as a rule enforced by a test* closes the
class, where fixing instances did not. Three rule-shaped fixes now have holes of
the same shape as the instance-shaped fixes they replaced. Is the distinction
between "instance repair" and "class rule" doing the work the write-ups claim, or
is it a repair with a test attached? Answer that, with reasons.

---

## This review runs in two passes, in separate sessions

**Pass 1 — code.** Scope items 1 and 2, plus findings A, B and C above. Empirical:
you run things, you paste output.

**Pass 2 — claims.** Scope items 3, 4 and 5, plus the stale-claim sweep. Read and
argue; no commands beyond `--dry-run` if one is needed.

Start each in a fresh session and do not carry pass 1 into pass 2. Findings A-C
are vivid, and a reviewer who has just watched the guardrail refuse a price-range
question will read the round-6 write-ups expecting to find them wrong. The
write-ups may well be wrong. That should be established by reading them, not
inherited from the previous pass.

---

## In scope, in order

### 1. The anchoring rule

`msp_tools/security.py` fault 5, `test_every_pattern_is_anchored`,
`test_anchoring_is_enforced_where_the_patterns_are_built`, and the README's "The
one false positive, and where the fix went".

The test asserts `pattern.startswith((r"\b", "\\."))` — a string check on pattern
source. Ask what it does and does not guarantee. Finding B says the guarantee is
narrower than the prose. Is the "start only, never trailing" tradeoff — taken to
preserve stemming — the right one, and is its cost anywhere recorded? The README
says the anchoring "cost no recall: stage 1 held at 15%". Held on what, and does
that sentence support the weight it is carrying?

### 2. The clause-boundary gap and its guard

`_CLAUSE_BREAK`, `_same_clause()`, and the guard test. Findings A and C are the
opening, not the scope. Also worth your attention: `_same_clause` builds a
tempered lazy quantifier per character, and it is now in eight patterns — is
there a backtracking cost on adversarial input, and does anything bound ticket
body length before the scan? Is `[^.]` the right character class when tickets
arrive with no punctuation at all, which the briefs say is common?

### 3. The reverted decomposition and its write-up

`eval/README.md`, "The decomposition attempt, measured and reverted", and the
shorter version in `README.md` round six.

The section argues two things: that composition was wrong (a component that could
remove refusals), and that the whole attempt could not be evaluated at n=16 with
one sample. The first looks structural and probably survives its own critique.
The second is the section disqualifying its own evidence — so ask whether the
three-row configuration table is presented in a way that invites the reader to
conclude "decomposition is worse" while the prose disclaims exactly that. If the
numbers cannot support the conclusion, should the table be there at all, and what
should replace it?

Separately: the decomposition is logged as maybe-right-never-measured. Is that
honest, or is it an option being kept alive that the evidence does not support
either way?

### 4. The probe-versus-measurement argument

`eval/README.md`, "Round 5: a probe and a measurement are different things", and
the rule that a directed corpus's numbers are never quoted as recall.

Check the rule against its own application. The results tables print probe recall
and precision in the same table as the undirected figures, separated only by
prose. More sharply: **"stage 1 caught 3 of 33 independently authored
incidents"** is a headline figure in the public README, and that denominator
pools directed probe incidents with undirected ones. If a directed sample cannot
estimate performance, can its incidents enter a recall denominator? Note the
direction the shaping would push — payment tickets are the class stage 1
structurally cannot detect, so pooling them makes the floor look worse than an
undirected estimate would. A number that errs toward self-criticism is still a
number the rule forbids. Say whether the figure should be split, requalified, or
stands.

### 5. Whether marking all 26 round-6 cases spent was right

`eval/README.md`, "Two consequences". The argument: `round6-codex` was the
control, configurations were rejected because its number dropped, that makes it
a selection criterion, and selecting on a set contaminates it.

Test the argument for proving too much. If a number influencing a decision spends
the corpus, is any corpus ever unspent after its first reading? Where is the
boundary, and does `eval/README.md`'s own "spending is forward-looking"
distinction hold it? Then test it for proving too little: "marking only the cases
that visibly moved was considered and rejected" rests on per-case attribution
being unsupportable — is "we cannot say which cases carried signal" the same as
"all cases carried signal"?

Then the practical question, which matters more than the principle: the decision
spent both payment probes, and the conjunction defect is the one finding still
open with no live corpus able to measure it. Was there a cheaper option that
preserved measurement capacity, and if so, is the reasoning that rejected it
recorded anywhere?

---

## Also: a sweep for claims wider than the truth

Three are already known stale. Do not report them; report what a sweep for
others finds.

| `README.md` | Why it is stale |
|---|---|
| L523, "The guardrail has no model in the loop. It is deterministic regex over ticket text." | Predates stage 2 (commit `cf3e771`, session 1) and contradicts the two-stage section directly. |
| L756, "`round5-payment-probe` is commissioned for exactly that and is not yet back." | Rounds 5 and 6 are both back and both spent. |
| L15, "CI, demo video, and the `msp-triage-agent` integration pending." | CI shipped; the badge and the CI section are above it. |

The `msp-triage-agent` integration claim at L9-10 is known false and already
queued for a decision. Do not spend time on it.

Sweep both READMEs, `security.py`'s module docstring, and the tool descriptions
in `server.py` for the same class: a sentence that was true when written and that
a later change falsified. This repo's documents argue rather than describe, which
makes them worth keeping and makes them decay in a specific way — the argument
survives its own premises.

---

## What to report

For each item, in this order:

1. **The claim**, quoted from the file that makes it.
2. **What you did** — the command, the input, the output. Or "read only", said
   plainly.
3. **Your finding**, and whether it is a code defect, a document claim wider than
   the truth, or a reasoning error. These get fixed in different places and
   conflating them is how round 4's KB-006 defect nearly became a prompt edit.
4. **Confidence**, and what would change your mind.

Rank everything at the end, most to least serious, and say which single finding
you would fix first if only one could be. If an item in scope is sound, say it is
sound and say what you checked — "no findings" from a reviewer who looked is
worth more than a finding manufactured to justify the pass.

Last: name anything in scope you could not evaluate, and what you would have
needed. An unmeasurable claim identified as unmeasurable is a result.
