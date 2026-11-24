"""Shared IO, parsing and project-context helpers for Substructure / Foundations features."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from saengine.design.rc_detailing import concrete_modulus
from saengine.features import FeatureContext, FeatureInputError
from saengine.library.materials import Category, MaterialLibrary
from saengine.library.soil import Borehole, Layer, SoilReport, SptRecord
from saengine.library.substructure import Substructure
from saengine.library.substructure import parse as parse_substructure
from saengine.soil.profile import Profile
from saengine.substructure.context import Context, load_context
from saengine.substructure.earth_pressure import Layer as EpLayer
from saengine.substructure.earth_pressure import Soil as EpSoil


def require_root(ctx: FeatureContext, purpose: str = "this feature") -> Path:
    """Return the project root path or raise a clear FeatureInputError."""
    if ctx.root is None or not ctx.root.exists():
        raise FeatureInputError(f"Open a project folder before running {purpose}.")
    return ctx.root


def load_substructure_model(ctx: FeatureContext) -> Substructure:
    """Read and validate 09 Substructure/substructure.json (with building positions if present)."""
    raw = ctx.raw("substructure")
    if raw is None:
        raise FeatureInputError(
            "No substructure file (09 Substructure/substructure.json) found in this project."
        )
    building = None
    bim_raw = ctx.raw("bim")
    if bim_raw is not None:
        try:
            from saengine.library.bim import BuildingModel

            building = BuildingModel.model_validate(bim_raw)
        except ValueError:
            building = None
    try:
        return parse_substructure(json.dumps(raw), building)
    except ValueError as err:
        raise FeatureInputError(f"Invalid substructure data: {err}") from err


def load_substructure_context(ctx: FeatureContext) -> Context:
    """Load the full substructure Context for the open project."""
    root = require_root(ctx, "project foundation checks")
    try:
        return load_context(root)
    except (OSError, ValueError) as err:
        raise FeatureInputError(f"Cannot load project substructure context: {err}") from err


def require_loads(sub_ctx: Context) -> Any:
    """Return BaseLoads from the project analysis or raise a clear FeatureInputError."""
    if sub_ctx.loads is None:
        reason = (
            sub_ctx.no_loads or "No structural analysis reactions found in 08 FEM/model.results."
        )
        raise FeatureInputError(
            f"{reason} Run the structural analysis first, or supply loads directly in a calculator."
        )
    return sub_ctx.loads


def build_profile(
    ctx: FeatureContext,
    *,
    borehole_id: str = "",
    soil_type: str = "sand",
    gamma: float = 18.0,
    gamma_sat: float = 20.0,
    phi: float = 32.0,
    cu: float = 60.0,
    spt_n: float = 20.0,
    water_depth: float = 3.0,
    depth_m: float = 30.0,
    cc: float = 0.20,
    cr: float = 0.04,
    e0: float = 0.75,
    ocr: float = 1.5,
) -> tuple[Profile, str]:
    """Return a soil Profile from the project's soil report, or build one from the inputs."""
    report = ctx.soil()
    if report is not None and report.boreholes:
        bh = None
        if borehole_id.strip():
            bh = next(
                (b for b in report.boreholes if b.id.lower() == borehole_id.strip().lower()),
                None,
            )
            if bh is None:
                avail = ", ".join(b.id for b in report.boreholes)
                raise FeatureInputError(
                    f"Borehole '{borehole_id.strip()}' not found in soil report (available: {avail})."
                )
        else:
            bh = report.boreholes[0]
        return Profile(report, bh), f"Project borehole {bh.id}"

    depth_mm = max(float(depth_m), 5.0) * 1000.0
    wt_mm = max(float(water_depth), 0.0) * 1000.0
    is_cohesive = soil_type in ("clay", "silt")
    layer_kwargs: dict[str, Any] = {
        "top": 0.0,
        "bottom": depth_mm,
        "description": f"Input {soil_type} stratum",
        "soilType": soil_type,
        "unitWeight": float(gamma),
        "saturatedUnitWeight": max(float(gamma_sat), float(gamma)),
    }
    if is_cohesive:
        layer_kwargs.update(
            {
                "cu": float(cu),
                "plasticityIndex": 20.0 if soil_type == "clay" else 4.0,
                "liquidLimit": 42.0 if soil_type == "clay" else 28.0,
                "Cc": float(cc),
                "Cr": float(cr),
                "e0": float(e0),
                "OCR": float(ocr),
            }
        )
    else:
        layer_kwargs.update({"phi": float(phi), "finesContent": 10.0})

    n_val = max(1, round(float(spt_n)))
    spts: list[SptRecord] = []
    z_m = 1.5
    while z_m <= depth_m + 1e-6:
        spts.append(SptRecord(depth=round(z_m * 1000.0, 1), N=n_val))
        z_m += 1.5

    bh = Borehole(
        id="INPUT",
        x=0.0,
        y=0.0,
        groundLevel=0.0,
        waterTable=wt_mm,
        depth=depth_mm,
        layers=[Layer(**layer_kwargs)],
        spt=spts,
    )
    synthetic = SoilReport(boreholes=[bh])
    return Profile(synthetic, bh), "Input soil parameters"


