"""The hydraulic calculation of the fire mains (BNBC 2020 Part 4 Sec 4.2.1, 4.2.3.4, 4.2.3.5).

BNBC sizes the fire pipes "as per provisions of this Code or on the basis of the hydraulic design
of the system to maintain flow rate and duration of water discharge" (Sec 4.2.1). The network is
solved with WNTR running EPANET 2.2, as the plumbing's water supply
(:mod:`saengine.plumbing.hydraulics`, whose solver and fitting lengths are reused):

* the fire pump's discharge is a fixed-head source; the pump's head is what the most demanding
  scenario needs there, less the lowest water level of the fire tank (its suction);
* a header from the pump to the foot of each riser (plan distance |dx| + |dy| and the rise), the
  riser a chain of pipes between its floors, the hose outlet 1.5 m above the floor (Sec
  4.2.3.10) through its landing valve;
* standpipes (Sec 4.2.3.2): the hydraulically most remote standpipe takes the Table 4.4.1 flow at
  its top outlet, every other standpipe 1000 l/min (at most eight of them), at the residual
  pressure of Sec 4.2.3.3 (300 kPa; 200 kPa first-aid hose). With fixed flows the head losses do
  not depend on the source, so one solution gives the head the source needs;
* sprinklers: the design area on the highest sprinklered floor, at the far corner of that floor
  from its riser, as branch lines of heads; each head an EPANET emitter of its K factor (flow =
  K sqrt(p)), so that the heads nearer the riser give more than the least head's flow, as a
  hydraulic calculation does. The source head is found (secant iterations) at which the least
  head gives its design flow. A combined riser adds the standpipe flow at its top outlet at the
  same time (Sec 4.2.3.5);
* Hazen-Williams friction (C 120 steel, 150 copper), fittings as equivalent lengths from BNBC
  Tables 8.O.2(a)-(c).

Units: inside m, m³/s; the results l/min, m, kPa, m/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.fire import tables as T
from saengine.plumbing.hydraulics import KPA_PER_M, _new_network, _solve, fitting_length

#: Fittings SAEngine allows on each fire pipe (its own allowance, not BNBC's).
PUMP_FITTINGS = {"check": 1, "gate": 2, "elbow": 4}
RISER_FITTINGS = {"teeRun": 1}
OUTLET_FITTINGS = {"teeBranch": 1, "gate": 1, "elbow": 1}  # take-off and landing valve
FLOOR_FITTINGS = {"teeBranch": 1, "gate": 1, "check": 1, "elbow": 2}  # floor control valve set
BRANCH_FITTINGS = {"teeBranch": 1}


def bore(nominal: float, material: str = "steel") -> float:
    """Inside diameter [mm] of a nominal size (the next listed size up)."""
    table = T.COPPER_BORE if material == "copper" and nominal <= 100 else T.STEEL_BORE
    for size in sorted(table):
        if nominal <= size + 1e-9:
            return table[size]
    return float(nominal)


def velocity(flow_lpm: float, nominal: float, material: str = "steel") -> float:
    """Velocity [m/s] of ``flow_lpm`` in the pipe."""
    d = bore(nominal, material) / 1000.0
    return flow_lpm / 60000.0 / (math.pi * d * d / 4.0) if d > 0 else 0.0


def size_for(flow_lpm: float, material: str = "steel", least: float = 0.0) -> int:
    """The smallest nominal size, at least ``least``, carrying ``flow_lpm`` within
    :data:`~saengine.fire.tables.MAX_VELOCITY`."""
    for size in sorted(T.STEEL_BORE):
        if size + 1e-9 < least:
            continue
        if velocity(flow_lpm, size, material) <= T.MAX_VELOCITY + 1e-9:
            return int(size)
    return int(max(T.STEEL_BORE))


def emitter_coefficient(k: float) -> float:
    """EPANET's emitter coefficient [m³/s per m^0.5] of a K factor [l/min per bar^0.5]."""
    return k / 60000.0 / math.sqrt(100.0 / KPA_PER_M)


