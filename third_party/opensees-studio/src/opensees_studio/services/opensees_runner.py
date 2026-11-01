"""OpenSees command translator and analysis executor.

The runner is a thin, deterministic translator from a validated
:class:`Project` to OpenSeesPy commands. It owns no domain state; it
operates on the project passed to its constructor.

Three usage patterns:

    runner = OpenSeesRunner(project)
    runner.build()                                  # construct model only
    results = runner.run(case)                      # build + analyze
    results = runner.run(case, results_dir=path)    # transient: HDF5 here

Testability is paramount. The ``ops`` module is injected (default:
``openseespy.opensees``). Unit tests pass a ``Mock()`` and assert the
exact command sequence — no OpenSees install needed for translation
correctness.

Command order (enforced; reordering is a runtime error in OpenSees):

    wipe → model → node × N → fix × N
    → uniaxialMaterial / nDMaterial × M
    → frictionModel × F
    → section × S
    → geomTransf × G  (auto-allocated for frame elements)
    → element × E
    → timeSeries × T
    → pattern × P  (with nested load × L per pattern)
    → recorder × R  (transient only)
    → system / numberer / constraints / integrator / algorithm / test / analysis
    → analyze
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from opensees_studio.core import (
    BEARING_CLASSES,
    SLIDING_BEARING_CLASSES,
    BeamWithHingesElement,
    Concrete01,
    Concrete02,
    Concrete04,
    ConstantTimeSeries,
    CorotTrussElement,
    CoulombFriction,
    DispBeamColumn,
    ElasticBeamColumn,
    ElasticIsotropic,
    ElasticMembranePlateSection,
    ElasticPP,
    ElasticSection,
    ElasticUniaxial,
    FiberSection,
    ForceBeamColumn,
    Hardening,
    HystereticMaterial,
    HystereticSM,
    ImposedSupportMotionPattern,
    LinearTimeSeries,
    ModalCase,
    MultiLinear,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    PushoverCase,
    QuadElement,
    ResponseSpectrumCase,
    RigidDiaphragmConstraint,
    RigidLinkConstraint,
    SectionAggregator,
    ShellElement,
    SolidElement,
    StagedCase,
    StaticCase,
    Steel01,
    Steel02,
    TransientCase,
    TrigTimeSeries,
    TrussElement,
    TwoNodeLinkElement,
    UniformExcitationPattern,
    VelDependentFriction,
    VelNormalFrcDepFriction,
    ZeroLengthElement,
    ZeroLengthSectionElement,
)
from opensees_studio.core.constraints import constrained_nodes
from opensees_studio.core.modal import (
    CONDENSED_MAX_COORDINATES,
    SOLVER_ARPACK,
    SOLVER_CONDENSED,
    SOLVER_DENSE,
    arpack_basis,
    dof_indices,
    free_dof_count,
    mass_dof_bound,
    normalize_mode_sign,
    orthogonalize_degenerate_modes,
    resolve_modal_solver,
)
from opensees_studio.core.modal_combination import DEFAULT_MODAL_DAMPING, closely_spaced_pairs
from opensees_studio.services.opensees_io import (
    check_recorder_output,
    load_recorder_table,
    place_files,
    staging_dir,
)
from opensees_studio.services.result_store import release_results_dir, temporary_results_dir
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)

# Derived-series tag block: the runner materialises the velocity companion of an
# ImposedSupportMotion displacement record as its own Path series. The tag lives
# far above any hand-authored model id and is collision-checked at emission.
_IMPOSED_VEL_TS_OFFSET = 900_000

SKIP_BEARING_ORIENT_ENV = "OPENSEES_STUDIO_TEST_SKIP_BEARING_ORIENT"
"""Tests only: ``1`` leaves ``-orient`` off bearings, so OpenSees itself hard-exits on a
zero-length bearing (a real solver crash for the crash-reporting tests)."""


# ─────────────────────── DOF-index helper ───────────────────────
def _dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
    """Map (ndm, ndf) onto positions in the canonical 6-DOF storage (see ``core.modal``)."""
    return dof_indices(ndm, ndf)


# ─────────────────────── runner ───────────────────────
#: Smaller increments a failed pushover step is retried in.
SUBSTEPS = 10


class OpenSeesRunner:
    """Translator + executor. Instantiate with a project, then ``run(case)``."""

    def __init__(
        self,
        project: Project,
        ops_module: Any | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """
        Args:
            project: The model to translate.
            ops_module: ``openseespy.opensees`` by default; override with a
                mock in tests to verify the emitted command sequence
                without invoking the real solver.
            on_progress: Called as ``(completed_steps, total_steps)`` after
                every converged step of a stepped analysis (static,
                pushover, transient). The analysis CLI turns these into
                progress lines.
        """
        if ops_module is None:
            import openseespy.opensees as ops_module  # local import for testability
        self._ops = ops_module
        self._on_progress = on_progress
        self._linear_model: bool | None = None
        self.project = project
        self._dof_idx: tuple[int, ...] = _dof_indices(project.ndm, project.ndf)
        self._solid_twin: dict[int, int] = {}
        self._solid_only: set[int] = set()
        self._geom_transf_tags: dict[str, int] = {}
        self._element_geom_transf_tag: dict[int, int] = {}
        self._emitted_time_series: set[int] = set()
        #: Whether a pattern of the case imposes support displacements (``sp`` with a value,
        #: which the Plain handler cannot enforce).
        self._imposed_displacements = False
        #: Modal results already computed on this model, by modal case id: a response spectrum
        #: case whose modal case is here combines them instead of solving the eigenproblem
        #: again (the analysis CLI fills it as it runs or keeps modal cases).
        self.known_modal_results: dict[int, ModalResults] = {}

    # ─────────────────────── public API ───────────────────────
    def _progress(self, completed: int, total: int) -> None:
        if self._on_progress is not None:
            self._on_progress(completed, total)

    def build(self) -> None:
        """Emit all model-construction commands. Idempotent (wipes first)."""
        self.project.validate_references()

        ops = self._ops
        ops.wipe()
        self._emitted_time_series.clear()
        self._imposed_displacements = False
        ops.model("basic", "-ndm", self.project.ndm, "-ndf", self.project.ndf)

        for node in self.project.nodes:
            self._emit_node(node)
        self._plan_solid_twins()
        for node in self.project.nodes:
            if node.is_restrained or node.id in self._solid_only:
                self._emit_fix(node)
        self._emit_solid_twins()
        for mp in self.project.mp_constraints:
            self._emit_mp_constraint(mp)

        # Mass: emit only if any non-zero
        for node in self.project.nodes:
            if any(node.mass):
                self._emit_mass(node)

        for material in self.project.materials:
            self._emit_material(material)
        for friction in self.project.friction_models:
            self._emit_friction_model(friction)

        # Pre-compute: FiberSection id → torsion material id, sourced from any
        # SectionAggregator that wraps the fiber section with a T pairing.
        # Used by _emit_section to satisfy OpenSees FiberSection3d's torsion
        # requirement when GJ is not set directly on the FiberSection.
        self._fiber_torsion_mat: dict[int, int] = {}
        for sec in self.project.sections:
            if isinstance(sec, SectionAggregator) and sec.section_id is not None:
                for pair in sec.pairings:
                    if pair.dof == "T":
                        self._fiber_torsion_mat[sec.section_id] = pair.material_id

        for section in self.project.sections:
            self._emit_section(section)

        # Geometric transformations needed by frame elements
        self._allocate_and_emit_geom_transfs()

        for element in self.project.elements:
            self._emit_element(element)

    def run(self, case: Any, results_dir: Path | None = None) -> Any:
        """Build the model and run the requested analysis case.

        Returns:
            :class:`StaticResults` / :class:`ModalResults` / :class:`TransientResults`
            depending on case type.
        """
        self.project.validate_case_references(case)
        self._check_ground_motion_records(case)
        overrides = getattr(case, "section_overrides", None)
        if overrides:
            # The case's own sections: the whole case (its preloads too) runs on that model.
            replaced = {section.id: section for section in overrides}
            sections = [replaced.get(s.id, s) for s in self.project.sections]
            runner = OpenSeesRunner(
                self.project.model_copy(update={"sections": sections}),
                self._ops,
                self._on_progress,
            )
            return runner.run(case.model_copy(update={"section_overrides": []}), results_dir)
        if isinstance(case, StagedCase):
            return self._run_staged(case)  # builds one model per stage
        if (
            isinstance(case, ResponseSpectrumCase)
            and case.modal_case_id in self.known_modal_results
        ):
            return self._run_response_spectrum(case)  # no eigen solve, so no model either
        if (
            isinstance(case, StaticCase)
            and case.release_diaphragms
            and any(isinstance(mp, RigidDiaphragmConstraint) for mp in self.project.mp_constraints)
        ):
            return self._run_released(case)
        self.build()
        self._check_dof_coverage()
        if isinstance(case, StaticCase):
            return self._run_static(case)
        if isinstance(case, ModalCase):
            return self._run_modal(case)
        if isinstance(case, PushoverCase):
            return self._run_pushover(case)
        if isinstance(case, ResponseSpectrumCase):
            return self._run_response_spectrum(case)
        if isinstance(case, TransientCase):
            if results_dir is not None:
                return self._run_transient(case, results_dir)
            # A folder the runner made itself lives as long as the results read from it.
            target = temporary_results_dir()
            try:
                results = self._run_transient(case, target)
            except BaseException:
                release_results_dir(target)
                raise
            release_results_dir(target, results)
            return results
        raise TypeError(f"Unsupported analysis case type: {type(case).__name__}")

    def _check_ground_motion_records(self, case: Any) -> None:
        """Fail fast when the case uses a flagged ground-motion record.

        Collects the case's own patterns plus those of any preload cases
        and delegates to ``Project.check_ground_motion_records``, which
        raises a message naming each unusable record and its path.
        """
        pattern_ids = list(getattr(case, "pattern_ids", []))
        for preload_id in getattr(case, "preload_case_ids", []):
            preload = next((c for c in self.project.analyses if c.id == preload_id), None)
            if preload is not None:
                pattern_ids.extend(getattr(preload, "pattern_ids", []))
        self.project.check_ground_motion_records(pattern_ids)

    # ─────────────────────── nodes / fixes / mass ───────────────────────
    def _emit_node(self, node: Any) -> None:
        coords = node.coords[: self.project.ndm]
        self._ops.node(node.id, *coords)

    def _emit_fix(self, node: Any) -> None:
        # A node only solids use has no rotational stiffness: hold its rotations. The
        # translations of a node with a solid twin are held at the twin (see _emit_solid_twins).
        held = node.id in self._solid_only
        twin = node.id in self._solid_twin
        flags = tuple(
            int((node.restraint[i] and not (twin and i < 3)) or (held and i >= 3))
            for i in self._dof_idx
        )
        if any(flags):
            self._ops.fix(node.id, *flags)

    def _reaction(self, node_id: int, dof: int) -> float:
        """A node's reaction, including its solid twin's (which carries the solids' forces)."""
        value = float(self._ops.nodeReaction(node_id, dof))
        twin = self._solid_twin.get(node_id)
        if twin is not None and dof <= 3:
            value += float(self._ops.nodeReaction(twin, dof))
        return value

    def _plan_solid_twins(self) -> None:
        """Solid elements take three-DOF nodes. In a model with more DOFs per node, every node
        a solid uses gets a twin (a new tag after the last node) that the solid connects to.
        The twin is the retained node of an equalDOF in translation, and takes over the node's
        translational supports: OpenSees computes a reaction from the elements at a node, and
        the solids are at the twin. Nodes no other element uses hold their rotations."""
        self._solid_twin: dict[int, int] = {}
        self._solid_only: set[int] = set()
        solids = [el for el in self.project.elements if isinstance(el, SolidElement)]
        if not solids or self.project.ndf == 3:
            return
        used = {n for el in solids for n in el.nodes}
        others = {
            n
            for el in self.project.elements
            if not isinstance(el, SolidElement)
            for n in getattr(el, "nodes", ())
        }
        next_tag = max((n.id for n in self.project.nodes), default=0) + 1
        for offset, node_id in enumerate(sorted(used)):
            self._solid_twin[node_id] = next_tag + offset
        self._solid_only = used - others

    def _emit_solid_twins(self) -> None:
        if not self._solid_twin:
            return
        ops = self._ops
        coords = {n.id: n.coords for n in self.project.nodes}
        restraints = {n.id: n.restraint for n in self.project.nodes}
        ops.model("basic", "-ndm", 3, "-ndf", 3)
        for node_id, twin in self._solid_twin.items():
            ops.node(twin, *coords[node_id][:3])
            held = [int(bool(r)) for r in restraints[node_id][:3]]
            if any(held):
                ops.fix(twin, *held)
        ops.model("basic", "-ndm", self.project.ndm, "-ndf", self.project.ndf)
        for node_id, twin in self._solid_twin.items():
            ops.equalDOF(twin, node_id, 1, 2, 3)

    def _emit_mass(self, node: Any) -> None:
        m = tuple(node.mass[i] for i in self._dof_idx)
        self._ops.mass(node.id, *m)

    @property
    def _any_ops(self) -> Any:
        """The ops module typed as Any, for the twoNodeLink and rigid link calls."""
        return self._ops

    def _emit_mp_constraint(self, mp: Any) -> None:
        if isinstance(mp, RigidLinkConstraint):
            self._any_ops.rigidLink("beam", mp.retained_node, mp.constrained_node)
            return
        if isinstance(mp, RigidDiaphragmConstraint):
            self._any_ops.rigidDiaphragm(mp.perp_dir, mp.retained_node, *mp.constrained_nodes)
            return
        self._ops.equalDOF(mp.retained_node, mp.constrained_node, *mp.dofs)

    def _constraints_handler(self, requested: str) -> str:
        """The constraint handler a case runs with: Transformation when the model
        has a rigid link or diaphragm (it enforces them exactly), else the case's own setting."""
        if self.project.needs_transformation or self._imposed_displacements:
            return "Transformation"
        return requested

    # ─────────────────────── materials ───────────────────────
    def _emit_material(self, mat: Any) -> None:
        ops = self._ops
        match mat:
            case ElasticUniaxial():
                args: list[Any] = [mat.E]
                if mat.eta or mat.Eneg is not None:
                    args.append(mat.eta)
                if mat.Eneg is not None:
                    args.append(mat.Eneg)
                ops.uniaxialMaterial("Elastic", mat.id, *args)
            case Steel01():
                args = [mat.Fy, mat.E0, mat.b]
                if mat.a1 is not None:
                    args.extend([mat.a1, mat.a2, mat.a3, mat.a4])
                ops.uniaxialMaterial("Steel01", mat.id, *args)
            case Steel02():
                ops.uniaxialMaterial(
                    "Steel02",
                    mat.id,
                    mat.Fy,
                    mat.E0,
                    mat.b,
                    mat.R0,
                    mat.cR1,
                    mat.cR2,
                    *mat.isotropic_args(),
                )
            case Concrete01():
                ops.uniaxialMaterial("Concrete01", mat.id, mat.fpc, mat.epsc0, mat.fpcu, mat.epsU)
            case Concrete02():
                ops.uniaxialMaterial(
                    "Concrete02",
                    mat.id,
                    mat.fpc,
                    mat.epsc0,
                    mat.fpcu,
                    mat.epsU,
                    mat.lambda_,
                    mat.ft,
                    mat.Ets,
                )
            case Concrete04():
                args = [mat.fpc, mat.epsc0, mat.epscu, mat.Ec]
                if mat.fct is not None:
                    args.extend([mat.fct, mat.et])
                    if mat.beta is not None:
                        args.append(mat.beta)
                ops.uniaxialMaterial("Concrete04", mat.id, *args)
            case ElasticPP():
                args = [mat.E, mat.epsy_pos]
                if mat.epsy_neg is not None or mat.eps0 != 0.0:
                    args.append(mat.epsy_neg if mat.epsy_neg is not None else -mat.epsy_pos)
                    args.append(mat.eps0)
                ops.uniaxialMaterial("ElasticPP", mat.id, *args)
            case Hardening():
                hardening_args: list[Any] = [mat.E, mat.sigmaY, mat.H_iso, mat.H_kin]
                if mat.eta:
                    hardening_args.append(mat.eta)
                ops.uniaxialMaterial("Hardening", mat.id, *hardening_args)
            case HystereticMaterial():
                ops.uniaxialMaterial(
                    "Hysteretic",
                    mat.id,
                    mat.s1p,
                    mat.e1p,
                    mat.s2p,
                    mat.e2p,
                    mat.s3p,
                    mat.e3p,
                    mat.s1n,
                    mat.e1n,
                    mat.s2n,
                    mat.e2n,
                    mat.s3n,
                    mat.e3n,
                    mat.px,
                    mat.py,
                    mat.d1,
                    mat.d2,
                    mat.beta,
                )
            case HystereticSM():
                # uniaxialMaterial HystereticSM $tag -posEnv f1 d1 f2 d2 ...
                #                                     <-negEnv f1 d1 ...>
                # Envelopes carry (force, deformation) pairs in command order.
                hsm_args: list[Any] = ["-posEnv"]
                for force, defo in mat.pos_env:
                    hsm_args.extend([force, defo])
                if mat.neg_env:
                    hsm_args.append("-negEnv")
                    for force, defo in mat.neg_env:
                        hsm_args.extend([force, defo])
                ops.uniaxialMaterial("HystereticSM", mat.id, *hsm_args)
            case MultiLinear():
                # uniaxialMaterial MultiLinear $tag u1 f1 u2 f2 ... (strain first)
                ml_args: list[Any] = []
                for strain, stress in mat.points:
                    ml_args.extend([strain, stress])
                ops.uniaxialMaterial("MultiLinear", mat.id, *ml_args)
            case ElasticIsotropic():
                ops.nDMaterial("ElasticIsotropic", mat.id, mat.E, mat.nu, mat.rho)
            case _:
                raise NotImplementedError(f"Material type not yet handled: {type(mat).__name__}")

    # ─────────────────────── sections ───────────────────────
    def _emit_friction_model(self, fm: Any) -> None:
        """``frictionModel`` in the live OpenSeesPy 3.8.0 argument order."""
        ops = self._ops
        match fm:
            case CoulombFriction():
                ops.frictionModel("Coulomb", fm.id, fm.mu)
            case VelDependentFriction():
                ops.frictionModel("VelDependent", fm.id, fm.mu_slow, fm.mu_fast, fm.trans_rate)
            case VelNormalFrcDepFriction():
                ops.frictionModel(
                    "VelNormalFrcDep",
                    fm.id,
                    fm.a_slow,
                    fm.n_slow,
                    fm.a_fast,
                    fm.n_fast,
                    fm.alpha0,
                    fm.alpha1,
                    fm.alpha2,
                    fm.max_mu_fact,
                )
            case _:
                raise NotImplementedError(f"Friction model type not supported: {fm.type}")

    def _emit_section(self, sec: Any) -> None:
        ops = self._ops
        match sec:
            case ElasticSection():
                if self.project.ndm == 2:
                    ops.section("Elastic", sec.id, sec.E, sec.A, sec.Iz)
                else:
                    if sec.Iy is None or sec.G is None or sec.J is None:
                        raise ValueError(f"ElasticSection {sec.id} needs Iy, G, J for 3D models.")
                    ops.section("Elastic", sec.id, sec.E, sec.A, sec.Iz, sec.Iy, sec.G, sec.J)
            case FiberSection():
                if sec.GJ is not None:
                    ops.section("Fiber", sec.id, "-GJ", sec.GJ)
                elif self.project.ndm == 3:
                    torsion_mat = self._fiber_torsion_mat.get(sec.id)
                    if torsion_mat is not None:
                        # FiberSection3d requires torsion. The SectionAggregator
                        # wrapping this section will override T — use the same
                        # material so the intent is transparent.
                        ops.section("Fiber", sec.id, "-torsion", torsion_mat)
                    else:
                        raise ValueError(
                            f"FiberSection {sec.id!r} is used in a 3D model but has no "
                            "torsion defined. Either set GJ on the section or wrap it in "
                            "a SectionAggregator with a T DOF pairing."
                        )
                else:
                    ops.section("Fiber", sec.id)
                # Emit patches: rectangular / circular.
                for patch in sec.patches:
                    if patch.kind == "rect":
                        ops.patch(
                            "rect",
                            patch.material_id,
                            patch.n_fib_y,
                            patch.n_fib_z,
                            patch.y_i,
                            patch.z_i,
                            patch.y_j,
                            patch.z_j,
                        )
                    elif patch.kind == "circ":
                        ops.patch(
                            "circ",
                            patch.material_id,
                            patch.n_fib_circ,
                            patch.n_fib_rad,
                            patch.y_center,
                            patch.z_center,
                            patch.r_inner,
                            patch.r_outer,
                            patch.start_angle,
                            patch.end_angle,
                        )
                # Emit layers: straight.
                for layer in sec.layers:
                    if layer.kind == "straight":
                        ops.layer(
                            "straight",
                            layer.material_id,
                            layer.n_bars,
                            layer.bar_area,
                            layer.y_start,
                            layer.z_start,
                            layer.y_end,
                            layer.z_end,
                        )
                # Emit individual fibres (legacy / custom).
                for fb in sec.fibres:
                    ops.fiber(fb.y, fb.z, fb.area, fb.material_id)
            case ElasticMembranePlateSection():
                plate = [sec.Ep_mod] if sec.Ep_mod != 1.0 else []
                ops.section(
                    "ElasticMembranePlateSection", sec.id, sec.E, sec.nu, sec.h, sec.rho, *plate
                )
            case SectionAggregator():
                # section Aggregator $secTag $matTag1 $dof1 ... <-section $baseSec>
                args: list[Any] = [sec.id]
                for p in sec.pairings:
                    args.extend([p.material_id, p.dof])
                if sec.section_id is not None:
                    args.extend(["-section", sec.section_id])
                ops.section("Aggregator", *args)
            case _:
                raise NotImplementedError(f"Section type not yet handled: {type(sec).__name__}")

    # ─────────────────────── geomTransf ───────────────────────
    def _allocate_and_emit_geom_transfs(self) -> None:
        """One transformation tag per (transf_type, vecxz) combination used.

        For 3D frame elements, ``vecxz`` must be a vector in the local
        x-z plane that is NOT parallel to the local x-axis (the element
        axis). We compute the element axis from the node coordinates,
        then pick a ``vecxz`` orthogonal to it:

        - element axis nearly parallel to global Z (vertical column) →
          vecxz = (1, 0, 0)
        - everything else (horizontal beam, sloped brace) → vecxz = (0, 0, 1)

        Each frame element gets a tag in ``_element_geom_transf_tag`` so
        :meth:`_emit_element` can look up the right one.
        """
        import numpy as np

        frame_types = (
            ElasticBeamColumn,
            ForceBeamColumn,
            DispBeamColumn,
            BeamWithHingesElement,
        )
        node_coords = {n.id: np.array(n.coords, dtype=float) for n in self.project.nodes}

        # Allocate (transf_type, vecxz_tuple[, joint offsets]) → tag, lazily.
        combo_to_tag: dict[tuple[Any, ...], int] = {}
        self._element_geom_transf_tag: dict[int, int] = {}
        next_tag = 1

        for el in self.project.elements:
            if not isinstance(el, frame_types):
                continue
            if self.project.ndm == 2:
                key = (el.geom_transf, (0.0, 0.0, 0.0))  # vecxz unused in 2D
                if key not in combo_to_tag:
                    combo_to_tag[key] = next_tag
                    self._ops.geomTransf(el.geom_transf, next_tag)
                    next_tag += 1
                self._element_geom_transf_tag[el.id] = combo_to_tag[key]
                continue

            # 3D: pick vecxz orthogonal to the element axis (unless the element gives its own).
            p0 = node_coords[el.nodes[0]]
            p1 = node_coords[el.nodes[1]]
            axis = p1 - p0
            length = float(np.linalg.norm(axis))
            own = getattr(el, "vecxz", None)
            if own is not None:
                vecxz = tuple(float(v) for v in own)
            elif length < 1e-12:
                # Degenerate element; fall back to horizontal default.
                vecxz = (0.0, 0.0, 1.0)
            else:
                axis_unit = axis / length
                # If the axis is closer to global Z than to global X,
                # use vecxz = (1, 0, 0). Otherwise (0, 0, 1).
                if abs(axis_unit[2]) > abs(axis_unit[0]):
                    vecxz = (1.0, 0.0, 0.0)
                else:
                    vecxz = (0.0, 0.0, 1.0)

            # Rigid end offsets: one transformation per element that has them.
            offsets = getattr(el, "joint_offsets", None)
            key = (el.geom_transf, vecxz) if offsets is None else (el.geom_transf, vecxz, el.id)
            if key not in combo_to_tag:
                combo_to_tag[key] = next_tag
                extra: list[Any] = (
                    [] if offsets is None else ["-jntOffset", *(float(v) for v in offsets)]
                )
                self._ops.geomTransf(el.geom_transf, next_tag, *vecxz, *extra)
                next_tag += 1
            self._element_geom_transf_tag[el.id] = combo_to_tag[key]

        # Backward-compat for tests that read _geom_transf_tags.
        self._geom_transf_tags = {k[0]: v for k, v in combo_to_tag.items()}

    # ─────────────────────── elements ───────────────────────
    def _bearing_orient(self, el: Any) -> tuple[float, ...]:
        """``(x1, x2, x3, y1, y2, y3)`` for an elastomeric or sliding bearing.

        The user's ``orient`` wins. Otherwise x is the element axis (node i
        to node j) or, for coincident nodes, the vertical (global Y in 2D,
        global Z in 3D); y is the shear direction, global X unless the axis
        is horizontal, then the horizontal perpendicular to the axis.
        OpenSees 3.8 terminates the process when a zero-length bearing has
        no -orient, so the six values are always written.
        """
        if el.orient is not None:
            return tuple(float(v) for v in el.orient)
        ndm = self.project.ndm
        pi = np.asarray(self.project.node(el.nodes[0]).coords[:3], dtype=float)
        pj = np.asarray(self.project.node(el.nodes[1]).coords[:3], dtype=float)
        if ndm == 2:
            pi[2] = pj[2] = 0.0
        axis = pj - pi
        length = float(np.linalg.norm(axis))
        up = np.array([0.0, 1.0, 0.0]) if ndm == 2 else np.array([0.0, 0.0, 1.0])
        x = axis / length if length > 1e-12 else up
        y = np.cross(up, x) if ndm == 3 else np.array([x[1], -x[0], 0.0])
        if float(np.linalg.norm(y)) < 1e-9:
            y = np.array([1.0, 0.0, 0.0])
        y = y / float(np.linalg.norm(y))
        return (*(float(v) for v in x), *(float(v) for v in y))

    def _bearing_args(self, el: Any) -> list[Any]:
        """Argument list of ``ops.element`` for a bearing element.

        Matches the live OpenSeesPy 3.8.0 signatures::

            elastomericBearingPlasticity tag i j kInit qd alpha1 alpha2 mu
                -P p -Mz mz            (2D)
                -P p -T t -My my -Mz mz  (3D)
                -orient x1 x2 x3 y1 y2 y3 <-shearDist s> <-doRayleigh> <-mass m>
            elastomericBearingBoucWen tag i j kInit qd alpha1 alpha2 mu eta beta gamma
                ... same trailing arguments
            flatSliderBearing tag i j frnTag kInit
                ... same materials and trailing arguments, then <-iter maxIter tol>
            singleFPBearing tag i j frnTag Reff kInit
                ... same materials and trailing arguments, then <-iter maxIter tol>
        """
        args: list[Any]
        if isinstance(el, SLIDING_BEARING_CLASSES):
            if el.type == "SingleFPBearing":
                args = ["singleFPBearing", el.id, *el.nodes, el.friction_model_id, el.r_eff]
            else:
                args = ["flatSliderBearing", el.id, *el.nodes, el.friction_model_id]
            args.append(el.k_init)
        else:
            name = (
                "elastomericBearingBoucWen"
                if el.type == "ElastomericBearingBoucWen"
                else "elastomericBearingPlasticity"
            )
            args = [name, el.id, *el.nodes, el.k_init, el.qd, el.alpha1, el.alpha2, el.mu]
            if el.type == "ElastomericBearingBoucWen":
                args += [el.eta, el.beta, el.gamma]
        if self.project.ndm == 3:
            if el.t_material_id is None or el.my_material_id is None:
                raise ValueError(
                    f"Bearing {el.id} needs T and My materials in a 3D model "
                    "(t_material_id, my_material_id)."
                )
            args += [
                "-P",
                el.p_material_id,
                "-T",
                el.t_material_id,
                "-My",
                el.my_material_id,
                "-Mz",
                el.mz_material_id,
            ]
        else:
            args += ["-P", el.p_material_id, "-Mz", el.mz_material_id]
        if os.environ.get(SKIP_BEARING_ORIENT_ENV, "").strip() != "1":
            args += ["-orient", *self._bearing_orient(el)]
        if el.shear_dist != 0.5:
            args += ["-shearDist", el.shear_dist]
        if el.do_rayleigh:
            args.append("-doRayleigh")
        if el.mass > 0.0:
            args += ["-mass", el.mass]
        if isinstance(el, SLIDING_BEARING_CLASSES) and (el.max_iter != 25 or el.tol != 1e-12):
            args += ["-iter", el.max_iter, el.tol]
        return args

    def _two_node_link_args(self, el: TwoNodeLinkElement) -> list[Any]:
        """Argument list of ``ops.element`` for a twoNodeLink::

            twoNodeLink tag i j -mat m1 m2 ... -dir d1 d2 ...
                <-orient x1 x2 x3 y1 y2 y3> <-shearDist sy <sz>> <-doRayleigh>

        -orient, -shearDist and -doRayleigh are written only when set, so OpenSees
        applies its own defaults otherwise (shear distance 0.5 0.5, no Rayleigh).
        -orient is always written with both vectors: x is ``orient_x`` or, when that
        is None, node i to node j (the OpenSees default). OpenSeesPy 3.8.0 refuses
        "-orient y1 y2 y3" followed by another flag ("invalid -orient values").
        A 2D model takes one shear distance ratio (local y).
        """
        args: list[Any] = [
            "twoNodeLink",
            el.id,
            *el.nodes,
            "-mat",
            *el.material_ids,
            "-dir",
            *el.dofs,
        ]
        if el.orient_y is not None:
            x = el.orient_x
            if x is None:
                pi = self.project.node(el.nodes[0]).coords
                pj = self.project.node(el.nodes[1]).coords
                x = (pj[0] - pi[0], pj[1] - pi[1], pj[2] - pi[2])
            args += ["-orient", *x, *el.orient_y]
        if el.shear_dist is not None:
            ratios = el.shear_dist if self.project.ndm == 3 else el.shear_dist[:1]
            args += ["-shearDist", *ratios]
        if el.do_rayleigh:
            args.append("-doRayleigh")
        return args

    @staticmethod
    def _force_response(el: Any) -> str:
        """The element force response the runner reads: ``basicForce`` for a
        twoNodeLink (one force per -dir direction, as zeroLength's ``localForce``;
        its own ``localForce`` reads zero in OpenSeesPy 3.8.0), else ``localForce``."""
        return "basicForce" if isinstance(el, TwoNodeLinkElement) else "localForce"

    def _emit_element(self, el: Any) -> None:
        ops = self._ops
        match el:
            case TrussElement():
                ops.element("truss", el.id, *el.nodes, el.area, el.material_id, "-rho", el.rho)
            case CorotTrussElement():
                ops.element("corotTruss", el.id, *el.nodes, el.area, el.material_id, "-rho", el.rho)
            case ElasticBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ebc_args: list[Any] = [el.section_id, tag, "-mass", el.rho]
                if el.consistent_mass:
                    ebc_args.append("-cMass")
                ops.element(
                    "elasticBeamColumn",
                    el.id,
                    *el.nodes,
                    *ebc_args,
                )
            case ForceBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.beamIntegration(el.integration, el.id, el.section_id, el.integration_points)
                ops.element(
                    "forceBeamColumn",
                    el.id,
                    *el.nodes,
                    tag,
                    el.id,
                    "-iter",
                    el.max_iter,
                    el.tolerance,
                )
            case DispBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.beamIntegration(el.integration, el.id, el.section_id, el.integration_points)
                ops.element("dispBeamColumn", el.id, *el.nodes, tag, el.id)
            case ZeroLengthElement():
                zl_args: list[Any] = [
                    "zeroLength",
                    el.id,
                    *el.nodes,
                    "-mat",
                    *el.material_ids,
                    "-dir",
                    *el.dofs,
                ]
                # ``-doRayleigh 1`` only when requested (default off, matching
                # OpenSees' zeroLength default) — so an isolator can opt its
                # stiffness into a Kinit-proportional Rayleigh damping matrix.
                if el.do_rayleigh:
                    zl_args += ["-doRayleigh", 1]
                ops.element(*zl_args)
            case TwoNodeLinkElement():
                self._any_ops.element(*self._two_node_link_args(el))
            case el if isinstance(el, BEARING_CLASSES):
                ops.element(*self._bearing_args(el))
            case ZeroLengthSectionElement():
                # element zeroLengthSection $eleTag $iNode $jNode $secTag
                ops.element(
                    "zeroLengthSection",
                    el.id,
                    *el.nodes,
                    el.section_id,
                )
            case QuadElement() if True:
                # element quad         eleTag n1 n2 n3 n4 thk type matTag <pressure rho b1 b2>
                # element bbarQuad     eleTag n1 n2 n3 n4 thk matTag
                # element enhancedQuad eleTag n1 n2 n3 n4 thk type matTag
                if el.variant == "quad":
                    ops.element(
                        "quad",
                        el.id,
                        *el.nodes,
                        el.thickness,
                        el.behaviour,
                        el.material_id,
                        el.pressure,
                        el.rho,
                        el.b1,
                        el.b2,
                    )
                elif el.variant == "bbarQuad":
                    ops.element(
                        "bbarQuad",
                        el.id,
                        *el.nodes,
                        el.thickness,
                        el.material_id,
                    )
                else:  # enhancedQuad
                    ops.element(
                        "enhancedQuad",
                        el.id,
                        *el.nodes,
                        el.thickness,
                        el.behaviour,
                        el.material_id,
                    )
            case ShellElement():
                # element ASDShellQ4 eleTag n1 n2 n3 n4 secTag (and the other formulations)
                ops.element(el.formulation, el.id, *el.nodes, el.section_id)
            case SolidElement():
                # element TenNodeTetrahedron eleTag n1 ... n10 matTag (and the others)
                nodes = [self._solid_twin.get(n, n) for n in el.nodes]
                ops.element(el.formulation, el.id, *nodes, el.material_id)
            case BeamWithHingesElement():
                tag = self._element_geom_transf_tag[el.id]
                # OpenSees 3D signature:
                #   element beamWithHinges id ni nj secI lpI secJ lpJ E A Iz Iy G J transfTag
                # 2D signature drops Iy, G, J:
                #   element beamWithHinges id ni nj secI lpI secJ lpJ E A Iz transfTag
                args = [
                    el.id,
                    *el.nodes,
                    el.section_i_id,
                    el.lp_i,
                    el.section_j_id,
                    el.lp_j,
                    el.E,
                    el.A,
                    el.Iz,
                ]
                if self.project.ndm == 3:
                    if el.Iy is None or el.G is None or el.J is None:
                        raise ValueError(
                            f"BeamWithHinges {el.id} needs Iy, G, J in 3D models.",
                        )
                    args.extend([el.Iy, el.G, el.J])
                args.append(tag)
                ops.element("beamWithHinges", *args)
            case _:
                raise NotImplementedError(f"Element type not yet handled: {type(el).__name__}")

    # ─────────────────────── time series + patterns ───────────────────────
    def _emit_time_series(self, ts: Any) -> None:
        ops = self._ops
        match ts:
            case LinearTimeSeries():
                ops.timeSeries("Linear", ts.id, "-factor", ts.factor)
            case ConstantTimeSeries():
                ops.timeSeries("Constant", ts.id, "-factor", ts.factor)
            case PathTimeSeries():
                tail: list[Any] = ["-useLast"] if ts.use_last else []
                if ts.dt is not None:
                    ops.timeSeries(
                        "Path",
                        ts.id,
                        "-dt",
                        ts.dt,
                        "-values",
                        *ts.values,
                        "-factor",
                        ts.factor,
                        *tail,
                    )
                elif ts.times is not None:
                    ops.timeSeries(
                        "Path",
                        ts.id,
                        "-time",
                        *ts.times,
                        "-values",
                        *ts.values,
                        "-factor",
                        ts.factor,
                        *tail,
                    )
                else:
                    raise ValueError(
                        f"PathTimeSeries {ts.id}: either ``dt`` or ``times`` is required."
                    )
            case TrigTimeSeries():
                ops.timeSeries(
                    "Trig",
                    ts.id,
                    ts.t_start,
                    ts.t_end,
                    ts.period,
                    "-factor",
                    ts.factor,
                    "-shift",
                    ts.shift,
                    "-zeroShift",
                    ts.zero_shift,
                )
            case _:
                raise NotImplementedError(f"TimeSeries type not yet handled: {type(ts).__name__}")

    def _emit_pattern(self, pat: Any) -> None:
        ops = self._ops
        match pat:
            case PlainLoadPattern():
                ops.pattern("Plain", pat.id, pat.time_series_id)
                for nl in pat.nodal_loads:
                    forces = tuple(nl.forces[i] for i in self._dof_idx)
                    ops.load(nl.node_id, *forces)
                for sd in pat.support_displacements:
                    # The fix in that DOF gives way to the imposed value (a settlement).
                    ops.remove("sp", sd.node_id, sd.dof)
                    ops.sp(sd.node_id, sd.dof, sd.value)
                    self._imposed_displacements = True
                for el in pat.element_loads:
                    # eleLoad -ele N -type -beamUniform wy wz wx
                    # 2D: only (wy, wx) are emitted (wz drops).
                    # 3D: (wy, wz, wx).
                    if self.project.ndm == 2:
                        ops.eleLoad("-ele", el.element_id, "-type", "-beamUniform", el.wy, el.wx)
                    else:
                        ops.eleLoad(
                            "-ele", el.element_id, "-type", "-beamUniform", el.wy, el.wz, el.wx
                        )
            case UniformExcitationPattern():
                args: list[Any] = [pat.direction, "-accel", pat.accel_series_id]
                if pat.vel_series_id is not None:
                    args.extend(["-vel", pat.vel_series_id])
                if pat.disp_series_id is not None:
                    args.extend(["-disp", pat.disp_series_id])
                if pat.factor != 1.0:
                    args.extend(["-fact", pat.factor])
                ops.pattern("UniformExcitation", pat.id, *args)
            case ImposedSupportMotionPattern():
                self._emit_imposed_support_motion(pat)
            case _:
                raise NotImplementedError(f"Pattern type not yet handled: {type(pat).__name__}")

    def _emit_imposed_support_motion(self, pat: ImposedSupportMotionPattern) -> None:
        """``pattern MultipleSupport`` + shared ``groundMotion`` + per-node ``imposedMotion``.

        The support nodes are modelled FIXED in the driven DOF, so static
        preloads and modal cases see an ordinary grounded support. The fix is
        swapped for the imposed motion here — at pattern-emission time, which
        for a transient case is AFTER the preload sequence — i.e. the ground is
        at rest until the transient starts (the disp record begins at 0).

        ``ImposedMotionSP`` enforces displacement AND velocity at the node.
        The velocity is what carries the support motion into the
        stiffness-proportional (Rayleigh betaKinit) damping forces of
        ``-doRayleigh`` elements, and OpenSees's internal differentiation of a
        ``-disp``-only ground motion is unreliable — so the runner derives the
        velocity companion from the displacement record by central differences
        and hands both series to the ground motion explicitly.
        """
        ops = self._ops
        if pat.direction > self.project.ndf:
            raise ValueError(
                f"ImposedSupportMotion {pat.id}: direction {pat.direction} "
                f"exceeds ndf={self.project.ndf}."
            )
        slot = self._dof_idx[pat.direction - 1]
        nodes_by_id = {n.id: n for n in self.project.nodes}
        for nid in pat.node_ids:
            if not nodes_by_id[nid].restraint[slot]:
                raise ValueError(
                    f"ImposedSupportMotion {pat.id}: node {nid} must be "
                    f"restrained in direction {pat.direction} — the imposed "
                    f"motion replaces that fix at transient start."
                )
        ts = next(t for t in self.project.time_series if t.id == pat.disp_series_id)
        if not isinstance(ts, PathTimeSeries) or ts.dt is None:
            raise ValueError(
                f"ImposedSupportMotion {pat.id}: disp_series_id must reference "
                f"a PathTimeSeries with uniform ``dt``."
            )
        vel_tag = _IMPOSED_VEL_TS_OFFSET + pat.id
        if any(t.id == vel_tag for t in self.project.time_series):
            raise ValueError(
                f"ImposedSupportMotion {pat.id}: derived velocity-series tag "
                f"{vel_tag} collides with an existing time series."
            )
        vel = np.gradient(np.asarray(ts.values, dtype=float), ts.dt)
        ops.timeSeries(
            "Path",
            vel_tag,
            "-dt",
            ts.dt,
            "-values",
            *vel.tolist(),
            "-factor",
            ts.factor,
        )
        for nid in pat.node_ids:
            ops.remove("sp", nid, pat.direction)
        ops.pattern("MultipleSupport", pat.id)
        ops.groundMotion(
            pat.id,
            "Plain",
            "-disp",
            pat.disp_series_id,
            "-vel",
            vel_tag,
            "-fact",
            pat.factor,
        )
        for nid in pat.node_ids:
            ops.imposedMotion(nid, pat.direction, pat.id)

    # ─────────────────────── analysis runners ───────────────────────
    def _emit_patterns_for_case(self, pattern_ids: list[int]) -> None:
        # Time series for the patterns we are about to emit.
        used_ts: set[int] = set()
        for pid in pattern_ids:
            pat = next(p for p in self.project.load_patterns if p.id == pid)
            for ts_id in (
                getattr(pat, "time_series_id", None),
                getattr(pat, "accel_series_id", None),
                getattr(pat, "vel_series_id", None),
                getattr(pat, "disp_series_id", None),
            ):
                if ts_id is not None:
                    used_ts.add(ts_id)
        for ts in self.project.time_series:
            if ts.id in used_ts and ts.id not in self._emitted_time_series:
                self._emit_time_series(ts)
                self._emitted_time_series.add(ts.id)
        for pid in pattern_ids:
            pat = next(p for p in self.project.load_patterns if p.id == pid)
            self._emit_pattern(pat)

    def _run_preload_sequence(self, preload_ids: list[int], parent_case_id: int) -> None:
        """Run a list of StaticCase preloads, then lock load + reset time.

        Shared by :meth:`_run_transient` and :meth:`_run_pushover`. After
        all preload cases finish, ``ops.loadConst -time 0.0`` freezes the
        applied load as a baseline (any Linear time series attached to
        subsequent patterns won't re-ramp it) and rewinds pseudo-time so
        the continuation case begins at t=0. ``wipeAnalysis`` clears the
        static analysis objects so the caller can install its own
        integrator / algorithm.
        """
        ops = self._ops
        if not preload_ids:
            return
        for preload_id in preload_ids:
            preload_case = next(
                (c for c in self.project.analyses if c.id == preload_id),
                None,
            )
            if preload_case is None:
                raise ValueError(
                    f"AnalysisCase {parent_case_id}: preload_case_ids "
                    f"references missing AnalysisCase id={preload_id}."
                )
            if not isinstance(preload_case, StaticCase):
                raise TypeError(
                    f"AnalysisCase {parent_case_id}: preload_case_ids only "
                    f"supports StaticCase entries; got "
                    f"{type(preload_case).__name__}."
                )
            self._emit_patterns_for_case(preload_case.pattern_ids)
            self._setup_analysis(preload_case)
            for step in range(preload_case.n_steps):
                if ops.analyze(1) != 0:
                    raise RuntimeError(
                        f"Preload StaticCase {preload_case.id} failed at "
                        f"step {step + 1}/{preload_case.n_steps}."
                    )
        ops.loadConst("-time", 0.0)
        ops.wipeAnalysis()

    def _setup_analysis(self, case: Any) -> None:
        ops = self._ops
        ops.system(case.system, *case.system_args)
        ops.numberer(case.numberer)
        ops.constraints(self._constraints_handler(case.constraints))
        ops.test(case.test, case.tolerance, case.max_iter)
        ops.algorithm(case.algorithm, *case.algorithm_args)
        if isinstance(case, StaticCase):
            ops.integrator(case.integrator, case.load_factor_increment)
        elif isinstance(case, TransientCase):
            ops.integrator(case.integrator, *case.integrator_params)
            # Apply Rayleigh damping (C = alphaM*M + betaK*K) in a SINGLE
            # ``rayleigh`` call (a second call silently replaces the first). The
            # four args are alphaM and the betaK multipliers on current-K /
            # initial-K / commit-K: ``rayleigh 0 0 betaKinit 0`` is the Kinit-
            # proportional (initial-stiffness) idiom an isolated structure uses.
            alpha = float(getattr(case, "rayleigh_alpha_m", 0.0))
            beta = float(getattr(case, "rayleigh_beta_k", 0.0))
            beta_init = float(getattr(case, "rayleigh_beta_k_init", 0.0))
            beta_comm = float(getattr(case, "rayleigh_beta_k_comm", 0.0))
            if alpha != 0.0 or beta != 0.0 or beta_init != 0.0 or beta_comm != 0.0:
                ops.rayleigh(alpha, beta, beta_init, beta_comm)
        ops.analysis("Static" if isinstance(case, StaticCase) else "Transient")

    def _check_dof_coverage(self) -> None:
        """Fail loudly if any free DOF has no element contributing to it.

        OpenSees's direct solver returns a singular-matrix *warning* but
        `analyze` still returns 0, so the runner would otherwise pass
        garbage displacements back to the user (typically the load vector
        shows up verbatim as the displacement). The most common trigger:
        a pure-truss model with ndf=3 (rotational DOFs free but no frame
        element to resist them). Instead of auto-constraining, we tell
        the user exactly what went wrong so they can set ndf correctly
        or add the missing frame element / constraint.
        """
        from opensees_studio.core import (
            BeamWithHingesElement,
            CorotTrussElement,
            DispBeamColumn,
            ElasticBeamColumn,
            ForceBeamColumn,
            TrussElement,
            ZeroLengthSectionElement,
        )

        truss_types = (TrussElement, CorotTrussElement)
        frame_types = (
            ElasticBeamColumn,
            DispBeamColumn,
            ForceBeamColumn,
            BeamWithHingesElement,
        )
        # zeroLengthSection wires a full Section (P, Mz, My, T, V…) into
        # every DOF of both nodes — treat it as a frame for the coverage
        # check so Moment-Curvature models with free Rz don't get
        # rejected as singular.
        section_types = (ZeroLengthSectionElement,)

        # Per-node bitmask of DOFs with stiffness contribution from any
        # connected element. We work in canonical 6-DOF slot terms so the
        # comparison with ``_dof_idx`` is straightforward.
        active: dict[int, set[int]] = {n.id: set() for n in self.project.nodes}
        for el in self.project.elements:
            if isinstance(el, truss_types):
                contributed = {0, 1, 2}  # translations only
            elif isinstance(el, (frame_types, section_types)):
                contributed = {0, 1, 2, 3, 4, 5}
            else:
                # Unknown type: assume it covers every DOF (safe default).
                contributed = {0, 1, 2, 3, 4, 5}
            for nid in el.nodes:
                if nid in active:
                    active[nid].update(contributed)

        for mp in self.project.mp_constraints:
            if isinstance(mp, RigidLinkConstraint) and mp.constrained_node in active:
                active[mp.constrained_node].update({0, 1, 2, 3, 4, 5})
            elif isinstance(mp, RigidDiaphragmConstraint):
                # The plane's translations and the rotation about its normal follow the
                # retained node, which gets their stiffness from the tied nodes.
                axis = mp.perp_dir - 1
                tied = {*(i for i in range(3) if i != axis), 3 + axis}
                for nid in (mp.retained_node, *mp.constrained_nodes):
                    if nid in active:
                        active[nid].update(tied)

        problems: list[str] = []
        for node in self.project.nodes:
            for slot in self._dof_idx:
                if node.restraint[slot]:
                    continue  # restrained, no contribution needed
                if slot not in active[node.id]:
                    label = {0: "Ux", 1: "Uy", 2: "Uz", 3: "Rx", 4: "Ry", 5: "Rz"}[slot]
                    problems.append(
                        f"Node {node.id}, DOF {label}: no element "
                        f"contributes stiffness and DOF is unrestrained."
                    )
        if problems:
            hint = (
                "\n\nHint: pure-truss models should use ndm=2/ndf=2 "
                "(or ndm=3/ndf=3). File → New 2D Truss creates an ndf=2 "
                "project. For mixed truss+frame models, add a frame "
                "element that engages the listed rotational DOFs, or "
                "restrain them manually."
            )
            raise RuntimeError(
                "Singular stiffness matrix — the solve cannot run.\n" + "\n".join(problems) + hint
            )

    def _read_state(self, links: list[Any], shells: list[Any]) -> tuple[dict[int, np.ndarray], ...]:
        """The current state: node displacements and reactions, element end forces, link
        deformations and shell section forces (one flat array per tag)."""
        ops = self._ops
        ndf = len(self._dof_idx)
        ops.reactions()
        disp: dict[int, np.ndarray] = {}
        reaction: dict[int, np.ndarray] = {}
        for node in self.project.nodes:
            # One call per node for all its DOFs (six per node on a tall building's thousands
            # of nodes, per case, was a fifth of the solver's time); a node with fewer DOFs
            # than the model reads them one by one, as before.
            values = ops.nodeDisp(node.id)
            if isinstance(values, list | tuple) and len(values) == ndf:
                disp[node.id] = np.array(values, dtype=float)
            else:
                disp[node.id] = np.array(
                    [ops.nodeDisp(node.id, dof) for dof in range(1, ndf + 1)], dtype=float
                )
            forces_at = ops.nodeReaction(node.id)
            if (
                isinstance(forces_at, list | tuple)
                and len(forces_at) == ndf
                and node.id not in self._solid_twin
            ):
                reaction[node.id] = np.array(forces_at, dtype=float)
            else:
                reaction[node.id] = np.array(
                    [self._reaction(node.id, dof) for dof in range(1, ndf + 1)], dtype=float
                )
        forces: dict[int, np.ndarray] = {}
        for el in self.project.elements:
            if isinstance(el, SolidElement):
                continue  # no section forces (stresses follow from the displacements)
            # Prefer "localForce" — gives [N, V_y, V_z, T, M_y, M_z] per
            # end in the element's local frame, which is what diagrams
            # need. Fall back to global eleForce if the element type
            # doesn't expose localForce (e.g. zeroLength, truss).
            try:
                values = ops.eleResponse(el.id, self._force_response(el))
            except Exception:
                values = []
            if not values:
                values = ops.eleForce(el.id)
            forces[el.id] = np.asarray(values, dtype=float)
        # twoNodeLink: basicDeformation next to basicForce, the same order and sign.
        deformations = {
            el.id: np.asarray(
                self._any_ops.eleResponse(el.id, "basicDeformation") or [], dtype=float
            )
            for el in links
        }
        # Shells: section forces per unit length at each integration point.
        stresses = {
            el.id: np.asarray(ops.eleResponse(el.id, "stresses") or [], dtype=float)
            for el in shells
        }
        return disp, reaction, forces, deformations, stresses

    def _run_static(self, case: StaticCase) -> StaticResults:
        ops = self._ops
        links = [el for el in self.project.elements if isinstance(el, TwoNodeLinkElement)]
        shells = [el for el in self.project.elements if isinstance(el, ShellElement)]
        baseline: tuple[dict[int, np.ndarray], ...] | None = None
        if case.preload_case_ids:
            # Second order from a preload: lock it, then report the increment from its state.
            self._run_preload_sequence(case.preload_case_ids, case.id)
            baseline = self._read_state(links, shells)
        self._emit_patterns_for_case(case.pattern_ids)
        self._setup_analysis(case)

        ndf = len(self._dof_idx)
        initial = int(case.n_steps > 1)
        rows = case.n_steps + initial
        load_factors = np.zeros(rows)
        node_disp = {n.id: np.zeros((rows, ndf)) for n in self.project.nodes}
        node_reaction = {n.id: np.zeros((rows, ndf)) for n in self.project.nodes}
        element_forces: dict[int, np.ndarray] = {}
        element_deformations: dict[int, np.ndarray] = {}
        shell_forces: dict[int, np.ndarray] = {}
        targets = (node_disp, node_reaction, element_forces, element_deformations, shell_forces)

        for step in range(rows):
            status = 0 if initial and step == 0 else ops.analyze(1)
            if status != 0:
                raise RuntimeError(
                    f"Static analysis failed at step {step + 1}/{case.n_steps} "
                    f"(ops.analyze returned {status})."
                )
            load_factors[step] = ops.getTime()
            state = self._read_state(links, shells)
            for k, (target, current) in enumerate(zip(targets, state, strict=True)):
                for tag, values in current.items():
                    if baseline is not None and tag in baseline[k]:
                        values = values - baseline[k][tag]
                    if tag not in target:
                        target[tag] = np.zeros((rows, values.size))
                    target[tag][step, :] = values
            if not initial or step > 0:
                self._progress(step + 1 - initial, case.n_steps)

        return StaticResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=case.n_steps,
            load_factors=load_factors,
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_forces=element_forces,
            element_deformations=element_deformations,
            shell_forces=shell_forces,
        )

    # ─────────────────────── linear static batch ───────────────────────
    def batch_key(self, case: Any) -> tuple[Any, ...] | None:
        """The solver settings a linear static case shares with the cases it may run with in one
        model (:meth:`start_static_batch`), or None when it runs alone: a preload, several steps,
        an algorithm other than Linear, released diaphragms, section overrides, a load factor at
        the step other than 1, or a model that is not linear."""
        if not isinstance(case, StaticCase):
            return None
        if (
            case.preload_case_ids
            or case.section_overrides
            or case.n_steps != 1
            or case.algorithm != "Linear"
            or case.algorithm_args
            or case.integrator != "LoadControl"
            or case.load_factor_increment != 1.0
        ):
            return None
        if case.release_diaphragms and any(
            isinstance(mp, RigidDiaphragmConstraint) for mp in self.project.mp_constraints
        ):
            return None
        series = {ts.id: ts for ts in self.project.time_series}
        patterns = {p.id: p for p in self.project.load_patterns}
        for pid in case.pattern_ids:
            pattern = patterns.get(pid)
            if not isinstance(pattern, PlainLoadPattern):
                return None
            ts = series.get(pattern.time_series_id)
            if not isinstance(ts, LinearTimeSeries | ConstantTimeSeries) or ts.factor != 1.0:
                return None
        if self._linear_model is None:
            self._linear_model = not self._nonlinear_parts({el.id for el in self.project.elements})
        if not self._linear_model:
            return None
        return (
            case.system,
            tuple(case.system_args),
            case.numberer,
            case.constraints,
            case.test,
            case.tolerance,
            case.max_iter,
        )

    def start_static_batch(self, cases: list[StaticCase]) -> None:
        """Build the model once for linear static cases of one :meth:`batch_key`, run one after
        the other by :meth:`next_static_batch_case`. Each case's patterns get their own copies
        on a series that is 1 at the case's step and 0 at every other, and the stiffness is
        factored once (``Linear -factorOnce``): on a 25-storey model a case took 7 s alone, as
        each built the model and factored the same stiffness again."""
        for case in cases:
            self.project.validate_case_references(case)
        self.build()
        self._check_dof_coverage()
        ops = self._ops
        patterns = {p.id: p for p in self.project.load_patterns}
        series = 1 + max([ts.id for ts in self.project.time_series] + [0])
        tag = 1 + max([p.id for p in self.project.load_patterns] + [0])
        for step, case in enumerate(cases, start=1):
            ops.timeSeries(
                "Path", series, "-time", step - 1, step, step + 1, "-values", 0.0, 1.0, 0.0
            )
            for pid in case.pattern_ids:
                copy = patterns[pid].model_copy(update={"id": tag, "time_series_id": series})
                self._emit_pattern(copy)
                tag += 1
            series += 1
        self._setup_analysis(cases[0])
        ops.algorithm("Linear", "-factorOnce")

    def next_static_batch_case(self, case: StaticCase) -> StaticResults:
        """The results of the next case of the batch (:meth:`start_static_batch`, same order)."""
        ops = self._ops
        status = ops.analyze(1)
        if status != 0:
            raise RuntimeError(
                f"Static analysis failed at step 1/1 (ops.analyze returned {status})."
            )
        links = [el for el in self.project.elements if isinstance(el, TwoNodeLinkElement)]
        shells = [el for el in self.project.elements if isinstance(el, ShellElement)]
        disp, reaction, forces, deformations, shell_forces = (
            {tag: values[None, :].copy() for tag, values in part.items()}
            for part in self._read_state(links, shells)
        )
        self._progress(1, 1)
        return StaticResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=1,
            load_factors=np.array([1.0]),
            node_disp=disp,
            node_reaction=reaction,
            element_forces=forces,
            element_deformations=deformations,
            shell_forces=shell_forces,
        )

    # ─────────────────────── released diaphragms ───────────────────────
    def _run_released(self, case: StaticCase) -> StaticResults:
        """A static case on the model without its rigid diaphragms (``release_diaphragms``).

        The nodes no element or remaining constraint uses (a diaphragm's own centre node) are
        left out of the solved model and report zero displacement and reaction."""
        project = self.project
        constraints = [
            mp for mp in project.mp_constraints if not isinstance(mp, RigidDiaphragmConstraint)
        ]
        used = {nid for e in project.elements for nid in e.nodes}
        for mp in constraints:
            used.update((mp.retained_node, mp.constrained_node))
        for pattern in project.load_patterns:
            if pattern.id not in case.pattern_ids or not isinstance(pattern, PlainLoadPattern):
                continue
            loose = sorted({load.node_id for load in pattern.nodal_loads} - used)
            if loose:
                raise ValueError(
                    f"Case {case.id} ({case.name}) releases the rigid diaphragms, but pattern "
                    f"{pattern.id} loads node(s) {', '.join(map(str, loose))} that only a "
                    "diaphragm connects."
                )
        sub = project.model_copy(
            update={
                "nodes": [n for n in project.nodes if n.id in used],
                "mp_constraints": constraints,
                "load_patterns": [p for p in project.load_patterns if p.id in case.pattern_ids],
                "analyses": [],
            }
        )
        runner = OpenSeesRunner(sub, self._ops, self._on_progress)
        runner.build()
        runner._check_dof_coverage()
        results = runner._run_static(case)
        rows = len(results.load_factors)
        ndf = len(self._dof_idx)
        for node in project.nodes:
            if node.id not in used:
                results.node_disp[node.id] = np.zeros((rows, ndf))
                results.node_reaction[node.id] = np.zeros((rows, ndf))
        return results

    # ─────────────────────── staged construction ───────────────────────
    _LINEAR_MATERIALS = ("Elastic", "ElasticIsotropic")
    _LINEAR_SECTIONS = ("ElasticSection", "ElasticMembranePlateSection")

    def _nonlinear_parts(self, element_ids: set[int]) -> list[str]:
        """What makes the elements ``element_ids`` nonlinear (superposition needs none)."""
        materials = {m.id: m for m in self.project.materials}
        sections = {s.id: s for s in self.project.sections}
        problems: list[str] = []
        for el in self.project.elements:
            if el.id not in element_ids:
                continue
            transf = getattr(el, "geom_transf", "Linear")
            if transf != "Linear":
                problems.append(f"element {el.id}: geometric transformation {transf}")
            if isinstance(el, CorotTrussElement) or getattr(el, "friction_model_id", None):
                problems.append(f"element {el.id}: {el.type}")
            mids = [getattr(el, "material_id", None), *(getattr(el, "material_ids", None) or [])]
            for mid in mids:
                material = materials.get(mid) if mid is not None else None
                if material is not None and material.type not in self._LINEAR_MATERIALS:
                    problems.append(f"element {el.id}: material {mid} ({material.type})")
            sid = getattr(el, "section_id", None)
            section = sections.get(sid) if sid is not None else None
            if section is not None and section.type not in self._LINEAR_SECTIONS:
                problems.append(f"element {el.id}: section {sid} ({section.type})")
        return problems

    def _stage_project(self, case: StagedCase, stage: Any, active: set[int]) -> Project:
        """The part of the model built by the end of ``stage`` with only its loads."""
        project = self.project
        elements = [e for e in project.elements if e.id in active]
        used = {nid for e in elements for nid in e.nodes}
        constraints: list[Any] = []
        for mp in project.mp_constraints:
            if isinstance(mp, RigidDiaphragmConstraint):
                kept = [n for n in mp.constrained_nodes if n in used]
                if kept:
                    constraints.append(mp.model_copy(update={"constrained_nodes": kept}))
                    used.add(mp.retained_node)
            elif mp.constrained_node in used:
                constraints.append(mp)
                used.add(mp.retained_node)
        patterns = {p.id: p for p in project.load_patterns}
        stage_patterns = []
        prefix = f"Case {case.id}, stage '{stage.name}'"
        for pid in stage.pattern_ids:
            pattern = patterns[pid]
            if not isinstance(pattern, PlainLoadPattern):
                raise ValueError(f"{prefix}: pattern {pid} is not a plain load pattern.")
            nodes = sorted({load.node_id for load in pattern.nodal_loads} - used)
            loaded = sorted({load.element_id for load in pattern.element_loads} - active)
            if nodes or loaded:
                what = [f"node(s) {', '.join(map(str, nodes))}"] if nodes else []
                what += [f"element(s) {', '.join(map(str, loaded))}"] if loaded else []
                raise ValueError(
                    f"{prefix}: pattern {pid} loads {' and '.join(what)} not built by then."
                )
            stage_patterns.append(pattern)
        return project.model_copy(
            update={
                "nodes": [n for n in project.nodes if n.id in used],
                "elements": elements,
                "mp_constraints": constraints,
                "load_patterns": stage_patterns,
                "analyses": [],
            }
        )

    def _run_staged(self, case: StagedCase) -> StaticResults:
        """Each stage: the structure built so far under the stage's loads alone (a fresh linear
        model), the results summed over the stages (see :class:`StagedCase`)."""
        if case.linear_geometry and any(
            getattr(e, "geom_transf", "Linear") != "Linear" for e in self.project.elements
        ):
            # A first-order construction sequence in a model whose other cases use P-Delta.
            elements = [
                e.model_copy(update={"geom_transf": "Linear"})
                if getattr(e, "geom_transf", "Linear") != "Linear"
                else e
                for e in self.project.elements
            ]
            runner = OpenSeesRunner(
                self.project.model_copy(update={"elements": elements}),
                self._ops,
                self._on_progress,
            )
            return runner._run_staged(case)
        built = {i for stage in case.stages for i in stage.element_ids}
        problems = self._nonlinear_parts(built)
        if problems:
            shown = "; ".join(problems[:5]) + ("; ..." if len(problems) > 5 else "")
            raise ValueError(
                f"Case {case.id} ({case.name}): a staged analysis sums linear stages and needs a "
                f"linear elastic model, but {shown}."
            )
        ndf = len(self._dof_idx)
        count = len(case.stages)
        node_disp = {n.id: np.zeros((count, ndf)) for n in self.project.nodes}
        node_reaction = {n.id: np.zeros((count, ndf)) for n in self.project.nodes}
        element_forces: dict[int, np.ndarray] = {}
        shell_forces: dict[int, np.ndarray] = {}
        running: dict[str, dict[int, np.ndarray]] = {
            "disp": {},
            "reaction": {},
            "forces": {},
            "shells": {},
        }
        active: set[int] = set()
        for k, stage in enumerate(case.stages):
            active.update(stage.element_ids)
            if stage.pattern_ids:
                sub = self._stage_project(case, stage, active)
                runner = OpenSeesRunner(sub, self._ops)
                runner.build()
                runner._check_dof_coverage()
                step = runner._run_static(
                    StaticCase(
                        id=case.id,
                        name=f"{case.name}: {stage.name}",
                        pattern_ids=stage.pattern_ids,
                        system=case.system,
                        system_args=case.system_args,
                        numberer=case.numberer,
                        constraints=case.constraints,
                    )
                )
                for key, group in (
                    ("disp", step.node_disp),
                    ("reaction", step.node_reaction),
                    ("forces", step.element_forces),
                    ("shells", step.shell_forces),
                ):
                    for tag, rows in group.items():
                        last = np.asarray(rows[-1], dtype=float)
                        total = running[key].get(tag)
                        running[key][tag] = last.copy() if total is None else total + last
            for tag, value in running["disp"].items():
                node_disp[tag][k, :] = value
            for tag, value in running["reaction"].items():
                node_reaction[tag][k, :] = value
            for target, key in ((element_forces, "forces"), (shell_forces, "shells")):
                for tag, value in running[key].items():
                    if tag not in target:
                        target[tag] = np.zeros((count, value.size))
                    target[tag][k, :] = value
            self._progress(k + 1, count)
        return StaticResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=count,
            load_factors=np.ones(count),  # every stage applies its patterns in full
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_forces=element_forces,
            shell_forces=shell_forces,
            stage_names=[stage.name for stage in case.stages],
        )

    def _run_pushover(self, case: PushoverCase) -> PushoverResults:
        """Monotonic displacement-controlled pushover.

        Steps the control DOF from 0 to ``target_disp`` in increments of
        ``step_size`` (sign-aware: negative target → negative increments).
        At each step we:
        - run ops.analyze(1)
        - record the control-DOF displacement (x-axis value)
        - sum reactions at base_nodes projected onto the control DOF
          direction; negated = applied base shear (y-axis value)
        - snapshot node displacements and element local forces
        """
        from opensees_studio.core import ConstantTimeSeries

        ops = self._ops

        # Base-node list defaults to every restrained node.
        base_nodes = (
            list(case.base_nodes)
            if case.base_nodes
            else [n.id for n in self.project.nodes if n.is_restrained]
        )
        if not base_nodes:
            raise RuntimeError(
                "Pushover needs at least one restrained (base) node for "
                "reaction summation. Add a support or specify base_nodes.",
            )

        ndf = len(self._dof_idx)
        # Number of analysis steps — sign-aware increment.
        sign = 1.0 if case.target_disp >= 0.0 else -1.0
        dU = sign * case.step_size
        n_steps = int(abs(case.target_disp) / case.step_size)
        if n_steps == 0:
            raise ValueError(
                f"Pushover step_size ({case.step_size}) larger than target "
                f"({case.target_disp}); would run zero steps.",
            )

        # ── Preload (gravity / axial) ──────────────────────────────
        # Preferred path: explicit ``preload_case_ids`` — each runs its
        # patterns through a full LoadControl ramp, matching the Tcl
        # "analyze 10; loadConst -time 0.0" recipe.
        # Legacy path (no preload_case_ids): fall back to splitting
        # ``pattern_ids`` by TimeSeries kind — Constant patterns become
        # a single zero-step LoadControl preload, Linear patterns
        # become the DisplacementControl reference.
        preload_ids = list(getattr(case, "preload_case_ids", []) or [])
        if preload_ids:
            self._run_preload_sequence(preload_ids, case.id)
            linear_ids = list(case.pattern_ids)
        else:
            const_ids: list[int] = []
            linear_ids = []
            ts_by_id = {ts.id: ts for ts in self.project.time_series}
            for pid in case.pattern_ids:
                pat = next(p for p in self.project.load_patterns if p.id == pid)
                ts_id = getattr(pat, "time_series_id", None)
                ts = ts_by_id.get(ts_id) if ts_id is not None else None
                if isinstance(ts, ConstantTimeSeries):
                    const_ids.append(pid)
                else:
                    linear_ids.append(pid)
            if const_ids:
                self._emit_patterns_for_case(const_ids)
                ops.system(case.system, *case.system_args)
                ops.numberer(case.numberer)
                ops.constraints(self._constraints_handler(case.constraints))
                ops.test(case.test, case.tolerance, case.max_iter)
                ops.algorithm(case.algorithm, *case.algorithm_args)
                ops.integrator("LoadControl", 0.0)
                ops.analysis("Static")
                status = ops.analyze(1)
                if status != 0:
                    raise RuntimeError(
                        "Pushover preload step (constant patterns) failed "
                        "to converge. Loosen test tolerance or check the "
                        "axial magnitude.",
                    )
                ops.loadConst("-time", 0.0)

        # Emit Linear reference patterns (after preload so they don't
        # accumulate into the locked baseline).
        if linear_ids:
            self._emit_patterns_for_case(linear_ids)

        # Configure analysis — DisplacementControl integrator.
        ops.system(case.system, *case.system_args)
        ops.numberer(case.numberer)
        ops.constraints(self._constraints_handler(case.constraints))
        ops.test(case.test, case.tolerance, case.max_iter)
        ops.algorithm(case.algorithm, *case.algorithm_args)
        ops.integrator(
            "DisplacementControl",
            case.control_node,
            case.control_dof,
            dU,
        )
        ops.analysis("Static")

        # Allocate output arrays, including step 0 (initial state).
        control_disp = np.zeros(n_steps + 1)
        base_shear = np.zeros(n_steps + 1)
        node_disp = {n.id: np.zeros((n_steps + 1, ndf)) for n in self.project.nodes}
        node_reaction = {n.id: np.zeros((n_steps + 1, ndf)) for n in self.project.nodes}
        element_end_fibers: dict[int, np.ndarray] = {}
        element_start_fibers: dict[int, np.ndarray] = {}
        element_forces: dict[int, np.ndarray] = {}

        def _snapshot(step: int) -> None:
            ops.reactions()
            # Sum reactions at base nodes in the control direction; negate
            # so positive base_shear means "applied load to the right".
            bs = 0.0
            for nid in base_nodes:
                bs += self._reaction(nid, case.control_dof)
            base_shear[step] = -bs
            control_disp[step] = float(
                ops.nodeDisp(case.control_node, case.control_dof),
            )
            for node in self.project.nodes:
                for j, dof in enumerate(range(1, ndf + 1)):
                    node_disp[node.id][step, j] = ops.nodeDisp(node.id, dof)
                    node_reaction[node.id][step, j] = self._reaction(node.id, dof)
            for el in self.project.elements:
                if isinstance(el, SolidElement):
                    continue
                if isinstance(el, ForceBeamColumn | DispBeamColumn):
                    # The final integration section provides beam-end fiber
                    # stress/strain without changing any analysis settings.
                    data = ops.eleResponse(el.id, "section", el.integration_points, "fiberData")
                    if data:
                        fibers = np.asarray(data, dtype=float).reshape(-1, 5)
                        if el.id not in element_end_fibers:
                            element_end_fibers[el.id] = np.zeros((n_steps + 1, *fibers.shape))
                        element_end_fibers[el.id][step] = fibers
                    # And the first section (node i): the member's other end.
                    data = ops.eleResponse(el.id, "section", 1, "fiberData")
                    if data:
                        fibers = np.asarray(data, dtype=float).reshape(-1, 5)
                        if el.id not in element_start_fibers:
                            element_start_fibers[el.id] = np.zeros((n_steps + 1, *fibers.shape))
                        element_start_fibers[el.id][step] = fibers
                try:
                    forces = ops.eleResponse(el.id, self._force_response(el))
                except Exception:
                    forces = []
                if not forces:
                    try:
                        forces = ops.eleForce(el.id)
                    except Exception:
                        continue
                if el.id not in element_forces:
                    element_forces[el.id] = np.zeros(
                        (n_steps + 1, len(forces)),
                        dtype=float,
                    )
                element_forces[el.id][step, :] = forces

        # Step 0: initial state (all zeros in the linear case, but we
        # still record so the curve starts at the origin cleanly).
        _snapshot(0)

        def _fallbacks() -> int:
            """One increment with the fallback algorithms of the OpenSees portal-frame
            tutorials: initial-tangent Newton, then Broyden, then Newton with line search."""
            ops.test(case.test, case.tolerance, 2000)
            ops.algorithm("Newton", "-initial")
            status = ops.analyze(1)
            if status != 0:
                ops.algorithm("Broyden", 8)
                status = ops.analyze(1)
            if status != 0:
                ops.algorithm("NewtonLineSearch", 0.8)
                status = ops.analyze(1)
            ops.test(case.test, case.tolerance, case.max_iter)
            ops.algorithm(case.algorithm, *case.algorithm_args)
            return status

        def _substeps() -> int:
            """The step in SUBSTEPS smaller increments (each with the fallbacks), for the
            steps where a member softens (concrete crushing) faster than one increment
            can follow; the integrator returns to the full increment afterwards."""
            ops.integrator(
                "DisplacementControl", case.control_node, case.control_dof, dU / SUBSTEPS
            )
            status = 0
            for _ in range(SUBSTEPS):
                status = ops.analyze(1)
                if status != 0:
                    status = _fallbacks()
                if status != 0:
                    break
            ops.integrator("DisplacementControl", case.control_node, case.control_dof, dU)
            return status

        for step in range(1, n_steps + 1):
            status = ops.analyze(1)
            if status != 0:
                status = _fallbacks()
            if status != 0:
                status = _substeps()
            if status != 0:
                # Still failed — trim output to where we got, then stop.
                control_disp = control_disp[:step]
                base_shear = base_shear[:step]
                for nid in node_disp:
                    node_disp[nid] = node_disp[nid][:step]
                    node_reaction[nid] = node_reaction[nid][:step]
                for eid in element_end_fibers:
                    element_end_fibers[eid] = element_end_fibers[eid][:step]
                for eid in element_start_fibers:
                    element_start_fibers[eid] = element_start_fibers[eid][:step]
                for eid in element_forces:
                    element_forces[eid] = element_forces[eid][:step]
                break
            _snapshot(step)
            self._progress(step, n_steps)

        return PushoverResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=len(control_disp) - 1,
            control_node=case.control_node,
            control_dof=case.control_dof,
            control_disp=control_disp,
            base_shear=base_shear,
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_end_fibers=element_end_fibers,
            element_start_fibers=element_start_fibers,
            element_forces=element_forces,
            n_steps_requested=n_steps,
        )

    def _run_response_spectrum(self, case: ResponseSpectrumCase) -> ResponseSpectrumResults:
        """Re-run the referenced modal case (or take its results from
        :attr:`known_modal_results`), then combine via SRSS/CQC.

        We delegate to the spectrum service for the math; the runner's
        only job is finding the linked ModalCase + ResponseSpectrum and
        wiring up :class:`ResponseSpectrumResults`.
        """
        from opensees_studio.services.spectrum import (
            combine_modal_response,
            mass_participation,
        )

        modal_case = next(
            (
                c
                for c in self.project.analyses
                if isinstance(c, ModalCase) and c.id == case.modal_case_id
            ),
            None,
        )
        if modal_case is None:
            raise ValueError(
                f"ResponseSpectrum case references modal_case_id="
                f"{case.modal_case_id}, but no such ModalCase exists.",
            )
        spectrum = next(
            (s for s in self.project.spectra if s.id == case.spectrum_id),
            None,
        )
        if spectrum is None:
            raise ValueError(
                f"ResponseSpectrum case references spectrum_id="
                f"{case.spectrum_id}, but no such ResponseSpectrum exists.",
            )

        modal_results = self.known_modal_results.get(modal_case.id) or self._run_modal(modal_case)

        warnings: list[str] = []
        damping: float | None = None
        if case.combination == "CQC":
            damping = (
                case.damping_ratio if case.damping_ratio is not None else spectrum.damping_ratio
            )
            if damping <= 0.0:
                warnings.append(
                    f"CQC needs a positive modal damping ratio; the case leaves it to the "
                    f"spectrum and spectrum '{spectrum.name}' has {spectrum.damping_ratio:g}. "
                    f"Using {DEFAULT_MODAL_DAMPING:g}."
                )
                damping = DEFAULT_MODAL_DAMPING

        modes = mass_participation(self.project, modal_results, case.direction)
        combined, modes = combine_modal_response(
            modes,
            spectrum,
            modal_results,
            case.direction,
            method=case.combination,
            damping=damping,
        )

        if case.combination == "SRSS":
            pairs = closely_spaced_pairs(
                [m.angular_frequency for m in modes], ratio=case.closely_spaced_ratio
            )
            if pairs:
                listed = ", ".join(
                    f"modes {modes[i].mode_number} and {modes[j].mode_number} (ratio {r:.3f})"
                    for i, j, r in pairs
                )
                warnings.append(
                    f"SRSS with closely spaced modes (frequency ratio at or above "
                    f"{case.closely_spaced_ratio:g}): {listed}. SRSS ignores their correlation "
                    f"and its result depends on the eigen basis inside such a pair; use CQC."
                )

        return ResponseSpectrumResults(
            case_id=case.id,
            case_name=case.name,
            direction=case.direction,
            combination=case.combination,
            combined_disp=combined,
            modes=modes,
            solver=modal_results.solver,
            damping_ratio=damping,
            warnings=warnings,
        )

    def _run_modal(self, case: ModalCase) -> ModalResults:
        """Eigenvalue analysis with history-independent results.

        The solver comes from :func:`core.modal.resolve_modal_solver`:
        dense ``fullGenLapack`` at or below the free DOF threshold (a direct
        method, bit-identical on every call), ARPACK above it (the CLI runs
        such a case as the first eigen call of a fresh process, because
        ARPACK keeps its start vector across calls). An explicit solver is
        honoured; ARPACK still falls back to dense when
        ``2 * n_modes >= n_free`` (it aborts with ``_saupd info = -9999``).
        Degenerate groups (repeated eigenvalues) are made mass-orthogonal
        and every mode shape is sign-normalized (largest absolute component
        positive, ties broken by the lowest DOF index).
        """
        ops = self._ops
        ndf = len(self._dof_idx)

        n_free = free_dof_count(self.project)
        solver, _reason = resolve_modal_solver(
            case.solver, n_free, case.n_modes, mass_dof_bound(self.project)
        )

        if case.preload_case_ids:
            # The tangent stiffness of the preloaded structure (geometric stiffness with
            # P-Delta transformations); the static analysis objects are wiped after it.
            self._run_preload_sequence(case.preload_case_ids, case.id)
        reduced = None
        if solver == SOLVER_CONDENSED:
            reduced = None if case.preload_case_ids else self._mass_coordinates()
            if reduced is None:
                # A preload or a mass layout the condensation leaves out: ARPACK when it can run
                # (auto condenses big models it could), else dense.
                solver = (
                    SOLVER_ARPACK
                    if 2 * case.n_modes < n_free
                    and arpack_basis(case.n_modes) < mass_dof_bound(self.project)
                    else SOLVER_DENSE
                )
        raw_shapes: dict[int, dict[int, np.ndarray]] = {}
        if reduced is not None:
            eigenvalues, raw_shapes = self._condensed_modes(case.n_modes, *reduced)
        else:
            if self.project.needs_transformation:
                self._any_ops.constraints("Transformation")
            eigenvalues = np.array(ops.eigen(f"-{solver}", case.n_modes), dtype=float)
            for mode in range(1, case.n_modes + 1):
                raw_shapes[mode] = {
                    node.id: np.array(
                        [ops.nodeEigenvector(node.id, mode, dof) for dof in range(1, ndf + 1)],
                        dtype=float,
                    )
                    for node in self.project.nodes
                }
        node_mass = {
            node.id: np.array([node.mass[i] for i in self._dof_idx], dtype=float)
            for node in self.project.nodes
        }
        # A repeated eigenvalue gives an arbitrary, with the dense solver even
        # mass-oblique, basis of its eigenspace: make it mass-orthogonal so
        # participation and CQC are basis-invariant, then fix every sign.
        mode_shapes = {
            mode: normalize_mode_sign(shape)
            for mode, shape in orthogonalize_degenerate_modes(
                eigenvalues, raw_shapes, node_mass
            ).items()
        }

        return ModalResults(
            case_id=case.id,
            case_name=case.name,
            eigenvalues=eigenvalues,
            mode_shapes=mode_shapes,
            solver=solver,
            n_free_dof=n_free,
        )

    def _mass_coordinates(self) -> tuple[list[tuple[int, list[float]]], np.ndarray] | None:
        """The coordinates with mass of a condensed eigen solve: ``(loads, M)``, one unit load
        (node, ndf-vector) per coordinate and the mass matrix in those coordinates. A rigid
        diaphragm contributes its retained node's in-plane translations and rotation, with the
        mass and polar inertia of all its nodes about it; every other unrestrained DOF with mass
        one coordinate. None when the condensation does not apply (a diaphragm not
        perpendicular to Z, a mass on a node tied by another constraint, too many
        coordinates): the caller then solves dense."""
        idx = self._dof_idx
        ndf = len(idx)
        position = {c: k for k, c in enumerate(idx)}
        nodes = {n.id: n for n in self.project.nodes}
        diaphragms: list[RigidDiaphragmConstraint] = []
        in_diaphragm: set[int] = set()
        tied: set[int] = set()
        for mp in self.project.mp_constraints:
            if isinstance(mp, RigidDiaphragmConstraint):
                if mp.perp_dir != 3 or ndf != 6:
                    return None
                diaphragms.append(mp)
                in_diaphragm.update([mp.retained_node, *mp.constrained_nodes])
            else:
                tied.update(constrained_nodes(mp))

        def unit(node: int, canonical: int) -> tuple[int, list[float]]:
            vector = [0.0] * ndf
            vector[position[canonical]] = 1.0
            return node, vector

        loads: list[tuple[int, list[float]]] = []
        blocks: list[tuple[list[int], np.ndarray]] = []
        plane = (0, 1, 5)
        for mp in diaphragms:
            master = nodes[mp.retained_node]
            block = np.zeros((3, 3))
            for nid in (mp.retained_node, *mp.constrained_nodes):
                node = nodes[nid]
                dx = node.coords[0] - master.coords[0]
                dy = node.coords[1] - master.coords[1]
                t = np.array([[1.0, 0.0, -dy], [0.0, 1.0, dx], [0.0, 0.0, 1.0]])
                block += t.T @ np.diag([node.mass[c] for c in plane]) @ t
            keep = [k for k, c in enumerate(plane) if not master.restraint[c] and block[k, k] > 0]
            start = len(loads)
            loads.extend(unit(master.id, plane[k]) for k in keep)
            blocks.append((list(range(start, len(loads))), block[np.ix_(keep, keep)]))
        for node in self.project.nodes:
            for c in idx:
                if not node.mass[c] or node.restraint[c]:
                    continue
                if node.id in in_diaphragm and c in plane:
                    continue
                if node.id in tied:
                    return None
                loads.append(unit(node.id, c))
                blocks.append(([len(loads) - 1], np.array([[float(node.mass[c])]])))
        if not loads or len(loads) > CONDENSED_MAX_COORDINATES:
            return None
        mass = np.zeros((len(loads), len(loads)))
        for rows, block in blocks:
            mass[np.ix_(rows, rows)] = block
        return loads, mass

    def _condensed_modes(
        self, n_modes: int, loads: list[tuple[int, list[float]]], mass: np.ndarray
    ) -> tuple[np.ndarray, dict[int, dict[int, np.ndarray]]]:
        """Eigenvalues and mode shapes from the stiffness condensed onto the coordinates with
        mass (:meth:`_mass_coordinates`). One linear static solve per coordinate gives the
        displacement fields ``U`` and the flexibility ``F`` among the coordinates; the massless
        DOF carry no inertia, so ``F·M·φ = φ/ω²`` is the exact eigen problem, and each mode
        shape is the static response to its inertia forces, ``U·M·φ·ω²`` (mass-normalized, as
        OpenSees returns them). Direct, so as reproducible as the dense solver."""
        ops = self._ops
        ndf = len(self._dof_idx)
        ids = [n.id for n in self.project.nodes]
        series = 1 + max([t.id for t in self.project.time_series] + [0])
        pattern = 1 + max([p.id for p in self.project.load_patterns] + [0])
        ops.wipeAnalysis()
        ops.timeSeries("Constant", series)
        ops.system("UmfPack")  # sparse: a banded system of a tall building takes gigabytes
        ops.numberer("RCM")
        ops.constraints(self._constraints_handler("Plain"))
        ops.test("NormDispIncr", 1e-8, 10)
        ops.algorithm("Linear", "-factorOnce")
        ops.integrator("LoadControl", 1.0)
        ops.analysis("Static")
        fields = np.zeros((len(ids) * ndf, len(loads)))
        flexibility = np.zeros((len(loads), len(loads)))
        row = {nid: k * ndf for k, nid in enumerate(ids)}
        for k, (node, vector) in enumerate(loads):
            ops.pattern("Plain", pattern, series)
            ops.load(node, *vector)
            if ops.analyze(1) != 0:
                raise RuntimeError(f"Condensed eigen analysis: the unit load {k + 1} failed.")
            for nid in ids:
                fields[row[nid] : row[nid] + ndf, k] = ops.nodeDisp(nid)[:ndf]
            ops.remove("loadPattern", pattern)
            ops.reset()
        for a, (node, vector) in enumerate(loads):
            flexibility[a, :] = np.asarray(vector) @ fields[row[node] : row[node] + ndf, :]
        flexibility = (flexibility + flexibility.T) / 2
        values, vectors = np.linalg.eigh(mass)
        root = vectors @ np.diag(np.sqrt(np.clip(values, 0.0, None))) @ vectors.T
        lam, psi = np.linalg.eigh(root @ flexibility @ root)
        order = np.argsort(lam)[::-1]
        positive = [k for k in order if lam[k] > 1e-12 * max(lam[order[0]], 1e-300)]
        chosen = positive[:n_modes]
        eigenvalues = np.array([1.0 / lam[k] for k in chosen], dtype=float)
        shapes: dict[int, dict[int, np.ndarray]] = {}
        for mode, k in enumerate(chosen, start=1):
            full = fields @ (root @ psi[:, k]) / lam[k]
            shapes[mode] = {nid: full[row[nid] : row[nid] + ndf].copy() for nid in ids}
        ops.wipeAnalysis()
        return eigenvalues, shapes

    def _run_transient(self, case: TransientCase, results_dir: Path) -> TransientResults:
        ops = self._ops
        results_dir.mkdir(parents=True, exist_ok=True)
        # OpenSees never gets results_dir itself: it may hold characters
        # OpenSees cannot open on Windows. Recorders write into an ASCII
        # staging directory and Python copies the files to recorder_dir.
        recorder_dir = results_dir / "recorders"
        with staging_dir() as stage:
            try:
                return self._run_transient_staged(case, results_dir, recorder_dir, stage)
            finally:
                # Close OpenSees' file handles before the stage is removed
                # (a no-op when the run already flushed its recorders).
                ops.remove("recorders")

    def _run_transient_staged(
        self, case: TransientCase, results_dir: Path, recorder_dir: Path, stage: Path
    ) -> TransientResults:
        import math as _math

        import h5py

        ops = self._ops

        # Preload phase — run each referenced StaticCase to completion
        # before the transient recorders open, so the static solve's
        # intermediate steps don't bloat the time-history file.
        self._run_preload_sequence(
            getattr(case, "preload_case_ids", []) or [],
            case.id,
        )

        # First-mode Rayleigh βK — compute *after* preload so λ₁ reflects
        # the currently loaded tangent stiffness (for linear models this
        # is the same as the unloaded value, but for PDelta frames it
        # picks up the geometric-softening contribution).
        beta_k_override: float | None = None
        damping = getattr(case, "rayleigh_mode1_damping", None)
        if damping is not None:
            # For mode-1 Rayleigh calibration we only need the first
            # eigenvalue. Using the dense solver here avoids ARPACK's
            # small-model failure mode (common in 1-element / 1-storey
            # tutorials) and keeps the damping workflow deterministic.
            if self.project.needs_transformation:
                self._any_ops.constraints("Transformation")
            eigs = ops.eigen("-fullGenLapack", 1)
            lam1 = eigs[0] if hasattr(eigs, "__getitem__") else eigs
            if lam1 <= 0.0:
                raise RuntimeError(
                    f"TransientCase {case.id}: first eigenvalue is "
                    f"{lam1:.3e} — cannot compute mode-1 Rayleigh damping."
                )
            beta_k_override = 2.0 * float(damping) / _math.sqrt(float(lam1))

        # Drop preload patterns the user flagged for removal (classic
        # ``remove loadPattern`` free-vibration idiom).
        for pid in getattr(case, "remove_patterns", []) or []:
            ops.remove("loadPattern", pid)

        # One recorder per quantity for all nodes, and one for the local
        # forces of all elements (hysteresis loops), whatever the model size:
        # every recorder keeps its file open for the whole run and the C
        # runtime allows about 509 open files, so one file per node and
        # element silently lost output on larger models. The "-time" flag
        # prepends the time column to every row. Python splits the columns
        # into the per-node and per-element datasets afterwards.
        node_ids = [n.id for n in self.project.nodes]
        dofs = list(range(1, len(self._dof_idx) + 1))
        node_files = {kind: stage / f"nodes_{kind}.out" for kind in ("disp", "vel", "accel")}
        for kind, path in node_files.items():
            ops.recorder(
                "Node", "-file", str(path), "-time", "-node", *node_ids, "-dof", *dofs, kind
            )
        elem_ids = [el.id for el in self.project.elements if not isinstance(el, TwoNodeLinkElement)]
        elem_file = stage / "elements_localForce.out"
        if elem_ids:
            ops.recorder(
                "Element", "-file", str(elem_file), "-time", "-ele", *elem_ids, "localForce"
            )
        # twoNodeLink elements record their basicForce (see _force_response) in a
        # second recorder, written only when the model has one.
        link_ids = [el.id for el in self.project.elements if isinstance(el, TwoNodeLinkElement)]
        link_file = stage / "elements_basicForce.out"
        link_deformation_file = stage / "elements_basicDeformation.out"
        if link_ids:
            self._any_ops.recorder(
                "Element", "-file", str(link_file), "-time", "-ele", *link_ids, "basicForce"
            )
            # Their basicDeformation, the same order and sign as basicForce.
            self._any_ops.recorder(
                "Element",
                "-file",
                str(link_deformation_file),
                "-time",
                "-ele",
                *link_ids,
                "basicDeformation",
            )

        self._emit_patterns_for_case(case.pattern_ids)
        self._setup_analysis(case)
        # If a mode-1 βK was computed, re-issue ``ops.rayleigh`` with the
        # calibrated coefficient — this overrides whatever _setup_analysis
        # emitted from ``case.rayleigh_beta_k``.
        if beta_k_override is not None:
            ops.rayleigh(
                float(case.rayleigh_alpha_m),
                beta_k_override,
                0.0,
                0.0,
            )

        # Step-by-step with a ModifiedNewton -initial fallback on any
        # step the configured Newton-type algorithm fails to converge.
        # Matches the OpenSees RC Portal Earthquake example's while-
        # loop retry. If the fallback also fails we stop the transient
        # where we got — the recorders already hold the partial
        # history, which is still useful (shows collapse / divergence
        # point) just like the Tcl reference does.
        steps_completed = 0
        for _step in range(case.n_steps):
            status = ops.analyze(1, case.dt)
            if status != 0:
                ops.test(case.test, case.tolerance, 1000)
                ops.algorithm("Newton", "-initial")
                status = ops.analyze(1, case.dt)
                if status != 0:
                    ops.algorithm("Broyden", 8)
                    status = ops.analyze(1, case.dt)
                if status != 0:
                    ops.algorithm("NewtonLineSearch", 0.8)
                    status = ops.analyze(1, case.dt)
                ops.test(case.test, case.tolerance, case.max_iter)
                ops.algorithm(case.algorithm, *case.algorithm_args)
            if status != 0:
                break
            # Counts successful steps only, so enumerate() would be wrong here.
            # Reported as TransientResults.n_steps; recorders write one row
            # per committed step, so the history arrays have the same length.
            steps_completed += 1
            self._progress(steps_completed, case.n_steps)

        # Flush recorders, then consolidate.
        ops.wipeAnalysis()
        ops.remove("recorders")

        if steps_completed == 0:
            # Nothing was committed, so the recorder files are empty and
            # there is no history to consolidate.
            raise RuntimeError(
                f"Transient analysis failed at step 1/{case.n_steps}: "
                "no step converged, even with the fallback algorithms."
            )

        # A recorder that could not open its file leaves nothing behind and
        # OpenSees reports no error: never hand back a silently empty history.
        staged = [
            *node_files.values(),
            *([elem_file] if elem_ids else []),
            *([link_file, link_deformation_file] if link_ids else []),
        ]
        check_recorder_output(staged, steps_completed)

        # Column layout: time, then node by node (each with its ndf DOF), and
        # element by element with the width of its localForce vector (0 for
        # an element without that response, as in the recorder itself).
        ndof = len(dofs)
        node_tables = {
            kind: load_recorder_table(path, steps_completed, 1 + ndof * len(node_ids))
            for kind, path in node_files.items()
        }
        widths = [len(ops.eleResponse(eid, "localForce") or []) for eid in elem_ids]
        elem_table = (
            load_recorder_table(elem_file, steps_completed, 1 + sum(widths)) if elem_ids else None
        )
        link_widths = [len(self._any_ops.eleResponse(eid, "basicForce") or []) for eid in link_ids]
        link_table = (
            load_recorder_table(link_file, steps_completed, 1 + sum(link_widths))
            if link_ids
            else None
        )
        deformation_widths = [
            len(self._any_ops.eleResponse(eid, "basicDeformation") or []) for eid in link_ids
        ]
        deformation_table = (
            load_recorder_table(link_deformation_file, steps_completed, 1 + sum(deformation_widths))
            if link_ids
            else None
        )

        # The raw recorder files keep their place next to the HDF5 file; they
        # are placed first so a failure here leaves the previous HDF5 intact.
        place_files(staged, recorder_dir)

        h5_path = results_dir / f"case_{case.id}.h5"
        tmp_h5 = results_dir / f"case_{case.id}.h5.{os.getpid()}.tmp"
        try:
            with h5py.File(tmp_h5, "w") as f:
                f.create_dataset("time", data=node_tables["disp"][:, 0])
                for i, nid in enumerate(node_ids):
                    cols = slice(1 + i * ndof, 1 + (i + 1) * ndof)
                    for kind, table in node_tables.items():
                        f.create_dataset(f"nodes/{nid}/{kind}", data=table[:, cols])
                if elem_table is not None:
                    start = 1
                    for eid, width in zip(elem_ids, widths, strict=True):
                        f.create_dataset(
                            f"elements/{eid}/forces", data=elem_table[:, start : start + width]
                        )
                        start += width
                if link_table is not None:
                    start = 1
                    for eid, width in zip(link_ids, link_widths, strict=True):
                        f.create_dataset(
                            f"elements/{eid}/forces", data=link_table[:, start : start + width]
                        )
                        start += width
                if deformation_table is not None:
                    start = 1
                    for eid, width in zip(link_ids, deformation_widths, strict=True):
                        f.create_dataset(
                            f"elements/{eid}/deformations",
                            data=deformation_table[:, start : start + width],
                        )
                        start += width
            os.replace(tmp_h5, h5_path)
        except BaseException:
            tmp_h5.unlink(missing_ok=True)
            raise

        return TransientResults(
            case_id=case.id,
            case_name=case.name,
            h5_path=h5_path,
            n_steps=steps_completed,
            dt=case.dt,
            n_steps_requested=case.n_steps,
        )
