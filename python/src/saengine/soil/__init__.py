"""Part 1, the soil report: what the boreholes give the foundation design.

- :mod:`saengine.soil.profile`: stresses, SPT corrections and layer parameters of a borehole;
- :mod:`saengine.soil.site_class`: BNBC 2020 site class from the top 30 m;
- :mod:`saengine.soil.bearing`: allowable bearing pressure of spread footings;
- :mod:`saengine.soil.settlement`: immediate and consolidation settlement;
- :mod:`saengine.soil.liquefaction`: SPT liquefaction screening (Idriss & Boulanger 2014);
- :mod:`saengine.soil.piles`: pile parameters per layer and the subgrade modulus;
- :mod:`saengine.soil.importer`: CSV and Excel import, and its template;
- :mod:`saengine.soil.report`: the JSON-ready API the workbench calls.

The data model is :mod:`saengine.library.soil`.
"""

from saengine.soil.importer import import_soil, soil_template
from saengine.soil.report import allowable_bearing, footing_settlement, soil_report

__all__ = ["allowable_bearing", "footing_settlement", "import_soil", "soil_report", "soil_template"]
