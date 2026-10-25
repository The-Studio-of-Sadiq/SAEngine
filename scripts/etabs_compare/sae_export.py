"""SAEngine side of the comparison harness: run SAEngine headless on a copy of a project and
write what the other program needs and what it is compared with.

    python sae_export.py --project <copy> --out <dir> [--members C4,B1] [--skip-run]

Writes into ``<dir>``:

- ``saengine.json``: SAEngine's results (periods, effective modal masses, base reactions per
  case, the static seismic weight and base shear, storey centre-of-mass displacements and storey
  shears, member end forces with what is needed to evaluate them at any station);
- ``mirror_input.json``: the derived analysis model (``08 FEM/model.osmodel``) flattened for
  the mirror build, node by node (a solver check);
- ``native_input.json``: the physical model (``06 BIM`` with the object types, materials, the
  settings' area loads and the MEP equipment) for the native build (a conventions check).

Run it with the repository's Python (``.venv``); it imports ``saengine`` read-only and never
writes into the repository. Units in the outputs: kN, m, t, s.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import mirror_angle, reference_axes  # the harness's own module

G = 9.80665
MM = 0.001
#: The cases compared member by member.
MEMBER_CASES = ("D", "SD", "L", "EX", "EY")


def _read(root: Path, rel: str) -> str:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _case_key(case_name: str) -> str:
    return case_name.split(":")[0].strip()


def _last(values: Any) -> list[float]:
    import numpy as np

    a = np.asarray(values, dtype=float)
    return [float(v) for v in (a[-1] if a.ndim > 1 else a)]


def local_axes(
    a: list[float], b: list[float], vecxz: list[float] | None = None
) -> tuple[list[float], list[float], list[float]]:
    """The element axes SAEngine's analysis model uses (saengine.fem.derive.local_axes), from
    the element's own ``vecxz`` when it has one (a column at a skew angle)."""
    import numpy as np

    from saengine.fem.derive import local_axes as derive_axes

    a_, b_ = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if vecxz is None:
        x, y, z = derive_axes(a_, b_)
    else:
        x, y, z = derive_axes(a_, b_, [float(v) for v in vecxz])
    return [float(v) for v in x], [float(v) for v in y], [float(v) for v in z]


def flexible_ends(e: dict[str, Any]) -> tuple[float, float]:
    """The rigid lengths at ends i and j of a frame element (m): the lengths of its joint
    offsets (OpenSees ``-jntOffset``, global vectors from each node to its flexible end)."""
    offsets = _joint_offsets(e)
    if not offsets:
        return 0.0, 0.0
    return math.hypot(*offsets[:3]), math.hypot(*offsets[3:])


# ─────────────────────────────── running SAEngine ───────────────────────────────


def run_saengine(project: Path) -> dict[str, Any]:
    """``saengine run-all <project> --steps derive analysis --json`` on the copy."""
    cmd = [
        sys.executable,
        "-m",
        "saengine.cli",
        "run-all",
        str(project),
        "--steps",
        "derive",
        "analysis",
        "--json",
        "-q",
    ]
    done = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8")
    try:
        doc = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise SystemExit(
            f"saengine run-all failed (exit {done.returncode}):\n{done.stdout}\n{done.stderr}"
        ) from None
    if done.returncode not in (0, 1) or doc.get("stoppedAt"):
        raise SystemExit(f"saengine run-all stopped: {json.dumps(doc.get('steps'), indent=1)}")
    return doc


def derive_summary(project: Path) -> dict[str, Any]:
    """The derivation's summary (period, Sa, W, V) and notes, as Run All's derive step makes
    them (the model it writes is the one analysed)."""
    from saengine.rpc.handlers import derive_fem

    res = derive_fem(
        _read(project, "06 BIM/bim.json"),
        _read(project, "04 Objects/objects.json"),
        _read(project, "03 Materials/materials.json"),
        _read(project, "02 Project Settings/project-settings.json"),
        model_folder=str(project / "08 FEM"),
    )
    if res.get("problems"):
        raise SystemExit("derive: " + "; ".join(res["problems"]))
    return {"summary": res.get("summary") or {}, "notes": res.get("notes") or []}


# ─────────────────────────────── SAEngine results ───────────────────────────────


