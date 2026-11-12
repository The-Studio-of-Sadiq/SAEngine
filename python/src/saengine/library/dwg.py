"""DWG drawings (AutoCAD's own format), read as DXF through GNU LibreDWG's ``dwg2dxf``.

Architects send DWG. SAEngine reads DXF (ezdxf here, the CAD editor in the workbench), so a DWG
is converted to DXF first by ``dwg2dxf`` of GNU LibreDWG (GPL-3.0-or-later): a separate program
shipped next to SAEngine (``<app>/resources/libredwg``) and started as its own process, never
linked into SAEngine, like LibreCAD. LibreDWG reads DWG up to R2018 (AC1032, the format of
AutoCAD 2018 to today's releases; tested from R2000); objects it cannot read yet (some styles,
proxy objects) are skipped and counted in the warnings, the geometry is kept.

Writing DWG (the drawing sheets, :func:`write_dwg`) is the other direction, by ``dxf2dwg`` of
the same LibreDWG, found the same way (:func:`find_writer`), also run as its own process. It
writes AutoCAD R2000 DWG (AC1015), which every current CAD program opens; its DWG writer is
younger than its reader, so the DXF stays the sheet's master file and the DWG a copy for issue.

Where ``dwg2dxf`` is (:func:`find_converter`): the ``SAENGINE_LIBREDWG`` environment variable
(the folder or the exe), then the copy bundled with SAEngine (``<app>/resources/libredwg``, next
to the bundled ``resources/python``), then ``dwg2dxf`` on the ``PATH``.

:func:`convert` writes ``<name>.dwg.dxf`` into a ``.dwg-cache`` folder beside the DWG (a
computed cache: left out of archives and versions, see
:data:`saengine.project.archive.COMPUTED_PATHS`) and converts again only when the DWG changed.
:func:`converted` converts into a temporary folder instead, for files read once (imports).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

ENV_VAR = "SAENGINE_LIBREDWG"
EXE = "dwg2dxf.exe" if os.name == "nt" else "dwg2dxf"
WRITER = "dxf2dwg.exe" if os.name == "nt" else "dxf2dwg"
#: A DWG of a few MB converts in seconds; this bounds a file the converter loops on.
TIMEOUT = 120.0
CACHE_FOLDER = ".dwg-cache"
#: The first bytes of every DWG version (``AC1015`` R2000 ... ``AC1032`` R2018).
MAGIC = b"AC1"
#: At most this many of the converter's error lines are passed on.
MAX_ERRORS = 5


class DwgError(RuntimeError):
    """The DWG could not be converted; the message says why, for the user."""


class ConverterMissing(DwgError):
    """No ``dwg2dxf`` was found."""


@dataclass
class Conversion:
    """A DWG converted to DXF: the DXF, what the converter reported, whether it was cached."""

    dxf: Path
    warnings: list[str] = field(default_factory=list)
    cached: bool = False

    def to_json(self) -> dict[str, object]:
        return {"dxf": str(self.dxf), "warnings": self.warnings, "cached": self.cached}


def bundled_dir() -> Path:
    """Where the setup's *DWG import* component puts ``dwg2dxf``:
    ``<app>/resources/python/python.exe`` -> ``<app>/resources/libredwg``."""
    return Path(sys.executable).resolve().parent.parent / "libredwg"


def _candidates(program: str = "dwg2dxf") -> list[Path]:
    out: list[Path] = []
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(Path(env))
    out.append(bundled_dir())
    found = shutil.which(program)
    if found:
        out.append(Path(found))
    return out


def _find(name: str, explicit: str | Path | None) -> Path | None:
    for candidate in ([Path(explicit)] if explicit else []) + _candidates(Path(name).stem):
        # a folder, or one of LibreDWG's programs (its sibling is beside it)
        if candidate.suffix.lower() in (".exe", "") and candidate.name.lower().startswith(
            ("dwg2dxf", "dxf2dwg")
        ):
            candidate = candidate.parent
        exe = candidate / name
        try:
            if exe.is_file():
                return exe
        except OSError:
            continue
    return None


def find_converter(explicit: str | Path | None = None) -> Path | None:
    """The ``dwg2dxf`` executable (``explicit``: a folder or the exe, before the others), or
    None when there is none."""
    return _find(EXE, explicit)


def find_writer(explicit: str | Path | None = None) -> Path | None:
    """The ``dxf2dwg`` executable (``explicit``: a folder or a LibreDWG exe, before the
    others), or None when there is none."""
    return _find(WRITER, explicit)


def is_dwg(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".dwg"


def _summary(output: str) -> list[str]:
    """The converter's report in a few lines: its errors, and how many objects it skipped."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    errors = list(dict.fromkeys(line for line in lines if line.upper().startswith("ERROR")))
    warnings = sum(1 for line in lines if line.lower().startswith("warning"))
    out = errors[:MAX_ERRORS]
    if len(errors) > MAX_ERRORS:
        out.append(f"... and {len(errors) - MAX_ERRORS} more errors")
    if warnings:
        out.append(
            f"LibreDWG reported {warnings} warning(s), mostly objects it skips (styles, "
            "materials, proxies); the drawing's geometry is kept"
        )
    return out


