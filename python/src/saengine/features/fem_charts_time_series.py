"""Analysis Charts - Time Series tab: transient extraction, DSP filtering, FFT/PSD, damping identification, and audio/CSV export."""

from __future__ import annotations

import csv
import io
import math
import struct
import wave
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.fem_common import (
    export_fem_file,
    parse_series,
    require_results,
    results_dir,
)
from saengine.fem import result_tables, spectral_matching

_DEFAULT_SIGNAL = "0.0, 1.2, 2.8, 1.9, -0.8, -2.5, -1.7, 0.6, 2.1, 1.3, -0.5, -1.8, -1.1, 0.4, 1.4, 0.8, -0.3, -1.0, -0.6, 0.2"


def _load_or_parse_series(
    ctx: FeatureContext, raw: str, dt: float
) -> tuple[float, np.ndarray, str]:
    """Use transient results from 08 FEM/model.results if available, else parse input signal."""
    out = results_dir(ctx)
    if out is not None:
        from opensees_studio.services.result_store import load_manifest, load_results
        from opensees_studio.services.results import TransientResults

        manifest = load_manifest(out)
        for entry in manifest.get("cases", []):
            if entry.get("result_type") == "TransientResults":
                res = load_results(entry, out)
                if isinstance(res, TransientResults) and res.node_disp:
                    first_node = next(iter(res.node_disp.values()))
                    arr = np.asarray(first_node, dtype=float)
                    sig = arr[:, 0] if arr.ndim > 1 else arr
                    t_arr = (
                        np.asarray(res.time, dtype=float)
                        if getattr(res, "time", None) is not None
                        else None
                    )
                    dt_eff = (
                        float(np.median(np.diff(t_arr)))
                        if t_arr is not None and len(t_arr) > 1
                        else dt
                    )
                    return dt_eff, sig, f"Transient result ({entry.get('case_name', '')})"
    dt_p, sig_p = parse_series(raw, dt, "Time series")
    return dt_p, sig_p, "Input time series"


@feature(
    "femChartsTimeSeries.selectNode",
    "Select Node",
    part="fem",
    fields=[number("nodeId", "Target node ID (0 = first available)", 0, min=0)],
    requires_project=True,
)
def select_node(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select a node from transient results and list its displacement time-history peaks."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    th = [
        e
        for e in idx.get("results", [])
        if any(t["id"].startswith("history:") for t in e.get("tables", []))
    ]
    if not th:
        raise FeatureInputError("No transient time-history results found in 08 FEM/model.results.")
    tbl = result_tables.result_table(out_dir, model_path, th[0]["key"], "history:0")
    cols = [c["key"] for c in tbl.get("columns", [])]
    rows = [dict(zip(cols, r, strict=False)) for r in tbl.get("rows", [])[:30]]
    return result(
        summary={"case": th[0]["label"], "nodesRecorded": len(tbl.get("rows", []))},
        tables=[
            table(
                "Transient node peak displacements",
                [(c["key"], c["title"]) for c in tbl.get("columns", [])],
                rows,
            )
        ],
        notes=["Selects recorded DOF time history from solved transient cases."],
    )


@feature(
    "femChartsTimeSeries.selectResult",
    "Select Result",
    part="fem",
    fields=[
        select(
            "dof",
            "Result component",
            [
                ("Ux", "X displacement"),
                ("Uy", "Y displacement"),
                ("Uz", "Z displacement"),
                ("Ax", "X acceleration"),
            ],
            "Ux",
        )
    ],
    requires_project=True,
)
def select_result(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Choose the displacement or acceleration DOF component to extract over time."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    th = [
        e
        for e in idx.get("results", [])
        if any(t["id"].startswith("history:") for t in e.get("tables", []))
    ]
    if not th:
        raise FeatureInputError("No transient time-history results found in 08 FEM/model.results.")
    rows = [{"case": str(e["label"]), "selectedComponent": values["dof"]} for e in th]
    return result(
        summary={"component": values["dof"], "transientCases": len(th)},
        tables=[
            table(
                "Selected time-history component",
                [("case", "Case"), ("selectedComponent", "Component")],
                rows,
            )
        ],
        notes=["Extracts the requested DOF channel from transient HDF5 outputs."],
    )


