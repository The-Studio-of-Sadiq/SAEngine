"""Torsion of beams by the cracking torque and its interaction with shear (method
``torsionInteraction`` of the pack's ``concreteMethods.torsion``; alpha 9 C18b, the form of
AS 3600:2018 8.3).

A rectangular beam b x D (the slab cast with it not counted: on the safe side), φ the pack's
shear φ:

- torsion modulus ``Jt = torsionModulus x² y`` (x the short side), the cracking torque
  ``Tuc = crackingCoefficient Jt √f'c``;
- torsion is neglected where ``T* < neglectShare φ Tuc``;
- web crushing: ``T* / (φ Tu.max) + V* / (φ Vu.max) <= crushingInteraction`` with
  ``Tu.max = maxCoefficient f'c Jt`` and Vu.max the pack's shear method's (the compression
  field method's ``vrMaxShare φc f'c bv dv``; without it the crushing row holds T* alone);
- no torsion reinforcement where ``T* / (φ Tuc) + V* / (φ Vuc) <= plainInteraction``, φVuc the
  beam's shear strength without links (the pack's shear method);
- else closed links: ``Tus = fsy.f (Asw / s) 2 At cot θv`` (Asw one leg, At = x1 y1 inside the
  centres of the corner bars, ut = 2 (x1 + y1)), the same links carrying the shear beyond the
  concrete: ``(V* - φVuc)+ / φVus + T* / φTus <= 1`` (SAEngine's linear sharing of the links,
  as the code adds the torsion links to the shear's); spacing at most
  ``min(share ut, mm)``; the longitudinal steel ``ΔAl = T* ut cot θv / (2 φ At fsy)`` reported
  (informative: added to the flexural steel by the engineer).

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

METHOD = "torsionInteraction"
#: Torsion below this [N·mm] (0.1 kN·m) is the analysis's noise (SAEngine practice).
TORSION_FLOOR = 1e5


def rules() -> Any | None:
    """The pack's ``concreteMethods.torsion`` when it is this method, or None."""
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen

    return chosen(pack.table("concreteMethods"), "torsion", METHOD)


def _cite() -> str:
    found = code_context.cite("concreteMethods", "torsion")
    return f" ({found})" if found else ""


def torsion_modulus(b: float, h: float, r: Any) -> float:
    """Jt [mm³] of a b x h rectangle."""
    x, y = min(b, h), max(b, h)
    return r.torsionModulus * x * x * y


def cracking_torque(b: float, h: float, fc: float, r: Any) -> float:
    """Tuc [N·mm]."""
    return r.crackingCoefficient * torsion_modulus(b, h, r) * math.sqrt(fc)


def link_torque(asw_s: float, fy: float, at: float, r: Any) -> float:
    """Tus [N·mm] of closed links Asw/s [mm²/mm per leg]."""
    return min(fy, r.fyMax) * asw_s * 2 * at * r.cotTheta


