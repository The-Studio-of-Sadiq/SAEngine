# New Building from Grid, and modelling fast

A whole RC building in one step: give the grid spacings and the storeys, pick the structural
system and a few choices, and SAEngine writes the project (materials, object types, the floor plan
of every storey, typical floors, the foundations and the project settings). Then edit it with the
floor plan's bulk tools and the Members Table, run **Run All**, and let Design mode propose the
bars.

- [The wizard](#the-wizard)
- [From the command line](#from-the-command-line)
- [What is generated](#what-is-generated)
- [How the preliminary sizes are chosen](#how-the-preliminary-sizes-are-chosen)
- [Editing fast: selection, bulk tools, Members Table](#editing-fast-selection-bulk-tools-members-table)
- [RC design items added in this round](#rc-design-items-added-in-this-round)
- [Limits](#limits)

## The wizard

Open it from the start page (**New Building from Grid...**), from **≡ File → New Building from
Grid...**, from the sidebar's ≡ menu, or with *SAEngine: New Building from Grid...* in the command
palette.

| Field | What to type |
| --- | --- |
| Grid X, Grid Y | Bay spacings, left to right and bottom to top: `3×6000, 4500` or `6 m, 2×5000, 20 ft`. Units mm unless given (m, cm, ft). |
| Storeys | The number of storeys with the ground and typical heights, or every height (`4000, 9×3200`). |
| System | RC frame; RC frame + core walls (round the middle bay); flat slab (no beams). |
| Concrete, reinforcement | Materials of `03 Materials` (the default library). |
| Foundations | Isolated footings, one mat (raft), or none (add them in 09 Substructure). |
| Location, building use, occupancy category | BNBC 2020 location (seismic zone, basic wind speed), use (the live load of Table 6.2.3) and category (Table 6.1.1). The category is preselected from the use; confirm it. |

**Create** writes the project into the folder shown and opens it at the floor plan, with the
generator's notes. The notes say how each size was chosen: read them before the analysis.

## From the command line

```console
> saengine new-building office.json "D:\Projects"
```

`office.json` is either the generator's own spec:

```json
{
	"name": "Office Block",
	"gridsX": [6000, 6000, 6000],
	"gridsY": [5000, 5000],
	"storyCount": 6,
	"groundHeight": 3600,
	"typicalHeight": 3200,
	"system": "rcFrame",
	"concrete": "C27.6",
	"rebar": "B500DWR",
	"footing": "isolated",
	"location": "dhaka",
	"occupancy": "office",
	"occupancyCategory": "II"
}
```

or the document the wizard sends (`"schema": "saengine.newBuilding/1"`, grid lines and storeys
written out). Other fields: `stories` (`[{"name", "height"}]` instead of the count), `typical`
(default true), `coreBay` (`{"x": "B", "y": "2"}`, the lower-left grid lines of the core bay),
`live` (kN/m², never below the Table 6.2.3 value), `siteClass`, `allowableBearing` (kPa, default
100), `columnGroupStoreys` (default 3), `beamSpanDepth`, `minSlab`, `matOverhang`. See
[cli.md](cli.md#new-building).

The app calls the same code through the backend method `library/generateBuilding` (`{spec,
destParent, name?, overwrite?}`).

## What is generated

- `03 Materials`: the default library. `04 Objects`: square column types by storey group and
  position (interior, edge, corner), beam types by span, slab types by panel, wall types for the
  core, footing types. No bars: Design mode proposes them after the analysis.
- `05 Floor Plan`: the grids and storeys; a column at every grid intersection on every storey; a
  beam on every grid line of every suspended floor (none for a flat slab, none on the core's
  sides); a slab in every bay; the core walls; typical floors as `similarTo` families (a new family
  where the column types change).
- `06 BIM`: generated from the floor plan. `09 Substructure`: the footings or the mat (and the
  core's strips or raft).
- `02 Project Settings`: occupancy, live load, site, and the structural system the Seismic Design
  Category asks for (Table 6.2.18, 6.2.19).

## How the preliminary sizes are chosen

The sizes are **preliminary**: code minimums for deflection and the seismic proportioning rules of
BNBC 2020 where they apply, rules of thumb elsewhere. The analysis and Design mode check and size
every member for strength.

| Member | Rule |
| --- | --- |
| Beams | h = max(Table 6.6.1 minimum: l/16, l/18.5, l/21 for 0, 1, 2 continuous ends, × (0.4 + fy/700) when fy ≠ 420 MPa; span/15, a rule of thumb for frame beams under lateral load; 300 mm), rounded up to 25 mm; b = max(250 mm, 0.3 h) (Sec 8.3.4.1(c), (d)(i) for special moment frames). |
| Slabs with beams | Sec 6.2.5.3.3: h from α_fm (the rectangular beam section, without the slab flange: on the low side), Eq. 6.6.5 / 6.6.6; one-way panels (β > 2) by Table 6.6.1; at least 125 mm; rounded up to 25 mm. |
| Flat plates | Table 6.6.3 (no drop panels): ln/30 for exterior panels without edge beams, ln/33 interior, at fy 420 MPa (interpolated for others), ln the longest clear span; at least 125 mm (Sec 6.2.5.3.2); one thickness for every panel. Punching is checked in Design mode, which proposes studs or stirrups (below). |
| Columns | Square; Ag = k P / (0.4 f'c), P the service load from the tributary area of every floor above (slab, beams below it, finishes, partitions, live load, no live load reduction) plus the columns' own weight; k = 1.0 interior, 1.25 edge, 1.5 corner (bending allowance, rule of thumb); side rounded up to 50 mm, at least 300 mm in special moment frames (Sec 8.3.5.1(a)), else 250 mm; one type per 3 storeys and position, never larger above than below. |
| Core walls | 200 mm up to 10 storeys, 250 mm up to 20, 300 mm above (rule of thumb). Closed: add the door and slab openings. |
| Isolated footings | Square, side = √(1.1 P / qa) rounded up to 100 mm (P the service load at the base, +10 % for the footing and the soil on it); thickness max(450 mm, side/4). qa = 100 kPa unless given: enter the soil report's value. |
| Mat | The grid plus 1000 mm all round; thickness max(500 mm, 100 mm per storey). |
| Core foundation | Strip footings along the core walls (width from B² + L B = 1.1 P / qa, at least 600 mm), or one raft F-CORE when the strips would fill the core. Gravity only: the core's overturning under wind and earthquake is not included and usually governs. |
| System | From the Seismic Design Category: in Category D an RC frame becomes a special moment frame; a flat plate gets core walls and is the gravity system of a building frame with special walls. |
| Occupancy category | When not given: IV for health care, III for educational and assembly, II otherwise (Table 6.1.1, pp. 480-481, on the safe side). Confirm it. |

The verification pack's case DX4 checks that the base loads the columns are sized for add up to
the building's gravity load.

## Editing fast: selection, bulk tools, Members Table

In the floor plan (05 Floor Plan):

- **Window selection**: drag left to right to select what lies inside the window, right to left
  for what the window touches; Ctrl adds, Shift adds. **Ctrl+A** selects all on the storey;
  *Select by Type...* selects every member of a type.
- **Copy to Stories...**: copies the selection to the stories you pick (columns and walls rise
  from the storey below each). **Ctrl+C / Ctrl+V** copy and paste with a base point.
- **Fill** (toolbar): columns at every grid intersection, beams on every grid line, slabs in every
  bay of the storey or of a window.
- **Move, Mirror, Array**: on the command line (press `:`), e.g. `move 6000,0`, `mirror B move`,
  `array 6000,0 3`, `copy 0,5000`; a selection moves as one rigid group, and a member whose new place is taken
  stays where it was.
- **Delete** removes the selection.
- The selection and bulk tools are also in the command palette under *Floor Plan:* (Select All on
  Story, Select by Type, Copy Selection to Stories, Mirror Selection, Delete Selection).
- **Members Table** (the floor plan's ... menu, the sidebar's ≡ menu, or *SAEngine: Members
  Table*): every column, beam, wall and slab in one table; change types and stories of many rows at
  once; the edits are undoable and saved with Ctrl+S, and a type change on a typical floor applies
  to its whole family.

## RC design items added in this round

- **Flanged walls**: walls that meet at an L, T, C or X are designed as one flanged section
  (effective flange widths of Sec 8.3.6.5(b)), with strain-compatibility P-M, web shear and
  boundary elements; brick and undesigned walls touching them are left out, with a note.
- **Spandrels and coupling beams** without diagonal bars are designed as beams; flexural coupling
  beams of special walls take the special moment frame beam rules (their width rules count unless
  a lateral stability analysis is shown, Sec 8.3.6.7(a)).
- **Lintels** over the openings of masonry and partition walls: simply supported beams designed
  by hand (Sec 7.4.3.2), in the design report, the report's *Lintels* table and the bill of
  quantities.
- **Punching shear reinforcement**: where a flat slab or a footing fails punching with concrete
  alone, Design mode proposes headed shear studs (Sec 6.4.10.5) or stirrups (6.4.10.3): elements
  per line, lines, first line and spacing. *Apply* writes them on the slab type (04 Objects,
  *Punching reinforcement*) or the footing (09 Substructure); they are then checked, the section
  outside the last line included. Old files stay valid (the field is optional). Studs are measured
  in the bill of quantities.
- **Overstrength (Ω0) combinations** (Sec 2.5.5.6.1, 2.5.13.4): besides the beams and columns
  under discontinuous columns or walls, girders carrying transfer beams, walls under them and
  transfer slabs now take the Ω0 combinations; the report states Em's factors.

## Limits

- The generator handles regular rectangular grids, square columns and the default materials;
  sizes are for gravity only (see the table). In Seismic Design Category C or D the first note
  of the result is a warning: the earthquake usually governs the columns there, so expect Design
  mode to report some columns (corner and edge ones first) as "section too small" and enlarge
  those types after the first Run All. Pile caps and combined footings are not generated:
  add them in 09 Substructure.
- Lintel bars are not drawn on the wall detail sheet yet; they are in the design report.
- Punching studs of a slab type (or footing) are one layout for every column of it: the larger
  bar and elements per line, the shorter first line and spacing, and enough lines to reach as far
  from the face as the farthest-reaching column's own layout; Design mode then checks that layout
  at every column again (adding lines while one fails) before proposing it. When a column still
  fails, no layout is proposed and the notes name the column: give it its own type. When the
  studs or stirrups already given fail, a new layout is proposed from the demands.
