"""Display units: SI or US customary, for what SAEngine prints and reads back.

SAEngine computes and stores in SI only (mm, m, kN, MPa, kN/m², kN·m). A project chooses how
its numbers are shown (Project Settings › Units, ``units``): ``system`` "SI" (the default, the
numbers exactly as today) or "USCustomary", with optional per-quantity choices (``length``
"ft" or "in", ``force`` "kip" or "lbf", ...). Switching never changes a stored value: the
values are converted only where they are printed (the report, the drawings, the bar bending
schedule, the BOQ, CSV headers) and, in the editors, where they are typed
(``services/saengineProject/common/displayUnits.ts``, the same table).

A quantity is known by its SI unit as SAEngine writes it ("mm", "kN/m²", the "[mm]" of a
field's description): :data:`SI_UNITS` maps each to a quantity kind (:data:`KINDS`) and the
factor to the kind's base unit. A field whose unit is not written that way names its kind in
its JSON schema (``unitKind``).

Temperatures (C13b): "°C" is a temperature (°F = 1.8 °C + 32), "Δ°C" a temperature change
(1.8 °F per °C; a field names it with ``unitKind`` "temperatureChange", and printed text writes
it as a change, "ΔT = 20 °C" or "±20 °C"); "1/°C" a coefficient of thermal expansion.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

# ── exact definitions (NIST SP 811) ──
FOOT = 0.3048  # m
INCH = 0.0254  # m
POUND_FORCE = 4.4482216152605  # N
KIP = 1000 * POUND_FORCE  # N
POUND = 0.45359237  # kg
SHORT_TON = 2000 * POUND  # kg
MILE = 1609.344  # m

SYSTEMS = ("SI", "USCustomary")


@dataclass(frozen=True)
class Kind:
    """A quantity: its SI base unit and the US customary units it can be shown in, each with
    the factor from the base unit (``value_us = value_si * factor``); the first is the default."""

    id: str
    si: str
    us: tuple[tuple[str, float], ...]
    title: str
    #: Added after the factor (``value_us = value_si * factor + offset``): absolute temperatures.
    offsets: tuple[tuple[str, float], ...] = ()
    #: The unit text shown in SI when it is not :attr:`si` (a temperature change shows "°C").
    si_label: str = ""

    def offset(self, unit: str) -> float:
        return dict(self.offsets).get(unit, 0.0)

    def factor(self, unit: str) -> float:
        if unit == self.si:
            return 1.0
        for label, factor in self.us:
            if label == unit:
                return factor
        raise KeyError(f"{unit!r} is not a unit of {self.id}")

    @property
    def options(self) -> tuple[str, ...]:
        return tuple(label for label, _ in self.us)


def _kinds() -> dict[str, Kind]:
    kn_m2_in_psf = 1000 / (POUND_FORCE / FOOT**2)
    kn_in_kip = 1000 / KIP
    kn_m_in_kip_ft = 1000 / (KIP * FOOT)
    kinds = [
        Kind("length", "m", (("ft", 1 / FOOT), ("in", 1 / INCH)), "Lengths and levels [m]"),
        Kind(
            "dimension",
            "mm",
            (("in", 1e-3 / INCH), ("ft", 1e-3 / FOOT)),
            "Member sizes, covers and spacings [mm]",
        ),
        Kind("force", "kN", (("kip", kn_in_kip), ("lbf", 1000 / POUND_FORCE)), "Forces [kN]"),
        Kind(
            "stress",
            "MPa",
            (("ksi", 1e6 / (KIP / INCH**2)), ("psi", 1e6 / (POUND_FORCE / INCH**2))),
            "Stresses and strengths [MPa]",
        ),
        Kind(
            "pressure",
            "kN/m²",
            (("psf", kn_m2_in_psf), ("ksf", kn_m2_in_psf / 1000)),
            "Area loads and soil pressures [kN/m²]",
        ),
        Kind(
            "moment",
            "kN·m",
            (("kip·ft", kn_m_in_kip_ft), ("kip·in", 1000 / (KIP * INCH))),
            "Moments [kN·m]",
        ),
        Kind(
            "lineLoad",
            "kN/m",
            (("kip/ft", 1000 * FOOT / KIP), ("plf", 1000 * FOOT / POUND_FORCE)),
            "Line loads [kN/m]",
        ),
        Kind(
            "momentPerLength",
            "kN·m/m",
            (("kip·ft/ft", kn_m_in_kip_ft * FOOT),),
            "Moments per width [kN·m/m]",
        ),
        Kind(
            "unitWeight",
            "kN/m³",
            (("pcf", 1000 * FOOT**3 / POUND_FORCE), ("kcf", 1000 * FOOT**3 / KIP)),
            "Unit weights [kN/m³]",
        ),
        Kind("density", "kg/m³", (("pcf", FOOT**3 / POUND),), "Densities [kg/m³]"),
        Kind("area", "mm²", (("in²", 1e-6 / INCH**2),), "Bar and section areas [mm²]"),
        Kind(
            "areaPerLength",
            "mm²/m",
            (("in²/ft", 1e-6 / INCH**2 * FOOT),),
            "Reinforcement per width [mm²/m]",
        ),
        Kind(
            "areaPerSpacing",
            "mm²/mm",
            (("in²/in", 1e-6 / INCH**2 * 1e3 * INCH),),
            "Reinforcement per spacing [mm²/mm]",
        ),
        Kind("areaLarge", "m²", (("ft²", 1 / FOOT**2),), "Floor and plan areas [m²]"),
        Kind("volume", "m³", (("ft³", 1 / FOOT**3), ("yd³", 1 / (3 * FOOT) ** 3)), "Volumes [m³]"),
        Kind("mass", "kg", (("lb", 1 / POUND),), "Masses [kg]"),
        Kind("massLarge", "t", (("ton", 1000 / SHORT_TON),), "Masses [t]"),
        Kind("velocity", "m/s", (("mph", 3600 / MILE), ("ft/s", 1 / FOOT)), "Speeds [m/s]"),
        Kind(
            "stiffness",
            "kN/mm",
            (("kip/in", 1000 * INCH * 1000 / KIP),),
            "Spring stiffnesses [kN/mm]",
        ),
        Kind("inertia", "mm⁴", (("in⁴", 1e-12 / INCH**4),), "Second moments of area [mm⁴]"),
        Kind("sectionModulus", "mm³", (("in³", 1e-9 / INCH**3),), "Section moduli [mm³]"),
        # C13b: temperatures (an absolute one with the offset, a change without)
        Kind("temperature", "°C", (("°F", 1.8),), "Temperatures [°C]", offsets=(("°F", 32.0),)),
        Kind(
            "temperatureChange",
            "Δ°C",
            (("°F", 1.8),),
            "Temperature changes [°C]",
            si_label="°C",
        ),
        Kind("perTemperature", "1/°C", (("1/°F", 1 / 1.8),), "Thermal expansion [1/°C]"),
    ]
    return {k.id: k for k in kinds}


#: The quantity kinds, by id.
KINDS: dict[str, Kind] = _kinds()

#: SAEngine's SI unit texts -> (kind, factor to the kind's base unit).
SI_UNITS: dict[str, tuple[str, float]] = {
    "m": ("length", 1.0),
    "mm": ("dimension", 1.0),
    "kN": ("force", 1.0),
    "MPa": ("stress", 1.0),
    "N/mm²": ("stress", 1.0),
    "GPa": ("stress", 1000.0),
    "kN/m²": ("pressure", 1.0),
    "kPa": ("pressure", 1.0),
    "kN·m": ("moment", 1.0),
    "kNm": ("moment", 1.0),
    "kN/m": ("lineLoad", 1.0),
    "kN·m/m": ("momentPerLength", 1.0),
    "kN/m³": ("unitWeight", 1.0),
    "kg/m³": ("density", 1.0),
    "mm²": ("area", 1.0),
    "mm²/m": ("areaPerLength", 1.0),
    "mm²/mm": ("areaPerSpacing", 1.0),
    "m²": ("areaLarge", 1.0),
    "m³": ("volume", 1.0),
    "kg": ("mass", 1.0),
    "t": ("massLarge", 1.0),
    "m/s": ("velocity", 1.0),
    "kN/mm": ("stiffness", 1.0),
    "mm⁴": ("inertia", 1.0),
    "mm³": ("sectionModulus", 1.0),
    "°C": ("temperature", 1.0),
    "Δ°C": ("temperatureChange", 1.0),
    "1/°C": ("perTemperature", 1.0),
}

#: The per-quantity choices a project can make (Project Settings › Units), kind -> options.
OVERRIDABLE = (
    "length",
    "dimension",
    "force",
    "stress",
    "pressure",
    "moment",
    "lineLoad",
    "unitWeight",
    "volume",
    "velocity",
)


def kind_of(unit: str) -> tuple[str, float] | None:
    """(kind, factor to its base unit) of the SI unit text ``unit``, or None."""
    return SI_UNITS.get(unit.strip())


# ─────────────────────────────────────── number text ───────────────────────────────────────


def fmt(value: float, significant: int = 3) -> str:
    """A converted value as printed: three significant figures, whole units from 100 (with
    thousands separators), as the report prints its own values."""
    if value is None or not math.isfinite(value):
        return "-" if value is None or math.isnan(value) else ("∞" if value > 0 else "-∞")
    size = abs(value)
    if size == 0:
        return "0"
    if size >= 10 ** (significant - 1):
        return f"{value:,.0f}"
    decimals = significant - 1 - math.floor(math.log10(size))
    text = f"{value:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def feet_inches(mm: float, denominator: int = 8) -> str:
    """A length [mm] in feet and inches to the nearest 1/``denominator`` inch: 3810 ->
    ``12'-6"``, 165 -> ``6 1/2"``, 0 -> ``0"``."""
    sign = "-" if mm < 0 else ""
    steps = round(abs(mm) / 25.4 * denominator)
    whole, part = divmod(steps, denominator)
    feet, inches = divmod(whole, 12)
    fraction = ""
    if part:
        g = math.gcd(part, denominator)
        fraction = f"{part // g}/{denominator // g}"
    inch_text = " ".join(t for t in (str(inches) if inches else "", fraction) if t)
    if feet:
        return f"{sign}{feet}'-{inch_text or '0'}\""
    return f'{sign}{inch_text or "0"}"'


