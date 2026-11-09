"""The axial and elastic bending resistances of a steel part by the code pack's own steel
member method (alpha 9 L7): the parts of special members (the chords and webs of open-web
joists, the tees of castellated and cellular beams) are designed by whichever steel method the
pack in force chooses, without a method of their own:

- buckling curves with partial factors (:mod:`saengine.design.steel.buckling_curves`, the EN
  1993 type) when the pack's limit state table selects it;
- limit state with partial factors (:mod:`saengine.design.steel.limit_state`, the IS 800 type)
  when the pack has the limit state table;
- else the pack's ``steel`` table by φ (LRFD) or Ω (ASD) (:mod:`saengine.design.steel.members`).

Each function returns ``(design resistance [N or N·mm], clause, note)``. Units: mm, MPa, N.
"""

from __future__ import annotations

from typing import Any

from saengine.design.steel.properties import ShapeProperties, tee


def doubled(shape: ShapeProperties) -> ShapeProperties:
    """Two of ``shape`` back to back: two angles act as a tee of their legs (flange 2b, stem
    2t; the gap between them neglected, on the safe side for the out-of-plane axis); other
    shapes as twice the area, inertias and moduli (their radii of gyration unchanged)."""
    import dataclasses

    if shape.family == "angle":
        d = shape.dims
        legs = tee(d["d"], 2 * d["b"], d["t"], 2 * d["t"], label=f"2{shape.label}")
        return dataclasses.replace(legs, notes=(*shape.notes, "two angles taken as a tee"))
    return dataclasses.replace(
        shape,
        label=f"2×{shape.label}",
        area=2 * shape.area,
        ix=2 * shape.ix,
        iy=2 * shape.iy,
        sx=2 * shape.sx,
        sy=2 * shape.sy,
        zx=2 * shape.zx,
        zy=2 * shape.zy,
        j=2 * shape.j,
        cw=2 * shape.cw,
        sx_top=2 * shape.sx_top,
        sx_bottom=2 * shape.sx_bottom,
        iz=2 * shape.iz,
        ixy=2 * shape.ixy,
    )


def outer_distance(shape: ShapeProperties) -> float:
    """Distance from the outer face (the flange's, of a tee) to the centroid [mm]."""
    if shape.sx_top > 0:
        return shape.ix / shape.sx_top
    return shape.ix / shape.sx if shape.sx > 0 else 0.0


def _family() -> str:
    from saengine.design.steel import buckling_curves as bc
    from saengine.design.steel import limit_state as ls

    if ls.rules() is None:
        return "members"
    return "curves" if bc.active() else "limitState"


def axial(
    shape: ShapeProperties, steel: Any, klx: float, kly: float, compression: bool
) -> tuple[float, str, str]:
    """The design axial resistance of ``shape``: in compression with the buckling lengths
    ``klx`` (about its x axis) and ``kly`` [mm], else in tension (gross yielding: the joints
    of the parts are not known to the member)."""
    from saengine.design.steel import buckling_curves as bc
    from saengine.design.steel import limit_state as ls
    from saengine.design.steel import members as sm

    family = _family()
    if family == "curves":
        t = bc.table()
        sec = bc.Section.of(shape, steel.fy, steel.fu, False)
        if not compression:
            g0 = float(t.gammaM0)
            return (
                shape.area * sec.fy / g0,
                bc.clause("tension"),
                f"Npl,Rd = A fy / γM0, A = {shape.area:.0f} mm², γM0 = {g0:g}",
            )
        found = bc.buckling(sec, klx, kly, kly)
        g1 = float(t.gammaM1)
        return found.chi * sec.area_eff * sec.fy / g1, bc.clause("buckling"), found.note
    if family == "limitState":
        st = ls.design_steel(shape, steel)
        if compression:
            cap = ls.compression(shape, st, klx, kly, klx, kly).cap
        else:
            cap = ls.tension_yielding(shape, st)
        return cap.design, cap.clause, cap.note
    cap = (
        sm.compression(shape, steel, klx, kly) if compression else sm.tension_yielding(shape, steel)
    )
    return cap.design, cap.clause, cap.note


def elastic_moment(shape: ShapeProperties, steel: Any) -> tuple[float, str, str]:
    """The design elastic moment about the shape's x axis (the least elastic modulus: on the
    safe side for tees and angles) [N·mm]."""
    from saengine.design.steel import buckling_curves as bc
    from saengine.design.steel import limit_state as ls
    from saengine.design.steel import members as sm

    family = _family()
    if family == "curves":
        g0 = float(bc.table().gammaM0)
        return (
            shape.sx * steel.fy / g0,
            bc.clause("bending"),
            f"Wel fy / γM0, Wel = {shape.sx:.0f} mm³",
        )
    if family == "limitState":
        g0 = float(ls.rules().partialFactors.gammaM0)
        return (
            shape.sx * steel.fy / g0,
            ls.cite("flexure"),
            f"Ze fy / γm0, Ze = {shape.sx:.0f} mm³",
        )
    phi = sm._phi("flexure")
    return phi * shape.sx * steel.fy, sm._s("interaction"), f"Sx = {shape.sx:.0f} mm³ (elastic)"


__all__ = ["axial", "doubled", "elastic_moment", "outer_distance"]
