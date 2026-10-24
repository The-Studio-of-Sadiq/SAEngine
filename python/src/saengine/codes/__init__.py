"""Code packs: the design code (reference data, factors, combinations) as a replaceable unit.

A pack is a folder with ``pack.json`` (:mod:`saengine.codes.manifest`), ``data/<table>.json``
tables (validated by the models of :mod:`saengine.codes.tables`) and optional trusted hooks.
Packs extend other packs and override only the tables they provide
(:mod:`saengine.codes.merge`). Usage::

    from saengine.codes import registry, CodePack

    pack = registry.active(settings, project_root)  # settings.codePack, default "bnbc2020"
    pack.table("combinations")
"""

from saengine.codes import registry
from saengine.codes.manifest import PackInfo, PackManifest, Problem
from saengine.codes.registry import (
    DEFAULT_PACK,
    CodePack,
    CodePackError,
    CodePackHookError,
    Registry,
    register,
)

__all__ = [
    "DEFAULT_PACK",
    "CodePack",
    "CodePackError",
    "CodePackHookError",
    "PackInfo",
    "PackManifest",
    "Problem",
    "Registry",
    "register",
    "registry",
]
