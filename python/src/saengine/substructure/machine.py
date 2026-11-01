"""Machine and generator foundations: a block under a machine checked by the code pack's
machine foundation rules (Part 9).

Every number and clause comes from the pack's ``foundations.machine`` group
(:class:`saengine.codes.tables.MachineFoundationRules`); a pack without it does not cover
machine foundations, and the report says so. The pack chooses the method by id
(``lumpedSdof``: the machine, the block and the participating soil as one mass on one spring
and dashpot). What is checked for each :class:`saengine.library.substructure.MachineFoundation`:

- the impact rule: impact forces are designed for under hammers and presses, cranes and moving
  equipment, on loose granular soil, or when the live load causing the impact exceeds the
  pack's share of the dead load;
- the mass m = mf + ms, with the participating soil ms / mf given, else the pack's range
  enveloped (the lighter and the heavier system both checked);
- the vertical spring k from the soil: Barkan's relation from E (the soil report's layers
  under the base, a laboratory E, or E = 2G(1 + μ) from a torsional test's G), the subgrade
  modulus ks (the soil report's at the nearest borehole) times the area, a repeated plate load
  test scaled to the base (cohesive or cohesionless), a resonance test, or a given value; the
  pack's forms of a printed relation are enveloped;
- the damping factor D given, from a logarithmic decrement or a hysteresis loop, else the low
  end of the pack's range (the larger amplitude);
- resonance: the frequency ratio f / fn on the side of resonance the pack allows for the
  machine's speed class (below for a stiff foundation, above for a soft one);
- the amplitude at the operating speed under the unbalanced force (or the rotating unbalance
  m·e·ω²) against the maker's value, else the pack's permissible amplitude for the speed; a
  soft foundation also at resonance while starting and stopping; a hammer's under one blow,
  I / (m ωn), against the pack's hammer amplitude;
- the horizontal mode the same way when its spring is given (the pack's methods give the
  vertical spring);
- the static soil pressure at most the pack's share of qa;
- the eccentricity of the centre of gravity of machine and block from the centroid of the
  base;
- the ground water at least the pack's multiple of the base width below the base;
- the base below the adjacent building's foundations, and separated from them.

Units: mm and levels in mm (project datum) in the model; inside m, t, kN, kN/m, kPa, Hz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.codes import context as code_context
from saengine.design.check import _check

#: Standard gravity [m/s²] (t × g = kN).
GRAVITY = 9.81


# ─────────────────────────────────────── the pack ───────────────────────────────────────


def rules() -> Any | None:
    """The pack's ``foundations.machine`` group, or None when the pack does not cover it."""
    pack = code_context.current()
    table = pack.table("foundations") if pack.has("foundations") else None
    if table is None or getattr(table, "machine", None) is None:
        from saengine.codes.registry import DEFAULT_PACK
        from saengine.codes.tables import builtin_table

        if pack.id != DEFAULT_PACK:
            return None
        table = builtin_table("foundations", DEFAULT_PACK)
    return getattr(table, "machine", None)


def _sources() -> dict[str, str]:
    pack = code_context.current()
    try:
        table = pack.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table names no clause
        return {}
    sources = dict(getattr(table, "sources", {}) or {})
    if not any(k.startswith("machine") for k in sources):
        from saengine.codes.registry import DEFAULT_PACK
        from saengine.codes.tables import builtin_table

        if pack.id == DEFAULT_PACK:
            sources.update(builtin_table("foundations", DEFAULT_PACK).sources)
    return sources


def clause(key: str | None = None) -> str:
    """The clause of ``machine.<key>``, else of the whole group (empty when none)."""
    sources = _sources()
    if key and f"machine.{key}" in sources:
        return sources[f"machine.{key}"]
    return sources.get("machine", "")


def code_name() -> str:
    pack = code_context.current()
    return pack.name or pack.id


def not_covered(what: str) -> str:
    return f"{what}: not covered by the code pack {code_name()}"


def _cite(text: str, key: str | None = None) -> str:
    where = clause(key)
    return f"{text} ({where})" if where else text


def _rule(name: str, ok: bool, note: str, flag: bool = False) -> dict[str, Any]:
    """A yes/no requirement as a check: utilisation 0 when met, 99 when not."""
    return _check(name, 0.0 if ok else 1.0, 1.0, "", None, note, flag, 0.0 if ok else 99.0)


