"""Bar bending schedules (BBS) from the reinforcement detailing model (11 Exports, drawings).

A schedule lists every bar mark of the detailed members the way a fabricator cuts and bends it:
member, mark, bar type and size, BS 8666 shape code, the dimensions A to E, the number of
members by the bars in each, the cutting length, the total length and the mass, with remarks
(zone, lap). Totals are given per bar size and per element type, and the schedule can be set
against the bill of quantities (10 BOQ), which measures bars with its own conventions.

Conventions (units: mm for lengths and dimensions, m for total lengths, kg for masses):

- shape codes and cutting-length formulas follow BS 8666 (the common set for RC buildings, see
  ``SHAPES``); the dimensions are outside dimensions, as BS 8666 schedules them, and the
  cutting length ``L`` deducts the bends with the bend radius ``r``;
- the bend radius is the larger of BS 8666's minimum scheduling radius (``BS8666_RADIUS``) and
  half BNBC 2020's minimum inside bend diameter (Part 6, 8.1.2.2 and Table 6.8.1, PDF pp.
  1065-1066: 6 d for 10-25 mm bars, 8 d over 25 to 40 mm, 10 d over 40 mm; 4 d for stirrups and
  ties of 16 mm and smaller);
- the default hook of a link (shape 51 and 63 ends) is a 135° seismic hook with an extension of
  6 d but not less than 75 mm (BNBC 2020 Part 6, 8.1.2.1 (c)(iv) and (d), PDF p. 1066), and no
  straight end is shorter than BS 8666's minimum end projection ``P``;
- cutting lengths are rounded up to the next 25 mm; bar mass is ``d² / 162`` kg/m (7850 kg/m³).

The BS 8666 radii, end projections and formulas in this module were written from memory and are
to be checked against BS 8666:2020 before the schedules are issued for fabrication.

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
default 1) and ``bars``. Each bar has ``mark``, ``dia`` [mm], ``shape`` (a BS 8666 code such as
``"51"`` or a name: straight, L, U, link, stirrup, tie, hook, ...), ``count`` (bars per member),
and either ``dims`` (``{"A": ..., "B": ...}``, outside dimensions) or ``segments`` (outside
lengths in the order A, B, C, ...; numbers or ``{"length": ...}``) or only ``length`` (the
cutting length, scheduled as given). Optional: ``material`` or ``grade`` (``"B420DWR"``),
``radius`` [mm] (overrides the bend radius), ``bendDia`` [mm] (the detailing model's least
inside bend diameter: the radius is at least half of it), ``role`` (longitudinal, top, bottom,
stirrup, tie, mesh, ...), ``zone``, ``lap`` [mm] (lap length included in each bar),
``curtailed`` (true for a cut-off bar; "true"/"yes"/"1" texts too), ``members`` (overrides the
element's count), ``remarks``. Shape 12 takes an optional ``R`` (its large bend radius) in
``dims``; shape 77's ``C`` is its number of turns. A pile element (kind ``pile``) may name its
``cap``: the BOQ books pile bars under the cap's id. Numbers may be texts such as ``"12"`` or
``"Ø12"``; a bar with a value that is not a number is not scheduled and gets a note (no bar's
problem raises). This is :mod:`saengine.drawings.detailing`'s ``detailing_model`` output (kinds
beam, column, slab, wall, staircase, footing, pileCap).
"""

from __future__ import annotations

import csv
import io
import math
import re
import textwrap
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

ROUND_TO = 25.0  # mm: cutting lengths are rounded up to this
STOCK_LENGTH = 12_000.0  # mm: the longest bar delivered
LETTERS = ("A", "B", "C", "D", "E")

# BS 8666 minimum scheduling radius r [mm] and minimum end projection P [mm] by bar size, grade
# B500 (from memory, to be checked against BS 8666:2020 Table 2).
BS8666_RADIUS = {6: 12, 8: 16, 10: 20, 12: 24, 16: 32, 20: 70, 25: 87, 32: 112, 40: 140, 50: 175}
BS8666_END = {
    6: 110,
    8: 115,
    10: 130,
    12: 160,
    16: 210,
    20: 290,
    25: 365,
    32: 465,
    40: 585,
    50: 725,
}


def bar_mass(dia: float) -> float:
    """Mass of a bar [kg/m] of diameter ``dia`` [mm] (7850 kg/m³)."""
    return dia * dia / 162


