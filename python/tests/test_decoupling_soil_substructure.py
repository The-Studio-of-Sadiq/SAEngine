"""D3: the soil, substructure and gis modules read the code pack, not BNBC constants.

Every value below is pinned with the default pack (bnbc2020): the results are those before the
values moved into the pack. A stub pack that extends bnbc2020 and overrides one table changes
only that table's results; a pack without a group says the feature is not covered. Synthetic
data; packs are written to ``tmp_path`` only."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.soil import SoilReport
from saengine.soil import liquefaction, site_class
from saengine.soil.profile import Profile

#: Clean sand to 10 m (FC 10 %, water table at 2 m), N = 15 at 8 m; clay below to 31 m.
HOLE = {
    "id": "BH-1",
    "waterTable": 2000,
    "depth": 31000,
    "layers": [
        {
            "top": 0,
            "bottom": 10000,
            "soilType": "sand",
            "unitWeight": 18,
            "saturatedUnitWeight": 20,
            "finesContent": 10,
        },
        {"top": 10000, "bottom": 31000, "soilType": "clay", "cu": 60},
    ],
    "spt": [{"depth": 8000, "N": 15}, {"depth": 20000, "N": 12}, {"depth": 30000, "N": 18}],
}


def profile(method: str = "codePack") -> Profile:
    """The borehole with ``method``; "codePack" (the engine's id, not yet in the soil report's
    schema, which still saves the former "bnbc2020") is set without validation."""
    saved = "bnbc2020" if method == "codePack" else method
    report = SoilReport.model_validate(
        {
            "boreholes": [HOLE],
            "design": {"liquefactionMethod": saved, "liquefaction": {"magnitude": 7.5}},
        }
    )
    if method != saved:
        design = report.design.model_copy(update={"liquefactionMethod": method})
        report = report.model_copy(update={"design": design})
    return Profile(report, report.boreholes[0])


def stub(root: Path, tables: dict[str, dict], extends: str | None = "bnbc2020") -> object:
    """A pack ``d3-stub`` (name "D3 stub") extending bnbc2020 with ``tables`` over it."""
    folder = root / "d3-stub"
    (folder / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": "d3-stub",
        "name": "D3 stub",
        "version": "1.0.0",
        "extends": extends,
        "covers": list(tables),
    }
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, data in tables.items():
        (folder / "data" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return registry.load_path(folder)


# ─────────────────────────────── default pack: pinned ───────────────────────────────


def test_liquefaction_code_procedure_pinned_and_the_old_id_reads_the_same() -> None:
    amax, note = liquefaction.amax_from(None, 0.20, ["SD"])
    assert amax == 2 / 3 * 0.20 * 1.35
    assert note.startswith("amax = (2/3) Z S = (2/3) × 0.2 × 1.35 = 0.180 g")
    new = liquefaction.screen(profile("codePack"), amax, note)
    old = liquefaction.screen(profile("bnbc2020"), amax, note)
    assert new["points"] == old["points"] and new["lpi"] == old["lpi"]
    point = new["points"][0]
    assert point["rd"] == pytest.approx(1 - 0.015 * 8, abs=1e-3)
    # By hand: amax 0.18, σv 156, σ'v 97.14 kPa, rd 0.88: CSR = 0.18 × 0.88 × 156 / 97.14.
    assert (point["csr"], point["fs"], point["liquefiable"]) == (0.254, 0.66, True)
    assert "BNBC 2020 Sec 3.9.5 screening" in " ".join(new["notes"])
    assert liquefaction.method_text("bnbc2020") == liquefaction.method_text("codePack")


def test_site_class_pinned() -> None:
    site = site_class.site_class(profile())
    assert (site["class"], site["N"], site["byN"], site["bySu"]) == ("SD", 14.1, "SD", "SD")
    assert site["note"].endswith("(BNBC 2020 Table 6.2.13, harmonic means over the top 30 m).")
    assert site_class.ORDER == ("SA", "SB", "SC", "SD", "SE")
    assert site_class.liquefiable_assumed() == "SD"
    flagged = site_class.flag_liquefaction({**site, "class": "SC"}, True)
    assert flagged["class"] == "SD" and flagged["flags"][-1]["class"] == "S2"


def test_pile_cap_and_tie_beam_rules_pinned() -> None:
    import test_substructure_piles as tp
    import test_substructure_shallow as ts

    from saengine.substructure import ground_slab, pilecap, piles, retaining_walls
    from saengine.substructure.shallow import design_tie_beam

    p = tp.profile(tp.CLAY_ON_SAND)
    pile = piles.single_pile(p, "bored", 0.5, 18.0, 1.5)
    assert piles.uplift_skin() == 0.7
    assert pile["Ta"] == pytest.approx((0.7 * pile["Qs"] + pile["W"]) / 3.0, abs=0.1)
    spec = tp.four_pile_cap()
    service = {"D + L": [np.array([1800e3, 0, 0])]}
    strength = {"1.2D + 1.6L": [np.array([2500e3, 0, 0])]}
    out = pilecap.pile_cap_design(spec, service, strength, pile, p, None, {})
    by_name = {c["name"]: c for c in out["checks"]}
    assert (by_name["Pile spacing"]["demand"], by_name["Pile spacing"]["capacity"]) == (1500, 1500)
    assert by_name["Cap edge beyond the piles"]["demand"] == 100
    assert by_name["Cover of the cap's main bars"]["demand"] == 75
    ctx = ts.two_columns(settlement=12)
    result, _ = design_tie_beam(ctx, ctx.substructure.tieBeams[0])
    assert result["force"] == pytest.approx(130)
    sizes = [c for c in result["checks"] if c["name"] == "Least size"]
    assert (sizes[0]["demand"], sizes[0]["capacity"]) == (280, 250)
    assert ground_slab.live_factor() == (1.6, "BNBC 2020 Part 6 Sec 2.7.3.1 combination 2")
    strip = retaining_walls.Strip("stem", 10.0, 5.0, 300.0, 50.0)
    assert retaining_walls.minimum_area(strip, 420.0, 16.0) == pytest.approx(0.0012 * 300e3)
    assert retaining_walls.minimum_area(strip, 420.0, 20.0) == pytest.approx(0.0015 * 300e3)
    assert retaining_walls.base_cover(50.0) == 75.0


def test_town_suggestion_pinned() -> None:
    from saengine.gis import site, towns

    s = site.suggestion(23.7104, 90.4074)
    assert (s["town"], s["zone"], s["Z"], s["windSpeed"]) == ("Dhaka", 2, 0.2, 65.7)
    assert s["settingsLocation"] == "dhaka"
    assert len(towns.TOWNS) == 75 and towns.ZONES == {0.12: 1, 0.2: 2, 0.28: 3, 0.36: 4}


# ─────────────────────────────── a second pack ───────────────────────────────


def test_a_pack_overriding_site_investigation_changes_only_the_liquefaction(tmp_path) -> None:
    pack = stub(
        tmp_path,
        {"siteInvestigation": {"liquefaction": {"rdSlope": 0.02, "fieldNLimit": 12}}},
    )
    amax, note = liquefaction.amax_from(None, 0.20, ["SD"])
    before = liquefaction.screen(profile(), amax, note)
    site_before = site_class.site_class(profile())
    ib_before = liquefaction.screen(profile("idrissBoulanger2014"), amax, note)
    with code_context.using(pack):
        assert liquefaction.amax_from(None, 0.20, ["SD"]) == (amax, note)  # seismic: unchanged
        after = liquefaction.screen(profile(), amax, note)
        assert site_class.site_class(profile()) == site_before  # same table, not overridden
        ib_after = liquefaction.screen(profile("idrissBoulanger2014"), amax, note)
    # rd = 1 - 0.02 z, and N 15 > 12 is now dense by the rule of thumb: not screened.
    assert before["points"][0]["screened"] and not after["points"][0]["screened"]
    assert "field N = 15 > 12" in after["points"][0]["reason"]
    # Idriss & Boulanger: the same FS; only the rule-of-thumb flag follows the pack.
    assert [p.get("fs") for p in ib_after["points"]] == [p.get("fs") for p in ib_before["points"]]


def test_a_pack_without_the_soil_groups_says_not_covered(tmp_path) -> None:
    pack = stub(
        tmp_path, {"siteInvestigation": {"$remove": ["liquefaction", "siteClassification"]}}
    )
    amax, note = liquefaction.amax_from(None, 0.20, ["SD"])
    with code_context.using(pack):
        screened = liquefaction.screen(profile(), amax, note)
        site = site_class.site_class(profile())
    assert any("not covered by the code pack D3 stub" in n for n in screened["notes"])
    assert screened["points"][0]["fs"] is not None  # Idriss & Boulanger used, said so
    assert site["class"] is None and "not covered by the code pack D3 stub" in site["note"]


def test_a_pack_overriding_foundations_changes_only_the_pile_cap_and_tie_rules(tmp_path) -> None:
    import test_substructure_piles as tp
    import test_substructure_shallow as ts

    from saengine.substructure import pilecap, piles
    from saengine.substructure.shallow import design_tie_beam

    pack = stub(
        tmp_path,
        {
            "foundations": {
                "upliftSkin": 0.5,
                "pileCap": {"edgeDistance": 150.0},
                "shallow": {"tieBeams": {"forceShare": 0.05}},
            }
        },
    )
    p = tp.profile(tp.CLAY_ON_SAND)
    spec = tp.four_pile_cap()
    service = {"D + L": [np.array([1800e3, 0, 0])]}
    strength = {"1.2D + 1.6L": [np.array([2500e3, 0, 0])]}

    def run() -> tuple[dict, dict, dict]:
        pile = piles.single_pile(p, "bored", 0.5, 18.0, 1.5)
        out = pilecap.pile_cap_design(spec, service, strength, pile, p, None, {})
        ctx = ts.two_columns(settlement=12)
        return (
            pile,
            {c["name"]: c for c in out["checks"]},
            design_tie_beam(ctx, ctx.substructure.tieBeams[0])[0],
        )

    pile0, cap0, tie0 = run()
    with code_context.using(pack):
        pile1, cap1, tie1 = run()
    assert pile1["Qa"] == pile0["Qa"] and pile1["Qs"] == pile0["Qs"]
    assert pile1["Ta"] == pytest.approx((0.5 * pile0["Qs"] + pile0["W"]) / 3.0, abs=0.1)
    assert cap1["Cap edge beyond the piles"]["demand"] == 150
    assert cap1["Pile spacing"] == cap0["Pile spacing"]
    assert cap1["Pile load, compression"] == cap0["Pile load, compression"]
    assert tie1["force"] == pytest.approx(tie0["force"] / 2)


def test_a_pack_without_towns_or_planning_covers_neither(tmp_path) -> None:
    from saengine.gis import planning, site

    pack = stub(tmp_path, {"locations": {"$remove": ["towns"]}})
    with code_context.using(pack):
        assert site.suggestion(23.7104, 90.4074) is None
    root = stub(tmp_path / "root", {}, extends=None)
    with code_context.using(root):
        assert planning.planning_table() is None
        with pytest.raises(ValueError, match="not covered by the code pack D3 stub"):
            planning.rules()
