"""Table model of the bar bending schedule's standard (alpha 9 track C14): ``barSchedule``.

A pack names the standard its schedules follow (``standard``) and gives the standards it knows
(``standards``: BS 8666, ACI 315 / CRSI, IS 2502, EN ISO 3766, ...). A standard is data: its
shape codes with their dimension letters and cutting-length formulas (expressions in the
dimension letters, the bar size ``d``, the bend radius ``r``, the link hook's extension ``ext``
and the standard's bend deductions; :func:`saengine.drawings.bbs.evaluate`), its minimum
scheduling radii and end projections, the rounding of the lengths, the bar size label, the
schedule's columns and sheet title, and the shape sketches of the drawing set. The engine
(:mod:`saengine.drawings.bbs`) has no shape or formula of its own.

A project picks another standard with the override ``barSchedule.standard``; a standard the
pack in force does not give is taken from the built-in pack that gives it (named in the
schedule's notes). Every number is the pack's; the pack's VERIFY.md gives each clause.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, TableModel, _Group


class RadiusStep(_Group):
    """Bars up to ``upTo`` [mm] (None: every larger bar): a radius of ``factor`` × d, rounded up
    to a whole millimetre when ``ceil``."""

    upTo: Positive | None = Field(default=None, description="Bar size up to [mm]; None: above.")
    factor: Positive = Field(description="Minimum radius as a multiple of d.")
    ceil: bool = Field(default=False, description="Round the radius up to a whole mm.")


class MinimumRadius(_Group):
    """The standard's minimum scheduling radius r [mm]: ``bySize`` (bar size [mm] as text ->
    r), else the first of ``steps`` that holds the bar."""

    bySize: dict[str, Positive] = Field(default_factory=dict, description="r [mm] by bar size.")
    steps: list[RadiusStep] = Field(default_factory=list, description="r for other sizes.")


class EndProjection(_Group):
    """The standard's minimum straight end projection P [mm]: ``bySize``, else r + ``radiusDb``
    × d rounded up to ``roundTo``."""

    bySize: dict[str, Positive] = Field(default_factory=dict, description="P [mm] by bar size.")
    radiusDb: Positive = Field(description="P = r + this × d for other sizes.")
    roundTo: Positive = Field(default=5.0, description="... rounded up to this [mm].")


class ShapeSketch(_Group):
    """A shape's sketch for the drawing set's shape key: polylines in a box of about 1 × 1
    (``paths``, each a list of (x, y)), and where each dimension letter is written."""

    paths: list[list[tuple[float, float]]] = Field(description="Polylines of the bar.")
    labels: dict[str, tuple[float, float]] = Field(
        default_factory=dict, description="Dimension letter -> (x, y) of its label."
    )


class BarShape(_Group):
    """A shape code: its dimension letters and its cutting length."""

    name: str = Field(description="What the shape is (straight, L bar, closed link, ...).")
    letters: str = Field(default="", description="The dimension letters scheduled, in order.")
    length: str = Field(
        description="Cutting length: an expression in the letters, d, r, ext, pi, the "
        "standard's deductions (b45, b90, b135, b180) and max, min, sqrt, ceil."
    )
    formula: str = Field(default="", description="The formula as printed (default 'L = ...').")
    defaults: dict[str, str] = Field(
        default_factory=dict, description="Letters that may be left out -> expression of them."
    )
    transverse: bool = Field(default=False, description="A link, tie or helix.")
    bends: int = Field(default=0, ge=0, description="Number of bends.")
    endCheck: bool = Field(
        default=False, description="Check the first and last letters against the end projection."
    )
    hook: str = Field(
        default="", description="Letter the schedule fills with the link hook when not given."
    )
    radius: str = Field(default="", description="Letter of a scheduled bend radius (noted if low).")
    counts: str = Field(default="", description="Letters that are counts, not mm (turns).")
    remarks: str = Field(default="", description="Remark printed with the bar (e.g. 'C = turns').")
    kind: Literal["bent", "straight", "special"] = Field(
        default="bent",
        description="straight: a bar with only a length is scheduled as A; special: as detailed.",
    )
    sketch: ShapeSketch | None = None


class BarScheduleColumn(_Group):
    """A column of the schedule: ``key`` (member, mark, size, shape, a letter, members,
    per_member, total_count, cutting_length, total_length, mass, remarks) and its title; the
    title's ``{len}`` is the display unit of lengths (mm)."""

    key: str
    title: str


class BarScheduleStandard(_Group):
    """One standard of bar scheduling."""

    name: str = Field(description="The standard as the notes name it (e.g. 'BS 8666').")
    edition: str = Field(default="", description="Its edition (e.g. 'BS 8666:2020').")
    title: str = Field(default="Bar bending schedule", description="The sheet title.")
    shapeTerm: str = Field(default="Shape codes", description="What it calls its shape codes.")
    roundTo: Positive = Field(default=25.0, description="Cutting lengths rounded to this [mm].")
    rounding: Literal["up", "nearest"] = Field(default="up", description="How they are rounded.")
    stockLength: Positive = Field(default=12_000.0, description="Longest bar delivered [mm].")
    radius: MinimumRadius | None = Field(
        default=None,
        description="The standard's minimum scheduling radius; the bend radius is the larger of "
        "it and half the code's least bend diameter (None: the code's alone).",
    )
    endProjection: EndProjection | None = Field(
        default=None, description="Minimum end projection P (None: not checked)."
    )
    linkHook: str = Field(
        default="ext + r + d",
        description="The outside dimension of a link's hooked end (expression in ext, r, d).",
    )
    linkHookRound: Positive = Field(default=5.0, description="... rounded up to this [mm].")
    deductions: dict[str, float] = Field(
        default_factory=dict,
        description="Bend deductions by angle ('45', '90', '135', '180') × d: b45, b90, ... in "
        "the formulas.",
    )
    sizeLabel: str = Field(default="Ø{d}", description="A bar size as printed ({d}: its size).")
    shapes: dict[str, BarShape] = Field(description="Shape code -> shape.")
    aliases: dict[str, str] = Field(
        default_factory=dict, description="Shape names of the detailing model -> shape code."
    )
    special: str = Field(default="99", description="The code of a special (as sketched) bar.")
    columns: list[BarScheduleColumn] = Field(description="The schedule's columns, in order.")
    note: str = Field(
        default="",
        description="The schedule's note: {name}, {bend} (the code's bend clause), {round} and "
        "{unit} are filled in.",
    )

    @model_validator(mode="after")
    def _known(self) -> BarScheduleStandard:
        missing = sorted({c for c in self.aliases.values() if c not in self.shapes})
        if missing:
            raise ValueError(f"aliases name shapes the standard does not give: {missing}")
        if self.special not in self.shapes:
            raise ValueError(f"the special shape {self.special} is not one of the shapes")
        return self


class BarScheduleTable(TableModel):
    """The bar bending schedule's standard (:mod:`saengine.drawings.bbs`): ``standard`` picks
    one of ``standards`` (or of a built-in pack's); ``shapeKey`` draws the sketches of the shape
    codes used on the schedule's sheets."""

    standard: str = Field(description="The standard the schedules follow (a key of standards).")
    shapeKey: bool = Field(
        default=False, description="Draw the shape key (sketches) on the schedule's sheets."
    )
    standards: dict[str, BarScheduleStandard] = Field(
        default_factory=dict, description="The standards this pack gives, by id."
    )
