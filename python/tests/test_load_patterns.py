"""Issue #301: the project's own load patterns (load cases) beside D, SD, L and Lr.

Known answers by hand:

- a simply supported beam (L = 6 m, 300 × 500 concrete) with a 30 kN "Equipment" point load at
  midspan in the user pattern EQP, combined 1.2D + 1.6EQP: M_mid = 1.2·wL²/8 + 1.6·PL/4;
- the one-bay frame of ``test_line_loads`` with the same point load on a beam: the EQP case's
  base reaction is P, and 1.2D + 1.6EQP's is 1.2·ΣD + 1.6·P.

And old projects: settings and member loads without patterns read and write unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from saengine.fem.combinations import DesignCombination, combination_factors, evaluate, model_cases
from saengine.library import line_loads as ll
from saengine.library import load_patterns as lp
from saengine.library.settings import (
    AreaLoad,
    LoadCombination,
    LoadPattern,
    ProjectSettings,
    default_project_settings,
    project_strength_combinations,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SETTINGS = (
    ROOT
    / "workbench/resources/saengine/samples/Sample Frame/02 Project Settings/project-settings.json"
)
P_KN = 30.0
EQP = LoadPattern(id="EQP", name="Equipment", type="Other")


def with_patterns(settings: ProjectSettings, *patterns: LoadPattern, **update) -> ProjectSettings:
    """``settings`` with these load patterns (validated, as a saved file is read)."""
    data = settings.model_dump(mode="json", by_alias=True)
    data["loadPatterns"] = [p.model_dump(mode="json") for p in patterns]
    data.update(update)
    return ProjectSettings.model_validate(data)


# ── the model ──


def test_patterns_are_checked() -> None:
    base = default_project_settings("P")
    with pytest.raises(ValidationError, match="codes the program uses"):
        with_patterns(base, LoadPattern(id="LP1", name="clash"))
    with pytest.raises(ValidationError, match="codes the program uses"):
        with_patterns(base, LoadPattern(id="sd", name="clash"))
    with pytest.raises(ValidationError, match="duplicate load pattern"):
        with_patterns(base, EQP, EQP)
    combo = {"name": "1.2D + 1.6X", "D": 1.2, "F": 0.0, "patterns": {"X": 1.6}}
    with pytest.raises(ValidationError, match="no load pattern X"):
        with_patterns(base, EQP, combinations=[combo])
    ok = with_patterns(base, EQP, combinations=[{**combo, "patterns": {"EQP": 1.6}}])
    assert combination_factors(ok.combinations[0]) == {"D": 1.2, "SD": 1.2, "EQP": 1.6}
    # A model derived before EQP was added has no EQP results: left out, as optional cases are.
    assert "EQP" not in combination_factors(ok.combinations[0], present={"D", "SD"})


def test_member_loads_take_any_pattern_id() -> None:
    loads = ll.MemberLoads.model_validate(
        {
            "loads": [
                {
                    "id": "T",
                    "story": "L1",
                    "member": "B1",
                    "kind": "point",
                    "value": 30,
                    "distance": 3000,
                    "case": "EQP",
                }
            ]
        }
    )
    assert loads.loads[0].case == "EQP"
    with pytest.raises(ValidationError):
        ll.MemberLoads.model_validate(
            {"loads": [{"id": "T", "story": "L1", "member": "B1", "value": 3, "case": "1x"}]}
        )


def test_generated_combinations_take_patterns_by_type() -> None:
    """The code pack's rows give a Dead pattern D's factor and a Live one L's; Other none."""
    base = default_project_settings("P")
    settings = with_patterns(
        base,
        LoadPattern(id="CONST", name="Construction", type="Live"),
        LoadPattern(id="TANK", name="Water tank", type="Dead"),
        EQP,
    )
    for c in project_strength_combinations(settings):
        own = c.patterns
        assert "EQP" not in own  # Other: only the factors the engineer gives it
        assert own.get("TANK", 0.0) == pytest.approx(c.D)
        assert own.get("CONST", 0.0) == pytest.approx(c.L)
    assert any(c.patterns.get("CONST") for c in project_strength_combinations(settings))


def test_deleting_a_pattern_with_loads_is_refused() -> None:
    settings = with_patterns(default_project_settings("P"), EQP)
    text = json.dumps(
        {
            "loads": [
                {
                    "id": "T",
                    "story": "L1",
                    "member": "B11",
                    "kind": "point",
                    "value": 30,
                    "distance": 3000,
                    "case": "EQP",
                }
            ]
        }
    )
    assert "1 member load" in (lp.deletion_problem(settings, "EQP", text) or "")
    assert lp.deletion_problem(settings, "EQP", None) is None
    assert "built-in" in (lp.deletion_problem(settings, "D") or "")


