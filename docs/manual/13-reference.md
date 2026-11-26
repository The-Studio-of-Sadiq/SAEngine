# Reference: commands, command line and files

## Command search

Press **Ctrl+Shift+P** (or click *Search or run a command* in the title bar) and type part of a
command. SAEngine commands are in the category **SAEngine**; floor-plan commands in **Floor
Plan**. Every ribbon button is a command too.

| Command | Where else |
| --- | --- |
| New Project... | Start page, ≡ › File, Home › Project › New |
| Open Project... | Start page, ≡ › File, Home › Project › Open |
| Open Sample Project... | Start page |
| Import from ETABS, STAAD or SAP2000... | Start page, ≡ › File |
| Show Import Report | |
| Project Overview | sidebar, Home › Project › Overview |
| Versions, Save Version... | sidebar (clock icon), Home › Workspace › Collaborate, ≡ › File |
| Export Project..., Open Project Archive... | ≡ › File, Exports › Output |
| Run All | title bar, F5, FEM › Analyze › Solver |
| Run Analysis, Run Selected Analysis Cases..., Show Analysis Log | FEM › Analyze › Solver, Mesh & View |
| Design Reinforcement | 8 FEM › Design Reinforcement, FEM › Analyze › Analysis Model |
| End Releases..., Point Spring... | FEM › Analyze › Assign |
| Load Patterns... | Settings, Floor Plan and FEM › Loads ribbons |
| Print Design Report, Export Design Report to Word, Configure Design Report... | ≡ › File, Exports page |
| Export Bill of Quantities as CSV... | BOQ › Quantities › Export, Exports page |
| Open DXF in CAD... | ≡ › File |
| Add Borehole to the Soil Report, Import Boreholes from CSV, Excel, AGS4 or DIGGS..., Save Borehole Template... | Soil Report › Investigation › Boreholes |
| Size Footings, Import Footings from the Building Model into the Substructure | Substructure › Shallow & Raft › Sizing |
| Suggest Sleeves from the MEP Clashes | MEP › Coordination › Clashes |
| Copy Selection to Stories..., Grid Systems..., Select All on Story, Select by Type..., Mirror Selection..., Delete Selection | Floor Plan › Structure › Edit |
| Start Live Co-Editing | Home › Workspace › Collaborate › Live Co-Editing |
| Check Python Runtime | |
| User Manual, Report a Bug..., Send Feedback..., Toggle Developer Mode | ≡ › Help |

## The `saengine` command line

The installer can add `saengine` to the PATH (an opt-in task). Every step of the app can run
without the window, for scripts and checking. Full description: [docs/cli.md](../cli.md).

| Command | Does |
| --- | --- |
| `saengine validate <project>` | checks every part file |
| `saengine status <project>` | the status of every part, as in the sidebar |
| `saengine run-all <project> [--steps ...]` | Run All (steps: derive analysis ssi design substructure mep boq report drawings) |
| `saengine derive`, `analyse`, `design`, `report <project>` | single steps |
| `saengine check <project>` | exits with 1 when a check fails |
| `saengine export <project> --format ifc\|dxf\|csv\|pdf\|drawings\|civil` | the exports |
| `saengine import <file> <dest> [--name NAME]` | `.civil`, `.e2k`, `.std`, `.s2k` |
| `saengine new-building <spec.json> <dest>` | a building from the grid (as New Project) from a JSON spec |
| `saengine versions status\|list\|save\|diff\|restore\|issue` | versions |
| `saengine verify [--pdf]` | runs the verification benchmarks against closed-form and published references |

`--json` writes one JSON document; `-q` hides the progress.

## Files of a project

| File | Written by |
| --- | --- |
| `<name>.saengine` | New Project |
| `01 Soil Report/soil-report.json` | Soil Report editor |
| `02 Project Settings/project-settings.json` | Project Settings editor (and the soil map's *Apply*) |
| `03 Materials/materials.json` | Materials editor |
| `04 Objects/objects.json` | Object Types editor, Design Reinforcement |
| `05 Floor Plan/floor-plan.json`, `Underlays/*.dxf` | Floor Plan editor |
| `06 BIM/bim.json` | Build from Floor Plan, Additions |
| `07 MEP/mep.json`, `IFC/`, `mep.results/` | MEP editor |
| `08 FEM/model.osmodel`, `model.results/` | Derive, Run Analysis, design checks |
| `09 Substructure/substructure.json`, `substructure.results/` | Substructure editor |
| `10 BOQ/boq.json` | Measure / Update |
| `11 Exports/report.pdf`, `Drawings/`, `IFC/`, `Floor Plan/`, `boq.csv` | Exports |
| `import-report.json` | the importers |

All part files are JSON. *Reopen Editor With... → Text Editor* shows the text of any of them;
edit it only if you know the format.

## Verification

`saengine verify` runs SAEngine's verification pack: benchmark problems compared with an
independent reference (closed-form solutions, published benchmarks, hand calculations) within a
stated tolerance (1 % for closed-form frames, 0.5 % for design hand calculations, ...). With
`--pdf` it writes a verification manual. See [docs/verification](../verification/README.md).
