"""Design overwrites of frame members: effective length factors, unbraced lengths and framing
type, per object type and per member, as the engineer sets them where the automatic values
do not fit (a column the model does not show braced, a beam braced by secondary members the
model leaves out, a sway frame designed with K from a buckling analysis).

A value set on the member wins over the one set on its object type, which wins over the
automatic one (:func:`resolve`); a value left empty (None) inherits. The checks say where each
value came from: "k = 1.20 (overwrite)" for the member's, "(type overwrite)" for the type's.

Axes follow the profile: ``k3``, ``Lu3`` for bending about the profile's x-axis (its width
axis: the depth ``yDim`` bends, ``Mx``; the major axis of a section deeper than wide, local 3 of
the usual frame programs), ``k2``, ``Lu2`` about its y-axis (``My``, local 2).

Used by:

- RC columns (:mod:`saengine.design.slender`, BNBC 2020 Part 6 Sec 6.3.10): k replaces the
  chart's or 1.0, Lu the unsupported length lu, ``framing`` "braced" designs the column as
  nonsway and "sway" as sway whatever its storey's stability index Q says (6.3.10.5 lets
  either be assumed when justified), ``momentMagnifiers`` replace Cm, δns or δs.
- Steel members (:mod:`saengine.design.steel.lengths`): k per axis (K), Lu per axis (the
  unbraced length for compression buckling), ``Lb`` the laterally unbraced length of the
  compression flange (lateral-torsional buckling).
- ``liveLoadReduction``: the factor on the floor live load L of the member, given instead of the
  one :mod:`saengine.design.live_reduction` works out (BNBC 2020 Part 6 Sec 2.3.13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The models live in the library (object types and floor-plan members carry them).
from saengine.library.modifiers import DesignOverwrites, Framing, MomentMagnifiers

#: Where a resolved value came from.
MEMBER = "member"
TYPE = "type"
DEFAULT = "default"

_SOURCE_TEXT = {MEMBER: " (overwrite)", TYPE: " (type overwrite)", DEFAULT: ""}


#: The fields resolved one by one (``momentMagnifiers`` per factor).
FIELDS = ("k2", "k3", "Lb", "Lu2", "Lu3", "framing", "cm", "deltaNs", "deltaS", "liveLoadReduction")


def _flat(value: DesignOverwrites | dict[str, Any] | None) -> dict[str, Any]:
    """The set fields of an overwrite, the magnifiers flattened."""
    if value is None:
        return {}
    if not isinstance(value, DesignOverwrites):
        value = DesignOverwrites.model_validate(value)
    found = {k: getattr(value, k) for k in FIELDS if hasattr(value, k)}
    if value.momentMagnifiers is not None:
        for k in ("cm", "deltaNs", "deltaS"):
            found[k] = getattr(value.momentMagnifiers, k)
    return {k: v for k, v in found.items() if v is not None}


@dataclass
class Resolved:
    """A member's overwrites after merging: per field (value, source)."""

    values: dict[str, tuple[Any, str]] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        found = self.values.get(name)
        return default if found is None else found[0]

    def source(self, name: str) -> str:
        found = self.values.get(name)
        return DEFAULT if found is None else found[1]

    def has(self, name: str) -> bool:
        return name in self.values

    def text(self, name: str) -> str:
        """ " (overwrite)", " (type overwrite)" or "" for the value's source."""
        return _SOURCE_TEXT[self.source(name)]

    def __bool__(self) -> bool:
        return bool(self.values)

    # ── per bending axis of the profile ("x": Mx, local 3; "y": My, local 2) ──

    def k(self, axis: str) -> float | None:
        return self.get("k3" if axis == "x" else "k2")

    def k_text(self, axis: str) -> str:
        return self.text("k3" if axis == "x" else "k2")

    def lu(self, axis: str) -> float | None:
        return self.get("Lu3" if axis == "x" else "Lu2")

    def lu_text(self, axis: str) -> str:
        return self.text("Lu3" if axis == "x" else "Lu2")

    def notes(self) -> list[str]:
        """What the overwrites change, for the member's notes."""
        out = []
        for name in FIELDS:
            if name in self.values:
                value, source = self.values[name]
                shown = f"{value:g}" if isinstance(value, float) else str(value)
                out.append(f"{name} = {shown}{_SOURCE_TEXT[source]}")
        return out


