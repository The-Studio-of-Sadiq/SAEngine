"""Fixed offshore structures: a jacket or monopile under the design wave, current and the wind on
its deck, by Morison's equation (the code pack's ``offshore`` table).

Waves (:class:`Wave`), x along the wave's direction, z up from still water, the seabed at -d:

- Airy (linear): k from ω² = g k tanh(k d); u = a ω cosh(k(z' + d)) / sinh(k d) cos θ, w with
  sinh and sin θ, the local accelerations a ω² ...; above still water by Wheeler stretching z' =
  d (z + d) / (d + η) - d;
- the stream function wave (Rienecker and Fenton's Fourier method, N = 12 terms: the surface at
  N + 1 points of half a wavelength, the coefficients Bj, k, the mean speed, Q and R solved by
  Newton's method from the Airy wave, the height raised in steps), as accurate as Stokes' fifth
  order theory and valid to steeper waves; zero mean Eulerian current, so the wave speed is the
  mean fluid speed in the wave's frame. A wave that does not converge falls back to Airy (said).

Loads: each member in pieces of at most 1 m; at each piece below the surface the velocity
(the wave's horizontal velocity × the kinematics factor, plus the current U (z + d / d)^exponent
× the blockage factor of the number of legs, along the wave) and the local acceleration, their
components normal to the member, and f = ½ ρ Cd De |un| un + ρ Cm π De² / 4 an with De the
diameter plus twice the marine growth (rough coefficients with growth). The phase of the wave
with the largest base shear (36 phases over a period) is applied, each piece's force shared by
the member's two nodes; the deck's weight and wind at the top nodes.

Analysis: the jacket (:class:`saengine.library.shapes.JacketFrame`) or monopile as a frame fixed
at the mudline (the piles' depth to fixity is not modelled), cases D (members and deck) and E
(wave, current, deck wind), combined γG D + γE E and 0.9 D + γE E (the table's factors; 0.9
SAEngine practice), each member checked |N| / NRd + |M| / MRd by the pack's steel method.

Not covered: buoyancy and flooded members, wave slam and slap, the piles and the soil,
fatigue, joint (punching) checks of the tubular joints, seismic, the topsides. Units: m, kN.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.special import common
from saengine.special import frame as fr

G = 9.80665
#: Fourier terms of the stream function wave.
FOURIER_TERMS = 12
#: Phases of the wave searched for the largest base shear.
PHASES = 36
#: Longest piece of a member for the wave loads [m].
PIECE = 1.0


def wave_number(period: float, depth: float) -> float:
    """k of the linear wave: ω² = g k tanh(k d) (Newton from the deep water value)."""
    omega = 2 * math.pi / period
    k = max(omega**2 / G, omega / math.sqrt(G * depth))
    for _ in range(100):
        f = G * k * math.tanh(k * depth) - omega**2
        df = G * math.tanh(k * depth) + G * k * depth / math.cosh(k * depth) ** 2
        step = f / df
        k -= step
        if abs(step) < 1e-12 * k:
            break
    return k


@dataclass
class Wave:
    """A steady wave: ``theory`` "airy" or "streamFunction"; ``k`` [1/m], ``c`` [m/s]; for the
    stream function its coefficients ``b`` [m²/s] and the surface (``surface_x`` [m] from the
    crest, ``surface_eta`` [m] above still water) over half a wavelength."""

    theory: str
    height: float
    period: float
    depth: float
    k: float
    c: float
    b: np.ndarray = field(default_factory=lambda: np.zeros(0))
    surface_x: np.ndarray = field(default_factory=lambda: np.zeros(0))
    surface_eta: np.ndarray = field(default_factory=lambda: np.zeros(0))
    notes: list[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return 2 * math.pi / self.k

    def eta(self, x: float) -> float:
        """The surface above still water at ``x`` from the crest [m]."""
        if self.theory == "airy":
            return self.height / 2 * math.cos(self.k * x)
        lam = self.length
        p = x % lam
        p = lam - p if p > lam / 2 else p
        return float(np.interp(p, self.surface_x, self.surface_eta))

    def kinematics(self, x: float, z: float) -> tuple[float, float, float, float]:
        """(u, w, ∂u/∂t, ∂w/∂t) at ``x`` from the crest and ``z`` above still water [m/s,
        m/s²]; zero above the surface."""
        eta = self.eta(x)
        if z > eta + 1e-9:
            return 0.0, 0.0, 0.0, 0.0
        d, k = self.depth, self.k
        if self.theory == "airy":
            zs = d * (z + d) / (d + eta) - d  # Wheeler stretching
            a = self.height / 2
            omega = 2 * math.pi / self.period
            theta = k * x
            ch = math.cosh(k * (zs + d)) / math.sinh(k * d)
            sh = math.sinh(k * (zs + d)) / math.sinh(k * d)
            return (
                a * omega * ch * math.cos(theta),
                a * omega * sh * math.sin(theta),
                a * omega**2 * ch * math.sin(theta),
                -a * omega**2 * sh * math.cos(theta),
            )
        y = z + d
        u = w = du = dw = 0.0
        for j, bj in enumerate(self.b, start=1):
            jk = j * k
            ch = _ratio(math.cosh, jk * y, jk * d)
            sh = _ratio(math.sinh, jk * y, jk * d)
            cos, sin = math.cos(jk * x), math.sin(jk * x)
            u += bj * jk * ch * cos
            w += bj * jk * sh * sin
            du += self.c * bj * jk * jk * ch * sin
            dw -= self.c * bj * jk * jk * sh * cos
        return u, w, du, dw


def _ratio(fn: Any, top: float, bottom: float) -> float:
    """fn(top) / cosh(bottom) without overflow (top <= bottom + a little)."""
    if bottom < 300:
        return fn(top) / math.cosh(bottom)
    sign = -1.0 if (fn is math.sinh and top < 0) else 1.0
    return sign * math.exp(abs(top) - bottom)


def airy(height: float, period: float, depth: float) -> Wave:
    k = wave_number(period, depth)
    return Wave("airy", height, period, depth, k, 2 * math.pi / (k * period))


def stream_function(height: float, period: float, depth: float, terms: int = FOURIER_TERMS) -> Wave:
    """The stream function wave (Rienecker and Fenton): ValueError when it does not converge
    (a wave too steep, or breaking)."""
    n = terms
    h_nd = height / depth
    tau = period * math.sqrt(G / depth)
    k0 = wave_number(period, depth) * depth
    c0 = 2 * math.pi / (k0 * tau)
    xs_unit = np.arange(n + 1) * math.pi / n  # k X_m

    def unpack(v: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, float, float, float]:
        return v[0], v[1 : n + 2], v[n + 2 : 2 * n + 2], v[2 * n + 2], v[2 * n + 3], v[2 * n + 4]

    def residual(v: np.ndarray, target: float) -> np.ndarray:
        k, eta, b, u_mean, q, r = unpack(v)
        js = np.arange(1, n + 1)
        out = np.zeros(2 * n + 5)
        for m in range(n + 1):
            kx = js * xs_unit[m]
            arg_y = js * k * eta[m]
            denom = np.cosh(js * k)
            sh = np.sinh(arg_y) / denom
            ch = np.cosh(arg_y) / denom
            psi = -u_mean * eta[m] + float(np.sum(b * sh * np.cos(kx))) + q
            u = -u_mean + float(np.sum(b * js * k * ch * np.cos(kx)))
            v_ = float(np.sum(b * js * k * sh * np.sin(kx)))
            out[m] = psi
            out[n + 1 + m] = 0.5 * (u * u + v_ * v_) + eta[m] - r
        out[2 * n + 2] = (0.5 * eta[0] + float(np.sum(eta[1:n])) + 0.5 * eta[n]) / n - 1.0
        out[2 * n + 3] = eta[0] - eta[n] - target
        out[2 * n + 4] = k * u_mean * tau - 2 * math.pi
        return out

    v = np.zeros(2 * n + 5)
    a0 = 0.5 * h_nd * 0.25
    v[0] = k0
    v[1 : n + 2] = 1.0 + a0 * np.cos(xs_unit)
    v[n + 2] = c0 * a0 / math.tanh(k0)
    v[2 * n + 2] = c0
    v[2 * n + 3] = c0
    v[2 * n + 4] = 0.5 * c0 * c0 + 1.0
    steps = 4
    for step in range(1, steps + 1):
        target = h_nd * step / steps
        for _ in range(60):
            f = residual(v, target)
            if float(np.max(np.abs(f))) < 1e-10:
                break
            jac = np.zeros((len(v), len(v)))
            for i in range(len(v)):
                dv = 1e-7 * max(1.0, abs(v[i]))
                w = v.copy()
                w[i] += dv
                jac[:, i] = (residual(w, target) - f) / dv
            try:
                delta = np.linalg.solve(jac, -f)
            except np.linalg.LinAlgError as error:
                raise ValueError("the stream function wave did not converge") from error
            v = v + delta
            if not np.all(np.isfinite(v)):
                raise ValueError("the stream function wave did not converge")
        else:
            raise ValueError("the stream function wave did not converge")
    k, eta, b, u_mean, _, _ = unpack(v)
    if k <= 0 or np.any(eta <= 0):
        raise ValueError("the stream function wave did not converge")
    scale_v = math.sqrt(G * depth)
    wave = Wave(
        "streamFunction",
        height,
        period,
        depth,
        k / depth,
        u_mean * scale_v,
        b=b * scale_v * depth,
        surface_x=xs_unit / (k / depth),
        surface_eta=(eta - 1.0) * depth,
    )
    wave.notes.append(
        f"stream function wave ({n} terms): L = {wave.length:.1f} m, crest {wave.surface_eta[0]:.2f} "
        f"m and trough {wave.surface_eta[-1]:.2f} m about still water"
    )
    return wave


def design_wave(structure: Any) -> Wave:
    if structure.waveTheory == "airy":
        wave = airy(structure.waveHeight, structure.wavePeriod, structure.waterDepth)
        wave.notes.append(f"Airy wave, Wheeler stretched: L = {wave.length:.1f} m")
        return wave
    try:
        return stream_function(structure.waveHeight, structure.wavePeriod, structure.waterDepth)
    except ValueError as error:
        wave = airy(structure.waveHeight, structure.wavePeriod, structure.waterDepth)
        wave.notes.append(f"{error}; the Airy wave is used (L = {wave.length:.1f} m)")
        return wave


def jacket_shape(structure: Any) -> Any:
    from saengine.library.shapes import JacketFrame

    return JacketFrame(
        form=structure.kind,
        height=(structure.waterDepth + structure.deckElevation) * 1000,
        baseWidth=structure.baseWidth * 1000,
        topWidth=structure.topWidth * 1000,
        bays=structure.bays,
        memberType=structure.legType,
        braceType=structure.braceType,
        supports="fixed",
    )


@dataclass
class _Piece:
    member: int
    share: float  # of the force to the member's start node
    middle: np.ndarray  # [m] from the mudline
    length: float
    axis: np.ndarray
    diameter: float


def analyse_offshore(structure: Any, settings: Any, objects: Any, materials: Any) -> dict[str, Any]:
    pack = code_context.current()
    code = code_context.code_name(pack)
    if not pack.has("offshore"):
        raise ValueError(f"offshore structures: not covered by the code pack {code}")
    t = pack.table("offshore")
    notes: list[str] = []
    wave = design_wave(structure)
    notes += wave.notes
    shape = jacket_shape(structure)
    geometry = shape.local()
    ids = {structure.legType} | ({structure.braceType} if structure.braceType else set())
    types = {i: common.member_type(i, objects, materials) for i in ids}
    frame = fr.Frame()
    roles = []
    for m in geometry.members:
        frame.member(m.start / 1000, m.end / 1000, types[m.type].section)
        roles.append("leg" if m.type == structure.legType else "brace")
    for s in geometry.supports:
        frame.support(s.at / 1000, (1, 1, 1, 1, 1, 1))
    d = structure.waterDepth
    direction = np.array(
        [
            math.cos(math.radians(structure.waveDirection)),
            math.sin(math.radians(structure.waveDirection)),
            0.0,
        ]
    )
    legs = 1 if structure.kind == "monopile" else 4
    blockage = float(t.blockage.get(str(legs), min(t.blockage.values())))
    growth = structure.marineGrowth / 1000
    cd = t.dragRough if growth > 0 else t.dragSmooth
    cm = t.inertiaRough if growth > 0 else t.inertiaSmooth
    pieces: list[_Piece] = []
    for k, (i, j, _) in enumerate(frame.members):
        a, b = frame.nodes[i], frame.nodes[j]
        length = float(np.linalg.norm(b - a))
        count = max(1, math.ceil(length / PIECE))
        axis = (b - a) / length
        diameter = types[geometry.members[k].type].width + 2 * growth
        for p in range(count):
            s = (p + 0.5) / count
            pieces.append(_Piece(k, 1 - s, a + s * (b - a), length / count, axis, diameter))
    rho = t.seawaterDensity

    def loads_at(phase: float) -> tuple[float, list[np.ndarray]]:
        forces = []
        shear = 0.0
        for piece in pieces:
            z = float(piece.middle[2]) - d
            x = float(piece.middle @ direction) - phase * wave.length
            u, w, du, dw = wave.kinematics(x, z)
            if z > wave.eta(x) + 1e-9 or z < -d:
                forces.append(np.zeros(3))
                continue
            current = structure.current * blockage * ((z + d) / d) ** t.currentExponent
            vel = direction * (t.kinematicsFactor * u + current) + np.array([0, 0, w])
            acc = direction * (t.kinematicsFactor * du) + np.array([0, 0, dw])
            vn = vel - (vel @ piece.axis) * piece.axis
            an = acc - (acc @ piece.axis) * piece.axis
            f = 0.5 * rho * cd * piece.diameter * np.linalg.norm(vn) * vn + (
                rho * cm * math.pi * piece.diameter**2 / 4 * an
            )
            forces.append(f * piece.length)
            shear += float(f @ direction) * piece.length
        return shear, forces

    best_phase, best_shear, best_forces = 0.0, 0.0, None
    for step in range(PHASES):
        phase = step / PHASES
        shear, forces = loads_at(phase)
        if best_forces is None or abs(shear) > abs(best_shear):
            best_phase, best_shear, best_forces = phase, shear, forces
    assert best_forces is not None
    environment = fr.Loads()
    for piece, f in zip(pieces, best_forces, strict=True):
        i, j, _ = frame.members[piece.member]
        environment.add_nodal(i, f * piece.share)
        environment.add_nodal(j, f * (1 - piece.share))
    top = max(float(p[2]) for p in frame.nodes)
    top_nodes = [n for n, p in enumerate(frame.nodes) if abs(float(p[2]) - top) < 1e-6]
    dead = fr.self_weight(frame)
    for n in top_nodes:
        dead.add_nodal(n, [0, 0, -structure.deckLoad * 1000 / len(top_nodes)])
        environment.add_nodal(n, direction * structure.deckWindForce * 1000 / len(top_nodes))
    results = fr.solve(frame, {"D": dead, "E": environment})
    pairs = [
        (
            f"{t.permanentFactor:g} D + {t.environmentalFactor:g} E",
            t.permanentFactor,
            t.environmentalFactor,
        ),
        (f"0.9 D + {t.environmentalFactor:g} E", 0.9, t.environmentalFactor),
    ]
    worst: dict[str, dict[str, Any]] = {}
    failing = 0
    for k in range(len(frame.members)):
        kind = types[geometry.members[k].type]
        best: tuple[float, str, float] | None = None
        for name, gd, ge in pairs:
            n = gd * results["D"].axial(k) + ge * results["E"].axial(k)
            m = gd * results["D"].end_moments(k)[5] + ge * results["E"].end_moments(k)[5]
            ratio, _ = common.check_member(kind, frame.length(k), 1.0, n, m)
            if best is None or ratio > best[0]:
                best = (ratio, name, n)
        assert best is not None
        if best[0] > 1.0:
            failing += 1
        role = roles[k]
        if role not in worst or best[0] > worst[role]["ratio"]:
            worst[role] = {
                "role": role,
                "member": k + 1,
                "type": kind.id,
                "section": kind.label,
                "length": round(frame.length(k), 2),
                "axial": round(best[2] / 1000, 1),
                "ratio": round(best[0], 3),
                "combination": best[1],
            }
    supports = sorted(frame.supports)
    base_shear = (
        abs(
            sum(
                float(results["E"].reactions[n] @ np.append(direction, [0, 0, 0])) for n in supports
            )
        )
        / 1000
    )
    clause = str((t.clauses or {}).get("morison", ""))
    notes.append(
        f"Morison ({code} {clause}): Cd {cd:g}, Cm {cm:g}, kinematics factor {t.kinematicsFactor:g}, "
        f"current blockage {blockage:g}, marine growth {structure.marineGrowth:g} mm; the "
        f"phase {best_phase:.2f} of the wave gives the largest base shear {abs(best_shear) / 1000:.0f} kN"
    )
    notes.append(
        "not covered: buoyancy, wave slam, the piles and soil (fixed at the mudline), fatigue, "
        "tubular joint checks, seismic, the topsides"
    )
    if failing:
        notes.append(f"{failing} member(s) of {len(frame.members)} exceed their resistance")
    return {
        "wave": {
            "theory": wave.theory,
            "length": round(wave.length, 2),
            "celerity": round(wave.c, 2),
            "crest": round(wave.eta(0.0), 2),
        },
        "baseShear": round(base_shear, 1),
        "rows": list(worst.values()),
        "members": len(frame.members),
        "failing": failing,
        "notes": notes,
    }
