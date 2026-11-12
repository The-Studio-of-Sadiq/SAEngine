"""Rebuild the solver-neutral model (``ir.py``) in CalculiX and run it with ``ccx``.

    python -I run_ccx.py --ir ir.json --ccx <path to ccx.exe> --work <dir> --out ccx.json

CalculiX (GPL, http://www.calculix.de) is used as a separate program: this script writes its
input decks (``.inp``), starts ``ccx`` as a subprocess and reads its ``.dat`` output. Nothing
of CalculiX is linked or shipped with SAEngine.

The deck, element by element (no remeshing):

- frames: CalculiX's user element **U1** (a two-node 3D Timoshenko beam that is not expanded
  into solid elements, so it keeps general section properties A, I11, I22): the shear factor
  is set very high (Euler-Bernoulli, as OpenSees ``elasticBeamColumn``), local direction 1 is
  SAEngine's local y (I11 = Iz, I22 = Iy). U1 takes its torsional stiffness from the polar
  moment I11 + I22, so the shear modulus is scaled by J / (Iy + Iz) to give G·J (as far as a
  Poisson's ratio below 0.5 allows: a deep rectangle stays stiffer in torsion). U1 takes no
  span loads: a uniform load becomes its consistent nodal loads, and the element end forces
  get the fixed-end forces back (``fixed_end``). Its torsional moment output is not usable.
- rigid end zones (OpenSees ``-jntOffset``): a node at each flexible end, tied to its joint by
  the six rigid-link equations (``*EQUATION``; the same kinematics as ``-jntOffset``);
- pinned ends (``ZeroLength`` twins): the twin node tied to its main node in the listed DOFs;
- shells: the user element **US3** (three-node shell, six DOFs per node, not expanded); a
  quadrilateral becomes two triangles over its shorter diagonal; layered sections (cracked
  bending, see ``ir.layers``) become coincident elements;
- rigid diaphragms: ``*EQUATION`` per constrained node (u_x, u_y, r_z follow the retained node);
- a node that only equations use (a retained node, a joint whose members all have rigid zones)
  gets a negligible beam to a fixed node: CalculiX gives a node rotational DOFs only through
  its elements, and an equation on a missing rotation holds it at zero;
- masses: ``MASS`` elements on auxiliary nodes tied to the structural node in one direction
  each (CalculiX's point mass acts in all three directions; SAEngine lumps horizontal mass
  only); a rotary inertia Iz becomes a unit-arm auxiliary mass tied to r_z;
- every static case one ``*STEP`` (``*STATIC``), the modal case its own deck (``*FREQUENCY``).

Every equation is written in independent DOFs only (``Ties.resolve``), and loads on tied
DOFs are moved to the independent ones by virtual work. Units: the model's (m, N, kg, s).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

#: The shear factor of U1: shear deformation negligible (Euler-Bernoulli).
SHEAR_FACTOR = 1.0e5
#: A retained node with no element gets this beam to a fixed node (a negligible stiffness).
DUMMY = {"A": 1e-8, "I": 1e-10}
#: CalculiX rejects a Poisson's ratio of 0.5 and above (it caps U1's torsional correction).
MAX_NU = 0.499
Dof = tuple[int, int]  # (node, dof 1..6)


# ─────────────────────────────── linear constraints ───────────────────────────────


class Ties:
    """Linear constraints ``u[dep] = Σ c · u[indep]``, resolved to independent DOFs only."""

    def __init__(self) -> None:
        self.raw: dict[Dof, list[tuple[Dof, float]]] = {}

    def add(self, dep: Dof, terms: list[tuple[Dof, float]]) -> None:
        if dep in self.raw:
            raise ValueError(f"DOF {dep} is tied twice")
        self.raw[dep] = [(d, c) for d, c in terms if c != 0.0]

    def resolve(self) -> dict[Dof, dict[Dof, float]]:
        done: dict[Dof, dict[Dof, float]] = {}

        def expand(dep: Dof, stack: tuple[Dof, ...]) -> dict[Dof, float]:
            if dep in done:
                return done[dep]
            if dep in stack:
                raise ValueError(f"circular ties through {dep}")
            out: dict[Dof, float] = {}
            for d, c in self.raw[dep]:
                if d in self.raw:
                    for d2, c2 in expand(d, (*stack, dep)).items():
                        out[d2] = out.get(d2, 0.0) + c * c2
                else:
                    out[d] = out.get(d, 0.0) + c
            done[dep] = {d: c for d, c in out.items() if abs(c) > 1e-14}
            return done[dep]

        for dep in self.raw:
            expand(dep, ())
        return done


def rigid_link(ties: Ties, joint: int, follower: int, r: np.ndarray) -> None:
    """``follower`` moves with ``joint`` as a rigid body (``r`` from the joint to it)."""
    rx, ry, rz = (float(v) for v in r)
    ties.add((follower, 1), [((joint, 1), 1.0), ((joint, 5), rz), ((joint, 6), -ry)])
    ties.add((follower, 2), [((joint, 2), 1.0), ((joint, 6), rx), ((joint, 4), -rz)])
    ties.add((follower, 3), [((joint, 3), 1.0), ((joint, 4), ry), ((joint, 5), -rx)])
    for k in (4, 5, 6):
        ties.add((follower, k), [((joint, k), 1.0)])


def fixed_end(w: np.ndarray, x: np.ndarray, length: float, at_j: bool) -> tuple[np.ndarray, ...]:
    """Section resultant (force, moment; the part beyond the section acting on the part before)
    at end i or j of a fixed-ended element of ``length`` under the uniform global load ``w``:
    F = w (L/2 - s), M = (x × w)(L²/12 - L s/2 + s²/2), s the distance from end i."""
    s = length if at_j else 0.0
    force = w * (length / 2 - s)
    moment = np.cross(x, w) * (length**2 / 12 - length * s / 2 + s * s / 2)
    return force, moment


# ─────────────────────────────── the deck ───────────────────────────────


class Deck:
    """One CalculiX model of an analysis group of the description."""

    def __init__(self, ir: dict[str, Any], group: dict[str, Any]) -> None:
        self.ir, self.group = ir, group
        self.notes: list[str] = []
        self.xyz: dict[int, np.ndarray] = {n["id"]: np.asarray(n["xyz"]) for n in ir["nodes"]}
        self.restraint = {n["id"]: n["restraint"] for n in ir["nodes"]}
        self.next_node = max(self.xyz) + 1
        self.ties = Ties()
        self.fixed: dict[int, list[int]] = {}
        self.beams: list[dict[str, Any]] = []  # U1: id, a, b, section, dir1
        self.tris: list[dict[str, Any]] = []  # US3: id, nodes, layer (E, h, nu), shell
        self.masses: list[tuple[int, float]] = []  # (aux node, mass)
        self.frame_ends: dict[int, tuple[int, int]] = {}  # frame id -> flexible end nodes
        self.frame_elem: dict[int, int] = {}
        self.shell_elems: dict[int, list[int]] = {}
        self._build()

    def new_node(self, at: np.ndarray) -> int:
        nid = self.next_node
        self.next_node += 1
        self.xyz[nid] = np.asarray(at, dtype=float)
        return nid

    def _build(self) -> None:
        ir, group = self.ir, self.group
        in_element: set[int] = set()
        for t in ir["twins"]:
            for k in t["dofs"]:
                self.ties.add((t["twin"], k), [((t["main"], k), 1.0)])
        eid = 0
        for f in ir["frames"]:
            a, b = f["i"], f["j"]
            off = f.get("offsets")
            if off:
                for end, (joint, vec) in enumerate(((a, off[0:3]), (b, off[3:6]))):
                    r = np.asarray(vec, dtype=float)
                    if np.linalg.norm(r) < 1e-12:
                        continue
                    node = self.new_node(self.xyz[joint] + r)
                    rigid_link(self.ties, joint, node, r)
                    if end == 0:
                        a = node
                    else:
                        b = node
            eid += 1
            self.beams.append(
                {"id": eid, "a": a, "b": b, "section": str(f["section"]), "dir1": f["axes"]["y"]}
            )
            self.frame_ends[f["id"]] = (a, b)
            self.frame_elem[f["id"]] = eid
            in_element.update((a, b))
        for s in ir["shells"]:
            sec = group["shellSections"][str(s["section"])]
            nodes = s["nodes"]
            if len(nodes) == 4:
                p = [self.xyz[n] for n in nodes]
                if np.linalg.norm(p[2] - p[0]) <= np.linalg.norm(p[3] - p[1]):
                    tris = [(nodes[0], nodes[1], nodes[2]), (nodes[0], nodes[2], nodes[3])]
                else:
                    tris = [(nodes[0], nodes[1], nodes[3]), (nodes[1], nodes[2], nodes[3])]
            else:
                tris = [tuple(nodes)]
            ids = []
            for k, (e_layer, h_layer) in enumerate(sec["layers"]):
                for tri in tris:
                    eid += 1
                    self.tris.append(
                        {
                            "id": eid,
                            "nodes": tri,
                            "E": e_layer,
                            "h": h_layer,
                            "nu": sec["nu"],
                            "layer": k,
                            "shell": s["id"],
                        }
                    )
                    ids.append(eid)
            self.shell_elems[s["id"]] = ids
            in_element.update(nodes)
        for d in ir["diaphragms"]:
            m = d["retained"]
            if d["perp"] != 3:
                self.notes.append(f"diaphragm at node {m}: perp_dir {d['perp']} not rebuilt")
                continue
            xm, ym = self.xyz[m][0], self.xyz[m][1]
            for n in d["nodes"]:
                if n == m:
                    continue
                dx, dy = self.xyz[n][0] - xm, self.xyz[n][1] - ym
                self.ties.add((n, 1), [((m, 1), 1.0), ((m, 6), -dy)])
                self.ties.add((n, 2), [((m, 2), 1.0), ((m, 6), dx)])
                self.ties.add((n, 6), [((m, 6), 1.0)])
        # A node that only equations use (a retained node, the joint of members that all have
        # rigid zones) has no rotational DOFs in CalculiX unless an element gives it some: it
        # gets a negligible beam to a fixed node (without it, its rotations act as held)
        for node in sorted({d[0] for terms in self.ties.raw.values() for d, _ in terms}):
            if node in in_element:
                continue
            ground = self.new_node(self.xyz[node] - np.array([0.0, 0.0, 1.0]))
            eid += 1
            self.beams.append(
                {"id": eid, "a": ground, "b": node, "section": "DUMMY", "dir1": [1.0, 0.0, 0.0]}
            )
            self.fixed[ground] = [1, 2, 3, 4, 5, 6]
            in_element.add(node)
        active = in_element
        for n in ir["nodes"]:
            held = [k + 1 for k, r in enumerate(n["restraint"]) if r]
            if held and n["id"] in active:
                self.fixed[n["id"]] = held
            mass = n["mass"]
            for k in range(3):
                if mass[k] > 0:
                    aux = self.new_node(self.xyz[n["id"]])
                    self.ties.add((aux, k + 1), [((n["id"], k + 1), 1.0)])
                    self.fixed[aux] = [j for j in (1, 2, 3) if j != k + 1]
                    self.masses.append((aux, mass[k]))
            for k in range(3, 6):
                if mass[k] > 0:
                    # a unit-arm mass moving with the rotation: kinetic energy Iz·θ²/2
                    axis = np.eye(3)[k - 3]
                    arm = np.eye(3)[(k - 2) % 3]
                    aux = self.new_node(self.xyz[n["id"]] + arm)
                    direction = int(np.argmax(np.abs(np.cross(axis, arm)))) + 1
                    sign = float(np.cross(axis, arm)[direction - 1])
                    self.ties.add((aux, direction), [((n["id"], k + 1), sign)])
                    self.fixed[aux] = [j for j in (1, 2, 3) if j != direction]
                    self.masses.append((aux, mass[k]))
        self.resolved = self.ties.resolve()
        for node, dofs in list(self.fixed.items()):
            clash = [k for k in dofs if (node, k) in self.resolved]
            if clash:
                self.notes.append(f"node {node}: restrained DOFs {clash} are tied, kept tied")
                self.fixed[node] = [k for k in dofs if k not in clash]
        # the supports (a diaphragm's retained node is held out of plane only to be solvable)
        masters = {d["retained"] for d in ir["diaphragms"]}
        self.supports = sorted(
            n["id"] for n in ir["nodes"] if any(n["restraint"]) and n["id"] not in masters
        )
        # nodes tied to a support in all three translations (a pinned end's twin, a rigid zone
        # from a support): their elements' forces reach the support through the ties
        held = set(self.supports)
        tied: dict[int, set[int]] = {}
        for (node, k), terms in self.ties.raw.items():
            if k <= 3 and terms and all(d[0] in held for d, _ in terms):
                tied.setdefault(node, set()).add(k)
        self.support_cluster = sorted(held | {n for n, ks in tied.items() if ks == {1, 2, 3}})

    # ─────────── loads ───────────

    def loads_of(self, case: dict[str, Any]) -> dict[Dof, float]:
        """Nodal loads of a case on independent DOFs (span loads as consistent nodal loads)."""
        out: dict[Dof, float] = {}

        def put(node: int, k: int, value: float) -> None:
            if value == 0.0:
                return
            if (node, k) in self.resolved:
                for d, c in self.resolved[(node, k)].items():
                    out[d] = out.get(d, 0.0) + c * value
            else:
                out[(node, k)] = out.get((node, k), 0.0) + value

        for node, forces in case["nodal"]:
            for k, v in enumerate(forces):
                put(int(node), k + 1, float(v))
        for fid, w in case["element"]:
            a, b = self.frame_ends[int(fid)]
            w = np.asarray(w, dtype=float)
            x = self.xyz[b] - self.xyz[a]
            length = float(np.linalg.norm(x))
            x /= length
            m = np.cross(x, w) * length**2 / 12
            for k in range(3):
                put(a, k + 1, w[k] * length / 2)
                put(b, k + 1, w[k] * length / 2)
                put(a, k + 4, m[k])
                put(b, k + 4, -m[k])
        return out

    # ─────────── writing ───────────

    def write(self, path: Path, steps: list[tuple[str, dict[str, Any] | None]], modes: int) -> None:
        g = self.group
        lines = [
            "** SAEngine cross-check: the derived analysis model in CalculiX",
            "*NODE, NSET=NALL",
        ]
        lines += [f"{n},{p[0]:.9g},{p[1]:.9g},{p[2]:.9g}" for n, p in sorted(self.xyz.items())]
        by_section: dict[str, list[dict[str, Any]]] = {}
        for b in self.beams:
            by_section.setdefault(b["section"] + "|" + json.dumps(b["dir1"]), []).append(b)
        lines.append("*USER ELEMENT,TYPE=U1,NODES=2,INTEGRATION POINTS=2,MAXDOF=6")
        if self.tris:
            lines.append("*USER ELEMENT,TYPE=US3,NODES=3,INTEGRATION POINTS=3,MAXDOF=6")
        for k, (key, items) in enumerate(sorted(by_section.items())):
            lines.append(f"*ELEMENT, TYPE=U1, ELSET=B{k}")
            lines += [f"{b['id']},{b['a']},{b['b']}" for b in items]
        layers: dict[tuple[float, float, float], list[dict[str, Any]]] = {}
        for t in self.tris:
            layers.setdefault((t["E"], t["h"], t["nu"]), []).append(t)
        for k, (_, items) in enumerate(sorted(layers.items())):
            lines.append(f"*ELEMENT, TYPE=US3, ELSET=S{k}")
            lines += [f"{t['id']},{t['nodes'][0]},{t['nodes'][1]},{t['nodes'][2]}" for t in items]
        if self.masses:
            lines.append("*ELEMENT, TYPE=MASS, ELSET=MASSES")
            first = max([b["id"] for b in self.beams] + [t["id"] for t in self.tris] + [0]) + 1
            for k, (node, _) in enumerate(self.masses):
                lines.append(f"{first + k},{node}")
            for k, (_, value) in enumerate(self.masses):
                lines += [
                    f"*ELSET, ELSET=M{k}",
                    str(first + k),
                    f"*MASS, ELSET=M{k}",
                    f"{value:.9g}",
                ]
        # sections and materials
        for k, (key, items) in enumerate(sorted(by_section.items())):
            sec_id = items[0]["section"]
            dir1 = items[0]["dir1"]
            if sec_id == "DUMMY":
                e, nu, a, i11, i22 = 1.0e9, 0.3, DUMMY["A"], DUMMY["I"], DUMMY["I"]
            else:
                s = g["frameSections"][sec_id]
                a, i11, i22 = s["A"], s["Iz"], s["Iy"]
                g_eff = s["G"] * s["J"] / (s["Iy"] + s["Iz"])
                e, nu = s["E"], s["E"] / (2 * g_eff) - 1
                if nu > MAX_NU:
                    excess = s["E"] / (2 * (1 + MAX_NU)) / g_eff - 1
                    self.notes.append(
                        f"section {sec_id}: U1 torsional stiffness G·(Iy + Iz) cannot go below "
                        f"E·(Iy + Iz)/3; G·J is {excess:.0%} too high"
                    )
                    nu = MAX_NU
            lines += [
                f"*MATERIAL, NAME=MB{k}",
                "*ELASTIC",
                f"{e:.9g},{nu:.9g}",
                f"*BEAM SECTION, ELSET=B{k}, MATERIAL=MB{k}, SECTION=GENERAL",
                f"{a:.9g},{i11:.9g},0.,{i22:.9g},{SHEAR_FACTOR:g}",
                f"{dir1[0]:.9g},{dir1[1]:.9g},{dir1[2]:.9g}",
            ]
        for k, ((e, h, nu), _) in enumerate(sorted(layers.items())):
            lines += [
                f"*MATERIAL, NAME=MS{k}",
                "*ELASTIC",
                f"{e:.9g},{nu:.9g}",
                f"*USER SECTION, ELSET=S{k}, MATERIAL=MS{k}, CONSTANTS=1",
                f"{h:.9g}",
            ]
        # constraints
        if self.resolved:
            lines.append("*EQUATION")
            for (node, k), terms in sorted(self.resolved.items()):
                items = [(node, k, 1.0)] + [(d[0], d[1], -c) for d, c in sorted(terms.items())]
                lines.append(str(len(items)))
                flat = [f"{n},{dof},{c:.12g}" for n, dof, c in items]
                for start in range(0, len(flat), 4):  # at most 12 entries per line
                    lines.append(",".join(flat[start : start + 4]))
        lines.append("*BOUNDARY")
        for node, dofs in sorted(self.fixed.items()):
            lines += [f"{node},{k},{k}" for k in dofs]
        # output sets
        probes = self.ir["probes"]
        if probes["nodes"]:
            lines += ["*NSET, NSET=PROBES"] + [str(n) for n in probes["nodes"]]
        lines += ["*NSET, NSET=SUPPORTS"] + [str(n) for n in self.support_cluster]
        frames = [self.frame_elem[f] for f in self.probe_frames() if f in self.frame_elem]
        if frames:
            lines += ["*ELSET, ELSET=FPROBES"] + [str(e) for e in frames]
        shells = [e for s in probes["shells"] for e in self.shell_elems.get(s, [])]
        if shells:
            lines += ["*ELSET, ELSET=SPROBES"] + [str(e) for e in shells]
        at_supports = self.support_beams()
        if at_supports:
            lines += ["*ELSET, ELSET=FSUPPORTS"] + [str(b["id"]) for b in at_supports]
        for name, case in steps:
            lines += (
                ["*STEP", "*STATIC"] if case is not None else ["*STEP", "*FREQUENCY", str(modes)]
            )
            if case is not None:
                lines.append("*CLOAD, OP=NEW")
                for (node, k), v in sorted(self.loads_of(case).items()):
                    lines.append(f"{node},{k},{v:.12g}")
            if probes["nodes"]:
                lines += ["*NODE PRINT, NSET=PROBES", "U"]
            if case is not None:
                lines += ["*NODE PRINT, NSET=SUPPORTS", "RF"]
                if at_supports:
                    lines += ["*EL PRINT, ELSET=FSUPPORTS", "S"]
                if frames:
                    lines += ["*EL PRINT, ELSET=FPROBES", "S"]
                if shells:
                    lines += ["*EL PRINT, ELSET=SPROBES", "S"]
            lines.append("*END STEP")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def support_beams(self) -> list[dict[str, Any]]:
        held = set(self.support_cluster)
        return [b for b in self.beams if b["section"] != "DUMMY" and {b["a"], b["b"]} & held]

    def reactions(
        self, rf: list[list[float]], stress: dict[int, dict[int, list[float]]], case: dict[str, Any]
    ) -> list[float]:
        """Total support reaction [FX, FY, FZ]. CalculiX's RF of a support node is the internal
        force of the elements at it (the load put on the node itself left out), and U1 reports
        the axial part of its internal force with the wrong sign (CalculiX 2.23: a vertical
        column's base shows -N where +N is due; the section forces and displacements are
        right): that part is put right with the element's own axial force (its ``S``), and the
        node's applied load is taken off: R = f_int - P."""
        total = np.zeros(3)
        for r in rf:
            total += r[1:4]
        for b in self.support_beams():
            rows = stress.get(b["id"])
            if rows is None:
                continue
            x = self.xyz[b["b"]] - self.xyz[b["a"]]
            x /= np.linalg.norm(x)
            if b["a"] in self.support_cluster:
                total += 2 * (-rows[1][0]) * x  # axial force on the element at end i
            if b["b"] in self.support_cluster:
                total += 2 * rows[2][0] * x
        for (node, k), v in self.loads_of(case).items():
            if k <= 3 and node in self.supports:
                total[k - 1] -= v
        return total.tolist()

    def probe_frames(self) -> list[int]:
        """The probed frames and the elements their faces lie on."""
        out = list(self.ir["probes"]["frames"])
        for fid in list(out):
            for face in (self.ir["faces"].get(str(fid)) or {}).values():
                at = int(face["at"][0])
                if at not in out:
                    out.append(at)
        return out


