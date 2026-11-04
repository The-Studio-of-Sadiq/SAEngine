# ACI 318-19 + ASCE 7-22 code pack (`aci318-asce7-22`)

The built-in US pack. This version covers the **loads** of ASCE/SEI 7-22 (alpha 9, track C1)
and **structural concrete** of ACI 318-19 (track C2), **structural steel** of AISC 360-22 and
AISC 341-22 and the strength design of **masonry** of TMS 402-22 (track C3), and (track C3b)
**timber** by the NDS 2018, **masonry** by allowable stresses (TMS 402-22 Chapter 8, the
default masonry method), the rest of AISC 360-22 (built-up members, stability bracing,
ponding, tension field stiffeners, HSS connections, fatigue) and of AISC 341-22 (moment frame
connections and panel zones, links, BRBF, SPSW, composite systems) and the steel systems of
the New Building generator. The pack extends `bnbc2020`: every table or value it does not give
(the masonry empirical and seismic rules, the geotechnical tables, the building services, dead
load unit weights ...) is BNBC 2020's, and the report and the design notes cite those as BNBC
2020's.

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

### Timber, masonry ASD, the steel remainder and the generator (C3b)

| File | What it holds | Clauses |
| --- | --- | --- |
| `timber.json` | method `referenceDesign`: reference design values (psi) of Douglas Fir-Larch, Hem-Fir, Spruce-Pine-Fir and two glulam stress classes; CD, CM, Ct, Ci, CF, Cfu, Cr, CV, CL, CP, Cb; LRFD KF, φ, λ; dowel-type fasteners (Fe, Rd, Fyb, Cg, CΔ); the deflection creep factor | NDS 2018 Ch 2-5, 11-12, App N; Supplement Tables 4A, 4D, 5A |
| `masonry.json` `allowable` | Fa by h/r (slender members), Fb 1/3 and 0.45 f'm, Ft, Fv with the axial stress, Fv = Fvm + Fvs (`additive`), Fs by grade (`steps`); no one-third increase, no halving; Em by the units | TMS 402-22 Ch 8, Sec 4.2.2 |
| `steel.json` | built-up members by Ki (`builtUp.method = ki`), stability bracing (`torsionalMomentForm = share`), ponding references, tension field stiffeners by inertia (`stiffenerMethod = inertia`), Chapter K φ and references | AISC 360-22 E6, App 2, App 6, G2.3, Ch K |
| `fatigue.json` | the stress categories' Cf and FTH, the design stress range | AISC 360-22 App 3 |
| `steelSeismic.json` | Cpr of the expected moment (`hingeFactorMethod = cpr`), beam bracing by Ry Fy (`beamBracingExpected`), SPSW Ic, composite concrete limits; the AISC 341-22 section of every rule | AISC 341-22 Ch A-K, AISC 358 |
| `seismic.json` `generatorSystems` | the New Building generator's steel systems | ASCE 7-22 Table 12.2-1 |

Timber members are designed by `saengine.design.timber.reference` when the pack's timber method
is `referenceDesign`: ASD by default (the allowable stress combinations, CD), LRFD with the
project override `timber.reference.format = LRFD` (the strength combinations, KF φ λ). The
material's Species (a reference species id or name), Reference grade, location (wet or outside:
wet service), incising and service temperature, and the member type's restraint spacing and
repetitive option, set the factors. Bolted and nailed joints are checked by the yield limit
equations; split rings and disc-dowels are flagged not covered under this method.

### Cold-formed members, steel in fire, bracing rows (C12, steel half)

| File | What it holds | Clauses |
| --- | --- | --- |
| `coldFormed.json` | lipped C and Z members (04 Objects profiles `C` and `Z`): Winter's effective widths, distortional buckling by the direct strength curves, compression, flexure with lateral-torsional buckling, web shear, the linear interaction; LRFD φ | AISI S100-16 1.1, B4, D-H |
| `steelFire.json` | steel members at their fire rating: Table A-4.2.1 retention factors, the steel temperature by the lumped heat capacity (SAEngine practice), the critical temperature where ky = μ0, compression by Eq A-4-9 | AISC 360-22 Appendix 4 |
| `steel.json` `bracing.rows` | the Appendix 6 brace strength and stiffness listed as flagged rows of the members (they were notes) | AISC 360-22 Appendix 6 |

The protection of the steel (thickness, conductivity, density, specific heat; default none) is set under Code Values (`steelFire.protection`). Values: VERIFY.md rows S1-S18.

The New Building wizard's "Steel moment frame" and "Steel braced frame" generate steel columns
(HEB), beams (IPE), X braces (SHS, BIM inclined members) and RC slabs, with the first system of
`generatorSystems` the Seismic Design Category and height permit (steel not specifically
detailed in B and C, else OMF, IMF, SMF or OCBF, SCBF), every member within that system's
width-thickness limits; Design mode then checks them under the pack (LRFD, or ASD by
`steel.designMethod`).

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
