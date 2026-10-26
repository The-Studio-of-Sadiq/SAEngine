"""Rebuild the solver-neutral model (``ir.py``) in PyNite and analyse it.

    <PyNite venv>\\Scripts\\python -I run_pynite.py --ir ir.json --out pynite.json

Runs in a virtual environment of its own that has PyNite (``pip install PyNiteFEA``, MIT);
it imports neither SAEngine nor OpenSees. Units: the model's (m, N, kg, s).

PyNite has no rigid diaphragms, no rigid end offsets and no nodal masses in only some
directions, so the model is transformed into an equivalent one:

- rigid end zones: a node at each flexible end and a stiff member (the section's properties
  × ``RIGID``) from the joint to it; the span load stays on the flexible member;
- pinned ends (``ZeroLength`` twins): the frame takes the main node and releases the rotations
  the twin leaves free (mapped onto the member's local axes);
- rigid diaphragms: a stiff link member from the retained node to every constrained node,
  rigid in the floor plane (axial and in-plane bending), released out of plane (bending about
  its horizontal axis at both ends, torsion at one end), so it ties u_x, u_y and r_z only;
- shells: ``Quad3D`` (PyNite's MITC4 plate); a triangle becomes a quadrilateral with its last
  node repeated; layered sections (cracked bending, ``ir.layers``) coincident quads;
- modal: PyNite's own ``analyze_modal`` makes masses out of loads in all three directions,
  so the eigenproblem is solved on PyNite's assembled stiffness matrix with SAEngine's lumped
  masses as they are (``scipy.sparse.linalg.eigsh``, shift-invert at 0, as PyNite does).

PyNite splits a member at every node lying on it; the frames of the analysis model are already
split, so that search is limited to the member's own end nodes (``_own_ends_only``).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

#: Rigid end zones and diaphragm links: stiffness relative to the members they tie (1e4
#: leaves in-plane forces of a few kN in short beams of a rigid floor; 1e6 is rigid enough).
RIGID = 1.0e6
DIRS = ("FX", "FY", "FZ", "MX", "MY", "MZ")


def _own_ends_only() -> None:
    from Pynite.PhysMember import PhysMember

    original = PhysMember.descritize
    if getattr(original, "_own_ends", False):
        return

    def descritize(self: Any) -> None:
        nodes = self.model.nodes
        self.model.nodes = {self.i_node.name: self.i_node, self.j_node.name: self.j_node}
        try:
            original(self)
        finally:
            self.model.nodes = nodes

    descritize._own_ends = True  # type: ignore[attr-defined]
    PhysMember.descritize = descritize


def _axes(member: Any) -> np.ndarray:
    return np.asarray(member.T(), dtype=float)[:3, :3]


def orient(member: Any, y: np.ndarray) -> None:
    """Turn ``member`` about its axis so that its local y is ``y``."""
    member.rotation = 0.0
    t = _axes(member)
    angle = math.degrees(math.atan2(float(y @ t[2]), float(y @ t[1])))
    for trial in (angle, -angle):
        member.rotation = trial
        if float(_axes(member)[1] @ y) > 1 - 1e-6:
            return
    raise RuntimeError(f"cannot orient member {member.name}")


class Model:
    def __init__(self, ir: dict[str, Any], group: dict[str, Any], cases: list[str]) -> None:
        from Pynite import FEModel3D

        _own_ends_only()
        self.ir, self.group = ir, group
        self.notes: list[str] = []
        self.m = FEModel3D()
        self.xyz = {n["id"]: np.asarray(n["xyz"], dtype=float) for n in ir["nodes"]}
        self.member_of: dict[int, str] = {}
        self.extra = 0
        self.cases = cases
        self._build()

    def node(self, nid: int | str) -> str:
        return f"N{nid}"

    def _new_node(self, at: np.ndarray) -> str:
        self.extra += 1
        name = f"X{self.extra}"
        self.m.add_node(name, *map(float, at))
        return name

    def _build(self) -> None:
        ir, g, m = self.ir, self.group, self.m
        main = {t["twin"]: t for t in ir["twins"]}
        for n in ir["nodes"]:
            if n["id"] in main:
                continue
            m.add_node(self.node(n["id"]), *n["xyz"])
            if any(n["restraint"]):
                m.def_support(self.node(n["id"]), *n["restraint"])
        for sid, s in g["frameSections"].items():
            m.add_material(f"MAT{sid}", s["E"], s["G"], s["E"] / (2 * s["G"]) - 1, 0.0)
            m.add_section(f"SEC{sid}", s["A"], s["Iy"], s["Iz"], s["J"])
            m.add_section(
                f"RIG{sid}", s["A"] * RIGID, s["Iy"] * RIGID, s["Iz"] * RIGID, s["J"] * RIGID
            )
        for f in ir["frames"]:
            self._frame(f, main)
        for sid, s in g["shellSections"].items():
            for k, (e, _) in enumerate(s["layers"]):
                m.add_material(f"SH{sid}_{k}", e, e / (2 * (1 + s["nu"])), s["nu"], 0.0)
        for s in ir["shells"]:
            sec = g["shellSections"][str(s["section"])]
            nodes = [self.node(n) for n in s["nodes"]]
            if len(nodes) == 3:
                nodes = self._triangle_as_quad(s["nodes"])
            for k, (_, h) in enumerate(sec["layers"]):
                m.add_quad(f"Q{s['id']}_{k}", *nodes, h, f"SH{s['section']}_{k}")
        if ir["diaphragms"]:
            ea = max(s["E"] * s["A"] for s in g["frameSections"].values())
            m.add_material("LINK", ea * RIGID, ea * RIGID / 2.4, 0.2, 0.0)
            m.add_section("LINK", 1.0, 1e-6, 1.0, 1e-6)
        for d in ir["diaphragms"]:
            self._diaphragm(d)
        for code in self.cases:
            self._loads(code, self.ir["cases"][code])

    def _triangle_as_quad(self, tri: list[int]) -> list[str]:
        """PyNite has no triangular plate (a repeated node makes MITC4 singular): a triangle
        becomes a quadrilateral with a fourth node at the middle of its longest edge, a node of
        that element only (the neighbour across that edge does not share it)."""
        p = [self.xyz[n] for n in tri]
        longest = max(range(3), key=lambda k: float(np.linalg.norm(p[(k + 1) % 3] - p[k])))
        a, b = longest, (longest + 1) % 3
        mid = self._new_node((p[a] + p[b]) / 2)
        names = [self.node(n) for n in tri]
        if not getattr(self, "_tri_noted", False):
            self.notes.append(
                "triangular shells: quadrilaterals with a mid-edge node of their own (PyNite has "
                "no triangle)"
            )
            self._tri_noted = True
        # start at the opposite corner: PyNite takes its plane from corners 1, 2 and 3
        return [names[(a + 2) % 3], names[a], mid, names[b]]

    def _frame(self, f: dict[str, Any], main: dict[int, dict[str, Any]]) -> None:
        m = self.m
        sid = str(f["section"])
        y = np.asarray(f["axes"]["y"], dtype=float)
        ends = []
        releases: dict[str, list[bool]] = {}
        for end, joint in (("i", f["i"]), ("j", f["j"])):
            twin = main.get(joint)
            joint_name = self.node(twin["main"] if twin else joint)
            free = [k for k in (4, 5, 6) if twin and k not in twin["dofs"]]
            if twin and any(k not in twin["dofs"] for k in (1, 2, 3)):
                self.notes.append(f"{f['name']}: a translation release is not rebuilt")
            rel = [False] * 3
            for k in free:
                axis = np.eye(3)[k - 4]
                hits = [a for a, v in enumerate(f["axes"].values()) if abs(np.dot(v, axis)) > 0.99]
                if hits:
                    rel[hits[0]] = True
                else:
                    # a sloped member pinned about global axes: PyNite releases local axes only,
                    # so it becomes a moment release about local y and z (a pin)
                    rel[1] = rel[2] = True
                    self.notes.append(
                        f"{f['name']}: released global rotations {free} not along its axes; "
                        "modelled as a moment release (local y and z)"
                    )
                    break
            off = f.get("offsets")
            vec = np.asarray(off[0:3] if end == "i" else off[3:6]) if off else np.zeros(3)
            if np.linalg.norm(vec) > 1e-12:
                flex = self._new_node(self.xyz[joint] + vec)
                name = f"R{f['id']}{end}"
                a, b = (joint_name, flex) if end == "i" else (flex, joint_name)
                m.add_member(name, a, b, f"MAT{sid}", f"RIG{sid}")
                orient(m.members[name], y)
                if any(rel):
                    self._release(name, "i" if end == "i" else "j", rel)
                ends.append(flex)
            else:
                ends.append(joint_name)
                releases[end] = rel
        name = f"M{f['id']}"
        m.add_member(name, ends[0], ends[1], f"MAT{sid}", f"SEC{sid}")
        orient(m.members[name], y)
        for end, rel in releases.items():
            if any(rel):
                self._release(name, end, rel)
        self.member_of[f["id"]] = name

    def _release(self, member: str, end: str, rel: list[bool]) -> None:
        keys = ("Rx", "Ry", "Rz")
        kwargs = {f"{k}{end}": r for k, r in zip(keys, rel, strict=True)}
        self.m.def_releases(member, **kwargs)

    def _diaphragm(self, d: dict[str, Any]) -> None:
        if d["perp"] != 3:
            self.notes.append(f"diaphragm at node {d['retained']}: perp_dir {d['perp']} skipped")
            return
        master = d["retained"]
        for n in d["nodes"]:
            if n == master:
                continue
            delta = self.xyz[n] - self.xyz[master]
            if np.linalg.norm(delta) < 1e-9:
                self.notes.append(f"node {n} coincides with its diaphragm's retained node")
                continue
            name = f"L{master}_{n}"
            self.m.add_member(name, self.node(master), self.node(n), "LINK", "LINK")
            x = delta / np.linalg.norm(delta)
            orient(self.m.members[name], np.cross([0.0, 0.0, 1.0], x))
            # rigid in plane (axial, bending about the vertical local z); free out of plane
            self.m.def_releases(name, Rxi=True, Ryi=True, Ryj=True)

    def _loads(self, code: str, case: dict[str, Any]) -> None:
        m = self.m
        for nid, forces in case["nodal"]:
            for k, v in enumerate(forces):
                if v:
                    m.add_node_load(self.node(nid), DIRS[k], float(v), case=code)
        for fid, w in case["element"]:
            for k, v in enumerate(w):
                if v:
                    m.add_member_dist_load(self.member_of[int(fid)], DIRS[k], v, v, case=code)
        m.add_load_combo(code, {code: 1.0})

    # ─────────── results ───────────

    def static_results(self, code: str) -> dict[str, Any]:
        m = self.m
        total = np.zeros(6)
        for n in self.ir["nodes"]:
            if not any(n["restraint"]) or self.node(n["id"]) not in m.nodes:
                continue
            node = m.nodes[self.node(n["id"])]
            r = np.array(
                [getattr(node, f"Rxn{k}")[code] for k in ("FX", "FY", "FZ", "MX", "MY", "MZ")]
            )
            p = self.xyz[n["id"]]
            total[:3] += r[:3]
            total[3:] += r[3:] + np.cross(p, r[:3])
        disp = {}
        for nid in self.ir["probes"]["nodes"]:
            node = m.nodes.get(self.node(nid))
            if node is not None:
                disp[str(nid)] = [
                    float(getattr(node, k)[code]) for k in ("DX", "DY", "DZ", "RX", "RY", "RZ")
                ]
        return {
            "reactions": total.tolist(),
            "disp": disp,
            "frames": self.frame_forces(code),
            "shells": self.shell_forces(code),
        }

    def probe_frames(self) -> list[int]:
        out = list(self.ir["probes"]["frames"])
        for fid in list(out):
            for face in (self.ir["faces"].get(str(fid)) or {}).values():
                if int(face["at"][0]) not in out:
                    out.append(int(face["at"][0]))
        return out

    def section(self, member: Any, x: float, code: str) -> list[float]:
        """PyNite's own section forces N, Vy, Vz, T, My, Mz at ``x`` along the member."""
        return [
            float(member.axial(x, code)),
            float(member.shear("Fy", x, code)),
            float(member.shear("Fz", x, code)),
            float(member.torque(x, code)),
            float(member.moment("My", x, code)),
            float(member.moment("Mz", x, code)),
        ]

    def frame_forces(self, code: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for fid in self.probe_frames():
            name = self.member_of.get(fid)
            if name is None:
                continue
            member = self.m.members[name]
            length = float(member.L())
            stations: dict[str, list[float]] = {}
            for key, face in self._faces_on(fid).items():
                stations[key] = self.section(member, face, code)
            out[str(fid)] = {
                "length": length,
                "ends": {
                    "i": self.section(member, 0.0, code),
                    "j": self.section(member, length, code),
                },
                "stations": stations,
            }
        return out

    def _faces_on(self, fid: int) -> dict[str, float]:
        """The support faces that lie on element ``fid``: {"<element>/<end>": distance from
        its flexible end i}."""
        rigid = {f["id"]: f["rigid"][0] for f in self.ir["frames"]}
        out = {}
        for key, ends in self.ir["faces"].items():
            for end, face in ends.items():
                if int(face["at"][0]) == fid:
                    out[f"{key}/{end}"] = float(face["at"][1]) - rigid[fid]
        return out

    def shell_forces(self, code: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        shells = {s["id"]: s for s in self.ir["shells"]}
        for sid in self.ir["probes"]["shells"]:
            s = shells[sid]
            sec = self.group["shellSections"][str(s["section"])]
            n_t, m_t = np.zeros((2, 2)), np.zeros((2, 2))
            for k, (_, h) in enumerate(sec["layers"]):
                q = self.m.quads[f"Q{sid}_{k}"]
                mx, my, mxy = (float(v) for v in np.asarray(q.moment(0.0, 0.0, True, code)).ravel())
                sx, sy, txy = (
                    float(v) for v in np.asarray(q.membrane(0.0, 0.0, True, code)).ravel()
                )
                m_t += np.array([[mx, mxy], [mxy, my]])
                n_t += np.array([[sx, txy], [txy, sy]]) * h
            out[str(sid)] = {"N": invariants(n_t), "M": invariants(m_t)}
        return out

    # ─────────── modal ───────────

    def modal(self, modes: int) -> dict[str, Any]:
        import scipy.sparse as sps
        from Pynite import Analysis
        from scipy.sparse.linalg import eigsh

        m = self.m
        if not m.load_combos:
            m.add_load_combo("Modal", {"Modal": 1.0})
        Analysis._prepare_model(m)
        d1, _, _ = Analysis._partition_D(m)
        combo = next(iter(m.load_combos))
        k = m.Ke(combo, False, False, sparse=True).tocsr()
        size = k.shape[0]
        mass = np.zeros(size)
        for n in self.ir["nodes"]:
            node = m.nodes.get(self.node(n["id"]))
            if node is None:
                continue
            mass[node.ID * 6 : node.ID * 6 + 6] += n["mass"]
        free = np.asarray(d1, dtype=int)
        k11 = k[free][:, free]
        mf = mass[free]
        eps = mf[mf > 0].min() * 1e-8 if (mf > 0).any() else 1.0
        m11 = sps.diags(np.where(mf > 0, mf, eps))
        vals, vecs = eigsh(k11, k=min(modes, len(free) - 2), M=m11, sigma=0.0, which="LM")
        order = np.argsort(vals)
        vals, vecs = vals[order], vecs[:, order]
        dof = np.arange(size)[free] % 6
        eff = []
        for v in vecs.T:
            mm = float(v @ (mf * v))
            lx = float((mf * v)[dof == 0].sum())
            ly = float((mf * v)[dof == 1].sum())
            eff.append([lx * lx / mm, ly * ly / mm])
        total = [float(mass[k::6].sum()) for k in range(3)]
        return {
            "periods": [float(2 * math.pi / math.sqrt(v)) for v in vals if v > 0],
            "effMass": eff,
            "massTotal": total,
        }


def invariants(t: np.ndarray) -> dict[str, float]:
    mean = (t[0, 0] + t[1, 1]) / 2
    radius = math.hypot((t[0, 0] - t[1, 1]) / 2, (t[0, 1] + t[1, 0]) / 2)
    return {"mean": float(mean), "radius": float(radius)}


def run(ir: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "solver": "PyNite",
        "version": version("PyNiteFEA"),
        "cases": {},
        "notes": [],
    }
    for group in ir["groups"]:
        analyses = [a for a in ir["analyses"] if a["group"] == group["name"]]
        statics = [a["code"] for a in analyses if a["type"] == "Static"]
        modal = next((a for a in analyses if a["type"] == "Modal"), None)
        if statics:
            model = Model(ir, group, statics)
            model.m.analyze_linear(check_stability=False, check_statics=False, sparse=True)
            result["notes"] += model.notes
            for code in statics:
                result["cases"][code] = model.static_results(code)
        if modal is not None and any(sum(n["mass"][k] for n in ir["nodes"]) for k in range(3)):
            model = Model(ir, group, [])
            result["modal"] = model.modal(modal["modes"])
    result["seconds"] = round(time.perf_counter() - started, 1)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    res = run(ir)
    args.out.write_text(json.dumps(res), encoding="utf-8")
    print(f"PyNite {res['version']}: {len(res['cases'])} cases in {res['seconds']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
