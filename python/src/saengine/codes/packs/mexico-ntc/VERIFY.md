# mexico-ntc: values to verify against the printed NTC-CDMX and the CFE wind manual

No copy of the norms was available when this pack was written (alpha 9, track C17,
2026-11-04). Every value was entered from knowledge of the norms and is to be checked by the
owner against the printed editions. **Sure**: well-known value, low risk. **Check**: believed
right, confirm the number or the row. **Uncertain**: the value or its reading may be wrong, or
it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack does not set
is the US pack's (`aci318-asce7-22`, its VERIFY.md).

## Site and importance

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| M1 | locations.cdmx.windSpeed | 32.8 m/s (118 km/h) | CFE Viento 2008, VR of Mexico City, 50 years | Regional speed | Uncertain (from memory; replace with the manual's map or table) |
| M2 | locations.cdmx.pressureFactor | 0.781 = G × 0.610 / 0.613, G = 0.392 × 579 / (273 + 16) = 0.785 | CFE Viento 4.2.5 | Barometric correction of qz | Check (Ω from the standard atmosphere at 2240 m, τ 16 °C: SAEngine values) |
| M3 | zoneCoefficients | Z = 1.0 | - | Marks the city as seismic | SAEngine practice |
| M4 | occupancyCategories.*.seismicImportance | B 1.0, A 1.5 | NTC-Sismo 3 (Group A × 1.5) | | Sure |
| M5 | occupancyCategories.*.windImportance | B 1.0, A 1.21 | CFE Viento 4.1 (200 years for A) | | Uncertain (≈ 1.1² as SAEngine estimate) |
| M6 | categories ids | I = B2, II = B1, III = A2, IV = A1 | Reglamento Art. 139 | SAEngine's ids | SAEngine practice |

## Loads and combinations (NTC-Criterios 2017)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| M7 | areaLoads.uses | habitación 1.9; oficinas 2.5; aulas 2.5; comunicación 3.5; reunión con asientos 3.5, sin asientos 4.5; comercios 3.5; estacionamientos 2.5; azoteas <= 5 % 1.0 kPa (Wm) | Tabla 6.1.1 | | Check (every row; 2017 edition) |
| M8 | combinations.strength 1 | 1.3D + 1.5L + 1.5Lr | 3.4(a) | Group B | Check (2017 factors; Group A 1.5 / 1.7 not formed) |
| M9 | combinations.strength 2W, 2E | 1.1(D + L + W), 1.1(D + L + E) | 2.3(b), 3.4(b) | Accidental | Sure (1.1); L at Wm in place of Wa: SAEngine practice, on the safe side |
| M10 | combinations.strength 3W, 3E | 0.9D + 1.1W, 0.9D + 1.1E | 3.4(c) | Favourable dead load | Check |
| M11 | combinations.service | D + L; D + 0.4L; D + 0.4L + 0.7W | 4, 6.1 | | SAEngine practice |
| M12 | combinations.temperature | 1.1D ± 1.1T + 1.1L | 2.3(b) | | Uncertain |
| M13 | seismic.liveShare | 0.7 (Wa ≈ 0.7 Wm) | 6.1 | Seismic weight | SAEngine practice |

## Seismic (NTC-Sismo)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| M14 | ductility.sites | I: c 0.16, a0 0.04, Ta 0.2, Tb 1.35, r 1.0; II: 0.32, 0.08, 0.2, 1.35, 1.33; IIIa: 0.40, 0.10, 0.53, 1.8, 2.0; IIIb: 0.45, 0.11, 0.85, 3.0, 2.0; IIIc: 0.40, 0.10, 1.25, 4.2, 2.0; IIId: 0.30, 0.10, 0.85, 4.2, 2.0 | 2004 Tabla 3.1 | Zone spectra | Check (well known; the 2017 edition replaced them by site-specific spectra) |
| M15 | spectrum form | a0 + (c - a0) T/Ta; c; c (Tb/T)^r | 2004 Sec 3 | | Sure |
| M16 | reduction | Q' = 1 + (Q - 1) T/Ta below Ta, Q beyond; R = 1 | 2004 Sec 4 | | Sure |
| M17 | site-specific form | a beyond Tb = c p (Tb/T)², p = k + (1 - k)(Tb/T)²; Q' with √(β/k) (√(β p/k) beyond Tb); R = k1 R0 + k2, k2 = 0.5 [1 - (T/Ta)^½] | 2017 Secs 3.1-3.5 | Used where k is given | Uncertain (the form as remembered) |
| M18 | ductility.overstrength | R0: Q 1 → 1.0, 2 → 1.75, >= 3 → 2.0 | 2017 Sec 3.5 | | Uncertain |
| M19 | ductility.regularityFactor | 1.0 (regular) | 2004 Sec 6.4 (0.9, 0.8, 0.7 irregular) | | Sure (the factors); the project sets it |
| M20 | systems Q | concrete and steel marcos dúctiles 4; frames 3 and 2; walls 3 / 2; dual 3; braced 3 / 2; EBF 4; masonry 2 / 1.5; other 1 | Sec 5 | | Check (the rows' conditions) |
| M21 | systems Omega0 | 2.0 (Q >= 3), 1.75 (Q 2), 1.5, 1.0 | 2017 R0 | Em = Ω0 E | SAEngine practice |
| M22 | systems Cd, driftAmplification | Cd = Q, the drifts of the reduced forces × Q | Sec 1.8 | | Check |
| M23 | allowableDrift, driftLimits | 0.006 attached, 0.012 separated | 2004 Sec 1.8 | | Check (2017 limits by system not entered) |
| M24 | designEccentricity, accidentalEccentricity | e = 1.5 es + 0.1 b, es - 0.1 b | Sec 8.5 | | Check |
| M25 | lateralForce | Fi ∝ Wi hi | Sec 8.1 | | Sure (8.2 modified distribution not applied) |
| M26 | minimumScale | 0.8 | Sec 9.3 | | Check |
| M27 | orthogonalShare | 0.3 | Sec 8.7 | | Sure |
| M28 | stability | second-order effects above θ = 0.08 | Sec 8.6 | | Check |
| M29 | periodCoefficients | ASCE 7-22 Table 12.8-2 values; T <= 1.4 Ta | - | NTC has no Ta | SAEngine practice |
| M30 | siteClasses.S | a0 of the zone (with pgaFactor 1) | - | PGA | SAEngine practice |
| M31 | designCategories | I B, II C, III D; Group A one up | - | Letters for SAEngine's generator | SAEngine practice |
| M32 | irregularities, verticalFactor | not checked; 0 | Sec 6 | | Not covered |

## Wind (CFE Viento 2008)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| M33 | wind.exposures | (α, c): cat1 (0.099, 1.137), cat2 (0.128, 1.000), cat3 (0.156, 0.881), cat4 (0.170, 0.815); Frz = c below 10 m; Kz = Frz² | Tabla 4.2.3 | | Check (2008 values; δ not applied) |
| M34 | wind.gust | 1.0 | 4.3 | Rigid structures | Check |
| M35 | wind.directionality, topographic | 1.0, 1.0 (FT not covered) | 4.2.4 | | SAEngine practice |
| M36 | wind.cpWindward, cpLeeward | the parent's (0.8; -0.5 / -0.3 / -0.2 by d/b) | Tablas 4.3.1, 4.3.2 | | Check |

## Concrete and steel

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| M37 | factors.phi | FR 0.9 flexure, 0.75 shear, 0.65 tied / 0.75 spiral, 0.7 bearing | NTC-Concreto 3.7 | | Check (the strain transition is the parent's ACI form) |
| M38 | concrete.barDiameters | 7.9, 9.5, 12.7, 15.9, 19.1, 25.4, 31.8, 38.1 mm (#2.5-#12) | NMX-B-506 | | Sure |
| M39 | concrete design | the parent's ACI 318-19 (β1 = 1.05 - f'c/140 the same) | NTC-Concreto | | Check (the NTC shear equations not entered) |
| M40 | steel.memberMethods.columnCurve | χ = (1 + λ^2n)^(-1/n), n = 1.4 | NTC-Acero 5.2 | | Check (n by section type) |
| M41 | steel.memberMethods.lateralTorsional | 1.15 FR Mp (1 - 0.28 Mp/Mu) <= FR Mp where Mu > 2/3 Mp, else FR Mu | NTC-Acero 6.3 | | Check |
| M42 | steel.phi | FR 0.9 / 0.75 (the parent's) | NTC-Acero 3.2 | | Check |

## Column splice hoops (pack follow-up 2026-11-09)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| S1 | detailing.special.columnSplice* (inherited) | the ACI 318-19 pack's: ties over the lap splices of special moment frame columns at the end zones' spacing (least dimension / 4, 6 db, so) | NTC-Concreto (ductile columns, lap splices) | Check (the NTC rule not entered) |
