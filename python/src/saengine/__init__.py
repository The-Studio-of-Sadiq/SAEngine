"""SAEngine Python backend.

The modelling core, OpenSees runner and result services come from the headless
part of opensees-studio (``third_party/opensees-studio``). This package only adds
what the SAEngine workbench needs on top: a JSON-RPC server and the glue that turns
opensees-studio objects into JSON for the workbench.
"""

# The SAEngine release this backend belongs to: always workbench/package.json's "version" (bumped
# together; tests/test_version.py checks it). Archives (.civil) record it.
__version__ = "0.0.34"
