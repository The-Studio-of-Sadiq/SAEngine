"""Write THIRD_PARTY_NOTICES.txt for the Python bundled with the SAEngine installer.

Run it with the bundled interpreter in isolated mode, so it lists exactly the distributions that
ship:  python -I write_notices.py --out THIRD_PARTY_NOTICES.txt --version 0.0.25

Licence data comes from each distribution's own metadata (importlib.metadata): the SPDX
License-Expression when present, else the License field, else the trove classifiers, followed by
the full text of every licence file the distribution ships.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from importlib import metadata
from pathlib import Path

SOURCE_URL = "https://github.com/princekhan7748/saengine"
RULE = "=" * 100

HEADER = """\
SAEngine {version} - third-party notices
{rule}

SAEngine is free software: you can redistribute it and/or modify it under the terms of the GNU
Affero General Public License version 3 (AGPL-3.0-only). The full licence is in LICENSE.txt next
to this file.

Source code offer (AGPL-3.0 section 6 and 13): the complete corresponding source of this build,
including the build scripts that produced this installer, is available at
    {source}
(commit {commit}). The same source is available from the SAEngine contributors on request.

This installation contains four groups of third-party software:

1. The Code - OSS workbench (MIT, Copyright Microsoft Corporation) and its Node.js
   dependencies: see resources/app/LICENSE.txt and resources/app/ThirdPartyNotices.txt.
2. Electron and Chromium: see LICENSES.chromium.html and LICENSE.electron.txt (when present).
3. The SAEngine viewer bundles in resources/app/node_modules.asar (@saengine/fem-viewer,
   @saengine/cad-editor): JavaScript, WebAssembly and fonts from three.js, That Open,
   web-ifc, mlightcad and others. They are listed under "Bundled JavaScript, WebAssembly and
   fonts" below, with their licence texts.
4. A self-contained CPython {python} with the SAEngine analysis backend, in resources/python.
   Its packages are listed under "Bundled Python packages" below, with their licence texts.

Copyleft components shipped as binaries, and where their source is:
{copyleft}
  The source archives of exactly these versions are published from the same place as this
  installer, in the folder {sources_name} (see README.txt in it).
  Written offer: for at least three years after the SAEngine contributors distribute this
  version, they will give any third party, on request (open an issue at {source}/issues),
  a complete machine-readable copy of the corresponding source code of these components, for
  a charge no more than the cost of physically performing that distribution.
  ifcopenshell and cytriangle are shipped unmodified as separate Python packages, which you may
  replace with modified versions.

Other licence terms to note:
  - OpenSeesPy (openseespy, openseespywin) is free for research, education and internal use;
    its licence requires a separate licence for commercial redistribution. See its text below.
  - cytriangle contains Triangle by Jonathan Richard Shewchuk, whose licence permits
    distribution as part of a commercial system only by direct arrangement with the author.
  - SAEngine and opensees-studio are AGPL-3.0; see the source offer above.

