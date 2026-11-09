"""One OpenFOAM case of the CFD wind tunnel per wind direction (alpha 9 L3), every file from
the templates here (no OpenFOAM Python dependency).

The case of direction θ turns the building by -θ (:mod:`.envelope`), so the wind always blows
along +x:

- ``system/blockMeshDict``: a box from 5H upstream of the building to 15H downstream, 5H to each
  side and 5H above its roof (H its height), cut into cubes of H / ``cellsPerHeight`` (coarser
  until the box has at most ``maxCells``);
- ``system/snappyHexMeshDict``: the building (``constant/triSurface/building.stl``) cut out,
  ``surfaceLevel`` halvings at its surface and ``wakeLevel`` in a box 1H upstream, 3H downstream,
  1H to the sides and up to 1.5H; no prism layers (wall functions);
- ``0.orig``: the atmospheric boundary layer at the inlet (``atmBoundaryLayerInlet*``: the log
  law U = U*/κ ln((z + z0)/z0), U* = κ Uref / ln((H + z0)/z0), Uref = 10 m/s at H), the rough
  ground (``nutkAtmRoughWallFunction``, the same z0), smooth building walls, symmetry at the
  sides and top, p = 0 at the outlet; the runner copies it to ``0`` after meshing;
- k-ε (``kEpsilon``) or k-ω SST (``kOmegaSST``; its inlet ω from the boundary layer where the
  installation has ``atmBoundaryLayerInletOmega`` (OpenFOAM.com), else uniform at H);
- ``system/controlDict``, ``fvSchemes``, ``fvSolution``: steady (SIMPLEC) with the iterations
  and the pressure residual of the settings; ASCII output (read back by :mod:`.foam_io`);
- ``constant/transportProperties`` and ``physicalProperties`` (air, ν = 1.5e-5 m²/s),
  ``turbulenceProperties`` and ``momentumTransport``: both names, for OpenFOAM.com and the
  OpenFOAM.org releases.

The reference speed only sets the Reynolds number (sharp-edged buildings: the pressure
coefficients hardly depend on it); the loads scale with the code's design velocity pressure.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from saengine.fem.cfd_wind.envelope import Envelope, case_extent, stl_text, surface_area

#: Reference wind speed at the roof height H [m/s].
UREF = 10.0
#: Kinematic viscosity of air [m²/s].
NU = 1.5e-5
KAPPA = 0.41
CMU = 0.09
#: The domain around the building, in building heights: upstream, downstream, sides, above.
UPSTREAM, DOWNSTREAM, SIDES, ABOVE = 5.0, 15.0, 5.0, 5.0


@dataclass(frozen=True)
class CaseOptions:
    """What a case needs besides the envelope (see :class:`saengine.library.settings.CfdWind`)."""

    angle: float
    z0: float
    turbulence: str = "kEpsilon"
    cellsPerHeight: int = 8
    surfaceLevel: int = 3
    wakeLevel: int = 1
    maxCells: int = 4_000_000
    iterations: int = 1500
    residual: float = 1e-4
    processors: int = 1
    #: "com" (OpenFOAM.com / ESI), "org" (OpenFOAM.org) or "" (not known).
    flavour: str = ""
    #: "simpleFoam" or "foamRun" (OpenFOAM.org 11 and later).
    solver: str = "simpleFoam"
    uref: float = UREF


@dataclass(frozen=True)
class Domain:
    """The case's box [m] (z from the ground at the building's base), its background cell
    size and counts, the building's extent in it, the refinement box and a point in the air."""

    x0: float
    x1: float
    y0: float
    y1: float
    z1: float
    dx: float
    cells: tuple[int, int, int]
    building: tuple[float, float, float, float, float]
    box: tuple[float, float, float, float, float, float]
    inside: tuple[float, float, float]
    estimate: int


