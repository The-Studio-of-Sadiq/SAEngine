# Russian codes of practice (SP 20, SP 14, SP 63, SP 16, SP 22)

Code pack `russia-sp`, built in (alpha 9 track C25). It `extends` BNBC 2020: every table not in
`covers` comes from the default pack and the report names it BNBC 2020. SI units throughout. The
clause names are the SP numbers (SP 20.13330.2016 and so on); no code text is in the pack.

The limit state groups: the first (strength and stability) is SAEngine's strength combinations
with the design values γf × the normative ones; the second (serviceability: cracks, deflections,
drift under wind) is its service combinations with the normative values.

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 25 cities with the OSR-2015 intensities on the maps A, B and C (`mapZones`), the wind region (as V = √(w0/0.613)) and the snow region (Sg); default Moscow | SP 14 Appendix A, SP 20 Appendix E |
| `zoneCoefficients` | A in g: 0 (5 and below), 0.05 (6), 0.1 (7), 0.2 (8), 0.4 (9), 0.8 (10) | SP 14 5.5 |
| `occupancyCategories` | K0 0.8 / 1.0 / 1.2 / 1.5 in the slots I-IV | SP 14 Table 3 |
| `areaLoads` | Floor live loads by use | SP 20 Table 8.3 |
| `liveReduction` | ψA1 and ψn1 (the influence-area form, A1 9 m²) | SP 20 8.2.4, 8.2.5 |
| `combinations` | Basic combinations with γf and ψt 1.0 / 0.9 / 0.7; the special combination with the earthquake 0.9 / 0.5; service with γf 1 | SP 20 Section 6, SP 14 Table 2 |
| `wind` | wm = w0 k(ze) c of terrain A, B, C with ze by the proportions, the pulsation 1 + ζ(ze) ν | SP 20 11.1 |
| `snow` | S0 = μ Sg, μ 1 to 30°, 0 at 60° | SP 20 10.1, Appendix B |
| `seismic` | Soil categories I-IV with β(T), K1 as R = 1/K1, the hazard map by occupancy, ηk of a linear mode, height limits by intensity | SP 14 |
| `concrete` | Bars Ø6-Ø40 (A400, A500C) | GOST 34028, SP 63 10.3.6 |
| `concreteMethods` | Rb, Rbt, Eb of B15-B60, Rs, the rectangular block (ξR) or the nonlinear deformation model, the inclined section, punching, cracks, deflection, cover, anchorage, least steel | SP 63 |
| `steelLimitState` | Ry of C245-C390 with γm, φ of the curves a, b, c, the members | SP 16 |
| `foundations` (partial) | The design resistance R of the founding layer; the rest the parent's | SP 22 5.6.7 |
| `designClauses` | The clauses of the punching and deflection checks | SP 63 |

## Methods by id (the generic SAEngine modules)

- Earthquake `designSpectrum.method: "shapeFactors"` (`fem/spectra.py`, alpha 9 C18): Z = A,
  the importance = K0, R = 1/(K1 Kψ), Ch(T) = the soil category's β(T) branches (1 + 15T, 2.5,
  2.5 (Tc/T)^0.5, at least 0.8), the one-point shift of categories I / II / III as the soil
  factor S 0.5 / 1 / 2 (`shapeFactors.soilFactors`, alpha 9 C24; IV takes III with the
  site-specific study warning).
- Alpha 9 C25 `seismic.hazardMaps` with `locations.*.mapZones` (`library/settings.py`
  `derived`): the town's zone on the map of the occupancy category (A for I-II, B for III, C for
  IV; a project overrides `seismic.hazardMaps.byOccupancy.III` or `.default`).
- Alpha 9 C25 `lateralForce.correctionMethod: "linearMode"` (`fem/loads.py`): the static base
  shear × (Σ W h)² / (Σ W Σ W h²), the linear first mode's ηk, with Fi ∝ Wi hi.
- `modalCombination` `independence` 0.9 (alpha 9 C5c): SRSS, close modes by CQC.
- Wind `powerLaw` with the exposures' `kzFactor` (k10), `zg` 10 m and `alpha` = 1/α; alpha 9
  C25 `referenceHeight: "proportions"` (ze of SP 20 11.1.5 by the windward width) and
  `pulsation` (G(z) = 1 + ζ(ze) ν with ζ of `exposures.*.pulsationZeta`, ν of Table 11.6).
- Concrete `concreteMethods.ultimate` `partialFactors` (`design/design_strength.py`) with alpha 9
  C25 `designStrengths` (Rb, Rbt, Eb tabulated by Rbn, × γb1 0.9) and `cubePrefix` "B";
  `stressBlock` "rectangular" (default; Rb over 0.8 x, εb2 0.0035: ξR follows) or the
  nonlinear deformation model "bilinear" / "trilinear" (alpha 9 C25: the two- and three-linear
  diagrams of 6.1.22 integrated over the section's mesh by concreteproperties, the section in
  equilibrium under a plane strain distribution; set it as a project override
  `concreteMethods.ultimate.stressBlock`).
- Shear `tabulatedStress` (`design/tabulated_shear.py`) with alpha 9 C25 `inclinedSection`
  (method `qbQsw`: Q <= Qb + Qsw at the worst projection c, the strut 0.3 Rb b h0) and the links'
  `stirrupYieldShare` 0.8 / `stirrupYieldMax` 300 MPa (Rsw); Design Reinforcement sizes the links
  by the same inclined section.
- Punching `rootStress` `tensile` (F <= Rbt u h0), cracks `effectiveTensionRatio` with ψs = 1,
  deflection `longTermStiffness` (an approximation of SP 63's curvature, P) with the SP 20
  Table E.1 limits, cover `exposureCondition`, anchorage `bondStressTable` (Rbond = 2.5 Rbt),
  `memberLimits`.
- Steel `steelLimitState` (`design/steel/limit_state.py`) with `compression.perry` (alpha 9
  C20): SP 16's φ written as Perry constants a2 = 1 - α, a3 = π β on λn = λ̄/π.
- Alpha 9 C25 `foundations.shallow.designResistance` (method `frictionAngleFactors`,
  `soil/bearing.py`): R = γc1 γc2 / k (Mγ kz b γ + Mq d γ' + Mc c) of the soil report's founding
  layer, qa = R - σv, in place of the bearing capacity over the factor of safety.

## Not covered (falls back to BNBC 2020, named so)

Torsion (SP 63 8.1.36-8.1.45), the slender columns' η = 1/(1 - N/Ncr) (the parent's moment
magnification is used), φb of SP 16 (the parent method's χLT), connections and the seismic steel
rules, the dynamic wind factor ξ of flexible buildings and the cladding peak pressures, the SP 14
Section 6 detailing rules (SAEngine's intermediate level at 8 and 9 points), Kψ of towers, the
vertical earthquake, masonry, timber, the bar schedule and every table not in `covers`. Every
value is listed with its clause in [VERIFY.md](VERIFY.md), for checking against the printed codes
(no code text was available when the pack was written: most values are marked U).