def method_lines() -> list[str]:
    """The method lines of the report, from the pack."""
    found = rules()
    if found is None:
        return []
    return [
        f"Machine foundations ({clause()}): the machine, the block and the participating soil "
        "as one mass on one spring and dashpot (single degree of freedom); the spring from the "
        "soil's E (Barkan), the subgrade modulus, a plate load or resonance test; resonance "
        "kept to the side the code allows for the speed, amplitudes against the maker's or the "
        f"code's permissible values, static pressure at most {found.staticPressure:g} qa, "
        f"eccentricity at most {found.eccentricity:.0%}, ground water at least "
        f"{found.waterDepth:g} B below the base." + (f" {found.note}" if found.note else "")
    ]


# ─────────────────────────────────── the relations ───────────────────────────────────


def barkan_stiffness(
    e_kpa: float, poisson: float, area: float, coefficient: float, form: str
) -> float:
    """k = c E √A / (1 - μ) (``linear``) or / (1 - μ²) (``square``) [kN/m], E in kPa, A in m²."""
    denominator = 1 - poisson if form == "linear" else 1 - poisson**2
    return coefficient * e_kpa * math.sqrt(area) / denominator


def plate_stiffness(kp: float, b: float, bp: float, cohesive: bool, offset: float) -> float:
    """The foundation's spring from a plate's kp [kN/m]: kp B/Bp in cohesive soil, kp ((B +
    o)/(Bp + o))² in cohesionless soil; B and Bp in m."""
    if cohesive:
        return kp * b / bp
    return kp * ((b + offset) / (bp + offset)) ** 2


def subgrade_stiffness(ks: float, area: float) -> float:
    """k = ks A [kN/m]."""
    return ks * area


def resonance_stiffness(fn: float, mass: float) -> float:
    """k = 4π² fn² m [kN/m] of a resonance test at fn [Hz] with a vibrator of m [t]."""
    return 4 * math.pi**2 * fn**2 * mass


def damping_from_decrement(delta: float, form: str = "exact") -> float:
    """D of a logarithmic decrement δ: exact δ / √(4π² + δ²), else δ / 2π."""
    if form == "exact":
        return delta / math.sqrt(4 * math.pi**2 + delta**2)
    return delta / (2 * math.pi)


def damping_from_hysteresis(lost: float, done: float, divisor: float) -> float:
    """D = ΔW / (divisor × W)."""
    return lost / (divisor * done)


def natural_frequency(k: float, m: float) -> float:
    """fn = √(k/m) / 2π [Hz], k in kN/m and m in t."""
    return math.sqrt(k / m) / (2 * math.pi)


def magnification(r: float, d: float) -> float:
    """1 / √((1 - r²)² + (2 D r)²) of a damped single degree of freedom."""
    return 1 / math.sqrt((1 - r**2) ** 2 + (2 * d * r) ** 2)


def speed_class(found: Any, rpm: float) -> Any:
    for row in found.speedClasses:
        if row.upTo is None or rpm < row.upTo or (row.inclusive and rpm == row.upTo):
            return row
    return found.speedClasses[-1]


def permissible(found: Any, rpm: float, direction: str) -> float | None:
    """The pack's permissible amplitude [mm] at ``rpm`` (the low end of a range), else None."""
    for row in found.amplitudes:
        if rpm < row.upTo or (row.inclusive and rpm == row.upTo):
            return float(getattr(row, direction)[0])
    return None


# ─────────────────────────────────────── the checks ───────────────────────────────────────


@dataclass
class MachineSoil:
    """What the checks read from the soil: E [MPa], ks [kN/m³], the soil at the base, the
    ground water below the base [m], qa [kPa] (net of ``overburden``)."""

    E: float | None = None
    E_source: str = ""
    ks: float | None = None
    ks_source: str = ""
    cohesive: bool | None = None
    water_below_base: float | None = None
    water_source: str = ""
    qa: float | None = None
    qa_note: str = ""
    overburden: float | None = None
    borehole: str | None = None
    notes: list[str] = field(default_factory=list)


