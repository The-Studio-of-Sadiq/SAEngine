# Part 2: Project Settings

Project Settings hold the design code, occupancy, site, loads, load patterns, load
combinations and analysis options of the project. The design code is a **code pack**: BNBC 2020
by default, every value of which can be overridden. The floor plan, the building model and the
analysis read these settings. This chapter uses BNBC 2020; other packs show their own fields and
tables.

File: `02 Project Settings/project-settings.json`. Open it with **2 Project Settings** in the
sidebar, or one of its sub-windows (*Code, Occupancy, Construction, Site*; *Loads, Load Patterns
and Crane Runways*; *Seismic*; *Wind*; *Combinations and Analysis Model*; *Foundation*;
*Drawings and Detailing*; *Design Report*; *Code Values*).

![Project Settings: the sections, the form, and the code pack's tables in Properties](images/settings.png)

## Layout

- **Left of the window:** the sections (**Project**, **Occupancy**, **Construction**, **Site**,
  **Seismic**, **Wind**, **Area Loads**, **Load Patterns**, **Load Combinations**, **Crane
  Runways**, **Bridges and Special Structures**, **Analysis Model**, **Foundation**,
  **Drawings**, **Detailing**, **Design Report**, **IFC Export**, **Units**, **Code Values**).
  **Middle:** the form of the section.
- **Properties** (right): the design code pack and buttons for its tables (*Locations*, *Zone
  coefficients*, *Area loads*, *Combinations*, *Concrete*, ...). Click one to read the table.
- **Ribbon:** **Code & Packs › View** has the **Project type** (Building / Special Structure;
  changing it asks *Make this project a ...?* and keeps the old Part 5 folder) and the **Design
  code**. The other tabs follow the section: **Loads**, **Seismic & Wind**, **Foundation**,
  **Drawings & Report**, **Overrides** and the shared **Checks**, **Units** and **Audit**.
- Values you override are marked; hover a value for its source and clause.

## Sections and fields

### Project
Name, Project number, Client, Structural engineer, Address. They appear in the report and in
the drawing title block.

### Design code
The code pack is chosen in **Code & Packs › View › Design code** (and in the New Project
wizard). BNBC 2020 is built in; the Packages page installs the others. The pack sets the loads,
combinations, design clauses, least f′c and greatest fy, and the clause text the report cites.
With BNBC 2020 the concrete design follows BNBC 2020 Part 6 Chapter 6 (based on ACI 318) and the
steel design Part 6 Chapter 10 (based on AISC 360), in strength design.

### Construction
**Construction type** (fire resistance, Types I-A to II-E), the **Concrete aggregate**
(siliceous, carbonate, lightweight, brick chips), **Crossing beam bars at joints** (*Auto*: the
deeper beam, then the longer span keeps its bottom bars low; or *X beams main*, *Y beams main*,
*Same layer (flagged)*) and the **Fire separation distance**.

### Occupancy
- **Building use:** Residential (default), Office, Educational, Health care, Assembly, Retail,
  Industrial, Storage, Parking, Mixed use.
- **Occupancy category:** I to IV (BNBC Table 6.1.1), default II. It sets the importance
  factors and the allowable storey drift.

### Site
- **Location:** one of the code pack's towns (for BNBC 2020 the district towns, e.g. *Dhaka
  (zone 2, 65.7 m/s)*, *Chattogram (zone 3, 80 m/s)*, *Sylhet (zone 4, 61.1 m/s)*), which give
  the seismic zone and the basic wind speed, or *Custom (enter Z and V)*.
- **Site class source:** *From the soil report* (default; the softest class of the
  boreholes, see [Part 1](01-soil-report.md)) or *Entered*.
- **Site class:** SA to SE (default SD), used when entered or when there is no soil report.
- **Seismic zone coefficient Z** and **Basic wind speed**: optional overrides.

The site can also be filled from the soil report's map (**Apply to Project Settings**).

### Seismic
**Structural system** (BNBC Table 6.2.19), which sets R, Ω0 and Cd:

| System | R | Ω0 | Cd |
| --- | --- | --- | --- |
| RC special moment frame | 8 | 3 | 5.5 |
| RC intermediate moment frame (default) | 5 | 3 | 4.5 |
| RC ordinary moment frame | 3 | 3 | 2.5 |
| Building frame with RC special shear walls | 6 | 2.5 | 5 |
| Building frame with RC ordinary shear walls | 5 | 2.5 | 4.25 |
| Dual: RC special moment frame and special shear walls | 7 | 2.5 | 5.5 |
| Steel special moment frame | 8 | 3 | 5.5 |
| Steel ordinary moment frame | 3.5 | 3 | 3 |
| Steel special concentrically braced frame | 6 | 2 | 5 |

R, Ω0 and Cd can each be overridden.

### Wind
**Exposure** A (urban, suburban, wooded; default), B or C (BNBC Part 6 Sec 2.4.6.3).

