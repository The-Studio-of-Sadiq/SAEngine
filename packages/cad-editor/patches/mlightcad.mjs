// Source patches for mlightcad, applied at bundle time. Each `find` must occur exactly once in
// the named file, so an upgrade that changes the code fails the build instead of silently
// dropping a fix. Remove a patch once the fix ships upstream.

const ALIGNED = 'entity/dimension/AcDbAlignedDimension.js';
const VIEWER = { pkg: 'cad-simple-viewer', file: 'cad-simple-viewer.js' };

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
	{
		// An entity erased while its geometry was still being built (an MTEXT label in the layout
		// worker, or still queued) was skipped by the erase, as not in the scene yet, and added
		// when its geometry came: a ghost label. The floor plan regenerates its labels on every
		// edit, so a label moved by an edit (a rotated column's) showed twice, over itself.
		...VIEWER,
		description: 'drop the geometry of entities erased while it is being built',
		find: `      const o = rh(n.entity).filter(
        (r) => this.view.hasEntity(r.objectId)
      );
      o.length !== 0 && this.view.removeEntity(o.length === 1 ? o[0] : o);`,
		replace: `      const all = rh(n.entity), view = this.view;
      if (view._entityConvertGeneration && view._convertQueue) {
        const building = new Set(all.filter((r) => !view.hasEntity(r.objectId)).map((r) => String(r.objectId ?? "")).filter(Boolean));
        if (building.size) {
          const queued = view._convertQueue.filter((r) => !building.has(String(r.objectId ?? "")));
          view._convertQueue.length = 0;
          view._convertQueue.push(...queued);
          view._saengineErased ??= new Set();
          for (const id of building) {
            if (view._claimedConvertObjectIds.has(id)) {
              view._entityConvertGeneration.set(id, (view._entityConvertGeneration.get(id) ?? 0) + 1);
            } else {
              view._saengineErased.add(id);
            }
          }
        }
      }
      const o = all.filter(
        (r) => view.hasEntity(r.objectId)
      );
      o.length !== 0 && view.removeEntity(o.length === 1 ? o[0] : o);`,
	},
	{
		...VIEWER,
		description: 'skip entities erased before their geometry was started',
		find: `          if (d && (this.hasEntity(d) || this._claimedConvertObjectIds.has(d)))
            continue;`,
		replace: `          if (d && this._saengineErased?.delete(d))
            continue;
          if (d && (this.hasEntity(d) || this._claimedConvertObjectIds.has(d)))
            continue;`,
	},
	{
		...VIEWER,
		description: 'forget the erased entities once the queue they were in has drained',
		find: `    })().finally(() => {
      this._convertDrainPromise = null;`,
		replace: `    })().finally(() => {
      this._convertDrainPromise = null;
      this._saengineErased?.clear();`,
	},
];

/** Applies the patches for `filePath`; throws if a patch no longer matches. */
export function applyPatches(filePath, source, applied) {
	const normalized = filePath.replace(/\\/g, '/');
	let result = source.replace(/\r\n/g, '\n');
	for (const patch of PATCHES) {
		const where = patch.pkg ? `/@mlightcad/${patch.pkg}/dist/${patch.file}` : `/@mlightcad/data-model/lib/${patch.file}`;
		if (!normalized.endsWith(where)) {
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
