# Hong Kong Codes of Practice (`hongkong-cop`)

A thin built-in pack (alpha 9 track C23). The Hong Kong Codes of Practice of the Buildings
Department grew out of the British Standards, so the pack `extends` the legacy pack `bs8110`
(BS 8110, BS 6399, BS 5950) and sets only what the Hong Kong codes change; every other table
is the parent's (see its README), named BS 8110 / BS 6399 / BS 5950 in the report. Choose it in
**02 Project Settings → Design code** or in the **New Building** wizard; its places are in
**Site → Location**. Any value can be overridden per project under **Code Values**.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md). No copy of the
Hong Kong codes was available when the pack was written: the wind pressures (H1) and the
imposed loads are to be checked against the printed codes before design.

## What it sets

| Table | What | Code |
| --- | --- | --- |
| `locations` | 7 places, one pressure profile for the territory; zone 0 | CoP Wind Effects 2019 |
| `wind` | Design pressure by height (2.5 m to 500 m), Sq on the pressure, Sθ and the size and dynamic factor 1.0, no lack-of-correlation factor | CoP Wind Effects 2019 |
| `concreteMethods` | γm 1.15 (bars); 0.9 x / 0.8 x / 0.72 x and x/d <= 0.5 / 0.4 / 0.33 by grade; εcu above C60; Ec = 3.46 √fcu + 3.21; vc with fcu <= 80; vmax 0.8 √fcu <= 7 N/mm² | CoP Structural Use of Concrete 2013 |
| `concrete` | Ec of the analysis model (4050 √fcu) | CoP Concrete 2013 Table 3.2 |
| `areaLoads` | Domestic 2.0, offices 3.0, roofs without access 0.75 kPa | CoP Dead and Imposed Loads 2011 |

## Generic mechanisms it uses (open to any pack)

- `wind.speedFactors.referencePressures`: codes that tabulate the design pressure by height. For
  such a terrain pz = q(z) k1 k3 k4 (the factors act on the pressure), the basic wind speed is not
  used; `topographic` (Project Settings → Wind) is the site's Sq.
- `concreteMethods.ultimate.relations.<relation>.steps` and `ultimate.neutralAxisSteps`: a value
  by strength band (the stress block depth, εcu, the neutral axis limit).

## Not covered

- Earthquake: the pack makes no earthquake cases (zone 0). Hong Kong's seismic provisions are not
  included; a Z entered per project uses BNBC 2020's spectrum (named so).
- Wind: the dynamic response of tall or slender buildings (the size and dynamic factor), the
  directional factor by direction, the across-wind and torsional effects, cladding pressures.
- Steel: the Code of Practice for the Structural Use of Steel 2011 is not set; the parent's BS
  5950-1:2000 values apply to the members SAEngine designs.
- Concrete covers and durability of the HK code, the HK load combinations' special cases (the
  parent's BS 8110 Table 2.1 apply), the other imposed load rows (BS 6399-1).
