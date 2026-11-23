"""Shared IO, model/results loading, parsing, and export helpers for FEM features."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.features import FeatureContext, FeatureInputError
from saengine.report.clauses import in_force


def require_root(ctx: FeatureContext, purpose: str = "this feature") -> Path:
    """Return the open project root Path or raise FeatureInputError."""
    if ctx.root is None or not ctx.root.exists():
        raise FeatureInputError(f"Open a project folder before running {purpose}.")
    return ctx.root


def load_settings(ctx: FeatureContext) -> Any:
    """Return ProjectSettings from the open project or defaults."""
    return ctx.settings()


def load_bim(ctx: FeatureContext) -> Any | None:
    """Return validated BuildingModel from 06 BIM/bim.json, or None."""
    raw = ctx.raw("bim")
    if raw is None:
        return None
    from saengine.library.bim import BuildingModel

    try:
        return BuildingModel.model_validate(raw)
    except ValueError:
        return None


def load_objects(ctx: FeatureContext) -> tuple[Any | None, dict[str, Any]]:
    """Return (ObjectLibrary, {id: ObjectType}) from 04 Objects/objects.json."""
    raw = ctx.raw("objects")
    if raw is None:
        return None, {}
    from saengine.library.objects import ObjectLibrary

    try:
        lib = ObjectLibrary.model_validate(raw)
        return lib, {obj.id: obj for obj in lib.objects}
    except ValueError:
        return None, {}


def load_materials(ctx: FeatureContext) -> tuple[Any | None, dict[str, Any]]:
    """Return (MaterialLibrary, {id: Material}) from 03 Materials/materials.json."""
    raw = ctx.raw("materials")
    if raw is None:
        return None, {}
    from saengine.library.materials import MaterialLibrary

    try:
        lib = MaterialLibrary.model_validate(raw)
        return lib, {mat.id: mat for mat in lib.materials}
    except ValueError:
        return None, {}


def optional_osmodel(ctx: FeatureContext) -> tuple[Path | None, dict[str, Any] | None]:
    """Return (path, parsed dict) for 08 FEM/model.osmodel if present, else (None, None)."""
    if ctx.root is None or not ctx.root.exists():
        return None, None
    for rel in ("08 FEM/model.osmodel", "08 Analysis/model.osmodel"):
        path = ctx.root / rel
        if path.is_file():
            try:
                return path, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return path, None
    return None, None


def require_osmodel(ctx: FeatureContext) -> tuple[Path, dict[str, Any]]:
    """Return (path, parsed dict) for 08 FEM/model.osmodel or raise FeatureInputError."""
    require_root(ctx, "reading the analysis model")
    path, model = optional_osmodel(ctx)
    if path is None or model is None:
        raise FeatureInputError("Derive the analysis model first (08 FEM/model.osmodel not found).")
    return path, model


def results_dir(ctx: FeatureContext) -> Path | None:
    """Return the existing results directory (08 FEM/model.results) if it has a manifest."""
    if ctx.root is None or not ctx.root.exists():
        return None
    for rel in ("08 FEM/model.results", "08 Analysis/model.results"):
        folder = ctx.root / rel
        manifest = folder / "manifest.json"
        if folder.is_dir() and manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("cases"):
                    return folder
            except (OSError, ValueError):
                continue
    return None


def require_results(ctx: FeatureContext) -> tuple[Path, Path]:
    """Return (results_dir, model_path) or raise FeatureInputError('Run the analysis first.')."""
    out_dir = results_dir(ctx)
    model_path, _ = optional_osmodel(ctx)
    if out_dir is None:
        raise FeatureInputError("Run the analysis first.")
    if model_path is None:
        model_path = out_dir.parent / "model.osmodel"
    return out_dir, model_path


def load_manifest(out_dir: Path) -> dict[str, Any]:
    """Read manifest.json from ``out_dir``."""
    try:
        return json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError(f"Cannot read analysis manifest: {exc}") from exc


def require_cfd_results(ctx: FeatureContext) -> dict[str, Any]:
    """Load 08 FEM/cfd-wind/results.json or raise FeatureInputError."""
    from saengine.fem.cfd_wind import RESULTS, post

    if ctx.root is None or not ctx.root.exists():
        raise FeatureInputError("Run the analysis first.")
    data = post.read_results(ctx.root / RESULTS)
    if data is None or not data.get("directions"):
        raise FeatureInputError("Run the analysis first.")
    return data


def load_stm_file(ctx: FeatureContext) -> list[Any]:
    """Return list of StmModel from 08 FEM/strut-and-tie.json when present, else []."""
    if ctx.root is None or not ctx.root.exists():
        return []
    from saengine.library.strut_and_tie import FILE_NAME, StrutAndTieFile

    for folder in ("08 FEM", "08 Analysis"):
        path = ctx.root / folder / FILE_NAME
        if path.is_file():
            try:
                parsed = StrutAndTieFile.model_validate_json(path.read_text(encoding="utf-8"))
                return list(parsed.models)
            except (OSError, ValueError):
                return []
    return []


def resolve_stm_model(
    ctx: FeatureContext,
    template_kind: str = "deepBeam",
    params: dict[str, float] | None = None,
) -> tuple[Any, str]:
    """Return (StmModel, source_label) from project file or template."""
    from saengine.design import stm_model

    models = load_stm_file(ctx)
    if models and template_kind in ("project", "auto", ""):
        return models[0], "Project 08 FEM/strut-and-tie.json"
    if template_kind == "project":
        raise FeatureInputError("Create a strut-and-tie model first (08 FEM/strut-and-tie.json).")
    if models and template_kind == "fromProject":
        return models[0], "Project 08 FEM/strut-and-tie.json"
    kind = template_kind if template_kind in stm_model.TEMPLATES else "deepBeam"
    return stm_model.template(kind, params or {}), f"Template ({kind})"


def building_height_m(
    building: Any | None = None,
    osmodel: dict[str, Any] | None = None,
    fallback: float = 12.0,
) -> float:
    """Estimate building height [m] from BIM stories, osmodel nodes, or fallback."""
    if building is not None and getattr(building, "stories", None):
        elevs = [float(getattr(s, "elevation", 0.0) or 0.0) for s in building.stories]
        tops = [
            float(getattr(s, "elevation", 0.0) or 0.0) + float(getattr(s, "height", 0.0) or 0.0)
            for s in building.stories
        ]
        peak = max(elevs + tops)
        base = min(elevs)
        span = peak - base
        if span > 0:
            return span / 1000.0 if peak > 200.0 else span
    if osmodel and osmodel.get("nodes"):
        zs = [float(n["coords"][2]) for n in osmodel["nodes"] if len(n.get("coords") or []) >= 3]
        if zs:
            span = max(zs) - min(zs)
            if span > 0:
                return span
    return fallback


def building_plan_dims_m(
    building: Any | None = None,
    osmodel: dict[str, Any] | None = None,
    fallback: tuple[float, float] = (18.0, 12.0),
) -> tuple[float, float]:
    """Return (width_x_m, depth_y_m) from BIM elements or osmodel nodes."""
    xs: list[float] = []
    ys: list[float] = []
    if building is not None:
        for el in getattr(building, "elements", None) or []:
            pos = getattr(el, "position", None)
            if pos and len(pos) >= 2:
                xs.append(float(pos[0]) / 1000.0)
                ys.append(float(pos[1]) / 1000.0)
            for key in ("start", "end"):
                pt = getattr(el, key, None)
                if pt and len(pt) >= 2:
                    xs.append(float(pt[0]) / 1000.0)
                    ys.append(float(pt[1]) / 1000.0)
    if not xs and osmodel:
        for n in osmodel.get("nodes", []):
            c = n.get("coords") or []
            if len(c) >= 2:
                xs.append(float(c[0]))
                ys.append(float(c[1]))
    if len(xs) >= 2 and len(ys) >= 2:
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        if dx > 0.5 and dy > 0.5:
            return dx, dy
    return fallback


def site_params(settings: Any) -> tuple[str, float, float, float, float, str]:
    """Return (site_class, z_val, wind_speed_ms, r_factor, importance, exposure)."""
    from saengine.fem import seismic_design

    site = getattr(settings, "site", None)
    occ = getattr(settings, "occupancy", None)
    seis = getattr(settings, "seismic", None)
    wind = getattr(settings, "wind", None)

    site_class = str(getattr(site, "siteClass", None) or "SD")
    z_coeff = getattr(site, "zoneCoefficient", None)
    if z_coeff is None:
        try:
            z_coeff = seismic_design.peak_ground_acceleration(settings)
        except Exception:  # noqa: BLE001
            z_coeff = 0.2
    try:
        z_val = float(z_coeff) if z_coeff is not None else 0.2
    except (TypeError, ValueError):
        z_val = 0.2

    wind_speed = getattr(site, "windSpeed", None)
    try:
        vb = float(wind_speed) if wind_speed is not None else 44.0
    except (TypeError, ValueError):
        vb = 44.0

    r_val = getattr(seis, "r", None)
    try:
        r_fac = float(r_val) if r_val is not None else 8.0
    except (TypeError, ValueError):
        r_fac = 8.0

    cat = str(getattr(occ, "category", None) or "II")
    imp = {"I": 0.85, "II": 1.0, "III": 1.15, "IV": 1.25}.get(cat, 1.0)
    exp = str(getattr(wind, "exposure", None) or "B")
    return site_class, z_val, vb, r_fac, imp, exp


def concrete_rebar_defaults(ctx: FeatureContext) -> tuple[float, float]:
    """Return (fc_mpa, fy_mpa) from project materials or sensible defaults."""
    _, mats = load_materials(ctx)
    fc, fy = 28.0, 420.0
    for mat in mats.values():
        if getattr(mat, "concrete", None) is not None and getattr(mat.concrete, "fc", None):
            fc = float(mat.concrete.fc)
            break
    for mat in mats.values():
        if getattr(mat, "rebar", None) is not None and getattr(mat.rebar, "fy", None):
            fy = float(mat.rebar.fy)
            break
    return fc, fy


def steel_defaults(ctx: FeatureContext) -> tuple[float, float]:
    """Return (fy_mpa, fu_mpa) from project materials or sensible defaults."""
    _, mats = load_materials(ctx)
    fy, fu = 250.0, 410.0
    for mat in mats.values():
        if getattr(mat, "steel", None) is not None and getattr(mat.steel, "fy", None):
            fy = float(mat.steel.fy)
            fu = float(getattr(mat.steel, "fu", None) or 1.25 * fy)
            break
    return fy, fu


def export_fem_file(ctx: FeatureContext, filename: str, content: str | bytes) -> Path:
    """Write an export file into ``08 FEM/exports/<filename>`` and return its path."""
    root = require_root(ctx, "exporting FEM outputs")
    target = root / "08 FEM" / "exports" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def parse_numbers(raw: str, label: str = "Values") -> list[float]:
    """Parse comma, semicolon, or whitespace separated numbers."""
    tokens = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
    if not tokens:
        raise FeatureInputError(f"Enter at least one numeric value for {label}.")
    out: list[float] = []
    for tok in tokens:
        try:
            val = float(tok)
        except ValueError as exc:
            raise FeatureInputError(f"{label}: {tok!r} is not a valid number.") from exc
        if not math.isfinite(val):
            raise FeatureInputError(f"{label}: values must be finite.")
        out.append(val)
    return out


def parse_pairs(raw: str, label: str = "Pairs") -> list[tuple[float, float]]:
    """Parse ``x, y`` numeric pairs from lines or semicolon-separated text."""
    pairs: list[tuple[float, float]] = []
    for chunk in re.split(r"[\r\n;]+", raw.strip()):
        s = chunk.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[\s,]+", s) if p]
        if len(parts) < 2:
            raise FeatureInputError(f"{label}: each entry needs two numbers, got {s!r}.")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise FeatureInputError(f"{label}: invalid number in {s!r}.") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            raise FeatureInputError(f"{label}: values must be finite.")
        pairs.append((x, y))
    if not pairs:
        raise FeatureInputError(f"Enter at least one pair for {label}.")
    return pairs


def parse_series(raw: str, dt: float = 0.02, label: str = "Signal") -> tuple[float, np.ndarray]:
    """Parse a 1D signal (comma/space values) or ``t, y`` pairs into (dt, y_array)."""
    if dt <= 0:
        raise FeatureInputError("Time step dt must be positive.")
    text = raw.strip()
    if ";" in text or ("\n" in text and "," in text):
        pairs = parse_pairs(text, label)
        ts = np.array([p[0] for p in pairs], dtype=float)
        ys = np.array([p[1] for p in pairs], dtype=float)
        dt_eff = float(np.median(np.diff(ts))) if len(ts) > 1 and np.all(np.diff(ts) > 0) else dt
        return dt_eff, ys
    vals = parse_numbers(text, label)
    return float(dt), np.array(vals, dtype=float)


def active_pack_name(ctx: FeatureContext) -> str:
    """Return active code pack display name inside ``in_force``."""
    with in_force(ctx.root):
        return str(code_context.code_name())


def format_json(data: Any) -> str:
    """Serialize data as formatted JSON."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n"
