"""The worksheet machinery: kinds, their inputs, and the calculation record they write.

A kind is a function registered with :func:`worksheet` that reads its inputs from a
:class:`Sheet` and writes steps (a value with its formula and clause) and checks (a demand
against a capacity) on it. The kinds compute nothing themselves that a design module already
computes: they call the design functions of :mod:`saengine.design`,
:mod:`saengine.drawings.detailing`, :mod:`saengine.substructure.shallow`,
:mod:`saengine.soil.bearing` and :mod:`saengine.fem.loads`, so a worksheet and the design of
the model always agree, and the code pack in force supplies the coefficients.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

#: The printed name of the code the clauses refer to (the pack's own clauses carry it already).
CODE = "BNBC 2020 Part 6"

InputKind = Literal["number", "choice", "bool"]


@dataclass(frozen=True)
class Input:
    """One input of a kind: a number (with its unit), a choice or a yes/no."""

    name: str
    label: str
    default: float | str | bool
    unit: str = ""
    help: str = ""
    choices: tuple[tuple[str, str], ...] = ()  # (value, label)
    minimum: float | None = None
    maximum: float | None = None
    group: str = ""

    @property
    def kind(self) -> InputKind:
        if self.choices:
            return "choice"
        if isinstance(self.default, bool):
            return "bool"
        return "number"

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "unit": self.unit,
            "help": self.help,
            "group": self.group,
        }
        if self.choices:
            out["choices"] = [{"value": v, "label": label} for v, label in self.choices]
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        return out


def number(name: str, label: str, default: float, unit: str = "", **kw: Any) -> Input:
    return Input(name, label, float(default), unit, **kw)


def choice(name: str, label: str, default: str, choices: Sequence[tuple[str, str]], **kw) -> Input:
    return Input(name, label, default, choices=tuple(choices), **kw)


def flag(name: str, label: str, default: bool = False, **kw: Any) -> Input:
    return Input(name, label, bool(default), **kw)


#: Inputs every concrete worksheet shares.
def concrete_inputs(fc: float = 25.0, fy: float = 420.0, group: str = "Materials") -> list[Input]:
    return [
        number("fc", "f'c", fc, "MPa", minimum=10, maximum=100, group=group),
        number("fy", "fy", fy, "MPa", minimum=200, maximum=700, group=group),
    ]


def fmt(value: float, digits: int | None = None) -> str:
    """A value as printed: 3 significant figures (at least whole units above 100)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if isinstance(value, float) and math.isinf(value):
        return "∞"
    if digits is not None:
        return f"{value:,.{digits}f}"
    size = abs(value)
    if size >= 100:
        return f"{value:,.0f}"
    if size >= 10:
        return f"{value:.1f}"
    if size >= 1:
        return f"{value:.2f}"
    if size == 0:
        return "0"
    return f"{value:.3g}"


class WorksheetInputError(ValueError):
    """An input outside its range: the calculation is not made."""


@dataclass
class Sheet:
    """What a kind writes while it calculates (and the inputs it reads)."""

    values: dict[str, Any]
    steps: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def heading(self, text: str) -> None:
        """A sub-heading between the steps."""
        self.steps.append({"heading": text})

    def step(
        self,
        label: str,
        value: float | str,
        unit: str = "",
        formula: str = "",
        clause: str = "",
        digits: int | None = None,
    ) -> float | str:
        """Writes one intermediate value and returns it (for the next line)."""
        text = value if isinstance(value, str) else fmt(float(value), digits)
        row: dict[str, Any] = {
            "label": label,
            "value": text,
            "unit": unit,
            "formula": formula,
            "clause": clause,
        }
        if not isinstance(value, str):
            row["number"] = float(value) if math.isfinite(float(value)) else None
        self.steps.append(row)
        return value

    def check(
        self,
        label: str,
        demand: float,
        capacity: float,
        unit: str = "",
        clause: str = "",
        *,
        at_least: bool = False,
        digits: int | None = None,
    ) -> bool:
        """Writes a check: ``demand`` <= ``capacity`` (``at_least``: ``demand`` >= ``capacity``,
        a provided value against a minimum). Utilisation is demand / capacity (the inverse for
        ``at_least``)."""
        if at_least:
            ok = demand >= capacity - 1e-9
            util = capacity / demand if demand > 0 else math.inf
        else:
            ok = demand <= capacity + 1e-9
            util = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
        self.checks.append(
            {
                "label": label,
                "demand": fmt(demand, digits),
                "capacity": fmt(capacity, digits),
                "sense": "≥" if at_least else "≤",
                "unit": unit,
                "utilisation": round(util, 3) if math.isfinite(util) else None,
                "ok": ok,
                "clause": clause,
            }
        )
        return ok

    def adopt(self, check: dict[str, Any], clause: str = "") -> bool:
        """Writes a check made by a design module (:func:`saengine.design.check._check`:
        ``{name, demand, capacity, unit, utilisation, ok, note}``) as it is."""
        util = check.get("utilisation")
        self.checks.append(
            {
                "label": str(check["name"]),
                "demand": fmt(float(check["demand"])),
                "capacity": fmt(float(check["capacity"])),
                "sense": "≤",
                "unit": str(check.get("unit") or ""),
                "utilisation": None if util is None or util >= 99 else float(util),
                "ok": bool(check["ok"]),
                "clause": "; ".join(t for t in (str(check.get("note") or ""), clause) if t),
            }
        )
        return bool(check["ok"])

    def note(self, text: str) -> None:
        self.notes.append(text)


