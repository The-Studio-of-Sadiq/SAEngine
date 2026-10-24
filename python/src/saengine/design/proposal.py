"""Design mode, part 2: the bars SAEngine PROPOSES, per object type, and the edit that applies
them.

Bars live on the object types of 04 Objects, shared by every member placed with the type, so a
proposal is made per type: the envelope of the demands of all its members (the checks' own,
gathered once by :func:`saengine.design.required.gather`) decides, and the member that needs
the most steel is the type's governing member. Each member's own bars are worked out too:
members whose own bars would be lighter than the type's by more than ``overDesign`` are listed
as over-designed, and the ``splitTypes`` mode groups them into new types (``B300x500-2``, ...)
with their members reassigned in 06 BIM (and in 05 Floor Plan, where they come from), each new
type designed for the envelope of its own members.

Detailing (see :mod:`saengine.design.bars` for the clauses):

- Beams: one diameter per face, at most ``maxSizes`` (2) sizes in the beam (stirrups apart),
  at least 2 bars per face, in at most 2 rows at the least clear spacing (rows when one does
  not fit); fewer bars and less steel preferred. Stirrups Ø8/10/12 with 2 legs (4 in beams at
  least 300 mm wide when that is lighter), spacing in 25 mm steps within the largest spacing.
  Every pick is confirmed with the checks' own functions (:func:`rc.flexure` with εt >= 0.004,
  ACI 9.3.3.1, and :func:`rc.shear`), stepping up when it falls short.
- Columns: equal bars of one diameter round the section, a count fitting its shape (symmetric;
  even counts, shared between the faces as :func:`rc.section_of` lays them out), the smallest
  steel that the interaction surface (coarse to search, the checks' full one to confirm)
  accepts for every station of every member; ties by ACI 25.7.2.
- Slabs: per layer the lightest mesh of Ø10/12/16 at 25 mm spacing steps (at least 100 mm,
  at most the largest spacing), for the largest Wood-Armer moment of all the type's strips, As,min
  and the ρ that one-way shear needs (the slab has no shear bars).
- Foundations (9 Substructure, bars stored on each foundation): per direction and face, from
  their flexure and strut-and-tie checks, As,min and spacing at most min(3h, 450 mm).

When no practical bars make a section work (εt, the shear limit of ACI 22.5.1.2, ρ above 0.08,
a slab too thin for one-way shear without shear bars), the type is reported ``tooSmall`` with
the next practical section as information (depth in 50 mm steps for beams, both sides in
50 mm steps for columns, thickness in 25 mm steps for slabs); nothing is changed for it.

:func:`apply_proposal` is pure: it takes the texts of the part files and returns new texts, so
the workbench applies the proposal as one undoable edit.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.design import bars as B
from saengine.design import slab as slab_design
from saengine.design.rc import (
    DesignError,
    bar_area,
    flexure,
    section_of,
    shear,
)
from saengine.design.required import (
    BeamGeometry,
    ColumnSearch,
    Gathered,
    Options,
    Point,
    beam_demand,
    beam_need,
    column_requirements,
    foundation_demands,
    foundation_layer_need,
    gather,
    slab_envelope,
    slab_layer_need,
    slab_layer_rules,
)
from saengine.library.objects import (
    Beam,
    CircleProfile,
    LinearReinforcement,
    RectangleProfile,
    Slab,
)

#: The largest increase tried when suggesting a bigger section [mm].
GROWTH = {"beam": 600.0, "column": 300.0, "slab": 150.0}


@dataclass
class Pick:
    """A proposal for one set of demands: the reinforcement (the objects' JSON shape), its
    label, the steel that ranks it [mm² or mm²/m], or why there is none."""

    reinforcement: dict[str, Any] | None
    label: str
    area: float
    utilisation: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    too_small: str = ""
    suggestion: str = ""


# ─────────────────────────────────────── beams ───────────────────────────────────────


@dataclass(frozen=True)
class BeamLoads:
    sag: float  # N·mm
    hog: float
    shear: float  # N

    def envelope(self, other: BeamLoads) -> BeamLoads:
        return BeamLoads(
            max(self.sag, other.sag), max(self.hog, other.hog), max(self.shear, other.shear)
        )


def _beam_label(reinforcement: dict[str, Any]) -> str:
    parts = []
    for group in reinforcement.get("longitudinal", []):
        parts.append(f"{group['position']} {group['count']}Ø{group['dia']:g}")
    t = reinforcement.get("transverse")
    if t:
        parts.append(f"{t['type']}s Ø{t['dia']:g} {t.get('legs', 2)} legs @ {t['spacing']:g}")
        if _zone_text(t):
            parts[-1] += f" ({_zone_text(t)})"
    return ", ".join(parts)


class BeamDesigner:
    """Proposes the bars of one beam type (its profile, cover and materials) for any demands,
    caching the checks of the arrangements it tries."""

    def __init__(
        self, obj: Beam, fc: float, fy: float, es: float, aggregate: float | None, options: Options
    ) -> None:
        if not isinstance(obj.profile, RectangleProfile):
            raise DesignError("beams are proposed for rectangular profiles only")
        self.obj = obj
        self.b, self.h = obj.profile.xDim, obj.profile.yDim
        reinforcement = obj.reinforcement
        assert reinforcement is not None
        self.cover = reinforcement.cover
        self.material = reinforcement.material
        self.sides = [
            g.model_dump(mode="json") for g in reinforcement.longitudinal if g.position == "sides"
        ]
        self.kind = reinforcement.transverse.type if reinforcement.transverse else "stirrup"
        self.fc, self.fy, self.es, self.aggregate = fc, fy, es, aggregate
        self.options = options
        self._cache: dict[str, tuple[Any, Any, Any, Any]] = {}

    def geometry(self, h: float, stirrup: float) -> BeamGeometry:
        d = h - self.cover - stirrup - 10.0  # one row of Ø20 assumed
        return BeamGeometry(self.b, h, d, d, self.fc, self.fy, self.es, self.fy)

    def _analyse(self, reinforcement: dict[str, Any]):
        key = json.dumps(reinforcement, sort_keys=True)
        if key not in self._cache:
            section = section_of(
                self.obj.profile,
                LinearReinforcement.model_validate(reinforcement),
                self.fc,
                self.fy,
                self.es,
                self.aggregate,
            )
            t = reinforcement["transverse"]
            self._cache[key] = (
                section,
                flexure(section, False),
                flexure(section, True),
                shear(section, t["dia"], t["legs"], t["spacing"]),
            )
        return self._cache[key]

    def verify(self, reinforcement: dict[str, Any], loads: BeamLoads) -> dict[str, float] | None:
        """The utilisations of the checks (as :func:`check._beam_checks` makes them) when every
        one passes, else None."""
        _, sag, hog, resistance = self._analyse(reinforcement)
        result = {}
        for name, capacity, demand in (("sagging", sag, loads.sag), ("hogging", hog, loads.hog)):
            if demand <= 0:
                result[name] = 0.0
                continue
            if capacity.phi_mn <= 0 or round(demand / capacity.phi_mn, 3) > 1.0:
                return None
            if capacity.eps_t < 0.004:  # ACI 9.3.3.1
                return None
            result[name] = demand / capacity.phi_mn
        if round(loads.shear / resistance.phi_vn, 3) > 1.0 or not resistance.with_min_stirrups:
            return None
        need = B.beam_shear_need(loads.shear, self.b, resistance.d, self.fc, self.fy)
        if reinforcement["transverse"]["spacing"] > need.s_max + 1e-6:
            return None
        result["shear"] = loads.shear / resistance.phi_vn
        return result

    def bigger(self, loads: BeamLoads) -> str:
        """The next practical depth (50 mm steps) at which the demands have a solution."""
        step = 50.0
        h = self.h
        while h < self.h + GROWTH["beam"]:
            h += step
            g = self.geometry(h, 10.0)
            need, *_ = beam_need(g, loads.sag, loads.hog, loads.shear, self.options.beam_ratio_max)
            if not need.too_small:
                return (
                    f"try {self.b:g} x {h:g} mm (depth +{h - self.h:g} mm); the analysis must be "
                    "run again, the stiffness changes"
                )
        return f"no depth up to +{GROWTH['beam']:g} mm works: widen the beam or add a support"

    def propose(self, loads: BeamLoads) -> Pick:
        opts = self.options
        stirrup = 10.0
        stirrups: B.Stirrups | None = None
        need = None
        for _ in range(3):
            g = self.geometry(self.h, stirrup)
            need, *_, shear_need = beam_need(
                g, loads.sag, loads.hog, loads.shear, opts.beam_ratio_max
            )
            if need.too_small:
                return Pick(
                    None,
                    "",
                    0.0,
                    too_small="; ".join(need.too_small),
                    suggestion=self.bigger(loads),
                )
            stirrups = B.choose_stirrups(
                shear_need, self.b, opts.stirrup_diameters, opts.min_stirrup_spacing
            )
            if stirrups is None:
                return Pick(
                    None,
                    "",
                    0.0,
                    too_small=f"stirrups closer than {opts.min_stirrup_spacing:g} mm needed",
                    suggestion=self.bigger(loads),
                )
            if stirrups.dia == stirrup:
                break
            stirrup = stirrups.dia
        assert need is not None and stirrups is not None
        inset = self.cover + stirrups.dia
        scale = 1.0
        for _ in range(8):
            bottoms = B.face_options(
                need.bottom * scale, self.b, inset, opts.diameters, self.aggregate
            )[:5]
            tops = B.face_options(need.top * scale, self.b, inset, opts.diameters, self.aggregate)[
                :5
            ]
            combos = [
                (top, bottom)
                for top, bottom in itertools.product(tops, bottoms)
                if len({top.dia, bottom.dia}) <= opts.max_sizes
            ]
            combos.sort(
                key=lambda tb: (round(tb[0].score + tb[1].score, 1), len({tb[0].dia, tb[1].dia}))
            )
            for top, bottom in combos:
                for option in self._stirrup_options(stirrups, loads, top, bottom):
                    reinforcement = self.reinforcement(top, bottom, option)
                    utilisation = self.verify(reinforcement, loads)
                    if utilisation is not None:
                        notes = []
                        if bottom.rows > 1 or top.rows > 1:
                            notes.append("bars in 2 rows, 25 mm clear between them (ACI 25.2.2)")
                        return Pick(
                            reinforcement,
                            _beam_label(reinforcement),
                            top.area + bottom.area,
                            utilisation,
                            notes,
                        )
            scale *= 1.08
        return Pick(
            None,
            "",
            0.0,
            too_small="no practical bars found for the demands",
            suggestion=self.bigger(loads),
        )

    def _stirrup_options(self, first: B.Stirrups, loads: BeamLoads, top: Any, bottom: Any):
        """The stirrups picked at the assumed depth, then those for the arrangement's own d."""
        yield first
        probe = self.reinforcement(top, bottom, first)
        section = self._analyse(probe)[0]
        try:
            d = section.effective_depth(top=False)
        except DesignError:
            return
        need = B.beam_shear_need(loads.shear, self.b, d, self.fc, self.fy)
        again = B.choose_stirrups(
            need, self.b, self.options.stirrup_diameters, self.options.min_stirrup_spacing
        )
        if again is not None and again != first:
            yield again

    def reinforcement(self, top: B.FaceBars, bottom: B.FaceBars, stirrups: B.Stirrups):
        return {
            "material": self.material,
            "cover": self.cover,
            "longitudinal": [
                {"position": "top", "count": top.count, "dia": top.dia},
                {"position": "bottom", "count": bottom.count, "dia": bottom.dia},
                *self.sides,
            ],
            "transverse": {
                "type": self.kind,
                "dia": stirrups.dia,
                "spacing": stirrups.spacing,
                "legs": stirrups.legs,
            },
        }


def _beam_loads(member: dict[str, Any], combinations: list[str]) -> BeamLoads:
    demand = beam_demand(member, combinations)
    return BeamLoads(
        demand.overall("sag").value, demand.overall("hog").value, demand.overall("shear").value
    )


# ─────────────────────────────────────── columns ───────────────────────────────────────


def _column_label(reinforcement: dict[str, Any]) -> str:
    group = reinforcement["longitudinal"][0]
    t = reinforcement.get("transverse") or {}
    text = f"{group['count']}Ø{group['dia']:g}"
    if t:
        text += f", {t['type']}s Ø{t['dia']:g} @ {t['spacing']:g}"
        legs, legs_x = t.get("legs", 2), t.get("legsX")
        if legs_x and legs_x != legs:
            text += f" ({legs} × {legs_x} legs)"
        elif legs > 2:
            text += f" ({legs} legs)"
        if _zone_text(t):
            text += f" ({_zone_text(t)})"
    return text


def _column_pick(
    search: ColumnSearch, index: int | None, points: list[Point], confirm: bool = True
) -> Pick:
    if index is None:
        return Pick(
            None,
            "",
            0.0,
            too_small=(
                f"no layout with ρ up to {B.RHO_MAX:g} (ACI 10.6.1.1) carries the demand"
                if search.layouts
                else "no bar layout fits the section at the least clear spacing (ACI 25.2.3)"
            ),
            suggestion=_bigger_column(search, points),
        )
    if confirm:
        confirmed = search.confirm(index, points)
        if confirmed is None:
            return _column_pick(search, None, points)
        index = confirmed
    layout = search.layouts[index]
    ties = B.column_ties(
        layout,
        min(search.b, search.h),
        search.b,
        search.h,
        search.cover,
        search.options.stirrup_diameters,
    )
    reinforcement = search.reinforcement(layout, ties)
    notes = list(ties.notes)
    notes.append(f"ρ = {layout.area / search.gross:.4f}")
    utilisation = {}
    if confirm:
        utilisation["axialBending"] = search.utilisation(index, points, coarse=False)
    return Pick(reinforcement, _column_label(reinforcement), layout.area, utilisation, notes)


def _bigger_column(search: ColumnSearch, points: list[Point]) -> str:
    """The next practical size (both sides +50 mm) at which a layout of about ρ = 0.025
    carries the points (coarse surface; information only)."""
    obj = search.obj
    step = 50.0
    grow = step
    while grow <= GROWTH["column"]:
        if search.shape == "circle":
            profile: Any = CircleProfile(radius=search.b / 2 + grow / 2)
        else:
            profile = RectangleProfile(xDim=search.b + grow, yDim=search.h + grow)
        bigger = obj.model_copy(update={"profile": profile})
        trial = ColumnSearch(
            bigger, search.fc, search.fy, search.es, search.aggregate, search.options
        )
        if trial.layouts:
            target = 0.025 * trial.gross
            index = min(
                range(len(trial.layouts)), key=lambda k: abs(trial.layouts[k].area - target)
            )
            if trial.utilisation(index, points) <= 1.0:
                size = f"Ø{trial.b:g}" if trial.shape == "circle" else f"{trial.b:g} x {trial.h:g}"
                return (
                    f"try {size} mm (+{grow:g} mm) with about ρ = 0.025; the analysis must be "
                    "run again"
                )
        grow += step
    return f"no size up to +{GROWTH['column']:g} mm works: a higher concrete grade or more columns"


# ─────────────────────────────────────── slabs ───────────────────────────────────────


@dataclass
class SlabLoads:
    moments: dict[str, float]  # layer -> N·mm/m
    shear: dict[str, float]  # layer -> N/m
    combos: dict[str, str | None] = field(default_factory=dict)

    def envelope(self, other: SlabLoads) -> SlabLoads:
        names = set(self.moments) | set(other.moments)
        shear_names = set(self.shear) | set(other.shear)
        return SlabLoads(
            {n: max(self.moments.get(n, 0.0), other.moments.get(n, 0.0)) for n in names},
            {n: max(self.shear.get(n, 0.0), other.shear.get(n, 0.0)) for n in shear_names},
        )


def _slab_loads(collected: dict[str, Any], combinations: list[str]) -> SlabLoads:
    envelope = slab_envelope(collected, combinations)
    return SlabLoads(
        {n: p.value * 1e3 for n, p in envelope.items()},
        {n: v[0] for n, v in collected["context"].shear.items()},
        {n: p.combination for n, p in envelope.items()},
    )


def _mesh_label(reinforcement: dict[str, Any]) -> str:
    parts = []
    for name in slab_design.LAYERS:
        mesh = reinforcement.get(name)
        if mesh:
            parts.append(f"{name[:-1]} {name[-1]} Ø{mesh['dia']:g} @ {mesh['spacing']:g}")
    return ", ".join(parts)


class SlabDesigner:
    def __init__(self, obj: Slab, fc: float, fy: float, es: float, options: Options) -> None:
        self.obj = obj
        reinforcement = obj.reinforcement
        assert reinforcement is not None
        self.cover = reinforcement.cover
        self.material = reinforcement.material
        self.present = {n for n in slab_design.LAYERS if getattr(reinforcement, n) is not None}
        self.fc, self.fy, self.es = fc, fy, es
        self.options = options

    def propose(self, loads: SlabLoads, h: float | None = None, suggest: bool = True) -> Pick:
        h = h or self.obj.thickness
        span = slab_design.span_direction(self.obj.system, loads.moments)
        rules = slab_layer_rules(self.obj.system, h, span)
        reinforcement: dict[str, Any] = {"material": self.material, "cover": self.cover}
        notes: list[str] = []
        small: list[str] = []
        utilisation: dict[str, float] = {}
        total = 0.0
        for face in ("bottom", "top"):
            outer = 0.0
            for direction in ("X", "Y"):
                name = f"{face}{direction}"
                moment = loads.moments.get(name, 0.0)
                q = loads.shear.get(name)
                if name not in self.present and moment <= slab_design.NO_DEMAND * 1e3 and not q:
                    continue
                in_span = span is None or direction == span
                required_of: dict[float, float] = {}
                for dia in self.options.slab_diameters:
                    d = h - self.cover - (dia / 2 if direction == "X" else outer + dia / 2)
                    shear = (q, None, "") if q else None
                    required, _, layer_notes, too_small = slab_layer_need(
                        name, moment, d, h, self.fc, self.fy, self.es, in_span, shear
                    )
                    if too_small:
                        small.append(f"{name}: " + "; ".join(n for n in layer_notes if n))
                        break
                    required_of[dia] = required
                if small:
                    break
                s_max, rule = rules[name]
                mesh = B.mesh_for(
                    0.0,
                    s_max,
                    self.options.slab_diameters,
                    self.options.min_slab_spacing,
                    required_of,
                )
                if mesh is None:
                    small.append(
                        f"{name}: bars closer than {self.options.min_slab_spacing:g} mm needed"
                    )
                    break
                reinforcement[name] = {"dia": mesh.dia, "spacing": mesh.spacing}
                total += mesh.area
                d = h - self.cover - (mesh.dia / 2 if direction == "X" else outer + mesh.dia / 2)
                capacity = slab_design.layer_capacity(mesh.area, d, self.fc, self.fy, self.es)
                if moment > 0:
                    utilisation[name] = moment / capacity.phi_mn
                if q:
                    phi_vc, _ = slab_design.one_way_shear(mesh.area / (1000 * d), d, self.fc)
                    utilisation[f"shear {name}"] = q / phi_vc
                if direction == "X":
                    outer = mesh.dia
                notes.append(f"{name}: spacing ≤ {s_max:.0f} mm ({rule})")
            if small:
                break
        if small:
            suggestion = self.thicker(loads) if suggest else ""
            return Pick(None, "", 0.0, too_small="; ".join(small), suggestion=suggestion)
        if self.obj.system == "flat":
            notes.append(
                "flat slab: punching is not cured by flexural bars; check it after applying"
            )
        return Pick(reinforcement, _mesh_label(reinforcement), total, utilisation, notes)

    def thicker(self, loads: SlabLoads) -> str:
        h = self.obj.thickness
        while h < self.obj.thickness + GROWTH["slab"]:
            h += 25.0
            if self.propose(loads, h, suggest=False).reinforcement is not None:
                return (
                    f"try {h:g} mm (+{h - self.obj.thickness:g} mm); the analysis must be run again"
                )
        return f"no thickness up to +{GROWTH['slab']:g} mm works: add beams or drop panels"


# ─────────────────────────────────────── grouping ───────────────────────────────────────


@dataclass
class MemberPick:
    id: str
    loads: Any
    pick: Pick


def _over_designed(type_pick: Pick, members: list[MemberPick], threshold: float):
    found = []
    for m in members:
        if m.pick.reinforcement is None or m.pick.area <= 0 or type_pick.area <= 0:
            continue
        ratio = type_pick.area / m.pick.area - 1
        if ratio > threshold + 1e-9:
            found.append({"member": m.id, "own": m.pick.label, "overDesign": round(ratio, 3)})
    return found


def _groups(type_pick: Pick, members: list[MemberPick], threshold: float, limit: int):
    """The members that may leave the type, grouped (``[[MemberPick, ...], ...]``): those
    over-designed by more than ``threshold``, by their own bars; at most ``limit`` groups, the
    most populous kept, the members of the others joining the lightest kept group at least as
    heavy as their own bars (or staying)."""
    candidates = [
        m
        for m in members
        if m.pick.reinforcement is not None
        and m.pick.area > 0
        and type_pick.area / m.pick.area - 1 > threshold + 1e-9
    ]
    by_signature: dict[str, list[MemberPick]] = {}
    for m in candidates:
        by_signature.setdefault(json.dumps(m.pick.reinforcement, sort_keys=True), []).append(m)
    ordered = sorted(by_signature.values(), key=lambda g: (-len(g), g[0].pick.area))
    kept = [list(g) for g in ordered[:limit]]
    for group in ordered[limit:]:
        for m in group:
            home = min(
                (k for k in kept if k[0].pick.area >= m.pick.area),
                key=lambda k: k[0].pick.area,
                default=None,
            )
            if home is not None:
                home.append(m)
    return sorted(kept, key=lambda g: -g[0].pick.area)


def _split(
    pick: Pick, members: list[MemberPick], opts: Options, propose_for
) -> tuple[list[tuple[list[MemberPick], Pick]], Pick]:
    """The groups that leave the type, each with its own pick, and the pick of the members that
    stay. A group whose own envelope finds no bars does not leave: its members stay in the type
    and in the envelope its bars are designed for."""
    groups = _groups(pick, members, opts.over_design, opts.max_new_types)
    grouped = {m.id for group in groups for m in group}
    if not groups or all(m.id in grouped for m in members):
        return [], pick
    accepted: list[tuple[list[MemberPick], Pick]] = []
    for group in groups:
        envelope = group[0].loads
        for m in group[1:]:
            envelope = envelope.envelope(m.loads)
        group_pick = propose_for(envelope)
        if group_pick.reinforcement is not None:
            accepted.append((group, group_pick))
    if not accepted:
        return [], pick
    leaving = {m.id for group, _ in accepted for m in group}
    staying = [m for m in members if m.id not in leaving]
    envelope = staying[0].loads
    for m in staying[1:]:
        envelope = envelope.envelope(m.loads)
    return accepted, propose_for(envelope)


def _new_id(base: str, taken: set[str]) -> tuple[str, int]:
    k = 2
    while f"{base}-{k}" in taken:
        k += 1
    taken.add(f"{base}-{k}")
    return f"{base}-{k}", k


# ─────────────────────────────────────── the proposal ───────────────────────────────────────


def _entry(
    type_id: str,
    kind: str,
    name: str,
    current: dict[str, Any] | None,
    label_of,
    pick: Pick,
    members: list[MemberPick],
    governing: str | None,
    over: list[dict[str, Any]],
    demand: dict[str, Any],
) -> dict[str, Any]:
    status = "tooSmall" if pick.reinforcement is None else "ok"
    if status == "ok" and current is not None and _same(current, pick.reinforcement):
        status = "unchanged"
    return {
        "type": type_id,
        "kind": kind,
        "name": name,
        "current": None if current is None else bars_of(current, label_of(current)),
        "proposed": bars_of(pick.reinforcement, pick.label),
        "status": status,
        "governingMember": governing,
        "members": [m.id for m in members],
        "demand": demand,
        "utilisation": {k: round(float(v), 3) for k, v in pick.utilisation.items()},
        "overDesigned": [o["member"] for o in over],
        "overDesignedDetails": over,
        "tooSmall": None
        if pick.reinforcement is not None
        else {"reason": pick.too_small, "suggestion": pick.suggestion},
        "notes": pick.notes,
    }


def bars_of(reinforcement: dict[str, Any] | None, label: str) -> dict[str, Any] | None:
    """Bars as the proposal reports them: the reinforcement (04 Objects' or 09 Substructure's
    shape) with its description under ``"text"``."""
    if reinforcement is None:
        return None
    return {**copy.deepcopy(reinforcement), "text": label}


def reinforcement_of(bars: dict[str, Any]) -> dict[str, Any]:
    """The reinforcement of reported bars (:func:`bars_of`): without ``"text"``."""
    return {k: copy.deepcopy(v) for k, v in bars.items() if k != "text"}


def _normal(value: Any) -> Any:
    """``value`` with every number a float and no empty entries, to compare bars."""
    if isinstance(value, dict):
        return {k: _normal(v) for k, v in value.items() if v is not None and k != "text"}
    if isinstance(value, list):
        return [_normal(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return value


def _same(a: dict[str, Any], b: dict[str, Any] | None) -> bool:
    """Whether two reinforcements are the same bars (numbers compared as floats; a transverse
    without legs has 2)."""
    if b is None:
        return False
    a, b = _normal(a), _normal(b)
    for bars in (a, b):
        transverse = bars.get("transverse")
        if isinstance(transverse, dict):
            transverse.setdefault("legs", 2.0)
    return a == b


def design_proposal(
    out_dir: str | Path,
    project_path: str | Path,
    options: dict[str, Any] | None = None,
    gathered: Gathered | None = None,
) -> dict[str, Any]:
    """The proposed bars of every designed object type and foundation (see the module notes).

    ``options``: ``mode`` "byType" (default) or "splitTypes", ``diameters``,
    ``stirrupDiameters``, ``maxSizes`` (bar sizes per beam, 2), ``overDesign`` (0.25: members
    whose own bars would be 25 % lighter are listed), ``maxNewTypes`` (3 per type).

    Returns ``{"mode", "types": [{"type", "kind", "name", "current", "proposed", "status"
    ("ok", "unchanged", "tooSmall"), "governingMember", "members", "demand", "utilisation",
    "overDesigned" (member ids), "overDesignedDetails" ([{"member", "own", "overDesign"}]),
    "tooSmall" ({"reason", "suggestion"} or None), "notes", "byType" (splitTypes only: the
    single-type proposal)}], "newTypes": [{"type", "from", "kind", "name", "proposed",
    "members", "governingMember", "utilisation"}], "reassign": [{"member", "from", "to",
    "source"}], "foundations": [{"id", "type", "current", "proposed", "status", "notes",
    "otherFailures", "tooSmall"}], "warnings"}``; ``current``/``proposed`` are the
    reinforcement in the shape of 04 Objects (09 Substructure for foundations) with its
    description under ``"text"`` (:func:`bars_of`), or None.
    """
    raw = options or {}
    mode = raw.get("mode", "byType")
    if mode not in ("byType", "splitTypes"):
        raise ValueError(f"unknown mode '{mode}' (byType or splitTypes)")
    opts = Options.of(raw)
    gathered = gathered or gather(out_dir, project_path)
    combinations = gathered.collect.get("combinations", [])
    originals = {o["id"]: o for o in json.loads(gathered.objects_text).get("objects", [])}
    taken = set(originals)
    sources = {e.id: getattr(e, "source", None) for e in gathered.building.elements}
    types: list[dict[str, Any]] = []
    new_types: list[dict[str, Any]] = []
    reassign: list[dict[str, Any]] = []
    warnings: list[str] = list(gathered.notes)

    def current_of(type_id: str) -> dict[str, Any] | None:
        if type_id in gathered.assumed:
            return None
        return (originals.get(type_id) or {}).get("reinforcement")

    collected_by_id = {m["id"]: m for m in gathered.collect.get("members", [])}
    beam_designers: dict[str, BeamDesigner] = {}

    def split(
        type_id: str,
        kind: str,
        name: str,
        label_of,
        pick: Pick,
        members: list[MemberPick],
        propose_for,
    ) -> Pick:
        """Splits off the over-designed members; returns the remaining members' pick."""
        accepted, remaining = _split(pick, members, opts, propose_for)
        for group, group_pick in accepted:
            # The new type's own members' seismic detailing (hoop zones, Mn+ >= Mn-/2).
            own = [collected_by_id[m.id] for m in group if m.id in collected_by_id]
            if own and kind in ("beam", "column"):
                if kind == "beam" and type_id in beam_designers:
                    loads = group[0].loads
                    for m in group[1:]:
                        loads = loads.envelope(m.loads)
                    group_pick = _beam_positive_moment(
                        beam_designers[type_id], group_pick, loads, own
                    )
                _with_seismic(group_pick, kind, own[0]["object"], own, label_of, opts)
            new_id, k = _new_id(type_id, taken)
            governing = max(group, key=lambda m: m.pick.area).id
            new_types.append(
                {
                    "type": new_id,
                    "from": type_id,
                    "kind": kind,
                    "name": f"{name} ({k})",
                    "proposed": bars_of(group_pick.reinforcement, group_pick.label),
                    "members": [m.id for m in group],
                    "governingMember": governing,
                    "utilisation": {
                        kk: round(float(v), 3) for kk, v in group_pick.utilisation.items()
                    },
                }
            )
            for m in group:
                reassign.append(
                    {"member": m.id, "from": type_id, "to": new_id, "source": sources.get(m.id)}
                )
        return remaining

    # Beams.
    beams: dict[str, list[dict[str, Any]]] = {}
    for member in gathered.collect.get("members", []):
        if member["kind"] == "beam":
            beams.setdefault(member["type"], []).append(member)
    for type_id, members in beams.items():
        first = members[0]
        try:
            designer = BeamDesigner(
                first["object"], first["fc"], first["fy"], first["es"], first["aggregate"], opts
            )
        except DesignError as error:
            warnings.append(f"{type_id}: {error}")
            continue
        beam_designers[type_id] = designer
        picks = []
        cache: dict[BeamLoads, Pick] = {}
        for member in members:
            loads = _beam_loads(member, combinations)
            key = BeamLoads(*(round(v, -3) for v in (loads.sag, loads.hog, loads.shear)))
            if key not in cache:
                cache[key] = designer.propose(loads)
            picks.append(MemberPick(member["id"], loads, cache[key]))
        envelope = picks[0].loads
        for m in picks[1:]:
            envelope = envelope.envelope(m.loads)
        pick = designer.propose(envelope)
        pick = _beam_positive_moment(designer, pick, envelope, members)
        governing = max(picks, key=lambda m: m.pick.area if m.pick.reinforcement else math.inf).id
        over = _over_designed(pick, picks, opts.over_design) if pick.reinforcement else []
        by_type_pick = pick
        if mode == "splitTypes" and pick.reinforcement is not None:
            pick = split(
                type_id, "beam", first["object"].name, _beam_label, pick, picks, designer.propose
            )
        seismic = _with_seismic(pick, "beam", first["object"], members, _beam_label, opts)
        entry = _entry(
            type_id,
            "beam",
            first["object"].name,
            current_of(type_id),
            _beam_label,
            pick,
            picks,
            governing,
            over,
            {
                "sagging": round(envelope.sag / 1e6, 2),
                "hogging": round(envelope.hog / 1e6, 2),
                "shear": round(envelope.shear / 1e3, 2),
                "units": {"sagging": "kN·m", "hogging": "kN·m", "shear": "kN"},
            },
        )
        if mode == "splitTypes":
            entry["byType"] = bars_of(by_type_pick.reinforcement, by_type_pick.label)
        _seismic_entry(entry, seismic, warnings)
        types.append(entry)

    # Columns.
    for type_id, (search, members) in column_requirements(gathered, opts).items():
        obj = search.obj
        picks = []
        for member_id, (index, points) in members.items():
            picks.append(
                MemberPick(
                    member_id,
                    _ColumnLoads(index, points),
                    _column_pick(search, index, points, confirm=False),
                )
            )
        all_points = [p for _, points in members.values() for p in points]
        indices = [index for index, _ in members.values()]
        index = None if any(i is None for i in indices) else max(indices, default=None)
        pick = _column_pick(search, index, all_points)
        governing = max(picks, key=lambda m: m.pick.area if m.pick.reinforcement else math.inf).id
        over = _over_designed(pick, picks, opts.over_design) if pick.reinforcement else []
        by_type_pick = pick

        if mode == "splitTypes" and pick.reinforcement is not None:
            pick = split(
                type_id,
                "column",
                obj.name,
                _column_label,
                pick,
                picks,
                lambda loads, s=search: _column_pick(s, loads.index, loads.points),
            )
        collected = [m for m in gathered.collect.get("members", []) if m["type"] == type_id]
        seismic = _with_seismic(pick, "column", obj, collected, _column_label, opts)
        governing_points = next((pts for mid, (_, pts) in members.items() if mid == governing), [])
        top = max(governing_points, key=lambda p: math.hypot(p[1], p[2]), default=None)
        entry = _entry(
            type_id,
            "column",
            obj.name,
            current_of(type_id),
            _column_label,
            pick,
            picks,
            governing,
            over,
            {
                "maxAxial": round(max((p[0] for p in all_points), default=0.0) / 1e3, 1),
                "maxMoment": round(math.hypot(top[1], top[2]) / 1e6, 2) if top else 0.0,
                "units": {"maxAxial": "kN", "maxMoment": "kN·m"},
            },
        )
        if mode == "splitTypes":
            entry["byType"] = bars_of(by_type_pick.reinforcement, by_type_pick.label)
        _seismic_entry(entry, seismic, warnings)
        types.append(entry)

    # Slabs.
    slabs: dict[str, list[dict[str, Any]]] = {}
    for collected in gathered.collect.get("slabs", []):
        slabs.setdefault(collected["type"], []).append(collected)
    for type_id, collected in slabs.items():
        first = collected[0]
        designer = SlabDesigner(first["object"], first["fc"], first["fy"], first["es"], opts)
        picks = [
            MemberPick(c["id"], loads, designer.propose(loads))
            for c in collected
            for loads in (_slab_loads(c, combinations),)
        ]
        envelope = picks[0].loads
        for m in picks[1:]:
            envelope = envelope.envelope(m.loads)
        pick = designer.propose(envelope)
        governing = max(picks, key=lambda m: m.pick.area if m.pick.reinforcement else math.inf).id
        over = _over_designed(pick, picks, opts.over_design) if pick.reinforcement else []
        by_type_pick = pick
        if mode == "splitTypes" and pick.reinforcement is not None:
            pick = split(
                type_id, "slab", first["object"].name, _mesh_label, pick, picks, designer.propose
            )
        flat = [
            c["name"]
            for c in itertools.chain.from_iterable(x["checks"] for x in collected)
            if c["name"].startswith("Punching") and not c["ok"]
        ]
        entry = _entry(
            type_id,
            "slab",
            first["object"].name,
            current_of(type_id),
            _mesh_label,
            pick,
            picks,
            governing,
            over,
            {
                "moments": {k: round(v / 1e6, 2) for k, v in envelope.moments.items()},
                "shear": {k: round(v / 1e3, 2) for k, v in envelope.shear.items()},
                "units": {"moments": "kN·m/m", "shear": "kN/m"},
            },
        )
        if flat:
            failing = ", ".join(sorted(set(flat)))
            entry["notes"] = [
                *entry["notes"],
                f"punching fails ({failing}): thicken the slab, add drop panels or shear bars",
            ]
        if mode == "splitTypes":
            entry["byType"] = bars_of(by_type_pick.reinforcement, by_type_pick.label)
        _with_punching(entry, itertools.chain.from_iterable(x["checks"] for x in collected))
        types.append(entry)

    # Integrator glue: wall types (saengine.design.wall_design) and staircase types (stairs.py).
    from saengine.design import stairs as stair_design
    from saengine.design import wall_design

    types += wall_design.proposal_entries(
        gathered.collect.get("walls", []), gathered.assumed, originals
    )
    types += stair_design.proposal_entries(
        gathered.collect.get("stairs", []), opts.slab_diameters, opts.min_slab_spacing
    )
    # Integrator glue: steel beam, column and brace types (saengine.design.steel_design): the
    # lightest section of the type's family that passes (entries with ``family``; applied as a
    # new profile, see apply_proposal). Split types are not made for steel.
    from saengine.design import steel_design

    steel_types, steel_notes = steel_design.proposal_entries(
        gathered.collect.get("steel", []), originals
    )
    types += steel_types
    warnings += steel_notes

    foundations = [_foundation_entry(d, opts) for d in foundation_demands(gathered)]
    # Integrator glue: the footings' punching studs or stirrups (saengine.design.punching).
    checks_of = {
        r["id"]: r.get("checks", [])
        for r in (gathered.substructure or {}).get("foundations", [])
        if isinstance(r, dict) and "id" in r
    }
    for entry in foundations:
        _with_punching(entry, checks_of.get(entry["id"], []))
    for t in types:
        if t["status"] == "tooSmall":
            warnings.append(f"{t['type']}: section too small — {t['tooSmall']['reason']}")
    return {
        "mode": mode,
        "types": types,
        "newTypes": new_types,
        "reassign": reassign,
        "foundations": foundations,
        "warnings": warnings,
    }


# ─────────────────────────────────── seismic detailing ───────────────────────────────────


def _zone_text(transverse: dict[str, Any]) -> str:
    zone = transverse.get("zone") or {}
    if not zone:
        return ""
    text = f"ends @ {zone['spacing']:g}"
    if zone.get("length"):
        text += f" over {zone['length']:g}"
    return text + f", elsewhere @ {transverse['spacing']:g}"


def _seismic_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["seismicContext"] for m in members if m.get("seismicContext")]


def seismic_transverse(
    kind: str,
    obj: Any,
    reinforcement: dict[str, Any],
    members: list[dict[str, Any]],
    fc: float,
    fy: float,
    es: float,
    aggregate: float | None,
    opts: Options,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The proposed reinforcement with the hoop zones of BNBC Sec 8.3 for the type's members
    (their detailing contexts, :class:`saengine.design.seismic_detailing.Designed`), and what
    the detailing asks of the type: ``{"zones", "sectionTooSmall", "notes"}`` (None when no
    member has a Sec 8.3 rule).

    Ties: the legs hold every corner and alternate bar (8.1.9.4(c), 8.3.4.3(c), 8.3.5.4(a)(iii))
    and keep hx ≤ 350 mm (8.3.5.4(c)); the zone spacing is the smallest of every member's lo
    spacing (so, Ash of Eq. 6.8.7, 6.8.8), its capacity shear's Av/s (Sec 8.3.8, 8.3.10.3, Ve
    from the proposed bars' Mpr) and the strength design's; the diameter and legs are the
    lightest (legs × dia²) that keep it at least ``opts.min_stirrup_spacing``. Dimensions
    the frame type needs (8.3.4.1, 8.3.5.1) are reported as "section too small", nothing
    is changed for them."""
    from saengine.design import ductile_members as dm
    from saengine.design.bars import round_down
    from saengine.design.seismic_detailing import capacity_av_s

    contexts = _seismic_members(members)
    if not contexts:
        return reinforcement, None
    section = section_of(
        obj.profile, LinearReinforcement.model_validate(reinforcement), fc, fy, es, aggregate
    )
    t = dict(reinforcement["transverse"])
    circle = isinstance(obj.profile, CircleProfile)
    b, h = (obj.profile.xDim, obj.profile.yDim) if not circle else (2 * obj.profile.radius,) * 2
    cover = reinforcement["cover"]
    special = [c for c in contexts if c["level"] == "special"]
    too_small: list[str] = []
    notes: list[str] = []
    if any(c["lateral"] for c in special):
        need = dm.minimum_dimensions(kind, "special", h)
        if kind == "beam" and b < need["width"] - 1e-6:
            too_small.append(
                f"width {b:g} mm below max(250 mm, 0.3 h) = {need['width']:g} mm of a special "
                "moment frame beam (Sec 8.3.4.1(c), (d))"
            )
        if kind == "column":
            if min(b, h) < need["least"] - 1e-6:
                too_small.append(
                    f"least dimension {min(b, h):g} mm below 300 mm of a special moment frame "
                    "column (Sec 8.3.5.1(a))"
                )
            if min(b, h) / max(b, h) < need["ratio"] - 1e-9:
                too_small.append(
                    f"{b:g} x {h:g} mm: least to perpendicular dimension below 0.4 (Sec 8.3.5.1(b))"
                )
            rho = section.steel_area / section.gross_area
            if rho > dm.SMF_COLUMN_RHO[1] + 1e-9:
                too_small.append(
                    f"ρg = {100 * rho:.2f} % above 6 % of a special moment frame column (Sec "
                    "8.3.5.3(a))"
                )

    # Legs: every corner and alternate bar held, in the faces the rules cover.
    legs, legs_x = int(t.get("legs", 2)), int(t.get("legsX") or t.get("legs", 2))
    if special and not circle:
        legs = max(
            legs,
            dm.held_required(dm._face_bars(section, "y", 1)),
            dm.held_required(dm._face_bars(section, "y", -1)),
            2,
        )
        if kind == "column":
            legs_x = max(
                legs_x,
                dm.held_required(dm._face_bars(section, "x", 1)),
                dm.held_required(dm._face_bars(section, "x", -1)),
                2,
            )
    av_s: dict[str, float] = {}
    for c in contexts:
        for axis, value in capacity_av_s(section, kind, c).items():
            av_s[axis] = max(av_s.get(axis, 0.0), value)

    def zones_for(dia: float, ly: int, lx: int) -> dict[str, Any] | None:
        db = min(bar.dia for bar in section.bars)
        if kind == "column" and special and not circle:
            hx = max(dm._hx(b - 2 * cover, dia, db, ly), dm._hx(h - 2 * cover, dia, db, lx))
            if hx > dm.HX_MAX:
                return None
        area = bar_area(dia)
        shear_spacing = float(t["spacing"])
        for axis, value in av_s.items():
            if value > 0:
                count = ly if axis == "y" else lx
                shear_spacing = min(shear_spacing, count * area / value)
        found: dict[str, Any] = {}
        zones = dm.Zones(t["type"], dia, float(t["spacing"]), ly, lx if kind == "column" else None)
        for c in contexts:
            if kind == "beam":
                need = dm.beam_need(section, c["level"], dia, c["lateral"])
            else:
                need = dm.column_need(
                    section,
                    c["level"],
                    c["cover"],
                    zones,
                    clear_height=c.get("clearHeight"),
                    axial=c["axial"][0],
                    lateral=c["lateral"],
                    full_height=c.get("fullHeight", False),
                )
                if not need.applies:
                    continue
            proposed = dm.propose_zones(need, dia, ly, lx, shear_spacing)
            if proposed is None:
                continue
            if "spacing" in proposed:
                found["spacing"] = min(found.get("spacing", math.inf), proposed["spacing"])
            if "zone" in proposed:
                z = found.setdefault("zone", {})
                for key, pick in (("length", max), ("spacing", min), ("first", min)):
                    if key in proposed["zone"]:
                        z[key] = pick(z.get(key, proposed["zone"][key]), proposed["zone"][key])
            if "splice" in proposed:
                s = proposed["splice"]["spacing"]
                found["splice"] = {
                    "spacing": min(found.get("splice", {"spacing": s})["spacing"], s)
                }
        if not found:
            found["spacing"] = round_down(shear_spacing)
        smallest = min(
            [found.get("spacing", math.inf), found.get("zone", {}).get("spacing", math.inf)]
        )
        if smallest < opts.min_stirrup_spacing - 1e-6:
            return None
        return found

    candidates = sorted(
        (
            (dia, ly, lx)
            for dia in opts.stirrup_diameters
            if dia >= float(t["dia"]) - 1e-9
            for ly in range(legs, legs + 3)
            for lx in (range(legs_x, legs_x + 3) if kind == "column" else (legs_x,))
        ),
        key=lambda c: ((c[1] + (c[2] if kind == "column" else 0)) * c[0] ** 2, c[0]),
    )
    chosen = None
    for dia, ly, lx in candidates:
        found = zones_for(dia, ly, lx)
        if found is not None:
            chosen = (dia, ly, lx, found)
            break
    if chosen is None:
        too_small.append(
            "no ties up to "
            f"Ø{max(opts.stirrup_diameters):g} with 2 more legs give the seismic hoops at "
            f"{opts.min_stirrup_spacing:g} mm or more: enlarge the section"
        )
        return reinforcement, {"zones": None, "sectionTooSmall": too_small, "notes": notes}
    dia, ly, lx, found = chosen
    transverse = {
        **t,
        "dia": dia,
        "legs": ly,
        "spacing": min(float(t["spacing"]), found["spacing"]),
    }
    if kind == "column" and lx != ly:
        transverse["legsX"] = lx
    else:
        transverse.pop("legsX", None)
    if "zone" in found:
        zone = dict(found["zone"])
        zone["spacing"] = min(zone["spacing"], transverse["spacing"])
        transverse["zone"] = zone
    else:
        transverse.pop("zone", None)
    if "splice" in found:
        transverse["splice"] = found["splice"]
    else:
        transverse.pop("splice", None)
    if av_s:
        notes.append(
            "hoops for the capacity shear Ve (Sec 8.3.8 / 8.3.10.3): Av/s "
            + ", ".join(f"{axis} {value:.2f} mm²/mm" for axis, value in sorted(av_s.items()))
        )
    result = {**reinforcement, "transverse": transverse}
    return result, {"zones": transverse.get("zone"), "sectionTooSmall": too_small, "notes": notes}


def _with_seismic(
    pick: Pick,
    kind: str,
    obj: Any,
    members: list[dict[str, Any]],
    label_of,
    opts: Options,
) -> dict[str, Any] | None:
    """Adds the seismic hoop zones to ``pick`` (in place) and returns the detailing info."""
    if pick.reinforcement is None or not _seismic_members(members):
        return None
    first = members[0]
    try:
        reinforcement, info = seismic_transverse(
            kind,
            obj,
            pick.reinforcement,
            members,
            first["fc"],
            first["fy"],
            first["es"],
            first["aggregate"],
            opts,
        )
    except DesignError as error:
        return {"zones": None, "sectionTooSmall": [], "notes": [f"seismic detailing: {error}"]}
    pick.reinforcement = reinforcement
    pick.label = label_of(reinforcement)
    if info:
        pick.notes = [*pick.notes, *info["notes"]]
    return info


def _seismic_entry(
    entry: dict[str, Any], seismic: dict[str, Any] | None, warnings: list[str]
) -> None:
    """The detailing info on a type's entry (``"detailing"``), its "section too small" findings
    also as warnings (bars cannot fix them)."""
    entry["detailing"] = seismic
    if seismic:
        for reason in seismic["sectionTooSmall"]:
            warnings.append(
                f"{entry['type']}: section too small for the seismic detailing — {reason}"
            )


def _beam_positive_moment(
    designer: BeamDesigner, pick: Pick, loads: BeamLoads, members: list[dict[str, Any]]
) -> Pick:
    """Sec 8.3.4.2(a) (special frames, and members outside the system in Category D): at
    least ρmin = max(0.25 √f'c, 1.4)/fy top and bottom (no 4/3 As relief) and Mn+ at the face
    at least half of Mn-; the demands are raised until the bars give both (3 tries)."""
    from saengine.design import ductile_members as dm

    if pick.reinforcement is None:
        return pick
    if not any(c["level"] == "special" or not c["lateral"] for c in _seismic_members(members)):
        return pick
    rho_min = max(0.25 * math.sqrt(designer.fc), 1.4) / designer.fy

    def floor(area: float, d: float) -> float:
        """φ Mn of ``area`` at depth ``d`` (rectangular block), a little above."""
        a = area * designer.fy / (0.85 * designer.fc * designer.b)
        return 0.9 * area * designer.fy * (d - a / 2) * 1.02

    for _ in range(3):
        section, sag, hog, _ = designer._analyse(pick.reinforcement)
        new_sag, new_hog, why = loads.sag, loads.hog, []
        for top in (True, False):
            bars = dm.face_steel(section, top)
            d = dm._face_depth(section, top) or 0.9 * designer.h
            need = rho_min * designer.b * d
            if sum(bar.area for bar in bars) < need - 1e-6:
                if top:
                    new_hog = max(new_hog, floor(need, d))
                else:
                    new_sag = max(new_sag, floor(need, d))
                why.append(f"{'top' if top else 'bottom'} bars at least ρmin (Sec 8.3.4.2(a))")
        if sag.mn < 0.5 * hog.mn - 1e-6:
            new_sag = max(new_sag, 0.5 * hog.phi_mn * 1.02)
            why.append("bottom bars for Mn+ ≥ Mn-/2 (Sec 8.3.4.2(a))")
        if not why:
            return pick
        loads = BeamLoads(new_sag, new_hog, loads.shear)
        again = designer.propose(loads)
        if again.reinforcement is None:
            return pick
        again.notes = [*again.notes, *why]
        pick = again
    return pick


@dataclass(frozen=True)
class _ColumnLoads:
    index: int | None
    points: list[Point]

    def envelope(self, other: _ColumnLoads) -> _ColumnLoads:
        if self.index is None or other.index is None:
            index = None
        else:
            index = max(self.index, other.index)
        return _ColumnLoads(index, [*self.points, *other.points])

    def __hash__(self) -> int:  # points are a list
        return id(self)


# ─────────────────────────────────────── foundations ───────────────────────────────────────


#: Lines the shared layout may get beyond its first merge while the re-check asks for them.
PUNCHING_EXTRA_LINES = 10


def punching_layout(
    checks: Any,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """Integrator glue: one ``punchingReinforcement`` (04 Objects' slab type, 09 Substructure's
    foundation; :class:`saengine.library.objects.PunchingReinforcement`) for every column of
    the punching checks, from the layout each column got (``shearReinforcement``; where the
    given layout fails, the one proposed without it, ``proposedReinforcement``):

    - the larger diameter and elements per line, the shorter first line and spacing;
    - enough lines to reach as far from the face as the farthest-reaching column's own layout
      (``ceil((max extent - s0) / s) + 1`` with extent = s0 + (lines - 1) s), since the outer
      critical section of each column must lie at least as far out as its own layout put it;
    - then, where the rows can be re-checked (:class:`saengine.design.punching.PunchingRow`),
      checked at every column again, a line added while a column fails (at most
      :data:`PUNCHING_EXTRA_LINES`).

    Returns (layout or None, the columns where no layout works (a thicker member is needed),
    the columns the shared layout still fails (then no layout is proposed))."""
    rows: list[tuple[str, Any, dict[str, Any]]] = []
    thicken: list[str] = []
    for c in checks:
        name = str(c.get("name", ""))
        if not name.startswith("Punching at"):
            continue
        column = name[len("Punching at ") :]
        r = (
            c["proposedReinforcement"]
            if "proposedReinforcement" in c
            else c.get("shearReinforcement")
        )
        if isinstance(r, dict):
            rows.append((column, c, r))
        elif not c.get("ok", True):
            thicken.append(column)
    if not rows:
        return None, thicken, []
    kind = "studs" if any(r["kind"] == "studs" for _, _, r in rows) else "stirrups"
    same = [r for _, _, r in rows if r["kind"] == kind]
    s0 = min(float(r["s0"]) for r in same)
    s = min(float(r["s"]) for r in same)
    extent = max(float(r["s0"]) + (int(r["lines"]) - 1) * float(r["s"]) for r in same)
    lines = max(
        max(int(r["lines"]) for r in same),
        math.ceil((extent - s0) / s - 1e-9) + 1,
    )
    layout: dict[str, Any] = {
        "kind": kind,
        "dia": max(float(r["bar"]) for r in same),
        "perLine": max(int(r["perLine"]) for r in same),
        "lines": lines,
        "firstLine": s0,
        "spacing": s,
    }
    fyt = {float(r["fyt"]) for r in same if r.get("fyt")}
    if len(fyt) == 1:
        layout["fyt"] = fyt.pop()
    rechecks = [(column, getattr(c, "recheck", None)) for column, c, _ in rows]
    rechecks = [(column, f) for column, f in rechecks if f is not None]
    # Columns of the other kind are not covered by this layout unless the re-check says so.
    uncovered = [column for column, _, r in rows if r["kind"] != kind]
    if not rechecks:
        return layout, thicken, uncovered

    def fails(f: Any) -> bool:
        try:
            row = f(layout)
        except (ValueError, ArithmeticError, KeyError):
            return True
        return row is not None and not row.get("ok", False)

    checked = {column for column, _ in rechecks}
    unchecked = [column for column in uncovered if column not in checked]
    failing: list[str] = []
    for _ in range(PUNCHING_EXTRA_LINES + 1):
        failing = [column for column, f in rechecks if fails(f)]
        if not failing:
            return layout, thicken, unchecked
        layout["lines"] += 1
    return None, thicken, failing + unchecked


def _punching_text(layout: dict[str, Any] | None) -> str | None:
    if not layout:
        return None
    what = "headed studs" if layout["kind"] == "studs" else "stirrup legs"
    return (
        f"Ø{layout['dia']:g} {what}, {layout['perLine']} per line, {layout['lines']} lines, "
        f"first {layout['firstLine']:g} mm from the face, @ {layout['spacing']:g} mm"
    )


def _with_punching(entry: dict[str, Any], checks: Any) -> None:
    """Adds the punching reinforcement proposed for a slab type or foundation to its entry:
    ``punching`` ``{"current", "proposed", "text"}`` and notes."""
    checks = list(checks)
    layout, thicken, uncovered = punching_layout(checks)
    given_fails = sorted(
        {
            str(c["name"])[len("Punching at ") :]
            for c in checks
            if str(c.get("name", "")).startswith("Punching at") and "proposedReinforcement" in c
        }
    )
    if given_fails:
        entry["notes"] = [
            *entry.get("notes", []),
            (
                f"punching at {', '.join(given_fails)}: the given studs or stirrups are not "
                "enough; a new layout is proposed from the columns' demands"
            ),
        ]
    if layout is not None:
        rechecked = any(getattr(c, "recheck", None) is not None for c in checks)
        entry["punching"] = {"proposed": layout, "text": _punching_text(layout)}
        entry["notes"] = [
            *entry.get("notes", []),
            (
                f"punching: {_punching_text(layout)} round every column of it (one layout for "
                "all: the larger bar and elements per line, the shorter first line and "
                "spacing, lines reaching as far as the farthest column's own layout"
                + ("; checked again at every column" if rechecked else "")
                + "; BNBC 2020 Part 6 Sec 6.4.10)"
            ),
        ]
    if uncovered:
        entry["notes"] = [
            *entry.get("notes", []),
            (
                f"punching at {', '.join(sorted(set(uncovered)))}: one stud or stirrup layout "
                "for the whole type does not pass at these columns"
                + (" (none is proposed)" if layout is None else "")
                + ": give them their own slab type or footing, or detail them by hand"
            ),
        ]
    if thicken:
        entry["notes"] = [
            *entry.get("notes", []),
            (
                f"punching at {', '.join(sorted(set(thicken)))}: no stud or stirrup layout is "
                "enough: thicken, add a drop panel or a larger column"
            ),
        ]


def _apply_punching(
    entry: dict[str, Any], target: dict[str, Any], file: str, changes: list[dict[str, Any]]
) -> None:
    punching = entry.get("punching")
    if not punching or punching.get("apply") is False or not punching.get("proposed"):
        return
    before = target.get("punchingReinforcement")
    if _normal(before or {}) == _normal(punching["proposed"]):
        return
    target["punchingReinforcement"] = copy.deepcopy(punching["proposed"])
    changes.append(
        _change(
            file,
            entry.get("type") if file.startswith("04") else entry["id"],
            "punching reinforcement",
            _punching_text(before),
            punching.get("text"),
        )
    )


def _foundation_entry(demand: Any, opts: Options) -> dict[str, Any]:
    current = demand.current.model_dump(mode="json", exclude_none=True) if demand.current else None
    reinforcement: dict[str, Any] = {
        "material": demand.material,
        "cover": demand.cover,
    }
    s_max = (
        min(3 * demand.thickness, 450.0)
        if demand.type != "raft"
        else min(2 * demand.thickness, 450.0)
    )
    notes: list[str] = [
        f"spacing ≤ {s_max:.0f} mm (ACI {'7.7.2.3' if demand.type != 'raft' else '8.7.2.2'})"
    ]
    small: list[str] = []
    for face in ("bottom", "top"):
        outer = 0.0
        for direction in ("X", "Y"):
            name = f"{face}{direction}"
            if face == "top" and demand.moments[name].value <= 0:
                continue
            required_of = {}
            for dia in opts.footing_diameters:
                d = (
                    demand.thickness
                    - demand.cover
                    - (dia / 2 if direction == "X" else outer + dia / 2)
                )
                required, _, _, too_small = foundation_layer_need(demand, name, d)
                if too_small:
                    small.append(f"{name}: too thin for the moment")
                    break
                required_of[dia] = required
            if small:
                break
            if face == "top" and max(required_of.values(), default=0.0) <= 0:
                continue
            mesh = B.mesh_for(
                0.0, s_max, opts.footing_diameters, opts.min_slab_spacing, required_of
            )
            if mesh is None:
                small.append(f"{name}: bars closer than {opts.min_slab_spacing:g} mm needed")
                break
            reinforcement[name] = {"dia": mesh.dia, "spacing": mesh.spacing}
            if direction == "X":
                outer = mesh.dia
        if small:
            break
    proposed = None
    if not small:
        proposed = bars_of(reinforcement, _mesh_label(reinforcement))
    status = "ok" if not small else "tooSmall"
    if status == "ok" and current is not None and _mesh_equal(current, reinforcement):
        status = "unchanged"
    return {
        "id": demand.id,
        "type": demand.type,
        "current": bars_of(current, _mesh_label(current)) if current else None,
        "proposed": proposed,
        "status": status,
        "notes": notes,
        "otherFailures": list(demand.failing),
        "tooSmall": None
        if not small
        else {
            "reason": "; ".join(small),
            "suggestion": ("a thicker foundation (try +50 mm steps and run the design again)"),
        },
    }


def _mesh_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(
        (a.get(n) or {}).get("dia") == (b.get(n) or {}).get("dia")
        and (a.get(n) or {}).get("spacing") == (b.get(n) or {}).get("spacing")
        for n in slab_design.LAYERS
    )


# ─────────────────────────────────────── applying ───────────────────────────────────────


def _dump(data: Any, like: str) -> str:
    """JSON in the indentation of the text it replaces (tabs or spaces)."""
    indent: str | int = 2
    for line in like.splitlines()[1:3]:
        stripped = line.lstrip(" \t")
        if line != stripped:
            lead = line[: len(line) - len(stripped)]
            indent = "\t" if lead.startswith("\t") else len(lead)
            break
    text = json.dumps(data, indent=indent, ensure_ascii=False)
    return text + ("\n" if like.endswith("\n") else "")


def _text(bars: Any) -> str | None:
    if bars is None:
        return None
    if isinstance(bars, str):
        return bars
    return bars.get("text")


def _change(file: str, item: str, what: str, before: str | None, after: str | None):
    """One change of :func:`apply_proposal`, with its ``message`` for the workbench."""
    if what == "new type":
        message = f"{item}: new type from {before}, {after}"
    elif what == "type":
        message = f"{item}: type {before} → {after} ({file.split('/')[0]})"
    else:
        message = f"{item}: {before or 'no bars'} → {after}"
    return {"file": file, "id": item, "what": what, "from": before, "to": after, "message": message}


def apply_proposal(
    objects_text: str,
    bim_text: str,
    proposal: dict[str, Any],
    floor_plan_text: str | None = None,
    substructure_text: str | None = None,
) -> dict[str, Any]:
    """The part files with ``proposal`` (:func:`design_proposal`) applied, as new texts:
    ``{"objectsText", "bimText", "floorPlanText"?, "substructureText"?, "changes"}``. Pure: it
    reads and writes nothing. Entries with ``"apply": false`` (set by the workbench when the
    engineer unticks one) and those without a proposal (too small) are left out; new types are
    added after the type they come from, their members reassigned in the BIM model (and in the
    floor plan, for members that come from it; the BIM model's stamp of the floor plan follows
    when it was current). When a split-off member stays in its type (its new type or its row
    unticked), the type takes its ``byType`` bars (designed for all its members), not the split's;
    a new type none of whose members moves is not added. ``changes``: ``[{"file", "id", "what", "from",
    "to", "message"}]``. Raises ``ValueError`` when a text is not valid JSON or a type is not there."""
    from saengine.library.bim import source_stamp
    from saengine.library.objects import ObjectLibrary

    objects = json.loads(objects_text)
    bim = json.loads(bim_text)
    plan = json.loads(floor_plan_text) if floor_plan_text is not None else None
    sub = json.loads(substructure_text) if substructure_text is not None else None
    changes: list[dict[str, Any]] = []
    by_id = {o["id"]: o for o in objects.get("objects", [])}

    # Which split-off members really move: a reassignment is made when it and its new type are
    # both applied. A member that stays in its type although the split moved it (its new type or
    # its own row unticked) needs the type's bars for all its members (``byType``), since the
    # split's bars were designed without it.
    new_ids = {
        n.get("type") or n.get("id")
        for n in proposal.get("newTypes", [])
        if n.get("apply") is not False
    }
    moves = [
        m
        for m in proposal.get("reassign", [])
        if m.get("apply") is not False and m["to"] in new_ids
    ]
    moved = {m["member"] for m in moves}
    used = {m["to"] for m in moves}
    kept_back: dict[str, list[str]] = {}
    for move in proposal.get("reassign", []):
        if move["member"] not in moved:
            kept_back.setdefault(move["from"], []).append(move["member"])

    for entry in proposal.get("types", []):
        if entry.get("apply") is False or not entry.get("proposed"):
            continue
        target = by_id.get(entry["type"])
        if target is None:
            raise ValueError(f"object type '{entry['type']}' is not in 04 Objects")
        _apply_punching(entry, target, "04 Objects/objects.json", changes)
        proposed = entry["proposed"]
        if entry.get("family") is not None and "profile" in proposed:
            # Integrator glue: a steel type's proposed section (saengine.design.steel_proposal).
            if entry.get("status") == "unchanged" or target.get("profile") == proposed["profile"]:
                continue
            target["profile"] = proposed["profile"]
            changes.append(
                _change(
                    "04 Objects/objects.json",
                    entry["type"],
                    "section",
                    (entry.get("current") or {}).get("text"),
                    proposed.get("text"),
                )
            )
            continue
        staying = kept_back.get(entry["type"])
        if staying:
            proposed = entry.get("byType")
            if not proposed:
                raise ValueError(
                    f"object type '{entry['type']}': {', '.join(staying)} would stay in it on bars "
                    "designed without them; apply their new type too, or propose by type"
                )
        before = target.get("reinforcement")
        after = reinforcement_of(proposed)
        if before == after:
            continue
        target["reinforcement"] = after
        change = _change(
            "04 Objects/objects.json",
            entry["type"],
            "reinforcement",
            _text(entry.get("current")),
            _text(proposed),
        )
        if staying:
            change["message"] += (
                f" (the bars for all its members: {', '.join(staying)} stay in the type)"
            )
        changes.append(change)

    added: set[str] = set()
    for new in proposal.get("newTypes", []):
        if new.get("apply") is False or (new.get("type") or new.get("id")) not in used:
            continue  # unticked, or none of its members moves
        origin = by_id.get(new["from"])
        if origin is None:
            raise ValueError(f"object type '{new['from']}' is not in 04 Objects")
        new_id = new.get("type") or new.get("id")
        if new_id in by_id:
            raise ValueError(f"object type '{new_id}' exists already")
        clone = copy.deepcopy(origin)
        clone["id"], clone["name"] = new_id, new.get("name") or f"{origin['name']} ({new_id})"
        clone["reinforcement"] = reinforcement_of(new["proposed"])
        clone.pop("description", None)
        items = objects["objects"]
        at = items.index(origin) + 1
        while at < len(items) and items[at]["id"] in added:
            at += 1
        items.insert(at, clone)
        by_id[clone["id"]] = clone
        added.add(clone["id"])
        changes.append(
            _change(
                "04 Objects/objects.json", new_id, "new type", new["from"], _text(new["proposed"])
            )
        )

    elements = {e["id"]: e for e in bim.get("elements", [])}
    for member in (bim.get("additions") or {}).get("members", []):
        elements.setdefault(member["id"], member)
    plan_members: dict[str, dict[str, Any]] = {}
    if plan is not None:
        for key in ("columns", "beams", "slabs", "walls", "footings"):
            for item in plan.get(key, []):
                plan_members[item["id"]] = item
    for move in moves:
        element = elements.get(move["member"])
        if element is None:
            raise ValueError(f"member '{move['member']}' is not in 06 BIM")
        element["type"] = move["to"]
        changes.append(_change("06 BIM/bim.json", move["member"], "type", move["from"], move["to"]))
        source = move.get("source") or element.get("source")
        if plan is not None and source and source in plan_members:
            plan_members[source]["type"] = move["to"]
            changes.append(
                _change("05 Floor Plan/floor-plan.json", source, "type", move["from"], move["to"])
            )

    if sub is not None:
        found = {f["id"]: f for f in sub.get("foundations", [])}
        for entry in proposal.get("foundations", []):
            if entry.get("apply") is False or not entry.get("proposed"):
                continue
            target = found.get(entry["id"])
            if target is None:
                continue
            _apply_punching(entry, target, "09 Substructure/substructure.json", changes)
            after = reinforcement_of(entry["proposed"])
            if target.get("reinforcement") == after:
                continue
            target["reinforcement"] = after
            changes.append(
                _change(
                    "09 Substructure/substructure.json",
                    entry["id"],
                    "reinforcement",
                    _text(entry.get("current")),
                    _text(entry["proposed"]),
                )
            )

    ObjectLibrary.model_validate(objects)  # the result must still be a valid library
    result: dict[str, Any] = {
        "objectsText": _dump(objects, objects_text),
        "bimText": _dump(bim, bim_text),
        "changes": changes,
    }
    if plan is not None and floor_plan_text is not None:
        result["floorPlanText"] = _dump(plan, floor_plan_text)
        # The BIM model was built from the floor plan as it was: it stays current with the new
        # floor plan (the same members, the same types), so its stamp follows.
        stamps = bim.get("source") or {}
        new_stamp = source_stamp(result["floorPlanText"])
        if stamps.get("floorPlan") == source_stamp(floor_plan_text) and new_stamp != stamps.get(
            "floorPlan"
        ):
            stamps["floorPlan"] = new_stamp
            result["bimText"] = _dump(bim, bim_text)
    if sub is not None and substructure_text is not None:
        result["substructureText"] = _dump(sub, substructure_text)
    return result


__all__ = ["apply_proposal", "design_proposal"]