def round_up(length: float, step: float = ROUND_TO) -> float:
    """``length`` rounded up to the next ``step`` (a millimetre of float noise is ignored)."""
    return math.ceil(length / step - 1e-6) * step


def bs8666_radius(dia: float) -> float:
    """BS 8666 minimum scheduling radius [mm]: the table, else 2 d up to 16 mm and 3.5 d above."""
    if dia in BS8666_RADIUS:
        return float(BS8666_RADIUS[int(dia)])
    return 2.0 * dia if dia <= 16 else math.ceil(3.5 * dia)


def end_projection(dia: float) -> float:
    """BS 8666 minimum end projection P [mm]: the table, else r + 11 d rounded up to 5 mm."""
    if dia in BS8666_END:
        return float(BS8666_END[int(dia)])
    return round_up(bs8666_radius(dia) + 11 * dia, 5)


def bnbc_bend_diameter(dia: float, transverse: bool = False) -> float:
    """BNBC 2020 minimum inside bend diameter [mm] (Part 6, 8.1.2.2, Table 6.8.1)."""
    if transverse and dia <= 16:
        return 4.0 * dia
    if dia <= 25:
        return 6.0 * dia
    if dia <= 40:
        return 8.0 * dia
    return 10.0 * dia


def bend_radius(dia: float, transverse: bool = False) -> float:
    """The bend radius to schedule [mm]: BS 8666's minimum or BNBC's, whichever is larger."""
    return max(bs8666_radius(dia), bnbc_bend_diameter(dia, transverse) / 2)


def seismic_hook(dia: float, radius: float | None = None) -> float:
    """Outside dimension [mm] of the free end of a link with a 135° seismic hook: the 6 d (not
    less than 75 mm) extension plus the bend (r + d), but not less than P; rounded up to 5 mm."""
    r = bend_radius(dia, True) if radius is None else radius
    return max(round_up(max(6 * dia, 75.0) + r + dia, 5), end_projection(dia))


# ─────────────────────────────────── shape codes ───────────────────────────────────


@dataclass(frozen=True)
class Shape:
    """A BS 8666 shape code: its dimension letters and its cutting length ``L(dims, d, r)``."""

    code: str
    name: str
    letters: tuple[str, ...]
    formula: str
    length: Callable[[dict[str, float], float, float], float]
    transverse: bool = False
    bends: int = 0


def _s(code, name, letters, formula, length, transverse=False, bends=0) -> tuple[str, Shape]:
    return code, Shape(code, name, tuple(letters), formula, length, transverse, bends)