def build_soil_column(
    ctx: FeatureContext,
    *,
    borehole_id: str = "",
    gamma: float = 18.0,
    gamma_sat: float = 20.0,
    phi: float = 30.0,
    cohesion: float = 0.0,
    water_depth: float = 10.0,
    surcharge: float = 10.0,
    depth_m: float = 15.0,
) -> EpSoil:
    """Build an earth-pressure Soil column from the soil report or manual inputs."""
    report = ctx.soil()
    if report is not None and report.boreholes and borehole_id != "__manual__":
        from saengine.substructure.earth_pressure import soil_column

        profiles = [Profile(report, b) for b in report.boreholes]
        if borehole_id.strip():
            matched = [p for p in profiles if p.id.lower() == borehole_id.strip().lower()]
            if not matched:
                avail = ", ".join(p.id for p in profiles)
                raise FeatureInputError(
                    f"Borehole '{borehole_id.strip()}' not found (available: {avail})."
                )
            profiles = matched
        x_mm, y_mm = profiles[0].x * 1000.0, profiles[0].y * 1000.0
        wt = water_depth if water_depth < 90.0 else None
        return soil_column(profiles, x_mm, y_mm, water_table=wt, surcharge=surcharge)

    g_sat = max(float(gamma_sat), float(gamma))
    layer: EpLayer = (
        0.0,
        max(float(depth_m), 1.0),
        float(gamma),
        g_sat,
        float(phi) if phi > 0 else None,
        float(cohesion),
        1.0,
    )
    wt = float(water_depth) if water_depth < 90.0 else None
    return EpSoil(
        layers=[layer],
        water_table=wt,
        surcharge=float(surcharge),
        source="Input backfill parameters",
    )


def project_concrete_rebar(
    ctx: FeatureContext, fc_input: float = 28.0, fy_input: float = 420.0
) -> tuple[float, float, float]:
    """Return (fc [MPa], fy [MPa], Ec [MPa]) from project materials when available, else inputs."""
    fc = float(fc_input)
    fy = float(fy_input)
    raw = ctx.raw("materials")
    if raw is not None:
        try:
            lib = MaterialLibrary.model_validate(raw)
            concs = [m for m in lib.materials if m.category == Category.CONCRETE and m.concrete]
            rebars = [m for m in lib.materials if m.category == Category.REBAR and m.rebar]
            if concs and fc_input <= 0:
                fc = float(concs[0].concrete.fc)  # type: ignore[union-attr]
            if rebars and fy_input <= 0:
                fy = float(rebars[0].rebar.fy)  # type: ignore[union-attr]
        except ValueError:
            pass
    ec, _ = concrete_modulus(fc)
    return fc, fy, ec


def export_file(ctx: FeatureContext, filename: str, content: str) -> Path:
    """Write an output file inside 09 Substructure/exports/ and return its path."""
    root = require_root(ctx, "export")
    out_dir = root / "09 Substructure" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename
    target.write_text(content, encoding="utf-8")
    return target


def export_bytes(ctx: FeatureContext, filename: str, data: bytes) -> Path:
    """Write binary output (e.g. DXF) inside 09 Substructure/exports/ and return its path."""
    root = require_root(ctx, "export")
    out_dir = root / "09 Substructure" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename
    target.write_bytes(data)
    return target


def parse_pairs(text_value: str, label: str = "Pairs") -> list[tuple[float, float]]:
    """Parse 'x1,y1; x2,y2; ...' or newline-separated pairs into a list of (float, float)."""
    chunks = [c.strip() for c in re.split(r"[;\n]+", text_value.strip()) if c.strip()]
    if not chunks:
        raise FeatureInputError(f"{label}: enter at least one numeric pair (e.g. '0,0; 500,3.2').")
    pairs: list[tuple[float, float]] = []
    for chunk in chunks:
        parts = [p for p in re.split(r"[,\s]+", chunk.strip()) if p]
        if len(parts) != 2:
            raise FeatureInputError(f"{label}: expected two numbers in '{chunk}'.")
        try:
            pairs.append((float(parts[0]), float(parts[1])))
        except ValueError as err:
            raise FeatureInputError(f"{label}: non-numeric value in '{chunk}'.") from err
    return pairs


def parse_floats(text_value: str, label: str = "Values") -> list[float]:
    """Parse comma/semicolon/whitespace separated floats."""
    parts = [p for p in re.split(r"[,;\s]+", text_value.strip()) if p]
    if not parts:
        raise FeatureInputError(f"{label}: enter one or more numeric values.")
    out: list[float] = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError as err:
            raise FeatureInputError(f"{label}: '{p}' is not a valid number.") from err
    return out
