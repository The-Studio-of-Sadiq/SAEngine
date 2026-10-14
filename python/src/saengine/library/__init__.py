"""Project libraries: physical materials (Part 3) and structural object types (Part 4)."""

from saengine.library.defaults import default_material_library, default_object_library
from saengine.library.materials import Material, MaterialLibrary
from saengine.library.objects import ObjectLibrary, ObjectType

__all__ = [
    "Material",
    "MaterialLibrary",
    "ObjectLibrary",
    "ObjectType",
    "default_material_library",
    "default_object_library",
]
