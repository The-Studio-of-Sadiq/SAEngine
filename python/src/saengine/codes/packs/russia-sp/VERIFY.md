# russia-sp: values to verify

Every value of the pack with its clause, entered from knowledge of the codes (no copy of the SP
texts was available when the pack was written). **U** marks a value the author was not sure of
(the value, or the clause number of the 2016-2018 editions with their amendments): check it
first. SAEngine practice (not a code value) is marked **P**.

## Limit state groups and combinations (SP 20.13330.2016, SP 14.13330.2018)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 1 | First limit state group (strength, stability) = SAEngine's strength combinations; second group (serviceability) = the service combinations | SP 20 4.1, 6.1 | |
| 2 | γf permanent: RC 1.1 on D with the superimposed dead load (steel 1.05, factory-made layers 1.2, site-made layers 1.3 not told apart: one D factor) | SP 20 7.2, Table 7.1 | U |
| 3 | γf permanent where a lower value is unfavourable 0.9 | SP 20 7.2 | |
| 4 | γf floor live 1.3 (1.3 below 2.0 kN/m², 1.2 at 2.0 and more: 1.3 taken) | SP 20 8.2.2 | P |
| 5 | γf snow 1.4 | SP 20 10.12 | |
| 6 | γf wind 1.4 | SP 20 11.1.12 | |
| 7 | γf earth pressure 1.15, fluids 1.1 | SP 20 Table 7.1 | U |
| 8 | Basic combination ψt1 1.0, ψt2 0.9, ψt3+ 0.7 of the short-term loads (ψl 1.0 of the long-term) | SP 20 6.3, 6.4 | U |
| 9 | Rows: 1.1D + 1.3L + 1.26S; 1.1D + 1.4S + 1.17L; 1.1D + 1.3L + 1.26W + 0.98S; 1.1D + 1.4W + 1.17L + 0.98S; 1.1D + 1.4W + 1.26S + 0.91L; 0.9D + 1.4W | SP 20 6.2, 6.3 | |
| 10 | Special combination with the earthquake: 0.9 permanent, 0.5 short-term (on the design values), E 1.0, no wind: 0.99D + 0.65L + 0.7S + E | SP 14 5.1, Table 2 | U (design or normative values; the long-term share of the live load at 0.8 not split) |
| 11 | 0.81D + E (0.9 × γf 0.9, no live load) for uplift | - | P |
| 12 | Service: D + L + S; D + 0.35L (long-term: the reduced live value, 0.7 of 2.0 for offices); D + 0.9L + W | SP 20 6.1, 6.2, Table 8.3 | U |
| 13 | Ω0 1.0 (no system overstrength in SP 14) | - | P |

