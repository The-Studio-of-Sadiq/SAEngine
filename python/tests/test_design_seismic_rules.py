"""Which earthquake-resistant detailing provisions apply (saengine.design.seismic_rules) to
BNBC 2020 Part 6 Sec 8.3 (pp. 1088-1123) with Sec 2.5.5 (Table 6.2.18, p. 617; Table 6.2.19,
pp. 621-624) and Sec 2.5.13.4 (p. 646), against hand-worked values.

The projects are synthetic (default settings with the location, site class, occupancy and
system set per test; small libraries written here); the shipped sample is checked too.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.design import seismic_rules as sr
from saengine.library.bim import BuildingModel
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings, default_project_settings

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def settings(
    location: str = "dhaka",
    site: str = "SD",
    occupancy: str = "II",
    system: str = "rcSmf",
    z: float | None = None,
) -> ProjectSettings:
    s = default_project_settings("Test")
    s.site.location = location
    s.site.siteClass = site
    s.site.siteClassSource = "entered"
    s.site.zoneCoefficient = z
    s.occupancy.category = occupancy
    s.seismic.system = system
    return s


def concrete(mid: str, fc: float, density: float = 2400) -> dict:
    return {
        "id": mid,
        "name": mid,
        "category": "concrete",
        "mechanical": {"E": 25000, "density": density},
        "concrete": {"fc": fc},
    }


def rebar(mid: str, fy: float, fu: float | None = None, elongation: float | None = None) -> dict:
    steel: dict = {"fy": fy, "grade": mid}
    if fu is not None:
        steel["fu"] = fu
    if elongation is not None:
        steel["elongation"] = elongation
    return {
        "id": mid,
        "name": mid,
        "category": "rebar",
        "mechanical": {"E": 200000},
        "steel": steel,
    }


def library(*materials: dict) -> MaterialLibrary:
    return MaterialLibrary.model_validate({"materials": list(materials)})


def objects(conc: str = "C28", bars: str = "R420", dia: float = 16, flat: bool = False):
    reinforcement = {
        "material": bars,
        "cover": 40,
        "longitudinal": [{"position": "perimeter", "count": 8, "dia": dia}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 100, "legs": 2},
    }
    data = {
        "objects": [
            {
                "id": "COL",
                "kind": "column",
                "name": "Column",
                "material": conc,
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                "reinforcement": reinforcement,
            },
            {
                "id": "BM",
                "kind": "beam",
                "name": "Beam",
                "material": conc,
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                "reinforcement": {
                    **reinforcement,
                    "longitudinal": [
                        {"position": "top", "count": 3, "dia": dia},
                        {"position": "bottom", "count": 3, "dia": dia},
                    ],
                },
            },
        ]
    }
    if flat:
        data["objects"].append(
            {
                "id": "FS",
                "kind": "slab",
                "name": "Flat slab",
                "material": conc,
                "thickness": 200,
                "system": "flat",
            }
        )
    return ObjectLibrary.model_validate(data)


def frame(planted: bool = False, height: float = 3000) -> BuildingModel:
    """Two columns 6 m apart with a beam on top; with ``planted`` a third column standing on the
    middle of the beam, up to the next floor."""
    elements = [
        {
            "id": "CA",
            "kind": "column",
            "type": "COL",
            "position": [0, 0],
            "bottom": 0,
            "top": height,
        },
        {
            "id": "CB",
            "kind": "column",
            "type": "COL",
            "position": [6000, 0],
            "bottom": 0,
            "top": height,
        },
        {
            "id": "B1",
            "kind": "beam",
            "type": "BM",
            "start": [0, 0],
            "end": [6000, 0],
            "elevation": height,
        },
    ]
    if planted:
        elements.append(
            {
                "id": "CU",
                "kind": "column",
                "type": "COL",
                "position": [3000, 0],
                "bottom": height,
                "top": 2 * height,
            }
        )
    return BuildingModel.model_validate({"elements": elements})


GOOD = library(concrete("C28", 28), rebar("R420", 420, 550, 16))


def by_name(checks: list[dict], start: str) -> list[dict]:
    return [c for c in checks if c["name"].startswith(start)]


# ───────────────────────────── Seismic Design Category (Table 6.2.18) ─────────────────────────


@pytest.mark.parametrize(
    ("location", "site", "occupancy", "expected", "zone"),
    [
        ("rajshahi", "SA", "II", "B", 1),  # zone 1, SA, I-III: B
        ("rajshahi", "SA", "IV", "C", 1),  # zone 1, SA, IV: C
        ("rajshahi", "SD", "II", "C", 1),  # zone 1, SD: C
        ("dhaka", "SC", "II", "C", 2),  # zone 2, SC: C
        ("dhaka", "SD", "III", "D", 2),  # zone 2, SD: D
        ("chattogram", "SA", "II", "C", 3),  # zone 3, SA: C
        ("chattogram", "SB", "II", "D", 3),  # zone 3, SB: D
        ("sylhet", "SA", "I", "D", 4),  # zone 4: D
        ("khulna", "SE", "II", "D", 1),  # SE: D everywhere
    ],
)
def test_seismic_design_category(location, site, occupancy, expected, zone) -> None:
    assert sr.seismic_design_category(settings(location, site, occupancy)) == (expected, zone)


def test_category_from_an_entered_z() -> None:
    # Z = 0.30 is nearest zone 3's 0.28: SC, II → D.
    s = settings("custom", "SC", z=0.30)
    assert sr.seismic_design_category(s) == ("D", 3)


def test_custom_location_without_z_has_no_category() -> None:
    out = sr.seismic_detailing_scope(settings("custom"), GOOD, objects(), frame())
    assert out["sdc"] is None
    assert any("custom location without Z" in n for n in out["notes"])


# ───────────────────────────── the system (Table 6.2.19, Sec 8.3.2) ─────────────────────────


def test_sample_project() -> None:
    """The sample: Chattogram (zone 3), site class SD, occupancy II → Category D; an RC
    intermediate moment frame (R 5, Ω0 3, Cd 4.5) is NP in D, so it fails and the members are
    checked to the special provisions; f'c 20.7 MPa < 21 MPa."""

    def read(name: str) -> str:
        return (SAMPLE / name).read_text(encoding="utf-8")

    s = ProjectSettings.model_validate_json(read("02 Project Settings/project-settings.json"))
    out = sr.seismic_detailing_scope(
        s,
        MaterialLibrary.model_validate_json(read("03 Materials/materials.json")),
        ObjectLibrary.model_validate_json(read("04 Objects/objects.json")),
        BuildingModel.model_validate_json(read("06 BIM/bim.json")),
    )
    assert (out["system"], out["sdc"], out["zone"]) == ("rcSmf", "D", 2)
    assert (out["R"], out["Omega0"], out["Cd"]) == (8.0, 3.0, 5.5)
    assert out["systemFrameType"] == "special"
    assert out["frameType"] == out["requiredFrameType"] == "special"
    # A special moment frame is permitted in Category D (Table 6.2.19 row C.4, p. 623): no
    # "System permitted" check is reported; the sample's C24.1 meets f'c ≥ 21 MPa.
    assert not any(not c["ok"] for c in by_name(out["checks"], "System permitted"))
    fc = by_name(out["checks"], "f'c ≥ 21 MPa")[0]
    assert fc["name"].endswith("C24.1") and fc["ok"]
    assert fc["utilisation"] == pytest.approx(21 / 24.1, abs=1e-3)
    assert out["height"] == pytest.approx(6.4)
    # C7 stands 150 mm off C1, inside C1's 400 mm section: an eccentricity, no transfer.
    assert out["discontinuities"] == []
    assert all(m["role"] == "lateral" for m in out["members"].values())
    assert out["applies"]["8.3.4"]["applies"] and out["applies"]["8.3.11"]["applies"]
    assert not out["applies"]["8.3.10"]["applies"]


