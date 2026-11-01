"""Mirror SAEngine's built-in packages into a clone of a marketplace package repository.

The built-in packages (``python/src/saengine/codes/packs/<id>/``: BNBC 2020, the shape presets)
are edited here, in SAEngine, and published by the package repositories of their kind as
read-only copies (docs/marketplace-plan.md, round M2). This script copies each built-in package
of the repository's kind into the clone, replacing the copy there, and records in the clone's
``mirrors.json`` where it came from: the SAEngine repository, the folder and the commit. The
repositories' CI (``saengine-index``, ``check_packages.py``) compares a mirrored package file by
file with that commit, so a hand edit of a mirror fails until it is mirrored again.

Usage, from the SAEngine checkout (the folder must be committed: the commit is recorded)::

    python scripts/marketplace/mirror_packages.py --dest ../saengine-design-codes --kind designCode
    python scripts/marketplace/mirror_packages.py --dest ../saengine-structure-templates \
        --kind structureTemplate

Then commit the clone's changes on a branch and open a pull request there.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKS = Path("python/src/saengine/codes/packs")
REPOSITORY = "The-Studio-of-Sadiq/SAEngine"
MIRRORS_FILE = "mirrors.json"
MIRRORS_SCHEMA = "saengine.packageMirrors/1"
KINDS = ("designCode", "structureTemplate", "buildingTemplate", "languagePack")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def builtin_packages(kind: str) -> dict[str, Path]:
    """The built-in packages of ``kind``: id -> folder."""
    found = {}
    for pack in sorted((ROOT / PACKS).iterdir()):
        manifest = pack / "pack.json"
        if pack.is_dir() and manifest.is_file():
            doc = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if doc.get("kind", "designCode") == kind:
                found[doc["id"]] = pack
    return found


def _ignored(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))]


def mirror(dest: Path, kind: str, allow_dirty: bool = False) -> list[str]:
    packages = builtin_packages(kind)
    if not packages:
        return []
    dirty = _git(
        "status", "--porcelain", "--", *(p.relative_to(ROOT).as_posix() for p in packages.values())
    )
    if dirty and not allow_dirty:
        raise SystemExit(f"commit the built-in packages first (the commit is recorded):\n{dirty}")
    commit = _git("rev-parse", "HEAD")
    mirrors_path = dest / MIRRORS_FILE
    mirrors = (
        json.loads(mirrors_path.read_text(encoding="utf-8"))
        if mirrors_path.is_file()
        else {"schema": MIRRORS_SCHEMA, "packages": {}}
    )
    for pack_id, folder in packages.items():
        target = dest / pack_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(folder, target, ignore=_ignored)
        mirrors["packages"][pack_id] = {
            "repository": REPOSITORY,
            "path": folder.relative_to(ROOT).as_posix(),
            "commit": commit,
        }
    mirrors["packages"] = dict(sorted(mirrors["packages"].items()))
    mirrors_path.write_text(json.dumps(mirrors, indent=2) + "\n", encoding="utf-8")
    return list(packages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=Path, required=True, help="clone of the package repository")
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument(
        "--allow-dirty", action="store_true", help="mirror uncommitted packages (testing only)"
    )
    args = parser.parse_args(argv)
    if not args.dest.is_dir():
        parser.error(f"{args.dest} is not a folder")
    ids = mirror(args.dest, args.kind, args.allow_dirty)
    print(f"mirrored {', '.join(ids) or 'nothing'} into {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