# ─────────────────────────────── reading the .dat ───────────────────────────────

NUM = r"[-+]?\d*\.?\d+(?:[EeDd][-+]?\d+)?"


def parse_dat(text: str) -> list[dict[str, Any]]:
    """The steps of a ``.dat`` file: per step its blocks ``{title: rows}``."""
    steps: list[dict[str, Any]] = []
    for chunk in re.split(r"S T E P\s+\d+", text)[1:]:
        blocks: dict[str, list[list[float]]] = {}
        title = None
        for line in chunk.splitlines():
            s = line.strip()
            if not s:
                continue
            if " for set " in s or re.match(r"^(?:[A-Z] ){3,}", s):
                title = s
                blocks.setdefault(title, [])
                continue
            nums = re.findall(NUM, s)
            if title is not None and nums and len(nums) == len(s.split()):
                blocks[title].append([float(v.replace("D", "E").replace("d", "e")) for v in nums])
        steps.append(blocks)
    return steps


def _block(blocks: dict[str, Any], start: str) -> list[list[float]]:
    for title, rows in blocks.items():
        if title.lower().startswith(start):
            return rows
    return []


def _block_set(blocks: dict[str, Any], start: str, nset: str) -> list[list[float]]:
    for title, rows in blocks.items():
        if title.lower().startswith(start) and f" set {nset.lower()} " in title.lower() + " ":
            return rows
    return []


