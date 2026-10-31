# Revit link: the structural exchange file

SAEngine exchanges its analytical model and its designed reinforcement with Revit through one
neutral file, `saengine.structuralExchange/1`. SAEngine only reads and writes this file; it never
loads Revit's API. A separate Revit add-in (its own project, MIT licence) reads the file into a
Revit model and writes it back. SAEngine itself is AGPL and stays independent of Revit.

```text
SAEngine ── Export for Revit ──► <project>.exchange.json ──► add-in: Import into Revit
SAEngine ◄── Import Changes from Revit (preview, pick, apply) ◄── add-in: Export to SAEngine
```

## In the app

**11 Exports → Revit link**:

- **Export for Revit** writes `11 Exports/Revit/<project>.exchange.json`. It holds the levels,
  the grid lines, the materials and sections in use, the analytical elements of the building
  model and the designed bars (the 3D cages the drawings detail; generate the drawings first
  to include them).
- **Import Changes from Revit...** reads a file the add-in wrote back. It lists the changes made
  in Revit, each one ticked if SAEngine can take it:
  - levels moved or added;
  - grid lines moved or added;
  - columns, beams, walls, slabs and footings that were added, moved, deleted or given another
    type.

  Untick the ones you do not want, then apply. The changes go into the floor plan
  (05 Floor Plan), and a copy of the floor plan as it was is kept as
  `11 Exports/Revit/floor-plan.before-revit-import.json`. Rebuild the building model (06 BIM)
  to see them.

What SAEngine does not take back, and why:

| Change in Revit | Why not |
| --- | --- |
| Reinforcement | The bars come from the design and the detailing. Change the reinforcement of the object types (04 Objects), or design again. |
| Braces and other building-model additions | They belong to 06 BIM. Edit them there. |
| Sloped beams, slanted columns and sloped slabs | The floor plan holds level and vertical members. |
| A type that no object type matches (by id, name or size) | Add the object type in 04 Objects first. |
| Deleted levels and grid lines | Remove them in the floor plan, together with what stands on them. |
| Special-structure members and areas | They belong to the structural model. |

When a grid line moves, the members on it stay where they are, unless their own changes are
applied too. Their offsets from the grid line change instead.

The ids the two programs gave each element are kept in `11 Exports/Revit/revit-link.json`.

## The file

The file is UTF-8 JSON. Lengths are in mm, angles in degrees, stresses in MPa and densities in
kg/m³. Coordinates are model coordinates: x and y in plan, z the elevation.

```jsonc
{
  "schema": "saengine.structuralExchange/1",
  "origin": { "application": "SAEngine", "version": "0.0.60", "written": "2026-11-01T10:00:00Z" },
  "project": { "name": "Office", "type": "building" },
  "units": { "length": "mm", "angle": "deg", "stress": "MPa", "density": "kg/m3" },
  "scope": ["column", "beam", "wall", "slab", "footing", "brace", "member", "area"],
  "levels": [ { "id": "L1", "name": "Ground", "elevation": 0, "revitId": "…" } ],
  "grids": [ { "id": "x:A", "name": "A", "axis": "x", "position": 0, "start": [0, 0], "end": [0, 12000] } ],
  "materials": [ { "id": "C25", "name": "Concrete 25", "category": "concrete", "fc": 25, "E": 23500 } ],
  "sections": [ { "id": "C400x400", "name": "Column 400", "kind": "column", "material": "C25",
                  "profile": { "shape": "rectangle", "xDim": 400, "yDim": 400 }, "reinforcement": { } } ],
  "elements": [ … ],
  "rebar": [ … ],
  "notes": [ "…" ]
}
```

### levels and grids

- **Levels** are the stories, by elevation.
- **Grid lines** are straight lines in plan. `axis` `"x"` is a line at a constant x (it runs along
  y), and `position` is that x.
- A file written back may give `start` and `end` only. SAEngine reads the axis from them, and a
  slanted grid line is reported but not applied.

### sections

There is one section per object type of 04 Objects in use. Its `id` is the object type's id, and
the add-in maps it to a Revit family type by `name`. Frames carry SAEngine's `profile` (`rectangle`,
`circle`, `I`, `T`, `L`, `U`, hollow sections, or `designed`). Slabs and walls carry `thickness`.
Footings and pile caps carry `length`, `width` and `thickness`.

### elements

Every element has `id` (the SAEngine id), `kind`, `section` and `owner`:

- `owner` `"floorPlan"` means the element can take changes back from Revit;
- `owner` `"buildingModel"` means it is reported only.

| kind | geometry |
| --- | --- |
| `column` | `curve`: bottom then top point; `rotation`; `baseLevel`, `topLevel` |
| `beam` | `curve`: start and end at the top of the beam (`reference: "top"`); `level` |
| `wall` | `curve`: the location line at the bottom; `bottom`, `top`; `baseLevel`, `topLevel` |
| `slab` | `outline`: the corners at the top of the slab; `openings`: loops of corners; `level` |
| `footing` | `point`: the centre at the top of the footing; `rotation`; `level` |
| `brace` | `curve`: start and end |
| `member`, `area` | members and areas of special structures: `curve` or `outline` (+ `openings`) |

`revitId` is the Revit element's unique id once the add-in has linked it. The add-in keeps the
SAEngine `id` on the Revit element (in a shared parameter) and writes it back unchanged. It writes
elements created in Revit with no `id` and with their `revitId`.

`scope` lists the kinds the file covers. An element of a kind in `scope` that is missing from a
file written back counts as deleted in Revit. The add-in narrows `scope` when it exports only some
categories.

### rebar

There is one entry per bar mark of a beam or a column:

- `host`: the element the bars belong to;
- `mark`, `role`, `dia`, `shape`;
- `length`: the developed length of one bar;
- `count`, `transverse`, `material`;
- `lines`: one polyline per physical bar, along its centreline.

SAEngine writes the bars and never reads them back.
