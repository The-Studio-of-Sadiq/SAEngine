# Reference: commands, command line and files

## Command Palette

Press **Ctrl+Shift+P** (or click the search box in the title bar) and type part of a command.
SAEngine commands are in the category **SAEngine**; floor-plan commands in **Floor Plan**.

| Command | Where else |
| --- | --- |
| Show Start Window | |
| New Project... | File menu |
| Open Project... | File menu |
| Open Sample Project... | start page |
| New Building from Grid... | start page, File, ≡ |
| Import from ETABS, STAAD or SAP2000... | start page, File, ≡ |
| Show Import Report | |
| Project Overview, Project Settings, Exports | ≡ |
| Versions, Save Version... | ≡, sidebar |
| Export Project..., Open Project Archive... | File, ≡ |
| Open Folder in File Explorer | ≡ |
| Run All | title bar |
| Run Analysis, Run Selected Analysis Cases..., Show Analysis Log | FEM toolbar |
| Design Reinforcement | FEM toolbar, Project menu |
| Print Design Report | File, Exports page |
| Export Bill of Quantities as CSV... | BOQ, Exports page |
| Open DXF in CAD... | File |
| Add Borehole to the Soil Report, Import Boreholes from CSV/Excel..., Save Borehole Template... | Soil Report toolbar |
| Size Footings, Import Footings from the Building Model into the Substructure | Substructure toolbar |
| Suggest Sleeves from the MEP Clashes | MEP toolbar |
| Floor Plan: Toggle Command Line, Select All on Story, Select by Type..., Copy Selection to Stories..., Mirror Selection..., Delete Selection, Members Table | floor plan |
| Check Python Runtime | |
| Toggle Developer Mode | Help |

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
| `saengine new-building <spec.json> <dest>` | New Building from Grid from a JSON spec |
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
