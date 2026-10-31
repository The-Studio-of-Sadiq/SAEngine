"""The project archive: a whole SAEngine project in one ``.civil`` file, to send or keep.

A ``.civil`` file is a zip (deflate) with ``manifest.json`` at its root and the project's files
under ``project/<path relative to the project root>``. The manifest records the format
(:data:`FORMAT`), the SAEngine version that wrote it, when, the project, and for each part its
folder and files (size, SHA-256, modification time, the ``schema`` field of a JSON file); files
outside the part folders (the ``.saengine`` file, ``.gitignore``, ``.git`` ...) are listed under
``files``. An archive is a snapshot, not a validation: placeholders, missing parts and invalid
JSON files are archived as they are and noted in ``problems``.

The computed caches (:data:`COMPUTED_PATHS`: the analysis model derived from the building model,
the results folders and the summaries the sidebar reads) are left out unless asked for: SAEngine
regenerates them. The deliverables of ``11 Exports`` are included by default, the version
history (``.git``) only on request. Editor settings (``.vscode`` and the like,
:data:`EDITOR_SETTINGS_FOLDERS`) are never archived nor extracted.

:func:`export_project` writes an archive, :func:`inspect_archive` reads and checks one without
extracting it, :func:`import_project` extracts one safely into a new project folder.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
import zlib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import saengine
from saengine.library.substructure import is_placeholder as is_substructure_placeholder

#: The format written by this module: ``<name>/<major version>``.
FORMAT_NAME = "saengine.civil"
FORMAT_VERSION = 1
FORMAT = f"{FORMAT_NAME}/{FORMAT_VERSION}"
#: The archive's file extension.
EXTENSION = ".civil"
#: The manifest's name at the archive's root.
MANIFEST_NAME = "manifest.json"
#: The prefix of the project's files in the archive.
PROJECT_PREFIX = "project/"
#: The project manifest's extension.
PROJECT_EXTENSION = ".saengine"

#: The computed caches of a project, which SAEngine regenerates from its sources: glob patterns
#: relative to the project root, ``/``-separated, matched case-insensitively. ``*`` and ``?``
#: match within one path segment, ``**`` any number of segments; a trailing ``/`` names a folder
#: (everything under it). Every pattern contains a ``/``, so the list is also valid
#: ``.gitignore`` syntax (anchored at the project root), which the version history uses.
COMPUTED_PATHS: tuple[str, ...] = (
    # 8 FEM: the analysis models derived from the building model (saengine.fem.derive), the
    # pushover model, the fixed-base model of the soil-spring comparison (fem.ssi_compare) ...
    "08 FEM/*.osmodel",
    # ... their side files: the temperature case's fixed-end forces (fem.thermal), the column
    # bases' soil springs (fem.ssi) and the fixed-base comparison (fem.ssi_compare) ...
    "08 FEM/thermal.json",
    "08 FEM/ssi.json",
    "08 FEM/ssi-compare.json",
    # ... and the analysis results with the design checks' summary (design-summary.json).
    "08 FEM/*.results/",
    # 7 MEP: the coordination summary, the tank designs and their models (plumbing.project),
    # the EnergyPlus loads (hvac.report).
    "07 MEP/mep.results/",
    "07 MEP/hvac.results/",
    # 9 Substructure: the foundation checks' summary.
    "09 Substructure/substructure.results/",
    # Any other results folder of an OpenSees Studio run (``<model>.results``).
    "**/*.results/",
    # The DXF copies of DWG drawings (underlays), converted again from the DWG when missing
    # (saengine.library.dwg).
    "**/.dwg-cache/",
    # ... and of PDF pages (saengine.library.pdf_underlay).
    "**/.pdf-cache/",
)

#: The deliverables folder (report PDF, IFC, DXF, CSV), included unless ``include_exports`` is
#: false.
EXPORTS_FOLDER = "11 Exports"
#: The version history, included only with ``include_versions``.
VERSIONS_FOLDER = ".git"
#: Parts of an archived ``.git`` folder that are never extracted, because git would run or
#: follow what they say (hooks, other repositories' settings, links to other folders). Its
#: ``config`` is replaced by :data:`SAFE_GIT_CONFIG` (a received config could name a program,
#: e.g. ``core.fsmonitor``, that git runs as soon as it opens the project).
GIT_DROPPED: tuple[str, ...] = (
    ".git/hooks/",
    ".git/modules/",
    ".git/worktrees/",
    ".git/commondir",
    ".git/config.worktree",
    ".git/objects/info/alternates",
    ".git/objects/info/http-alternates",
)
#: The ``.git/config`` an imported version history gets: only what git needs to read it.
SAFE_GIT_CONFIG = (
    "[core]\n"
    "\trepositoryformatversion = {version}\n"
    "\tfilemode = false\n"
    "\tbare = false\n"
    "\tlogallrefupdates = true\n"
    "\tsymlinks = false\n"
    "\tignorecase = true\n"
)

#: Editor and IDE settings folders (any depth, any spelling Windows takes for the same folder):
#: never archived, never extracted, never restored from a version. A received
#: ``.vscode/settings.json`` could name a program that SAEngine or an editor starts as soon as
#: the project is opened (an interpreter, a language server, a formatter).
EDITOR_SETTINGS_FOLDERS: tuple[str, ...] = (
    ".vscode",
    ".vs",
    ".idea",
    ".devcontainer",
    ".fleet",
    ".theia",
    ".zed",
)
_EDITOR_FOLDERS = frozenset(f.casefold() for f in EDITOR_SETTINGS_FOLDERS)
# A Windows 8.3 short name ("VSCODE~1", "DEVCON~1"), which can reach an existing long-named
# folder of the destination.
_SHORT_NAME = re.compile(r"^(?P<base>[^~.]{1,6})~\d+(?:\.[^.]{0,3})?$")

#: File names never archived: operating-system and editor droppings, and other archives.
JUNK_PATTERNS: tuple[str, ...] = ("thumbs.db", "desktop.ini", ".ds_store", "~$*", "*.civil")

#: The parts of a project: id -> (folder, main file). Mirrors ``PROJECT_PARTS`` and
#: ``STRUCTURE_PART`` of the workbench's ``services/saengineProject/common/saengineProject.ts``.
PARTS: dict[str, tuple[str, str | None]] = {
    "soil": ("01 Soil Report", "soil-report.json"),
    "settings": ("02 Project Settings", "project-settings.json"),
    "materials": ("03 Materials", "materials.json"),
    "objects": ("04 Objects", "objects.json"),
    "floorPlan": ("05 Floor Plan", "floor-plan.json"),
    "structure": ("05 Structural Model", "structure.json"),
    "bim": ("06 BIM", "bim.json"),
    "mep": ("07 MEP", "mep.json"),
    "fem": ("08 FEM", "model.osmodel"),
    "substructure": ("09 Substructure", "substructure.json"),
    "boq": ("10 BOQ", "boq.json"),
    "exports": ("11 Exports", None),
}
#: The parts of a building project, in workflow order (a special structure has ``structure``
#: instead of ``floorPlan``).
BUILDING_PARTS: tuple[str, ...] = (
    "soil",
    "settings",
    "materials",
    "objects",
    "floorPlan",
    "bim",
    "mep",
    "fem",
    "substructure",
    "boq",
    "exports",
)

#: Refuse archives larger than this once extracted [bytes].
MAX_UNCOMPRESSED = 2 * 1024**3
#: Refuse an entry that inflates more than this many times ...
MAX_RATIO = 200
#: ... once it is larger than this [bytes] (small, very regular files compress well legitimately).
RATIO_MIN_SIZE = 1024**2
#: Refuse archives with more entries than this.
MAX_ENTRIES = 200_000
#: JSON files larger than this are archived without reading their ``schema`` field [bytes].
JSON_READ_LIMIT = 64 * 1024**2

_CHUNK = 1024 * 1024
_JSON_SUFFIXES = (".json", PROJECT_EXTENSION, ".osmodel")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.IGNORECASE)
_FORBIDDEN = re.compile(r'[<>:"|?*\\\x00-\x1f]')
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class ArchiveError(ValueError):
    """An archive that cannot be written or imported; ``problems`` says why."""

    def __init__(self, message: str, problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


# --- Paths -------------------------------------------------------------------------------------


def _glob_regex(pattern: str) -> re.Pattern[str]:
    directory = pattern.endswith("/")
    segments = pattern.strip("/").split("/")
    regex = ""
    for index, segment in enumerate(segments):
        if segment == "**":
            regex += "(?:[^/]+/)*"
            continue
        part = "".join(
            "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in segment
        )
        regex += part + ("/" if index < len(segments) - 1 else "")
    return re.compile("^" + regex + ("/" if directory else "(?:/|$)"), re.IGNORECASE)


_COMPUTED = tuple(_glob_regex(p) for p in COMPUTED_PATHS)


def matches(patterns: Iterable[str], relative: str, folder: bool = False) -> bool:
    """Whether the ``/``-separated ``relative`` path (a folder if ``folder``) matches one of the
    glob ``patterns`` (the syntax of :data:`COMPUTED_PATHS`)."""
    path = relative.strip("/") + ("/" if folder else "")
    return any(_glob_regex(p).match(path) for p in patterns)


def inputs_only_problems(path: str | Path) -> list[dict[str, Any]]:
    """Why the archive ``path`` is not inputs only, as a building template must be (docs/
    marketplace-plan.md): one error per kind of file it may not hold: results (the computed
    caches), the soil report (client data), the deliverables of ``11 Exports`` and the version
    history. Empty when it holds only inputs; an unreadable archive is :func:`inspect_archive`'s
    to report."""
    reasons = {
        "results": "results, which SAEngine computes again",
        "soil": f"a soil report ({PARTS['soil'][0]}): templates never hold client data",
        "exports": f"deliverables ({EXPORTS_FOLDER})",
        "versions": "the version history (.git)",
    }
    found: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            names = [i.filename for i in archive.infolist() if not i.is_dir()]
    except (zipfile.BadZipFile, OSError):
        return []
    for name in names:
        if not name.startswith(PROJECT_PREFIX):
            continue
        relative = name[len(PROJECT_PREFIX) :]
        top = relative.split("/", 1)[0].casefold()
        if is_computed(relative):
            found.setdefault("results", relative)
        elif top == PARTS["soil"][0].casefold():
            found.setdefault("soil", relative)
        elif top == EXPORTS_FOLDER.casefold():
            found.setdefault("exports", relative)
        elif top == VERSIONS_FOLDER:
            found.setdefault("versions", relative)
    return [
        _problem(f"not-inputs-only-{key}", f"the archive holds {reasons[key]}, e.g. {relative}")
        for key, relative in found.items()
    ]


def is_computed(relative: str, folder: bool = False) -> bool:
    """Whether ``relative`` (relative to the project root, ``/``-separated; a folder if
    ``folder``) is a computed cache, one of :data:`COMPUTED_PATHS`."""
    path = relative.strip("/") + ("/" if folder else "")
    return any(r.match(path) for r in _COMPUTED)


def path_problem(relative: str) -> str | None:
    """Why the ``/``-separated relative path cannot be a file of a project on Windows, or None:
    absolute paths, drive letters, ``..``, reserved device names (``CON``, ``NUL`` ...),
    characters Windows refuses, segments ending in a dot or a space."""
    if not relative or relative.startswith("/") or "\\" in relative:
        return "not a relative path"
    for segment in relative.split("/"):
        if segment in ("", ".", ".."):
            return f"the segment '{segment}' is not allowed"
        if _FORBIDDEN.search(segment):
            return f"'{segment}' has a character Windows does not allow in a file name"
        if _RESERVED.match(segment):
            return f"'{segment}' is a reserved device name on Windows"
        if segment[-1] in ". ":
            return f"'{segment}' ends with a dot or a space"
    return None


def _is_git_name(segment: str) -> bool:
    """Whether a path segment names a git folder on Windows (``.git``, also with trailing dots or
    spaces, or its 8.3 short name ``GIT~1``)."""
    return segment.rstrip(". ").casefold() in (".git", "git~1")


def is_editor_settings(relative: str) -> bool:
    """Whether the ``/``-separated ``relative`` path is in (or is) an editor settings folder,
    one of :data:`EDITOR_SETTINGS_FOLDERS`, in any spelling Windows takes for it (letter case,
    trailing dots or spaces, the 8.3 short name ``VSCODE~1``)."""
    for segment in relative.strip("/").split("/"):
        name = segment.rstrip(". ").casefold()
        if name in _EDITOR_FOLDERS:
            return True
        short = _SHORT_NAME.match(name)
        if short and any(f.lstrip(".").startswith(short["base"]) for f in _EDITOR_FOLDERS):
            return True
    return False


def _git_action(relative: str) -> str | None:
    """What import does with a project file under the root ``.git`` folder: ``"drop"``,
    ``"config"`` (replaced by :data:`SAFE_GIT_CONFIG`), ``"keep"``; None outside ``.git``."""
    key = relative.casefold()
    if not key.startswith(VERSIONS_FOLDER + "/"):
        return None
    if key == ".git/config":
        return "config"
    if any(key == p or (p.endswith("/") and key.startswith(p)) for p in GIT_DROPPED):
        return "drop"
    return "keep"


def _safe_git_config(text: str) -> str:
    """:data:`SAFE_GIT_CONFIG`, keeping only the repository format and object format of the
    archived ``text`` (everything else, includes and programs among it, is dropped)."""
    version = "0"
    extensions: list[str] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        header = re.match(r"^\[\s*([A-Za-z0-9.-]+)\s*\]", line)
        if header:
            section = header.group(1).casefold()
            continue
        item = re.match(r"^([A-Za-z][A-Za-z0-9-]*)\s*=\s*(\S+)\s*$", line)
        if not item:
            continue
        key, value = item.group(1).casefold(), item.group(2).casefold()
        if section == "core" and key == "repositoryformatversion" and value in ("0", "1"):
            version = value
        elif section == "extensions" and key == "objectformat" and value in ("sha1", "sha256"):
            extensions.append(f"\tobjectformat = {value}\n")
    config = SAFE_GIT_CONFIG.format(version=version)
    if extensions and version == "1":
        config += "[extensions]\n" + "".join(extensions)
    return config


def _is_junk(name: str) -> bool:
    lower = name.lower()
    return any(fnmatch.fnmatchcase(lower, p) for p in JUNK_PATTERNS)


def _is_link(entry: os.DirEntry[str]) -> bool:
    if entry.is_symlink():
        return True
    try:
        return Path(entry.path).is_junction()
    except OSError:
        return True


# --- Small helpers -----------------------------------------------------------------------------


def _problem(code: str, message: str, path: str | None = None, severity: str = "error") -> dict:
    problem: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if path is not None:
        problem["path"] = path
    return problem


def _errors(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in problems if p["severity"] == "error"]


def _version_tuple(version: str) -> tuple[int, ...]:
    numbers = []
    for part in str(version).split("."):
        match = re.match(r"\d+", part)
        if not match:
            break
        numbers.append(int(match.group()))
    return tuple(numbers)


def _newer(version: str, than: str) -> bool:
    a, b = _version_tuple(version), _version_tuple(than)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _iso(created: datetime | str | None) -> str:
    if isinstance(created, str):
        return created
    moment = created or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _zip_time(seconds: float) -> tuple[int, int, int, int, int, int]:
    moment = datetime.fromtimestamp(max(seconds, 0), UTC)
    stamp = (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)
    return max(stamp, _ZIP_EPOCH)


def _zip_info(name: str, seconds: float, size: int, compress: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, _zip_time(seconds))
    info.compress_type = compress
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.file_size = size
    return info


def _json_schema(path: Path, size: int) -> tuple[Any, str | None]:
    """The ``schema`` field of a JSON file (None if it has none), and why it is not valid JSON."""
    if size > JSON_READ_LIMIT:
        return None, None
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, str(exc).splitlines()[0]
    if isinstance(data, dict):
        schema = data.get("schema", data.get("schema_version"))
        if isinstance(schema, str | int) and not isinstance(schema, bool):
            return schema, None
    return None, None


def _is_placeholder(path: Path, part: str) -> bool:
    """Whether ``path`` is the stub a new project starts a part with (``{schema: 1, part}``)."""
    try:
        if path.stat().st_size > 4096:
            return False
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("schema") == 1 and data.get("part") == part


def _sort_key(relative: str) -> tuple[str, str]:
    return relative.casefold(), relative


# --- Export ------------------------------------------------------------------------------------


def find_manifest(root: str | Path) -> Path | None:
    """The project's ``.saengine`` file: the one named after the folder if there are several."""
    folder = Path(root)
    found = sorted(p for p in folder.glob(f"*{PROJECT_EXTENSION}") if p.is_file())
    for candidate in found:
        if candidate.stem.casefold() == folder.name.casefold():
            return candidate
    return found[0] if found else None


