"""Exports Archive - project archives, version checks, file integrity and cleanup."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.exports_common import (
    output_path,
    protect_for_current_windows_user,
    require_source,
    write_export_bytes,
    write_export_json,
)


@feature(
    "exportsArchive.createArchive",
    "Create Archive",
    part="settings",
    fields=[
        text("name", "Archive name", "project-archive"),
        checkbox("includeVersions", "Include project version history", False),
    ],
)
def create_archive(ctx: FeatureContext, values: dict) -> dict:
    """Create a native SAEngine .civil archive with an inspectable manifest."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to create an archive.")
    from saengine.project.archive import export_project

    target = output_path(ctx, f"{values['name'].strip() or 'project-archive'}.civil", "Archives")
    data = export_project(
        ctx.root, target, include_versions=values["includeVersions"], include_exports=True
    )
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"archivePath": path, "fileCount": data["files"], "sizeBytes": data["size"]},
        tables=[
            table(
                "Archive omissions",
                [("path", "Path"), ("reason", "Reason")],
                data.get("skipped", []),
            )
        ],
        notes=[
            f"SAEngine archive written to {path}; {len(data.get('problems', []))} project-file warnings were recorded."
        ],
    )


@feature(
    "exportsArchive.restoreArchive",
    "Restore Archive",
    part="settings",
    fields=[
        text(
            "archive",
            "Archive path relative to project",
            "11 Exports/Archives/project-archive.civil",
        ),
        text("destination", "New project folder name", "restored-project"),
        checkbox("includeMigrations", "Apply automatic project migrations", True),
    ],
)
def restore_archive(ctx: FeatureContext, values: dict) -> dict:
    """Safely import a selected .civil archive into a new folder under the current project."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder to choose an archive and destination.")
    from saengine.project.archive import ArchiveError, import_project

    source = require_source(ctx, values["archive"])
    try:
        info = import_project(
            source, ctx.root, name=values["destination"], migrate=values["includeMigrations"]
        )
    except ArchiveError as error:
        raise FeatureInputError(str(error)) from error
    return result(
        summary={
            "restoredProject": info["name"],
            "fileCount": info["files"],
            "migrations": len(info.get("migrated", [])),
            "projectPath": Path(info["root"]).relative_to(ctx.root).as_posix(),
        },
        tables=[
            table(
                "Import warnings",
                [("message", "Warning")],
                [{"message": row.get("message")} for row in info.get("problems", [])],
            )
        ],
        notes=[
            "The archive importer checks paths and checksums before extracting into a new project directory."
        ],
    )


@feature(
    "exportsArchive.archiveManifest",
    "Archive Manifest",
    part="settings",
    fields=[
        text(
            "archive",
            "Archive path relative to project",
            "11 Exports/Archives/project-archive.civil",
        ),
        checkbox("verifyChecksums", "Verify archive file checksums", True),
    ],
)
def archive_manifest(ctx: FeatureContext, values: dict) -> dict:
    """Read a native archive's manifest, project metadata and integrity findings without extracting it."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder to inspect an archive.")
    from saengine.project.archive import inspect_archive

    source = require_source(ctx, values["archive"])
    report = inspect_archive(source, verify=values["verifyChecksums"])
    manifest = report.get("manifest") or {}
    project = manifest.get("project", {})
    problems = report.get("problems", [])
    return result(
        summary={
            "archiveValid": report["ok"],
            "fileCount": report["files"],
            "uncompressedSizeBytes": report["size"],
            "projectName": project.get("name", ""),
            "problemCount": len(problems),
        },
        tables=[
            table(
                "Archive checks",
                [("severity", "Severity"), ("code", "Code"), ("message", "Finding")],
                problems,
            )
        ],
        notes=["Manifest and checksums are read in place; no archive entries are extracted."],
    )


