# BNBC 2020 code pack (`bnbc2020`)

The built-in pack of SAEngine: Bangladesh National Building Code 2020, Part 6 (Structural
Design). It is the root pack other packs extend (`"extends": "bnbc2020"`), and the default of
every project (`codePack` in 02 Project Settings).

The values are the ones SAEngine used before code packs, transcribed from its modules, so a
project computes exactly as before. `python/tests/test_codes_bnbc_pack.py` keeps a frozen copy
of the old constants and checks every value of the pack against it.

## Tables

| File | What it holds | Clauses |
| --- | --- | --- |
| `locations.json` | Towns: seismic zone, basic wind speed V | Table 6.2.8 (p. 600), Table 6.2.15 (p. 615) |
| `zoneCoefficients.json` | Zone coefficient Z by zone | Table 6.2.14 (p. 615) |
| `occupancyCategories.json` | Categories I-IV, seismic and wind importance | Tables 6.1.1 (p. 480), 6.2.17 (p. 616), 6.2.9 (p. 601) |
| `areaLoads.json` | Live loads by use (a selection) | Table 6.2.3 (pp. 533-539) |
| `combinations.json` | Load cases; strength, temperature and gravity combinations; D factors of the combinations with E | Sec 2.7.3.1 (p. 685) |
| `seismic.json` | Site classes and spectrum (S, TB, TC, TD), systems (R, Ω0, Cd, height limits, detailing level), Ct/m, SDC table, drift limits, RS scaling, torsion, Ev | Sec 2.5 (pp. 609-648) |
| `wind.json` | Exposures (α, zg), Kd, Kzt, G, Cp | Sec 2.4, Tables 6.2.11, 6.2.12 (pp. 602-603) |
| `materials.json` | εcu, Es, G of steel, f'c and fy limits of seismic members | Sec 8.3.3 (pp. 1089-1090) |
| `factors.json` | φ of concrete design | Sec 6.2.3 (pp. 897-898) |
| `concrete.json` | Bar sizes, spacings, steel ratios, minimum thickness tables, assumed covers, cracked stiffness, slenderness limits, wall steel | Chapter 6 (Tables 6.6.1, 6.6.3, pp. 900-902) |
| `detailing.json` | Special moment frames, joints, special walls, lintels | Sec 8.3 (pp. 1088-1122) |
| `steel.json` | φ, slenderness limits, An ≤ 0.85 Ag | Chapter 10 |
| `foundations.json` | Pile factors of safety, strut-and-tie factors | Chapter 3, Table 6.3.10a (p. 750) |
| `plumbing.json` | Water demand (Table 8.5.1), storage, supply fixture units and Hunter's curve, velocity and pressure limits, drainage units, stacks, drains and vents, septic tank and soak pit, rainwater leaders, gutters and storm drains; SAEngine's pipe diameters, Hazen-Williams C, sleeves and wet-room fixtures | Part 8 Chapters 5-7 and Appendices O, R, S (pp. 1034-1215), Part 3 Sec 2.4.4 (p. 94) |

Each file names its clauses in `source` (the table), `sources` (single entries) and `$sources`
(for the registry). Some entries are SAEngine practice, not code clauses (bar sizes in use,
least practical spacings, assumed covers); their `sources` say so.

## Data, not formulas

The pack holds numbers. The formulas (the spectrum shape, Cs, the interaction surface, shear
strength, development lengths ...) stay in SAEngine's Python modules; a pack that needs a
different formula provides a trusted hook (see `docs/code-packs.md`).
