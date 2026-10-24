# Cross-check against a commercial analysis program (local only)

`scripts/etabs_compare` builds a SAEngine project in a **licensed copy of ETABS** through its
public .NET API (hidden, never the GUI), runs it, runs SAEngine headless on a copy of the same
project, and writes a comparison report with PASS or FLAG per quantity.

It is a developer tool for the PC that holds the licence. It **never runs in CI**: it refuses
to start when a CI variable (`CI`, `GITHUB_ACTIONS`, `TF_BUILD`, ...) is set, when ETABS is not
installed, or while an ETABS instance is already running (the licence allows one at a time).
Only the report and tolerance logic (`compare.py`) is tested in CI, with synthetic data
(`tests/test_compare.py`).

## What it checks

Two modes (default: both):

- **mirror**: SAEngine's derived analysis model (`08 FEM/model.osmodel`) rebuilt node by node:
  the same joints, frame and shell elements, sections, cracked modifiers per case, releases,
  joint masses, nodal and span loads, rigid diaphragms; no automatic meshing and no mass
  lumping in ETABS. Each frame is turned so that ETABS's local axes are SAEngine's (a skewed
  column's own `vecxz`, a member sloping in a vertical YZ plane), and SAEngine's rigid end
  offsets (`joint_offsets`, OpenSees `-jntOffset`) become fully rigid end-length offsets; span
  loads act on the flexible length only, as in SAEngine, which already moved the rigid zones'
  share to the joints. A **solver check**: both programs solve the same mesh, so differences
  point at the solvers or the element formulations, never at the mesh. One convention remains:
  ETABS's rigid zones stiffen bending and shear only (axial and torsional deformation stay over
  the full length, CSI Analysis Reference Manual Eqn. 7-7), while OpenSees `-jntOffset` zones
  are rigid in every direction; on the sample this shows as a torsional mode (T3) about 6 %
  apart while T1, T2, reactions, drifts and member moments agree.
- **native**: the physical model (`06 BIM` with `04 Objects`, `03 Materials`, the settings'
  area loads, partitions on the beams below them and the MEP equipment) drawn the way an ETABS
  user would draw it: storeys, columns, beams, braces, walls and slabs as objects with
  openings, ETABS's own meshing, automatic end offsets, thin shells, a mass source of self mass
  plus SD and the code pack's live-load share, and the static earthquake as ETABS's "user
  coefficient" load with SAEngine's coefficient C = Sa and exponent k. When SAEngine's model
  has rigid end zones (D3), ETABS's automatic end offsets take the same rigid-zone factor
  (`08 FEM/faces.json`, else the analysis settings, else 0.5); otherwise ETABS's default. A **conventions check**:
  differences are the modelling conventions (seismic-weight lumping, rigid end zones, mesh,
  shell type), each FLAG carrying a short reason.

Quantities and tolerances:

| Quantity | Tolerance |
| --- | --- |
| Periods, first 3 modes | 2 % |
| Effective modal masses UX, UY, first 3 modes | 5 % (floor 1 % of the total mass) |
| Base reactions per load case (D, SD, L, Lr, F: FZ) | 1 % |
| Static base shear V (EX, EY) and seismic weight W | 2 % |
| Storey shears (EX, EY) | 2 % |
| Storey drifts at the centre of mass (EX, EY) | 5 % |
| Member moments at the support faces (D, SD, L, EX, EY) | 5 % (floor 2 % of the member's largest moment) |

Member forces: at the end stations where ETABS reports them (in **native** mode its support
faces, from its automatic end offsets; in **mirror** mode the joints, or the faces where the
frame has end offsets). SAEngine's forces are evaluated at the same stations by statics from
its element end forces and span loads. With rigid end zones OpenSees reports the end forces at
the flexible ends (the faces), so the statics start there, and a station inside a rigid zone
is reached with no span load on the zone. Moments are compared on ETABS's frame axes: M3
(major) and M2 (minor), SAEngine's moment vector projected on them; magnitudes only (the
programs' sign conventions differ). For a column local 2 is global X turned by its angle. A
column is compared storey by storey (`C1@L2`).

## How to run

Prerequisites: Windows, a licensed ETABS 22 (`C:\Program Files\Computers and Structures\ETABS 22`,
or `-EtabsDir`), the repository's Python environment (`.venv`).

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\etabs_compare\compare.ps1 `
    -Project "D:\Projects\Office Block" -Out "D:\Checks\office" -Mode both -Members C-A1-L1,B-A1-B1-L1
```

- `-Project`: the project folder (or its `.saengine` file). It is copied to `<Out>\work`; the
  original is never touched.
- `-Out`: the output folder, **outside the repository** (refused otherwise).
- `-Mode`: `mirror`, `native` or `both`.
- `-Members`: building-model ids to compare member by member (default: two columns of the
  lowest storey and two beams of the first level).
- `-SkipSaengine`: reuse `<Out>\data` from a previous run (only the ETABS part again).

Outputs: `<Out>\<mode>\report.md` and `results.json`
(`schema: saengine.referenceComparison/1`: every quantity with both values, the difference,
the tolerance, `PASS`/`FLAG`/`MISSING` and a reason); `<Out>\data` holds SAEngine's results
(`saengine.json`), the models sent (`mirror_input.json`, `native_input.json`) and ETABS's raw
results (`reference_<mode>.json`); `<Out>\models` holds the ETABS model files.

Steps, also usable one by one:

1. `python sae_export.py --project <copy> --out <dir> [--members ...] [--skip-run]`: runs
   `saengine run-all --steps derive analysis` on the copy and writes the three JSON files.
2. `powershell -File etabs_run.ps1 -InputJson <x_input.json> -OutputJson <ref.json> -WorkDir <dir>`:
   builds, runs (one run per stiffness set: gross for gravity, cracked for the lateral cases
   and the modes, as SAEngine) and reads ETABS's results. Always closes ETABS (`ApplicationExit`
   in `finally`). It records the process it started (`<ref.json>.pid`: id and start time);
   if a run dies, only that process is stopped, never another ETABS session. A run that
   refuses to start (exit code 2, e.g. because an instance is already open) stops nothing.
3. `python compare.py --saengine saengine.json --reference ref.json --out <dir>`.

A building of 6 storeys takes a few minutes per mode (ETABS's API calls dominate).

## Licence and data rules

- ETABS is driven only through its documented .NET API, hidden; never its GUI, never
  screenshots of it, never decompiled.
- **No ETABS file goes into the repository**: models (`.edb`, `.e2k`, ...), its result files and
  the JSON it produces stay in the output folder, which the script refuses to place inside the
  repository.
- Public documents may compare SAEngine with "a commercial analysis program" but never name it;
  the reports this tool writes say "the reference".
- Use your own or synthetic projects; a client's project stays on the client's machine.

## Known limits

- Native mode leaves out what has no direct ETABS object here: solid blocks, stairs (SAEngine
  leaves them out too), partitions with no beam under them, and wind (WX, WY are not compared in
  native mode). MEP equipment goes on the slab as point loads at its support points (or the
  quarter points of its footprint).
- A second frame on the same line as another (SAEngine allows it) becomes an axial link.
- Storey drifts are those of the diaphragms' centres of mass; levels without a diaphragm are
  skipped.
