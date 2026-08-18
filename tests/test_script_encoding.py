"""Encoding rules for anything that reaches a Windows console or PowerShell.

Two bug classes, both of which have already cost real time on this project, and
neither of which any other test would catch. Both are enforced here as
properties of every file rather than as repairs to the files that broke, because
this repo's ledger is largely a record of instance fixes that left the class
open.

WHY GREP DID NOT WORK
---------------------
The first attempt at rule 1 searched lines containing `print`. That found four
strings and missed two, because the two it missed were `CorpusError` messages -
raised in `load_corpus`, printed by `main()` several hundred lines away. The
claim "console output is ASCII now" was made and was false. Walking the AST for
string constants finds them regardless of how far the raise sits from the print,
which is the difference between a check and a coincidence.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PY_DIRS = ("scripts",)

# Vendored and generated trees. The first version of this file used a bare
# rglob and tested `.venv/Scripts/activate.ps1` - a third-party file this repo
# does not control and would not fix, which would have turned a real invariant
# into a failure nobody could act on. It also made collection walk the whole
# virtualenv, taking eleven seconds for a check that should be instant.
EXCLUDED_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache"}


def _owned_files(suffix: str) -> list[Path]:
    """Every file with `suffix` that this repo owns, pruning as it walks.

    `os.walk` with in-place pruning rather than `rglob` plus a filter: rglob
    descends into `.venv` before anything can exclude it, which took the whole
    suite from 0.65s to 10.5s for a check that reads four small files.
    """
    found: list[Path] = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        found += [Path(root) / f for f in files if f.endswith(suffix)]
    return sorted(found)


def _non_ascii(text: str) -> list[str]:
    return sorted({c for c in text if ord(c) > 127})


def _docstring_ids(tree: ast.Module) -> set[int]:
    """id() of every string constant that is a docstring.

    Docstrings are exempt: they are read in an editor, which renders them fine.
    A module, class, or function docstring is its first statement.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                out.add(id(first.value))
    return out


def _script_paths() -> list[Path]:
    return sorted(p for d in PY_DIRS for p in (REPO / d).glob("*.py"))


@pytest.mark.parametrize("path", _script_paths(), ids=lambda p: p.name)
def test_script_strings_are_ascii(path: Path) -> None:
    """No non-docstring string literal in scripts/ may contain non-ASCII.

    These strings reach a console. On a Windows console using a non-UTF-8 code
    page an em-dash arrives as `?`, which is worst in exactly the place it is
    most likely to appear: the long explanatory error messages this project
    favours. The reader of a `CorpusError` has just done something wrong and is
    being handed a paragraph; mojibake in it is a poor start.

    Comments are not checked. They are not string literals and never print.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exempt = _docstring_ids(tree)
    lines = source.splitlines()

    offenders = [
        f"{path.name}:{node.lineno} {_non_ascii(node.value)} "
        f"-> {lines[node.lineno - 1].strip()[:70]}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in exempt
        and _non_ascii(node.value)
    ]

    assert not offenders, (
        "non-ASCII in a string that can reach a console - use plain ASCII "
        "punctuation:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "path",
    _owned_files(".ps1"),
    ids=lambda p: p.name,
)
def test_powershell_files_are_ascii(path: Path) -> None:
    """A `.ps1` must be ASCII throughout, comments included.

    Windows PowerShell 5.1 reads a `.ps1` with no byte-order mark as
    ANSI/Windows-1252. File tools write UTF-8 without a BOM, so an em-dash
    arrives as two bytes, the second of which the parser sees as a stray quote.
    The result is errors like "Unexpected token" pointing at a line whose real
    problem is a dash in a comment several lines earlier - and it reads as the
    user's mistake rather than an encoding fault.

    This bit once, on `eval/handoff/make-handoff.ps1`. Comments are checked here
    and exempt in Python because the failure is different in kind: in Python a
    stray byte in a comment is ignored, in PowerShell 5.1 it stops the parse.
    """
    data = path.read_bytes()
    assert data[:3] != b"\xef\xbb\xbf", (
        f"{path.name} has a UTF-8 BOM. Write it without one; the encoding rule "
        "is ASCII-only rather than BOM-tagged UTF-8."
    )

    text = data.decode("utf-8", errors="replace")
    offenders = [
        f"{path.name}:{i} {_non_ascii(line)} -> {line.strip()[:70]}"
        for i, line in enumerate(text.splitlines(), 1)
        if _non_ascii(line)
    ]
    assert not offenders, (
        "non-ASCII in a PowerShell file - PS 5.1 parses these as ANSI and the "
        "error it reports will point somewhere else:\n  " + "\n  ".join(offenders)
    )


def test_the_two_corpus_states_are_exclusive() -> None:
    """`SEALED` and `RETIRED` must not share a corpus.

    The harness raises at import if they do, so this test would fail at
    collection rather than here - which is the intent. It exists to say the
    invariant out loud where someone reading the suite will find it, and to fail
    with an explanation rather than an ImportError if the guard is ever removed.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_eval_harness", REPO / "scripts" / "eval_classifier.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    overlap = sorted(set(module.SEALED) & set(module.RETIRED))
    assert not overlap, (
        f"{overlap} is both sealed and retired. Sealed means unread; retired "
        "means read at a disqualifying moment. Decide which."
    )
