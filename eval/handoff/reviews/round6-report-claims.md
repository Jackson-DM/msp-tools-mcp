# Round 6 independent review — pass 2 (claims)

Scope was limited to items 3, 4, and 5 in `round6.md`, followed by the requested
stale-claim sweep. I did not review items 1 or 2, findings A–C, or the separate
code-pass report. This was a read-only review of the relevant prose and corpus
metadata; I ran no classifier evaluation, live or dry-run.

## 3. The reverted decomposition and its write-up

### Claim

`eval/README.md` says:

> It was built, measured three ways, and reverted. All three were worse than the
> prompt-only baseline on the direction that matters.

It then labels the columns `probe recall` and `undirected recall`, bolds the
prompt-only scores, and later says:

> On sixteen cases, one sample per configuration, iterating against a corpus
> already spent, there is no way to distinguish a fix from a coin flip.

The public `README.md` repeats the first conclusion more strongly: the heading
calls the attempt a failure, and the body says **“all three were worse than the
prompt”** before explaining that the comparison could not identify an effect.

### What I did

Read only. I compared the configuration table and its lead-in with the
qualification immediately below it and with the shorter round-six account in
`README.md`. I did not rerun any configuration: the handoff prohibits live runs,
the implementations were reverted, and the documents themselves say the
single-sample readings cannot license a comparison.

### Finding

**Reasoning error; the document claim is wider than its evidence.** The text does
not merely invite the inference that decomposition was worse; it states that
inference. The later disclaimer retracts the evidential basis without retracting
the conclusion. Both cannot stand. The observed point readings are facts about
those calls, but “all three were worse” is a comparative claim about the
configurations, exactly what one sample on an iterated-against corpus cannot
support.

The table has audit value because it shows which numbers were used as selection
criteria and therefore helps explain why the corpora were spent. It has no
performance-estimation value. In the main argument it should be replaced by a
decision log: configuration attempted, whether it was monotone, which corpus was
consulted, and disposition. If the raw readings are retained for audit, they
should be explicitly labelled “single-call session observations; not comparable
performance estimates,” with no bold winner, no `recall` heading for the probe,
and no “worse” conclusion.

The composition finding itself is structurally sound, with a necessary
qualification. The initial authoritative form allowed one component to clear a
refusal from another. Given model-derived observations from attacker-controlled
ticket text, that violates this repo’s monotonic safety rule independently of
the noisy case movements. What would falsify the historical implementation claim
is a preserved implementation showing that no such clearing path existed; it is
not present in the current tree. The principle does not need the configuration
scores.

However, the blanket follow-up — **“The reasoning may still be right; it was
never measured well enough to say”** — keeps too much alive. The authoritative
variant is already ruled out structurally. The additive variants remain
empirically unresolved, but by construction they cannot fix over-refusal: if the
holistic verdict refuses a legitimate exception, an additive rule cannot clear
it. The honest surviving claim is narrower: additive decomposition may improve
missed-incident recall without weakening monotonicity, but its performance is
unmeasured and it is not a complete implementation of the exception in both
directions.

**Confidence: high** on the unsupported comparison and structural monotonicity
finding; **medium-high** on how narrowly the remaining option should be stated.
Repeated paired sampling on fresh, unspent corpora, with configurations and a
comparison threshold fixed in advance, would change the empirical conclusion.
A design using trustworthy non-model facts, rather than model-extracted facts,
could also change the structural analysis.

## 4. The probe-versus-measurement argument

### Claim

`eval/README.md` states the rule clearly:

> So the numbers from this file are never quoted as recall or precision. **A
> probe finds defects. It does not estimate performance.** Read it case by case.

The same file nevertheless prints `round5-payment-probe` as 0%/88% recall and
precision, calls the round-six directed score `recall`, and labels the
decomposition column `probe recall`. More importantly, it says:

> **Stage 1 caught 0 of 13 incidents.** With round 4 that is **3 of 33** on
> independently authored cases.

