"""The feature registry behind the ribbon's buttons (owner, 2026-11-23).

Every ribbon button of the catalog (scripts/ribbon/ribbon_catalog.json) whose feature is built
is one function here::

    @feature("soilBearing.ultimateBearing", "Ultimate Bearing Capacity", part="soil",
             fields=[number("width", "Footing width", 2.0, unit="m", min=0.1)])
    def ultimate_bearing(ctx: FeatureContext, values: dict) -> FeatureResult:
        ...
        return result(summary={...}, tables=[table(...)], notes=[...])

The id is the button's catalog id (``<tab>.<slug of its label>``). The workbench learns the
fields from :func:`describe` (exported to scripts/ribbon/features.json at build time), shows them
in the button's panel, and runs the function through the ``features/run`` engine method.

A feature reads the project through :class:`FeatureContext` (the parts' files) and the code
pack in force (``saengine.report.clauses.in_force``); it never names a design code itself.
"""

from __future__ import annotations

import importlib
import json
import math
import pkgutil
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

FeatureResult = dict[str, Any]


@dataclass(frozen=True)
class Field:
    """One input of a feature's panel."""

    key: str
    label: str
    type: str  # number | text | select | checkbox
    default: Any
    unit: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    min: float | None = None
    max: float | None = None
    help: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "label": f"{self.label} [{self.unit}]" if self.unit else self.label,
            "type": self.type,
            "default": self.default,
        }
        if self.options:
            out["options"] = [{"value": v, "label": label} for v, label in self.options]
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.help:
            out["help"] = self.help
        return out


def number(
    key: str,
    label: str,
    default: float,
    *,
    unit: str | None = None,
    min: float | None = None,
    max: float | None = None,
    help: str | None = None,
) -> Field:
    return Field(key, label, "number", default, unit, (), min, max, help)


def text(key: str, label: str, default: str = "", *, help: str | None = None) -> Field:
    return Field(key, label, "text", default, help=help)


def select(
    key: str,
    label: str,
    options: Iterable[tuple[str, str]],
    default: str | None = None,
    *,
    help: str | None = None,
) -> Field:
    # (value, label) pairs; a plain string is its own label.
    opts = tuple((o, o) if isinstance(o, str) else (o[0], o[1]) for o in options)
    return Field(
        key,
        label,
        "select",
        default if default is not None else opts[0][0],
        options=opts,
        help=help,
    )


def checkbox(key: str, label: str, default: bool = False, *, help: str | None = None) -> Field:
    return Field(key, label, "checkbox", default, help=help)


class FeatureContext:
    """The project a feature runs on: its folder and the parts' files, read on demand."""

    PART_FILES: ClassVar[dict[str, str]] = {
        "soil": "01 Soil Report/soil-report.json",
        "settings": "02 Project Settings/project-settings.json",
        "materials": "03 Materials/materials.json",
        "objects": "04 Objects/objects.json",
        "floorPlan": "05 Floor Plan/floor-plan.json",
        "bim": "06 BIM/bim.json",
        "mep": "07 MEP/mep.json",
        "substructure": "09 Substructure/substructure.json",
        "boq": "10 BOQ/boq.json",
    }

    def __init__(self, project_root: str | Path | None) -> None:
        self.root = Path(project_root) if project_root else None
        self._cache: dict[str, Any] = {}

    def path(self, relative: str) -> Path | None:
        return self.root / relative if self.root else None

    def raw(self, part: str) -> dict[str, Any] | None:
        """The part's main file as JSON, or None when the project or the file is missing."""
        if part in self._cache:
            return self._cache[part]
        path = self.path(self.PART_FILES[part])
        data = None
        if path is not None and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
        self._cache[part] = data
        return data

    def soil(self) -> Any | None:
        """The soil report as the engine's model, or None."""
        raw = self.raw("soil")
        if raw is None:
            return None
        from saengine.library.soil import SoilReport

        try:
            return SoilReport.model_validate(raw)
        except ValueError:
            return None

    def settings(self) -> Any:
        """The project settings (the defaults when the file is missing)."""
        from saengine.library.settings import ProjectSettings, default_project_settings

        raw = self.raw("settings")
        if raw is None:
            return default_project_settings()
        try:
            return ProjectSettings.model_validate(raw)
        except ValueError:
            return default_project_settings()


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    part: str
    fields: tuple[Field, ...]
    run: Callable[[FeatureContext, dict[str, Any]], FeatureResult]
    help: str = ""
    requires_project: bool = True
    tags: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "part": self.part,
            "help": self.help,
            "requiresProject": self.requires_project,
            "fields": [f.to_dict() for f in self.fields],
        }


