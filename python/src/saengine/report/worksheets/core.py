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
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from saengine.report import clauses as _clauses


class Cite:
    """A clause reference worked out when it is printed, from the code pack in force then (a
    kind's references are written when the module loads, before any pack is chosen)."""

    __slots__ = ("_text",)

    def __init__(self, text: Callable[[], str]) -> None:
        self._text = text

    def __str__(self) -> str:
        return self._text()

    def __bool__(self) -> bool:
        return bool(self._text())

    def __repr__(self) -> str:
        return f"Cite({self._text()!r})"

    def __add__(self, other: object) -> Cite:
        return Cite(lambda: self._text() + str(other))

    def __radd__(self, other: object) -> Cite:
        return Cite(lambda: str(other) + self._text())

    def paren(self, before: str = " ") -> str:
        """``before`` + "(reference)", or '' when there is none."""
        text = self._text()
        return f"{before}({text})" if text else ""


def code_ref(key: str, suffix: str = "") -> Cite:
    """The reference ``key`` of the code pack in force (its ``citations`` table, with the code's
    name), followed by ``suffix``; empty when the pack gives none."""

    def text() -> str:
        found = _clauses.ref(key)
        return f"{found}{suffix}" if found else ""

    return Cite(text)


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


# ── C13b: the expressions with their values, in a project's display units ──

#: Characters that continue a symbol: "As,min", "f'c", "φMn" are one symbol each.
_SYMBOL_CHAR = r"A-Za-z0-9_'’,Ͱ-Ͽ"
_SYMBOL = re.compile(rf"[A-Za-zͰ-Ͽ][{_SYMBOL_CHAR}]{{0,6}}")
#: Words of a label that are not its symbol ("Width b": b; "Height of F": none).
_NOT_SYMBOLS = {"the", "of", "to", "at", "in", "on", "and", "or", "per", "by", "a", "an"}
#: Words a pure-mathematics expression may hold besides its symbols.
_FUNCTIONS = {"max", "min", "sin", "cos", "tan", "cot", "log", "exp", "ln", "e"}
_WORD = re.compile(r"[A-Za-z]{3,}")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def symbol_of(label: str) -> str | None:
    """The symbol a step or an input is known by in the expressions: the label itself when it
    is one ("Vc", "As,min"), else its last word when that is a symbol ("Effective depth d",
    "Factored moment Mu"); a word before "(...)" when the last is in parentheses ("fyt
    (stirrups)", "q (service)"); None otherwise ("As required", "Height of F")."""
    words = label.split()
    if not words:
        return None
    candidates = [words[0]] if len(words) == 1 else []
    if len(words) > 1:
        if words[-1].startswith("("):
            k = next((i for i, w in enumerate(words) if w.startswith("(")), len(words))
            candidates = [words[k - 1]] if k == 1 else []
        elif words[-2].lower() not in _NOT_SYMBOLS and not _NUMBER.fullmatch(words[-2]):
            candidates = [words[-1]]
    from saengine.units import kind_of

    for word in candidates:
        if not _SYMBOL.fullmatch(word) or word.lower() in _NOT_SYMBOLS:
            continue
        if kind_of(word) and word != "t":
            continue  # a unit ("F at 30.0 m")
        if len(word) > 3 and word.isalpha() and word.islower():
            continue  # a word ("span", "weight"), not a symbol
        return word
    return None


def si_only(formula: str) -> bool:
    """Whether an expression holds in the code's SI units only (SAEngine practice, C13b): it
    takes a root of a stress ("0.17 λ √f'c bw d") or has a constant above 100 or a small one
    of two or more significant digits ("d² / 162", "1000 / s", "0.000613 Kz V²"), whose value
    assumes N, mm and MPa. A kind marks the others itself (:meth:`Sheet.step` ``si_form``)."""
    if "√" in formula:
        return True
    for number in _NUMBER.findall(formula):
        value = float(number)
        digits = number.replace(".", "").strip("0")
        if value > 100 or (0 < value < 0.01 and len(digits) >= 2):
            return True
    return False


