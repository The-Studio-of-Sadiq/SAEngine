"""Fiber sections of frame members for nonlinear (pushover) analysis.

The elastic analysis model represents a member by its section constants (EA, EI, GJ). A pushover
must follow the members as they crack and yield, so each frame becomes a force-based fiber
element (``forceBeamColumn``): its section is cut into small areas ("fibers"), each following
the stress-strain curve of its material, and the section forces come from integrating them.

Sections are built from the object types of Part 4:

- reinforced concrete (rectangle or circle with reinforcement): an unconfined cover, a core
  confined by the ties or spiral, and the longitudinal bars as point fibers;
- steel (I, T, L, U, hollow and solid shapes): the plates of the shape.

Material curves (stresses in Pa, compression negative):

- concrete: ``Concrete02`` (Kent-Park with linear tension softening). The core's strength and
  strain capacity rise with the volume of confining steel ρs (modified Kent-Park,
  K = 1 + ρs·fyh/f'c; Scott, Park and Priestley ultimate strain εcu = 0.004 + 0.9·ρs·fyh/300);
  the cover loses its strength by a strain of 0.006 (spalling);
- steel: ``Steel02`` (Giuffré-Menegotto-Pinto) with 1 % strain hardening.

Torsion stays elastic (GJ of the gross section): fiber sections carry axial force and bending.
Concrete members without reinforcement and members of other materials stay elastic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.library.materials import Material
from saengine.library.objects import (
    CircleHollowProfile,
    CircleProfile,
    IShapeProfile,
    LShapeProfile,
    RectangleHollowProfile,
    RectangleProfile,
    TShapeProfile,
    UShapeProfile,
)
from saengine.library.sections import section_properties

MM = 1e-3
MPA = 1e6

#: Strain-hardening ratio of reinforcing and structural steel.
HARDENING = 0.01
#: Strain at the peak stress of unconfined concrete.
EPS_C0 = 0.002
#: Strain by which unconfined (cover) concrete has spalled.
EPS_SPALL = 0.006

#: Fibers across a section's depth and width (concrete core), and through a steel plate.
FIBERS_DEPTH = 12
FIBERS_WIDTH = 6
FIBERS_PLATE = 2


@dataclass
class FiberMaterials:
    """The uniaxial materials of the fiber sections, shared between sections."""

    materials: list[dict[str, Any]] = field(default_factory=list)
    _ids: dict[tuple[Any, ...], int] = field(default_factory=dict)

    def _add(self, key: tuple[Any, ...], value: dict[str, Any]) -> int:
        if key not in self._ids:
            self._ids[key] = len(self.materials) + 1
            self.materials.append({"id": self._ids[key], **value})
        return self._ids[key]

    def concrete(self, material: Material, confinement: float = 0.0, fyh: float = 0.0) -> int:
        """Concrete02 of ``material``: unconfined (cover) or confined by ``confinement`` = ρs
        of ties of yield strength ``fyh`` [MPa] (core)."""
        fc = material.concrete.fc if material.concrete else 20.0
        ec = material.mechanical.E or 4700 * math.sqrt(fc)
        ft = (material.concrete.ft if material.concrete and material.concrete.ft else None) or (
            0.62 * math.sqrt(fc)
        )
        if confinement > 0:
            k = 1 + confinement * fyh / fc
            fpc, epsc0 = k * fc, EPS_C0 * k
            fpcu, eps_u = 0.2 * k * fc, max(0.004 + 0.9 * confinement * fyh / 300, EPS_SPALL)
            name = f"{material.id} core"
        else:
            fpc, epsc0, fpcu, eps_u = fc, EPS_C0, 0.0, EPS_SPALL
            name = f"{material.id} cover"
        return self._add(
            ("concrete", material.id, round(confinement, 6)),
            {
                "name": name,
                "type": "Concrete02",
                "fpc": -fpc * MPA,
                "epsc0": -epsc0,
                "fpcu": -fpcu * MPA,
                "epsU": -eps_u,
                "lambda_": 0.1,
                "ft": ft * MPA,
                # Tension softens to zero over ten times the cracking strain ft/Ec.
                "Ets": 0.1 * ec * MPA,
            },
        )

    def steel(self, material: Material) -> int:
        fy = material.steel.fy if material.steel else 250.0
        return self._add(
            ("steel", material.id),
            {
                "name": material.id,
                "type": "Steel02",
                "Fy": fy * MPA,
                "E0": (material.mechanical.E or 200_000) * MPA,
                "b": HARDENING,
                "R0": 18.0,
                "cR1": 0.925,
                "cR2": 0.15,
            },
        )


@dataclass
class _Section:
    """A section being built, in the profile's own axes: x across its width, y along its depth
    (up for a beam), origin at the middle of its bounding box [m]."""

    patches: list[dict[str, Any]] = field(default_factory=list)
    fibres: list[tuple[float, float, float, int]] = field(default_factory=list)  # x, y, area, mat

    def rect(
        self, material: int, x0: float, y0: float, x1: float, y1: float, nx: int, ny: int
    ) -> None:
        if x1 - x0 > 1e-9 and y1 - y0 > 1e-9:
            self.patches.append(
                {"kind": "rect", "mat": material, "box": (x0, y0, x1, y1), "n": (nx, ny)}
            )

    def ring(self, material: int, r0: float, r1: float, n_circ: int, n_rad: int) -> None:
        if r1 - r0 > 1e-9:
            self.patches.append(
                {"kind": "circ", "mat": material, "r": (r0, r1), "n": (n_circ, n_rad)}
            )

    def bar(self, material: int, x: float, y: float, dia: float) -> None:
        self.fibres.append((x, y, math.pi * dia**2 / 4, material))

    def centroid(self) -> tuple[float, float]:
        """Area centroid of the patches (bars ignored: they sit symmetrically or nearly so)."""
        area = sx = sy = 0.0
        for p in self.patches:
            if p["kind"] == "rect":
                x0, y0, x1, y1 = p["box"]
                a = (x1 - x0) * (y1 - y0)
                area, sx, sy = area + a, sx + a * (x0 + x1) / 2, sy + a * (y0 + y1) / 2
            else:
                r0, r1 = p["r"]
                area += math.pi * (r1**2 - r0**2)  # centred on the origin
        return (sx / area, sy / area) if area else (0.0, 0.0)


def fiber_section(
    section_id: int,
    name: str,
    object_type: Any,
    materials: dict[str, Material],
    library: FiberMaterials,
    vertical: bool,
    quarter_turns: int,
) -> dict[str, Any] | None:
    """The FiberSection of a member of ``object_type``, in the element's local axes, or None when
    it stays elastic (no reinforcement for concrete, no profile or material supported)."""
    material = materials.get(object_type.material)
    profile = getattr(object_type, "profile", None)
    if material is None or profile is None:
        return None
    category = material.category.value
    if category == "concrete":
        built = _concrete(object_type, profile, material, materials, library)
    elif category == "steel":
        built = _steel(profile, library.steel(material))
    else:
        built = None
    if built is None:
        return None

    # Profile axes -> element axes. A beam's depth is its local z (up) and its width local y;
    # a column's depth lies along global Y (local -y) and its width along global X (local z),
    # and a quarter turn swaps them (see derive.local_axes and derive.section).
    cx, cy = built.centroid()

    def local(x: float, y: float) -> tuple[float, float]:
        x, y = x - cx, y - cy
        if not vertical:
            return (x, y)
        return (-x, -y) if quarter_turns % 2 else (-y, x)

    patches: list[dict[str, Any]] = []
    for p in built.patches:
        if p["kind"] == "rect":
            x0, y0, x1, y1 = p["box"]
            (ya, za), (yb, zb) = local(x0, y0), local(x1, y1)
            nx, ny = p["n"]
            # Along local y lies the profile's x for a beam, its y for a column.
            ny_local, nz_local = (nx, ny) if not vertical or quarter_turns % 2 else (ny, nx)
            patches.append(
                {
                    "kind": "rect",
                    "material_id": p["mat"],
                    "n_fib_y": ny_local,
                    "n_fib_z": nz_local,
                    "y_i": min(ya, yb),
                    "z_i": min(za, zb),
                    "y_j": max(ya, yb),
                    "z_j": max(za, zb),
                }
            )
        else:
            r0, r1 = p["r"]
            yc, zc = local(0.0, 0.0)
            n_circ, n_rad = p["n"]
            patches.append(
                {
                    "kind": "circ",
                    "material_id": p["mat"],
                    "n_fib_circ": n_circ,
                    "n_fib_rad": n_rad,
                    "y_center": yc,
                    "z_center": zc,
                    "r_inner": r0,
                    "r_outer": r1,
                }
            )
    fibres = []
    for x, y, area, mat in built.fibres:
        yl, zl = local(x, y)
        fibres.append({"y": yl, "z": zl, "area": area, "material_id": mat})
    props = section_properties(profile)
    e = (material.mechanical.E or 0.0) * MPA
    nu = (
        material.mechanical.nu
        if material.mechanical.nu is not None
        else (0.2 if category == "concrete" else 0.3)
    )
    return {
        "id": section_id,
        "name": name,
        "type": "FiberSection",
        "GJ": max(e / (2 * (1 + nu)) * props.j * MM**4, 1.0),
        "patches": patches,
        "layers": [],
        "fibres": fibres,
    }


def _concrete(
    object_type: Any,
    profile: Any,
    material: Material,
    materials: dict[str, Material],
    library: FiberMaterials,
) -> _Section | None:
    reinforcement = getattr(object_type, "reinforcement", None)
    if reinforcement is None or not reinforcement.longitudinal:
        return None
    rebar = materials.get(reinforcement.material)
    if rebar is None:
        return None
    bar_mat = library.steel(rebar)
    ties = reinforcement.transverse
    tie_dia = ties.dia * MM if ties else 0.0
    cover = reinforcement.cover * MM
    to_core = cover + tie_dia / 2  # core: to the centre line of the ties
    fyh = rebar.steel.fy if rebar.steel else 420.0
    s = _Section()

    if isinstance(profile, RectangleProfile):
        b, h = profile.xDim * MM, profile.yDim * MM
        bc, hc = b - 2 * to_core, h - 2 * to_core
        if bc <= 0 or hc <= 0:
            return None
        rho = 0.0
        if ties and ties.spacing > 0:
            tie_area = math.pi * tie_dia**2 / 4
            rho = ties.legs * tie_area * (bc + hc) / (bc * hc * ties.spacing * MM)
        core = library.concrete(material, rho, fyh) if rho > 0 else library.concrete(material)
        shell = library.concrete(material)
        s.rect(core, -bc / 2, -hc / 2, bc / 2, hc / 2, FIBERS_WIDTH, FIBERS_DEPTH)
        s.rect(shell, -b / 2, hc / 2, b / 2, h / 2, FIBERS_WIDTH, 1)
        s.rect(shell, -b / 2, -h / 2, b / 2, -hc / 2, FIBERS_WIDTH, 1)
        s.rect(shell, -b / 2, -hc / 2, -bc / 2, hc / 2, 1, FIBERS_DEPTH)
        s.rect(shell, bc / 2, -hc / 2, b / 2, hc / 2, 1, FIBERS_DEPTH)
        for group in reinforcement.longitudinal:
            d = group.dia * MM
            to_bar = cover + tie_dia + d / 2
            xb, yb = b / 2 - to_bar, h / 2 - to_bar
            for x, y in _bars_in_rectangle(group.position, group.count, xb, yb):
                s.bar(bar_mat, x, y, d)
        return s

    if isinstance(profile, CircleProfile):
        r = profile.radius * MM
        rc = r - to_core
        if rc <= 0:
            return None
        rho = 0.0
        if ties and ties.spacing > 0:
            rho = 4 * (math.pi * tie_dia**2 / 4) / (2 * rc * ties.spacing * MM)
        core = library.concrete(material, rho, fyh) if rho > 0 else library.concrete(material)
        s.ring(core, 0.0, rc, 16, 8)
        s.ring(library.concrete(material), rc, r, 16, 1)
        for group in reinforcement.longitudinal:
            d = group.dia * MM
            rb = r - cover - tie_dia - d / 2
            for k in range(group.count):
                a = 2 * math.pi * k / group.count
                s.bar(bar_mat, rb * math.cos(a), rb * math.sin(a), d)
        return s
    return None


def _bars_in_rectangle(
    position: str, count: int, xb: float, yb: float
) -> list[tuple[float, float]]:
    """Bar centres of a group within the rectangle ±xb × ±yb (bar centre lines)."""

    def spread(n: int, a: float, b: float) -> list[float]:
        return [(a + b) / 2] if n == 1 else [a + (b - a) * i / (n - 1) for i in range(n)]

    if position == "top":
        return [(x, yb) for x in spread(count, -xb, xb)]
    if position == "bottom":
        return [(x, -yb) for x in spread(count, -xb, xb)]
    if position == "sides":
        # Between the top and bottom bars, half on each side.
        per_side = [count - count // 2, count // 2]
        result = []
        for side, n in zip((-xb, xb), per_side, strict=True):
            result += [(side, -yb + 2 * yb * (i + 1) / (n + 1)) for i in range(n)]
        return result
    # Perimeter: the four corners, then the rest along the sides in proportion to their length.
    if count < 4:
        return [(x, 0.0) for x in spread(count, -xb, xb)]
    rest = count - 4
    across = round(rest * xb / (xb + yb) / 2)  # between the corners of the top, and the bottom
    along = (rest - 2 * across) // 2  # between the corners of each side
    top = across + (rest - 2 * across - 2 * along)  # an odd bar goes to the top

    def inner(n: int, half: float) -> list[float]:
        return [-half + 2 * half * (i + 1) / (n + 1) for i in range(n)]

    result = [(-xb, -yb), (xb, -yb), (xb, yb), (-xb, yb)]
    result += [(x, yb) for x in inner(top, xb)] + [(x, -yb) for x in inner(across, xb)]
    result += [(xb, y) for y in inner(along, yb)] + [(-xb, y) for y in inner(along, yb)]
    return result


def _steel(profile: Any, mat: int) -> _Section | None:
    s = _Section()
    n, p = FIBERS_DEPTH, FIBERS_PLATE
    if isinstance(profile, RectangleProfile):
        b, h = profile.xDim * MM, profile.yDim * MM
        s.rect(mat, -b / 2, -h / 2, b / 2, h / 2, FIBERS_WIDTH, n)
    elif isinstance(profile, CircleProfile):
        s.ring(mat, 0.0, profile.radius * MM, 16, 8)
    elif isinstance(profile, CircleHollowProfile):
        r = profile.radius * MM
        s.ring(mat, r - profile.wallThickness * MM, r, 24, p)
    elif isinstance(profile, RectangleHollowProfile):
        b, h, t = profile.xDim * MM, profile.yDim * MM, profile.wallThickness * MM
        s.rect(mat, -b / 2, h / 2 - t, b / 2, h / 2, FIBERS_WIDTH, p)
        s.rect(mat, -b / 2, -h / 2, b / 2, -h / 2 + t, FIBERS_WIDTH, p)
        s.rect(mat, -b / 2, -h / 2 + t, -b / 2 + t, h / 2 - t, p, n)
        s.rect(mat, b / 2 - t, -h / 2 + t, b / 2, h / 2 - t, p, n)
    elif isinstance(profile, IShapeProfile):
        b, h = profile.overallWidth * MM, profile.overallDepth * MM
        tf, tw = profile.flangeThickness * MM, profile.webThickness * MM
        s.rect(mat, -b / 2, h / 2 - tf, b / 2, h / 2, FIBERS_WIDTH, p)
        s.rect(mat, -b / 2, -h / 2, b / 2, -h / 2 + tf, FIBERS_WIDTH, p)
        s.rect(mat, -tw / 2, -h / 2 + tf, tw / 2, h / 2 - tf, p, n)
    elif isinstance(profile, TShapeProfile):
        b, h = profile.flangeWidth * MM, profile.depth * MM
        tf, tw = profile.flangeThickness * MM, profile.webThickness * MM
        s.rect(mat, -b / 2, h / 2 - tf, b / 2, h / 2, FIBERS_WIDTH, p)
        s.rect(mat, -tw / 2, -h / 2, tw / 2, h / 2 - tf, p, n)
    elif isinstance(profile, UShapeProfile):
        b, h = profile.flangeWidth * MM, profile.depth * MM
        tf, tw = profile.flangeThickness * MM, profile.webThickness * MM
        s.rect(mat, -b / 2, h / 2 - tf, b / 2, h / 2, FIBERS_WIDTH, p)
        s.rect(mat, -b / 2, -h / 2, b / 2, -h / 2 + tf, FIBERS_WIDTH, p)
        s.rect(mat, -b / 2, -h / 2 + tf, -b / 2 + tw, h / 2 - tf, p, n)
    elif isinstance(profile, LShapeProfile):
        b, h, t = profile.width * MM, profile.depth * MM, profile.thickness * MM
        s.rect(mat, -b / 2, -h / 2, b / 2, -h / 2 + t, FIBERS_WIDTH, p)
        s.rect(mat, -b / 2, -h / 2 + t, -b / 2 + t, h / 2, p, n)
    else:
        return None
    return s


# ───────────────────────────── the pushover model ─────────────────────────────

#: Share of the live load on the structure while it is pushed (with D and SD), as in its
#: seismic weight.
LIVE_SHARE = 0.25


def pushover_model(
    linear: dict[str, Any],
    section_keys: dict[int, tuple[str, int, bool]],
    types: dict[str, Any],
    materials: dict[str, Material],
    node_weight: dict[int, float],
    base: float,
    options: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """The pushover model (``08 FEM/pushover.osmodel``) of the derived analysis model ``linear``.

    The same nodes, floors, supports and loads; frames become force-based fiber elements
    (``section_keys`` maps each elastic section id to its object type, quarter turns and
    whether it is vertical); walls and slabs stay elastic shells. It holds one gravity case
    (D + SD + 0.25 L) and a pushover per direction, driving the roof to ``options.targetDrift``
    percent of the height above ``base`` [m] after the gravity loads.
    """
    import copy

    notes: list[str] = []
    project = copy.deepcopy(linear)
    library = FiberMaterials()

    # ── fiber sections, one per elastic frame section that can have one ──
    fiber_of: dict[int, int] = {}
    elastic_types: set[str] = set()
    for elastic_id, (type_id, turns, vertical) in section_keys.items():
        object_type = types.get(type_id)
        section = None
        if object_type is not None:
            section = fiber_section(
                len(project["sections"]) + 1,
                f"{type_id} {'column' if vertical else 'beam'} fibers",
                object_type,
                materials,
                library,
                vertical,
                turns,
            )
        if section is None:
            elastic_types.add(type_id)
            continue
        project["sections"].append(section)
        fiber_of[elastic_id] = section["id"]
    if elastic_types:
        notes.append(
            "pushover: members of "
            + ", ".join(sorted(elastic_types))
            + " stay elastic (concrete without reinforcement, or a profile or material without "
            "a fiber section)"
        )
    project["materials"] = library.materials

    vertical_ids = {sid for sid, (_, _, vertical) in section_keys.items() if vertical}
    frames = 0
    for element in project["elements"]:
        if element["type"] != "ElasticBeamColumn" or element["section_id"] not in fiber_of:
            continue
        frames += 1
        column = element["section_id"] in vertical_ids
        element.update(
            {
                "type": "ForceBeamColumn",
                "section_id": fiber_of[element["section_id"]],
                "integration_points": 5,
                "integration": "Lobatto",
                # A force-based element iterates for its own deformations; ten iterations
                # (OpenSees' default) are too few once its concrete crushes.
                "max_iter": 100,
                "tolerance": 1e-10,
                # Columns carry the gravity load through the sway: P-Delta.
                "geom_transf": "PDelta" if column else "Linear",
            }
        )
        element.pop("rho", None)
        element.pop("consistent_mass", None)
    if not frames:
        return None, [*notes, "pushover: no frame member has a fiber section; no pushover model"]
    if any(e["type"] == "Shell" for e in project["elements"]):
        notes.append("pushover: walls and shell slabs stay elastic")

    # ── loads: gravity (D + SD + 0.25 L) and the lateral patterns ──
    by_name = {p["name"]: p for p in project["load_patterns"]}
    nodal: dict[int, list[float]] = {}
    element_loads: dict[int, list[float]] = {}
    for name, factor in (("D", 1.0), ("SD", 1.0), ("L", LIVE_SHARE)):
        pattern = by_name.get(name, {})
        for load in pattern.get("nodal_loads", []):
            total = nodal.setdefault(load["node_id"], [0.0] * 6)
            for k, f in enumerate(load["forces"]):
                total[k] += factor * f
        for load in pattern.get("element_loads", []):
            total = element_loads.setdefault(load["element_id"], [0.0] * 3)
            for k, key in enumerate(("wx", "wy", "wz")):
                total[k] += factor * load.get(key, 0.0)
    project["time_series"] = [s for s in project["time_series"] if s["id"] == 1]
    project["load_patterns"] = [p for p in project["load_patterns"] if p["type"] == "Plain"]
    project["spectra"] = []
    project["ground_motions"] = []
    gravity_id = max(p["id"] for p in project["load_patterns"]) + 1
    project["load_patterns"].append(
        {
            "id": gravity_id,
            "name": "G",
            "type": "Plain",
            "time_series_id": 1,
            "nodal_loads": [
                {"node_id": n, "forces": [round(f, 3) for f in v]} for n, v in sorted(nodal.items())
            ],
            "element_loads": [
                {"element_id": e, "wx": round(v[0], 3), "wy": round(v[1], 3), "wz": round(v[2], 3)}
                for e, v in sorted(element_loads.items())
            ],
        }
    )

    coords = {n["id"]: n["coords"] for n in project["nodes"]}
    supports = [n["id"] for n in project["nodes"] if all(n.get("restraint") or [])]
    control = _control_node(project, node_weight)
    height = coords[control][2] - base
    if height <= 0 or not supports:
        return None, [*notes, "pushover: the structure has no height above its supports"]
    target = options.targetDrift / 100 * height

    analyses: list[dict[str, Any]] = [
        {
            "id": 1,
            "name": "G: Gravity (D + SD + 0.25L)",
            "type": "Static",
            "pattern_ids": [gravity_id],
            "n_steps": 10,
            "load_factor_increment": 0.1,
            "system": "BandGeneral",
            "constraints": "Plain",
            "integrator": "LoadControl",
            "algorithm": "Newton",
            "test": "NormDispIncr",
            "tolerance": 1e-8,
            "max_iter": 50,
        }
    ]
    for axis in options.directions:
        dof = 1 if axis == "X" else 2
        pattern_id = _lateral_pattern(project, axis, dof, options.pattern, node_weight, notes)
        analyses.append(
            {
                "id": len(analyses) + 1,
                "name": f"P{axis}: Pushover {axis}",
                "type": "Pushover",
                "pattern_ids": [pattern_id],
                "control_node": control,
                "control_dof": dof,
                "target_disp": round(target, 6),
                "step_size": round(target / options.steps, 9),
                "base_nodes": supports,
                "preload_case_ids": [1],
                "system": "BandGeneral",
                "algorithm": "Newton",
                "test": "NormDispIncr",
                "tolerance": 1e-6,
                "max_iter": 50,
            }
        )
    project["analyses"] = analyses
    meta = project["meta"]
    project["meta"] = {
        **meta,
        "name": f"{meta['name']} (pushover)",
        "description": meta["description"].replace(
            "Derived by SAEngine", "Pushover model derived by SAEngine", 1
        ),
    }
    return project, notes


def _control_node(project: dict[str, Any], node_weight: dict[int, float]) -> int:
    """The roof node pushed: the top floor's own node (rigid floors), else the highest node
    with mass nearest the middle of the roof."""
    coords = {n["id"]: n["coords"] for n in project["nodes"]}
    retained = [
        c["retained_node"] for c in project.get("mp_constraints", []) if "retained_node" in c
    ]
    if retained:
        return max(retained, key=lambda n: coords[n][2])
    top = max(c[2] for c in coords.values())
    roof = [n for n, c in coords.items() if abs(c[2] - top) < 1e-6]
    weighted = [n for n in roof if node_weight.get(n)] or roof
    cx = sum(coords[n][0] for n in weighted) / len(weighted)
    cy = sum(coords[n][1] for n in weighted) / len(weighted)
    return min(weighted, key=lambda n: (coords[n][0] - cx) ** 2 + (coords[n][1] - cy) ** 2)


def _lateral_pattern(
    project: dict[str, Any],
    axis: str,
    dof: int,
    kind: str,
    node_weight: dict[int, float],
    notes: list[str],
) -> int:
    """The id of the reference lateral load pattern of a pushover in ``axis``."""
    seismic = next((p for p in project["load_patterns"] if p["name"] == f"E{axis}"), None)
    if kind == "seismic" and seismic and seismic["nodal_loads"]:
        return seismic["id"]
    if kind == "seismic":
        notes.append(
            f"pushover {axis}: no story forces (special structure or no seismic zone); the "
            "lateral load follows the masses"
        )
    pattern_id = max(p["id"] for p in project["load_patterns"]) + 1
    project["load_patterns"].append(
        {
            "id": pattern_id,
            "name": f"U{axis}",
            "type": "Plain",
            "time_series_id": 1,
            "nodal_loads": [
                {"node_id": n, "forces": [round(w, 3) if k == dof - 1 else 0.0 for k in range(6)]}
                for n, w in sorted(node_weight.items())
                if w > 0
            ],
            "element_loads": [],
        }
    )
    return pattern_id
