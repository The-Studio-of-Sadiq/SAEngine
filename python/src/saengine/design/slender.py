"""Slenderness of reinforced-concrete columns, designed for by moment magnification.

BNBC 2020 Part 6 Sec 6.3.10 (part 1 of the code, pp. 910-915; ACI 318's provisions, its
6.2.5 and 6.6.4) is followed clause by clause:

- Unsupported length lu (6.3.10.1.1): per bending direction, the column is cut at every joint
  where another member gives it lateral support in that direction (a beam or brace with a
  component along it, a slab, a wall in whose plane it lies, a support); a segment ending at
  a floor loses the depth of the beams along the direction (else the slab, else any beam) at
  its top: the clear height below the soffit. Radius of gyration r = 0.30 h (rectangle, h in
  the direction considered) or 0.25 D (circle) (6.3.10.1.2).
- Effective length factor k: from the Jackson and Moreland alignment charts (Figure 6.6.5),
  solved exactly (:func:`k_nonsway`, :func:`k_sway`), with ψ = Σ(EI/lc) of the columns over
  Σ(EI/l) of the beams in the plane at each end, the moments of inertia 0.70 Ig for columns
  and 0.35 Ig for beams (6.3.10.4.1, as 6.3.10.7.2 asks for k); a fixed support ψ = 1.0 by
  default (option), a pinned one or a joint without beams ψ = ∞ (taken as
  :data:`PSI_INFINITE`); lc and l are measured between the joints (a member's analysis pieces
  followed through the nodes where nothing else frames in), and a slab framing into a joint
  without a beam along that side counts as a flat plate at 0.25 Ig (its width the mean of
  the spans across, its l1 the span to the next column or wall). In nonsway storeys k = 1.0 by default (allowed by 6.3.10.6.3,
  conservative); the chart is an option. In sway storeys k is the chart's, never below 1.0
  (6.3.10.7.2). A segment ending at an intermediate brace or a wall in its plane is braced
  (k = 1, nonsway); one ending at an intermediate beam (a tie, plinth or landing beam) has
  its lu shortened but still sways with its storey (ψ at that joint).
- Sway or nonsway storey (6.3.10.5.2): Q = ΣPu Δo / (Vus lc) <= 0.05 is nonsway, per storey,
  direction (X, Y) and combination, from the analysis: ΣPu the vertical force and Vus the
  shear of the lateral load cases of the combination (W*, E*, R* cases) in the frame members
  and the walls (shells) crossing the storey's mid-height (a member with a node exactly there
  counted once), Δo the relative first-order displacement of the storey's floor levels under
  the lateral cases (the mean of each level's nodes, as the storey drifts of
  :func:`saengine.fem.ssi.storey_drifts`), times the drift factor: Δo is meant with the
  cracked stiffnesses of 6.3.10.4.1, so when the analysed model ran its lateral cases on the
  cracked sections (saengine.fem.second_order: the lateral cases carry cracked
  ``section_overrides``, or the model's own concrete frame sections are the cracked ones,
  :attr:`Model.lateral_cracked`; read from the model, not the current settings) the factor
  is 1.0; on gross sections it is the storey's cracked over gross drift (:meth:`Model.drift_factor`, the frames
  from the storey stiffness approximation, the walls' share of the shear at 1/0.35), or
  :attr:`SlenderOptions.drift_factor` as given; lc the storey height. A combination defines
  Q in a direction only when its shear there is a real share of the largest one and of its
  own shear across (:data:`MIN_SHEAR_SHARE`, :data:`ORTHOGONAL_SHARE`). A storey is sway
  when any combination's Q exceeds 0.05.
- Slenderness neglected (6.3.10.1): k lu / r <= 22 in sway storeys; <= 34 - 12 (M1/M2) <= 40
  in nonsway ones (M1/M2 positive in single curvature), per combination.
- Nonsway magnification (6.3.10.6): Mc = δns M2, δns = Cm / (1 - Pu / (0.75 Pc)) >= 1,
  Pc = π² EI / (k lu)², EI = 0.4 Ec Ig / (1 + βdns) (Eq. 6.6.22, the default: it does not
  depend on the bars, so the design mode's bar search keeps the same demand) or
  (0.2 Ec Ig + Es Ise) / (1 + βdns) (Eq. 6.6.21, option "bars"), βdns the factored sustained
  axial force (the dead load cases D and SD of the combination) over Pu; Cm = 0.6 + 0.4 M1/M2
  without transverse loads between the supports, 1.0 with them (a moment diagram that is not
  straight); M2 not less than M2,min = Pu (15 + 0.03 h) about each axis separately, with
  Cm = 1.0 when M2,min governs (6.3.10.6.5).
- Sway magnification (6.3.10.7): end moments M = Mns + δs Ms, Ms the moments of the lateral
  load cases of the combination; δs = 1 / (1 - Q) >= 1 (Eq. 6.6.27; above 1.5 the column needs
  a second-order analysis or Eq. 6.6.28, which is the option "sumPc":
  δs = 1 / (1 - ΣPu / (0.75 ΣPc)) over the storey's sway columns, each Pc with k from the
  sway chart and EI of 6.3.10.6.1 (the EI option over 1 + βdns of the combination), as BNBC
  6.3.10.7.4 (p 915) says; ACI 318-19 6.6.4.6.2 takes βds there instead, which BNBC does not).
  Along the length the nonsway procedure applies to the magnified end moments (6.3.10.2.2).
- Response spectrum combinations (saengine.fem.seismic_design, E = ± the envelope): the modal
  moments have no sign, so a column cannot be told to be in single or double curvature from
  them. SAEngine's rule (conservative, not a code clause): such a combination is taken in
  single curvature, M1/M2 = +|M1|/|M2| (nonsway limit 34 - 12 |M1/M2|), and Cm = 1.0.
  Their storey shear Vus in Q is the response spectrum's own (the modal storey shears
  combined like the drift), not the sum of the members' envelopes.
- With an elastic second-order analysis (P-Δ, option ``second_order="pDelta"``) the end
  moments already include the sway effects: δs = 1; the effects along the length are still
  magnified by δns (6.3.10.2.2).
- Limits: total moment with second-order effects <= 1.4 times the first-order moment
  (6.3.10.2.1, the first-order moment taken as max(M2, M2,min)); k lu / r <= 100 (ACI 318-19
  6.2.6: above it a nonlinear second-order analysis is required; BNBC has no such clause).

Units: mm, N, N·mm (the analysis model's m, N, N·m converted where read).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

NONSWAY_Q = 0.05
"""Stability index up to which a storey is nonsway (BNBC 6.3.10.5.2, Eq. 6.6.17)."""
SWAY_LIMIT = 22.0
"""k lu / r up to which slenderness is neglected in sway storeys (BNBC Eq. 6.6.13)."""
NONSWAY_CAP = 40.0
"""Cap of 34 - 12 M1/M2 for nonsway storeys (BNBC Eq. 6.6.14)."""
KLU_R_MAX = 100.0
"""k lu / r above which ACI 318-19 6.2.6 requires a nonlinear second-order analysis."""
DELTA_S_MAX = 1.5
"""δs = 1/(1 - Q) above which a second-order analysis (or Eq. 6.6.28) is required (6.3.10.7.3)."""
MOMENT_RATIO_MAX = 1.4
"""Second-order over first-order moment, at most (BNBC 6.3.10.2.1)."""
PHI_K = 0.75
"""The stiffness reduction factor of Eqs. 6.6.19 and 6.6.28."""
PSI_INFINITE = 1000.0
"""ψ taken for a pinned end or a joint without beams in the plane (∞ on the chart)."""
MIN_SHEAR_SHARE = 0.10
"""Q of a storey and direction is taken from the combinations whose storey shear there is at
least this share of the largest one."""
ORTHOGONAL_SHARE = 0.25
"""... and at least this share of the same combination's storey shear in the other direction
(a combination loading the other direction defines no Q here with its by-product shear and
drift; 100 % + 30 % orthogonal combinations still do)."""
CRACKED_COLUMN = 0.70
CRACKED_BEAM = 0.35
CRACKED_PLATE = 0.25
"""Flat plates and flat slabs (BNBC 6.3.10.4.1)."""
CRACKED_WALL = 0.35
"""Cracked walls (BNBC 6.3.10.4.1), taken for the walls' share of a storey's drift."""
PLATE_CONE = 0.3
"""A slab's span from a column runs to the nearest column (or wall node) within this offset
over the distance along the direction."""
SUSTAINED_CASES = frozenset({"D", "SD"})
"""Load cases whose factored axial force is sustained (βdns)."""


def is_lateral(code: str) -> bool:
    """Whether a load case code is lateral (sway moments Ms, storey shear): wind W*,
    earthquake E* and response-spectrum R* cases."""
    return code[:1] in ("E", "W", "R")


@dataclass
class SlenderOptions:
    """How slenderness is designed for (the project's settings; see the module notes)."""

    #: Nonsway k: "unity" (k = 1, BNBC 6.3.10.6.3) or "chart" (the alignment chart).
    effective_length: str = "unity"
    #: Sway magnifier: "Q" (δs = 1/(1 - Q), Eq. 6.6.27) or "sumPc" (Eq. 6.6.28).
    sway_magnifier: str = "Q"
    #: EI of Pc: "0.4EcIg" (Eq. 6.6.22) or "bars" ((0.2 Ec Ig + Es Ise), Eq. 6.6.21).
    stiffness: str = "0.4EcIg"
    #: "none" (first-order analysis: moment magnification) or "pDelta" (the analysis includes
    #: P-Δ: δs = 1, δns along the length still applies).
    second_order: str = "none"
    #: ψ of an end on a fixed support.
    fixed_psi: float = 1.0
    #: Multiplies the analysis's storey displacements Δo for Q (Q wants the cracked
    #: stiffnesses of 6.3.10.4.1): None (the default) is 1.0 when the analysed model ran its
    #: lateral cases on cracked sections (:attr:`Model.lateral_cracked`), else worked out per
    #: storey (:meth:`Model.drift_factor`); a number is used as given.
    drift_factor: float | None = None
    #: Whether the analysis model's concrete frame sections are already the cracked ones
    #: (Section stiffness ACI for every case: columns 0.70 Ig, beams 0.35 Ig in the model),
    #: which ψ takes back to gross before applying 6.3.10.4.1 once: None (the default) finds
    #: it per section from the model (:class:`Model`); True or False as given.
    model_cracked: bool | None = None

    @classmethod
    def of(cls, options: SlenderOptions | dict[str, Any] | None) -> SlenderOptions:
        """From the settings' camelCase keys (``effectiveLength``, ``swayMagnifier``,
        ``stiffness``, ``secondOrder``, ``fixedBasePsi``, ``driftFactor``) or this class."""
        if isinstance(options, SlenderOptions):
            return options
        options = options or {}
        result = cls()
        if options.get("effectiveLength") in ("unity", "chart"):
            result.effective_length = options["effectiveLength"]
        if options.get("swayMagnifier") in ("Q", "sumPc"):
            result.sway_magnifier = options["swayMagnifier"]
        if options.get("stiffness") in ("0.4EcIg", "bars"):
            result.stiffness = options["stiffness"]
        if options.get("secondOrder") in ("none", "pDelta"):
            result.second_order = options["secondOrder"]
        if isinstance(options.get("fixedBasePsi"), (int, float)) and options["fixedBasePsi"] >= 0:
            result.fixed_psi = float(options["fixedBasePsi"])
        drift = options.get("driftFactor")
        if isinstance(drift, (int, float)) and not isinstance(drift, bool) and drift > 0:
            result.drift_factor = float(drift)
        if isinstance(options.get("modelCracked"), bool):
            result.model_cracked = options["modelCracked"]
        return result


def options_from_settings(settings: Any) -> SlenderOptions:
    """The options from the project settings: ``analysis.slenderness`` (a model or dict with
    the camelCase keys of :meth:`SlenderOptions.of`) and ``analysis.secondOrder`` ("none" or
    "pDelta", which overrides the one in ``slenderness``); the defaults where absent."""
    analysis = getattr(settings, "analysis", None)
    raw = getattr(analysis, "slenderness", None)
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    values: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    second = getattr(analysis, "secondOrder", None)
    if isinstance(second, str):
        values["secondOrder"] = second
    # Whether the model's sections or its lateral cases are cracked (``analysis.stiffness``,
    # ``crackedFor``) is read from the analysed model itself (Model.lateral_cracked and the
    # per-section detection), not from these settings, which may have changed since the
    # analysis was run.
    values.pop("modelCracked", None)
    return SlenderOptions.of(values)


# ─────────────────────────────── effective length ───────────────────────────────


def _psi(psi: float) -> float:
    if not math.isfinite(psi):
        return PSI_INFINITE
    return min(max(psi, 1e-6), PSI_INFINITE)


def k_nonsway(psi_a: float, psi_b: float) -> float:
    """k of a braced column from the end restraints ψA, ψB: the nonsway alignment chart
    (BNBC Figure 6.6.5 (a)), the root in 0.5 <= k <= 1 of

    ψA ψB / 4 (π/k)² + (ψA + ψB)/2 (1 - (π/k) / tan(π/k)) + 2 tan(π/2k) / (π/k) - 1 = 0.
    """
    from scipy.optimize import brentq

    a, b = _psi(psi_a), _psi(psi_b)

    def f(x: float) -> float:
        return a * b / 4 * x * x + (a + b) / 2 * (1 - x / math.tan(x)) + 2 * math.tan(x / 2) / x - 1

    x = brentq(f, math.pi * (1 + 1e-9), 2 * math.pi * (1 - 1e-9), xtol=1e-12)
    return math.pi / x


def k_sway(psi_a: float, psi_b: float) -> float:
    """k of an unbraced column: the sway alignment chart (BNBC Figure 6.6.5 (b)), the root
    k >= 1 of (ψA ψB (π/k)² - 36) / (6 (ψA + ψB)) - (π/k) / tan(π/k) = 0."""
    from scipy.optimize import brentq

    a, b = _psi(psi_a), _psi(psi_b)

    def f(x: float) -> float:
        return (a * b * x * x - 36) / (6 * (a + b)) - x / math.tan(x)

    x = brentq(f, 1e-9, math.pi * (1 - 1e-9), xtol=1e-14)
    return max(1.0, math.pi / x)


# ─────────────────────────────── the magnifiers ───────────────────────────────


def nonsway_limit(m1_over_m2: float) -> float:
    """k lu / r up to which slenderness is neglected in a nonsway storey: 34 - 12 M1/M2, at
    most 40 (Eq. 6.6.14; M1/M2 positive in single curvature)."""
    return min(34 - 12 * m1_over_m2, NONSWAY_CAP)


def cm_factor(m1_over_m2: float, transverse: bool = False) -> float:
    """Cm = 0.6 + 0.4 M1/M2 (Eq. 6.6.23; M1/M2 positive in single curvature), 1.0 with
    transverse loads between the supports."""
    return 1.0 if transverse else 0.6 + 0.4 * m1_over_m2


def critical_load(ei: float, k: float, lu: float) -> float:
    """Pc = π² EI / (k lu)² (Eq. 6.6.20) [N, with EI in N·mm² and lu in mm]."""
    return math.pi**2 * ei / (k * lu) ** 2


def effective_ei(
    ec: float, ig: float, beta: float, es: float = 0.0, ise: float | None = None
) -> float:
    """EI of Pc: 0.4 Ec Ig / (1 + β) (Eq. 6.6.22), or (0.2 Ec Ig + Es Ise) / (1 + β)
    (Eq. 6.6.21) when ``ise`` is given; β at most 1 (6.3.10.6.2)."""
    beta = min(max(beta, 0.0), 1.0)
    if ise is None:
        return 0.4 * ec * ig / (1 + beta)
    return (0.2 * ec * ig + es * ise) / (1 + beta)


def delta_ns(cm: float, pu: float, pc: float) -> float:
    """δns = Cm / (1 - Pu / (0.75 Pc)) >= 1 (Eq. 6.6.19); infinite when Pu >= 0.75 Pc."""
    if pu <= 0:
        return 1.0
    if pu >= PHI_K * pc:
        return math.inf
    return max(cm / (1 - pu / (PHI_K * pc)), 1.0)


def delta_s_q(q: float) -> float:
    """δs = 1 / (1 - Q) >= 1 (Eq. 6.6.27); infinite when Q >= 1."""
    return math.inf if q >= 1 else max(1 / (1 - q), 1.0)


def delta_s_sum(sum_pu: float, sum_pc: float) -> float:
    """δs = 1 / (1 - ΣPu / (0.75 ΣPc)) >= 1 (Eq. 6.6.28); infinite when unstable."""
    if sum_pu <= 0:
        return 1.0
    if sum_pc <= 0 or sum_pu >= PHI_K * sum_pc:
        return math.inf
    return max(1 / (1 - sum_pu / (PHI_K * sum_pc)), 1.0)


def stability_index(sum_pu: float, delta_o: float, vus: float, lc: float) -> float:
    """Q = ΣPu Δo / (Vus lc) (Eq. 6.6.17)."""
    return sum_pu * abs(delta_o) / (abs(vus) * lc)


def minimum_moment(pu: float, h: float) -> float:
    """M2,min = Pu (15 + 0.03 h) [N·mm] (Eq. 6.6.24, h in mm)."""
    return max(pu, 0.0) * (15 + 0.03 * h)


# ─────────────────────────────── storeys ───────────────────────────────

_DIRECTIONS = {"X": np.array([1.0, 0.0, 0.0]), "Y": np.array([0.0, 1.0, 0.0])}


@dataclass
class Storey:
    """One storey in one direction: per combination ΣPu [N], Vus [N], Δo [m] and Q."""

    name: str
    bottom: float  # m
    top: float  # m
    direction: str
    sum_pu: list[float]
    vus: list[float]
    delta: list[float]  # m, the drift factor applied
    q: list[float | None]
    #: N, per combination the sway columns' ΣPc (Eq. 6.6.28, EI with that combination's
    #: βdns), filled by the context.
    sum_pc: list[float] = field(default_factory=list)
    factor: list[float] = field(default_factory=list)  # the drift factor per combination

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def q_max(self) -> tuple[float | None, int | None]:
        best: tuple[float | None, int | None] = (None, None)
        for c, q in enumerate(self.q):
            if q is not None and (best[0] is None or q > best[0]):
                best = (q, c)
        return best

    @property
    def sway(self) -> bool | None:
        q, _ = self.q_max
        return None if q is None else q > NONSWAY_Q

    def delta_s(self, c: int, method: str) -> float:
        q = self.q[c]
        if q is None:
            return 1.0
        if method == "sumPc":
            return delta_s_sum(self.sum_pu[c], self.sum_pc[c] if c < len(self.sum_pc) else 0.0)
        return delta_s_q(q)


def _global_force(piece: Any, rows: np.ndarray) -> np.ndarray:
    """The mean internal force of a piece in global axes [N], as the part above acts on the
    part below (whatever way the piece was drawn)."""
    mean = np.asarray(rows, dtype=float)[:, :3].mean(axis=0)
    up = 1.0 if piece.axes[0][2] >= 0 else -1.0
    return up * (mean @ piece.axes)


def _crosses(z_values: Any, mid: float) -> bool:
    """Whether a member spans the height ``mid``, half open (bottom <= mid < top), so that a
    column with a node exactly at mid-height is counted once (the piece above it)."""
    low, high = min(z_values), max(z_values)
    return low - 1e-6 <= mid < high - 1e-6


def _shell_cut(points: list[np.ndarray], rows: np.ndarray) -> np.ndarray:
    """The force [N, global] that the part of a vertical shell above a horizontal cut through
    it exerts on the part below: its mean membrane and transverse shear forces per length
    (N11 N22 N12 . . . Q13 Q23, the shell's axes) on the cut's normal (up, in its plane),
    times its horizontal width."""
    from saengine.design.slab import shell_axes

    e1, e2, e3 = shell_axes(points)
    m = np.asarray(rows, dtype=float).reshape(-1, 8).mean(axis=0)
    up = np.array([0.0, 0.0, 1.0])
    n = up - (up @ e3) * e3
    size = float(np.linalg.norm(n))
    if size < 1e-9:
        return np.zeros(3)
    n = n / size
    s = (
        m[0] * np.outer(e1, e1)
        + m[1] * np.outer(e2, e2)
        + m[2] * (np.outer(e1, e2) + np.outer(e2, e1))
    )
    traction = s @ n + (m[6] * float(e1 @ n) + m[7] * float(e2 @ n)) * e3
    across = np.cross(e3, n)
    width = float(np.ptp([p @ across for p in points]))
    return traction * width


def storeys(
    project: dict[str, Any],
    building: Any,
    pieces: dict[str, list[Any]],
    combinations: list[str],
    lateral_disp: list[dict[int, np.ndarray]],
    drift_factor: float | None = 1 / CRACKED_COLUMN,
    shells: dict[int, tuple[list[np.ndarray], list[np.ndarray]]] | None = None,
    model: Model | None = None,
    storey_shear: list[Any] | None = None,
) -> list[Storey]:
    """The storeys of the building per direction with their stability index per combination.

    ``pieces``: every member's analysis pieces with their combined forces and their lateral
    parts (``sway``); ``lateral_disp``: per combination the node displacements of its lateral
    part (global, m); ``shells``: per analysis shell id its forces per combination and their
    lateral parts (rows of N11 .. Q23), for the walls' share of ΣPu and Vus (6.3.10.5.2: the
    storey's total vertical load and shear). ``drift_factor`` None: per storey from ``model``
    (:meth:`Model.drift_factor`), the walls' share of the shear at 1/0.35. Storeys are the
    pairs of consecutive floor levels with nodes. ``storey_shear``: per combination None, or
    for a response spectrum combination a function of the cut height [m] giving the storey
    shear of its earthquake [N, global, >= 0] (the peak of the storey's sum, consistent with
    its combined drift): Vus is then that, not the sum of the members' signed envelopes,
    whose uniform sign per local component partly cancels."""
    z_of = {int(n["id"]): float(n["coords"][2]) for n in project.get("nodes", [])}
    xyz = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    levels = sorted({round(float(s.elevation) * 1e-3, 6) for s in building.stories})
    present = [lv for lv in levels if any(abs(z - lv) <= 1e-3 for z in z_of.values())]
    names = {round(float(s.elevation) * 1e-3, 6): s.name or s.id for s in building.stories}
    frames = [p for own in pieces.values() for p in own if p.start is not None]
    walls: list[tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]] = []
    for e in project.get("elements", []):
        found = (shells or {}).get(int(e["id"])) if e.get("type") == "Shell" else None
        nodes = [int(n) for n in e.get("nodes", [])]
        if found is None or len(nodes) < 3 or any(n not in xyz for n in nodes):
            continue
        points = [xyz[n] for n in nodes]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        if np.linalg.norm(normal) > 0 and abs(normal[2]) < 0.1 * np.linalg.norm(normal):
            walls.append((points, found[0], found[1]))
    n_comb = len(combinations)
    result: list[Storey] = []
    for z0, z1 in itertools.pairwise(present):
        if z1 - z0 <= 1e-3:
            continue
        mid = (z0 + z1) / 2
        crossing = [
            p for p in frames if _crosses((p.start[2], p.end[2]), mid) and abs(p.axes[0][2]) > 0.1
        ]
        cut = [w for w in walls if _crosses([p[2] for p in w[0]], mid)]
        on = {lv: [n for n, z in z_of.items() if abs(z - lv) <= 1e-3] for lv in (z0, z1)}
        # Per combination: ΣPu, and the lateral cases' storey shear of the frames and walls.
        pu_of, frame_v, wall_v = [], [], []
        for c in range(n_comb):
            pu, fv, wv = 0.0, np.zeros(3), np.zeros(3)
            for p in crossing:
                pu -= float(_global_force(p, p.forces[c])[2])
                if p.sway is not None:
                    fv = fv + _global_force(p, p.sway[c])
            for points, total, sway in cut:
                if c < len(total):
                    pu -= float(_shell_cut(points, total[c])[2])
                if c < len(sway):
                    wv = wv + _shell_cut(points, sway[c])
            pu_of.append(pu)
            frame_v.append(fv)
            wall_v.append(wv)
        # The storey shear of each combination's lateral part (global): the members' sum, or a
        # response spectrum combination's own storey shear.
        total_v = []
        for c in range(n_comb):
            fn = storey_shear[c] if storey_shear and c < len(storey_shear) else None
            total_v.append(
                np.abs(np.asarray(fn(mid), dtype=float)) if fn else frame_v[c] + wall_v[c]
            )
        both = [max(abs(float(v[0])), abs(float(v[1]))) for v in total_v]
        for direction, unit in _DIRECTIONS.items():
            axis = 0 if direction == "X" else 1
            frame_factor = None
            if drift_factor is None and model is not None:
                frame_factor = model.drift_factor(z0, z1, unit, [p.id for p in crossing])
            sum_pu, vus, delta, qs, factors = [], [], [], [], []
            for c in range(n_comb):
                shear = float(total_v[c] @ unit)
                if drift_factor is not None:
                    factor = drift_factor
                elif frame_factor is None:
                    factor = 1 / CRACKED_COLUMN
                else:
                    vf, vw = abs(float(frame_v[c] @ unit)), abs(float(wall_v[c] @ unit))
                    factor = (
                        (vf * frame_factor + vw / CRACKED_WALL) / (vf + vw)
                        if vf + vw > 0
                        else frame_factor
                    )
                disp = lateral_disp[c] if c < len(lateral_disp) else {}
                d = (_mean(disp, on[z1], axis) - _mean(disp, on[z0], axis)) * factor
                pu = pu_of[c]
                sum_pu.append(pu)
                vus.append(abs(shear))
                delta.append(d)
                factors.append(factor)
                usable = abs(shear) > 1.0 and abs(d) > 1e-12 and pu > 0
                # A combination loading the storey sideways mostly in the other direction
                # (its shear here a by-product, e.g. of torsion) does not define Q.
                usable = usable and abs(shear) >= ORTHOGONAL_SHARE * both[c]
                qs.append(stability_index(pu, d, shear, z1 - z0) if usable else None)
            largest = max(vus, default=0.0)
            qs = [
                q if v >= MIN_SHEAR_SHARE * largest else None for q, v in zip(qs, vus, strict=True)
            ]
            label = f"{names.get(z0, f'{z0:g} m')} to {names.get(z1, f'{z1:g} m')}"
            result.append(Storey(label, z0, z1, direction, sum_pu, vus, delta, qs, factor=factors))
    return result


