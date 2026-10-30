"""The manifest of a code pack (``pack.json``) and the problems reported about a pack.

A code pack is a folder::

    <id>/
      pack.json         the manifest (:class:`PackManifest`)
      data/<table>.json one file per table it provides (``locations.json``, ``combinations.json``, ...)
      hooks.py          optional: functions that override design functions (run only when trusted)
      docs/             optional: notes, the sources the values come from

The same manifest describes every package of the marketplace (docs/marketplace-plan.md): its
``kind`` is a design code (the default, so every older pack stays valid), a structure template
(``templates/*.json``: presets of a parametric shape) or a building template (``spec.json``: a
building specification, or ``template.civil``: an inputs-only project). ``requires`` names the
SAEngine versions and the other packages it needs, ``contents`` its files of the kind,
``preview`` its card image. A package holds data, and Python ``hooks`` at most: never programs
(:data:`PROGRAM_SUFFIXES`).

The JSON Schema of ``pack.json`` is :func:`manifest_schema` (exported to
``codes/schemas/code-pack.schema.json``).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MANIFEST_SCHEMA_ID = "saengine.codePack/1"
MANIFEST_FILE = "pack.json"
DATA_DIR = "data"

# The areas a pack can cover: the table names of :mod:`saengine.codes.tables`.
KNOWN_TABLES: tuple[str, ...] = (
    "locations",
    "zoneCoefficients",
    "windSpeeds",
    "areaLoads",
    "combinations",
    "seismic",
    "wind",
    "materials",
    "factors",
    "concrete",
    "detailing",
    "steel",
    "occupancyCategories",
    "foundations",
)

PACK_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"

Kind = Literal["designCode", "structureTemplate", "buildingTemplate"]
KINDS: tuple[Kind, ...] = ("designCode", "structureTemplate", "buildingTemplate")
DEFAULT_KIND: Kind = "designCode"
KIND_NAMES: dict[str, str] = {
    "designCode": "design code",
    "structureTemplate": "structure template",
    "buildingTemplate": "building template",
}
# The files of each kind when pack.json gives no ``contents`` (globs relative to the folder).
DEFAULT_CONTENTS: dict[str, tuple[str, ...]] = {
    "designCode": (f"{DATA_DIR}/*.json",),
    "structureTemplate": ("templates/*.json",),
    "buildingTemplate": ("spec.json", "template.civil"),
}
PREVIEW_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

# Files a package may never hold: programs, scripts and libraries that Windows or a shell would
# run. Python hooks (.py) are the only code, and they run only when trusted.
PROGRAM_SUFFIXES: frozenset[str] = frozenset(
    {
        ".exe", ".dll", ".pyd", ".so", ".dylib", ".sys", ".drv", ".ocx", ".cpl", ".scr",
        ".com", ".msi", ".msp", ".msix", ".appx", ".appxbundle", ".bat", ".cmd", ".ps1",
        ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".mjs", ".cjs", ".wsf", ".wsh",
        ".hta", ".lnk", ".url", ".reg", ".jar", ".sh", ".application", ".gadget", ".pif",
    }
)  # fmt: skip
MAX_FILE_BYTES = 5 * 1024 * 1024  # any file of a package but a .civil
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024  # a .civil (a full building template)
MAX_PACKAGE_BYTES = 200 * 1024 * 1024  # a whole package, unpacked
MAX_PREVIEW_BYTES = 1024 * 1024

_VERSION_CLAUSE = r"(?:>=|<=|==|!=|~=|>|<)?\s*\d+(?:\.\d+)*"
# A version requirement: comparisons joined by commas (">=0.0.50", ">=1.0, <2"); a bare version
# means "==".
VERSION_SPEC_PATTERN = rf"^\s*{_VERSION_CLAUSE}(?:\s*,\s*{_VERSION_CLAUSE})*\s*$"


class Source(BaseModel):
    """A document the pack's values come from (a code, a standard, a gazette notification)."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Short reference used in the tables' clause refs, e.g. 'BNBC'.")
    title: str
    edition: str | None = None
    publisher: str | None = None
    url: str | None = None