# Formulas from memory (BS 8666), to be checked against BS 8666:2020 Table 3.
SHAPES: dict[str, Shape] = dict(
    [
        _s("00", "straight", "A", "L = A", lambda m, d, r: m["A"]),
        _s("01", "straight (stock length)", "A", "L = A", lambda m, d, r: m["A"]),
        _s(
            "11",
            "L bar (one 90° bend)",
            "AB",
            "L = A + B - 0.5r - d",
            lambda m, d, r: m["A"] + m["B"] - 0.5 * r - d,
            bends=1,
        ),
        _s(
            "12",
            "L bar (one radius bend)",
            "AB",
            "L = A + B - 0.43R - 1.2d (R: the scheduled radius, else r)",
            lambda m, d, r: m["A"] + m["B"] - 0.43 * max(m.get("R", r), r) - 1.2 * d,
            bends=1,
        ),
        _s(
            "13",
            "U bar (180° bend)",
            "ABC",
            "L = A + 0.57B + C - 1.6d",
            lambda m, d, r: m["A"] + 0.57 * m["B"] + m["C"] - 1.6 * d,
            bends=1,
        ),
        _s("15", "cranked end", "ABC", "L = A + C", lambda m, d, r: m["A"] + m["C"], bends=2),
        _s(
            "21",
            "U bar (two 90° bends)",
            "ABC",
            "L = A + B + C - r - 2d",
            lambda m, d, r: m["A"] + m["B"] + m["C"] - r - 2 * d,
            bends=2,
        ),
        _s(
            "22",
            "U bar with a return",
            "ABCD",
            "L = A + B + C + D - 1.5r - 3d",
            lambda m, d, r: m["A"] + m["B"] + m["C"] + m["D"] - 1.5 * r - 3 * d,
            bends=3,
        ),
        _s(
            "23",
            "Z bar (two 90° bends)",
            "ABC",
            "L = A + B + C - r - 2d",
            lambda m, d, r: m["A"] + m["B"] + m["C"] - r - 2 * d,
            bends=2,
        ),
        _s(
            "26",
            "cranked bar",
            "ABC",
            "L = A + B + C",
            lambda m, d, r: m["A"] + m["B"] + m["C"],
            bends=2,
        ),
        _s(
            "31",
            "three 90° bends",
            "ABCD",
            "L = A + B + C + D - 1.5r - 3d",
            lambda m, d, r: m["A"] + m["B"] + m["C"] + m["D"] - 1.5 * r - 3 * d,
            bends=3,
        ),
        _s(
            "33",
            "U bar with 180° hooks",
            "ABC",
            "L = 2A + 1.7B + 2(C - 4d)",
            lambda m, d, r: 2 * m["A"] + 1.7 * m["B"] + 2 * (m["C"] - 4 * d),
            bends=4,
        ),
        _s(
            "41",
            "four 90° bends",
            "ABCDE",
            "L = A + B + C + D + E - 2r - 4d",
            lambda m, d, r: m["A"] + m["B"] + m["C"] + m["D"] + m["E"] - 2 * r - 4 * d,
            bends=4,
        ),
        _s(
            "51",
            "closed link",
            "ABC",
            "L = 2(A + B + C) - 2.5r - 5d",
            lambda m, d, r: 2 * (m["A"] + m["B"] + m["C"]) - 2.5 * r - 5 * d,
            True,
            5,
        ),
        _s(
            "63",
            "closed link, overlapping legs",
            "ABC",
            "L = 2A + 3B + 2C - 3r - 6d",
            lambda m, d, r: 2 * m["A"] + 3 * m["B"] + 2 * m["C"] - 3 * r - 6 * d,
            True,
            6,
        ),
        _s(
            "77",
            "helix",
            "ABC",
            "L = C·π(A - d)",
            lambda m, d, r: m["C"] * math.pi * (m["A"] - d),
            True,
        ),
        _s("99", "special (as sketched)", "", "L as detailed", lambda m, d, r: m["L"]),
    ]
)

# Shape names the detailing model may use instead of a code.
ALIASES = {
    "straight": "00", "bar": "00", "l": "11", "lbar": "11", "u": "21", "ubar": "21",
    "z": "23", "crank": "26", "cranked": "26", "hook": "33", "hooked": "33",
    "link": "51", "stirrup": "51", "tie": "51", "hoop": "51", "closedlink": "51",
    "helix": "77", "spiral": "77", "special": "99",
}  # fmt: skip

TRANSVERSE_ROLES = ("stirrup", "tie", "link", "hoop", "spiral", "helix", "crosstie", "cross-tie")


def shape_code(shape: Any) -> str:
    """The BS 8666 code for a code or a name (``"51"``, ``51``, ``"stirrup"`` → ``"51"``)."""
    text = str(shape if shape is not None else "00").strip().lower()
    if text.isdigit():
        text = text.zfill(2)
        if text in SHAPES:
            return text
    key = text.replace(" ", "").replace("_", "").replace("-", "")
    if key in ALIASES:
        return ALIASES[key]
    raise ValueError(f"unknown bar shape '{shape}'")


def cutting_length(code: str, dims: Mapping[str, float], dia: float, radius: float) -> float:
    """The cutting length of one bar [mm], not rounded, from BS 8666 shape ``code``."""
    shape = SHAPES[code]
    values = {k: float(v) for k, v in dims.items() if v is not None}
    missing = [k for k in shape.letters if k not in values]
    if missing or (code == "99" and "L" not in values):
        raise ValueError(f"shape {code} needs dimensions {', '.join(missing or ['L'])}")
    return shape.length(values, dia, radius)


def split_straight(run: float, lap: float, stock: float = STOCK_LENGTH) -> list[float]:
    """Straight bars [mm] that cover ``run`` with a lap of ``lap`` at every joint, each no
    longer than ``stock``: full stock bars and a last, shorter one."""
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
    cutting_length: float  # mm, rounded up to 25 mm
    lap: float = 0.0  # mm of lap included in each bar
    role: str = ""
    zone: str = ""
    curtailed: bool = False
    remarks: str = ""
    cap: str = ""  # a pile's cap (the element the BOQ books its bars under)
    bim: tuple[str, ...] = ()  # the BIM ids the element spans (a beam line "B1+B2": B1, B2)

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
        """Bar type and size, e.g. ``"B420DWR Ø16"``."""
        return f"{self.material} Ø{self.dia:g}".strip()

    @property
    def transverse(self) -> bool:
        return SHAPES[self.shape].transverse or any(r in self.role for r in TRANSVERSE_ROLES)


