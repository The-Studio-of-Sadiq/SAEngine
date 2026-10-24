"""The load combinations with the overstrength factor Ω0 and the elements that need them.

BNBC 2020 Part 6 Chapter 2:

- Sec 2.5.5.6.1 (p. 625): columns, beams, trusses or slabs supporting discontinuous walls or
  frames (horizontal irregularity Type IV, out-of-plane offsets, p. 618; vertical irregularity
  Type IV, in-plane discontinuity) shall resist the load combinations with the overstrength
  factor of Sec 2.5.13.4. Sec 2.5.5.6.3 (collectors, Category C and D) and 2.5.5.6.4 (batter
  piles, p. 626) name the others.
- Sec 2.5.13.4 (p. 646): in load combination 5 of Sec 2.7.3 (1.2D + 1.0E + 1.0L) E = Em =
  Ω0 Eh + Ev, in combination 7 (0.9D + 1.0E) Em = Ω0 Eh - Ev, Ev = 0.5 a_h D (Sec 2.5.13.2,
  eq. 6.2.56, a_h = (2/3) Z S), the 100 % + 30 % directions of 2.5.13.1(b) also for Emh; Emh
  need not exceed what a plastic mechanism or nonlinear analysis gives. (BNBC's Ev is 0.5 a_h D,
  not ASCE 7's 0.2 SDS D.) Ω0 of the system from Table 6.2.19 (pp. 621-624): 3 for RC special
  moment frames.

The combinations themselves are :func:`saengine.design.seismic_rules.omega_combinations` (and
:func:`~saengine.design.seismic_rules.omega_rs_combinations` for the response spectrum), and the
discontinuous columns and walls :func:`saengine.design.seismic_rules.discontinuities`, which
lists the beams directly under them and the columns at those beams' ends. This module adds what
that leaves out, for the design to give the Ω0 combinations to:

- girders carrying a transfer beam (a beam whose end lands on another beam instead of a column
  or wall), level by level down the chain, and the columns at their ends;
- structural walls under the ends of a transfer beam or girder;
- transfer slabs: a discontinuous column or wall with no beam under it stands on the slab
  whose outline holds it (the slab, 2.5.5.6.1 names slabs);
and the per-project factors (:func:`em_factors`) for the report.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Point, Polygon

from saengine.design import seismic_rules as sr

__all__ = [
    "CLAUSES",
    "em_factors",
    "omega_combinations",
    "overstrength_scope",
    "supporting_elements",
]

CLAUSES = {
    "supporting": "BNBC 2020 Part 6 Sec 2.5.5.6.1 (p. 625)",
    "em": "BNBC 2020 Part 6 Sec 2.5.13.4 (p. 646)",
    "ev": "BNBC 2020 Part 6 Sec 2.5.13.2 (eq. 6.2.56, pp. 645-646)",
    "omega": "BNBC 2020 Part 6 Table 6.2.19 (pp. 621-624)",
    "collectors": sr.CLAUSES.get("collectors", "BNBC 2020 Part 6 Sec 2.5.5.6.3"),
}


def em_factors(settings: Any, omega: float | None = None) -> dict[str, Any]:
    """The factors of Em for the project: ``{"omega", "ah", "ev", "upper": {"D", "E"},
    "lower": {"D", "E"}, "clause"}``: in 1.2D + 1.0E + L the dead load factor becomes
    1.2 + 0.5 a_h and E is multiplied by Ω0; in 0.9D + 1.0E, 0.9 - 0.5 a_h and Ω0."""
    from saengine.fem.seismic_design import peak_ground_acceleration
    from saengine.library.settings import derived

    value = float(omega if omega is not None else derived(settings)["omega"])
    ah = float(peak_ground_acceleration(settings))
    ev = 0.5 * ah
    return {
        "omega": value,
        "ah": ah,
        "ev": ev,
        "upper": {"D": round(1.2 + ev, 4), "E": value},
        "lower": {"D": round(0.9 - ev, 4), "E": value},
        "clause": f"{CLAUSES['em']}: Em = Ω0 Eh ± Ev, Ω0 = {value:g} ({CLAUSES['omega']}), "
        f"Ev = 0.5 a_h D = {ev:.4f} D ({CLAUSES['ev']})",
    }


def omega_combinations(settings: Any, omega: float | None = None) -> list[dict[str, Any]]:
    """The project's earthquake combinations with Em (:func:`saengine.design.seismic_rules.
    omega_combinations`): named ``"Ω0: <name>"``."""
    return sr.omega_combinations(settings, omega)


def _tops_at(elements: list[Any], z: float) -> list[Any]:
    return [e for e in elements if abs(float(e.top) - z) <= sr.TOLERANCE]


def supporting_elements(
    building: Any, objects: Any = None, materials: Any = None
) -> list[dict[str, Any]]:
    """The elements supporting discontinuous columns and walls (Sec 2.5.5.6.1): ``[{"id",
    "kind", "reason", "discontinuous": the column or wall id, "found": "direct" | "girder" |
    "wall" | "slab"}]``, each element once (its first reason). "direct" are those of
    :func:`saengine.design.seismic_rules.discontinuities` (the beams under the element and the
    columns at their ends); the others are what this module adds (see the module notes). An
    automatic finding for the engineer to confirm."""
    if building is None:
        return []
    found = sr.discontinuities(building, objects, materials)
    if not found:
        return []
    types = {o.id: o for o in getattr(objects, "objects", [])} if objects is not None else {}
    by_material = {m.id: m for m in getattr(materials, "materials", [])} if materials else {}
    elements = list(getattr(building, "elements", []))
    columns = [e for e in elements if getattr(e, "kind", "") == "column"]
    walls = [
        e
        for e in elements
        if getattr(e, "kind", "") == "wall" and sr._structural_wall(e, types, by_material)
    ]
    beams = [e for e in elements if getattr(e, "kind", "") == "beam"]
    slabs = [e for e in elements if getattr(e, "kind", "") == "slab"]
    result: dict[str, dict[str, Any]] = {}

    def add(element: Any, kind: str, reason: str, source: str, how: str) -> bool:
        if element.id in result:
            return False
        result[element.id] = {
            "id": element.id,
            "kind": kind,
            "reason": reason,
            "discontinuous": source,
            "found": how,
        }
        return True

    by_id = {e.id: e for e in elements}
    for item in found:
        source, z = item["id"], float(item["elevation"])
        what = f"discontinuous {item['kind']} {source}"
        for bid in item["supportedBy"]:
            add(by_id[bid], "beam", f"carries {what}", source, "direct")
        for cid in item["supportColumns"]:
            add(by_id[cid], "column", f"supports the beam(s) under {what}", source, "direct")
        if not item["supportedBy"]:
            standing = by_id.get(source)
            if standing is not None:
                if item["kind"] == "column":
                    shape: Any = Point(*map(float, standing.position[:2]))
                else:
                    shape = LineString([standing.start[:2], standing.end[:2]]).interpolate(
                        0.5, normalized=True
                    )
                for slab in slabs:
                    if abs(float(slab.elevation) - z) > sr.TOLERANCE:
                        continue
                    outline = Polygon([p[:2] for p in slab.boundary])
                    if outline.buffer(sr.TOLERANCE).contains(shape):
                        add(
                            slab,
                            "slab",
                            f"carries {what} without a beam under it (a transfer slab)",
                            source,
                            "slab",
                        )
        # Down the chain: a carrying beam's end that lands on no column or wall rests on a
        # girder; walls under the ends support the transfer beam as a column would.
        queue = [by_id[bid] for bid in item["supportedBy"]]
        seen = {b.id for b in queue}
        while queue:
            beam = queue.pop(0)
            level = float(beam.elevation)
            for end in (beam.start, beam.end):
                on_column = any(
                    sr._near(c.position, end, sr.TOLERANCE) for c in _tops_at(columns, level)
                )
                under = [w for w in _tops_at(walls, level) if sr._on_segment(end, w.start, w.end)]
                for wall in under:
                    add(wall, "wall", f"supports beam {beam.id} under {what}", source, "wall")
                if on_column or under:
                    continue
                for girder in beams:
                    if (
                        girder.id in seen
                        or abs(float(girder.elevation) - level) > sr.TOLERANCE
                        or not sr._on_segment(end, girder.start, girder.end)
                    ):
                        continue
                    seen.add(girder.id)
                    add(
                        girder,
                        "beam",
                        f"carries beam {beam.id} under {what} (a girder)",
                        source,
                        "girder",
                    )
                    for column in _tops_at(columns, level):
                        if sr._near(column.position, girder.start) or sr._near(
                            column.position, girder.end
                        ):
                            add(
                                column,
                                "column",
                                f"supports girder {girder.id} under {what}",
                                source,
                                "girder",
                            )
                    queue.append(girder)
    return list(result.values())


def overstrength_scope(
    settings: Any, building: Any, objects: Any = None, materials: Any = None
) -> dict[str, Any]:
    """What the design needs for Sec 2.5.5.6.1 and 2.5.13.4: ``{"factors": em_factors,
    "elements": supporting_elements, "ids": their ids, "added": the ids
    :func:`saengine.design.seismic_rules.seismic_detailing_scope` does not have (girders,
    walls, slabs), "combinations": the Ω0 combinations (empty without elements), "notes"}``.
    Collectors (2.5.5.6.3) are not found (no diaphragm model): the engineer marks them with
    ``omegaCombinations: "collector"`` as before."""
    elements = supporting_elements(building, objects, materials)
    factors = em_factors(settings)
    notes = []
    if elements:
        notes.append(
            f"{CLAUSES['supporting']}: {len(elements)} element(s) support discontinuous columns "
            "or walls and take the Ω0 combinations (an automatic finding to confirm)"
        )
    if any(e["kind"] == "slab" for e in elements):
        notes.append(
            "a transfer slab takes the Ω0 combinations in its own design (flexure and the "
            "punching at the planted column)"
        )
    return {
        "factors": factors,
        "elements": elements,
        "ids": sorted(e["id"] for e in elements),
        "added": sorted(e["id"] for e in elements if e["found"] != "direct"),
        "combinations": omega_combinations(settings, factors["omega"]) if elements else [],
        "notes": notes,
    }
