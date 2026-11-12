# Indian Standards (IS): loads, concrete, foundations, steel and the other materials

Code pack `is-codes`, built in. Alpha 9 track C7 covers the loads:

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 67 cities with their basic wind speed Vb and seismic zone (II-V as 2-5); default Delhi | IS 875 (Part 3):2015 Annex A, IS 1893 (Part 1):2016 Annex E |
| `zoneCoefficients` | Z = 0.10, 0.16, 0.24, 0.36 | IS 1893 (Part 1):2016 Table 3 |
| `occupancyCategories` | Importance I (1.0, 1.0, 1.2, 1.5) and the wind risk class of k1 (25, 50, 50, 100 years) in SAEngine's four slots | IS 1893 Table 8, IS 875 (Part 3) Table 1 |
| `areaLoads` | Imposed floor and roof loads, concentrated loads, the partition allowance | IS 875 (Part 2):1987 Tables 1-2, Clause 3.1.2 |
| `deadLoads` | Unit weights of brick masonry and cement plaster; 230 / 115 mm walls | IS 875 (Part 1):1987 Table 1 |
| `liveReduction` | Reduction by the number of floors carried, and of beams by area (`method: floorCount`) | IS 875 (Part 2):1987 Clause 3.2 |
| `combinations` | 1.5(D + L), 1.2(D + L ± W/E), 1.5(D ± W/E), 0.9D ± 1.5(W/E); serviceability | IS 875 (Part 5) 8.4, IS 456 Table 18, IS 1893 6.3.4 |
| `seismic` | Soil types I-III, the IS spectrum (Ah = (Z/2)(I/R)(Sa/g), Figures 2(a)/(b)), R of Table 9, Ta, least base shear, Qi by hi², scaling to VB, drift 0.004, irregularities, seismic weight | IS 1893 (Part 1):2016 Clauses 6-7 |
| `wind` | Terrain categories 1-4, Vz = Vb k1 k2 k3 k4, pz = 0.6 Vz², pd = Kd Ka Kc pz ≥ 0.7 pz, wall Cpe of clad buildings | IS 875 (Part 3):2015 Clauses 6-7 |

The methods the pack picks by id (generic SAEngine mechanisms shared with the other packs):
`wind.method: "speedFactors"` (`saengine.fem.wind_speed_factors`, with `wind.speedFactors` and
the wall coefficients `wind.cpByHeight`), `seismic.designSpectrum` (`reducedElastic` with
`factor` 0.5, `longPeriod: "constant"`, `staticPlateau`), `seismic.lateralForce`
(`distribution: "heightSquared"`, `minimumShare` by zone), `periodCoefficients.other.planDimension`
(0.09 h/√d), `seismic.driftAmplification: "designForces"` and `liveReduction.method:
"floorCount"`. A new project starts from `locations.default`, `seismic.defaultSiteClass`,
`seismic.defaultSystem` and `wind.defaultExposure`, each changeable in Project Settings.

## Concrete and foundations (track C8)

| Table | What it holds | Code |
| --- | --- | --- |
| `concreteMethods` | Design strengths (0.67 fck/1.5, fy/1.15, the 0.36 fck xu block, xu,max), the axial cap 0.4 fck Ac + 0.67 fy Asc, emin, shear by τc (Table 19) and τc,max (Table 20), least stirrups, torsion by Ve and Me1, punching ks τc, columns (additional moments, αn load contour), deflection (span/depth with kt, kc, kf; Annex C), crack width (Annex F), cover and mix by exposure (Tables 16, 5), Ld by τbd and laps, member steel limits, two-way slabs (Annex D), flat slab end spans (αc), wall shear, footings, IS 13920 ductile detailing | IS 456:2000, IS 13920:2016 |
| `concrete` | Ec = 5000 √fck | IS 456 6.2.3.1 |
| `detailing` | The ductile frame values Design Reinforcement reads (0.08 fck Ag, 200 mm beams, 0.8-4 % columns, 300 mm legs, 1.4 strong column, joint γ) | IS 13920:2016 |
| `foundations` | Bearing capacity factors (`bearingFactors.method: "flowValue"`), the column base 0.45 fck √(A1/A2), static pile capacity (`piles.staticMethod: "earthPressure"`), FS 2.5 | IS 6403, IS 2911 (Part 1/Sec 2), IS 456 34.4 |

