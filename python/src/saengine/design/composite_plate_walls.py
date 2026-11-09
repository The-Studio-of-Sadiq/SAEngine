"""Concrete-filled composite plate shear walls, C-PSW/CF (alpha 9 L7): a concrete wall type
with ``filledPlate`` (:class:`saengine.library.objects.FilledPlateWall`: two steel plates tied
through the fill; the type's thickness is tsc, its material the fill) is designed by the code
pack's ``compositePlateWalls`` table (the US pack: AISC 341-22 H7 with AISC 360-22 Chapter I),
from the storey sections' forces of the shell model (:func:`saengine.design.wall_forces.
wall_forces`, the walls' design path).

Per wall and storey section, enveloped over the combinations:

- in-plane shear: Vn = (Ks + Kc) / √(3 Ks² + Kc²) As Fy, Ks = Gs As, Kc = c Ec Ac Es As / (k Es
  As + Ec Ac) (the cracked fill), As = 2 tp lw;
- compression: Pno = Fy As + α f'c Ac (a storey-high wall: no slenderness reduction);
- in-plane flexure at the axial force: the plastic stress distribution (plates at Fy in
  tension and compression, the fill at α f'c over the compression depth), φb Mn ≥ Mu;
- detailing: the wall thickness, the steel ratio 2 tp / tsc, the plate thickness, the plate
  slenderness s / tp and the ties' spacing for composite action (α of the tie bars).

The plates' end closures (flanged walls) are not counted (on the safe side). A pack without the
table does not cover these walls. Units: mm, MPa, N; reported in kN, kN·m.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context

TABLE = "compositePlateWalls"


def table() -> Any | None:
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery
        return None


def _clause(key: str) -> str:
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def _row(name, demand, capacity, unit, combo, note, key) -> dict[str, Any]:
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    u = round(u, 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": u,
        "combination": combo,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": False,
        "clause": _clause(key),
    }


def shear_strength(
    tp: float, lw: float, tsc: float, fy: float, es: float, ec: float, nu: float = 0.3
) -> float:
    """Vn [N] of the composite section (``nu``: the plates' Poisson ratio)."""
    t = table()
    a_s = 2 * tp * lw
    a_c = (tsc - 2 * tp) * lw
    gs = es / (2 * (1 + nu))  # the plates' shear modulus
    ks = gs * a_s
    kc = (
        float(t.crackedConcrete)
        * ec
        * a_c
        * es
        * a_s
        / (float(t.compositeShear) * es * a_s + ec * a_c)
    )
    return (ks + kc) / math.sqrt(3 * ks**2 + kc**2) * a_s * fy


def plastic_moment(
    p: float, tp: float, lw: float, tsc: float, fy: float, fc: float
) -> tuple[float, float]:
    """(Mn [N·mm], compression depth c [mm]) at the axial force ``p`` [N] (compression +) by
    the plastic stress distribution."""
    t = table()
    alpha = float(t.concreteBlock)
    bc = tsc - 2 * tp
    c = (p + 2 * tp * fy * lw) / (alpha * fc * bc + 4 * tp * fy)
    c = min(max(c, 0.0), lw)
    cc = alpha * fc * bc * c
    cs = 2 * tp * fy * c
    ts = 2 * tp * fy * (lw - c)
    mn = (cc + cs) * (lw / 2 - c / 2) + ts * (c / 2)
    return mn, c


def check_wall(
    wall_id: str,
    wall: Any,
    element: Any,
    fill: Any,
    plate: Any,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """The design entry of one filled composite plate wall."""
    from saengine.design.slender import concrete_modulus

    t = table()
    fp = wall.filledPlate
    tp, tsc = float(fp.plateThickness), float(wall.thickness)
    fy = float(plate.steel.fy)
    es = float(plate.mechanical.E or 200000.0)
    fc = float(fill.concrete.fc)
    ec = float(concrete_modulus(fill))
    lw = float(np.linalg.norm(np.asarray(element.end, float) - np.asarray(element.start, float)))
    f = t.factors
    a_s = 2 * tp * lw
    a_c = (tsc - 2 * tp) * lw
    nu = float(plate.mechanical.nu or 0.3)
    vn = float(f.shear) * shear_strength(tp, lw, tsc, fy, es, ec, nu)
    pno = float(f.compression) * (fy * a_s + float(t.concreteBlock) * fc * a_c)
    worst = {"v": (0.0, None, ""), "p": (0.0, None, ""), "m": (-1.0, None, "", 0.0, 0.0)}
    for s in sections:
        for cut, rows in (s.get("cuts") or {}).items():
            for combo, r in (rows or {}).items():
                v = abs(float(r.get("V2", 0.0))) * 1e3
                p = float(r.get("P", 0.0)) * 1e3
                m = abs(float(r.get("M3", 0.0))) * 1e6
                where = f"{s.get('section', wall_id)} {cut}"
                if v > worst["v"][0]:
                    worst["v"] = (v, combo, where)
                if p > worst["p"][0]:
                    worst["p"] = (p, combo, where)
                mn, c = plastic_moment(p, tp, lw, tsc, fy, fc)
                cap = float(f.flexure) * mn
                u = m / cap if cap > 0 else (0.0 if m <= 0 else math.inf)
                if u > worst["m"][0]:
                    worst["m"] = (
                        u,
                        combo,
                        f"{where}; P = {p / 1e3:.0f} kN, c = {c:.0f} mm",
                        m,
                        cap,
                    )
    checks = []
    v, combo, where = worst["v"]
    checks.append(
        _row(
            "Filled plate wall: in-plane shear",
            v / 1e3,
            vn / 1e3,
            "kN",
            combo,
            f"φ Vn of the composite section, As = {a_s:.0f} mm², Ec = {ec:.0f} MPa; {where}",
            "shear",
        )
    )
    p, combo, where = worst["p"]
    checks.append(
        _row(
            "Filled plate wall: compression",
            p / 1e3,
            pno / 1e3,
            "kN",
            combo,
            f"φ Pno = φ (Fy As + {float(t.concreteBlock):g} f'c Ac); {where}",
            "compression",
        )
    )
    if worst["m"][1] is not None:
        _, combo, where, m, cap = worst["m"]
        checks.append(
            _row(
                "Filled plate wall: in-plane flexure",
                m / 1e6,
                cap / 1e6,
                "kN·m",
                combo,
                f"plastic stress distribution at the axial force; {where}",
                "flexure",
            )
        )
    lim = t.limits
    checks.append(
        _row(
            "Wall thickness tsc (least)", float(lim.thicknessMin), tsc, "mm", None, "", "detailing"
        )
    )
    checks.append(
        _row("Wall thickness tsc (most)", tsc, float(lim.thicknessMax), "mm", None, "", "detailing")
    )
    rho = 2 * tp / tsc
    checks.append(
        _row(
            "Steel ratio 2 tp / tsc (least)",
            float(lim.steelRatioMin),
            rho,
            "",
            None,
            "",
            "detailing",
        )
    )
    checks.append(
        _row(
            "Steel ratio 2 tp / tsc (most)",
            rho,
            float(lim.steelRatioMax),
            "",
            None,
            "",
            "detailing",
        )
    )
    checks.append(
        _row("Plate thickness (least)", float(lim.plateMin), tp, "mm", None, "", "detailing")
    )
    s_tie, d_tie = float(fp.tieSpacing), float(fp.tieDiameter)
    checks.append(
        _row(
            "Plate slenderness s / tp",
            s_tie / tp,
            float(lim.plateSlenderness) * math.sqrt(es / fy),
            "",
            None,
            f"tie spacing {s_tie:g} mm",
            "slenderness",
        )
    )
    alpha = float(lim.alphaFactor) * (tsc / tp - 2) * (tp / d_tie) ** float(lim.alphaExponent)
    checks.append(
        _row(
            "Tie spacing for composite action s / tp",
            s_tie / tp,
            float(lim.tieSpacing) * math.sqrt(es / ((2 * alpha + 1) * fy)),
            "",
            None,
            f"α = {alpha:.2f} (ties Ø{d_tie:g} mm)",
            "ties",
        )
    )
    strength = [c for c in checks if not c["flag"]]
    return {
        "id": wall_id,
        "kind": "wall",
        "type": wall.id,
        "wallType": "filledPlate",
        "members": [],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "filledPlate": {
            "tp": tp,
            "tsc": tsc,
            "lw": round(lw),
            "plate": plate.id,
            "fill": fill.id,
        },
    }


def design_walls(
    walls: list[tuple[Any, Any, Any]],
    sections_of: dict[str, list[dict[str, Any]]],
    mats: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """The filled plate walls ``(element, wall type, fill material)`` designed: (elements,
    skipped, notes)."""
    elements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    if table() is None:
        for e, t, _ in walls:
            skipped.append(
                {
                    "id": e.id,
                    "kind": "wall",
                    "type": t.id,
                    "reason": "concrete-filled composite plate walls are not covered by the "
                    "code pack",
                }
            )
        return elements, skipped, notes
    for e, t, fill in walls:
        plate = mats.get(t.filledPlate.plateMaterial)
        if plate is None or getattr(plate, "steel", None) is None:
            skipped.append(
                {
                    "id": e.id,
                    "kind": "wall",
                    "type": t.id,
                    "reason": f"plate material '{t.filledPlate.plateMaterial}' is not a steel",
                }
            )
            continue
        if fill is None or getattr(fill, "concrete", None) is None:
            skipped.append({"id": e.id, "kind": "wall", "type": t.id, "reason": "no concrete fill"})
            continue
        sections = sections_of.get(e.id, [])
        if not sections:
            skipped.append(
                {"id": e.id, "kind": "wall", "type": t.id, "reason": "not in the analysis results"}
            )
            continue
        elements.append(check_wall(e.id, t, e, fill, plate, sections))
    return elements, skipped, notes


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    return [
        (
            f"Concrete-filled composite plate shear walls ({_clause('code')}): in-plane shear Vn = "
            "(Ks + Kc) / √(3 Ks² + Kc²) As Fy with the cracked fill, compression Pno = Fy As + "
            f"{float(t.concreteBlock):g} f'c Ac, in-plane flexure by the plastic stress "
            "distribution at the axial force, the wall thickness, steel ratio, plate slenderness "
            "and tie spacing limits."
        )
    ]