def inches_text(mm: float, denominator: int = 8) -> str:
    """A size [mm] in inches to the nearest 1/``denominator`` inch, without feet: 300 ->
    ``11 3/4"``, 600 -> ``23 5/8"`` (member sizes, as US drawings write them)."""
    sign = "-" if mm < 0 else ""
    steps = round(abs(mm) / 25.4 * denominator)
    whole, part = divmod(steps, denominator)
    fraction = ""
    if part:
        g = math.gcd(part, denominator)
        fraction = f"{part // g}/{denominator // g}"
    text = " ".join(t for t in (str(whole) if whole else "", fraction) if t)
    return f'{sign}{text or "0"}"'


# ─────────────────────────────────────── the project's units ───────────────────────────────


@dataclass(frozen=True)
class Units:
    """How a project shows its numbers: ``system`` and the per-quantity choices."""

    system: str = "SI"
    choices: Mapping[str, str] = field(default_factory=dict)
    #: The code pack's bar names by diameter text ("16" -> "#5"), used in US customary units.
    bar_names: Mapping[str, str] = field(default_factory=dict)

    @property
    def si(self) -> bool:
        return self.system != "USCustomary"

    def unit(self, kind: str) -> str:
        """The unit ``kind`` is shown in."""
        k = KINDS[kind]
        if self.si:
            return k.si
        chosen = self.choices.get(kind)
        return chosen if chosen in k.options else k.us[0][0]

    def convert(self, value: float, si_unit: str) -> tuple[float, str]:
        """``value`` in the SI unit text ``si_unit`` -> (value, unit) as shown. A unit that is
        not a known SI unit, and every unit in SI, comes back as it is."""
        known = kind_of(si_unit)
        if self.si or known is None:
            return value, si_unit
        kind, scale = known
        unit = self.unit(kind)
        k = KINDS[kind]
        return value * scale * k.factor(unit) + k.offset(unit), unit

    def to_si(self, value: float, si_unit: str) -> float:
        """The inverse of :meth:`convert`: a value as shown -> the value in ``si_unit``."""
        known = kind_of(si_unit)
        if self.si or known is None:
            return value
        kind, scale = known
        k = KINDS[kind]
        unit = self.unit(kind)
        return (value - k.offset(unit)) / (scale * k.factor(unit))

    def label(self, si_unit: str) -> str:
        """The unit text shown for values stored in ``si_unit``."""
        if self.si:
            known = kind_of(si_unit)
            return (KINDS[known[0]].si_label or si_unit) if known else si_unit
        return self.convert(1.0, si_unit)[1]

    def format(self, value: float, si_unit: str, significant: int = 3) -> str:
        """``value`` [``si_unit``] as text with its unit: "9.84 in" (US), "250 mm" (SI keeps
        the value as given, with :func:`fmt`)."""
        shown, unit = self.convert(value, si_unit)
        return f"{fmt(shown, significant)} {unit}".strip()

    def length_text(self, mm: float) -> str:
        """A dimension [mm] as a drawing writes it: "250" in SI, ``9'-10 1/8"`` in US units."""
        return f"{mm:.0f}" if self.si else feet_inches(mm)

    def size_text(self, mm: float) -> str:
        """A member size [mm] as a drawing or a table writes it: "300" in SI; in US units in
        inches (``11 3/4"``), or feet and inches when the project shows sizes in feet."""
        if self.si:
            return f"{mm:g}"
        return feet_inches(mm) if self.unit("dimension") == "ft" else inches_text(mm)

    def bar(self, dia: float) -> str:
        """A bar size: "Ø16" in SI, the pack's name ("#5") in US units when it has one."""
        if not self.si:
            name = self.bar_names.get(f"{dia:g}")
            if name:
                return name
        return f"Ø{dia:g}"


