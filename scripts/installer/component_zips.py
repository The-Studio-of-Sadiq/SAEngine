"""Component zips of a SAEngine release (docs/marketplace-plan.md §6, round M7, option (b)).

Each optional component of the setup (``code.iss`` ``[Components]``) is also published as
``SAEngine-<version>-component-<name>.zip``, with ``SAEngine-<version>-components.json`` (the
manifest: name, file, size, SHA-256 and the folders it fills), so a component can be added
without the whole setup. The folders are the same ones ``code.iss`` gives each component.

Decision D7: the app downloads no program before SAEngine is signed. The zips are built now so the
release process is ready, but the app only offers them once product.json's
``saengineSigning.publisher`` is set, and then checks every ``.exe`` and ``.dll`` in a zip with
Authenticode before it is unpacked (until then *Add Component...* re-runs the setup).

Usage (standard library only; run after ``build-installer.ps1`` built the app folder)::

    python -I scripts/installer/component_zips.py --app <VSCode-win32-x64 folder> \
        --version 0.0.50-alpha.8 --out dist
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

RESOURCES = "resources"
EXTENSIONS = f"{RESOURCES}/app/extensions"
#: The folders of each component, relative to the app folder (as in code.iss).
COMPONENTS: dict[str, tuple[str, ...]] = {
    "energyplus": (f"{RESOURCES}/energyplus",),
    "librecad": (f"{RESOURCES}/librecad",),
    "libredwg": (f"{RESOURCES}/libredwg",),
    "ai": (f"{EXTENSIONS}/copilot", f"{EXTENSIONS}/github-authentication"),
    "git": (
        f"{EXTENSIONS}/git",
        f"{EXTENSIONS}/git-base",
        f"{EXTENSIONS}/github",
        f"{EXTENSIONS}/merge-conflict",
        f"{EXTENSIONS}/github-authentication",
    ),
    "collaboration": (f"{EXTENSIONS}/tunnel-forwarding", f"{EXTENSIONS}/microsoft-authentication"),
}
MANIFEST_SCHEMA = "saengine.components/1"
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_zip(app: Path, name: str, folders: tuple[str, ...], dest: Path) -> dict | None:
    """The zip of one component (reproducible: sorted entries, fixed times); None when the app
    folder has none of its folders (a component left out of the build)."""
    files = sorted(
        f for folder in folders if (app / folder).is_dir() for f in (app / folder).rglob("*")
        if f.is_file()
    )  # fmt: skip
    if not files:
        return None
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            info = zipfile.ZipInfo(f.relative_to(app).as_posix(), _FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, f.read_bytes())
    programs = sum(f.suffix.lower() in (".exe", ".dll") for f in files)
    return {
        "name": name,
        "file": dest.name,
        "size": dest.stat().st_size,
        "sha256": _sha256(dest),
        "folders": [f for f in folders if (app / f).is_dir()],
        "programs": programs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--app", type=Path, required=True, help="the built app folder")
    parser.add_argument("--version", required=True, help="the release version")
    parser.add_argument("--out", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, folders in COMPONENTS.items():
        dest = args.out / f"SAEngine-{args.version}-component-{name}.zip"
        entry = build_zip(args.app, name, folders, dest)
        if entry is None:
            print(f"{name}: not in this build, no zip")
            continue
        entries.append(entry)
        print(f"{dest.name}: {entry['size']:,} bytes, sha256 {entry['sha256']}")
    manifest = args.out / f"SAEngine-{args.version}-components.json"
    manifest.write_text(
        json.dumps(
            {"schema": MANIFEST_SCHEMA, "version": args.version, "components": entries}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{manifest.name}: {len(entries)} components")
    return 0


if __name__ == "__main__":
    sys.exit(main())
