"""Soil Report deliverables, review aids, figure data and revision records."""

from __future__ import annotations

import difflib
import html
import json
import zipfile
from pathlib import Path
from typing import Any

from saengine.features import checkbox, number, result, table, text
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    layer_rows,
    profile,
    register_tab,
    require_report,
    result_rows,
    save_json,
    save_text,
    spt_rows,
)


def _fields(fid: str) -> list[Any]:
    if fid == "soilReport.reviewSignOff":
        return [
            text("reviewer", "Reviewer", ""),
            text("reviewDate", "Review date", ""),
            checkbox("approved", "Ready for issue", False),
            text("comments", "Review comments", ""),
        ]
    if fid == "soilReport.issueTransmittal":
        return [
            text("recipient", "Recipient", ""),
            text("issuer", "Issuer", ""),
            text("revision", "Revision", "A"),
            text("issueDate", "Issue date", ""),
        ]
    if fid == "soilReport.revisionCompare":
        return [text("previousReportPath", "Project-relative previous Soil Report JSON", "")]
    if fid == "soilReport.contourFigure":
        return [*common_fields(fid), number("layerIndex", "Layer number", 1.0, min=1)]
    if fid == "soilReport.archiveSnapshot":
        return [text("archiveName", "Archive file name", "soil-report-archive.zip")]
    return common_fields(fid)


def _read_text(ctx: Any, relative: str) -> str | None:
    path = ctx.path(relative)
    return path.read_text(encoding="utf-8") if path and path.is_file() else None


def _report_output(ctx: Any, report: Any) -> dict[str, Any]:
    from saengine.report.clauses import in_force
    from saengine.soil.report import soil_report

    with in_force(ctx.root):
        return soil_report(
            _read_text(ctx, "01 Soil Report/soil-report.json") or "",
            _read_text(ctx, "02 Project Settings/project-settings.json"),
        )


