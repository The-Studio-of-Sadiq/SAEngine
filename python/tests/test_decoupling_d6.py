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


def test_a_pack_without_bar_rules_uses_the_generic_defaults(tmp_path: Path) -> None:
    """Re-pinned by D7 (owner update 2026-11-02): a pack that lacks a value still works with a
    named generic default; "not covered" stays only for a whole feature without a method. The
    bar detailing numbers are values, so a pack without ``bars`` now reads the generic defaults
    (ACI 318-19 values), named as such, instead of raising NotCovered."""
    from saengine.drawings import detailing as dt

    with stub(tmp_path, {"detailing": {"$remove": ["bars"]}}):
        pack = code_context.current()
        fallback = pack.fallback("detailing", "bars.laps.classB")
        ld = dt.development_tension(16.0, 420.0, 25.0).value
        no_lap_36 = dt.no_lap(36.0)
    assert fallback is not None and "ACI 318-19" in fallback.note
    assert "BNBC" not in fallback.note
    assert ld > 0
    assert not no_lap_36  # ACI 318-19 25.5.1.1: 36 mm bars may be lap spliced


# ─────────────── 2. rc code values outside design/ are read when used, not at import ───────────────


def _rc_values() -> dict[str, float]:
    from saengine.library.defaults import default_material_library
    from saengine.substructure import pilehead, shallow

    rebar = next(m for m in default_material_library().materials if m.id == "B500DWR")
    return {
        "pileShear": pilehead.shear_capacity(600.0, 25.0, 420.0, None)["phiVn"],
        "stripPhi": shallow.strip_flexure(1000.0, 400.0, 25.0, 420.0).phi,
        "oneWay": shallow.one_way_shear_capacity(1000.0, 400.0, 0.004, 25.0),
        "rebarE": rebar.mechanical.E,
    }


def test_rc_values_outside_design_are_pinned() -> None:
    import math

    values = _rc_values()
    assert values["rebarE"] == 200_000.0
    assert values["stripPhi"] == 0.9
    size = math.sqrt(2 / (1 + 0.004 * 480))  # pile head: bw = 600, d = 0.8 D, no hoops
    assert values["pileShear"] == pytest.approx(
        0.75 * 0.66 * size * 1e-6 ** (1 / 3) * 5 * 600 * 480, rel=1e-12
    )
    size = math.sqrt(2 / (1 + 0.004 * 400))
    assert values["oneWay"] == pytest.approx(
        0.75 * 0.66 * size * 0.004 ** (1 / 3) * 5 * 1000 * 400, rel=1e-12
    )


def test_stub_pack_phi_and_es_reach_the_modules_outside_design(tmp_path: Path) -> None:
    before = _rc_values()
    with stub(tmp_path, {"factors": {"phi": {"shear": 0.6}}, "materials": {"steelE": 210000.0}}):
        after = _rc_values()
    assert after["pileShear"] == pytest.approx(before["pileShear"] * 0.6 / 0.75)
    assert after["oneWay"] == pytest.approx(before["oneWay"] * 0.6 / 0.75)
    assert after["rebarE"] == 210_000.0
    assert after["stripPhi"] == before["stripPhi"]


# ───────────── 3. the settings' lists are the chosen pack's (towns, uses, systems, classes) ─────────────

XTOWN = {"locations": {"locations": {"xtown": {"name": "X Town", "zone": 2, "windSpeed": 51.0}}}}


def _settings_with(location: str, code_pack: str = registry.DEFAULT_PACK):
    from saengine.library.settings import ProjectSettings, default_project_settings

    data = default_project_settings("D6").model_dump(mode="json", by_alias=True)
    data["codePack"] = code_pack
    data["site"]["location"] = location
    return ProjectSettings.model_validate(data)


def test_the_default_pack_lists_are_checked_when_parsing() -> None:
    from pydantic import ValidationError

    assert _settings_with("dhaka").site.location == "dhaka"
    assert _settings_with("custom").site.location == "custom"
    with pytest.raises(ValidationError, match="site.location 'xtown'"):
        _settings_with("xtown")


