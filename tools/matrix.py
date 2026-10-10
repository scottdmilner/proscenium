"""Check the requirement-to-test matrix and render its Markdown view.

    uv run python tools/matrix.py check    # validate; fail if requirements-matrix.md is stale
    uv run python tools/matrix.py render   # rewrite requirements-matrix.md

The matrix (docs/testing/requirements.yaml) has one row per requirement in
PROJECT.md, spec/, and testing/. Each row quotes the text it traces, so the
checks below catch drift in either direction:
- Every row's quote appears, exactly once, in the section its `section` field names.
- Every bullet, paragraph, table row, and code block in those docs is quoted by a
  row or excluded with a reason.
- Every invariant bullet in spec/invariants.md ends with the IDs of the rows it
  summarizes, and those rows belong to sections the bullet links to.
- Fields, milestones, and fixtures (tests/fixtures/registry.py) are consistent.
- Rows of milestones listed in `started` have an oracle, and their behavior rows a fixture.
  Rows of later milestones may leave both for their milestone to fill in.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MATRIX = DOCS / "testing" / "requirements.yaml"
VIEW = DOCS / "testing" / "requirements-matrix.md"
INVARIANTS = "spec/invariants.md"
# Requirement docs, relative to docs/. Generated files and invariants (checked separately) are not scanned,
# and neither are docs outside these patterns (milestones, plans, testing/alab/).
SOURCES = ["PROJECT.md", "spec/*.md", "spec/support/*.md", "testing/*.md"]
NOT_SCANNED = {INVARIANTS, "testing/requirements-matrix.md"}

KINDS = {"behavior", "contract", "process"}
QUALIFIER = {1: "M12", 2: "M14"}  # behavior rows qualify in their phase's qualification milestone
ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{2}$")  # AREA-NN, e.g. FILE-03 or PH1-01
# Fields a row may set, and fields a section group may set as defaults for its rows.
ROW_FIELDS = {"id", "quote", "kind", "delivery", "phase", "fixtures", "oracle", "qualified_by", "note"}
SECTION_FIELDS = {"section", "kind", "delivery", "phase", "fixtures", "qualified_by", "note", "rows"}


# --- Markdown -----------------------------------------------------------------------------------


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


class _Slugger:
    """Heading anchors for one doc; a repeated heading gets GitHub's -1, -2 suffixes."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def __call__(self, heading: str) -> str:
        base = slug(heading)
        n = self.seen.get(base, 0)
        self.seen[base] = n + 1
        return base if n == 0 else f"{base}-{n}"


def plain(text: str) -> str:
    """Markdown reduced to comparable text: link targets, emphasis, and code marks dropped."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*`]", "", text)
    return " ".join(text.split())


@dataclass
class Block:
    """One bullet, paragraph, table row, or code block: the unit a row or exclusion must trace."""

    doc: str  # path relative to docs/
    sections: list[str]  # anchors of the enclosing headings, outermost first
    text: str  # plain text
    line: int  # 1-based line where the block starts; with doc, its identity


def blocks(doc: str) -> list[Block]:
    """The requirement-bearing blocks of one doc, in order.

    A small line-based parser for the Markdown these docs use; headings are not
    blocks, only context. Each list item is its own block (its nested items too),
    and an indented line right after one continues it. Consecutive plain lines
    form one paragraph, and table header and separator rows are skipped.
    """
    lines = (DOCS / doc).read_text(encoding="utf-8").splitlines()
    out: list[Block] = []
    stack: list[tuple[int, str]] = []  # open headings as (level, anchor)
    anchor_of = _Slugger()
    para: list[str] = []  # lines of the paragraph being collected
    para_line = 0
    item: Block | None = None  # the list item or quote just read, which indented lines continue
    i = 0

    def flush() -> None:
        """End the current paragraph, if any, as a block."""
        if para:
            out.append(Block(doc, [a for _, a in stack], plain(" ".join(para)), para_line))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if m := re.match(r"^(#+) (.*)", line):
            flush()
            item = None
            # A heading closes every open heading at its level or deeper.
            level = len(m.group(1))
            stack[:] = [(lvl, a) for lvl, a in stack if lvl < level] + [(level, anchor_of(m.group(2)))]
        elif stripped.startswith("```"):
            # A fenced code block is one block, so a formula can be quoted like prose.
            flush()
            item = None
            start, i = i, i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            out.append(Block(doc, [a for _, a in stack], plain(" ".join(lines[start + 1 : i])), start + 1))
        elif stripped.startswith("|"):
            # A row followed by a separator row (|---|) is a header; neither is a requirement.
            flush()
            item = None
            header = i + 1 < len(lines) and re.match(r"^\|[\s|:-]+\|$", lines[i + 1].strip())
            separator = re.match(r"^\|[\s|:-]+\|$", stripped)
            if not header and not separator:
                out.append(Block(doc, [a for _, a in stack], plain(stripped.strip("|")), i + 1))
        elif re.match(r"^\s*(?:[-*]|\d+\.) ", line) or stripped.startswith(">"):
            flush()
            text = re.sub(r"^\s*(?:[-*]|\d+\.|>)\s*", "", line)
            item = Block(doc, [a for _, a in stack], plain(text), i + 1)
            out.append(item)
        elif not stripped:
            flush()
            item = None
        elif item and line[0].isspace():
            item.text = f"{item.text} {plain(stripped)}"  # a wrapped line continues its list item
        else:
            if not para:
                para_line = i + 1
            para.append(stripped)
        i += 1
    flush()
    return out


def scanned_docs() -> list[str]:
    """The requirement docs, relative to docs/."""
    docs = {p.relative_to(DOCS).as_posix() for pattern in SOURCES for p in DOCS.glob(pattern)}
    return sorted(docs - NOT_SCANNED)


@cache
def anchors(doc: str) -> frozenset[str]:
    """Every heading anchor in a doc, for checking `section` fields."""
    anchor_of = _Slugger()
    fenced = False
    found = set()
    for line in (DOCS / doc).read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
        elif not fenced and (m := re.match(r"^#+ (.*)", line)):
            found.add(anchor_of(m.group(1)))
    return frozenset(found)


# --- Matrix -------------------------------------------------------------------------------------


@dataclass
class Row:
    """One requirement row, with its section's defaults already applied."""

    id: str
    section: str  # doc#anchor
    quote: str
    kind: str
    delivery: str
    phase: int
    fixtures: list[str]
    oracle: str
    qualified_by: str
    note: str = ""

    @property
    def doc(self) -> str:
        """The doc part of `section`."""
        return self.section.split("#", 1)[0]


