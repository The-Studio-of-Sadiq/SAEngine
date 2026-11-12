"""Python scripts that build the structural model of a special structure (Part 5).

A script is an ordinary Python file in ``05 Structural Model/scripts/``. When the engineer runs
it from the 3D modeller, it gets the model as ``model`` and adds to it::

    model.clear()  # start again on every run (keeps the grids)
    for i in range(6):
        model.member((i * 6000, 0, 0), (i * 6000, 0, 8000), type="COL")
        model.support((i * 6000, 0, 0), "fixed")
    model.add(BarrelVault(span=30000, rise=7500, length=30000, segments=12, bays=5,
                          memberType="CHS", origin=(0, 0, 8000)))

The shapes of :mod:`saengine.library.shapes` (``SpaceTruss``, ``PlaneTruss``, ``Arch``,
``Dome``, ``BarrelVault``, ``CableNet``, ``PortalFrame``), ``math`` and ``numpy`` (as ``np``) are at hand
without imports. What the script adds goes in as one edit, through
:func:`saengine.library.shapes.insert`, so it can be undone in one step.

Scripts run in their own Python process (:func:`run_script`), so a script that hangs or crashes
cannot take the workbench's backend with it; what they print is shown to the engineer.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from saengine.library import shapes
from saengine.library.shapes import Geometry, insert, shape_geometry
from saengine.library.structure import Point, StructuralModel

#: Seconds a script may run before it is stopped.
TIMEOUT = 300

TEMPLATE = '''"""Builds part of the structural model. Run it from the 3D modeller (Script).

`model` is the structural model. Lengths are in mm, angles in degrees, Z is up. The shapes
SpaceTruss, PlaneTruss, Arch, Dome, BarrelVault, CableNet and PortalFrame, `math` and `np` (numpy) are
available without imports.
"""

model.clear()  # start again on every run (grids are kept)

span = 30000
for x in (0, span):
    for y in range(0, 30001, 6000):
        model.member((x, y, 0), (x, y, 8000), type="{column}")
        model.support((x, y, 0), "fixed")

model.add(BarrelVault(
    span=span, rise=7500, length=30000, segments=12, bays=5,
    memberType="{member}", origin=(0, 0, 8000), supports="none",
))
'''


class ModelBuilder:
    """The ``model`` a script sees: the model as it was, and what the script adds."""

    def __init__(self, model: StructuralModel) -> None:
        self.current = model
        self.geometry = Geometry()
        self.cleared = False

    def clear(self) -> None:
        """Remove every member, area and support (the grids stay), so a script can rebuild its
        part of the model from scratch on every run."""
        self.cleared = True

    def member(self, start: Any, end: Any, type: str) -> None:
        """A member of object type ``type`` between two points ``(x, y, z)`` [mm]."""
        self.geometry.line(
            Point.model_validate(start).array(), Point.model_validate(end).array(), type
        )

    def area(self, outline: list[Any], type: str) -> None:
        """A flat area of object type ``type`` with these corners ``(x, y, z)`` [mm]."""
        self.geometry.panel([Point.model_validate(p).array() for p in outline], type)

    def support(self, at: Any, fixity: str = "fixed") -> None:
        """A ``"fixed"`` or ``"pinned"`` support at ``(x, y, z)`` [mm]."""
        if fixity not in ("fixed", "pinned"):
            raise ValueError(f"a support is fixed or pinned, not {fixity!r}")
        self.geometry.support(Point.model_validate(at).array(), fixity)  # type: ignore[arg-type]

    def add(self, shape: Any) -> None:
        """A parametric shape (``Dome(...)``, ``SpaceTruss(...)``...)."""
        self.geometry.extend(shape_geometry(shape))

    def result(self) -> tuple[StructuralModel, list[str], int]:
        base = self.current
        if self.cleared:
            base = base.model_copy(update={"members": [], "areas": [], "supports": []})
        return insert(base, self.geometry)


def namespace(builder: ModelBuilder) -> dict[str, Any]:
    names: dict[str, Any] = {"__name__": "__main__", "model": builder, "math": math, "np": np}
    names.update({cls.__name__: cls for cls in shapes.SHAPES})
    return names


def _main(argv: list[str]) -> int:
    """``python -m saengine.library.script <script> <result.json>``, model JSON on stdin."""
    script, result_path = Path(argv[0]), Path(argv[1])
    builder = ModelBuilder(StructuralModel.model_validate_json(sys.stdin.read()))
    try:
        code = compile(script.read_text(encoding="utf-8"), str(script), "exec")
        exec(code, namespace(builder))  # noqa: S102 - running the engineer's own script is the point
        model, ids, skipped = builder.result()
    except Exception as exc:  # noqa: BLE001 - every failure is reported to the engineer
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == str(script)]
        where = f" (line {frames[-1].lineno})" if frames else ""
        message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        result: dict[str, Any] = {"error": f"{type(exc).__name__}{where}: {message}"}
        traceback.print_exc()
    else:
        data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
        result = {
            "text": json.dumps(data, indent="\t", ensure_ascii=False) + "\n",
            "ids": ids,
            "skipped": skipped,
            "cleared": builder.cleared,
        }
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return 0


def run_script(structure_text: str, script_path: str) -> dict[str, Any]:
    """Runs the script at ``script_path`` on the structural model ``structure_text``.

    Returns ``{"text", "ids", "skipped", "cleared", "output"}``, or ``{"error", "output"}``.
    """
    StructuralModel.model_validate_json(structure_text)  # the model must be valid to start
    with tempfile.TemporaryDirectory() as folder:
        result_path = Path(folder) / "result.json"
        try:
            run = subprocess.run(
                [sys.executable, "-m", "saengine.library.script", script_path, str(result_path)],
                check=False,
                input=structure_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=TIMEOUT,
                cwd=str(Path(script_path).parent),
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout if isinstance(exc.stdout, str) else ""
            return {
                "error": f"The script ran longer than {TIMEOUT} s and was stopped.",
                "output": output,
            }
        output = (run.stdout + run.stderr).strip()
        if not result_path.exists():
            return {
                "error": f"The script's Python process ended early (exit code {run.returncode}).",
                "output": output,
            }
        result = json.loads(result_path.read_text(encoding="utf-8"))
    result["output"] = output
    return result


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
