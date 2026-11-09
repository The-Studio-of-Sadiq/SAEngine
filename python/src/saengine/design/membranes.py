"""Tensile membranes and cable nets (alpha 9 L7): each ``membrane`` object type of 04 Objects
(:class:`saengine.library.objects.Membrane`) is form found from its prestress and analysed under
the code pack's ``membranes`` cases (:mod:`saengine.fem.form_finding`), then checked:

- the fabric's warp and fill stress per unit width against its strip strength over the pack's
  factor of the case's duration (``fabricFactors``); a cable net's cables like the edge cables;
- the edge cables' force against their breaking force over ``cableFactor``;
- wrinkling: the share of fabric links whose stress falls below ``wrinkleShare`` × the
  prestress (reported, not a strength check);
- the largest movement against span / ``deflectionLimit`` (when the pack gives one);
- the corner reactions are reported for the masts, anchors and their foundations.

A pack without the table does not cover membranes. Units: mm, N; reported in kN/m, kN, mm.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context

TABLE = "membranes"
KPA = 1e-3


def table() -> Any | None:
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery
        return None


def _clause(key: str) -> str:
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def _row(
    name: str, demand: float, capacity: float, unit: str, combo: str | None, note: str, key: str
) -> dict[str, Any]:
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


def found_form(membrane: Any) -> Any:
    """The membrane's found form (:class:`saengine.fem.form_finding.Net`)."""
    from saengine.fem import form_finding as ff

    corners = np.array([[c.x, c.y, c.z] for c in membrane.corners], dtype=float)
    net = ff.mesh(
        corners,
        int(membrane.divisions),
        float(membrane.prestressWarp),
        float(membrane.prestressFill),
        bool(membrane.edgeCables),
        float(membrane.cablePrestress) * 1e3,
    )
    return ff.find_form(net)


def _missing_load(case: Any, membrane: Any) -> str:
    """ "snow load", "wind pressure" or "wind suction" when the pack's ``case`` takes a load the
    membrane type leaves at 0; "" when every load it takes is given (or it takes none)."""
    if float(getattr(case, "snow", 0) or 0) > 0 and float(membrane.snow) <= 0:
        return "snow load"
    if float(getattr(case, "wind", 0) or 0) > 0:
        if case.windSign > 0 and float(membrane.windPressure) <= 0:
            return "wind pressure"
        if case.windSign < 0 and float(membrane.windSuction) <= 0:
            return "wind suction"
    return ""


def _stiffness(membrane: Any, form: Any) -> np.ndarray:
    """Axial stiffness of each link [N/mm]."""
    lengths = np.linalg.norm(form.xyz[form.links[:, 1]] - form.xyz[form.links[:, 0]], axis=1)
    lengths = np.maximum(lengths, 1e-9)
    cable = float(membrane.cables.modulus) * float(membrane.cables.area) / lengths
    out = np.zeros(len(form.kinds))
    for k, kind in enumerate(form.kinds):
        if kind == "cable" or membrane.system == "cableNet":
            out[k] = cable[k]
        else:
            et = membrane.fabric.stiffnessWarp if kind == "warp" else membrane.fabric.stiffnessFill
            out[k] = float(et) * form.width[k] / lengths[k]
    return out


