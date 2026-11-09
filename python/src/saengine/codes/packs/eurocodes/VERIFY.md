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

## Alpha 9 C5b: values added with the design wiring

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| 191 | λlim = 20 A B C / √n; A = 1/(1 + 0.2 φef), B = √(1 + 2ω), C = 1.7 - rm | EN 1992-1-1 5.8.3.1(1) Eq 5.13N | `slenderness.limitCoefficient`, `creepShare`, `mechanicalShare`, `momentRatioBase` | sure |
| 192 | rm = 1.0 for unbraced members and first-order moments mainly from imperfections or transverse load | 5.8.3.1(1) | `unbracedRatio`; SAEngine takes "transverse" from a curved moment diagram, a free end or a spectrum combination | sure |
| 193 | φ(∞, t0) = 2.0, φef = φ × M0Eqp/M0Ed with the share = the sustained share of the axial force (else 0.65) | 5.8.4(2), 3.1.4 Fig 3.1 | `creepCoefficient`, `sustainedShare`: SAEngine practice, overridable | unsure (practice values) |
| 194 | 1/r0 = εyd/(0.45 d), d = h/2 + is | 5.8.8.3(1)-(2) | `curvatureDepthShare` | sure |
| 195 | Kr = (nu - n)/(nu - nbal) ≤ 1, nu = 1 + ω, nbal = 0.4 | 5.8.8.3(3) Eq 5.36 | `balancedAxial` | sure |
| 196 | Kφ = 1 + β φef ≥ 1, β = 0.35 + fck/200 - λ/150 | 5.8.8.3(4) Eq 5.37 | `betaBase`, `betaFckDivisor`, `betaLambdaDivisor` | sure |
| 197 | e2 = (1/r) l0²/c, c = 10 | 5.8.8.2(4) | `curvatureDistribution` | sure |
| 198 | Braced: M0e = 0.6 M02 + 0.4 M01 ≥ 0.4 M02; MEd ≥ M01 + 0.5 M2 and M02 | 5.8.8.2(2)-(3) Eqs 5.32, 5.33 | `equivalentMoment`, `curvatureShareEnd`; unbraced MEd = M02 + M2 | sure |
| 199 | l0 = k lu with k of SAEngine's frame (the parent's alignment chart) | 5.8.3.2 | Eqs 5.15/5.16 not used | SAEngine practice |
| 200 | xu/d ≤ (1 - k1)/k2, k1 = 0.44, k2 = 1.25 (δ = 1) for slabs, stairs and the proposal's beams | 5.5(4) | `ultimate.neutralAxisLimit`; fck ≤ 50 MPa values | sure (its use as a ductility limit is SAEngine practice) |
| 201 | Quasi-permanent combination 6.16b (G + 0.3Q), characteristic 6.14b-Q for the stress and crack rows | EN 1990 6.5.3; EN 1992-1-1 7.2, 7.3 | `serviceStress.quasiPermanent`, `characteristic` (ids of `combinations.service`) | sure |
| 202 | Crack and stress rows with αe = Es/Ecm on the cracked rectangle; exposure `defaultExposure` XC1 | 7.2, 7.3.4 | No effective modulus | SAEngine practice |
| 203 | Span/depth with As,req = As,prov; beff/bw from beff,i = 0.2 l0, l0 = 0.85 l | 7.4.2, 5.3.2.1 | On the safe side | SAEngine practice |
| 204 | Slab As,min = the beams' 9.2.1.1(1) per metre; secondary ≥ 20 % of the main; spacing min(3h, 400) principal, min(3.5h, 450) secondary | 9.3.1.1(1)-(3) | `memberSteel` (rows 157-158) | sure |
| 205 | Wall in-plane shear by 6.2 with bw = t, d = 0.8 lw, the horizontal bars as links | 6.2.2, 6.2.3 | d = 0.8 lw as the parent | SAEngine practice |
| 206 | Ductile walls VEd × ε = 1.5 | EN 1998-1 5.4.2.4(7) | DCH ε by Eq 5.25 not implemented (the 1.5 floor only) | unsure for DCH |
| 207 | Beams' capacity design shear VEd = γRd (MRb,1 + MRb,2)/lcl + VG, both end moments in full | EN 1998-1 5.4.2.2(2), 5.5.2.1(2) | min(1, ΣMRc/ΣMRb) taken as 1 (on the safe side) | sure |
| 208 | Columns' capacity design shear VEd = γRd 2 MRc/lcl, MRc the largest over the axial range | 5.4.2.3, 5.5.2.2 | Both ends' MRc equal (one section) | sure |
| 209 | DCH beams' critical regions with cot θ = 1 | 5.5.3.1.2(1) | | sure |
| 210 | Joint shear Vjhd = γRd (As1 + As2) fyd - VC interior, γRd As1 fyd - VC exterior | 5.5.2.3(2) Eqs 5.22, 5.23 | VC = 0 on the safe side; γRd = 1.2 | sure |
| 211 | bj = min(bc, bw + 0.5 hc) if bc > bw, else min(bw, bc + 0.5 hc) | 5.5.3.3(1) | hjc = hc less the hoops and bars | sure |
| 212 | Strong column not required at the top joint | EN 1998-1 4.4.2.3(6) | Reported only | sure |
| 213 | Footings: set A2 actions from the A1 strength combinations × γG(A2)/γG(A1) on permanent and × γQ(A2)/γQ(A1) on variable cases; earthquake combinations unchanged | EN 1997-1 2.4.7.3.4, Table A.3 | | SAEngine practice |
| 214 | The founding layer's φ'k, c'k, cu,k, γ of the nearest borehole; drained and undrained where both are given; φ'cv,k = φ'k | 6.5.2, 6.5.3(10) | `footings.drained`, `phiCvShare`: overridable | SAEngine practice |
| 215 | Piles from ground tests: Rc,cal per borehole (SAEngine's static method), n = the boreholes, Rc,k = min(mean/ξ3, min/ξ4), split base/shaft by their mean shares | 7.6.2.3(5)-(8) | | sure (the split is SAEngine practice) |
| 216 | Rt,k = the shaft's uplift share with ξ3, ξ4; Rt,d = Rt,k/γs,t + the pile's weight | 7.6.3.3 | | SAEngine practice (the weight) |

## Alpha 9 C5c: the remainder of the concrete, foundation and load parts

Numbered C5c-1 on so that they do not clash with the rows of the other alpha 9 tracks.

### EN 1992-1-1 (concreteMethods.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| C5c-1 | Struts σRd,max = fcd without transverse tension, 0.6 ν' fcd in cracked zones, ν' = 1 - fck/250 | 6.5.2(1)-(2), Eqs 6.55, 6.56, 6.57N | `strutAndTie.strutUncracked`, `strutCracked`, `nuDivisor` | sure |
| C5c-2 | Nodes k1 = 1.0 (C-C-C), k2 = 0.85 (C-C-T), k3 = 0.75 (C-T-T) × ν' fcd | 6.5.4(4) Eqs 6.60-6.62 | `nodeCCC`, `nodeCCT`, `nodeCTT` | sure |
| C5c-3 | Ties As fyd | 6.5.3 | No φ | sure |
| C5c-4 | Least strut-tie angle 21.8° (cot θ <= 2.5) | 6.5 (none given) | `minAngle` | SAEngine practice |
| C5c-5 | Deep beam: span < 3 h | 5.3.1(3) | `deepSpanRatio`; the parent's concentrated-load rule (within 2 h of a support) also kept | sure (the load rule SAEngine practice) |
| C5c-6 | Deep beam web mesh As,dbmin = 0.1 % of Ac per face and direction, at least 150 mm²/m; spacing min(2 b, 300 mm) | 9.7(1)-(2) | `deepMeshRatio`, `deepMeshMin`, `deepMeshSpacing` | sure |
| C5c-7 | Deep beams, deep pile caps: tie lever arm z = 0.9 d | 6.5 | `tieArm` (as the parent) | SAEngine practice |
| C5c-8 | Corbel: z0 = 0.8 d, tan θ = z0/ac within 1.0-2.5 | Annex J.3, Figure J.5 | `corbelLeverShare`, `corbelTanTheta` | unsure (tan θ limits); z0 SAEngine practice |
| C5c-9 | Corbel: closed horizontal links ΣAs,lnk >= k1 As,main where ac <= 0.5 hc, k1 = 0.25; vertical links >= k2 FEd/fyd where ac > 0.5 hc and FEd > VRd,c, k2 = 0.5 | Annex J.3(2)-(3) | `corbelShortShare`, `corbelHorizontalLinks`, `corbelVerticalLinks` | unsure (k1, k2 recommended values) |
| C5c-10 | Corbel HEd at least 0.2 FEd where none is given | none in EN 1992-1-1 | `corbelHorizontalForce` | SAEngine practice |
| C5c-11 | Corbel strut at the column face over x cos θ, x = 2 (d - z0), cracked 0.6 ν' fcd | 6.5.2 | | SAEngine practice |
| C5c-12 | Interface shear vRdi = c fctd + μ σn + ρ fyd μ (α = 90°) <= 0.5 ν fcd, c = 0 under tension | 6.2.5(1) Eqs 6.23-6.25 | `interfaceShear` | sure |
| C5c-13 | c / μ: very smooth 0.025 / 0.5, smooth 0.20 / 0.6, rough 0.40 / 0.7, indented 0.50 / 0.9 | 6.2.5(2) | `surfaces`; very smooth c = 0.025 (the code gives 0.025-0.10) | sure |
| C5c-14 | The parent's surfaces read as monolithic = indented, roughened = rough, not roughened = smooth, steel = very smooth | | `surfaceMap` | SAEngine practice |
| C5c-15 | Peripheral tie Ftie,per = li q1, q1 = 10 kN/m, at least q2 = 70 kN | 9.10.2.2(2) Eq 9.15 | `ties.peripheralPerLength`, `peripheralMin` | unsure (whether q2 is a least value or a cap: check the Note) |
| C5c-16 | Internal tie 20 kN/m, (l1 + l2)/2 taken as the beam's span, at least 70 kN | 9.10.2.3(4) | `internalPerLength`, `internalMin` | unsure (the q3/q4 form); span SAEngine practice |
| C5c-17 | Column ties 150 kN, facade 20 kN/m | 9.10.2.4(2) | `columnMin`, `facadePerLength` (facade value stored, not checked) | sure |
| C5c-18 | Ties at fyd of the accidental situation (γs = 1.0) | 9.10.1(4), 2.4.2.4 | | sure |
| C5c-19 | Column bases: control perimeters within 2d, vRd = CRd,c k (100 ρ fck)^(1/3) 2d/a >= vmin 2d/a, VEd,red = VEd - ΔVEd | 6.4.4(2) Eqs 6.50, 6.51 | `footingPunching` | sure |
| C5c-20 | k of the moment: c1/c2 <= 0.5: 0.45, 1.0: 0.6, 2.0: 0.7, >= 3.0: 0.8 (linear between) | 6.4.3(3) Table 6.1 | `momentK`; W of the perimeter at a by Eq 6.41's form | sure (W at a < 2d SAEngine practice) |
| C5c-21 | The critical perimeter searched at 16 distances to 2d; the soil pressure inside by the mean over the bounding rectangle | | `steps` | SAEngine practice |
| C5c-22 | Raft edge and corner columns: u1 at 2d with β, VEd less the net reaction within 2d | 6.4.2, 6.4.3(6) | | SAEngine practice |
| C5c-23 | Pile caps: VEd less the pile reactions inside each perimeter (by the share of a pile's area inside) | 6.4.2(2) | | SAEngine practice |
| C5c-24 | Walls out of plane: l0 = β lc, β = 1.0 held by both floors, 2.0 free-standing; i = t/√12; M at least NEd e0 | 5.8.3.2, 6.1(4) | `wallSlenderness.effectiveLength` | SAEngine practice (cf. 12.6.5.1 Table 12.1 for plain walls) |
| C5c-25 | Walls out of plane: single curvature rm = 1 (C = 0.7), nominal curvature beyond λlim | 5.8.3.1, 5.8.8 | | SAEngine practice (on the safe side) |
| C5c-26 | Flanged wall groups: the webs' VRd summed, VEd × ε (the largest class's ε) of a ductile wall | 6.2; EN 1998-1 5.4.2.4(7) | | SAEngine practice |
| C5c-27 | Slabs: span/depth with K 1.0 simply supported, 1.3 end span, 1.5 interior, 1.2 flat slabs; two-way slabs the shorter span, flat slabs the longer; ρ of the bottom bars | 7.4.2(2) Table 7.4N | `deflection` (C5's values) | sure |
| C5c-28 | Stairs: span/depth as one-way slabs by their continuous ends | 7.4.2 | | SAEngine practice |
| C5c-29 | Mandrel φm,min = 4 φ (φ <= 16 mm), 7 φ (> 16 mm) | 8.3(2) Table 8.1N | `barShapes.mandrel` | sure |
| C5c-30 | Bends and hooks of main bars: 5 φ past the bend | 8.4.1 Figure 8.1 | `bendTail` | unsure (the straight length of Figure 8.1 b, c) |
| C5c-31 | Links: 135° hooks 5 φ >= 50 mm, 90° bends 10 φ >= 70 mm | 8.5(1) Figure 8.5 | `link135`, `link90` | unsure |
| C5c-32 | Hooked anchorage lb,eq = α1 lb,rqd, α1 = 0.7 where cd > 3 φ (side cover given), else 1.0 | 8.4.4 Table 8.2 | `anchorage.hookAlpha` (C5) | sure (cd taken as 4 φ with the cover flag: SAEngine practice) |
| C5c-33 | Compression anchorage lbd = lb,rqd >= max(0.6 lb,rqd, 10 φ, 100 mm) | 8.4.4(1) Eq 8.7 | `anchorage.minCompression` (C5) | sure |
| C5c-34 | Compression laps l0 = α6 lb,rqd (α1 = α2 = 1) >= l0,min; one transverse bar outside each end within 4 φ | 8.7.3, 8.7.4.2(1) | `compressionLapEnd` | sure |
| C5c-35 | Column splices: all bars lapped at one section (α6 1.5) | 8.7.3 Table 8.3 | `columnLapShare` | SAEngine practice (on the safe side) |
| C5c-36 | Columns DCM/DCH: α ωwd >= 30 μφ νd εsy,d bc/b0 - 0.035, ωwd >= 0.08 (DCM base) / 0.12 (DCH base) | EN 1998-1 5.4.3.2.2(8), 5.5.3.2.2(6), (8) | C5's `confinementCoefficient`, `confinementOffset`, `omegaBase` | sure |
| C5c-37 | The base region's rule for every critical region; α = αn αs with the legs evenly spaced | EN 1998-1 5.4.3.2.2(8), Eqs 5.16-5.17 | | SAEngine practice (on the safe side) |
| C5c-38 | μφ from q0 = the analysis's q (kw = 1), T1 = Ct H^(3/4), TC of the ground type | EN 1998-1 5.2.3.4(3) Eqs 5.4, 5.5; 4.3.3.2.2(3) | | SAEngine practice (T1 approximate) |
| C5c-39 | Ductile walls' boundary elements: α ωwd >= 30 μφ (νd + ωv) εsy,d bw/b0 - 0.035, ωwd >= 0.08 (DCM) / 0.12 (DCH) | EN 1998-1 5.4.3.4.2(4) Eq 5.20, 5.5.3.4.5 | `wallOmega` (C5) | sure (DCH's 0.12 unsure) |

### EN 1997-1 (geotechnicalMethods.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| C5c-40 | EQU: γG,dst 1.10, γG,stb 0.90, γQ,dst 1.50 | EN 1990 Table A1.2(A) | `equilibrium` (overturning of retaining walls) | sure |
| C5c-41 | Retaining walls: Ka(φ'd) / Ka(φ'k) by Rankine on the retained soil (K0 = 1 - sin φ' at rest) | EN 1997-1 9.5, Annex C | `retaining` | SAEngine practice (the ratio) |
| C5c-42 | Retaining walls: sliding V'd tan δd / γR,h, δd = φ'd under the base (cast in place), passive / γR,e | 9.7.3, 6.5.3 | | sure |
| C5c-43 | Retaining walls: bearing on B' = B - 2e (Annex D) per design combination | 9.7.2, 6.5.2 | | sure |
| C5c-44 | Retaining walls: the stem and base under γG of A1 (1.35) on the earth pressure | EN 1990 Table A1.2(B), EN 1997-1 2.4.7.3.4 | | SAEngine practice |
| C5c-45 | Footing sizing assistant by the bearing resistance rows of the design approach | 6.5.2 | | SAEngine practice |

### EN 1991-1-4 (wind.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| C5c-46 | Torsion by e = b/10 with the full pressure; no simultaneous cases | 7.1.2(2), Figure 7.1 | `designCases` (Case 2 of the design wind cases) | sure |
| C5c-47 | co = 1 for Φ < 0.05; 1 + 2 s Φ for 0.05 <= Φ < 0.3; 1 + 0.6 s for Φ >= 0.3 with Le = H/0.3 | Annex A.3 Eqs A.1-A.3 | `orography` | sure |
| C5c-48 | s upwind A e^(B X/Lu), A = 0.1552 z⁴ - 0.8575 z³ + 1.8133 z² - 1.9115 z + 1.0124, B = 0.3542 z² - 1.0577 z + 2.6456 (z = z/Le), -1.5 <= X/Lu <= 0, z/Le <= 2 | Annex A.3 Eq A.2 | `upwindA`, `upwindB` | unsure (the polynomial coefficients) |
| C5c-49 | s downwind of hills and ridges A e^(B X/Ld), B = -0.3056 z² + 1.0212 z - 1.7637, 0 <= X/Ld <= 2 | Annex A.3 Eq A.4 | `hillB` | unsure (the polynomial coefficients) |
| C5c-50 | s downwind of cliffs and escarpments A log²(X/Le) + B log(X/Le) + C, A = -1.3420 l³ - 0.8222 l² + 0.4609 l - 0.0791, B = -1.0196 l³ - 0.8910 l² + 0.5343 l - 0.1156, C = 0.8030 l³ + 0.4236 l² - 0.5738 l + 0.1606 (l = log z/Le), 0.1 <= X/Ld <= 3.5, z/Le >= 0.1; linear to the crest below 0.1 | Annex A.3 Eq A.3 | `cliffA`, `cliffB`, `cliffC` | unsure (coefficients, and X/Le or X/Ld in the log) |
| C5c-51 | Lu = 2 × the project's half-height distance Lh, Ld = Lu | | `lengthFromHalfHeight` | SAEngine practice |
| C5c-52 | cscd of Annex B: zs = 0.6 h, L(zs) = 300 (zs/200)^α, α = 0.67 + 0.05 ln z0, B² = 1/(1 + 0.9 ((b + h)/L)^0.63), SL = 6.8 fL/(1 + 10.2 fL)^(5/3), R² = π²/(2δ) SL Rh Rb, η = 4.6 fL h/L (b), kp = √(2 ln νT) + 0.6/√(2 ln νT) >= 3, ν >= 0.08 Hz, T = 600 s | 6.3.1, Annex B.1-B.2 | `structuralFactor.detailed` | sure |
| C5c-53 | n1 = 46/h where the project gives none; δs = 0.10 (concrete buildings), 0.05 (steel); δa left out | Annex F Eq F.2, Table F.2 | `frequencyCoefficient`, `structuralDamping` | sure (δa omitted: SAEngine practice, on the safe side) |
| C5c-54 | cpe = cpe,1 at A <= 1 m², cpe,10 at A >= 10 m², log10 A between | 7.2.1 Figure 7.2 | `localPressures.areaSmall`, `areaLarge` | sure |
| C5c-55 | Walls cpe,10 / cpe,1: A -1.2/-1.4, B -0.8/-1.1, C -0.5/-0.5; D +0.8/+1.0 (h/d >= 1), +0.7/+1.0 (<= 0.25); E -0.7 (5), -0.5 (1), -0.3 (<= 0.25) | 7.2.2 Table 7.1 | `zones` | sure |
| C5c-56 | Flat roofs cpe,10 / cpe,1, sharp eaves: F -1.8/-2.5, G -1.2/-2.0, H -0.7/-1.2, I ±0.2; parapets hp/h 0.025: F -1.6/-2.2, G -1.1/-1.8; 0.05: -1.4/-2.0, -0.9/-1.6; 0.10: -1.2/-1.8, -0.8/-1.4 | 7.2.3 Table 7.2 | `zones` (H with parapets as sharp eaves) | unsure (the parapet rows) |
| C5c-57 | e = min(b, 2h); cpi +0.2 / -0.3 the more onerous | 7.2.2 Figure 7.5, 7.2.9(6) Note 2 | `edgeFactor`, `internal` | sure |

### EN 1991-1-3 (snow.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| C5c-58 | Roofs abutting taller construction: μ2 = μs + μw, μw = (b1 + b2)/(2h) <= γh/sk, 0.8 <= μw <= 4, ls = 2h within 5-15 m, μs = 0 for α <= 15°, γ = 2 kN/m³ | 5.3.6 Eqs 5.8, 5.9 | `drift` (method `shapeCoefficient`) | sure |
| C5c-59 | Parapets: μ2 = γh/sk within 0.8-2.0, ls = 2h within 5-15 m | 6.2 Eq 6.1 | `parapetRange` | sure |
| C5c-60 | μ1 = 0.8 away from the drift; Annex B (exceptional drifts) not covered | 5.3.6, Annex B | `lowerShape` | sure |

### EN 1998-1 (seismic.json)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| C5c-61 | Plan: λ = Lmax/Lmin <= 4; the floor within its convex envelope, the area between <= 5 % of the floor's | 4.2.3.2(4)-(5) | `regularity.slendernessMax`, `compactnessShare` | sure |
| C5c-62 | Plan: e0 <= 0.30 r, r >= ls in both directions; the stiffness centre and r from the moments of inertia of the columns and walls | 4.2.3.2(6) Eqs 4.1a, 4.1b; 4.2.3.2(8) | `eccentricityShare`, `torsionalRadius` | sure (the centre of mass at the floor's centroid SAEngine practice) |
| C5c-63 | Elevation: setbacks symmetric each <= 20 % of the dimension below; a single one in the lower 15 % of the height <= 50 %; unsymmetric each <= 10 % and together <= 30 % of the base's | 4.2.3.3(5) Figure 4.1 | `setbackShare`, `baseHeightShare`, `baseSetbackShare`, `unsymmetricShare`, `unsymmetricTotal` | sure |
| C5c-64 | A setback symmetric when its two sides differ by at most 25 % of it | | `symmetryTolerance` | SAEngine practice |
| C5c-65 | Abrupt change indicators: storey stiffness < 70 % of the storey above, mass > 150 % of an adjacent storey | 4.2.3.3(3) (no numbers) | `irregularities.soft`, `mass` | SAEngine practice |
| C5c-66 | Not regular in elevation: q0 × 0.8 (and qd = q); not regular in plan: αu/α1 = (1 + αu/α1)/2 | 4.2.3.1(7), 5.2.2.2(6) | `elevationFactor`, `planAverage`; αu/α1 is the system's Ω0 | sure (applied to q of every system: the plan rule is written for concrete systems) |
| C5c-67 | δ = 1 + 0.6 x/Le (1.2 for planar models) where no accidental eccentricity is analysed | 4.3.3.2.4(1)-(2) Eq 4.12 | `torsionalEffects`; the larger of the two directions' δ rounded up to 0.05 | sure (application SAEngine practice) |
| C5c-68 | Modes independent when Tj <= 0.9 Ti; SRSS where all are, else CQC | 4.3.3.3.2(1)-(3) | `modalCombination` | sure |
| C5c-69 | Vertical component where avg > 0.25 g; avg/ag = 0.90 (Type 1), 0.45 (Type 2); the vertical spectrum's plateau 3.0 avg/q with q = 1.5; 0.30 in the combination | 4.3.3.5.2(1), (4), Table 3.4, 3.2.2.5(5) | `verticalComponent` | sure (every member, the plateau: SAEngine practice) |
| C5c-70 | Foundations: EFd = EF,G + γRd Ω EF,E, γRd = 1.0 for q <= 3, 1.2 above, Ω <= q | 4.4.2.6(2)-(4) Eq 4.30 | `foundationCapacity` | sure |
| C5c-71 | Ω taken as q (the elastic response) unless the project gives one | 4.4.2.6(2) | `foundationCapacity.omega` | SAEngine practice (on the safe side) |
| C5c-72 | Type 2 spectrum where the earthquakes that contribute most have Ms <= 5.5 | 3.2.2.2(2) Note 1 | `spectrumTypeGuidance` | sure |

## Steel and the other materials (alpha 9 track C6)

Tables `steelLimitState` (groups `memberResistance`, `connections`, `seismic`), `steel`,
`steelStability`, `steelSeismic`, `composite`, `timber`, `masonry`, `aluminium`.

| # | Value | Clause | Note | Certainty |
|---|---|---|---|---|
| 217 | γM0 = 1.00, γM1 = 1.00, γM2 = 1.25 | EN 1993-1-1 6.1(1) Note 2B | Recommended values | sure |
| 218 | E = 210 000 MPa, G = 81 000 MPa | EN 1993-1-1 3.2.6(1) | The calculations' values (the material's E is not used by the method) | sure |
| 219 | fy for t > 40 mm: S235 215, S275 255, S355 335, S450 410 MPa | EN 1993-1-1 Table 3.1 (EN 10025-2) | Matched by the nominal fy; t the thickest plate | sure |
| 220 | ε = √(235/fy) | Table 5.2 | | sure |
| 221 | Internal parts in compression 33 / 38 / 42 ε, bending 72 / 83 / 124 ε | Table 5.2 sheet 1 | | sure |
| 222 | Bending and compression: class 1 396ε/(13α - 1) (α > 0.5) else 36ε/α; class 2 456ε/(13α - 1) else 41.5ε/α; class 3 42ε/(0.67 + 0.33ψ) (ψ > -1) else 62ε(1 - ψ)√(-ψ) | Table 5.2 sheet 1 | α plastic of the web under N, ψ elastic on the gross section | sure |
| 223 | Outstand flanges 9 / 10 / 14 ε | Table 5.2 sheet 2 | Also used for minor-axis bending tips (14ε, on the safe side) | sure |
| 224 | Tubes d/t 50 / 70 / 90 ε²; angles h/t <= 15ε and (b + h)/2t <= 11.5ε (class 3) | Table 5.2 sheet 3 | Class 4 tubes not covered (EN 1993-1-6) | sure |
| 225 | λ̄p = (b/t)/(28.4 ε √kσ); ρ = (λ̄p - 0.055(3 + ψ))/λ̄p² for λ̄p > 0.5 + √(0.085 - 0.055ψ) (internal); ρ = (λ̄p - 0.188)/λ̄p² for λ̄p > 0.748 (outstand) | EN 1993-1-5 4.4(2) Eqs 4.2, 4.3 | | sure |
| 226 | kσ internal: 4.0 (ψ = 1), 8.2/(1.05 + ψ) (1 > ψ > 0), 7.81 - 6.29ψ + 9.78ψ² (0 > ψ > -1), 23.9 (ψ = -1); outstand 0.43 (uniform), 0.57 (tip compression, root zero) | EN 1993-1-5 Tables 4.1, 4.2 | | sure (0.57: verify the row of Table 4.2 used) |
| 227 | Web effective zone be1 = 0.4 beff, be2 = 0.6 beff of the compression zone | EN 1993-1-5 Table 4.1 | One pass (no iteration of the neutral axis): SAEngine practice | sure (the method: SAEngine practice) |
| 228 | α: a0 0.13, a 0.21, b 0.34, c 0.49, d 0.76; Φ = 0.5[1 + α(λ̄ - 0.2) + λ̄²] | Table 6.1, Eq 6.49 | | sure |
| 229 | Rolled I curves: h/b > 1.2, tf <= 40: a/b (S460: a0/a0); 40 < tf <= 100: b/c (a/a); h/b <= 1.2, tf <= 100: b/c (a/a); tf > 100: d/d (c/c) | Table 6.2 | | sure |
| 230 | Welded I: tf <= 40: b/c; tf > 40: c/d. Hot-finished hollow a (S460 a0), cold-formed c; U, T, solid c; L b | Table 6.2 | SAEngine sections taken as rolled; ERW hollow sections as cold-formed (the run's option) | sure |
| 231 | Torsional and flexural-torsional modes with the z-z curve | 6.3.1.4(1) | Ncr,T = (G It + π² E Iw / LT²)/i0² | sure |
| 232 | Single angles about v-v, curve b | Table 6.2 | Annex BB.1.2 (truss angles) not applied | SAEngine practice |
| 233 | LTB general case curves: rolled I h/b <= 2 a, > 2 b; welded c / d; other d | Table 6.4 | | sure |
| 234 | LTB rolled case: λ̄LT,0 = 0.4, β = 0.75; rolled I h/b <= 2 b, > 2 c; welded c / d; χLT <= 1/λ̄LT² | 6.3.2.3(1), Table 6.5 | Default method `rolled`; f = 1 (`modification: none`) or kc = 1/√C1 (option) | sure (kc = 1/√C1 is an NCCI approximation: SAEngine practice) |
| 235 | Mcr = C1 π²EIz/L² √(Iw/Iz + L²GIt/(π²EIz)), k = kw = 1, zg = 0; C1 = the moment diagram's equivalent factor, at most 2.7 | (not in EN 1993-1-1: the elastic critical moment) | Cantilever segments L × 2, C1 = 1: SAEngine practice | SAEngine practice |
| 236 | Annex B class 1-2: kyy = Cmy(1 + (λ̄y - 0.2)nY) <= Cmy(1 + 0.8nY); kzz (I) = Cmz(1 + (2λ̄z - 0.6)nZ) <= Cmz(1 + 1.4nZ), (RHS) as kyy; kyz = 0.6 kzz; kzy = 0.6 kyy (not susceptible) or 1 - 0.1λ̄z nZ/(CmLT - 0.25) >= 1 - 0.1 nZ/(CmLT - 0.25) (λ̄z >= 0.4), 0.6 + λ̄z below | Annex B Tables B.1, B.2 | | sure |
| 237 | Annex B class 3-4: kyy = Cmy(1 + 0.6λ̄y nY) <= Cmy(1 + 0.6nY); kzz likewise; kyz = kzz; kzy = 0.8 kyy or 1 - 0.05λ̄z nZ/(CmLT - 0.25) >= ... | Annex B Tables B.1, B.2 | | sure |
| 238 | Cm = 0.6 + 0.4ψ >= 0.4 of a linear diagram; 1.0 with transverse load | Table B.3 | The transverse-load rows of Table B.3 not used (1.0 on the safe side): SAEngine practice | sure (the 1.0: SAEngine practice) |
| 239 | Annex A: Cmi,0 = 0.79 + 0.21ψ + 0.36(ψ - 0.33)NEd/Ncr,i; non-linear diagrams 1 + 0.03 NEd/Ncr | Annex A Table A.2 | The second: the uniformly loaded span row | unsure (the non-linear row) |
| 240 | Annex A: μ, wy, wz <= 1.5, npl, aLT = 1 - It/Iy, Cyy, Cyz, Czy, Czz with 1.6, 14, w^5, bLT 0.5, cLT 10/(5 + λ̄z⁴), dLT 2/(0.1 + λ̄z⁴), eLT 1.7/(0.1 + λ̄z⁴), λ̄0 <= 0.2√C1[(1 - NEd/Ncr,z)(1 - NEd/Ncr,TF)]^¼ | Annex A Tables A.1, A.2 | λ̄0 from λ̄LT with C1 | unsure (transcribed from memory: check every constant) |
| 241 | Shear area of rolled I A - 2btf + (tw + 2r)tf >= η hw tw; channels A - 2btf + (tw + r)tf; T 0.9(A - btf); RHS Ah/(b + h); CHS 2A/π; solid A | 6.2.6(3) | Minor axis of I 2 b tf; angles the leg | sure (the minor-axis and angle areas: SAEngine practice) |
| 242 | η = 1.2; shear buckling when hw/tw > 72ε/η; λ̄w = hw/(37.4 tw ε √kτ), kτ = 5.34; χw = η (λ̄w < 0.83/η) else 0.83/λ̄w | EN 1993-1-1 6.2.6(6); EN 1993-1-5 5.2-5.3 Table 5.1 | Non-rigid end post, the flanges not counted | sure |
| 243 | Bending and shear: ρ = (2VEd/Vpl,Rd - 1)² above 0.5 Vpl,Rd; I-sections My,V,Rd = (Wpl - ρAw²/4tw) fy/γM0 | 6.2.8 | Other shapes (1 - ρ) Mc,Rd: SAEngine practice | sure |
| 244 | MN,y = Mpl,y(1 - n)/(1 - 0.5a), a <= 0.5; MN,z by n vs a; exponents α 2, β 5n >= 1 (I); RHS 1.66/(1 - 1.13n²) <= 6; CHS (1 - n^1.7), 2 | 6.2.9.1(4)-(6) | Other shapes and class 3-4 linear | sure |
| 245 | Nu,Rd = 0.9 Anet fu / γM2 | 6.2.3(2) | Anet from the run's net area ratio | sure |
| 246 | αcr >= 10 for first-order analysis | 5.2.1(3) Eq 5.1 | αcr ≈ r/(r - 1) from r = Δ2nd/Δ1st: SAEngine practice | sure (the estimate: SAEngine practice) |
| 247 | φ = φ0 αh αm, φ0 = 1/200, αh = 2/√h, 2/3 <= αh <= 1, αm taken as 1 | 5.3.2(3) Eq 5.5 | Every combination; h the model's height | sure (αm = 1: SAEngine practice) |
| 248 | Bolt classes fyb/fub: 4.6 240/400, 4.8 320/400, 5.6 300/500, 5.8 400/500, 6.8 480/600, 8.8 640/800, 10.9 900/1000 | EN 1993-1-8 Table 3.1 | A307 as 4.6, A325 as 8.8, A490 as 10.9: SAEngine practice | sure |
| 249 | Fv,Rd = αv fub As/γM2, αv 0.6 (4.6, 5.6, 8.8), 0.5 (4.8, 5.8, 6.8, 10.9) | Table 3.4 | The shear plane through the threads (As) on the safe side | sure |
| 250 | Ft,Rd = 0.9 fub As/γM2; Fv/Fv,Rd + Ft/(1.4 Ft,Rd) <= 1 | Table 3.4, 3.6.1 | Punching shear Bp,Rd not checked | sure |
| 251 | As M12 84.3, M14 115, M16 157, M18 192, M20 245, M22 303, M24 353, M27 459, M30 561, M33 694, M36 817 mm² | EN ISO 898-1 / the bolt standards | | sure |
| 252 | Fb,Rd = k1 αb fu d t/γM2, αd = e1/3d0 (end), p1/3d0 - 1/4 (inner), αb = min(αd, fub/fu, 1), k1 = 2.5 | Table 3.4 | k1 at its largest (the transverse edges e2, p2 not known to the line: assumes e2 >= 1.5 d0, p2 >= 3 d0) | unsure (k1 assumption, check the edges) |
| 253 | Fillet welds fvw,d = fu/(√3 βw γM2) (simplified); directional F/a <= fu/(βw γM2 √(3 - sin²θ)), σ⊥ <= 0.9 fu/γM2; βw 0.80 (fu <= 360), 0.85 (<= 430), 0.90 (<= 510), 1.00 above | EN 1993-1-8 4.5.3.2-4.5.3.3, Table 4.1 | fu of the weaker part (the member and plate); the least listed fu when not known | sure |
| 254 | Block tearing Veff = fu Ant/γM2 + fy Anv/(√3 γM0) (0.5 fu Ant eccentric) | 3.10.2 Eqs 3.9, 3.10 | | sure |
| 255 | Slip Fs,Rd = ks n μ (Fp,C - 0.8 Ft,Ed)/γM3, Fp,C = 0.7 fub As, γM3 1.25 (ULS) / 1.1 (SLS); μ A 0.5, B 0.4; ks 1.0 normal, 0.85 oversize/short slot, 0.7 long slot | 3.9.1, 3.9.2, Tables 3.6, 3.7, Table 2.1 | The type's surface classes A, B read as EN classes A, B | sure (the class mapping: SAEngine practice) |
| 256 | Holes d + 1 (M12, M14), d + 2 (M16-M24), d + 3 (M27+); e1, e2 >= 1.2 d0; spacing 2.5 d | EN 1090-2 Table 11; EN 1993-1-8 Table 3.3 | 2.5 d covers p1 >= 2.2 d0: SAEngine practice | sure |
| 257 | Plate checks of the shared connection module: φ 1.00 (A fy, Wpl fy), 0.72 (0.9 Anet fu/γM2), shear 0.9623 × 0.6 = 1/√3, 0.7698 × 0.6 = 1/(√3 γM2) | EN 1993-1-1 6.2.3, 6.2.6; EN 1993-1-8 3.10.2 | The equivalents of the EN formulas in the φ form | sure |
| 258 | γov = 1.25 | EN 1998-1 6.2(3) Note 1 | | sure |
| 259 | Section classes: DCM (q <= 4) class 1 or 2, DCH (q > 4) class 1; DCL no rule | 6.5.3 Table 6.3 | DCM 1.5 < q <= 2 would allow class 3 (not used: the systems' q are 4) | sure |
| 260 | Non-dissipative members NEd = NEd,G + 1.1 γov Ω NEd,E | 6.6.3(1) Eq 6.6, 6.7.4(1) Eq 6.12, 6.8.3(1) | G and E from each earthquake combination and its opposite sign: SAEngine practice | sure (the split: SAEngine practice) |
| 261 | MRF beams NEd/Npl,Rd <= 0.15, (VG + VM)/Vpl,Rd <= 0.5, VM = 2 Mpl,Rd/L; columns VEd/Vpl,Rd <= 0.5 | 6.6.2(2) Eqs 6.3-6.5, 6.6.3(4) | | sure |
| 262 | ΣMRc >= 1.3 ΣMRb | EN 1998-1 4.4.2.3(4) Eq 4.29 | Both directions' beams summed (on the safe side) | sure |
| 263 | X braces 1.3 < λ̄ <= 2.0; Ωmax <= 1.25 Ωmin | 6.7.3(1), (8) | Lower bound a flag (V bracing has none) | sure |
| 264 | EBF links as short: Vp,link = (fy/√3) tw (d - tf), Ω = 1.5 Vp,link/VEd | 6.8.2(3), 6.8.3(1) | The link length is not identified: SAEngine practice | unsure (method) |
| 265 | Composite: γC 1.5, γS 1.15, γa 1.0, γV 1.25 | EN 1994-1-1 2.4.1.2 | | sure |
| 266 | PRd = min(0.8 fu πd²/4, 0.29 α d² √(fck Ecm))/γV, α = 0.2(hsc/d + 1) for 3 <= hsc/d <= 4, 1 above, fu <= 500 | 6.6.3.1 Eqs 6.18-6.21 | | sure |
| 267 | kt = 0.7/√nr (b0/hp)(hsc/hp - 1) <= 0.85 (nr 1) / 0.70 (nr 2); kl = 0.6 (b0/hp)(hsc/hp - 1) <= 1 | 6.6.4.1-6.6.4.2, Table 6.2 | kt,max of through-welded studs, t <= 1 mm | unsure (kt,max row) |
| 268 | Ecm = 22 000 ((fck + 8)/10)^0.3 | EN 1992-1-1 Table 3.1 (EN 1994-1-1 3.1) | | sure |
| 269 | η >= 1 - (355/fy)(0.75 - 0.03 Le) >= 0.4 (Le <= 25 m) | EN 1994-1-1 6.6.1.2(1) Eq 6.12 | Equal flanges; Le the member's span | sure |
| 270 | Plastic moment 0.85 fcd, fyd; web compact limit 2.78 √(E/fy) (= 83ε with E 210 000) | 6.2.1.2, Table 5.2 | | sure |
| 271 | C20/25 to C60/75, fy <= 460 | 3.1(2), 3.3(2) | | sure |
| 272 | Columns: Npl,Rd = Aa fyd + 0.85 fcd Ac (1.0 filled) + As fsd; (EI)eff = Ea Ia + Es Is + 0.6 Ecm Ic; curves encased y b, z c, filled a; χ with λ̄ = √(Npl,Rk/Ncr) | 6.7.3.2-6.7.3.3, Table 6.5 | Filled: ρs <= 3 % row | sure |
| 273 | (EI)eff,II = 0.9 (Ea Ia + Es Is + 0.5 Ecm Ic); k = β/(1 - NEd/Ncr,eff), β = 0.66 + 0.44ψ >= 0.44 (1.0 for e0); e0 = L/200 (encased y), L/150 (z), L/300 (filled) | 6.7.3.4, Table 6.4, Table 6.5 | The imperfection in the plane with the larger ratio | sure |
| 274 | MEd <= αM μd Mpl,Rd, αM 0.9 (S235-S355), 0.8 (S420-S460) | 6.7.3.6(1) | | sure |
| 275 | Timber γM solid 1.3, glulam 1.25 | EN 1995-1-1 Table 2.3 | | sure |
| 276 | kmod solid / glulam: SC1, SC2 0.60 / 0.70 / 0.80 / 0.90 / 1.10; SC3 0.50 / 0.55 / 0.65 / 0.70 / 0.90 | Table 3.1 | Permanent / long / medium / short / instantaneous | sure |
| 277 | kdef SC1 0.6, SC2 0.8, SC3 2.0 | Table 3.2 | Reported only (deflection not checked) | sure |
| 278 | Load durations: G permanent, imposed medium, roof live, snow and wind short, earthquake instantaneous | Table 2.2 (examples) | Wind short-term (some National Annexes: instantaneous) | unsure (wind) |
| 279 | Service class by location: inside 1, outside 2, wet 3 | 2.3.1.3 | SAEngine practice | SAEngine practice |
| 280 | kh solid min((150/h)^0.2, 1.3), glulam min((600/h)^0.1, 1.1); kcr 0.67; km 0.7; βc 0.2 / 0.1 | 3.2(3), 3.3(3), 6.1.7(2), 6.1.6(2), 6.3.2(3) Eq 6.29 | kh on tension too | sure |
| 281 | kc by λrel = λ/π √(fc,0,k/E0,05), k = 0.5(1 + βc(λrel - 0.3) + λrel²) | 6.3.2 Eqs 6.21-6.28 | | sure |
| 282 | σm,crit = 0.78 b² E0,05/(h lef); kcrit 1 (<= 0.75), 1.56 - 0.75λrel,m (<= 1.4), 1/λ² | 6.3.3 Eqs 6.32, 6.34 | lef = the member's length (simply supported, load at the centroid): SAEngine practice | sure |
| 283 | EN 338 C14-C40 and D30-D70 values (fm, ft0, ft90, fc0, fc90, fv, E0mean, E0,05, Gmean, ρk) | EN 338:2009 Table 1 | The 2009 edition (EN 338:2016 changed ft0 and fv) | unsure (edition; each value) |
| 284 | EN 14080 GL24h-GL32h, GL24c-GL32c values | EN 14080:2013 Tables 4, 5 | | unsure (each value) |
| 285 | Masonry fk = K fb^α fm^β, α 0.7, β 0.3; K clay groups 1/2/3 0.55/0.45/0.35, concrete 0.55/0.45/0.40 | EN 1996-1-1 3.6.1.2 Eq 3.1, Table 3.3 | General purpose mortar; group by units solid 1, hollow 2: SAEngine practice | sure (grouping: SAEngine practice) |
| 286 | fb <= 75, fm <= 20 and <= 2 fb | 3.6.1.2(1) | | sure |
| 287 | γM = 2.0 | 2.4.3 Table NA (class of execution) | One of the recommended classes chosen: overridable | unsure (the class) |
| 288 | Φi = 1 - 2ei/t, ei = M/N + einit >= 0.05t, einit = hef/450; Φm of Annex G with E = 1000 fk, ek = 0.002 φ∞ (hef/tef)√(t em) above hef/tef 15, φ∞ 1.5 | 6.1.2.2, 5.5.1.1, Annex G, 3.7.2, 3.7.4 | φ∞ 1.5 of Table 3.8 (clay range 0.5-1.5) | unsure (φ∞) |
| 289 | ρ2 = 0.75 (braced top and bottom), 2.0 free top; hef/tef <= 27 | 5.5.1.2, 5.5.1.4 | | sure |
| 290 | fvk = fvk0 + 0.4 σd <= 0.065 fb; fvk0 clay 0.1/0.2/0.3, concrete 0.1/0.15/0.2 by mortar M1-M2 / M2.5-M9 / M10-M20 | 3.6.2, Table 3.4 | The mortar's strength from its grade (the parent's grade table), else 2.5 MPa | sure (values) |
| 291 | Reinforced walls MRd = As fyd z, z = d(1 - 0.5 As fyd/(b d fd)) <= 0.95 d | 6.6.2 Eqs 6.23-6.24 | The bars at mid-thickness (d = t/2): SAEngine practice | sure |
| 292 | Aluminium γM1 1.10, γM2 1.25; E 70 000, G 27 000 MPa | EN 1999-1-1 6.1.3, 3.2.5 | | sure |
| 293 | Alloys f0/fu and ρo,haz/ρu,haz: 6082 T6 (t <= 5) 250/290, 0.50/0.64; (5-15) 260/310, 0.48/0.60; 6061 T6 240/260, 0.48/0.67; 6063 T6 170/215, 0.38/0.51; 6005A T6 225/270, 0.51/0.61; 7020 T6 290/350, 0.71/0.80; 5083 O 110/270, 1/1 | Table 3.2b | Extrusions | unsure (each value) |
| 294 | Class limits β/ε internal A 11/16/22, A welded 9/13/18, B 13/16.5/18, B welded 10/13.5/15; outstand A 3/4.5/6, A welded 2.5/4/5, B 3.5/4.5/5, B welded 3/3.5/4; ε = √(250/f0) | Table 6.2 | Webs in bending β = 0.4 b/t; CHS β = 3√(D/t) | unsure (each value) |
| 295 | ρc = C1/(β/ε) - C2/(β/ε)²: internal A 32/220, A welded 29/198, B 29/198, B welded 25/150; outstand A 10/24, A welded 9/20, B 9/20, B welded 8/16 | Table 6.3 | Weff = ρc Wel: SAEngine practice | unsure (each value) |
| 296 | Flexural buckling class A α 0.20, λ̄0 0.10; class B 0.32, 0.00; LTB α 0.10, λ̄0 0.6 (class 1-2), 0.20, 0.4 (3-4) | Table 6.6, 6.3.2.2 | | unsure |
| 297 | Combined: exponents ξ 0.8 (the conservative values); section linear; shear Av f0/(√3 γM1) while hw/tw <= 39 ε | 6.3.3, 6.2.9, 6.5.5 | HAZ over the whole section of welded members (on the safe side) | unsure (exponent form) |

## Alpha 9 C12 (steel half): torsion, bracing, joints, EBF links, cold-formed, fire, deck

Rows numbered S1-S36 (their own series, so the parallel tracks do not collide).

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| S1 | steelLimitState.torsion: γ = γM0 1.0, (σ/fd)² + 3 (τ/fd)² <= 1 | EN 1993-1-1 6.2.7(5), 6.2.1(5) Eq 6.1 | Torsion by the elastic St. Venant and warping stresses (σz = 0 in members) | sure |
| S2 | Vpl,T,Rd = √(1 - τt,Ed / (1.25 fy/(√3 γM0))) Vpl,Rd (I, H); channels less τw,Ed / (fy/(√3 γM0)); hollow (1 - τt,Ed / (fy/(√3 γM0))) Vpl,Rd | EN 1993-1-1 6.2.7(9) Eqs 6.26-6.28 | Shear with torsion | sure |
| S3 | torsion.neglect 0.05 of the St. Venant resistance: rows flagged | — | SAEngine practice | SAEngine practice |
| S4 | bracing: e0 = αm L / 500, αm = √(0.5 (1 + 1/m)), q = Σ NEd 8 (e0 + δq) / L² | EN 1993-1-1 5.3.3(1) Eqs 5.12-5.13 | Equivalent stabilising force of bracing systems | sure |
| S5 | δq taken at L / 2500 | EN 1993-1-1 5.3.3(2) | The bracing deflection (the system to be checked for it): SAEngine practice | unsure (the limit's value) |
| S6 | NEd = MEd / h of beam compression flanges; αm NEd / 100 at splices | EN 1993-1-1 5.3.3(3), (4) | Beams; splices and brace points | sure |
| S7 | beff,c,wc = tfb + 2√2 ab + 5 (tfc + s), s = rc; ab = 0.707 × the weld leg | EN 1993-1-8 6.2.6.2 Eq 6.10 | Web in transverse compression (welded joint) | sure |
| S8 | ω1 = 1/√(1 + 1.3 (beff twc/Avc)²) (β = 1), ω2 = 1/√(1 + 5.2 (...)²) (β = 2) | EN 1993-1-8 Table 6.3 | Shear interaction of the web; β = 2 for beams on both flanges (SAEngine: the sway case) | sure |
| S9 | kwc = 1 for σcom,Ed <= 0.7 fy, else 1.7 - σ/fy; λp = 0.932 √(beff dwc fy / (E twc²)), ρ = 1 (λp <= 0.72) else (λp - 0.2)/λp² | EN 1993-1-8 6.2.6.2(2), Eqs 6.13-6.14 | Web buckling under transverse compression | sure |
| S10 | Ft,wc,Rd = ω beff,t,wc twc fy / γM0 | EN 1993-1-8 6.2.6.3 Eq 6.15 | Web in transverse tension | sure |
| S11 | beff = twc + 2 s + 7 k tfc, k = (tfc/tp)(fy,c/fy,p) <= 1 | EN 1993-1-8 4.10 Eqs 4.6-4.7 | Unstiffened column flange of a welded joint (the plate's fy taken as the column's) | sure |
| S12 | Avc = A - 2 b tf + (tw + 2 r) tf; Vwp,Rd = 0.9 fy Avc / (√3 γM0); a supplementary web plate adds bs twc | EN 1993-1-8 6.2.6.1 Eq 6.7, (6); EN 1993-1-1 6.2.6(3) | Column web panel in shear | sure |
| S13 | CHS T/Y γ^0.2 kp fy0 t0² (2.8 + 14.2 β²) / sinθ1; X kp fy0 t0² 5.2 / ((1 - 0.81 β) sinθ1); K kg kp fy0 t0² (1.8 + 10.2 d1/d0) / sinθ1; all / γM5 | EN 1993-1-8 Table 7.2 | Chord face failure | sure |
| S14 | kp = 1 - 0.3 np (1 + np) <= 1 (np > 0), kg = γ^0.2 (1 + 0.024 γ^1.2 / (1 + exp(0.5 g/t0 - 1.33))) | EN 1993-1-8 7.4.2(2) | Chord stress and gap factors (np read as the joint's chord utilisation: SAEngine practice) | sure (the 2005 form) |
| S15 | Punching fy0 t0 π di (1 + sinθ) / (2 √3 sin²θ γM5) when di <= d0 - 2 t0 | EN 1993-1-8 Table 7.2 | CHS punching shear | sure |
| S16 | RHS (β <= 0.85) kn fy0 t0² (2η/sinθ + 4√(1 - β)) / ((1 - β) sinθ γM5); kn = 1.3 - 0.4 n/β <= 1 (n > 0) | EN 1993-1-8 Table 7.10 | Chord face failure of T, Y, X joints | sure |
| S17 | Brace failure fyi ti (2hi - 4ti + 2beff) / γM5, beff = 10/(b0/t0) fy0 t0/(fyi ti) bi <= bi; punching fy0 t0 (2hi/sinθ + 2be,p) / (√3 sinθ γM5), be,p = 10/(b0/t0) bi (0.85 <= β <= 1 - 1/γ) | EN 1993-1-8 Table 7.10 | RHS β > 0.85 | sure |
| S18 | K with gap 8.9 kn fy0 t0² √γ (b1 + b2 + h1 + h2) / (4 b0 sinθ γM5); brace fyi ti (2hi - 4ti + bi + beff) / γM5 | EN 1993-1-8 Table 7.12 | RHS K joints | check (the brace failure term) |
| S19 | Validity: CHS 0.2 <= di/d0 <= 1.0, 10 <= d0/t0 <= 50 (X: 40), di/ti <= 50; RHS b0/t0, h0/t0 <= 35, bi/ti <= 35, bi/b0 >= 0.25 (K: 0.35 and 0.1 + 0.01 b0/t0), g >= t1 + t2; γM5 = 1.0 | EN 1993-1-8 7.1.2, Tables 7.1, 7.8; 2.2 Table 2.1 | Limits of the joint rules | check (each limit) |
| S20 | Links: Vp,link = (fy/√3) tw (d - tf), Mp,link = fy b tf (d - tf) | EN 1998-1 6.8.2(3) Eqs 6.13-6.14 (numbering to check) | Link resistances | sure (formulas) / unsure (equation numbers) |
| S21 | short e < 1.6 Mp,link/Vp,link, long e > 3.0 Mp,link/Vp,link | EN 1998-1 6.8.2(8)-(9) | Link classes | sure |
| S22 | θp <= 0.08 rad (short), 0.02 rad (long), linear between | EN 1998-1 6.8.2(10) | Link rotation (θp from the drift limit: SAEngine practice, the whole drift as plastic) | sure (values) |
| S23 | NEd/Npl,Rd > 0.15: Vp,link,r = Vp,link √(1 - (NEd/Npl)²), Mp,link,r = Mp,link (1 - NEd/Npl); R = NEd tw (d - 2tf)/(VEd A): e <= 1.6 Mp/Vp (R < 0.3), (1.15 - 0.5 R) 1.6 Mp/Vp (R >= 0.3) | EN 1998-1 6.8.2(5)-(7) Eqs 6.15-6.20 | Links with axial force | check |
| S24 | Ωi = 1.5 Vp,link,i / VEd,i (short), 1.5 Mp,link,i / MEd,i (intermediate, long); Ωmax <= 1.25 Ωmin | EN 1998-1 6.8.3(1), 6.8.2(7) | Overstrength of the links | check (the homogeneity clause) |
| S25 | Composite deck: hp <= 85 mm, stud d <= 20 mm through the deck, studs 2d = 40 mm above the deck, hc >= 50 mm | EN 1994-1-1 6.6.4.1(1), 6.6.4.2, 6.6.5.8(1), 9.2.1(2) | The deck rules (the other deck values stay the parent's) | check (d 19 / 20 mm; 2d read at d = 20) |
| S26 | coldFormed: E 210 000, G 81 000 MPa | EN 1993-1-3 3.2.6 (EN 1993-1-1 3.2.6) | Moduli | sure |
| S27 | Internal ρ = (λp - 0.055 (3 + ψ))/λp² above 0.5 + √(0.085 - 0.055 ψ), outstand ρ = (λp - 0.188)/λp² above 0.748, λp = (b/t)/(28.4 ε √kσ), kσ 4 / 0.43 / 23.9 (ψ = -1) | EN 1993-1-5 4.4 Tables 4.1, 4.2 (via EN 1993-1-3 5.5.2) | Effective widths (at fy) | sure |
| S28 | χd = 1 (λd <= 0.65), 1.47 - 0.723 λd (< 1.38), 0.66/λd; σcr,s = 2√(K E Is)/As; K = E t³/(4(1 - ν²)) / (b1² hw + b1³ + 0.5 b1 b2 hw kf) | EN 1993-1-3 5.5.3.1(7) Eq 5.12, 5.5.3.2 Eqs 5.10b, 5.15 | Distortional buckling of the edge stiffener (the stiffener taken as the lip and half the flange: SAEngine practice; As reduced by χd, no iteration) | check |
| S29 | γM0 = γM1 = 1.0; buckling curve b (α 0.34) for lipped C and Z, χLT curve b | EN 1993-1-3 2(3), Table 6.3, 6.2.4 | Member resistances | sure |
| S30 | (NEd/Nb,Rd)^0.8 + (MEd/Mb,Rd)^0.8 <= 1 | EN 1993-1-3 6.3 Eq 6.36 | Combined compression and bending | sure |
| S31 | fbv = 0.58 fyb (λ̄w <= 0.83), 0.48 fyb/λ̄w (< 1.40), 0.67 fyb/λ̄w²; λ̄w = 0.346 (sw/t)√(fyb/E) | EN 1993-1-3 6.1.5 Table 6.1, Eq 6.10a | Shear buckling (no stiffening at the support) | sure |
| S32 | b/t <= 60, c/t <= 50, h/t <= 500; t <= 15 mm | EN 1993-1-3 5.2 Table 5.1; 1.1(3) | Limits | check (the thickness range) |
| S33 | steelFire.retention: ky,θ / kE,θ at 20-1200 °C: 1/1, 1/1, 1/0.9, 1/0.8, 1/0.7, 0.78/0.6, 0.47/0.31, 0.23/0.13, 0.11/0.09, 0.06/0.0675, 0.04/0.045, 0.02/0.0225, 0/0 | EN 1993-1-2 3.2.1 Table 3.1 | Reduction factors (linear between) | sure |
| S34 | θa,cr = 39.19 ln(1/(0.9674 μ0^3.833) - 1) + 482; ηfi = 0.65 | EN 1993-1-2 4.2.4 Eq 4.22; 2.4.2(3) | Critical temperature; the load ratio (μ0 = ηfi × the ambient utilisation, γM,fi = γM: SAEngine reading) | sure |
| S35 | Nb,fi,t,Rd = χfi A ky,θ fy / γM,fi, λ̄θ = λ̄ √(ky,θ/kE,θ), α = 0.65 √(235/fy), γM,fi = 1.0 | EN 1993-1-2 4.2.3.2 Eqs 4.5-4.7, 2.3 | Compression members in fire | sure |
| S36 | Heating: Δθa = ksh (Am/V) hnet Δt / (ca ρa), ksh = 0.9 [Am/V]b/[Am/V] (I-sections), αc 25 W/m²K, εm 0.7, εf 1.0, ca 600 J/kgK, ρa 7850 kg/m³; protected Eq 4.27 with φ = cp ρp dp (Ap/V)/(ca ρa); θg = 20 + 345 log10(8t + 1) | EN 1993-1-2 4.2.5.1 Eqs 4.25-4.26a, 4.2.5.2 Eq 4.27, 2.2(2), 3.4.1.2(2); EN 1991-1-2 3.2.1 Eq 3.4, 3.1(6) | Steel temperature (the protection is a project value, default none) | sure |

## EN 1998-1 Annex B and EN 1998-3 (pushover.json, alpha 9 track P3)

| # | Value | Clause | Description | Confidence |
| --- | --- | --- | --- | --- |
| N1 | Push to 150 % of the target displacement; no no-drop rule | EN 1998-1 4.3.3.4.2.3(2) | Two patterns (modal, uniform) are required; SAEngine runs the chosen one | sure |
| N2 | Γ = Σmφ/Σmφ², m* = Σmφ, F* = Fb/Γ, d* = dn/Γ (φ = 1 at the roof) | Annex B.2, B.3, Eqs B.1-B.3 | | sure |
| N3 | Fy* the force at the plastic mechanism (the largest force up to dm*), dy* = 2(dm* − Em*/Fy*) | Annex B.3, Eq B.6 | | sure |
| N4 | T* = 2π √(m* dy*/Fy*) | Annex B.4, Eq B.7 | | sure |
| N5 | det* = Se(T*)(T*/2π)²; T* ≥ TC: dt* = det*; T* < TC and Fy*/m* < Se: dt* = det*/qu (1 + (qu − 1) TC/T*) ≥ det*, qu = Se m*/Fy* | Annex B.5, Eqs B.8-B.12 | | sure |
| N6 | dt* ≤ 3 det* | Annex B.5 Note | | unsure |
| N7 | Iteration with dm* = dt* (optional) | Annex B.6 | SAEngine iterates until it settles | sure |
| N8 | Limit states SD (design action, 475 years, main), NC (2475 years, spectrum × 1.73), DL (225 years, × 0.78) | EN 1998-3 2.1(3); scale (TLR/TL)^(1/3) by EN 1998-1 2.1(4) Note, k = 3 | The scales are SAEngine practice where the National Annex gives no spectra | unsure |
| N9 | θum = (1/γel) 0.016 (0.3^ν) [max(0.01, ω')/max(0.01, ω) fc]^0.225 (LV/h)^0.35 25^(α ρsx fyw/fc) 1.25^(100 ρd), γel = 1.5 (primary) | EN 1998-3 A.3.2.2(1), Eq A.1 | ρ over b·h; ρd = 0; members with seismic detailing; no laps in the hinge | sure |
| N10 | Walls: θum × 0.58 | EN 1998-3 A.3.2.2(1) | | unsure |
| N11 | α = (1 − sh/2bo)(1 − sh/2ho)(1 − Σbi²/6hobo); every bar held by a tie corner or cross-tie | EN 1998-3 A.3.2.2(1) | The held bars are SAEngine practice | sure |
| N12 | SD = 3/4 θum, NC = θum, DL = θy (the chord rotation at the first yield of the tension bars in the analysis) | EN 1998-3 A.3.2.3, A.3.2.4 | θy from the analysis instead of Eq A.10: SAEngine practice | sure |
| N13 | Steel beams and columns (× θy): class 1 DL 1.0 SD 6.0 NC 8.0; class 2 DL 0.25 SD 2.0 NC 3.0; columns only up to N/Npl = 0.3 | EN 1998-3 B.5.2 | | unsure |
| N14 | Braces (× ΔT, Δc): tension DL 0.25 SD 7 NC 9; compression DL 0.25 SD 4 NC 6 | EN 1998-3 B.5.3 | | unsure |
| N15 | Class 1 / 2 by EN 1993-1-1 Table 5.2: flange c/tf 9ε / 10ε, web 72ε / 83ε, as √(E/fy) multiples 0.301 / 0.334 and 2.41 / 2.78 (E = 210 GPa) | EN 1993-1-1 Table 5.2 | Flange c taken as bf/2 | sure |

## EN ISO 3766:2003 bar schedules (alpha 9 C14)

`barSchedule.standard` = `iso3766`. EN ISO 3766 gives the shape codes and how they are
dimensioned (outside dimensions); it gives no cutting-length formulas, so SAEngine computes the
length along the bar's centre line (SAEngine practice), with the mandrel diameters of EN
1992-1-1 8.3 (`concreteMethods.barShapes`). A UK National Annex pack sets `standard` back to
`bs8666` (inherited from the default pack).

| # | Path | Value | Clause | What | Confidence |
|---|---|---|---|---|---|
| BI1 | barSchedule.standards.iso3766.shapes (codes) | 00, 11, 12, 13, 21, 23, 26, 31, 41, 51, 77, 99 and their dimension letters | EN ISO 3766:2003 shape code table | Shape codes and letters | Uncertain (the codes are taken as BS 8666 numbers them; check each code's meaning, and whether 51 is the closed link with 135° hooks) |
| BI2 | barSchedule.standards.iso3766.shapes.11 / 21 / 31 / 41 | sum of A.. less n [2(r + d) - π/2 (r + d/2)] for n 90° bends | geometry (SAEngine practice) | Centre-line length | Sure (geometry) |
| BI3 | barSchedule.standards.iso3766.shapes.13 | A + C - B + π (B - d)/2 | geometry (SAEngine practice) | 180° bend of outside width B | Check (that B is the bend's outside width) |
| BI4 | barSchedule.standards.iso3766.shapes.51 | 2(A + B) + 2C - 10(r + d) + 3π (r + d/2) | geometry (SAEngine practice) | Closed link, C = ext + r + d | Check |
| BI5 | barSchedule.standards.iso3766.shapes.77 | C √((π(A - d))² + B²) | geometry | Helix of C turns, pitch B | Sure (geometry) |
| BI6 | barSchedule.standards.iso3766.shapes.26 | A + B + C | SAEngine practice | Crank, kinks neglected | Check |
| BI7 | barSchedule.standards.iso3766.roundTo | 25 mm, up | SAEngine practice (not in the standard) | Rounding | Practice |

## Alpha 9 P7: floor vibration, wind comfort, embedded walls

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| P7E1 | floorVibration.steelMethod / concreteMethod | responseFactor (SCI P354 / CCIP-016); values as bnbc2020 FV9-FV17 | SCI P354, CCIP-016, ISO 10137 | Check |
| P7E2 | windComfort.response | EN 1991-1-4 Annex B.4 Eqs B.10-B.11 (Kx, me = m1 (2ξ+1)/h) | EN 1991-1-4 | Check |
| P7E3 | windComfort.probabilityTerms | K 0.2, n 0.5, p = 1 - exp(-1/T) | EN 1991-1-4 4.2(2) Note 4 | Sure (p for T = 1: SAEngine practice) |
| P7E4 | windComfort.duration, peakConstant | 600 s, 0.6 | EN 1991-1-4 Eq B.4 | Sure |
| P7E5 | windComfort.limits | 15 / 18 / 25 milli-g | SAEngine practice (EN 1990 A1.4.4 leaves them to the project) | Practice |
| P7E6 | embeddedWalls.materials, variableFactor | M2, 1.3 | EN 1997-1 Annex A (DA1 C2) | Sure |
| P7E7 | embeddedWalls.embedmentIncrease | 1.2 | Blum, SAEngine practice | Practice |

## Alpha 9 P1: excavation support

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| P1E1 | excavationSupport.analyses | DA1 C1: characteristic, effects × 1.35; C2: M2 strengths, × 1.0 | EN 1997-1 2.4.7.3.4.2, Annex A | Sure |
| P1E2 | excavationSupport.anchors.tendonFactor | 1.5525 = 1.35 × 1.15 | EN 1997-1 8.5 with γs 1.15 of EN 1992-1-1 | Check |
| P1E3 | excavationSupport.anchors.groundFactor | 1.485 = 1.35 × 1.1 (γa of Table A.12) | EN 1997-1 8.5, Annex A | Check |
| P1E4 | excavationSupport.anchors.proofFactor | 1.25 × working (temporary and permanent) | EN 1537 / EN ISO 22477-5 acceptance test | Unsure |
| P1E5 | excavationSupport.heave.pipingFactor | 1.5 = γG,dst 1.35 / γG,stb 0.9 | EN 1997-1 2.4.7.5 (HYD) | Check |
| P1E6 | excavationSupport (rest) | as bnbc2020 ES1-ES31 | SAEngine practice | see bnbc2020 |

## Alpha 9 P2: creep, shrinkage and column shortening (concreteTime)

| # | Path | Value | Clause | Confidence |
| --- | --- | --- | --- | --- |
| P2E1 | concreteTime.creep (method en1992AnnexB) | φ = φ0 βc(t, t0), φ0 = φRH β(fcm) β(t0); φRH with α1, α2 above fcm 35 MPa; β(fcm) = 16.8/√fcm; β(t0) = 1/(0.1 + t0^0.2); βc = ((t - t0)/(βH + t - t0))^0.3; βH = 1.5(1 + (0.012 RH)^18) h0 + 250 α3 ≤ 1500 α3 | EN 1992-1-1 Annex B Eqs B.1-B.8 | sure |
| P2E2 | concreteTime.creep.cementExponent | α = -1 (S), 0 (N), 1 (R) in t0 = t0,T (9/(2 + t0,T^1.2) + 1)^α ≥ 0.5 | Annex B Eq B.9 | sure |
| P2E3 | concreteTime.creep.tangentFactor | Ec = 1.05 Ecm | Sec 3.1.4(2) | sure |
| P2E4 | concreteTime.creep.fcmMargin, shrinkage.fcmMargin | fcm = fck + 8 MPa | Table 3.1 | sure |
| P2E5 | concreteTime.shrinkage.alphaDs1, alphaDs2 | 3/4/6 and 0.13/0.12/0.11 (S/N/R) | Annex B Eq B.11 | sure |
| P2E6 | concreteTime.shrinkage (εcd,0) | 0.85 ((220 + 110 αds1) exp(-αds2 fcm/10)) 10⁻⁶ βRH, βRH = 1.55 (1 - (RH/100)³) | Annex B Eqs B.11-B.12 | sure |
| P2E7 | concreteTime.shrinkage.kh | 1.0, 0.85, 0.75, 0.70 at h0 100, 200, 300, ≥ 500 mm | Table 3.3 | sure |
| P2E8 | concreteTime.shrinkage (βds, εca) | βds = (t - ts)/((t - ts) + 0.04 √h0³); εca(∞) = 2.5 (fck - 10) 10⁻⁶, βas = 1 - exp(-0.2 √t) | Eqs 3.10-3.13 | sure |
| P2E9 | concreteTime.strengthGain.s | s = 0.25 (class N) | Sec 3.1.2(6) Eq 3.2 | sure |
| P2E10 | concreteTime.exposure | inside 50 %, outside 80 % | Figure 3.1 | sure |
| P2E11 | concreteTime.ageing.chi | χ = 0.8 | not in EN 1992-1-1 | SAEngine practice |
| P2E12 | combinations.creepShrinkage | 1.35G + 1.0CS + 1.5Q + 0.75S | EN 1992-1-1 2.4.2.1(1) γSH = 1.0, with EN 1990 Eq 6.10 | unsure (1.0 on the creep part too is SAEngine practice) |
| P2E13 | concreteTime.creep.cementClass, shrinkage.cementClass | N by default | SAEngine practice | practice |

## Alpha 9 P5: time histories and non-linear time-history analysis (seismic.timeHistory, nonlinearHistory)

| # | Key | Value | Clause | Confidence |
|---|---|---|---|---|
| P5E1 | seismic.timeHistory.minimumRecords | 3 accelerograms | EN 1998-1 Sec 3.2.3.1.2(4) | Sure |
| P5E2 | seismic.timeHistory.periodLower, periodUpper | 0.2 T1 to 2 T1 | EN 1998-1 Sec 3.2.3.1.2(4)c | Sure |
| P5E3 | seismic.timeHistory.singleRatio, pairRatio | 90 % of the elastic spectrum | EN 1998-1 Sec 3.2.3.1.2(4)c | Sure |
| P5E4 | seismic.timeHistory.pairCombination | each component's mean meets the criterion | EN 1998-1 Sec 3.2.3.1.1, 4.3.3.5.1 | Check |
| P5E5 | seismic.timeHistory.meanFrom | 7 (fewer: the most unfavourable) | EN 1998-1 Sec 4.3.3.4.3(3) | Sure |
| P5E6 | seismic.timeHistory.targets.nonlinear | the elastic response spectrum, q = 1, ag = γI agR | EN 1998-1 Sec 3.2.2.2 (Eqs 3.2-3.5), 3.2.3.1.2 | Sure |
| P5E7 | zero-period condition (mean PGA ≥ ag S) | not checked | EN 1998-1 Sec 3.2.3.1.2(4)b | Not built |
| P5E8 | seismic.timeHistory.baseShearShare (linear) | 1.0 × the lateral force base shear | none in EN 1998-1 | SAEngine practice |
| P5E9 | seismic.timeHistory.matching | frequency domain, 0.8 × lower to 1.25 × upper bound, 10 %, 20 iterations | EN 1998-1 Sec 3.2.3.1.2 (artificial accelerograms) | SAEngine practice |
| P5E10 | nonlinearHistory.drift.limitFactor | 1.0 × the allowable α/ν of Sec 4.4.3.2 | EN 1998-1 Sec 4.4.3.2 | Check |
| P5E11 | nonlinearHistory.acceptance | EN 1998-3 chord rotation hinges at Significant Damage | none in EN 1998-1 for new buildings | SAEngine practice |
| P5E12 | nonlinearHistory.procedure.damping | each record's ratio on the first mode, committed stiffness | none | SAEngine practice |

## Alpha 9 P6: base isolation (isolation, EN 1998-1 Section 10, EN 15129)

| # | Key | Value | Clause | Confidence |
|---|---|---|---|---|
| P6E1 | isolation.procedure.method | singleLevel at the design seismic action | EN 1998-1 Sec 10.6, 10.9 | Sure |
| P6E2 | isolation.procedure.displacementFactor | γx = 1.2 on the devices' displacements | EN 1998-1 Sec 10.3(2)P | Sure (recommended value) |
| P6E3 | isolation.dampingFormula | η = √(10/(5 + ξ)) ≥ 0.55, B = 1/η | EN 1998-1 Eq 3.6 | Sure |
| P6E4 | d_dc, Teff | M Se(Teff, ξeff) / Keff, Teff = 2π √(M/Keff) | EN 1998-1 Sec 10.9.3 | Sure |
| P6E5 | isolation.forces reduction | q of the superstructure ≤ 1.5 | EN 1998-1 Sec 10.10(5) | Sure |
| P6E6 | isolation.distribution.exponent | 0 (f_j = m_j Se: a uniform acceleration), shearExponent 0 | EN 1998-1 Sec 10.9.4 | Check |
| P6E7 | isolation.torsion | rigidDeck: δi = 1 + (e_tot / r²) yi | EN 1998-1 Sec 10.9.3(6) | Check |
| P6E8 | isolation.staticLimits | Teff ≤ 3 s and ≥ 3 Tf, plan ≤ 50 m, Kv/Keff ≥ 150, ξeff ≤ 30 % | EN 1998-1 Sec 10.9.3 | Unsure (which conditions; Tv ≤ 0.1 s and the fault distance not checked) |
| P6E9 | isolation.spectrumAnalysis | ξ ≤ 30 %, 30 % of the orthogonal direction | EN 1998-1 Sec 10.9.5, 4.3.3.5.1 | Check |
| P6E10 | isolation.history | 3 records (the largest), 7 (the mean), 0.2 to 2 Teff, 90 % | EN 1998-1 Sec 3.2.3.1, 4.3.3.4.3 | Unsure (the period range for isolated buildings) |
| P6E11 | isolation.drift | 0.010 h (0.005 h / ν, ν = 0.5) | EN 1998-1 Sec 4.4.3.2 | SAEngine practice |
| P6E12 | isolation.spectrum.importance | 1.0 (γI not applied by the isolation design) | EN 1998-1 Sec 10.6 | Unsure (should take γI of the class) |
| P6E13 | isolation.restoring | none (not checked) | EN 1998-1 Sec 10.5.3 | Check (the lateral restoring capability rule) |
| P6E14 | isolation.procedure.minima | the factored wind only | none | SAEngine practice |
| P6E15 | isolation.propertyModification.aeShare | 1.0 (the plain product) | EN 15129 | Unsure (EN 15129's combination of the λ factors) |
| P6E16 | isolation.testing | a generic cyclic sequence | EN 15129 Sec 8.2, 9.2 | SAEngine practice (EN 15129's type tests govern) |
| P6E17 | isolation.overturning.minimumFactor | 1.0 | none | SAEngine practice |
| P6E18 | dampers | not covered: EN 1998-1 has no procedure for structures with damping systems | — | — |

## Alpha 9 P4: assessment and retrofit of existing buildings (existing)

| # | Key | Value | Clause | Confidence |
|---|---|---|---|---|
| P4E1 | existing.knowledge[].confidenceFactor | CF 1.35 (KL1), 1.20 (KL2), 1.00 (KL3) | EN 1998-3 Table 3.1 (recommended) | Sure |
| P4E2 | existing.knowledge[KL1].procedures | lateral force or modal response spectrum only | EN 1998-3 Table 3.1 | Sure |
| P4E3 | existing.strengths | analysis: mean; ductile capacities: mean/CF; brittle: mean/CF/γM (γc 1.5, γs 1.15) | EN 1998-3 Sec 3.5, Table 4.3, EN 1992-1-1 Table 2.1N | Check (γM of the persistent situation) |
| P4E4 | existing.linear.hazards | SD 475 years (scale 1.0), NC 2475 years (1.73), DL 225 years (0.78) | EN 1998-3 Sec 2.1 Notes; EN 1998-1 Sec 2.1(4) Note, k = 3 | SAEngine practice for the scales |
| P4E5 | existing.linear.liveShare | ψ2 = 0.3 | EN 1990 Table A1.1 (category B) | Check (by use) |
| P4E6 | existing.linear.chordRotation | γel 1.5, 0.016, 0.3^ν, ωmin 0.01, 0.225, 0.35, 25^(αρsx fyw/fc), 1.25^(100ρd), walls × 0.58; SD 3/4 θum, NC θum, DL θy | EN 1998-3 Eq A.1, A.3.2.2-A.3.2.4 | Sure |
| P4E7 | existing.linear.yieldRotation | θy = φy LV/3 + 0.0013 (1 + 1.5 h/LV) + 0.13 φy db fy/√fc (the av z term left out) | EN 1998-3 Eq A.10a | Check |
| P4E8 | existing.linear.yieldRotation.curvature | φy = 2.1 εy/h | Priestley's rectangular-section value | SAEngine practice |
| P4E9 | chord rotation demand | θ = (M/My) θy, My at first yield (or 1.8 fc/Ec) with the analysis strengths, LV = L/2 | EN 1998-3 A.3.2.4 (secant stiffness to yield) | SAEngine practice (LV) |
| P4E10 | existing.shear (cyclicDegradation) | 1/γel [(h - x)/(2LV) min(N, 0.55 Ac fc) + (1 - 0.05 min(5, μpl)) (0.16 max(0.5, 100ρtot)(1 - 0.16 min(5, LV/h)) √fc Ac + Vw)], γel 1.15 | EN 1998-3 Eq A.12 | Sure |
| P4E11 | existing.jacketing | My × 1.0, θy × 1.05, θum × 1.0, VR × 0.9 | EN 1998-3 A.4.2.2 | Check |
| P4E12 | existing.frp.shear | full wraps εfe = 0.004 ≤ 0.5 εfu; Vf = 0.9 d Ef εfe 2 n tf (wf/sf), θ = 45° | EN 1998-3 A.4.4.2 | Unsure (the effective stress of A.4.4.2 is simplified) |
| P4E13 | existing.frp.confinement.rotationFactor | θum's confinement exponent + α ρf ff,e/fc, α = 1.0, ff,e = Ef × 0.5 εfu | EN 1998-3 A.4.4.3 | Unsure |
| P4E14 | existing.frp.environment | 1.0 (EN 1998-3 gives none) | none | SAEngine practice |
| P4E15 | existing.nonlinear | θum with fc and fy over CF (× CF^-0.225 × 0.3^(ν (CF - 1))), shear by Eq A.12 at the target | EN 1998-3 Sec 3.5, A.3.2.2, A.3.3.1 | Check |

## Nonlinear stability (`nonlinearStability`) and the FE check of joints (`connectionFe`), alpha 9 L4 / L6

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L4E1 | bow.ratios | L/e0 = 350, 300, 250, 200, 150 for curves a0, a, b, c, d (elastic analysis) | EN 1993-1-1 Table 5.1 | Sure |
| L4E2 | bow.plasticRatios | L/e0 = 300, 250, 200, 150, 100 (plastic analysis) | EN 1993-1-1 Table 5.1 | Sure |
| L4E3 | sway | φ0 = 1/200, αh = 2/√h with 2/3 ≤ αh ≤ 1, αm = √(0.5 (1 + 1/m)) | EN 1993-1-1 5.3.2(3) Eq 5.5 | Sure |
| L4E4 | eigenmode | the first mode scaled so that its most bowed member gets e0 of Table 5.1 | EN 1993-1-1 5.3.2(11) (Eq 5.11 simplified) | Check (simplified amplitude) |
| L4E5 | plates.panelRatio | panel imperfection min(a, b) / 200 | EN 1993-1-5 Annex C Table C.2 | Check |
| L4E6 | plates.dimple | U0,max = 0.006 / 0.010 / 0.016 for fabrication classes A / B / C | EN 1993-1-6 Table 8.4 | Check |
| L4E7 | yieldFactor, stiffnessFactor | 1.0 and 1.0 (γM1 = 1.0 recommended) | EN 1993-1-5 C.9, EN 1993-1-1 6.1 | Check |
| L4E8 | hardeningRatio | E/10000 nominal plateau slope | EN 1993-1-5 C.6(2) Fig C.2 (b) | Unsure (figure from memory) |
| L4E9 | cables.breakingShare | FRd = Fuk / (1.5 γR), γR = 0.90: 0.741 | EN 1993-1-11 6.2(2) and Table 6.2 | Unsure (γR by the socket kind) |
| L6E1 | plasticStrainLimit | 5 % principal (equivalent) plastic strain | EN 1993-1-5 Annex C C.8 Note 1 | Sure |
| L6E2 | yieldFactor | fy / γM0, γM0 = 1.0 | EN 1993-1-1 6.1 | Sure |
| L6E3 | hardeningRatio | E/1000 | SAEngine practice (C.6 allows a hardening slope) | Practice |
| L6E4 | boltStiffness | k10 = 1.6 As/Lb, k11 = 16 nb d² fub / (E dM16) | EN 1993-1-8 Table 6.11 | Check |
| L6E5 | classification | pinned ≤ 0.5 E Ib/Lb; rigid ≥ 8 (braced) or 25 (unbraced) E Ib/Lb | EN 1993-1-8 5.2.2.5 | Sure |
| L6E6 | elementSize, elementsAcross, loadSteps | 10 mm, 8 across, 10 steps | SAEngine practice | Practice |

## Precast pieces (`precast`; alpha 9 L1; EN 1992-1-1 Section 10)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L1E1 | bearing.method | netBearing: a = a1 + a2 + a3 + √(Δa2² + Δa3²), a1 = FEd/(b1 fRd) | EN 1992-1-1 10.9.5.2(1), Eq 10.6 | Sure |
| L1E2 | bearing.strength | fRd = 0.4 fcd dry, 0.85 fcd bedded | EN 1992-1-1 10.9.5.2(2) | Sure |
| L1E3 | bearing.stressBands | σEd/fcd ≤ 0.15, 0.15-0.4, > 0.4 | EN 1992-1-1 Tables 10.2-10.3 | Sure |
| L1E4 | bearing.a1Minimum | linear 25/30/40, ribbed 55/70/80, concentrated 90/110/140 mm | EN 1992-1-1 Table 10.2 | Check |
| L1E5 | bearing.a2 | steel 0/0/10 (linear), 5/10/15 (concentrated); RC ≥ C30 5/10/15, 10/15/25; plain or RC < C30 10/15/25, 20/25/35; masonry as the last | EN 1992-1-1 Table 10.3 | Unsure (masonry's > 0.4 column is "–" in the code; taken as concrete < C30) |
| L1E6 | bearing.highStrength | C30 | Table 10.3 | Sure |
| L1E7 | bearing.a3 | continuous 0/0; straight bars or horizontal loops 5/15 (at least the end cover); exposed tendons or bars 5/15; vertical loops 15/15 | EN 1992-1-1 Table 10.4 | Check (vertical loops, concentrated: the code gives end cover + inner bend radius; 15 mm taken) |
| L1E8 | bearing.supportTolerance | steel or precast 10 ≤ l/1200 ≤ 30 mm; masonry or cast in situ 15 ≤ l/1200 + 5 ≤ 40 mm | EN 1992-1-1 Table 10.5 | Check |
| L1E9 | bearing.memberTolerance | Δa3 = ln/2500 | EN 1992-1-1 10.9.5.2(1) | Check |
| L1E10 | dowel | dowelAction: α0 1.0, ε = 3 √(fcd/fyd), γRd 1.3, γc 1.5, γs 1.15, cap fyd/√3 As | fib Bulletin 43 (2008) Ch 5 (Rasmussen dowel action) | Unsure (α0 and γRd as recalled) |
| L1E11 | connections.tensionShare | 0.2 FEd where none is entered | none in EN 1992-1-1 10.9.4 | SAEngine practice |
| L1E12 | handling.tension | 0.7 × 0.30 f'ci^(2/3) / 1.5 (fctk,0.05 / γc) | EN 1992-1-1 Table 3.1, 2.4.2.4 | Check |
| L1E13 | handling.insertSafety | 2.5 | CEN/TR 15728 (order of its factors) | Unsure |
| L1E14 | handling (multipliers), erection | as the default pack's L1B11-L1B19 | PCI Design Handbook 8th ed.; Mast | SAEngine practice |
| L1E15 | integrity | not given: EN 1992-1-1 9.10 tying systems are the concreteMethods ties | none | Not covered here |

## Floor response spectra (`floorSpectra`; alpha 9 L5)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L5-1 | methods | timeHistory, spectrumToSpectrum (time history first when the run has one) | none in the code | SAEngine practice |
| L5-2 | broadening | ±15 % of the period | ASCE 4-16 Sec 6.2 / US NRC RG 1.122 practice | Check |
| L5-3 | damping | 2, 3, 5, 7 % computed; 5 % for the components | none | SAEngine practice |
| L5-4 | periods | 0.02-4 s, 120 on a log scale | none | SAEngine practice |
| L5-5 | direct.duration / iterations | 20 s strong motion (Davenport peak factor), 8 iterations of the density | none | SAEngine practice |
| L5-6 | components | F = Sa(Tc) Wc Ic / Rc within the nonstructural table's least and largest force; rigid (αc ≤ 1) at 0.06 s, flexible at the peak | the form of ASCE 7-16 Eq 13.3-4 / EN 1998-1 Eq 4.24 with the floor spectrum | SAEngine practice (off unless the project turns it on) |
## Alpha 9 P8: composite slabs on steel deck (compositeSlab), the slab's longitudinal shear and the camber of composite beams (composite.beam), composite floors' vibration (floorVibration)

| # | Key | Value | Clause | Confidence |
|---|---|---|---|---|
| P8E1 | compositeSlab.gammaC, gammaAp, gammaVs | 1.5, 1.0 (γM0 of the sheeting), 1.25 | EN 1994-1-1 2.4.1.2; EN 1993-1-3 2(3) | Sure (γVs: check the recommended value) |
| P8E2 | compositeSlab.gammaG, gammaQ | 1.35, 1.5 (construction stage) | EN 1990 Table A1.2(B) | Sure |
| P8E3 | compositeSlab.concreteShare | 0.85 fcd in the plastic block | EN 1994-1-1 9.7.2(5) | Sure |
| P8E4 | compositeSlab.plasticReduction | Mpr = 1.25 Mpa (1 - Ncf / (Ape fyp,d)) <= Mpa | EN 1994-1-1 9.7.2(6), Eq 9.6 | Sure |
| P8E5 | compositeSlab.shearSpanShare | Ls = L/4 for a uniform load | EN 1994-1-1 9.7.3(5) | Sure |
| P8E6 | compositeSlab.longitudinalShear | m-k (Eq 9.7) and the partial connection method (τu,Rd = τu,Rk / γVs) | EN 1994-1-1 9.7.3(4)-(8) | Sure; the end anchorage and the overhang L0 of 9.7.3(9)-(10) are not counted (safe side) |
| P8E7 | compositeSlab.wetIncrement | fresh concrete + 1 kN/m³ | EN 1991-1-1 Table A.1 (note on unhardened concrete) | Check |
| P8E8 | compositeSlab.constructionLoad | 10 % of the concrete's weight within 0.75-1.5 kN/m² over a 3 m working area, 0.75 kN/m² outside | EN 1991-1-6 4.11.1, Table 4.1 (recommended) | Check (the working area at mid-span is SAEngine's placing) |
| P8E9 | compositeSlab.ponding | δ > h/10: the concrete 0.7 δ deeper | EN 1994-1-1 9.3.2(2) | Sure |
| P8E10 | compositeSlab.deflection.construction | δs,max = L/180 | EN 1994-1-1 9.6(2) (recommended) | Sure |
| P8E11 | compositeSlab.deflection.service | L/250 overall | EN 1990 A1.4, EN 1992-1-1 7.4.1(4) | SAEngine practice (no limit in EN 1994-1-1 9.8.2) |
| P8E12 | compositeSlab.thickness | h >= 80, hc >= 40; as a beam's flange h >= 90, hc >= 50 mm | EN 1994-1-1 9.2.1(2)-(3) | Sure |
| P8E13 | compositeSlab.modularFactor | n = 2 Ea / Ecm (short and long term together) | EN 1994-1-1 5.4.2.2(11) | Check (buildings: the simplified n) |
| P8E14 | compositeSlab.antiCrack | 0.2 % (unpropped), 0.4 % (propped) of the concrete above the ribs | EN 1994-1-1 9.8.1(2) | Sure |
| P8E15 | compositeSlab.meshMinimum | 80 mm²/m each way above the ribs | EN 1994-1-1 9.2.1(4)-(5) | Unsure (the clause number and value: check) |
| P8E16 | vertical shear | VRd,c of concreteMethods.shear (EN 1992-1-1 6.2.2) on the ribs' mean width and dp | EN 1994-1-1 9.7.5 | Sure |
| P8E17 | deck moments of the construction stage | one span: γG g L²/8 + γQ (q_out L²/8 + (q_in - q_out) a (2L - a)/8); continuous: 0.125 w L² over the support, 0.070 g L² + 0.096 q L² in the span; deflection 5/384 (one span), 1/185 (continuous) w L⁴ / EI | elastic beam coefficients | SAEngine practice |
| P8E18 | composite.beam.longitudinalShear | flangeStrut: cot θf 1.0-2.0 (compression flange), ν = 0.6 (1 - fck/250); planes a-a (beside the beam, top + bottom bars) and b-b (round the studs, 2 hsc + the studs' spread + d, the bottom bars twice) | EN 1994-1-1 6.6.6.1-6.6.6.3, Figure 6.15; EN 1992-1-1 6.2.4(4), 6.2.2(6) | Check (the b-b perimeter with the shank diameter; the deck's contribution Ape fyp,d of 6.6.6.4(4) is not counted) |
| P8E19 | composite.beam.camber | 80 % of the wet-concrete deflection on the steel alone, 5 mm steps, none below 20 mm | none (EN 1994-1-1 gives no camber rule) | SAEngine practice |
| P8E20 | floorVibration.compositeDynamicModulus | Ec,dyn = 1.1 Ecm, full interaction | SCI P354 (the dynamic modulus of normal-weight concrete) | Unsure (check the factor of SCI P354) |
| P8E21 | deck profiles | DECK_PROFILES: generic trapezoidal 46/150, 60/300, 80/300 (geometry only) | none (not a product's) | SAEngine practice: replace by the product's data |

## CFD wind tunnel (`cfdWind`; alpha 9 L3)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L3-1 | directionStep | 30° | none in the code | SAEngine practice |
| L3-2 | roughness | none here: the wind table's z0 of terrain categories 0-IV (0.003, 0.01, 0.05, 0.3, 1.0 m) | EN 1991-1-4 Table 4.1 | Sure |
| L3-3 | lowerLimit | 0.8 | after ASCE 7-22 Sec 31.4.3; EN 1991-1-4 gives none (a National Annex may) | SAEngine practice |
| L3-4 | validation / clauses | wind tunnel tests and properly validated numerical methods allowed | EN 1991-1-4:2005 Sec 1.5(2) | Check (wording) |

## Alpha 9 L7: special members — `webOpenings`, `glass`, `membranes`, `aluminium.joints`

| # | Key | Value | Source | Status |
|---|---|---|---|---|
| L7E1 | webOpenings.factors | γM0 = γM1 = 1.0, τy = fy/√3 | EN 1993-1-1 6.1 (recommended), 6.2.6 | Sure |
| L7E2 | webOpenings.circularLength | le = 0.45 d0 | SCI P355 | Check |
| L7E3 | webOpenings.webPost | strut, curve c (α 0.49, λ̄0 0.2), length 0.5 √(w0² + h0²) | SCI P355 (as read), EN 1993-1-1 6.3.1 | Unsure (the strut length) |
| L7E4 | webOpenings.geometry | d0/dg 0.5–0.8, w0/d0 ≥ 0.1, tee stem ≥ 30 mm, end post ≥ 0.5 d0 | SCI P355 | Unsure |
| L7E5 | webOpenings.vierendeelDeflection | +10 % | none | SAEngine practice |
| L7E6 | glass.partialFactors | γM;A 1.8, γM;v 1.2, fg;k 45, fb;k 70 / 120 / 150 MPa, ksp 1.0 / 0.75 / 1.0, kv 1.0 | EN 16612:2019 Sec 7, Table 4 | Check |
| L7E7 | glass.partialFactors.kmod | wind 0.74, barrier 0.89, snow 0.44, floors 0.5, permanent 0.29 | EN 16612:2019 Table 2 | Unsure (snow and floor durations) |
| L7E8 | glass.actionFactors | 1.5 variable, 1.35 permanent | EN 1990 A1 (set B) | Sure |
| L7E9 | glass.interlayers | PVB 0.44 / 0.05 MPa, ionoplast 100 / 10, EVA 3 / 0.5 | manufacturers' typical values (CEN/TS 19100 families) | SAEngine practice |
| L7E10 | glass.deflection, finBuckling | span/65, span/100, height/65, 50 mm; fin Mcr ≥ 1.5 M | none (National Annexes) | SAEngine practice |
| L7E11 | membranes | as the US pack (L7U19) | TensiNet guide; CEN/TS 19102 not entered | SAEngine practice |
| L7E12 | aluminium.joints.gamma | γM2 1.25, γMw 1.25 | EN 1999-1-1 Table 6.1 (recommended) | Sure |
| L7E13 | aluminium.joints.bolts | αv 0.6 (4.6, 8.8), 0.5 (10.9, A4-70, A4-80); As = 0.78 π d²/4 | EN 1999-1-1 Table 8.5 | Check |
| L7E14 | aluminium.joints.bearing | k1 ≤ 2.5, d0 = d + 1 mm | EN 1999-1-1 Table 8.5 | Check (the hole clearance is SAEngine practice) |
| L7E15 | aluminium.joints.weldStrength | fw: 5356 filler 210 MPa, 4043 190 MPa, with 6063 160 / 150 MPa | EN 1999-1-1 Table 8.8 | Unsure |
| L7E16 | aluminium.joints.haz | fu,haz = ρu,haz fu of the alloy, the force as shear | EN 1999-1-1 8.6.3.4 | Check |

Steel joists: no `steelJoists` table; joists are designed as generic open-web trusses by the
EN 1993-1-1 checks. Concrete-filled plate walls: not covered (no `compositePlateWalls`).

## Slope stability (`slopeStability`; alpha 9 L8)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L8E1 | verification | partial factors of the design approach (geotechnicalMethods.designApproach, DA1 here) | EN 1997-1 11.5.1 with 2.4.7.3.4 | Sure |
| L8E2 | partialFactors.resistances | γR;e R1 1.0, R2 1.1, R3 1.0 | EN 1997-1 Annex A Table A.14 (slopes and overall stability) | Check |
| L8E3 | partialFactors.soilWeight | 1.0 (the soil's weight not factored; γγ of the M set still divides it) | EN 1997-1 2.4.2(9)P note (single source) | SAEngine practice |
| L8E4 | checked | all four methods | EN 1997-1 11.5.1(1)P-(6) | SAEngine practice |
| L8E5 | seismic.khFactor | 0.5 (FH = 0.5 α S W) | EN 1998-5 4.1.3.3(3), Eq 4.1 | Sure |
| L8E6 | seismic.kvRatio | 0.5 (FV = ± 0.5 FH; 0.33 where avg/ag ≤ 0.6) | EN 1998-5 4.1.3.3(4), Eq 4.2 | Check (0.5 taken for every site) |
| L8E7 | seismic.materials / required | M2 (γφ' 1.25, γc' 1.25, γcu 1.4), F ≥ 1.0 | EN 1998-5 3.1(3) Note | Check |
| L8E8 | reinforcement | as the parent (FHWA-NHI-14-007 factors) | none in EN 1997-1 for soil nails | SAEngine practice |
| L8E9 | topographic amplification ST | not applied (kh by α S of the seismic settings) | EN 1998-5 4.1.3.3 / EN 1998-5 Annex A | Not built |


## Bridges and special structures (alpha 9 L9) — `movingLoads.json`, `bridgeDesign.json`, `latticeTowers.json`, `shellStructures.json`, `offshore.json`

| # | Path | Value | Clause | Status |
|---|---|---|---|---|
| L9E1 | movingLoads.laneWidth, narrow | 3 m; < 5.4 m one lane; 5.4-6 m two lanes of w/2 | EN 1991-2 4.2.3, Table 4.1 | Sure |
| L9E2 | movingLoads.vehicles ts1-ts3 | 2 × 300, 200, 100 kN at 1.2 m, gauge 2.0 m | Table 4.2, Figure 4.2a | Sure |
| L9E3 | movingLoads lm1 areaLoad | 9.0, 2.5, 2.5, 2.5 kN/m² | Table 4.2 | Sure |
| L9E4 | movingLoads lm2 | one axle 400 kN (βQ = 1), gauge 2.0 m | 4.3.3 | Sure |
| L9E5 | movingLoads multiplePresence, dynamic | αQ = αq = 1; dynamic amplification included | 4.3.2 (recommended), 4.3.1 | Check (National Annexes change α) |
| L9E6 | bridgeDesign.strength | 1.35 G (incl. surfacing), 1.35 Q (road traffic) | EN 1990 A2 Table A2.4(B) | Check (some NAs use 1.2 for surfacing) |
| L9E7 | bridgeDesign.prestress | 0.6 fck(t) at transfer; 0.45 fck permanent; 0.6 fck characteristic; no tension (0 MPa) at transfer and service | EN 1992-1-1 5.10.2.2(5); EN 1992-2 7.2(102), 7.2(3) | Unsure (no tension is SAEngine practice for the decompression of Table 7.101N) |
| L9E8 | bridgeDesign.prestress.relaxedYield | fp0,1k = 0.88 fpk | EN 1992-1-1 3.3 (typical) | Check |
| L9E9 | latticeTowers.annexB | cf,0 = 1.76 C1 (1 - C2 φ + φ²), C1 2.25 / 1.9, C2 1.5 / 1.4 | EN 1993-3-1 B.2.2.2 | Check |
| L9E10 | latticeTowers diagonal | Kθ = 1.11 at 45° (K1 0.55, K2 0.2) | B.2.2.? | Unsure |
| L9E11 | latticeTowers gust | cs cd = 1 on qp | EN 1991-1-4 6.1 | Practice |
| L9E12 | shellStructures.silos solids | wheat 9.0 kN/m³, φim 30°, Km 0.54, aK 1.11, μ 0.24/0.38/0.57, aμ 1.16; maize 8.4, 31, 0.53, 1.14, 0.22/0.36/0.53, 1.24; cement 16.0, 30, 0.54, 1.20, 0.41/0.46/0.51, 1.07 | EN 1991-4 Annex E Table E.1 | Unsure (every value) |
| L9E13 | shellStructures.silos discharge | Ch 1.15, Cw 1.10 (AAC 1) | EN 1991-4 5.2.4.3.1 | Unsure |
| L9E14 | shellStructures.silos.loadFactor | γF 1.5 | EN 1991-4 Annex A | Check |
| L9E15 | shellStructures.chimneys | St 0.18, K 0.13, Kw ≤ 0.6, Lj/b 6 / 4.8 + 12 yF/b / 12, vcrit < 1.25 vm | EN 1991-1-4 E.1.3.2, E.1.5.2, Tables E.4, E.5 | Check |
| L9E16 | shellStructures.chimneys.lateral | clat,0 0.7 to Re 3e5, 0.2 from 5e5 to 5e6, 0.3 from 1e7 | Figure E.2 | Unsure (read off a figure) |
| L9E17 | shellStructures.chimneys.damping | δs 0.012 welded steel, 0.020 insulated, 0.03 concrete | Annex F Table F.2 | Check |
| L9E18 | shellStructures.coolingTowers.rows | Re 5e5: 85°, -2.2, 135°, -0.4; 2e6: 80°, -1.9, 120°, -0.7; 1e7: 75°, -1.5, 105°, -0.8 | EN 1991-1-4 Table 7.12 | Check |
| L9E19 | shellStructures.coolingTowers.internal | -0.5 | none (VGB practice) | Practice |
| L9E20 | offshore | Cd 0.65 / 1.05, Cm 1.6 / 1.2, kinematics 0.9, blockage as the US pack, 1.1 G + 1.35 E | ISO 19902 9.4, 9.5, Table 9.10-1 | Unsure (clause numbers, the kinematics factor) |

Not covered by this pack: piping (`pipingStress`; EN 13480-3 planned) and load rating (EN
gives no rating method).
