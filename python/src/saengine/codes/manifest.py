"""The manifest of a code pack (``pack.json``) and the problems reported about a pack.

A code pack is a folder::

    <id>/
      pack.json         the manifest (:class:`PackManifest`)
      data/<table>.json one file per table it provides (``locations.json``, ``combinations.json``, ...)
      hooks.py          optional: functions that override design functions (run only when trusted)
      docs/             optional: notes, the sources the values come from

The JSON Schema of ``pack.json`` is :func:`manifest_schema` (exported to
``codes/schemas/code-pack.schema.json``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class Source(BaseModel):
    """A document the pack's values come from (a code, a standard, a gazette notification)."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Short reference used in the tables' clause refs, e.g. 'BNBC'.")
    title: str
    edition: str | None = None
    publisher: str | None = None
    url: str | None = None


class PackManifest(BaseModel):
    """``pack.json``: what the pack is, which pack it builds on and which tables it provides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(
        default=None, alias="$schema", description="Path of the JSON Schema, for editors."
    )
    comment: str | None = Field(default=None, alias="$comment")
    schema_: Literal["saengine.codePack/1"] = Field(default=MANIFEST_SCHEMA_ID, alias="schema")
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
    author: str | None = None
    licence: str | None = Field(default=None, description="SPDX id of the pack's licence.")
    hooks: str | None = Field(
        default=None,
        description="Python file in the pack (e.g. 'hooks.py') whose top-level functions "
        "override design functions of the same name. Imported only when the user trusts the "
        "pack; editing the file revokes the trust.",
    )


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
    usable: bool = True
    problems: list[Problem] = Field(default_factory=list)


def manifest_schema() -> dict[str, Any]:
    """JSON Schema of ``pack.json``."""
    schema = PackManifest.model_json_schema(by_alias=True)
    schema["$id"] = MANIFEST_SCHEMA_ID
    schema["title"] = "SAEngine code pack"
    return schema
