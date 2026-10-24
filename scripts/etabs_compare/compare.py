"""Compare SAEngine's results with the reference program's and write the report.

    python compare.py --saengine saengine.json --reference reference.json --out <dir>

Writes ``report.md`` and ``results.json`` into ``<dir>``: every quantity with both values, the
difference, the tolerance and PASS or FLAG with a short reason. Pure standard library and no
analysis program needed: this module is what the CI-safe unit tests exercise.

Tolerances (the harness's contract): periods 2 %, base reactions 1 %, static base shear V and
the seismic weight W 2 %, storey shears 2 %, storey drifts 5 %, member moments at the support
faces 5 %, effective modal masses 5 %. A difference below a quantity's absolute floor (a value
too small to matter) passes and says so.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

G = 9.80665

#: Relative tolerances and absolute floors (in the quantity's units).
TOLERANCES: dict[str, dict[str, float]] = {
    "period": {"rel": 0.02, "abs": 1e-4},
    "modalMass": {"rel": 0.05, "abs": 0.0},  # floor: 1 % of the total mass, set per run
    "reaction": {"rel": 0.01, "abs": 0.05},
    "baseShear": {"rel": 0.02, "abs": 0.05},
    "weight": {"rel": 0.02, "abs": 0.5},
    "storyShear": {"rel": 0.02, "abs": 0.05},
    "drift": {"rel": 0.05, "abs": 1e-6},
    "faceMoment": {"rel": 0.05, "abs": 0.05},  # raised to 2 % of the member's largest moment
}
GRAVITY = ("D", "SD", "L", "Lr", "F")
LATERAL = {"EX": "FX", "EY": "FY", "WX": "FX", "WY": "FY"}
MEMBER_CASES = ("D", "SD", "L", "EX", "EY")


@dataclass
class Quantity:
    group: str
    name: str
    saengine: float | None
    reference: float | None
    kind: str
    unit: str = ""
    case: str = ""
    diff_pct: float | None = None
    tol_pct: float | None = None
    status: str = "INFO"
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def judge(q: Quantity, reasons: dict[str, str], floor: float | None = None) -> Quantity:
    """PASS or FLAG ``q`` against its kind's tolerance; the reason of a FLAG comes from
    ``reasons`` (by kind), else a generic one."""
    tol = TOLERANCES.get(q.kind)
    if q.saengine is None or q.reference is None:
        q.status = "MISSING"
        q.reason = "not available from " + ("SAEngine" if q.saengine is None else "the reference")
        return q
    a, b = abs(q.saengine), abs(q.reference)
    diff = b - a
    q.diff_pct = (diff / a * 100.0) if a > 0 else (0.0 if b == 0 else math.inf)
    if tol is None:
        q.status = "INFO"
        return q
    q.tol_pct = tol["rel"] * 100.0
    limit = max(tol["abs"], floor or 0.0)
    if abs(diff) <= tol["rel"] * a:
        q.status, q.reason = "PASS", "within tolerance"
    elif abs(diff) <= limit:
        q.status, q.reason = (
            "PASS",
            f"difference {abs(diff):.3g} below the absolute floor {limit:.3g}",
        )
    else:
        q.status = "FLAG"
        q.reason = reasons.get(q.kind, "difference above tolerance: investigate")
    return q


# ─────────────────────────────── member forces at a station ───────────────────────────────


def internal_forces(fi: list[float], w: list[float], x: float) -> list[float]:
    """Internal forces [N, Vy, Vz, T, My, Mz] (local) at ``x`` from end i of an element with
    end-i forces ``fi`` (the forces on the element, OpenSees localForce) and uniform local
    load ``w`` = [wx, wy, wz] per length. Free body from i to x; the signs are those of the
    part beyond x acting on it, only the magnitudes are compared."""
    n, vy, vz, t, my, mz = fi
    wx, wy, wz = w
    return [
        -(n + wx * x),
        -(vy + wy * x),
        -(vz + wz * x),
        -t,
        -(my + vz * x + wz * x * x / 2),
        -(mz - vy * x - wy * x * x / 2),
    ]


def saengine_at(span: dict[str, Any], case: str, station: float) -> dict[str, Any] | None:
    """SAEngine's internal forces of a span at ``station`` (m from its start): from the
    sub-element containing it, by statics from that sub-element's end i."""
    best = None
    for sub in span["subs"]:
        lo, hi = min(sub["a"], sub["b"]), max(sub["a"], sub["b"])
        if lo - 1e-6 <= station <= hi + 1e-6:
            best = sub
            if station < hi - 1e-6 or sub is span["subs"][-1]:
                break
    if best is None or case not in best["cases"]:
        return None
    data = best["cases"][case]
    x = abs(station - best["a"])
    f = internal_forces(data["fi"], data["w"], x)
    return {"f": f, "axes": best["axes"]}