### Area Loads
The floor loads of the project, in kN/m². Each area load has an ID, a name, a **use** (BNBC
Table 6.2.3, which sets the minimum live load), **live**, **Floor finish** and **partitions**.
**Floors** and **Roof** choose which area load applies to every floor and to the roof.

| Default | Use | Live | Finish | Partitions |
| --- | --- | --- | --- | --- |
| FL Floors | Residential | 2.0 | 1.2 | 1.0 |
| ST Stairs | Stairs | 4.8 | 1.2 | — |
| RF Roof | Roof | 1.0 | 1.5 | — |

A live load below the BNBC minimum for its use is flagged (*FL: live load 1.5 kN/m² is below the
BNBC 2020 minimum of 2.0 kN/m² for residential*).

> **Where loads come from.** Self-weight is computed from the object types and material
> densities. Floor finish and partitions become the superimposed dead case SD, the live load the
> case L (Lr on the roof). Non-structural walls become line loads on the beams under them. MEP
> equipment and tanks add their weights (Part 7). The floor plan editor has **no per-slab load
> entry**: one area load applies to all floors and one to the roof. A slab can carry its own area
> load (`areaLoad` in `floor-plan.json`, written by the importers when a model's slabs have
> different loads); there is no field for it in the editor in this version.

### Load Patterns
The project's own load cases, beside the built-in D (dead, with the self-weight), SD
(superimposed dead), L (live) and Lr (roof live): equipment, construction or special loads.
**Add Load Pattern** gives each an **Id** (its case code, e.g. *EQP*), a **Name**, a **Type**
(Dead, Superimposed dead, Live, Roof live, Wind, Seismic or Other) and a **Self-weight
multiplier**. Open it from this section, or **Loads › Patterns › Load Patterns...** on the
Settings, Floor Plan and FEM ribbons. *(after Alpha 3)*

![Project Settings › Load Patterns](images/load-patterns.png)

- Member and point loads (Floor Plan › Loads) and an area load's *Other load* can go to any
  pattern. Each pattern becomes its own case in the analysis.
- The type sets how a pattern combines: generated combinations give it the factor of its type
  (Dead takes D's, Live takes L's, and so on); an **Other** pattern gets only the factors you enter
  under **Factors on the Load Patterns** in Load Combinations.
- The self-weight multiplier adds load, not mass; the type sets the seismic weight share.
- Deleting a pattern that still has loads is refused. Renaming an id follows into the
  combinations and the area loads. Case codes the program forms itself (D, L, EX, ...) are
  refused as ids.

### Load Combinations
Each combination has a name and the factors of the cases **D, L, Lr, Wx, Wy, Ex, Ey, T, ST, CS,
F, H, FaX, FaY, S** (D also applies to SD; F follows D when left empty; hover a heading for its
meaning). **Factors on the Load Patterns** below adds a column per load pattern. **Generate
from BNBC 2020** replaces the combinations with the pack's set (with confirmation; undoable). New
projects get the BNBC 2020 strength combinations (Part 6, 2.7.3), expanded to ±X and ±Y for
wind and earthquake:

- 1.4D
- 1.2D + 1.6L + 0.5Lr
- 1.2D + 1.6Lr + 1.0L
- 1.2D + 1.6Lr + 0.8W
- 1.2D + 1.6W + 1.0L + 0.5Lr
- 1.2D + 1.0E + 1.0L
- 0.9D + 1.6W
- 0.9D + 1.0E

Combinations are formed from the case results (exact for the linear analysis). The service
combinations used for foundation bearing are built in by 9 Substructure.

### Analysis Model

