# Chinese national standards (GB 50009, GB 50011, GB 50010, GB 50017, GB 50007)

Code pack `china-gb`, built in (alpha 9 tracks C20, C20b). It `extends` BNBC 2020: every table not in
`covers` comes from the default pack and the report names it BNBC 2020. SI units throughout.

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 37 cities with intensity, design earthquake group, w0 (as v0 = √(1600 w0)) and s0; default Beijing | GB 50011 Appendix A, GB 50009 Appendix E |
| `zoneCoefficients` | αmax of the frequent earthquake in slots 1-6: 6 (0.05g) 0.04 ... 9 (0.40g) 0.32 | GB 50011 Table 5.1.4-1 |
| `occupancyCategories` | 丁 丙 乙 甲 in the slots I-IV, importance 1.0 | GB 50223 |
| `areaLoads` | Floor live loads by use (2021 values), roofs 0.5 / 3.0 | GB 55001 4.2.2, GB 50009 5.1.1, 5.3.1 |
| `liveReduction` | By the floors above (1.00 ... 0.55), beams over 25 m² 0.9 | GB 50009 5.1.2 |
| `combinations` | 1.3G + 1.5Q, with wind ψc 0.6 / live ψc 0.7, 1.0G + 1.5W, 1.3(G + 0.5Q) + 1.4E | GB 55001 3.1.13, GB 55002 4.3.2 |
| `wind` | wk = βz μs μz w0: μz of terrain A-D, μs 0.8 / -0.5, βz >= 1.2 | GB 50009 Ch 8, GB 55001 4.6.5 |
| `snow` | sk = μr s0, μr 1.0 to 25°, 0 at 50° | GB 50009 7.1.1, Table 7.2.1 |
| `seismic` | Site classes I0-IV, Tg by group, the influence coefficient spectrum, λ, drift limits, rare drift, seismic grades | GB 50011, GB 55002 |
| `concrete` | Bars Φ6-Φ40 (HRB400 / HRB500), column steel 0.55 %-5 % | GB/T 1499.2, GB 50010 8.5.1, 9.3.1 |
| `concreteMethods` | Design strengths C20-C80, α1 β1 εcu, 0.9(fc A + fy' As'), beam shear 0.7 ft b h0 + fyv Asv h0 / s | GB 50010 4.1, 4.2, 6.2, 6.3 |
| `steelLimitState` | f = fy/γR, S1-S5, φ of classes a-d, γx 1.05, shear, tension 0.7 fu An; C20b: bolts, fillet welds, seismic steel by grade | GB 50017-2017, GB 50011 Ch 8 |
| `designClauses` | C20b: the clauses of the torsion, deflection and punching checks | GB 50010 |
| `foundations` (partial) | C20b: fa by ηb / ηd, the settlement with ψs; the rest the parent's | GB 50007-2011 |

## Methods by id (the generic SAEngine modules)

- Earthquake `designSpectrum.method: "influenceCoefficient"` (`fem/spectra.py`, alpha 9 C20):
  Z = αmax, α(T)/αmax = 0.45 + (η2 - 0.45) T/0.1 to 0.1 s, η2 to Tg, η2 (Tg/T)^γ to 5 Tg,
  η2 0.2^γ - η1 (T - 5 Tg) to 6 s; γ, η1, η2 from the damping ratio (Project Settings >
  Seismic > damping). R = 1 (elastic design for the frequent earthquake). The city's design
  earthquake group sets `seismic.spectrumType` (group1-3, the Tg row; it is applied like a
  project override, so the Code values list shows it); a project's own override wins.
- The base shear method: `lateralForce` Geq = 0.85 GE (`correction`), Fi ∝ Gi Hi (`linear`), λ
  by zone (`minimumShare`); the modal method by the response spectrum with CQC.
- Two-level design (`fem/two_level_seismic.py`): `seismic.rareDrift` checks the elasto-plastic
  storey drift under the rare earthquake, Δup = ηp Δue with Δue the response spectrum drift ×
  α_rare(T1)/α(T1), against [θp] (1/50 frame, 1/100 frame-wall, 1/120 wall);
  `seismic.seismicGrades` gives the grade 一-四 of Table 6.1.2 (乙 buildings one degree higher)
  with ηc, ηvc, ηvb, ηvw, μN and λv, in the seismic design summary and its notes. A pushover
  (P3) or nonlinear time histories (P5) under the rare earthquake are the detailed check.
