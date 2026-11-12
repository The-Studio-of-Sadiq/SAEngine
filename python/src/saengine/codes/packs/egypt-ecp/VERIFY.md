# egypt-ecp: values to verify against the printed codes

No copy of ECP 201 or ECP 203 was available when this pack was written (alpha 9, track C24,
2026-11-05). Every value was entered from knowledge of the codes and is to be checked by the
owner. **Sure** / **Check** / **Uncertain** / **SAEngine practice** as in the other packs'
lists. Everything the pack does not set is the parent's (`bs8110`, then `bnbc2020`).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| E1 | locations.*.zone | Cairo, Giza, Ismailia 3; Alexandria, Port Said, Mansoura, Tanta, Asyut, Luxor 2; Suez, Aswan 4; Hurghada, Sharm El Sheikh 5A; Nuweiba 5B | ECP 201 Table 8.1, Figure 8.1 | Towns' zones | Uncertain |
| E2 | locations.*.windSpeed | 22 inland, 25 coast (hourly mean, BS 6399-2) | ECP 201 Ch 6 | Wind | Placeholder (ECP 201's map and method not set) |
| E3 | zoneCoefficients.zones | 0.10, 0.125, 0.15, 0.20, 0.25, 0.30 | ECP 201 Table 8.1 | ag | Check |
| E4 | seismic.spectra | Type 1: A 1.0 / 0.05 / 0.25 / 1.2, B 1.35 / 0.05 / 0.25 / 1.2, C 1.5 / 0.10 / 0.25 / 1.2, D 1.8 / 0.10 / 0.30 / 1.2; Type 2: A 1.0 / 0.15 / 0.4 / 2.0, B 1.2 / 0.15 / 0.5 / 2.0, C 1.15 / 0.20 / 0.6 / 2.0, D 1.35 / 0.20 / 0.8 / 2.0 (S / TB / TC / TD) | ECP 201 Tables 8.2, 8.3 | Soil parameters | Uncertain (the numbers are EN 1998-1's; which type applies where is not known: Type 2 taken) |
| E5 | seismic.designSpectrum | behaviourFactor, plateau 2.5, β 0.2 | ECP 201 8.3.3 | Design spectrum | Check |
| E6 | seismic.systems.*.R | RC frames 7 (sufficient ductility), 5 (limited); RC walls 5; dual 6; steel moment frames 7; concentric braces 4; eccentric braces 6 | ECP 201 Table 8.10 | Response modification factor | Uncertain |
| E7 | seismic.systems.*.Cd / Omega0 | Cd = R; Ω0 1.2-1.3 | ECP 201 8.6 | Displacement factor, overstrength | SAEngine practice |
| E8 | seismic.lateralForce | λ = 0.85 (T ≤ 2 TC, > 2 storeys), linear distribution | ECP 201 8.5.1, 8.5.2 | Base shear correction | Check |
| E9 | seismic.periodCoefficients | 0.075, 0.085, 0.075, 0.05 × H^0.75 | ECP 201 8.5.1 | Period | Check |
| E10 | seismic.allowableDrift / driftLimits | dr ν ≤ 0.005 h (ν 0.5 / 0.4), 0.0075 h ductile finishes | ECP 201 8.6 | Drift | Uncertain (EN 1998-1's form taken) |
| E11 | seismic.liveShare | 0.25 | ECP 201 8.4 | Live share in W | Check |
| E12 | seismic.designCategories | zone 1 B, 2-3 C, 4-5B D | - | SAEngine's category for the detailing | SAEngine practice |
| E13 | occupancyCategories | γI 0.8, 1.0, 1.2, 1.4 | ECP 201 Table 8.9 | Importance | Check |
| E14 | combinations.strength | 1.4D + 1.6L; 1.12D + 1.28L + 1.28W; 0.9D + 1.3W; 1.12D + 0.5L + E; 0.9D + E | ECP 203 3.2.1 | Combinations | Check (α = 0.5 taken for every use) |
| E15 | concreteMethods.ultimate | γs 1.15, 0.67 fcu/1.5 over 0.8 c, Ec 4400 √fcu, fctr 0.6 √fcu, emin 0.05 t ≥ 20 mm, Pu 0.35 fcu Ac + 0.67 fy As, c ≤ 0.42 d | ECP 203 4.2.1, 4.3 | Ultimate | Check (the neutral axis limit at fy 400) |
| E16 | concreteMethods.shear | τc = 0.12 √(fcu/1.5) (half of qcu), qmax 0.7 √(fcu/1.5) ≤ 4, least 0.35 MPa, s ≤ d/2 ≤ 200 mm | ECP 203 4.2.2 | Shear | Check (members without stirrups held to half qcu: on the safe side) |
| E17 | concrete.barDiameters | Ø8-Ø32 | ES 262 | Bars | SAEngine practice |
| E18 | concrete (other areas) | the parent's BS 8110 | ECP 203 | Punching, deflection, cracks, cover, anchorage | Uncertain (not ECP 203's) |
