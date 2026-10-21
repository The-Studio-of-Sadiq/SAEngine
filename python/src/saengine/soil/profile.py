"""The soil profile of a borehole: unit weights, stresses, SPT corrections and layer parameters.

Every computation of :mod:`saengine.soil` starts from a :class:`Profile`: the borehole's layers
with each property resolved (from the log, else the laboratory samples in the layer, else a
correlation with the SPT, else a documented default), the vertical stresses with the water
table, and the SPT records with their corrections.

SPT corrections (Youd et al. 2001, "Liquefaction resistance of soils: summary report from the
1996 NCEER and 1998 NCEER/NSF workshops", J. Geotech. Geoenviron. Eng. 127(10), eq. 8 and
Table 2; Skempton 1986):

- ``N60 = N · (ER/60) · CB · CS · CR``: ER the hammer's energy ratio [%] (the test's own, else
  the report's), CB the borehole diameter factor, CS the sampler factor and CR the rod length
  factor: 0.75 below 3 m of rod, 0.80 for 3-4 m, 0.85 for 4-6 m, 0.95 for 6-10 m and 1.0
  beyond. The rod length is taken equal to the test depth (no stick-up above the ground), which
  errs on the low, safe side.
- ``(N1)60 = CN · N60`` with ``CN = (pa/σ'v)^0.5 ≤ 1.7`` (Liao & Whitman 1986, the form Youd
  et al. 2001 eq. 9 recommends, capped at 1.7 as there), σ'v the effective stress at the test,
  summed over the layers above. The liquefaction screening uses its procedure's own CN
  (:mod:`saengine.soil.liquefaction`).

That is the "textbook" practice (``design.practice``). The "bdConsultant" practice reproduces
the SPT correction sheets of common Bangladesh (Dhaka) soil reports:

- Each SPT row stands for the soil from the test above (or the ground) down to its own test;
  its soil is the layer at the test depth (on a layer boundary the layer below, which the
  sampler is driven into). The stress for CN is worked out at the row's mid-depth zm as if the
  whole column above were the row's own soil: ``σ'v = γ min(zm, zw) + (γsat - γw) max(0, zm - zw)``, zw the water table
  (with the water table at the ground, ``σ'v = zm · γ'``). It is not cumulative: it is low in
  a light layer under heavy ones and high in a heavy layer under light ones. The sheets print
  σ'v at the test depth as well; their CN uses the mid-depth value.
- ``CN = 0.77 log10(2000/σ'v)``, σ'v in kPa (Peck, Hanson & Thornburn 1974, Foundation
  Engineering, 2nd ed., in SI units), not capped.
- ``N60 = N · Eh · CB · CS · CR / 0.6`` with Eh = ER/100, CB = CS = 1 and Skempton's (1986) rod
  length factors: 0.75 below 4 m of rod, 0.85 for 4-6 m, 0.95 for 6-10 m and 1.0 from 10 m
  (Youd et al. 2001 Table 2 later split off 0.80 for 3-4 m; the sheets give 0.75 to a 3.0 m
  test, 0.85 at 4.5 m, 0.95 from 6.0 to 9.0 m and 1.0 from 10.5 m, which both readings fit;
  between the 1.5 m test intervals the sheets show nothing, so the band edges are Skempton's,
  each edge belonging to the band below it).
- ``(N1)60 = CN · N60``.
- Below the water table, ``N' = 15 + ((N1)60 - 15)/2`` when (N1)60 > 15 (the Terzaghi & Peck
  1948 dilatancy correction for submerged fine sand, applied by the sheets to (N1)60 and to
  every soil); otherwise ``N' = (N1)60``. N' feeds the Meyerhof-Bowles bearing pressure
  (:mod:`saengine.soil.bearing`).

Whatever the practice, the stresses of the profile (σv, u, σ'v for the bearing capacity, the
settlement and the liquefaction CSR) are the cumulative ones.

Unit weights missing from the log and the samples are the typical values of
:data:`DEFAULT_UNIT_WEIGHTS` (moist above the water table, saturated below; typical ranges in
e.g. Bowles 1996, Foundation Analysis and Design, 5th ed., and Das, Principles of Foundation
Engineering); a layer with a measured γ but no γsat takes the type's saturated value, at
least γ. They are indicative only: the profile reports which values are defaults. A layer's
missing values are first taken from the laboratory samples within it (their mean), the PI
as LL - PL (0 for a non-plastic sample). A sample gives the value it states, else the one its
tests give (:mod:`saengine.soil.lab`: cu = qu/2 of the unconfined compression or the triaxial
UU's cu, c' and φ' of the direct shear or an effective-stress triaxial, the fines content of
the grading, Cc, Cr and e0 of the consolidation test); the source then names the test. A layer
without a logged OCR takes ``OCR = σ'p/σ'v0`` (at least 1) of its consolidation samples, σ'v0
at each sample's mid-depth, averaged.

Correlations used when a layer has no measured value (each is reported as the value's source):

- cu of cohesive soil from N60: ``cu = 4.5 · N60`` kPa (Stroud 1974, "The standard
  penetration test in insensitive clays and soft rocks", f1 ≈ 4.5 kPa for PI of about 20-60).
- φ' of granular soil from (N1)60: ``φ' = (15.4 (N1)60)^0.5 + 20`` degrees, at most 45°
  (Hatanaka & Uchida 1996, in the N60 form of Mayne et al. 2001, FHWA NHI-01-031).
- E of granular soil from N60: ``E = α · pa · N60`` with α = 10 for clean sand and gravel, 5 for
  sand with fines (FC ≥ 15 %) and non-plastic silt (Kulhawy & Mayne 1990, EPRI EL-6800,
  normally consolidated).
- Undrained E of cohesive soil: ``Eu = 500 cu`` (Duncan & Buchignani 1976 give Eu/cu of about
  300-1500 by PI and OCR; 500 is at the soft end).
- Cc from the liquid limit: ``Cc = 0.009 (LL - 10)`` (Terzaghi & Peck 1967, normally
  consolidated clay of low to medium sensitivity); Cr = Cc/5 when only Cc is known; e0 from a
  sample's moisture content as ``e0 = w Gs`` with Gs = 2.70 (saturated).

Units inside: m, kPa, kN/m³, MPa for E.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any

from saengine.library.soil import Borehole, Design, Layer, Sample, SoilReport
from saengine.soil import lab

#: Unit weight of water [kN/m³].
GAMMA_W = 9.81
#: Atmospheric pressure [kPa].
PA = 101.325
#: Specific gravity of the soil solids for the void ratio from the moisture content.
GS = 2.70

#: Typical unit weights by soil type [kN/m³]: (moist, above the water table; saturated).
DEFAULT_UNIT_WEIGHTS: dict[str, tuple[float, float]] = {
    "clay": (18.0, 19.0),
    "silt": (18.0, 19.0),
    "sand": (18.0, 20.0),
    "gravel": (19.0, 21.0),
    "organic": (14.0, 15.0),
    "fill": (17.0, 19.0),
    "rock": (22.0, 23.0),
}

#: Rod length factor CR by rod length [m] (Youd et al. 2001, Table 2): (up to length, CR).
ROD_FACTORS = ((3.0, 0.75), (4.0, 0.80), (6.0, 0.85), (10.0, 0.95))
#: Skempton's (1986) rod length factors, as the Bangladesh consultant sheets use them.
SKEMPTON_ROD_FACTORS = ((4.0, 0.75), (6.0, 0.85), (10.0, 0.95))
#: (N1)60 above which the dilatancy correction of submerged soil applies (Terzaghi & Peck).
DILATANCY_N = 15.0

#: How the SPT corrections are worked out, per ``design.practice``.
SPT_METHODS = {
    "textbook": (
        "SPT (textbook): N60 = N (ER/60) CB CS CR, CR of Youd et al. 2001; (N1)60 = CN N60, "
        "CN = (pa/σ'v)^0.5 ≤ 1.7 (Liao & Whitman 1986) with the cumulative σ'v."
    ),
    "bdConsultant": (
        "SPT (Bangladesh consultant practice): N60 = N Eh CR/0.6, Eh = ER/100, CB = CS = 1, CR "
        "of Skempton 1986 (0.75 below 4 m, 0.85 to 6 m, 0.95 to 10 m, 1.0 beyond); (N1)60 = CN "
        "N60, CN = 0.77 log10(2000/σ'v) (Peck, Hanson & Thornburn), σ'v = the row's mid-depth "
        "× its own effective unit weight (not cumulative); below the water table N' = 15 + "
        "((N1)60 - 15)/2 when (N1)60 > 15 (Terzaghi & Peck), for every soil."
    ),
}

#: f1 of Stroud (1974): cu = f1 · N60 [kPa].
STROUD_F1 = 4.5
#: Eu/cu of cohesive soil.
EU_RATIO = 500.0
#: φ' from (N1)60 is capped at this [°].
PHI_MAX = 45.0
#: A silt with at least this plasticity index behaves like clay (Boulanger & Idriss 2006).
PLASTIC_PI = 7.0
#: The profile note of a silt with neither a PI nor a cu (log or samples): it is taken as
#: non-plastic, which the engineer should confirm.
SILT_NOTE = (
    "layer {index} (silt): no PI or cu given — treated as non-plastic (granular): it counts in "
    "the liquefaction screening and the sand methods; give PI or cu if it is plastic"
)

#: Properties a layer can take from its laboratory samples (stated by the sample or derived
#: from its tests, :func:`saengine.soil.lab.feed`), besides the PI, Cr and the OCR.
_SAMPLE_FIELDS = (
    "unitWeight", "cu", "c", "phi", "finesContent", "liquidLimit", "clayFraction", "Cc", "e0",
)  # fmt: skip


def behaviour(layer: Layer, pi: float | None = None, cu: float | None = None) -> str:
    """'granular', 'cohesive' or 'rock': which methods apply to the layer."""
    kind = layer.soilType
    if kind == "rock":
        return "rock"
    if kind in ("sand", "gravel"):
        return "granular"
    if kind in ("clay", "organic"):
        return "cohesive"
    if kind == "silt":
        if pi is not None:
            return "cohesive" if pi >= PLASTIC_PI else "granular"
        return "cohesive" if cu is not None else "granular"
    # fill: by what was measured in it
    return "cohesive" if cu is not None or (pi is not None and pi >= PLASTIC_PI) else "granular"


def rod_factor(depth: float, practice: str = "textbook") -> float:
    """CR for a rod as long as the test is deep [m]."""
    bands = SKEMPTON_ROD_FACTORS if practice == "bdConsultant" else ROD_FACTORS
    for length, factor in bands:
        if depth < length:
            return factor
    return 1.0


def peck_cn(sigma_eff: float) -> float:
    """CN = 0.77 log10(2000/σ'v), σ'v in kPa (Peck, Hanson & Thornburn 1974), not capped."""
    return 0.77 * math.log10(2000 / max(sigma_eff, 1e-6))


def dilatancy(n160: float) -> float:
    """N' = 15 + ((N1)60 - 15)/2 above 15 (Terzaghi & Peck), for soil below the water table."""
    return DILATANCY_N + (n160 - DILATANCY_N) / 2 if n160 > DILATANCY_N else n160


@dataclass
class SoilLayer:
    """A layer with its properties resolved; ``sources`` says where each came from."""

    index: int
    top: float  # m
    bottom: float  # m
    soil_type: str
    description: str
    behaviour: str
    gamma: float
    gamma_sat: float
    cu: float | None = None
    c: float = 0.0
    phi: float | None = None
    E: float | None = None  # MPa
    fines: float | None = None
    pi: float | None = None
    ll: float | None = None
    pl: float | None = None  # plastic limit, mean of the samples
    w: float | None = None  # natural moisture content [%], mean of the samples
    clay_fraction: float | None = None  # finer than 0.005 mm [%]
    cc: float | None = None
    cr: float | None = None
    e0: float | None = None
    ocr: float = 1.0
    n60: float | None = None  # mean N60 of the tests in the layer
    n160: float | None = None
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, z: float) -> bool:
        return self.top <= z < self.bottom

    def to_json(self) -> dict[str, Any]:
        def r(v: float | None, digits: int = 2) -> float | None:
            return None if v is None else round(v, digits)

        return {
            "index": self.index,
            "top": r(self.top * 1e3, 0),
            "bottom": r(self.bottom * 1e3, 0),
            "soilType": self.soil_type,
            "description": self.description,
            "behaviour": self.behaviour,
            "unitWeight": r(self.gamma),
            "saturatedUnitWeight": r(self.gamma_sat),
            "cu": r(self.cu, 1),
            "c": r(self.c, 1),
            "phi": r(self.phi, 1),
            "E": r(self.E, 1),
            "finesContent": r(self.fines, 1),
            "plasticityIndex": r(self.pi, 1),
            "liquidLimit": r(self.ll, 1),
            "plasticLimit": r(self.pl, 1),
            "moisture": r(self.w, 1),
            "clayFraction": r(self.clay_fraction, 1),
            "Cc": r(self.cc, 3),
            "Cr": r(self.cr, 3),
            "e0": r(self.e0, 3),
            "OCR": r(self.ocr),
            "N60": r(self.n60, 1),
            "N160": r(self.n160, 1),
            "sources": self.sources,
        }


