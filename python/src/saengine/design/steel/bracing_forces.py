"""The forces of the stability bracing of steel columns and beams under the limit state
methods: the bracing method a pack picks with ``steelLimitState.bracing`` (alpha 9 C12).

- ``equivalentImperfection`` (the Eurocodes pack, EN 1993-1-1 5.3.3): the bracing system takes
  the equivalent stabilising force q = Σ NEd 8 (e0 + δq) / L² along the member, e0 = αm L /
  500, αm = √(0.5 (1 + 1/m)) for the ``members`` m the system restrains, δq taken at the
  pack's deflection limit L / 2500 (SAEngine practice: the system is then checked for that
  deflection); a beam's compression flange with NEd = MEd / h. Each intermediate brace point
  takes q over its spacing, a member braced only at its ends puts q L / 2 into each end's
  system; the local force αm NEd / 100 at splices and brace points is stated.
- ``forceShare`` (the IS pack): each lateral restraint carries the pack's share of the largest
  force in the beam's compression flange (Mr / ho) or of the column's axial force.

The entries have the format of :func:`saengine.design.steel.members.bracing_requirements`
(``betaBr`` None: these methods give no stiffness); the member's notes list them and, when the
pack's table asks (``rows``), each becomes a flagged row of the member's checks
(:func:`rows_of`; the US pack's ``steel.bracing.rows``).

Units: mm, N; the entries in kN and m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

#: Above this many brace points a direction is taken as continuously braced (a slab).
_DISCRETE_BRACES = 10


def table() -> Any | None:
    """The pack's ``steelLimitState.bracing``; None: not chosen."""
    from saengine.design.steel.limit_state import rules

    t = rules()
    return getattr(t, "bracing", None) if t is not None else None


def _cite(key: str) -> str:
    """The group's clause ``key`` (the full reference, the code's name included)."""
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def alpha_m(members: int) -> float:
    """αm = √(0.5 (1 + 1/m)) (EN 1993-1-1 Eq 5.12 form)."""
    return math.sqrt(0.5 * (1 + 1 / max(members, 1)))


def stabilising_force(n_ed: float, length: float, t: Any) -> tuple[float, str]:
    """q [N/mm] of the method ``equivalentImperfection`` for the compression ``n_ed`` [N] over
    ``length`` [mm], and how it was worked out."""
    am = alpha_m(int(t.members))
    e0 = am * length / float(t.bowDivisor)
    dq = length / float(t.deflectionDivisor)
    q = n_ed * 8 * (e0 + dq) / length**2 if length > 0 else 0.0
    note = (
        f"q = NEd 8 (e0 + δq) / L² = {q:.3f} N/mm, αm = {am:.3f} (m = {int(t.members)}), e0 = "
        f"αm L / {float(t.bowDivisor):g} = {e0:.1f} mm, δq = L / {float(t.deflectionDivisor):g}"
        f" = {dq:.1f} mm"
    )
    return q, note


def _entry(what: str, kind: str, points: int, lb: float, demand: str, pbr: float, note: str):
    return {
        "what": what,
        "type": kind,
        "points": points,
        "Lb": round(lb / 1e3, 3),
        "demand": demand,
        "Pbr": round(pbr / 1e3, 2),
        "betaBr": None,
        "note": note,
    }


def _forces(force: float, length: float, inner: int, lb: float, t: Any) -> tuple[float, str, str]:
    """(force per brace point or end [N], type, note) of a compression ``force`` [N]."""
    if t.method == "forceShare":
        share = float(t.share)
        return share * force, "nodal" if inner else "end", f"{share:g} × the force"
    # equivalentImperfection
    q, note = stabilising_force(force, length, t)
    am = alpha_m(int(t.members))
    local = am * force / float(t.spliceDivisor)
    splice = f"at a splice αm NEd / {float(t.spliceDivisor):g} = {local / 1e3:.1f} kN"
    if inner > 0:
        pbr = q * lb
        how = f"{note}; each brace point q × Lb; {splice}"
    else:
        pbr = q * length / 2
        how = f"{note}; each end's bracing system q L / 2; {splice}"
    return pbr, "nodal" if inner else "system", how


