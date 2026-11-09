"""Table model of floor (in-structure) response spectra (alpha 9 L5): ``floorSpectra``.

Read by :mod:`saengine.fem.floor_spectra`; this module holds no numbers:

- ``methods``: the methods the pack allows, the first its default: ``timeHistory`` (the floor
  acceleration histories of the run's time-history cases through damped oscillators) and
  ``spectrumToSpectrum`` (the direct method: the ground spectrum as a power spectral density,
  through the modal transfer function of the floor and the component's oscillator, with a
  peak factor);
- ``broadening``: the peaks widened by ± this share of their period;
- ``damping``: the component damping ratios computed, ``componentDamping`` the one the
  nonstructural components use;
- ``direct``: the direct method's strong-motion duration, iterations and the structure's
  damping (none: the run's spectrum damping);
- ``components``: how a component's force follows from the floor spectrum (method
  ``spectralAcceleration``: F = Sa(Tc) Wc Ic / Rc within the nonstructural table's bounds; a
  component of amplification above ``flexibleAlpha`` takes the spectrum's peak, the others
  Sa at ``rigidPeriod``).

Every number is the pack's; its VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from saengine.codes.tables import Positive, Share, TableModel, _Group

Method = Literal["timeHistory", "spectrumToSpectrum"]


class DirectMethod(_Group):
    """``spectrumToSpectrum``: the ground spectrum's power spectral density (iterated until
    its oscillator peaks meet the spectrum), the floor's modal transfer function."""

    duration: Positive = Field(description="Strong-motion duration of the peak factor [s].")
    iterations: int = Field(ge=1, le=50, description="Iterations of the density.")
    structureDamping: Share | None = Field(
        default=None, description="Modal damping of the structure; none: the run's spectrum's."
    )


class ComponentForce(_Group):
    """``spectralAcceleration``: F = Sa(Tc) Wc Ic / Rc (``divideByR``), within the
    nonstructural table's least and largest force (``bounds``)."""

    method: Literal["spectralAcceleration"] = "spectralAcceleration"
    rigidPeriod: Positive = Field(description="Tc of a rigid component [s].")
    flexibleAlpha: Positive = Field(
        description="A component whose amplification is above this is flexible: the peak of "
        "the floor spectrum (its period is not known)."
    )
    divideByR: bool = Field(description="Divide by the component's response modification.")
    bounds: bool = Field(description="Keep the nonstructural table's least and largest force.")


class FloorSpectraTable(TableModel):
    """Floor response spectra (see the module notes)."""

    methods: list[Method] = Field(min_length=1, description="Allowed methods, default first.")
    broadening: float = Field(ge=0, lt=1, description="Peak broadening ± share of the period.")
    damping: list[Share] = Field(min_length=1, description="Component damping ratios computed.")
    componentDamping: Share = Field(description="The damping the components' forces use.")
    periods: tuple[Positive, Positive, int] = Field(
        description="Periods of the spectra: (first, last, count) on a log scale [s]."
    )
    direct: DirectMethod | None = None
    components: ComponentForce | None = None
