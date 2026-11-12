"""Retrieval over the code pack in force and SAEngine's manual, for the AI assistant's code Q&A.

The assistant answers questions on the design code only from what this module finds: passages
of the code pack's tables (``saengine.codes``, the built-in BNBC 2020 pack unless the project
chooses another), each with the clauses its table or entry names, and sections of the user
manual. When nothing matches, :func:`search_code` says so (``found: False``) and the assistant
answers "not in the pack" instead of quoting a clause from memory.

The ranking is plain BM25 over words and clause numbers ("6.2.14"), with a boost for a clause
number the question names: no embeddings, no model, nothing downloaded.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Longest passage text [characters]; bigger nodes are split into their entries.
PASSAGE_CHARS = 700
#: Longest manual section [characters]; longer ones are cut into parts.
DOC_CHARS = 1200
#: Most passages returned.
MAX_LIMIT = 20
#: Keys whose string values cite a clause, table, row or source.
CITATION_KEYS = ("$sources", "source", "sources", "clause", "clauses", "ref", "reference", "row")
#: BM25 parameters (the usual ones).
BM25_K1 = 1.4
BM25_B = 0.75
#: Score added per clause number of the question found in a passage's citations.
CLAUSE_BOOST = 6.0
#: The environment variable that points to the docs folder when it is not beside the package.
DOCS_ENV = "SAENGINE_DOCS_DIR"

# Not "0.20": a clause number starts with 1-9.
_CLAUSE = re.compile(r"\b[1-9]\d*(?:\.\d+)+[a-z]?")
# Words, clause numbers, and runs of Bangla script (U+0980-U+09FF).
_WORD = re.compile("[a-z0-9]+(?:\\.[0-9]+)*[a-z]?|[ঀ-৿]+")
_STOP = frozenset(
    {
        *("a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is"),
        *("it", "its", "of", "on", "or", "the", "to", "what", "when", "which", "with", "does"),
        *("do", "i", "my", "me", "we", "our", "this", "that", "there", "per", "vs", "can"),
        *("should", "must"),
    }
)


@dataclass
class Passage:
    """One piece of text the assistant may quote, with where it comes from."""

    id: str
    kind: str  # "pack" or "docs"
    title: str
    text: str
    citations: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list, repr=False)

    def to_json(self, score: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "text": self.text,
            "citations": self.citations,
            "score": round(score, 3),
        }


def tokenize(text: str) -> list[str]:
    """Lower-case words and clause numbers ("6.2.14" stays one token), stop words left out."""
    tokens: list[str] = []
    for token in _WORD.findall(text.lower()):
        if token in _STOP:
            continue
        tokens.append(token)
        # "6.2.14" also matches "6.2" and "6": a question may name the section only.
        if "." in token and token[0].isdigit():
            parts = token.split(".")
            tokens.extend(".".join(parts[:i]) for i in range(2, len(parts)))
    return tokens


def clause_numbers(text: str) -> list[str]:
    """The clause, table or section numbers written in ``text`` ("Table 6.2.14" -> "6.2.14")."""
    return _CLAUSE.findall(text.lower())


# ---------------------------------------------------------------- the code pack


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def _own_citations(node: Any) -> list[str]:
    if not isinstance(node, dict):
        return []
    found: list[str] = []
    for key in CITATION_KEYS:
        found.extend(_strings(node.get(key)))
    return found


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "), default=str)


def _unique(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item.strip(), None)
    return [item for item in seen if item]


def pack_passages(table: str, data: Any, sources: list[str]) -> Iterator[Passage]:
    """Passages of one table of a pack: each node small enough to read whole, bigger dicts and
    lists split into their entries. Each passage cites its own clauses, its parents' and the
    table's ``$sources`` (the pack's ``clauses`` when the file has none)."""

    def walk(node: Any, path: list[str], inherited: list[str]) -> Iterator[Passage]:
        cites = _unique([*_own_citations(node), *inherited])
        text = _compact(node)
        splittable = (isinstance(node, dict) and node) or (
            isinstance(node, list) and any(isinstance(v, (dict, list)) for v in node)
        )
        if len(text) <= PASSAGE_CHARS or not splittable:
            label = ".".join([table, *path]) if path else table
            body = text if len(text) <= PASSAGE_CHARS * 2 else text[: PASSAGE_CHARS * 2] + " ..."
            yield Passage(
                id=f"pack:{label}",
                kind="pack",
                title=label,
                text=f"{label}: {body}",
                citations=cites or list(sources),
            )
            return
        entries = node.items() if isinstance(node, dict) else enumerate(node)
        scalars: dict[str, Any] = {}
        for key, child in entries:
            key = str(key)
            if key.startswith("$") or key in CITATION_KEYS:
                continue
            if isinstance(child, (dict, list)):
                yield from walk(child, [*path, key], cites)
            else:
                scalars[key] = child
        if scalars:
            label = ".".join([table, *path]) if path else table
            yield Passage(
                id=f"pack:{label}#values",
                kind="pack",
                title=label,
                text=f"{label}: {_compact(scalars)[: PASSAGE_CHARS * 2]}",
                citations=cites or list(sources),
            )

    top = data if isinstance(data, dict) else {"values": data}
    yield from walk({k: v for k, v in top.items() if k != "$schema"}, [], list(sources))


def _settings(project_root: Path | None) -> dict[str, Any] | None:
    if project_root is None:
        return None
    try:
        text = (project_root / "02 Project Settings" / "project-settings.json").read_text(
            encoding="utf-8"
        )
        value = json.loads(text)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def code_pack_passages(project_root: Path | None = None) -> tuple[dict[str, Any], list[Passage]]:
    """The pack in force for the project (its settings' ``codePack``, else BNBC 2020) and the
    passages of every usable table."""
    from saengine.codes import registry

    pack = registry.active(_settings(project_root), project_root)
    passages: list[Passage] = []
    for name in pack.tables():
        if name in pack.broken:
            # A broken table is left out; the rest of the pack still answers.
            continue
        data = pack.data(name)
        sources = [s for s in pack.source(name) if isinstance(s, str)]
        passages.extend(pack_passages(name, data, sources))
    info = {"id": pack.id, "name": pack.name, "edition": pack.edition, "chain": pack.chain}
    return info, passages


# ---------------------------------------------------------------- the manual


def docs_dir() -> Path | None:
    """The folder holding ``manual/``: :data:`DOCS_ENV`, else the repository's ``docs`` beside
    the package (a source checkout or an install that ships the docs); None when neither has it."""
    candidates: list[Path] = []
    configured = os.environ.get(DOCS_ENV)
    if configured:
        candidates.append(Path(configured))
    here = Path(__file__).resolve()
    candidates.extend(parent / "docs" for parent in here.parents[2:5])
    for candidate in candidates:
        if (candidate / "manual").is_dir():
            return candidate
    return None


def markdown_passages(name: str, text: str) -> Iterator[Passage]:
    """Sections of a Markdown file (split at headings, long ones cut), each citing the file and
    heading, plus the clause numbers it names."""
    heading = name
    lines: list[str] = []
    part = 0

    def flush() -> Iterator[Passage]:
        nonlocal part
        body = "\n".join(lines).strip()
        while body:
            chunk, body = body[:DOC_CHARS], body[DOC_CHARS:]
            part += 1
            cites = [f"SAEngine manual, {name} › {heading}"]
            cites.extend(
                f"clause {c} (as named in the manual)" for c in _unique(clause_numbers(chunk))[:4]
            )
            yield Passage(
                id=f"docs:{name}#{part}",
                kind="docs",
                title=f"{name} › {heading}",
                text=chunk,
                citations=cites,
            )

    for line in text.splitlines():
        match = re.match(r"^#{1,4}\s+(.*)$", line)
        if match:
            yield from flush()
            lines = []
            heading = match.group(1).strip()
        else:
            lines.append(line)
    yield from flush()


def doc_passages(folder: Path | None = None) -> list[Passage]:
    folder = folder if folder is not None else docs_dir()
    if folder is None:
        return []
    passages: list[Passage] = []
    for path in sorted((folder / "manual").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        passages.extend(markdown_passages(f"manual/{path.name}", text))
    return passages


# ---------------------------------------------------------------- ranking


def rank(query: str, passages: list[Passage], limit: int) -> list[tuple[float, Passage]]:
    """BM25 over the passages' text and citations, plus :data:`CLAUSE_BOOST` per clause number
    of the question found in a passage's citations. Passages with no matching word are left out."""
    terms = tokenize(query)
    if not terms or not passages:
        return []
    for passage in passages:
        if not passage.tokens:
            passage.tokens = tokenize(
                f"{passage.title} {passage.text} {' '.join(passage.citations)}"
            )
    count = len(passages)
    average = sum(len(p.tokens) for p in passages) / count or 1.0
    frequency: Counter[str] = Counter()
    for passage in passages:
        frequency.update(set(passage.tokens))
    clauses = set(clause_numbers(query))
    scored: list[tuple[float, Passage]] = []
    for passage in passages:
        counts = Counter(passage.tokens)
        score = 0.0
        for term in set(terms):
            tf = counts.get(term, 0)
            if not tf:
                continue
            df = frequency[term]
            idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
            norm = tf + BM25_K1 * (1 - BM25_B + BM25_B * len(passage.tokens) / average)
            score += idf * tf * (BM25_K1 + 1) / norm
        if score <= 0:
            continue
        if clauses:
            cited = " ".join(passage.citations).lower()
            score += CLAUSE_BOOST * sum(1 for c in clauses if c in cited)
        scored.append((score, passage))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    return scored[:limit]


def search_code(
    query: str,
    project_root: str | Path | None = None,
    limit: int = 8,
    include_docs: bool = True,
) -> dict[str, Any]:
    """The passages of the code pack in force (and the manual) that best match ``query``:
    ``{"pack": {id, name, edition, chain}, "query", "found", "passages": [{id, kind, title, text,
    citations, score}], "note"}``. ``found`` is False when no passage matches a word of the
    question: the assistant must then say the pack does not cover it."""
    from saengine.codes import context as code_context

    root = code_context.find_project_root(project_root) if project_root else None
    limit = max(1, min(int(limit or 8), MAX_LIMIT))
    info, passages = code_pack_passages(root)
    if include_docs:
        passages.extend(doc_passages())
    ranked = rank(query, passages, limit)
    return {
        "pack": info,
        "query": query,
        "found": bool(ranked),
        "passages": [passage.to_json(score) for score, passage in ranked],
        "note": (
            "Quote only these passages and their citations. Pack passages are the values SAEngine "
            "designs with; manual passages explain how SAEngine uses them."
            if ranked
            else "Nothing in the code pack or the manual matches: the pack does not cover this."
        ),
    }
