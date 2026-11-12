# eurocodes-uk: values to verify against the printed National Annex

No copy of the National Annex was available when this pack was written (alpha 9, track C15, 2026-11-04). Every value was entered from knowledge of the annex and is to be checked by the owner against the printed edition. **Sure**: well-known value, low risk. **Check**: believed right, confirm the number or the row. **Uncertain**: the value or its reading may be wrong, or it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack does not set is the base pack's recommended value (`eurocodes`, its VERIFY.md).

## BS EN 1990 (UK NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| U1 | combinations.strengthSet | 6.10ab | NA.2.2.3.2 | Eqs 6.10a and 6.10b, the less favourable | Sure |
| U2 | combinations.strengthSets.6.10ab (6.10b) | ξ = 0.925: ξ γG = 1.249 (named 1.25G) | Table NA.A1.2(B) | Reduction factor of the unfavourable permanent actions in Eq 6.10b | Sure |
| U3 | combinations.strengthSets.* | γG,sup 1.35, γG,inf 1.0, γQ 1.5 | Table NA.A1.2(B) | Partial factors of set B | Sure |
| U4 | combinations.strengthSets.* (W accompanying) | ψ0 wind 0.5 → 0.75 W | Table NA.A1.1 | Combination value of the wind | Check (UK ψ0 wind 0.5, recommended 0.6) |
| U5 | combinations.strengthSets.* (S accompanying) | ψ0 snow 0.5 → 0.75 S | Table NA.A1.1 | Snow at altitude ≤ 1000 m | Sure |
| U6 | combinations.strengthSets.* (Q accompanying) | ψ0 0.7 → 1.05 Q | Table NA.A1.1 | Imposed loads, categories A-D (E: 1.0 not separated) | Check |
| U7 | combinations.service | 6.14b G + Q + 0.5S + 0.5W; G + W + 0.7Q + 0.5S; frequent and quasi-permanent as the base pack (ψ1 wind 0.2, ψ2 0.3 / 0) | Table NA.A1.1, Eqs 6.14b-6.16b | SLS combinations | Check |

## BS EN 1991-1-1 imposed loads (UK NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| U8 | areaLoads.uses.residential, dwelling | 1.5 kN/m², 2.0 kN | Table NA.2/NA.3, A1 | Self-contained dwelling units | Sure |
| U9 | areaLoads.uses.residentialPublic, hospitalWard | 2.0 kN/m², 1.8 kN | Table NA.3, A3 | Hotel bedrooms, hospital wards | Check |
| U10 | areaLoads.uses.stairsDwelling | 1.5 kN/m², 2.0 kN | Table NA.3, A2 | Stairs of single dwellings | Check |
| U11 | areaLoads.uses.balcony | 2.5 kN/m², 2.0 kN | Table NA.3, A5 | Balconies of single dwellings and communal areas (hotels: as the rooms, at least 4.0, not separated) | Uncertain |
| U12 | areaLoads.uses.office | 2.5 kN/m², 2.7 kN | Table NA.3, B1 | Offices for general use (B2 at or below ground floor 3.0: not separated) | Sure |
| U13 | areaLoads.uses.classroom | 3.0 kN/m², 3.0 kN | Table NA.3, C13 | Classrooms | Check |
| U14 | areaLoads.uses.dining | 2.0 kN/m², 3.0 kN | Table NA.3, C11 | Public, institutional and communal dining rooms | Check |
| U15 | areaLoads.uses.assemblyFixed | 4.0 kN/m², 3.6 kN | Table NA.3, C21 | Assembly areas with fixed seats | Check |
| U16 | areaLoads.uses.danceHall, gymnasium | 5.0 kN/m², 3.6 kN | Table NA.3, C41/C42 | Areas for physical activities | Check |
| U17 | areaLoads.uses.grandstand | 5.0 kN/m², 3.6 kN | Table NA.3, C5 | Areas susceptible to large crowds | Check |
| U18 | areaLoads.uses.retailGround, retailUpper, wholesale | 4.0 kN/m², 3.6 kN | Table NA.3, D1/D2 | Shopping areas | Check |
| U19 | areaLoads.roofLive (H) | 0.6 kN/m², 0.9 kN | Table NA.7 | Roofs not accessible, slope below 30° (reduced linearly to 0 at 60°: not covered, the flat value used) | Check |
| U20 | areaLoads.uses (others) | EN recommended | - | Corridors, stages, storage (2.4 kN/m² per m height in the UK), parking: base pack values | Uncertain (not set: check the UK rows) |

