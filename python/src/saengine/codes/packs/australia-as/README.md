# Australian Standards (AS/NZS 1170, AS 3600, AS 4100)

Code pack `australia-as`, built in (alpha 9 track C18). It `extends` BNBC 2020: every table not
in `covers` comes from the default pack and the report names it BNBC 2020. The New Zealand pack
`newzealand-nzs` extends this one.

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 26 towns with Z and the V500 of their wind region (A0-A5, B1, B2, C, D); default Sydney | AS 1170.4 Table 3.3, AS/NZS 1170.2:2021 Table 3.1(A) |
| `zoneCoefficients` | Z 0.03-0.12 in SAEngine's zone slots 1-10 | AS 1170.4 Table 3.3 |
| `occupancyCategories` | IL1-IL4 in the slots I-IV: kp 0.75 / 1.0 / 1.3 / 1.5, the wind row marker | AS/NZS 1170.0 Table 3.3, NCC B1.2b, AS 1170.4 Table 3.1 |
| `areaLoads` | Imposed actions by occupancy type A-F, R | AS/NZS 1170.1 Table 3.1 |
| `liveReduction` | ψa = 0.3 + 3/√A, 0.5-1.0 (`influenceArea` with KLL 1) | AS/NZS 1170.1 3.4.2 |
| `combinations` | 1.35G, 1.2G + 1.5Q, 1.2G + ψc Q + Wu, 0.9G + Wu, G + ψE Q + Eu; G + ψs Q, G + ψl Q, G + ψs Q + Ws | AS/NZS 1170.0 4.2, 4.3, Table 4.1 |
| `wind` | Vsit = VR Md Mz,cat Ms Mt, p = 0.6 Vdes² Cp,e Ka Kc Kl Cdyn, TC1-TC4 | AS/NZS 1170.2:2021 |
| `seismic` | Classes Ae-Ee with Ch(T), μ and Sp, the equivalent static and modal methods, T1, drift 1.5 % | AS 1170.4-2007 (Amdt 2) |
| `materials` | εcu 0.003, the block α2 and γ, the squash α1, Es, G | AS 3600:2018 8.1.3, 10.6.2.2 |
| `factors` | φ of Class N bars, φ = 1.24 - 13 kuo/12 | AS 3600:2018 Table 2.2.2 |
| `concrete` | Bars N10-N40, ρ of columns, Ec, shrinkage steel, deflection limits | AS 3600:2018, AS/NZS 4671 |
| `concreteMethods` | Beam shear by kv and θv (`compressionField`) | AS 3600:2018 8.2 |
| `steelLimitState` | AS 4100 members (see below) | AS 4100:2020 |

## Methods by id (the generic SAEngine modules)

- Wind `method: "speedFactors"` (`fem/wind_speed_factors.py`): VR / V500 as k1 (by the
  importance level's row at the town's V500), Mz,cat as k2, Mt as k3 (Project Settings > Wind),
  Ms as k4, Md as Kd, Ka and Kc,e as Ka, Kc; 0.6 Vdes².
- Earthquake `designSpectrum.method: "shapeFactors"` (`fem/spectra.py`, alpha 9 C18): the site
  class's Ch(T) branches; Cd(T) = kp Z Ch(T) Sp/μ with the system's R holding μ, kp Z at least
  0.08; the equivalent static method takes the plateau below 0.1 s (`staticPlateau`).
- Concrete: the strength design with φ (the default path) with the pack's stress block
  (`materials.stressBlock`), φ by kuo (`factors.phiTransition`) and the beam shear by the
  compression field method of C17 (`concreteMethods.shear`, the AS 3600 constants, kv at most
  0.10 without the least links).
- Steel `steelLimitState` (`design/steel/limit_state.py`): γm0 = 1/0.9, the λe limits in
  ε = √(250/fy) units, `compression.slendernessReduction` (αc with αb by section family),
  `flexure.slendernessReduction` (αs), shear 0.6 fy Aw, the linear section and member checks.

## Alpha 9 C18b (version 0.2)

- Torsion `concreteMethods.torsion` method `torsionInteraction` (`design/torsion_interaction.py`,
  AS 3600 8.3): Jt, Tuc, neglected below 0.25 φTuc, no links up to T*/φTuc + V*/φVuc = 0.5,
  web crushing with Tu.max = 0.2 f'c Jt, closed links Tus, their spacing, ΔAl (informative).
- Punching `concreteMethods.punching` method `momentTransfer` (`design/moment_punching.py`,
  AS 3600 9.3): fcv = 0.17 (1 + 2/βh) √f'c <= 0.34 √f'c, Vu = Vuo/(1 + u M*v/(8 V* a dom)) in
  flat slabs, footings and the slab frames; closed fitments and shearheads not laid out.
- Walls `concreteMethods.simplifiedWalls` method `simplifiedWall` (`design/simplified_walls.py`,
  AS 3600 11.5, 11.6): the simplified axial strength (informative) and the in-plane shear by
  Hw/Lw.
- Wind `speedFactors.hillShape` (AS/NZS 1170.2 4.4.2): Mh at each level's height from Project
  Settings > Wind > Topography (H, Lu, x, downwind); `speedFactors.gustFactor` with
  `form: "dynamicResponse"`: Cdyn of Section 6 for n1 below 1 Hz on the design pressure.
- Earthquake `designCategories.byHeight`, `simpleStatic`, `dynamicRequired` (AS 1170.4 2.2,
  Table 2.1, Section 5): the EDC by hn in the analysis, EDC I designed by Fi = 0.1 Wi, EDC III
  noted as needing the dynamic analysis.
- `designClauses`: the clauses of the covered checks (torsion, deflection, punching, accidental
  eccentricity, fire); a key without an AS counterpart names the row without a clause.

## Not covered (falls back to BNBC 2020, named so)

Slender columns (AS 3600 10.4 δb, δs with Nc from Mub), the seismic detailing (Clause 14 and
Appendix C: the parent's ordinary detailing rows apply), anchorage and laps (13.1, 13.2),
strut-and-tie for deep beams and corbels (Chapters 7 and 12), the walls' minimum steel and
detailing (11.7), footings and pile caps beyond punching, connections (AS 4100 Chapter 9: the
parent's connection checks are AISC-shaped and are not re-based), masonry (AS 3700: none of
SAEngine's masonry engines has the capacity-reduction-factor form of AS 3700) and timber
(AS 1720.1: the timber engine's modification factors are not the k1-k12 of AS 1720.1), the
services, fire and the other tables not in `covers`. The bar schedule stays the parent's BS 8666:
AS 3600 and AS/NZS 4671 give no shape code standard of their own, and Australian schedules use
shapes of the same form. The earthquake design category by height does not include the kp Z and
site class columns of Table 2.1 (see VERIFY.md). Every value is listed with its clause in
[VERIFY.md](VERIFY.md), for checking against the printed standards (no code text was available
when the pack was written).
