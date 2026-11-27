# SAEngine verification pack

The verification pack runs a set of benchmark problems through SAEngine and compares each
result with an independent reference: a closed-form solution, a published benchmark, or a hand
calculation written out step by step in the case. Each compared quantity passes when SAEngine's
value is within a stated relative tolerance of the reference.

The code is in `python/src/saengine/verification/`. The cases are in `cases/analysis.py`, `cases/advanced.py` (the advanced analyses of #290), `cases/parity.py` (the analysis model's conventions of version 0.0.44), `cases/depth.py` (the depth tests of issue #298), `cases/bim_mep.py` (the BIM and MEP depth tests of issue #299) and
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
  building's gravity load, `saengine.library.generator`) in `cases/beta.py`. Masonry walls
  by the code pack's allowable stress method (`saengine.design.masonry_asd`) have DY1 (a plain
  brick wall at 50 % of the allowable stresses) and DY2 (a reinforced strip on the cracked
  transformed section) in `cases/masonry.py`.

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
| AX1 | Linear buckling: pin-ended column (one member) and fixed-base sway portal, Pcr and the column's K | Euler π²EI/L² (Timoshenko & Gere, 2nd ed., Art. 2.1-2.2); sway alignment chart, AISC 360-16 Commentary Eq C-A-7-2 with G_B = 0 |
| AX2 | Cable under its own weight, level and inclined chords: H, sag, end tensions; the closed form and 40 OpenSees cable elements | Irvine, Cable Structures (1981), Ch 1, elastic catenary run forwards from a chosen H |
| AX3 | Four lead-rubber isolators: keff and βeff at 150 mm, design displacement, effective period and damping by the equivalent linear iteration | Naeim & Kelly (1999) Ch 4 bilinear keff, βeff; BNBC 2020 Part 6 Eqs 6.2.62-6.2.63 (p. 661), Table 6.2.24 (p. 662), Eqs 6.2.34-6.2.35 (p. 615) |
| AX4 | Viscous damper brace in one storey, linear and α = 0.5: added damping ratio | ζ = C cos²θ/(2mω) (Chopra, 5th ed., Sec 2.2, 3.8); λ C ω^α δ^(1+α) energy per cycle (Christopoulos & Filiatrault 2006, Ch 5) |
| AX5 | Moving loads: mid-span influence ordinate, HL-93 truck × 1.33 + lane at mid-span of a 20 m span, absolute maximum moment, support moment influence of two spans | Influence lines and Barré's theorem (Hibbeler, 10th ed., Ch 6); AASHTO LRFD 9th ed. Art 3.6.1.2, 3.6.2.1; M_B = −a(L² − a²)/(4L²) |
| AX6 | Time history of a column with two masses under a two-sine record: peak displacement of both levels | Modal superposition (Chopra, 5th ed., Ch 12-13), cantilever flexibility coefficients, each mode by Newmark average acceleration |
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
| AG1 | P-Delta: 4 m cantilever column, P = 2500 kN preload and H = 20 kN: tip sway, amplification, base moment | Beam-column: δ = H (tan uL − uL)/(P u), M = H L + P δ (Timoshenko & Gere) |
| AG2 | Uniform three-storey shear building, the case's own spectrum: periods, modal mass ratios, CQC roof displacement and base shear | ωn = 2√(k/m) sin((2n−1)π/(2(2N+1))) (Chopra; Clough & Penzien); Der Kiureghian's CQC |
| AG3 | Rigid diaphragm over four cantilever columns of unequal stiffness, eccentric load: twist, translation at the centre of rigidity, displacements, stiff column's shear | Centre of rigidity and storey torsion by hand (3EI/h³, GJ/h) |
| AG4 | Two-storey cantilever wall of shells: pier P, V2 and M3 at the base and at level 1 (`design.wall_forces`) | Statics of the free body above each cut |
| DG5 | Strong column / weak beam ΣMnc ≥ 1.2 ΣMnb and the beam's capacity shear Ve at one joint (`design.ductile_joints`), ratio and 1.25 fy from the code pack | BNBC 2020 Part 6 Sec 8.3.5.2, 8.3.8.1(a); strain compatibility by hand |
| DG6 | Cantilever retaining wall: Rankine thrust, FS overturning and sliding, base pressures, stem moment, shear and φMn (`substructure.retaining_walls`) | Textbook procedure (Das; Bowles), friction and 1.6H from the code pack |
| AG7 | The A3 portal in the floor plan, exported to e2k and read back: identical sway and base moment, both against slope-deflection | Slope-deflection; the original model's results |
| AG8 | Support settlement case ST (`fem.settlement`) on a fixed-ended beam: end moment and shear | 6EIΔ/L², 12EIΔ/L³ with the columns' axial shortening |
| AG9 | Semi-rigid diaphragm: 16 × 4 m slab of shells spanning in its plane between two walls: midspan deflection and moment | Plane-stress elasticity (Timoshenko & Goodier, Art. 22); statics |
| DG10 | One-bay bill of quantities (concrete, formwork, bars by size) and beam B1's bar schedule (links, cutting lengths, hook tails, mass) | Hand take-off by the estimating rules; BNBC 2020 8.1.2 and BS 8666:2005 |
| DI1 | IFC4 and IFC2X3 exports of a two-bay frame with a stair validated; a third-party IFC (buildingSMART Simple-Scene Building-Architecture, IFC2X3, CC BY 4.0) validated and adopted: walls, rooms, wall lengths and widths | `ifcopenshell.validate` with the EXPRESS rules; the sample's own IfcWall/IfcSpace counts and Qto_WallBaseQuantities |
| DI2 | Every drawing sheet of the two-bay frame written as DWG (LibreDWG dxf2dwg) and read back (dwg2dxf): sheets written, entities, (layer, type) groups that differ | The sheets' own DXF counted with ezdxf; without LibreDWG only the copy handed to dxf2dwg (entities kept, no MTEXT rotation left) |
| DI3 | Clash benchmark: a DN100 pipe through a 300 mm beam and a duct riser 50 mm off a beam, 100 mm clearance test; the clashes out to BCF 3.0 and into a fresh coordination | Hand placement: overlap 300 mm, gap 50 mm; topics, elements and viewpoints read back |
| DI4 | Two-bay frame on six isolated footings: concrete, formwork and excavation by element group | Hand take-off by the BOQ's stated measurement rules |
| DI5 | The bill split by phase: bay A-B existing with its slab demolished, bay B-C new | Hand split of the DI4 take-off |
| DI6 | One room's cooling load (`hvac.fallback`) on the inputs of a published worked example: humidity ratios, glass conduction, lights, equipment, people | NPTEL / IIT Kharagpur, Refrigeration and Air Conditioning, Lesson 35, Q 10 |