def with_values(
    formula: str, symbols: dict[str, tuple[float, str]], units: Any, si_form: bool
) -> str | None:
    """``formula`` with its symbols replaced by their values ("As fy / (0.85 f'c b)" ->
    "3.1 in² × 60.9 ksi / (0.85 × 3.63 ksi × 11.8 in)"): in ``units``, or in SI for an
    expression in the SI form (``si_form``). None for an expression in words ("1 m strip,
    stress block") or with no symbol known."""
    from saengine.units import SI

    if not formula or not symbols:
        return None
    names = sorted(symbols, key=len, reverse=True)
    # a comma continues a symbol only before a letter ("As,min"), not in a list ("√f'c, 1.4")
    pattern = re.compile(
        rf"(?<![{_LETTER}])(?<![{_LETTER}],)({'|'.join(re.escape(n) for n in names)})"
        rf"(?![{_LETTER}]|,[{_LETTER}])"
    )
    if not pattern.search(formula):
        return None
    rest = pattern.sub(" ", formula)
    words = re.findall(r"[A-Za-z]{2,}", rest)
    if any(w in _PROSE or (len(w) > 2 and w.lower() not in _FUNCTIONS) for w in words):
        return None
    shown = SI if si_form else units
    # the gaps between juxtaposed factors are products ("As fy" -> "As × fy"), marked before
    # the values (which have gaps of their own) go in; not a function's ("tan φ", "Σ F")
    marked = _FUNCTION_GAP.sub(r"\1 ", _PRODUCT.sub(_MARK, formula))

    def value_of(match: re.Match[str]) -> str:
        value, unit = symbols[match.group(1)]
        number, label = shown.convert(value, unit) if unit else (value, "")
        text = f"{fmt(number)}{label}" if label == "°" else f"{fmt(number)} {label}".strip()
        before = marked[match.start() - 1 : match.start()]
        after = marked[match.end() : match.end() + 1]
        return f"({text})" if label and (before == "√" or after in ("²", "³", "^")) else text

    return pattern.sub(value_of, marked).replace(_MARK, " × ")


#: A gap between two factors of an expression ("As fy", "0.85 f'c", ") (").
_PRODUCT = re.compile(r"(?<=[\w)²³⁴'’°])\s+(?=[\w(√])")
_MARK = "\x00"
_FUNCTION_GAP = re.compile("(\\bsin|\\bcos|\\btan|\\bcot|\\blog|\\bexp|\\bln|Σ|∑)\x00")
_LETTER = r"A-Za-z0-9_'’Ͱ-Ͽ"
#: Words that make an expression one in words ("Ie at D", "D in m").
_PROSE = {"at", "in", "of", "to", "on", "as", "is", "by", "or", "if", "no", "for", "and"}


@dataclass
class Sheet:
    """What a kind writes while it calculates (and the inputs it reads)."""

    values: dict[str, Any]
    steps: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: C13b: the project's display units (:class:`saengine.units.Units`); None: SI, and the
    #: steps are written exactly as before (no expression with values).
    units: Any = None
    #: The values known by their symbol so far, symbol -> (value, unit).
    symbols: dict[str, tuple[float, str]] = field(default_factory=dict)

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def bind(self, label: str, value: Any, unit: str) -> None:
        """Remembers a value by the symbol of its label (:func:`symbol_of`) for the
        expressions of the steps after it."""
        symbol = symbol_of(label)
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if symbol and number and math.isfinite(float(value)):
            self.symbols[symbol] = (float(value), unit)

    def heading(self, text: str) -> None:
        """A sub-heading between the steps."""
        self.steps.append({"heading": text})

    def step(
        self,
        label: str,
        value: float | str,
        unit: str = "",
        formula: str = "",
        clause: str | Cite = "",
        digits: int | None = None,
        si_form: bool | None = None,
    ) -> float | str:
        """Writes one intermediate value and returns it (for the next line). ``si_form``:
        whether ``formula`` is the code's SI form (valid in N, mm and MPa only; C13b), None to
        tell from the formula (:func:`si_only`)."""
        text = value if isinstance(value, str) else fmt(float(value), digits)
        row: dict[str, Any] = {
            "label": label,
            "value": text,
            "unit": unit,
            "formula": formula,
            "clause": str(clause),
        }
        if not isinstance(value, str):
            row["number"] = float(value) if math.isfinite(float(value)) else None
        if self.units is not None and not self.units.si:
            # C13b: the expression with the values, in the display units; one in the code's SI
            # form with the SI values, marked so
            si_form = si_only(formula) if si_form is None else si_form
            expression = with_values(formula, self.symbols, self.units, si_form)
            if expression:
                row["expression"] = expression
                row["siForm"] = si_form
            self.bind(label, value, unit)
        self.steps.append(row)
        return value

    def check(
        self,
        label: str,
        demand: float,
        capacity: float,
        unit: str = "",
        clause: str | Cite = "",
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
                "clause": str(clause),
            }
        )
        return ok

    def adopt(self, check: dict[str, Any], clause: str | Cite = "") -> bool:
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
                "clause": "; ".join(t for t in (str(check.get("note") or ""), str(clause)) if t),
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
    references: tuple[str | Cite, ...] = ()

    def cited(self) -> list[str]:
        """The references, with the clauses of the code pack in force (the empty left out)."""
        return [t for t in (str(r) for r in self.references) if t]

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "group": self.group,
            "summary": self.summary,
            "inputs": [i.describe() for i in self.inputs],
            "references": self.cited(),
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
    references: Sequence[str | Cite] = (),
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