# ── old projects ──


def test_old_settings_round_trip_unchanged() -> None:
    """The sample project (saved before load patterns) reads and writes without new fields."""
    raw = json.loads(SAMPLE_SETTINGS.read_text(encoding="utf-8"))
    settings = ProjectSettings.model_validate(raw)
    assert settings.loadPatterns == []
    out = settings.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "loadPatterns" not in out
    for c in out["combinations"]:
        assert "patterns" not in c
    for a in out["areaLoads"]:
        assert "otherLoad" not in a and "otherPattern" not in a
    assert ProjectSettings.model_validate(out).model_dump(mode="json", by_alias=True) == (
        settings.model_dump(mode="json", by_alias=True)
    )


def test_old_member_loads_round_trip_unchanged() -> None:
    data = {
        "schema": "saengine.memberLoads/1",
        "wallTypes": [],
        "loads": [
            {"id": "W", "story": "L1", "member": "B11", "kind": "line", "value": 7.5, "case": "SD"},
            {
                "id": "P",
                "story": "L1",
                "member": "B12",
                "kind": "point",
                "value": 30.0,
                "distance": 2000.0,
                "case": "Lr",
            },
        ],
    }
    loads = ll.parse(json.dumps(data))
    out = loads.model_dump(mode="json", by_alias=True)
    assert [load["case"] for load in out["loads"]] == ["SD", "Lr"]
    for before, after in zip(data["loads"], out["loads"], strict=True):
        assert after == {**after, **before}  # every saved value kept as it was
    assert ll.parse(json.dumps(out)) == loads


# ── known answers ──