class Requires(BaseModel):
    """What a package needs: the SAEngine versions that understand it and other packages."""

    model_config = ConfigDict(extra="forbid")

    saengine: str | None = Field(
        default=None,
        pattern=VERSION_SPEC_PATTERN,
        description="SAEngine versions the package works with, e.g. '>=0.0.50'.",
    )
    packages: dict[str, str] = Field(
        default_factory=dict,
        description="Other packages it needs, by id, with their versions, e.g. "
        "{'bnbc2020': '>=1.0.0'} for a building template made with BNBC 2020.",
    )

    @field_validator("packages")
    @classmethod
    def _packages(cls, value: dict[str, str]) -> dict[str, str]:
        for pack_id, spec in value.items():
            if not re.match(PACK_ID_PATTERN, pack_id):
                raise ValueError(f"'{pack_id}' is not a package id")
            if not re.match(VERSION_SPEC_PATTERN, spec):
                raise ValueError(f"'{spec}' ({pack_id}) is not a version requirement like '>=1.0'")
        return value

class Basis(BaseModel):
    """What the report and the design method state the design follows. A pack that extends
    another inherits the labels it does not give; without any, the pack's edition (or name)."""

    model_config = ConfigDict(extra="forbid")

    general: str | None = Field(default=None, description="Loads and general, e.g. 'BNBC 2020'.")
    concrete: str | None = Field(
        default=None, description="Concrete design, e.g. 'BNBC 2020 Part 6 Chapter 6'."
    )
    steel: str | None = Field(
        default=None, description="Steel design, e.g. 'BNBC 2020 Part 6 Chapter 10'."
    )
    method: str | None = Field(
        default=None, description="Design method, e.g. 'Strength design (LRFD)'."
    )


class PackManifest(BaseModel):
    """``pack.json``: what the pack is, which pack it builds on and which tables it provides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(
        default=None, alias="$schema", description="Path of the JSON Schema, for editors."
    )
    comment: str | None = Field(default=None, alias="$comment")
    schema_: Literal["saengine.codePack/1"] = Field(default=MANIFEST_SCHEMA_ID, alias="schema")
    kind: Kind = Field(
        default=DEFAULT_KIND,
        description="What the package holds: a design code (default), a structure template "
        "(presets of a parametric shape) or a building template.",
    )
    id: str = Field(
        pattern=PACK_ID_PATTERN,
        description="Unique id: lower case letters, digits, '.', '_' and '-', e.g. 'bnbc2020'.",
    )
    name: str = Field(min_length=1, description="Readable name, e.g. 'BNBC 2020'.")
    edition: str | None = Field(default=None, description="Edition or year of the code.")
    country: str | None = Field(default=None, description="ISO 3166 country code, e.g. 'BD'.")
    region: str | None = Field(default=None, description="State, province or city, when local.")
    version: str = Field(default="1.0.0", description="Version of the pack itself.")
    extends: str | None = Field(
        default=None,
        description="Id of the pack this one builds on; tables not provided here are inherited.",
    )
    covers: list[str] = Field(
        default_factory=list,
        description="The areas (table names) this pack provides, e.g. ['locations', 'wind'].",
    )
    description: str | None = None
    sources: list[Source] = Field(
        default_factory=list, description="The documents the values come from."
    )
    clauses: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Clause references per table, e.g. {'combinations': ['BNBC Part 6 2.7.3']}; "
        "a data file's own '$sources' take precedence.",
    )
    basis: Basis | None = Field(
        default=None,
        description="The code the design follows, as the report states it (loads and general, "
        "concrete, steel, design method).",
    )
    author: str | None = None
    licence: str | None = Field(default=None, description="SPDX id of the pack's licence.")
    hooks: str | None = Field(
        default=None,
        description="Python file in the pack (e.g. 'hooks.py') whose top-level functions "
        "override design functions of the same name. Imported only when the user trusts the "
        "pack; editing the file revokes the trust.",
    )
    requires: Requires | None = Field(
        default=None, description="The SAEngine versions and the other packages it needs."
    )
    contents: list[str] | None = Field(
        default=None,
        description="The package's files of its kind, as paths or globs relative to its folder "
        "(default: 'data/*.json' for a design code, 'templates/*.json' for a structure template, "
        "'spec.json' and 'template.civil' for a building template).",
    )
    preview: str | None = Field(
        default=None,
        description="Card image of the package: a small .png, .jpg or .webp in its folder.",
    )

    def content_globs(self) -> tuple[str, ...]:
        """``contents``, else the kind's default files."""
        return tuple(self.contents) if self.contents is not None else DEFAULT_CONTENTS[self.kind]


