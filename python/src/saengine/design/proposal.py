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
  and the ρ that one-way shear needs (the slab has no shear bars). At a free floor edge (no
  edge beam) whose diaphragm chord (:mod:`saengine.design.diaphragms`) the proposed mesh within
  the edge strip does not carry, the slab type gets ``chordBars`` along its free edges for the
  shortfall (in its reinforcement, so apply_proposal, the checks and the drawings and BOQ read
  them from 04 Objects; owner decision 2026-11-02, "Both").
- Foundations are not proposed here: 9 Substructure designs them (its Size Footings gives their
  size and bars). One feature lives in one part only.

When no practical bars make a section work (εt, the shear limit of ACI 22.5.1.2, ρ above 0.08,
a slab too thin for one-way shear without shear bars), the type is reported ``tooSmall`` with
the next practical section as information (depth in 50 mm steps for beams, both sides in
50 mm steps for columns, thickness in 25 mm steps for slabs); nothing is changed for it.

Joints of special moment frames (default pack BNBC 2020 Part 6 Sec 8.3.7): the joint shear Vj comes from
1.25 fy of the beam bars framing in, less the column shear, against φ γ √f'c Aj, which bars
cannot raise. Every joint the checks check is checked with the proposed beam bars (the checks'
own :func:`saengine.design.ductile_joints.joint_checks`); where one fails, the beam types
framing in get the lightest bars that still pass their own checks when fewer joints fail with
them, and the column types below the joints still failing are reported ``tooSmall`` ("joint
shear at ...") with the next practical size (both sides in 50 mm steps).

:func:`apply_proposal` is pure: it takes the texts of the part files and returns new texts, so
the workbench applies the proposal as one undoable edit.
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.design import bars as B
from saengine.design import slab as slab_design
from saengine.design.clauses import clause
from saengine.design.rc import (
    DesignError,
    bar_area,
    flexure,
    section_of,
    shear,
    with_top_drop,
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
from saengine.rpc import jobs as rpc_jobs

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
    #: A column's layout (:attr:`ColumnSearch.layouts`), to move up from.
    index: int | None = None


# ─────────────────────────────────────── beams ───────────────────────────────────────


@dataclass(frozen=True)
class BeamLoads:
    sag: float  # N·mm
    hog: float
    shear: float  # N
    #: Torsion (saengine.design.torsion, the default pack's BNBC 2020 Part 6 Sec 6.4.4): At/s per leg of the closed
    #: stirrups [mm²/mm], the longitudinal Al [mm²] and the stirrups' largest spacing [mm].
    at_s: float = 0.0
    al: float = 0.0
    torsion_s_max: float = math.inf

    def envelope(self, other: BeamLoads) -> BeamLoads:
        return BeamLoads(
            max(self.sag, other.sag),
            max(self.hog, other.hog),
            max(self.shear, other.shear),
            max(self.at_s, other.at_s),
            max(self.al, other.al),
            min(self.torsion_s_max, other.torsion_s_max),
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
        self,
        obj: Beam,
        fc: float,
        fy: float,
        es: float,
        aggregate: float | None,
        options: Options,
        top_drop: float = 0.0,
    ) -> None:
        """``top_drop``: how much lower its top bars pass the joints where they go in the
        second layer (T33, :func:`saengine.design.rc_detailing.joint_top_layers`) [mm]."""
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
        self.top_drop = top_drop
        #: OI-1 of walk 3: where the type's bars must fit (:class:`BarRoom`), or None.
        self.anchorage: BarRoom | None = None
        self._cache: dict[str, tuple[Any, Any, Any, Any]] = {}

    def hooked_need(self, db: float, special: bool) -> float:
        """ldh [mm] of a 90° hooked bar of ``db``: in a special moment frame's joint
        (:func:`saengine.design.ductile_joints.hooked_anchorage_seismic`), else a standard
        hook in tension (:func:`saengine.design.ductile_joints.hooked_development`)."""
        from saengine.design import ductile_joints as dj

        if special:
            return dj.hooked_anchorage_seismic(db, self.fy, self.fc)
        return dj.hooked_development(db, self.fy, self.fc)

    def diameters(self) -> tuple[tuple[float, ...], str | None]:
        """The bar sizes the top and bottom bars may take: those whose hooks fit the room in
        the columns the type's members end in (OI-1 of walk 3: Ø25 bars hooking into 400 mm
        columns, 396 mm needed, 348 mm there), and a note when that leaves some out."""
        from saengine.design import ductile_joints as dj

        sizes = tuple(self.options.diameters)
        room = self.anchorage
        if room is None:
            return sizes, None
        ratio = dj.through_bar_ratio()

        def hooks(d: float) -> bool:
            return self.hooked_need(d, room.special) <= room.end + 1e-6

        def passes(d: float) -> bool:
            return ratio * d <= room.through + 1e-6

        fit = tuple(d for d in sizes if hooks(d) and passes(d))
        if fit == sizes:
            return sizes, None
        if not fit:
            smallest = min(sizes, default=0.0)
            if not hooks(smallest):
                why = (
                    f"Ø{smallest:g} needs ldh = {self.hooked_need(smallest, room.special):.0f} "
                    f"mm, {room.end:.0f} mm in {room.end_at}"
                )
            else:
                why = f"Ø{smallest:g} needs {ratio} db through {room.through_at}"
            return sizes, f"no bar size fits: {why}; use headed bars or a larger column"
        parts = []
        if any(not hooks(d) for d in sizes):
            first = min(d for d in sizes if not hooks(d))
            parts.append(
                f"their 90° hooks fit the {room.end:.0f} mm in {room.end_at} (ldh of "
                f"Ø{first:g} = {self.hooked_need(first, room.special):.0f} mm)"
            )
        if any(not passes(d) for d in sizes):
            parts.append(
                f"the column depth {room.through:.0f} mm they pass through in {room.through_at} "
                f"is at least {ratio} db (Sec 8.3.7.1(d))"
            )
        return fit, f"bars at most Ø{max(fit):g}: " + "; ".join(parts)

    def geometry(self, h: float, stirrup: float) -> BeamGeometry:
        d = h - self.cover - stirrup - 10.0  # one row of Ø20 assumed
        return BeamGeometry(self.b, h, d, d - self.top_drop, self.fc, self.fy, self.es, self.fy)

    def _analyse(self, reinforcement: dict[str, Any]):
        key = json.dumps(reinforcement, sort_keys=True)
        if key not in self._cache:
            section = with_top_drop(
                section_of(
                    self.obj.profile,
                    LinearReinforcement.model_validate(reinforcement),
                    self.fc,
                    self.fy,
                    self.es,
                    self.aggregate,
                ),
                self.top_drop,
            )
            t = reinforcement["transverse"]
            self._cache[key] = (
                section,
                flexure(section, False),
                flexure(section, True),
                shear(section, t["dia"], t["legs"], t["spacing"]),
            )
        return self._cache[key]

    def section(self, reinforcement: dict[str, Any]) -> Any:
        """The section of ``reinforcement`` (the same object for the same bars)."""
        return self._analyse(reinforcement)[0]

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
        if loads.at_s > 0:
            # Sec 6.4.4.6.1-2 with the proposed stirrups and the top bars where they run: the
            # spacing within ph / 8 and 300 mm, a longitudinal bar in each corner.
            t = reinforcement["transverse"]
            if t["spacing"] > self._torsion_s_max(t["dia"]) + 1e-6:
                return None
            if not self._corners_held(reinforcement):
                return None
        need = B.beam_shear_need(loads.shear, self.b, resistance.d, self.fc, self.fy)
        if reinforcement["transverse"]["spacing"] > need.s_max + 1e-6:
            return None
        result["shear"] = loads.shear / resistance.phi_vn
        return result

    def _torsion_s_max(self, dia: float) -> float:
        """The largest spacing of closed stirrups of ``dia`` for torsion (the pack's ph / 8
        and 300 mm, Sec 6.4.4.6.1), ph of this beam's cage with its top drop. The drop is the
        crossing beams' top bar diameter, which the proposal may enlarge: the largest bar
        offered is taken, so the spacing still holds once their bars are applied."""
        from saengine.design import torsion as torsion_design

        rules = torsion_design.TorsionRules.from_pack()
        drop = self.top_drop
        if drop > 0:
            drop = max(drop, max(self.options.diameters, default=drop))
        cage = torsion_design.TorsionSection(self.b, self.h, self.cover, dia, 0.0, top_drop=drop)
        try:
            return min(cage.ph / rules.perimeter_divisor, rules.spacing_max)
        except ValueError:
            return 0.0

    def _corners_held(self, reinforcement: dict[str, Any]) -> bool:
        """Whether a longitudinal bar sits in each corner of the closed stirrups (the torsion
        detailing, :func:`saengine.design.torsion.perimeter_bars`), the top bars at the level
        they pass the joints."""
        from saengine.design import torsion as torsion_design

        section = self.section(reinforcement)
        try:
            ts = torsion_design.TorsionSection.of(section, self.cover, top_drop=self.top_drop)
            return torsion_design.perimeter_bars(section.bars, ts)[1] == 4
        except (DesignError, ValueError):
            return False

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

    def propose(self, loads: BeamLoads, lightest: bool = False) -> Pick:
        """The bars for ``loads``; ``lightest``: the least top and bottom steel rather than the
        best ranked (fewer bars and rows), for the joint shear (see :func:`_joint_shear`)."""
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
            stirrups = self._choose_stirrups(shear_need, loads)
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
        # Torsion: Al on top of the flexural bars, half at each face (Sec 6.4.4.3.8); the side
        # bars of Sec 6.4.4.6.2 are added by reinforcement().
        al_face = loads.al / 2
        scale = 1.0
        sizes, anchorage_note = self.diameters()
        for _ in range(8):
            bottoms = B.face_options(
                (need.bottom + al_face) * scale, self.b, inset, sizes, self.aggregate
            )[:5]
            tops = B.face_options(
                (need.top + al_face) * scale, self.b, inset, sizes, self.aggregate
            )[:5]
            combos = [
                (top, bottom)
                for top, bottom in itertools.product(tops, bottoms)
                if len({top.dia, bottom.dia}) <= opts.max_sizes
            ]
            if lightest:
                combos.sort(
                    key=lambda tb: (round(tb[0].area + tb[1].area, 1), tb[0].score + tb[1].score)
                )
            else:
                combos.sort(
                    key=lambda tb: (
                        round(tb[0].score + tb[1].score, 1),
                        len({tb[0].dia, tb[1].dia}),
                    )
                )
            for top, bottom in combos:
                for option in self._stirrup_options(stirrups, loads, top, bottom):
                    reinforcement = self.reinforcement(top, bottom, option, loads)
                    utilisation = self.verify(reinforcement, loads)
                    if utilisation is not None:
                        notes = [anchorage_note] if anchorage_note else []
                        if bottom.rows > 1 or top.rows > 1:
                            from saengine.design.clauses import text as clause_text

                            rows_at = (
                                clause("required", "barRows")
                                if clause_text("required", "barRows")
                                else "ACI 25.2.2"
                            )
                            notes.append(f"bars in 2 rows, 25 mm clear between them ({rows_at})")
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
        probe = self.reinforcement(top, bottom, first, loads)
        section = self._analyse(probe)[0]
        try:
            d = section.effective_depth(top=False)
        except DesignError:
            return
        need = B.beam_shear_need(loads.shear, self.b, d, self.fc, self.fy)
        again = self._choose_stirrups(need, loads)
        if again is not None and again != first:
            yield again

    def _choose_stirrups(self, need: B.ShearNeed, loads: BeamLoads) -> B.Stirrups | None:
        """The stirrups for the shear and, with torsion, closed stirrups whose outer legs carry
        At/s each on top of their share of Av/s (two legs: the inner legs of four would not
        count for torsion), at most at the torsion spacing (Sec 6.4.4.3.8, 6.4.4.6.1)."""
        opts = self.options
        if loads.at_s <= 0:
            return B.choose_stirrups(need, self.b, opts.stirrup_diameters, opts.min_stirrup_spacing)
        largest = max(opts.stirrup_diameters, default=10.0)
        torsion_need = dataclasses.replace(
            need,
            av_s=need.av_s + 2 * loads.at_s,
            s_max=min(need.s_max, loads.torsion_s_max, self._torsion_s_max(largest)),
        )
        # Two legs only: below 300 mm width choose_stirrups tries two legs alone.
        return B.choose_stirrups(
            torsion_need, min(self.b, 299.0), opts.stirrup_diameters, opts.min_stirrup_spacing
        )

    def reinforcement(
        self,
        top: B.FaceBars,
        bottom: B.FaceBars,
        stirrups: B.Stirrups,
        loads: BeamLoads | None = None,
    ):
        sides = self.sides
        if loads is not None and loads.at_s > 0 and not sides:
            # Sec 6.4.4.6.2: longitudinal torsion bars at most 300 mm apart around the
            # perimeter, at least 0.042 s and 10 mm: side bars on each face when deep.
            inside = self.h - 2 * (self.cover + stirrups.dia)
            per_face = max(0, math.ceil(inside / 300.0) - 1)
            least = max(0.042 * stirrups.spacing, 10.0)
            dia = next((d for d in sorted(self.options.diameters) if d >= least), 12.0)
            if per_face:
                sides = [{"position": "sides", "count": 2 * per_face, "dia": dia}]
        skin = None if self.sides else self._skin_bars(top, bottom, stirrups)
        if skin is not None and (not sides or self._per_face(sides) < skin["count"] // 2):
            # FD-7 of walk 3: a beam deeper than the pack's limit gets the side (skin) bars
            # its skin check asks for (rc_detailing.skin_check), not only torsion's.
            dia = max([skin["dia"], *(g["dia"] for g in sides)])
            sides = [{**skin, "dia": dia}]
        return {
            "material": self.material,
            "cover": self.cover,
            "longitudinal": [
                {"position": "top", "count": top.count, "dia": top.dia},
                {"position": "bottom", "count": bottom.count, "dia": bottom.dia},
                *sides,
            ],
            "transverse": {
                "type": self.kind,
                "dia": stirrups.dia,
                "spacing": stirrups.spacing,
                "legs": stirrups.legs,
            },
        }

    @staticmethod
    def _per_face(sides: list[dict[str, Any]]) -> int:
        return sum(int(g["count"]) for g in sides) // 2

    def _skin_bars(
        self, top: B.FaceBars, bottom: B.FaceBars, stirrups: B.Stirrups
    ) -> dict[str, Any] | None:
        """The side bars of a beam deeper than the pack's skin limit
        (:func:`saengine.design.rc_detailing.skin_check`): on each side face between the top and
        bottom rows, evenly spaced at most the crack control spacing with cc the cover and
        stirrup to the side face; None for a shallower beam or a pack without the rule."""
        from saengine.design import rc_detailing as RD

        rule = getattr(RD._detailing(), "skin", None)
        if rule is None or self.h <= rule.depthOver:
            return None
        cc = self.cover + stirrups.dia
        limit = RD.crack_spacing_limit(RD.service_stress(self.fy), cc)
        if not limit or limit <= 0:
            return None
        gap = self.h - 2 * cc - (top.dia + bottom.dia) / 2
        per_face = max(0, math.ceil(gap / limit - 1e-9) - 1)
        if not per_face:
            return None
        dia = next((d for d in sorted(self.options.diameters) if d >= 10.0), 12.0)
        return {"position": "sides", "count": 2 * per_face, "dia": dia}


def _beam_loads(member: dict[str, Any], combinations: list[str]) -> BeamLoads:
    demand = beam_demand(member, combinations)
    torsion = member.get("torsion")
    return BeamLoads(
        demand.overall("sag").value,
        demand.overall("hog").value,
        demand.overall("shear").value,
        torsion.at_s if torsion is not None else 0.0,
        torsion.al if torsion is not None else 0.0,
        torsion.s_max if torsion is not None else math.inf,
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
                f"no layout with ρ up to {B.column_rho()[1]:g} (ACI 10.6.1.1) carries the demand"
                if search.layouts
                else "no bar layout fits the section at the least clear spacing (ACI 25.2.3)"
            ),
            suggestion=_bigger_column(search, points),
        )
    if confirm:
        confirmed = search.confirm(index, points)
        if confirmed is None:
            return _column_pick(search, None, points)
        index = _fewer_bars(search, confirmed, points)
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
    return Pick(
        reinforcement, _column_label(reinforcement), layout.area, utilisation, notes, index=index
    )


#: Steel a column layout with fewer, larger bars may add over the lightest one (a share).
FEWER_BARS_MARGIN = 0.10


def _fewer_bars(search: ColumnSearch, index: int, points: list[Point]) -> int:
    """The layout with the fewest bars within :data:`FEWER_BARS_MARGIN` more steel than
    ``index`` that the full surface accepts (``index`` itself when none has fewer): the lightest
    layout of small bars (56Ø16 in a 1050 mm column) is harder to place, tie and concrete than
    one of larger bars (24Ø25) for a few per cent more steel."""
    best = index
    limit = search.layouts[index].area * (1 + FEWER_BARS_MARGIN)
    for k in range(index + 1, len(search.layouts)):
        layout = search.layouts[k]
        if layout.area > limit + 1e-6:
            break
        if layout.count < search.layouts[best].count and search.carries(k, points, coarse=False):
            best = k
    return best


def _ties_hold(pick: Pick, obj: Any, members: list[dict[str, Any]], opts: Options) -> bool:
    """Whether the seismic ties of the default pack's BNBC Sec 8.3 can be made for ``pick`` (no tie legs beyond
    the bars of a face, hx ≤ 350 mm, the hoop spacing at least the least spacing; see
    :func:`seismic_transverse`)."""
    if pick.reinforcement is None or not _seismic_members(members):
        return True
    first = members[0]
    try:
        _, info = seismic_transverse(
            "column",
            obj,
            copy.deepcopy(pick.reinforcement),
            members,
            first["fc"],
            first["fy"],
            first["es"],
            first["aggregate"],
            opts,
        )
    except DesignError:
        return True  # reported by _with_seismic
    return info is None or info.get("detailable", True)


def _detailed_column_pick(
    search: ColumnSearch,
    index: int | None,
    points: list[Point],
    members: list[dict[str, Any]],
    opts: Options,
) -> Pick:
    """:func:`_column_pick`, moved up to the next layout with more bars on its faces while the
    seismic ties cannot hold the bars (4Ø32 in a 550 mm column leaves 418 mm between the
    corner bars, above hx = 350 mm, and a crosstie needs a bar to hold, Sec 8.3.5.4(a)(iii),
    (c)). None of them: too small, with the next practical size."""
    pick = _column_pick(search, index, points)
    tries = 0
    while not _ties_hold(pick, search.obj, members, opts):
        assert pick.index is not None
        count = search.layouts[pick.index].count
        following = next(
            (
                k
                for k in range(pick.index + 1, len(search.layouts))
                if search.layouts[k].count > count and search.carries(k, points)
            ),
            None,
        )
        tries += 1
        if following is None or tries > 12:
            return Pick(
                None,
                "",
                0.0,
                too_small=(
                    "no bar layout lets the ties hold every corner and alternate bar with hx ≤ "
                    "350 mm and the hoops at the least spacing (Sec 8.3.5.4)"
                ),
                suggestion=_bigger_column(search, points),
            )
        pick = _column_pick(search, following, points, confirm=False)
        pick.utilisation["axialBending"] = search.utilisation(following, points, coarse=False)
    return pick


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
            if trial.carries(index, points):
                size = f"Ø{trial.b:g}" if trial.shape == "circle" else f"{trial.b:g} x {trial.h:g}"
                return (
                    f"try {size} mm (+{grow:g} mm) with about ρ = 0.025; the analysis must be "
                    "run again"
                )
        grow += step
    return f"no size up to +{GROWTH['column']:g} mm works: a higher concrete grade or more columns"


# ─────────────────────────────────── beam-column joints ───────────────────────────────────


@dataclass
class _JointCase:
    """A joint the checks found joint shear at (special moment frames, the default pack's BNBC Sec 8.3.7), as
    :func:`saengine.design.ductile_joints.joint_checks` takes it: its beams' ``type`` is the
    beam member's id, so every beam can carry bars of its own."""

    joint: Any  # ductile_joints.FrameJoint
    below: Any  # ductile_joints.JointColumn
    above: Any
    profile: Any  # the column below's
    column_type: str
    above_type: str | None = None
    #: The checks' strong column / weak beam row is required there (not flagged, 8.3.5.2(a)).
    strong_required: bool = False


def _anchorage_rooms(gathered: Any) -> dict[str, tuple[float, str]]:
    """Per beam that ends in a column (no beam beyond it on the column's axis): the least room
    [mm] for its hooked bars there, the column's dimension along the beam less its cover and
    tie (to the far face of the confined core, as the joint checks and the drawings take it),
    and the column. OI-1 of walk 3."""
    import numpy as np

    from saengine.design import ductile_joints as dj

    types = {o.id: o for o in getattr(getattr(gathered, "objects", None), "objects", [])}
    try:
        joints = dj.frame_joints(gathered.building, types)
    except (DesignError, ValueError, AttributeError, TypeError):
        return {}
    by_id = {e.id: e for e in gathered.building.elements}
    out: dict[str, tuple[float, str]] = {}
    for joint in joints:
        column = by_id.get(joint.below)
        obj = types.get(getattr(column, "type", None))
        profile = getattr(obj, "profile", None)
        if column is None or profile is None:
            continue
        reinforcement = getattr(obj, "reinforcement", None)
        cover = float(getattr(reinforcement, "cover", 40.0) or 40.0)
        tie = getattr(reinforcement, "transverse", None)
        tie_dia = float(getattr(tie, "dia", 10.0) or 10.0)
        rotation = float(getattr(column, "rotation", 0.0) or 0.0)
        ex, ey = dj.column_axes(rotation)
        sides: dict[tuple[int, int], list[Any]] = {}
        for beam in joint.beams:
            u = np.asarray(beam.direction, dtype=float)
            ux, uy = float(u @ ex), float(u @ ey)
            axis = 0 if abs(ux) >= abs(uy) else 1
            sign = 1 if (ux if axis == 0 else uy) > 0 else -1
            sides.setdefault((axis, sign), []).append(beam)
        for (axis, sign), framing in sides.items():
            try:
                frame = dj.column_frame(profile, rotation, ex if axis == 0 else ey)
            except DesignError:
                continue
            if (axis, -sign) in sides:
                # The bars run through the joint: a special frame's column depth >= 20 db
                # (ductile_joints.joint_checks, Sec 8.3.7.1(d)), kept as "through:<id>".
                for beam in framing:
                    key = f"through:{beam.id}"
                    if key not in out or frame.along < out[key][0]:
                        out[key] = (frame.along, column.id)
                continue
            room = frame.along - cover - tie_dia
            for beam in framing:
                if beam.id not in out or room < out[beam.id][0]:
                    out[beam.id] = (room, column.id)
    return out


def _bar_rooms(gathered: Any) -> dict[str, Any]:
    """The rooms the drawings' anchorage checks measure for the columns on foundations and the
    slabs' edge supports (:func:`saengine.drawings.detailing.anchorage_rooms`, with 9
    Substructure's foundations when there are); empty when they cannot be found."""
    from saengine.drawings.detailing import anchorage_rooms

    empty: dict[str, Any] = {"columns": {}, "slabs": {}}
    root = getattr(gathered, "root", None)
    text = None
    if root is not None:
        path = Path(root) / "09 Substructure" / "substructure.json"
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else None
        except OSError:
            text = None
    try:
        return anchorage_rooms(
            gathered.building, gathered.objects, gathered.materials, gathered.settings, text
        )
    except (DesignError, ValueError, AttributeError, TypeError, ArithmeticError):
        return empty


def _column_short(
    entry: dict[str, Any] | None, rooms: dict[str, Any], gathered: Any, opts: Options
) -> tuple[float, list[tuple[Any, ...]], list[float]] | None:
    """The proposed column bars of ``entry`` that do not anchor in a foundation (R2-8, as the
    drawings check it: ldh <= the foundation's thickness less its cover and two mesh bars):
    ``(largest bar, [(shortfall, member, room, ldh, available, fy)], the smaller column bar
    sizes that anchor in every such foundation)``; None when they all anchor."""
    from saengine.design import ductile_joints as dj

    found = rooms.get("columns") or {}
    proposed = (entry or {}).get("proposed") if (entry or {}).get("kind") == "column" else None
    groups = (proposed or {}).get("longitudinal") or []
    if not found or not groups or entry is None:
        return None
    fy_of = {
        m["id"]: float(m["fy"])
        for m in gathered.collect.get("members", [])
        if m.get("kind") == "column" and m.get("fy")
    }
    db = max(float(g["dia"]) for g in groups)
    short = []
    for member in entry.get("members", []):
        room = found.get(member)
        if room is None:
            continue
        fy = fy_of.get(member, 420.0)
        need = dj.hooked_development(db, fy, room["fc"])
        available = room["thickness"] - room["cover"] - 2 * room["mesh"]
        if need > available + 1e-6:
            short.append((need - available, member, room, need, available, fy))
    if not short:
        return None
    # The sizes that anchor in every foundation found short (not only the worst one).
    fitting = [
        d
        for d in sorted(opts.column_diameters)
        if d < db and all(dj.hooked_development(d, s[5], s[2]["fc"]) <= s[4] + 1e-6 for s in short)
    ]
    return db, short, fitting


def _column_anchorage(
    types: list[dict[str, Any]], rooms: dict[str, Any], gathered: Any, opts: Options
) -> list[str]:
    """R2-8: the proposed column bars' hooked development into the foundation (as the drawings
    check it, :func:`saengine.design.ductile_joints.column_dowel_checks`: ldh <= the foundation's
    thickness less its cover and two mesh bars). The column's bars carry its forces, so they are
    not made smaller here: a note on the type says how deep the foundation must be (9
    Substructure sizes it) and the largest bar that fits. Returns the warnings."""
    warnings: list[str] = []
    for entry in types:
        found = _column_short(entry, rooms, gathered, opts)
        if found is None:
            continue
        db, short, fitting = found
        _, member, room, need, available, _fy = max(short, key=lambda s: s[0])
        depth = math.ceil((need + room["cover"] + 2 * room["mesh"]) / 25.0) * 25.0
        others = ", ".join(sorted(s[1] for s in short if s[1] != member))
        note = (
            f"column bars Ø{db:g} into the foundation: {member} needs ldh {need:.0f} mm in "
            f"{room['foundation']}, {available:.0f} mm there (thickness less cover and two mesh "
            f"bars){f'; also short at {others}' if others else ''}: deepen "
            f"{room['foundation']} to at least {depth:.0f} mm in 9 Substructure"
            + (f", or use bars of at most Ø{max(fitting):g}" if fitting else "")
        )
        entry["notes"] = [*entry.get("notes", []), note]
        warnings.append(f"{entry['type']}: {note}")
    return warnings


def _type_anchorage(
    members: list[dict[str, Any]], rooms: dict[str, tuple[float, str]]
) -> tuple[float, bool, str] | None:
    """The least anchorage room of a beam type's members (:func:`_anchorage_rooms`), whether
    a special moment frame's hooked anchorage applies there, and the column."""
    special = any(
        c.get("level") == "special" and c.get("lateral") for c in _seismic_members(members)
    )
    found = [(rooms[m["id"]], m) for m in members if m["id"] in rooms]
    through = [(rooms[f"through:{m['id']}"], m) for m in members if f"through:{m['id']}" in rooms]
    end = min(found, key=lambda f: f[0][0]) if found else None
    passing = min(through, key=lambda f: f[0][0]) if through and special else None
    if end is None and passing is None:
        return None
    return BarRoom(
        end[0][0] if end else math.inf,
        special,
        f"column {end[0][1]} (at {end[1]['id']})" if end else "",
        passing[0][0] if passing else math.inf,
        f"column {passing[0][1]} (at {passing[1]['id']})" if passing else "",
    )


@dataclass(frozen=True)
class BarRoom:
    """Where a beam type's bars must fit (OI-1 of walk 3): the least room [mm] for a hooked
    bar where a member ends in a column, and the least column depth the bars pass through in a
    special frame's joint (``inf``: none), with the columns."""

    end: float
    special: bool
    end_at: str
    through: float = math.inf
    through_at: str = ""


def _joint_cases(gathered: Gathered) -> list[_JointCase]:
    """The joints of the checks with a joint shear row, with their columns as the checks take
    them (:mod:`saengine.design.seismic_detailing`; the axial forces do not enter joint shear)."""
    from saengine.design import ductile_joints as dj

    # The joint rows are named as the members' detailing rows ("Detailing: Joint shear, ...").
    rows = {j["id"]: j for j in gathered.collect.get("joints", [])}
    checked = {
        joint_id
        for joint_id, j in rows.items()
        if any("Joint shear, " in r["name"] for r in j.get("checks", []))
    }
    if not checked:
        return []
    columns = {m["id"]: m for m in gathered.collect.get("members", []) if m["kind"] == "column"}

    def column(member: dict[str, Any], axial: Any) -> Any:
        reinforcement = member["object"].reinforcement
        tie = reinforcement.transverse if reinforcement else None
        pmin, pmax = axial or (0.0, 0.0)
        return dj.JointColumn(
            member["section"],
            float(getattr(member.get("element"), "rotation", 0.0) or 0.0),
            float(pmin),
            float(pmax),
            reinforcement.cover if reinforcement else 40.0,
            tie.dia if tie else 10.0,
        )

    types = {o.id: o for o in gathered.objects.objects}
    cases = []
    try:
        joints = dj.frame_joints(gathered.building, types)
    except (DesignError, ValueError, AttributeError):
        return []  # the checks found none either (seismic_detailing.apply)
    for joint in joints:
        below = columns.get(joint.below)
        if joint.id not in checked or below is None:
            continue
        above = columns.get(joint.above) if joint.above else None
        row = rows[joint.id]
        axial = row.get("axial") or {}
        cases.append(
            _JointCase(
                dataclasses.replace(
                    joint, beams=[dataclasses.replace(b, type=b.id) for b in joint.beams]
                ),
                column(below, axial.get("below")),
                column(above, axial.get("above")) if above is not None else None,
                below["object"].profile,
                below["type"],
                above["type"] if above is not None else None,
                any(
                    "Strong column / weak beam" in r["name"] and not r.get("flag")
                    for r in row.get("checks", [])
                ),
            )
        )
    return cases


def _joint_fails(case: _JointCase, sections: dict[str, Any], profile: Any = None) -> bool:
    """Whether the joint shear of the checks (:func:`ductile_joints.joint_checks`) fails with
    the beam sections ``sections`` (by beam member id) and the column ``profile`` (default the
    column's own)."""
    from saengine.design import ductile_joints as dj

    beams = {b.id: sections[b.id] for b in case.joint.beams if b.id in sections}
    if not beams:
        return False
    try:
        rows, _ = dj.joint_checks(
            case.joint, beams, case.below, case.above, profile or case.profile
        )
    except DesignError:
        return False
    return any(r["name"].startswith("Joint shear") and not r["ok"] for r in rows)


def _joint_shear(cases: list[_JointCase], sections: dict[str, Any]) -> dict[str, list[str]]:
    """The joints whose shear fails with ``sections`` (by beam member id), by the column type
    below them."""
    failing: dict[str, list[str]] = {}
    for case in cases:
        if _joint_fails(case, sections):
            failing.setdefault(case.column_type, []).append(case.joint.id)
    return failing


def _joint_column_size(cases: list[_JointCase], sections: dict[str, Any]) -> str:
    """The next practical column size (both sides +50 mm) at which every joint of ``cases``
    (those of one column type) passes joint shear: Vj does not change, φ γ √f'c Aj grows with
    the joint (γ may fall when the beams no longer cover three quarters of a face)."""
    first = cases[0].profile
    grow = 50.0
    while grow <= GROWTH["column"]:
        if isinstance(first, CircleProfile):
            profile: Any = CircleProfile(radius=first.radius + grow / 2)
            size = f"Ø{2 * profile.radius:g}"
        else:
            profile = RectangleProfile(xDim=first.xDim + grow, yDim=first.yDim + grow)
            size = f"{profile.xDim:g} x {profile.yDim:g}"
        if not any(_joint_fails(case, sections, profile) for case in cases):
            return (
                f"try {size} mm (+{grow:g} mm) for the joint shear; the analysis must be run again"
            )
        grow += 50.0
    return (
        f"no size up to +{GROWTH['column']:g} mm passes the joint shear: a higher concrete "
        "grade, or lighter beam bars from deeper beams"
    )


def _strong_column_fails(
    case: _JointCase, sections: dict[str, Any], below: Any, above: Any
) -> bool:
    """Whether ΣMnc ≥ 1.2 ΣMnb (:func:`ductile_joints.strong_column_checks`) fails at the joint
    with the beam sections ``sections`` (by member id) and the column sections ``below`` and
    ``above`` (None: the checked ones)."""
    from saengine.design import ductile_joints as dj

    beams = {b.id: sections[b.id] for b in case.joint.beams if b.id in sections}
    if not beams:
        return False
    column_below = dataclasses.replace(case.below, section=below or case.below.section)
    column_above = case.above
    if column_above is not None and above is not None:
        column_above = dataclasses.replace(column_above, section=above)
    try:
        rows, _ = dj.strong_column_checks(
            case.joint, beams, column_below, column_above, case.profile
        )
    except DesignError:
        return False
    return any(not r["ok"] and not r["flag"] for r in rows)


#: Layouts the strong column pass may move a column type up by, at most.
STRONG_COLUMN_STEPS = 24


def _strong_column_layouts(
    cases: list[_JointCase],
    sections: dict[str, Any],
    searches: dict[str, ColumnSearch],
    chosen: dict[str, int],
) -> tuple[dict[str, tuple[int, list[str]]], dict[str, list[str]]]:
    """The column types to raise for ΣMnc ≥ 1.2 ΣMnb (Sec 8.3.5.2(b)) at ``cases`` with the beam
    sections ``sections``, from the layouts ``chosen`` (by type, those with bars proposed):
    ``({type: (least layout, joints)}, {type: joints no layout makes pass})``. At a failing
    joint the types below and above move up one layout at a time, together, until it passes."""
    raised: dict[str, tuple[int, list[str]]] = {}
    short: dict[str, list[str]] = {}

    def section(type_id: str | None, index: int | None) -> Any:
        if type_id is None or index is None or type_id not in searches:
            return None
        return searches[type_id].section(index)

    for case in cases:
        below_type, above_type = case.column_type, case.above_type
        if below_type not in chosen:
            continue
        levels = {t: chosen[t] for t in (below_type, above_type) if t in chosen}

        def fails(
            case: _JointCase = case,
            levels: dict[str, int] = levels,
            below_type: str = below_type,
            above_type: str | None = above_type,
        ) -> bool:
            return _strong_column_fails(
                case,
                sections,
                section(below_type, levels.get(below_type)),
                section(above_type, levels.get(above_type)),
            )

        if not fails():
            continue
        passed = False
        for _ in range(STRONG_COLUMN_STEPS):
            moved = False
            for t, index in list(levels.items()):
                if index + 1 < len(searches[t].layouts):
                    levels[t] = index + 1
                    moved = True
            if not moved:
                break
            if not fails():
                passed = True
                break
        if passed:
            for t, index in levels.items():
                if index > chosen[t]:
                    least, joints = raised.get(t, (index, []))
                    raised[t] = (max(least, index), [*joints, case.joint.id])
        else:
            short.setdefault(below_type, []).append(case.joint.id)
    return raised, short


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
    chord = reinforcement.get("chordBars")
    if chord:
        parts.append(f"chord bars {chord['count']}Ø{chord['dia']:g} along the free edges")
    return ", ".join(parts)


def _chord_edges(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The diaphragm chord checks (:func:`saengine.design.diaphragms.diaphragms_of`'s
    ``chord``) by the slab members along their edge."""
    found: dict[str, list[dict[str, Any]]] = {}
    for element in report.get("elements", []):
        if element.get("kind") != "diaphragm":
            continue
        for check in element.get("checks", []):
            chord = check.get("chord")
            if not chord:
                continue
            for slab in chord["slabs"]:
                found.setdefault(slab, []).append({**chord, "story": element.get("story")})
    return found


def _with_chord_bars(
    target: dict[str, Any] | None,
    members: list[str],
    chords: dict[str, list[dict[str, Any]]],
    fy: float,
    diameters: tuple[float, ...],
) -> list[str]:
    """Adds ``chordBars`` to the proposed slab bars ``target`` (:func:`bars_of`) where the
    proposed mesh within the edge strip leaves a free edge's chord force of ``members`` short
    (the lightest of 2 to 4 bars of ``diameters``, else the most of the largest); returns the
    notes."""
    from saengine.design.diaphragms import strip_area

    if target is None or fy <= 0:
        return []
    need = 0.0
    short: list[str] = []
    beams_short: list[str] = []
    for member in members:
        for chord in chords.get(member, []):
            where = f"{chord['story']} {chord['edge']} (force along {chord['axis']})"
            strip = chord["phi"] * fy * strip_area(target, chord["direction"], chord["strip"])
            missing = chord["force_kN"] * 1e3 - chord["beams_kN"] * 1e3 - strip
            if missing <= 0:
                continue
            if not chord["free"]:
                beams_short.append(where)
                continue
            need = max(need, missing / (chord["phi"] * fy))
            short.append(where)
    notes = []
    if beams_short:
        notes.append(
            f"diaphragm chord at {', '.join(sorted(set(beams_short)))}: the edge beams' bars "
            "and the slab's bars in the edge strip fall short; give the edge beams more bars"
        )
    if need <= 0:
        if target.pop("chordBars", None) is not None:
            target["text"] = _mesh_label(target)
        return notes
    sizes = sorted(diameters) or [12.0]
    count, dia = next(
        (
            (max(2, math.ceil(need / bar_area(d) - 1e-9)), d)
            for d in sizes
            if max(2, math.ceil(need / bar_area(d) - 1e-9)) <= 4
        ),
        (max(2, math.ceil(need / bar_area(sizes[-1]) - 1e-9)), sizes[-1]),
    )
    target["chordBars"] = {"count": count, "dia": dia}
    target["text"] = _mesh_label(target)
    notes.append(
        f"diaphragm chord: the slab's bars in the edge strip fall short at "
        f"{', '.join(sorted(set(short)))} (no edge beam): chord bars {count}Ø{dia:g} along the "
        f"free edges, As {need:.0f} mm² for the shortfall"
    )
    return notes


def _thin_slabs(type_id: str, obj: Any, collected: list[dict[str, Any]]) -> str | None:
    """R2-18: the slabs of a type thinner than the least thickness of the code pack's table
    (the checks' "Min. thickness (Table ...)" row, reported beside the strength checks since a
    computed deflection may stand for it): what they need and the thickness to try (in 25 mm
    steps), else None. Bars do not cure it."""
    rows = [
        r
        for c in collected
        for r in c.get("checks", [])
        if str(r.get("name", "")).startswith("Min. thickness") and not r.get("ok", True)
    ]
    if not rows:
        return None
    worst = max(rows, key=lambda r: float(r.get("demand") or 0.0))
    need = float(worst.get("demand") or 0.0)
    given = float(getattr(obj, "thickness", 0.0) or worst.get("capacity") or 0.0)
    members = {c["id"] for c in collected if any(r in rows for r in c.get("checks", []))}
    rule = str(worst["name"]).removeprefix("Min. thickness").strip(" ()") or "the code pack"
    return (
        f"{type_id}: {len(members)} of its {len(collected)} slabs are thinner than the least "
        f"thickness of {rule} (up to {need:.0f} mm needed, {given:.0f} mm given): try "
        f"{math.ceil(need / 25.0 - 1e-9) * 25.0:.0f} mm, or check their deflection by "
        "calculation; bars do not cure it, and the analysis must be run again"
    )


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
        #: The bar sizes the top layers may take (R2-8): those whose hooks develop in the
        #: supports at the slabs' discontinuous edges (:meth:`limit_top_bars`); all by default.
        self.top_sizes: dict[str, tuple[float, ...]] = {}
        self.anchorage_notes: list[str] = []

    def limit_top_bars(self, supports: dict[str, list[tuple[float, float, str | None, str]]]):
        """Limits the top bars to the sizes whose standard hook develops in every edge support
        (``supports``: per direction "X"/"Y" the ``(width, depth, ref, slab)`` of the type's
        members, :func:`saengine.drawings.detailing.anchorage_rooms`), as the drawings check
        them (:func:`saengine.drawings.detailing._edge_anchorage`: ldh <= the support's width
        less the cover where the hook fits in its depth); a note when no size does."""
        from saengine.drawings.detailing import hook_development, standard_hook

        h, cover = float(self.obj.thickness), float(self.cover)
        sizes = tuple(self.options.slab_diameters)

        def short_of(db: float, found: list[tuple[float, float, str | None, str]]):
            """(ldh, room, support, slab) of the first support the hook of ``db`` does not
            develop in, else None."""
            need = hook_development(db, self.fy, self.fc).value
            for width, depth, ref, slab in found:
                if standard_hook(db).leg > max(depth, h) - 2 * cover + 1e-6:
                    continue  # not hooked there: the drawings check a straight length
                if need > width - cover + 1e-6:
                    return need, width - cover, ref, slab
            return None

        for direction, found in supports.items():
            name = f"top{direction}"
            if not found:
                continue
            fitting = tuple(d for d in sizes if short_of(d, found) is None)
            if fitting == sizes:
                continue
            smallest = min(sizes)
            miss = short_of(smallest, found)
            if not fitting:
                assert miss is not None
                need, room, ref, slab = miss
                self.anchorage_notes.append(
                    f"{name} bars hooked into the edge support {ref} of {slab}: even Ø{smallest:g} "
                    f"needs ldh {need:.0f} mm, {room:.0f} mm there (its width less the cover): "
                    f"a wider support (at least {need + cover:.0f} mm), or anchor the bars "
                    "beyond it"
                )
                continue
            self.top_sizes[name] = fitting
            left = [d for d in sizes if d not in fitting]
            self.anchorage_notes.append(
                f"{name} bars at most Ø{max(fitting):g}: the hooks of Ø"
                + ", Ø".join(f"{d:g}" for d in left)
                + " do not develop in the edge supports ("
                + ", ".join(
                    sorted({f"{m[2]} of {m[3]}" for d in left if (m := short_of(d, found))})
                )
                + ")"
            )

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
                sizes = self.top_sizes.get(name) or tuple(self.options.slab_diameters)
                for dia in sizes:
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
                    sizes,
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


@dataclass
class _TypeResult:
    """What the proposal of one type adds: its entry, the types split off it and their
    members' reassignment, warnings."""

    entry: dict[str, Any] | None = None
    new_types: list[dict[str, Any]] = field(default_factory=list)
    reassign: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _some_joints(joint_ids: list[str], shown: int = 3) -> str:
    """Joint ids: "C1@3000" as is; "52 joints: C-A1@3600, C-A4@3600, C-E1@3600 and 49 more" for
    many (N-X21 of usability walk 2: a row with a wall of joint ids)."""
    if len(joint_ids) <= shown + 1:
        return ", ".join(joint_ids)
    rest = len(joint_ids) - shown
    return f"{len(joint_ids)} joints: {', '.join(joint_ids[:shown])} and {rest} more"


def _joint_too_small(found: _TypeResult, joint_ids: list[str], suggestion: str) -> None:
    """Reports a column type too small for the joint shear at ``joint_ids`` (as a section too
    small for bars: nothing is changed for it, its split types are not made); the bars its
    axial forces and moments need stay in a note and under ``"strengthBars"`` (the type's bars
    for all its members), which the engineer may apply anyway (``"applyStrengthBars"``, see
    :func:`apply_proposal`) rather than leave the columns without bars."""
    entry = found.entry
    assert entry is not None
    bars = entry.get("byType") or entry["proposed"]
    entry["status"] = "tooSmall"
    entry["proposed"] = None
    entry["strengthBars"] = bars
    entry["tooSmall"] = {
        "reason": f"joint shear at {_some_joints(joint_ids)}",
        "suggestion": suggestion,
        "joints": list(joint_ids),
    }
    if bars:
        entry["notes"] = [
            *entry["notes"],
            (
                f"bars for its axial forces and moments: {bars['text']}; not proposed, the joints "
                "need a larger column (joint shear φ γ √f'c Aj, Sec 8.3.7.3, does not depend on "
                "the column's bars; the beams' bars give Vj = 1.25 fy As - Vcol, judged on each "
                "beam type's shared bars)"
            ),
        ]
    if "byType" in entry:
        entry["byType"] = None
    found.new_types.clear()
    found.reassign.clear()


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


#: The proposals made last, by (results folder, inputs stamp, options): the page asks again on
#: every open and mode switch (N-X4 of usability walk 2: 5 to 10 minutes each time).
_PROPOSED: dict[tuple[str, str, str], dict[str, Any]] = {}
_PROPOSED_KEPT = 4
_proposed_lock = threading.Lock()
#: The proposals being worked out, by the same key: a second request for the same inputs (the
#: page shown again while the first one runs) waits for it rather than proposing again.
_PROPOSING: dict[tuple[str, str, str], threading.Event] = {}


def design_proposal(
    out_dir: str | Path,
    project_path: str | Path,
    options: dict[str, Any] | None = None,
    gathered: Gathered | None = None,
) -> dict[str, Any]:
    """The proposed bars of every designed object type (:func:`propose`), kept while the run's
    inputs (:func:`saengine.pipeline.design_mode.report_stamp`) and the options do not change;
    with ``gathered`` given, always worked out from it."""
    if gathered is not None:
        return propose(out_dir, project_path, options, gathered)
    from saengine.pipeline.design_mode import gathered as kept_gathering
    from saengine.pipeline.design_mode import report_stamp

    stamp = report_stamp(out_dir, project_path)
    key = (str(Path(out_dir).resolve()), stamp, json.dumps(options or {}, sort_keys=True))
    while True:
        with _proposed_lock:
            found = _PROPOSED.get(key)
            running = _PROPOSING.get(key) if found is None else None
            if found is None and running is None:
                running = _PROPOSING[key] = threading.Event()
                mine = True
            else:
                mine = False
        if found is not None:
            return copy.deepcopy(found)
        if mine:
            break
        assert running is not None
        running.wait()  # then kept (or failed: worked out here)
    try:
        # The checks the design view, Run All and the required steel already made for these
        # inputs, else made once for all of them (saengine.pipeline.design_mode).
        from saengine.pipeline.design_mode import recording

        with recording(out_dir):
            result = propose(
                out_dir,
                project_path,
                options,
                kept_gathering(out_dir, project_path, stamp, substructure=False),
            )
        with _proposed_lock:
            while len(_PROPOSED) >= _PROPOSED_KEPT:
                _PROPOSED.pop(next(iter(_PROPOSED)))
            _PROPOSED[key] = copy.deepcopy(result)
    finally:
        with _proposed_lock:
            _PROPOSING.pop(key, None)
        running.set()
    return result


def propose(
    out_dir: str | Path,
    project_path: str | Path,
    options: dict[str, Any] | None = None,
    gathered: Gathered | None = None,
) -> dict[str, Any]:
    """The proposed bars of every designed object type (see the module notes).

    ``options``: ``mode`` "byType" (default) or "splitTypes", ``diameters``,
    ``stirrupDiameters``, ``maxSizes`` (bar sizes per beam, 2), ``overDesign`` (0.25: members
    whose own bars would be 25 % lighter are listed), ``maxNewTypes`` (3 per type).

    Returns ``{"mode", "types": [{"type", "kind", "name", "current", "proposed", "status"
    ("ok", "unchanged", "tooSmall"), "governingMember", "members", "demand", "utilisation",
    "overDesigned" (member ids), "overDesignedDetails" ([{"member", "own", "overDesign"}]),
    "tooSmall" ({"reason", "suggestion"} or None), "notes", "byType" (splitTypes only: the
    single-type proposal), "strengthBars" (a column type too small for its joints' shear: the
    bars its strength needs)}], "newTypes": [{"type", "from", "kind", "name", "proposed",
    "members", "governingMember", "utilisation"}], "reassign": [{"member", "from", "to",
    "source"}], "foundations": [] (kept for older callers: 9 Substructure designs the
    foundations), "warnings", "notes"}``; ``current``/``proposed`` are the reinforcement in the
    shape of 04 Objects with its description under ``"text"`` (:func:`bars_of`), or None.

    ``gathered``: the checks to propose from; by default those
    :func:`saengine.pipeline.design_mode.gathered` keeps for the run's inputs (made once and
    shared with the design view, Run All and the required steel).
    """
    raw = options or {}
    mode = raw.get("mode", "byType")
    if mode not in ("byType", "splitTypes"):
        raise ValueError(f"unknown mode '{mode}' (byType or splitTypes)")
    opts = Options.of(raw)
    if gathered is None:
        # The checks the design view, Run All and the required steel already made for these
        # inputs, else made once for all of them (saengine.pipeline.design_mode).
        from saengine.pipeline.design_mode import gathered as kept_gathering

        gathered = kept_gathering(out_dir, project_path, substructure=False)
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
    chords = _chord_edges(getattr(gathered, "report", None) or {})
    beam_designers: dict[str, BeamDesigner] = {}

    def split(
        type_id: str,
        kind: str,
        name: str,
        label_of,
        pick: Pick,
        members: list[MemberPick],
        propose_for,
        found: _TypeResult,
        lightest: bool = False,
    ) -> Pick:
        """Splits off the over-designed members (into ``found``); returns the remaining
        members' pick."""
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
                        beam_designers[type_id], group_pick, loads, own, lightest
                    )
                _with_seismic(group_pick, kind, own[0]["object"], own, label_of, opts)
            new_id, k = _new_id(type_id, taken)
            governing = max(group, key=lambda m: m.pick.area).id
            found.new_types.append(
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
                found.reassign.append(
                    {"member": m.id, "from": type_id, "to": new_id, "source": sources.get(m.id)}
                )
        if accepted and kind == "beam" and type_id in beam_designers:
            # B10 of walk 3: the members that stay get Mn+ >= Mn-/2 too (their bars were
            # proposed afresh from their own envelope, without it).
            leaving = {m.id for group, _ in accepted for m in group}
            staying = [m for m in members if m.id not in leaving]
            own = [collected_by_id[m.id] for m in staying if m.id in collected_by_id]
            if staying and own:
                loads = staying[0].loads
                for m in staying[1:]:
                    loads = loads.envelope(m.loads)
                remaining = _beam_positive_moment(
                    beam_designers[type_id], remaining, loads, own, lightest
                )
        return remaining

    # Beams.
    beams: dict[str, list[dict[str, Any]]] = {}
    for member in gathered.collect.get("members", []):
        if member["kind"] == "beam":
            beams.setdefault(member["type"], []).append(member)

    beam_loads: dict[str, BeamLoads] = {}  # by member id, for the joints' second pass too

    def beam_type(type_id: str, lightest: bool = False) -> _TypeResult:
        """The proposal of a beam type; ``lightest``: the least steel that passes (for the
        joint shear) rather than the best ranked bars."""
        rpc_jobs.check()  # Stop Waiting on Design Reinforcement stops the proposal here
        members = beams[type_id]
        first = members[0]
        designer = beam_designers[type_id]
        found = _TypeResult()
        picks = []
        cache: dict[BeamLoads, Pick] = {}
        for member in members:
            if member["id"] not in beam_loads:
                beam_loads[member["id"]] = _beam_loads(member, combinations)
            loads = beam_loads[member["id"]]
            key = BeamLoads(
                *(round(v, -3) for v in (loads.sag, loads.hog, loads.shear)),
                round(loads.at_s, 4),
                round(loads.al, -1),
                loads.torsion_s_max,
            )
            if key not in cache:
                cache[key] = designer.propose(loads, lightest)
            picks.append(MemberPick(member["id"], loads, cache[key]))
        envelope = picks[0].loads
        for m in picks[1:]:
            envelope = envelope.envelope(m.loads)
        pick = designer.propose(envelope, lightest)
        pick = _beam_positive_moment(designer, pick, envelope, members, lightest)
        governing = max(picks, key=lambda m: m.pick.area if m.pick.reinforcement else math.inf).id
        over = _over_designed(pick, picks, opts.over_design) if pick.reinforcement else []
        by_type_pick = pick
        if mode == "splitTypes" and pick.reinforcement is not None:
            pick = split(
                type_id,
                "beam",
                first["object"].name,
                _beam_label,
                pick,
                picks,
                lambda loads: designer.propose(loads, lightest),
                found,
                lightest,
            )
        seismic = _with_seismic(pick, "beam", first["object"], members, _beam_label, opts)
        if mode == "splitTypes" and by_type_pick is not pick:
            # The shared bars get their hoops too: members that stay and the joint pass use them.
            _with_seismic(by_type_pick, "beam", first["object"], members, _beam_label, opts)
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
        _seismic_entry(entry, seismic, found.warnings)
        found.entry = entry
        return found

    results: list[_TypeResult] = []
    beam_results: dict[str, _TypeResult] = {}
    rooms = _anchorage_rooms(gathered)
    for type_id, members in beams.items():
        first = members[0]
        try:
            designer = BeamDesigner(
                first["object"], first["fc"], first["fy"], first["es"], first["aggregate"], opts,
                max(float(m.get("topDrop") or 0.0) for m in members),
            )  # fmt: skip
        except DesignError as error:
            results.append(_TypeResult(warnings=[f"{type_id}: {error}"]))
            continue
        designer.anchorage = _type_anchorage(members, rooms)
        beam_designers[type_id] = designer
        beam_results[type_id] = beam_type(type_id)
        results.append(beam_results[type_id])

    # Columns.
    column_results: dict[str, _TypeResult] = {}
    column_searches = column_requirements(gathered, opts)
    column_index: dict[str, int] = {}  # the layout of the type's shared bars

    def column_type(type_id: str, at_least: int | None = None) -> _TypeResult:
        """The proposal of a column type; ``at_least``: the least layout its shared bars take
        (the strong column pass), which proposes for all its members (no split)."""
        rpc_jobs.check()
        search, members = column_searches[type_id]
        obj = search.obj
        found = _TypeResult()
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
        if index is not None and at_least is not None:
            index = max(index, at_least)
        collected = [m for m in gathered.collect.get("members", []) if m["type"] == type_id]
        pick = _detailed_column_pick(search, index, all_points, collected, opts)
        if pick.index is not None:
            column_index[type_id] = pick.index
        governing = max(picks, key=lambda m: m.pick.area if m.pick.reinforcement else math.inf).id
        over = _over_designed(pick, picks, opts.over_design) if pick.reinforcement else []
        by_type_pick = pick

        if mode == "splitTypes" and pick.reinforcement is not None and at_least is None:
            pick = split(
                type_id,
                "column",
                obj.name,
                _column_label,
                pick,
                picks,
                lambda loads, s=search, c=collected: _detailed_column_pick(
                    s, loads.index, loads.points, c, opts
                ),
                found,
            )
        seismic = _with_seismic(pick, "column", obj, collected, _column_label, opts)
        if mode == "splitTypes" and by_type_pick is not pick:
            _with_seismic(by_type_pick, "column", obj, collected, _column_label, opts)
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
        _seismic_entry(entry, seismic, found.warnings)
        found.entry = entry
        return found

    for type_id in column_searches:
        column_results[type_id] = column_type(type_id)
        results.append(column_results[type_id])
    bar_rooms = _bar_rooms(gathered)
    # R3 misc: column bars that would not anchor in their foundation: the type proposed again
    # with the bar sizes that do, kept when it still passes (else the note says what to do).
    for type_id in list(column_searches):
        first = column_results[type_id]
        short = _column_short(first.entry, bar_rooms, gathered, opts)
        if short is None or not short[2]:
            continue
        kept_search = column_searches[type_id]
        _search, members = kept_search
        member = next(
            (m for m in gathered.collect.get("members", []) if m["type"] == type_id), None
        )
        if member is None:
            continue
        smaller = dataclasses.replace(opts, column_diameters=tuple(short[2]))
        alt = ColumnSearch(
            member["object"], member["fc"], member["fy"], member["es"], member["aggregate"], smaller
        )
        column_searches[type_id] = (
            alt,
            {mid: (alt.smallest(points), points) for mid, (_, points) in members.items()},
        )
        taken.difference_update(t["type"] for t in first.new_types)
        again = column_type(type_id)
        if (
            again.entry is not None
            and again.entry.get("proposed")
            and again.entry["status"]
            in (
                "ok",
                "unchanged",
            )
        ):
            _, worst, room, need, _, _ = max(short[1], key=lambda s: s[0])
            again.entry["notes"] = [
                *again.entry["notes"],
                (
                    f"bars of at most Ø{max(short[2]):g}, so they anchor in the foundation "
                    f"(Ø{short[0]:g} needs ldh {need:.0f} mm in {room['foundation']} under "
                    f"{worst}): checked as the others"
                ),
            ]
            column_results[type_id] = again
            results[results.index(first)] = again
        else:
            column_searches[type_id] = kept_search
            taken.difference_update(t["type"] for t in again.new_types)
            taken.update(t["type"] for t in first.new_types)

    # Beam-column joints of special moment frames (Sec 8.3.7): bars cannot raise a joint's
    # capacity (the column section and f'c give it); lighter beam bars lower its shear. The
    # joints are judged on each beam type's shared bars (``byType`` in splitTypes) in both
    # modes, so a column's verdict does not depend on the mode (N-X5 of usability walk 2: a
    # C400x400 failed joint shear when keeping shared types and passed when splitting).
    cases = _joint_cases(gathered)
    if cases:

        def shared(found: _TypeResult | None) -> dict[str, Any] | None:
            if found is None or found.entry is None:
                return None
            if "byType" in found.entry:
                return found.entry["byType"]
            return found.entry["proposed"]

        def sections(chosen: dict[str, _TypeResult]) -> dict[str, Any]:
            """The beam sections at the joints by member id: the shared bars proposed for the
            member's type, else the bars it was checked with."""
            out: dict[str, Any] = {}
            for type_id, members in beams.items():
                bars = shared(chosen.get(type_id))
                section = (
                    None
                    if bars is None
                    else beam_designers[type_id].section(reinforcement_of(bars))
                )
                for member in members:
                    out[member["id"]] = member["section"] if section is None else section
            return out

        failing = _joint_shear(cases, sections(beam_results))
        for type_id, members in beams.items():
            found = beam_results.get(type_id)
            if not failing or not shared(found):
                continue
            failing_ids = {j for ids in failing.values() for j in ids}
            own = {m["id"] for m in members}
            if not any(
                b.id in own for c in cases if c.joint.id in failing_ids for b in c.joint.beams
            ):
                continue
            # (a) The lightest bars that pass the beam's own checks, kept when fewer joints
            # fail with them.
            released = {t["type"] for t in found.new_types}
            taken.difference_update(released)
            trial = beam_type(type_id, lightest=True)
            again = None
            if not _same(shared(trial) or {}, shared(found)):
                again = _joint_shear(cases, sections({**beam_results, type_id: trial}))
            if again is not None and sum(map(len, again.values())) < len(failing_ids):
                fixed = sorted(failing_ids - {j for ids in again.values() for j in ids})
                trial.entry["notes"] = [
                    *trial.entry["notes"],
                    (
                        "the lightest bars that pass, for the joint shear at "
                        f"{_some_joints(fixed)} (Vj from 1.25 fy of the beam bars, Sec 8.3.7.1(a))"
                    ),
                ]
                beam_results[type_id] = trial
                results[results.index(found)] = trial
                failing = again
            else:
                taken.difference_update(t["type"] for t in trial.new_types)
                taken.update(released)
        # (b) Else the column is too small: the next practical size.
        final = sections(beam_results)
        for type_id, joint_ids in failing.items():
            found = column_results.get(type_id)
            if found is None or found.entry is None:
                continue
            own_cases = [c for c in cases if c.column_type == type_id]
            _joint_too_small(found, joint_ids, _joint_column_size(own_cases, final))

        # (c) Strong column / weak beam (Sec 8.3.5.2, Eq. 6.8.5): ΣMnc ≥ 1.2 ΣMnb with the
        # proposed bars; a column type at a joint where it fails takes heavier bars (N-X6 of
        # usability walk 2: 20 joints failing with no remedy), else it is reported.
        raised, short = _strong_column_layouts(
            [c for c in cases if c.strong_required],
            final,
            {t: column_searches[t][0] for t in column_searches},
            {
                t: i
                for t, i in column_index.items()
                if column_results.get(t) is not None
                and column_results[t].entry is not None
                and column_results[t].entry["proposed"]
            },
        )
        for type_id, (index, joint_ids) in raised.items():
            old = column_results[type_id]
            taken.difference_update(t["type"] for t in old.new_types)
            again = column_type(type_id, at_least=index)
            if again.entry is None or not again.entry["proposed"]:
                taken.update(t["type"] for t in old.new_types)
                short.setdefault(type_id, []).extend(joint_ids)
                continue
            again.entry["notes"] = [
                *again.entry["notes"],
                (
                    f"bars raised for strong column / weak beam at {', '.join(joint_ids)}: "
                    "ΣMnc ≥ 1.2 ΣMnb (Sec 8.3.5.2(b), Eq. 6.8.5); for all its members"
                ),
            ]
            column_results[type_id] = again
            results[results.index(old)] = again
        for type_id, joint_ids in short.items():
            found = column_results.get(type_id)
            if found is None or found.entry is None:
                continue
            found.entry["strongColumn"] = {
                "joints": sorted(set(joint_ids)),
                "suggestion": (
                    "no bars up to the largest ρ give ΣMnc ≥ 1.2 ΣMnb (Sec 8.3.5.2(b)): a "
                    "larger column, or lighter beam bars from deeper beams"
                ),
            }
            found.warnings.append(
                f"{type_id}: strong column / weak beam fails at {', '.join(sorted(set(joint_ids)))}"
                " with any bars: a larger column, or lighter beam bars from deeper beams"
            )

    for found in results:
        if found.entry is not None:
            types.append(found.entry)
        new_types += found.new_types
        reassign += found.reassign
        warnings += found.warnings

    # Slabs.
    slabs: dict[str, list[dict[str, Any]]] = {}
    for collected in gathered.collect.get("slabs", []):
        slabs.setdefault(collected["type"], []).append(collected)
    thin_slabs: list[str] = []
    for type_id, collected in slabs.items():
        first = collected[0]
        designer = SlabDesigner(first["object"], first["fc"], first["fy"], first["es"], opts)
        edge_supports: dict[str, list[tuple[float, float, str | None, str]]] = {"X": [], "Y": []}
        for c in collected:
            for direction, found in (bar_rooms["slabs"].get(c["id"]) or {}).items():
                edge_supports[direction] += [(*f, c["id"]) for f in found]
        designer.limit_top_bars(edge_supports)
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
        slab_new: list[dict[str, Any]] = []
        if mode == "splitTypes" and pick.reinforcement is not None:
            found = _TypeResult()
            slab_new = found.new_types
            pick = split(
                type_id,
                "slab",
                first["object"].name,
                _mesh_label,
                pick,
                picks,
                designer.propose,
                found,
            )
            new_types += found.new_types
            reassign += found.reassign
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
            _with_chord_bars(entry["byType"], entry["members"], chords, first["fy"], opts.diameters)
            for new in slab_new:
                new["notes"] = _with_chord_bars(
                    new["proposed"], new["members"], chords, first["fy"], opts.diameters
                )
        moved = {m["member"] for m in reassign if m["from"] == type_id}
        entry["notes"] = [
            *entry["notes"],
            *_with_chord_bars(
                entry["proposed"],
                [m for m in entry["members"] if m not in moved],
                chords,
                first["fy"],
                opts.diameters,
            ),
        ]
        if entry["status"] in ("ok", "unchanged") and entry["current"] is not None:
            same = _same(entry["current"], entry["proposed"])
            entry["status"] = "unchanged" if same else "ok"
        _with_punching(entry, itertools.chain.from_iterable(x["checks"] for x in collected))
        entry["notes"] = [*entry["notes"], *designer.anchorage_notes]
        thin = _thin_slabs(type_id, first["object"], collected)
        if thin:
            entry["notes"] = [*entry["notes"], thin]
            thin_slabs.append(thin)
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
    warnings += _column_anchorage(types, bar_rooms, gathered, opts)

    notes: list[str] = []
    if (gathered.root / "09 Substructure" / "substructure.json").exists():
        # No duplication: footings, rafts and pile caps, their bars and punching layouts are
        # designed in 9 Substructure (its Size Footings), never here.
        notes.append(
            "Foundations are designed in 9 Substructure: its Size Footings proposes their "
            "size and bars."
        )
    notes += thin_slabs  # R2-18: said with the summary too, not only in the type's row
    for t in types:
        if t["status"] == "tooSmall":
            warnings.append(f"{t['type']}: section too small — {t['tooSmall']['reason']}")
    return {
        "mode": mode,
        "types": types,
        "newTypes": new_types,
        "reassign": reassign,
        "foundations": [],
        "warnings": warnings,
        "notes": notes,
    }


# ─────────────────────────────────── seismic detailing ───────────────────────────────────


def _zone_text(transverse: dict[str, Any]) -> str:
    zone = transverse.get("zone") or {}
    if not zone or zone.get("spacing") == transverse.get("spacing"):
        return ""  # one spacing along the member: said once (X27 of the usability walk)
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
    """The proposed reinforcement with the hoop zones of the default pack's BNBC Sec 8.3 for the type's members
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
            if rho > dm._column_rho()[1] + 1e-9:
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
    # A tie leg needs a bar to hold: never more legs than bars on the face (4Ø32 with 4 legs
    # cannot be built); a section that needs more takes more bars (_detailed_column_pick).
    if circle:
        most_y, most_x = legs + 2, legs_x + 2
    else:
        most_y = min(len(dm._face_bars(section, "y", s)) for s in (1, -1))
        most_x = legs_x
        if kind == "column":
            most_x = min(len(dm._face_bars(section, "x", s)) for s in (1, -1))
    most_y, most_x = max(most_y, legs), max(most_x, legs_x)
    av_s: dict[str, float] = {}
    for c in contexts:
        for axis, value in capacity_av_s(section, kind, c).items():
            av_s[axis] = max(av_s.get(axis, 0.0), value)

    hx_max = dm._special("hxMax")

    def zones_for(dia: float, ly: int, lx: int) -> dict[str, Any] | None:
        db = min(bar.dia for bar in section.bars)
        if kind == "column" and special and not circle:
            hx = max(dm._hx(b - 2 * cover, dia, db, ly), dm._hx(h - 2 * cover, dia, db, lx))
            if hx > hx_max:
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
            for ly in range(legs, min(legs + 2, most_y) + 1)
            for lx in (
                range(legs_x, min(legs_x + 2, most_x) + 1) if kind == "column" else (legs_x,)
            )
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
            f"no ties up to Ø{max(opts.stirrup_diameters):g} with a leg on at most every bar "
            f"give the seismic hoops at {opts.min_stirrup_spacing:g} mm or more with hx ≤ "
            f"{hx_max:g} mm: more bars on the faces or a larger section"
        )
        return reinforcement, {
            "zones": None,
            "sectionTooSmall": too_small,
            "notes": notes,
            "detailable": False,
        }
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
    needed = {axis: value for axis, value in sorted(av_s.items()) if value > 1e-9}
    if needed:
        notes.append(
            "hoops for the capacity shear Ve (Sec 8.3.8 / 8.3.10.3): Av/s "
            + ", ".join(f"{axis} {value:.2f} mm²/mm" for axis, value in needed.items())
        )
    elif av_s:
        notes.append(
            "capacity shear Ve (Sec 8.3.8 / 8.3.10.3): φ Vc carries it, the confinement rules "
            "set the hoops"
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
    designer: BeamDesigner,
    pick: Pick,
    loads: BeamLoads,
    members: list[dict[str, Any]],
    lightest: bool = False,
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

    for _ in range(6):
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
        loads = dataclasses.replace(loads, sag=new_sag, hog=new_hog)
        again = designer.propose(loads, lightest)
        if again.reinforcement is None:
            return pick
        again.notes = [*again.notes, *why]
        pick = again
    _, sag, hog, _ = designer._analyse(pick.reinforcement)
    if sag.mn < 0.5 * hog.mn - 1e-6:
        note = "Mn+ ≥ Mn-/2 at the faces not reached (Sec 8.3.4.2(a))"
        pick = dataclasses.replace(pick, notes=[*pick.notes, note])
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
                + f"; {clause('punching', 'section')})"
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
    ``{"objectsText", "bimText", "floorPlanText"?, "changes"}``. Pure: it
    reads and writes nothing. Entries with ``"apply": false`` (set by the workbench when the
    engineer unticks one) and those without a proposal (too small) are left out, but for a
    column type too small for its joints' shear with ``"applyStrengthBars": true``, which takes
    its ``strengthBars`` (:func:`_joint_too_small`); new types are
    added after the type they come from, their members reassigned in the BIM model (and in the
    floor plan, for members that come from it; the BIM model's stamp of the floor plan follows
    when it was current). When a split-off member stays in its type (its new type or its row
    unticked), the type takes its ``byType`` bars (designed for all its members), not the split's;
    a new type none of whose members moves is not added. ``changes``: ``[{"file", "id", "what", "from",
    "to", "message"}]``. Raises ``ValueError`` when a text is not valid JSON or a type is not there.
    ``substructure_text`` is accepted and ignored (older callers send it): foundations are
    designed in 9 Substructure."""
    from saengine.library.bim import floor_plan_current, floor_plan_stamp
    from saengine.library.objects import ObjectLibrary

    objects = json.loads(objects_text)
    bim = json.loads(bim_text)
    plan = json.loads(floor_plan_text) if floor_plan_text is not None else None
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
        if entry.get("applyStrengthBars") and entry.get("strengthBars"):
            # A column type too small for its joints' shear, given the bars its own strength
            # needs anyway: the joints still fail until the section grows.
            entry = {**entry, "proposed": entry["strengthBars"], "byType": None}
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
        new_stamp = floor_plan_stamp(result["floorPlanText"])
        if floor_plan_current(stamps.get("floorPlan"), floor_plan_text) and (
            new_stamp != stamps.get("floorPlan")
        ):
            stamps["floorPlan"] = new_stamp
            result["bimText"] = _dump(bim, bim_text)
    return result


__all__ = ["apply_proposal", "design_proposal"]