REGISTRY: dict[str, Feature] = {}


def feature(
    feature_id: str,
    title: str,
    *,
    part: str,
    fields: Iterable[Field] = (),
    help: str = "",
    requires_project: bool = True,
) -> Callable[
    [Callable[[FeatureContext, dict[str, Any]], FeatureResult]], Callable[..., FeatureResult]
]:
    """Registers the decorated function as the feature of the ribbon button ``feature_id``."""

    def wrap(
        fn: Callable[[FeatureContext, dict[str, Any]], FeatureResult],
    ) -> Callable[..., FeatureResult]:
        if feature_id in REGISTRY:
            raise ValueError(f"feature {feature_id!r} registered twice")
        REGISTRY[feature_id] = Feature(
            feature_id,
            title,
            part,
            tuple(fields),
            fn,
            help or (fn.__doc__ or "").strip().split("\n")[0],
            requires_project,
        )
        return fn

    return wrap


def table(
    title: str,
    columns: Iterable[tuple[str, str] | tuple[str, str, str]],
    rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """A result table: columns as (key, title) or (key, title, unit)."""
    cols = []
    for column in columns:
        key, label = column[0], column[1]
        unit = column[2] if len(column) > 2 else None
        cols.append({"key": key, "title": f"{label} [{unit}]" if unit else label})
    return {"title": title, "columns": cols, "rows": list(rows)}


def result(
    summary: dict[str, Any] | None = None,
    tables: Iterable[dict[str, Any]] = (),
    notes: Iterable[str] = (),
    problems: Iterable[str] = (),
) -> FeatureResult:
    return {
        "summary": summary or {},
        "tables": list(tables),
        "notes": list(notes),
        "problems": list(problems),
    }


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "model_dump"):
        return _clean(value.model_dump(mode="json"))
    return value


_LOADED = False

# "'NoneType' object has no attribute 'barFactor'" from a code-pack table the pack lacks, or a
# field missing from the pack's table model ("'PushoverTable' object has no attribute 'method'").
_PACK_GAP = re.compile(
    r"'(?:NoneType|[A-Za-z]*Table|Wind|Seismic|Concrete[A-Za-z]*)' object has no attribute '(?P<name>[A-Za-z_]+)'"
)


def load_all() -> None:
    """Imports every module of this package, which registers their features."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for info in pkgutil.walk_packages(__path__, __name__ + "."):
        importlib.import_module(info.name)


def describe() -> list[dict[str, Any]]:
    load_all()
    return [REGISTRY[k].to_dict() for k in sorted(REGISTRY)]


def run(
    feature_id: str, project_root: str | None, values: dict[str, Any] | None = None
) -> FeatureResult:
    """Runs a feature with its inputs (missing ones take their defaults)."""
    load_all()
    found = REGISTRY.get(feature_id)
    if found is None:
        return result(problems=[f"No feature {feature_id!r} in this version."])
    merged = {f.key: f.default for f in found.fields}
    for key, value in (values or {}).items():
        if key in merged:
            merged[key] = value
    for f in found.fields:
        if f.type == "number":
            try:
                merged[f.key] = float(merged[f.key])
            except (TypeError, ValueError):
                return result(problems=[f"{f.label}: a number is needed."])
    context = FeatureContext(project_root)
    from saengine.report.clauses import in_force

    try:
        # The project's code pack is in force (the default pack without a project): code
        # values come from it, never from the feature.
        with in_force(context.root) as pack_problems:
            out = found.run(context, merged)
    except FeatureInputError as error:
        return result(problems=[str(error)])
    except AttributeError as error:
        # An engine method another code pack defines: its table is missing from the active pack.
        missing = _PACK_GAP.search(str(error))
        if missing is None:
            raise
        return result(
            problems=[
                (
                    f"The active code pack has no data for this method ({missing.group('name')}); "
                    "it is defined by other code packs. Choose one in Project Settings > Code & Packs."
                )
            ]
        )
    if pack_problems:
        out.setdefault("notes", []).extend(pack_problems)
    return _clean(out)


class FeatureInputError(ValueError):
    """A feature cannot run on these inputs or this project; the message says why."""