## BS EN 1991-1-4 wind and BS EN 1991-1-3 snow (UK NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| U21 | locations.*.windSpeed | London 21.5, Birmingham 22, Manchester 23.5, Liverpool 24, Leeds 23, Sheffield 22.5, Newcastle upon Tyne 24, Bristol 22.5, Cardiff 23.5, Swansea 24.5, Plymouth 24, Southampton 22, Norwich 22.5, Cambridge 21.5, Nottingham 22, Edinburgh 25, Glasgow 25.5, Aberdeen 26, Inverness 27, Belfast 25, Londonderry 27, Lerwick 31 m/s | Figure NA.1 | vb,map near each town (the same towns and readings as the bs8110 pack's BS 6399-2 Figure 6) | Uncertain (the UK NA map is the BS 6399-2 map in 10-minute means; if its values differ, about 1.06 × the hourly ones, correct every town) |
| U22 | locations.default | london | - | New projects start in London | SAEngine practice |
| U23 | wind.altitude.factor | 0.001 (calt = 1 + 0.001 A) | NA.2.5, Eq NA.2a | Altitude factor on vb,map; applied to the town's or the entered speed | Sure (Eq NA.2a); Eq NA.2b (z > 10 m) not used: conservative |
| U24 | wind.directionality | 1.0 | Table NA.1 | cdir, the largest for every direction | SAEngine practice (conservative) |
| U25 | wind.peakVelocityPressure.season | 1.0 | NA.2.8 | cseason of permanent buildings | Sure |
| U26 | wind (qp) | EN Eq 4.8 by terrain category | Figures NA.7, NA.8 not covered | The UK exposure factor ce(z) with the town terrain correction is not covered | Uncertain (SAEngine practice: check qp against the NA figures) |
| U27 | snow.groundLoad.zones.1-5 | sk = 0.2 + 0.1 Z + (A - 100)/525 (Z = 1..5), at least 0 | NA.2.8, Eq NA.1, Figure NA.1 | Ground snow load by zone and site altitude | Check (the zone numbers of Figure NA.1, and whether a least value applies at low altitude) |

## BS EN 1992-1-1, 1993, 1997, 1998 (UK NA) and the bar schedule

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| U28 | concreteMethods.ultimate.alphaCC | 0.85 | 3.1.6(1)P | αcc of compression in flexure and axial loading | Sure |
| U29 | concreteMethods.ultimate.alphaCCShear | 1.0 | 3.1.6(1)P | αcc of the other phenomena (shear VRd,max, torsion TRd,max, punching vRd,max) | Sure |
| U30 | concreteMethods.ultimate.gammaC / gammaS | 1.5 / 1.15 | 2.4.2.4 | Persistent and transient design situations | Sure |
| U31 | concreteMethods.cover.deviation | 10 mm | 4.4.1.3(1)P | Δcdev | Sure |
| U32 | concreteMethods.cover (cmin,dur) | EN Table 4.4N of the base pack | 4.4.1.2 → BS 8500-1 | The UK's durability covers by BS 8500 are not covered | Uncertain (not covered: check covers against BS 8500-1) |
| U33 | steelLimitState.memberResistance.gammaM0/M1/M2 | 1.00 / 1.00 / 1.10 | UK NA to BS EN 1993-1-1 6.1(1) | Member resistances; net section fracture | Sure |
| U34 | steelLimitState.connections.gammaM2 | 1.25 | UK NA to BS EN 1993-1-8 2.2(2) | Bolts, welds, plates in bearing | Sure |
| U35 | geotechnicalMethods.designApproach | DA1 | UK NA to BS EN 1997-1 2.4.7.3.4.1 | Design Approach 1, combinations 1 and 2 | Sure |
| U36 | geotechnicalMethods (piles R4) | base pack's recommended R4 | Tables NA.A.6-NA.A.8 | UK pile factors with/without SLS verification are not covered | Uncertain (not covered) |
| U37 | zoneCoefficients.zones | {0: 0.0}, every town zone 0 | UK NA to BS EN 1998-1, PD 6698 | Very low seismicity: no earthquake cases unless the project enters agR | Check (CC3 and special structures need a study) |
| U38 | barSchedule.standard | bs8666 (shapeKey false) | BS 8666:2020 | Bar schedules by BS 8666 (the standard of the default pack, C14) | Sure |
| U39 | seismic.designCategories.zoneColumns | {0: 0} | - | Zone 0 takes the first category column (B: no seismic detailing) | SAEngine practice |
