"""Knowledge-base loading and retrieval over the Summit Managed IT corpus.

Project 1 had no retrieval layer to reuse — it concatenated all nine articles
into the system prompt behind a cache_control breakpoint, which is a reasonable
strategy at nine documents but is not something an MCP tool can do. `search_kb`
needs to return a bounded, ranked, citable excerpt, so retrieval is built here.

Scoring is deterministic keyword overlap, not embeddings. Three reasons:
nine articles do not justify a vector index; an API call inside retrieval would
make the test suite non-deterministic, breaking the same discipline Project 1's
grader holds to; and a reviewer can read this function and verify what it does,
which is not true of a similarity score.

Articles are split into blocks on blank lines. The corpus is written as
`**Bold label:** prose` paragraphs and bullet groups, so a block is the natural
citable unit — big enough to carry a complete procedure, small enough not to
flood the caller's context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Words too common in this corpus to carry signal.
STOPWORDS = frozenset(
    """a an and are as at be but by for from has have how i if in into is it its
    my of on or our that the their them then there these they this to us was we
    were what when where which who will with you your can do does not no""".split()
)

# A block must clear this to be returned at all; below it, the match is noise.
MIN_SCORE = 1.0

# Blocks that instruct the support agent rather than inform the customer.
# These are real KB content and search_kb returns them — a technician asking
# "what are the rules on temporary passwords" wants exactly this. But they must
# never be pasted into a customer-facing draft: "NEVER issue a temporary
# password" is a rule for staff, and a reply that opens with it is nonsense at
# best and leaks internal escalation policy at worst.
#
# Deliberately narrow, and matched against the block text rather than guessed
# from the label. Over-filtering silently strips facts a draft needs — the
# lockout block says "direct them to self-service" but also carries the
# 15-minute timeout and the reset URL, so phrasing aimed at staff is not by
# itself enough to exclude a block.
_INTERNAL_PATTERNS = (
    r"rules for support",
    r"never (?:issue|advise|include|read out|promise)",
    r"escalate (?:per|to|immediately)",
    r"\bper kb-\d",
    r"do not (?:troubleshoot|attempt)",
)

# Whole articles that are staff documents end to end. Block-level matching is
# not enough for these: KB-006's indicator list contains the words "account
# lockout" and "password", so it out-ranks the actual lockout runbook on a
# lockout ticket and lands the incident-response checklist in a reply to a
# customer asking why their account is locked. KB-000 is the triage priority
# matrix — internal by nature, and never something a requester should read.
_INTERNAL_ARTICLES = frozenset({"KB-000", "KB-006"})


def _is_internal(article_id: str, label: str | None, text: str) -> bool:
    if article_id in _INTERNAL_ARTICLES:
        return True
    hay = f"{label or ''} {text}".lower()
    return any(re.search(p, hay) for p in _INTERNAL_PATTERNS)


@dataclass(frozen=True)
class Block:
    """One citable chunk of a KB article."""

    article_id: str
    article_title: str
    label: str | None
    text: str
    internal: bool = False
    """True when the block instructs support staff. Safe to retrieve, unsafe to
    paste into a reply to a customer."""


@dataclass(frozen=True)
class Excerpt:
    """A scored retrieval result."""

    article_id: str
    article_title: str
    label: str | None
    text: str
    score: float
    matched_terms: tuple[str, ...]
    internal: bool = False


def _tokenize(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in STOPWORDS and len(w) > 2
    ]


def _split_blocks(article_id: str, title: str, body: str) -> list[Block]:
    blocks: list[Block] = []
    for raw in re.split(r"\n\s*\n", body):
        chunk = raw.strip()
        if not chunk:
            continue
        label_match = re.match(r"\*\*(.+?)\*\*", chunk)
        label = label_match.group(1).rstrip(":") if label_match else None
        blocks.append(
            Block(
                article_id=article_id,
                article_title=title,
                label=label,
                text=chunk,
                internal=_is_internal(article_id, label, chunk),
            )
        )
    return blocks


@lru_cache(maxsize=8)
def load_blocks(kb_dir: str) -> tuple[Block, ...]:
    """Load and chunk every article in kb_dir. Cached — the corpus is static."""
    path = Path(kb_dir)
    articles = sorted(path.glob("*.md"))
    if not articles:
        raise FileNotFoundError(f"no KB articles found in {path}")

    blocks: list[Block] = []
    for f in articles:
        text = f.read_text(encoding="utf-8")
        first = text.lstrip().splitlines()[0] if text.strip() else ""
        title = first.lstrip("# ").strip()
        article_id = f.name.split("-")[0] + "-" + f.name.split("-")[1]  # "KB-006"
        body = text.split("\n", 1)[1] if "\n" in text else ""
        blocks.extend(_split_blocks(article_id, title, body))
    return tuple(blocks)


def search(
    query: str,
    kb_dir: str,
    limit: int = 3,
    topic_hint: str | None = None,
    include_internal: bool = True,
) -> list[Excerpt]:
    """Rank KB blocks against a free-text query.

    A term matching the article title or a block's bold label counts for more
    than one buried mid-paragraph — in this corpus the label is the procedure
    name, so a hit there is usually the article the caller wanted.

    `topic_hint` was called `category`, which was a lie about what it does. It
    does not filter: the KB corpus carries no category metadata to filter on.
    Its tokens are folded into the query, so it can only ever promote blocks
    that already match something — it widens the query, it never narrows the
    corpus. A block matching only the hint and nothing in `query` still scores,
    which is why the name mattered: a caller reading "category" would reasonably
    expect results confined to it, and would misread a hint-only hit as a
    category match.

    Filtering was considered and rejected. It would mean labelling all nine
    articles and trusting those labels — the same trust-the-label failure the
    security scan exists to avoid, in a place where being wrong means a
    technician cannot find a procedure that is sitting right there.

    `include_internal=False` drops staff-facing blocks. draft_response uses it
    so internal escalation rules cannot end up in a customer reply; search_kb
    leaves it on, because a technician looking up policy should see policy.
    """
    # Load before inspecting the query. Otherwise a query with no usable terms
    # returns [] against a missing corpus, which the caller reads as "no match"
    # — reintroducing, in a corner, exactly the conflation KB_UNAVAILABLE exists
    # to remove. A missing corpus should be reported as missing regardless of
    # what was asked of it.
    blocks = load_blocks(kb_dir)

    terms = set(_tokenize(query))
    if not terms:
        return []

    if not include_internal:
        blocks = tuple(b for b in blocks if not b.internal)
    if topic_hint:
        terms |= set(_tokenize(topic_hint.replace("_", " ")))

    scored: list[Excerpt] = []
    for block in blocks:
        body_tokens = _tokenize(block.text)
        if not body_tokens:
            continue
        title_tokens = set(_tokenize(block.article_title))
        label_tokens = set(_tokenize(block.label or ""))
        body_set = set(body_tokens)

        matched = terms & (body_set | title_tokens | label_tokens)
        if not matched:
            continue

        score = 0.0
        for term in matched:
            if term in title_tokens:
                score += 2.0
            if term in label_tokens:
                score += 1.5
            if term in body_set:
                # Diminishing returns on repetition: a term repeated five times
                # does not make the block five times more relevant.
                score += min(body_tokens.count(term), 3) * 0.5

        # Prefer blocks that cover more of the query rather than one term hard.
        score *= 1.0 + 0.3 * (len(matched) - 1)

        if score >= MIN_SCORE:
            scored.append(
                Excerpt(
                    article_id=block.article_id,
                    article_title=block.article_title,
                    label=block.label,
                    text=block.text,
                    score=round(score, 2),
                    matched_terms=tuple(sorted(matched)),
                    internal=block.internal,
                )
            )

    # Stable ordering: score desc, then article id, so results never churn.
    scored.sort(key=lambda e: (-e.score, e.article_id))
    return scored[:limit]
