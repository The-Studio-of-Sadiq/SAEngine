"""Material and object type actions (03 Materials, 04 Objects). A concrete's Ec follows f'c by
the code pack in force (:func:`saengine.design.rc_detailing.concrete_modulus`), a steel's Es is
the pack's; values are checked by the material and object models and the guardrails (the least
f'c of the pack, bar sizes, section sizes)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._util import Params, fmt, merge
from saengine.actions.errors import refuse
from saengine.actions.paths import MATERIALS, OBJECTS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView
from saengine.library.defaults import CONCRETE_DENSITY, STEEL_DENSITY


def _library(view: ProjectView) -> dict[str, Any]:
    data = view.part(MATERIALS, {"schema": "saengine.materials/1", "materials": []})
    data.setdefault("materials", [])
    return data


def _find(entries: list[dict[str, Any]], entry_id: str, what: str) -> dict[str, Any]:
    for e in entries:
        if e.get("id") == entry_id:
            return e
    known = ", ".join(e.get("id", "?") for e in entries) or "none"
    refuse(f"There is no {what} '{entry_id}' (the {what}s: {known}).", "id", entry_id)
    raise AssertionError  # pragma: no cover


def _free(entries: list[dict[str, Any]], wanted: str) -> str:
    ids = {e.get("id") for e in entries}
    if wanted not in ids:
        return wanted
    n = 2
    while f"{wanted}-{n}" in ids:
        n += 1
    return f"{wanted}-{n}"


def _concrete_e(fc: float, density: float | None) -> tuple[float, str]:
    from saengine.design.rc_detailing import concrete_modulus

    ec, how = concrete_modulus(fc, density)
    return round(ec, -1), how


def _steel_e() -> float:
    from saengine.library.defaults import _steel_e as pack_steel_e

    return pack_steel_e()


# ── materials ──


class ConcreteAddParams(Params):
    fc: float = Field(description="Specified compressive strength f'c [MPa].")
    id: str | None = Field(default=None, description="Default: C<f'c>.")
    name: str | None = None
    density: float = Field(default=CONCRETE_DENSITY, description="[kg/m³]")
    maxAggregate: float | None = Field(default=20, description="[mm]")
    E: float | None = Field(default=None, description="[MPa]; default: the pack's Ec of f'c.")
    makeDefault: bool = Field(
        default=False, description="Make it the project's concrete (types without their own)."
    )


@action(
    "material.concrete.add",
    summary="Add a concrete by its f'c (Ec by the code pack); optionally the project's concrete.",
    params=ConcreteAddParams,
    parts=("materials",),
    kind="edit",
    example={"fc": 28, "makeDefault": True},
)
def concrete_add(view: ProjectView, p: ConcreteAddParams) -> ActionResult:
    lib = _library(view)
    entries = lib["materials"]
    material_id = p.id or _free(entries, f"C{p.fc:g}")
    if any(e.get("id") == material_id for e in entries):
        refuse(f"There is a material '{material_id}' already.", "id", material_id)
    e, how = (p.E, "entered") if p.E is not None else _concrete_e(p.fc, p.density)
    entry = {
        "id": material_id,
        "name": p.name or f"Concrete f'c {fmt(p.fc)} MPa",
        "category": "concrete",
        "mechanical": {"E": e, "nu": 0.2, "density": p.density, "alpha": 1.0e-5},
        "concrete": {"fc": p.fc, **({"maxAggregate": p.maxAggregate} if p.maxAggregate else {})},
        "source": {"note": how},
    }
    entries.append(entry)
    if p.makeDefault:
        lib["defaults"] = {**(lib.get("defaults") or {}), "concrete": material_id}
    view.put(MATERIALS, lib)
    return ActionResult(
        message=f"Concrete {material_id} added: f'c {fmt(p.fc)} MPa, Ec {fmt(e)} MPa ({how})"
        + ("; the project's concrete." if p.makeDefault else "."),
        created=[material_id],
    )


class ConcreteSetParams(Params):
    id: str
    fc: float | None = Field(default=None, description="[MPa]; Ec follows unless E is given.")
    name: str | None = None
    density: float | None = None
    maxAggregate: float | None = None
    E: float | None = None
    makeDefault: bool | None = None


@action(
    "material.concrete.set",
    summary="Change a concrete (f'c, density, Ec, name); Ec follows a new f'c unless given.",
    params=ConcreteSetParams,
    parts=("materials",),
    kind="edit",
    example={"id": "C24.1", "fc": 25},
)
def concrete_set(view: ProjectView, p: ConcreteSetParams) -> ActionResult:
    lib = _library(view)
    entry = _find(lib["materials"], p.id, "material")
    if entry.get("category") != "concrete":
        refuse(f"{p.id} is a {entry.get('category')}, not a concrete.", "id", p.id)
    mech = entry.setdefault("mechanical", {})
    props = entry.setdefault("concrete", {})
    if p.fc is not None:
        props["fc"] = p.fc
        props.pop("ft", None)  # the modulus of rupture follows f'c again
    if p.maxAggregate is not None:
        props["maxAggregate"] = p.maxAggregate
    if p.density is not None:
        mech["density"] = p.density
    if p.E is not None:
        mech["E"] = p.E
    elif p.fc is not None or p.density is not None:
        mech["E"], how = _concrete_e(float(props["fc"]), mech.get("density"))
        entry.setdefault("source", {})["note"] = how
    if p.name:
        entry["name"] = p.name
    if p.makeDefault:
        lib["defaults"] = {**(lib.get("defaults") or {}), "concrete": p.id}
    view.put(MATERIALS, lib)
    return ActionResult(
        message=f"Concrete {p.id}: f'c {fmt(props['fc'])} MPa, Ec {fmt(mech.get('E', 0))} MPa."
    )


class SteelAddParams(Params):
    kind: Literal["rebar", "steel"] = Field(
        description="rebar: reinforcing bars; steel: structural steel."
    )
    fy: float = Field(description="Yield strength [MPa].")
    fu: float | None = Field(default=None, description="Tensile strength [MPa].")
    grade: str | None = Field(default=None, description="E.g. B500DWR, A992.")
    id: str | None = Field(default=None, description="Default: the grade.")
    name: str | None = None
    makeDefault: bool = Field(default=False, description="Rebar: make it the project's bars.")


@action(
    "material.steel.add",
    summary="Add reinforcing bars or a structural steel by fy (Es by the code pack).",
    params=SteelAddParams,
    parts=("materials",),
    kind="edit",
    example={"kind": "rebar", "fy": 500, "grade": "B500DWR"},
)
def steel_add(view: ProjectView, p: SteelAddParams) -> ActionResult:
    lib = _library(view)
    entries = lib["materials"]
    base = p.id or p.grade or f"{'R' if p.kind == 'rebar' else 'S'}{p.fy:g}"
    material_id = p.id or _free(entries, base)
    if any(e.get("id") == material_id for e in entries):
        refuse(f"There is a material '{material_id}' already.", "id", material_id)
    steel: dict[str, Any] = {"fy": p.fy}
    if p.grade:
        steel["grade"] = p.grade
    if p.fu is not None:
        steel["fu"] = p.fu
    entries.append(
        {
            "id": material_id,
            "name": p.name
            or f"{'Rebar' if p.kind == 'rebar' else 'Structural steel'} "
            f"{p.grade or f'fy {fmt(p.fy)} MPa'}",
            "category": p.kind,
            "mechanical": {"E": _steel_e(), "nu": 0.3, "density": STEEL_DENSITY, "alpha": 1.2e-5},
            "steel": steel,
        }
    )
    if p.makeDefault:
        if p.kind != "rebar":
            refuse("Only reinforcing bars can be the project's bars.", "makeDefault", True)
        lib["defaults"] = {**(lib.get("defaults") or {}), "rebar": material_id}
    view.put(MATERIALS, lib)
    return ActionResult(
        message=f"{p.kind.capitalize()} {material_id} added: fy {fmt(p.fy)} MPa.",
        created=[material_id],
    )


class SteelSetParams(Params):
    id: str
    fy: float | None = None
    fu: float | None = None
    grade: str | None = None
    name: str | None = None
    makeDefault: bool | None = None


@action(
    "material.steel.set",
    summary="Change reinforcing bars or a structural steel (fy, fu, grade, name).",
    params=SteelSetParams,
    parts=("materials",),
    kind="edit",
    example={"id": "B420DWR", "fy": 420},
)
def steel_set(view: ProjectView, p: SteelSetParams) -> ActionResult:
    lib = _library(view)
    entry = _find(lib["materials"], p.id, "material")
    if entry.get("category") not in ("rebar", "steel"):
        refuse(f"{p.id} is a {entry.get('category')}, not a steel.", "id", p.id)
    steel = entry.setdefault("steel", {})
    for name in ("fy", "fu", "grade"):
        value = getattr(p, name)
        if value is not None:
            steel[name] = value
    if p.name:
        entry["name"] = p.name
    if p.makeDefault:
        if entry["category"] != "rebar":
            refuse("Only reinforcing bars can be the project's bars.", "makeDefault", True)
        lib["defaults"] = {**(lib.get("defaults") or {}), "rebar": p.id}
    view.put(MATERIALS, lib)
    return ActionResult(message=f"{p.id}: fy {fmt(steel['fy'])} MPa.")


# ── object types ──

TYPE_KINDS = ("column", "beam", "slab", "wall", "footing")


class TypeParams(Params):
    id: str | None = Field(
        default=None, description="Default from the size, e.g. C400x400, B250x500, S125."
    )
    name: str | None = None
    material: str | None = Field(default=None, description="Default: the project's concrete.")
    width: float | None = Field(default=None, description="Columns, beams: section width [mm].")
    depth: float | None = Field(default=None, description="Columns, beams: section depth [mm].")
    diameter: float | None = Field(default=None, description="Round columns [mm].")
    profile: dict[str, Any] | None = Field(
        default=None, description="Columns, beams: any profile of 04 Objects (e.g. an I shape)."
    )
    thickness: float | None = Field(
        default=None, description="Slabs, walls, footings: thickness [mm]."
    )
    system: Literal["oneWay", "twoWay", "flat"] | None = Field(default=None, description="Slabs.")
    structural: bool | None = Field(default=None, description="Walls: false for partitions.")
    length: float | None = Field(default=None, description="Footings: along x [mm].")
    footingWidth: float | None = Field(default=None, description="Footings: along y [mm].")
    more: dict[str, Any] = Field(
        default_factory=dict, description="Other fields of the type (04 Objects' names); merged."
    )


class TypeSetParams(TypeParams):
    id: str = Field(description="The type to change.")  # type: ignore[assignment]


def _objects(view: ProjectView) -> dict[str, Any]:
    data = view.part(OBJECTS, {"schema": "saengine.objects/1", "objects": []})
    data.setdefault("objects", [])
    return data


def _profile(kind: str, p: TypeParams, current: dict[str, Any] | None) -> dict[str, Any] | None:
    if p.profile is not None:
        return p.profile
    if p.diameter is not None:
        return {"shape": "circle", "radius": p.diameter / 2}
    if p.width is not None or p.depth is not None:
        old = current if current and current.get("shape") == "rectangle" else {}
        width = p.width if p.width is not None else old.get("xDim")
        depth = p.depth if p.depth is not None else old.get("yDim")
        if width is None or depth is None:
            refuse(f"A rectangular {kind} needs both width and depth [mm].", "width", p.width)
        return {"shape": "rectangle", "xDim": width, "yDim": depth}
    return None


def _apply(kind: str, entry: dict[str, Any], p: TypeParams, adding: bool) -> None:
    if kind in ("column", "beam"):
        profile = _profile(kind, p, entry.get("profile"))
        if profile is not None:
            entry["profile"] = profile
        elif adding:
            refuse(
                f"A {kind} type needs its section: width and depth, a diameter or a profile.",
                "width",
                None,
            )
    if kind in ("slab", "wall", "footing"):
        if p.thickness is not None:
            entry["thickness"] = p.thickness
        elif adding:
            refuse(f"A {kind} type needs its thickness [mm].", "thickness", None)
    if kind == "slab" and p.system is not None:
        entry["system"] = p.system
    if kind == "wall" and p.structural is not None:
        entry["structural"] = p.structural
    if kind == "footing":
        for field, value in (("length", p.length), ("width", p.footingWidth)):
            if value is not None:
                entry[field] = value
            elif adding:
                refuse(f"A footing type needs its {field} [mm].", field, None)
    if p.material is not None:
        entry["material"] = p.material
    if p.name:
        entry["name"] = p.name
    if p.more:
        entry.update(merge(entry, p.more))


def _default_id(kind: str, entry: dict[str, Any]) -> str:
    prefix = {"column": "C", "beam": "B", "slab": "S", "wall": "W", "footing": "F"}[kind]
    profile = entry.get("profile") or {}
    if profile.get("shape") == "rectangle":
        return f"{prefix}{fmt(profile['xDim'])}x{fmt(profile['yDim'])}"
    if profile.get("shape") == "circle":
        return f"{prefix}D{fmt(2 * profile['radius'])}"
    if kind == "footing":
        return f"F{fmt(entry['length'])}x{fmt(entry['width'])}x{fmt(entry['thickness'])}"
    if "thickness" in entry:
        return f"{prefix}{fmt(entry['thickness'])}"
    return prefix


def _type_add(kind: str) -> Any:
    def run(view: ProjectView, p: TypeParams) -> ActionResult:
        lib = _objects(view)
        materials = view.read(MATERIALS, {"materials": []})
        entry: dict[str, Any] = {"kind": kind}
        _apply(kind, entry, p, adding=True)
        if "material" not in entry:
            from saengine.library.materials import Category, default_of

            entry["material"] = default_of(materials, Category.CONCRETE) or ""
            if not entry["material"]:
                refuse(
                    "Give the type's material: the project has no concrete yet.", "material", None
                )
        type_id = p.id or _free(lib["objects"], _default_id(kind, entry))
        if any(o.get("id") == type_id for o in lib["objects"]):
            refuse(f"There is an object type '{type_id}' already.", "id", type_id)
        entry = {
            "id": type_id,
            "name": entry.pop("name", None) or f"{kind.capitalize()} {type_id}",
            **entry,
        }
        lib["objects"].append(entry)
        view.put(OBJECTS, lib)
        return ActionResult(message=f"{kind.capitalize()} type {type_id} added.", created=[type_id])

    return run


def _type_set(kind: str) -> Any:
    def run(view: ProjectView, p: TypeSetParams) -> ActionResult:
        lib = _objects(view)
        entry = _find(lib["objects"], p.id, "object type")
        if entry.get("kind") != kind:
            refuse(f"{p.id} is a {entry.get('kind')} type, not a {kind} type.", "id", p.id)
        _apply(kind, entry, p, adding=False)
        view.put(OBJECTS, lib)
        return ActionResult(message=f"{kind.capitalize()} type {p.id} changed.")

    return run


_EXAMPLES = {
    "column": {"width": 400, "depth": 400},
    "beam": {"width": 250, "depth": 500},
    "slab": {"thickness": 125, "system": "twoWay"},
    "wall": {"thickness": 200},
    "footing": {"length": 1500, "footingWidth": 1500, "thickness": 450},
}

for _kind in TYPE_KINDS:
    action(
        f"type.{_kind}.add",
        summary=f"Add a {_kind} object type (its section and material) to 04 Objects.",
        params=TypeParams,
        parts=("objects",),
        kind="edit",
        example=_EXAMPLES[_kind],
    )(_type_add(_kind))
    action(
        f"type.{_kind}.set",
        summary=f"Change a {_kind} object type (section, material, name, other fields).",
        params=TypeSetParams,
        parts=("objects",),
        kind="edit",
        example={"id": "X", **_EXAMPLES[_kind]},
    )(_type_set(_kind))
