# ACI 318-19 + ASCE 7-22 code pack (`aci318-asce7-22`)

The built-in US pack. This version covers the **loads** of ASCE/SEI 7-22 (alpha 9, track C1)
and **structural concrete** of ACI 318-19 (track C2), **structural steel** of AISC 360-22 and
AISC 341-22 and the strength design of **masonry** of TMS 402-22 (track C3); timber (NDS) is a
later track. The pack extends `bnbc2020`: every table or value it does not give (timber,
masonry by allowable stresses, the steel and masonry rules it does not revise, the geotechnical
tables, the building services, dead load unit weights ...) is BNBC 2020's, and the report and
the design notes cite those as BNBC 2020's.

Each table's clause references are named after the code they come from (`tableCodes` in
`pack.json`): the concrete tables "ACI 318-19", the load clauses "ASCE 7-22", the steel tables
"AISC 360-22" and "AISC 341-22"; the few rules
ACI 318-19 does not have and the pack keeps from BNBC 2020 (the two-way slab coefficient
method, stair spans) are cited as BNBC 2020's.

### Concrete tables (C2)

| File | What it holds | Clauses |
| --- | --- | --- |
| `factors.json` | φ | 21.2 |
| `materials.json` | εcu, Es, seismic concrete and bar grades | 18.2, 19.2, 20.2, 22.2 |
| `concrete.json` | bar sizes (No. 10-36), thickness tables, deflection (Ie `bischoff`), shrinkage steel 0.0018, walls, torsion, prestress (punching `precompression`) | Ch 6-11, 19-24 |
| `detailing.json` | crack control, integrity, shear friction, SMF limits, joints (γ of columns ending at the joint), special walls (1.5 δu/hw, the amplified design shear Ωv ωv, two curtains by hw/lw), bars (hooks and headed bars by db^1.5, ψg) | Ch 18, 24.3, 25 |
| `designClauses.json`, `citations.json` | the clause references of the design checks, worksheets and drawings | |
| `slabMethods.json`, `wallMethods.json`, `compositeConcrete.json` | clause references (same numbers) | 8.10-8.11, 11.8, 16.4 |
| `foundations.json` | strut-and-tie βs | Ch 23 |

Methods it chooses where ACI 318-19 differs from the default pack: `concrete.deflection.
effectiveInertia = bischoff`, `detailing.bars.development.hookMethod = powerDiameter` (with
`hook`, `headed`, `psiG`), `detailing.walls.driftFactor`, `curtainAspect`,
`shearAmplification`, `detailing.joints.gamma` "…Top" keys, `concrete.prestress.
punchingMethod = precompression`. Each is a value of the pack, overridable per project.

### Steel and masonry tables (C3)

| File | What it holds | Clauses |
| --- | --- | --- |
| `steel.json` | φ and Ω (LRFD, ASD selectable), member methods, bolts, slip, edges, concrete bearing, the connection notes' references | AISC 360-22 Ch B, D-K |
| `steelStability.json` | the direct analysis method, the effective length and first-order methods | Ch C, App 7-8 |
| `steelSeismic.json` | Ry, Rt; highly and moderately ductile width-thickness limits of √(E/(Ry Fy)); the frames' ductility | AISC 341-22 A3, D1, E1-E3, F1-F5 |
| `composite.json` | material limits, Es, C1, C3, compact filled walls, Rp | AISC 360-22 Ch I |
| `masonry.json` | strength design: φ, stress block, Pn, the in-plane shear Vnm + Vns | TMS 402-22 Ch 9 |
| `designClauses.json` `steelMembers` | the clause of every steel member check, the method text | AISC 360-22 |

Methods it chooses where AISC 360-22 differs from the default pack (BNBC 2020, AISC 360-05
based): `steel.memberMethods.compressionSlender = effectiveWidth` (Sec E7), `webShear = cv1`
(Sec G2.1, kv 5.34), `tensionField = reduced` (Sec G2.2), `teeFlexure = lengthLimits` (Sec
F9), `teeCompression = general` (Sec E4), `hssLateralTorsional` (Sec F7.4);
`steelSeismic.widthThickness.expectedYield`, `widthThicknessModerate` and the frames'
`compactness = moderate` (AISC 341-22 Table D1.1); `masonry.strength.shear` with `steelShare`,
`axialShare` (TMS 402-22). `steel.designMethod = ASD` (a project override) designs the steel
members and their connections by Rn / Ω under the ASD combinations of ASCE 7-22 Sec 2.4;
composite members, the members of a steel seismic force-resisting system and runs by the
direct analysis method stay LRFD (the report says so). Steel shapes are SAEngine's own shape
list, not the AISC shapes database (owner).

Choose it in Project Settings (Design code) or in the New Building wizard. The site's values
come from the ASCE Hazard Tool, not from a table of towns: enter SDS, SD1 (or SMS, SM1, or the
multi-period MCER spectrum), S1 and TL under Site > Mapped spectral values, the basic wind
speed V of the risk category under Site, and a ground snow load under Site > Snow.

**Every value is listed with its clause in [`VERIFY.md`](VERIFY.md), to be checked against the
printed standard.** No text of the standards is reproduced here.

## Tables

| File | What it holds | Clauses |
| --- | --- | --- |
| `locations.json` | No towns: the site's values are entered | Sec 11.4.2, 26.5.1, 7.2 |
| `occupancyCategories.json` | Risk categories I-IV, Ie; no wind importance factor | Tables 1.5-1, 1.5-2 |
| `areaLoads.json` | Live loads by use with their concentrated loads, partitions, impact | Table 4.3-1, Sec 4.3.2, 4.4, 4.6 |
| `liveReduction.json` | Reduction by influence area, KLL, roof R1 R2 | Sec 4.7, Table 4.7-1, Sec 4.8.2 |
| `combinations.json` | Strength and ASD combinations with E, flood, cantilever uplift | Sec 2.3, 2.4, 12.4 |
| `seismic.json` | Mapped spectral hazard (method `mappedSpectral`), site classes, systems, SDC bands, Cs bounds, Cu, drift limits, irregularities, W, θ | Ch 11, 12, 20 |
| `wind.json` | ASCE 7-22 terrain constants and Kz, topography; the shared coefficients from bnbc2020 | Ch 26-30 |
| `snow.json` | Flat and sloped roof snow, minimum load, density, drift (method `windParameter`) | Ch 7 |
| `flood.json` | US design flood; the Bangladesh surge tables removed | Ch 5, Sec 8.2 |
| `transfer.json` | Diaphragm force bounds and collectors | Sec 12.10.1.1, 12.10.2.1 |

## Methods it chooses

- `seismic.designSpectrum.method = mappedSpectral` (`saengine.fem.spectral_hazard`; the methods `reducedElastic` and `behaviourFactor` of the other packs share the selector): the two-period and
  multi-period spectra from the site's mapped values, Cs with its bounds, the SDC from the
  bands of SDS and SD1, Cu by SD1.
- `snow.method = slopeFactor`, `snow.loadCase = S` and `snow.drift.method = windParameter` (`saengine.fem.snow_load`, shared with the Eurocodes pack's `shapeCoefficient`).
- `seismic.stability.method = elasticDrift` (θ of Eq 12.8-16).
