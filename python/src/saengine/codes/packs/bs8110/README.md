# BS 8110 + BS 6399 + BS 5950 (legacy British Standards)

Code pack `bs8110`, built in (alpha 9 track C10). The withdrawn British Standards that many
countries still design to. It `extends` BNBC 2020: every table not in `covers` comes from the
default pack and the report names it BNBC 2020.

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 22 UK towns with the basic wind speed Vb; zone 0 (no earthquake); default London | BS 6399-2:1997 Figure 6 |
| `zoneCoefficients` | Zone 0, Z = 0: no earthquake loading (not covered) | - |
| `occupancyCategories` | Sp = 1.0 for every category (standard design) | BS 6399-2 2.2.2.5 |
| `areaLoads` | Imposed floor and roof loads, concentrated loads on 50 mm, partitions | BS 6399-1:1996 Table 1, BS 6399-3:1988 |
| `liveReduction` | By the floors carried (Table 2) and beams by area (`method: floorCount`) | BS 6399-1 5 |
| `combinations` | 1.4G + 1.6Q, 1.0G + 1.6Q, 1.4G + 1.4W, 1.0G + 1.4W, 1.2(G + Q + W); service | BS 8110-1 Table 2.1, BS 5950-1 Table 2 |
| `wind` | Standard method: Ve = Vb Sa Sd Ss Sp Sb, qs = 0.613 Ve², Sb by height and distance from the sea (country, town), overall × 0.85, Table 5 walls | BS 6399-2:1997 |
| `concreteMethods` | BS 8110-1 limit state design (see below) | BS 8110-1:1997, BS 8110-2:1985 |
| `concrete` | Ec of the shared checks | BS 8110-2 7.2 |
| `steelLimitState` | BS 5950-1 members (see below) | BS 5950-1:2000 |

## Methods by id (the generic SAEngine modules)

Wind `method: "speedFactors"` (`fem/wind_speed_factors.py`: Sb as k2, Sp as k1, Ss as k4, Sa as
the topographic factor, Ca as Ka, the 0.85 of 2.1.3.6 as Kc). Concrete, the C8 family of
tabulated methods with the BS values: `ultimate: partialFactors` (γm 1.5 / 1.05, 0.45 fcu over
0.9 x, x <= 0.5 d, emin 0.05 h <= 20 mm, 0.4 fcu Ac + 0.8 fy Asc, Ec = 20 + 0.2 fcu),
`shear: tabulatedStress` (vc of Table 3.8 with the generic `depthFactor` (400/d)^1/4 >= 1),
`punching: rootStress` (the 1.5 d perimeter), `deflection: spanDepthModification` (the generic
`tensionMoment` form of Table 3.10), `cracking: strainSpacing` (BS 8110-2 eq. 12-13),
`cover: exposureCondition` (Table 3.3), `anchorage: bondStressTable` (fbu = β √fcu),
`memberLimits`, `columns` (additional moments with the generic `unbracedLimit`: 15 braced, 10
unbraced; biaxial by the interaction surface), `twoWaySlabs: restrainedPanel` (Tables 3.13-3.14).
The project's concrete fc is read as fcu. Steel, `steelLimitState` with the generic switches of
this track: `compression.robertson` (Perry-Robertson by the constants a, Annex C),
`flexure.robertson` (αLT 7.0, Annex B), `shear.yieldShare` (0.6 py), `designStrength` (py by
thickness, Table 9), the linear section check and the 4.8.3.3.1 member check.

## Not covered (falls back to BNBC 2020, named so)

Earthquake: the British Standards give none. Every location has Z = 0: no earthquake cases are
made and the derivation says so. A Z entered in Project Settings uses the parent's spectrum and
systems (named BNBC 2020). Also from the parent: concrete torsion (BS 8110-2 2.4), flat slabs
(3.7), walls (3.9), bases (3.11), the notional horizontal loads (3.1.4.2), BS 5950 connections,
BS 5628 masonry and BS 5268 timber (SAEngine's masonry and timber engines are the parent's
methods), the services, fire and the other tables not in `covers`.

Every value is listed with its clause in [VERIFY.md](VERIFY.md), for checking against the printed
codes (no code text was available when the pack was written).
