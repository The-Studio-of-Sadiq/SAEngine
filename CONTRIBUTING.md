# Contributing to SAEngine

Thank you for helping. SAEngine is free software for structural engineers, and it gets better
through reports, checks against hand calculations, code packs and code.

By contributing you agree that your contribution is licensed under the
[GNU AGPL-3.0-only](LICENSE), like the rest of SAEngine, and you follow the
[code of conduct](CODE_OF_CONDUCT.md).

## Ways to help

| You are... | Help by... |
| --- | --- |
| An engineer trying SAEngine | Reporting wrong results, confusing screens and missing steps: **Help › Report a Bug** in the app, or an [issue](https://github.com/The-Studio-of-Sadiq/SAEngine/issues/new/choose). For a wrong result, give SAEngine's value, the value you expect and the clause or hand calculation behind it. |
| Someone who knows a building code | Checking the pack values marked **verify** against the code text, or writing a code pack (see [docs/code-packs.md](docs/code-packs.md)). |
| A developer | Fixing an issue, adding tests or verification examples, improving performance. Start with issues labelled *good first issue* or the [project board](https://github.com/orgs/The-Studio-of-Sadiq/projects/8). |
| A writer | Improving the [manual](docs/manual/README.md) and the [wiki](https://github.com/The-Studio-of-Sadiq/SAEngine/wiki). |

Confidential project details never go into a public issue: e-mail
publicrelations@thestudioofsadiq.tech instead (see [SECURITY.md](SECURITY.md)).

## The repository

| Folder | What it is |
| --- | --- |
| `workbench/` | The application: a Code - OSS (VS Code) build. SAEngine's code is in `src/vs/workbench/contrib/saengine*`, `src/vs/workbench/services/saengine*` and `src/vs/platform/saengine`. |
| `python/` | The engine: the `saengine` package (OpenSeesPy analysis, design, drawings, BOQ, report, code packs), its tests and the verification pack. |
| `packages/` | The 3D viewers and the CAD editor used inside the app. |
| `third_party/` | opensees-studio (AGPL-3.0). |
| `scripts/` | Building the setup, signing, releases and CI helpers. |
| `docs/` | The manual, command line, collaboration, code packs and [engineering decisions](docs/engineering-decisions.md). |

## Branches

- **`main`**: releases only.
- **`beta`**: the work towards the next release. **Pull requests go into `beta`.**
- **`gh-pages`**: the website.

Make one change per branch, branched from `beta`. The branch is deleted after it is merged.

## House rules

1. **Code independence.** The engine and the UI never ask which building code is in use (no
   `if code == "BNBC"`). Values, methods and clause texts come from the code pack.
2. **One feature, one place.** A feature lives in one part of the program; other parts link to
   it instead of copying it.
3. **Reuse proven open source.** Use the editor, terminal and viewers SAEngine already has, and
   existing libraries, instead of building new ones.
4. **Cite, do not copy, the codes.** Packs and comments give the clause and page, and paraphrase.
   Standards are copyrighted.
5. **The repository is public.** No client data, real project files, secrets, personal paths or
   e-mail addresses in commits.
6. **Engineers' words in the UI.** Labels in title case, plain sentences, units shown, and every
   user-visible string localised.
7. **Guardrails, not surprises.** Impossible input is refused with the reason; deleting
   important data asks first; Run All never writes reinforcement on its own.

Decisions that set a result where a code is silent or ambiguous go into
[docs/engineering-decisions.md](docs/engineering-decisions.md) with the reason.

## Setting up

Windows 10/11 x64, with Git, Node.js (the version in `workbench/.nvmrc`), Python 3.12 and the
Visual Studio Build Tools (C++).

```powershell
git clone https://github.com/The-Studio-of-Sadiq/SAEngine.git
cd SAEngine
git checkout beta

# The engine
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e python -e third_party/opensees-studio

# The application (see workbench/README.md for details)
cd workbench
npm install
```

Run the app from the sources with `.\scripts\run-saengine.ps1`, or build it:

```powershell
.\scripts\build-installer.ps1 -SkipPython -SkipSetup   # the app only, about 15 minutes
.\scripts\build-installer.ps1                         # the full setup
```

Third-party programs for the setup (EnergyPlus, LibreCAD, LibreDWG) are downloaded by
`scripts/ci/fetch_pinned.py`, which checks each file's SHA-256 against its pin in
`scripts/ci/third-party-binaries.json`.

## Checks before a pull request

In `python/` (with `PYTHONPATH="src;.;../third_party/opensees-studio/src"`):

```powershell
..\.venv\Scripts\python -m ruff check .
..\.venv\Scripts\python -m ruff format --check .
..\.venv\Scripts\python -m pytest tests/<the tests of what you changed>
```

In `workbench/`:

```powershell
npm run eslint -- <changed files>
npm run typecheck-client        # for broad changes
scripts\test.bat --grep "<your suite>"
```

CI runs the workbench checks, six Python test groups and the verification pack on every pull
request into `beta` and `main`.

## Pull requests

- Into `beta`, with a title that says what changes for the engineer.
- Describe what you changed and why, and how you checked it.
- **Screenshots** for anything visible, at 1366×768 and 1920×1080, from a fresh project.
- New results need a test, and a verification example (hand calculation or published example)
  when they are engineering results.
- Keep the [project board](https://github.com/orgs/The-Studio-of-Sadiq/projects/8) item up to
  date, and say which issue the pull request fixes.

## Commit messages

A first line that says what changes, in plain words (for example *Floor plan: a rotated column's
label no longer overlaps*), then the reason if it is not obvious.
