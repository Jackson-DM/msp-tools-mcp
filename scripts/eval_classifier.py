"""Held-out evaluation of the two-stage guardrail.

WHY THIS FILE EXISTS
--------------------
Three times now, a guardrail score has been produced by measuring against the
cases that produced it. Every time the number looked good and meant nothing:

  round 1  indicators written against data/tickets.json, scored on the same
           tickets: "6/6, no false positives". An independent review then found
           7 bypasses and 7 false positives.
  round 2  patterns rewritten to fix all 14 of those, scored on those 14:
           "14/14". Six newly written incidents were then missed 6/6.
  round 3  cases held out from the regex patterns, but written by the same
           author as the stage-2 system prompt — whose supplementary list names
           5 of the 8 incidents outright. "100% recall" was the prompt scoring
           its own reflection.

The fix for round 3 is structural and is why this file no longer contains any
cases. **The harness must not be the corpus.** A corpus lives in
eval/corpora/*.json, carries a `provenance` block naming what its author was
given and denied, and is written by a party who cannot see what it measures.
A corpus whose provenance says otherwise is a regression suite, not a
measurement.

The held-out property also decays. Every time a case here drives a code change
it stops being held out and belongs in tests/test_adversarial_corpus.py, with a
fresh case written to replace it.

Reports stage 1 alone and both stages together, because the interesting question
is not "is the guardrail good" but "what does stage 2 add".

Usage:
    uv sync --extra classifier
    $env:MSP_TOOLS_CLASSIFIER = "on"
    $env:ANTHROPIC_API_KEY = (Get-Content "$env:USERPROFILE\\.anthropic-key" -Raw).Trim()
    uv run python scripts/eval_classifier.py eval/corpora/round4-codex.json

    uv run python scripts/eval_classifier.py --list
    uv run python scripts/eval_classifier.py <corpus> --dry-run   # stage 1 only, no API calls
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from msp_tools import guardrail, security  # noqa: E402
from msp_tools.classifier import NullClassifier, build_default  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = str(ROOT / "kb")
CORPORA_DIR = ROOT / "eval" / "corpora"

DEFAULT_FILED_CATEGORY = "hardware"
CASE_TYPES = {"incident", "injection", "routine", "hard_negative"}


class CorpusError(ValueError):
    """The corpus is malformed in a way that would make its score meaningless."""


def load_corpus(path: Path) -> dict:
    """Load and validate a corpus.

    Validation is strict and fails loudly, because every check here guards a way
    a corpus can produce a number that looks fine and measures nothing.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CorpusError(f"no corpus at {path}") from None
    except json.JSONDecodeError as e:
        raise CorpusError(f"{path.name} is not valid JSON: {e}") from None

    for key in ("corpus_id", "provenance", "cases"):
        if key not in data:
            raise CorpusError(f"{path.name} is missing required key '{key}'")

    prov = data["provenance"]
    for key in ("author", "authored_on", "materials_provided", "materials_withheld"):
        if key not in prov:
            raise CorpusError(
                f"{path.name}: provenance is missing '{key}'. A corpus without a "
                "provenance trail cannot support a held-out claim — that is the "
                "only thing that makes its score worth quoting."
            )

    cases = data["cases"]
    if not cases:
        raise CorpusError(f"{path.name} contains no cases")

    seen: set[str] = set()
    for i, c in enumerate(cases):
        where = f"{path.name} case {i}"
        for key in ("id", "expect_refuse", "case_type", "subject", "body"):
            if key not in c:
                raise CorpusError(f"{where} is missing '{key}'")
        if c["id"] in seen:
            raise CorpusError(f"{where}: duplicate id '{c['id']}'")
        seen.add(c["id"])
        if c["case_type"] not in CASE_TYPES:
            raise CorpusError(
                f"{where} ({c['id']}): unknown case_type {c['case_type']!r}; "
                f"expected one of {sorted(CASE_TYPES)}"
            )
        filed = (c.get("filed_category") or DEFAULT_FILED_CATEGORY).lower()
        if filed == "security":
            raise CorpusError(
                f"{where} ({c['id']}): filed_category is 'security'. Stage 1's "
                "label check refuses that before reading a word of the body, so "
                "the case would measure nothing. File it as a plausible wrong "
                "label instead — that is the realistic failure mode."
            )
        if c["case_type"] == "injection" and not c["expect_refuse"]:
            raise CorpusError(
                f"{where} ({c['id']}): an injection case that expects a draft is "
                "not a test of injection resistance."
            )
    return data


