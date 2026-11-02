"""Decoupling track D6 (the leftovers of D1 to D4): the code is only a setting.

- The bar detailing numbers of the drawings (hooks, bends, development and lap minima and
  factors, splice zones, bar extents) are the code pack's ``detailing.bars``, read when used.
- With the default pack every value is the same as before the move: pinned here.
- A stub pack that extends the default pack and overrides one table changes only what that
  table drives.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

STUB = "stub-d6"


def _stub_pack(folder: Path, tables: dict[str, dict]) -> Path:
    """A pack that extends the default pack and changes only ``tables``."""
    pack = folder / STUB
    (pack / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": STUB,
        "name": "Stub Code 2030",
        "version": "0.1.0",
        "extends": registry.DEFAULT_PACK,
        "covers": list(tables),
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    for table, data in tables.items():
        (pack / f"data/{table}.json").write_text(json.dumps(data), encoding="utf-8")
    return pack


@contextmanager
def stub(tmp_path: Path, tables: dict[str, dict]) -> Iterator[Path]:
    """Within the block the stub pack is in force (a project of ``tmp_path`` that chooses it)."""
    root = tmp_path / "Stub project"
    (root / "02 Project Settings").mkdir(parents=True)
    _stub_pack(root / registry.PROJECT_PACKS, tables)
    with code_context.project(root):
        pack = code_context.pack_for({"codePack": STUB}, root)
        with code_context.using(pack):
            yield root


# ─────────────────────────────── 1. bar detailing of the drawings ───────────────────────────────


def _detailing_values() -> dict[str, object]:
    from saengine.drawings import detailing as dt

    return {
        "ld16": dt.development_tension(16.0, 420.0, 25.0).value,
        "ld6min": dt.development_tension(6.0, 420.0, 25.0).value,
        "ld6formula": dt.development_tension(6.0, 420.0, 25.0).formula,
        "ldc20": dt.development_compression(20.0, 420.0, 25.0).value,
        "ldh20": dt.hook_development(20.0, 420.0, 25.0, cover=True).value,
        "lapB16": dt.lap_tension(16.0, 420.0, 25.0).value,
        "lapA16": dt.lap_tension(16.0, 420.0, 25.0, cls="A").value,
        "lapB16formula": dt.lap_tension(16.0, 420.0, 25.0).formula,
        "lapC20": dt.lap_compression(20.0, 420.0, 18.0).value,
        "lapC20formula": dt.lap_compression(20.0, 420.0, 18.0).formula,
        "spiral10": dt.spiral_lap(10.0).value,
        "bend20": dt.bend_diameter(20.0).value,
        "bend32": dt.bend_diameter(32.0).value,
        "bendTie10": dt.bend_diameter(10.0, transverse=True).value,
        "hook90tail16": dt.standard_hook(16.0).tail,
        "hook180tail10": dt.standard_hook(10.0, 180).tail,
        "seismicTail10": dt.seismic_hook(10.0).tail,
        "tie90tail20": dt.standard_hook(20.0, 90, transverse=True).tail,
        "classA": dt.splice_class(2.0, 0.5),
        "exclusion": dt.seismic_splice_exclusion(500.0).value,
        "columnRegion": dt.column_splice_region(2800.0),
        "slabTop": dt.slab_top_extent(4000.0).value,
        "negative": dt.negative_extension(400.0, 16.0, 6400.0).value,
        "intoSupport": dt.positive_into_support(7, True),
        "noLap36": dt.no_lap(36.0),
        "noLap32": dt.no_lap(32.0),
    }


#: The values before the move (base 6be21163, 2026-11-02), with the default pack.
PINNED_DETAILING = {
    "ld16": pytest.approx(16 * 420 / (2.1 * 5.0), rel=1e-12),
    "ld6min": 300.0,
    "ld6formula": "fy ψt ψe / (2.1 λ √f'c) db = 420·1 / (2.1·1·5.00)·6, at least 300 mm (8.2.3.1)",
    "ldc20": pytest.approx(0.24 * 420 * 20 / 5.0, rel=1e-12),
    "ldh20": pytest.approx(0.24 * 420 * 20 / 5.0 * 0.7, rel=1e-12),
    "lapB16": pytest.approx(1.3 * 16 * 420 / (2.1 * 5.0), rel=1e-12),
    "lapA16": pytest.approx(16 * 420 / (2.1 * 5.0), rel=1e-12),
    "lapB16formula": "1.3 ld = 1.3 × 640, at least 300 mm",
    "lapC20": pytest.approx(0.071 * 420 * 20 * 4 / 3, rel=1e-12),
    "lapC20formula": "0.071 fy db × 4/3 (f'c < 21 MPa), at least 300 mm",
    "spiral10": 480.0,
    "bend20": 120.0,
    "bend32": 256.0,
    "bendTie10": 40.0,
    "hook90tail16": 192.0,
    "hook180tail10": 65.0,
    "seismicTail10": 75.0,
    "tie90tail20": 240.0,
    "classA": "A",
    "exclusion": 1000.0,
    "columnRegion": (700.0, 2100.0),
    "slabTop": 1200.0,
    "negative": 400.0,
    "intoSupport": 2,
    "noLap36": True,
    "noLap32": False,
}


def test_bar_detailing_values_are_pinned() -> None:
    assert _detailing_values() == PINNED_DETAILING


def test_sample_frame_detailing_is_unchanged_in_shape() -> None:
    from saengine.drawings.detailing import detailing_model

    root = Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples"
    model = detailing_model(root / "Sample Frame")
    assert model["options"]["slabTopExtent"] == 0.3
    laps = [lap for e in model["elements"] for lap in e["laps"] if lap["class"] == "B"]
    assert laps and all(lap["length"] >= 300 for lap in laps)


def test_stub_pack_changes_only_the_lap_factors(tmp_path: Path) -> None:
    before = _detailing_values()
    with stub(tmp_path, {"detailing": {"bars": {"laps": {"classB": 1.5, "min": 400.0}}}}):
        after = _detailing_values()
    changed = {k for k in before if before[k] != after[k]}
    # lapC20 (795 mm) and the spiral lap (480 mm) stay above the new 400 mm minimum
    assert changed == {"lapB16", "lapB16formula", "lapC20formula"}
    assert after["lapB16"] == pytest.approx(1.5 * 640.0)
    assert after["lapB16formula"] == "1.5 ld = 1.5 × 640, at least 400 mm"
    assert after["lapC20formula"].endswith("at least 400 mm")


def test_a_pack_without_bar_rules_does_not_cover_the_detailing(tmp_path: Path) -> None:
    from saengine.drawings import detailing as dt

    with (
        stub(tmp_path, {"detailing": {"$remove": ["bars"]}}),
        pytest.raises(dt.NotCovered, match="not covered by the code pack"),
    ):
        dt.development_tension(16.0, 420.0, 25.0)