@feature(
    "exportsArchive.zipCompression",
    "ZIP Compression",
    part="settings",
    fields=[
        text("folder", "Project folder to compress", "01 Soil Report"),
        text("filename", "ZIP filename", "soil-report-inputs.zip"),
        number("compressionLevel", "Deflate level", 6, min=0, max=9),
    ],
)
def zip_compression(ctx: FeatureContext, values: dict) -> dict:
    """Package one project folder in ZIP and report its original and compressed sizes."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to compress a folder.")
    folder = (ctx.root / values["folder"]).resolve()
    if ctx.root.resolve() not in folder.parents or not folder.is_dir():
        raise FeatureInputError("Choose an existing project folder below the project root.")
    target = output_path(ctx, values["filename"].strip() or "project-files.zip", "Archives")
    method = zipfile.ZIP_STORED if int(values["compressionLevel"]) == 0 else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(
        target,
        "w",
        compression=method,
        compresslevel=int(values["compressionLevel"]) if method == zipfile.ZIP_DEFLATED else None,
    ) as archive:
        source_files = [
            path for path in folder.rglob("*") if path.is_file() and ".git" not in path.parts
        ]
        for source in source_files:
            archive.write(source, source.relative_to(ctx.root).as_posix())
    total = sum(path.stat().st_size for path in source_files)
    relative = target.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "fileCount": len(source_files),
            "originalSizeBytes": total,
            "compressedSizeBytes": target.stat().st_size,
            "compressionRatio": target.stat().st_size / total if total else 1,
            "archivePath": relative,
        },
        notes=[
            f"Project folder packaged to {relative}; this is a generic ZIP, not a native .civil archive."
        ],
    )


@feature(
    "exportsArchive.encryptArchive",
    "Encrypt Archive",
    part="settings",
    fields=[
        text(
            "source",
            "File to protect, relative to project",
            "11 Exports/Archives/project-archive.civil",
        ),
        text("filename", "Encrypted output name", "project-archive.civil.dpapi"),
    ],
)
def encrypt_archive(ctx: FeatureContext, values: dict) -> dict:
    """Protect an archive using Windows DPAPI for the current user's Windows profile."""
    source = require_source(ctx, values["source"])
    protected = protect_for_current_windows_user(source.read_bytes())
    payload = b"SAENGINE-DPAPI/1\n" + protected
    path = write_export_bytes(
        ctx, values["filename"].strip() or "project-archive.civil.dpapi", payload, "Secure"
    )
    return result(
        summary={
            "inputSizeBytes": source.stat().st_size,
            "protectedSizeBytes": len(payload),
            "outputPath": path,
            "scope": "current Windows user profile",
        },
        notes=[
            f"Encrypted bytes written to {path}. Windows DPAPI restricts decryption to the same user's Windows profile; this package is not portable to another recipient."
        ],
    )


