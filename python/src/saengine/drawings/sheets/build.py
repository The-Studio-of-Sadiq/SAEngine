"""The drawing set as sheets: which views go on which sheet, the sheet numbers, and the files
(one DXF per sheet, one PDF of all sheets, a PNG preview per sheet).

How it is called::

    data = drawing_set(project_root)                       # saengine.drawings.sheets.project
    settings = DrawingSettings.from_dict({"size": "A1", "planScale": 100, ...})
    sheets = build_sheets(data, settings)                  # in memory: Sheet objects (ezdxf)
    result = write_drawings(sheets, out_dir)               # the files

``write_drawings`` returns ``{"sheets": [{"number", "title", "dxf", "pdfPage", "png", "size",
"scale", "views"}], "pdf", "problems"}`` with absolute paths (the shape the Exports page reads).

Sheet order and numbers (``S-101`` on): general notes and tables; the foundation plan (with
piles, the pile layout plan and the pile cap schedule); the framing plans per level; the slab
reinforcement plans; the column schedule; the beam elevations; the footing, wall and stair
details; the bar bending schedule; then, with structural steel
(:mod:`.steel`), the steel notes, framing plans, braced elevations, member schedule and
connection details; then, with an architecture (:mod:`.architecture`), the architectural
sheets numbered on their own (``A-101`` on): plans, elevations, sections, the door and window
schedule and the room finish schedule; then, with building services in 07 MEP (:mod:`.mep`), the
plumbing, HVAC, electrical, fire protection and coordination plans and the MEP schedules (``P-``,
``M-``, ``E-``, ``FP-``, ``MC-``). The office standard (:mod:`.standards`) may rename the prefixes
and the layers. A category takes as many sheets as its views need; small views share a sheet.

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

from saengine.drawings.sheets import architecture as ar
from saengine.drawings.sheets import details, plans, schedules
from saengine.drawings.sheets import mep as mp
from saengine.drawings.sheets import steel as st
from saengine.drawings.sheets.layout import (
    Sheet,
    ViewSpec,
    centred,
    drawing_area,
    fits,
    pack,
    paper_size,
)
from saengine.drawings.sheets.model import DrawingSet
from saengine.drawings.sheets.standards import DEFAULT_PREFIXES, Standard

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
    standard: dict[str, Any] | None = None  # the office standard (Drawings > Office standard)

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
            "standard": "standard",
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
    notes: list[str] | None = None  # the sheets' notes (plans: the plans' notes)
    prefix: str | None = None  # of the sheet numbers (None: the settings')


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
    spec, p = _fit_plan(lambda s: plans.pile_layout_plan(b, s), settings.plan_scale, area)
    problems += p
    if spec is not None:
        out.append(_Category("Pile layout plan", spec.scale, [spec], plan=True))
    if data.pile_caps is not None:
        specs = schedules.table_specs(
            data.pile_caps, height, key="pile-caps", max_width=area[2] - area[0]
        )
        out.append(_Category("Pile cap schedule", 1, specs, scale_text="NTS"))
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
    specs += _details(
        details.retaining_wall_detail,
        data.retaining_walls,
        settings.detail_scale,
        area,
        problems,
    )
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
    out += _steel_categories(data, settings, area, problems)
    out += _architecture_categories(data, settings, area, problems)
    out += _mep_categories(data, settings, area, problems)
    for category in out:
        for spec in category.specs:
            if not fits(spec, area):
                problems.append(f"{spec.title}: larger than the sheet's drawing area")
    return out, problems


def build_sheets(
    data: DrawingSet,
    settings: DrawingSettings | None = None,
    before_finish: Callable[[Sheet], None] | None = None,
) -> list[Sheet]:
    """The sheets of ``data`` (DXF documents in memory, views drawn). ``before_finish(sheet)``
    is called once a sheet's views and notes are drawn, before its revisions are written into
    the title block (:mod:`.revisions` sets them there and draws the revision clouds)."""
    settings = settings or DrawingSettings()
    area = drawing_area(settings.size)
    cats, problems = categories(data, settings)
    data.problems += problems
    standard = Standard.from_dict(settings.standard) if settings.standard else None
    if standard is not None:
        data.problems += standard.problems
    sheets: list[Sheet] = []
    numbers: dict[str, int] = {}
    for cat in cats:
        prefix = _prefix(cat.prefix or settings.prefix, standard)
        pages = pack(cat.specs, area)
        if cat.plan:
            pages = [centred(page, area) for page in pages]
        for i, page in enumerate(pages):
            title = cat.title
            if cat.plan:
                names = [spec.title.split(" - ", 1)[-1] for spec, _, _ in page]
                title = f"{cat.title} - {', '.join(names)}" if len(names) > 0 else title
                if len(page) == 1:
                    title = page[0][0].title
            elif len(pages) > 1:
                title = f"{cat.title} ({i + 1} of {len(pages)})"
            number = numbers.setdefault(prefix, settings.first)
            numbers[prefix] += 1
            sheet = Sheet(
                f"{prefix}{number}",
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
                standard=standard,
            )
            sheet.category = cat.title  # type: ignore[attr-defined]
            sheet.members = members_of(page, data)  # type: ignore[attr-defined]
            for spec, x, y in page:
                sheet.view(spec, x, y)
            if cat.notes:
                sheet.notes(cat.notes)
            elif cat.plan:
                sheet.notes(_plan_notes(data))
            if before_finish is not None:
                before_finish(sheet)
            sheet.finish()
            sheets.append(sheet)
    return sheets


def _prefix(prefix: str, standard: Standard | None) -> str:
    """The sheet number prefix of the office standard for SAEngine's ``prefix`` (S-, A-, P-, ...)."""
    if standard is None:
        return prefix
    for discipline, default in DEFAULT_PREFIXES.items():
        if prefix == default:
            return standard.prefixes.get(discipline, prefix)
    return prefix


