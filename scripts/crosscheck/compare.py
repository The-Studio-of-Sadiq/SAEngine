"""Compare SAEngine's results with PyNite's and CalculiX's and write the report.

    python compare.py --dir <model dir>      (ir.json, saengine.json, pynite.json, ccx.json)

Writes ``<dir>/report.md`` and ``<dir>/comparison.json``: every quantity with the three
values, the differences, the tolerance and PASS or FLAG, a FLAG with its reason. The PASS test
is the Verification Manual's (:class:`saengine.verification.cases.common.Quantity`: the
SAEngine value over the reference within a relative tolerance), with an absolute floor for
values too small to matter (a difference below the floor passes and says so).

Tolerances (the cross-check's contract): base reactions 0.5 %, periods 2 %, displacements and
storey drifts 5 %, member forces 5 %, shell resultants 5 %; effective modal masses 5 % with a
floor of 1 % of the total mass. Forces are compared as magnitudes on SAEngine's element axes
(each program's own sign convention aside).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TOLERANCE = {
    "reaction": 0.005,
    "period": 0.02,
    "modalMass": 0.05,
    "displacement": 0.05,
    "drift": 0.05,
    "member": 0.05,
    "shell": 0.05,
}
SOLVERS = ("pynite", "ccx")
NAMES = {"pynite": "PyNite", "ccx": "CalculiX"}
LATERAL = {"EX": 0, "EY": 1, "WX": 0, "WY": 1, "EXP": 0, "EXN": 0, "EYP": 1, "EYN": 1}
MEMBER_CASES = ("D", "L", "EX", "EY")
COMPONENTS = ("N", "Vy", "Vz", "T", "My", "Mz")


@dataclass
class Row:
    group: str
    name: str
    case: str
    unit: str
    kind: str
    saengine: float | None
    values: dict[str, float | None]
    floor: float = 0.0
    status: dict[str, str] = field(default_factory=dict)
    diff_pct: dict[str, float | None] = field(default_factory=dict)
    reason: dict[str, str] = field(default_factory=dict)


def judge(row: Row, reasons: dict[str, str]) -> Row:
    from saengine.verification.cases.common import Quantity

    tol = TOLERANCE[row.kind]
    for solver in SOLVERS:
        ref = row.values.get(solver)
        if ref is None or row.saengine is None:
            row.status[solver], row.diff_pct[solver] = "n/a", None
            continue
        a, b = abs(row.saengine), abs(ref)
        q = Quantity(row.name, row.unit, b, a, tol)
        row.diff_pct[solver] = (q.ratio - 1) * 100 if b > 0 and math.isfinite(q.ratio) else None
        if q.passed:
            row.status[solver] = "PASS"
        elif abs(a - b) <= row.floor:
            row.status[solver] = "PASS"
            row.reason[solver] = f"difference below the floor {row.floor:.3g} {row.unit}"
        else:
            row.status[solver] = "FLAG"
            row.reason[solver] = reasons.get(f"{solver}:{row.kind}") or reasons.get(
                row.kind, "difference above tolerance: investigate"
            )
    return row


# ─────────────────────────────── the quantities ───────────────────────────────


def _get(doc: dict[str, Any] | None, *keys: Any) -> Any:
    for k in keys:
        if doc is None:
            return None
        doc = doc.get(k) if isinstance(doc, dict) else (doc[k] if k < len(doc) else None)
    return doc


def storeys(ir: dict[str, Any]) -> tuple[float, list[tuple[int, float]]]:
    """The base level and the diaphragms' retained nodes by height."""
    z = {n["id"]: n["xyz"][2] for n in ir["nodes"]}
    held = [z[n["id"]] for n in ir["nodes"] if all(n["restraint"][:3])]
    base = min(held) if held else min(z.values())
    masters = sorted(
        ((d["retained"], z[d["retained"]]) for d in ir["diaphragms"]), key=lambda t: t[1]
    )
    return base, masters


