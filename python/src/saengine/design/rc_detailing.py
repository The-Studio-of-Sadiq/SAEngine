"""Reinforced-concrete detailing and material rules that follow the concrete's aggregate and
the code pack in force (B21).

Every number comes from the code pack: ``concrete.aggregates``, ``concrete.modulus`` and
``concrete.shrinkage`` (the material rules), ``detailing.crackControl``, ``skin``,
``flangeTension``, ``integrity``, ``shearFriction`` and ``tendonSpacing`` (the detailing
checks), and the clause references from the tables' ``clauses``. A pack without one of these
groups leaves the check out and says that the pack does not cover it.

- **Aggregate.** Project Settings > Construction > Concrete aggregate (the generic setting the
  fire resistance checks also read). :func:`using_aggregate` makes it the aggregate in force for
  a design run; without it the project's settings are read (the RPC server sets the project
  root), else the first of the pack's aggregates is taken.
- **Ec** (:func:`concrete_modulus`): normal weight ``modulus.normal √f'c``; the density form
  ``densityCoefficient wc^densityExponent √f'c`` for lightweight aggregates (wc within
  ``densityRange``); brick aggregate ``modulus.brick √f'c``. A concrete whose E is still the
  default (the normal-weight Ec the materials editor fills) takes the aggregate's Ec in the
  analysis and design (:func:`aggregate_moduli`); an E the engineer typed wins, and
  :func:`material_notes` flags a typed E that differs from the aggregate's rule (or is the
  normal-weight value on a brick aggregate concrete).
- **Shrinkage and temperature steel** (:func:`shrinkage_ratio`): ``ratioLow`` below
  ``referenceFy``, else ``ratioReference × referenceFy / fy`` and at least ``ratioMin``, times
  the aggregate's ``shrinkageFactor``; spaced at most ``slabCoefficients.maxSpacing.
  temperature``.
- **Crack control** (:func:`crack_spacing_limit`): the bars nearest the tension face at most
  ``coefficient (reference / fs) - coverFactor cc`` and ``cap (reference / fs)`` apart, fs =
  ``serviceStressShare fy``; one bar: s is the width of the tension face.
- **Skin steel** (:func:`skin_check`): beams deeper than ``depthOver`` need side bars over
  ``extentShare h`` from the tension face, spaced as the crack control with cc to the side.
- **Flange tension** (:func:`flange_note`): part of the hogging steel of a T-beam spread over
  the smaller of the effective flange width and ``spanShare`` × the span.
- **Structural integrity** (:func:`integrity_check`): continuous bottom bars in every beam and
  continuous top bars in perimeter beams, at least ``minBars``; the bars of a SAEngine beam
  type run its whole length, so the shares of the support and midspan steel hold by
  construction and the splice positions are noted for the drawings.
- **Shear friction** (:func:`shear_friction`): Vn = μ (Avf fy - net tension), μ by the
  surface (``mu``) times λ, fy at most ``fyMax``, Vn at most the ``roughLimits`` or
  ``otherLimits``; the column construction joints at each floor and the floor-to-wall
  connections of the diaphragms use it.
- **Class C tendons** (:func:`tendon_spacing_limit`): Δfps in place of fs, bonded tendons at
  ``share`` and bars beside tendons at ``mixedShare`` of the limit.

Units: mm, N, MPa.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

__all__ = [
    "ShearFrictionResult",
    "aggregate_moduli",
    "aggregate_rules",
    "beam_checks",
    "beam_top_drops",
    "building_bottom_rises",
    "building_top_drops",
    "clause",
    "column_joint_check",
    "concrete_modulus",
    "crack_spacing_limit",
    "current_aggregate",
    "face_spacing",
    "flange_note",
    "follows_default",
    "integrity_check",
    "joint_bottom_layers",
    "joint_mode",
    "joint_top_layers",
    "lambda_factor",
    "main_direction",
    "material_modulus",
    "material_notes",
    "shear_friction",
    "shrinkage_ratio",
    "shrinkage_spacing",
    "skin_check",
    "tendon_spacing_limit",
    "using_aggregate",
    "wall_joint_check",
]

#: The aggregate in force for a design run (None: read the project's settings).
_AGGREGATE: ContextVar[str | None] = ContextVar("saengine_aggregate", default=None)
#: Position tolerance [mm] when grouping bars into the outer row of a face.
_ROW = 1.0


# ───────────────────────────────────────── the aggregate ─────────────────────────────────────────


def aggregate_of(settings: Any) -> str | None:
    """The aggregate type of a project's settings (Construction > Concrete aggregate)."""
    construction = getattr(settings, "construction", None)
    value = getattr(construction, "aggregate", None) if construction is not None else None
    if value is None and isinstance(settings, dict):
        value = (settings.get("construction") or {}).get("aggregate")
    return str(value) if value else None


@contextmanager
def using_aggregate(settings: Any) -> Iterator[str | None]:
    """Within the block, :func:`current_aggregate` is the aggregate of ``settings`` (a
    :class:`ProjectSettings`, its dict, or an aggregate id)."""
    value = settings if isinstance(settings, str) else aggregate_of(settings)
    token = _AGGREGATE.set(value)
    try:
        yield value
    finally:
        _AGGREGATE.reset(token)


def _project_aggregate() -> str | None:
    root = code_context.project_root()
    if root is None:
        return None
    path = Path(root) / "02 Project Settings" / "project-settings.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _READ.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = aggregate_of(data) if isinstance(data, dict) else None
    _READ[path] = (stamp, value)
    return value


#: The aggregate read from a project's settings file, by file and modification time.
_READ: dict[Path, tuple[int, str | None]] = {}


