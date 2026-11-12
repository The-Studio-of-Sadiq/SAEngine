"""Run the cross-check: SAEngine's derived analysis models against PyNite and CalculiX.

    python scripts/crosscheck/run.py --work <dir> --pynite-python <venv>\\Scripts\\python.exe
        --ccx <ccx.exe> [--models cantilever portal ...] [--skip-build]

Run it with SAEngine's Python (the repository's ``.venv``, with ``python/src`` and
``third_party/opensees-studio/src`` on PYTHONPATH). For every model of the corpus
(``corpus.py``) it

1. builds and analyses the model with SAEngine (Run All's derivation and analysis),
2. writes the solver-neutral description of the derived model (``ir.py``),
3. reads SAEngine's results at its probes (``saengine_side.py``),
4. rebuilds and analyses it in PyNite (``run_pynite.py``, in PyNite's own environment, ``-I``)
   and in CalculiX (``run_ccx.py``, ``ccx`` as a separate program),
5. compares them (``compare.py``) and writes ``<work>/<model>/report.md``,

and writes ``<work>/report.md`` with every model's table. The models run one at a time (the
buildings take minutes each). Local only: it never runs in CI (PyNite and CalculiX are not
installed there; ``tests/`` checks the translation without them). Setup:
``docs/verification/cross-check.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import compare  # the harness's own modules
import corpus

TITLES = {
    "cantilever": "Cantilever (4 m, 300 x 500, self-weight + tip loads)",
    "portal": "Portal frame (h 3.2 m, span 6 m)",
    "offsets": "Fixed-ended beam with rigid end zones (factor 0.5, 10 kN/m)",
    "plate": "Simply supported square plate (2 m, 20 mm steel, 100 mm mesh)",
    "sample": "Sample Frame (the bundled sample)",
    "frame6": "Generated frame, 3 x 2 bays, 6 storeys (beams and slabs)",
    "flatslab10": "Generated flat slab, 3 x 2 bays, 10 storeys",
    "core10": "Generated frame with core walls, 3 x 2 bays, 10 storeys",
}


def _run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    done = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if done.returncode != 0:
        raise SystemExit(
            f"{' '.join(cmd[:3])} failed:\n{done.stdout[-2000:]}\n{done.stderr[-3000:]}"
        )
    print("  " + (done.stdout.strip().splitlines() or [""])[-1])


def check_one(name: str, work: Path, pynite: Path, ccx: Path, build: bool) -> dict:
    folder = work / name
    model = folder / "08 FEM" / "model.osmodel"
    if build or not model.exists():
        corpus.build(name, work)
    py = sys.executable
    _run([py, str(HERE / "ir.py"), "--model", str(model), "--out", str(folder / "ir.json")])
    _run(
        [
            py,
            str(HERE / "saengine_side.py"),
            "--model",
            str(model),
            "--ir",
            str(folder / "ir.json"),
            "--out",
            str(folder / "saengine.json"),
        ]
    )
    # PyNite in its own environment, isolated (-I: no user site, no script-folder imports)
    clean = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    _run(
        [
            str(pynite),
            "-I",
            str(HERE / "run_pynite.py"),
            "--ir",
            str(folder / "ir.json"),
            "--out",
            str(folder / "pynite.json"),
        ],
        env=clean,
    )
    _run(
        [
            py,
            "-I",
            str(HERE / "run_ccx.py"),
            "--ir",
            str(folder / "ir.json"),
            "--ccx",
            str(ccx),
            "--work",
            str(folder / "ccx"),
            "--out",
            str(folder / "ccx.json"),
        ]
    )
    doc = compare.compare_dir(folder, TITLES.get(name, name))
    print(f"  report: {folder / 'report.md'}")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--pynite-python", type=Path, required=True)
    ap.add_argument("--ccx", type=Path, required=True)
    ap.add_argument("--models", nargs="*", default=list(corpus.MODELS))
    ap.add_argument("--skip-build", action="store_true", help="reuse analysed models in --work")
    args = ap.parse_args(argv)
    if any(os.environ.get(k) for k in ("CI", "GITHUB_ACTIONS", "TF_BUILD")):
        raise SystemExit("the cross-check runs locally only")
    args.work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    parts = [f"# SAEngine cross-check against PyNite and CalculiX ({date.today().isoformat()})", ""]
    for name in args.models:
        print(f"{name}:")
        check_one(name, args.work, args.pynite_python, args.ccx.resolve(), not args.skip_build)
        parts.append((args.work / name / "report.md").read_text(encoding="utf-8"))
    (args.work / "report.md").write_text("\n".join(parts), encoding="utf-8")
    print(f"done in {time.perf_counter() - started:.0f} s: {args.work / 'report.md'}")
    print(json.dumps({"models": args.models}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