SI = Units()


def units_of(settings: Any, bar_names: Mapping[str, str] | None = None) -> Units:
    """The display units of project settings (a :class:`ProjectSettings`, its JSON dict, or
    its ``units`` value); SI when they say none."""
    data: Any = settings
    if data is not None and not isinstance(data, Mapping):
        data = getattr(data, "units", None)
    elif isinstance(data, Mapping) and "units" in data:
        data = data.get("units")
    if data is not None and not isinstance(data, Mapping):
        dump = getattr(data, "model_dump", None)
        data = dump(mode="json", exclude_none=True) if dump else None
    if not isinstance(data, Mapping):
        return Units(bar_names=dict(bar_names or {}))
    system = data.get("system")
    choices = {k: str(v) for k, v in data.items() if k in OVERRIDABLE and v}
    return Units(
        system=system if system in SYSTEMS else "SI",
        choices=choices,
        bar_names=dict(bar_names or {}),
    )


def units_from_json(text: str | None) -> Units:
    """:func:`units_of` the JSON text of a ``units`` value (as the drawings' title info
    carries it); SI when it is empty or not valid."""
    if not text:
        return SI
    try:
        data = json.loads(text)
    except ValueError:
        return SI
    if not isinstance(data, Mapping):
        return SI
    names = data.get("barNames")
    return units_of({"units": data}, names if isinstance(names, Mapping) else pack_bar_names())


