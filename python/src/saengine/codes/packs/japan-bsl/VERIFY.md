# japan-bsl: values to verify against the printed law, notifications and AIJ standards

No copy of the Building Standard Law, its Enforcement Order (EO), the MLIT/MOC notifications or
the AIJ standards was available when this pack was written (alpha 9, track C19, 2026-11-05).
Every value was entered from knowledge of them and is to be checked by the owner. **Sure**:
well-known value, low risk. **Check**: believed right, confirm the number or the row.
**Uncertain**: the value or its reading may be wrong, or it is an SAEngine form of the rule;
SAEngine's choice is stated. Everything the pack does not set is the US pack's
(`aci318-asce7-22`, its VERIFY.md).

## Site (N1793 Art. 1, N1454 Art. 2)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J1 | zoneCoefficients.zones | 1: 0.7, 2: 0.8, 3: 0.9, 4: 1.0 | N1793 Art. 1 | Z of the regions | Sure |
| J2 | locations: Z = 1.0 | Sendai, Fukushima, Mito, Utsunomiya, Maebashi, Saitama, Chiba, Tokyo, Yokohama, Fukui, Kofu, Nagano, Gifu, Shizuoka, Nagoya, Tsu, Otsu, Kyoto, Osaka, Kobe, Nara, Wakayama, Tokushima, Kochi | N1793 Art. 1 | Z of the capitals | Sure for Tokyo, Yokohama, Nagoya, Osaka, Kobe, Kyoto, Shizuoka; Check for the others; Uncertain Tokushima, Kochi (regions split within the prefectures) |
| J3 | locations: Z = 0.9 | Sapporo, Aomori, Morioka, Akita, Yamagata, Niigata, Toyama, Kanazawa, Tottori, Matsue, Okayama, Hiroshima, Takamatsu, Matsuyama, Kumamoto, Oita, Miyazaki | N1793 Art. 1 | | Check (Morioka, Yamagata, Niigata Uncertain: may be 1.0) |
| J4 | locations: Z = 0.8 | Yamaguchi, Fukuoka, Saga, Nagasaki, Kagoshima | N1793 Art. 1 | | Check |
| J5 | locations: Z = 0.7 | Naha | N1793 Art. 1 | Okinawa | Sure |
| J6 | locations.*.windSpeed | V0 [m/s]: Tokyo 34, Osaka 34, Nagoya 34, Naha 46; Sapporo 32, Sendai 30, Fukuoka 34, Hiroshima 32, Kyoto 32, Kobe 34, Yokohama 34, Chiba 36, Kochi 38, Kagoshima 38, Wakayama 36, Tokushima 36, Nagasaki 36, Miyazaki 36; the others 30-34 (pack data) | N1454 Art. 2 table | Standard wind speed | Sure Tokyo 34, Naha 46; Uncertain all others (from memory of the municipality list: check each) |
| J7 | locations.towns | coordinates of the city centres | - | Site map suggestion | Sure |
| J8 | locations (snow) | no vertical snow depth (prefecture rules, N1455) | N1455 | The project enters sk | SAEngine practice |