# Corpora written toward a target the COMMISSIONER named. These report counts
# and never recall or precision — see `_line`.
#
# This list lives here, on the commissioner's side, rather than as a field in
# the corpus files, and that placement is the point. `provenance` is the
# AUTHOR's statement of what they were given and denied; whether the resulting
# sample can estimate performance is a judgement the commissioner makes, and
# writing it into the author's block would blur two different claims into one.
#
# `known_leakage` is not a usable proxy for this. `round4-codex` declares
# leakage — its `hard_negative` cases were written to seams named in the brief —
# and that qualifies its PRECISION while leaving recall untouched, which is why
# the undirected floor is quotable from it at all. Suppressing rates on every
# corpus with a non-null disclosure would delete the honest headline along with
# the dishonest one. Direction and leakage are different properties.
DIRECTED = frozenset({
    "round5-payment-probe",
    "round6-payment-probe",
    "round7-payment-alpha",
    "round7-payment-beta",
})


# Corpora that may not be run without an explicit, recorded reason.
#
# A sealed corpus is a holdout: it may be opened ONCE, after a candidate fix is
# committed and its diff is final, and reading it earlier destroys the only
# thing it was commissioned to provide. That rule lived in `eval/README.md` as a
# paragraph, and on 2026-08-10 it was broken twice within an hour — once by an
# instruction I wrote myself naming a sealed file, once by an assistant checking
# the corpora that instruction had not named, which is ordinary diligence.
# Neither reader had seen the paragraph.
#
# This repo's whole argument is that a rule in prose is a request and a rule in
# code is a wall, and the eval harness was the one place that argument had not
# been applied. `--unseal` is the wall. It cannot stop a determined person —
# nothing here can — but it makes opening a holdout a deliberate act that leaves
# a record, instead of a side effect of being thorough.
# SCOPE, learned the hard way on 2026-08-18: this gates THIS SCRIPT. A throwaway
# that json.loads eval/corpora/*.json and calls security.scan never reaches it,
# and that is precisely how `round8-codex` was opened - by a reviewer verifying
# that a headline figure derived correctly, which required walking every corpus.
# The wall stops a holdout being opened by a command someone types. It does not
# stop one being opened by a file someone reads. See eval/README.md.
SEALED: dict[str, str] = {
    "round8-payment": (
        "round 7 holdout; opens once, after a candidate fix is committed "
        "and its diff is final"
    ),
}


def score(results: list[tuple[bool, bool]]) -> dict[str, float | int]:
    """results: list of (expected_refuse, actual_refuse)."""
    tp = sum(1 for e, a in results if e and a)
    fn = sum(1 for e, a in results if e and not a)
    fp = sum(1 for e, a in results if not e and a)
    tn = sum(1 for e, a in results if not e and not a)
    recall = tp / (tp + fn) if tp + fn else float("nan")
    precision = tp / (tp + fp) if tp + fp else float("nan")
    return {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "recall": recall, "precision": precision,
        "accuracy": (tp + tn) / len(results) if results else float("nan"),
    }


def _pct(x: float) -> str:
    return " n/a" if x != x else f"{x:.0%}"


def _line(label: str, results: list[tuple[bool, bool]], *, estimator: bool = True) -> str:
    """One results row.

    `estimator=False` prints counts and never the words "recall" or
    "precision". Callers pass it for the corpora in `DIRECTED` — those written
    toward a target the commissioner named — because `eval/README.md` says
    outright that such a file finds defects and cannot estimate performance.
    Note that this is direction, not `known_leakage`; see `DIRECTED` for why
    the two are not interchangeable.

    Printing `recall 0%` for it and relying on a paragraph elsewhere to explain
    that the row is not quotable is asking a caption to undo what a table says.
    It does not work: `3 of 33` reached the public README twice that way, and
    the round-6 review called it the sharpest violation of this project's own
    rule. A percentage under a `recall` heading IS a performance estimate, so
    the fix is to stop printing one where none is licensed.
    """
    m = score(results)
    counts = f"(tp{m['tp']} fn{m['fn']} fp{m['fp']} tn{m['tn']})"
    if estimator:
        return (
            f"{label:26}  recall {_pct(m['recall']):>4}  precision {_pct(m['precision']):>4}  "
            f"accuracy {_pct(m['accuracy']):>4}   {counts}"
        )
    caught = f"{m['tp']} of {m['tp'] + m['fn']}"
    refused = f"{m['fp']} of {m['fp'] + m['tn']}"
    return (
        f"{label:26}  caught {caught:>8}   wrongly refused {refused:>8}   {counts}"
    )


