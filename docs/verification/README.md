# SAEngine verification pack

The verification pack runs a set of benchmark problems through SAEngine and compares each
result with an independent reference: a closed-form solution, a published benchmark, or a hand
calculation written out step by step in the case. Each compared quantity passes when SAEngine's
value is within a stated relative tolerance of the reference.

The code is in `python/src/saengine/verification/`. The cases are in `cases/analysis.py`, `cases/parity.py` (the analysis model's conventions of version 0.0.44) and
`cases/design.py`, the runner is `run.py`, and the PDF template is `templates/verification.typ`.

## Running it

From `python/`, with the project's virtual environment:

```sh
../.venv/Scripts/python -m saengine.verification                  # all cases, summary table + verification.json
../.venv/Scripts/python -m saengine.verification --pdf            # also the Verification Manual PDF
../.venv/Scripts/python -m saengine.verification --out DIR        # output folder (default ./verification)
../.venv/Scripts/python -m saengine.verification --cases A3 D5    # only some cases
../.venv/Scripts/python -m saengine.verification --fast           # skip cases marked slow (none at present)
../.venv/Scripts/python -m saengine.verification --jobs 1 --keep  # serial; keep models and results in DIR/work
```

The command prints a table of every quantity (reference, SAEngine, ratio, tolerance, pass or
fail) and writes the following:

- `verification.json`: `{meta, cases, summary}`. Each case has the fields `{id, title, category,
  description, model, reference: {source, formula, steps}, quantities: [{name, unit, reference,
  saengine, ratio, tolerance, pass}], notes, error, pass, seconds}`.
- `verification-manual.pdf` (with `--pdf`): a cover with the SAEngine version, date, platform
  and library versions; a summary table of every case and every quantity; then one page per
  case with its description, a model sketch in words, the reference derivation and the
  results table. Typst typesets the PDF from the same data, which is passed as JSON through
  `sys_inputs`, the same way as the design report.

The exit code is 0 when every case passes and 1 otherwise; at present it is 1 (see the known
issues below). The whole pack takes about 35 s on a desktop machine. The cases run in parallel threads, and each analysis runs OpenSees in its own
process.

`python/tests/test_verification.py` runs every case in about 30 s. It checks that every
quantity passes except the known issues listed in its `KNOWN_ISSUES` (a fix in SAEngine that
turns one into a pass is accepted; any other failure fails the test), that the PDF builds and
that the command line works.

## How the cases use SAEngine

- **Analysis cases** draw the structure as a Part 5 structural model (members, areas, blocks,
  supports). They derive the analysis model with `saengine.fem.derive.derive_fem`, which
  handles sections, meshing, self-weight, lumped masses, the BNBC spectrum, time-history
  records and the pushover model. They then run that model with OpenSees Studio's runner
  (`python -m opensees_studio.run`) and read the results with SAEngine's own readers
  (`saengine.fem.display.result_view`) or OpenSees Studio's result store. Where a benchmark
  needs a load or boundary condition the pipeline does not author, the case edits the derived
  project and says so in its model text. Examples are a tip load, line supports along plate
  edges and a single lumped mass.
- **Design cases** call the functions the design checks use: `saengine.design.rc`,
  `saengine.design.slab`, `saengine.substructure.shallow.design_footing` and, for the seismic
  detailing of BNBC Sec 8.3 (cases DZ1 column confinement, DZ2 joint shear in
  `cases/seismic_detailing.py`), `saengine.design.ductile_members` and `ductile_joints`. The reference is plain
  arithmetic in the case and does not use any SAEngine helper. The structural walls of BNBC
  2020 Part 6 Sec 6.6, 6.4.8 and 8.3.6 (`saengine.design.walls`) have cases DV1 (special wall
  shear, αc), DV2 (ordinary wall in-plane shear), DV3 (a P-M point of a wall section), DV4
  (boundary elements) and DV5 (a diagonally reinforced coupling beam) in `cases/walls.py`.
  The beta items have DX1 (punching with headed shear studs, `saengine.design.punching`), DX2
  (a P-M point of a flanged T wall, `saengine.design.wall_flanges`), DX3 (a lintel over a door,
  `saengine.design.lintels`) and DX4 (the building generator's base loads against the
  building's gravity load, `saengine.library.generator`) in `cases/beta.py`.

Tolerances are set from the method. They are 1 % for closed-form linear frames, where the
element formulation is exact, 0.5 % for design hand calculations (SAEngine rounds reported
checks to 0.01, the interaction-surface lookup included), and 2 % for the shell plate. They are
3 % for the pushover against the exact inelastic curve (one fiber element with a rounded
yield corner against a bilinear continuum) and 5 % for the solid of tetrahedra. No tolerance
was widened to make a case pass; where SAEngine is off, the case fails.

## What it covers

| Case | Benchmark | Reference |
|---|---|---|
| A1 | Cantilever beam, self-weight + tip load: tip deflection, fixed-end moment and shear | Euler-Bernoulli beam theory |
| A2 | Simply supported beam under its self-weight: midspan deflection and moment | 5wL⁴/384EI, wL²/8 |
| A3 | Fixed-base portal frame under a lateral load: sway and base moments | Slope-deflection (hand stiffness method) |
| A4 | Cantilever column, distributed mass: first natural frequency | 1.8751² √(EI/mL⁴) / 2π |
| A5 | One-mass oscillator under the BNBC 2020 design spectrum: period and peak displacement | Sa/ω², BNBC 2020 Part 6 2.5.4.3 |
| A6 | One-mass oscillator under a sine record: peak displacement | Independent Newmark-β integration in the case |
| A7 | Pushover of a steel I cantilever (fiber elements) to 3 % drift: initial stiffness, base moment at 1, 2 and 3 % drift | 3EI/L³; Mp = Z fy; exact inelastic cantilever δ = ∫ κ(M) s ds with the section's bilinear moment-curvature |
| A8 | Simply supported square plate under uniform load (shells): central deflection and moment | Timoshenko & Woinowsky-Krieger, α = 0.00406, β = 0.0479 (ν = 0.3) |
| A9 | Solid cantilever block (tetrahedra) under its self-weight: tip deflection at the default mesh, the finest allowed (100 mm) and 50 mm | Timoshenko beam (bending + shear) |
| A10 | Construction sequence: shortening of a three-storey column built storey by storey under its self-weight, and the same load applied at once | Statics of a column built in stages, linear elastic (staged: (j - 1/2 + j(n - j)) Wh/EA; at once: (j(n + 1/2) - j(j + 1)/2) Wh/EA) |
| AP1 | Seismic weight W of a two-storey bay lumped at the story levels: W per level, the weight to the base and the lateral mass | BNBC 2020 Part 6 Sec 2.5.7.3 (p. 628), hand sum of the dead, superimposed and 25 % live loads |
| AP2 | Eccentric static earthquake case EXP: the torsion it adds to EX at each floor | BNBC 2020 Part 6 Sec 2.5.7.6.2, Eq. 6.2.43 (p. 630): M = 0.05 L F |
| AP3 | Beam with rigid end zones (factor 0.5) between held joints under 10 kN/m: moment and shear at the column face | Fixed-ended flexible length: w Lf²/12 − w Lf x/2 + w x²/2 |
| AP4 | 125 mm brick wall (line load from loads.json) on a beam with pinned ends: reactions and mid-span moment | wL/2, wL²/8; wall weight from BNBC 2020 Part 6 Table 6.2.2 (pp. 530-531) |
| D1 | RC beam φMn, singly reinforced | ACI 318-19 22.2, 21.2.2 |
| D2 | RC beam shear with and without stirrups | ACI 318-19 Table 22.5.5.1 (a) and (c), λs |
| D3 | Tied column φPn,max and the balanced point | ACI 318-19 22.4.2, strain compatibility |
| D4 | Slab layers: effective depths and φMn per metre | ACI 318-19 22.2 |
| D5 | Isolated footing with eccentric load: bearing, punching (with moment transfer), one-way shear and flexure at the face in X and Y, each with its own layer's d | ACI 318-19 13.2.7, 22.6, 8.4.4.2, 22.5 |
| D6 | Site class of a 30 m borehole from the harmonic mean of its field SPT N values | BNBC 2020 Table 6.2.13; harmonic mean as ASCE 7-16 20.4 |
| D7 | Net allowable bearing pressure against shear failure: square footing on sand (drained), rectangular footing on clay (undrained), FS = 3 | General bearing capacity equation, Vesic (1975) factors, De Beer shape and Hansen depth factors |
| D8 | Immediate settlement of a square footing on sand | Schmertmann et al. (1978) strain influence factor |
| D9 | Liquefaction factor of safety at one SPT test: rd, CSR, (N1)60cs, CRR and FS | Idriss & Boulanger (2014) SPT procedure |
| D10 | SPT corrections of the Bangladesh consultant practice: σ'v per row, CN, N60 with rod-length factors, (N1)60 and the dilatancy N' | Peck, Hanson and Thornburn (1974) CN; Terzaghi and Peck dilatancy correction |
| D11 | Settlement-limited allowable bearing pressure with N' averaged over the zone from Df - B/2 to Df + 2B | Meyerhof (1965) as modified by Bowles, 25 mm |
| D12 | Liquefaction factor of safety at one SPT test with amax = (2/3) Z S | BNBC 2020 Sec 3.9.5 (Eqs 6.3.6-6.3.8, rd = 1 - 0.015z, no 0.65 factor), CRR by Youd et al. (2001) |
| D13 | Depth of boring below a long footing and the soil corrosivity score of one sample | BNBC 2020 Sec 3.4.5(i) (2B to 4B by L/B), Tables 6.3.6a-6.3.6b |
| AN1 | Slab load on a beam: the 45° triangle of a square two-way panel applied member by member (`cases/correctness.py`): edge total, fixed-end and midspan moments, simple-span midspan moment | 5 w L²/96, w L²/32, w L²/12 (BNBC 2020 Part 6 Sec 6.5.6.8.1, p. 955) |
| DN1 | Two-way slab by the coefficient method, case 4, m = 0.80 and the interpolation at m = 0.825 | BNBC 2020 Part 6 Tables 6.6.8-6.6.10 (pp. 961-964), values read from the code |
| AN2 | Live load arrangement on three equal spans: end-span and support moments of the envelope and of the full load | Three-moment equation: 0.10125 wL², 7 wL²/60; 0.08 wL², wL²/10 (BNBC 2020 Part 6 Sec 6.1.12.2, p. 894) |
| DN2 | Beam torsion: φTth, At/s, Al and the section limit | BNBC 2020 Part 6 Sec 6.4.4, Eqs. 6.6.59, 6.6.61-6.6.63 |
| DN3 | Deflection: Icr, Mcr, Ie and the immediate deflection of a simple span | BNBC 2020 Part 6 Eqs. 6.6.1-6.6.3; 5 w l⁴/384 Ec Ie |
| AN3 | Wind torsional case WTX of a three-storey bay: total torsion and no net force | BNBC 2020 Part 6 Figure 6.2.9 (p. 574): Mt = F · 0.15 B per level |

## Results at the time of writing

92 of the 93 cases pass (0.0.45); A9 fails on the known issue below. The table lists the
largest deviation in each case:

| Case | Ratio | Tolerance | Case | Ratio | Tolerance |
|---|---|---|---|---|---|
| A1 | 1.0000 | 1 % | D1 | 1.0000 | 1 % |
| A2 | 1.0000 | 1 % | D2 | 1.0000 | 0.5 % |
| A3 | 1.0020 | 1 % | D3 | 1.0000 | 0.5 % |
| A4 | 0.9989 | 1 % | D4 | 1.0000 | 0.5 % |
| A5 | 1.0000 | 1 % | D5 | 1.0000 | 0.5 % |
| A6 | 1.0000 | 1 % | D6 | 0.9983 | 0.5 % |
| A7 | 1.0224 | 3 % | D7 | 1.0000 | 0.5 % |
| A8 | 0.9952 | 2 % | D8 | 1.0000 | 0.5 % |
| A9 | 0.9247 (fail) | 5 % | D9 | 0.9942 | 1 % |
| A10 | 1.0000 | 1 % | D10 | 1.0000 | 0.5 % |
| AP1 | 1.0000 | 0.1 % | | | |
| AP2 | 1.0000 | 0.1 % | | | |
| AP3 | 1.0000 | 1 % | | | |
| AP4 | 1.0000 | 0.1 % | | | |
| | | | D11 | 0.9999 | 0.5 % |
| | | | D12 | 1.0024 | 1 % |
| | | | D13 | 1.0000 | 0.1 % |

## Known issues (failing cases)

- **A9, linear tetrahedra.** Blocks mesh into four-node tetrahedra, which are stiff in bending.
  At the default mesh and at 100 mm (the smallest mesh size Project Settings accept) the tip
  deflection is about 8 % low (ratios 0.925 and 0.928). Only a 50 mm mesh, below the
  settings' minimum, comes within 5 % (0.972).

## Other observations recorded by the cases

- **A2.** Two pinned supports leave a straight member free to spin about its own axis, and
  the solver rejects that mechanism. The case holds the twist at the supports, as fork
  supports do.
- **A4.** Frame members are not subdivided by the mesh size, and their masses are lumped at
  the member ends. A column drawn as one member therefore has a natural frequency about 30 %
  too low. The case draws the column as 20 members.
- **A7.** SAEngine's steel (Steel02) hardens by 1 % of E after yield, so a pushover does not
  cap at Mp. The exact response of the same cantilever is 1.04, 1.11 and 1.16 Mp at 1, 2 and
  3 % drift; SAEngine follows it within -1.8 % to +2.2 % (lower near the knee, where Steel02
  rounds the yield corner; higher at large drift, where one element lumps the plastic
  curvature at its base integration point).
- **D3 (fixed).** The φ-factored interaction diagram bends inwards where φ leaves 0.65
  (εt = εy, the balanced point) and where it reaches 0.90 (εt = εy + 0.003). The chords of
  `rc.InteractionSurface` used to cross the balanced corner, giving φMn at φPnb as 193.06 kN·m
  against the exact 190.98 kN·m (1.1 % unconservative). Every meridian now has points at both
  corners and 11 between them, so this case reads a computed point. Between meridians the
  surface is interpolated at equal εt (so with equal φ) instead of by chords at the demand's
  axial force, which overstated biaxial capacity by up to 1.4 %; `tests/test_design.py` checks
  it against exact points off the meridians (at most 0.4 % above; 0.35 % was the largest
  found over nine sections).
- **D5 (fixed).** `design/footing.py` used one d = h - cover - largest bar diameter (509 mm
  here) for both directions. It now takes each direction's own layer for flexure and one-way
  shear (X outer: 517 mm, Y inner: 501 mm, as in slabs) and their mean for punching.

## Independent solver cross-check

Beside the closed-form references, `scripts/crosscheck/` rebuilds the analysis model SAEngine
derives in two independent open-source programs, PyNite and CalculiX, and compares reactions,
displacements, drifts, periods, member forces and shell resultants on a corpus from a cantilever
to ten-storey buildings. It runs locally (the programs are not installed in CI); see
[cross-check.md](cross-check.md) for the setup, the method and the latest results.

## Adding a case

Write a function `run(folder: Path) -> Outcome` in `cases/analysis.py`, `cases/design.py` or
`cases/soil.py`. It
returns a `Reference` (source, formula, steps) and a list of `Quantity(name, unit, reference,
saengine, tolerance)`. Add a `Case(id, title, category, description, model, run, fast=...)` to
that module's `CASES`. Cite the reference by name, and do not copy text from it.