def test_imf_in_category_c() -> None:
    out = sr.seismic_detailing_scope(
        settings("dhaka", "SC", system="rcImf"), GOOD, objects(), frame()
    )
    assert out["sdc"] == "C" and out["frameType"] == "intermediate"
    assert by_name(out["checks"], "System permitted") == []
    applies = {k for k, v in out["applies"].items() if v["applies"]}
    assert applies == {"8.3.10"}
    # 8.3.3.3/8.3.3.4 are for special frames and special walls only.
    assert by_name(out["checks"], "f'c") == []
    assert out["members"]["CA"]["provisions"] == ["8.3.10"]


def test_omf_not_permitted_in_category_c() -> None:
    out = sr.seismic_detailing_scope(
        settings("dhaka", "SC", system="rcOmf"), GOOD, objects(), frame()
    )
    check = by_name(out["checks"], "System permitted")[0]
    assert not check["ok"] and "C.5" in check["note"] and "intermediate" in check["note"]
    # Checked to what Category C requires.
    assert out["frameType"] == "intermediate"


def test_omf_in_category_b() -> None:
    out = sr.seismic_detailing_scope(
        settings("rajshahi", "SA", system="rcOmf"), GOOD, objects(), frame()
    )
    assert out["sdc"] == "B" and out["frameType"] == "ordinary"
    assert [c for c in out["checks"] if not c["ok"]] == []
    assert out["applies"]["8.3.9"]["applies"] and not out["applies"]["8.3.11"]["applies"]
    assert out["members"]["B1"]["provisions"] == ["8.3.9"]


