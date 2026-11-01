"""The general strut-and-tie model of any D-region (the model editor's engine).

A model (:class:`saengine.library.strut_and_tie.StmModel`) is a plane truss of struts and ties
in the region's own x-y plane, held by supports at its boundary and loaded, case by case, by the
factored forces from the analysis. This module:

1. solves the truss for every load case (pin-jointed, by the stiffness method with one axial
   stiffness for all members: exact for a statically determinate model; a statically
   indeterminate one gets an elastic share and a warning), and reports the member forces and
   the reactions, a mechanism or a member of zero length as a problem;
2. checks it with the strut-and-tie procedure of the code pack (:mod:`saengine.design.stm`,
   the shared capacities; their clauses come from the pack):

   - equilibrium and φ Fn ≥ Fu for every strut, tie and nodal zone, Fu the largest force of
     all cases;
   - a member drawn as a strut must be in compression in every case, a tie in tension;
   - a strut: Fns = fce Acs + As' fs' with fce the smaller of the strut's (βs by its shape,
     the bottle-shaped strut's βs by its crack-control web steel) and the nodal zones' at its
     two ends (βn by the ties each anchors);
   - a bottle-shaped strut's web steel: Σ Asi sin αi / (bs si) against the pack's ratio up to
     its f'c limit (one direction only at the least angle), above it the transverse tension
     of the strut's spread (slope ``spreadSlope``: T = C / (2 slope) in each half) against the
     bars crossing half the strut;
   - a tie: Fnt = Ats fy + Atp (fse + Δfp) (fse + Δfp ≤ fpy); with no bars yet, the area it
     needs;
   - a nodal zone's faces: the bearing (the reaction or the applied load over the bearing
     length) and each tie's face (its effective width), against φ fce,n Anz;
   - the angle between every strut and tie meeting at a node;
   - the anchorage of the ties ending at a node with standard hooks.

3. offers templates to start from (:func:`template`): a deep beam with a point load, a dapped
   end, a corbel and a frame corner under a closing moment.

Units: input mm, mm², MPa, kN; reported in kN, mm², MPa, degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.design import stm
from saengine.library.strut_and_tie import (
    StmLoad,
    StmLoadCase,
    StmMember,
    StmModel,
    StmNode,
    StmWebLayer,
)

__all__ = [
    "TEMPLATES",
    "Solution",
    "check_model",
    "solve",
    "template",
]

#: One axial stiffness for every member [N] (the forces of a determinate truss do not depend
#: on it; an indeterminate one's are shared by it).
_EA = 1.0e6
#: A member's force smaller than this is no force [N] (struts and ties may carry none in a case).
_ZERO_FORCE = 1.0
#: Members shorter than this are of zero length [mm].
_SHORT = 1.0


@dataclass
class Solution:
    """The truss solved for one load case: member forces [N] (tension positive), reactions [N]
    by node (x, y), and the problems that kept it from being solved."""

    case: str
    forces: dict[str, float] = field(default_factory=dict)
    reactions: dict[str, tuple[float, float]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _held(support: str) -> tuple[bool, bool]:
    return {"pin": (True, True), "rollerX": (False, True), "rollerY": (True, False)}.get(
        support, (False, False)
    )


def _geometry(model: StmModel) -> tuple[dict[str, int], dict[str, tuple[float, float, float]]]:
    """Node index by id, and each member's (cos, sin, length) from start to end."""
    index = {n.id: k for k, n in enumerate(model.nodes)}
    at = {n.id: (n.x, n.y) for n in model.nodes}
    geometry = {}
    for m in model.members:
        (x0, y0), (x1, y1) = at[m.start], at[m.end]
        length = math.hypot(x1 - x0, y1 - y0)
        geometry[m.id] = ((x1 - x0) / length, (y1 - y0) / length, length) if length else (
            0.0, 0.0, 0.0)  # fmt: skip
    return index, geometry


def indeterminacy(model: StmModel) -> int:
    """Members + reactions - 2 × nodes: 0 for a statically determinate truss (when it is
    stable), > 0 for an indeterminate one, < 0 for a mechanism."""
    reactions = sum(sum(_held(n.support)) for n in model.nodes)
    return len(model.members) + reactions - 2 * len(model.nodes)


