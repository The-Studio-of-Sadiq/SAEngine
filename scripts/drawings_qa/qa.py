"""QA of SAEngine's drawing sheets: opens every DXF of a drawing set with ezdxf (audit, layers,
styles, linetypes, text heights, extents against the sheet), with AutoCAD's accoreconsole (AUDIT,
missing fonts and linetypes, ZOOM E, a PDF plot at the sheet's size and scale, SAVEAS DWG 2018)
and with LibreCAD's headless dxf2pdf, and writes a report (report.json and report.md).

Usage (from the repository root, the SAEngine Python environment)::

    python scripts/drawings_qa/qa.py "<project>/11 Exports/Drawings" --out <scratch folder>

AutoCAD is used only through accoreconsole.exe and a script (sheet.scr.in), headless; without
AutoCAD (CI) that part is skipped with a message. The plots and DWGs it writes are for looking
at; keep them out of the repository. See docs/drawings-qa.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "sheet.scr.in"

PAPER = {"A1": (841.0, 594.0), "A2": (594.0, 420.0), "A3": (420.0, 297.0)}
PDF_PAPER = {
    "A1": "ISO full bleed A1 (841.00 x 594.00 MM)",
    "A2": "ISO full bleed A2 (594.00 x 420.00 MM)",
    "A3": "ISO full bleed A3 (420.00 x 297.00 MM)",
}
PLOT_TEXT_HEIGHTS = (1.8, 2.0, 2.5, 3.5, 5.0, 7.0, 10.0)  # paper mm, ISO 3098 series and 1.8


def find_accoreconsole() -> Path | None:
    """accoreconsole.exe of the newest AutoCAD in Program Files (or ``SAE_ACCORECONSOLE``)."""
    env = os.environ.get("SAE_ACCORECONSOLE")
    if env:
        return Path(env) if Path(env).is_file() else None
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Autodesk"
    found = sorted(root.glob("AutoCAD 20*/accoreconsole.exe"), reverse=True)
    return found[0] if found else None


def find_librecad() -> Path | None:
    env = os.environ.get("SAE_LIBRECAD")
    if env:
        return Path(env) if Path(env).is_file() else None
    for candidate in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LibreCAD" / "LibreCAD.exe",
        Path(shutil.which("librecad") or ""),
    ):
        if candidate.name and candidate.is_file():
            return candidate
    return None


# ─────────────────────────────────── ezdxf ───────────────────────────────────


def sheet_geometry(doc: Any) -> dict[str, Any]:
    """The sheet's size and base scale from its outer frame (layer S-SHEET, the largest
    rectangle)."""
    from ezdxf import bbox

    frame = bbox.extents(doc.modelspace().query("LWPOLYLINE[layer=='S-SHEET']"))
    if not frame.has_data:
        return {}
    w, h = frame.size.x, frame.size.y
    for size, (pw, ph) in PAPER.items():
        scale = w / pw
        if abs(h / ph - scale) < 1e-3 * scale and abs(scale - round(scale)) < 1e-3:
            return {"size": size, "scale": round(scale), "width": w, "height": h}
    return {"size": None, "scale": None, "width": w, "height": h}


def ezdxf_check(path: Path) -> dict[str, Any]:
    import ezdxf
    from ezdxf import bbox

    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    msp = doc.modelspace()
    geometry = sheet_geometry(doc)
    scale = geometry.get("scale") or 1
    counts = Counter(e.dxftype() for e in msp)
    layers_used = Counter(e.dxf.layer for e in msp)
    undefined_layers = sorted(n for n in layers_used if n not in doc.layers)
    linetypes = {lt.dxf.name.upper() for lt in doc.linetypes}
    used_lt = {layer.dxf.linetype.upper() for layer in doc.layers} | {
        e.dxf.linetype.upper() for e in msp if e.dxf.hasattr("linetype")
    }
    missing_lt = sorted(
        lt for lt in used_lt if lt not in linetypes and lt not in ("BYLAYER", "BYBLOCK")
    )
    styles = {s.dxf.name: s.dxf.font for s in doc.styles}
    heights = Counter()
    for e in msp.query("TEXT MTEXT"):
        heights[round(e.dxf.char_height if e.dxftype() == "MTEXT" else e.dxf.height, 3)] += 1
    paper_heights = Counter({round(h / scale, 2): n for h, n in heights.items()})
    # plot heights only on a sheet; a real-size plan (a floor plan export) has none
    odd_heights = (
        sorted(h for h in paper_heights if h not in PLOT_TEXT_HEIGHTS)
        if geometry.get("scale")
        else []
    )
    ext = bbox.extents(msp, fast=True)
    out_of_sheet: list[str] = []
    out_of_border: list[str] = []
    if geometry.get("width") and ext.has_data:
        w, h = geometry["width"], geometry["height"]
        tol = 1e-3 * w
        if (
            ext.extmin.x < -tol
            or ext.extmin.y < -tol
            or ext.extmax.x > w + tol
            or (ext.extmax.y > h + tol)
        ):
            out_of_sheet.append(f"extents {fmt(ext.extmin)} - {fmt(ext.extmax)}")
        # the border: 20 mm binding edge on the left, 10 mm elsewhere (paper mm)
        border = (20 * scale, 10 * scale, w - 10 * scale, h - 10 * scale)
        cache = bbox.Cache()
        for e in msp:
            if e.dxf.layer == "S-SHEET":
                continue  # the frame itself and its centring marks
            b = bbox.extents([e], fast=True, cache=cache)
            if not b.has_data:
                continue
            if (
                b.extmin.x < border[0] - tol
                or b.extmin.y < border[1] - tol
                or b.extmax.x > border[2] + tol
                or b.extmax.y > border[3] + tol
            ):
                out_of_border.append(f"{e.dxftype()} on {e.dxf.layer} {fmt(b.extmin)}")
    return {
        "audit_errors": [str(err.message) for err in auditor.errors],
        "audit_fixes": [str(fix.message) for fix in auditor.fixes],
        "dxfversion": doc.dxfversion,
        "insunits": doc.header.get("$INSUNITS"),
        "sheet": geometry,
        "entities": dict(sorted(counts.items())),
        "entity_total": sum(counts.values()),
        "layers": {
            layer.dxf.name: {
                "color": layer.color,
                "linetype": layer.dxf.linetype,
                "lineweight": layer.dxf.lineweight,
                "used": layers_used.get(layer.dxf.name, 0),
            }
            for layer in doc.layers
        },
        "undefined_layers": undefined_layers,
        "missing_linetypes": missing_lt,
        "styles": styles,
        "text_heights_paper": {str(k): v for k, v in sorted(paper_heights.items())},
        "odd_text_heights": odd_heights,
        "out_of_sheet": out_of_sheet,
        "out_of_border": out_of_border[:20],
        "out_of_border_count": len(out_of_border),
        "extents": [list(ext.extmin)[:2], list(ext.extmax)[:2]] if ext.has_data else None,
    }


def fmt(v: Any) -> str:
    return f"({v.x:.0f}, {v.y:.0f})"


# ─────────────────────────────────── AutoCAD ───────────────────────────────────


def run_console(exe: Path, args: list[str], cwd: Path, timeout: float) -> tuple[int | None, str]:
    """Runs ``exe`` with ``args`` in a console of its own, hidden (accoreconsole needs a console
    for its script; it shows no window). Returns the exit code (None: timed out) and the
    output."""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs = {"startupinfo": si, "creationflags": subprocess.CREATE_NEW_CONSOLE}
    proc = subprocess.Popen(
        [str(exe), *args],
        cwd=cwd,
        stdin=subprocess.PIPE,  # kept open: an end of input makes accoreconsole wait for ever
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
    try:
        raw, _ = proc.communicate(timeout=timeout)
        code: int | None = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        raw, _ = proc.communicate()
        code = None
    text = (
        raw.decode("utf-16-le", "replace") if raw[1:2] == b"\0" else raw.decode("utf-8", "replace")
    )
    return code, text.replace("\0", "").replace("\r", "")


def acad_check(
    exe: Path, dxf: Path, sheet: dict[str, Any], out: Path, timeout: float
) -> dict[str, Any]:
    stem = dxf.stem.split(" ")[0]  # S-105
    pdf, dwg, scr, log = (out / f"{stem}{ext}" for ext in (".pdf", ".dwg", ".scr", ".acad.log"))
    layout_pdf = out / f"{stem}.layout.pdf"
    for f in (pdf, dwg, layout_pdf):
        f.unlink(missing_ok=True)
    is_sheet = bool(sheet.get("size") and sheet.get("scale"))
    size, scale = sheet.get("size") or "A1", sheet.get("scale") or 1
    pw, ph = PAPER[size]
    if is_sheet:  # the sheet's frame at its scale, then its layout by its own page setup
        plot_area, layout_plot = f"W\n0,0\n{pw * scale:g},{ph * scale:g}\n1:{scale:g}", LAYOUT_PLOT
    else:  # a DXF that is no sheet (a floor plan export): its extents fitted to A1
        plot_area, layout_plot = "E\nF", ""
    script = TEMPLATE.read_text(encoding="utf-8")
    for key, value in {
        "{plot_area}": plot_area,
        "{layout_plot}": layout_plot,
        "{pc3}": "DWG To PDF.pc3",
        "{paper}": PDF_PAPER[size],
        "{pdf}": str(pdf),
        "{dwg}": str(dwg),
        "{layout}": stem,  # the sheet's paper space layout, named after its number
        "{layout_pdf}": str(layout_pdf),
    }.items():
        script = script.replace(key, value)
    scr.write_text(script, encoding="utf-8")
    code, text = run_console(exe, ["/i", str(dxf), "/s", str(scr), "/l", "en-US"], out, timeout)
    log.write_text(text, encoding="utf-8")
    result = parse_acad_log(text, code, pdf, dwg)
    result["layout_plot_ok"] = (
        (layout_pdf.is_file() and layout_pdf.stat().st_size > 0) if is_sheet else None
    )
    result["layout_pdf"] = str(layout_pdf) if layout_pdf.is_file() else None
    layout = _between(text.split("\n"), "SAE-LAYOUT-BEGIN", "SAE-LAYOUT-END")
    result["layout_messages"] = [ln.strip() for ln in layout if ln.strip()][-12:]
    return result


LAYOUT_PLOT = """(princ "\\nSAE-LAYOUT-BEGIN\\n")
-PLOT
N
{layout}

