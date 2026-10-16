"""Run the verification pack: every benchmark, a summary table, ``verification.json`` and, on
request, the Verification Manual PDF.

Command line::

    python -m saengine.verification [--out DIR] [--pdf] [--cases A1 D5 ...] [--fast] [--jobs N]

The cases run in parallel threads; each analysis case runs OpenSees in a process of its own.
The exit code is 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import saengine
from saengine.verification.cases import BY_ID, CASES

TEMPLATE = Path(__file__).parent / "templates" / "verification.typ"


def run_case(case_id: str, work: str | Path) -> dict[str, Any]:
    """Run one case in ``work`` (its model files go to ``work/<id>``) and return its record:
    ``{id, title, category, description, model, reference, quantities, notes, pass, error,
    seconds}``."""
    case = BY_ID[case_id]
    folder = Path(work) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "id": case.id,
        "title": case.title,
        "category": case.category,
        "description": case.description,
        "model": case.model,
        "reference": None,
        "quantities": [],
        "notes": [],
        "error": None,
    }
    start = time.perf_counter()
    try:
        outcome = case.run(folder)
    except Exception as error:  # noqa: BLE001 - a failing case is reported, not raised
        record["error"] = f"{type(error).__name__}: {error}"
        record["traceback"] = traceback.format_exc()
    else:
        record["reference"] = outcome.reference.as_dict()
        record["quantities"] = [q.as_dict() for q in outcome.quantities]
        record["notes"] = outcome.notes
    record["seconds"] = round(time.perf_counter() - start, 2)
    record["pass"] = record["error"] is None and all(q["pass"] for q in record["quantities"])
    return record


def run_all(
    work: str | Path,
    ids: list[str] | None = None,
    *,
    fast_only: bool = False,
    jobs: int | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Run the cases ``ids`` (all by default; only the fast ones with ``fast_only``) and return
    the pack's data: ``{meta, cases, summary}``."""
    chosen = [c for c in CASES if (ids is None or c.id in ids) and (c.fast or not fast_only)]
    unknown = sorted(set(ids or []) - set(BY_ID))
    if unknown:
        raise ValueError(f"unknown case ids: {', '.join(unknown)}")
    # Threads suffice: the analyses run in OpenSees processes of their own, and the model
    # derivations (gmsh) take turns (see cases.common.derive).
    workers = max(1, min(jobs or os.cpu_count() or 1, len(chosen)))
    if workers == 1:
        records = [run_case(c.id, work) for c in chosen]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            records = list(pool.map(run_case, [c.id for c in chosen], [str(work)] * len(chosen)))
    passed = sum(r["pass"] for r in records)
    return {
        "meta": meta(today),
        "cases": records,
        "summary": {"cases": len(records), "passed": passed, "failed": len(records) - passed},
    }


def meta(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    from importlib.metadata import PackageNotFoundError, version

    versions = {"SAEngine": saengine.__version__}
    for label, dist in (
        ("OpenSees Studio", "opensees-studio"),
        ("OpenSeesPy", "openseespy"),
        ("concreteproperties", "concreteproperties"),
    ):
        try:
            versions[label] = version(dist)
        except PackageNotFoundError:
            versions[label] = "not installed"
    return {
        "title": "Verification Manual",
        "version": saengine.__version__,
        "date": f"{today.day} {today:%B %Y}",
        "isoDate": today.isoformat(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()}), "
        f"Python {platform.python_version()}",
        "versions": [[k, v] for k, v in versions.items()],
    }


# ─────────────────────────────────────── output ───────────────────────────────────────


def _number(value: float) -> str:
    if value is None or not math.isfinite(value):
        return "–"
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1e6 or magnitude < 1e-3:
        return f"{value:.4e}"
    # Five significant figures, in fixed notation.
    return f"{value:.{max(0, 4 - math.floor(math.log10(magnitude)))}f}"


