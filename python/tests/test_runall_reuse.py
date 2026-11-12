"""Run All's reuse: section properties once per profile, the design checks once per change."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from saengine.library import objects as o
from saengine.library import section_designer as sd
from saengine.library import sections
from saengine.pipeline import design_mode

# ─────────────────────────────── section properties ───────────────────────────────


def _counting_solves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """A fresh memo and disk cache, and the keys :func:`sections._solve` is called for."""
    monkeypatch.setenv(sections.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(sections, "_MEMO", {})
    solved: list[str] = []
    solve = sections._solve

    def counted(key: str) -> sections.SectionProperties:
        solved.append(key)
        return solve(key)

    monkeypatch.setattr(sections, "_solve", counted)
    return solved


def test_section_properties_are_worked_out_once_per_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    solved = _counting_solves(monkeypatch, tmp_path)
    first = sections.section_properties(o.RectangleProfile(xDim=300, yDim=500))
    # The same dimensions, as floats and on another object: the kept answer.
    again = sections.section_properties(o.RectangleProfile(xDim=300.0, yDim=500.0))
    assert again is first
    assert len(solved) == 1
    # Exactly what a computation of its own gives.
    key = sections.profile_key(o.RectangleProfile(xDim=300, yDim=500))
    assert sections._solve(key) == first
    assert first.area == pytest.approx(150_000)


def test_section_properties_are_kept_on_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    solved = _counting_solves(monkeypatch, tmp_path)
    profile = o.RectangleProfile(xDim=300, yDim=500)
    first = sections.section_properties(profile)
    monkeypatch.setattr(sections, "_MEMO", {})  # a new process
    assert sections.section_properties(profile) == first
    assert len(solved) == 1
    monkeypatch.setenv(sections.CACHE_ENV, "0")
    monkeypatch.setattr(sections, "_MEMO", {})
    assert sections.section_properties(profile) == first
    assert len(solved) == 2


def test_prefetch_solves_the_missing_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(sections.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setenv(sections.JOBS_ENV, "2")
    monkeypatch.setattr(sections, "_MEMO", {})
    profiles = [o.RectangleProfile(xDim=300, yDim=500), o.RectangleProfile(xDim=400, yDim=400)]
    sections.prefetch_section_properties([*profiles, profiles[0]])
    keys = [sections.profile_key(p) for p in profiles]
    assert all(k in sections._MEMO for k in keys)
    for profile, key in zip(profiles, keys, strict=True):
        assert sections.section_properties(profile) == sections._solve(key)


def test_the_key_tells_shapes_and_dimensions_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profiles = [
        o.RectangleProfile(xDim=300, yDim=500),
        o.RectangleProfile(xDim=500, yDim=300),
        o.RectangleProfile(xDim=300, yDim=550),
        o.CircleProfile(radius=250),
        o.RectangleHollowProfile(xDim=300, yDim=500, wallThickness=10),
        o.RectangleHollowProfile(xDim=300, yDim=500, wallThickness=12),
        o.IShapeProfile(overallDepth=300, overallWidth=150, flangeThickness=10, webThickness=7),
        o.IShapeProfile(
            overallDepth=300,
            overallWidth=150,
            flangeThickness=10,
            webThickness=7,
            filletRadius=10,
        ),
    ]
    keys = {sections.profile_key(p) for p in profiles}
    assert len(keys) == len(profiles)
    solved = _counting_solves(monkeypatch, tmp_path)
    rotated = sections.section_properties(profiles[1])
    upright = sections.section_properties(profiles[0])
    assert rotated.ixx == pytest.approx(upright.iyy)
    assert len(solved) == 2


def test_a_designed_section_is_keyed_by_its_definition(tmp_path: Path) -> None:
    from saengine.codes import context

    (tmp_path / "02 Project Settings").mkdir()
    profile = o.DesignedProfile(section="L1")

    def save(leg: float) -> None:
        outline = [(0, 0), (600, 0), (600, leg), (leg, leg), (leg, 600), (0, 600)]
        region = sd.Region(outline=outline, material="C30")
        sd.save_section(tmp_path, sd.DesignedSection(id="L1", name="L", regions=[region]))

    save(250)
    with context.project(tmp_path):
        first = sections.section_properties(profile)
        assert sections.section_properties(profile) is first
        save(300)  # the engineer edits the section: new properties, not the kept ones
        edited = sections.section_properties(profile)
    assert first.area == pytest.approx(237_500)
    assert edited.area == pytest.approx(2 * 600 * 300 - 300 * 300)


# ─────────────────────────────── the design checks ───────────────────────────────


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "P"
    for relative in design_mode.INPUT_FILES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("{}", "utf-8")
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True)
    model.write_text("{}", "utf-8")
    out = root / "08 FEM" / "model.results"
    out.mkdir()
    (out / "case-1.h5").write_bytes(b"results")
    return out, model


class _Gathered:
    def __init__(self, n: int, assumed: set[str]) -> None:
        self.report = {"elements": [{"id": "B1", "ok": True, "checks": []}], "gathering": n}
        self.collect: dict[str, Any] = {"members": []}
        self.assumed = assumed
        self.root = Path("no such project")  # no foundations to add
        # design's report without the assumed bars: told for slabs only.
        if not assumed:
            self.plain: dict[str, Any] | None = self.report
        elif all(t.startswith("S") for t in assumed):
            self.plain = {"elements": [], "gathering": n, "noBars": sorted(assumed)}
        else:
            self.plain = None


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Fake gather, design_report and design_required counting their calls."""
    import saengine.design
    from saengine.design import required

    calls: dict[str, list[Any]] = {"gather": [], "report": [], "required": []}
    assumed: set[str] = set()

    def gather(out_dir: Any, project_path: Any, substructure: bool = True) -> _Gathered:
        calls["gather"].append(substructure)
        return _Gathered(len(calls["gather"]), set(assumed))

    def design_report(out_dir: Any, project_path: Any) -> dict[str, Any]:
        calls["report"].append(1)
        return {"elements": [], "alone": len(calls["report"])}

    def design_required(
        out_dir: Any, project_path: Any, options: Any = None, gathered: Any = None
    ) -> dict[str, Any]:
        calls["required"].append(gathered)
        return {"elements": [], "summary": {}}

    design_mode.forget()
    monkeypatch.setattr(design_mode, "_ensure_seismic_design", lambda *_: None)
    monkeypatch.setattr(required, "gather", gather)
    monkeypatch.setattr(saengine.design, "design_report", design_report)
    monkeypatch.setattr(saengine.design, "design_required", design_required)
    calls["assumed"] = assumed  # type: ignore[assignment]
    yield calls
    design_mode.forget()