def current_aggregate() -> str:
    """The aggregate in force: :func:`using_aggregate`'s, else the project's settings, else the
    pack's first aggregate (the settings' default, siliceous, for the default pack)."""
    value = _AGGREGATE.get() or _project_aggregate()
    if value:
        return value
    aggregates = getattr(_concrete(), "aggregates", None) or {}
    return next(iter(aggregates), "siliceous")


def _concrete() -> Any:
    return code_context.pack_table("concrete")


def _detailing() -> Any:
    return code_context.pack_table("detailing")


def _material_group(name: str) -> tuple[Any, bool]:
    """(group ``name`` of the concrete table, whether the pack in force gives it). A material
    rule every design needs (Ec, the slabs' least steel) the pack does not give comes from the
    generic defaults (``codes/generic``), named as such (:func:`_generic`)."""
    group = getattr(_concrete(), name, None)
    if group is not None:
        return group, code_context.current().fallback("concrete", name) is None
    # Only a pack without a concrete table at all gets here (it reads the default pack's).
    from saengine.codes.registry import DEFAULT_PACK
    from saengine.codes.tables import builtin_table

    return getattr(builtin_table("concrete", DEFAULT_PACK), name), True


def _generic(name: str) -> str:
    """How results name the generic default of the concrete table's group ``name``."""
    from saengine.codes import generic

    pack = code_context.current()
    note = generic.note("concrete", name).split(" (")[0]
    return generic.label(pack.edition or pack.name) + (f": {note}" if note else "")


def clause(table: str, key: str) -> str:
    """The pack's clause reference ``key`` of table ``table`` ("concrete" or "detailing"),
    after the pack's edition; empty when the pack gives none."""
    found = getattr(code_context.pack_table(table), "clauses", None) or {}
    text = found.get(key)
    if not text:
        return ""
    pack = code_context.current()
    # Alpha 9 C5b: an inherited clause is named after the pack that wrote it.
    owner = pack.clause_code(table, key) if hasattr(pack, "clause_code") else None
    return f"{owner or pack.edition or pack.name} {text}"


def _not_covered(what: str) -> str:
    pack = code_context.current()
    return f"{what}: not covered by the code pack {pack.name}"


def aggregate_rules(aggregate: str | None = None) -> Any:
    """The pack's rules of ``aggregate`` (None: the one in force; "": none, normal weight);
    None when it gives none."""
    aggregates = getattr(_concrete(), "aggregates", None) or {}
    return aggregates.get(aggregate if aggregate is not None else current_aggregate())


def modulus_rules() -> Any:
    """The pack's ``concrete.modulus`` (the generic default when the pack in force has none)."""
    return _material_group("modulus")[0]


def lambda_factor(aggregate: str | None = None) -> float:
    """λ of the aggregate (1 when the pack gives none)."""
    rules = aggregate_rules(aggregate)
    return float(rules.lambdaFactor) if rules is not None else 1.0


# ─────────────────────────────────────────── materials ───────────────────────────────────────────


def concrete_modulus(
    fc: float, density: float | None = None, aggregate: str | None = None
) -> tuple[float, str]:
    """(Ec [MPa], how) of concrete of ``fc`` [MPa] and ``density`` [kg/m³] with ``aggregate``
    (default: in force) by the pack's ``concrete.modulus`` (the generic default when it gives
    none); normal weight for an aggregate the pack does not list."""
    rules, covered = _material_group("modulus")
    root = math.sqrt(max(fc, 0.0))
    if not covered:
        return rules.normal * root, f"Ec = {rules.normal:g} √f'c ({_generic('modulus')})"
    kind = getattr(aggregate_rules(aggregate), "modulus", "normal")
    if kind == "brick":
        return (
            rules.brick * root,
            f"Ec = {rules.brick:g} √f'c ({clause('concrete', 'modulusBrick')})",
        )
    low, high = rules.densityRange
    if kind == "density" and density is not None and low <= density <= high:
        ec = rules.densityCoefficient * density**rules.densityExponent * root
        return ec, (
            f"Ec = {rules.densityCoefficient:g} wc^{rules.densityExponent:g} √f'c, wc = "
            f"{density:g} kg/m³ ({clause('concrete', 'modulusDensity')})"
        )
    note = f"Ec = {rules.normal:g} √f'c ({clause('concrete', 'modulus')})"
    if kind == "density":
        note += "; the density is not given within the density form's range"
    return rules.normal * root, note


#: An E within this share of the pack's normal-weight Ec of its f'c is the default the
#: materials editor writes (it rounds to 10 MPa), not a value the engineer typed.
_FOLLOWS = 0.005


def _normal_modulus(fc: float) -> float:
    """The pack's normal-weight Ec of ``fc`` [MPa]: the value a concrete's E holds by default."""
    return modulus_rules().normal * math.sqrt(max(fc, 0.0))


def follows_default(e: float | None, fc: float) -> bool:
    """Whether ``e`` [MPa] is the default E of a concrete of ``fc`` (the pack's normal-weight
    Ec, as the materials editor fills it), not one the engineer typed."""
    normal = _normal_modulus(fc)
    return not e or (normal > 0 and abs(e - normal) <= _FOLLOWS * normal)


