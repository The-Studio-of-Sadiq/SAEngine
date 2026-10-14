"""SAEngine Python backend.

The modelling core, OpenSees runner and result services come from the headless
part of opensees-studio (``third_party/opensees-studio``). This package only adds
what the SAEngine workbench needs on top: a JSON-RPC server and the glue that turns
opensees-studio objects into JSON for the workbench.
"""

__version__ = "0.1.0"