| Field | Default | Meaning |
| --- | --- | --- |
| Slabs | Loads to beams | Slab loads go to the beams by the 45° rule as triangles and trapezoids (since 0.0.45; before, a uniform load of the same total), and the slabs are designed by BNBC's coefficient methods (Sec 6.5.8, 6.1.4.3); *Shells* models the slabs as shell elements |
| Floor diaphragm | Rigid | or flexible |
| Mesh size | 500 mm | for shells, and the largest beam element with slabs as loads to beams (1000 mm before version 0.0.44) |
| Mesh by slab span | On | shell slabs no coarser than their shorter span / 8 |
| Mesh convergence check | On | Run All solves the gravity cases again on a mesh twice as coarse and warns when a beam end moment changes by more than 5 % |
| Seismic mass | Lumped at the story levels | each node's weight to the nearest level; the lower half of the first storey (the supports' own share included) goes to the base and does not take part (as the usual analysis programs lump it); a node exactly half way between two levels gives half to each, so W hardly depends on the mesh. *Each node's own* is the convention before 0.0.44: the whole first storey counts with the first level. Since 0.0.44 it also counts the supports' own share (the lower half of the elements at the supports), which 0.0.43 left out, so its W no longer changes with the mesh |
| Mass source | D ×1, SD ×1, live load by the code | the code's live share is 25 %, 50 % for live loads above 3 kN/m² (BNBC 2020 Part 6 Sec 2.5.7.3, p. 628); extra masses per story |
| Wind torsional cases | On | WTX, WTY and the four design wind load cases of BNBC 2020 Part 6 Figure 6.2.9 (Sec 2.4.11.3) for every one-direction wind combination; off: Cases 1 and 3 |
| Live load arrangement | BNBC 6.1.12.2 | cases LP1, LP2 ...: live load on adjacent spans (each floor alone) and on alternate spans (a checkerboard over the floors) of the column grid, each gravity combination with live load checked with each; or adjacent spans on alternate floors (fewer cases, support moments up to about 2 % lower), alternate spans only, or off |
| Beam deflection limits | Partitions likely to be damaged | Table 6.6.2: l/360 (l/180 roofs) live load, l/480 after attachment; *not likely to be damaged*: l/240, and beams as deep as Table 6.6.1 asks are not computed; or off |
| Sustained share of the live load | 0.25 | for the long-term deflection (SAEngine assumption) |
| Eccentric static earthquake cases | On | EXP, EXN, EYP, EYN: EX and EY with the story masses shifted ±5 % across the force (Sec 2.5.7.6.2); with equivalent static design every E combination is checked with both |
| Period for the static base shear | Approximate Ta | or *From the modal analysis*, at most 1.4 Ta (Sec 2.5.7.2 (a), p. 627) and not below Ta |
| End offsets (rigid zones) | On | beams end at the column faces, columns at the beam soffit; the part inside the joint is rigid over the rigid zone factor |
| Rigid zone factor | 0.5 | 0: the whole length flexible (forces still read at the faces); 1: fully rigid |
| Columns at any angle | On | a column turned by an angle that is not a multiple of 90° is analysed and designed on its own axes |
| Response spectrum | On | adds the response-spectrum cases RX, RY (BNBC design spectrum, CQC, 5 % damping) |
| Section stiffness | Cracked (ACI) for lateral cases | |
| Second-order analysis | None (moment magnification) | or P-Delta analysis |
| Earthquake design forces | Response spectrum, scaled (BNBC 2.5.9.4) | or Equivalent static (EX, EY) |
| Orthogonal effects (100 % + 30 %) | Auto | by Seismic Design Category |
| Accidental torsion | On | ±5 % |
| Vertical earthquake component | On | |
| Redundancy factor ρ (drift) | 1.0 | |
| Construction sequence, time histories, pushover, temperature | Off | advanced analyses |
| Column supports | Fixed | or **Soil springs** from the soil report and 9 Substructure |

### Foundation
**Allowable bearing override qa** (kPa; empty: from the soil report), **Soil unit weight γ**
(18 kN/m³) and **Ground level** (0 mm).

### Units
**Unit system** SI or US customary, and for US customary the unit of each quantity (lengths and
levels in ft or in, member sizes in in or ft, forces in kip or lbf, stresses in ksi or psi, area
loads in psf or ksf, moments, line loads, unit weights, volumes, speeds). Only the display and the
inputs change.

### Drawings
Firm, Engineer, Drawn by, Checked by, Approved by, Project number, status (default *FOR
REVIEW*), revisions, **Sheet size** (A1, A2, A3; default A1), scales (plans 1:100, slab plans
1:50, elevations 1:50, details 1:25), development length (*simplified*), **Cut off beam top
bars** (on) and **BOQ reinforcement** (*Measured by the BOQ's rules* or *From the bar bending
schedule*).

## Code Values

**Code Values** lists every value of the code pack by table (factors, concrete, detailing,
serviceability, combinations, seismic, wind, foundations, fire, planning and more). Each shows
the pack's value in grey, its clause where the pack gives one, and a field for the project's
own value. Leave the field empty and the pack's value applies. Every run uses the overrides, and
the design report lists them. Values marked *generic default* are not given by the code pack
(SAEngine practice; hover the mark for its source).

The values that matter most for a building: seismic zone, Z (Table 6.2.14), basic wind speed V (Table 6.2.8), seismic and wind importance
factors (Tables 6.2.17 and 6.2.9), R, Ω0, Cd (Table 6.2.19), the site class (Table 6.2.13, *from
1 Soil Report* when used) and the wind exposure.

| Occupancy category | Seismic I | Wind I |
| --- | --- | --- |
| I | 1.00 | 0.87 |
| II | 1.00 | 1.00 |
| III | 1.25 | 1.15 |
| IV | 1.50 | 1.15 |

## Not confirmed

- Some field labels inside the advanced analysis options were read from the schema and may be
  worded slightly differently on screen.
- Per-slab area loads (*Floors* applies "unless the floor plan says otherwise") can only be set by
  the importers or in the JSON file; the floor plan shows no field for them.