def _walk(
    root: Path,
    include_results: bool,
    include_versions: bool,
    include_exports: bool,
    exclude: set[str],
    skipped: list[dict[str, Any]],
    problems: list[dict[str, Any]],
) -> list[tuple[str, Path, os.stat_result]]:
    """The files to archive, sorted: (relative path, absolute path, stat)."""
    files: list[tuple[str, Path, os.stat_result]] = []
    seen: dict[str, str] = {}
    resolved_root = root.resolve()

    def visit(folder: Path, prefix: str) -> None:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: _sort_key(e.name))
        except OSError as exc:
            problems.append(_problem("unreadable", str(exc), prefix.rstrip("/") or ".", "warning"))
            return
        for entry in entries:
            relative = prefix + entry.name
            if _is_link(entry):
                skipped.append({"path": relative, "reason": "link"})
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir:
                if _is_git_name(entry.name) and relative.casefold() != VERSIONS_FOLDER:
                    skipped.append({"path": relative + "/", "reason": "nested repository"})
                    continue
                if is_editor_settings(entry.name):
                    skipped.append({"path": relative + "/", "reason": "editor settings"})
                    continue
                if relative.casefold() == VERSIONS_FOLDER and not include_versions:
                    skipped.append({"path": relative + "/", "reason": "versions"})
                    continue
                if relative.casefold() == EXPORTS_FOLDER.casefold() and not include_exports:
                    skipped.append({"path": relative + "/", "reason": "exports"})
                    continue
                if not include_results and is_computed(relative, folder=True):
                    skipped.append({"path": relative + "/", "reason": "computed"})
                    continue
                visit(Path(entry.path), relative + "/")
                continue
            if not entry.is_file(follow_symlinks=False):
                skipped.append({"path": relative, "reason": "not a file"})
                continue
            full = Path(entry.path)
            if os.path.normcase(str(full.resolve())) in exclude:
                skipped.append({"path": relative, "reason": "the archive itself"})
                continue
            if _is_junk(entry.name):
                skipped.append({"path": relative, "reason": "junk"})
                continue
            if _is_git_name(entry.name):
                skipped.append({"path": relative, "reason": "git link"})
                continue
            if is_editor_settings(entry.name):
                skipped.append({"path": relative, "reason": "editor settings"})
                continue
            if not include_results and is_computed(relative):
                skipped.append({"path": relative, "reason": "computed"})
                continue
            problem = path_problem(relative)
            if problem:
                problems.append(_problem("unsafe-path", problem, relative, "warning"))
                skipped.append({"path": relative, "reason": "name not allowed on Windows"})
                continue
            key = relative.casefold()
            if key in seen:
                problems.append(
                    _problem(
                        "duplicate-path",
                        f"differs from '{seen[key]}' only in letter case",
                        relative,
                        "warning",
                    )
                )
                skipped.append({"path": relative, "reason": "case-insensitive duplicate"})
                continue
            try:
                if not full.resolve().is_relative_to(resolved_root):
                    skipped.append({"path": relative, "reason": "outside the project"})
                    continue
                files.append((relative, full, full.stat()))
            except OSError as exc:
                problems.append(_problem("unreadable", str(exc), relative, "warning"))
                continue
            seen[key] = relative

    visit(root, "")
    files.sort(key=lambda f: _sort_key(f[0]))
    return files


