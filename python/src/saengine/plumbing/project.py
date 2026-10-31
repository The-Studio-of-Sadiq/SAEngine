"""The plumbing of a project as the workbench, Run All, the report and the bill use it.

This module joins the sizing (:mod:`saengine.plumbing.report`, BNBC 2020 Part 8), the tank
design (:mod:`saengine.plumbing.tanks`, OpenSees Studio shells) and the water-supply hydraulics
(:mod:`saengine.plumbing.hydraulics`, WNTR / EPANET) into one answer:

- :func:`full_report` the plumbing report with ``tankDesigns`` and ``hydraulics`` added, the
  sleeves still missing and their check, JSON-safe (no infinities), for the RPC.
- :func:`design_tanks` the designs of the tanks, cached in ``07 MEP/mep.results/
  tank-designs.json`` by the tank, its materials, the soil report and the options (an OpenSees
  run takes seconds; an unchanged tank is not run again).
- :func:`missing_sleeves` the proposed sleeves no opening of 07 MEP already gives.
- :func:`occupancies` BNBC Table 8.5.1's rows for the editor.
- :func:`pipe_runs` the risers' lengths and sizes for the bill of quantities.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from saengine.library.mep import MEP_FILE, MepModel, parse

#: Where the tank designs are kept between runs (beside the MEP summary).
DESIGNS_FILE = "07 MEP/mep.results/tank-designs.json"
#: The tank models' folders.
MODELS_DIR = "07 MEP/mep.results/tanks"
SOIL_FILE = "01 Soil Report/soil-report.json"
MATERIALS_FILE = "03 Materials/materials.json"
BIM_FILE = "06 BIM/bim.json"
SETTINGS_FILE = "02 Project Settings/project-settings.json"
#: Version of the cached design entries: a change to the design invalidates them.
DESIGN_CACHE_VERSION = 4


def finite(value: Any) -> Any:
    """``value`` as JSON the workbench can parse: non-finite floats become None (P1 writes
    infinite utilisations where a capacity is zero), numpy scalars Python numbers, tuples
    lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [finite(v) for v in value]
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__ == "numpy":
        return finite(item())
    return value