def frame_forces(deck: Deck, rows: list[list[float]], case: dict[str, Any]) -> dict[str, Any]:
    """Section forces [N, Vy, Vz, T, My, Mz] of the probed frames (SAEngine's local axes and
    convention: the part beyond the section acting on the part before, as
    ``saengine.fem.end_zones.section_at``) at the flexible ends and at the support faces on
    them, with the fixed-end forces of the span load added back. T is not available (U1's
    torsion output is not usable)."""
    by_elem: dict[int, dict[int, list[float]]] = {}
    for r in rows:
        by_elem.setdefault(int(r[0]), {})[int(r[1])] = r[2:8]
    loads = {int(f): np.asarray(w, dtype=float) for f, w in case["element"]}
    frames = {f["id"]: f for f in deck.ir["frames"]}
    out: dict[str, Any] = {}
    for fid in deck.probe_frames():
        e = deck.frame_elem.get(fid)
        if e is None or e not in by_elem:
            continue
        f = frames[fid]
        x, y, z = (np.asarray(f["axes"][k]) for k in ("x", "y", "z"))
        a, b = deck.frame_ends[fid]
        length = float(np.linalg.norm(deck.xyz[b] - deck.xyz[a]))
        w = loads.get(fid, np.zeros(3))
        sxx, syy, szz, sxy, sxz, _ = by_elem[e][1]
        force = sxx * x - sxy * y - sxz * z
        moment = szz * y - syy * z
        df, dm = fixed_end(w, x, length, at_j=False)
        force, moment = force + df, moment + dm

        def at(
            s: float,
            force: np.ndarray = force,
            moment: np.ndarray = moment,
            w: np.ndarray = w,
            x: np.ndarray = x,
            y: np.ndarray = y,
            z: np.ndarray = z,
        ) -> list[float | None]:
            fs = force - w * s
            ms = moment - s * np.cross(x, force) + s * s / 2 * np.cross(x, w)
            return [float(fs @ x), float(fs @ y), float(fs @ z), None, float(ms @ y), float(ms @ z)]

        stations = {}
        for key, ends in deck.ir["faces"].items():
            for end, face in ends.items():
                if int(face["at"][0]) == fid:
                    stations[f"{key}/{end}"] = at(float(face["at"][1]) - f["rigid"][0])
        out[str(fid)] = {
            "length": length,
            "ends": {"i": at(0.0), "j": at(length)},
            "stations": stations,
        }
    return out