@dataclass
class SptPoint:
    """An SPT record with its corrections and the stresses at its depth."""

    depth: float  # m
    n: int
    energy: float  # %
    cr: float
    n60: float
    sigma_v: float
    sigma_v_eff: float
    u: float
    cn: float
    n160: float
    layer: SoilLayer | None
    #: The effective stress CN was worked out with [kPa]: σ'v (textbook) or the row's own
    #: (bdConsultant).
    sigma_cn: float = 0.0
    #: N' after the dilatancy correction (bdConsultant), else None.
    n_prime: float | None = None
    #: (top, bottom) of the soil the row stands for (bdConsultant) [m].
    row: tuple[float, float] | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "depth": round(self.depth * 1e3),
            "N": self.n,
            "energyRatio": self.energy,
            "CR": self.cr,
            "N60": round(self.n60, 1),
            "sigma_v": round(self.sigma_v, 1),
            "u": round(self.u, 1),
            "sigma_v_eff": round(self.sigma_v_eff, 1),
            "sigma_cn": round(self.sigma_cn, 2),
            "CN": round(self.cn, 3),
            "N160": round(self.n160, 1),
            "soilType": self.layer.soil_type if self.layer else None,
            "layer": self.layer.index if self.layer else None,
        }
        if self.n_prime is not None:
            out["Nprime"] = round(self.n_prime, 1)
        if self.row is not None:
            out["rowTop"], out["rowBottom"] = round(self.row[0] * 1e3), round(self.row[1] * 1e3)
        return out