def _springs(spec: Any, soil: MachineSoil, found: Any) -> tuple[list[tuple[float, str]], str]:
    """The vertical springs [(k kN/m, how)] of the method chosen, and why there are none."""
    b, l_ = spec.width / 1e3, spec.length / 1e3
    area = b * l_
    method = spec.stiffnessMethod
    if method == "given":
        if spec.stiffness is None:
            return [], "enter the spring k"
        return [(spec.stiffness, f"k = {spec.stiffness:.0f} kN/m given")], ""
    if method == "barkan":
        if spec.E is not None:
            e, how = spec.E, f"E = {spec.E:g} MPa from a laboratory test"
        elif spec.G is not None:
            e = 2 * spec.G * (1 + spec.poisson)
            how = f"E = 2G(1 + μ) = 2 × {spec.G:g} × {1 + spec.poisson:g} = {e:.1f} MPa"
        elif soil.E is not None:
            e, how = soil.E, f"E = {soil.E:.1f} MPa, {soil.E_source}"
        else:
            return [], "no E: enter E or G, or the soil report's layers under the base"
        springs = []
        for form in found.barkanPoisson:
            k = barkan_stiffness(e * 1e3, spec.poisson, area, found.barkanCoefficient, form)
            denominator = "1 - μ" if form == "linear" else "1 - μ²"
            springs.append(
                (
                    k,
                    (
                        f"k = {found.barkanCoefficient:g} E √A / ({denominator}) = {k:.0f} kN/m "
                        f"({how}, μ = {spec.poisson:g}, A = {area:.2f} m²)"
                    ),
                )
            )
        return springs, ""
    if method == "subgrade":
        if spec.ks is not None:
            ks, how = spec.ks, "given"
        elif soil.ks is not None:
            ks, how = soil.ks, soil.ks_source
        else:
            return [], "no ks: enter it, or the soil report's subgrade modulus"
        k = subgrade_stiffness(ks, area)
        return [(k, f"k = ks A = {ks:.0f} × {area:.2f} = {k:.0f} kN/m (ks {how})")], ""
    if method == "plateLoad":
        if spec.plateStiffness is None or spec.plateWidth is None:
            return [], "enter the plate's stiffness kp and width Bp"
        cohesive = spec.cohesive if spec.cohesive is not None else soil.cohesive
        if cohesive is None:
            return [], "say whether the soil at the base is cohesive"
        bp = spec.plateWidth / 1e3
        k = plate_stiffness(spec.plateStiffness, b, bp, cohesive, found.plateOffset)
        form = (
            "kp B / Bp"
            if cohesive
            else f"kp ((B + {found.plateOffset:g}) / (Bp + {found.plateOffset:g}))²"
        )
        return [(k, f"k = {form} = {k:.0f} kN/m (B = {b:g} m, Bp = {bp:g} m)")], ""
    if method == "resonance":
        if spec.testFrequency is None or spec.testMass is None:
            return [], "enter the test's resonance frequency and vibrator mass"
        k = resonance_stiffness(spec.testFrequency, spec.testMass)
        return [
            (
                k,
                (
                    f"k = 4π² fn² m = {k:.0f} kN/m (fn = {spec.testFrequency:g} Hz, m = "
                    f"{spec.testMass:g} t)"
                ),
            )
        ], ""
    return [], f"unknown spring method '{method}'"


def _damping(spec: Any, found: Any) -> tuple[float, str]:
    if spec.damping is not None:
        return spec.damping, f"D = {spec.damping:g} given"
    if spec.decrement is not None:
        d = damping_from_decrement(spec.decrement, found.decrement)
        return d, _cite(f"D = {d:.3f} from δ = {spec.decrement:g}", "decrement")
    if spec.workLost is not None and spec.workDone is not None:
        d = damping_from_hysteresis(spec.workLost, spec.workDone, found.hysteresisDivisor)
        return d, _cite(
            f"D = ΔW / ({found.hysteresisDivisor:.3f} W) = {d:.3f}", "hysteresisDivisor"
        )
    low = float(found.damping[0])
    return low, _cite(
        f"D = {low:g}, the low end of the soils' range (larger amplitudes)", "damping"
    )


def _force(spec: Any, omega: float, omega_operating: float) -> float | None:
    """The vertical unbalanced force [kN] at ω [rad/s]: m·e·ω², else the given force scaled
    by (ω/ωop)² (a rotating unbalance), None without either."""
    if spec.unbalance is not None:
        return spec.unbalance * omega**2 / 1e3
    if spec.force is not None:
        return spec.force * (omega / omega_operating) ** 2
    return None


