"""The building code's own site rules beside the planning authority's (B23): for the bnbc2020
pack BNBC 2020 Part 3 Chapter 1, read from planning.json's ``buildingCode`` block: plinth and
formation levels (Sec 1.5.3), overhead lines (Sec 1.5.2, Table 3.1.3), open and unpaved area
(Sec 1.8.2-1.8.5), the fallback open spaces (Sec 1.8.8.1, 1.8.9, Table 3.1.5), height by road
width and construction type (Sec 1.9.2, Tables 3.1.7-3.1.8) and parking floors out of FAR
(Sec 1.9.3.3)."""

from __future__ import annotations

import json

import pytest

from saengine.codes import context as code_context
from saengine.gis import planning
from saengine.library.report_template import ReportSection, ReportTemplate
from saengine.library.soil import Site
from saengine.report.document import report_document


def _site(points=None, front=1500, rear=2000, side=1250, **plan) -> Site:
    return Site.model_validate(
        {
            "plot": {
                "points": points or [[0, 0], [15000, 0], [15000, 22000], [0, 22000]],
                "road": 0,
                "front": front,
                "rear": rear,
                "side": side,
                "planning": {"use": "A1-A4", "roadWidth": 6000, **plan},
            }
        }
    )


def _settings(construction_type: str) -> str:
    return json.dumps({"construction": {"constructionType": construction_type}})


def _by_label(result: dict) -> dict:
    return {c["label"]: c for c in result["checks"]}


def test_pack_block_cites_part_3() -> None:
    code = code_context.pack_table("planning").buildingCode
    assert code is not None and code.source.startswith("BNBC 2020 Part 3")
    for block in ("levels", "overheadLines", "openArea", "front", "setbacks", "height"):
        assert getattr(code, block).source, block


# ─────────────────────────── Sec 1.5.2, Table 3.1.3: overhead lines ───────────────────────────


@pytest.mark.parametrize(
    ("kind", "kv", "vertical", "horizontal"),
    [
        ("lowMedium", None, 2.5, 1.25),  # low to medium voltage and service lines
        ("high", 11, 3.5, 1.75),  # high voltage up to 33 kV
        ("high", 33, 3.5, 1.75),
        ("high", 66, 3.8, 2.05),  # + 0.3 for each additional 33 kV
        ("high", 132, 4.4, 2.65),  # 99 kV more: 3 steps
        ("high", 34, 3.8, 2.05),  # "or part thereof"
    ],
)
def test_overhead_line_distances(kind, kv, vertical, horizontal) -> None:
    need = planning.overhead_clearance(kind, kv)
    assert need["vertical"] == pytest.approx(vertical)
    assert need["horizontal"] == pytest.approx(horizontal)


def test_overhead_line_check() -> None:
    result = planning.check(
        _site(overheadLine={"kind": "high", "voltage": 132, "vertical": 4000, "horizontal": 3000})
    )
    assert [c["id"] for c in result["lineClasses"]] == ["lowMedium", "high"]
    checks = _by_label(result)
    assert not checks["Overhead line (High voltage lines), vertically"]["ok"]
    assert checks["Overhead line (High voltage lines), horizontally"]["ok"]
    assert not result["ok"]


# ─────────────────────────── Sec 1.5.3: plinth and formation levels ───────────────────────────


def test_plinth_at_least_450_mm_above_the_road() -> None:
    assert _by_label(planning.check(_site(plinthHeight=450)))["Plinth above the road"]["ok"]
    low = planning.check(_site(plinthHeight=300))
    assert not _by_label(low)["Plinth above the road"]["ok"] and not low["ok"]
    # flood prone: the development authority's level; not checked
    flood = planning.check(_site(plinthHeight=300, floodProne=True))
    assert "Plinth above the road" not in _by_label(flood)


def test_formation_level_between_road_and_450_mm() -> None:
    checks = _by_label(planning.check(_site(formationHeight=600)))
    assert not checks["Formation level above the road"]["ok"]
    checks = _by_label(planning.check(_site(formationHeight=-100)))
    assert not checks["Formation level not below the road"]["ok"]


# ─────────────────────────── Sec 1.8.2-1.8.5: open and unpaved area ───────────────────────────


def test_open_area_percent_by_occupancy() -> None:
    assert planning.open_area_percent("A1-A4") == 33  # Sec 1.8.4
    assert planning.open_area_percent("B1") == 50  # Sec 1.8.3 educational
    assert planning.open_area_percent("D") == 50  # health care
    assert planning.open_area_percent("C") == 50  # institutional


def test_open_area_is_advisory_under_the_authority_and_binds_by_the_code() -> None:
    # 330 m² plot, 230 m² covered: 30 % open < 33 %
    authority = _by_label(planning.check(_site(groundCoverage=230)))
    assert not authority["Open area"]["ok"] and authority["Open area"]["advisory"]
    code = planning.check(_site(groundCoverage=230, rules="code"))
    assert not _by_label(code)["Open area"]["advisory"] and not code["ok"]


