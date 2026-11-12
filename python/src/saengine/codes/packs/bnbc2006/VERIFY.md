# bnbc2006: values to verify against the printed code

No copy of BNBC 1993 (reissued as BNBC 2006) was available when this pack was written (alpha 9,
track C10, 2026-11-04); the BNBC 2020 text was, and the values that changed were taken from
knowledge of the older code. Every value below is to be checked by the owner against the printed
1993 / 2006 edition. **Sure**: well-known value, low risk. **Check**: believed right, confirm the
number. **Uncertain**: the value or its reading may be wrong, or it is an SAEngine form; the
choice is stated.

## Seismic (Part 6 Sec 2.5)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| Q1 | zoneCoefficients.zones | 1: 0.075, 2: 0.15, 3: 0.25 | Table 6.2.22 | Seismic zone coefficient Z | Sure |
| Q2 | locations.*.zone | see the district table below | Figure 6.2.24 | Zones of the districts | Uncertain (from the zoning map as recalled: check every district) |
| Q3 | seismic.designSpectrum.factor | 1.0 | 2.5.6.1 | V = Z I C W / R | Sure |
| Q4 | seismic.designSpectrum.shapePlateau / descendingExponent | 2.75, 2/3 | 2.5.6.3 | C = 1.25 S / T^(2/3) <= 2.75 | Sure |
| Q5 | seismic.designSpectrum.leastCoefficient | 0.075 | 2.5.6.3 | C/R at least 0.075 | Check |
| Q6 | seismic.siteClasses.*.TC | (1.25 S / 2.75)^1.5: 0.3065, 0.4028, 0.5630, 0.8668 s | - | Where C reaches 2.75 for S1-S4 (S itself 1 in the class) | SAEngine form (exact) |
| Q7 | seismic.siteClasses (S) | S1 1.0, S2 1.2, S3 1.5, S4 2.0 | Table 6.2.24 | Site coefficient | Check |
| Q8 | seismic.siteClasses (mapping) | SA, SB = S1; SC = S2; SD = S3; SE = S4 | 2.5.4.3 | The default pack's classes read as the 1993 soil types | Uncertain (SAEngine practice) |
| Q9 | seismic.siteClasses.*.TB | 0.1 s | - | The dynamic spectrum rises from 1.0 at T = 0 (the static method takes the plateau) | SAEngine practice |
| Q10 | seismic.siteClasses.*.TD | 10 s, constant beyond | - | C keeps falling as T^(-2/3) to 10 s | SAEngine practice |
| Q11 | seismic.periodCoefficients | Ct 0.083 steel MRF, 0.073 RC MRF and EBF, 0.049 others; hn^(3/4) | 2.5.6.5 | Period method A | Sure |
| Q12 | seismic.lateralForce.topForce | Ft = 0.07 T V <= 0.25 V when T > 0.7 s | 2.5.7.2 | Top force | Sure |
| Q13 | seismic.lateralForce.distribution | Fx ∝ wx hx (the rest V - Ft) | 2.5.7.2 | Vertical distribution | Sure |
| Q14 | seismic.systems.rcSmf / rcImf / rcOmf | 12 / 8 / 5 | Table 6.2.25 | RC moment frames | Check |
| Q15 | seismic.systems.steelSmf / steelImf / steelOmf | 12 / 8 / 6 | Table 6.2.25 | Steel moment frames (IMRF of steel: uncertain row) | Check |
| Q16 | seismic.systems.rcSpecialWallFrame / rcOrdinaryWallFrame | 8 / 8 | Table 6.2.25 | Building frame with concrete shear walls (no special / ordinary split in 1993) | Check |
| Q17 | seismic.systems.rcSpecialBearingWall / rcOrdinaryBearingWall | 6 / 6 | Table 6.2.25 | Bearing walls of concrete | Check |
| Q18 | seismic.systems.masonryOrdinaryReinforced / ...Frame | 6 / 8 | Table 6.2.25 | Masonry shear walls (bearing / building frame) | Uncertain |
| Q19 | seismic.systems.rcDualSpecial / rcDualSpecialOrdinaryWalls | 12 / 12 | Table 6.2.25 | Dual: SMRF and concrete walls | Check |
| Q20 | seismic.systems.rcDualIntermediate* | 9 | Table 6.2.25 | Dual: IMRF and concrete walls | Check |
| Q21 | seismic.systems.steelEbf / steelEbfMoment | 10 / 10 | Table 6.2.25 | Steel EBF | Check |
| Q22 | seismic.systems.steelScbf / steelOcbf | 8 / 8 | Table 6.2.25 | Steel braced frames | Check |
| Q23 | seismic.systems.steelDualSmfEbf / steelDualSmfScbf | 12 / 10 | Table 6.2.25 | Steel dual systems | Check |
| Q24 | seismic.systems (others) | BNBC 2020's | - | Systems the 1993 table lacks (BRBF, plate walls ...) | Inherited |
| Q25 | seismic (Ω0, Cd, drift) | BNBC 2020's | - | The 1993 drift rule (0.04/R, 0.005 h for T < 0.7 s) is not covered | Not covered |
| Q26 | seismic.designCategories | zone 1 B, 2 C, 3 D (IV: C, D, D) | Part 6 Sec 8 | The detailing of members by zone | SAEngine practice |
| Q27 | occupancyCategories.*.seismicImportance | 1.0, 1.0, 1.0, 1.25 | Table 6.2.23 | Structure importance factor I (essential and hazardous 1.25) | Check |

