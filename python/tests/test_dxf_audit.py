"""The floor-plan DXFs pass ezdxf's audit with no fixes (walkthrough 3, OI-7)."""

from __future__ import annotations

import shutil
from pathlib import Path

from saengine.library.dxf_audit import audit_dxf, clean_dxf, rpc_clean_dxf
from saengine.pipeline.exports import export_dxf
from saengine.pipeline.project import open_project

DATA = Path(__file__).parent / "data" / "export"
SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


def test_cad_editor_floor_plan_is_repaired(tmp_path: Path) -> None:
    # The sample's Level 1 plan as the app's CAD editor (mlightcad) wrote it in walkthrough 3:
    # invalid "ByLayer" transparency on every entity, MTEXT style "0", stale owner handles.
    path = tmp_path / "L1 Level 1.dxf"
    shutil.copy(DATA / "cad-editor-floor-plan.dxf", path)
    assert audit_dxf(path)["fixes"] > 40
    result = clean_dxf(path)
    assert result["fixed"] > 40 and result["errors"] == 0
    assert audit_dxf(path) == {"errors": 0, "fixes": 0}
    # The drawing is kept: its grids, members and labels.
    import ezdxf

    layers = {e.dxf.layer for e in ezdxf.readfile(path).modelspace()}
    assert {"S-GRID", "S-COLS", "S-BEAM", "S-SLAB", "S-ANNO-IDEN"} <= layers
    # A clean file is left as it is; an unreadable one is reported.
    assert clean_dxf(path)["fixed"] == 0
    bad = tmp_path / "bad.dxf"
    bad.write_text("not a drawing", encoding="utf-8")
    answer = rpc_clean_dxf({"paths": [str(path), str(bad)]})
    assert not answer["ok"] and answer["files"][0]["fixed"] == 0
    assert "message" in answer["files"][1]


def test_python_floor_plan_export_audits_clean(tmp_path: Path) -> None:
    project = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, project)
    written = export_dxf(open_project(project))
    assert written
    for path in written:
        assert audit_dxf(path) == {"errors": 0, "fixes": 0}, path.name
