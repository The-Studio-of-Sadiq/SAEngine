"""The direct design method of two-way slab systems (method id ``directDesign`` of the code
pack's ``slabMethods``; BNBC 2020 Part 6 Sec 6.5.6).

Per frame (:class:`saengine.design.slab_frames.SlabFrame`) and span, under each gravity
combination:

- the total static moment Mo = qu l2 ln² / ``staticDivisor`` (ln face to face of the supports,
  at least ``minClearSpanShare`` l1; l2 the frame's width);
- shared to the negative moments at the support faces and the positive moment: an interior span
  ``interiorNegative`` / ``interiorPositive``, an end span by the edge condition (``endSpan``:
  the exterior edge fully restrained by a wall, beams between all supports, no beams with or
  without an edge beam);
- each moment shared to the column strip by the pack's tables in l2/l1, αf1 l2/l1 and (exterior
  negative) βt = Ecb C / (2 Ecs Is), linear between the rows; a support that is a wall at least
  ``uniformSupportShare`` l2 long spreads its negative moment uniformly across l2; a beam along
  the span takes ``beamShare`` of the column strip moment at αf1 l2/l1 >= ``alphaLimit`` (linear
  to zero); the middle strips the rest;
- the moments the columns resist: at an interior support Msc = ``columnMomentFactor``
  [(qDu + ``columnMomentLiveShare`` qLu) l2 ln² - q'Du l'2 l'n²] (the primes of the shorter
  span); at an exterior column ``edgeTransferShare`` Mo.

The 10 % modification of the moments the method permits is not used (conservative).

Units: mm, N, MPa; N·mm.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.design.slab_frames import FrameResult, Loads, SlabFrame, StripMoment, clause


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    return float(np.interp(x, list(xs), list(ys)))


def torsion_constant(parts: Sequence[tuple[float, float]], shape: float) -> float:
    """C = Σ (1 - shape x/y) x³ y / 3 [mm⁴] of rectangles (x <= y) (BNBC Eq 6.6.86)."""
    total = 0.0
    for a, b in parts:
        x, y = min(a, b), max(a, b)
        if x > 0:
            total += (1 - shape * x / y) * x**3 * y / 3
    return total


def torsional_parts(
    c1: float, h: float, beam: tuple[float, float] | None, shape: float
) -> list[tuple[float, float]]:
    """The rectangles of the torsional member at a support: the slab ``c1`` wide (h deep), or
    the transverse beam (width, total depth) with the slab beside it as far as its projection
    below the slab and at most 4h, whichever gives the larger C (split into the stem through
    the slab and the flanges)."""
    plain = [(c1, h)]
    if beam is None:
        return plain
    width, depth = beam
    stem = max(depth - h, 0.0)
    flange = min(stem, 4 * h)
    one = [(width, depth), (flange, h), (flange, h)]
    two = [(width + 2 * flange, h), (width, stem)]
    return max((plain, one, two), key=lambda p: torsion_constant(p, shape))


def beta_t(frame: SlabFrame, support: int, shape: float) -> float:
    """βt = Ecb C / (2 Ecs Is) at a support, Is = l2 h³ / 12 (BNBC Eq 6.6.85); 0 without a
    transverse (edge) beam."""
    s = frame.supports[support]
    if s.transverse_beam is None:
        return 0.0
    c = torsion_constant(torsional_parts(s.c1, frame.h, s.transverse_beam, shape), shape)
    return c / (2 * frame.l2 * frame.h**3 / 12)


def limitations(frames: Sequence[SlabFrame], loads: Loads, rules: Any) -> list[str]:
    """The limits of the method the frames do not meet ([] when they all do)."""
    problems: list[str] = []
    for frame in frames:
        spans = frame.spans
        if len(spans) < int(rules.minSpans):
            problems.append(
                f"{frame.name}: {len(spans)} continuous span(s), fewer than {rules.minSpans}"
            )
            continue
        for k, l1 in enumerate(spans):
            for l2 in frame.panels():
                if max(l1, l2) / min(l1, l2) > float(rules.maxPanelRatio) + 1e-9:
                    problems.append(
                        f"{frame.name}: panel {l1:.0f} x {l2:.0f} mm, more than "
                        f"{rules.maxPanelRatio:g} : 1"
                    )
            if k + 1 < len(spans):
                longer = max(l1, spans[k + 1])
                if abs(l1 - spans[k + 1]) > float(rules.maxSpanDifference) * longer + 1e-6:
                    problems.append(
                        f"{frame.name}: successive spans {l1:.0f} and {spans[k + 1]:.0f} mm "
                        f"differ by more than {rules.maxSpanDifference:.3g} of the longer"
                    )
    if loads.dead > 0 and loads.live > float(rules.maxLiveToDead) * loads.dead + 1e-12:
        problems.append(
            f"live load {loads.live * 1e3:.2f} kN/m² more than {rules.maxLiveToDead:g} x the "
            f"dead load {loads.dead * 1e3:.2f} kN/m²"
        )
    # Eq 6.6.82 for panels with beams on all sides: the beams of the two directions.
    alphas = {d: [a for f in frames if f.direction == d for a in f.alpha] for d in ("X", "Y")}
    if all(alphas.values()) and all(min(v) > 0 for v in alphas.values()):
        lo, hi = rules.stiffnessRatioRange
        for frame in frames:
            other = "Y" if frame.direction == "X" else "X"
            a2 = float(np.mean(alphas[other]))
            for k, l1 in enumerate(frame.spans):
                l2 = frame.l2
                ratio = frame.alpha[k] * l2**2 / (a2 * l1**2)
                if not lo <= ratio <= hi:
                    problems.append(
                        f"{frame.name}: αf1 l2² / αf2 l1² = {ratio:.2f} outside {lo:g}-{hi:g}"
                    )
    return problems


def end_condition(frame: SlabFrame, exterior: int) -> str:
    """The column of the end span table for the exterior support ``exterior`` (0 or last)."""
    support = frame.supports[exterior]
    if support.kind == "wall":
        return "restrained"
    if frame.alpha and all(a > 0 for a in frame.alpha):
        return "beamsAll"
    if support.transverse_beam is not None:
        return "noBeamsEdgeBeam"
    return "noBeams"


def span_shares(frame: SlabFrame, k: int, rules: Any) -> tuple[float, float, float, str]:
    """(negative at the start support, positive, negative at the end support) as shares of Mo,
    and what they are."""
    last = len(frame.spans) - 1
    start_exterior, end_exterior = k == 0, k == last
    if not start_exterior and not end_exterior:
        return (
            float(rules.interiorNegative),
            float(rules.interiorPositive),
            float(rules.interiorNegative),
            "interior span",
        )
    table = rules.endSpan
    exterior = 0 if start_exterior else len(frame.supports) - 1
    condition = end_condition(frame, exterior)
    i = list(table.conditions).index(condition)
    ext, pos, inner = (
        float(table.exteriorNegative[i]),
        float(table.positive[i]),
        float(table.interiorNegative[i]),
    )
    what = f"end span ({condition})"
    return (ext, pos, inner, what) if start_exterior else (inner, pos, ext, what)


def column_strip_share(
    frame: SlabFrame, k: int, where: str, support: int | None, rules: Any
) -> tuple[float, str]:
    """Share (0-1) of a moment the column strip takes: ``where`` "interior", "exterior" (at
    ``support``) or "positive"."""
    l1 = frame.spans[k]
    ratio = max(frame.panels(), default=frame.l2) / l1
    alpha_l = frame.alpha[k] * frame.l2 / l1 if frame.alpha else 0.0
    t = min(max(alpha_l / float(rules.alphaLimit), 0.0), 1.0)
    if support is not None:
        s = frame.supports[support]
        if s.kind == "wall" and s.wall_length >= float(rules.uniformSupportShare) * frame.l2:
            cs, _ = frame.column_strip(k)
            return cs / frame.l2, "a wall across: uniform over l2"
    if where == "exterior":
        table = rules.exteriorStrip
        bt = beta_t(frame, support if support is not None else 0, float(rules.torsionShape))
        u = min(bt / float(table.betaLimit), 1.0)
        zero = (1 - u) * _interp(ratio, table.ratios, table.alphaZeroBetaZero) + u * _interp(
            ratio, table.ratios, table.alphaZeroBetaFull
        )
        full = (1 - u) * _interp(ratio, table.ratios, table.alphaFullBetaZero) + u * _interp(
            ratio, table.ratios, table.alphaFullBetaFull
        )
        return ((1 - t) * zero + t * full) / 100, f"βt = {bt:.2f}"
    table = rules.interiorStrip if where == "interior" else rules.positiveStrip
    zero = _interp(ratio, table.ratios, table.alphaZero)
    full = _interp(ratio, table.ratios, table.alphaFull)
    return ((1 - t) * zero + t * full) / 100, f"l2/l1 = {ratio:.2f}, αf1 l2/l1 = {alpha_l:.2f}"


def distribute(
    frame: SlabFrame,
    k: int,
    where: str,
    moment: float,
    combination: str | None,
    rules: Any,
    support: int | None = None,
    note: str = "",
) -> list[StripMoment]:
    """A frame moment [N·mm] at a section of span ``k`` shared to the column strip (and its
    beam) and the middle strips. ``where``: "interior", "exterior" (negative, at ``support``)
    or "positive"."""
    share, why = column_strip_share(frame, k, where, support, rules)
    cs_width, ms_width = frame.column_strip(k)
    l1 = frame.spans[k]
    alpha_l = frame.alpha[k] * frame.l2 / l1 if frame.alpha else 0.0
    beam = float(rules.beamShare) * min(max(alpha_l / float(rules.alphaLimit), 0.0), 1.0)
    label = "positive" if where == "positive" else f"negative at support {support}"
    column = share * moment
    detail = f"column strip {share:.0%} ({why})" + (f"; {note}" if note else "")
    out = [
        StripMoment(
            k,
            label,
            "column",
            column * (1 - beam),
            cs_width,
            combination,
            detail + (f", beam {beam:.0%} of it" if beam else ""),
        ),
        StripMoment(k, label, "middle", moment - column, ms_width, combination, detail),
    ]
    if beam:
        out.append(StripMoment(k, label, "beam", column * beam, 0.0, combination, detail))
    return out


def design_frame(frame: SlabFrame, loads: Loads, rules: Any) -> FrameResult:
    """The strip moments of a frame by the direct design method (the module notes)."""
    result = FrameResult("directDesign", frame)
    l2 = frame.l2
    spans = frame.spans
    for name, qd, ql in loads.factored():
        qu = qd + ql
        for k, l1 in enumerate(spans):
            ln = max(frame.clear(k), float(rules.minClearSpanShare) * l1)
            mo = qu * l2 * ln**2 / float(rules.staticDivisor)
            start, positive, end, what = span_shares(frame, k, rules)
            note = f"Mo = qu l2 ln² / {rules.staticDivisor:g} = {mo / 1e6:.1f} kN·m, {what}"
            last = len(spans) - 1
            result.moments += distribute(
                frame, k, "exterior" if k == 0 else "interior", start * mo, name, rules, k, note
            )
            result.moments += distribute(
                frame, k, "positive", positive * mo, name, rules, None, note
            )
            result.moments += distribute(
                frame,
                k,
                "exterior" if k == last else "interior",
                end * mo,
                name,
                rules,
                k + 1,
                note,
            )
            for support in (k, k + 1):
                if support not in (0, len(frame.supports) - 1):
                    continue
                if frame.supports[support].kind != "column":
                    continue
                transfer = float(rules.edgeTransferShare) * mo
                _keep(
                    result,
                    support,
                    transfer,
                    name,
                    f"{rules.edgeTransferShare:g} Mo ({clause('edgeTransfer')})",
                )
        # Interior columns: Eq 6.6.87 between the two spans framing in.
        for support in range(1, len(frame.supports) - 1):
            if frame.supports[support].kind != "column":
                continue
            a, b = support - 1, support
            ln_a = max(frame.clear(a), float(rules.minClearSpanShare) * spans[a])
            ln_b = max(frame.clear(b), float(rules.minClearSpanShare) * spans[b])
            (long_ln, short_ln) = (ln_a, ln_b) if ln_a >= ln_b else (ln_b, ln_a)
            share = float(rules.columnMomentLiveShare)
            msc = float(rules.columnMomentFactor) * (
                (qd + share * ql) * l2 * long_ln**2 - qd * l2 * short_ln**2
            )
            _keep(result, support, msc, name, f"Eq ({clause('columnMoment')})")
    return result


def _keep(result: FrameResult, support: int, value: float, name: str, note: str) -> None:
    old = result.column_moments.get(support)
    if old is None or abs(value) > abs(old[0]):
        result.column_moments[support] = (value, name, note)