@dataclass
class BarSchedule:
    rows: list[BbsRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

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
    try:
        code = shape_code(_get(bar, "shape"))
    except ValueError as error:
        notes.append(f"{where}: {error}; scheduled as shape 99.")
        code = "99"
    role = str(_get(bar, "role", "")).lower()
    shape = SHAPES[code]
    transverse = shape.transverse or any(r in role for r in TRANSVERSE_ROLES)
    radius = bend_radius(dia, transverse)
    bend_dia = _get(bar, "bendDia", _get(bar, "bend_dia"))
    if bend_dia is not None:  # the detailing model's least inside bend diameter (BNBC)
        radius = max(radius, _num(bend_dia, "the bend diameter") / 2)
    if _get(bar, "radius") is not None:
        radius = _num(_get(bar, "radius"), "the bend radius")
    dims = _dims(bar, code)
    if code == "12" and "R" in dims and dims["R"] < radius - 1e-6:
        notes.append(
            f"{where}: R = {dims['R']:g} mm is below the minimum bend radius {radius:g} mm; "
            "scheduled with the minimum."
        )
    if code in ("51", "63") and "C" not in dims and {"A", "B"} <= dims.keys():
        dims["C"] = seismic_hook(dia, radius)
    given = _get(bar, "length")
    if not dims and given is None:
        notes.append(f"{where}: neither dimensions nor a length; not scheduled.")
        return None
    if not dims or code == "99":
        if code not in ("00", "01", "99"):
            notes.append(f"{where}: shape {code} without dimensions; scheduled as shape 99.")
            code = "99"
        if given is not None:
            length = _num(given, "the length")
        elif "L" in dims:
            length = dims["L"]
        else:
            notes.append(f"{where}: shape 99 without a length; not scheduled.")
            return None
        if code in ("00", "01") and not dims:
            dims = {"A": length}
    else:
        try:
            length = cutting_length(code, dims, dia, radius)
        except ValueError as error:
            if given is None:
                notes.append(f"{where}: {error}; not scheduled.")
                return None
            notes.append(f"{where}: {error}; scheduled with the detailed length as shape 99.")
            code, length = "99", _num(given, "the length")
    p = end_projection(dia)
    ends = SHAPES[code].letters
    if code in ("11", "21", "23", "31", "41") and min(dims[ends[0]], dims[ends[-1]]) < p:
        notes.append(f"{where}: an end is shorter than the minimum end projection P = {p:g} mm.")
    if length > STOCK_LENGTH + 1e-6:
        notes.append(f"{where}: {length:.0f} mm is longer than a {STOCK_LENGTH:.0f} mm stock bar.")
    lap = _num(_get(bar, "lap", 0.0), "the lap")
    zone = str(_get(bar, "zone", ""))
    curtailed = _flag(_get(bar, "curtailed", False))
    members = int(_num(_get(bar, "members", _get(element, "count", 1)), "the number of members"))
    per_member = int(_num(_get(bar, "count", 1), "the number of bars"))
    remarks = [str(_get(bar, "remarks", ""))]
    if code == "77":
        remarks.append("C = turns")
    if zone:
        remarks.append(f"zone {zone}")
    if lap:
        remarks.append(f"lap {lap:.0f}")
    if curtailed:
        remarks.append("cut-off")
    # Dimensions print in whole mm, except a helix's C (its number of turns).
    shown = {k: round(v, 2) if (code, k) == ("77", "C") else round(v) for k, v in dims.items()}
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
        cutting_length=round_up(length),
        lap=lap,
        role=role,
        zone=zone,
        curtailed=curtailed,
        remarks=", ".join(r for r in remarks if r),
        cap=str(_get(element, "cap", "")),
        bim=_bim_ids(element),
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
    schedule.notes.append(
        "Shape codes, cutting lengths and minimum radii after BS 8666; bend radii not less than "
        "BNBC 2020 Part 6, 8.1.2.2; lengths rounded up to 25 mm; mass d²/162 kg/m."
    )
    return schedule


# ─────────────────────────────────── tables and CSV ───────────────────────────────────

COLUMNS = (
    ("member", "Member"),
    ("mark", "Bar\nmark"),
    ("size", "Type and\nsize"),
    ("shape", "Shape\ncode"),
    ("A", "A\n(mm)"),
    ("B", "B\n(mm)"),
    ("C", "C\n(mm)"),
    ("D", "D\n(mm)"),
    ("E", "E/R\n(mm)"),
    ("members", "No. of\nmbrs"),
    ("per_member", "No. in\neach"),
    ("total_count", "Total\nno."),
    ("cutting_length", "Length of\neach (mm)"),
    ("total_length", "Total\nlength (m)"),
    ("mass", "Mass\n(kg)"),
    ("remarks", "Remarks"),
)
NUMERIC = {"A", "B", "C", "D", "E", "members", "per_member", "total_count",
           "cutting_length", "total_length", "mass"}  # fmt: skip


def _cells(row: BbsRow) -> dict[str, str]:
    def dim(k: str) -> str:
        v = row.dims.get(k, row.dims.get("R") if k == "E" else None)
        if v is None:
            return ""
        return f"{v:g}" if (row.shape, k) == ("77", "C") else f"{v:.0f}"

    return {
        "member": row.member,
        "mark": row.mark,
        "size": row.size,
        "shape": row.shape,
        **{k: dim(k) for k in LETTERS},
        "members": str(row.members),
        "per_member": str(row.per_member),
        "total_count": str(row.total_count),
        "cutting_length": f"{row.cutting_length:.0f}",
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
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([title.replace("\n", " ") for _, title in COLUMNS])
    for row in schedule.rows:
        cells = _cells(row)
        writer.writerow([cells[key] for key, _ in COLUMNS])
    writer.writerow([])
    writer.writerow(["Totals per bar size", "", "Size", "", "", "", "", "", "", "", "", "",
                     "", "Total length (m)", "Mass (kg)"])  # fmt: skip
    for dia, mass in schedule.by_diameter.items():
        length = sum(r.total_length for r in schedule.rows if r.dia == dia)
        writer.writerow(["", "", f"Ø{dia:g}", *[""] * 10, f"{length:.2f}", f"{mass:.2f}"])
    writer.writerow(["Total", *[""] * 13, f"{schedule.total:.2f}"])
    writer.writerow([])
    writer.writerow(["Totals per element type", "", "Size", *[""] * 11, "Mass (kg)"])
    for kind, sizes in schedule.by_kind.items():
        for dia, mass in sizes.items():
            writer.writerow([_kind_label(kind), "", f"Ø{dia:g}", *[""] * 11, f"{mass:.2f}"])
        writer.writerow([f"{_kind_label(kind)} total", *[""] * 13, f"{sum(sizes.values()):.2f}"])
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
    columns: list[dict[str, Any]] = [
        {"key": k, "title": t, "align": "right" if k in NUMERIC else "left",
         "max": 28 if k in ("member", "remarks") else 14}
        for k, t in COLUMNS
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
        rows.append([cells[k] for k, _ in COLUMNS])
    _widths(columns, rows)
    for column in columns:
        column.pop("max")

    sizes = list(schedule.by_diameter)
    total_cols: list[dict[str, Any]] = [{"key": "kind", "title": "Element\ntype", "align": "left"}]
    total_cols += [{"key": f"d{d:g}", "title": f"Ø{d:g}\n(kg)", "align": "right"} for d in sizes]
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
    return {
        "title": "Bar bending schedule",
        "columns": columns,
        "rows": rows,
        "groups": groups,
        "totals": {"columns": total_cols, "rows": total_rows},
        "notes": list(schedule.notes),
    }


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
                "transverse": "hooks to BS 8666 / BNBC 135° seismic hooks and bend deductions "
                "(BOQ: centre line + 2 × 10 d), and link counts by zone (BOQ: length / spacing "
                "+ 1 at one spacing)",
                "longitudinal": "laps at the detailed splice positions with BNBC lap lengths "
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
            "The BOQ measures bars by its own conventions (10 BOQ notes): longitudinal bars over "
            "the member's full length with a 40 d lap per 12 m stock bar, links at their centre line "
            "with two 10 d hooks, meshes as area / spacing; the schedule cuts the detailed bars "
            "(BS 8666 cutting lengths rounded up to 25 mm, BNBC laps and hooks, cut-off bars)."
        ),
    ]
    return Reconciliation(rows, notes)


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
            [f"Ø{r.dia:g}", f"{r.bbs:.1f}", f"{r.boq:.1f}", f"{r.difference:+.1f}", pct,
             "\n".join(r.reasons)]
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
