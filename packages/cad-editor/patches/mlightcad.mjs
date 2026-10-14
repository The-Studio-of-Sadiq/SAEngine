// Source patches for mlightcad, applied at bundle time. Each `find` must occur exactly once in
// the named file, so an upgrade that changes the code fails the build instead of silently
// dropping a fix. Remove a patch once the fix ships upstream.

const ALIGNED = 'entity/dimension/AcDbAlignedDimension.js';

export const PATCHES = [
	{
		// Rotated (DIMLINEAR) dimensions lost their extension-line points (DXF 13/14) on load and
		// were saved without the AcDbAlignedDimension subclass. Per the DXF reference (and as
		// AutoCAD and ezdxf write it), linear dimensions keep 13/14/50/52 in AcDbAlignedDimension,
		// followed by an empty AcDbRotatedDimension subclass for rotated ones.
		file: ALIGNED,
		description: 'read rotated dimensions from the AcDbAlignedDimension subclass',
		find: `        _super.prototype.dxfInFields.call(this, filer);
        filer.atSubclassData(this.dxfSubclassMarker);`,
		replace: `        _super.prototype.dxfInFields.call(this, filer);
        if (!filer.atSubclassData('AcDbAlignedDimension')) {
            // Files saved by unpatched mlightcad carry only the derived marker.
            filer.atSubclassData(this.dxfSubclassMarker);
        }`,
	},
	{
		file: ALIGNED,
		description: 'read through the empty AcDbRotatedDimension subclass',
		find: `                case 100:
                    filer.pushBackItem(item);`,
		replace: `                case 100:
                    if (item.value === 'AcDbRotatedDimension') {
                        break;
                    }
                    filer.pushBackItem(item);`,
	},
	{
		file: ALIGNED,
		description: 'write AcDbAlignedDimension (+ empty AcDbRotatedDimension) like AutoCAD',
		find: `        filer.writeSubclassMarker(this.dxfSubclassMarker);
        filer.writePoint3d(13, this.xLine1Point);
        filer.writePoint3d(14, this.xLine2Point);
        filer.writePoint3d(15, this.dimLinePoint);
        filer.writeAngle(50, this.rotation);
        filer.writeAngle(52, this.oblique);
        return this;`,
		replace: `        filer.writeSubclassMarker('AcDbAlignedDimension');
        filer.writePoint3d(13, this.xLine1Point);
        filer.writePoint3d(14, this.xLine2Point);
        filer.writeAngle(50, this.rotation);
        filer.writeAngle(52, this.oblique);
        if (this.dxfSubclassMarker !== 'AcDbAlignedDimension') {
            filer.writeSubclassMarker(this.dxfSubclassMarker);
        }
        return this;`,
	},
];

/** Applies the patches for `filePath`; throws if a patch no longer matches. */
export function applyPatches(filePath, source, applied) {
	const normalized = filePath.replace(/\\/g, '/');
	let result = source.replace(/\r\n/g, '\n');
	for (const patch of PATCHES) {
		if (!normalized.endsWith(`/@mlightcad/data-model/lib/${patch.file}`)) {
			continue;
		}
		const count = result.split(patch.find).length - 1;
		if (count !== 1) {
			throw new Error(`mlightcad patch "${patch.description}" matched ${count} times in ${patch.file}; review it after upgrading.`);
		}
		result = result.replace(patch.find, patch.replace);
		applied.push(patch.description);
	}
	return result;
}