def shell_forces(deck: Deck, rows: list[list[float]]) -> dict[str, Any]:
    """Shell resultants at the probed shells (per unit width): membrane N and moment M tensors
    in the element plane, from the stresses US3 reports at the bottom, middle and top of the
    thickness (in the triangle's own axes: x along its first edge, z its normal), summed over
    the layers and averaged over the triangles of a quadrilateral; reported as invariants."""
    by_elem: dict[int, dict[int, list[float]]] = {}
    for r in rows:
        by_elem.setdefault(int(r[0]), {})[int(r[1])] = r[2:8]
    tris = {t["id"]: t for t in deck.tris}
    shells = {s["id"]: s for s in deck.ir["shells"]}
    out: dict[str, Any] = {}
    for sid in deck.ir["probes"]["shells"]:
        quad = in_plane_axes([deck.xyz[n] for n in shells[sid]["nodes"]])
        per_tri: dict[tuple[int, ...], list[np.ndarray]] = {}
        for eid in deck.shell_elems.get(sid, []):
            if eid not in by_elem:
                continue
            t = tris[eid]
            axes = in_plane_axes([deck.xyz[n] for n in t["nodes"]])
            turn = quad @ axes.T  # triangle axes -> the quadrilateral's

            def plane(v: list[float], turn: np.ndarray = turn) -> np.ndarray:
                sxx, syy, _, sxy, _, _ = v
                return turn @ np.array([[sxx, sxy], [sxy, syy]]) @ turn.T

            bottom, mid, top = (plane(by_elem[eid][k]) for k in (1, 2, 3))
            h = t["h"]
            acc = per_tri.setdefault(t["nodes"], [np.zeros((2, 2)), np.zeros((2, 2))])
            acc[0] += mid * h
            acc[1] += (top - bottom) / 2 * h * h / 6
        if not per_tri:
            continue
        n_avg = sum(v[0] for v in per_tri.values()) / len(per_tri)
        m_avg = sum(v[1] for v in per_tri.values()) / len(per_tri)
        out[str(sid)] = {"N": invariants(n_avg), "M": invariants(m_avg)}
    return out


