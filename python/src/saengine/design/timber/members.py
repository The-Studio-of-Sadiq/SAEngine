"""Sawn timber beams, columns and braces to BNBC 2020 Part 6 Chapter 11 (permissible stress
design, as IS 883 gives it).

The member's forces are the allowable stress (service level) combinations of the code pack
(``combinations.allowable``, BNBC 2020 Part 6 Sec 2.7.3.2) formed from the analysis's load
cases, not the strength combinations. Per member, at every station of every combination:

- bending about both axes, f = M / Z against Fb, times the depth factor K3 for beams deeper
  than 300 mm (IS 883 Sec 6.2.1.3);
- horizontal shear H = 3V / (2 b d) against Fv (Sec 6.2.1.4), each axis;
- axial tension f = T / A against Ft, axial compression against Fc of the column's slenderness
  Le/d (short, intermediate or long, Sec 7.3, with Le/d ≤ 50);
- combined: f/F (axial) + fbx/Fbx + fby/Fby ≤ 1, linear (on the safe side of the IS 883
  interaction with the Euler term);
- the stresses one third higher in combinations with wind or earthquake (Sec 5.3).

Le is the member's length between its analysis ends (both ends held; no bracing in between
taken), the least dimension of the section its d. Not checked: deflection (span/240), bearing
across the grain at supports, notches and holes, and connections (planned).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.ductile_members import _row

CODE = "BNBC 2020 Part 6 Chapter 11 (permissible stress design; IS 883:1994 provisions)"
CLAUSE = "BNBC 2020 Part 6 Ch 11"

METHOD = [
    (
        f"Timber members: permissible stresses to {CODE}, under the allowable stress "
        "combinations (BNBC 2020 Part 6 Sec 2.7.3.2) formed from the analysis's load cases. "
        "Rectangular sawn sections of the strength group and location of their material; "
        "bending with the depth factor K3 over 300 mm, horizontal shear 3V/(2bd), tension, "
        "compression by Le/d (short ≤ 11, intermediate with K8 = 0.702 √(E/Fc), long 0.329 "
        "E/(Le/d)², Le/d ≤ 50), combined stresses linearly; one third more with wind or "
        "earthquake. Le is the member length (no intermediate bracing); deflection, bearing "
        "across the grain and connections are not checked."
    )
]

LOCATIONS = ("inside", "outside", "wet")


class TimberDesignError(ValueError):
    """A timber member that cannot be checked (not a rectangle, no group ...)."""


def _table() -> Any:
    return code_context.pack_table("timber")


def is_timber(material: Any) -> bool:
    """Whether members of ``material`` are designed as timber."""
    category = getattr(getattr(material, "category", None), "value", None)
    return category == "timber" and getattr(material, "timber", None) is not None


# ─────────────────────────────────────── stresses ───────────────────────────────────────


@dataclass(frozen=True)
class Timber:
    """Permissible stresses of a strength group at a location [MPa]."""

    group: str
    location: str
    e: float
    fb: float
    ft: float
    fv: float
    fc: float
    fcp: float

    @classmethod
    def of(cls, group: str, location: str = "inside", e: float | None = None) -> Timber:
        groups = _table().groups
        if group not in groups:
            raise TimberDesignError(f"unknown strength group '{group}'")
        if location not in LOCATIONS:
            raise TimberDesignError(f"unknown location '{location}'")
        g = groups[group]
        return cls(
            group,
            location,
            float(e or g.E),
            float(g.bending[location]),
            float(g.tension[location]),
            float(g.shearHorizontal),
            float(g.compressionParallel[location]),
            float(g.compressionPerpendicular[location]),
        )

    @classmethod
    def of_material(cls, material: Any) -> Timber:
        props = getattr(material, "timber", None)
        if props is None:
            raise TimberDesignError(f"'{getattr(material, 'id', '?')}' is not a timber material")
        return cls.of(props.group, props.location, getattr(material.mechanical, "E", None))


def depth_factor(d: float) -> float:
    """K3 of a beam of depth ``d`` [mm]: 1 up to 300 mm, 0.81 (d² + 89400) / (d² + 55000)
    above (IS 883 Sec 6.2.1.3)."""
    f = _table().depthFactor
    if d <= float(f.above):
        return 1.0
    return float(f.factor) * (d * d + float(f.a)) / (d * d + float(f.b))


def compression_stress(fc: float, e: float, slenderness: float) -> tuple[float, str]:
    """(permissible compression parallel to the grain [MPa], "short" | "intermediate" |
    "long") at Le/d = ``slenderness`` (IS 883 Sec 7.3)."""
    c = _table().column
    k8 = float(c.k8) * math.sqrt(e / fc)
    if slenderness <= float(c.short):
        return fc, "short"
    if slenderness < k8:
        return fc * (1.0 - (slenderness / k8) ** 4 / float(c.intermediate)), "intermediate"
    return float(c.long) * e / slenderness**2, "long"


def duration_factor(lateral: bool, earthquake: bool = False) -> float:
    """1 for gravity, 4/3 with wind or earthquake (IS 883 Sec 5.3)."""
    d = _table().duration
    if not lateral:
        return float(d.permanent)
    return float(d.earthquake if earthquake else d.wind)


# ─────────────────────────────────────── the member ───────────────────────────────────────


@dataclass(frozen=True)
class Section:
    """A rectangular sawn section: ``b`` across (xDim) and ``d`` deep (yDim) [mm]."""

    b: float
    d: float

    @classmethod
    def of(cls, profile: Any) -> Section:
        if getattr(profile, "shape", None) != "rectangle":
            raise TimberDesignError("timber members are designed as rectangular sawn sections")
        return cls(float(profile.xDim), float(profile.yDim))

    @property
    def area(self) -> float:
        return self.b * self.d

    @property
    def zx(self) -> float:
        """About the width axis (bending in the depth) [mm³]."""
        return self.b * self.d**2 / 6

    @property
    def zy(self) -> float:
        return self.d * self.b**2 / 6

    @property
    def least(self) -> float:
        return min(self.b, self.d)


def check_member(
    section: Section,
    timber: Timber,
    stations: Sequence[Any],
    length: float,
    lateral: dict[str, str],
    kind: str = "beam",
) -> list[dict[str, Any]]:
    """The checks of a member (see the module notes): ``stations`` per combination
    (:class:`saengine.design.steel.members.Stations`: P compression positive [N], Mx, My
    [N·mm], Vy, Vx [N]); ``length`` [mm]; ``lateral``: per combination name "wind" or
    "earthquake" when it has lateral loads."""
    table = _table()
    slenderness = length / section.least
    fca, column = compression_stress(timber.fc, timber.e, slenderness)
    k3 = depth_factor(section.d)
    fbx = timber.fb * k3
    fby = timber.fb * depth_factor(section.b)
    rows: dict[str, dict[str, Any]] = {}

    def offer(key: str, row: dict[str, Any]) -> None:
        if key not in rows or row["utilisation"] > rows[key]["utilisation"]:
            rows[key] = row

    for st in stations:
        name = st.combination
        what = lateral.get(name)
        k = duration_factor(what is not None, what == "earthquake")
        tag = f"; stresses x {k:.2f} ({what})" if what else ""
        for i in range(len(st.s)):
            where = st.where[i] if i < len(st.where) else ""
            p = float(st.P[i])
            mx, my = abs(float(st.Mx[i])), abs(float(st.My[i]))
            vy, vx = abs(float(st.Vy[i])), abs(float(st.Vx[i]))
            sx, sy = mx / section.zx, my / section.zy
            offer(
                "bx",
                _row(
                    f"Bending fb = M/Z about the width axis ({CLAUSE}; IS 883 Sec 6.2.1)",
                    sx,
                    k * fbx,
                    "MPa",
                    name,
                    f"{where}; K3 = {k3:.3f}{tag}",
                ),
            )
            offer(
                "by",
                _row(
                    f"Bending fb = M/Z about the depth axis ({CLAUSE}; IS 883 Sec 6.2.1)",
                    sy,
                    k * fby,
                    "MPa",
                    name,
                    f"{where}{tag}",
                ),
            )
            offer(
                "v",
                _row(
                    f"Horizontal shear H = 3V/(2bd) ({CLAUSE}; IS 883 Sec 6.2.1.4)",
                    1.5 * max(vy, vx) / section.area,
                    k * timber.fv,
                    "MPa",
                    name,
                    f"{where}{tag}",
                ),
            )
            fa = abs(p) / section.area
            if p >= 0:  # compression
                axial_capacity = k * fca
                offer(
                    "c",
                    _row(
                        f"Compression parallel to the grain, {column} column (Le/d = "
                        f"{slenderness:.1f}) ({CLAUSE}; IS 883 Sec 7.3)",
                        fa,
                        axial_capacity,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
            else:
                axial_capacity = k * timber.ft
                offer(
                    "t",
                    _row(
                        f"Tension parallel to the grain ({CLAUSE}; IS 883 Sec 6.3)",
                        fa,
                        axial_capacity,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
            combined = (
                fa / axial_capacity + sx / (k * fbx) + sy / (k * fby)
                if axial_capacity > 0
                else math.inf
            )
            offer(
                "m",
                _row(
                    f"Combined axial and bending f/F + fbx/Fbx + fby/Fby ({CLAUSE}; IS 883 Sec "
                    "7.5)",
                    combined,
                    1.0,
                    "",
                    name,
                    f"{where}{tag}",
                    utilisation=combined,
                ),
            )
    out = [rows[k] for k in ("bx", "by", "v", "t", "c", "m") if k in rows]
    if kind in ("column", "brace") or "c" in rows:
        out.append(
            _row(
                f"Slenderness Le/d ≤ {float(table.column.maxSlenderness):g} ({CLAUSE}; IS 883 "
                "Sec 7.3)",
                slenderness,
                float(table.column.maxSlenderness),
                "",
                note=f"Le = {length:.0f} mm (the member length), d = {section.least:.0f} mm",
            )
        )
    return out


def lateral_kinds(factors: Sequence[dict[str, float]], names: Sequence[str]) -> dict[str, str]:
    """Per combination name, "earthquake" or "wind" when its factors have such a case."""
    out: dict[str, str] = {}
    for name, f in zip(names, factors, strict=True):
        cases = {c for c, v in f.items() if v}
        if any(c.startswith("E") for c in cases):
            out[name] = "earthquake"
        elif any(c.startswith("W") for c in cases):
            out[name] = "wind"
    return out


def design_timber_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    lateral: dict[str, str],
    turned: bool = False,
) -> dict[str, Any]:
    """The design report entry of one timber beam, column or brace: ``{id, kind, type,
    members, checks, utilisation, ok, material, timber}``. ``pieces``: its analysis elements
    with the allowable stress combinations' forces. Raises :class:`TimberDesignError`."""
    from saengine.design.steel.lengths import positions
    from saengine.design.steel.members import member_stations

    if not pieces:
        raise TimberDesignError("not in the analysis results")
    section = Section.of(object_type.profile)
    timber = Timber.of_material(material)
    s, _ = positions(pieces, 2)
    length = float(s[-1] - s[0]) * 1000.0
    stations = member_stations(pieces, combinations, turned)
    checks = check_member(section, timber, stations, length, lateral, kind)
    strength = [c for c in checks if not c["flag"]]
    return {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        # Not "section": the workbench reads a "section" with a label as a steel member's.
        "timber": {
            "label": f"{section.b:g} x {section.d:g} sawn timber",
            "group": timber.group,
            "location": timber.location,
            "E": timber.e,
            "stresses": {
                "Fb": timber.fb,
                "Ft": timber.ft,
                "Fv": timber.fv,
                "Fc": timber.fc,
                "Fcp": timber.fcp,
            },
            "length": round(length, 0),
        },
    }