- Wind `method: "speedFactors"` (`fem/wind_speed_factors.py`): 0.625 v0² with k2 = √μz.
- Concrete: `concreteMethods.ultimate` `partialFactors` (`design/design_strength.py`) with the GB
  strength classes and relations, and `shear` `tabulatedStress` with τc = 0.7 ft by grade.
- Steel `steelLimitState` (`design/steel/limit_state.py`) with `compression.perry` (the Perry
  constants of GB 50017 Appendix D).

## Alpha 9 C20b: the remainder (methods by id, unset in every other pack)

- Design yields by bar grade (`ultimate.designYields`, GB 50010 Table 4.2.3-1): HRB400 360 MPa
  in place of 400/1.15; the axial cap 0.9 (fc A + fy' As') on them (`axialYieldShare`).
- Torsion `plasticModulus` (`design/plastic_torsion.py`, 6.4): Wt = b²(3h - b)/6, βt, the
  closed links for T and V together, Astl (flagged), the least links.
- Punching `rootStress` with `strength: "tensile"` (6.5.1): 0.7 βh ft η um h0, η = min(η1, η2).
- Cracks `effectiveTensionRatio` and deflection `longTermStiffness`
  (`design/tension_stiffening.py`, 7.1.2, 7.2): wmax with ψ and B = Bs/θ under Mq.
- Cover by environment class 一-三b (`cover` `exposureCondition` with `beamCover`, 8.2.1),
  la = ζa lab, laE = ζaE la and the laps ζl (`anchorage` `bondStressTable` with `lapFactors`,
  8.3, 8.4, 11.1.7), the member steel (`memberLimits` with `beamMinRatio`, 8.5.1, 9.1-9.3).
- Slender columns `endMomentMagnifier` (`design/end_moment_magnifier.py`, 6.2.3-6.2.4).
- Walls `shearSpanWalls` (`design/shear_span_walls.py`, 6.3.21, 11.7.4).
- The seismic grade in the member design `seismic.gradeDesign` (`design/seismic_grades.py`):
  ηc, ηvc, ηvb, ηvw on the earthquake part of the forces, γRE (Table 5.4.2) on the earthquake
  combinations, then the checks of μN, λv, the end zones and the grade's least steel (GB 50011
  6.2, 6.3). Design Reinforcement sizes from the same forces.
- The top force δn (`lateralForce.topForce` with `cornerFactor` and `offsets`, Table 5.2.1) and
  the vertical earthquake `verticalComponent` `gravityShare` (5.3.3; on with Project Settings >
  Seismic > vertical component, in the response spectrum combinations).
- GB 50017 connections (`steelLimitState.connections`: fv, ft by bolt grade, fc, P, ffw by
  electrode, 11.2, 11.4) and the seismic steel rules by grade (`seismic.gradeFrames`, GB 50011
  8.2.5, 8.3, 8.4).
- GB 50007 (`foundations.shallow`, the rest of the table the parent's): fa = fak + ηb γ (b - 3)
  + ηd γm (d - 0.5) of a qa given in Project Settings > Foundation without a soil report, and the
  settlement by the layer-wise summation with ψs (5.2.4, 5.3.5).

## Not covered (falls back to BNBC 2020, named so)

λ on every storey's shear, the joints of the seismic grade, the corner columns' and the
bottom sections' extra factors (6.2.3, 6.2.6), the torsion need in Design Reinforcement (the
check rows only), the 9-degree tall buildings' vertical action of 5.3.1 (the 20 % share is
used), GB 50017's φb (the parent method's χLT is used), GB 50007's fa from the shear strength
(5.2.5; the soil report's own qa is kept), masonry, timber, the bar schedule and every table
not in `covers`. Every value is listed with its clause in [VERIFY.md](VERIFY.md), for checking
against the printed standards (no code text was available when the pack was written).
