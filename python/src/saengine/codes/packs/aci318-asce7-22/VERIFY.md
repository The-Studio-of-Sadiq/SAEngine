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

## Not covered in this version (fall back or absent)

- Concrete, steel, masonry, timber, foundations and every other material table: inherited from
  BNBC 2020 (the report names them as the BNBC tables); the ACI 318-19 / AISC 360-22 tracks C2
  and C3 replace them.
- Dead load unit weights (`deadLoads`): BNBC's.
- Nonstructural components (Ch 13), isolation (Ch 17), dampers (Ch 18), nonlinear response
  history (Ch 16), ice (Ch 10): BNBC's tables or not covered.
- The ground loads worksheet of the report covers zone-factor packs only.
