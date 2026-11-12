"""The reinforcement cages (:mod:`saengine.drawings.cages`) in the IFC of the building model:
one IfcReinforcingBar per bar mark of a member, its body one IfcSweptDiskSolid per physical
bar along the bar's centreline, in the storey of its lowest point.

IFC4 attributes: NominalDiameter, CrossSectionArea, BarLength (one bar), BarSurface TEXTURED
(deformed bars), PredefinedType MAIN (longitudinal) or LIGATURE (stirrups, hoops, ties; a spiral
is USERDEFINED "SPIRAL"), Tag the bar mark, ObjectType the role. Pset_ReinforcingBarCommon is not
written; ``SAEngine_Rebar`` holds the mark, the role, the count in the member and the member.

Ids in the returned map: ``rebar:<member>/<n>`` (the member is the building model element the
bars belong to), so the 3D view can show and hide them with their member.
"""

from __future__ import annotations

import math
from typing import Any


def export_rebar(
    w: Any, cages: dict[str, Any], storey_at: Any, ids: dict[str, str], skipped: list[str]
) -> int:
    """Adds the cages' bars to the IFC of the writer ``w`` (:class:`saengine.library.ifc._Writer`);
    returns how many IfcReinforcingBar were written."""
    from saengine.library.ifc import _placement

    f = w.file
    written = 0
    counters: dict[str, int] = {}
    for bar in cages.get("bars") or []:
        lines = [line for line in bar.get("lines") or [] if len(line) >= 2]
        if not lines:
            continue
        member = str(bar.get("member") or bar.get("element"))
        n = counters.get(member, 0)
        counters[member] = n + 1
        key = f"rebar:{member}/{n}"
        role = str(bar.get("role") or "")
        if role == "spiral":
            predefined = "USERDEFINED"
        elif bar.get("transverse"):
            predefined = "LIGATURE"
        else:
            predefined = "MAIN"
        mark = str(bar.get("mark") or "")
        try:
            product = w.entity("IfcReinforcingBar", mark or role, key, predefined)
            if role == "spiral":
                product.ObjectType = "SPIRAL"
            else:
                product.ObjectType = role
            dia = float(bar.get("dia") or 0.0)
            product.Tag = mark or None
            product.NominalDiameter = dia
            product.CrossSectionArea = math.pi * dia * dia / 4
            if bar.get("length"):
                product.BarLength = float(bar["length"])
            product.BarSurface = "TEXTURED"
            items = []
            for line in lines:
                points = [f.createIfcCartesianPoint([float(v) for v in p]) for p in line]
                items.append(f.createIfcSweptDiskSolid(f.createIfcPolyline(points), dia / 2))
            shape = f.createIfcShapeRepresentation(w.body, "Body", "AdvancedSweptSolid", items)
            product.Representation = f.createIfcProductDefinitionShape(None, None, [shape])
            w.place(product, _placement((0.0, 0.0, 0.0), (1, 0, 0), (0, 0, 1)))
            lowest = min(float(p[2]) for line in lines for p in line)
            w.run(
                "spatial.assign_container",
                f,
                products=[product],
                relating_structure=storey_at(lowest),
            )
            pset = w.run("pset.add_pset", f, product=product, name="SAEngine_Rebar")
            w.run(
                "pset.edit_pset",
                f,
                pset=pset,
                properties={
                    "Mark": mark,
                    "Role": role,
                    "Count": len(lines),
                    "Member": member,
                    "DetailingElement": str(bar.get("element") or ""),
                },
            )
        except Exception as error:  # noqa: BLE001 - one bar set does not stop the others
            skipped.append(f"{key}: reinforcement not written ({error})")
            continue
        ids[key] = product.GlobalId
        written += 1
    return written
