"""Version, title and assets of an SAEngine pre-release (.github/workflows/release.yml).

python -I release.py version --tag Pre-Alpha-v5 [--version 0.0.35-alpha.5]
    Prints (and writes to GITHUB_OUTPUT) ``version``, ``title`` and ``tag``. The version is
    ``<x.y.z>-alpha.<N>``: x.y.z from HEAD's commit title ``v<x.y.z>`` (a release commit, as
    for every manual release so far), N from the tag ``Pre-Alpha-v<N>``. The title is
    ``Pre Alpha Version <N>``. Fails when HEAD is not a release commit and no --version is
    given, so a release is never cut from an arbitrary commit by accident.

python -I release.py version --tag "" [--version X]
    A test build (workflow_dispatch without a tag): the version is --version or
    ``<x.y.z of workbench/package.json>-ci.<GITHUB_RUN_NUMBER>``, the tag stays empty and the
    title is ``Test build <version>``. Nothing is released from a test build.

python -I release.py assets --tag Pre-Alpha-v5 --version 0.0.35-alpha.5 --out DIR
        [--verification-pdf FILE]
    Collects into DIR the files of the release, named as GitHub shows them (an asset name
    cannot contain spaces): the setup and its .sha256 from dist/, the third-party sources
    folder zipped, Sample.Frame.zip (workbench/resources/saengine/samples/Sample Frame),
    SAEngine.Verification.Manual.pdf, and every file in docs/release/<tag>/ except
    notes.md and title.txt (for example SAEngine.Testing.Guide.pdf, which is written by
    hand for each release). Writes DIR/../release-notes.md from docs/release/<tag>/notes.md
    ({version} and {sha256} are filled in) or from a short default, and prints the list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TAG = re.compile(r"^Pre-Alpha-v(?P<n>[0-9]+)$")
RELEASE_TITLE = re.compile(r"^v(?P<v>[0-9]+\.[0-9]+\.[0-9]+)\s*$")
SAMPLE = Path("workbench/resources/saengine/samples/Sample Frame")
NOTES_FILES = {"notes.md", "title.txt"}

DEFAULT_NOTES = """\
**Alpha software: do not use for real projects.**

## Install
Download `{setup}` (Windows 10/11, 64-bit; no Python, EnergyPlus or CAD program needed).
Uninstall the previous alpha first; your projects are not touched. The setup is not
code-signed yet: on SmartScreen click *More info* then *Run anyway*. SHA-256 (also in the
`.sha256` file):
`{sha256}`

## Files
{files}