@feature(
    "exportsArchive.validateFormats",
    "Validate Formats",
    part="settings",
    fields=[
        text(
            "files",
            "Files relative to project",
            "01 Soil Report/soil-report.json,02 Project Settings/project-settings.json",
        )
    ],
)
def validate_formats(ctx: FeatureContext, values: dict) -> dict:
    """Check selected project files for readable JSON, XML, CSV, ZIP, DXF or IFC signatures."""
    import xml.etree.ElementTree as ET

    checks = []
    for relative in [item.strip() for item in values["files"].split(",") if item.strip()]:
        path = require_source(ctx, relative)
        suffix = path.suffix.casefold()
        status, detail = "checked", ""
        try:
            if suffix == ".json":
                json.loads(path.read_text(encoding="utf-8-sig"))
            elif suffix in (".xml", ".ifcxml"):
                ET.parse(path)
            elif suffix == ".csv":
                rows = list(csv.reader(path.open(encoding="utf-8-sig", newline="")))
                if not rows:
                    raise ValueError("CSV is empty")
            elif suffix in (".zip", ".civil"):
                with zipfile.ZipFile(path) as archive:
                    bad = archive.testzip()
                    if bad:
                        raise ValueError(f"corrupt ZIP member {bad}")
            elif suffix == ".dxf":
                import ezdxf

                ezdxf.readfile(path)
            elif suffix in (".ifc", ".step", ".stp"):
                import ifcopenshell

                ifcopenshell.open(str(path))
            elif suffix in (".txt", ".md", ".csv", ".bdf", ".inp", ".mgt"):
                path.read_text(encoding="utf-8-sig")
            else:
                status, detail = (
                    "no validator",
                    f"No parser is configured for {suffix or 'extensionless files'}",
                )
        except (
            OSError,
            ValueError,
            UnicodeError,
            ImportError,
            RuntimeError,
            zipfile.BadZipFile,
            ET.ParseError,
        ) as error:
            status, detail = "invalid", str(error).splitlines()[0]
        checks.append({"path": relative, "status": status, "detail": detail})
    return result(
        summary={
            "fileCount": len(checks),
            "valid": sum(row["status"] == "checked" for row in checks),
            "invalid": sum(row["status"] == "invalid" for row in checks),
        },
        tables=[
            table(
                "File format checks",
                [("path", "Path"), ("status", "Status"), ("detail", "Detail")],
                checks,
            )
        ],
        notes=[
            "This validates parseability only; format-specific engineering completeness and recipient acceptance are not checked."
        ],
    )


@feature(
    "exportsArchive.brokenLinks",
    "Broken Links",
    part="settings",
    fields=[
        text("file", "JSON file relative to project", "06 BIM/bim.json"),
        number("maximumLinks", "Maximum links to inspect", 10000, min=1, max=100000),
    ],
)
def broken_links(ctx: FeatureContext, values: dict) -> dict:
    """Find relative file-path references in a JSON document that do not resolve in the project."""
    source = require_source(ctx, values["file"])
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The selected file is not readable JSON: {error}") from error
    found: list[tuple[str, str]] = []

    def visit(node: Any, location: str = "") -> None:
        if len(found) >= int(values["maximumLinks"]):
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    isinstance(value, str)
                    and ("path" in key.casefold() or "file" in key.casefold())
                    and ("/" in value or "\\" in value)
                ):
                    found.append((f"{location}.{key}".strip("."), value))
                else:
                    visit(value, f"{location}.{key}".strip("."))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{location}[{index}]")

    visit(data)
    rows = []
    for location, reference in found:
        candidate = (source.parent / reference).resolve()
        valid = ctx.root.resolve() in candidate.parents and candidate.exists()
        rows.append({"location": location, "reference": reference, "exists": valid})
    return result(
        summary={"linkCount": len(rows), "brokenLinks": sum(not row["exists"] for row in rows)},
        tables=[
            table(
                "Project file references",
                [("location", "JSON field"), ("reference", "Reference"), ("exists", "Resolves")],
                rows,
            )
        ],
        notes=[
            "Only string values under keys containing 'path' or 'file' are treated as links; external URL references are not followed."
        ],
    )


@feature(
    "exportsArchive.versionCheck",
    "Version Check",
    part="settings",
    fields=[text("file", "Project manifest path", ".saengine")],
)
def version_check(ctx: FeatureContext, values: dict) -> dict:
    """Read the project manifest schema and compare it with supported migration metadata."""
    source = require_source(ctx, values["file"])
    try:
        manifest = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The project manifest is not readable JSON: {error}") from error
    schema = manifest.get("schema")
    return result(
        summary={
            "projectName": manifest.get("name", ""),
            "projectType": manifest.get("type", "building"),
            "schema": schema,
            "migrationStatus": "schema declared" if schema else "legacy schema field absent",
        },
        tables=[
            table(
                "Project version metadata",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": key, "value": value}
                    for key, value in manifest.items()
                    if key in ("name", "type", "schema", "version", "created")
                ],
            )
        ],
        notes=[
            "Checks manifest metadata only; engine migrations are listed and run by the separate Version Upgrade operation."
        ],
    )


