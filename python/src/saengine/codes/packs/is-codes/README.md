# Indian Standards (IS): loads

Code pack `is-codes`, built in. Alpha 9 track C7 covers the loads:

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 67 cities with their basic wind speed Vb and seismic zone (II-V as 2-5); default Delhi | IS 875 (Part 3):2015 Annex A, IS 1893 (Part 1):2016 Annex E |
| `zoneCoefficients` | Z = 0.10, 0.16, 0.24, 0.36 | IS 1893 (Part 1):2016 Table 3 |
| `occupancyCategories` | Importance I (1.0, 1.0, 1.2, 1.5) and the wind risk class of k1 (25, 50, 50, 100 years) in SAEngine's four slots | IS 1893 Table 8, IS 875 (Part 3) Table 1 |
| `areaLoads` | Imposed floor and roof loads, concentrated loads, the partition allowance | IS 875 (Part 2):1987 Tables 1-2, Clause 3.1.2 |
| `deadLoads` | Unit weights of brick masonry and cement plaster; 230 / 115 mm walls | IS 875 (Part 1):1987 Table 1 |
| `liveReduction` | Reduction by the number of floors carried, and of beams by area (`method: floorCount`) | IS 875 (Part 2):1987 Clause 3.2 |
| `combinations` | 1.5(D + L), 1.2(D + L ± W/E), 1.5(D ± W/E), 0.9D ± 1.5(W/E); serviceability | IS 875 (Part 5) 8.4, IS 456 Table 18, IS 1893 6.3.4 |
| `seismic` | Soil types I-III, the IS spectrum (Ah = (Z/2)(I/R)(Sa/g), Figures 2(a)/(b)), R of Table 9, Ta, least base shear, Qi by hi², scaling to VB, drift 0.004, irregularities, seismic weight | IS 1893 (Part 1):2016 Clauses 6-7 |
| `wind` | Terrain categories 1-4, Vz = Vb k1 k2 k3 k4, pz = 0.6 Vz², pd = Kd Ka Kc pz ≥ 0.7 pz, wall Cpe of clad buildings | IS 875 (Part 3):2015 Clauses 6-7 |

The methods the pack picks by id (generic SAEngine mechanisms shared with the other packs):
`wind.method: "speedFactors"` (`saengine.fem.wind_speed_factors`, with `wind.speedFactors` and
the wall coefficients `wind.cpByHeight`), `seismic.designSpectrum` (`reducedElastic` with
`factor` 0.5, `longPeriod: "constant"`, `staticPlateau`), `seismic.lateralForce`
(`distribution: "heightSquared"`, `minimumShare` by zone), `periodCoefficients.other.planDimension`
(0.09 h/√d), `seismic.driftAmplification: "designForces"` and `liveReduction.method:
"floorCount"`. A new project starts from `locations.default`, `seismic.defaultSiteClass`,
`seismic.defaultSystem` and `wind.defaultExposure`, each changeable in Project Settings.

## Not covered yet (falls back)

The pack `extends` BNBC 2020: every table not in `covers` comes from BNBC 2020 until the IS
material packs exist (tracks C8 and C9). That is: concrete (`concrete`, `factors`,
`detailing`, `materials`, `slabCoefficients`, `transfer` ...), steel (`steel`, `steelSeismic`,
`steelStability`, `steelSections`), masonry, timber, foundations, site investigation, flood,
fire, the building services, the nonstructural components and serviceability (deflection and
wind drift limits). The report names the pack as "BNBC 2020 (bnbc2020), modified by: Indian
Standards (IS)".

Also not covered inside the loads: the gust factor method (IS 875-3 Clause 10), cladding and
roof pressures, k3 by Annex C (enter k3 as the topographic factor), the 1.5 esi of the design
eccentricity, the RC wall-building period form (b), damping other than 5 %, vertical motion,
IS 16700 tall-building limits.

Every value is listed with its clause in [VERIFY.md](VERIFY.md), for checking against the
printed codes (no code text was available when the pack was written).
