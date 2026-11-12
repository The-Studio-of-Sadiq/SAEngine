"""Reading the MEP models of the building services (IFC files from the consultants).

:func:`inspect_ifc` opens an IFC file with IfcOpenShell and says what is in it: its distribution
elements (ducts, pipes, cable trays, terminals, equipment) counted by class, their systems, the
storeys, and the discipline it most likely belongs to, from the classes of its elements (and the
names of its systems for fire protection, whose pipes are pipes like any other).
"""

from __future__ import annotations

import filecmp
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.system

#: The IFC classes (IFC4 names; IFC2X3 files are read through their element types) that tell
#: the discipline of an MEP model.
DISCIPLINE_CLASSES: dict[str, tuple[str, ...]] = {
    "mechanical": (
        "IfcDuctSegment",
        "IfcDuctFitting",
        "IfcDuctSilencer",
        "IfcAirTerminal",
        "IfcAirTerminalBox",
        "IfcDamper",
        "IfcFan",
        "IfcUnitaryEquipment",
        "IfcChiller",
        "IfcCoil",
        "IfcBoiler",
        "IfcCoolingTower",
        "IfcHeatExchanger",
        "IfcAirToAirHeatRecovery",
        "IfcEvaporator",
        "IfcCondenser",
        "IfcCompressor",
        "IfcHumidifier",
    ),
    "plumbing": (
        "IfcPipeSegment",
        "IfcPipeFitting",
        "IfcSanitaryTerminal",
        "IfcWasteTerminal",
        "IfcStackTerminal",
        "IfcInterceptor",
        "IfcTank",
        "IfcPump",
        "IfcValve",
    ),
    "fire": ("IfcFireSuppressionTerminal", "IfcAlarm"),
    "electrical": (
        "IfcCableCarrierSegment",
        "IfcCableCarrierFitting",
        "IfcCableSegment",
        "IfcCableFitting",
        "IfcLightFixture",
        "IfcLamp",
        "IfcElectricDistributionBoard",
        "IfcOutlet",
        "IfcSwitchingDevice",
        "IfcElectricAppliance",
        "IfcJunctionBox",
        "IfcTransformer",
        "IfcElectricGenerator",
        "IfcElectricMotor",
        "IfcProtectiveDevice",
    ),
}
_FIRE_WORDS = ("fire", "sprinkler", "hydrant", "deluge", "standpipe")


def mep_elements(model: ifcopenshell.file) -> list[Any]:
    """The distribution elements of an IFC model (what MEP draws: segments, fittings,
    terminals, equipment)."""
    return list(model.by_type("IfcDistributionElement"))


def element_class(element: Any) -> str:
    """The element's class; for IFC2X3's generic classes (IfcFlowSegment, ...) the class of its
    type without 'Type' (IfcDuctSegmentType -> IfcDuctSegment)."""
    name = element.is_a()
    if name.startswith(("IfcFlow", "IfcDistributionFlowElement", "IfcEnergyConversionDevice")):
        element_type = ifcopenshell.util.element.get_type(element)
        if element_type is not None and element_type.is_a().endswith("Type"):
            return element_type.is_a()[: -len("Type")]
    return name


def systems_of(element: Any) -> list[str]:
    try:
        return [s.Name or "" for s in ifcopenshell.util.system.get_element_systems(element)]
    except Exception:  # noqa: BLE001 - systems are optional information
        return []


def guess_discipline(counts: Counter[str], systems: Counter[str]) -> tuple[str | None, dict]:
    """The discipline whose classes are most numerous; pipes in systems named for fire
    protection count for fire. Returns (discipline or None, scores)."""
    scores = {name: 0 for name in DISCIPLINE_CLASSES}
    for discipline, classes in DISCIPLINE_CLASSES.items():
        scores[discipline] = sum(counts.get(c, 0) for c in classes)
    fire_pipes = sum(
        n for name, n in systems.items() if any(w in name.lower() for w in _FIRE_WORDS)
    )
    if fire_pipes:
        scores["fire"] += fire_pipes
        scores["plumbing"] = max(scores["plumbing"] - fire_pipes, 0)
    best = max(scores, key=lambda k: scores[k])
    return (best if scores[best] else None), scores


def inspect_ifc(path: str | Path) -> dict[str, Any]:
    """What an MEP IFC file holds: ``{"schema", "elements", "counts", "systems", "storeys",
    "discipline", "scores", "notes"}``. Raises ``ValueError`` when the file cannot be read."""
    try:
        model = ifcopenshell.open(str(path))
    except Exception as error:
        raise ValueError(f"{Path(path).name} could not be read as IFC: {error}") from error
    elements = mep_elements(model)
    counts: Counter[str] = Counter(element_class(e) for e in elements)
    systems: Counter[str] = Counter()
    for element in elements:
        for name in systems_of(element):
            systems[name] += 1
    discipline, scores = guess_discipline(counts, systems)
    notes = []
    if not elements:
        notes.append(f"{Path(path).name} has no MEP (distribution) elements")
    elif discipline is None:
        notes.append(f"{Path(path).name}: its discipline could not be told from its elements")
    return {
        "notes": notes,
        "schema": model.schema,
        "elements": len(elements),
        "counts": dict(sorted(counts.items())),
        "systems": dict(sorted(systems.items())),
        "storeys": [s.Name or "" for s in model.by_type("IfcBuildingStorey")],
        "discipline": discipline,
        "scores": scores,
    }


def mep_import_ifc(project_root: str | Path, path: str | Path, copy: bool = False) -> dict:
    """Inspect an MEP IFC for 7 MEP: :func:`inspect_ifc` and ``"path"``, its project-relative
    path (POSIX separators) for ``mep.json``'s ``ifcModels``. A file outside the project is
    copied into ``07 MEP`` with ``copy`` (else its absolute path is returned, with
    ``"inside": False``). The copy never replaces a file already there: the same file (same
    bytes) is reused, a different one with that name gets the next free ``name (2).ifc``, and a
    note says so. Nothing else is written."""
    root = Path(project_root).resolve()
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    source = source.resolve()
    info = inspect_ifc(source)
    try:
        relative = source.relative_to(root)
        inside = True
    except ValueError:
        inside = False
        if copy:
            folder = root / "07 MEP"
            folder.mkdir(parents=True, exist_ok=True)
            target, k = folder / source.name, 2
            while target.exists() and not filecmp.cmp(target, source, shallow=False):
                target, k = folder / f"{source.stem} ({k}){source.suffix}", k + 1
            if target.exists():
                info["notes"].append(f"07 MEP/{target.name} is already this model; reused")
            else:
                if target.name != source.name:
                    info["notes"].append(
                        f"07 MEP/{source.name} is another model; copied as {target.name}"
                    )
                shutil.copyfile(source, target)
            relative, inside = target.relative_to(root), True
    info["path"] = relative.as_posix() if inside else str(source)
    info["inside"] = inside
    return info