@dataclass
class Net:
    """A fire network to solve: nodes (name -> elevation m), pipes, fixed demands and emitters."""

    material: str = "steel"
    nodes: dict[str, float] = field(default_factory=dict)
    pipes: list[dict[str, Any]] = field(default_factory=list)
    demands: dict[str, float] = field(default_factory=dict)  # l/min
    emitters: dict[str, float] = field(default_factory=dict)  # K
    source: str = "PUMP"

    def node(self, name: str, z: float) -> str:
        self.nodes[name] = z
        return name

    def pipe(self, name: str, a: str, b: str, length: float, nominal: float,
             fittings: dict[str, int] | None = None, role: str = "") -> None:  # fmt: skip
        extra = fitting_length(nominal, fittings or {})
        self.pipes.append({"id": name, "a": a, "b": b, "length": max(length, 0.1),
                           "equivalent": extra, "nominal": nominal, "role": role})  # fmt: skip


def solve(net: Net, head: float) -> dict[str, Any]:
    """Pressures [m], flows [l/min] and velocities of ``net`` with the source at ``head`` [m]."""
    wn = _new_network()
    c = T.HAZEN_C.get(net.material, 120.0)
    wn.add_reservoir(net.source, base_head=head)
    for name, z in net.nodes.items():
        if name == net.source:
            continue
        wn.add_junction(name, base_demand=net.demands.get(name, 0.0) / 60000.0, elevation=z)
        if name in net.emitters:
            wn.get_node(name).emitter_coefficient = emitter_coefficient(net.emitters[name])
    for p in net.pipes:
        wn.add_pipe(p["id"], p["a"], p["b"], length=p["length"] + p["equivalent"],
                    diameter=bore(p["nominal"], net.material) / 1000.0, roughness=c)  # fmt: skip
    results = _solve(wn)
    pressure = results.node["pressure"].iloc[0].to_dict()
    flow = results.link["flowrate"].iloc[0].to_dict()
    demand = results.node["demand"].iloc[0].to_dict()
    pipes = []
    for p in net.pipes:
        q = abs(float(flow[p["id"]])) * 60000.0
        pipes.append({**p, "flow": round(q, 1),
                      "velocity": round(velocity(q, p["nominal"], net.material), 2)})  # fmt: skip
    heads = {n: float(pressure[n]) + z for n, z in net.nodes.items() if n in pressure}
    heads[net.source] = head
    _loss_along(pipes, heads)
    return {
        "pressure": {n: float(v) for n, v in pressure.items() if n != net.source},
        "flow": {n: float(v) * 60000.0 for n, v in demand.items() if n != net.source},
        "pipes": pipes,
        "total": -float(demand.get(net.source, 0.0)) * 60000.0,
    }


def _loss_along(pipes: list[dict[str, Any]], heads: dict[str, float]) -> None:
    for p in pipes:
        p["loss"] = round(heads[p["a"]] - heads[p["b"]], 3)


def fixed_head(net: Net, required: dict[str, float]) -> dict[str, Any]:
    """The source head [m] at which every node of ``required`` (name -> least pressure [m]) has
    its pressure, with fixed demands (no emitters); and the solution at that head."""
    trial = max(net.nodes.values()) + 300.0
    first = solve(net, trial)
    margin = min(first["pressure"][n] - p for n, p in required.items())
    head = trial - margin
    shift = head - trial
    pressure = {n: v + shift for n, v in first["pressure"].items()}
    heads = {n: pressure[n] + net.nodes[n] for n in pressure}
    heads[net.source] = head
    _loss_along(first["pipes"], heads)
    return {**first, "pressure": pressure, "head": head}


def emitter_head(net: Net, remote: list[str], least_flow: float, extra: dict[str, float]
                 ) -> dict[str, Any]:  # fmt: skip
    """The source head [m] at which the least of the ``remote`` emitters gives ``least_flow``
    [l/min] and the fixed-demand nodes of ``extra`` (name -> least pressure [m]) have their
    pressure; and the solution there (secant iterations on the head)."""
    k = next(iter(net.emitters.values()))
    need = (least_flow / k) ** 2 * 100.0 / KPA_PER_M  # m at the least head

    def shortfall(h: float) -> tuple[float, dict[str, Any]]:
        s = solve(net, h)
        worst = min(s["pressure"][n] - need for n in remote)
        if extra:
            worst = min(worst, *(s["pressure"][n] - p for n, p in extra.items()))
        return worst, s

    z = max(net.nodes[n] for n in remote)
    h0 = z + need + 20.0
    f0, _s0 = shortfall(h0)
    h1 = h0 - f0 * 1.2 + 1.0
    f1, s1 = shortfall(h1)
    for _ in range(12):
        if abs(f1) < 0.02:
            break
        slope = (f1 - f0) / (h1 - h0) if h1 != h0 else 1.0
        h2 = h1 - f1 / (slope if slope > 0.05 else 1.0)
        h0, f0 = h1, f1
        h1 = h2
        f1, s1 = shortfall(h1)
    heads = {n: s1["pressure"][n] + net.nodes[n] for n in s1["pressure"]}
    heads[net.source] = h1
    _loss_along(s1["pipes"], heads)
    return {**s1, "head": h1}


