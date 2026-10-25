# Independent solver cross-check: PyNite and CalculiX

The Verification Manual checks SAEngine against closed-form solutions and hand calculations.
This cross-check adds a second kind of evidence: it takes the **analysis model SAEngine
derives** (`08 FEM/model.osmodel`: nodes, frame elements with their sections, axes, rigid end
zones and releases, shells, rigid diaphragms, supports, lumped masses and load cases), rebuilds
it element by element in two independent open-source programs, solves it there and compares the
results with SAEngine's own (OpenSees through OpenSees Studio).

- **PyNite** (`PyNiteFEA` 3.2.0, MIT licence, <https://github.com/JWock82/Pynite>): a Python
  3D frame and plate program.
- **CalculiX** (`ccx` 2.23, GPL, <http://www.calculix.de>): a general finite element program,
  used as a separate executable (`subprocess`); nothing of it is linked, imported or shipped
  with SAEngine.

It is a **solver check**: the three programs solve the same mesh, so a difference points at an
element formulation, a modelling convention or a bug, never at the mesh. The code is in
`scripts/crosscheck/`; it runs locally, never in CI.

RESULTS_PLACEHOLDER

## Setting it up

Both programs are downloaded by the developer, outside the repository, and treated as untrusted
downloads: each in a folder of its own, run from another folder, PyNite's Python with `-I`.
Nothing of them is committed.

**PyNite** in a virtual environment of its own (do not install it into the repository's
`.venv`):

```bash
py -3.12 -m venv <scratch>/pynite-venv
<scratch>/pynite-venv/Scripts/python -m pip install PyNiteFEA==3.2.0
```

Source: PyPI, <https://pypi.org/project/PyNiteFEA/3.2.0/>, wheel
`pynitefea-3.2.0-py3-none-any.whl`, sha256
`3e2d0e8e294ac1b328c756349131596b39c4c4dfce3663ec3b53cbf16f6aa99b` (it pulls numpy, scipy and
its other requirements from PyPI).

**CalculiX** for Windows from its author's site, the archive the CalculiX download page
(<http://www.dhondt.de/>) lists as the Windows update of version 2.23:

- <https://www.dhondt.de/calculix_2.23_4win.zip>, sha256
  `87fc4e1721df37370ec67d0a244bb14f9bf804b0a95df49e2ae7369d30ec72e8`;
- unpacked into a folder of its own; the harness uses `calculix_2.23_4win/ccx_static.exe`
  (sha256 `e18360eb32a5cd48f91a212c57069212cd8e27d2f798a599a78106bd0b3ecc1f`, SPOOLES and
  PaStiX solvers, no DLLs needed); `ccx_static.exe -v` prints `This is Version 2.23`.

The CalculiX sources of that build are `http://www.dhondt.de/ccx_2.23.src.tar.bz2` (its
README). The CalculiX manual (`ccx_2.23.pdf`) and test suite (`ccx_2.23.test.tar.bz2`) on the
same site document the user elements U1 and US3 used here.

## Running it

With SAEngine's Python and the worktree's sources on `PYTHONPATH`:

```bash
python scripts/crosscheck/run.py --work <scratch>/cc --pynite-python <scratch>/pynite-venv/Scripts/python.exe --ccx <scratch>/ccx/calculix_2.23_4win/ccx_static.exe
```

`--models` picks some of the corpus (`cantilever portal offsets plate sample frame6 flatslab10
core10`), `--skip-build` reuses models already analysed in `--work`. Each model gets
`<work>/<model>/report.md` (its table, every FLAG with its reason) and `comparison.json`;
`<work>/report.md` collects them. The buildings take a few minutes each (SAEngine's derivation
and analysis dominate); they run one at a time.

The unit tests (`python -m pytest -q scripts/crosscheck/tests`) check the translation of a
small model without the solvers; with `CROSSCHECK_PYNITE_PYTHON` and `CROSSCHECK_CCX` set they
also solve it in both programs against Euler-Bernoulli beam theory.

## The pieces

| Script | Runs with | Does |
|---|---|---|
| `corpus.py` | SAEngine | builds and analyses the corpus with SAEngine's own pipeline: the small models with the Verification Manual's builders (`saengine.verification.cases`), the sample and the generated buildings (`saengine.library.generator.generate_building`) with `saengine run-all --steps derive analysis` |
| `ir.py` | SAEngine | writes the derived model as plain JSON (element axes from `saengine.fem.derive.local_axes`, rigid zones from `saengine.fem.end_zones`), one section table per analysis group (the cracked overrides of the lateral and modal cases) |
| `saengine_side.py` | SAEngine | reads SAEngine's results (OpenSees Studio's result store, SAEngine's own support-face forces `end_zones.face_forces`) at the probes |
| `run_pynite.py` | PyNite's venv, `-I` | rebuilds and solves the model in PyNite |
| `run_ccx.py` | any Python with numpy, `-I` | writes CalculiX decks, runs `ccx`, reads its `.dat` |
| `compare.py` | SAEngine | PASS or FLAG per quantity (the Verification Manual's `Quantity`), the report |
| `run.py` | SAEngine | all of it, model by model |

## How the model is rebuilt

| SAEngine (OpenSees) | PyNite | CalculiX |
|---|---|---|
| `elasticBeamColumn` (Euler-Bernoulli), local axes from `vecxz` | `Member3D` (Euler-Bernoulli), turned about its axis so its local y is SAEngine's | user element **U1** (a two-node beam not expanded into solids), Timoshenko with a very high shear factor (so Euler-Bernoulli), direction 1 = SAEngine's local y, I11 = Iz, I22 = Iy |
| torsion G·J | G·J | U1 takes G·(Iy + Iz): G is scaled by J/(Iy + Iz), but only down to E·(Iy + Iz)/3 (Poisson's ratio < 0.5): deep beams stay stiffer in torsion |
| rigid end zones (`-jntOffset`), span loads on the flexible length | a node at the flexible end and a stiff member (×10⁶) | a node at the flexible end tied by the six rigid-link equations (`*EQUATION`) |
| pinned ends: `ZeroLength` twin tied in some global DOFs | local releases (a sloped member pinned about global axes: a moment release) | the twin tied by equations in the same global DOFs |
| `ASDShellQ4` / `ASDShellT3` | `Quad3D` (MITC4); a triangle becomes a quadrilateral with a mid-edge node of its own | user element **US3** (three-node shell, not expanded); a quadrilateral is two triangles over its shorter diagonal |
| cracked shells: membrane factor and `Ep_mod` (bending) | two coincident layers that give both stiffnesses (`ir.layers`) | the same layers |
| `rigidDiaphragm` (u_x, u_y, r_z of the floor follow the retained node) | stiff link members from the retained node, rigid in plane, released out of plane | `*EQUATION` per node |
| lumped masses (horizontal only) | PyNite's stiffness matrix with SAEngine's masses as they are, eigenvalues by `scipy.sparse.linalg.eigsh` (PyNite's own modal analysis turns loads into masses in all three directions) | `MASS` elements on auxiliary nodes tied to one direction each |
| uniform span loads | member distributed loads | consistent nodal loads, the fixed-end forces added back to the section forces |

Every quantity is read where SAEngine reports it: base reactions summed over the supports
(moments about the origin), the top node's displacement (and a plate's centre), storey drifts at
the diaphragms' retained nodes, the first three periods with their effective masses, member
section forces at the flexible ends and at the support faces SAEngine designs for
(`faces.json`), shell resultants at the element centre (as invariants: the mean of the two
normal resultants and the radius of their circle, so the elements' own in-plane axes do not
matter). Forces are compared as magnitudes on SAEngine's element axes.

## Tolerances

| Quantity | Tolerance | Floor (passes below it) |
|---|---|---|
| Base reactions | 0.5 % | 0.01 % of the case's largest force |
| Periods (first 3) | 2 % | - |
| Effective modal masses | 5 % | 1 % of the total mass |
| Displacements, storey drifts | 5 % | 0.001 mm; 10⁻⁴ ‰ |
| Member forces | 5 % | 2 % of the member's largest force or moment in the case, at least 0.5 % of the largest of all probed members |
| Shell resultants | 5 % | 2 % of the largest of the probed shells |

## What the two programs cannot do here (and how that is handled)

- **PyNite** has no rigid diaphragms, rigid end offsets, triangular plates or direction-wise
  nodal masses: the equivalents above. Stiff members are penalties; at ×10⁴ they left in-plane
  forces of about 1.5 kN in a short beam of a rigid floor where the exact constraint gives none,
  at ×10⁶ they are gone.
- **CalculiX**: the beam elements B31/B32 are expanded into solids and take only geometric
  sections, so the user element U1 is used; its torsion limit is above. U1 takes no span loads
  and its torsional moment output is not usable (T is not compared). Two behaviours of ccx 2.23
  found on the way, both handled in `run_ccx.py`: the nodal reaction (RF) of a U1 element has
  its axial part with the wrong sign (displacements and section forces are right; the reactions
  are put right with the elements' own axial forces), and a node used only by equations has no
  rotational DOFs (its rotations act as held), so such a node gets a negligible beam.
  ARPACK does not start on the one-to-three-element models (cantilever, portal: their periods
  are checked against PyNite only).
- Orthogonal buildings only for now (sloped and skewed members are rebuilt, but the corpus has
  none beyond the sample's brace).
