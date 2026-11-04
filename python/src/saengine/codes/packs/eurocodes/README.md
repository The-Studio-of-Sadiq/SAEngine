# Eurocodes code pack (`eurocodes`)

The Eurocodes with their **recommended values**, loads and seismic actions only (version 0.1,
alpha 9 track C4). Choose it in **02 Project Settings → Design code** or in the **New Building**
wizard's design code list.

Every value, with its clause and a one-line description, is in [`VERIFY.md`](VERIFY.md) for
checking against the printed codes: no code text was available when the pack was written, and
the values marked there as unsure must be checked before the pack is used for design.

## What it covers

| Table | Code | What |
| --- | --- | --- |
| `combinations` | EN 1990 Sec 6.4.3, 6.5.3, Annex A1 | ULS sets **6.10** and **6.10a/b** (`strengthSet` chooses), seismic 6.12b, SLS characteristic, frequent and quasi-permanent; ψ of Table A1.1, partial factors of Table A1.2(B) |
| `areaLoads` | EN 1991-1-1 Sec 6.3, 6.4, Annex B | Imposed loads of categories A-I (with `category`), movable partitions, barriers and vehicle barriers |
| `liveReduction` | EN 1991-1-1 Sec 6.3.1.2(10)-(11) | αA and αn (`method: "areaAndStoreys"`) |
| `snow` | EN 1991-1-3 Sec 5.2, 5.3.2 | s = μ1·Ce·Ct·sk on the roof (the project gives sk under Site → Snow) |
| `wind` | EN 1991-1-4 Sec 4, 6.2, 7.2.2 | Peak velocity pressure qp(z) by terrain category (`method: "peakVelocityPressure"`), cpe of walls, lack of correlation, cscd |
| `flood` | EN 1991-1-7 Annex D | Internal gas explosions only (`explosion`); the rest of the table is the parent's |
| `seismic` | EN 1998-1 Sec 3, 4; Tables 5.1, 6.2, 9.1 | Ground types A-E (ids SA-SE), Type 1 and Type 2 spectra (`spectrumType`), the design spectrum with q and β, behaviour factors of the systems SAEngine models (DCL, DCM, DCH), λ and the linear lateral force distribution, accidental torsion, 90 % modal mass, 0.3 orthogonal share, ψE, drift with ν, θ |
| `occupancyCategories` | EN 1998-1 Sec 4.2.5 | Importance classes I-IV, γI |
| `locations`, `zoneCoefficients` | EN 1998-1 Sec 3.2.1, EN 1991-1-4 Sec 4.2 | No towns (National Annex maps): Location Custom with agR as Z and vb,0 as V; bands of agR for the category of the seismic action |

The pack chooses these generic methods of SAEngine by id (other packs may choose them too):
`seismic.designSpectrum.method: "behaviourFactor"` (`saengine.fem.spectra`),
`seismic.lateralForce`, `seismic.driftAmplification: "displacementFactor"`,
`seismic.stability.method: "designDrift"`, `wind.method: "peakVelocityPressure"`
(`saengine.fem.peak_velocity_pressure`), `liveReduction.method: "areaAndStoreys"` and the
`snow` table (`saengine.fem.snow_load`).

## Concrete and foundations (version 0.2, alpha 9 track C5)

| Table | Code | What |
| --- | --- | --- |
| `concreteMethods` | EN 1992-1-1 | `ultimate` (method `partialFactors`): fcd = αcc fck/γc, fyd = fyk/γs, no φ; the strength-class relations of Table 3.1 as coefficients; the rectangular block η, λ, εcu3 (or `stressBlock: "parabolaRectangle"`); NRd with εc2; e0 = h/30 ≥ 20 mm |
| | EN 1992-1-1 6.2, 6.3, 6.4 | `shear` (`variableStrut`): VRd,c, VRd,s, VRd,max, cot θ 1-2.5, ρw,min, link spacing; `torsion` (`thinWalledVariableStrut`); `punching` (`controlPerimeter`) |
| | EN 1992-1-1 7.2-7.4 | `serviceStress` (k1-k4), `cracking` (`directWidth`: wmax by exposure, As,min, wk), `deflection` (`spanDepthK`: Eqs 7.16a/b, K) |
| | EN 1992-1-1 4.4, 8, 9 | `cover` (`exposureClass`: cmin,dur by S class, Δcdev), `anchorage` (`bondStress`: fbd, lbd, l0, α6), `memberSteel` (beams, slabs, columns, walls), `exposureClasses` |
| | EN 1998-1 Section 5 | `seismic` (`curvatureDuctility`): DCM and DCH (special → DCH, intermediate → DCM): γRd, strong column 1.3, critical lengths, hoop spacing, ρ limits, νd, confinement ωwd, DCH joints, ductile walls, coupling beams |
| `geotechnicalMethods` | EN 1997-1 | Sets A1/A2, M1/M2, R1-R4 (spread foundations; driven, bored, CFA piles), design approaches DA1 (combinations 1 and 2), DA2, DA3 (`designApproach`, DA1 by default), bearing on the effective base (Annex D, `effectiveArea`), sliding, correlation factors ξ1-ξ4 |

