"""SAEngine's own results of an analysed model, at the probes of the solver-neutral model.

    python saengine_side.py --model "<project>/08 FEM/model.osmodel" --ir ir.json --out saengine.json

Runs with SAEngine's Python and reads the results the way SAEngine does: OpenSees Studio's
result store (:mod:`opensees_studio.services.result_store`) and SAEngine's own support-face
forces (:func:`saengine.fem.end_zones.face_forces`). The output has the same layout as the
other solvers' (``run_pynite.py``, ``run_ccx.py``). Units: N, m, kg, s.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _last(rows: Any) -> np.ndarray:
    a = np.asarray(rows, dtype=float)
    return a[-1] if a.ndim > 1 else a


def results_dir(model_path: Path) -> Path:
    name = model_path.name
    stem = name[: -len(".osmodel")] if name.lower().endswith(".osmodel") else name
    return model_path.parent / f"{stem}.results"


def saengine_results(model_path: Path, ir: dict[str, Any]) -> dict[str, Any]:
    import saengine
    from opensees_studio.services import result_store as rs
    from opensees_studio.services.results import StaticResults
    from saengine.fem.end_zones import face_forces, section_at

    out_dir = results_dir(model_path)
    project = json.loads(model_path.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in project["nodes"]}
    analyses = {a["id"]: a for a in project["analyses"]}
    patterns = {p["id"]: p for p in project["load_patterns"]}
    manifest = rs.load_manifest(out_dir)
    by_code = {a["code"]: a for a in ir["analyses"]}
    frames = {f["id"]: f for f in ir["frames"]}
    faces = face_forces(model_path, out_dir).get("cases", {})
    probe_frames = list(ir["probes"]["frames"])
    for fid in list(probe_frames):
        for face in (ir["faces"].get(str(fid)) or {}).values():
            if int(face["at"][0]) not in probe_frames:
                probe_frames.append(int(face["at"][0]))

    result: dict[str, Any] = {"solver": "SAEngine", "version": saengine.__version__, "cases": {}}
    for entry in manifest["cases"]:
        analysis = analyses.get(int(entry["case_id"]), {})
        code = str(entry["case_name"]).split(":")[0].strip()
        if code not in by_code:
            continue
        r = rs.load_results(entry, out_dir)
        if isinstance(r, StaticResults):
            total = np.zeros(6)
            for nid, rows in r.node_reaction.items():
                v = _last(rows)
                p = np.asarray(nodes[nid]["coords"], dtype=float)
                total[:3] += v[:3]
                total[3:] += v[3:6] + np.cross(p, v[:3])
            disp = {
                str(n): _last(r.node_disp[n])[:6].tolist()
                for n in ir["probes"]["nodes"]
                if n in r.node_disp
            }
            loads: dict[int, np.ndarray] = {}
            for pid in analysis.get("pattern_ids", []):
                for x in patterns[pid].get("element_loads", []) or []:
                    w = loads.setdefault(int(x["element_id"]), np.zeros(3))
                    w += [x.get("wx", 0.0), x.get("wy", 0.0), x.get("wz", 0.0)]
            frame_out: dict[str, Any] = {}
            for fid in probe_frames:
                if fid not in r.element_forces:
                    continue
                f12 = _last(r.element_forces[fid])[:12]
                w = loads.get(fid, np.zeros(3))
                flex = frames[fid]["length"] - sum(frames[fid]["rigid"])
                frame_out[str(fid)] = {
                    "length": flex,
                    "ends": {
                        "i": section_at(f12, w, 0.0).tolist(),
                        "j": section_at(f12, w, flex).tolist(),
                    },
                    "stations": {},
                }
            for key, ends in (faces.get(code) or {}).items():
                for end, values in ends.items():
                    at = int(ir["faces"][key][end]["at"][0])
                    if str(at) in frame_out:
                        frame_out[str(at)]["stations"][f"{key}/{end}"] = [
                            values[c] for c in ("N", "Vy", "Vz", "T", "My", "Mz")
                        ]
            shell_out: dict[str, Any] = {}
            for sid in ir["probes"]["shells"]:
                rows = r.shell_forces.get(sid)
                if rows is None or not len(rows):
                    continue
                v = _last(rows).reshape(-1, 8).mean(axis=0)
                n_t = np.array([[v[0], v[2]], [v[2], v[1]]])
                m_t = np.array([[v[3], v[5]], [v[5], v[4]]])
                shell_out[str(sid)] = {"N": invariants(n_t), "M": invariants(m_t)}
            result["cases"][code] = {
                "reactions": total.tolist(),
                "disp": disp,
                "frames": frame_out,
                "shells": shell_out,
            }
        elif analysis.get("type") == "Modal":
            ev = np.asarray(r.eigenvalues, dtype=float)
            ids = [n["id"] for n in project["nodes"]]
            idx = {nid: i for i, nid in enumerate(ids)}
            mass = np.array([n.get("mass") or [0.0] * 6 for n in project["nodes"]], dtype=float)
            eff = []
            for mode in sorted(r.mode_shapes):
                shape = np.zeros((len(ids), 6))
                for nid, v in r.mode_shapes[mode].items():
                    shape[idx[nid]] = _last(v)[:6]
                mm = float((mass * shape * shape).sum())
                lx = float((mass[:, 0] * shape[:, 0]).sum())
                ly = float((mass[:, 1] * shape[:, 1]).sum())
                eff.append([lx * lx / mm, ly * ly / mm] if mm else [0.0, 0.0])
            result["modal"] = {
                "periods": [float(2 * math.pi / math.sqrt(v)) for v in ev if v > 0],
                "effMass": eff,
                "massTotal": [float(mass[:, k].sum()) for k in range(3)],
            }
    return result


def invariants(t: np.ndarray) -> dict[str, float]:
    mean = (t[0, 0] + t[1, 1]) / 2
    radius = math.hypot((t[0, 0] - t[1, 1]) / 2, (t[0, 1] + t[1, 0]) / 2)
    return {"mean": float(mean), "radius": float(radius)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--ir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    res = saengine_results(args.model, ir)
    args.out.write_text(json.dumps(res), encoding="utf-8")
    print(f"SAEngine {res['version']}: {len(res['cases'])} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