DWG To PDF.pc3
"{layout_pdf}"
N
Y
(princ "\\nSAE-LAYOUT-END\\n")
"""
"""Plots a sheet's paper space layout by its own page setup (only the sheets have one)."""

AUDIT_TOTAL = re.compile(r"Total errors found\s+(\d+)\s+fixed\s+(\d+)", re.IGNORECASE)
SUBSTITUTE = re.compile(r"Substituting \[(.+?)\] for \[(.+?)\]", re.IGNORECASE)
MISSING = re.compile(
    r"(can(?:no|')t find|cannot find|could not find|unable to (?:load|find|open)|not found"
    r"|missing|invalid|unknown|error)",
    re.IGNORECASE,
)


def parse_acad_log(text: str, code: int | None, pdf: Path, dwg: Path) -> dict[str, Any]:
    lines = text.split("\n")
    styles, layers, ltypes, xrefs = [], [], [], []
    entities = None
    extents = None
    for line in lines:
        if line.startswith("SAE-STYLE|"):
            _, name, font, state = line.split("|")[:4]
            styles.append({"name": name, "font": font, "state": state.strip()})
        elif line.startswith("SAE-LAYER|"):
            layers.append(line.split("|")[1:])
        elif line.startswith("SAE-LTYPE|"):
            ltypes.append(line.split("|")[1].strip())
        elif line.startswith("SAE-XREF|"):
            xrefs.append(line.split("|")[1].strip())
        elif line.startswith("SAE-ENTITIES|"):
            entities = int(line.split("|")[1])
        elif line.startswith("SAE-EXTENTS|"):
            extents = [float(v) for v in line.split("|")[1:5]]
    audit = _between(lines, "SAE-AUDIT-BEGIN", "SAE-AUDIT-END")
    totals = AUDIT_TOTAL.findall("\n".join(audit))
    errors_found = sum(int(a) for a, _ in totals)
    opening = _before(lines, "SAE-QA-BEGIN")
    plot = _between(lines, "SAE-PLOT-BEGIN", "SAE-PLOT-END")
    save = _between(lines, "SAE-SAVE-BEGIN", "SAE-SAVE-END")
    substituted = sorted({f"{b} -> {a}" for a, b in SUBSTITUTE.findall(text)})
    noise = ("SAE-", "(princ", "(progn", "Command:", "Regenerating", "_>", "Fix any errors")
    warnings = sorted(
        {
            ln.strip()
            for ln in lines
            if MISSING.search(ln)
            and not ln.lstrip().startswith(noise)
            and "Total errors found" not in ln
            and "errors found" not in ln.lower()
        }
    )
    return {
        "ran": True,
        "exit_code": code,
        "timed_out": code is None,
        "opened": "SAE-QA-BEGIN" in text,
        "finished": "SAE-QA-END" in text,
        "open_messages": [ln for ln in opening if ln.strip()][-15:],
        "audit_errors_found": errors_found,
        "audit_lines": [
            ln.strip()
            for ln in audit
            if ln.strip() and not ln.strip().startswith(("Command:", "(princ", "Fix any"))
        ],
        "styles": styles,
        "missing_fonts": [s["font"] for s in styles if s["state"] == "missing"],
        "substituted_fonts": substituted,
        "linetypes": ltypes,
        "layers": len(layers),
        "xrefs": xrefs,
        "entities": entities,
        "extents": extents,
        "warnings": warnings[:40],
        "plot_ok": pdf.is_file() and pdf.stat().st_size > 0,
        "plot_messages": [ln.strip() for ln in plot if "plot" in ln.lower() and ln.strip()][-5:],
        "dwg_ok": dwg.is_file() and dwg.stat().st_size > 0,
        "save_messages": [ln.strip() for ln in save if ln.strip()][-4:],
        "pdf": str(pdf) if pdf.is_file() else None,
        "dwg": str(dwg) if dwg.is_file() else None,
    }


