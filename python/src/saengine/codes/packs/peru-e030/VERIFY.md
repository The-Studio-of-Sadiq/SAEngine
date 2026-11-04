# peru-e030: values to verify against the printed standards

No copy of E.030, E.060 or E.020 was available when this pack was written (alpha 9, track C24,
2026-11-05). Every value was entered from knowledge of the standards and is to be checked by the
owner. **Sure** / **Check** / **Uncertain** / **SAEngine practice** as in the other packs'
lists. Everything the pack does not set is the base pack's (`aci318-asce7-22`).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| P1 | locations.*.zone | Lima, Callao, Arequipa, Trujillo, Chiclayo, Piura, Ica, Tacna 4; Huancayo, Cajamarca, Puno 3; Cusco, Pucallpa 2; Iquitos 1 | E.030 Anexo I | Towns' zones | Uncertain (the coastal towns 4: Check; the others Uncertain) |
| P2 | locations.*.windSpeed | 20.8 m/s (75 km/h) | E.020 12.3 | Wind speed | Placeholder (E.020's least design speed; its own map and method are not set) |
| P3 | zoneCoefficients.zones | 0.10, 0.25, 0.35, 0.45 | E.030 Table 1 | Z | Sure |
| P4 | seismic.designSpectrum.shapeFactors.soilFactors | S0 0.80; S1 1.00; S2 1.60 / 1.20 / 1.15 / 1.05; S3 2.00 / 1.40 / 1.20 / 1.10 (Z1 / Z2 / Z3 / Z4) | E.030 Table 3 | Soil factor S | Check |
| P5 | seismic.siteClasses (TP, TL) | S0 0.3 / 3.0; S1 0.4 / 2.5; S2 0.6 / 2.0; S3 1.0 / 1.6 s | E.030 Table 4 | Periods | Check |
| P6 | seismic.siteClasses.*.shape | C = 2.5; 2.5 TP/T; 2.5 TP TL/T²; 1 + 7.5 T/TP below 0.2 TP (modal) | E.030 14, 29.2.2 | Amplification factor | Check |
| P7 | seismic.siteClasses.*.vs30 | > 1500, 500-1500, 180-500, < 180 m/s | E.030 Table 2 | Soil profiles | Check |
| P8 | seismic.designSpectrum.shapeFactors.leastSoilShare | 0.11 | E.030 28.2.1 | C/R ≥ 0.11 | Check |
| P9 | seismic.systems.*.R | concrete frames 8, dual 7, walls 6, limited ductility walls 4; steel SMF 8, IMF 5, OMF 4, SCBF 7, OCBF 4, EBF 8; masonry 3 | E.030 Table 7 | R0 | Check |
| P10 | seismic.systems.*.Cd | 0.75 R0 | E.030 31.1 | Displacement factor (regular buildings; 0.85 R irregular) | Check |
| P11 | seismic.systems.*.Omega0 | 3.0 frames, 2.5 walls and dual, 2.0 braces | - | Overstrength (E.030 gives none) | SAEngine practice |
| P12 | seismic.periodCoefficients | Ct = 1/35, 1/35, 1/45, 1/60, m = 1 | E.030 28.4.1 | T = hn / CT | Check (steel braced frames take 1/60 here: the "other" family) |
| P13 | seismic.allowableDrift / driftLimits | 0.010 steel and timber; 0.007 concrete; 0.005 masonry | E.030 Table 11 | Drift limits | Sure (limited ductility walls 0.005: enter it) |
| P14 | seismic.liveShare | 0.25 | E.030 26 | Category C (50 % A and B, 80 % storage: enter) | Check |
| P15 | seismic.minimumScale | 0.8 | E.030 29.4 | Modal / static base shear (regular) | Check |
| P16 | seismic.torsionIrregular / Extreme | 1.3 / 1.5 | E.030 Table 9 | Torsional irregularity | Check |
| P17 | seismic.verticalFactor | 2/3 | E.030 29.2.3 | Vertical spectrum | Uncertain (clause) |
| P18 | seismic.designCategories | zone 1 B, 2 C, 3-4 D | - | SAEngine's category for the detailing | SAEngine practice |
| P19 | occupancyCategories | U = 1.0, 1.0, 1.3, 1.5 | E.030 Table 5 | Use factor | Sure (uses: check) |
| P20 | combinations.strength | 1.4D + 1.7L; 1.25(D + L ± W); 0.9D ± 1.25W; 1.25(D + L) ± E; 0.9D ± E | E.060 9.2.1-9.2.3 | Load combinations | Check |
| P21 | combinations.temperature | 1.05D + 1.25L ± 1.05T | E.060 9.2.5 | Temperature | Uncertain |
| P22 | factors.phi | tied 0.70, shear 0.85, punching 0.85, bearing 0.70, plain 0.65 (tension 0.90, spirals 0.75 the base pack's) | E.060 9.3.2, 9.3.5 | Strength reduction factors | Check (plain: Uncertain) |
| P23 | concrete.barNames | 3/8" ... 1 3/8" at 10-36 mm | NTP 341.031 | Bar names | Check |
| P24 | areaLoads, wind method | the base pack's ASCE 7-22 | E.020 | Live loads, wind | Uncertain (E.020's values not set) |