def asd_pieces(
    pieces: Sequence[Any], case_forces: dict[str, dict[int, np.ndarray]], factors: Sequence[dict]
) -> list[Any]:
    """Copies of ``pieces`` whose forces are the combinations ``factors`` ({case: factor})
    of the analysis's per-case forces ``case_forces`` ({case: {element id: (stations, 6)}});
    a case without forces counts nothing."""
    from dataclasses import replace

    out = []
    for p in pieces:
        forces = []
        for f in factors:
            total = None
            for case, value in f.items():
                rows = case_forces.get(case, {}).get(p.id)
                if rows is None or not value:
                    continue
                part = value * np.asarray(rows, dtype=float)
                total = part if total is None else total + part
            if total is None:
                total = np.zeros_like(np.asarray(p.forces[0], dtype=float))
            forces.append(total)
        out.append(replace(p, forces=forces, sway=None, sustained=None, live=None))
    return out


#: The load cases each factor of a pack combination stands for (W and E expand by direction).
_CASES = {"D": ("D", "SD"), "L": ("L",), "Lr": ("Lr",), "F": ("F",), "H": ("H",), "T": ("T",)}


def allowable_combinations() -> list[tuple[str, dict[str, float]]]:
    """The code pack's allowable stress combinations (``combinations.allowable``, BNBC 2020
    Part 6 Sec 2.7.3.2) as ``(name, {case: factor})``, wind and earthquake in ±X and ±Y."""
    table = code_context.pack_table("combinations")
    out: list[tuple[str, dict[str, float]]] = []
    for c in getattr(table, "allowable", None) or []:
        factors = dict(c.factors)
        base: dict[str, float] = {}
        for key, value in factors.items():
            for case in _CASES.get(key, ()):
                base[case] = value
        lateral = next((k for k in ("W", "E") if k in factors), None)
        if lateral is None:
            out.append((c.name, base))
            continue
        for axis in ("X", "Y"):
            for sign in (1, -1):
                label = (
                    c.name.replace(lateral, f"{lateral}{axis}", 1)
                    if sign > 0
                    else c.name.replace(lateral, f"(-{lateral}{axis})", 1)
                )
                out.append((label, {**base, f"{lateral}{axis}": sign * factors[lateral]}))
    return out