@dataclass
class Matrix:
    """The loaded matrix. `problems` holds what loading found (unknown fields); check() adds the rest."""

    rows: list[Row] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    started: set[str] = field(default_factory=set)  # milestones whose rows must be complete
    problems: list[str] = field(default_factory=list)


def load(path: Path = MATRIX) -> Matrix:
    """Read requirements.yaml, applying each section's defaults to its rows."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    matrix = Matrix(excluded=data.get("excluded", []), started=set(data.get("started", [])))
    for group in data.get("requirements") or []:
        if extra := set(group) - SECTION_FIELDS:
            matrix.problems.append(f"{group.get('section')}: unknown section fields {sorted(extra)}")
        if "section" not in group or "rows" not in group:
            matrix.problems.append(f"requirement group needs `section` and `rows`: {sorted(group)}")
            continue
        for raw in group["rows"]:
            if extra := set(raw) - ROW_FIELDS:
                matrix.problems.append(f"{raw.get('id')}: unknown fields {sorted(extra)}")
            values = {
                k: raw.get(k, group.get(k)) for k in ("kind", "delivery", "phase", "fixtures", "qualified_by", "note")
            }
            # Defaults: kind behavior; behavior rows qualify in their phase's milestone.
            kind = values["kind"] or "behavior"
            phase = values["phase"]
            row = Row(
                id=raw.get("id", "?"),
                section=group["section"],
                quote=raw.get("quote", ""),
                kind=kind,
                delivery=str(values["delivery"] or ""),
                phase=phase,
                fixtures=list(values["fixtures"] or []),
                oracle=raw.get("oracle", ""),
                qualified_by=values["qualified_by"] or (QUALIFIER.get(phase, "?") if kind == "behavior" else ""),
                note=values["note"] or "",
            )
            matrix.rows.append(row)
    return matrix


def milestone_of(path: Path) -> str | None:
    """'M1b' for docs/milestones/M01b-evaluation-gate.md; None for other files."""
    m = re.match(r"M(\d+)([a-z]?)-", path.name)
    return f"M{int(m.group(1))}{m.group(2)}" if m else None


def milestones() -> set[str]:
    """M1, M1b, M2, ... from the milestone file names."""
    return {name for path in (DOCS / "milestones").glob("M*.md") if (name := milestone_of(path))}


def _fixtures() -> dict[str, Any]:
    """The fixture registry; imported late, since it lives under tests/ and loads pxr."""
    if (tests := str(ROOT / "tests")) not in sys.path:
        sys.path.insert(0, tests)
    from fixtures.registry import FIXTURES

    return FIXTURES


def check(matrix: Matrix) -> list[str]:
    """Every problem with the matrix as human-readable lines; empty when it is consistent."""
    problems = list(matrix.problems)
    valid_milestones = milestones()
    fixtures = _fixtures()
    rows = {r.id: r for r in matrix.rows}

    # Fields: well-formed IDs, known kinds, phases, and milestones; completeness once a milestone starts.
    seen: set[str] = set()
    for r in matrix.rows:
        where = f"{r.id} ({r.section})"
        if not ID.match(r.id):
            problems.append(f"{where}: ID must look like AREA-NN")
        if r.id in seen:
            problems.append(f"{where}: duplicate ID")
        seen.add(r.id)
        if r.kind not in KINDS:
            problems.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if r.phase not in QUALIFIER:
            problems.append(f"{where}: phase must be 1 or 2")
        for name, value in [("delivery", r.delivery), ("qualified_by", r.qualified_by)]:
            if value not in valid_milestones:
                problems.append(f"{where}: {name} {value!r} is not a milestone")
        if not r.quote:
            problems.append(f"{where}: no quote")
        if r.delivery in matrix.started:
            if not r.oracle:
                problems.append(f"{where}: {r.delivery} has started, so the row needs an oracle")
            if r.kind == "behavior" and not r.fixtures:
                problems.append(f"{where}: {r.delivery} has started, so the behavior row needs a bespoke fixture")
        if r.kind == "behavior":
            if r.qualified_by != QUALIFIER.get(r.phase):
                problems.append(f"{where}: Phase {r.phase} behavior qualifies in {QUALIFIER.get(r.phase)}")
        for f in r.fixtures:
            if f not in fixtures:
                problems.append(f"{where}: fixture {f} is not in tests/fixtures/registry.py")

    # Quotes are in their sections; every block is quoted or excluded.
    # `covered` collects (doc, line) of each block that a row or exclusion traces.
    docs = scanned_docs()
    all_blocks = {doc: blocks(doc) for doc in docs}
    covered: set[tuple[str, int]] = set()
    for r in matrix.rows:
        doc, _, anchor = r.section.partition("#")
        if doc not in all_blocks:
            problems.append(f"{r.id}: {doc} is not a scanned requirement doc")
            continue
        if anchor not in anchors(doc):
            problems.append(f"{r.id}: no heading for #{anchor} in {doc}")
            continue
        # A quote matches a block in its section or any subsection; it must match exactly one.
        hits = [b for b in all_blocks[doc] if anchor in b.sections and plain(r.quote) in b.text]
        if not hits:
            problems.append(f"{r.id}: quote not found under {r.section}: {r.quote!r}")
        elif len(hits) > 1:
            problems.append(f"{r.id}: quote matches {len(hits)} blocks; quote more of the text: {r.quote!r}")
        covered.update((b.doc, b.line) for b in hits)
    for ex in matrix.excluded:
        where = f"excluded {ex.get('section')}"
        if extra := set(ex) - {"section", "quotes", "reason", "restates"}:
            problems.append(f"{where}: unknown fields {sorted(extra)}")
        if not ex.get("reason") and not ex.get("restates"):
            problems.append(f"{where}: give a reason, or the IDs it restates")
        problems += [f"{where}: restates unknown {rid}" for rid in ex.get("restates", []) if rid not in rows]
        doc, _, anchor = ex["section"].partition("#")
        if doc not in all_blocks or (anchor and anchor not in anchors(doc)):
            problems.append(f"{where}: no such section")
            continue
        # Unlike row quotes, an exclusion quote may match several blocks (for example "|" for
        # every table row); a section without an anchor is the whole doc.
        in_section = [b for b in all_blocks[doc] if not anchor or anchor in b.sections]
        for quote in ex.get("quotes") or [""]:  # no quotes: the whole section
            hits = [b for b in in_section if plain(quote) in b.text]
            if not hits:
                problems.append(f"{where}: matches nothing: {quote!r}")
            covered.update((b.doc, b.line) for b in hits)
    for bs in all_blocks.values():
        problems += [
            f"{b.doc}:{b.line}: not traced by any row or exclusion: {b.text[:90]!r}"
            for b in bs
            if (b.doc, b.line) not in covered and not _lead_in(b)
        ]

    # Invariants.
    problems += check_invariants(rows)

    # The started list names real milestones, and every registered fixture is assigned somewhere.
    problems += [f"started milestone {m!r} is not a milestone" for m in sorted(matrix.started - valid_milestones)]
    used = {f for r in matrix.rows for f in r.fixtures}
    problems += [f"fixture {f} is registered but no row lists it" for f in fixtures if f not in used]
    return problems


def _lead_in(block: Block) -> bool:
    """A short line introducing the list after it ('Support:'); the list items carry the requirements."""
    return block.text.endswith(":") and len(block.text) <= 80


def check_invariants(rows: dict[str, Row]) -> list[str]:
    """Every invariant bullet ends with '(ID, ID)', naming rows in the sections it links to."""
    problems = []
    raw_lines = (DOCS / INVARIANTS).read_text(encoding="utf-8").splitlines()
    for b in blocks(INVARIANTS):
        if b.sections == [] or b.text.startswith("Cross-cutting"):
            continue  # the file's introduction, not an invariant
        m = re.search(r"\(([A-Z][A-Z0-9-]*(?:, [A-Z][A-Z0-9-]*)*)\)$", b.text)
        if not m:
            problems.append(f"{INVARIANTS}:{b.line}: invariant names no requirement IDs: {b.text[:70]!r}")
            continue
        # Links are gone from the block's plain text, so read them from the raw line.
        raw = raw_lines[b.line - 1]
        targets = (_resolve(INVARIANTS, target) for target in re.findall(r"\]\(([^)]+)\)", raw))
        linked = {t for t in targets if t}
        for rid in m.group(1).split(", "):
            if rid not in rows:
                problems.append(f"{INVARIANTS}:{b.line}: unknown requirement {rid}")
            elif rows[rid].section not in linked:
                problems.append(
                    f"{INVARIANTS}:{b.line}: {rid} is in {rows[rid].section}, which the bullet does not link"
                )
    return problems


def _resolve(doc: str, target: str) -> str | None:
    """A relative link from doc, as docs-relative 'path#anchor'; None for external links and paths outside docs/."""
    path, _, anchor = target.partition("#")
    if re.match(r"^[a-z][a-z0-9+.-]*:", path, re.IGNORECASE):
        return None  # https:, mailto:, ...
    if not path:
        return f"{doc}#{anchor}"
    resolved = (DOCS / doc).parent.joinpath(path).resolve()
    if not resolved.is_relative_to(DOCS.resolve()):
        return None
    return f"{resolved.relative_to(DOCS.resolve()).as_posix()}#{anchor}"


# --- Rendering ----------------------------------------------------------------------------------


def render(matrix: Matrix) -> str:
    """requirements-matrix.md: one table per doc, rows in matrix order."""
    lines = [
        "# Requirement-to-Test Matrix",
        "",
        "Generated from [requirements.yaml](requirements.yaml) by `tools/matrix.py render`; do not edit.",
        "Each row quotes the requirement it traces; the linked section is authoritative.",
        "Kinds: **behavior** rows are checked by bespoke fixture tests; **contract** rows by the decision record",
        "of the milestone that settles them; **process** rows by tooling or CI. A row without fixtures or oracle",
        "is filled in by its delivering milestone before implementation.",
        "",
    ]
    total = {k: sum(r.kind == k for r in matrix.rows) for k in sorted(KINDS)}
    lines.append(
        f"{len(matrix.rows)} rows: "
        + ", ".join(f"{n} {k}" for k, n in total.items())
        + f"; milestones started: {', '.join(sorted(matrix.started))}."
    )
    lines.append("")
    current_doc = None
    for r in matrix.rows:
        if r.doc != current_doc:
            current_doc = r.doc
            lines += [
                f"## {current_doc}",
                "",
                "| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |",
                "|---|---|---|---|---|---|---|",
            ]
        link = f"[{r.id}](../{r.section})"  # sections are docs-relative; the view is in docs/testing/
        # "|" would end a table cell; rows of milestones not yet started show who fills them in.
        quote = r.quote.replace("|", "\\|")
        oracle = (r.oracle or f"Set by {r.delivery}.").replace("|", "\\|") + (f" *{r.note}*" if r.note else "")
        fixtures = ", ".join(f"`{f}`" for f in r.fixtures) or "—"
        cells = [link, quote, r.kind, r.delivery, f"{r.phase} / {r.qualified_by}", fixtures, oracle]
        lines.append(f"| {' | '.join(cells)} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Run check (also failing on a stale view) or render; exit 1 on any problem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "render"])
    args = parser.parse_args()
    matrix = load()
    problems = check(matrix)
    view = render(matrix)
    if args.command == "render":
        VIEW.write_text(view, encoding="utf-8")
        print(f"wrote {VIEW.relative_to(ROOT)}")
    elif not VIEW.exists() or VIEW.read_text(encoding="utf-8") != view:
        problems.append(f"{VIEW.relative_to(ROOT)} is out of date: run tools/matrix.py render")
    print("\n".join(problems) or f"matrix OK: {len(matrix.rows)} rows")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
