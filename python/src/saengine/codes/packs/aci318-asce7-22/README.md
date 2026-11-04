# ACI 318-19 + ASCE 7-22 code pack (`aci318-asce7-22`)

The built-in US pack. This version covers the **loads** of ASCE/SEI 7-22 (alpha 9, track C1)
and **structural concrete** of ACI 318-19 (track C2); steel (AISC 360-22) and the other
materials are later tracks. The pack extends `bnbc2020`: every table it does not give (steel,
masonry, timber, the geotechnical tables, the building services, dead load unit weights ...)
is BNBC 2020's, and the report and the design notes cite those tables as BNBC 2020's.

Each table's clause references are named after the code they come from (`tableCodes` in
`pack.json`): the concrete tables "ACI 318-19", the load clauses "ASCE 7-22"; the few rules
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