def test_run_all_designs_once(tmp_path: Path, counted: dict[str, list[Any]]) -> None:
    out, model = _project(tmp_path)
    stamp = design_mode.report_stamp(out, model)
    # Run All's design step: the checks, their report, the required steel.
    gathered = design_mode.gathered(out, model, stamp)
    report = design_mode.checks(out, model, stamp)
    assert report == gathered.report and report is not gathered.report
    design_mode.keep_report(out, model, report, stamp)
    (out / "design-summary.json").write_text("{}", "utf-8")
    design_mode.required(out, model)
    assert counted["required"] == [gathered]
    # The report and the column view after it.
    report["elements"].clear()  # a caller's change never reaches the kept checks
    assert design_mode.checks(out, model) == gathered.report
    assert design_mode.gathered(out, model, substructure=False) is gathered
    assert design_mode.report(out, model) == gathered.report
    assert counted["gather"] == [True] and counted["report"] == []


def test_a_changed_input_designs_again(tmp_path: Path, counted: dict[str, list[Any]]) -> None:
    out, model = _project(tmp_path)
    first = design_mode.gathered(out, model)
    (model.parent.parent / "04 Objects" / "objects.json").write_text('{"objects": []}', "utf-8")
    second = design_mode.gathered(out, model)
    assert second is not first and design_mode.checks(out, model)["gathering"] == 2
    (out / "case-1.h5").write_bytes(b"a new analysis")
    # The checks made now are one gathering, which the proposal and the required steel reuse.
    assert design_mode.checks(out, model)["gathering"] == 3
    assert design_mode.checks(out, model)["gathering"] == 3  # kept as well
    assert design_mode.gathered(out, model, substructure=False).report["gathering"] == 3
    assert counted["gather"] == [True, True, False] and counted["report"] == []


