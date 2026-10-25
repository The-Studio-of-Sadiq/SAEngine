"""The soil report (Part 1) downstream: the site class of the analysis, the RPC handlers."""

from __future__ import annotations

import json
from pathlib import Path

from test_fem_derive import OBJECTS, PLAN, SETTINGS

from saengine.fem.derive import stamp
from saengine.library import default_material_library
from saengine.library.bim import generate
from saengine.library.settings import (
    ProjectSettings,
    resolve_site_class,
    soil_site_class,
)
from saengine.rpc import handlers

PLACEHOLDER = '{"schema": 1, "part": "soil"}'


def soil_text(n: int = 8, depth: int = 30000) -> str:
    """One borehole BH-1 of silty sand with SPT N = ``n`` every 1.5 m down to ``depth``."""
    return json.dumps(
        {
            "schema": "saengine.soilReport/1",
            "boreholes": [
                {
                    "id": "BH-1",
                    "x": 0,
                    "y": 0,
                    "waterTable": 2000,
                    "depth": depth,
                    "layers": [
                        {
                            "top": 0,
                            "bottom": depth,
                            "description": "Silty fine sand",
                            "soilType": "sand",
                            "unitWeight": 18,
                            "finesContent": 20,
                        }
                    ],
                    "spt": [{"depth": d, "N": n} for d in range(1500, depth + 1, 1500)],
                }
            ],
        }
    )


def settings(site_class: str = "SC", source: str = "soilReport") -> ProjectSettings:
    site = SETTINGS.site.model_copy(update={"siteClass": site_class, "siteClassSource": source})
    return SETTINGS.model_copy(update={"site": site})


def dumps(model: ProjectSettings) -> str:
    return json.dumps(model.model_dump(mode="json", by_alias=True, exclude_none=True))


def test_site_class_from_the_soil_report() -> None:
    # N = 8 everywhere: N̄ = 8 < 15, SD (BNBC 2020 Table 6.2.13), over the full 30 m.
    soil = soil_site_class(soil_text())
    assert soil["class"] == "SD" and soil["N"] == 8 and soil["borehole"] == "BH-1"
    assert soil["label"] == "SD (N̄ = 8 over 30 m, BH-1)"
    # A 20 m borehole: its last N is taken down to 30 m, and the label says so.
    assert soil_site_class(soil_text(depth=20000))["label"] == (
        "SD (N̄ = 8 over 30 m, extrapolated, BH-1)"
    )

    resolved, info = resolve_site_class(settings("SC"), soil_text())
    assert resolved.site.siteClass == "SD" and info["source"] == "soilReport"
    assert info["entered"] == "SC"
    assert info["label"] == "from 1 Soil Report: SD (N̄ = 8 over 30 m, BH-1)"

    # Entered: the entered class stays, whatever the boreholes say.
    resolved, info = resolve_site_class(settings("SC", "entered"), soil_text())
    assert resolved.site.siteClass == "SC" and info["source"] == "entered"
    # No boreholes (an old project's placeholder, no file, errors): the entered class.
    for text in (PLACEHOLDER, None, "{not json"):
        resolved, info = resolve_site_class(settings("SC"), text)
        assert resolved.site.siteClass == "SC" and info["source"] == "entered", text
    # Old settings files have no source: from the soil report by default.
    old = json.loads(dumps(settings("SC")))
    del old["site"]["siteClassSource"]
    model = ProjectSettings.model_validate(old)
    assert model.site.siteClassSource == "soilReport"
    assert resolve_site_class(model, soil_text())[0].site.siteClass == "SD"


def derive(settings_model: ProjectSettings, soil: str | None, folder: str | None = None):
    bim = generate(PLAN, "s").model_dump(mode="json", by_alias=True, exclude_none=True)
    return handlers.derive_fem(
        json.dumps(bim),
        json.dumps(OBJECTS.model_dump(mode="json", by_alias=True, exclude_none=True)),
        json.dumps(default_material_library().model_dump(mode="json", by_alias=True)),
        dumps(settings_model),
        folder,
        soil,
    )


def test_the_analysis_uses_the_soil_report_site_class(tmp_path: Path) -> None:
    entered = derive(settings("SC"), PLACEHOLDER)
    from_soil = derive(settings("SC"), soil_text())
    same_as_sd = derive(settings("SD", "entered"), PLACEHOLDER)
    assert "problems" not in from_soil, from_soil
    # SD's larger soil factor (S = 1.35 against 1.15) raises the base shear: the analysis is
    # derived with SD, exactly as if SD had been entered.
    shear = {k: r["summary"]["base_shear_kN"] for k, r in [("SC", entered), ("soil", from_soil)]}
    assert shear["soil"] > shear["SC"]
    assert from_soil["summary"] == same_as_sd["summary"]
    assert from_soil["notes"][0].startswith(
        "Site class from 1 Soil Report: SD (N̄ = 8 over 30 m, BH-1)"
    )

    # The soil report is recorded as a source of the model (its stamp) whenever the settings
    # take the class from it, also while it is the placeholder (boreholes added later then make
    # the model out of date); never with the source Entered.
    def recorded(result: dict) -> str:
        return json.loads(result["text"])["meta"]["description"]

    assert f"soil={stamp(soil_text())}" in recorded(from_soil)
    assert f"soil={stamp(PLACEHOLDER)}" in recorded(entered)
    assert "soil=" not in recorded(same_as_sd)

    # Without the text, the soil report beside the model folder (08 FEM) is read.
    (tmp_path / "01 Soil Report").mkdir()
    (tmp_path / "01 Soil Report" / "soil-report.json").write_text(soil_text(), encoding="utf-8")
    beside = derive(settings("SC"), None, str(tmp_path / "08 FEM"))
    assert beside["summary"] == from_soil["summary"]


