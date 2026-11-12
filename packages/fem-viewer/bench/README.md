# FEM viewer benchmark

Times the viewer (`dist/fem-viewer.js`) on a 30-storey building of about 56,000 elements, in an
Electron window placed off-screen (x = -4000). The building and its results are synthesised by
`synth.js` in the shape the editor passes them: an `.osmodel`'s nodes and elements, and
`results/view` payloads with 11 stations per frame element. Pass `--model` to use a derived
`.osmodel` instead; results are still synthesised for it.

```bash
cd packages/fem-viewer && npm run build && cd ../..
"workbench/.build/electron/Code - OSS.exe" packages/fem-viewer/bench --out=bench.json
```

The options are `--storeys=30`, `--model=<file.osmodel>`, `--theme=dark|light`, `--out=<file.json>`,
and `--shots=<folder>`. With `--shots` it saves screenshots instead of timing: the model, a few
results, and a storey plan, drawn with the editor's colours under Dark Modern or Light Modern.

## What it measures

| Key | Measurement |
| --- | --- |
| `firstFrame` | `createFemViewer` + `setModel` + `setVisibleElements(undefined)`, as the editor loads a model; time to the first frame drawn |
| `orbit*` | Frame rate while orbiting 2° per frame for 180 frames (model alone, member labels, contour, mode animation, one storey); draw calls, triangles, GPU geometries and textures |
| `switch.*` | `setResults` until the next frame: deflected shape, diagrams, contour, utilisation, reactions, scale change, mode shape; cold (first time) and warm |
| `select`, `isolate`, `theme` | Selection under a diagram, one storey isolated and back, a theme change |
| `memory` | JS heap (the least of a few full collections) and GPU objects before and after five model switches and `dispose` |
| `idleFps` | The window's own frame rate with nothing drawn, which caps the rates above |

## Results (2026-10-25, 54,576 nodes, 56,400 elements, 17.6 MB results payload)

Medians of three runs, measured on the same machine:

| | Before | After |
| --- | ---: | ---: |
| `setModel` | 657 ms | 219 ms |
| First frame | 806 ms | 333 ms |
| Orbit, model (draw calls) | 57.7 fps (71) | 57.3 fps (6) |
| Orbit, 400 member labels (draw calls, textures) | 42.6 fps (474, 401) | 39.8 fps (10, 2) |
| Orbit, mode animation | 44.7 fps | 49.8 fps |
| Switch to deflected shape | 1,142 ms | 227 ms |
| Switch to Mz diagram / another case | 620 / 690 ms | 242 / 167 ms |
| Switch to Mz with member labels | 1,274 ms | 455 ms |
| Switch to M11 contour | 695 ms | 196 ms |
| Switch to utilisation | 622 ms | 226 ms |
| Switch to reactions / change scale | 382 / 529 ms | 47 / 47 ms |
| Switch to mode shape | 845 ms | 256 ms |
| Results off | 269 ms | 1 ms |
| Select / deselect an element under a diagram | 455 / 328 ms | 34 / 74 ms |
| Isolate a storey / back to all / "all" again | 199 / 742 / 755 ms | 127 / 393 / 1 ms |
| JS heap with the model | 99.9 MB | 102.9 MB |
| GPU geometries / textures after 5 model switches | 5 / 1 | 5 / 1 |

Orbit frame rates are GPU-bound at about 45 to 60 fps on this machine, so they barely change.
Per-frame CPU is what dropped: a frame with member labels took 20 ms of `render` before and
1.3 ms after (474 draw calls became 10). On a contended CPU, the first "before" run fell to 22 fps
with member labels and 29 fps on the model alone, against 40 and 57 fps after.