def machine_checks(spec: Any, soil: MachineSoil, block_mass: float) -> dict[str, Any]:
    """The checks of a machine foundation ``spec`` on ``soil`` with its block of ``block_mass``
    [t]: ``{"checks", "requirements", "dynamics"}``. Raises ``LookupError`` when the pack does
    not cover machine foundations."""
    found = rules()
    if found is None or found.method != "lumpedSdof":
        raise LookupError(not_covered("Machine foundations"))
    checks: list[dict[str, Any]] = []
    needs: list[str] = []
    b, l_ = min(spec.width, spec.length) / 1e3, max(spec.width, spec.length) / 1e3
    area = b * l_
    mf = spec.machineMass + block_mass
    dead = mf * GRAVITY

    # Impact rule.
    ratio = (spec.impactLoad or 0.0) / dead if dead > 0 else 0.0
    impact = (
        spec.kind == "impact"
        or spec.movingEquipment
        or spec.looseGranular
        or ratio > found.impactRatio
    )
    if impact:
        why = []
        if spec.kind == "impact":
            why.append("an impact machine")
        if spec.movingEquipment:
            why.append("cranes or moving equipment")
        if spec.looseGranular:
            why.append("loose granular soil")
        if ratio > found.impactRatio:
            why.append(f"impact live load {ratio:.0%} of the dead load")
        needs.append(_cite(f"Impact forces designed for ({', '.join(why)})", "impactRatio"))
    if spec.form in ("wall", "frame"):
        needs.append(
            f"A {spec.form} foundation is taken as a rigid block on the soil: the flexibility "
            "of its walls or frame is not in the check."
        )

    # Mass, springs, damping.
    if spec.participatingMass is not None:
        shares = [spec.participatingMass]
        mass_note = f"ms / mf = {spec.participatingMass:g} given"
    else:
        shares = sorted({float(found.participatingMass[0]), float(found.participatingMass[1])})
        mass_note = _cite(
            f"ms / mf from {shares[0]:g} to {shares[-1]:g}, both checked", "participatingMass"
        )
    masses = [mf * (1 + s) for s in shares]
    springs, missing = _springs(spec, soil, found)
    d, d_note = _damping(spec, found)
    low, high = found.damping
    if not low <= d <= high:
        needs.append(_cite(f"D = {d:.3f} is outside the soils' usual {low:g}-{high:g}", "damping"))
    rpm = spec.speed
    f_op = rpm / 60
    omega = 2 * math.pi * f_op
    klass = speed_class(found, rpm)
    dynamics: dict[str, Any] = {
        "mass": [round(m, 2) for m in masses],
        "massNote": mass_note,
        "springs": [{"k": round(k), "note": n} for k, n in springs],
        "damping": round(d, 4),
        "dampingNote": d_note,
        "speedClass": klass.name,
        "operatingFrequency": round(f_op, 2),
    }
    if not springs:
        checks.append(_rule("Soil spring", False, f"no vertical spring: {missing}", flag=True))
    else:
        combos = [(k, m) for k, _ in springs for m in masses]
        fns = [natural_frequency(k, m) for k, m in combos]
        ratios = [f_op / fn for fn in fns]
        dynamics["naturalFrequency"] = [round(min(fns), 2), round(max(fns), 2)]
        dynamics["frequencyRatio"] = [round(min(ratios), 3), round(max(ratios), 3)]
        checks.append(
            _resonance("Resonance (vertical)", found, klass, min(ratios), max(ratios), rpm)
        )
        limit, limit_note = _limit(spec, found, rpm, "vertical")
        if spec.kind == "impact":
            if spec.impulse is None:
                checks.append(
                    _rule("Amplitude under a blow", False, "enter the impulse of one blow", True)
                )
            else:
                amp = max(
                    spec.impulse / (m * 2 * math.pi * natural_frequency(k, m)) * 1e3
                    for k, m in combos
                )
                dynamics["amplitude"] = round(amp, 3)
                checks.append(
                    _check(
                        "Amplitude under a blow",
                        amp,
                        limit,
                        "mm",
                        None,
                        f"A = I / (m ωn) = {amp:.3f} mm, I = {spec.impulse:g} kN·s; " + limit_note,
                    )
                )
        else:
            checks += _amplitudes(
                spec, combos, ratios, d, omega, rpm, limit, limit_note, found, klass
            )
        needs.append(
            "Vibrations to be kept from annoying people and from harming other structures; the "
            + _cite("frequency-amplitude limit charts are a guide", "vibration")
        )

    # Horizontal mode.
    if spec.horizontalStiffness is not None:
        k = spec.horizontalStiffness
        ratios_h = [f_op / natural_frequency(k, m) for m in masses]
        checks.append(
            _resonance("Resonance (horizontal)", found, klass, min(ratios_h), max(ratios_h), rpm)
        )
        force = spec.horizontalForce
        if force is None and spec.unbalance is not None:
            force = spec.unbalance * omega**2 / 1e3
        if force is not None:
            limit, limit_note = _limit(spec, found, rpm, "horizontal")
            amp = max(force / k * magnification(r, d) * 1e3 for r in ratios_h)
            checks.append(
                _check(
                    "Amplitude (horizontal)",
                    amp,
                    limit,
                    "mm",
                    None,
                    f"A = F/k × M = {amp:.3f} mm (F = {force:.2f} kN, k = {k:.0f} kN/m); "
                    + limit_note,
                    flag=limit == math.inf,
                )
            )
    else:
        needs.append(
            "Horizontal mode not checked: the code's methods give the vertical spring; enter the "
            "horizontal spring and force to check it."
        )

    # Static pressure.
    gross = dead / area
    net = gross - (soil.overburden or 0.0)
    if soil.qa:
        allowed = found.staticPressure * soil.qa
        checks.append(
            _check(
                "Static soil pressure",
                net,
                allowed,
                "kPa",
                None,
                _cite(
                    f"(machine + block) {dead:.0f} kN on {area:.2f} m²"
                    + (f" less the overburden {soil.overburden:.0f} kPa" if soil.overburden else "")
                    + f" ≤ {found.staticPressure:g} × qa {soil.qa:.0f} kPa; {soil.qa_note}",
                    "staticPressure",
                ),
            )
        )
    else:
        checks.append(
            _rule(
                "Static soil pressure",
                False,
                f"no qa: {soil.qa_note or 'enter the soil report or the qa override'}",
                flag=True,
            )
        )

    # Eccentricity.
    dx, dy = spec.machineOffset or (0.0, 0.0)
    ex = abs(spec.machineMass * dx / mf) / spec.length
    ey = abs(spec.machineMass * dy / mf) / spec.width
    worst = max(ex, ey)
    checks.append(
        _check(
            "Eccentricity",
            worst * 100,
            found.eccentricity * 100,
            "%",
            None,
            _cite(
                f"centre of gravity off the base's centroid by {ex:.1%} of L, {ey:.1%} of B",
                "eccentricity",
            ),
        )
    )

    # Ground water.
    need = found.waterDepth * b
    if soil.water_below_base is None:
        checks.append(
            _rule(
                "Ground water below the base",
                False,
                f"water table not known; it must be at least {need:.2f} m below the base",
                flag=True,
            )
        )
    else:
        have = soil.water_below_base
        checks.append(
            _check(
                "Ground water below the base",
                need,
                max(have, 0.0),
                "m",
                None,
                _cite(
                    f"{have:.2f} m below the base ({soil.water_source}), at least "
                    f"{found.waterDepth:g} × B = {need:.2f} m",
                    "waterDepth",
                ),
            )
        )

    # Adjacent building.
    if spec.adjacentFoundingLevel is not None:
        lower = spec.foundingLevel < spec.adjacentFoundingLevel
        checks.append(
            _rule(
                "Below the adjacent foundations",
                lower,
                _cite(
                    f"base at {spec.foundingLevel / 1e3:.2f} m, adjacent foundations at "
                    f"{spec.adjacentFoundingLevel / 1e3:.2f} m",
                    "separation",
                ),
            )
        )
    checks.append(
        _rule(
            "Separated from the building",
            spec.separated,
            _cite("separated from the adjacent foundations", "separation"),
        )
    )
    return {"checks": checks, "requirements": needs, "dynamics": dynamics}