def material_modulus(
    material: Any, aggregate: str | None = None, fc: float | None = None
) -> tuple[float, str]:
    """(E [MPa], how) of a concrete ``material``, the one E every analysis and design takes:
    the E the engineer typed; else (its E is the default, :func:`follows_default`, or none)
    :func:`concrete_modulus` of its f'c, density and ``aggregate`` (default: in force), to 10
    MPa as the editor rounds; the stored default itself where the aggregate's Ec is the same.
    ``fc``: the f'c [MPa] when the material gives none (or there is no material)."""
    mechanical = getattr(material, "mechanical", None)
    e = getattr(mechanical, "E", None)
    concrete = getattr(material, "concrete", None)
    strength = float(concrete.fc) if concrete is not None else fc
    if strength is None:
        return float(e or 0.0), "the material's E"
    if e and not follows_default(e, strength):
        return float(e), "the material's E (typed)"
    code, how = concrete_modulus(strength, getattr(mechanical, "density", None), aggregate)
    if e and code > 0 and abs(e - code) <= _FOLLOWS * code:
        return float(e), how
    return float(round(code / 10) * 10), how


def aggregate_moduli(materials: Any, aggregate: str | None = None) -> tuple[Any, list[str]]:
    """(``materials`` with the default E of each concrete set by the aggregate's Ec, notes):
    each concrete takes :func:`material_modulus` (a typed E kept, a default one the
    aggregate's, e.g. ``modulus.brick √f'c`` for brick aggregate). The library itself is not
    changed (a copy is returned)."""
    aggregate = aggregate or current_aggregate()
    changed, notes = [], []
    for material in getattr(materials, "materials", []) or []:
        concrete = getattr(material, "concrete", None)
        mechanical = getattr(material, "mechanical", None)
        e = getattr(mechanical, "E", None)
        if concrete is None or mechanical is None:
            changed.append(material)
            continue
        code, how = material_modulus(material, aggregate)
        if code > 0 and code != e:
            material = material.model_copy(
                update={"mechanical": mechanical.model_copy(update={"E": code})}
            )
            notes.append(
                f"{material.id}: E = {code:g} MPa for {aggregate} aggregate ({how}), in place "
                f"of the normal-weight default {e or 0:.0f} MPa; type another E in 03 Materials "
                "to override it"
            )
        changed.append(material)
    if not notes:
        return materials, []
    return materials.model_copy(update={"materials": changed}), notes


def material_notes(materials: Any, aggregate: str | None = None) -> list[str]:
    """Notes on concrete materials whose typed E (not the default, :func:`aggregate_moduli`)
    differs by more than 10 % from the aggregate's Ec, or, where the aggregate has its own Ec
    (brick), is within 10 % of the normal-weight Ec (the stone-aggregate value typed by hand).
    The analysis and design use the typed E."""
    aggregate = aggregate or current_aggregate()
    notes: list[str] = []
    for material in getattr(materials, "materials", []) or []:
        concrete = getattr(material, "concrete", None)
        e = getattr(getattr(material, "mechanical", None), "E", None)
        if concrete is None or follows_default(e, concrete.fc):
            continue
        density = getattr(material.mechanical, "density", None)
        code, how = concrete_modulus(concrete.fc, density, aggregate)
        normal = _normal_modulus(concrete.fc)
        own_rule = normal > 0 and abs(code - normal) > _FOLLOWS * normal
        if own_rule and abs(e - normal) / normal <= 0.10:
            notes.append(
                f"{material.id}: the typed E = {e:g} MPa looks like the normal-weight (stone "
                f"aggregate) value {normal:.0f} MPa, but the aggregate is {aggregate}: "
                f"{code:.0f} MPa ({how}); the analysis and design use the typed E: reset it to "
                "the default in 03 Materials to follow the aggregate, or keep it if it comes "
                "from tests"
            )
        elif code > 0 and abs(e - code) / code > 0.10:
            notes.append(
                f"{material.id}: the typed E = {e:g} MPa differs by {abs(e - code) / code:.0%} "
                f"from {code:.0f} MPa for {aggregate} aggregate ({how}); the analysis and design "
                "use the typed E: reset it to the default in 03 Materials to follow the "
                "aggregate, or keep it if it comes from tests"
            )
    return notes


def shrinkage_ratio(fy: float, aggregate: str | None = None) -> tuple[float, str]:
    """(ratio of As to the gross area, how) of the shrinkage and temperature steel (and the
    As,min of slabs) for ``fy`` [MPa] with ``aggregate`` (default: in force)."""
    rules, covered = _material_group("shrinkage")
    if fy < rules.referenceFy:
        ratio = rules.ratioLow
        how = f"{ratio:.4f} for fy {fy:g} < {rules.referenceFy:g} MPa"
    else:
        ratio = max(rules.ratioReference * rules.referenceFy / fy, rules.ratioMin)
        how = (
            f"max({rules.ratioReference:g} × {rules.referenceFy:g}/fy, {rules.ratioMin:g}) = "
            f"{ratio:.4f}"
        )
    how += f" ({clause('concrete', 'shrinkage')})" if covered else f" ({_generic('shrinkage')})"
    agg = aggregate if aggregate is not None else current_aggregate()
    factor = float(getattr(aggregate_rules(agg), "shrinkageFactor", 1.0) or 1.0)
    if factor != 1.0:
        ratio *= factor
        how += f"; × {factor:g} for {agg} aggregate ({clause('concrete', 'shrinkageBrick')})"
    return ratio, how


def shrinkage_spacing(h: float) -> tuple[float, str]:
    """(largest spacing [mm], clause text) of the shrinkage and temperature bars of a slab
    ``h`` [mm] thick."""
    times, most = (
        float(v) for v in code_context.pack_table("slabCoefficients").maxSpacing["temperature"]
    )
    return (
        min(times * h, most),
        f"{clause('concrete', 'shrinkageSpacing')}: min({times:g}h, {most:g} mm)",
    )


# ──────────────────────────────────────── crack control ────────────────────────────────────────


