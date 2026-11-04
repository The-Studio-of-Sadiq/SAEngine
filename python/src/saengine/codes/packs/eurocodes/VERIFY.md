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

## EN 1992-1-1 (concreteMethods.json, alpha 9 track C5)

Recommended values of the CEN text (2004 with AC:2010). The strength-class relations are
stored as their coefficients and evaluated by `design/design_strength.py`; the tables of the
code are not copied.

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 99 | γc = 1.5, γs = 1.15 | 2.4.2.4, Table 2.1N | Persistent and transient situations (also used for the seismic situation, EN 1998-1 5.2.4(2) Note) | sure |
| 100 | γc = 1.2, γs = 1.0 | Table 2.1N | Accidental (stored, not used yet) | sure |
| 101 | αcc = 1.0, αct = 1.0 | 3.1.6(1), (2) | Recommended (many annexes take αcc 0.85) | sure |
| 102 | Strength classes C12/15 ... C90/105 | Table 3.1 | fck / fck,cube | sure |
| 103 | fcm = fck + 8 | Table 3.1 | MPa | sure |
| 104 | fctm = 0.30 fck^(2/3) (≤ C50/60), 2.12 ln(1 + fcm/10) above | Table 3.1 | | sure |
| 105 | fctk,0.05 = 0.7 fctm, fctk,0.95 = 1.3 fctm | Table 3.1 | | sure |
| 106 | Ecm = 22 (fcm/10)^0.3 GPa | Table 3.1 | | sure |
| 107 | εc2 = 2.0 ‰; 2.0 + 0.085 (fck - 50)^0.53 above C50 | Table 3.1 | | sure |
| 108 | εcu2 = εcu3 = 3.5 ‰; 2.6 + 35 ((90 - fck)/100)^4 above | Table 3.1 | | sure |
| 109 | n = 2.0; 1.4 + 23.4 ((90 - fck)/100)^4 above | Table 3.1 | | sure |
| 110 | εc3 = 1.75 ‰; 1.75 + 0.55 (fck - 50)/40 above | Table 3.1 | | sure |
| 111 | η = 1.0; 1.0 - (fck - 50)/200 above. λ = 0.8; 0.8 - (fck - 50)/400 above | 3.1.7(3), Eqs 3.19-3.22 | Rectangular stress block (the method default) | sure |
| 112 | Es = 200 GPa, horizontal top branch at fyd | 3.2.7(2)b, (4) | | sure |
| 113 | e0 = h/30 ≥ 20 mm | 6.1(4) | SAEngine applies it about both axes at once (conservative) | sure (application SAEngine practice) |
| 114 | Pure compression strain εc2 → σs = min(fyd, Es εc2) | 6.1(5) | NRd = η fcd (Ac - As) + σs As | sure |
| 115 | CRd,c = 0.18/γc, k = 1 + √(200/d) ≤ 2, ρl ≤ 0.02, k1 = 0.15 | 6.2.2(1), Eq 6.2a | VRd,c | sure |
| 116 | vmin = 0.035 k^1.5 √fck | Eq 6.3N | | sure |
| 117 | σcp ≤ 0.2 fcd | 6.2.2(1) | | sure |
| 118 | 1 ≤ cot θ ≤ 2.5 | Eq 6.7N | | sure |
| 119 | ν1 = ν = 0.6 (1 - fck/250) | Eq 6.6N, 6.2.3(3) Note | The reduced ν1 for fywd < 0.8 fywk is not used | sure |
| 120 | αcw = 1 (non-prestressed), z = 0.9 d | 6.2.3(3), (1) | | sure |
| 121 | VRd = max(VRd,c, min(VRd,s, VRd,max)) | 6.2.1(3)-(5) | No calculated links where VEd ≤ VRd,c | SAEngine practice (reading) |
| 122 | ρw,min = 0.08 √fck / fyk | 9.2.2(5), Eq 9.5N | | sure |
| 123 | sl,max = 0.75 d (1 + cot α); st,max = 0.75 d ≤ 600 mm; β3 = 0.5 | 9.2.2(6), (8), (4) | Eqs 9.6N, 9.8N | sure |
| 124 | tef = A/u ≥ 2 × the distance to the bar axis; TRd,max = 2 ν αcw fcd Ak tef sin θ cos θ | 6.3.2(1), (4), Eq 6.30 | Torsion (method only, not wired into the beam checks yet) | sure |
| 125 | Torsion links ≤ u/8, ≤ the least dimension; longitudinal bars ≤ 350 mm apart | 9.2.3(3), (4) | | sure |
| 126 | u1 at 2 d | 6.4.2(1) | Punching (method only) | sure |
| 127 | β = 1.15 / 1.4 / 1.5 interior / edge / corner | 6.4.3(6), Fig 6.21N | Simplified values | sure |
| 128 | vRd,c: CRd,c = 0.18/γc, k1 = 0.1 | 6.4.4(1), Eq 6.47 | | sure |
| 129 | vRd,max = 0.4 ν fcd | 6.4.5(3) Note | AC:2010 value (0.5 ν fcd before) | unsure (edition) |
| 130 | vRd,cs = 0.75 vRd,c + 1.5 (d/sr) Asw fywd,ef sin α /(u1 d), fywd,ef = 250 + 0.25 d ≤ fywd | 6.4.5(1), Eq 6.52 | | sure |
| 131 | Outermost perimeter within 1.5 d of uout | 6.4.5(4) | | sure |
| 132 | k1 = 0.6 (XD, XF, XS), k2 = 0.45, k3 = 0.8, k4 = 1.0 | 7.2(2), (3), (5) | Stress limits (method only) | sure |
| 133 | wmax 0.4 mm X0, XC1; 0.3 mm XC2-XC4, XD, XS | 7.3.1(5), Table 7.1N | RC members, quasi-permanent | sure |
| 134 | kc 0.4 bending, 1.0 tension; k 1.0 (h ≤ 300) to 0.65 (h ≥ 800) | 7.3.2(2), Eq 7.1 | | sure |
| 135 | k1 0.8, k2 0.5/1.0, k3 3.4, k4 0.425, kt 0.6/0.4 | 7.3.4(1)-(3), Eqs 7.9, 7.11 | | sure |
| 136 | εsm - εcm ≥ 0.6 σs/Es; hc,ef = min(2.5 (h - d), (h - x)/3, h/2) | Eq 7.9, 7.3.2(3) | | sure |
| 137 | Spacing > 5 (c + φ/2): sr,max = 1.3 (h - x) | 7.3.4(3), Eq 7.14 | | sure |
| 138 | Eqs 7.16a/b: 11, 1.5, 3.2, 1/12; ρ0 = √fck 10⁻³ | 7.4.2(2) | Span/depth (method only) | sure |
| 139 | K = 1.0 / 1.3 / 1.5 / 1.2 / 0.4 | Table 7.4N | Simply supported, end span, interior span, flat slab, cantilever | sure |
| 140 | 310/σs = 500/(fyk As,req/As,prov); flanged × 0.8 (beff/bw > 3); spans > 7 m × 7/leff, flat slabs > 8.5 m × 8.5/leff | 7.4.2(2) | | sure |
| 141 | cmin,dur by structural class S1-S6 and exposure group (X0, XC1, XC2/XC3, XC4, XD1/XS1, XD2/XS2, XD3/XS3) | 4.4.1.2(5), Table 4.4N | 10-55 mm | sure |
| 142 | Structural class S4 (50 years); +2 for 100 years; -1 at C30/37 (X0, XC1), C35/45 (XC2, XC3), C40/50 (XC4, XD1, XD2, XS1), C45/55 (XD3, XS2, XS3); -1 for slabs | Table 4.3N | Special quality control (-1) not applied | sure |
| 143 | Δcdev = 10 mm, cmin ≥ 10 mm, cmin,b = φ (+5 mm for aggregate > 32 mm) | 4.4.1.3(1), 4.4.1.2(2), (3) | | sure |
| 144 | fbd = 2.25 η1 η2 fctd; η1 = 0.7 poor bond; η2 = (132 - φ)/100 for φ > 32 mm | 8.4.2(2), Eq 8.2 | | sure |
| 145 | fctd taken at most at C60/75 | 8.4.2(2) Note | | unsure (wording) |
| 146 | lb,rqd = (φ/4) σsd/fbd; lb,min = max(0.3 lb,rqd, 10 φ, 100) tension, max(0.6 lb,rqd, 10 φ, 100) compression | 8.4.3(2), 8.4.4(1) | | sure |
| 147 | α1 = 0.7 for bent bars with cd > 3 φ; α2 = 1 - 0.15 (cd - φ)/φ in [0.7, 1]; α3-α5 = 1 | Table 8.2 | α3-α5 at 1 on the safe side | SAEngine practice (α3-α5) |
| 148 | l0 = α1 α2 α3 α5 α6 lb,rqd ≥ max(0.3 α6 lb,rqd, 15 φ, 200); α6 = 1.0 / 1.15 / 1.4 / 1.5 for < 25 / 33 / 50 / > 50 % lapped | 8.7.3, Eqs 8.10, 8.11, Table 8.3 | | sure |
| 149 | As,min = 0.26 fctm/fyk bt d ≥ 0.0013 bt d; As,max = 0.04 Ac | 9.2.1.1(1), (3), Eq 9.1N | Beams and slabs | sure |
| 150 | Slab bars ≤ 3 h ≤ 400 mm (principal), 3.5 h ≤ 450 mm (secondary); secondary ≥ 20 % | 9.3.1.1(2)-(3) | Stored; not wired (slabs keep the parent's) | sure |
| 151 | Columns: φ ≥ 8 mm; As,min = max(0.10 NEd/fyd, 0.002 Ac); As,max = 0.04 Ac (0.08 at laps) | 9.5.2(1)-(3), Eq 9.12N | | sure |
| 152 | Column links ≥ max(6 mm, φmax/4); scl,tmax = min(20 φmin, b, 400 mm), × 0.6 near beams/slabs and at laps; bars ≤ 150 mm from a restrained bar | 9.5.3(1), (3), (4), (6) | The 0.6 reduction is stated, not checked | sure |
| 153 | Walls: As,v 0.002-0.04 Ac, spacing ≤ min(3 t, 400); As,h ≥ max(0.25 As,v, 0.001 Ac), spacing ≤ 400 | 9.6.2, 9.6.3 | Stored; wall rows not wired yet | sure |
| 154 | Exposure classes X0, XC1-4, XD1-3, XS1-3, XF1-4, XA1-3 with indicative strength classes | 4.2 Table 4.1, Annex E Table E.1N | XF, XA have no cover group (combine with XC/XD/XS) | sure (E.1N informative) |
| 155 | Default exposure XC1 | | | SAEngine practice |

## EN 1998-1 Section 5 (concreteMethods.json → seismic)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 156 | special → DCH, intermediate → DCM | C4 mapping (rcSmf, rcImf) | Ductility class of the system | SAEngine practice |
| 157 | fck ≥ 16 MPa (DCM), 20 MPa (DCH) | 5.4.1.1(1), 5.5.1.1(1) | | sure |
| 158 | γRd = 1.0 beams, 1.1 columns (DCM); 1.2 beams, 1.3 columns, 1.2 joints (DCH) | 5.4.2.2(1), 5.4.2.3(1), 5.5.2.1(1), 5.5.2.2(1), 5.5.2.3(2) | Capacity design shear (functions; not wired into the member checks yet) | sure |
| 159 | ΣMRc ≥ 1.3 ΣMRb | 4.4.2.3(4) | Strong column (function) | sure |
| 160 | μφ = 2 q0 - 1 (T1 ≥ TC), 1 + 2 (q0 - 1) TC/T1; × 1.5 with class B steel (DCH) | 5.2.3.4(3)-(4), Eqs 5.4, 5.5 | | sure (class B factor: unsure) |
| 161 | Beams lcr = hw (DCM), 1.5 hw (DCH) | 5.4.3.1.2(1), 5.5.3.1.3(1) | | sure |
| 162 | Beam hoops s ≤ min(hw/4, 24 dbw, 225, 8 dbL) DCM; min(hw/4, 24 dbw, 175, 6 dbL) DCH; first ≤ 50 mm; dbw ≥ 6 mm | 5.4.3.1.2(6), 5.5.3.1.3(6) | | sure |
| 163 | ρ ≥ 0.5 fctm/fyk; ρ ≤ ρ' + 0.0018/(μφ εsy,d) fcd/fyd; As' ≥ 0.5 As in critical regions | 5.4.3.1.2(4)-(5), Eqs 5.11, 5.12 | ρmax row only when μφ is passed (not by the member checks yet) | sure |
| 164 | DCH: 2 bars ≥ 14 mm top and bottom along the beam | 5.5.3.1.3(2) | | sure |
| 165 | νd ≤ 0.65 (DCM), 0.55 (DCH) | 5.4.3.2.1(3), 5.5.3.2.1(3) | NEd the largest of all combinations (on the safe side, not the seismic one alone) | sure (application SAEngine practice) |
| 166 | Columns ρl 0.01-0.04 | 5.4.3.2.2(1) | | sure |
| 167 | lcr = max(hc, lcl/6, 0.45 m) DCM; max(1.5 hc, lcl/6, 0.6 m) DCH | 5.4.3.2.2(4), 5.5.3.2.2(4) | | sure |
| 168 | Column hoops s ≤ min(b0/2, 175, 8 dbL) DCM; min(b0/3, 125, 6 dbL) DCH; restrained bars ≤ 200 (DCM), 150 mm (DCH) | 5.4.3.2.2(11), 5.5.3.2.2(12) | b0 taken as the least side when the hoop cover is not known | sure |
| 169 | DCH columns ≥ 250 mm | 5.5.1.2.2(1) | | sure |
| 170 | α ωwd ≥ 30 μφ νd εsy,d bc/b0 - 0.035; ωwd ≥ 0.08 (DCM base), 0.12 base / 0.08 other (DCH) | 5.4.3.2.2(8)-(9), 5.5.3.2.2(6)-(9) | Function; not wired into the member checks yet | sure |
| 171 | Joints DCH: Vjhd ≤ η fcd √(1 - νd/η) bj hjc, η = 0.6 (1 - fck/250), exterior × 0.8 | 5.5.3.3(2), Eqs 5.33, 5.34 | Function | sure |
| 172 | Walls hcr = max(lw, hw/6); lc ≥ max(0.15 lw, 1.5 bw); ρv ≥ 0.005; ωwd ≥ 0.08 (DCM) / 0.12 (DCH); bw ≥ max(150, hs/20); ε = 1.5 | 5.4.3.4.2, 5.5.3.4.5, 5.4.2.4(7) | Functions; the DCH ε formula is not implemented (the floor 1.5 only) | unsure (DCH ωwd 0.12 for walls) |
| 173 | Coupling beams: diagonals unless VEd ≤ fctd bw d or l/h ≥ 3; VRd = 2 Asi fyd sin α | 5.5.3.5(2)-(3), Eq 5.46 | Functions | sure |

## EN 1997-1 (geotechnicalMethods.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 174 | A1: γG 1.35 / 1.0, γQ 1.5; A2: γG 1.0 / 1.0, γQ 1.3 | Annex A Table A.3 | | sure |
| 175 | M1 all 1.0; M2: γφ' 1.25 (on tan φ'), γc' 1.25, γcu 1.4, γqu 1.4, γγ 1.0 | Table A.4 | | sure |
| 176 | Spread foundations R1 1.0/1.0, R2 bearing 1.4, sliding 1.1, R3 1.0/1.0; earth resistance R2 1.4 | Tables A.5, A.13 | | sure |
| 177 | Driven piles R1 1.0/1.0/1.0/1.25, R2 1.1/1.1/1.1/1.15, R3 1.0/1.0/1.0/1.1, R4 1.3/1.3/1.3/1.6 | Table A.6 | γb/γs/γt/γs,t | sure |
| 178 | Bored piles R1 1.25/1.0/1.15/1.25, R4 1.6/1.3/1.5/1.6 (R2, R3 as driven) | Table A.7 | | sure |
| 179 | CFA piles R1 1.1/1.0/1.1/1.25, R4 1.45/1.3/1.4/1.6 | Table A.8 | | sure |
| 180 | DA1: C1 A1 + M1 + R1, C2 A2 + M2 + R1 (piles A2 + M1 + R4); DA2: A1 + M1 + R2; DA3: A1 (structural) / A2 (geotechnical) + M2 + R3 | 2.4.7.3.4.2-2.4.7.3.4.4 | | sure |
| 181 | Design approach in force DA1 | 2.4.7.3.4.1 | National choice; overridable | SAEngine practice |
| 182 | Nq, Nc = (Nq - 1) cot φ', Nγ = 2 (Nq - 1) tan φ' | Annex D.4 | | sure |
| 183 | sq = 1 + (B'/L') sin φ', sγ = 1 - 0.3 B'/L', sc = (sq Nq - 1)/(Nq - 1) | D.4 | | sure |
| 184 | iq, iγ with m = (2 + B'/L')/(1 + B'/L'); ic = iq - (1 - iq)/(Nc tan φ'); bq = bγ = (1 - α tan φ')² | D.4 | Load along B' only | sure |
| 185 | Undrained (π + 2) cu bc sc ic + q; sc = 1 + 0.2 B'/L'; ic = ½ (1 + √(1 - H/(A' cu))); bc = 1 - 2α/(π + 2) | D.3 | | sure |
| 186 | Sliding: δd = φ'cv,d cast in place, 2/3 φ'cv,d precast; undrained Rd ≤ 0.4 Vd where water can reach the interface | 6.5.3(10)-(12) | | sure |
| 187 | ξ1 / ξ2 for n = 1, 2, 3, 4, ≥ 5: 1.4/1.4, 1.3/1.2, 1.2/1.05, 1.1/1.0, 1.0/1.0 | Table A.9 | Static load tests | sure |
| 188 | ξ3 / ξ4 for n = 1, 2, 3, 4, 5, 7, 10: 1.40/1.40, 1.35/1.27, 1.33/1.23, 1.31/1.20, 1.29/1.15, 1.27/1.12, 1.25/1.08 | Table A.10 | Ground tests; linear between rows | sure (interpolation SAEngine practice) |
| 189 | ξ ÷ 1.1 for stiff structures (ξ1 ≥ 1.0) | 7.6.2.2(9), 7.6.2.3(9) | | unsure (which ξ the division applies to) |
| 190 | Rc,k from the initial tests' failure loads, Rc,d = Rc,k/γt per DA combination | 7.6.2.2(8), (14) | Reported in the pile type's load-test results | sure |