def _between(lines: list[str], begin: str, end: str) -> list[str]:
    out, on = [], False
    for ln in lines:
        if begin in ln and not ln.lstrip().startswith(("Command:", "(princ")):
            on = True
            continue
        if end in ln and not ln.lstrip().startswith(("Command:", "(princ")):
            on = False
        if on:
            out.append(ln)
    return out


def _before(lines: list[str], marker: str) -> list[str]:
    for i, ln in enumerate(lines):
        if marker in ln and not ln.lstrip().startswith(("Command:", "(princ")):
            return lines[:i]
    return lines


# ─────────────────────────────────── LibreCAD ───────────────────────────────────


def librecad_check(exe: Path, dxf: Path, sheet: dict[str, Any], out: Path, timeout: float):
    stem = dxf.stem.split(" ")[0]
    pdf = out / f"{stem}.librecad.pdf"
    pdf.unlink(missing_ok=True)
    size = sheet.get("size") or "A1"
    pw, ph = PAPER[size]
    args = ["dxf2pdf", "-a", "-k", "-p", f"{pw:g}x{ph:g}", "-o", str(pdf), str(dxf)]
    code, text = run_console(exe, args, out, timeout)
    (out / f"{stem}.librecad.log").write_text(text, encoding="utf-8")
    return {
        "ran": True,
        "exit_code": code,
        "timed_out": code is None,
        "pdf": str(pdf) if pdf.is_file() else None,
        "messages": [ln.strip() for ln in text.split("\n") if ln.strip()][-10:],
    }


