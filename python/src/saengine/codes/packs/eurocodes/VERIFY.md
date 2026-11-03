# Eurocodes pack: values to verify

No copy of the Eurocodes was available when this pack was written (alpha 9 track C4). The values
below were entered from knowledge of the codes' recommended values. Check each one against the
printed code (the EN edition of the CEN text, not a National Annex) and tick it. "Unsure" marks
values the author was not certain of; those must be checked before the pack is used for design.
"SAEngine practice" marks choices that are not values of the code.

## EN 1990 (combinations.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 1 | γG,sup = 1.35, γG,inf = 1.00 | Table A1.2(B) | Permanent actions, set B | sure |
| 2 | γQ = 1.50 (0 favourable) | Table A1.2(B) | Variable actions | sure |
| 3 | ξ = 0.85 | Table A1.2(B), Eq 6.10b | Reduction of unfavourable G in 6.10b | sure |
| 4 | ψ0/ψ1/ψ2 = 0.7/0.5/0.3 | Table A1.1 | Imposed loads, categories A and B | sure |
| 5 | ψ0/ψ1/ψ2 = 0.7/0.7/0.6 | Table A1.1 | Categories C, D (not used by the default rows) | sure |
| 6 | ψ0/ψ1/ψ2 = 1.0/0.9/0.8 | Table A1.1 | Category E (used for ψE of heavy loads) | sure |
| 7 | ψ0/ψ1/ψ2 = 0.5/0.2/0 | Table A1.1 | Snow, sites at most 1000 m a.s.l. (not Finland, Iceland, Norway, Sweden) | sure |
| 8 | ψ0/ψ1/ψ2 = 0.6/0.2/0 | Table A1.1 | Wind | sure |
| 9 | ψ0/ψ1/ψ2 = 0.6/0.5/0 | Table A1.1 | Temperature (non-fire) | sure |
| 10 | ψ0/ψ1/ψ2 = 0/0/0 | Table A1.1 | Roofs, category H (SAEngine takes the snow ψ for Lr: practice, conservative) | sure |
| 11 | Rows of set 6.10 | Eq 6.10 | 1.35G; 1.35G + 1.5Q + 0.75S (+0.9W); 1.35G + 1.5S + 1.05Q (+0.9W); 1.35G + 1.5W + 1.05Q + 0.75S; 1.0G + 1.5W | sure (row choice SAEngine practice) |
| 12 | Rows of set 6.10ab | Eqs 6.10a, 6.10b | 6.10a with every variable action at ψ0; 6.10b with 0.85·1.35 = 1.1475 G | sure |
| 13 | Seismic G + AEd + 0.3Q | Eq 6.12b | G at 1.0, ψ2 Q | sure |
| 14 | Characteristic, frequent, quasi-permanent rows | Eqs 6.14b, 6.15b, 6.16b | G + Q + 0.5S + 0.6W, G + W + 0.7Q + 0.5S; G + 0.5Q, G + 0.2W + 0.3Q; G + 0.3Q | sure |
| 15 | Temperature rows ±0.9T | Eq 6.10 with ψ0 = 0.6 | 1.35G ± 0.9T + 1.5Q + 0.75S | sure |
| 16 | H (earth pressure) and F (liquids) at γG | Table A1.2(B), EN 1997-1 | 1.35 / 1.0 | SAEngine practice |
| 17 | P-Δ preload G + 0.3Q | EN 1998-1 4.4.2.2(2) | Gravity of the seismic situation | sure |

