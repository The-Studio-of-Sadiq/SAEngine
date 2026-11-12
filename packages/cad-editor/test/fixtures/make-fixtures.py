"""Writes test/fixtures/dimensions.dxf with ezdxf: two rotated (DIMLINEAR) dimensions and one
true aligned (DIMALIGNED, type 1) dimension, as AutoCAD stores them.

    python test/fixtures/make-fixtures.py
"""

from pathlib import Path

import ezdxf
from ezdxf import units

doc = ezdxf.new("R2018", setup=True, units=units.MM)
msp = doc.modelspace()
msp.add_linear_dim(base=(0, -1000), p1=(0, 0), p2=(6000, 0)).render()  # rotated 0°
msp.add_linear_dim(base=(-800, 0), p1=(0, 0), p2=(0, 5000), angle=90).render()  # rotated 90°
aligned = msp.add_aligned_dim(p1=(0, 0), p2=(3000, 4000), distance=500)
aligned.dimension.dxf.dimtype = 1 | 32  # ezdxf writes aligned dims as rotated; make it a true aligned one
aligned.render()
doc.saveas(Path(__file__).with_name("dimensions.dxf"))