The public README promotes the pooled value twice: **“3 of 33 independently
authored incidents”** and **“Stage 1 catches 3 of 33 incidents on unfamiliar
language.”**

### What I did

Read only. I traced the denominator through the three corpus descriptions and
case metadata. It consists of 20 expected-refusal cases from round 4, five from
the undirected `round5-codex`, and eight from the directed payment probe. The
documents report that stage 1 caught 3, 0, and 0 respectively.

### Finding

**Reasoning and measurement error.** The rule is sound and its application
violates it. A percentage in a results table under a `recall` or `precision`
label is quoting probe recall or precision; saying the row exists only as a
case-by-case header does not alter what is printed. Pooling the eight directed
expected-refusal cases into 3/33 is the sharper violation. Independent authorship
prevents detector-author leakage; it does not make a directed sample an
undirected performance sample.

The shaping pushes toward self-criticism: payment-detail tickets are the seam
stage 1 systematically misses, so adding them makes the floor look worse. That
does not rescue the estimate. Bias in an unfavorable direction is still bias,
and the repo’s rule is about what the sample can estimate, not whether the
result flatters the system.

The defensible split is:

- **Undirected measurement:** stage 1 caught 3 of 25 expected-refusal cases from
  round 4’s unbriefed incident side and `round5-codex`, with the existing
  small-sample and corpus-provenance qualifications.
- **Directed probe:** stage 1 caught 0 of eight expected-refusal payment cases in
  `round5-payment-probe`; across all twelve probe cases it produced no indicator
  hit. Report the concrete missed conjunctions and anti-abuse cases, not a recall
  or precision estimate.

Round-six payment results should be presented the same way. The current 3/33 can
stand only if renamed as a descriptive challenge-set coverage count and stripped
of the claims “on unfamiliar language” and “not a meaningful detector on its
own.” Those are population-facing conclusions. There is no reason to accept that
weaker presentation when the cleaner 3/25 split is available and already points
in the same substantive direction.

**Confidence: high.** I would change my mind if the payment commission had not
shaped the positive cases, or if the documents explicitly defined 3/33 as an
inventory count over a deliberately mixed challenge set and drew no performance
conclusion from it. The provenance and current prose establish the opposite.

## 5. Whether all 26 round-six cases should have been spent

### Claim

`eval/README.md` says:

> `round6-codex` was the control ... configurations were rejected *because that
> number dropped*. That makes it a selection criterion, not a control, and
> selecting on a set contaminates it for reporting no matter which candidate
> wins.

It rejects a partial spend because:

> Working out which cases carried the signal requires exactly the per-case
> causal attribution this session concluded is unsupportable at n=16 with one
> sample.

It also says **“Both payment probes are now spent”**, while later noting that the
harness still reports ten qualifying `round5-payment-probe` cases.

### What I did

Read only. I checked the policy prose, the round-six decision account, and the
corpus flags. All 16 `round6-payment-probe` cases and all 10 `round6-codex` cases
are marked `spent: true`; only two of 12 round-five payment-probe cases are so
marked, leaving ten qualifying in the harness.

### Finding

**The all-26 outcome is sound; one supporting argument and the terminology are
not.** Merely reading a fixed system’s result does not spend a corpus. Using the
result to choose among configurations does. That boundary does not prove too
much: a baseline reading remains a valid historical claim about the system before
selection, while the set loses the ability to grade later candidates influenced
by it. This is the ordinary distinction between a test estimate and a validation
set, and it is consistent with the document’s forward-looking rule.

The 16 directed cases became development evidence when the decomposition was
designed and iterated against them. The ten undirected cases became validation
evidence when their aggregate score helped reject configurations. Reverting to
the baseline does not undo either use. On the facts recorded here, globally
marking both round-six files spent is the defensible conservative choice.