## Results at the time of writing

122 of the 124 cases pass (beta after 0.0.52, 27 Nov 2026, with the advanced analysis cases AX1-AX6 of #290, the depth tests AG1-DG10 of #298 and the BIM and MEP depth tests DI1-DI6 of #299); A9 and DG10 fail on the known issues below. AH1 was skipped on that machine (EnergyPlus not installed); DI2 ran with LibreDWG 0.14.
Every case added since 0.0.45 passes. The table lists the largest deviation in each case (AH1
compares no ratios: it passes when its checks hold):

| Case | Ratio | Tolerance | Case | Ratio | Tolerance |
|---|---|---|---|---|---|
| A1 | 1.0000 | 1 % | DX3 | 0.9965 | 1 % |
| A2 | 1.0000 | 1 % | DX4 | 1.0000 | 0.5 % |
| A3 | 1.0020 | 1 % | DY1 | 0.9933 | 1 % |
| A4 | 0.9989 | 1 % | DY2 | 1.0000 | 0.1 % |
| A5 | 1.0000 | 1 % | D6 | 0.9983 | 0.5 % |
| A6 | 1.0000 | 1 % | D7 | 1.0000 | 0.5 % |
| A7 | 1.0224 | 3 % | D8 | 1.0000 | 0.5 % |
| A8 | 0.9952 | 2 % | D9 | 0.9942 | 1 % |
| A9 | 0.9247 (fail) | 5 % | D10 | 1.0000 | 0.5 % |
| A10 | 1.0000 | 1 % | D11 | 0.9999 | 0.5 % |
| AP1 | 1.0000 | 0.1 % | D12 | 1.0024 | 1 % |
| AP2 | 1.0000 | 0.1 % | D13 | 1.0000 | 0.1 % |
| AP3 | 1.0000 | 1 % | DS1 | 1.0001 | 0.5 % |
| AP4 | 1.0000 | 0.1 % | DS2 | 1.0000 | 0.5 % |
| AT1 | 1.0000 | 1 % | DS3 | 1.0004 | 0.5 % |
| AT2 | 1.0000 | 1 % | DP1 | 1.0001 | 0.5 % |
| AT3 | 1.0026 | 2 % | DP2 | 0.9999 | 0.5 % |
| AS1 | 1.0000 | 1 % | DP3 | 1.0000 | 0.5 % |
| D1 | 1.0000 | 1 % | DP5 | 0.9999 | 0.5 % |
| D2 | 1.0000 | 0.5 % | DP6 | 0.9997 | 1 % |
| D3 | 1.0000 | 0.5 % | DP4 | 1.0185 | 3 % |
| D4 | 1.0000 | 0.5 % | DM1 | 1.0000 | 0.5 % |
| D5 | 1.0000 | 0.5 % | DM2 | 1.0000 | 0.5 % |
| DR1 | 1.0002 | 1 % | DM3 | 1.0000 | 0.5 % |
| DR2 | 1.0000 | 0.5 % | AM1 | 1.0000 | 1 % |
| DR3 | 1.0000 | 0.5 % | DB1 | 1.0000 | 0.5 % |
| DR4 | 1.0000 | 0.5 % | DB2 | 1.0000 | 0.5 % |
| DR5 | 1.0010 | 1 % | DB3 | 1.0000 | 0.5 % |
| DL1 | 1.0000 | 0.1 % | DB4 | 1.0000 | 0.5 % |
| DL2 | 1.0001 | 0.1 % | DB5 | 1.0000 | 0.5 % |
| DL3 | 0.9996 | 0.1 % | DW1 | 0.9990 | 0.5 % |
| DT1 | 1.0000 | 0.0001 % | DW2 | 1.0028 | 1 % |
| DT2 | 0.9999 | 0.1 % | DW3 | 1.0008 | 0.5 % |
| DT3 | 1.0000 | 0.0001 % | AK1 | 1.0137 | 2 % |
| DT4 | 1.0005 | 0.2 % | DK1 | 1.0001 | 0.5 % |
| DQ1 | 1.0000 | 1 % | DK2 | 1.0000 | 0.5 % |
| DZ1 | 1.0000 | 0.1 % | DK3 | 1.0003 | 0.5 % |
| DZ2 | 0.9999 | 0.5 % | DE1 | 1.0000 | 0.5 % |
| DV1 | 1.0000 | 0.1 % | DE2 | 1.0000 | 0.5 % |
| DV2 | 1.0000 | 0.1 % | DE3 | 1.0000 | 0.5 % |
| DV3 | 1.0000 | 0.1 % | DE4 | 1.0000 | 0.5 % |
| DV4 | 1.0000 | 0.1 % | DF1 | 1.0000 | 0.5 % |
| DV5 | 1.0000 | 0.1 % | DF2 | 1.0000 | 0.5 % |
| AN1 | 1.0000 | 1 % | DF3 | 1.0003 | 1 % |
| DN1 | 1.0000 | 0.5 % | DF4 | 1.0000 | 1 % |
| AN2 | 0.9945 | 1 % | DA1 | 1.0000 | 0.5 % |
| DN2 | 1.0000 | 0.5 % | DA2 | 1.0000 | 0.5 % |
| DN3 | 1.0000 | 0.5 % | DA3 | 1.0000 | 0.5 % |
| AN3 | 1.0000 | 0.5 % | DH1 | 1.0203 | 3 % |
| DX1 | 1.0000 | 0.5 % | DH2 | 1.0000 | 0.5 % |
| DX2 | 1.0000 | 0.1 % | AH1 | pass | - |
| AX1 | 1.0075 | 1 % | AX2 | 1.0005 | 0.5-1 % |
| AX3 | 1.0000 | 0.1-0.5 % | AX4 | 1.0000 | 0.1 % |
| AX5 | 0.9977 | 0.1-0.5 % | AX6 | 1.0000 | 1 % |
| AG1 | 0.9997 | 1 % | DG6 | 1.0016 | 0.5 % |
| AG2 | 1.0000 | 1 % | AG7 | 1.0020 | 1 % |
| AG3 | 1.0000 | 1 % | AG8 | 1.0000 | 1 % |
| AG4 | 1.0003 | 0.1 % | AG9 | 0.9964 | 2 % |
| DG5 | 0.9999 | 0.5 % | DG10 | 0.9583 (fail) | 0.0001 % |
| DI1 | 1.0000 | 0.5 % | DI2 | 1.0000 | 0.5 % |
| DI3 | 1.0000 | 0.5-1 % | DI4 | 0.9999 | 0.5 % |
| DI5 | 1.0001 | 0.5 % | DI6 | 1.0249 | 0.5-3 % |

The MEP cases (DM1-DM3, AM1, DB1-DB5, DW1-DW3, AK1, DK1-DK3, DF1-DF4, DE1-DE4, DA1-DA3,
DH1-DH2) were run again in this pack run for issue #299, after the "from memory" values were
checked (next section): all pass with the ratios above; DF3 and DE3 are unchanged (1.0003, 1.0000)
because no checked value changed.

## Known issues (failing cases)

- **A9, linear tetrahedra.** Blocks mesh into four-node tetrahedra, which are stiff in bending.
  At the default mesh and at 100 mm (the smallest mesh size Project Settings accept) the tip
  deflection is about 8 % low (ratios 0.925 and 0.928). Only a 50 mm mesh, below the
  settings' minimum, comes within 5 % (0.972).
- **DG10, hook tails of Ø20 and larger bars (#386).** The detailing sizes a beam bar's 90°
  hook with the code's bend (6 db, r = 60 mm for Ø20: A = 320 mm), but the bar schedule bends
  it on BS 8666's larger minimum radius (70 mm). As bent, the hook's straight tail is
  A - r - d = 230 mm, short of the 12 db = 240 mm of the standard hook. The cutting lengths
  round up to the same 6850 mm, and Ø16 is consistent; the rest of DG10 passes.

## Other observations recorded by the cases

- **DI1, DI2 (fixed, #299).** The IFC2X3 export left `IfcStair.ShapeType`, required in IFC2X3,
  unset, so a project with a stair failed the schema; `library/ifc.py` now fills it (also for
  ramps and roofs). LibreDWG 0.14's `dxf2dwg` refused 16 of 21 sheets of the sample project
  ("Invalid DXF code 50 for MTEXT": the rotation of a rotated note), so DWG export failed for
  every plan; `library/dwg.py` now hands it a copy with the rotations as text directions, and
  every sheet comes back with the same entities per layer and type. Paper-space viewports come
  back on layer 0 instead of `VIEWPORTS`, so DI2 does not compare them.
- **DI1.** No openly licensed Revit- or ArchiCAD-exported IFC could be confirmed (the
  buildingSMART repository dropped its old ones; KIT's AC20-FZK-Haus states no licence), so the
  third-party sample is a SketchUp export (`verification/data/README.md`).
- **DI6.** Only the components computed the same way are compared. On the whole room SAEngine's
  estimate is 1.40 times the example's: the exposed floor is SAEngine's bare RC slab (U 4.2
  against 1.2, with no input to change it), the roof and wall take the sol-air excess of fixed
  mean irradiances against the example's ETDs, the west glass the peak 500 W/m² against 300, and
  the infiltration standard density (1.204 kg/m³) against the outdoor air's 1.095. It is on the
  safe side for sizing plant, not a design load.
- **"From memory" values (#299).** Checked against public sources, not the printed standards
  (which are not freely available): the NFPA 13 densities, design areas, hose allowances and the
  1.2 √A rule agree with NFPA 13 (2022) as quoted by secondary sources, and the IEC 62305-3
  mesh sizes, rolling spheres and down-conductor spacings with ABB Furse's guide, which
  reproduces Tables 2 and 4. No value had to change; the code pack's sources now cite them. The
  40 % cable tray fill for power cables could not be traced to any standard (NEC 392.22(A)
  gives fill areas per tray width; 40 % is its limit for control cables in solid-bottom trays)
  and stays marked "to be checked"; so does the 0.2 ohm of reinforcement as a down conductor
  (found only in an unofficial copy).

- **AX1 (fixed).** The linear buckling analysis took one cubic element per analysis piece, and
  the derived model does not subdivide frame members. A pin-ended column drawn as one member
  buckled at 12 EI/L² instead of π² EI/L², 21.6 % high (unconservative); a sway portal was
  barely affected (0.7 %). `fem/buckling.py` now splits every frame element in two inside the
  buckling model (`SUBDIVISIONS`), which leaves the pin-ended column 0.75 % above Euler and
  drops the interior nodes from the mode shapes.
- **AX3.** The isolators are checked through the code's equivalent linear iteration. Their
  nonlinear time history (Bouc-Wen bearings in the fibre model) needs the full nonlinear
  history model and has no case yet.

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
