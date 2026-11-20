"""Steel connection fabrication parts in IFC (plates, bolts, bolt holes and assemblies).

Reads the fabrication model (:func:`saengine.fabrication.model.build`) and writes:
- ``IfcPlate`` for connection plates (fin plates, end plates, flange plates, gussets, tabs,
  stiffeners, doublers, splice plates, base plates, cap plates);
- ``IfcOpeningElement`` voids cutting each plate at every bolt hole (``IfcRelVoidsElement``);
- ``IfcMechanicalFastener`` (IFC4) or ``IfcFastener`` (IFC2X3) for each bolt/anchor;
- ``IfcElementAssembly`` grouping the plates and bolts per connection, carrying the assembly
  and part marks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.fabrication.model import Assembly, Attached, FabricationModel, build
from saengine.library.bim import (
    BeamElement,
    BuildingModel,
    ColumnElement,
    MemberElement,
)
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary

_CLEARANCE = 10.0
_BOLT_OVERHANG = 10.0
_SI = 0.001


@dataclass
class _MemberFrame:
    start: np.ndarray
    end: np.ndarray
    u: np.ndarray
    x: np.ndarray
    y: np.ndarray
    depth: float
    width: float
    tw: float
    tf: float
    vertical: bool
    is_beam_element: bool


def _norm(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _member_frames(building: BuildingModel, objects: ObjectLibrary) -> dict[str, _MemberFrame]:
    from saengine.library.steel_sections import section_of_profile

    types = {o.id: o for o in objects.objects}
    frames: dict[str, _MemberFrame] = {}

    def add(
        eid: str,
        type_id: str,
        start_pt: tuple[float, float, float],
        end_pt: tuple[float, float, float],
        rotation_deg: float,
        *,
        is_column_element: bool = False,
        is_beam_element: bool = False,
    ) -> None:
        obj = types.get(type_id)
        if obj is None or getattr(obj, "profile", None) is None:
            return
        try:
            sec = section_of_profile(obj.profile)
        except (TypeError, ValueError, KeyError, AttributeError):
            sec = None
        s_arr = np.array(start_pt, dtype=float)
        e_arr = np.array(end_pt, dtype=float)
        u = _norm(e_arr - s_arr)
        rad = math.radians(rotation_deg)
        if is_column_element:
            x = np.array([math.cos(rad), math.sin(rad), 0.0], dtype=float)
            y = np.cross(u, x)
        elif is_beam_element:
            x = np.array([-u[1], u[0], 0.0], dtype=float)
            y = np.array([0.0, 0.0, 1.0], dtype=float)
        else:
            side = np.cross((0.0, 0.0, 1.0), u)
            x0 = _norm(side) if float(np.linalg.norm(side)) > 1e-9 else np.array([1.0, 0.0, 0.0])
            x = x0 * math.cos(rad) + np.cross(u, x0) * math.sin(rad)
            y = np.cross(u, x)
        depth = (
            float(sec.h)
            if sec is not None
            else float(getattr(obj.profile, "overallDepth", 200.0) or 200.0)
        )
        width = (
            float(sec.b)
            if sec is not None
            else float(getattr(obj.profile, "overallWidth", 100.0) or 100.0)
        )
        tw = float(sec.tw) if sec is not None else 8.0
        tf = float(sec.tf) if sec is not None else 10.0
        frames[eid] = _MemberFrame(
            s_arr,
            e_arr,
            u,
            x,
            y,
            depth,
            width,
            tw,
            tf,
            abs(float(u[2])) > 0.999,
            is_beam_element,
        )

    for el in building.elements:
        if isinstance(el, ColumnElement):
            add(
                el.id,
                el.type,
                (el.position[0], el.position[1], el.bottom),
                (el.position[0], el.position[1], el.top),
                el.rotation,
                is_column_element=True,
            )
        elif isinstance(el, BeamElement):
            add(
                el.id,
                el.type,
                (el.start[0], el.start[1], el.elevation),
                (el.end[0], el.end[1], el.elevation),
                0.0,
                is_beam_element=True,
            )
        elif isinstance(el, MemberElement):
            add(
                el.id,
                el.type,
                tuple(el.start),  # type: ignore[arg-type]
                tuple(el.end),  # type: ignore[arg-type]
                el.rotation,
            )
    for m in building.additions.members:
        add(m.id, m.type, (m.x1, m.y1, m.z1), (m.x2, m.y2, m.z2), 0.0)
    return frames


def _connection_key(asm: Assembly, att: Attached) -> tuple[str, str]:
    """Group plates belonging to the same physical connection into one assembly key."""
    role = att.part.role
    what = att.what or role
    if role == "base plate":
        return f"base:{asm.member}", f"{asm.member} base plate"
    if role == "cap plate":
        return f"cap:{asm.member}", f"{asm.member} cap plate"
    if role == "end plate":
        return f"end:{asm.member}:{att.face}", f"{asm.member} {att.face} end plate"
    if role == "splice plate":
        return f"splice:{asm.member}:{round(att.x)}", f"{asm.member} splice"
    m = re.search(r"\b(?:for|of)\s+([A-Za-z0-9_./-]+)", what)
    if m:
        target = m.group(1)
        return (
            f"conn:{asm.member}:{target}:{round(att.x / 500)}",
            f"{asm.member}-{target} connection",
        )
    return f"conn:{asm.member}:{role}:{round(att.x)}", f"{asm.member} {what}"


def _plate_pose(
    asm: Assembly,
    att: Attached,
    frame: _MemberFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(origin, local_x, local_z)`` in world mm for ``att.part`` (outline in X-Y, extruded +Z)."""
    part = att.part
    u, mx, my = frame.u, frame.x, frame.y
    base = np.array(asm.start, dtype=float)
    face = att.face
    role = part.role

    # Base / cap plates sit perpendicular to the column axis at the cut ends.
    if role in ("base plate", "cap plate") or (frame.vertical and face in ("start", "end")):
        px = mx
        pz = u
        py = np.cross(pz, px)
        z_pos = base + (0.0 if face == "start" else (asm.cut0 + asm.main.length) * u)
        origin = z_pos - px * (part.length / 2.0) - py * (part.h / 2.0)
        return origin, px, pz

    # End plate at beam/member start or end.
    if role == "end plate" or face in ("start", "end"):
        px = -my
        pz = u
        py = np.cross(pz, px)
        # Set-out centre on the member at cut0 (start) or cut0 + main.length (end).
        along = (asm.cut0 - part.tw) if face == "start" else (asm.cut0 + asm.main.length)
        mid_shift = -frame.depth / 2.0 if frame.is_beam_element else 0.0
        centre = base + along * u + mid_shift * my
        origin = centre - px * (part.length / 2.0) - py * (part.h / 2.0)
        return origin, px, pz

    # Splice plates on a member.
    if role == "splice plate":
        mid_shift = -frame.depth / 2.0 if frame.is_beam_element else 0.0
        pos = base + (asm.cut0 + att.x) * u + mid_shift * my
        if "top flange" in att.what:
            px, pz = u, my
            py = np.cross(pz, px)
            origin = pos + my * (frame.depth / 2.0) - px * (part.length / 2.0) - py * (part.h / 2.0)
            return origin, px, pz
        if "bottom flange" in att.what:
            px, pz = u, -my
            py = np.cross(pz, px)
            origin = pos - my * (frame.depth / 2.0) - px * (part.length / 2.0) - py * (part.h / 2.0)
            return origin, px, pz
        sign = -1.0 if "back" in att.what else 1.0
        px, pz = u, sign * mx
        py = np.cross(pz, px)
        origin = pos + sign * mx * (frame.tw / 2.0) - px * (part.length / 2.0) - py * (part.h / 2.0)
        return origin, px, pz

    # Stiffeners and doubler on column panel zone.
    if role == "stiffener":
        px, pz = mx, u
        py = np.cross(pz, px)
        sign = 1.0 if att.offset >= 0 else -1.0
        pos = base + (asm.cut0 + att.x) * u
        origin = pos + sign * mx * (frame.tw / 2.0) - (0.0 if sign > 0 else part.h * py)
        if sign > 0:
            origin = pos + mx * (frame.tw / 2.0) - px * (part.length / 2.0) - pz * (part.tw / 2.0)
        else:
            origin = (
                pos
                - mx * (frame.tw / 2.0 + part.h)
                - px * (part.length / 2.0)
                - pz * (part.tw / 2.0)
            )
        return origin, px, pz

    if role == "doubler":
        px, pz = u, mx
        py = np.cross(pz, px)
        pos = base + (asm.cut0 + att.x) * u
        origin = pos + mx * (frame.tw / 2.0) - py * (part.h / 2.0)
        return origin, px, pz

    # Fin plates, flange plates, gussets, tabs: use face + outward direction.
    # Determine outward direction along the supported member.
    if face == "o":
        outward = my
        reach = frame.depth / 2.0
    elif face == "u":
        outward = -my
        reach = frame.depth / 2.0
    elif face == "h":
        outward = -mx
        reach = frame.tw / 2.0
    elif face == "v" and frame.vertical:
        outward = mx
        reach = frame.tw / 2.0
    else:
        # Horizontal beam web or loose part: project along att.direction if known, else mx.
        if att.direction is not None:
            d_arr = np.array(att.direction, dtype=float)
            proj = float(np.dot(d_arr, mx))
            outward = mx if proj >= 0 else -mx
        else:
            outward = mx
        reach = frame.tw / 2.0

    # If the attached part has an explicit direction vector (e.g. a sloped brace or beam), keep it in-plane.
    if att.direction is not None and role == "flange plate":
        d_arr = _norm(np.array(att.direction, dtype=float))
        px = d_arr
        pz = my if "top" in att.what else -my
        py = np.cross(pz, px)
        z_face = base + (asm.cut0 + att.x) * u + outward * reach
        origin = z_face - py * (part.h / 2.0)
        return origin, px, pz

    if role == "gusset":
        px = u
        py = outward
        pz = _norm(np.cross(px, py))
        pos = base + (asm.cut0 + att.x) * u + outward * reach
        origin = pos - px * att.anchor - pz * (part.tw / 2.0)
        return origin, px, pz

    # Fin plate / tab: length along vertical (u on column, my on beam), width outward.
    if frame.vertical:
        px = u
        py = outward
        pz = _norm(np.cross(px, py))
        pos = base + (asm.cut0 + att.x) * u + outward * reach
        origin = pos - px * (part.length / 2.0) - pz * (part.tw / 2.0)
        return origin, px, pz

    px = my
    py = outward
    pz = _norm(np.cross(px, py))
    mid_shift = -frame.depth + att.offset if frame.is_beam_element else att.offset
    pos = base + (asm.cut0 + att.x) * u + my * mid_shift + outward * reach
    origin = pos - px * (part.length / 2.0) - pz * (part.tw / 2.0)
    return origin, px, pz