def check_membrane(type_id: str, membrane: Any) -> dict[str, Any]:
    """The design entry of one membrane type."""
    from saengine.fem import form_finding as ff

    t = table()
    form = found_form(membrane)
    stiffness = _stiffness(membrane, form)
    kinds = np.array(form.kinds)
    fabric = kinds != "cable"
    cables = kinds == "cable"
    width = np.maximum(form.width, 1e-9)
    corners = np.array([[c.x, c.y, c.z] for c in membrane.corners], dtype=float)
    span = max(float(np.linalg.norm(corners[(k + 2) % 4][:2] - corners[k][:2])) for k in range(2))
    checks: list[dict[str, Any]] = []
    reactions = np.zeros(4)
    net = membrane.system == "cableNet"
    cable_rd = float(membrane.cables.breaking) * 1e3 / float(t.cableFactor)
    missing: list[str] = []
    for case in t.cases:
        # W4C-11 of usability walk 4: a case whose snow or wind the type does not give was
        # analysed as the prestress alone and reported as passing; it is not checked, and said.
        lacking = _missing_load(case, membrane)
        if lacking:
            missing.append(f"{case.name}: no {lacking} given")
            row = _row(
                f"{case.name}: not checked",
                0.0,
                0.0,
                "",
                case.name,
                f"no {lacking} given on the membrane type (04 Objects): the case is not "
                "analysed; enter the characteristic load to check it",
                "formFinding",
            )
            row.update(flag=True, ok=True, utilisation=0.0, status="noLoad")
            checks.append(row)
            continue
        pressure = (
            float(case.wind)
            * case.windSign
            * (float(membrane.windPressure) if case.windSign > 0 else float(membrane.windSuction))
        )
        found = ff.analyse(
            form,
            stiffness,
            snow=float(case.snow) * float(membrane.snow) * KPA,
            pressure=pressure * KPA,
            weight=float(membrane.fabric.weight) * KPA,
            prestress_factor=float(case.prestress),
        )
        reactions = np.maximum(reactions, found.reactions)
        factor = float(t.fabricFactors[case.duration])
        note_conv = "" if found.converged else "; not converged: check the form"
        for direction, strength in (
            ("warp", float(membrane.fabric.strengthWarp)),
            ("fill", float(membrane.fabric.strengthFill)),
        ):
            mask = kinds == direction
            if not mask.any():
                continue
            if net:
                demand = float(np.max(found.forces[mask]))
                checks.append(
                    _row(
                        f"Cable net ({direction}): {case.name}",
                        demand / 1e3,
                        cable_rd / 1e3,
                        "kN",
                        case.name,
                        f"breaking {float(membrane.cables.breaking):g} kN / "
                        f"{float(t.cableFactor):g}{note_conv}",
                        "cables",
                    )
                )
                continue
            stress = found.forces[mask] / width[mask]  # N/mm = kN/m
            checks.append(
                _row(
                    f"Fabric {direction} stress: {case.name}",
                    float(np.max(stress)),
                    strength / factor,
                    "kN/m",
                    case.name,
                    f"strip strength {strength:g} kN/m / {factor:g} ({case.duration} "
                    f"duration){note_conv}",
                    "fabric",
                )
            )
        if cables.any():
            demand = float(np.max(found.forces[cables]))
            checks.append(
                _row(
                    f"Edge cables: {case.name}",
                    demand / 1e3,
                    cable_rd / 1e3,
                    "kN",
                    case.name,
                    f"breaking {float(membrane.cables.breaking):g} kN / {float(t.cableFactor):g}",
                    "cables",
                )
            )
        if not net and fabric.any():
            pre = form.prestress[fabric] / width[fabric] * float(case.prestress)
            now = found.forces[fabric] / width[fabric]
            slack = float(np.mean(now < float(t.wrinkleShare) * pre)) if len(pre) else 0.0
            row = _row(
                f"Wrinkling: {case.name}",
                slack * 100,
                100.0,
                "%",
                case.name,
                f"links below {float(t.wrinkleShare):.0%} of the prestress (slack fabric); "
                "reported, not a strength check",
                "wrinkling",
            )
            row["flag"] = True
            checks.append(row)
        if float(t.deflectionLimit) > 0:
            checks.append(
                _row(
                    f"Movement: {case.name}",
                    found.movement,
                    span / float(t.deflectionLimit),
                    "mm",
                    case.name,
                    f"span {span:.0f} mm / {float(t.deflectionLimit):g}",
                    "formFinding",
                )
            )
    strength_rows = [c for c in checks if not c["flag"]]
    area, plan, _ = ff.node_areas(form, form.xyz)
    ends = form.links[cables]
    cable_length = float(
        np.sum(np.linalg.norm(form.xyz[ends[:, 1]] - form.xyz[ends[:, 0]], axis=1))
    )
    return {
        "id": type_id,
        "kind": "membrane",
        "type": type_id,
        "members": [],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength_rows), default=0.0),
        "ok": all(c["ok"] for c in strength_rows),
        "membrane": {
            "system": membrane.system,
            "nodes": len(form.xyz),
            "links": len(form.links),
            "area": round(float(np.sum(area)) / 1e6, 2),
            "planArea": round(float(np.sum(plan)) / 1e6, 2),
            "cableLength": round(cable_length / 1e3, 2),
            "reactions": [round(float(r) / 1e3, 2) for r in reactions],
            "form": [[round(float(v), 1) for v in p] for p in form.xyz],
            # W4C-11: the cases not analysed for want of their load ("<case>: no snow load
            # given"); the design notes list them.
            "missingLoads": missing,
        },
    }


def design_types(types: dict[str, Any]) -> tuple[list, list, list[str]]:
    """The membrane types of 04 Objects designed: (entries, skipped, notes)."""
    found = [(k, o) for k, o in types.items() if getattr(o, "kind", None) == "membrane"]
    if not found:
        return [], [], []
    if table() is None:
        return (
            [],
            [
                {
                    "id": k,
                    "kind": "membrane",
                    "type": k,
                    "reason": "tensile membranes are not covered by the code pack",
                    "status": "notCovered",  # W4C-6: not "no reinforcement", not a failure
                }
                for k, _ in found
            ],
            [],
        )
    entries, skipped = [], []
    for k, o in found:
        try:
            entries.append(check_membrane(k, o))
        except (np.linalg.LinAlgError, ValueError, KeyError) as error:
            skipped.append({"id": k, "kind": "membrane", "type": k, "reason": str(error)})
    notes = [
        f"membrane {e['id']}: {'; '.join(e['membrane']['missingLoads'])} on its type (04 "
        "Objects), so those cases are not checked (not passed): enter the characteristic snow "
        "and wind loads"
        for e in entries
        if e["membrane"].get("missingLoads")
    ]
    return entries, skipped, notes


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    cases = ", ".join(c.name for c in t.cases)
    return [
        (
            f"Tensile membranes and cable nets ({_clause('code')}): form found by force density "
            "from the prestress on four corners, then analysed (tension-only links, follower "
            f"pressures, dynamic relaxation) under {cases}; the fabric's stress against its strip "
            f"strength / {float(t.fabricFactors['short']):g} (short) or "
            f"/ {float(t.fabricFactors['long']):g} (long), cables against their breaking force / "
            f"{float(t.cableFactor):g}; wrinkling and the corner reactions reported."
        )
    ]
