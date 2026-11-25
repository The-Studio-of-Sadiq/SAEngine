"""Exports Publish - create issue packages, viewer payloads and delivery records."""

from __future__ import annotations

import hashlib
import html
import json
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.exports_common import (
    coordinate_rows,
    model_elements,
    output_path,
    project_file_rows,
    require_source,
    write_export_json,
    write_export_text,
)


def _selected_files(ctx: FeatureContext, raw: str) -> list[Path]:
    if ctx.root is None:
        raise FeatureInputError("Open a project to prepare a delivery package.")
    paths = []
    for name in (part.strip() for part in raw.splitlines() if part.strip()):
        path = require_source(ctx, name)
        if path not in paths:
            paths.append(path)
    if not paths:
        paths = [
            ctx.root / row["path"]
            for row in project_file_rows(ctx)
            if row["path"].startswith(("01 Soil Report/", "02 Project Settings/", "06 BIM/"))
        ]
    return paths


@feature(
    "exportsPublish.publishPackage",
    "Publish Package",
    part="settings",
    fields=[
        text("name", "Package name", "design-issue"),
        text(
            "files",
            "Project files, one per line",
            "06 BIM/bim.json\n02 Project Settings/project-settings.json",
        ),
        checkbox("includeManifest", "Include checksums and package manifest", True),
    ],
)
def publish_package(ctx: FeatureContext, values: dict) -> dict:
    """Build a ZIP delivery from selected project files and add source hashes."""
    paths = _selected_files(ctx, values["files"])
    target = output_path(ctx, (values["name"].strip() or "design-issue") + ".zip", "Packages")
    manifest = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source in paths:
            relative = source.relative_to(ctx.root).as_posix()
            data = source.read_bytes()
            archive.writestr(relative, data)
            manifest.append(
                {
                    "path": relative,
                    "sizeBytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        if values["includeManifest"]:
            archive.writestr(
                "delivery-manifest.json",
                json.dumps(
                    {"createdUtc": datetime.now(UTC).isoformat(), "files": manifest},
                    indent=2,
                )
                + "\n",
            )
    return result(
        summary={
            "packagePath": target.relative_to(ctx.root).as_posix(),
            "fileCount": len(paths),
            "sizeBytes": target.stat().st_size,
        },
        tables=[
            table(
                "Included files",
                [("path", "Project path"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256")],
                manifest,
            )
        ],
        notes=[
            "Package contents are copied from the current project files; the manifest can be used to verify the delivered bytes."
        ],
    )


@feature(
    "exportsPublish.packageContents",
    "Package Contents",
    part="settings",
    fields=[text("package", "ZIP package path", "11 Exports/Packages/design-issue.zip")],
)
def package_contents(ctx: FeatureContext, values: dict) -> dict:
    """List ZIP member names, sizes and CRCs without extracting package data."""
    source = require_source(ctx, values["package"])
    try:
        with zipfile.ZipFile(source) as archive:
            rows = [
                {
                    "path": item.filename,
                    "sizeBytes": item.file_size,
                    "compressedBytes": item.compress_size,
                    "crc32": f"{item.CRC:08x}",
                }
                for item in archive.infolist()
            ]
            bad = archive.testzip()
    except (OSError, zipfile.BadZipFile) as error:
        raise FeatureInputError(f"Package cannot be read as ZIP: {error}") from error
    return result(
        summary={
            "memberCount": len(rows),
            "integrityCheck": "passed" if bad is None else f"failed at {bad}",
        },
        tables=[
            table(
                "Package members",
                [
                    ("path", "Member"),
                    ("sizeBytes", "Uncompressed", "byte"),
                    ("compressedBytes", "Compressed", "byte"),
                    ("crc32", "CRC-32"),
                ],
                rows,
            )
        ],
    )


@feature(
    "exportsPublish.recipients",
    "Recipients",
    part="settings",
    fields=[
        text("recipients", "Recipients, one per line", ""),
        text("issue", "Issue reference", "ISSUE-001"),
    ],
)
def recipients(ctx: FeatureContext, values: dict) -> dict:
    """Validate a recipient list and write a transmittal recipient register."""
    rows = []
    for item in values["recipients"].splitlines():
        address = item.strip()
        if address:
            valid = (
                address.count("@") == 1
                and "." in address.rsplit("@", 1)[-1]
                and not any(char.isspace() for char in address)
            )
            rows.append(
                {"recipient": address, "syntaxValid": valid, "issue": values["issue"].strip()}
            )
    if not rows:
        raise FeatureInputError("Enter at least one recipient address.")
    path = write_export_json(ctx, "recipients.json", rows, "Packages") if ctx.root else None
    return result(
        summary={
            "recipientCount": len(rows),
            "invalidCount": sum(not row["syntaxValid"] for row in rows),
            "registerPath": path,
        },
        tables=[
            table(
                "Delivery recipients",
                [("recipient", "Recipient"), ("syntaxValid", "Address syntax"), ("issue", "Issue")],
                rows,
            )
        ],
        notes=["Address syntax is checked locally; this feature does not send email."],
    )


@feature(
    "exportsPublish.zipPackage",
    "ZIP Package",
    part="settings",
    fields=[
        text("files", "Project files, one per line", "06 BIM/bim.json"),
        text("filename", "ZIP filename", "issue-package.zip"),
        number("compression", "Deflate level", 6, min=0, max=9),
    ],
)
def zip_package(ctx: FeatureContext, values: dict) -> dict:
    """Compress an explicit list of project files into a standard ZIP archive."""
    paths = _selected_files(ctx, values["files"])
    level = int(values["compression"])
    target = output_path(ctx, values["filename"].strip() or "issue-package.zip", "Packages")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as archive:
        for source in paths:
            archive.write(source, source.relative_to(ctx.root).as_posix())
    return result(
        summary={
            "packagePath": target.relative_to(ctx.root).as_posix(),
            "fileCount": len(paths),
            "sizeBytes": target.stat().st_size,
            "compressionLevel": level,
        }
    )


@feature(
    "exportsPublish.passcodeProtect",
    "Passcode Protect",
    part="settings",
    fields=[
        text("source", "Package path", "11 Exports/Packages/design-issue.zip"),
        text("passcode", "Passcode", ""),
        text("output", "Protected package name", "issue-package.protected.json"),
    ],
)
def passcode_protect(ctx: FeatureContext, values: dict) -> dict:
    """Create a passcode-derived AES-GCM encrypted package using a random salt and nonce."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as error:
        raise FeatureInputError(
            "Install the cryptography package to create passcode-protected packages."
        ) from error
    if len(values["passcode"]) < 8:
        raise FeatureInputError("Use a passcode with at least eight characters.")
    source = require_source(ctx, values["source"])
    import os

    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(values["passcode"].encode())
    ciphertext = AESGCM(key).encrypt(nonce, source.read_bytes(), b"SAEngine package v1")
    data = {
        "format": "SAEngine AES-GCM package v1",
        "kdf": "scrypt N=16384 r=8 p=1",
        "saltHex": salt.hex(),
        "nonceHex": nonce.hex(),
        "ciphertextHex": ciphertext.hex(),
    }
    path = write_export_json(
        ctx, values["output"].strip() or "issue-package.protected.json", data, "Secure"
    )
    return result(
        summary={
            "protectedPath": path,
            "ciphertextBytes": len(ciphertext),
            "cipher": "AES-256-GCM",
        },
        notes=[
            "The passcode is never stored in the output; retain it separately to decrypt the package."
        ],
    )


@feature(
    "exportsPublish.transmittalSheet",
    "Transmittal Sheet",
    part="settings",
    fields=[
        text("project", "Project title", ""),
        text("issue", "Issue reference", "ISSUE-001"),
        text("files", "Transmitted files, one per line", ""),
        text("recipient", "Recipient", ""),
    ],
)
def transmittal_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Write a readable issue register for selected files with sizes and checksums."""
    paths = _selected_files(ctx, values["files"])
    rows = [
        {
            "file": path.relative_to(ctx.root).as_posix(),
            "sizeBytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]
    text_data = (
        "# Transmittal\n\nProject: "
        + values["project"]
        + "\nIssue: "
        + values["issue"]
        + "\nRecipient: "
        + values["recipient"]
        + "\n\n"
        + "\n".join(
            f"- {row['file']} — {row['sizeBytes']} bytes — SHA-256 {row['sha256']}" for row in rows
        )
        + "\n"
    )
    path = write_export_text(ctx, "transmittal.md", text_data, "Packages")
    return result(
        summary={"transmittalPath": path, "fileCount": len(rows)},
        tables=[
            table(
                "Transmitted files",
                [("file", "File"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256")],
                rows,
            )
        ],
    )


@feature(
    "exportsPublish.coverLetter",
    "Cover Letter",
    part="settings",
    fields=[
        text("project", "Project title", ""),
        text("recipient", "Recipient", ""),
        text("subject", "Subject", "Design issue"),
        text("message", "Message", "Please find the listed project deliverables attached."),
    ],
)
def cover_letter(ctx: FeatureContext, values: dict) -> dict:
    """Assemble a cover letter citing project settings title and packaged deliverables."""
    settings = ctx.raw("settings")
    project_title = values["project"].strip()
    if not project_title and isinstance(settings, dict):
        proj = settings.get("project")
        if isinstance(proj, dict) and isinstance(proj.get("name"), str):
            project_title = proj["name"]
    if not project_title and ctx.root is not None:
        project_title = ctx.root.name
    pkg_dir = ctx.root / "11 Exports" / "Packages" if ctx.root is not None else None
    enclosures = (
        [
            f"- {p.name} ({p.stat().st_size} bytes, sha256:{hashlib.sha256(p.read_bytes()).hexdigest()[:12]})"
            for p in sorted(pkg_dir.iterdir())
            if p.is_file() and p.name != "cover-letter.txt"
        ]
        if pkg_dir is not None and pkg_dir.is_dir()
        else []
    )
    enclosure_block = "\nEnclosures:\n" + "\n".join(enclosures) if enclosures else ""
    body = (
        f"To: {values['recipient']}\n"
        f"Subject: {values['subject']}\n\n"
        f"Re: {project_title}\n\n"
        f"{values['message']}\n"
        f"{enclosure_block}\n\n"
        "Regards,\nProject team\n"
    )
    path = write_export_text(ctx, "cover-letter.txt", body, "Packages")
    return result(
        summary={"letterPath": path, "characters": len(body), "enclosureCount": len(enclosures)},
        notes=["The letter is a draft text file and is not transmitted."],
    )


@feature(
    "exportsPublish.issueLog",
    "Issue Log",
    part="settings",
    fields=[
        text("issue", "Issue reference", "ISSUE-001"),
        select(
            "status",
            "Issue status",
            [("draft", "Draft"), ("issued", "Issued"), ("superseded", "Superseded")],
        ),
        text("description", "Issue description", ""),
    ],
)
def issue_log(ctx: FeatureContext, values: dict) -> dict:
    """Append an issue event to an auditable local publication log."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to record an issue event.")
    path = output_path(ctx, "issue-log.json", "Packages")
    try:
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError as error:
        raise FeatureInputError("The existing issue log is not valid JSON.") from error
    if not isinstance(entries, list):
        raise FeatureInputError("The existing issue log must contain a JSON array.")
    entry = {
        "issue": values["issue"].strip(),
        "status": values["status"],
        "description": values["description"],
        "recordedUtc": datetime.now(UTC).isoformat(),
    }
    entries.append(entry)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={
            "entryCount": len(entries),
            "status": entry["status"],
            "logPath": path.relative_to(ctx.root).as_posix(),
        },
        tables=[
            table(
                "Latest issue event",
                [
                    ("issue", "Issue"),
                    ("status", "Status"),
                    ("recordedUtc", "Recorded UTC"),
                    ("description", "Description"),
                ],
                [entry],
            )
        ],
    )


@feature(
    "exportsPublish.publishWebModel",
    "Publish Web Model",
    part="bim",
    fields=[
        text("title", "Viewer title", "Project model"),
        checkbox("includeProperties", "Include BIM element properties", True),
    ],
)
def publish_web_model(ctx: FeatureContext, values: dict) -> dict:
    """Create a self-contained HTML model index and readable geometry payload."""
    elements = model_elements(ctx)
    geometry = coordinate_rows(ctx)
    payload = [
        {
            "id": str(row.get("id", i + 1)),
            "kind": str(row.get("kind", row.get("type", "element"))),
            "properties": row if values["includeProperties"] else {},
        }
        for i, row in enumerate(elements)
    ]
    data_path = write_export_json(
        ctx,
        "web-model.json",
        {"title": values["title"], "elements": payload, "coordinates": geometry},
        "Web",
    )
    viewer = (
        "<!doctype html><meta charset='utf-8'><title>"
        + html.escape(values["title"])
        + "</title><h1>"
        + html.escape(values["title"])
        + "</h1><p>Model data: <a href='"
        + html.escape(data_path.split("/")[-1])
        + "'>"
        + html.escape(data_path)
        + "</a></p><p>This publication contains a data index; connect it to an approved viewer to render geometry.</p>"
    )
    page = write_export_text(ctx, "index.html", viewer, "Web")
    return result(
        summary={
            "elementCount": len(elements),
            "coordinateCount": len(geometry),
            "dataPath": data_path,
            "viewerPath": page,
        },
        notes=["The HTML page is a static index; it does not embed a WebGL renderer."],
    )


@feature(
    "exportsPublish.embedCode",
    "Embed Code",
    part="settings",
    fields=[
        text("url", "Published viewer URL", "https://example.org/model"),
        number("width", "Frame width", 960, min=200),
        number("height", "Frame height", 640, min=150),
        checkbox("allowFullscreen", "Allow full screen", True),
    ],
)
def embed_code(ctx: FeatureContext, values: dict) -> dict:
    """Create an iframe snippet with escaped URL and explicit dimensions."""
    from urllib.parse import urlparse

    url = values["url"].strip()
    if urlparse(url).scheme not in ("https", "http") or not urlparse(url).netloc:
        raise FeatureInputError("Enter an absolute HTTP or HTTPS viewer URL.")
    code = (
        f'<iframe src="{html.escape(url, quote=True)}" width="{int(values["width"])}" height="{int(values["height"])}" title="Project model"'
        + (" allowfullscreen" if values["allowFullscreen"] else "")
        + "></iframe>\n"
    )
    path = write_export_text(ctx, "embed-code.html", code, "Web")
    return result(
        summary={
            "snippetPath": path,
            "width": int(values["width"]),
            "height": int(values["height"]),
            "fullscreen": values["allowFullscreen"],
        },
        notes=[
            "The snippet points to the URL provided; access controls must be configured by its hosting service."
        ],
    )


@feature(
    "exportsPublish.accessLinks",
    "Access Links",
    part="settings",
    fields=[
        text("url", "Resource URL", "https://example.org/model"),
        number("expiryDays", "Link validity (days)", 30, min=1, max=3650),
        text("recipient", "Recipient label", ""),
    ],
)
def access_links(ctx: FeatureContext, values: dict) -> dict:
    """Create a dated access-link record without pretending to provision a remote account."""
    from urllib.parse import urlparse

    url = values["url"].strip()
    if urlparse(url).scheme not in ("https", "http") or not urlparse(url).netloc:
        raise FeatureInputError("Enter an absolute HTTP or HTTPS resource URL.")
    created = datetime.now(UTC)
    row = {
        "url": url,
        "recipient": values["recipient"].strip(),
        "createdUtc": created.isoformat(),
        "expiresUtc": (created.timestamp() + int(values["expiryDays"]) * 86400),
    }
    path = write_export_json(ctx, "access-links.json", [row], "Secure")
    return result(
        summary={"linkRecordPath": path, "expiryDays": int(values["expiryDays"])},
        tables=[
            table(
                "Access link",
                [
                    ("url", "URL"),
                    ("recipient", "Recipient"),
                    ("createdUtc", "Created"),
                    ("expiresUtc", "Expiry timestamp"),
                ],
                [row],
            )
        ],
        notes=[
            "This is a local link register. It does not create or expire credentials at the remote host."
        ],
    )


@feature(
    "exportsPublish.gltfExport",
    "glTF Export",
    part="bim",
    fields=[text("filename", "glTF filename", "model.gltf")],
)
def gltf_export(ctx: FeatureContext, values: dict) -> dict:
    """Export BIM member centerlines as a glTF scene with an external binary vertex buffer."""
    rows = model_elements(ctx)
    coords = coordinate_rows(ctx)
    endpoints: dict[str, dict[str, dict]] = {}
    for row in coords:
        if row["role"] in ("start", "end"):
            endpoints.setdefault(row["element"], {})[row["role"]] = row
    segments = [
        (ends["start"], ends["end"])
        for ends in endpoints.values()
        if "start" in ends and "end" in ends
    ]
    vertices = [point for segment in segments for point in segment] if segments else coords
    positions = [
        (float(point["xMm"]) / 1000, float(point["yMm"]) / 1000, float(point["zMm"]) / 1000)
        for point in vertices
    ]
    if not positions:
        raise FeatureInputError("The BIM model has no exportable point or member geometry.")
    binary = struct.pack(
        f"<{len(positions) * 3}f", *(axis for point in positions for axis in point)
    )
    minimum = [min(point[axis] for point in positions) for axis in range(3)]
    maximum = [max(point[axis] for point in positions) for axis in range(3)]
    requested = Path(values["filename"].strip() or "model.gltf").name
    if not requested.casefold().endswith(".gltf"):
        requested += ".gltf"
    gltf_path = output_path(ctx, requested, "Models")
    buffer_name = gltf_path.with_suffix(".bin").name
    document = {
        "asset": {"version": "2.0", "generator": "SAEngine BIM centerline export"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "BIM member geometry", "mesh": 0, "extras": {"sourceElementCount": len(rows)}}
        ],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "mode": 1 if segments else 0,
                    }
                ]
            }
        ],
        "buffers": [{"uri": buffer_name, "byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary), "target": 34962}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": minimum,
                "max": maximum,
            }
        ],
        "extras": {"coordinateUnit": "metre", "primitive": "lines" if segments else "points"},
    }
    gltf_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    buffer_path = output_path(ctx, buffer_name, "Models")
    buffer_path.write_bytes(binary)
    return result(
        summary={
            "elementCount": len(rows),
            "coordinateCount": len(coords),
            "vertexCount": len(positions),
            "primitive": "lines" if segments else "points",
            "gltfPath": gltf_path.relative_to(ctx.root).as_posix(),
            "bufferPath": buffer_path.relative_to(ctx.root).as_posix(),
        },
        notes=[
            "Line geometry is exported from BIM start/end coordinates in metres. Solid surface meshes are not inferred from centerlines."
        ],
    )


@feature(
    "exportsPublish.usdzExport",
    "USDZ Export",
    part="bim",
    fields=[text("filename", "USDZ package filename", "model.usdz")],
)
def usdz_export(ctx: FeatureContext, values: dict) -> dict:
    """Package BIM line geometry as a standards-shaped uncompressed USDZ archive."""
    coords = coordinate_rows(ctx)
    endpoints: dict[str, dict[str, dict]] = {}
    for row in coords:
        if row["role"] in ("start", "end"):
            endpoints.setdefault(row["element"], {})[row["role"]] = row
    segments = [
        (ends["start"], ends["end"])
        for ends in endpoints.values()
        if "start" in ends and "end" in ends
    ]
    points = [point for segment in segments for point in segment] if segments else coords
    usd_points = [
        f"({float(row['xMm']) / 1000:.8g}, {float(row['yMm']) / 1000:.8g}, {float(row['zMm']) / 1000:.8g})"
        for row in points
    ]
    if segments:
        stage = (
            '#usda 1.0\n(\n    defaultPrim = "Model"\n    metersPerUnit = 1\n    upAxis = "Z"\n)\n'
            'def Xform "Model" {\n    def BasisCurves "Members" {\n'
            '        uniform token type = "linear"\n        uniform token wrap = "nonperiodic"\n'
            f"        point3f[] points = [{', '.join(usd_points)}]\n"
            f"        int[] curveVertexCounts = [{', '.join('2' for _ in segments)}]\n"
            "    }\n}\n"
        )
        geometry = "linear centerlines"
    else:
        stage = (
            '#usda 1.0\n(\n    defaultPrim = "Model"\n    metersPerUnit = 1\n    upAxis = "Z"\n)\n'
            'def Xform "Model" {\n    def Points "Coordinates" {\n'
            f"        point3f[] points = [{', '.join(usd_points)}]\n"
            "    }\n}\n"
        )
        geometry = "survey points"
    requested = Path(values["filename"].strip() or "model.usdz").name
    if not requested.casefold().endswith(".usdz"):
        requested += ".usdz"
    target = output_path(ctx, requested, "Models")
    member = "model.usda"
    padding = (-(30 + len(member.encode("utf-8")) + 4)) % 64
    info = zipfile.ZipInfo(member)
    info.compress_type = zipfile.ZIP_STORED
    info.extra = struct.pack("<HH", 0x1986, padding) + bytes(padding)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(info, stage.encode("utf-8"))
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "coordinateCount": len(coords),
            "segmentCount": len(segments),
            "geometry": geometry,
            "path": path,
            "sizeBytes": target.stat().st_size,
        },
        notes=[
            "USD ASCII geometry is stored uncompressed in a USDZ container with a 64-byte-aligned first asset. Member centerlines are exported; solid surfaces are not inferred from them."
        ],
    )


@feature(
    "exportsPublish.3dPdfCreate",
    "3D PDF Create",
    part="bim",
    fields=[text("filename", "PDF filename", "model-3d-summary.pdf")],
)
def three_d_pdf_create(ctx: FeatureContext, values: dict) -> dict:
    """Create a printable PDF model summary with source element and coordinate listings."""
    elements = model_elements(ctx)
    coords = coordinate_rows(ctx)
    try:
        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        page = canvas.Canvas(buffer, pagesize=A4)
        _, height = A4
        page.setTitle("SAEngine model summary")
        page.drawString(48, height - 48, "3D Model Summary")
        page.drawString(
            48, height - 70, f"Elements: {len(elements)}    Coordinate records: {len(coords)}"
        )
        y = height - 105
        for row in coords[:45]:
            page.drawString(
                48,
                y,
                f"{row['element']} {row['role']}: {row['xMm']:.1f}, {row['yMm']:.1f}, {row['zMm']:.1f} mm",
            )
            y -= 14
            if y < 40:
                page.showPage()
                y = height - 48
        page.save()
        payload = buffer.getvalue()
    except ImportError as error:
        raise FeatureInputError("Install reportlab to generate the model-summary PDF.") from error
    target = output_path(ctx, values["filename"].strip() or "model-3d-summary.pdf", "Models")
    target.write_bytes(payload)
    return result(
        summary={
            "pdfPath": target.relative_to(ctx.root).as_posix(),
            "elementCount": len(elements),
            "coordinateRowsShown": min(45, len(coords)),
        },
        notes=[
            "This is a printable model summary, not a PDF with embedded interactive 3D content."
        ],
    )


@feature(
    "exportsPublish.webglViewer",
    "WebGL Viewer",
    part="bim",
    fields=[text("title", "Page title", "Model viewer")],
)
def webgl_viewer(ctx: FeatureContext, values: dict) -> dict:
    """Create a self-contained WebGL wireframe preview from BIM member centerlines."""
    rows = coordinate_rows(ctx)
    endpoints: dict[str, dict[str, dict]] = {}
    for row in rows:
        if row["role"] in ("start", "end"):
            endpoints.setdefault(row["element"], {})[row["role"]] = row
    segments = [
        (ends["start"], ends["end"])
        for ends in endpoints.values()
        if "start" in ends and "end" in ends
    ]
    source_points = [point for segment in segments for point in segment] if segments else rows
    center = [
        sum(float(row[key]) for row in source_points) / len(source_points)
        for key in ("xMm", "yMm", "zMm")
    ]
    scale = (
        max(
            max(float(row[key]) for row in source_points)
            - min(float(row[key]) for row in source_points)
            for key in ("xMm", "yMm", "zMm")
        )
        or 1.0
    )
    vertices = [
        [2 * (float(row[key]) - center[i]) / scale for i, key in enumerate(("xMm", "yMm", "zMm"))]
        for row in source_points
    ]
    payload = {
        "title": values["title"],
        "primitive": "LINES" if segments else "POINTS",
        "vertices": vertices,
        "units": "normalized from source mm",
    }
    data = write_export_json(ctx, "scene-data.json", payload, "WebGL")
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = (
        """<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>body{font:14px system-ui;margin:1rem;background:#111827;color:#e5e7eb}canvas{width:min(100%,1000px);height:70vh;display:block;background:#0b1220;border:1px solid #475569}#status{color:#93c5fd}</style>
<h1>__TITLE__</h1><canvas id="view"></canvas><p id="status">Drag to rotate the BIM wireframe. Scene data: __DATA__</p>
<script>
const scene=__SCENE__;
const canvas=document.getElementById('view'), gl=canvas.getContext('webgl');
if(!gl){document.getElementById('status').textContent='WebGL is unavailable in this browser.';throw new Error('WebGL unavailable');}
const vs='attribute vec3 p; uniform float ax; uniform float ay; void main(){float y=cos(ax)*p.y-sin(ax)*p.z; float z=sin(ax)*p.y+cos(ax)*p.z; float x=cos(ay)*p.x+sin(ay)*z; float d=-sin(ay)*p.x+cos(ay)*z; gl_Position=vec4(x,y,0.7*d,1.0); gl_PointSize=7.0;}';
const fs='precision mediump float; void main(){gl_FragColor=vec4(0.20,0.78,0.92,1.0);}';
function shader(type,src){const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vs));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fs));gl.linkProgram(program);gl.useProgram(program);
const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(scene.vertices.flat()),gl.STATIC_DRAW);
const pos=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(pos);gl.vertexAttribPointer(pos,3,gl.FLOAT,false,0,0);
const ax=gl.getUniformLocation(program,'ax'),ay=gl.getUniformLocation(program,'ay');let rx=-0.35,ry=0.55,drag=null;
function draw(){const ratio=window.devicePixelRatio||1;const w=Math.max(1,canvas.clientWidth*ratio),h=Math.max(1,canvas.clientHeight*ratio);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.clearColor(0.04,0.07,0.13,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.uniform1f(ax,rx);gl.uniform1f(ay,ry);gl.drawArrays(scene.primitive==='LINES'?gl.LINES:gl.POINTS,0,scene.vertices.length);}
canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)});canvas.addEventListener('pointermove',e=>{if(drag){ry+=(e.clientX-drag[0])*0.01;rx+=(e.clientY-drag[1])*0.01;drag=[e.clientX,e.clientY];draw()}});canvas.addEventListener('pointerup',()=>drag=null);window.addEventListener('resize',draw);draw();
</script>""".replace("__TITLE__", html.escape(values["title"]))
        .replace("__DATA__", html.escape(data))
        .replace("__SCENE__", embedded)
    )
    html_path = write_export_text(ctx, "viewer.html", page, "WebGL")
    return result(
        summary={
            "coordinateCount": len(rows),
            "vertexCount": len(vertices),
            "sceneDataPath": data,
            "viewerPath": html_path,
        },
        notes=[
            "The viewer draws member centerlines as WebGL lines, or source coordinates as points when no member endpoints are available."
        ],
    )


@feature(
    "exportsPublish.pushToCloud",
    "Push to Cloud",
    part="settings",
    fields=[
        select(
            "provider",
            "Provider",
            [
                ("generic", "Generic HTTPS endpoint"),
                ("s3", "S3-compatible"),
                ("azure", "Azure Blob"),
                ("gcs", "Google Cloud Storage"),
            ],
        ),
        text("remoteFolder", "Remote folder or bucket path", "project-issues"),
    ],
)
def push_to_cloud(ctx: FeatureContext, values: dict) -> dict:
    """Prepare a cloud-transfer manifest with hashes for a separate authenticated uploader."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to prepare a cloud transfer.")
    rows = project_file_rows(ctx)
    manifest = [
        {
            "path": row["path"],
            "sizeBytes": row["sizeBytes"],
            "sha256": hashlib.sha256((ctx.root / row["path"]).read_bytes()).hexdigest(),
        }
        for row in rows
    ]
    path = write_export_json(
        ctx,
        "cloud-transfer-manifest.json",
        {"provider": values["provider"], "remoteFolder": values["remoteFolder"], "files": manifest},
        "Packages",
    )
    return result(
        summary={"manifestPath": path, "fileCount": len(manifest), "uploaded": False},
        notes=[
            "Authentication and network transfer are delegated to the selected cloud provider's approved uploader."
        ],
    )


@feature(
    "exportsPublish.clientAccess",
    "Client Access",
    part="settings",
    fields=[
        text("client", "Client name", ""),
        text("resource", "Resource path or URL", ""),
        number("expiryDays", "Access term in days", 30, min=1, max=3650),
        checkbox("downloadAllowed", "Allow local download", False),
    ],
)
def client_access(ctx: FeatureContext, values: dict) -> dict:
    """Record client access scope and expiry as a local access-policy entry."""
    if not values["client"].strip() or not values["resource"].strip():
        raise FeatureInputError("Provide both a client name and a resource.")
    created = datetime.now(UTC)
    policy = {
        "client": values["client"].strip(),
        "resource": values["resource"].strip(),
        "createdUtc": created.isoformat(),
        "expiresUtc": datetime.fromtimestamp(
            created.timestamp() + int(values["expiryDays"]) * 86400, UTC
        ).isoformat(),
        "downloadAllowed": values["downloadAllowed"],
    }
    path = write_export_json(ctx, "client-access-policy.json", [policy], "Secure")
    return result(
        summary={
            "policyPath": path,
            "expiryUtc": policy["expiresUtc"],
            "downloadAllowed": policy["downloadAllowed"],
        },
        tables=[
            table(
                "Client policy",
                [
                    ("client", "Client"),
                    ("resource", "Resource"),
                    ("expiresUtc", "Expiry UTC"),
                    ("downloadAllowed", "Download"),
                ],
                [policy],
            )
        ],
        notes=[
            "This policy file records intended access; enforcement requires a connected document service."
        ],
    )


@feature(
    "exportsPublish.feedbackLink",
    "Feedback Link",
    part="settings",
    fields=[
        text("url", "Feedback form URL", "https://example.org/feedback"),
        text("issue", "Issue reference", "ISSUE-001"),
    ],
)
def feedback_link(ctx: FeatureContext, values: dict) -> dict:
    """Create a feedback invitation record with an issue reference."""
    from urllib.parse import urlparse

    url = values["url"].strip()
    if urlparse(url).scheme not in ("https", "http") or not urlparse(url).netloc:
        raise FeatureInputError("Enter an absolute HTTP or HTTPS feedback URL.")
    path = write_export_json(
        ctx,
        "feedback-invitation.json",
        {
            "url": url,
            "issue": values["issue"],
            "createdUtc": datetime.now(UTC).isoformat(),
        },
        "Packages",
    )
    return result(
        summary={"invitationPath": path, "issue": values["issue"]},
        notes=[
            "The feedback endpoint is recorded for the recipient; this feature does not submit a response."
        ],
    )


@feature(
    "exportsPublish.drmProtection",
    "DRM Protection",
    part="settings",
    fields=[
        text("package", "Package path", "11 Exports/Packages/design-issue.zip"),
        text("policy", "Protection policy name", "view-only"),
    ],
)
def drm_protection(ctx: FeatureContext, values: dict) -> dict:
    """Create a DRM policy manifest that describes the package and verifies its current hash."""
    source = require_source(ctx, values["package"])
    policy = {
        "package": source.relative_to(ctx.root).as_posix(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "policy": values["policy"],
        "createdUtc": datetime.now(UTC).isoformat(),
        "enforcement": "requires-compatible-DRM-service",
    }
    path = write_export_json(ctx, "drm-policy.json", policy, "Secure")
    return result(
        summary={"policyPath": path, "packageSha256": policy["sha256"], "enforcedLocally": False},
        notes=[
            "The manifest documents requested restrictions; it does not encrypt or enforce rights on the package."
        ],
    )


@feature(
    "exportsPublish.expirationDate",
    "Expiration Date",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        number("validDays", "Validity in days", 30, min=1, max=3650),
    ],
)
def expiration_date(ctx: FeatureContext, values: dict) -> dict:
    """Calculate and store an explicit UTC expiry date for a publication resource."""
    created = datetime.now(UTC)
    expires = datetime.fromtimestamp(created.timestamp() + int(values["validDays"]) * 86400, UTC)
    path = write_export_json(
        ctx,
        "publication-expiry.json",
        {
            "resource": values["resource"],
            "createdUtc": created.isoformat(),
            "expiresUtc": expires.isoformat(),
        },
        "Secure",
    )
    return result(
        summary={
            "resource": values["resource"],
            "expiresUtc": expires.isoformat(),
            "recordPath": path,
        }
    )


@feature(
    "exportsPublish.watermarkModel",
    "Watermark Model",
    part="bim",
    fields=[
        text("label", "Watermark text", "PRELIMINARY"),
        text("output", "Watermarked data filename", "watermarked-model.json"),
    ],
)
def watermark_model(ctx: FeatureContext, values: dict) -> dict:
    """Add a visible publication label to every BIM element in an export copy."""
    elements = model_elements(ctx)
    payload = {
        "watermark": values["label"],
        "elements": [{**row, "publicationWatermark": values["label"]} for row in elements],
    }
    path = write_export_json(
        ctx, values["output"].strip() or "watermarked-model.json", payload, "Models"
    )
    return result(
        summary={"elementCount": len(elements), "watermark": values["label"], "path": path},
        notes=["Source BIM data is unchanged; the watermark is stored as export metadata."],
    )


@feature(
    "exportsPublish.emailPackage",
    "Email Package",
    part="settings",
    fields=[
        text("package", "Package path", "11 Exports/Packages/design-issue.zip"),
        text("recipient", "Recipient address", ""),
        text("subject", "Email subject", "Project issue package"),
    ],
)
def email_package(ctx: FeatureContext, values: dict) -> dict:
    """Draft an email message with a package hash and attachment path."""
    source = require_source(ctx, values["package"])
    body = f"To: {values['recipient']}\nSubject: {values['subject']}\nAttachment: {source.relative_to(ctx.root).as_posix()}\nSHA-256: {hashlib.sha256(source.read_bytes()).hexdigest()}\n"
    path = write_export_text(ctx, "email-draft.eml", body, "Packages")
    return result(
        summary={"draftPath": path, "packageBytes": source.stat().st_size},
        notes=["Email is saved as a draft; no message is sent."],
    )


@feature(
    "exportsPublish.ftpUpload",
    "FTP Upload",
    part="settings",
    fields=[
        text("source", "File path", "11 Exports/Packages/design-issue.zip"),
        text("host", "FTP hostname", ""),
        text("remotePath", "Remote path", "/incoming/"),
        checkbox("useTls", "Require explicit FTPS", True),
    ],
)
def ftp_upload(ctx: FeatureContext, values: dict) -> dict:
    """Prepare an FTP transfer manifest and reject cleartext transport by default."""
    source = require_source(ctx, values["source"])
    if not values["useTls"]:
        raise FeatureInputError(
            "Cleartext FTP is disabled because it exposes credentials and package contents."
        )
    if not values["host"].strip():
        raise FeatureInputError("Enter the approved FTPS host.")
    manifest = {
        "protocol": "explicit-FTPS",
        "host": values["host"].strip(),
        "remotePath": values["remotePath"],
        "source": source.relative_to(ctx.root).as_posix(),
        "sizeBytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "uploaded": False,
    }
    path = write_export_json(ctx, "ftps-transfer.json", manifest, "Packages")
    return result(
        summary={"manifestPath": path, "uploaded": False, "protocol": "explicit-FTPS"},
        notes=[
            "Transfer credentials and server certificate checks belong to an approved FTPS client."
        ],
    )


@feature(
    "exportsPublish.webhookNotify",
    "Webhook Notify",
    part="settings",
    fields=[
        text("endpoint", "HTTPS webhook URL", "https://example.org/hooks/issue"),
        text("issue", "Issue reference", "ISSUE-001"),
        select(
            "event",
            "Event",
            [("published", "Published"), ("superseded", "Superseded"), ("withdrawn", "Withdrawn")],
        ),
    ],
)
def webhook_notify(ctx: FeatureContext, values: dict) -> dict:
    """Create a signed-ready webhook payload for a separately configured notification service."""
    from urllib.parse import urlparse

    url = values["endpoint"].strip()
    if urlparse(url).scheme != "https" or not urlparse(url).netloc:
        raise FeatureInputError("Enter an absolute HTTPS webhook URL.")
    payload = {
        "event": values["event"],
        "issue": values["issue"],
        "createdUtc": datetime.now(UTC).isoformat(),
        "projectFileCount": len(project_file_rows(ctx)) if ctx.root else 0,
    }
    path = write_export_json(
        ctx, "webhook-payload.json", {"endpoint": url, "payload": payload}, "Packages"
    )
    return result(
        summary={"payloadPath": path, "event": payload["event"], "sent": False},
        notes=[
            "No outbound request is made; a separately authorized webhook worker must deliver the payload."
        ],
    )
