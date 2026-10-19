"""Copy LibreCAD into the SAEngine app folder as a separate program, with its licences.

LibreCAD (GPL-2.0-only) edits the DXF drawings SAEngine exports ("Open in LibreCAD"). It is
shipped next to SAEngine as a separate program in ``resources/librecad`` and started as its own
process with the drawing's path; nothing of it is linked into SAEngine (an aggregate, GPL-2.0
section 2). Its program folder holds Qt 5 DLLs (LGPL-3.0), which LibreCAD links dynamically.

    python -I -B librecad_bundle.py --source <LibreCAD folder> --dest <app>\\resources\\librecad
        [--license FILE ...] [--expect-version 2.2.1.6] [--require-licenses] [--dry-run]

``--source`` is an installed LibreCAD (``C:\\Program Files\\LibreCAD``) or its NSIS installer
unpacked with ``7z x``; the folder holding ``LibreCAD.exe`` is found inside it. Copied: the
program folder (``LibreCAD.exe``, the Qt DLLs, the Qt plug-in folders, ``resources``), without
what only the installer uses (NSIS's ``$PLUGINSDIR``, the uninstaller) and debug symbols, and
by default trimmed (:data:`TRIM`: the Visual C++ redistributable installer and the CJK fonts;
translations other than English), which takes LibreCAD 2.2.1.6 from 321 MB to about 110 MB.
``--vc-runtime`` copies the Visual C++ runtime DLLs next to LibreCAD.exe instead of its
redistributable installer. LibreCAD's installer ships no licence file (its licences are
compiled in), so the release build passes the texts with ``--license`` (LibreCAD's LICENSE and
gpl-2.0.txt, Qt's LICENSE.LGPLv3 and LICENSE.GPL3, pinned in scripts/ci/third-party-binaries.json);
they go to ``resources/librecad/licenses``, together with any licence file the source has.

Writes ``resources/librecad/SAENGINE-BUNDLE.json``: the LibreCAD and Qt versions (from the
version resources of ``LibreCAD.exe`` and ``Qt5Core.dll``), the Qt modules it ships (which
decide the Qt source archives fetch-sources.ps1 collects), the licence files, file count and
size. write_notices.py and fetch-sources.ps1 read it. ``--dry-run`` prints the plan and copies
nothing.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

PROGRAM = "LibreCAD.exe"
MANIFEST_NAME = "SAENGINE-BUNDLE.json"
#: Never copied: what only the NSIS installer uses, the uninstaller, debug symbols.
EXCLUDE = ("$*", "uninstall*.exe", "uninst*.exe", "*.pdb", MANIFEST_NAME)
LICENSE_PREFIXES = ("license", "licence", "copying", "gpl", "lgpl", "qt-license")
#: Left out of a trimmed bundle (the default), paths relative to the program folder: the
#: Visual C++ redistributable installer (the runtime DLLs are copied app-local instead, see
#: ``vc_runtime``) and the CJK fonts (151 of LibreCAD 2.2.1.6's 321 MB; a DXF that names one
#: falls back to LibreCAD's standard font).
TRIM = (
    "vc_redist*.exe",
    "resources/fonts/noto-sans-sc.lff",
    "resources/fonts/noto-sans-tc.lff",
    "resources/fonts/wqy-microhei.lff",
)
#: The translations a trimmed bundle keeps (LibreCAD's resources/qm and Qt's translations).
KEEP_LANGUAGES = ("en", "en_au")
#: The Visual C++ runtime DLLs copied next to LibreCAD.exe from a Microsoft.VC14x.CRT
#: redistributable folder (Visual Studio's VC\Redist\MSVC\<version>\x64), app-local.
VC_RUNTIME = ("msvcp140*.dll", "vcruntime140*.dll", "concrt140.dll")

#: Qt module (source archive ``<module>-everywhere-src-<version>``) of each Qt DLL or plug-in.
QT_DLL_MODULES = {
    "core": "qtbase",
    "gui": "qtbase",
    "widgets": "qtbase",
    "printsupport": "qtbase",
    "network": "qtbase",
    "sql": "qtbase",
    "xml": "qtbase",
    "opengl": "qtbase",
    "concurrent": "qtbase",
    "dbus": "qtbase",
    "test": "qtbase",
    "svg": "qtsvg",
    "help": "qttools",
    "designer": "qttools",
    "uitools": "qttools",
    "multimedia": "qtmultimedia",
    "charts": "qtcharts",
    "xmlpatterns": "qtxmlpatterns",
    "winextras": "qtwinextras",
    "quick": "qtdeclarative",
    "qml": "qtdeclarative",
}
QT_PLUGIN_MODULES = {
    "qsvg": "qtsvg",
    "qsvgicon": "qtsvg",
    "qtiff": "qtimageformats",
    "qwebp": "qtimageformats",
    "qicns": "qtimageformats",
    "qtga": "qtimageformats",
    "qwbmp": "qtimageformats",
}


class BundleError(Exception):
    pass


def find_program_dir(source: Path) -> Path:
    """The shallowest folder under ``source`` (or ``source`` itself) holding LibreCAD.exe."""
    if (source / PROGRAM).is_file():
        return source
    hits = sorted(
        (p.parent for p in source.rglob("*") if p.is_file() and p.name.lower() == PROGRAM.lower()),
        key=lambda p: (len(p.relative_to(source).parts), str(p)),
    )
    if not hits:
        raise BundleError(f"{source} holds no {PROGRAM}")
    return hits[0]


def excluded(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in EXCLUDE)


def trimmed(relative: Path) -> bool:
    """Whether a trimmed bundle leaves ``relative`` out (see :data:`TRIM`, :data:`KEEP_LANGUAGES`)."""
    posix = relative.as_posix().lower()
    if any(fnmatch.fnmatch(posix, pattern) for pattern in TRIM):
        return True
    folder = relative.parent.as_posix().lower()
    if relative.suffix.lower() == ".qm" and folder in ("resources/qm", "translations"):
        language = relative.stem.lower().split("_", 1)[1] if "_" in relative.stem else ""
        return language not in KEEP_LANGUAGES
    return False


def plan(root: Path, trim: bool = True) -> list[Path]:
    """The files to copy, relative to the program folder."""
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(excluded(part) for part in relative.parts):
            continue
        if trim and trimmed(relative):
            continue
        if path.is_file():
            files.append(relative)
    return files


def vc_runtime_files(folder: Path) -> list[Path]:
    """The runtime DLLs of a Microsoft.VC14x.CRT folder (an error when it has none)."""
    if not folder.is_dir():
        raise BundleError(f"{folder} is not a folder: expected a Microsoft.VC14x.CRT folder")
    found = sorted(
        p for p in folder.iterdir()
        if p.is_file() and any(fnmatch.fnmatch(p.name.lower(), pattern) for pattern in VC_RUNTIME)
    )  # fmt: skip
    if not any(p.name.lower() == "vcruntime140.dll" for p in found):
        raise BundleError(f"{folder} holds no vcruntime140.dll: not a Microsoft.VC14x.CRT folder")
    return found


def file_version(path: Path) -> str | None:
    """``a.b.c.d`` from the PE version resource (Windows only; None elsewhere or without one)."""
    if sys.platform != "win32" or not path.is_file():
        return None
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version.dll")
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    info = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length)):
        return None
    if length.value < 52:
        return None
    fixed = ctypes.cast(info, ctypes.POINTER(wintypes.DWORD * 13)).contents
    if fixed[0] != 0xFEEF04BD:
        return None
    ms, ls = fixed[2], fixed[3]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def qt_inventory(root: Path, files: list[Path]) -> tuple[str | None, str | None, list[str]]:
    """``(Qt major, Qt version, Qt modules)`` of the files to ship."""
    major = None
    modules: set[str] = set()
    for relative in files:
        name = relative.name.lower()
        stem = name.removesuffix(".dll")
        if not name.endswith(".dll"):
            continue
        for candidate in ("qt5", "qt6"):
            if len(relative.parts) == 1 and stem.startswith(candidate) and len(stem) > 3:
                major = major or candidate[-1]
                module = stem[3:]
                if module.endswith("d") and module[:-1] in QT_DLL_MODULES:  # debug builds
                    module = module[:-1]
                modules.add(QT_DLL_MODULES.get(module, "qtbase"))
        if len(relative.parts) > 1 and stem in QT_PLUGIN_MODULES:
            modules.add(QT_PLUGIN_MODULES[stem])
        elif len(relative.parts) > 1 and stem.startswith("q"):
            modules.add("qtbase")
    if major is None:
        return None, None, []
    raw = file_version(root / f"Qt{major}Core.dll")
    qt_version = ".".join(raw.split(".")[:3]) if raw else None
    return major, qt_version, sorted(modules)


def is_license(name: str) -> bool:
    return name.lower().startswith(LICENSE_PREFIXES)


def bundle(
    source: Path,
    dest: Path,
    licenses: list[Path] | None = None,
    expect_version: str | None = None,
    require_licenses: bool = False,
    dry_run: bool = False,
    trim: bool = True,
    vc_runtime: Path | None = None,
) -> dict:
    """Copies LibreCAD into a fresh ``dest`` (unless ``dry_run``); the bundle manifest.

    ``trim`` leaves out :data:`TRIM` and the translations outside :data:`KEEP_LANGUAGES`;
    ``vc_runtime`` (a Microsoft.VC14x.CRT folder) puts the Visual C++ runtime DLLs next to
    LibreCAD.exe, which a trimmed bundle needs on a PC without the runtime installed."""
    root = find_program_dir(source)
    files = plan(root, trim)
    runtime = vc_runtime_files(vc_runtime) if vc_runtime else []
    if trim and not runtime:
        print(
            "warning: the trimmed bundle has no Visual C++ runtime (pass --vc-runtime): LibreCAD "
            "starts only where the Visual C++ 2015-2022 runtime is installed"
        )
    licenses = list(licenses or [])
    for path in licenses:
        if not path.is_file():
            raise BundleError(f"licence file {path} does not exist")
    version = file_version(root / PROGRAM)
    if expect_version and version and version != expect_version:
        raise BundleError(f"{root / PROGRAM} is version {version}, expected {expect_version}")
    major, qt_version, qt_modules = qt_inventory(root, files)
    if major is None:
        print(f"warning: no Qt core DLL next to {PROGRAM}: is this a complete LibreCAD folder?")
    if not any(f.as_posix().lower() == "platforms/qwindows.dll" for f in files):
        print("warning: platforms/qwindows.dll is missing: LibreCAD will not start without it")
    shipped_licenses = sorted(
        {f.as_posix() for f in files if is_license(f.name)}
        | {f"licenses/{p.name}" for p in licenses}
    )
    has_gpl2 = any("gpl-2" in name.lower() for name in shipped_licenses)
    if require_licenses and (not shipped_licenses or not has_gpl2):
        raise BundleError(
            "no licence text for LibreCAD: pass --license with LibreCAD's LICENSE and gpl-2.0.txt "
            "(scripts/ci/fetch_pinned.py librecad-license librecad-gpl-2.0)"
        )
    if not shipped_licenses:
        print("warning: no licence text is bundled with LibreCAD (pass --license)")
    size = (
        sum((root / f).stat().st_size for f in files)
        + sum(p.stat().st_size for p in licenses)
        + sum(p.stat().st_size for p in runtime)
    )
    manifest = {
        "name": "LibreCAD",
        "version": version or expect_version or "unknown",
        "license": "GPL-2.0-only",
        "qt_major": major,
        "qt_version": qt_version,
        "qt_license": "LGPL-3.0-only" if major else None,
        "qt_modules": qt_modules,
        "program": PROGRAM,
        "licenses": shipped_licenses,
        "trimmed": trim,
        # Microsoft's Visual C++ redistributable DLLs ("Distributable Code" of Visual Studio).
        "vc_runtime": {
            "files": [p.name for p in runtime],
            "version": file_version(next(p for p in runtime if p.name.lower() == "vcruntime140.dll")),
        } if runtime else None,
        "files": len(files) + len(licenses) + len(runtime),
        "bytes": size,
        "source": str(root),
    }  # fmt: skip
    print(
        f"LibreCAD {manifest['version']} (Qt {qt_version or '?'}; modules "
        f"{', '.join(qt_modules) or '-'}): {manifest['files']} files, {size / 1e6:.1f} MB"
        f"{' (dry run: nothing copied)' if dry_run else ''}"
    )
    if dry_run:
        for relative in files[:20]:
            print(f"  copy {relative.as_posix()}")
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more")
        for path in licenses:
            print(f"  licence {path} -> licenses/{path.name}")
        for path in runtime:
            print(f"  runtime {path} -> {path.name}")
        return manifest
    if dest.exists():
        shutil.rmtree(dest)
    for relative in files:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    for path in runtime:
        shutil.copy2(path, dest / path.name)
    if licenses:
        (dest / "licenses").mkdir(parents=True, exist_ok=True)
        for path in licenses:
            shutil.copy2(path, dest / "licenses" / path.name)
    if not (dest / PROGRAM).is_file():
        raise BundleError(f"{dest / PROGRAM} is missing after the copy")
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-trim", action="store_true", help="copy the whole program folder")
    parser.add_argument("--vc-runtime", type=Path, help="a Microsoft.VC14x.CRT folder")
    args = parser.parse_args(argv)
    try:
        bundle(
            args.source,
            args.dest,
            args.license,
            args.expect_version,
            args.require_licenses,
            args.dry_run,
            trim=not args.no_trim,
            vc_runtime=args.vc_runtime,
        )
    except BundleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
