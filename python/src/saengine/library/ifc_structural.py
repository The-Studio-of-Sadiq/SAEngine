"""Structural analysis view export for IFC (IFC4 and IFC2X3).

Writes ``IfcStructuralAnalysisModel`` with:
- ``IfcStructuralCurveMember`` for beams, columns and braces (analytical axes, sections, materials,
  and end releases);
- ``IfcStructuralSurfaceMember`` for slabs and walls (with thickness and material);
- ``IfcStructuralPointConnection`` nodes, with ``IfcBoundaryNodeCondition`` at supports;
- ``IfcStructuralLoadGroup`` per load case and load combination, with ``IfcStructuralPointAction``,
  ``IfcStructuralLinearAction`` and ``IfcStructuralPlanarAction`` loads;
- ``IfcRelAssignsToProduct`` linking each structural member back to its physical ``IfcElement``.

Reuses :mod:`saengine.exporters.analytical` (``AnalyticalModel``, ``joined_members``, ``local_axes``).
"""

from __future__ import annotations

import math
from typing import Any

from saengine.exporters.analytical import AnalyticalModel, joined_members, local_axes

# AnalyticalModel uses metres; IFC project length unit is millimetres.
_MM = 1000.0

_LOAD_ACTION: dict[str, tuple[str, str]] = {
    "D": ("PERMANENT_G", "DEAD_LOAD_G"),
    "SD": ("PERMANENT_G", "DEAD_LOAD_G"),
    "L": ("VARIABLE_Q", "LIVE_LOAD_Q"),
    "Lr": ("VARIABLE_Q", "LIVE_LOAD_Q"),
    "W": ("VARIABLE_Q", "WIND_W"),
    "E": ("EXTRAORDINARY_A", "EARTHQUAKE_E"),
    "other": ("VARIABLE_Q", "USERDEFINED"),
}


def _restraint_condition(w: Any, condition: Any, restraint: tuple[bool, ...]) -> None:
    """Populate translational and rotational stiffnesses on ``IfcBoundaryNodeCondition``."""
    names = (
        ("TranslationalStiffnessX", "TranslationalStiffnessY", "TranslationalStiffnessZ")
        if not w.is_ifc2x3
        else ("LinearStiffnessX", "LinearStiffnessY", "LinearStiffnessZ")
    )
    rot_names = ("RotationalStiffnessX", "RotationalStiffnessY", "RotationalStiffnessZ")
    for attr, fixed in zip(names, restraint[:3], strict=True):
        val = (
            -1.0
            if (w.is_ifc2x3 and fixed)
            else 0.0
            if w.is_ifc2x3
            else w.file.createIfcBoolean(bool(fixed))
        )
        setattr(condition, attr, val)
    for attr, fixed in zip(rot_names, restraint[3:6], strict=True):
        val = (
            -1.0
            if (w.is_ifc2x3 and fixed)
            else 0.0
            if w.is_ifc2x3
            else w.file.createIfcBoolean(bool(fixed))
        )
        setattr(condition, attr, val)


def _member_z_axis(
    a: tuple[float, float, float], b: tuple[float, float, float], rotation_deg: float
) -> tuple[float, float, float]:
    """Unit local Z axis of an analytical member rotated by ``rotation_deg`` about local X."""
    _, y0, z0 = local_axes(a, b)
    rad = math.radians(rotation_deg)
    z_rot = z0 * math.cos(rad) - y0 * math.sin(rad)
    norm = float(sum(float(v) * float(v) for v in z_rot) ** 0.5) or 1.0
    return (float(z_rot[0]) / norm, float(z_rot[1]) / norm, float(z_rot[2]) / norm)


def _pset(w: Any, product: Any, name: str, values: dict[str, Any]) -> None:
    if not values:
        return
    props = w.run("pset.add_pset", w.file, product=product, name=name)
    w.run("pset.edit_pset", w.file, pset=props, properties=values)