def crack_spacing_limit(fs: float, cc: float) -> float | None:
    """Largest spacing [mm] of the bars nearest a tension face at service stress ``fs`` [MPa]
    with ``cc`` [mm] from their surface to the face; None when the pack has no rule."""
    rule = getattr(_detailing(), "crackControl", None)
    if rule is None or fs <= 0:
        return None
    ratio = rule.reference / fs
    return min(rule.coefficient * ratio - rule.coverFactor * cc, rule.cap * ratio)


def service_stress(fy: float) -> float:
    """fs [MPa] the pack permits instead of a service-load analysis (0 without a rule)."""
    rule = getattr(_detailing(), "crackControl", None)
    return rule.serviceStressShare * fy if rule is not None else 0.0


def tendon_spacing_limit(
    delta_fps: float, cc: float, mixed: bool = False
) -> tuple[float | None, str]:
    """(largest spacing [mm] or None for no limit, how) of the bonded tendons nearest the
    tension face of a Class C prestressed member, Δfps [MPa] the tendon stress at service
    loads above decompression; ``mixed``: a bar beside a tendon."""
    rule = getattr(_detailing(), "tendonSpacing", None)
    if rule is None:
        return None, _not_covered("tendon spacing")
    where = clause("detailing", "tendonSpacing")
    if delta_fps > rule.deltaMax:
        return 0.0, f"Δfps {delta_fps:g} MPa above {rule.deltaMax:g} MPa ({where})"
    limit = crack_spacing_limit(max(delta_fps, 1e-9), cc)
    if limit is None:
        return None, _not_covered("crack control")
    if delta_fps <= rule.deltaExempt:
        return limit, f"Δfps <= {rule.deltaExempt:g} MPa: the full spacing ({where})"
    share = rule.mixedShare if mixed else rule.share
    return share * limit, f"{share:g} × the spacing with Δfps for fs ({where})"


@dataclass
class FaceSpacing:
    """The bars nearest one tension face of a rectangle."""

    spacing: float  # largest centre-to-centre spacing; the face width for one bar [mm]
    cc: float  # clear distance from their surface to the face [mm]
    count: int


def _outer_row(section: Any, top: bool) -> list[Any]:
    bars = [b for b in section.bars if (b.y > 0) == top and b.y != 0]
    if not bars:
        return []
    edge = max(abs(b.y) + b.dia / 2 for b in bars)
    return sorted((b for b in bars if edge - abs(b.y) - b.dia / 2 <= _ROW), key=lambda b: b.x)


def face_spacing(section: Any, top: bool) -> FaceSpacing | None:
    """The spacing of the outer row of bars at the top (``top``) or bottom face of a
    rectangular section (:class:`saengine.design.rc.RcSection`); None without bars there."""
    row = _outer_row(section, top)
    if not row:
        return None
    h = section.depth
    cc = min(h / 2 - abs(b.y) - b.dia / 2 for b in row)
    if len(row) == 1:
        return FaceSpacing(float(section.width), float(cc), 1)
    gaps = [q.x - p.x for p, q in itertools.pairwise(row)]
    return FaceSpacing(float(max(gaps)), float(cc), len(row))