def test_smf_in_category_b_uses_special_detailing() -> None:
    # 8.3.2(e): a lower category may use the detailing of a higher one.
    out = sr.seismic_detailing_scope(settings("rajshahi", "SA"), GOOD, objects(), frame())
    assert out["sdc"] == "B" and out["frameType"] == "special"
    assert any("8.3.2(e)" in n for n in out["notes"])
    assert out["members"]["CA"]["provisions"] == ["8.3.5", "8.3.7", "8.3.8"]
    assert out["members"]["B1"]["provisions"] == ["8.3.4", "8.3.8"]


def test_height_limit_of_a_wall_frame_system() -> None:
    """B.5 building frame with special RC walls: 50 m in Category D; 60 m fails (60/50)."""
    out = sr.seismic_detailing_scope(
        settings(system="rcSpecialWallFrame"), GOOD, objects(), frame(), height=60
    )
    check = by_name(out["checks"], "Height limit")[0]
    assert (check["demand"], check["capacity"]) == (60, 50)
    assert check["utilisation"] == pytest.approx(1.2) and not check["ok"]
    # The beams and columns of a building frame system are gravity members: in D 8.3.3.1(d)
    # sends them to 8.3.9 and 8.3.12.1(a) adds 8.3.12.
    assert {m["role"] for m in out["members"].values()} == {"gravity"}
    assert out["members"]["CA"]["provisions"] == ["8.3.9", "8.3.12"]
    applies = out["applies"]
    assert applies["8.3.12"]["applies"] and applies["8.3.6"]["applies"]
    assert applies["8.3.3"]["applies"] and applies["8.3.9"]["applies"]
    # No special moment frame: its sections and its material rules do not apply to the frames.
    assert out["frameType"] is None and out["detailingLevel"] == "special"
    assert not any(applies[s]["applies"] for s in ("8.3.4", "8.3.5", "8.3.7", "8.3.8"))
    assert [c for c in out["checks"] if "8.3.3" in c["name"]] == []
    ok = sr.seismic_detailing_scope(
        settings(system="rcSpecialWallFrame"), GOOD, objects(), frame(height=3000)
    )
    assert by_name(ok["checks"], "Height limit")[0]["ok"]


def test_ordinary_wall_frame_cd_matches_the_table() -> None:
    # library/bnbc.py now has Cd 4.25 of Table 6.2.19 row B.6 (p. 622), so no note is left.
    out = sr.seismic_detailing_scope(
        settings("dhaka", "SC", system="rcOrdinaryWallFrame"), GOOD, objects(), frame()
    )
    assert out["Cd"] == 4.25
    assert not any(n.startswith("Cd of") for n in out["notes"])


def test_flat_slab_in_a_special_moment_frame() -> None:
    building = frame()
    building.elements.append(
        BuildingModel.model_validate(
            {
                "elements": [
                    {
                        "id": "S1",
                        "kind": "slab",
                        "type": "FS",
                        "boundary": [[0, 0], [6000, 0], [6000, 5000]],
                        "elevation": 3000,
                    }
                ]
            }
        ).elements[0]
    )
    out = sr.seismic_detailing_scope(settings(), GOOD, objects(flat=True), building)
    check = by_name(out["checks"], "Slabs without beams")[0]
    assert check["flag"] and "FS" in check["note"]


def test_steel_system_has_no_rc_provisions() -> None:
    out = sr.seismic_detailing_scope(settings(system="steelSmf"), GOOD, objects(), frame())
    assert out["frameType"] is None
    assert not any(v["applies"] for v in out["applies"].values())