def export_structural_analysis(
    w: Any,
    analytical: AnalyticalModel,
    products: dict[str, Any],
    ids: dict[str, str],
    skipped: list[str],
) -> Any:
    """Add the structural analysis view of ``analytical`` to the IFC writer ``w``."""
    from saengine.library.ifc import _placement, global_id

    model = joined_members(analytical)
    f = w.file
    ref_context = w.run(
        "context.add_context",
        f,
        context_type="Model",
        context_identifier="Reference",
        target_view="GRAPH_VIEW",
        parent=w.body.ParentContext,
    )
    origin_matrix = _placement((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))

    sam = w.entity(
        "IfcStructuralAnalysisModel",
        model.name or "Structural Analysis",
        "analysis:model",
        "LOADING_3D",
    )
    ids["analysis:model"] = sam.GlobalId
    assigned_to_model: list[Any] = []

    # ── nodes and supports (only nodes referenced by at least one curve/surface member) ──
    member_nodes: set[int] = set()
    for m in model.members:
        if m.i in model.nodes and m.j in model.nodes:
            member_nodes.add(m.i)
            member_nodes.add(m.j)
    for p in model.plates:
        if len(p.nodes) >= 3 and all(nid in model.nodes for nid in p.nodes):
            member_nodes.update(p.nodes)

    vertices: dict[int, Any] = {}
    conns: dict[int, Any] = {}
    for nid in sorted(member_nodes):
        node = model.nodes[nid]
        x, y, z = (float(c) * _MM for c in node.xyz)
        pt = f.createIfcCartesianPoint((x, y, z))
        vtx = f.createIfcVertexPoint(pt)
        vertices[nid] = vtx

        conn = w.entity("IfcStructuralPointConnection", f"N{nid}", f"analysis:node:{nid}")
        w.place(conn, origin_matrix)
        rep = f.createIfcShapeRepresentation(ref_context, "Reference", "Vertex", [vtx])
        conn.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        if node.supported:
            bc = w.run(
                "structural.add_structural_boundary_condition",
                f,
                name=f"Support N{nid}",
                connection=conn,
            )
            _restraint_condition(w, bc, node.restraint)
        conns[nid] = conn
        assigned_to_model.append(conn)
        ids[f"analysis:node:{nid}"] = conn.GlobalId

    # ── curve members (beams, columns, braces) ──
    curve_members: dict[str, Any] = {}
    for m in model.members:
        if m.i not in vertices or m.j not in vertices:
            skipped.append(f"analysis:{m.id}: missing end node")
            continue
        pinned_both = {"M2", "M3"} <= m.releases[0] and {"M2", "M3"} <= m.releases[1]
        predefined = "PIN_JOINED_MEMBER" if pinned_both else "RIGID_JOINED_MEMBER"
        curve = w.entity(
            "IfcStructuralCurveMember",
            m.id,
            f"analysis:member:{m.id}",
            predefined,
        )
        curve.ObjectType = m.section
        curve.Description = f"{m.kind} ({m.section})"
        if not w.is_ifc2x3:
            curve.Axis = f.createIfcDirection(
                _member_z_axis(model.nodes[m.i].xyz, model.nodes[m.j].xyz, m.rotation)
            )
        w.place(curve, origin_matrix)
        edge = f.createIfcEdge(vertices[m.i], vertices[m.j])
        rep = f.createIfcShapeRepresentation(ref_context, "Reference", "Edge", [edge])
        curve.Representation = f.createIfcProductDefinitionShape(None, None, [rep])

        sec = model.sections.get(m.section)
        if sec is not None:
            if sec.material:
                w.material(curve, sec.material)
            _pset(
                w,
                curve,
                "SAEngine_AnalyticalSection",
                {
                    "Section": sec.name,
                    "Shape": sec.shape,
                    "Material": sec.material,
                    "Kind": m.kind,
                    "Rotation_deg": float(m.rotation),
                    "A_m2": float(sec.A),
                    "I33_m4": float(sec.I33),
                    "I22_m4": float(sec.I22),
                    "J_m4": float(sec.J),
                },
            )

        for end_idx, (nid, rel_set) in enumerate(((m.i, m.releases[0]), (m.j, m.releases[1]))):
            rel = w.run(
                "structural.add_structural_member_connection",
                f,
                relating_structural_member=curve,
                related_structural_connection=conns[nid],
            )
            if rel_set:
                bc = f.createIfcBoundaryNodeCondition(Name=f"{m.id}-end{end_idx + 1}")
                _restraint_condition(
                    w,
                    bc,
                    (
                        "P" not in rel_set,
                        "V2" not in rel_set,
                        "V3" not in rel_set,
                        "T" not in rel_set,
                        "M2" not in rel_set,
                        "M3" not in rel_set,
                    ),
                )
                rel.AppliedCondition = bc

        phys = products.get(m.source) or products.get(m.id)
        if phys is not None:
            w.run("structural.assign_product", f, relating_product=curve, related_object=phys)

        curve_members[m.id] = curve
        assigned_to_model.append(curve)
        ids[f"analysis:member:{m.id}"] = curve.GlobalId

    # ── surface members (slabs, walls) ──
    surface_members: dict[str, Any] = {}
    for p in model.plates:
        if len(p.nodes) < 3 or any(nid not in vertices for nid in p.nodes):
            skipped.append(f"analysis:{p.id}: invalid plate nodes")
            continue
        psec = model.plate_sections.get(p.section)
        predefined = "SHELL" if psec and psec.kind == "wall" else "BENDING_ELEMENT"
        surf = w.entity(
            "IfcStructuralSurfaceMember",
            p.id,
            f"analysis:plate:{p.id}",
            predefined,
        )
        surf.ObjectType = p.section
        if psec is not None:
            surf.Thickness = float(psec.thickness) * _MM
            if psec.material:
                w.material(surf, psec.material)
        w.place(surf, origin_matrix)
        pts = [vertices[nid].VertexGeometry for nid in p.nodes]
        loop = f.createIfcPolyLoop(pts)
        bound = f.createIfcFaceOuterBound(loop, True)
        face = f.createIfcFace([bound])
        rep = f.createIfcShapeRepresentation(ref_context, "Reference", "Face", [face])
        surf.Representation = f.createIfcProductDefinitionShape(None, None, [rep])

        phys = products.get(p.source) or products.get(p.id)
        if phys is not None:
            w.run("structural.assign_product", f, relating_product=surf, related_object=phys)

        for nid in p.nodes:
            w.run(
                "structural.add_structural_member_connection",
                f,
                relating_structural_member=surf,
                related_structural_connection=conns[nid],
            )

        surface_members[p.id] = surf
        assigned_to_model.append(surf)
        ids[f"analysis:plate:{p.id}"] = surf.GlobalId

    # ── load groups (cases + combinations) and structural actions ──
    load_groups: list[Any] = []
    case_groups: dict[str, Any] = {}
    for c in model.cases:
        actions: list[Any] = []
        for nid, forces in sorted(c.nodal.items()):
            if nid not in conns or not any(abs(float(v)) > 1e-9 for v in forces[:6]):
                continue
            vals = [float(v) for v in (list(forces) + [0.0] * 6)[:6]]
            load = f.createIfcStructuralLoadSingleForce(f"{c.name}-N{nid}", *vals)
            act = w.entity(
                "IfcStructuralPointAction",
                f"{c.name}-N{nid}",
                f"analysis:load:{c.name}:N{nid}",
                "DISCRETE",
            )
            act.AppliedLoad = load
            act.GlobalOrLocal = "GLOBAL_COORDS"
            if w.is_ifc2x3:
                act.DestabilizingLoad = False
            w.place(act, origin_matrix)
            rel = f.createIfcRelConnectsStructuralActivity(
                GlobalId=global_id(f"analysis:act:{c.name}:N{nid}"),
                RelatingElement=conns[nid],
                RelatedStructuralActivity=act,
            )
            if w.is_ifc2x3:
                rel.OwnerHistory = w.owner_history
            actions.append(act)

        for mid, wvec in sorted(c.uniform.items()):
            if mid not in curve_members or not any(abs(float(v)) > 1e-9 for v in wvec[:3]):
                continue
            vals = [float(v) for v in (list(wvec) + [0.0] * 3)[:3]]
            load = f.createIfcStructuralLoadLinearForce(f"{c.name}-{mid}", *vals, 0.0, 0.0, 0.0)
            act = w.entity(
                "IfcStructuralLinearAction",
                f"{c.name}-{mid}",
                f"analysis:load:{c.name}:{mid}",
                "CONST",
            )
            act.AppliedLoad = load
            act.GlobalOrLocal = "GLOBAL_COORDS"
            act.ProjectedOrTrue = "TRUE_LENGTH"
            if w.is_ifc2x3:
                act.DestabilizingLoad = False
            w.place(act, origin_matrix)
            rel = f.createIfcRelConnectsStructuralActivity(
                GlobalId=global_id(f"analysis:act:{c.name}:{mid}"),
                RelatingElement=curve_members[mid],
                RelatedStructuralActivity=act,
            )
            if w.is_ifc2x3:
                rel.OwnerHistory = w.owner_history
            actions.append(act)

        for mid, runs in sorted(c.partial.items()):
            if mid not in curve_members:
                continue
            for r_idx, (wvec, a_dist, b_dist) in enumerate(runs, start=1):
                if not any(abs(float(v)) > 1e-9 for v in wvec[:3]):
                    continue
                vals = [float(v) for v in (list(wvec) + [0.0] * 3)[:3]]
                load = f.createIfcStructuralLoadLinearForce(
                    f"{c.name}-{mid}-P{r_idx}", *vals, 0.0, 0.0, 0.0
                )
                act = w.entity(
                    "IfcStructuralLinearAction",
                    f"{c.name}-{mid}-P{r_idx}",
                    f"analysis:load:{c.name}:{mid}:P{r_idx}",
                    "CONST",
                )
                act.Description = f"from {a_dist:g} m to {b_dist:g} m"
                act.AppliedLoad = load
                act.GlobalOrLocal = "GLOBAL_COORDS"
                act.ProjectedOrTrue = "TRUE_LENGTH"
                if w.is_ifc2x3:
                    act.DestabilizingLoad = False
                w.place(act, origin_matrix)
                rel = f.createIfcRelConnectsStructuralActivity(
                    GlobalId=global_id(f"analysis:act:{c.name}:{mid}:P{r_idx}"),
                    RelatingElement=curve_members[mid],
                    RelatedStructuralActivity=act,
                )
                if w.is_ifc2x3:
                    rel.OwnerHistory = w.owner_history
                actions.append(act)

        if not actions:
            continue
        action_type, action_source = _LOAD_ACTION.get(c.kind, ("VARIABLE_Q", "USERDEFINED"))
        lg = w.entity(
            "IfcStructuralLoadGroup",
            c.name,
            f"analysis:case:{c.name}",
            "LOAD_CASE",
        )
        lg.Description = c.title_text()
        lg.ActionType = action_type
        lg.ActionSource = action_source
        lg.Purpose = "LOAD_CASE"
        w.run("group.assign_group", f, products=actions, group=lg)
        assigned_to_model.extend(actions)
        case_groups[c.name] = lg
        load_groups.append(lg)
        ids[f"analysis:case:{c.name}"] = lg.GlobalId

    for combo_name, factors in model.combinations:
        members_lg = [case_groups[k] for k in factors if k in case_groups]
        if not members_lg:
            continue
        combo_lg = w.entity(
            "IfcStructuralLoadGroup",
            combo_name,
            f"analysis:combo:{combo_name}",
            "LOAD_COMBINATION",
        )
        combo_lg.ActionType = "USERDEFINED"
        combo_lg.ActionSource = "USERDEFINED"
        combo_lg.Purpose = "ULS"
        _pset(
            w,
            combo_lg,
            "SAEngine_LoadCombination",
            {k: float(v) for k, v in factors.items()},
        )
        w.run("group.assign_group", f, products=members_lg, group=combo_lg)
        load_groups.append(combo_lg)
        ids[f"analysis:combo:{combo_name}"] = combo_lg.GlobalId

    if load_groups:
        sam.LoadedBy = tuple(load_groups)
    if assigned_to_model:
        w.run(
            "structural.assign_structural_analysis_model",
            f,
            products=assigned_to_model,
            structural_analysis_model=sam,
        )
    return sam
