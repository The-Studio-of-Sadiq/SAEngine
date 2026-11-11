# NTC-CDMX 2017 (`mexico-ntc`)

A built-in pack for Mexico City (alpha 9 track C17): the Normas Técnicas Complementarias of the
city's building regulations, with the CFE wind manual where the NTC refer to it. It `extends`
the US pack `aci318-asce7-22` (NTC-Concreto follows ACI 318's form) and sets what the NTC
change; every other table is the US pack's (see its README) and the report names those ACI
318-19, AISC 360-22 or ASCE 7-22. Choose it in **02 Project Settings → Design code** or in the
**New Project** wizard; the city is in **Site → Location** and its zone (I, II, IIIa-IIId) is
the **site class**. Any value can be overridden per project under **Code Values**; switching the
pack applies on the next run. New projects start in SI units. Clause names are given in short
Spanish form only.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md). No copy of the
norms was available when the pack was written: the values are to be checked against the printed
editions before the pack is used for design.

## What it sets

| Table | What | Clause |
| --- | --- | --- |
| `locations`, `zoneCoefficients` | Ciudad de México: VR and the barometric factor G of its altitude (as the town's pressure factor); Z 1.0 (the spectrum comes from the zone) | CFE Viento 4.2; NTC-Sismo 1.4 |
| `occupancyCategories` | Groups B2, B1, A2, A1 (ids I-IV); 1.5 for Group A | Reglamento Art. 139; NTC-Sismo 3 |
| `areaLoads` | Wm of the common uses (habitación 1.9, oficinas 2.5, comunicación 3.5 kPa ...) | NTC-Criterios Tabla 6.1.1 |
| `combinations` | 1.3D + 1.5L; 1.1(D + L + W or E); 0.9D + 1.1(W or E) | NTC-Criterios 2.3, 3.4 |
| `seismic` | The zone spectra (a0, c, Ta, Tb, r) reduced by Q' and the regularity factor (method `ductilityOverstrength`, alpha 9 C17), the site-specific form with k and R; Q of the systems; drifts Q × elastic, 0.006 / 0.012; the static method's distribution and 1.5 es ± 0.1 b | NTC-Sismo 1.8, 3-6, 8 |
| `wind` | Frz = c (z/10)^α of terrain categories 1-4 (Kz = Frz²); no gust factor for rigid buildings | CFE Viento 4.2.3, 4.3 |
| `factors` | FR 0.9, 0.75, 0.65 / 0.75, 0.7 | NTC-Concreto 3.7 |
| `concrete` | Bars #2.5-#12 | NMX-B-506 |
| `steel`, `designClauses` | The column curve with n = 1.4; lateral-torsional buckling by Mu | NTC-Acero 5.2, 6.3 |

## The seismic spectrum

The zone spectra of NTC-Sismo (2004 edition's Tabla 3.1) are the default: choose the site's
zone as its site class. For a site-specific spectrum of the 2017 edition (the city's SASID
values a0, c, Ta, Tb, k), override `seismic.designSpectrum.ductility.sites.<zone>` under Code
Values with its values and k: the method then takes Q' with √(β/k) and R = k1 R0 + k2. The
regularity factor (0.9, 0.8, 0.7 for irregular structures, NTC-Sismo 6.4) is
`seismic.designSpectrum.ductility.regularityFactor` (1 for a regular structure: set it).

## Not covered (the parent's method or none, named in the report)

- Other cities (CFE MDOC-Sismo / PRODISIS spectra and their regional wind speeds): a custom
  location with the site's values.
- The NTC-Concreto shear and torsion equations, its development lengths and the Chapter 7
  ductile detailing values: the parent's ACI 318-19 (marcos dúctiles ↔ special frames).
- NTC-Acero connections and Chapter 12 seismic design: the parent's AISC 360-22 / 341-22.
- The regularity conditions of NTC-Sismo Sec 6 (no checks: set the factor), the modified static
  distribution for T > Tb, the 30 m limit of the static method, the 2017 drift limits by system,
  the vertical component.
- Group A's gravity factors 1.5 / 1.7 (raise them under Code Values), the instantaneous live load
  Wa in the accidental combinations (Wm taken, on the safe side).
- The CFE topography factor and the dynamic factor of flexible structures, snow (none in the
  city; the parent's would apply to an entered ground snow load), masonry (NTC-Mampostería) and
  timber (NTC-Madera): the parent's.
- The bar names #2.5-#12 are shown in US customary display units only (SI shows Ø and the
  diameter); the bar schedule is the parent's ACI 315 form.
