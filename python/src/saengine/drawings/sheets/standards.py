"""The office's drafting standard on the sheets (Project Settings > Drawings > Office standard,
:class:`saengine.library.settings.DraftingStandard`): its layer names, colours and lineweights,
the text font, the dimension arrows and the sheet number prefixes.

How it is used:

- :meth:`Standard.setup` sets the font and the arrows of a new sheet's DXF
  (:class:`~saengine.drawings.sheets.layout.Sheet` calls it);
- :meth:`Standard.apply` renames the layers to the office's names and sets their colours and
  lineweights just before a sheet is written (:func:`~saengine.drawings.sheets.build.write_drawings`);
  until then every view draws on SAEngine's own layers, so the label placement, the sheet index
  and the revision clouds (:mod:`.revisions`) work on one scheme;
- :meth:`Standard.restore` renames an earlier sheet's layers back before its edits are compared
  with what SAEngine drew (:func:`~saengine.drawings.sheets.revisions.carry_edits`).

A layer's office name must be a valid DXF layer name, unique, and not a name of SAEngine's own
scheme (renaming must be reversible): an entry that breaks this is skipped and listed in
:attr:`Standard.problems`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from saengine.drawings.sheets.layout import LAYERS

FONTS: dict[str, str] = {
    "Arial": "arial.ttf",
    "Arial Narrow": "arialn.ttf",
    "Calibri": "calibri.ttf",
    "Segoe UI": "segoeui.ttf",
    "Tahoma": "tahoma.ttf",
}
"""The fonts offered (Windows TrueType fonts) and their files."""

DEFAULT_PREFIXES: dict[str, str] = {
    "structural": "S-",
    "architectural": "A-",
    "plumbing": "P-",
    "mechanical": "M-",
    "electrical": "E-",
    "fire": "FP-",
    "coordination": "MC-",
}
"""The sheet number prefix of each discipline (S-101, A-101, P-101, ...)."""

_INVALID = re.compile(r'[<>/\\":;?*|=`]')
OWN = {name.upper(): name for name, *_ in LAYERS}
STANDARD_SCHEMA = "saengine.drafting-standard/1"
"""The schema of an office standard saved as a file (Drawings, Office standard)."""


@dataclass
class LayerRule:
    name: str
    color: int | None = None
    lineweight: int | None = None  # 1/100 mm


@dataclass
class Standard:
    """The drafting standard as the sheets apply it."""

    name: str = ""
    font: str = "Arial"
    arrows: str = "tick"
    rules: dict[str, LayerRule] = field(default_factory=dict)  # SAEngine layer -> its rule
    prefixes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PREFIXES))
    office_line: str = ""
    disclaimer: str = ""
    problems: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Standard:
        """From the ``standard`` of the drawing settings (the settings model's dump)."""
        data = data or {}
        out = cls(
            name=str(data.get("name") or ""),
            font=str(data.get("font") or "Arial"),
            arrows=str(data.get("arrows") or "tick"),
            office_line=str(data.get("officeLine") or ""),
            disclaimer=str(data.get("disclaimer") or ""),
        )
        if out.font not in FONTS:
            out.problems.append(f"Office standard: font {out.font!r} not offered, Arial used.")
            out.font = "Arial"
        for key in DEFAULT_PREFIXES:
            value = data.get(f"{key}Prefix")
            if isinstance(value, str) and value.strip():
                out.prefixes[key] = value.strip()
        if len(set(out.prefixes.values())) < len(out.prefixes):
            out.problems.append(
                "Office standard: two disciplines share a sheet prefix, the default prefixes "
                "are used."
            )
            out.prefixes = dict(DEFAULT_PREFIXES)
        prefix = str(data.get("layerPrefix") or "")
        if prefix and _INVALID.search(prefix):
            out.problems.append(f"Office standard: layer prefix {prefix!r} has characters DXF "
                                "does not allow, not used.")  # fmt: skip
            prefix = ""
        entries = {}
        for entry in data.get("layers") or []:
            if not isinstance(entry, dict):
                continue
            own = OWN.get(str(entry.get("layer") or "").strip().upper())
            if own is None:
                out.problems.append(
                    f"Office standard: {entry.get('layer')!r} is not a layer of SAEngine's "
                    "scheme (docs/drawings-layers.md), skipped."
                )
                continue
            entries[own] = entry
        taken: dict[str, str] = {}
        for own in (name for name, *_ in LAYERS):
            entry = entries.get(own, {})
            name = str(entry.get("name") or "").strip() or f"{prefix}{own}"
            lineweight = entry.get("lineweight")
            rule = LayerRule(
                name,
                int(entry["color"]) if entry.get("color") else None,
                round(float(lineweight) * 100) if lineweight else None,
            )
            if name != own:
                problem = None
                if _INVALID.search(name) or not name:
                    problem = "has characters DXF does not allow"
                elif name.upper() in OWN:
                    problem = "is a layer of SAEngine's scheme"
                elif name.upper() in taken:
                    problem = f"is also the name of {taken[name.upper()]}"
                if problem:
                    out.problems.append(
                        f"Office standard: the name {name!r} of {own} {problem}; {own} kept."
                    )
                    rule.name = own
            taken[rule.name.upper()] = own
            if rule.name != own or rule.color or rule.lineweight:
                out.rules[own] = rule
        return out

    @property
    def renames(self) -> dict[str, str]:
        """SAEngine layer -> office name, for the layers named otherwise."""
        return {own: r.name for own, r in self.rules.items() if r.name != own}

    @property
    def is_default(self) -> bool:
        return not self.rules and self.font == "Arial" and self.arrows == "tick"

    # ── on a sheet ──

    def setup(self, doc: Any) -> None:
        """The font of the text styles and the arrows of the dimension styles of ``doc``."""
        import ezdxf

        font = FONTS.get(self.font, "arial.ttf")
        for style in doc.styles:
            if style.dxf.name in ("Standard", "SAE"):
                style.dxf.font = font
                style.set_extended_font_data(self.font)
        arrows = {
            "tick": ezdxf.ARROWS.architectural_tick,
            "closed": ezdxf.ARROWS.closed_filled,
            "dot": ezdxf.ARROWS.dot_small,
            "oblique": ezdxf.ARROWS.oblique,
        }.get(self.arrows, ezdxf.ARROWS.architectural_tick)
        if self.arrows != "tick":
            for style in doc.dimstyles:
                if str(style.dxf.name).startswith("SAE-"):
                    style.set_arrows(blk=arrows)

    def apply(self, doc: Any) -> None:
        """The office's layer names, colours and lineweights in ``doc`` (just before saving)."""
        for own, rule in self.rules.items():
            if own not in doc.layers:
                continue
            layer = doc.layers.get(own)
            if rule.color:
                layer.color = rule.color
            if rule.lineweight:
                layer.dxf.lineweight = rule.lineweight
            if rule.name != own and rule.name not in doc.layers:
                layer.rename(rule.name)

    def restore(self, doc: Any) -> None:
        """SAEngine's layer names back in an earlier sheet ``doc`` written with this standard."""
        restore_names(doc, self.renames)


def restore_names(doc: Any, renames: dict[str, str] | None) -> None:
    """SAEngine's layer names back in ``doc``, written with ``renames`` (SAEngine layer ->
    office name; the drawings record keeps those of the last generation)."""
    for own, name in (renames or {}).items():
        if own in OWN.values() and name in doc.layers and own not in doc.layers:
            try:
                doc.layers.get(name).rename(own)
            except ValueError:
                continue
