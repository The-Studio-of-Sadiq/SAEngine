"""Finding the user's OpenFOAM and the commands of a run (alpha 9 L3).

SAEngine neither bundles nor downloads OpenFOAM. On Windows it looks in WSL (the distribution
the user names, else the default one); on Linux and macOS on the host. In either it takes, in
order: the path the user sets (OpenFOAM's ``etc/bashrc`` or the folder holding ``etc/bashrc``),
the solvers already on a login shell's PATH, then the usual install places
(``/usr/lib/openfoam/openfoam*`` of the OpenFOAM.com packages, ``/opt/openfoam*`` of the
OpenFOAM.org packages, ``~/OpenFOAM/OpenFOAM-*`` of a source build). It reports the version, the
flavour ("com": OpenFOAM.com / ESI, version vYYMM; "org": OpenFOAM.org, a number), the steady
solver (``simpleFoam``, or ``foamRun -solver incompressibleFluid`` of OpenFOAM.org 11 and
later), MPI and the processor count. Finding runs a short probe script, nothing else.

Each step of a run is a small bash script written into the case (``.sae-step.sh``): it sources
the installation, enters the case, writes its process id (``.sae-step.pid``, for Cancel) and
replaces itself with the OpenFOAM program, whose output goes to ``log.<program>``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

#: The probe: the configured path ($1) or the usual places; key=value lines out.
PROBE = r"""#!/bin/bash
want="$1"
found=""
have() { command -v "$1" >/dev/null 2>&1; }
if [ -n "$want" ]; then
  if [ -f "$want" ]; then found="$want"
  elif [ -f "$want/etc/bashrc" ]; then found="$want/etc/bashrc"
  else echo "SAE_ERROR=nothing at $want"
  fi
fi
if [ -z "$found" ] && ! { have simpleFoam || have foamRun; }; then
  for c in /usr/lib/openfoam/openfoam*/etc/bashrc /opt/openfoam*/etc/bashrc \
           /opt/OpenFOAM-*/etc/bashrc /opt/OpenFOAM/OpenFOAM-*/etc/bashrc \
           /usr/local/OpenFOAM/OpenFOAM-*/etc/bashrc "$HOME"/OpenFOAM/OpenFOAM-*/etc/bashrc; do
    [ -f "$c" ] && found="$c"
  done
fi
if [ -n "$found" ]; then source "$found" >/dev/null 2>&1; fi
echo "SAE_BASHRC=$found"
echo "SAE_VERSION=${WM_PROJECT_VERSION:-}"
for t in simpleFoam foamRun blockMesh snappyHexMesh decomposePar reconstructPar mpirun; do
  if have "$t"; then echo "SAE_HAS_$t=1"; else echo "SAE_HAS_$t=0"; fi
done
echo "SAE_CORES=$(nproc 2>/dev/null || echo 1)"
"""

#: How long finding may take [s] (WSL may have to start).
PROBE_TIMEOUT = 120


@dataclass
class Installation:
    """What was found (see the module notes)."""

    found: bool = False
    #: "wsl" (Windows, through wsl.exe) or "posix" (the host's own bash).
    mode: str = ""
    distribution: str | None = None
    distributions: list[str] = field(default_factory=list)
    bashrc: str | None = None
    version: str | None = None
    flavour: str | None = None
    solver: str | None = None
    mpirun: bool = False
    parallel: bool = False
    cores: int | None = None
    problems: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Installation:
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def flavour_of(version: str | None) -> str | None:
    """ "com" for OpenFOAM.com (vYYMM), "org" for OpenFOAM.org (a number or dev), else None."""
    if not version:
        return None
    v = version.strip().lower()
    if v.startswith("v") and v[1:2].isdigit():
        return "com"
    if v[:1].isdigit() or v == "dev":
        return "org"
    return None


def parse_probe(text: str) -> dict[str, str]:
    """The probe's ``SAE_key=value`` lines."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if line.startswith("SAE_") and "=" in line:
            key, value = line[4:].split("=", 1)
            out[key] = value.strip()
    return out