def top_node(ir: dict[str, Any]) -> int | None:
    _, masters = storeys(ir)
    if masters:
        return masters[-1][0]
    z = {n["id"]: n["xyz"][2] for n in ir["nodes"]}
    probes = ir["probes"]["nodes"]
    return max(probes, key=lambda n: z[n]) if probes else None


def rows_for(ir: dict[str, Any], sae: dict[str, Any], res: dict[str, dict[str, Any]]) -> list[Row]:
    rows: list[Row] = []
    cases = list(sae["cases"])
    # base reactions
    for case in cases:
        r = sae["cases"][case]["reactions"]
        big = max(abs(v) for v in r[:3]) or 1.0
        for k, comp in enumerate(("FX", "FY", "FZ", "MX", "MY", "MZ")):
            if abs(r[k]) < (0.01 * big if k < 3 else 0.01 * max(abs(v) for v in r[3:]) or 1.0):
                continue
            rows.append(
                Row(
                    "reactions",
                    f"Base {comp}",
                    case,
                    "kN" if k < 3 else "kN·m",
                    "reaction",
                    r[k] / 1e3,
                    {s: _scaled(_get(res[s], "cases", case, "reactions", k)) for s in SOLVERS},
                    floor=1e-4 * big / 1e3,
                )
            )
    # displacements: the dominant translation of the top node and of the other probed nodes
    # that are not a diaphragm's (a plate's centre)
    top = top_node(ir)
    masters = {d["retained"] for d in ir["diaphragms"]}
    probed = [top] + [n for n in ir["probes"]["nodes"] if n != top and n not in masters]
    for node in [n for n in probed if n is not None]:
        for case in cases:
            d = _get(sae, "cases", case, "disp", str(node))
            if not d:
                continue
            k = max(range(3), key=lambda i: abs(d[i]))
            if abs(d[k]) < 1e-6:
                continue  # nothing moves there (a retained node under gravity, a held edge)
            where = "Top" if node == top else "Node"
            rows.append(
                Row(
                    "displacements",
                    f"{where} u{'xyz'[k]} (node {node})",
                    case,
                    "mm",
                    "displacement",
                    d[k] * 1e3,
                    {
                        s: _scaled(_get(res[s], "cases", case, "disp", str(node), k), 1e3)
                        for s in SOLVERS
                    },
                    floor=1e-3,
                )
            )
    # storey drifts (the diaphragms' retained nodes)
    base, masters = storeys(ir)
    for case in cases:
        if case not in LATERAL:
            continue
        k = LATERAL[case]
        below = {"saengine": 0.0, **{s: 0.0 for s in SOLVERS}}
        z0 = base
        for level, (node, z) in enumerate(masters, start=1):
            h = z - z0
            values: dict[str, float | None] = {}
            u_sae = _get(sae, "cases", case, "disp", str(node), k)
            for s in SOLVERS:
                u = _get(res[s], "cases", case, "disp", str(node), k)
                values[s] = None if u is None or below[s] is None else (u - below[s]) / h
                below[s] = u
            if u_sae is None:
                break
            drift = (u_sae - below["saengine"]) / h
            below["saengine"] = u_sae
            rows.append(
                Row(
                    "drifts",
                    f"Storey {level} drift ({'XY'[k]}, z = {z:.2f} m)",
                    case,
                    "‰",
                    "drift",
                    drift * 1e3,
                    {s: None if v is None else v * 1e3 for s, v in values.items()},
                    floor=1e-4,
                )
            )
            z0 = z
    # modal
    modal = sae.get("modal")
    if modal:
        total = max(modal["massTotal"][:2]) / 1e3
        for m in range(min(3, len(modal["periods"]))):
            rows.append(
                Row(
                    "modal",
                    f"T{m + 1}",
                    "Modal",
                    "s",
                    "period",
                    modal["periods"][m],
                    {s: _get(res[s], "modal", "periods", m) for s in SOLVERS},
                )
            )
            for k, comp in enumerate(("UX", "UY")):
                rows.append(
                    Row(
                        "modal",
                        f"Mode {m + 1} effective mass {comp}",
                        "Modal",
                        "t",
                        "modalMass",
                        modal["effMass"][m][k] / 1e3,
                        {s: _scaled(_get(res[s], "modal", "effMass", m, k)) for s in SOLVERS},
                        floor=0.01 * total,
                    )
                )
    # member forces at the flexible ends and the support faces; floors: 2 % of the member's
    # largest force (moment) in the case, at least 0.5 % of the largest of all probed members
    for case in cases:
        if case not in MEMBER_CASES:
            continue
        frames = sae["cases"][case]["frames"]

        def peak(f: dict[str, Any], comps: tuple[int, ...]) -> float:
            stations = [f["ends"]["i"], f["ends"]["j"], *f.get("stations", {}).values()]
            return max((abs(v[c]) for v in stations for c in comps), default=0.0)

        case_peak = (
            max((peak(f, (0, 1, 2)) for f in frames.values()), default=0.0),
            max((peak(f, (3, 4, 5)) for f in frames.values()), default=0.0),
        )
        for fid, f in frames.items():
            stations = {"i": f["ends"]["i"], "j": f["ends"]["j"], **f.get("stations", {})}
            floors = (
                max(0.02 * peak(f, (0, 1, 2)), 0.005 * case_peak[0]),
                max(0.02 * peak(f, (3, 4, 5)), 0.005 * case_peak[1]),
            )
            name = next((x["name"] for x in ir["frames"] if str(x["id"]) == fid), fid)
            for station, values in stations.items():
                for c, comp in enumerate(COMPONENTS):

                    def other(
                        s: str, station: str = station, c: int = c, case: str = case, fid: str = fid
                    ) -> float | None:
                        f2 = _get(res[s], "cases", case, "frames", fid)
                        v = (
                            _get(f2, "ends", station, c)
                            if station in ("i", "j")
                            else _get(f2, "stations", station, c)
                        )
                        return None if v is None else v / 1e3

                    label = (
                        f"end {station}"
                        if station in ("i", "j")
                        else f"face {station.split('/')[1]}"
                    )
                    rows.append(
                        Row(
                            "members",
                            f"{name} (element {fid}) {comp} at {label}",
                            case,
                            "kN" if c < 3 else "kN·m",
                            "member",
                            values[c] / 1e3,
                            {s: other(s) for s in SOLVERS},
                            floor=(floors[0] if c < 3 else floors[1]) / 1e3,
                        )
                    )
    # shell resultants
    for case in cases:
        if case not in MEMBER_CASES:
            continue
        shells = sae["cases"][case].get("shells") or {}
        if not shells:
            continue
        for what, unit in (("M", "kN·m/m"), ("N", "kN/m")):
            peak = max(
                (abs(v[what]["mean"]) + v[what]["radius"] for v in shells.values()), default=0
            )
            if peak <= 0:
                continue
            for sid, v in shells.items():
                name = next((x["name"] for x in ir["shells"] if str(x["id"]) == sid), sid)
                for label, fn in (
                    ("mean", lambda t: abs(t["mean"])),
                    ("max principal", lambda t: abs(t["mean"]) + t["radius"]),
                ):
                    rows.append(
                        Row(
                            "shells",
                            f"{name} (element {sid}) {what} {label}",
                            case,
                            unit,
                            "shell",
                            fn(v[what]) / 1e3,
                            {
                                s: (
                                    None
                                    if _get(res[s], "cases", case, "shells", sid, what) is None
                                    else fn(res[s]["cases"][case]["shells"][sid][what]) / 1e3
                                )
                                for s in SOLVERS
                            },
                            floor=0.02 * peak / 1e3,
                        )
                    )
    return rows


