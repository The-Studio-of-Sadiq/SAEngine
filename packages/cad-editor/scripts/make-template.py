"""Writes the empty drawing SAEngine opens for a new plan (assets/templates/acadiso.dxf).

mlightcad loads new drawings from a template; its default comes from an unlicensed asset
repository, so SAEngine generates its own with ezdxf (MIT): metric (mm) units with the
standard linetypes, text styles and dimension styles.

    python scripts/make-template.py
"""

from pathlib import Path

import ezdxf
from ezdxf import units

doc = ezdxf.new("R2018", setup=True, units=units.MM)
doc.header["$MEASUREMENT"] = 1  # metric
target = Path(__file__).resolve().parents[1] / "assets" / "templates" / "acadiso.dxf"
target.parent.mkdir(parents=True, exist_ok=True)
doc.saveas(target)
print(f"wrote {target}")