@feature(
    "femChartsTimeSeries.sampleRate",
    "Sample Rate",
    part="fem",
    fields=[number("dtS", "Sampling interval Δt", 0.01, unit="s", min=0.0005, max=1.0)],
    requires_project=False,
)
def sample_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute sampling frequency fs and Nyquist frequency f_Nyq for time-history processing."""
    dt = values["dtS"]
    fs = 1.0 / dt
    f_nyq = 0.5 * fs
    rows = [{"dtS": dt, "samplingHz": fs, "nyquistHz": f_nyq}]
    return result(
        summary={"dtS": dt, "samplingRateHz": fs, "nyquistFreqHz": f_nyq},
        tables=[
            table(
                "Sampling rate & aliasing limits",
                [("dtS", "Δt", "s"), ("samplingHz", "fs", "Hz"), ("nyquistHz", "f_Nyq", "Hz")],
                rows,
            )
        ],
        notes=["Signals above the Nyquist frequency f_Nyq = 1/(2Δt) alias into lower frequencies."],
    )


@feature(
    "femChartsTimeSeries.timeWindow",
    "Time Window",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        number("tStartS", "Window start", 0.04, unit="s", min=0.0),
        number("tEndS", "Window end", 0.30, unit="s", min=0.01),
    ],
    requires_project=False,
)
def time_window(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Slice a time series to [tStart, tEnd] and report windowed peak and RMS values."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    t = np.arange(len(sig)) * dt
    mask = (t >= values["tStartS"]) & (t <= values["tEndS"])
    if not np.any(mask):
        raise FeatureInputError("No samples fall within the specified time window.")
    sub = sig[mask]
    t_sub = t[mask]
    rows = [
        {"tS": float(ti), "value": float(vi)} for ti, vi in zip(t_sub[:30], sub[:30], strict=True)
    ]
    return result(
        summary={
            "source": src,
            "samplesKept": int(sub.size),
            "windowPeak": float(np.max(np.abs(sub))),
            "windowRms": float(np.sqrt(np.mean(sub**2))),
        },
        tables=[table("Windowed time series", [("tS", "Time", "s"), ("value", "Value")], rows)],
        notes=["Restricts downstream spectral and peak statistics to the selected duration."],
    )


@feature(
    "femChartsTimeSeries.filterSignal",
    "Filter Signal",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        select(
            "band", "Filter type", [("lowpass", "Low-pass"), ("highpass", "High-pass")], "lowpass"
        ),
        number("cutoffHz", "Cutoff frequency", 5.0, unit="Hz", min=0.05),
    ],
    requires_project=False,
)
def filter_signal(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply zero-phase FFT brick-wall/tapered frequency filter to a response time series."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    freqs = np.fft.rfftfreq(len(sig), d=dt)
    spec = np.fft.rfft(sig)
    fc = values["cutoffHz"]
    if values["band"] == "lowpass":
        spec = np.where(freqs <= fc, spec, 0.0)
    else:
        spec = np.where(freqs >= fc, spec, 0.0)
    filtered = np.fft.irfft(spec, n=len(sig))
    rows = [
        {"step": i, "tS": i * dt, "raw": float(sig[i]), "filtered": float(filtered[i])}
        for i in range(min(25, len(sig)))
    ]
    return result(
        summary={
            "source": src,
            "cutoffHz": fc,
            "rawPeak": float(np.max(np.abs(sig))),
            "filteredPeak": float(np.max(np.abs(filtered))),
        },
        tables=[
            table(
                "Filtered signal comparison",
                [("step", "Step"), ("tS", "t", "s"), ("raw", "Raw"), ("filtered", "Filtered")],
                rows,
            )
        ],
        notes=["Zero-phase Fourier filter preserves signal phase alignment."],
    )


@feature(
    "femChartsTimeSeries.baselineCorrect",
    "Baseline Correct",
    part="fem",
    fields=[
        text("series", "Acceleration/response series", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        number("polyOrder", "Detrend polynomial order", 2, min=1, max=5),
    ],
    requires_project=False,
)
def baseline_correct(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Remove polynomial drift baseline from a time-history signal."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    corrected = spectral_matching.baseline_corrected(dt, sig, order=int(values["polyOrder"]))
    rows = [
        {"tS": i * dt, "raw": float(sig[i]), "corrected": float(corrected[i])}
        for i in range(min(25, len(sig)))
    ]
    return result(
        summary={
            "source": src,
            "rawMean": float(np.mean(sig)),
            "correctedMean": float(np.mean(corrected)),
        },
        tables=[
            table(
                "Baseline-corrected series",
                [("tS", "Time", "s"), ("raw", "Raw"), ("corrected", "Corrected")],
                rows,
            )
        ],
        notes=["Uses saengine.fem.spectral_matching.baseline_corrected."],
    )


@feature(
    "femChartsTimeSeries.fftSpectrum",
    "FFT Spectrum",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
    ],
    requires_project=False,
)
def fft_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute single-sided Fast Fourier Transform amplitude spectrum and dominant frequency."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    n = len(sig)
    freqs = np.fft.rfftfreq(n, d=dt)
    amp = 2.0 * np.abs(np.fft.rfft(sig - np.mean(sig))) / max(n, 1)
    peak_idx = int(np.argmax(amp[1:]) + 1) if len(amp) > 1 else 0
    rows = [{"freqHz": float(f), "amplitude": float(a)} for f, a in zip(freqs, amp, strict=True)]
    return result(
        summary={
            "source": src,
            "dominantFreqHz": float(freqs[peak_idx]),
            "peakAmplitude": float(amp[peak_idx]),
        },
        tables=[
            table(
                "FFT amplitude spectrum",
                [("freqHz", "Frequency", "Hz"), ("amplitude", "Amplitude")],
                rows[:30],
            )
        ],
        notes=["Mean-removed single-sided Fourier magnitude spectrum."],
    )


@feature(
    "femChartsTimeSeries.smoothSeries",
    "Smooth Series",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        number("windowSamples", "Moving-average window N", 3, min=2, max=25),
    ],
    requires_project=False,
)
def smooth_series(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Smooth high-frequency numerical noise with a centered moving-average kernel."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    w = int(values["windowSamples"])
    kernel = np.ones(w, dtype=float) / w
    smoothed = np.convolve(sig, kernel, mode="same")
    rows = [
        {"tS": i * dt, "raw": float(sig[i]), "smoothed": float(smoothed[i])}
        for i in range(min(25, len(sig)))
    ]
    return result(
        summary={"source": src, "windowSamples": w, "smoothedStd": float(np.std(smoothed))},
        tables=[
            table(
                "Moving-average smoothed series",
                [("tS", "t", "s"), ("raw", "Raw"), ("smoothed", "Smoothed")],
                rows,
            )
        ],
        notes=["Symmetric boxcar convolution reduces high-frequency jitter."],
    )


@feature(
    "femChartsTimeSeries.overlaySeries",
    "Overlay Series",
    part="fem",
    fields=[],
    requires_project=True,
)
def overlay_series(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay peak responses across multiple transient time-history cases."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    th = [
        e
        for e in idx.get("results", [])
        if any(t["id"].startswith("history:") for t in e.get("tables", []))
    ]
    if not th:
        raise FeatureInputError("No transient time-history results found in 08 FEM/model.results.")
    rows = [{"case": str(e["label"]), "key": str(e["key"])} for e in th]
    return result(
        summary={"overlaidCases": len(rows)},
        tables=[
            table("Overlaid transient series", [("case", "Case"), ("key", "Result Key")], rows)
        ],
        notes=["Groups solved transient response histories for visual comparison."],
    )


@feature(
    "femChartsTimeSeries.cursorRead",
    "Cursor Read",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        number("cursorTimeS", "Query time t*", 0.11, unit="s", min=0.0),
    ],
    requires_project=False,
)
def cursor_read(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Interpolate exact time-series value and instantaneous slope at a cursor timestamp."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    t = np.arange(len(sig)) * dt
    tq = min(max(values["cursorTimeS"], 0.0), float(t[-1]))
    val = float(np.interp(tq, t, sig))
    grad = float(np.interp(tq, t, np.gradient(sig, dt))) if len(sig) > 1 else 0.0
    rows = [{"cursorTimeS": tq, "value": val, "slopePerS": grad}]
    return result(
        summary={"source": src, "cursorTimeS": tq, "interpolatedValue": val, "slopePerS": grad},
        tables=[
            table(
                "Shared cursor readout",
                [("cursorTimeS", "t*", "s"), ("value", "y(t*)"), ("slopePerS", "dy/dt")],
                rows,
            )
        ],
        notes=["Linearly interpolates value and central-difference derivative at t*."],
    )


@feature(
    "femChartsTimeSeries.differencePlot",
    "Difference Plot",
    part="fem",
    fields=[
        text("seriesA", "Series A", _DEFAULT_SIGNAL),
        text(
            "seriesB",
            "Series B",
            "0.0, 1.0, 2.4, 1.7, -0.6, -2.2, -1.5, 0.5, 1.8, 1.1, -0.4, -1.6, -0.9, 0.3, 1.2, 0.7, -0.2, -0.8, -0.5, 0.1",
        ),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
    ],
    requires_project=False,
)
def difference_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute pointwise difference (A - B) and RMSE between two synchronized time series."""
    dt, a = parse_series(values["seriesA"], values["dtS"], "Series A")
    _, b = parse_series(values["seriesB"], values["dtS"], "Series B")
    n = min(len(a), len(b))
    diff = a[:n] - b[:n]
    rmse = float(np.sqrt(np.mean(diff**2)))
    rows = [
        {"tS": i * dt, "a": float(a[i]), "b": float(b[i]), "diff": float(diff[i])}
        for i in range(min(25, n))
    ]
    return result(
        summary={"samples": n, "maxAbsDiff": float(np.max(np.abs(diff))), "rmse": rmse},
        tables=[
            table(
                "Time-series difference (A - B)",
                [("tS", "t", "s"), ("a", "A"), ("b", "B"), ("diff", "A - B")],
                rows,
            )
        ],
        notes=["Computes residual difference series and root-mean-square error."],
    )


