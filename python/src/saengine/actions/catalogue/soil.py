"""Soil report actions (01 Soil Report): boreholes, their layers and SPT records as the log
sheet gives them, and the allowable bearing pressure override of the footing design. Entries are
checked by the soil report's model (:mod:`saengine.library.soil`)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._util import Params, fmt
from saengine.actions.errors import refuse
from saengine.actions.paths import SETTINGS, SOIL
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView


def _report(view: ProjectView) -> dict[str, Any]:
    """The soil report to edit; a new (empty) report for a missing file or the placeholder."""
    from saengine.library.soil import SoilReport

    data = view.part(SOIL, None)
    if not isinstance(data, dict) or data.get("schema") != "saengine.soilReport/1":
        data = SoilReport().model_dump(mode="json", by_alias=True, exclude_none=True)
    return data


def _borehole(report: dict[str, Any], borehole_id: str) -> dict[str, Any]:
    for b in report.get("boreholes") or []:
        if b.get("id") == borehole_id:
            return b
    known = ", ".join(b.get("id", "?") for b in report.get("boreholes") or []) or "none yet"
    refuse(
        f"There is no borehole '{borehole_id}' (the boreholes: {known}).", "borehole", borehole_id
    )
    raise AssertionError  # pragma: no cover


class BoreholeParams(Params):
    id: str | None = Field(default=None, description="E.g. BH-1; default: the next free BH-n.")
    x: float = Field(description="Position in the project's plan [mm].")
    y: float = Field(description="Position in the project's plan [mm].")
    groundLevel: float | None = Field(default=None, description="Ground level at the hole [mm].")
    waterTable: float | None = Field(
        default=None, description="Depth of the water table below the ground [mm]."
    )
    depth: float | None = Field(default=None, description="Depth drilled [mm].")
    date: str | None = None
    method: str | None = None


@action(
    "soil.borehole.add",
    summary="Add a borehole to the soil report at a plan position.",
    params=BoreholeParams,
    parts=("soil",),
    kind="edit",
    example={"x": 0, "y": 0, "waterTable": 2000, "depth": 15000},
)
def soil_borehole_add(view: ProjectView, p: BoreholeParams) -> ActionResult:
    report = _report(view)
    holes = report.setdefault("boreholes", [])
    ids = {b.get("id") for b in holes}
    hole_id = p.id
    if hole_id is None:
        n = 1
        while f"BH-{n}" in ids:
            n += 1
        hole_id = f"BH-{n}"
    elif hole_id in ids:
        refuse(f"There is a borehole '{hole_id}' already.", "id", hole_id)
    entry = {"id": hole_id, **p.model_dump(exclude={"id"}, exclude_none=True)}
    holes.append(entry)
    view.put(SOIL, report)
    return ActionResult(
        message=f"Borehole {hole_id} added at ({fmt(p.x)}, {fmt(p.y)}) mm.", created=[hole_id]
    )


class LayerParams(Params):
    borehole: str = Field(description="Borehole id.")
    top: float = Field(description="Depth of the top below the borehole's ground [mm].")
    bottom: float = Field(description="Depth of the bottom [mm].")
    soilType: Literal["clay", "silt", "sand", "gravel", "organic", "fill", "rock"]
    description: str = ""
    uscs: str | None = Field(default=None, description="USCS group, e.g. CL, SM.")
    unitWeight: float | None = Field(default=None, description="[kN/m³]")
    cu: float | None = Field(default=None, description="Undrained shear strength [kPa].")
    c: float | None = Field(default=None, description="Cohesion c' [kPa].")
    phi: float | None = Field(default=None, description="Friction angle [°].")
    more: dict[str, Any] = Field(
        default_factory=dict, description="Other fields of the layer (the soil report's names)."
    )


@action(
    "soil.layer.add",
    summary="Add a soil layer (stratum) to a borehole's log.",
    params=LayerParams,
    parts=("soil",),
    kind="edit",
    example={"borehole": "BH-1", "top": 0, "bottom": 3000, "soilType": "clay", "cu": 40},
)
def soil_layer_add(view: ProjectView, p: LayerParams) -> ActionResult:
    if p.bottom <= p.top:
        refuse(
            f"The layer's bottom ({fmt(p.bottom)} mm) must be below its top ({fmt(p.top)} mm).",
            "bottom",
            p.bottom,
        )
    report = _report(view)
    hole = _borehole(report, p.borehole)
    layers = hole.setdefault("layers", [])
    for other in layers:
        if p.top < float(other.get("bottom", 0)) and float(other.get("top", 0)) < p.bottom:
            refuse(
                f"The layer {fmt(p.top)}-{fmt(p.bottom)} mm overlaps the layer "
                f"{fmt(other['top'])}-{fmt(other['bottom'])} mm of {p.borehole}.",
                "top",
                p.top,
            )
    entry = {**p.model_dump(exclude={"borehole", "more"}, exclude_none=True), **p.more}
    layers.append(entry)
    layers.sort(key=lambda layer: float(layer.get("top", 0)))
    view.put(SOIL, report)
    return ActionResult(
        message=f"{p.soilType.capitalize()} layer {fmt(p.top)}-{fmt(p.bottom)} mm added to "
        f"{p.borehole}."
    )


class SptParams(Params):
    borehole: str = Field(description="Borehole id.")
    depth: float = Field(description="Depth of the test below the borehole's ground [mm].")
    N: int | None = Field(default=None, description="Field blow count [blows/300 mm].")
    seat: int | None = Field(default=None, description="Blows for the first 150 mm.")
    N1: int | None = Field(default=None, description="Blows for the second 150 mm.")
    N2: int | None = Field(default=None, description="Blows for the third 150 mm.")
    more: dict[str, Any] = Field(default_factory=dict, description="Other fields of the record.")


@action(
    "soil.spt.add",
    summary="Add a standard penetration test record (N, or the 150 mm increments) to a borehole.",
    params=SptParams,
    parts=("soil",),
    kind="edit",
    example={"borehole": "BH-1", "depth": 1500, "N": 8},
)
def soil_spt_add(view: ProjectView, p: SptParams) -> ActionResult:
    report = _report(view)
    hole = _borehole(report, p.borehole)
    records = hole.setdefault("spt", [])
    if any(abs(float(r.get("depth", -1)) - p.depth) < 1e-6 for r in records):
        refuse(f"{p.borehole} has an SPT record at {fmt(p.depth)} mm already.", "depth", p.depth)
    records.append({**p.model_dump(exclude={"borehole", "more"}, exclude_none=True), **p.more})
    records.sort(key=lambda r: float(r.get("depth", 0)))
    view.put(SOIL, report)
    n = f"N {p.N}" if p.N is not None else "the increments"
    return ActionResult(message=f"SPT at {fmt(p.depth)} mm ({n}) added to {p.borehole}.")


class BearingParams(Params):
    value: float | None = Field(
        description="Net allowable bearing pressure qa [kPa] for every footing; null: take qa "
        "per footing from the soil report again."
    )


@action(
    "soil.allowable_bearing.set",
    summary="Set the net allowable bearing pressure qa used for every footing (when there is "
    "no soil report, or to override it); null to use the soil report's again.",
    params=BearingParams,
    parts=("settings",),
    kind="edit",
    example={"value": 150},
)
def soil_allowable_bearing_set(view: ProjectView, p: BearingParams) -> ActionResult:
    data = view.part(SETTINGS)
    foundation = dict(data.get("foundation") or {})
    if p.value is None:
        foundation.pop("allowableBearing", None)
    else:
        foundation["allowableBearing"] = p.value
    data["foundation"] = foundation
    view.put(SETTINGS, data)
    return ActionResult(
        message="The footings take qa from the soil report."
        if p.value is None
        else f"Allowable bearing pressure qa {fmt(p.value)} kPa for every footing."
    )