def _run(exe: Path, dwg: Path, dxf: Path, timeout: float) -> list[str]:
    """Converts ``dwg`` to ``dxf`` (replaced only when the conversion succeeds)."""
    try:
        head = dwg.read_bytes()[:6]
    except OSError as exc:
        raise DwgError(f"{dwg.name} could not be read: {exc.strerror or exc}") from exc
    if not head.startswith(MAGIC):
        raise DwgError(f"{dwg.name} is not a DWG drawing")
    dxf.parent.mkdir(parents=True, exist_ok=True)
    # The converter gets plain ASCII names relative to its working folder: it takes its
    # arguments in the ANSI code page, in which a Bangla file or folder name cannot be written.
    with tempfile.TemporaryDirectory(prefix="dwg-", dir=dxf.parent) as tmp:
        work = Path(tmp)
        shutil.copyfile(dwg, work / "in.dwg")
        try:
            done = subprocess.run(
                [str(exe), "-y", "-o", "out.dxf", "in.dwg"],
                cwd=work,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DwgError(
                f"{dwg.name}: the DWG converter did not finish within {timeout:g} s "
                "(save the drawing as DXF in the CAD program instead)"
            ) from exc
        except OSError as exc:
            raise DwgError(f"the DWG converter {exe} could not be started: {exc}") from exc
        report = _summary((done.stderr or "") + "\n" + (done.stdout or ""))
        out = work / "out.dxf"
        if done.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            detail = "; ".join(line for line in report if not line.startswith("LibreDWG"))
            raise DwgError(
                f"{dwg.name} could not be converted to DXF (dwg2dxf exit code "
                f"{done.returncode}{': ' + detail if detail else ''}); save it as DXF in the "
                "CAD program instead"
            )
        os.replace(out, dxf)
    return report


def _stamp(dwg: Path) -> dict[str, int]:
    stat = dwg.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def convert(
    dwg: str | Path,
    cache: str | Path | None = None,
    timeout: float = TIMEOUT,
    converter: str | Path | None = None,
) -> Conversion:
    """The DXF of ``dwg`` in ``cache`` (default: ``.dwg-cache`` beside it), converted when the
    cached copy is missing or older than the DWG. Raises :class:`ConverterMissing` without a
    converter and :class:`DwgError` when the conversion fails."""
    dwg = Path(dwg)
    if not dwg.is_file():
        raise DwgError(f"{dwg.name} does not exist")
    folder = Path(cache) if cache else dwg.parent / CACHE_FOLDER
    dxf = folder / f"{dwg.name}.dxf"
    meta = folder / f"{dwg.name}.json"
    stamp = _stamp(dwg)
    with contextlib.suppress(OSError, ValueError, TypeError):
        known = json.loads(meta.read_text(encoding="utf-8"))
        if known.get("source") == stamp and dxf.is_file():
            return Conversion(dxf, list(known.get("warnings", [])), cached=True)
    exe = find_converter(converter)
    if exe is None:
        raise ConverterMissing(
            f"{dwg.name}: opening DWG drawings needs GNU LibreDWG's dwg2dxf, the SAEngine "
            f"setup's DWG import component, which is not installed: add it with Help > "
            f"Installer Components..., set {ENV_VAR} to its folder, or save the drawing as DXF"
        )
    warnings = _run(exe, dwg, dxf, timeout)
    with contextlib.suppress(OSError):
        meta.write_text(json.dumps({"source": stamp, "warnings": warnings}), encoding="utf-8")
    return Conversion(dxf, warnings)


@contextlib.contextmanager
def converted(
    dwg: str | Path, timeout: float = TIMEOUT, converter: str | Path | None = None
) -> Iterator[Conversion]:
    """``dwg`` converted into a temporary folder, removed afterwards."""
    with tempfile.TemporaryDirectory(prefix="saengine-dwg-") as tmp:
        yield convert(dwg, tmp, timeout, converter)


class WriterMissing(DwgError):
    """No ``dxf2dwg`` was found."""


def write_dwg(
    dxf: str | Path,
    dwg: str | Path,
    timeout: float = TIMEOUT,
    writer: str | Path | None = None,
) -> list[str]:
    """Writes ``dxf`` as the DWG ``dwg`` (R2000) with LibreDWG's ``dxf2dwg``, run as its own
    process; returns what the converter reported. Raises :class:`WriterMissing` without the
    program and :class:`DwgError` when it fails (``dwg`` is then left as it was)."""
    dxf, dwg = Path(dxf), Path(dwg)
    if not dxf.is_file():
        raise DwgError(f"{dxf.name} does not exist")
    exe = find_writer(writer)
    if exe is None:
        raise WriterMissing(
            f"{dxf.name}: writing DWG needs GNU LibreDWG's dxf2dwg, the SAEngine setup's DWG "
            f"component, which is not installed: add it with Help > Installer Components..., "
            f"or set {ENV_VAR} to its folder. The DXF sheets open in every CAD program meanwhile."
        )
    dwg.parent.mkdir(parents=True, exist_ok=True)
    # Plain ASCII names in a working folder, as for dwg2dxf (the ANSI code page).
    with tempfile.TemporaryDirectory(prefix="dxf-", dir=dwg.parent) as tmp:
        work = Path(tmp)
        shutil.copyfile(dxf, work / "in.dxf")
        try:
            done = subprocess.run(
                [str(exe), "-y", "-o", "out.dwg", "in.dxf"],
                cwd=work,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DwgError(
                f"{dxf.name}: the DWG writer did not finish within {timeout:g} s (use the DXF)"
            ) from exc
        except OSError as exc:
            raise DwgError(f"the DWG writer {exe} could not be started: {exc}") from exc
        report = _summary((done.stderr or "") + "\n" + (done.stdout or ""))
        out = work / "out.dwg"
        ok = out.is_file() and out.stat().st_size > 0 and out.read_bytes()[:3] == MAGIC
        if done.returncode != 0 or not ok:
            detail = "; ".join(line for line in report if not line.startswith("LibreDWG"))
            raise DwgError(
                f"{dxf.name} could not be written as DWG (dxf2dwg exit code "
                f"{done.returncode}{': ' + detail if detail else ''}); use the DXF"
            )
        os.replace(out, dwg)
    return report