@feature(
    "exportsArchive.purgeUnused",
    "Purge Unused",
    part="settings",
    fields=[checkbox("includeMaterials", "Find unused material definitions", True)],
)
def purge_unused(ctx: FeatureContext, values: dict) -> dict:
    """Identify unreferenced object types and optionally material records without deleting them."""
    objects, materials = ctx.raw("objects"), ctx.raw("materials")
    if not isinstance(objects, dict) or not isinstance(materials, dict):
        raise FeatureInputError("Open a project with valid object and material libraries.")
    all_json = (
        " ".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in ctx.root.rglob("*.json")
            if ".git" not in path.parts
        )
        if ctx.root
        else ""
    )
    object_rows = objects.get("objects", [])
    material_rows = materials.get("materials", [])
    unused = [
        {"kind": "object type", "id": row.get("id"), "name": row.get("name", "")}
        for row in object_rows
        if isinstance(row, dict) and row.get("id") and f'"{row["id"]}"' not in all_json
    ]
    if values["includeMaterials"]:
        unused += [
            {"kind": "material", "id": row.get("id"), "name": row.get("name", "")}
            for row in material_rows
            if isinstance(row, dict) and row.get("id") and f'"{row["id"]}"' not in all_json
        ]
    return result(
        summary={
            "unusedDefinitionCount": len(unused),
            "objectTypes": sum(row["kind"] == "object type" for row in unused),
            "materials": sum(row["kind"] == "material" for row in unused),
        },
        tables=[
            table(
                "Unreferenced definitions",
                [("kind", "Kind"), ("id", "Identifier"), ("name", "Name")],
                unused,
            )
        ],
        notes=[
            "Reference search scans project JSON text for identifier values. No library records are removed."
        ],
    )


@feature(
    "exportsArchive.compactProject",
    "Compact Project",
    part="settings",
    fields=[
        text("name", "Compact archive name", "compact-project"),
        checkbox("includeVersions", "Keep version history", False),
    ],
)
def compact_project(ctx: FeatureContext, values: dict) -> dict:
    """Compact project deliverables by creating a new native archive without computed results."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to create a compact archive.")
    from saengine.project.archive import export_project

    target = output_path(ctx, f"{values['name'].strip() or 'compact-project'}.civil", "Archives")
    summary = export_project(
        ctx.root,
        target,
        include_results=False,
        include_versions=values["includeVersions"],
        include_exports=True,
    )
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "archivePath": path,
            "fileCount": summary["files"],
            "sizeBytes": summary["size"],
            "skippedComputedFiles": len(summary.get("skipped", [])),
        },
        notes=[
            f"Compact .civil archive written to {path}; reproducible computed caches and results are omitted by the archive format."
        ],
    )


@feature(
    "exportsArchive.backupNow",
    "Backup Now",
    part="settings",
    fields=[
        text("label", "Backup label", "manual-backup"),
        checkbox("includeExports", "Include published deliverables", True),
    ],
)
def backup_now(ctx: FeatureContext, values: dict) -> dict:
    """Create an immediate timestamped native project archive as a local backup."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating a backup.")
    from datetime import datetime

    from saengine.project.archive import export_project

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    label = "".join(char for char in values["label"] if char.isalnum() or char in "-_") or "backup"
    target = output_path(ctx, f"{label}-{stamp}.civil", "Backups")
    data = export_project(ctx.root, target, include_exports=values["includeExports"])
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"backupPath": path, "fileCount": data["files"], "sizeBytes": data["size"]},
        notes=[f"Project backup created at {path}."],
    )


@feature(
    "exportsArchive.checksumTest",
    "Checksum Test",
    part="settings",
    fields=[text("file", "Project file relative path", "06 BIM/bim.json")],
)
def checksum_test(ctx: FeatureContext, values: dict) -> dict:
    """Calculate SHA-256 and file length for a selected project deliverable."""
    source = require_source(ctx, values["file"])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return result(
        summary={
            "relativePath": source.relative_to(ctx.root).as_posix(),
            "sizeBytes": source.stat().st_size,
            "sha256": digest,
        },
        notes=[
            "SHA-256 identifies the current file bytes; a trusted signature is a separate operation."
        ],
    )