def _limit(spec: Any, found: Any, rpm: float, direction: str) -> tuple[float, str]:
    """The permissible amplitude [mm] and where it comes from (inf: none known)."""
    if spec.allowableAmplitude is not None:
        return spec.allowableAmplitude, f"the maker's {spec.allowableAmplitude:g} mm"
    if spec.kind == "impact":
        return float(found.hammerAmplitude), _cite(
            f"hammer {found.hammerAmplitude:g} mm", "hammerAmplitude"
        )
    value = permissible(found, rpm, direction)
    if value is None:
        return math.inf, f"no permissible amplitude at {rpm:g} rpm: enter the maker's"
    return value, _cite(f"permissible {value:g} mm at {rpm:g} rpm", "amplitudes")


def _resonance(
    name: str, found: Any, klass: Any, r_min: float, r_max: float, rpm: float
) -> dict[str, Any]:
    below, above = found.frequencyRatioBelow, found.frequencyRatioAbove
    options = []
    if "below" in klass.allowed:
        options.append((r_max / below, f"f/fn ≤ {r_max:.3f} < {below:g}", r_max < below))
    if "above" in klass.allowed:
        options.append((above / r_min, f"f/fn ≥ {r_min:.3f} ≥ {above:g}", r_min >= above))
    passing = [o for o in options if o[2]]
    utilisation, text, _ = min(passing or options, key=lambda o: o[0])
    if not passing:
        text = f"f/fn from {r_min:.3f} to {r_max:.3f} within the band"
        utilisation = max(utilisation, 1.001)
    sides = " or ".join(
        f"below {below:g}" if s == "below" else f"at least {above:g}" for s in klass.allowed
    )
    key = "frequencyRatioBelow" if klass.allowed == ["below"] else "frequencyRatioAbove"
    note = _cite(f"{klass.name} ({rpm:g} rpm): {text}; f/fn {sides}", key)
    return _check(name, utilisation, 1.0, "", None, note, utilisation=utilisation)


