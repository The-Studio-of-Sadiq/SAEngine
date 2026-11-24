"""Shared IO, parsing, and bill/rates/schedule helpers for BOQ & Costing features."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from saengine.boq.construction_schedule import (
    ConstructionSchedule,
    Productivity,
    parse_productivity,
    sample_productivity_text,
)
from saengine.boq.costing import (
    CarbonFactors,
    RateSchedule,
    cost_bill,
    default_carbon_text,
    parse_carbon,
    parse_rates,
    sample_rates_text,
)
from saengine.boq.takeoff import Takeoff
from saengine.features import FeatureContext, FeatureInputError


def require_root(ctx: FeatureContext, purpose: str = "this feature") -> Path:
    """Return the project root path or raise a clear FeatureInputError."""
    if ctx.root is None or not ctx.root.exists():
        raise FeatureInputError(f"Open a project folder before running {purpose}.")
    return ctx.root


def load_bill(ctx: FeatureContext) -> dict[str, Any] | None:
    """Return ``10 BOQ/boq.json`` as a dict, or None when absent."""
    raw = ctx.raw("boq")
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("items"), list):
        return None
    return raw


def require_bill(ctx: FeatureContext) -> dict[str, Any]:
    """Return ``10 BOQ/boq.json`` or raise FeatureInputError."""
    bill = load_bill(ctx)
    if bill is None:
        raise FeatureInputError(
            "Open a project with 10 BOQ/boq.json first (or measure the BOQ from the model)."
        )
    return bill


def load_rates(ctx: FeatureContext) -> tuple[RateSchedule, bool]:
    """Return (RateSchedule, is_project) reading ``10 BOQ/rates.json`` or the sample schedule."""
    path = ctx.path("10 BOQ/rates.json")
    if path is not None and path.is_file():
        try:
            return parse_rates(path.read_text(encoding="utf-8")), True
        except Exception as exc:
            raise FeatureInputError(f"10 BOQ/rates.json is invalid: {exc}") from exc
    return parse_rates(sample_rates_text()), False


def load_carbon(ctx: FeatureContext) -> tuple[CarbonFactors, bool]:
    """Return (CarbonFactors, is_project) reading ``10 BOQ/carbon-factors.json`` or default."""
    path = ctx.path("10 BOQ/carbon-factors.json")
    if path is not None and path.is_file():
        try:
            return parse_carbon(path.read_text(encoding="utf-8")), True
        except Exception as exc:
            raise FeatureInputError(f"10 BOQ/carbon-factors.json is invalid: {exc}") from exc
    return parse_carbon(default_carbon_text()), False


def load_productivity(ctx: FeatureContext) -> tuple[Productivity, bool]:
    """Return (Productivity, is_project) from ``10 BOQ/productivity.json`` or sample."""
    path = ctx.path("10 BOQ/productivity.json")
    if path is not None and path.is_file():
        try:
            return parse_productivity(path.read_text(encoding="utf-8")), True
        except Exception as exc:
            raise FeatureInputError(f"10 BOQ/productivity.json is invalid: {exc}") from exc
    return parse_productivity(sample_productivity_text()), False


def load_schedule(ctx: FeatureContext) -> ConstructionSchedule | None:
    """Return validated ``10 BOQ/construction-schedule.json`` if present, else None."""
    path = ctx.path("10 BOQ/construction-schedule.json")
    if path is not None and path.is_file():
        try:
            return ConstructionSchedule.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FeatureInputError(f"10 BOQ/construction-schedule.json is invalid: {exc}") from exc
    return None


def load_takeoff(ctx: FeatureContext) -> Takeoff | None:
    """Return validated ``10 BOQ/takeoff.json`` if present, else None."""
    path = ctx.path("10 BOQ/takeoff.json")
    if path is not None and path.is_file():
        try:
            return Takeoff.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FeatureInputError(f"10 BOQ/takeoff.json is invalid: {exc}") from exc
    return None


def save_export(ctx: FeatureContext, filename: str, content: str | bytes) -> Path:
    """Write an export file under ``10 BOQ/exports/<filename>``."""
    require_root(ctx, "exporting BOQ outputs")
    target = ctx.path(f"10 BOQ/exports/{filename}")
    if target is None:
        raise FeatureInputError("Open a project folder first.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def price_project_bill(
    ctx: FeatureContext,
) -> tuple[dict[str, Any], RateSchedule, CarbonFactors, Any]:
    """Load and price the project bill using ``saengine.boq.costing.cost_bill``."""
    bill = require_bill(ctx)
    rates, _ = load_rates(ctx)
    carbon, _ = load_carbon(ctx)
    costing = cost_bill(bill, rates, carbon)
    return bill, rates, carbon, costing


def parse_csv_rows(raw: str) -> list[dict[str, str]]:
    """Parse CSV text with a header row into stripped dict rows."""
    text_clean = raw.strip()
    if not text_clean:
        raise FeatureInputError("Provide CSV input with a header row.")
    reader = csv.DictReader(io.StringIO(text_clean))
    if not reader.fieldnames:
        raise FeatureInputError("CSV input needs a header row.")
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if any(cleaned.values()):
            rows.append(cleaned)
    if not rows:
        raise FeatureInputError("CSV input contains no data rows.")
    return rows


def parse_numbers(raw: str, label: str = "Values") -> list[float]:
    """Parse comma, whitespace, or semicolon separated numbers."""
    tokens = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
    if not tokens:
        raise FeatureInputError(f"Enter at least one number for {label}.")
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
    for line in re.split(r"[\r\n;]+", raw.strip()):
        s = line.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[\s,]+", s) if p]
        if len(parts) < 2:
            raise FeatureInputError(f"{label}: expected two numbers on line {s!r}.")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise FeatureInputError(f"{label}: invalid number on line {s!r}.") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            raise FeatureInputError(f"{label}: numbers must be finite.")
        pairs.append((x, y))
    if not pairs:
        raise FeatureInputError(f"Enter at least one pair for {label}.")
    return pairs


def safe_json(data: Any) -> str:
    """Serialize data deterministically to indented JSON."""
    return json.dumps(data, indent=2, sort_keys=False) + "\n"
