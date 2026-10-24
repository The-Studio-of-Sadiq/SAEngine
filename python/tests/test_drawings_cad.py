"""Drawing sheets as CAD programs read them (AutoCAD, BricsCAD, LibreCAD): only SAEngine's own
table entries (layers, linetypes, the TrueType text style, dimension styles), text at the ISO
plot heights, everything inside the border, a layout that plots as it is. Checked with ezdxf
on the written DXFs; the AutoCAD run itself is the manual check of docs/drawings-qa.md."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from ezdxf import bbox
from test_drawings_sheets import _synthetic_set

from saengine.drawings.sheets import LAYERS, PAPER, DrawingSettings, build_sheets, write_drawings
from saengine.drawings.sheets.layout import (
    FONT,
    HATCH_SCALES,
    LINETYPES,
    MARGIN,
    MARGIN_LEFT,
    PLOT_STYLES,
    PLOTTER,
    TEXT_HEIGHTS,
)

LAYER_NAMES = {name for name, *_ in LAYERS}
STANDARD_LINETYPES = {"BYBLOCK", "BYLAYER", "CONTINUOUS"}


@pytest.fixture(scope="module", params=["A1", "A3"])
def written(request, tmp_path_factory) -> list[tuple[dict, ezdxf.document.Drawing]]:
    """The synthetic set written as DXFs and read back."""
    out = tmp_path_factory.mktemp(f"cad-{request.param}")
    sheets = build_sheets(_synthetic_set(), DrawingSettings.from_dict({"size": request.param}))
    result = write_drawings(sheets, out, ppi=10)
    return [(row, ezdxf.readfile(row["dxf"])) for row in result["sheets"]]


def _scale(doc) -> float:
    return float(doc.header["$DIMSCALE"])


def test_only_our_table_entries(written) -> None:
    for row, doc in written:
        # text styles: Standard and SAE, both the TrueType font (no SHX, no fonts a CAD
        # program would have to substitute)
        assert {s.dxf.name for s in doc.styles} == {"Standard", "SAE"}, row["number"]
        for style in doc.styles:
            assert style.dxf.font == FONT
            assert style.get_extended_font_data()[0] == "Arial"
        # linetypes: ours, each one used by a layer or not, all defined in the file
        names = {lt.dxf.name.upper() for lt in doc.linetypes}
        assert names == STANDARD_LINETYPES | {n for n, _, _ in LINETYPES}
        # layers: ours (and the DXF's 0 and Defpoints that ezdxf or CAD programs add)
        assert {layer.dxf.name for layer in doc.layers} <= LAYER_NAMES | {"0", "Defpoints"}
        assert doc.header["$INSUNITS"] == 4 and doc.header["$MEASUREMENT"] == 1
        assert doc.header["$LTSCALE"] == pytest.approx(_scale(doc))
        assert doc.header["$DIMSTYLE"] in doc.dimstyles


def test_linetypes_plot_their_paper_lengths() -> None:
    from saengine.drawings.sheets import Sheet, TitleInfo

    sheet = Sheet("S-1", "T", "A2", 100, TitleInfo())
    for name, _, pattern in LINETYPES:
        linetype = sheet.doc.linetypes.get(name)
        assert linetype.simplified_line_pattern() == pytest.approx([abs(v) for v in pattern])
    assert sheet.doc.header["$LTSCALE"] == 100
    used = {layer[2].upper() for layer in LAYERS}
    assert used <= {n for n, _, _ in LINETYPES} | {"CONTINUOUS"}


def test_entities_use_defined_layers_linetypes_and_the_text_style(written) -> None:
    for row, doc in written:
        linetypes = {lt.dxf.name.upper() for lt in doc.linetypes}
        for e in doc.modelspace():
            assert e.dxf.layer in LAYER_NAMES, (row["number"], e.dxftype(), e.dxf.layer)
            if e.dxf.hasattr("linetype"):
                assert e.dxf.linetype.upper() in linetypes, (row["number"], e.dxf.linetype)
            if e.dxftype() in ("TEXT", "MTEXT"):
                assert e.dxf.style == "SAE", (row["number"], e.dxf.text)


def test_text_heights_are_the_iso_plot_heights(written) -> None:
    for row, doc in written:
        scale = _scale(doc)
        heights = {round(e.dxf.height / scale, 3) for e in doc.modelspace().query("TEXT")}
        assert heights <= set(TEXT_HEIGHTS), (row["number"], heights)
        for style in doc.dimstyles:
            if style.dxf.name.startswith("SAE-"):
                assert style.dxf.dimtxt in TEXT_HEIGHTS
                assert style.dxf.dimtxsty == "SAE"


def test_everything_but_the_frame_is_inside_the_border(written) -> None:
    for row, doc in written:
        scale = _scale(doc)
        w, h = (v * scale for v in PAPER[row["size"]])
        border = (MARGIN_LEFT * scale, MARGIN * scale, w - MARGIN * scale, h - MARGIN * scale)
        tol = 0.01 * scale  # 0.01 mm on paper
        cache = bbox.Cache()
        for e in doc.modelspace():
            box = bbox.extents([e], fast=True, cache=cache)
            if not box.has_data:
                continue
            if e.dxf.layer == "S-SHEET":  # the frame and its centring marks
                inside = (-tol, -tol, w + tol, h + tol)
            else:
                inside = (border[0] - tol, border[1] - tol, border[2] + tol, border[3] + tol)
            assert box.extmin.x >= inside[0] and box.extmin.y >= inside[1], (
                row["number"],
                e.dxftype(),
                e.dxf.layer,
            )
            assert box.extmax.x <= inside[2] and box.extmax.y <= inside[3], (
                row["number"],
                e.dxftype(),
                e.dxf.layer,
            )


def test_layout_page_setup_plots_the_sheet(written) -> None:
    for row, doc in written:
        layout = doc.layouts.get(row["number"])
        dxf = layout.dxf_layout.dxf
        w, h = PAPER[row["size"]]
        assert dxf.plot_configuration_file == PLOTTER
        assert dxf.paper_size == f"ISO_full_bleed_{row['size']}_({w:.2f}_x_{h:.2f}_MM)"
        assert dxf.current_style_sheet == PLOT_STYLES
        assert (dxf.scale_numerator, dxf.scale_denominator) == (1, 1)
        viewports = [v for v in layout.query("VIEWPORT") if v.dxf.id != 1]
        assert len(viewports) == 1
        vp = viewports[0]
        assert vp.dxf.layer == "S-VIEWPORT"
        assert vp.dxf.view_height / vp.dxf.height == pytest.approx(_scale(doc))


def test_hatch_patterns_plot_at_their_paper_size(written) -> None:
    for row, doc in written:
        scale = _scale(doc)
        for hatch in doc.modelspace().query("HATCH"):
            if hatch.dxf.solid_fill:
                continue
            name = hatch.dxf.pattern_name.upper()
            assert name in HATCH_SCALES, (row["number"], name)
            assert hatch.dxf.pattern_scale == pytest.approx(HATCH_SCALES[name] * scale)


def test_no_dimension_overrides_or_explicit_colours(written) -> None:
    """What a CAD program draws comes from the layers and the styles: no colour, lineweight
    or dimension override that would plot differently from what the layer table says (the
    north arrow's solid fill excepted)."""
    for row, doc in written:
        for e in doc.modelspace():
            if e.dxftype() == "DIMENSION":
                assert not e.has_xdata("ACAD"), row["number"]
            color = e.dxf.get("color", 256)
            if color != 256:
                assert e.dxftype() == "HATCH" and e.dxf.layer == "S-TITLE", (
                    row["number"],
                    e.dxftype(),
                    e.dxf.layer,
                )


def test_qa_harness_skips_without_autocad(tmp_path: Path, monkeypatch) -> None:
    """scripts/drawings_qa runs its ezdxf checks and skips AutoCAD with a message when there
    is no accoreconsole (CI)."""
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("qa", root / "scripts/drawings_qa/qa.py")
    qa = importlib.util.module_from_spec(spec)
    sys.modules["qa"] = qa
    spec.loader.exec_module(qa)
    monkeypatch.setenv("SAE_ACCORECONSOLE", str(tmp_path / "missing.exe"))
    monkeypatch.setenv("SAE_LIBRECAD", str(tmp_path / "missing.exe"))
    sheets = build_sheets(_synthetic_set(), DrawingSettings.from_dict({"size": "A3"}))
    drawings = tmp_path / "Drawings"
    write_drawings(sheets[:2], drawings, ppi=10)
    out = tmp_path / "qa"
    assert qa.main([str(drawings), "--out", str(out)]) == 0
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "not found (skipped)" in report
    data = __import__("json").loads((out / "report.json").read_text(encoding="utf-8"))
    assert len(data["sheets"]) == 2
    for sheet in data["sheets"]:
        assert sheet["ezdxf"]["audit_errors"] == []
        assert sheet["ezdxf"]["odd_text_heights"] == []
        assert sheet["ezdxf"]["out_of_border_count"] == 0
        assert sheet["ezdxf"]["sheet"]["size"] == "A3"


def test_floor_plan_dxf_has_only_its_own_tables() -> None:
    """The per-storey floor plan DXFs (11 Exports/Floor Plan): the Arial text style alone and
    only the linetypes their layers use (ezdxf's, as the app's linetype scales expect)."""
    from saengine.pipeline.exports import LAYERS as PLAN_LAYERS
    from saengine.pipeline.exports import drawing_dxf

    entities = [
        {
            "kind": "line",
            "layer": "S-GRID",
            "start": (0, 0),
            "end": (6000, 0),
            "linetypeScale": 200,
        },
        {"kind": "text", "layer": "S-GRID-IDEN", "position": (0, 500), "height": 350, "text": "A"},
    ]
    doc = ezdxf.read(__import__("io").StringIO(drawing_dxf(entities)))
    assert [(s.dxf.name, s.dxf.font) for s in doc.styles] == [("Standard", FONT)]
    used = {linetype for _, _, linetype, _ in PLAN_LAYERS if linetype}
    assert {lt.dxf.name.upper() for lt in doc.linetypes} == STANDARD_LINETYPES | used
    assert not doc.audit().has_errors
    assert next(iter(doc.modelspace().query("TEXT"))).dxf.style == "Standard"