But **“we cannot identify which cases carried signal” does not imply “all cases
carried signal.”** That paragraph is an invalid inference. The stronger and
sufficient reason is set-level selection: the aggregate over the whole set was
used to choose a configuration, so the whole set is contaminated for a future
aggregate comparison. Post-hoc rescue of the apparently invariant cases would
itself be selection based on the observed outcomes, especially with one noisy
sample. The conclusion survives after the faulty premise is removed.

“Both payment probes are now spent” also overloads `spent`. The repository’s
machine-readable meaning is global and case-level, yet ten round-five probe cases
remain globally qualifying. What the prose means is that both probes are
contaminated **for the payment-conjunction claim**. It should say exactly that,
then preserve the separate fact that ten round-five cases remain usable for
unrelated claims. Otherwise the same word denotes incompatible states within
one paragraph.

There was a cheaper prospective option, but not an honest retrospective rescue.
After the round-six baseline showed that the prompt fix had not transferred, the
builder could have iterated only on already-spent regression cases (including the
two round-five drivers), or commissioned a separate development corpus, locked
one candidate, and then evaluated it once on a still-unread round-six probe while
leaving the undirected control untouched. A predeclared development/validation
split would also have preserved some capacity. The write-up records only why a
partial spend was rejected after the fact; it does not record why no capacity was
reserved before trying three configurations. That omission matters more than the
decision to spend the already-used cases.

**Confidence: high** that the two complete round-six sets are spent for future
comparisons influenced by this work; **high** that the partial-spend paragraph’s
logical implication is invalid; **medium** on the best prospective split because
the exact sequence of what was viewed when is not preserved. Evidence that the
undirected aggregate was not actually used in configuration selection would
change the first conclusion. A predeclared case-level holdout never inspected
during iteration would also have remained live.

## Stale-claim sweep

### A. The old two-route guardrail still appears in public and tool-facing prose

#### Claim

Early in `README.md`, `draft_response` is said to decide “two ways,
independently”: filed category or a content indicator, and the content scan is
called **“Layer 2.”** The `draft_response` tool description in
`msp_tools/server.py` repeats the same exhaustive two-item list and the same
“Layer 2” terminology.

#### What I did

Read only. I compared those passages with the later two-stage section, the
server’s `CLASSIFIER` construction, and the current guardrail description in
`.claude/CLAUDE.md`.

#### Finding

**Document claim wider than the truth, stale after stage 2 was added.** Category
and regex are two deterministic stage-1 routes. The configured model classifier
is the actual stage 2 and can independently add a refusal after both deterministic
routes clear. The stale public paragraph is confusing; the stale tool description
is more serious because it is the description presented to a calling model.
Both should describe stage 1’s two routes, then the additive, fail-closed stage 2
and regex-only disclosure.

**Confidence: high.** I would change my mind only if “decision” and “Layer 2”
were explicitly scoped to subparts of deterministic stage 1. They are currently
presented as exhaustive properties of the tool.

### B. Repeated sampling is simultaneously implemented and logged as unfixed

#### Claim

The public round-six section says:

> The real blocker is the harness. Every number in this README rests on one
> sample per case ... Repeated sampling comes before the next fix attempt.

The final defect table in `eval/README.md` still says:

> The harness cannot distinguish a real change from sampling noise.

and says it was named rather than fixed. Earlier in that same file, however,
`--samples` is documented as implemented: repeated calls, instability reporting,
majority scoring, and a within-corpus disagreement threshold.

#### What I did

Read only. I checked the public round-six conclusion, the `--samples` section,
and the final logged-defects table. No sampling run was needed to establish the
documentary contradiction.

#### Finding

**Stale document claim.** The historical round-six measurements still lack error
bars, and the old spent corpora cannot retroactively repair that. But repeated
sampling is no longer a missing harness capability, so it is not the current
blocker and should not remain logged as wholly unfixed. The live blockers are a
fresh corpus for the conjunction and a predeclared repeated-sampling comparison.
The defect can be narrowed if the author means that the new disagreement
heuristic is not a full statistical test; the current absolute wording is false
by the file’s own description.

