"""DWG drawings through GNU LibreDWG's dwg2dxf (saengine.library.dwg).

The fixtures (tests/data/dwg) are SAEngine's own plan geometry saved by AutoCAD in each DWG
version (make_fixtures.py). Tests that run the converter are skipped where LibreDWG is not
installed (set SAENGINE_LIBREDWG to its folder); the others always run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from saengine.library import FloorPlan, dwg
from saengine.library.importers import ImportOptions, import_geometry
from saengine.project.archive import is_computed
from saengine.rpc import handlers

DATA = Path(__file__).parent / "data" / "dwg"
VERSIONS = ("r2000", "r2004", "r2007", "r2010", "r2013", "r2018")
LAYERS = {"A-WALL", "A-DOOR", "A-GRID", "A-TEXT"}
ENTITIES = {
    ("LWPOLYLINE", "A-WALL"): 2,
    ("LINE", "A-WALL"): 2,
    ("LINE", "A-GRID"): 5,
    ("ARC", "A-DOOR"): 1,
    ("LINE", "A-DOOR"): 1,
    ("CIRCLE", "A-DOOR"): 1,
    ("TEXT", "A-TEXT"): 2,
}

needs_libredwg = pytest.mark.skipif(
    dwg.find_converter() is None,
    reason=f"GNU LibreDWG's dwg2dxf is not installed (set {dwg.ENV_VAR} to its folder)",
)


def fixture(tmp_path: Path, version: str = "r2018", folder: str = "Underlays") -> Path:
    target = tmp_path / folder / f"plan-{version}.dwg"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA / f"plan-{version}.dwg", target)
    return target


@pytest.mark.parametrize("version", VERSIONS)
def test_fixtures_are_dwg(version: str) -> None:
    expected = {"r2000": b"AC1015", "r2004": b"AC1018", "r2007": b"AC1021",
                "r2010": b"AC1024", "r2013": b"AC1027", "r2018": b"AC1032"}  # fmt: skip
    assert (DATA / f"plan-{version}.dwg").read_bytes()[:6] == expected[version]


@needs_libredwg
@pytest.mark.parametrize("version", VERSIONS)
def test_every_version_converts_with_its_layers_and_extents(tmp_path: Path, version: str) -> None:
    import ezdxf
    from ezdxf import bbox

    source = fixture(tmp_path, version)
    result = dwg.convert(source)
    assert result.dxf == source.parent / ".dwg-cache" / f"plan-{version}.dwg.dxf"
    assert not result.cached and all(isinstance(w, str) for w in result.warnings)
    doc = ezdxf.readfile(result.dxf)
    msp = doc.modelspace()
    found: dict[tuple[str, str], int] = {}
    for e in msp:
        key = (e.dxftype(), e.dxf.layer)
        found[key] = found.get(key, 0) + 1
    assert found == ENTITIES
    assert LAYERS <= {layer.dxf.name for layer in doc.layers}
    assert doc.header["$INSUNITS"] == 4  # mm
    extents = bbox.extents(msp)
    assert tuple(extents.extmin)[:2] == pytest.approx((0, 0))
    assert tuple(extents.extmax)[:2] == pytest.approx((12000, 9000))


@needs_libredwg
def test_the_conversion_is_cached_until_the_dwg_changes(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    first = dwg.convert(source)
    again = dwg.convert(source)
    assert again.cached and again.dxf == first.dxf and again.warnings == first.warnings
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert not dwg.convert(source).cached


@needs_libredwg
def test_names_outside_the_ansi_code_page(tmp_path: Path) -> None:
    source = fixture(tmp_path, folder="প্রকল্প/নকশা")
    renamed = source.with_name("স্থপতি নকশা.dwg")
    source.rename(renamed)
    result = dwg.convert(renamed)
    assert result.dxf.name == "স্থপতি নকশা.dwg.dxf" and result.dxf.stat().st_size > 0


@needs_libredwg
def test_dwg_import(tmp_path: Path) -> None:
    options = ImportOptions(memberType="BM")
    g = import_geometry(fixture(tmp_path), options, {"BM": "beam"})
    # The 9 lines, the arc in pieces, the circle and the polylines' sides become members.
    assert len(g.members) > 9
    assert any("TEXT" in note for note in g.notes)
    # The temporary DXF is gone: nothing was written beside the DWG.
    assert not (tmp_path / "Underlays" / ".dwg-cache").exists()
    for m in g.members:
        assert -1 <= min(m.start[0], m.end[0]) and max(m.start[0], m.end[0]) <= 12001


@needs_libredwg
def test_a_file_that_is_not_a_dwg(tmp_path: Path) -> None:
    bad = tmp_path / "plan.dwg"
    bad.write_text("0\nSECTION\n", encoding="ascii")
    with pytest.raises(dwg.DwgError, match="is not a DWG drawing"):
        dwg.convert(bad)


@needs_libredwg
def test_a_real_timeout(tmp_path: Path) -> None:
    with pytest.raises(dwg.DwgError, match=r"did not finish within 1e-06 s"):
        dwg.convert(fixture(tmp_path, "r2000"), timeout=1e-6)


def test_a_timeout_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(command: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])  # type: ignore[arg-type]

    monkeypatch.setattr(dwg, "find_converter", lambda explicit=None: tmp_path / dwg.EXE)
    monkeypatch.setattr(dwg.subprocess, "run", hang)
    with pytest.raises(dwg.DwgError) as caught:
        dwg.convert(fixture(tmp_path), timeout=5)
    assert "did not finish within 5 s" in str(caught.value)
    assert "save the drawing as DXF" in str(caught.value)
    assert not list((tmp_path / "Underlays" / ".dwg-cache").glob("*.dxf"))


def test_a_failed_conversion_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stderr = "Warning: Unstable Class object\nERROR 0x40 bad section\n"
        return subprocess.CompletedProcess(command, 1, "", stderr)

    monkeypatch.setattr(dwg, "find_converter", lambda explicit=None: tmp_path / dwg.EXE)
    monkeypatch.setattr(dwg.subprocess, "run", fail)
    with pytest.raises(dwg.DwgError, match=r"exit code 1: ERROR 0x40 bad section\); save it"):
        dwg.convert(fixture(tmp_path))
    answer = handlers.convert_dwg(str(fixture(tmp_path)))
    assert answer["ok"] is False and answer["code"] == "failed"


def test_without_a_converter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dwg.ENV_VAR, str(tmp_path / "nowhere"))
    monkeypatch.setattr(dwg.sys, "executable", str(tmp_path / "python" / "python.exe"))
    monkeypatch.setattr(dwg.shutil, "which", lambda name: None)
    assert dwg.find_converter() is None
    source = fixture(tmp_path)
    with pytest.raises(dwg.ConverterMissing, match=dwg.ENV_VAR):
        dwg.convert(source)
    answer = handlers.convert_dwg(str(source))
    assert answer == {"ok": False, "code": "no-converter", "message": answer["message"]}
    assert "save the drawing as DXF" in answer["message"]
    problems = handlers.import_geometry(str(source), {}, None)["problems"]
    assert problems[0].startswith("plan-r2018.dwg: opening DWG drawings needs GNU LibreDWG")
    assert not handlers.convert_dwg(str(tmp_path / "missing.dwg"))["ok"]


def test_the_converter_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "libredwg"
    folder.mkdir()
    (folder / dwg.EXE).write_bytes(b"")
    monkeypatch.setenv(dwg.ENV_VAR, str(folder))
    assert dwg.find_converter() == folder / dwg.EXE
    monkeypatch.setenv(dwg.ENV_VAR, str(folder / dwg.EXE))
    assert dwg.find_converter() == folder / dwg.EXE
    # The bundled copy: <app>/resources/python/python.exe -> <app>/resources/libredwg.
    monkeypatch.delenv(dwg.ENV_VAR)
    monkeypatch.setattr(dwg.sys, "executable", str(tmp_path / "python" / "python.exe"))
    assert dwg.find_converter() == folder / dwg.EXE


def test_underlays_may_be_dwg() -> None:
    from test_floorplan import model

    for name in ("Underlays/architect L1.dwg", "plan.DWG", "a.dxf"):
        plan = FloorPlan.model_validate(model(underlays=[{"story": "L1", "file": name}]))
        assert plan.underlays[0].file == name
    for name in ("plan.dwgx", "plan.dw", "plan.pdf"):
        with pytest.raises(ValueError, match="pattern"):
            FloorPlan.model_validate(model(underlays=[{"story": "L1", "file": name}]))


def test_the_cache_is_computed() -> None:
    assert is_computed("05 Floor Plan/Underlays/.dwg-cache/plan.dwg.dxf")
    assert is_computed("05 Floor Plan/.dwg-cache", folder=True)
    assert not is_computed("05 Floor Plan/Underlays/plan.dwg")


def test_installer_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``components/list``: the component's copy beside the bundled Python is "installed", one
    found elsewhere (the environment variable) "elsewhere", none "missing"."""
    from saengine.hvac import energyplus as EP

    python = tmp_path / "resources" / "python" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    monkeypatch.setattr(dwg.sys, "executable", str(python))
    monkeypatch.setattr(dwg.shutil, "which", lambda name: None)
    monkeypatch.delenv(dwg.ENV_VAR, raising=False)
    monkeypatch.setattr(EP, "_candidates", lambda: [tmp_path / "nowhere", EP.bundled_dir()])
    assert handlers.installer_components() == {
        "energyplus": {"state": "missing"},
        "libredwg": {"state": "missing"},
    }
    bundled = tmp_path / "resources" / "libredwg" / dwg.EXE
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"")
    other = tmp_path / "EnergyPlusV26-2-0" / EP.EXE
    other.parent.mkdir(parents=True)
    other.write_bytes(b"")
    monkeypatch.setattr(EP, "_candidates", lambda: [other.parent, EP.bundled_dir()])
    assert handlers.installer_components() == {
        "energyplus": {"state": "elsewhere", "path": str(other)},
        "libredwg": {"state": "installed", "path": str(bundled)},
    }