def moment_components(
    kind: str, local: list[float], axes: dict[str, list[float]]
) -> dict[str, float]:
    """The moment magnitudes compared: a column's about global X and Y, a beam's or brace's
    major (about its horizontal axis) and minor."""
    my, mz = local[4], local[5]
    if kind == "column":
        y, z = axes["y"], axes["z"]
        gx = my * y[0] + mz * z[0]
        gy = my * y[1] + mz * z[1]
        return {"Mx": abs(gx), "My": abs(gy)}
    return {"Mmajor": abs(my), "Mminor": abs(mz)}


def reference_components(kind: str, row: dict[str, Any], angle_deg: float) -> dict[str, float]:
    """The reference program's moments (M2 about local 2, M3 about local 3) in the same terms:
    for a vertical frame local 2 is global X turned by its angle."""
    m2, m3 = row["M2"], row["M3"]
    if kind == "column":
        c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
        return {"Mx": abs(m2 * c - m3 * s), "My": abs(m2 * s + m3 * c)}
    return {"Mmajor": abs(m3), "Mminor": abs(m2)}


# ─────────────────────────────── the reference program's output ───────────────────────────────


def _csv(run: dict[str, Any], key: str) -> list[dict[str, str]]:
    t = (run.get("tables") or {}).get(key) or {}
    text = t.get("csv") or ""
    return list(csv.DictReader(io.StringIO(text))) if text else []


def _field(row: dict[str, str], *names: str) -> str | None:
    low = {k.lower().replace(" ", ""): v for k, v in row.items() if k}
    for n in names:
        v = low.get(n.lower().replace(" ", ""))
        if v not in (None, ""):
            return v
    return None


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def runs_of(ref: dict[str, Any]) -> list[dict[str, Any]]:
    runs = ref.get("runs") or []
    return runs if isinstance(runs, list) else [runs]


def run_with(ref: dict[str, Any], case: str) -> dict[str, Any] | None:
    for run in runs_of(ref):
        if case in _as_list(run.get("cases")):
            return run
    return None


def ref_base(ref: dict[str, Any], case: str) -> dict[str, float] | None:
    """The reference's base reaction of ``case``; D includes DW, the partitions the native
    model puts in a Dead pattern of their own (kept out of the mass source's self-weight)."""
    run = run_with(ref, case)
    found = None
    for row in _as_list((run or {}).get("base")):
        if row.get("case") == case:
            found = dict(row)
    if found is not None and case == "D":
        extra = ref_base(ref, "DW")
        if extra is not None:
            for k in ("FX", "FY", "FZ", "MX", "MY", "MZ"):
                found[k] = found.get(k, 0.0) + extra.get(k, 0.0)
    return found


def ref_total_mass(ref: dict[str, Any]) -> float | None:
    """The reference's participating mass (t): its mass summary without the base."""
    for run in runs_of(ref):
        rows = _csv(run, "Mass Summary by Story")
        if rows:
            return sum(
                _num(_field(r, "UX", "Mass X")) or 0.0
                for r in rows
                if (_field(r, "Story") or "").lower() != "base"
            )
    return None


def ref_weight(ref: dict[str, Any]) -> tuple[float | None, str]:
    """The reference's seismic weight (kN): its static earthquake's weight used, else its
    participating mass times g."""
    for run in runs_of(ref):
        for key in (
            "Auto Seismic - User Coefficients",
            "Load Pattern Definitions - Auto Seismic - User Coefficient",
        ):
            for r in _csv(run, key):
                w = _num(_field(r, "Weight Used", "WeightUsed"))
                if w:
                    return w, "static earthquake's weight used"
    m = ref_total_mass(ref)
    return (m * G if m is not None else None), "participating mass x g"