# ───────────────────────────── materials (Sec 8.3.3.3, 8.3.3.4) ─────────────────────────


def test_good_materials_pass() -> None:
    out = sr.seismic_detailing_scope(settings(), GOOD, objects(), frame())
    material = [c for c in out["checks"] if "8.3.3" in c["name"]]
    assert len(material) == 6
    assert all(c["ok"] for c in material)
    ratio = by_name(material, "fu/fy")[0]
    assert ratio["capacity"] == pytest.approx(550 / 420, abs=0.01)
    assert ratio["utilisation"] == pytest.approx(1.25 / (550 / 420), abs=1e-3)


def test_concrete_limits() -> None:
    lib = library(concrete("C28", 20), rebar("R420", 420, 550, 16))
    out = sr.seismic_detailing_scope(settings(), lib, objects(), frame())
    assert not by_name(out["checks"], "f'c ≥ 21 MPa")[0]["ok"]
    light = library(concrete("C28", 40, density=1800), rebar("R420", 420, 550, 16))
    out = sr.seismic_detailing_scope(settings(), light, objects(), frame())
    check = by_name(out["checks"], "Lightweight f'c ≤ 35 MPa")[0]
    assert check["utilisation"] == pytest.approx(40 / 35, abs=1e-3) and not check["ok"]
    assert (
        by_name(
            sr.seismic_detailing_scope(settings(), GOOD, objects(), frame())["checks"],
            "Lightweight",
        )
        == []
    )


def test_grade_500_not_permitted() -> None:
    lib = library(concrete("C28", 28), rebar("R500", 500, 650, 16))
    out = sr.seismic_detailing_scope(settings(), lib, objects(bars="R500"), frame())
    check = by_name(out["checks"], "Reinforcement grade")[0]
    assert check["utilisation"] == pytest.approx(500 / 420, abs=1e-3) and not check["ok"]


def test_grade_410_is_not_a_listed_grade() -> None:
    lib = library(concrete("C28", 28), rebar("R410", 410, 600, 16))
    out = sr.seismic_detailing_scope(settings(), lib, objects(bars="R410"), frame())
    assert not by_name(out["checks"], "Reinforcement grade")[0]["ok"]


def test_tensile_ratio_and_elongation() -> None:
    # fu/fy = 500/420 = 1.190 < 1.25; 16 mm bars need 14 %, 12 % given.
    lib = library(concrete("C28", 28), rebar("R420", 420, 500, 12))
    out = sr.seismic_detailing_scope(settings(), lib, objects(), frame())
    ratio = by_name(out["checks"], "fu/fy")[0]
    assert ratio["utilisation"] == pytest.approx(1.25 / (500 / 420), abs=1e-3)
    assert not ratio["ok"]
    elongation = by_name(out["checks"], "Elongation")[0]
    assert (elongation["demand"], elongation["capacity"]) == (14, 12) and not elongation["ok"]
    # 25 mm bars need 12 %.
    out = sr.seismic_detailing_scope(settings(), lib, objects(dia=25), frame())
    assert by_name(out["checks"], "Elongation")[0]["ok"]


def test_missing_mill_values_are_flags() -> None:
    lib = library(concrete("C28", 28), rebar("R420", 420))
    out = sr.seismic_detailing_scope(settings(), lib, objects(), frame())
    for start in ("Actual fy", "fu/fy", "Elongation"):
        check = by_name(out["checks"], start)[0]
        assert check["flag"] and check["ok"]


def test_mill_test_values_when_the_material_has_them() -> None:
    """Integrator's optional steel.fyActual / fuActual: 560 > 420 + 125 fails; 700/560 = 1.25."""
    lib = library(concrete("C28", 28), rebar("R420", 420, 550, 16))
    lib.materials[1].steel.__dict__.update(fyActual=560.0, fuActual=700.0)
    out = sr.seismic_detailing_scope(settings(), lib, objects(), frame())
    actual = by_name(out["checks"], "Actual fy")[0]
    assert (actual["demand"], actual["capacity"]) == (560, 545) and not actual["ok"]
    assert by_name(out["checks"], "fu/fy")[0]["capacity"] == pytest.approx(1.25)


@pytest.mark.parametrize(
    ("dia", "need"), [(8, 14), (10, 14), (20, 14), (22, 12), (36, 12), (40, 10)]
)
def test_required_elongation(dia, need) -> None:
    assert sr.required_elongation(dia) == need


