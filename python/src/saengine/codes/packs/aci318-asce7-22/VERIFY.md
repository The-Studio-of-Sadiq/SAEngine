# Verification list: `aci318-asce7-22` (ASCE 7-22 loads)

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

## Not covered in this version (fall back or absent)

- Steel, masonry, timber, the geotechnical foundation tables and every other material table:
  inherited from BNBC 2020 (the report names them as the BNBC tables); AISC 360-22 is track C3.
- The seismic detailing rows of special, intermediate and ordinary frames (ductile members and
  joints) still print the extended pack's clause numbers in their row names: their values are
  ACI 318-19's (the same numbers), the row clauses are not yet read from the pack.
- ACI 318 Chapter 17 anchorage and ACI 350 tanks: no ACI values in this version (the anchor and
  tank checks use the extended pack's).
- Dead load unit weights (`deadLoads`): BNBC's.
- Nonstructural components (Ch 13), isolation (Ch 17), dampers (Ch 18), nonlinear response
  history (Ch 16), ice (Ch 10): BNBC's tables or not covered.
- The ground loads worksheet of the report covers zone-factor packs only.