The generic methods: `saengine.design.design_strength`, `strut_shear`, `perimeter_punching`,
`crack_control`, `bar_rules`, `curvature_ductility` and
`saengine.substructure.limit_state_geotechnics`. A pack without these tables (BNBC 2020)
designs exactly as before.

What the design does with them (version 0.3, alpha 9 track C5b): every area is picked by
`saengine.design.method_selection` (see `docs/code-packs.md`, "Concrete and foundation
methods"); the glue is `saengine.design.limit_state_rows`, `capacity_design` and
`saengine.substructure.limit_state_footings`, `limit_state_piles`.

- Beams and columns on the design strengths (C5), and now beam torsion (6.3), span/depth
  deflection (7.4.2; the calculated deflection follows a span that exceeds it), crack widths
  and stress limits under the pack's quasi-permanent and characteristic combinations (7.2,
  7.3; they replace the bar-spacing crack control), column slenderness by λlim and the nominal
  curvature method (5.8.3.1, 5.8.8).
- Slabs (shells, coefficients, direct design and equivalent frame moments as SAEngine computes
  them) and stairs: MRd of the strips on fcd/fyd with xu/d ≤ 0.448, VRd,c, the least steel and
  spacings of 9.3.1.1; punching of flat slabs on u1 at 2d with β (6.4).
- Walls: EN 1992-1-1 9.6 steel and spacings, in-plane shear by the variable strut method, the
  P-M interaction on the design strengths; ductile walls (DCM/DCH): ε = 1.5 on VEd, thickness,
  critical height.
- DCM/DCH frames: the curvature-ductility rows (C5) plus ΣMRc ≥ 1.3 ΣMRb at the joints, joint
  shear (DCH), capacity-design shear of beams and columns, the critical regions' hoop spacing;
  the parent's special/intermediate frame detailing does not run.
- Design Reinforcement sizes with the pack's resistances, least/largest steel, link sizes and
  spacings, and proposes the critical regions' hoops of the ductility class.
- Anchorage and laps of the detailing and the bar schedule by 8.4 and 8.7.
- Spread footings: bearing (Annex D) and sliding in each combination of the design approach
  (DA1 by default) with the founding layer of the nearest borehole; the allowable-pressure rows
  stay as a serviceability indication. Pile caps' piles: Rc,k from load tests (ξ1, ξ2) or from
  the calculated resistance at every borehole (ξ3, ξ4), Rc,d by the R sets.

Still by the parent's method (the design report lists them): deep beams and corbels, the
deflection of slabs and stairs, the confinement ωwd of columns and walls (functions only), the
footings' structural shear and punching, pile-cap structural design, retaining walls and
rafts, hooks, compression and column splices in the detailing, the sizing assistant of
footings.

## What falls back (not Eurocode yet)

The pack `extends` BNBC 2020, so a project designs and runs. Until the EN 1993 to EN 1999 packs
(track C6) exist, and for the concrete methods not covered above, these tables come from
**BNBC 2020** and the report's design basis says so: `materials`, `factors`, `concrete`, `detailing`, `steel`, `steelSections`, `steelSeismic`,
`steelStability`, `foundations`, `transfer`, `slabCoefficients`, `slabMethods`, `wallMethods`,
`stairMethods`, `masonry`, `timber`, `composite`, `compositeConcrete`, `anchors`,
`concreteTime`, `designLimits`, `designClauses`, `serviceability`, `siteInvestigation`,
`fireResistance` and the services (`plumbing`, `hvac`, `electrical`, `fire`, `planning`,
`accessibility`, `mepOpenings`). The load tables without a Eurocode counterpart here are the
parent's too: `deadLoads` (unit weights), `cranes`, `nonstructural`, `isolation`, `pushover`,
`nonlinearHistory`, `fatigue` and the flood, rain, helipad and shelter parts of `flood`. The
member design therefore applies BNBC's strength reduction factors φ to the EN 1990 design
actions.

Not covered by this version (stated in the results where they would apply): EN 1991-1-4
torsion (e = b/10), orography (co ≠ 1), the detailed cscd and the cladding pressures;
EN 1991-1-3 drift and local effects; EN 1998-1 regularity criteria (4.2.3), the torsional
effects factor δ (4.3.3.2.4), the vertical component, the SRSS/CQC choice (CQC is always used),
response history rules and capacity design.

## National Annexes

A National Annex is a pack that `extends: "eurocodes"` and gives only its Nationally Determined
Parameters. For example (see `python/tests/test_codes_eurocodes.py`):

```json
{ "schema": "saengine.codePack/1", "id": "ec-xx", "name": "Eurocodes with the XX National Annex",
  "extends": "eurocodes", "covers": ["combinations", "seismic"] }
```

`data/combinations.json`: `{ "strengthSet": "6.10ab" }`;
`data/seismic.json`: `{ "spectrumType": "2", "designSpectrum": { "lowerBound": 0.1 } }`.
Objects merge key by key, so the annex changes one value and keeps the rest. It may also list
its towns with their zones and wind speeds in `locations`, and give its own `zoneCoefficients`.
A project may override any single value under **Code Values** instead.
