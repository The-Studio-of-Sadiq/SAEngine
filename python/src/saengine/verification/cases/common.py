"""What the verification cases share: the result record, quantities and running the analysis.

A case builds its model through SAEngine's own pipeline wherever one exists (structural model ->
building model -> :func:`saengine.fem.derive.derive_fem` -> OpenSees Studio's runner -> SAEngine's
result readers), or calls the design functions directly, and compares what comes out with an
independent reference written out in the case.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.fem.derive import Derivation, derive_fem
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel, generate_from_structure, source_stamp
from saengine.library.settings import ProjectSettings, default_project_settings
from saengine.library.structure import StructuralModel, default_structural_model

G = 9.80665  # m/s²
MATERIALS = default_material_library()
BY_ID = {m.id: m for m in MATERIALS.materials}


@dataclass
class Quantity:
    """One compared value: SAEngine's against the reference, within a relative tolerance."""

    name: str
    unit: str
    reference: float
    saengine: float
    tolerance: float  # relative, e.g. 0.01 for 1 %

    @property
    def ratio(self) -> float:
        if self.reference == 0:
            return 1.0 if self.saengine == 0 else math.inf
        return self.saengine / self.reference

    @property
    def passed(self) -> bool:
        ratio = self.ratio
        return bool(math.isfinite(ratio) and abs(ratio - 1) <= self.tolerance + 1e-12)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "reference": float(self.reference),
            "saengine": float(self.saengine),
            "ratio": float(self.ratio),
            "tolerance": float(self.tolerance),
            "pass": self.passed,
        }


@dataclass
class Reference:
    """The independent reference of a case: where it comes from and how it is derived."""

    source: str
    formula: str
    steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "formula": self.formula, "steps": self.steps}


@dataclass
class Outcome:
    """What a case function returns: the reference and the compared quantities."""

    reference: Reference
    quantities: list[Quantity]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Case:
    """A benchmark problem of the verification pack."""

    id: str
    title: str
    category: str  # "analysis" or "design"
    description: str
    model: str  # the model sketched in words
    run: Callable[[Path], Outcome]
    #: Seconds it takes, roughly: the fast ones run in the test suite.
    fast: bool = True


def structure(**parts: list[dict[str, Any]]) -> StructuralModel:
    """A structural model (Part 5, special structures) with these members, areas, blocks and
    supports."""
    return StructuralModel.model_validate(
        {**default_structural_model().model_dump(mode="json", by_alias=True), **parts}
    )


def point(x: float, y: float, z: float) -> dict[str, float]:
    return {"x": x, "y": y, "z": z}


def building(model: StructuralModel) -> BuildingModel:
    return generate_from_structure(model, source_stamp(model.model_dump_json()))


def objects(*items: dict[str, Any]) -> ObjectLibrary:
    return ObjectLibrary.model_validate({"objects": list(items)})


def settings(**analysis: Any) -> ProjectSettings:
    """Default settings on gross sections (the references are closed-form elastic solutions
    with the members' full E·I); ``analysis`` overrides, ``stiffness="aci"`` among them."""
    s = default_project_settings("Verification")
    analysis = {"stiffness": "gross", **analysis}
    return s.model_copy(update={"analysis": s.analysis.model_copy(update=analysis)})


def nodes_at(project: dict[str, Any], test: Callable[[list[float]], bool]) -> list[int]:
    return [n["id"] for n in project["nodes"] if test(n["coords"])]


def node_at(project: dict[str, Any], xyz: tuple[float, float, float], tol: float = 1e-6) -> int:
    """The id of the node at ``xyz`` [m]."""
    found = nodes_at(project, lambda c: all(abs(a - b) < tol for a, b in zip(c, xyz, strict=True)))
    if not found:
        raise LookupError(f"no node at {xyz}")
    return found[0]


def only_pattern(
    project: dict[str, Any],
    nodal: list[dict[str, Any]] | None = None,
    element: list[dict[str, Any]] | None = None,
    keep_dead: bool = False,
) -> None:
    """Replace the loads of the first load case (D) by ``nodal`` and ``element`` loads, or keep
    its self-weight and add them (``keep_dead``)."""
    pattern = project["load_patterns"][0]
    if not keep_dead:
        pattern["nodal_loads"], pattern["element_loads"] = [], []
    pattern["nodal_loads"] += nodal or []
    pattern["element_loads"] += element or []


#: Gmsh (the mesher behind derive_fem) keeps global state: one derivation at a time when the
#: cases run in threads.
_DERIVE = threading.Lock()


def derive(*args: Any, **kwargs: Any) -> Derivation:
    """:func:`saengine.fem.derive.derive_fem`, one call at a time."""
    with _DERIVE:
        return derive_fem(*args, **kwargs)


def run_model(project: dict[str, Any], folder: Path, cases: list[int], name: str = "model"):
    """Run ``cases`` of the OpenSees Studio ``project`` with its runner (as the workbench does)
    and return ``(model path, results folder, {case id: results})``."""
    from opensees_studio.services.result_store import load_manifest, load_results

    folder.mkdir(parents=True, exist_ok=True)
    model = folder / f"{name}.osmodel"
    model.write_text(json.dumps(project), encoding="utf-8")
    out = folder / f"{name}.results"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, cases),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if done.returncode != 0:
        raise RuntimeError(f"the analysis failed: {done.stderr[-1500:]}")
    results = {e["case_id"]: load_results(e, str(out)) for e in load_manifest(str(out))["cases"]}
    return model, out, results


def fmt(value: float, digits: int = 4) -> str:
    """A number with ``digits`` significant figures, for the derivation steps."""
    if value == 0 or not math.isfinite(value):
        return "0" if value == 0 else str(value)
    exponent = math.floor(math.log10(abs(value)))
    if -3 <= exponent < 6:
        text = f"{value:.{max(0, digits - 1 - exponent)}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text
    mantissa = f"{value / 10**exponent:.{digits - 1}f}".rstrip("0").rstrip(".")
    superscript = str(exponent).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
    return f"{mantissa} × 10{superscript}"