## Loads (EO Art. 82, 85, 86)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J9 | areaLoads row 1 | 1800 / 1300 / 600 N/m² | EO Art. 85(1) table row 1 | Dwellings' rooms, bedrooms, wards | Sure |
| J10 | areaLoads row 2 | 2900 / 1800 / 800 | row 2 | Offices | Sure |
| J11 | areaLoads row 3 | 2300 / 2100 / 1100 | row 3 | Classrooms | Sure |
| J12 | areaLoads row 4 | 2900 / 2400 / 1300 | row 4 | Sales floors | Sure |
| J13 | areaLoads row 5 | fixed seats 2900 / 2600 / 1600; other 3500 / 3200 / 2100 | row 5 | Assembly | Sure |
| J14 | areaLoads row 6 | 5400 / 3900 / 2000 | row 6 | Garages | Sure |
| J15 | areaLoads row 7 | 3500 / 3200 / 2100 (row 5 other) | row 7 | Corridors, entrances, stairs serving rows 3-5 | Check (SAEngine applies it to every public corridor) |
| J16 | areaLoads row 8 | row 1 values | row 8 | Roof plazas, balconies (schools and stores: row 4) | Check (SAEngine: row 1 for balcony, terrace, roofPromenade; row 5 other for roofGarden) |
| J17 | areaLoads.storageLight | 3900 (slab, frame, seismic) | EO Art. 85(3) | Warehouse floors at least | Check (frame and seismic = slab: SAEngine practice) |
| J18 | areaLoads mapping | SAEngine uses to rows (README; dining, gymnasium, danceHall, grandstand -> row 5 other; cellBlock, atticHabitable -> row 1; accessFloorOffice -> row 2) | - | | SAEngine practice |
| J19 | areaLoads.partitions | removed (no allowance) | EO Art. 84 | Partitions are fixed load | Check |
| J20 | seismic.liveShare | 0.5 for uses without seismicLive | - | | SAEngine practice |
| J21 | liveReduction.method | frameValue (frameLive / live on beams and columns, the largest ratio of the uses) | EO Art. 85(1) column (ii) | | Check (column reduction of Art. 85(2) not covered) |
| J22 | combinations.allowable | L1 G+P, L2 G+P+0.7S (long-term); S1 G+P+S, W1 G+P+W, W2 G+P+0.35S+W, E1 G+P+K, E2 G+P+0.35S+K (short-term) | EO Art. 82(2) table | | Sure |
| J23 | combinations.allowable W0, E0 | G+W, G+K (P = 0) | EO Art. 82(2) note (P by the actual state for uplift) | | Uncertain (SAEngine takes P = 0) |
| J24 | combinations.strength | long-term × 1.5, short-term × 1.0 | - | Bar sizing by the parent's method | SAEngine practice (not the law's) |
| J25 | combinations (heavy snow rows) | formed wherever the model has a snow case | - | | SAEngine practice (conservative in ordinary areas) |
| J26 | snow.shape | μb = √cos(1.5β), 0 above 60°, as points | EO Art. 86(4) | Roof shape factor | Sure (formula); points SAEngine |
| J27 | snow.seismicShare / seismicThreshold | 0.35 above sk 2.0 kN/m² | EO Art. 82(2) table | 0.35S with K in heavy-snow areas | Uncertain (threshold SAEngine: 1 m at 20 N/m²/cm) |
| J28 | snow (unit load) | 20 N/m² per cm of depth (ordinary areas) | EO Art. 86(2) | For the project's sk | Sure |

## Wind (EO Art. 87, N1454)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J29 | wind.exposures I-IV | Zb 5, 5, 10, 20 m; ZG 250, 350, 450, 550 m; α 0.10, 0.15, 0.20, 0.27 | N1454 Art. 1(2) table | Er = 1.7 (max(z, Zb)/ZG)^α | Sure |
| J30 | wind.exposures.*.kzFactor | 2.8287 = 1.7² × 0.6/0.613 | EO Art. 87(2): q = 0.6 E V0² | The program's constant carried | Sure (arithmetic) |
| J31 | wind.exposures.*.gustByHeight | H <= 10 m: 2.0, 2.2, 2.5, 3.1; H >= 40 m: 1.8, 2.0, 2.1, 2.3; linear | N1454 Art. 1(3) table | Gf | Check |
| J32 | wind.cpWindward / cpLeeward | 0.8 (× kz through the height profile), -0.4 | N1454 Art. 3 (Table of Cpe) | Closed buildings, walls | Check |
| J33 | wind.defaultExposure | III | N1454 Art. 1(2) | Ordinary towns | SAEngine practice |

