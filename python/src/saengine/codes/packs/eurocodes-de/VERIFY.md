# eurocodes-de: values to verify against the printed National Annex

No copy of the National Annex was available when this pack was written (alpha 9, track C15, 2026-11-04). Every value was entered from knowledge of the annex and is to be checked by the owner against the printed edition. **Sure**: well-known value, low risk. **Check**: believed right, confirm the number or the row. **Uncertain**: the value or its reading may be wrong, or it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack does not set is the base pack's recommended value (`eurocodes`, its VERIFY.md).

## DIN EN 1990 and DIN EN 1991-1-1 (NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| D1 | combinations.strengthSet | 6.10 | DIN EN 1990/NA zu 6.4.3.2(3) | Eq 6.10 (not 6.10a/b) | Sure |
| D2 | combinations (γ, ψ) | γG 1.35/1.0, γQ 1.5; ψ A,B 0.7/0.5/0.3, snow 0.5/0.2/0, wind 0.6/0.2/0 | Tables NA.A.1.1, NA.A.1.2(B) | Equal to the recommended values of the base pack | Check |
| D3 | areaLoads.uses.residential / dwelling | A2 1.5 (no Qk) / A3 2.0, 1.0 kN | Table 6.1DE | Residential floors with / without sufficient lateral distribution | Check |
| D4 | areaLoads.uses.office | B1 2.0 kN/m², 2.0 kN | Table 6.1DE | Offices | Check |
| D5 | areaLoads.uses.residentialPublic, hospitalWard | B2 3.0, 3.0 kN | Table 6.1DE | Hotel rooms, hospital wards | Check |
| D6 | areaLoads.uses.stairs / stairsDwelling | T2 5.0, 2.0 / T1 3.0, 2.0 | Table 6.1DE | Stairs | Check |
| D7 | areaLoads.uses.balcony | Z 4.0, 2.0 | Table 6.1DE | Access ways, loggias, balconies | Check |
| D8 | areaLoads.uses.classroom, dining / assemblyFixed / assemblyMovable, corridorAbove, officeLobby | C1 3.0, 4.0 / C2 4.0, 4.0 / C3 5.0, 4.0 | Table 6.1DE | Assembly categories C1-C3 | Check |
| D9 | areaLoads.uses.danceHall, gymnasium, stageFloor / grandstand | C4 5.0, 7.0 / C5 5.0, 4.0 | Table 6.1DE | C4, C5 (C6 grandstands 7.5, 10.0 not separated) | Uncertain |
| D10 | areaLoads.uses.retailGround, retailUpper, wholesale | D2 5.0, 4.0 | Table 6.1DE | Retail and department stores (D1 small shops 2.0 not separated) | Check |
| D11 | areaLoads.uses (others) | EN recommended | - | Storage, parking, roofs: base pack values | Uncertain (not set) |

