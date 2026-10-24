# Drawing sheets QA: AutoCAD, LibreCAD and ezdxf

`scripts/drawings_qa/qa.py` checks a generated drawing set the way the engineers who receive
it will open it. For each sheet DXF of `11 Exports/Drawings` it:

1. **ezdxf** (always): reads the DXF, runs ezdxf's audit, counts the entities per type and
   layer, finds the sheet's size and base scale from its frame, and lists layers used but not
   defined, linetypes missing, text heights that are not plot heights (2.5/3.5/5/7 mm on
   paper) and anything outside the border.
2. **AutoCAD** (when installed): runs `accoreconsole.exe` headless (no window) with the script
   `scripts/drawings_qa/sheet.scr.in`, which opens the DXF and
   - lists the text styles and whether their fonts are found, the linetypes, the layers and
     any external references;
   - runs `AUDIT` without fixing (the log lists every error);
   - `ZOOM E` and reports the extents;
   - plots the model space through `DWG To PDF.pc3` on the ISO full-bleed sheet at the sheet's
     scale with `monochrome.ctb` (`S-1xx.pdf`);
   - plots the sheet's paper space layout by its own page setup (`S-1xx.layout.pdf`), which
     proves that the layout plots as it is;
   - saves the drawing as DWG 2018 (`S-1xx.dwg`).

   The log (`S-1xx.acad.log`) is parsed for the AUDIT total, font substitutions
   ("Substituting [simplex.shx] for [...]"), missing resources and errors.
3. **LibreCAD** (when installed): converts the DXF with its headless `dxf2pdf` command
   (`S-1xx.librecad.pdf`), the bundled viewer's view of the sheet.

A DXF that is not a sheet (the floor plans of `11 Exports/Floor Plan`, which have no frame) is
checked the same way, except that AutoCAD plots its extents fitted to A1 and there is no layout
plot, text-height or border check.

It writes `report.json` and `report.md` (one row per sheet, then the details) into `--out`.

## Run it

From the repository root, in the SAEngine Python environment, on a copy of a project:

```bash
python -m saengine.cli export "<copy of Sample Frame>" --format drawings
```

```bash
python scripts/drawings_qa/qa.py "<copy of Sample Frame>/11 Exports/Drawings" --out "<scratch>/qa" --png
```

Options: `--only S-105,S-110` for some sheets, `--skip-autocad`, `--skip-librecad`, `--png`
(PNG previews of the AutoCAD plots, with PyMuPDF from the development environment),
`--timeout` per sheet and program (default 600 s). `SAE_ACCORECONSOLE` and `SAE_LIBRECAD`
point at the programs when they are not in the default places (the newest
`C:\Program Files\Autodesk\AutoCAD 20xx\accoreconsole.exe`,
`C:\Program Files\LibreCAD\LibreCAD.exe`). A sheet takes about 15 s in AutoCAD.

The exit code is 1 when a sheet has ezdxf audit errors or AutoCAD AUDIT errors, or AutoCAD
could not plot it.

## Without AutoCAD (CI)

CI has no AutoCAD: the script prints "AutoCAD (accoreconsole.exe) not found: the AutoCAD
checks are skipped." and runs the rest. The AutoCAD part is a manual check, run locally before
a release or after a change to the sheets' layers, styles, title block or plotting. What it
found is guarded in CI by `python/tests/test_drawings_cad.py` (ezdxf only): only SAEngine's
own text style (Arial), linetypes and layers; text at the plot heights; everything inside the
border; ByLayer colours; hatch scales; the layout's page setup.

## Rules for the AutoCAD part

- AutoCAD is used only through `accoreconsole.exe` with a script, Autodesk's documented
  headless console. No GUI, no other interface.
- Nothing of AutoCAD's goes into the repository: no fonts (`.shx`), linetype files (`.lin`),
  hatch patterns (`.pat`), templates (`.dwt`), blocks, plotter configurations, and no DWG or
  PDF that AutoCAD wrote. Keep `--out` in a scratch folder. The sheets name AutoCAD's PDF
  plotter and `monochrome.ctb` in their page setup by name only.
- accoreconsole needs a console of its own: the script starts it in a hidden one and keeps its
  standard input open (when its input ends, accoreconsole waits for ever). Under Git Bash,
  call the script with Python; do not call accoreconsole directly, since MSYS rewrites its
  `/i` and `/s` switches into drive paths.
- If accoreconsole stops at a first-run or profile prompt, run AutoCAD once interactively to
  finish its setup; the script cannot answer such prompts.

## Reading the report

| Column | Good | If not |
| --- | --- | --- |
| ezdxf audit | 0 err / 0 fix | Broken DXF structure: fix the writer. |
| Odd text heights | – | Text not at 2.5/3.5/5/7 mm on paper. |
| Outside border | 0 | Something drawn over the margin. |
| AutoCAD AUDIT | 0 | AutoCAD finds errors ezdxf does not: look at the log. |
| Missing fonts / Font subst. | 0 / 0 | A style refers to a font AutoCAD does not have. |
| PDF / Layout PDF / DWG | ok | The plot or save failed: the log's last lines say why. |
| LibreCAD | ok | dxf2pdf failed: `S-1xx.librecad.log`. |

Compare the three PDFs of a sheet (AutoCAD model plot, AutoCAD layout plot, LibreCAD) with
the sheet's page of `drawings.pdf`: they should match line for line; LibreCAD draws its own
font.
