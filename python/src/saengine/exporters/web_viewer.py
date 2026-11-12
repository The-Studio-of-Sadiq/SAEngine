"""The licence-free web viewer: a folder a reviewer opens in any browser, no SAEngine needed.

Alpha 9 L12 (gap CO-3). :func:`export_web_viewer` writes ``11 Exports/Web Viewer/``:

- ``index.html``: the viewer, self-contained (the model and results are inlined, so it works from
  a USB stick or an e-mail attachment opened as a file, where a browser refuses to fetch side
  files). Its built-in view is a small dependency-free 3D wireframe (drag to orbit, wheel to zoom,
  click a member for its section and design result, members coloured by utilisation). When the
  three.js viewer bundle is beside it (``viewer.js``, built from ``packages/web-viewer``) that
  richer view is used instead;
- ``model.json``: the analysis model's members and plates as pieces (:func:`saengine.exporters.
  analytical.physical_members`), sections, levels and grids (m);
- ``results.json``: the design checks of the last run per element (utilisation, governing
  check, ok), the design summary and, when the analysis results are there, the storey drifts;
- ``model.gltf``: the same geometry as glTF 2.0 (members as lines, plates as triangles), for any
  glTF viewer;
- ``<project>.ifc``: the building model as IFC (the IFC export), for BIM viewers.

The bundle is NOT built here: ``packages/web-viewer`` holds its source and ``npm run build``
there writes ``dist/web-viewer.js`` (see ``docs/exchange.md``); the release build copies it to
``workbench/resources/saengine/web-viewer/viewer.js``. :func:`viewer_bundle` finds it.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
from pathlib import Path
from typing import Any

from saengine.exporters.analytical import AnalyticalModel, ExchangeReport, physical_members

FORMAT_NAME = "Web viewer"
EXPORT_FOLDER = "Web Viewer"
SCHEMA = "saengine.webViewer/1"


def viewer_bundle() -> Path | None:
    """The built three.js viewer bundle, when there is one: ``SAENGINE_WEB_VIEWER_BUNDLE``, the
    release's resources, or the development build of ``packages/web-viewer``."""
    env = os.environ.get("SAENGINE_WEB_VIEWER_BUNDLE")
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates += [
            parent / "workbench" / "resources" / "saengine" / "web-viewer" / "viewer.js",
            parent / "packages" / "web-viewer" / "dist" / "web-viewer.js",
            parent / "resources" / "saengine" / "web-viewer" / "viewer.js",
        ]
    return next((c for c in candidates if c.is_file()), None)


# ─────────────────────────────────────────── data ───────────────────────────────────────────


def model_data(model: AnalyticalModel) -> dict[str, Any]:
    pieces = physical_members(model)
    sections = {
        s.name: {
            "shape": s.shape,
            "depth": s.depth,
            "width": s.width,
            "material": s.material,
            "designation": s.designation,
            "objectType": s.object_type,
        }
        for s in model.sections.values()
    }
    plates = []
    for p in model.plates:
        plates.append(
            {
                "id": p.id,
                "source": p.source,
                "section": p.section,
                "points": [list(model.nodes[n].xyz) for n in p.nodes],
            }
        )
    return {
        "schema": SCHEMA,
        "name": model.name,
        "units": "m",
        "members": [
            {
                "id": m.id,
                "start": list(m.start),
                "end": list(m.end),
                "section": m.section,
                "kind": m.kind,
                "rotation": m.rotation,
                "parts": m.parts,
            }
            for m in pieces
        ],
        "plates": plates,
        "sections": sections,
        "supports": [
            list(model.nodes[n].xyz) for n in model.used_nodes() if model.nodes[n].supported
        ],
        "grids": [{"axis": a, "label": label, "position": pos} for a, label, pos in model.grids],
    }


def results_data(project_root: Path, report: ExchangeReport) -> dict[str, Any]:
    """The design results of the last run, per building element, and the storey drifts."""
    out: dict[str, Any] = {"schema": SCHEMA, "elements": {}, "summary": None, "drifts": []}
    results = project_root / "08 FEM" / "model.results"
    try:
        kept = json.loads((results / "design-report.json").read_text("utf-8"))
        result = kept.get("result") if isinstance(kept, dict) else None
        for e in (result or {}).get("elements") or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            checks = sorted(
                (c for c in e.get("checks") or [] if isinstance(c, dict)),
                key=lambda c: -(c.get("utilisation") or 0),
            )
            entry = {
                "utilisation": e.get("utilisation"),
                "ok": e.get("ok"),
                "type": e.get("type"),
                "governing": checks[0].get("name") if checks else None,
            }
            out["elements"][str(e["id"])] = entry
            for member in e.get("members") or []:
                out["elements"].setdefault(str(member), entry)
        out["summary"] = (result or {}).get("summary")
    except (OSError, ValueError, AttributeError):
        report.warn("No design results yet (Run All): the viewer shows the model only.")
    try:
        summary = json.loads((results / "design-summary.json").read_text("utf-8"))
        out["summary"] = out["summary"] or summary
    except (OSError, ValueError):
        pass
    model_file = project_root / "08 FEM" / "model.osmodel"
    if (results / "manifest.json").is_file() and model_file.is_file():
        try:
            from saengine.rpc.handlers import story_response

            response = story_response(str(results), str(model_file))
            out["drifts"] = _drift_rows(response)
        except Exception as error:  # noqa: BLE001 - a reviewer's extra, never a reason to fail
            report.warn(f"The storey drifts could not be read: {error}")
    return out