# ─────────────────────────────────── report ───────────────────────────────────


def render_png(pdf: Path, png: Path, dpi: int = 50) -> bool:
    try:
        import pymupdf
    except ImportError:
        return False
    with pymupdf.open(pdf) as doc:
        if not doc.page_count:
            return False
        doc[0].get_pixmap(dpi=dpi).save(png)
    return True


def markdown(report: dict[str, Any]) -> str:
    out = ["# Drawing sheets QA", ""]
    out.append(f"Drawings: `{report['drawings']}`  ")
    out.append(f"AutoCAD: {report['autocad'] or 'not found (skipped)'}  ")
    out.append(f"LibreCAD: {report['librecad'] or 'not found (skipped)'}")
    out.append("")
    out.append(
        "| Sheet | Size 1:N | Entities | ezdxf audit | Odd text heights | Outside border "
        "| AutoCAD AUDIT | Missing fonts | Font subst. | Warnings | PDF | Layout PDF | DWG "
        "| LibreCAD |"
    )
    out.append("|" + "---|" * 14)
    for s in report["sheets"]:
        e, a, lc = s["ezdxf"], s.get("autocad") or {}, s.get("librecad") or {}
        sheet = e.get("sheet", {})
        out.append(
            "| {name} | {size} 1:{scale} | {ent} | {ea} | {odd} | {ob} | {aa} | {mf} | {sf} | {w} "
            "| {pdf} | {lpdf} | {dwg} | {lc} |".format(
                name=s["name"],
                size=sheet.get("size"),
                scale=sheet.get("scale"),
                ent=e["entity_total"],
                ea=f"{len(e['audit_errors'])} err / {len(e['audit_fixes'])} fix",
                odd=", ".join(f"{h:g}" for h in e["odd_text_heights"]) or "-",
                ob=e["out_of_border_count"],
                aa=a.get("audit_errors_found", "-") if a else "skipped",
                mf=len(a.get("missing_fonts", [])) if a else "-",
                sf=len(a.get("substituted_fonts", [])) if a else "-",
                w=len(a.get("warnings", [])) if a else "-",
                pdf="ok" if a.get("plot_ok") else ("FAIL" if a else "-"),
                lpdf={True: "ok", False: "FAIL"}.get(a.get("layout_plot_ok"), "-"),
                dwg="ok" if a.get("dwg_ok") else ("FAIL" if a else "-"),
                lc="ok" if lc.get("pdf") else ("FAIL" if lc else "-"),
            )
        )
    out.append("")
    for s in report["sheets"]:
        e, a = s["ezdxf"], s.get("autocad") or {}
        details = []
        details += [f"- ezdxf audit: {m}" for m in e["audit_errors"] + e["audit_fixes"]]
        details += [f"- undefined layer: {n}" for n in e["undefined_layers"]]
        details += [f"- missing linetype: {n}" for n in e["missing_linetypes"]]
        details += [f"- outside the border: {n}" for n in e["out_of_border"]]
        details += [f"- outside the sheet: {n}" for n in e["out_of_sheet"]]
        details += [
            f"- AutoCAD AUDIT: {m}"
            for m in a.get("audit_lines", [])
            if a.get("audit_errors_found") or "Total errors" in m
        ]
        details += [f"- AutoCAD missing font: {m}" for m in a.get("missing_fonts", [])]
        details += [f"- AutoCAD substituted font: {m}" for m in a.get("substituted_fonts", [])]
        details += [f"- AutoCAD: {m}" for m in a.get("warnings", [])]
        if a and a.get("layout_plot_ok") is False:
            details += [f"- layout plot: {m}" for m in a.get("layout_messages", [])]
        if details:
            out += [f"## {s['name']}", "", *details, ""]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("drawings", type=Path, help="folder of the sheet DXFs")
    parser.add_argument("--out", type=Path, required=True, help="scratch folder for the output")
    parser.add_argument("--skip-autocad", action="store_true")
    parser.add_argument("--skip-librecad", action="store_true")
    parser.add_argument("--only", help="sheet numbers, by commas (S-105,S-106)")
    parser.add_argument("--timeout", type=float, default=600.0, help="per sheet and program [s]")
    parser.add_argument("--png", action="store_true", help="PNGs of the AutoCAD plots (pymupdf)")
    args = parser.parse_args(argv)

    dxfs = sorted(args.drawings.glob("*.dxf"))
    if args.only:
        wanted = {s.strip().upper() for s in args.only.split(",")}
        dxfs = [d for d in dxfs if d.stem.split(" ")[0].upper() in wanted]
    if not dxfs:
        print(f"no DXF in {args.drawings}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    acad = None if args.skip_autocad else find_accoreconsole()
    librecad = None if args.skip_librecad else find_librecad()
    if acad is None and not args.skip_autocad:
        print("AutoCAD (accoreconsole.exe) not found: the AutoCAD checks are skipped.")
    if librecad is None and not args.skip_librecad:
        print("LibreCAD not found: the LibreCAD checks are skipped.")

    report: dict[str, Any] = {
        "drawings": str(args.drawings),
        "autocad": str(acad) if acad else None,
        "librecad": str(librecad) if librecad else None,
        "sheets": [],
    }
    for dxf in dxfs:
        print(f"{dxf.name}: ezdxf", flush=True)
        entry: dict[str, Any] = {"name": dxf.stem, "file": str(dxf), "ezdxf": ezdxf_check(dxf)}
        sheet = entry["ezdxf"]["sheet"]
        if acad:
            print(f"{dxf.name}: AutoCAD", flush=True)
            entry["autocad"] = acad_check(acad, dxf, sheet, args.out, args.timeout)
            pdf = entry["autocad"].get("pdf")
            if args.png and pdf:
                png = args.out / f"{dxf.stem.split(' ')[0]}.acad.png"
                entry["autocad"]["png"] = str(png) if render_png(Path(pdf), png) else None
        if librecad:
            print(f"{dxf.name}: LibreCAD", flush=True)
            entry["librecad"] = librecad_check(librecad, dxf, sheet, args.out, args.timeout)
        report["sheets"].append(entry)

    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.out / "report.md").write_text(markdown(report), encoding="utf-8")
    print(f"Wrote {args.out / 'report.md'}")
    bad = [
        s["name"]
        for s in report["sheets"]
        if s["ezdxf"]["audit_errors"]
        or (s.get("autocad") or {}).get("audit_errors_found")
        or (s.get("autocad") and not s["autocad"].get("plot_ok"))
    ]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