def overwrites_of(item: Any) -> DesignOverwrites | dict[str, Any] | None:
    """The ``designOverwrites`` of an object type, building element or floor-plan member (an
    attribute or a dict key), or None."""
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get("designOverwrites")
    return getattr(item, "designOverwrites", None)


def resolve(
    member: Any = None,
    object_type: Any = None,
    member_overwrites: DesignOverwrites | dict[str, Any] | None = None,
    type_overwrites: DesignOverwrites | dict[str, Any] | None = None,
) -> Resolved:
    """A member's overwrites, merged member > type > default: from the ``designOverwrites`` of
    ``member`` and ``object_type`` (or the overwrites given directly, which take precedence
    over those read from them)."""
    of_type = _flat(type_overwrites if type_overwrites is not None else overwrites_of(object_type))
    of_member = _flat(member_overwrites if member_overwrites is not None else overwrites_of(member))
    values: dict[str, tuple[Any, str]] = {k: (v, TYPE) for k, v in of_type.items()}
    values.update({k: (v, MEMBER) for k, v in of_member.items()})
    return Resolved(values)


def resolve_all(
    members: list[tuple[str, Any, Any]],
    by_member: dict[str, DesignOverwrites | dict[str, Any]] | None = None,
) -> dict[str, Resolved]:
    """The resolved overwrites of the members ``(id, element, object type)`` that have any;
    ``by_member``: overwrites per member id found elsewhere (the floor-plan member an element
    was generated from), used when the element carries none."""
    found: dict[str, Resolved] = {}
    for member_id, element, object_type in members:
        own = overwrites_of(element)
        if own is None and by_member:
            own = by_member.get(member_id)
        resolved = resolve(None, object_type, own, None)
        if resolved:
            found[member_id] = resolved
    return found


# ─────────────────────────────────── steel ───────────────────────────────────


def steel_length_options(resolved: Resolved | None, base: Any = None) -> Any:
    """The steel members' :class:`saengine.design.steel.lengths.LengthOptions` with the
    overwrites applied (K per axis, unbraced lengths per axis and for LTB), from ``base`` (the
    project's, or the defaults)."""
    from saengine.design.steel.lengths import LengthOptions

    base = base if isinstance(base, LengthOptions) else LengthOptions()
    if not resolved:
        return base
    k = dict(base.k)
    unbraced = dict(base.unbraced)
    sources = dict(base.sources)
    for axis, k_name, lu_name in (("x", "k3", "Lu3"), ("y", "k2", "Lu2")):
        if resolved.has(k_name):
            k[axis] = float(resolved.get(k_name))
            sources[f"k{axis}"] = resolved.source(k_name)
        if resolved.has(lu_name):
            unbraced[axis] = float(resolved.get(lu_name)) * 1e-3
            sources[f"L{axis}"] = resolved.source(lu_name)
    if resolved.has("Lb"):
        unbraced["ltb"] = float(resolved.get("Lb")) * 1e-3
        sources["Lb"] = resolved.source("Lb")
    return LengthOptions(
        k=k,
        slab_braces_top_flange=base.slab_braces_top_flange,
        unbraced=unbraced,
        sources=sources,
    )


def steel_options(resolved: Resolved | None, base: Any = None) -> Any:
    """:class:`saengine.design.steel.SteelOptions` (``base``, or the defaults) with the
    member's length overwrites (:func:`steel_length_options`)."""
    from saengine.design.steel.members import SteelOptions

    options = SteelOptions.of(base)
    if not resolved:
        return options
    import dataclasses

    return dataclasses.replace(options, lengths=steel_length_options(resolved, options.lengths))


__all__ = [
    "DEFAULT",
    "FIELDS",
    "MEMBER",
    "TYPE",
    "DesignOverwrites",
    "Framing",
    "MomentMagnifiers",
    "Resolved",
    "overwrites_of",
    "resolve",
    "resolve_all",
    "steel_length_options",
    "steel_options",
]