def _stamp(text: str | None) -> str:
    """The workbench's source stamp of a part file; "" for a missing one (partStatus.ts)."""
    if text is None:
        return ""
    return hashlib.sha1((text or "").replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def occupancies() -> list[dict[str, Any]]:
    """The occupancies of BNBC 2020 Part 8 Tables 8.5.1(a)-(d) as the editor lists them:
    ``[{key, label, lpcd (full facility), restricted, unit, group, table, row, source}]``."""
    from saengine.plumbing import tables as T

    return [
        {
            "key": o.key,
            "label": o.label,
            "lpcd": o.full if o.full is not None else o.restricted,
            "restricted": o.restricted,
            "unit": o.unit,
            "group": o.group,
            "table": o.table,
            "row": o.row,
            "source": T.PAGES.get(o.table, f"Table {o.table}"),
        }
        for o in T.OCCUPANCIES.values()
    ]


# ─────────────────────────────────────── tank designs ───────────────────────────────────────


def tank_stamp(tank: dict[str, Any]) -> str:
    """The stamp of a tank's own data (the bill finds its last design by it)."""
    return _stamp(json.dumps(tank, sort_keys=True))


def _design_key(
    tank: dict[str, Any], materials_text: str | None, soil_text: str | None, options: Any
) -> str:
    return _stamp(
        json.dumps(
            {
                "v": DESIGN_CACHE_VERSION,
                "tank": tank,
                "materials": _stamp(materials_text),
                "soil": _stamp(soil_text),
                "options": options or {},
            },
            sort_keys=True,
        )
    )


def read_designs(root: str | Path) -> dict[str, Any]:
    """The cached designs ``{key: {"id", "tank" (tank_stamp), "result"}}`` (empty when none)."""
    text = _read(Path(root), DESIGNS_FILE)
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    entries = data.get("designs") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def design_tanks(
    root: str | Path,
    tanks: list[dict[str, Any]],
    materials: Any = None,
    materials_text: str | None = None,
    soil_text: str | None = None,
    options: dict[str, Any] | None = None,
    cache: bool = True,
    cached_only: bool = False,
) -> list[dict[str, Any]]:
    """The design of each tank (:func:`saengine.plumbing.tanks.design_tank`), or ``{id, kind,
    error}`` for one that cannot be designed yet. With ``cache``, a tank whose data, materials,
    soil report and options are unchanged since its last design is not run again, and the
    designs are written to :data:`DESIGNS_FILE` (only those of the current tanks are kept).
    ``cached_only``: a tank without a current cached design is not designed but returned as
    ``{id, kind, pending: True}`` (the quick first pass of the report; nothing is written)."""
    from saengine.plumbing.tanks import TankContext, design_tank

    root = Path(root)
    old = read_designs(root) if cache else {}
    kept: dict[str, Any] = {}
    out: list[dict[str, Any]] = []
    context = None
    for tank in tanks:
        key = _design_key(tank, materials_text, soil_text, options)
        entry = old.get(key)
        if entry is not None and isinstance(entry.get("result"), dict):
            result = entry["result"]
        elif cached_only:
            out.append({"id": tank.get("id"), "kind": tank.get("kind"), "pending": True})
            continue
        else:
            if context is None:
                context = TankContext.build(materials, soil_text, options, root / MODELS_DIR)
            try:
                result = finite(design_tank(tank, context))
            except Exception as error:  # noqa: BLE001 - one tank must not fail the report
                message = str(error).strip().splitlines()[0] if str(error).strip() else repr(error)
                result = {"id": tank.get("id"), "kind": tank.get("kind"), "error": message}
        out.append(result)
        if "error" not in result:
            kept[key] = {"id": tank.get("id"), "tank": tank_stamp(tank), "result": result}
    if cache and not cached_only and (kept.keys() != old.keys()):
        path = root / DESIGNS_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"version": DESIGN_CACHE_VERSION, "designs": kept}) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass  # a read-only project still gets its report
    return out


def _with_proposals(tank: dict[str, Any], proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The user's tank with the sizes the sizing proposes where it gives none (so a tank still
    being entered is designed at the proposed size)."""
    proposal = proposals.get(str(tank.get("id")))
    if not proposal:
        return tank
    return {**proposal, **{k: v for k, v in tank.items() if v is not None}}


# ─────────────────────────────────────── sleeves ───────────────────────────────────────


def _opening_covers(opening: Any, x: float, y: float) -> bool:
    p = opening.position
    if p.x is None or p.y is None:
        return False
    width, height = opening.size
    if opening.shape == "circle":
        return math.hypot(x - p.x, y - p.y) <= width / 2 + 1e-6
    return abs(x - p.x) <= width / 2 + 1e-6 and abs(y - p.y) <= height / 2 + 1e-6


def missing_sleeves(mep: MepModel, proposed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The proposed sleeves (07 MEP openings) that no opening of ``mep`` on the same slab already
    gives: by id, or by covering the riser's point."""
    have = {o.id for o in mep.openings}
    out = []
    for sleeve in proposed:
        if sleeve.get("id") in have:
            continue
        x, y = sleeve["position"].get("x"), sleeve["position"].get("y")
        if (
            x is not None
            and y is not None
            and any(o.host == sleeve["host"] and _opening_covers(o, x, y) for o in mep.openings)
        ):
            continue
        out.append(sleeve)
    return out


def sleeves_check(missing: list[dict[str, Any]]) -> dict[str, Any]:
    """The check Run All and the report list: every riser and stack has its sleeve through each
    slab it crosses (SAEngine coordination check; the editor's Add Sleeves adds them)."""
    names = ", ".join(s["id"] for s in missing[:6]) + ("…" if len(missing) > 6 else "")
    return {
        "name": "Sleeves for the risers and stacks",
        "demand": float(len(missing)),
        "capacity": 0.0,
        "unit": "missing",
        "utilisation": None if missing else 0.0,
        "ok": not missing,
        "note": (
            f"{len(missing)} slab crossing(s) without a sleeve: {names}; add them with Add Sleeves "
            "in 7 MEP (Plumbing)"
            if missing
            else "every slab crossing has a sleeve, an opening or a shaft"
        ),
    }