{rule}
"""

# Shown in the header; the archives themselves are listed in copyleft-sources.json.
COPYLEFT_FALLBACK = "  (see copyleft-sources.json; no list was given to this script)\n"


def declared_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    text = (meta.get("License") or "").strip()
    # Some packages put the whole licence text in the License field (keep its first line only),
    # others the name of their licence file (no information: fall through to the classifiers).
    names_a_file = text.lower().startswith(("license", "licence", "copying")) and "." in text
    if text and "\n" not in text and len(text) <= 80 and not names_a_file:
        return text
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    if text and not names_a_file:
        return text.splitlines()[0].strip()
    return "see the licence text below"


def license_files(dist: metadata.Distribution) -> list[Path]:
    """Licence and notice files of the distribution.

    Those in its metadata folder; when there are none, licence files anywhere among its
    installed files (openseespy ships `openseespy/LICENSE.md`, gmsh `share/doc/gmsh/LICENSE.txt`).
    """
    in_meta, elsewhere = [], []
    for file in dist.files or []:
        parts = [p.lower() for p in file.parts]
        name = parts[-1]
        is_license = name.startswith(("license", "licence", "copying", "notice"))
        if parts[0].endswith((".dist-info", ".egg-info")):
            if is_license or name.startswith("authors") or "licenses" in parts:
                in_meta.append(file)
        elif is_license and not name.endswith((".py", ".pyc")):
            elsewhere.append(file)
    paths = [Path(str(f.locate())) for f in (in_meta or elsewhere)]
    return sorted(p for p in paths if p.is_file())


def homepage(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("Home-page"):
        return meta["Home-page"]
    for url in meta.get_all("Project-URL") or []:
        label, _, value = url.partition(",")
        if label.strip().lower() in {"homepage", "home", "source", "repository", "source code"}:
            return value.strip()
    return ""


def lgpl3_holder(dists: list[metadata.Distribution]) -> str:
    """Name of a bundled distribution whose licence file is the full LGPL-3.0 text, if any."""
    for dist in dists:
        for path in license_files(dist):
            head = path.read_text(encoding="utf-8", errors="replace")[:400]
            if "GNU LESSER GENERAL PUBLIC LICENSE" in head and "Version 3" in head:
                return dist.metadata["Name"]
    return ""


def missing_license_note(name: str, declared: str, lgpl3: str) -> str:
    """What stands in for the licence text of a distribution that ships none."""
    if name.lower() in {"saengine", "opensees-studio"}:
        return "AGPL-3.0: the full licence text is LICENSE.txt next to this file.\n"
    if "LGPL" in declared.upper() or "LESSER GENERAL PUBLIC" in declared.upper():
        where = (
            f"is reproduced in this file under {lgpl3}"
            if lgpl3
            else "is at https://www.gnu.org/licenses/lgpl-3.0.txt"
        )
        return (
            "The package ships no licence file. Its licence, the GNU LGPL version 3 or later, "
            f"{where};\nthe GNU GPL version 3 it supplements is at "
            "https://www.gnu.org/licenses/gpl-3.0.txt .\n"
        )
    return "(The package ships no licence file; see its declared licence above.)\n"


def copyleft_lines(manifest: Path | None) -> str:
    if manifest is None or not manifest.is_file():
        return COPYLEFT_FALLBACK
    sources = json.loads(manifest.read_text(encoding="utf-8"))["sources"]
    return "".join(
        f"  - {s['name']} {s['version']}: {s['license']}; upstream source {s['url']}\n"
        for s in sources
    )


def npm_package_root(path: Path) -> Path | None:
    """The package folder of a file inside node_modules (scoped names included)."""
    parts = path.parts
    indexes = [i for i, part in enumerate(parts) if part == "node_modules"]
    if not indexes:
        return None
    i = indexes[-1]
    depth = 3 if len(parts) > i + 1 and parts[i + 1].startswith("@") else 2
    if len(parts) < i + depth:
        return None
    return Path(*parts[: i + depth])


def bundled_npm_packages(package_dir: Path) -> list[Path]:
    """Folders of the npm packages whose code or files end up in <package_dir>/dist.

    The modules esbuild bundled come from the source maps; the files the build copies as they
    are (workers, WebAssembly, fonts) from the node_modules paths named in build.mjs.
    """
    roots: set[Path] = set()
    for source_map in sorted((package_dir / "dist").glob("*.map")):
        data = json.loads(source_map.read_text(encoding="utf-8"))
        base = source_map.parent / (data.get("sourceRoot") or "")
        for source in data.get("sources", []):
            if "node_modules/" not in source:
                continue
            root = npm_package_root(Path(os.path.normpath(base / source)))
            if root is None:
                continue
            if not (root / "package.json").is_file():
                # Paths taken over from a dependency's own source map can be off by a folder
                # (fragments: "node_modules/node_modules/pako"): look the name up at the top.
                scoped = root.parent.name.startswith("@")
                name = Path(root.parent.name, root.name) if scoped else Path(root.name)
                root = package_dir / "node_modules" / name
            roots.add(root)
    build = package_dir / "build.mjs"
    if build.is_file():
        for name in re.findall(
            r"node_modules/((?:@[\w.\-]+/)?[\w.\-]+)/", build.read_text("utf-8")
        ):
            roots.add(package_dir / "node_modules" / Path(name))
    return sorted(r for r in roots if (r / "package.json").is_file())


def npm_license(meta: dict) -> str:
    value = meta.get("license") or meta.get("licenses") or ""
    if isinstance(value, dict):
        value = value.get("type", "")
    if isinstance(value, list):
        value = " OR ".join(v.get("type", "") if isinstance(v, dict) else str(v) for v in value)
    return str(value) or "see the licence text below"


def npm_homepage(meta: dict) -> str:
    repository = meta.get("repository")
    if isinstance(repository, dict):
        repository = repository.get("url", "")
    url = meta.get("homepage") or repository or ""
    return str(url).removeprefix("git+")


def npm_license_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.iterdir()
        if p.is_file()
        and p.name.lower().startswith(("license", "licence", "copying", "notice"))
        and not p.name.lower().endswith((".js", ".ts", ".json"))
    )


def js_section(package_dirs: list[Path]) -> tuple[list[str], int]:
    """Listing, licence texts and esbuild legal comments of the SAEngine viewer bundles."""
    entries: dict[tuple[str, str], tuple[dict, Path, set[str]]] = {}
    for package_dir in package_dirs:
        owner = json.loads((package_dir / "package.json").read_text("utf-8"))["name"]
        for root in bundled_npm_packages(package_dir):
            meta = json.loads((root / "package.json").read_text("utf-8"))
            key = (meta["name"], meta.get("version", ""))
            entries.setdefault(key, (meta, root, set()))[2].add(owner)
    if not entries:
        return [], 0
    out = ["\nBundled JavaScript, WebAssembly and fonts (resources/app/node_modules.asar)\n\n"]
    width = max(len(name) for name, _ in entries) + 2
    for (name, version), (meta, _, owners) in sorted(entries.items()):
        out.append(
            f"  {name:<{width}}{version:<14}{npm_license(meta)}  [{', '.join(sorted(owners))}]\n"
        )
    out.append(f"\n{RULE}\n")
    for (name, version), (meta, root, _) in sorted(entries.items()):
        out.append(f"\n{name} {version}\nLicence: {npm_license(meta)}\n")
        if npm_homepage(meta):
            out.append(f"Home: {npm_homepage(meta)}\n")
        out.append("-" * 100 + "\n")
        files = npm_license_files(root)
        if not files:
            out.append("(The package ships no licence file; see its declared licence above.)\n")
        for path in files:
            out.append(f"[{path.name}]\n")
            out.append(path.read_text(encoding="utf-8", errors="replace").rstrip() + "\n\n")
        out.append(RULE + "\n")
    # Code that the bundled packages had already inlined from others (for example mlightcad's
    # copy of feross/buffer): esbuild collects its licence comments into *.LEGAL.txt.
    for package_dir in package_dirs:
        for legal in sorted((package_dir / "dist").glob("*.LEGAL.txt")):
            out.append(
                f"\nLicence comments collected by esbuild from {legal.name.removesuffix('.LEGAL.txt')}\n"
            )
            out.append("-" * 100 + "\n")
            out.append(legal.read_text(encoding="utf-8", errors="replace").rstrip() + "\n")
            out.append(RULE + "\n")
    return out, len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--version", default="")
    parser.add_argument("--commit", default="unknown")
    parser.add_argument(
        "--python-license", type=Path, help="CPython's own LICENSE.txt (python-build-standalone)"
    )
    parser.add_argument(
        "--js-package",
        type=Path,
        action="append",
        default=[],
        help="an SAEngine npm package (packages/fem-viewer) whose dist/ the app ships",
    )
    parser.add_argument(
        "--copyleft-sources", type=Path, help="scripts/installer/copyleft-sources.json"
    )
    parser.add_argument(
        "--sources-name", default="third-party-sources", help="folder of the source archives"
    )
    args = parser.parse_args()

    dists = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name and name.lower() not in dists:
            dists[name.lower()] = dist
    ordered = [dists[k] for k in sorted(dists)]

    python = ".".join(map(str, sys.version_info[:3]))
    out = [
        HEADER.format(
            version=args.version,
            rule=RULE,
            source=SOURCE_URL,
            commit=args.commit,
            python=python,
            copyleft=copyleft_lines(args.copyleft_sources),
            sources_name=args.sources_name,
        )
    ]
    js_out, js_count = js_section(args.js_package)
    out.extend(js_out)
    out.append("Bundled Python packages\n\n")
    width = max(len(d.metadata["Name"]) for d in ordered) + 2
    out.append(f"  {'CPython':<{width}}{python:<14}PSF-2.0\n")
    for dist in ordered:
        out.append(
            f"  {dist.metadata['Name']:<{width}}{dist.version:<14}{declared_license(dist)}\n"
        )
    out.append(f"\n{RULE}\n")

    if args.python_license and args.python_license.is_file():
        out.append(f"\nCPython {python}\n{'-' * 100}\n")
        out.append(args.python_license.read_text(encoding="utf-8", errors="replace"))
        out.append(f"\n{RULE}\n")

    lgpl3 = lgpl3_holder(ordered)
    missing = []
    for dist in ordered:
        name = dist.metadata["Name"]
        out.append(f"\n{name} {dist.version}\n")
        out.append(f"Licence: {declared_license(dist)}\n")
        if homepage(dist):
            out.append(f"Home: {homepage(dist)}\n")
        out.append("-" * 100 + "\n")
        files = license_files(dist)
        if not files:
            missing.append(name)
            out.append(missing_license_note(name, declared_license(dist), lgpl3))
        for path in files:
            out.append(f"[{path.name}]\n")
            out.append(path.read_text(encoding="utf-8", errors="replace").rstrip() + "\n\n")
        out.append(RULE + "\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(out), encoding="utf-8", newline="\r\n")
    print(f"{len(ordered)} Python and {js_count} npm packages written to {args.out}")
    if missing:
        print("No licence file shipped by: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