@feature(
    "exportsArchive.fileHashSign",
    "File Hash Sign",
    part="settings",
    fields=[
        text("file", "File relative to project", "06 BIM/bim.json"),
        text("signingKey", "HMAC signing key", "replace-this-demo-key"),
        text("signatureName", "Signature record filename", "bim-signature.json"),
    ],
)
def file_hash_sign(ctx: FeatureContext, values: dict) -> dict:
    """Sign the selected file's SHA-256 digest with a user-supplied HMAC-SHA256 key."""
    if len(values["signingKey"].encode("utf-8")) < 16:
        raise FeatureInputError("Use a signing key of at least 16 UTF-8 bytes.")
    source = require_source(ctx, values["file"])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    signature = hmac.new(
        values["signingKey"].encode("utf-8"), digest.encode("ascii"), hashlib.sha256
    ).hexdigest()
    record = {
        "algorithm": "HMAC-SHA256 over SHA-256 digest",
        "file": source.relative_to(ctx.root).as_posix(),
        "sha256": digest,
        "signature": signature,
    }
    path = write_export_json(
        ctx, values["signatureName"].strip() or "file-signature.json", record, "Integrity"
    )
    return result(
        summary={"file": record["file"], "sha256": digest, "signaturePath": path},
        notes=[f"Signature record written to {path}; retain the HMAC key securely to verify it."],
    )


@feature(
    "exportsArchive.fileAudit",
    "File Audit",
    part="settings",
    fields=[
        text("expected", "Expected SHA-256", ""),
        text("file", "File relative to project", "06 BIM/bim.json"),
    ],
)
def file_audit(ctx: FeatureContext, values: dict) -> dict:
    """Compare current project file bytes with an expected SHA-256 digest."""
    source = require_source(ctx, values["file"])
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    expected = values["expected"].strip().casefold()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise FeatureInputError("Enter the expected SHA-256 as 64 hexadecimal characters.")
    return result(
        summary={
            "relativePath": source.relative_to(ctx.root).as_posix(),
            "sha256": actual,
            "matchesExpected": hmac.compare_digest(actual, expected),
            "sizeBytes": source.stat().st_size,
        },
        notes=[
            "A matching checksum establishes byte equality with the supplied digest, not who created it."
        ],
    )


