# Release gates: scale (#291) and walkthrough (#292)

Two depth tests run before every release. Both issues stay the record: post the results as a
comment on the issue each time, file one issue per failure, and close the issue only when the
run is complete and recorded (reopen it, or start a new comment, for the next release).

Rules that apply to both: heavy runs (the benchmark, build-fast, Run All) at most three at a
time on the machine; stop any orphaned Run All or benchmark Python when done; keep test output,
projects and screenshots **outside** the repository.

## #291 — Run All at 10, 20 and 30 storeys

Uses the existing benchmark (see [large-models.md](large-models.md) for what it measures).

```console
# from the repository root, with the SAEngine Python and the checkout's sources
set PYTHONPATH=python/src;third_party/opensees-studio/src
python scripts/perf/bench_large_models.py beam-10 beam-20 beam-30 --no-profile --out <scratch>\gate-291
python scripts/perf/bench_large_models.py --summary --out <scratch>\gate-291
```

- `beam-N` is the 4 × 3 bay RC frame (bays 7/6/8/7 × 6/8/6 m, 4.0 + 3.2 m storeys, C27.6 /
  B500DWR, mat, Dhaka) **with the generator's template bars**, so the design step checks every
  member. Add `flat-N` / `core-N` for the flat plate and core-wall towers when time allows.
- Record per step: wall time, peak memory (`Peak RSS` and the step's growth), the result
  counts in the step message (members pass/fail, joints, foundations, drawing sheets), and any
  crash or `MemoryError`. The payload table shows what the workbench pays after a run.
- Run it on a quiet machine (no app test windows, no other benchmark): memory pressure and
  CPU contention change the times several-fold.
- Compare with the previous comment on #291 and with the alpha-10 baseline: a 10-storey
  frame through Run All + Design Reinforcement + Apply + Run All in about 2.7 min (smaller
  3 × 2 bay plan, app timings).

## #292 — engineer's walkthrough at 1366×768 and 1920×1080

1. **Build** a dev workbench from the branch under test (a worktree is fine). In a worktree,
   make `workbench/node_modules` a folder of junctions to the main checkout's entries with
   `@saengine/fem-viewer` pointing at the worktree's `packages/fem-viewer` (build it there with
   `npm run build`), and junction the other `node_modules` folders (`workbench/build`,
   `extensions/*`, `remote`, `test/automation`). Then:

   ```console
   cd workbench
   npm run electron
   npm run build-fast -- --client-only --force
   ```

2. **Launch** a test window with its own profile and a CDP port (custom dialogs and the
   simple file picker, so nothing opens as a native OS dialog):

   ```console
   powershell -File scripts/gate/launch.ps1 -GateDir <scratch>\walk -Port 9347
   ```

3. **Drive it over CDP only** — never the real mouse or keyboard — and keep the window
   visible. `scripts/gate/cdp.js` (env `SAENGINE_GATE_DIR`, `SAENGINE_GATE_PORT`):

   ```console
   node scripts/gate/cdp.js size 1366 768        # resize the real window
   node scripts/gate/cdp.js size 1920 1080       # device-metrics emulation (screen is smaller)
   node scripts/gate/cdp.js shot 01-wizard       # screenshot into <gate dir>/shots
   node scripts/gate/cdp.js key F1 ; node scripts/gate/cdp.js type "New Project" ; node scripts/gate/cdp.js key Enter
   node scripts/gate/cdp.js fill "input[aria-label=Name]" Gate Walk 6S
   node scripts/gate/cdp.js click ':is(a,button,.monaco-button):visible:text-is("Next")'
   node scripts/gate/cdp.js mclick 1100 636      # screenshot coordinates (2000-wide view) -> CSS
   node scripts/gate/cdp.js click li.saengine-run-all
   node scripts/gate/waitrun.js                   # until "Run All done in" / "step N ... failed"
   node scripts/gate/waitidle.js                  # until no job timer in the status bar
   ```

4. **Walk as a practising engineer** on a fresh project: wizard → soil (enter a borehole by
   the log sheet: strata, SPT, water table) → project settings incl. a load pattern → floor
   plan loads (a wall line load on a beam, a load on the new pattern) → BIM 3D → Run All →
   Design Reinforcement → Apply → Run All → substructure → BOQ (hand-check a volume) → report
   (hand-check Ta, Cs, V) → drawings. Then revisit the main editors at 1920×1080.
5. **Report**: one issue per bug with severity in the title (`[blocker]`, `[major]`,
   `[minor]`), steps, expected/actual and screenshots. Screenshots must show no local paths
   or personal data (crop or skip the Overview and wizard result pages, which print the
   project folder). Publish them on the image-only `gate-shots` branch (a commit holding just
   the PNGs, pushed with `git hash-object` / `mktree` / `commit-tree`, never merged) and link
   them by commit-pinned raw URL. Post the stage table on #292.
6. Close the test window (command palette › Close Window) so its engine stops too.
