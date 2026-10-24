"""The drawing set as sheets: which views go on which sheet, the sheet numbers, and the files
(one DXF per sheet, one PDF of all sheets, a PNG preview per sheet).

How it is called::

    data = drawing_set(project_root)                       # saengine.drawings.sheets.project
    settings = DrawingSettings.from_dict({"size": "A1", "planScale": 100, ...})
    sheets = build_sheets(data, settings)                  # in memory: Sheet objects (ezdxf)
    result = write_drawings(sheets, out_dir)               # the files

``write_drawings`` returns ``{"sheets": [{"number", "title", "dxf", "pdfPage", "png", "size",
"scale", "views"}], "pdf", "problems"}`` with absolute paths (the shape the Exports page reads).

Sheet order and numbers (``S-101`` on): general notes and tables; the foundation plan; the
framing plans per level; the slab reinforcement plans; the column schedule; the beam elevations;
the footing, wall and stair details; the bar bending schedule. A category takes as many sheets
as its views need; small views share a sheet.

Why one DXF per sheet in model space: LibreCAD 2.2 edits the model space only (it has no paper
space layouts), so every sheet is complete there, plans at real size; each DXF also carries a
paper space layout with one viewport at the sheet's scale for CAD programs that plot layouts.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saengine.drawings.sheets import details, plans, schedules
from saengine.drawings.sheets.layout import Sheet, ViewSpec, drawing_area, fits, pack, paper_size
from saengine.drawings.sheets.model import DrawingSet

PLAN_SCALES = (50, 75, 100, 125, 150, 200, 250, 300, 400, 500)
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


@dataclass
class DrawingSettings:
    """The drawing settings (sheet size, scales, numbering)."""

    size: str = "A1"
    plan_scale: float = 100
    slab_scale: float = 50
    elevation_scale: float = 50
    detail_scale: float = 25
    prefix: str = "S-"
    first: int = 101
    ppi: float = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DrawingSettings:
        data = data or {}
        keys = {
            "size": "size",
            "planScale": "plan_scale",
            "slabScale": "slab_scale",
            "elevationScale": "elevation_scale",
            "detailScale": "detail_scale",
            "sheetPrefix": "prefix",
            "firstNumber": "first",
            "previewPpi": "ppi",
        }
        values = {}
        for key, name in keys.items():
            value = data.get(key, data.get(name))
            if value is not None:
                values[name] = value
        settings = cls(**values)
        settings.size = str(settings.size).upper()
        paper_size(settings.size)
        return settings


@dataclass
class _Category:
    title: str
    scale: float
    specs: list[ViewSpec]
    plan: bool = False
    scale_text: str | None = None


def _fit_plan(
    make: Callable[[float], ViewSpec | None], scale: float, area
) -> tuple[ViewSpec | None, list[str]]:
    """A plan view at ``scale``, or at the next larger scale that fits the sheet."""
    spec = make(scale)
    if spec is None or fits(spec, area):
        return spec, []
    for s in (s for s in PLAN_SCALES if s > scale):
        candidate = make(s)
        if candidate is not None and fits(candidate, area):
            return candidate, [f"{candidate.title}: drawn at 1:{s:g}, 1:{scale:g} does not fit"]
    return spec, [f"{spec.title}: too large for the sheet at 1:{PLAN_SCALES[-1]}"]


DETAIL_SCALES = (25, 50, 75, 100, 150, 200)


def _fit_detail(
    make: Callable[[float], ViewSpec], scale: float, area
) -> tuple[ViewSpec, list[str]]:
    """A detail at ``scale``, or at the next smaller scale (of ``DETAIL_SCALES``) that fits."""
    spec = make(scale)
    if fits(spec, area):
        return spec, []
    for s in (s for s in DETAIL_SCALES if s > scale):
        candidate = make(s)
        if fits(candidate, area):
            candidate.group = "refit"  # the sheet's scale is then "AS SHOWN"
            return candidate, [f"{candidate.title}: drawn at 1:{s:g}, 1:{scale:g} does not fit"]
    return spec, []


def _details(make, items, scale: float, area, problems: list[str]) -> list[ViewSpec]:
    specs = []
    for item in items:
        spec, p = _fit_detail(lambda s, item=item: make(item, s), scale, area)
        problems += p
        specs.append(spec)
    return specs


def categories(data: DrawingSet, settings: DrawingSettings) -> tuple[list[_Category], list[str]]:
    """The views of the drawing set by sheet category."""
    area = drawing_area(settings.size)
    height = area[3] - area[1]
    problems: list[str] = []
    out: list[_Category] = []
    b = data.building
    # general notes and their tables
    specs = [schedules.notes_spec(data.notes)] if data.notes else []
    for table in data.tables:
        specs += schedules.table_specs(
            table, height, key=f"notes-table:{table.title}", max_width=area[2] - area[0]
        )
    if specs:
        out.append(_Category("General notes", 1, specs, scale_text="NTS"))
    # plans
    by_scale: dict[float, list[ViewSpec]] = {}
    spec, p = _fit_plan(lambda s: plans.foundation_plan(b, s), settings.plan_scale, area)
    problems += p
    if spec is not None:
        out.append(_Category("Foundation plan", spec.scale, [spec], plan=True))
    levels = sorted(b.levels, key=lambda lv: lv.elevation)
    for lv in levels:
        if plans.level_has_plan(b, lv):
            spec, p = _fit_plan(
                lambda s, lv=lv: plans.framing_plan(b, lv, s), settings.plan_scale, area
            )
            problems += p
            by_scale.setdefault(spec.scale, []).append(spec)
    for scale, specs in by_scale.items():
        out.append(_Category("Framing plans", scale, specs, plan=True))
    by_scale = {}
    for lv in levels:
        if any(s.level == lv.id for s in data.slabs):
            spec, p = _fit_plan(
                lambda s, lv=lv: plans.slab_plan(b, data.slabs, lv, s), settings.slab_scale, area
            )
            problems += p
            by_scale.setdefault(spec.scale, []).append(spec)
    for scale, specs in by_scale.items():
        out.append(_Category("Slab reinforcement plans", scale, specs, plan=True))
    # schedules and details
    size = (area[2] - area[0], height)
    specs = schedules.column_schedule(data.columns, b.levels, settings.detail_scale, size)
    if specs:
        out.append(
            _Category(
                "Column schedule",
                settings.detail_scale,
                specs,
                scale_text=f"1:{settings.detail_scale:g}",
            )
        )
    specs = _details(
        lambda beam, s: schedules.beam_elevation(beam, s, min(settings.detail_scale, s)),
        data.beams,
        settings.elevation_scale,
        area,
        problems,
    )
    if specs:
        out.append(
            _Category(
                "Beam elevations",
                settings.elevation_scale,
                specs,
                scale_text=f"1:{settings.elevation_scale:g}, 1:{settings.detail_scale:g}",
            )
        )
    specs = _details(details.footing_detail, data.footings, settings.detail_scale, area, problems)
    if specs:
        out.append(
            _Category(
                "Foundation details",
                settings.detail_scale,
                specs,
                scale_text=f"1:{settings.detail_scale:g}",
            )
        )
    specs = _details(
        lambda w, s: details.wall_detail(
            w, s, s / 2 if s > settings.elevation_scale else settings.detail_scale
        ),
        data.walls,
        settings.elevation_scale,
        area,
        problems,
    )
    if specs:
        out.append(
            _Category(
                "Wall details",
                settings.elevation_scale,
                specs,
                scale_text=f"1:{settings.elevation_scale:g}, 1:{settings.detail_scale:g}",
            )
        )
    specs = _details(details.stair_detail, data.stairs, settings.detail_scale, area, problems)
    if specs:
        out.append(
            _Category(
                "Stair details",
                settings.detail_scale,
                specs,
                scale_text=f"1:{settings.detail_scale:g}, 1:{settings.detail_scale * 2:g}",
            )
        )
    specs = []
    for table in data.bbs:
        specs += schedules.table_specs(
            table, height, key=f"bbs:{table.title}", max_width=area[2] - area[0]
        )
    if specs:
        out.append(_Category("Bar bending schedule", 1, specs, scale_text="NTS"))
    for category in out:
        for spec in category.specs:
            if not fits(spec, area):
                problems.append(f"{spec.title}: larger than the sheet's drawing area")
    return out, problems


def build_sheets(data: DrawingSet, settings: DrawingSettings | None = None) -> list[Sheet]:
    """The sheets of ``data`` (DXF documents in memory, views drawn)."""
    settings = settings or DrawingSettings()
    area = drawing_area(settings.size)
    cats, problems = categories(data, settings)
    data.problems += problems
    sheets: list[Sheet] = []
    number = settings.first
    for cat in cats:
        pages = pack(cat.specs, area)
        for i, page in enumerate(pages):
            title = cat.title
            if cat.plan:
                names = [spec.title.split(" - ", 1)[-1] for spec, _, _ in page]
                title = f"{cat.title} - {', '.join(names)}" if len(names) > 0 else title
                if len(page) == 1:
                    title = page[0][0].title
            elif len(pages) > 1:
                title = f"{cat.title} ({i + 1} of {len(pages)})"
            sheet = Sheet(
                f"{settings.prefix}{number}",
                title,
                settings.size,
                cat.scale,
                data.title,
                scale_text=(
                    "AS SHOWN"
                    if any(spec.group == "refit" for spec, _, _ in page)
                    else cat.scale_text or f"1:{cat.scale:g}"
                ),
                north=data.building.north if cat.plan else None,
            )
            sheet.category = cat.title  # type: ignore[attr-defined]
            for spec, x, y in page:
                sheet.view(spec, x, y)
            if cat.plan:
                sheet.notes(_plan_notes(data))
            sheet.finish()
            sheets.append(sheet)
            number += 1
    return sheets


def _plan_notes(data: DrawingSet) -> list[str]:
    return [
        "Levels are top of slab.",
        "Hatched: columns and walls below the level; outlined: starting at the level.",
        "Dashed: beams below the slab.",
        "Marks refer to the schedules.",
    ]


MANIFEST = "MANIFEST"
"""The list of the files the last run wrote (one relative path per line)."""


def _earlier_files(out: Path, sheets: Sequence[Sheet]) -> set[str]:
    """The files of an earlier run in ``out`` (relative paths, see :func:`write_drawings`)."""
    manifest = out / MANIFEST
    if manifest.exists():
        names = set()
        for line in manifest.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            parts = Path(name).parts
            # only plain names in out/ or out/previews/, never anything outside
            if not name or ".." in parts or Path(name).is_absolute() or len(parts) > 2:
                continue
            if len(parts) == 2 and parts[0] != "previews":
                continue
            if Path(name).suffix.lower() in (".dxf", ".png", ".pdf"):
                names.add(Path(name).as_posix())
        return names
    prefixes = {re.sub(r"\d+$", "", s.number) for s in sheets}
    names = set()
    for prefix in prefixes:
        pattern = re.compile(rf"^{re.escape(prefix)}\d+( .*)?$")
        for path in out.glob("*.dxf"):
            if pattern.match(path.stem):
                names.add(path.name)
        for path in (out / "previews").glob("*.png"):
            if pattern.match(path.stem):
                names.add(f"previews/{path.name}")
    return names


def sheet_file_name(sheet: Sheet) -> str:
    return _UNSAFE.sub("-", f"{sheet.number} {sheet.title}")[:120].strip()


def write_drawings(
    sheets: Sequence[Sheet],
    out_dir: str | Path,
    *,
    pdf: bool = True,
    png: bool = True,
    ppi: float = 60,
    pdf_name: str = "drawings.pdf",
    problems: Sequence[str] = (),
    clean: bool = True,
) -> dict[str, Any]:
    """Writes one DXF per sheet into ``out_dir``, the PDF of all sheets and the PNG previews
    (``out_dir/previews/<number>.png``); returns what was written (see the module notes).

    ``clean``: the sheet files of an earlier run that this run does not write again (sheets
    renumbered or renamed, a smaller set) are removed. Only files this module wrote are
    touched: those listed in ``out_dir/MANIFEST`` (written each run), or, when there is no
    manifest, DXFs and previews named like sheets (``<prefix><number> <title>.dxf``,
    ``previews/<prefix><number>.png``). Pass ``clean=False`` when writing some sheets only
    (their files are added to the manifest)."""
    from saengine.drawings.sheets.render import render

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    earlier = _earlier_files(out, sheets)
    rows = []
    for i, sheet in enumerate(sheets):
        target = out / f"{sheet_file_name(sheet)}.dxf"
        sheet.doc.saveas(target)
        rows.append(
            {
                "number": sheet.number,
                "title": sheet.title,
                "dxf": str(target),
                "pdfPage": i + 1 if pdf else None,
                "png": None,
                "size": sheet.size,
                "scale": sheet.scale_text,
                "views": [v.spec.title for v in sheet.views],
            }
        )
    rendered = render(
        list(sheets),
        out / pdf_name if pdf else None,
        out / "previews" if png else None,
        ppi=ppi,
    )
    for row, path in zip(rows, rendered.get("png") or []):
        row["png"] = str(path)
    written = {Path(r["dxf"]).name for r in rows}
    written |= {f"previews/{Path(r['png']).name}" for r in rows if r["png"]}
    if rendered.get("pdf"):
        written.add(Path(rendered["pdf"]).name)
    if clean:
        for name in sorted(earlier - written):
            try:
                (out / name).unlink()
            except OSError:
                pass
        kept = written
    else:
        kept = written | {n for n in earlier if (out / n).exists()}
    (out / MANIFEST).write_text("\n".join(sorted(kept)) + "\n", encoding="utf-8")
    return {
        "sheets": rows,
        "pdf": str(rendered["pdf"]) if rendered.get("pdf") else None,
        "problems": list(problems),
    }
