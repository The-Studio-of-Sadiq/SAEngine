"""Part 1, the soil report: what the boreholes give the foundation design.

- :mod:`saengine.soil.profile`: stresses, SPT corrections and layer parameters of a borehole;
- :mod:`saengine.soil.site_class`: the code pack's site class from the SPT;
- :mod:`saengine.soil.bearing`: allowable bearing pressure of spread footings;
- :mod:`saengine.soil.settlement`: immediate and consolidation settlement;
- :mod:`saengine.soil.liquefaction`: SPT liquefaction screening (Idriss & Boulanger 2014);
- :mod:`saengine.soil.piles`: pile parameters per layer and the subgrade modulus;
- :mod:`saengine.soil.importer`: CSV and Excel import, and its template; AGS4 and DIGGS
  import and export (:mod:`saengine.soil.ags`, :mod:`saengine.soil.diggs`, alpha 9 L8);
- :mod:`saengine.soil.report`: the JSON-ready API the workbench calls.

The data model is :mod:`saengine.library.soil`.
"""

from saengine.soil.importer import export_soil, import_soil, soil_template
from saengine.soil.report import allowable_bearing, footing_settlement, soil_report

__all__ = [
    "allowable_bearing",
    "export_soil",
    "footing_settlement",
    "import_soil",
    "soil_report",
    "soil_template",
]