# ─────────────────────────────────────── the full report ───────────────────────────────────────


def _sizing(report: dict[str, Any]) -> dict[str, Any]:
    """What the hydraulics take from the sizing: riser diameters and proposed tank sizes."""
    risers = {
        r["id"]: {"diameter": r["diameter"]}
        for r in report.get("risers") or []
        if r.get("id") and r.get("diameter")
    }
    tanks: dict[str, Any] = {}
    volumes = {
        t.get("id"): t.get("provided") for t in (report.get("storage") or {}).get("tanks") or []
    }
    for t in report.get("tanks") or []:
        entry = {k: t[k] for k in ("waterDepth", "length", "width") if t.get(k) is not None}
        if volumes.get(t.get("id")):
            entry["volume"] = volumes[t["id"]]
        if entry:
            tanks[t["id"]] = entry
    return {"risers": risers, "tanks": tanks}


def full_report(
    project_root: str | Path,
    mep_text: str | None = None,
    *,
    designs: bool | str = True,
    hydraulics: bool = True,
) -> dict[str, Any]:
    """The plumbing report of a project for the workbench (``saengine.plumbing.report``):
    :func:`saengine.plumbing.report.plumbing_report` with ``sleeves`` reduced to those still
    missing (:func:`missing_sleeves`) and their check added to ``checks``, ``tankDesigns`` (the
    design of each tank of ``plumbing.tanks``, sized where it gives no size), ``hydraulics``
    (:func:`saengine.plumbing.hydraulics.water_hydraulics` with the sizing's sizes) and
    ``sources`` (the stamps of the files read). Never raises: ``{problems}`` when 07 MEP cannot
    be read. ``mep_text``: the editor's unsaved text of ``07 MEP/mep.json``. ``designs``:
    ``"cached"`` gives only the tank designs already cached and lists the others as pending
    (``tankDesignsPending``: how many), so the editor shows the rest of the report at once."""
    from saengine.plumbing.report import plumbing_report

    root = Path(project_root)
    report = plumbing_report(root, mep_text)
    if "demand" not in report:
        return finite(report)
    text = mep_text if mep_text is not None else _read(root, MEP_FILE)
    try:
        mep = parse(text)
    except ValueError as error:
        return {"problems": [f"{MEP_FILE} is not valid: {error}"]}
    from saengine.mep.rooms import read_room_inputs, stamp, with_rooms

    # The hydraulics draw the same fixtures as the sizing: the rooms' where they are used.
    mep, _ = with_rooms(mep, read_room_inputs(root, mep.plumbing)[0])
    proposed = list(report.get("sleeves") or [])
    missing = missing_sleeves(mep, proposed)
    report["sleeves"] = missing
    report["sleevesProposed"] = len(proposed)
    report["tankDesigns"] = []
    report["hydraulics"] = None
    soil_text = _read(root, SOIL_FILE)
    materials_text = _read(root, MATERIALS_FILE)
    if mep.plumbing is not None:
        if mep.plumbing.risers:
            report["checks"].append(sleeves_check(missing))
        if designs and mep.plumbing.tanks:
            report["tankDesigns"] = project_tank_designs(
                root, mep, report, materials_text, soil_text, cached_only=designs == "cached"
            )
            report["tankDesignsPending"] = sum(1 for d in report["tankDesigns"] if d.get("pending"))
            done = [d for d in report["tankDesigns"] if not d.get("pending")]
            report["checks"].extend(linked_weight_checks(mep, done))
        if hydraulics:
            report["hydraulics"] = _hydraulics(root, mep, report)
    _summarise_checks(report)
    report["sources"] = {
        "mep": _stamp(text),
        "bim": _stamp(_read(root, BIM_FILE)),
        "soil": _stamp(soil_text),
        "materials": _stamp(materials_text),
        "settings": _stamp(_read(root, SETTINGS_FILE)),
        "architecture": stamp(root),
    }
    return finite(report)


