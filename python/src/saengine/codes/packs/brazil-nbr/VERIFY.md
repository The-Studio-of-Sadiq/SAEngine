# brazil-nbr: values to verify against the printed standards

No copy of NBR 15421, 6123, 6118, 8681, 6120 or 8800 was available when this pack was written
(alpha 9, track C24, 2026-11-05). Every value was entered from knowledge of the standards and is
to be checked by the owner. **Sure** / **Check** / **Uncertain** / **SAEngine practice** as in
the other packs' lists. Everything the pack does not set is the base pack's (`aci318-asce7-22`).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| B1 | locations.*.ss / s1 | ag 0.025 (São Paulo, Rio de Janeiro, Brasília, Belo Horizonte, Curitiba, Porto Alegre, Florianópolis, Salvador), 0.05 (Recife, Fortaleza, Manaus), 0.10 (Natal), 0.15 (Rio Branco, Cruzeiro do Sul) as SS = 2.5 ag, S1 = ag | NBR 15421 Figure 1, Table 1 | Towns' ag (the zone's upper value) | Uncertain |
| B2 | locations.*.windSpeed | V0 São Paulo 40, Rio de Janeiro 35, Brasília 35, Belo Horizonte 32, Curitiba 42, Porto Alegre 45, Florianópolis 43, Salvador 30, Recife 30, Fortaleza 30, Natal 30, Manaus 30, Rio Branco 30, Cruzeiro do Sul 30 m/s | NBR 6123 Figure 1 | Basic wind speed | Uncertain |
| B3 | seismic.siteClasses | A > 1500, B 760-1500, C 370-760, D 180-370, E < 180 m/s, F | NBR 15421 Table 2 | Site classes | Check |
| B4 | seismic.designSpectrum.siteCoefficients.fa | Ca A 0.8, B 1.0, C 1.2, D 1.6 / 1.5, E 2.5 / 2.1 at ag ≤ 0.10 / 0.15 | NBR 15421 Table 3 | Ca | Check |
| B5 | seismic.designSpectrum.siteCoefficients.fv | Cv A 0.8, B 1.0, C 1.7, D 2.4 / 2.2, E 3.5 / 3.4 | NBR 15421 Table 3 | Cv | Check |
| B6 | seismic.designSpectrum.designShare | 1.0 | NBR 15421 6.3 | No 2/3 | Sure |
| B7 | seismic.designSpectrum (t0Share, rampStart) | the base pack's 0.2, 0.4 | NBR 15421 6.3 Eq (1) | Ramp to 0.08 Cv/Ca from ags0 | Sure (the same shape) |
| B8 | seismic.designSpectrum.sdsBands / sd1Bands, designCategories | 0.125 / 0.25 and 0.05 / 0.10; B, B, C | NBR 15421 7.3.1, Table 4 | Seismic categories | SAEngine practice (category A analysed as B) |
| B9 | seismic.designSpectrum.csLimits | at least 0.01 | NBR 15421 9.1 | Least Cs | Check |
| B10 | seismic.designSpectrum.periodUpper | Cup 1.7 / 1.6 / 1.5 at SD1 0.05 / 0.10 / 0.15 | NBR 15421 9.2, Table 9 | Period cap | Check (by zone in NBR, here by SD1) |
| B11 | wind.speedFactors.heightFactors | S2 = b Fr (z/10)^p, class B: I 1.10 / 0.065, II 1.00 / 0.09, III 0.94 / 0.105, IV 0.86 / 0.125, V 0.74 / 0.16; Fr 0.98 | NBR 6123 5.3, Table 21 | Terrain and height factor | Check (classes A, C not set) |
| B12 | wind.speedFactors.airFactor | 0.613 | NBR 6123 4.2 | q = 0.613 Vk² | Sure |
| B13 | wind.cpWindward / cpLeeward | +0.8; -0.5, -0.3, -0.2 by L/B | NBR 6123 Figure 4 (Ca) | Net drag of closed buildings | SAEngine practice |
| B14 | occupancyCategories.*.windImportance | S3 0.95, 1.00, 1.00, 1.10 | NBR 6123 Table 3 | Statistical factor | Check |
| B15 | occupancyCategories.*.seismicImportance | 1.0, 1.0, 1.25, 1.5 | NBR 15421 Table 3 | Importance factor | Check |
| B16 | combinations.strength | 1.4G + 1.4Q; 1.4G + 1.4W + 0.7Q; 1.4G + 1.4Q + 0.84W; 1.0G + 1.4W; 1.2G + E + 0.3Q; 1.0G + E | NBR 8681 5.1.3 | Combinations | Check (the seismic ones Uncertain) |
| B17 | combinations.service | G + 0.4Q, G + 0.3Q, G + 0.3W | NBR 6118 11.8.3 | Service combinations | Check |
| B18 | concreteMethods.ultimate | γc 1.4, γs 1.15, αc 0.85, λ 0.8, εcu 3.5 ‰, Es 210 GPa | NBR 6118 12.4.1, 17.2.2, 8.3.5 | Ultimate | Sure |
| B19 | concreteMethods.ultimate.neutralAxisLimit | δ ≥ 0.44 + 1.25 x/d (x/d ≤ 0.45) | NBR 6118 14.6.4.3 | Ductility limit | Check |
| B20 | concreteMethods.shear | τc = 0.09 fck^(2/3); τmax = 0.27 (1 - fck/250) fck/1.4; fy ≤ 450 (0.9 d × 435 MPa); least 0.50 MPa; s ≤ 0.6 d ≤ 300 mm | NBR 6118 17.4.2.2, 17.4.1.1.1, 18.3.3.2 | Shear model I | Check (the least stirrups taken at C30) |
| B21 | concreteMethods.ultimate.eccentricity | e0 = h/20 ≥ 24 mm | NBR 6118 11.3.3.4.3 (15 mm + 0.03 h) | Least eccentricity | SAEngine practice (within 5 mm) |
| B22 | concrete (other areas) | the base pack's ACI 318-19 | NBR 6118 | Torsion, punching, slenderness, cover, anchorage | Uncertain (not NBR 6118's) |
| B23 | concrete.barDiameters / barNames | Ø5, Ø6,3, Ø8, Ø10, Ø12,5, Ø16, Ø20, Ø25, Ø32, Ø40 | NBR 7480 | Bars | Sure |
| B24 | concrete.modulus.normal | 4760 √fck | NBR 6118 8.2.8 | Ecs for the analysis | SAEngine practice |
| B25 | steel | the base pack's AISC 360-22 | NBR 8800 | Steel design | Check (γa1 1.10, γa2 1.35 against φ 0.90, 0.75) |

## Column splice hoops (pack follow-up 2026-11-09)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| S1 | detailing.special.columnSplice* (inherited) | the ACI 318-19 pack's: ties over the lap splices of special moment frame columns at the end zones' spacing (least dimension / 4, 6 db, so) | NBR 6118 / NBR 15421 (no special moment frame rule of their own) | Check |