def boundary_layer(z0: float, height: float, uref: float = UREF) -> dict[str, float]:
    """The log-law boundary layer of the inlet: U* [m/s] from Uref at H, and k, ε, ω at H
    (k = U*²/√Cμ, ε = U*³/(κ (z + z0)), ω = ε / (Cμ k))."""
    ustar = KAPPA * uref / math.log((height + z0) / z0)
    k = ustar**2 / math.sqrt(CMU)
    epsilon = ustar**3 / (KAPPA * (height + z0))
    return {"ustar": ustar, "k": k, "epsilon": epsilon, "omega": epsilon / (CMU * k)}


def domain(envelope: Envelope, options: CaseOptions) -> Domain:
    """The case's box and mesh sizes (see the module notes)."""
    h = envelope.height
    if h <= 0:
        raise ValueError("the building has no height")
    bx0, bx1, by0, by1 = case_extent(envelope, options.angle)
    x0, x1 = bx0 - UPSTREAM * h, bx1 + DOWNSTREAM * h
    y0, y1 = by0 - SIDES * h, by1 + SIDES * h
    z1 = h * (1 + ABOVE)
    dx = h / options.cellsPerHeight

    def counts(size: float) -> tuple[int, int, int]:
        return (
            max(1, math.ceil((x1 - x0) / size)),
            max(1, math.ceil((y1 - y0) / size)),
            max(1, math.ceil(z1 / size)),
        )

    n = counts(dx)
    while n[0] * n[1] * n[2] > options.maxCells:
        dx *= (n[0] * n[1] * n[2] / options.maxCells) ** (1 / 3) * 1.001
        n = counts(dx)
    # The box's own sizes: whole cubes of dx.
    x1, y1, z1 = x0 + n[0] * dx, y0 + n[1] * dx, n[2] * dx
    box = (
        max(x0, bx0 - h),
        min(x1, bx1 + 3 * h),
        max(y0, by0 - h),
        min(y1, by1 + h),
        0.0,
        min(z1, 1.5 * h),
    )
    inside = (
        x0 + 0.5 * (bx0 - x0) + 0.123 * dx,
        y0 + 0.5 * (by0 - y0) + 0.137 * dx,
        min(0.5 * h, z1 / 2) + 0.111 * dx,
    )
    background = n[0] * n[1] * n[2]
    wake = 0.0
    if options.wakeLevel > 0:
        volume = (box[1] - box[0]) * (box[3] - box[2]) * (box[5] - box[4])
        wake = volume / dx**3 * (8**options.wakeLevel - 1)
    surface = 0.0
    area = surface_area(envelope)
    for level in range(options.wakeLevel + 1, options.surfaceLevel + 1):
        size = dx / 2**level
        surface += 3 * area / size**2  # about three cells thick at each level
    return Domain(
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
        z1=z1,
        dx=dx,
        cells=n,
        building=(bx0, bx1, by0, by1, h),
        box=box,
        inside=inside,
        estimate=int(background + wake + surface),
    )


def _header(cls: str, obj: str, location: str | None = None) -> str:
    where = f'    location    "{location}";\n' if location else ""
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "  Written by SAEngine (CFD wind tunnel, alpha 9 L3). Edit the project settings,\n"
        "  not this file: it is written again before every run.\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        f"    class       {cls};\n{where}    object      {obj};\n}}\n\n"
    )


def _v(values: tuple[float, ...] | list[float]) -> str:
    return "(" + " ".join(f"{v:.6g}" for v in values) + ")"