## Live loads (SP 20.13330.2016 Table 8.3, kN/m², normative full values)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 14 | Apartments, dormitories, hotel rooms, hospital wards 1.5 | Table 8.3 item 1 | |
| 15 | Offices, classrooms 2.0 | Table 8.3 item 2 | |
| 16 | Laboratories, operating rooms 2.0 | Table 8.3 item 3 | U |
| 17 | Dining halls, reading rooms 3.0 / 2.0 | Table 8.3 item 4 a | U |
| 18 | Halls with fixed seats 4.0, without 5.0 | Table 8.3 item 4 b, c | U |
| 19 | Shops, exhibitions 4.0 | Table 8.3 item 5 | U |
| 20 | Book stores, archives 5.0 (at least) | Table 8.3 item 6 | U |
| 21 | Sports halls, stages 5.0 | Table 8.3 items 4 c, 8 | U |
| 22 | Machine rooms 5.0 (by the equipment) | Table 8.3 item 7 | P |
| 23 | Garages for cars 3.5 | Table 8.3 item 9 | U |
| 24 | Roofs, other areas 0.5; roofs used for rest 1.5 | Table 8.3 item 9 b, c | U (item numbers) |
| 25 | Corridors and stairs of dwellings 3.0; of offices, halls, public buildings 4.0 | Table 8.3 item 12 a, b | U |
| 26 | Balconies 2.0 (uniform over the area; the 4.0 strip not covered) | Table 8.3 item 13 | U |
| 27 | ψA1 = 0.4 + 0.6/√(A/A1), A1 9 m² (items 1, 2, 12 a) | SP 20 8.2.4 Eq 8.1 | |
| 28 | ψn1 = 0.4 + (ψA1 - 0.4)/√n (the influence-area form with the n floors' area) | SP 20 8.2.5 Eq 8.3 | |
| 29 | ψA2 / ψn2 uses (halls, shops, public corridors) not reduced | SP 20 8.2.4 | P |

## Snow (SP 20.13330.2016 Section 10)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 30 | S0 = ce ct μ Sg | SP 20 10.1 Eq 10.1 | |
| 31 | Sg by region: I 0.5, II 1.0, III 1.5, IV 2.0, V 2.5, VI 3.0, VII 3.5, VIII 4.0 kN/m² | SP 20 Table 10.1 | U |
| 32 | μ 1.0 up to 30°, 0 from 60°, linear between (single and double slope roofs) | SP 20 Appendix B, B.1 | |
| 33 | ce = 1 (the drift reduction of 10.5-10.9 not applied), ct = 1 (10.10 not applied) | SP 20 10.5, 10.10 | P (on the safe side) |
| 34 | Snow and roof live load not together (the larger) | - | P |
| 35 | Snow in the seismic weight 0.5 × 1.4 = 0.7 | SP 14 Table 2 | U |

## Wind (SP 20.13330.2016 Section 11)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 36 | w0 by region: Ia 0.17, I 0.23, II 0.30, III 0.38, IV 0.48, V 0.60, VI 0.73, VII 0.85 kN/m² (as V = √(w0/0.613), N/m²) | SP 20 Table 11.1 | U |
| 37 | wm = w0 k(ze) c, w = wm + wp | SP 20 11.1.3, 11.1.4 | |
| 38 | k(ze) = k10 (ze/10)^2α: A α 0.15 k10 1.0; B 0.20, 0.65; C 0.25, 0.4 | SP 20 11.1.6, Table 11.3 | U |
| 39 | k at least the value at 5 m (A, B) and 10 m (C) (Table 11.2's first row; A there 0.75, 0.81 here) | SP 20 Table 11.2 | U |
| 40 | ze = h for h <= d; d and h for d < h <= 2d; d, z, h for h > 2d (d the windward width; the split of the middle case at z = d, EN 1991-1-4 form) | SP 20 11.1.5 | U |
| 41 | ζ(ze) = ζ10 (ze/10)^-α, ζ10: A 0.76, B 1.06, C 1.78 | SP 20 11.1.8, Table 11.4 | U |
| 42 | wp = wm ζ(ze) ν, ν by ρ = b, χ = h of the windward face, Table 11.6 rows ρ 0.1-160 m and columns χ 5-350 m (0.95 ... 0.38) | SP 20 11.1.11, Tables 11.6, 11.7 | U (every ν) |
| 43 | Windward c 0.8, leeward -0.5 (ce3 -0.4 to -0.6 by the proportions, one value) | SP 20 Appendix B.1.2 | U |
| 44 | No directionality or topographic factor (1.0) | - | P |
| 45 | G 1.7 for the parent's roof and wall pressures that take the table's gust | - | P |
| 46 | The dynamic factor ξ for f1 < flim (Table 11.5) is not applied | SP 20 11.1.10 | U (flexible buildings under-estimated) |

## Earthquake (SP 14.13330.2018)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 47 | Intensity MSK-64 of the OSR-2015 maps: A (10 % in 50 years) mass construction, B (5 %) and C (1 %) increased responsibility / especially important (the client chooses: III -> B, IV -> C) | SP 14 4.3 | P (the map by category) |
| 48 | A = 0.1, 0.2, 0.4 g at 7, 8, 9 points | SP 14 5.5 | |
| 49 | 6 points: 0.05 g (SP 14 asks no calculation below 7); 10 points: 0.8 g (beyond SP 14) | - | P |
| 50 | Soil categories I, II, III, IV; the site's intensity one point less on I, one more on III (IV: a site-specific study, III assumed) | SP 14 Table 1 | U (IV) |
| 51 | The one-point shift as the factor 0.5 / 1 / 2 on the spectrum (A doubles per point) | - | P |
| 52 | Sik = K0 K1 S0ik, S0ik = Qk A β(Ti) Kψ ηik | SP 14 5.5 Eqs 1, 2 | |
| 53 | β = 1 + 15T (T <= 0.1 s), 2.5 (to 0.4 s, I-II; to 0.8 s, III-IV), 2.5 (Tc/T)^0.5 beyond; β at least 0.8 | SP 14 5.6 | U |
| 54 | K0: 0.8 (I reduced), 1.0 (II normal), 1.2 (III increased), 1.5 (IV essential) | SP 14 Table 3 | U |
| 55 | K1: RC frame 0.35, RC frame with diaphragms 0.3, monolithic walls 0.25, steel frame 0.25, braced steel 0.22 (R = 1/K1) | SP 14 Table 5 | U |
| 56 | Kψ 1.0 for buildings (1.5 towers and masts: not covered) | SP 14 Table 4 | U |
| 57 | ηk with a linear first mode: V = Sa (Σ Q h)² / Σ Q h², Fi ∝ Qi hi (the static method) | SP 14 5.5 Eq 3 | |
| 58 | Modes to 90 % of the mass; SRSS, modes with Tj/Ti >= 0.9 by CQC | SP 14 5.9-5.11 | U |
| 59 | Seismic weight: 0.65 L (0.5 × 1.3), snow 0.7 | SP 14 Table 2 | U |
| 60 | Height limits [m] at 7 / 8 / 9 points: RC frame 30 / 23 / 17, frame with diaphragms 50 / 40 / 30, monolithic walls 75 / 60 / 45, steel by calculation (above them SP 14 asks for scientific support, not a ban) | SP 14 Table 8 | U (every value) |
| 61 | Storey drift 2 % (I, II), 1.5 % (III), 1 % (IV) on Cd × the K1-reduced drift, Cd = 1/K1 | - | P (SP 14 has no drift limit) |
| 62 | Accidental eccentricity 0.1 of the plan dimension | SP 14 5.? | U |
| 63 | Orthogonal 100 % + 30 % | - | P |
| 64 | The SP 14 Section 6 rules of RC and steel buildings taken as SAEngine's intermediate detailing at 8 and 9 points | SP 14 Section 6 | P |
| 65 | City intensities (A, B, C) and regions (wind, snow): Moscow 5/5/6 I/III; Saint Petersburg 5/5/5 II/III; Novosibirsk 6/7/8 III/IV; Yekaterinburg 6/6/7 I/III; Kazan 6/6/7 II/IV; Nizhny Novgorod 5/5/6 I/IV; Samara 5/6/7 III/IV; Omsk 5/6/6 II/III; Rostov-on-Don 6/7/8 III/II; Krasnodar 7/8/9 IV/II; Sochi 8/9/9 IV/II; Makhachkala 9/9/10 V/I; Grozny 8/9/9 IV/I; Vladikavkaz 8/9/9 III/II; Barnaul 6/7/8 III/III; Gorno-Altaysk 8/9/9 II/III; Krasnoyarsk 6/7/8 III/III; Kyzyl 8/9/9 II/I; Irkutsk 8/9/9 III/II; Ulan-Ude 8/9/9 III/I; Chita 7/8/9 II/I; Khabarovsk 7/8/9 III/II; Vladivostok 6/7/8 IV/II; Yuzhno-Sakhalinsk 8/9/9 IV/VI; Petropavlovsk-Kamchatsky 9/9/10 VII/VII | SP 14 Appendix A; SP 20 Appendix E maps | U (every city) |

## Concrete (SP 63.13330.2018)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 66 | Rbn B15-B60: 11.0, 15.0, 18.5, 22.0, 25.5, 29.0, 32.0, 36.0, 39.5, 43.0 MPa (the project's concrete takes Rbn) | Table 6.7 | |
| 67 | Rb: 8.5, 11.5, 14.5, 17.0, 19.5, 22.0, 25.0, 27.5, 30.0, 33.0 MPa | Table 6.8 | |
| 68 | Rbt: 0.75, 0.90, 1.05, 1.15, 1.30, 1.40, 1.50, 1.60, 1.70, 1.80 MPa | Table 6.8 | |
| 69 | Eb: 24.0, 27.5, 30.0, 32.5, 34.5, 36.0, 37.0, 38.0, 39.0, 39.5 GPa | Table 6.11 | |
| 70 | γb 1.3, γbt 1.5 (in the tabulated values) | 6.1.11 | |
| 71 | γb1 0.9 for the long-term loads on Rb and Rbt (1.0 short-term: 0.9 taken for every combination) | 6.1.12 | P |
| 72 | Rbtn fit 0.2197 Rbn^0.672 (Table 6.7 within 0.02 MPa) | - | P |
| 73 | Rs: A240 210, A400 350, A500C 435 MPa; Rsc of A500 400 MPa (by min(Rs, Es εb0)) | Table 6.14 | U (A240 210 or 215) |
| 74 | Rsw = 0.8 Rs at most 300 MPa (A240 170: 168 here; A400 280; A500 300) | Table 6.15 | U |
| 75 | εb0 0.002, εb2 0.0035, εb1,red 0.0015 (two-linear) | 6.1.20, 6.1.22 | |
| 76 | Three-linear diagram: σb1 0.6 Rb at εb1 = σb1/Eb, Rb from εb0 to εb2 | 6.1.22 | U |
| 77 | Rectangular block Rb over x = 0.8 × the neutral axis depth (η 1.0, λ 0.8): ξR = 0.8/(1 + Rs/(Es εb2)) (A400 0.533, A500 0.493) | 8.1.6 Eq 8.1 | |
| 78 | The nonlinear deformation model (the section in equilibrium under a plane strain distribution with the diagrams) as the section method of a project override stressBlock 'bilinear' or 'trilinear' | 8.1.20-8.1.30 | |
| 79 | ea >= max(l/600, h/30, 10 mm) | 8.1.7 | |
| 80 | Shear Q <= Qb + Qsw, Qb = φb2 Rbt b h0²/c, φb2 1.5, 0.5-2.5 Rbt b h0 | 8.1.33 (2018 form) | U |
| 81 | Qsw = φsw qsw c0, φsw 0.75, c0 <= 2 h0, c from h0 to 3 h0, the worst c | 8.1.33, 8.1.34 | U |
| 82 | Links counted where qsw >= 0.25 Rbt b, else Rbt b = 4 qsw in Qb | 8.1.33 | U |
| 83 | Strut Q <= 0.3 Rb b h0 | 8.1.32 | |
| 84 | Q taken at the support face (SP: at the end of the inclined section) | - | P (on the safe side) |
| 85 | Least links qsw >= 0.25 Rbt b at Rbt of B25 (one value 0.236 MPa with γb1) | 8.1.33 | P |
| 86 | Link spacing <= 0.5 h0 and 300 mm | 10.3.13 | |
| 87 | Columns' shear: τc = 0.5 × 0.9 Rbt (Qb,min with γb1), τc,max 0.3 × 0.9 Rb, + the ties on d (on the safe side of the inclined section); no φn of the axial force | 8.1.33 | P |
| 88 | Punching F <= Rbt u h0, u at h0/2 from the loaded area; with links Fb + Fsw <= 2 Fb (Fsw = 0.8 qsw u: the method's steel term is the full excess, U) | 8.1.46, 8.1.48 | U |
| 89 | Crack width acrc = φ1 φ2 φ3 ψs σs/Es ls: φ1 1.4 (long-term), φ2 0.5 (ribbed), φ3 1.0 (bending), ψs = 1 (allowed) | 8.2.15 | U |
| 90 | ls = 0.5 Abt/As ds, Abt = 0.5 b h (the upper bound), at most 40 ds (the 10 ds and 100-400 mm bounds not applied) | 8.2.17 | U |
| 91 | acrc,ult 0.3 mm under the long-term loads (0.4 short-term not checked) | 8.2.6 | U |
| 92 | Deflection: the curvature of the cracked section approximated by B = Bs/θ (Bs = Es As h0²/(1.15 ψ + 0.2 + 6 αE ρ), ψ 1, θ 2.0 / 1.6) | 8.2.21-8.2.31 | P (the generic form, not SP's curvature) |
| 93 | Deflection limits l/120 (l <= 1 m), l/150 (3 m), l/200 (6 m), l/250 (24 m), l/300 (36 m), the steps at the stricter end | SP 20 Appendix E, Table E.1 | U |
| 94 | Cover 20 (closed rooms, normal humidity), 25 (high humidity), 30 (open air), 40 mm (ground with a blinding layer; 70 without) | 10.3.2, Table 10.1 | U |
| 95 | Water-cement ratios and least grades of the exposure conditions | - | P (SP 28 not covered) |
| 96 | l0,an = Rs ds/(4 Rbond), Rbond = η1 η2 Rbt, η1 2.5 (ribbed), η2 0.9 above 32 mm | 10.3.24 | U |
| 97 | lan = α l0,an >= 200 mm (15 ds not applied), compression α 0.75 | 10.3.25 | U |
| 98 | Laps ll = 1.2 l0,an >= 20 ds and 250 mm, bars up to 40 mm | 10.3.30, 10.3.31 | U |
| 99 | Least steel 0.1 % in bending (on b h); columns 0.5 % in total (0.25 % per face at λ >= 87), at most 4 % | 10.3.6 | U / P (4 %) |
| 100 | Side bars from 700 mm, 0.1 %, at most 400 mm apart | 10.3.? | U |
| 101 | Column bars >= 12 mm; ties >= 0.25 d, 6 mm, at most 15 d and 500 mm | 10.3.? , 10.3.14 | U |
| 102 | Bars Ø6-Ø40 (A400, A500C) | GOST 34028-2016 | |

## Steel (SP 16.13330.2017)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 103 | γm 1.025 (C245-C390 to GOST 27772) | Table 3 | U |
| 104 | Ryn [MPa] by thickness: C245 245 (to 20 mm), 235 (to 30); C255 255 (to 3.9), 245 (to 20), 235 (to 40); C345 345 (to 10), 325 (to 20), 305 (to 40), 285 (to 60); C390 390 (to 50) | Table B.5 | U |
| 105 | γc 1.0 (0.9 columns of public buildings, 0.75-0.95 others: project overrides) | Table 1 | U |
| 106 | φ = 0.5 (δ - √(δ² - 39.48 λ̄²)) / λ̄², δ = 9.87 (1 - α + β λ̄) + λ̄² | 7.1.3 Eqs 8, 9 | U |
| 107 | α, β: a 0.03, 0.06; b 0.04, 0.09; c 0.04, 0.14 | Table 7 | U |
| 108 | φ = 1 up to λ̄ 0.4; the cap 7.6/λ̄² not applied | 7.1.3 | U |
| 109 | Curves: hollow and round a; I sections b (major), c (minor); channels, tees, angles c | Table 7 | U |
| 110 | Tension N <= An Ru/γu, γu 1.3; single angles γc 0.75 | 7.1.1, Table 1 | U |
| 111 | Bending cx 1.05 (Table E.1: 1.07-1.12 for I sections) | 8.2.3 | U |
| 112 | Rs = 0.58 Ry | 8.2.1, Table 2 | |
| 113 | Width-thickness: flange outstand 0.5 √(E/Ry) = 14.8 ε, web 3.2 √(E/Ry) = 94.8 ε as the semi-compact limits; plastic and compact limits the generic ones | 8.5.18, 7.3.2, 8.5.1 | U |
| 114 | Slenderness: compression 150, tension 300 | Tables 32, 33 | U |
| 115 | G = 78 000 MPa | Table Г.10 | U |
| 116 | φb (Appendix Ж) not covered: the parent method's χLT (curves b / c) | 8.4 | U |
| 117 | The interaction of 9.1, 9.2 in the generic linear form (conservative) | 9.1, 9.2 | P |

## Foundations (SP 22.13330.2016)

| # | Value | Clause | |
| --- | --- | --- | --- |
| 118 | R = γc1 γc2 / k (Mγ kz b γII + Mq d1 γ'II + (Mq - 1) db γ'II + Mc cII), db = 0 | 5.6.7 Eq 5.7 | |
| 119 | Mγ, Mq, Mc by φII 0-45° (e.g. 30°: 1.15, 5.59, 7.95) from the closed form, equal to Table 5.5 to its rounding | Table 5.5 | U |
| 120 | γc1 1.25 sands, 1.1 clays (on the safe side), γc2 1.0 (flexible scheme) | Table 5.4 | U / P |
| 121 | k 1.1 (strength from tables or correlations) | 5.6.7 | |
| 122 | kz 1 for b < 10 m, z0/b + 0.2 with z0 8 m above | 5.6.7 | U |
| 123 | qa = R - σv of the founding layer; deeper layers keep the parent's check | - | P |

## Not covered (the parent's, named BNBC 2020)

Torsion (SP 63 8.1.36-8.1.45), slender columns by η = 1/(1 - N/Ncr) (the parent's moment
magnification), φb of SP 16, connections and the seismic steel rules, the dynamic wind factor ξ
and the cladding peak pressures, the SP 14 Section 6 detailing (SAEngine's intermediate level),
Kψ of towers, the vertical earthquake, masonry, timber, the bar schedule.