def _mean(disp: dict[int, np.ndarray], nodes: list[int], axis: int) -> float:
    """The mean displacement of a level's nodes along a global axis (0 where not given)."""
    values = [float(disp[n][axis]) if n in disp else 0.0 for n in nodes]
    return sum(values) / len(values) if values else 0.0


def storey_rows(found: list[Storey], combinations: list[str], method: str) -> list[dict]:
    """The storeys for the report: ``{"storey", "bottom", "top" (m), "direction", "Q",
    "combination", "sumPu", "Vus" (kN), "deltaO" (mm, factored), "driftFactor", "lc" (m),
    "sway", "deltaS"}`` at the
    combination with the largest Q (None where no combination loads the storey sideways)."""
    rows = []
    for s in found:
        q, c = s.q_max
        rows.append(
            {
                "storey": s.name,
                "bottom": round(s.bottom, 4),
                "top": round(s.top, 4),
                "direction": s.direction,
                "Q": None if q is None else round(q, 4),
                "combination": None if c is None else combinations[c],
                "sumPu": None if c is None else round(s.sum_pu[c] / 1e3, 1),
                "Vus": None if c is None else round(s.vus[c] / 1e3, 1),
                "deltaO": None if c is None else round(abs(s.delta[c]) * 1e3, 3),
                "driftFactor": None if c is None or c >= len(s.factor) else round(s.factor[c], 3),
                "lc": round(s.height, 4),
                "sway": s.sway,
                "deltaS": None if c is None else _round(s.delta_s(c, method), 3),
            }
        )
    return rows


