# eurocodes-my: values to verify against the printed National Annex

No copy of the National Annex was available when this pack was written (alpha 9, track C15, 2026-11-04). Every value was entered from knowledge of the annex and is to be checked by the owner against the printed edition. **Sure**: well-known value, low risk. **Check**: believed right, confirm the number or the row. **Uncertain**: the value or its reading may be wrong, or it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack does not set is the base pack's recommended value (`eurocodes`, its VERIFY.md).

## MS EN 1991-1-4, MS EN 1998-1, MS EN 1992-1-1 (NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| M1 | locations.*.windSpeed | Zone I 23.8, Zone II 23.0 m/s | MS EN 1991-1-4 NA | vb,0 (10-minute mean) of the wind zones | Uncertain (SAEngine's conversion of the MS 1553 3-second gusts 33.5 / 32.5 m/s by ÷ 1.41, not the NA's number: replace with the NA's vb,0) |
| M2 | locations.* (zones) | Kuala Lumpur zone 2 / agR 0.04 g, George Town (Penang) zone 1 / agR 0.04 g, Johor Bahru zone 2 / agR 0.03 g, Ipoh zone 2 / agR 0.03 g, Kota Bharu zone 1 / agR 0.02 g, Kuantan zone 1 / agR 0.02 g, Kuching zone 2 / agR 0.02 g, Kota Kinabalu zone 2 / agR 0.08 g, Ranau zone 2 / agR 0.12 g, Sandakan zone 2 / agR 0.06 g, Lahad Datu zone 2 / agR 0.08 g | MS EN 1991-1-4 NA map; MS EN 1998-1 NA Figure NA.1 | Wind zone and agR band of each town | Uncertain (from memory: check every town on the NA maps) |
| M3 | zoneCoefficients.zones | 0, 0.02, 0.03, 0.04, 0.06, 0.08, 0.12 g | MS EN 1998-1 NA Figure NA.1 | Bands of agR | SAEngine practice |
| M4 | concreteMethods.ultimate.alphaCC / alphaCCShear | 0.85 / 1.0 | MS EN 1992-1-1 NA 3.1.6(1)P | αcc flexure and axial / other phenomena | Check |
| M5 | combinations, areaLoads, steel, geotechnics | base pack recommended values | MS EN 1990, 1991-1-1, 1993-1-1, 1997-1 NA | Not set by this version | Uncertain (not covered: check the Malaysian NDPs) |
| M6 | seismic.designCategories.zoneColumns | bands 0-3 → B, 4-5 → C, 6 → D | - | Category of the seismic action by the agR band | SAEngine practice |
