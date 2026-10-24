# The `saengine` command line

`saengine` does what the app does, without the app: it validates a project, runs **Run All**
(derive the analysis model, analyse, design the members and the foundations, check the MEP
services, measure the bill of quantities, build the report), exports the drawings and models,
archives a project as a `.civil` file and keeps its versions. It reads and writes the same files
as the app, in the same formats: after `saengine run-all`, the app's part list shows the results
as current, and the app's Run All finds nothing out of date.

It is the tool for scripts, batch runs and continuous integration: `saengine check` exits with
code 1 when a design, foundation or MEP check fails, so a pull request that breaks a check can be
stopped before it is merged.

- [Install and PATH](#install-and-path)
- [Commands](#commands)
- [Run All, step by step](#run-all-step-by-step)
- [JSON output](#json-output)
- [Exit codes](#exit-codes)
- [In continuous integration](#in-continuous-integration)
- [What differs from the app](#what-differs-from-the-app)

## Install and PATH

**With the SAEngine installer** (Windows): the setup's task *Add the saengine command to PATH*
puts `%LOCALAPPDATA%\Programs\SAEngine\bin` on the user `PATH`. The task is opt-in (not ticked
by default): tick it in the setup's *Select Additional Tasks* page, or pass
`/MERGETASKS="addtopath"` to an unattended install. Then open a new terminal and run:

```console
> saengine --version
saengine 0.1.0 (opensees-studio 0.0.1, openseespy 3.8.0.0, Python 3.12.10)
```

`bin\saengine.cmd` (and `bin/saengine` for Git Bash) runs the Python bundled with the app,
isolated from any other Python on the machine:

```bat
"%~dp0..\resources\python\python.exe" -I -m saengine.cli %*
```

The program that opens a folder in the SAEngine window is `bin\saengine-app.cmd`. Without the
`PATH` entry, call `"%LOCALAPPDATA%\Programs\SAEngine\bin\saengine.cmd"`.

**From the source** (developers): with the repository's virtual environment (see the
repository README), `pip install -e python` installs the console script `saengine`; without it,
`python -m saengine.cli` is the same command.

EnergyPlus is not needed: Run All never starts it (see [HVAC loads](#hvac-loads)). The
installed app's bundled EnergyPlus is found by itself; elsewhere set `SAENGINE_ENERGYPLUS` to
the EnergyPlus folder.

## Commands

Every command that takes a `<project>` accepts the project folder or its `.saengine` file.
Results go to **stdout** (text, or one JSON document with `--json`); progress goes to
**stderr** (`-q` silences it). The examples run on the sample project the app opens from
*Help > Open Sample Project* (a copy of `workbench/resources/saengine/samples/Sample Frame`).

| Command | What it does |
| --- | --- |
| `saengine --version` | The versions of SAEngine, OpenSees Studio, OpenSeesPy and Python. |
| `saengine validate <project>` | Checks every part as its editor does. |
| `saengine run-all <project> [--steps STEP ...]` | Run All, or some of its steps. |
| `saengine derive <project>` | Derives `08 FEM/model.osmodel` when it is out of date. |
| `saengine analyse <project>` (or `analyze`) | Derives if needed, runs every analysis case (and the fixed-base run on soil springs). |
| `saengine design <project>` | The member design checks and the foundation design, from the last analysis. |
| `saengine report <project>` | Builds `11 Exports/report.pdf`. |
| `saengine check <project>` | The checks for CI: Run All without the bill and the report. |
| `saengine status <project>` | The status of each part, as the app's part list shows it. |
| `saengine export <project> --format ifc\|dxf\|csv\|pdf\|drawings\|civil [--out PATH] [--size A1\|A2\|A3]` | Writes an export (`drawings`: the structural drawing set), or a `.civil` archive. |
| `saengine import <file.civil> <dest>` | Extracts an archive into `<dest>/<project name>`. |
| `saengine import <file.e2k\|.std\|.s2k> <dest>` | A new project from an ETABS, STAAD.Pro or SAP2000 model (see [import.md](import.md)). |
| `saengine new-building <spec.json> <dest> [--name NAME]` | A new building project generated from its grids and storeys (see [new-building.md](new-building.md)). |
| `saengine versions status\|list\|save\|diff\|restore\|issue <project> ...` | The project's version history. |
| `saengine verify [--out DIR] [--pdf]` | Runs SAEngine's verification pack. |

### validate

```console
> saengine validate "Sample Frame"
placeholder  01 Soil Report/soil-report.json
ok           02 Project Settings/project-settings.json
ok           03 Materials/materials.json
ok           04 Objects/objects.json
ok           05 Floor Plan/floor-plan.json
ok           06 BIM/bim.json
ok           07 MEP/mep.json
missing      08 FEM/model.osmodel
ok           09 Substructure/substructure.json
ok           10 BOQ/boq.json

No errors.
```

Each part's main file is read as JSON, validated against its schema and checked against the
rules the schema cannot express, the same checks the editors show as problems: duplicate ids,
references between entries and between parts (an object type's material, a member's object
type, a foundation's column, an opening's host), the settings' code minimums. A part's state is
`ok`, `warnings` (only warnings: the soil report's "there are no SPT records"), `problems` (an
error among them: exit code 1), `placeholder` (not started) or `missing` (an optional part
without its file). `08 FEM/model.osmodel`, once derived, is checked with OpenSees Studio's
schema.

### run-all

```console
> saengine run-all "Sample Frame"
[1/9] analysis model
[2/9] analysis
[2/9] analysis: D: Dead (self-weight) (Static)
...
[9/9] drawings
ok       analysis model: Derived 193 nodes and 195 elements; base shear 103.9 kN, seismic weight 824.8 kN.
ok       analysis: Analysis complete: 12 case(s).
skipped  fixed-base run for the soil springs: The supports are not soil springs.
ok       design checks: 0 pass, 15 fail; steel short in 16 element(s)
ok       foundation design: foundations 0 pass, 1 fail
ok       MEP coordination, plumbing, HVAC and electrical checks: MEP: failing openings 0, open clashes 0 · plumbing: failing checks 2, floors below the minimum pressure 1 · HVAC: failing checks 2, openings to add 0 · electrical: failing checks 0, openings to add 1
ok       bill of quantities: BOQ updated
ok       report: report written
skipped  drawings: drawings not generated yet (11 Exports, Drawings; or --steps drawings)

  1 Soil Report        done        3 boreholes
  ...
  8 FEM                failed      15 fail (review the failing members)
  9 Substructure       failed      1 fail (review the failing foundations)
  10 BOQ               done        measured
  11 Exports           done        report 19 Oct

Done: 0 pass, 15 fail · foundations 0 pass, 1 fail · MEP: ... · model derived · BOQ updated · report written

Failing checks:
  8 FEM: 15 of 15 members fail the design checks (max utilisation 3.247, C1)
  ...
```

The sample is an RC intermediate moment frame in Seismic Design Category D, where BNBC 2020
Part 6 Sec 8.3.2 asks for special moment frame detailing: its beams and columns fail the
seismic detailing checks (hoop spacing, confinement, cross ties, capacity shear; `Detailing:`
checks) as well as a few strength checks. Design Reinforcement proposes bars with hoop zones
that resolve them; the system itself (not permitted in Category D) and the concrete grade
(f'c below 21 MPa, Sec 8.3.3.3) stay as project-level findings in the report's Seismic
detailing chapter.

`--steps` runs some steps only, always in Run All's order: `saengine run-all "Sample Frame"
--steps design substructure` (or `--steps design,substructure`; the project may also come after
the steps, `run-all --steps design substructure "Sample Frame"`; a folder name with a comma, such
as `"Smith, Dhaka"`, is kept whole. Only a folder named like a step, or like a comma-separated
list of steps, must come first). The steps are `derive`,
`analysis`, `ssi`, `design`, `substructure`, `mep`, `boq`, `report` and `drawings`; see
[Run All, step by step](#run-all-step-by-step). As in the app, a step that cannot be done (an
invalid building model, a solver failure) stops the run: its status is `failed`, the steps
after it are `skipped` with the message "Not run: Run All stopped at ...", and the exit code is
3. Failing checks do not stop the run: they are results (exit code 1).

The whole sample takes about three minutes the first time (the tank designs of the plumbing
take most of the MEP step) and less afterwards.

The last step, `drawings`, keeps the structural drawings of `11 Exports/Drawings` current: when a
drawing set was generated before (the Exports page's Generate Drawings, or `export --format
drawings`) and is out of date, Run All draws it again with the design checks of the run;
otherwise it is skipped ("drawings not generated yet" or "drawings up to date"). Drawing a set
takes from seconds (the sample: about 15 s) to minutes for a large building, so the first set is
the engineer's choice. `--steps drawings` always draws it.

### derive, analyse, design, report

Shorthands for `run-all --steps`:

| Command | Steps |
| --- | --- |
| `saengine derive` | `derive` |
| `saengine analyse` | `derive analysis ssi` (the derivation does nothing when the model is current) |
| `saengine design` | `design substructure` |
| `saengine report` | `report` |

### check

```console
> saengine check "Sample Frame" --json > check.json
> echo %ERRORLEVEL%
1
```

`check` runs Run All's checks, `derive analysis ssi design substructure mep`, and leaves out the
bill of quantities and the report: it writes the computed files (the derived model, the results,
the summaries the part list reads; `.gitignore`d by Versions and left out of `.civil` archives)
but no deliverable and no part file. (One exception, as in the app: a project from before Part 9
whose `09 Substructure/substructure.json` is still the placeholder gets the building model's
footings moved there once.) It exits with 1 when a member, a foundation, an opening, a plumbing,
HVAC or electrical check fails or a floor is below the minimum water pressure, with every failure
in `failures`; open clashes, partly checked openings, openings still to add and estimated HVAC
loads are `warnings` and do not fail the check.

### status

```console
> saengine status "Sample Frame"
  1 Soil Report        notStarted  not started (enter the soil report)
  2 Project Settings   done
  ...
  8 FEM                notStarted  not derived (derive the analysis model)
  ...
Next: 8 FEM: derive the analysis model
```

The rules are the app's (`partStatus.ts`): `notStarted`, `inProgress`, `done`, `stale` (an
upstream part changed since), `failed` (a check fails) or `error` (an invalid file), the few
words the part list shows and the hint.

### export

```console
> saengine export "Sample Frame" --format ifc
Wrote ...\Sample Frame\11 Exports\IFC\Sample Frame.ifc
> saengine export "Sample Frame" --format dxf
Wrote ...\Sample Frame\11 Exports\Floor Plan\BASE Base.dxf
Wrote ...\Sample Frame\11 Exports\Floor Plan\L1 Level 1.dxf
...
> saengine export "Sample Frame" --format csv
Wrote ...\Sample Frame\11 Exports\boq.csv
> saengine export "Sample Frame" --format pdf
Wrote ...\Sample Frame\11 Exports\report.pdf
> saengine export "Sample Frame" --format drawings
Wrote ...\Sample Frame\11 Exports\Drawings\S-101 General notes.dxf
...
Wrote ...\Sample Frame\11 Exports\Drawings\drawings.pdf
Wrote ...\Sample Frame\11 Exports\Drawings\bbs.csv
...
> saengine export "Sample Frame" --format civil --out "Sample Frame.civil"
Wrote Sample Frame.civil (19 files, 379162 bytes).
```

The files go where the Exports page puts them: the IFC of the building model in
`11 Exports/IFC/<project>.ifc`, the structural plan of every story in
`11 Exports/Floor Plan/<story id> <story name>.dxf` (layers `S-GRID`, `S-COLS`, `S-BEAM`, ...,
as the app draws them), the bill of quantities in `11 Exports/boq.csv` and the design report in
`11 Exports/report.pdf`. The structural drawings (`drawings`) go to `11 Exports/Drawings`: one
DXF per sheet for LibreCAD (general notes, foundation plan, framing and slab reinforcement
plans per level, column schedule, beam elevations, footing, wall and stair details, the bar
bending schedule), all sheets in `drawings.pdf`, PNG previews in `previews/`, the bar bending
schedule as `bbs.csv` and the record `drawings.json` (the stamps of the files they were drawn
from, so the app shows when they are out of date). Their title block, sheet size and scales are
Project Settings' Drawings section; `--size` overrides the sheet size. `--out` writes elsewhere
(a folder for `dxf`; for `drawings`, the set is generated in the project and copied there).
With analysis results, the drawings use the design checks of the run, kept in
`08 FEM/model.results/design-report.json` (Run All's design step writes it; else the first
generation makes it, about a minute on the sample). Detailing checks that are not met (bars
anchored too short) and members failing the design checks are printed on standard error as
"to resolve before issue", listed on the Exports page and written on the general notes sheet
as a "NOT FOR CONSTRUCTION until these are resolved" note; the set is still written. A
`.civil` archive
leaves out the computed caches unless `--include-results`, and the version history unless
`--include-versions`; it records each part's status.

### import

```console
> saengine import "Sample Frame.civil" "D:\Projects"
Imported Sample Frame into D:\Projects\Sample Frame (19 files).
```

`<dest>` is the folder the project folder is created in. The archive is checked first (format,
paths, sizes, checksums); a refused archive leaves nothing behind (exit 3). An existing,
non-empty project folder is refused unless `--overwrite`; `--name` gives the project another
name.

An ETABS `.e2k`, STAAD.Pro `.std` or SAP2000 `.s2k` file creates a new project there instead,
and prints the import report: what was imported, approximated and skipped, and the loads not
carried over ([import.md](import.md)). `--json`: `{import: {root, name, format, report,
problems, files}}`.

### new-building

```console
> saengine new-building office.json "D:\Projects"
Generated Office Block into D:\Projects\Office Block.
  72 columns, 102 beams, 36 slabs, 12 foundations
  note: Seismic Design Category D (zone 2, site class SD, occupancy category II); system RC special moment frame.
  ...
```

`<spec.json>` is the generator's spec (`{"name", "gridsX", "gridsY", "storyCount",
"typicalHeight", "groundHeight", "system", "footing", "location", "occupancy", ...}`, lengths in
mm) or the document the app's *New Building from Grid* wizard sends (`schema:
"saengine.newBuilding/1"`). The project is written into `<dest>/<name>`; a folder that holds files
already is refused (exit 3) unless `--overwrite`. Every note says how a size was chosen: the
sizes are preliminary (see [new-building.md](new-building.md)). `--json`: `{newBuilding: {root,
name, notes, summary, settingsPatch, files}}`.

### versions

```console
> saengine versions save "Sample Frame" -m "Beam B5 deepened" --author "A. Rahman <rahman@example.com>"
Saved v3 1a2b3c4: Beam B5 deepened
> saengine versions list "Sample Frame"
v3  1a2b3c4  2026-10-19T10:12:00+06:00  A. Rahman  Beam B5 deepened
v2  9f8e7d6  2026-10-18T16:40:00+06:00  A. Rahman  Soil report entered  [Tender]
v1  5c4b3a2  2026-10-17T09:05:00+06:00  A. Rahman  First
> saengine versions diff "Sample Frame" v2
Floor Plan: 1 change: Beam B5 changed
  changed  Beam B5: section B300x500 → B300x600
> saengine versions restore "Sample Frame" v2 --parts floorPlan
> saengine versions issue "Sample Frame" v3 "Issued for construction"
```

A version is named as `list` shows it: `v3` (or `3`) is the third version saved. A commit id
(`1a2b3c4`), `HEAD`, an issue tag (`issued/tender`) and git's `~N` suffixes (`v3~1`, `HEAD~2`)
work too; a plain number of four or more digits is taken as a commit id.

`status` lists the parts changed since the last version; `diff [FROM [TO]]` compares the last
version (or `FROM`) with the current files (or `TO`), in an engineer's words; `restore` brings
back some parts (`--parts`, part ids) or all of a version as a new version, after saving any
unsaved changes as their own version (`--no-commit` leaves the restore unsaved). The history is
an ordinary git repository in the project folder.

### verify

```console
> saengine verify --out verification --pdf
```

Runs the verification pack (closed-form and published references, see
`docs/verification/README.md`) into `--out`, with the Verification Manual PDF on `--pdf`;
`--fast` skips the slow cases, `--cases ID ...` runs some. Exit code 1 when a case is outside
its tolerance. With `--json` the pack's table goes to stderr (nowhere with `-q`) and stdout is
the JSON document.

## Run All, step by step

The steps are the app's Run All (`saengine.runAll`), in its order, writing the same files:

| Step | What it does | Writes |
| --- | --- | --- |
| `derive` | Derives the analysis model when it is not derived or a source (building model, settings, object types, materials, the soil report or substructure it took, the MEP loads) changed; `skipped` when current. | `08 FEM/model.osmodel`, `pushover.osmodel`, `thermal.json`, `ssi.json` |
| `analysis` | Runs every analysis case with OpenSees Studio's runner (`python -m opensees_studio.run`). | `08 FEM/model.results/` |
| `ssi` | On soil springs only: the fixed-base model and the comparison. | `08 FEM/model-fixed.*`, `ssi-compare.json` |
| `design` | The RC member design checks, then the steel each element requires next to the bars entered (design mode; the message adds the elements short of steel and the sections too small). | `08 FEM/model.results/design-summary.json`, `design-required.json` (kept while the project does not change; the report reads it) |
| `substructure` | Designs the foundations of 9 Substructure; `skipped` without foundations. | `09 Substructure/substructure.results/summary.json` |
| `mep` | The coordination of 7 MEP (equipment loads, openings, clashes), its plumbing (BNBC 2020 Part 8 sizing, tank designs, hydraulics), HVAC and electrical checks; the openings still missing are reported, never added. `skipped` while 7 MEP is empty. | `07 MEP/mep.results/` |
| `boq` | Measures the bill of quantities when a source changed (or the plumbing has just designed tanks whose bars it waits for); `skipped` when current. | `10 BOQ/boq.json` |
| `report` | Builds the design report. | `11 Exports/report.pdf` |
| `drawings` | Draws the structural drawings again, with the design checks of the run, when a set was generated before and is out of date; `skipped` when none was generated ("drawings not generated yet") or it is current. Asked for by name (`--steps drawings`), it always draws them. | `11 Exports/Drawings/` (sheet DXFs, `drawings.pdf`, `previews/`, `bbs.csv`, `drawings.json`) |

The summaries are written exactly as the app writes them (the same keys in the same order, tab
indentation, the source stamps of the files they were computed from), so the app's part list
reads them as current.

### HVAC loads

As in the app's Run All, the HVAC check never starts EnergyPlus: it uses the loads of the last
*Calculate Loads* when they were calculated for the current input (and EnergyPlus is found: the
installed app's own, or `SAENGINE_ENERGYPLUS`), else the estimate, said in `warnings` and in the
summary's `engine` ("estimate").

## JSON output

With `--json`, a command writes one JSON document to stdout (UTF-8), also when it fails:

```json
{
  "schema": "saengine.cli/1",
  "command": "check",
  "exitCode": 1,
  "saengine": "0.1.0",
  "...": "the command's fields"
}
```

On an error (exit 2 or 3) the command's fields are replaced by `"error": "<message>"`. When
the arguments themselves are wrong (exit 2), the document is written when `--json` is among
them, adds `"usage"` (the command's usage line), and `command` is the command as far as it
could be read (`""` for an unknown command); argparse's usage text still goes to stderr.

**`run-all`, `check`, `derive`, `analyse`, `design`, `report`**:

```json
{
  "project": {"root": "D:\\Projects\\Sample Frame", "name": "Sample Frame", "type": "building"},
  "ok": true,
  "stoppedAt": null,
  "summary": "Done: 0 pass, 15 fail · foundations 0 pass, 1 fail · ...",
  "steps": [
    {
      "id": "design",
      "label": "design checks",
      "status": "ok",
      "message": "10 pass, 5 fail",
      "counts": {"checked": 15, "passed": 10, "failed": 5, "maxUtilisation": 1.873, "governing": "S1"},
      "outputs": ["08 FEM/model.results/design-summary.json"],
      "seconds": 18.7
    }
  ],
  "parts": [
    {"part": "fem", "state": "failed", "text": "5 fail", "hint": "review the failing members"}
  ],
  "failures": [
    {"part": "fem", "check": "design", "count": 5, "message": "5 of 15 members fail the design checks (max utilisation 1.873, S1)"}
  ],
  "warnings": [
    {"part": "mep", "check": "openingsToAdd", "count": 1, "message": "openings the ducts, risers or trays still need are not in 07 MEP"}
  ]
}
```

- `ok`: no step failed (`stoppedAt` is the id of the step that stopped the run, else null).
- `steps[].status`: `ok` (done), `skipped` (nothing to do, or not reached after a stop),
  `failed` (could not be done: the message says why) or `error` (an unexpected error).
- `steps[].counts` by step: `derive` `{nodes, elements, baseShear [kN], weight [kN], changed:
  [source labels], notes}`; `analysis` `{cases}`; `design` `{checked, passed, failed,
  maxUtilisation, governing}`; `substructure` the same and `foundations`; `mep`
  `{openingsFailed, openingsPartial, clashesOpen}` and, for the disciplines the file has,
  `{plumbingFailed, floorsLow}`, `{hvacFailed, hvacOpeningsToAdd, hvacLoadsCalculated}`,
  `{electricalFailed, electricalOpeningsToAdd}`; `boq` `{changed: [part ids], items}`; `report`
  `{pages, warnings}`; `drawings` `{sheets, bbsKg, warnings}`.
- `parts[]`: every part of the project, in order, after the run: `state` (`notStarted`,
  `inProgress`, `done`, `stale`, `failed`, `error`), `text`, `hint` (or null).
- `failures[].check`: `design` (8 FEM), `foundations` (9 Substructure), `openings`, `plumbing`,
  `pressure`, `hvac`, `electrical` (7 MEP). `warnings[].check`: `clashes`, `openingsPartial`,
  `openingsToAdd`, `hvacLoads` (7 MEP), `notDesigned` (9 Substructure).

**`validate`**: `{project, ok, errors: <count>, parts: [{part, file, state, problems:
[{severity: "error"|"warning", path, index, message}]}]}`.

**`status`**: `{project, parts: [...as above], next: <part id or null>}`.

**`export`**: `{project, format, files: [paths written]}` (`civil` adds `archive`: the
archive's `{path, size, files, skipped, problems}`).

**`import`**: `{import: {root, name, files, problems, migrated, pending}}`.

**`verify`**: `{out, files: [verification.json, verification-manual.pdf with --pdf],
summary: {cases, passed, failed}, failedCases: [case ids]}`.

**`versions <action>`**: `{project, result}`, `result` as the version history returns it
(`list`: `{versions: [{id, sha, number, message, author, authorName, time, issued, label,
parts, ...}], count, more}`; `diff`: `{from, to, parts: [{part, title, changes: [{kind, id,
what, before, after, path, file}], summary}], problems}`).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Done; every check passes. |
| 1 | A check fails: a design, foundation or MEP check (`run-all`, `check` and the step commands), a validation error (`validate`) or a verification case (`verify`). |
| 2 | Usage: unknown command or option, a path that is not a SAEngine project, a missing archive. |
| 3 | Error: a step could not be done (Run All stopped), an export, import or version operation failed, an unexpected error. |

The installed shim exits with 9009 when the bundled Python is missing (repair the installation).

## In continuous integration

Keep the project folder in a git repository (the app's *Versions* does this, and pushes to
GitHub like any repository). Then a workflow can run the checks on every pull request and keep
the results and the report as artifacts. The computed files are ignored by the project's
`.gitignore`, so the checks always start from the sources.

On a **self-hosted Windows runner** with SAEngine installed (an office PC) and the *Add the
saengine command to PATH* task ticked at install, the command is on the `PATH` of the runner's
user (restart the runner service after the install so it reads the new `PATH`). As GitHub
advises for any self-hosted runner, do not run workflows of pull requests from forks of a
public repository on it:

```yaml
# .github/workflows/saengine-check.yml
name: SAEngine checks
on: [push, pull_request]
jobs:
  check:
    runs-on: [self-hosted, windows]
    steps:
      - uses: actions/checkout@v4
      - name: Validate
        run: saengine validate "Tower A" --json > validate.json
      - name: Design checks
        run: saengine check "Tower A" --json > check.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: saengine-check
          path: |
            validate.json
            check.json
```

On a **GitHub-hosted runner**, install SAEngine first, unattended, from your copy of the setup
(here a release asset; `SAENGINE_SETUP_URL` is a repository variable):

```yaml
jobs:
  check:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install SAEngine
        shell: pwsh
        run: |
          Invoke-WebRequest "${{ vars.SAENGINE_SETUP_URL }}" -OutFile setup.exe
          Start-Process .\setup.exe -Wait -ArgumentList '/VERYSILENT','/NORESTART','/MERGETASKS="!runcode"',"/DIR=$env:RUNNER_TEMP\SAEngine"
          "$env:RUNNER_TEMP\SAEngine\bin" | Out-File -Append -Encoding utf8 $env:GITHUB_PATH
      - name: Design checks
        run: saengine check "Tower A" --json > check.json
      - name: Design report
        if: success()
        run: saengine report "Tower A"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: saengine
          path: |
            check.json
            Tower A/11 Exports/report.pdf
```

A failing check fails the job (exit code 1); `check.json` lists the failures per part. To let a
job pass with failing checks but stop on errors, accept exit code 1 only. In `cmd` (`shell:
cmd`), `%ERRORLEVEL%` would be read before `saengine` runs, so test it with `if errorlevel`:

```bat
saengine check "Tower A" --json > check.json || if errorlevel 1 if not errorlevel 2 exit /b 0
```

In PowerShell (`shell: pwsh`):

```powershell
saengine check "Tower A" --json > check.json
if ($LASTEXITCODE -eq 1) { exit 0 } else { exit $LASTEXITCODE }
```

## What differs from the app

The command line reads the files as saved: the app's Run All first saves the editors' unsaved
changes. Otherwise the results are the app's: on the same project, `saengine run-all` writes the
same `model.osmodel`, the same `boq.json` and summary files equal to the app's except for the
time in `computed` (checked on the sample). Two presentational differences remain: the texts are
English (the app's follow its display language), and the date in "report 19 Oct" is written
`day month` (the app follows the system's locale). The DXF floor plans hold the same drawing
(layers, entities, sizes) as the app's, written by ezdxf instead of the app's CAD editor, so the
files are not byte-identical.
