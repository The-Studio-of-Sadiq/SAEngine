"""Sheets to PDF and PNG: each sheet's model space is drawn to SVG at its paper size and scale
by ezdxf's drawing add-on (its SVG backend, pure Python), and Typst, which SAEngine already
bundles for the design report, sets the SVGs as the pages of one PDF and as PNG previews.

Why this route: it adds no dependency to the installer. PyMuPDF (AGPL-3.0, the add-on's PDF
backend) is in the development environment only, and matplotlib (also possible) is slower and
draws lineweights less faithfully; the SVG backend writes the plot lineweights of the layers
(mm) and the text as filled outlines, so the pages look the same everywhere.

Plotting style: black on white, the lineweights of the layers. The DXF's SHX font is swapped
for a TrueType font (Arial, else ezdxf's fallback) while drawing, since SHX fonts are not
shipped with SAEngine.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

from saengine.drawings.sheets.layout import Sheet

PDF_FONT = "arial.ttf"


def sheet_svg(sheet: Sheet) -> str:
    """The SVG of ``sheet`` at its paper size (mm)."""
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg

    style = sheet.doc.styles.get("SAE")
    font = style.dxf.font
    style.dxf.font = PDF_FONT
    try:
        backend = svg.SVGBackend()
        cfg = config.Configuration(
            color_policy=config.ColorPolicy.BLACK,
            background_policy=config.BackgroundPolicy.WHITE,
            lineweight_policy=config.LineweightPolicy.ABSOLUTE,
            min_lineweight=0.09,
            hatch_policy=config.HatchPolicy.NORMAL,
        )
        context = RenderContext(sheet.doc)
        Frontend(context, backend, config=cfg).draw_layout(sheet.msp, finalize=True)
        page = layout.Page(sheet.width, sheet.height, layout.Units.mm)
        settings = layout.Settings(fit_page=False, scale=1 / sheet.scale)
        return backend.get_string(page, settings=settings)
    finally:
        style.dxf.font = font


def render(
    sheets: Sequence[Sheet],
    pdf: Path | None = None,
    png_dir: Path | None = None,
    ppi: float = 60,
    png_names: Sequence[str] | None = None,
) -> dict[str, object]:
    """Writes the sheets as the pages of ``pdf`` and as PNGs in ``png_dir`` (named
    ``png_names`` or by sheet number). Returns ``{"pdf": Path | None, "png": [Path, ...]}``."""
    import typst

    result: dict[str, object] = {"pdf": None, "png": []}
    if not sheets or (pdf is None and png_dir is None):
        return result
    with tempfile.TemporaryDirectory(prefix="saengine-sheets-") as tmp:
        root = Path(tmp)
        pages = []
        for i, sheet in enumerate(sheets):
            name = f"sheet-{i + 1}.svg"
            (root / name).write_text(sheet_svg(sheet), encoding="utf-8")
            pages.append(
                f"#page(width: {sheet.width}mm, height: {sheet.height}mm, margin: 0pt)"
                f'[#image("{name}", width: 100%, height: 100%, fit: "stretch")]'
            )
        source = root / "sheets.typ"
        source.write_text("\n".join(pages) + "\n", encoding="utf-8")
        if pdf is not None:
            pdf.parent.mkdir(parents=True, exist_ok=True)
            typst.compile(str(source), output=str(root / "sheets.pdf"), root=str(root))
            pdf.write_bytes((root / "sheets.pdf").read_bytes())
            result["pdf"] = pdf
        if png_dir is not None:
            png_dir.mkdir(parents=True, exist_ok=True)
            typst.compile(
                str(source),
                output=str(root / "page-{p}.png"),
                format="png",
                ppi=ppi,
                root=str(root),
            )
            written = []
            for i, sheet in enumerate(sheets):
                made = _page_png(root, i + 1, len(sheets))
                name = (png_names[i] if png_names else sheet.number) + ".png"
                target = png_dir / name
                target.write_bytes(made.read_bytes())
                written.append(target)
            result["png"] = written
    return result


def _page_png(root: Path, page: int, pages: int) -> Path:
    """Typst pads ``{p}`` with zeros to the width of the page count."""
    for candidate in (f"page-{page}.png", f"page-{page:0{len(str(pages))}d}.png"):
        if (root / candidate).exists():
            return root / candidate
    raise FileNotFoundError(f"page {page} was not rendered")
