"""The foundation step of Run All: :func:`design_foundations`.

Run All designs the foundations of ``09 Substructure/substructure.json`` with one call:

1. a project from before Part 9 gets the footings of its building model
   (:func:`saengine.substructure.handover.ensure_migrated`);
2. a foundation without bars (the footings of New Building from Grid, a migrated footing type
   without reinforcement) gets the minimum mesh for its thickness, written into the file and
   listed in ``summary["barsAdded"]``: a footing without bars is not designed at all, and the
   minimum mesh is what the engineer would start from (:func:`minimum_mesh`);
3. the design report (:func:`saengine.substructure.report.substructure_report`), whose
   ``summary`` says how many of the foundations and tie beams were checked (``checked`` of
   ``total``) and whether that is all of them (``status``).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from saengine.library.materials import Category, default_of
from saengine.library.substructure import SUBSTRUCTURE_FILE

#: The closest spacing a minimum mesh takes before a larger bar is used [mm].
MIN_SPACING = 125
#: The cover of the bars a foundation without reinforcement gets [mm].
COVER = 75.0
MATERIALS_FILE = "03 Materials/materials.json"


def bar_dias() -> tuple[float, ...]:
    """The bar diameters a minimum mesh is chosen from [mm], as the sizing assistant's: the code
    pack's ``concrete.barDiameters["foundation"]`` (BNBC 2020: 12, 16, 20, 25)."""
    from saengine.design.bars import diameters

    return diameters("foundation")


def min_steel_ratio(fy: float = 420.0) -> float:
    """As,min / Ag of a slab or footing with deformed bars: 0.0018 · 420 / fy, at least 0.0014
    (ACI 318-19 Table 7.6.1.1, as :func:`saengine.substructure.shallow.min_steel_ratio`)."""
    return max(0.0018 * 420.0 / fy, 0.0014)


def minimum_mesh(thickness: float, fy: float = 420.0) -> dict[str, float]:
    """The lightest mesh ``{"dia", "spacing"}`` that gives at least As,min = ratio · h per metre
    (:func:`min_steel_ratio`) at a spacing of at most min(3h, 450 mm) (ACI 318-19 7.7.2.3) and
    at least :data:`MIN_SPACING`, in steps of 25 mm. The Substructure editor's
    ``minimumMesh`` gives the same mesh for a new foundation."""
    need = min_steel_ratio(fy) * thickness * 1000.0
    limit = min(3.0 * thickness, 450.0)
    dias = bar_dias()
    for dia in dias:
        area = math.pi * dia**2 / 4.0
        spacing = min(math.floor(area * 1000.0 / need / 25.0) * 25.0, math.floor(limit / 25) * 25)
        if spacing >= MIN_SPACING:
            return {"dia": dia, "spacing": spacing}
    dia = dias[-1]
    spacing = max(math.floor(math.pi * dia**2 / 4.0 * 1000.0 / need / 25.0) * 25.0, 75.0)
    return {"dia": dia, "spacing": spacing}


def _rebar(root: Path, document: dict[str, Any]) -> tuple[str | None, float]:
    """The bar material a foundation without bars gets: the one the other foundations use, else
    the project's rebar of 03 Materials (``defaults.rebar``, else the first one); with its fy
    [MPa] (420 when unknown)."""
    used = next(
        (
            r["material"]
            for f in document.get("foundations", [])
            if isinstance(r := f.get("reinforcement"), dict) and isinstance(r.get("material"), str)
        ),
        None,
    )
    try:
        library = json.loads((root / MATERIALS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        library = {}
    if not isinstance(library, dict):
        library = {}
    materials = library.get("materials") or []
    rebars = [m for m in materials if isinstance(m, dict) and m.get("category") == "rebar"]
    project = default_of(library, Category.REBAR)
    chosen = next((m for m in rebars if m.get("id") == used), None) or next(
        (m for m in rebars if m.get("id") == project), None
    )
    fy = chosen.get("steel", {}).get("fy") if chosen else None
    material = used or (chosen.get("id") if chosen else None)
    return material, float(fy) if isinstance(fy, int | float) and fy > 0 else 420.0


def add_minimum_bars(root: Path, document: dict[str, Any]) -> list[str]:
    """Gives each foundation of ``document`` (the JSON of ``substructure.json``) that has no
    reinforcement the minimum mesh both ways at the bottom (a raft also at the top: it hogs
    between the columns), :data:`COVER` and the project's bar material. Returns the
    ``"<id> <dia>@<spacing>"`` of each one changed; nothing when there is no bar material."""
    material, fy = _rebar(root, document)
    if material is None:
        return []
    added: list[str] = []
    for foundation in document.get("foundations", []):
        if not isinstance(foundation, dict) or foundation.get("reinforcement") is not None:
            continue
        thickness = foundation.get("thickness")
        if not isinstance(thickness, int | float) or thickness <= 0:
            continue
        mesh = minimum_mesh(float(thickness), fy)
        bars: dict[str, Any] = {"material": material, "cover": COVER}
        layers = ("bottomX", "bottomY") + (
            ("topX", "topY") if foundation.get("type") == "raft" else ()
        )
        for layer in layers:
            bars[layer] = dict(mesh)
        foundation["reinforcement"] = bars
        added.append(f"{foundation.get('id')} {mesh['dia']:g}@{mesh['spacing']:g}")
    return added


def design_foundations(
    project_root: str | Path, out_dir: str | Path | None = None, add_bars: bool = True
) -> dict[str, Any]:
    """The foundation step of Run All (see the module's docstring): the design report of the
    project's substructure, with ``summary["barsAdded"]`` (the foundations given minimum bars)
    and ``migrated`` (the footings moved in from 6 BIM). ``{"problems"}`` when the migration
    fails; a substructure without foundations gives ``{"foundations": [], "summary":
    {"status": "none", ...}}``. Raises ``ValueError`` when a part cannot be read."""
    from saengine.substructure.handover import ensure_migrated, substructure_text
    from saengine.substructure.report import substructure_report

    root = Path(project_root)
    migration = ensure_migrated(root)
    if migration.get("problems"):
        return {"problems": list(migration["problems"])}
    path = root / SUBSTRUCTURE_FILE
    added: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    document = json.loads(text) if text.strip() else None
    if not isinstance(document, dict) or not document.get("foundations"):
        return {
            "foundations": [],
            "tieBeams": [],
            "skipped": [],
            "summary": {"checked": 0, "total": 0, "status": "none", "barsAdded": []},
            "notes": ["There are no foundations to design."],
            "method": [],
            "migrated": migration.get("count", 0),
        }
    if add_bars:
        added = add_minimum_bars(root, document)
        if added:
            path.write_text(substructure_text(document), encoding="utf-8", newline="\n")
    report = substructure_report(root, out_dir)
    report["summary"]["barsAdded"] = added
    if added:
        report["notes"].insert(
            0,
            "Minimum bars added (ACI 318-19 Table 7.6.1.1, As,min = 0.0018 Ag at fy 420; the "
            f"foundations had none): {', '.join(added)}. Check and change them in 9 Substructure.",
        )
    report["migrated"] = migration.get("count", 0)
    return report
