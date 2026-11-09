"""Cost-driven design: the cheapest section, steel grade and concrete strength per member group
that still passes the design checks (alpha 9 L11).

Design Reinforcement already proposes the lightest passing bars of an RC type
(:mod:`saengine.design.proposal`) and the lightest passing table section of a steel type
(:mod:`saengine.design.steel_proposal`). This module searches over the options of each group
(an object type of 04 Objects and its members) and prices them with the project's schedule of
rates (alpha 9 T6, :mod:`saengine.boq.costing`):

- steel beams, columns and braces: every section family the type's shape allows times every
  steel material of 03 Materials chosen; per family and grade the lightest section passing every
  station of every member is found with the steel proposal's own checks (:func:`_trial`), and
  priced by mass x length x the rate of that steel;
- RC beams (rectangular): the section's depth and width steps times the concrete materials
  chosen; per option the bars are the lightest passing ones of Design Reinforcement's
  :class:`~saengine.design.proposal.BeamDesigner` (``lightest=True``), and the option is priced
  as concrete (b h L) + formwork ((b + 2h) L) + bars (longitudinal and stirrups along L).

The search is a branch and bound per group: options are tried cheapest lower bound first (the
concrete and formwork of an RC option, the lightest section of a steel family, need no design),
and stop once the next lower bound is not cheaper than the best passing option found.

Limits (said in every result): the member forces are those of the last analysis, so a section
change that alters stiffness or self-weight must be confirmed by running the analysis and the
checks again; deflection and the checks Design Reinforcement does not size for (the joints of
special moment frames, the strong column rule) are confirmed by that run, not here. Costs are
comparative: an RC beam's concrete is its full depth, though the bill gives the slab its depth.
RC columns and slabs are not optimised yet (their interaction surfaces and meshes are searched
per type by Design Reinforcement; the options here would need them again per grade).
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

from saengine.boq.costing import RateSchedule, conversion, parse_rates, rate_for
from saengine.design.proposal import _in_project_pack

#: Depth steps of an RC beam tried by default [mm]: as it is and deeper (a smaller depth needs
#: the deflection checked again: given only on request).
DEFAULT_DEPTH_STEPS = (0.0, 50.0, 100.0, 150.0)
DEFAULT_WIDTH_STEPS = (0.0,)
STEEL_DENSITY = 7850.0  # kg/m³ (bars)

LIMITS = [
    (
        "The member forces are those of the last analysis: a change of section or grade alters "
        "stiffness and self-weight, so run the analysis and the design checks again after applying."
    ),
    "Deflection, joint shear and the strong column rule are confirmed by that run, not here.",
    (
        "Costs are comparative (an RC beam's concrete over its full depth); the bill of quantities "
        "remains the cost of record."
    ),
]


# ─────────────────────────────────── pricing ───────────────────────────────────


class Pricer:
    """Unit prices of the schedule of rates for a pseudo bill item (group, kind, material, unit,
    diameter), cached; None when no rate prices it."""

    def __init__(self, schedule: RateSchedule) -> None:
        self.schedule = schedule
        self.missing: set[str] = set()
        self._cache: dict[tuple[Any, ...], float | None] = {}

    def price(
        self,
        group: str,
        kind: str,
        unit: str,
        material: str | None = None,
        diameter: float | None = None,
        description: str = "",
    ) -> float | None:
        key = (group, kind, unit, material, diameter, description)
        if key in self._cache:
            return self._cache[key]
        item = {
            "group": group,
            "kind": kind,
            "unit": unit,
            "material": material,
            "diameter": diameter,
            "description": description,
        }
        rate = rate_for(self.schedule, item)
        found = None
        if rate is not None and rate.rate is not None:
            factor = conversion(rate.unit, unit)
            if factor is not None:
                found = rate.rate * factor
        if found is None:
            self.missing.add(f"{group} {kind}{f' {material}' if material else ''} ({unit})")
        self._cache[key] = found
        return found


def _cost(parts: list[tuple[float, float | None]]) -> tuple[float, bool]:
    """Σ quantity x unit price, and whether every part was priced."""
    total, complete = 0.0, True
    for quantity, price in parts:
        if price is None:
            complete = complete and quantity <= 0
            continue
        total += quantity * price
    return total, complete


# ─────────────────────────────────── geometry ───────────────────────────────────


def _length(element: Any) -> float:
    """Length of a building element [mm] (members along their axis, columns their height)."""
    kind = getattr(element, "kind", None)
    if kind == "column":
        return abs(float(element.top) - float(element.bottom))
    start, end = getattr(element, "start", None), getattr(element, "end", None)
    if start is not None and end is not None:
        return math.dist([float(v) for v in start], [float(v) for v in end])
    return 0.0


def _lengths(building: Any) -> dict[str, float]:
    return {e.id: _length(e) for e in building.elements}


def bar_kg(reinforcement: dict[str, Any] | None, length: float, b: float, h: float) -> float:
    """Mass [kg] of a beam's bars over ``length`` [mm]: the longitudinal groups along it, and the
    stirrups (their perimeter inside the cover, plus a cross-tie per leg beyond two) at their
    spacing."""
    if not reinforcement:
        return 0.0
    kg = 0.0
    for group in reinforcement.get("longitudinal") or []:
        d = float(group.get("dia") or 0.0)
        kg += int(group.get("count") or 0) * math.pi * d * d / 4 * length * STEEL_DENSITY * 1e-9
    t = reinforcement.get("transverse") or {}
    d, s = float(t.get("dia") or 0.0), float(t.get("spacing") or 0.0)
    if d > 0 and s > 0:
        cover = float(reinforcement.get("cover") or 25.0)
        bi, hi = max(b - 2 * cover - d, 0.0), max(h - 2 * cover - d, 0.0)
        legs = int(t.get("legs") or 2)
        one = 2 * (bi + hi) + 20 * d + max(legs - 2, 0) * hi
        kg += (length / s + 1) * one * math.pi * d * d / 4 * STEEL_DENSITY * 1e-9
    return kg


# ─────────────────────────────────── RC beams ───────────────────────────────────


def _rc_beam_group(
    type_id: str,
    members: list[dict[str, Any]],
    lengths: dict[str, float],
    concretes: list[Any],
    pricer: Pricer,
    opts: Any,
    combinations: list[str],
    depth_steps: list[float],
    width_steps: list[float],
) -> dict[str, Any]:
    from saengine.design.proposal import BeamDesigner, _beam_loads
    from saengine.design.rc import DesignError
    from saengine.library.objects import RectangleProfile

    first = members[0]
    obj = first["object"]
    notes: list[str] = []
    if not isinstance(obj.profile, RectangleProfile) or obj.reinforcement is None:
        return {"type": type_id, "kind": "beam", "skipped": "only rectangular RC beams"}
    b0, h0 = float(obj.profile.xDim), float(obj.profile.yDim)
    total = sum(lengths.get(m["id"], 0.0) for m in members)
    if total <= 0:
        return {"type": type_id, "kind": "beam", "skipped": "no member lengths"}
    envelope = None
    for m in members:
        loads = _beam_loads(m, combinations)
        envelope = loads if envelope is None else envelope.envelope(loads)
    bar_material = obj.reinforcement.material
    top_drop = max(float(m.get("topDrop") or 0.0) for m in members)

    options: list[dict[str, Any]] = []
    for concrete in concretes:
        for dh in depth_steps:
            for db in width_steps:
                b, h = b0 + db, h0 + dh
                if b < 150 or h < 200 or h < b * 0.5:
                    continue
                volume = b * h * total * 1e-9  # m³
                form = (b + 2 * h) * total * 1e-6  # m²
                lower, complete = _cost(
                    [
                        (volume, pricer.price("concrete", "beam", "m3", concrete.id)),
                        (form, pricer.price("formwork", "beam", "m2")),
                    ]
                )
                options.append(
                    {
                        "label": f"{b:g} x {h:g} mm, {concrete.name or concrete.id}",
                        "b": b,
                        "h": h,
                        "material": concrete.id,
                        "fc": float(concrete.concrete.fc),
                        "aggregate": concrete.concrete.maxAggregate,
                        "lower": lower,
                        "priced": complete,
                        "quantities": {"concrete": round(volume, 3), "formwork": round(form, 2)},
                    }
                )
    options.sort(key=lambda o: o["lower"])
    best: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    evaluated = pruned = 0
    for option in options:
        is_current = option["b"] == b0 and option["h"] == h0 and option["material"] == obj.material
        if best is not None and option["lower"] >= best["cost"] and not is_current:
            pruned += 1
            continue
        evaluated += 1
        profile = obj.profile.model_copy(update={"xDim": option["b"], "yDim": option["h"]})
        candidate = obj.model_copy(update={"profile": profile, "material": option["material"]})
        try:
            designer = BeamDesigner(
                candidate, option["fc"], first["fy"], first["es"], option["aggregate"], opts,
                top_drop,
            )  # fmt: skip
            pick = designer.propose(envelope, lightest=True)
        except DesignError as error:
            option["passes"], option["reason"] = False, str(error)
            continue
        option["passes"] = pick.reinforcement is not None
        if not option["passes"]:
            option["reason"] = pick.too_small
            if is_current:
                current = option
            continue
        kg = bar_kg(pick.reinforcement, total, option["b"], option["h"])
        bars, bars_priced = _cost([(kg, pricer.price("reinforcement", "beam", "kg", bar_material))])
        option["quantities"]["reinforcement"] = round(kg, 1)
        option["reinforcement"] = pick.reinforcement
        option["bars"] = pick.label
        option["cost"] = round(option["lower"] + bars, 2)
        option["priced"] = option["priced"] and bars_priced
        if is_current:
            current = option
        if best is None or option["cost"] < best["cost"]:
            best = option
    if current is None or not current.get("passes"):
        notes.append(
            "the current section does not pass with any bars: the cheapest passing option is "
            "the comparison"
        )
    return _group_result(
        type_id, "beam", obj.name, members, total, current, best, evaluated, pruned, notes
    )


# ─────────────────────────────────── steel ───────────────────────────────────


def _steel_group(
    type_id: str,
    entries: list[dict[str, Any]],
    lengths: dict[str, float],
    original: dict[str, Any],
    steels: list[Any],
    pricer: Pricer,
    limit: float,
) -> dict[str, Any]:
    from saengine.design.steel_proposal import (
        SteelMaterial,
        SteelMemberDemand,
        _trial,
        default_checker,
        slender_elements,
    )
    from saengine.library import steel_sections as tbl

    kind = entries[0]["kind"]
    profile = original.get("profile") or {}
    families = list(tbl.families_for(profile))
    if not families:
        return {"type": type_id, "kind": kind, "skipped": "no section table for the profile"}
    if any("mats" in e for e in entries):
        return {"type": type_id, "kind": kind, "skipped": "composite types are not optimised yet"}
    members = [
        SteelMemberDemand(e["id"], e["lengths"], e["stations"], e["kind"], e.get("options"))
        for e in entries
    ]
    total = sum(lengths.get(e["id"], 0.0) for e in entries)
    if total <= 0:
        total = sum(float(getattr(e["lengths"], "L", 0.0) or 0.0) for e in entries)
    checker, real = default_checker()
    notes: list[str] = []
    if not real:
        notes.append("checked with the stand-in member checks (saengine.design.steel missing)")
    current_section = tbl.match(profile)
    current_material = original.get("material")
    nonslender = kind in ("brace", "column")
    options: list[dict[str, Any]] = []
    for grade in steels:
        material = SteelMaterial.from_material(grade)
        price = pricer.price("steel", kind, "kg", grade.id)
        for fam in families:
            sections = [tbl.oriented(s, profile) for s in tbl.family(fam)]
            if not sections:
                continue
            options.append(
                {
                    "family": fam,
                    "material": grade.id,
                    "steel": material,
                    "price": price,
                    "sections": sections,
                    "lower": sections[0].mass * total * 1e-3 * (price or 0.0),
                }
            )
    options.sort(key=lambda o: o["lower"])
    best: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    evaluated = pruned = 0
    for option in options:
        if best is not None and option["lower"] >= best["cost"]:
            pruned += 1
            continue
        evaluated += 1
        found = None
        for s in option["sections"]:
            if (
                best is not None
                and s.mass * total * 1e-3 * (option["price"] or 0.0) >= best["cost"]
            ):
                break  # heavier sections of this family cost more than the best found
            if nonslender and slender_elements(s, option["steel"]):
                continue
            if _trial(s, members, option["steel"], checker, limit).utilisation <= limit:
                found = s
                break
        if found is None:
            continue
        kg = found.mass * total * 1e-3
        cost, priced = _cost([(kg, option["price"])])
        result = {
            "label": f"{found.name} ({found.mass:.1f} kg/m), {option['material']}",
            "section": found.name,
            "profile": found.profile(),
            "material": option["material"],
            "quantities": {"steel": round(kg, 1)},
            "cost": round(cost, 2),
            "priced": priced,
            "passes": True,
        }
        if best is None or result["cost"] < best["cost"]:
            best = result
    if current_section is not None and current_material:
        grade = next((g for g in steels if g.id == current_material), None)
        if grade is not None:
            material = SteelMaterial.from_material(grade)
            trial = _trial(
                tbl.oriented(current_section, profile), members, material, checker, limit, False
            )
            kg = current_section.mass * total * 1e-3
            cost, priced = _cost([(kg, pricer.price("steel", kind, "kg", grade.id))])
            current = {
                "label": f"{current_section.name} ({current_section.mass:.1f} kg/m), {grade.id}",
                "section": current_section.name,
                "material": grade.id,
                "quantities": {"steel": round(kg, 1)},
                "cost": round(cost, 2),
                "priced": priced,
                "passes": trial.utilisation <= limit,
                "utilisation": round(trial.utilisation, 3),
            }
    elif current_section is None:
        notes.append("the current profile is not a table section: no current cost")
    return _group_result(
        type_id, kind, original.get("name", type_id), entries, total, current, best, evaluated,
        pruned, notes,
    )  # fmt: skip


# ─────────────────────────────────── results ───────────────────────────────────


def _public(option: dict[str, Any] | None) -> dict[str, Any] | None:
    if option is None:
        return None
    hidden = {"lower", "fc", "aggregate", "steel", "sections", "price"}
    return {k: v for k, v in option.items() if k not in hidden}


def _group_result(
    type_id: str,
    kind: str,
    name: str,
    members: list[dict[str, Any]],
    total: float,
    current: dict[str, Any] | None,
    best: dict[str, Any] | None,
    evaluated: int,
    pruned: int,
    notes: list[str],
) -> dict[str, Any]:
    delta = None
    if best is not None and current is not None and current.get("passes"):
        delta = round(best["cost"] - current["cost"], 2)
    status = "noPassingOption" if best is None else ("unchanged" if delta == 0 else "cheaper")
    if best is not None and current is not None and best.get("label") == current.get("label"):
        status = "unchanged"
    if best is not None and not best.get("priced", True):
        notes.append("some quantities have no rate in the schedule: the costs leave them out")
    return {
        "type": type_id,
        "kind": kind,
        "name": name,
        "members": [m["id"] for m in members],
        "length": round(total / 1000, 2),
        "current": _public(current),
        "best": _public(best),
        "delta": delta,
        "status": status,
        "evaluated": evaluated,
        "pruned": pruned,
        "notes": notes,
    }


@_in_project_pack  # the project's code pack, as Design Reinforcement
def optimise(
    out_dir: str,
    project_path: str,
    rates_text: str | None = None,
    options: dict[str, Any] | None = None,
    gathered: Any = None,
) -> dict[str, Any]:
    """The cheapest passing option per member group of the run (see the module notes).

    ``options``: ``types`` (object type ids; all the beam, column and brace types designed by
    default), ``concretes`` / ``steels`` (material ids of 03 Materials to try; default every
    concrete or structural steel of the library), ``depthSteps`` / ``widthSteps`` (RC beams, mm
    added to the current section), ``limit`` (utilisation, 1.0). ``gathered``: the design
    checks to work from (by default those the design mode keeps for the run).

    Returns ``{"currency", "groups": [{type, kind, name, members, length (m), current, best,
    delta, status, evaluated, pruned, notes}], "total": {current, best, delta}, "notes",
    "limits"}``.
    """
    from saengine.design.required import Options

    options = options or {}
    if gathered is None:
        from saengine.pipeline.design_mode import gathered as kept_gathering

        gathered = kept_gathering(out_dir, project_path, substructure=False)
    schedule = parse_rates(rates_text)
    pricer = Pricer(schedule)
    wanted = set(options.get("types") or [])
    limit = float(options.get("limit") or 1.0)
    materials = list(gathered.materials.materials)
    from saengine.library.materials import Category

    concretes = [
        m
        for m in materials
        if m.category == Category.CONCRETE
        and m.concrete is not None
        and (not options.get("concretes") or m.id in options["concretes"])
    ]
    steels = [
        m
        for m in materials
        if m.category == Category.STEEL
        and m.steel is not None
        and (not options.get("steels") or m.id in options["steels"])
    ]
    depth_steps = [float(v) for v in options.get("depthSteps") or DEFAULT_DEPTH_STEPS]
    width_steps = [float(v) for v in options.get("widthSteps") or DEFAULT_WIDTH_STEPS]
    lengths = _lengths(gathered.building)
    combinations = gathered.collect.get("combinations", [])
    opts = Options.of(options.get("design"))
    originals = {o["id"]: o for o in json.loads(gathered.objects_text).get("objects", [])}
    groups: list[dict[str, Any]] = []
    notes: list[str] = []

    beams: dict[str, list[dict[str, Any]]] = {}
    for member in gathered.collect.get("members", []):
        if member["kind"] == "beam" and (not wanted or member["type"] in wanted):
            beams.setdefault(member["type"], []).append(member)
    for type_id, members in beams.items():
        groups.append(
            _rc_beam_group(
                type_id,
                members,
                lengths,
                concretes,
                pricer,
                opts,
                combinations,
                depth_steps,
                width_steps,
            )
        )
    steel: dict[str, list[dict[str, Any]]] = {}
    for member in gathered.collect.get("steel", []):
        if not wanted or member["type"] in wanted:
            steel.setdefault(member["type"], []).append(member)
    for type_id, entries in steel.items():
        if type_id not in originals:
            continue
        groups.append(
            _steel_group(type_id, entries, lengths, originals[type_id], steels, pricer, limit)
        )
    columns = {m["type"] for m in gathered.collect.get("members", []) if m["kind"] == "column"}
    if columns:
        notes.append(
            f"{len(columns)} RC column type(s) not optimised yet (Design Reinforcement sizes "
            "their bars; section and grade options are planned)"
        )
    current = sum(g["current"]["cost"] for g in groups if g.get("current") and g.get("best"))
    best = sum(g["best"]["cost"] for g in groups if g.get("current") and g.get("best"))
    if pricer.missing:
        notes.append(
            "no rate in the schedule of rates for: " + ", ".join(sorted(pricer.missing)[:6])
        )
    return {
        "currency": schedule.currency,
        "rateSchedule": schedule.name,
        "groups": groups,
        "total": {
            "current": round(current, 2),
            "best": round(best, 2),
            "delta": round(best - current, 2),
        },
        "notes": notes,
        "limits": LIMITS,
    }


def apply_optimisation(
    objects_text: str, result: dict[str, Any], accept: list[str] | None = None
) -> dict[str, Any]:
    """04 Objects with the best options of the groups in ``accept`` (all cheaper ones by
    default): the profile, the material and, for RC beams, the lightest passing bars. Pure:
    ``{"objectsText", "changes"}``. The analysis must be run again afterwards."""
    data = json.loads(objects_text)
    by_id = {o.get("id"): o for o in data.get("objects", [])}
    changes = []
    for group in result.get("groups", []):
        best = group.get("best")
        if not best or group.get("status") != "cheaper":
            continue
        if accept is not None and group["type"] not in accept:
            continue
        obj = by_id.get(group["type"])
        if obj is None:
            continue
        before = {k: copy.deepcopy(obj.get(k)) for k in ("profile", "material")}
        if "b" in best and "h" in best:
            obj["profile"] = {**obj.get("profile", {}), "xDim": best["b"], "yDim": best["h"]}
            if best.get("reinforcement"):
                obj["reinforcement"] = best["reinforcement"]
        elif best.get("profile"):
            obj["profile"] = best["profile"]
        if best.get("material"):
            obj["material"] = best["material"]
        changes.append({"type": group["type"], "before": before, "after": best.get("label")})
    return {
        "objectsText": json.dumps(data, indent="\t", ensure_ascii=False) + "\n",
        "changes": changes,
    }