def ref_cm(ref: dict[str, Any], case: str) -> dict[str, list[float]]:
    run = run_with(ref, case)
    out: dict[str, list[float]] = {}
    for r in _csv(run or {}, "Diaphragm Center Of Mass Displacements"):
        if _field(r, "Output Case", "OutputCase") != case:
            continue
        story = _field(r, "Story") or ""
        ux, uy = _num(_field(r, "UX")), _num(_field(r, "UY"))
        if ux is not None and uy is not None:
            out[story] = [ux, uy]
    return out


def ref_story_shear(ref: dict[str, Any], case: str) -> dict[str, float]:
    run = run_with(ref, case)
    comp = "VX" if LATERAL.get(case) == "FX" else "VY"
    out: dict[str, float] = {}
    for r in _csv(run or {}, "Story Forces"):
        if (
            _field(r, "Output Case", "OutputCase") != case
            or (_field(r, "Location") or "") != "Bottom"
        ):
            continue
        v = _num(_field(r, comp))
        if v is not None:
            out[_field(r, "Story") or ""] = abs(v)
    return out


# ─────────────────────────────── the comparison ───────────────────────────────


def reasons_for(mode: str, sae: dict[str, Any]) -> dict[str, str]:
    """Short reasons for a FLAG, by quantity kind and mode: the known modelling conventions."""
    settings = sae.get("analysisSettings") or {}
    lumping = settings.get("massLumping", "every node's weight to the level above (pre-D1)")
    mesh = settings.get("meshSize", 1000)
    shells = settings.get("slabs", "shells") == "shells"
    slab_note = (
        f"slab mesh {mesh} mm (D2: 500 mm or span/8)"
        if shells
        else "slab loads to the beams: SAEngine's edge shares vs the reference's membrane distribution"
    )
    if mode == "mirror":
        return {
            "period": "same model: a solver or mass difference; check that the reference lumps no mass",
            "modalMass": "the reference's mode normalisation or mass lumping (it lumps lateral mass at storeys by default)",
            "reaction": "same model, same loads: investigate the load transfer",
            "baseShear": "same nodal forces: investigate",
            "weight": "same joint masses: investigate",
            "storyShear": "same nodal forces: investigate",
            "drift": "same model: a stiffness difference (thick vs thin shells, element formulation)",
            "faceMoment": (
                f"slab mesh not converged at {mesh} mm (D2: 500 mm or span/8) or shell formulation"
                if shells
                else "same frame model and loads: investigate"
            ),
        }
    return {
        "period": "conventions: rigid end zones, thin shells, storey mass lumping, column angle (snapped rotation)",
        "modalMass": f"storey mass lumping (D1): SAEngine's lumping is '{lumping}'",
        "reaction": "loaded areas differ: self-weight overlaps at joints (counted in full in SAEngine), openings, equipment as point loads; see the notes",
        "baseShear": f"seismic-weight convention (D1): the reference sends the lower half of the first storey to the base; SAEngine '{lumping}'",
        "weight": f"seismic-weight convention (D1): the reference sends the lower half of the first storey to the base; SAEngine '{lumping}'",
        "storyShear": "follows W (D1) and the vertical distribution",
        "drift": "follows the storey forces (W) and the stiffness conventions (end offsets, thin shells)",
        "faceMoment": f"rigid end zones and auto end offsets (D3); {slab_note}; compared at the same station",
    }