def installation_from_probe(
    values: dict[str, str], mode: str, distribution: str | None
) -> Installation:
    """The installation the probe's values describe."""
    has = {k[4:]: v == "1" for k, v in values.items() if k.startswith("HAS_")}
    solver = "simpleFoam" if has.get("simpleFoam") else "foamRun" if has.get("foamRun") else None
    version = values.get("VERSION") or None
    inst = Installation(
        mode=mode,
        distribution=distribution,
        bashrc=values.get("BASHRC") or None,
        version=version,
        flavour=flavour_of(version),
        solver=solver,
        mpirun=bool(has.get("mpirun")),
        parallel=bool(has.get("mpirun") and has.get("decomposePar") and has.get("reconstructPar")),
    )
    try:
        inst.cores = int(values.get("CORES") or 0) or None
    except ValueError:
        inst.cores = None
    if values.get("ERROR"):
        inst.problems.append(f"the OpenFOAM path set in the settings: {values['ERROR']}")
    missing = [t for t in ("blockMesh", "snappyHexMesh") if not has.get(t)]
    if solver is None:
        missing.insert(0, "simpleFoam (or foamRun)")
    if missing:
        inst.problems.append("not found: " + ", ".join(missing))
    inst.found = not missing
    return inst


def _wsl() -> str | None:
    return shutil.which("wsl.exe") or shutil.which("wsl")


def _hidden() -> dict[str, Any]:
    """No console window for the programs started on Windows."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def wsl_distributions() -> list[str]:
    """The WSL distributions installed (``wsl.exe -l -q``; its output is UTF-16)."""
    exe = _wsl()
    if exe is None:
        return []
    try:
        done = subprocess.run(
            [exe, "-l", "-q"], capture_output=True, timeout=30, check=False, **_hidden()
        )
    except (OSError, subprocess.SubprocessError):
        return []
    raw = done.stdout or b""
    text = (
        raw.decode("utf-16-le", errors="ignore") if b"\x00" in raw else raw.decode(errors="ignore")
    )
    names = [line.strip().strip("\x00").lstrip("\ufeff") for line in text.splitlines()]
    return [n for n in names if n and done.returncode == 0]


def to_wsl_path(path: str | Path) -> str:
    """A Windows path as WSL sees it: ``C:\\a b\\c`` -> ``/mnt/c/a b/c`` (a UNC path
    ``\\\\wsl$\\<distro>\\x`` -> ``/x``)."""
    p = PureWindowsPath(str(path))
    if p.drive and len(p.drive) == 2 and p.drive[1] == ":":
        return "/mnt/" + p.drive[0].lower() + "/" + "/".join(p.parts[1:])
    text = str(p).replace("\\", "/")
    for prefix in ("//wsl$/", "//wsl.localhost/"):
        if text.lower().startswith(prefix):
            rest = text[len(prefix) :].split("/", 1)
            return "/" + (rest[1] if len(rest) > 1 else "")
    return text


def host_path(path: str | Path, mode: str) -> str:
    """``path`` as the installation's bash sees it."""
    return to_wsl_path(path) if mode == "wsl" else str(Path(path))


def bash_command(script: str | Path, mode: str, distribution: str | None, *args: str) -> list[str]:
    """The command line running ``script`` (a file on this computer) with bash as a login
    shell, through WSL in mode "wsl"."""
    if mode == "wsl":
        exe = _wsl() or "wsl.exe"
        head = [exe] + (["-d", distribution] if distribution else [])
        return [*head, "--exec", "bash", "-l", to_wsl_path(script), *args]
    return ["bash", "-l", str(script), *args]


def install_steps(windows: bool | None = None) -> list[str]:
    """How to install OpenFOAM for SAEngine (shown when none is found)."""
    win = sys.platform == "win32" if windows is None else windows
    steps = []
    if win:
        steps += [
            (
                "Install WSL with Ubuntu: in a terminal opened as administrator run "
                "`wsl --install -d Ubuntu-24.04`, restart Windows and create the Ubuntu user."
            ),
            "Open Ubuntu (Start menu) for the next steps.",
        ]
    steps += [
        (
            "OpenFOAM.com (ESI, recommended: it has simpleFoam and every inlet SAEngine writes): run "
            "`curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash`, then "
            "`sudo apt-get install openfoam2412-default` (or the newest openfoamYYMM-default "
            "`apt search openfoam` lists)."
        ),
        (
            "Or OpenFOAM.org: follow openfoam.org/download (Ubuntu packages `openfoam12`); "
            "SAEngine then runs `foamRun -solver incompressibleFluid`."
        ),
        "Back in SAEngine: Find OpenFOAM again. If it is installed somewhere else, set "
        "Settings > SAEngine > CFD Wind: OpenFOAM to its etc/bashrc"
        + (" (a path inside WSL), and the WSL distribution if not the default." if win else "."),
        (
            "SAEngine does not install, bundle or download OpenFOAM; it is GPL software you install "
            "and keep yourself."
        ),
    ]
    return steps


