# Verification list: `aci318-asce7-22` (ASCE 7-22, ACI 318-19, AISC 360-22 / 341-22, NDS 2018, TMS 402-22)

No copy of ASCE/SEI 7-22 or ACI 318-19 was available while this pack was written (alpha 9,
track C1). Every value below was entered from the author's knowledge of the standards and
must be checked against the printed text before the pack is relied on. Clause numbers follow
the ASCE 7-16/7-22 numbering as recalled; where 7-22 renumbered a clause, fix the reference.

Status: **OK?** a value the author is confident of (still to be checked); **UNSURE** a value
or reference the author is not sure of (check first); **PRACTICE** SAEngine practice where the
standard gives no number (labelled so in the data).

SI values are the ones ASCE 7 prints beside the US customary ones (psf × 0.04788 kN/m²,
lb × 0.004448 kN, ft × 0.3048 m), rounded as printed.

## Occupancy (risk) categories — `occupancyCategories.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 1 | Ie = 1.0, 1.0, 1.25, 1.5 (I–IV) | Table 1.5-2 | Seismic importance factor | OK? |
| 2 | wind importance 1.0 for all | Sec 26.5.1 | No Iw in 7-16/7-22; V of the risk category's map | OK? |
| 3 | category descriptions | Table 1.5-1 | Short descriptions (not the table's text) | OK? |

## Live loads — `areaLoads.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 4 | 1.92 kN/m² (40 psf) | Table 4.3-1 | Residential private rooms, dwellings, classrooms, patient rooms, cell blocks, garages (passenger) | OK? |
| 5 | 2.40 kN/m² (50 psf), 8.90 kN | Table 4.3-1 | Offices, office access floors | OK? |
| 6 | 3.83 kN/m² (80 psf) | Table 4.3-1 | Corridors above the first floor (offices, schools, hospitals, libraries) | OK? |
| 7 | 4.79 kN/m² (100 psf) | Table 4.3-1 | Lobbies, first-floor corridors, assembly movable seats and platforms, dining, dance halls, gymnasiums, stairs, retail first floor, roof gardens, terraces, fire escapes, penal corridors, grandstands, stadium bleachers | OK? |
| 8 | 2.87 kN/m² (60 psf) | Table 4.3-1 | Assembly fixed seats, operating rooms, library reading rooms, roof promenades, walkways, stadium fixed seats | OK? |
| 9 | 3.59 kN/m² (75 psf) | Table 4.3-1 | Retail upper floors, bowling alleys, marquees | OK? |
| 10 | 6.00 kN/m² (125 psf) | Table 4.3-1 | Light storage, wholesale stores, light manufacturing | OK? |
| 11 | 11.97 kN/m² (250 psf) | Table 4.3-1 | Heavy storage, heavy manufacturing, driveways subject to trucking | OK? |
| 12 | 7.18 kN/m² (150 psf) | Table 4.3-1 | Library stacks, stage floors, armories | OK? |
| 13 | 1.44, 0.96, 0.48 kN/m² | Table 4.3-1 | Dwellings: habitable attics/sleeping 30, attics with storage 20, without 10 psf | OK? |
| 14 | 0.96 kN/m² (20 psf), 1.33 kN | Table 4.3-1, Sec 4.8 | Ordinary roofs, other awnings, storage above ceilings | OK? |
| 15 | 0.24 kN/m² (5 psf) nonreducible | Table 4.3-1 | Fabric awnings | OK? |
| 16 | balconies 4.79 kN/m² | Table 4.3-1 | 1.5 × the occupancy served, ≤ 100 psf: the row gives the cap | UNSURE (the rule, not the value) |
| 17 | 4.45 kN (1,000 lb), 8.90 (2,000 lb), 13.35 (3,000 lb), 35.60 (8,000 lb), 1.33 (300 lb) | Table 4.3-1, Sec 4.4, 4.10 | Concentrated loads | OK? |
| 18 | patch 762 mm (2.5 ft), 114 mm (4.5 in, vehicles), 50.8 mm (2 in, stair treads) | Sec 4.4, 4.10.1, Table 4.3-1 | Concentrated load areas | OK? |
| 19 | partitions minimum 0.72 kN/m² (15 psf) | Sec 4.3.2 | Partition allowance | OK? |
| 20 | partitions share 0.33, lightMax 5.5 kN/m | — | Drawn light partitions as a uniform load: inherited BNBC rule | PRACTICE |
| 21 | impact 100 %, 20 %, 50 %, 33 % | Sec 4.6.2-4.6.3 | Elevators, light machinery, reciprocating machinery, hangers | OK? |
| 22 | roofLive by slope: none | Sec 4.8.2 | ASCE reduces the 20 psf roof load by R1, R2 instead | OK? |
| 23 | vehicle and handrail barrier loads | Sec 4.5 | Not in the pack (not covered) | — |

## Live load reduction — `liveReduction.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 24 | L = L0 (0.25 + 4.57/√(KLL AT)) | Eq 4.7-1 | 15/√ft² in SI | OK? |
| 25 | KLL AT ≥ 37.16 m² (400 ft²) | Sec 4.7.2 | Members that may be reduced | OK? |
| 26 | ≥ 0.50 L0 one floor, ≥ 0.40 L0 two or more | Sec 4.7.2 | Limits | OK? |
| 27 | > 4.79 kN/m² not reduced; 20 % on 2+ floors | Sec 4.7.3 | Heavy live loads | OK? |
| 28 | garages 20 % on 2+ floors | Sec 4.7.4 | Passenger vehicle garages | OK? |
| 29 | assembly ≤ 4.79 kN/m² not reduced | Sec 4.7.5 | Assembly uses | OK? |
| 30 | one-way slab AT ≤ 1.5 L² | Sec 4.7.6 | One-way slabs | OK? |
| 31 | KLL 4, 4, 3, 2, 2, 2, 1 | Table 4.7-1 | Element factor | OK? |
| 32 | Lr = L0 R1 R2, 0.58 ≤ Lr ≤ 0.96 kN/m²; R1 1.2 − 0.011 AT (18.58–55.74 m²); R2 1.2 − 0.05 F (4–12) | Sec 4.8.2, Eqs 4.8-1 to 4.8-3 | Roof live load reduction | OK? |

## Load combinations — `combinations.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 33 | 1.4D | Sec 2.3.1 (1) | | OK? |
| 34 | 1.2D + 1.6L + 0.5(Lr or S or R) | Sec 2.3.1 (2) | | OK? |
| 35 | 1.2D + 1.6(Lr or S or R) + (L or 0.5W) | Sec 2.3.1 (3) | | OK? |
| 36 | 1.2D + 1.0W + L + 0.5(Lr or S or R) | Sec 2.3.1 (4) | | OK? |
| 37 | 0.9D + 1.0W | Sec 2.3.1 (5) | | OK? |
| 38 | 1.2D + Ev + Eh + L + **0.2S** | Sec 2.3.6 (6) | 7-16 has 0.2S; 7-22 may print 0.15S | UNSURE |
| 39 | 0.9D − Ev + Eh | Sec 2.3.6 (7) | | OK? |
| 40 | F with D's factor; H 1.6 where it adds | Sec 2.3.1 notes | | OK? |
| 41 | F left out of 0.9D combinations | — | An empty tank: on the safe side | PRACTICE |
| 42 | L at 0.5 in (3), (4), (6) where L0 ≤ 4.79 kN/m², not garages or assembly | Sec 2.3.1 exc. 1, 2.3.6 exc. 1 | | OK? |
| 43 | ASD: D; D + L; D + (Lr/S/R); D + 0.75L + 0.75(Lr/S/R); D + 0.6W; D + 0.75L + 0.45W + 0.75(Lr/S/R); 0.6D + 0.6W | Sec 2.4.1 (1-7) | | OK? |
| 44 | ASD seismic: D + 0.7Ev + 0.7Eh; D + 0.525Ev + 0.525Eh + 0.75L + **0.75S**; 0.6D − 0.7Ev + 0.7Eh | Sec 2.4.5 (8-10) | 7-22 may have changed the S factor | UNSURE |
| 45 | allowable stress increase 1.2 with Em | Sec 12.4.3.3 | | OK? |
| 46 | flood: coastal V/Coastal A 1.0W → 1.0W + 2.0Fa; noncoastal A 0.5W + 1.0Fa; ASD 1.5Fa / 0.75Fa added to (5), (6), (7) | Sec 2.3.2, 2.4.2 | Numbering may differ in 7-22 | UNSURE (clause no.) |
| 47 | T with 1.0 | Sec 2.3.4 | Self-straining loads, factor at least 1.0 | OK? |
| 48 | cantilever uplift 0.2D in SDC D-F | Sec 12.4.4 | | OK? |
| 49 | serviceability D + L, D + 0.5L, D + 0.5L + 0.6W | Appendix C / CC.2 | 0.6W as the service wind | PRACTICE |
| 50 | P-Delta preload 1.2D + 1.0L | Sec 2.3.6 (6) | Gravity part | OK? |

## Seismic — `seismic.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 51 | SDS = (2/3) SMS, SD1 = (2/3) SM1 | Eqs 11.4-3, 11.4-4 | Design values from MCER | OK? |
| 52 | T0 = 0.2 TS, TS = SD1/SDS; Sa = SDS (0.4 + 0.6 T/T0) below T0; SDS to TS; SD1/T to TL; SD1 TL/T² beyond | Sec 11.4.6, Fig 11.4-1 | Two-period spectrum | OK? |
| 53 | multi-period design spectrum used where entered | Sec 11.4.5.1 | 7-22's multi-period spectrum from the hazard tool | OK? |
| 54 | SMS = 0.9 × max Sa (0.2–5 s); SM1 = max T·Sa (1–2 s; 1–5 s for vs30 ≤ 442 m/s) | Sec 21.4 (applied to the multi-period MCER spectrum) | Whether 11.4 points to 21.4 this way for the mapped spectrum | UNSURE |
| 55 | SDS bands 0.167, 0.33, 0.50 | Table 11.6-1 | SDC by SDS | OK? |
| 56 | SD1 bands 0.067, 0.133, 0.20 | Table 11.6-2 | SDC by SD1 | OK? |
| 57 | A, B, C, D (I–III); A, C, D, D (IV) by band; E (I–III) / F (IV) where S1 ≥ 0.75 | Sec 11.6 | The more severe of the two tables | OK? |
| 58 | the 11.6 exception (SDC from Table 11.6-1 alone for short-period buildings) | Sec 11.6 | Not applied (conservative) | — |
| 59 | Cs = SDS/(R/Ie) ≤ SD1/(T R/Ie) (T ≤ TL), SD1 TL/(T² R/Ie) | Eqs 12.8-2 to 12.8-4 | ELF coefficient | OK? |
| 60 | Cs ≥ 0.044 SDS Ie ≥ 0.01 | Eq 12.8-5 | | OK? |
| 61 | Cs ≥ 0.5 S1/(R/Ie) where S1 ≥ 0.6 g | Eq 12.8-6 | | OK? |
| 62 | Cu 1.4 (SD1 ≥ 0.3), 1.5 (0.2), 1.6 (0.15), 1.7 (≤ 0.1) | Table 12.8-1 | Linear between | OK? |
| 63 | Ct, x = 0.0466, 0.9 (RC MF); 0.0724, 0.8 (steel MF); 0.0731, 0.75 (EBF, BRBF); 0.0488, 0.75 (other) | Table 12.8-2 (SI) | Approximate period | OK? |
| 64 | k = 1 (T ≤ 0.5 s), 2 (T ≥ 2.5 s), linear | Sec 12.8.3 | Vertical distribution (engine's, unchanged) | OK? |
| 65 | site classes A, B, BC, C, CD, D, DE, E, F by vs30 (> 1524, 914–1524, 640–914, 442–640, 305–442, 213–305, 152–213, < 152 m/s) | Table 20.2-1 | 7-22's nine classes | OK? |
| 66 | site class F: site response analysis | Sec 11.4.8, 20.2.1 | Warning; SE assumed for the SDC | OK? |
| 67 | R, Ω0, Cd and height limits of every system row (see `seismic.json`) | Table 12.2-1 | A.1, A.2, B.1-B.5, C.1, C.3-C.7, D.1-D.4, E.1, E.2, F, H and the masonry, BRBF and SPSW rows; heights 160 ft = 48.8 m, 100 ft = 30.5 m, 35 ft = 10.7 m | UNSURE (row numbers; E.3 masonry Cd 2.5; the E row with ordinary RC walls R 5.5, Cd 4.5) |
| 68 | one EBF row (8, 2, 4) and one BRBF row (8, 2.5, 5) | Table 12.2-1 | SAEngine's two ids of each take the same row | OK? |
| 69 | detailing ordinary (B), intermediate (C), special (D-F) | ACI 318-19 Sec 18.2.1 | Concrete systems | OK? |
| 70 | drift Δa/hsx 0.020, 0.020, 0.015, 0.010 (I–IV); 0.025/0.020/0.015 ≤ 4 storeys with drift-tolerant finishes; masonry cantilever 0.010, other masonry 0.007 | Table 12.12-1 | | OK? |
| 71 | Δa/ρ for moment frames in SDC D-F | Sec 12.12.1.1 | | OK? |
| 72 | modal scaling to 100 % of V | Sec 12.9.1.4.1 | Forces (drifts per 12.9.1.4.2) | OK? |
| 73 | 90 % mass participation | Sec 12.9.1.1 | The alternative to 100 % with residual mode | UNSURE (7-22 wording) |
| 74 | accidental eccentricity 5 %; Ax = (δmax/1.2δavg)² ≤ 3.0 | Sec 12.8.4.2-12.8.4.3, Eq 12.8-14 | | OK? |
| 75 | 100 % + 30 % orthogonal | Sec 12.5.3.1 | | OK? |
| 76 | Ev = 0.2 SDS D (pgaFactor 0.4 × verticalFactor 0.5) | Sec 12.4.2.2 | SAEngine maps a_h = 0.4 SDS | OK? (mapping PRACTICE) |
| 77 | W: 25 % of floor live load in storage areas | Sec 12.7.2 | Storage taken as L0 > 4.79 kN/m² | PRACTICE |
| 78 | W: partitions in full (≥ 0.48 kN/m²) | Sec 12.7.2 | | OK? |
| 79 | θ = Px Δ Ie/(Vx hsx Cd); θmax = 0.5/(β Cd) ≤ 0.25 | Eqs 12.8-16, 12.8-17 | Ie cancels the one in Δ | OK? |
| 80 | Px with no factor above 1.0 | Sec 12.8.7 | | OK? |
| 81 | torsion 1.2 / 1.4 | Table 12.3-1 1a/1b | | OK? |
| 82 | re-entrant 15 %, diaphragm opening 50 %, stiffness change 50 % | Table 12.3-1 2, 3 | | OK? |
| 83 | non-parallel tolerance 5° | Table 12.3-1 5 | The table says "not parallel" | PRACTICE |
| 84 | soft 70 % / 80 %, extreme soft 60 % / 70 %, mass 150 %, geometry 130 %, weak 80 %, extreme weak 65 % | Table 12.3-2 | | OK? |
| 85 | in-plane offset counted above 0.01 × the element length | Table 12.3-2 type 4 | 7-16+ counts any offset loading the supports | PRACTICE |
| 86 | orthogonal for non-parallel systems in SDC C-F | Sec 12.5.3-12.5.4 | | OK? |
| 87 | +25 % connection forces, SDC D-F, types 1a, 1b, 2, 3, 4, vertical 4 | Sec 12.3.3.4 | | OK? |
| 88 | separation δM (property line), √(δM1² + δM2²) | Sec 12.12.3 | No reduction for aligned floors | OK? |
| 89 | the 5 % spectrum, no damping correction | Sec 11.4.6 | Damping modification is Ch 17-18 | OK? |
| 90 | procedure selection (Table 12.6-1), soft storey factors, linear response history | Sec 12.6, 12.9.2 | Not covered (null) | — |

## Wind — `wind.json` (over the BNBC 2020 tables it extends)

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 91 | α 7.5, 9.8, 11.5; zg 3280, 2460, 1935 ft (999.7, 749.8, 589.8 m) for B, C, D | Table 26.11-1 | 7-22's new terrain constants | UNSURE (recalled change from 7-16's 7.0/9.5/11.5, 1200/900/700 ft) |
| 92 | Kz = 2.41 (z/zg)^(2/α), z ≥ 15 ft (4.57 m) | Table 26.10-1 note | 2.41 goes with the new zg (Kz ≈ 1.0 at 33 ft in C) | UNSURE (with 91) |
| 93 | c, ℓ, ε̄, ᾱ, b̄, zmin of B, C, D | Table 26.11-1 | Gust constants, as earlier editions | OK? |
| 94 | Kd = 0.85 | Table 26.6-1 | Buildings, MWFRS and C&C | OK? |
| 95 | G = 0.85 (rigid) | Sec 26.11.4 | | OK? |
| 96 | Ke = 1.0 | Sec 26.9 | Permitted; ground elevation not applied | OK? |
| 97 | K1/(H/Lh) ridge 1.30/1.45/1.55, escarpment 0.75/0.85/0.95, hill 0.95/1.05/1.15; γ 3, 2.5, 4; μ 1.5 (escarpment downwind 4) | Fig 26.8-1 | Topography | OK? |
| 98 | H ≥ 60 ft (18.3 m) in B, 15 ft (4.5 m) in C, D | Sec 26.8.1 | | OK? |
| 99 | design wind load cases 0.75, ±0.15B, 0.563 | Fig 27.3-8 | Inherited (same values) | OK? |
| 100 | wall and roof Cp (Fig 27.3-1), GCpf (Fig 28.3-1), GCpi ±0.18/±0.55 (Table 26.13-1) | Ch 27, 28, 26.13 | Inherited from BNBC (= ASCE 7-05) | OK? (7-22 adds "partially open" ±0.18, not offered) |
| 101 | C&C walls (Fig 30.3-1, 30.5-1) | Ch 30 | Inherited from BNBC (= ASCE 7-05) | OK? |
| 102 | C&C roofs h ≤ 60 ft | Fig 30.3-2A to 2I | **Inherited 7-05 values and zones; 7-16/7-22 changed them (zones 1′, 1, 2, 3)** | NOT COVERED: values are the earlier edition's |
| 103 | open buildings, signs, chimneys, lattice towers, rooftop equipment | Ch 27, 29, 30 | Inherited from BNBC | UNSURE (not re-checked against 7-22) |

## Snow — `snow.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 104 | pf = 0.7 Ce Ct pg, no Is | Eq 7.3-1, Sec 7.2 | 7-22 ground snow by risk category | UNSURE (that Is was removed) |
| 105 | Ce 0.9/1.0/1.2 (B), 0.9/1.0/1.1 (C), 0.8/0.9/1.0 (D), 0.7/0.8 (above tree line, Alaska) | Table 7.3-1 | | OK? |
| 106 | Ct 1.0 heated, 1.1 just above freezing, 1.2 unheated, 1.3 freezer, 0.85 greenhouse | Table 7.3-2 | 7-22 may give Ct by the roof's thermal resistance | UNSURE |
| 107 | Cs: warm roofs 5°/30°, Ct 1.1 10°/37.5°, Ct ≥ 1.2 15°/45°, all to 0 at 70° | Fig 7.4-1 | Slippery / other | OK? |
| 108 | pm = pg (pg ≤ 0.96 kN/m²), 0.96 kN/m² above, slopes < 15° | Sec 7.3.3 | | UNSURE (7-22 form) |
| 109 | γ = 0.426 pg + 2.2 ≤ 4.7 kN/m³ | Eq 7.7-1 | | OK? |
| 110 | hd = 1.5 √(pg^0.74 lu^0.70 W2^1.7 / γ) (ft, psf, pcf); lu ≥ 20 ft | Eq 7.8-1 | 7-22's drift with the winter wind parameter | UNSURE (coefficients and exponents) |
| 111 | windward drift 0.75 hd; w = 4 hd; hd > hc: w = 4 hd²/hc ≤ 8 hc | Sec 7.8 | | OK? |
| 112 | W: 20 % of the snow where pf > 1.44 kN/m² | Sec 12.7.2 | In the table; not yet added to the masses | — |

## Flood, rain, diaphragms — `flood.json`, `transfer.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| 113 | design flood: 1 % annual chance for all categories | Sec 5.3, 1.2 | Enter the DFE as the flood level | OK? |
| 114 | hydrostatic, hydrodynamic (Cd 1.25 min), breaking wave Cp 1.6/2.8/3.2/3.5, debris 1,000 lb | Sec 5.4, C5 | Inherited from BNBC (= ASCE 7-05 Ch 5) | UNSURE (7-22 Ch 5 updates) |
| 115 | Bangladesh surge regions and stations removed | — | | — |
| 116 | R = 0.0098 (ds + dh + dp) | Eq 8.2-1 | Depth entered as ds + dh + dp; controlled drainage allowance inherited (0.25 kN/m²) | UNSURE (the allowance) |
| 117 | Fpx: 0.2 ≤ Fpx/(SDS Ie wpx) ≤ 0.4 | Eqs 12.10-1 to 12.10-3 | | OK? |
| 118 | collectors with Ω0 in SDC C-F | Sec 12.10.2.1 | | OK? |
| 119 | the alternative diaphragm design (Rs) | Sec 12.10.3 | Not covered | — |

## Concrete: ACI 318-19 (track C2)

No copy of ACI 318-19 / 318M-19 was available either. SI values are those of ACI 318M-19 as
recalled (MPa, mm); where 318M prints a rounded SI coefficient the recalled one is entered.
Clause references in `designClauses.json`, `citations.json` and the tables' `clauses` follow
the ACI 318-19 numbering as recalled; each must be checked with the values.

### Strength reduction — `factors.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| C1 | φ 0.90 / 0.65 / 0.75, transition εty to εty + 0.003 | Table 21.2.2 | Tension-controlled, tied, spiral (the engine already used εty + 0.003) | OK? |
| C2 | φ 0.75 shear, torsion, two-way shear | Table 21.2.1(b), (c) | | OK? |
| C3 | φ 0.60 shear where Vn < shear at Mn | 21.2.4.1 | Special walls, IMF | OK? |
| C4 | φ 0.85 joints, diagonally reinforced coupling beams | 21.2.4.3, 21.2.4.4 | | OK? |
| C5 | φ 0.75 strut-and-tie, 0.65 bearing, 0.60 plain | Table 21.2.1(d), (g), (k) | | OK? |
| C6 | 0.75 of Pc in δ | Eq 6.6.4.5.2 | Moment magnifier | OK? |

### Concrete and steel — `materials.json`, `concrete.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| C7 | εcu 0.003, Es 200 000 MPa | 22.2.2.1, 20.2.2.2 | | OK? |
| C8 | f'c ≥ 21 MPa; lightweight ≤ 35 MPa in special frames and walls | Table 19.2.1.1 | | OK? |
| C9 | lightweight concrete up to 1840 kg/m³ | 2.3 | Definition (was 1850 in the BNBC table) | UNSURE (1840 vs 1850) |
| C10 | seismic bars: Grades 280, 420, 550; largest 550 | 20.2.2.4-20.2.2.5, 18.2.6 | Grade 690 for special walls not offered | UNSURE (Grade 280 permission) |
| C11 | actual fy ≤ specified + 125 MPa; fu/fy ≥ 1.25 | 20.2.2.5(b), ASTM A706 | | OK? |
| C12 | retest margin 20 MPa | (ACI 318-08 21.1.5.2) | Not in 318-19: kept as practice | PRACTICE |
| C13 | Ec = 4700 √f'c, 0.043 wc^1.5 √f'c (1440-2560 kg/m³) | 19.2.2.1 | | OK? |
| C14 | λ 0.85 sand-lightweight, 0.75 all-lightweight | Table 19.2.4.2 | | OK? |
| C15 | brick aggregate taken as normal weight (Ec, shrinkage × 1.0) | — | ACI has no brick aggregate rule | PRACTICE |
| C16 | shrinkage and temperature steel 0.0018 for every grade | Table 24.4.3.2 | Changed from 318-14 | OK? |
| C17 | least εt of slabs 0.005 | 7.3.3.1, 8.3.3.1 | 318-19 asks for tension-controlled slabs, εty + 0.003 (0.0051 at 420 MPa) | UNSURE (the rule and the fixed value) |
| C18 | fyt of shear steel ≤ 420 MPa | Table 20.2.2.4(a) | | OK? |
| C19 | bar sizes No. 10-36 as 10, 13, 16, 19, 22, 25, 29, 32, 36 mm | ASTM A615/A706 | Sets by use (stirrups 10, 13 ...) | PRACTICE |
| C20 | assumed covers: lintels 40, stairs 20, pile caps 75 mm | Table 20.5.1.3.1 | When no bars are entered | PRACTICE |
| C21 | two-way slab thickness ln/33, 36, 36 (280), 30, 33, 33 (420), 28, 31, 31 (520); drop panels 36, 40, 40 / 33, 36, 36 / 31, 34, 34 | Table 8.3.1.1 | Same as the extended pack | OK? |
| C22 | one-way slabs l/20, 24, 28; beams l/16, 18.5, 21; cantilevers l/10, l/8 | Tables 7.3.1.1, 9.3.1.1 | | OK? |
| C23 | deflection limits l/180, l/360, l/480, l/240; ξ 1.0, 1.2, 1.4, 2.0 | Tables 24.2.2, 24.2.4.1.3 | | OK? |
| C24 | Ie = Icr / (1 - ((2/3) Mcr/Ma)² (1 - Icr/Ig)), Ig up to (2/3) Mcr | Table 24.2.3.5 | Method `bischoff` | OK? |
| C25 | cracked stiffness 0.70 columns, 0.35 beams, 0.25 slabs, 0.35 / 0.70 walls | Table 6.6.3.1.1(a) | | OK? |
| C26 | Q ≤ 0.05; klu/r ≤ 22; 34 - 12 M1/M2 ≤ 40; δs ≤ 1.5; second-order ≤ 1.4 first-order | 6.6.4.3, 6.2.5, 6.6.4.6.2, 6.2.6 | | OK? |
| C27 | walls ρl 0.0012 / 0.0015, ρt 0.0020 / 0.0025 (≤ No. 16 and fy ≥ 420 / others); 0.0025 where Vu > 0.5 φVc; 3h and 450 mm; two layers above 250 mm | Table 11.6.1, 11.6.2, 11.7.2.1, 11.7.2.3 | | OK? |
| C28 | torsion θ 45°, Ao 0.85 Aoh, fy ≤ 420, ph/8 and 300 mm, longitudinal 300 mm, db ≥ 0.042 s and 10 mm | 22.7.6.1, Table 20.2.2.4(a), 9.7.6.3.3, 9.7.5 | | OK? |
| C29 | prestress: the extended pack's numbers; punching of prestressed slabs by 22.6.5.5 (βp ≤ 0.29, 0.3 fpc, √f'c ≤ 5.8, fpc 0.9-3.5 MPa) | 22.6.5.5, Ch 20, 24.5, 8.6, 8.7.5, 25.9 | `punchingMethod` precompression | UNSURE (clause numbers of the prestress keys) |