def in_plane_axes(p: list[np.ndarray]) -> np.ndarray:
    """Rows e1 (along the first edge) and e2 (in the plane, normal × e1) of a shell element."""
    e1 = (p[1] - p[0]) / np.linalg.norm(p[1] - p[0])
    normal = np.cross(p[1] - p[0], p[2] - p[0])
    normal /= np.linalg.norm(normal)
    return np.array([e1, np.cross(normal, e1)])


def invariants(t: np.ndarray) -> dict[str, float]:
    """Mean and deviator radius of a 2×2 resultant tensor: the principal values are
    mean ± radius (independent of the element's in-plane axes)."""
    mean = (t[0, 0] + t[1, 1]) / 2
    radius = math.hypot((t[0, 0] - t[1, 1]) / 2, (t[0, 1] + t[1, 0]) / 2)
    return {"mean": float(mean), "radius": float(radius)}


def modal_results(blocks: dict[str, Any], total: list[float]) -> dict[str, Any]:
    eig = [r for r in _block(blocks, "e i g e n v a l u e   o u t p u t") if r[2] > 0]
    periods = [2 * math.pi / r[2] for r in eig]
    eff = _block(blocks, "e f f e c t i v e   m o d a l   m a s s")
    eff_mass = [[r[1], r[2]] for r in eff[: len(periods)]]
    return {"periods": periods, "effMass": eff_mass, "massTotal": total}


