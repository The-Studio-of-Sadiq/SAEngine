"""Strut-and-tie models of D-regions (``08 FEM/strut-and-tie.json``).

A D-region the deep members' own checks do not cover (a dapped end, a corbel with several loads,
a frame corner, a wall or beam with an opening, a continuous deep beam) is drawn as a plane truss
of struts and ties joined at nodes, in its own x-y plane (x along the member, y up; mm). Its
boundary is held by supports (the B-regions next to it, or bearings), and each load case puts
the factored forces from the analysis on its nodes (kN). :mod:`saengine.design.stm_model` solves
the truss and checks every strut, tie and nodal zone with the code pack's strut-and-tie
procedure.

The file only stores what the engineer drew and chose; forces and checks are worked out on
demand. Units: mm, mm², MPa, kN, degrees.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_ID = "saengine.strutAndTie/1"

#: The file beside the analysis model.
FILE_NAME = "strut-and-tie.json"

Support = Literal["", "pin", "rollerX", "rollerY"]
MemberKind = Literal["strut", "tie"]
StrutShape = Literal["prism", "bottle", "tension", "other"]
Anchorage = Literal["", "hook", "plate", "through"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StmNode(_Model):
    """A node of the truss."""

    id: str = Field(min_length=1, description='Name of the node ("N1").')
    x: float = Field(description="Position along the member [mm].")
    y: float = Field(description="Position up [mm].")
    support: Support = Field(
        default="",
        description='"pin" holds x and y; "rollerX" holds y only (rolls along x); '
        '"rollerY" holds x only; "" free.',
    )
    bearing: float = Field(
        default=0.0,
        ge=0,
        description="Length of the bearing plate or column face that loads the node [mm]: its "
        "face is checked against the reaction or the applied load; 0: not checked.",
    )
    anchorage: Anchorage = Field(
        default="",
        description='How the ties ending here are anchored: "hook" (standard hooks, their '
        'length checked against anchorLength), "plate" (a bearing plate or mechanical device), '
        '"through" (the bars run through and develop beyond); "": not given.',
    )
    anchorLength: float = Field(
        default=0.0,
        ge=0,
        description="Length available to develop the ties past the point where their centroid "
        "leaves the extended nodal zone [mm].",
    )


class StmMember(_Model):
    """A strut or a tie between two nodes."""

    id: str = Field(min_length=1, description='Name of the member ("S1", "T1").')
    start: str = Field(description="Node at one end.")
    end: str = Field(description="Node at the other end.")
    kind: MemberKind = Field(default="strut")
    width: float = Field(
        default=0.0,
        ge=0,
        description="Strut: its width ws at the narrower end [mm]. Tie: its effective width wt "
        "[mm] (0: the tie's node faces are not checked).",
    )
    shape: StrutShape = Field(
        default="bottle",
        description='Strut: "prism" (uniform section, a compression zone), "bottle" (wider '
        'at mid-length than at its ends), "tension" (in a tension member or flange), '
        '"other".',
    )
    steelArea: float = Field(
        default=0.0,
        ge=0,
        description="Strut: area of anchored, tied compression bars along it [mm²].",
    )
    barArea: float = Field(default=0.0, ge=0, description="Tie: area of its bars Ats [mm²].")
    barDiameter: float = Field(
        default=0.0, ge=0, description="Tie: diameter of its bars [mm] (anchorage)."
    )
    prestressArea: float = Field(
        default=0.0, ge=0, description="Tie: area of prestressing steel Atp [mm²]."
    )
    fse: float = Field(
        default=0.0, ge=0, description="Tie: effective stress in the prestressing steel [MPa]."
    )
    fpy: float = Field(
        default=0.0, ge=0, description="Tie: yield strength of the prestressing steel [MPa]."
    )
    bonded: bool = Field(default=True, description="Tie: the prestressing steel is bonded.")

    @model_validator(mode="after")
    def _distinct_ends(self) -> StmMember:
        if self.start == self.end:
            raise ValueError(f"member {self.id} starts and ends at node {self.start}")
        return self


class StmLoad(_Model):
    node: str
    fx: float = Field(default=0.0, description="Force along x [kN].")
    fy: float = Field(default=0.0, description="Force along y (up) [kN].")


class StmLoadCase(_Model):
    name: str = Field(min_length=1, description="The factored combination these forces are of.")
    loads: list[StmLoad] = Field(default_factory=list)


class StmWebLayer(_Model):
    """A layer of distributed bars crossing the struts (stirrups, side bars)."""

    area: float = Field(gt=0, description="Area of the layer's bars at one spacing [mm²].")
    spacing: float = Field(gt=0, description="Spacing [mm].")
    angle: float = Field(
        default=90.0, description="Direction of the bars from the x axis [degrees] (90: stirrups)."
    )


class StmModel(_Model):
    """One D-region and its strut-and-tie model."""

    name: str = Field(min_length=1, description='Name ("Dapped end of B12").')
    member: str = Field(default="", description='The analysis member it belongs to ("B12").')
    template: str = Field(default="", description="The template it was started from.")
    thickness: float = Field(gt=0, description="Thickness bs of the region [mm].")
    depth: float = Field(
        default=0.0, ge=0, description="Depth h of the member [mm] (the D-region's extent)."
    )
    fc: float = Field(gt=0, description="f'c [MPa].")
    fy: float = Field(gt=0, description="fy of the tie and web bars [MPa].")
    lam: float = Field(default=1.0, gt=0, le=1, description="λ of lightweight concrete.")
    nodes: list[StmNode] = Field(default_factory=list)
    members: list[StmMember] = Field(default_factory=list)
    cases: list[StmLoadCase] = Field(default_factory=list)
    web: list[StmWebLayer] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> StmModel:
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("two nodes have the same name")
        names = [m.id for m in self.members]
        if len(set(names)) != len(names):
            raise ValueError("two members have the same name")
        known = set(ids)
        for m in self.members:
            for end in (m.start, m.end):
                if end not in known:
                    raise ValueError(f"member {m.id}: no node {end}")
        for case in self.cases:
            for load in case.loads:
                if load.node not in known:
                    raise ValueError(f"case {case.name}: no node {load.node}")
        return self


class StrutAndTieFile(_Model):
    schema_: str = Field(default=SCHEMA_ID, alias="$schema")
    models: list[StmModel] = Field(default_factory=list)
