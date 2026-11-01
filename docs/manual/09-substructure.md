# Part 9: Substructure

Part 9 is where foundations are placed and designed: isolated, combined and strip footings,
pile caps with piles, rafts, and tie beams. The loads are the support reactions of the analysis
(8 FEM); the soil capacity comes from the soil report (Part 1) or from Project Settings.

File: `09 Substructure/substructure.json`. Open it with **9 Substructure** (or **Place Footings
in 9 Substructure** on the floor plan).

![The foundation plan of the sample after sizing](images/substructure.png)

## Layout

- **Views:** **Plan**, **Data**, **Results**.
- **Plan** (*Base level*): the grid, the columns, the boreholes and the foundations, coloured by
  utilisation (**below 0.9**, **0.9 to 1.0**, **above 1.0**). Click a column or a foundation to
  select it, **Shift+click** to add to the selection; **Delete** removes the selection; **Esc**
  discards a proposal or clears the selection.
- **Data:** tables of foundations (ID, type, columns, sizes, founding level, piles, utilisation),
  pile types and tie beams. Sizes in mm, levels and positions in m.
- **Properties panel:** the selected foundation, or (nothing selected) the counts, *Columns
  without one*, and the **Design** options.
- **Status line:** e.g. *6 foundations · 0 fail · max pressure 150 kPa (qa 150)*.

Toolbar (the labels follow the selection):

| Button | Does |
| --- | --- |
| **Add Footing under the Selected Columns** | an isolated footing; with several columns selected **Add Combined Footing under the n Selected Columns**; with nothing selected **Add Footings under the Columns without a Foundation** |
| **Add Pile Cap under the Selected Columns** | a pile cap (needs a pile type) |
| **Add Raft under the Selected Columns** | a raft round the columns |
| **Add Tie Beam between the Two Selected Foundations** | a tie beam |
| **Size Footings** | proposes sizes (below) |
| **Import Footings from the Building Model** | takes over footings drawn in an older building model |
| **Delete** | |
| ... | **Add Strip Footing along the Selected Columns**, **Add Pile Type**, **Select Columns without a Foundation**, **Check the Foundations Again** |

## Foundation properties