def test_unpaved_half_of_minimum_open_space() -> None:
    # authority: 4-5 katha on a 6 m road, MGC 62.5 %: minimum open space 123.75 m² (> 33 %),
    # half of it unpaved: 61.875 m²
    checks = _by_label(planning.check(_site(groundCoverage=200, unpavedArea=60)))
    assert checks["Unpaved open area"]["limit"] == pytest.approx(61.875)
    assert not checks["Unpaved open area"]["ok"] and not checks["Unpaved open area"]["advisory"]
    # building code only: 33 % of 330 m² = 108.9 m², half: 54.45 m²
    code = _by_label(planning.check(_site(groundCoverage=200, unpavedArea=60, rules="code")))
    assert code["Unpaved open area"]["limit"] == pytest.approx(54.45)
    assert code["Unpaved open area"]["ok"]


# ─────────────────────────── Sec 1.8.8-1.8.9, Table 3.1.5: fallback open spaces ──────────────────


@pytest.mark.parametrize(
    ("use", "area", "height", "storeys", "typology", "rear", "side"),
    [
        ("A1-A4", 60, 9, 3, "row", 1.25, 0.0),  # row type up to 67 m²: side nil
        ("A1-A4", 100, 9, 3, "row", 1.5, 0.0),
        ("A1-A4", 200, 20, 6, "semiDetached", 2.5, 2.5),  # PG, 2.5
        ("A1-A4", 300, 20, 6, "semiDetached", 3.0, 2.5),
        ("A1-A4", 200, 20, 6, "detached", 2.5, 1.25),
        ("A1-A4", 300, 20, 6, "detached", 3.0, 1.25),
        ("A1-A4", 300, 40, 12, "detached", 3.0, 3.0),  # higher than 10 storeys or 33 m
        ("C", 500, 20, 6, "detached", 3.0, 3.0),  # institution for care
        ("B1", 500, 20, 6, "detached", 3.0, 3.0),  # educational
        ("E", 500, 20, 6, "detached", 3.0, 3.0),  # assembly
        ("F1", 500, 20, 6, "semiDetached", 1.5, 3.0),  # PG, 3.0
        ("F1", 500, 20, 6, "detached", 1.5, 2.5),  # 1.25, 2.5: the larger
        ("F2-F5", 600, 40, 12, "semiDetached", 3.0, 6.0),  # over 536 m², tall: PG, 6.0
        ("F1", 600, 40, 12, "detached", 3.0, 3.0),
    ],
)
def test_table_3_1_5(use, area, height, storeys, typology, rear, side) -> None:
    result = planning.code_setbacks(use, area, height, storeys, 6.0, typology)
    assert result["covered"]
    assert result["rear"] == pytest.approx(rear)
    assert result["side"] == pytest.approx(side)


def test_semi_detached_links_the_pounding_gap_to_the_seismic_separation() -> None:
    result = planning.code_setbacks("A1-A4", 200, 20, 6, 6.0, "semiDetached")
    assert result["sides"][0] is None
    assert any("2.5.14.3" in n and "Seismic" in n for n in result["notes"])


def test_table_3_1_5_gaps_are_not_checked() -> None:
    # industrial: by the other provisions; a tall residential on a small plot: no row
    assert not planning.code_setbacks("G-K", 600, 20, 6, 6.0)["covered"]
    small = planning.code_setbacks("A1-A4", 200, 40, 12, 6.0, "detached")
    assert not small["covered"] and small["notes"]


def test_front_open_space_sec_1_8_8_1() -> None:
    # 4.5 m from the centre of a 6 m road (1.5 m from the line), at least 1.5 m
    assert planning.code_setbacks("A1-A4", 300, 20, 6, 6.0)["front"] == pytest.approx(1.5)
    assert planning.code_setbacks("A1-A4", 300, 20, 6, 3.0)["front"] == pytest.approx(3.0)


def test_code_rules_replace_the_authority_setbacks() -> None:
    # 330 m² detached residential by the code: rear 3.0 m (the plot gives 2.0), side 1.25 m
    result = planning.check(_site(rules="code", groundCoverage=200, floorArea=1000))
    assert result["setbacks"]["required"] == {"front": 1.5, "rear": 3.0, "side": 1.25}
    checks = _by_label(result)
    assert not checks["Rear setback"]["ok"] and "Table 3.1.5" in checks["Rear setback"]["rule"]
    assert "FAR" not in checks and "permitted" not in result


# ─────────────────────────── Sec 1.9.2, Tables 3.1.7-3.1.8: height ───────────────────────────