def _round(value: float, digits: int) -> float | None:
    return round(value, digits) if math.isfinite(value) else None


# ─────────────────────────────── the model around a column ───────────────────────────────


@dataclass
class _Frame:
    id: int
    source: str
    nodes: tuple[int, int]
    axes: np.ndarray
    e: float  # N/m²
    iy: float  # m⁴
    iz: float
    length: float  # m, the analysis element's


@dataclass
class _Shell:
    source: str
    normal: np.ndarray
    centroid: np.ndarray  # m
    e: float = 0.0  # N/m²
    h: float = 0.0  # m, thickness


@dataclass
class JointStiffness:
    """The members' flexural stiffness at a joint for sway along a direction, gross (E I / l
    [N·m]): the columns (lc to the next joints), the beams (l to the next joints) and the
    slabs framing in as flat plates; and the beams and slabs at their cracked 0.35 Ig and
    0.25 Ig (6.3.10.4.1)."""

    columns: float = 0.0
    beams: float = 0.0
    slabs: float = 0.0

    @property
    def flexural_cracked(self) -> float:
        return CRACKED_BEAM * self.beams + CRACKED_PLATE * self.slabs


class Model:
    """What slenderness needs of the analysis model and the building: the members at each
    node, their stiffness, the beam depths and slab thicknesses, the supports."""

    def __init__(
        self,
        project: dict[str, Any],
        building: Any,
        types: dict[str, Any],
        cracked: bool | None = None,
        mats: dict[str, Any] | None = None,
    ) -> None:
        """``cracked``: whether the model's concrete frame sections are the cracked ones of
        saengine.fem.second_order (columns 0.70 Ig, beams 0.35 Ig, Section stiffness ACI for
        every case); those are taken back to gross here, the factors of 6.3.10.4.1 being
        applied where ψ and the drift need them. None (the default) finds it per section from
        the model: an ``ElasticBeamColumn`` on an ``ElasticSection`` of a building member whose
        object type is concrete or masonry (as saengine.fem.derive passes them to
        second_order), whose section has the profile's gross area and whose moments of
        inertia are 0.70 (a column) or 0.35 (a beam) times the profile's. True: every such
        concrete frame (a member of unknown material when E <= 50 GPa) is taken as cracked;
        False: none.

        :attr:`lateral_cracked`: whether the model ran its lateral static cases on cracked
        sections (they carry cracked ``section_overrides``, crackedFor "lateral", or the frame
        sections themselves were found cracked), so that Δo is the cracked drift."""
        from saengine.fem.derive import local_axes
        from saengine.fem.second_order import CONCRETE_E_MAX, VERTICAL
        from saengine.library.bim import AreaElement, BeamElement, MemberElement, SlabElement

        owners = {e.id: e for e in building.elements}
        additions = getattr(building, "additions", None)
        for addition in getattr(additions, "members", []) or []:
            owners.setdefault(addition.id, addition)

        def concrete_type(source: str) -> tuple[bool | None, Any]:
            """(concrete or masonry: True/False, None when unknown; the object type)."""
            owner = owners.get(source)
            object_type = types.get(owner.type) if owner is not None else None
            material = (mats or {}).get(getattr(object_type, "material", None))
            if material is None:
                return None, object_type
            category = getattr(material.category, "value", material.category)
            return category in ("concrete", "masonry"), object_type

        def gross_factor(
            element: dict[str, Any], section: dict[str, Any], column: bool, e_mod: float
        ) -> float:
            """1 / the cracked factor the model's section carries (1.0 when gross)."""
            if cracked is False or element.get("type") != "ElasticBeamColumn":
                return 1.0
            if section.get("type", "ElasticSection") != "ElasticSection":
                return 1.0
            if "/embed" in str(element.get("name", "")) or str(section.get("name", "")).endswith(
                "embedding strut"
            ):
                return 1.0
            factor = CRACKED_COLUMN if column else CRACKED_BEAM
            source = (element.get("name") or str(element["id"])).split("#")[0]
            is_concrete, object_type = concrete_type(source)
            if cracked is True:
                if is_concrete is False or (
                    is_concrete is None and not 0 < e_mod <= CONCRETE_E_MAX
                ):
                    return 1.0
                return 1 / factor
            # Detect: the profile's gross properties against the section's.
            if not is_concrete or not hasattr(object_type, "profile"):
                return 1.0
            from saengine.library.sections import section_properties

            try:
                props = section_properties(object_type.profile)
            except Exception:  # noqa: BLE001 - a profile without properties: left as it is
                return 1.0
            area, i1, i2 = props.area * 1e-6, props.ixx * 1e-12, props.iyy * 1e-12
            a, iy, iz = (float(section.get(k) or 0.0) for k in ("A", "Iy", "Iz"))
            if area <= 0 or i1 <= 0 or i2 <= 0 or iy <= 0 or iz <= 0:
                return 1.0
            if abs(a / area - 1) > 0.02:
                return 1.0
            measured = math.sqrt(iy * iz / (i1 * i2))  # the factor, whatever the axes' order
            return 1 / factor if abs(measured / factor - 1) <= 0.02 else 1.0

        self.coords = {
            int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])
        }
        self.restraint = {
            int(n["id"]): list(n.get("restraint") or [False] * 6) for n in project.get("nodes", [])
        }
        sections = {s["id"]: s for s in project.get("sections", [])}
        self.frames: dict[int, _Frame] = {}
        self.frames_at: dict[int, list[_Frame]] = {}
        self.shells_at: dict[int, list[_Shell]] = {}
        #: Per level (mm) the nodes of columns and walls: where slab spans end.
        self.vertical_nodes: dict[int, set[int]] = {}
        #: Per level (mm) the nodes of columns alone.
        self.column_nodes: dict[int, set[int]] = {}
        #: The frame elements whose cracked section was taken back to gross.
        self.cracked_frames = 0
        for e in project.get("elements", []):
            nodes = [int(n) for n in e.get("nodes", [])]
            if any(n not in self.coords for n in nodes):
                continue
            source = (e.get("name") or str(e["id"])).split("#")[0]
            section = sections.get(e.get("section_id"), {})
            if e.get("type") == "Shell" and len(nodes) >= 3:
                p = [self.coords[n] for n in nodes]
                normal = np.cross(p[1] - p[0], p[2] - p[0])
                size = float(np.linalg.norm(normal))
                if size > 0:
                    shell = _Shell(
                        source,
                        normal / size,
                        sum(p) / len(p),
                        float(section.get("E") or 0.0),
                        float(section.get("h") or 0.0),
                    )
                    for n in nodes:
                        self.shells_at.setdefault(n, []).append(shell)
                    if abs(float(shell.normal[2])) < 0.1:  # a wall
                        for n in nodes:
                            self._add_vertical(n, wall=True)
                continue
            if len(nodes) != 2 or e.get("type") == "Solid":
                continue
            a, b = self.coords[nodes[0]], self.coords[nodes[1]]
            length = float(np.linalg.norm(b - a))
            if length < 1e-9:
                continue
            e_mod = float(section.get("E") or 0.0)
            column = abs(float(b[2] - a[2])) / length >= VERTICAL
            gross = gross_factor(e, section, column, e_mod)
            if gross != 1.0:
                self.cracked_frames += 1
            frame = _Frame(
                int(e["id"]),
                source,
                (nodes[0], nodes[1]),
                np.array(local_axes(a, b)),
                e_mod,
                float(section.get("Iy") or 0.0) * gross,
                float(section.get("Iz") or 0.0) * gross,
                length,
            )
            self.frames[frame.id] = frame
            for n in nodes:
                self.frames_at.setdefault(n, []).append(frame)
                if abs(float(frame.axes[0][2])) >= 0.9:
                    self._add_vertical(n, wall=False)
        self.lateral_cracked = self.cracked_frames > 0 or any(
            a.get("type") == "Static"
            and a.get("section_overrides")
            and is_lateral(str(a.get("name", "")).split(":")[0].strip())
            for a in project.get("analyses", [])
        )
        # Beam depths and slab thicknesses [mm] by building element id.
        self.depth: dict[str, float] = {}
        self.thickness: dict[str, float] = {}
        for element in building.elements:
            object_type = types.get(element.type)
            if isinstance(element, (BeamElement, MemberElement)):
                profile = getattr(object_type, "profile", None)
                depth = getattr(profile, "yDim", None) or (
                    2 * profile.radius if hasattr(profile, "radius") else None
                )
                if depth and getattr(object_type, "kind", "") == "beam":
                    self.depth[element.id] = float(depth)
            elif isinstance(element, (SlabElement, AreaElement)):
                thickness = getattr(object_type, "thickness", None)
                if thickness and getattr(object_type, "kind", "") == "slab":
                    self.thickness[element.id] = float(thickness)

    def _add_vertical(self, node: int, wall: bool) -> None:
        level = round(float(self.coords[node][2]) * 1e3)
        self.vertical_nodes.setdefault(level, set()).add(node)
        if not wall:
            self.column_nodes.setdefault(level, set()).add(node)

    # ── lateral support ──

    def supports(
        self, node: int, member: str, unit: np.ndarray, axis: np.ndarray | None = None
    ) -> list[str]:
        """What gives the member (along ``axis``) lateral support in direction ``unit`` at
        ``node``: other frame members with a component along it that are not in line with the
        member, plates in whose plane it lies, a support."""
        return [name for name, _ in self._supports(node, member, unit, axis)]

    def _supports(
        self, node: int, member: str, unit: np.ndarray, axis: np.ndarray | None
    ) -> list[tuple[str, str]]:
        """:meth:`supports` with what each is: "support", "beam" (a horizontal frame member),
        "brace" (an inclined one) or "plate"."""
        found: list[tuple[str, str]] = []
        restraint = self.restraint.get(node, [False] * 6)
        if any(restraint[:3]):
            found.append(("support", "support"))
        for f in self.frames_at.get(node, []):
            in_line = axis is not None and abs(float(f.axes[0] @ axis)) > 0.99
            if f.source != member and not in_line and abs(float(f.axes[0] @ unit)) > 0.1:
                kind = "beam" if abs(float(f.axes[0][2])) <= 0.1 else "brace"
                found.append((f.source, kind))
        for s in self.shells_at.get(node, []):
            if abs(float(s.normal @ unit)) < 0.9:
                found.append((s.source, "plate"))
        return list(dict.fromkeys(found))

    def framed_joint(
        self, node: int, member: str, unit: np.ndarray, axis: np.ndarray | None
    ) -> bool:
        """Whether a column joint between floor levels is supported in direction ``unit`` by
        beams alone (a tie, plinth or landing beam): such a beam shortens lu but does not stop
        the storey from swaying (6.3.10.7), unlike a brace or a wall in the plane."""
        kinds = {kind for _, kind in self._supports(node, member, unit, axis)}
        return kinds == {"beam"}

    def clear_depth(self, node: int, unit: np.ndarray) -> float:
        """Depth [mm] taken off a column's length below a floor joint (6.3.10.1.1): the deepest
        beam along ``unit``, else the slab, else any beam framing in."""
        along, other = [], []
        for f in self.frames_at.get(node, []):
            depth = self.depth.get(f.source)
            if depth is None or abs(float(f.axes[0][2])) > 0.1:
                continue
            (along if abs(float(f.axes[0] @ unit)) >= 0.5 else other).append(depth)
        slabs = [
            self.thickness[s.source]
            for s in self.shells_at.get(node, [])
            if s.source in self.thickness and abs(float(s.normal[2])) > 0.9
        ]
        for found in (along, slabs, other):
            if found:
                return max(found)
        return 0.0

    # ── restraint at the joints (ψ) ──

    def _is_joint(self, node: int, frame: _Frame) -> bool:
        """Whether a node along a member is a joint: a support, or another member framing in
        (not the member's own next piece in line). Mesh nodes of slabs and walls are not."""
        if any(self.restraint.get(node, [False] * 6)[:3]):
            return True
        for f in self.frames_at.get(node, []):
            if f.id == frame.id:
                continue
            if f.source != frame.source or abs(float(f.axes[0] @ frame.axes[0])) < 0.99:
                return True
        return False

    def chain(self, node: int, frame: _Frame) -> tuple[list[_Frame], float]:
        """The pieces of a member from the joint ``node`` along ``frame`` to the next joint,
        and their centre-to-centre length [m] (Figure 6.6.5's lc and l): followed through the
        nodes where nothing else frames in, so a column cut into several elements, or one
        element spanning several storeys, gets its length between the joints."""
        found, total, at, current = [], 0.0, node, frame
        for _ in range(100_000):
            found.append(current)
            other = current.nodes[1] if current.nodes[0] == at else current.nodes[0]
            total += current.length
            if self._is_joint(other, current):
                break
            nxt = [
                f
                for f in self.frames_at.get(other, [])
                if f.id != current.id and f.source == current.source
            ]
            if len(nxt) != 1:
                break
            at, current = other, nxt[0]
        return found, total

    def joint_length(self, node: int, frame: _Frame) -> float:
        """The length [m] of :meth:`chain`."""
        return self.chain(node, frame)[1]

    def _nearest(self, at: np.ndarray, along: np.ndarray, across: np.ndarray) -> float | None:
        """Distance [m] along ``along`` to the nearest column or wall node at the level of
        ``at`` within :data:`PLATE_CONE` of the line."""
        best = None
        for n in self.vertical_nodes.get(round(float(at[2]) * 1e3), ()):
            v = self.coords[n] - at
            d = float(v @ along)
            if d > 0.05 and abs(float(v @ across)) <= PLATE_CONE * d and (best is None or d < best):
                best = d
        return best

    def _slab_stiffness(self, node: int, unit: np.ndarray) -> float:
        """Σ E Ig / l [N·m] of the slabs framing into a column joint as flat plates, on each
        side along ``unit`` without a beam: the slab-beam l1 to the next column (or wall) along
        it, its width the mean of the spans across (half of each side's; l1 when there is
        none), Ig = b h³ / 12."""
        slabs = [
            s
            for s in self.shells_at.get(node, [])
            if abs(float(s.normal[2])) > 0.9 and s.e > 0 and s.h > 0
        ]
        if not slabs:
            return 0.0
        at = self.coords[node]
        across = np.array([-unit[1], unit[0], 0.0])
        total = 0.0
        for sign in (1.0, -1.0):
            d = sign * unit
            side = [s for s in slabs if float((s.centroid - at) @ d) > 1e-6]
            if not side:
                continue
            beam = False
            for f in self.frames_at.get(node, []):
                if abs(float(f.axes[0][2])) > 0.1:
                    continue
                other = self.coords[f.nodes[1] if f.nodes[0] == node else f.nodes[0]] - at
                if float(other @ d) > 0.5 * float(np.linalg.norm(other)):
                    beam = True
            if beam:  # the slab is the beam's flange
                continue
            l1 = self._nearest(at, d, across)
            if l1 is None:  # a cantilever: no restraint taken
                continue
            spans = [self._nearest(at, s * across, d) for s in (1.0, -1.0)]
            widths = [w for w in spans if w is not None]
            width = sum(w / 2 for w in widths) if widths else l1
            h = max(s.h for s in side)
            total += side[0].e * width * h**3 / 12 / l1
        return total

    def joint(self, node: int, unit: np.ndarray) -> JointStiffness:
        """The gross stiffness of the members at a joint for sway along ``unit``: columns
        bending for a deflection along it, beams weighted by the square of their component
        along it (bending in their vertical plane), slabs as flat plates."""
        result = JointStiffness()
        for f in self.frames_at.get(node, []):
            if f.e <= 0:
                continue
            length = self.joint_length(node, f)
            if length <= 0:
                continue
            x, y, z = f.axes
            if abs(float(x[2])) >= 0.9:  # a column
                inertia = f.iz * float(y @ unit) ** 2 + f.iy * float(z @ unit) ** 2
                result.columns += f.e * inertia / length
            elif abs(float(x[2])) <= 0.1:  # a beam: bending in its vertical plane (about y)
                result.beams += f.e * f.iy * float(x @ unit) ** 2 / length
        result.slabs = self._slab_stiffness(node, unit)
        return result

    def psi(self, node: int, unit: np.ndarray, fixed_psi: float) -> tuple[float, str]:
        """ψ at a column end for sway along ``unit``: Σ 0.70 EI/lc of the columns over
        Σ EI/l of the flexural members, beams at 0.35 Ig and flat plates at 0.25 Ig
        (6.3.10.4.1); with what it is ("fixed support", "pinned", "no beams", "flat plate"
        or "")."""
        restraint = self.restraint.get(node, [False] * 6)
        if all(restraint):
            return fixed_psi, "fixed support"
        if all(restraint[:3]):
            return PSI_INFINITE, "pinned"
        j = self.joint(node, unit)
        flexural = j.flexural_cracked
        if flexural <= 0:
            return PSI_INFINITE, "no beams"
        note = "flat plate" if j.beams <= 0 else ""
        return CRACKED_COLUMN * j.columns / flexural, note

    # ── the cracked storey drift ──

    def drift_factor(self, z0: float, z1: float, unit: np.ndarray, columns: list[int]) -> float:
        """Cracked over gross storey drift of the frames of a storey (z0 to z1, m) for sway
        along ``unit``, by the storey stiffness approximation Δ ∝ 1/ΣKc + (1/ΣKb,bottom +
        1/ΣKb,top)/2 (K = E I / l of the columns crossing it and of the floors' beams and
        flat plates, a fixed base's term 0): the columns at 0.70 Ig, the beams at 0.35 Ig and
        the flat plates at 0.25 Ig (6.3.10.4.1), so ``(1/(0.70 ΣKc) + B_cracked) / (1/ΣKc +
        B_gross)``, between 1/0.70 and 1/0.25. 1/0.35 when the storey has no frame columns or
        a floor without beams or slabs."""
        h = z1 - z0
        kc = 0.0
        for i in columns:
            f = self.frames.get(i)
            if f is None or f.e <= 0 or abs(float(f.axes[0][2])) < 0.9:
                continue
            _, y, z = f.axes
            kc += f.e * (f.iz * float(y @ unit) ** 2 + f.iy * float(z @ unit) ** 2) / h
        if kc <= 0:
            return 1 / CRACKED_WALL
        gross, cracked = [], []
        for level in (z0, z1):
            nodes = self.column_nodes.get(round(level * 1e3), set())
            if nodes and all(all(self.restraint.get(n, [False] * 6)) for n in nodes):
                gross.append(0.0)
                cracked.append(0.0)
                continue
            beams = slabs = 0.0
            seen: set[int] = set()
            for n in nodes:
                for f in self.frames_at.get(n, []):
                    if f.id in seen or f.e <= 0 or abs(float(f.axes[0][2])) > 0.1:
                        continue
                    pieces, span = self.chain(n, f)
                    seen.update(p.id for p in pieces)  # each span once
                    if span > 0:
                        beams += f.e * f.iy * float(f.axes[0] @ unit) ** 2 / span
                slabs += self._slab_stiffness(n, unit) / 2  # a panel from both its columns
            if beams + slabs <= 0:
                return 1 / CRACKED_BEAM
            gross.append(1 / (beams + slabs))
            cracked.append(1 / (CRACKED_BEAM * beams + CRACKED_PLATE * slabs))
        b_gross, b_cracked = sum(gross) / 2, sum(cracked) / 2
        factor = (1 / (CRACKED_COLUMN * kc) + b_cracked) / (1 / kc + b_gross)
        return min(max(factor, 1 / CRACKED_COLUMN), 1 / CRACKED_PLATE)


