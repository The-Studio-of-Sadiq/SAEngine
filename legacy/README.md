# Legacy prototypes

Kept for reference only. Nothing here is built, tested, or shipped.

- `python/` — first PySide6 desktop prototype: ribbon/panels GUI, custom
  direct-stiffness frame solver (`core/analysis.py`), stdlib HTTP service, and
  grid/story/unit models. Superseded by the OpenSeesPy backend built on the
  headless core of [opensees-studio](https://github.com/ogunc/opensees-studio).
- `extensions/saengine/` — plain-JS VS Code extension with webview panels
  (soil report importer, materials/object editors, Canvas 2D structure preview).
  Superseded by native Code - OSS contributions in `workbench/src/vs/workbench/contrib`.
  The soil-report and materials ideas will be revisited in Parts 1 and 2.
