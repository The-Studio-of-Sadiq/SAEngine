"""Shared soil feature helpers: project data, profile rows and deterministic exports."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features._soil_feature_catalog import FEATURES


def register_tab(
    tab: str,
    handler: Callable[[str, FeatureContext, dict[str, Any]], dict[str, Any]],
    *,
    requires_project: Callable[[str], bool] | None = None,
    fields: Callable[[str], list[Any]] | None = None,
) -> None:
    """Register one generated Python runner for each exact batch entry."""
    for item in FEATURES[tab]:
        feature_id = item["id"]

        def run(
            ctx: FeatureContext, values: dict[str, Any], fid: str = feature_id
        ) -> dict[str, Any]:
            return handler(fid, ctx, values)

        run.__name__ = re.sub(r"\W+", "_", feature_id)
        run.__doc__ = item["help"]
        feature(
            feature_id,
            item["title"],
            part="soil",
            fields=fields(feature_id) if fields else common_fields(feature_id),
            help=item["help"],
            requires_project=requires_project(feature_id) if requires_project else True,
        )(run)


def common_fields(feature_id: str) -> list[Any]:
    """Useful panel inputs shared by soil analyses, in SI units."""
    fields: list[Any] = [text("boreholeId", "Borehole ID", "")]
    key = feature_id.lower()
    if any(word in key for word in ("depth", "slice", "datum", "dissipation", "pressureprofile")):
        fields.append(number("depthM", "Depth [m]", 5.0, unit="m", min=0))
    if any(word in key for word in ("width", "footing", "bearing", "raft", "spring", "settlement")):
        fields.append(number("widthM", "Footing width [m]", 2.0, unit="m", min=0.1))
    if any(word in key for word in ("surcharge", "load", "pressure", "raft")):
        fields.append(number("pressureKpa", "Applied pressure [kPa]", 100.0, unit="kPa", min=0))
    if "magnitude" in key or "liquefaction" in key or "seismic" in key or "arias" in key:
        fields.extend(
            [
                number("magnitude", "Moment magnitude", 7.5, min=4.0, max=9.5),
                number("pgaG", "Peak ground acceleration [g]", 0.25, unit="g", min=0.01, max=2),
            ]
        )
    if any(word in key for word in ("wall", "earth", "slope", "friction", "backfill")):
        fields.extend(
            [
                number("heightM", "Height [m]", 4.0, unit="m", min=0.1),
                number("phiDeg", "Effective friction angle [°]", 30.0, unit="°", min=0, max=50),
            ]
        )
    if any(
        word in key for word in ("sulfate", "sulphate", "chloride", "ph", "organic", "aggressivity")
    ):
        fields.append(text("sampleNumber", "Sample number", ""))
    return fields


def require_report(ctx: FeatureContext) -> Any:
    report = ctx.soil()
    if report is None:
        raise FeatureInputError("Open a project with a valid Soil Report and borehole data first.")
    return report


def borehole(report: Any, identifier: str | None = None) -> Any:
    if not report.boreholes:
        raise FeatureInputError("Add at least one borehole to the Soil Report first.")
    if identifier:
        found = next((bh for bh in report.boreholes if bh.id == identifier), None)
        if found is None:
            raise FeatureInputError(f"Borehole {identifier!r} is not in the Soil Report.")
        return found
    return report.boreholes[0]


def profile(report: Any, bh: Any) -> Any:
    from saengine.soil.profile import Profile

    return Profile(report, bh)


def profiles(report: Any) -> list[tuple[Any, Any]]:
    return [(bh, profile(report, bh)) for bh in report.boreholes]


def samples(report: Any) -> list[tuple[Any, Any, int]]:
    return [(bh, sample, i) for bh in report.boreholes for i, sample in enumerate(bh.samples)]


def layer_rows(report: Any, bh: Any | None = None) -> list[dict[str, Any]]:
    selected = [bh] if bh is not None else report.boreholes
    rows: list[dict[str, Any]] = []
    for hole in selected:
        for i, layer in enumerate(hole.layers, 1):
            rows.append(
                {
                    "borehole": hole.id,
                    "layer": i,
                    "topM": layer.top / 1000,
                    "bottomM": layer.bottom / 1000,
                    "thicknessM": (layer.bottom - layer.top) / 1000,
                    "soilType": layer.soilType,
                    "uscs": layer.uscs,
                    "description": layer.description,
                    "cuKpa": layer.cu,
                    "phiDeg": layer.phi,
                    "unitWeightKnM3": layer.unitWeight,
                    "finesPct": layer.finesContent,
                    "plasticityIndexPct": layer.plasticityIndex,
                }
            )
    return rows


def spt_rows(report: Any, bh: Any | None = None) -> list[dict[str, Any]]:
    selected = [bh] if bh is not None else report.boreholes
    rows: list[dict[str, Any]] = []
    for hole in selected:
        prof = profile(report, hole)
        by_depth = {round(point.depth * 1000): point for point in prof.spt}
        for record in hole.spt:
            point = by_depth.get(round(record.depth))
            rows.append(
                {
                    "borehole": hole.id,
                    "depthM": record.depth / 1000,
                    "fieldN": record.blows,
                    "n60": point.n60 if point else None,
                    "n160": point.n160 if point else None,
                    "effectiveStressKpa": point.sigma_v_eff if point else None,
                    "energyPct": point.energy if point else record.energyRatio,
                    "issues": "; ".join(record.issues),
                }
            )
    return rows


def sample_rows(report: Any) -> list[dict[str, Any]]:
    rows = []
    for bh, sample, i in samples(report):
        rows.append(
            {
                "borehole": bh.id,
                "sample": sample.number or f"S{i + 1}",
                "type": sample.type,
                "depthM": sample.depth / 1000,
                "depthToM": sample.depthTo / 1000 if sample.depthTo is not None else None,
                "recoveryPct": sample.recovery,
                "moisturePct": sample.moisture,
                "unitWeightKnM3": sample.unitWeight,
                "cuKpa": sample.cu,
                "phiDeg": sample.phi,
                "liquidLimitPct": sample.liquidLimit,
                "plasticLimitPct": sample.plasticLimit,
                "issues": "; ".join(sample.issues),
            }
        )
    return rows


def require_layers(report: Any) -> None:
    if not any(bh.layers for bh in report.boreholes):
        raise FeatureInputError("Add logged soil layers to at least one borehole first.")


def save_json(ctx: FeatureContext, relative: str, payload: Any) -> str:
    path = ctx.path(relative)
    if path is None:
        raise FeatureInputError("Open a project before exporting Soil Report data.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return str(path.resolve())


def save_text(ctx: FeatureContext, relative: str, payload: str) -> str:
    path = ctx.path(relative)
    if path is None:
        raise FeatureInputError("Open a project before exporting Soil Report data.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return str(path.resolve())


def counts(report: Any) -> dict[str, int]:
    return {
        "boreholesCount": len(report.boreholes),
        "layersCount": sum(len(bh.layers) for bh in report.boreholes),
        "sptTestsCount": sum(len(bh.spt) for bh in report.boreholes),
        "samplesCount": sum(len(bh.samples) for bh in report.boreholes),
    }


def result_rows(
    title: str,
    columns: list[tuple[str, str] | tuple[str, str, str]],
    rows: list[dict[str, Any]],
    *,
    summary: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return result(
        summary=summary or {"rowsCount": len(rows)},
        tables=[table(title, columns, rows)],
        notes=notes or [],
    )


def clean_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "soil-export"


__all__ = [
    "FeatureInputError",
    "borehole",
    "checkbox",
    "clean_slug",
    "common_fields",
    "counts",
    "feature",
    "layer_rows",
    "number",
    "profile",
    "profiles",
    "register_tab",
    "require_layers",
    "require_report",
    "result",
    "result_rows",
    "sample_rows",
    "samples",
    "save_json",
    "save_text",
    "select",
    "spt_rows",
    "table",
    "text",
]