def units_json(units: Units) -> str:
    """:class:`Units` as the JSON text :func:`units_from_json` reads ("" for SI)."""
    if units.si:
        return ""
    return json.dumps(
        {"system": units.system, **dict(units.choices), "barNames": dict(units.bar_names)},
        ensure_ascii=False,
    )


def project_units(settings: Any) -> Units:
    """The display units of project settings (a model or its JSON dict) with the bar names of
    the code pack they choose; SI (without loading a pack) when they choose SI."""
    units = units_of(settings)
    if units.si:
        return units
    try:
        from saengine.codes import context as code_context

        concrete = code_context.pack_for(settings).table("concrete")
        names = getattr(concrete, "barNames", None) or {}
    except Exception:  # noqa: BLE001 - the pack cannot be loaded: the names of the one in force
        names = pack_bar_names()
    return Units(units.system, units.choices, {str(k): str(v) for k, v in names.items()})


def units_at(project_root: Any) -> Units:
    """:func:`project_units` of the project at ``project_root`` (its Project Settings file);
    SI without a root or when the file cannot be read."""
    if not project_root:
        return SI
    from pathlib import Path

    path = Path(project_root) / "02 Project Settings" / "project-settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SI
    return project_units(settings) if isinstance(settings, Mapping) else SI