def _compress_type(path: Path, size: int) -> int:
    """Deflate, unless a large file compresses so well that the import would take it for a zip
    bomb (then it is stored)."""
    if size <= RATIO_MIN_SIZE:
        return zipfile.ZIP_DEFLATED
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    compressed = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            compressed += len(compressor.compress(chunk))
    compressed += len(compressor.flush())
    ok = size <= compressed * MAX_RATIO / 2
    return zipfile.ZIP_DEFLATED if ok else zipfile.ZIP_STORED


def export_project(
    root: str | Path,
    out_path: str | Path,
    include_results: bool = False,
    include_versions: bool = False,
    include_exports: bool = True,
    note: str | None = None,
    statuses: Mapping[str, Any] | None = None,
    saengine_version: str | None = None,
    created: datetime | str | None = None,
) -> dict[str, Any]:
    """Archive the project at ``root`` into ``out_path`` (a ``.civil`` file, replaced if it
    exists): ``{"path", "size", "files": count, "skipped": [{"path", "reason"}], "problems"}``.

    ``statuses`` (part id -> anything JSON-ready, e.g. the sidebar's part status) is recorded as
    each part's ``status``; ``saengine_version`` (default: the backend's version) and ``created``
    (default: now) go into the manifest. Raises :class:`ArchiveError` if ``root`` is not a
    project (no ``.saengine`` file)."""
    root = Path(root)
    out = Path(out_path)
    manifest_file = find_manifest(root)
    if manifest_file is None:
        raise ArchiveError(f"{root} is not a SAEngine project: it has no {PROJECT_EXTENSION} file")
    problems: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    partial = out.with_name(out.name + ".partial")
    exclude = {os.path.normcase(str(p.resolve())) for p in (out, partial)}
    files = _walk(
        root, include_results, include_versions, include_exports, exclude, skipped, problems
    )

    # The project manifest: name, type and parts.
    try:
        project_data = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        if not isinstance(project_data, dict):
            raise TypeError("not a JSON object")
    except (OSError, ValueError, TypeError) as exc:
        problems.append(
            _problem("invalid-json", str(exc).splitlines()[0], manifest_file.name, "warning")
        )
        project_data = {}
    name = project_data.get("name") if isinstance(project_data.get("name"), str) else None
    project_type = "structure" if project_data.get("type") == "structure" else "building"
    part_ids = project_data.get("parts")
    if not (isinstance(part_ids, list) and all(isinstance(p, str) for p in part_ids)):
        part_ids = [
            "structure" if p == "floorPlan" and project_type == "structure" else p
            for p in BUILDING_PARTS
        ]

    total = 0
    entries: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for relative, full, info in files:
            size = info.st_size
            compress = _compress_type(full, size)
            zinfo = _zip_info(PROJECT_PREFIX + relative, info.st_mtime, size, compress)
            digest = hashlib.sha256()
            written = 0
            with (
                full.open("rb") as source,
                archive.open(zinfo, "w", force_zip64=size > 2**31) as target,
            ):
                while chunk := source.read(_CHUNK):
                    digest.update(chunk)
                    target.write(chunk)
                    written += len(chunk)
            entry: dict[str, Any] = {
                "path": relative,
                "size": written,
                "sha256": digest.hexdigest(),
                "mtime": info.st_mtime_ns,
            }
            if full.suffix.lower() in _JSON_SUFFIXES:
                schema, invalid = _json_schema(full, written)
                if schema is not None:
                    entry["schema"] = schema
                if invalid:
                    problems.append(
                        _problem("invalid-json", f"not valid JSON: {invalid}", relative, "warning")
                    )
            if is_computed(relative):
                entry["computed"] = True
            entries[relative] = entry
            total += written

        # The parts, with their files; everything else under "files".
        claimed: set[str] = set()
        parts: list[dict[str, Any]] = []
        for part_id in part_ids:
            folder, main_file = PARTS.get(part_id, (None, None))
            part: dict[str, Any] = {"id": part_id, "folder": folder}
            if folder is None:
                problems.append(
                    _problem("unknown-part", f"the part '{part_id}' is unknown", None, "warning")
                )
                part["files"] = []
                parts.append(part)
                continue
            prefix = folder.casefold() + "/"
            listed = [e for r, e in entries.items() if r.casefold().startswith(prefix)]
            claimed.update(e["path"] for e in listed)
            part["mainFile"] = main_file
            part["files"] = listed
            present = (root / folder).is_dir()
            main = root / folder / main_file if main_file else None
            if not present:
                part["missing"] = True
            elif main is not None and not main.is_file():
                part["missingMainFile"] = True
            elif main is not None and _is_placeholder(main, part_id):
                part["placeholder"] = True
            if statuses and part_id in statuses:
                part["status"] = statuses[part_id]
            parts.append(part)

        manifest: dict[str, Any] = {
            "format": FORMAT,
            "saengineVersion": saengine_version or saengine.__version__,
            "created": _iso(created),
            "project": {"name": name or root.name, "file": manifest_file.name},
            "parts": parts,
            "files": [e for r, e in entries.items() if r not in claimed],
            "includes": {
                "results": include_results,
                "versions": include_versions,
                "exports": include_exports,
            },
        }
        if "type" in project_data:
            manifest["project"]["type"] = project_type
        if note:
            manifest["note"] = note
        text = json.dumps(manifest, indent="\t", ensure_ascii=False) + "\n"
        archive.writestr(_zip_info(MANIFEST_NAME, 0, 0, zipfile.ZIP_DEFLATED), text.encode("utf-8"))

    if total > MAX_UNCOMPRESSED:
        problems.append(
            _problem(
                "too-large",
                f"the project is {total / 1024**3:.1f} GB, more than SAEngine imports "
                f"({MAX_UNCOMPRESSED / 1024**3:.0f} GB)",
                None,
                "warning",
            )
        )
    os.replace(partial, out)
    return {
        "path": str(out),
        "size": out.stat().st_size,
        "files": len(entries),
        "skipped": skipped,
        "problems": problems,
    }