## Seismic force (EO Art. 82-2, 82-6, 88; N1793)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J34 | shearCoefficient.standardCoefficient | C0 = 0.2 | EO Art. 88(2) | Primary design | Sure |
| J35 | shearCoefficient.ultimateCoefficient | C0 = 1.0 | EO Art. 88(3) | Required horizontal capacity | Sure |
| J36 | shearCoefficient (Rt) | 1 (T < Tc); 1 - 0.2 (T/Tc - 1)² (< 2Tc); 1.6 Tc/T | N1793 Art. 2 | | Sure |
| J37 | siteClasses S1-S3 TC | 0.4, 0.6, 0.8 s | N1793 Art. 2 table | Soil types 1-3 | Sure |
| J38 | shearCoefficient (Ai) | 1 + (1/√α - α) 2T/(1 + 3T) | N1793 Art. 3 | | Sure |
| J39 | periodCoefficients | 0.02 h concrete, 0.03 h steel (T = h (0.02 + 0.01 α)) | N1793 Art. 2 | | Sure (mixed structures by their system: SAEngine) |
| J40 | systems.*.R, Cd | 1.0 | - | C0 is the design level, the drift elastic | SAEngine practice |
| J41 | systems.*.Omega0 | 2.0 | - | Em of the parent's capacity rules | SAEngine practice |
| J42 | seismic.allowableDrift | 1/200 (0.005) | EO Art. 82-2 | Layered drift (1/120 with the finishes shown sound) | Sure |
| J43 | horizontalCapacity.shapeFactors rsLimit / reLimit | 0.6 / 0.15 | EO Art. 82-6 | Route 2 limits | Sure |
| J44 | occupancyCategories | I = 1.0 all | EO Art. 87, 88 | No importance factor | Sure |
| J45 | seismic.designCategories / requiredDetailing | C (Z 0.7, 0.8), D (0.9, 1.0); ordinary | - | For the parent's modules | SAEngine practice |
| J46 | seismic.accidentalEccentricity | 0.05 (only when the project asks) | - | | SAEngine practice |
| J47 | seismic.pgaFactor | 0.4 | - | Z to PGA for other checks | SAEngine practice |