def compare(sae: dict[str, Any], ref: dict[str, Any], mode: str) -> list[Quantity]:
    reasons = reasons_for(mode, sae)
    out: list[Quantity] = []

    # periods and effective modal masses
    s_modal = sae.get("modal") or {}
    r_run = run_with(ref, "Modal")
    r_modal = sorted(_as_list((r_run or {}).get("modal")), key=lambda r: r["mode"])
    m_ref = ref_total_mass(ref)
    m_sae = s_modal.get("massTotal_t") or 0.0
    for k in range(3):
        s_t = s_modal["periods"][k] if k < len(s_modal.get("periods", [])) else None
        r_t = r_modal[k]["T"] if k < len(r_modal) else None
        out.append(judge(Quantity("modal", f"T{k + 1}", s_t, r_t, "period", "s", "Modal"), reasons))
        for comp, idx in (("UX", 0), ("UY", 1)):
            s_m = s_modal["effMass_t"][k][idx] if k < len(s_modal.get("effMass_t", [])) else None
            r_m = r_modal[k][comp] * m_ref if (k < len(r_modal) and m_ref is not None) else None
            q = Quantity(
                "modal", f"mode {k + 1} effective mass {comp}", s_m, r_m, "modalMass", "t", "Modal"
            )
            q.detail = {
                "saengineRatio": (s_m / m_sae) if (s_m is not None and m_sae) else None,
                "referenceRatio": r_modal[k][comp] if k < len(r_modal) else None,
            }
            out.append(judge(q, reasons, floor=0.01 * m_sae))
    out.append(Quantity("modal", "participating mass", m_sae, m_ref, "info", "t"))

    # base reactions per case
    for case in (*GRAVITY, *LATERAL):
        s = (sae.get("baseReactions") or {}).get(case)
        r = ref_base(ref, case)
        if (s is None or not any(abs(v) > 1e-9 for v in s[:3])) and (
            r is None
            or abs(r.get("FZ", 0.0)) + abs(r.get("FX", 0.0)) + abs(r.get("FY", 0.0)) < 1e-9
        ):
            continue
        comp = LATERAL.get(case, "FZ")
        idx = {"FX": 0, "FY": 1, "FZ": 2}[comp]
        kind = "baseShear" if case in ("EX", "EY") else "reaction"
        q = Quantity(
            "reactions",
            f"base {comp}",
            s[idx] if s else None,
            r[comp] if r else None,
            kind,
            "kN",
            case,
        )
        if s is not None and r is not None and s[idx] * r[comp] < 0 and abs(s[idx]) > 1e-6:
            q.detail["signs"] = "opposite"
        out.append(judge(q, reasons))

    # static seismic weight and base shear
    seis = sae.get("seismic") or {}
    w_ref, how = ref_weight(ref)
    q = Quantity("seismic", "seismic weight W", seis.get("W_kN"), w_ref, "weight", "kN")
    q.detail = {"reference": how, "saengineMass_t": seis.get("massTotal_t")}
    out.append(judge(q, reasons))
    if seis.get("V_kN") is not None:
        for case in ("EX", "EY"):
            r = ref_base(ref, case)
            v_ref = abs(r[LATERAL[case]]) if r else None
            out.append(
                judge(
                    Quantity(
                        "seismic",
                        "static base shear V",
                        seis["V_kN"],
                        v_ref,
                        "baseShear",
                        "kN",
                        case,
                    ),
                    reasons,
                )
            )

    # storeys: shears and centre-of-mass drifts
    stories = sae.get("stories") or {}
    levels = stories.get("levels") or []
    for case in ("EX", "EY"):
        s_sh = (stories.get("shear") or {}).get(case) or {}
        r_sh = ref_story_shear(ref, case)
        for lv in levels:
            s_v, r_v = s_sh.get(lv["name"]), r_sh.get(lv["name"])
            if (s_v is None or abs(s_v) < 1e-9) and (r_v is None or abs(r_v) < 1e-9):
                continue
            out.append(
                judge(
                    Quantity(
                        "stories", f"storey shear {lv['name']}", s_v, r_v, "storyShear", "kN", case
                    ),
                    reasons,
                )
            )
        comp = 0 if case == "EX" else 1
        s_cm = (stories.get("cmDisp") or {}).get(case) or {}
        r_cm = ref_cm(ref, case)
        below_s: float | None = 0.0
        below_r: float | None = 0.0
        for lv in levels:
            name = lv["name"]
            s_u = s_cm.get(name, [None, None])[comp]
            r_u = r_cm.get(name, [None, None])[comp]
            if s_u is None or r_u is None:
                below_s = s_u
                below_r = r_u
                continue
            if below_s is None or below_r is None:
                # the level below has no diaphragm in one of them: no storey drift here
                below_s, below_r = s_u, r_u
                continue
            s_d = (s_u - below_s) / lv["h"]
            r_d = (r_u - below_r) / lv["h"]
            q = Quantity(
                "stories", f"storey drift {name} (centre of mass)", s_d, r_d, "drift", "", case
            )
            out.append(judge(q, reasons))
            below_s, below_r = s_u, r_u

    # member forces at the faces (native: the reference's face stations; mirror: the joints)
    for span in sae.get("members") or []:
        frames = None
        for run in runs_of(ref):
            if span["label"] in (run.get("frames") or {}):
                frames = frames or {}
                for case in _as_list(run.get("cases")):
                    frames[case] = run["frames"][span["label"]]
        if not frames:
            out.append(
                Quantity(
                    "members",
                    f"{span['label']}",
                    None,
                    None,
                    "faceMoment",
                    status="MISSING",
                    reason="no frame output from the reference",
                )
            )
            continue
        rows: list[Quantity] = []
        peak = 0.0
        for case in MEMBER_CASES:
            fr = frames.get(case)
            if fr is None:
                continue
            first = [r for r in _as_list(fr.get("first")) if r.get("case") == case]
            last = [r for r in _as_list(fr.get("last")) if r.get("case") == case]
            if not first or not last:
                continue
            ends = (
                ("i", min(first, key=lambda r: r["sta"]), 0.0),
                ("j", max(last, key=lambda r: r["sta"]), float(fr.get("lastStart") or 0.0)),
            )
            for end, row, offset in ends:
                station = offset + row["sta"]
                s = saengine_at(span, case, station)
                if s is None:
                    continue
                sc = moment_components(span["kind"], s["f"], s["axes"])
                rc = reference_components(
                    span["kind"], row, span.get("angle", 0.0) if mode == "native" else 0.0
                )
                for comp in sc:
                    peak = max(peak, sc[comp])
                    q = Quantity(
                        "members",
                        f"{span['label']} {end} {comp}",
                        sc[comp],
                        rc[comp],
                        "faceMoment",
                        "kN·m",
                        case,
                    )
                    q.detail = {
                        "station_m": round(station, 4),
                        "N_saengine": abs(s["f"][0]),
                        "N_reference": abs(row["P"]),
                    }
                    rows.append(q)
        angle = float(span.get("angle", 0.0) or 0.0)
        skew = (
            mode == "native"
            and span["kind"] == "column"
            and abs(angle / 90 - round(angle / 90)) > 1e-6
        )
        for q in rows:
            judge(q, reasons, floor=0.02 * peak)
            if skew and q.status == "FLAG":
                q.reason = (
                    f"column at {angle:g}°: SAEngine's analysis snaps it to a quarter turn "
                    "(rotation bug, stream A); components in global axes"
                )
            out.append(q)
    return out


