"""Exports Batch Export - configure, execute and audit repeatable export queues."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
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
    output_path,
    project_file_rows,
    require_source,
    write_export_json,
)


def _queue_path(ctx: FeatureContext) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project to manage its batch export queue.")
    return output_path(ctx, "batch-queue.json", "Batch")


def _load_queue(ctx: FeatureContext) -> tuple[Path, list[dict]]:
    path = _queue_path(ctx)
    try:
        jobs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError as error:
        raise FeatureInputError("Batch queue file is not valid JSON.") from error
    if not isinstance(jobs, list) or any(not isinstance(row, dict) for row in jobs):
        raise FeatureInputError("Batch queue must be a JSON array of job objects.")
    return path, jobs


def _save_queue(ctx: FeatureContext, path: Path, jobs: list[dict]) -> str:
    path.write_text(json.dumps(jobs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path.relative_to(ctx.root).as_posix()


@feature(
    "exportsBatchExport.addJob",
    "Add Job",
    part="settings",
    fields=[
        text("source", "Project file", "06 BIM/bim.json"),
        text("name", "Job name", "Export BIM model"),
        text("output", "Output filename", "bim-copy.json"),
    ],
)
def add_job(ctx: FeatureContext, values: dict) -> dict:
    """Append an explicit source-to-output file-copy job to the project queue."""
    source = require_source(ctx, values["source"])
    if not values["name"].strip() or not values["output"].strip():
        raise FeatureInputError("Enter a job name and output filename.")
    path, jobs = _load_queue(ctx)
    jobs.append(
        {
            "id": hashlib.sha1(
                f"{source}:{len(jobs)}:{datetime.now(UTC).isoformat()}".encode()
            ).hexdigest()[:12],
            "name": values["name"].strip(),
            "source": source.relative_to(ctx.root).as_posix(),
            "output": values["output"].strip(),
            "enabled": True,
        }
    )
    return result(
        summary={"jobCount": len(jobs), "queuePath": _save_queue(ctx, path, jobs)},
        tables=[
            table(
                "Batch jobs",
                [("id", "ID"), ("name", "Name"), ("source", "Source"), ("output", "Output")],
                jobs,
            )
        ],
    )


@feature(
    "exportsBatchExport.reorderJobs",
    "Reorder Jobs",
    part="settings",
    fields=[text("jobIds", "Job IDs in desired order, comma separated", "")],
)
def reorder_jobs(ctx: FeatureContext, values: dict) -> dict:
    """Reorder jobs only when the supplied identifiers cover the queue exactly once."""
    path, jobs = _load_queue(ctx)
    ids = [item.strip() for item in values["jobIds"].split(",") if item.strip()]
    if len(ids) != len(jobs) or set(ids) != {str(job.get("id")) for job in jobs}:
        raise FeatureInputError("Provide every queue job ID exactly once in the desired order.")
    by_id = {str(job["id"]): job for job in jobs}
    ordered = [by_id[key] for key in ids]
    return result(
        summary={"jobCount": len(ordered), "queuePath": _save_queue(ctx, path, ordered)},
        tables=[
            table(
                "Execution order",
                [("position", "Position"), ("id", "Job ID"), ("name", "Name")],
                [
                    {"position": i + 1, "id": job["id"], "name": job["name"]}
                    for i, job in enumerate(ordered)
                ],
            )
        ],
    )


@feature(
    "exportsBatchExport.removeJob",
    "Remove Job",
    part="settings",
    fields=[text("jobId", "Job ID", "")],
)
def remove_job(ctx: FeatureContext, values: dict) -> dict:
    """Remove one explicitly identified batch job while preserving all remaining order."""
    path, jobs = _load_queue(ctx)
    remaining = [job for job in jobs if str(job.get("id")) != values["jobId"].strip()]
    if len(remaining) == len(jobs):
        raise FeatureInputError("No queued job matches that ID.")
    return result(
        summary={
            "removed": len(jobs) - len(remaining),
            "jobCount": len(remaining),
            "queuePath": _save_queue(ctx, path, remaining),
        }
    )


@feature(
    "exportsBatchExport.clearQueue",
    "Clear Queue",
    part="settings",
    fields=[checkbox("confirm", "Confirm removal of all queued jobs", False)],
)
def clear_queue(ctx: FeatureContext, values: dict) -> dict:
    """Clear the local job queue only after the user confirms the destructive action."""
    if not values["confirm"]:
        raise FeatureInputError("Enable confirmation to clear queued jobs.")
    path, jobs = _load_queue(ctx)
    relative = _save_queue(ctx, path, [])
    return result(summary={"removedJobs": len(jobs), "queuePath": relative})


@feature(
    "exportsBatchExport.fileNaming",
    "File Naming",
    part="settings",
    fields=[
        text(
            "template", "Filename template using {name}, {date}, {index}", "{name}_{date}_{index}"
        ),
        text("names", "Job names, one per line", "BIM model\nBOQ"),
    ],
)
def file_naming(ctx: FeatureContext, values: dict) -> dict:
    """Expand safe filename tokens into deterministic output filenames."""
    template = values["template"].strip()
    names = [name.strip() for name in values["names"].splitlines() if name.strip()]
    day = datetime.now(UTC).strftime("%Y%m%d")
    rows = []
    for index, name in enumerate(names, 1):
        rendered = template.format(
            name=re.sub(r"[^A-Za-z0-9._-]+", "_", name), date=day, index=index
        )
        rows.append(
            {"jobName": name, "filename": re.sub(r"[^A-Za-z0-9._-]+", "_", rendered).strip("._")}
        )
    return result(
        summary={"filenameCount": len(rows), "dateToken": day},
        tables=[table("Generated names", [("jobName", "Job"), ("filename", "Filename")], rows)],
    )


@feature(
    "exportsBatchExport.folderRules",
    "Folder Rules",
    part="settings",
    fields=[
        text("rules", "Extension to folder map JSON", '{".pdf":"PDF",".ifc":"BIM",".csv":"Tables"}')
    ],
)
def folder_rules(ctx: FeatureContext, values: dict) -> dict:
    """Validate extension-based folder rules and apply them to the current queued jobs."""
    try:
        rules = json.loads(values["rules"])
    except ValueError as error:
        raise FeatureInputError("Folder rules must be valid JSON.") from error
    if not isinstance(rules, dict) or any(
        not str(k).startswith(".") or not isinstance(v, str) for k, v in rules.items()
    ):
        raise FeatureInputError("Rules must map file extensions such as .pdf to folder names.")
    path, jobs = _load_queue(ctx)
    for job in jobs:
        job["folder"] = rules.get(Path(job["output"]).suffix.casefold(), "Other")
    relative = _save_queue(ctx, path, jobs)
    return result(
        summary={"jobCount": len(jobs), "ruleCount": len(rules), "queuePath": relative},
        tables=[
            table(
                "Routed jobs", [("name", "Job"), ("output", "Filename"), ("folder", "Folder")], jobs
            )
        ],
    )


@feature(
    "exportsBatchExport.overwritePolicy",
    "Overwrite Policy",
    part="settings",
    fields=[
        select(
            "policy",
            "Existing output policy",
            [
                ("skip", "Skip existing"),
                ("replace", "Replace existing"),
                ("error", "Stop on existing"),
            ],
        )
    ],
)
def overwrite_policy(ctx: FeatureContext, values: dict) -> dict:
    """Store the overwrite decision used by later batch runs."""
    _, jobs = _load_queue(ctx)
    config_path = output_path(ctx, "batch-settings.json", "Batch")
    settings = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    settings["overwritePolicy"] = values["policy"]
    config_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return result(
        summary={
            "policy": values["policy"],
            "settingsPath": config_path.relative_to(ctx.root).as_posix(),
            "queuedJobs": len(jobs),
        }
    )


@feature(
    "exportsBatchExport.versionSuffix",
    "Version Suffix",
    part="settings",
    fields=[text("suffix", "Suffix", "_v001")],
)
def version_suffix(ctx: FeatureContext, values: dict) -> dict:
    """Add a version suffix before each queued output extension."""
    if not values["suffix"].strip() or any(char in values["suffix"] for char in '\\/:*?"<>|'):
        raise FeatureInputError("Enter a nonempty suffix without filename path characters.")
    path, jobs = _load_queue(ctx)
    for job in jobs:
        output = Path(job["output"])
        job["output"] = output.with_name(output.stem + values["suffix"] + output.suffix).as_posix()
    return result(summary={"updatedJobs": len(jobs), "queuePath": _save_queue(ctx, path, jobs)})


def _run_jobs(ctx: FeatureContext, jobs: list[dict]) -> list[dict]:
    if ctx.root is None:
        raise FeatureInputError("Open a project to run batch exports.")
    config = output_path(ctx, "batch-settings.json", "Batch")
    settings = (
        json.loads(config.read_text(encoding="utf-8"))
        if config.exists()
        else {"overwritePolicy": "skip"}
    )
    policy = settings.get("overwritePolicy", "skip")
    rows = []
    for job in jobs:
        source = require_source(ctx, str(job.get("source", "")))
        folder = str(job.get("folder", ""))
        relative = (
            Path("11 Exports")
            / "Batch Output"
            / folder
            / Path(str(job.get("output", source.name))).name
        )
        target = (ctx.root / relative).resolve()
        batch_root = (ctx.root / "11 Exports" / "Batch Output").resolve()
        if batch_root not in target.parents:
            raise FeatureInputError("Batch output path escapes the export folder.")
        if target.exists() and policy == "error":
            raise FeatureInputError(
                f"Output already exists and stop-on-existing is set: {relative}"
            )
        if target.exists() and policy == "skip":
            rows.append(
                {"job": job.get("name"), "output": relative.as_posix(), "status": "skipped"}
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rows.append(
            {
                "job": job.get("name"),
                "output": relative.as_posix(),
                "status": "written",
                "sizeBytes": target.stat().st_size,
            }
        )
    return rows


@feature(
    "exportsBatchExport.runNow",
    "Run Now",
    part="settings",
    fields=[text("jobIds", "Run these job IDs (blank means enabled jobs)", "")],
)
def run_now(ctx: FeatureContext, values: dict) -> dict:
    """Execute enabled queue jobs as byte-preserving copies using the saved overwrite policy."""
    _, jobs = _load_queue(ctx)
    selected = {item.strip() for item in values["jobIds"].split(",") if item.strip()}
    chosen = [
        job
        for job in jobs
        if job.get("enabled", True) and (not selected or str(job.get("id")) in selected)
    ]
    if selected and len(chosen) != len(selected):
        raise FeatureInputError("One or more requested job IDs are not enabled in the queue.")
    rows = _run_jobs(ctx, chosen)
    history = output_path(ctx, "job-history.json", "Batch")
    existing = json.loads(history.read_text(encoding="utf-8")) if history.exists() else []
    existing.append({"completedUtc": datetime.now(UTC).isoformat(), "results": rows})
    history.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return result(
        summary={
            "jobsRun": len(rows),
            "written": sum(row["status"] == "written" for row in rows),
            "historyPath": history.relative_to(ctx.root).as_posix(),
        },
        tables=[
            table(
                "Batch results",
                [
                    ("job", "Job"),
                    ("output", "Output"),
                    ("status", "Status"),
                    ("sizeBytes", "Bytes", "byte"),
                ],
                rows,
            )
        ],
    )


@feature(
    "exportsBatchExport.scheduleBatch",
    "Schedule Batch",
    part="settings",
    fields=[
        text("runAt", "Scheduled time (ISO 8601 with timezone)", ""),
        checkbox("enabled", "Enable schedule", False),
    ],
)
def schedule_batch(ctx: FeatureContext, values: dict) -> dict:
    """Validate and save a timezone-aware schedule request for an external task runner."""
    try:
        scheduled = datetime.fromisoformat(values["runAt"])
    except ValueError as error:
        raise FeatureInputError("Enter a valid ISO 8601 date and time.") from error
    if scheduled.tzinfo is None:
        raise FeatureInputError("Include an explicit timezone offset.")
    _, jobs = _load_queue(ctx)
    path = write_export_json(
        ctx,
        "batch-schedule.json",
        {
            "runAt": scheduled.astimezone(UTC).isoformat(),
            "enabled": values["enabled"],
            "jobIds": [job.get("id") for job in jobs if job.get("enabled", True)],
            "requiresExternalScheduler": True,
        },
        "Batch",
    )
    return result(
        summary={"schedulePath": path, "jobCount": len(jobs), "enabled": values["enabled"]},
        notes=["This records a schedule; the application does not install a background task."],
    )


@feature(
    "exportsBatchExport.notifyOnFinish",
    "Notify on Finish",
    part="settings",
    fields=[
        text("email", "Notification address", ""),
        checkbox("onSuccess", "Notify on success", True),
        checkbox("onFailure", "Notify on failure", True),
    ],
)
def notify_on_finish(ctx: FeatureContext, values: dict) -> dict:
    """Save queue notification preferences for the external batch runner."""
    if values["email"] and ("@" not in values["email"] or " " in values["email"]):
        raise FeatureInputError("Enter a valid notification address or leave it blank.")
    path = write_export_json(
        ctx,
        "batch-notifications.json",
        {
            "email": values["email"].strip(),
            "onSuccess": values["onSuccess"],
            "onFailure": values["onFailure"],
            "delivery": "external-runner",
        },
        "Batch",
    )
    return result(
        summary={"preferencesPath": path, "configured": bool(values["email"])},
        notes=["Email delivery is performed by an external runner with configured mail access."],
    )


@feature("exportsBatchExport.jobHistory", "Job History", part="settings", fields=[])
def job_history(ctx: FeatureContext, values: dict) -> dict:
    """Read prior batch execution records and summarize success and skip counts."""
    path = output_path(ctx, "job-history.json", "Batch")
    try:
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError as error:
        raise FeatureInputError("Batch job history is not valid JSON.") from error
    rows = [
        {
            "completedUtc": entry.get("completedUtc"),
            "jobs": len(entry.get("results", [])),
            "written": sum(row.get("status") == "written" for row in entry.get("results", [])),
            "skipped": sum(row.get("status") == "skipped" for row in entry.get("results", [])),
        }
        for entry in entries
    ]
    return result(
        summary={"runCount": len(rows), "historyPath": path.relative_to(ctx.root).as_posix()},
        tables=[
            table(
                "Batch runs",
                [
                    ("completedUtc", "Completed"),
                    ("jobs", "Jobs"),
                    ("written", "Written"),
                    ("skipped", "Skipped"),
                ],
                rows,
            )
        ],
    )


@feature(
    "exportsBatchExport.presetManager",
    "Preset Manager",
    part="settings",
    fields=[
        text("name", "Preset name", "BIM issue"),
        text("extensions", "Allowed output extensions, comma separated", ".ifc,.json,.csv"),
    ],
)
def preset_manager(ctx: FeatureContext, values: dict) -> dict:
    """Save or update a named batch preset with validated extension filters."""
    extensions = [
        item.strip().casefold() for item in values["extensions"].split(",") if item.strip()
    ]
    if not values["name"].strip() or any(not item.startswith(".") for item in extensions):
        raise FeatureInputError("Provide a preset name and extensions beginning with a dot.")
    path = output_path(ctx, "batch-presets.json", "Batch")
    try:
        presets = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as error:
        raise FeatureInputError("Preset file is not valid JSON.") from error
    presets[values["name"].strip()] = {
        "extensions": extensions,
        "updatedUtc": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(presets, indent=2) + "\n", encoding="utf-8")
    return result(
        summary={"presetCount": len(presets), "presetPath": path.relative_to(ctx.root).as_posix()},
        tables=[
            table(
                "Presets",
                [("name", "Preset"), ("extensions", "Extensions")],
                [
                    {"name": name, "extensions": ", ".join(data["extensions"])}
                    for name, data in presets.items()
                ],
            )
        ],
    )


@feature(
    "exportsBatchExport.pdfGrouping",
    "PDF Grouping",
    part="settings",
    fields=[
        text("files", "PDF files, one per line", ""),
        text("group", "Group name", "combined-issue"),
    ],
)
def pdf_grouping(ctx: FeatureContext, values: dict) -> dict:
    """Combine selected PDF pages in order using pypdf and report page boundaries."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as error:
        raise FeatureInputError("Install pypdf to group PDF files.") from error
    paths = [
        require_source(ctx, name.strip()) for name in values["files"].splitlines() if name.strip()
    ]
    if not paths or any(path.suffix.casefold() != ".pdf" for path in paths):
        raise FeatureInputError("Select one or more existing PDF files, one per line.")
    writer, rows = PdfWriter(), []
    for path in paths:
        reader = PdfReader(str(path))
        first = len(writer.pages) + 1
        for page in reader.pages:
            writer.add_page(page)
        rows.append(
            {
                "source": path.relative_to(ctx.root).as_posix(),
                "pages": len(reader.pages),
                "firstOutputPage": first,
            }
        )
    target = output_path(ctx, (values["group"].strip() or "grouped") + ".pdf", "Batch Output")
    with target.open("wb") as stream:
        writer.write(stream)
    return result(
        summary={
            "outputPath": target.relative_to(ctx.root).as_posix(),
            "pageCount": len(writer.pages),
        },
        tables=[
            table(
                "PDF page groups",
                [("source", "Source"), ("pages", "Pages"), ("firstOutputPage", "First page")],
                rows,
            )
        ],
    )


