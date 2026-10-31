"""SAEngine's public Python API for plugins, scripts and other programs (docs/sdk/README.md).

Everything named in :data:`__all__` is the *versioned* API: its names, parameters and results
change only with :data:`API_VERSION` (SemVer: a new minor version adds, a new major version may
change or remove). Everything else in the ``saengine`` package is internal and may change in any
release. The same operations are reachable from other languages through the JSON-RPC server
(``python -m saengine.rpc.server``, methods in docs/sdk/reference.md) and the command line
(``saengine ...``, docs/cli.md).

Import lazily: ``from saengine import api`` loads nothing heavy until a name is used.

    from saengine import api
    print(api.API_VERSION)
    for pack in api.list_packages(kind=None):
        print(pack.id, pack.kind, pack.scope)
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

#: The version of this API (not of SAEngine): ``saengine.api.API_VERSION``.
API_VERSION = "1.0.0"

#: name -> (module, attribute): the versioned API, imported when first used.
_EXPORTS: dict[str, tuple[str, str]] = {
    # packages (design codes, structure and building templates)
    "list_packages": ("saengine.codes.registry", "list_packs"),
    "package_info": ("saengine.codes.registry", "info"),
    "load_package": ("saengine.codes.registry", "load"),
    "active_code_pack": ("saengine.codes.registry", "active"),
    "validate_package": ("saengine.codes.registry", "validate"),
    "install_package": ("saengine.codes.registry", "install"),
    "remove_package": ("saengine.codes.registry", "uninstall"),
    "trust_package": ("saengine.codes.registry", "set_trusted"),
    "CodePackError": ("saengine.codes.registry", "CodePackError"),
    "PackManifest": ("saengine.codes.manifest", "PackManifest"),
    "PackInfo": ("saengine.codes.manifest", "PackInfo"),
    "structure_presets": ("saengine.codes.catalogue", "structure_presets"),
    "building_templates": ("saengine.codes.catalogue", "building_templates"),
    "coded_geometry": ("saengine.codes.coded", "coded_geometry"),
    "CodedTemplate": ("saengine.codes.contents", "CodedTemplate"),
    # geometry of special structures
    "Geometry": ("saengine.library.shapes", "Geometry"),
    "ShapeInput": ("saengine.library.shapes", "ShapeInput"),
    "shape_geometry": ("saengine.library.shapes", "shape_geometry"),
    "insert_geometry": ("saengine.library.shapes", "insert"),
    # buildings
    "BuildingSpec": ("saengine.library.generator", "BuildingSpec"),
    "generate_building": ("saengine.library.generator", "generate_building"),
    # project archives (.civil)
    "export_project": ("saengine.project.archive", "export_project"),
    "import_project": ("saengine.project.archive", "import_project"),
    "inspect_archive": ("saengine.project.archive", "inspect_archive"),
    "template_problems": ("saengine.project.archive", "template_problems"),
}

if TYPE_CHECKING:  # the names as the lazy __getattr__ gives them, for type checkers
    from saengine.codes.catalogue import building_templates, structure_presets
    from saengine.codes.coded import coded_geometry
    from saengine.codes.contents import CodedTemplate
    from saengine.codes.manifest import PackInfo, PackManifest
    from saengine.codes.registry import CodePackError
    from saengine.codes.registry import active as active_code_pack
    from saengine.codes.registry import info as package_info
    from saengine.codes.registry import install as install_package
    from saengine.codes.registry import list_packs as list_packages
    from saengine.codes.registry import load as load_package
    from saengine.codes.registry import set_trusted as trust_package
    from saengine.codes.registry import uninstall as remove_package
    from saengine.codes.registry import validate as validate_package
    from saengine.library.generator import BuildingSpec, generate_building
    from saengine.library.shapes import Geometry, ShapeInput, shape_geometry
    from saengine.library.shapes import insert as insert_geometry
    from saengine.project.archive import (
        export_project,
        import_project,
        inspect_archive,
        template_problems,
    )

__all__ = [
    "API_VERSION",
    "BuildingSpec",
    "CodePackError",
    "CodedTemplate",
    "Geometry",
    "PackInfo",
    "PackManifest",
    "ShapeInput",
    "active_code_pack",
    "building_templates",
    "coded_geometry",
    "export_project",
    "generate_building",
    "import_project",
    "insert_geometry",
    "inspect_archive",
    "install_package",
    "list_packages",
    "load_package",
    "package_info",
    "remove_package",
    "shape_geometry",
    "structure_presets",
    "template_problems",
    "trust_package",
    "validate_package",
]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"saengine.api has no {name!r} (see saengine.api.__all__)")
    value = getattr(importlib.import_module(target[0]), target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return list(__all__)


def exports() -> dict[str, tuple[str, str]]:
    """The versioned names and where each lives (for the generated reference)."""
    return dict(_EXPORTS)
