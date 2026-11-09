# korea-kds: values to verify against the printed standards

No copy of KDS 41 17 00, KDS 41 12 00 or KDS 14 20 was available when this pack was written
(alpha 9, track C24, 2026-11-05). Every value was entered from knowledge of the standards and is
to be checked by the owner. **Sure**: well-known value. **Check**: believed right, confirm the
number or the clause. **Uncertain**: may be wrong; replace it from the standard before design.
**SAEngine practice**: SAEngine's choice where the standard gives no number. Everything the pack
does not set is the base pack's (`aci318-asce7-22`, its VERIFY.md).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K1 | locations.*.ss / s1 / zoneLabel | zone I: SS 0.55, S1 0.22 (Seoul, Incheon, Suwon, Sejong, Daejeon, Daegu, Gwangju, Busan, Ulsan, Pohang, Gangneung); zone II: SS 0.35, S1 0.14 (Mokpo, Jeju) | KDS 41 17 00 4.2.1.1, Table 4.2-1 (Z 0.11 zone I, 0.07 zone II) × I 2.0 (2400 years) | S = Z I entered as SS = 2.5 S, S1 = S | Check (Z and I); towns' zones Uncertain (zone II: north-east Gangwon, south-west Jeonnam, Jeju, as SAEngine recalls) |
| K2 | locations.*.windSpeed | V0 Seoul 26, Incheon 28, Suwon 26, Sejong 26, Daejeon 28, Daegu 26, Gwangju 28, Busan 38, Ulsan 34, Pohang 34, Gangneung 34, Mokpo 38, Jeju 44 m/s, × 1.43 | KDS 41 12 00 5.5.1 (V0 by region) | The 3-second gust the base pack's method takes | Uncertain (V0 from memory of the KBC map; the factor 1.43, 10-minute mean to 3-second gust in open terrain, is SAEngine practice) |
| K3 | occupancyCategories.*.windImportance | 1.0 | KDS 41 12 00 (importance factor Iw) | The wind's importance factor | SAEngine practice (Iw not set; enter a higher V for important buildings) |
| K4 | seismic.siteClasses | S1-S6 | KDS 41 17 00 Table 4.2-1 | Site classes by the depth to bedrock and the soil's vs | Check |
| K5 | seismic.designSpectrum.siteCoefficients.fa | S1 1.12; S2 1.4, 1.4, 1.3; S3 1.7, 1.5, 1.3; S4 1.6, 1.4, 1.2; S5 1.8, 1.3, 1.3 at S = 0.1, 0.2, 0.3 (SS 0.25, 0.5, 0.75) | KDS 41 17 00 Table 4.2-3 | Short-period site coefficient | Uncertain |
| K6 | seismic.designSpectrum.siteCoefficients.fv | S1 0.84; S2 1.5, 1.4, 1.3; S3 1.7, 1.6, 1.5; S4 2.2, 2.0, 1.8; S5 3.0, 2.7, 2.4 at S = 0.1, 0.2, 0.3 | KDS 41 17 00 Table 4.2-4 | Long-period site coefficient | Uncertain |
| K7 | seismic.defaultSiteClass, siteSpecificStudy | S4; S6 needs a study, assumed S5 | KDS 41 17 00 4.2.1.2 | Unknown site; site-specific class | SAEngine practice |
| K8 | seismic.designSpectrum (designShare, t0Share, rampStart, bands, Cs) | the base pack's: 2/3, 0.2, 0.4, SDS 0.167 / 0.33 / 0.50, SD1 0.067 / 0.133 / 0.20, Cs ≥ 0.044 SDS I ≥ 0.01 | KDS 41 17 00 4.2.2, 6.1.3, 7.2.1 | Spectrum shape, categories, Cs | Check (the same numbers believed; TL not given: SD1/T beyond any TL, on the safe side) |
| K9 | seismic.systems, allowableDrift | the base pack's (RC special moment frame R 8, Ω0 3, Cd 5.5 ...; drift 0.010 / 0.015 / 0.020) | KDS 41 17 00 Table 6.2-1, Table 7.2-1 | R, Ω0, Cd, drift limits by importance | Check (the KDS rows are believed the same as ASCE 7; the height limits differ and are not set) |
| K10 | concrete.barDiameters / barNames | D10-D32 at 10, 13, 16, 19, 22, 25, 29, 32 mm | KS D 3504 | Bars | Check (designed with the rounded diameters: D10's area 78.5 mm² vs 71.3 nominal, as the base pack's US bars) |
| K11 | factors.phi.tension | 0.85 | KDS 14 20 10 4.2.3 | Tension-controlled sections | Check |
| K12 | factors.phi.compressionSpiral | 0.70 | KDS 14 20 10 4.2.3 | Spirally reinforced compression members | Check |
| K13 | factors.phi.plain | 0.55 | KDS 14 20 10 4.2.3 | Plain concrete | Check |
| K14 | factors.phi (others) | the base pack's (tied 0.65, shear 0.75, bearing 0.65, strut-and-tie 0.75) | KDS 14 20 10 4.2.3 | Other φ | Check |
| K15 | concrete rules | the base pack's ACI 318-19 | KDS 14 20 (2021) | Stress block, shear, development | Uncertain (KDS 14 20 20:2021 changed the stress block: εcu 0.0033 with its own α, β by fck; not set) |
| K16 | combinations, areaLoads | the base pack's ASCE 7-22 | KDS 41 10 15 | Combinations and live loads | Check (1.2D + 1.6L, 1.2D + 1.0E + 1.0L, 0.9D + 1.0E believed the same) |

## Nominal bar masses (alpha 9 C26, `concrete.barMasses`)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| C26-1 | concrete.barMasses 10, 13, 16, 19 | 0.560, 0.995, 1.56, 2.25 kg/m (D10-D19, nominal 9.53-19.1 mm) | KS D 3504 table of nominal dimensions | Check |
| C26-2 | concrete.barMasses 22, 25, 29, 32 | 3.04, 3.98, 5.04, 6.23 kg/m (D22-D32, nominal 22.2-31.8 mm) | KS D 3504 table of nominal dimensions | Check |