@feature(
    "femChartsTimeSeries.exportSeries",
    "Export Series",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        text("filename", "Output CSV filename", "time-series.csv"),
    ],
    requires_project=True,
)
def export_series(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export time-history signal samples to CSV in 08 FEM/exports/."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_s", "value"])
    for i, v in enumerate(sig):
        w.writerow([round(i * dt, 6), float(v)])
    path = export_fem_file(ctx, values["filename"].strip() or "time-series.csv", buf.getvalue())
    return result(
        summary={"source": src, "samples": len(sig), "exportPath": str(path)},
        tables=[
            table(
                "Exported time-series preview",
                [("tS", "t", "s"), ("val", "Value")],
                [{"tS": i * dt, "val": float(v)} for i, v in enumerate(sig[:15])],
            )
        ],
        notes=[f"Series exported to {path}"],
    )


@feature(
    "femChartsTimeSeries.powerSpectrum",
    "Power Spectrum",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
    ],
    requires_project=False,
)
def power_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute one-sided Power Spectral Density (PSD) S(f) via periodogram."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    n = len(sig)
    s0 = sig - np.mean(sig)
    freqs = np.fft.rfftfreq(n, d=dt)
    psd = (dt / max(n, 1)) * (np.abs(np.fft.rfft(s0)) ** 2) * 2.0
    peak_i = int(np.argmax(psd))
    rows = [{"freqHz": float(f), "psd": float(p)} for f, p in zip(freqs, psd, strict=True)]
    return result(
        summary={"source": src, "peakFreqHz": float(freqs[peak_i]), "peakPsd": float(psd[peak_i])},
        tables=[
            table(
                "Power spectral density (PSD)",
                [("freqHz", "Frequency", "Hz"), ("psd", "PSD", "unit²/Hz")],
                rows[:30],
            )
        ],
        notes=["Parseval-normalized one-sided periodogram PSD."],
    )


