"""Smoke test of an installed SAEngine Python backend.

Run with the bundled interpreter, outside the repository:
    <install>\\resources\\python\\python.exe -I smoke_model.py --work <empty temp folder>

It imports every backend module, derives the one-bay model of python/tests/test_fem_derive.py
(four columns, four beams, one slab), writes it into a project folder, asks
`python -m saengine.rpc` for saengine/info and project/validate over stdio JSON-RPC (as the
workbench's solver service does), runs every case through
`python -m opensees_studio.run` exactly as the workbench does, and checks that the
1.2D + 1.6L + 0.5Lr base reaction balances the applied gravity load. Exit code 0 on success.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HEADLESS_MODULES = [
    "saengine.rpc.server",
    "saengine.design.rc",
    "saengine.report.build",
    "opensees_studio.run",
    "openseespy.opensees",
    "gmsh",
    "ifcopenshell",
    "ezdxf",
    "rhino3dm",
    "shapely",
    "sectionproperties",
    "concreteproperties",
    "typst",
    "docx",
    "saengine.report.word",
    "pygls",
    "wntr",
    "saengine.plumbing.hydraulics",
    "saengine.plumbing.project",
    "fluids",
    "saengine.hvac.report",
    "saengine.hvac.air",
    "saengine.electrical.report",
]
GUI_MODULES = ["PySide6", "pyvista", "vtk"]


def check_imports() -> None:
    for name in HEADLESS_MODULES:
        start = time.perf_counter()
        importlib.import_module(name)
        print(f"import {name}: ok ({time.perf_counter() - start:.2f} s)")
    for name in GUI_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            continue
        raise SystemExit(f"{name} is installed: the bundle must stay headless")
    print(f"python {sys.version.split()[0]} at {sys.executable}")


SHADOW = 'raise ImportError("shadow numpy from {where} was imported instead of the bundle")\n'
ISOLATION_PROBE = """\
import sys
import numpy, saengine.rpc.server, opensees_studio.run
prefix = sys.prefix.lower()
foreign = [p for p in sys.path if p and not p.lower().startswith(prefix)]
assert not foreign, f"sys.path entries outside the bundle: {foreign}"
print("isolated: sys.path =", len(sys.path), "entries inside", sys.prefix)
"""


def check_isolation(scratch: Path) -> None:
    """The bundle must ignore the user's Python settings, the way the workbench starts it.

    The workbench runs python.exe without -I and passes its environment on. Start it the same
    way with a hostile environment: PYTHONHOME pointing nowhere, PYTHONPATH and a per-user
    site-packages (APPDATA, PYTHONUSERBASE) holding a numpy that fails to import.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for where in ("PYTHONPATH", "USER site-packages"):
        folder = scratch / where.split()[0].lower()
        package = (
            folder
            / "Python"
            / f"Python{sys.version_info[0]}{sys.version_info[1]}"
            / "site-packages"
            / "numpy"
            if where.startswith("USER")
            else folder / "numpy"
        )
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text(SHADOW.format(where=where), encoding="utf-8")
    env["PYTHONPATH"] = str(scratch / "pythonpath")
    env["PYTHONHOME"] = str(scratch / "no-such-home")
    env["APPDATA"] = str(scratch / "user")
    env["PYTHONUSERBASE"] = str(scratch / "user" / "Python")
    env.pop("PYTHONNOUSERSITE", None)
    result = subprocess.run(
        [sys.executable, "-B", "-c", ISOLATION_PROBE],
        check=False,
        env=env,
        cwd=scratch,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise SystemExit(
            "the bundled Python is not isolated from the user's environment:\n"
            + result.stdout
            + result.stderr
        )
    print(result.stdout.strip())


class RpcClient:
    """The workbench's view of the backend: `python -u -m saengine.rpc` over stdio JSON-RPC."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "saengine.rpc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.next_id = 1

    def request(self, method: str, params: dict) -> dict:
        assert self.process.stdin and self.process.stdout
        body = json.dumps(
            {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        ).encode("utf-8")
        self.next_id += 1
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self.process.stdin.flush()
        length = 0
        while True:
            line = self.process.stdout.readline()
            if not line:
                stderr = (
                    self.process.stderr.read().decode("utf-8", "replace")
                    if self.process.stderr
                    else ""
                )
                raise SystemExit(f"saengine.rpc closed its output: {stderr[-2000:]}")
            if line in (b"\r\n", b"\n"):
                break
            name, _, value = line.decode("ascii").partition(":")
            if name.strip().lower() == "content-length":
                length = int(value)
        reply = json.loads(self.process.stdout.read(length))
        if "error" in reply:
            raise SystemExit(f"{method} failed: {reply['error']}")
        return reply["result"]

    def close(self) -> None:
        self.process.kill()
        self.process.wait()


def one_bay():
    from saengine.fem.derive import derive_fem
    from saengine.library import (
        FloorPlan,
        ObjectLibrary,
        default_floor_plan,
        default_material_library,
    )
    from saengine.library.bim import generate
    from saengine.library.settings import default_project_settings

    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "COL",
                    "name": "Column 400x400",
                    "kind": "column",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                },
                {
                    "id": "BM",
                    "name": "Beam 300x500",
                    "kind": "beam",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                },
                {
                    "id": "SL",
                    "name": "Slab 150",
                    "kind": "slab",
                    "material": "C24.1",
                    "thickness": 150,
                },
            ]
        }
    )
    corners = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
    plan = FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "columns": [
                {
                    "id": f"C{i + 1}",
                    "type": "COL",
                    "at": {"x": x, "y": y},
                    "base": "BASE",
                    "top": "L1",
                }
                for i, (x, y) in enumerate(corners)
            ],
            "beams": [
                {
                    "id": f"B{i + 1}",
                    "type": "BM",
                    "story": "L1",
                    "start": {"x": a[0], "y": a[1]},
                    "end": {"x": b[0], "y": b[1]},
                }
                for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1], strict=True))
            ],
            "slabs": [
                {
                    "id": "S1",
                    "type": "SL",
                    "story": "L1",
                    "boundary": [{"x": x, "y": y} for x, y in corners],
                }
            ],
        }
    )
    settings = default_project_settings("Bay")
    derivation = derive_fem(
        generate(plan, "s"), objects, default_material_library(), settings, {"bim": "smoke"}
    )
    return derivation, settings


def gravity(project: dict, name: str) -> float:
    """Vertical applied load of a pattern (nodal loads plus uniform beam loads). A uniform load
    acts on an element's flexible length, between its rigid end zones (``joint_offsets``); the
    derivation puts the share over the end zones on the joints as nodal loads."""
    import numpy as np

    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    elements = {e["id"]: e for e in project["elements"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    total = sum(n["forces"][2] for n in pattern["nodal_loads"])
    for load in pattern["element_loads"]:
        element = elements[load["element_id"]]
        offsets = np.array(element.get("joint_offsets") or [0.0] * 6, dtype=float)
        a, b = (coords[n] for n in element["nodes"])
        a, b = a + offsets[:3], b + offsets[3:]
        x = (b - a) / np.linalg.norm(b - a)
        vecxz = np.array([1.0, 0, 0]) if abs(x[2]) > abs(x[0]) else np.array([0, 0, 1.0])
        y = np.cross(vecxz, x)
        y /= np.linalg.norm(y)
        w = load["wx"] * x + load["wy"] * y + load["wz"] * np.cross(x, y)
        total += float(w[2] * np.linalg.norm(b - a))
    return float(total)


def run_analysis(work: Path) -> None:
    from saengine.fem.combinations import combination_results

    derivation, settings = one_bay()
    project = derivation.project
    model = work / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps(project), encoding="utf-8")
    out = model.with_suffix(".results")
    cases = [str(c["id"]) for c in project["analyses"]]

    rpc = RpcClient()
    try:
        start = time.perf_counter()
        info = rpc.request("saengine/info", {})
        print(f"saengine.rpc saengine/info: {info} ({time.perf_counter() - start:.2f} s)")
        validation = rpc.request("project/validate", {"path": str(model)})
        if not validation["ok"]:
            raise SystemExit(f"project/validate rejected the model: {validation['errors']}")
        print(f"saengine.rpc project/validate: ok, {len(validation['summary']['analyses'])} cases")
    finally:
        rpc.close()

    start = time.perf_counter()
    run = subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *cases,
            "--out",
            str(out),
        ],
        cwd=model.parent,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    elapsed = time.perf_counter() - start
    if run.returncode != 0:
        print(run.stdout[-3000:])
        print(run.stderr[-3000:])
        raise SystemExit(f"opensees_studio.run exited with {run.returncode}")
    print(f"opensees_studio.run: {len(cases)} cases in {elapsed:.1f} s")

    entries = {e["caseName"]: e for e in combination_results(out, project, settings)}
    reaction = entries["1.2D + 1.6L + 0.5Lr"]["tables"][0]["rows"][-1][3]
    expected = -1.2 * (gravity(project, "D") + gravity(project, "SD")) - 0.5 * gravity(
        project, "Lr"
    )
    error = abs(reaction - expected) / abs(expected)
    print(
        f"base reaction 1.2D + 1.6L + 0.5Lr: {reaction / 1e3:.2f} kN "
        f"(applied {expected / 1e3:.2f} kN, error {error:.1e})"
    )
    if error > 1e-4:
        raise SystemExit("the base reaction does not balance the applied load")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, help="empty folder for the test project")
    parser.add_argument("--imports-only", action="store_true", help="skip the analysis run")
    parser.add_argument(
        "--scratch", type=Path, help="folder for the isolation check (default: a temp folder)"
    )
    args = parser.parse_args()
    check_imports()
    if args.scratch is not None:
        check_isolation(args.scratch)
    else:
        with tempfile.TemporaryDirectory(prefix="saengine-isolation-") as scratch:
            check_isolation(Path(scratch))
    if args.imports_only:
        return 0
    if args.work is None:
        parser.error("--work is required unless --imports-only is given")
    args.work.mkdir(parents=True, exist_ok=True)
    run_analysis(args.work)
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
