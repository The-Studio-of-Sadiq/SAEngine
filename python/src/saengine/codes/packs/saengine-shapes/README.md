# SAEngine shapes

Presets of the parametric shapes built into SAEngine (`saengine.library.shapes`): one file per
preset in `templates/`, each a name, a description and the shape's parameters as the modeller's
Generate panel edits them. The seven files named after a shape (`space-truss.json`,
`plane-truss.json`, `arch.json`, `dome.json`, `barrel-vault.json`, `cable-net.json`,
`portal-frame.json`) are the
starting values of the Generate panel (`saengine.library.templates._SHAPES`, checked by the
tests); the others are named variants.

This package ships built into SAEngine and is published, as a read-only mirror, in the
structure templates repository of the marketplace (docs/marketplace-plan.md). Change it here,
then mirror it with `scripts/marketplace/mirror_packages.py`.

Licence: CC-BY-4.0. Member types are placeholders (`MEMBER`): pick the object types of your
model when you apply a preset.