**Confidence: high** that the capability claim is stale; **medium** on whether
the heuristic fully solves comparison. I would change the latter view if the
intended standard requires a formal between-configuration test that `--samples`
does not provide.

### C. The spending definition and round-five replacement entries predate round six

#### Claim

The ledger defines:

> A case is spent once the system changed in response to it.

The main README similarly glosses spent cases as ones “the system was changed in
response to.” Yet round six deliberately spends the undirected control even
though the code returned byte-identical to the baseline, because the set was a
selection criterion. In the same ledger, the replacement entries for
`linen_draft_edit` and `reno_branch_quickbooks` still say **“round 6, pending.”**

#### What I did

Read only. I compared the general definition and replacement column with “Two
consequences,” the forward-looking selection-criterion rule, and the round-six
corpus flags.

#### Finding

**Stale document claims.** The concise definition is now too narrow: a case is
spent when it becomes an optimization target or selection criterion, whether or
not a change ships. The two replacement entries were not updated after round six
returned. Their replacement status now needs to record that round six measured
the failed prompt transfer and was itself subsequently spent, not `pending`.

This is not just housekeeping. The narrow definition is the premise a future
reader is most likely to remember, and it contradicts the more careful rule that
does the work in item 5.

**Confidence: high.** A definition that explicitly used “changed” to include a
rejected selection decision could alter the wording issue, but the documents
elsewhere distinguish the code returning unchanged from the decision changing.

### Sweep result for the other requested surfaces

I found no additional later-change stale claim in `security.py`’s module
docstring. Its “no model in the loop” sentence is scoped to **“This scanner,”**
so it accurately describes deterministic stage 1 rather than the whole
guardrail. The other four tool descriptions in `server.py` were consistent with
the current public architecture and error contract. I did not report the three
stale README statements already listed in the handoff, or the separately queued
integration statement.

## Ranked findings

1. **Directed probe cases are pooled into the public 3/33 performance claim.**
   This directly violates the repo’s central measurement rule and is repeated as
   a headline conclusion.
2. **The decomposition is declared worse/failed after its comparison is declared
   unmeasurable.** That can incorrectly close an architectural option on noise;
   the structural monotonicity rejection should be kept separate.
3. **The live `draft_response` tool description still exposes the old two-route
   architecture.** This is stale prose on an operational interface, not merely
   historical narrative.
4. **Round-six spending is concluded correctly, but partial-spend reasoning is
   invalid and no prospective holdout strategy is recorded.** The lost payment
   measurement capacity was avoidable before iteration, not recoverable after it.
5. **Repeated sampling remains described as an unfixed harness blocker after
   `--samples` was implemented.** This obscures the actual blocker: fresh,
   predeclared measurement.
6. **The short spending definition and `round 6, pending` ledger entries are
   stale.** They contradict the later selection-criterion rule and completed
   round-six history.

If only one finding could be fixed, I would split and requalify **3/33** first.
The repo’s thesis depends on refusing attractive numbers that its sampling design
cannot support; leaving its headline floor estimate pooled with a deliberately
directed probe weakens that thesis more than any other claim reviewed here.

## What I could not evaluate

- I could not evaluate the behavioral performance of any decomposition. That
  requires a preserved candidate, fresh unspent corpora, repeated live model
  samples, and a comparison rule fixed before results are read. A paid live run
  was out of scope, and rerunning spent round-six cases would not answer it.
- I could not independently verify the exact control flow of the reverted
  authoritative implementation from the current tree. The write-up’s structural
  description is enough to assess the principle, but verifying the historical
  fact would require the preserved patch or commit.
- I could not determine which individual round-six outcomes were stable. That
  requires repeated live sampling. This does not prevent the set-level spending
  conclusion because the recorded aggregate was used for selection.
- No corpus here can estimate population recall for payment-change incidents.
  The payment corpora are directed probes, and the documents correctly identify
  the need for a new commission before the conjunction defect is measured.