The methods by id, each a generic SAEngine module: `ultimate.method: "partialFactors"`
(C5's `design_strength`, with the grade names, the axial shares and emin with l/500),
`shear.method: "tabulatedStress"`, `torsion: "equivalentShear"`, `punching: "rootStress"`
(`design/tabulated_shear.py`), `columns` (`design/additional_moment.py`), `deflection:
"spanDepthModification"` and `cracking: "strainSpacing"` (`design/span_depth_factors.py`),
`cover: "exposureCondition"`, `anchorage: "bondStressTable"`, `memberLimits`
(`design/member_limits.py`), `twoWaySlabs: "restrainedPanel"`, `flatSlabs: "columnStiffness"`
(`design/panel_coefficients.py`), `seismic: "ductileDetailing"` (`design/ductile_detailing.py`,
in place of the parent's Sec 8.3 rows). The project's concrete `fc` is read as fck; the exposure
condition is `concreteMethods.defaultExposure` (moderate), changeable in Code values.

## Steel and the other materials (track C9)

| Table | What it holds | Code |
| --- | --- | --- |
| `steelLimitState` | γm0 1.10, γm1 1.25, γmb, γmf, γmw; classification (plastic, compact, semi-compact, slender in ε); tension (gross yielding, net rupture, angles by α); compression by the buckling curves a-d (α, Table 10 curves, single angles by λe); flexure (βb Zp fy/γm0 ≤ 1.2 Ze fy/γm0, high shear, LTB by Mcr and χLT); shear with web buckling (simple post-critical); combined forces (9.3.1, 9.3.2); slenderness 180 / 400; the bolt, friction grip, block shear and fillet weld strengths; the Section 12 frame rules | IS 800:2007 |
| `steel` | The connection geometry the shared checks read: holes (Table 19), edges 1.5 / 1.7 d0, pitch 2.5 d, fillet sizes (Table 21), and the connection elements' resistance factors as IS 800 strengths | IS 800:2007 10.2, 10.5 |
| `steelSections` | ISMB, ISMC, equal angles, SHS / RHS / CHS (the IPE / HE families removed); properties computed by SAEngine | IS 808 |
| `serviceability` | Deflection limits of Table 6 (floors span/300 and /360, purlins, industrial members, rafters, gantry girders; cantilevers by their double length) | IS 800:2007 5.6.1 |
| `masonry` | `method: "basicStress"`: fc = fb ks ka kp (Table 8 basic stresses by unit strength and mortar, Table 9 stress reduction by SR and e/t, the area factor), SR ≤ 27, 1.25 fc for eccentric loads, flexural tension 0.07 / 0.14 MPa, shear 0.1 + fd/6 ≤ 0.5 MPa | IS 1905:1987 |
| `timber` | The parent's values (BNBC 2020 Chapter 11 follows IS 883) with the IS 883 clauses | IS 883:1994 |
| `composite` | Composite beams by the design strengths (0.36 fck block, 0.87 fy) and the tabulated stud strengths, slab concrete at least M20 | IS 11384:1985 |
| `combinations.allowable` | D, D + L, D + W, D + E, D + L + W, D + L + E for the permissible stress methods | IS 875 (Part 5) 8.1 |

The methods by id, each a generic SAEngine module: the table `steelLimitState` itself chooses
`design/steel/limit_state.py` (members, section proposals and the report go through
`members.check_member`; the connection helpers of `design/steel_connections.py` take its bolt,
weld and block shear strengths; `design/check.py` runs its `seismic` group, method
`prescriptiveFrames`, in place of the steel seismic provisions of B35 / B38), masonry
`method: "basicStress"` (`design/masonry_basic_stress.py`), composite beams
`beam.limitState.method: "partialFactors"` (`design/steel/composite.py`). The steel seismic
frame rules apply when a steel SMRF, OMRF or concentric braced frame (taken as SCBF) is a
system of the project.

## The remainder (track C9b)

| Table | What it adds | Code |
| --- | --- | --- |
| `concreteMethods.shear` | `axialFactor` 3, `axialMax` 1.5: column shear by δ τc (net tension: the line continued, not below 0) | IS 456 40.2.2 |
| `concreteMethods.walls` | the empirical axial strength Puw and Hwe/t (now checked) | IS 456 32.2.3-32.2.5 |
| `concreteMethods.twoWaySlabs` | the corner torsion steel (now checked, in place of the parent's corner rows) | IS 456 D-1.8 to D-1.10 |
| `concreteMethods.deepBeams` | `method: "leverArm"`: deep by l/D, z by the support, the tension zone, the side face steel as walls | IS 456 29 |
| `concreteMethods.corbels` | `method: "rootTie"`: av < d, the outer edge, the tie for Vu av + Nuc (h - d), shear with 2 d/av, links, bearing | IS 456 28, 34.4 |
| `stairMethods`, `designClauses` | the stairs' spans, built-in and open well rules cited from IS 456 33 (the parent's values); flights and landings by the slab rules | IS 456 33 |
| `steel` | the base plate bearing 0.6 fck | IS 800 7.4.1 |
| `steelSections` | ISLB, ISWB, ISHB (one section per size, the root radius from the published mass) | IS 808:1989 |
| `seismic` | `dampingCorrection.method: "table"` (Table 4 factors), `verticalFactor` 2/3 | IS 1893 (Part 1):2016 Table 4, 6.4.6 |
| `wind.speedFactors` | `cyclonic` (off; set it in Code Values), `cyclonicImportance` (k4 1.30 for the 100-year class), `cyclonicDirectionality` (Kd 1.0) | IS 875 (Part 3):2015 6.3.4, 7.2.1 |
| `masonry.seismic` | the strengthening by IS zones (III-V; V as the parent's highest group) | IS 4326:2013 |

Also: Design Reinforcement sizes the closed links of beams in torsion by IS 456 41.4.3 and
26.5.1.7 (the whole Asv/sv on the closed links, the IS spacing in place of the parent's ph/8)
and the required steel lists them; the IS 13920 joints are listed in the design report's
`joints` (the joints view); bolts of property class 4.6 are in the object library's grade list.

## Steel remainder (track C12, steel half)

| Table | What it adds | Code |
| --- | --- | --- |
| `steelLimitState.torsion` | torsion by the elastic St. Venant and warping stresses with γm0 (IS 800 has no torsion clause: SAEngine practice) | IS 800:2007 5.4.1 |
| `steelLimitState.bracing` | lateral restraints for 2.5 % of the flange (or axial) force | IS 800:2007 |
| `steelLimitState.columnSide` | web bearing and web buckling under the beam flange forces, the panel as web shear | IS 800:2007 8.7.4, 8.7.3.1, 8.4 |
| `coldFormed` | lipped C and Z members by permissible stresses (limiting widths, the lip's least depth, compression, bending, shear, combined; working forces = factored / 1.5) | IS 801:1975 |
| `steelFire` | the variation of fy and E with temperature, the limiting temperature 905 - 690 rf for every member, the heating by the lumped heat capacity (SAEngine practice) | IS 800:2007 Section 16 |

Values: VERIFY.md rows S1-S16.

## Concrete, foundations and loads leftovers (track C12)

| Table | What it adds | Code |
| --- | --- | --- |
| `concrete.prestress` | post-tensioned slabs: jacking 0.76 fpu, transfer 0.54 fci and 1 MPa, service 0.41 fck and 3 MPa (Types 1-2 as Class U), `tensionForm: "absolute"` (the limits as stresses); the losses' values are the parent's (the same as IS 1343) | IS 1343:1980 18, 22 |
| `plumbing.tanks` | water tanks: crack width 0.2 mm (limit state) or `crackControl: "steelStress"` (working stress, 130 / 190 MPa), surface zone steel 0.35 %, cover 45 mm, w/c 0.45, IS 456 Table 18 combinations | IS 3370 (Parts 1-2):2009 |
| `concreteMethods.deepBeams.hogging` | the support steel of continuous deep beams by zone | IS 456:2000 29.3.2 |
| `foundations.shallow` | `settlementRigidity` 0.8, `raftStiffness` 1.75/λ (a note), the permissible settlements cited by IS 1904 | IS 8009 (Part 1), IS 1904, IS 2950 (Part 1) |
| `seismic` | `periodCoefficients.concreteWall` (0.075 h^0.75/√Aw >= 0.09 h/√d for the RC wall systems), `designEccentricity` (1.5 esi ± 0.05 bi in the static torsion cases) | IS 1893 (Part 1):2016 7.6.2 (b), 7.8.2 |
| `wind.speedFactors` | `topography` (k3 by Annex C from Project Settings > Wind > Topography), `gustFactor` (Clause 10 for h/b > 5 or f0 < 1 Hz: the storey forces × G (k̄2/k2)²) | IS 875 (Part 3):2015 |
| `serviceability.sway` | H/500 | IS 16700:2017 |

The generic modules: `fem/gust_response.py` (gust factor), `fem/design_eccentricity.py`
(es and the design eccentricity), `fem/wind_speed_factors.slope_factor`, the wall-area period
of `fem/loads.approximate_period`, the tension forms of `design/prestress.py`, the crack control
methods of `plumbing/tanks.py`, `substructure/raft.raft_stiffness`. Values: VERIFY.md rows L1-L20.

## Not covered yet (falls back)

The pack `extends` BNBC 2020: every table not in `covers` comes from BNBC 2020. That is: the
concrete tables C8 does not replace (`factors`, `materials`, `slabCoefficients` shear shares,
`transfer` ...) for the checks the IS methods do not cover (construction joints, prestress),
`steelSeismic` and `steelStability` (not used by the limit state method, except the stability
method's K = 1 of the direct analysis), site investigation, flood, fire, the building services,
the nonstructural components and the storey drift and sway limits. Inside the covered tables the
parent's rules stay where IS has no counterpart in SAEngine's checks, named after the parent in
the notes: HSS joints, ponding, eccentrically braced frames, the composite columns and deck
rules (IS 800:2007 and IS 11384:1985 have none), reinforced masonry (IS 1905 covers unreinforced masonry only), the IS 1343 flexural strength,
shear and anchorage zones (the parent's ACI 318 based rules) and the strength design of tank sections. The report names the pack
as "Indian Standards (IS) (is-codes), ...; extends BNBC 2020 (bnbc2020) for the tables it does
not give".

Also not covered inside the loads: cladding and roof pressures (IS 875-3 Tables 5-8), the
across-wind response, the IS 16700 slenderness and acceleration limits.

Every value is listed with its clause in [VERIFY.md](VERIFY.md), for checking against the
printed codes (no code text was available when the pack was written).