@feature(
    "exportsBatchExport.dwgSettings",
    "DWG Settings",
    part="settings",
    fields=[
        select("version", "Target version", [("2018", "2018"), ("2013", "2013"), ("2010", "2010")]),
        select("units", "Drawing units", [("mm", "Millimetres"), ("m", "Metres"), ("ft", "Feet")]),
    ],
)
def dwg_settings(ctx: FeatureContext, values: dict) -> dict:
    """Save drawing interchange settings for CAD jobs that use a configured converter."""
    path = write_export_json(
        ctx,
        "dwg-settings.json",
        {"targetVersion": values["version"], "units": values["units"], "converterRequired": True},
        "Batch",
    )
    return result(
        summary={
            "settingsPath": path,
            "targetVersion": values["version"],
            "units": values["units"],
        },
        notes=[
            "A licensed DWG converter is required to produce DWG bytes; these settings do not relabel DXF output."
        ],
    )


@feature(
    "exportsBatchExport.ifcExportSetup",
    "IFC Export Setup",
    part="bim",
    fields=[
        select("schema", "IFC schema", [("IFC4", "IFC 4"), ("IFC2X3", "IFC 2x3")]),
        checkbox("includeProperties", "Include element properties", True),
    ],
)
def ifc_export_setup(ctx: FeatureContext, values: dict) -> dict:
    """Validate BIM presence and store IFC schema/export property settings."""
    from saengine.features.exports_common import model_elements

    elements = model_elements(ctx)
    path = write_export_json(
        ctx,
        "ifc-export-settings.json",
        {
            "schema": values["schema"],
            "includeProperties": values["includeProperties"],
            "elementCountAtSetup": len(elements),
        },
        "Batch",
    )
    return result(
        summary={"settingsPath": path, "schema": values["schema"], "elementCount": len(elements)}
    )


