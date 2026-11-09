"""Table models of the nonlinear stability analysis and of the finite element check of steel
joints (alpha 9 tracks L4 and L6).

``nonlinearStability`` (:mod:`saengine.fem.nonlinear_stability`, :mod:`saengine.fem.cables`):
the geometrically and materially nonlinear analysis with imperfections (GMNIA) of steel frames
and plated parts, and the large-displacement analysis of cables. The pack picks:

- the **equivalent imperfections**: the member bow ``bow`` (method ``curveRatio``: e0 = L / the
  ratio of the member's buckling curve, the EN 1993-1-1 Table 5.1 form; ``fixedRatio``: one
  ratio for every member, the AISC 360 Appendix 1 out-of-straightness form) and the frame sway
  ``sway`` (method ``heightAndColumns``: φ = φ0 αh αm, the EN 1993-1-1 5.3.2(3) form;
  ``fixedRatio``: one out-of-plumbness ratio, the AISC 360 Appendix 1 form);
- the **eigenmode-affine imperfection** ``eigenmode`` (method ``memberBow``: the first
  buckling mode scaled so that the member that moves most in it gets the bow amplitude of the
  pack; ``fixedRatio``: scaled to that member's length over a ratio) and the plated parts'
  amplitude ``plates`` (method ``panelRatio``: the panel's shorter side over a ratio, the
  EN 1993-1-5 Annex C Table C.2 form; ``dimple``: the EN 1993-1-6 dimple amplitude parameter of
  the fabrication class times the shell's √(r t));
- the **material**: the yield strength and modulus factors of the model (``yieldFactor``,
  ``stiffnessFactor``) and the strain hardening ratio;
- the **path**: the default solver, steps and stopping rules;
- **cables**: the design tension resistance as a share of the breaking force.

``connectionFe`` (:mod:`saengine.design.connection_fe`): the component-based finite element
model of a steel joint: the plastic strain limit, the material model, the bolt stiffness method,
the stiffness classification bounds and the mesh.

A pack without these tables gets the default pack's (SAEngine practice, stated in the results).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, Share, TableModel, _Row

# ─────────────────────────────── nonlinearStability ───────────────────────────────


class BowImperfection(_Row):
    """The equivalent bow imperfection e0 of a member: L / ratio."""

    method: Literal["curveRatio", "fixedRatio"] = Field(
        description="curveRatio: by the member's buckling curve (ratios); fixedRatio: one "
        "ratio (fixedRatio) for every member."
    )
    ratios: dict[str, Positive] = Field(
        default_factory=dict, description="Buckling curve -> L / e0 (elastic analysis)."
    )
    plasticRatios: dict[str, Positive] = Field(
        default_factory=dict,
        description="Buckling curve -> L / e0 when the members' plasticity is modelled (empty: "
        "the elastic ratios).",
    )
    defaultCurve: str | None = Field(
        default=None, description="The curve of a member whose curve is not known."
    )
    fixedRatio: Positive | None = Field(default=None, description="L / e0 of fixedRatio.")

    @model_validator(mode="after")
    def _complete(self) -> BowImperfection:
        if self.method == "curveRatio":
            if not self.ratios or self.defaultCurve not in self.ratios:
                raise ValueError("bow curveRatio: needs ratios and a defaultCurve among them")
        elif self.fixedRatio is None:
            raise ValueError("bow fixedRatio: needs fixedRatio")
        return self


class FrameSway(_Row):
    """The equivalent sway imperfection φ of a frame (rad)."""

    method: Literal["heightAndColumns", "fixedRatio"] = Field(
        description="heightAndColumns: φ = (1 / baseRatio) αh αm, αh = 2/√h within "
        "[heightFactorMin, 1], αm = √(0.5 (1 + 1/m)); fixedRatio: φ = 1 / baseRatio."
    )
    baseRatio: Positive = Field(description="1 / φ0 (or 1 / φ of fixedRatio).")
    heightFactorMin: Share = Field(default=2 / 3, description="Least αh.")


class EigenmodeImperfection(_Row):
    """The first buckling mode as the imperfection, scaled to the pack's amplitude."""

    method: Literal["memberBow", "fixedRatio"] = Field(
        description="memberBow: the member moving most in the mode gets the bow amplitude e0; "
        "fixedRatio: that member's length over fixedRatio."
    )
    fixedRatio: Positive | None = Field(default=None, description="L / amplitude of fixedRatio.")

    @model_validator(mode="after")
    def _complete(self) -> EigenmodeImperfection:
        if self.method == "fixedRatio" and self.fixedRatio is None:
            raise ValueError("eigenmode fixedRatio: needs fixedRatio")
        return self


