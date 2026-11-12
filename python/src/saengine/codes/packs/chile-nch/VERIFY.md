# chile-nch: values to verify against the printed standards

No copy of NCh 433, DS 61, NCh 430, DS 60 or NCh 3171 was available when this pack was written
(alpha 9, track C24, 2026-11-05). Every value was entered from knowledge of the standards and is
to be checked by the owner. **Sure** / **Check** / **Uncertain** / **SAEngine practice** as in
the other packs' lists. Everything the pack does not set is the base pack's (`aci318-asce7-22`).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| C1 | locations.*.zone | Arica, Iquique, Antofagasta, La Serena, Valparaíso, Viña del Mar, Concepción, Valdivia 3; Calama, Santiago, Rancagua, Talca, Temuco, Puerto Montt 2 | NCh 433 Table 4.1, Figure 4.1 | Towns' zones | Uncertain (Santiago 2 and the coast 3: Check) |
| C2 | locations.*.windSpeed | 35 m/s | NCh 432 | Wind speed | Placeholder |
| C3 | zoneCoefficients.zones | 0.20, 0.30, 0.40 | NCh 433 Table 6.2 | A0 / g | Sure |
| C4 | seismic.siteClasses (S / T0 / T' / n / p) | A 0.90 / 0.15 / 0.20 / 1.00 / 2.0; B 1.00 / 0.30 / 0.35 / 1.33 / 1.5; C 1.05 / 0.40 / 0.45 / 1.40 / 1.6; D 1.20 / 0.75 / 0.85 / 1.80 / 1.0; E 1.30 / 1.20 / 1.35 / 1.80 / 1.0 | DS 61 Table 6.3 | Soil parameters | Check |
| C5 | seismic.siteClasses.*.vs30 | A > 900, B 500-900, C 350-500, D 180-350, E < 180 m/s | DS 61 Table 4.2 | Soil types | Check (DS 61 classifies by vs30 and other properties) |
| C6 | seismic.siteClasses.*.shape | α = (1 + 4.5 (T/T0)^p) / (1 + (T/T0)^3) | NCh 433 Eq 6-10 | Spectral amplification | Sure |
| C7 | seismic.designSpectrum.shapeFactors.ratioShare / ratioPeriods | 0.10; T0 of the soil type | NCh 433 Mod.2009 Eq 6-11 | R* = 1 + T*/(0.10 T0 + T*/R0) | Sure (taken at each ordinate's period: SAEngine practice) |
| C8 | seismic.systems.*.R | R0 = 11 RC walls, frames, dual and steel SMF; 6 steel concentric braces; 10 steel EBF; 4 confined masonry (R 7, 7, 7, 7, 5.5, 6, 4) | NCh 433 Table 5.1 | R0 (R in the row name) | Uncertain (EBF and the braces' R0) |
| C9 | seismic.designSpectrum.shapeFactors.leastSoilShare | 1/6 | NCh 433 6.2.3.1.1, 6.3.7.1 | Cmin = A0 S / 6g | Sure |
| C10 | seismic.designSpectrum.shapeFactors.capByDuctility | R0 4 → 0.55, 6 → 0.40, 11 → 0.35 | NCh 433 Table 6.4 (R 2 0.90, 3 0.60, 4 0.55, 5.5 0.40, 6 0.35, 7 0.35) | Cmax by the system | Uncertain (Table 6.4 is by R: written here by the R0 of the systems with that R, linear between) |
| C11 | seismic.allowableDrift, driftAmplification | 0.002 under the design forces | NCh 433 5.9.2 | Drift at the centre of mass | Sure (5.9.3, 0.001 h more at any point: not checked) |
| C12 | seismic.systems.*.Cd / Omega0 | Cd = R; Ω0 the ASCE 7 values | NCh 433 5.10 | Separation, overstrength | SAEngine practice |
| C13 | seismic.periodCoefficients | ASCE 7-22 Table 12.8-2 | - | Approximate period (NCh 433 uses T* from the analysis) | SAEngine practice |
| C14 | seismic (static method) | the spectrum at the period (C = S A0 α / (R*/I)) | NCh 433 6.2.3 | NCh 433's static C = 2.75 S A0 (T'/T*)^n / (g R) not built | SAEngine practice (soil B, T* 0.5 s, A0 0.4 g, R 7: 0.098 by NCh 433, 0.099 here) |
| C15 | seismic.liveShare | 0.25 | NCh 433 5.5.1 | Live share in P (50 % for many occupants) | Check |
| C16 | seismic.designCategories, requiredDetailing | D, special everywhere | NCh 430 Chapter 21 | Earthquake detailing | SAEngine practice |
| C17 | detailing.walls.driftMin / driftFactor | 0.007 / 1.0 | DS 60 21.9.6.2 | Boundary element trigger | Check (εc ≤ 0.008, the least thickness and DS 60's confinement rules not set) |
| C18 | combinations.strength | 1.4D; 1.2D + 1.6L + 0.5Lr; 1.2D + 1.6Lr + L; 1.2D + 1.6W + L + 0.5Lr; 1.2D + 1.4E + L + 0.2S; 0.9D + 1.6W; 0.9D + 1.4E | NCh 3171:2010 4.3 | Strength combinations | Check (1.4 on E: Check) |
| C19 | combinations.allowable | the ASCE 7 form with E × 1.0 | NCh 3171:2010 4.2 | Allowable stress combinations | Uncertain |
| C20 | occupancyCategories | I = 0.6, 1.0, 1.2, 1.2 | NCh 433 Table 6.1 | Importance factor | Sure |
| C21 | concrete.barDiameters | Ø8-Ø36 | NCh 204 | Bars | Check |
| C22 | concrete rules | the base pack's ACI 318-19 (φ, shear, development) | NCh 430:2008 (ACI 318-08) | Concrete design | Check (ACI 318-08 → 318-19 differences, e.g. the size effect in one-way shear, apply) |
