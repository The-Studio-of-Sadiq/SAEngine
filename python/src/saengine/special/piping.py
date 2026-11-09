"""Piping stress: a pipe run on its supports under its weight, its thermal expansion and an
occasional lateral load, checked against the code pack's piping allowables (``pipingStress``).

Model: the route's straight runs as tube elements (OpenSees, :mod:`saengine.special.frame`) in
pieces of at most 1 m, the corners as bends (their flexibility is not modelled: the corner is a
sharp joint, stiffer than the bend, on the safe side for the expansion stresses at the
supports), on supports at route points: an anchor (every direction, a nozzle or fixed point), a
rest (vertical), a guide (vertical and across the pipe) or an axial stop (along the pipe), the
guide and stop across or along the run's nearer global axis. A direction no support holds is
held at the first support (said), so the run is stable.

Cases: W (the pipe, its contents and insulation), T (the temperature change from installation:
the equivalent nodal forces E A α ΔT of each element, its true axial force the frame's less E A α
ΔT) and O (W × the occasional share across the run, either horizontal way).

Stresses at every element end (B31.3 type, the pack's factors):

- bends: h = T R / r2², SIF in plane 0.9 / h^(2/3) and out of plane 0.75 / h^(2/3) (the pack's),
  at least 1; the larger is applied to the resultant bending moment (on the safe side); straight
  pipe i = 1;
- sustained SL = P Do / (4 tc) + |N| / Ac + max(1, 0.75 i) Mb / Zc (tc, Ac, Zc with the
  corrosion allowance) <= Sh;
- expansion SE = √(Sb² + 4 St²), Sb = i Mb / Z, St = Mt / (2 Z) <= SA = f (1.25 Sc + 0.25 Sh)
  (+ Sh - SL where the pack allows), f = 6.0 N^-0.2 at most the pack's limit;
- occasional SL + 0.75 i Mo / Zc <= k Sh;
- the wall for the pressure: t = P Do / (2 (S E W + P Y)) + c.

The anchors' forces and moments (nozzle loads) are given for W + T and W + O. Not covered: the
bends' flexibility factors and pressure stiffening, branch connections and their SIF, spring
hangers, friction at the supports, cold spring, creep range, and the equipment's allowable
nozzle loads. Units: m, mm, kN, MPa.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.special import frame as fr

G = 9.80665
#: Longest piece of a pipe run [m].
PIECE = 1.0


def allowable(material: Any, temperature: float) -> float:
    """S [MPa] at ``temperature`` [°C], linear between the table's points (held beyond)."""
    points = sorted(material.allowable)
    return float(np.interp(temperature, [p[0] for p in points], [p[1] for p in points]))


def range_factor(table: Any, cycles: float) -> float:
    return min(float(table.rangeFactorMax), table.rangeCoefficient * cycles**table.rangeExponent)


def bend_sif(table: Any, outside: float, wall: float, radius: float) -> tuple[float, float, float]:
    """(h, ii, io) of a bend of radius ``radius`` [mm]."""
    r2 = (outside - wall) / 2
    h = wall * radius / r2**2
    ii = max(1.0, table.elbowInPlane / h ** (2 / 3))
    io = max(1.0, table.elbowOutPlane / h ** (2 / 3))
    return h, ii, io


def _held(axis: np.ndarray, along: bool, vertical_too: bool) -> tuple[int, ...]:
    """Translational DOFs a guide (across) or stop (along) holds for a run along ``axis``."""
    a = np.abs(axis)
    main = int(np.argmax(a))
    out = [0, 0, 0]
    if along:
        out[main] = 1
    else:
        if main == 2:
            out[0] = out[1] = 1
        else:
            out[1 - main] = 1
    if vertical_too:
        out[2] = 1
    return (*out, 0, 0, 0)


