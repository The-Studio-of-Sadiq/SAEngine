"""The language of the reports and drawings (Project Settings › Project › Language).

SAEngine's screens are translated by the workbench's language pack; the reports and drawings are
written here, in Python, so they have a small message catalogue of their own: one JSON file per
language (``bn.json``), keyed by the English text it replaces. English is the source and needs no
file. A label without a translation is printed in English.

In Bangla the digits of printed numbers become Bengali digits (০-৯). What stays as it is:

- units and symbols (kN, mm, m², φVn) - they are Latin text, not digits;
- code clause numbers: ``Sec 8.3.5.2``, ``Table 8.5.1``, ``BNBC 2020``, ``ACI 318-11``
  (a number after a clause word, or one with two or more dots);
- identifiers that mix letters and digits: member marks (C1, B12), bar marks (B1-T2), sheet
  numbers (S-101), load combinations (1.2D+1.6L);
- any text left in English, so a sentence never mixes English words with Bengali digits.

A language pack from the marketplace (package kind ``languagePack``) can add a language or more
messages: :func:`register_messages` merges its ``messages`` over the built-in ones.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

#: Languages the reports and drawings can be written in (Project Settings ``project.language``).
LANGUAGES = {"en": "English", "bn": "বাংলা"}
DEFAULT_LANGUAGE = "en"

_BENGALI_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

#: Words after which a number is a code clause, edition or standard number and stays Latin.
CLAUSE_WORDS = {
    "sec", "sec.", "section", "sections", "table", "tables", "eq", "eq.", "eqs.", "part",
    "parts", "chapter", "ch.", "appendix", "annex", "fig.", "figure", "clause", "cl.", "§",
    "bnbc", "aci", "asce", "aisc", "aisi", "bs", "en", "iso", "is", "astm", "nfpa", "pti",
    "fema", "imarat", "bidhimala",
}  # fmt: skip
#: Words that continue a list of clauses ("Sec 6.3.10.6 and 6.3.10.7").
_CLAUSE_JOINERS = {"and", "or", "to", "ও", "এবং", "বা", "থেকে", "-", "–", ","}

_TOKEN = re.compile(r"\S+")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_CLAUSE_NUMBER = re.compile(r"^\(?\d+(\.\d+){2,}")
#: Short Latin tokens that are units or symbols, not English words.
_UNIT_WORDS = {
    "mm", "cm", "km", "kn", "kpa", "mpa", "gpa", "pa", "kg", "kgs", "cft", "kw", "kva", "kwh",
    "hz", "rpm", "lpcd", "kn/m", "kn/m²", "kn/m³", "kn·m", "knm", "mm²", "m²", "m³", "m/s",
    "l/min", "l/s", "m³/s", "w/m²", "ft", "in", "mph", "deg", "rad", "no.", "nos", "nos.", "dia",
    "thk", "max", "min", "ok", "na", "n/a", "x", "c/c",
}  # fmt: skip

_extra: dict[str, dict[str, str]] = {}


def normalize(language: str | None) -> str:
    """``language`` if the reports can be written in it, else English."""
    return language if language in LANGUAGES or language in _extra else DEFAULT_LANGUAGE


@cache
def _builtin(language: str) -> dict[str, str]:
    path = Path(__file__).with_name(f"{language}.json")
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (data.get("messages") or {}).items()}


@cache
def _installed(language: str) -> dict[str, str]:
    """The ``messages/*.json`` of the installed language packs of ``language`` (kind
    ``languagePack``, installed for the user; see docs/packages.md)."""
    messages: dict[str, str] = {}
    try:
        from saengine.codes.catalogue import _files
        from saengine.codes.manifest import MANIFEST_FILE, PackManifest
        from saengine.codes.registry import default_registry

        for info in default_registry().list_packs(None, "languagePack"):
            if not (info.effective and info.usable):
                continue
            manifest = PackManifest.model_validate_json(
                (Path(info.path) / MANIFEST_FILE).read_text(encoding="utf-8-sig")
            )
            if manifest.language != language:
                continue
            for path in _files(info):
                if path.parent.name == "messages" and path.suffix == ".json":
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                    messages.update({str(k): str(v) for k, v in data["messages"].items()})
    except Exception:  # noqa: BLE001 - a broken pack must not stop a report; validate shows it
        return messages
    return messages


@cache
def _merged(language: str) -> dict[str, str]:
    return {**_builtin(language), **_installed(language), **_extra.get(language, {})}


@cache
def _folded(language: str) -> dict[str, str]:
    return {k.casefold(): v for k, v in catalogue(language).items()}


def catalogue(language: str) -> dict[str, str]:
    """The messages of ``language``: English text → translation (empty for English). The
    built-in file, then the installed language packs, then :func:`register_messages`."""
    if language == DEFAULT_LANGUAGE:
        return {}
    return _merged(language)


def register_messages(language: str, messages: dict[str, str]) -> None:
    """Adds ``messages`` for ``language`` (they win over the built-in and installed ones)."""
    _extra.setdefault(language, {}).update({str(k): str(v) for k, v in messages.items()})
    clear_cache()


def clear_cache() -> None:
    """Forget the merged catalogues (after a language pack is installed or removed)."""
    _installed.cache_clear()
    _merged.cache_clear()
    _folded.cache_clear()


def project_language(settings: Any) -> str:
    """The reports' language of a project: its settings' ``project.language`` (a
    :class:`~saengine.library.settings.ProjectSettings` or the raw JSON mapping)."""
    project = getattr(settings, "project", None)
    if project is None and isinstance(settings, dict):
        project = settings.get("project")
    value = (
        project.get("language") if isinstance(project, dict) else getattr(project, "language", None)
    )
    return normalize(value)


def to_bengali_digits(text: str) -> str:
    """Every ASCII digit of ``text`` as a Bengali digit, nothing else changed."""
    return text.translate(_BENGALI_DIGITS)


def _is_english(text: str) -> bool:
    """Whether ``text`` has an English word (two or more Latin letters that are not a unit, a
    symbol or part of an identifier with digits)."""
    for token in _TOKEN.findall(text):
        bare = token.strip("()[],;:.")
        if not _LATIN_WORD.search(bare) or any(c.isdigit() for c in bare):
            continue
        if bare.casefold() in _UNIT_WORDS or bare.casefold() in CLAUSE_WORDS:
            continue
        if bare.isupper() and len(bare) <= 5:
            continue  # an abbreviation: BNBC, SPT, BOQ, FAIL
        return True
    return False


_MONTHS_BN = {
    "January": "জানুয়ারি", "February": "ফেব্রুয়ারি", "March": "মার্চ", "April": "এপ্রিল",
    "May": "মে", "June": "জুন", "July": "জুলাই", "August": "আগস্ট", "September": "সেপ্টেম্বর",
    "October": "অক্টোবর", "November": "নভেম্বর", "December": "ডিসেম্বর",
}  # fmt: skip


def localize_date(text: str, language: str) -> str:
    """A printed date ("1 November 2026", "2026-11-01") in ``language``."""
    if language != "bn":
        return text
    for english, bangla in _MONTHS_BN.items():
        text = re.sub(rf"\b{english}\b", bangla, text)
    return text if _is_english(text) else to_bengali_digits(text)


def localize_digits(text: str) -> str:
    """Bengali digits for the numbers of ``text``, keeping clause numbers and identifiers."""
    out: list[str] = []
    clause = False
    last = 0
    for match in _TOKEN.finditer(text):
        token = match.group()
        out.append(text[last : match.start()])
        last = match.end()
        bare = token.strip("()[],;:")
        folded = bare.casefold()
        has_digit = any(c.isdigit() for c in bare)
        if folded in CLAUSE_WORDS:
            clause = True
            out.append(token)
            continue
        if not has_digit:
            if folded not in _CLAUSE_JOINERS:
                clause = False
            out.append(token)
            continue
        if clause and token[-1] in ":;।":
            clause = False  # the clause list ends here; this number is still part of it
            out.append(token)
            continue
        if clause or "{" in bare or _CLAUSE_NUMBER.match(bare) or re.search(r"[A-Za-z]", bare):
            out.append(token)  # a clause number, or an identifier such as C1, S-101, 1.2D
            continue
        out.append(to_bengali_digits(token))
    out.append(text[last:])
    return "".join(out)


def translate(text: str, language: str) -> str:
    """The translation of ``text`` in ``language``: the catalogue's message (exact, then ignoring
    case), else segment by segment for drawing subtitles ("SCALE 1:100   LEVEL +3.000"), else
    ``text`` itself. Numbers get Bengali digits in Bangla unless the text stays English."""
    if language == DEFAULT_LANGUAGE or not text:
        return text
    messages = catalogue(language)
    if not messages:
        return text
    found = _lookup(text, language)
    if found is not None:
        return localize_digits(found) if language == "bn" else found
    if "\n" in text:
        return "\n".join(translate(line, language) for line in text.split("\n"))
    parts = re.split(r"(\s{2,})", text)
    if len(parts) > 1:
        return "".join(p if not p.strip() else translate(p, language) for p in parts)
    prefixed = _prefixed(text, language)
    if prefixed is not None:
        return prefixed
    if _is_english(text):
        return text
    return localize_digits(text) if language == "bn" else text


def _lookup(text: str, language: str) -> str | None:
    stripped = text.strip()
    found = catalogue(language).get(stripped)
    if found is None:
        found = _folded(language).get(stripped.casefold())
    if found is None:
        return None
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    return lead + found + trail


def _prefixed(text: str, language: str) -> str | None:
    """A known label followed by a value: "SCALE 1:100", "LEVEL +3.000", "Part 6"."""
    words = text.split(" ")
    for n in range(len(words) - 1, 0, -1):
        head, rest = " ".join(words[:n]), " ".join(words[n:])
        if _is_english(rest):
            continue
        found = _lookup(head, language)
        if found is not None:
            value = localize_digits(rest) if language == "bn" else rest
            return f"{found} {value}"
    return None


# ─────────────────────────────────── the report document ───────────────────────────────────

#: The fixed texts of the report renderers (templates/report.typ and report/word.py).
REPORT_LABELS = {
    "check": "Check",
    "demand": "Demand",
    "capacity": "Capacity",
    "unit": "Unit",
    "util": "Util.",
    "combination": "Combination",
    "result": "Result",
    "codeBasis": "Code basis",
    "date": "Date",
    "contents": "Contents",
    "readBeforeUse": "Read before use.",
    "warnings": "This report carries {0} warning(s), listed in the Limitations section.",
    "preparedTypst": "Prepared with SAEngine {0} (AGPL-3.0), typeset with Typst.",
    "preparedWord": "Prepared with SAEngine {0} (AGPL-3.0).",
    "disclaimer": "This report presents the results of computer analysis and design. It shall "
    "be reviewed, checked and signed by the structural engineer responsible for the design.",
    "fail": "FAIL",
    "updateField": "Update the field (F9) to fill it in.",
}


def report_labels(language: str) -> dict[str, str]:
    return {key: translate(text, language) for key, text in REPORT_LABELS.items()}


def number(value: Any, language: str) -> str:
    """``value`` as printed text in ``language`` (Bengali digits in Bangla)."""
    text = str(value)
    return to_bengali_digits(text) if language == "bn" else text


def localize_document(document: dict[str, Any], language: str) -> dict[str, Any]:
    """The report document of :func:`saengine.report.document.report_document` in
    ``language``: its headings, labels, table heads and values translated where the catalogue
    has them, with Bengali digits in Bangla; plus ``lang`` and ``labels`` (the renderers' own
    fixed texts). User text (project name, cover note) is kept, only its digits are not
    changed either."""
    language = normalize(language)
    tr = lambda text: translate(text, language) if isinstance(text, str) else text
    doc = dict(document)
    doc["lang"] = language
    doc["labels"] = report_labels(language)
    if language == DEFAULT_LANGUAGE:
        return doc
    meta = dict(doc.get("meta") or {})
    for key in ("details", "titleBlock"):
        if isinstance(meta.get(key), list):
            meta[key] = [[tr(label), value] for label, value in meta[key]]
    for key in ("title", "units"):
        if isinstance(meta.get(key), str):
            meta[key] = tr(meta[key])
    for key in ("date", "isoDate"):
        if isinstance(meta.get(key), str):
            meta[key] = localize_date(meta[key], language)
    doc["meta"] = meta
    cover = dict(doc.get("cover") or {})
    if isinstance(cover.get("title"), str):
        cover["title"] = tr(cover["title"])
    doc["cover"] = cover
    status = dict(doc.get("status") or {})
    if isinstance(status.get("headline"), str):
        status["headline"] = tr(status["headline"])
    doc["status"] = status
    doc["sections"] = [
        {
            **s,
            "title": tr(s.get("title", "")),
            "blocks": [_block(b, tr) for b in s.get("blocks", [])],
        }
        for s in doc.get("sections", [])
    ]
    return doc


def _block(block: dict[str, Any], tr: Any) -> dict[str, Any]:
    out = dict(block)
    for key in ("text", "strong", "title"):
        if isinstance(out.get(key), str):
            out[key] = tr(out[key])
    if isinstance(out.get("head"), list):
        out["head"] = [tr(c) for c in out["head"]]
    for key in ("rows",):
        if isinstance(out.get(key), list):
            out[key] = [[tr(c) for c in row] if isinstance(row, list) else row for row in out[key]]
    if isinstance(out.get("items"), list):
        out["items"] = [tr(i) for i in out["items"]]
    return out
