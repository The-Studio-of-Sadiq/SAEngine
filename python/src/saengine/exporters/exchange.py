"""The exchange exports of alpha 9 L12, one entry point: ``.s2k``, ``.std``, SAF, SDNF, CIS/2.

:func:`export_file` derives the project's analysis model (:func:`saengine.exporters.analytical.
project_model`), writes the format into ``11 Exports/<folder>/<project><ext>`` (or ``out_path``)
and its export report beside it, as the e2k export does (``<name>.export-report.json`` and
``.export-report.md``). :func:`rpc_export` is the app's ``export/exchange`` method.

Steel detailing programs: there is no proprietary link. IFC (the building model export, with the
steel members' profiles) is the route, with SDNF and CIS/2 for programs that read those.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saengine.exporters import cis2, s2k, saf, sdnf, std
from saengine.exporters.analytical import (
    AnalyticalModel,
    ExchangeExportError,
    ExchangeReport,
    project_model,
)


@dataclass(frozen=True)
class Format:
    id: str
    name: str
    extension: str
    folder: str
    #: Writes the model to the path (text formats return their text).
    write: Callable[[AnalyticalModel, Path, ExchangeReport], Path]


def _text(
    writer: Callable[..., str], newline: str = "\n"
) -> Callable[[AnalyticalModel, Path, ExchangeReport], Path]:
    def write(model: AnalyticalModel, path: Path, report: ExchangeReport) -> Path:
        text = writer(model, report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\r\n", "\n").replace("\n", newline).encode("utf-8"))
        return path

    return write


FORMATS: dict[str, Format] = {
    "s2k": Format(
        "s2k", s2k.FORMAT_NAME, s2k.EXTENSION, s2k.EXPORT_FOLDER, _text(s2k.write_s2k, "\r\n")
    ),
    "std": Format(
        "std", std.FORMAT_NAME, std.EXTENSION, std.EXPORT_FOLDER, _text(std.write_std, "\r\n")
    ),
    "saf": Format(
        "saf",
        saf.FORMAT_NAME,
        saf.EXTENSION,
        saf.EXPORT_FOLDER,
        lambda m, p, r: saf.write_saf(m, p, r),
    ),
    "sdnf": Format(
        "sdnf", sdnf.FORMAT_NAME, sdnf.EXTENSION, sdnf.EXPORT_FOLDER, _text(sdnf.write_sdnf, "\r\n")
    ),
    "cis2": Format(
        "cis2", cis2.FORMAT_NAME, cis2.EXTENSION, cis2.EXPORT_FOLDER, _text(cis2.write_cis2)
    ),
}


def export_file(
    project: str | Path, fmt: str, out_path: str | Path | None = None
) -> dict[str, Any]:
    """Exports the project as ``fmt`` (a key of :data:`FORMATS`): ``{"path", "reportPath",
    "readablePath", "report", "format"}``. Raises :class:`ExchangeExportError`."""
    spec = FORMATS.get(fmt)
    if spec is None:
        raise ExchangeExportError(f"unknown exchange format {fmt!r} (one of {', '.join(FORMATS)})")
    model, report, p = project_model(project, spec.name, spec.extension)
    stem = p.name.replace("/", "-").replace("\\", "-")
    target = (
        Path(out_path)
        if out_path
        else p.folder("exports") / spec.folder / f"{stem}{spec.extension}"
    )
    if target.is_dir():
        target = target / f"{stem}{spec.extension}"
    written = spec.write(model, target, report)
    report.source["file"] = written.name
    data = report.to_dict()
    report_path = written.with_name(f"{written.stem}.export-report.json")
    report_path.write_text(json.dumps(data, indent="\t", ensure_ascii=False) + "\n", "utf-8")
    readable = written.with_name(f"{written.stem}.export-report.md")
    readable.write_text(report.to_markdown(), "utf-8")
    return {
        "path": str(written),
        "reportPath": str(report_path),
        "readablePath": str(readable),
        "report": data,
        "format": fmt,
    }


def rpc_export(params: dict[str, Any]) -> dict[str, Any]:
    """``export/exchange`` ``{projectRoot, format, outPath?}`` -> :func:`export_file`'s answer, or
    ``{"error"}``; ``format: "webViewer"`` writes the web viewer
    (:func:`saengine.exporters.web_viewer.export_web_viewer`)."""
    fmt = str(params.get("format") or "")
    try:
        if fmt == "webViewer":
            from saengine.exporters.web_viewer import export_web_viewer

            return export_web_viewer(params["projectRoot"], params.get("outPath"))
        return export_file(params["projectRoot"], fmt, params.get("outPath"))
    except (ExchangeExportError, OSError, KeyError) as error:
        return {"error": str(error)}


__all__ = ["FORMATS", "Format", "export_file", "rpc_export"]