## DIN EN 1991-1-4 wind and DIN EN 1991-1-3 snow (NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| D12 | locations.*.windSpeed | WZ 1-4: 22.5, 25.0, 27.5, 30.0 m/s | Annex NA.A, Table NA.A.1 | vb,0 of the wind zones | Sure |
| D13 | locations.* (zones) | Berlin WZ 2 / EZ 0, Hamburg WZ 3 / EZ 0, München WZ 1 / EZ 0, Köln WZ 1 / EZ 1, Frankfurt am Main WZ 1 / EZ 0, Stuttgart WZ 1 / EZ 0, Düsseldorf WZ 2 / EZ 0, Hannover WZ 2 / EZ 0, Dresden WZ 2 / EZ 0, Leipzig WZ 2 / EZ 0, Aachen WZ 1 / EZ 3, Albstadt WZ 1 / EZ 3, Freiburg im Breisgau WZ 1 / EZ 1, Kiel WZ 3 / EZ 0, Rostock WZ 3 / EZ 0, Westerland (Sylt) WZ 4 / EZ 0 | NA.A map / district list; DIN EN 1998-1/NA map | Wind zone (WZ) and seismic zone (EZ) of each town | Uncertain (every town from memory: check against the district lists) |
| D14 | wind.peakVelocityPressure.profiles.inland | 1.5 qb (≤ 7 m); 1.7 qb (z/10)^0.37 (≤ 50 m); 2.1 qb (z/10)^0.24 (≤ 300 m) | Table NA.B.2 | Mixed profile inland (II/III) | Check (continuous at 7 and 50 m) |
| D15 | wind.peakVelocityPressure.profiles.coast | 1.8 qb (≤ 4 m); 2.3 qb (z/10)^0.27; 2.6 qb (z/10)^0.19 | Table NA.B.2 | Coastal belt and Baltic islands (I/II) | Check |
| D16 | wind.peakVelocityPressure.profiles.northSeaIslands | 1.1 kN/m² (≤ 2 m); 1.5 (z/10)^0.19 kN/m² | Table NA.B.2 | North Sea islands | Check |
| D17 | wind.peakVelocityPressure.simplified | WZ1 inland 0.50/0.65/0.75; WZ2 inland 0.65/0.80/0.90, coast 0.85/1.00/1.10; WZ3 inland 0.80/0.95/1.10, coast 1.05/1.20/1.30; WZ4 inland 0.95/1.15/1.30, coast 1.25/1.40/1.55, North Sea islands 1.40 (≤ 10 m) kN/m² for h ≤ 10/18/25 m | Table NA.B.3 | Simplified velocity pressures (opt-in: useSimplified) | Uncertain (cells from memory) |
| D18 | wind.peakVelocityPressure.useSimplified | false | NA.B.3 | The profiles by default; the simplified pressures by a Code Values override | SAEngine practice |
| D19 | wind.exposures (z0, zmin of inland, coast, islands) | 0.3/7, 0.05/4, 0.01/2 m | - | Only for the turbulence of the detailed cscd; the profiles' lower bounds as zmin | SAEngine practice |
| D20 | wind (orography) | qp × co(z)² | - | A hill's orography on the NA profile | SAEngine practice |
| D21 | snow.groundLoad.zones.1/1a/2/2a/3 | 0.19 + 0.91 x² ≥ 0.65; × 1.25; 0.25 + 1.91 x² ≥ 0.85; × 1.25; 0.31 + 2.91 x² ≥ 1.10; x = (A + 140)/760 | NDP zu 4.1(1), Eqs NA.1-NA.3 | Ground snow load by zone and altitude | Check |

## DIN EN 1992, 1993, 1997, 1998 (NA)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| D22 | concreteMethods.ultimate.alphaCC | 0.85 (shear too) | NDP zu 3.1.6(1)P | αcc | Sure |
| D23 | concreteMethods.ultimate.gammaC / gammaS | 1.5 / 1.15 | NDP zu 2.4.2.4 | Persistent and transient | Sure |
| D24 | concreteMethods.shear.crdcCoefficient | 0.15 | NDP zu 6.2.2(1) | CRd,c = 0.15/γc | Check |
| D25 | concreteMethods.shear.nuCoefficient/nuDivisor/nuMax | 0.825 / 550 / 0.75 | NDP zu 6.2.3(3) | ν1 = 0.75 ν2, ν2 = 1.1 - fck/500 ≤ 1 | Check |
| D26 | concreteMethods.shear.cotTheta | base pack 1.0-2.5 | Eq 6.7aDE not covered | DIN allows up to 3.0 by Eq 6.7aDE | SAEngine practice (on the safe side) |
| D27 | steelLimitState.memberResistance.gammaM0/M1/M2 | 1.00 / 1.10 / 1.25 | DIN EN 1993-1-1/NA zu 6.1(1) | Member resistances | Sure |
| D28 | steelLimitState.connections.gammaM2 | 1.25 | DIN EN 1993-1-8/NA zu 2.2(2) | Joints | Sure |
| D29 | geotechnicalMethods.designApproach | DA2* (A1, M1, R2) | DIN 1054 2.4.7.3.4 | Design approach 2* with γR,v 1.4, γR,h 1.1 | Check (DA2* applied as DA2 on the actions) |
| D30 | zoneCoefficients.zones | 0: 0, 1: 0.0408, 2: 0.0612, 3: 0.0816 g | DIN 4149 Table 2 / DIN EN 1998-1/NA | agR 0.4, 0.6, 0.8 m/s² | Check |
| D31 | seismic.spectra.1 AR-CS | AR 1.00/0.05/0.20; BR 1.25/0.05/0.25; CR 1.50/0.05/0.30; BT 1.00/0.10/0.30; CT 1.25/0.10/0.40; CS 0.75/0.10/0.50 (S/TB/TC), TD 2.0 | DIN EN 1998-1/NA Table NA.4 | Combined subsoil classes | Uncertain (from memory) |
| D32 | seismic.designCategories | zones 0-2 B, zone 3 C (IV: C from zone 2) | - | Category of the seismic action (detailing) | SAEngine practice |
| D33 | occupancyCategories (γI) | base pack 0.8/1.0/1.2/1.4 | DIN EN 1998-1/NA zu 4.2.5(5) | Importance factors | Check |
