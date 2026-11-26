# Glossary: SAEngine terms and the ETABS / AutoCAD terms you know

| SAEngine | What it is | ETABS / SAP2000 | AutoCAD / drafting |
| --- | --- | --- | --- |
| **Project** | A folder with a `.saengine` manifest and one folder per part | Model file (`.EDB`) | Drawing set folder |
| **Part** | One of the eleven numbered steps in the Project sidebar | Menus Define / Assign / Analyze / Design | — |
| **Overview** | The page with the status of every part and the next step | — | — |
| **Stage bar** | Site & Soil › Model › Loads › Analysis › Design › Drawings · BOQ · Report on the Overview's ribbon, each with its state | — | — |
| **Ribbon** | Tabs and groups of buttons that follow the active window | Menus and toolbars | Ribbon |
| **Properties** | The panel on the right: the selection's properties, ready to edit | Assign / Display → Object info | Properties palette |
| **Tables** | The panel below the model: Members, Storeys, Progress | Display → Show Tables | Data extraction |
| **Code pack** | The design code as data (BNBC 2020 by default; 34 others) | Design code preferences | — |
| **Run All** | One click: derive, analyse, design, foundations, MEP checks, BOQ, report, drawings | Analyze → Run, then Design → Start Design/Check | — |
| **Soil Report** (Part 1) | Boreholes, strata, SPT, lab tests and the derived site class and bearing | Not in ETABS (site class typed in the seismic load) | — |
| **Project Settings** (Part 2) | Codes, occupancy, site, area loads, combinations, analysis options | Define → Load Patterns / Load Combinations, Auto Seismic/Wind, Preferences | — |
| **Code Values** | Every value of the code pack, each overridable per project | Auto seismic / wind load parameters, design preferences | — |
| **Area load** | A named set of live, floor finish and partition loads for floors or the roof | Shell uniform load sets | — |
| **Load case** D, SD, L, Lr, WX, WY, EX, EY, F, T | Created by SAEngine from the settings | Load patterns + load cases | — |
| **Load pattern** | A load case of your own (id, name, type, self-weight multiplier) | Define → Load Patterns | — |
| **Load combination** | Factors on the load cases (BNBC 2.7.3 by default) | Load combinations | — |
| **Materials** (Part 3) | Concrete, rebar, steel, masonry, mortar with their mix | Define → Material Properties | — |
| **Object type** (Part 4) | A section with its material, profile and bars | Frame section / Shell property / Concrete section | Block / member type |
| **Floor Plan** (Part 5) | The grids, storeys and members drawn storey by storey | Plan view drawing (Draw Columns, Beams, Floors) | Structural framing plan |
| **Storey** | A level with an elevation (top of floor) | Story | Level / floor |
| **Grid system** | A rotated, radial or angled grid beside the main grid | Grid systems (cartesian / cylindrical) | — |
| **Typical floor** (`similarTo`) | Storeys that repeat a master storey; edits apply to all | Similar stories / Master story | — |
| **Window / crossing window** | Drag left→right selects members inside; right→left selects members touched | Window / intersecting-line selection | Window / crossing selection |
| **Fill** | Places members on every grid intersection, segment or bay inside a window | Quick Draw Columns / Beams / Floors | — |
| **Copy to Stories** | Copies the selection to other storeys | Replicate → Story | Copy to layouts |
| **Underlay** | An architect's DXF shown greyed under the plan | DXF import as background | Xref |
| **Command line (:)** | Typed commands on the floor plan: CAD commands and member commands (`fill`, `copy`, `array`, `mirror`) | — | Command line |
| **Draft** | AutoCAD-style 2D drafting on each storey's plan | — | Drawing commands |
| **Building model / BIM** (Part 6) | The 3D model generated from the floor plan, with openings and stairs | The 3D model | 3D / IFC model |
| **Additions** | Openings, stairs, inclined members, end releases and point springs the building model adds to the plan | Openings, ramps, braces, releases | — |
| **End release** | An action at a member end released or on a spring | Assign → Frame → Releases/Partial Fixity | — |
| **Point spring** | Six springs (and a support) at a joint | Assign → Joint → Springs | — |
| **MEP** (Part 7) | Equipment loads, sleeves, shafts, plumbing, HVAC, electrical for the structure | Additional point/area loads, openings | MEP coordination drawing |
| **Analysis model** (`model.osmodel`, Part 8) | The finite-element model derived from the building model | The analysis model (meshed) | — |
| **Derive** | Create the analysis model from its sources | (automatic in ETABS when you run) | — |
| **Out of date / stale** | A derived file whose sources changed | Model unlocked / analysis results deleted | — |
| **Model and Analysis** (8 FEM) | The 3D view of the analysis model and its results | Model window with Display → Force/Stress Diagrams | — |
| **Design Utilisation** | Member colour by demand/capacity ratio | Concrete Frame Design → Display Design Info (P-M-M ratios) | — |
| **Required Steel** | The area of steel each member needs | Longitudinal reinforcing (As required) | — |
| **Design Reinforcement / design proposal** | Bars proposed for every object type and applied to Part 4 | Concrete Frame Design summary (bars are not written back) | Reinforcement detailing |
| **Section too small** | No practical bars can carry the demand: enlarge the section | *O/S* (over-stressed) message | — |
| **Steel short** | Bars entered, but less than required | Rebar % < required | — |
| **Seismic Design Category** | BNBC category from Z, site class and occupancy | Seismic design category | — |
| **Soil springs** | Supports on springs from the soil report | Point springs / area springs | — |
| **Substructure** (Part 9) | Footings, combined and strip footings, pile caps, piles, rafts, tie beams | SAFE / CSi Detail / hand design | Foundation layout |
| **Size Footings** | Proposes footing sizes from the reactions | SAFE design strips / hand sizing | — |
| **BOQ** (Part 10) | Quantities of concrete, steel by diameter, formwork, earthwork, cement bags, sand, stone chips | Material takeoff | Quantity takeoff |
| **Exports** (Part 11) | Report, drawings, IFC, DXF, CSV | Reports / Export | Plot / Publish |
| **Design report** | PDF calculations | Design report / tables | — |
| **Drawings / sheets S-101...** | DXF sheets plus a PDF set and a bar bending schedule | — | Sheet set / layouts |
| **Bar bending schedule (BBS)** | `bbs.csv` with BS 8666 shape codes | — | BBS |
| **Version** | A saved snapshot of the project | (save as a new file) | Revision |
| **Live co-editing** | Several engineers editing one part at once over the office network | — | Shared views |
| **Issued** | A version marked as submitted, e.g. *Rev A* | — | Issue / revision cloud |
| **.civil archive** | The whole project in one file | `.EDB` / `.e2k` transfer | eTransmit |
| **Developer mode** | Shows the underlying code-editor tools | — | — |

## Abbreviations

| | |
| --- | --- |
| BNBC | Bangladesh National Building Code 2020 |
| SPT, N, N60, (N1)60 | Standard penetration test blow count, corrected to 60 % energy, and to overburden |
| N̄, s̄u | Harmonic mean N and undrained shear strength over the top 30 m |
| qa | Allowable (net) bearing pressure |
| ks | Modulus of subgrade reaction |
| LPI | Liquefaction potential index |
| BTM | Bangladesh Transverse Mercator coordinates |
| R, Ω0, Cd | Response reduction factor, overstrength factor, deflection amplification factor |
| SD (load case) | Superimposed dead load; not to be confused with site class SD |
| RX, RY | Response spectrum cases |
| SDC | Seismic Design Category |
| IFC | Industry Foundation Classes (BIM exchange format) |
| DXF | AutoCAD drawing exchange format |
| cft | Cubic feet |
