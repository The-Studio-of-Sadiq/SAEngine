"""Copy GNU LibreDWG's dwg2dxf into the SAEngine app folder as a separate program, with its licence.

The floor plan's underlays and the geometry import read architects' DWG drawings by converting
them to DXF with ``dwg2dxf`` of GNU LibreDWG (GPL-3.0-or-later). It is shipped next to SAEngine
as a separate program in ``resources/libredwg`` and run by the backend as its own process
(saengine.library.dwg); nothing of it is linked into SAEngine (an aggregate, GPL-3.0 section 5).

    python -I -B libredwg_bundle.py --source <LibreDWG folder> --dest <app>\\resources\\libredwg
        [--license FILE ...] [--expect-version 0.14] [--require-licenses] [--no-check] [--dry-run]

``--source`` is the official Windows build ``libredwg-<version>-win64.zip`` unpacked (the folder
holding ``dwg2dxf.exe`` is found inside it). Only :data:`KEEP` is copied: ``dwg2dxf.exe`` and
``libredwg-0.dll``, the one DLL it imports (the zip's other programs, the iconv and PCRE2 DLLs
that only ``dwggrep`` needs, headers, import libraries, Python bindings and manuals are left
out: 51 MB down to about 31 MB). The zip ships no licence file, so the release build passes
LibreDWG's COPYING (the GPL-3.0 text, pinned in scripts/ci/third-party-binaries.json) with
``--license``; it goes to ``resources/libredwg/licenses``. By default the copy is checked by
running ``dwg2dxf --version`` (which also gives the version).

Writes ``resources/libredwg/SAENGINE-BUNDLE.json``: the version, licence, files and size;
write_notices.py and fetch-sources.ps1 read it. ``--dry-run`` prints the plan and copies nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROGRAM = "dwg2dxf.exe"
#: What the bundle holds, besides the licences: the converter and the library it imports.
KEEP = (PROGRAM, "libredwg-0.dll")
MANIFEST_NAME = "SAENGINE-BUNDLE.json"


class BundleError(Exception):
    pass


def find_program_dir(source: Path) -> Path:
    """The shallowest folder under ``source`` (or ``source`` itself) holding dwg2dxf.exe."""
    if (source / PROGRAM).is_file():
        return source
    hits = sorted(
        (p.parent for p in source.rglob("*") if p.is_file() and p.name.lower() == PROGRAM),
        key=lambda p: (len(p.relative_to(source).parts), str(p)),
    )
    if not hits:
        raise BundleError(f"{source} holds no {PROGRAM}")
    return hits[0]


def program_version(exe: Path, timeout: float = 60) -> str:
    """``dwg2dxf --version`` ("dwg2dxf 0.14" -> "0.14"); an error when it does not run."""
    try:
        done = subprocess.run(
            [str(exe), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BundleError(f"{exe} does not run: {exc}") from exc
    match = re.search(r"dwg2dxf\s+(\S+)", done.stdout)
    if done.returncode != 0 or not match:
        raise BundleError(f"{exe} --version answered {done.returncode}: {done.stdout.strip()!r}")
    return match.group(1)


def bundle(
    source: Path,
    dest: Path,
    licenses: list[Path] | None = None,
    expect_version: str | None = None,
    require_licenses: bool = False,
    check: bool = True,
    dry_run: bool = False,
) -> dict:
    """Copies dwg2dxf into a fresh ``dest`` (unless ``dry_run``); the bundle manifest."""
    root = find_program_dir(source)
    missing = [name for name in KEEP if not (root / name).is_file()]
    if missing:
        raise BundleError(f"{root} lacks {', '.join(missing)}: not a LibreDWG Windows build")
    licenses = list(licenses or [])
    for path in licenses:
        if not path.is_file():
            raise BundleError(f"licence file {path} does not exist")
    if require_licenses and not licenses:
        raise BundleError(
            "no licence text for LibreDWG: pass --license with its COPYING "
            "(scripts/ci/fetch_pinned.py libredwg-copying)"
        )
    if not licenses:
        print("warning: no licence text is bundled with LibreDWG (pass --license)")
    version = program_version(root / PROGRAM) if check else None
    if expect_version and version and version != expect_version:
        raise BundleError(f"{root / PROGRAM} is version {version}, expected {expect_version}")
    size = sum((root / name).stat().st_size for name in KEEP) + sum(
        p.stat().st_size for p in licenses
    )
    manifest = {
        "name": "LibreDWG",
        "version": version or expect_version or "unknown",
        "license": "GPL-3.0-or-later",
        "program": PROGRAM,
        "licenses": [f"licenses/{p.name}" for p in licenses],
        "files": len(KEEP) + len(licenses),
        "bytes": size,
        "source": str(root),
    }
    print(
        f"LibreDWG {manifest['version']}: {manifest['files']} files, {size / 1e6:.1f} MB"
        f"{' (dry run: nothing copied)' if dry_run else ''}"
    )
    if dry_run:
        for name in KEEP:
            print(f"  copy {name}")
        for path in licenses:
            print(f"  licence {path} -> licenses/{path.name}")
        return manifest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in KEEP:
        shutil.copy2(root / name, dest / name)
    if licenses:
        (dest / "licenses").mkdir()
        for path in licenses:
            shutil.copy2(path, dest / "licenses" / path.name)
    if check:
        program_version(dest / PROGRAM)  # runs from the bundle, with only the kept DLL
    manifest["source"] = root.name
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--license", type=Path, action="append", default=[])
    parser.add_argument("--expect-version")
    parser.add_argument("--require-licenses", action="store_true")
    parser.add_argument("--no-check", action="store_true", help="do not run dwg2dxf --version")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        bundle(
            args.source,
            args.dest,
            args.license,
            args.expect_version,
            args.require_licenses,
            check=not args.no_check,
            dry_run=args.dry_run,
        )
    except BundleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