def pack_bar_names() -> dict[str, str]:
    """The bar names of the code pack in force (``concrete.barNames``), {} when it has none."""
    try:
        from saengine.codes import context as code_context

        names = getattr(code_context.table("concrete"), "barNames", None)
    except Exception:  # noqa: BLE001 - no pack in force, or one without a concrete table
        return {}
    return {str(k): str(v) for k, v in (names or {}).items()}


# ─────────────────────────────────────── printed text ───────────────────────────────────────

# A number as SAEngine prints one: 1,234.5, -12, 0.25 (not part of a word, a clause number
# like 6.2.19 or a bar size like Ø16).
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNIT_TEXTS = sorted(
    (u for u in SI_UNITS if u not in ("t", "kNm", "Δ°C", "1/°C")), key=len, reverse=True
)
_UNIT = "|".join(re.escape(u) for u in _UNIT_TEXTS)
_QUANTITY = re.compile(
    rf"(?<![\w.,#Ø/·])(-?{_NUM})((?:\s*(?:×|x|–|to)\s*-?{_NUM})*)\s?({_UNIT})(?![\w²³⁴/·])"
)
_SEPARATOR = re.compile(rf"(\s*(?:×|x|–|to)\s*)(-?{_NUM})")
_BAR = re.compile(
    r"(?:(?<![\w.,])(\d+)(\s?))?Ø(\d+(?:\.\d+)?)(?:\s*@\s*(\d+(?:\.\d+)?)(?!\s*(?:mm|m)\b))?"
)


def _number(text: str) -> float:
    return float(text.replace(",", ""))


#: Words before a temperature that make it a change ("ΔT = 20 °C", "±20 °C", "differ by 11 °C").
_CHANGE = re.compile(r"Δ|±|\b(?:by|range|rise|drop|change|gradient)\b", re.IGNORECASE)


def _is_change(text: str, at: int) -> bool:
    """Whether the temperature printed at ``at`` in ``text`` is a change (SAEngine practice: a
    "Δ", "±" or one of :data:`_CHANGE`'s words within the 20 characters before it)."""
    return _CHANGE.search(text[max(0, at - 20) : at]) is not None


