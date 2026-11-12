# Skills for working on SAEngine

What an agent (or a new contributor) needs to know and be able to do on this project, grouped
by area. Each entry says what the skill is for and where it is used. Project rules are in
`../rules/`; owner decisions are in `docs/engineering-decisions.md`.

## 1. Structural engineering (the domain)

| Skill | Used for |
|---|---|
| RC frame analysis and design (beams, columns, slabs, shear walls, footings, piles) | `python/src/saengine` design modules, detailing, drawings |
| Reading building codes and citing them (Part / Section / page) | Code packs; every value carries its source |
| Load calculation: dead, live, wind, seismic, load combinations | Loads stage, pack data (`codes/packs/*/data`) |
| Geotechnics: SPT logs, bearing capacity, settlement, pile capacity | Site & Soil part, soil report import |
| FEM modelling: lumped storey mass, rigid zones, meshing, modal / response spectrum | OpenSeesPy model builder, results view |
| Reinforcement detailing: lap and anchorage, joint bars, bar clashes | Drawings, BOQ, `rc_detailing` |
| Quantity take-off (BOQ: concrete, cement bags, sand / stone cft, steel) | BOQ part |
| Plumbing and MEP coordination for structural engineers | MEP part (fixture units, RC tanks, WNTR) |

**Code independence:** the engine never asks which code is in use. A code pack supplies the
values, methods and clause text, and BNBC is only the default pack. Write `pack.value(...)`,
never `if code == "BNBC"`.

## 2. Code packs

- JSON data first; a pack may `extend` another pack. Hooks (Python) run only when trusted.
- Every number has a citation. Mark values not yet checked against the code text with `verify`.
- Packs: BNBC (default), ACI/ASCE, Eurocodes, IS and others. Tests in `python/tests/test_codes_*`
  and `test_pack_material_limits.py`.
- Never copy code text verbatim into the public repo; paraphrase and cite.

## 3. Python backend

- Python 3.12, OpenSeesPy, numpy / scipy, h5py (one dataset per result kind, not per id), ezdxf for
  drawings, IfcOpenShell for IFC, typst for reports.
- Run tests from `python/` with `PYTHONPATH="src;.;../third_party/opensees-studio/src"` and the
  project venv. Lint with `ruff check` and `ruff format --check`.
- Guardrails (impossible input is blocked with a reason) live in one place:
  `library/guardrails.py` + `library/data/guardrails.json`, shared by the UI and the AI.

## 4. Workbench (VS Code fork, TypeScript)

- VS Code architecture: layers (base → platform → editor → workbench), dependency injection,
  contributions, `MenuRegistry`, context keys, view containers, editor panes.
- SAEngine code lives in `workbench/src/vs/workbench/contrib/saengine*` and
  `services/saengine*`. Follow `workbench/.claude/CLAUDE.md` (tabs, localized strings, disposables).
- Developer mode (`saengine.developerMode`) gates the VS Code surfaces engineers do not need.
  Gate them, never delete them.
- Design system: brand tokens `--sa-brand-*`, Saira for headings, logo assets in
  `workbench/resources/brand/` (built by `scripts/brand/build_brand.py`).
- Targeted checks: `npx eslint <files>`, a temporary tsconfig for a targeted `tsc`, unit tests via
  `scripts/test.bat --grep`.
- 3D viewer: That Open / three.js in the `@saengine/fem-viewer` package; MapLibre for the site map.

## 5. UX for engineers

- Walk every flow as a practising engineer: one entry per task, nothing asked twice, fewest steps,
  1366×768 first, then 1920×1080.
- One New Project wizard (info + grid). Stage bar: Site & Soil → Model → Loads → Analysis →
  Design → Drawings / BOQ / Report.
- Trust: a consent dialog before any data leaves the machine, diagnostics opt-in and off by default,
  a delete confirmation for important data only.
- No duplication: a feature lives in one part; other parts link to it.

## 6. Testing the desktop app

- Build without the setup: `scripts/build-installer.ps1 -SkipPython -SkipSetup` (about 15 min).
- Drive test windows through the Chrome DevTools Protocol (CDP, `--remote-debugging-port`) with a
  separate `--user-data-dir`. Never use the owner's mouse or keyboard, never touch the owner's own
  windows, and keep test windows visible.
- Use custom dialogs and the simple file dialog in the test profile so CDP can reach them.
- Run heavy checks (Run All, full pytest) through the lock script, at most three at a time.

## 7. Build, CI and release

- CI: GitHub Actions `CI` workflow (workbench typecheck / eslint / unit tests, six Python shards,
  verification pack). Full run: `gh workflow run CI --ref <branch> -f full=true`.
- Third-party binaries are pinned with SHA-256 in `scripts/ci/third-party-binaries.json` and
  downloaded by `scripts/ci/fetch_pinned.py` (EnergyPlus, LibreCAD, LibreDWG and their licences).
- Full setup: `build-installer.ps1` with `-EnergyPlusDir`, `-LibreCADDir`, `-LibreDWGDir`
  (about 40 min). Release: `scripts/ci/release.py assets` + `gh release create --prerelease`.
- Licensing: SAEngine is AGPL-3.0-only. LibreCAD (GPL-2.0-only) and LibreDWG (GPL-3.0+) ship
  alongside as separate programs and are never linked.
- Code signing: SignPath (planned).

## 8. Git workflow

- Integration branch `feat/ui-ux-redesign`; side work on `side/*` branches with PRs, merged with
  `--no-ff` into the integration branch only, never into `main`.
- The repository is public: no local paths, secrets, client data or `.claude/` content in commits.
- Commit messages end with the Co-Authored-By line. PR bodies end with the Claude Code line.

## 9. Agent tooling (Claude Code skills and tools used)

| Skill / tool | Used for |
|---|---|
| `run` | Launching the built app and confirming a change works |
| `code-review`, `simplify`, `security-review` | Reviewing side-session PRs before merging |
| `workflow-authoring` + Workflow | Multi-agent rounds (find → verify) when the owner asks for one |
| Agent (side sessions, at most two at once) | Parallel tracks in worktrees |
| `pdf` | Reading code PDFs and soil reports; the user guide PDF |
| `docx`, `xlsx` | Consultant reports and BOQ exports supplied by the owner |
| `dataviz` | Charts in reports and results |
| `artifact-design` | Plans and explainers shared with the owner |
| Browser / CDP tools | Driving and screenshotting test windows |
| `gh` CLI | PRs, CI runs, releases |

## 10. Things never to do

- Never run or cite ETABS, SAP2000 or STAAD. Use open-source cross-checks instead.
- Never `npm install` / `pip install` or download anything without the owner's approval.
- Never write reinforcement automatically in Run All. Design fails with a Design Reinforcement
  button instead.
- Never reinvent what VS Code or a proven library already does (`../rules/no-reinventing.md`).