def members_of(page: Sequence[tuple[ViewSpec, float, float]], data: DrawingSet) -> list[str]:
    """The building model's elements a sheet details (beam elevations, column schedule,
    footing, wall and stair details, by their views' keys), for flagging the sheets of members
    that fail their design checks. Plans and schedules of the whole building name none."""
    by_kind: dict[str, dict[str, list[str]]] = {
        "beam": {b.mark: b.members for b in data.beams},
        "footing": {f.mark: f.members for f in data.footings},
        "wall": {w.mark: w.members for w in data.walls},
        "stair": {st.mark: st.members for st in data.stairs},
    }
    found: set[str] = set()
    for spec, _, _ in page:
        kind, _, mark = str(spec.key or "").partition(":")
        if kind == "columns":
            for line in data.columns:
                found.update(line.members)
        elif kind in by_kind:
            found.update(by_kind[kind].get(mark, []))
    return sorted(found)


def _steel_categories(
    data: DrawingSet, settings: DrawingSettings, area, problems: list[str]
) -> list[_Category]:
    """The structural steel sheets, after the concrete ones (none without steel members):
    notes and quantities, framing plans, elevations of the braced bays, the member schedule,
    the connection details."""
    steel = data.steel
    if not steel.members:
        return []
    b = data.building
    height = area[3] - area[1]
    width = area[2] - area[0]
    out: list[_Category] = []
    specs = [schedules.notes_spec(st.steel_notes(steel), title="Steel general notes")]
    for table in (st.quantities_table(steel), st.bolt_table(steel)):
        if table.rows:
            specs += schedules.table_specs(
                table, height, key=f"steel-table:{table.title}", max_width=width
            )
    out.append(_Category("Steel general notes", 1, specs, scale_text="NTS", notes=[]))
    by_scale: dict[float, list[ViewSpec]] = {}
    for lv in sorted(b.levels, key=lambda lv: lv.elevation):
        if st.level_has_steel(steel, lv, b.levels):
            spec, p = _fit_plan(
                lambda s, lv=lv: st.steel_plan(b, steel, lv, s), settings.plan_scale, area
            )
            problems += p
            if spec is not None:
                by_scale.setdefault(spec.scale, []).append(spec)
    for scale, specs in by_scale.items():
        out.append(_Category("Steel framing plans", scale, specs, plan=True, notes=st.PLAN_NOTES))
    by_scale = {}
    for line in st.elevation_lines(b, steel):
        spec, p = _fit_plan(
            lambda s, line=line: st.steel_elevation(b, steel, line, s),
            settings.elevation_scale,
            area,
        )
        problems += p
        by_scale.setdefault(spec.scale, []).append(spec)
    for scale, specs in by_scale.items():
        out.append(_Category("Steel elevations", scale, specs, notes=st.ELEVATION_NOTES))
    specs = schedules.table_specs(
        st.member_schedule(steel, b.levels), height, key="steel-members", max_width=width
    )
    out.append(_Category("Steel member schedule", 1, specs, scale_text="NTS", notes=[]))
    specs = [st.connection_detail(c, max_size=(width, height)) for c in steel.connections]
    if specs:
        out.append(
            _Category(
                "Steel connection details",
                st.CONNECTION_SCALE,
                specs,
                scale_text=f"1:{st.CONNECTION_SCALE:g}",
                notes=st.CONNECTION_NOTES,
            )
        )
    return out