def _clean(value: Any) -> Any:
    """JSON-safe: infinities and NaN as None."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k != "traceback"}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def write_json(data: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(data), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def manual_data(data: dict[str, Any]) -> dict[str, Any]:
    """The pack's data with every value as display text, for the Typst template."""
    cases = []
    for record in data["cases"]:
        quantities = [
            {
                "name": q["name"],
                "unit": q["unit"],
                "reference": _number(q["reference"]),
                "saengine": _number(q["saengine"]),
                "ratio": "–" if not math.isfinite(q["ratio"]) else f"{q['ratio']:.4f}",
                "tolerance": f"± {q['tolerance'] * 100:g} %",
                "pass": bool(q["pass"]),
            }
            for q in record["quantities"]
        ]
        ratios = [q["ratio"] for q in record["quantities"] if math.isfinite(q["ratio"])]
        worst = max(ratios, key=lambda r: abs(r - 1), default=None)
        cases.append(
            {
                "id": record["id"],
                "title": record["title"],
                "category": record["category"],
                "description": record["description"],
                "model": record["model"],
                "reference": record["reference"] or {"source": "–", "formula": "–", "steps": []},
                "quantities": quantities,
                "notes": record["notes"],
                "error": record["error"] or "",
                "pass": bool(record["pass"]),
                "worst": "–" if worst is None else f"{worst:.4f}",
                "seconds": f"{record['seconds']:.1f}",
            }
        )
    summary = data["summary"]
    return {
        "meta": data["meta"],
        "summary": {k: str(v) for k, v in summary.items()},
        "cases": cases,
    }


def render_pdf(data: dict[str, Any]) -> tuple[bytes, list[str]]:
    """The Verification Manual PDF of the pack's ``data`` and Typst's warnings."""
    import typst

    inputs = {"data": json.dumps(manual_data(data), ensure_ascii=False, allow_nan=False)}
    result = typst.compile_with_warnings(str(TEMPLATE), format="pdf", sys_inputs=inputs)
    pdf, warnings = result if isinstance(result, tuple) else (result, [])
    return pdf, [f"Typst: {getattr(w, 'message', w)}" for w in warnings or []]


def summary_table(data: dict[str, Any]) -> str:
    """A plain-text table of every compared quantity."""
    lines = [
        (
            f"{'Case':<5} {'Quantity':<44} {'Reference':>12} {'SAEngine':>12} {'Ratio':>7} "
            f"{'Tol.':>6}  Result"
        ),
        "-" * 100,
    ]
    for record in data["cases"]:
        if record["error"]:
            lines.append(f"{record['id']:<5} {record['title'][:44]:<44} ERROR {record['error']}")
            continue
        for q in record["quantities"]:
            name = f"{q['name']} [{q['unit']}]"
            ratio = f"{q['ratio']:.4f}" if math.isfinite(q["ratio"]) else "-"
            lines.append(
                f"{record['id']:<5} {name[:44]:<44} {_number(q['reference']):>12} "
                f"{_number(q['saengine']):>12} {ratio:>7} {q['tolerance'] * 100:>5g}%  "
                f"{'pass' if q['pass'] else 'FAIL'}"
            )
    s = data["summary"]
    lines += ["-" * 100, f"{s['passed']} of {s['cases']} cases pass, {s['failed']} fail"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m saengine.verification",
        description="Run SAEngine's verification pack against closed-form and published "
        "references.",
    )
    parser.add_argument(
        "--out", default="verification", help="output folder (default: %(default)s)"
    )
    parser.add_argument("--pdf", action="store_true", help="also write the Verification Manual PDF")
    parser.add_argument("--cases", nargs="+", metavar="ID", help="run only these cases")
    parser.add_argument("--fast", action="store_true", help="skip the slow cases")
    parser.add_argument("--jobs", type=int, default=None, help="parallel processes")
    parser.add_argument(
        "--keep", action="store_true", help="keep the case models and results in OUT/work"
    )
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.keep:
        work = out / "work"
        data = run_all(work, args.cases, fast_only=args.fast, jobs=args.jobs)
    else:
        with tempfile.TemporaryDirectory(prefix="saengine-verification-") as work:
            data = run_all(work, args.cases, fast_only=args.fast, jobs=args.jobs)
    text = summary_table(data)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    print(f"wrote {write_json(data, out / 'verification.json')}")
    if args.pdf:
        pdf, warnings = render_pdf(data)
        path = out / "verification-manual.pdf"
        path.write_bytes(pdf)
        for warning in warnings:
            print(warning, file=sys.stderr)
        print(f"wrote {path}")
    return 0 if data["summary"]["failed"] == 0 else 1