def _scaled(v: float | None, factor: float = 1e-3) -> float | None:
    return None if v is None else v * factor


# ─────────────────────────────── reasons ───────────────────────────────


def reasons_for(ir: dict[str, Any], res: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The reason a FLAG of each kind gets, from what the model has (the formulation and
    modelling differences between the programs; ``docs/verification/cross-check.md``)."""
    has_shells = bool(ir["shells"])
    triangles = any(len(s["nodes"]) == 3 for s in ir["shells"])
    torsion = any("torsional stiffness" in n for n in res["ccx"].get("notes", []))
    shell = (
        "shell formulation and mesh: SAEngine's ASDShellQ4 (OpenSees) against "
        "{other}; the resultant is read at the element centre"
    )
    out = {
        "pynite:shell": shell.format(other="PyNite's MITC4 quadrilateral")
        + (" (a triangle becomes a quadrilateral with a mid-edge node)" if triangles else ""),
        "ccx:shell": shell.format(other="CalculiX's US3 triangles (two per quadrilateral)"),
        "reaction": "the sum of the reactions: an equilibrium check, investigate",
    }
    if has_shells:
        lateral = (
            "the shells' in-plane and bending stiffness ({other}) changes how the lateral load "
            "shares between walls, slabs and frames"
        )
        out["pynite:drift"] = lateral.format(other="PyNite MITC4 against ASDShellQ4")
        out["pynite:displacement"] = out["pynite:drift"]
        out["ccx:drift"] = lateral.format(other="CalculiX US3 triangles against ASDShellQ4")
        out["ccx:displacement"] = out["ccx:drift"]
        out["pynite:member"] = (
            "members framing into shells: the force sharing follows the shell formulation "
            "(PyNite MITC4 against ASDShellQ4)"
        )
        out["ccx:member"] = (
            "members framing into shells: the force sharing follows the shell formulation "
            "(CalculiX US3 triangles against ASDShellQ4)"
        )
        out["pynite:period"] = out["pynite:drift"]
        out["ccx:period"] = out["ccx:drift"]
        out["pynite:modalMass"] = out["pynite:drift"]
        out["ccx:modalMass"] = out["ccx:drift"]
    if torsion:
        out["ccx:period"] = (
            out.get("ccx:period", "")
            + ("; " if "ccx:period" in out else "")
            + "CalculiX's U1 beam takes its torsion from the polar moment Iy + Iz, which a "
            "Poisson's ratio below 0.5 cannot bring down to J (deep beams stiffer in torsion)"
        )
    return out


# ─────────────────────────────── the report ───────────────────────────────


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    a = abs(v)
    if a == 0:
        return "0"
    if a < 0.01:
        return f"{v:.3e}"
    return f"{v:.4g}" if a < 100 else f"{v:.1f}"


def _diff(v: float | None) -> str:
    return "-" if v is None else f"{v:+.2f} %"


def summary(rows: list[Row]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        for s in SOLVERS:
            cell = out.setdefault(r.group, {}).setdefault(
                s, {"PASS": 0, "FLAG": 0, "n/a": 0, "max": 0.0}
            )
            cell[r.status[s]] = cell.get(r.status[s], 0) + 1
            measured = r.status[s] in ("PASS", "FLAG") and r.diff_pct[s] is not None
            if measured and (r.status[s] == "FLAG" or "floor" not in r.reason.get(s, "")):
                cell["max"] = max(cell["max"], abs(r.diff_pct[s]))
    return out


TITLES = {
    "reactions": "Base reactions (sum over the supports)",
    "displacements": "Displacements (top, plate centre)",
    "drifts": "Storey drifts (diaphragm retained nodes)",
    "modal": "Periods and effective modal masses",
    "members": "Member forces (flexible ends and support faces)",
    "shells": "Shell resultants (element centre)",
}


def report(meta: dict[str, Any], rows: list[Row], notes: dict[str, list[str]]) -> str:
    counts = summary(rows)
    lines = [
        f"## {meta['title']}",
        "",
        meta.get("description", ""),
        "",
        (
            f"Model: {meta['nodes']} nodes, {meta['frames']} frames, {meta['shells']} shells, "
            f"{meta['diaphragms']} rigid diaphragms; cases {', '.join(meta['cases'])}. "
            f"PyNite {meta['versions'].get('pynite', '-')} ({meta['seconds'].get('pynite', '-')} s), "
            f"CalculiX {meta['versions'].get('ccx', '-')} ({meta['seconds'].get('ccx', '-')} s)."
        ),
        "",
        "| Quantity | Tol | PyNite PASS/FLAG | PyNite max diff | CalculiX PASS/FLAG | CalculiX max diff |",
        "|---|---|---|---|---|---|",
    ]
    for group, title in TITLES.items():
        if group not in counts:
            continue
        kinds = {r.kind for r in rows if r.group == group}
        tol = "/".join(f"{TOLERANCE[k] * 100:g} %" for k in sorted(kinds))
        cells = []
        for s in SOLVERS:
            c = counts[group][s]
            if c["PASS"] + c["FLAG"] == 0:
                cells += ["n/a", "-"]
            else:
                cells += [f"{c['PASS']}/{c['FLAG']}", f"{c['max']:.2f} %"]
        lines.append(f"| {title} | {tol} | " + " | ".join(cells) + " |")
    lines.append("")
    detail = [r for r in rows if r.group in ("reactions", "displacements", "modal")]
    detail += [r for r in rows if r.group == "drifts" and r.case in ("EX", "EY")]
    if detail:
        lines += [
            "| Quantity | Case | SAEngine | PyNite | diff | CalculiX | diff | Status |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in detail:
            status = "/".join(r.status[s] for s in SOLVERS)
            lines.append(
                f"| {r.name} | {r.case} | {_fmt(r.saengine)} {r.unit} | {_fmt(r.values['pynite'])} "
                f"| {_diff(r.diff_pct['pynite'])} | {_fmt(r.values['ccx'])} | "
                f"{_diff(r.diff_pct['ccx'])} | {status} |"
            )
        lines.append("")
    flags = [(r, s) for r in rows for s in SOLVERS if r.status[s] == "FLAG"]
    if flags:
        lines += [
            f"FLAGs ({len(flags)}):",
            "",
            "| Program | Quantity | Case | SAEngine | Other | diff | Reason |",
            "|---|---|---|---|---|---|---|",
        ]
        for r, s in flags:
            lines.append(
                f"| {NAMES[s]} | {r.name} | {r.case} | {_fmt(r.saengine)} {r.unit} | "
                f"{_fmt(r.values[s])} | {_diff(r.diff_pct[s])} | {r.reason[s]} |"
            )
        lines.append("")
    for who, items in notes.items():
        unique = list(dict.fromkeys(items))
        if unique:
            lines += [f"Notes ({who}):", ""] + [f"- {n}" for n in unique] + [""]
    return "\n".join(lines)


def compare_dir(folder: Path, title: str | None = None, description: str = "") -> dict[str, Any]:
    ir = json.loads((folder / "ir.json").read_text(encoding="utf-8"))
    sae = json.loads((folder / "saengine.json").read_text(encoding="utf-8"))
    res = {}
    for s, file in (("pynite", "pynite.json"), ("ccx", "ccx.json")):
        path = folder / file
        res[s] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"cases": {}}
    rows = [judge(r, reasons_for(ir, res)) for r in rows_for(ir, sae, res)]
    meta = {
        "title": title or folder.name,
        "description": description,
        "nodes": len(ir["nodes"]),
        "frames": len(ir["frames"]),
        "shells": len(ir["shells"]),
        "diaphragms": len(ir["diaphragms"]),
        "cases": list(sae["cases"]) + (["Modal"] if sae.get("modal") else []),
        "versions": {s: res[s].get("version") for s in SOLVERS},
        "seconds": {s: res[s].get("seconds") for s in SOLVERS},
    }
    notes = {
        "model": ir.get("notes", []),
        "PyNite": res["pynite"].get("notes", []),
        "CalculiX": res["ccx"].get("notes", []),
    }
    text = report(meta, rows, notes)
    (folder / "report.md").write_text(text, encoding="utf-8")
    doc = {"meta": meta, "summary": summary(rows), "rows": [asdict(r) for r in rows]}
    (folder / "comparison.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--title")
    args = ap.parse_args(argv)
    doc = compare_dir(args.dir, args.title)
    flags = sum(c["FLAG"] for g in doc["summary"].values() for c in g.values())
    print(f"{args.dir.name}: {len(doc['rows'])} quantities, {flags} FLAGs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
