"""Design of reinforced-concrete waist-slab stairs (BNBC 2020 Part 6 Sec 6.7, with the stair
geometry rules of Part 3 Sec 1.14.5 and Part 4 Sec 3.10).

Stairs are not in the analysis model (``saengine.fem.derive`` reports them as not modelled), so
they are designed by hand methods, as a structural office does: each flight is a one-way slab
spanning horizontally (BNBC Sec 6.7.1.1: "the effective span of stairs without stringer beams
shall be taken as the following horizontal distances"), loaded per plan area.

Pages cited are those of the BNBC 2020 PDF (Bangladesh Gazette, 11 February 2021).

Geometry (:func:`stair_geometry`). A ``Stair`` of 06 BIM rises from its base story to its top
story; its type (04 Objects, ``Staircase``) gives the riser, tread, waist and flight width.
The number of risers is ``round(rise / riser)`` (as the BOQ measures it), the risers built are
``rise / n``. A straight stair is one flight; a dog-legged stair (``arrangement``
"dogLegged") is two flights of ``ceil(n/2)`` and ``floor(n/2)`` risers with a half landing
between them. The going of a flight of ``k`` risers is ``(k - 1) T``: its top riser lands on
the landing or floor. Per flight: cos θ = T / √(R² + T²), the waist t is measured
perpendicular to the soffit (Sec 6.7.1.4, p. 974) and the mean thickness for the self weight
on plan is t / cos θ + R / 2.

Effective span (Sec 6.7.1.1, pp. 972-973; ``spanning`` of the type):

- "betweenBeams" (a): beams at the top and bottom risers spanning parallel with them: centre
  to centre of the beams, going + supportWidth;
- "landingEdges" (b): at the edges of landing slabs spanning parallel with the risers: going +
  min(landing / 2, 1.0 m) at each end; the landings span across and carry the flights;
- "withLandings" (c): the landings span in the direction of the flight: centre to centre of
  the supporting beams or walls, landing + going + landing + supportWidth;
- "landingsThreeSides" (d): landings at right angles supported on three sides: the going;
  positive and negative moments wl²/8 (BNBC's own rule); the landings span across.

A type without ``spanning`` is (a): the BIM stair is a flight from floor to floor with no
landings drawn, so the floor beams at its ends are its supports.

Loads (:func:`loads_from_settings`): the stairs area load of the project settings (use
"stairs"), else BNBC Table 6.2.3 (p. 536) "Stairs and exit ways" 4.80 kN/m² (2.00 for one-
and two-family residences only); its floor finish on plan. Self weight: the concrete
material's density x g (as the analysis takes it; BNBC Table 6.2.1, p. 530: 22.8 kN/m³ stone
aggregate plain concrete, plus 0.63 kN/m³ per 1% of steel). Strength combinations: the gravity
combinations of the settings (no wind, earthquake or temperature), else 1.4D and 1.2D + 1.6L
(Sec 2.7.3.1, p. 685); Sec 6.7.1.2 (p. 973) refers stairs to them.

Strength (per metre width, Sec 6.7.1.5.1, p. 974: the rules for beams and one-way slabs):
the moment of a simply supported beam with the flight and landing loads as patches (both ends
simple: no end restraint is counted; at an end entered as continuous a support moment of
w L² / 10 with w the mean load is designed for, an SAEngine adoption, not a BNBC clause; for
(d) wl²/8 at both ends). Flexure by the rectangular stress block (saengine.design.slab /
bars, the slab strip code of the design mode). As,min = the shrinkage and temperature ratio of
Sec 8.1.11.2(a) (p. 1075: 0.0020 for fy 275 or 350, 0.0018 for 420, 0.0018 x 420 / fy above,
at least 0.0014; 1.5 times for brick aggregate concrete, (b)) in the span direction (Sec
6.3.5.4, p. 907) and as the distribution steel; main bars at most min(3h, 450 mm) apart (Sec
6.3.5.4, p. 907; 8.1.6.5, p. 1068), distribution bars min(5h, 450 mm) (Sec 8.1.11.2(c)).
One-way shear without shear reinforcement: φVc = 0.75 x 0.17 λ √f'c b d (Sec 6.4.2.1.1, Eq.
6.6.49, p. 922; λ = 1), against the support reaction (the critical section at d from the face
that Sec 6.4.1.3.1 permits is not used: conservative). Deflection by the span/thickness ratios
of Table 6.6.1 (Sec 6.2.5.2, p. 900: l/20 simply supported, l/24 one end continuous, l/28
both, x (0.4 + fy/700) for fy other than 420), the ratio increased by 15% where the flight
occupies at least 60% of the span (Sec 6.7.1.5.2, p. 974); reported, as for slabs.

Landings spanning across the flights ((b), (d)) are one-way slabs spanning between the walls
or beams at their sides: W + supportWidth for one flight, 2W + well + supportWidth for the
half landing of a dog-legged stair, loaded by their own weight, finish and live load and by
the reactions of the flights landing on them, spread over the landing's depth along the
travel; in (b) the strip of landing inside a flight's span is in that flight's reaction and
its own load is not counted again there. The half landing of a dog-legged stair spanning
between beams (a) is not designed (a note says so). A flight of one riser (no going) is
skipped. Not handled: stairs with stringer beams, cantilever steps, free-standing, sawtooth and
helicoidal stairs (Appendix M), the 150 mm strip of Sec 6.7.1.3.1 for flights built into walls
(not deducted: conservative), the halved loads of open wells (Sec 6.7.1.3, Figure 6.6.27), the
concentrated tread load of Table 6.2.3 note l (1.33 kN), and the stairs' part in the lateral
system.

Units: mm, N, MPa; loads in kN/m² and kN/m, moments kN·m/m in the report.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context
from saengine.design import bars as B
from saengine.design import slab as slab_design
from saengine.design.rc import PHI_SHEAR, bar_area

G = 9.80665  # m/s², as saengine.fem.derive
DENSITY = 2400.0  # kg/m³ when the material gives none
SUPPORT_WIDTH = 250.0  # mm, width of the supporting beams or walls when not entered
SPANNINGS = ("betweenBeams", "landingEdges", "withLandings", "landingsThreeSides")

#: Live load on stairs, BNBC 2020 Part 6 Table 6.2.3 (p. 536) [kN/m²].
LIVE_STAIRS = 4.80
LIVE_STAIRS_DWELLING = 2.00


def gravity_combinations() -> tuple[tuple[str, float, float], ...]:
    """The strength combinations with gravity loads only, as (name, D factor, L factor): the
    pack's ``combinations.gravity`` (BNBC 2020 Part 6 Sec 2.7.3.1, p. 685: 1.4D and
    1.2D + 1.6L)."""
    return tuple(
        (c.name, c.factors["D"], c.factors.get("L", 0.0))
        for c in code_context.table("combinations").gravity
    )


def _cover() -> float:
    """Cover [mm] assumed when no reinforcement is entered (as the design mode's slabs): the
    pack's ``concrete.cover.stair`` (BNBC 2020: 20 mm)."""
    return float(code_context.table("concrete").cover["stair"])


#: Sum of two risers and one tread, BNBC Part 3 Sec 1.14.5.2 (p. 69) [mm].
TWO_R_PLUS_T = (610.0, 648.0)
#: BNBC Part 4 Table 4.3.5 (p. 310): (riser, tread) combinations [mm].
TABLE_4_3_5 = (
    (127, 406),
    (133, 394),
    (140, 375),
    (146, 356),
    (152, 343),
    (159, 330),
    (165, 311),
    (171, 324),  # as printed (out of sequence)
    (178, 279),
    (184, 267),
    (190, 254),
    (197, 241),
    (203, 229),
    (210, 216),
    (216, 210),
    (222, 206),
    (229, 203),
)
#: Largest rise of a flight between landings, Part 3 Sec 1.14.5.3 (p. 69) [mm].
FLIGHT_RISE_MAX = 3660.0
FLIGHT_RISE_MAX_ASSEMBLY = 2440.0
#: Clear headroom between flights, Part 3 Sec 1.14.5.4 (p. 69) [mm].
HEADROOM = 2150.0
HEADROOM_REDUCED = 2030.0  # for not more than three flights in any staircase
#: Variation between adjacent risers or treads, Part 4 Sec 3.10.6 (p. 313) [mm].
RISER_VARIATION = 5.0
#: Landing in a straight run need not be wider in the travel direction, Part 4 Sec 3.10.2.
STRAIGHT_LANDING_CAP = 1200.0

METHOD = [
    (
        "Stairs (not in the analysis model): each flight a one-way slab spanning horizontally, "
        "per metre width, with the effective spans of BNBC 2020 Part 6 Sec 6.7.1.1 (a)-(d) "
        "(between beams: centre to centre; at landing edges: going + min(landing/2, 1.0 m) "
        "each end; landings spanning with the flight: centre to centre of their supports; "
        "landings on three sides: the going, ±wl²/8). Loads on plan: self weight with the "
        "mean thickness t/cosθ + R/2 (t the waist perpendicular to the soffit, Sec 6.7.1.4), "
        "the stairs area load's finish and live load (Table 6.2.3: 4.80 kN/m²), the gravity "
        "strength combinations (Sec 2.7.3.1). Moments of a simply supported span with the "
        "flight and landing loads as patches; at an end entered as continuous wL²/10 "
        "(SAEngine adoption)."
    ),
    (
        "Stair sections: flexure by the rectangular stress block, d = t - cover - db/2, εt ≥ "
        "0.004; As,min and distribution steel by Sec 8.1.11.2 (0.0018 for fy 420; x1.5 brick "
        "aggregate), main bars at most min(3h, 450 mm) apart (Sec 6.3.5.4, 8.1.6.5), "
        "distribution bars min(5h, 450 mm) (8.1.11.2(c)); one-way shear φ 0.17 √f'c b d "
        "(Sec 6.4.2.1.1) against the support reaction; minimum thickness of Table 6.6.1 "
        "with the ratio increased by 15% where the flight is at least 60% of the span "
        "(Sec 6.7.1.5.2), reported. Landings spanning across the flights carry the flights' "
        "reactions spread over their depth. Geometry: 2R + T within 610-648 mm (Part 3 Sec "
        "1.14.5.2), risers within Table 4.3.5 of Part 4, flight rise ≤ 3660 mm (2440 mm "
        "assembly, Sec 1.14.5.3), headroom ≥ 2.15 m (Sec 1.14.5.4), stair width by Part 4 "
        "Table 4.3.6, landing depth ≥ the stair width (Part 4 Sec 3.10.2)."
    ),
]


# ─────────────────────────────────────── inputs ───────────────────────────────────────


@dataclass(frozen=True)
class Mesh:
    dia: float
    spacing: float

    @property
    def area(self) -> float:
        """mm²/m."""
        return bar_area(self.dia) * 1000 / self.spacing

    def label(self) -> str:
        return f"Ø{self.dia:g} @ {self.spacing:g}"


@dataclass(frozen=True)
class StairBars:
    """The bars of a staircase type (``StairReinforcement``): ``top`` over continuous supports
    and ``landing`` (main bars of landings spanning across) are proposed fields; None for top
    means no top bars, for landing the main mesh."""

    material: str
    cover: float
    main: Mesh
    distribution: Mesh
    top: Mesh | None = None
    landing: Mesh | None = None


@dataclass(frozen=True)
class StairSpec:
    """A staircase type, with the proposed fields' defaults (see :func:`spec_of`)."""

    waist: float
    riser: float
    tread: float
    width: float
    arrangement: str = "straight"  # "straight" | "dogLegged"
    spanning: str = "betweenBeams"  # one of SPANNINGS
    landing_length: float | None = None  # along the travel [mm]; None: the flight width
    landing_thickness: float | None = None  # None: the waist
    support_width: float = SUPPORT_WIDTH
    bottom_end: str = "simple"  # "simple" | "continuous"
    top_end: str = "simple"
    well: float = 0.0  # gap between the flights of a dog-legged stair [mm]
    headroom: float | None = None  # clear headroom provided [mm]
    bars: StairBars | None = None

    @property
    def landing(self) -> float:
        return self.landing_length if self.landing_length else self.width

    @property
    def landing_h(self) -> float:
        return self.landing_thickness if self.landing_thickness else self.waist


def _mesh(value: Any) -> Mesh | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return Mesh(float(value["dia"]), float(value["spacing"]))
    return Mesh(float(value.dia), float(value.spacing))


def bars_of(reinforcement: Any) -> StairBars | None:
    """The bars of a ``StairReinforcement`` (model or its JSON dict)."""
    if reinforcement is None:
        return None
    get = (
        reinforcement.get
        if isinstance(reinforcement, dict)
        else (lambda name, default=None: getattr(reinforcement, name, default))
    )
    main, distribution = _mesh(get("main")), _mesh(get("distribution"))
    assert main is not None and distribution is not None
    return StairBars(
        str(get("material")),
        float(get("cover")),
        main,
        distribution,
        _mesh(get("top", None)),
        _mesh(get("landing", None)),
    )


def spec_of(staircase: Any) -> StairSpec:
    """The spec of a ``Staircase`` object type. The fields this module proposes for it
    (``arrangement``, ``spanning``, ``landingLength``, ``landingThickness``, ``supportWidth``,
    ``bottomEnd``, ``topEnd``, ``wellWidth``, ``headroom``) are read when present, so a type
    without them is designed with the defaults."""

    def get(name: str, default: Any) -> Any:
        value = getattr(staircase, name, None)
        return default if value is None else value

    return StairSpec(
        waist=float(staircase.waistThickness),
        riser=float(staircase.riser),
        tread=float(staircase.tread),
        width=float(staircase.flightWidth),
        arrangement=get("arrangement", "straight"),
        spanning=get("spanning", "betweenBeams"),
        landing_length=get("landingLength", None),
        landing_thickness=get("landingThickness", None),
        support_width=float(get("supportWidth", SUPPORT_WIDTH)),
        bottom_end=get("bottomEnd", "simple"),
        top_end=get("topEnd", "simple"),
        well=float(get("wellWidth", 0.0)),
        headroom=get("headroom", None),
        bars=bars_of(getattr(staircase, "reinforcement", None)),
    )


@dataclass(frozen=True)
class StairMaterial:
    fc: float  # MPa
    fy: float  # MPa
    es: float = 200_000.0
    density: float = DENSITY  # kg/m³
    brick_aggregate: bool = False
    steel: str = ""  # id of the bar material

    @property
    def unit_weight(self) -> float:
        """kN/m³."""
        return self.density * G / 1000


def material_of(
    staircase: Any, materials: dict[str, Any], default_rebar: str | None = None
) -> StairMaterial | str:
    """The concrete and bar strengths of a staircase type, or why it cannot be designed. A
    type without reinforcement is designed with ``default_rebar`` (the design mode's
    ``required._default_rebar``), else the first reinforcing bar material."""
    concrete = materials.get(staircase.material)
    if concrete is None or getattr(concrete, "concrete", None) is None:
        return f"'{staircase.material}' is not a concrete material"
    reinforcement = getattr(staircase, "reinforcement", None)
    if reinforcement is not None:
        steel_id = reinforcement.material
    else:
        steel_id = default_rebar or next(
            (
                m.id
                for m in materials.values()
                if getattr(m.category, "value", m.category) == "rebar" and m.steel
            ),
            None,
        )
    steel = materials.get(steel_id) if steel_id else None
    if steel is None or steel.steel is None:
        return f"unknown reinforcement material '{steel_id}'"
    density = (concrete.mechanical.density if concrete.mechanical else None) or DENSITY
    es = (steel.mechanical.E if steel.mechanical else None) or 200_000.0
    return StairMaterial(concrete.concrete.fc, steel.steel.fy, es, density, steel=steel.id)


@dataclass(frozen=True)
class StairLoads:
    finish: float  # kN/m² on plan
    live: float  # kN/m²
    combinations: tuple[tuple[str, float, float], ...]  # (name, D factor, L factor)
    source: str = ""


def loads_from_settings(settings: Any | None) -> StairLoads:
    """The stairs area load (use "stairs") and gravity combinations of the project settings,
    with BNBC's values where the settings have none (see the module notes)."""
    area = None
    combos: list[tuple[str, float, float]] = []
    use = None
    if settings is not None:
        area = next((a for a in settings.areaLoads if a.use == "stairs"), None)
        use = settings.occupancy.use
        seen = set()
        for c in settings.combinations:
            lateral = (c.WX, c.WY, c.EX, c.EY, c.T)
            if any(lateral) or (c.D == 0 and c.L == 0):
                continue
            key = (round(c.D, 6), round(c.L, 6))
            if key not in seen:
                seen.add(key)
                combos.append((c.name, float(c.D), float(c.L)))
    if area is not None:
        live, finish = float(area.live), float(area.finish) + float(area.partitions)
        source = f"area load {area.id} ({area.name})"
        if live < LIVE_STAIRS:
            source += f"; below BNBC Table 6.2.3's {LIVE_STAIRS} kN/m² for stairs"
            if use == "residential" and live >= LIVE_STAIRS_DWELLING:
                source += (
                    f" (its {LIVE_STAIRS_DWELLING} kN/m² row is for one- and two-family "
                    "residences only)"
                )
    else:
        live, finish = LIVE_STAIRS, 0.0
        source = f"BNBC Table 6.2.3 (p. 536): stairs and exit ways {LIVE_STAIRS} kN/m²"
    if not combos:
        combos = list(gravity_combinations())
    return StairLoads(finish, live, tuple(combos), source)


# ─────────────────────────────────────── geometry ───────────────────────────────────────


@dataclass(frozen=True)
class Flight:
    name: str
    risers: int
    riser: float  # mm, as built: rise / n
    tread: float
    going: float  # mm, (risers - 1) x tread
    span: float  # mm, effective horizontal span
    rule: str
    landing_bottom: float  # mm of landing inside the span, at each end ((b), (c))
    landing_top: float
    ends: tuple[str, str]  # bottom, top: "simple" | "continuous"

    @property
    def rise(self) -> float:
        return self.risers * self.riser

    @property
    def cos(self) -> float:
        return self.tread / math.hypot(self.riser, self.tread)

    def mean_thickness(self, waist: float) -> float:
        """t / cos θ + R / 2 [mm]: the concrete per plan area of waist and steps."""
        return waist / self.cos + self.riser / 2


@dataclass(frozen=True)
class Landing:
    """A landing spanning across the flights between supports at its sides."""

    name: str
    span: float  # mm
    depth: float  # mm, along the travel
    flights: tuple[tuple[str, float, float], ...]  # (flight, start, end) along the span [mm]


@dataclass(frozen=True)
class StairGeometry:
    rise: float
    risers: int
    riser: float
    flights: tuple[Flight, ...]
    landings: tuple[Landing, ...]


def stair_geometry(spec: StairSpec, rise: float) -> StairGeometry:
    """Flights and landings of a stair rising ``rise`` mm (see the module notes)."""
    if spec.spanning not in SPANNINGS:
        raise ValueError(f"unknown stair spanning '{spec.spanning}'")
    n = max(1, round(rise / spec.riser))
    riser = rise / n
    counts = [n] if spec.arrangement != "dogLegged" else [math.ceil(n / 2), n // 2]
    counts = [k for k in counts if k > 0]
    flights = []
    lnd, sw = spec.landing, spec.support_width
    for i, k in enumerate(counts):
        going = (k - 1) * spec.tread
        if spec.spanning == "betweenBeams":
            span, rule, lb, lt = going + sw, "Sec 6.7.1.1(a): centre to centre of beams", 0, 0
        elif spec.spanning == "landingEdges":
            ext = min(lnd / 2, 1000.0)
            span, lb, lt = going + 2 * ext, ext, ext
            rule = "Sec 6.7.1.1(b): going + min(landing/2, 1.0 m) each end"
        elif spec.spanning == "withLandings":
            span, lb, lt = lnd + going + lnd + sw, lnd + sw / 2, lnd + sw / 2
            rule = "Sec 6.7.1.1(c): centre to centre of the landings' supports"
        else:
            span, lb, lt = going, 0, 0
            rule = "Sec 6.7.1.1(d): the going"
        if going <= 0 or span <= 0:
            raise ValueError(
                f"flight F{i + 1} has {k} riser{'s' if k != 1 else ''}: no going, not designed "
                "as a sloping slab (a step on the floor or landing)"
            )
        flights.append(
            Flight(
                f"F{i + 1}",
                k,
                riser,
                spec.tread,
                going,
                span,
                rule,
                lb,
                lt,
                (spec.bottom_end, spec.top_end),
            )
        )
    landings: list[Landing] = []
    if spec.spanning in ("landingEdges", "landingsThreeSides"):
        w, half = spec.width, spec.support_width / 2
        if spec.arrangement == "dogLegged" and len(flights) == 2:
            span = 2 * w + spec.well + spec.support_width
            landings.append(
                Landing(
                    "L1",
                    span,
                    lnd,
                    (
                        ("F1", half, half + w),
                        ("F2", half + w + spec.well, half + 2 * w + spec.well),
                    ),
                )
            )
        else:
            span = w + spec.support_width
            landings += [
                Landing("L0", span, lnd, (("F1", half, half + w),)),
                Landing("L1", span, lnd, ((flights[-1].name, half, half + w),)),
            ]
    return StairGeometry(rise, n, riser, tuple(flights), tuple(landings))


# ─────────────────────────────────────── statics ───────────────────────────────────────


@dataclass(frozen=True)
class BeamResult:
    left: float  # reactions [kN per m width, or kN]
    right: float
    moment: float  # largest sagging moment
    at: float  # where [m]


def simple_beam(span: float, patches: Iterable[tuple[float, float, float]]) -> BeamResult:
    """Reactions and the largest moment of a simply supported span [m] under uniform patches
    ``(start, end, q)`` [m, m, kN/m], exact (the zero of the piecewise linear shear)."""
    if span <= 0:
        raise ValueError("a span of zero length cannot be designed")
    patches = [(max(0.0, a), min(span, b), q) for a, b, q in patches if b > a]
    total = sum(q * (b - a) for a, b, q in patches)
    right = sum(q * (b - a) * (a + b) / 2 for a, b, q in patches) / span
    left = total - right

    def shear(x: float) -> float:
        return left - sum(q * min(max(x - a, 0.0), b - a) for a, b, q in patches)

    def bending(x: float) -> float:
        m = left * x
        for a, b, q in patches:
            if x > a:
                e = min(x, b)
                m -= q * (e - a) * (x - (a + e) / 2)
        return m

    points = sorted({0.0, span, *(a for a, _, _ in patches), *(b for _, b, _ in patches)})
    at = span / 2
    for x0, x1 in pairwise(points):
        v0, v1 = shear(x0), shear(x1)
        if v0 >= 0 >= v1:
            at = x0 if v0 == v1 else x0 + v0 * (x1 - x0) / (v0 - v1)
            break
    return BeamResult(left, right, bending(at), at)


@dataclass(frozen=True)
class PartLoads:
    """Service loads per plan area of a flight or landing [kN/m²]."""

    dead: float  # self weight + finish
    live: float
    self_weight: float


def flight_loads(
    flight: Flight, spec: StairSpec, material: StairMaterial, loads: StairLoads
) -> tuple[PartLoads, PartLoads]:
    """(flight, landing) loads on plan."""
    gamma = material.unit_weight
    sw = gamma * flight.mean_thickness(spec.waist) / 1000
    lw = gamma * spec.landing_h / 1000
    return (
        PartLoads(sw + loads.finish, loads.live, sw),
        PartLoads(lw + loads.finish, loads.live, lw),
    )


@dataclass
class Demand:
    """Factored demands per metre width of a part, enveloped over the combinations."""

    part: str
    kind: str  # "flight" | "landing"
    span: float  # mm
    h: float  # mm
    mu: float = 0.0  # kN·m/m sagging
    mu_top: float = 0.0  # kN·m/m hogging at the supports
    vu: float = 0.0  # kN/m
    wu: float = 0.0  # kN/m², the factored load on the flight (or landing)
    combination: str | None = None
    continuous_ends: int = 0
    going_share: float = 1.0
    notes: list[str] = field(default_factory=list)
    reactions: dict[str, dict[str, float]] = field(default_factory=dict)  # service, kN/m


def _flight_patches(flight: Flight, wf: float, wl: float) -> list[tuple[float, float, float]]:
    span = flight.span / 1000
    lb, lt = flight.landing_bottom / 1000, flight.landing_top / 1000
    patches = [(lb, span - lt, wf)]
    if lb > 0:
        patches.append((0.0, lb, wl))
    if lt > 0:
        patches.append((span - lt, span, wl))
    return patches


def flight_demand(
    flight: Flight, spec: StairSpec, material: StairMaterial, loads: StairLoads
) -> Demand:
    """The factored moments and shear of a flight per metre width (module notes)."""
    on_flight, on_landing = flight_loads(flight, spec, material, loads)
    span = flight.span / 1000
    continuous = sum(1 for e in flight.ends if e == "continuous")
    demand = Demand(
        flight.name,
        "flight",
        flight.span,
        spec.waist,
        continuous_ends=continuous,
        going_share=flight.going / flight.span if flight.span else 1.0,
    )
    for name, fd, fl in loads.combinations:
        wf = fd * on_flight.dead + fl * on_flight.live
        wl = fd * on_landing.dead + fl * on_landing.live
        beam = simple_beam(span, _flight_patches(flight, wf, wl))
        mean = (beam.left + beam.right) / span
        if spec.spanning == "landingsThreeSides":
            top = wf * span**2 / 8  # Sec 6.7.1.1(d): ±wl²/8
        elif continuous:
            top = mean * span**2 / 10
        else:
            top = 0.0
        if beam.moment > demand.mu:
            demand.mu, demand.combination, demand.wu = beam.moment, name, wf
        demand.mu_top = max(demand.mu_top, top)
        demand.vu = max(demand.vu, beam.left, beam.right)
    for case, wf, wl in (
        ("D", on_flight.dead, on_landing.dead),
        ("L", on_flight.live, on_landing.live),
    ):
        beam = simple_beam(span, _flight_patches(flight, wf, wl))
        demand.reactions[case] = {"bottom": beam.left, "top": beam.right}
    if spec.spanning == "landingsThreeSides":
        demand.notes.append("Sec 6.7.1.1(d): positive and negative moments wl²/8")
    elif continuous:
        demand.notes.append("continuous end: support moment wL²/10 (SAEngine adoption)")
    return demand


def landing_demand(
    landing: Landing,
    flights: dict[str, Demand],
    spec: StairSpec,
    material: StairMaterial,
    loads: StairLoads,
) -> Demand:
    """A landing spanning across: own load per metre of its depth plus the flights' reactions
    (per metre of flight width) spread over its depth, at their places along the span."""
    lw = material.unit_weight * spec.landing_h / 1000
    dead, live = lw + loads.finish, loads.live
    span, depth = landing.span / 1000, landing.depth / 1000
    demand = Demand(landing.name, "landing", landing.span, spec.landing_h)

    def reaction(flight: str, case: str) -> float:
        # the landing L0 carries the bottom ends, the others the top end of the flight
        # arriving and the bottom end of the flight leaving
        ends = flights[flight].reactions[case]
        if landing.name == "L0":
            return ends["bottom"]
        if len(landing.flights) == 1:
            return ends["top"]
        return ends["top"] if flight == "F1" else ends["bottom"]

    # Case (b): the strip of landing min(landing/2, 1.0 m) deep inside a flight's span is
    # already in that flight's reaction; its own load is not counted again under the flight.
    inside = min(spec.landing / 2, 1000.0) if spec.spanning == "landingEdges" else 0.0
    share = min(inside / landing.depth, 1.0) if landing.depth > 0 else 0.0

    def patches_of(own: float, r_of) -> list[tuple[float, float, float]]:
        patches = [(0.0, span, own)]
        for flight, a, b in landing.flights:
            patches.append((a / 1000, b / 1000, r_of(flight) / depth - own * share))
        return patches

    for name, fd, fl in loads.combinations:
        own = fd * dead + fl * live
        beam = simple_beam(
            span,
            patches_of(own, lambda f, fd=fd, fl=fl: fd * reaction(f, "D") + fl * reaction(f, "L")),
        )
        if beam.moment > demand.mu:
            demand.mu, demand.combination, demand.wu = beam.moment, name, own
        demand.vu = max(demand.vu, beam.left, beam.right)
    for case, own in (("D", dead), ("L", live)):
        beam = simple_beam(span, patches_of(own, lambda f, c=case: reaction(f, c)))
        demand.reactions[case] = {"left": beam.left, "right": beam.right}
    demand.notes.append(
        "carries " + ", ".join(f for f, _, _ in landing.flights) + f" over {landing.depth:.0f} mm"
    )
    if share:
        demand.notes.append(
            f"its own load over {inside:.0f} mm under each flight is in the flight's reaction "
            "(Sec 6.7.1.1(b)), not counted twice"
        )
    return demand


# ─────────────────────────────────────── geometry checks ───────────────────────────────────────


def _range_check(name: str, value: float, lo: float, hi: float, unit: str, note: str):
    from saengine.design.check import _check

    utilisation = max(lo / value if value > 0 else math.inf, value / hi)
    limit = lo if value < lo else hi
    return _check(name, value, limit, unit, None, note, utilisation=utilisation)


def table_tread(riser: float) -> float:
    """The tread of BNBC Part 4 Table 4.3.5 for ``riser``, interpolated between its rows in
    riser order (the printed 171/324 row is left out of the interpolation: out of sequence)."""
    rows = [(r, t) for r, t in TABLE_4_3_5 if (r, t) != (171, 324)]
    if riser <= rows[0][0]:
        return float(rows[0][1])
    for (r0, t0), (r1, t1) in pairwise(rows):
        if r0 <= riser <= r1:
            return t0 + (t1 - t0) * (riser - r0) / (r1 - r0)
    return float(rows[-1][1])


def minimum_width(use: str | None, occupants: int | None = None) -> tuple[float | None, str]:
    """The least stair width of BNBC Part 4 Table 4.3.6 (p. 311) for the building use of the
    settings, or None where the table gives none ("as per provisions of this Code")."""
    if use == "residential":
        return 1120.0, (
            "residential A3-A5: 1120 mm (Table 4.3.6; for A1, A2 the table refers to itself: "
            "1120 mm taken)"
        )
    if use == "educational":
        if occupants is not None and occupants > 130:
            return 2235.0, "educational, more than 130 occupants: 2235 mm (Table 4.3.6)"
        return 1120.0, "educational, up to 130 occupants: 1120 mm (Table 4.3.6)"
    if use == "healthcare":
        return 2235.0, "hospital patient area: 2235 mm (Table 4.3.6; staff area 1120 mm)"
    return None, f"Table 4.3.6 gives no width for '{use}' (as per provisions of the Code)"


def geometry_checks(
    spec: StairSpec,
    geometry: StairGeometry,
    use: str | None = None,
    occupants: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The BNBC stair geometry checks (design report format) and notes on what is not checked."""
    from saengine.design.check import _check

    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    r, t = geometry.riser, spec.tread
    lo, hi = TWO_R_PLUS_T
    checks.append(
        _range_check(
            "2R + T (BNBC Part 3 Sec 1.14.5.2, p. 69)",
            2 * r + t,
            lo,
            hi,
            "mm",
            f"R = {r:.1f} mm (rise / {geometry.risers}), T = {t:.0f} mm; 610 ≤ 2R + T ≤ 648 mm",
        )
    )
    diff = abs(r - spec.riser)
    checks.append(
        _check(
            "Riser as built against the type's riser",
            diff,
            RISER_VARIATION,
            "mm",
            None,
            f"rise {geometry.rise:.0f} mm / {geometry.risers} risers = {r:.1f} mm against the "
            f"type's {spec.riser:.0f} mm; reported (all risers are equal, so Part 4 Sec 3.10.6, "
            "p. 313, adjacent risers within 5 mm, is met)",
            flag=True,
        )
    )
    checks.append(
        _check(
            "Riser height (Part 4 Table 4.3.5, p. 310)",
            r,
            229.0,
            "mm",
            None,
            "largest riser of Table 4.3.5: 229 mm",
        )
    )
    checks.append(
        _check(
            "Tread depth (Part 4 Table 4.3.5, p. 310)",
            203.0,
            t,
            "mm",
            None,
            "least tread of Table 4.3.5: 203 mm (nosing not included)",
        )
    )
    paired = table_tread(r)
    checks.append(
        _check(
            "Tread for the riser (Part 4 Table 4.3.5, p. 310)",
            paired,
            t,
            "mm",
            None,
            f"the table pairs a {r:.0f} mm riser with a {paired:.0f} mm tread (interpolated); "
            "reported",
            flag=True,
        )
    )
    limit = FLIGHT_RISE_MAX_ASSEMBLY if use == "assembly" else FLIGHT_RISE_MAX
    highest = max(geometry.flights, key=lambda f: f.rise)
    checks.append(
        _check(
            "Flight rise (Part 3 Sec 1.14.5.3, p. 69)",
            highest.rise,
            limit,
            "mm",
            None,
            f"{highest.name}: {highest.risers} risers; at most {limit:.0f} mm between landings"
            + (" (assembly)" if use == "assembly" else ""),
        )
    )
    width, note = minimum_width(use, occupants)
    if width is not None:
        checks.append(
            _check(
                "Stair width (Part 4 Table 4.3.6, p. 311)",
                width,
                spec.width,
                "mm",
                None,
                note + "; flight width taken as the clear width between handrails",
            )
        )
    else:
        notes.append(note)
    has_landings = spec.spanning != "betweenBeams" or spec.arrangement == "dogLegged"
    if has_landings:
        need = spec.width
        rule = "least dimension at least the stair width"
        if spec.arrangement != "dogLegged":
            need = min(need, STRAIGHT_LANDING_CAP)
            rule += ", in a straight run not more than 1.2 m needed"
        checks.append(
            _check(
                "Landing depth (Part 4 Sec 3.10.2, p. 309)",
                need,
                spec.landing,
                "mm",
                None,
                f"landing {spec.landing:.0f} mm along the travel; {rule}",
            )
        )
    if spec.headroom is not None:
        reduced = HEADROOM_REDUCED <= spec.headroom < HEADROOM
        checks.append(
            _check(
                "Headroom (Part 3 Sec 1.14.5.4, p. 69)",
                HEADROOM_REDUCED if reduced else HEADROOM,
                spec.headroom,
                "mm",
                None,
                "at least 2.15 m; 2.03 m allowed for not more than three flights"
                + (" (taken: check the number of flights)" if reduced else ""),
                flag=reduced,
            )
        )
    else:
        notes.append("headroom not entered: not checked (Part 3 Sec 1.14.5.4: 2.15 m)")
    if spec.arrangement == "dogLegged" and spec.spanning == "betweenBeams":
        notes.append(
            "the half landing of a dog-legged stair spanning between beams (Sec 6.7.1.1(a)) "
            "is not designed: design it as a slab, or set the spanning to landingEdges or "
            "landingsThreeSides"
        )
    return checks, notes


# ─────────────────────────────────────── section design ───────────────────────────────────────


def min_ratio(fy: float, brick_aggregate: bool = False) -> float:
    """Shrinkage and temperature (and As,min) ratio of BNBC Sec 8.1.11.2(a), (b)."""
    # B21: the aggregate factor is the code pack's (the project's aggregate unless set here).
    return slab_design.min_steel_ratio(fy, "brick" if brick_aggregate else None)


def thickness_rule(demand: Demand, fy: float) -> tuple[float, str]:
    """Least thickness of Table 6.6.1 (Sec 6.2.5.2) with the stair's 15% (Sec 6.7.1.5.2)."""
    t = slab_design.one_way_thickness(demand.span, demand.continuous_ends, fy)
    if demand.kind == "flight" and demand.going_share >= 0.6:
        return t.required / 1.15, t.note + "; ratio + 15% (Sec 6.7.1.5.2, going ≥ 60% of span)"
    return t.required, t.note


def phi_vc(d: float, fc: float) -> float:
    """φVc per metre [kN/m]: 0.75 x 0.17 √f'c b d (Sec 6.4.2.1.1, Eq. 6.6.49), λ = 1."""
    return PHI_SHEAR * 0.17 * math.sqrt(fc) * 1000 * d / 1000


def part_checks(demand: Demand, bars: StairBars, material: StairMaterial) -> list[dict[str, Any]]:
    """The strength and detailing checks of one flight or landing with the entered bars."""
    from saengine.design.check import _check

    p, h, fc, fy = demand.part, demand.h, material.fc, material.fy
    main = bars.landing if demand.kind == "landing" and bars.landing else bars.main
    d = h - bars.cover - main.dia / 2
    capacity = slab_design.layer_capacity(main.area, d, fc, fy, material.es)
    checks = [
        _check(
            f"{p}: flexure (bottom)",
            demand.mu,
            capacity.phi_mn / 1e6,
            "kN·m/m",
            demand.combination,
            f"{main.label()}, d = {d:.0f} mm, span {demand.span:.0f} mm, wu = {demand.wu:.2f} "
            "kN/m²" + ("; " + "; ".join(demand.notes) if demand.notes else ""),
        ),
        _check(
            f"{p}: net tensile strain",
            capacity.c_d,
            capacity.c_d_limit,
            "c/d",
            None,
            f"εt = {capacity.eps_t:.4f}, at least 0.004 (c/d ≤ {capacity.c_d_limit:.3f})",
        ),
    ]
    if demand.mu_top > 0:
        if bars.top is None:
            checks.append(
                _check(
                    f"{p}: flexure (top, supports)",
                    demand.mu_top,
                    0.0,
                    "kN·m/m",
                    None,
                    "no top bars entered for the support moment",
                )
            )
        else:
            dt = h - bars.cover - bars.top.dia / 2
            top = slab_design.layer_capacity(bars.top.area, dt, fc, fy, material.es)
            checks.append(
                _check(
                    f"{p}: flexure (top, supports)",
                    demand.mu_top,
                    top.phi_mn / 1e6,
                    "kN·m/m",
                    None,
                    f"{bars.top.label()}, d = {dt:.0f} mm",
                )
            )
    checks.append(
        _check(
            f"{p}: one-way shear",
            demand.vu,
            phi_vc(d, fc),
            "kN/m",
            None,
            "φVc = 0.75 x 0.17 √f'c b d (BNBC Sec 6.4.2.1.1, p. 922) at the support reaction",
        )
    )
    ratio = min_ratio(fy, material.brick_aggregate)
    as_min = ratio * 1000 * h
    checks.append(
        _check(
            f"{p}: min. reinforcement",
            as_min,
            main.area,
            "mm²/m",
            None,
            f"{ratio:.4f} Ag = {as_min:.0f} mm²/m (Sec 6.3.5.4, 8.1.11.2, pp. 907, 1075)",
        )
    )
    s_main = min(3 * h, 450.0)
    checks.append(
        _check(
            f"{p}: max. spacing (main)",
            main.spacing,
            s_main,
            "mm",
            None,
            f"min(3h, 450 mm) = {s_main:.0f} mm (Sec 6.3.5.4, 8.1.6.5)",
        )
    )
    checks.append(
        _check(
            f"{p}: distribution steel",
            as_min,
            bars.distribution.area,
            "mm²/m",
            None,
            f"{bars.distribution.label()}; {ratio:.4f} Ag (Sec 8.1.11.2(a))",
        )
    )
    s_dist = min(5 * h, 450.0)
    checks.append(
        _check(
            f"{p}: max. spacing (distribution)",
            bars.distribution.spacing,
            s_dist,
            "mm",
            None,
            f"min(5h, 450 mm) = {s_dist:.0f} mm (Sec 8.1.11.2(c))",
        )
    )
    required, note = thickness_rule(demand, fy)
    checks.append(
        _check(
            f"{p}: min. thickness (Table 6.6.1)",
            required,
            h,
            "mm",
            None,
            note + "; reported (deflection not computed)",
            flag=True,
        )
    )
    return checks


# ─────────────────────────────────────── design mode ───────────────────────────────────────


@dataclass
class StairNeed:
    """What a staircase type needs, enveloped over its stairs (for the design mode)."""

    main: dict[float, float] = field(default_factory=dict)  # dia -> mm²/m
    top: dict[float, float] = field(default_factory=dict)
    landing: dict[float, float] = field(default_factory=dict)
    distribution: float = 0.0
    s_main: float = 450.0
    s_dist: float = 450.0
    s_landing: float = 450.0
    too_small: list[str] = field(default_factory=list)
    governing: str | None = None

    def merge(self, other: StairNeed) -> StairNeed:
        def most(a: dict[float, float], b: dict[float, float]) -> dict[float, float]:
            return {k: max(a.get(k, 0.0), b.get(k, 0.0)) for k in set(a) | set(b)}

        return StairNeed(
            most(self.main, other.main),
            most(self.top, other.top),
            most(self.landing, other.landing),
            max(self.distribution, other.distribution),
            min(self.s_main, other.s_main),
            min(self.s_dist, other.s_dist),
            min(self.s_landing, other.s_landing),
            self.too_small + other.too_small,
            self.governing or other.governing,
        )


def need_of(
    demands: Sequence[Demand],
    cover: float,
    material: StairMaterial,
    diameters: Sequence[float] | None = None,
) -> StairNeed:
    """The bars the parts need, per bar diameter (d depends on it): flexure (bars.
    slab_flexure_need) at least As,min, and the shear the waist must carry without bars."""
    if diameters is None:
        diameters = B.diameters("slab")
    need = StairNeed()
    fc, fy, es = material.fc, material.fy, material.es
    ratio = min_ratio(fy, material.brick_aggregate)
    for demand in demands:
        h = demand.h
        as_min = ratio * 1000 * h
        need.distribution = max(need.distribution, as_min)
        target = need.landing if demand.kind == "landing" else need.main
        if demand.kind == "landing":
            need.s_landing = min(need.s_landing, 3 * h)
        else:
            need.s_main = min(need.s_main, 3 * h)
            need.s_dist = min(need.s_dist, 5 * h)
        for dia in diameters:
            d = h - cover - dia / 2
            flexure = B.slab_flexure_need(demand.mu * 1e6, d, fc, fy, es)
            if flexure.too_small:
                need.too_small.append(f"{demand.part}: {flexure.note}")
                break
            target[dia] = max(target.get(dia, 0.0), flexure.area, as_min)
            if demand.mu_top > 0:
                top = B.slab_flexure_need(demand.mu_top * 1e6, d, fc, fy, es)
                need.top[dia] = max(need.top.get(dia, 0.0), top.area)
            if demand.vu > phi_vc(d, fc) * (1 + 1e-9):
                need.too_small.append(
                    f"{demand.part}: shear {demand.vu:.1f} kN/m above φVc "
                    f"{phi_vc(d, fc):.1f} kN/m without shear bars"
                )
                break
    return need


@dataclass
class StairPick:
    """A proposal, with the fields of ``saengine.design.proposal.Pick``."""

    reinforcement: dict[str, Any] | None
    label: str
    area: float
    utilisation: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    too_small: str = ""
    suggestion: str = ""


def propose(
    need: StairNeed,
    material_id: str,
    cover: float,
    diameters: Sequence[float] | None = None,
    min_spacing: float | None = None,
) -> StairPick:
    """Bars for a staircase type (``StairReinforcement`` JSON with the proposed ``top`` and
    ``landing`` meshes when needed): the mesh with the least steel per layer (bars.mesh_for),
    spacings in 25 mm steps within the spacing limits."""
    if diameters is None:
        diameters = B.diameters("slab")
    if min_spacing is None:
        min_spacing = B.min_slab_spacing()
    if need.too_small:
        return StairPick(
            None,
            "",
            0.0,
            too_small="; ".join(dict.fromkeys(need.too_small)),
            suggestion="try a thicker waist",
        )
    small = [min(diameters)]  # distribution bars: the smallest size (practice)
    layers: dict[str, Any] = {"material": material_id, "cover": cover}
    notes = []

    def sizes(required: dict[float, float]) -> tuple[float, ...]:
        # only the diameters the need was found for (d depends on the bar)
        return tuple(d for d in diameters if d in required) or tuple(sorted(required))

    picks = {
        "main": B.mesh_for(0.0, need.s_main, sizes(need.main), min_spacing, need.main),
        "distribution": B.mesh_for(need.distribution, need.s_dist, tuple(small), min_spacing),
    }
    if need.top:
        picks["top"] = B.mesh_for(0.0, need.s_main, sizes(need.top), min_spacing, need.top)
    if need.landing:
        picks["landing"] = B.mesh_for(
            0.0, need.s_landing, sizes(need.landing), min_spacing, need.landing
        )
    for name, mesh in picks.items():
        if mesh is None:
            return StairPick(
                None,
                "",
                0.0,
                too_small=f"{name}: bars closer than {min_spacing:g} mm needed",
                suggestion="try a thicker waist",
            )
        layers[name] = {"dia": mesh.dia, "spacing": mesh.spacing}
    label = ", ".join(f"{n} Ø{m.dia:g} @ {m.spacing:g}" for n, m in picks.items() if m)
    area = sum(m.area for m in picks.values() if m)
    notes.append(f"main bars at most {need.s_main:.0f} mm apart (min(3h, 450 mm))")
    return StairPick(layers, label, area, {}, notes)


# ─────────────────────────────────────── a stair, the report ───────────────────────────────────────


@dataclass
class StairResult:
    entry: dict[str, Any] | None  # design report element; None when not checked
    skip: str | None
    notes: list[str]
    need: StairNeed | None
    geometry: StairGeometry | None


def design_stair(
    stair_id: str,
    type_id: str,
    spec: StairSpec,
    rise: float,
    material: StairMaterial,
    loads: StairLoads,
    use: str | None = None,
    occupants: int | None = None,
    diameters: Sequence[float] | None = None,
) -> StairResult:
    """Geometry checks, demands, the checks of the entered bars and what is needed."""
    if diameters is None:
        diameters = B.diameters("slab")
    geometry = stair_geometry(spec, rise)
    checks, notes = geometry_checks(spec, geometry, use, occupants)
    demands = [flight_demand(f, spec, material, loads) for f in geometry.flights]
    by_name = {d.part: d for d in demands}
    demands += [landing_demand(lnd, by_name, spec, material, loads) for lnd in geometry.landings]
    cover = spec.bars.cover if spec.bars else _cover()
    need = need_of(demands, cover, material, diameters)
    parts = [
        {
            "name": d.part,
            "kind": d.kind,
            "span": round(d.span, 1),
            "h": d.h,
            "wu": round(d.wu, 3),
            "mu": round(d.mu, 3),
            "muTop": round(d.mu_top, 3),
            "vu": round(d.vu, 3),
            "combination": d.combination,
            "reactions": {
                c: {k: round(v, 3) for k, v in r.items()} for c, r in d.reactions.items()
            },
        }
        for d in demands
    ]
    flights = [
        {
            "name": f.name,
            "risers": f.risers,
            "riser": round(f.riser, 2),
            "going": f.going,
            "span": round(f.span, 1),
            "rule": f.rule,
            "meanThickness": round(f.mean_thickness(spec.waist), 2),
        }
        for f in geometry.flights
    ]
    if spec.bars is None:
        failed = [c["name"] for c in checks if not c["ok"] and not c["flag"]]
        if failed:
            notes.append(f"{stair_id}: geometry fails " + ", ".join(failed))
        return StairResult(None, "no reinforcement", notes, need, geometry)
    for demand in demands:
        checks += part_checks(demand, spec.bars, material)
    strength = [c for c in checks if not c["flag"]]
    entry = {
        "id": stair_id,
        "kind": "staircase",
        "type": type_id,
        "members": [],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "flights": flights,
        "parts": parts,
        "loads": {
            "finish": loads.finish,
            "live": loads.live,
            "unitWeight": round(material.unit_weight, 3),
            "source": loads.source,
        },
    }
    return StairResult(entry, None, notes, need, geometry)


def stair_report(
    building: Any,
    types: dict[str, Any],
    materials: dict[str, Any],
    settings: Any | None,
    collect: dict[str, Any] | None = None,
    diameters: Sequence[float] | None = None,
    default_rebar: str | None = None,
) -> dict[str, Any]:
    """The stairs of 06 BIM (``building.additions.stairs``) designed: ``{"elements",
    "skipped", "notes"}`` in the design report's format (``kind`` "staircase"). With
    ``collect``, ``collect["stairs"]`` gets per staircase type ``{"type", "object", "material",
    "need", "members"}`` for the design mode (:func:`propose`)."""
    if diameters is None:
        diameters = B.diameters("slab")
    levels = {s.id: s.elevation for s in building.stories}
    loads = loads_from_settings(settings)
    use = settings.occupancy.use if settings is not None else None
    elements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    by_type: dict[str, dict[str, Any]] = {}
    for stair in building.additions.stairs:
        t = types.get(stair.type)

        def skip(reason: str, stair: Any = stair) -> None:
            skipped.append(
                {"id": stair.id, "kind": "staircase", "type": stair.type, "reason": reason}
            )

        if t is None or getattr(t, "kind", None) != "staircase":
            skip(f"'{stair.type}' is not a staircase type")
            continue
        if stair.base not in levels or stair.top not in levels:
            skip("its base or top story is missing")
            continue
        rise = levels[stair.top] - levels[stair.base]
        if rise <= 0:
            skip("its top story is not above its base story")
            continue
        material = material_of(t, materials, default_rebar)
        if isinstance(material, str):
            skip(material)
            continue
        try:
            result = design_stair(
                stair.id, stair.type, spec_of(t), rise, material, loads, use, None, diameters
            )
        except ValueError as error:
            skip(str(error))
            continue
        notes += [n if n.startswith(stair.id) else f"{stair.id}: {n}" for n in result.notes]
        if result.entry is not None:
            elements.append(result.entry)
        else:
            skip(result.skip or "not designed")
        if result.need is not None:
            group = by_type.setdefault(
                stair.type,
                {
                    "type": stair.type,
                    "object": t,
                    "material": material,
                    "loads": loads,
                    "need": None,
                    "members": [],
                    "cases": [],
                },
            )
            group["need"] = (
                result.need if group["need"] is None else group["need"].merge(result.need)
            )
            group["members"].append(stair.id)
            group["cases"].append((spec_of(t), rise))
    if collect is not None:
        collect["stairs"] = list(by_type.values())
    if building.additions.stairs:
        notes.append(f"stair loads: {loads.source}; finish {loads.finish:g} kN/m² on plan")
    return {"elements": elements, "skipped": skipped, "notes": notes}


def proposal_entries(
    collected: list[dict[str, Any]],
    diameters: Sequence[float] | None = None,
    min_spacing: float | None = None,
) -> list[dict[str, Any]]:
    """Design-mode entries (the shape of ``saengine.design.proposal._entry``) per staircase
    type from ``collect["stairs"]`` of :func:`stair_report`."""
    if diameters is None:
        diameters = B.diameters("slab")
    if min_spacing is None:
        min_spacing = B.min_slab_spacing()
    from saengine.design.proposal import _same
    from saengine.design.proposal import bars_of as reported

    entries = []
    for group in collected:
        t, need = group["object"], group["need"]
        current = t.reinforcement.model_dump(exclude_none=True) if t.reinforcement else None
        material_id = t.reinforcement.material if t.reinforcement else group["material"].steel
        cover = t.reinforcement.cover if t.reinforcement else _cover()
        pick = propose(need, material_id, cover, diameters, min_spacing)
        if pick.reinforcement is None:
            pick.suggestion = thicker_waist(group, cover, diameters, min_spacing)
        status = "tooSmall" if pick.reinforcement is None else "ok"
        if status == "ok" and current is not None and _same(current, pick.reinforcement):
            status = "unchanged"
        entries.append(
            {
                "type": group["type"],
                "kind": "staircase",
                "name": t.name,
                "current": None if current is None else reported(current, _label(current)),
                "proposed": reported(pick.reinforcement, pick.label),
                "status": status,
                "governingMember": group["members"][0] if group["members"] else None,
                "members": group["members"],
                "demand": {
                    "main": {f"{k:g}": round(v, 1) for k, v in sorted(need.main.items())},
                    "top": {f"{k:g}": round(v, 1) for k, v in sorted(need.top.items())},
                    "landing": {f"{k:g}": round(v, 1) for k, v in sorted(need.landing.items())},
                    "distribution": round(need.distribution, 1),
                },
                "utilisation": {},
                "overDesigned": [],
                "overDesignedDetails": [],
                "tooSmall": None
                if pick.reinforcement is not None
                else {"reason": pick.too_small, "suggestion": pick.suggestion},
                "notes": pick.notes,
            }
        )
    return entries


#: How much thicker than its waist a staircase is tried for in the design mode [mm].
GROWTH = 150.0


def thicker_waist(
    group: dict[str, Any],
    cover: float,
    diameters: Sequence[float] | None = None,
    min_spacing: float | None = None,
) -> str:
    """The least waist, in 25 mm steps up to +150 mm, with which every stair of the type works
    (landings of no thickness of their own follow the waist)."""
    if diameters is None:
        diameters = B.diameters("slab")
    if min_spacing is None:
        min_spacing = B.min_slab_spacing()
    cases: list[tuple[StairSpec, float]] = group.get("cases", [])
    if not cases:
        return "try a thicker waist"
    material, loads = group["material"], group["loads"]
    waist = cases[0][0].waist
    step = 25.0
    while step <= GROWTH:
        need: StairNeed | None = None
        for spec, rise in cases:
            thicker = StairSpec(**{**spec.__dict__, "waist": spec.waist + step})
            geometry = stair_geometry(thicker, rise)
            demands = [flight_demand(f, thicker, material, loads) for f in geometry.flights]
            by_name = {d.part: d for d in demands}
            demands += [
                landing_demand(lnd, by_name, thicker, material, loads) for lnd in geometry.landings
            ]
            found = need_of(demands, cover, material, diameters)
            need = found if need is None else need.merge(found)
        if need is not None and propose(need, "", cover, diameters, min_spacing).reinforcement:
            return f"try a {waist + step:g} mm waist (+{step:g} mm)"
        step += 25.0
    return (
        f"no waist up to +{GROWTH:g} mm works: shorten the span (landings, a dog-legged "
        "arrangement or intermediate beams)"
    )


def _label(reinforcement: dict[str, Any]) -> str:
    return ", ".join(
        f"{n} Ø{m['dia']:g} @ {m['spacing']:g}"
        for n in ("main", "distribution", "top", "landing")
        if (m := reinforcement.get(n))
    )