class Profile:
    """A borehole's layers, stresses and SPT records, in m and kPa below its ground."""

    def __init__(self, report: SoilReport, borehole: Borehole) -> None:
        self.borehole = borehole
        self.design: Design = report.design
        self.id = borehole.id
        self.x = borehole.x / 1e3
        self.y = borehole.y / 1e3
        self.ground_level = report.ground_level(borehole) / 1e3
        self.water_table = None if borehole.waterTable is None else borehole.waterTable / 1e3
        self.notes: list[str] = []
        self.layers = [self._resolve(i, layer) for i, layer in enumerate(borehole.layers)]
        self._ocr_from_samples()
        self.bottom = borehole.bottom / 1e3
        self.practice = self.design.practice
        self.spt: list[SptPoint] = []
        for record in borehole.spt:
            above = self.spt[-1].depth if self.spt else 0.0
            self.spt.append(self._spt(record.depth / 1e3, record.blows, record.energyRatio, above))
        self._correlate()

    # ─────────────────────────────── layers ───────────────────────────────

    def samples_in(self, index: int, layer: Layer) -> list[Sample]:
        """The samples whose top lies in the layer (the deepest layer also takes those below
        the log when it has none of its own)."""
        top, bottom = layer.top / 1e3, layer.bottom / 1e3
        samples = [s for s in self.borehole.samples if top <= s.depth / 1e3 < bottom]
        if not samples and index == len(self.borehole.layers) - 1:
            samples = [s for s in self.borehole.samples if s.depth / 1e3 >= top]
        return samples

    def _ocr_from_samples(self) -> None:
        """OCR = σ'p/σ'v0 (at least 1) of the layer's consolidation samples, σ'v0 at each
        sample's mid-depth, where the log gives no OCR."""
        for layer, soil_layer in zip(self.borehole.layers, self.layers, strict=True):
            if layer.OCR is not None:
                continue
            ratios = []
            for sample in self.samples_in(soil_layer.index, layer):
                found = lab.feed(sample).get("preconsolidation")
                if found is None:
                    continue
                stress = self.sigma_v_eff(sample.mid / 1e3)
                if stress > 0:
                    ratios.append(max(1.0, found[0] / stress))
            if ratios:
                soil_layer.ocr = fmean(ratios)
                soil_layer.sources["OCR"] = f"σ'p/σ'v0 of samples ({len(ratios)})"

    def _resolve(self, index: int, layer: Layer) -> SoilLayer:
        top, bottom = layer.top / 1e3, layer.bottom / 1e3
        sources: dict[str, str] = {}
        samples = self.samples_in(index, layer)
        feeds = [lab.feed(s) for s in samples]

        def from_samples(name: str) -> tuple[float, str] | None:
            """The mean of the samples' values and its source (with the tests they come from
            when a sample does not state the value itself)."""
            found = [f[name] for f in feeds if name in f]
            if not found:
                return None
            how = sorted({h for _, h in found if h})
            source = f"samples ({len(found)})"
            if how:
                source = f"samples ({len(found)}: {', '.join(how)})"
            return fmean(v for v, _ in found), source

        def value(name: str) -> float | None:
            own = getattr(layer, name)
            if own is not None:
                sources[name] = "log"
                return float(own)
            found = from_samples(name)
            if found is not None:
                sources[name] = found[1]
                return found[0]
            return None

        gamma = value("unitWeight")
        gamma_sat = layer.saturatedUnitWeight
        default, default_sat = DEFAULT_UNIT_WEIGHTS[layer.soilType]
        if gamma_sat is not None:
            sources["saturatedUnitWeight"] = "log"
        elif gamma is not None:
            gamma_sat = max(gamma, default_sat)
            sources["saturatedUnitWeight"] = "default, at least γ"
        else:
            gamma_sat = default_sat
            sources["saturatedUnitWeight"] = "default"
        if gamma is None:
            gamma = default
            sources["unitWeight"] = "default"
        pi = None
        if layer.plasticityIndex is not None:
            pi = layer.plasticityIndex
            sources["plasticityIndex"] = "log"
        else:
            found = from_samples("plasticityIndex")
            if found is not None:
                pi = max(0.0, found[0])
                count = sum("plasticityIndex" in f for f in feeds)
                sources["plasticityIndex"] = f"samples LL - PL ({count})"
                if any(
                    f["plasticityIndex"][1] == "non-plastic"
                    for f in feeds
                    if "plasticityIndex" in f
                ):
                    sources["plasticityIndex"] = found[1]
        cu = value("cu")
        e0 = value("e0")
        if e0 is None:
            moistures = [s.moisture for s in samples if s.moisture is not None]
            if moistures and layer.soilType in ("clay", "silt", "organic"):
                e0 = fmean(moistures) / 100 * GS
                sources["e0"] = f"w·Gs from samples ({len(moistures)}), Gs = {GS}"
        ll = value("liquidLimit")
        clay_fraction = value("clayFraction")
        plastic = [s.plasticLimit for s in samples if s.plasticLimit is not None]
        pl = fmean(plastic) if plastic else None
        moisture = [s.moisture for s in samples if s.moisture is not None]
        w = fmean(moisture) if moisture else None
        cc = value("Cc")
        if cc is None and ll is not None:
            cc = 0.009 * max(ll - 10, 0)
            sources["Cc"] = "0.009(LL - 10), Terzaghi & Peck 1967"
        cr = layer.Cr
        found_cr = from_samples("Cr")
        if cr is not None:
            sources["Cr"] = "log"
        elif found_cr is not None:
            cr = found_cr[0]
            sources["Cr"] = found_cr[1]
        elif cc is not None:
            cr = cc / 5
            sources["Cr"] = "Cc/5"
        resolved = SoilLayer(
            index=index,
            top=top,
            bottom=bottom,
            soil_type=layer.soilType,
            description=layer.description,
            behaviour=behaviour(layer, pi, cu),
            gamma=gamma,
            gamma_sat=float(gamma_sat),
            cu=cu,
            c=value("c") or 0.0,
            phi=value("phi"),
            E=value("E"),
            fines=value("finesContent"),
            pi=pi,
            ll=ll,
            pl=pl,
            w=w,
            clay_fraction=clay_fraction,
            cc=cc,
            cr=cr,
            e0=e0,
            ocr=layer.OCR or 1.0,
            sources=sources,
        )
        if layer.OCR is not None:
            sources["OCR"] = "log"
        if layer.soilType == "silt" and pi is None and cu is None:
            self.notes.append(SILT_NOTE.format(index=index + 1))
        return resolved

    def layer_at(self, z: float) -> SoilLayer | None:
        """The layer at depth ``z`` [m]; the deepest one continues below the log."""
        for layer in self.layers:
            if layer.contains(z):
                return layer
        if self.layers and z >= self.layers[-1].bottom:
            return self.layers[-1]
        return None

    # ─────────────────────────────── stresses ───────────────────────────────

    def sigma_v(self, z: float) -> float:
        """Total vertical stress at depth ``z`` [kPa]."""
        wt = math.inf if self.water_table is None else self.water_table
        total, depth = 0.0, 0.0
        bounds = [(layer.top, layer.bottom, layer) for layer in self.layers]
        if not bounds:
            default, sat = DEFAULT_UNIT_WEIGHTS["sand"]
            above = min(z, wt)
            return default * above + sat * max(0.0, z - wt)
        last = bounds[-1]
        bounds[-1] = (last[0], math.inf, last[2])
        for top, bottom, layer in bounds:
            if depth >= z:
                break
            lower = min(bottom, z)
            dry = max(0.0, min(lower, wt) - top)
            wet = max(0.0, lower - max(top, wt))
            total += layer.gamma * dry + layer.gamma_sat * wet
            depth = lower
        return total

    def u(self, z: float) -> float:
        """Hydrostatic pore pressure at depth ``z`` [kPa]."""
        if self.water_table is None:
            return 0.0
        return GAMMA_W * max(0.0, z - self.water_table)

    def sigma_v_eff(self, z: float) -> float:
        return self.sigma_v(z) - self.u(z)

    def below_water(self, z: float) -> bool:
        return self.water_table is not None and z >= self.water_table

    # ─────────────────────────────── SPT ───────────────────────────────

    def energy(self, own: float | None) -> float:
        return own if own is not None else self.design.hammerEnergy

    def n60(self, depth: float, n: float, energy: float | None = None) -> tuple[float, float]:
        """(N60, CR) of a field N at ``depth`` [m]."""
        spt = self.design.spt
        cr = rod_factor(depth, self.practice) if spt.rodLength else 1.0
        if self.practice == "bdConsultant":
            # N60 = N Eh CB CS CR / 0.6 with CB = CS = 1.
            return n * self.energy(energy) / 100 * cr / 0.6, cr
        return n * self.energy(energy) / 60 * spt.boreholeFactor * spt.samplerFactor * cr, cr

    def row_stress(self, layer: SoilLayer | None, z: float) -> float:
        """σ'v at ``z`` [m] as if the whole column were ``layer``'s soil (consultant sheets)."""
        if layer is None:
            gamma, gamma_sat = DEFAULT_UNIT_WEIGHTS["sand"]
        else:
            gamma, gamma_sat = layer.gamma, layer.gamma_sat
        wt = math.inf if self.water_table is None else self.water_table
        return gamma * min(z, wt) + (gamma_sat - GAMMA_W) * max(0.0, z - wt)

    def _spt(self, depth: float, n: int, energy: float | None, above: float) -> SptPoint:
        n60, cr = self.n60(depth, n, energy)
        sv, u = self.sigma_v(depth), self.u(depth)
        eff = max(sv - u, 1e-6)
        layer = self.layer_at(depth)
        if self.practice == "bdConsultant":
            mid = (above + depth) / 2
            sigma_cn = max(self.row_stress(layer, mid), 1e-6)
            cn = peck_cn(sigma_cn)
            n160 = cn * n60
            n_prime = dilatancy(n160) if self.below_water(depth) else n160
            return SptPoint(
                depth, n, self.energy(energy), cr, n60, sv, eff, u, cn, n160, layer,
                sigma_cn, n_prime, (above, depth),
            )  # fmt: skip
        cn = min(1.7, math.sqrt(PA / eff))
        return SptPoint(
            depth, n, self.energy(energy), cr, n60, sv, eff, u, cn, cn * n60, layer, eff
        )

    @property
    def spt_method(self) -> str:
        return SPT_METHODS[self.practice]

    def spt_in(self, top: float, bottom: float) -> list[SptPoint]:
        return [p for p in self.spt if top - 1e-9 <= p.depth <= bottom + 1e-9]

    def _correlate(self) -> None:
        """Mean N60 per layer and the SPT correlations for the values the log does not give."""
        for layer in self.layers:
            last = layer is self.layers[-1]
            points = [
                p for p in self.spt if layer.contains(p.depth) or (last and p.depth >= layer.top)
            ]
            if not points:
                continue
            layer.n60 = fmean(p.n60 for p in points)
            layer.n160 = fmean(p.n160 for p in points)
            if layer.behaviour == "cohesive" and layer.cu is None:
                layer.cu = STROUD_F1 * layer.n60
                layer.sources["cu"] = f"{STROUD_F1:g}·N60, Stroud 1974"
            if layer.behaviour == "granular" and layer.phi is None:
                layer.phi = min(PHI_MAX, math.sqrt(15.4 * layer.n160) + 20)
                layer.sources["phi"] = "√(15.4 (N1)60) + 20, Hatanaka & Uchida 1996"
            if layer.behaviour == "granular" and layer.E is None:
                alpha = self.modulus_number(layer)
                layer.E = alpha * PA * layer.n60 / 1e3
                layer.sources["E"] = f"{alpha:g}·pa·N60, Kulhawy & Mayne 1990"
        for layer in self.layers:
            if layer.behaviour == "cohesive" and layer.E is None and layer.cu is not None:
                layer.E = EU_RATIO * layer.cu / 1e3
                layer.sources["E"] = f"Eu = {EU_RATIO:g}·cu"

    @staticmethod
    def modulus_number(layer: SoilLayer) -> float:
        """α of E = α · pa · N60 (Kulhawy & Mayne 1990)."""
        if layer.soil_type in ("silt", "fill") or (layer.fines is not None and layer.fines >= 15):
            return 5.0
        return 10.0

    def to_json(self) -> list[dict[str, Any]]:
        return [p.to_json() for p in self.spt]
