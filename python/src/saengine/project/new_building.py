"""A new building project from a grid and storeys (integrator glue).

The New Building wizard of the app (``saengine.library.generateBuilding``, RPC
``library/generateBuilding``) and the command line (``saengine new-building <spec.json> <dest>``)
both come here. The building itself is :func:`saengine.library.generator.generate_building`;
this module only

- reads the spec, either the generator's own :class:`~saengine.library.generator.BuildingSpec`
  JSON or the wizard's ``saengine.newBuilding/1`` document (grid lines, storeys and heights
  written out, see ``newBuildingModel.ts``), and maps the wizard's names to the generator's;
- picks the project folder ``<dest_parent>/<name>`` (refusing a folder that holds files already,
  unless ``overwrite``), writes the generated parts (:func:`~saengine.library.generator.
  write_building`) and the placeholders of the parts the generator does not write (soil report,
  MEP, BOQ), as a structural import does.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any

from pydantic import ValidationError

__all__ = ["NewBuildingError", "create_building", "project_parent", "spec_from_wizard"]

WIZARD_SCHEMA = "saengine.newBuilding/1"

#: The wizard's structural systems -> the generator's.
SYSTEMS = {"rcFrame": "rcFrame", "rcFrameCore": "rcFrameWithWalls", "flatSlab": "flatSlab"}

#: Parts the generator does not write: folder -> (main file, part id) or None (folder only).
OTHER_PARTS: dict[str, tuple[str, str] | None] = {
    "01 Soil Report": ("soil-report.json", "soil"),
    "07 MEP": ("mep.json", "mep"),
    "08 FEM": None,
    "10 BOQ": ("boq.json", "boq"),
    "11 Exports": None,
}


#: The wizard's site classes (BNBC 2020 Part 6 Table 6.2.13, p. 609; S1 and S2 need a
#: site-specific study, Sec 2.5.3.1, and are not offered).
SITE_CLASSES = ("SA", "SB", "SC", "SD", "SE")


class NewBuildingError(ValueError):
    """The spec is not valid, the parent folder is not an existing absolute folder, or the
    project folder holds files already."""


def project_parent(dest_parent: str | Path) -> Path:
    """``dest_parent`` as the folder the new project goes in, or :class:`NewBuildingError` when
    it is not an absolute path to an existing folder. Never resolved against the current
    folder: on Windows (and for any path written the Windows way, with a drive letter or
    backslashes) a drive-relative path like ``C:Users`` and a rooted path without a drive like
    ``\\Users`` are not absolute."""
    text = str(dest_parent).strip()
    if not text:
        raise NewBuildingError("give the folder to create the project in")
    windows = os.name == "nt" or re.match(r"^[A-Za-z]:", text) is not None or "\\" in text
    if windows:
        path = PureWindowsPath(text)
        absolute = bool(path.drive) and bool(path.root)
    else:
        absolute = os.path.isabs(text)
    if not absolute:
        raise NewBuildingError(
            f"'{text}' is not a full folder path (give the drive and the folders, e.g. "
            "C:\\Users\\me\\Documents)"
        )
    parent = Path(text)
    if not parent.is_dir():
        raise NewBuildingError(f"the folder '{text}' does not exist")
    return parent


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "-", name).strip().strip(".") or "Building"


def spec_from_wizard(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The generator's spec (:class:`saengine.library.generator.BuildingSpec` JSON) of a
    wizard document (``schema: "saengine.newBuilding/1"``), and notes on what was mapped.
    A spec without that schema is returned as it is."""
    if spec.get("schema") != WIZARD_SCHEMA:
        return dict(spec), []
    notes: list[str] = []
    spacings = spec.get("spacings") or {}
    heights = [float(h) for h in spec.get("storyHeights") or []]
    stories = [s for s in spec.get("stories") or [] if float(s.get("elevation", 0)) > 0]
    names = [str(s.get("name") or s.get("id")) for s in stories]
    if len(names) != len(heights):
        names = [f"Level {i + 1}" for i in range(len(heights))]
    out: dict[str, Any] = {
        "name": spec.get("name") or "Building",
        "gridsX": [float(v) for v in spacings.get("x") or []],
        "gridsY": [float(v) for v in spacings.get("y") or []],
        "stories": [{"name": n, "height": h} for n, h in zip(names, heights, strict=True)],
    }
    system = spec.get("system")
    if system is not None:
        if system not in SYSTEMS:
            raise NewBuildingError(f"unknown structural system '{system}'")
        out["system"] = SYSTEMS[system]
    materials = spec.get("materials") or {}
    for key in ("concrete", "rebar"):
        if materials.get(key):
            out[key] = materials[key]
    footing = spec.get("footing")
    if footing in ("isolated", "mat", "none"):
        out["footing"] = footing
    elif footing == "combined":
        out["footing"] = "isolated"
        notes.append(
            "Combined footings are not generated: isolated footings were placed; combine those "
            "that overlap in 09 Substructure."
        )
    elif footing == "pileCap":
        out["footing"] = "none"
        notes.append(
            "Pile caps are not generated: no foundations were placed; add the pile types and "
            "caps in 09 Substructure."
        )
    site = spec.get("site") or {}
    if site.get("location"):
        out["location"] = site["location"]
    site_class = site.get("siteClass")
    if site_class is not None:
        if site_class not in SITE_CLASSES:
            raise NewBuildingError(
                f"site class '{site_class}' is not one of {', '.join(SITE_CLASSES)}"
            )
        out["siteClass"] = site_class
        source = site.get("siteClassSource", "assumed")
        if source not in ("assumed", "entered"):
            raise NewBuildingError(f"unknown site class source '{source}'")
        out["siteClassSource"] = source
    occupancy = spec.get("occupancy") or {}
    if occupancy.get("use"):
        out["occupancy"] = occupancy["use"]
    if occupancy.get("category"):
        out["occupancyCategory"] = occupancy["category"]
    return out, notes