def project_tank_designs(
    root: Path,
    mep: MepModel,
    report: dict[str, Any],
    materials_text: str | None,
    soil_text: str | None,
    cached_only: bool = False,
) -> list[dict[str, Any]]:
    """The designs of the project's tanks (the user's, sized where they give no size)."""
    from saengine.library.materials import MaterialLibrary

    assert mep.plumbing is not None
    materials = None
    if materials_text:
        try:
            materials = MaterialLibrary.model_validate_json(materials_text)
        except ValueError:
            materials = None
    proposals = {str(t.get("id")): t for t in report.get("tanks") or []}
    tanks = [
        _with_proposals(t.model_dump(mode="json", exclude_none=True), proposals)
        for t in mep.plumbing.tanks
    ]
    return design_tanks(root, tanks, materials, materials_text, soil_text, cached_only=cached_only)


#: An equipment tank that stands for a plumbing tank may weigh this much less than the tank's
#: design before the check fails (rounding of an entered weight).
WEIGHT_TOLERANCE = 0.05


def linked_weight_checks(mep: MepModel, designs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For an overhead tank whose weight the analysis takes from an equipment tank (linked, or
    standing where it is: :func:`saengine.mep.loads.plumbing_tank_equipment`), whether that
    equipment carries the tank's designed weight: empty (its concrete and roof finish) and full
    (with the water to the overflow)."""
    from saengine.mep.loads import footprint_covers

    assert mep.plumbing is not None
    by_id = {d.get("id"): d for d in designs}
    checks = []
    for tank in mep.plumbing.tanks:
        if tank.kind != "overhead":
            continue
        equipment = next(
            (
                e
                for e in mep.equipment
                if e.kind == "tank"
                and (
                    e.id == tank.equipment
                    if tank.equipment is not None
                    else e.story == tank.story and footprint_covers(e, tank.x, tank.y)
                )
            ),
            None,
        )
        loads = (by_id.get(tank.id) or {}).get("supportLoads")
        if equipment is None or not loads:
            continue
        empty = equipment.emptyWeight if equipment.emptyWeight is not None else 0.0
        need_full, need_empty = float(loads["full"]), float(loads["empty"])
        ok = equipment.operatingWeight >= need_full * (1 - WEIGHT_TOLERANCE) and (
            empty >= need_empty * (1 - WEIGHT_TOLERANCE)
        )
        checks.append(
            {
                "name": f"{tank.id} weight in the analysis ({equipment.id})",
                "demand": need_full,
                "capacity": float(equipment.operatingWeight),
                "unit": "kN",
                "utilisation": need_full / equipment.operatingWeight
                if equipment.operatingWeight
                else None,
                "ok": bool(ok),
                "note": (
                    f"the analysis loads {equipment.id}: {empty:g} kN empty, "
                    f"{equipment.operatingWeight:g} kN full; {tank.id}'s design: {need_empty:g} "
                    f"kN empty, {need_full:g} kN full"
                    + (
                        ""
                        if ok
                        else f"; enter these in {equipment.id}, or delete it (and the link) so "
                        f"the tank loads the model itself"
                    )
                ),
            }
        )
    return checks


def _hydraulics(root: Path, mep: MepModel, report: dict[str, Any]) -> dict[str, Any]:
    try:
        from saengine.plumbing.hydraulics import water_hydraulics
    except ImportError as error:  # WNTR missing from the environment
        return {
            "floors": [], "risers": [], "pump": None, "zones": [], "mains": None, "checks": [],
            "notes": [], "problems": [f"the hydraulics need WNTR: {error}"],
        }  # fmt: skip
    try:
        return water_hydraulics(
            root, mep=mep.model_dump(mode="json", by_alias=True), sizing=_sizing(report)
        )
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {
            "floors": [], "risers": [], "pump": None, "zones": [], "mains": None, "checks": [],
            "notes": [], "problems": [f"the hydraulics failed: {error!r}"],
        }  # fmt: skip


def _summarise_checks(report: dict[str, Any]) -> None:
    """The summary's line of the checks counts every check the editor counts (the sizing's,
    the hydraulics' and the tank designs', :func:`plumbing_failures`) and names the failing ones,
    so it agrees with the tile; the sizing's own line counted only its checks."""
    checks = [c for c in report.get("checks") or [] if isinstance(c, dict)]
    checks += [
        c for c in (report.get("hydraulics") or {}).get("checks") or [] if isinstance(c, dict)
    ]
    for design in report.get("tankDesigns") or []:
        checks += [
            {**c, "name": f"{design.get('id')}: {c.get('name')}"}
            for c in design.get("checks") or []
            if isinstance(c, dict)
        ]
    failed = [str(c.get("name")) for c in checks if c.get("ok") is False]
    line = f"{len(failed)} of {len(checks)} checks fail" + (
        f": {', '.join(failed)}" if failed else ""
    )
    if report.get("tankDesignsPending"):
        line += (
            f" ({report['tankDesignsPending']} tank designs running in the background: "
            "their checks are added when they are in)"
        )
    summary = [s for s in report.get("summary") or [] if " checks fail" not in s]
    pump = (report.get("hydraulics") or {}).get("pump")
    if isinstance(pump, dict) and pump.get("motor") is not None and pump.get("flow") is not None:
        # The sizing's line gives the flow only: with the hydraulics, its head and motor too.
        duty = (
            f"Pump {pump['flow'] * 60:.1f} l/min at {pump.get('tdh', 0):.1f} m head, "
            f"{pump.get('shaftPower', 0):.2g} kW at the shaft: a {pump['motor']:g} kW motor"
        )
        summary = [duty if s.startswith("Pump ") else s for s in summary]
    report["summary"] = [*summary, line]