# --- Inspect -----------------------------------------------------------------------------------


def _manifest_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = []
    for part in manifest.get("parts") or []:
        if isinstance(part, dict):
            listed.extend(f for f in part.get("files") or [] if isinstance(f, dict))
    listed.extend(f for f in manifest.get("files") or [] if isinstance(f, dict))
    return listed


def _hash_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> tuple[str, int]:
    """SHA-256 and size of an entry, reading at most ``limit`` + 1 bytes."""
    digest = hashlib.sha256()
    read = 0
    with archive.open(info) as stream:
        while chunk := stream.read(min(_CHUNK, limit + 1 - read)):
            digest.update(chunk)
            read += len(chunk)
            if read > limit:
                break
    return digest.hexdigest(), read


def _check(
    archive: zipfile.ZipFile, current_version: str | None, verify: bool
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, tuple[zipfile.ZipInfo, dict]]]:
    """The manifest, the problems, and the project's files: relative path -> (entry, listing)."""
    problems: list[dict[str, Any]] = []
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        problems.append(_problem("too-many-files", f"{len(infos)} entries"))
        return None, problems, {}

    # The manifest and its format.
    try:
        if archive.getinfo(MANIFEST_NAME).file_size > JSON_READ_LIMIT:
            raise ValueError("too large")
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8-sig"))
        if not isinstance(manifest, dict):
            raise TypeError("not a JSON object")
    except KeyError:
        problems.append(_problem("no-manifest", f"the archive has no {MANIFEST_NAME}"))
        return None, problems, {}
    except (ValueError, TypeError) as exc:
        problems.append(_problem("invalid-manifest", f"{MANIFEST_NAME}: {exc}"))
        return None, problems, {}
    current = current_version or saengine.__version__
    made_with = str(manifest.get("saengineVersion") or "an unknown version")
    fmt = str(manifest.get("format") or "")
    name, _, major = fmt.partition("/")
    if name != FORMAT_NAME or not major.isdigit():
        problems.append(_problem("unknown-format", f"'{fmt}' is not a SAEngine project archive"))
        return manifest, problems, {}
    if int(major) > FORMAT_VERSION:
        problems.append(
            _problem(
                "newer-format",
                f"made with SAEngine {made_with}, newer than this one ({current}): its archive "
                f"format {fmt} is newer than {FORMAT}. Update SAEngine to open it.",
            )
        )
        return manifest, problems, {}
    if manifest.get("saengineVersion") and _newer(made_with, current):
        problems.append(
            _problem(
                "newer-version",
                f"made with SAEngine {made_with}, newer than this one ({current}): parts it "
                "changed may not open until SAEngine is updated.",
                None,
                "warning",
            )
        )

    # The entries: where they are, how large, whether listed.
    listing = {
        str(f.get("path")): f for f in _manifest_files(manifest) if isinstance(f.get("path"), str)
    }
    found: dict[str, tuple[zipfile.ZipInfo, dict]] = {}
    seen: dict[str, str] = {}
    total = 0
    includes = manifest.get("includes") if isinstance(manifest.get("includes"), dict) else {}
    versions_declared = includes.get("versions") is True
    has_versions = False
    editor_settings: list[str] = []
    for info in infos:
        name = info.filename
        if name == MANIFEST_NAME:
            continue
        if "\\" in info.orig_filename or not name.startswith(PROJECT_PREFIX):
            problems.append(_problem("outside", "the entry is outside 'project/'", name))
            continue
        relative = name[len(PROJECT_PREFIX) :]
        if info.is_dir():
            if relative and path_problem(relative.rstrip("/")):
                problems.append(_problem("unsafe-path", "unsafe folder name", name))
            continue
        problem = path_problem(relative)
        if problem:
            problems.append(_problem("unsafe-path", problem, name))
            continue
        segments = relative.split("/")
        if any(
            _is_git_name(s) and not (i == 0 and s.casefold() == VERSIONS_FOLDER and segments[1:])
            for i, s in enumerate(segments)
        ):
            problems.append(
                _problem(
                    "nested-repository",
                    "a git folder or link other than the project's version history",
                    relative,
                )
            )
            continue
        if is_editor_settings(relative):
            # Never extracted: noted once below, and not a "missing" file of the listing.
            editor_settings.append(relative)
            seen.setdefault(relative.casefold(), relative)
            continue
        if _git_action(relative) is not None:
            if not versions_declared:
                problems.append(
                    _problem(
                        "unexpected-versions",
                        "version history in an archive whose manifest says it has none",
                        relative,
                    )
                )
                continue
            has_versions = True
        if stat.S_ISLNK(info.external_attr >> 16):
            problems.append(_problem("link", "symbolic links are not extracted", relative))
            continue
        if info.flag_bits & 0x1:
            problems.append(_problem("encrypted", "encrypted entries are not supported", relative))
            continue
        key = relative.casefold()
        if key in seen:
            problems.append(
                _problem("duplicate-path", f"same as '{seen[key]}' on Windows", relative)
            )
            continue
        seen[key] = relative
        if info.file_size > RATIO_MIN_SIZE and info.file_size > MAX_RATIO * max(
            info.compress_size, 1
        ):
            problems.append(
                _problem(
                    "zip-bomb",
                    f"inflates {info.file_size / max(info.compress_size, 1):.0f} times "
                    f"(more than {MAX_RATIO})",
                    relative,
                )
            )
            continue
        total += info.file_size
        listed = listing.get(relative)
        if listed is None:
            problems.append(_problem("unlisted-file", "not in the manifest", relative))
            continue
        if listed.get("size") != info.file_size:
            problems.append(
                _problem(
                    "size-mismatch",
                    f"{info.file_size} bytes, the manifest says {listed.get('size')}",
                    relative,
                )
            )
            continue
        found[relative] = (info, listed)
    if total > MAX_UNCOMPRESSED:
        problems.append(
            _problem(
                "too-large",
                f"{total / 1024**3:.1f} GB once extracted, more than "
                f"{MAX_UNCOMPRESSED / 1024**3:.0f} GB",
            )
        )
    present = {k.casefold() for k in seen}
    for relative in listing:
        if relative.casefold() not in present:
            problems.append(_problem("missing-file", "listed but not in the archive", relative))
    # A file whose path is also another file's folder ("a" and "a/b") cannot be extracted.
    for key, relative in sorted(seen.items()):
        segments = key.split("/")
        for depth in range(1, len(segments)):
            parent = "/".join(segments[:depth])
            if parent in seen:
                problems.append(
                    _problem(
                        "path-conflict",
                        f"'{seen[parent]}' is a file and also a folder of this file",
                        relative,
                    )
                )
                break
    # The project file, which import renames: one file at the root, in the archive.
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    file_name = project.get("file")
    if file_name is not None and (
        not isinstance(file_name, str)
        or "/" in file_name
        or path_problem(file_name) is not None
        or not file_name.casefold().endswith(PROJECT_EXTENSION)
        or file_name not in found
    ):
        problems.append(
            _problem(
                "invalid-project-file",
                f"the manifest's project file '{file_name}' is not a {PROJECT_EXTENSION} file "
                "at the root of the archived project",
            )
        )
    if editor_settings:
        problems.append(
            _problem(
                "editor-settings",
                f"{len(editor_settings)} editor settings file(s) ("
                + ", ".join(editor_settings[:3])
                + (" ..." if len(editor_settings) > 3 else "")
                + ") are not extracted: they could name programs to run when the project is "
                "opened",
                editor_settings[0],
                "warning",
            )
        )
    if has_versions:
        problems.append(
            _problem(
                "versions",
                "includes a version history: its git settings are reset and its hooks are not "
                "extracted",
                VERSIONS_FOLDER,
                "warning",
            )
        )

    if verify and not _errors(problems):
        for relative, (info, listed) in found.items():
            try:
                digest, size = _hash_entry(archive, info, info.file_size)
            except (zipfile.BadZipFile, zlib.error, OSError) as exc:
                problems.append(_problem("corrupt", str(exc), relative))
                continue
            if size != info.file_size or digest != listed.get("sha256"):
                problems.append(
                    _problem("checksum", "the content does not match its checksum", relative)
                )
    return manifest, problems, found