def _drift_rows(response: Any) -> list[dict[str, Any]]:
    """Rows ``{case, name, z, driftX, driftY}`` of every storey table in a story response."""
    rows: list[dict[str, Any]] = []

    def walk(value: Any, case: str | None) -> None:
        if isinstance(value, dict):
            label = value.get("label") or value.get("case") or value.get("key") or case
            storeys = value.get("storeys")
            if isinstance(storeys, list):
                for r in storeys:
                    if isinstance(r, dict) and (
                        r.get("driftX") is not None or r.get("driftY") is not None
                    ):
                        rows.append(
                            {
                                "case": label,
                                "name": r.get("name"),
                                "z": r.get("z"),
                                "driftX": r.get("driftX"),
                                "driftY": r.get("driftY"),
                            }
                        )
            for k, v in value.items():
                if k != "storeys":
                    walk(v, label if isinstance(label, str) else case)
        elif isinstance(value, list):
            for v in value:
                walk(v, case)

    walk(response, None)
    return rows[:2000]


def max_drift(response: Any) -> float | None:
    """The largest storey drift ratio of a story response (any case or combination)."""
    values = [
        abs(float(v))
        for r in _drift_rows(response)
        for v in (r.get("driftX"), r.get("driftY"))
        if isinstance(v, int | float)
    ]
    return max(values) if values else None


# ─────────────────────────────────────────── glTF ───────────────────────────────────────────


def gltf(model: AnalyticalModel) -> dict[str, Any]:
    """glTF 2.0 (JSON, one embedded buffer) of the members (lines) and plates (triangles), Y up
    as glTF wants it (SAEngine's Z up turned: x, z, -y)."""

    def gl(p: tuple[float, float, float]) -> tuple[float, float, float]:
        return (p[0], p[2], -p[1])

    line_points: list[tuple[float, float, float]] = []
    for m in physical_members(model):
        line_points += [gl(m.start), gl(m.end)]
    tri_points: list[tuple[float, float, float]] = []
    for p in model.plates:
        pts = [gl(model.nodes[n].xyz) for n in p.nodes]
        for k in range(1, len(pts) - 1):
            tri_points += [pts[0], pts[k], pts[k + 1]]
    buffers = b""
    views, accessors, primitives = [], [], []
    for points, mode in ((line_points, 1), (tri_points, 4)):
        if not points:
            continue
        data = b"".join(struct.pack("<3f", *p) for p in points)
        views.append(
            {"buffer": 0, "byteOffset": len(buffers), "byteLength": len(data), "target": 34962}
        )
        mins = [min(p[k] for p in points) for k in range(3)]
        maxs = [max(p[k] for p in points) for k in range(3)]
        accessors.append(
            {
                "bufferView": len(views) - 1,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
                "min": mins,
                "max": maxs,
            }
        )
        primitives.append(
            {
                "attributes": {"POSITION": len(accessors) - 1},
                "mode": mode,
                "material": 0 if mode == 1 else 1,
            }
        )
        buffers += data
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "SAEngine web viewer export"},
        "scene": 0,
        "scenes": [{"nodes": [0], "name": model.name}],
        "nodes": [{"mesh": 0, "name": model.name}] if primitives else [{"name": model.name}],
        "materials": [
            {"name": "members", "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.3, 0.5, 1]}},
            {
                "name": "plates",
                "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.7, 0.5]},
                "alphaMode": "BLEND",
                "doubleSided": True,
            },
        ],
    }
    if primitives:
        document["meshes"] = [{"primitives": primitives, "name": "structure"}]
        document["buffers"] = [
            {
                "byteLength": len(buffers),
                "uri": "data:application/octet-stream;base64,"
                + base64.b64encode(buffers).decode("ascii"),
            }
        ]
        document["bufferViews"] = views
        document["accessors"] = accessors
    return document