def print_provenance(data: dict) -> None:
    prov = data["provenance"]
    print(f"corpus:   {data['corpus_id']}  ({len(data['cases'])} cases)")
    print(f"author:   {prov['author']}")
    print(f"given:    {', '.join(prov['materials_provided']) or 'nothing recorded'}")
    print(f"withheld: {', '.join(prov['materials_withheld']) or 'NOTHING — not a held-out corpus'}")
    if prov.get("isolation"):
        print(f"isolation: {prov['isolation']}")
    leak = prov.get("known_leakage")
    if leak:
        print()
        print("KNOWN LEAKAGE — do not quote the headline number without this:")
        for line in _wrap(leak, 92):
            print(f"  {line}")
    print()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("corpus", nargs="?", help="path to a corpus JSON, or a corpus_id in eval/corpora/")
    ap.add_argument("--list", action="store_true", help="list available corpora and exit")
    ap.add_argument("--dry-run", action="store_true", help="stage 1 only; makes no API calls")
    ap.add_argument(
        "--samples",
        type=int,
        default=1,
        metavar="N",
        help=(
            "run stage 2 N times per case and report how often it disagrees with "
            "itself. Costs N times as much. Stage 1 is deterministic and is run once."
        ),
    )
    ap.add_argument(
        "--unseal",
        metavar="REASON",
        help=(
            "open a sealed holdout corpus. Requires a reason, which is printed "
            "with the results. A holdout may be opened once, after a candidate "
            "is committed and its diff is final."
        ),
    )
    args = ap.parse_args()

    # Odd samples only. Ties break toward refusal, which is correct for the
    # guardrail and wrong for a thing measuring it: at N=4 a coin-flip case
    # scores refused 68.75% of the time against 50% at N=5, an 18.75-point bias
    # landing entirely on unstable cases — the ones this flag exists to surface.
    # Odd N is exactly unbiased. Rejected rather than documented because
    # "compare at matching parity" is an unenforced invariant, and this repo's
    # record with those is poor enough to have its own ledger.
    if args.samples < 1 or args.samples % 2 == 0:
        print(
            f"error: --samples must be odd and at least 1 (got {args.samples}).\n"
            "  Ties break toward refusal, so an even N reports more refusals than\n"
            "  the system produces: +18.75 points at N=4 on a coin-flip case, and\n"
            "  still +13.7 at N=8. Odd N is unbiased. Use 3, 5, 7 or 9.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.list or not args.corpus:
        # Print the qualifying count, not just a LEAKED marker. Two different
        # things were both being called leakage: per-case `leaked`, which
        # excludes a case from the quotable row, and corpus-level
        # `known_leakage`, which is a prose disclosure and feeds no computation
        # at all. Every corpus here carries a disclosure, so the old marker lit
        # up all six while four of them still had qualifying cases — and a
        # reader (this project's own README, as it turned out) concluded there
        # were none left anywhere. A number the reader can check beats a label
        # they have to interpret.
        print("corpora in eval/corpora/:")
        for p in sorted(CORPORA_DIR.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                cases = d.get("cases", [])
                qualifying = sum(
                    1 for c in cases if not (c.get("leaked") or c.get("spent"))
                )
                note = " <-- discloses leakage, read it" if d.get("provenance", {}).get(
                    "known_leakage"
                ) else ""
                if p.stem in SEALED:
                    state = "SEALED"
                    note = f" <-- HOLDOUT: {SEALED[p.stem]}"
                elif qualifying == 0:
                    state = "REGRESSION SUITE"
                else:
                    state = f"{qualifying:>3} qualifying"
                print(
                    f"  {p.stem:22} {len(cases):>3} cases  {state:>16}   "
                    f"{d.get('provenance', {}).get('author', '?')}{note}"
                )
            except Exception as e:  # pragma: no cover - listing is best effort
                print(f"  {p.stem:22} unreadable: {e}")
        print(
            "\n'qualifying' excludes per-case leaked and spent. The disclosure note is\n"
            "separate: it means the provenance block qualifies the headline number in\n"
            "prose, and it feeds no computation. Read both; they are not the same thing."
        )
        if not args.corpus:
            print("\npass one:  uv run python scripts/eval_classifier.py eval/corpora/<id>.json")
        return

    path = Path(args.corpus)
    if not path.exists():
        path = CORPORA_DIR / f"{args.corpus}.json"

    # The seal is checked BEFORE the corpus is loaded and before anything is
    # printed, so a refused run reveals nothing about the file — not a case
    # count, not an author, not a provenance block. A gate that leaks while
    # refusing is a gate in name only.
    if path.stem in SEALED and not args.unseal:
        print(
            f"error: {path.stem} is a SEALED holdout.\n"
            f"  {SEALED[path.stem]}\n"
            "\n"
            "  A holdout may be opened ONCE, after a candidate fix is committed\n"
            "  and its diff is final. Reading it earlier destroys the only thing\n"
            "  it was commissioned to provide, and --dry-run is not exempt: it is\n"
            "  free, which is what makes it the tempting way to break this.\n"
            "\n"
            "  If you are genuinely at that point:\n"
            '    --unseal "candidate <sha> locked, opening holdout as planned"\n'
            "\n"
            "  Then record the reading in eval/README.md and remove it from\n"
            "  SEALED. A holdout is opened once; the entry should not survive it.",
            file=sys.stderr,
        )
        raise SystemExit(3)

    try:
        data = load_corpus(path)
    except CorpusError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2) from None

    if args.unseal:
        print("=" * 78)
        print(f"UNSEALING {path.stem} — this is a one-time reading.")
        print(f"  reason given: {args.unseal}")
        if path.stem not in SEALED:
            print("  NOTE: this corpus was not sealed. --unseal did nothing.")
        print("=" * 78)
        print()

    classifier = NullClassifier() if args.dry_run else build_default(KB_DIR)
    live = not isinstance(classifier, NullClassifier)

    print_provenance(data)
    print(f"stage 2: {type(classifier).__name__}" + ("" if live else "  <-- NOT LIVE, regex-only"))
    if not live and not args.dry_run:
        print("  set MSP_TOOLS_CLASSIFIER=on and ANTHROPIC_API_KEY, and")
        print("  install the extra:  uv sync --extra classifier")
    print()
    print(f"{'case':24} {'type':14} {'want':6} {'stage1':7} {'both':6} note")
    print("-" * 100)

    s1: list[tuple[bool, bool]] = []
    both: list[tuple[bool, bool]] = []
    unstable_ids: list[tuple[str, int, int]] = []

    for c in data["cases"]:
        want = bool(c["expect_refuse"])
        ticket = {
            "ticket_id": c["id"],
            "category": c.get("filed_category") or DEFAULT_FILED_CATEGORY,
            "subject": c["subject"],
            "body": c["body"],
        }

        stage1 = bool(security.scan(c["subject"], c["body"]))
        s1.append((want, stage1))

        # Sample the whole assessment, not just stage 2, so the reported verdict
        # is the one the tool would actually return. Stage 1 is deterministic,
        # so any variation you see came from the model.
        runs = [guardrail.assess(ticket, classifier) for _ in range(max(1, args.samples))]
        refusals = sum(1 for r in runs if r.is_security)

        # Majority, not "refuse if any run refused". The question here is what a
        # single production call typically does, and a max-over-samples rule
        # would report a system nobody is running. Ties break toward refusal,
        # which is the direction everything else in this repo breaks toward.
        verdict = refusals * 2 >= len(runs)
        a = next((r for r in runs if r.is_security == verdict), runs[0])
        both.append((want, verdict))

        unstable = 0 < refusals < len(runs)
        if unstable:
            unstable_ids.append((c["id"], refusals, len(runs)))

        flag = "" if verdict == want else "   <-- WRONG"
        spread = f" [{refusals}/{len(runs)}]" if len(runs) > 1 else ""
        if unstable:
            spread += " UNSTABLE"
        note = (a.stage if verdict else "cleared") + spread + flag
        print(
            f"{c['id']:24} {c['case_type']:14} {str(want):6} {str(stage1):7} "
            f"{str(verdict):6} {note}"
        )

    print()
    # A directed corpus gets counts, never recall/precision. See _line and DIRECTED.
    estimator = data["corpus_id"] not in DIRECTED
    print(_line("stage 1 only (regex)", s1, estimator=estimator))
    print(_line("both stages", both, estimator=estimator))
    if not estimator:
        print(
            "  Counts, not rates: this corpus was written toward a target the\n"
            "  commissioner chose, so it finds defects and cannot estimate\n"
            "  performance. Read it case by case."
        )

    # --- how much of this is noise ---------------------------------------
    # Round 6 was evaluated at one sample per case. Single cases moved in both
    # directions between configurations, each movement got a causal explanation,
    # and at least two of those explanations were wrong. A number with no error
    # bar cannot support a comparison, and comparisons are what fixes are judged
    # on. See eval/README.md.
    n = max(1, args.samples)
    if n == 1:
        print()
        print(
            "  1 sample per case. This number has no error bar, so it cannot support\n"
            "  a comparison between configurations. Re-run with --samples 5 before\n"
            "  concluding that a change helped."
        )
    else:
        pct = 100.0 * len(unstable_ids) / max(1, len(data["cases"]))
        print()
        print(f"  {n} samples per case.  unstable: {len(unstable_ids)}/{len(data['cases'])} ({pct:.0f}%)")
        for cid, r, tot in unstable_ids:
            print(f"    {cid:38} refused {r}/{tot}")
        if unstable_ids:
            print(
                f"  A difference of fewer than {len(unstable_ids)} cases between two\n"
                "  configurations is inside this corpus's own disagreement with itself.\n"
                "  Do not attribute a mechanism to it."
            )
        else:
            print("  Every case was unanimous. Differences of one case are still n=1.")

    # --- breakdowns ------------------------------------------------------
    # Reported separately because they answer different questions, and because
    # a single blended number is exactly how the previous three rounds hid what
    # they were actually measuring.
    types = [c["case_type"] for c in data["cases"]]
    leaked = [bool(c.get("leaked")) for c in data["cases"]]
    spent = [bool(c.get("spent")) for c in data["cases"]]

    print()
    for t in ("incident", "injection", "routine", "hard_negative"):
        subset = [r for r, ct in zip(both, types) if ct == t]
        if subset:
            correct = sum(1 for e, a in subset if e == a)
            print(f"  {t:14} {correct}/{len(subset)} correct")

    # A case can stop being a measurement in two ways, and both have to be
    # visible or a corpus decays into a test suite without anyone noticing:
    # LEAKED, the author saw the situation described in the thing being scored;
    # and SPENT, the thing being scored was changed in response to this case.
    # The second is the one that creeps in, because it happens later and to a
    # file nobody re-reads. Both are excluded from the quotable row.
    if any(leaked) or any(spent):
        qualifying = [
            r for r, lk, sp in zip(both, leaked, spent) if not (lk or sp)
        ]
        print()
        if any(leaked):
            print(
                f"  {sum(leaked)} case(s) LEAKED - situation named in the "
                "classifier's own prompt."
            )
        if any(spent):
            # Not "the system was changed": round 6 spent 26 cases and shipped
            # nothing. What spends a case is being used as the target a change
            # is evaluated against, whether or not the change survived.
            print(
                f"  {sum(spent)} case(s) SPENT - used as the target of a change, "
                "shipped or not. See eval/README.md."
            )
            print(
                "    "
                + ", ".join(c["id"] for c, sp in zip(data["cases"], spent) if sp)
            )
        if qualifying:
            print("  " + _line("qualifying subset only", qualifying, estimator=estimator).strip())
            print(
                "  Quote the qualifying row. The full-corpus row includes cases "
                "that can no longer measure anything."
            )
        else:
            print(
                "  No qualifying cases remain. This corpus is a regression "
                "suite now; it cannot produce a measurement."
            )

    missed = [c["id"] for c, (_, a) in zip(data["cases"], both) if c["expect_refuse"] and not a]
    over = [c["id"] for c, (_, a) in zip(data["cases"], both) if not c["expect_refuse"] and a]
    print()
    print("MISSED INCIDENTS (false negatives - the dangerous direction):", missed or "none")
    print("WRONGLY REFUSED (false positives - the survivable direction):", over or "none")

    if missed:
        print()
        print("A case you act on is spent: fixing it makes it training data. Copy it into")
        print("tests/test_adversarial_corpus.py, set \"spent\": true on it here, log it in")
        print("eval/README.md, and commission fresh cases. Cases you do NOT act on stay")
        print("live and keep measuring.")


if __name__ == "__main__":
    main()
