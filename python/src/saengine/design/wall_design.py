"""Integrator glue: the structural walls of 06 BIM in the design report (:mod:`saengine.design.
check`), from the pier forces of :mod:`saengine.design.wall_forces` and the checks of
:mod:`saengine.design.walls`.

Per structural wall of a reinforced concrete type (04 Objects ``Wall`` with ``reinforcement``)
one design element of ``kind`` "wall": its piers (one per storey band, more where doors and
windows split it, bottom up) each checked by :func:`saengine.design.walls.wall_checks` from its
bottom, middle and top cuts; under a window or opening that leaves the wall continuous at a
level, the whole wall at the band's bottom level as one more "pier" (the continuous section,
the critical section of BNBC 2020 Part 6 Sec 8.3.6.6(b) at a wall's base); and for special
structural walls (the seismic scope puts Sec 8.3.6 in force, :func:`walls.special_applies`)
the boundary elements and the coupling beams (the spandrels over openings between two piers,
:func:`walls.coupling_beam_checks`). Spandrels over an opening between two piers that no
diagonal bars design are designed as beams (:func:`saengine.design.lintels.spandrel_design`),
and walls meeting in plan as flanged sections (:func:`design_flanged`,
:mod:`saengine.design.wall_flanges`).

The wall's height hw (for αc and the boundary elements' height) is that of the stack of
collinear wall elements it belongs to; δu/hw for the displacement-based boundary elements
(8.3.6.6(b)) is Cd δe / I at the stack's top (the largest in-plane displacement of its top
nodes over the earthquake combinations, Sec 2.5.9) over hw, for a stack that starts at the
lowest level (continuous from the base); otherwise the stress method of 8.3.6.6(c) is used.

The element is ``{"id", "kind": "wall", "type", "members" (every shell), "checks" (all its
piers' and coupling beams' checks, each note led by the pier), "utilisation", "ok",
"wallType" ("special" | "ordinary"), "curtains", "curtainsRequired", "boundary", "piers",
"couplingBeams", "notes"}`` (the shape the workbench's femWallsStairs.ts reads).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design import walls as W
from saengine.design.ductile_members import _row
from saengine.design.rc import DesignError

#: Static earthquake cases (as saengine.fem.combinations.EARTHQUAKE_CASES).
EARTHQUAKE_CASES = ("EX", "EY")
OMEGA = "Ω0: "

METHOD = [
    (
        "Walls (BNBC 2020 Part 6 Sec 6.6, 6.4.8; special structural walls Sec 8.3.6): the forces "
        "of each pier (the wall between openings in a storey) from section cuts of the shell "
        "model (the shells' nodal forces summed over the cut, as ETABS forms pier forces), at "
        "its bottom, middle and top; axial force with in-plane and out-of-plane bending on the "
        "pier's section with its distributed and end bars (strain compatibility, 6.6.4); "
        "in-plane shear by 6.4.8 (ordinary) or Eq. 6.8.9 (special); the minimum ratios, "
        "spacings and layers of 6.6.3, 6.4.8.9 and 8.3.6.2; the boundary elements of 8.3.6.6 "
        "(displacement-based with δu = Cd δe / I where the wall rises from the base, else the "
        "0.2 f'c stress trigger); coupling beams by 8.3.6.7. Under a window the whole wall at "
        "its bottom level is checked too (the continuous section)."
    ),
    (
        "Flanged walls (Sec 8.3.6.5): walls meeting at an L, T or C in a storey are checked as "
        "one section per direction, the walls along it webs and the others flanges of "
        "effective width min(half the distance to the adjacent web, 25 % of the wall height) "
        "beyond the web face (8.3.6.5(b), also for ordinary walls), with the sum of their "
        "piers' forces: axial force and biaxial bending by strain compatibility on the "
        "composite section, the webs' shear together (8.3.6.4(d)), boundary elements at the "
        "web ends and flanges (8.3.6.6(c), (d)(ii)); the rectangular piers' P-M and boundary "
        "rows are then informative. Spandrels over an opening between two piers without "
        "diagonal bars are designed as beams (8.3.6.7(a), (c); the capacity-design shear of "
        "8.3.8.1(a) for special walls)."
    ),
]


def _base_name(name: str) -> str:
    """A response spectrum pattern ``"<name> [<label>]"``'s combination."""
    if name.endswith("]") and " [" in name:
        return name.rsplit(" [", 1)[0]
    return name


def earthquake_names(combinations: list[Any]) -> set[str]:
    """Names of the design combinations (``saengine.fem.combinations.DesignCombination``) with
    earthquake: EX or EY among their factors, or a response spectrum envelope."""
    return {
        c.name
        for c in combinations
        if c.has_envelope or any(c.factors.get(k) for k in EARTHQUAKE_CASES)
    }


def _is_earthquake(name: str, earthquake: set[str]) -> bool:
    return name in earthquake or _base_name(name) in earthquake


def wall_stacks(building: Any) -> dict[str, tuple[float, float, list[str]]]:
    """Per wall element, the stack of collinear wall elements it belongs to (the same plan line,
    each starting where the one below ends): ``(bottom, top, ids)`` [mm]."""
    from saengine.library.bim import WallElement

    walls = [e for e in building.elements if isinstance(e, WallElement)]

    def line(e: Any) -> tuple[Any, ...]:
        a = (round(float(e.start[0])), round(float(e.start[1])))
        b = (round(float(e.end[0])), round(float(e.end[1])))
        return tuple(sorted((a, b)))

    by_line: dict[tuple[Any, ...], list[Any]] = {}
    for e in walls:
        by_line.setdefault(line(e), []).append(e)
    out: dict[str, tuple[float, float, list[str]]] = {}
    for group in by_line.values():
        group.sort(key=lambda e: float(e.bottom))
        stacks: list[list[Any]] = []
        for e in group:
            if stacks and abs(float(e.bottom) - float(stacks[-1][-1].top)) <= 1.0:
                stacks[-1].append(e)
            else:
                stacks.append([e])
        for stack in stacks:
            bottom = float(stack[0].bottom)
            top = max(float(e.top) for e in stack)
            ids = [e.id for e in stack]
            for e in stack:
                out[e.id] = (bottom, top, ids)
    return out


def wall_drift(
    project: dict[str, Any],
    stack: list[str],
    along: np.ndarray,
    height: float,
    displacements: list[dict[int, np.ndarray]],
    indices: list[int],
    factor: float,
) -> float | None:
    """δu/hw of a wall stack: ``factor`` (Cd / I) times the largest in-plane displacement of its
    top nodes (``along``: the wall's plan direction) over the combinations ``indices`` of
    ``displacements`` [m], over ``height`` [mm]; None when there are none."""
    names = set(stack)
    xyz = {int(n["id"]): n["coords"] for n in project.get("nodes", [])}
    nodes: set[int] = set()
    for e in project.get("elements", []):
        if e.get("type") == "Shell" and str(e.get("name") or e["id"]).split("#")[0] in names:
            nodes.update(int(n) for n in e.get("nodes", []))
    nodes = {n for n in nodes if n in xyz}
    if not nodes or height <= 0:
        return None
    z_top = max(float(xyz[n][2]) for n in nodes)
    top = [n for n in nodes if abs(float(xyz[n][2]) - z_top) < 1e-3]
    largest = None
    for c in indices:
        if c >= len(displacements):
            continue
        found = [displacements[c].get(n) for n in top]
        values = [abs(float(u[0] * along[0] + u[1] * along[1])) for u in found if u is not None]
        if values:
            mean = sum(values) / len(values)
            largest = mean if largest is None else max(largest, mean)
    if largest is None:
        return None
    return factor * largest * 1e3 / height