@feature(
    "exportsBatchExport.compressOutput",
    "Compress Output",
    part="settings",
    fields=[
        text("folder", "Export folder relative to project", "11 Exports/Batch Output"),
        number("level", "Deflate level", 6, min=0, max=9),
    ],
)
def compress_output(ctx: FeatureContext, values: dict) -> dict:
    """Compress an export folder to ZIP while preserving relative member paths."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to compress batch outputs.")
    folder = (ctx.root / values["folder"]).resolve()
    if ctx.root.resolve() not in folder.parents or not folder.is_dir():
        raise FeatureInputError("Choose an existing folder below the project root.")
    import zipfile

    target = output_path(ctx, "batch-output.zip", "Batch")
    files = [p for p in folder.rglob("*") if p.is_file() and p.resolve() != target]
    with zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED, compresslevel=int(values["level"])
    ) as archive:
        for path in files:
            archive.write(path, path.relative_to(folder).as_posix())
    return result(
        summary={
            "archivePath": target.relative_to(ctx.root).as_posix(),
            "fileCount": len(files),
            "zipBytes": target.stat().st_size,
        }
    )


@feature(
    "exportsBatchExport.watermarkBatch",
    "Watermark Batch",
    part="settings",
    fields=[
        text("files", "Text files, one per line", ""),
        text("label", "Watermark label", "PRELIMINARY"),
        checkbox("dryRun", "Preview only", True),
    ],
)
def watermark_batch(ctx: FeatureContext, values: dict) -> dict:
    """Add an explicit footer line to selected text deliverables, preserving backups."""
    paths = [
        require_source(ctx, name.strip()) for name in values["files"].splitlines() if name.strip()
    ]
    if not paths or any(
        path.suffix.casefold() not in (".txt", ".csv", ".md", ".json") for path in paths
    ):
        raise FeatureInputError(
            "Select one or more text-based deliverables (.txt, .csv, .md or .json)."
        )
    rows = []
    for path in paths:
        if path.stat().st_size > 20 * 1024 * 1024:
            raise FeatureInputError(f"Selected file is larger than 20 MB: {path.name}")
        data = path.read_text(encoding="utf-8")
        rows.append(
            {
                "path": path.relative_to(ctx.root).as_posix(),
                "bytes": len(data.encode()),
                "changed": not values["dryRun"],
            }
        )
        if not values["dryRun"]:
            backup = path.with_suffix(path.suffix + ".pre-watermark.bak")
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(
                data.rstrip() + f"\n\n[Publication label: {values['label']}]\n", encoding="utf-8"
            )
    return result(
        summary={"fileCount": len(rows), "dryRun": values["dryRun"]},
        tables=[
            table(
                "Watermark targets",
                [("path", "File"), ("bytes", "Bytes"), ("changed", "Changed")],
                rows,
            )
        ],
        notes=[
            "Original files are backed up once before modification; structured JSON should be treated as text and may no longer parse after appending a footer."
        ],
    )


@feature(
    "exportsBatchExport.scriptExecution",
    "Script Execution",
    part="settings",
    fields=[
        text("script", "Project-relative Python script", "scripts/export_job.py"),
        checkbox("allowExecution", "Run this trusted project script", False),
    ],
)
def script_execution(ctx: FeatureContext, values: dict) -> dict:
    """Run one explicitly approved project-local Python script with the project as working directory."""
    source = require_source(ctx, values["script"])
    if source.suffix.casefold() != ".py":
        raise FeatureInputError("Only Python scripts are supported.")
    if not values["allowExecution"]:
        raise FeatureInputError(
            "Enable the run confirmation after reviewing the selected project script."
        )
    if source.stat().st_size > 2 * 1024 * 1024:
        raise FeatureInputError("Script execution is limited to scripts below 2 MB.")
    completed = subprocess.run(
        [sys.executable, str(source)],
        cwd=ctx.root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result(
        summary={
            "script": source.relative_to(ctx.root).as_posix(),
            "returnCode": completed.returncode,
            "stdout": completed.stdout[-8000:],
            "stderr": completed.stderr[-8000:],
        },
        notes=[
            "Project scripts run with the current user's permissions; review their contents before enabling execution."
        ],
    )


@feature("exportsBatchExport.exportMonitor", "Export Monitor", part="settings", fields=[])
def export_monitor(ctx: FeatureContext, values: dict) -> dict:
    """Summarize queued jobs, recent run status and output-folder size."""
    _, jobs = _load_queue(ctx)
    history_path = output_path(ctx, "job-history.json", "Batch")
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    files = project_file_rows(ctx)
    outputs = [row for row in files if row["path"].startswith("11 Exports/Batch Output/")]
    return result(
        summary={
            "queuedJobs": len(jobs),
            "enabledJobs": sum(job.get("enabled", True) for job in jobs),
            "completedRuns": len(history),
            "outputFiles": len(outputs),
            "outputBytes": sum(row["sizeBytes"] for row in outputs),
        },
        tables=[
            table(
                "Recent runs",
                [("completedUtc", "Completed"), ("jobCount", "Jobs")],
                [
                    {
                        "completedUtc": row.get("completedUtc"),
                        "jobCount": len(row.get("results", [])),
                    }
                    for row in history[-10:]
                ],
            )
        ],
    )


@feature(
    "exportsBatchExport.errorRecovery",
    "Error Recovery",
    part="settings",
    fields=[checkbox("retryFailed", "Retry jobs marked failed", True)],
)
def error_recovery(ctx: FeatureContext, values: dict) -> dict:
    """Inspect the latest run and retry only failed entries that still have an explicit source job."""
    history_path = output_path(ctx, "job-history.json", "Batch")
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    if not history:
        raise FeatureInputError("There is no batch run history to recover.")
    last = history[-1]
    failed = [
        row for row in last.get("results", []) if row.get("status") == "failed" and row.get("jobId")
    ]
    if values["retryFailed"] and failed:
        _, jobs = _load_queue(ctx)
        ids = {row["jobId"] for row in failed}
        retry = [job for job in jobs if str(job.get("id")) in ids]
        rows = _run_jobs(ctx, retry)
    else:
        rows = []
    return result(
        summary={"failedPreviously": len(failed), "retried": len(rows)},
        tables=[
            table(
                "Recovery results",
                [("job", "Job"), ("output", "Output"), ("status", "Status")],
                rows,
            )
        ],
        notes=[
            "The batch runner currently records interrupted jobs only when a completed run history entry exists."
        ],
    )