def export_steel_connections(
    w: Any,
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary | None,
    products: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
    fabrication: FabricationModel | None = None,
) -> int:
    """Export steel connection plates, bolts, bolt-hole openings and assemblies into ``w.file``.

    Returns the number of connection plates written.
    """
    from saengine.library.ifc import _placement

    fab = fabrication if fabrication is not None else build(building, objects, materials)
    if not fab.assemblies:
        return 0
    frames = _member_frames(building, objects)
    if not frames:
        return 0

    # Group attached plates into connection assemblies.
    groups: dict[str, tuple[str, Assembly, list[Attached]]] = {}
    for asm in fab.assemblies:
        for att in asm.parts:
            if att.part.kind != "plate":
                continue
            key, label = _connection_key(asm, att)
            if key not in groups:
                groups[key] = (label, asm, [])
            groups[key][2].append(att)

    written_plates = 0
    for conn_key, (label, asm, attached_list) in groups.items():
        base_id = asm.member.split("/")[0]
        frame = frames.get(base_id)
        if frame is None:
            continue

        storey = storey_at(min(float(asm.start[2]), float(asm.end[2])))
        assembly = w.entity(
            "IfcElementAssembly", label, f"assembly:{conn_key}", "ACCESSORY_ASSEMBLY"
        )
        assembly.Tag = asm.mark
        assembly.ObjectType = attached_list[0].part.role
        assembly.Description = f"Connection assembly {asm.mark} ({asm.member})"
        w.place(assembly, _placement((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        w.run("spatial.assign_container", w.file, products=[assembly], relating_structure=storey)
        asm_pset = w.run("pset.add_pset", w.file, product=assembly, name="SAEngine_Fabrication")
        w.run(
            "pset.edit_pset",
            w.file,
            pset=asm_pset,
            properties={
                "AssemblyMark": asm.mark,
                "Member": asm.member,
                "Connection": label,
            },
        )
        ids[f"conn:{conn_key}"] = assembly.GlobalId

        children: list[Any] = []
        for p_idx, att in enumerate(attached_list, start=1):
            part = att.part
            origin, px, pz = _plate_pose(asm, att, frame)
            py = _norm(np.cross(pz, px))
            plate_key = f"{conn_key}:p{p_idx}"

            plate = w.entity(
                "IfcPlate",
                f"{part.mark} {part.name}".strip() if part.mark else part.name,
                f"plate:{plate_key}",
                "SHEET",
            )
            plate.Tag = part.mark or None
            plate.ObjectType = part.role
            plate.Description = f"{part.profile} {part.grade}".strip()

            pts = [(float(x) * _SI, float(y) * _SI) for x, y in part.outline()]
            profile = w.run(
                "profile.add_arbitrary_profile",
                w.file,
                profile=[*pts, pts[0]],
                name=part.mark or part.profile,
            )
            w.extrusion(plate, profile, float(part.tw), None)
            w.place(plate, _placement(tuple(origin), tuple(px), tuple(pz)))
            w.material(plate, part.grade or "Steel")
            p_pset = w.run("pset.add_pset", w.file, product=plate, name="SAEngine_Fabrication")
            w.run(
                "pset.edit_pset",
                w.file,
                pset=p_pset,
                properties={
                    "PartMark": part.mark,
                    "AssemblyMark": asm.mark,
                    "Role": part.role,
                    "Profile": part.profile,
                    "Grade": part.grade,
                    "Thickness_mm": float(part.tw),
                    "Mass_kg": round(float(part.mass), 3),
                },
            )
            children.append(plate)
            ids[f"plate:{plate_key}"] = plate.GlobalId
            written_plates += 1

            # Avoid duplicate bolts on the back web splice plate (shares bolts with front web plate).
            skip_bolts = part.role == "splice plate" and "back" in (att.what or "")
            for h_idx, hole in enumerate(part.holes, start=1):
                hole_pos = origin + px * float(hole.x) + py * float(hole.y) - pz * _CLEARANCE
                hole_prof = w.param_profile("IfcCircleProfileDef")
                hole_prof.Radius = float(hole.dia) / 2.0
                void = w.entity(
                    "IfcOpeningElement",
                    f"{part.mark or 'P'}-H{h_idx}",
                    f"hole:{plate_key}:{h_idx}",
                    "OPENING",
                )
                void.Description = f"Bolt hole D{hole.dia:g}"
                w.extrusion(void, hole_prof, float(part.tw) + 2.0 * _CLEARANCE, None)
                w.place(void, _placement(tuple(hole_pos), tuple(px), tuple(pz)))
                w.run("feature.add_feature", w.file, feature=void, element=plate)
                ids[f"hole:{plate_key}:{h_idx}"] = void.GlobalId

                if skip_bolts:
                    continue
                bolt_dia = (
                    float(hole.bolt_dia) if hole.bolt_dia > 0 else max(float(hole.dia) - 2.0, 1.0)
                )
                bolt_len = float(part.tw) + 2.0 * _BOLT_OVERHANG
                bolt_cls = "IfcFastener" if w.is_ifc2x3 else "IfcMechanicalFastener"
                bolt_predef = None if w.is_ifc2x3 else "BOLT"
                bolt = w.entity(
                    bolt_cls,
                    f"M{bolt_dia:g}",
                    f"bolt:{plate_key}:{h_idx}",
                    bolt_predef,
                )
                bolt.Tag = f"M{bolt_dia:g}"
                bolt.ObjectType = "Bolt"
                if not w.is_ifc2x3:
                    bolt.NominalDiameter = bolt_dia
                    bolt.NominalLength = bolt_len
                bolt_prof = w.param_profile("IfcCircleProfileDef")
                bolt_prof.Radius = bolt_dia / 2.0
                bolt_pos = origin + px * float(hole.x) + py * float(hole.y) - pz * _BOLT_OVERHANG
                w.extrusion(bolt, bolt_prof, bolt_len, None)
                w.place(bolt, _placement(tuple(bolt_pos), tuple(px), tuple(pz)))
                children.append(bolt)
                ids[f"bolt:{plate_key}:{h_idx}"] = bolt.GlobalId

        if children:
            w.run("aggregate.assign_object", w.file, products=children, relating_object=assembly)
    return written_plates
