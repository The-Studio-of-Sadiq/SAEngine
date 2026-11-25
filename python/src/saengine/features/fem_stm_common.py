"""Shared persistence and geometry helpers for strut-and-tie ribbon features."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from saengine.design import stm_model
from saengine.features import FeatureContext, FeatureInputError
from saengine.features.fem_common import load_stm_file, resolve_stm_model
from saengine.library.strut_and_tie import StmModel, StrutAndTieFile


def project_models(ctx: FeatureContext) -> list[StmModel]:
    """Load project models or explain how to create one."""
    models = load_stm_file(ctx)
    if not models:
        raise FeatureInputError("Create a strut-and-tie model first (08 FEM/strut-and-tie.json).")
    return models


def project_model(ctx: FeatureContext, index: int = 0) -> tuple[list[StmModel], StmModel]:
    models = project_models(ctx)
    if index < 0 or index >= len(models):
        raise FeatureInputError(f"Model index {index} is outside the {len(models)} project models.")
    return models, models[index]


def working_model(ctx: FeatureContext, values: dict[str, Any], kind: str = "deepBeam") -> StmModel:
    """Use a project model when present, otherwise solve an explicit engineering template."""
    requested = str(values.get("templateKind", kind))
    params = {
        key: float(values[key])
        for key in ("spanMm", "depthMm", "thicknessMm", "loadKn", "bearingMm", "fcMpa", "fyMpa")
        if key in values
    }
    params = {
        "span": params.get("spanMm", 3000.0),
        "depth": params.get("depthMm", 1500.0),
        "thickness": params.get("thicknessMm", 300.0),
        "load": params.get("loadKn", 1000.0),
        "bearing": params.get("bearingMm", 300.0),
        "fc": params.get("fcMpa", 28.0),
        "fy": params.get("fyMpa", 420.0),
    }
    model, _source = resolve_stm_model(ctx, requested, params)
    return model


def store_models(ctx: FeatureContext, models: list[StmModel]) -> Path:
    """Persist edited STM models next to the FEM model."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder before saving the strut-and-tie model.")
    target = next(
        (
            ctx.root / folder / "strut-and-tie.json"
            for folder in ("08 FEM", "08 Analysis")
            if (ctx.root / folder / "strut-and-tie.json").is_file()
        ),
        ctx.root / "08 FEM" / "strut-and-tie.json",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        history_path = target.with_name("strut-and-tie-history.json")
        try:
            history = (
                json.loads(history_path.read_text(encoding="utf-8"))
                if history_path.is_file()
                else []
            )
            previous = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FeatureInputError(f"Cannot preserve STM edit history: {exc}") from exc
        history.append(previous)
        history_path.write_text(
            json.dumps(history[-20:], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    payload = StrutAndTieFile(models=models).model_dump_json(indent=2, by_alias=True) + "\n"
    target.write_text(payload, encoding="utf-8")
    return target


def solve_rows(model: StmModel) -> dict[str, Any]:
    """Return checked model data, rejecting a mechanism instead of fabricating forces."""
    checked = stm_model.check_model(model)
    if checked["problems"]:
        raise FeatureInputError("; ".join(checked["problems"]))
    return checked


def geometry(model: StmModel) -> dict[str, tuple[float, float, float, float, float]]:
    """Member start point, unit direction, and length in millimetres."""
    nodes = {node.id: node for node in model.nodes}
    out = {}
    for member in model.members:
        start, end = nodes[member.start], nodes[member.end]
        dx, dy = end.x - start.x, end.y - start.y
        length = math.hypot(dx, dy)
        if length <= 0:
            raise FeatureInputError(f"Member {member.id} has zero length.")
        out[member.id] = (start.x, start.y, dx / length, dy / length, length)
    return out


def next_id(prefix: str, used: set[str]) -> str:
    number = 1
    while f"{prefix}{number}" in used:
        number += 1
    return f"{prefix}{number}"


def export_json(ctx: FeatureContext, filename: str, payload: Any) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project folder before exporting strut-and-tie results.")
    target = ctx.root / "08 FEM" / "exports" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
