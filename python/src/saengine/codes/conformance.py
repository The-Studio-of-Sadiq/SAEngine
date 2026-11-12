"""The conformance checks every code pack must pass (alpha 9 C26: "make sure our software works
at ease with any country code").

:func:`check_pack` reads a resolved pack (:class:`saengine.codes.registry.CodePack`) and
returns what is wrong with it as a whole, beyond what loading validates table by table:

- **loads**: no table is broken (failed to merge or validate);
- **covers**: every area ``covers`` names is a table the pack gives itself (a data file of its
  own); a data file of its own that ``covers`` leaves out is a warning;
- **sources**: every table the pack gives itself says where its values come from (its file's
  ``$sources``, ``source`` or ``sources``, or the manifest's ``clauses`` of the table);
- **clause ownership**: a pack's own clause texts never speak for another code ("SAEngine
  practice where <code> is silent" names this pack's code), and every table it inherits is
  labelled with the pack that supplies it (:func:`saengine.codes.context.attribute`);
- **actions**: the seismic and wind tables exist and the strength combinations hold an
  earthquake and a wind row, unless the pack declares the area in ``notCovered``;
- **units and bar names**: the bar names and nominal masses are keyed by sizes of
  ``concrete.barDiameters``; ``units`` is a known system;
- **verification**: the pack states whether its values were checked (``VERIFY.md`` or
  ``verified``), a warning otherwise.

``saengine codepack check <pack>`` runs them; ``tests/test_codes_conformance.py`` runs them
over every installed pack (built-in and a sample user pack) and, marked slow, derives and
designs a generated building under each.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

#: The checks, in the order :func:`check_pack` runs them.
CHECKS = ("loads", "covers", "sources", "clauses", "actions", "bars", "verification")

#: "where <code> is silent", "where <code> gives no ...": a clause text that speaks for a code.
_SPEAKS_FOR = re.compile(r"where ([A-Z][A-Za-z0-9 .:/()-]{1,40}?) (?:is silent|gives no\b)")


@dataclass(frozen=True)
class Finding:
    """One thing wrong with a pack: ``level`` "error" (the pack does not conform) or
    "warning"; ``check`` one of :data:`CHECKS`; ``table`` the table it is about, if any."""

    level: str
    check: str
    message: str
    table: str | None = None

    def __str__(self) -> str:
        where = f" [{self.table}]" if self.table else ""
        return f"{self.level}: {self.check}{where}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _own_tables(pack: Any) -> dict[str, Any]:
    """The tables the pack gives itself: table name -> its own file (``TableFile``); a help-only
    file of ``saengine codepack new`` (only ``$help``/``$example``) changes nothing."""
    from saengine.codes.registry import gives_table

    found = pack._found
    return {name: table for name, table in found.tables.items() if gives_table(found, name)}


def _texts(value: Any) -> list[str]:
    """Every string inside ``value`` (a table's data)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    return []


def _code_names(pack: Any) -> set[str]:
    """The names this pack's own texts may speak for: its edition, name, id, ``tableCodes``
    and ``basis`` labels."""
    info = pack.info
    names = {pack.id, info.name, info.edition or ""}
    names |= set(info.tableCodes.values())
    names |= set(pack.basis.values())
    names |= {s.title for s in info.sources} | {s.id for s in info.sources}
    return {n for n in names if n}


def _speaks_for_own(code: str, names: set[str]) -> bool:
    """Whether ``code`` (as a text names it, "EN 1992-1-1 10.9.4") is one of ``names``: by
    its designation, its first two words ("EN 1992-1-1", "BNBC 2020", "ACI 318-19")."""
    code = code.strip()
    designation = " ".join(code.split()[:2])
    return any(code in name or name in code or designation in name for name in names)


def check_pack(pack: Any) -> list[Finding]:
    """The conformance findings of ``pack`` (see the module's docstring); empty for a pack that
    conforms without remarks."""
    findings: list[Finding] = []
    own = _own_tables(pack)
    info = pack.info
    # A pack inherits what its parents declare not covered (BS 8110's children).
    not_covered = {
        area
        for f in pack._chain
        if f.manifest is not None
        for area in (getattr(f.manifest, "notCovered", None) or [])
    }
    # Walk 4: the extended pack's tables the pack declares not applicable are not covered.
    not_covered |= set(getattr(pack, "not_applicable", None) or [])

    # loads
    for name, problems in pack.broken.items():
        message = problems[0].message if problems else "cannot be used"
        findings.append(Finding("error", "loads", message, name))

    # covers
    for name in info.covers:
        if name not in own:
            findings.append(
                Finding(
                    "error",
                    "covers",
                    f"'covers' names '{name}' but the pack has no data/{name}.json of its own",
                    name,
                )
            )
    for name in sorted(own):
        if name not in info.covers:
            findings.append(
                Finding(
                    "warning",
                    "covers",
                    f"data/{name}.json changes the table but 'covers' does not name it",
                    name,
                )
            )

    # sources
    for name, table in sorted(own.items()):
        data = table.data if isinstance(table.data, dict) else {}
        has = bool(table.sources) or bool(info.clauses.get(name))
        has = has or bool(data.get("source")) or bool(data.get("sources"))
        if not has:
            findings.append(
                Finding(
                    "error",
                    "sources",
                    "no '$sources', 'source' or 'sources' says where its values come from",
                    name,
                )
            )

    # clause ownership: own texts speak for this code; inherited tables are labelled
    names = _code_names(pack)
    for name, table in sorted(own.items()):
        texts = _texts(table.data) + [str(s) for s in table.sources]
        for text in texts:
            for match in _SPEAKS_FOR.finditer(text):
                if not _speaks_for_own(match.group(1), names):
                    findings.append(
                        Finding(
                            "error",
                            "clauses",
                            f"its own text speaks for another code: '{match.group(0)}'",
                            name,
                        )
                    )
    from saengine.codes import context as code_context

    probe = "SAEngine practice (probe)"
    for name in pack.tables():
        if name in own or name in pack.broken:
            continue
        owner = pack.value_owner(name)
        if owner is None:
            continue
        shown = code_context.attribute(probe, name, pack=pack)
        if owner[1] != pack.info.table_code(name) and "inherited from" not in shown:
            findings.append(
                Finding(
                    "error",
                    "clauses",
                    f"inherited from '{owner[0]}' but its texts are not labelled with it",
                    name,
                )
            )

    # actions: earthquake and wind
    for area, case in (("seismic", "E"), ("wind", "W")):
        if area in not_covered:
            continue
        if not pack.has(area):
            findings.append(
                Finding("error", "actions", f"no '{area}' table and not in 'notCovered'", area)
            )
            continue
        try:
            rows = pack.table("combinations").strength
        except Exception as error:  # noqa: BLE001 - reported as the finding
            findings.append(Finding("error", "actions", str(error), "combinations"))
            break
        if not any(r.factors.get(case) for r in rows):
            findings.append(
                Finding(
                    "error",
                    "actions",
                    f"no strength combination with {case} (declare '{area}' in 'notCovered' "
                    "when the code does not design for it)",
                    "combinations",
                )
            )

    # units and bar names
    if info.units not in (None, "SI", "USCustomary"):
        findings.append(Finding("error", "bars", f"unknown units '{info.units}'"))
    if pack.has("concrete") and "concrete" not in pack.broken:
        concrete = pack.table("concrete")
        sizes = {
            f"{float(d):g}"
            for group in concrete.barDiameters.model_dump().values()
            if isinstance(group, list)
            for d in group
        }
        for field in ("barNames", "barMasses"):
            keyed = getattr(concrete, field, None) or {}
            stray = sorted(k for k in keyed if f"{float(k):g}" not in sizes)
            if stray:
                findings.append(
                    Finding(
                        "error",
                        "bars",
                        f"concrete.{field} names sizes that barDiameters does not have: "
                        + ", ".join(stray),
                        "concrete",
                    )
                )

    # verification
    status = pack.verification
    if status.status == "unstated":
        findings.append(Finding("warning", "verification", status.message))
    return findings


def errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == "error"]