@pytest.mark.parametrize(
    ("ctype", "road", "front", "storeys", "height"),
    [
        ("I-A", 3.0, 2.0, 3, 11),  # 2 × 5 = 10 m: below 10.6 m
        ("I-B", 6.0, 1.5, 5, 17),  # 15 m: 13.6 to below 16.6 m
        ("I-A", 12.0, 3.0, 10, 32),  # 30 m: 28.6 to below 31.6 m
        ("I-A", 20.0, 3.0, 15, 48),  # 46 m: 43.6 to below 46.6 m
        ("I-A", 21.0, 3.0, 16, 51),  # 48 m: 46.6 to below 49.6 m, the next 3 m step
        ("I-A", 22.0, 3.0, 17, 54),  # 50 m: 49.6 to below 52.6 m
        ("I-C", 6.0, 1.5, 4, 14),  # Sec 1.9.2.3: 4 storeys or 14 m from 13.6 m
        ("I-C", 5.0, 1.0, 3, 11),  # 12 m: 10.6 to below 13.6 m
        ("I-D", 6.0, 1.5, 3, 11),  # Sec 1.9.2.4: 3 storeys or 11 m
        ("II-B", 4.0, 1.0, 2, 8),  # 10 m: below 10.6 m
        ("I-E", 20.0, 3.0, 1, 8),  # unprotected: 1 storey, 8 m (note *)
        ("II-E", 20.0, 3.0, 1, 8),
    ],
)
def test_table_3_1_7(ctype, road, front, storeys, height) -> None:
    limit = planning.height_limit(ctype, road, front)
    assert (limit["storeys"], limit["height"]) == (storeys, height)


def test_height_check_reads_the_construction_type_setting() -> None:
    # 6 m road + 1.5 m front: 15 m basis: type I-C up to 4 storeys and 14 m
    site = _site(height=17000, storeys=5)
    result = planning.check(site, None, _settings("I-C"))
    checks = _by_label(result)
    assert result["heightLimit"]["storeys"] == 4
    assert not checks["Building height"]["ok"] and not checks["Storeys"]["ok"]
    assert not result["ok"]
    # I-A: 5 storeys and 17 m
    assert planning.check(site, None, _settings("I-A"))["heightLimit"]["height"] == 17
    # not classified: a note, no check
    unset = planning.check(site, None, None)
    assert "Building height" not in _by_label(unset)
    assert any("construction type" in n for n in unset["notes"])


def test_unlimited_height_on_a_23_m_road_needs_table_3_1_8() -> None:
    site = _site(
        points=[[0, 0], [40000, 0], [40000, 40000], [0, 40000]],
        roadWidth=24000,
        approvedArea=True,
        height=60000,
        storeys=18,
        front=4000,
        rear=5000,
        side=4000,
    )
    assert planning.unlimited_height("A1-A4", "I-A", 24.0, True)
    assert not planning.unlimited_height("A1-A4", "I-C", 24.0, True)
    assert not planning.unlimited_height("A1-A4", "I-A", 20.0, True)
    result = planning.check(site, None, _settings("I-A"))
    checks = _by_label(result)
    assert "Building height" not in checks
    rear = checks["Rear open space (unlimited height or FAR)"]
    assert rear["limit"] == 6.0 and not rear["ok"]  # Table 3.1.8 residential rear 6.0 m
    assert checks["Side open space (unlimited height or FAR)"]["ok"]


def test_unlimited_far_applies_table_3_1_8() -> None:
    # Bidhimala Table 3(E): offices on an 18 m road: FAR NR -> Table 3.1.8 business 6/6/6 m
    site = _site(
        points=[[0, 0], [50000, 0], [50000, 50000], [0, 50000]],
        use="F1",
        roadWidth=18000,
    )
    checks = _by_label(planning.check(site))
    assert checks["Front open space (unlimited height or FAR)"]["limit"] == 6.0


# ─────────────────────────── Sec 1.9.3.3: parking floors out of FAR ───────────────────────────


def test_parking_floors_are_left_out_of_far() -> None:
    result = planning.check(
        _site(groundCoverage=200, floorArea=1300, excludedArea=20, parkingArea=180)
    )
    assert result["areas"]["farArea"] == pytest.approx(1100.0)
    assert result["areas"]["parking"] == 180
    assert _by_label(result)["FAR"]["ok"]  # 1100 / 330 = 3.33 ≤ 3.50
    assert any("1.9.3.3" in n for n in result["notes"])


def test_report_marks_advisory_checks() -> None:
    result = planning.check(_site(groundCoverage=230, parkingArea=50, floorArea=900))
    only = ReportTemplate(sections=[ReportSection(id="planning")])
    document = report_document({"planning": result, "warnings": []}, only)
    text = json.dumps(document)
    assert "advisory" in text and "Less parking floors" in text
