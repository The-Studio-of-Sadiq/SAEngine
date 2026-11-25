"""Soil Report seismic site classification, liquefaction, spectra and shaking records."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import number, result, table, text
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    profile,
    register_tab,
    require_report,
    result_rows,
)

G = 9.80665


def _fields(fid: str) -> list[Any]:
    if fid in {
        "soilSeismic.ariasIntensity",
        "soilSeismic.recordDuration",
        "soilSeismic.slopeDisplacement",
    }:
        fields = [
            text("accelerationG", "Acceleration time series [g] (one value per row)", ""),
            number("timeStepS", "Time step [s]", 0.01, unit="s", min=0.0001),
        ]
        if fid == "soilSeismic.slopeDisplacement":
            fields.extend(
                [
                    number(
                        "yieldAccelerationG", "Yield acceleration ky [g]", 0.15, unit="g", min=0.001
                    ),
                    number("slopeAngleDeg", "Slope angle [°]", 25.0, unit="°", min=1, max=80),
                ]
            )
        return fields
    if fid in {
        "soilSeismic.transferFunction",
        "soilSeismic.shearWaveProfile",
        "soilSeismic.hystereticDamping",
    }:
        fields = [text("profileRows", "Thickness [m], Vs [m/s], damping ratio rows", "")]
        if fid == "soilSeismic.transferFunction":
            fields.append(
                number("maximumFrequencyHz", "Maximum frequency [Hz]", 10.0, unit="Hz", min=0.1)
            )
        if fid == "soilSeismic.hystereticDamping":
            fields.append(number("strainPct", "Shear strain amplitude [%]", 0.1, unit="%", min=0))
        return fields
    if fid == "soilSeismic.timeHistoryPick":
        return [
            text("recordRows", "ID, magnitude, Rrup [km], Vs30 [m/s], PGA [g], duration [s]", ""),
            number("targetMagnitude", "Target magnitude", 7.5, min=4, max=9.5),
            number("targetPgaG", "Target PGA [g]", 0.25, unit="g", min=0.01),
            number("siteVs30", "Site Vs30 [m/s]", 250.0, unit="m/s", min=50),
        ]
    if fid == "soilSeismic.amplificationFactor":
        return [number("periodS", "Spectral period [s]", 0.5, unit="s", min=0)]
    if fid == "soilSeismic.postLiquefactionSettlement":
        return [
            *common_fields(fid),
            number("pgaG", "Peak ground acceleration [g]", 0.25, unit="g", min=0.01),
            number("magnitude", "Moment magnitude", 7.5, min=4, max=9.5),
            text("strainRows", "Layer index, post-liquefaction volumetric strain [%]", ""),
        ]
    if fid == "soilSeismic.seismicEarthPressure":
        return [
            number("heightM", "Retained height [m]", 4.0, unit="m", min=0.1),
            number("phiDeg", "Friction angle φ' [°]", 30.0, unit="°", min=0, max=50),
            number("gammaKnM3", "Soil unit weight [kN/m³]", 18.0, unit="kN/m³", min=1),
            number("kh", "Horizontal seismic coefficient kh", 0.15, min=0, max=1),
            number("kv", "Vertical seismic coefficient kv", 0.0, min=-0.5, max=0.5),
            number("waterTableM", "Water table below wall top [m]", 100.0, unit="m", min=0),
        ]
    if fid == "soilSeismic.retainingDisplacement":
        return [
            number("heightM", "Retained height [m]", 4.0, unit="m", min=0.1),
            number("wallThicknessM", "Wall thickness [m]", 0.3, unit="m", min=0.05),
            number("concreteEMpa", "Wall elastic modulus [MPa]", 25000.0, unit="MPa", min=100),
            number("soilGammaKnM3", "Soil unit weight [kN/m³]", 18.0, unit="kN/m³", min=1),
            number("phiDeg", "Soil friction angle φ' [°]", 30.0, unit="°", min=0, max=50),
        ]
    return common_fields(fid)


def _needs_project(fid: str) -> bool:
    return fid not in {
        "soilSeismic.ariasIntensity",
        "soilSeismic.recordDuration",
        "soilSeismic.slopeDisplacement",
        "soilSeismic.timeHistoryPick",
        "soilSeismic.transferFunction",
        "soilSeismic.shearWaveProfile",
        "soilSeismic.hystereticDamping",
        "soilSeismic.seismicEarthPressure",
        "soilSeismic.retainingDisplacement",
    }


def _series(raw: str) -> list[float]:
    try:
        values = [
            float(part) for line in raw.replace(",", " ").splitlines() for part in line.split()
        ]
    except ValueError:
        raise FeatureInputError("Acceleration series contains a non-numeric reading.") from None
    if len(values) < 3:
        raise FeatureInputError("Enter at least three acceleration readings.")
    return values


def _profile_rows(raw: str) -> list[tuple[float, float, float]]:
    rows = []
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        bits = [part.strip() for part in line.split(",")]
        if len(bits) < 2:
            raise FeatureInputError(f"Shear-wave row {line_no} must be thickness,Vs[,damping].")
        try:
            thickness, vs = float(bits[0]), float(bits[1])
            damping = float(bits[2]) if len(bits) > 2 and bits[2] else 0.05
        except ValueError:
            raise FeatureInputError(
                f"Shear-wave row {line_no} contains a non-numeric value."
            ) from None
        if thickness <= 0 or vs <= 0 or not 0 <= damping < 1:
            raise FeatureInputError(
                f"Shear-wave row {line_no} needs positive thickness/Vs and 0 ≤ damping < 1."
            )
        rows.append((thickness, vs, damping))
    if not rows:
        raise FeatureInputError(
            "Enter at least one layer as thickness [m], Vs [m/s], damping ratio."
        )
    return rows


def _vs30_from_profile(rows: list[tuple[float, float, float]]) -> float:
    depth = 0.0
    travel = 0.0
    for thickness, vs, _ in rows:
        used = min(thickness, 30 - depth)
        if used > 0:
            travel += used / vs
            depth += used
        if depth >= 30:
            break
    if depth < 30:
        rows = rows[:]
        travel += (30 - depth) / rows[-1][1]
    return 30 / travel


def _screen_all(
    report: Any, pga: float, magnitude: float, ctx: Any
) -> list[tuple[Any, Any, dict[str, Any]]]:
    from saengine.soil import liquefaction

    modified = report.model_copy(
        update={
            "design": report.design.model_copy(
                update={
                    "liquefaction": report.design.liquefaction.model_copy(
                        update={"magnitude": magnitude, "pga": pga}
                    )
                }
            )
        }
    )
    out = []
    for bh in modified.boreholes:
        prof = profile(modified, bh)
        screening = liquefaction.screen(prof, pga, f"Entered PGA = {pga:g} g")
        out.append((bh, prof, screening))
    return out


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid in {
        "soilSeismic.ariasIntensity",
        "soilSeismic.recordDuration",
        "soilSeismic.slopeDisplacement",
    }:
        series = _series(values["accelerationG"])
        dt = values["timeStepS"]
        cumulative = []
        total = 0.0
        for acceleration in series:
            total += acceleration**2 * dt
            cumulative.append(total)
        if fid == "soilSeismic.ariasIntensity":
            ia = math.pi * G / 2 * total
            return result(
                summary={
                    "ariasIntensityMPerS": ia,
                    "recordDurationS": (len(series) - 1) * dt,
                    "peakAccelerationG": max(abs(a) for a in series),
                },
                tables=[
                    table(
                        "Arias intensity accumulation",
                        [
                            ("sample", "Sample"),
                            ("timeS", "Time", "s"),
                            ("cumulativeIntensityMPerS", "Cumulative Ia", "m/s"),
                        ],
                        [
                            {
                                "sample": i + 1,
                                "timeS": i * dt,
                                "cumulativeIntensityMPerS": math.pi * G / 2 * v,
                            }
                            for i, v in enumerate(cumulative)
                            if i % max(1, len(series) // 50) == 0
                        ],
                    )
                ],
                notes=[
                    "Ia = π/(2g)∫a²dt, with acceleration in g converted to m/s²; baseline correction and instrument filtering should be completed before entering a record."
                ],
            )
        if fid == "soilSeismic.recordDuration":
            if total <= 0:
                raise FeatureInputError("The acceleration record has no non-zero energy.")
            t5 = next(i * dt for i, value in enumerate(cumulative) if value >= 0.05 * total)
            t95 = next(i * dt for i, value in enumerate(cumulative) if value >= 0.95 * total)
            return result(
                summary={
                    "significantDurationS": t95 - t5,
                    "t5S": t5,
                    "t95S": t95,
                    "recordDurationS": (len(series) - 1) * dt,
                },
                tables=[
                    table(
                        "Significant duration",
                        [
                            ("timeS", "Time", "s"),
                            ("cumulativeEnergyPct", "Cumulative Arias energy", "%"),
                        ],
                        [
                            {"timeS": i * dt, "cumulativeEnergyPct": 100 * v / total}
                            for i, v in enumerate(cumulative)
                            if i % max(1, len(series) // 50) == 0
                        ],
                    )
                ],
                notes=[
                    "Significant duration is D5–95 from cumulative squared acceleration; this energy-based metric is sensitive to baseline correction and the chosen record window."
                ],
            )
        ky = values["yieldAccelerationG"]
        velocity = displacement = 0.0
        max_disp = 0.0
        for ag in series:
            if velocity > 0 or ag > ky:
                velocity = max(0.0, velocity + (ag - ky) * G * dt)
                displacement += velocity * dt
                max_disp = max(max_disp, displacement)
        return result(
            summary={
                "newmarkDisplacementMm": max_disp * 1000,
                "yieldAccelerationG": ky,
                "slopeAngleDeg": values["slopeAngleDeg"],
                "significantDurationS": (len(series) - 1) * dt,
            },
            tables=[
                table(
                    "Newmark sliding-block integration",
                    [
                        ("sample", "Sample"),
                        ("accelerationG", "Acceleration", "g"),
                        ("timeS", "Time", "s"),
                    ],
                    [
                        {"sample": i + 1, "accelerationG": ag, "timeS": i * dt}
                        for i, ag in enumerate(series)
                        if i % max(1, len(series) // 50) == 0
                    ],
                )
            ],
            notes=[
                "Rigid sliding-block screening integrates only acceleration excursions above the entered yield acceleration; the simplified zero-velocity reset is not a deformable-slope analysis."
            ],
        )
    if fid == "soilSeismic.timeHistoryPick":
        lines = [line.strip() for line in values["recordRows"].splitlines() if line.strip()]
        rows = []
        for i, line in enumerate(lines, 1):
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 6:
                raise FeatureInputError(
                    f"Record row {i} must be id, magnitude, Rrup, Vs30, PGA, duration."
                )
            try:
                mag, rrup, vs, pga, duration = map(float, parts[1:])
            except ValueError:
                raise FeatureInputError(
                    f"Record row {i} contains a non-numeric parameter."
                ) from None
            scale = values["targetPgaG"] / pga if pga > 0 else math.inf
            score = (
                abs(mag - values["targetMagnitude"])
                + abs(math.log(max(vs, 1) / values["siteVs30"]))
                + 0.02 * rrup
                + abs(math.log(max(scale, 1e-6)))
            )
            rows.append(
                {
                    "recordId": parts[0],
                    "magnitude": mag,
                    "rrupKm": rrup,
                    "vs30MPerS": vs,
                    "pgaG": pga,
                    "durationS": duration,
                    "scaleFactor": scale,
                    "selectionScore": score,
                }
            )
        if not rows:
            raise FeatureInputError(
                "Enter candidate ground motions to rank by magnitude, distance, site velocity and amplitude."
            )
        rows.sort(key=lambda row: row["selectionScore"])
        return result_rows(
            "Ground-motion selection ranking",
            [
                ("recordId", "Record"),
                ("magnitude", "Magnitude"),
                ("rrupKm", "Rrup", "km"),
                ("vs30MPerS", "Vs30", "m/s"),
                ("pgaG", "PGA", "g"),
                ("durationS", "Duration", "s"),
                ("scaleFactor", "PGA scale"),
                ("selectionScore", "Selection score"),
            ],
            rows,
            summary={
                "candidatesCount": len(rows),
                "topRecordId": rows[0]["recordId"],
                "targetMagnitude": values["targetMagnitude"],
            },
            notes=[
                "Records are ranked by a transparent distance/magnitude/Vs30/amplitude score; confirm spectral compatibility, component pairing and record quality before selection."
            ],
        )
    if fid in {
        "soilSeismic.transferFunction",
        "soilSeismic.shearWaveProfile",
        "soilSeismic.hystereticDamping",
    }:
        layers = _profile_rows(values["profileRows"])
        if fid == "soilSeismic.shearWaveProfile":
            depth = 0.0
            rows = []
            for i, (thickness, vs, damping) in enumerate(layers, 1):
                top = depth
                depth += thickness
                rows.append(
                    {
                        "layer": i,
                        "topM": top,
                        "bottomM": depth,
                        "thicknessM": thickness,
                        "vsMPerS": vs,
                        "dampingRatio": damping,
                    }
                )
            return result(
                summary={
                    "vs30MPerS": _vs30_from_profile(layers),
                    "fundamentalPeriodS": 4
                    * sum(
                        min(t, max(0, 30 - sum(x[0] for x in layers[:i]))) / v
                        for i, (t, v, _) in enumerate(layers)
                    ),
                },
                tables=[
                    table(
                        "Shear-wave velocity layers",
                        [
                            ("layer", "Layer"),
                            ("topM", "Top", "m"),
                            ("bottomM", "Bottom", "m"),
                            ("thicknessM", "Thickness", "m"),
                            ("vsMPerS", "Vs", "m/s"),
                            ("dampingRatio", "Damping ratio"),
                        ],
                        rows,
                    )
                ],
                notes=[
                    "Vs30 is the travel-time average over the top 30 m; if the profile is shorter, the last measured Vs is extended to 30 m."
                ],
            )
        if fid == "soilSeismic.hystereticDamping":
            strain = values["strainPct"]
            rows = [
                {"layer": i + 1, "vsMPerS": vs, "dampingRatio": damping, "strainPct": strain}
                for i, (_, vs, damping) in enumerate(layers)
            ]
            return result_rows(
                "Entered damping by layer",
                [
                    ("layer", "Layer"),
                    ("vsMPerS", "Vs", "m/s"),
                    ("strainPct", "Shear strain", "%"),
                    ("dampingRatio", "Damping ratio"),
                ],
                rows,
                summary={
                    "meanDampingRatio": sum(row["dampingRatio"] for row in rows) / len(rows),
                    "strainPct": strain,
                },
                notes=[
                    "Layer damping values are accepted as user-supplied strain-compatible inputs; no default modulus-reduction curve is assumed."
                ],
            )
        maximum = values["maximumFrequencyHz"]
        total_time = sum(thickness / vs for thickness, vs, _ in layers)
        rows = []
        for i in range(101):
            f = maximum * i / 100
            phase = 2 * math.pi * f * total_time
            damping = sum(
                weight * layer[2]
                for weight, layer in zip(
                    (layer[0] / layer[1] / total_time for layer in layers), layers, strict=True
                )
            )
            denom = math.sqrt(math.cos(phase) ** 2 + (2 * damping * math.sin(phase)) ** 2)
            rows.append({"frequencyHz": f, "amplification": 1 / max(denom, 1e-4)})
        return result_rows(
            "Equivalent-column SH transfer function",
            [("frequencyHz", "Frequency", "Hz"), ("amplification", "Amplitude ratio")],
            rows,
            summary={
                "travelTimeS": total_time,
                "fundamentalFrequencyHz": 1 / (4 * total_time),
                "fundamentalPeriodS": 4 * total_time,
                "maximumAmplification": max(row["amplification"] for row in rows),
            },
            notes=[
                "A vertically propagating SH wave in an equivalent uniform column is approximated with a travel-time-weighted damping ratio; a layered transfer matrix should be used for site-specific response."
            ],
        )
    if fid == "soilSeismic.seismicEarthPressure":
        phi = math.radians(values["phiDeg"])
        theta = math.atan2(values["kh"], 1 - values["kv"])
        if theta >= phi:
            raise FeatureInputError(
                "Horizontal seismic coefficient gives an inertial angle at or above the soil friction angle; the active wedge is not defined by this solution."
            )
        root = math.sqrt(
            max(0.0, math.sin(phi) * math.sin(phi - theta) / max(math.cos(theta), 1e-9))
        )
        kae = math.cos(phi - theta) ** 2 / (math.cos(theta) ** 2 * (1 + root) ** 2)
        ka = math.tan(math.pi / 4 - phi / 2) ** 2
        h, gamma, kv = values["heightM"], values["gammaKnM3"], values["kv"]
        static = 0.5 * ka * gamma * h**2
        seismic = 0.5 * ((1 - kv) * kae - ka) * gamma * h**2
        zw = values["waterTableM"]
        rows = []
        for i in range(11):
            z = h * i / 10
            rows.append(
                {
                    "depthM": z,
                    "staticSoilKpa": ka * gamma * z,
                    "seismicIncrementKpa": ((1 - kv) * kae - ka) * gamma * z,
                    "waterKpa": G * max(0, z - zw),
                }
            )
        return result(
            summary={
                "staticKa": ka,
                "seismicKae": kae,
                "staticResultantKnPerM": static,
                "seismicIncrementKnPerM": seismic,
            },
            tables=[
                table(
                    "Seismic retaining pressure profile",
                    [
                        ("depthM", "Depth", "m"),
                        ("staticSoilKpa", "Static soil pressure", "kPa"),
                        ("seismicIncrementKpa", "Seismic increment", "kPa"),
                        ("waterKpa", "Water", "kPa"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Mononobe–Okabe active wedge for a smooth vertical wall and level backfill, with the pseudo-static inertial angle atan(kh/(1−kv)); water pressure is hydrostatic and separate."
            ],
        )
    if fid == "soilSeismic.retainingDisplacement":
        from saengine.soil.earth_pressure import rankine_active

        h = values["heightM"]
        pmax = rankine_active(values["phiDeg"]) * values["soilGammaKnM3"] * h
        e = values["concreteEMpa"] * 1000
        inertia = values["wallThicknessM"] ** 3 / 12
        displacement_m = pmax * h**4 / (30 * e * inertia)
        return result(
            summary={
                "estimatedTopDisplacementMm": displacement_m * 1000,
                "activeBasePressureKpa": pmax,
                "wallThicknessM": values["wallThicknessM"],
            },
            tables=[
                table(
                    "Cantilever wall elastic displacement",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Wall height [m]", "value": h},
                        {"parameter": "Base pressure [kPa]", "value": pmax},
                        {"parameter": "Wall EI [kN·m² per m]", "value": e * inertia},
                        {
                            "parameter": "Estimated top displacement [mm]",
                            "value": displacement_m * 1000,
                        },
                    ],
                )
            ],
            notes=[
                "A one-metre cantilever strip with triangular lateral pressure is treated as an uncracked elastic beam; soil-structure interaction, cracking and support conditions are not included."
            ],
        )

    report = require_report(ctx)
    from saengine.report.clauses import in_force
    from saengine.soil import site_class

    if fid == "soilSeismic.siteClassMap":
        rows = []
        with in_force(ctx.root):
            for bh in report.boreholes:
                info = site_class.site_class(profile(report, bh))
                rows.append(
                    {
                        "borehole": bh.id,
                        "xM": bh.x / 1000,
                        "yM": bh.y / 1000,
                        "siteClass": info.get("class"),
                        "meanN": info.get("N"),
                        "meanCuKpa": info.get("su"),
                        "provisional": info.get("provisional"),
                        "flags": "; ".join(flag["class"] for flag in info.get("flags", [])),
                        "note": info.get("note"),
                    }
                )
        if not any(row["siteClass"] for row in rows):
            raise FeatureInputError(
                "No borehole has sufficient SPT or undrained-strength data for a site class."
            )
        return result_rows(
            "Seismic site-class map nodes",
            [
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("siteClass", "Site class"),
                ("meanN", "Harmonic N"),
                ("meanCuKpa", "Harmonic cu", "kPa"),
                ("provisional", "Provisional"),
                ("flags", "Special flags"),
                ("note", "Basis"),
            ],
            rows,
            summary={
                "boreholesCount": len(rows),
                "classesCount": len({row["siteClass"] for row in rows if row["siteClass"]}),
            },
            notes=[
                "Each borehole uses the active code-pack site-class rules; classes needing special study appear as flags."
            ],
        )
    if fid in {"soilSeismic.vs30Profile", "soilSeismic.sitePeriod", "soilSeismic.shearWaveProfile"}:
        rows = []
        for bh in report.boreholes:
            prof = profile(report, bh)
            tests = prof.spt
            velocity_layers = []
            for layer in prof.layers:
                points = [point for point in tests if layer.top <= point.depth < layer.bottom]
                n = (
                    sum(point.n60 for point in points) / len(points)
                    if points
                    else next((point.n60 for point in tests if point.depth >= layer.top), None)
                )
                if n is None:
                    continue
                # Widely used SPT-to-Vs screening relation (Imai & Tonouchi-type): Vs ≈ 97 N60^0.314.
                vs = 97 * max(n, 1) ** 0.314
                velocity_layers.append((layer.top, layer.bottom, vs, layer.soil_type, n))
            if not velocity_layers:
                continue
            depth = 0.0
            travel = 0.0
            for top, bottom, vs, _, _ in velocity_layers:
                thickness = min(max(0.0, bottom - max(top, depth)), 30 - depth)
                if thickness > 0:
                    travel += thickness / vs
                    depth += thickness
                if depth >= 30:
                    break
            if depth < 30:
                travel += (30 - depth) / velocity_layers[-1][2]
            vs30 = 30 / travel
            rows.append(
                {
                    "borehole": bh.id,
                    "vs30MPerS": vs30,
                    "sitePeriodS": 4 * 30 / vs30,
                    "layersCount": len(velocity_layers),
                    "basis": "SPT empirical correlation",
                }
            )
        if not rows:
            raise FeatureInputError(
                "SPT data are needed to estimate a shear-wave velocity profile."
            )
        if fid == "soilSeismic.sitePeriod":
            return result_rows(
                "Quarter-wave site period",
                [
                    ("borehole", "Borehole"),
                    ("vs30MPerS", "Vs30", "m/s"),
                    ("sitePeriodS", "Approximate site period", "s"),
                    ("basis", "Velocity basis"),
                ],
                rows,
                summary={"governingSitePeriodS": max(row["sitePeriodS"] for row in rows)},
                notes=[
                    "T0 ≈ 4H/Vs30 with H = 30 m; the velocity is correlated from SPT, not measured by downhole or surface-wave testing."
                ],
            )
        return result_rows(
            "Shear-wave velocity screening profile",
            [
                ("borehole", "Borehole"),
                ("vs30MPerS", "Vs30", "m/s"),
                ("sitePeriodS", "Quarter-wave period", "s"),
                ("layersCount", "Correlated layers"),
                ("basis", "Basis"),
            ],
            rows,
            summary={
                "meanVs30MPerS": sum(row["vs30MPerS"] for row in rows) / len(rows),
                "boreholesCount": len(rows),
            },
            notes=[
                "Vs is estimated from corrected SPT N60 using Vs ≈ 97 N60^0.314 and harmonically averaged through the top 30 m; measure Vs directly for final site classification."
            ],
        )
    if fid in {
        "soilSeismic.liquefactionMap",
        "soilSeismic.csrCrr",
        "soilSeismic.postLiquefactionSettlement",
        "soilSeismic.lateralSpread",
    }:
        pga = values.get("pgaG") or report.design.liquefaction.pga
        if pga is None:
            raise FeatureInputError(
                "Enter the design peak ground acceleration to screen the logged SPT profile."
            )
        with in_force(ctx.root):
            screened = _screen_all(
                report, pga, values.get("magnitude", report.design.liquefaction.magnitude), ctx
            )
        points = [
            {"borehole": bh.id, "xM": bh.x / 1000, "yM": bh.y / 1000, **point}
            for bh, _, out in screened
            for point in out["points"]
        ]
        layers = [
            {"borehole": bh.id, **layer} for bh, _, out in screened for layer in out["layers"]
        ]
        if not points:
            raise FeatureInputError("No SPT records are available for liquefaction screening.")
        if fid == "soilSeismic.csrCrr":
            return result_rows(
                "Cyclic stress and resistance ratios",
                [
                    ("borehole", "Borehole"),
                    ("depth", "Depth", "mm"),
                    ("N", "Field N"),
                    ("N60", "N60"),
                    ("sigma_v", "Total stress", "kPa"),
                    ("sigma_v_eff", "Effective stress", "kPa"),
                    ("csr", "CSR"),
                    ("crr", "CRR"),
                    ("fs", "CRR/CSR"),
                    ("liquefiable", "Liquefiable"),
                ],
                [row for row in points if row.get("screened")],
                summary={
                    "screenedPointsCount": sum(row.get("screened", False) for row in points),
                    "liquefiablePointsCount": sum(row.get("liquefiable", False) for row in points),
                },
                notes=[note for _, _, out in screened for note in out["notes"]],
            )
        if fid == "soilSeismic.liquefactionMap":
            return result(
                summary={
                    "screenedPointsCount": len(points),
                    "liquefiableRangesCount": len(layers),
                    "maximumLpi": max(out["lpi"] for _, _, out in screened),
                    "pgaG": pga,
                },
                tables=[
                    table(
                        "Liquefaction screening map nodes",
                        [
                            ("borehole", "Borehole"),
                            ("xM", "X", "m"),
                            ("yM", "Y", "m"),
                            ("depth", "Depth", "mm"),
                            ("fs", "Factor of safety"),
                            ("liquefiable", "Liquefiable"),
                            ("reason", "Screening reason"),
                        ],
                        points,
                    ),
                    table(
                        "Liquefiable intervals",
                        [
                            ("borehole", "Borehole"),
                            ("top", "Top", "mm"),
                            ("bottom", "Bottom", "mm"),
                            ("soilType", "Soil type"),
                        ],
                        layers,
                    ),
                ],
                notes=[note for _, _, out in screened for note in out["notes"]],
            )
        if fid == "soilSeismic.postLiquefactionSettlement":
            strain_rows = {}
            for line_no, line in enumerate(values["strainRows"].splitlines(), 1):
                if not line.strip():
                    continue
                parts = [part.strip() for part in line.split(",")]
                if len(parts) != 2:
                    raise FeatureInputError(
                        f"Layer strain row {line_no} must be layer index, volumetric strain percent."
                    )
                try:
                    strain_rows[int(parts[0])] = float(parts[1])
                except ValueError:
                    raise FeatureInputError(f"Layer strain row {line_no} is invalid.") from None
            settlements = []
            for layer in layers:
                index = layer["layer"] + 1
                strain = strain_rows.get(index)
                if strain is None:
                    raise FeatureInputError(
                        f"Enter a post-liquefaction volumetric strain for layer {index} before estimating settlement."
                    )
                thick = (layer["bottom"] - layer["top"]) / 1000
                settlements.append(
                    {
                        "borehole": layer["borehole"],
                        "layer": index,
                        "thicknessM": thick,
                        "volumetricStrainPct": strain,
                        "settlementMm": thick * strain * 10,
                    }
                )
            if not settlements:
                return result(
                    summary={"postLiquefactionSettlementMm": 0.0, "liquefiableRangesCount": 0},
                    notes=[
                        "The selected screening found no liquefiable intervals; no post-liquefaction settlement is estimated."
                    ],
                )
            total_by_bh: dict[str, float] = {}
            for row in settlements:
                total_by_bh[row["borehole"]] = (
                    total_by_bh.get(row["borehole"], 0.0) + row["settlementMm"]
                )
            return result(
                summary={
                    "maximumSettlementMm": max(total_by_bh.values()),
                    "meanSettlementMm": sum(total_by_bh.values()) / len(total_by_bh),
                    "boreholesCount": len(total_by_bh),
                },
                tables=[
                    table(
                        "Volumetric-strain settlement estimate",
                        [
                            ("borehole", "Borehole"),
                            ("layer", "Layer"),
                            ("thicknessM", "Liquefied thickness", "m"),
                            ("volumetricStrainPct", "Volumetric strain", "%"),
                            ("settlementMm", "Settlement", "mm"),
                        ],
                        settlements,
                    )
                ],
                notes=[
                    "Settlement sums liquefied interval thickness × user-entered post-shaking volumetric strain; the strain must come from a compatible published correlation or cyclic test."
                ],
            )
        spread_rows = [
            {
                "borehole": bh.id,
                "xM": bh.x / 1000,
                "yM": bh.y / 1000,
                "lpi": out["lpi"],
                "category": out["category"],
                "liquefiableRanges": len(out["layers"]),
                "freeFaceDistanceM": values.get("freeFaceDistanceM"),
                "spreadScreen": "susceptible"
                if out["layers"] and out["lpi"] > 0
                else "no susceptible interval in screening",
            }
            for bh, _, out in screened
        ]
        return result_rows(
            "Lateral-spread susceptibility map",
            [
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("lpi", "LPI"),
                ("category", "LPI category"),
                ("liquefiableRanges", "Liquefiable ranges"),
                ("spreadScreen", "Screen"),
            ],
            spread_rows,
            summary={
                "susceptibleBoreholesCount": sum(
                    row["liquefiableRanges"] > 0 for row in spread_rows
                )
            },
            notes=[
                "The liquefaction engine supplies the susceptible layers and LPI. Lateral displacement needs free-face geometry, slope and a displacement correlation; this view reports screening locations only."
            ],
        )
    if fid in {
        "soilSeismic.designSpectrum",
        "soilSeismic.siteAmplification",
        "soilSeismic.amplificationFactor",
        "soilSeismic.soilProfileType",
    }:
        settings = ctx.settings()
        with in_force(ctx.root):
            if fid == "soilSeismic.soilProfileType":
                rows = [
                    {
                        "siteClass": cls,
                        "description": definition.description,
                        "vs30LowerMPerS": definition.vs30[0] if definition.vs30 else None,
                        "vs30UpperMPerS": definition.vs30[1] if definition.vs30 else None,
                    }
                    for cls, definition in __import__("saengine.codes.context", fromlist=["table"])
                    .table("seismic")
                    .siteClasses.items()
                ]
                return result_rows(
                    "Site class profile types",
                    [
                        ("siteClass", "Class"),
                        ("description", "Description"),
                        ("vs30LowerMPerS", "Vs30 lower", "m/s"),
                        ("vs30UpperMPerS", "Vs30 upper", "m/s"),
                    ],
                    rows,
                    summary={"siteClassesCount": len(rows)},
                    notes=[
                        "Class descriptions and velocity ranges are read from the active seismic code pack."
                    ],
                )
            from saengine.codes import context as code_context
            from saengine.fem import spectral_hazard

            site_class_id = settings.site.siteClass
            try:
                hazard = spectral_hazard.site_hazard(
                    settings.site.spectral,
                    site_class_id,
                    code_context.current(),
                    settings.site.zoneCoefficient,
                    settings.site.location,
                )
            except Exception as error:
                raise FeatureInputError(
                    f"The active pack could not build a site spectrum: {error}"
                ) from error
            if hazard is None:
                raise FeatureInputError(
                    "Enter mapped spectral values in project settings or use a pack with defined seismic zonation before calculating a design spectrum."
                )
            if fid == "soilSeismic.designSpectrum":
                periods = [0.0, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 3.0, 4.0]
                rows = [
                    {
                        "periodS": t,
                        "spectralAccelerationG": spectral_hazard.spectral_acceleration(
                            t, hazard, code_context.current()
                        ),
                    }
                    for t in periods
                ]
                return result_rows(
                    "Elastic design spectrum",
                    [("periodS", "Period", "s"), ("spectralAccelerationG", "Sa", "g")],
                    rows,
                    summary={
                        "sdsG": hazard.sds,
                        "sd1G": hazard.sd1,
                        "siteClass": site_class_id,
                        "longPeriodTransitionS": hazard.tl,
                        "source": hazard.source,
                    },
                    notes=[
                        "The two-period or entered multi-period spectrum is evaluated by the active code pack at 5% damping."
                    ],
                )
            if fid == "soilSeismic.siteAmplification":
                rules = code_context.table("seismic")
                cls = rules.siteClasses.get(site_class_id)
                if cls is None:
                    raise FeatureInputError(
                        f"Site class {site_class_id} has no amplification factors in the active pack."
                    )
                rows = [
                    {
                        "periodS": t,
                        "siteFactor": cls.S,
                        "spectralAccelerationG": spectral_hazard.spectral_acceleration(
                            t, hazard, code_context.current()
                        ),
                    }
                    for t in (0.0, 0.2, 0.5, 1.0, 2.0)
                ]
                return result_rows(
                    "Site amplification factors",
                    [
                        ("periodS", "Period", "s"),
                        ("siteFactor", "Class soil factor"),
                        ("spectralAccelerationG", "Site Sa", "g"),
                    ],
                    rows,
                    summary={
                        "siteClass": site_class_id,
                        "soilFactor": cls.S,
                        "vs30RangeMPerS": cls.vs30,
                    },
                    notes=[
                        "The site-class factor and design spectral ordinates come from the active pack; site-specific response analysis may be needed for special classes."
                    ],
                )
            return result(
                summary={
                    "siteClass": site_class_id,
                    "soilFactor": code_context.table("seismic").siteClasses[site_class_id].S,
                    "amplificationAtZeroPeriod": code_context.table("seismic")
                    .siteClasses[site_class_id]
                    .S,
                },
                tables=[
                    table(
                        "Site amplification factor",
                        [("parameter", "Parameter"), ("value", "Value")],
                        [
                            {"parameter": "Site class", "value": site_class_id},
                            {
                                "parameter": "Code-pack soil factor S",
                                "value": code_context.table("seismic").siteClasses[site_class_id].S,
                            },
                        ],
                    )
                ],
                notes=[
                    "The factor shown is the pack's class soil factor. Period-dependent amplification requires site response or a mapped-spectral coefficient table."
                ],
            )
    if fid == "soilSeismic.pgaContours":
        pga = values.get("pgaG")
        rows = [
            {
                "borehole": bh.id,
                "xM": bh.x / 1000,
                "yM": bh.y / 1000,
                "pgaG": pga,
                "source": "feature input" if pga else "report design setting",
            }
            for bh in report.boreholes
        ]
        if pga is None:
            pga = report.design.liquefaction.pga
            for row in rows:
                row["pgaG"] = pga
                row["source"] = "report design setting"
        if pga is None:
            raise FeatureInputError(
                "Enter PGA or set it in the Soil Report design options before mapping."
            )
        return result_rows(
            "PGA contour control nodes",
            [
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("pgaG", "PGA", "g"),
                ("source", "Source"),
            ],
            rows,
            summary={"controlPointsCount": len(rows), "pgaG": pga},
            notes=[
                "A single entered site PGA is repeated at each investigation point; a spatial hazard model is required to create varying contours."
            ],
        )
    if fid == "soilSeismic.amplificationFactor":
        from saengine.fem import spectra

        period = values["periodS"]
        settings = ctx.settings()
        with in_force(ctx.root):
            code_context = __import__("saengine.codes.context", fromlist=["table"])
            classes = code_context.table("seismic").siteClasses
            cls = classes.get(settings.site.siteClass)
            if cls is None:
                raise FeatureInputError(
                    "The entered site class has no amplification factors in the active pack."
                )
            factor = spectra.shape_factor(period, cls.shape) if cls.shape else cls.S
        return result(
            summary={
                "periodS": period,
                "amplificationFactor": factor,
                "siteClass": settings.site.siteClass,
            },
            tables=[
                table(
                    "Period-dependent amplification",
                    [("periodS", "Period", "s"), ("amplificationFactor", "Factor")],
                    [{"periodS": period, "amplificationFactor": factor}],
                )
            ],
            notes=[
                "Where the active pack defines spectral shape branches, its shape factor is evaluated; otherwise its class soil factor is returned."
            ],
        )
    raise FeatureInputError(
        "The requested seismic feature needs site-class, spectrum, shear-wave or record data."
    )


register_tab("soilSeismic", _handle, requires_project=_needs_project, fields=_fields)