def detect(setting: str | None = None, distribution: str | None = None) -> Installation:
    """Finds OpenFOAM (see the module notes); never raises."""
    windows = sys.platform == "win32"
    mode = "wsl" if windows else "posix"
    inst = Installation(mode=mode, distribution=distribution or None)
    if windows:
        if _wsl() is None:
            inst.problems.append(
                "WSL (Windows Subsystem for Linux) is not installed: OpenFOAM runs in it on Windows"
            )
            return inst
        inst.distributions = wsl_distributions()
        if not inst.distributions:
            inst.problems.append("WSL has no Linux distribution installed (e.g. Ubuntu)")
            return inst
        if distribution and distribution not in inst.distributions:
            inst.problems.append(
                f"the WSL distribution '{distribution}' is not installed (installed: "
                + ", ".join(inst.distributions)
                + ")"
            )
            return inst
    elif shutil.which("bash") is None:
        inst.problems.append("bash was not found on this computer")
        return inst
    with tempfile.TemporaryDirectory(prefix="saengine-cfd-") as tmp:
        script = Path(tmp) / "probe.sh"
        script.write_text(PROBE, encoding="utf-8", newline="\n")
        command = bash_command(script, mode, distribution or None, (setting or "").strip())
        try:
            done = subprocess.run(
                command,
                capture_output=True,
                timeout=PROBE_TIMEOUT,
                check=False,
                stdin=subprocess.DEVNULL,
                **_hidden(),
            )
        except subprocess.TimeoutExpired:
            inst.problems.append(f"finding OpenFOAM took longer than {PROBE_TIMEOUT} s")
            return inst
        except OSError as error:
            inst.problems.append(f"could not start bash: {error}")
            return inst
    values = parse_probe((done.stdout or b"").decode("utf-8", errors="replace"))
    found = installation_from_probe(values, mode, distribution or None)
    found.distributions = inst.distributions
    if not values:
        message = (done.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        found.problems.append("the probe gave no answer" + (f": {message[-1]}" if message else ""))
    return found


def step_script(case: Path, inst: Installation, argv: list[str], log: str) -> str:
    """The bash script of one step (see the module notes)."""
    lines = ["#!/bin/bash"]
    if inst.bashrc:
        lines.append(f"source {shlex.quote(inst.bashrc)} >/dev/null 2>&1")
    lines += [
        f"cd {shlex.quote(host_path(case, inst.mode))} || exit 90",
        "echo $$ > .sae-step.pid",
        "exec " + " ".join(shlex.quote(a) for a in argv) + f" > {shlex.quote(log)} 2>&1",
    ]
    return "\n".join(lines) + "\n"


def solver_argv(inst: Installation, parallel: bool, processors: int) -> list[str]:
    """The steady solver's command (``mpirun -np N ... -parallel`` when ``parallel``)."""
    argv = (
        ["foamRun", "-solver", "incompressibleFluid"]
        if inst.solver == "foamRun"
        else ["simpleFoam"]
    )
    if parallel:
        return ["mpirun", "-np", str(processors), *argv, "-parallel"]
    return argv


def stop_command(inst: Installation, pid: int) -> list[str] | None:
    """The command that stops the step's program ``pid`` (inside WSL); None on a posix host
    (the runner signals it itself)."""
    if inst.mode != "wsl":
        return None
    exe = _wsl() or "wsl.exe"
    head = [exe] + (["-d", inst.distribution] if inst.distribution else [])
    return [*head, "--exec", "kill", "-TERM", str(pid)]


def process_flags() -> dict[str, Any]:
    """Popen keywords of a step: no console window on Windows; its own session on posix."""
    if os.name == "nt":
        return _hidden()
    return {"start_new_session": True}