def test_simple_beam_equipment_1p2d_1p6eqp(tmp_path: Path) -> None:
    """M_mid of 1.2D + 1.6EQP on a simply supported beam = 1.2·wL²/8 + 1.6·PL/4."""
    from saengine.fem.display import result_view
    from saengine.verification.cases.analysis import A_BM, BEAM, RHO_C
    from saengine.verification.cases.common import (
        MATERIALS,
        G,
        building,
        derive,
        node_at,
        objects,
        point,
        run_model,
        settings,
        structure,
    )

    span, p = 6.0, P_KN * 1e3
    model = structure(
        members=[
            {"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(3000, 0, 0)},
            {"id": "M2", "type": "BM", "start": point(3000, 0, 0), "end": point(6000, 0, 0)},
        ],
        supports=[
            {"id": "S1", "at": point(0, 0, 0), "fixity": "pinned"},
            {"id": "S2", "at": point(6000, 0, 0), "fixity": "pinned"},
        ],
    )
    project_settings = with_patterns(settings(), EQP)
    d = derive(building(model), objects(BEAM), MATERIALS, project_settings)
    project = d.project
    names = [pt["name"] for pt in project["load_patterns"]]
    assert "EQP" in names  # its own OpenSees pattern
    eqp = names.index("EQP") + 1
    analysis = next(a for a in project["analyses"] if a["id"] == eqp)
    assert analysis["name"] == "EQP: Equipment"
    for node in project["nodes"]:  # fork supports, as the verification case holds the twist
        if node["restraint"][:3] == [True, True, True]:
            node["restraint"][3] = True
    # The equipment's 30 kN at midspan, in EQP (an empty pattern until a load is entered).
    mid = node_at(project, (span / 2, 0, 0))
    project["load_patterns"][eqp - 1]["nodal_loads"] = [
        {"node_id": mid, "forces": [0.0, 0.0, -p, 0.0, 0.0, 0.0]}
    ]
    path, out, _ = run_model(project, tmp_path, [1, eqp])

    def moment(case_id: int) -> float:
        view = result_view(out, path, f"case:{case_id}")
        (half,) = [e for e in view["elements"] if e["name"] == "M1"]
        return float(half["forces"][-1][5])

    static = {"D": moment(1), "SD": 0.0, "EQP": moment(eqp)}
    combo = LoadCombination(name="1.2D + 1.6EQP", D=1.2, patterns={"EQP": 1.6})
    s, _ = evaluate(DesignCombination.of(combo, model_cases(project) | {"SD"}), static)
    w = RHO_C * G * A_BM
    by_hand = 1.2 * w * span**2 / 8 + 1.6 * p * span / 4
    assert abs(float(s)) == pytest.approx(by_hand, rel=0.01)
    assert abs(static["EQP"]) == pytest.approx(p * span / 4, rel=0.01)


def test_frame_point_load_in_eqp_and_combined(tmp_path: Path) -> None:
    """A floor-plan point load in EQP: its case carries P, D and SD are unchanged, and the
    base reaction of 1.2D + 1.6EQP is 1.2·ΣD + 1.6·P."""
    import numpy as np

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from saengine.verification.cases.common import run_model
    from tests.test_line_loads import OBJECTS, _applied, loads, plan

    settings = with_patterns(default_project_settings("Bay"), EQP)
    building = generate(plan(), "s")
    member_loads = loads(
        {
            "id": "PUMP",
            "story": "L1",
            "member": "B12",
            "kind": "point",
            "value": P_KN,
            "distance": 2000,
            "case": "EQP",
        }
    )
    args = (building, OBJECTS, default_material_library(), settings, {"bim": "abc"})
    without = derive_fem(*args).project
    project = derive_fem(*args, member_loads=member_loads).project
    assert _applied(project, "EQP") / 1e3 == pytest.approx(-P_KN, rel=1e-9)
    assert _applied(without, "EQP") == 0.0
    for case in ("D", "SD"):
        assert _applied(project, case) == pytest.approx(_applied(without, case), rel=1e-9)
    names = [pt["name"] for pt in project["load_patterns"]]
    ids = [names.index(c) + 1 for c in ("D", "SD", "EQP")]
    _, _, results = run_model(project, tmp_path, ids)

    def base_reaction(case_id: int) -> float:
        reactions = results[case_id].node_reaction
        return sum(float(np.asarray(rows[-1])[2]) for rows in reactions.values() if len(rows))

    static = {c: np.array([base_reaction(i)]) for c, i in zip(("D", "SD", "EQP"), ids, strict=True)}
    assert static["EQP"][0] / 1e3 == pytest.approx(P_KN, rel=0.005)
    combo = LoadCombination(name="1.2D + 1.6EQP", D=1.2, patterns={"EQP": 1.6})
    s, _ = evaluate(DesignCombination.of(combo, model_cases(project)), static)
    dead = -(_applied(project, "D") + _applied(project, "SD"))
    assert float(s[0]) == pytest.approx(1.2 * dead + 1.6 * P_KN * 1e3, rel=0.005)


def test_area_other_load_and_self_weight_multiplier() -> None:
    """An area load's other load lands in its pattern (load × slab area); a pattern with a
    self-weight multiplier carries that many times D's self-weight."""
    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from tests.test_line_loads import OBJECTS, _applied, plan

    base = default_project_settings("Bay")
    data = base.model_dump(mode="json", by_alias=True)
    data["areaLoads"] = [{**a, "otherLoad": 2.0, "otherPattern": "EQP"} for a in data["areaLoads"]]
    sw2 = LoadPattern(id="SW2", name="Twice the self-weight", type="Dead", selfWeight=2.0)
    data["loadPatterns"] = [EQP.model_dump(), sw2.model_dump()]
    settings = ProjectSettings.model_validate(data)
    assert isinstance(settings.areaLoads[0], AreaLoad)
    building = generate(plan(), "s")
    project = derive_fem(
        building, OBJECTS, default_material_library(), settings, {"b": "x"}
    ).project
    # 6 m × 5 m panel (column-line to column-line): 2 kN/m² over it.
    assert -_applied(project, "EQP") / 1e3 == pytest.approx(2.0 * 6.0 * 5.0, rel=0.02)
    assert _applied(project, "SW2") == pytest.approx(2.0 * _applied(project, "D"), rel=0.02)


# ── live load arrangements ──


def test_live_pattern_loads_are_arranged_with_l() -> None:
    """A point load in a Live-type pattern goes into the arrangement cases whose bays hold it
    (bay 1: LP1 alternate 1 and 3, LP3 adjacent 1-2), not into the others; an Other-type
    pattern's load stays out of them."""
    import numpy as np

    from saengine.fem.derive import derive_fem
    from saengine.fem.end_zones import element_offsets
    from saengine.library import default_material_library
    from tests.test_correctness_wiring import _three_bays_two_storeys
    from tests.test_line_loads import loads

    building, objects = _three_bays_two_storeys()
    point = {
        "id": "PUMP",
        "story": "L1",
        "member": "BAB1L1",
        "kind": "point",
        "value": P_KN,
        "distance": 2500,
    }

    def totals(pattern: LoadPattern) -> dict[str, float]:
        settings = with_patterns(default_project_settings("Arrangements"), pattern)
        member_loads = loads({**point, "case": pattern.id})
        project = derive_fem(
            building,
            objects,
            default_material_library(),
            settings,
            {"b": "x"},
            member_loads=member_loads,
        ).project
        coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
        elements = {e["id"]: e for e in project["elements"]}
        out = {}
        for p in project["load_patterns"]:
            total = sum(n["forces"][2] for n in p["nodal_loads"])
            for load in p["element_loads"]:
                element = elements[load["element_id"]]
                a, c = (coords[k] for k in element["nodes"])
                length = float(np.linalg.norm(c - a)) - sum(element_offsets(element))
                total += load["wz"] * length
            out[p["name"]] = total
        return out

    live = totals(LoadPattern(id="EQL", name="Equipment", type="Live"))
    other = totals(LoadPattern(id="EQO", name="Equipment", type="Other"))
    assert live["EQL"] / 1e3 == pytest.approx(-P_KN, rel=1e-9)
    for case, change in (("LP1", -P_KN), ("LP2", 0.0), ("LP3", -P_KN), ("LP4", 0.0)):
        assert (live[case] - other[case]) / 1e3 == pytest.approx(change, abs=1e-6), case


def test_arrangement_combinations_replace_live_patterns() -> None:
    """The arrangement combinations replace L and the Live-type patterns by LPk at L's factor;
    a combination giving such a pattern another factor is not arranged and is reported."""
    from saengine.fem.combinations import pattern_live_combinations

    present = {"D", "L", "EQL", "LP1", "LP2"}
    same = LoadCombination(name="1.2D + 1.6L", D=1.2, L=1.6, patterns={"EQL": 1.6})
    other = LoadCombination(name="1.2D + 1.0L", D=1.2, L=1.0, patterns={"EQL": 1.6})
    skipped: list[str] = []
    formed = pattern_live_combinations([same, other], present, ["EQL"], skipped)
    assert formed is not None
    assert skipped == ["1.2D + 1.0L"]
    arranged = [c for c in formed if "[LP" in c.name]
    assert [c.name for c in arranged] == ["1.2D + 1.6L [LP1]", "1.2D + 1.6L [LP2]"]
    assert combination_factors(arranged[0], present) == {"D": 1.2, "SD": 1.2, "LP1": 1.6}
    # Without Live-type patterns, as before.
    plain = pattern_live_combinations([other], present)
    assert plain is not None and [c.name for c in plain][1:] == [
        "1.2D + 1.0L [LP1]",
        "1.2D + 1.0L [LP2]",
    ]


# ── exporters ──


def test_exporters_write_the_patterns() -> None:
    """The e2k file declares the project's patterns (type, self-weight), their member and area
    loads, their mass share and their combination factors; the neutral model behind the SAP,
    SAF and STAAD files gives each its type's kind."""
    from saengine.exporters.analytical import from_osmodel
    from saengine.exporters.etabs import write_e2k
    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from tests.test_line_loads import OBJECTS, loads, plan

    base = default_project_settings("Bay")
    data = base.model_dump(mode="json", by_alias=True)
    data["areaLoads"] = [{**a, "otherLoad": 2.0, "otherPattern": "SWX"} for a in data["areaLoads"]]
    data["loadPatterns"] = [
        LoadPattern(id="EQL", name="Equipment", type="Live").model_dump(),
        LoadPattern(id="SWX", name="Extra dead", type="Dead", selfWeight=0.5).model_dump(),
    ]
    data["combinations"] = [
        {"name": "1.2D + 1.6EQL", "D": 1.2, "patterns": {"EQL": 1.6, "SWX": 1.2}},
    ]
    settings = ProjectSettings.model_validate(data)
    building = generate(plan(), "s")
    member_loads = loads(
        {
            "id": "PUMP",
            "story": "L1",
            "member": "B12",
            "kind": "point",
            "value": P_KN,
            "distance": 2000,
            "case": "EQL",
        }
    )
    materials = default_material_library()
    text = write_e2k(building, OBJECTS, materials, settings, member_loads=member_loads).text
    assert 'LOADPATTERN "EQL"  TYPE  "Live"  SELFWEIGHT  0' in text
    assert 'LOADPATTERN "SWX"  TYPE  "Dead"  SELFWEIGHT  0.5' in text
    assert 'LC "EQL"' in text and 'LC "SWX"' in text
    assert 'MASSSOURCELOAD  "MsSrc1"  "SWX"  1 ' in text
    assert 'LOADCASE "EQL"  LOADPAT  "EQL"' in text
    assert 'COMBO "1.2D + 1.6EQL"  LOADCASE "EQL"  SF 1.6 ' in text
    assert 'COMBO "1.2D + 1.6EQL"  LOADCASE "SWX"  SF 1.2 ' in text

    project = derive_fem(
        building, OBJECTS, materials, settings, {"b": "x"}, member_loads=member_loads
    ).project
    model = from_osmodel(project, OBJECTS, materials, settings)
    kinds = {c.name: c.kind for c in model.cases}
    assert kinds["EQL"] == "L" and kinds["SWX"] == "D"
    assert dict(model.combinations)["1.2D + 1.6EQL"]["EQL"] == 1.6