def convert_text(text: str, units: Units) -> str:
    """``text`` with every SI quantity it prints ("250 mm", "300 × 500 mm", "4.5 kN/m²") in
    the display units, and bar sizes ("Ø16 @ 150") by the pack's names; as it is in SI."""
    if units.si or not text:
        return text

    def quantity(match: re.Match[str]) -> str:
        unit = match.group(3)
        if unit == "°C" and _is_change(text, match.start()):
            unit = "Δ°C"
        first = units.convert(_number(match.group(1)), unit)
        shown = first[1]
        rest = _SEPARATOR.sub(
            lambda m: m.group(1) + fmt(units.convert(_number(m.group(2)), unit)[0]),
            match.group(2),
        )
        return f"{fmt(first[0])}{rest} {shown}"

    def bar(match: re.Match[str]) -> str:
        name = units.bar(float(match.group(3)))
        if match.group(1) is not None:
            # a count before the size: "4Ø16" -> "4-#5" by the pack's name, as it was without
            gap = match.group(2) if name.startswith("Ø") else "-"
            name = f"{match.group(1)}{gap}{name}"
        if match.group(4) is None:
            return name
        spacing = fmt(units.convert(float(match.group(4)), "mm")[0])
        return f"{name} @ {spacing} {units.unit('dimension')}"

    return _BAR.sub(bar, _QUANTITY.sub(quantity, text))


#: Sizes in mm a drawing writes without a unit ("300x500", "500 x 500 x 600"); not a section
#: designation ("SHS 150x150x8" after two capitals and a space, "W310x39" after a letter).
_SIZE = re.compile(
    r"(?<![\w.,#Ø/\"'])(?<![A-Z]{2} )(\d+(?:\.\d+)?)((?:\s?[x×]\s?\d+(?:\.\d+)?){1,2})"
    r"(?![\w.²³/\"'])"
)
_SIZE_PART = re.compile(r"(\s?[x×]\s?)(\d+(?:\.\d+)?)")
#: Lengths in mm a drawing writes with a word: "LAP 800", "WAIST 150", "COVER 40", "150 THK".
_WORD_SIZE = re.compile(
    r"\b(LAP|WAIST|COVER|TIE COLUMN|TIE BEAM)(\s+)(\d+(?:\.\d+)?)(?![\w.])"
    r"|(?<![\w.,/])(\d+(?:\.\d+)?)(\s+THK)\b"
)


def convert_sizes(text: str, units: Units) -> str:
    """The sizes in mm a drawing's text writes without a unit (``300x500``, ``LAP 800``,
    ``150 THK``) in the display units (:meth:`Units.size_text`); as it is in SI."""
    if units.si or not text:
        return text

    def size(match: re.Match[str]) -> str:
        rest = _SIZE_PART.sub(
            lambda m: m.group(1) + units.size_text(float(m.group(2))), match.group(2)
        )
        return units.size_text(float(match.group(1))) + rest

    def word(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}{match.group(2)}{units.size_text(float(match.group(3)))}"
        return f"{units.size_text(float(match.group(4)))}{match.group(5)}"

    return _WORD_SIZE.sub(word, _SIZE.sub(size, text))


_MM_TITLE = re.compile(r"\(mm\)")
_PILE_CELL = re.compile(r"(\d+(?:\.\d+)?) x (\d+(?:\.\d+)?)")
_MM_CELL = re.compile(r"(?<![\w.,#Ø/\"'])(\d+(?:\.\d+)?)(?![\w.²³/\"'])")


