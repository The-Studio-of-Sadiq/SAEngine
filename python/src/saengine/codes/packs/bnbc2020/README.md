# BNBC 2020 code pack (`bnbc2020`)

The built-in pack of SAEngine: Bangladesh National Building Code 2020, Part 6 (Structural
Design), with Parts 3, 4 and 8 for the building services, and the standard steel sections. It
is the root pack other packs extend (`"extends": "bnbc2020"`), and the default of every project
(`codePack` in 02 Project Settings).

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
| `combinations.json` | Load cases; strength, temperature and gravity combinations; allowable stress combinations (Sec 2.7.3.2, for timber); D factors of the combinations with E | Sec 2.7.3.1 (p. 685) |
| `seismic.json` | Site classes and spectrum (S, TB, TC, TD), systems (R, Ω0, Cd, height limits, detailing level), Ct/m, SDC table, drift limits, RS scaling, torsion, Ev | Sec 2.5 (pp. 609-648) |
| `wind.json` | Exposures (α, zg), Kd, Kzt, G, Cp | Sec 2.4, Tables 6.2.11, 6.2.12 (pp. 602-603) |
| `materials.json` | εcu, Es, G of steel, f'c and fy limits of seismic members | Sec 8.3.3 (pp. 1089-1090) |
| `factors.json` | φ of concrete design | Sec 6.2.3 (pp. 897-898) |
| `concrete.json` | Bar sizes, spacings, steel ratios, minimum thickness tables, assumed covers, cracked stiffness, slenderness limits, wall steel | Chapter 6 (Tables 6.6.1, 6.6.3, pp. 900-902) |
| `detailing.json` | Special moment frames, joints, special walls, lintels | Sec 8.3 (pp. 1088-1122) |
| `steel.json` | φ, slenderness limits, An ≤ 0.85 Ag | Chapter 10 |
| `foundations.json` | Pile factors of safety, strut-and-tie factors (shared by pile caps and deep beams) | Chapter 3, Table 6.3.10a (p. 750); Sec 6.2.3.2 (p. 897) with ACI 318-19 Chapter 23 |
| `transfer.json` | Deep beams and transfer girders (when a beam is deep, Vn limit, web steel), corbels and brackets (shear friction limits, least steel, ties), diaphragm force bounds and collectors | Secs 6.4.6, 6.4.7, 2.5.5.6 (p. 625); ASCE 7-05 Sec 12.10.1.1 where BNBC is silent |
| `plumbing.json` | Water demand (Table 8.5.1), storage, supply fixture units and Hunter's curve, velocity and pressure limits, drainage units, stacks, drains and vents, septic tank and soak pit, rainwater leaders, gutters and storm drains; SAEngine's pipe diameters, Hazen-Williams C, sleeves and wet-room fixtures | Part 8 Chapters 5-7 and Appendices O, R, S (pp. 1034-1215), Part 3 Sec 2.4.4 (p. 94) |
| `hvac.json` | Outside design conditions of the stations (Table 8.2.2), inside conditions (Table 8.2.1), ventilation rates and occupancy (Table 8.2.3), lighting power density, glazing SHGC, overhangs and least window area; SAEngine's equipment, metabolic heat, supply air and design-day values where the code is silent | Part 8 Chapter 2 (pp. 859-916), Part 3 Chapter 4 (pp. 186-192) |
| `electrical.json` | Load densities (Table 8.1.17), load factor, substation and transformer rooms (Table 8.1.23), standby generator (Table 8.1.24), lifts, shafts and rising mains, earthing, lightning risk indices (Tables 8.1.27-8.1.28) and protection (Table 8.1.29); typical equipment data (marked) | Part 8 Chapter 1 (pp. 763-828), Sec 4.2.1 (pp. 982-983) |
| `fire.json` | Hazard classes, flows and durations (Table 4.4.1), standpipe and hose pressures, pump ratings (Table 4.4.2), sprinkler pipe schedules and spacing (Tables 4.4.5-4.4.7); the NFPA 10, 13, 20 values the code leaves out (marked from memory) and SAEngine's pipe and pump data | Part 4 Chapters 4-5 (pp. 321-355), Part 1 Chapter 2, Part 3 Sec 2.4.4 |
| `liveReduction.json` | Reduction of floor live loads by influence area: L = L0 (0.25 + 4.57/√(KLL AT)), least factors, uses not reduced, KLL by member | Sec 2.3.13 |
| `fireResistance.json` | Least slab and wall thickness, column size and the covers of slabs, beams and columns for 1-4 h fire resistance (siliceous aggregate; from memory, to be checked) | ACI 216.1-14 Tables 4.2, 4.3.1.1, 4.3.1.2, 4.5.1a, Sec 4.5.3; the ratings by BNBC 2020 Part 4 |
| `planning.json` | Planning rules of the plot for Dhaka (RAJUK): FAR and maximum ground coverage by use, plot size and road width (Tables 3(A)-3(F)), narrow roads and the road-width increment (Rule 51(9)-(11)), setbacks by plot size and height (Table 2, Rule 46), the road-centre distance (Rule 46(3)); transcribed from the gazette | Dhaka Mohanagar Imarat Nirman Bidhimala 2008; BNBC 2020 Part 3 Chapter 1 defers to the planning authority |
| `timber.json` | Permissible stress design of sawn timber: stresses by strength group (A, B, C) and location of use (inside, outside, wet), E, the column formulas (short, intermediate with K8, long), the depth factor K3, load duration factors and deflection limits (stresses from memory, to be checked) | Part 6 Chapter 11, with the provisions of IS 883:1994 it follows (section and page numbers of the BNBC text to be checked) |
| `masonry.json` | Masonry walls by allowable stress design (`method: "allowableStress"`): mortar grades M1-M6 (Table 6.7.1), the 50 % stresses without special inspection and prism tests, the one-third wind/earthquake increase, Fa, Fb, Ft, bond, Fv of beams and of plain and reinforced shear walls (Tables 6.7.2-6.7.4), Fs and Fsc, Em = 750 f'm ≤ 15,000 MPa, Es, G; effective height, length (Table 6.7.8) and thickness (stiffening coefficient), slenderness 20/12, stiffening walls (Table 6.7.9), basement and free-standing walls (Tables 6.7.10-6.7.11), least thicknesses, parapets, arches, corbels; reinforcement details (development, laps, hooks, bends Table 6.7.12, covers); the values of the strength design of slender walls and shear walls (Sec 7.7, Tables 6.7.13-6.7.14) and of the earthquake provisions (Sec 7.8) for the strength and seismic checks; a labelled f'm estimate from the unit strength (TMS 602 Tables 1-2, not BNBC, used only with 50 % stresses). Table 6.7.12's overlapping rows and Table 6.7.14's 72/48 are read conservatively (see the notes) | Part 6 Chapter 7 Sec 7.2-7.8 (pp. 1003-1039) |
| `siteInvestigation.json` | Number, pattern, spacing (60/30/15 and 45/30/15 m) and depth of the borings (2B-4B by L/B, 1.5 × building width, 6 m below the pile tip, rock cores); organic, expansive, collapsible, dispersive and soft soils; corrosivity scores and ratings; steel corrosion rates; corrosive-site limits; sulphate classes and chloride exposure of concrete in the ground; geo-hazards | Part 6 Secs 3.4.4-3.4.5, 3.5.3-3.5.8, 3.6.2, 3.10.1.29, 3.21, Tables 6.3.3, 6.3.4, 6.3.6a-b, Appendix E; Secs 5.5.1-5.5.2, Table 6.5.2 (pp. 702-846) |
| `steelSections.json` | Nominal dimensions of the steel shapes: IPE, HEA, HEB (EN 10365), ISMB, ISMC (IS 808, mean flange thickness), equal angles (EN 10056 / IS 808), SHS, RHS, CHS (EN 10219) and the walls rolled per size; the steel density. The properties are computed from them | The standard of each family, in its `source` |

Each file names its clauses in `source` (the table), `sources` (single entries) and `$sources`
(for the registry). Some entries are SAEngine practice, not code clauses (bar sizes in use,
least practical spacings, assumed covers); their `sources` say so.

## Data, not formulas

The pack holds numbers. The formulas (the spectrum shape, Cs, the interaction surface, shear
strength, development lengths ...) stay in SAEngine's Python modules; a pack that needs a
different formula provides a trusted hook (see `docs/code-packs.md`).
