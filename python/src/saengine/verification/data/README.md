# Third-party data of the verification pack

## bsi-building-architecture-ifc2x3.ifc

- **What:** `Building-Architecture.ifc` of the "Simple-Scene" set, IFC2X3 (CoordinationView 2.0),
  exported by the IFC manager for SketchUp 5.6.0 (header dated 2026-06-23). Four walls with
  `Qto_WallBaseQuantities`, two spaces, three slabs, one storey.
- **Source:** buildingSMART International, Sample-Test-Files,
  <https://github.com/buildingSMART/Sample-Test-Files/tree/main/IFC%202.3.0.1%20(IFC%202x3%20TC1)/Simple-Scene>
- **Licence:** © buildingSMART International Ltd., licensed under the Creative Commons
  Attribution 4.0 International License (<https://creativecommons.org/licenses/by/4.0/>), as the
  repository's `LICENSE` states. Copied unchanged, only renamed.
- **Used by:** case DI1 (`cases/bim_mep.py`), which validates it and adopts its walls and rooms
  through the architect-IFC import.

No openly licensed Revit- or ArchiCAD-exported sample could be confirmed for this (issue #299):
buildingSMART's older Revit and ArchiCAD files were removed from that repository's history, and
the licence of KIT's AC20-FZK-Haus is not stated where it is published.