@feature(
    "femChartsTimeSeries.transferFunction",
    "Transfer Function",
    part="fem",
    fields=[
        text("inputSeries", "Base input signal x(t)", _DEFAULT_SIGNAL),
        text(
            "outputSeries",
            "Roof output signal y(t)",
            "0.0, 1.8, 4.1, 2.9, -1.2, -3.7, -2.5, 0.9, 3.2, 2.0, -0.7, -2.7, -1.6, 0.6, 2.1, 1.2, -0.4, -1.5, -0.9, 0.3",
        ),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
    ],
    requires_project=False,
)
def transfer_function(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute frequency-domain transfer function magnitude |H(f)| = |Y(f)/X(f)| and phase."""
    dt, x = parse_series(values["inputSeries"], values["dtS"], "Input series")
    _, y = parse_series(values["outputSeries"], values["dtS"], "Output series")
    n = min(len(x), len(y))
    freqs = np.fft.rfftfreq(n, d=dt)
    xf = np.fft.rfft(x[:n] - np.mean(x[:n]))
    yf = np.fft.rfft(y[:n] - np.mean(y[:n]))
    denom = np.where(np.abs(xf) > 1e-9, xf, 1e-9 + 0j)
    h = yf / denom
    mag = np.abs(h)
    phase = np.degrees(np.angle(h))
    rows = [
        {"freqHz": float(f), "gain": float(m), "phaseDeg": float(p)}
        for f, m, p in zip(freqs, mag, phase, strict=True)
    ]
    return result(
        summary={
            "samples": n,
            "maxGain": float(np.max(mag[1:])) if len(mag) > 1 else float(mag[0]),
        },
        tables=[
            table(
                "Transfer function H(f)",
                [("freqHz", "Freq", "Hz"), ("gain", "|H(f)|"), ("phaseDeg", "Phase", "°")],
                rows[:25],
            )
        ],
        notes=["Identifies structural amplification peaks and resonance phase shifts."],
    )


@feature(
    "femChartsTimeSeries.coherencePlot",
    "Coherence Plot",
    part="fem",
    fields=[
        text("seriesA", "Channel A", _DEFAULT_SIGNAL),
        text(
            "seriesB",
            "Channel B",
            "0.0, 1.5, 3.4, 2.2, -1.0, -3.0, -2.0, 0.7, 2.6, 1.6, -0.6, -2.1, -1.3, 0.5, 1.7, 1.0, -0.4, -1.2, -0.7, 0.2",
        ),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
    ],
    requires_project=False,
)
def coherence_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Welch-segment magnitude-squared coherence γ²(f) between two output channels."""
    dt, a = parse_series(values["seriesA"], values["dtS"], "Channel A")
    _, b = parse_series(values["seriesB"], values["dtS"], "Channel B")
    n = min(len(a), len(b))
    seg = max(4, n // 2)
    step = max(2, seg // 2)
    sxx = syy = sxy = None
    for start in range(0, n - seg + 1, step):
        fa = np.fft.rfft(a[start : start + seg])
        fb = np.fft.rfft(b[start : start + seg])
        sxx = (np.abs(fa) ** 2) if sxx is None else (sxx + np.abs(fa) ** 2)
        syy = (np.abs(fb) ** 2) if syy is None else (syy + np.abs(fb) ** 2)
        sxy = (fa * np.conj(fb)) if sxy is None else (sxy + fa * np.conj(fb))
    freqs = np.fft.rfftfreq(seg, d=dt)
    coh = np.where((sxx * syy) > 1e-18, (np.abs(sxy) ** 2) / (sxx * syy), 0.0)
    rows = [{"freqHz": float(f), "coherence": float(c)} for f, c in zip(freqs, coh, strict=True)]
    return result(
        summary={"meanCoherence": float(np.mean(coh)), "peakCoherence": float(np.max(coh))},
        tables=[
            table(
                "Magnitude-squared coherence γ²(f)",
                [("freqHz", "Freq", "Hz"), ("coherence", "γ²(f)")],
                rows,
            )
        ],
        notes=["Coherence near 1.0 indicates linear phase-locked response between channels."],
    )


@feature(
    "femChartsTimeSeries.responseSpectrum",
    "Response Spectrum",
    part="fem",
    fields=[
        text("series", "Acceleration time history [g]", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
        number("damping", "Damping ratio ξ", 0.05, min=0.005, max=0.30),
    ],
    requires_project=False,
)
def response_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute SDOF pseudo-spectral acceleration Sa(T) and displacement Sd(T) from an accelerogram."""
    dt, acc, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    periods = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0]
    sa = spectral_matching.spectrum(dt, acc, periods, values["damping"])
    sd = spectral_matching.displacements(dt, acc, periods, values["damping"])
    rows = [
        {"periodS": t, "saG": float(a), "sdMm": float(d) * 9806.65}
        for t, a, d in zip(periods, sa, sd, strict=True)
    ]
    return result(
        summary={
            "source": src,
            "peakSaG": float(np.max(sa)),
            "maxSdMm": max(r["sdMm"] for r in rows),
        },
        tables=[
            table(
                "Computed elastic response spectrum",
                [("periodS", "Period T", "s"), ("saG", "Sa", "g"), ("sdMm", "Sd", "mm")],
                rows,
            )
        ],
        notes=[
            "Exact piecewise-linear SDOF Duhamel integration via saengine.fem.spectral_matching."
        ],
    )


@feature(
    "femChartsTimeSeries.logDecrypt",
    "Log Decrypt",
    part="fem",
    fields=[
        number("peak1", "First cycle peak x1", 10.0, min=0.01),
        number("peakN", "Peak after N cycles xN", 4.5, min=0.001),
        number("cycles", "Number of cycles N", 3, min=1, max=100),
    ],
    requires_project=False,
)
def log_decrypt(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate logarithmic decrement δ and equivalent viscous damping ratio ξ from free decay."""
    if values["peakN"] >= values["peak1"]:
        raise FeatureInputError("Decayed peak xN must be smaller than initial peak x1.")
    delta = (1.0 / values["cycles"]) * math.log(values["peak1"] / values["peakN"])
    xi = delta / math.sqrt(4.0 * math.pi**2 + delta**2)
    rows = [{"delta": delta, "dampingRatio": xi, "dampingPct": xi * 100.0}]
    return result(
        summary={"logDecrement": delta, "dampingRatio": xi, "dampingPct": xi * 100.0},
        tables=[
            table(
                "Logarithmic decrement damping fit",
                [("delta", "δ"), ("dampingRatio", "ξ"), ("dampingPct", "ξ [%]")],
                rows,
            )
        ],
        notes=["δ = (1/N) ln(x1/xN) and ξ = δ / √(4π² + δ²)."],
    )


@feature(
    "femChartsTimeSeries.halfPower",
    "Half Power",
    part="fem",
    fields=[
        number("fResonanceHz", "Resonant peak frequency fn", 2.40, unit="Hz", min=0.05),
        number("fLowHz", "Lower -3 dB frequency f1", 2.28, unit="Hz", min=0.01),
        number("fHighHz", "Upper -3 dB frequency f2", 2.52, unit="Hz", min=0.02),
    ],
    requires_project=False,
)
def half_power(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine modal damping ratio ξ via half-power (-3 dB) bandwidth method."""
    if values["fHighHz"] <= values["fLowHz"]:
        raise FeatureInputError("Upper half-power frequency f2 must exceed lower frequency f1.")
    bw = values["fHighHz"] - values["fLowHz"]
    xi = bw / (2.0 * values["fResonanceHz"])
    q_fac = 1.0 / (2.0 * xi)
    rows = [
        {"bandwidthHz": bw, "dampingRatio": xi, "dampingPct": xi * 100.0, "qualityFactorQ": q_fac}
    ]
    return result(
        summary={"bandwidthHz": bw, "dampingRatio": xi, "dampingPct": xi * 100.0},
        tables=[
            table(
                "Half-power bandwidth damping",
                [
                    ("bandwidthHz", "Δf", "Hz"),
                    ("dampingRatio", "ξ"),
                    ("dampingPct", "ξ [%]"),
                    ("qualityFactorQ", "Q"),
                ],
                rows,
            )
        ],
        notes=["ξ = (f2 - f1) / (2 fn) at 1/√2 of peak amplitude."],
    )


@feature(
    "femChartsTimeSeries.dampingFit",
    "Damping Fit",
    part="fem",
    fields=[
        number("freq1Hz", "Mode 1 frequency f1", 1.2, unit="Hz", min=0.05),
        number("freq2Hz", "Mode 2 frequency f2", 4.5, unit="Hz", min=0.1),
        number("damping1", "Target damping ξ1", 0.05, min=0.005, max=0.3),
        number("damping2", "Target damping ξ2", 0.05, min=0.005, max=0.3),
    ],
    requires_project=False,
)
def damping_fit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Solve Rayleigh damping coefficients (αM, βK) matching target damping at two frequencies."""
    w1 = 2.0 * math.pi * values["freq1Hz"]
    w2 = 2.0 * math.pi * values["freq2Hz"]
    if abs(w2 - w1) < 1e-6:
        raise FeatureInputError("Frequencies f1 and f2 must be distinct.")
    z1, z2 = values["damping1"], values["damping2"]
    beta = 2.0 * (z2 * w2 - z1 * w1) / (w2**2 - w1**2)
    alpha = 2.0 * w1 * z1 - beta * w1**2
    rows = [
        {
            "freqHz": values["freq1Hz"],
            "omegaRadS": w1,
            "dampingPct": (alpha / (2 * w1) + beta * w1 / 2) * 100.0,
        },
        {
            "freqHz": 0.5 * (values["freq1Hz"] + values["freq2Hz"]),
            "omegaRadS": 0.5 * (w1 + w2),
            "dampingPct": (alpha / (w1 + w2) + beta * (w1 + w2) / 4) * 100.0,
        },
        {
            "freqHz": values["freq2Hz"],
            "omegaRadS": w2,
            "dampingPct": (alpha / (2 * w2) + beta * w2 / 2) * 100.0,
        },
    ]
    return result(
        summary={"massAlpha": alpha, "stiffnessBeta": beta},
        tables=[
            table(
                "Rayleigh damping C = αM + βK fit",
                [
                    ("freqHz", "Freq", "Hz"),
                    ("omegaRadS", "ω", "rad/s"),
                    ("dampingPct", "ξ(ω)", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Exact 2-point Rayleigh fit across [f1, f2]; intermediate modes experience slightly lower damping."
        ],
    )


@feature(
    "femChartsTimeSeries.exportAudio",
    "Export Audio",
    part="fem",
    fields=[
        text("series", "Vibration signal", _DEFAULT_SIGNAL),
        number("sampleRateHz", "Audio sample rate", 8000, unit="Hz", min=1000, max=48000),
        text("filename", "WAV filename", "vibration-sonification.wav"),
    ],
    requires_project=True,
)
def export_audio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sonify structural vibration time series into a 16-bit PCM WAV file in 08 FEM/exports/."""
    _, sig, src = _load_or_parse_series(ctx, values["series"], 0.02)
    peak = float(np.max(np.abs(sig))) or 1.0
    norm = np.clip(sig / peak, -1.0, 1.0)
    # Repeat short sequences so audio duration is audible
    tiled = np.tile(norm, max(1, int(values["sampleRateHz"] // max(len(norm), 1))))
    pcm = (tiled * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(values["sampleRateHz"]))
        wf.writeframes(struct.pack(f"<{len(pcm)}h", *pcm.tolist()))
    path = export_fem_file(
        ctx, values["filename"].strip() or "vibration-sonification.wav", buf.getvalue()
    )
    return result(
        summary={"source": src, "samplesWritten": len(pcm), "wavPath": str(path)},
        tables=[
            table(
                "WAV audio export",
                [("item", "Property"), ("val", "Value")],
                [
                    {"item": "Sample rate [Hz]", "val": int(values["sampleRateHz"])},
                    {"item": "Samples", "val": len(pcm)},
                ],
            )
        ],
        notes=[f"16-bit PCM WAV written to {path}"],
    )


@feature(
    "femChartsTimeSeries.timePeakSummary",
    "Time Peak Summary",
    part="fem",
    fields=[
        text("series", "Signal values", _DEFAULT_SIGNAL),
        number("dtS", "Time step Δt", 0.02, unit="s", min=0.001),
    ],
    requires_project=False,
)
def time_peak_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize positive peak, negative peak, occurrence times, and RMS of a time history."""
    dt, sig, src = _load_or_parse_series(ctx, values["series"], values["dtS"])
    i_max, i_min = int(np.argmax(sig)), int(np.argmin(sig))
    rows = [
        {"metric": "Peak positive", "value": float(sig[i_max]), "timeS": i_max * dt},
        {"metric": "Peak negative", "value": float(sig[i_min]), "timeS": i_min * dt},
        {"metric": "RMS", "value": float(np.sqrt(np.mean(sig**2))), "timeS": 0.0},
    ]
    return result(
        summary={
            "source": src,
            "maxPos": float(sig[i_max]),
            "minNeg": float(sig[i_min]),
            "tMaxPosS": i_max * dt,
            "tMinNegS": i_min * dt,
        },
        tables=[
            table(
                "Time-history peak summary",
                [("metric", "Metric"), ("value", "Value"), ("timeS", "Time", "s")],
                rows,
            )
        ],
        notes=["Reports extreme positive and negative ordinates with timestamps."],
    )