def _architecture_categories(
    data: DrawingSet, settings: DrawingSettings, area, problems: list[str]
) -> list[_Category]:
    """The architectural sheets (numbered A-101 on), after the structural ones: the plans of the
    stories, the elevations and sections (at the plan scale), the door and window schedule and
    the room finish schedule. None without architectural walls."""
    arch = data.architecture
    if arch is None or not arch.walls:
        return []
    b = data.building
    height = area[3] - area[1]
    width = area[2] - area[0]
    out: list[_Category] = []
    cuts = ar.section_lines(arch, b)
    by_scale: dict[float, list[ViewSpec]] = {}
    problems += ar.unenclosed_rooms(arch, b)
    for lv in ar.plan_levels(arch, b):
        spec, p = _fit_plan(
            lambda s, lv=lv: ar.floor_plan(b, arch, lv, s, cuts), settings.plan_scale, area
        )
        problems += p
        by_scale.setdefault(spec.scale, []).append(spec)
    for scale, specs in by_scale.items():
        out.append(
            _Category(
                "Architectural plans", scale, specs, plan=True, notes=ar.PLAN_NOTES,
                prefix=ar.PREFIX,
            )
        )  # fmt: skip
    for title, views, notes in (
        (
            "Elevations",
            [lambda s, side=side: ar.elevation(b, arch, side, s) for side, _ in ar.SIDES],
            ar.ELEVATION_NOTES,
        ),
        (
            "Sections",
            [lambda s, cut=cut: ar.section(b, arch, cut, s) for cut in cuts],
            ar.SECTION_NOTES,
        ),
    ):
        by_scale = {}
        for make in views:
            spec, p = _fit_plan(make, settings.plan_scale, area)
            problems += p
            by_scale.setdefault(spec.scale, []).append(spec)
        for scale, specs in by_scale.items():
            out.append(_Category(title, scale, specs, notes=notes, prefix=ar.PREFIX))
    for title, tables in (
        ("Door and window schedule", ar.door_window_tables(arch, b)),
        ("Room finish schedule", ar.room_tables(arch, b)),
    ):
        specs = []
        for table in tables:
            specs += schedules.table_specs(
                table, height, key=f"arch-table:{table.title}", max_width=width
            )
        if specs:
            out.append(_Category(title, 1, specs, scale_text="NTS", notes=[], prefix=ar.PREFIX))
    return out


def _mep_categories(
    data: DrawingSet, settings: DrawingSettings, area, problems: list[str]
) -> list[_Category]:
    """The MEP sheets (:mod:`.mep`), after the architectural ones: per discipline the plans of
    the stories that have its services (plumbing and drainage P-, HVAC M-, electrical E-, fire
    protection FP-), the coordination plans (MC-) and the MEP schedules. None without 07 MEP."""
    drawing = data.mep
    if drawing is None:
        return []
    b = data.building
    items = mp.items_by_level(drawing, b)
    if not items:
        return []
    arch = data.architecture
    out: list[_Category] = []
    for discipline, title, prefix in mp.DISCIPLINES:
        by_scale: dict[float, list[ViewSpec]] = {}
        for lv in sorted(b.levels, key=lambda lv: lv.elevation):
            on_level = items.get(lv.id, [])
            if not mp.has_plan(on_level, discipline):
                continue
            spec, p = _fit_plan(
                lambda s, lv=lv, on_level=on_level, discipline=discipline, title=title: mp.mep_plan(
                    b, on_level, lv, discipline, title.removesuffix("s"), s, arch
                ),
                settings.plan_scale,
                area,
            )
            problems += p
            if spec is not None:
                by_scale.setdefault(spec.scale, []).append(spec)
        for scale, specs in by_scale.items():
            out.append(
                _Category(title, scale, specs, plan=True, notes=mp.PLAN_NOTES[discipline],
                          prefix=prefix)
            )  # fmt: skip
    height = area[3] - area[1]
    width = area[2] - area[0]
    specs = []
    for table in mp.schedule_tables(drawing, b):
        specs += schedules.table_specs(
            table, height, key=f"mep-table:{table.title}", max_width=width
        )
    if specs:
        out.append(
            _Category("MEP schedules", 1, specs, scale_text="NTS", notes=mp.SCHEDULE_NOTES,
                      prefix=mp.SCHEDULE_PREFIX)
        )  # fmt: skip
    return out


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
    on_sheet: Callable[[int, int], None] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Writes one DXF per sheet into ``out_dir``, the PDF of all sheets and the PNG previews
    (``out_dir/previews/<number>.png``); returns what was written (see the module notes).

    ``clean``: the sheet files of an earlier run that this run does not write again (sheets
    renumbered or renamed, a smaller set) are removed. Only files this module wrote are
    touched: those listed in ``out_dir/MANIFEST`` (written each run), or, when there is no
    manifest, DXFs and previews named like sheets (``<prefix><number> <title>.dxf``,
    ``previews/<prefix><number>.png``). Pass ``clean=False`` when writing some sheets only
    (their files are added to the manifest). ``on_sheet(n, count)`` is called as sheet ``n``
    of ``count`` is written (the progress of a long set), ``on_step(message)`` as each stage of
    the PDF and the previews starts (see :func:`~saengine.drawings.sheets.render.render`)."""
    from saengine.drawings.sheets.render import render

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    earlier = _earlier_files(out, sheets)
    rows = []
    for i, sheet in enumerate(sheets):
        if on_sheet is not None:
            on_sheet(i + 1, len(sheets))
        target = out / f"{sheet_file_name(sheet)}.dxf"
        standard = getattr(sheet, "standard", None)
        if standard is not None:
            standard.apply(sheet.doc)  # the office's layer names, last (see .standards)
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
                "members": list(getattr(sheet, "members", []) or []),
            }
        )
    rendered = render(
        list(sheets),
        out / pdf_name if pdf else None,
        out / "previews" if png else None,
        ppi=ppi,
        on_step=on_step,
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
