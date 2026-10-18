"""Copy the minimal EnergyPlus runtime the SAEngine installer bundles, and check it.

SAEngine runs EnergyPlus version 26.2.0 as a separate program (``energyplus.exe``, a
subprocess; never linked) for the HVAC cooling loads of 7 MEP: design-day sizing of an epJSON
model. Only what that needs is bundled into ``resources/energyplus``, where the backend looks for
it (``saengine.hvac.energyplus.find_energyplus``: ``<app>/resources/python/python.exe`` ->
``<app>/resources/energyplus``): the program, its DLLs, the input data dictionary and schema, and
its licence. Documentation, example files, weather data, data sets, EP-Launch, the
pre- and post-processors, the Python API and plug-in library are left out (the runs use none of
them). Measured on EnergyPlus 26.2.0 for Windows x64: 60 files, about 62 MB (the full
distribution is about 890 MB); python312.dll is needed because energyplusapi.dll links it.

    python -I -B energyplus_runtime.py --source <EnergyPlus folder> --dest <app>\\resources\\energyplus
    python -I -B energyplus_runtime.py --dest <folder> --check   (only checks a copy)

``--check`` runs ``energyplus --version`` and a one-zone design-day case from the copy alone
(a 10 x 10 x 3 m box: SAEngine's own epJSON for it, when the saengine package is importable),
so that a missing DLL is found at build time, not by the user.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "26.2.0"
#: The licence's clause (4): the bundled program is referred to by this name only.
NAME = f"EnergyPlus version {VERSION}"
#: The minimal runtime for design-day sizing from epJSON (glob patterns in the distribution's
#: root folder). The api-ms-win-* and ucrtbase files are the Universal C Runtime EnergyPlus ships
#: for older Windows; Windows 10 and 11 have their own, the copies are kept for Windows Server.
FILES = (
    "energyplus.exe",
    "energyplusapi.dll",
    "python312.dll",
    "msvcp140*.dll",
    "vcruntime140*.dll",
    "concrt140.dll",
    "ucrtbase.dll",
    "api-ms-win-*.dll",
    "Energy+.idd",
    "Energy+.schema.epJSON",
    "LICENSE.txt",
)


def copy_runtime(source: Path, dest: Path) -> list[Path]:
    """Copies :data:`FILES` from ``source`` into a fresh ``dest``; the files copied."""
    if not (source / "energyplus.exe").is_file():
        raise SystemExit(f"{source} has no energyplus.exe")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied = []
    for pattern in FILES:
        found = sorted(source.glob(pattern))
        if not found:
            raise SystemExit(f"{source} has no {pattern}")
        for path in found:
            shutil.copy2(path, dest / path.name)
            copied.append(dest / path.name)
    return copied


def check_runtime(dest: Path) -> str:
    """``energyplus --version`` from ``dest`` and, with saengine importable, a design-day run
    of a one-zone box; the version line. Exits on failure."""
    exe = dest / "energyplus.exe"
    done = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, timeout=60, check=False
    )
    line = done.stdout.strip()
    if done.returncode != 0 or VERSION not in line:
        raise SystemExit(f"{exe} --version failed (exit {done.returncode}): {line or done.stderr}")
    try:
        from saengine.hvac import energyplus as EP
        from saengine.verification.cases.hvac_loads import steady_box_model
    except ImportError:
        print("saengine is not importable here: only the version was checked")
        return line
    model, parts = steady_box_model()
    with tempfile.TemporaryDirectory(prefix="saengine-eplus-check-") as work:
        result = EP.run(model, exe, Path(work))
    zone = result["zones"][parts["zone"].name]
    if not zone.get("total", 0) > 0:
        raise SystemExit(f"the design-day check gave no cooling load: {zone}")
    print(f"design-day check: {zone['total']:.2f} kW in {result['seconds']:.1f} s")
    return line


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, help="the extracted EnergyPlus distribution")
    parser.add_argument("--dest", type=Path, required=True, help="resources\\energyplus")
    parser.add_argument("--check", action="store_true", help="check the copy (no --source: only)")
    args = parser.parse_args()
    if args.source is not None:
        files = copy_runtime(args.source, args.dest)
        size = sum(f.stat().st_size for f in files)
        print(f"{NAME}: {len(files)} files, {size / 1e6:.1f} MB copied to {args.dest}")
    if args.check or args.source is None:
        print(check_runtime(args.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
