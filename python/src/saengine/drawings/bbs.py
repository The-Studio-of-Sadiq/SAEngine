"""Bar bending schedules (BBS) from the reinforcement detailing model (11 Exports, drawings).

A schedule lists every bar mark of the detailed members the way a fabricator cuts and bends it:
member, mark, bar type and size, shape code, the dimensions A to E, the number of members by
the bars in each, the cutting length, the total length and the mass, with remarks (zone, lap).
Totals are given per bar size and per element type, and the schedule can be set against the
bill of quantities (10 BOQ), which takes these bars for every element the drawings detail.

The schedule follows the standard the code pack names (alpha 9 C14: its ``barSchedule`` table,
:mod:`saengine.codes.bar_schedule_tables`; the default pack: BS 8666): its shape codes with
their dimension letters and cutting-length formulas, its minimum radii and end projections, the
rounding of the lengths, the bar size label, the columns and the sheet title. This module has no
shape or formula of its own: a formula is an expression the pack gives (:func:`evaluate`).

Conventions (units: mm for lengths and dimensions, m for total lengths, kg for masses):

- the dimensions are outside dimensions, as the detailing model gives them; the cutting length
  ``L`` is the standard's formula in them, the bar size ``d`` and the bend radius ``r``;
- the bend radius is the larger of the standard's minimum scheduling radius (where it gives
  one) and half the code's least inside bend diameter
  (:func:`saengine.drawings.detailing.bend_diameter`; in the default pack BNBC 2020 Part 6,
  8.1.2.2 and Table 6.8.1: 6 d for 10-25 mm bars, 8 d over 25 to 40 mm, 10 d over 40 mm; 4 d
  for stirrups and ties of 16 mm and smaller);
- the hook of a link (the letter its shape names as ``hook``, C of BS 8666 shapes 51 and 63)
  is the code's 135° seismic hook (:func:`saengine.drawings.detailing.seismic_hook`: in the
  default pack an extension of 6 d but not less than 75 mm, BNBC 2020 Part 6, 8.1.2.1 (c)(iv)
  and (d)) as the standard's ``linkHook`` measures it, and no straight end is shorter than the
  standard's minimum end projection ``P`` (where it gives one);
- cutting lengths are rounded (up, in the default pack to the next 25 mm) to the standard's
  ``roundTo``; bar mass is ``d² / 162`` kg/m (7850 kg/m³).

How it is called (pure functions, no files read)::

    schedule = bar_schedule(detailing)           # detailing: the detailing model (see below)
    schedule.rows / .by_diameter / .by_kind / .total / .notes
    text = schedule_csv(schedule)                # write with encoding="utf-8-sig", newline=""
    table = sheet_table(schedule)                # rows and column widths for the BBS sheets
    rec = reconcile(schedule, boq)               # boq: BillOfQuantities or the boq.json dict
    rec.rows / .notes; reconciliation_table(rec) # the same as a table

The detailing model is a mapping or an object (attributes or keys alike) with ``elements``:
each element has ``id``, ``kind`` (column, beam, slab, wall, stair, footing, pile cap, ...),
``member`` (the label to print; defaults to ``id``), ``story``, ``count`` (identical members,
default 1) and ``bars``. Each bar has ``mark``, ``dia`` [mm], ``shape`` (a shape code of the
standard such as ``"51"`` or a name: straight, L, U, link, stirrup, tie, hook, ...), ``count``
(bars per member), and either ``dims`` (``{"A": ..., "B": ...}``, outside dimensions) or
``segments`` (outside lengths in the order A, B, C, ...; numbers or ``{"length": ...}``) or only
``length`` (the cutting length, scheduled as given). Optional: ``material`` or ``grade``
(``"B420DWR"``), ``radius`` [mm] (overrides the bend radius), ``bendDia`` [mm] (the detailing
model's least inside bend diameter: the radius is at least half of it), ``role``
(longitudinal, top, bottom, stirrup, tie, mesh, ...), ``zone``, ``lap`` [mm] (lap length
included in each bar), ``curtailed`` (true for a cut-off bar; "true"/"yes"/"1" texts too),
``members`` (overrides the element's count), ``remarks``. A shape's ``radius`` letter (R of BS
8666 shape 12) is an optional large bend radius in ``dims``; its ``counts`` letters (C of shape
77) are counts (turns). A pile element (kind ``pile``) may name its ``cap``: the BOQ books pile
bars under the cap's id. Numbers may be texts such as ``"12"`` or ``"Ø12"``; a bar with a value
that is not a number is not scheduled and gets a note (no bar's problem raises). This is
:mod:`saengine.drawings.detailing`'s ``detailing_model`` output (kinds beam, column, slab, wall,
staircase, footing, pileCap).
"""

from __future__ import annotations

import ast
import csv
import io
import json
import math
import operator
import re
import textwrap
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any

LETTERS = ("A", "B", "C", "D", "E")


def bar_mass(dia: float) -> float:
    """Mass of a bar [kg/m] of diameter ``dia`` [mm] (7850 kg/m³)."""
    return dia * dia / 162


def round_up(length: float, step: float | None = None) -> float:
    """``length`` rounded up to the next ``step`` (default: the standard's ``roundTo``; a
    millimetre of float noise is ignored)."""
    step = standard().roundTo if step is None else step
    return math.ceil(length / step - 1e-6) * step


def round_length(length: float) -> float:
    """A cutting length rounded as the standard rounds it (up or to the nearest ``roundTo``)."""
    std = standard()
    if std.rounding == "nearest":
        return math.floor(length / std.roundTo + 0.5) * std.roundTo
    return round_up(length, std.roundTo)


# ─────────────────────────────────── the standard ───────────────────────────────────


def _table() -> Any:
    from saengine.codes import context as code_context

    return code_context.pack_table("barSchedule")


