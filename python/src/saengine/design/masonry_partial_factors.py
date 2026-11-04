"""Masonry walls by partial factors: the ``"partialFactors"`` method of the code pack's
``masonry`` table (alpha 9 C6; the Eurocodes pack: EN 1996-1-1). Every number is the pack's
``masonry.partialFactors``.

The forces are the wall piers' under the design (ultimate) combinations. Per pier:

- the characteristic compressive strength fk = K fb^α fm^β of the unit group (fb the unit's
  strength times the shape factor, at most the pack's limits; fm the mortar grade's strength,
  at most its limits), or the entered f'm when it comes from tests; fd = fk / γM;
- vertical load: NEd <= Φ t fd per length at the top and bottom (Φi = 1 - 2 ei / t, ei = M/N +
  einit >= 0.05 t, einit = hef / 450) and at mid-height (Φm of the slenderness, the eccentricity
  emk = em + ek with creep), hef = ρn h, hef / tef within the limit;
- in-plane shear: VEd <= fvd t lc, fvk = fvk0 + 0.4 σd <= the pack's share of fb, lc the
  compressed length of the in-plane bending (the whole length without tension);
- reinforced walls (vertical bars): the out-of-plane moment MRd = As fyd z, z = d (1 - 0.5 As
  fyd / (b d fd)) <= 0.95 d, the bars at mid-thickness (SAEngine practice).

Unit groups by the material's units (solid, hollow: the pack's ``groupOf``), the mortar
strength by the material's grade (the pack's mortar table) or the pack's default (on the safe
side), each stated in the notes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from saengine.design import masonry as M
from saengine.design import walls as W
from saengine.design.ductile_members import _row as _base_row
from saengine.design.rc import DesignError, bar_area

#: The combinations this method checks: the design (factored) combinations.
COMBINATIONS = "strength"


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    combination: str | None = None,
    clause: str = "",
    note: str = "",
) -> dict[str, Any]:
    row = _base_row(name, demand, capacity, unit, combination, note)
    row.setdefault("flag", False)
    row["clause"] = clause
    return row


def _p() -> Any:
    found = M.table().partialFactors
    if found is None:
        raise DesignError("the code pack's masonry table has no partial factors")
    return found


def _clause(key: str) -> str:
    return str(_p().clauses.get(key) or M.clause("chapter"))


def method_text() -> list[str]:
    p = _p()
    return [
        (
            f"Masonry walls by partial factors ({_clause('chapter')}): fk = K fb^α fm^β of the unit "
            f"group ({_clause('strength')}), fd = fk / γM, γM = {float(p.gammaM):g}, under the design "
            f"combinations; vertical load Φ t fd at the top, bottom and mid-height with the "
            f"eccentricities ({_clause('vertical')}), hef = ρn h, hef/tef <= "
            f"{float(p.slendernessMax):g}; in-plane shear fvd t lc, fvk = fvk0 + "
            f"{float(p.shearCompression):g} σd ({_clause('shear')}); reinforced walls MRd = As fyd z "
            f"({_clause('reinforced')})."
        )
    ]


def characteristic_strength(m: M.Masonry, notes: list[str]) -> tuple[float, float]:
    """(fk, fb) [MPa] of the masonry: the entered f'm from tests, else K fb^α fm^β."""
    p = _p()
    fb = float(m.unit_strength or 0.0) * float(p.shapeFactor)
    if m.fm_source == "entered" and m.fm > 0 and not m.unit_strength:
        notes.append(f"fk = {m.fm:g} MPa: the masonry strength entered (from tests)")
        return float(m.fm), fb or float(m.fm)
    if fb <= 0:
        raise DesignError("no unit strength: enter the units' strength on the masonry material")
    group = p.groupOf.get(m.units, next(iter(p.groupOf.values())))
    key = f"{m.kind}.{group}"
    if key not in p.unitGroups:
        raise DesignError(f"no K, α, β for {m.kind} units of group {group} in the code pack")
    g = p.unitGroups[key]
    mortars = M.table().mortars
    if m.mortar and m.mortar in mortars:
        fm = float(mortars[m.mortar].strength)
    else:
        fm = float(p.defaultMortar)
        notes.append(f"mortar grade not known: fm = {fm:g} MPa taken (the code pack's default)")
    fb_used = min(fb, float(p.fbMax))
    fm_used = min(fm, float(p.fmMax), float(p.fmShare) * fb_used)
    fk = float(g.K) * fb_used ** float(g.alpha) * fm_used ** float(g.beta)
    notes.append(
        f"fk = K fb^α fm^β = {float(g.K):g} × {fb_used:.1f}^{float(g.alpha):g} × "
        f"{fm_used:.1f}^{float(g.beta):g} = {fk:.2f} MPa ({m.kind} units, group {group}; "
        f"{_clause('strength')})"
    )
    return fk, fb_used


def capacity_reduction_end(e_i: float, t: float) -> float:
    return max(0.0, 1 - float(_p().endReduction) * e_i / t)


def capacity_reduction_middle(emk: float, t: float, hef: float, fk: float) -> float:
    """Φm of the mid-height (the code's annex): A1 e^(-u²/2)."""
    p = _p()
    e = float(p.elasticModulus) * fk
    lam = hef / t * math.sqrt(fk / e)
    a1 = 1 - 2 * emk / t
    if a1 <= 0:
        return 0.0
    u = (lam - 0.063) / (0.73 - 1.17 * emk / t)
    return max(0.0, a1 * math.exp(-(u**2) / 2))


