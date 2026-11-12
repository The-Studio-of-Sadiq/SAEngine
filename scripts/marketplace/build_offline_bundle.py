"""Build the offline bundle of the package index (docs/marketplace-plan.md §7, round M8).

Offices with slow or metered connections install packages from one file: a zip with the signed
``index.json``, its ``index.json.sig`` and every package zip the index names, under
``packages/``. In SAEngine, *Packages › Install from File...* on the bundle shows its packages in
Browse; the index's signature and every zip's size and SHA-256 are checked exactly as online.

The ``saengine-index`` release attaches it as ``saengine-packages-offline-<date>.zip``. Standard
library only; run it with ``python -I``::

    python -I build_offline_bundle.py --index index.json --zips release-assets/ --out dist
    python -I build_offline_bundle.py --index index.json --download --out dist

``--zips``: a folder that already holds the package zips (named as in their URLs);
``--download``: fetch each from its URL (HTTPS on GitHub only). Every zip is checked against the
index before it goes into the bundle; a mismatch stops the build. The signature is not checked
here (the app checks it); ``index.json.sig`` must sit beside ``index.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _name(url: str) -> str:
    return Path(urllib.parse.urlparse(url).path).name


def _fetch(url: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS:
        raise SystemExit(f"{url}: only HTTPS on {', '.join(HOSTS)}")
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def collect(index: dict, zips: Path | None, download: bool) -> dict[str, bytes]:
    """File name -> bytes of every package zip of the index, checked against it."""
    files: dict[str, bytes] = {}
    for entry in index.get("packages", []):
        url, size, sha = entry.get("url", ""), entry.get("size"), entry.get("sha256", "")
        name = _name(url)
        if not name.endswith(".zip"):
            raise SystemExit(f"{entry.get('id')}: its URL does not name a zip")
        if name in files:
            continue
        if zips is not None and (zips / name).is_file():
            data = (zips / name).read_bytes()
        elif download:
            data = _fetch(url)
        else:
            raise SystemExit(f"{name} is not in {zips} (or use --download)")
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit(f"{name} does not match the index's size and SHA-256")
        files[name] = data
    return files


def build(index_path: Path, files: dict[str, bytes], out: Path, date: str) -> Path:
    sig = Path(f"{index_path}.sig")
    if not sig.is_file():
        raise SystemExit(f"{sig} is missing: an unsigned index is never used by SAEngine")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"saengine-packages-offline-{date}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in [
            ("index.json", index_path.read_bytes()),
            ("index.json.sig", sig.read_bytes()),
            *((f"packages/{n}", files[n]) for n in sorted(files)),
        ]:
            info = zipfile.ZipInfo(arcname, _FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--zips", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    args = parser.parse_args(argv)
    index = json.loads(args.index.read_text(encoding="utf-8"))
    if index.get("schema") != "saengine.packageIndex/1":
        raise SystemExit(f"{args.index} is not a saengine.packageIndex/1 document")
    files = collect(index, args.zips, args.download)
    dest = build(args.index, files, args.out, args.date)
    print(f"{dest}: {len(files)} packages, {dest.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