# ─────────────────────────────────────────── page ───────────────────────────────────────────

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ - SAEngine model viewer</title>
<style>
:root { color-scheme: light dark; --bg: #f7f7f5; --fg: #1d1d1b; --muted: #6b6b66; --line: #3b5b8c;
  --ok: #2e7d32; --warn: #c77700; --bad: #c62828; --panel: #ffffffd9; }
@media (prefers-color-scheme: dark) { :root { --bg: #1b1c1e; --fg: #e9e9e6; --muted: #a2a29c;
  --line: #8fb0e0; --panel: #26272ad9; } }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg);
  font: 14px/1.4 system-ui, sans-serif; }
#view { position: fixed; inset: 0; width: 100%; height: 100%; touch-action: none; }
#panel { position: fixed; top: 12px; left: 12px; max-width: min(360px, calc(100% - 24px));
  background: var(--panel); border-radius: 8px; padding: 10px 12px; backdrop-filter: blur(6px); }
#panel h1 { font-size: 15px; margin: 0 0 4px; }
#panel p { margin: 4px 0; color: var(--muted); }
#info { margin-top: 6px; white-space: pre-line; }
.legend span { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 10px; }
button { font: inherit; margin-right: 6px; }
</style>
</head>
<body>
<canvas id="view"></canvas>
<div id="panel">
  <h1>__TITLE__</h1>
  <p id="summary"></p>
  <p class="legend"><span style="background:var(--ok)"></span>passes<span style="background:var(--warn)"></span>&gt; 90 %<span style="background:var(--bad)"></span>fails<span style="background:var(--line)"></span>not checked</p>
  <p><button id="reset">Reset view</button><button id="plates">Plates</button></p>
  <div id="info">Drag to orbit, wheel to zoom, click a member.</div>
</div>
<script>window.SAENGINE_DATA = __DATA__;</script>
<script src="viewer.js" onerror="window.saengineFallbackViewer &amp;&amp; window.saengineFallbackViewer()"></script>
<script>
window.saengineFallbackViewer = function () {
  if (window.saengineViewerStarted) { return; }
  window.saengineViewerStarted = true;
  const data = window.SAENGINE_DATA, model = data.model, results = data.results || { elements: {} };
  const canvas = document.getElementById('view'), ctx = canvas.getContext('2d');
  const css = getComputedStyle(document.documentElement);
  const color = name => css.getPropertyValue(name).trim();
  const pts = [];
  model.members.forEach(m => { pts.push(m.start, m.end); });
  model.plates.forEach(p => p.points.forEach(q => pts.push(q)));
  const lo = [0, 1, 2].map(k => Math.min(...pts.map(p => p[k])));
  const hi = [0, 1, 2].map(k => Math.max(...pts.map(p => p[k])));
  const centre = lo.map((v, k) => (v + hi[k]) / 2);
  const size = Math.max(1, ...hi.map((v, k) => v - lo[k]));
  let yaw = -0.7, pitch = 0.5, zoom = 1, showPlates = true, picked = null;
  const s = results.summary;
  document.getElementById('summary').textContent = s ? `Design: ${s.checked ?? '?'} checked, ${s.passed ?? '?'} pass, ${s.failed ?? '?'} fail` : 'Model only (no design results).';
  function result(m) { return results.elements[m.id] || (m.parts || []).map(p => results.elements[p]).find(Boolean); }
  function stroke(m) {
    const r = result(m);
    if (!r || typeof r.utilisation !== 'number') { return color('--line'); }
    return r.ok === false || r.utilisation > 1 ? color('--bad') : r.utilisation > 0.9 ? color('--warn') : color('--ok');
  }
  function project(p) {
    const x = p[0] - centre[0], y = p[1] - centre[1], z = p[2] - centre[2];
    const cx = Math.cos(yaw), sx = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const x1 = x * cx - y * sx, y1 = x * sx + y * cx;
    const scale = Math.min(canvas.width, canvas.height) / size * 0.8 * zoom;
    return [canvas.width / 2 + x1 * scale, canvas.height / 2 - (z * cp - y1 * sp) * scale, y1 * cp + z * sp];
  }
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (showPlates) {
      ctx.fillStyle = 'rgba(128,128,128,0.12)';
      model.plates.forEach(p => { ctx.beginPath(); p.points.map(project).forEach((q, k) => k ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.closePath(); ctx.fill(); });
    }
    model.members.forEach(m => {
      const a = project(m.start), b = project(m.end);
      ctx.strokeStyle = stroke(m); ctx.lineWidth = (m === picked ? 4 : 1.6) * dpr;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    });
  }
  function nearest(x, y) {
    let best = null, dist = 12 * (window.devicePixelRatio || 1);
    model.members.forEach(m => {
      const a = project(m.start), b = project(m.end), dx = b[0] - a[0], dy = b[1] - a[1];
      const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)));
      const d = Math.hypot(a[0] + t * dx - x, a[1] + t * dy - y);
      if (d < dist) { dist = d; best = m; }
    });
    return best;
  }
  let drag = null;
  canvas.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, moved: false }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', e => {
    if (!drag) { return; }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) { drag.moved = true; }
    yaw += dx * 0.01; pitch = Math.max(-1.5, Math.min(1.5, pitch + dy * 0.01));
    drag.x = e.clientX; drag.y = e.clientY; draw();
  });
  canvas.addEventListener('pointerup', e => {
    if (drag && !drag.moved) {
      const dpr = window.devicePixelRatio || 1;
      picked = nearest(e.clientX * dpr, e.clientY * dpr);
      const r = picked && result(picked), sec = picked && model.sections[picked.section];
      document.getElementById('info').textContent = picked
        ? `${picked.id} (${picked.kind})\\nSection: ${sec && (sec.designation || sec.objectType) || picked.section}` +
          (r ? `\\nUtilisation: ${typeof r.utilisation === 'number' ? (r.utilisation * 100).toFixed(0) + ' %' : '-'}${r.governing ? ' (' + r.governing + ')' : ''}` : '\\nNot checked')
        : 'Drag to orbit, wheel to zoom, click a member.';
      draw();
    }
    drag = null;
  });
  canvas.addEventListener('wheel', e => { e.preventDefault(); zoom *= Math.exp(-e.deltaY * 0.001); draw(); }, { passive: false });
  document.getElementById('reset').onclick = () => { yaw = -0.7; pitch = 0.5; zoom = 1; draw(); };
  document.getElementById('plates').onclick = () => { showPlates = !showPlates; draw(); };
  addEventListener('resize', draw);
  draw();
};
if (!window.saengineViewer) { window.addEventListener('load', () => { if (!window.saengineViewerStarted && !window.saengineViewer) { window.saengineFallbackViewer(); } }); }
</script>
</body>
</html>
"""


def page(model: AnalyticalModel, results: dict[str, Any]) -> str:
    data = json.dumps({"model": model_data(model), "results": results}, ensure_ascii=False)
    # Never close the script element from inside the data.
    data = data.replace("</", "<\\/")
    title = (
        model.name.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return _PAGE.replace("__TITLE__", title).replace("__DATA__", data)


def export_web_viewer(
    project: str | Path, out_dir: str | Path | None = None, *, ifc: bool = True
) -> dict[str, Any]:
    """Writes the web viewer of the project (see the module notes) into ``out_dir`` (default
    ``11 Exports/Web Viewer``): ``{"path" (index.html), "folder", "files", "report"}``."""
    from saengine.exporters.analytical import project_model

    model, report, p = project_model(project, FORMAT_NAME, ".html")
    folder = Path(out_dir) if out_dir else p.folder("exports") / EXPORT_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    results = results_data(p.root, report)
    files = []
    index = folder / "index.html"
    index.write_text(page(model, results), encoding="utf-8")
    files.append(index)
    for name, value in (
        ("model.json", model_data(model)),
        ("results.json", results),
        ("model.gltf", gltf(model)),
    ):
        target = folder / name
        target.write_text(
            json.dumps(value, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8"
        )
        files.append(target)
    bundle = viewer_bundle()
    if bundle is not None:
        shutil.copyfile(bundle, folder / "viewer.js")
        files.append(folder / "viewer.js")
    else:
        stale = folder / "viewer.js"
        if stale.exists():
            stale.unlink()
        report.approximate(
            "the built-in wireframe view (the three.js viewer bundle is not built: packages/web-viewer)"
        )
    if ifc:
        try:
            from saengine.pipeline.exports import ExportError, export_ifc

            files += export_ifc(p, folder / f"{p.name}.ifc")
        except (ExportError, OSError) as error:  # the IFC is an extra of the viewer
            report.warn(f"The IFC was not written: {error}")
    report.count("members", len(model_data(model)["members"]))
    report.count("plates", len(model.plates))
    readable = folder / "export-report.md"
    readable.write_text(report.to_markdown(), encoding="utf-8")
    return {
        "path": str(index),
        "folder": str(folder),
        "files": [str(f) for f in files],
        "report": report.to_dict(),
        "readablePath": str(readable),
    }


__all__ = [
    "EXPORT_FOLDER",
    "FORMAT_NAME",
    "SCHEMA",
    "export_web_viewer",
    "gltf",
    "max_drift",
    "model_data",
    "page",
    "viewer_bundle",
]
