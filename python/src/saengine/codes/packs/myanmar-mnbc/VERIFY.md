# myanmar-mnbc: values to verify against the printed MNBC 2020

No copy of MNBC 2020 was available when this pack was written (alpha 9, track C23,
2026-11-04). Every value was entered from knowledge of the code and of the ASCE 7 form it
follows, and is to be checked by the owner against the printed edition. **Sure**: well-known
value, low risk. **Check**: believed right, confirm the number or the row. **Uncertain**: the
value or its reading may be wrong, or it is an SAEngine form of the rule; SAEngine's choice is
stated. Everything the pack does not set is the US pack's (`aci318-asce7-22`, its VERIFY.md).

## Seismic

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N1 | locations.*.zone | Yangon 3, Mandalay 5, Nay Pyi Taw 4, Sagaing 5, Bago 5, Taungoo 4, Myitkyina 4, Monywa 4, Nyaung-U 4, Magway 3, Taunggyi 3, Lashio 3, Sittwe 4, Kyaukphyu 4, Pathein 2, Mawlamyine 2, Hpa-An 2, Dawei 2, Myeik 1 | MNBC 2020 seismic zone map | The town's zone (for information) | Uncertain (from memory of the zone map: check every town) |
| N2 | locations.*.ss, s1 | zone 5: 1.25 / 0.5; zone 4: 1.0 / 0.4; zone 3: 0.75 / 0.3; zone 2: 0.4 / 0.15; zone 1: 0.25 / 0.1 g | MNBC 2020 town table of SS, S1 | Mapped MCE accelerations at 0.2 s and 1 s | Uncertain (SAEngine estimate from the zone, SS ≈ 2.5 × and S1 ≈ 1.0 × the zone's upper PGA; not the MNBC table: replace with the town's values) |
| N3 | zoneCoefficients.zones | 1: 0.1, 2: 0.15, 3: 0.3, 4: 0.4, 5: 0.5 g | MNBC zone map | Upper PGA of each zone, for information (not used by the spectrum) | Uncertain |
| N4 | seismic.designSpectrum.siteCoefficients.fa | SS 0.25 / 0.5 / 0.75 / 1.0 / 1.25: A 0.8; B 1.0; C 1.2, 1.2, 1.1, 1.0, 1.0; D 1.6, 1.4, 1.2, 1.1, 1.0; E 2.5, 1.7, 1.2, 0.9, 0.9 | ASCE 7-05 Table 11.4-1 (as MNBC adopts) | Fa | Sure (the ASCE 7-05 table); Check that MNBC adopts it |
| N5 | seismic.designSpectrum.siteCoefficients.fv | S1 0.1 / 0.2 / 0.3 / 0.4 / 0.5: A 0.8; B 1.0; C 1.7, 1.6, 1.5, 1.4, 1.3; D 2.4, 2.0, 1.8, 1.6, 1.5; E 3.5, 3.2, 2.8, 2.4, 2.4 | ASCE 7-05 Table 11.4-2 | Fv | Sure (the ASCE 7-05 table); Check that MNBC adopts it |
| N6 | seismic.siteClasses | A > 1524, B 762-1524, C 366-762, D 183-366, E < 183 m/s, F | ASCE 7-05 Table 20.3-1 | Site classes by vs30 | Sure (ASCE 7-05); Check MNBC |
| N7 | seismic.designSpectrum (inherited) | SDS = 2/3 Fa SS, T0 = 0.2 TS, Sa(0) = 0.4 SDS, SDC bands 0.167/0.33/0.5 and 0.067/0.133/0.2, Cu by SD1 | ASCE 7-05 11.4.4-11.4.5, 11.6, Table 12.8-1 (the same as the parent's ASCE 7-22 values) | Spectrum, SDC, Cu | Check |
| N8 | seismic.designSpectrum.tl | not set | MNBC long-period map | TL | Uncertain (not covered: SD1/T beyond TS) |
| N9 | seismic class F | read as E until a site study | ASCE 7-05 11.4.7 | Site response analysis | SAEngine practice (the parent's) |

## Wind

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N10 | locations.*.windSpeed | Sittwe, Kyaukphyu 55; Pathein 50; Yangon, Bago, Mawlamyine, Dawei, Myeik 45; Mandalay, Nay Pyi Taw, Sagaing, Taungoo, Monywa, Nyaung-U, Magway, Hpa-An 40; Myitkyina, Taunggyi, Lashio 38 m/s | MNBC 2020 basic wind speed by region | V, 3-second gust at 10 m, exposure C, 50-year | Uncertain (SAEngine reading by region: Rakhine coast highest, then the delta and the south coast, then the central and upland regions; replace with MNBC's map or table) |
| N11 | occupancyCategories.*.windImportance | I 0.87, II 1.0, III 1.15, IV 1.15 | ASCE 7-05 Table 6-1 (non-hurricane regions) | Wind importance factor | Sure (ASCE 7-05); Check MNBC, and the cyclone-prone coast (1.15 for I-IV in hurricane regions is not set) |
| N12 | wind.exposures | B α 7.0 zg 365.76; C 9.5, 274.32; D 11.5, 213.36 m | ASCE 7-05 Table 6-2 | Exposure constants | Sure (ASCE 7-05) |
| N13 | wind.kzFactor, kzMinHeight | 2.01, 4.57 m | ASCE 7-05 Table 6-3 note | Kz = 2.01 (z/zg)^(2/α) | Sure |
| N14 | wind (inherited) | Kd 0.85, G 0.85, topography K1-K3, Cp | ASCE 7-05 6.5.4-6.5.11 (the parent's values are the same) | Wind | Check |

## Combinations

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N15 | combinations.strength | 1.4D; 1.2D + 1.6L + 0.5Lr; 1.2D + 1.6Lr + L; 1.2D + 1.6Lr + 0.8W; 1.2D + 1.6W + L + 0.5Lr; 0.9D + 1.6W; 1.2D + E + L + 0.2S; 0.9D + E | ASCE 7-05 Sec 2.3.2 | Strength design | Check (that MNBC 2020 keeps the 1.6W form with 50-year speeds; with ultimate speeds it would be 1.0W: then 1.6W is on the safe side) |
| N16 | combinations.allowable | D; D + L; D + Lr; D + 0.75L + 0.75Lr; D + W; D + 0.7E; D + 0.75(L + W + Lr); D + 0.525E + 0.75L + 0.75S; 0.6D + W; 0.6D + 0.7E | ASCE 7-05 Sec 2.4.1 | Allowable stress design | Check |
| N17 | combinations.service | D + L; D + 0.5L; D + 0.5L + 0.7W | ASCE 7-05 Appendix C commentary | Serviceability | SAEngine practice (0.7W) |
| N18 | combinations.temperature | 1.2D ± 1.2T + 1.6L + 0.5Lr | ASCE 7-05 Sec 2.3.2 combination 2 | T | Check |
| N19 | combinations.flood | 1.6W + 2.0Fa (coastal), 0.8W + 1.0Fa (inland); ASD + 1.5Fa / 0.75Fa | ASCE 7-05 Sec 2.3.3, 2.4.2 | Flood | Check |

## Materials

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N20 | concrete.barDiameters | 10, 12, 16, 20, 25, 28, 32 mm; links 8, 10, 12 | - | Metric bars | SAEngine practice |
| N21 | barSchedule.standard | bs8666 | - | Bar shapes and schedule | SAEngine practice |
| N22 | concrete design, steel, live loads | the parent's ACI 318-19, AISC 360-22, ASCE 7-22 Table 4.3-1 | MNBC 2020 Part 3 references | Not set by this version | Uncertain (check which editions MNBC 2020 references and its own live load table) |

## Column splice hoops (pack follow-up 2026-11-09)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| S1 | detailing.special.columnSplice* (inherited) | the ACI 318-19 pack's: ties over the lap splices of special moment frame columns at the end zones' spacing (least dimension / 4, 6 db, so) | MNBC concrete chapter (column lap splices) | Check (not confirmed) |