@feature(
    "exportsArchive.syncCloud",
    "Sync Cloud",
    part="settings",
    fields=[
        text("provider", "Cloud provider", "Client storage"),
        text("remoteFolder", "Remote folder key", "project-archives"),
        text(
            "includePatterns",
            "Included project folders",
            "01 Soil Report,02 Project Settings,03 Materials,04 Objects,05 Floor Plan,06 BIM",
        ),
    ],
)
def sync_cloud(ctx: FeatureContext, values: dict) -> dict:
    """Create a checksummed cloud-transfer manifest for selected project files."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to prepare a cloud-transfer manifest.")
    selected = [
        item.strip().rstrip("/") for item in values["includePatterns"].split(",") if item.strip()
    ]
    files = []
    for relative in selected:
        folder = (ctx.root / relative).resolve()
        if ctx.root.resolve() not in folder.parents or not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                files.append(
                    {
                        "path": path.relative_to(ctx.root).as_posix(),
                        "sizeBytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
    manifest = {
        "provider": values["provider"],
        "remoteFolder": values["remoteFolder"],
        "files": files,
        "totalBytes": sum(row["sizeBytes"] for row in files),
    }
    path = write_export_json(ctx, "cloud-sync-manifest.json", manifest, "Cloud")
    return result(
        summary={
            "fileCount": len(files),
            "totalBytes": manifest["totalBytes"],
            "manifestPath": path,
        },
        tables=[
            table(
                "Transfer file list",
                [("path", "Project path"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256")],
                files,
            )
        ],
        notes=[
            f"Transfer manifest saved to {path}; no network upload is performed because this local feature runner has no cloud-provider connection."
        ],
    )


@feature(
    "exportsArchive.vaultStorage",
    "Vault Storage",
    part="settings",
    fields=[
        text("source", "Archive file relative path", "11 Exports/Archives/project-archive.civil"),
        text("vaultName", "Local vault copy name", "project-immutable-backup.civil"),
    ],
)
def vault_storage(ctx: FeatureContext, values: dict) -> dict:
    """Copy an archive to a separate local vault folder and mark the copy read-only."""
    source = require_source(ctx, values["source"])
    target = output_path(ctx, values["vaultName"].strip() or "vault-copy.civil", "Vault")
    shutil.copy2(source, target)
    target.chmod(target.stat().st_mode & ~0o222)
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "vaultCopy": path,
            "sizeBytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "readOnly": True,
        },
        notes=[
            "The local vault copy is marked read-only for the current filesystem user; administrator access and backups can still alter or remove it."
        ],
    )


@feature(
    "exportsArchive.revisionSnapshot",
    "Revision Snapshot",
    part="settings",
    fields=[
        text("label", "Milestone label", "Tender issue"),
        checkbox("includeExports", "Include issued deliverables", True),
    ],
)
def revision_snapshot(ctx: FeatureContext, values: dict) -> dict:
    """Create a named native project archive suitable as a milestone snapshot."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to create a revision snapshot.")
    from saengine.project.archive import export_project

    label = (
        "".join(char for char in values["label"] if char.isalnum() or char in "-_") or "snapshot"
    )
    target = output_path(ctx, f"{label}.civil", "Snapshots")
    summary = export_project(
        ctx.root,
        target,
        include_exports=values["includeExports"],
        note=f"Revision snapshot: {values['label']}",
    )
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "revisionLabel": values["label"],
            "snapshotPath": path,
            "fileCount": summary["files"],
            "sizeBytes": summary["size"],
        },
        notes=[
            f"Revision snapshot recorded as {path}; the current project version history is unchanged."
        ],
    )


@feature(
    "exportsArchive.clearCache",
    "Clear Cache",
    part="settings",
    fields=[checkbox("dryRun", "List only; do not delete", False)],
)
def clear_cache(ctx: FeatureContext, values: dict) -> dict:
    """Remove only recognized mesh, cloud and drawing cache folders under the project."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to inspect its calculation caches.")
    recognized = {
        ".mesh-cache",
        ".cloud-cache",
        ".dwg-cache",
        ".pdf-cache",
        "mesh-cache",
        "point-cache",
    }
    targets = [
        path
        for path in ctx.root.rglob("*")
        if path.is_dir() and path.name.casefold() in recognized and ".git" not in path.parts
    ]
    rows = [
        {
            "path": path.relative_to(ctx.root).as_posix(),
            "fileCount": sum(item.is_file() for item in path.rglob("*")),
        }
        for path in targets
    ]
    if not values["dryRun"]:
        for path in targets:
            shutil.rmtree(path)
    return result(
        summary={
            "cacheDirectoryCount": len(targets),
            "deleted": not values["dryRun"],
            "fileCount": sum(row["fileCount"] for row in rows),
        },
        tables=[
            table("Calculation caches", [("path", "Cache directory"), ("fileCount", "Files")], rows)
        ],
        notes=[
            "Only named temporary cache directories are considered; analysis result folders and project source data are retained."
        ],
    )


@feature(
    "exportsArchive.deleteTempFiles",
    "Delete Temp Files",
    part="settings",
    fields=[checkbox("dryRun", "List only; do not delete", False)],
)
def delete_temp_files(ctx: FeatureContext, values: dict) -> dict:
    """Remove temporary scratch files only from the project's FEM and study-output folders."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to inspect temporary files.")
    allowed = [
        (ctx.root / "08 FEM").resolve(),
        (ctx.root / "12 Automation/studies/outputs").resolve(),
    ]
    candidates = []
    for base in allowed:
        if base.is_dir():
            candidates.extend(
                path
                for path in base.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in (".tmp", ".temp", ".scratch")
                and base in path.resolve().parents
            )
    rows = [
        {"path": path.relative_to(ctx.root).as_posix(), "sizeBytes": path.stat().st_size}
        for path in candidates
    ]
    if not values["dryRun"]:
        for path in candidates:
            path.unlink(missing_ok=True)
    return result(
        summary={
            "temporaryFileCount": len(rows),
            "deleted": not values["dryRun"],
            "sizeBytes": sum(row["sizeBytes"] for row in rows),
        },
        tables=[
            table(
                "Temporary files", [("path", "Relative path"), ("sizeBytes", "Size", "byte")], rows
            )
        ],
        notes=[
            "Cleanup is restricted to .tmp, .temp and .scratch files under 08 FEM and study outputs."
        ],
    )


