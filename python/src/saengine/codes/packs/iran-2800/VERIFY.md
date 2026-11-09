# iran-2800: values to verify against the printed standard and regulations

No copy of Standard 2800 or the INBC parts was available when this pack was written (alpha 9,
track C24, 2026-11-05). Every value was entered from knowledge of the codes and is to be checked
by the owner. **Sure** / **Check** / **Uncertain** / **SAEngine practice** as in the other packs'
lists. Everything the pack does not set is the base pack's (`aci318-asce7-22`).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| R1 | locations.*.zone | Tehran, Karaj, Tabriz, Bandar Abbas 1; Mashhad, Shiraz, Qom, Kermanshah, Kerman, Rasht 2; Isfahan, Ahvaz, Yazd, Zahedan 3 | Standard 2800 Appendix 1 | The towns' relative seismic hazard | Uncertain |
| R2 | locations.*.windSpeed | 40 m/s | INBC Part 6 | Basic wind speed | Placeholder (replace from INBC Part 6; the base pack's ASCE 7 method takes a 3-second gust) |
| R3 | zoneCoefficients.zones | 0.35, 0.30, 0.25, 0.20 | Standard 2800 Table 2-1 | Design base acceleration A | Sure |
| R4 | seismic.siteClasses (zones 1-2) | T0 / Ts / S0 / S: I 0.1 / 0.4 / 1.0 / 1.5; II 0.1 / 0.5 / 1.0 / 1.5; III 0.15 / 0.7 / 1.1 / 1.75; IV 0.15 / 1.0 / 1.1 / 1.75 | Standard 2800 Table 2-2 | Soil parameters, very high and high hazard | Check |
| R5 | seismic.siteClasses (zones 3-4) | as R4 but IVL S0 1.3, S 2.25 | Standard 2800 Table 2-2 | Soil parameters, moderate and low hazard | Uncertain (IVL) |
| R6 | seismic.siteClasses.*.shape | B1 = S0 + (S - S0 + 1) T/T0, S + 1, (S + 1) Ts/T; N = 1 + 0.7 (T - Ts)/(4 - Ts) to 1.7 (zones 1-2), 0.4 and 1.4 (zones 3-4) | Standard 2800 Eqs 2-1 to 2-4 | B = B1 N as branches | Check |
| R7 | seismic.siteClasses.*.vs30 | > 750, 375-750, 175-375, < 175 m/s | Standard 2800 Table 2-3 | Soil type by vs | Check |
| R8 | seismic.systems | RC SMF 7.5 / 3 / 5.5; IMF 5 / 3 / 4.5; OMF 3.5 / 3 / 3; special walls (building frame) 6 / 2.5 / 5; dual 7.5 / 2.5 / 6; steel SMF 7.5 / 3 / 5.5; SCBF 5.5 / 2 / 5; EBF 7 / 2 / 4 (Ru / Ω0 / Cd); height limits IMF 35 m, OMF 15 m (zones 3-4 only), walls and braces 50 m | Standard 2800 Table 3-4 | Behaviour factors | Uncertain |
| R9 | seismic.designSpectrum.shapeFactors.leastZShare | 0.12 | Standard 2800 3-3-1 | C ≥ 0.12 A I | Check |
| R10 | seismic.periodCoefficients | 0.05 H^0.9 RC MRF; 0.08 H^0.75 steel MRF; 0.05 H^0.75 others | Standard 2800 3-3-6 | Empirical period | Check |
| R11 | seismic.allowableDrift | 0.020 (0.025 below T 0.7 s, not set) | Standard 2800 3-5 | Drift with Cd Δeu | Check |
| R12 | seismic.designCategories | zones 1-2 D, 3-4 C | - | SAEngine's category for the detailing | SAEngine practice |
| R13 | seismic.liveShare | 0.2 | Standard 2800 3-3-2 | Live share in W | Check |
| R14 | seismic.minimumScale | 0.9 | Standard 2800 3-4-2-3 | Modal / static base shear | Uncertain |
| R15 | seismic.lateralForce | k = 0.5 T + 0.75 (1-2), no top force | Standard 2800 (4th ed.) 3-3-5 | Vertical distribution | Check |
| R16 | seismic.verticalFactor | 2/3 | Standard 2800 3-3-10 | Vertical acceleration | Check |
| R17 | seismic.designSpectrum.staticPlateau | true | - | Plateau below T0 in the static method | SAEngine practice (on the safe side) |
| R18 | occupancyCategories | 0.8, 1.0, 1.2, 1.4 | Standard 2800 Table 3-1 | Importance factor | Sure (the uses of each group: check) |
| R19 | concreteMethods.ultimate.gammaC / gammaS | 1/0.65, 1/0.85 | INBC Part 9 | Material resistance factors | Check (clause numbers not given: no copy) |
| R20 | concreteMethods.ultimate.relations | α1 = 0.85 - 0.0015 fc ≥ 0.67, β1 = 0.97 - 0.0025 fc ≥ 0.67, εcu 0.0035, Ec = 5000 √fc | INBC Part 9 | Stress block | Check (Ec uncertain) |
| R21 | concreteMethods.ultimate.axialShares, neutralAxisLimit | 0.80 Pro; c/d ≤ 700/(700 + fy) at fy 400 | INBC Part 9 | Axial cap, ductility limit | Check |
| R22 | concrete shear and detailing | the base pack's ACI 318-19 with φ 0.75 | INBC Part 9 | φVc 0.1275 √fc bw d vs 0.13 √fc bw d | SAEngine practice (within 2 %) |
| R23 | concrete.barDiameters | Φ8-Φ32 | ISIRI 3132 | Bars | SAEngine practice |
| R24 | combinations, areaLoads | the base pack's ASCE 7-22 | INBC Part 6 | Loads | Uncertain (INBC Part 6 follows ASCE 7 closely: check the factors and the live loads) |
| R25 | steel | the base pack's AISC 360-22 | INBC Part 10 | Steel design | Check |

## Column splice hoops (pack follow-up 2026-11-09)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| S1 | detailing.special.columnSplice* (inherited) | the ACI 318-19 pack's: ties over the lap splices of special moment frame columns at the end zones' spacing (least dimension / 4, 6 db, so) | MNR Part 9 (column lap splices) | Check (not confirmed) |
