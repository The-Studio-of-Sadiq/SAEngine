"""Download the pinned third-party files of the release build and check their SHA-256.

The files are listed in ``scripts/ci/third-party-binaries.json`` (url, file, size, sha256, and
for an archive how to unpack it). Each download lands in ``<cache>/<file>.partial`` and is only
renamed to ``<cache>/<file>`` once its size and SHA-256 match the pin, so a cut-off or tampered
download never reaches the build. A file already in the cache is checked again, not trusted.

    python -I fetch_pinned.py --cache DIR --out DIR energyplus librecad librecad-license
    python -I fetch_pinned.py --verify FILE --name energyplus     (only checks a local file)
    python -I fetch_pinned.py --list

For an item with ``unpack`` (``zip``: Python's zipfile; ``7z``: ``7z x``, the 7-Zip preinstalled
on GitHub's Windows runners, which also reads NSIS installers such as LibreCAD's) the archive is
extracted into a fresh ``<out>/<name>`` and the folder holding ``program`` is reported. With
``GITHUB_OUTPUT`` set (GitHub Actions) it writes ``<name>_file=<path>`` and, for unpacked items,
``<name>_dir=<program folder>`` (dashes in the name become underscores).

Standard library only, so it runs with any Python 3.10+ (``-I``: nothing from the current folder).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = Path(__file__).with_name("third-party-binaries.json")
CHUNK = 1 << 20


class PinError(Exception):
    """A file does not match its pin, or an item is unknown or malformed."""


def load_manifest(path: Path = MANIFEST) -> dict[str, dict]:
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    by_name: dict[str, dict] = {}
    for item in items:
        for key in ("name", "file", "url", "sha256"):
            if not item.get(key):
                raise PinError(f"{path.name}: an item lacks '{key}': {item}")
        sha = item["sha256"].lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise PinError(f"{path.name}: {item['name']} has no valid SHA-256 ({item['sha256']})")
        if item["name"] in by_name:
            raise PinError(f"{path.name}: {item['name']} is listed twice")
        by_name[item["name"]] = item
    return by_name


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, item: dict) -> str:
    """The file's SHA-256 when it matches the item's size and hash; else :class:`PinError`."""
    if not path.is_file():
        raise PinError(f"{path} does not exist")
    size = item.get("size")
    actual_size = path.stat().st_size
    if size is not None and actual_size != size:
        raise PinError(f"{path.name}: {actual_size} bytes, the pin says {size} ({item['name']})")
    actual = sha256_of(path)
    if actual != item["sha256"].lower():
        raise PinError(
            f"SHA-256 mismatch for {path.name} ({item['name']}): expected {item['sha256']}, "
            f"got {actual}"
        )
    return actual


def download(item: dict, cache: Path, opener=urllib.request.urlopen) -> Path:
    """``<cache>/<file>``, downloaded when missing, checked either way."""
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / item["file"]
    if target.is_file():
        try:
            verify(target, item)
            print(f"cached   {target.name}")
            return target
        except PinError as error:
            print(f"stale    {target.name}: {error}; downloading again")
            target.unlink()
    partial = target.with_name(target.name + ".partial")
    request = urllib.request.Request(item["url"], headers={"User-Agent": "saengine-ci"})
    print(f"download {item['url']}")
    with opener(request) as response, partial.open("wb") as handle:
        shutil.copyfileobj(response, handle, CHUNK)
    try:
        verify(partial, item)
    except PinError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    return target


def find_program(root: Path, program: str) -> Path:
    """The shallowest folder under ``root`` that holds ``program`` (case-insensitive)."""
    wanted = program.lower()
    hits = sorted(
        (p for p in root.rglob("*") if p.is_file() and p.name.lower() == wanted),
        key=lambda p: (len(p.relative_to(root).parts), str(p)),
    )
    if not hits:
        raise PinError(f"{program} is not in the unpacked {root}")
    return hits[0].parent


def unpack(archive: Path, item: dict, out: Path, run=subprocess.run) -> Path:
    """Extracts ``archive`` into a fresh ``<out>/<name>``; the folder holding the program."""
    dest = out / item["name"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    kind = item["unpack"]
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                resolved = (dest / member).resolve()
                if not resolved.is_relative_to(dest.resolve()):
                    raise PinError(f"{archive.name}: unsafe path in the archive: {member}")
            zf.extractall(dest)
    elif kind == "7z":
        seven = shutil.which("7z") or shutil.which("7z.exe")
        if seven is None:
            candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip/7z.exe"
            seven = str(candidate) if candidate.is_file() else None
        if seven is None:
            raise PinError("7-Zip (7z) is not on PATH: it unpacks the NSIS installer")
        result = run([seven, "x", "-y", f"-o{dest}", str(archive)], capture_output=True, text=True)
        if result.returncode != 0:
            raise PinError(f"7z x {archive.name} failed ({result.returncode}): {result.stderr}")
    else:
        raise PinError(f"{item['name']}: unknown unpack kind '{kind}'")
    return find_program(dest, item["program"]) if item.get("program") else dest


def write_output(key: str, value: Path) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"{key.replace('-', '_')}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="items of the manifest to fetch")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--cache", type=Path, help="download folder")
    parser.add_argument("--out", type=Path, help="folder for unpacked archives")
    parser.add_argument("--verify", type=Path, help="only check this local file against --name")
    parser.add_argument("--name", help="the manifest item --verify checks against")
    parser.add_argument("--list", action="store_true", help="print the manifest")
    args = parser.parse_args(argv)
    try:
        items = load_manifest(args.manifest)
        if args.list:
            for item in items.values():
                print(f"{item['name']:<18} {item.get('version', ''):<10} {item['url']}")
            return 0
        if args.verify:
            if not args.name or args.name not in items:
                raise PinError(f"--verify needs --name, one of: {', '.join(items)}")
            digest = verify(args.verify, items[args.name])
            print(f"ok       {args.verify.name} matches {args.name} (sha256 {digest})")
            return 0
        if not args.names or not args.cache:
            parser.error("give the item names and --cache (or --verify/--list)")
        for name in args.names:
            if name not in items:
                raise PinError(f"unknown item '{name}', one of: {', '.join(items)}")
            item = items[name]
            path = download(item, args.cache)
            write_output(f"{name}_file", path)
            if item.get("unpack"):
                if not args.out:
                    raise PinError(f"{name} is an archive: give --out")
                folder = unpack(path, item, args.out)
                write_output(f"{name}_dir", folder)
                print(f"unpacked {name} -> {folder}")
    except PinError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