@feature(
    "exportsArchive.orphanRepair",
    "Orphan Repair",
    part="bim",
    fields=[
        text("referenceMap", "Missing type id to replacement id", "{}"),
        checkbox("dryRun", "Report only; do not edit BIM", True),
    ],
)
def orphan_repair(ctx: FeatureContext, values: dict) -> dict:
    """Repair BIM object-type references only when the user supplies an explicit replacement map."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to inspect BIM references.")
    try:
        mapping = json.loads(values["referenceMap"])
    except ValueError as error:
        raise FeatureInputError("The reference map must be valid JSON.") from error
    if not isinstance(mapping, dict):
        raise FeatureInputError("The reference map must be a JSON object.")
    bim, objects = ctx.raw("bim"), ctx.raw("objects")
    if not isinstance(bim, dict) or not isinstance(objects, dict):
        raise FeatureInputError("A valid BIM model and object library are required.")
    valid = {str(row.get("id")) for row in objects.get("objects", []) if isinstance(row, dict)}
    edits = []
    for element in bim.get("elements", []):
        old = str(element.get("type", ""))
        if old in mapping:
            new = str(mapping[old])
            if new not in valid:
                raise FeatureInputError(
                    f"Replacement object type '{new}' does not exist in the project library."
                )
            edits.append({"element": element.get("id"), "oldType": old, "newType": new})
    if edits and not values["dryRun"]:
        source = require_source(ctx, "06 BIM/bim.json")
        backup = source.with_suffix(".json.pre-orphan-repair.bak")
        if not backup.exists():
            shutil.copy2(source, backup)
        for element in bim.get("elements", []):
            element["type"] = mapping.get(str(element.get("type", "")), element.get("type"))
        source.write_text(json.dumps(bim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={
            "referenceCountRepaired": len(edits),
            "dryRun": values["dryRun"],
            "backupCreated": bool(edits and not values["dryRun"]),
        },
        tables=[
            table(
                "Type reference changes",
                [("element", "Element"), ("oldType", "Missing type"), ("newType", "Replacement")],
                edits,
            )
        ],
        notes=[
            "A backup is made before the BIM JSON is rewritten; only references named in the explicit map are changed."
        ],
    )


@feature(
    "exportsArchive.versionUpgrade",
    "Version Upgrade",
    part="settings",
    fields=[checkbox("apply", "Apply automatic project migrations", True)],
)
def version_upgrade(ctx: FeatureContext, values: dict) -> dict:
    """Inspect or apply SAEngine's built-in automatic project migrations."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to inspect its automatic migrations.")
    from saengine.project.archive import pending_migrations, run_migrations

    before = pending_migrations(ctx.root)
    migrated, problems = run_migrations(ctx.root) if values["apply"] else ([], [])
    after = pending_migrations(ctx.root)
    return result(
        summary={
            "pendingBefore": len(before),
            "migrationsApplied": len(migrated),
            "pendingAfter": len(after),
            "applied": values["apply"],
        },
        tables=[
            table(
                "Migrations applied",
                [("id", "Migration"), ("message", "Change"), ("count", "Records")],
                migrated,
            )
        ],
        notes=[row.get("message", "") for row in problems]
        + [row.get("message", "") for row in after],
    )