def plumbing_failures(report: dict[str, Any]) -> tuple[int, int]:
    """(failing checks, floors below the minimum pressure) of a :func:`full_report`, counted as
    the editor's summary counts them (the sizing's, the hydraulics' and every tank design's
    checks; distinct stories whose floor lacks the pressure)."""
    checks = list(report.get("checks") or [])
    hyd = report.get("hydraulics") or {}
    checks += hyd.get("checks") or []
    for design in report.get("tankDesigns") or []:
        checks += design.get("checks") or []
    failed = sum(1 for c in checks if isinstance(c, dict) and c.get("ok") is False)
    low = {f.get("story") for f in hyd.get("floors") or [] if f.get("pressureOk") is False}
    return failed, len(low)


# ─────────────────────────────────────── bill of quantities ───────────────────────────────────────


def pipe_runs(mep: MepModel, bim: Any, report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The risers and stacks as vertical runs for the bill: ``[{id, system, material, diameter
    (mm), length (m), story}]``, the length from the story it starts at to its top story, the
    diameter the user's or the sizing's (at the riser's base)."""
    if mep.plumbing is None or bim is None:
        return []
    levels = {s.id: s.elevation for s in bim.stories}
    sized = {r["id"]: r.get("diameter") for r in (report or {}).get("risers") or [] if r.get("id")}
    runs = []
    for riser in mep.plumbing.risers:
        if riser.fromStory not in levels or riser.toStory not in levels:
            continue
        length = (levels[riser.toStory] - levels[riser.fromStory]) / 1000.0
        diameter = riser.diameter or sized.get(riser.id)
        if length <= 0:
            continue
        runs.append(
            {
                "id": riser.id,
                "system": riser.system,
                "material": riser.material,
                "diameter": float(diameter) if diameter else None,
                "length": length,
                "story": riser.fromStory,
            }
        )
    return runs
