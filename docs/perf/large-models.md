# Performance on large buildings

How long **Run All** takes on the 10–30 storey RC towers Dhaka engineers model, where the time
goes, and what to change first. Measured on 2026-10-25 with the benchmark
`scripts/perf/bench_large_models.py`, on two bases of `feat/ui-ux-redesign`:

- **`6c5968b1`**, before the ETABS parity round: every building, 10 to 30 storeys;
- **`012dc5e8`** (`960d8569`, the parity round v0.0.44, and a lint commit): the 10-storey
  buildings again. Its 500 mm shell mesh is the main change for the flat plate and core
  buildings (see [The parity round's mesh](#the-parity-rounds-mesh-and-the-band-solver)).

Nothing in the app was changed for this report. File and line references are to `012dc5e8`.

**In short.** A 10-storey frame takes 50 minutes of Run All, a 30-storey frame two hours, a
10-storey flat plate an hour and a half, a 10-storey frame with core walls almost three; and
opening the column interaction and required-steel views afterwards costs another 35 minutes
to 2.5 hours. The OpenSees analysis is under a minute for the frames. The time is SAEngine's
own Python, and most of it is avoidable: one finite-element section analysis per member where
one per section type would do, the member design checks run four or five times, a cache that
the column view invalidates, and per-point Python loops where arrays would do. On the parity
round's base, the 500 mm mesh with the dense band solver makes the shell buildings' analysis
fail or take hours and up to 10 GB.

- [The benchmark](#the-benchmark)
- [Results](#results)
- [The parity round's mesh and the band solver](#the-parity-rounds-mesh-and-the-band-solver)
- [Where the time goes](#where-the-time-goes)
- [The top 10 hotspots](#the-top-10-hotspots)
- [Proposed fixes, ranked](#proposed-fixes-ranked)
- [Limits of these measurements](#limits-of-these-measurements)

## The benchmark

```console
python scripts/perf/bench_large_models.py --list
python scripts/perf/bench_large_models.py beam-10 flat-10 core-10 --no-profile --out <scratch>\perf\timing
python scripts/perf/bench_large_models.py beam-3 flat-3 core-3 --out <scratch>\perf\profile
python scripts/perf/bench_large_models.py --summary --out <scratch>\perf\timing
```

Keep `--out` outside the repository. The script reuses the app's own code and adds no second
runner:

- **The buildings** come from `saengine.project.new_building.create_building` (the CLI's
  `new-building`): 4 × 3 bays of 7, 6, 8, 7 m by 6, 8, 6 m, a 4.0 m ground storey and 3.2 m
  typical storeys, C27.6 / B500DWR, a mat, Dhaka, residential, in three systems: `beam` (RC
  frame, `rcFrame`), `flat` (flat plate, `flatSlab`) and `core` (frame and core walls,
  `rcFrameWithWalls`), at 3, 10, 20 and 30 storeys. They are generated **with the template
  bars** (`reinforcement: true`): without bars the design step checks nothing (Design mode
  would propose bars first), and checking every member is the work to measure.
- **Each Run All step** runs as `saengine.pipeline.run_all.run_all(project, [step])` (the CLI's
  `run-all --steps <step>`), one after the other in Run All's order, each reading the files
  afresh. Two differences from one Run All that do not change the work measured: `boq` does
  not know whether `mep` has just designed tanks, and `drawings` reads the kept design checks
  (`design-report.json`) rather than receiving them. `drawings` runs as if asked for (`--steps
  drawings`), so the first drawing set is included.
- **The workbench's payloads** after a run are the RPC handlers of `saengine.rpc.handlers`,
  called in the same process in the order the app asks for them: `results/list`,
  `results/tables`, `fem/storyResponse`, `fem/seismicDesign`, `fem/secondOrder`,
  `fem/columnInteraction`, `design/required`, `drawings/list`, `results/view` for every result
  the list offers (the first three modes of a modal case), `fem/memberForces` for one column,
  and the parse of `model.osmodel`, which the 3D viewer reads itself. Each answer's JSON size
  is the size the RPC server sends.

Per step it records the wall time and the CPU time of this process, the CPU time and the peak
memory of every process the step starts (the OpenSees Studio solver: the analysis, the
response spectrum design's modal-force run, the fixed-base run, raft and tank models; the
virtual environment's `python.exe` launcher is looked through to the interpreter it starts),
the peak resident memory of this process and how much it grew in the step, the whole
machine's CPU load meanwhile, the files written, and (without `--no-profile`) a cProfile of
the step with the solver runs' profiles merged in: `profiles/<step>.prof` and a text summary
of the top 30 functions by cumulative and by own time. After `derive` it counts the nodes,
elements by type and DOFs of `08 FEM/model.osmodel`.

Two lessons for whoever measures next:

- **cProfile slows this code two to four times** (concreteproperties and sectionproperties
  make millions of small calls), and Python 3.12's cProfile sees every thread. Time with
  `--no-profile`; profile the 3-storey buildings, whose hotspots are the same.
- **`psutil.Process.children()` costs about 70 ms on Windows** and holds the GIL: a sampler
  calling it ten times a second slowed the measured step down by a third. The script samples
  only the processes it saw started.

## Results

### Overview (`6c5968b1`)

Minutes of wall time / CPU time per step (CPU: the backend process, plus the solver's where
the sampler caught it; "other" is ssi, substructure, mep and boq). *Step memory* is the most
a step grew the backend process (the report's, every time). *Viewer* is the two slow payloads
the workbench asks for after a run, `fem/columnInteraction` and `design/required`.

| Building | Nodes | Elements | DOFs | generate | derive | analysis | design | report | drawings | other | Run All | Step memory (GB) | Viewer (min) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| beam-10 | 230 | 510 | 1,380 | 3.4 / 1.5 | 12.3 / 5.6 | 0.4 / 0.0 | 25.4 / 23.7 | 11.5 / 10.9 | 0.6 / 0.7 | 0.1 / 0.1 | **50 / 41** | 1.3 | 34 |
| beam-20 | 440 | 1,020 | 2,640 | 1.9 / 1.9 | 7.5 / 7.3 | 0.2 / 0.1 | 67.4 / 60.0 | 24.7 / 24.6 | 1.4 / 1.5 | 0.2 / 0.2 | **101 / 94** | 2.5 | 48 |
| beam-30 | 650 | 1,530 | 3,900 | 4.1 / 4.0 | 15.0 / 12.4 | 0.7 / 0.3 | 71.6 / 69.2 | 28.5 / 28.4 | 1.5 / 1.6 | 0.3 / 0.3 | **118 / 112** | 3.9 | 151 |
| flat-10 | 1,318 | 1,492 | 7,908 | 0.0 / 0.0 | 1.9 / 1.9 | 6.4 / – | 54.7 / 37.8 | 24.4 / 20.3 | 0.7 / 0.7 | 0.3 / 0.3 | **88 / 61+** | 0.7 | 37 |
| core-10 | 1,318 | 1,762 | 7,908 | 0.5 / 0.5 | 3.3 / 3.3 | 6.4 / – | 137.9 / 35.2 | 19.9 / 19.4 | 0.8 / 0.8 | 0.2 / 0.2 | **169 / 59+** | 1.0 | 40 |

Run All excludes `generate` (the wizard's step, before Run All). For the flat plate and core
buildings the gap between wall and CPU time in `analysis` and `design` is the solver, whose
CPU time the sampler did not catch for these runs (see the limits): `design` includes a second
solver run of every case, the response spectrum modal-force run (`saengine/fem/seismic_design.py:522`
`_run`). On `core-10` it waited 103 minutes for that run, with the machine at 15 % load and
short of memory (four benchmarks were running): the solver was paging.

For comparison, the one earlier measurement of a 10-storey building, about 65 minutes for
Run All, matches `beam-10`'s 50 minutes plus its first viewing.

### The detailed tables (`6c5968b1`)

Generated with `--summary`. *Machine load* is the whole machine's CPU load while the step ran;
*Step's growth* is how much the step grew the backend's memory (the process keeps what earlier
steps allocated, so *Peak RSS* is cumulative).

<details><summary>beam-10, beam-20, beam-30, flat-10, core-10</summary>

#### beam-10 (rcFrame, 10 storeys)

230 nodes, 510 elements (ElasticBeamColumn 510), 1,380 DOFs, 11 analysis cases; model.osmodel 394.9 kB. Run All 50.3 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 201.7 | 91.4 | – | 100 % | 139.0 | 20.0 | – | – |
| derive | ok | 737.7 | 338.5 | – | 100 % | 221.1 | 82.1 | – | 394.9 kB |
| analysis | ok | 23.1 | 0.6 | 0.0 | 100 % | 225.8 | 3.5 | 4.2 | 6.7 MB |
| ssi | skipped | 0.0 | 0.0 | – | 100 % | 225.5 | 0.0 | – | – |
| design | ok | 1,526.2 | 1,422.0 | 0.0 | 64 % | 401.6 | 176.1 | 4.2 | 18.0 MB |
| substructure | ok | 3.4 | 2.7 | – | 70 % | 343.5 | 4.2 | – | 510 B |
| mep | skipped | 0.0 | 0.0 | – | 81 % | 342.2 | 0.1 | – | – |
| boq | ok | 2.9 | 2.8 | – | 60 % | 344.7 | 2.5 | – | 285.1 kB |
| report | ok | 688.7 | 653.7 | – | 54 % | 1,679.0 | 1,335.3 | – | 29.3 MB |
| drawings | ok | 38.1 | 39.1 | – | 56 % | 2,032.9 | 628.8 | – | 72.7 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 2.54 | 3.4 kB |
| results/tables | 10.64 | 7.9 MB |
| fem/storyResponse | 2.52 | 145.6 kB |
| fem/seismicDesign | 1.55 | 15.7 kB |
| fem/secondOrder | 0.01 | 51 B |
| fem/columnInteraction | 754.50 | 8.0 MB |
| design/required | 1,263.29 | 1.8 MB |
| drawings/list | 0.03 | 31.3 kB |
| results/view (every result) ×36 | 26.10 | 19.1 MB |
| model.osmodel (read by the viewer) | 0.01 | 394.9 kB |

#### core-10 (rcFrameWithWalls, 10 storeys)

1,318 nodes, 1,762 elements (Shell 1,172, ElasticBeamColumn 590), 7,908 DOFs, 11 analysis cases; model.osmodel 1.2 MB. Run All 168.5 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 32.8 | 32.3 | – | 55 % | 1,704.8 | 0.1 | – | – |
| derive | ok | 197.5 | 195.6 | – | 53 % | 1,710.8 | 6.7 | – | 1.2 MB |
| analysis | ok | 385.7 | 0.3 | 0.0 | 54 % | 1,709.6 | 0.2 | 4.2 | 39.7 MB |
| ssi | skipped | 0.0 | 0.0 | – | 58 % | 1,709.6 | 0.0 | – | – |
| design | ok | 8,275.8 | 2,112.5 | 0.0 | 15 % | 1,815.3 | 105.7 | 10.3 | 77.6 MB |
| substructure | ok | 11.4 | 10.2 | – | 44 % | 1,144.4 | 0.6 | – | 510 B |
| mep | skipped | 0.0 | 0.0 | – | 38 % | 1,143.5 | 0.1 | – | – |
| boq | ok | 2.0 | 1.8 | – | 53 % | 1,143.7 | 0.3 | – | 286.1 kB |
| report | ok | 1,193.1 | 1,166.3 | – | 60 % | 2,199.4 | 1,056.4 | – | 29.1 MB |
| drawings | ok | 47.4 | 50.0 | – | 59 % | 2,951.8 | 804.4 | – | 88.1 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 13.97 | 3.5 kB |
| results/tables | 56.05 | 38.1 MB |
| fem/storyResponse | 14.36 | 147.1 kB |
| fem/seismicDesign | 7.07 | 16.2 kB |
| fem/secondOrder | 0.03 | 51 B |
| fem/columnInteraction | 1,104.15 | 6.5 MB |
| design/required | 1,308.53 | 1.6 MB |
| drawings/list | 0.03 | 44.9 kB |
| results/view (every result) ×36 | 56.99 | 32.2 MB |
| model.osmodel (read by the viewer) | 0.01 | 1.2 MB |

#### flat-10 (flatSlab, 10 storeys)

1,318 nodes, 1,492 elements (Shell 1,172, ElasticBeamColumn 320), 7,908 DOFs, 11 analysis cases; model.osmodel 1.2 MB. Run All 88.4 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 0.9 | 0.6 | – | 73 % | 123.8 | 5.2 | – | – |
| derive | ok | 113.7 | 113.0 | – | 55 % | 196.3 | 70.8 | – | 1.2 MB |
| analysis | ok | 382.6 | 0.6 | 0.0 | 60 % | 197.5 | 2.7 | 4.2 | 38.8 MB |
| ssi | skipped | 0.0 | 0.0 | – | 69 % | 197.3 | 0.0 | – | – |
| design | ok | 3,282.0 | 2,269.0 | 0.0 | 66 % | 497.5 | 300.2 | 5.8 | 70.7 MB |
| substructure | ok | 15.3 | 14.6 | – | 69 % | 331.8 | 9.0 | – | 510 B |
| mep | skipped | 0.0 | 0.0 | – | 69 % | 323.0 | 0.0 | – | – |
| boq | ok | 1.2 | 1.1 | – | 66 % | 329.5 | 6.5 | – | 175.2 kB |
| report | ok | 1,466.5 | 1,218.5 | – | 92 % | 1,033.3 | 710.8 | – | 14.3 MB |
| drawings | ok | 43.8 | 44.0 | – | 82 % | 1,610.7 | 579.9 | – | 52.8 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 17.47 | 3.4 kB |
| results/tables | 69.20 | 34.4 MB |
| fem/storyResponse | 17.27 | 146.5 kB |
| fem/seismicDesign | 8.28 | 16.1 kB |
| fem/secondOrder | 0.02 | 51 B |
| fem/columnInteraction | 908.80 | 7.6 MB |
| design/required | 1,320.71 | 421.0 kB |
| drawings/list | 0.03 | 29.9 kB |
| results/view (every result) ×36 | 90.57 | 21.8 MB |
| model.osmodel (read by the viewer) | 0.03 | 1.2 MB |

#### beam-20 (rcFrame, 20 storeys)

440 nodes, 1,020 elements (ElasticBeamColumn 1,020), 2,640 DOFs, 11 analysis cases; model.osmodel 760.7 kB. Run All 101.4 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 116.3 | 112.2 | – | 53 % | 144.4 | 25.4 | – | – |
| derive | ok | 448.9 | 436.1 | – | 60 % | 245.0 | 99.2 | – | 760.7 kB |
| analysis | ok | 14.7 | 0.5 | 7.4 | 70 % | 245.6 | 3.6 | 123.7 | 12.9 MB |
| ssi | skipped | 0.0 | 0.0 | – | 36 % | 246.3 | 0.0 | – | – |
| design | ok | 4,045.7 | 3,581.1 | 20.8 | 78 % | 534.2 | 288.9 | 131.5 | 35.4 MB |
| substructure | ok | 5.0 | 5.0 | – | 64 % | 397.5 | 15.7 | – | 510 B |
| mep | skipped | 0.0 | 0.0 | – | 56 % | 386.4 | 0.0 | – | – |
| boq | ok | 6.2 | 6.2 | – | 65 % | 391.9 | 5.5 | – | 567.4 kB |
| report | ok | 1,479.6 | 1,473.5 | – | 66 % | 2,987.7 | 2,604.5 | – | 58.8 MB |
| drawings | ok | 84.3 | 87.4 | – | 67 % | 3,972.6 | 1,125.1 | – | 143.6 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 5.94 | 3.4 kB |
| results/tables | 23.76 | 15.8 MB |
| fem/storyResponse | 5.81 | 273.2 kB |
| fem/seismicDesign | 5.20 | 28.1 kB |
| fem/secondOrder | 0.02 | 51 B |
| fem/columnInteraction | 1,167.94 | 16.7 MB |
| design/required | 1,723.64 | 3.7 MB |
| drawings/list | 0.02 | 59.1 kB |
| results/view (every result) ×36 | 39.38 | 38.4 MB |
| model.osmodel (read by the viewer) | 0.01 | 760.7 kB |

#### beam-30 (rcFrame, 30 storeys)

650 nodes, 1,530 elements (ElasticBeamColumn 1,530), 3,900 DOFs, 11 analysis cases; model.osmodel 1.1 MB. Run All 117.8 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 245.3 | 238.1 | – | 62 % | 155.2 | 36.6 | – | – |
| derive | ok | 903.0 | 741.1 | – | 86 % | 281.2 | 124.7 | – | 1.1 MB |
| analysis | ok | 44.4 | 0.5 | 17.7 | 100 % | 280.3 | 2.5 | 175.8 | 18.9 MB |
| ssi | skipped | 0.1 | 0.0 | – | 100 % | 281.7 | 0.1 | – | – |
| design | ok | 4,294.9 | 4,149.0 | 0.1 | 66 % | 762.2 | 480.6 | 187.4 | 53.0 MB |
| substructure | ok | 10.8 | 8.8 | – | 76 % | 533.5 | 14.1 | – | 510 B |
| mep | skipped | 0.1 | 0.0 | – | 91 % | 516.8 | 0.0 | – | – |
| boq | ok | 9.8 | 9.6 | – | 56 % | 524.4 | 7.6 | – | 849.7 kB |
| report | ok | 1,711.0 | 1,704.5 | – | 39 % | 4,453.8 | 3,943.1 | – | 88.7 MB |
| drawings | ok | 91.5 | 98.8 | – | 43 % | 5,770.2 | 1,548.5 | – | 210.5 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 6.40 | 3.4 kB |
| results/tables | 28.11 | 23.7 MB |
| fem/storyResponse | 7.57 | 401.0 kB |
| fem/seismicDesign | 4.55 | 39.7 kB |
| fem/secondOrder | 0.01 | 51 B |
| fem/columnInteraction | 6,923.80 | 27.0 MB |
| design/required | 2,139.81 | 5.8 MB |
| drawings/list | 0.05 | 82.5 kB |
| results/view (every result) ×36 | 53.78 | 57.9 MB |
| model.osmodel (read by the viewer) | 0.02 | 1.1 MB |

</details>

### The 10-storey buildings on `012dc5e8`

The machine was busier for these runs (the load column reads 92–100 % throughout: other
sessions' tests and cross-checks ran alongside), so their wall times are longer across the
board and their CPU times are inflated too, by hyperthreads sharing cores. Compare the work by
the call counts of the 3-storey profiles instead, which are **the same on both bases** for
derive, design and the report (542,256 `moment_capacity`, 492 `section_properties`, 23
interaction surfaces in the frame's design step), plus the new face forces
(`saengine/design/face_forces.py:341`, about 3 % of the design step). Two changes are real:

| | `6c5968b1` | `012dc5e8` | |
| --- | ---: | ---: | --- |
| beam-10: analysis cases | 11 | 15 | storey mass lumping and the new cases |
| beam-10: drawings, CPU s | 39 | **951** | the drawings design everything again (hotspot 4) |
| flat-10: elements | 1,492 | **5,060** | the 500 mm mesh |
| flat-10: analysis | 6.4 min | **failed** | the band solver (hotspot 1) |
| core-10: analysis | 6.4 min | **> 1 h 55 min, 10.4 GB** | the band solver, stopped |

On the flat plate whose analysis failed, `fem/columnInteraction` and `design/required` still
spent 10 and 17 minutes running the design over empty results before answering with nothing.

<details><summary>beam-10, flat-10, core-10 on 012dc5e8</summary>

#### beam-10 (rcFrame, 10 storeys)

230 nodes, 510 elements (ElasticBeamColumn 510), 1,380 DOFs, 15 analysis cases; model.osmodel 624.7 kB. Run All 165.9 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 105.7 | 71.0 | – | 92 % | 134.9 | 15.3 | – | – |
| derive | ok | 402.1 | 279.8 | – | 97 % | 215.3 | 77.0 | – | 676.4 kB |
| analysis | ok | 27.7 | 0.7 | 0.0 | 100 % | 149.4 | 5.3 | 11.4 | 8.3 MB |
| ssi | skipped | 0.1 | 0.0 | – | 100 % | 150.1 | 0.0 | – | – |
| design | ok | 4,942.1 | 2,935.5 | 0.0 | 99 % | 309.4 | 159.3 | 77.5 | 19.1 MB |
| substructure | ok | 8.7 | 5.5 | – | 100 % | 152.5 | 24.4 | – | 510 B |
| mep | skipped | 0.0 | 0.0 | – | 100 % | 152.7 | 0.1 | – | – |
| boq | ok | 8.4 | 4.5 | – | 100 % | 171.8 | 19.1 | – | 285.1 kB |
| report | ok | 2,297.0 | 1,261.6 | – | 100 % | 1,312.6 | 1,139.8 | – | 29.2 MB |
| drawings | ok | 2,265.8 | 951.2 | – | 100 % | 1,157.6 | 96.9 | – | 77.6 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 14.17 | 3.8 kB |
| results/tables | 60.17 | 9.6 MB |
| fem/storyResponse | 16.77 | 162.8 kB |
| fem/seismicDesign | 5.23 | 15.7 kB |
| fem/secondOrder | 0.03 | 51 B |
| fem/columnInteraction | 2,673.22 | 8.0 MB |
| design/required | 4,943.28 | 1.8 MB |
| drawings/list | 0.43 | 32.0 kB |
| results/view (every result) ×40 | 74.77 | 21.5 MB |
| model.osmodel (read by the viewer) | 0.03 | 624.7 kB |

#### core-10 (rcFrameWithWalls, 10 storeys)

4,830 nodes, 5,330 elements; stopped during the analysis after 1 h 55 min (a 10.4 GB solver),
so the counts the script takes after the run and the payloads are missing.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 71.7 | 45.2 | – | 93 % | 137.6 | 17.9 | – | – |
| derive | ok | 525.3 | 362.4 | – | 97 % | 198.0 | 60.3 | – | 3.9 MB |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |

#### flat-10 (flatSlab, 10 storeys)

4,830 nodes, 5,060 elements (Shell 4,580, ElasticBeamColumn 480), 28,980 DOFs, 15 analysis cases; model.osmodel 3.7 MB. Run All 5.8 min.

| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load | Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| generate | ok | 0.9 | 0.8 | – | 99 % | 125.9 | 6.1 | – | – |
| derive | ok | 334.6 | 243.1 | – | 94 % | 238.0 | 111.9 | – | 3.7 MB |
| analysis | failed | 14.0 | 0.9 | 0.0 | 100 % | 218.0 | 11.5 | 11.4 | 253 B |

| Payload | Time (s) | JSON |
| --- | ---: | ---: |
| results/list | 0.43 | 31 B |
| results/tables | 0.79 | 4.3 kB |
| fem/storyResponse | 0.19 | 2.0 kB |
| fem/seismicDesign | 0.56 | 224 B |
| fem/secondOrder | 0.11 | 51 B |
| fem/columnInteraction | 607.73 | 153 B |
| design/required | 1,006.13 | 328 B |
| drawings/list | 0.06 | 59 B |
| model.osmodel (read by the viewer) | 0.28 | 3.7 MB |

</details>

## The parity round's mesh and the band solver

`960d8569` meshes slabs and walls at 500 mm by default (with a convergence check). On the
10-storey flat plate that takes the model from 1,318 nodes and 1,492 elements to **4,830 nodes
and 5,060 elements** (4,580 shells), about 29,000 DOFs, and the core building to 5,330
elements. Derive itself copes (335 s for the flat plate, 525 s for the core building, from
114 s and 198 s). The analysis does not:

| Building on `012dc5e8` | Elements | Analysis |
| --- | ---: | --- |
| flat-10 | 5,060 | **failed** after 14 s: "Static analysis failed at step 1/1 (ops.analyze returned -1)"; Run All stops there |
| core-10 | 5,330 | still running after **1 h 55 min, 4,800 CPU s, a 10.4 GB working set**, when the benchmark stopped it (the machine had 0.4 GB left) |
| flat-10, the same model with `"system": "UmfPack"` (a scratch copy, run by hand) | 5,060 | the dead load case in **15 s**, about 10 s of it the solver's start-up |

The cause is the linear solver derive asks for, `BandGeneral` (`saengine/fem/derive.py:1699`,
`:1729`, `:1834`), with the rigid diaphragms: under the Transformation handler each floor's
master node couples every node of its floor, so the band is about a floor wide. Its storage,
n × (2b + 1) numbers, reaches gigabytes at this size; the flat plate's failure in 14 s is most
likely that allocation failing on a machine short of memory. A sparse solver does not fill the
band: on the 10-storey frame, `UmfPack` and `BandGeneral` give the same displacements to 1e-14
(cases D, WX, EX). This is fix 1 below. The response spectrum design re-runs every case in its
own solver process with a 3,600 s timeout (`saengine/fem/seismic_design.py:531`), so with the
band solver it would time out on these buildings too.

## Where the time goes

Across the buildings, **design** is 45–80 % of Run All, the **report** 15–25 % (it runs the
design checks again), **derive** 5–25 % (the frames: section analyses), and the **analysis**
under 1 % for the frames and 7 % for the shell buildings on the old mesh. Every step grows
about linearly with the number of members: from 3 to 10 storeys (3.3× the members) the design
step's calls to its slow functions grow 3.3–3.9×, with no quadratic loop. From 10 to 20
storeys the frame's design CPU grows 2.5×: the larger lower columns take more column types and
interaction surfaces, and the 20-storey run had a busier machine (hyperthreads sharing a core
inflate CPU time too).

What a step costs is set by how often SAEngine repeats an expensive calculation, not by the
size of the model: the 30-storey frame has 16 distinct sections and 1,530 elements, and its
design runs the checks of all 1,530 at every station and combination four or five times over.
The 3-storey profiles (`profile/<case>/profiles/*.txt`) attribute the time:

| Step (3 storeys, profiled) | Time | Where |
| --- | ---: | --- |
| derive, frame | 298 s | `section_properties` 85 % |
| design, frame | 1,152 s | `section_properties` 40 %, the second design pass (`gather`) 25 %, `ductile_joints` strengths 17 %, interaction surfaces 16 %, `moment_capacity` 15 % (overlapping) |
| design, flat plate | 1,306 s | the second design pass 45 %, `moment_capacity` 24 %, wall design 25 %, `section_properties` 16 % |
| report, frame | 232 s | the design checks again 68 %, the model derived again 30 % |
| `fem/columnInteraction`, frame | 242 s | the design checks again (`gather`) 80 % |
| generate, frame | 114 s | the column sizing's interaction surfaces 88 % |
| analysis (the solver process) | 15–23 s | Python imports ≈ 11 s, HDF5 writes of one dataset per id; OpenSees `analyze` 0.1–7 s |

## The top 10 hotspots

Ranked by what they cost the buildings measured. Shares are of the step's time in the 3-storey
profiles (`profile/<case>/profiles/<step>.prof`); the 10–30 storey timings above show the same
steps growing with the member count.

1. **The shell buildings' analysis uses a dense band solver (`012dc5e8`).** Every case derive
   writes has `"system": "BandGeneral"` (`saengine/fem/derive.py:1699`, `:1729`, `:1834`).
   The rigid floor diaphragms make OpenSees use the Transformation constraint handler, and each
   floor's master node then couples every node of the floor, so the band is about a floor
   wide; band LU costs about n·b² per factorisation and stores n × (2b + 1) numbers. With the
   parity round's 500 mm mesh (the 10-storey flat plate: 4,830 nodes, 5,060 elements, about
   29,000 DOFs) the analysis **failed** in Run All ("Static analysis failed at step 1/1
   (ops.analyze returned -1)" after 14 s, most likely the band storage not allocated), and in
   the 10-storey core building it ran for **1 h 55 min and 4,800 CPU seconds, reaching a 10.4
   GB working set**, before the benchmark was stopped. The same flat plate's model with
   `"system": "UmfPack"` runs its dead load case in **15 s** (about 10 s of it the solver's
   start-up), and on the 10-storey frame UmfPack and BandGeneral give the same displacements to
   1e-14 (cases D, WX, EX). The response spectrum design re-runs every case in a second solver
   process (hotspot 10), with a 3,600 s timeout.
2. **`section_properties` runs a finite-element section analysis for every member, uncached.**
   `saengine/library/sections.py:95` meshes the profile and runs sectionproperties'
   geometric *and warping* analysis (about 1.1 s of CPU for a 400 × 400 rectangle), to read
   A, Ixx, Iyy and J. It is called per element, not per section type:
   `saengine/fem/derive.py:567` (`section()` returns the area through a second
   `section_properties(...)` call on every frame element, outside the `b.section_ids` cache
   of line 535) and `saengine/design/slender.py:643` (`gross_factor`, per element, in every
   design pass), plus the other design and report callers. The 30-storey tower has **16
   distinct profiles** and calls it about 1,500 times in derive alone. Share: **85 % of
   derive** (254 of 298 s), **40 % of the design step** (464 of 1,152 s), 60 % of the report
   (138 of 232 s), 37 % of `fem/columnInteraction`. Measured cost on the frames: 6–15 minutes
   of derive, and about as much again in each design pass.
3. **The member design checks run four or five times per Run All and viewing.** The design
   step runs `design()` twice: `design_report` (`saengine/design/check.py:104`), then
   `design_required` → `required.gather` (`saengine/design/required.py:195`), which runs the
   whole check again with `collect` to gather the demands. The report runs it a third time
   (`saengine/report/build.py:1262` `_design` calls `saengine.design.design_report`
   directly, not the kept `design-report.json` of `saengine/pipeline/design_mode.py`).
   `fem/columnInteraction` (`saengine/fem/member_detail.py:300`) runs `gather` a fourth time,
   and `design/required` a fifth when its kept answer has gone stale (hotspot 4). Share:
   `gather` is 25–45 % of the design step, `design_report` 68–78 % of the report, `gather`
   80 % of `fem/columnInteraction`. Measured cost: the report's 11–28 minutes are mostly this,
   and `fem/columnInteraction` takes 12 minutes on 10 storeys, 115 on 30.
4. **Caches written into the results folder make the kept design checks stale.**
   `inputs_stamp` (`saengine/pipeline/design_mode.py:55`) hashes every file of
   `08 FEM/model.results` except `_DERIVED` (line 37). Two files written there are missing
   from it:
   - `column-interaction.json` (`saengine/fem/member_detail.py:33`), written by
     `fem/columnInteraction`: after opening the column view, the next `design/required` (the
     Properties panel, the report's required steel) works everything out again, **21 minutes
     on 10 storeys, 29 on 20, 36 on 30** in the payload tables;
   - on `012dc5e8`, `face-forces.json`, written by the design step itself
     (`saengine/design/check.py:738` `_face_forces_file`, on its first use inside `design()`,
     after `run_all._design` took its stamp): the design checks and required steel that Run
     All's design step keeps are stale as soon as it ends, so the **drawings step designs
     everything again** (`saengine/pipeline/drawings.py:201` `_design_inputs`: 792 of the
     3-storey drawings' 888 s; on the 10-storey frame the drawings went from **39 to 951 CPU
     seconds**, the same 38 sheets), and so does every later reader of the kept checks.
5. **Interaction surfaces are rebuilt from concreteproperties point by point, in every pass.**
   `InteractionSurface.__init__` (`saengine/design/rc.py:577`) computes 25–50 meridians of
   about 30 depths each, every point a `concreteproperties`
   `calculate_ultimate_section_actions` (`rc.py:639` `_point`: about 0.05–0.15 s each, with a
   polygon split per call). Surfaces are kept per type within one `design()` call only, so
   each pass of hotspot 3, `fem/columnInteraction`, and the generator's column sizing
   (`saengine/library/generator.py:749`, `:840`, 88 % of `generate`) build them again. Share:
   16–20 % of the design step, 18 % of `fem/columnInteraction`.
6. **`moment_capacity` is evaluated one demand at a time.** `InteractionSurface.check` →
   `moment_capacity` → `contour` (`saengine/design/rc.py:701`, `:675`, `:655`) is called
   542,256 times in the 3-storey frame's design step and 722,656 times in the flat plate's
   (every station × combination × member), each building the contour at its own Pu with
   numpy on arrays of ~100 points: the numpy call overhead dominates. Share: 15 % (frame) to
   24 % (flat plate) of the design step.
7. **Wall strain compatibility: a 70-step bisection that re-rotates the polygon every time.**
   `FlangedSurface.nominal` (`saengine/design/wall_flanges.py:711`) bisects the neutral-axis
   depth 70 times; each `actions` (`:634`) calls `_frame` (`:622`), which rotates the shapely
   polygon and the bars for the same angle again, then clips. 291,600 `actions` calls in the
   flat plate's 3-storey design step; `walls.py:473` / `:530` do the same for plain walls
   (765,168 calls). Share: `design_walls` is **25 % of the flat plate's design step** (331 of
   1,306 s), and with the core walls' it is why the flat plate and core buildings take longer
   to design than the frame with as many members.
8. **The ductile-joint strengths miss their memo.** `saengine/design/ductile_joints.py:100`
   keys strengths by `id(section)` and the exact axial force (`round(axial, 0)`): the sections
   are new objects in each pass of hotspot 3, and each member's own Pu is a new key, so
   `column_moment` runs a `concreteproperties` `ultimate_bending_capacity` (an iterative
   neutral-axis search) per member and sense. Share: 17 % of the frame's design step (190 s).
9. **The report derives the model again, and Typst keeps gigabytes.** `_model_summary`
   (`saengine/report/build.py:674`) → `_derive_again` (`:839`) calls `derive_fem` on the whole
   building (hotspot 2 inside it) for counts and loads that `08 FEM/model.osmodel` and the
   derive step's summary hold: 15–30 % of the report. The report step's memory grows by 1.3 GB
   on 10 storeys, 2.6 GB on 20 and 3.9 GB on 30 (the backend then holds 4.5 GB, on a 16 GB
   laptop that also runs the workbench). That memory is **Typst's**: on the 10-storey frame
   `report_data` peaks at 326 MB with a 2.4 MB JSON (nearly all of it the design section),
   then `render_pdf` (`saengine/report/build.py:181`, Typst in the backend's process) takes the
   process to 1,460 MB in 8 s to typeset a 30 MB PDF, and the memory is not given back.
10. **Solver runs and result files.** The analysis itself is quick for the frames (44 s of
    wall time on 30 storeys; OpenSees `analyze` is 0.1–7 s of a 15–23 s solver run on 3
    storeys): each solver process spends about 11 s importing, and
    `opensees_studio/services/result_store.py:78` `_write_int_dict` / `:84` `_read_int_dict`
    write and read **one HDF5 dataset per node or element** (4,968 datasets for the 3-storey
    frame's analysis, 17,612 for the flat plate's; 16,508 reads for one `results/tables`),
    which every reader pays again (`results/tables`, `results/view`, the design's demands,
    `fem/memberForces`). The design step also runs a **second solver process over every case**
    for the response spectrum design (`saengine/fem/seismic_design.py:522` `_run`): on the
    old mesh's core building that run took 103 of the design step's 138 minutes on a machine
    short of memory. And the payloads are built whole: on 10 storeys `results/tables` is 8–38
    MB of JSON, `results/view` 19–32 MB over 36 results, `fem/columnInteraction` 7–8 MB (27
    MB on 30 storeys).

## Proposed fixes, ranked

By gain for effort; the estimates are for the 10–30 storey buildings measured here. None of
these is implemented in this change.

| # | Fix | Where | Gain | Effort |
| --- | --- | --- | --- | --- |
| 1 | **A sparse solver for the derived cases**: `"system": "UmfPack"` (or Mumps where the OpenSeesPy build has it) instead of `BandGeneral`, at least when the model has shells or diaphragms; RCM numbering stays. Checked: the same displacements to 1e-14 on the 10-storey frame. | `fem/derive.py:1699`, `:1729`, `:1834` | Shell buildings on `012dc5e8`: analysis from failing or hours (10 GB) to about a minute; the response spectrum design's run likewise | XS |
| 2 | **Memoise `section_properties`** by the profile (`functools.lru_cache` on `profile.model_dump_json()`), and use closed forms for rectangles and circles (A = bh, I = bh³/12, J by the series of Roark Table 10.7; sectionproperties only for other shapes). Fix the uncached second call at `fem/derive.py:567`. | `library/sections.py:95`, `fem/derive.py:567`, `design/slender.py:643` | Derive **5–10×** (minutes → seconds), design −40 %, report −60 % | XS (an hour) |
| 3 | **Add `column-interaction.json` and `face-forces.json` (`end_zones.FACE_FORCES_FILE`) to `_DERIVED`**; better: let the stamp list what it *includes*, the analysis outputs, rather than what it excludes, so the next cache written there cannot do this again. | `pipeline/design_mode.py:37` | Drawings on `012dc5e8`: 951 → about 40 CPU s on 10 storeys; `design/required` after viewing: 21–36 min → instant | XS |
| 4 | **Run the design checks once per run** and reuse them: the design step calls `gather` once (`design()` with `collect`) and keeps both the report and the required steel from it (`design-report.json`, `design-required.json`); the report reads the kept report through `design_mode.design_report` instead of `saengine.design.design_report`; `fem/columnInteraction` is written by the design step from the same `collect`. | `pipeline/run_all.py:468`, `design/required.py:195`, `report/build.py:1262`, `fem/member_detail.py:300` | Design step **≈ 2×**, report **3–4×**, column interaction view 12–115 min → seconds | S–M |
| 5 | **Read the model summary from the derived model** instead of `_derive_again`: the derive step already returns nodes, elements, base shear and weight; keep them in `model.osmodel`'s `meta` (or a side file) and read them. | `report/build.py:674`, `:839` | Report −15–30 % | S |
| 6 | **Cache interaction surfaces by section signature** (outline, bars, f'c, fy, Es, spiral) across passes, in the process and on disk beside the results (`model.results/surfaces/<hash>.npy`, a few kB each), shared by the generator, the design checks, Design mode and the column interaction view. | `design/rc.py:577`, `design/required.py:593`, `library/generator.py:733` | Design −15–20 %, generator −80 %, column view −20 % | S |
| 7 | **Batch `moment_capacity`**: check all stations and combinations of a member in one call: contours for an array of Pu (the meridian crossings vectorised over Pu), rays for all demands at once. | `design/rc.py:655`, `:675`, `:701`; callers in `design/check.py` | Design −15–25 % | S–M |
| 8 | **Wall strain compatibility**: compute `_frame(theta)` once per angle (cache it on the surface), replace the 70-step bisection by Brent's method (`scipy.optimize.brentq`, about 10 evaluations), and a closed form for rectangular blocks. | `design/wall_flanges.py:622`, `:634`, `:711`; `design/walls.py:473`, `:530` | Wall design **5–10×**; flat plate and core design −20 % | S |
| 9 | **Key the ductile-joint memo by section signature** and take Mn(P) from the cached interaction surface (interpolated on its meridians) instead of an `ultimate_bending_capacity` solve per member. | `design/ductile_joints.py:100`, `:155` | Design −10–17 % | S |
| 10 | **Vectorise the surface itself**: for rectangular sections with bars, integrate the stress block and the bars with numpy over all depths of a meridian at once (closed-form block of a rotated rectangle, bars as arrays) instead of one concreteproperties call per point; concreteproperties stays for other outlines and as the test oracle. | `design/rc.py:626`, `:639` | Surface build **20–50×** | M |
| 11 | **Parallel design checks**: once 2–10 make each check cheap and free of shared state, split the elements over a `concurrent.futures.ProcessPoolExecutor` (by storey or by type; the surfaces of fix 6 shared on disk). The machines here have 4–8 cores. | `design/check.py:184` | Design **2–3×** more on 4 cores | M |
| 12 | **Fewer, lighter solver runs**: results stored as arrays (one dataset per quantity: ids and an n × k array, a format version, a reader for the old layout); the solver's heavy modules imported lazily; the response spectrum design's modal-force cases run with the analysis (or the run kept while the model does not change, as it is now, but started once, not per caller). | `opensees_studio/services/result_store.py:78`, `:84`; `opensees_studio/run.py`; `fem/seismic_design.py:522` | Solver runs −30–50 %; every results reader faster | M |
| 13 | **Lazy, smaller payloads and the report out of process**: `results/tables` per case and paged (the workbench shows one table at a time); the 3D view's displacements and forces as float32 arrays (base64) rather than JSON lists. The Typst memory is a note for now: typesetting in a child process would give the 1–4 GB back when it ends, and keeping the per-member design tables to the governing check (the full tables as CSV/XLSX beside the PDF) would keep the PDF to tens of pages. | `rpc/handlers.py:150`, `fem/display.py:354`, `report/build.py:181` | Payloads 3–5× smaller; the backend no longer keeps 1–4 GB after a report | M |

Fixes 1–5 are small and independent and remove most of the time. On the old base's 10-storey
frame (CPU minutes: derive 5.6, design 23.7, report 10.9) fixes 2–5 leave derive under a
minute, the design about 7–9 minutes and the report 2–3, so Run All goes from 50 minutes to
about 10–15, and the viewer's first column interaction and required-steel views from 34
minutes to seconds. Fix 1 makes the parity round's mesh usable for the flat plate and core
buildings. Fixes 6–10 then make the remaining design work proportional to the number of
distinct sections rather than members, and fix 11 uses the other cores.

## Limits of these measurements

- **A shared, busy machine.** A 4-core / 8-thread laptop with 16 GB, with Windows Defender
  (`MsMpEng`) and other sessions' test runs keeping it at 50–100 % load, and up to five
  benchmark processes at once. Wall times are inflated by up to 2.5× where the machine load
  column shows 100 %; **CPU seconds** are less affected, but hyperthreads sharing a core
  inflate them too at full load, so across runs on different days compare the profiles' call
  counts. Each case was run once.
- **The solver's CPU and memory** are often missing (0.0, –, or the launcher's 4–11 MB): the
  virtual environment's `python.exe` is a launcher that starts the interpreter as its own
  child, and on a loaded machine the sampler often did not find that child in time (the
  script now looks for 5 s). Where it is missing, the gap between wall and CPU time in
  `analysis` and `design` is the solver.
- **`012dc5e8` was measured on the 10-storey buildings only**: the flat plate and the core
  building did not get past the analysis (see the parity round section), and the 30-storey
  frame was not repeated, its work being the same as on `6c5968b1` by the call counts.
- **The foundations are not exercised**: the generated mat reports "foundations 0 pass, 0
  fail" (no soil report, no column loads assigned to it), and MEP has nothing to check. A
  project with a soil report, piles or a raft on springs adds the raft model and the
  fixed-base run, which this benchmark does not measure.
- **Template bars**: every member fails its checks (the template bars are placeholders),
  which is the same work as passing ones; Design mode's proposal (`design/proposal`) is not
  timed.
- The step order matches Run All, but each step opens the project afresh, as the app does
  after editing; the process memory is cumulative, so the growth column, not the peak, is a
  step's own need.