@feature(
    "exportsArchive.legacyConvert",
    "Legacy Convert",
    part="settings",
    fields=[
        text("source", "Legacy file relative to project", "legacy/records.csv"),
        text("output", "JSON output name", "converted-records.json"),
    ],
)
def legacy_convert(ctx: FeatureContext, values: dict) -> dict:
    """Convert a bounded legacy CSV or XML file into readable JSON records."""
    source = require_source(ctx, values["source"])
    if source.stat().st_size > 10 * 1024 * 1024:
        raise FeatureInputError("Legacy conversion is limited to files below 10 MB.")
    suffix = source.suffix.casefold()
    try:
        if suffix == ".csv":
            with source.open(encoding="utf-8-sig", newline="") as file:
                records = list(csv.DictReader(file))
        elif suffix == ".xml":
            import xml.etree.ElementTree as ET

            root = ET.parse(source).getroot()
            records = [
                {child.tag: child.text for child in element} for element in root if list(element)
            ]
        elif suffix == ".json":
            records = json.loads(source.read_text(encoding="utf-8-sig"))
        else:
            raise FeatureInputError("Choose a legacy CSV, XML or JSON file.")
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Legacy file could not be parsed: {error}") from error
    path = write_export_json(
        ctx,
        values["output"].strip() or "converted-records.json",
        {"source": source.relative_to(ctx.root).as_posix(), "records": records},
        "Migration",
    )
    count = len(records) if isinstance(records, list) else 1
    return result(
        summary={"convertedRecords": count, "outputPath": path},
        notes=[f"Converted data saved to {path}; source file remains unchanged."],
    )


@feature(
    "exportsArchive.schemaMigration",
    "Schema Migration",
    part="settings",
    fields=[
        text("source", "JSON file relative to project", "04 Objects/objects.json"),
        text("renames", "Old key to new key JSON", '{"legacyName":"name"}'),
        text("output", "Migrated JSON filename", "objects-migrated.json"),
    ],
)
def schema_migration(ctx: FeatureContext, values: dict) -> dict:
    """Apply explicit JSON key renames recursively and write a separate migrated copy."""
    source = require_source(ctx, values["source"])
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        renames = json.loads(values["renames"])
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The source or rename map is not valid JSON: {error}") from error
    if not isinstance(renames, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in renames.items()
    ):
        raise FeatureInputError("Renames must be a JSON object of old and new property names.")
    counts = {key: 0 for key in renames}

    def rename(node: Any) -> Any:
        if isinstance(node, list):
            return [rename(item) for item in node]
        if isinstance(node, dict):
            result = {}
            for key, value in node.items():
                target = renames.get(key, key)
                if target in result:
                    raise FeatureInputError(f"Key rename collision at '{target}'.")
                if key in counts:
                    counts[key] += 1
                result[target] = rename(value)
            return result
        return node

    migrated = rename(data)
    path = write_export_json(
        ctx, values["output"].strip() or f"{source.stem}-migrated.json", migrated, "Migration"
    )
    return result(
        summary={"renamedProperties": sum(counts.values()), "outputPath": path},
        tables=[
            table(
                "Property rename counts",
                [("oldKey", "Old key"), ("newKey", "New key"), ("occurrences", "Occurrences")],
                [
                    {"oldKey": old, "newKey": new, "occurrences": counts[old]}
                    for old, new in renames.items()
                ],
            )
        ],
        notes=["The source file is preserved; only explicitly named JSON object keys are changed."],
    )