def inspect_archive(
    path: str | Path, current_version: str | None = None, verify: bool = True
) -> dict[str, Any]:
    """Read and check the archive ``path`` without extracting it: ``{"manifest" (None if it has
    none), "problems", "ok": no error, "files": count, "size": bytes once extracted}``.

    Errors: not a zip, no or invalid manifest, a format that is not :data:`FORMAT_NAME` or newer
    than :data:`FORMAT_VERSION`, entries outside ``project/``, unsafe or duplicate paths, links,
    encrypted entries, zip bombs, files missing from the archive or from the manifest, sizes and
    (with ``verify``) checksums that do not match. A warning: made with a SAEngine newer than
    ``current_version`` (default: the backend's version)."""
    try:
        with zipfile.ZipFile(path) as archive:
            manifest, problems, found = _check(archive, current_version, verify)
    except (zipfile.BadZipFile, OSError) as exc:
        manifest, found = None, {}
        problems = [_problem("not-an-archive", f"not a SAEngine project archive: {exc}")]
    return {
        "manifest": manifest,
        "problems": problems,
        "ok": not _errors(problems),
        "files": len(found),
        "size": sum(info.file_size for info, _ in found.values()),
    }


# --- Import ------------------------------------------------------------------------------------


#: The workbench command that imports the building model's footings into 9 Substructure.
IMPORT_FOOTINGS_COMMAND = "saengine.substructure.importFootings"


