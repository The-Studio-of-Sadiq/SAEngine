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

The rest of the concrete, foundation and load parts (version 0.4, alpha 9 track C5c; values
C5c-1 to C5c-72 of VERIFY.md):

- Deep beams (span below 3 h), corbels (Annex J) and the deep pile caps by strut-and-tie models
  on the design strengths (6.5: struts fcd / 0.6 ν' fcd, nodes k1-k3 ν' fcd, ties fyd), the
  deep beams' web mesh (9.7) (`concreteMethods.strutAndTie`, `saengine.design.stress_fields`).
- Slabs and stairs by the limiting span/depth ratio (7.4.2) in place of the parent's least
  thickness table.
- The confinement ωwd of DCM/DCH columns' critical regions and of ductile walls' boundary
  elements (EN 1998-1 5.4.3.2.2(8), 5.4.3.4.2(4)) with μφ from q0 and T1.
- Footings, pile caps and rafts: punching on control perimeters within 2d with the soil
  pressure (pile reactions) inside deducted (6.4.4) (`footingPunching`).
- Retaining walls by EN 1997-1 Section 9 in each combination of the design approach (earth
  pressure with Ka(φ'd), sliding, bearing on B', overturning by EQU) and the stem and base by
  EN 1992-1-1 (`geotechnicalMethods.retaining`, `equilibrium`).
- Bends, hooks and links' bends (8.3, 8.4.1, 8.5), compression laps and column splices (8.4.4,
  8.7) in the detailing (`barShapes`).
- Flanged wall groups' shear by the webs' VRd; walls out of their plane as columns (5.8) with
  the out-of-plane shear VRd,c (`wallSlenderness`); construction joints by 6.2.5
  (`interfaceShear`); tying systems by 9.10 (`ties`); the footing sizing assistant by the
  bearing resistance of the design approach.
- EN 1991-1-4: torsion by e = b/10 (7.1.2), orography co(z) of Annex A.3, the detailed cscd of
  Annex B outside the simplified cases, the cladding pressures by cpe,1 / cpe,10 (7.2,
  `wind.localPressures`); EN 1991-1-3: drifts at roof steps and parapets (5.3.6, 6.2).
- EN 1998-1: regularity in plan and elevation by the criteria of 4.2.3 with q × 0.8 (not
  regular in elevation) and αu/α1 averaged (not regular in plan), δ of 4.3.3.2.4 where no
  accidental eccentricity is analysed, the vertical component where avg > 0.25 g, SRSS or CQC
  by the modes' independence, the capacity design of foundations (4.4.2.6) and the Type 1/2
  guidance (`seismic.regularity`, `torsionalEffects`, `verticalComponent`,
  `modalCombination`, `foundationCapacity`, `spectrumTypeGuidance`).

Still by the parent's method: the general strut-and-tie models of D-regions, the punching
reinforcement of footings and rafts, Annex B's exceptional snow drifts and the snow on
pitched roofs beside a step (μs = 0 taken).

## Steel and the other materials (version 0.4, alpha 9 track C6)