# ─────────────────────────────── one column ───────────────────────────────


@dataclass
class Segment:
    """A length of a column between lateral supports in one direction."""

    pieces: list[Any]  # ordered from the bottom
    lc: float  # mm, centre-to-centre length
    lu: float  # mm, unsupported length
    #: Both ends at floor levels, supports or beam joints (a tie, plinth or landing beam):
    #: the segment sways with its storey. Else it ends at a brace or a wall in the plane
    #: between the floors, which braces it (k = 1, nonsway).
    framed: bool
    k_ns: float
    k_s: float | None
    psi: tuple[float, float] | None
    psi_notes: tuple[str, str] = ("", "")
    braced_by: list[str] = field(default_factory=list)
    storey: Storey | None = None


def _key(xyz: Any) -> tuple[int, int, int]:
    """A node position rounded to 0.01 mm, for looking nodes up by their coordinates [m]."""
    return (round(float(xyz[0]) * 1e5), round(float(xyz[1]) * 1e5), round(float(xyz[2]) * 1e5))


def _is_vertical(piece: Any) -> bool:
    return abs(float(piece.axes[0][2])) >= 0.9


@dataclass
class AxisResult:
    """The slenderness of a column for bending about one profile axis."""

    axis: str  # "x" (Mx, about the width) or "y"
    direction: str  # "X" or "Y": the sway direction
    check: dict[str, Any]
    #: Per combination: the magnified moment with M2,min and without it [N·mm], and δs.
    mc: list[float]
    mc_no_min: list[float]
    delta_s: list[float]
    segment_of: dict[int, Segment]  # piece id -> segment
    #: Per combination: whether a segment is designed for slenderness (not neglected).
    magnified: list[bool] = field(default_factory=list)