def _pdf(lines: list[str]) -> bytes:
    pages = [lines[i : i + 48] for i in range(0, max(1, len(lines)), 48)]
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(pages))]
    content_ids = [5 + 2 * i for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{i} 0 R" for i in page_ids)
            + f"] /Count {len(pages)} >>"
        ).encode()
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, stream_id, page in zip(page_ids, content_ids, pages, strict=True):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode()
        )
        commands = ["BT", "/F1 9 Tf", "42 756 Td", "12 TL"]
        for line in page:
            plain = (
                line.encode("ascii", "replace")
                .decode("ascii")[:110]
                .replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )
            commands.append(f"({plain}) Tj T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def _docx(lines: list[str]) -> bytes:
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{html.escape(line)}</w:t></w:r></w:p>'
        for line in lines
    )
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}<w:sectPr/></w:body></w:document>'
    content_types = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _lines(report: Any) -> list[str]:
    lines = [
        report.report.title or "Soil Investigation Report",
        "",
        f"Boreholes: {len(report.boreholes)}",
        f"SPT records: {sum(len(bh.spt) for bh in report.boreholes)}",
        f"Samples: {sum(len(bh.samples) for bh in report.boreholes)}",
        "",
        "Borehole summary",
    ]
    for bh in report.boreholes:
        lines.extend(
            [
                f"{bh.id}: ground level {report.ground_level(bh) / 1000:g} m, depth {bh.bottom / 1000:g} m, water table {bh.waterTable / 1000 if bh.waterTable is not None else 'not recorded'} m",
                f"  Layers: {len(bh.layers)}, SPT: {len(bh.spt)}, samples: {len(bh.samples)}",
            ]
        )
        for i, layer in enumerate(bh.layers, 1):
            lines.append(
                f"  {i}. {layer.top / 1000:.2f}-{layer.bottom / 1000:.2f} m: {layer.soilType} {layer.uscs or ''} {layer.description}"
            )
    lines.extend(
        [
            "",
            "This report is an output of the saved Soil Report data. Review interpretations and adopted design values before issue.",
        ]
    )
    return lines


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    report = require_report(ctx)
    if fid == "soilReport.reportTemplates":
        rows = [
            {"template": name, "format": fmt, "sections": sections}
            for name, fmt, sections in (
                (
                    "Geotechnical factual report",
                    "Markdown / HTML / PDF / Word",
                    "site, investigation, boreholes, laboratory tests, design recommendations",
                ),
                (
                    "Borehole log pack",
                    "Markdown / PDF",
                    "location, strata, SPT and sample register",
                ),
                (
                    "Design parameter schedule",
                    "CSV / JSON",
                    "adopted properties, source and depth range",
                ),
            )
        ]
        return result_rows(
            "Available report layouts",
            [("template", "Template"), ("format", "Output formats"), ("sections", "Sections")],
            rows,
            summary={"templatesCount": len(rows)},
            notes=[
                "Layouts are deterministic renderings of the saved Soil Report; project branding and signature blocks can be added in the report editor."
            ],
        )
    if fid == "soilReport.consistencyCheck":
        from saengine.library.soil import check

        problems = check(report)
        rows = [
            {"check": i + 1, "severity": "review", "message": message}
            for i, message in enumerate(problems)
        ]
        return result(
            summary={
                "problemsCount": len(rows),
                "boreholesCheckedCount": len(report.boreholes),
                "consistent": not rows,
            },
            tables=[
                table(
                    "Soil Report consistency checks",
                    [("check", "Check"), ("severity", "Severity"), ("message", "Finding")],
                    rows,
                )
            ],
            notes=[
                "Checks boreholes, logged strata, SPT issues, sample consistency and coordinate inputs from the Soil Report model."
            ],
        )
    if fid == "soilReport.compileSoilReport":
        data = _report_output(ctx, report)
        path = save_json(ctx, "01 Soil Report/exports/compiled-soil-report.json", data)
        lines = _lines(report)
        md_path = save_text(
            ctx, "01 Soil Report/exports/compiled-soil-report.md", "\n".join(lines) + "\n"
        )
        return result(
            summary={
                "exportPath": path,
                "markdownPath": md_path,
                "boreholesCount": len(report.boreholes),
                "reportSectionsCount": len(data),
            },
            notes=[
                f"Compiled report JSON written to {path}.",
                f"Readable report written to {md_path}.",
            ],
        )
    if fid == "soilReport.executiveSummary":
        if not report.boreholes:
            raise FeatureInputError("Add borehole data before compiling an executive summary.")
        ground = [report.ground_level(bh) / 1000 for bh in report.boreholes]
        depths = [bh.bottom / 1000 for bh in report.boreholes]
        waters = [bh.waterTable / 1000 for bh in report.boreholes if bh.waterTable is not None]
        type_counts: dict[str, int] = {}
        for bh in report.boreholes:
            for layer in bh.layers:
                type_counts[layer.soilType] = type_counts.get(layer.soilType, 0) + 1
        rows = [
            {"soilType": kind, "loggedIntervals": count}
            for kind, count in sorted(type_counts.items())
        ]
        return result(
            summary={
                "title": report.report.title,
                "boreholesCount": len(report.boreholes),
                "depthRangeM": [min(depths), max(depths)],
                "waterTableDepthRangeM": [min(waters), max(waters)] if waters else None,
                "samplesCount": sum(len(bh.samples) for bh in report.boreholes),
                "sptTestsCount": sum(len(bh.spt) for bh in report.boreholes),
                "groundLevelRangeM": [min(ground), max(ground)],
            },
            tables=[
                table(
                    "Logged strata distribution",
                    [("soilType", "Soil type"), ("loggedIntervals", "Intervals")],
                    rows,
                )
            ],
            notes=[
                "Summary values describe the investigation records; they are not design conclusions."
            ],
        )
    if fid == "soilReport.recommendations":
        notes = []
        if not report.boreholes:
            raise FeatureInputError(
                "Add investigation boreholes before generating report recommendations."
            )
        if any(not bh.layers for bh in report.boreholes):
            notes.append(
                "Complete the layer descriptions in each borehole before finalizing the ground model."
            )
        if any(not bh.spt for bh in report.boreholes):
            notes.append(
                "Consider additional in-situ strength or density measurements where design parameters are currently inferred."
            )
        if any(bh.waterTable is not None for bh in report.boreholes):
            notes.append(
                "Monitor groundwater over a representative seasonal period where excavation, buoyancy or effective-stress design is sensitive to water level."
            )
        if any(
            any(
                layer.soilType in {"clay", "organic"} and (layer.Cc is None or layer.e0 is None)
                for layer in bh.layers
            )
            for bh in report.boreholes
        ):
            notes.append(
                "Obtain consolidation test data for compressible cohesive strata where settlement under sustained loading governs."
            )
        if any(any(layer.soilType == "fill" for layer in bh.layers) for bh in report.boreholes):
            notes.append(
                "Characterize fill thickness, composition and compaction before relying on it for foundation support."
            )
        if not notes:
            notes.append(
                "The saved investigation is populated; confirm adopted design properties, groundwater assumptions and serviceability criteria against the project requirements."
            )
        return result(
            summary={"recommendationsCount": len(notes)},
            tables=[
                table(
                    "Investigation and design recommendations",
                    [("item", "Recommendation")],
                    [{"item": item} for item in notes],
                )
            ],
            notes=[
                "Recommendations are deterministic prompts generated from missing or sensitive logged data and require geotechnical review."
            ],
        )
    if fid == "soilReport.designValuesTable":
        from saengine.report.clauses import in_force
        from saengine.soil import bearing as bearing_engine

        rows = []
        with in_force(ctx.root):
            for bh in report.boreholes:
                if bh.layers:
                    for row in bearing_engine.table(profile(report, bh)):
                        rows.append({"borehole": bh.id, **row})
        if not rows:
            raise FeatureInputError("Borehole layers are needed for a design bearing-value table.")
        columns = [(key, key.replace("_", " ").title()) for key in rows[0]]
        return result_rows(
            "Design bearing values",
            columns,
            rows,
            summary={"rowsCount": len(rows), "boreholesCount": len(report.boreholes)},
            notes=[
                "Values are calculated by the soil engine under the active code pack and design options."
            ],
        )
    if fid in {
        "soilReport.boreholeSheets",
        "soilReport.sectionSheets",
        "soilReport.locationPlanFigure",
        "soilReport.profileFigureSet",
        "soilReport.contourFigure",
        "soilReport.chartInserts",
        "soilReport.figureNumbering",
        "soilReport.captionStyles",
        "soilReport.drawingRegister",
        "soilReport.reportAppendices",
    }:
        if fid == "soilReport.boreholeSheets":
            rows = [
                {
                    "borehole": bh.id,
                    "groundLevelM": report.ground_level(bh) / 1000,
                    "terminationDepthM": bh.bottom / 1000,
                    "waterTableM": bh.waterTable / 1000 if bh.waterTable is not None else None,
                    "layersCount": len(bh.layers),
                    "sptTestsCount": len(bh.spt),
                    "samplesCount": len(bh.samples),
                    "drillingMethod": bh.method,
                }
                for bh in report.boreholes
            ]
            return result_rows(
                "Borehole sheet index",
                [
                    ("borehole", "Borehole"),
                    ("groundLevelM", "Ground level", "m"),
                    ("terminationDepthM", "Termination depth", "m"),
                    ("waterTableM", "Water table", "m"),
                    ("layersCount", "Layers"),
                    ("sptTestsCount", "SPT tests"),
                    ("samplesCount", "Samples"),
                    ("drillingMethod", "Method"),
                ],
                rows,
                summary={"sheetsCount": len(rows)},
                notes=[
                    "The table is the source data for borehole sheets; it does not alter the saved log."
                ],
            )
        if fid in {"soilReport.sectionSheets", "soilReport.profileFigureSet"}:
            rows = layer_rows(report)
            return result_rows(
                "Geological profile figure data",
                [
                    ("borehole", "Borehole"),
                    ("layer", "Layer"),
                    ("topM", "Top", "m"),
                    ("bottomM", "Bottom", "m"),
                    ("soilType", "Soil type"),
                    ("uscs", "USCS"),
                    ("description", "Description"),
                ],
                rows,
                summary={"layerSegmentsCount": len(rows), "boreholesCount": len(report.boreholes)},
                notes=[
                    "Logged layer intervals and descriptions are the figure data; interpolation between boreholes is not implied."
                ],
            )
        if fid == "soilReport.locationPlanFigure":
            from saengine.gis.crs import Grid

            if report.site is None or not report.site.georeferenced:
                raise FeatureInputError(
                    "Set the site latitude and longitude before producing a geographic location-plan figure."
                )
            grid = Grid(report.site)
            rows = [
                {
                    "borehole": bh.id,
                    "latitudeDeg": grid.to_wgs84(bh.x, bh.y)[0],
                    "longitudeDeg": grid.to_wgs84(bh.x, bh.y)[1],
                    "xM": bh.x / 1000,
                    "yM": bh.y / 1000,
                }
                for bh in report.boreholes
            ]
            return result_rows(
                "Location plan figure nodes",
                [
                    ("borehole", "Borehole"),
                    ("latitudeDeg", "Latitude", "°"),
                    ("longitudeDeg", "Longitude", "°"),
                    ("xM", "Project X", "m"),
                    ("yM", "Project Y", "m"),
                ],
                rows,
                summary={"boreholesCount": len(rows), "siteAddress": report.site.address},
                notes=[
                    "WGS 84 coordinates are transformed from the project grid for the location plan."
                ],
            )
        if fid == "soilReport.contourFigure":
            index = max(1, int(values.get("layerIndex", 1))) - 1
            rows = []
            for bh in report.boreholes:
                if index < len(bh.layers):
                    layer = bh.layers[index]
                    rows.append(
                        {
                            "borehole": bh.id,
                            "xM": bh.x / 1000,
                            "yM": bh.y / 1000,
                            "layer": index + 1,
                            "topElevationM": (report.ground_level(bh) - layer.top) / 1000,
                            "bottomElevationM": (report.ground_level(bh) - layer.bottom) / 1000,
                        }
                    )
            if not rows:
                raise FeatureInputError(
                    "No borehole has the requested layer number for a contour figure."
                )
            return result_rows(
                "Stratum contour figure nodes",
                [
                    ("borehole", "Borehole"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("layer", "Layer"),
                    ("topElevationM", "Top elevation", "m"),
                    ("bottomElevationM", "Bottom elevation", "m"),
                ],
                rows,
                summary={"nodesCount": len(rows)},
                notes=[
                    "Rows are observed control points for contouring; interpolation should stay within the investigation footprint."
                ],
            )
        if fid == "soilReport.chartInserts":
            rows = spt_rows(report)
            if not rows:
                raise FeatureInputError(
                    "SPT or grain-size data are needed for report chart inserts."
                )
            return result_rows(
                "SPT chart insert data",
                [
                    ("borehole", "Borehole"),
                    ("depthM", "Depth", "m"),
                    ("fieldN", "Field N"),
                    ("n60", "N60"),
                    ("n160", "(N1)60"),
                    ("effectiveStressKpa", "Effective stress", "kPa"),
                ],
                rows,
                summary={"chartPointsCount": len(rows)},
                notes=[
                    "SPT depth, corrected blow count and effective stress are available as plot data."
                ],
            )
        figures = [
            ("F-01", "Location plan", "site coordinates"),
            ("F-02", "Borehole profiles", "logged layers and SPT"),
            ("F-03", "Design value plot", "bearing pressure table"),
            ("F-04", "Stratum contour", "layer elevations"),
        ]
        if fid == "soilReport.figureNumbering":
            return result_rows(
                "Figure numbering schedule",
                [("number", "Figure"), ("caption", "Caption"), ("dataSource", "Data source")],
                [{"number": a, "caption": b, "dataSource": c} for a, b, c in figures],
                summary={"figureCount": len(figures)},
                notes=[
                    "Numbers are assigned in a stable sequence for the available Soil Report figure families."
                ],
            )
        if fid == "soilReport.captionStyles":
            return result(
                summary={"stylesCount": 3},
                tables=[
                    table(
                        "Caption style presets",
                        [("style", "Style"), ("format", "Format")],
                        [
                            {
                                "style": "Figure caption",
                                "format": "Figure n — concise description; source or date where relevant",
                            },
                            {
                                "style": "Table caption",
                                "format": "Table n — measured or computed quantity and units",
                            },
                            {"style": "Note", "format": "Method, assumptions and limitations"},
                        ],
                    )
                ],
                notes=[
                    "Captions identify the displayed quantity and unit; method assumptions stay in the note below the figure."
                ],
            )
        if fid == "soilReport.drawingRegister":
            return result_rows(
                "Soil drawing register",
                [("number", "Drawing"), ("title", "Title"), ("source", "Source data")],
                [{"number": a, "title": b, "source": c} for a, b, c in figures],
                summary={"drawingsCount": len(figures)},
                notes=[
                    "Register lists the drawing families with source data currently represented in the Soil Report model."
                ],
            )
        appendices = [
            {"appendix": "A", "title": "Borehole logs", "recordCount": len(report.boreholes)},
            {
                "appendix": "B",
                "title": "SPT records",
                "recordCount": sum(len(bh.spt) for bh in report.boreholes),
            },
            {
                "appendix": "C",
                "title": "Laboratory sample register",
                "recordCount": sum(len(bh.samples) for bh in report.boreholes),
            },
        ]
        return result_rows(
            "Report appendix index",
            [("appendix", "Appendix"), ("title", "Contents"), ("recordCount", "Records")],
            appendices,
            summary={
                "appendicesCount": len(appendices),
                "recordsCount": sum(row["recordCount"] for row in appendices),
            },
            notes=[
                "Appendix entries are generated from the saved boreholes, SPT records and samples."
            ],
        )
    if fid == "soilReport.testCertificates":
        from saengine.soil import lab

        rows = []
        for bh in report.boreholes:
            for i, sample in enumerate(bh.samples, 1):
                groups = []
                for name, present in (
                    ("UCS", sample.ucs is not None),
                    ("Direct shear", sample.directShear is not None),
                    ("Triaxial", sample.triaxial is not None),
                    ("Consolidation", sample.consolidation is not None),
                    ("Grain size", sample.grading is not None),
                    ("Permeability", sample.permeability is not None),
                    ("Chemistry", sample.chemistry is not None),
                ):
                    if present:
                        groups.append(name)
                rows.append(
                    {
                        "borehole": bh.id,
                        "sample": sample.number or f"S{i}",
                        "depthM": sample.depth / 1000,
                        "testGroups": "; ".join(groups),
                        "derivedValues": json.dumps(
                            lab.feed(sample), default=str, ensure_ascii=False
                        ),
                        "issues": "; ".join(sample.issues),
                    }
                )
        if not rows:
            raise FeatureInputError("No laboratory samples are recorded for test certificates.")
        return result_rows(
            "Laboratory test certificate index",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("testGroups", "Recorded tests"),
                ("derivedValues", "Derived values"),
                ("issues", "Issues"),
            ],
            rows,
            summary={"certificatesCount": len(rows)},
            notes=[
                "Index summarizes test groups and engine-derived values; source laboratory certificates remain the record of measured readings."
            ],
        )
    if fid in {"soilReport.exportSoilPdf", "soilReport.exportSoilWord"}:
        lines = _lines(report)
        relative = (
            "01 Soil Report/exports/soil-report.pdf"
            if fid.endswith("Pdf")
            else "01 Soil Report/exports/soil-report.docx"
        )
        path = ctx.path(relative)
        if path is None:
            raise FeatureInputError("Open a project before exporting the report.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_pdf(lines) if fid.endswith("Pdf") else _docx(lines))
        return result(
            summary={
                "exportPath": str(path.resolve()),
                "boreholesCount": len(report.boreholes),
                "format": "PDF" if fid.endswith("Pdf") else "DOCX",
            },
            notes=[
                f"Report exported to {path.resolve()}.",
                "The deliverable contains logged borehole strata and investigation counts; add project-specific interpretation and sign-off before issue.",
            ],
        )
    if fid == "soilReport.reviewSignOff":
        if not values["reviewer"].strip():
            raise FeatureInputError("Enter a reviewer name before saving the review record.")
        review = {
            "reviewer": values["reviewer"].strip(),
            "date": values["reviewDate"],
            "approved": values["approved"],
            "comments": values["comments"],
            "reportNumber": report.report.reportNumber,
            "boreholesReviewed": len(report.boreholes),
        }
        path = save_json(ctx, "01 Soil Report/exports/review-sign-off.json", review)
        return result(
            summary={
                "reviewer": review["reviewer"],
                "approved": review["approved"],
                "reviewPath": path,
            },
            tables=[
                table(
                    "Review sign-off",
                    [("item", "Item"), ("value", "Value")],
                    [{"item": k, "value": v} for k, v in review.items()],
                )
            ],
            notes=[
                f"Review record written to {path}; it records approval metadata but does not digitally sign or lock the report."
            ],
        )
    if fid == "soilReport.dataPackExport":
        path = ctx.path("01 Soil Report/exports/soil-data-pack.zip")
        if path is None:
            raise FeatureInputError("Open a project before exporting the soil data pack.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in (
                "01 Soil Report/soil-report.json",
                "02 Project Settings/project-settings.json",
            ):
                source = ctx.path(relative)
                if source and source.is_file():
                    archive.write(source, arcname=Path(relative).name)
        return result(
            summary={
                "exportPath": str(path.resolve()),
                "boreholesCount": len(report.boreholes),
                "samplesCount": sum(len(bh.samples) for bh in report.boreholes),
            },
            notes=[
                f"Soil data pack written to {path.resolve()}.",
                "The archive includes the soil report and project settings used by its design summaries.",
            ],
        )
    if fid == "soilReport.revisionCompare":
        old_path = ctx.path(values["previousReportPath"])
        if not values["previousReportPath"].strip() or old_path is None or not old_path.is_file():
            raise FeatureInputError(
                "Choose a previous report JSON file inside the project to compare revisions."
            )
        old = json.loads(old_path.read_text(encoding="utf-8"))
        new = report.model_dump(mode="json", by_alias=True)
        old_lines = json.dumps(old, ensure_ascii=False, sort_keys=True, indent=2).splitlines()
        new_lines = json.dumps(new, ensure_ascii=False, sort_keys=True, indent=2).splitlines()
        diff = list(
            difflib.unified_diff(
                old_lines, new_lines, fromfile="previous", tofile="current", lineterm=""
            )
        )
        path = save_text(ctx, "01 Soil Report/exports/revision-diff.txt", "\n".join(diff) + "\n")
        return result(
            summary={
                "changedLinesCount": sum(
                    line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
                    for line in diff
                ),
                "diffPath": path,
            },
            tables=[
                table(
                    "Revision differences",
                    [("line", "Diff")],
                    [{"line": line} for line in diff[:500]],
                )
            ],
            notes=[f"Unified JSON diff written to {path}."],
        )
    if fid == "soilReport.issueTransmittal":
        if not values["recipient"].strip() or not values["issuer"].strip():
            raise FeatureInputError("Enter both the recipient and issuer to create a transmittal.")
        payload = {
            "recipient": values["recipient"],
            "issuer": values["issuer"],
            "revision": values["revision"],
            "date": values["issueDate"],
            "reportTitle": report.report.title,
            "reportNumber": report.report.reportNumber,
            "boreholes": [bh.id for bh in report.boreholes],
            "includedFiles": [
                "soil-report.json",
                "exports/soil-report.pdf",
                "exports/soil-report.docx",
            ],
        }
        path = save_json(ctx, "01 Soil Report/exports/issue-transmittal.json", payload)
        return result(
            summary={
                "transmittalPath": path,
                "recipient": payload["recipient"],
                "revision": payload["revision"],
                "boreholesCount": len(payload["boreholes"]),
            },
            tables=[
                table(
                    "Issue transmittal",
                    [("item", "Item"), ("value", "Value")],
                    [{"item": k, "value": v} for k, v in payload.items()],
                )
            ],
            notes=[
                f"Transmittal manifest written to {path}; issue status is not sent to an external recipient."
            ],
        )
    if fid == "soilReport.archiveSnapshot":
        name = Path(values["archiveName"]).name
        if not name.lower().endswith(".zip"):
            name += ".zip"
        path = ctx.path(f"01 Soil Report/exports/{name}")
        folder = ctx.path("01 Soil Report")
        if path is None or folder is None:
            raise FeatureInputError("Open a project before creating an archive snapshot.")
        path.parent.mkdir(parents=True, exist_ok=True)
        files = [p for p in folder.rglob("*") if p.is_file() and p.resolve() != path.resolve()]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in files:
                archive.write(source, source.relative_to(folder))
        return result(
            summary={"archivePath": str(path.resolve()), "archivedFilesCount": len(files)},
            notes=[
                f"Soil Report snapshot written to {path.resolve()}.",
                "Only files inside 01 Soil Report are included; the archive excludes itself.",
            ],
        )
    raise FeatureInputError(
        "The selected report tool needs report data or one of its stated metadata inputs."
    )


register_tab("soilReport", _handle, fields=_fields)