def test_a_gathering_without_the_substructure_is_not_enough(
    tmp_path: Path, counted: dict[str, list[Any]]
) -> None:
    # The foundations are added to it rather than every member designed again.
    out, model = _project(tmp_path)
    first = design_mode.gathered(out, model, substructure=False)
    assert design_mode.gathered(out, model) is first
    assert counted["gather"] == [False]


def test_checks_with_assumed_bars_are_not_the_report(
    tmp_path: Path, counted: dict[str, list[Any]]
) -> None:
    # The required steel checks types without bars with assumed ones; the report does not.
    counted["assumed"].add("B300")  # type: ignore[attr-defined]
    out, model = _project(tmp_path)
    design_mode.gathered(out, model)
    assert design_mode.checks(out, model) == {"elements": [], "alone": 1}


def test_checks_with_assumed_slab_bars_tell_the_report(
    tmp_path: Path, counted: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A wizard project's slab type has no bars: the gathering gives the report too.
    counted["assumed"].add("S150")  # type: ignore[attr-defined]
    monkeypatch.setattr(design_mode, "_has_assumed_bars", lambda _: False)
    out, model = _project(tmp_path)
    report = design_mode.checks(out, model)
    assert report == {"elements": [], "gathering": 1, "noBars": ["S150"]}
    design_mode.required(out, model)
    assert counted["gather"] == [False] and counted["report"] == []
    assert counted["required"] == [design_mode.gathered(out, model)]


def test_has_assumed_bars_leaves_slabs_out(tmp_path: Path) -> None:
    from test_design import COLUMN_REINFORCEMENT, beam_reinforcement
    from test_fem_derive import OBJECTS

    from saengine.library import default_material_library

    root = tmp_path / "P"
    (root / "03 Materials").mkdir(parents=True)
    (root / "04 Objects").mkdir()
    materials = default_material_library().model_dump_json(by_alias=True)
    (root / "03 Materials/materials.json").write_text(materials, "utf-8")

    def has(*with_bars: str) -> bool:
        data = OBJECTS.model_dump(mode="json", by_alias=True)
        bars = {"BM": beam_reinforcement(top=3), "COL": COLUMN_REINFORCEMENT}
        for t in data["objects"]:
            if t["id"] in with_bars:
                t["reinforcement"] = bars[t["id"]].model_dump(mode="json")
        (root / "04 Objects/objects.json").write_text(json.dumps(data), "utf-8")
        return design_mode._has_assumed_bars(root / "08 FEM" / "model.osmodel")

    assert not has("BM", "COL")  # the slab type SL has none
    assert has("COL")


def test_files_written_after_the_stamp_do_not_make_the_kept_answers_stale(
    tmp_path: Path,
) -> None:
    from saengine.fem.end_zones import FACE_FORCES_FILE
    from saengine.fem.member_detail import CACHE_FILE

    out, model = _project(tmp_path)
    stamp = design_mode.inputs_stamp(out, model)
    # The first design after a run writes the face forces; the column view its diagrams.
    for name in (FACE_FORCES_FILE, CACHE_FILE, *design_mode._DERIVED):
        (out / name).write_text(json.dumps({"written": name}), "utf-8")
    assert design_mode.inputs_stamp(out, model) == stamp
    design_mode.keep(out, stamp, {"elements": []})
    assert design_mode.kept(out, design_mode.inputs_stamp(out, model)) == {"elements": []}
    # An output of the analysis does.
    (out / "case-2.h5").write_bytes(b"more results")
    assert design_mode.inputs_stamp(out, model) != stamp
