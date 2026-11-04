# eurocodes-sg: values to verify against the printed National Annex

No copy of the National Annex was available when this pack was written (alpha 9, track C15, 2026-11-04). Every value was entered from knowledge of the annex and is to be checked by the owner against the printed edition. **Sure**: well-known value, low risk. **Check**: believed right, confirm the number or the row. **Uncertain**: the value or its reading may be wrong, or it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack does not set is the base pack's recommended value (`eurocodes`, its VERIFY.md).

## SS EN 1991-1-4, SS EN 1992-1-1, SS EN 1993-1-1 (NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| S1 | locations.singapore.windSpeed | 20.0 m/s | SS EN 1991-1-4 NA (NA to 4.2(1)) | vb,0 for Singapore | Check |
| S2 | wind.directionality | 1.0 | SS EN 1991-1-4 NA | cdir | Check |
| S3 | wind.minimumLateral.share | 0.015 | Singapore NA (notional horizontal load) | Least horizontal load 1.5 % of the characteristic dead weight at each floor, applied as the least characteristic wind storey force | Uncertain (the clause, and whether it is a design ultimate load: SAEngine takes it on the characteristic wind, on the safe side) |
| S4 | zoneCoefficients.zones | {0: 0.0} | - | No seismic design (EN 1998 not adopted) | Check |
| S5 | concreteMethods.ultimate.alphaCC / alphaCCShear | 0.85 / 1.0 | SS EN 1992-1-1 NA 3.1.6(1)P | αcc flexure and axial / other phenomena | Check |
| S6 | steelLimitState.memberResistance.gammaM0/M1/M2 | 1.00 / 1.00 / 1.10 | SS EN 1993-1-1 NA 6.1(1) | Member resistances | Check |
| S7 | combinations, areaLoads | base pack recommended values | SS EN 1990, SS EN 1991-1-1 NA | Not set by this version | Uncertain (not covered: check the Singapore NDPs) |
| S8 | seismic.designCategories.zoneColumns | {0: 0} | - | Zone 0 takes the first category column (B) | SAEngine practice |