# ─────────────────────────────── running ───────────────────────────────


def ccx_version(ccx: Path, work: Path) -> str:
    done = subprocess.run([str(ccx), "-v"], cwd=work, capture_output=True, text=True, check=False)
    found = re.search(r"Version\s+([\d.]+)", done.stdout + done.stderr)
    return found.group(1) if found else "unknown"


def run_deck(ccx: Path, inp: Path, threads: int) -> str:
    env = {**os.environ, "OMP_NUM_THREADS": str(threads), "CCX_NPROC_EQUATION_SOLVER": str(threads)}
    done = subprocess.run(
        [str(ccx), "-i", inp.stem],
        cwd=inp.parent,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=7200,
    )
    log = done.stdout + done.stderr
    (inp.parent / f"{inp.stem}.log").write_text(log, encoding="utf-8")
    dat = inp.with_suffix(".dat")
    # ARPACK's "*ERROR in d[n,s]aupd: info=-9999" with the eigenvalues it did converge is a
    # warning: the modes are written
    errors = [ln for ln in log.splitlines() if "*ERROR" in ln and "aupd" not in ln]
    if done.returncode != 0 or errors or not dat.exists():
        if threads > 1 and done.returncode != 0:
            return run_deck(ccx, inp, 1)  # a tiny eigenproblem can crash ccx's threaded solver
        raise RuntimeError(f"ccx failed on {inp.name} (exit {done.returncode}): {errors[:8]}")
    return dat.read_text(encoding="utf-8", errors="replace")