@dataclass
class ColumnSlenderness:
    """A column's slenderness: per axis the check and the magnified moments, and the demand
    points the strength check takes (station points with the sway moments magnified, then
    the moments magnified along the length)."""

    axes: list[AxisResult]
    points: list[tuple[float, float, float, str, str]]  # Pu, |Mux|, |Muy|, combination, where

    @property
    def checks(self) -> list[dict[str, Any]]:
        return [a.check for a in self.axes]


class SlenderContext:
    """Slenderness of the columns of one analysed building (see the module notes)."""

    def __init__(
        self,
        project: dict[str, Any],
        building: Any,
        types: dict[str, Any],
        mats: dict[str, Any],
        pieces: dict[str, list[Any]],
        combinations: list[str],
        lateral_disp: list[dict[int, np.ndarray]],
        options: SlenderOptions | dict[str, Any] | None = None,
        shells: dict[int, tuple[list[np.ndarray], list[np.ndarray]]] | None = None,
        spectrum: list[bool] | None = None,
        storey_shear: list[Any] | None = None,
    ) -> None:
        """``shells``: per analysis shell id its forces per combination and their lateral
        parts (rows of N11 .. Q23), so that the walls count in each storey's ΣPu and Vus.
        ``spectrum``: per combination whether its earthquake is the response spectrum's
        envelope (± E, no sign: single curvature and Cm = 1.0, see the module notes).
        ``storey_shear``: per combination None or its response spectrum storey shear function
        (:func:`storeys`, ``extra["storeyShear"]`` of saengine.fem.seismic_design.design_demands)."""
        self.options = SlenderOptions.of(options)
        self.combinations = combinations
        self.spectrum = [bool(s) for s in (spectrum or [])]
        self.model = Model(project, building, types, self.options.model_cracked, mats)
        self.levels = sorted({round(float(s.elevation) * 1e-3, 6) for s in building.stories})
        drift = self.options.drift_factor
        if drift is None and self.model.lateral_cracked:
            drift = 1.0  # Δo is already the cracked drift
        self.storeys = storeys(
            project,
            building,
            pieces,
            combinations,
            lateral_disp,
            drift,
            shells,
            self.model,
            storey_shear,
        )
        self.types, self.mats, self.pieces = types, mats, pieces
        self._segments: dict[tuple[str, str], list[Segment]] = {}
        self._nodes = {_key(at): node for node, at in self.model.coords.items()}
        if self.options.sway_magnifier == "sumPc":
            self._sum_pc(building)

    # ── geometry ──

    def _at_level(self, z: float) -> bool:
        return any(abs(z - level) <= 1e-3 for level in self.levels)

    def storey_at(self, z: float, direction: str) -> Storey | None:
        for s in self.storeys:
            if s.direction == direction and s.bottom - 1e-6 <= z <= s.top + 1e-6:
                return s
        return None

    def segments(self, member: str, own: list[Any], unit: np.ndarray, direction: str) -> list:
        """The member's segments between lateral supports along ``unit`` (cached)."""
        key = (member, direction)
        if key in self._segments:
            return self._segments[key]
        ordered = sorted(own, key=lambda p: min(p.start[2], p.end[2]))
        vertical = all(_is_vertical(p) for p in ordered)
        groups: list[list[Any]] = [[]]
        braced: list[list[str]] = [[]]
        for k, p in enumerate(ordered):
            groups[-1].append(p)
            if k == len(ordered) - 1:
                break
            top = p.end if p.end[2] >= p.start[2] else p.start
            node = self._node_at(top)
            by = self.model.supports(node, member, unit, p.axes[0]) if node is not None else []
            if by:
                braced[-1] += by
                groups.append([])
                braced.append(list(by))
        model = self.model

        def framed_end(node: int | None, z: float, axis: np.ndarray) -> bool:
            # A floor level, a support, or a joint with beams alone (it sways with the storey).
            if node is None:
                return self._at_level(z)
            if self._at_level(z) or any(model.restraint.get(node, [False] * 6)[:3]):
                return True
            return model.framed_joint(node, member, unit, axis)

        found: list[Segment] = []
        for group, by in zip(groups, braced, strict=True):
            lc = sum(p.length for p in group) * 1e3
            bottom = min(group[0].start[2], group[0].end[2])
            top = max(group[-1].start[2], group[-1].end[2])
            top_node = self._node_at(
                group[-1].end if group[-1].end[2] >= group[-1].start[2] else group[-1].start
            )
            bottom_node = self._node_at(
                group[0].start if group[0].start[2] <= group[0].end[2] else group[0].end
            )
            framed = (
                vertical
                and framed_end(bottom_node, bottom, group[0].axes[0])
                and framed_end(top_node, top, group[-1].axes[0])
            )
            lu = lc
            if (
                vertical
                and top_node is not None
                and (self._at_level(top) or model.framed_joint(top_node, member, unit, None))
            ):
                lu = max(lc - model.clear_depth(top_node, unit), 0.5 * lc)
            psi = None
            notes = ("", "")
            k_ns, k_s = 1.0, None
            if framed and top_node is not None and bottom_node is not None:
                pb, nb = self.model.psi(bottom_node, unit, self.options.fixed_psi)
                pt, nt = self.model.psi(top_node, unit, self.options.fixed_psi)
                psi, notes = (pb, pt), (nb, nt)
                k_s = k_sway(pb, pt)
                if self.options.effective_length == "chart":
                    k_ns = k_nonsway(pb, pt)
            storey = self.storey_at((bottom + top) / 2, direction) if vertical else None
            found.append(Segment(group, lc, lu, framed, k_ns, k_s, psi, notes, by, storey))
        self._segments[key] = found
        return found

    def _node_at(self, xyz: np.ndarray) -> int | None:
        return self._nodes.get(_key(xyz))

    def _sum_pc(self, building: Any) -> None:
        """ΣPc of each storey's sway columns per combination (Eq. 6.6.28): Pc from Eq. 6.6.20
        with k of 6.3.10.7.2 (the sway chart) and EI of 6.3.10.6.1 as BNBC 6.3.10.7.4 says
        (p 915): the project's EI option (Eq. 6.6.22, or Eq. 6.6.21 with the column's bars)
        over (1 + βdns), βdns that combination's sustained over total axial force of the
        column. A column cut by an intermediate beam counts once, with its smallest segment
        Pc."""
        from saengine.design.check import _profile_forces
        from saengine.library.bim import ColumnElement

        n = len(self.combinations)
        for storey in self.storeys:
            storey.sum_pc = [0.0] * n
        for element in building.elements:
            if not isinstance(element, ColumnElement):
                continue
            own = self.pieces.get(element.id, [])
            object_type = self.types.get(element.type)
            props = _concrete_column(object_type, self.mats)
            if not own or props is None:
                continue
            ec, dims = props
            section = self._bars_section(object_type) if self.options.stiffness == "bars" else None
            turned = round((element.rotation or 0.0) / 90) % 2 == 1
            for axis in ("x", "y"):
                unit, direction, _h, ig, ise = _axis_frame(own[0], turned, axis, dims, section)
                smallest: dict[int, tuple[Storey, list[float]]] = {}
                for seg in self.segments(element.id, own, unit, direction):
                    if seg.storey is None or seg.k_s is None:
                        continue
                    pcs = []
                    for c in range(n):
                        pu = p_sus = 0.0
                        for p in seg.pieces:
                            pu = max(pu, float(_profile_forces(p, turned, p.forces[c])["P"].max()))
                            if p.sustained is not None:
                                p_sus = max(
                                    p_sus,
                                    float(_profile_forces(p, turned, p.sustained[c])["P"].max()),
                                )
                        beta = min(max(p_sus / pu, 0.0), 1.0) if pu > 0 else 0.0
                        ei = effective_ei(
                            ec,
                            ig,
                            beta,
                            section.es if section is not None else 0.0,
                            ise if section is not None else None,
                        )
                        pcs.append(critical_load(ei, seg.k_s, seg.lu))
                    key = id(seg.storey)
                    if key not in smallest:
                        smallest[key] = (seg.storey, pcs)
                    else:
                        smallest[key] = (
                            seg.storey,
                            [min(a, b) for a, b in zip(smallest[key][1], pcs, strict=True)],
                        )
                for storey, pcs in smallest.values():
                    storey.sum_pc = [a + b for a, b in zip(storey.sum_pc, pcs, strict=True)]

    def _bars_section(self, object_type: Any) -> Any:
        """The column type's reinforced section (its bars, for Eq. 6.6.21 in ΣPc), or None when
        it cannot be built (Eq. 6.6.22 is then used for it)."""
        from saengine.design.rc import section_of

        try:
            concrete = self.mats[object_type.material]
            steel = self.mats[object_type.reinforcement.material]
            return section_of(
                object_type.profile,
                object_type.reinforcement,
                concrete.concrete.fc,
                steel.steel.fy,
                (steel.mechanical.E if steel.mechanical else None) or 200_000.0,
                concrete.concrete.maxAggregate,
            )
        except Exception:  # noqa: BLE001 - any missing data: the bar-free EI
            return None

    # ── the design of one column ──

    def column(
        self, member: str, section: Any, own: list[Any], turned: bool, ec: float
    ) -> ColumnSlenderness:
        """The slenderness checks and the magnified demand points of a column member."""
        from saengine.design.check import _profile_forces, _where

        dims = _dimensions(section)
        combos = self.combinations
        results: list[AxisResult] = []
        for axis in ("x", "y"):
            unit, direction, h, ig, ise = _axis_frame(own[0], turned, axis, dims, section)
            segs = self.segments(member, own, unit, direction)
            results.append(
                self._axis(member, segs, axis, direction, h, ig, ise, ec, section, turned)
            )

        points: list[tuple[float, float, float, str, str]] = []
        by_axis = {r.axis: r for r in results}
        for piece in own:
            for c, forces in enumerate(piece.forces):
                values = _profile_forces(piece, turned, forces)
                sway = (
                    _profile_forces(piece, turned, piece.sway[c])
                    if piece.sway is not None
                    else None
                )
                count = len(forces)
                mx, my = values["Mx"].copy(), values["My"].copy()
                if sway is not None:
                    ds_x = by_axis["x"].delta_s[c] if piece.id in by_axis["x"].segment_of else 1.0
                    ds_y = by_axis["y"].delta_s[c] if piece.id in by_axis["y"].segment_of else 1.0
                    mx = mx + (ds_x - 1) * sway["Mx"]
                    my = my + (ds_y - 1) * sway["My"]
                for k in range(count):
                    points.append(
                        (
                            float(values["P"][k]),
                            abs(float(mx[k])),
                            abs(float(my[k])),
                            combos[c],
                            _where(piece, k, count),
                        )
                    )
        rx, ry = by_axis["x"], by_axis["y"]
        for c in range(len(combos)):
            pu = max(float(_profile_forces(p, turned, p.forces[c])["P"].max()) for p in own)
            # Only where slenderness is designed for (about either axis): a column whose
            # slenderness is neglected is checked at its stations alone.
            if pu <= 0 or not (rx.magnified[c] or ry.magnified[c]):
                continue
            where = f"{member}, moments magnified along the length (slenderness)"
            points.append((pu, rx.mc[c], ry.mc_no_min[c], combos[c], where + ", M2,min about x"))
            points.append((pu, rx.mc_no_min[c], ry.mc[c], combos[c], where + ", M2,min about y"))
        return ColumnSlenderness(results, points)

    def _axis(
        self,
        member: str,
        segs: list[Segment],
        axis: str,
        direction: str,
        h: float,
        ig: float,
        ise: float,
        ec: float,
        section: Any,
        turned: bool,
    ) -> AxisResult:
        from saengine.design.check import _profile_forces

        opts = self.options
        moment = "Mx" if axis == "x" else "My"
        r = 0.25 * h if _dimensions(section)[2] else 0.3 * h
        combos = self.combinations
        n = len(combos)
        mc = [0.0] * n
        mc_no_min = [0.0] * n
        ds_member = [1.0] * n
        magnified = [False] * n
        segment_of: dict[int, Segment] = {}
        best: dict[str, Any] | None = None  # the governing segment and combination
        # The worst of every combination: (value, combination) of δs, Mc / M1st, k lu / r.
        worst: dict[str, Any] = {"ds": (1.0, None), "ratio": (0.0, None), "buckles": None}
        for seg in segs:
            for p in seg.pieces:
                segment_of[p.id] = seg
            sway_storey = seg.storey is not None and bool(seg.storey.sway) and seg.framed
            k_used = seg.k_s if sway_storey and seg.k_s is not None else seg.k_ns
            slender = k_used * seg.lu / r
            reversed_ = [p.start[2] > p.end[2] for p in seg.pieces]
            consistent = len(set(reversed_)) == 1
            for c in range(n):
                rows = []
                for p, flip in zip(seg.pieces, reversed_, strict=True):
                    total = _profile_forces(p, turned, p.forces[c])
                    sway = _profile_forces(p, turned, p.sway[c]) if p.sway is not None else None
                    sustained = (
                        _profile_forces(p, turned, p.sustained[c])
                        if p.sustained is not None
                        else None
                    )
                    order = slice(None, None, -1) if flip else slice(None)
                    rows.append(
                        (
                            total["P"][order],
                            total[moment][order],
                            (sway[moment] if sway is not None else 0 * total[moment])[order],
                            (sustained["P"] if sustained is not None else 0 * total["P"])[order],
                        )
                    )
                pu = float(max(r_[0].max() for r_ in rows))
                p_sus = float(max(r_[3].max() for r_ in rows))
                m_all = np.concatenate([r_[1] for r_ in rows])
                ms_all = np.concatenate([r_[2] for r_ in rows])
                m_bot, m_top = float(m_all[0]), float(m_all[-1])
                ms_bot, ms_top = float(ms_all[0]), float(ms_all[-1])
                first = max(abs(m_bot), abs(m_top))
                # Sway magnification of the end moments (6.3.10.7).
                ds = 1.0
                sway_applies = sway_storey and slender > SWAY_LIMIT and opts.second_order == "none"
                if sway_applies and seg.storey is not None and pu > 0:
                    ds = seg.storey.delta_s(c, opts.sway_magnifier)
                ds_member[c] = max(ds_member[c], ds) if math.isfinite(ds) else math.inf
                if ds > worst["ds"][0]:
                    worst["ds"] = (ds, c)
                end_b = m_bot + (ds - 1) * ms_bot if math.isfinite(ds) else math.inf
                end_t = m_top + (ds - 1) * ms_top if math.isfinite(ds) else math.inf
                # Along the length (6.3.10.6, 6.3.10.2.2).
                info: dict[str, Any] = {
                    "segment": seg,
                    "c": c,
                    "pu": pu,
                    "first": first,
                    "ds": ds,
                    "k": k_used,
                    "slender": slender,
                }
                if not math.isfinite(ds):
                    magnified[c] = True
                    mc[c] = mc_no_min[c] = math.inf
                    info.update(neglected=False, dns=math.inf, mc=math.inf, limit=SWAY_LIMIT)
                    best = _governs(best, info)
                    continue
                m2 = max(abs(end_b), abs(end_t))
                m1 = min(abs(end_b), abs(end_t))
                spectral = c < len(self.spectrum) and self.spectrum[c]
                # A response spectrum combination: no sign, single curvature and Cm = 1.0.
                same_sign = spectral or end_b * end_t > 0
                ratio = (m1 / m2 if m2 > 0 else 1.0) * (1 if same_sign else -1)
                transverse = spectral or not consistent or _curved(m_all + (ds - 1) * ms_all)
                if sway_storey:
                    limit = SWAY_LIMIT
                    neglected = slender <= SWAY_LIMIT
                else:
                    limit = nonsway_limit(ratio)
                    neglected = slender <= limit
                info.update(limit=limit, neglected=neglected, ratio=ratio, m2=m2, spectral=spectral)
                if neglected or pu <= 0:
                    mc[c] = max(mc[c], m2)
                    mc_no_min[c] = max(mc_no_min[c], m2)
                    info.update(dns=1.0, mc=m2, cm=None, transverse=transverse)
                    best = _governs(best, info)
                    continue
                magnified[c] = True
                beta = min(max(p_sus / pu, 0.0), 1.0)
                ei = effective_ei(
                    ec, ig, beta, section.es, ise if opts.stiffness == "bars" else None
                )
                pc = critical_load(ei, seg.k_ns, seg.lu)
                m2_min = minimum_moment(pu, h)
                cm = cm_factor(ratio, transverse)
                d_ns = delta_ns(cm, pu, pc)
                d_ns_min = delta_ns(1.0, pu, pc)  # Cm = 1 when M2,min governs (6.3.10.6.5)
                with_min = d_ns * m2 if m2 >= m2_min else d_ns_min * m2_min
                mc[c] = max(mc[c], with_min)
                mc_no_min[c] = max(mc_no_min[c], d_ns * m2)
                reference = max(first, m2_min)
                info.update(
                    dns=d_ns if m2 >= m2_min else d_ns_min,
                    mc=with_min,
                    cm=1.0 if m2 < m2_min else cm,
                    transverse=transverse,
                    beta=beta,
                    ei=ei,
                    pc=pc,
                    m2min=m2_min,
                    moment_ratio=with_min / reference if reference > 0 else 1.0,
                    min_governs=m2 < m2_min,
                )
                if not math.isfinite(d_ns) and worst["buckles"] is None:
                    worst["buckles"] = c
                if info["moment_ratio"] > worst["ratio"][0]:
                    worst["ratio"] = (info["moment_ratio"], c)
                best = _governs(best, info)
        check = self._check(member, axis, direction, r, best, worst)
        return AxisResult(axis, direction, check, mc, mc_no_min, ds_member, segment_of, magnified)

    def _check(
        self,
        member: str,
        axis: str,
        direction: str,
        r: float,
        best: dict[str, Any] | None,
        worst: dict[str, Any],
    ) -> dict[str, Any]:
        from saengine.design.check import _check

        opts = self.options
        if best is None:
            return _check(f"Slenderness about {axis}", 0.0, KLU_R_MAX, "", None, "", flag=True)
        seg: Segment = best["segment"]
        c = best["c"]
        storey = seg.storey
        sway = None if storey is None or not seg.framed else storey.sway
        q = storey.q[c] if storey is not None else None
        slender = best["slender"]
        designed = not best.get("neglected", False)
        failures: list[str] = []
        second_order_required = False
        utils = [slender / KLU_R_MAX]
        if slender > KLU_R_MAX:
            failures.append(
                f"k lu / r = {slender:.1f} > {KLU_R_MAX:g}: a nonlinear second-order analysis "
                "is required (ACI 318-19 6.2.6)"
            )
            second_order_required = True
        ds, ds_c = worst["ds"]
        combos = self.combinations
        if sway and opts.second_order == "none" and opts.sway_magnifier == "Q" and designed:
            utils.append(ds / DELTA_S_MAX if math.isfinite(ds) else math.inf)
            if ds > DELTA_S_MAX:
                failures.append(
                    f"δs = 1/(1 - Q) = {_fmt(ds)} > {DELTA_S_MAX:g} ({combos[ds_c]}): "
                    "second-order analysis required (BNBC 6.3.10.7.3; or δs from ΣPc, "
                    "Eq. 6.6.28)"
                )
                second_order_required = True
        elif not math.isfinite(ds):
            utils.append(math.inf)
            failures.append(
                f"ΣPu >= 0.75 ΣPc ({combos[ds_c]}): the storey is unstable (Eq. 6.6.28)"
            )
        dns = best.get("dns", 1.0)
        if worst["buckles"] is not None:
            utils.append(math.inf)
            failures.append(
                f"Pu >= 0.75 Pc ({combos[worst['buckles']]}): the column buckles (Eq. 6.6.19): "
                "enlarge it"
            )
        ratio, ratio_c = worst["ratio"]
        if designed and ratio_c is not None and math.isfinite(ratio):
            utils.append(ratio / MOMENT_RATIO_MAX)
            if ratio > MOMENT_RATIO_MAX:
                failures.append(
                    f"second-order moment {_fmt(ratio)} times the first-order one "
                    f"({combos[ratio_c]}), above {MOMENT_RATIO_MAX:g} (BNBC 6.3.10.2.1)"
                )
        utilisation = max(utils)
        kind = "sway" if sway else "nonsway"
        if not designed:
            label = f"{kind}, neglected"
        elif sway and opts.second_order == "pDelta":
            label = f"{kind}, P-Δ analysis, δns = {_fmt(dns)}"
        elif sway:
            label = f"{kind}, δs = {_fmt(ds)}, δns = {_fmt(dns)}"
        else:
            label = f"{kind}, δns = {_fmt(dns)}"
        parts = [
            f"lu = {seg.lu:.0f} mm, k = {best['k']:.2f}, r = {r:.0f} mm",
            f"{seg.pieces[0].name} to {seg.pieces[-1].name}"
            if len(seg.pieces) > 1
            else seg.pieces[0].name,
        ]
        if seg.psi is not None:
            parts.append(
                f"ψ bottom = {_fmt_psi(seg.psi[0], seg.psi_notes[0])}, ψ top = "
                f"{_fmt_psi(seg.psi[1], seg.psi_notes[1])}"
            )
        elif seg.braced_by:
            parts.append(f"braced by {', '.join(seg.braced_by)}: k = 1")
        if storey is not None and seg.framed:
            qm, _ = storey.q_max
            parts.append(
                f"storey {storey.name} ({direction}): {kind}"
                + (f", Q = {qm:.3f}" if qm is not None else ", no lateral load")
            )
        if designed and "cm" in best and best.get("cm") is not None:
            parts.append(
                f"Cm = {best['cm']:.2f}, βdns = {best['beta']:.2f}, Pc = {best['pc'] / 1e3:.0f} kN"
                + ("; M2,min governs" if best.get("min_governs") else "")
            )
        if best.get("spectral"):
            parts.append(
                "response spectrum combination: the modal moments have no sign, single "
                "curvature taken (M1/M2 = +|M1/M2|) and Cm = 1.0"
            )
        if not designed:
            parts.append(f"k lu / r <= {best['limit']:.1f}: slenderness may be neglected")
        parts += failures
        result = _check(
            f"Slenderness about {axis} ({label})",
            slender,
            KLU_R_MAX,
            "",
            self.combinations[c],
            "; ".join(parts),
            flag=not designed and not failures,
            utilisation=utilisation if designed or failures else slender / best["limit"],
        )
        m2 = best.get("m2", best["first"])
        result["slenderness"] = {
            "lu": round(seg.lu, 1),
            "k": round(best["k"], 3),
            "r": round(r, 1),
            "klu_r": round(slender, 2),
            "sway": sway,
            "Q": None if q is None else round(q, 4),
            "deltaNs": _round(dns, 3) if designed else None,
            "deltaS": _round(best["ds"], 3) if sway and opts.second_order == "none" else None,
            "M2": round(best["first"] / 1e6, 2),
            "M2magnified": _round(best["mc"] / 1e6, 2) if designed else round(m2 / 1e6, 2),
            "limit": round(best["limit"], 2),
            "storey": storey.name if storey is not None else None,
            "axis": axis,
            "direction": direction,
            "kNonsway": round(seg.k_ns, 3),
            "kSway": None if seg.k_s is None else round(seg.k_s, 3),
            "psi": None if seg.psi is None else [round(v, 3) for v in seg.psi],
            "Cm": None if best.get("cm") is None else round(best["cm"], 3),
            "betaDns": round(best["beta"], 3) if "beta" in best else None,
            "Pc": round(best["pc"] / 1e3, 1) if "pc" in best else None,
            "Pu": round(best["pu"] / 1e3, 1),
            "M2min": round(best["m2min"] / 1e6, 2) if "m2min" in best else None,
            "neglected": not designed,
            "secondOrder": opts.second_order,
        }
        result["secondOrderRequired"] = second_order_required
        if failures:
            result["ok"] = False
        return result