def _amplitudes(
    spec: Any,
    combos: list[tuple[float, float]],
    ratios: list[float],
    d: float,
    omega: float,
    rpm: float,
    limit: float,
    limit_note: str,
    found: Any,
    klass: Any,
) -> list[dict[str, Any]]:
    checks = []
    if spec.force is None and spec.unbalance is None:
        return [
            _rule(
                "Amplitude (vertical)",
                False,
                "enter the unbalanced force or the rotating unbalance m·e",
                flag=True,
            )
        ]
    force = _force(spec, omega, omega) or 0.0
    amp = max(force / k * magnification(r, d) * 1e3 for (k, _), r in zip(combos, ratios))
    checks.append(
        _check(
            "Amplitude (vertical)",
            amp,
            limit,
            "mm",
            None,
            f"A = F/k × 1/√((1 - r²)² + (2Dr)²) = {amp:.4f} mm (F = {force:.2f} kN, D = {d:.3f});"
            f" {limit_note}",
            flag=limit == math.inf,
        )
    )
    # A soft foundation passes through resonance while starting and stopping.
    if min(ratios) >= found.frequencyRatioAbove and "above" in klass.allowed:
        worst, at = 0.0, 0.0
        for k, m in combos:
            wn = 2 * math.pi * natural_frequency(k, m)
            f = _force(spec, wn, omega) or 0.0
            a = f / k / (2 * d) * 1e3
            if a > worst:
                worst, at = a, wn * 60 / (2 * math.pi)
        rlimit, rnote = _limit(spec, found, at, "vertical")
        checks.append(
            _check(
                "Amplitude at resonance (starting)",
                worst,
                rlimit,
                "mm",
                None,
                _cite(
                    f"A = F/(2Dk) = {worst:.4f} mm at {at:.0f} rpm"
                    + ("" if spec.unbalance is not None else ", the force scaled by (ωn/ω)²")
                    + f"; {rnote}",
                    "frequencyRatioAbove",
                ),
                flag=rlimit == math.inf,
            )
        )
    return checks


# ─────────────────────────────────────── the project ───────────────────────────────────────


