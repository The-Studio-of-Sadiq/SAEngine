# southafrica-sans: values to verify against the printed standards

No copy of SANS 10160, SANS 10100-1 or SANS 10162-1 was available when this pack was written
(alpha 9, track C24, 2026-11-05). Every value was entered from knowledge of the standards and is
to be checked by the owner. **Sure** / **Check** / **Uncertain** / **SAEngine practice** as in
the other packs' lists. Everything the pack does not set is the parent's (`eurocodes`).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| Z1 | locations.*.windSpeed | vb,0 36 m/s (Johannesburg, Pretoria, Cape Town, Durban, Klerksdorp, Polokwane, Mbombela, Pietermaritzburg), 40 m/s (Gqeberha, East London, Bloemfontein, Kimberley, Welkom, Ceres) | SANS 10160-3 Figure 1 | Fundamental basic wind speed | Uncertain |
| Z2 | locations.*.zone | ag 0.10 (Johannesburg, Pretoria, Cape Town, Welkom, Klerksdorp), 0.15 (Ceres), 0.05 (the others) | SANS 10160-4 Figure 1 | Towns' ag (mining areas included) | Uncertain |
| Z3 | zoneCoefficients.zones | 0.05, 0.10, 0.15 | SANS 10160-4 5.2 | ag bands | Check |
| Z4 | seismic.spectra.SANS | S 1.0, 1.35, 1.5, 1.8; TB 0.15; TC 0.4, 0.5, 0.6, 0.6; TD 2.0 | SANS 10160-4 Table 1 | Ground types 1-4 | Uncertain |
| Z5 | seismic.designCategories | B, C, D by zone | - | SAEngine's category | SAEngine practice |
| Z6 | combinations.strengthSets.sans | 1.35G; 1.2G + 1.6Q; 1.2G + 1.6Q + 0.6W; 1.2G + 1.3W + 0.5Q; 0.9G + 1.3W; G + E + 0.3Q | SANS 10160-1 Table 3, 7.4 | STR combinations | Uncertain (the ψ of the accompanying actions) |
| Z7 | occupancyCategories | the parent's γI 0.8, 1.0, 1.2, 1.4 | SANS 10160-4 Table 2 | Importance factor | Check |
| Z8 | seismic (systems, drift, rules) | the parent's EN 1998-1 | SANS 10160-4 | Behaviour factors and rules | Uncertain (SANS 10160-4's own q not set) |
| Z9 | concreteMethods.ultimate.alphaCC | 0.85 | SANS 10100-1 4.3.4 | 0.67 fcu/γm on fck | SAEngine practice |
| Z10 | concreteMethods.ultimate.gammaC / gammaS | the parent's 1.5, 1.15 | SANS 10100-1 3.3.3 | Partial factors | Check |
| Z11 | concrete (other areas) | the parent's EN 1992-1-1 | SANS 10100-1 | Shear, deflection, detailing | Not covered (named in the report as EN 1992-1-1) |
| Z12 | steel | the parent's EN 1993-1-1 | SANS 10162-1 | Steel design | Not covered |
| Z13 | wind terrain | the parent's EN 1991-1-4 categories | SANS 10160-3 Table 3 | Terrain profile | Not covered (SANS's power law not set) |
| Z14 | areaLoads | the parent's EN 1991-1-1 recommended values | SANS 10160-2 Table 2 | Imposed loads | Uncertain (SANS values not set) |