def _governs(best: dict[str, Any] | None, info: dict[str, Any]) -> dict[str, Any]:
    """The governing case of an axis: a designed one over a neglected one, then the larger
    magnified moment over its first-order moment, then the larger magnified moment."""

    def key(i: dict[str, Any]) -> tuple[float, float, float]:
        mc = i.get("mc", 0.0)
        growth = mc / max(i.get("m2", i["first"]), 1.0) if math.isfinite(mc) else math.inf
        return (0.0 if i.get("neglected") else 1.0, mc if math.isfinite(mc) else math.inf, growth)

    if best is None or key(info) > key(best):
        return info
    return best


def _curved(moments: np.ndarray) -> bool:
    """Whether a moment diagram is not a straight line between its ends: a transverse load
    between the supports (Cm = 1.0)."""
    m = np.asarray(moments, dtype=float)
    if len(m) < 3:
        return False
    line = np.linspace(m[0], m[-1], len(m))
    scale = max(float(np.abs(m).max()), 1e3)
    return bool(np.abs(m - line).max() > 0.02 * scale)


def _fmt(value: float) -> str:
    return f"{value:.2f}" if math.isfinite(value) else "∞"


def _fmt_psi(value: float, note: str) -> str:
    text = "∞" if value >= PSI_INFINITE else f"{value:.2f}"
    return f"{text} ({note})" if note else text