def create_building(
    spec: dict[str, Any],
    dest_parent: str | Path,
    name: str | None = None,
    overwrite: bool = False,
    site: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generates the building of ``spec`` into a new project ``<dest_parent>/<name>`` (default:
    the spec's name): ``{"root", "name", "notes", "summary", "settingsPatch", "files"}``.
    ``site``: the soil report's site (``saengine.library.soil.Site``) the project starts with;
    with a plot, the project grid is turned along it with its origin inside the buildable
    envelope (``saengine.gis.plot.aligned_site``), where the wizard fitted the grid.
    Raises :class:`NewBuildingError` for an invalid spec, a ``dest_parent`` that is not an
    absolute path to an existing folder (:func:`project_parent`), or a folder holding files
    already (unless ``overwrite``, which replaces the generated part files only)."""
    from saengine.library.generator import BuildingSpec, generate_building, write_building

    parent = project_parent(dest_parent)
    generator_spec, notes = spec_from_wizard(spec)
    if name:
        generator_spec["name"] = name
    try:
        parsed = BuildingSpec.model_validate(generator_spec)
        result = generate_building(parsed)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'spec'}: {e['msg']}" for e in error.errors()
        )
        raise NewBuildingError(f"the building spec is not valid: {problems}") from error
    except ValueError as error:
        raise NewBuildingError(str(error)) from error
    soil_text = None
    if site:
        from saengine.gis.plot import aligned_site
        from saengine.library.soil import Site, SoilReport
        from saengine.soil.report import dumps

        try:
            given = Site.model_validate(site)
            soil_text = dumps(SoilReport(site=Site.model_validate(aligned_site(given) or site)))
        except ValidationError as error:
            raise NewBuildingError(f"the site is not valid: {error.errors()[0]['msg']}") from error
    title = parsed.name
    root = parent / _safe(title)
    if root.exists() and any(root.iterdir()) and not overwrite:
        raise NewBuildingError(f"{root} exists already and is not empty")
    root.mkdir(parents=True, exist_ok=True)
    files = write_building(result, root, title)
    if soil_text is not None:
        path = root / "01 Soil Report" / "soil-report.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(soil_text, encoding="utf-8")
        files.append(path)
    for folder, main in OTHER_PARTS.items():
        (root / folder).mkdir(exist_ok=True)
        if main is not None and not (root / folder / main[0]).exists():
            path = root / folder / main[0]
            path.write_text(
                json.dumps({"schema": 1, "part": main[1]}, indent="\t") + "\n", encoding="utf-8"
            )
            files.append(path)
    return {
        "root": str(root),
        "name": title,
        "notes": notes + list(result["notes"]),
        "summary": result["summary"],
        "settingsPatch": result["settingsPatch"],
        "files": [str(p) for p in files],
    }