def _manhattan(a: tuple[float, float], b: tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class RiserRun:
    """A riser of the network: plan point [m], its floors (story, level m), size [mm]."""

    id: str
    system: str
    x: float
    y: float
    floors: list[tuple[str, float]]
    nominal: float


def build(
    pump: tuple[float, float, float],
    risers: list[RiserRun],
    material: str,
    header: float,
) -> tuple[Net, dict[str, dict[str, str]]]:
    """The pump, header and risers: ``{riser: {story: take-off node}}``."""
    net = Net(material=material)
    px, py, pz = pump
    net.node(net.source, pz)
    hub = net.node("HUB", pz)
    net.pipe("HEADER", net.source, hub, 1.0, header, PUMP_FITTINGS, "pump discharge")
    takeoffs: dict[str, dict[str, str]] = {}
    for r in risers:
        base_z = r.floors[0][1] if r.floors else pz
        foot = net.node(f"{r.id}:FOOT", min(base_z, pz))
        length = _manhattan((px, py), (r.x, r.y)) + abs(pz - min(base_z, pz))
        net.pipe(f"{r.id}:H", hub, foot, length, header, {"elbow": 2, "gate": 1}, "header")
        prev, prev_z = foot, min(base_z, pz)
        takeoffs[r.id] = {}
        for story, z in r.floors:
            node = net.node(f"{r.id}:{story}", z)
            net.pipe(f"{r.id}:R:{story}", prev, node, max(z - prev_z, 0.1), r.nominal,
                     RISER_FITTINGS, "riser")  # fmt: skip
            takeoffs[r.id][story] = node
            prev, prev_z = node, z
    return net, takeoffs


def outlet(net: Net, riser: RiserRun, takeoff: str, z: float, nominal: float) -> str:
    """The hose outlet of a take-off, 1.5 m above the floor (Sec 4.2.3.10)."""
    node = net.node(f"{takeoff}:OUT", z + T.OUTLET_HEIGHT)
    net.pipe(f"{takeoff}:O", takeoff, node, T.OUTLET_HEIGHT, nominal, OUTLET_FITTINGS, "outlet")
    return node


def design_area(
    net: Net,
    takeoff: str,
    start: tuple[float, float],
    far: tuple[float, float],
    head_z: float,
    floor: dict[str, Any],
    sizes: dict[str, float],
) -> list[str]:
    """The design area's branch lines from a floor take-off (riser at ``start``, the area at
    the floor's ``far`` corner): returns the head nodes. ``sizes``: ``cross`` and ``branch``
    nominal sizes [mm]."""
    s = floor["spacing"]
    nb, nl = floor["headsPerBranch"], floor["branches"]
    total = floor["designHeads"]
    run = max(_manhattan(start, far) - (nb - 1) * s - (nl - 1) * s, 1.0)
    valve = net.node(f"{takeoff}:FCV", head_z)
    net.pipe(f"{takeoff}:F", takeoff, valve, max(head_z - net.nodes[takeoff], 0.1),
             sizes["cross"], FLOOR_FITTINGS, "floor valve")  # fmt: skip
    cross = net.node(f"{takeoff}:X0", head_z)
    net.pipe(f"{takeoff}:XM", valve, cross, run, sizes["cross"], {"elbow": 2}, "cross main")
    heads: list[str] = []
    placed = 0
    for line in range(nl):
        if line:
            nxt = net.node(f"{takeoff}:X{line}", head_z)
            net.pipe(f"{takeoff}:XM{line}", cross, nxt, s, sizes["cross"], {"teeRun": 1},
                     "cross main")  # fmt: skip
            cross = nxt
        prev = cross
        for h in range(nb):
            if placed >= total:
                break
            node = net.node(f"{takeoff}:B{line}H{h}", head_z)
            net.pipe(f"{takeoff}:B{line}P{h}", prev, node, s if h else s / 2,
                     sizes["branch"], BRANCH_FITTINGS if not h else {}, "branch line")  # fmt: skip
            net.emitters[node] = T.K_FACTOR
            heads.append(node)
            prev = node
            placed += 1
    return heads