# ───────────────────────────── members (8.3.12) and Ω0 (2.5.5.6) ─────────────────────────


def test_planted_column_is_found() -> None:
    out = sr.seismic_detailing_scope(settings(), GOOD, objects(), frame(planted=True))
    assert out["discontinuities"] == [
        {
            "id": "CU",
            "kind": "column",
            "elevation": 3000.0,
            "supportedBy": ["B1"],
            "supportColumns": ["CA", "CB"],
        }
    ]
    assert out["omega"]["elements"] == ["B1", "CA", "CB"]
    assert out["members"]["B1"]["omega"] == "transfer"
    assert out["members"]["CU"]["omega"] is None
    assert out["omega"]["combinations"]


def test_overrides() -> None:
    out = sr.seismic_detailing_scope(
        settings(),
        GOOD,
        objects(),
        frame(planted=True),
        overrides={"B1": {"omega": "none"}, "CA": {"role": "gravity"}},
    )
    assert out["members"]["B1"]["omega"] is None
    assert out["members"]["CA"]["role"] == "gravity"
    assert out["members"]["CA"]["provisions"] == ["8.3.9", "8.3.12"]
    assert out["applies"]["8.3.12"]["applies"] and out["applies"]["8.3.9"]["applies"]
    # The other members stay special moment frame members.
    assert out["applies"]["8.3.4"]["applies"] and out["frameType"] == "special"


def test_element_and_type_flags() -> None:
    """The fields the integrator adds (``seismicRole``, ``omegaCombinations``), read from an
    element or its type when present."""
    base = frame()
    elements = [SimpleNamespace(**e.model_dump()) for e in base.elements]
    elements[0].seismicRole = "gravity"
    elements[2].omegaCombinations = "collector"
    building = SimpleNamespace(elements=elements, additions=None)
    out = sr.seismic_detailing_scope(settings(), GOOD, objects(), building)
    assert out["members"]["CA"]["role"] == "gravity"
    assert out["members"]["CA"]["roleSource"] == "element"
    assert out["members"]["B1"]["omega"] == "collector"
    # A collector needs Ω0 in Category C and D only.
    out = sr.seismic_detailing_scope(settings("rajshahi", "SA"), GOOD, objects(), building)
    assert out["members"]["B1"]["omega"] is None


def test_omega_combinations_by_hand() -> None:
    """Chattogram Z = 0.28, SD S = 1.35: a_h = (2/3)(0.28)(1.35) = 0.252, Ev = 0.126 D; Ω0 = 3
    (rcSmf). 1.2D + 1.0EX + 1.0L → 1.326D + 3EX + 1.0L; 0.9D + 1.0EX → 0.774D + 3EX."""
    s = settings("chattogram")
    found = {c["name"]: c for c in sr.omega_combinations(s)}
    upper = found["Ω0: 1.2D + 1.0EX + 1.0L"]
    assert upper["D"] == pytest.approx(1.326) and upper["EX"] == pytest.approx(3.0)
    assert upper["L"] == 1.0 and upper["F"] == pytest.approx(1.326)
    lower = found["Ω0: 0.9D + 1.0(-EY)"]
    assert lower["D"] == pytest.approx(0.774) and lower["EY"] == pytest.approx(-3.0)
    assert lower["F"] == 0
    # 2 earthquake combinations × 4 directions.
    assert len(found) == 8
    # They are LoadCombinations (the clause aside).
    from saengine.library.settings import LoadCombination

    LoadCombination(**{k: v for k, v in upper.items() if k != "clause"})


def test_omega_rs_combinations() -> None:
    s = settings("chattogram")
    rs = [
        {
            "name": "1.326D + 1.0L ± 1.0E(RS EX)",
            "loads": {"D": 1.326, "L": 1.0},
            "envelope": {"RX": 1.0, "AX": 1.1},
        },
        {"name": "0.9D ± 1.0E(RS EX)", "loads": {"D": 0.9}, "envelope": {"RX": 1.0}},
    ]
    upper, lower = sr.omega_rs_combinations(rs, s)
    assert upper["envelope"] == {"RX": 3.0, "AX": pytest.approx(3.3)}
    assert upper["loads"] == {"D": pytest.approx(1.326), "L": 1.0}
    # Ev is in Em even where the response spectrum design left it out (0.9D here).
    assert lower["loads"]["D"] == pytest.approx(0.774)