def block_mesh(d: Domain) -> str:
    x0, x1, y0, y1, z1 = d.x0, d.x1, d.y0, d.y1, d.z1
    vertices = [
        (x0, y0, 0.0),
        (x1, y0, 0.0),
        (x1, y1, 0.0),
        (x0, y1, 0.0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    nx, ny, nz = d.cells
    return (
        _header("dictionary", "blockMeshDict")
        + "scale 1;\nconvertToMeters 1;\n\nvertices\n(\n"
        + "".join(f"    {_v(v)}\n" for v in vertices)
        + ");\n\nblocks\n(\n"
        + f"    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)\n);\n\n"
        + "edges\n(\n);\n\nboundary\n(\n"
        + "    inlet\n    {\n        type patch;\n        faces ((0 4 7 3));\n    }\n"
        + "    outlet\n    {\n        type patch;\n        faces ((2 6 5 1));\n    }\n"
        + "    ground\n    {\n        type wall;\n        faces ((0 3 2 1));\n    }\n"
        + "    top\n    {\n        type symmetry;\n        faces ((4 5 6 7));\n    }\n"
        + "    sides\n    {\n        type symmetry;\n        faces ((1 5 4 0) (3 7 6 2));\n    }\n"
        + ");\n\nmergePatchPairs\n(\n);\n"
    )


def snappy(d: Domain, options: CaseOptions) -> str:
    s = options.surfaceLevel
    box = d.box
    wake = options.wakeLevel > 0
    geometry = (
        "    building.stl\n    {\n        type triSurfaceMesh;\n        name building;\n    }\n"
    )
    if wake:
        geometry += (
            "    wake\n    {\n        type searchableBox;\n"
            f"        min {_v(box[0::2])};\n        max {_v(box[1::2])};\n    }}\n"
        )
    regions = (
        f"        wake\n        {{\n            mode inside;\n            levels ((1e15 {options.wakeLevel}));\n        }}\n"
        if wake
        else ""
    )
    return (
        _header("dictionary", "snappyHexMeshDict")
        + "castellatedMesh true;\nsnap            true;\naddLayers       false;\n\n"
        + "geometry\n{\n"
        + geometry
        + "}\n\ncastellatedMeshControls\n{\n"
        + "    maxLocalCells 2000000;\n    maxGlobalCells 40000000;\n    minRefinementCells 10;\n"
        + "    maxLoadUnbalance 0.10;\n    nCellsBetweenLevels 3;\n    features ();\n"
        + "    refinementSurfaces\n    {\n        building\n        {\n"
        + f"            level ({s} {s});\n            patchInfo\n            {{\n"
        + "                type wall;\n            }\n        }\n    }\n"
        + "    resolveFeatureAngle 30;\n    refinementRegions\n    {\n"
        + regions
        + "    }\n"
        + f"    locationInMesh {_v(d.inside)};\n    insidePoint {_v(d.inside)};\n"
        + "    allowFreeStandingZoneFaces true;\n}\n\n"
        + "snapControls\n{\n    nSmoothPatch 3;\n    tolerance 2.0;\n    nSolveIter 50;\n"
        + "    nRelaxIter 5;\n    nFeatureSnapIter 10;\n    implicitFeatureSnap true;\n"
        + "    explicitFeatureSnap false;\n    multiRegionFeatureSnap false;\n}\n\n"
        + "addLayersControls\n{\n    relativeSizes true;\n    layers\n    {\n    }\n"
        + "    expansionRatio 1.2;\n    finalLayerThickness 0.5;\n    minThickness 0.1;\n"
        + "    nGrow 0;\n    featureAngle 60;\n    nRelaxIter 3;\n    nSmoothSurfaceNormals 1;\n"
        + "    nSmoothNormals 3;\n    nSmoothThickness 10;\n    maxFaceThicknessRatio 0.5;\n"
        + "    maxThicknessToMedialRatio 0.3;\n    minMedialAxisAngle 90;\n    minMedianAxisAngle 90;\n"
        + "    nBufferCellsNoExtrude 0;\n    nLayerIter 50;\n}\n\n"
        + "meshQualityControls\n{\n    maxNonOrtho 65;\n    maxBoundarySkewness 20;\n"
        + "    maxInternalSkewness 4;\n    maxConcave 80;\n    minVol 1e-13;\n"
        + "    minTetQuality -1e30;\n    minArea -1;\n    minTwist 0.02;\n    minDeterminant 0.001;\n"
        + "    minFaceWeight 0.05;\n    minVolRatio 0.01;\n    minTriangleTwist -1;\n"
        + "    nSmoothScale 4;\n    errorReduction 0.75;\n"
        + "    relaxed\n    {\n        maxNonOrtho 75;\n    }\n}\n\n"
        + "mergeTolerance 1e-6;\n"
    )


def control(options: CaseOptions) -> str:
    n = options.iterations
    application = "foamRun" if options.solver == "foamRun" else "simpleFoam"
    return (
        _header("dictionary", "controlDict")
        + f"application     {application};\nsolver          incompressibleFluid;\n"
        + "startFrom       latestTime;\nstartTime       0;\nstopAt          endTime;\n"
        + f"endTime         {n};\ndeltaT          1;\nwriteControl    timeStep;\n"
        + f"writeInterval   {n};\npurgeWrite      1;\nwriteFormat     ascii;\n"
        + "writePrecision  8;\nwriteCompression off;\ntimeFormat      general;\n"
        + "timePrecision   8;\nrunTimeModifiable true;\n"
        + 'libs            ("libatmosphericModels.so");\n'
    )


def schemes(options: CaseOptions) -> str:
    turbulence = "omega" if options.turbulence == "kOmegaSST" else "epsilon"
    return (
        _header("dictionary", "fvSchemes")
        + "ddtSchemes\n{\n    default steadyState;\n}\n\n"
        + "gradSchemes\n{\n    default Gauss linear;\n"
        + "    grad(U) cellLimited Gauss linear 1;\n    grad(k) cellLimited Gauss linear 1;\n"
        + f"    grad({turbulence}) cellLimited Gauss linear 1;\n}}\n\n"
        + "divSchemes\n{\n    default bounded Gauss upwind;\n"
        + "    div(phi,U) bounded Gauss linearUpwind grad(U);\n"
        + "    div(phi,k) bounded Gauss upwind;\n"
        + f"    div(phi,{turbulence}) bounded Gauss upwind;\n"
        + "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        + "    div((nuEff*dev(T(grad(U))))) Gauss linear;\n}\n\n"
        + "laplacianSchemes\n{\n    default Gauss linear limited corrected 0.33;\n}\n\n"
        + "interpolationSchemes\n{\n    default linear;\n}\n\n"
        + "snGradSchemes\n{\n    default limited corrected 0.33;\n}\n\n"
        + "wallDist\n{\n    method meshWave;\n}\n"
    )


def solution(options: CaseOptions) -> str:
    turbulence = "omega" if options.turbulence == "kOmegaSST" else "epsilon"
    control_ = (
        "{\n    nNonOrthogonalCorrectors 1;\n    consistent yes;\n"
        "    momentumPredictor yes;\n    nOuterCorrectors 1;\n    nCorrectors 1;\n"
        f"    residualControl\n    {{\n        p {options.residual:g};\n"
        f'        U {options.residual / 10:g};\n        "(k|{turbulence})" {options.residual / 10:g};\n'
        "    }\n}\n\n"
    )
    return (
        _header("dictionary", "fvSolution")
        + "solvers\n{\n    p\n    {\n        solver GAMG;\n        smoother GaussSeidel;\n"
        + "        tolerance 1e-7;\n        relTol 0.1;\n    }\n"
        + f'    "(U|k|{turbulence})"\n    {{\n        solver smoothSolver;\n'
        + "        smoother symGaussSeidel;\n        tolerance 1e-8;\n        relTol 0.1;\n    }\n}\n\n"
        + "SIMPLE\n"
        + control_
        + "PIMPLE\n"
        + control_
        + "relaxationFactors\n{\n    equations\n    {\n        U 0.9;\n"
        + f'        k 0.7;\n        {turbulence} 0.7;\n        ".*" 0.9;\n    }}\n}}\n'
    )


def _decompose(options: CaseOptions) -> str:
    return (
        _header("dictionary", "decomposeParDict")
        + f"numberOfSubdomains {max(1, options.processors)};\nmethod          scotch;\n"
    )


def _physical() -> tuple[str, str]:
    transport = (
        _header("dictionary", "transportProperties")
        + f"transportModel  Newtonian;\nnu              [0 2 -1 0 0 0 0] {NU:g};\n"
    )
    physical = (
        _header("dictionary", "physicalProperties")
        + f"viscosityModel  constant;\nnu              [0 2 -1 0 0 0 0] {NU:g};\n"
    )
    return transport, physical


def _turbulence(options: CaseOptions, name: str) -> str:
    return (
        _header("dictionary", name)
        + "simulationType  RAS;\n\nRAS\n{\n"
        + f"    RASModel        {options.turbulence};\n    model           {options.turbulence};\n"
        + "    turbulence      on;\n    printCoeffs     on;\n}\n"
    )


def _abl(options: CaseOptions, height: float) -> str:
    return (
        "        flowDir         (1 0 0);\n        zDir            (0 0 1);\n"
        + f"        Uref            {options.uref:g};\n        Zref            {height:.6g};\n"
        + f"        z0              uniform {options.z0:g};\n        zGround         uniform 0;\n"
        + f"        d               uniform 0;\n        kappa           {KAPPA:g};\n"
        + f"        Cmu             {CMU:g};\n"
    )


def _field(cls: str, name: str, dims: str, internal: str, patches: dict[str, str]) -> str:
    body = "".join(f"    {key}\n    {{\n{value}    }}\n" for key, value in patches.items())
    return (
        _header(cls, name, "0")
        + f"dimensions      {dims};\n\ninternalField   {internal};\n\nboundaryField\n{{\n"
        + body
        + "}\n"
    )


SYMMETRY = "        type            symmetry;\n"


def fields(options: CaseOptions, height: float) -> dict[str, str]:
    """The initial fields (``0.orig``) by name."""
    layer = boundary_layer(options.z0, height, options.uref)
    u0 = f"uniform ({options.uref:g} 0 0)"
    k0, e0, w0 = layer["k"], layer["epsilon"], layer["omega"]
    abl = _abl(options, height)
    common = {"top": SYMMETRY, "sides": SYMMETRY}
    out = {
        "U": _field(
            "volVectorField",
            "U",
            "[0 1 -1 0 0 0 0]",
            u0,
            {
                "inlet": f"        type            atmBoundaryLayerInletVelocity;\n{abl}        value           {u0};\n",
                "outlet": "        type            inletOutlet;\n        inletValue      uniform (0 0 0);\n"
                f"        value           {u0};\n",
                "ground": "        type            noSlip;\n",
                **common,
                '"building.*"': "        type            noSlip;\n",
            },
        ),
        "p": _field(
            "volScalarField",
            "p",
            "[0 2 -2 0 0 0 0]",
            "uniform 0",
            {
                "inlet": "        type            zeroGradient;\n",
                "outlet": "        type            fixedValue;\n        value           uniform 0;\n",
                "ground": "        type            zeroGradient;\n",
                **common,
                # zeroGradient: the face values are the cells' (read back that way, foam_io).
                '"building.*"': "        type            zeroGradient;\n",
            },
        ),
        "k": _field(
            "volScalarField",
            "k",
            "[0 2 -2 0 0 0 0]",
            f"uniform {k0:.6g}",
            {
                "inlet": f"        type            atmBoundaryLayerInletK;\n{abl}        value           uniform {k0:.6g};\n",
                "outlet": f"        type            inletOutlet;\n        inletValue      uniform {k0:.6g};\n"
                f"        value           uniform {k0:.6g};\n",
                "ground": f"        type            kqRWallFunction;\n        value           uniform {k0:.6g};\n",
                **common,
                '"building.*"': f"        type            kqRWallFunction;\n        value           uniform {k0:.6g};\n",
            },
        ),
        "nut": _field(
            "volScalarField",
            "nut",
            "[0 2 -1 0 0 0 0]",
            "uniform 0",
            {
                "inlet": "        type            calculated;\n        value           uniform 0;\n",
                "outlet": "        type            calculated;\n        value           uniform 0;\n",
                "ground": "        type            nutkAtmRoughWallFunction;\n"
                f"        z0              uniform {options.z0:g};\n        value           uniform 0;\n",
                **common,
                '"building.*"': "        type            nutkWallFunction;\n        value           uniform 0;\n",
            },
        ),
    }
    if options.turbulence == "kOmegaSST":
        inlet = (
            f"        type            atmBoundaryLayerInletOmega;\n{abl}        value           uniform {w0:.6g};\n"
            if options.flavour == "com"
            else f"        type            fixedValue;\n        value           uniform {w0:.6g};\n"
        )
        out["omega"] = _field(
            "volScalarField",
            "omega",
            "[0 0 -1 0 0 0 0]",
            f"uniform {w0:.6g}",
            {
                "inlet": inlet,
                "outlet": f"        type            inletOutlet;\n        inletValue      uniform {w0:.6g};\n"
                f"        value           uniform {w0:.6g};\n",
                "ground": f"        type            omegaWallFunction;\n        value           uniform {w0:.6g};\n",
                **common,
                '"building.*"': f"        type            omegaWallFunction;\n        value           uniform {w0:.6g};\n",
            },
        )
    else:
        out["epsilon"] = _field(
            "volScalarField",
            "epsilon",
            "[0 2 -3 0 0 0 0]",
            f"uniform {e0:.6g}",
            {
                "inlet": f"        type            atmBoundaryLayerInletEpsilon;\n{abl}        value           uniform {e0:.6g};\n",
                "outlet": f"        type            inletOutlet;\n        inletValue      uniform {e0:.6g};\n"
                f"        value           uniform {e0:.6g};\n",
                "ground": f"        type            epsilonWallFunction;\n        value           uniform {e0:.6g};\n",
                **common,
                '"building.*"': f"        type            epsilonWallFunction;\n        value           uniform {e0:.6g};\n",
            },
        )
    return out


def case_name(angle: float) -> str:
    """The case folder of direction ``angle``: ``dir-000``, ``dir-030``, ``dir-022.5``."""
    a = round(float(angle) % 360, 6)
    return f"dir-{int(a):03d}" if a.is_integer() else f"dir-{a:05.1f}"


def write_case(folder: Path, envelope: Envelope, options: CaseOptions) -> dict[str, Any]:
    """Writes the case of ``options.angle`` into ``folder`` (its old mesh, fields and results
    removed first); returns what it is: the domain, the cells, the boundary layer, notes."""
    if folder.exists():
        shutil.rmtree(folder)
    d = domain(envelope, options)
    h = envelope.height
    files: dict[str, str] = {
        "system/blockMeshDict": block_mesh(d),
        "system/snappyHexMeshDict": snappy(d, options),
        "system/controlDict": control(options),
        "system/fvSchemes": schemes(options),
        "system/fvSolution": solution(options),
        "system/decomposeParDict": _decompose(options),
        "constant/turbulenceProperties": _turbulence(options, "turbulenceProperties"),
        "constant/momentumTransport": _turbulence(options, "momentumTransport"),
        "constant/triSurface/building.stl": stl_text(envelope, options.angle, below=d.dx),
    }
    files["constant/transportProperties"], files["constant/physicalProperties"] = _physical()
    for name, text in fields(options, h).items():
        files[f"0.orig/{name}"] = text
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    notes = []
    if d.dx / 2 < options.z0:
        notes.append(
            f"the first cell over the ground ({d.dx / 2:.2f} m to its centre) is lower than z0 "
            f"= {options.z0:g} m: the rough-wall function is outside its range there; use more "
            "cells per building height only with a smaller z0, or accept the rougher inlet"
        )
    if options.turbulence == "kOmegaSST" and options.flavour != "com":
        notes.append(
            "k-ω SST: this installation has no boundary layer inlet for ω, so ω is uniform at "
            "its value at H (the inlet's turbulence decays faster near the ground)"
        )
    layer = boundary_layer(options.z0, h, options.uref)
    return {
        "angle": options.angle,
        "folder": folder.name,
        "domain": {
            "x": [d.x0, d.x1],
            "y": [d.y0, d.y1],
            "z": [0.0, d.z1],
            "cell_m": d.dx,
            "cells": list(d.cells),
        },
        "estimatedCells": d.estimate,
        "boundaryLayer": {"z0_m": options.z0, "uref": options.uref, "zref_m": h, **layer},
        "options": asdict(options),
        "notes": notes,
    }