def _row(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check

    return _check(*args, **kwargs)


def torsion_rows(
    section: Any,
    cover: float,
    stirrups: tuple[float, int, float] | None,
    points: list[tuple[float, float, float, str, str]],
) -> list[dict[str, Any]]:
    """The torsion rows of a beam at its governing station. ``points``: (T* [N·mm], V* [N],
    M* [N·mm], combination, where) of the stations. [] without the method or torsion."""
    from saengine.design import compression_field_shear
    from saengine.design.rc import bar_area, shear

    r = rules()
    if r is None or not points or max(abs(p[0]) for p in points) < TORSION_FLOOR:
        return []
    phi = float(code_context.table("factors").phi.shear)
    b, h, fc = float(section.width), float(section.depth), float(section.fc)
    tdia = float(getattr(section, "transverse_dia", None) or (stirrups[0] if stirrups else 10.0))
    bar = max((float(x.dia) for x in section.bars), default=16.0)
    inset = 2 * (cover + tdia) + bar
    x1, y1 = b - inset, h - inset
    if x1 <= 0 or y1 <= 0:
        return [
            _row(f"Torsion{_cite()}", 0.0, 0.0, "kN·m", None, "not checked: no room", flag=True)
        ]
    at, ut = x1 * y1, 2 * (x1 + y1)
    tuc = cracking_torque(b, h, fc, r)
    tu_max = r.maxCoefficient * fc * torsion_modulus(b, h, r)
    plain = shear(section, None, 0, None)
    phi_vuc = float(plain.phi_vn)
    with_links = shear(section, *stirrups) if stirrups else plain
    phi_vus = max(float(with_links.phi_vn) - phi_vuc, 0.0)
    cf = compression_field_shear.rules()
    phi_vu_max = None
    if cf is not None:
        dv = compression_field_shear.shear_depth(float(with_links.d), h, cf)
        phi_vu_max = cf.vrMaxShare * cf.phiC * fc * b * dv
    asw_s = bar_area(stirrups[0]) / stirrups[2] if stirrups and stirrups[2] else 0.0
    phi_tus = phi * link_torque(asw_s, section.fy, at, r)

    def crushing(p: tuple[float, float, float, str, str]) -> float:
        out = abs(p[0]) / (phi * tu_max)
        if phi_vu_max:
            out += abs(p[1]) / phi_vu_max
        return out

    def plain_sum(p: tuple[float, float, float, str, str]) -> float:
        return abs(p[0]) / (phi * tuc) + (abs(p[1]) / phi_vuc if phi_vuc > 0 else math.inf)

    def links(p: tuple[float, float, float, str, str]) -> float:
        shear_part = max(abs(p[1]) - phi_vuc, 0.0)
        part = shear_part / phi_vus if phi_vus > 0 else (math.inf if shear_part else 0.0)
        return part + (abs(p[0]) / phi_tus if phi_tus > 0 else math.inf)

    worst_t = max(points, key=lambda p: abs(p[0]))
    rows: list[dict[str, Any]] = []
    terms = (
        f"Jt = {r.torsionModulus:g} x² y = {torsion_modulus(b, h, r) / 1e6:.1f}e6 mm³, Tuc = "
        f"{r.crackingCoefficient:g} Jt √f'c = {tuc / 1e6:.1f} kN·m, φ = {phi:g}"
    )
    if abs(worst_t[0]) < r.neglectShare * phi * tuc:
        rows.append(
            _row(
                f"Torsion below {r.neglectShare:g} φTuc{_cite()}",
                abs(worst_t[0]) / 1e6,
                r.neglectShare * phi * tuc / 1e6,
                "kN·m",
                worst_t[3],
                f"{terms}; at {worst_t[4]}: torsion neglected",
                flag=True,
            )
        )
        return rows
    worst_c = max(points, key=crushing)
    rows.append(
        _row(
            f"Torsion and shear: web crushing{_cite()}",
            crushing(worst_c),
            r.crushingInteraction,
            "",
            worst_c[3],
            f"T*/(φTu.max) + V*/(φVu.max), Tu.max = {r.maxCoefficient:g} f'c Jt = "
            f"{tu_max / 1e6:.1f} kN·m"
            + (
                f", φVu.max = {phi_vu_max / 1e3:.1f} kN"
                if phi_vu_max
                else " (the shear method gives no Vu.max: T* alone)"
            )
            + f"; T* = {abs(worst_c[0]) / 1e6:.1f} kN·m, V* = {abs(worst_c[1]) / 1e3:.1f} kN at "
            f"{worst_c[4]}",
            utilisation=crushing(worst_c) / r.crushingInteraction,
        )
    )
    needing = [p for p in points if plain_sum(p) > r.plainInteraction]
    if not needing:
        worst_p = max(points, key=plain_sum)
        rows.append(
            _row(
                f"Torsion: no torsion links needed{_cite()}",
                plain_sum(worst_p),
                r.plainInteraction,
                "",
                worst_p[3],
                f"T*/(φTuc) + V*/(φVuc) with φVuc = {phi_vuc / 1e3:.1f} kN; {terms}",
            )
        )
        return rows
    worst_l = max(needing, key=links)
    ratio = links(worst_l)
    rows.append(
        _row(
            f"Torsion: closed links Tus{_cite()}",
            abs(worst_l[0]) / 1e6,
            phi_tus / 1e6,
            "kN·m",
            worst_l[3],
            f"φTus = φ fsy.f (Asw/s) 2 At cot θv, Asw/s = {asw_s:.3f} mm²/mm per leg, At = "
            f"{at:.0f} mm², cot θv = {r.cotTheta:g}; with the shear beyond φVuc on the same "
            f"links (V* - φVuc)/φVus + T*/φTus = {ratio:.3f}; V* = {abs(worst_l[1]) / 1e3:.1f} "
            f"kN at {worst_l[4]}; {terms}" + ("" if stirrups else "; no closed links given"),
            utilisation=ratio,
        )
    )
    share, cap = r.linkSpacing
    limit = min(share * ut, cap)
    rows.append(
        _row(
            f"Torsion: closed link spacing{_cite()}",
            float(stirrups[2]) if stirrups else 0.0,
            limit,
            "mm",
            worst_l[3],
            f"s <= min({share:g} ut, {cap:g} mm), ut = {ut:.0f} mm",
            utilisation=(float(stirrups[2]) / limit) if stirrups else math.inf,
        )
    )
    fy = float(section.fy)
    extra = abs(worst_t[0]) * ut * r.cotTheta / (2 * phi * at * fy)
    rows.append(
        _row(
            f"Torsion: added longitudinal steel ΔAl{_cite()}",
            extra,
            extra,
            "mm²",
            worst_t[3],
            "ΔAl = T* ut cot θv / (2 φ At fsy) around the perimeter, in addition to the "
            "flexural steel (informative: not deducted from the flexural capacity here)",
            flag=True,
        )
    )
    return rows


def method_line() -> str:
    """The report's line of the method."""
    r = rules()
    return (
        f"torsion by Tuc = {r.crackingCoefficient:g} Jt √f'c (neglected below "
        f"{r.neglectShare:g} φTuc, no links up to T*/φTuc + V*/φVuc = {r.plainInteraction:g}), "
        f"web crushing with Tu.max = {r.maxCoefficient:g} f'c Jt and closed links "
        f"Tus = fsy.f (Asw/s) 2 At cot θv{_cite()}"
    )
