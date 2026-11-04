# nepal-nbc: values to verify against the printed NBC 105:2020

No copy of NBC 105:2020, NBC 102, NBC 103 or NBC 104 was available when this pack was written
(alpha 9, track C21, 2026-11-05). Every value was entered from knowledge of the code and is to
be checked by the owner. **Sure**, **Check**, **Uncertain** and **SAEngine practice** as in the
other packs' lists. Everything the pack does not set is the parent's (`is-codes`, its VERIFY.md).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N1 | locations.*.zone (Z × 100) | Kathmandu, Lalitpur, Bhaktapur, Hetauda, Dharan 0.35; Pokhara, Bharatpur, Biratnagar, Birgunj, Janakpur, Butwal, Nepalgunj 0.30; Birendranagar, Dhangadhi 0.40 | Table 4-5, Figure 4-2 | Seismic zoning factor Z | Uncertain (SAEngine readings from memory: check every municipality) |
| N2 | seismic.siteClasses.*.shape | Ch = 1 + (α - 1) T/Ta to Ta; α to Tc; α [K + (1 - K)(Tc/T)²](Tc/T)² beyond, held beyond 6 s | 4.1.2, Eq 4.1(1) | Spectral shape factor | Uncertain (the powers of the long-period branch, (Tc/T) or (Tc/T)², and the branch beyond 6 s are from memory: check Eq 4.1(1)) |
| N3 | seismic.siteClasses (Table 4-1) | A: Ta 0.11, Tc 0.5, α 2.5, K 1.8; B: 0.11, 0.7, 2.5, 1.8; C: 0.11, 1.0, 2.5, 1.8; D: 0.5, 2.0, 2.25, 0.8 | Table 4-1 | Soil type parameters | Check (soil D confirmed on a public DUDBC slide; A-C from memory) |
| N4 | seismic.designSpectrum (shapeFactors) | Cd(T) = Ch(T) Z I / (Rμ Ωu); α below Ta for the ESM (staticPlateau) | 4.1, 6.1 | ULS design spectrum | Check |
| N5 | seismic.systems (Rμ / Ωu) | RC MRF 4 / 1.5; RC dual 4 / 1.5; RC walls 3 / 1.5; steel MRF 4 / 1.5; steel EBF 4 / 1.5; steel CBF 3 / 1.3; masonry with bands 2 / 1.2 | Table 5-2 | Ductility and overstrength factors (R = Rμ Ωu, Cd = Rμ) | Uncertain (check every row; Ωs is not used) |
| N6 | seismic.periodCoefficients | Ct = 1.25 kt: 0.09375 (RC MRF, kt 0.075), 0.10625 (steel MRF, 0.085), 0.09375 (EBF, 0.075), 0.0625 (others, 0.05); m 0.75 | 5.1.2 | T1 = 1.25 kt H^(3/4) | Check |
| N7 | occupancyCategories | I 1.0 (slots I, II), 1.25 (III), 1.5 (IV) | Table 4-3 | Importance factor | Check |
| N8 | seismic.allowableDrift, driftAmplification | 0.025; Rμ × the elastic deflections (displacementFactor) | 5.6.3, 6.5 | ULS drift | Check |
| N9 | locations.*.windSpeed | 47 m/s | NBC 104 | Basic wind speed (the parent's IS 875 method) | Uncertain |
| N10 | seismic.liveShare | 0.3 | 5.2 | λ of the seismic weight (0.6 storage: Code Value) | Check |
| N11 | combinations.strength | 1.2D + 1.5L; D + 0.3L + E; the parent's wind rows | 3.6.1 | Combinations | Check (whether 3.6 also gives 0.9D + E; the wind rows are IS 456 Table 18, Nepal practice) |
| N12 | (SLS not built) | Cs = 0.2 C(T) / Ωs, drift 0.006 | 4.2, 5.6.3 | Serviceability | SAEngine practice: the SLS drift over the ULS drift is 0.2 Ωu/Ωs ≈ 0.24 for Ωu 1.5, Ωs 1.25, and 0.006 / 0.24 = 0.025, so the ULS check governs for those factors |
| N13 | seismic.accidentalEccentricity | 0.1 b | 5.5 | Accidental eccentricity | Check |
| N14 | seismic.torsionIrregular / torsionExtreme | 1.5 / 2.0 | 5.5.2 | Torsional irregularity | Uncertain |
| N15 | seismic.massParticipation / orthogonalShare | 0.90 / 0.30 | Section 7; 3.5 | Modes, 100 % + 30 % | Check |
| N16 | seismic.minimumScale | 1.0 | Section 7 | Modal base shear scaled to the static one | SAEngine practice (on the safe side) |
| N17 | seismic.pgaFactor / verticalFactor | 1.0 / 0.6667 | 4.1, 4.3 | PGA = Z; vertical (2/3) Z | Uncertain |
| N18 | seismic.designCategories, requiredDetailing | one category D (special) for every Z | 4.1.4 | Ductile detailing everywhere | SAEngine practice |
| N19 | seismic.defaultSiteClass | C | - | New projects | SAEngine practice |