### Detailing and seismic — `detailing.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| C30 | crack control 380 (280/fs) - 2.5 cc ≤ 300 (280/fs), fs = 2/3 fy | Table 24.3.2 | | OK? |
| C31 | skin steel h > 900 mm over h/2 | 9.7.2.3 | | OK? |
| C32 | flange overhang 8 hf, ln/8 each side (taken as bf ≤ span/4), one side 6 hf, ln/12 | Table 6.3.2.1 | sw/2 not checked | UNSURE (span/4 approximation) |
| C33 | integrity 1/4 positive, 1/6 negative, two bars | 9.7.7.1-9.7.7.2 | | OK? |
| C34 | shear friction μ 1.4, 1.0, 0.6, 0.7 λ; min(0.2 f'c, 3.3 + 0.08 f'c, 11), min(0.2 f'c, 5.5) | Tables 22.9.4.2, 22.9.4.4 | | OK? |
| C35 | SMF: ln ≥ 4d, b ≥ 0.3 h and 250 mm, ρ ≤ 0.025; columns ≥ 300 mm, ratio ≥ 0.4, 0.01 ≤ ρ ≤ 0.06; hx ≤ 350 mm; first hoop 50 mm | 18.6.2, 18.6.3.1, 18.7.2, 18.7.4.1, 18.7.5.2(e), 18.6.4.4 | | OK? |
| C36 | confinement fyt ≤ 690 MPa | Table 20.2.2.4(a) | 100 ksi | OK? |
| C37 | joints γ 1.7, 1.2, 1.0 (continuous columns); 1.2, 1.0, 0.7 where the column ends at the joint | Table 18.8.4.3 | SI of 20, 15, 12, 8; 318M may print 1.25 for 15 | UNSURE (SI coefficients; mapping of the table's beam continuity / confinement cases to the confined-faces count) |
| C38 | T = 1.25 fy As; ΣMnc ≥ 1.2 ΣMnb; Vc = 0 below 0.05 Ag f'c | 18.8.2.1, 18.7.3.2, 18.7.6.2.1 | | OK? |
| C39 | special walls: ρ relaxed below 0.083 λ √f'c Acv; two curtains above 0.17 λ √f'c Acv or hw/lw ≥ 2.0 | 18.10.2.1, 18.10.2.2 | `curtainAspect` 2.0 | OK? |
| C40 | boundary elements c ≥ lw / (600 · 1.5 δu/hw), δu/hw ≥ 0.005; stress 0.2 / 0.15 f'c | 18.10.6.2, 18.10.6.3 | `driftFactor` 1.5 | OK? |
| C41 | Ve = Ωv ωv Vu ≤ 3 Vu; Ωv 1.5 where hw/lw > 1.5; ωv 0.9 + ns/10 (ns ≤ 6), 1.3 + ns/30 ≤ 1.8; 1.0 where hw/lw < 2.0 | 18.10.3.3 | Ωv taken as its lower bound 1.5 (Mpr/Mu not computed), ns = hw / storey height | UNSURE (the table's form and ranges, Ωv bound) |
| C42 | coupling beams and wall piers: the generic ACI 318-19 values (hoops 150 mm / 6 db, legs 200 mm, 1.25 ld, ...) | 18.10.7.4, 18.10.8.1, 2.3 | Same numbers as the extended pack | OK? |
| C43 | hooks 180° 4 db / 65 mm, 90° 12 db; ties 6 db (≤ No. 16), 12 db, 135° 6 db / 75 mm | Tables 25.3.1, 25.3.2 | | OK? |
| C44 | bends 6 db to No. 25, 8 db to No. 36, 10 db No. 43-57 | Table 25.3.1 | | OK? |
| C45 | ld simplified fy ψt ψe ψg / (2.1 or 1.7, 1.4 or 1.1 λ √f'c) db; general Eq 25.4.2.4a with (cb + Ktr)/db ≤ 2.5, Ktr = 40 Atr / (s n); √f'c ≤ 8.3; ≥ 300 mm | 25.4.2.1-25.4.2.4, 25.4.1.4 | | OK? |
| C46 | ψg 1.0 (≤ 420), 1.15 (550), 1.3 (690) | Table 25.4.2.5 | | OK? |
| C47 | ldh = fy ψe ψr ψo ψc db^1.5 / (23 λ √f'c) ≥ 8 db, 150 mm; ψr 1.6 without the ties, ψo 1.25 without the side cover, ψc = f'c/105 + 0.6 below 42 MPa | 25.4.3.1, Table 25.4.3.2 | `hookMethod` powerDiameter | UNSURE (SI coefficient 23, ψc divisor 105) |
| C48 | ldt = fy ψe ψp ψo ψc db^1.5 / (31 λ √f'c) ≥ 8 db, 150 mm; ψp 1.6 | 25.4.4.2, Table 25.4.4.3 | Shown in the development worksheet and Design Reinforcement's note | UNSURE (SI coefficient 31) |
| C49 | ldc = max(0.24 fy ψr / (λ √f'c), 0.043 fy ψr) db ≥ 200 mm, × 0.75 confined | 25.4.9.2-25.4.9.3 | | OK? |
| C50 | laps class A 1.0 ld, B 1.3 ld, ≥ 300 mm; no laps above No. 36 | 25.5.2, 25.5.1.1 | | OK? |
| C51 | compression laps 0.071 fy db (≤ 420), (0.13 fy - 24) db, × 4/3 below 21 MPa | 25.5.5.1 | | OK? |
| C52 | SMF laps outside joints and 2h, hoops d/4 and 100 mm; column laps in the middle half | 18.6.3.3, 18.7.4.3 | | OK? |
| C53 | special wall bars 1.25 ld where they may yield | 18.10.2.3 | | OK? |

### Methods and foundations — `slabMethods.json`, `wallMethods.json`, `compositeConcrete.json`, `foundations.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| C54 | direct design and equivalent frame: the extended pack's numbers | 8.10, 8.11 | Clause references only | OK? |
| C55 | slender walls (alternative method) | 11.8 | Clause references only | OK? |
| C56 | composite members 0.55, (1.8 + 0.6 ρv fy) λ ≤ 3.5 MPa | Table 16.4.4.2 | Clause references only | OK? |
| C57 | strut-and-tie βs 0.4 for interior struts without 23.5 reinforcement and in tension members; βc = 1.0 | Table 23.4.3(a), 23.4.3 | Was 0.6 λ in 318-14 | UNSURE |
| C58 | two-way slab coefficient method, stair spans, masonry lintel wind rule | — | ACI 318-19 has none: the extended pack's, cited as BNBC 2020 | PRACTICE |
| C59 | lintel bearing 100 mm, span/600 | TMS 402 5.2.1.3-5.2.1.4 | Cited as TMS 402-22 | UNSURE (clause numbers) |

## Steel: AISC 360-22, AISC 341-22 (track C3)

No copy of AISC 360-22, AISC 341-22 or TMS 402-22 was available. Values are entered from the
author's knowledge of the specifications; section numbers follow the 2016 arrangement (kept
in 2022 as recalled) and equation numbers are given only where recalled with confidence. SI
values are those of the SI tables of AISC 360 (Tables J3.1M-J3.4M, J3.2 in MPa) as recalled.
Steel shapes are SAEngine's own shape list (owner decision), not the AISC shapes database.

### Design basis and φ / Ω — `steel.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S1 | designMethod LRFD; ASD selectable, Ω = 1.5 / φ for limit states without a listed Ω | Sec B3.1, B3.2 | `omegaFromPhi` 1.5 is how AISC relates φ and Ω (SAEngine practice for the few unlisted ones: HSS connection factors) | OK? |
| S2 | φ 0.90 / 0.75, Ω 1.67 / 2.00 | Sec D2 | Tension yielding / rupture | OK? |
| S3 | φ 0.90, Ω 1.67 | Sec E1, F1, G1 | Compression, flexure, shear | OK? |
| S4 | φ 1.00, Ω 1.50 rolled I webs with h/tw ≤ 2.24 √(E/Fy) | Sec G2.1(a) | key `shearWebYield` | OK? |
| S5 | φ 0.75, Ω 2.00 bolts, bearing, block shear, welds, anchor rods | J2.4, J3.6-J3.7, J3.10, J4.3, J9 | | OK? |
| S6 | φ 0.65, Ω 2.31 concrete bearing | Sec J8 | Was 0.60 in BNBC 2020 | OK? |
| S7 | φ 0.90 / 1.00 / 0.75 / 0.85 / 0.90 / 0.90 (Ω 1.67 / 1.50 / 2.00 / 1.76 / 1.67 / 1.67) | Sec J10.1-J10.6 | Flange bending, web yielding, crippling, sidesway, compression buckling, panel zone | OK? |
| S8 | φ 1.00 / 0.75 (Ω 1.50 / 2.00) elements in shear | Sec J4.2 | | OK? |
| S9 | Ω 1.50 slip (standard holes) | Sec J3.8 | With hsc 0.85 / 0.70 this gives Ω 1.76 / 2.14 | OK? |
| S10 | Ω 1.67 torsion, Ω 2.00 bracing stiffness | Sec H3, App 6 | | OK? |
| S11 | KL/r ≤ 200, L/r ≤ 300 | Sec E2, D1 (user notes) | Checked as limits (SAEngine practice; flags for beams) | PRACTICE |

### Member methods — `steel.json` `memberMethods`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S12 | compressionSlender `effectiveWidth`: Pn = Fcr Ae, be = b (1 − c1 √(Fel/Fcr)) √(Fel/Fcr), Fel = (c2 λr/λ)² Fy when λ > λr √(Fy/Fcr) | Sec E7.1, Eqs E7-1 to E7-5 | Replaces Q = Qs Qa of 360-10 | OK? |
| S13 | c1, c2 = 0.18, 1.31 (stiffened), 0.20, 1.38 (walls of rectangular HSS), 0.22, 1.49 (other: flanges, legs, stems) | Table E7.1 | | OK? |
| S14 | round HSS Ae / Ag = 0.038 E / (Fy D/t) + 2/3 | Sec E7.2, Eq E7-6 | | OK? |
| S15 | webShear `cv1`: Cv1 = 1 for h/tw ≤ 1.10 √(kv E/Fy), else 1.10 √(kv E/Fy) / (h/tw); kv 5.34 unstiffened (and a/h > 3) | Sec G2.1(b), Eqs G2-3, G2-4 | No elastic branch (Cv2 keeps it, Sec G2.2) | OK? |
| S16 | tension field: Eq G2-7 (1.15 √(1 + (a/h)²)) within 2 Aw/(Afc + Aft) ≤ 2.5, h/bf ≤ 6.0; Eq G2-8 (1.15 (a/h + √(1 + (a/h)²))) outside; no limit (260/(h/tw))² on a/h | Sec G2.2 | The assignment of G2-7 / G2-8 to the two cases as recalled | UNSURE |
| S17 | tees `lengthLimits`: Lp = 1.76 ry √(E/Fy), Lr = 1.95 (E/Fy) √(Iy J)/Sx √(2.36 (Fy/E) d Sx/J + 1); stem in compression Mcr ≤ My | Sec F9.2 | Sx the least elastic modulus | OK? |
| S18 | tee flange local buckling Mn = Mp − (Mp − 0.7 Fy Sxc)(λ − λpf)/(λrf − λpf) ≤ 1.6 My; slender 0.7 E Sxc / (bf/2tf)² | Sec F9.3 | Changed in 2016 as recalled | UNSURE |
| S19 | tee stem local buckling: d/tw ≤ 0.84 √(E/Fy) Fcr = Fy; ≤ 1.52 √(E/Fy) (1.43 − 0.515 (d/tw) √(Fy/E)) Fy; else 1.52 E / (d/tw)² | Sec F9.4(b) | | OK? |
| S20 | teeCompression `general`: Fe of singly symmetric members, then Eqs E3-2, E3-3 | Sec E4 | The tee-specific Fcry/Fcrz form of 360-05 not used | UNSURE |
| S21 | rectangular HSS lateral-torsional buckling: Lp = 0.13 E ry √(J Ag)/Mp, Lr = 2 E ry √(J Ag)/(0.7 Fy Sx), elastic Mn = 2 E Cb √(J Ag)/(Lb/ry) | Sec F7.4 | | OK? |
| S22 | Sec F2-F6, F8, F10-F12, H1-H3 equations as the default pack's (AISC 360-05 = 360-22 for these) | — | Clause references only changed | OK? |

### Connections — `steel.json` `connections`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S23 | Fnt 310 / 620 / 780 MPa (A307, Group A, Group B) | Table J3.2 | | OK? |
| S24 | Fnv 188 (A307), 372 / 469 (Group A N / X), 469 / 579 (Group B N / X) MPa | Table J3.2 | A307 188 vs 186 (27 ksi) | UNSURE (A307) |
| S25 | threaded parts Fnt 0.75 Fu, Fnv 0.450 Fu (N), 0.563 Fu (X) | Table J3.2 | | OK? |
| S26 | pretension (kN) as BNBC 2020: 91-475 Group A, 114-595 Group B (M16-M36) | Table J3.1M | Inherited values, AISC clause | OK? |
| S27 | μ 0.30 (Class A), 0.50 (Class B), Du 1.13, φ 1.00 / 0.85 / 0.70 by hole (hsc) | Sec J3.8, Eq J3-4 | Short slots taken at 0.85 whatever their direction (conservative) | OK? |
| S28 | edge distances 22, 26, 28, 30, 34, 38, 46 mm (M16-M36), 1.25 d above; no sheared-edge increase | Table J3.4M | | OK? |
| S29 | holes d + 2 (M16-M24), d + 3 above | Table J3.3M | Inherited values | OK? |
| S30 | long joints: Fnv × 0.833 beyond 950 mm | Table J3.2 note | Applied by SAEngine to tension splices only | UNSURE (scope) |
| S31 | Pp = 0.85 f'c A1, ≤ 1.7 f'c A1, 0.85 √(A2/A1) | Sec J8, Eqs J8-1, J8-2 | | OK? |
| S32 | fillet weld minimum (Table J2.4), maximum along edges (J2.2b): as BNBC 2020 | Table J2.4, Sec J2.2b | Inherited values | OK? |
| S33 | connection notes: BNBC 2020 references mapped to AISC 360-22 sections and equations (`references`) | Ch J | Chapter K (HSS) equations keep the BNBC 2020 number, named so | UNSURE (equation numbers J3-3a, J3-5a, J3-6a/c, J10-5a/b) |
| S34 | HSS connection φ (Chapter K): the default pack's (360-05) values | Ch K | 2016 rearranged Chapter K | UNSURE |

### Stability — `steelStability.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S35 | Ni = 0.002 α Yi, additive 0.001 α Yi; EI* = 0.8 τb EI, EA* = 0.8 EA; τb = 4 (αPr/Py)(1 − αPr/Py) above 0.5 | Sec C2.2b, C2.3 | Same as BNBC 2020; 360-22 writes τb with Pns (= Py for nonslender) | OK? |
| S36 | Notional loads in the gravity-only combinations while Δ2nd/Δ1st ≤ 1.7 | Sec C2.2b(4) | Was 1.5 (360-10, BNBC 2020) | UNSURE |
| S37 | Effective length method while Δ2nd/Δ1st ≤ 1.5; K = 1 ≤ 1.1; first-order method αPr ≤ 0.5 Py, Ni = 2.1 α (Δ/L) Yi ≥ 0.0042 Yi | App 7, Sec 7.2-7.3 | | OK? |
| S38 | α 1.0 (LRFD), 1.6 (ASD); ASD analysis at 1.6 × the ASD combinations | Sec C2.1(4) | SAEngine keeps the direct analysis method LRFD only | OK? |
| S39 | P-δ neglected while αPr < 0.15 PeL | App 8 | | UNSURE |

### Seismic: AISC 341-22 — `steelSeismic.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S40 | width-thickness limits of √(E/(Ry Fy)) (`expectedYield`) | Table D1.1 | 341-10 used √(E/Fy) | OK? |
| S41 | λhd 0.32, λmd 0.40: flanges of I-shapes, channels, tees; angle legs; tee stems | Table D1.1 | | OK? |
| S42 | webs λhd: Ca ≤ 0.114: 2.57 (1 − 1.04 Ca); above 0.88 (2.68 − Ca) ≥ 1.57 | Table D1.1 | SMF beam webs 2.57 | OK? |
| S43 | webs λmd: Ca ≤ 0.114: 3.96 (1 − 3.04 Ca); above 1.29 (2.12 − Ca) ≥ 1.57 | Table D1.1 | | OK? |
| S44 | rectangular HSS walls λhd 0.65, λmd 0.76 | Table D1.1 | λmd read as 0.64 √(E/Fy) of 341-10 at Ry 1.4 | UNSURE (λmd) |
| S45 | round HSS D/t λhd 0.053, λmd 0.062 E/(Ry Fy) | Table D1.1 | | OK? |
| S46 | Ca = Pu / (φc Py), φc 0.90, Py = Fy Ag | Table D1.1 note | Whether Py is Ry Fy Ag in 341-22 | UNSURE |
| S47 | H-pile flanges and webs, flat bars, the relaxed ratio 2.0 of SMF columns: the default pack's | Table D1.1 | Not revised | UNSURE |
| S48 | Ry, Rt: A500 Grade C 1.3, 1.2; Grade B and A501 1.4, 1.3; A1085 1.25, 1.15; the other rows as BNBC 2020 (A36 1.5/1.2, A992 / A572 Gr 50 1.1/1.1, A529 1.2/1.2 and 1.1/1.2, A53 1.6/1.2, plates A36 1.3/1.2, A572 1.1/1.2) | Sec A3.2 | | OK? |
| S49 | IMF beams and columns moderately ductile; SMF highly ductile; OMF no seismic limits | Sec E1.5a, E2.5a, E3.5a | | OK? |
| S50 | SCBF braces and columns highly ductile, beams moderately; OCBF braces moderately ductile | Sec F2.5a, F1.5a | | OK? |
| S51 | the other seismic rules (connections, panel zones, bracing, splices, bases, EBF links, BRBF, SPSW, STMF, composite systems) | — | Revised in track C3b: K1-K9 below | — |

### Composite: AISC 360-22 Chapter I — `composite.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S52 | f'c 21-69 MPa normal weight, 21-41 MPa lightweight; Fy ≤ 525 MPa | Sec I1.3 | | OK? |
| S53 | Es 200 000 MPa | Sec I1.5 | Was 210 000 in BNBC 2020 | OK? |
| S54 | encased EIeff = Es Is + Es Isr + C1 Ec Ic, C1 = 0.25 + 3 ρ ≤ 0.7 | Sec I2.1b | ρ taken As / Ag without Asr (conservative) | OK? |
| S55 | filled C3 = 0.45 + 3 ρ ≤ 0.9 | Sec I2.2b | Same simplification | OK? |
| S56 | filled walls compact only: b/t ≤ 2.26 √(E/Fy) (1011 / √Fy), D/t ≤ 0.15 E/Fy (30 000 / Fy) | Sec I1.4, Table I1.1a | Noncompact and slender filled sections not designed (refused) | OK? |
| S57 | φb 0.90 (Ω 1.67) of encased and filled members in flexure | Sec I3.3 | Was 0.85 | UNSURE |
| S58 | Rp 0.75 for studs welded directly to the steel shape | Sec I8.2a | Was 1.0 in BNBC 2020 | OK? |

### Masonry: TMS 402-22 Chapter 9 — `masonry.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| M1 | φ 0.90 axial and flexure, 0.80 shear | Sec 9.1.4 | | OK? |
| M2 | εmu 0.0025 (clay; 0.0035 concrete masonry not used), 0.80 f'm over 0.80 c | Sec 9.3.2 | | OK? |
| M3 | Pn = 0.80 [0.80 f'm (An − As) + fy As] | Sec 9.3.4.1.1 | The slenderness factor not applied to shear walls | UNSURE |
| M4 | Vnm = 0.083 [4.0 − 1.75 Mu/(Vu dv)] Anv √f'm + 0.25 Pu, Mu/(Vu dv) 0 to 1.0; Vns = 0.5 ρn fy Anv; Vn ≤ 0.498 / 0.332 Anv √f'm at 0.25 / 1.0 | Sec 9.3.6.5 | γg = 1.0 | UNSURE (clause numbers) |
| M5 | f'm 10.3-27.6 MPa for shear walls | Sec 9.1.9.1 | Concrete masonry; clay up to 41.4 | UNSURE |
| M6 | slender walls, modulus of rupture, boundary members, reinforcement rules and the seismic and empirical rules: the default pack's, cited as BNBC 2020 | — | The allowable stress method (Chapter 8): MA1-MA13 below | — |

## Timber, masonry ASD, the steel remainder and the generator (track C3b)

No copy of the NDS 2018 (or its Supplement), TMS 402-22, AISC 360-22, AISC 341-22 or AISC 358
was available. The values come from the author's knowledge of these standards (the NDS values
are those of the 2018 Supplement as recalled; most are unchanged since the 2005 edition).
Stresses of the NDS tables are entered in psi as printed (`reference.toMPa` converts them).

### Timber: NDS 2018 — `timber.json` (method `referenceDesign`, ASD by default, LRFD selectable)

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| T1 | Douglas Fir-Larch dimension lumber (Fb, Ft, Fv, Fc⊥, Fc, E, Emin psi): SS 1500, 1000, 180, 625, 1700, 1.9e6, 690 000; No.1 & Btr 1200, 800, 180, 625, 1550, 1.8e6, 660 000; No.1 1000, 675, 180, 625, 1500, 1.7e6, 620 000; No.2 900, 575, 180, 625, 1350, 1.6e6, 580 000; No.3 525, 325, 180, 625, 775, 1.4e6, 510 000; Stud 700, 450, 180, 625, 850, 1.4e6, 510 000; G 0.50 | Supplement Table 4A | | OK? |
| T2 | Douglas Fir-Larch beams and stringers: SS 1600, 950, 170, 625, 1100, 1.6e6, 580 000; No.1 1350, 675, 170, 625, 925, 1.6e6, 580 000; No.2 875, 425, 170, 625, 600, 1.3e6, 470 000 | Supplement Table 4D | | UNSURE (Ft, Fc of No.1, No.2) |
| T3 | Douglas Fir-Larch posts and timbers: SS 1500, 1000, 170, 625, 1150, 1.6e6, 580 000; No.1 1200, 825, 170, 625, 1000, 1.6e6, 580 000; No.2 750, 475, 170, 625, 700, 1.3e6, 470 000 | Supplement Table 4D | | UNSURE |
| T4 | Hem-Fir dimension lumber: SS 1400, 925, 150, 405, 1500, 1.6e6, 580 000; No.1 & Btr 1100, 725, 150, 405, 1350, 1.5e6, 550 000; No.1 975, 625, 150, 405, 1350, 1.5e6, 550 000; No.2 850, 525, 150, 405, 1300, 1.3e6, 470 000; No.3 500, 300, 150, 405, 725, 1.2e6, 440 000; Stud 675, 400, 150, 405, 800, 1.2e6, 440 000; G 0.43 | Supplement Table 4A | | OK? |
| T5 | Spruce-Pine-Fir dimension lumber: SS 1250, 700, 135, 425, 1400, 1.5e6, 550 000; No.1/No.2 875, 450, 135, 425, 1150, 1.4e6, 510 000; No.3 500, 250, 135, 425, 650, 1.2e6, 440 000; Stud 675, 350, 135, 425, 725, 1.2e6, 440 000; G 0.42 | Supplement Table 4A | | OK? |
| T6 | Glulam 24F-1.8E: Fbx+ 2400, Fbx- 1450, Fc⊥x 650, Fvx 265, Ex 1.8e6, Ex min 950 000, Fby 1450, Ft 1100, Fc 1600; 20F-1.5E: 2000, 1100, 425, 210, 1.5e6, 790 000, Fby 800, Ft 725, Fc 925; G 0.42 | Supplement Table 5A | Fby, Ft, Fc and G of both classes from memory | UNSURE |
| T7 | Southern Pine and the other species and grades of the Supplement | Tables 4B, 4C, 4E, 4F, 5B | Not in the pack (a material naming them takes the default species, with a note) | — |
| T8 | CD: dead 0.9, live (ten years) 1.0, snow 1.15, roof live 1.25, wind and earthquake 1.6, impact 2.0; not on Fc⊥, E, Emin | Sec 2.3.2, Table 2.3.2 | Rain taken 1.25 and the flood load 1.6 (SAEngine practice) | OK? |
| T9 | CM wet service of dimension lumber: Fb 0.85 (1.0 when Fb CF ≤ 1150 psi), Ft 1.0, Fv 0.97, Fc⊥ 0.67, Fc 0.8 (1.0 when Fc CF ≤ 750 psi), E and Emin 0.9 | Supplement Table 4A adjustment factors | | OK? |
| T10 | CM of timbers (5 in. and thicker): Fc⊥ 0.67, Fc 0.91, the others 1.0 | Supplement Table 4D | | OK? |
| T11 | CM of glulam: Fb 0.8, Ft 0.8, Fv 0.875, Fc⊥ 0.53, Fc 0.73, E and Emin 0.833 | Supplement Table 5A | | OK? |
| T12 | Ct up to 38 °C 1.0; 38-52 °C Ft, E, Emin 0.9, the others 0.8 dry / 0.7 wet; 52-66 °C 0.9 and 0.7 dry / 0.5 wet | Table 2.3.3 | | OK? |
| T13 | Ci incising: Fb, Ft, Fc, Fv 0.80; E, Emin 0.95; Fc⊥ 1.00 | Table 4.3.8 | Dimension lumber | OK? |
| T14 | CF of dimension lumber (SS to No.3) by width 2-4, 5, 6, 8, 10, 12, 14+ in.: Fb 1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9 (2-3 in. thick) and 1.5, 1.4, 1.3, 1.3, 1.2, 1.1, 1.0 (4 in.); Ft 1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9; Fc 1.15, 1.1, 1.1, 1.05, 1.0, 1.0, 0.9; Stud 1.1/1.1/1.05 (2-4 in.), 1.0 (5-6 in.) | Supplement Table 4A | Actual depths 89, 114, 140, 184, 235, 286 mm | OK? |
| T15 | CF of timbers deeper than 12 in.: (12/d)^(1/9) | Sec 4.3.6.2 | | OK? |
| T16 | Cfu flat use by width 2-3, 4, 5, 6, 8, 10+ in.: 1.0, 1.1, 1.1, 1.15, 1.15, 1.2 (2-3 in. thick); 1.0, 1.0, 1.05, 1.05, 1.05, 1.1 (4 in.) | Supplement Table 4A | Applied to bending about the weak axis | OK? |
| T17 | Cr repetitive member 1.15 (Fb of dimension lumber) | Sec 4.3.9 | The member type's option | OK? |
| T18 | CV of glulam = (21/L)^(1/x) (12/d)^(1/x) (5.125/b)^(1/x) ≤ 1, x = 10 (SI 6400 mm, 305 mm, 130 mm); not with CL (the lesser) | Sec 5.3.6 | x = 20 of Southern Pine not used | OK? |
| T19 | CL: le = 2.06 lu (lu/d < 7), 1.63 lu + 3 d (7 to 14.3), 1.84 lu (above); RB = √(le d/b²) ≤ 50; FbE = 1.20 Emin'/RB²; CL = (1 + α)/1.9 - √(((1 + α)/1.9)² - α/0.95) | Sec 3.3.3, Table 3.3.3 | The 'any loading' row of Table 3.3.3 for every beam (SAEngine practice) | OK? |
| T20 | CP: FcE = 0.822 Emin'/(le/d)², c 0.8 sawn, 0.9 glulam; le/d ≤ 50 | Sec 3.7.1 | le = the member length (Ke = 1.0, SAEngine practice) | OK? |
| T21 | Combined bending and compression (fc/Fc')² + fb1/(Fb1'(1 - fc/FcE1)) + fb2/(Fb2'[1 - fc/FcE2 - (fb1/FbE)²]) ≤ 1; bending and tension ft/Ft' + fb/Fb* ≤ 1, (fb - ft)/Fb** ≤ 1 | Sec 3.9.1, 3.9.2 (Eq 3.9-3) | | OK? |
| T22 | Shear fv = 3V/(2bd), loads within d of the support left out | Sec 3.4.2, 3.4.3.1 | | OK? |
| T23 | Cb = (lb + 0.375)/lb for bearings under 6 in. (SI lb + 9.525 mm, 152 mm) | Sec 3.10.4 | The end distance of 3 in. not checked | OK? |
| T24 | Deflection: Kcr 1.5 on the dead load; limits L/240, L/360 (brittle finishes), cantilevers L/120 | Sec 3.5.2; IBC Table 1604.3 | The limits are SAEngine practice (IBC not in the pack); Kcr 2.0 of wet service not distinguished | PRACTICE |
| T25 | LRFD: KF Fb 2.54, Ft 2.70, Fv 2.88, Fc 2.40, Fc⊥ 1.67, Emin 1.76, connections 3.32; φ 0.85, 0.80, 0.75, 0.90, 0.90, 0.85, connections 0.65 | Appendix N, Tables N1, N2 | | OK? |
| T26 | λ: 0.6 dead alone; 0.8 occupancy live governing (1.25 impact); 0.8 roof live, snow, rain; 1.0 wind, earthquake | Appendix N, Table N3 | Storage live (0.7) not distinguished: the material's live load duration maps continuous → 0.8 (SAEngine practice) | UNSURE |
| T27 | Dowels: Fe∥ = 11 200 G, Fe⊥ = 6100 G^1.45/√D psi (D ≥ 1/4 in.), 16 600 G^1.84 (D < 1/4 in.); Hankinson at the angle | Table 12.3.3, Sec 12.3.4 | | OK? |
| T28 | Rd = 4 Kθ (I), 3.6 Kθ (II), 3.2 Kθ (III, IV), Kθ = 1 + 0.25 θ/90; KD 2.2 (D ≤ 0.17 in.), 10 D + 0.5 (0.17-0.25 in.) | Table 12.3.1B | | OK? |
| T29 | Yield modes single shear Im, Is, II, IIIm, IIIs, IV and double shear Im, Is, IIIs, IV with k1, k2, k3 | Table 12.3.1A, Eqs 12.3-1 to 12.3-10 | | OK? |
| T30 | Fyb 45 ksi bolts; nails 100 ksi (D ≤ 0.142 in.), 90 (≤ 0.177), 80 (≤ 0.236), 70 ksi (≤ 0.273) | Table I1 (Appendix I) | | UNSURE |
| T31 | Cg by Sec 11.3.6, γ = 180 000 D^1.5 lb/in; CΔ: end distance 7 D (tension softwood), 5 D (hardwood), 4 D (compression) for 1.0, least 3.5 D / 2.5 D / 2 D for 0.5; spacing 4 D for 1.0, least 3 D | Sec 11.3.6, Tables 12.5.1A, 12.5.1B | Side members of the member's species and depth (SAEngine practice) | UNSURE (γ, CΔ rules) |
| T32 | CM of fasteners in wet service 0.7 | Table 11.3.3 | | UNSURE |
| T33 | A material 'wet' or 'outside' is in wet service | Sec 4.1.4 | SAEngine practice | PRACTICE |

### Masonry: TMS 402-22 Chapter 8 — `masonry.json` `allowable` (the default masonry method)

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| MA1 | Fa = 0.25 f'm [1 - (h/140r)²] up to h/r 99, 0.25 f'm (70r/h)² above; r = t/√12 (h'/t 40.41, 28.58, 20.21) | Sec 8.2.4.1 | Solid section radius | OK? |
| MA2 | Reinforced columns Pa = (0.25 f'm An + 0.65 Ast Fs) [1 - (h/140r)²] (columnSteelArea 1/0.65) | Sec 8.3.4.2.1 | Compression steel stress the default pack's | UNSURE |
| MA3 | Fb = 1/3 f'm unreinforced, 0.45 f'm reinforced; no cap | Sec 8.2.4.2, 8.3.4.2.2 | | OK? |
| MA4 | Ft normal to the bed joints 53 / 33 psi (solid / hollow ungrouted, Type M or S), parallel 106 / 66 psi; Type N about 24.5 % less (40, 25, 80, 50 psi) | Table 8.2.4.2 | M1, M2 taken as Type M/S, M3, M4 as Type N (SAEngine practice); grouted hollow units take the ungrouted value | UNSURE (mapping) |
| MA5 | Unreinforced shear Fv = least of 1.5 √f'm, 120 psi, 37 psi + 0.45 Nv/An (60 psi + 0.45 Nv/An fully grouted, 15 psi stack bond) | Sec 8.2.6.2 | | OK? |
| MA6 | Reinforced shear Fv = Fvm + Fvs, Fvm = 1/2 [(4.0 - 1.75 M/(V dv)) √f'm] + 0.25 P/An, Fvs = 0.5 (Av Fs dv)/(An s); max 3 √f'm (M/(V dv) ≤ 0.25), 2 √f'm (≥ 1.0); fv = V/An | Sec 8.3.5.1 | γg = 1.0 | OK? |
| MA7 | Beams and out-of-plane shear: 0.0934 √f'm MPa (M/Vd = 1), with reinforcement 0.166 √f'm | Sec 8.3.5 | SAEngine practice | PRACTICE |
| MA8 | Fs 20 ksi (138 MPa) Grade 40 and 50, 32 ksi (220 MPa) Grade 60, joint reinforcement 30 ksi (207 MPa) | Sec 8.3.3.1 | | OK? |
| MA9 | No increase of the allowable stresses for wind or earthquake | Sec 8.1 with ASCE 7-22 Sec 2.4 | | OK? |
| MA10 | No reduction of the allowable stresses without special inspection | Chapter 3 | | OK? |
| MA11 | Em = 700 f'm clay, 900 f'm concrete masonry; Es 200 000 MPa; Ev = 0.4 Em | Sec 4.2.2 | Also used by the strength design and the analysis model of masonry walls | OK? |
| MA12 | h'/t at most 30 for walls, 25 for columns | Sec 5.3.1.4 (columns) | The wall limit is SAEngine practice (TMS 402-22 sets none) | PRACTICE |
| MA13 | P ≤ 1/4 Pe of unreinforced members | Sec 8.2.4.1 | Not checked | — |

### Steel: AISC 360-22 remainder — `steel.json`, `fatigue.json`, `designClauses.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S59 | Built-up members, welded or pretensioned connectors: (Lc/r)m = (Lc/r)o up to a/ri = 40, else √((Lc/r)o² + (Ki a/ri)²), Ki 0.50 (back-to-back angles), 0.75 (channels), 0.86 (other) | Sec E6.1(b), Eqs E6-2a, E6-2b | | OK? |
| S60 | Snug-tight bolts √((Lc/r)o² + (a/ri)²) | Sec E6.1(a), Eq E6-1 | | OK? |
| S61 | Stability bracing φ 0.75 (Ω 2.00); columns relative 0.005 Pr, 2 Pr/(φ Lbr); nodal 0.01 Pr, 8 Pr/(φ Lbr) | Appendix 6, Sec 6.2.1, 6.2.2 | 360-10 had 0.004 Pr | OK? |
| S62 | Beams lateral relative 0.005 Mr Cd/ho, 4 Mr Cd/(φ Lbr ho); nodal 0.02 Mr Cd/ho, 10 Mr Cd/(φ Lbr ho) | Appendix 6, Sec 6.3.1a, 6.3.1b | 360-10 had 0.008 | OK? |
| S63 | Torsional nodal Mbr = 0.02 Mr, βT = 3.6 L Mr²/(φ n E Iyeff Cb²), βsec = 3.3 E/ho (1.5 ho tw³/12 + ts bs³/12) | Appendix 6, Sec 6.3.2a | Iyeff taken Iy | OK? |
| S64 | Equation numbers of Appendix 6 (A-6-1 to A-6-8) in the notes | Appendix 6 | | UNSURE |
| S65 | Ponding: Cp + 0.9 Cs ≤ 0.25, Id ≥ 3940 S⁴ (SI 504, mm⁴), improved by Figures A-2.1, A-2.2 (the default pack's digitised curves); Eq A-2-1, A-2-2, A-2-4 | Appendix 2 | Equation numbers | UNSURE (numbers) |
| S66 | Tension field stiffeners: Ist ≥ Ist2 + (Ist1 - Ist2) ρw, Ist1 = h⁴ ρst^1.3/40 (Fyw/E)^1.5, Ist2 = b tw³ j (b the lesser of a and h), ρw = (Vr - Vc2)/(Vc1 - Vc2) ≥ 0; (b/t)st ≤ 0.56 √(E/Fyst); the area rule dropped | Sec G2.3 | | UNSURE (Ist1 form) |
| S67 | HSS connections: the default pack's equations (AISC 360-10 forms) cited as AISC 360-22 Sec K2 (plates, Tables K2.1, K2.2), K3 (truss, Tables K3.1, K3.2), K4 (moment, Tables K4.1, K4.2), K5 (welds) | Chapter K | Table numbers and whether 360-22 changed any equation | UNSURE |
| S68 | Chapter K φ: plastification 0.90 round / 1.00 rectangular, punching 0.95 (round gapped K joints included: 0.95, not the 0.90 of BNBC 2020), sidewall yielding 1.00, crippling 0.75, local buckling 0.90, uneven load 0.95, distortion 1.00, cap plates 1.00 / 0.75 | Chapter K tables | | OK? |
| S69 | Fatigue: no evaluation below 20 000 cycles or below FTH; 0.66 Fy under unfactored loads; FSR = (Cf × 329/nSR)^0.333 ≥ FTH (F: (Cf × 110 000/nSR)^0.167); Cf, FTH of categories A to F as the default pack's (Table 6.10.14a = Table A-3.1) | Appendix 3, Sec 3.1, 3.3, Table A-3.1 | SI equation numbers A-3-1M, A-3-2M | UNSURE (numbers) |
| S70 | Brace L/r 180 of stability braces | Appendix 6 | The default pack's limit kept as a flag; 360-22 may give none | UNSURE |
| S71 | Fire (Appendix 4): not covered (no home in SAEngine's steel engine) | Appendix 4 | Planned | — |

### Seismic: AISC 341-22 remainder — `steelSeismic.json`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| K1 | Expected moment at the hinge Mpr = Cpr Ry Fy Z, Cpr = (Fy + Fu)/(2 Fy) ≤ 1.2 (SMF, IMF) | Sec E3.6d, E2.6d; AISC 358 Sec 2.4.3 | Fixed 1.1 when Fu is unknown | OK? |
| K2 | Beam bracing Lb ≤ 0.095 ry E/(Ry Fy) (highly ductile, SMF), 0.19 ry E/(Ry Fy) (moderately, IMF); braces 0.06 Ry Fy Z/ho | Sec D1.2b, D1.2a, E3.4b, E2.4a | | OK? |
| K3 | Panel zone φv 1.00, t ≥ (dz + wz)/90, ΣM*pc/ΣM*pb > 1.0 (exempt below 0.3 Pc) | Sec E3.6e, E3.4a | | OK? |
| K4 | OMF connections 1.1 Ry Mp, PR at least 0.5 Mp; STMF the default pack's numbers | Sec E1.6b, E4 | | OK? |
| K5 | EBF links: Vp = 0.6 Fy Alw (Pr/Pc ≤ 0.15), rotation 0.08 to 0.02 rad, φv 0.90; the other link numbers the default pack's | Sec F3.4a, F3.5b | Unchanged numbers since 341-05 assumed | UNSURE |
| K6 | BRBF: adjusted brace strength β ω Ry Fysc Asc, connections 1.1 ×; the default pack's numbers | Sec F4.2a, F4.6c | | OK? |
| K7 | SPSW: Vn = 0.42 Fy tw Lcf sin 2α, φ 0.90; 0.8 < L/h ≤ 2.5; VBE Ic ≥ 0.0031 tw h⁴/L | Sec F5.5b, F5.4a; Eq F5-2 (α) | Equation number of α | UNSURE |
| K8 | Composite: f'c ≥ 21 MPa, ≤ 41 MPa lightweight; the other numbers the default pack's | Sec A3.5, D1.4b, Chapters G, H | | UNSURE |
| K9 | The section references of every rule (toughness A3.3, bolts D2.2, splices D2.5, bases D2.6, conformance E3.6c and Chapter K, SCBF F2.4-F2.6, OCBF F1.4-F1.6, links F3.4-F3.6, BRBF F4.2-F4.6, SPSW F5.2-F5.7, composite D1.4b, G3.5a, H6, clips I2.4) | — | Sub-clause letters from memory | UNSURE |
| K10 | Width-thickness limits of Table B4.1 named in the notes of compact (non-seismic) members | AISC 360-22 Table B4.1 | | OK? |

### Generator — `seismic.json` `generatorSystems`

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| G1 | Steel moment frames: steel not specifically detailed (R 3, row H), OMF (C.4), IMF (C.3), SMF (C.1); braced frames: steel not specifically detailed, OCBF (B.3), SCBF (B.2): the first the category and height permit | ASCE 7-22 Table 12.2-1 | SAEngine practice (the order) | PRACTICE |
| G2 | Preliminary sizes: beams Zx ≥ Mu/(0.9 Fy) (w l²/8, moment frames w l²/10 × 1.5), live deflection l/360, depth ≥ l/24; columns A ≥ Pu/(0.5 Fy), moment frames Zx ≥ 1.2 × the beams'; X braces for the storey shear (φc Pn of the full diagonal); every member within the system's width-thickness limits | — | Rules of thumb; Design mode sizes the members | PRACTICE |

### Alpha 9 C12 (steel half): cold-formed members, steel in fire, bracing rows — `coldFormed.json`, `steelFire.json`, `steel.json`

Rows numbered S1-S18 (their own series, so the parallel tracks do not collide).

| # | Value | Clause | Description | Status |
|---|---|---|---|---|
| S1 | E = 203 000 MPa (29 500 ksi), G = 78 000 MPa (11 300 ksi) | AISI S100-16 A3 | Steel moduli of the cold-formed members | OK? |
| S2 | ρ = 1 for λ <= 0.673, else (1 - 0.22/λ)/λ; λ = (1.052/√k)(w/t)√(f/E) | S100-16 1.1 (effective width of stiffened elements) | Winter's effective width of every flat element | OK? (the S100-16 section number: UNSURE) |
| S3 | k = 4.0 stiffened, 0.43 unstiffened (the lips); webs k = 4 + 2(1-ψ)³ + 2(1-ψ) at ψ = -1 | S100-16 1.1, 1.2 | Plate buckling coefficients; the lipped flange taken as fully stiffened (the distortional mode carries the lip's weakness: SAEngine practice) | OK? / PRACTICE |
| S4 | Pnd = Py for λd <= 0.561, else (1 - 0.25 (Pcrd/Py)^0.6)(Pcrd/Py)^0.6 Py; Mnd = My for λd <= 0.673, else (1 - 0.22 (Mcrd/My)^0.5)(Mcrd/My)^0.5 My | S100-16 E4, F4 | Distortional buckling by the direct strength curves | OK? |
| S5 | Fcrd = 2 √(K E Is) / As of the lip and half the flange on the spring of the web and flange plates | (EN 1993-1-3 5.5.3.2 model) | The distortional critical stress: SAEngine practice (S100 gives its own formulas) | PRACTICE |
| S6 | φt 0.90, φc 0.85, φb 0.90, φv 0.95 | S100-16 D2, E1, F1, G1 | LRFD resistance factors (cold-formed members stay LRFD when the project picks ASD) | OK? |
| S7 | Fn = 0.658^(λc²) Fy for λc <= 1.5, else 0.877 Fy / λc²; Fe the least of flexural (x, y, the least principal axis of a Z), torsional and flexural-torsional buckling | S100-16 E2 | Compression on the effective area at Fn | OK? |
| S8 | Fcre = Cb r0 A √(σey σt) / Sf (channels), Cb π² E d Iyc / (2 Sf (Ky Ly)²) (Z); Fn = Fy (Fcre >= 2.78 Fy), 10/9 Fy (1 - 10 Fy / (36 Fcre)), Fcre (<= 0.56 Fy); Cb = 1 | S100-16 F2.1 | Lateral-torsional buckling; Mn = Se Fn with Se at Fy (on the safe side), Cb = 1: PRACTICE | OK? |
| S9 | Vn = 0.6 Fy Aw (h/t <= √(E kv/Fy)), 0.6 t² √(kv Fy E) (<= 1.51 √(E kv/Fy)), 0.904 E kv t³ / h; kv = 5.34 | S100-16 G2.1 | Web shear (unreinforced web) | OK? |
| S10 | P/Pa + Mx/Max + My/May <= 1 | S100-16 H1.2 | Combined forces | OK? |
| S11 | w/t: web 200, flange (simple lip) 60, lip 60; t <= 25.4 mm | S100-16 B4.1, A1.1 | Largest ratios and thickness covered | UNSURE |
| S12 | ky / kE at 68, 200, 400, 600, 750, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200 °F: 1.00/1.00, 1.00/1.00, 1.00/0.90, 1.00/0.78, 1.00/0.70, 0.94/0.67, 0.66/0.49, 0.35/0.22, 0.16/0.11, 0.07/0.07, 0.04/0.05, 0.02/0.02, 0/0 (entered in °C) | AISC 360-22 App 4.2.3b, Table A-4.2.1 | Retention factors of Fy and E | UNSURE (each value) |
| S13 | Fn(T) = 0.42^√(Fy(T)/Fe(T)) Fy(T) | App 4.2.4d(b) (Eq A-4-9 in 360-16) | Compression at elevated temperature | OK? |
| S14 | φ = 0.90 in fire (gammaFire 1.111) | App 4.1.4 | Resistance factor of the simple method | UNSURE |
| S15 | μ0 = 0.6 × the ambient utilisation | (ASCE 7-22 2.5: 1.2 D + 0.5 L over the strength combinations) | The load ratio in fire | PRACTICE |
| S16 | Lumped heat capacity, the ISO 834 curve θg = 20 + 345 log10(8t + 1) for ASTM E119, αc 25 W/m²K, εm 0.7, ca 600 J/kgK, ρa 7850 kg/m³, no shadow factor | App 4.2.2 | Steel temperature at the rating | PRACTICE |
| S17 | θcr: the temperature at which ky = μ0 | App 4.2.4c | Members without compression | PRACTICE |
| S18 | `steel.bracing.rows` true: the Appendix 6 brace strength and stiffness as flagged rows of the member | App 6.2, 6.3 | Reported, not a new value | PRACTICE |
## Frame and seismic detailing clause references (track C11) — `designClauses.json`

The groups `ductileMembersRows`, `ductileJointsRows`, `seismicDetailingRows` and
`seismicRulesRows` name the ACI 318-19 Chapter 18 (and ASCE 7-22) clause of each row of the RC
frame detailing, capacity design and seismic system rules. They are clause numbers only: the
values those rows check are the pack's tables (`detailing`, `materials`, ...). A key this pack
leaves out names its row without a clause (it never shows the BNBC number it would inherit).
All clause numbers are from memory of ACI 318-19; sub-clause letters especially need checking.

| # | Rows | Clause | Description | Status |
|---|---|---|---|---|
| D1 | SMF beams: scope, ln ≥ 4d, b ≥ 0.3h and 250 mm, width within the column | 18.6, 18.6.2.1(a), (b), (c); Figure R18.6.2 | | OK? |
| D2 | SMF beams: As,min, ρ ≤ 0.025, two bars each face; Mn+ ≥ Mn-/2, Mn ≥ max Mn/4 | 18.6.3.1 (9.6.1.2), 18.6.3.2 | | OK? |
| D3 | SMF beams: lap splices, hoop zones 2h, other yielding sections, two-piece hoops, first hoop and spacing, stirrups elsewhere | 18.6.3.3, 18.6.4.1(a), (b), 18.6.4.3, 18.6.4.4, 18.6.4.5 | 318-19 spacing limits differ from the engine's (d/4, 8 db, 24 dh, 300 mm): only the clause is the pack's | UNSURE |
| D4 | Beams with Pu > Ag f'c/10 (BNBC: detail as a column) | 18.6.4.6 | 318-19 has no axial limit in the beam scope; 18.6.4.6 asks column hoops | UNSURE |
| D5 | Lateral support of the perimeter bars | 25.7.2.3 (beams), 18.7.5.2 (columns) | | OK? |
| D6 | SMF columns: scope, least dimension 300 mm, ratio 0.4, ρg 0.01-0.06, splices | 18.7.1, 18.7.2.1(a), (b), 18.7.4.1, 18.7.4.3 | Splice clause number | UNSURE |
| D7 | SMF columns: lo, so, hx, Ash and ρs, outside lo, first hoop | 18.7.5.1, 18.7.5.3, 18.7.5.2(e), Table 18.7.5.4 (a), (b), (d), (e), 18.7.5.5, Figure R18.7.5.1 | | OK? |
| D8 | Columns of a joint failing the strong-column rule | 18.7.3.3 | 318-19 sends them to 18.14 rather than full-height hoops | UNSURE |
| D9 | IMF beams and columns: Mn shares, stirrups over 2h, d/2, so over lo, first tie, outside lo | 18.4.2, 18.4.2.2, 18.4.2.4, 18.4.2.5, 18.4.3, 18.4.3.3, 18.4.3.4, 18.4.3.5 | | OK? |
| D10 | Members not in the seismic-force-resisting system (SDC D-F) | 18.14.3.1, 18.14.3.2, 18.14.3.3 | Sub-clause letters left out | UNSURE |
| D11 | Not given (no 318-19 counterpart): the ordinary frame column tie rules and the members outside the system in an ordinary frame (BNBC 8.3.9, 8.3.9.1, 8.3.9.2), the IMF axial rule (BNBC 8.3.10.2), the lists of clauses the members outside the system follow | — | Named without a clause | — |
| D12 | Strong column / weak beam, its scope, full height | 18.7.3.1, 18.7.3.2 (Eq 18.7.3.2), 18.7.3.3 | | OK? |
| D13 | Joints: forces at 1.25 fy, through bars 20 db, hooked anchorage, γ by confinement, bj, φ | 18.8.2.1, 18.8.2.3, 18.8.5.1 (Eq 18.8.5.1), 18.8.4.1 (Table 18.8.4.1), 18.8.4.3, 21.2.4.4 | | OK? |
| D14 | Capacity shear: beams, columns, Vc = 0, fyt limit, IMF | 18.6.5.1, 18.7.6.1.1, 18.6.5.2, 18.7.6.2.1, 20.2.2.4, 18.4.2.3, 18.4.3.1 | | OK? |
| D15 | Foundations: column bars into the footing, grade beam ties | 25.4.3 (hooks), 18.13.2.3, 18.13.3.2, 18.13.3.3 | Grade beam clause numbers | UNSURE |
| D16 | System and materials: detailing by SDC, the systems table, f'c, λ, grades, actual fy, fu/fy, elongation, mechanical splices, φ, walls | 18.2.1, ASCE 7-22 Table 12.2-1, 18.2.5 (Table 19.2.1.1), 19.2.4, 18.2.6 (20.2.2.5), 20.2.2.5(b)(i)-(iii), 18.2.7 (18.2.7.1), 21.2, 18.10 | The 20.2.2.5(b) letters | UNSURE |

## Not covered in this version (fall back or absent)

- Timber: the NDS species and grades not listed (Southern Pine, the machine stress rated
  grades, the other glulam combinations), split ring and shear plate connectors (NDS Chapter
  13), wood screws and lag screws, the split ring and disc-dowel joints of SAEngine's timber
  members (flagged not covered under this method); round timber poles, I-joists and SCL.
- Masonry: the masonry rules not listed above (empirical design, seismic detailing, slender
  walls of the strength method): BNBC 2020's, named so.
- AISC 360-22 Appendix 4: the simple method only (rows S12-S17); the advanced method of
  analysis and the qualification testing are not covered.
- The geotechnical foundation tables and the remaining material tables: inherited from BNBC 2020
  (the report names them as the BNBC tables).
- The seismic detailing rows of special, intermediate and ordinary frames (ductile members and
  joints) still print the extended pack's clause numbers in their row names: their values are
  ACI 318-19's (the same numbers), the row clauses are not yet read from the pack.
- ACI 318 Chapter 17 anchorage and ACI 350 tanks: no ACI values in this version (the anchor and
  tank checks use the extended pack's).
- Dead load unit weights (`deadLoads`): BNBC's.
- Nonstructural components (Ch 13), isolation (Ch 17), dampers (Ch 18), nonlinear response
  history (Ch 16), ice (Ch 10): BNBC's tables or not covered.
- The ground loads worksheet of the report covers zone-factor packs only.