class PlateImperfection(_Row):
    """The geometric imperfection amplitude of plated parts and shells."""

    method: Literal["panelRatio", "dimple"] = Field(
        description="panelRatio: the panel's shorter side / panelRatio; dimple: U0 √(r t) with "
        "U0 of the fabrication class (dimple)."
    )
    panelRatio: Positive | None = Field(default=None, description="b / amplitude of panelRatio.")
    dimple: dict[str, Positive] = Field(
        default_factory=dict, description="Fabrication quality class -> U0,max."
    )
    defaultClass: str | None = Field(default=None, description="The class taken when none is set.")

    @model_validator(mode="after")
    def _complete(self) -> PlateImperfection:
        if self.method == "panelRatio" and self.panelRatio is None:
            raise ValueError("plates panelRatio: needs panelRatio")
        if self.method == "dimple" and self.defaultClass not in self.dimple:
            raise ValueError("plates dimple: needs dimple values and a defaultClass among them")
        return self


class StabilityPath(_Row):
    """The load-displacement path's solver and stopping rules (SAEngine practice by default)."""

    method: Literal["arcLength", "displacementControl"] = Field(
        default="arcLength", description="The path-following method by default."
    )
    steps: int = Field(default=100, ge=5, le=5000, description="Steps of the path at most.")
    maxDisplacementRatio: Positive = Field(
        default=10.0,
        description="Stop once the control displacement exceeds the height (or span) / this.",
    )
    dropShare: Share = Field(
        default=0.2, description="Stop once the load factor falls this share below its peak."
    )


class CableResistance(_Row):
    """The design tension resistance of a cable: breakingShare × the breaking force."""

    breakingShare: Share = Field(description="FRd / Fuk (or φ of the breaking strength).")
    minimumPretensionShare: Share | None = Field(
        default=None, description="Pretension at least this share of the breaking force."
    )


class NonlinearStabilityTable(TableModel):
    """Nonlinear buckling (GMNIA) and large-displacement cable analysis: imperfections,
    material of the model, the path's solver and the cables' resistance."""

    bow: BowImperfection
    sway: FrameSway
    eigenmode: EigenmodeImperfection
    plates: PlateImperfection
    yieldFactor: Positive = Field(
        default=1.0, description="The model's yield strength = this × fy (1/γM1, or 0.9 ...)."
    )
    stiffnessFactor: Positive = Field(
        default=1.0, description="The model's modulus = this × E."
    )
    hardeningRatio: float = Field(
        default=0.0001, ge=0, lt=1, description="Strain hardening modulus / E of the steel."
    )
    requiredFactor: Positive = Field(
        default=1.0,
        description="The limit load factor of the combination needs at least this.",
    )
    path: StabilityPath = Field(default_factory=StabilityPath)
    cables: CableResistance
    clauses: dict[str, str] = Field(default_factory=dict)
    note: str = ""


# ─────────────────────────────── connectionFe ───────────────────────────────


class JointClassification(_Row):
    """Stiffness classification by Sj,ini Lb / (E Ib) (method ``stiffnessRatio``)."""

    method: Literal["stiffnessRatio"] = "stiffnessRatio"
    pinned: Positive = Field(description="Pinned at most this × E Ib / Lb.")
    rigidBraced: Positive = Field(description="Rigid at least this × E Ib / Lb, braced frame.")
    rigidUnbraced: Positive = Field(
        description="Rigid at least this × E Ib / Lb, unbraced (sway) frame."
    )


class ConnectionFeTable(TableModel):
    """The component-based finite element check of steel joints (CBFEM)."""

    plasticStrainLimit: Share = Field(description="Plates' plastic strain at most this.")
    yieldFactor: Positive = Field(
        default=1.0, description="The plates' design yield = this × fy (1/γM0, or φ)."
    )
    hardeningRatio: float = Field(
        default=0.001, ge=0, lt=1, description="Tangent modulus after yield / E."
    )
    boltStiffness: Literal["componentTable", "elasticShank"] = Field(
        description="componentTable: k10 = 1.6 As/Lb in tension, k11 = 16 d² fub/(E dM16) in "
        "shear (the EN 1993-1-8 Table 6.11 form); elasticShank: E As/Lb in tension, the "
        "shank's E Ab/d in shear."
    )
    classification: JointClassification
    elementSize: Positive = Field(default=10.0, description="Mesh size of the plates at most [mm].")
    elementsAcross: int = Field(
        default=8, ge=2, le=40, description="Elements across a plate's shorter side at least."
    )
    loadSteps: int = Field(default=10, ge=1, le=200, description="Load steps to the design forces.")
    clauses: dict[str, str] = Field(default_factory=dict)
    note: str = ""