def run_migrations(root: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The migrations SAEngine applies by itself when a project is opened, run on ``root``:
    (migrated ``[{"id", "message", "count"}]``, problems). Today one: the footings of 6 BIM
    written into a placeholder ``substructure.json``
    (:func:`saengine.substructure.handover.ensure_migrated`, which the Substructure editor also
    runs on open; it never overwrites a substructure that was worked on)."""
    from saengine.substructure.handover import ensure_migrated

    migrated: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    try:
        result = ensure_migrated(root)
    except (OSError, ValueError) as exc:
        result = {"migrated": False, "problems": [str(exc)]}
    if result.get("migrated"):
        count = int(result.get("count") or 0)
        migrated.append(
            {
                "id": "substructure.footings",
                "message": f"{count} footing(s) of 6 BIM moved into 9 Substructure",
                "count": count,
            }
        )
    for message in result.get("problems") or []:
        problems.append(_problem("migration", str(message), None, "warning"))
    return migrated, problems


def safe_name(name: str) -> str:
    """``name`` as a Windows folder name: forbidden characters replaced, no trailing dots or
    spaces, reserved device names avoided."""
    cleaned = _FORBIDDEN.sub("-", name.replace("/", "-")).strip().rstrip(". ")
    if _RESERVED.match(cleaned):
        cleaned += "_"
    return cleaned or "Project"


def pending_migrations(root: str | Path) -> list[dict[str, Any]]:
    """The migrations a project could take, which SAEngine offers rather than applying: each
    ``{"id", "message", "command"}``. Today: footings drawn in 6 BIM that a substructure already
    worked on (not the placeholder, which :func:`import_project` migrates) does not have; the
    command is the Substructure editor's "Import Footings from the Building Model"
    (``saengine.substructure.importFootings``), an engineering choice, never automatic."""
    folder = Path(root)
    pending: list[dict[str, Any]] = []
    try:
        bim = json.loads((folder / "06 BIM" / "bim.json").read_text(encoding="utf-8-sig"))
        footings = {
            e.get("id")
            for e in bim.get("elements") or []
            if isinstance(e, dict) and e.get("kind") == "footing"
        }
    except (OSError, ValueError, AttributeError):
        footings = set()
    if footings:
        try:
            sub = json.loads(
                (folder / "09 Substructure" / "substructure.json").read_text(encoding="utf-8-sig")
            )
            if is_substructure_placeholder(sub):
                return pending  # migrated by run_migrations, and by the editor on open
            taken = {f.get("id") for f in sub.get("foundations") or [] if isinstance(f, dict)}
        except OSError:
            return pending  # no substructure yet: the editor's migration writes one on open
        except (ValueError, AttributeError):
            return pending  # an invalid file is the engineer's to fix
        new = sorted(str(f) for f in footings - taken)
        if new:
            pending.append(
                {
                    "id": "substructure.footings",
                    "message": f"{len(new)} footing(s) drawn in 6 BIM are not in 9 Substructure "
                    f"yet ({', '.join(new[:5])}{' ...' if len(new) > 5 else ''}): import them in "
                    "9 Substructure (Import Footings from the Building Model).",
                    "command": IMPORT_FOOTINGS_COMMAND,
                }
            )
    return pending


def _extract(
    archive: zipfile.ZipFile, found: dict[str, tuple[zipfile.ZipInfo, dict]], staging: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract ``found`` into ``staging``, checking each file: (problems, the ``.git`` files left
    out). The archived ``.git/config`` is replaced by :func:`_safe_git_config`."""
    problems: list[dict[str, Any]] = []
    dropped: list[str] = []
    base = staging.resolve()
    for relative in sorted(found, key=_sort_key):
        info, listed = found[relative]
        action = _git_action(relative)
        if action == "drop":
            dropped.append(relative)
            continue
        target = (staging / relative).resolve()
        if not target.is_relative_to(base) or target == base:
            problems.append(_problem("unsafe-path", "resolves outside the project", relative))
            continue
        digest = hashlib.sha256()
        written = 0
        content = bytearray() if action == "config" else None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as out:
                while chunk := source.read(_CHUNK):
                    written += len(chunk)
                    if written > info.file_size:
                        break
                    digest.update(chunk)
                    if content is not None:
                        if len(content) < JSON_READ_LIMIT:
                            content.extend(chunk)
                    else:
                        out.write(chunk)
                if content is not None:
                    text = _safe_git_config(content.decode("utf-8", "replace"))
                    out.write(text.encode("utf-8"))
        except (OSError, zipfile.BadZipFile, zlib.error) as exc:
            problems.append(_problem("unwritable", str(exc), relative))
            continue
        if written != info.file_size or digest.hexdigest() != listed.get("sha256"):
            problems.append(
                _problem("checksum", "the content does not match its checksum", relative)
            )
            continue
        if content is not None:
            continue  # a new file: its time is now
        mtime = listed.get("mtime")
        if isinstance(mtime, int) and mtime > 0:
            try:
                os.utime(target, ns=(mtime, mtime))
            except (OSError, OverflowError, ValueError):
                pass
    return problems, dropped


def _move_into(staging: Path, dest: Path) -> None:
    """Move the files of ``staging`` into the existing folder ``dest``, replacing files there."""
    for folder, _dirs, names in os.walk(staging):
        relative = Path(folder).relative_to(staging)
        (dest / relative).mkdir(parents=True, exist_ok=True)
        for name in names:
            target = dest / relative / name
            if target.is_dir() and not target.is_symlink():
                raise ArchiveError(f"{target} is a folder; the archive has a file there")
            os.replace(Path(folder) / name, target)


def import_project(
    path: str | Path,
    dest_parent: str | Path,
    name: str | None = None,
    overwrite: bool = False,
    current_version: str | None = None,
    migrate: bool = True,
) -> dict[str, Any]:
    """Extract the archive ``path`` into ``<dest_parent>/<name>`` (default name: the archived
    project's): ``{"root", "name", "files": count, "problems" (warnings), "migrated": [...]
    (:func:`run_migrations`, unless not ``migrate``), "pending": [...]
    (:func:`pending_migrations`), "renamed"?: {"from", "to"}}``.

    Everything is checked first (:func:`inspect_archive`) and extracted into a temporary folder
    beside the destination, checksum by checksum, then moved into place, so a refused import
    leaves nothing behind. An existing non-empty destination is refused unless ``overwrite``
    (its files that the archive also has are then replaced; the others stay). With a new name
    the ``.saengine`` file is renamed and its ``name`` updated. A version history (``.git``,
    only if the manifest declares it) is extracted without its hooks and with a reset
    ``config`` (see :data:`GIT_DROPPED`), and editor settings folders
    (:data:`EDITOR_SETTINGS_FOLDERS`, e.g. ``.vscode``) are never extracted, so nothing in a
    received archive makes git, SAEngine or an editor run a program. The migrations SAEngine runs on open are run (``migrated``); the ones it offers
    are returned as ``pending``. Raises :class:`ArchiveError` (``.problems``) when the archive
    is refused or cannot be written."""
    parent = Path(dest_parent)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest, problems, found = _check(archive, current_version, verify=False)
            errors = _errors(problems)
            if errors or manifest is None:
                raise ArchiveError(
                    "the archive cannot be imported: "
                    + "; ".join(p["message"] for p in errors[:3]),
                    problems,
                )
            project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
            archived_name = str(project.get("name") or Path(path).stem)
            folder_name = safe_name(name or archived_name)
            dest = parent / folder_name
            if dest.exists() and not dest.is_dir():
                raise ArchiveError(f"{dest} exists and is not a folder", problems)
            if dest.is_dir() and any(dest.iterdir()) and not overwrite:
                raise ArchiveError(
                    f"{dest} already exists and is not empty; choose another name",
                    [*problems, _problem("exists", "the folder is not empty", str(dest))],
                )
            parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".civil-import-", dir=parent))
            try:
                failed, dropped = _extract(archive, found, staging)
                if failed:
                    raise ArchiveError(
                        "the archive cannot be extracted: "
                        + "; ".join(f"{p['path']}: {p['message']}" for p in failed[:3]),
                        [*problems, *failed],
                    )
                if dropped:
                    problems.append(
                        _problem(
                            "versions-hooks",
                            f"{len(dropped)} file(s) of the version history were not extracted "
                            "(hooks, links to other repositories)",
                            VERSIONS_FOLDER,
                            "warning",
                        )
                    )
                result: dict[str, Any] = {}
                # The project file: the manifest's (checked by _check: a .saengine file at the
                # root of the archived project), else the archive's only root .saengine file.
                file_name = project.get("file")
                if not isinstance(file_name, str) or file_name not in found:
                    roots = [
                        r
                        for r in found
                        if "/" not in r and r.casefold().endswith(PROJECT_EXTENSION)
                    ]
                    file_name = roots[0] if len(roots) == 1 else ""
                old = staging / file_name if file_name else None
                new = staging / f"{folder_name}{PROJECT_EXTENSION}"
                if (
                    old is not None
                    and old.is_file()
                    and folder_name != old.stem
                    and (not new.exists() or new.name.casefold() == old.name.casefold())
                ):
                    os.replace(old, new)
                    try:
                        data = json.loads(new.read_text(encoding="utf-8-sig"))
                        if isinstance(data, dict) and data.get("name") != folder_name:
                            data["name"] = folder_name
                            new.write_text(
                                json.dumps(data, indent="\t", ensure_ascii=False) + "\n",
                                encoding="utf-8",
                            )
                    except (OSError, ValueError):
                        pass
                    result["renamed"] = {"from": file_name, "to": new.name}
                try:
                    if dest.is_dir() and any(dest.iterdir()):
                        others = [
                            p.name
                            for p in dest.glob(f"*{PROJECT_EXTENSION}")
                            if not (staging / p.name).exists()
                        ]
                        _move_into(staging, dest)
                        if others:
                            problems.append(
                                _problem(
                                    "several-manifests",
                                    f"the folder also has {', '.join(sorted(others))}",
                                    str(dest),
                                    "warning",
                                )
                            )
                    else:
                        if dest.is_dir():
                            dest.rmdir()
                        os.replace(staging, dest)
                except OSError as exc:
                    raise ArchiveError(
                        f"the project could not be written to {dest}: {exc}",
                        [*problems, _problem("unwritable", str(exc), str(dest))],
                    ) from exc
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"not a SAEngine project archive: {exc}") from exc
    except OSError as exc:
        raise ArchiveError(f"the archive cannot be imported: {exc}") from exc
    migrated: list[dict[str, Any]] = []
    if migrate:
        migrated, migration_problems = run_migrations(dest)
        problems.extend(migration_problems)
    return {
        "root": str(dest),
        "name": folder_name,
        "files": len(found),
        "problems": problems,
        "migrated": migrated,
        "pending": pending_migrations(dest),
        **result,
    }