def test_soil_handlers() -> None:
    text = soil_text()
    # Entered SC against the boreholes' SD: the soil report says so...
    report = handlers.soil_report(text, dumps(settings("SC", "entered")))
    assert report["siteClass"]["class"] == "SD"
    assert any("The project settings use site class SC" in n for n in report["notes"])
    # ... but not when the settings take the class from the soil report.
    report = handlers.soil_report(text, dumps(settings("SC")))
    assert not any("The project settings use site class" in n for n in report["notes"])

    found = handlers.allowable_bearing(text, None, 0, 0, -1500, 2000, 2000)
    assert found["borehole"] == "BH-1" and found["qa_kpa"] > 0

    sources = handlers.soil_sources(text, dumps(settings("SC")))
    assert sources["site"]["class"] == "SD" and sources["site"]["source"] == "soilReport"
    assert sources["bearing"]["source"] == "soilReport" and sources["bearing"]["boreholes"] == 1
    assert sources["bearing"]["levels"] is None  # finished ground and BH-1's both at the datum
    filled = settings("SC").model_copy(
        update={"foundation": SETTINGS.foundation.model_copy(update={"groundLevel": 1000})}
    )
    assert handlers.soil_sources(text, dumps(filled))["bearing"]["levels"].startswith(
        "The finished ground (+1.00 m) differs from the ground of BH-1 +0.00 m: qa is net of"
    )
    with_override = settings("SC").model_copy(
        update={"foundation": SETTINGS.foundation.model_copy(update={"allowableBearing": 150})}
    )
    assert handlers.soil_sources(text, dumps(with_override))["bearing"]["source"] == "override"
    empty = handlers.soil_sources(PLACEHOLDER, dumps(settings("SC")))
    assert empty["site"]["source"] == "entered" and empty["bearing"]["source"] == "none"


def test_soil_template_and_import_round_trip(tmp_path: Path) -> None:
    template = tmp_path / "boreholes.csv"
    assert handlers.soil_template(str(template)) == {"path": str(template)}
    # The template's example borehole is never imported (it would replace a real BH-1).
    imported = handlers.import_soil(str(template), PLACEHOLDER)
    assert "EXAMPLE-1" in imported["problems"][0]
    rows = template.read_text(encoding="utf-8-sig").splitlines()
    rows += [row.replace("EXAMPLE-1", "BH-7", 1) for row in rows[1:]]
    template.write_text("\n".join(rows) + "\n", encoding="utf-8")
    imported = handlers.import_soil(str(template), PLACEHOLDER)
    assert [b["id"] for b in json.loads(imported["text"])["boreholes"]] == ["BH-7"]
    assert any(n.startswith("BH-7: added (3 layers") for n in imported["notes"])


def test_soil_methods_over_the_stdio_server(tmp_path: Path) -> None:
    import subprocess
    import sys

    from test_rpc import _rpc

    proc = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    text = soil_text()
    try:
        report = _rpc(proc, 1, "soil/report", {"soilText": text})["result"]
        assert report["siteClass"]["class"] == "SD" and len(report["boreholes"]) == 1
        qa = _rpc(
            proc,
            2,
            "soil/allowableBearing",
            {"soilText": text, "x": 0, "y": 0, "foundingLevel": -1500, "b": 2000, "l": 2000},
        )["result"]
        assert (
            qa["qa_kpa"]
            == handlers.allowable_bearing(text, None, 0, 0, -1500, 2000, 2000)["qa_kpa"]
        )
        template = str(tmp_path / "t.xlsx")
        assert _rpc(proc, 3, "soil/template", {"path": template})["result"] == {"path": template}
        imported = _rpc(proc, 4, "soil/import", {"path": template, "soilText": PLACEHOLDER})
        assert "EXAMPLE-1" in imported["result"]["problems"][0]
        settlement = _rpc(
            proc,
            5,
            "soil/settlement",
            {"soilText": text, "borehole": "BH-1", "b": 2000, "l": 2000, "df": 1500, "q": 50},
        )["result"]
        assert settlement["total"] > 0
        sources = _rpc(proc, 6, "soil/sources", {"soilText": text})["result"]
        assert sources["site"]["class"] == "SD" and sources["bearing"]["source"] == "soilReport"
    finally:
        proc.kill()
        proc.wait()