def _dimensions(section: Any) -> tuple[float, float, bool]:
    """(width along the profile's x, depth along its y, circular) [mm]."""
    from saengine.library.objects import CircleProfile

    profile = section.profile if hasattr(section, "profile") else section
    if isinstance(profile, CircleProfile):
        return 2 * profile.radius, 2 * profile.radius, True
    return float(profile.xDim), float(profile.yDim), False


def _concrete_column(object_type: Any, mats: dict[str, Any]) -> tuple[float, Any] | None:
    from saengine.library.materials import Category
    from saengine.library.objects import CircleProfile, Column, RectangleProfile

    if not isinstance(object_type, Column):
        return None
    if not isinstance(object_type.profile, (RectangleProfile, CircleProfile)):
        return None
    concrete = mats.get(object_type.material)
    if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
        return None
    return concrete_modulus(concrete), object_type.profile


def concrete_modulus(concrete: Any) -> float:
    """Ec [MPa]: the material's E, else 4700 √f'c (BNBC 6.1.7.1 / ACI 19.2.2.1)."""
    e = concrete.mechanical.E if concrete.mechanical else None
    return float(e) if e else 4700 * math.sqrt(concrete.concrete.fc)


def _axis_frame(
    piece: Any, turned: bool, axis: str, dims: Any, section: Any = None
) -> tuple[np.ndarray, str, float, float, float]:
    """For bending about the profile's ``axis``: the global sway direction (unit vector, and
    "X" or "Y" whichever it is nearer), the dimension h in that direction [mm], Ig and the
    bars' Ise about the axis [mm⁴]."""
    if not isinstance(dims, tuple):
        dims = _dimensions(dims)
    b, d, circle = dims
    along_z = piece.depth_along_z != turned
    depth_axis = piece.axes[2] if along_z else piece.axes[1]
    width_axis = piece.axes[1] if along_z else piece.axes[2]
    unit = np.asarray(depth_axis if axis == "x" else width_axis, dtype=float)
    if _is_vertical(piece):  # the sway direction is horizontal
        unit = np.array([unit[0], unit[1], 0.0])
        size = float(np.linalg.norm(unit))
        unit = unit / size if size > 1e-9 else np.array([1.0, 0.0, 0.0])
    direction = "X" if abs(unit[0]) >= abs(unit[1]) else "Y"
    h = d if axis == "x" else b
    if circle:
        ig = math.pi * b**4 / 64
    else:
        ig = (b * d**3 if axis == "x" else d * b**3) / 12
    ise = 0.0
    if section is not None:
        ise = sum(bar.area * (bar.y if axis == "x" else bar.x) ** 2 for bar in section.bars)
    return unit, direction, h, ig, ise