## EN 1991-1-1 (areaLoads.json, liveReduction.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 18 | A floors qk 2.0, Qk 2.0 | Table 6.2 | Recommended (underlined) values | unsure (range 1.5-2.0 / 2.0-3.0) |
| 19 | A stairs qk 2.0, Qk 2.0 | Table 6.2 | Recommended | unsure (range 2.0-4.0) |
| 20 | A balconies qk 2.5, Qk 2.0 | Table 6.2 | Recommended | unsure (range 2.5-4.0) |
| 21 | B qk 3.0, Qk 4.5 | Table 6.2 | Offices | unsure (range 2.0-3.0 / 1.5-4.5) |
| 22 | C1 qk 3.0, Qk 4.0 | Table 6.2 | Areas with tables | unsure |
| 23 | C2 qk 4.0, Qk 4.0 | Table 6.2 | Fixed seats | unsure |
| 24 | C3 qk 5.0, Qk 4.0 | Table 6.2 | No obstacles, access areas | unsure |
| 25 | C4 qk 5.0, Qk 7.0 | Table 6.2 | Physical activities | unsure |
| 26 | C5 qk 5.0, Qk 4.5 | Table 6.2 | Crowds | unsure |
| 27 | D1 qk 4.0, Qk 4.0 | Table 6.2 | Retail | unsure |
| 28 | D2 qk 5.0, Qk 7.0 | Table 6.2 | Department stores | unsure |
| 29 | E1 qk 7.5, Qk 7.0 | Table 6.4 | Storage | sure |
| 30 | F qk 2.5, Qk 20 on 100 mm squares | Tables 6.7-6.8, 6.3.3.2(4) | Light vehicles | unsure (qk range 1.5-2.5) |
| 31 | G qk 5.0, Qk 90 on 200 mm squares | Tables 6.7-6.8 | Medium vehicles | unsure (Qk range 40-90) |
| 32 | H qk 0.4, Qk 1.0 | Table 6.10 | Roofs not accessible | unsure (qk range 0-1.0) |
| 33 | I (roof garden 3.0/4.0, terrace 2.5/2.0) | Table 6.9 | Accessible roofs by category | SAEngine practice |
| 34 | Qk on a 50 mm square | 6.3.1.2(4) | A-D | sure |
| 35 | Partitions 0.5 / 0.8 / 1.2 kN/m² for ≤ 1 / 2 / 3 kN/m | 6.3.1.2(8) | Modelled as 0.4 per kN/m, at least 0.5 (under the step between 1 and 2 kN/m) | sure (model approximate) |
| 36 | Barrier line loads 0.5 (A, B, C1), 1.0 (C2-C4, D), 3.0 (C5), 2.0 (E) kN/m | Table 6.12 | Recommended | unsure |
| 37 | Vehicle barrier 150 kN at 375 mm over 1.5 m; ramps 0.5 F at 610 mm; 2 F beyond 20 m ramps | Annex B | m 1500 kg, v 4.5 m/s, δc 100 mm | unsure |
| 38 | αA = 5/7 ψ0 + A0/A, A0 = 10 m² | Eq 6.1 | Area reduction | sure |
| 39 | αA ≥ 0.6 for C and D | 6.3.1.2(10) Note 1 | Recommended | sure |
| 40 | αn = (2 + (n - 2) ψ0)/n | Eq 6.2 | Storeys reduction, A-D | sure |
| 41 | The lesser of αA and αn | 6.3.1.2(11) | Their joint use is an NDP | SAEngine practice |
| 42 | Not reduced above 5.0 kN/m², E, F, G, C5 | 6.3.1.2(10)-(11) | | SAEngine practice |

## EN 1991-1-3 (snow.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 43 | s = μ1 Ce Ct sk | Eq 5.1 | Persistent and transient situation | sure |
| 44 | Ce 0.8 / 1.0 / 1.2 | Table 5.1 | Windswept, normal, sheltered | sure |
| 45 | Ct = 1.0 | 5.2(8) | Thermal coefficient | sure |
| 46 | μ1 0.8 (0-30°), 0.8(60-α)/30, 0 (≥ 60°) | Table 5.2 | Monopitch and duopitch, undrifted | sure |
| 47 | Cesl = 2.0 | 4.3, Eq 4.1 | Exceptional snow, reported only | sure |
| 48 | Snow and roof imposed load not together (envelope in Lr) | EN 1991-1-1 3.3.2(1) | | sure (modelling: SAEngine practice) |