| Group | Fields (defaults) |
| --- | --- |
| General | Type (*Isolated footing, Combined footing, Strip footing, Pile cap, Raft*), Columns |
| Geometry | X, Y (m; default the columns' centroid), Rotation (°), Length, Width, Thickness (mm), Founding level (m; default ground − 1.5 m) |
| Section (isolated footings) | *Flat*, *Sloped* or *Stepped*; Edge thickness, Top length and Top width (the flat top or upper step round the column) |
| Piles (pile caps) | Pile type; layout *n piles at 3 diameters* with n = 2, 3, 4, 5, 6 or 9 |
| Material and reinforcement | Concrete, Bars, Cover (75 mm), Bottom x/y and Top x/y as `12@150` |
| Design (read only) | Utilisation, governing check, bearing pressure *p kPa (qa q)* |

New foundations: isolated 1.5 × 1.5 × 0.45 m; combined: the columns' extent + 750 mm each side,
600 mm thick; raft: the columns' extent + 1 m, 600 mm thick; bottom mesh 12@150 both ways.
New pile type: bored, 500 mm, 18 m, head fixed in the cap, no depth to fixity.

**Pile heads under lateral load:** each pile type has a *Head* (*Fixed in the cap* or *Free
(pinned)*) and a *Depth to fixity* (m below the head, from the geotechnical report). The cap's
horizontal force is shared equally by its piles; the head moment is H Lf / 2 for a fixed head
and H Lf at the depth to fixity for a free one. With a depth to fixity the pile section is
checked for axial force plus that moment and for shear, and fixed heads add their moments to the
cap's face moments. Empty: the piles are checked for axial force only. Lateral capacity by
Broms and by p-y springs are planned (chips under the pile types table).

**Design options** (nothing selected): pile capacity from the *Soil report (per layer)* or the
*BNBC SPT equations*; factors of safety for pile compression and uplift (default 2.5, BNBC Table
6.3.10a; both raised to 3.0 without a pile load test at the site, Secs 3.10.1.18 and 3.11.3) and for bearing
(default: the soil report's); *Pile load test at the site*; raft mesh size (500 mm); subgrade
modulus ks (default: the soil report's); *Raft springs*: *No tension (iterative)* (default: where
the raft lifts off, the soil carries nothing; a combination that does not converge in one step is
rerun in 10 load steps) or *Linear*.

**Slabs on grade:** the *Slabs on grade* table (Add Slab on Grade) gives each ground-bearing slab
its thickness, concrete, floor load, largest post or wheel load and its contact side, the
sub-base modulus k (empty: the design's subgrade modulus) and an optional crack-control mesh as
`8@200`. A new slab covers the columns' extent, 150 mm, 5 kPa.

**Excavations:** the *Excavations* table (Add Excavation) gives each excavation its bottom level,
how its sides are kept (sloped, stepped, shoring, sheet piles, retaining wall, rock cut or
vertical), the side slope (horizontal per vertical), the step height, the sheet piles' height
above ground, the cut-off toe, the design water table, and ticks for the guard rail, access
precluded, permanent, dewatered, piling nearby and erratic soil. Two tables under it list the
spoil, materials and machinery beside each excavation (their distance from the edge) and the
adjoining structures (distance, founding level, underpinned, another owner's, old and
sensitive). The checks are the active code pack's rules of excavation work (BNBC 2020 Part 6
Sec 3.12-3.13 and Part 7 Sec 3.3 by default): a geotechnical engineer's check beyond 6 m or in
soft soil, protection of sides 1.5 m deep or deeper (else 1:1 slopes, steps at most 1.5 m), the
1 m guard rail, the 1.5 × depth surcharge zone, the machinery setback, sheet piles 150 mm above
ground, underpinning of adjoining foundations at or above the bottom, nothing within 300 mm
under a footing, dewatering, the uplift of a clay layer at the base and the seepage gradient
round a cut-off (reported only). The notices, inspection and monitoring each excavation needs
are listed under the table. The *Formwork* table (Add Formwork Check) checks the slab formwork:
twice the wet concrete and workers' load on the sheeting and joists against the timber's
allowable stress, and the posts' height and diameter (Part 7 Sec 3.8, Table 7.3.1). Footings
founded in a fill layer of the soil report and the waterproofing of basements are noted in the
report, and the drawings' general notes carry the excavation, fill, waterproofing and formwork
rules. The design of the walls themselves (contiguous and secant pile walls, sheet pile walls,
struts, walers and anchors) stays planned: each chip opens its planned-feature page.

**Machine foundations:** the *Machine foundations* table (Add Machine Foundation) gives each
block under a generator, compressor, turbine or hammer its kind, base L × B, depth and founding
level, the machine's mass and operating speed, its unbalanced force (or rotating unbalance m·e,
or a hammer's impulse per blow), the maker's permissible amplitude if given, and where the
soil's spring comes from: E of the soil (Barkan; empty E or G uses the mean E of 1 Soil Report's
layers within B under the base, a G from a torsional test gives E = 2G(1 + μ)), the subgrade
modulus ks (empty: 1 Soil Report's at the nearest borehole), a plate load or resonance test, or
a given k; and the damping D (empty: from a test's decrement or hysteresis loop, else the low end
of the soils' range). The checks are the active code pack's machine foundation rules (BNBC 2020
Part 6 Sec 3.20 by default) by its lumped single-degree-of-freedom method: the impact rule, the
frequency ratio kept below 0.5 (low speed) or at least 2 (high speed), the amplitude at the
operating speed (and at resonance while a soft foundation starts) against the maker's value or
the code's, a hammer's 10 mm, the static pressure at most 80% of qa, the eccentricity at most 5%
and the ground water at least B/4 below the base. The participating soil mass (0 to the mass of
machine and block) and the printed forms of Barkan's relation are enveloped. The horizontal mode
is checked when its spring is entered. The plate load and resonance test data, the decrement or
hysteresis loop, the horizontal spring and force, the machine's offset from the centre, the
impact live load and the adjacent foundations' level are set in `substructure.json` (the table
shows the main inputs). Natural frequencies, frequency ratios and what else each
foundation needs are listed under the table.

## Sizing footings

**Size Footings** proposes isolated footings for the columns without a foundation (or for the
foundations and columns you selected): the width grows in 50 mm steps until bearing passes, then
the thickness from 300 mm for punching and one-way shear, then the bars. Footings that would
overlap are merged into combined footings. The proposal is drawn dashed (*Proposed sizes for 5
foundations*) with **Accept** and **Discard**; nothing is written until you accept.

It needs analysis results: *The sizing assistant proposed no foundations. Run the analysis
first: it sizes from the support reactions.*

## Where the loads and soil capacity come from

- **Loads:** the support reactions of `08 FEM/model.results`, reversed. With soil-spring supports,
  the fixed-base run is used. Without results: *there are no analysis results; run the analysis
  in 8 FEM first*.
- **Bearing combinations:** the service combinations of BNBC 2020 Part 6 2.7.2 — D, D + L + Lr,
  D + W, D + 0.75L + 0.75Lr + 0.75W, 0.6D + W, D + 0.7E, D + 0.75L + 0.75Lr + 0.525E, 0.6D + 0.7E,
  with W and E in ±X and ±Y. **Strength** checks use the factored combinations of Project
  Settings.
- **Allowable bearing qa** of a footing: the *Allowable bearing override qa* in Project Settings →
  Foundation if set; else the soil report: the lowest of the boreholes within 10 m (else the
  nearest), at the footing's width and depth. The check's note says which applied (*qa = 150 kPa,
  the override in Project Settings → Foundation; 1 Soil Report gives 153 kPa here (BH-1, 2.9 m
  away ...)*).

## Checks

| Foundation | Checks |
| --- | --- |
| Footings (isolated, combined, strip) | Bearing (service), Uplift (service), Resultant within the base (service), One-way shear X/Y, Punching at each column, Flexure X/Y bottom and top, Flexure between columns (top), Min. reinforcement. ACI 318-19 Ch. 13, 22 and 7; plain concrete per 14.5. |
| Pile caps | Pile load in compression and uplift, group capacity, block failure (clay), group settlement, pile spacing, cap edge beyond the piles, cover, flexure, one-way shear, punching at columns and round a pile; strut-and-tie for deep caps. |
| Pile sections | Axial + moment on the P-M surface of the circular section (ACI 318-19 22.4) and shear (22.5, bw = D, d = 0.8 D) under the head shear and moment; fully embedded, not a long column (BNBC 2020 Part 6 Sec 3.10.1.31). |
| Sloped and stepped footings | The same checks, each section with its own depth (ACI 318-19 13.2.7.3): one-way shear summed over strips across the section (at d from the column faces, at d from the step, along the slope), flexure with the compression face as wide as the top there, punching with the depth at d/2 and round the upper step; weight and BOQ from the true volume. |
| Slabs on grade | Flexural stress under the post load at the interior, an edge and a corner (Westergaard, Ioannides et al. 1985) against 0.62 √f'c / FS; punching of the plain slab under 1.6 P (ACI 14.5.5.1); mesh and joint spacing reported only. |
| Driven precast piles | Square of side B (perimeter 4B, area B²) in capacity and section checks; handling when lifted at two points (0.207 L) and pitched from one (0.293 L), × 1.5 impact, against φMn (cracking moment reported only); at least four bars and 1 % of the section; service stress 0.33 f'c (BNBC Sec 3.10.1.31). Piled rafts and group settlement by interaction factors are planned (chips under the pile types table). |
| Pile capacity | Soil-report method or BNBC SPT equations (6.3.21 to 6.3.34): Qult = Qs + Qb − W, uplift ≤ 0.7 Qs + W. |
| Rafts | OpenSees plate on compression-only springs: net contact pressure, maximum and differential settlement, angular distortion (BNBC Table 6.3.8), punching, slab flexure and shear (Wood-Armer). A contact pressure / settlement map can be shown on the plan. |
| Tie beams | Tie force (10 %, BNBC Part 6 1.8.5.2), size (BNBC 8.3.11.3), flexure and shear from settlement. |

The **Results** view (*Design checks — computed from the analysis reactions and the soil report;
not stored in the file*) shows tiles for the number checked and failing, the largest utilisation
and the largest bearing pressure; a table **By foundation** with the governing check and
combination; and **all checks** of the selected foundation with demand, capacity, utilisation,
combination and a note explaining the numbers. Then pile loads, contact pressure, pile capacity,
notes and the method.

![Results of the foundation checks](images/substructure-results.png)

**The checks run on the saved file**: save (Ctrl+S) to check your latest edits; the view warns
*These are the checks of the saved file. Save to check the latest edits.*

## Outputs

The foundations are measured in the BOQ, drawn on the *Foundation plan* and *Foundation details*
sheets of the drawings and reported in the design report. `09 Substructure/substructure.results/`
holds the summary.

## Not confirmed / limitations

- Not checked: sliding and overturning of footings, development lengths, rock sockets of piles.
- Walls on rafts are not supported yet (*walls on rafts: not yet*).
- Size Footings proposes isolated and combined footings only (not piles or rafts).
- Raft outlines and strip footing paths cannot be edited graphically.
- A per-foundation qa override, punching reinforcement and separate skin/end-bearing factors
  exist only in the JSON file.