def solve(model: StmModel, case: StmLoadCase) -> Solution:
    """The truss of ``model`` under ``case`` (see the module)."""
    solution = Solution(case.name)
    index, geometry = _geometry(model)
    short = [m.id for m in model.members if geometry[m.id][2] < _SHORT]
    if short:
        solution.problems.append(f"members of zero length: {', '.join(short)}")
        return solution
    size = 2 * len(model.nodes)
    stiffness = np.zeros((size, size))
    for m in model.members:
        c, s, length = geometry[m.id]
        k = _EA / length * np.array([[c * c, c * s], [c * s, s * s]])
        i, j = 2 * index[m.start], 2 * index[m.end]
        for a, b, sign in ((i, i, 1), (j, j, 1), (i, j, -1), (j, i, -1)):
            stiffness[a : a + 2, b : b + 2] += sign * k
    load = np.zeros(size)
    for item in case.loads:
        k = 2 * index[item.node]
        load[k] += item.fx * 1e3
        load[k + 1] += item.fy * 1e3
    fixed = [
        2 * index[n.id] + axis
        for n in model.nodes
        for axis, held in enumerate(_held(n.support))
        if held
    ]
    free = [k for k in range(size) if k not in set(fixed)]
    reduced = stiffness[np.ix_(free, free)]
    scale = float(np.abs(reduced).max()) if reduced.size else 0.0
    if not fixed or (
        reduced.size
        and (scale == 0 or np.linalg.matrix_rank(reduced, tol=1e-10 * scale) < len(free))
    ):
        solution.problems.append(
            "the truss is a mechanism: add members or supports so that every node is held"
        )
        return solution
    displacement = np.zeros(size)
    displacement[free] = np.linalg.solve(reduced, load[free])
    for m in model.members:
        c, s, length = geometry[m.id]
        i, j = 2 * index[m.start], 2 * index[m.end]
        stretch = c * (displacement[j] - displacement[i]) + s * (
            displacement[j + 1] - displacement[i + 1]
        )
        solution.forces[m.id] = float(_EA / length * stretch)
    reaction = stiffness @ displacement - load
    for n in model.nodes:
        hx, hy = _held(n.support)
        if hx or hy:
            k = 2 * index[n.id]
            solution.reactions[n.id] = (
                float(reaction[k]) if hx else 0.0,
                float(reaction[k + 1]) if hy else 0.0,
            )
    return solution


# ─────────────────────────────────────── checks ───────────────────────────────────────


