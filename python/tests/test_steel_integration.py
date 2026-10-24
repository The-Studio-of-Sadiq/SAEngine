"""Integration of the steel design and the structural importers (integrator glue):

- :mod:`saengine.design.steel_design`: a braced steel portal's members designed with their
  types' simple connections (repeated as "Connection: ..." checks), and the design mode's steel
  entries applied by :func:`saengine.design.apply_proposal`;
- the bill of quantities' structural steel by section (kg/m × length);
- :func:`saengine.importers.project.import_structural` (the RPC's ``import/structural`` and
  ``saengine import <file.e2k>``): the new project's files, its report, the refusals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.design import apply_proposal, steel_design
from saengine.design.check import _demands
from saengine.fem.derive import pinned_twins
from saengine.importers.neutral import named_profile
from saengine.importers.project import (
    StructuralImportError,
    import_structural,
    section_lookup,
    section_lookup_noted,
)
from saengine.library.settings import LoadCombination
from saengine.rpc import handlers
from saengine.verification.cases.common import (
    MATERIALS,
    derive,
    node_at,
    objects,
    point,
    run_model,
    settings,
    structure,
)
from saengine.verification.cases.common import building as building_of

DATA = Path(__file__).parent / "data" / "import"
W = {
    "shape": "I",
    "overallWidth": 254,
    "overallDepth": 254,
    "webThickness": 8.6,
    "flangeThickness": 14.2,
}
SHS = {"shape": "rectangleHollow", "xDim": 150, "yDim": 150, "wallThickness": 8}
TYPES = objects(
    {"id": "COL", "name": "W col", "kind": "column", "material": "A992", "profile": W},
    {
        "id": "BM",
        "name": "W beam",
        "kind": "beam",
        "material": "A992",
        "profile": W,
        "connection": {"type": "finPlate", "rows": 4},
    },
    {
        "id": "BR",
        "name": "SHS 150x8",
        "kind": "brace",
        "material": "A992",
        "profile": SHS,
        "connection": {"type": "gusset", "tabThickness": 10},
    },
)


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
            {"id": "M1", "type": "BR", "start": point(0, 0, 0), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    building = building_of(model)
    project = derive(building, TYPES, MATERIALS, settings()).project
    top = node_at(project, (0, 0, 3.2))
    wx = next(p for p in project["load_patterns"] if p["name"] == "WX")
    wx["nodal_loads"] = [{"node_id": top, "forces": [100e3, 0, 0, 0, 0, 0]}]
    beam = next(e["id"] for e in project["elements"] if e["name"] == "B1")
    project["load_patterns"][0]["element_loads"].append(
        {"element_id": beam, "wy": 0.0, "wz": -20e3, "wx": 0.0}
    )
    static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
    _, out, _ = run_model(project, tmp_path_factory.mktemp("steel-integration"), static)
    s = settings().model_copy(
        update={
            "combinations": [
                LoadCombination(name="1.2D+1.0WX", D=1.2, WX=1.0),
                LoadCombination(name="0.9D-1.0WX", D=0.9, WX=-1.0),
            ]
        }
    )
    combinations, pieces, _, _ = _demands(project, out, s)
    types = {t.id: t for t in TYPES.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    found = {}
    for element in building.elements:
        t = types[element.type]
        found[element.id] = steel_design.design_member(
            element.id,
            t.kind,
            t,
            mats[t.material],
            mats,
            pieces[element.id],
            combinations,
            False,
            project,
        )
    return found


def test_members_with_their_connections(portal):
    brace, _ = portal["M1"]
    beam, _ = portal["B1"]
    column, _ = portal["C1"]
    summary = {
        "brace": (brace["kind"], brace["material"], brace["connections"][0]["connection"]),
        "beam": (beam["kind"], beam["connections"][0]["connection"]),
        "column has none": "connections" not in column,
    }
    assert summary == {
        "brace": ("brace", "A992", "gusset"),
        "beam": ("beam", "finPlate"),
        "column has none": True,
    }
    for entry in (brace, beam):
        repeated = [c for c in entry["checks"] if c["name"].startswith("Connection: ")]
        assert len(repeated) == len(entry["connections"][0]["checks"]) > 0
        strength = [c for c in entry["checks"] if not c["flag"]]
        assert entry["utilisation"] == max(c["utilisation"] for c in strength)
    # The brace gusset sees both signs of the sway; the fin plate the beam's end shear (about
    # wL/2 = 60 kN under 1.2D plus the sway's share).
    names = {c["name"] for c in brace["checks"]}
    assert {"Connection: bolt shear (tension)", "Connection: bolt shear (compression)"} <= names
    shear = next(c for c in beam["connections"][0]["checks"] if c["name"].startswith("bolt"))
    assert 30 < shear["demand"] * 4 < 200


def test_simple_connections_are_pinned_in_the_analysis(portal):
    """A fin plate or gusset transfers no moment: the derived model pins those member ends, so
    the beam carries the simply supported span moment and its connection sees no end moment."""
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
            {"id": "M1", "type": "BR", "start": point(0, 0, 0), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    derivation = derive(building_of(model), TYPES, MATERIALS, settings())
    project = derivation.project
    links = {e["name"]: e for e in project["elements"] if e["type"] == "ZeroLength"}
    # B1 at both ends (torsion kept at its first end, about global X), M1 at its top only:
    # its foot is at a support, where the reaction must stay at the support node.
    assert sorted((name, e["dofs"]) for name, e in links.items()) == [
        ("B1/pin", [1, 2, 3, 4]),
        ("B1/pin#2", [1, 2, 3]),
        ("M1/pin", [1, 2, 3]),
    ]
    twins = pinned_twins(project)
    assert all(twins[e["nodes"][1]] == e["nodes"][0] for e in links.values())
    beam = [e for e in project["elements"] if e["name"].split("#")[0] == "B1"]
    assert {n for e in beam for n in e["nodes"]} <= set(twins) | {
        n for e in beam for n in e["nodes"][1:-1]
    }
    assert any("pinned (no end moment)" in n for n in derivation.notes)
    assert any("analysed rigid at a support" in n and "M1" in n for n in derivation.notes)

    beam, collected = portal["B1"]
    gravity = next(st for st in collected["stations"] if st.combination == "1.2D+1.0WX")
    span = max(abs(gravity.Mx)) / 1e6
    ends = max(abs(gravity.Mx[0]), abs(gravity.Mx[-1])) / 1e6
    # 1.2 (20 kN/m + the W section's self-weight, about 0.7 kN/m) × 6² / 8 ≈ 112 kN·m.
    assert span == pytest.approx(1.2 * 20.7 * 6**2 / 8, rel=0.02) and ends < 0.5
    flexure = next(c for c in beam["checks"] if c["name"].startswith("Flexure about x"))
    assert flexure["demand"] >= span
    assert not any("end moment" in c["name"] for c in beam["checks"])
    # The brace's foot stays rigid at the support: flagged, not counted in its utilisation.
    brace, _ = portal["M1"]
    moment = next(c for c in brace["checks"] if "end moment" in c["name"])
    assert moment["flag"] and not moment["ok"]
    assert brace["utilisation"] < moment["utilisation"]


def test_report_and_bill_weigh_steel_alike(portal):
    """The design entry's kg/m is the section table's (corner radii), as the BOQ measures it."""
    from saengine.boq.quantities import STEEL_DENSITY
    from saengine.library.steel_sections import section_of_profile

    brace, _ = portal["M1"]
    table = section_of_profile(TYPES.objects[2].profile).A * 1e-6
    density = next(m for m in MATERIALS.materials if m.id == "A992").mechanical.density
    expected = round(table * (density or STEEL_DENSITY), 3)
    assert brace["section"]["massPerMetre"] == expected
    assert f"{brace['section']['massPerMetre']:.1f}" == "33.9"  # as the BOQ prints it


def test_steel_proposal_applied_as_a_new_profile(portal):
    collected = [c for _, c in portal.values()]
    originals = {t.id: t.model_dump(mode="json", exclude_none=True) for t in TYPES.objects}
    entries, notes = steel_design.proposal_entries(collected, originals)
    by_type = {e["type"]: e for e in entries}
    assert set(by_type) == {"COL", "BM", "BR"} and notes == []
    brace = by_type["BR"]
    assert brace["family"] == "SHS" and brace["status"] in ("ok", "unchanged")
    text = json.dumps({"schema": "saengine.objects/1", "objects": list(originals.values())})
    result = apply_proposal(text, "{}", {"types": [brace]})
    after = {o["id"]: o for o in json.loads(result["objectsText"])["objects"]}
    if brace["status"] == "ok":
        assert after["BR"]["profile"] == brace["proposed"]["profile"]
        assert [c["what"] for c in result["changes"]] == ["section"]
    assert after["BR"]["connection"]["type"] == "gusset"  # the connection stays


def test_bill_of_quantities_measures_steel_by_section():
    sample = (
        Path(__file__).parents[2] / "workbench/resources/saengine/samples/Sample Frame"
    ).resolve()
    bill = json.loads((sample / "10 BOQ" / "boq.json").read_text(encoding="utf-8"))
    steel = [i for i in bill["items"] if i["group"] == "steel"]
    assert [(i["description"], i["unit"]) for i in steel] == [
        ("Structural steel A572-50, SHS 150x150x8 (33.9 kg/m) in braces", "kg")
    ]
    detail = steel[0]["breakdown"][0]["detail"]
    length, per_metre = (float(x.split()[0]) for x in detail.split(" × "))
    assert steel[0]["quantity"] == pytest.approx(length * per_metre, rel=1e-3)


def test_section_lookup_by_database_name():
    assert section_lookup("IPE300")["overallDepth"] == 300
    assert section_lookup("shs100x100x5")["wallThickness"] == 5
    # The same reading as the STAAD and SAP2000 importers (neutral.named_profile).
    for name in ("HE200A", "UB305X165X40", "UC203X203X46", "W12X26", "SHS25X25X2.5"):
        profile, note = named_profile(name)
        assert section_lookup_noted(name) == (profile.model_dump(), note), name
    assert section_lookup("HE200A")["overallDepth"] == 190
    assert section_lookup_noted("HE200A")[1] is None  # in the table: exact
    assert "estimated" in section_lookup_noted("W14X90")[1]
    assert section_lookup("C10X20") is None


def test_etabs_import_keeps_database_sections_staad_reads(tmp_path):
    """An ETABS frame section named only by a database designation (W14X90 in the test file)
    is read as the STAAD and SAP2000 importers read it, and reported as approximated."""
    result = import_structural(DATA / "two_story_frame.e2k", tmp_path, "Lookup")
    report = result["report"]
    approximated = {a["what"]: a for a in report["approximated"]}
    entry = next(a for what, a in approximated.items() if what.startswith("database sections"))
    assert "W14X90" in entry["examples"] and "estimated" in entry["what"]
    skipped = [s["what"] for s in report["skipped"]]
    assert not any("steel database" in what for what in skipped)


def test_metric_tube_names_are_not_read_in_inches():
    profile, note = named_profile("SHS25X25X2.5")
    assert (profile.xDim, profile.yDim, profile.wallThickness, note) == (25, 25, 2.5, None)
    tube, note = named_profile("TUBE4X4X0.25")
    assert tube.xDim == pytest.approx(101.6) and "inches" in note
    angle, note = named_profile("L50X50X5")
    assert angle.depth == 50 and note is None
    hss, note = named_profile("HSS4X4X1/4")
    assert hss.wallThickness == pytest.approx(6.35) and note is None


def test_import_structural_writes_a_whole_project(tmp_path):
    result = import_structural(DATA / "two_story_frame.e2k", tmp_path, "Office")
    root = Path(result["root"])
    assert root == tmp_path / "Office" and result["format"] == "etabs"
    assert result["report"]["source"]["program"] == "ETABS"
    for part in (
        "02 Project Settings/project-settings.json",
        "04 Objects/objects.json",
        "06 BIM/bim.json",
        "import-report.json",
        "Office.saengine",
    ):
        assert (root / part).is_file(), part
    placeholder = json.loads((root / "10 BOQ" / "boq.json").read_text(encoding="utf-8"))
    assert placeholder == {"schema": 1, "part": "boq"}
    assert (root / "08 FEM").is_dir() and (root / "11 Exports").is_dir()
    with pytest.raises(StructuralImportError, match="exists already"):
        import_structural(DATA / "two_story_frame.e2k", tmp_path, "Office")


@pytest.mark.parametrize("name", ["frame.std", "frame.s2k"])
def test_import_structural_staad_and_sap(tmp_path, name):
    result = import_structural(DATA / name, tmp_path)
    assert result["format"] == {"frame.std": "staad", "frame.s2k": "sap2000"}[name]
    assert (Path(result["root"]) / "06 BIM" / "bim.json").is_file()


def test_rpc_import_refuses_other_files(tmp_path):
    other = tmp_path / "model.txt"
    other.write_text("nothing", encoding="utf-8")
    answer = handlers.import_structural(str(other), str(tmp_path))
    assert set(answer) == {"error", "problems"} and "not an ETABS" in answer["error"]