Licensed under AGPL-3.0-only. EnergyPlus version 26.2.0 and LibreCAD (GPL-2.0-only, a separate
program for the DXF drawings) are their copyright holders' under their own licences: see
THIRD_PARTY_NOTICES.txt in the installation. The third-party sources zip holds the source of
the copyleft components shipped as binaries.
"""

DESCRIPTIONS = {
    "SAEngine.Testing.Guide.pdf": "what to try and the numbers you should see.",
    "SAEngine.Verification.Manual.pdf": "the benchmarks against theory and hand calculations.",
    "Sample.Frame.zip": "the sample project (also inside the app: *Open Sample Project...*).",
}


class ReleaseError(Exception):
    pass


def git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def release_number(tag: str) -> int:
    match = TAG.match(tag)
    if not match:
        raise ReleaseError(f"tag '{tag}' is not Pre-Alpha-v<N>")
    return int(match["n"])


def release_version(tag: str, explicit: str | None, head_title: str) -> str:
    if explicit:
        if not re.fullmatch(r"[0-9A-Za-z.\-]+", explicit):
            raise ReleaseError(f"version '{explicit}' may only hold letters, digits, . and -")
        return explicit
    match = RELEASE_TITLE.match(head_title)
    if not match:
        raise ReleaseError(
            f"HEAD's commit title is '{head_title}', not a release commit 'v<x.y.z>': "
            "release from a release commit, or give the version"
        )
    return f"{match['v']}-alpha.{release_number(tag)}"


def test_build_version(explicit: str | None, package_version: str, run_number: str) -> str:
    """The version of a build without a release tag (a CI test build)."""
    if explicit:
        return release_version("", explicit, "")
    core = re.match(r"^[0-9]+\.[0-9]+\.[0-9]+", package_version)
    if not core:
        raise ReleaseError(f"workbench/package.json has no x.y.z version ('{package_version}')")
    if not run_number.isdigit():
        raise ReleaseError(f"run number '{run_number}' is not a number")
    return f"{core[0]}-ci.{run_number}"


def write_outputs(values: dict[str, str]) -> None:
    for key, value in values.items():
        print(f"{key}={value}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def zip_folder(folder: Path, target: Path, top: str) -> None:
    """``target`` holding ``folder``'s files under ``top/`` (sorted, so the zip is stable)."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, f"{top}/{path.relative_to(folder).as_posix()}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def collect_assets(
    tag: str,
    version: str,
    out: Path,
    verification_pdf: Path | None = None,
    repo: Path = REPO,
) -> tuple[list[Path], Path]:
    """The asset files in ``out`` and the release notes file."""
    dist = repo / "dist"
    setup = dist / f"SAEngine-x64-user-setup-{version}.exe"
    checksum = setup.with_name(setup.name + ".sha256")
    sources = dist / f"SAEngine-{version}-third-party-sources"
    for required in (setup, checksum, sources):
        if not required.exists():
            raise ReleaseError(
                f"{required} is missing: did build-installer.ps1 run with this version?"
            )
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    assets = [Path(shutil.copy2(setup, out)), Path(shutil.copy2(checksum, out))]
    sources_zip = out / f"{sources.name}.zip"
    zip_folder(sources, sources_zip, sources.name)
    assets.append(sources_zip)
    sample = repo / SAMPLE
    if not sample.is_dir():
        raise ReleaseError(f"the sample project {sample} is missing")
    zip_folder(sample, out / "Sample.Frame.zip", sample.name)
    assets.append(out / "Sample.Frame.zip")
    if verification_pdf is not None:
        if not verification_pdf.is_file():
            raise ReleaseError(f"{verification_pdf} is missing")
        assets.append(
            Path(shutil.copy2(verification_pdf, out / "SAEngine.Verification.Manual.pdf"))
        )
    # A test build has no tag, and so no docs/release/<tag>/ folder.
    extras = repo / "docs" / "release" / tag if tag else None
    notes_template = None
    if extras is not None and extras.is_dir():
        for path in sorted(extras.iterdir()):
            if path.name in NOTES_FILES or not path.is_file():
                continue
            name = path.name.replace(" ", ".")
            assets.append(Path(shutil.copy2(path, out / name)))
        if (extras / "notes.md").is_file():
            notes_template = (extras / "notes.md").read_text(encoding="utf-8")
    sha = checksum.read_text(encoding="ascii").split()[0]
    if sha != sha256_of(setup):
        raise ReleaseError(f"{checksum.name} does not match {setup.name}")
    files = "\n".join(
        f"- `{a.name}`" + (f": {DESCRIPTIONS[a.name]}" if a.name in DESCRIPTIONS else "")
        for a in assets
        if not a.name.endswith(".sha256")
    )
    template = notes_template or DEFAULT_NOTES
    notes = template.replace("{version}", version).replace("{sha256}", sha)
    notes = notes.replace("{setup}", setup.name).replace("{files}", files)
    notes_file = out.parent / "release-notes.md"
    notes_file.write_text(notes, encoding="utf-8")
    return assets, notes_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    version = sub.add_parser("version")
    version.add_argument("--tag", required=True)
    version.add_argument("--version")
    assets = sub.add_parser("assets")
    assets.add_argument("--tag", required=True)
    assets.add_argument("--version", required=True)
    assets.add_argument("--out", required=True, type=Path)
    assets.add_argument("--verification-pdf", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "version" and not args.tag:
            package = json.loads((REPO / "workbench" / "package.json").read_text(encoding="utf-8"))
            value = test_build_version(
                args.version, package["version"], os.environ.get("GITHUB_RUN_NUMBER", "0")
            )
            write_outputs({"tag": "", "version": value, "title": f"Test build {value}"})
        elif args.command == "version":
            number = release_number(args.tag)
            value = release_version(args.tag, args.version, git("log", "-1", "--format=%s"))
            title_file = REPO / "docs" / "release" / args.tag / "title.txt"
            title = (
                title_file.read_text(encoding="utf-8").strip()
                if title_file.is_file()
                else f"Pre Alpha Version {number}"
            )
            write_outputs({"tag": args.tag, "version": value, "title": title})
        else:
            files, notes = collect_assets(args.tag, args.version, args.out, args.verification_pdf)
            for path in files:
                print(f"asset {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
            print(f"notes {notes}")
            write_outputs({"notes": str(notes), "assets": str(args.out)})
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
