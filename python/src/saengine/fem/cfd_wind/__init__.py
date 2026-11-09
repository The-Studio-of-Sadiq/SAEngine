"""The CFD wind tunnel (alpha 9 L3): an optional link to the user's own OpenFOAM.

SAEngine does not bundle or download OpenFOAM. It finds an installed one (in WSL on Windows,
or on the PATH of a Linux or macOS host, or at the path the user sets) and otherwise says how to
install it. Nothing runs unless the user starts it.

- :mod:`.envelope`: the building's envelope (each storey's outline from the BIM slabs, else its
  columns and walls, else the analysis model's nodes) and its closed surface as STL;
- :mod:`.case`: one OpenFOAM case per wind direction, every file written from Python templates
  (blockMesh domain 5H upstream, 15H downstream, 5H to the sides and above; snappyHexMesh around
  the STL; an atmospheric boundary layer inlet with the log law, z0 from the code pack's
  exposure; k-ε or k-ω SST; simpleFoam steady RANS);
- :mod:`.openfoam`: finding the installation, the commands of each step (through WSL on
  Windows), the install instructions;
- :mod:`.runner`: the background run (a separate process: progress, cancel, one case per
  direction) and ``python -m saengine.fem.cfd_wind.runner <folder>``;
- :mod:`.foam_io`: the ASCII mesh and field files read back (no OpenFOAM Python dependency);
- :mod:`.post`: surface pressures to Cp per facade zone and storey, storey force coefficients,
  and the storey forces scaled by the code's design velocity pressure;
- :mod:`.loads`: the "CFD wind" cases the analysis can take in place of the code's;
- :mod:`.service`: what the RPC methods ``cfd/*`` and the report call.

The results are engineer-supplied: a steady RANS simulation is not a code wind tunnel test, and
the report says so with the code pack's own requirement (``cfdWind.validation``).

Files: ``08 FEM/cfd-wind/results.json`` (the coefficients, kept with the project) and
``08 FEM/cfd-wind/cases/`` (the OpenFOAM cases, logs and the run's status; left out of archives
and versions).
"""

from __future__ import annotations

from pathlib import Path

#: The CFD wind tunnel's folder in the project.
FOLDER = Path("08 FEM") / "cfd-wind"
#: The OpenFOAM cases, the run's plan, status and logs (computed, not archived).
CASES = FOLDER / "cases"
#: The coefficients of every direction run (kept: the analysis can use them).
RESULTS = FOLDER / "results.json"
#: The results file's schema id.
SCHEMA = "saengine.cfdWind/1"