Calculation = Callable[[Sheet], None]


@dataclass(frozen=True)
class Kind:
    id: str
    title: str
    group: str
    summary: str
    inputs: tuple[Input, ...]
    calculate: Calculation
    references: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "group": self.group,
            "summary": self.summary,
            "inputs": [i.describe() for i in self.inputs],
            "references": list(self.references),
        }

    def defaults(self) -> dict[str, Any]:
        return {i.name: i.default for i in self.inputs}


KINDS: dict[str, Kind] = {}


def worksheet(
    kind_id: str,
    title: str,
    *,
    group: str,
    summary: str,
    inputs: Sequence[Input],
    references: Sequence[str] = (),
) -> Callable[[Calculation], Calculation]:
    """Registers a worksheet kind."""

    def register(calculate: Calculation) -> Calculation:
        if kind_id in KINDS:
            raise ValueError(f"worksheet kind {kind_id!r} registered twice")
        names = [i.name for i in inputs]
        if len(set(names)) != len(names):
            raise ValueError(f"worksheet kind {kind_id!r} repeats an input name")
        KINDS[kind_id] = Kind(
            kind_id, title, group, summary, tuple(inputs), calculate, tuple(references)
        )
        return calculate

    return register


def _coerce(spec: Input, raw: Any, problems: list[str]) -> Any:
    if raw is None:
        return spec.default
    if spec.kind == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if spec.kind == "choice":
        allowed = [v for v, _ in spec.choices]
        if str(raw) in allowed:
            return str(raw)
        problems.append(f"{spec.label}: '{raw}' is not one of {', '.join(allowed)}")
        return spec.default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        problems.append(f"{spec.label}: '{raw}' is not a number")
        return spec.default
    if not math.isfinite(value):
        problems.append(f"{spec.label}: not a finite number")
        return spec.default
    unit = f" {spec.unit}" if spec.unit else ""
    if spec.minimum is not None and value < spec.minimum:
        problems.append(f"{spec.label} = {fmt(value)}{unit} is below {fmt(spec.minimum)}{unit}")
    if spec.maximum is not None and value > spec.maximum:
        problems.append(f"{spec.label} = {fmt(value)}{unit} is above {fmt(spec.maximum)}{unit}")
    return value


def calculate(kind_id: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """The calculation of a worksheet ``kind_id`` for ``inputs`` (the kind's defaults where an
    input is not given): ``{kind, title, inputs, steps, checks, notes, ok, utilisation,
    problems}``. With a problem in the inputs, or an input the design functions refuse, nothing
    is calculated and ``problems`` says why."""
    kind = KINDS.get(kind_id)
    if kind is None:
        return {"kind": kind_id, "problems": [f"Unknown worksheet kind {kind_id!r}."]}
    given = inputs or {}
    problems: list[str] = []
    values = {spec.name: _coerce(spec, given.get(spec.name), problems) for spec in kind.inputs}
    shown = [
        {
            "name": spec.name,
            "label": spec.label,
            "value": _shown(spec, values[spec.name]),
            "unit": spec.unit,
            "group": spec.group,
        }
        for spec in kind.inputs
    ]
    out: dict[str, Any] = {
        "kind": kind.id,
        "title": kind.title,
        "references": list(kind.references),
        "inputs": shown,
        "steps": [],
        "checks": [],
        "notes": [],
        "problems": problems,
    }
    if problems:
        return out
    sheet = Sheet(values)
    try:
        kind.calculate(sheet)
    except (WorksheetInputError, ValueError, ZeroDivisionError) as error:
        out["problems"] = [str(error) or type(error).__name__]
        out["steps"] = sheet.steps
        return out
    utilisations = [c["utilisation"] for c in sheet.checks]
    out.update(
        steps=sheet.steps,
        checks=sheet.checks,
        notes=sheet.notes,
        ok=all(c["ok"] for c in sheet.checks),
        utilisation=(
            None if any(u is None for u in utilisations) else max(utilisations, default=0.0)
        ),
    )
    return out


def _shown(spec: Input, value: Any) -> str:
    if spec.kind == "bool":
        return "yes" if value else "no"
    if spec.kind == "choice":
        return dict(spec.choices).get(value, str(value))
    return fmt(float(value))


def kinds() -> list[dict[str, Any]]:
    """Every worksheet kind with its inputs, grouped as the menus list them."""
    return [k.describe() for k in KINDS.values()]