def _governing_forces(pier: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    """P, V2, M3 [kN, kN·m] of the pier's governing check's combination at the cut that check
    names ("... at W1/L1/P1 top"), else at its bottom cut."""
    strength = [c for c in checks if not c["flag"] and c.get("combination")]
    worst = max(strength, key=lambda c: c["utilisation"], default=None)
    cuts = pier.get("cuts", {})
    order = ["bottom", "middle", "top"]
    named = next((cut for cut in order if worst and f" {cut}" in str(worst.get("note", ""))), None)
    if named:
        order.remove(named)
        order.insert(0, named)
    for cut in order:
        rows = cuts.get(cut) or {}
        name = worst["combination"] if worst else next(iter(rows), None)
        if name in rows:
            r = rows[name]
            return {
                "combination": name,
                "P": round(float(r["P"]), 2),
                "V2": round(float(r["V2"]), 2),
                "M3": round(float(r["M3"]), 2),
            }
    return {}


def boundary_entry(need: W.BoundaryNeed | None, fc: float) -> dict[str, Any] | None:
    """The workbench's ``boundary`` of a pier or wall from :class:`walls.BoundaryNeed`."""
    if need is None:
        return None
    if need.method == "displacement":
        trigger = need.trigger or 0.0
        reason = (
            f"c = {need.c:.0f} mm {'≥' if need.required else '<'} lw / (600 δu/hw) = "
            f"{trigger:.0f} mm"
        )
        clause = "BNBC 2020 Part 6 Sec 8.3.6.6(b), Eq. 6.8.10"
    else:
        reason = (
            f"σ = {need.stress:.1f} MPa {'>' if need.required else '≤'} 0.2 f'c = "
            f"{W.special_limit('stressRequired') * fc:.1f} MPa"
        )
        clause = "BNBC 2020 Part 6 Sec 8.3.6.6(c)"
    if need.required and need.height:
        reason += f"; over {need.height:.0f} mm above the critical section"
    if not need.required and need.ties:
        reason += f"; end ties at ≤ 200 mm over {need.length:.0f} mm (8.3.6.6(e)(i))"
    return {
        "required": bool(need.required),
        "length": round(float(need.length), 0) if need.required else None,
        "reason": reason,
        "method": need.method,
        "clause": clause,
        "c": round(float(need.c), 1),
        "trigger": None if need.trigger is None else round(float(need.trigger), 1),
        "stress": round(float(need.stress), 2),
        "height": None if need.height is None else round(float(need.height), 0),
        "ties": bool(need.ties),
    }


def required_layers(geometry: W.WallGeometry, forces: list[W.PierForces], special: bool, fc: float):
    """Curtains required: two above 250 mm (6.6.3.4) or, in special walls, where Vu > 0.17 Acv
    λ √f'c (8.3.6.2(b))."""
    two_layers = W.steel_limit("twoLayerThickness")
    layers = 2 if geometry.thickness > two_layers and not geometry.basement else 1
    vu = max((abs(f.V2) for f in forces), default=0.0)
    if special and vu > W.special_limit("twoCurtainShare") * geometry.gross_area * math.sqrt(fc):
        layers = 2
    return layers


def design_walls(
    project: dict[str, Any],
    out_dir: str | Path,
    building: Any,
    types: dict[str, Any],
    mats: dict[str, Any],
    settings: Any,
    with_omega: Any,
    resolved: Any,
    scope: dict[str, Any] | None,
    extra: dict[str, Any],
    combinations: list[str],
    collect: dict[str, Any] | None = None,
    mep: Any = None,
    flanged: bool = True,
) -> dict[str, Any]:
    """The walls designed: ``{"elements", "skipped", "notes", "designed"}`` (``designed``: True
    when a wall was checked, for the report's method). ``flanged``: walls meeting at an L, T or
    C are checked as flanged sections too (:func:`design_flanged`). ``with_omega``: the settings with the
    Ω0 combinations check.py added (for the elements ``scope["omega"]`` names); ``resolved``:
    the settings with the site class the analysis used; ``extra``: check.py's ``extra``
    (``factors``, ``envelope``, ``lateralDisplacements``) for δu; ``combinations``: check.py's
    combination names (aligned with ``extra``). With ``collect``, ``collect["walls"]`` gets per
    pier what the design mode needs."""
    from saengine.design import seismic_detailing, seismic_rules, wall_forces
    from saengine.library.bim import WallElement
    from saengine.library.materials import Category
    from saengine.library.objects import Wall

    elements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    if collect is not None:
        collect.setdefault("walls", [])
    candidates = []
    for e in building.elements:
        if not isinstance(e, WallElement):
            continue
        t = types.get(e.type)
        if not isinstance(t, Wall) or not t.structural:
            continue  # partitions and infill: loads only, not designed
        candidates.append((e, t))
    if not candidates:
        return {"elements": [], "skipped": [], "notes": [], "designed": False}

    def skip(e: Any, reason: str) -> None:
        skipped.append({"id": e.id, "kind": "wall", "type": e.type, "reason": reason})

    ready = []
    masonry_ready: list[tuple[Any, Any, Any]] = []
    for e, t in candidates:
        concrete = mats.get(t.material)
        if concrete is not None and concrete.category == Category.MASONRY:
            # T31: masonry walls (saengine.design.masonry, the code pack's method).
            masonry_ready.append((e, t, concrete))
            continue
        if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
            skip(e, "not a concrete or masonry wall")
            continue
        if t.reinforcement is None:
            skip(e, "no reinforcement")
            continue
        bars = W.wall_bars(t.reinforcement)
        if bars is None:
            skip(e, "no vertical or horizontal bars entered")
            continue
        steel = mats.get(t.reinforcement.material)
        if steel is None or steel.steel is None:
            skip(e, f"unknown reinforcement material '{t.reinforcement.material}'")
            continue
        ready.append((e, t, bars, concrete, steel))
    if not ready and not masonry_ready:
        return {"elements": [], "skipped": skipped, "notes": notes, "designed": False}

    # The pier forces, with the combinations of check.py (the Ω0 ones for the response spectrum
    # appended as check.py appends them to its summary).
    from saengine.fem import seismic_design
    from saengine.fem.combinations import DesignCombination

    omega_elements = set((scope or {}).get("omega", {}).get("elements", []))
    try:
        found_combos, seismic, signs = wall_forces.design_combination_list(with_omega, out_dir)
        if seismic is not None and omega_elements:
            summary = seismic_design.load_summary(out_dir) or {}
            found_combos += [
                DesignCombination.from_json(c)
                for c in seismic_rules.omega_rs_combinations(
                    summary.get("combinations", []), resolved
                )
            ]
        found = wall_forces.wall_forces(project, building, out_dir, found_combos, seismic, signs)
    except (OSError, ValueError, KeyError) as error:
        for e, *_ in [*ready, *masonry_ready]:
            skip(e, f"the wall forces could not be found: {error}")
        return {"elements": [], "skipped": skipped, "notes": notes, "designed": False}
    notes += [f"walls: {n}" for n in found["notes"]]
    earthquake = earthquake_names(found_combos)

    def own_combinations(rows: dict[str, Any], wall_id: str) -> dict[str, Any]:
        if wall_id in omega_elements:
            return rows
        return {n: r for n, r in rows.items() if not n.startswith(OMEGA)}

    def filtered(part: dict[str, Any], key: str = "cuts") -> dict[str, Any]:
        return {
            **part,
            key: {
                cut: own_combinations(rows or {}, part["wall"])
                for cut, rows in part.get(key, {}).items()
            },
        }

    piers_of: dict[str, list[dict[str, Any]]] = {}
    for p in found["piers"]:
        piers_of.setdefault(p["wall"], []).append(filtered(p))
    spandrels_of: dict[str, list[dict[str, Any]]] = {}
    for s in found["spandrels"]:
        spandrels_of.setdefault(s["wall"], []).append(filtered(s))
    sections_of: dict[str, list[dict[str, Any]]] = {}
    for s in found["sections"]:
        sections_of.setdefault(s["wall"], []).append(filtered(s))

    stacks = wall_stacks(building)
    levels = sorted(s.elevation for s in building.stories)
    base_level = levels[0] if levels else 0.0
    story_names = {s.id: (s.name or s.id) for s in building.stories}
    # δu = Cd δxe / I (Part 6 Sec 2.5.7.7, Eq. 6.2.45, p. 631) amplifies the elastic deflection
    # under the design forces: the "Ω0: " combinations, whose E is already amplified by Ω0, never
    # set it, for Ω0 elements or not.
    eq_indices = [
        c
        for c in seismic_detailing.earthquake_indices(extra, len(combinations))
        if c >= len(combinations) or not str(combinations[c]).startswith(OMEGA)
    ]
    from saengine.library.settings import derived

    try:
        values = derived(settings)
        drift_factor = float(values["Cd"]) / float(values["seismicImportance"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError, AttributeError):
        drift_factor = None

    infos: dict[str, dict[str, Any]] = {}
    for e, t, bars, concrete, steel in ready:
        piers = piers_of.get(e.id, [])
        if not piers:
            skip(e, "not in the analysis results (no shells of the wall)")
            continue
        fc, fy = concrete.concrete.fc, steel.steel.fy
        es = steel.mechanical.E or 200_000.0
        special = W.special_applies(scope, t.structural)
        bottom, top, stack = stacks.get(e.id, (float(e.bottom), float(e.top), [e.id]))
        hw = top - bottom
        continuous = abs(bottom - base_level) <= 1.0
        run = np.array([e.end[0] - e.start[0], e.end[1] - e.start[1]], dtype=float)
        along = run / (np.linalg.norm(run) or 1.0)
        drift = None
        if special and continuous and drift_factor and eq_indices:
            drift = wall_drift(
                project,
                stack,
                along,
                hw,
                extra.get("lateralDisplacements", []),
                eq_indices,
                drift_factor,
            )
        options = {
            "braced": bool(getattr(t, "braced", True)),
            "restrained": bool(getattr(t, "restrainedEnds", True)),
            "basement": bool(getattr(t, "basement", False)),
            "continuous": continuous,
        }
        wall = _Wall(e, t, bars, fc, fy, es, special, drift, hw, options, earthquake, story_names)
        wall.collect = collect["walls"] if collect is not None else None
        for pier in piers:
            wall.part(pier, pier["pier"], ("bottom", "middle", "top"))
            if pier.get("holes"):
                wall.notes.append(
                    f"{pier['pier']}: small opening(s) {', '.join(pier['holes'])} in the pier are "
                    "not deducted from its section"
                )
        sections = sections_of.get(e.id, [])
        for section in sections:
            # The continuous section at the band's bottom under openings that do not reach it.
            segments = (section.get("segments") or {}).get("bottom") or []
            if len(section.get("piers", [])) > 1 and len(segments) == 1:
                wall.part(section, f"{section['section']} (whole wall)", ("bottom",), True)
        bottoms = {p.get("pier") or f"{p['section']} (whole wall)": p["bottom"] for p in sections}
        bottoms.update({p["pier"]: p["bottom"] for p in piers})
        wall.piers.sort(key=lambda p: (float(bottoms.get(p["id"], 0.0)), p["id"]))

        beams: list[dict[str, Any]] = []
        if special:
            beams = _coupling_beams(e, t, spandrels_of.get(e.id, []), piers, fc, fy, story_names)
        # Spandrels over an opening between two piers that no diagonal bars design: as beams
        # (8.3.6.7(a), (c) for special walls; Chapter 6 for ordinary walls).
        beams = _beam_spandrels(
            e,
            t,
            spandrels_of.get(e.id, []),
            piers,
            beams,
            fc,
            fy,
            es,
            special,
            earthquake,
            story_names,
        )
        for b in beams:
            for c in b["checks"]:
                note = f"{b['id']}: {c['note']}" if c["note"] else b["id"]
                wall.checks.append({**c, "note": note})
        designed = {b["id"] for b in beams if b["ok"] is not None}
        by_id = {b["id"]: b for b in beams}
        for s in spandrels_of.get(e.id, []):
            # The spandrel's shells stay with the wall (selecting one shows the wall), but a
            # spandrel without a strength check is listed as not designed (report.skipped and
            # the wall's notes), never as passing.
            wall.members.update(s.get("shells", []))
            if s["spandrel"] in designed:
                continue
            beam = by_id.get(s["spandrel"])
            if beam is not None:
                reason = (
                    f"coupling beam, ln/h = {beam['ln'] / beam['h']:.2f}: not designed here "
                    + (
                        "(as a special moment frame beam, 8.3.6.7(a))"
                        if beam["mode"] == "flexural"
                        else "(enter diagonal bars on the wall type, 8.3.6.7(c)-(d), or design "
                        "it to the beam rules of 8.3.6.7(c))"
                    )
                )
            else:
                where = "over" if s.get("position") == "above" else "under"
                reason = (
                    f"spandrel (the wall {where} an opening): not designed here; design it as a "
                    "lintel or deep beam"
                )
            skipped.append(
                {"id": s["spandrel"], "kind": "spandrel", "type": e.type, "reason": reason}
            )
            wall.notes.append(f"{s['spandrel']}: {reason}")

        if not wall.piers:
            skip(e, "; ".join(wall.notes) or "no pier could be checked")
            continue
        strength = [c for c in wall.checks if not c["flag"]]
        own_notes = wall.notes + [n for p in wall.piers for n in p["notes"]]
        elements.append(
            {
                "id": e.id,
                "kind": "wall",
                "type": e.type,
                "members": sorted(wall.members),
                "checks": wall.checks,
                "utilisation": max((c["utilisation"] for c in strength), default=0.0),
                "ok": all(c["ok"] for c in strength),
                "wallType": "special" if special else "ordinary",
                "curtains": bars.layers,
                "curtainsRequired": wall.layers_required,
                "boundary": _wall_boundary(wall.piers),
                "piers": wall.piers,
                "couplingBeams": beams,
                "drift": None if drift is None else round(drift, 5),
                "height": hw,
                "notes": list(dict.fromkeys(own_notes)),
            }
        )
        infos[e.id] = {
            "fc": fc,
            "fy": fy,
            "es": es,
            "special": special,
            "drift": drift,
            "height": hw,
            "continuous": continuous,
        }
    if flanged and elements:
        notes += design_flanged(building, types, elements, piers_of, infos, earthquake, story_names)
    concrete_designed = bool(elements)
    masonry_piers: dict[str, list[dict[str, Any]]] = piers_of
    masonry_lateral: frozenset[str] = frozenset(earthquake)
    if masonry_ready:
        masonry_piers, masonry_lateral, masonry_notes = _masonry_forces(
            project, building, out_dir, piers_of, earthquake
        )
        notes += masonry_notes
    masonry_elements = _design_masonry(
        masonry_ready,
        masonry_piers,
        spandrels_of,
        stacks,
        story_names,
        mats,
        skipped,
        masonry_lateral,
        len(building.stories),
    )
    elements += masonry_elements
    return {
        "elements": elements,
        "skipped": skipped,
        "notes": notes,
        "designed": concrete_designed,
        "masonry": bool(masonry_elements),
    }


def _masonry_forces(
    project: dict[str, Any],
    building: Any,
    out_dir: str | Path,
    piers_of: dict[str, list[dict[str, Any]]],
    earthquake: set[str],
) -> tuple[dict[str, list[dict[str, Any]]], frozenset[str], list[str]]:
    """The masonry walls' pier forces under the combinations of the code pack's masonry method
    (:func:`saengine.design.masonry.combinations_kind`): ``(piers by wall, the combinations with
    wind or earthquake, notes)``. The design combinations' piers (``piers_of``) serve a
    strength method; an allowable stress method gets the pack's allowable stress combinations,
    the gravity cases the model lacks (SD, L, Lr) taken as zero and the combinations whose wind
    or earthquake cases have no results left out."""
    from saengine.design import masonry as M
    from saengine.design import wall_forces
    from saengine.fem.combinations import DesignCombination, allowable_combinations

    if M.combinations_kind() != "allowable":
        return piers_of, frozenset(earthquake), []
    notes: list[str] = []
    try:
        cases = wall_forces.case_shell_forces(project, out_dir)
    except (OSError, ValueError, KeyError) as error:
        return {}, frozenset(), [f"masonry walls: the load cases' forces were not found: {error}"]
    present = set(cases)
    formed = allowable_combinations(present)
    combos: list[Any] = []
    left_out = 0
    for name, factors in formed:
        own = {
            c: v for c, v in factors.items() if v and (c in present or c not in ("SD", "L", "Lr"))
        }
        if any(c not in present for c in own):
            left_out += 1
            continue
        combos.append(DesignCombination(name, own))
    if left_out:
        notes.append(
            f"masonry walls: {left_out} allowable stress combinations left out (their wind or "
            "earthquake cases have no results)"
        )
    if not combos:
        return {}, frozenset(), notes + ["masonry walls: no allowable stress combinations"]
    found = wall_forces.wall_forces(project, building, cases, combos)
    lateral = frozenset(
        c.name for c in combos if any(k[:1] in ("W", "E") and v for k, v in c.factors.items())
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for p in found["piers"]:
        out.setdefault(p["wall"], []).append(p)
    return out, lateral, notes


def _design_masonry(
    masonry_ready: list[tuple[Any, Any, Any]],
    piers_of: dict[str, list[dict[str, Any]]],
    spandrels_of: dict[str, list[dict[str, Any]]],
    stacks: dict[str, tuple[float, float, list[str]]],
    story_names: dict[str, str],
    mats: dict[str, Any],
    skipped: list[dict[str, Any]],
    lateral: frozenset[str] = frozenset(),
    storeys: int | None = None,
) -> list[dict[str, Any]]:
    """T31 integrator glue: the masonry walls' design elements (``kind`` "wall", ``wallType``
    "masonryPlain" or "masonryReinforced"), each pier checked by
    :func:`saengine.design.masonry.masonry_wall_checks` (the code pack's method) from the
    forces of its combinations (``piers_of``; ``lateral`` those with wind or earthquake); walls
    that cannot be checked go to ``skipped``."""
    from saengine.design import masonry as M

    out: list[dict[str, Any]] = []
    for e, t, material in masonry_ready:

        def skip(reason: str, e: Any = e) -> None:
            skipped.append({"id": e.id, "kind": "wall", "type": e.type, "reason": reason})

        piers = piers_of.get(e.id, [])
        if not piers:
            skip("not in the analysis results (no shells of the wall)")
            continue
        try:
            m = M.masonry_of(material, mats)
        except DesignError as error:
            skip(str(error))
            continue
        bars = W.wall_bars(t.reinforcement) if t.reinforcement is not None else None
        fy = 420.0
        if bars is not None:
            steel = mats.get(t.reinforcement.material)
            if steel is None or steel.steel is None:
                skip(f"unknown reinforcement material '{t.reinforcement.material}'")
                continue
            fy = steel.steel.fy
        bottom, top, _stack = stacks.get(e.id, (float(e.bottom), float(e.top), [e.id]))
        hw = top - bottom
        options = {
            "braced": bool(getattr(t, "braced", True)),
            "restrained": bool(getattr(t, "restrainedEnds", True)),
            "basement": bool(getattr(t, "basement", False)),
        }
        entries: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        members: set[int] = set()
        notes: list[str] = []
        for pier in piers:
            name = pier["pier"]
            geometry = W.geometry_of(pier, wall_height=hw, **options)
            forces = W.pier_rows(pier, None, ("bottom", "middle", "top"))
            try:
                d = M.masonry_wall_checks(geometry, bars, forces, m, fy, lateral, storeys)
            except DesignError as error:
                notes.append(f"{name}: not checked: {error}")
                d = M.MasonryDesign(
                    [_row("Masonry wall checked", 1.0, 0.0, "", note=f"{error}; not checked")],
                    [],
                    99.0,
                )
            entry = {
                "id": name,
                "storey": story_names.get(pier.get("storey"), pier.get("storey") or ""),
                "lw": round(float(pier["lw"]), 1),
                "tw": round(float(pier["tw"]), 1),
                "members": list(pier.get("shells", [])),
                "forces": _governing_forces(pier, d.checks),
                "checks": d.checks,
                "utilisation": d.utilisation,
                "ok": all(c["ok"] for c in d.checks if not c["flag"]),
                "boundary": None,
                "whole": False,
                "notes": d.notes,
                "holes": list(pier.get("holes", [])),
            }
            entries.append(entry)
            members.update(entry["members"])
            for c in d.checks:
                checks.append({**c, "note": f"{name}: {c['note']}" if c["note"] else name})
        for s in spandrels_of.get(e.id, []):
            members.update(s.get("shells", []))
            reason = (
                "spandrel of a masonry wall (over or under an opening): not designed here; "
                "design it as a lintel"
            )
            skipped.append(
                {"id": s["spandrel"], "kind": "spandrel", "type": e.type, "reason": reason}
            )
            notes.append(f"{s['spandrel']}: {reason}")
        strength = [c for c in checks if not c["flag"]]
        out.append(
            {
                "id": e.id,
                "kind": "wall",
                "type": e.type,
                "members": sorted(members),
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in strength), default=0.0),
                "ok": all(c["ok"] for c in strength),
                "wallType": "masonryReinforced" if bars is not None else "masonryPlain",
                "masonry": M.describe(m, bars is not None),
                # B18: the masonry row of the fire checks (design/fire_resistance.py).
                "fireMasonry": M.fire_row(m),
                "curtains": bars.layers if bars is not None else None,
                "curtainsRequired": None,
                "boundary": None,
                "piers": entries,
                "couplingBeams": [],
                "drift": None,
                "height": hw,
                "notes": list(dict.fromkeys(notes + [n for p in entries for n in p["notes"]])),
            }
        )
    return out


@dataclass
class _Wall:
    """One wall being designed: what its piers share, and what they add up to."""

    element: Any
    object: Any
    bars: W.WallBars
    fc: float
    fy: float
    es: float
    special: bool
    drift: float | None
    height: float
    options: dict[str, Any]
    earthquake: set[str]
    story_names: dict[str, str]
    collect: list[dict[str, Any]] | None = None
    notes: list[str] = field(default_factory=list)
    piers: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    members: set[int] = field(default_factory=set)
    layers_required: int = 1

    def part(
        self, part: dict[str, Any], name: str, cuts: tuple[str, ...], whole: bool = False
    ) -> None:
        """Checks a pier (or the whole wall at a level, ``whole``) from its ``cuts``."""
        geometry = W.geometry_of(part, wall_height=self.height, **self.options)
        forces = [
            replace(f, earthquake=_is_earthquake(f.combination or "", self.earthquake))
            for f in W.pier_rows({**part, "pier": name}, None, cuts)
        ]
        if not forces:
            self.notes.append(f"{name}: no forces at its cuts; not checked")
            return
        fc = self.fc
        try:
            d = W.wall_checks(
                geometry,
                self.bars,
                forces,
                fc,
                self.fy,
                self.es,
                special=self.special,
                drift=self.drift,
            )
        except DesignError as error:
            # Not checked is not passing: the pier stays in the wall with a failing row.
            self.notes.append(f"{name}: not checked: {error}")
            self._unchecked(part, name, geometry, forces, str(error), whole)
            return
        self.layers_required = max(
            self.layers_required, required_layers(geometry, forces, self.special, fc)
        )
        need = d.need.boundary if d.need else None
        entry = {
            "id": name,
            "storey": self.story_names.get(part.get("storey"), part.get("storey") or ""),
            "lw": round(float(part["lw"]), 1),
            "tw": round(float(part["tw"]), 1),
            "members": list(part.get("shells", [])),
            "forces": _governing_forces(part, d.checks),
            "checks": d.checks,
            "utilisation": d.utilisation,
            "ok": all(c["ok"] for c in d.checks if not c["flag"]),
            "boundary": boundary_entry(need, fc) if self.special else None,
            "whole": whole,
            "notes": d.notes,
            "holes": list(part.get("holes", [])),
        }
        self.piers.append(entry)
        self.members.update(entry["members"])
        for c in d.checks:
            self.checks.append({**c, "note": f"{name}: {c['note']}" if c["note"] else name})
        if self.collect is not None:
            self.collect.append(
                {
                    "id": name,
                    "wall": self.element.id,
                    "type": self.element.type,
                    "object": self.object,
                    "geometry": geometry,
                    "forces": forces,
                    "fc": fc,
                    "fy": self.fy,
                    "es": self.es,
                    "special": self.special,
                    "drift": self.drift,
                    "need": d.need,
                    "checks": d.checks,
                    "whole": whole,
                }
            )

    def _unchecked(
        self,
        part: dict[str, Any],
        name: str,
        geometry: W.WallGeometry,
        forces: list[W.PierForces],
        error: str,
        whole: bool,
    ) -> None:
        """A pier the type's bars cannot be laid out in: one failing row, so the wall fails."""
        lw = float(part["lw"])
        b = self.bars.boundary
        if b is not None and 2 * b.length >= lw:
            row = _row(
                "End bars fit in the pier: 2 × end length < lw",
                2 * b.length,
                lw,
                "mm",
                note=f"{error}; a longer pier, or a wall type without end bars for it",
            )
        else:
            row = _row(
                "Bars of the wall type laid out in the pier",
                1.0,
                0.0,
                "",
                note=f"{error}; not checked",
            )
        entry = {
            "id": name,
            "storey": self.story_names.get(part.get("storey"), part.get("storey") or ""),
            "lw": round(lw, 1),
            "tw": round(float(part["tw"]), 1),
            "members": list(part.get("shells", [])),
            "forces": _governing_forces(part, []),
            "checks": [row],
            "utilisation": row["utilisation"],
            "ok": False,
            "boundary": None,
            "whole": whole,
            "notes": [f"not checked: {error}"],
            "holes": list(part.get("holes", [])),
        }
        self.piers.append(entry)
        self.members.update(entry["members"])
        self.checks.append({**row, "note": f"{name}: {row['note']}"})
        if self.collect is not None:
            self.collect.append(
                {
                    "id": name,
                    "wall": self.element.id,
                    "type": self.element.type,
                    "object": self.object,
                    "geometry": geometry,
                    "forces": forces,
                    "fc": self.fc,
                    "fy": self.fy,
                    "es": self.es,
                    "special": self.special,
                    "drift": self.drift,
                    "need": None,
                    "checks": [row],
                    "whole": whole,
                    "error": error,
                }
            )


def _wall_boundary(piers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The wall's boundary elements: the longest required of its piers', else its lowest
    pier's (the critical section)."""
    found = [p["boundary"] for p in piers if p.get("boundary")]
    if not found:
        return None
    required = [b for b in found if b["required"]]
    if required:
        return max(required, key=lambda b: b["length"] or 0.0)
    return found[0]


def _coupling_beams(
    wall: Any,
    wall_type: Any,
    spandrels: list[dict[str, Any]],
    piers: list[dict[str, Any]],
    fc: float,
    fy: float,
    story_names: dict[str, str],
) -> list[dict[str, Any]]:
    """The coupling beams of a special wall: its spandrels over an opening with a pier on each
    side (8.3.6.7), checked with the type's diagonal bars (``reinforcement.diagonal``)."""
    diagonal_bars = getattr(wall_type.reinforcement, "diagonal", None)
    cover = float(wall_type.reinforcement.cover)
    out = []
    for s in spandrels:
        if s.get("position") != "above":
            continue
        beside = [p for p in piers if s["spandrel"] in p.get("spandrels", [])]
        if len(beside) < 2:
            continue
        vu, combination = 0.0, None
        for rows in s.get("cuts", {}).values():
            for name, r in (rows or {}).items():
                if abs(float(r["V2"])) > vu:
                    vu, combination = abs(float(r["V2"])), name
        ln, h, bw = float(s["length"]), float(s["depth"]), float(s["tw"])
        diagonal = None
        if diagonal_bars is not None:
            angle = getattr(diagonal_bars, "angle", None)
            diagonal = W.Diagonal(
                int(diagonal_bars.count),
                float(diagonal_bars.dia),
                angle=math.radians(angle) if angle else None,
            )
        found = W.coupling_beam_checks(
            ln, h, bw, vu * 1e3, fc, fy, diagonal=diagonal, combination=combination, cover=cover
        )
        notes = list(found.notes)
        if found.mode == "flexural":
            notes.append(
                "checked as a spandrel of the wall: its design as a special moment frame beam "
                "(8.3.4) is not done here"
            )
        if found.proposal is not None and diagonal is None and found.mode != "flexural":
            notes.append(
                f"diagonal bars: {found.proposal.count} Ø{found.proposal.dia:g} per group would do"
            )
        strength = [c for c in found.checks if not c["flag"]]
        if not strength:
            notes.append("not designed: no strength check applies with the bars entered")
        out.append(
            {
                "id": s["spandrel"],
                "storey": story_names.get(s.get("storey"), s.get("storey") or ""),
                "ln": round(ln, 1),
                "h": round(h, 1),
                "mode": found.mode,
                "diagonal": found.mode == "diagonal" or diagonal is not None,
                "checks": found.checks,
                # None (not designed), never 0.0 and ok: an unchecked beam does not pass.
                "utilisation": max((c["utilisation"] for c in strength), default=None),
                "ok": all(c["ok"] for c in strength) if strength else None,
                "notes": notes,
            }
        )
    return out


def _beam_spandrels(
    wall: Any,
    wall_type: Any,
    spandrels: list[dict[str, Any]],
    piers: list[dict[str, Any]],
    beams: list[dict[str, Any]],
    fc: float,
    fy: float,
    es: float,
    special: bool,
    earthquake: set[str],
    story_names: dict[str, str],
) -> list[dict[str, Any]]:
    """``beams`` (the coupling beams checked with diagonal bars) with every spandrel over an
    opening between two piers that they leave without a strength check designed as a beam
    (:func:`saengine.design.lintels.spandrel_design`): special walls' flexural (ln/h > 4) and
    "either" coupling beams without diagonal bars (8.3.6.7(a), (c)), ordinary walls' spandrels."""
    from saengine.design import lintels

    by_id = {b["id"]: b for b in beams}
    cover = float(wall_type.reinforcement.cover)
    out = list(beams)
    for s in spandrels:
        if s.get("position") != "above":
            continue
        beside = [p for p in piers if s["spandrel"] in p.get("spandrels", [])]
        if len(beside) < 2:
            continue
        old = by_id.get(s["spandrel"])
        if old is not None and old["ok"] is not None:
            continue  # designed with its diagonal bars
        names = {n for rows in (s.get("cuts") or {}).values() for n in (rows or {})}
        found = lintels.spandrel_design(
            s,
            fc,
            fy,
            special=special,
            earthquake={n for n in names if _is_earthquake(n, earthquake)},
            cover=cover,
            es=es,
        )
        if found["ok"] is None:
            continue  # diagonal bars required: the coupling beam's own failing row stays
        entry = {
            "id": s["spandrel"],
            "storey": story_names.get(s.get("storey"), s.get("storey") or ""),
            "ln": found["ln"],
            "h": found["h"],
            "mode": found["mode"],
            "diagonal": False,
            "checks": found["checks"],
            "utilisation": found["utilisation"],
            "ok": found["ok"],
            "bars": found["bars"],
            "label": found["label"],
            "notes": [
                *(
                    n
                    for n in (old["notes"] if old else [])
                    if "not designed" not in n and "not done here" not in n
                ),
                *found["notes"],
            ],
        }
        if old is not None:
            out[out.index(old)] = entry
        else:
            out.append(entry)
    return out


def design_flanged(
    building: Any,
    types: dict[str, Any],
    elements: list[dict[str, Any]],
    piers_of: dict[str, list[dict[str, Any]]],
    infos: dict[str, dict[str, Any]],
    earthquake: set[str],
    story_names: dict[str, str],
) -> list[str]:
    """Walls meeting at an L, T or C checked as one flanged section per storey
    (:mod:`saengine.design.wall_flanges`), in place on the wall ``elements``: each wall of a
    group gets ``flanged`` entries ``{"id", "walls", "storey", "sections", "checks",
    "utilisation", "ok", "boundary", "notes"}`` and their checks (led by the group's id); its
    piers' rectangular P-M and boundary-element rows in that storey become informative
    (superseded). A storey where a door or window splits a wall of the group keeps the
    rectangular piers (a note). Returns notes for the report."""
    from saengine.design import wall_flanges as WF

    by_id = {e["id"]: e for e in elements}
    notes: list[str] = []
    designed = {k for k in infos if k in by_id}
    groups = WF.wall_groups(building, types, designed)
    # Walls touching a group that are not designed RC walls (brick infill against a core, an
    # RC wall without bars): not taken as flanges, said so.
    grouped = {leg.id for g in groups for leg in g.legs}
    for g in WF.wall_groups(building, types):
        others = sorted(leg.id for leg in g.legs if leg.id not in designed)
        touched = sorted(leg.id for leg in g.legs if leg.id in grouped)
        if others and touched:
            notes.append(
                f"walls: {', '.join(others)} meet{'s' if len(others) == 1 else ''} "
                f"{', '.join(touched)} but {'is' if len(others) == 1 else 'are'} not a designed "
                "RC wall: not taken as a flange (left out of the flanged section)"
            )
    superseded = ("Axial force and bending P-M3-M2", "Boundary element")
    for group in groups:
        info = [infos[leg.id] for leg in group.legs]
        fc, fy = min(i["fc"] for i in info), min(i["fy"] for i in info)
        es = info[0]["es"]
        special = any(i["special"] for i in info)
        drifts = [i["drift"] for i in info if i["drift"] is not None]
        drift = max(drifts) if drifts else None
        height = max(i["height"] for i in info)
        continuous = all(i["continuous"] for i in info)
        storeys: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for leg in group.legs:
            for p in piers_of.get(leg.id, []):
                storeys.setdefault(p.get("storey") or "", {}).setdefault(leg.id, []).append(p)
        for storey, found in storeys.items():
            name = f"{group.id}/{storey}"
            if len(found) < len(group.legs):
                continue  # the walls do not share this storey
            whole = all(
                len(ps) == 1 and abs(float(ps[0]["lw"]) - group.leg(w).length) <= 1.0
                for w, ps in found.items()
            )
            if not whole:
                notes.append(
                    f"walls: {name}: an opening splits a wall of the group: its rectangular "
                    "piers are checked, not the flanged section"
                )
                continue
            piers = {w: ps[0] for w, ps in found.items()}
            cut_names = {
                n for p in piers.values() for rows in p.get("cuts", {}).values() for n in rows or {}
            }
            seismic = {n for n in cut_names if _is_earthquake(n, earthquake)}
            forces = WF.group_forces(group, piers, seismic)
            if not forces:
                notes.append(f"walls: {name}: no combination common to its piers' cuts")
                continue
            try:
                d = WF.flanged_checks(
                    group,
                    forces,
                    fc,
                    fy,
                    es,
                    height=height,
                    special=special,
                    drift=drift,
                    continuous=continuous,
                )
            except DesignError as error:
                notes.append(f"walls: {name}: flanged section not checked: {error}")
                continue
            strength = [c for c in d.checks if not c["flag"]]
            entry = {
                "id": name,
                "walls": [leg.id for leg in group.legs],
                "storey": story_names.get(storey, storey),
                "junctions": [
                    {"walls": [j.a, j.b], "kind": j.kind, "at": [round(v, 1) for v in j.point]}
                    for j in group.junctions
                ],
                "sections": [WF.section_json(s) for s in d.sections],
                "checks": d.checks,
                "utilisation": d.utilisation,
                "ok": all(c["ok"] for c in strength),
                "boundary": d.boundary,
                "notes": list(dict.fromkeys(d.notes)),
            }
            pier_names = {p["pier"] for p in piers.values()}
            for leg in group.legs:
                element = by_id[leg.id]
                element.setdefault("flanged", []).append(entry)
                for c in d.checks:
                    note = f"{name} (flanged): {c['note']}" if c["note"] else f"{name} (flanged)"
                    element["checks"].append({**c, "note": note})
                for pier in element["piers"]:
                    if pier["id"] not in pier_names:
                        continue
                    for c in pier["checks"]:
                        if c["name"].startswith(superseded) and not c["flag"]:
                            c["flag"] = True
                            c["note"] = (c["note"] + "; " if c["note"] else "") + (
                                f"superseded by the flanged section {name}"
                            )
                    own = [c for c in pier["checks"] if not c["flag"]]
                    pier["utilisation"] = max((c["utilisation"] for c in own), default=0.0)
                    pier["ok"] = all(c["ok"] for c in own)
                    for c in element["checks"]:
                        lead = str(c.get("note") or "")
                        if (
                            c["name"].startswith(superseded)
                            and not c["flag"]
                            and (lead == pier["id"] or lead.startswith(f"{pier['id']}:"))
                        ):
                            c["flag"] = True
                            c["note"] = lead + f"; superseded by the flanged section {name}"
        for leg in group.legs:
            element = by_id[leg.id]
            own = [c for c in element["checks"] if not c["flag"]]
            element["utilisation"] = max((c["utilisation"] for c in own), default=0.0)
            element["ok"] = all(c["ok"] for c in own)
    if any(e.get("flanged") for e in elements):
        notes.append(
            "walls: walls meeting at an L, T or C are checked as flanged sections (BNBC 2020 "
            "Part 6 Sec 8.3.6.5); their piers' rectangular P-M and boundary rows are informative"
        )
    return notes


# ─────────────────────────────────────── design mode ───────────────────────────────────────

#: Bars assumed for walls without reinforcement in the design mode (for their checks only).
ASSUMED = {
    "cover": 25,
    "vertical": {"dia": 10, "spacing": 200},
    "horizontal": {"dia": 10, "spacing": 200},
    "layers": 2,
}


def _face(rho: float, t: float, layers: int) -> float:
    """mm²/m of one layer (face) for the ratio ``rho`` of a wall ``t`` thick."""
    return rho * t * 1000 / layers


def _required_ratio(checks: list[dict[str, Any]], start: str) -> tuple[float, float] | None:
    """(required, provided) ratio of the check row whose name starts with ``start``."""
    row = next((c for c in checks if c["name"].startswith(start)), None)
    return None if row is None else (row["demand"] / 100, row["capacity"] / 100)


def shear_ratio(collected: dict[str, Any]) -> float:
    """ρt the in-plane shear needs (6.4.8.9.1, or Eq. 6.8.9 with φ 0.60 for special walls)."""
    g, forces = collected["geometry"], collected["forces"]
    fc, fy = collected["fc"], collected["fy"]
    if not collected["special"]:
        return W._rho_t_shear(g, forces, fc, fy, 1.0)
    vu = max((abs(f.V2) for f in forces), default=0.0)
    need = vu / W.wall_phi("shearSeismic") / g.gross_area - W.alpha_c(g.aspect) * math.sqrt(fc)
    return max(need, 0.0) / min(fy, W.FYT_SHEAR_MAX)


def search_need(collected: dict[str, Any], layers: int | None = None) -> W.WallNeed:
    """What the pier needs with the end bars searched (:func:`walls.wall_need`), with at least
    ``layers`` curtains."""
    t = collected["object"]
    cover = float(t.reinforcement.cover) if t.reinforcement else float(ASSUMED["cover"])
    bars = None
    if layers is not None:
        bars = W.WallBars(cover, 10.0, 200.0, 10.0, 200.0, layers)
    return W.wall_need(
        collected["geometry"],
        collected["forces"],
        collected["fc"],
        collected["fy"],
        collected["es"],
        special=collected["special"],
        drift=collected["drift"],
        bars=bars,
        cover=cover,
        search=True,
    )


def required_rows(collected: dict[str, Any], assumed: bool, row: Any) -> list[dict[str, Any]]:
    """The design mode's rows of a pier (``row``: :func:`saengine.design.required._row`): the web
    bars per face each way, the end bars and the boundary element's length."""
    t = collected["object"]
    bars = W.wall_bars(t.reinforcement)
    g = collected["geometry"]
    layers = bars.layers if bars else 2
    checks = collected["checks"]
    pid, type_id = collected["id"], collected["type"]
    rows = []
    vertical = _required_ratio(checks, "Vertical web ratio")
    horizontal = _required_ratio(checks, "Horizontal web ratio")
    shear = shear_ratio(collected)
    shear_row = next((c for c in checks if c["name"].startswith("In-plane shear")), None)
    if vertical:
        face = _face(vertical[0], g.thickness, layers)
        rows.append(
            row(
                pid,
                "wall",
                type_id,
                "web, vertical",
                "vertical bars per face",
                None,
                "",
                face,
                face,
                None
                if assumed or bars is None
                else _face(bars.rho_l(g.thickness), g.thickness, layers),
                "mm²/m",
                None,
                [f"ρl ≥ {100 * vertical[0]:.3f} %", f"{layers} layer(s)"],
            )
        )
    if horizontal:
        rho = max(horizontal[0], shear)
        rows.append(
            row(
                pid,
                "wall",
                type_id,
                "web, horizontal",
                "horizontal bars per face",
                shear_row["demand"] if shear_row else None,
                "kN",
                _face(rho, g.thickness, layers),
                _face(horizontal[0], g.thickness, layers),
                None
                if assumed or bars is None
                else _face(bars.rho_t(g.thickness), g.thickness, layers),
                "mm²/m",
                shear_row["combination"] if shear_row else None,
                [
                    (
                        f"ρt ≥ {100 * rho:.3f} % (minimum {100 * horizontal[0]:.3f} %, in-plane "
                        f"shear {100 * shear:.3f} %)"
                    )
                ],
            )
        )
    need = search_need(collected, layers)
    pm = next((c for c in checks if c["name"].startswith("Axial force and bending")), None)
    end = need.end_bars
    provided_end = bars.boundary if bars else None
    too_small = any("enlarge the wall" in n or "too thin" in n for n in need.notes)
    if bars is not None and not assumed:
        # The end bars the entered web needs (the need's own web is the least mesh).
        found, end = W._search_end_bars(
            g,
            collected["forces"],
            collected["fc"],
            collected["fy"],
            collected["es"],
            collected["fy"],
            replace(bars, boundary=None),
            need.boundary,
            collected["special"],
        )
        too_small = not found
    if end is not None or provided_end is not None or (pm and not pm["ok"]):
        rows.append(
            row(
                pid,
                "wall",
                type_id,
                "ends",
                "end bars per end",
                pm["demand"] if pm else None,
                "kN·m",
                end.count * W.bar_area(end.dia) if end else 0.0,
                None,
                None
                if assumed
                else (provided_end.count * W.bar_area(provided_end.dia) if provided_end else 0.0),
                "mm²",
                pm["combination"] if pm else None,
                [
                    f"{end.count} Ø{end.dia:g} per end over {end.length:.0f} mm"
                    if end
                    else "the web bars carry the axial force and bending",
                    *need.notes,
                ],
                too_small,
            )
        )
    b = need.boundary
    if collected["special"] and b is not None and b.required:
        rows.append(
            row(
                pid,
                "wall",
                type_id,
                "boundary element",
                "length from each end",
                b.c,
                "mm",
                b.length,
                b.least_length,
                None if assumed else (provided_end.length if provided_end else 0.0),
                "mm",
                None,
                [
                    f"c = {b.c:.0f} mm",
                    f"hoops at ≤ {b.spacing:.0f} mm" if b.spacing else "",
                    f"over {b.height:.0f} mm above the critical section" if b.height else "",
                ],
            )
        )
    return rows


def _boundary_json(b: W.Boundary) -> dict[str, Any]:
    return {
        "length": b.length,
        "count": b.count,
        "dia": b.dia,
        "hoop": {
            "dia": b.hoop_dia,
            "spacing": b.hoop_spacing,
            "legsAcross": b.legs_across,
            "legsAlong": b.legs_along,
        },
    }


def wall_label(reinforcement: dict[str, Any]) -> str:
    """'Ø10 @ 200 V, Ø10 @ 200 H, 2 layer(s); ends 4 Ø16 over 400 (Ø10 @ 100)'."""
    parts = []
    for key, short in (("vertical", "V"), ("horizontal", "H")):
        m = reinforcement.get(key)
        if m:
            parts.append(f"Ø{m['dia']:g} @ {m['spacing']:g} {short}")
    text = ", ".join(parts) + f", {reinforcement.get('layers', 2)} layer(s)"
    b = reinforcement.get("boundary")
    if b:
        hoop = b.get("hoop") or {}
        text += f"; ends {b['count']} Ø{b['dia']:g} over {b['length']:g}"
        if hoop:
            text += f" (Ø{hoop.get('dia', 10):g} @ {hoop.get('spacing', 100):g})"
    return text


def _recheck(
    group: list[dict[str, Any]], reinforcement: dict[str, Any]
) -> tuple[dict[str, float], list[str]]:
    """Every pier of ``group`` checked with ``reinforcement``: (utilisation by pier, problems:
    the piers that fail or whose section the bars cannot be laid out in)."""
    bars = W.wall_bars(reinforcement)
    assert bars is not None
    utilisation: dict[str, float] = {}
    problems: list[str] = []
    for c in group:
        try:
            d = W.wall_checks(
                c["geometry"],
                bars,
                c["forces"],
                c["fc"],
                c["fy"],
                c["es"],
                special=c["special"],
                drift=c["drift"],
            )
        except DesignError as error:
            problems.append(f"{c['id']}: not checked with these bars: {error}")
            continue
        utilisation[c["id"]] = round(d.utilisation, 3)
        failing = [x["name"] for x in d.checks if not x["ok"] and not x["flag"]]
        if failing:
            problems.append(f"{c['id']} still fails: {', '.join(failing)}")
    return utilisation, problems


def _heavier_meshes(least: dict[str, Any], s_max: float) -> list[dict[str, float]]:
    """Meshes (Ø10-Ø20, 25 mm steps of spacing, >= 100 mm, <= ``s_max``) heavier than ``least``,
    lightest first."""
    area = W.bar_area(float(least["dia"])) / float(least["spacing"])
    out = []
    for dia in W.bar_sizes("wall"):
        spacing = math.floor(s_max / 25.0) * 25.0
        while spacing >= W.MIN_WALL_SPACING:
            if W.bar_area(dia) / spacing > area * (1 + 1e-9):
                out.append({"dia": dia, "spacing": spacing})
            spacing -= 25.0
    return sorted(out, key=lambda m: (W.bar_area(m["dia"]) / m["spacing"], m["dia"]))


def proposal_entries(
    collected: list[dict[str, Any]], assumed: set[str], originals: dict[str, Any]
) -> list[dict[str, Any]]:
    """Design-mode entries (the shape of ``saengine.design.proposal._entry``) per wall type from
    ``collect["walls"]``: the web meshes every pier needs (one mesh each way for the type), the
    end bars (boundary elements of special walls, or end bars with ties), checked again on
    every pier with the bars proposed. ``originals``: 04 Objects' types by id (JSON)."""
    from saengine.design.bars import mesh_for
    from saengine.design.proposal import _same
    from saengine.design.proposal import bars_of as reported

    groups: dict[str, list[dict[str, Any]]] = {}
    for c in collected:
        groups.setdefault(c["type"], []).append(c)
    entries = []
    for type_id, group in groups.items():
        t = group[0]["object"]
        own = (originals.get(type_id) or {}).get("reinforcement")
        current = None if type_id in assumed else own
        material = t.reinforcement.material
        cover = float(t.reinforcement.cover)
        layers = max(search_need(c).layers for c in group)
        # Never fewer curtains than the type has (X12 of the usability walk: a special wall cut
        # to one curtain): the engineer's second curtain may answer rules outside these checks
        # (detailing, crack control, the other walls of the type); one is only added.
        held = (current or {}).get("layers") if isinstance(current, dict) else None
        if isinstance(held, int | float) and held > layers:
            layers = int(held)
        needs = [search_need(c, layers) for c in group]
        notes = list(dict.fromkeys(n for need in needs for n in need.notes))
        thickness = group[0]["geometry"].thickness
        too_small = ""
        picks: dict[str, Any] = {}
        sizes = W.bar_sizes("wall")
        for key, rho, s_max in (
            ("vertical", "rho_l", "vertical_s_max"),
            ("horizontal", "rho_t", "horizontal_s_max"),
        ):
            if any(getattr(n, key) is None for n in needs):
                too_small = f"no {key} mesh of Ø10-Ø20 at ≥ 100 mm apart: the wall is too thin"
                break
            area = max(_face(getattr(n, rho), thickness, layers) for n in needs)
            spacing = min(getattr(n, s_max) for n in needs)
            mesh = mesh_for(area, spacing, sizes, W.MIN_WALL_SPACING)
            if mesh is None:
                too_small = f"no {key} mesh carries {area:.0f} mm²/m at ≤ {spacing:.0f} mm"
                break
            picks[key] = {"dia": mesh.dia, "spacing": mesh.spacing}
        if any("enlarge the wall" in n for n in notes):
            too_small = too_small or "no end bars carry the axial force and bending"
        reinforcement: dict[str, Any] | None = None
        utilisation: dict[str, float] = {}
        if not too_small:
            reinforcement = {"material": material, "cover": cover, **picks, "layers": layers}
            ends = [n.end_bars for n in needs if n.end_bars is not None]
            if ends:
                big = max(ends, key=lambda b: (b.count * W.bar_area(b.dia), b.dia))
                merged = W.Boundary(
                    max(b.length for b in ends),
                    big.count,
                    big.dia,
                    max(b.hoop_dia for b in ends),
                    min(b.hoop_spacing for b in ends),
                    max(b.legs_across for b in ends),
                    max(b.legs_along for b in ends),
                )
                reinforcement["boundary"] = _boundary_json(merged)
            if current and current.get("diagonal"):
                reinforcement["diagonal"] = current["diagonal"]
            utilisation, problems = _recheck(group, reinforcement)
            if problems and "boundary" in reinforcement:
                # End bars that do not fit in a pier (a short pier between openings): try a
                # heavier vertical web with no end bars, which every pier can take.
                spacing = min(n.vertical_s_max for n in needs)
                for mesh in _heavier_meshes(picks["vertical"], spacing):
                    trial = {**reinforcement, "vertical": mesh}
                    del trial["boundary"]
                    found, left = _recheck(group, trial)
                    if not left:
                        notes += [
                            p.replace(": not checked with these bars: ", ": with end bars, ")
                            for p in problems
                        ] + [
                            (
                                "the end bars do not fit in every pier: a heavier vertical web "
                                "carries the axial force and bending instead, checked on every pier"
                            )
                        ]
                        reinforcement, utilisation, problems = trial, found, []
                        break
            if problems:
                # Bars the type's piers cannot all take are not proposed (applying them would
                # leave a pier failing or unchecked).
                notes += problems
                too_small = "; ".join(problems)
                reinforcement, utilisation = None, {}
        status = "tooSmall" if reinforcement is None else "ok"
        if status == "ok" and current is not None and _same(current, reinforcement):
            status = "unchanged"
        governing = max(utilisation, key=lambda k: utilisation[k], default=group[0]["id"])
        entries.append(
            {
                "type": type_id,
                "kind": "wall",
                "name": t.name,
                "current": None if current is None else reported(current, wall_label(current)),
                "proposed": None
                if reinforcement is None
                else reported(reinforcement, wall_label(reinforcement)),
                "status": status,
                "governingMember": governing,
                "members": list(dict.fromkeys(c["wall"] for c in group)),
                "demand": {
                    "piers": len(group),
                    "layers": layers,
                    "maxShear": round(
                        max((abs(f.V2) for c in group for f in c["forces"]), default=0.0) / 1e3, 1
                    ),
                    "units": {"maxShear": "kN"},
                },
                "utilisation": {"piers": max(utilisation.values(), default=0.0)},
                "overDesigned": [],
                "overDesignedDetails": [],
                "tooSmall": None
                if reinforcement is not None
                else {
                    "reason": too_small,
                    "suggestion": "a thicker or longer wall (or pier), or a separate wall type "
                    "for the piers that fail",
                },
                "notes": notes,
            }
        )
    return entries