def _soil(ctx: Any, spec: Any) -> MachineSoil:
    """E, ks, the soil and the ground water at the base from 1 Soil Report and qa."""
    from saengine.substructure.piles import profiles_of

    soil = MachineSoil()
    x, y = spec.center or (0.0, 0.0)
    b, l_ = min(spec.width, spec.length), max(spec.width, spec.length)
    bearing = ctx.soil.at(x, y, spec.foundingLevel, b, l_, owner=spec.id)
    soil.qa, soil.qa_note, soil.overburden = bearing.qa, bearing.note, bearing.overburden
    profiles = profiles_of(ctx.soil_text)[0]
    water = spec.designWaterTable
    if water is None:
        water = ctx.substructure.earthPressure.designWaterTable
    ground = ctx.ground_level
    if profiles:
        profile = min(profiles, key=lambda p: math.hypot(p.x * 1e3 - x, p.y * 1e3 - y))
        soil.borehole = profile.id
        ground = profile.ground_level * 1e3
        df = max((ground - spec.foundingLevel) / 1e3, 0.0)
        bottom = df + b / 1e3
        weighted, depth = 0.0, 0.0
        for layer in profile.layers:
            top, end = max(layer.top, df), min(layer.bottom, bottom)
            if end > top and layer.E is not None:
                weighted += layer.E * (end - top)
                depth += end - top
        if depth > 0:
            soil.E = weighted / depth
            soil.E_source = (
                f"the mean of 1 Soil Report's layers {df:.1f}-{bottom:.1f} m at {profile.id}"
            )
        here = profile.layer_at(df) if hasattr(profile, "layer_at") else None
        if here is not None:
            soil.cohesive = here.behaviour == "cohesive"
        ks = _report_ks(profile)
        if ks is not None:
            soil.ks = ks
            soil.ks_source = f"1 Soil Report at {profile.id}"
        if water is None and profile.water_table is not None:
            water = profile.water_table
            soil.water_source = f"the water table of {profile.id}"
    if water is not None:
        soil.water_below_base = water - (ground - spec.foundingLevel) / 1e3
        soil.water_source = soil.water_source or "the design water table"
    return soil


def _report_ks(profile: Any) -> float | None:
    """The soil report's ks [kN/m³] of a borehole (its subgrade footing)."""
    from saengine.soil import bearing, piles

    design = profile.design
    try:
        reference = bearing.allowable(
            profile,
            design.subgradeWidth / 1e3,
            design.subgradeWidth / 1e3,
            design.subgradeDepth / 1e3,
        )
        value = piles.subgrade_modulus(profile, reference["qa"])["value"]
    except Exception:  # noqa: BLE001 - the soil report's own errors are reported there
        return None
    return float(value) if value else None


def _block_mass(ctx: Any, spec: Any) -> float:
    """The block's mass [t]: given, else its volume × the concrete's density."""
    from saengine.library.materials import Category, default_of
    from saengine.substructure.context import Skip

    if spec.blockMass is not None:
        return spec.blockMass
    material_id = spec.material or default_of(ctx.materials, Category.CONCRETE)
    material = ctx.mats.get(material_id) if material_id else None
    density = getattr(getattr(material, "mechanical", None), "density", None)
    if not density:
        raise Skip("no concrete density: choose the concrete or enter the block mass")
    volume = spec.length * spec.width * spec.height / 1e9
    return volume * density / 1e3


def design_machine_foundations(
    ctx: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """The machine foundations of the substructure in the report's format, the skipped ones
    and notes."""
    from saengine.substructure.context import Skip

    specs = ctx.substructure.machineFoundations
    if not specs:
        return [], [], []
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    if rules() is None:
        reason = not_covered("Machine foundations")
        return [], [{"id": s.id, "type": "machineFoundation", "reason": reason} for s in specs], []
    for spec in specs:
        try:
            mass = _block_mass(ctx, spec)
            soil = _soil(ctx, spec)
            found = machine_checks(spec, soil, mass)
        except (Skip, LookupError) as reason:
            skipped.append({"id": spec.id, "type": "machineFoundation", "reason": str(reason)})
            continue
        checks = found["checks"]
        counted = [c for c in checks if not c["flag"]]
        results.append(
            {
                "id": spec.id,
                "type": "machineFoundation",
                "columns": [],
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in counted), default=0.0),
                "ok": all(c["ok"] for c in counted),
                "sizes": {
                    "L": round(spec.length),
                    "B": round(spec.width),
                    "H": round(spec.height),
                    "blockMass": round(mass, 2),
                },
                "dynamics": found["dynamics"],
                "requirements": found["requirements"],
                "borehole": soil.borehole,
            }
        )
        notes += [f"{spec.id}: {n}" for n in found["requirements"]]
    return results, skipped, notes