## Allowable stresses (EO Art. 90, 91; AIJ RC Standard 2018; AIJ Steel Standard 2005)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J48 | allowableStress.concrete | fc = Fc/3 long, 2Fc/3 short | EO Art. 91 | Compression | Sure |
| J49 | allowableStress.concrete shear | fs = min(Fc/30, 0.49 + Fc/100) long, × 1.5 short | EO Art. 91, AIJ RC Art. 6 | | Sure |
| J50 | allowableStress.concrete.modularRatio | n = 15 | AIJ RC Art. 5 / Art. 13 | All grades (AIJ: 15 up to Fc 27, smaller above) | Uncertain (SAEngine keeps 15 for every grade) |
| J51 | allowableStress.concrete.leverArm | j = 7/8 d | AIJ RC | | Sure |
| J52 | rebar SR235 | 155 / 235, shear 155 / 235 | EO Art. 90 | | Check |
| J53 | rebar SD295 | 195 / 295, shear 195 / 295 | EO Art. 90 | | Sure |
| J54 | rebar SD345 | 215 (195 from D29) / 345, shear 195 / 345 | EO Art. 90, AIJ RC Art. 6 | | Sure |
| J55 | rebar SD390 | 215 (195 from D29) / 390, shear 195 / 390 | EO Art. 90 | | Check |
| J56 | rebar SD490 | 215 (195 from D29) / 490, shear 195 / 490 | EO Art. 90 | | Uncertain (AIJ limits wft to 390; the law's value for SD490 shear bars to check) |
| J57 | shear | Qa = b j (α fs + 0.5 wft (pw - 0.002)) short, b j α fs long; α = 4/(M/(Qd)+1), 1-2 beams, 1-1.5 columns; pw <= 1.2 % | AIJ RC Art. 15 | | Check (AIJ 2010+ splits short-term into damage control with 2/3 α fs; SAEngine takes the classic form) |
| J58 | elastic section | cracked, no concrete in tension, n × the concrete stress in the bars, compression bars not deducted | AIJ RC Art. 13 | Beams and columns, each column axis on its own | Check |
| J59 | steel | ft = F/1.5, fs = ft/√3, Λ = √(π² E/(0.6F)), fc parabola 0.4 and ν = 3/2 + 2/3 (λ/Λ)², 0.277 F/(λ/Λ)² | EO Art. 90, AIJ Steel Ch 5 | | Sure |
| J60 | steel.bending | fb = max(F (2/3 - 4/15 (lb/i)²/(C Λ²)), 89 000/(lb h/Af)) <= ft, C = 1.0 | AIJ Steel (older ASD form) | | Uncertain (the 2005 standard has the λb form; C = 1.0 SAEngine) |
| J61 | steel lengths | lb and the buckling length = the member's analysis length, K = 1 | - | | SAEngine practice |
| J62 | steel.modulus | 205 000 MPa | EO / AIJ | | Sure |

## Horizontal capacity (EO Art. 82-3, N1792)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J63 | ds.concrete | FA 0.30/0.35/0.40, FB 0.35/0.40/0.45, FC 0.40/0.45/0.50, FD 0.45/0.50/0.55 for βu <= 0.3 / <= 0.7 / above | N1792 Art. 4 | RC Ds | Check (the law combines the frames' and walls' ranks; SAEngine one rank) |
| J64 | ds.steel | FA 0.25/0.30/0.35, FB 0.30/0.35/0.40, FC 0.35/0.40/0.45, FD 0.40/0.45/0.50 | N1792 Art. 3 | Steel Ds | Uncertain (the braces' ranks BA-BC are not entered) |
| J65 | shapeFactors | Fs = 2 - Rs/0.6 below 0.6; Fe 1.0 to Re 0.15, 1.5 from 0.45, linear | N1792 Art. 5 | | Sure |
| J66 | capacityDrift | 1/100 | - | Qu read at this storey drift (law: at the mechanism) | SAEngine practice |
| J67 | systems βu | frames 0, frame-walls 0.5, walls 1.0, braced 0.8, frame-braced 0.5 | - | | SAEngine practice |
| J68 | defaultRank | FD | - | Without design ranks | SAEngine practice |
| J69 | memberRanks.columns | FA: h0/D >= 2.5, σ0/Fc <= 0.35, pt <= 0.8 %, τu/Fc <= 0.1; FB: 2.0, 0.45, 1.0, 0.125; FC: σ0/Fc <= 0.55, τu/Fc <= 0.15 | N1792 Art. 4 | RC columns | Check |
| J70 | memberRanks.beams | FA τu/Fc <= 0.15, FB <= 0.2 | N1792 Art. 4 | RC beams | Check |
| J71 | memberRanks.steelColumns | H flange 9.5/12/15.5, web 43/45/48; box 33/37/48; pipe 50/70/100 × 235/F | N1792 Art. 3 | | Uncertain |
| J72 | memberRanks.steelBeams | H flange 9/11/15.5, web 60/65/71 | N1792 Art. 3 | | Uncertain |
| J73 | memberRanks.shearFailureRank | FD where Qsu < Qmu | N1792 Art. 4 | | Check |
| J74 | shearStrength | Qsu = {0.068 pt^0.23 (Fc+18)/(M/(Qd)+0.12) + 0.85 √(pw σwy) + 0.1 σ0} b j, 1 <= M/(Qd) <= 3, pw <= 1.2 % | AIJ / BSL commentary (Arakawa mean) | | Sure |
| J75 | shearStrength flexure | Mu = 0.9 at σy d (beams), 0.8 at σy D + 0.5 N D (1 - N/(b D Fc)) (columns) | BSL commentary | | Sure |
| J76 | shearStrength.yieldFactor | σy = 1.1 F | MLIT N2464 (ultimate strength of SD bars) | | Check |
| J77 | member rank lengths | h0, L0 = analysis lengths; Qmu of columns = 2 Mu / h0 | - | | SAEngine practice |
| J78 | stiffness for Re | D = 12 E I / h³ (columns), walls in-plane flexure + shear (fixed-fixed), beams rigid; the weights' centre of the masses at and above the storey's top | N1792 Art. 5 (D values) | | SAEngine practice (the law's D values include the beams) |
| J79 | pushover.targetDisplacement | the parent's ASCE 41 method with spectrumR 0.2 (Z Rt × 1.0) | - | | SAEngine practice |

## Bars (JIS G 3112)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| J80 | concrete.barDiameters / barNames | D10 9.53, D13 12.7, D16 15.9, D19 19.1, D22 22.2, D25 25.4, D29 28.6, D32 31.8, D35 34.9, D38 38.1, D41 41.3 mm | JIS G 3112 | Nominal diameters | Sure |
| J81 | concrete (sets by use) | main D16-D32, columns D19-D41, slabs and links D10-D16 | - | | SAEngine practice |

## Column splice hoops (pack follow-up 2026-11-09)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| S1 | detailing.special.columnSplice* (inherited) | the ACI 318-19 pack's: ties over the lap splices of special moment frame columns at the end zones' spacing (least dimension / 4, 6 db, so) | AIJ RC Standard (column lap splices) | Check (the Japanese rule not entered) |