Severity = Literal["error", "warning"]


class Problem(BaseModel):
    """Something wrong with a pack. A pack with an ``error`` (its own or its parents') is
    listed but cannot be loaded or activated."""

    severity: Severity = "error"
    message: str
    file: str | None = None
    table: str | None = None


# "folder": a pack read straight from a folder (validate, load_path), above every other scope.
Scope = Literal["project", "user", "builtin", "folder"]
SCOPE_ORDER: tuple[Scope, ...] = ("project", "user", "builtin")  # installed, highest first


class PackInfo(BaseModel):
    """A pack found on disk, for the pack list (``saengine codepack list``, the Code Packs page)."""

    id: str
    kind: Kind = DEFAULT_KIND
    name: str
    edition: str | None = None
    country: str | None = None
    region: str | None = None
    version: str | None = None
    extends: str | None = None
    covers: list[str] = Field(default_factory=list)
    tables: list[str] = Field(
        default_factory=list, description="Tables of the resolved pack (own and inherited)."
    )
    chain: list[str] = Field(
        default_factory=list, description="Ids from this pack up to its root ancestor."
    )
    scope: Scope
    path: str
    effective: bool = Field(
        default=True, description="False when a pack of a higher scope has the same id."
    )
    shadowedBy: Scope | None = None
    shadows: list[Scope] = Field(
        default_factory=list, description="Lower scopes with a pack of the same id."
    )
    hooks: bool = Field(
        default=False, description="Whether hooks run with this pack: its own or its parents'."
    )
    trusted: bool | None = Field(
        default=None,
        description="Whether every hooks file of the chain is trusted; None without hooks. "
        "Built-in packs are always trusted.",
    )
    hooksFrom: list[str] = Field(
        default_factory=list, description="Ids of the packs in the chain that have hooks."
    )
    untrustedHooks: list[str] = Field(
        default_factory=list,
        description="Ids of the packs in the chain whose hooks are not trusted (they do not run).",
    )
    requires: Requires | None = None
    missingRequires: list[str] = Field(
        default_factory=list,
        description="Ids of the required packages that are not installed, or not in a version "
        "it accepts (to offer installing them).",
    )
    contents: list[str] = Field(
        default_factory=list, description="The package's files of its kind (relative paths)."
    )
    preview: str | None = Field(default=None, description="Full path of the card image.")
    usable: bool = True
    problems: list[Problem] = Field(default_factory=list)


def manifest_schema() -> dict[str, Any]:
    """JSON Schema of ``pack.json``."""
    schema = PackManifest.model_json_schema(by_alias=True)
    schema["$id"] = MANIFEST_SCHEMA_ID
    schema["title"] = "SAEngine package (code pack)"
    return schema


def version_tuple(text: str | None) -> tuple[int, ...] | None:
    """``"1.2.0"`` -> ``(1, 2, 0)``; None when the version is not dotted numbers (a leading "v"
    and a pre-release or build suffix after "-" or "+" are ignored)."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)(?:[-+].*)?\s*$", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def version_satisfies(version: str | None, spec: str) -> bool | None:
    """Whether ``version`` meets the requirement ``spec`` (:data:`VERSION_SPEC_PATTERN`); None
    when either cannot be read. Versions are padded with zeros (1.0 == 1.0.0); ``~=1.4.2`` means
    ``>=1.4.2, <1.5``."""
    have = version_tuple(version)
    if have is None or not re.match(VERSION_SPEC_PATTERN, spec or ""):
        return None
    for clause in spec.split(","):
        m = re.match(r"^\s*(>=|<=|==|!=|~=|>|<)?\s*(\d+(?:\.\d+)*)\s*$", clause)
        assert m is not None
        op, want = m.group(1) or "==", tuple(int(x) for x in m.group(2).split("."))
        if op == "~=":
            if len(want) < 2:
                return None
            upper = want[:-2] + (want[-2] + 1,)
            if not (_cmp(have, want) >= 0 and _cmp(have, upper) < 0):
                return False
            continue
        c = _cmp(have, want)
        ok = {">=": c >= 0, "<=": c <= 0, "==": c == 0, "!=": c != 0, ">": c > 0, "<": c < 0}
        if not ok[op]:
            return False
    return True


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)