def analyse_piping(system: Any) -> dict[str, Any]:
    pack = code_context.current()
    code = code_context.code_name(pack)
    if not pack.has("pipingStress"):
        raise ValueError(f"piping: not covered by the code pack {code}")
    t = pack.table("pipingStress")
    material = t.materials.get(system.material)
    if material is None:
        raise ValueError(f"piping {system.id}: no material '{system.material}' in the code pack")
    notes: list[str] = []
    do = system.outsideDiameter
    wall = system.wallThickness
    corroded = max(wall - system.corrosion, 0.1)
    e = material.modulus * 1e6
    section = fr.tube(do / 1000, wall / 1000, e, 0.3, material.density)
    di = do - 2 * wall
    content = system.contentDensity * math.pi * (di / 1000) ** 2 / 4  # kg/m
    w_line = section.mass * G + content * G + system.insulationWeight * 1000  # N/m
    points = [np.array([p.x, p.y, p.z], dtype=float) for p in system.route]
    frame = fr.Frame()
    for a, b in itertools.pairwise(points):
        length = float(np.linalg.norm(b - a))
        if length <= 0:
            continue
        count = max(1, math.ceil(length / PIECE))
        for k in range(count):
            frame.member(a + (b - a) * k / count, a + (b - a) * (k + 1) / count, section)
    route_nodes = [frame.node(p) for p in points]
    axes = []
    for i in range(len(points)):
        j = i + 1 if i + 1 < len(points) else i - 1
        v = points[j] - points[i] if j > i else points[i] - points[j]
        axes.append(v / np.linalg.norm(v))
    nozzles = []
    for s in system.supports:
        if s.kind == "anchor":
            fixity = (1, 1, 1, 1, 1, 1)
        elif s.kind == "rest":
            fixity = (0, 0, 1, 0, 0, 0)
        elif s.kind == "guide":
            fixity = _held(axes[s.at], along=False, vertical_too=True)
        else:
            fixity = _held(axes[s.at], along=True, vertical_too=False)
        frame.support(points[s.at], fixity)  # type: ignore[arg-type]
        if s.nozzle:
            nozzles.append(s.at)
    held = [max(f[d] for f in frame.supports.values()) for d in range(6)]
    if not all(held):
        first = points[system.supports[0].at]
        frame.support(first, tuple(1 - h for h in held))  # type: ignore[arg-type]
        names = [n for n, h in zip(("x", "y", "z", "rx", "ry", "rz"), held, strict=True) if not h]
        notes.append(f"held at the first support for stability: {', '.join(names)}")
    weight = fr.Loads()
    for k in range(len(frame.members)):
        weight.add_uniform(k, [0.0, 0.0, -w_line])
    thermal = fr.Loads()
    delta = system.temperature - system.installation
    for k, (i, j, _) in enumerate(frame.members):
        axis = frame.axes(k)[0][0]
        force = e * section.area * material.expansion * delta  # E A α ΔT
        thermal.add_nodal(i, -force * axis)
        thermal.add_nodal(j, force * axis)
    cases = {"W": weight, "T": thermal}
    if system.occasional > 0:
        for name, direction in (("OX", (1.0, 0.0, 0.0)), ("OY", (0.0, 1.0, 0.0))):
            loads = fr.Loads()
            for k in range(len(frame.members)):
                axis = frame.axes(k)[0][0]
                d = np.array(direction) - (np.array(direction) @ axis) * axis
                if np.linalg.norm(d) > 1e-6:
                    loads.add_uniform(k, system.occasional * w_line * d / np.linalg.norm(d))
            cases[name] = loads
    results = fr.solve(frame, cases)
    sh = allowable(material, system.temperature)
    sc = allowable(material, min(system.installation, system.temperature))
    f = range_factor(t, system.cycles)
    radius = system.bendRadius or 1.5 * do
    _, ii, io = bend_sif(t, do, wall, radius)
    bends = {route_nodes[k] for k in range(1, len(points) - 1)}
    z = math.pi * (do**4 - di**4) / (32 * do)  # mm³
    dci = do - 2 * corroded
    zc = math.pi * (do**4 - dci**4) / (32 * do)
    ac = math.pi * (do**2 - dci**2) / 4
    pressure = system.pressure * do / (4 * corroded)
    worst = {"SL": (0.0, 0), "SE": (0.0, 0, 1.0), "SO": (0.0, 0)}
    for k, (i, j, _) in enumerate(frame.members):
        for end, node in ((0, i), (1, j)):
            sif = max(ii, io) if node in bends else 1.0
            sus_i = max(1.0, t.sustainedIndex * sif)

            def bending(case: str, end: int = end, k: int = k) -> tuple[float, float]:
                mo = results[case].end_moments(k)
                mb = math.hypot(mo[0], mo[1]) if end == 0 else math.hypot(mo[2], mo[3])
                return mb * 1000, abs(mo[4]) * 1000  # N·mm

            mb_w, _ = bending("W")
            n_w = abs(results["W"].axial(k))
            sl = pressure + n_w / ac + sus_i * mb_w / zc
            mb_t, mt_t = bending("T")
            sb = sif * mb_t / z
            st = mt_t / (2 * z)
            se = math.sqrt(sb * sb + 4 * st * st)
            sa = f * (t.rangeShares[0] * sc + t.rangeShares[1] * sh)
            if t.liberal:
                sa += max(sh - sl, 0.0)
            so = 0.0
            for case in ("OX", "OY"):
                if case in results:
                    mb_o, _ = bending(case)
                    so = max(so, sus_i * mb_o / zc)
            if sl > worst["SL"][0]:
                worst["SL"] = (sl, node)
            if se / sa > worst["SE"][0] / worst["SE"][2]:
                worst["SE"] = (se, node, sa)
            if sl + so > worst["SO"][0]:
                worst["SO"] = (sl + so, node)
    clause = t.clauses or {}
    y = t.pressureY
    t_req = system.pressure * do / (2 * (sh + system.pressure * y)) + system.corrosion
    rows = [
        _row(
            "Pressure design thickness",
            t_req,
            wall,
            "mm",
            f"P Do / (2 (S E W + P Y)) + c, Y {y:g}" + _cite(code, clause.get("pressure")),
        ),
        _row(
            "Sustained stress SL",
            worst["SL"][0],
            sh,
            "MPa",
            f"at {_where(frame, worst['SL'][1])}; Sh at {system.temperature:g} °C"
            + _cite(code, clause.get("sustained")),
        ),
        _row(
            "Expansion stress range SE",
            worst["SE"][0],
            worst["SE"][2],
            "MPa",
            f"at {_where(frame, worst['SE'][1])}; f = {f:.2f}, ΔT {delta:g} °C"
            + _cite(code, clause.get("expansion")),
        ),
    ]
    if system.occasional > 0:
        k_sh = t.occasionalFactor * sh
        rows.append(
            _row(
                "Sustained + occasional",
                worst["SO"][0],
                k_sh,
                "MPa",
                f"at {_where(frame, worst['SO'][1])}; {t.occasionalFactor:g} Sh"
                + _cite(code, clause.get("occasional")),
            )
        )
    nozzle_rows = []
    for at in nozzles:
        node = route_nodes[at]
        for label, combo in (("W + T", ("W", "T")), ("W + O", ("W", "OX", "OY"))):
            total = np.zeros(6)
            for case in combo:
                if case in results:
                    r = results[case].reactions.get(node)
                    if r is not None:
                        total = total + (np.abs(r) if case.startswith("O") else r)
            nozzle_rows.append(
                {
                    "point": at,
                    "combination": label,
                    "force": round(float(np.linalg.norm(total[:3])) / 1000, 2),
                    "moment": round(float(np.linalg.norm(total[3:])) / 1000, 2),
                    "components": [round(float(v) / 1000, 2) for v in total],
                }
            )
    notes.append(
        f"{material.label}: Sc {sc:.1f} MPa, Sh {sh:.1f} MPa; bends R = {radius:.0f} mm, ii "
        f"{ii:.2f}, io {io:.2f}" + _cite(code, clause.get("sif"))
    )
    notes.append(
        "not covered: bend flexibility, branch connections, spring hangers, support friction, "
        "cold spring, creep range, the equipment's allowable nozzle loads"
    )
    return {"rows": rows, "nozzles": nozzle_rows, "notes": notes}


def _cite(code: str, clause: str | None) -> str:
    return f" ({code} {clause})" if clause else ""


def _where(frame: fr.Frame, node: int) -> str:
    p = frame.nodes[node]
    return f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}) m"


def _row(name: str, demand: float, capacity: float, unit: str, note: str) -> dict[str, Any]:
    ratio = demand / capacity if capacity else None
    return {
        "name": name,
        "demand": round(demand, 2),
        "capacity": round(capacity, 2),
        "unit": unit,
        "ratio": None if ratio is None else round(ratio, 3),
        "ok": None if ratio is None else ratio <= 1.0 + 1e-9,
        "note": note,
    }
