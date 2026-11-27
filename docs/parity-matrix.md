# Feature parity matrix

SAEngine compared, feature by feature, with the programs engineers use today: **ETABS, SAP2000,
STAAD.Pro, SAFE and Robot** (part 1) and **Revit, AutoCAD and typical MEP design tools** (part 2).
It is the plan's honest baseline: what SAEngine has, what is proven, and what to build or check
next.

How to read it:

- **SAEngine status**
  - **Verified:** a test or verification case in the repository checks the feature against a hand
    calculation or a published value.
  - **Built, untested:** the code exists, possibly with unit tests, but nothing checks it against an
    independent result yet.
  - **Partial:** some of the feature exists; the row says what is missing.
  - **Missing:** nothing found in the code after searching.
  - **Out of scope (decision):** deliberately not built, with the reason.
- **Other programs' columns** come only from their public documentation and general knowledge: ✓
  has it, – does not, *add-on* needs a separate product, ? not sure. None of them was run.
- **Evidence** paths are relative to the repository root. The statuses were found by reading the
  repository on 12 November 2026; the verification pack was not re-run for this document (its last
  recorded run is in [verification/README.md](verification/README.md)).

Overall: **348 features**: 154 verified, 160 built but untested, 20 partial, 8 missing, 6 out of
scope by decision. The gaps and the first verifications to do are tracked on the
[project board](https://github.com/orgs/The-Studio-of-Sadiq/projects/8).

## Part 1: analysis and design (ETABS, SAP2000, STAAD.Pro, SAFE, Robot)

**Paths.** Evidence paths are relative to the repository root (branch `beta`).

**What the statuses rest on.**
- The repository was read, not run: neither pytest nor the verification pack was run for this document.
- "Verified" means a verification case, or a test that checks against a hand or closed-form value, exists in the repo.
- The last recorded pass/fail results are in `docs/verification/README.md`: 92 of 93 cases passed at version 0.0.45, and A9 fails. Cases added since then have no recorded result in that table, so their current pass state is unconfirmed: AN/DN, DR, DQ, DL, DT, DS, DP, DK, AT, AS, DV, DX, DY, DZ.

**How to read the program columns.**
- ✓ = has the feature; – = does not; add-on = needs a separate product; ? = not sure.
- They come only from public knowledge of these programs. None of them was run.

### 1. Modelling

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Cartesian grid lines | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/library/floorplan.py (Grids); workbench/src/vs/workbench/contrib/saengineLibrary/browser/gridsEditor.ts | 5 | Coordinates of an imported published example building, round trip |
| Skew / cylindrical / non-orthogonal grids | ✓ | ✓ | ✓ | ✓ | ✓ | Built (#300): `grids.systems` (rotated orthogonal, radial, angled lines) in floorplan.py, one geometry helper (grid_geometry.py, gridGeometry.ts), Floor Plan > Grid Systems..., drawn and snapped; columns turn with their system. New Project wizard makes rotated and radial grids (grid_placement.py); Substructure, MEP plans and FEM elevations show every system; Revit arc grids | python/tests/test_grid_systems.py (30° frame = 0° frame), python/tests/test_grid_wizard.py | 5 | Radial frame statics by hand |
| Storeys / levels | ✓ | – | ? | – | ✓ | Built, untested | python/src/saengine/library/floorplan.py | 5 | Storey heights against a published example |
| Typical (similar) floors | ✓ | – | ? | – | ? | Built, untested | `similarTo` in python/src/saengine/library/floorplan.py; workbench/src/vs/workbench/contrib/saengineCad/browser/floorPlanTypical.ts; python/tests/test_floorplan.py | 5 | Typical-floor model gives the same results as the explicit model |
| Building generator / templates | ✓ | ✓ | ✓ | ✓ | ? | Verified (DX4) | python/src/saengine/verification/cases/beta.py; python/src/saengine/library/generator.py | 5 | Gravity takedown of the generated building by hand |
| Frame members (beam/column/brace) | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (A1–A3) | python/src/saengine/verification/cases/analysis.py | 4/5 | Closed-form beam and portal frame |
| Shell slabs / walls | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (A8, AK1) | python/src/saengine/verification/cases/analysis.py, python/src/saengine/verification/cases/tanks.py | 8 | Timoshenko plate; NAFEMS LE-type plate |
| Automatic meshing (slabs, walls, openings) | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested (only a cross-check against other solvers) | python/src/saengine/fem/mesh.py, python/src/saengine/fem/mesh_check.py; docs/verification/cross-check.md | 8 | Plate with an opening: convergence against published FE results |
| Solid elements | – | ✓ | ✓ | – | ✓ | Partial. Linear tetrahedra are about 8 % stiff at the allowed meshes (A9 known failure) | python/src/saengine/verification/cases/analysis.py (A9); python/tests/test_verification.py KNOWN_ISSUES | 8 | Solid cantilever (Timoshenko); NAFEMS LE10-type |
| Rigid diaphragm | ✓ | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/fem/derive.py; python/tests/test_fem_shells.py | 8 | One-storey building with eccentric stiffness: centre of rigidity and torsion by hand |
| Semi-rigid diaphragm | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/library/settings.py:2190 (`diaphragm` rigid/flexible); python/src/saengine/fem/derive.py | 2/8 | Slab diaphragm as a deep beam between walls, by hand |
| Rigid end zones | ✓ | ✓ | ? | – | ? | Verified (AP3) | python/src/saengine/verification/cases/parity.py; python/src/saengine/fem/end_zones.py | 8 | Fixed-ended beam with rigid zones |
| Member end releases | ✓ | ✓ | ✓ | ? | ✓ | Partial. Only steel members with simple connections are pinned automatically; the user cannot release a chosen DOF on any member | python/src/saengine/fem/derive.py:5468 (`_release_simple_ends`) | 4/5 | Propped cantilever with a released end |
| Insertion points / member offsets | ✓ | ✓ | ✓ | ? | ✓ | Partial. Plan offsets from grid points and end offsets exist; no vertical cardinal-point offsets found (searched cardinal, insertion) | python/src/saengine/library/floorplan.py (GridPoint offset); python/src/saengine/fem/derive.py (endOffsets) | 5 | T-beam with an offset flange: stiffness by hand |
| Panel zones in the analysis | ✓ | ✓ | – | – | ? | Partial. Steel panel zones are checked in design; their deformation is not in the analysis model | python/src/saengine/design/steel/seismic.py (panel_zone_checks) | 8 | Textbook panel-zone sway example |
| Fixed / pinned supports | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (A1–A3) | python/src/saengine/verification/cases/analysis.py; python/src/saengine/library/structure.py (Support) | 5 | Closed-form beams |
| User point / joint springs | ✓ | ✓ | ✓ | ✓ | ✓ | Missing. Searched pointSpring, nodal spring, supportSpring; supports are only fixed or soilSprings (settings.py:2670) | – | 5/8 | Beam on a spring support, by hand |
| Line / area (subgrade) springs | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (DP4; Westergaard; partial contact) | python/src/saengine/verification/cases/substructure_deep.py; python/tests/test_substructure_raft.py | 9 | Plate on Winkler foundation |
| General link elements (gap, hook, multilinear) | ✓ | ✓ | ? | ? | ? | Partial. zeroLength links are used only for isolators, dampers and pins | python/src/saengine/fem/isolation.py, python/src/saengine/fem/dampers.py, python/src/saengine/fem/derive.py | 8 | Gap-contact problem in the style of a CSI verification example |
| Section Designer | ✓ | ✓ | ✓ | – | ✓ | Verified (L and box properties against hand formulas) | python/tests/test_section_designer.py; python/src/saengine/library/section_designer.py; workbench/src/vs/workbench/contrib/saengineLibrary/browser/sectionDesignerEditor.ts | 4 | Section properties by hand |
| Steel section tables | ✓ | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/library/steel_sections.py | 4 | Properties against published section tables |
| Property / stiffness modifiers | ✓ | ✓ | ? | ✓ | ? | Built, untested | python/src/saengine/library/modifiers.py | 4 | Cantilever with 0.7 I, by hand |
| Cracked stiffness set by the code | ? | ? | ? | ? | ? | Built, untested. The test only checks that the factors are applied | python/src/saengine/fem/second_order.py; python/tests/test_fem_second_order.py | 8 | Frame drift with 0.35/0.70 I, by hand |
| Material library | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/library/materials.py, python/src/saengine/library/defaults.py | 3 | Ec and density by code formula |
| Slab and wall openings | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/fem/mesh.py; python/tests/test_boq.py | 5 | Plate with an opening (published FE) |
| Ribbed / waffle slabs, drop panels | ✓ | ? | – | ✓ | ? | Built, untested | python/src/saengine/design/slab_systems.py; python/tests/test_design_slab_systems.py | 4 | Equivalent-stiffness hand calculation |
| Free-form 3D (special structures, shapes, scripts) | ? | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/library/structure.py, python/src/saengine/library/shapes.py, python/src/saengine/library/script.py | 5 | 3D truss statics by hand |

### 2. Loads

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| User-defined load patterns / cases | ✓ | ✓ | ✓ | ✓ | ✓ | Built (#301, not walked yet): Project Settings › Load Patterns (id, name, type, self-weight multiplier); member, point and area loads take any pattern; one analysis case per pattern; combinations by type plus a factor table | python/src/saengine/library/load_patterns.py; python/tests/test_load_patterns.py; docs/manual/08-fem.md (Load cases) | 2 | M_mid = 1.2wL²/8 + 1.6PL/4 by hand |
| Self-weight | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (A1, A2) | python/src/saengine/verification/cases/analysis.py | 8 | wL²/8 and 5wL⁴/384EI |
| Area loads by occupancy | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (load totals; values of the code table) | python/tests/test_fem_shells.py; python/tests/test_live_loads_combinations.py | 2 | Load total by hand |
| One-way / two-way slab load to beams | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (AN1) | python/src/saengine/verification/cases/correctness.py; python/tests/test_fem_slab_load_shapes.py; python/src/saengine/fem/slab_load_shapes.py | 8 | 45° tributary area by hand |
| Wall line loads on beams | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (AP4) | python/src/saengine/verification/cases/parity.py; python/src/saengine/library/line_loads.py | 5 | wL/2, wL²/8 |
| Point loads on members and joints | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/library/line_loads.py (PointLoad); python/tests/test_line_loads.py | 5 | Pab/L by hand |
| Automatic seismic, equivalent static (default pack) | ✓ | ✓ | ✓ | – | ✓ | Verified (Ta, Sa and vertical distribution; AP1) | python/tests/test_fem_loads.py; python/src/saengine/fem/loads.py | 2/8 | Textbook equivalent-static example |
| Automatic seismic, other codes | ✓ | ✓ | ✓ | – | ✓ | Built, untested (the tests check only the pack values) | python/src/saengine/codes/packs; python/src/saengine/fem/spectra.py; python/tests/test_codes_asce7_pack.py | Code packs | Code-commentary worked example |
| Accidental torsion | ✓ | ? | ✓ | – | ✓ | Verified (AP2) | python/src/saengine/verification/cases/parity.py | 8 | M = 0.05 L F per floor |
| Vertical seismic component, Ω0 combinations | ? | ? | ? | – | ? | Built, untested | python/src/saengine/fem/seismic_design.py; python/src/saengine/design/overstrength.py | 8 | Hand combination |
| Automatic wind, default pack (main wind-force system) | ✓ | ✓ | ✓ | – | ✓ | Verified (AN3; hand pressures) | python/src/saengine/verification/cases/correctness.py; python/tests/test_fem_wind.py; python/tests/test_wind_mwfrs.py | 2/8 | Textbook wind example |
| Wind by other methods (EN, gust factor, open structures, cladding) | ✓ | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/fem/peak_velocity_pressure.py, wind_speed_factors.py, gust_response.py, open_wind.py, local_pressures.py | 8 | EN 1991-1-4 design-guide worked example |
| Notional loads | ✓ | ✓ | ✓ | – | ? | Verified (Ni = 0.002 Yi by hand) | python/tests/test_fem_notional_loads.py | 8 | Hand calculation |
| Temperature | ✓ | ✓ | ✓ | ? | ✓ | Verified (AT1–AT3) | python/src/saengine/verification/cases/thermal.py | 8 | Restrained beam αΔT EA |
| Support settlement | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/fem/settlement.py | 8 | Fixed beam 6EIΔ/L² |
| Pattern live loading | ? | ? | ? | ✓ | ? | Verified (AN2) | python/src/saengine/verification/cases/correctness.py; python/tests/test_fem_pattern_live.py | 8 | Three-moment equation |
| Live load reduction | ✓ | ✓ | ? | ? | ? | Verified (equation checked by hand) | python/tests/test_live_loads_combinations.py::test_floor_live_reduction; python/src/saengine/design/live_reduction.py | 2 | Hand calculation |
| Load combinations by code | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (factors against the code) | python/tests/test_live_loads_combinations.py; python/src/saengine/fem/combinations.py | 2 | Combinations table by hand |
| Mass source / seismic weight | ✓ | ✓ | ✓ | – | ✓ | Verified (AP1) | python/src/saengine/verification/cases/parity.py | 8 | Hand sum D + SD + 25 % L |
| Moving vehicle loads | – | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/special/moving_loads.py, python/src/saengine/special/bridges.py | 8 | AASHTO-style girder example |
| Crane runway loads | ? | ? | ? | – | ? | Verified (wheel loads by hand) | python/tests/test_cranes.py; python/src/saengine/fem/cranes.py | 8 | Hand calculation |
| Snow, rain, flood | ? | – | ✓ | – | ✓ | Built, untested | python/src/saengine/fem/snow_load.py, python/src/saengine/fem/special_loads.py, python/src/saengine/fem/flood.py | 8 | Code worked example |
| Basement earth and water pressure | – | – | – | – | ? | Built, untested (only the Ka, K0, Kp and M-O coefficients are tested) | python/src/saengine/substructure/basement_loads.py, python/src/saengine/substructure/earth_pressure.py; python/tests/test_substructure_retaining_walls.py | 9 | Textbook basement wall |

### 3. Analysis

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Linear static | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (A1–A3, AP3; PyNite and CalculiX cross-check) | python/src/saengine/verification/cases/analysis.py; docs/verification/cross-check.md | 8 | Closed form |
| P-Delta | ✓ | ✓ | ✓ | – | ✓ | Built, untested (the test only checks that the amplification is small) | python/src/saengine/fem/second_order.py; python/tests/test_fem_second_order_sample.py | 8 | Cantilever with axial load: amplification ≈ 1/(1−P/Pcr) |
| Direct analysis method (steel) | ✓ | ✓ | ✓ | – | ? | Built, untested | python/src/saengine/design/steel/stability.py; python/tests/test_steel_direct_analysis.py | 8 | AISC design-example-style frame |
| Modal (eigen) | ✓ | ✓ | ✓ | ? | ✓ | Verified (A4; periods cross-checked) | python/src/saengine/verification/cases/analysis.py | 8 | Cantilever 1.8751² frequency |
| Ritz vectors | ✓ | ✓ | ? | – | ? | Missing. Searched "ritz" in python/src and the workbench contribs | – | 8 | Same periods as eigen on a shear building |
| Response spectrum (CQC / SRSS) | ✓ | ✓ | ✓ | – | ✓ | Verified, single mass only (A5) | python/src/saengine/verification/cases/analysis.py; python/tests/test_fem_dynamic.py | 8 | Multi-storey shear building (Chopra-type) |
| Spectrum scaling to the static base shear, drift | ? | ? | ? | – | ? | Verified (DQ1) | python/src/saengine/verification/cases/rs_design.py | 8 | Hand calculation |
| Linear time history | ✓ | ✓ | ✓ | – | ✓ | Verified (A6) | python/src/saengine/verification/cases/analysis.py | 8 | Newmark SDOF |
| Record scaling and spectral matching | ? | ? | ? | – | ? | Built, untested | python/src/saengine/fem/records.py, python/src/saengine/fem/spectral_matching.py; python/tests/test_fem_nlth_design.py | 8 | PEER record scaled to a target spectrum |
| Nonlinear time history | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/fem/nonlinear.py, python/src/saengine/fem/nonlinear_history.py | 8 | Elastoplastic SDOF (textbook) |
| Pushover (fibre) | ✓ | ✓ | ✓ | – | ✓ | Verified (A7) | python/src/saengine/verification/cases/analysis.py; python/tests/test_fem_pushover.py | 8 | Exact inelastic cantilever |
| Pushover target displacement, hinges, acceptance | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/fem/pushover_target.py, hinges.py, acceptance.py | 8 | FEMA 440 / ASCE 41-style example |
| Linear buckling | ✓ | ✓ | ✓ | – | ✓ | Verified (Euler load, K factors) | python/tests/test_fem_buckling.py; python/src/saengine/fem/buckling.py | 8 | Euler |
| Nonlinear buckling (GNA / GMNIA) | ? | ✓ | ? | – | ? | Verified (path tends to Euler; within Perry bounds) | python/tests/test_fem_nonlinear_stability.py | 8 | Perry-Robertson column |
| Staged construction | ✓ | ✓ | ? | – | ✓ | Verified (A10) | python/src/saengine/verification/cases/analysis.py; python/src/saengine/fem/staged.py | 8 | Column shortening statics |
| Creep, shrinkage, column shortening | ✓ | ✓ | ? | ✓ | ? | Built, untested (only the code-figure values are tested) | python/src/saengine/fem/concrete_time.py, python/src/saengine/fem/staged.py; python/tests/test_fem_concrete_time.py, python/tests/test_fem_column_shortening.py | 8 | Published column-shortening example |
| Cable elements | ? | ✓ | ✓ | – | ✓ | Verified (elastic catenary) | python/tests/test_fem_cables.py; python/src/saengine/fem/cables.py | 8 | Irvine catenary |
| Tension-only braces | ✓ | ✓ | ✓ | – | ✓ | Verified (X-brace by hand) | python/tests/test_tension_only.py | 8 | Hand calculation |
| Compression-only soil springs | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (partial contact q_max by hand) | python/tests/test_substructure_raft.py | 9 | Rigid footing with e > L/6 |
| Base isolation | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/fem/isolation.py, isolation_single_level.py, device_response.py | 8 | ASCE 7 Ch 17 design example |
| Supplemental dampers | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/fem/dampers.py | 8 | Damped SDOF |
| Soil-structure interaction springs | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (AS1) | python/src/saengine/verification/cases/ssi.py; python/src/saengine/fem/ssi.py, python/src/saengine/fem/ssi_compare.py | 8/9 | Rocking oscillator |
| Influence lines | – | ✓ | ? | – | ? | Verified (simple span, L/4) | python/tests/test_special_structures_l9.py | 8 | Müller-Breslau |
| Bridge girders and load rating | – | ? | – | – | ? | Built, untested | python/src/saengine/special/bridges.py | 8 | AASHTO-style example |
| Floor vibration | ? | ? | ? | ? | ? | Built, untested | python/src/saengine/fem/floor_vibration.py | 8 | AISC DG11 example |
| Floor response spectra | ? | ? | ? | – | ? | Built, untested | python/src/saengine/fem/floor_spectra.py | 8 | Code formula by hand |
| Wind comfort (top-floor acceleration) | ? | – | ? | – | ? | Built, untested | python/src/saengine/fem/wind_comfort.py | 8 | Hand calculation |
| Cracked nonlinear slab analysis | ? | – | – | ✓ | ✓ | Missing. The long-term cracked deflection of FE slabs scales the linear analysis per design strip (#302); there is no nonlinear reanalysis with cracked shells | python/src/saengine/design/slab_service.py | 8 | Published long-term slab deflection |
| CFD wind | – | – | – | – | ✓ | Built, untested (optional OpenFOAM) | python/src/saengine/fem/cfd_wind/ | 8 | CAARC standard tall building |

### 4. Reinforced concrete design

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Beam flexure | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (D1, DR1, DR2) | python/src/saengine/verification/cases/design.py, python/src/saengine/verification/cases/design_mode.py; python/src/saengine/design/rc.py | 8 | Textbook beam |
| Beam shear | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (D2, DR3) | python/src/saengine/verification/cases/design.py, python/src/saengine/verification/cases/design_mode.py | 8 | Textbook |
| Beam torsion | ✓ | ✓ | ✓ | ? | ✓ | Verified (DN2) | python/src/saengine/verification/cases/correctness.py; python/tests/test_design_torsion.py | 8 | Textbook |
| Design forces at support faces | ✓ | ? | ? | ? | ? | Verified (AP3) | python/src/saengine/design/face_forces.py; python/src/saengine/verification/cases/parity.py | 8 | Hand calculation |
| Column P-M (uniaxial) | ✓ | ✓ | ✓ | – | ✓ | Verified (D3, DR5) | python/src/saengine/verification/cases/design.py, python/src/saengine/verification/cases/design_mode.py | 8 | Strain compatibility |
| Biaxial P-M-M | ✓ | ✓ | ✓ | – | ✓ | Verified (exact points off the meridians) | python/tests/test_design.py; docs/verification/README.md | 8 | Bresler / exact fibre |
| Slender columns | ✓ | ✓ | ✓ | – | ✓ | Verified (DL1–DL3) | python/src/saengine/verification/cases/slenderness.py | 8 | ACI-style moment magnifier example |
| Column shear with axial force | ✓ | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/design/column_shear.py; python/tests/test_design_column_shear.py | 8 | Hand calculation |
| Wall pier / spandrel forces from shells | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/design/wall_forces.py; python/tests/test_design_wall_forces.py | 8 | Cantilever shell wall: section-cut statics |
| Shear wall design (P-M, shear, boundary elements, flanged) | ✓ | – | ✓ | – | ✓ | Verified (DV1–DV4, DX2) | python/src/saengine/verification/cases/walls.py, python/src/saengine/verification/cases/beta.py | 8 | Textbook wall |
| Coupling beams | ✓ | – | ? | – | ? | Verified (DV5) | python/src/saengine/verification/cases/walls.py | 8 | Textbook |
| Beam-column joint shear | ✓ | ✓ | add-on | – | ? | Verified (DZ2) | python/src/saengine/verification/cases/seismic_detailing.py | 8 | Textbook |
| Strong-column/weak-beam, capacity shear | ✓ | ✓ | add-on | – | ? | Built, untested | python/src/saengine/design/ductile_joints.py, python/src/saengine/design/capacity_design.py; python/tests/test_design_ductile_joints.py | 8 | Textbook special moment frame example |
| Seismic detailing (confinement) | ✓ | ✓ | ? | – | ? | Verified (DZ1) | python/src/saengine/verification/cases/seismic_detailing.py | 8 | Textbook |
| FE slab design (Wood–Armer) | ✓ | – | ✓ | ✓ | ✓ | Verified (DR4, D4) | python/src/saengine/verification/cases/design_mode.py, python/src/saengine/verification/cases/design.py; python/src/saengine/design/slab.py | 8 | Wood–Armer by hand |
| Slab strips / equivalent frame / direct design | ✓ | – | – | ✓ | ? | Built, untested | python/src/saengine/design/slab_frames.py, equivalent_frame.py, direct_design.py | 8 | ACI/PCA flat-plate design example |
| Two-way coefficient method | – | – | – | – | ? | Verified (DN1) | python/src/saengine/verification/cases/correctness.py | 8 | Code table values |
| Punching shear (moment transfer, studs, openings) | ✓ | – | add-on | ✓ | ✓ | Verified (D5, DX1) | python/src/saengine/verification/cases/design.py, python/src/saengine/verification/cases/beta.py; python/tests/test_design_punching.py | 8 | Textbook |
| Beam deflection (Ie, long term) | ? | – | ? | ✓ | ✓ | Verified (DN3) | python/src/saengine/verification/cases/correctness.py; python/tests/test_design_deflection.py | 8 | Branson by hand |
| Long-term cracked FE slab deflection | ? | – | – | ✓ | ✓ | Built, untested (#302; known-answer hand cases only): per design strip, Ie from the bars provided and the code pack's long-term method | python/src/saengine/design/slab_service.py; python/tests/test_slab_service.py | 8 | Published flat-plate long-term deflection |
| Crack width | – | – | – | ? | ✓ | Partial. Checked for a tank wall (DK2); FE slabs per design strip and shell by the code pack's method (#302), checked by hand cases only; beams and walls not yet | python/src/saengine/design/crack_control.py; python/src/saengine/verification/cases/tanks.py; python/src/saengine/design/slab_service.py; python/tests/test_slab_service.py | 8 | EN 1992 crack-width example |
| Required reinforcement output | ✓ | ✓ | ✓ | ✓ | ✓ | Verified (DR1–DR5) | python/src/saengine/verification/cases/design_mode.py; python/src/saengine/design/required.py | 8 | Hand calculation |
| Proposed bar layout | add-on | – | add-on | ✓ | ✓ | Verified (bars proposed in DR1, DR4) | python/src/saengine/design/proposal.py, python/src/saengine/design/bars.py | 8 | Hand bar selection |
| Stairs | – | – | ? | – | ? | Verified (flight by hand) | python/tests/test_design_stairs.py; python/src/saengine/design/stairs.py | 8 | Textbook stair |
| Deep beams / strut-and-tie / corbels | – | – | – | – | ? | Built, untested (only the code equations are tested) | python/src/saengine/design/stm_model.py, deep_beams.py, corbels.py; python/tests/test_design_stm_model.py | 8 | ACI SP-208 strut-and-tie example |
| Lintels | – | – | – | – | – | Verified (DX3) | python/src/saengine/verification/cases/beta.py | 8 | Hand calculation |
| Fire resistance by member size | – | – | – | – | ? | Built, untested | python/src/saengine/design/fire_resistance.py | 8 | Code table |
| Development and lap lengths, cover | – | – | add-on | – | ✓ | Built, untested | python/src/saengine/design/bar_rules.py, python/src/saengine/design/development_factors.py | 8 | Hand calculation |

### 5. Steel, composite and other materials

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Steel compression | ✓ | ✓ | ✓ | – | ✓ | Verified (DT1, DT3) | python/src/saengine/verification/cases/steel.py | 8 | AISC design-example style |
| Steel flexure / lateral-torsional buckling | ✓ | ✓ | ✓ | – | ✓ | Verified (DT2) | python/src/saengine/verification/cases/steel.py | 8 | Same |
| Beam-column interaction | ✓ | ✓ | ✓ | – | ✓ | Verified (DT4) | python/src/saengine/verification/cases/steel.py | 8 | Same |
| Steel seismic systems (moment and braced frames) | ✓ | ✓ | ? | – | ? | Built, untested | python/src/saengine/design/steel/seismic.py, python/src/saengine/design/steel/seismic_braced.py | 8 | AISC seismic design manual-style example |
| Simple shear and bracing connections | ✓ | ? | add-on | – | ✓ | Verified (block shear by hand, Whitmore) | python/tests/test_design_steel_connections.py; python/src/saengine/design/steel_connections.py | 8 | AISC manual-style example |
| Moment end-plate connections | ? | ? | add-on | – | ✓ | Missing (planned as `fem.endPlateMoment`) | workbench/src/vs/workbench/contrib/saengineFem/browser/femPlannedFeatures.ts | 8 | AISC DG4-style |
| Base plates | ? | ? | add-on | – | ✓ | Partial. Anchors and concrete bearing are built; plate thickness is planned | python/src/saengine/design/steel_connections.py (check_base_plate), python/src/saengine/design/anchors.py | 8 | AISC DG1-style |
| Connection FE check (CBFEM) | add-on | add-on | add-on | – | add-on | Built, untested | python/src/saengine/design/connection_fe.py | 8 | Component-method comparison |
| Composite beams | ✓ | ? | ? | – | ✓ | Built, untested (code equations only) | python/src/saengine/design/steel/composite.py; python/tests/test_design_composite.py | 8 | Design-guide composite beam |
| Composite columns | ✓ | – | – | – | ? | Built, untested | python/src/saengine/design/steel/composite.py | 8 | Same |
| Composite deck slabs | ✓ | – | – | – | ? | Built, untested | python/src/saengine/design/composite_slab.py; python/tests/test_design_composite_p8.py | 8 | Deck manufacturer / SDI-style example |
| Cold-formed steel | ✓ | ✓ | ✓ | – | ✓ | Partial. Lipped C/Z effective section only; purlins and girts planned | python/src/saengine/design/steel/cold_formed.py | 8 | AISI-style example |
| Steel joists | ✓ | – | – | – | – | Built, untested | python/src/saengine/design/steel_joists.py | 8 | SJI-style example |
| Aluminium | ✓ | ✓ | ✓ | – | ✓ | Partial. EN 1999 only; Aluminum Design Manual (US) planned | python/src/saengine/design/aluminium.py | 8 | Design-manual example |
| Post-tensioned slabs | ✓ | ? | – | ✓ | ? | Partial. Losses, load balancing and hyperstatic moments built; automatic tendon layout and time-step losses planned | python/src/saengine/design/prestress.py; python/tests/test_design_prestress.py | 8 | PTI-style slab example |
| Masonry | – | – | ? | – | ? | Verified (DY1, DY2) | python/src/saengine/verification/cases/masonry.py | 8 | Textbook |
| Timber | – | ? | ✓ | – | ✓ | Built, untested (only table values are tested) | python/src/saengine/design/timber/; python/tests/test_design_timber.py | 8 | Textbook |
| Precast | – | – | – | – | ? | Built, untested | python/src/saengine/design/precast.py; python/tests/test_precast.py | 8 | PCI handbook-style example |

### 6. Foundations and geotechnics

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Isolated footings | – | – | add-on | ✓ | ✓ | Verified (D5) | python/src/saengine/verification/cases/design.py; python/tests/test_substructure_shallow.py | 9 | Textbook |
| Combined footings | – | – | add-on | ✓ | ? | Verified (DS2) | python/src/saengine/verification/cases/substructure.py | 9 | Textbook |
| Strip / wall footings | – | – | add-on | ✓ | ✓ | Verified (DS1) | python/src/saengine/verification/cases/substructure.py | 9 | Textbook |
| Tie / strap beams | – | – | ? | ✓ | ? | Verified (DS3) | python/src/saengine/verification/cases/substructure.py | 9 | Hand calculation |
| Footing sizing assistant | – | – | add-on | – | ✓ | Built, untested | python/src/saengine/substructure/sizing.py | 9 | Hand sizing |
| Mat / raft on springs | – | – | add-on | ✓ | ✓ | Verified (DP4) | python/src/saengine/verification/cases/substructure_deep.py; python/src/saengine/substructure/raft.py | 9 | Westergaard; q/ks |
| Pile caps | – | – | add-on | ? | ✓ | Verified (DP3) | python/src/saengine/verification/cases/substructure_deep.py | 9 | Textbook four-pile cap |
| Pile axial capacity from soil | – | – | ? | – | ? | Verified (DP1, DP2, DP5) | python/src/saengine/verification/cases/substructure_deep.py; python/tests/test_pile_static.py | 9 | Textbook α/β method |
| Pile and pile-group settlement | – | – | – | – | ? | Verified (DP6) | python/src/saengine/verification/cases/substructure_deep.py | 9 | Vesic / textbook |
| Lateral pile response (Broms, p-y, head fixity) | – | – | ? | – | ? | Built, untested | python/src/saengine/substructure/pile_lateral_soil.py, pilehead.py; python/tests/test_substructure_pilehead.py | 9 | Broms chart example; published p-y case |
| Pile structural design and detailing | – | – | add-on | – | ? | Built, untested | python/src/saengine/substructure/pile_detailing.py, python/src/saengine/substructure/precast.py | 9 | Hand calculation |
| Retaining / basement walls | – | – | ? | – | ? | Built, untested | python/src/saengine/substructure/retaining_walls.py | 9 | Textbook cantilever wall |
| Slab on grade | – | – | ? | ? | ? | Built, untested | python/src/saengine/substructure/ground_slab.py | 9 | ACI 360 / TR34-style |
| Machine foundations | – | – | add-on | – | – | Built, untested | python/src/saengine/substructure/machine.py; python/tests/test_substructure_machine.py | 9 | Textbook block foundation |
| Bearing capacity and settlement from the soil report | – | – | ? | – | ? | Verified (D7, D8, D11) | python/src/saengine/verification/cases/soil.py; python/src/saengine/soil/bearing.py, python/src/saengine/soil/settlement.py | 1 | Vesic, Schmertmann, Meyerhof |
| Site class and SPT corrections | – | – | – | – | – | Verified (D6, D10) | python/src/saengine/verification/cases/soil.py | 1 | Hand calculation |
| Liquefaction | – | – | – | – | – | Verified (D9, D12) | python/src/saengine/verification/cases/soil.py; python/src/saengine/soil/liquefaction.py | 1 | Idriss–Boulanger example |
| Excavation support / embedded walls | – | – | – | – | – | Built, untested | python/src/saengine/substructure/excavation_support.py, python/src/saengine/substructure/embedded_wall.py | 9 | Free-earth-support textbook example |
| Slope stability / geotechnical FE | – | – | – | – | – | Built, untested | python/src/saengine/substructure/slope_stability.py, python/src/saengine/substructure/geotech_fe.py | 9 | ACADS-style slope benchmark |
| Water tanks (flotation, weight) | – | – | – | – | ? | Verified (DK1, DK3; wall AK1) | python/src/saengine/verification/cases/tanks.py | 9 | Hand calculation |

### 7. Output

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Storey drift tables and limits | ✓ | ? | ✓ | – | ✓ | Verified (DQ1) | python/src/saengine/verification/cases/rs_design.py; python/tests/test_serviceability.py; python/src/saengine/fem/seismic_design.py | 8 | Hand calculation |
| Storey shear and overturning | ✓ | ? | ✓ | – | ✓ | Verified (by hand) | python/tests/test_fem_story_response.py | 8 | Hand calculation |
| Irregularity checks | ? | ? | ? | – | ? | Verified (unit tests with hand ratios) | python/tests/test_fem_irregularity.py; python/src/saengine/fem/irregularity.py | 8 | Code-commentary example |
| Modal participation / mass ratios | ✓ | ✓ | ✓ | ? | ✓ | Built, untested (cross-check only) | python/src/saengine/fem/story_response.py | 8 | Exact 3-DOF shear building |
| Deflected shapes, force diagrams, contours | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/fem/display.py; workbench/src/vs/workbench/contrib/saengineFem/browser/femResultsView.ts | 8 | – |
| Member detail (frame detail, P-M chart) | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/fem/member_detail.py | 8 | Hand calculation |
| Column load takedown | ? | ? | ? | – | ? | Built, untested | python/src/saengine/design/takedown.py | 8 | Hand takedown |
| Result tables and Excel export | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/fem/result_tables.py, python/src/saengine/fem/table_export.py | 8 | – |
| Design utilisation display | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/design/check.py; workbench/src/vs/workbench/contrib/saengineFem/browser/femDesign.ts | 8 | – |
| Calculation report (PDF / Word) | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/report/build.py, python/src/saengine/report/word.py; python/tests/test_report.py | 11 | – |
| Verification manual | ✓ | ✓ | ✓ | ✓ | ✓ | Partial. The pack exists; A9 fails; the results table is dated 0.0.45 | python/src/saengine/verification/; docs/verification/README.md | 8 | – |
| Structural drawings (plans, schedules, details) | add-on | – | add-on | ✓ | ✓ | Built, untested | python/src/saengine/drawings/sheets/, python/src/saengine/drawings/detailing.py; python/tests/test_drawings_*.py | 11 | Hand-detailed beam sheet |
| Bar bending schedules | add-on | – | add-on | ? | ✓ | Verified (shapes and lengths by hand) | python/tests/test_drawings_bbs.py; python/src/saengine/drawings/bbs.py | 11 | BS 8666-style schedule |
| 3D rebar cages and congestion | add-on | – | – | – | ? | Built, untested | python/src/saengine/drawings/cages.py, python/src/saengine/library/ifc_rebar.py | 11 | – |
| BOQ (concrete, steel, formwork, cement, sand) | ✓ | ✓ | ✓ | ? | ✓ | Verified (mixes and quantities by hand) | python/tests/test_boq_materials.py, python/tests/test_boq.py; python/src/saengine/boq/quantities.py | 10 | Hand takeoff of one bay |
| Costing and embodied carbon | ? | ? | – | – | ? | Built, untested | python/src/saengine/boq/costing.py, python/src/saengine/boq/workbook.py | 10 | Hand calculation |
| 4D construction schedule | – | – | add-on | – | – | Built, untested | python/src/saengine/boq/construction_schedule.py | 10 | – |

### 8. Interoperability

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| ETABS .e2k import | ✓ | ? | ? | ? | – | Built; round trip tested | python/src/saengine/importers/etabs.py; python/tests/test_import_etabs*.py; python/tests/test_exchange_round_trip.py (A3, AP3, DQ1: same counts, coordinates, sections, loads; member forces within 0.1 %); python/tests/test_exchange_public_examples.py | 11 | Open the export in a licensed ETABS |
| ETABS .e2k export | ✓ | – | – | – | – | Built; round trip tested | python/src/saengine/exporters/etabs.py; python/tests/test_export_etabs.py; python/tests/test_exchange_round_trip.py (A3, AP3, DQ1: same counts, coordinates, sections, loads; member forces within 0.1 %) | 11 | Same |
| SAP2000 .s2k import / export | ✓ | ✓ | ? | ? | ? | Built; round trip tested | python/src/saengine/importers/sap2000.py, python/src/saengine/exporters/s2k.py; python/tests/test_exchange_round_trip.py (A3, AP3, DQ1: same counts, coordinates, sections, loads; member forces within 0.1 %) | 11 | Open the export in a licensed SAP2000 |
| STAAD .std import / export | ✓ | ✓ | ✓ | – | ? | Built; round trip tested | python/src/saengine/importers/staad.py, python/src/saengine/exporters/std.py; python/tests/test_exchange_round_trip.py (A3, AP3, DQ1: same counts, coordinates, sections, loads; member forces within 0.1 %) | 11 | Open the export in a licensed STAAD.Pro |
| SAFE .f2k import / export | ✓ | ? | – | ✓ | – | Built; round trip tested (#305); frame/wall tables unverified | python/src/saengine/importers/safe.py, python/src/saengine/exporters/f2k.py; python/tests/test_exchange_f2k.py; python/tests/test_exchange_round_trip.py (A3, AP3, DQ1: same counts, coordinates, sections, loads; member forces within 0.1 %) | 11 | Open the export in a licensed SAFE |
| Robot .rtd / .str | – | – | – | – | ✓ | Missing. Searched rtd, robot | – | 11 | – |
| IFC export / import, including rebar | ✓ | ✓ | ? | ? | ✓ | Built, untested | python/src/saengine/library/ifc.py, python/src/saengine/library/architecture_ifc.py, python/src/saengine/library/ifc_rebar.py; python/tests/test_ifc.py | 6 | IFC validation of a sample |
| DXF / DWG / PDF import as underlay | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/library/architecture_dxf.py, python/src/saengine/library/dwg.py, python/src/saengine/library/pdf_underlay.py; workbench/src/vs/workbench/contrib/saengineCad/browser/floorPlanUnderlay.ts | 5 | – |
| DXF export of plans and drawings | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/library/dxf_audit.py, python/src/saengine/drawings/ | 11 | – |
| Excel model edit, in and out | ✓ | ✓ | ? | ✓ | ✓ | Built, untested | python/src/saengine/library/workbook.py | 5 | – |
| SAF | ? | ? | ? | ? | ? | Built, untested | python/src/saengine/exporters/saf.py | 11 | – |
| CIS/2, SDNF | ? | ? | ? | – | ? | Built, untested | python/src/saengine/exporters/cis2.py, python/src/saengine/exporters/sdnf.py; python/tests/test_exchange_exports.py | 11 | – |
| Revit link | add-on | add-on | add-on | add-on | ✓ | Partial. Writes and reads the exchange file; MIT Revit 2027 add-in (`revit-addin/`) built without live Revit run | python/src/saengine/exporters/revit_link.py; python/tests/test_revit_link.py; revit-addin/; docs/revit-link.md | 11 | Round trip through the add-in in Revit |
| Point-cloud underlay | – | – | – | – | – | Built, untested | python/src/saengine/library/point_cloud.py | 5 | – |
| Web viewer | – | – | add-on | – | – | Built, untested | python/src/saengine/exporters/web_viewer.py | 11 | – |
| API / SDK / CLI | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/api.py, python/src/saengine/rpc/, python/src/saengine/cli/, docs/sdk/; python/tests/test_sdk.py, python/tests/test_cli.py | Shell | – |
| AGS / DIGGS soil data, GIS | – | – | – | – | – | Built, untested | python/src/saengine/soil/ags.py, python/src/saengine/soil/diggs.py, python/src/saengine/gis/ | 1 | – |

### 9. Workflow

| Feature | ETABS | SAP2000 | STAAD.Pro | SAFE | Robot | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|---|---|
| Units (SI / US) | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested (unit tests) | python/src/saengine/units.py; python/tests/test_units.py | Shell | Exact conversion factors |
| Version history (git) | – | – | – | – | – | Built, untested | python/src/saengine/project/versions.py; python/tests/test_project_versions.py | Shell | – |
| Semantic diff of versions | – | – | – | – | – | Built, untested | python/src/saengine/project/diff.py | Shell | – |
| Shared projects, part locks, presence | – | – | add-on | – | add-on | Built, untested | python/src/saengine/project/share.py; docs/collaboration.md | Shell | – |
| Live co-editing | – | – | ? | – | – | Built, untested | workbench/src/vs/workbench/contrib/saengineCad/browser/floorPlanPresence.ts | Shell | – |
| Scripting inside the app | ✓ | ✓ | ✓ | ✓ | ✓ | Partial. In-app Python scripts work for special structures only; buildings go through the SDK | python/src/saengine/library/script.py | 5/Shell | – |
| Visual programming | – | – | ? | – | add-on | Built, untested | python/src/saengine/automation/graph.py | Shell | – |
| Design studies / section optimisation | ✓ | ✓ | ✓ | – | ✓ | Built, untested | python/src/saengine/automation/studies.py, python/src/saengine/design/cost_optimisation.py, python/src/saengine/design/steel_proposal.py | 8 | – |
| Several design codes (code packs) | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested (pack values unit-tested) | python/src/saengine/codes/; python/tests/test_codes_*.py | Code packs | – |
| Single-file project archive | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/project/archive.py; python/tests/test_project_archive.py | Shell | – |
| Model checks / input guardrails | ✓ | ✓ | ✓ | ✓ | ✓ | Built, untested | python/src/saengine/library/guardrails.py, python/src/saengine/pipeline/validate.py, python/src/saengine/fem/results_check.py | Shell | – |

### Summary

**Counts (190 rows).**

| Status | Rows |
|---|---|
| Verified | 76 |
| Built, untested | 93 |
| Partial | 14 |
| Missing | 7 |

The 7 Missing rows are:
- non-orthogonal grids
- user point springs
- Ritz vectors
- cracked nonlinear slab analysis
- moment end-plate connections
- SAFE .f2k exchange
- Robot exchange

**The 15 most important gaps for a practising RC building engineer in Bangladesh, in order:**
1. ~~**Non-orthogonal grids are missing.**~~ Built in #300 (rotated, radial and angled grid systems), including the New Project wizard's rotated and radial grids.
2. **Load cases cannot be defined by the user.** The case set is fixed, member loads are limited to D/SD/L/Lr, and joint loads are restricted.
3. **Long-term cracked deflection of FE slabs is built but unverified (#302).** It is checked by hand cases only; it needs a published flat-plate benchmark. SAFE does this.
4. **P-Delta is unverified** against a closed-form amplification.
5. **Response spectrum and modal checks cover only single-mass models.** There is no multi-storey CQC or modal-mass benchmark, and Ritz vectors are missing.
6. **Rigid and semi-rigid diaphragms are unverified.** This includes the torsional response.
7. **Pier and spandrel forces from wall shells are unverified.** Wall design is verified only at section level.
8. **General member end releases and user point springs are missing.**
9. **Strong-column/weak-beam and capacity-shear design are unverified.**
10. **Auto-meshing and FE slab design are unverified on a whole slab.** The only evidence is a cross-check against other solvers.
11. **ETABS/SAP/STAAD exchange is proved only by SAEngine's own round trips (#305).** The exports are not yet opened in the target programs.
12. **SAFE .f2k exchange is built (#305), but its frame and wall tables are unverified.** Public SAFE samples hold no frame connectivity tables.
13. **Retaining and basement wall design is unverified.** Only the earth-pressure coefficients are tested.
14. **Drawings and schedules are not checked against a hand-detailed sheet.** The only check is the bar bending schedule unit tests.
15. **Crack widths of FE slabs are built but unverified (#302).** They are checked by hand cases only; water-tank walls are covered by DK2.

**The 10 cheapest high-value verifications to do first:**
1. **P-Delta:** cantilever column under axial and lateral load, against the closed-form amplification.
2. **3-storey shear building:** periods, modal mass and CQC response spectrum against a textbook (Chopra-type).
3. **Rigid diaphragm:** one-storey building with eccentric stiffness, centre of rigidity and storey twist by hand.
4. **Wall shell:** cantilever wall under lateral load; pier P, V and M against statics.
5. **Strong-column/weak-beam ratio and capacity shear:** one joint, by hand.
6. **Cantilever retaining wall:** stability and stem design against a textbook example.
7. **e2k round trip:** export the verified cases A3, AP3 and DQ1, re-import them, and check identical results.
8. **Fixed beam with support settlement:** 6EIΔ/L², a quick test of `fem/settlement.py`.
9. **Semi-rigid diaphragm:** slab spanning as a deep beam between two walls.
10. **One-bay BOQ and drawing schedule** against a hand takeoff and hand-detailed beam.

**Caveats.**
- The commercial-program columns come from general public knowledge, with "?" wherever unsure.
- Rows marked "Built, untested" often do have unit tests, but those tests check code-table values or round trips, not an independent hand calculation or published result.

## Part 2: BIM, drafting and MEP (Revit, AutoCAD, MEP tools)

**How statuses were assigned.**
- **Verified**: a test or verification case checks the feature against a hand calculation or a published value. For exchange formats, a round-trip or sample-file test also counts.
- **Built, untested**: the code exists. It may have unit tests, but none of them is an independent benchmark.
- **Nothing was run** for this document. "Verified" means the check exists in the repository, not that it passes today: since 31 October 2026 features have been merged without running the tests on every commit, with a full test pass planned before release.

**Program columns.** These come from public knowledge only. "add-on" means a separate product, toolset or plugin.

Verification case IDs (such as DM1) are in the `Case(...)` entries of the files under `python/src/saengine/verification/cases/`.

### A. BIM modelling

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Levels and grids (rectangular, skewed, cylindrical) | ✓ | add-on | – | Built, untested | python/src/saengine/library/floorplan.py, python/src/saengine/library/structure.py (cylindrical); python/tests/test_floorplan.py, python/tests/test_structure.py (unit) | 5 | Round trip: model storeys and grids, export IFC, reopen in an independent viewer, compare elevations and spacings |
| Structural members on the grid (columns, beams, walls, slabs, footings) | ✓ | add-on | – | Built, untested | workbench/src/vs/workbench/contrib/saengineCad/browser/floorPlanEdits.ts (+ test), python/src/saengine/library/bim.py; python/tests/test_bim.py | 5 | Model a textbook frame; compare member count and lengths in the IFC with a hand list |
| Architectural walls, layered types, location line | ✓ | add-on | – | Verified | python/src/saengine/library/architecture.py (WallType); python/tests/test_architecture_extras.py::test_type_weights_by_hand; python/tests/test_architecture_loads.py::test_wall_on_a_6_m_beam_with_a_door_by_hand | 5 | Hand calculation of wall weight per m and the load on the beam |
| Stacked walls, sweeps and reveals, wall-join editing | ✓ | add-on | – | Out of scope (decision) | architecture.py docstring ("no stacked walls"); owner decision (architecture layer plan, avoid list) | 5 | – |
| Doors and windows hosted in walls | ✓ | add-on | – | Verified (quantities) | architecture.py Door/Window; python/tests/test_architecture_loads.py::test_boq_brickwork_plaster_finishes_and_doors_by_hand; python/tests/test_architecture.py::test_ifc_export_has_walls_openings_spaces_and_coverings | 5 | Hand deduction of openings from brickwork; IFC opening/void check |
| Curtain walls | ✓ | add-on | – | Verified | Grid rules (fixed distance/number, max spacing), panel types with per-panel overrides, mullion types, beam line loads and IFC (`IfcCurtainWall`, `IfcPlate`, `IfcMember`). python/src/saengine/library/architecture.py; python/src/saengine/library/architecture_ifc.py; python/tests/test_architecture_extras.py::test_curtain_wall_and_railing_on_a_beam_by_hand, ::test_curtain_wall_grid_panels_mullions_and_beam_load_by_hand, ::test_ifc_export_r1_roof_ceiling_curtain_wall | 5 | Hand calculation of the line load on the supporting beam |
| Floors and slabs (polygon slabs, openings) | ✓ | add-on | – | Built, untested | floorPlanEdits.ts (polygonSlab); bim additions slabOpenings; python/tests/test_ifc.py::test_additions_cut_hosts_and_add_stairs_and_inclined_members | 5 | Hand slab area and volume less openings |
| Roofs | ✓ | add-on | – | Verified | Footprint roofs with per-edge slopes (hip, gable, shed, mansard, flat with drainage slope, overhangs) via straight skeleton, loads, BOQ and `IfcRoof`/`IfcSlab` ROOF parts. python/src/saengine/library/roof_geometry.py; python/tests/test_architecture_extras.py::test_hip_roof_10x6_at_30_deg_by_hand, ::test_gable_roof_10x6_at_30_deg_by_hand, ::test_l_and_t_shaped_hip_roofs_by_hand, ::test_shed_mansard_drainage_and_overhang_roofs_by_hand | 5 | Hand load of the roof covering per m² |
| Ceilings | ✓ | add-on | – | Verified | Ceiling elements per room or outline (gypsum, grid tiles, height above level, openings), `ceiling_void` and MEP void checks, BOQ and `IfcCovering` CEILING. python/src/saengine/library/architecture.py; python/src/saengine/mep/rooms.py (`check_ceiling_voids`); python/tests/test_architecture_extras.py::test_ceiling_void_and_boq_by_hand, ::test_ifc_export_r1_roof_ceiling_curtain_wall | 5 | Hand ceiling void and net area less openings |
| Stairs | ✓ | add-on | – | Built, untested | bim additions stairs (IfcStair, waist slab); python/tests/test_design_stairs.py; python/src/saengine/drawings/sheets/details.py | 6 | Published worked example of waist-slab stair design |
| Ramps and railings | ✓ | add-on | – | Verified | Straight ramps only. python/tests/test_architecture_extras.py::test_ramp_fill_finish_and_rooms_by_hand, ::test_curtain_wall_and_railing_on_a_beam_by_hand | 5 | Hand calculation of ramp fill and railing loads |
| Rooms and spaces (area, finishes, occupancy), room separators | ✓ | add-on | – | Verified | Rooms by polygonize; gross and net areas asserted by hand in python/tests/test_architecture_extras.py; python/tests/test_architecture.py::test_separator_closes_an_open_plan | 5 | Hand room areas net of wall thickness |
| Area statement, FAR, ground coverage, setbacks | ✓ (area plans) | – | – | Built, untested | python/src/saengine/gis/planning.py; python/tests/test_gis_planning.py, python/tests/test_gis_planning_code.py | 1 | Hand FAR and ground coverage for a sample plot against the authority's table |
| Furniture, casework, generic components | ✓ | add-on | – | Verified | python/src/saengine/library/components.py (ComponentType, starter library, host room, schedule, IFC); python/src/saengine/boq/architecture.py; python/tests/test_architecture_r2.py::test_place_bed_in_room_detects_host_and_counts_in_boq, ::test_schedule_three_chairs_and_one_table_across_two_rooms | 5 | Bed and chairs/table counts per room and IFC export |
| Types library (object types; wall, door, window, finish, roof, railing types) | ✓ | add-on | – | Verified | python/src/saengine/library/objects.py, architecture.py, types_library.py (TypesLibrary, parametric DoorType/WindowType); workbench/src/vs/workbench/contrib/saengineCad/browser/architectureTypesPanel.ts; python/tests/test_architecture_r2.py::test_types_library_crud_rename_delete_refusal_and_round_trip | 4 | Export/import round trip and delete refusal when used |
| Family editor | ✓ | – | – | Out of scope (decision) | architecture.py docstring ("no family editor"); owner decision (architecture layer plan) | 4 | – |
| Conceptual massing, in-place elements | ✓ | add-on | – | Verified | python/src/saengine/library/massing.py (ConceptualMass, InPlaceElement, prismoid loft volume, FAR check, IFC proxy); python/tests/test_architecture_r2.py::test_mass_extrusion_floors_gfa_far_and_create_floors, ::test_loft_volume_by_hand_prismoid_formula | 6 | 10-storey extrusion GFA/FAR and prismoid loft volume by hand |
| Topography surface (DEM, XYZ, DXF contours as a TIN) | ✓ | add-on | – | Built, untested | python/src/saengine/gis/terrain.py; python/tests/test_l11_office_tools.py::test_xyz_reader_skips_headers | 1 | Compare TIN spot heights with survey points |
| Phases (existing, new, demolished, temporary), bill by phase | ✓ | – | – | Built, untested | python/src/saengine/project/phasing.py; python/tests/test_l11_office_tools.py::test_phase_status_and_bill (unit); docs/engineering-decisions.md "Phasing and design options" | 6 | Hand split of a two-phase toy bill |
| Design options | ✓ | – | – | Built, untested | phasing.compare_options over saved versions (python/src/saengine/project/versions.py) | 6 | Two versions with a known concrete difference; check the comparison |
| Worksets | ✓ | – | – | Out of scope (decision) | architecture.py docstring; part locks replace them (docs/collaboration.md) | Shell | – |
| Groups and typical floors (copy to storeys) | ✓ | ✓ (blocks) | – | Built, untested | workbench/src/vs/workbench/contrib/saengineCad/browser/floorPlanTypical.ts (+ workbench/src/vs/workbench/contrib/saengineCad/test/browser/floorPlanTypical.test.ts) | 5 | – |
| Point clouds (LAS, LAZ, E57, XYZ, PTS), snap and trace | ✓ | ✓ | – | Verified (round trip) | python/src/saengine/library/point_cloud.py; python/tests/test_point_cloud.py::test_las_round_trip | 5 | Public LAS sample: point count and bounds match the header |
| 3D view: section box, measure, hide or isolate | ✓ | ✓ | – | Built, untested | packages/fem-viewer/src/section.ts, sectionMath.ts, measure.ts, measureMath.ts, visibilityMath.ts, building.ts, index.ts (+ test/*.test.mjs); workbench/src/vs/workbench/contrib/saengineFem/browser/viewerTools.ts, femModelEditor.ts; workbench/src/vs/workbench/contrib/saengineLibrary/browser/buildingEditor.ts | 6 | – |
| Rendering and walkthrough | ✓ | ✓ | – | Built, untested | docs/manual/06-bim.md (Studies); packages/fem-viewer | 6 | – |
| Sun and shadow study | ✓ | ✓ | – | Verified | python/src/saengine/environment/solar.py; python/tests/test_l11_office_tools.py::test_sun_at_equinox_noon | 6 | Published solar position (NOAA) for a date and site |
| Daylight factor | add-on | – | ✓ | Verified (formula) | python/src/saengine/environment/daylight.py; python/tests/test_l11_office_tools.py::test_daylight_factor_formula | 6 | Hand average daylight factor (BR 209 form) for one room |

### B. Structural BIM

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Analytical model derived from the physical model (rigid zones, diaphragms) | ✓ | – | – | Verified | python/src/saengine/fem/derive.py; python/src/saengine/verification/cases/analysis.py (A1–A6), python/src/saengine/verification/cases/parity.py (AP3 rigid end zones) | 8 | Closed-form beam, frame and modal cases (already present) |
| Loads and load combinations on the model | ✓ | – | – | Verified | python/src/saengine/verification/cases/correctness.py (AN1 slab load to beam, AN2 pattern live load, AN3 wind torsion); python/src/saengine/verification/cases/parity.py (AP1, AP2, AP4) | 2 | Hand load take-down on a published frame |
| 3D reinforcement cages, rebar in IFC | ✓ | – | – | Built, untested | python/src/saengine/drawings/cages.py, python/src/saengine/library/ifc_rebar.py; python/tests/test_rebar_cages.py (unit) | 11 | Count and length of IfcReinforcingBar elements against the BBS |
| Rebar generated from design results | add-on | – | – | Built, untested | python/src/saengine/drawings/detailing.py; python/tests/test_drawings_sheets.py::test_beam_elevation_bar_lengths_match_the_detailing | 11 | Hand detailing of one beam (laps, curtailment) |
| Bar bending schedule | ✓ (rebar schedules) | – | – | Verified | python/src/saengine/drawings/bbs.py; python/tests/test_drawings_bbs.py (expected values worked by hand), python/tests/test_bbs_standards.py | 11 | BS 8666-type worked shape-code lengths |
| Bar congestion and clashes at joints | add-on | – | – | Built, untested | cages.py congestion check; python/tests/test_joint_bottom_layers.py | 11 | Hand clear-spacing check of one joint |
| Steel connection design (fin plate, block shear, welds, base plates) | add-on | – | – | Verified | python/src/saengine/design/steel_connections.py; python/tests/test_design_steel_connections.py (against hand calculations), python/tests/test_design_steel_connections2.py | 8 | Published connection design-guide example |
| Steel connections modelled in 3D and IFC (plates, bolts) | ✓ | – | – | Built, untested | python/src/saengine/fabrication/model.py; exported via python/src/saengine/library/ifc_fabrication.py (IfcElementAssembly, IfcPlate, IfcMechanicalFastener/IfcFastener, IfcOpeningElement voids, marks); python/tests/test_ifc_r9.py::test_fin_plate_connection_exports_plate_bolts_and_openings | 11 | Fabrication drawings / shop review |
| NC files (DSTV) and rebar BVBS | add-on | – | – | Verified | python/src/saengine/fabrication/dstv.py, bvbs.py; python/tests/test_fabrication_l10.py::test_checksum_of_the_guideline_examples | 11 | BVBS guideline checksum examples (already present) |
| Steel shop drawings, assembly and part marks | add-on | – | – | Built, untested | python/src/saengine/drawings/sheets/shop.py; python/tests/test_walk4_fabrication.py | 11 | – |
| Precast piece and post-tensioning sheets | add-on | – | – | Built, untested | python/src/saengine/drawings/sheets/precast.py, pt.py; python/tests/test_precast.py, python/tests/test_drawings_pt.py | 11 | Hand tendon elongation for one tendon |
| Framing plans, column schedule, beam elevations | ✓ | add-on | – | Built, untested | python/src/saengine/drawings/sheets/plans.py, schedules.py; python/tests/test_drawings_sheets.py | 11 | – |

### C. Documentation

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Sheets with frame and title block (A1 to A3) | ✓ | ✓ | – | Built, untested | python/src/saengine/drawings/sheets/layout.py; python/tests/test_drawings_sheets.py::test_sheet_size_frame_and_title_block | 11 | Plot in AutoCAD or LibreCAD with scripts/drawings_qa |
| Automatic structural drawing set | add-on | – | – | Built, untested | python/src/saengine/drawings/sheets/build.py; docs/manual/11-exports.md | 11 | – |
| Architectural plans, elevations and sections | ✓ | add-on | – | Built, untested | python/src/saengine/drawings/sheets/architecture.py; python/tests/test_drawings_architecture.py | 11 | – |
| MEP plans, coordination plan, MEP schedules | ✓ | add-on | ✓ | Built, untested | python/src/saengine/drawings/sheets/mep.py; python/tests/test_drawings_mep.py | 11 | – |
| User-placed views, view templates, visibility and graphics overrides | ✓ | ✓ (layers) | – | Out of scope (decision) | Owner decision (architecture layer plan, avoid list: "user view templates"); sheets are generated | 11 | – |
| Callouts, dependent views, matchlines, scope boxes | ✓ | ✓ | – | Verified | python/src/saengine/drawings/sheets/documentation.py; python/src/saengine/drawings/sheets/plans.py; python/src/saengine/drawings/sheets/build.py; python/tests/test_drawings_documentation.py | 11 | Two 20 x 20 m dependent plans from one 40 x 20 m plan; reciprocal matchline references |
| Tags, marks, general notes | ✓ | ✓ | – | Built, untested | python/src/saengine/drawings/automation.py (auto_tag); plans.py marks | 11 | – |
| Dimensions (grid chains, overall) | ✓ | ✓ | – | Built, untested | plans.py; automation.auto_dimension; python/tests/test_drawings_sheets.py::test_grid_dimensions_count | 11 | – |
| Leaders, keynotes, legends | ✓ | ✓ | – | Verified | python/src/saengine/drawings/automation.py; python/src/saengine/drawings/sheets/keynotes.py, documentation.py; python/src/saengine/library/keynotes.json; python/tests/test_drawings_documentation.py | 11 | Per-sheet legend includes only element and material keynote keys actually used |
| Schedules | ✓ | ✓ (tables, data extraction) | ✓ | Verified | python/src/saengine/drawings/sheets/schedule_builder.py; fixed schedules unchanged; python/tests/test_drawings_documentation.py | 11 | Filter, sort, level groups, itemize/count and checked totals against hand counts |
| Revision clouds, revision table, issues, drawing register | ✓ | ✓ | – | Built, untested | python/src/saengine/drawings/sheets/revisions.py; python/tests/test_drawing_revisions.py | 11 | – |
| Engineer's CAD edits kept when sheets are regenerated | – | – | – | Built, untested | revisions.py; python/tests/test_drawing_revisions.py::test_user_edits_are_carried_to_the_new_sheet | 11 | – |
| Layer, linetype, lineweight and text standards (office standard) | ✓ | ✓ | – | Verified | docs/drawings-layers.md, python/src/saengine/drawings/sheets/standards.py; python/tests/test_drawings_cad.py (ISO plot text heights, linetype paper lengths) | 11 | ISO plot text heights and linetype lengths (already present) |
| Hatches on sheets | ✓ | ✓ | – | Built, untested | layout.py add_hatch; python/tests/test_drawings_cad.py::test_hatch_patterns_plot_at_their_paper_size | 11 | – |
| PDF set and PNG previews | ✓ | ✓ | – | Built, untested | python/src/saengine/drawings/sheets/render.py (Typst); python/tests/test_drawings_sheets.py::test_drawing_set_sheets_dxf_round_trip_and_pdf | 11 | – |
| DWG export of sheets | ✓ | ✓ | – | Built, untested | python/src/saengine/library/dwg.py write_dwg (LibreDWG dxf2dwg); only python/tests/test_drawing_revisions.py::test_write_dwg_without_the_writer | 11 | Round trip: write DWG, read back, compare entity counts per layer |
| Drawing automation (auto-dimension, auto-tag, auto-arrange, label placement) | add-on | add-on | – | Built, untested | python/src/saengine/drawings/automation.py; python/tests/test_drawings_sheets.py::test_labels_keep_off_lines_and_leaders_off_texts | 11 | – |

### D. CAD drafting

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Drawing: line, polyline, arc and circle (all options), ellipse, spline, rectangle, polygon, donut, xline, ray, multiline, revision cloud, wipeout | ✓ (detail lines) | ✓ | – | Verified (geometry) | packages/cad-editor/src/drawCommands.ts, drawGeometry.ts; test/draw-geometry.test.mjs (hand-computed: 3P/TTR/TTT circles, arc options, filleted rectangle, polygon, donut); library commands | 5 | – |
| Modify: move, copy, rotate, offset, erase, mirror, scale, stretch | ✓ | ✓ | – | Verified (geometry) | packages/cad-editor/src/commands.ts, gripGeometry.ts; test/modify-geometry*.test.mjs, test/grips.test.mjs | 5 | – |
| Trim, extend, fillet, chamfer, break, join, explode, lengthen, align | ✓ | ✓ | – | Verified (geometry) | packages/cad-editor/src/modifyGeometry.ts, modifyGeometry2.ts; test/modify-geometry.test.mjs, test/modify-geometry2.test.mjs (hand-computed). Replaces the earlier out-of-scope decision (docs/engineering-decisions.md, CAD parity) | 5 | – |
| Arrays: rectangular, polar, path; editable arrays (ARRAYEDIT) | ✓ | ✓ | – | Verified (geometry) | packages/cad-editor/src/commands.ts, pathGeometry.ts, arrayCommands.ts; test/path-array.test.mjs, test/dim-find-field.test.mjs. Copies kept as a group (no associative array object in the data model) | 5 | – |
| PEDIT, SPLINEDIT, OVERKILL | – | ✓ | – | Verified (geometry) | packages/cad-editor/src/polyEditCommands.ts, polyEditGeometry.ts; test/poly-edit.test.mjs (arc-fit on a known circle, B-spline midpoint, OVERKILL command test). PLINEGEN is not in the data model | 5 | – |
| Layers and properties: LAYER, isolate/off/freeze/lock and reverses, LAYMRG, LAYWALK, MATCHPROP, CHPROP, colour/linetype/lineweight, Properties panel for drafting | ✓ | ✓ | – | Built, untested | packages/cad-editor/src/layerCommands.ts, properties.ts, linetypes.ts (test/layers.test.mjs, DASHED acadiso values); floor plan status bar and Properties panel (floorPlanCadBar.ts, floorPlanDraftProperties.ts); status bar walked in the app 2026-11-18 | 5 | Walk: isolate a layer, MATCHPROP, edit a colour in the Properties panel, save and reopen |
| Drafting aids: object snaps (all modes and overrides), ORTHO, POLAR, OTRACK, SNAP, GRID, dynamic input | ✓ | ✓ | – | Verified (geometry) | packages/cad-editor/src/draftingAids.ts, draftingAidsGeometry.ts; test/drafting-aids.test.mjs (perpendicular, tangent, polar, ortho, grid snap); F8 and the status bar walked in the app | 5 | – |
| Selection: window, crossing, fence, polygons, All, Last, Previous, Remove/Add, Undo, QSELECT, SELECTSIMILAR, lasso, selection cycling | ✓ | ✓ | – | Built, untested | packages/cad-editor/src/selectionModes.ts, selectionGeometry.ts; test/selection-modes.test.mjs, test/lasso.test.mjs; floorPlanEditor.ts (lasso, cycling) | 5 | Walk: lasso and cycling over overlapping drafting and members |
| Grip editing: stretch, move, rotate, scale, mirror (Space or Enter cycles), polyline vertex and segment grips | ✓ | ✓ | – | Built, untested | packages/cad-editor/src/gripEdit.ts, gripGeometry.ts, spaceAsEnter.ts; test/grips.test.mjs; Space cycling walked in the app 2026-11-19 | 5 | – |
| Blocks: create, insert, write, attributes, ATTSYNC, block editor, in-place edit (REFEDIT), xrefs (attach, overlay, reload, bind), dynamic blocks (linear/stretch, flip, visibility, rotation) | ✓ (detail components, families) | ✓ | – | Built, untested | packages/cad-editor/src/blockCommands.ts, blockEditor.ts, xrefCommands.ts, dynamicBlocks.ts; test/blocks.test.mjs, test/block-editor.test.mjs (inverse transform; Discard byte-identical). Dynamic-block grips are not possible in the viewer (-DYNPROP instead) | 5 | Walk: BEDIT a block with members on the plan, save, reopen |
| Dimensions: linear, aligned, angular, arc length, radius, diameter, jogged, ordinate, baseline, continue, QDIM; DIMEDIT, DIMTEDIT, DIMOVERRIDE, DIMSPACE, DIMBREAK; dimension styles | ✓ | ✓ | – | Verified (geometry) | packages/cad-editor/src/dimensionCommands.ts, dimensionGeometry.ts, dimensionEditCommands.ts; test/dimension-commands.test.mjs, test/dimension-roundtrip.test.mjs, test/dim-find-field.test.mjs. No dimension associativity in the data model; breaks are stored but drawn unbroken | 5 | – |
| Hatch and gradient: create, edit, boundary, islands | ✓ | ✓ | – | Verified (geometry) | packages/cad-editor/src/hatchCommands.ts, hatchGeometry.ts; test/hatch-geometry.test.mjs (1000×500 loop area). Gradients are stored and round-tripped but drawn as solid fills by the viewer | 5 | – |
| Text, MText, leaders (MLEADER, QLEADER), tables, fields, FIND and replace, text/table/multileader styles; Bengali | ✓ | ✓ | – | Partial | packages/cad-editor/src/annotationCommands.ts, findCommands.ts, fieldCommands.ts, stylesAuditCommands.ts; test/annotation.test.mjs, test/dim-find-field.test.mjs, test/styles-audit.test.mjs. Bengali shaping is still incomplete | 5 | Bengali room names shaped correctly on screen and in the DXF |
| Regions, UNION/SUBTRACT/INTERSECT, MASSPROP (area, centroid, second moments, principal axes) | – | ✓ | – | Verified | packages/cad-editor/src/regionGeometry.ts; test/annotate-gaps.test.mjs (100×50 rectangle: Ixx 1,041,666.7, Iyy 4,166,666.7; L-shape centroid 41.667). Regions are tagged closed polylines (no ACIS in the data model) | 5 | – |
| Annotation symbols: TOLERANCE (feature control frames), CENTERMARK, CENTERLINE, BLEND, DRAWORDER | – | ✓ | – | Built, untested | packages/cad-editor/src/annotateGapsCommands.ts, annotationCommands.ts; test/annotate-gaps.test.mjs | 5 | – |
| Inquiry: DIST, AREA, ID, LIST, MEASUREGEOM, DIVIDE, MEASURE; UNITS; DATAEXTRACTION (table, CSV) | – | ✓ | – | Verified (geometry) | packages/cad-editor/src/inquiryCommands.ts, inquiryGeometry.ts, unitsFormat.ts, stylesAuditCommands.ts; test/inquiry-geometry.test.mjs, test/units-format.test.mjs (architectural 2'-6 1/2", surveyor's N 60d E), test/styles-audit.test.mjs | 5 | – |
| Command line, AUDIT, RECOVER, PURGE, GROUP | – | ✓ | – | Built, untested | packages/cad-editor/src/index.ts (command line), stylesAuditCommands.ts, blockCommands.ts; test/styles-audit.test.mjs; packages/cad-editor/COMMANDS.md lists every AutoCAD 2D command with its status | 5 | – |
| Underlays and xrefs (DXF, DWG, PDF vector) | ✓ | ✓ | – | Verified (sample files) | workbench/src/vs/workbench/contrib/saengineCad/browser/floorPlanUnderlay.ts (+ test); python/tests/test_dwg.py::test_underlays_may_be_dwg; python/src/saengine/library/pdf_underlay.py, python/tests/test_architect_input.py | 5 | Architect DWG and PDF placed and calibrated against a known length |
| Paper space layouts and viewports | ✓ | ✓ | – | Partial | Sheets drawn in model space at a base scale with one layout page setup (layout.py; python/tests/test_drawings_cad.py::test_layout_page_setup_plots_the_sheet). Layouts stay in 11 Drawings (owner decision 2026-11-18) | 11 | – |
| Parametric constraints: geometric (GC*, AUTOCONSTRAIN), dimensional (DC*) with parameters and expressions | ✓ | ✓ | – | Verified | packages/cad-editor/src/constraintSolver.ts, constraintModel.ts, constraintCommands.ts; test/constraints.test.mjs (rectangle d1 = 100, d2 = d1/2 → 100×50; d1 = 200 → 200×100; over-constraint refused; ids kept across solves). Shown as dimensions on a non-plotting layer (no constraint glyphs in the viewer) | 5 | – |
| DXF read | ✓ | ✓ | – | Verified | python/src/saengine/library/importers.py; python/tests/test_dxf_audit.py, python/tests/test_architecture_dxf.py::test_inspect_lists_layers_unit_and_preview | 5 | – |
| DXF write | ✓ | ✓ | – | Verified (round trip) | ezdxf; python/tests/test_drawings_sheets.py::test_drawing_set_sheets_dxf_round_trip_and_pdf; python/tests/test_dxf_audit.py; scripts/drawings_qa (AutoCAD audit harness, docs/drawings-qa.md) | 11 | – |
| DWG read (R2000–R2018) | ✓ | ✓ | – | Verified (sample files) | python/src/saengine/library/dwg.py; python/tests/test_dwg.py using fixtures saved by AutoCAD in python/tests/data/dwg (skipped without LibreDWG) | 5 | – |
| Architect DXF or DWG converted to walls, doors, windows and rooms (layer mapping) | add-on | – | – | Verified (sample files) | python/src/saengine/library/architecture_dxf.py; python/tests/test_architecture_dxf.py (synthetic architect-style plans) | 5 | A real Bangladeshi architect's DWG |

### E. Interoperability

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| IFC4 export of the structure (openings, stairs, inclined members) | ✓ | add-on | – | Verified (round trip) | python/src/saengine/library/ifc.py; python/tests/test_ifc.py | 6 | ifcopenshell validate, then open in an independent viewer |
| IFC4 export of the architecture (IfcWall, IfcDoor, IfcWindow, IfcSpace, IfcCovering) | ✓ | – | – | Verified (round trip) | python/src/saengine/library/architecture_ifc.py; python/tests/test_architecture.py::test_ifc_round_trip | 6 | – |
| IFC export of MEP (IfcTank, IfcPipeSegment, IfcDuctSegment, IfcCableCarrierSegment) | ✓ | – | ✓ | Built, untested | python/src/saengine/library/ifc.py (around lines 496–729); used in python/tests/test_mep_clash.py and python/tests/test_services_integration.py | 7 | – |
| IFC import of an architect's model (adopted into architecture.json) | ✓ | – | – | Verified (synthetic round trip) | python/tests/test_architecture.py::test_import_of_an_architects_ifc | 5 | A public Revit- or ArchiCAD-exported IFC sample |
| Import of MEP consultants' IFC models (discipline detected) | ✓ | – | ✓ | Built, untested | python/src/saengine/mep/ifc_import.py; python/tests/test_mep_clash.py::test_import_ifc_guesses_the_discipline | 7 | – |
| IFC structural analysis view | ✓ | – | – | Built, untested | python/src/saengine/library/ifc_structural.py (IfcStructuralAnalysisModel, curve/surface members, point supports with IfcBoundaryNodeCondition, load groups/actions, IfcRelAssignsToProduct); python/tests/test_ifc_r9.py::test_structural_analysis_view_two_bay_frame | 11 | Round-trip in structural viewer |
| IFC2x3 export | ✓ | – | – | Built, untested | python/src/saengine/library/ifc.py (`schema="IFC2X3"` with entity/PredefinedType mappings, ProjectSettings.ifc, export.ifc, CLI `--schema`); python/tests/test_ifc_r9.py::test_ifc2x3_two_bay_frame_counts_and_validates | 6 | Third-party IFC2x3 reader |
| IDS checks | add-on | – | – | Built, untested | python/src/saengine/mep/ids.py; only python/tests/test_mep_coordination.py::test_ids_without_ifctester_says_so | 7 | buildingSMART IDS sample, pass and fail cases |
| Model diff between revisions | add-on | ✓ (DWG compare) | – | Built, untested | python/src/saengine/library/ifc_diff.py (`diff_ifc`) + python/src/saengine/project/diff.py (`.ifc` revision diff JSON & colour-coded summary); python/tests/test_ifc_r9.py::test_ifc_diff_self_is_empty_and_moved_beam_reported | Shell | – |
| BCF 3.0 and 2.1 export and import | add-on | – | add-on | Verified (round trip) | python/src/saengine/mep/bcf.py; python/tests/test_mep_coordination.py::test_bcf_round_trip, ::test_bcf_import_updates_and_adds, ::test_bcf_statuses_of_other_tools | 7 | A BCF file from another tool |
| Multi-model clash detection (hard and clearance) and issue workflow | ✓ (interference check); add-on (Navisworks) | – | add-on | Built, untested | python/src/saengine/mep/coordination.py, python/src/saengine/mep/clash.py; python/tests/test_mep_coordination.py (unit tests on synthetic geometry) | 7 | Boxes with known overlap and clearance, worked by hand |
| Revit link (structural exchange file, preview, apply) | ✓ | – | – | Partial | python/src/saengine/exporters/revit_link.py; python/tests/test_revit_link.py; revit-addin/ (MIT Revit 2027 add-in, `SAEngine.RevitLink.Core` builds on .NET 8; `SAEngine.RevitLink` untested in live Revit) | 11 | Round trip through the add-in in Revit |
| Native RVT or RFA read and write | ✓ | – | ? | Out of scope (decision) | Owner decision: AGPL must not link RevitAPI.dll; add-in later (architecture layer plan) | 11 | – |
| Analysis exchange (SAF, CIS/2, SDNF, .s2k, .std, .e2k) | add-on | – | – | Partial | python/src/saengine/exporters/*; python/tests/test_exchange_exports.py (SAEngine reads back its own files only); docs/exchange.md "Not verified" | 11 | Open in the target program or a format validator |
| Georeferencing (BTM), GeoJSON, GeoPackage, shared coordinates | ✓ | ✓ | – | Built, untested | python/src/saengine/gis/crs.py (`ifc_map_conversion`), python/src/saengine/library/ifc.py (`IfcMapConversion`/`IfcProjectedCRS` in IFC4, `ePSet_MapConversion`/`ePSet_ProjectedCRS` in IFC2X3), geojson.py, gpkg.py; python/tests/test_ifc_r9.py::test_georeferencing_map_conversion_against_crs | 1 | Published BTM control-point transform |
| Web viewer for reviewers (no licence needed) | add-on | add-on | – | Built, untested | python/src/saengine/exporters/web_viewer.py | 11 | – |

### F. MEP

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Cooling load calculation | ✓ | – | ✓ | Verified (per-room & per-storey fallback; EnergyPlus optional) | Room-by-room and per-storey CLTD/CLF-style fallback and EnergyPlus epJSON; python/src/saengine/verification/cases/hvac_loads.py DH1, DH2, AH1 (AH1 needs EnergyPlus); python/tests/test_hvac_r6.py; python/src/saengine/hvac/geometry.py, gains.py, fallback.py, energyplus.py, report.py | 7 | ASHRAE-style worked load example for a single room |
| Heating load | ✓ | – | ✓ | Verified (fallback; EnergyPlus setpoint & winter day) | Envelope conduction + infiltration + outdoor air in python/src/saengine/hvac/fallback.py, winter design DB & infiltration in code pack hvac.json, heating setpoint & WinterDesignDay in python/src/saengine/hvac/energyplus.py; hand-checked in python/tests/test_hvac_r6.py | 7 | Hand envelope + infiltration calculation for one room |
| Ventilation and outdoor-air load | ✓ | – | ✓ | Verified | python/src/saengine/verification/cases/hvac_loads.py DH1 | 7 | – |
| Supply airflow and duct sizing (equal friction) | ✓ | – | ✓ | Verified | python/src/saengine/hvac/air.py; python/src/saengine/verification/cases/hvac_air.py DA1 | 7 | – |
| Duct pressure drop, fan static pressure, static regain | ✓ | – | ✓ | Verified | Darcy–Weisbach (Colebrook) friction per material, fitting C-coefficients from hvac.json, critical-path total pressure → fan static pressure, static regain, velocity reduction, and noise velocity flags in python/src/saengine/hvac/air.py; hand-checked in python/tests/test_hvac_r6.py | 7 | Published duct system pressure-loss example |
| Duct layout and routing | ✓ | add-on | ✓ | Verified (RoomGraph auto-routing) | Auto-routing from AHU/FCU to room diffusers via RoomGraph corridor spines with beam-crossing penalties in python/src/saengine/hvac/routing.py and python/src/saengine/mep/routing.py; ceiling-void check skipped while architecture.ceiling_void is absent; python/tests/test_hvac_r6.py | 7 | – |
| Fittings and LOD 400 fabrication (elbows, spools, hangers) | ✓ | add-on | add-on | Built, untested | python/src/saengine/mep/fabrication.py; python/tests/test_l11_office_tools.py::test_fabrication_pieces_fittings_hangers | 7 | Hand cut lengths for one run |
| HVAC plant sizing and weights (chiller, AHU, cooling tower, VRF) | ✓ | – | ✓ | Verified | python/src/saengine/hvac/plant.py; python/src/saengine/verification/cases/hvac_air.py DA2; python/tests/test_hvac_plant.py | 7 | – |
| Chilled and condenser water pipe sizing | ✓ | – | ✓ | Built, untested | plant.py (velocity at most 3 m/s, friction at most 400 Pa/m); python/tests/test_hvac_plant.py::test_riser_pipe_and_sleeve | 7 | Hand Darcy friction for one pipe size |
| Annual energy simulation and envelope compliance | add-on | – | ✓ | Verified (epJSON, WWR, envelope check & EUI by hand; EnergyPlus annual run unverified without EPW/EnergyPlus) | Full-year `RunPeriod` (Jan 1–Dec 31), hourly occupancy/lighting/equipment schedules by room use, `Output:Meter` end uses, EUI (kWh/m²·yr), unmet hours, and envelope compliance pass/fail table (wall/roof/glazing U-values, WWR, SHGC) in python/src/saengine/hvac/energyplus.py, compliance.py, report.py, bnbc2020/data/hvac.json (limits/schedules marked "to be checked"); python/tests/test_hvac_annual.py | 7 | Full-year EnergyPlus run with a real EPW file |
| Water demand and storage | – | – | ✓ | Verified | python/src/saengine/plumbing/demand.py, storage.py; python/src/saengine/verification/cases/plumbing.py DB1 | 7 | – |
| Fixture units to probable flow, riser sizing | ✓ | – | ✓ | Verified | demand.py hunter_flow, supply.py; python/src/saengine/verification/cases/plumbing.py DB2 | 7 | – |
| Network hydraulics (residual head, pump head, pressure zones) | ? | – | ✓ | Verified | python/src/saengine/plumbing/hydraulics.py (WNTR running EPANET 2.2); python/src/saengine/verification/cases/hydraulics.py DW1–DW3 | 7 | – |
| Drainage fixture units, stack, branch and vent sizing | ✓ | – | ✓ | Verified | python/src/saengine/plumbing/drainage.py; python/src/saengine/verification/cases/plumbing.py DB3 (stack); vents built but not benchmarked | 7 | Hand vent-stack sizing from the table |
| Rainwater leaders, septic tank and soak well | ? | – | ✓ | Verified | rainwater.py, septic.py; python/src/saengine/verification/cases/plumbing.py DB4, DB5 | 7 | – |
| RC water tanks (overhead, underground, septic) | – | – | – | Verified | python/src/saengine/plumbing/tanks.py, tanks_model.py; python/src/saengine/verification/cases/tanks.py AK1, DK1–DK3 | 7 | – |
| Hot water system (heater sizing, recirculation) | ✓ | – | ✓ | Verified | python/src/saengine/plumbing/hot_water.py (heater storage + recovery, recirculation loop flow & pipe sizing); python/tests/test_r7_revit_mep.py::test_hot_water_storage_and_recirculation_by_hand | 7 | – |
| Branch pipe routing through rooms, beam crossings | ✓ | – | ✓ | Built, untested | python/src/saengine/plumbing/branches.py, python/src/saengine/mep/routing.py; python/tests/test_mep_rooms.py::test_branch_runs_and_the_beams_they_cross | 7 | – |
| Gas and medical gas | ✓ | – | ✓ | Verified | python/src/saengine/plumbing/gas.py (natural gas / LPG diversity, Pole's formula, meter checks, medical gas outlets & pipes); python/tests/test_r7_revit_mep.py::test_gas_pipe_sizing_by_hand, ::test_lpg_basement_check_and_medical_gas | 7 | – |
| Sprinkler layout and pipe schedule | ✓ | – | ✓ | Verified | python/src/saengine/fire/sprinklers.py (room grid head placement, RoomGraph branch/cross-main routing, pipe schedule); python/src/saengine/fire/network.py (placed_sprinkler_network); python/tests/test_r7_revit_mep.py::test_sprinkler_room_grid_by_hand, ::test_sprinkler_placed_network_routing_and_hydraulics | 7 | – |
| Sprinkler hydraulic calculation | add-on | – | ✓ | Verified, with a caveat | python/src/saengine/fire/network.py (EPANET); python/src/saengine/verification/cases/fire.py DF3, DF4; the NFPA design area and density are marked "from memory, to be checked" | 7 | Published sprinkler hydraulic worked example |
| Standpipes, fire pump, fire-water reservoir | add-on | – | ✓ | Verified | python/src/saengine/fire/supply.py, network.py; python/src/saengine/verification/cases/fire.py DF1, DF2 | 7 | – |
| Fire alarm and detection | ✓ | – | ✓ | Verified | python/src/saengine/fire/alarm.py (smoke/heat detector grid per room, MCPs at exits, sounders, panel, battery Ah calculation); python/tests/test_r7_revit_mep.py::test_fire_alarm_battery_by_hand, ::test_fire_alarm_device_layout | 7 | – |
| Connected load and maximum demand | ✓ | – | ✓ | Verified | Per storey from unit load densities; python/src/saengine/electrical/demand.py; python/src/saengine/verification/cases/electrical.py DE1 | 7 | – |
| Panel and distribution-board schedules, circuiting | ✓ | – | ✓ | Verified | python/src/saengine/electrical/panels.py, python/src/saengine/drawings/sheets/mep.py (db_schedule_tables); python/tests/test_electrical_circuits.py (greedy phase balancing [5,4,3,3,2,1] -> 6 kW, schedule rows sum to incomer load, Excel export via write_xlsx and drawing schedule tables) | 7 | – |
| Cable sizing (ampacity, derating) | ✓ | – | ✓ | Verified | python/src/saengine/electrical/cables.py, python/src/saengine/electrical/risers.py; python/tests/test_electrical_circuits.py (2.5 mm² Cu PVC method C 30 °C Iz=27 A, 3-circuit grouping Cg=0.70 Iz=18.9 A, adiabatic k²S²≥I²t); IEC 60364-5-52 Annex B / IEC 60364-4-43 pack tables in bnbc2020/data/electrical.json marked "to be checked" | 7 | Hand cable size from a published current-rating table |
| Voltage drop | ✓ | – | ✓ | Verified | python/src/saengine/electrical/cables.py (mV/A/m and R/X with cos φ, cumulative from transformer); python/tests/test_electrical_circuits.py (18 mV/A/m × 16 A × 20 m / 1000 = 5.76 V = 2.50 %, failing 60 m run recommends 4 mm²); IEC 60364-5-52 Annex G pack limits marked "to be checked" | 7 | Hand mV/A/m calculation |
| Short circuit and fault level | – | – | ✓ | Verified | python/src/saengine/electrical/short_circuit.py; python/tests/test_electrical_circuits.py (1000 kVA 11/0.415 kV uk 5 % -> Ik3 27.82 kA at c=1.0 / 29.22 kA at c=1.05, breaking capacity Icu, Zs ≤ limit); IEC 60909-0 / IEC 60898-1 pack parameters marked "to be checked" | 7 | IEC 60909-style worked example |
| Transformer, standby generator and fuel, UPS, room checks | – | – | ✓ | Verified | python/src/saengine/electrical/supply.py, rooms.py; python/src/saengine/verification/cases/electrical.py DE1, DE2 | 7 | – |
| Lighting design (lux levels, luminaire layout) | add-on | – | ✓ | Verified | python/src/saengine/electrical/lighting.py (lumen method, UF table, luminaire library, grid layout, HVAC/electrical feedback); python/tests/test_r7_revit_mep.py::test_lumen_method_office_by_hand | 7 | Lumen-method hand calculation |
| Lightning protection and earthing | – | – | ✓ | Verified | python/src/saengine/electrical/lightning.py; python/src/saengine/verification/cases/electrical.py DE4 | 7 | – |
| Cable trays: fill and openings | ✓ | – | ✓ | Verified (openings) | risers.py; python/src/saengine/verification/cases/electrical.py DE3; the 40 % tray fill is marked "from memory" | 7 | – |
| MEP equipment loads on the structure (SD and F cases) | – | – | – | Verified | python/src/saengine/mep/loads.py; python/src/saengine/verification/cases/mep.py DM1; python/src/saengine/verification/cases/tanks.py DK3 | 7 | – |
| Sleeves and web openings in beams (checks) | add-on | – | – | Verified | python/src/saengine/mep/openings.py, python/src/saengine/hvac/openings.py; python/src/saengine/verification/cases/mep.py DM2, AM1; python/src/saengine/verification/cases/hvac_air.py DA3 | 7 | – |
| Slab openings near columns (punching perimeter) | – | – | – | Verified | python/src/saengine/verification/cases/mep.py DM3 | 7 | – |
| Sleeves proposed from clashes, riser sleeves, shafts | add-on | – | add-on | Built, untested | python/src/saengine/mep/report.py mep_suggest_sleeves; python/src/saengine/plumbing/sleeves.py; python/tests/test_mep_clash.py::test_suggested_sleeves_are_checked | 7 | – |
| MEP-against-structure clash check | ✓ | – | add-on | Built, untested | python/src/saengine/mep/clash.py; python/tests/test_mep_clash.py | 7 | Hand-placed pipe through a beam with a known overlap |
| MEP systems and connectors (logical networks, system browser) | ✓ | – | ✓ | Verified | python/src/saengine/mep/systems.py, python/src/saengine/library/mep.py (Connector, Pipe, AirTerminal), python/src/saengine/library/ifc.py (_export_systems), workbench/src/vs/workbench/contrib/saengineMep/browser/systemBrowserView.ts; python/tests/test_mep_systems.py | 7 | AHU with trunk, branches and diffusers (total flow and disconnect check); 50 to 40 mm size mismatch; mixed classification; legacy mep.json without connectors |

### G. Quantities and BOQ

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Concrete, formwork and excavation from the model | ✓ | ✓ (data extraction) | – | Built, untested | python/src/saengine/boq/quantities.py; python/tests/test_boq.py (unit, no hand values) | 10 | Hand take-off of a two-bay sample frame |
| Rebar quantities from the detailed bars (agree with the BBS) | ✓ | – | – | Built, untested | python/src/saengine/boq/schedule.py; python/tests/test_boq.py::test_the_bill_takes_the_detailed_bars | 10 | – |
| Cement (kg and bags), sand and stone (cft) from mixes | – | – | – | Verified | python/tests/test_boq_materials.py (by hand) | 10 | – |
| Brickwork, plaster, finishes, doors and windows | ✓ | – | – | Verified | python/src/saengine/boq/architecture.py; python/tests/test_architecture_loads.py, python/tests/test_architecture_extras.py::test_boq_of_the_extras_by_hand | 10 | – |
| MEP quantities (pipes by size, sprinklers, valves, tanks, ducts, trays) | ✓ | – | ✓ | Built, untested | python/src/saengine/fire/boq.py; quantities.py PLUMBING_CONVENTIONS | 10 | Hand count for the DF and DB test buildings |
| Costing from a schedule of rates, embodied carbon | add-on | – | – | Built, untested | python/src/saengine/boq/costing.py; python/tests/test_boq_costing.py | 10 | – |
| Excel workbook with live formulas | ✓ (schedule export) | ✓ | – | Built, untested | python/src/saengine/boq/workbook.py | 10 | – |
| PDF 2D take-off | – | add-on | – | Built, untested | python/src/saengine/boq/takeoff.py; python/tests/test_l11_office_tools.py::test_takeoff_calibration_and_measures | 10 | – |
| Earthwork cut and fill | add-on | add-on | – | Verified | python/tests/test_l11_office_tools.py::test_cut_fill_of_a_sloped_tin_is_exact | 10 | – |
| 4D programme and playback | add-on | – | – | Built, untested | python/src/saengine/boq/construction_schedule.py; python/tests/test_l11_office_tools.py::test_schedule_* | 10 | – |
| Cost-driven optimisation | – | – | – | Built, untested | python/tests/test_l11_office_tools.py::test_apply_optimisation_changes_only_cheaper_accepted_groups | 10 | – |

### H. Collaboration

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Office copy and sync with per-part three-way merge | ✓ (central model) | – | – | Built, untested | python/src/saengine/project/share.py; python/tests/test_project_share.py; docs/collaboration.md | Shell | Two-user scripted conflict scenario |
| Part locks and presence (the equivalent of element borrowing) | ✓ | – | – | Built, untested | share.py; python/tests/test_project_share.py::test_locks_block_sending_a_locked_part, ::test_presence_and_not_shared | Shell | – |
| Live co-editing (Yjs over the office relay) | add-on (cloud worksharing) | – | – | Built, untested | workbench/src/vs/platform/saengine/node/coEditingRelay.ts, coEditingDoc.ts; workbench/src/vs/platform/saengine/test/node/coEditing.test.ts | Shell | – |
| Versions, restore, semantic diff | ✓ (backups) | ✓ (DWG compare) | – | Built, untested | python/src/saengine/project/versions.py, diff.py; python/tests/test_project_versions.py, python/tests/test_project_diff.py | Shell | – |
| Cloud hosting (an ACC or BIM 360 equivalent) | add-on | add-on | add-on | Out of scope (decision) | docs/collaboration.md "SAEngine uses no outside service" | Shell | – |
| Project archive and transmittal (.civil) | ? | ✓ (eTransmit) | – | Built, untested | python/src/saengine/project/archive.py; python/tests/test_project_archive.py | Shell | – |

### I. API and scripting

| Feature | Revit | AutoCAD | Typical MEP tools | SAEngine status | Evidence | Part | Benchmark that would prove it |
|---|---|---|---|---|---|---|---|
| Versioned Python API | ✓ (.NET) | ✓ (.NET, AutoLISP) | ? | Built, untested | python/src/saengine/api.py; docs/sdk/; python/tests/test_sdk.py | Shell | – |
| JSON-RPC server for other languages | – | – | – | Built, untested | python/src/saengine/rpc/server.py; python/tests/test_rpc*.py | Shell | – |
| Command line and batch runs | ✓ (journals) | ✓ (core console, scripts) | ? | Built, untested | python/src/saengine/cli/main.py; docs/cli.md; python/tests/test_cli.py | Shell | – |
| Visual programming (a Dynamo equivalent) | ✓ (Dynamo) | – | – | Built, untested | python/src/saengine/automation/graph.py; python/tests/test_l12_automation.py | Shell | – |
| Scripts that generate models, parametric studies | ✓ (Dynamo, pyRevit add-on) | ✓ | – | Built, untested | python/src/saengine/library/script.py, python/src/saengine/automation/studies.py | 5 | – |
| Plugins, code packs, marketplace | ✓ | ✓ | ? | Partial | Code packs are built (docs/code-packs.md); the marketplace is only planned (docs/marketplace-plan.md) | Code packs | – |
| AI assistant that edits the model | add-on | ? | – | Partial | python/src/saengine/ai/knowledge.py and the title-bar chat; the model-editing assistant is planned (docs/engineering-decisions.md, 2026-11-11) | Shell | – |

### Summary

**Counts (158 rows; CAD drafting rows updated 19 November 2026 after the CAD parity and AutoCAD-gaps rounds):**

| Status | Rows |
|---|---|
| Verified | 78 |
| Built, untested | 68 |
| Partial | 6 |
| Missing | 0 |
| Out of scope (decision) | 6 |

"Verified (geometry)" in the CAD drafting rows means the package tests check the geometry against hand-computed values; the commands themselves are walked in the app only where the row says so.

Verification is concentrated where the structure meets MEP (equipment loads, sleeves, openings, tanks) and in plumbing and fire. Documentation, collaboration and API features are mostly built with unit tests only.

**Some of the stated decisions don't match the repo:**
- **Phases and design options** were added in alpha 9 L11 (docs/engineering-decisions.md, the "Phasing and design options" entry; python/src/saengine/project/phasing.py). They are now Built, untested, not out of scope. The docstring in python/src/saengine/library/architecture.py still says there are none, so it is stale.
- **Where the other decisions are recorded:** "no family editor, worksets or stacked walls", "MEP is coordination-grade" and "bundle LibreCAD" are owner decisions that are not logged in docs/engineering-decisions.md. In the repo they appear only in the architecture.py docstring, docs/manual/07-mep.md and docs/ci.md.
- **MEP has grown past coordination.** It now sizes plumbing, fire, HVAC and electrical supply, but still has no circuit-level electrical design.

**12 most important gaps for a Bangladeshi structural engineer coordinating architecture and MEP:**
1. **Electrical circuits (now built and unit-verified in R5, pack tables to be checked).** Distribution-board schedules, circuiting, cable sizing with derating, voltage drop and short-circuit checks are implemented in `saengine/electrical/` with IEC 60364 / IEC 60909 data in `bnbc2020/data/electrical.json` (marked "to be checked" against printed editions); workbench UI controls for editing circuits are not yet added.
2. **Revit round trip.** The Revit link has no add-in in the repo, so it cannot work end to end.
3. **No third-party IFC tested.** IFC4 and IFC2x3 outputs validate with `ifcopenshell.validate`, though they are tested only on SAEngine's own synthetic files rather than third-party viewers.
4. **3D view app walks.** Section box, single section planes, 3D measure with snapping, and temporary/permanent hide/isolate were added in `@saengine/fem-viewer` and the workbench 3D viewers (R3 parity, November 2026, math unit-tested), but have not yet been walked end-to-end in the desktop app.
5. **Ceiling void.** There are no ceiling elements, so duct and tray clearance under false ceilings cannot be checked.
6. **Cooling loads per storey only.** The zone-per-storey model makes duct sizes, and so the beam openings, coarse.
7. **Clash detection has no benchmark** against hand-placed cases.
8. **Sprinkler inputs unconfirmed.** The design area and density, and the 40 % tray fill, are marked "from memory, to be checked".
9. **Bengali text and app walks in the CAD editor.** The floor plan's CAD editor now covers AutoCAD 2D drafting (CAD parity and AutoCAD-gaps rounds, November 2026), but Bengali text shaping is still incomplete, and lasso, cycling, block editing and constraints have not yet been walked in the app.
10. **Schedules and views.** There are no user-defined schedules, callouts, legends or keynotes, so non-standard submissions need manual CAD work.
11. **Sheet DWG export is untested** (LibreDWG dxf2dwg). Bangladeshi consultants usually exchange DWG.
12. **Duct pressure.** There is no fan static pressure or duct pressure drop, so AHU and fan selection (and so plant weights) rest on typical values.

**8 cheapest high-value verifications to do first:**
1. **Run the existing verification pack** (`python -m saengine.verification --fast` from `python/`) and record the results of DM1–3, AM1, DB1–5, DW1–3, AK1, DK1–3, DF1–4, DE1–4, DA1–3 and DH1–2. No new code is needed.
2. **Validate the sample project's IFC.** Run ifcopenshell validate on the exported IFC and import one public Revit- or ArchiCAD-exported IFC sample through the architect-IFC adopt path.
3. **DWG round trip.** Write sheets with write_dwg, read them back with dwg2dxf, and compare entity counts per layer. The fixture tooling is already in python/tests/test_dwg.py.
4. **Clash benchmark.** Place a pipe through a beam and a duct beside a slab edge with known overlap and clearance, worked by hand, and assert hard and clearance clash counts. Then export to BCF and re-import it.
5. **Hand take-off of the two-bay sample frame** (concrete, formwork, excavation) against python/tests/test_boq.py. The BOQ core is currently Built, untested.
6. **Check the "from memory" values** (NFPA design area and density, 40 % tray fill, IEC mesh size) against the standards, and re-run DF3 and DE3.
7. **Two-phase toy model:** split the bill by phase by hand and compare with phasing.phase_bill.
8. **Hand-check the room-group HVAC load for one room** (ASHRAE-style worked example) against the fallback estimate, before room-by-room zones are built.