def _parts_of(model: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [
        e
        for e in model["elements"]
        if e["type"] == "ElasticBeamColumn"
        and (e["name"] == name or e["name"].startswith(name + "#"))
    ]


def _project_on(p: list[float], a: list[float], axis: list[float]) -> float:
    return sum((p[k] - a[k]) * axis[k] for k in range(3))


def _off_line(p: list[float], a: list[float], axis: list[float], length: float) -> float:
    t = _project_on(p, a, axis)
    closest = [a[k] + axis[k] * t for k in range(3)]
    return math.dist(p, closest) if -1e-6 <= t <= length + 1e-6 else math.inf


def member_spans(bim: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """The spans a building-model element is compared over: a column storey by storey (split
    at every level it passes), a beam or member from end to end. Coordinates in m."""
    levels = sorted({s["elevation"] for s in bim.get("stories", [])})
    for e in bim.get("elements", []):
        if e.get("id") != name:
            continue
        if e["kind"] == "column":
            x, y = e["position"]
            stops = [e["bottom"], *[lv for lv in levels if e["bottom"] < lv < e["top"]], e["top"]]
            story_of = {s["elevation"]: s["id"] for s in bim.get("stories", [])}
            spans = []
            for k in range(len(stops) - 1):
                label = name if len(stops) == 2 else f"{name}@{story_of.get(stops[k + 1], k + 1)}"
                spans.append(
                    {
                        "label": label,
                        "member": name,
                        "kind": "column",
                        "angle": float(e.get("rotation", 0.0)),
                        "start": [x * MM, y * MM, stops[k] * MM],
                        "end": [x * MM, y * MM, stops[k + 1] * MM],
                    }
                )
            return spans
        if e["kind"] == "beam":
            z = e["elevation"] * MM
            return [
                {
                    "label": name,
                    "member": name,
                    "kind": "beam",
                    "angle": 0.0,
                    "start": [e["start"][0] * MM, e["start"][1] * MM, z],
                    "end": [e["end"][0] * MM, e["end"][1] * MM, z],
                }
            ]
        if e["kind"] == "member":
            return [
                {
                    "label": name,
                    "member": name,
                    "kind": "brace",
                    "angle": float(e.get("rotation", 0.0)),
                    "start": [v * MM for v in e["start"]],
                    "end": [v * MM for v in e["end"]],
                }
            ]
    for m in bim.get("additions", {}).get("members", []):
        if m.get("id") == name:
            return [
                {
                    "label": name,
                    "member": name,
                    "kind": "brace",
                    "angle": 0.0,
                    "start": [m["x1"] * MM, m["y1"] * MM, m["z1"] * MM],
                    "end": [m["x2"] * MM, m["y2"] * MM, m["z2"] * MM],
                }
            ]
    return []


def default_members(bim: dict[str, Any]) -> list[str]:
    """Two columns of the lowest storey and two beams of the first level, when none are named."""
    stories = sorted(bim.get("stories", []), key=lambda s: s["elevation"])
    base = stories[0]["elevation"] if stories else 0.0
    first = stories[1]["elevation"] if len(stories) > 1 else None
    cols = sorted(
        e["id"] for e in bim.get("elements", []) if e["kind"] == "column" and e["bottom"] == base
    )
    beams = sorted(
        e["id"]
        for e in bim.get("elements", [])
        if e["kind"] == "beam" and first is not None and e["elevation"] == first
    )
    picks = cols[:1] + cols[len(cols) // 2 : len(cols) // 2 + 1] + beams[:1]
    picks += beams[len(beams) // 2 : len(beams) // 2 + 1]
    return list(dict.fromkeys(picks))


def saengine_results(
    project: Path, members: list[str], summary: dict[str, Any], notes: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """SAEngine's results of the analysed copy, and the member spans (for the probes)."""
    import numpy as np
    from opensees_studio.services import result_store as rs

    fem = project / "08 FEM"
    model = json.loads((fem / "model.osmodel").read_text(encoding="utf-8"))
    bim = json.loads(_read(project, "06 BIM/bim.json"))
    settings = json.loads(_read(project, "02 Project Settings/project-settings.json") or "{}")
    out_dir = fem / "model.results"
    manifest = rs.load_manifest(out_dir)
    results = {_case_key(e["case_name"]): rs.load_results(e, out_dir) for e in manifest["cases"]}
    nodes = {n["id"]: n for n in model["nodes"]}
    patterns = {p["name"]: p for p in model["load_patterns"]}
    res: dict[str, Any] = {
        "program": "SAEngine",
        "units": {"force": "kN", "length": "m", "mass": "t"},
        "cases": sorted(results),
        "notes": notes,
        "analysisSettings": _analysis_settings(project, settings),
    }

    # base reactions per case [FX, FY, FZ, MX, MY, MZ] (kN, kN·m)
    react: dict[str, list[float]] = {}
    for case, r in results.items():
        if not getattr(r, "node_reaction", None):
            continue
        total = [0.0] * 6
        for nid, v in r.node_reaction.items():
            row = _last(v)
            xyz = nodes[nid]["coords"]
            for k in range(3):
                total[k] += row[k]
            # moments about the origin
            fx, fy, fz = row[:3]
            total[3] += row[3] + xyz[1] * fz - xyz[2] * fy
            total[4] += row[4] + xyz[2] * fx - xyz[0] * fz
            total[5] += row[5] + xyz[0] * fy - xyz[1] * fx
        react[case] = [round(v / 1e3, 4) for v in total]
    res["baseReactions"] = react

    # seismic weight and static base shear
    masses = [n["mass"][0] for n in model["nodes"]]
    res["seismic"] = {
        "W_kN": float(summary.get("weight_kN", sum(masses) * G / 1e3)),
        "V_kN": float(summary.get("base_shear_kN", 0.0)),
        "period_s": summary.get("period_s"),
        "Sa_g": summary.get("Sa_g"),
        "massTotal_t": sum(masses) / 1e3,
    }
    period = summary.get("period_s") or 0.0
    res["seismic"]["k"] = 1.0 if period <= 0.5 else 2.0 if period >= 2.5 else 1 + (period - 0.5) / 2

    # modal: periods and effective modal masses (t)
    if "Modal" in results:
        mod = results["Modal"]
        ev = np.asarray(mod.eigenvalues, dtype=float)
        periods = [float(2 * math.pi / math.sqrt(v)) for v in ev if v > 0]
        ids = [n["id"] for n in model["nodes"]]
        idx = {nid: i for i, nid in enumerate(ids)}
        mass = np.array([n["mass"] for n in model["nodes"]], dtype=float)
        eff = []
        for mode in sorted(mod.mode_shapes):
            shape = np.zeros((len(ids), 6))
            for nid, v in mod.mode_shapes[mode].items():
                shape[idx[nid]] = _last(v)
            mm = float((mass * shape * shape).sum())
            lx = float((mass[:, 0] * shape[:, 0]).sum())
            ly = float((mass[:, 1] * shape[:, 1]).sum())
            eff.append([lx * lx / mm / 1e3, ly * ly / mm / 1e3] if mm else [0.0, 0.0])
        res["modal"] = {"periods": periods, "effMass_t": eff, "massTotal_t": mass[:, 0].sum() / 1e3}

    # storeys: centre-of-mass displacements (the diaphragms' retained nodes) and storey shears
    stories = sorted(bim.get("stories", []), key=lambda s: s["elevation"])
    base = stories[0]["elevation"] * MM if stories else 0.0
    levels = [
        {
            "name": s["id"],
            "z": s["elevation"] * MM,
            "h": (s["elevation"] - stories[i]["elevation"]) * MM,
        }
        for i, s in enumerate(stories[1:])
    ]
    res["stories"] = {"base": base, "levels": levels}
    cm: dict[str, dict[str, list[float]]] = {}
    for c in model.get("mp_constraints", []):
        nid = c["retained_node"]
        z = nodes[nid]["coords"][2]
        level = next((lv for lv in levels if abs(lv["z"] - z) < 1e-4), None)
        if level is None:
            continue
        for case in ("EX", "EY", "WX", "WY"):
            r = results.get(case)
            if r is not None and nid in r.node_disp:
                d = _last(r.node_disp[nid])
                cm.setdefault(case, {})[level["name"]] = [d[0], d[1]]
    res["stories"]["cmDisp"] = cm
    shear: dict[str, dict[str, float]] = {}
    for case, comp in (("EX", 0), ("EY", 1), ("WX", 0), ("WY", 1)):
        pat = patterns.get(case)
        if pat is None:
            continue
        lower = base
        for lv in levels:
            v = sum(
                nl["forces"][comp]
                for nl in pat.get("nodal_loads", [])
                if nodes[nl["node_id"]]["coords"][2] > lower + 1e-6
            )
            shear.setdefault(case, {})[lv["name"]] = v / 1e3
            lower = lv["z"]
    res["stories"]["shear"] = shear

    # members: the sub-elements of each span with their end forces and uniform loads, so the
    # forces can be evaluated at any station (the other program's support faces)
    element_loads: dict[str, dict[int, list[float]]] = {}
    for case in MEMBER_CASES:
        pat = patterns.get(case)
        for el in pat.get("element_loads", []) if pat else []:
            element_loads.setdefault(case, {})[el["element_id"]] = [
                el["wx"] / 1e3,
                el["wy"] / 1e3,
                el["wz"] / 1e3,
            ]
    spans_out = []
    for name in members:
        spans = member_spans(bim, name)
        if not spans:
            res.setdefault("memberNotes", []).append(
                f"{name}: no column, beam or member of that id"
            )
            continue
        parts = _parts_of(model, name)
        for span in spans:
            a, b = span["start"], span["end"]
            length = math.dist(a, b)
            axis = [(b[k] - a[k]) / length for k in range(3)]
            subs = []
            for e in parts:
                pi, pj = (nodes[n]["coords"] for n in e["nodes"])
                if _off_line(pi, a, axis, length) > 1e-3 or _off_line(pj, a, axis, length) > 1e-3:
                    continue
                ti, tj = _project_on(pi, a, axis), _project_on(pj, a, axis)
                lo, hi = min(ti, tj), max(ti, tj)
                if hi < 1e-6 or lo > length - 1e-6:
                    continue
                x, y, z = local_axes(pi, pj, e.get("vecxz"))
                # OpenSees reports the end forces at the flexible ends (the faces) when the
                # element has rigid end offsets: the statics start there, not at the nodes
                ri, rj = flexible_ends(e)
                step = 1.0 if tj >= ti else -1.0
                fa, fb = ti + step * ri, tj - step * rj
                angle = mirror_angle(pi, pj, z)
                cases = {}
                for case in MEMBER_CASES:
                    r = results.get(case)
                    if r is None or e["id"] not in r.element_forces:
                        continue
                    f = _last(r.element_forces[e["id"]])
                    cases[case] = {
                        "fi": [v / 1e3 for v in f[:6]],
                        "w": element_loads.get(case, {}).get(e["id"], [0.0, 0.0, 0.0]),
                    }
                subs.append(
                    {
                        "element": e["id"],
                        "name": e["name"],
                        "na": ti,
                        "nb": tj,
                        "a": fa,
                        "b": fb,
                        "rigid": [ri, rj],
                        "vecxz": e.get("vecxz"),
                        "axes": {"x": x, "y": y, "z": z},
                        # the mirror's frame: drawn from node i, turned so its axes are SAEngine's
                        "refAngle": angle,
                        "refAxes": reference_axes(pi, pj, angle),
                        "cases": cases,
                    }
                )
            subs.sort(key=lambda s: min(s["na"], s["nb"]))
            spans_out.append({**span, "length": length, "subs": subs})
    res["members"] = spans_out
    face = _face_forces(out_dir)
    if face:
        res["faceForces"] = face
    return res, {"spans": spans_out}


def _analysis_settings(project: Path, raw: dict[str, Any]) -> dict[str, Any]:
    """The analysis settings with their defaults (the reasons quote them)."""
    from saengine.library.settings import ProjectSettings

    try:
        settings = ProjectSettings.model_validate_json(
            _read(project, "02 Project Settings/project-settings.json")
        )
        return settings.analysis.model_dump(mode="json")
    except ValueError:
        return raw.get("analysis") or {}


def _face_forces(out_dir: Path) -> dict[str, Any] | None:
    """SAEngine's own support-face forces, when the analysis writes them (per element
    ``faceForces`` {i: {N, Vy, Vz, T, My, Mz}, j: {...}} and ``faceOffsets`` {i, j} mm)."""
    for path in sorted(out_dir.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "faceForces" not in text:
            continue
        try:
            return {"file": path.name, "data": json.loads(text)}
        except json.JSONDecodeError:
            continue
    return None


# ─────────────────────────────── mirror input ───────────────────────────────


def mirror_input(project: Path, spans: list[dict[str, Any]]) -> dict[str, Any]:
    """The derived analysis model, flattened for the mirror build (kN, m, t)."""
    model = json.loads((project / "08 FEM" / "model.osmodel").read_text(encoding="utf-8"))
    bim = json.loads(_read(project, "06 BIM/bim.json"))
    nodes = {n["id"]: n for n in model["nodes"]}
    elements = {e["id"]: e for e in model["elements"]}
    used = {n for e in model["elements"] for n in e.get("nodes", [])}
    # Pinned ends: ZeroLength twins (main node, twin node, the dofs tied)
    alias: dict[int, int] = {}
    tied: dict[int, list[int]] = {}
    for e in model["elements"]:
        if e["type"] == "ZeroLength":
            alias[e["nodes"][1]] = e["nodes"][0]
            tied[e["nodes"][1]] = list(e.get("dofs", []))
    notes: list[str] = []
    retained = {c["retained_node"] for c in model.get("mp_constraints", [])}
    out: dict[str, Any] = {
        "mode": "mirror",
        "notes": notes,
        "stories": [],
        "nodes": [],
        "frames": [],
        "links": [],
        "shells": [],
        "frame_sections": [],
        "shell_sections": [],
        "loads": {},
        "elem_loads": {},
        "diaphragms": [],
        "groups": [],
        "modal": None,
    }
    stories = sorted(bim.get("stories", []), key=lambda s: s["elevation"])
    out["base"] = stories[0]["elevation"] * MM if stories else 0.0
    out["stories"] = [
        {"name": s["id"], "height": (s["elevation"] - stories[i]["elevation"]) * MM}
        for i, s in enumerate(stories[1:])
    ]
    # A diaphragm's master node carries the story's lumped mass and loads (the seismic mass
    # lumped at the story levels, the story forces): it is kept as a joint of its diaphragm.
    loaded = {x["node_id"] for p in model["load_patterns"] for x in p.get("nodal_loads", [])}
    carrying = {n["id"] for n in model["nodes"] if any(n.get("mass") or []) or n["id"] in loaded}
    kept = used | (retained & carrying)
    for n in model["nodes"]:
        if n["id"] in alias:
            continue
        if n["id"] in retained and n["id"] not in kept:
            continue  # the diaphragm's master node: the other program makes its own
        mass = [v / 1e3 for v in n.get("mass", [0.0] * 6)]
        out["nodes"].append(
            {"id": n["id"], "xyz": n["coords"], "mass": mass, "restraint": n["restraint"]}
        )
    # sections and the cracked overrides of each analysis
    secs = {s["id"]: s for s in model["sections"]}
    for sid, s in secs.items():
        if s["type"] == "ElasticSection":
            # ETABS I33 (local 3: horizontal for beams, global Y for columns) = OpenSees Iy
            out["frame_sections"].append(
                {
                    "id": sid,
                    "name": f"S{sid}",
                    "label": s["name"],
                    "E": s["E"] / 1e3,
                    "G": s.get("G", s["E"] / 2.4) / 1e3,
                    "A": s["A"],
                    "J": s["J"],
                    "I33": s["Iy"],
                    "I22": s["Iz"],
                }
            )
        elif s["type"] == "ElasticMembranePlateSection":
            out["shell_sections"].append(
                {
                    "id": sid,
                    "name": f"SH{sid}",
                    "label": s["name"],
                    "E": s["E"] / 1e3,
                    "nu": s.get("nu", 0.2),
                    "h": s["h"],
                    "wall": s["name"].endswith(" wall"),
                }
            )
        else:
            notes.append(f"section {sid} ({s['type']}) is not mirrored")

    def modifiers(overrides: list[dict[str, Any]] | None) -> dict[str, list[float]]:
        mods: dict[str, list[float]] = {}
        for o in overrides or []:
            s = secs.get(o["id"])
            if s is None:
                continue
            if s["type"] == "ElasticSection":
                e = o.get("E", s["E"]) / s["E"]
                g = o.get("G", s.get("G", 1.0)) / s.get("G", 1.0)
                mods[f"S{o['id']}"] = [
                    e * o.get("A", s["A"]) / s["A"],
                    1.0,
                    1.0,
                    g * o.get("J", s["J"]) / s["J"],
                    e * o.get("Iz", s["Iz"]) / s["Iz"],
                    e * o.get("Iy", s["Iy"]) / s["Iy"],
                    1.0,
                    1.0,
                ]
            elif s["type"] == "ElasticMembranePlateSection":
                memb = o.get("E", s["E"]) / s["E"] * (o.get("h", s["h"]) / s["h"])
                bend = o.get("E", s["E"]) / s["E"] * o.get("Ep_mod", 1.0)
                mods[f"SH{o['id']}"] = [memb, memb, memb, bend, bend, bend, memb, memb, 1.0, 1.0]
        return mods

    # load patterns analysed together with the same section overrides form one run
    by_pattern = {p["id"]: p for p in model["load_patterns"]}
    groups: dict[str, dict[str, Any]] = {}
    for a in model["analyses"]:
        mods = modifiers(a.get("section_overrides"))
        key = json.dumps(mods, sort_keys=True)
        group = groups.setdefault(key, {"modifiers": mods, "patterns": [], "modal": False})
        if a["type"] == "Static":
            for pid in a.get("pattern_ids", []):
                name = by_pattern[pid]["name"]
                if name not in group["patterns"] and by_pattern[pid].get("type") == "Plain":
                    group["patterns"].append(name)
        elif a["type"] == "Modal":
            group["modal"] = True
            out["modal"] = int(a.get("n_modes", 12))
        elif a["type"] == "Staged":
            notes.append(f"{a['name']}: a construction sequence is not mirrored (D at once)")
    out["groups"] = [g for g in groups.values() if g["patterns"] or g["modal"]]

    def main(n: int) -> int:
        return alias.get(n, n)

    seen_pairs: dict[frozenset[int], int] = {}
    for e in model["elements"]:
        if e["type"] == "ElasticBeamColumn":
            i, j = e["nodes"]
            rel_i = _released(tied.get(i)) if i in alias else None
            rel_j = _released(tied.get(j)) if j in alias else None
            offsets = _joint_offsets(e)
            pi, pj = nodes[i]["coords"], nodes[j]["coords"]
            _, _, z = local_axes(pi, pj, e.get("vecxz"))
            frame = {
                "id": e["id"],
                "name": f"F{e['id']}",
                "member": e["name"],
                "i": main(i),
                "j": main(j),
                "sec": f"S{e['section_id']}",
                "relI": rel_i,
                "relJ": rel_j,
                "offsets": offsets,
                # the reference's frame angle that gives it SAEngine's local axes (a skewed
                # column's vecxz, a sloped member in a vertical YZ plane)
                "angle": mirror_angle(pi, pj, z),
            }
            pair = frozenset((main(i), main(j)))
            if pair in seen_pairs:
                # The other program takes one frame per joint pair: the second one becomes a
                # link with the frame's stiffness (axial only when it is pinned at both ends).
                s = secs[e["section_id"]]
                pi, pj = nodes[main(i)]["coords"], nodes[main(j)]["coords"]
                length = math.dist(pi, pj)
                axial = s["E"] * s["A"] / length / 1e3
                # axial only as soon as one end is pinned (a brace): its bending is negligible
                pinned = bool(rel_i) or bool(rel_j)
                k = [axial] + (
                    [0.0] * 5
                    if pinned
                    else [
                        12 * s["E"] * s["Iz"] / length**3 / 1e3,
                        12 * s["E"] * s["Iy"] / length**3 / 1e3,
                        s.get("G", 0.0) * s["J"] / length / 1e3,
                        4 * s["E"] * s["Iy"] / length / 1e3,
                        4 * s["E"] * s["Iz"] / length / 1e3,
                    ]
                )
                out["links"].append({**frame, "name": f"LK{e['id']}", "k": k, "pinned": pinned})
                notes.append(
                    f"{e['name']}: shares its joints with {elements[seen_pairs[pair]]['name']}; "
                    f"modelled as a {'pinned axial' if pinned else 'linear'} link"
                )
                continue
            seen_pairs[pair] = e["id"]
            out["frames"].append(frame)
        elif e["type"] == "Shell":
            out["shells"].append(
                {
                    "id": e["id"],
                    "name": f"A{e['id']}",
                    "member": e["name"],
                    "nodes": [main(k) for k in e["nodes"]],
                    "sec": f"SH{e['section_id']}",
                }
            )
        elif e["type"] == "Solid":
            notes.append(f"{e['name']}: solid elements are not mirrored")
    for p in model["load_patterns"]:
        if p.get("type") != "Plain" or p["name"].startswith("D, stage"):
            continue
        out["loads"][p["name"]] = [
            {"node": main(x["node_id"]), "f": [v / 1e3 for v in x["forces"]]}
            for x in p.get("nodal_loads", [])
        ]
        els = []
        for x in p.get("element_loads", []):
            e = elements[x["element_id"]]
            pi, pj = (nodes[k]["coords"] for k in e["nodes"])
            ax, ay, az = local_axes(pi, pj, e.get("vecxz"))
            g = [(x["wx"] * ax[k] + x["wy"] * ay[k] + x["wz"] * az[k]) / 1e3 for k in range(3)]
            # SAEngine's element carries its span load over its flexible length only (the
            # load on a rigid zone is already a nodal load at the joint): load the same part
            ri, rj = flexible_ends(e)
            full = math.dist(pi, pj)
            target = (
                f"F{e['id']}" if any(f["id"] == e["id"] for f in out["frames"]) else f"LK{e['id']}"
            )
            els.append(
                {
                    "frame": target,
                    "g": g,
                    "length": full - ri - rj,
                    "d0": ri / full,
                    "d1": 1.0 - rj / full,
                    "ends": [main(k) for k in e["nodes"]],
                }
            )
        out["elem_loads"][p["name"]] = els
    for k, c in enumerate(model.get("mp_constraints", []), start=1):
        nodes_tied = [main(n) for n in c["constrained_nodes"]]
        if c["retained_node"] in kept:
            nodes_tied.append(main(c["retained_node"]))
        out["diaphragms"].append({"name": f"D{k}", "nodes": sorted(set(nodes_tied))})
    # the probes: first and last sub-element of each span
    probes = []
    for span in spans:
        if not span["subs"]:
            continue
        first, last = span["subs"][0], span["subs"][-1]
        probes.append(
            {
                "label": span["label"],
                "first": f"F{first['element']}",
                "last": f"F{last['element']}",
                "lastStart": min(last["na"], last["nb"]),
                "length": span["length"],
            }
        )
    out["probes"] = probes
    out["probePoints"] = []
    return out


def _released(dofs: list[int] | None) -> list[int] | None:
    """The rotational DOFs (4-6) a ZeroLength twin leaves free: released at that end."""
    if dofs is None:
        return None
    free = [d for d in (4, 5, 6) if d not in dofs]
    return free or None


def _joint_offsets(e: dict[str, Any]) -> list[float] | None:
    """Rigid joint offsets of a frame element ([dXi, dYi, dZi, dXj, dYj, dZj], m), whatever
    key the analysis model keeps them under (OpenSees geomTransf -jntOffset)."""
    for key, value in e.items():
        low = key.lower()
        if ("offset" in low) and isinstance(value, list | dict):
            if isinstance(value, dict):
                vi, vj = value.get("i"), value.get("j")
                if isinstance(vi, list) and isinstance(vj, list):
                    return [float(v) for v in (*vi, *vj)]
            elif len(value) == 6:
                return [float(v) for v in value]
    return None


# ─────────────────────────────── native input ───────────────────────────────


def native_input(
    project: Path, spans: list[dict[str, Any]], seismic: dict[str, Any]
) -> dict[str, Any]:
    """The physical model for the native build: storeys, materials, sections, columns, beams,
    members, walls and slabs with their openings, the settings' area loads, the partitions on
    the beams, the MEP equipment as point loads, the supports, the mass source and the static
    seismic coefficient SAEngine used (kN, m)."""
    from saengine.codes import context as code_context
    from saengine.library.bim import (
        AreaElement,
        BeamElement,
        BuildingModel,
        ColumnElement,
        MemberElement,
        SlabElement,
        WallElement,
    )
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.sections import section_properties
    from saengine.library.settings import ProjectSettings

    building = BuildingModel.model_validate_json(_read(project, "06 BIM/bim.json"))
    objects = ObjectLibrary.model_validate_json(_read(project, "04 Objects/objects.json"))
    materials = MaterialLibrary.model_validate_json(_read(project, "03 Materials/materials.json"))
    settings = ProjectSettings.model_validate_json(
        _read(project, "02 Project Settings/project-settings.json")
    )
    model = json.loads((project / "08 FEM" / "model.osmodel").read_text(encoding="utf-8"))
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    notes: list[str] = []
    out: dict[str, Any] = {"mode": "native", "notes": notes}

    stories = sorted(building.stories, key=lambda s: s.elevation)
    levels = [s.elevation for s in stories]
    base = levels[0] if levels else 0.0
    top = levels[-1] if levels else 0.0
    out["base"] = base * MM
    out["stories"] = [
        {"name": s.id, "height": (s.elevation - stories[i].elevation) * MM}
        for i, s in enumerate(stories[1:])
    ]

    used_mats: dict[str, dict[str, Any]] = {}

    def material(mid: str) -> str | None:
        m = mats.get(mid)
        if m is None or not m.mechanical.E:
            return None
        if mid not in used_mats:
            nu = m.mechanical.nu
            cat = m.category.value
            used_mats[mid] = {
                "name": mid,
                "type": "steel"
                if cat == "steel"
                else "concrete"
                if cat in ("concrete", "masonry")
                else "other",
                "E": m.mechanical.E * 1e3,  # MPa -> kPa
                "nu": nu if nu is not None else (0.2 if cat == "concrete" else 0.3),
                "w": (m.mechanical.density or 0.0) * G / 1e3,  # kN/m³
                "m": (m.mechanical.density or 0.0) / 1e3,  # t/m³
            }
        return mid

    frame_secs: dict[str, dict[str, Any]] = {}

    def frame_section(type_id: str, kind: str) -> str | None:
        """The frame section of an object type: a rectangle as the other program draws it
        (t3 along local 2: a column's X width, a beam's depth), any other shape as its general
        properties (SAEngine's section_properties)."""
        t = types.get(type_id)
        if t is None or not hasattr(t, "profile") or material(t.material) is None:
            return None
        name = f"{type_id}-{'COL' if kind == 'column' else 'BM'}"
        if name in frame_secs:
            return name
        p = t.profile
        shape = getattr(p, "shape", None)
        if shape == "rectangle":
            xd, yd = p.xDim * MM, p.yDim * MM
            t3, t2 = (xd, yd) if kind == "column" else (yd, xd)
            frame_secs[name] = {
                "name": name,
                "mat": t.material,
                "shape": "rect",
                "t3": t3,
                "t2": t2,
            }
        else:
            props = section_properties(p)
            about_x, about_y = props.ixx * MM**4, props.iyy * MM**4
            # local 3 is about global Y for a column (I33 = iyy), horizontal for a beam (ixx)
            i33, i22 = (about_y, about_x) if kind == "column" else (about_x, about_y)
            frame_secs[name] = {
                "name": name,
                "mat": t.material,
                "shape": "general",
                "A": props.area * MM**2,
                "J": props.j * MM**4,
                "I33": i33,
                "I22": i22,
                "label": shape,
            }
        return name

    area_secs: dict[str, dict[str, Any]] = {}

    def area_section(type_id: str) -> str | None:
        t = types.get(type_id)
        if (
            t is None
            or getattr(t, "kind", None) not in ("slab", "wall")
            or material(t.material) is None
        ):
            return None
        if type_id not in area_secs:
            area_secs[type_id] = {
                "name": type_id,
                "mat": t.material,
                "kind": t.kind,
                "t": t.thickness * MM,
                # SAEngine's "loads to beams" slabs have no stiffness: the reference's membrane
                # slab is the same idea (loads to the beams, in-plane stiffness only)
                "shell": "Membrane"
                if t.kind == "slab" and settings.analysis.slabs != "shells"
                else "ShellThin",
            }
        return type_id

    def simple(type_id: str) -> bool:
        t = types.get(type_id)
        m = mats.get(getattr(t, "material", None)) if t else None
        return (
            getattr(t, "connection", None) is not None
            and m is not None
            and m.category.value == "steel"
        )

    frames: list[dict[str, Any]] = []
    restraints: dict[tuple[int, int, int], list[bool]] = {}

    def fix(x: float, y: float, z: float, r: list[bool] | None = None) -> None:
        restraints[(round(x), round(y), round(z))] = r or [True] * 6

    for e in building.elements:
        if isinstance(e, ColumnElement):
            sec = frame_section(e.type, "column")
            if sec is None:
                notes.append(f"{e.id}: no frame section; left out")
                continue
            x, y = e.position
            stops = [e.bottom, *[lv for lv in levels if e.bottom < lv < e.top], e.top]
            story_of = {s.elevation: s.id for s in stories}
            for k in range(len(stops) - 1):
                label = e.id if len(stops) == 2 else f"{e.id}@{story_of.get(stops[k + 1], k + 1)}"
                frames.append(
                    {
                        "name": label,
                        "kind": "column",
                        "i": [x * MM, y * MM, stops[k] * MM],
                        "j": [x * MM, y * MM, stops[k + 1] * MM],
                        "sec": sec,
                        "angle": e.rotation,
                        "type": e.type,
                    }
                )
            if math.isclose(e.bottom, base):
                fix(x, y, e.bottom)
        elif isinstance(e, BeamElement):
            sec = frame_section(e.type, "beam")
            if sec is None:
                notes.append(f"{e.id}: no frame section; left out")
                continue
            frames.append(
                {
                    "name": e.id,
                    "kind": "beam",
                    "i": [e.start[0] * MM, e.start[1] * MM, e.elevation * MM],
                    "j": [e.end[0] * MM, e.end[1] * MM, e.elevation * MM],
                    "sec": sec,
                    "angle": 0.0,
                    "type": e.type,
                    "pinned": simple(e.type),
                }
            )
        elif isinstance(e, MemberElement):
            vertical = abs(e.end[2] - e.start[2]) > abs(e.end[0] - e.start[0])
            sec = frame_section(e.type, "column" if vertical else "beam")
            if sec is None:
                notes.append(f"{e.id}: no frame section; left out")
                continue
            frames.append(
                {
                    "name": e.id,
                    "kind": "brace",
                    "i": [v * MM for v in e.start],
                    "j": [v * MM for v in e.end],
                    "sec": sec,
                    "angle": e.rotation,
                    "type": e.type,
                    "pinned": simple(e.type),
                }
            )
    for m in building.additions.members:
        a = [m.x1, m.y1, m.z1]
        b = [m.x2, m.y2, m.z2]
        vertical = abs(b[2] - a[2]) > abs(b[0] - a[0])
        sec = frame_section(m.type, "column" if vertical else "beam")
        if sec is None:
            notes.append(f"{m.id}: no frame section; left out")
            continue
        frames.append(
            {
                "name": m.id,
                "kind": "brace",
                "i": [v * MM for v in a],
                "j": [v * MM for v in b],
                "sec": sec,
                "angle": 0.0,
                "type": m.type,
                "pinned": simple(m.type),
            }
        )
    # one frame per line: a second frame on the same line becomes a link (as in the mirror)
    links = []
    seen: dict[tuple[Any, ...], str] = {}
    kept = []
    for f in frames:
        key = tuple(
            sorted((tuple(round(v, 4) for v in f["i"]), tuple(round(v, 4) for v in f["j"])))
        )
        if key in seen:
            s = frame_secs[f["sec"]]
            mat = used_mats[s["mat"]]
            area = s["A"] if s["shape"] == "general" else s["t3"] * s["t2"]
            length = math.dist(f["i"], f["j"])
            links.append({**f, "k": [mat["E"] * area / length, 0, 0, 0, 0, 0], "pinned": True})
            notes.append(f"{f['name']}: on the same line as {seen[key]}; modelled as an axial link")
            continue
        seen[key] = f["name"]
        kept.append(f)
    out["frames"] = kept
    out["links"] = links

    # walls (structural: areas; others: partitions on the beams below them)
    areas: list[dict[str, Any]] = []
    frame_loads: list[dict[str, Any]] = []
    wall_openings: dict[str, list[Any]] = {}
    for o in building.additions.wallOpenings:
        wall_openings.setdefault(o.host, []).append(o)
    beams = [f for f in kept if f["kind"] == "beam"]
    for e in building.elements:
        if not isinstance(e, WallElement):
            continue
        t = types.get(e.type)
        if t is None or t.kind != "wall":
            continue
        sx, sy = e.start
        ex, ey = e.end
        length = math.hypot(ex - sx, ey - sy)
        if length < 1:
            continue
        ux, uy = (ex - sx) / length, (ey - sy) / length

        def corner(
            s: float, z: float, sx: float = sx, sy: float = sy, ux: float = ux, uy: float = uy
        ):
            return [(sx + s * ux) * MM, (sy + s * uy) * MM, z * MM]

        if not t.structural:
            m = mats.get(t.material)
            density = (m.mechanical.density or 0.0) if m else 0.0
            w = density * G * t.thickness * MM * (e.top - e.bottom) * MM / 1e3  # kN/m
            if math.isclose(e.bottom, base) or not w:
                continue
            placed = _on_beams(beams, corner(0, e.bottom), corner(length, e.bottom))
            if not placed:
                notes.append(f"{e.id}: partition with no beam under it; its load is left out")
            for frame, d0, d1 in placed:
                frame_loads.append({"frame": frame, "case": "DW", "w": w, "d0": d0, "d1": d1})
            continue
        sec = area_section(e.type)
        if sec is None:
            notes.append(f"{e.id}: no wall section; left out")
            continue
        areas.append(
            {
                "name": e.id,
                "kind": "wall",
                "pts": [
                    corner(0, e.bottom),
                    corner(length, e.bottom),
                    corner(length, e.top),
                    corner(0, e.top),
                ],
                "sec": sec,
                "openings": [
                    [
                        corner(o.offset, e.bottom + o.sill),
                        corner(o.offset + o.width, e.bottom + o.sill),
                        corner(o.offset + o.width, e.bottom + o.sill + o.height),
                        corner(o.offset, e.bottom + o.sill + o.height),
                    ]
                    for o in wall_openings.get(e.id, [])
                ],
                "loads": {},
                "diaphragm": False,
            }
        )
        if math.isclose(e.bottom, base):
            fix(sx, sy, e.bottom)
            fix(ex, ey, e.bottom)

    area_loads = {a.id: a for a in settings.areaLoads}
    slab_openings: dict[str, list[Any]] = {}
    for o in building.additions.slabOpenings:
        slab_openings.setdefault(o.host, []).append(o)
    rigid = settings.analysis.diaphragm == "rigid"
    for e in building.elements:
        if isinstance(e, SlabElement):
            sec = area_section(e.type)
            if sec is None:
                notes.append(f"{e.id}: no slab section; left out")
                continue
            roof = math.isclose(e.elevation, top)
            load_id = e.areaLoad or (settings.roofLoad if roof else settings.floorLoad)
            al = area_loads.get(load_id)
            loads = {}
            if al is not None:
                loads["SD"] = al.finish + al.partitions
                loads["Lr" if roof else "L"] = al.live
            z = e.elevation * MM
            areas.append(
                {
                    "name": e.id,
                    "kind": "slab",
                    "pts": [[x * MM, y * MM, z] for x, y in e.boundary],
                    "sec": sec,
                    "openings": [_rect_opening(o, z) for o in slab_openings.get(e.id, [])],
                    "loads": loads,
                    "diaphragm": rigid,
                }
            )
        elif isinstance(e, AreaElement):
            sec = area_section(e.type)
            if sec is None:
                notes.append(f"{e.id}: no slab or wall section; left out")
                continue
            al = area_loads.get(e.areaLoad) if e.areaLoad else None
            loads = {"SD": al.finish + al.partitions, "L": al.live} if al else {}
            areas.append(
                {
                    "name": e.id,
                    "kind": types[e.type].kind,
                    "pts": [[v * MM for v in p] for p in e.outline],
                    "sec": sec,
                    "openings": [[[v * MM for v in p] for p in o] for o in e.openings],
                    "loads": loads,
                    "diaphragm": False,
                }
            )
        elif getattr(e, "kind", None) == "block":
            notes.append(f"{e.id}: solid blocks are not drawn in the native model")
    for st in building.additions.stairs:
        notes.append(f"{st.id}: stairs are not in either model")
    for s in building.supports:
        pinned = s.fixity == "pinned"
        fix(*s.at, [True, True, True, not pinned, not pinned, not pinned])
    out["areas"] = areas
    out["restraints"] = [
        {"xyz": [k[0] * MM, k[1] * MM, k[2] * MM], "r": r} for k, r in restraints.items()
    ]

    # MEP equipment: SAEngine's own parts (empty weight, contents, impact, plinth) at its
    # support points or footprint corners, as point loads on the slab
    point_loads: list[dict[str, Any]] = []
    mep_text = _read(project, "07 MEP/mep.json")
    if mep_text:
        try:
            from saengine.library.mep import MepModel
            from saengine.mep.geometry import footprint_points
            from saengine.mep.loads import _points, equipment_parts, with_services_equipment

            mep = MepModel.model_validate_json(mep_text)
            mep, _ = with_services_equipment(mep, materials)
            densities = {m.id: m.mechanical.density for m in materials.materials}
            cases = sorted({p["name"] for p in model["load_patterns"]})
            story_z = {s.id: s.elevation for s in stories}
            for item in mep.equipment:
                z = story_z.get(item.story)
                if z is None or math.isclose(z, base):
                    continue
                if item.loadAs == "points":
                    pts = _points(item)
                else:  # a footprint: the centres of its four quarters (SAEngine's grid, 2x2)
                    pts = footprint_points(
                        item.x,
                        item.y,
                        item.length,
                        item.width,
                        item.rotation,
                        spacing=max(item.length, item.width) / 2,
                    )
                for part in equipment_parts(item, mep.contentsAs, densities, cases):
                    for x, y in pts:
                        point_loads.append(
                            {
                                "xyz": [x * MM, y * MM, z * MM],
                                "case": part.case,
                                "fz": -part.total / len(pts) / 1e3,
                                "source": item.id,
                                "massShare": part.weight_share,
                            }
                        )
                notes.append(f"{item.id}: equipment as {len(pts)} point loads on the slab")
        except Exception as exc:  # noqa: BLE001 - the equipment is a detail of the comparison, never a stop
            notes.append(f"MEP equipment left out of the native model: {exc}")
    out["frame_loads"] = frame_loads
    out["point_loads"] = point_loads

    # mass source: self mass + the load patterns with SAEngine's seismic shares
    live_share = 0.25
    try:
        with code_context.using(code_context.pack_for(settings, project)):
            live_share = float(code_context.table("seismic").liveShare)
    except Exception as exc:  # noqa: BLE001 - a fallback, noted
        notes.append(f"code pack: live share of the seismic weight taken as 0.25 ({exc})")
    # Self mass comes from the elements; a Dead pattern in the mass source would count the
    # self-weight twice, so the partitions on the beams have their own Dead pattern DW.
    mass_patterns = {"SD": 1.0, "L": live_share}
    if frame_loads:
        mass_patterns["DW"] = 1.0
    if any(p["case"] == "F" and p["massShare"] for p in point_loads):
        mass_patterns["F"] = 1.0
    out["mass_source"] = {"self": True, "patterns": mass_patterns}
    out["seismic"] = {
        "C": seismic.get("Sa_g"),
        "K": seismic.get("k", 1.0),
        "top": stories[-1].id if stories else None,
    }

    # cracked modifiers by object type, from the analysis model's overrides
    secs = {s["id"]: s for s in model["sections"]}
    lateral = next((a for a in model["analyses"] if a["type"] == "Modal"), None) or next(
        (a for a in model["analyses"] if a.get("section_overrides")), {}
    )
    frame_mods: dict[str, list[float]] = {}
    area_mods: dict[str, list[float]] = {}
    for o in lateral.get("section_overrides", []) or []:
        s = secs.get(o["id"])
        if s is None:
            continue
        type_id, _, kind = s["name"].partition(" ")
        if s["type"] == "ElasticSection":
            e = o.get("E", s["E"]) / s["E"]
            target = f"{type_id}-{'COL' if kind.startswith('column') else 'BM'}"
            # both bending axes take the code's factor; keep the larger of the two ratios apart
            frame_mods[target] = [
                e * o.get("A", s["A"]) / s["A"],
                1.0,
                1.0,
                e * o.get("J", s["J"]) / s["J"],
                e * o.get("Iz", s["Iz"]) / s["Iz"],
                e * o.get("Iy", s["Iy"]) / s["Iy"],
                1.0,
                1.0,
            ]
        else:
            memb = o.get("E", s["E"]) / s["E"]
            bend = memb * o.get("Ep_mod", 1.0)
            area_mods[type_id] = [memb, memb, memb, bend, bend, bend, memb, memb, 1.0, 1.0]
    out["modifiers"] = {"frames": frame_mods, "areas": area_mods}
    lateral_cases = sorted(
        {
            p["name"]
            for a in model["analyses"]
            if a.get("section_overrides") and a["type"] == "Static"
            for p in model["load_patterns"]
            if p["id"] in a.get("pattern_ids", [])
        }
    )
    gravity_cases = [c for c in ("D", "DW", "SD", "L", "Lr", "F") if c not in lateral_cases]
    lateral_cases = [c for c in ("EX", "EY") if c in lateral_cases] or ["EX", "EY"]
    cracked_modal = bool(
        next(
            (a for a in model["analyses"] if a["type"] == "Modal" and a.get("section_overrides")),
            None,
        )
    )
    out["groups"] = [
        {"cracked": True, "patterns": lateral_cases, "modal": cracked_modal},
        {"cracked": False, "patterns": gravity_cases, "modal": not cracked_modal},
    ]
    out["modal"] = next(
        (int(a.get("n_modes", 12)) for a in model["analyses"] if a["type"] == "Modal"), 12
    )
    out["rigidZoneFactor"] = rigid_zone_factor(project, model, settings)
    if out["rigidZoneFactor"] is not None:
        notes.append(
            f"SAEngine's model has rigid end zones: the reference's automatic end offsets take "
            f"the same rigid-zone factor {out['rigidZoneFactor']:g}"
        )
    out["materials"] = list(used_mats.values())
    out["frame_sections"] = list(frame_secs.values())
    out["area_sections"] = list(area_secs.values())
    out["probes"] = [
        {
            "label": s["label"],
            "first": s["label"],
            "last": s["label"],
            "lastStart": 0.0,
            "length": s["length"],
        }
        for s in spans
    ]
    return out


def rigid_zone_factor(project: Path, model: dict[str, Any], settings: Any) -> float | None:
    """The rigid-zone factor of SAEngine's end offsets (D3), when its analysis model has rigid
    end zones: from ``08 FEM/faces.json``, else the analysis settings, else 0.5 (the D3
    default). None when no element has joint offsets."""
    if not any(_joint_offsets(e) for e in model["elements"] if e["type"] == "ElasticBeamColumn"):
        return None
    try:
        faces = json.loads(_read(project, "08 FEM/faces.json") or "{}")
        if faces.get("rigidZoneFactor") is not None:
            return float(faces["rigidZoneFactor"])
    except (ValueError, TypeError):
        pass
    value = getattr(settings.analysis, "rigidZoneFactor", None)
    return float(value) if value is not None else 0.5


def _rect_opening(o: Any, z: float) -> list[list[float]]:
    c, s = math.cos(math.radians(o.rotation)), math.sin(math.radians(o.rotation))
    pts = []
    for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        lx, ly = dx * o.xDim / 2, dy * o.yDim / 2
        pts.append([(o.x + lx * c - ly * s) * MM, (o.y + lx * s + ly * c) * MM, z])
    return pts


def _on_beams(
    beams: list[dict[str, Any]], p0: list[float], p1: list[float]
) -> list[tuple[str, float, float]]:
    """The beams under a partition from ``p0`` to ``p1`` (m): (beam, relative start, end)."""
    placed = []
    for f in beams:
        a, b = f["i"], f["j"]
        length = math.dist(a, b)
        if length < 1e-6 or abs(a[2] - p0[2]) > 1e-3:
            continue
        axis = [(b[k] - a[k]) / length for k in range(3)]
        if _off_line(p0, a, axis, math.inf) > 1e-3 or _off_line(p1, a, axis, math.inf) > 1e-3:
            continue
        t0, t1 = sorted((_project_on(p0, a, axis), _project_on(p1, a, axis)))
        lo, hi = max(t0, 0.0), min(t1, length)
        if hi - lo > 1e-3:
            placed.append((f["name"], lo / length, hi / length))
    return placed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, type=Path, help="a COPY of the project folder")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--members", default="", help="building-model ids, comma separated")
    ap.add_argument("--skip-run", action="store_true", help="use the copy's existing results")
    args = ap.parse_args(argv)
    project: Path = args.project.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    run = None
    if not args.skip_run:
        print(f"SAEngine: derive + analysis on {project}", file=sys.stderr)
        run = run_saengine(project)
    derived = derive_summary(project)
    bim = json.loads(_read(project, "06 BIM/bim.json"))
    members = [m.strip() for m in args.members.split(",") if m.strip()] or default_members(bim)
    sae, extra = saengine_results(project, members, derived["summary"], derived["notes"])
    sae["members_requested"] = members
    if run is not None:
        sae["run"] = [
            {k: s.get(k) for k in ("id", "status", "message")} for s in run.get("steps", [])
        ]
        sae["version"] = run.get("saengine")
    (args.out / "saengine.json").write_text(json.dumps(sae, indent=1), encoding="utf-8")
    mirror = mirror_input(project, extra["spans"])
    (args.out / "mirror_input.json").write_text(json.dumps(mirror), encoding="utf-8")
    native = native_input(project, extra["spans"], sae["seismic"])
    (args.out / "native_input.json").write_text(json.dumps(native), encoding="utf-8")
    print(
        f"SAEngine: W {sae['seismic']['W_kN']:.1f} kN, V {sae['seismic']['V_kN']:.2f} kN, "
        f"{len(mirror['nodes'])} nodes / {len(mirror['frames'])} frames / "
        f"{len(mirror['shells'])} shells; native: {len(native['frames'])} frames, "
        f"{len(native['areas'])} areas; members {', '.join(members)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