def shear_strength(fvk0: float, sigma_d: float, fb: float) -> float:
    p = _p()
    return min(fvk0 + float(p.shearCompression) * max(sigma_d, 0.0), float(p.shearMax) * fb)


def _fvk0(m: M.Masonry) -> float:
    p = _p()
    rows = p.fvk0.get(m.kind) or next(iter(p.fvk0.values()))
    mortars = M.table().mortars
    fm = float(mortars[m.mortar].strength) if m.mortar in mortars else float(p.defaultMortar)
    value = float(rows[0][1])
    for start, v in rows:
        if fm >= start - 1e-9:
            value = float(v)
    return value


def wall_checks(
    geometry: W.WallGeometry,
    bars: W.WallBars | None,
    forces: list[W.PierForces],
    m: M.Masonry,
    fy: float = 500.0,
    lateral: Iterable[str] = (),
    storeys: int | None = None,
) -> M.MasonryDesign:
    """The checks of a masonry wall pier by partial factors (see the module notes); ``forces``
    under the design combinations, compression positive [N, N·mm]."""
    del lateral, storeys
    p = _p()
    notes: list[str] = list(m.notes)
    fk, fb = characteristic_strength(m, notes)
    gm = float(p.gammaM)
    fd = fk / gm
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    rho = float(p.restraint["braced" if geometry.braced else "unbraced"])
    hef = rho * h
    checks: list[dict[str, Any]] = []
    checks.append(
        _row(
            "Slenderness hef / tef",
            hef / t,
            float(p.slendernessMax),
            "",
            clause=_clause("slenderness"),
            note=f"hef = ρn h = {rho:g} × {h:.0f} mm",
        )
    )
    einit = hef / float(p.heightEccentricity)
    e_min = float(p.eccentricityMin) * t
    worst_v = worst_s = None
    fvk0 = _fvk0(m)
    for f in forces:
        n = max(f.P, 0.0)
        middle = f.where.endswith("middle")
        if n > 0:
            if middle:
                em = abs(f.M2) / n + einit
                ek = 0.0
                if hef / t > float(p.creepFrom):
                    ek = 0.002 * float(p.creep) * hef / t * math.sqrt(t * em)
                emk = max(em + ek, e_min)
                phi = capacity_reduction_middle(emk, t, hef, fk)
                how = f"Φm = {phi:.3f} (emk = {emk:.1f} mm, hef = {hef:.0f} mm)"
            else:
                ei = max(abs(f.M2) / n + einit, e_min)
                phi = capacity_reduction_end(ei, t)
                how = f"Φi = 1 - 2 ei/t = {phi:.3f} (ei = {ei:.1f} mm)"
            nrd = phi * t * lw * fd
            u = n / nrd if nrd > 0 else math.inf
            if worst_v is None or u > worst_v[0]:
                worst_v = (u, n, nrd, f, how)
        # in-plane shear on the compressed length
        e_in = abs(f.M3) / n if n > 0 else math.inf
        lc = lw if e_in <= lw / 6 else max(0.0, 3 * (lw / 2 - e_in))
        if abs(f.V2) > 0:
            sigma = n / (t * lc) if lc > 0 else 0.0
            fvd = shear_strength(fvk0, sigma, fb) / gm
            vrd = fvd * t * lc
            u = abs(f.V2) / vrd if vrd > 0 else math.inf
            if worst_s is None or u > worst_s[0]:
                worst_s = (u, abs(f.V2), vrd, f, f"fvd = {fvd:.3f} MPa, lc = {lc:.0f} mm")
    if worst_v is not None:
        u, n, nrd, f, how = worst_v
        checks.append(
            _row(
                "Vertical load NEd / NRd",
                n / 1e3,
                nrd / 1e3,
                "kN",
                combination=f.combination,
                clause=_clause("vertical"),
                note=f"{how}; fd = fk / γM = {fd:.2f} MPa; {f.where}",
            )
        )
    if worst_s is not None:
        u, v, vrd, f, how = worst_s
        checks.append(
            _row(
                "In-plane shear",
                v / 1e3,
                vrd / 1e3,
                "kN",
                combination=f.combination,
                clause=_clause("shear"),
                note=f"{how}, fvk0 = {fvk0:g} MPa; {f.where}",
            )
        )
    if bars is not None:
        a_s = bar_area(bars.vertical_dia) * lw / bars.vertical_spacing * bars.layers
        fyd = fy / float(p.gammaS)
        d = t / 2
        z = min(d * (1 - 0.5 * a_s * fyd / (lw * d * fd)), 0.95 * d)
        mrd = a_s * fyd * max(z, 0.0)
        worst_m = max(forces, key=lambda f: abs(f.M2), default=None)
        if worst_m is not None:
            checks.append(
                _row(
                    "Out-of-plane bending (reinforced)",
                    abs(worst_m.M2) / 1e6,
                    mrd / 1e6,
                    "kN·m",
                    combination=worst_m.combination,
                    clause=_clause("reinforced"),
                    note=f"MRd = As fyd z, As = {a_s:.0f} mm², z = {z:.0f} mm (bars at mid-"
                    f"thickness); {worst_m.where}",
                )
            )
    strength = [c for c in checks if not c["flag"]]
    return M.MasonryDesign(checks, notes, max((c["utilisation"] for c in strength), default=0.0))
