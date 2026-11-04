# Chinese national standards (GB 50009, GB 50011, GB 50010, GB 50017)

Code pack `china-gb`, built in (alpha 9 track C20). It `extends` BNBC 2020: every table not in
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
| `steelLimitState` | f = fy/γR, S1-S5, φ of classes a-d, γx 1.05, shear, tension 0.7 fu An | GB 50017-2017 |

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

## Not covered (falls back to BNBC 2020, named so)

Concrete torsion, punching, crack width wmax, deflection, cover by environment class,
anchorage la / laE, walls, slender columns, the detailing by seismic grade inside the member
design (the grade and its factors are reported; the members follow the parent's rules at the
category's level), the seismic adjustment factor γRE (not applied: on the safe side), the
vertical earthquake, the top additional force δn of the base shear method, λ on every storey's
shear, GB 50017's φb (the parent method's χLT is used), steel connections and seismic steel,
GB 50007 foundations (fa with ηb, ηd and the settlement ψs), masonry, timber, the bar
schedule and every table not in `covers`. Every value is listed with its clause in
[VERIFY.md](VERIFY.md), for checking against the printed standards (no code text was available
when the pack was written).
