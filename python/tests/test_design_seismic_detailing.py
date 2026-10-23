"""The seismic detailing of BNBC 2020 Part 6 Sec 8.3 wired into the design report, the design
mode and the report (saengine.design.seismic_detailing, the integrator's glue over
seismic_rules, ductile_members and ductile_joints).

The sample (a copy) is an RC intermediate moment frame in Chattogram on site class SD:
Seismic Design Category D, so Sec 8.3.2 asks for special moment frame detailing, which its
ties at 150 mm with 2 legs and f'c 20.7 MPa were not designed for.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.design import seismic_detailing as sd
from saengine.library.objects import Column, ObjectLibrary

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


def test_clause_is_taken_from_the_check_name() -> None:
    assert sd._clause("Width ≥ 250 mm (8.3.4.1(d))") == "BNBC 2020 Part 6 Sec 8.3.4.1(d)"
    assert sd._clause("Ties over lap splices (Figure 6.8.8)") == "BNBC 2020 Part 6 Figure 6.8.8"
    assert sd._clause("Capacity shear Ve (SMF)") is None
    assert sd._clause("Joint shear, C1@3200 x") is None


def test_earthquake_combinations_are_found_from_factors_and_envelopes() -> None:
    extra = {
        "factors": [{"D": 1.4}, {"D": 1.2, "EX": 1.0}, {"D": 1.2}, {"D": 0.9, "EY": -1.0}],
        "envelope": [{}, {}, {"RSX": 1.0}, {}],
    }
    assert sd.earthquake_indices(extra, 4) == [1, 2, 3]
    assert sd.earthquake_indices({}, 2) == []


def test_old_object_files_stay_valid_and_zones_round_trip() -> None:
    old = {
        "objects": [
            {
                "id": "C1",
                "kind": "column",
                "name": "C1",
                "material": "C28",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                "reinforcement": {
                    "material": "B420DWR",
                    "cover": 40,
                    "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
                    "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
                },
            }
        ]
    }
    library = ObjectLibrary.model_validate(old)
    column = library.objects[0]
    assert isinstance(column, Column)
    assert (column.seismicRole, column.omegaCombinations) == ("auto", "auto")
    assert column.reinforcement.transverse.zone is None
    zoned = json.loads(json.dumps(old))
    zoned["objects"][0]["reinforcement"]["transverse"].update(
        zone={"spacing": 100, "length": 600, "first": 50}, splice={"spacing": 100}, legsX=3
    )
    t = ObjectLibrary.model_validate(zoned).objects[0].reinforcement.transverse
    assert (t.zone.spacing, t.zone.length, t.zone.first, t.splice.spacing, t.legsX) == (
        100,
        600,
        50,
        100,
        3,
    )
    from saengine.design.ductile_members import zones_of

    z = zones_of(t)
    assert (z.in_zone, z.zone_length, z.zone_first, z.splice_spacing, z.across_depth) == (
        100,
        600,
        50,
        100,
        3,
    )


# ─────────────────────────────────────── the sample ───────────────────────────────────────


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from saengine.pipeline.run_all import run_all

    root = tmp_path_factory.mktemp("detailing-sample") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    result = run_all(root, ["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    return root


def _report(root: Path) -> dict:
    from saengine.design.check import design_report

    return design_report(root / "08 FEM" / "model.results", root / "08 FEM" / "model.osmodel")


@pytest.fixture(scope="module")
def report(analysed: Path) -> dict:
    return _report(analysed)


def _failing(element: dict) -> set[str]:
    return {
        c["name"]
        for c in element["checks"]
        if c["name"].startswith(sd.PREFIX) and not c["ok"] and not c["flag"]
    }


@pytest.mark.slow
def test_sample_detailing_scope_and_failures(report: dict) -> None:
    json.dumps(report, allow_nan=False)  # strict JSON for the RPC
    scope = report["seismic"]
    assert (scope["sdc"], scope["system"], scope["detailingLevel"]) == ("D", "rcSmf", "special")
    failed = {c["name"].split(" (")[0] for c in scope["checks"] if not c["ok"] and not c["flag"]}
    # Dhaka on SD soil (Category D), a special moment frame of C24.1: both project checks pass.
    assert failed == set()
    by_id = {e["id"]: e for e in report["elements"]}
    c1, b1 = by_id["C1"], by_id["B1"]
    assert c1["detailing"]["frameType"] == "special" and c1["detailing"]["zones"]["lo"] == 1200
    assert {
        "Detailing: Tie spacing in lo (8.3.5.4(b), 8.3.4.3(b))",
        "Detailing: Cross-tie spacing hx (8.3.5.4(c))",
        "Detailing: Confinement Ash, bc along y, in lo (8.3.5.4(a)(ii))",
    } <= _failing(c1)
    assert "Detailing: Hoop spacing at the ends (8.3.4.3(b))" in _failing(b1)
    # Detailing failures fail the member, and every detailing check names its clause.
    assert not c1["ok"] and c1["utilisation"] > 1
    assert all(
        c["clause"]
        for e in report["elements"]
        for c in e["checks"]
        if c["name"].startswith(sd.PREFIX)
    )
    assert any(c["name"].startswith(sd.PREFIX + "Capacity shear") for c in c1["checks"])
    assert all(c["clause"] for j in report["joints"] for c in j["checks"])
    # The hoop spacing in lo the required-steel report names keeps Ash (Eq. 6.8.7, 6.8.8) and
    # the capacity shear's Av/s with the type's ties: Ash/s 3.40 mm²/mm with 2 Ø10 legs
    # (157 mm²) allows 46 mm, below the 85 mm of the dimensions (d/4: the
    # columns carry Pu <= 0.1 Ag f'c, so the 8.3.4.3 hoop rules join 8.3.5.4; lo = 2h = 1200).
    zones = c1["detailing"]["zones"]
    assert zones["soDetailing"] == 85 and zones["so"] <= 46
    assert "Ash" in zones["soRule"]
    joints = report["joints"]
    assert joints and all(isinstance(j["node"], int) for j in joints)
    assert {j["column"] for j in joints} <= set(by_id)
    assert report["summary"]["joints"]["checked"] == len(joints)
    # The sample's columns carry less than 0.1 Ag f'c: the strong-column rule is reported only.
    assert all(
        s is None or s["notRequired"] for j in joints for s in (j["scwb"]["x"], j["scwb"]["y"])
    )


@pytest.mark.slow
def test_sample_proposal_zones_resolve_the_member_detailing(analysed: Path, tmp_path) -> None:
    from saengine.design.proposal import apply_proposal, design_proposal
    from saengine.pipeline.run_all import run_all

    root = tmp_path / "Sample Frame"
    shutil.copytree(analysed, root)
    fem = root / "08 FEM"
    proposal = design_proposal(fem / "model.results", fem / "model.osmodel")
    by_type = {t["type"]: t for t in proposal["types"]}
    beam = by_type["B300x500"]["proposed"]["transverse"]
    column = by_type["C400x600"]["proposed"]["transverse"]
    assert beam["zone"]["length"] == 1000 and beam["zone"]["spacing"] <= 100
    assert column["zone"]["spacing"] <= 100 and column["legs"] >= 3
    assert by_type["C400x600"]["detailing"]["sectionTooSmall"] == []
    out = apply_proposal(
        (root / "04 Objects/objects.json").read_text("utf-8"),
        (root / "06 BIM/bim.json").read_text("utf-8"),
        proposal,
    )
    (root / "04 Objects/objects.json").write_text(out["objectsText"], "utf-8")
    run_all(root, ["derive", "analysis"])
    after = _report(root)
    # Every element passes, detailing included (the stair ST1 meets BNBC's geometry rules).
    assert {e["id"] for e in after["elements"] if not e["ok"]} == set()
    # The project checks (system permitted, f'c ≥ 21 MPa) pass on the sample.
    assert after["summary"]["seismicChecksFailed"] == 0


@pytest.mark.slow
def test_omega_combinations_reach_the_marked_members_only(analysed: Path, tmp_path) -> None:
    root = tmp_path / "Sample Frame"
    shutil.copytree(analysed, root)
    path = root / "04 Objects/objects.json"
    data = json.loads(path.read_text("utf-8"))
    for o in data["objects"]:
        if o["id"] == "C400x600":
            o["omegaCombinations"] = "transfer"
    path.write_text(json.dumps(data), "utf-8")
    report = _report(root)
    omega = [c for c in report["combinations"] if c.startswith("Ω0: ")]
    assert omega
    assert set(report["seismic"]["omega"]["elements"]) >= {"C1", "C2"}
    for e in report["elements"]:
        if e["kind"] == "beam":
            assert not any((c["combination"] or "").startswith("Ω0: ") for c in e["checks"])


@pytest.mark.slow
def test_report_chapter(report: dict) -> None:
    from saengine.report.build import _seismic_detailing

    chapter = _seismic_detailing(report)
    assert chapter["available"] and chapter["failedChecks"] == 0
    assert len(chapter["joints"]) == len(report["joints"])
    assert any(r[0] == "C400x600" for r in chapter["members"])
    assert all(r[-1] == "FAIL" for r in chapter["shears"] if r[1] == "column")


def _marked(analysed: Path, tmp_path: Path, field: str, value: str, types: tuple) -> dict:
    root = tmp_path / "Sample Frame"
    shutil.copytree(analysed, root)
    path = root / "04 Objects/objects.json"
    data = json.loads(path.read_text("utf-8"))
    for o in data["objects"]:
        if o["id"] in types:
            o[field] = value
    path.write_text(json.dumps(data), "utf-8")
    return _report(root)


@pytest.mark.slow
def test_omega_combinations_leave_the_other_members_demands_alone(
    analysed: Path, report: dict, tmp_path: Path
) -> None:
    # Only the beams get the Ω0 combinations: the columns' earthquake demands (pmin, which sets
    # the strong-column Mnc, the Vc = 0 test and Mpr) must not see them as zero axial force.
    marked = _marked(analysed, tmp_path, "omegaCombinations", "transfer", ("B300x500",))
    assert not set(marked["seismic"]["omega"]["elements"]) & {"C1", "C2", "C5"}

    def strong(r: dict) -> dict:
        return {
            (j["id"], c["name"]): (c["capacity"], c["note"])
            for j in r["joints"]
            for c in j["checks"]
            if "Strong column" in c["name"]
        }

    assert strong(marked) == strong(report) and strong(report)


@pytest.mark.slow
def test_gravity_members_in_category_d(analysed: Path, tmp_path: Path) -> None:
    report = _marked(analysed, tmp_path, "seismicRole", "gravity", ("B300x500", "C400x600"))
    by_id = {e["id"]: e for e in report["elements"]}
    c1, b1 = by_id["C1"], by_id["B1"]
    assert c1["detailing"]["role"] == "gravity"
    # Columns: the induced forces are not computed, so 8.3.12.3 with the 8.3.8 capacity shear.
    names = [c["name"] for c in c1["checks"] if c["name"].startswith(sd.PREFIX)]
    shear = [c for c in c1["checks"] if c["name"].startswith(sd.PREFIX + "Capacity shear")]
    assert shear and all("8.3.12.3" in c["clause"] and "8.3.8.1(b)" in c["clause"] for c in shear)
    assert any("for columns, so Sec 8.3.12.3 applies" in n for n in c1["detailing"]["notes"])
    assert len(names) == len(set(names))
    # Beams: one d/2 row; the notes do not both say the moments are and are not computed.
    b_names = [c["name"] for c in b1["checks"] if c["name"].startswith(sd.PREFIX)]
    assert sum("Stirrup spacing" in n for n in b_names) == 1
    notes = " ".join(b1["detailing"]["notes"])
    assert not ("are not computed" in notes and "8.3.12.2(a) applies" in notes)
    assert "8.3.12.2(a) applies" in notes and "lap splices" not in notes
    assert all(c["clause"] for c in b1["checks"] + c1["checks"] if c["name"].startswith(sd.PREFIX))


@pytest.mark.slow
def test_response_spectrum_omega_uses_the_resolved_site_class(
    analysed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Entered SA, but the soil report (the default source) gives SD: the Ω0 combinations of
    # the response spectrum path take Ev from the class the analysis used, as the static do.
    from saengine.design import check, seismic_rules
    from saengine.fem import seismic_design

    root = tmp_path / "Sample Frame"
    shutil.copytree(analysed, root)
    path = root / "02 Project Settings/project-settings.json"
    settings = json.loads(path.read_text("utf-8"))
    settings["site"]["siteClass"] = "SA"
    settings.setdefault("analysis", {})["seismicDesign"] = "responseSpectrum"
    path.write_text(json.dumps(settings), "utf-8")
    objects = root / "04 Objects/objects.json"
    data = json.loads(objects.read_text("utf-8"))
    for o in data["objects"]:
        if o["id"] == "B300x500":
            o["omegaCombinations"] = "transfer"
    objects.write_text(json.dumps(data), "utf-8")
    seen: list = []
    real = seismic_rules.omega_rs_combinations

    def spy(combinations, s, *args):
        seen.append(s.site.siteClass)
        return real(combinations, s, *args)

    class Stop(Exception):
        pass

    def stop(*args, **kwargs):
        raise Stop

    rs = [{"name": "1.2D + 1.0RSX + 1.0L", "loads": {"D": 1.2, "L": 1.0}, "envelope": {"RSX": 1}}]
    monkeypatch.setattr(check.seismic_rules, "omega_rs_combinations", spy)
    monkeypatch.setattr(seismic_design, "load_summary", lambda out_dir: {"combinations": rs})
    monkeypatch.setattr(seismic_design, "design_demands", stop)
    with pytest.raises(Stop):
        _report(root)
    assert seen == ["SD"]