def test_a_project_pack_town_is_accepted_and_used(tmp_path: Path) -> None:
    from saengine.library.settings import derived, pack_choices
    from saengine.rpc.handlers import codes_choices

    with stub(tmp_path, XTOWN) as root:
        settings = _settings_with("xtown", STUB)
        assert settings.site.location == "xtown"
        values = derived(settings)
        lists = pack_choices(code_context.current())
        answer = codes_choices(STUB, str(root))
    assert any(row["id"] == "xtown" for row in lists["locations"])
    assert lists["locations"][-1]["id"] == "custom"
    assert any("X Town" in row["label"] for row in answer["choices"]["locations"])
    assert answer["name"] == "Stub Code 2030"
    assert values["windSpeed"] == 51.0 and values["zone"] == 2


def test_a_pack_not_found_here_is_not_checked_when_parsing() -> None:
    # A project's own pack read without its project: its lists are unknown here, so the ids are
    # taken (check() reports the pack as not installed).
    assert _settings_with("xtown", "not-installed-pack").site.location == "xtown"


def test_default_pack_choices_match_the_schema_fallback() -> None:
    from saengine.library import code_data
    from saengine.library.settings import ProjectSettings, pack_choices

    lists = pack_choices(code_context.default_pack())
    assert [r["id"] for r in lists["locations"]] == [*code_data.LOCATIONS, "custom"]
    assert [r["id"] for r in lists["systems"]] == list(code_data.STRUCTURAL_SYSTEMS)
    assert [r["id"] for r in lists["siteClasses"]] == list(code_data.SITE_CLASSES)
    schema = ProjectSettings.model_json_schema()
    site = schema["$defs"]["Site"]["properties"]
    assert site["location"]["enum"] == [r["id"] for r in lists["locations"]]
    assert site["location"]["enumDescriptions"] == [r["label"] for r in lists["locations"]]
    assert site["siteClass"]["enumDescriptions"] == [r["label"] for r in lists["siteClasses"]]


# ───────────────────── 4. P-Delta preload and stability factors from the pack ─────────────────────


def test_pdelta_and_stability_factors_are_pinned() -> None:
    from saengine.fem import second_order as so
    from saengine.library.settings import PDeltaFactors, default_project_settings

    # The values before the move (base 6be21163): 1.2D + 1.2SD + 1.2F + 1.0L and 1.0 each.
    assert so.pdelta_factors() == {"D": 1.2, "SD": 1.2, "F": 1.2, "L": 1.0}
    assert so.stability_gravity_factors() == {"D": 1.0, "SD": 1.0, "F": 1.0, "L": 1.0}
    assert so.DEFAULT_PDELTA_FACTORS == so.pdelta_factors()  # the former names still read
    assert so.STABILITY_GRAVITY_FACTORS == so.stability_gravity_factors()
    settings = default_project_settings("D6")
    assert settings.analysis.pDeltaFactors is None
    assert so.options_from_settings(settings).pDeltaFactors == so.pdelta_factors()
    assert PDeltaFactors().model_dump() == {"D": 1.2, "SD": 1.2, "F": 1.2, "L": 1.0}
    # A file that gives the factors keeps them.
    settings.analysis.pDeltaFactors = PDeltaFactors(D=1.0, SD=1.0, F=1.0, L=0.5)
    assert so.options_from_settings(settings).pDeltaFactors["L"] == 0.5


def test_stub_pack_changes_only_the_pdelta_preload(tmp_path: Path) -> None:
    from saengine.fem import second_order as so
    from saengine.library.settings import default_project_settings

    settings = default_project_settings("D6")
    with stub(tmp_path, {"combinations": {"pDeltaPreload": {"D": 1.4, "L": 0.5}}}):
        preload = so.options_from_settings(settings).pDeltaFactors
        stability = so.stability_gravity_factors()
    # Objects are merged key by key: SD and F keep the default pack's 1.2.
    assert preload == {"D": 1.4, "SD": 1.2, "F": 1.2, "L": 0.5}
    assert stability == {"D": 1.0, "SD": 1.0, "F": 1.0, "L": 1.0}