## Wind (Part 6 Sec 2.4)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| W1 | locations.*.windSpeed | the district table below, km/h / 3.6 | Table 6.2.8 | Basic wind speed Vb (fastest mile) | Check (each district; their ratio to BNBC 2020's 3-s gust speeds is 1.11-1.15 throughout, which supports the list) |
| W2 | speedFactors.airFactor | 0.6117 (47.2e-6 × 3.6² × 1000) | 2.4.4 | qz = Cc CI Cz Vb², Cc = 47.2 × 10⁻⁶ | Sure |
| W3 | speedFactors.heightFactors | √(Cz CG) by exposure A, B, C | Tables 6.2.10, 6.2.11 | Cz = 2.58 (z/zg)^(2/α), CG = 0.65 + 3.65 Tz; A α 4.5, zg 365.76 m, D0 0.010; B 7.0, 274.32 m, 0.005; C 10.0, 213.36 m, 0.003; below 4.572 m constant | Check (the tables against these forms: Cz at 4.5 m 0.368 / 0.801 / 1.196, CG at 4.5 m 1.651 / 1.320 / 1.154) |
| W4 | speedFactors.riskCoefficients | k1 = √CI: 0.894, 1.0, 1.118 | Table 6.2.9 | CI 0.80 low-risk, 1.00 standard and special, 1.25 essential and hazardous | Check |
| W5 | occupancyCategories.*.windImportance | 0.80, 1.00, 1.00, 1.25 | Table 6.2.9 | CI as the marker of the k1 row | Check |
| W6 | cpWindward | 0.8 | Table 6.2.12 | Windward wall | Check |
| W7 | cpLeeward | -0.5, -0.3, -0.2 at L/B 1, 2, 4 | Table 6.2.12 | Leeward wall | Check |
| W8 | directionality / topographic / gust | 1.0 / 1.0 / 1.0 | - | No such factors (CG in k2) | Sure |
| W9 | defaultExposure | A | 2.4.6 | Urban and suburban (the default pack's default letter) | SAEngine practice |
| W10 | - | cladding, roofs, open structures | - | Not covered (the wind table is replaced whole) | Not covered |

## Load combinations and strength reduction factors (Part 6 Sec 2.7, 6.2)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| F1 | combinations.strength "1" | 1.4D + 1.7L (+ 1.7H) | 6.2.2.1 | Dead and live | Sure |
| F2 | combinations.strength "2W" | 0.75 (1.4D + 1.7L + 1.7W) | 6.2.2.2 | With wind | Sure |
| F3 | combinations.strength "3W" | 0.9D + 1.3W | 6.2.2.2 | Wind, dead favourable | Sure |
| F4 | combinations.strength "2E" | 0.75 (1.4D + 1.7L + 1.87E) | 6.2.2.3 | With earthquake | Check |
| F5 | combinations.strength "3E" | 0.9D + 1.43E | 6.2.2.3 | Earthquake, dead favourable | Check |
| F6 | combinations.service | D + L, D + W, D + L + W | 2.7.2 | Service | Check |
| F7 | combinations.allowable | D + L, D + L + W, D + L + E, D + W, D + E (no 1/3 increase) | 2.7.2, 2.7.4 | Allowable stress design | Check |
| F8 | combinations.seismicDeadUpper / Lower | 1.05 / 0.9 | 6.2.2.3 | Dead factors with earthquake | Check |
| F9 | factors.phi.tension | 0.90 | 6.2.3.2 | Flexure | Sure |
| F10 | factors.phi.compressionTied / Spiral | 0.70 / 0.75 | 6.2.3.2 | Axial compression | Sure |
| F11 | factors.phi.shear / punching | 0.85 | 6.2.3.2 | Shear and torsion | Sure |
| F12 | factors.phi.bearing / plain | 0.70 / 0.65 | 6.2.3.2 | Bearing, plain concrete | Check |
| F13 | factors.phi (others) | BNBC 2020's | - | Strut-and-tie, seismic shear, joints | Inherited |
| F14 | - | working stress design of concrete | Part 6 Ch 6 | Not covered | Not covered |

## Districts (zone, Vb km/h)

Bagerhat 1, 252; Bandarban 2, 200; Barguna 1, 260; Barishal 1, 256; Bhola 1, 225; Bogura 2, 198;
Brahmanbaria 2, 180; Chandpur 2, 160; Chapai Nawabganj 1, 130; Chattogram 2, 260; Chuadanga 1,
198; Cox's Bazar 2, 260; Cumilla 2, 196; Dhaka 2, 210; Dinajpur 2, 130; Faridpur 2, 202; Feni 2,
205; Gaibandha 3, 210; Gazipur 2, 215; Gopalganj 1, 242; Habiganj 3, 172; Jamalpur 3, 180;
Jashore 1, 205; Jhalokati 1, 260; Jhenaidah 1, 208; Joypurhat 2, 180; Khagrachhari 2, 180; Khulna
1, 238; Kishoreganj 3, 207; Kurigram 3, 210; Kushtia 1, 215; Lakshmipur 1, 162; Lalmonirhat 3,
204; Madaripur 1, 220; Magura 1, 208; Manikganj 2, 185; Meherpur 1, 185; Moulvibazar 3, 168;
Munshiganj 2, 184; Mymensingh 3, 217; Naogaon 2, 175; Narail 1, 222; Narayanganj 2, 195;
Narsingdi 2, 190; Natore 2, 198; Netrokona 3, 210; Nilphamari 3, 151; Noakhali 1, 184; Pabna 2,
202; Panchagarh 2, 130; Patuakhali 1, 260; Pirojpur 1, 260; Rajbari 2, 188; Rajshahi 1, 155;
Rangamati 2, 180; Rangpur 3, 209; Satkhira 1, 183; Shariatpur 1, 198; Sherpur 3, 200; Sirajganj
2, 160; Srimangal 3, 160; Sunamganj 3, 195; Sylhet 3, 195; Tangail 2, 160; Thakurgaon 2, 130.

The zones are the least sure part (Q2): in particular Rajshahi, Chapai Nawabganj, Noakhali,
Lakshmipur (taken 1), Faridpur, Rajbari, Dinajpur, Thakurgaon, Panchagarh (taken 2) and
Nilphamari, Gaibandha (taken 3) lie near the zone boundaries of the 1993 map.

## Inherited from BNBC 2020 (named BNBC 2020)

Live loads, dead loads, concrete and steel design (with the factors above), foundations, the
services, drift and irregularities, and every table not in `covers`.