## EN 1991-1-4 (wind.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 49 | cdir = cseason = 1.0 | 4.2(2) Notes 2-3 | Recommended | sure |
| 50 | z0 / zmin: 0.003/1, 0.01/1, 0.05/2, 0.3/5, 1.0/10 m | Table 4.1 | Terrain categories 0-IV | sure |
| 51 | kr = 0.19 (z0/z0,II)^0.07, z0,II = 0.05 m | Eq 4.5 | Terrain factor | sure |
| 52 | zmax = 200 m | 4.3.2 | | sure |
| 53 | kI = 1.0, co = 1.0 | 4.4(1), 4.3.3 | Turbulence factor, flat ground | sure |
| 54 | qp = [1 + 7 Iv] ½ ρ vm², ρ = 1.25 kg/m³ | Eq 4.8, 4.5(1) Note 2 | | sure |
| 55 | ze: h ≤ b, b < h ≤ 2b, h > 2b (strips at their height) | 7.2.2(1), Figure 7.4 | Strips taken at the level height | sure (strip height: SAEngine practice) |
| 56 | cpe,10 D +0.8/+0.8/+0.7, E -0.7/-0.5/-0.3 at h/d 5/1/≤0.25 | Table 7.1 | Linear between | sure |
| 57 | Lack of correlation 0.85 (h/d ≤ 1) to 1.0 (h/d ≥ 5) | 7.2.2(3) Note | | sure |
| 58 | cscd = 1.0 below 15 m; frame buildings with walls below 100 m and below 4 d | 6.2(1) a, c | Simplified cases | sure |
| 59 | cpi +0.2 / -0.3 | 7.2.9(6) Note 2 | Reported only | sure |