def test_gravity_members_by_category() -> None:
    """8.3.2(d): in B all RC structures follow 8.3.9; in C 8.3.2(c) asks for 8.3.10 only and
    8.3.10.1 covers the earthquake frames: BNBC sets no 8.3 provision for gravity members."""
    gravity = {"CA": {"role": "gravity"}}
    out = sr.seismic_detailing_scope(
        settings("dhaka", "SC", system="rcImf"), GOOD, objects(), frame(), overrides=gravity
    )
    assert out["members"]["CA"]["provisions"] == []
    assert out["members"]["CB"]["provisions"] == ["8.3.10"]
    assert not out["applies"]["8.3.9"]["applies"] and not out["applies"]["8.3.12"]["applies"]
    out = sr.seismic_detailing_scope(
        settings("rajshahi", "SA", system="rcOmf"), GOOD, objects(), frame(), overrides=gravity
    )
    assert out["members"]["CA"]["provisions"] == ["8.3.9"]
    assert out["applies"]["8.3.9"]["members"] == "lateral members, gravity members"


def test_system_check_names_the_row_page() -> None:
    # B.6 ordinary RC shear walls is NP in D on p. 622 (not 623).
    out = sr.seismic_detailing_scope(
        settings(system="rcOrdinaryWallFrame"), GOOD, objects(), frame()
    )
    check = by_name(out["checks"], "System permitted")[0]
    assert "row B.6 (p. 622)" in check["name"] and not check["ok"]
    out = sr.seismic_detailing_scope(settings(system="rcImf"), GOOD, objects(), frame())
    assert "row C.5 (p. 623)" in by_name(out["checks"], "System permitted")[0]["name"]


def test_grade_415_taken_as_grade_420_with_a_warning() -> None:
    # 60 ksi = 413.7 MPa, often entered as 415: within 2 % of 420 → a flag, not a failure.
    lib = library(concrete("C28", 28), rebar("R415", 415, 550, 16))
    out = sr.seismic_detailing_scope(settings(), lib, objects(bars="R415"), frame())
    check = by_name(out["checks"], "Reinforcement grade")[0]
    assert check["ok"] and check["flag"] and "Grade 420" in check["note"]
    assert check["utilisation"] == pytest.approx(415 / 420, abs=1e-3)


def wall_objects(structural: bool, material: str) -> ObjectLibrary:
    lib = objects()
    lib.objects.append(
        ObjectLibrary.model_validate(
            {
                "objects": [
                    {
                        "id": "W",
                        "kind": "wall",
                        "name": "Wall",
                        "material": material,
                        "thickness": 125 if not structural else 200,
                        "structural": structural,
                    }
                ]
            }
        ).objects[0]
    )
    return lib


def wall_on_beam() -> BuildingModel:
    """The frame of :func:`frame` with a wall on beam B1 up to the next floor, nothing under
    it but the beam (an open ground floor)."""
    building = frame()
    building.elements.append(
        BuildingModel.model_validate(
            {
                "elements": [
                    {
                        "id": "W1",
                        "kind": "wall",
                        "type": "W",
                        "start": [0, 0],
                        "end": [6000, 0],
                        "bottom": 3000,
                        "top": 6000,
                    }
                ]
            }
        ).elements[0]
    )
    return building


BRICK = {"id": "BRICK", "name": "Brick", "category": "masonry", "masonry": {"unit": "brick"}}


def test_partition_on_a_beam_is_not_a_discontinuous_wall() -> None:
    """A brick partition on a floor beam over an open ground floor: infill, not a wall of the
    seismic force-resisting system (2.5.5.6.1 concerns those): no Ω0 members."""
    lib = library(concrete("C28", 28), rebar("R420", 420, 550, 16), BRICK)
    for structural in (False, True):  # a partition type; a brick type marked structural
        out = sr.seismic_detailing_scope(
            settings(), lib, wall_objects(structural, "BRICK"), wall_on_beam()
        )
        assert out["discontinuities"] == [] and out["omega"]["elements"] == []
    # A structural RC wall standing on the beam is a discontinuous wall.
    out = sr.seismic_detailing_scope(settings(), lib, wall_objects(True, "C28"), wall_on_beam())
    assert [d["id"] for d in out["discontinuities"]] == ["W1"]
    assert out["omega"]["elements"] == ["B1", "CA", "CB"]