def run(ir: dict[str, Any], ccx: Path, work: Path, threads: int = 2) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result: dict[str, Any] = {
        "solver": "CalculiX",
        "version": ccx_version(ccx, work),
        "cases": {},
        "notes": [],
    }
    total = [sum(n["mass"][k] for n in ir["nodes"]) for k in range(3)]
    for group in ir["groups"]:
        analyses = [a for a in ir["analyses"] if a["group"] == group["name"]]
        statics = [a["code"] for a in analyses if a["type"] == "Static"]
        modal = next((a for a in analyses if a["type"] == "Modal"), None)
        deck = Deck(ir, group)
        result["notes"] += deck.notes
        if statics:
            inp = work / f"{group['name']}_static.inp"
            deck.write(inp, [(c, ir["cases"][c]) for c in statics], 0)
            steps = parse_dat(run_deck(ccx, inp, threads))
            for code, blocks in zip(statics, steps, strict=True):
                disp = _block_set(blocks, "displacements", "PROBES")
                rf = _block_set(blocks, "forces", "SUPPORTS")
                stress: dict[int, dict[int, list[float]]] = {}
                for title, rows in blocks.items():
                    if title.lower().startswith("stresses"):
                        for r in rows:
                            stress.setdefault(int(r[0]), {})[int(r[1])] = r[2:8]
                result["cases"][code] = {
                    "reactions": deck.reactions(rf, stress, ir["cases"][code]),
                    "disp": {str(int(r[0])): r[1:7] for r in disp},
                    "frames": frame_forces(
                        deck, _rows_of(blocks, deck, "frames"), ir["cases"][code]
                    ),
                    "shells": shell_forces(deck, _rows_of(blocks, deck, "shells")),
                }
        if modal is not None and any(total):
            inp = work / f"{group['name']}_modal.inp"
            deck.write(inp, [("Modal", None)], modal["modes"])
            try:
                steps = parse_dat(run_deck(ccx, inp, threads))
            except RuntimeError as error:
                # CalculiX's ARPACK does not start on an eigenproblem of a few DOFs
                # (``d[n,s]aupd info=-9999``): the one-to-three-element models
                result["notes"].append(f"modal: {error}")
            else:
                result["modal"] = modal_results(steps[0], total)
    result["seconds"] = round(time.perf_counter() - started, 1)
    return result


def _rows_of(blocks: dict[str, Any], deck: Deck, what: str) -> list[list[float]]:
    """The stress rows of the frame or the shell probes (two element sets in one step)."""
    ids = (
        {deck.frame_elem[f] for f in deck.probe_frames() if f in deck.frame_elem}
        if what == "frames"
        else {e for s in deck.ir["probes"]["shells"] for e in deck.shell_elems.get(s, [])}
    )
    rows = []
    for title, values in blocks.items():
        if title.lower().startswith("stresses"):
            rows += [r for r in values if int(r[0]) in ids]
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ir", type=Path, required=True)
    ap.add_argument("--ccx", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args(argv)
    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    res = run(ir, args.ccx.resolve(), args.work.resolve(), args.threads)
    args.out.write_text(json.dumps(res), encoding="utf-8")
    print(f"CalculiX {res['version']}: {len(res['cases'])} cases in {res['seconds']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