def _row(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check

    return _check(*args, **kwargs)


def _cite(*keys: str) -> str:
    found = [c for c in (stm.cite(k) for k in keys) if c]
    return "; ".join(dict.fromkeys(found))


def _acute(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The angle [degrees] between two lines of directions ``a`` and ``b`` (0-90)."""
    cos = abs(a[0] * b[0] + a[1] * b[1])
    return math.degrees(math.acos(min(1.0, cos)))


def _web_angles(
    model: StmModel, direction: tuple[float, float]
) -> list[tuple[float, float, float]]:
    """The web layers as (area, spacing, angle to the strut of ``direction``)."""
    out = []
    for layer in model.web:
        bar = (math.cos(math.radians(layer.angle)), math.sin(math.radians(layer.angle)))
        out.append((layer.area, layer.spacing, _acute(bar, direction)))
    return out


def _web(model: StmModel, member: StmMember, direction: tuple[float, float], length: float,
         force: float) -> tuple[bool, dict[str, Any] | None]:  # fmt: skip
    """Whether a bottle-shaped strut's crack-control web steel is there (so βs = betaBottle),
    and its check row (None when there is no web steel at all)."""
    if not model.web:
        return False, None
    layers = _web_angles(model, direction)
    angles = [a for _, _, a in layers if a > 1.0]
    one_way = len({round(_acute((math.cos(math.radians(w.angle)), math.sin(math.radians(
        w.angle))), (1.0, 0.0))) for w in model.web}) == 1  # fmt: skip
    least_angle = stm.factor("webAngleMin")
    if one_way and (not angles or min(angles) < least_angle):
        return False, _row(
            f"Web steel angle to strut {member.id}",
            least_angle,
            min(angles) if angles else 0.0,
            "°",
            None,
            f"web bars in one direction only: at least {least_angle:g}° to the strut "
            f"({_cite('webAngleMin')}); βs of a strut without its web steel",
        )
    if model.fc <= stm.factor("webRatioFcMax"):
        ratio = stm.web_ratio(layers, model.thickness)
        need = stm.factor("webRatio")
        row = _row(
            f"Web steel across strut {member.id}",
            need,
            ratio,
            "",
            None,
            f"Σ Asi sin αi / (bs si) = {ratio:.4f} against {need:g} for f'c ≤ "
            f"{stm.factor('webRatioFcMax'):g} MPa ({_cite('webRatio')})",
        )
        return row["ok"], row
    slope = stm.factor("spreadSlope")
    tension = force / (2 * slope)
    provided = (
        sum(
            area / spacing * (length / 2) * math.sin(math.radians(angle))
            for area, spacing, angle in layers
        )
        * model.fy
        * stm.phi()
    )
    row = _row(
        f"Spread tension across strut {member.id}",
        tension / 1e3,
        provided / 1e3,
        "kN",
        None,
        f"f'c above {stm.factor('webRatioFcMax'):g} MPa: T = C / (2 × {slope:g}) in each half "
        f"of the strut against φ Σ Asi fy sin αi over half its length "
        f"({_cite('spreadSlope', 'webRatioFcMax')})",
    )
    return row["ok"], row


def _envelope(solutions: list[Solution]) -> dict[str, dict[str, tuple[float, str | None]]]:
    """Per member: the largest tension and compression [N] and their case."""
    out: dict[str, dict[str, tuple[float, str | None]]] = {}
    for solution in solutions:
        for member, force in solution.forces.items():
            entry = out.setdefault(member, {"tension": (0.0, None), "compression": (0.0, None)})
            if force > entry["tension"][0]:
                entry["tension"] = (force, solution.case)
            if -force > entry["compression"][0]:
                entry["compression"] = (-force, solution.case)
    return out


def _node_beta(model: StmModel) -> dict[str, tuple[float, int]]:
    """βn and the number of ties anchored, by node."""
    ties: dict[str, int] = {n.id: 0 for n in model.nodes}
    for m in model.members:
        if m.kind == "tie":
            ties[m.start] += 1
            ties[m.end] += 1
    return {node: (stm.beta_node(count), count) for node, count in ties.items()}


_NODE_KIND = {0: "C-C-C", 1: "C-C-T"}


def check_model(model: StmModel) -> dict[str, Any]:
    """Solve and check ``model`` (see the module): ``{"name", "ok", "utilisation",
    "problems", "warnings", "cases": [{"name", "forces": {member: kN}, "reactions": {node:
    [kN, kN]}}], "members": [{"id", "kind", "force", "case", "utilisation", "ok"}], "nodes":
    [{"id", "type", "betaN"}], "checks": [check rows], "assumptions": [str], "source"}``."""
    problems: list[str] = []
    warnings: list[str] = []
    if not model.nodes or not model.members:
        problems.append("draw the model: at least three nodes and the struts and ties joining them")
    if not model.cases:
        problems.append("add a load case with the factored forces on the region")
    solutions = [solve(model, case) for case in model.cases] if not problems else []
    for solution in solutions:
        problems += [f"{solution.case}: {p}" for p in solution.problems]
    result: dict[str, Any] = {
        "name": model.name,
        "member": model.member,
        "ok": False,
        "utilisation": None,
        "problems": problems,
        "warnings": warnings,
        "cases": [],
        "members": [],
        "nodes": [],
        "checks": [],
        "assumptions": [],
        "source": _cite("general", "equilibrium"),
        "covered": stm.covers_general(),
    }
    if problems:
        return result
    excess = indeterminacy(model)
    if excess > 0:
        warnings.append(
            f"the model is statically indeterminate ({excess} redundant): its forces are an "
            "elastic share with one axial stiffness for all members; check that they are a "
            "load path the reinforcement follows"
        )
    result["cases"] = [
        {
            "name": s.case,
            "forces": {k: round(v / 1e3, 2) for k, v in s.forces.items()},
            "reactions": {
                k: [round(v[0] / 1e3, 2), round(v[1] / 1e3, 2)] for k, v in s.reactions.items()
            },
        }
        for s in solutions
    ]
    _, geometry = _geometry(model)
    envelope = _envelope(solutions)
    betas = _node_beta(model)
    phi = stm.phi()
    effective = stm.factor("effective")
    t = model.thickness
    checks: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    for m in model.members:
        c, s, length = geometry[m.id]
        tension, t_case = envelope[m.id]["tension"]
        compression, c_case = envelope[m.id]["compression"]
        rows: list[dict[str, Any]] = []
        if m.kind == "strut":
            if tension > _ZERO_FORCE:
                rows.append(_row(f"Strut {m.id} in tension", tension / 1e3, 0.0, "kN", t_case,
                                 "a strut must be in compression in every case: draw it as a "
                                 f"tie or change the model ({_cite('equilibrium')})"))  # fmt: skip
            force = compression
            web_ok, web_row = (False, None)
            if m.shape == "bottle":
                web_ok, web_row = _web(model, m, (c, s), length, force)
                if web_row is not None:
                    rows.append(web_row)
            beta_s = stm.beta_strut(m.shape, web_ok, model.lam)
            beta_n = min(betas[m.start][0], betas[m.end][0])
            fce_strut = stm.effective_strength(model.fc, beta_s)
            fce_node = stm.effective_strength(model.fc, beta_n)
            fce = min(fce_strut, fce_node)
            if m.width <= 0:
                problems.append(f"strut {m.id}: give its width")
                continue
            area = m.width * t
            nominal = stm.strut_nominal(fce, area, m.steelArea, model.fy)
            shape_key = {"prism": "betaPrism", "tension": "betaTension", "other": "betaOther"}.get(
                m.shape, "betaBottle" if web_ok else "betaBottlePlain")  # fmt: skip
            rows.append(_row(
                f"Strut {m.id}",
                force / 1e3,
                phi * nominal / 1e3,
                "kN",
                c_case,
                f"φ (fce Acs + As' fs'), φ = {phi:g}; fce = min({effective:g} βs f'c, "
                f"{effective:g} βn f'c) = min({fce_strut:.2f}, {fce_node:.2f}) MPa, βs = "
                f"{beta_s:g} ({m.shape}), βn = {beta_n:g} at its ends; Acs = ws bs = "
                f"{m.width:.0f} × {t:.0f} mm"
                + (f"; As' = {m.steelArea:.0f} mm², fs' = fy" if m.steelArea else "")
                + f" ({_cite(shape_key, 'effective', 'compressionSteel')})",
            ))  # fmt: skip
        else:
            if compression > _ZERO_FORCE:
                rows.append(_row(f"Tie {m.id} in compression", compression / 1e3, 0.0, "kN",
                                 c_case, "a tie must be in tension in every case: draw it as a "
                                 f"strut or change the model ({_cite('equilibrium')})"))  # fmt: skip
            force = tension
            nominal = stm.tie_nominal(m.barArea, model.fy, m.prestressArea, m.fse, m.fpy,
                                      m.bonded)  # fmt: skip
            prestress = nominal - m.barArea * model.fy
            need = max((force / phi - prestress) / model.fy, 0.0)
            rows.append(_row(
                f"Tie {m.id}",
                force / 1e3,
                phi * nominal / 1e3,
                "kN",
                t_case,
                f"φ (Ats fy + Atp (fse + Δfp)), φ = {phi:g}, Ats = {m.barArea:.0f} mm²"
                + (f", Atp = {m.prestressArea:.0f} mm²" if m.prestressArea else "")
                + f"; Ats needed {need:.0f} mm² ({_cite('deltaFpBonded')})",
            ))  # fmt: skip
        worst = max(rows, key=lambda r: r["utilisation"]) if rows else None
        member_rows.append({
            "id": m.id,
            "kind": m.kind,
            "force": round((force if m.kind == "tie" else -force) / 1e3, 2),
            "case": t_case if m.kind == "tie" else c_case,
            "utilisation": worst["utilisation"] if worst else 0.0,
            "ok": all(r["ok"] for r in rows),
            **({"required": round(need, 0)} if m.kind == "tie" else {}),
        })  # fmt: skip
        checks += rows
    # ── nodes ──
    node_rows: list[dict[str, Any]] = []
    least = stm.min_angle()
    for n in model.nodes:
        beta_n, count = betas[n.id]
        kind = _NODE_KIND.get(count, "C-T-T")
        node_key = {0: "betaCCC", 1: "betaCCT"}.get(count, "betaCTT")
        fce_n = stm.effective_strength(model.fc, beta_n)
        rows = []
        # The bearing face: the reaction, or the largest load put on the node.
        if n.bearing > 0:
            bearing_force, bearing_case = 0.0, None
            for solution in solutions:
                rx, ry = solution.reactions.get(n.id, (0.0, 0.0))
                force = math.hypot(rx, ry)
                for item in next(c for c in model.cases if c.name == solution.case).loads:
                    if item.node == n.id:
                        force = max(force, math.hypot(item.fx, item.fy) * 1e3)
                if force > bearing_force:
                    bearing_force, bearing_case = force, solution.case
            rows.append(_row(
                f"Node {n.id} bearing face ({kind})",
                bearing_force / 1e3,
                phi * fce_n * n.bearing * t / 1e3,
                "kN",
                bearing_case,
                f"φ fce Anz, fce = {effective:g} βn f'c = {fce_n:.2f} MPa, βn = {beta_n:g}; "
                f"Anz = {n.bearing:.0f} × {t:.0f} mm ({_cite('nodeArea', node_key)})",
            ))  # fmt: skip
        members_here = [m for m in model.members if n.id in (m.start, m.end)]
        for m in members_here:
            if m.kind == "tie" and m.width > 0:
                force, case = envelope[m.id]["tension"]
                rows.append(_row(
                    f"Node {n.id} face of tie {m.id} ({kind})",
                    force / 1e3,
                    phi * fce_n * m.width * t / 1e3,
                    "kN",
                    case,
                    f"φ fce wt bs, fce = {fce_n:.2f} MPa, wt = {m.width:.0f} mm "
                    f"({_cite('nodeArea', node_key)})",
                ))  # fmt: skip
        # Angles between the struts and the ties at the node.
        for a in members_here:
            if a.kind != "strut":
                continue
            for b in members_here:
                if b.kind != "tie":
                    continue
                angle = _acute(geometry[a.id][:2], geometry[b.id][:2])
                rows.append(_row(
                    f"Angle of strut {a.id} to tie {b.id} at {n.id}",
                    least,
                    angle,
                    "°",
                    None,
                    f"at least {least:g}° ({_cite('minAngle')})",
                ))  # fmt: skip
        # Anchorage of the ties ending here.
        ending = [m for m in members_here if m.kind == "tie"]
        if ending and n.anchorage == "hook":
            from saengine.design.ductile_joints import hooked_development

            for m in ending:
                if m.barDiameter <= 0:
                    warnings.append(
                        f"tie {m.id}: give its bar diameter to check its hooks at {n.id}"
                    )
                    continue
                need = hooked_development(m.barDiameter, model.fy, model.fc, model.lam)
                rows.append(_row(
                    f"Anchorage of tie {m.id} at {n.id} (hooks)",
                    need,
                    n.anchorLength,
                    "mm",
                    None,
                    f"ldh = {need:.0f} mm for Ø{m.barDiameter:g}, developed past the extended "
                    f"nodal zone ({_cite('anchorage')})",
                ))  # fmt: skip
        elif ending and n.anchorage == "":
            if len(ending) == 1 or n.support:
                warnings.append(
                    f"node {n.id}: say how the ties ending there are anchored (hooks, a plate or "
                    "bars running through) so their development can be checked"
                )
        worst = max(rows, key=lambda r: r["utilisation"]) if rows else None
        node_rows.append({
            "id": n.id,
            "type": kind,
            "betaN": beta_n,
            "utilisation": worst["utilisation"] if worst else 0.0,
            "ok": all(r["ok"] for r in rows),
        })  # fmt: skip
        checks += rows
    result["members"] = member_rows
    result["nodes"] = node_rows
    result["checks"] = checks
    result["problems"] = problems
    result["utilisation"] = max((r["utilisation"] for r in checks), default=0.0)
    result["ok"] = not problems and all(r["ok"] for r in checks)
    depth = model.depth * stm.factor("dRegionDepth")
    assumptions = [
        f"φ = {phi:g} for the struts, ties, nodal zones and bearing areas ({_cite('equilibrium')})",
        "a strut's Fu and a tie's Fu are the largest of all load cases",
        "the faces of a nodal zone are checked where a bearing length or a tie width is given; a "
        + "section through a subdivided nodal zone is not checked",
    ]
    if depth > 0:
        assumptions.append(
            f"the D-region extends {depth:.0f} mm from the discontinuity ({_cite('dRegionDepth')})"
        )
    result["assumptions"] = assumptions
    return result


# ─────────────────────────────────────── templates ───────────────────────────────────────

#: The bar diameter a template gives its ties [mm] (the engineer changes it).
_TEMPLATE_BAR = 16.0


def _model(name: str, kind: str, thickness: float, depth: float, fc: float, fy: float,
           nodes: list[StmNode], members: list[tuple[str, str, str, float]],
           loads: list[StmLoad], web: list[StmWebLayer] | None = None) -> StmModel:  # fmt: skip
    """A template model, its members' kinds taken from the forces under ``loads``."""
    drafted = StmModel(
        name=name,
        template=kind,
        thickness=thickness,
        depth=depth,
        fc=fc,
        fy=fy,
        nodes=nodes,
        members=[StmMember(id=i, start=a, end=b, width=w) for i, a, b, w in members],
        cases=[StmLoadCase(name="Factored", loads=loads)],
        web=web or [],
    )
    solution = solve(drafted, drafted.cases[0])
    members_out = []
    for (member_id, a, b, width), m in zip(members, drafted.members, strict=True):
        tie = solution.forces.get(m.id, 0.0) > _ZERO_FORCE
        members_out.append(StmMember(
            id=("T" if tie else "S") + member_id,
            start=a,
            end=b,
            kind="tie" if tie else "strut",
            width=0.0 if tie else width,
            shape="bottle",
            barDiameter=_TEMPLATE_BAR if tie else 0.0,
        ))  # fmt: skip
    return drafted.model_copy(update={"members": members_out})


def _deep_beam(p: dict[str, float]) -> StmModel:
    span, h, t = p.get("span", 3000.0), p.get("depth", 1500.0), p.get("thickness", 300.0)
    load, bearing, cover = p.get("load", 1000.0), p.get("bearing", 300.0), p.get("cover", 75.0)
    top = h - cover
    nodes = [
        StmNode(id="A", x=0, y=cover, support="pin", bearing=bearing, anchorage="plate"),
        StmNode(id="B", x=span, y=cover, support="rollerX", bearing=bearing, anchorage="plate"),
        StmNode(id="C", x=span / 2, y=top, bearing=bearing),
    ]
    members = [("1", "A", "B", 0.0), ("2", "A", "C", bearing), ("3", "B", "C", bearing)]
    return _model("Deep beam", "deepBeam", t, h, p.get("fc", 28.0), p.get("fy", 420.0), nodes,
                  members, [StmLoad(node="C", fy=-load)])  # fmt: skip


def _dapped_end(p: dict[str, float]) -> StmModel:
    h, nib, t = p.get("depth", 750.0), p.get("nibDepth", 375.0), p.get("thickness", 300.0)
    dap = p.get("dapLength", 300.0)  # length of the nib from the beam's end
    reaction, cover = p.get("reaction", 300.0), p.get("cover", 50.0)
    bearing = p.get("bearing", 150.0)
    a = dap / 2  # the bearing's centre
    yb = h - nib + cover  # the nib's tie
    xh = dap + cover  # the hanger, just inside the full-depth beam
    xb = xh + h  # the B-region boundary, h further in
    nodes = [
        StmNode(id="A", x=a, y=yb, bearing=bearing, anchorage="plate"),
        StmNode(id="B", x=xh, y=yb, anchorage="through"),
        StmNode(id="C", x=xh, y=h - cover),
        StmNode(id="E", x=xb, y=h - cover, support="pin"),
        StmNode(id="F", x=xb, y=cover, support="pin", anchorage="through"),
    ]
    members = [
        ("1", "A", "C", 150.0),
        ("2", "A", "B", 0.0),
        ("3", "B", "C", 0.0),
        ("4", "B", "F", 150.0),
        ("5", "C", "E", 150.0),
        ("6", "C", "F", 150.0),
    ]
    return _model("Dapped end", "dappedEnd", t, h, p.get("fc", 35.0), p.get("fy", 420.0), nodes,
                  members, [StmLoad(node="A", fy=reaction)])  # fmt: skip


def _corbel(p: dict[str, float]) -> StmModel:
    h, t = p.get("depth", 500.0), p.get("thickness", 400.0)
    a, cover = p.get("shearSpan", 250.0), p.get("cover", 50.0)
    vu, nuc = p.get("load", 400.0), p.get("horizontal", 80.0)
    bearing = p.get("bearing", 150.0)
    nodes = [
        StmNode(id="P", x=a, y=h - cover, bearing=bearing, anchorage="plate"),
        StmNode(id="Q", x=-cover, y=h - cover, support="pin", anchorage="through"),
        StmNode(id="R", x=-cover, y=cover, support="pin"),
    ]
    members = [("1", "P", "Q", 0.0), ("2", "P", "R", 150.0)]
    return _model("Corbel", "corbel", t, h, p.get("fc", 28.0), p.get("fy", 420.0), nodes,
                  members, [StmLoad(node="P", fx=nuc, fy=-vu)],
                  [StmWebLayer(area=157.0, spacing=100.0, angle=0.0)])  # fmt: skip


def _frame_corner(p: dict[str, float]) -> StmModel:
    h, t = p.get("depth", 500.0), p.get("thickness", 300.0)
    moment, cover = p.get("moment", 200.0), p.get("cover", 60.0)  # kN·m, closing
    z = h - 2 * cover
    force = moment * 1e3 / z  # kN of the couple
    nodes = [
        StmNode(id="O", x=cover, y=h - cover, anchorage="through"),
        StmNode(id="I", x=h - cover, y=cover),
        StmNode(id="Bt", x=h + h, y=h - cover, anchorage="through"),
        StmNode(id="Bb", x=h + h, y=cover),
        StmNode(id="Co", x=cover, y=-h, support="pin", anchorage="through"),
        StmNode(id="Ci", x=h - cover, y=-h, support="pin"),
    ]
    members = [
        ("1", "O", "Bt", 0.0),
        ("2", "O", "Co", 0.0),
        ("3", "O", "I", 250.0),
        ("4", "I", "Bb", 250.0),
        ("5", "I", "Ci", 250.0),
        ("6", "Bt", "Bb", 150.0),
        ("7", "I", "Bt", 150.0),
        ("8", "I", "Co", 150.0),
    ]
    loads = [StmLoad(node="Bt", fx=force), StmLoad(node="Bb", fx=-force)]
    return _model("Frame corner", "frameCorner", t, h, p.get("fc", 28.0), p.get("fy", 420.0),
                  nodes, members, loads)  # fmt: skip


#: The templates: id -> (builder, title).
TEMPLATES = {
    "deepBeam": (_deep_beam, "Deep beam with a point load"),
    "dappedEnd": (_dapped_end, "Dapped end"),
    "corbel": (_corbel, "Corbel"),
    "frameCorner": (_frame_corner, "Frame corner, closing moment"),
}


def template(kind: str, parameters: dict[str, float] | None = None) -> StmModel:
    """A model to start from: ``kind`` one of :data:`TEMPLATES`, with its sizes and loads in
    ``parameters`` (mm, MPa, kN; the defaults where not given)."""
    if kind not in TEMPLATES:
        raise ValueError(f"no strut-and-tie template {kind!r}")
    return TEMPLATES[kind][0](parameters or {})