def convert_mm_table(
    columns: list[dict[str, Any]], rows: list[list[str]], units: Units
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """A drawing's table (columns ``{"title", ...}``, rows of text) in the display units: the
    numbers of its "(mm)" columns by :meth:`Units.size_text` (a bar size column "Ø (mm)" by
    the pack's bar names), their titles with the unit, the other cells by
    :func:`convert_text`; the same table in SI."""
    if units.si:
        return columns, rows
    shown = units.unit("dimension")
    kinds: dict[int, str] = {}
    out_columns = []
    for i, column in enumerate(columns):
        title = str(column.get("title") or "")
        if _MM_TITLE.search(title):
            if "Ø x L (mm)" in title:  # a pile type: its diameter [mm] and length [m]
                kinds[i] = "pile"
                title = _MM_TITLE.sub("", title).rstrip()
            elif "Ø (mm)" in title:
                kinds[i] = "bar"
                title = title.replace("Ø (mm)", "size")
            elif re.search(r"Length|Position", title):  # lengths along members, positions
                kinds[i] = "length"
                title = _MM_TITLE.sub("(ft-in)", title)
            else:
                kinds[i] = "size"
                title = _MM_TITLE.sub(f"({'ft-in' if shown == 'ft' else 'in'})", title)
        out_columns.append({**column, "title": title})
    out_rows = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            text = str(cell)
            if kinds.get(i) == "pile":
                text = _PILE_CELL.sub(
                    lambda m: (
                        f"{units.size_text(float(m.group(1)))} x "
                        f"{fmt(units.convert(float(m.group(2)), 'm')[0])} {units.unit('length')}"
                    ),
                    text,
                )
            elif kinds.get(i) == "bar":
                text = _MM_CELL.sub(lambda m: units.bar(float(m.group(1))), text)
            elif kinds.get(i) == "length":
                text = _MM_CELL.sub(lambda m: feet_inches(float(m.group(1))), text)
            elif kinds.get(i) == "size":
                text = _MM_CELL.sub(lambda m: units.size_text(float(m.group(1))), text)
            else:
                text = convert_text(text, units)
            cells.append(text)
        out_rows.append(cells)
    return out_columns, out_rows


#: A level as the drawings write it: a signed number of metres to 3 decimals ("+3.000").
_LEVEL = re.compile(r"(?<![\w.,])([+-]\d+\.\d{3})(?![\d\w])")


def convert_levels(text: str, units: Units) -> str:
    """The levels of a drawing's text ("GROUND +0.000", "+3.000" [m]) in the display unit of
    lengths, two decimals with a foot mark in feet ("+9.84'"); as it is in SI."""
    if units.si or not text:
        return text
    unit = units.unit("length")
    mark = "'" if unit == "ft" else '"'

    def level(match: re.Match[str]) -> str:
        value = units.convert(float(match.group(1)), "m")[0]
        return f"{value:+.2f}{mark}"

    return _LEVEL.sub(level, text)


# ─────────────────────────────────────── the report document ───────────────────────────────

#: Table columns whose numbers are in the unit of the row's "Unit" column.
_VALUE_HEADS = {"value", "demand", "capacity", "limit", "provided", "required", "quantity"}
_HEAD_UNIT = re.compile(r"^(.*?)(\s*)([(\[])([^()\[\]]+)([)\]])\s*$", re.DOTALL)
_PLAIN_NUMBER = re.compile(rf"^\s*(-?{_NUM})\s*$")


def _cell(value: Any, unit: str, units: Units) -> Any:
    """A table cell that is a plain number [``unit``] in the display unit; text otherwise."""
    if not isinstance(value, str):
        return value
    match = _PLAIN_NUMBER.match(value)
    if match is None:
        return convert_text(value, units)
    return fmt(units.convert(_number(match.group(1)), unit)[0])


def _head(text: str, units: Units) -> tuple[str, str | None]:
    """A column heading with a unit, "Elevation (m)" -> ("Elevation (ft)", "m")."""
    match = _HEAD_UNIT.match(text)
    if match is None or kind_of(match.group(4)) is None:
        return convert_text(text, units), None
    title, gap, open_, unit, close = match.groups()
    return f"{title}{gap}{open_}{units.label(unit)}{close}", unit.strip()


def convert_rows(
    head: list[str], rows: list[list[Any]], units: Units
) -> tuple[list[str], list[list[Any]]]:
    """A table's heading and rows in the display units: the columns whose heading names a unit
    ("Mu (kN·m)"), the value columns of a table with a "Unit" column (each row in its own
    unit), and every other text cell by :func:`convert_text`."""
    if units.si:
        return head, rows
    heads = [_head(str(h), units) for h in head]
    names = [str(h).strip().lower() for h in head]
    unit_at = names.index("unit") if "unit" in names else None
    value_at = {i for i, n in enumerate(names) if n in _VALUE_HEADS}
    out: list[list[Any]] = []
    for row in rows:
        row_unit = str(row[unit_at]) if unit_at is not None and unit_at < len(row) else ""
        cells: list[Any] = []
        for i, value in enumerate(row):
            column_unit = heads[i][1] if i < len(heads) else None
            if column_unit:
                cells.append(_cell(value, column_unit, units))
            elif i in value_at and kind_of(row_unit):
                cells.append(_cell(value, row_unit, units))
            elif i == unit_at and kind_of(row_unit):
                cells.append(units.label(row_unit))
            else:
                cells.append(convert_text(value, units) if isinstance(value, str) else value)
        out.append(cells)
    return [h for h, _ in heads], out


def _texts(value: Any, units: Units) -> Any:
    if isinstance(value, str):
        return convert_text(value, units)
    if isinstance(value, list):
        return [_texts(v, units) for v in value]
    return value


def convert_block(block: dict[str, Any], units: Units) -> dict[str, Any]:
    """One report block (:mod:`saengine.report.document`) in the display units; a block made
    in them already (``shown``: a calculation worksheet's, C13b) as it is."""
    if block.get("shown"):
        return block
    kind = block.get("t")
    out = dict(block)
    if kind == "table":
        out["head"], out["rows"] = convert_rows(list(block["head"]), list(block["rows"]), units)
    elif kind == "checks":
        # [check, demand, capacity, unit, utilisation, combination, result, remark?]
        rows = []
        for row in block.get("rows", []):
            row = list(row)
            unit = str(row[3]) if len(row) > 3 else ""
            if kind_of(unit):
                row[1] = _cell(row[1], unit, units)
                row[2] = _cell(row[2], unit, units)
                row[3] = units.label(unit)
            rows.append(
                [
                    convert_text(c, units) if isinstance(c, str) and i not in (1, 2, 3) else c
                    for i, c in enumerate(row)
                ]
            )
        out["rows"] = rows
        out["title"] = convert_text(str(block.get("title", "")), units)
    else:
        for key in ("text", "strong", "rows", "items"):
            if key in out:
                out[key] = _texts(out[key], units)
    return out


#: What the report says of its units in US customary units.
UNITS_NOTE = (
    "Values are computed in SI and printed in US customary units (3 significant figures). "
    "The calculation worksheets give each expression with its values as printed; an "
    "expression in the code's SI form (valid in N, mm and MPa only) is given with its SI "
    "values and marked so."
)


def convert_document(document: dict[str, Any], units: Units) -> dict[str, Any]:
    """The report document (:func:`saengine.report.document.report_document`) in the display
    units; the same document in SI. Its numbers were computed in SI: only their text changes."""
    if units.si:
        return document
    sections = []
    for section in document.get("sections", []):
        blocks = [convert_block(b, units) for b in section.get("blocks", [])]
        if section.get("id") == "basis":
            at = 1 if blocks and blocks[0].get("t") == "h" else 0
            blocks.insert(at, {"t": "note", "text": UNITS_NOTE})
        sections.append(
            {
                **section,
                "title": convert_text(str(section.get("title", "")), units),
                "blocks": blocks,
            }
        )
    out = {**document, "sections": sections}
    out["warnings"] = [convert_text(str(w), units) for w in document.get("warnings", [])]
    status = document.get("status")
    if isinstance(status, dict) and isinstance(status.get("headline"), str):
        out["status"] = {**status, "headline": convert_text(status["headline"], units)}
    return out


def csv_heading(title: str, units: Units) -> str:
    """A CSV column heading with its unit in the display units: "Mass (kg)" -> "Mass (lb)"."""
    return _head(title, units)[0]


def converter(units: Units, si_unit: str) -> Callable[[float], float]:
    """A function from values [``si_unit``] to the display unit (for columns of numbers)."""
    return lambda value: units.convert(value, si_unit)[0]