METHOD = [
    (
        "Column slenderness to BNBC 2020 Part 6 Sec 6.3.10 (ACI 318-19 6.2.5, 6.6.4): per "
        "bending direction lu = the clear height between lateral supports (the beam depth "
        "below a floor taken off), r = 0.30 h or 0.25 D; storeys sway when Q = ΣPu Δo / "
        "(Vus lc) > 0.05 (ΣPu and Vus of the frames and walls, Δo × {drift} for cracked "
        "stiffness); k = {k} in nonsway "
        "storeys, from the sway alignment chart (ψ with 0.70 Ig columns, 0.35 Ig beams, "
        "0.25 Ig flat plates, lengths between the joints) in sway ones, a column cut by an "
        "intermediate beam swaying with its storey; slenderness neglected when k lu / r <= 22 (sway) or 34 - 12 M1/M2 <= 40 "
        "(nonsway)."
    ),
    (
        "Moment magnification: Mc = δns M2, δns = Cm / (1 - Pu / (0.75 Pc)) >= 1, "
        "Pc = π² EI / (k lu)², EI = {ei} / (1 + βdns), Cm = 0.6 + 0.4 M1/M2 (1.0 with loads "
        "along the column), M2 >= Pu (15 + 0.03 h) about each axis separately; sway "
        "storeys: M = Mns + δs Ms, {sway}. Limits: δs <= 1.5 (Q method), Mc <= 1.4 times the "
        "first-order moment, k lu / r <= 100 (ACI 318-19 6.2.6). Response spectrum "
        "combinations (± E, the modal moments without sign): single curvature and Cm = 1.0 "
        "(SAEngine's conservative rule)."
    ),
]


def method(options: SlenderOptions, lateral_cracked: bool = False) -> list[str]:
    """The method lines of the report for these options; ``lateral_cracked``: the analysed
    model ran its lateral cases on cracked sections (:attr:`Model.lateral_cracked`)."""
    sway = (
        "the analysis includes P-Δ (δs = 1)"
        if options.second_order == "pDelta"
        else (
            "δs = 1 / (1 - Q)"
            if options.sway_magnifier == "Q"
            else "δs = 1 / (1 - ΣPu / (0.75 ΣPc)), Pc with EI / (1 + βdns) (BNBC 6.3.10.7.4)"
        )
    )
    return [
        line.format(
            drift=(
                f"{options.drift_factor:.2f}"
                if options.drift_factor is not None
                else "1.00 (the analysis ran its lateral cases on cracked sections)"
                if lateral_cracked
                else "the storey's cracked-over-gross drift ratio (0.70 Ig columns, 0.35 Ig "
                "beams and walls, 0.25 Ig flat plates)"
            ),
            k="1.0" if options.effective_length == "unity" else "from the nonsway chart",
            ei="0.4 Ec Ig" if options.stiffness == "0.4EcIg" else "(0.2 Ec Ig + Es Ise)",
            sway=sway,
        )
        for line in METHOD
    ]