Steel is designed by the limit state steel table `steelLimitState` (the same table and selector
as the IS pack's IS 800 method; each group names its method id):

- `memberResistance` (method `crossSectionClasses`, `saengine.design.steel.buckling_curves`):
  EN 1993-1-1 with γM0 1.00, γM1 1.00, γM2 1.25, E 210 000 and G 81 000 MPa, fy of thick plates
  (Table 3.1); cross-section classes 1-4 (Table 5.2, the web by α and ψ under N + M), class 4 by
  the effective widths of EN 1993-1-5 4.4 (Aeff; Weff of I-sections, channels and RHS); the
  resistances of 6.2 (tension, compression, bending, shear with η and shear buckling, bending
  with shear, bending with axial force by MN and the biaxial exponents); flexural, torsional and
  flexural-torsional buckling with the curves a0-d of Table 6.2 (χ of the limit state method);
  lateral-torsional buckling by the rolled case 6.3.2.3 (default) or the general case 6.3.2.2,
  Mcr by the C1 formula with C1 from the moment diagram; the interaction 6.3.3 by Annex B
  (default) or Annex A (`interaction.method`).
- `connections` (method `partialFactors`, `saengine.design.steel.joint_resistances`): EN
  1993-1-8 Table 3.4 bolts in shear, tension and both, bearing with αb and k1, the simplified
  (default) or directional weld method of 4.5.3 with βw, block tearing 3.10.2, slip 3.9; holes
  and edges of Table 3.3 in `steel.connections`; the plate checks of the shared connection
  checks with the factors 1/γM (`steel.phi`).
- `seismic` (method `dissipativeZones`, `saengine.design.steel.seismic_dissipative`): EN 1998-1
  Section 6: γov 1.25, Ω of the dissipative members, the non-dissipative members under G +
  1.1 γov Ω E, section classes by ductility class, MRF beam N and V limits, column shear, ΣMRc >=
  1.3 ΣMRb, brace slenderness 1.3 < λ̄ <= 2.0, Ωmax <= 1.25 Ωmin, EBF links taken as short links.
  The parent's AISC-type frame provisions are switched off (`steelSeismic.systems` emptied).
- The global sway imperfection φ = φ0 αh αm of 5.3.2 as the notional loads of the second-order
  method (`steelStability.notional.swayImperfection`, every combination), αcr from Δ2nd/Δ1st as
  a column flag.

The other materials: **composite** members by EN 1994-1-1 (`composite.partialFactors`: design
strengths, headed studs PRd with γV, kt/kl of decks, Ecm, the least degree of shear connection,
columns by χ with (EI)eff and the second-order moments with e0, αM μd); **timber** by EN 1995-1-1
(`timber.method = "partialFactors"`: EN 338 and EN 14080 strength classes, kmod by service class
and load duration, γM, kh, kcr, km, kc and kcrit; the material's `strengthClass`, the service
class from its location of use); **masonry** by EN 1996-1-1 (`masonry.method = "partialFactors"`:
fk = K fb^α fm^β, γM 2.0, Φ at the ends and mid-height, fvk, reinforced walls MRd = As fyd z);
**aluminium** members by EN 1999-1-1 (the `aluminium` table and the material category
`aluminium`: alloys with f0, fu and the heat-affected zone, buckling classes A/B, classes by β/ε,
ρc, γM1 1.10, γM2 1.25). Every value is in VERIFY.md (rows 217-297).

Not covered by the C6 methods (stated in the notes): torsion of steel members, the shift eN of
class 4 sections, class 4 circular tubes (EN 1993-1-6), the stability bracing rules, timber
joints and serviceability, aluminium joints and the plate buckling of slender aluminium webs.

## What falls back (not Eurocode yet)

The pack `extends` BNBC 2020, so a project designs and runs. For the methods not covered above,
these tables come from **BNBC 2020** and the report's design basis says so: `materials`,
`factors`, `concrete`, `detailing`, `steelSections`, `foundations`, `transfer`,
`slabCoefficients`, `slabMethods`, `wallMethods`, `stairMethods`, `compositeConcrete`,
`anchors`, `concreteTime`, `designLimits`, `designClauses`, `serviceability`,
`siteInvestigation`, `fireResistance` and the services (`plumbing`, `hvac`, `electrical`,
`fire`, `planning`, `accessibility`, `mepOpenings`); the parts of `steel`, `composite`,
`masonry` and `timber` the pack does not set (base plates, HSS joints, the masonry seismic
detailing, the timber joints). The load tables without a Eurocode counterpart here are the
parent's too: `deadLoads` (unit weights), `cranes`, `nonstructural`, `isolation`, `pushover`,
`nonlinearHistory`, `fatigue` and the flood, rain, helipad and shelter parts of `flood`.

Not covered by this version (stated in the results where they would apply): EN 1991-1-3
local effects (overhangs, snow guards) and exceptional drifts; EN 1998-1 response history
rules.

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