## EN 1991-1-7 (flood.json, explosion only)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 60 | pd = 3 + pstat; 3 + pstat/2 + 0.04/(Av/V)², the larger | Annex D, Eqs D.1-D.2 | Points for 0.05 ≤ Av/V ≤ 0.15 | sure (equations), unsure (Annex D details) |
| 61 | pstat = 3.0 kN/m² | Annex D | Failure pressure of the vent panels | SAEngine practice (the project's value) |

## EN 1998-1 (seismic.json, occupancyCategories.json, zoneCoefficients.json, locations.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 62 | Type 1: S/TB/TC/TD A 1.0/0.15/0.4/2.0, B 1.2/0.15/0.5/2.0, C 1.15/0.2/0.6/2.0, D 1.35/0.2/0.8/2.0, E 1.4/0.15/0.5/2.0 | Table 3.2 | | sure |
| 63 | Type 2: A 1.0/0.05/0.25/1.2, B 1.35/0.05/0.25/1.2, C 1.5/0.1/0.25/1.2, D 1.8/0.1/0.3/1.2, E 1.6/0.05/0.25/1.2 | Table 3.3 | | sure |
| 64 | Ground types A-E as ids SA-SE, by vs,30 800/360/180, NSPT 50/15, cu 250/70 | Table 3.1 | Same limits as the soil report's classes | sure |
| 65 | S1, S2 need special studies | 3.1.2(4) | Assumed E meanwhile | sure (assumption: SAEngine practice) |
| 66 | Design spectrum Eqs 3.13-3.16, β = 0.2 | 3.2.2.5 | | sure |
| 67 | ag = γI agR | 3.2.1(3) | | sure |
| 68 | η = √(10/(5 + ξ)) ≥ 0.55 | Eq 3.6 | Elastic spectrum only | sure |
| 69 | γI 0.8, 1.0, 1.2, 1.4 | 4.2.5(5), Table 4.3 | Importance classes I-IV | sure |
| 70 | ψE = φ ψ2, φ = 1.0 | 3.2.4(2), 4.2.4 Table 4.2 | φ 0.5-1.0 in the code | SAEngine practice (the largest φ) |
| 71 | Heavy loads > 5.0 kN/m²: ψE 0.8 | Table A1.1 (E), Table 4.2 | | SAEngine practice |
| 72 | T1 = Ct H^0.75, Ct 0.085 / 0.075 / 0.050 | Eq 4.6 | Steel MRF / RC MRF and steel EBF / others | sure |
| 73 | λ = 0.85 if T1 ≤ 2 TC and more than 2 storeys | Eq 4.5 | | sure |
| 74 | Fi = Fb zi mi / Σ zj mj | Eq 4.11 | Linear mode shape | sure |
| 75 | Lateral force method if T1 ≤ min(4 TC, 2.0 s) and regular in elevation | 4.3.3.2.1(2) | | sure |
| 76 | e = ±0.05 L | Eq 4.3 | Accidental eccentricity | sure |
| 77 | 90 % of the mass | 4.3.3.3.1(3) | Modal analysis | sure |
| 78 | 0.30 orthogonal share | Eqs 4.18-4.19 | | sure |
| 79 | No scaling of the modal base shear | Sec 4.3.3.3 | | sure |
| 80 | RC frame q0 = 3.0 (DCM), 4.5 (DCH) × αu/α1 | Table 5.1 | | sure |
| 81 | RC uncoupled walls q0 = 3.0 (DCM), 4.0 αu/α1 (DCH) | Table 5.1 | | sure |
| 82 | αu/α1 = 1.3 (multi-bay multi-storey frames), 1.2 (wall-equivalent dual), 1.1 (uncoupled walls) | 5.2.2.2(5) | | sure |
| 83 | kw = 1 | 5.2.2.2(11) | Walls with hw/lw ≥ 2 assumed | SAEngine practice |
| 84 | DCL q = 1.5 | 5.3.3, 6.1.2 | Low seismicity only | sure |
| 85 | Steel MRF q = 4 (DCM), 5 αu/α1 (DCH), αu/α1 = 1.3 | Table 6.2, 6.3.2(3) | | sure |
| 86 | Steel concentric diagonal bracing q = 4 | Table 6.2 | DCM and DCH | sure |
| 87 | Steel eccentric bracing q = 5 αu/α1, αu/α1 = 1.2 (DCH) | Table 6.2 | | sure |
| 88 | Steel MRF + concentric bracing q = 4 αu/α1, αu/α1 = 1.2 (DCH) | Table 6.2 | | unsure |
| 89 | Masonry q 1.5 / 2.0 / 2.5 (unreinforced / confined / reinforced) | Table 9.1 | Lower recommended values | unsure (ranges) |
| 90 | Ω0 = αu/α1, Cd = q | 4.3.4(1) | EN 1998-1 has no Ω0 | SAEngine practice |
| 91 | Drift dr ν ≤ 0.005 h, ν 0.5 / 0.4 → 0.010 / 0.0125 | 4.4.3.2(1)a, (2) | Brittle non-structural elements | sure |
| 92 | Drift dr ν ≤ 0.0075 h → 0.015 / 0.01875 | 4.4.3.2(1)b | Ductile non-structural elements (finishes designed for the drift) | sure |
| 93 | ds = qd de, qd = q | 4.3.4(1), Eq 4.23 | Design displacements | sure |
| 94 | θ = Ptot dr / (Vtot h); ≤ 0.1 ignore, ≤ 0.2 by 1/(1 - θ), ≤ 0.3 | 4.4.2.2(2)-(4) | | sure |
| 95 | Separation: SRSS, 0.7 at equal floor levels | 4.4.2.7(2)-(3) | | sure |
| 96 | Vertical component not taken (verticalFactor 0) | 4.3.3.5.2 | Only for avg > 0.25 g and listed members | sure (not covered) |
| 97 | Category of the seismic action B/C/D by bands of agR (zones 0.02/0.06/0.10/0.30 g) | 3.2.1(4)-(5) | Very low ≤ 0.05 g, low ≤ 0.10 g of ag S | SAEngine practice |
| 98 | Torsion ratios 1.2 / 1.4 reported, Ax ≤ 1.0 | 4.2.3.2, 4.3.3.2.4 | Not the code's criteria | SAEngine practice |