def _as_list(v: Any) -> list[dict[str, Any]]:
    if v is None:
        return []
    return list(v) if isinstance(v, list | tuple) else [v]


# ─────────────────────────────── the report ───────────────────────────────


def summary_of(quantities: list[Quantity]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for q in quantities:
        counts[q.status] = counts.get(q.status, 0) + 1
    return counts


def _fmt(v: float | None, unit: str = "") -> str:
    if v is None:
        return "-"
    a = abs(v)
    if a < 1e-9:
        return "0"
    if unit == "" and a < 0.01:
        return f"{v:.3e}"
    return f"{v:.4g}" if a < 1 else f"{v:.2f}" if a < 1000 else f"{v:.1f}"


def report_markdown(
    meta: dict[str, Any], quantities: list[Quantity], notes: dict[str, list[str]]
) -> str:
    counts = summary_of(quantities)
    lines = [
        f"# SAEngine vs a commercial analysis program: {meta.get('project', '')} ({meta.get('mode', '')})",
        "",
        "Local cross-check, never run in CI. The reference program is not named in public material.",
        "",
        f"- Mode: **{meta.get('mode')}** ({'SAEngine’s derived model rebuilt node by node: a solver check' if meta.get('mode') == 'mirror' else 'the physical model drawn the reference’s way: a conventions check'})",
        f"- SAEngine {meta.get('saengineVersion', '')}; run {meta.get('date', '')}; reference run {meta.get('referenceSeconds', 0):.0f} s",
        f"- Members: {', '.join(meta.get('members') or []) or '-'}",
        f"- Result: **{counts.get('PASS', 0)} PASS, {counts.get('FLAG', 0)} FLAG**"
        + (f", {counts.get('MISSING', 0)} missing" if counts.get("MISSING") else ""),
        "",
        (
            "Tolerances: periods 2 %, base reactions 1 %, V and W 2 %, storey shears 2 %, "
            "storey drifts 5 %, face moments 5 % (floor 2 % of the member's largest moment), "
            "effective modal masses 5 % (floor 1 % of the total mass)."
        ),
        "",
    ]
    titles = {
        "modal": "Periods and effective modal masses",
        "reactions": "Base reactions per load case",
        "seismic": "Static seismic weight and base shear",
        "stories": "Storey shears and drifts",
        "members": "Member moments at the support faces"
        if meta.get("mode") == "native"
        else "Member end moments (at the joints)",
    }
    for group, title in titles.items():
        rows = [q for q in quantities if q.group == group]
        if not rows:
            continue
        lines += [
            f"## {title}",
            "",
            "| Quantity | Case | SAEngine | Reference | Diff | Tol | Status | Reason |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for q in rows:
            diff = (
                "-"
                if q.diff_pct is None
                else ("inf" if math.isinf(q.diff_pct) else f"{q.diff_pct:+.1f} %")
            )
            tol = "-" if q.tol_pct is None else f"{q.tol_pct:.0f} %"
            name = q.name + (f" @ {q.detail['station_m']:.3f} m" if "station_m" in q.detail else "")
            unit = f" {q.unit}" if q.unit else ""
            lines.append(
                f"| {name} | {q.case} | {_fmt(q.saengine, q.unit)}{unit} | {_fmt(q.reference, q.unit)}{unit} | {diff} | {tol} | {q.status} | {q.reason} |"
            )
        lines.append("")
    for who, items in notes.items():
        if items:
            lines += [f"## Notes: {who}", ""] + [f"- {n}" for n in items] + [""]
    return "\n".join(lines)


def write_outputs(
    out_dir: Path, meta: dict[str, Any], quantities: list[Quantity], notes: dict[str, list[str]]
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "saengine.referenceComparison/1",
        "meta": meta,
        "tolerances": TOLERANCES,
        "summary": summary_of(quantities),
        "quantities": [asdict(q) for q in quantities],
        "notes": notes,
    }
    (out_dir / "results.json").write_text(
        json.dumps(doc, indent=1, default=_json_default), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(report_markdown(meta, quantities, notes), encoding="utf-8")
    return doc


def _json_default(v: Any) -> Any:
    if isinstance(v, float) and math.isinf(v):
        return None
    return str(v)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare SAEngine with the reference program's run.")
    ap.add_argument("--saengine", required=True, type=Path)
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--input", type=Path, help="the model input the reference was built from")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--project", default="")
    ap.add_argument("--date", default="")
    args = ap.parse_args(argv)
    sae = load_json(args.saengine)
    ref = load_json(args.reference)
    mode = ref.get("mode") or "native"
    inp = load_json(args.input) if args.input and args.input.exists() else {}
    quantities = compare(sae, ref, mode)
    meta = {
        "project": args.project,
        "mode": mode,
        "date": args.date,
        "saengineVersion": sae.get("version", ""),
        "referenceSeconds": ref.get("seconds", 0) or 0,
        "members": sae.get("members_requested") or [],
        "referenceError": ref.get("error"),
    }
    notes = {
        "SAEngine": list(sae.get("notes") or []) + list(sae.get("memberNotes") or []),
        "model sent to the reference": list(inp.get("notes") or []),
        "reference run": [str(x) for x in _as_list(ref.get("log"))],
    }
    doc = write_outputs(args.out, meta, quantities, notes)
    print(json.dumps(doc["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
