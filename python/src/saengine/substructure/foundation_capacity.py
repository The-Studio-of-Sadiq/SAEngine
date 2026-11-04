"""Capacity design of foundations (method ``overstrengthFactor`` of the pack's
``seismic.foundationCapacity``; alpha 9 C5c, EN 1998-1 4.4.2.6 type).

The foundations' strength combinations with earthquake take EFd = EF,G + γRd Ω EF,E: the
earthquake cases' factors × γRd Ω, γRd by the behaviour factor q (``gammaLow`` up to
``qLimit``, ``gammaHigh`` above), Ω the pack's (or the project's override) and, without one, q
(the action effects of the elastic response, which the rule need not exceed: SAEngine practice,
on the safe side); γRd Ω at most q. A pack without the rule (the default) leaves the
combinations as they are.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

#: The earthquake load cases of the analysis whose factors are scaled.
EARTHQUAKE = ("EX", "EY", "EXP", "EXN", "EYP", "EYN", "RX", "RY", "EV")


def rules() -> Any | None:
    found = getattr(code_context.table("seismic"), "foundationCapacity", None)
    return found if found is not None and found.method == "overstrengthFactor" else None


def factor(settings: Any) -> tuple[float, str] | None:
    """(γRd Ω, how) of the project, None without the pack's rule."""
    from saengine.library.settings import derived

    r = rules()
    if r is None:
        return None
    q = float(derived(settings).get("R") or 1.0)
    gamma = r.gammaLow if q <= r.qLimit else r.gammaHigh
    omega = r.omega if r.omega is not None else q
    value = min(gamma * omega, q)
    how = (
        f"EFd = EF,G + γRd Ω EF,E, γRd = {gamma:g} (q = {q:g}), Ω = "
        + (f"{omega:g}" if r.omega is not None else "q (the elastic response, on the safe side)")
        + f", γRd Ω = {value:.3f} at most q"
    )
    clause = code_context.cite("seismic", "foundationCapacity")
    return value, how + (f" ({clause})" if clause else "")


def capacity_combinations(
    strength: list[tuple[str, dict[str, float]]], settings: Any
) -> tuple[list[tuple[str, dict[str, float]]], str | None]:
    """The strength combinations with their earthquake factors × γRd Ω, and the note; as they
    are without the rule."""
    found = factor(settings)
    if found is None:
        return strength, None
    value, how = found
    out = []
    for name, factors in strength:
        if any(factors.get(c) for c in EARTHQUAKE):
            scaled = {k: (v * value if k in EARTHQUAKE else v) for k, v in factors.items()}
            out.append((name, scaled))
        else:
            out.append((name, factors))
    return out, how