@cache
def _builtin_standards() -> dict[str, tuple[str, Any]]:
    """Standard id -> (built-in pack name, standard) of every built-in pack's ``barSchedule``."""
    from saengine.codes.tables import PACKS_DIR, validate_table

    found: dict[str, tuple[str, Any]] = {}
    for path in sorted(PACKS_DIR.glob("*/data/barSchedule.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            table = validate_table("barSchedule", raw.get("$data", raw))
            name = json.loads((path.parent.parent / "pack.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key, std in table.standards.items():
            found.setdefault(key, (str(name.get("name") or path.parent.parent.name), std))
    return found


def standard_of(table: Any) -> tuple[Any, str]:
    """The standard ``table`` (a ``barSchedule`` table) picks and a note when it is not the
    pack's own: one of a built-in pack's (a project override naming another standard), or the
    pack's first when no pack gives it."""
    std = table.standards.get(table.standard)
    if std is not None:
        return std, ""
    builtin = _builtin_standards().get(table.standard)
    if builtin is not None:
        pack, std = builtin
        return std, f"The bar schedule standard '{table.standard}' is the {pack} pack's."
    if not table.standards:
        raise ValueError("the code pack gives no bar schedule standard")
    key, std = next(iter(table.standards.items()))
    return std, f"No bar schedule standard '{table.standard}': {std.name} ('{key}') is used."


def standard() -> Any:
    """The bar schedule standard of the code pack in force (its ``barSchedule``)."""
    return standard_of(_table())[0]


def shape_key_on() -> bool:
    """Whether the schedule's sheets draw the shape key (the pack's ``barSchedule.shapeKey``)."""
    return bool(_table().shapeKey)


def length_display() -> tuple[str, Callable[[float], str]]:
    """How the schedule shows lengths and dimensions given in mm: (unit label, format).

    Alpha 9 C14 / C13 seam: the schedule keeps every length in mm; the project's display units
    (C13, US customary feet and inches) are to be applied here, in this one function, when they
    are merged. Until then the schedule prints mm under every standard."""
    return "mm", lambda mm: f"{mm:.0f}"


# ─────────────────────────────────── formulas ───────────────────────────────────

_BINARY: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_CALLS: dict[str, Callable[..., float]] = {
    "max": max,
    "min": min,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
}


@cache
def _parsed(expression: str) -> ast.expr:
    try:
        return ast.parse(expression, mode="eval").body
    except SyntaxError as error:
        raise ValueError(f"the formula '{expression}' cannot be read") from error


def evaluate(expression: str, values: Mapping[str, float]) -> float:
    """The value of a pack's formula ``expression`` (numbers, the names in ``values`` and
    ``pi``, + - * / ** and brackets, max, min, sqrt, ceil); anything else raises ValueError."""

    def ev(node: ast.expr) -> float:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in values:
                return values[node.id]
            if node.id == "pi":
                return math.pi
            raise ValueError(f"'{expression}' needs {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
            value = ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _CALLS
            and not node.keywords
        ):
            return float(_CALLS[node.func.id](*(ev(a) for a in node.args)))
        raise ValueError(f"'{expression}': only arithmetic, max, min, sqrt and ceil are read")

    return ev(_parsed(expression))


# ─────────────────────────────────── radii and hooks ───────────────────────────────────


def _by_size(table: Mapping[str, float], dia: float) -> float | None:
    for key, value in table.items():
        try:
            if float(key) == dia:
                return float(value)
        except ValueError:
            continue
    return None


def standard_radius(dia: float) -> float:
    """The standard's minimum scheduling radius [mm] (0 when it gives none): its table, else
    its steps (BS 8666: 2 d up to 16 mm and 3.5 d, rounded up, above)."""
    rule = standard().radius
    if rule is None:
        return 0.0
    value = _by_size(rule.bySize, dia)
    if value is not None:
        return value
    for step in rule.steps:
        if step.upTo is None or dia <= step.upTo:
            r = step.factor * dia
            return math.ceil(r) if step.ceil else r
    return 0.0


def bs8666_radius(dia: float) -> float:
    """The standard's minimum scheduling radius [mm] (the name of before alpha 9 C14)."""
    return standard_radius(dia)


def end_projection(dia: float) -> float | None:
    """The standard's minimum end projection P [mm] (None: it gives none): its table, else
    r + k d rounded up (BS 8666: r + 11 d rounded up to 5 mm)."""
    rule = standard().endProjection
    if rule is None:
        return None
    value = _by_size(rule.bySize, dia)
    if value is not None:
        return value
    return round_up(standard_radius(dia) + rule.radiusDb * dia, rule.roundTo)


def code_bend_diameter(dia: float, transverse: bool = False) -> float:
    """The code's least inside bend diameter [mm]
    (:func:`saengine.drawings.detailing.bend_diameter`)."""
    from saengine.drawings.detailing import bend_diameter

    return float(bend_diameter(dia, transverse).value)


def _bend_reference() -> str:
    """The code's bend diameter clause, as the schedule's note names it ("BNBC 2020 Part 6,
    8.1.2.2" in the default pack)."""
    from saengine.codes import context as code_context
    from saengine.drawings import detailing

    if detailing._bar_shapes() is not None:  # alpha 9 C5c: the pack's own bends (EN 1992-1-1)
        cited = detailing._shapes_cite()
        if cited:
            return cited
    return code_context.cite("citations", "bbsBend") or "the code's least bend diameter"


def bend_radius(dia: float, transverse: bool = False) -> float:
    """The bend radius to schedule [mm]: the standard's minimum or the code's, whichever is
    larger."""
    return max(standard_radius(dia), code_bend_diameter(dia, transverse) / 2)


def hook_extension(dia: float) -> float:
    """The straight extension [mm] of a link's 135° hook: the code's seismic hook
    (:func:`saengine.drawings.detailing.seismic_hook`; the default pack: 6 d, at least 75 mm)."""
    from saengine.drawings.detailing import seismic_hook as code_hook

    return float(code_hook(dia).tail)


def link_hook(dia: float, radius: float | None = None) -> float:
    """The dimension [mm] of the hooked free end of a link (the standard's ``linkHook`` in the
    code's extension ``ext``, ``r`` and ``d``; BS 8666: ext + r + d), rounded up to the
    standard's ``linkHookRound`` and not less than its end projection P."""
    std = standard()
    r = bend_radius(dia, True) if radius is None else radius
    value = round_up(
        evaluate(std.linkHook, {"ext": hook_extension(dia), "r": r, "d": dia}), std.linkHookRound
    )
    p = end_projection(dia)
    return value if p is None else max(value, p)


def seismic_hook(dia: float, radius: float | None = None) -> float:
    """The dimension [mm] of the free end of a link with a 135° seismic hook
    (:func:`link_hook`)."""
    return link_hook(dia, radius)


# ─────────────────────────────────── shape codes ───────────────────────────────────


@dataclass(frozen=True)
class Shape:
    """A shape code of the standard: its dimension letters and its cutting length."""

    code: str
    name: str
    letters: tuple[str, ...]
    formula: str
    expression: str
    transverse: bool = False
    bends: int = 0
    defaults: tuple[tuple[str, str], ...] = ()
    end_check: bool = False
    hook: str = ""
    radius_letter: str = ""
    counts: tuple[str, ...] = ()
    remarks: str = ""
    kind: str = "bent"
    sketch: Any = None

    def length(self, dims: Mapping[str, float], d: float, r: float) -> float:
        """The cutting length [mm], not rounded, of outside dimensions ``dims``."""
        std = standard()
        values: dict[str, float] = {"d": d, "r": r, "ext": hook_extension(d) if self.hook else 0}
        values.update({f"b{k}": v * d for k, v in std.deductions.items()})
        values.update(dims)
        for letter, default in self.defaults:
            if letter not in dims:
                values[letter] = evaluate(default, values)
        return evaluate(self.expression, values)


def _shape(code: str, spec: Any) -> Shape:
    return Shape(
        code=code,
        name=spec.name,
        letters=tuple(spec.letters),
        formula=spec.formula or f"L = {spec.length}",
        expression=spec.length,
        transverse=spec.transverse,
        bends=spec.bends,
        defaults=tuple(spec.defaults.items()),
        end_check=spec.endCheck,
        hook=spec.hook,
        radius_letter=spec.radius,
        counts=tuple(spec.counts),
        remarks=spec.remarks,
        kind=spec.kind,
        sketch=spec.sketch,
    )


def shapes() -> dict[str, Shape]:
    """The shape codes of the standard in force."""
    return {code: _shape(code, spec) for code, spec in standard().shapes.items()}


class _Shapes(Mapping[str, Shape]):
    """``SHAPES``: the shape codes of the standard in force, read when used."""

    def __getitem__(self, code: str) -> Shape:
        spec = standard().shapes.get(code)
        if spec is None:
            raise KeyError(code)
        return _shape(code, spec)

    def __iter__(self) -> Iterator[str]:
        return iter(standard().shapes)

    def __len__(self) -> int:
        return len(standard().shapes)


SHAPES: Mapping[str, Shape] = _Shapes()

TRANSVERSE_ROLES = ("stirrup", "tie", "link", "hoop", "spiral", "helix", "crosstie", "cross-tie")


def shape_code(shape: Any) -> str:
    """The standard's code for a code or a name (BS 8666: ``"51"``, ``51``, ``"stirrup"`` →
    ``"51"``)."""
    std = standard()
    text = str(shape if shape is not None else "").strip()
    if text in std.shapes:
        return text
    lower = text.lower()
    if lower.isdigit():
        padded = lower.zfill(2)
        if padded in std.shapes:
            return padded
    for code in std.shapes:
        if code.lower() == lower and lower:
            return code
    key = (lower or "straight").replace(" ", "").replace("_", "").replace("-", "")
    aliases = {k.lower(): v for k, v in std.aliases.items()}
    if key in aliases:
        return aliases[key]
    raise ValueError(f"unknown bar shape '{shape}'")


def cutting_length(code: str, dims: Mapping[str, float], dia: float, radius: float) -> float:
    """The cutting length of one bar [mm], not rounded, from the standard's shape ``code``."""
    shape = SHAPES[code]
    values = {k: float(v) for k, v in dims.items() if v is not None}
    missing = [k for k in shape.letters if k not in values]
    if missing or (shape.kind == "special" and "L" not in values):
        raise ValueError(f"shape {code} needs dimensions {', '.join(missing or ['L'])}")
    return shape.length(values, dia, radius)


def split_straight(run: float, lap: float, stock: float | None = None) -> list[float]:
    """Straight bars [mm] that cover ``run`` with a lap of ``lap`` at every joint, each no
    longer than ``stock`` (default: the standard's stock length): full stock bars and a last,
    shorter one."""
    stock = standard().stockLength if stock is None else stock
    if run <= stock:
        return [run]
    if lap >= stock:
        raise ValueError("the lap is longer than a stock bar")
    pieces = []
    remaining = run
    while remaining > stock:
        pieces.append(stock)
        remaining -= stock - lap
    pieces.append(remaining)
    return pieces


def size_label(dia: float) -> str:
    """A bar size as the standard prints it (BS 8666: ``"Ø16"``; ACI 315: ``"No. 16"``)."""
    return standard().sizeLabel.replace("{d}", f"{dia:g}")


# ─────────────────────────────────── the schedule ───────────────────────────────────


@dataclass
class BbsRow:
    element: str
    member: str
    kind: str
    story: str | None
    mark: str
    material: str
    dia: float
    shape: str
    dims: dict[str, float]
    radius: float
    members: int
    per_member: int
    cutting_length: float  # mm, rounded as the standard rounds (BS 8666: up to 25 mm)
    lap: float = 0.0  # mm of lap included in each bar
    role: str = ""
    zone: str = ""
    curtailed: bool = False
    remarks: str = ""
    cap: str = ""  # a pile's cap (the element the BOQ books its bars under)
    bim: tuple[str, ...] = ()  # the BIM ids the element spans (a beam line "B1+B2": B1, B2)
    shape_transverse: bool = False  # the standard's shape is a link, tie or helix
    size_format: str = "Ø{d}"  # the standard's bar size label
    counts: tuple[str, ...] = ()  # letters of the shape that are counts (a helix's turns)

    @property
    def total_count(self) -> int:
        return self.members * self.per_member

    @property
    def total_length(self) -> float:
        """Total length [m]."""
        return self.total_count * self.cutting_length / 1000

    @property
    def mass(self) -> float:
        """Mass [kg]."""
        return self.total_length * bar_mass(self.dia)

    @property
    def size(self) -> str:
        """Bar type and size, e.g. ``"B420DWR Ø16"`` (the standard's size label)."""
        return f"{self.material} {self.size_format.replace('{d}', f'{self.dia:g}')}".strip()

    @property
    def transverse(self) -> bool:
        return self.shape_transverse or any(r in self.role for r in TRANSVERSE_ROLES)


@dataclass
class BarSchedule:
    rows: list[BbsRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    standard: Any = None  # the standard it follows (barSchedule); None: the pack in force's
    shape_key: bool = False  # the sheets draw the sketches of its shape codes

    @property
    def std(self) -> Any:
        return self.standard if self.standard is not None else standard()

    @property
    def by_diameter(self) -> dict[float, float]:
        """Mass [kg] per bar diameter, smallest first."""
        out: dict[float, float] = {}
        for row in self.rows:
            out[row.dia] = out.get(row.dia, 0.0) + row.mass
        return dict(sorted(out.items()))

    @property
    def by_kind(self) -> dict[str, dict[float, float]]:
        """Mass [kg] per element kind and bar diameter."""
        out: dict[str, dict[float, float]] = {}
        for row in self.rows:
            kind = out.setdefault(row.kind, {})
            kind[row.dia] = kind.get(row.dia, 0.0) + row.mass
        return {k: dict(sorted(v.items())) for k, v in out.items()}

    @property
    def total(self) -> float:
        return sum(row.mass for row in self.rows)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        value = obj.get(key, default)
    else:
        value = getattr(obj, key, default)
    return default if value is None else value


_NUMBER = re.compile(r"^\s*(?:[ØøΦφTYHRK#]\s*)?([-+]?\d+(?:\.\d*)?|[-+]?\.\d+)\s*(?:mm)?\s*$")


def _num(value: Any, what: str) -> float:
    """``value`` as a number [mm]: a number or a text such as ``"12"``, ``"Ø12"``, ``"T12"`` or
    ``"12 mm"``; anything else raises ``ValueError`` (``TypeError`` for a boolean) naming
    ``what``."""
    if isinstance(value, bool):
        raise TypeError(f"{what} is not a number ({value!r})")
    if isinstance(value, int | float):
        number = float(value)
    else:
        match = _NUMBER.match(str(value)) if value is not None else None
        if match is None:
            raise ValueError(f"{what} is not a number ({value!r})")
        number = float(match.group(1))
    if not math.isfinite(number):
        raise ValueError(f"{what} is not a finite number ({value!r})")
    return number


def _flag(value: Any) -> bool:
    """A yes/no field: booleans, numbers, and texts such as ``"true"``, ``"yes"``, ``"1"``."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _dims(bar: Any, code: str) -> dict[str, float]:
    dims = _get(bar, "dims")
    if dims:
        return {
            str(k).upper(): _num(v, f"dimension {str(k).upper()}")
            for k, v in dict(dims).items()
            if v is not None
        }
    segments = _get(bar, "segments")
    if segments:
        lengths = []
        for i, s in enumerate(segments):
            letter = LETTERS[i] if i < len(LETTERS) else f"#{i + 1}"
            value = s if isinstance(s, int | float | str) else _get(s, "length")
            if value is None:
                raise ValueError(f"segment {letter} has no length")
            lengths.append(_num(value, f"segment {letter}"))
        return dict(zip(LETTERS, lengths, strict=False))
    return {}


def _row(element: Any, bar: Any, notes: list[str]) -> BbsRow | None:
    eid = str(_get(element, "id", ""))
    mark = str(_get(bar, "mark", ""))
    where = f"{eid} {mark}".strip()
    try:
        return _scheduled(element, bar, notes, eid, mark, where)
    except (ValueError, TypeError) as error:
        notes.append(f"{where}: {error}; not scheduled.")
        return None


def _scheduled(
    element: Any, bar: Any, notes: list[str], eid: str, mark: str, where: str
) -> BbsRow | None:
    dia = _num(_get(bar, "dia", 0), "the bar diameter")
    if dia <= 0:
        notes.append(f"{where}: no bar diameter; not scheduled.")
        return None
    std = standard()
    special = std.special
    try:
        code = shape_code(_get(bar, "shape"))
    except ValueError as error:
        notes.append(f"{where}: {error}; scheduled as shape {special}.")
        code = special
    role = str(_get(bar, "role", "")).lower()
    shape = SHAPES[code]
    transverse = shape.transverse or any(r in role for r in TRANSVERSE_ROLES)
    radius = bend_radius(dia, transverse)
    bend_dia = _get(bar, "bendDia", _get(bar, "bend_dia"))
    if bend_dia is not None:  # the detailing model's least inside bend diameter (the code's)
        radius = max(radius, _num(bend_dia, "the bend diameter") / 2)
    if _get(bar, "radius") is not None:
        radius = _num(_get(bar, "radius"), "the bend radius")
    dims = _dims(bar, code)
    big = shape.radius_letter
    if big and big in dims and dims[big] < radius - 1e-6:
        notes.append(
            f"{where}: {big} = {dims[big]:g} mm is below the minimum bend radius {radius:g} mm; "
            "scheduled with the minimum."
        )
    hook = shape.hook
    if hook and hook not in dims and set(shape.letters) - {hook} <= dims.keys():
        dims[hook] = link_hook(dia, radius)
    given = _get(bar, "length")
    if not dims and given is None:
        notes.append(f"{where}: neither dimensions nor a length; not scheduled.")
        return None
    if not dims or shape.kind == "special":
        if shape.kind == "bent":
            notes.append(f"{where}: shape {code} without dimensions; scheduled as shape {special}.")
            code = special
        if given is not None:
            length = _num(given, "the length")
        elif "L" in dims:
            length = dims["L"]
        else:
            notes.append(f"{where}: shape {special} without a length; not scheduled.")
            return None
        if shape.kind == "straight" and not dims:
            dims = {(shape.letters or "A")[0]: length}
    else:
        try:
            length = cutting_length(code, dims, dia, radius)
        except ValueError as error:
            if given is None:
                notes.append(f"{where}: {error}; not scheduled.")
                return None
            notes.append(
                f"{where}: {error}; scheduled with the detailed length as shape {special}."
            )
            code, length = special, _num(given, "the length")
    shape = SHAPES[code]
    p = end_projection(dia)
    ends = shape.letters
    if p is not None and shape.end_check and ends and min(dims[ends[0]], dims[ends[-1]]) < p:
        notes.append(f"{where}: an end is shorter than the minimum end projection P = {p:g} mm.")
    stock = std.stockLength
    if length > stock + 1e-6:
        notes.append(f"{where}: {length:.0f} mm is longer than a {stock:.0f} mm stock bar.")
    lap = _num(_get(bar, "lap", 0.0), "the lap")
    zone = str(_get(bar, "zone", ""))
    curtailed = _flag(_get(bar, "curtailed", False))
    members = int(_num(_get(bar, "members", _get(element, "count", 1)), "the number of members"))
    per_member = int(_num(_get(bar, "count", 1), "the number of bars"))
    remarks = [str(_get(bar, "remarks", ""))]
    if shape.remarks:
        remarks.append(shape.remarks)
    if zone:
        remarks.append(f"zone {zone}")
    if lap:
        remarks.append(f"lap {lap:.0f}")
    if curtailed:
        remarks.append("cut-off")
    # Dimensions print in whole mm, except the counts (a helix's number of turns).
    shown = {k: round(v, 2) if k in shape.counts else round(v) for k, v in dims.items()}
    return BbsRow(
        element=eid,
        member=str(_get(element, "member", eid)),
        kind=str(_get(element, "kind", "")),
        story=_get(element, "story"),
        mark=mark,
        material=str(_get(bar, "material", _get(bar, "grade", ""))),
        dia=dia,
        shape=code,
        dims=shown,
        radius=radius,
        members=members,
        per_member=per_member,
        cutting_length=round_length(length),
        lap=lap,
        role=role,
        zone=zone,
        curtailed=curtailed,
        remarks=", ".join(r for r in remarks if r),
        cap=str(_get(element, "cap", "")),
        bim=_bim_ids(element),
        shape_transverse=shape.transverse,
        size_format=std.sizeLabel,
        counts=shape.counts,
    )


def _bim_ids(element: Any) -> tuple[str, ...]:
    """The BIM ids an element spans: the detailing model's ``members`` when it is a list (a
    beam line over several BIM beams), else none."""
    members = _get(element, "members")
    if isinstance(members, list | tuple):
        return tuple(str(m) for m in members if m is not None)
    return ()


def bar_schedule(detailing: Any) -> BarSchedule:
    """The bar bending schedule of a detailing model (see the module notes for its shape)."""
    schedule = BarSchedule()
    elements: Iterable[Any] = _get(detailing, "elements", [])
    for element in elements:
        for bar in _get(element, "bars", []):
            row = _row(element, bar, schedule.notes)
            if row is not None and row.total_count > 0:
                schedule.rows.append(row)
    std, why = standard_of(_table())
    schedule.standard, schedule.shape_key = std, shape_key_on()
    if why:
        schedule.notes.append(why)
    unit, _ = length_display()
    schedule.notes.append(
        std.note.replace("{name}", std.name)
        .replace("{bend}", _bend_reference())
        .replace("{round}", f"{std.roundTo:g}")
        .replace("{unit}", unit)
    )
    return schedule


# ─────────────────────────────────── tables and CSV ───────────────────────────────────

#: The cells a standard's columns may show (``barSchedule`` ``columns[].key``).
CELL_KEYS = ("member", "mark", "size", "shape", *LETTERS, "members", "per_member",
             "total_count", "cutting_length", "total_length", "mass", "remarks")  # fmt: skip
NUMERIC = {"A", "B", "C", "D", "E", "members", "per_member", "total_count",
           "cutting_length", "total_length", "mass"}  # fmt: skip


def columns_of(std: Any) -> tuple[tuple[str, str], ...]:
    """The standard's columns as (key, title), the title's ``{len}`` the length unit
    (:func:`length_display`); keys the schedule has no cell for are left out."""
    unit, _ = length_display()
    return tuple((c.key, c.title.replace("{len}", unit)) for c in std.columns if c.key in CELL_KEYS)


def _cells(row: BbsRow) -> dict[str, str]:
    _, fmt = length_display()

    def dim(k: str) -> str:
        v = row.dims.get(k, row.dims.get("R") if k == "E" else None)
        if v is None:
            return ""
        return f"{v:g}" if k in row.counts else fmt(v)

    return {
        "member": row.member,
        "mark": row.mark,
        "size": row.size,
        "shape": row.shape,
        **{k: dim(k) for k in LETTERS},
        "members": str(row.members),
        "per_member": str(row.per_member),
        "total_count": str(row.total_count),
        "cutting_length": fmt(row.cutting_length),
        "total_length": f"{row.total_length:.2f}",
        "mass": f"{row.mass:.2f}",
        "remarks": row.remarks,
    }


def _kind_label(kind: str) -> str:
    return kind.replace("_", " ").capitalize() + "s" if kind else "Other"


def schedule_csv(schedule: BarSchedule) -> str:
    """The schedule as CSV for Excel: one row per bar mark, then the totals per bar size and per
    element type. Write it with ``encoding="utf-8-sig"`` (Excel reads the Ø then) and
    ``newline=""``."""
    std = schedule.std
    columns = columns_of(std)
    keys = [key for key, _ in columns]
    label = std.sizeLabel

    def line(first: str, **cells: str) -> list[str]:
        """A totals line: ``first`` in the first column, each cell under its column (the size
        under the size column, ...), up to the last cell given."""
        out = [first]
        at = {keys.index(k): v for k, v in cells.items() if k in keys}
        for i in range(1, max(at, default=0) + 1):
            out.append(at.get(i, ""))
        return out

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([title.replace("\n", " ") for _, title in columns])
    for row in schedule.rows:
        cells = _cells(row)
        writer.writerow([cells[key] for key in keys])
    writer.writerow([])
    writer.writerow(
        line("Totals per bar size", size="Size", total_length="Total length (m)", mass="Mass (kg)")
    )
    for dia, mass in schedule.by_diameter.items():
        length = sum(r.total_length for r in schedule.rows if r.dia == dia)
        size = label.replace("{d}", f"{dia:g}")
        writer.writerow(line("", size=size, total_length=f"{length:.2f}", mass=f"{mass:.2f}"))
    writer.writerow(line("Total", mass=f"{schedule.total:.2f}"))
    writer.writerow([])
    writer.writerow(line("Totals per element type", size="Size", mass="Mass (kg)"))
    for kind, sizes in schedule.by_kind.items():
        for dia, mass in sizes.items():
            size = label.replace("{d}", f"{dia:g}")
            writer.writerow(line(_kind_label(kind), size=size, mass=f"{mass:.2f}"))
        writer.writerow(line(f"{_kind_label(kind)} total", mass=f"{sum(sizes.values()):.2f}"))
    return out.getvalue()


def _widths(columns: list[dict[str, Any]], rows: list[list[str]]) -> None:
    """Set each column's ``width`` [characters] from its title and cells, not more than its
    ``max``, and wrap the cells that are longer onto lines split by ``"\\n"``, so that no line
    of a cell is longer than ``width - 1`` (one character is the gap to the next column)."""
    for i, column in enumerate(columns):
        title = max(len(line) for line in column["title"].split("\n"))
        cells = max((len(line) for r in rows for line in r[i].split("\n")), default=0)
        width = max(min(max(cells, 3) + 1, column.get("max", 40)), title + 1)
        column["width"] = width
        for r in rows:
            if any(len(line) > width - 1 for line in r[i].split("\n")):
                r[i] = "\n".join(
                    "\n".join(textwrap.wrap(line, width - 1, break_on_hyphens=False) or [""])
                    for line in r[i].split("\n")
                )


def sheet_table(schedule: BarSchedule) -> dict[str, Any]:
    """The schedule as table data for the BBS drawing sheets.

    Returns ``{"title", "columns", "rows", "groups", "totals", "notes"}``: ``columns`` are
    ``{"key", "title" (lines split by "\\n"), "width" (characters), "align" ("left"/"right")}``;
    ``rows`` are lists of cell strings in column order (the member printed on the first row of
    each member only); a cell longer than its column is already wrapped onto lines split by
    ``"\\n"``, none longer than ``width - 1``, so a row is as many text lines high as its tallest
    cell (a renderer must not draw a cell on one line); ``groups`` are ``{"member", "first", "count"}`` row ranges (a sheet break
    should not split one); ``totals`` is another table ``{"columns", "rows"}`` of the masses per
    bar size and element type, with a grand total row last.
    """
    std = schedule.std
    layout = columns_of(std)
    columns: list[dict[str, Any]] = [
        {"key": k, "title": t, "align": "right" if k in NUMERIC else "left",
         "max": 28 if k in ("member", "remarks") else 14}
        for k, t in layout
    ]  # fmt: skip
    rows: list[list[str]] = []
    groups: list[dict[str, Any]] = []
    previous = None
    for row in schedule.rows:
        cells = _cells(row)
        key = (row.element, row.member)
        if key != previous:
            groups.append({"member": row.member, "first": len(rows), "count": 0})
            previous = key
        else:
            cells["member"] = ""
        groups[-1]["count"] += 1
        rows.append([cells[k] for k, _ in layout])
    _widths(columns, rows)
    for column in columns:
        column.pop("max")

    sizes = list(schedule.by_diameter)
    total_cols: list[dict[str, Any]] = [{"key": "kind", "title": "Element\ntype", "align": "left"}]
    label = std.sizeLabel
    total_cols += [
        {"key": f"d{d:g}", "title": f"{label.replace('{d}', f'{d:g}')}\n(kg)", "align": "right"}
        for d in sizes
    ]
    total_cols.append({"key": "total", "title": "Total\n(kg)", "align": "right"})
    total_rows = []
    for kind, masses in schedule.by_kind.items():
        total_rows.append(
            [_kind_label(kind), *[f"{masses.get(d, 0.0):.1f}" if d in masses else "" for d in sizes],
             f"{sum(masses.values()):.1f}"]
        )  # fmt: skip
    by_dia = schedule.by_diameter
    total_rows.append(["Total", *[f"{by_dia[d]:.1f}" for d in sizes], f"{schedule.total:.1f}"])
    _widths(total_cols, total_rows)
    lengths: dict[str, float] = {}
    for r in schedule.rows:
        if r.mark:
            lengths.setdefault(r.mark, r.cutting_length)
    table: dict[str, Any] = {
        "title": std.title,
        "columns": columns,
        "rows": rows,
        "groups": groups,
        "totals": {"columns": total_cols, "rows": total_rows},
        "notes": list(schedule.notes),
        # the cutting length of each mark in mm, whatever unit the cells show
        "cuttingLengths": lengths,
    }
    if schedule.shape_key:
        table["shapeKey"] = shape_key(schedule)
    return table


def shape_key(schedule: BarSchedule) -> list[dict[str, Any]]:
    """The shape codes the schedule uses, in the standard's order, for the sheets' shape key:
    ``{"code", "name", "formula", "letters", "sketch"}`` (``sketch``: ``{"paths", "labels"}``
    or None when the standard draws none)."""
    std = schedule.std
    used = {row.shape for row in schedule.rows}
    out = []
    for code, spec in std.shapes.items():
        if code not in used:
            continue
        sketch = spec.sketch
        out.append(
            {
                "code": code,
                "name": spec.name,
                "formula": spec.formula or f"L = {spec.length}",
                "letters": spec.letters,
                "sketch": None
                if sketch is None
                else {
                    "paths": [[list(p) for p in path] for path in sketch.paths],
                    "labels": {k: list(v) for k, v in sketch.labels.items()},
                },
            }
        )
    return out


# ─────────────────────────────────── BOQ reconciliation ───────────────────────────────────


MESH_KINDS = ("slab", "wall", "stair", "staircase", "footing", "pile cap", "pile_cap", "pilecap")
# Bars of a mesh element that the BOQ books as longitudinal bars: wall end (boundary) bars.
LONGITUDINAL_ROLES = ("longitudinal", "end", "boundary bar", "lintel")


def _category(transverse: bool, role: str, kind: str) -> str:
    """The schedule side's category, in the same split as the BOQ's (``_boq_category``)."""
    if transverse:
        return "transverse"
    if kind.lower() == "pile":  # the BOQ books pile bars as "pile bars" (longitudinal)
        return "longitudinal"
    if kind.lower() == "wall" and any(role.startswith(r) for r in LONGITUDINAL_ROLES):
        return "longitudinal"  # BOQ: "end bars"
    if "mesh" in role or kind.lower() in MESH_KINDS:
        return "mesh"
    return "longitudinal"


def _boq_category(detail: str | None) -> str:
    """The category of a BOQ breakdown entry by its ``detail`` (boq/quantities.py ``rebar``):
    "longitudinal", "pile bars" and "end bars" (wall boundaries) are longitudinal bars;
    stirrups, ties, hoops, spirals and "pile ties" are transverse; the rest are meshes."""
    text = (detail or "").lower().strip()
    if any(r in text for r in TRANSVERSE_ROLES) or "hoops" in text:
        return "transverse"
    if not text or text.startswith(("longitudinal", "pile bars", "end bars")):
        return "longitudinal"
    return "mesh"


def _boq_element(row: BbsRow) -> str:
    """The element id the BOQ books a row's bars under: a pile's under its cap (``cap``)."""
    return row.cap if row.kind.lower() == "pile" and row.cap else row.element


@dataclass
class ReconciliationRow:
    dia: float
    bbs: float  # kg
    boq: float  # kg
    categories: dict[str, tuple[float, float]]  # category -> (bbs kg, boq kg)
    laps: float  # kg of laps in the BBS
    cutoffs: int  # cut-off (curtailed) bar marks in the BBS
    only_bbs: dict[str, float]  # element -> kg detailed but not in the BOQ
    only_boq: dict[str, float]  # element -> kg in the BOQ but not detailed
    reasons: list[str]

    @property
    def difference(self) -> float:
        """BBS minus BOQ [kg]."""
        return self.bbs - self.boq

    @property
    def percent(self) -> float | None:
        return None if self.boq == 0 else 100 * self.difference / self.boq


@dataclass
class Reconciliation:
    rows: list[ReconciliationRow]
    notes: list[str]
    size_format: str = "Ø{d}"  # the schedule standard's bar size label

    @property
    def bbs(self) -> float:
        return sum(r.bbs for r in self.rows)

    @property
    def boq(self) -> float:
        return sum(r.boq for r in self.rows)


def _boq_items(boq: Any) -> list[Any]:
    items = _get(boq, "items", [])
    return [i for i in items if _get(i, "group") == "reinforcement"]


def reconcile(schedule: BarSchedule, boq: Any, tolerance: float = 0.5) -> Reconciliation:
    """The schedule's reinforcement against the bill of quantities' (``boq``: a
    ``BillOfQuantities`` or the ``boq.json`` dict), per bar diameter, with the reasons for each
    difference larger than ``tolerance`` kg: bars per category (longitudinal, links and ties,
    meshes: hooks and bend deductions show in the links, laps and cut-offs in the bars), the
    laps and cut-off bars of the schedule, and elements on one side only."""
    bbs: dict[float, dict[str, float]] = {}
    bbs_el: dict[float, dict[str, float]] = {}
    laps: dict[float, float] = {}
    cutoffs: dict[float, int] = {}
    for r in schedule.rows:
        cat = _category(r.transverse, r.role, r.kind)
        side = bbs.setdefault(r.dia, {})
        side[cat] = side.get(cat, 0.0) + r.mass
        el = bbs_el.setdefault(r.dia, {})
        name = _boq_element(r)
        el[name] = el.get(name, 0.0) + r.mass
        laps[r.dia] = laps.get(r.dia, 0.0) + r.total_count * r.lap / 1000 * bar_mass(r.dia)
        cutoffs[r.dia] = cutoffs.get(r.dia, 0) + (1 if r.curtailed else 0)

    boq_cat: dict[float, dict[str, float]] = {}
    boq_el: dict[float, dict[str, float]] = {}
    # The BOQ books a beam line's bars under each BIM beam: count them under the line's id.
    alias = {m: _boq_element(r) for r in schedule.rows for m in r.bim}
    for item in _boq_items(boq):
        dia = float(_get(item, "diameter", 0) or 0)
        breakdown = _get(item, "breakdown", [])
        if not breakdown:
            breakdown = [{"element": "", "detail": None, "quantity": _get(item, "quantity", 0)}]
        for entry in breakdown:
            q = float(_get(entry, "quantity", 0))
            cat = _boq_category(_get(entry, "detail"))
            side = boq_cat.setdefault(dia, {})
            side[cat] = side.get(cat, 0.0) + q
            el = boq_el.setdefault(dia, {})
            name = str(_get(entry, "element", ""))
            name = alias.get(name, name)
            el[name] = el.get(name, 0.0) + q

    names = {"longitudinal": "Longitudinal bars", "transverse": "Links and ties",
             "mesh": "Meshes"}  # fmt: skip
    std = schedule.std
    rows = []
    for dia in sorted(set(bbs) | set(boq_cat)):
        a, b = bbs.get(dia, {}), boq_cat.get(dia, {})
        cats = {c: (a.get(c, 0.0), b.get(c, 0.0)) for c in names if c in a or c in b}
        ea, eb = bbs_el.get(dia, {}), boq_el.get(dia, {})
        only_bbs = {e: m for e, m in ea.items() if e not in eb}
        only_boq = {e: m for e, m in eb.items() if e not in ea}
        reasons = []
        for cat, (x, y) in cats.items():
            if abs(x - y) <= tolerance:
                continue
            why = {
                "transverse": f"hooks to {std.name} / the code's 135° seismic hooks and bend "
                "deductions (BOQ: centre line + 2 × 10 d), and link counts by zone (BOQ: length "
                "/ spacing + 1 at one spacing)",
                "longitudinal": "laps at the detailed splice positions with the code's lap lengths "
                "(BOQ: 40 d per 12 m stock bar), anchorage bends and cut-off bars (BOQ: every "
                "bar the member's full length)",
                "mesh": "bars counted per panel with end anchorage and laps (BOQ: area / "
                "spacing with 40 d laps)",
            }[cat]
            reasons.append(f"{names[cat]}: {x - y:+.1f} kg — {why}.")
        if reasons and abs(sum(a.values()) - sum(b.values())) <= tolerance:
            reasons.append(
                "The totals agree: the bars are booked under different categories on the two "
                "sides (the per-category differences cancel)."
            )
        if laps.get(dia, 0.0) > 0:
            reasons.append(f"Laps in the schedule: {laps[dia]:.1f} kg.")
        if cutoffs.get(dia, 0):
            reasons.append(f"Cut-off bars in the schedule: {cutoffs[dia]} bar marks.")
        if only_bbs:
            reasons.append(
                f"Detailed but not in the BOQ: {', '.join(sorted(only_bbs))} "
                f"({sum(only_bbs.values()):.1f} kg)."
            )
        if only_boq:
            reasons.append(
                f"In the BOQ but not detailed: {', '.join(sorted(e or '?' for e in only_boq))} "
                f"({sum(only_boq.values()):.1f} kg)."
            )
        rows.append(
            ReconciliationRow(
                dia=dia,
                bbs=sum(a.values()),
                boq=sum(b.values()),
                categories=cats,
                laps=laps.get(dia, 0.0),
                cutoffs=cutoffs.get(dia, 0),
                only_bbs=only_bbs,
                only_boq=only_boq,
                reasons=reasons,
            )
        )
    notes = [
        (
            "The BOQ takes the bars of this schedule for every element the drawings detail (10 BOQ "
            "notes); a difference is the elements it measures by its estimating rules "
            "(longitudinal bars over the member's full length with a 40 d lap per 12 m stock bar, "
            "links at their centre line with two 10 d hooks, meshes as area / spacing), or a bill "
            "measured from other files than these drawings."
        ),
    ]
    return Reconciliation(rows, notes, std.sizeLabel)


def reconciliation_table(rec: Reconciliation) -> dict[str, Any]:
    """The reconciliation as table data (``{"columns", "rows"}`` as ``sheet_table``; the reasons
    are wrapped onto lines split by ``"\\n"`` to the column's width)."""
    columns: list[dict[str, Any]] = [
        {"key": "dia", "title": "Bar\nsize", "align": "left"},
        {"key": "bbs", "title": "BBS\n(kg)", "align": "right"},
        {"key": "boq", "title": "BOQ\n(kg)", "align": "right"},
        {"key": "difference", "title": "Difference\n(kg)", "align": "right"},
        {"key": "percent", "title": "Difference\n(%)", "align": "right"},
        {"key": "reasons", "title": "Why", "align": "left", "max": 80},
    ]
    rows = []
    for r in rec.rows:
        pct = "" if r.percent is None else f"{r.percent:+.1f}"
        rows.append(
            [rec.size_format.replace("{d}", f"{r.dia:g}"), f"{r.bbs:.1f}", f"{r.boq:.1f}",
             f"{r.difference:+.1f}", pct, "\n".join(r.reasons)]
        )  # fmt: skip
    diff = rec.bbs - rec.boq
    pct = "" if rec.boq == 0 else f"{100 * diff / rec.boq:+.1f}"
    rows.append(["Total", f"{rec.bbs:.1f}", f"{rec.boq:.1f}", f"{diff:+.1f}", pct, ""])
    for column in columns:
        column.setdefault("max", 14)
    _widths(columns, rows)
    for column in columns:
        column.pop("max")
    return {"title": "Reinforcement: schedule and bill of quantities", "columns": columns,
            "rows": rows, "notes": list(rec.notes)}  # fmt: skip