def calculate(
    kind_id: str, inputs: dict[str, Any] | None = None, units: Any = None
) -> dict[str, Any]:
    """The calculation of a worksheet ``kind_id`` for ``inputs`` (the kind's defaults where an
    input is not given): ``{kind, title, inputs, steps, checks, notes, ok, utilisation,
    problems}``. With a problem in the inputs, or an input the design functions refuse, nothing
    is calculated and ``problems`` says why. In US customary ``units`` (C13b) each step whose
    expression is mathematics gets it with the values (``expression``, and ``siForm`` when it
    is the code's SI form, with the SI values); the numbers stay in SI (:func:`displayed`)."""
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
        "references": kind.cited(),
        "inputs": shown,
        "steps": [],
        "checks": [],
        "notes": [],
        "problems": problems,
    }
    if problems:
        return out
    sheet = Sheet(values)
    if units is not None and not units.si:
        sheet.units = units
        for spec in kind.inputs:
            if spec.kind == "number":
                sheet.bind(spec.label, values[spec.name], spec.unit)
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


def displayed(result: dict[str, Any], units: Any) -> dict[str, Any]:
    """A calculation (:func:`calculate`) as the worksheet editor shows it in ``units`` (C13b):
    the inputs, the steps' values and units, the checks and the texts converted; the same
    result in SI (or without units)."""
    from saengine.units import convert_text
    from saengine.units import fmt as units_fmt

    if units is None or units.si:
        return result

    def text(value: Any) -> Any:
        return convert_text(value, units) if isinstance(value, str) else value

    def number(value: Any, unit: str) -> str:
        try:
            return units_fmt(units.convert(float(str(value).replace(",", "")), unit)[0])
        except ValueError:
            return text(value)

    out = dict(result)
    out["inputs"] = [
        {**i, "value": number(i["value"], i["unit"]), "unit": units.label(i["unit"])}
        if i.get("unit")
        else i
        for i in result.get("inputs", [])
    ]
    steps = []
    for step in result.get("steps", []):
        if "heading" in step:
            steps.append({**step, "heading": text(step["heading"])})
            continue
        shown = dict(step)
        unit = str(step.get("unit") or "")
        if step.get("number") is not None and unit:
            shown["value"] = units_fmt(units.convert(float(step["number"]), unit)[0])
        else:
            shown["value"] = text(step.get("value"))
        shown["unit"] = units.label(unit) if unit else unit
        shown["label"] = text(step.get("label"))
        steps.append(shown)
    out["steps"] = steps
    out["checks"] = [
        {
            **c,
            "label": text(c["label"]),
            "demand": number(c["demand"], c["unit"]) if c.get("unit") else c["demand"],
            "capacity": number(c["capacity"], c["unit"]) if c.get("unit") else c["capacity"],
            "unit": units.label(c["unit"]) if c.get("unit") else c.get("unit", ""),
        }
        for c in result.get("checks", [])
    ]
    out["notes"] = [text(n) for n in result.get("notes", [])]
    out["problems"] = [text(p) for p in result.get("problems", [])]
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