def _check(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check as check

    return check(*args, **kwargs)


def crack_checks(section: Any, fy: float, faces: dict[str, bool]) -> list[dict[str, Any]]:
    """Crack-control spacing of the outer bars of the faces in tension (``faces``: "bottom",
    "top" -> whether the face is in tension under some combination)."""
    rule = getattr(_detailing(), "crackControl", None)
    if rule is None:
        return []
    fs = service_stress(fy)
    rows = []
    for face, tension in faces.items():
        if not tension:
            continue
        found = face_spacing(section, face == "top")
        if found is None:
            continue
        limit = crack_spacing_limit(fs, found.cc)
        if limit is None:
            continue
        what = (
            "one bar: s is the face width"
            if found.count == 1
            else f"{found.count} bars, largest spacing"
        )
        rows.append(
            _check(
                f"Crack control, {face} bars",
                found.spacing,
                max(limit, 0.0),
                "mm",
                None,
                f"s <= {rule.coefficient:g} ({rule.reference:g}/fs) - {rule.coverFactor:g} cc and "
                f"<= {rule.cap:g} ({rule.reference:g}/fs), fs = {rule.serviceStressShare:.3g} fy = "
                f"{fs:.0f} MPa, cc = {found.cc:.0f} mm; {what} ({clause('detailing', 'crackControl')})",
            )
        )
    return rows


def skin_check(section: Any, faces: dict[str, bool]) -> dict[str, Any] | None:
    """Side (skin) bars of a beam deeper than the pack's limit: on both side faces over the
    pack's share of h from each tension face, spaced as the crack control with cc to the side
    face. None for a shallower beam."""
    rule = getattr(_detailing(), "skin", None)
    crack = getattr(_detailing(), "crackControl", None)
    h, b = float(section.depth), float(section.width)
    if rule is None or crack is None or h <= rule.depthOver:
        return None
    fs = service_stress(section.fy)
    top_row, bottom_row = _outer_row(section, True), _outer_row(section, False)
    y_top = max((bar.y for bar in top_row), default=h / 2)
    y_bottom = min((bar.y for bar in bottom_row), default=-h / 2)
    edge_x = max((abs(bar.x) for bar in section.bars), default=b / 2)
    side = [bar for bar in section.bars if abs(abs(bar.x) - edge_x) <= _ROW + bar.dia]
    cc = min((b / 2 - abs(bar.x) - bar.dia / 2 for bar in side), default=0.0)
    limit = crack_spacing_limit(fs, cc) or 0.0
    reach = rule.extentShare * h
    worst = 0.0
    for sx in (-1, 1):
        ys = sorted(bar.y for bar in side if (bar.x > 0) == (sx > 0))
        ys = sorted({y_bottom, y_top, *ys})
        for y0, y1 in itertools.pairwise(ys):
            # Only the gaps within the zone from a tension face.
            in_zone = (faces.get("bottom") and y0 < -h / 2 + reach) or (
                faces.get("top") and y1 > h / 2 - reach
            )
            if in_zone:
                worst = max(worst, y1 - y0)
    count = sum(1 for bar in side if y_bottom + _ROW < bar.y < y_top - _ROW)
    return _check(
        "Skin reinforcement",
        worst,
        max(limit, 0.0),
        "mm",
        None,
        f"h = {h:.0f} mm > {rule.depthOver:g} mm: side bars on both faces over "
        f"{rule.extentShare:g} h = {reach:.0f} mm from the tension face, spaced as "
        f"{clause('detailing', 'crackControl')} with cc = {cc:.0f} mm to the side; "
        + (f"{count} side bars" if count else "no side bars")
        + f" ({clause('detailing', 'skin')})",
    )


def effective_flange(span: float, bw: float, hf: float, sides: int) -> float | None:
    """Effective T-beam flange width [mm] of a beam ``bw`` wide with a slab ``hf`` thick on
    ``sides`` sides over ``span`` [mm] (half the clear distance to the next web is not
    known); None without a slab or a rule."""
    rule = getattr(_detailing(), "flangeTension", None)
    if rule is None or sides <= 0 or hf <= 0 or span <= 0:
        return None
    if sides >= 2:
        return min(rule.bothSidesSpan * span, bw + 2 * rule.bothSidesThickness * hf)
    return bw + min(rule.oneSideSpan * span, rule.oneSideThickness * hf)


def flange_note(span: float, bw: float, hf: float, sides: int) -> str | None:
    """What a T-beam's hogging (flange in tension) steel needs: spread over the smaller of the
    effective flange width and the pack's share of the span; some bars in the outer flange
    when the flange is wider. None without a flange."""
    rule = getattr(_detailing(), "flangeTension", None)
    bf = effective_flange(span, bw, hf, sides)
    if rule is None or bf is None:
        return None
    width = min(bf, rule.spanShare * span)
    text = (
        f"flange in tension: spread part of the top bars over {width:.0f} mm (the smaller of "
        f"the effective flange {bf:.0f} mm and {rule.spanShare:g} × span {span:.0f} mm)"
    )
    if bf > rule.spanShare * span:
        text += "; add some longitudinal bars in the outer flange"
    return text + f" ({clause('detailing', 'flangeTension')})"


def integrity_check(section: Any, perimeter: bool) -> list[dict[str, Any]]:
    """Structural integrity of a cast-in-place beam: at least the pack's ``minBars``
    continuous bottom bars, and top bars too for a perimeter beam. A beam type's bars run its
    whole length, so the shares of the support and midspan steel are continuous by
    construction; the splice positions are a drawing note."""
    rule = getattr(_detailing(), "integrity", None)
    if rule is None:
        return []
    rows = []
    faces = (("bottom", False), ("top", True)) if perimeter else (("bottom", False),)
    for face, top in faces:
        count = sum(1 for bar in section.bars if (bar.y > 0) == top and bar.y != 0)
        share = (
            (rule.perimeterTopShare if top else rule.perimeterBottomShare)
            if perimeter
            else rule.otherBottomShare
        )
        key = "integrityPerimeter" if perimeter else "integrityOther"
        rows.append(
            _check(
                f"Integrity, continuous {face} bars",
                float(rule.minBars),
                float(count),
                "bars",
                None,
                ("perimeter beam" if perimeter else "beam")
                + f": at least {share:.3g} of the {'support (negative)' if top else 'midspan (positive)'} "
                f"steel and {rule.minBars} bars continuous; the type's {count} {face} bars run the "
                "whole length"
                + (
                    "; Class B splices: top bars at midspan, bottom bars at or near the supports"
                    if perimeter
                    else "; spliced over the supports with a Class B splice, or anchored at "
                    "non-continuous supports by a standard hook"
                )
                + f" ({clause('detailing', key)})",
            )
        )
    return rows


def beam_checks(
    section: Any,
    checks: list[dict[str, Any]],
    *,
    perimeter: bool = False,
    span: float | None = None,
    flange: tuple[float, int] | None = None,
) -> list[dict[str, Any]]:
    """The detailing checks of a rectangular RC beam with ``section``, whose strength
    ``checks`` (:func:`saengine.design.check._beam_checks`) say which faces are in tension:
    crack control, skin steel, structural integrity and the flange note on the top bars.
    ``span``: the beam's length [mm]; ``flange``: (slab thickness, sides) beside it."""
    faces = {
        "bottom": any(c["name"].startswith("Flexure, sagging") and c["demand"] > 0 for c in checks),
        "top": any(c["name"].startswith("Flexure, hogging") and c["demand"] > 0 for c in checks),
    }
    rows = crack_checks(section, section.fy, faces)
    skin = skin_check(section, faces)
    if skin is not None:
        rows.append(skin)
    if faces["top"] and span and flange is not None:
        note = flange_note(span, float(section.width), flange[0], flange[1])
        for row in rows if note is not None else []:
            if row["name"] == "Crack control, top bars":
                row["note"] += f"; {note}"
    from saengine.design import limit_state_members

    if limit_state_members.tie_rules() is not None:
        # Alpha 9 C5c: the pack's tying systems in place of the integrity bars.
        rows += limit_state_members.tie_rows(section, perimeter, span)
    else:
        rows += integrity_check(section, perimeter)
    return rows


# ───────────────────────────────────────── shear friction ─────────────────────────────────────────


@dataclass
class ShearFrictionResult:
    """Shear transfer across a plane [N]."""

    phi_vn: float
    vn: float
    limit: float
    mu: float
    phi: float
    note: str
    #: Alpha 9 C5c: the cohesion term c fctd Ac [N] of the pack's interface shear (0 under the
    #: parent's shear friction) and the bar stress used [MPa] (None: min(fy, fyMax)).
    cohesion: float = 0.0
    fy_used: float | None = None


def _interface_shear(
    avf: float, fy: float, fc: float, area: float, surface: str, tension: float,
    compression: float,
) -> ShearFrictionResult | None:  # fmt: skip
    """Alpha 9 C5c: shear at the interface by the pack's ``interfaceShear`` method (EN 1992-1-1
    6.2.5 type): VRdi = c fctd Ai + μ (σn Ai + As fyd) <= limitShare ν fcd Ai, c = 0 under net
    tension, the bars at right angles to the joint; None when the pack does not pick it."""
    from saengine.design import design_strength, method_selection, strut_shear

    if not method_selection.uses("interfaceShear", "interfaceShear"):
        return None
    r = code_context.table("concreteMethods").interfaceShear
    name = r.surfaceMap.get(surface, surface)
    if name not in r.surfaces:
        return None
    c, mu = r.surfaces[name]
    fctd = design_strength.fctd(fc)
    fyd = design_strength.fyd(fy)
    net = compression - tension
    cohesion = c * fctd * area if net >= 0 else 0.0
    vrdi = cohesion + mu * max(avf * fyd + net, 0.0)
    nu = strut_shear.nu1(fc, strut_shear.rules())
    limit = r.limitShare * nu * design_strength.fcd(fc) * area
    note = (
        f"VRdi = c fctd Ai + μ (σn Ai + As fyd), c = {c:g}, μ = {mu:g} ({name}), fctd = "
        f"{fctd:.2f} MPa, As = {avf:.0f} mm², fyd = {fyd:.0f} MPa; at most {r.limitShare:g} ν "
        f"fcd Ai = {limit / 1e3:.0f} kN ({code_context.cite('concreteMethods', 'interfaceShear')})"
    )
    if tension > 0:
        note += f"; net tension {tension / 1e3:.0f} kN taken off, c = 0"
    return ShearFrictionResult(min(vrdi, limit), vrdi, limit, mu, 1.0, note, cohesion, fyd)


def shear_friction(
    avf: float,
    fy: float,
    fc: float,
    area: float,
    surface: str = "roughened",
    tension: float = 0.0,
    compression: float = 0.0,
    aggregate: str | None = None,
    phi: float | None = None,
) -> ShearFrictionResult | None:
    """φVn of shear friction across a plane of concrete ``area`` [mm²] with ``avf`` [mm²] of
    bars at right angles to it: Vn = μ (Avf fy + permanent compression - net tension), μ =
    the pack's ``mu[surface]`` λ, fy at most ``fyMax``, Vn at most the pack's limits on Ac.
    None when the pack has no shear-friction rules."""
    rule = getattr(_detailing(), "shearFriction", None)
    found = _interface_shear(avf, fy, fc, area, surface, tension, compression)  # Alpha 9 C5c
    if found is not None:
        return found
    if rule is None or surface not in rule.mu:
        return None
    if phi is None:
        phi = float(code_context.table("factors").phi["shear"])
    lam = lambda_factor(aggregate)
    mu = rule.mu[surface] * lam
    fy_used = min(fy, rule.fyMax)
    force = max(avf * fy_used + compression - tension, 0.0)
    vn = mu * force
    if surface in rule.roughSurfaces and lam >= 1.0:
        a, b, c, d = rule.roughLimits
        stress = min(a * fc, b + c * fc, d)
        limit_text = f"min({a:g} f'c, {b:g} + {c:g} f'c, {d:g}) Ac"
    else:
        a, b = rule.otherLimits
        stress = min(a * fc, b)
        limit_text = f"min({a:g} f'c, {b:g}) Ac"
    limit = stress * area
    note = (
        f"Vn = μ (Avf fy{' + Nc' if compression else ''}{' - Nt' if tension else ''}), μ = "
        f"{rule.mu[surface]:g} λ = {mu:.2f} ({surface}), Avf = {avf:.0f} mm², fy = "
        f"{fy_used:g} MPa; Vn <= {limit_text} = {limit / 1e3:.0f} kN, φ = {phi:g} "
        f"({clause('detailing', 'shearFriction')})"
    )
    if tension > 0:
        note += f"; net tension {tension / 1e3:.0f} kN taken off"
    return ShearFrictionResult(phi * min(vn, limit), vn, limit, mu, phi, note)


def column_joint_check(section: Any, points: Any, fy: float) -> dict[str, Any] | None:
    """Shear friction across the construction joint of a column at the floor (concrete cast
    against hardened, roughened concrete), all its longitudinal bars crossing it, the
    resultant shear of every point (``points``: :class:`saengine.design.column_shear.
    ShearPoints`) with its net axial tension taken off; permanent compression is not counted
    (on the safe side)."""
    rule = getattr(_detailing(), "shearFriction", None)
    if rule is None or len(points.pu) == 0:
        return None
    avf = float(sum(bar.area for bar in section.bars))
    vu = np.hypot(points.vx, points.vy)
    tension = np.maximum(-points.pu, 0.0)
    base = shear_friction(avf, fy, section.fc, section.gross_area, "roughened")
    if base is None:
        return None
    mu, phi = base.mu, base.phi
    fy_used = base.fy_used if base.fy_used is not None else min(fy, rule.fyMax)
    # Alpha 9 C5c: the pack's interface shear adds c fctd Ac where there is no net tension.
    cohesion = np.where(tension > 0, 0.0, base.cohesion)
    capacity = phi * np.minimum(
        cohesion + mu * np.maximum(avf * fy_used - tension, 0.0), base.limit
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(capacity > 0, vu / capacity, np.where(vu > 0, np.inf, 0.0))
    i = int(np.argmax(ratio))
    combination, where = points.label(i)
    note = base.note
    if tension[i] > 0:
        note += f"; net tension {tension[i] / 1e3:.0f} kN taken off"
    return _check(
        "Construction joint (shear friction)",
        float(vu[i]) / 1e3,
        float(capacity[i]) / 1e3,
        "kN",
        combination,
        f"{note}; all longitudinal bars, roughened to about {rule.roughness:g} mm; {where}",
        utilisation=float(ratio[i]),
    )


def wall_joint_check(
    name: str,
    force: float,
    wall_type: Any,
    length: float,
    fc: float,
    fy: float,
    combination: str | None,
    end_bars: tuple[int, float, float] | None = None,
) -> dict[str, Any] | None:
    """Shear friction of a floor-to-wall connection: ``force`` [N] along a wall ``length``
    [mm] long across its horizontal construction joint at the floor, the wall's vertical bars
    crossing it. ``end_bars``: (count per end, diameter, length per end [mm]) of end bars that
    cross the joint too, in place of the web over those lengths. None when the wall type has
    no vertical bars or the pack has no rule."""
    reinforcement = getattr(wall_type, "reinforcement", None)
    vertical = getattr(reinforcement, "vertical", None)
    if vertical is None or length <= 0:
        return None
    rule = getattr(_detailing(), "shearFriction", None)
    per_metre = int(reinforcement.layers) * math.pi * vertical.dia**2 / 4 * 1000 / vertical.spacing
    avf = per_metre * length / 1000
    ends = ""
    if end_bars is not None and 0 < 2 * end_bars[2] < length:
        count, dia, zone = end_bars
        avf = per_metre * (length - 2 * zone) / 1000 + 2 * count * math.pi * dia**2 / 4
        ends = f" and {count} Ø{dia:g} per end over {zone:g} mm"
    area = float(wall_type.thickness) * length
    found = shear_friction(avf, fy, fc, area, "roughened")
    if found is None or rule is None:
        return None
    return _check(
        name,
        force / 1e3,
        found.phi_vn / 1e3,
        "kN",
        combination,
        f"{found.note}; the wall's vertical bars {reinforcement.layers} × Ø{vertical.dia:g} @ "
        f"{vertical.spacing:g}{ends} over {length / 1e3:.2f} m, roughened to about "
        f"{rule.roughness:g} mm",
    )


# ──────────────────────────────────── crossing top bars ────────────────────────────────────

#: Two beams within this angle of each other are one direction at a joint [degrees].
_SAME_DIRECTION = 10.0


def _face_dia(beam_type: Any, face: str = "top") -> float:
    """The largest ``face`` ("top" / "bottom") bar of a beam type [mm]; 0 without such bars."""
    reinforcement = getattr(beam_type, "reinforcement", None)
    groups = getattr(reinforcement, "longitudinal", None) or []
    return max((float(g.dia) for g in groups if g.position == face), default=0.0)


def _top_dia(beam_type: Any) -> float:
    """The largest top bar of a beam type [mm]; 0 without top bars."""
    return _face_dia(beam_type, "top")


def _bottom_level(beam_type: Any) -> float:
    """How far under the beam's top its outer bottom bars' centre is [mm] (the beams of a joint
    have their tops at its level): depth - cover - stirrup - half the largest bottom bar."""
    reinforcement = getattr(beam_type, "reinforcement", None)
    transverse = getattr(reinforcement, "transverse", None)
    cover = float(getattr(reinforcement, "cover", 0.0) or 0.0)
    tdia = float(getattr(transverse, "dia", 0.0) or 0.0) if transverse is not None else 0.0
    return _depth(beam_type) - cover - tdia - _face_dia(beam_type, "bottom") / 2


def _depth(beam_type: Any) -> float:
    return float(getattr(getattr(beam_type, "profile", None), "yDim", 0.0) or 0.0)


def _plan_axis(direction: Sequence[float]) -> str:
    return "x" if abs(direction[0]) >= abs(direction[1]) else "y"


def main_direction(joints: Sequence[Any]) -> str:
    """The plan direction ("x" or "y") whose beams have the longer mean span (centre to centre
    of the joints, so the larger hogging moments) over ``joints``
    (:func:`saengine.design.ductile_joints.frame_joints`); "x" on a tie."""
    spans: dict[str, list[float]] = {"x": [], "y": []}
    for joint in joints:
        for beam in joint.beams:
            spans[_plan_axis(beam.direction)].append(float(beam.length))
    mean = {k: sum(v) / len(v) if v else 0.0 for k, v in spans.items()}
    return "y" if mean["y"] > mean["x"] + 1e-6 else "x"


def joint_top_layers(
    joints: Sequence[Any], types: dict[str, Any], mode: str = "auto"
) -> dict[str, dict[str, float]]:
    """T33: the top bars of beams from two directions cannot share the outer layer where they
    cross at a joint. ``{joint id: {beam id: drop [mm]}}`` of the beams whose top bars go in
    the second layer, under the main direction's: ``drop`` is the main bars' largest diameter
    (crossing bars touch; their clear spacing is not a parallel-layer rule), summed over the
    directions above when more than two cross.

    ``mode`` (Project Settings > Construction > Crossing beam bars at joints, SAEngine practice):
    "auto" takes the deeper beam as the main one (its hogging d is the larger and it usually
    carries the larger hogging moment), beams of equal depth the plan direction of
    :func:`main_direction` (the longer spans), the same everywhere so a continuous beam stays
    in one layer; "x" / "y" that plan direction; "sameLayer" none (the drawings flag the
    clash). ``joints``: :func:`saengine.design.ductile_joints.frame_joints`."""
    return _joint_layers(joints, types, mode, "top")


def joint_bottom_layers(
    joints: Sequence[Any], types: dict[str, Any], mode: str = "auto"
) -> dict[str, dict[str, float]]:
    """The mirror of :func:`joint_top_layers` for the bottom bars (owner decision 2026-11-11,
    SAEngine practice): where the bottom bars of beams from two directions meet at a joint at
    the same level, the secondary direction's pass one main bar diameter higher (summed over
    the directions below when more than two meet). ``{joint id: {beam id: rise [mm]}}``. The
    main direction is chosen as for the top bars, with the same ``mode``, so a secondary
    beam's bars sit inside the main beam's at both faces. A direction whose outer bottom bars
    are already clear of the main direction's (a shallower beam, its bottom bars at least
    half the two diameters higher) is not raised."""
    return _joint_layers(joints, types, mode, "bottom")


def _joint_layers(
    joints: Sequence[Any], types: dict[str, Any], mode: str, face: str
) -> dict[str, dict[str, float]]:
    """:func:`joint_top_layers` (``face`` "top": the drops) and :func:`joint_bottom_layers`
    ("bottom": the rises)."""
    if mode == "sameLayer":
        return {}
    preferred = mode if mode in ("x", "y") else main_direction(joints)
    limit = math.cos(math.radians(_SAME_DIRECTION))
    out: dict[str, dict[str, float]] = {}
    for joint in joints:
        groups: list[tuple[tuple[float, float], list[Any]]] = []
        for beam in joint.beams:
            if _face_dia(types.get(beam.type), face) <= 0:
                continue
            u = beam.direction
            for axis, members in groups:
                if abs(axis[0] * u[0] + axis[1] * u[1]) >= limit:
                    members.append(beam)
                    break
            else:
                groups.append((u, [beam]))
        if len(groups) < 2:
            continue

        def rank(group: tuple[tuple[float, float], list[Any]]) -> tuple[int, int]:
            axis, members = group
            depth = max(_depth(types.get(b.type)) for b in members)
            # depths to the mm: equal ones take the preferred direction first
            first = 0 if _plan_axis(axis) == preferred else 1
            return (-round(depth) if mode == "auto" else 0, first)

        ordered = sorted(groups, key=rank)
        main = ordered[0][1]
        main_level = max(_bottom_level(types.get(b.type)) for b in main)
        main_dia = max(_face_dia(types.get(b.type), face) for b in main)
        shift = 0.0
        found: dict[str, float] = {}
        for k, (_axis, members) in enumerate(ordered):
            dia = max(_face_dia(types.get(b.type), face) for b in members)
            if k and face == "bottom":
                # bottom bars meet only where the beams' bottoms are at about one level
                level = max(_bottom_level(types.get(b.type)) for b in members)
                if main_level - level >= (main_dia + dia) / 2 - 1e-6:
                    continue
            if shift > 0:
                for beam in members:
                    found[beam.id] = max(found.get(beam.id, 0.0), shift)
            shift += dia
        if found:
            out[joint.id] = found
    return out


def beam_top_drops(layers: dict[str, dict[str, float]]) -> dict[str, float]:
    """``{beam id: drop [mm]}``: the largest drop of each beam's top bars over its joints
    (:func:`joint_top_layers`); its hogging design takes it all along (the top bars of a beam
    type run its length). The same for the rises of :func:`joint_bottom_layers`: the bottom
    bars run the beam's length too, and its sagging design takes the rise all along."""
    out: dict[str, float] = {}
    for found in layers.values():
        for beam_id, drop in found.items():
            out[beam_id] = max(out.get(beam_id, 0.0), drop)
    return out


def building_top_drops(building: Any, types: dict[str, Any], settings: Any) -> dict[str, float]:
    """:func:`beam_top_drops` of a building model's joints with the project's mode
    (``construction.jointBars``, "auto" when not set)."""
    from saengine.design.ductile_joints import frame_joints

    joints = frame_joints(building, types)
    return beam_top_drops(joint_top_layers(joints, types, joint_mode(settings)))


def joint_mode(settings: Any) -> str:
    """The project's crossing-bars mode (``construction.jointBars``, "auto" when not set):
    it orders the top bars (:func:`joint_top_layers`) and the bottom bars
    (:func:`joint_bottom_layers`) alike."""
    construction = getattr(settings, "construction", None)
    return str(getattr(construction, "jointBars", None) or "auto")


def building_bottom_rises(building: Any, types: dict[str, Any], settings: Any) -> dict[str, float]:
    """``{beam id: rise [mm]}`` of a building model's beams whose bottom bars pass their joints
    one main bar diameter higher (:func:`joint_bottom_layers`, the project's mode)."""
    from saengine.design.ductile_joints import frame_joints

    joints = frame_joints(building, types)
    return beam_top_drops(joint_bottom_layers(joints, types, joint_mode(settings)))
