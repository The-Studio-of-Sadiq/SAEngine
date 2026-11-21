"""Thin JSON-RPC handlers for SAEngine U3 engine features (no new math; delegates to domain modules).

Never raises across the JSON-RPC boundary: validation or missing-input errors return a dict with
``problems`` and/or ``notes`` so the generic UI data panel can display clear guidance.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def _first_line(error: BaseException) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _finite(value: Any) -> Any:
    from saengine.plumbing.project import finite

    return finite(value)


def _load_mep_and_context(project_root: str | Path, mep_text: str | None = None) -> dict[str, Any]:
    from saengine.library import architecture as arch_lib
    from saengine.library.bim import BuildingModel
    from saengine.library.mep import MEP_FILE, parse
    from saengine.library.objects import ObjectLibrary
    from saengine.mep.rooms import read_room_inputs
    from saengine.plumbing.building import Building

    root = Path(project_root)
    problems: list[str] = []
    text = mep_text if mep_text is not None else _read_text(root / MEP_FILE)
    try:
        mep = parse(text)
    except ValueError as error:
        raise ValueError(f"{MEP_FILE} is not valid: {error}") from error

    bim = objects = arch = None
    bim_text = _read_text(root / "06 BIM/bim.json")
    if bim_text:
        try:
            bim = BuildingModel.model_validate_json(bim_text)
        except ValueError as error:
            problems.append(f"06 BIM/bim.json is not valid: {error}")
    obj_text = _read_text(root / "04 Objects/objects.json")
    if obj_text:
        try:
            objects = ObjectLibrary.model_validate_json(obj_text)
        except ValueError as error:
            problems.append(f"04 Objects/objects.json is not valid: {error}")
    arch_text = _read_text(root / arch_lib.ARCHITECTURE_FILE)
    if arch_text:
        try:
            arch = arch_lib.parse(arch_text)
        except ValueError as error:
            problems.append(f"05 Floor Plan/architecture.json is not valid: {error}")

    ground = None
    building_use = None
    settings_text = _read_text(root / "02 Project Settings/project-settings.json")
    if settings_text:
        try:
            raw_settings = json.loads(settings_text)
            if isinstance(raw_settings, dict):
                ground = (raw_settings.get("foundation") or {}).get("groundLevel")
                building_use = (raw_settings.get("occupancy") or {}).get("use")
        except ValueError:
            pass
    if not isinstance(ground, int | float):
        ground = None

    rooms, room_problem = read_room_inputs(root, mep.plumbing)
    if room_problem:
        problems.append(room_problem)

    building = Building.of(bim, ground)
    return {
        "root": root,
        "mep": mep,
        "bim": bim,
        "objects": objects,
        "arch": arch,
        "building": building,
        "ground": ground,
        "building_use": building_use,
        "rooms": rooms,
        "problems": problems,
    }


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.strip()).strip("_").lower()


# ────────────────────────────────────────── Electrical ──────────────────────────────────────────


def electrical_cable_size(
    project_root: str | None = None,
    *,
    mode: str = "project",
    design_current_a: float = 32.0,
    length_m: float = 30.0,
    phases: int = 1,
    installation_method: str = "C",
    insulation: str = "PVC",
    conductor: str = "Cu",
    ambient_c: float = 35.0,
    grouped_circuits: int = 1,
    vd_limit_pct: float = 4.0,
    nominal_voltage: float | None = None,
) -> dict[str, Any]:
    """Cable sizing & voltage drop check: project circuit schedule OR standalone calculator."""
    from saengine.codes import context as code_context
    from saengine.report.clauses import in_force

    if mode == "calculator":
        from saengine.electrical.cables import size_cable

        try:
            ctx = (
                in_force(project_root)
                if project_root
                else code_context.using(code_context.pack_for())
            )
            with ctx:
                sized = size_cable(
                    float(design_current_a),
                    float(length_m),
                    phases=int(phases) if int(phases) in (1, 3) else 1,
                    conductor=conductor,
                    insulation=insulation,
                    method=installation_method,
                    ambient_temp=float(ambient_c),
                    grouped_circuits=max(1, int(grouped_circuits)),
                    vd_limit_pct=float(vd_limit_pct),
                    voltage=float(nominal_voltage) if nominal_voltage else None,
                )
            notes = [sized["note"]] if sized.get("note") else []
            return _finite({"mode": "calculator", "result": sized, "notes": notes, "problems": []})
        except Exception as error:  # noqa: BLE001
            return {
                "mode": "calculator",
                "result": None,
                "notes": [],
                "problems": [_first_line(error)],
            }

    if not project_root:
        return {
            "mode": "project",
            "boards": [],
            "circuits": [],
            "notes": [],
            "problems": ["No project folder given."],
        }
    from saengine.electrical.report import electrical_report

    try:
        report = electrical_report(project_root)
    except Exception as error:  # noqa: BLE001
        return {
            "mode": "project",
            "boards": [],
            "circuits": [],
            "notes": [],
            "problems": [_first_line(error)],
        }
    boards = list(report.get("boards") or [])
    circuits = [
        {**c, "board": b["id"], "story": b.get("story")}
        for b in boards
        for c in b.get("circuits") or []
    ]
    return _finite(
        {
            "mode": "project",
            "boards": boards,
            "circuits": circuits,
            "shortCircuit": report.get("shortCircuit"),
            "failingVd": list(report.get("failingVoltageDrop") or []),
            "notes": list(report.get("notes") or []),
            "problems": list(report.get("problems") or []),
        }
    )


def electrical_lighting(
    project_root: str,
    *,
    luminaire_type: str | None = None,
    maintenance_factor: float | None = None,
    work_plane_m: float | None = None,
    reflectance: str | None = None,
) -> dict[str, Any]:
    """Run lumen-method interior lighting design even when electrical.lighting isn't enabled yet."""
    from saengine.electrical.lighting import lighting_design
    from saengine.electrical.risers import Frame
    from saengine.library.mep import Electrical, LightingSettings
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            ctx = _load_mep_and_context(project_root)
            mep = ctx["mep"]
            elec = mep.electrical or Electrical()
            base_cfg = elec.lighting or LightingSettings()
            cfg = base_cfg.model_copy(
                update={
                    "enabled": True,
                    **({"luminaireType": luminaire_type} if luminaire_type else {}),
                    **(
                        {"maintenanceFactor": float(maintenance_factor)}
                        if maintenance_factor is not None
                        else {}
                    ),
                    **({"workPlaneM": float(work_plane_m)} if work_plane_m is not None else {}),
                    **({"reflectance": reflectance} if reflectance else {}),
                }
            )
            mep_mod = mep.model_copy(
                update={"electrical": elec.model_copy(update={"lighting": cfg})}
            )
            frame = Frame.of(ctx["bim"], ctx["objects"])
            out = lighting_design(mep_mod, ctx["building"], ctx["rooms"], frame.slab_thickness)
            notes: list[str] = []
            if elec.lighting is None or not elec.lighting.enabled:
                notes.append(
                    "Computed using Lighting Designer defaults (07 MEP electrical.lighting is not yet saved)."
                )
            stories = list((out.get("stories") or {}).values())
            return _finite(
                {
                    "rooms": out.get("rooms") or [],
                    "stories": stories,
                    "circuits": out.get("circuits") or [],
                    "luminaireCount": len(out.get("luminaires") or []),
                    "totalKw": round(sum(s.get("kw") or 0.0 for s in stories), 3),
                    "notes": notes,
                    "problems": [*pack_problems, *ctx["problems"]],
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "rooms": [],
            "stories": [],
            "circuits": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


# ────────────────────────────────────────── HVAC ──────────────────────────────────────────


def hvac_loads_detailed(
    project_root: str,
    *,
    zoning: str | None = None,
    use_energyplus: bool = False,
    annual: bool = False,
    epw: str | None = None,
) -> dict[str, Any]:
    """Cooling/heating loads (room or story zoning), envelope compliance, and optional annual simulation."""
    from saengine.hvac.report import hvac_loads

    try:
        res = hvac_loads(
            project_root,
            use_energyplus=bool(use_energyplus or annual),
            run_energyplus=bool(use_energyplus or annual),
            zoning=zoning or "room",
            annual=bool(annual),
            epw=epw or None,
        )
        res.pop("stamp", None)
        return _finite(res)
    except Exception as error:  # noqa: BLE001
        return {
            "engine": None,
            "zones": [],
            "stories": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def hvac_duct_pressure(
    project_root: str,
    *,
    friction_rate: float = 1.0,
    method: str = "equalFriction",
    material: str | None = None,
    supply_delta_t: float | None = None,
) -> dict[str, Any]:
    """Duct network friction/fitting/critical-path pressure loss and velocity check."""
    from saengine.hvac.air import SUPPLY_DT, duct_network_pressure, hvac_air, size_duct_network
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            air = hvac_air(
                project_root,
                dt=float(supply_delta_t) if supply_delta_t is not None else SUPPLY_DT,
                rate=float(friction_rate),
                with_plant=False,
                with_openings=False,
            )
            ducts = list(air.get("ducts") or [])
            pressure = air.get("pressure")
            if ducts and (method != "equalFriction" or material):
                from saengine.hvac.air import load_project

                proj = load_project(project_root)
                raw_by_id = {
                    d["id"]: d
                    for d in proj.hvac.get("ducts", [])
                    if isinstance(d, dict) and d.get("id")
                }
                segments = [
                    {
                        **raw_by_id.get(d["id"], {}),
                        **d,
                        "size": d["size"],
                        **({"material": material} if material else {}),
                    }
                    for d in ducts
                    if d.get("flow") and d.get("size")
                ]
                if segments:
                    resized = size_duct_network(
                        segments,
                        method=method,
                        rate=float(friction_rate),
                        material=material,
                    )
                    pressure = resized["pressure"]
                elif segments := [d for d in ducts if d.get("flow")]:
                    pressure = duct_network_pressure(segments)
            problems = [*pack_problems, *(air.get("problems") or [])]
            return _finite(
                {
                    "ducts": ducts,
                    "pressure": pressure,
                    "zones": air.get("zones") or [],
                    "checks": air.get("checks") or [],
                    "notes": list(air.get("notes") or []),
                    "problems": problems,
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "ducts": [],
            "pressure": None,
            "zones": [],
            "checks": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def hvac_route_ducts(
    project_root: str,
    *,
    story: str | None = None,
    system: str = "supply",
    shape: str = "rect",
    method: str = "equalFriction",
    friction_rate: float = 1.0,
    beam_penalty: float = 5000.0,
    material: str | None = None,
    apply_to_mep: bool = False,
) -> dict[str, Any]:
    """Auto-route HVAC ducts from AHU/shaft to each room diffuser on ``story``."""
    from saengine.hvac.report import hvac_loads
    from saengine.hvac.routing import auto_route_ducts
    from saengine.library.mep import MEP_FILE
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            ctx = _load_mep_and_context(project_root)
            loads = hvac_loads(project_root, zoning="room", run_energyplus=False)
            rooms = ctx["rooms"]
            building = ctx["building"]
            available_stories = (
                list(rooms.stories)
                if rooms is not None and rooms.stories
                else (
                    building.ordered()[:-1]
                    if building.known and len(building.ordered()) > 1
                    else building.ordered()
                )
            )
            target_story = story or (available_stories[0] if available_stories else None)
            if not target_story:
                return {
                    "story": None,
                    "availableStories": available_stories,
                    "ducts": [],
                    "pressure": None,
                    "notes": [],
                    "problems": [
                        *pack_problems,
                        "No storeys or architectural rooms found to route ducts.",
                    ],
                }
            mep = ctx["mep"]
            start_pt: tuple[float, float] | None = None
            if mep.hvac is not None:
                for p in mep.hvac.plant:
                    if p.story == target_story and p.kind in ("ahu", "freshAirUnit", "fcu"):
                        start_pt = (float(p.x), float(p.y))
                        break
            if start_pt is None and mep.shafts:
                pts = mep.shafts[0].outline
                start_pt = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            if (
                start_pt is None
                and rooms is not None
                and rooms.story(target_story)
                and rooms.story(target_story).rooms
            ):
                rm0 = rooms.story(target_story).rooms[0].net.representative_point()
                start_pt = (float(rm0.x), float(rm0.y))
            if start_pt is None:
                poly = building.roof(target_story) if building.known else None
                if poly is not None and not poly.is_empty:
                    c = poly.representative_point()
                    start_pt = (float(c.x), float(c.y))
                else:
                    start_pt = (0.0, 0.0)

            routed = auto_route_ducts(
                target_story,
                start_pt,
                loads.get("zones") or [],
                rooms,
                bim=ctx["bim"],
                arch=ctx["arch"],
                objects=ctx["objects"],
                system=system,
                shape=shape,
                method=method,
                rate=float(friction_rate),
                beam_penalty=float(beam_penalty),
                material=material or None,
            )
            applied = False
            if apply_to_mep and routed.get("ducts"):
                mep_path = Path(project_root) / MEP_FILE
                raw = json.loads(mep_path.read_text(encoding="utf-8")) if mep_path.is_file() else {}
                hvac_sec = raw.setdefault("hvac", {})
                existing = [
                    d
                    for d in (hvac_sec.get("ducts") or [])
                    if not (
                        isinstance(d, dict)
                        and d.get("story") == target_story
                        and d.get("system", "supply") == system
                    )
                ]
                hvac_sec["ducts"] = [*existing, *routed["ducts"]]
                _atomic_write(mep_path, json.dumps(raw, indent="\t", ensure_ascii=False) + "\n")
                applied = True

            return _finite(
                {
                    "story": target_story,
                    "availableStories": available_stories,
                    "startPoint": [round(start_pt[0], 1), round(start_pt[1], 1)],
                    "applied": applied,
                    **routed,
                    "problems": [*pack_problems, *ctx["problems"]],
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "story": story,
            "availableStories": [],
            "ducts": [],
            "pressure": None,
            "notes": [],
            "problems": [_first_line(error)],
        }


# ────────────────────────────────────────── Fire & Plumbing ──────────────────────────────────────────


def fire_sprinklers(
    project_root: str,
    *,
    hazard: str | None = None,
    material: str = "steel",
    ceiling: str = "beams",
) -> dict[str, Any]:
    """Sprinkler head placement and NFPA/BNBC pipe schedule per story (without running tank FE)."""
    from saengine.fire import tables as T
    from saengine.fire.sprinklers import floor_sprinklers, layout_story_sprinklers
    from saengine.library.mep import Fire
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            ctx = _load_mep_and_context(project_root)
            building = ctx["building"]
            rooms = ctx["rooms"]
            mep = ctx["mep"]
            fire = mep.fire or Fire()
            eff_hazard = hazard or getattr(fire, "hazard", None) or "lightI"
            if eff_hazard not in T.DENSITY_AREA:
                eff_hazard = "lightI"

            story_ids: list[str] = []
            if building.known:
                order = building.ordered()
                story_ids = order[:-1] if len(order) > 1 else order
            elif fire.stories:
                story_ids = [s.story for s in fire.stories]
            elif rooms is not None:
                story_ids = list(rooms.stories)

            riser0 = fire.risers[0] if fire.risers else None
            stories_out: list[dict[str, Any]] = []
            all_heads: list[dict[str, Any]] = []
            all_pipes: list[dict[str, Any]] = []
            notes: list[str] = []
            h_offset = 1
            p_offset = 1

            for sid in story_ids:
                poly = building.roof(sid) if building.known else None
                story_rooms = (
                    rooms.story(sid).rooms if (rooms is not None and rooms.story(sid)) else []
                )
                area = (
                    building.floor_area(sid) if building.known else sum(r.area for r in story_rooms)
                )
                if area <= 0 and story_rooms:
                    area = sum(r.area for r in story_rooms)
                if area <= 0:
                    continue
                extent = (
                    (
                        (poly.bounds[2] - poly.bounds[0]) / 1000.0,
                        (poly.bounds[3] - poly.bounds[1]) / 1000.0,
                    )
                    if (poly is not None and not poly.is_empty)
                    else None
                )
                floor_info = floor_sprinklers(area, eff_hazard, ceiling, extent, material)
                if riser0 is not None:
                    rxy = (riser0.x, riser0.y)
                elif poly is not None and not poly.is_empty:
                    c = poly.representative_point()
                    rxy = (float(c.x), float(c.y))
                elif story_rooms:
                    c = story_rooms[0].net.representative_point()
                    rxy = (float(c.x), float(c.y))
                else:
                    rxy = (0.0, 0.0)
                lay = layout_story_sprinklers(
                    sid,
                    rxy,
                    story_rooms,
                    poly,
                    eff_hazard,
                    ceiling,
                    material,
                    head_offset=h_offset,
                    pipe_offset=p_offset,
                )
                h_offset += len(lay["heads"])
                p_offset += len(lay["pipes"])
                all_heads.extend(lay["heads"])
                all_pipes.extend(lay["pipes"])
                stories_out.append(
                    {
                        "story": sid,
                        "area": floor_info["area"],
                        "hazard": eff_hazard,
                        "coverage": floor_info["coverage"],
                        "maxSpacing": floor_info["maxSpacing"],
                        "heads": max(floor_info["heads"], lay["headCount"]),
                        "placedHeads": lay["headCount"],
                        "designArea": floor_info["designArea"],
                        "designHeads": floor_info["designHeads"],
                        "headFlow": floor_info["headFlow"],
                        "demand": floor_info["demand"],
                        "mainSize": lay["mainSize"] or floor_info["mainSize"],
                        "risersNeeded": floor_info["risersNeeded"],
                    }
                )
            if not stories_out:
                notes.append("No floor slabs or rooms found to place sprinklers.")
            return _finite(
                {
                    "hazard": eff_hazard,
                    "material": material,
                    "stories": stories_out,
                    "heads": all_heads,
                    "pipes": all_pipes,
                    "headCount": len(all_heads),
                    "totalDemand": round(max((s["demand"] for s in stories_out), default=0.0), 1),
                    "notes": notes,
                    "problems": [*pack_problems, *ctx["problems"]],
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "stories": [],
            "heads": [],
            "pipes": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def fire_alarm(
    project_root: str,
    *,
    standby_hours: float | None = None,
    alarm_minutes: float | None = None,
    ageing_factor: float | None = None,
) -> dict[str, Any]:
    """Fire alarm device layout and battery capacity sizing with optional standby/alarm overrides."""
    from saengine.fire.alarm import alarm_layout, battery_calculation
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            ctx = _load_mep_and_context(project_root)
            out = alarm_layout(ctx["mep"], ctx["building"], ctx["rooms"], ctx["arch"])
            bat = out.get("battery") or {}
            if standby_hours is not None or alarm_minutes is not None or ageing_factor is not None:
                standby_a = float(bat.get("standbyAmps") or 0.0)
                alarm_a = float(bat.get("alarmAmps") or 0.0)
                bat = battery_calculation(
                    standby_a,
                    alarm_a,
                    standby_hours=float(standby_hours) if standby_hours is not None else None,
                    alarm_minutes=float(alarm_minutes) if alarm_minutes is not None else None,
                    ageing_factor=float(ageing_factor) if ageing_factor is not None else None,
                )
                out["battery"] = bat
            return _finite(
                {
                    **out,
                    "notes": list(out.get("notes") or []),
                    "problems": [*pack_problems, *ctx["problems"]],
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "devices": [],
            "counts": {},
            "battery": None,
            "notes": [],
            "problems": [_first_line(error)],
        }


def plumbing_hot_water(
    project_root: str,
    *,
    supply_temp_c: float | None = None,
    cold_temp_c: float | None = None,
    loop_length_m: float | None = None,
    material: str | None = None,
) -> dict[str, Any]:
    """Domestic hot water heater sizing and recirculation loop hydraulics."""
    from saengine.library.mep import HotWaterSystem, Plumbing
    from saengine.mep.rooms import with_rooms
    from saengine.plumbing.hot_water import hot_water_results
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            ctx = _load_mep_and_context(project_root)
            mep, _sources = with_rooms(ctx["mep"], ctx["rooms"])
            plumb = mep.plumbing or Plumbing()
            configured = plumb.hotWater is not None and bool(plumb.hotWater.enabled)
            hw_cfg = (plumb.hotWater or HotWaterSystem(enabled=True)).model_copy(
                update={
                    "enabled": True,
                    **({"storageTempC": float(supply_temp_c)} if supply_temp_c is not None else {}),
                    **({"coldTempC": float(cold_temp_c)} if cold_temp_c is not None else {}),
                    **({"loopLengthM": float(loop_length_m)} if loop_length_m is not None else {}),
                    **({"material": material} if material else {}),
                }
            )
            mep_mod = mep.model_copy(
                update={"plumbing": plumb.model_copy(update={"hotWater": hw_cfg})}
            )
            hw = hot_water_results(mep_mod, ctx["building"])
            notes: list[str] = []
            if not configured:
                notes.append(
                    "Computed using Hot Water defaults (07 MEP plumbing.hotWater is not yet configured)."
                )
            if not plumb.stories:
                notes.append(
                    "No plumbing storeys or wet rooms found; fixture hot-water demand is 0 L/h."
                )
            return _finite(
                {
                    "configured": configured,
                    "hotWater": hw,
                    "notes": notes,
                    "problems": [*pack_problems, *ctx["problems"]],
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "configured": False,
            "hotWater": None,
            "notes": [],
            "problems": [_first_line(error)],
        }


def plumbing_gas(
    project_root: str,
    *,
    fuel: str | None = None,
    supply_pressure_kpa: float | None = None,
    max_drop_kpa: float | None = None,
) -> dict[str, Any]:
    """Fuel gas (Pole's formula) and medical gas piping sizing."""
    from saengine.library.mep import GasSystem
    from saengine.mep.rooms import with_rooms
    from saengine.plumbing.gas import gas_results, medical_gas_results
    from saengine.report.clauses import in_force

    try:
        with in_force(project_root) as pack_problems:
            ctx = _load_mep_and_context(project_root)
            mep, _ = with_rooms(ctx["mep"], ctx["rooms"])
            gas_configured = getattr(mep, "gas", None) is not None
            medgas_configured = getattr(mep, "medicalGas", None) is not None
            notes: list[str] = []

            mep_mod = mep
            if gas_configured:
                gas_upd = mep.gas.model_copy(
                    update={
                        **({"fuel": fuel} if fuel in ("naturalGas", "lpg") else {}),
                        **(
                            {"supplyPressureKpa": float(supply_pressure_kpa)}
                            if supply_pressure_kpa is not None
                            else {}
                        ),
                        **({"maxDropKpa": float(max_drop_kpa)} if max_drop_kpa is not None else {}),
                    }
                )
                mep_mod = mep.model_copy(update={"gas": gas_upd})
            elif fuel or supply_pressure_kpa or max_drop_kpa:
                gas_tmp = GasSystem(
                    fuel=fuel if fuel in ("naturalGas", "lpg") else "naturalGas",
                    supplyPressureKpa=float(supply_pressure_kpa) if supply_pressure_kpa else None,
                    maxDropKpa=float(max_drop_kpa) if max_drop_kpa else None,
                )
                mep_mod = mep.model_copy(update={"gas": gas_tmp})
                notes.append("No fuel gas appliances or pipes defined yet in 07 MEP (gas).")

            gas = gas_results(mep_mod, ctx["building"])
            medgas = medical_gas_results(mep_mod, ctx["rooms"])
            if not gas_configured and not medgas_configured and not notes:
                notes.append(
                    "Neither fuel gas nor medical gas systems are configured in 07 MEP yet."
                )
            return _finite(
                {
                    "gasConfigured": gas_configured,
                    "medicalGasConfigured": medgas_configured,
                    "gas": gas,
                    "medicalGas": medgas,
                    "notes": [
                        *notes,
                        *(gas.get("notes") or [] if gas else []),
                    ],
                    "problems": [
                        *pack_problems,
                        *ctx["problems"],
                    ],
                }
            )
    except Exception as error:  # noqa: BLE001
        return {"gas": None, "medicalGas": None, "notes": [], "problems": [_first_line(error)]}


# ────────────────────────────────────────── Documents ──────────────────────────────────────────


def _load_drawing_building(project_root: Path):
    from saengine.drawings.sheets.project import building_of
    from saengine.library.bim import BuildingModel
    from saengine.library.floorplan import FloorPlan
    from saengine.library.objects import ObjectLibrary
    from saengine.library.substructure import parse as parse_sub
    from saengine.pipeline.drawings import drawing_settings

    bim_text = _read_text(project_root / "06 BIM/bim.json")
    obj_text = _read_text(project_root / "04 Objects/objects.json")
    if not bim_text or not obj_text:
        raise ValueError(
            "06 BIM/bim.json and 04 Objects/objects.json are required for sheet views."
        )
    bim = BuildingModel.model_validate_json(bim_text)
    objects = ObjectLibrary.model_validate_json(obj_text)
    plan = None
    plan_text = _read_text(project_root / "05 Floor Plan/floor-plan.json")
    if plan_text:
        try:
            plan = FloorPlan.model_validate_json(plan_text)
        except ValueError:
            plan = None
    sub = None
    sub_text = _read_text(project_root / "09 Substructure/substructure.json")
    if sub_text:
        try:
            sub = parse_sub(sub_text, None)
        except ValueError:
            sub = None
    settings, title = drawing_settings(
        _read_text(project_root / "02 Project Settings/project-settings.json")
    )
    building = building_of(bim, objects, plan, sub)
    return building, settings, title


def _building_bounds_xy(building: Any) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for c in building.columns:
        xs.append(float(c.x))
        ys.append(float(c.y))
    for b in building.beams:
        xs.extend([float(b.start[0]), float(b.end[0])])
        ys.extend([float(b.start[1]), float(b.end[1])])
    for s in building.slabs:
        for p in s.boundary:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    if not xs or not ys:
        return (0.0, 0.0, 12000.0, 10000.0)
    return (
        round(min(xs) - 500.0, 1),
        round(min(ys) - 500.0, 1),
        round(max(xs) + 500.0, 1),
        round(max(ys) + 500.0, 1),
    )


def _parse_scope_boxes(
    raw: Any, bounds: tuple[float, float, float, float]
) -> tuple[list[Any], bool]:
    from saengine.drawings.sheets.documentation import ScopeBox

    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        items = [x for x in raw if isinstance(x, dict)]
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("["):
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [x for x in parsed if isinstance(x, dict)]
        else:
            for line in re.split(r"[;\n]+", text):
                part = line.strip()
                if not part or ":" not in part:
                    continue
                name, coords = part.split(":", 1)
                nums = [float(n.strip()) for n in coords.split(",") if n.strip()]
                if len(nums) == 4:
                    items.append({"name": name.strip(), "bounds": nums})
    if items:
        boxes = [
            ScopeBox(
                str(it.get("name") or f"Zone {i + 1}"),
                tuple(float(v) for v in it["bounds"][:4]),  # type: ignore[arg-type]
                tuple(str(l) for l in (it.get("levels") or [])),
            )
            for i, it in enumerate(items)
        ]
        return boxes, False
    x0, y0, x1, y1 = bounds
    xm = round((x0 + x1) / 2.0, 1)
    return [ScopeBox("West Zone", (x0, y0, xm, y1)), ScopeBox("East Zone", (xm, y0, x1, y1))], True


def _to_title_info(title_dict: dict[str, Any]) -> Any:
    from saengine.drawings.sheets.layout import Revision, TitleInfo

    revs_raw = title_dict.get("revisions") or []
    revs = [
        r if isinstance(r, Revision) else Revision(**r)
        for r in revs_raw
        if isinstance(r, (Revision, dict))
    ]
    fields = {
        k: v
        for k, v in title_dict.items()
        if k in TitleInfo.__dataclass_fields__ and k != "revisions"
    }
    return TitleInfo(**fields, revisions=revs)


def drawings_scope_boxes(
    project_root: str,
    *,
    scope_boxes: Any = None,
    size: str = "A1",
    scale: float = 100.0,
    prefix: str = "S-",
    write_files: bool = False,
    save_to_settings: bool = False,
) -> dict[str, Any]:
    """Build (and optionally write) dependent plan views cropped by scope boxes with matchlines."""
    from saengine.drawings.sheets.build import write_drawings
    from saengine.drawings.sheets.documentation import build_dependent_plans
    from saengine.report.clauses import in_force

    root = Path(project_root)
    try:
        with in_force(root) as pack_problems:
            building, settings, title_dict = _load_drawing_building(root)
            bounds = _building_bounds_xy(building)
            stored = settings.get("scopeBoxes") or []
            raw_spec = scope_boxes if scope_boxes not in (None, "", []) else stored
            boxes, auto_proposed = _parse_scope_boxes(raw_spec, bounds)
            title = _to_title_info(title_dict)
            plans = build_dependent_plans(
                building,
                boxes,
                size=str(size or "A1").upper(),
                scale=float(scale or 100.0),
                prefix=str(prefix or "S-"),
                title_info=title,
            )
            for p in plans:
                p.sheet.finish()
            written_paths: dict[str, str] = {}
            if write_files and plans:
                out_dir = root / "11 Exports/Drawings/Scope Boxes"
                written = write_drawings(
                    [p.sheet for p in plans], out_dir, pdf=False, png=False, clean=False
                )
                written_paths = {s["number"]: s["dxf"] for s in written.get("sheets") or []}

            if save_to_settings:
                s_path = root / "02 Project Settings/project-settings.json"
                if s_path.is_file():
                    s_raw = json.loads(s_path.read_text(encoding="utf-8"))
                    s_raw.setdefault("drawings", {})["scopeBoxes"] = [
                        {
                            "name": b.name,
                            "bounds": list(b.bounds),
                            **({"levels": list(b.levels)} if b.levels else {}),
                        }
                        for b in boxes
                    ]
                    _atomic_write(s_path, json.dumps(s_raw, indent="\t", ensure_ascii=False) + "\n")

            plan_rows = []
            for p in plans:
                matchlines = [
                    str(e.dxf.text)
                    for e in p.sheet.doc.modelspace().query("TEXT")
                    if "MATCHLINE" in str(getattr(e.dxf, "text", ""))
                ]
                plan_rows.append(
                    {
                        "sheetNumber": p.sheet.number,
                        "title": p.sheet.title,
                        "scopeBox": p.scope.name,
                        "level": p.level,
                        "scale": f"1:{int(scale)}",
                        "size": str(size).upper(),
                        "bounds": list(p.scope.bounds),
                        "matchlines": ", ".join(matchlines) if matchlines else "None",
                        "dxf": written_paths.get(p.sheet.number),
                    }
                )
            notes: list[str] = []
            if auto_proposed:
                notes.append(
                    "No scope boxes configured in Project Settings: auto-proposed West Zone and East Zone along mid-X."
                )
            return _finite(
                {
                    "buildingBounds": list(bounds),
                    "levels": [
                        {"id": lv.id, "name": lv.name, "elevation": lv.elevation}
                        for lv in building.levels
                    ],
                    "autoProposed": auto_proposed,
                    "scopeBoxes": [
                        {"name": b.name, "bounds": list(b.bounds), "levels": list(b.levels)}
                        for b in boxes
                    ],
                    "plans": plan_rows,
                    "notes": notes,
                    "problems": list(pack_problems),
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "plans": [],
            "scopeBoxes": [],
            "levels": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def drawings_callout(
    project_root: str,
    *,
    level: str | None = None,
    callout_number: str = "1",
    detail_sheet_number: str = "S-501",
    x0: float | None = None,
    y0: float | None = None,
    x1: float | None = None,
    y1: float | None = None,
    plan_scale: float = 100.0,
    detail_scale: float = 25.0,
    size: str = "A1",
    write_files: bool = False,
) -> dict[str, Any]:
    """Create a plan/section callout linking a parent framing plan to a zoomed detail sheet."""
    from saengine.drawings.sheets.build import write_drawings
    from saengine.drawings.sheets.documentation import create_callout
    from saengine.drawings.sheets.layout import Sheet
    from saengine.drawings.sheets.plans import framing_plan
    from saengine.report.clauses import in_force

    root = Path(project_root)
    try:
        with in_force(root) as pack_problems:
            building, _settings, title_dict = _load_drawing_building(root)
            if not building.levels:
                raise ValueError("No levels found in 06 BIM/bim.json.")
            lv = next((l for l in building.levels if l.id == level), building.levels[0])
            b = _building_bounds_xy(building)
            cx0 = float(x0) if x0 is not None else round(b[0] + (b[2] - b[0]) * 0.25, 1)
            cy0 = float(y0) if y0 is not None else round(b[1] + (b[3] - b[1]) * 0.25, 1)
            cx1 = float(x1) if x1 is not None else round(b[0] + (b[2] - b[0]) * 0.75, 1)
            cy1 = float(y1) if y1 is not None else round(b[1] + (b[3] - b[1]) * 0.75, 1)
            bounds = (cx0, cy0, cx1, cy1)

            title = _to_title_info(title_dict)
            psize = str(size or "A1").upper()
            pscale = float(plan_scale or 100.0)
            dscale = float(detail_scale or 25.0)
            parent_spec = framing_plan(building, lv, pscale)
            parent_sheet = Sheet("S-101", parent_spec.title, psize, pscale, title)
            parent_view = parent_sheet.view(parent_spec, *parent_sheet.area[:2])

            detail_spec = framing_plan(building, lv, dscale, bounds)
            detail_spec.title = f"Callout {callout_number} - {lv.name}"
            detail_sheet = Sheet(
                str(detail_sheet_number or "S-501"), detail_spec.title, psize, dscale, title
            )

            callout = create_callout(
                parent_view, bounds, detail_sheet, detail_spec, str(callout_number or "1")
            )
            parent_sheet.finish()
            detail_sheet.finish()

            parent_dxf = detail_dxf = None
            if write_files:
                out_dir = root / "11 Exports/Drawings/Callouts"
                written = write_drawings(
                    [parent_sheet, detail_sheet], out_dir, pdf=False, png=False, clean=False
                )
                sheets = written.get("sheets") or []
                if len(sheets) >= 2:
                    parent_dxf, detail_dxf = sheets[0]["dxf"], sheets[1]["dxf"]

            return _finite(
                {
                    "levels": [{"id": l.id, "name": l.name} for l in building.levels],
                    "buildingBounds": list(b),
                    "callout": {
                        "number": callout.number,
                        "reference": callout.reference,
                        "level": lv.id,
                        "bounds": list(bounds),
                        "detailSheet": detail_sheet.number,
                        "planScale": pscale,
                        "detailScale": dscale,
                        "parentDxf": parent_dxf,
                        "detailDxf": detail_dxf,
                    },
                    "notes": [
                        f"Created callout {callout.reference} on {lv.name} (1:{int(dscale)})."
                    ],
                    "problems": list(pack_problems),
                }
            )
    except Exception as error:  # noqa: BLE001
        return {"levels": [], "callout": None, "notes": [], "problems": [_first_line(error)]}


def _dxf_sheets(project_root: Path, sheet_filter: str | None = None) -> list[Path]:
    folder = project_root / "11 Exports/Drawings"
    if not folder.is_dir():
        return []
    dxfs = sorted(p for p in folder.glob("*.dxf") if p.is_file())
    if sheet_filter and sheet_filter.strip():
        needle = sheet_filter.strip().casefold()
        dxfs = [p for p in dxfs if needle in p.name.casefold()]
    return dxfs


def drawings_keynotes(project_root: str, *, sheet: str | None = None) -> dict[str, Any]:
    """Inspect keynote catalogue and keynotes actually tagged across generated drawing DXFs."""
    import ezdxf

    from saengine.drawings.sheets.keynotes import STARTER_KEYNOTES, load_keynotes, used_keynotes

    root = Path(project_root)
    try:
        custom = next(
            (
                p
                for p in (
                    root / "11 Exports/Drawings/keynotes.json",
                    root / "02 Project Settings/keynotes.json",
                )
                if p.is_file()
            ),
            STARTER_KEYNOTES,
        )
        catalogue = load_keynotes(custom)
        dxfs = _dxf_sheets(root, sheet)
        used_rows: list[dict[str, Any]] = []
        used_keys: set[str] = set()
        for path in dxfs:
            doc = ezdxf.readfile(str(path))
            for key in sorted(used_keynotes(doc)):
                used_keys.add(key)
                used_rows.append(
                    {
                        "key": key,
                        "description": catalogue.get(key, "(missing description)"),
                        "sheet": path.stem,
                        "known": key in catalogue,
                    }
                )
        cat_rows = [
            {"key": k, "description": v, "used": k in used_keys}
            for k, v in sorted(catalogue.items())
        ]
        notes: list[str] = []
        if not dxfs:
            notes.append(
                "No generated DXF sheets found in 11 Exports/Drawings yet: showing the active keynote catalogue."
            )
        return {
            "source": "project" if custom != STARTER_KEYNOTES else "starter",
            "totalCatalogue": len(cat_rows),
            "totalUsed": len(used_rows),
            "sheetsScanned": len(dxfs),
            "used": used_rows,
            "catalogue": cat_rows,
            "notes": notes,
            "problems": [],
        }
    except Exception as error:  # noqa: BLE001
        return {
            "used": [],
            "catalogue": [],
            "sheetsScanned": 0,
            "notes": [],
            "problems": [_first_line(error)],
        }


def drawings_legend(project_root: str, *, sheet: str | None = None) -> dict[str, Any]:
    """Scan generated DXF sheets for used linetypes, hatches, blocks/symbols and tags."""
    import ezdxf

    from saengine.drawings.sheets.documentation import documentation_legend

    root = Path(project_root)
    try:
        all_dxfs = _dxf_sheets(root)
        dxfs = _dxf_sheets(root, sheet)
        seen: dict[tuple[str, str], set[str]] = {}
        for path in dxfs:
            doc = ezdxf.readfile(str(path))
            tbl = documentation_legend(doc)
            for kind, name, _ in tbl.rows:
                seen.setdefault((str(kind), str(name)), set()).add(path.stem)
        items = [
            {
                "kind": k,
                "name": n,
                "sheetCount": len(sheets),
                "sheets": ", ".join(sorted(sheets)[:5]),
            }
            for (k, n), sheets in sorted(seen.items())
        ]
        notes: list[str] = []
        if not all_dxfs:
            notes.append(
                "No generated DXF sheets found in 11 Exports/Drawings: generate the drawing set first."
            )
        return {
            "sheetsScanned": len(dxfs),
            "availableSheets": [p.stem for p in all_dxfs],
            "items": items,
            "notes": notes,
            "problems": [],
        }
    except Exception as error:  # noqa: BLE001
        return {
            "sheetsScanned": 0,
            "availableSheets": [],
            "items": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def _collect_schedule_categories(
    project_root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Assemble queryable JSON category records from BIM, Substructure, Architecture and MEP."""
    categories: dict[str, list[dict[str, Any]]] = {
        "beams": [],
        "columns": [],
        "slabs": [],
        "walls": [],
        "footings": [],
        "rooms": [],
        "doors": [],
        "windows": [],
        "mepEquipment": [],
    }
    notes: list[str] = []

    bim_text = _read_text(project_root / "06 BIM/bim.json")
    obj_text = _read_text(project_root / "04 Objects/objects.json")
    if bim_text:
        try:
            bim = json.loads(bim_text)
        except ValueError:
            bim = {}
        types: dict[str, dict[str, Any]] = {}
        if obj_text:
            try:
                objs = json.loads(obj_text)
                types = {
                    o["id"]: o
                    for o in objs.get("objects") or []
                    if isinstance(o, dict) and o.get("id")
                }
            except ValueError:
                pass
        stories = {
            s["id"]: s for s in bim.get("stories") or [] if isinstance(s, dict) and s.get("id")
        }
        for el in bim.get("elements") or []:
            if not isinstance(el, dict):
                continue
            kind = el.get("kind")
            t = types.get(str(el.get("type") or ""), {})
            prof = t.get("profile") or {}
            if kind == "beam":
                s, e = el.get("start") or [0, 0], el.get("end") or [0, 0]
                length_mm = round(
                    math.hypot(float(e[0]) - float(s[0]), float(e[1]) - float(s[1])), 1
                )
                w = float(prof.get("xDim") or prof.get("overallWidth") or 300)
                d = float(prof.get("yDim") or prof.get("overallDepth") or 500)
                categories["beams"].append(
                    {
                        "id": str(el.get("id") or ""),
                        "story": str(el.get("story") or el.get("level") or ""),
                        "type": str(el.get("type") or ""),
                        "material": str(t.get("material") or ""),
                        "widthMm": w,
                        "depthMm": d,
                        "lengthMm": length_mm,
                        "volumeM3": round((w * d * length_mm) / 1e9, 3),
                    }
                )
            elif kind == "column":
                bot_z = float((stories.get(el.get("bottom")) or {}).get("elevation") or 0.0)
                top_z = float((stories.get(el.get("top")) or {}).get("elevation") or 3000.0)
                h_mm = round(max(top_z - bot_z, 0.0), 1)
                bx = float(
                    prof.get("xDim") or prof.get("overallWidth") or (2 * prof.get("radius", 150))
                )
                hy = float(prof.get("yDim") or prof.get("overallDepth") or bx)
                categories["columns"].append(
                    {
                        "id": str(el.get("id") or ""),
                        "bottom": str(el.get("bottom") or ""),
                        "top": str(el.get("top") or ""),
                        "type": str(el.get("type") or ""),
                        "material": str(t.get("material") or ""),
                        "widthMm": bx,
                        "depthMm": hy,
                        "heightMm": h_mm,
                        "areaMm2": round(bx * hy, 1),
                    }
                )
            elif kind == "slab":
                from shapely.geometry import Polygon

                pts = el.get("boundary") or []
                area_m2 = (
                    round(Polygon([(p[0], p[1]) for p in pts]).area / 1e6, 2)
                    if len(pts) >= 3
                    else 0.0
                )
                thick = float(t.get("thickness") or 150)
                categories["slabs"].append(
                    {
                        "id": str(el.get("id") or ""),
                        "story": str(el.get("story") or el.get("level") or ""),
                        "type": str(el.get("type") or ""),
                        "thicknessMm": thick,
                        "areaM2": area_m2,
                        "volumeM3": round(area_m2 * thick / 1000.0, 3),
                    }
                )
            elif kind == "wall":
                s, e = el.get("start") or [0, 0], el.get("end") or [0, 0]
                length_mm = round(
                    math.hypot(float(e[0]) - float(s[0]), float(e[1]) - float(s[1])), 1
                )
                thick = float(t.get("thickness") or 200)
                categories["walls"].append(
                    {
                        "id": str(el.get("id") or ""),
                        "bottom": str(el.get("bottom") or ""),
                        "top": str(el.get("top") or ""),
                        "type": str(el.get("type") or ""),
                        "thicknessMm": thick,
                        "lengthMm": length_mm,
                    }
                )
            elif kind == "footing":
                b = float(el.get("b") or prof.get("xDim") or 1500)
                l_dim = float(el.get("l") or prof.get("yDim") or 1500)
                d_dim = float(el.get("d") or 400)
                categories["footings"].append(
                    {
                        "id": str(el.get("id") or ""),
                        "kind": str(el.get("footingKind") or "isolated"),
                        "type": str(el.get("type") or ""),
                        "widthMm": b,
                        "lengthMm": l_dim,
                        "depthMm": d_dim,
                        "areaM2": round(b * l_dim / 1e6, 2),
                    }
                )
    else:
        notes.append("06 BIM/bim.json not present yet.")

    sub_text = _read_text(project_root / "09 Substructure/substructure.json")
    if sub_text:
        try:
            sub = json.loads(sub_text)
            for f in sub.get("foundations") or []:
                if not isinstance(f, dict):
                    continue
                b = float(f.get("width") or f.get("b") or 0)
                l_dim = float(f.get("length") or f.get("l") or 0)
                d_dim = float(f.get("thickness") or f.get("d") or 0)
                categories["footings"].append(
                    {
                        "id": str(f.get("id") or ""),
                        "kind": str(f.get("kind") or "footing"),
                        "type": str(f.get("column") or ""),
                        "widthMm": b,
                        "lengthMm": l_dim,
                        "depthMm": d_dim,
                        "areaM2": round(b * l_dim / 1e6, 2),
                    }
                )
        except ValueError:
            pass

    arch_text = _read_text(project_root / "05 Floor Plan/architecture.json")
    if arch_text:
        try:
            from shapely.geometry import Polygon

            from saengine.mep.rooms import read_room_inputs

            arch = json.loads(arch_text)
            door_types = {
                t["id"]: t
                for t in arch.get("doorTypes") or []
                if isinstance(t, dict) and t.get("id")
            }
            win_types = {
                t["id"]: t
                for t in arch.get("windowTypes") or []
                if isinstance(t, dict) and t.get("id")
            }
            room_inputs, _room_err = read_room_inputs(project_root, None)
            seen_rooms: set[str] = set()
            if room_inputs is not None:
                for story_id, sr in room_inputs.stories.items():
                    for rm in sr.rooms:
                        seen_rooms.add(rm.id)
                        categories["rooms"].append(
                            {
                                "id": rm.id,
                                "name": rm.label or rm.name or rm.id,
                                "story": story_id,
                                "use": str(rm.hvacUse or rm.use or ""),
                                "areaM2": round(float(rm.area), 2),
                            }
                        )
            for r in arch.get("rooms") or []:
                if not isinstance(r, dict) or str(r.get("id") or "") in seen_rooms:
                    continue
                pts = r.get("boundary") or []
                area_m2 = (
                    round(Polygon([(p[0], p[1]) for p in pts]).area / 1e6, 2)
                    if len(pts) >= 3
                    else 0.0
                )
                categories["rooms"].append(
                    {
                        "id": str(r.get("id") or ""),
                        "name": str(r.get("name") or r.get("id") or ""),
                        "story": str(r.get("story") or ""),
                        "use": str(r.get("use") or r.get("hvacUse") or r.get("occupancy") or ""),
                        "areaM2": area_m2,
                    }
                )
            for d in arch.get("doors") or []:
                if isinstance(d, dict):
                    dt = door_types.get(str(d.get("type") or ""), {})
                    categories["doors"].append(
                        {
                            "id": str(d.get("id") or ""),
                            "type": str(d.get("type") or ""),
                            "wall": str(d.get("wall") or ""),
                            "widthMm": float(dt.get("width") or d.get("width") or 900),
                            "heightMm": float(dt.get("height") or d.get("height") or 2100),
                        }
                    )
            for w in arch.get("windows") or []:
                if isinstance(w, dict):
                    wt = win_types.get(str(w.get("type") or ""), {})
                    categories["windows"].append(
                        {
                            "id": str(w.get("id") or ""),
                            "type": str(w.get("type") or ""),
                            "wall": str(w.get("wall") or ""),
                            "widthMm": float(wt.get("width") or w.get("width") or 1200),
                            "heightMm": float(wt.get("height") or w.get("height") or 1200),
                        }
                    )
        except ValueError:
            pass

    mep_text = _read_text(project_root / "07 MEP/mep.json")
    if mep_text:
        try:
            mep = json.loads(mep_text)
            for eq in mep.get("equipment") or []:
                if isinstance(eq, dict):
                    categories["mepEquipment"].append(
                        {
                            "id": str(eq.get("id") or ""),
                            "name": str(eq.get("name") or eq.get("kind") or ""),
                            "kind": str(eq.get("kind") or ""),
                            "story": str(eq.get("story") or ""),
                            "weightKn": float(eq.get("operatingWeight") or 0.0),
                        }
                    )
        except ValueError:
            pass

    return categories, notes


def drawings_schedule_categories(project_root: str) -> dict[str, Any]:
    """Available schedule categories, item counts and queryable fields for Schedule Builder."""
    try:
        cats, notes = _collect_schedule_categories(Path(project_root))
        out = []
        labels = {
            "beams": "Structural Beams",
            "columns": "Structural Columns",
            "slabs": "Floor & Roof Slabs",
            "walls": "Structural Walls",
            "footings": "Foundations / Footings",
            "rooms": "Architectural Rooms",
            "doors": "Doors",
            "windows": "Windows",
            "mepEquipment": "MEP Equipment",
        }
        for key, rows in cats.items():
            fields: list[dict[str, Any]] = []
            if rows:
                sample = rows[0]
                fields = [
                    {
                        "key": k,
                        "title": k,
                        "numeric": isinstance(v, int | float) and not isinstance(v, bool),
                    }
                    for k, v in sample.items()
                ]
            out.append(
                {"id": key, "label": labels.get(key, key), "count": len(rows), "fields": fields}
            )
        return {"categories": out, "notes": notes, "problems": []}
    except Exception as error:  # noqa: BLE001
        return {"categories": [], "notes": [], "problems": [_first_line(error)]}


def drawings_schedule(
    project_root: str,
    definition: dict[str, Any],
    *,
    export_xlsx_path: str | None = None,
) -> dict[str, Any]:
    """Run :func:`saengine.drawings.sheets.schedule_builder.build_schedule` on project data."""
    from saengine.drawings.sheets.schedule_builder import build_schedule

    try:
        cats, notes = _collect_schedule_categories(Path(project_root))
        res = build_schedule(definition, cats)
        xlsx_path = None
        if export_xlsx_path:
            res.write_xlsx(export_xlsx_path)
            xlsx_path = str(export_xlsx_path)
        return _finite(
            {
                "title": res.title,
                "columns": res.columns,
                "rows": res.rows,
                "rowCount": len(res.rows),
                "csvText": res.csv_text(),
                "xlsxPath": xlsx_path,
                "notes": [*notes, *res.notes],
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "title": "Schedule",
            "columns": [],
            "rows": [],
            "rowCount": 0,
            "notes": [],
            "problems": [_first_line(error)],
        }


# ────────────────────────────────────────── Output / IFC ──────────────────────────────────────────


def bim_export_ifc_file(
    project_root: str,
    *,
    schema: str | None = None,
    structural_analysis: bool | None = None,
    include_georeferencing: bool | None = None,
    crs: str | None = None,
    include_connections: bool | None = None,
    out_path: str | None = None,
) -> dict[str, Any]:
    """Export the project building model to an ``.ifc`` file on disk with explicit options."""
    from saengine.rpc import handlers

    root = Path(project_root)
    try:
        bim_text = _read_text(root / "06 BIM/bim.json")
        obj_text = _read_text(root / "04 Objects/objects.json")
        if not bim_text or not obj_text:
            return {
                "problems": [
                    "06 BIM/bim.json and 04 Objects/objects.json are required before exporting IFC."
                ]
            }
        mat_text = _read_text(root / "03 Materials/materials.json")
        settings_text = _read_text(root / "02 Project Settings/project-settings.json")
        sub_text = _read_text(root / "09 Substructure/substructure.json")
        mep_text = _read_text(root / "07 MEP/mep.json")
        arch_text = _read_text(root / "05 Floor Plan/architecture.json")
        soil_text = _read_text(root / "01 Soil Report/soil-report.json")
        name = root.name
        for m in root.glob("*.saengine"):
            try:
                manifest = json.loads(m.read_text(encoding="utf-8"))
                name = str(manifest.get("name") or name)
            except (OSError, ValueError):
                pass
            break
        result = handlers.building_ifc(
            bim_text,
            obj_text,
            mat_text,
            name,
            substructure_text=sub_text,
            settings_text=settings_text,
            mep_text=mep_text,
            architecture_text=arch_text,
            rebar_root=str(root),
            schema=schema,
            include_structural_analysis=structural_analysis,
            soil_text=soil_text,
            include_connections=include_connections,
            include_georeferencing=include_georeferencing,
            crs=crs,
            project_root=str(root),
        )
        if not result.get("text"):
            return {
                "problems": list(result.get("problems") or ["IFC generation returned no content."])
            }
        safe_name = re.sub(r'[\\/:*?"<>|]+', "-", name) or "Project"
        target = Path(out_path) if out_path else root / "11 Exports/IFC" / f"{safe_name}.ifc"
        if target.is_dir():
            target = target / f"{safe_name}.ifc"
        _atomic_write(target, result["text"])
        return {
            "path": str(target),
            "schema": schema or "IFC4",
            "structuralAnalysis": bool(structural_analysis),
            "includeGeoreferencing": include_georeferencing
            if include_georeferencing is not None
            else True,
            "crs": crs or "",
            "elementCount": len(result.get("ids") or {}),
            "sizeBytes": target.stat().st_size,
            "skipped": list(result.get("skipped") or []),
            "notes": [f"Wrote {len(result.get('ids') or {})} IFC entity(ies) to {target}."],
            "problems": list(result.get("problems") or []),
        }
    except Exception as error:  # noqa: BLE001
        return {"problems": [_first_line(error)]}


def bim_diff_ifc(before_path: str, after_path: str) -> dict[str, Any]:
    """Semantic and geometric diff of two IFC revisions by ``GlobalId``."""
    from saengine.library.ifc_diff import diff_ifc

    try:
        before, after = Path(before_path), Path(after_path)
        if not before.is_file():
            return {"problems": [f"Before IFC file not found: {before_path}"]}
        if not after.is_file():
            return {"problems": [f"After IFC file not found: {after_path}"]}
        diff = diff_ifc(before, after)
        return _finite({**diff, "problems": []})
    except Exception as error:  # noqa: BLE001
        return {
            "counts": {},
            "changes": [],
            "added": [],
            "removed": [],
            "changed": [],
            "problems": [_first_line(error)],
        }


# ────────────────────────────────────────── Analyze / Validate & Verification ──────────────────────────────────────────


def project_validate_all(project_root: str) -> dict[str, Any]:
    """Validate every part of the project using :func:`saengine.pipeline.validate.validate_project`."""
    from saengine.pipeline.project import open_project
    from saengine.pipeline.validate import validate_project

    try:
        proj = open_project(project_root)
        parts = validate_project(proj)
        part_rows = [p.to_json() for p in parts]
        flat_problems = [
            {
                "part": p.part,
                "file": p.file,
                "severity": prob.get("severity", "error"),
                "path": prob.get("path", ""),
                "message": prob.get("message", ""),
            }
            for p in parts
            for prob in p.problems
        ]
        errors = sum(p.errors for p in parts)
        warnings = sum(len(p.problems) - p.errors for p in parts)
        return _finite(
            {
                "ok": errors == 0,
                "parts": part_rows,
                "problems": flat_problems,
                "summary": {
                    "parts": len(parts),
                    "ok": sum(1 for p in parts if p.state == "ok"),
                    "errors": errors,
                    "warnings": warnings,
                },
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "parts": [],
            "problems": [{"part": "project", "severity": "error", "message": _first_line(error)}],
            "summary": {},
        }


def verification_cases() -> dict[str, Any]:
    """List SAEngine verification benchmark cases."""
    from saengine.verification.cases import CASES

    return {
        "cases": [
            {
                "id": c.id,
                "title": c.title,
                "category": c.category,
                "fast": bool(getattr(c, "fast", False)),
                "description": c.description,
            }
            for c in CASES
        ]
    }


def verification_run(
    *,
    out_dir: str | None = None,
    ids: list[str] | None = None,
    fast_only: bool = True,
    pdf: bool = True,
) -> dict[str, Any]:
    """Run selected/fast verification cases and optionally compile ``verification-manual.pdf``."""
    from saengine.verification.run import _clean, render_pdf, run_all, write_json

    warnings: list[str] = []
    try:
        target_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="saengine-verify-"))
        target_dir.mkdir(parents=True, exist_ok=True)
        work_dir = target_dir / "work"
        cleaned_ids = [s.strip() for s in (ids or []) if s and s.strip()] or None
        data = _clean(
            run_all(work_dir, cleaned_ids, fast_only=bool(fast_only and cleaned_ids is None))
        )
        json_path = write_json(data, target_dir / "verification.json")
        pdf_path: str | None = None
        if pdf:
            try:
                pdf_bytes, typst_warnings = render_pdf(data)
                warnings.extend(typst_warnings)
                out_pdf = target_dir / "verification-manual.pdf"
                out_pdf.write_bytes(pdf_bytes)
                pdf_path = str(out_pdf)
            except Exception as pdf_err:  # noqa: BLE001
                warnings.append(f"PDF rendering skipped/failed: {_first_line(pdf_err)}")
        return _finite(
            {
                "meta": data.get("meta") or {},
                "summary": data.get("summary") or {},
                "cases": data.get("cases") or [],
                "jsonPath": str(json_path),
                "pdfPath": pdf_path,
                "warnings": warnings,
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "meta": {},
            "summary": {},
            "cases": [],
            "jsonPath": None,
            "pdfPath": None,
            "warnings": warnings,
            "problems": [_first_line(error)],
        }