def requirements(
    shape: Any, stations: Sequence[Any], lengths: Any, kind: str
) -> list[dict[str, Any]]:
    """The brace forces of a column or beam (I or channel) under the pack's bracing method;
    [] without one. A direction braced at many points (a slab) is continuous bracing, not
    listed."""
    t = table()
    if t is None:
        return []
    clause = _cite("bracing")
    length = float(lengths.length) * 1e3
    out: list[dict[str, Any]] = []
    if kind == "column":
        pr = max((float(p) for st in stations for p in st.P), default=0.0)
        if pr <= 0:
            return []
        for axis, seg in (("x", lengths.x), ("y", lengths.y)):
            inner = len(seg.points) - 2
            lb = seg.longest() * 1e3
            if lb <= 0 or inner > _DISCRETE_BRACES:
                continue
            pbr, how, note = _forces(pr, length, max(inner, 0), lb, t)
            out.append(
                _entry(
                    f"column, buckling about {axis}", how, max(inner, 0), lb,
                    f"NEd = {pr / 1e3:.1f} kN", pbr, f"{clause}: {note}",
                )
            )  # fmt: skip
        return out
    if kind == "beam" and shape.family in ("I", "channel"):
        d = shape.dims
        h = d.get("d", 0.0) if t.method == "equivalentImperfection" else d.get("ho", 0.0)
        if h <= 0:
            return []
        mx = [abs(float(m)) for st in stations for m in st.Mx]
        mr = max(mx, default=0.0)
        if mr <= 0:
            return []
        flange = mr / h
        for label, seg in (("top flange", lengths.ltb_top), ("bottom flange", lengths.ltb_bottom)):
            inner = len(seg.points) - 2
            if inner <= 0 or inner > _DISCRETE_BRACES:
                continue
            lb = seg.longest() * 1e3
            pbr, how, note = _forces(flange, length, inner, lb, t)
            out.append(
                _entry(
                    f"beam, lateral bracing of the {label}", how, inner, lb,
                    f"MEd = {mr / 1e6:.1f} kN·m, NEd = MEd / h = {flange / 1e3:.1f} kN "
                    f"(h = {h:.0f} mm)", pbr, f"{clause}: {note}",
                )
            )  # fmt: skip
    return out


def note_of(b: dict[str, Any]) -> str:
    """The member note of one brace entry."""
    stiffness = f" and {b['betaBr']:g} kN/mm" if b.get("betaBr") is not None else ""
    return (
        f"stability bracing ({b['what']}, {b['type']}, {b['note']}): each brace needs "
        f"{b['Pbr']:g} kN{stiffness} ({b['demand']}, Lb = {b['Lb']:g} m)"
    )


def rows_of(bracing: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flagged check rows of the brace entries: what each brace must provide (informational:
    the braces are other members or the slab, not checked here)."""
    out = []
    for b in bracing:
        stiffness = (
            f", stiffness at least {b['betaBr']:g} kN/mm" if b.get("betaBr") is not None else ""
        )
        out.append(
            {
                "name": f"Stability bracing: {b['what']} (required strength)",
                "demand": float(b["Pbr"]),
                "capacity": float(b["Pbr"]),
                "unit": "kN",
                "utilisation": 0.0,
                "combination": None,
                "ok": True,
                "note": (
                    f"each {b['type']} brace needs at least {b['Pbr']:g} kN{stiffness} "
                    f"({b['demand']}, Lb = {b['Lb']:g} m); {b['note']}; the brace itself is "
                    "checked as its own member"
                ),
                "flag": True,
                "clause": b["note"],
            }
        )
    return out


def method_line() -> str | None:
    """The report paragraph of the bracing method (None: not chosen)."""
    t = table()
    if t is None:
        return None
    if t.method == "forceShare":
        how = (
            f"each lateral restraint for {float(t.share):g} × the force in the beam's "
            "compression flange (Mr / ho) or the column's axial force"
        )
    else:
        how = (
            f"the equivalent stabilising force q = Σ NEd 8 (e0 + δq) / L², e0 = αm L / "
            f"{float(t.bowDivisor):g}, δq = L / {float(t.deflectionDivisor):g}, beams with NEd "
            f"= MEd / h; αm NEd / {float(t.spliceDivisor):g} at splices"
        )
    return f"Stability bracing ({_cite('bracing')}): the braces of columns and beams carry {how}."
