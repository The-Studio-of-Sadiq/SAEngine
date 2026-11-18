/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDb2dPolyline, AcDbArc, AcDbCircle, AcDbDatabase, AcDbLine, AcDbOsnapMode,
	AcDbPolyline, AcDbSysVarManager, AcDbSystemVariables, acdbMaskToOsnapModes,
	acdbOsnapModesToMask,
} from '@mlightcad/data-model';
import { AcApDocManager, AcApSettingManager, AcEdOsnapResolver } from '@mlightcad/cad-simple-viewer';
import {
	geometricCenter, orthoConstraint, perpendicularFoot, snapToGrid, tangentPointsToCircle,
} from './draftingAidsGeometry.js';
import type { CadCommandContext } from './commands.js';

export interface DraftingSettings {
	readonly osnap: boolean;
	readonly ortho: boolean;
	readonly polar: boolean;
	readonly polarAngle: number;
	readonly otrack: boolean;
	readonly dyn: boolean;
	readonly grid: boolean;
	readonly snap: boolean;
	readonly snapUnit: number | [number, number];
	readonly osnapModes: number;
}

/** Standard OSNAP override keywords recognized at point prompts. */
export const OSNAP_OVERRIDE_KEYWORDS = [
	'END', 'MID', 'CEN', 'GCE', 'NOD', 'QUA', 'INT', 'APP', 'EXT', 'INS', 'PER', 'TAN', 'NEA', 'PAR', 'NON',
] as const;

export type OsnapOverrideKeyword = typeof OSNAP_OVERRIDE_KEYWORDS[number];

export const OSNAP_MODE_BY_KEYWORD: Record<string, AcDbOsnapMode | 0> = {
	END: AcDbOsnapMode.EndPoint,
	ENDPOINT: AcDbOsnapMode.EndPoint,
	MID: AcDbOsnapMode.MidPoint,
	MIDPOINT: AcDbOsnapMode.MidPoint,
	CEN: AcDbOsnapMode.Center,
	CENTER: AcDbOsnapMode.Center,
	GCE: AcDbOsnapMode.Centroid,
	GEOCENTER: AcDbOsnapMode.Centroid,
	GEOMETRICCENTER: AcDbOsnapMode.Centroid,
	NOD: AcDbOsnapMode.Node,
	NODE: AcDbOsnapMode.Node,
	QUA: AcDbOsnapMode.Quadrant,
	QUADRANT: AcDbOsnapMode.Quadrant,
	INT: AcDbOsnapMode.Intersection,
	INTERSECTION: AcDbOsnapMode.Intersection,
	APP: AcDbOsnapMode.Intersection,
	EXT: AcDbOsnapMode.EndPoint,
	INS: AcDbOsnapMode.Insertion,
	INSERT: AcDbOsnapMode.Insertion,
	INSERTION: AcDbOsnapMode.Insertion,
	PER: AcDbOsnapMode.Perpendicular,
	PERPENDICULAR: AcDbOsnapMode.Perpendicular,
	TAN: AcDbOsnapMode.Tangent,
	TANGENT: AcDbOsnapMode.Tangent,
	NEA: AcDbOsnapMode.Nearest,
	NEAREST: AcDbOsnapMode.Nearest,
	PAR: AcDbOsnapMode.EndPoint,
	NON: 0,
	NONE: 0,
};

export const OSNAP_ALL_MODES: ReadonlyArray<{ readonly mode: AcDbOsnapMode; readonly code: string; readonly name: string }> = [
	{ mode: AcDbOsnapMode.EndPoint, code: 'END', name: 'Endpoint' },
	{ mode: AcDbOsnapMode.MidPoint, code: 'MID', name: 'Midpoint' },
	{ mode: AcDbOsnapMode.Center, code: 'CEN', name: 'Center' },
	{ mode: AcDbOsnapMode.Centroid, code: 'GCE', name: 'Geometric Center' },
	{ mode: AcDbOsnapMode.Node, code: 'NOD', name: 'Node' },
	{ mode: AcDbOsnapMode.Quadrant, code: 'QUA', name: 'Quadrant' },
	{ mode: AcDbOsnapMode.Intersection, code: 'INT', name: 'Intersection' },
	{ mode: AcDbOsnapMode.Insertion, code: 'INS', name: 'Insertion' },
	{ mode: AcDbOsnapMode.Perpendicular, code: 'PER', name: 'Perpendicular' },
	{ mode: AcDbOsnapMode.Tangent, code: 'TAN', name: 'Tangent' },
	{ mode: AcDbOsnapMode.Nearest, code: 'NEA', name: 'Nearest' },
];

/** Default active running osnap modes when osnap is turned on. */
export const DEFAULT_OSNAP_MODES_MASK = acdbOsnapModesToMask([
	AcDbOsnapMode.EndPoint,
	AcDbOsnapMode.MidPoint,
	AcDbOsnapMode.Center,
	AcDbOsnapMode.Quadrant,
	AcDbOsnapMode.Intersection,
	AcDbOsnapMode.Nearest,
]);

let isGeometryPatched = false;

/**
 * Patches geometry prototypes and osnap resolver once globally to support missing
 * modes: perpendicular, tangent, centroid (geometric centre), node, and insertion.
 */
export function ensureDraftingGeometryPatched(): void {
	if (isGeometryPatched) return;
	isGeometryPatched = true;

	// 1. AcDbLine: support perpendicular using prompt base / last point
	const origLineSubGetOsnap = AcDbLine.prototype.subGetOsnapPoints;
	AcDbLine.prototype.subGetOsnapPoints = function (this: AcDbLine, osnapMode, pickPoint, lastPoint, snapPoints, ...args) {
		if (osnapMode === AcDbOsnapMode.Perpendicular) {
			const base = lastPoint ?? pickPoint;
			if (base) {
				const foot = perpendicularFoot(base, this.startPoint, this.endPoint);
				snapPoints.push({ x: foot.x, y: foot.y, z: foot.z ?? 0 } as any);
				return;
			}
		}
		return origLineSubGetOsnap.call(this, osnapMode, pickPoint, lastPoint, snapPoints, ...args);
	};

	// 2. AcDbCircle: support tangent and perpendicular using base point
	const origCircleSubGetOsnap = AcDbCircle.prototype.subGetOsnapPoints;
	AcDbCircle.prototype.subGetOsnapPoints = function (this: AcDbCircle, osnapMode, pickPoint, lastPoint, snapPoints, ...args) {
		if (osnapMode === AcDbOsnapMode.Tangent) {
			const base = lastPoint ?? pickPoint;
			if (base) {
				const tangents = tangentPointsToCircle(base, this.center, this.radius);
				if (tangents.length > 0) {
					snapPoints.push(...(tangents as any[]));
					return;
				}
			}
		} else if (osnapMode === AcDbOsnapMode.Perpendicular) {
			const base = lastPoint ?? pickPoint;
			if (base) {
				// Perpendicular to a circle from a point lies along the radial line from center through base
				const dx = base.x - this.center.x;
				const dy = base.y - this.center.y;
				const dist = Math.hypot(dx, dy);
				if (dist > 1e-12) {
					const uX = dx / dist;
					const uY = dy / dist;
					// Two intersection points with radial line
					snapPoints.push(
						{ x: this.center.x + this.radius * uX, y: this.center.y + this.radius * uY, z: this.center.z } as any,
						{ x: this.center.x - this.radius * uX, y: this.center.y - this.radius * uY, z: this.center.z } as any,
					);
					return;
				}
			}
		}
		return origCircleSubGetOsnap.call(this, osnapMode, pickPoint, lastPoint, snapPoints, ...args);
	};

	// 3. AcDbArc: support tangent using base point
	const origArcSubGetOsnap = AcDbArc.prototype.subGetOsnapPoints;
	AcDbArc.prototype.subGetOsnapPoints = function (this: AcDbArc, osnapMode, pickPoint, lastPoint, snapPoints, ...args) {
		if (osnapMode === AcDbOsnapMode.Tangent) {
			const base = lastPoint ?? pickPoint;
			if (base) {
				const tangents = tangentPointsToCircle(base, this.center, this.radius);
				if (tangents.length > 0) {
					// Filter tangents that fall within the arc angular sweep
					const valid = tangents.filter(t => {
						const ang = Math.atan2(t.y - this.center.y, t.x - this.center.x);
						const norm = ((ang % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
						const s = ((this.startAngle % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
						const e = ((this.endAngle % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
						return s <= e ? norm >= s && norm <= e : norm >= s || norm <= e;
					});
					if (valid.length > 0) {
						snapPoints.push(...(valid as any[]));
						return;
					}
				}
			}
		}
		return origArcSubGetOsnap.call(this, osnapMode, pickPoint, lastPoint, snapPoints, ...args);
	};

	// 4. AcDbPolyline: support geometric center (Centroid) for closed polylines
	const origPolySubGetOsnap = AcDbPolyline.prototype.subGetOsnapPoints;
	AcDbPolyline.prototype.subGetOsnapPoints = function (this: AcDbPolyline, osnapMode, pickPoint, lastPoint, snapPoints, ...args) {
		if (osnapMode === AcDbOsnapMode.Centroid) {
			if (this.closed && this.numberOfVertices >= 3) {
				const count = this.numberOfVertices;
				const vertices: { x: number; y: number }[] = [];
				for (let i = 0; i < count; i++) {
					const pt = this.getPoint2dAt(i);
					vertices.push({ x: pt.x, y: pt.y });
				}
				const center = geometricCenter(vertices);
				snapPoints.push((this as any).ocsPointToWcs(center.x, center.y));
				return;
			}
		}
		return origPolySubGetOsnap.call(this, osnapMode, pickPoint, lastPoint, snapPoints, ...args);
	};

	// 5. AcDb2dPolyline: support geometric center (Centroid) for closed 2D polylines
	const orig2dPolySubGetOsnap = AcDb2dPolyline.prototype.subGetOsnapPoints;
	AcDb2dPolyline.prototype.subGetOsnapPoints = function (this: any, osnapMode, pickPoint, lastPoint, snapPoints, ...args) {
		if (osnapMode === AcDbOsnapMode.Centroid) {
			const isClosed = this.isClosed || this.closed;
			if (isClosed) {
				const vertices: { x: number; y: number }[] = [];
				try {
					if (typeof this.vertexPoints === 'function') {
						for (const pt of this.vertexPoints()) vertices.push({ x: pt.x, y: pt.y });
					}
				} catch {
					// ignore
				}
				if (vertices.length >= 3) {
					const center = geometricCenter(vertices);
					snapPoints.push({ x: center.x, y: center.y, z: 0 });
					return;
				}
			}
		}
		return orig2dPolySubGetOsnap.call(this, osnapMode, pickPoint, lastPoint, snapPoints, ...args);
	};

	// 6. Marker type mapping for custom osnap modes
	const origMarkerType = AcEdOsnapResolver.osnapModeToMarkerType;
	AcEdOsnapResolver.osnapModeToMarkerType = function (mode: AcDbOsnapMode) {
		switch (mode) {
			case AcDbOsnapMode.Node:
				return 'plus';
			case AcDbOsnapMode.Insertion:
				return 'rect';
			case AcDbOsnapMode.Perpendicular:
				return 'intersection';
			case AcDbOsnapMode.Tangent:
				return 'circle';
			case AcDbOsnapMode.Centroid:
				return 'diamond';
			default:
				return origMarkerType(mode);
		}
	};

	// 7. Marker priority mapping
	const origPriority = (AcEdOsnapResolver as any).osnapModePriority;
	(AcEdOsnapResolver as any).osnapModePriority = function (mode: AcDbOsnapMode) {
		switch (mode) {
			case AcDbOsnapMode.EndPoint:
			case AcDbOsnapMode.MidPoint:
			case AcDbOsnapMode.Center:
			case AcDbOsnapMode.Intersection:
			case AcDbOsnapMode.Node:
			case AcDbOsnapMode.Insertion:
			case AcDbOsnapMode.Perpendicular:
			case AcDbOsnapMode.Tangent:
			case AcDbOsnapMode.Centroid:
				return 0;
			case AcDbOsnapMode.Quadrant:
				return 1;
			case AcDbOsnapMode.Nearest:
				return 2;
			default:
				return origPriority ? origPriority(mode) : 1;
		}
	};
}

export class DraftingAidsManager {
	private readonly listeners = new Set<(settings: DraftingSettings) => void>();
	private _savedRunningModes: number = DEFAULT_OSNAP_MODES_MASK;
	private _grid = true;
	private _snap = false;
	private _snapUnit: number | [number, number] = 5;
	private _otrack = false;
	private _singlePickOverride: AcDbOsnapMode | 0 | undefined = undefined;
	private _savedOverrideModes: number | undefined = undefined;
	private _acquiredTrackingPoints: { x: number; y: number; z: number }[] = [];
	private _hoverTimer: ReturnType<typeof setTimeout> | null = null;
	private _lastHoverPoint: { x: number; y: number } | null = null;
	private _cleanupFKeys: (() => void) | undefined;
	private _cleanupSysVars: (() => void) | undefined;

	constructor(
		private readonly container: HTMLElement,
		private readonly getDb: () => AcDbDatabase | undefined,
	) {
		ensureDraftingGeometryPatched();
		this.initSysVarListener();
		this.initKeyboardHandler();
		this.initContextMenuHandler();
	}

	private get db(): AcDbDatabase | undefined {
		return this.getDb();
	}

	private initSysVarListener(): void {
		const sysVars = AcDbSysVarManager.instance();
		const onSysVarChanged = () => {
			this.notify();
		};
		sysVars.events.sysVarChanged.addEventListener(onSysVarChanged);
		this._cleanupSysVars = () => {
			sysVars.events.sysVarChanged.removeEventListener(onSysVarChanged);
		};
	}

	private initKeyboardHandler(): void {
		const onKeyDown = (e: KeyboardEvent) => {
			let handled = true;
			switch (e.key) {
				case 'F3':
					this.toggleOsnap();
					break;
				case 'F7':
					this.toggleGrid();
					break;
				case 'F8':
					this.toggleOrtho();
					break;
				case 'F9':
					this.toggleSnap();
					break;
				case 'F10':
					this.togglePolar();
					break;
				case 'F11':
					this.toggleOtrack();
					break;
				case 'F12':
					this.toggleDyn();
					break;
				default:
					handled = false;
					break;
			}
			if (handled) {
				e.preventDefault();
				e.stopPropagation();
			}
		};

		this.container.addEventListener('keydown', onKeyDown, { capture: true });
		window.addEventListener('keydown', onKeyDown, { capture: true });

		this._cleanupFKeys = () => {
			this.container.removeEventListener('keydown', onKeyDown, { capture: true });
			window.removeEventListener('keydown', onKeyDown, { capture: true });
		};
	}

	private initContextMenuHandler(): void {
		// Shift + Right Click on canvas opens OSNAP override menu
		const onContextMenu = (e: MouseEvent) => {
			if (!e.shiftKey) return;
			e.preventDefault();
			e.stopPropagation();
			this.showOsnapContextMenu(e.clientX, e.clientY);
		};
		this.container.addEventListener('contextmenu', onContextMenu, { capture: true });
	}

	private showOsnapContextMenu(clientX: number, clientY: number): void {
		const menu = document.createElement('div');
		menu.className = 'sa-osnap-override-menu';
		menu.style.position = 'fixed';
		menu.style.left = `${clientX}px`;
		menu.style.top = `${clientY}px`;
		menu.style.zIndex = '99999';
		menu.style.background = '#222';
		menu.style.color = '#eee';
		menu.style.border = '1px solid #555';
		menu.style.borderRadius = '4px';
		menu.style.padding = '4px 0';
		menu.style.fontSize = '12px';
		menu.style.fontFamily = 'monospace, sans-serif';
		menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.5)';

		const close = () => {
			menu.remove();
			document.removeEventListener('pointerdown', onDocClick);
		};

		const onDocClick = (ev: MouseEvent) => {
			if (!menu.contains(ev.target as Node)) {
				close();
			}
		};
		setTimeout(() => document.addEventListener('pointerdown', onDocClick), 0);

		const items = [
			...OSNAP_ALL_MODES.map(m => ({ label: `${m.name} (${m.code})`, mode: m.mode })),
			{ label: 'None (NON)', mode: 0 as const },
		];

		for (const item of items) {
			const row = document.createElement('div');
			row.style.padding = '4px 12px';
			row.style.cursor = 'pointer';
			row.textContent = item.label;
			row.addEventListener('mouseenter', () => { row.style.background = '#3a3a3a'; });
			row.addEventListener('mouseleave', () => { row.style.background = 'transparent'; });
			row.addEventListener('click', () => {
				close();
				this.setSinglePickOverride(item.mode);
			});
			menu.appendChild(row);
		}

		document.body.appendChild(menu);
	}

	/** Returns current drafting aid settings. */
	get(): DraftingSettings {
		const settings = AcApSettingManager.instance;
		const activeModes = settings.osnapModes;
		const sysVars = AcDbSysVarManager.instance();
		const db = this.db;

		const ortho = db ? Number(sysVars.getVar(AcDbSystemVariables.ORTHOMODE, db)) !== 0 : false;
		const polarMode = db ? Number(sysVars.getVar(AcDbSystemVariables.POLARMODE, db)) || 0 : 0;
		const polar = (polarMode & 2) !== 0;
		const polarAngle = db ? Number(sysVars.getVar(AcDbSystemVariables.POLARANG, db)) || 90 : 90;
		const dyn = db ? Number(sysVars.getVar(AcDbSystemVariables.DYNMODE, db)) !== 0 : true;

		return {
			osnap: activeModes > 0,
			ortho,
			polar,
			polarAngle,
			otrack: this._otrack,
			dyn,
			grid: this._grid,
			snap: this._snap,
			snapUnit: this._snapUnit,
			osnapModes: activeModes > 0 ? activeModes : this._savedRunningModes,
		};
	}

	/** Updates drafting aid settings. */
	set(patch: Partial<DraftingSettings>): void {
		const sysVars = AcDbSysVarManager.instance();
		const settings = AcApSettingManager.instance;
		const db = this.db;

		if (patch.osnapModes !== undefined) {
			this._savedRunningModes = patch.osnapModes;
			if (settings.osnapModes > 0 || patch.osnap === true) {
				settings.osnapModes = patch.osnapModes;
				if (db) sysVars.setVar(AcDbSystemVariables.OSMODE, patch.osnapModes, db);
			}
		}

		if (patch.osnap !== undefined) {
			if (patch.osnap) {
				const modes = this._savedRunningModes || DEFAULT_OSNAP_MODES_MASK;
				settings.osnapModes = modes;
				if (db) sysVars.setVar(AcDbSystemVariables.OSMODE, modes, db);
			} else {
				if (settings.osnapModes > 0) {
					this._savedRunningModes = settings.osnapModes;
				}
				settings.osnapModes = 0;
				if (db) sysVars.setVar(AcDbSystemVariables.OSMODE, this._savedRunningModes | 16384, db);
			}
		}

		if (patch.ortho !== undefined && db) {
			sysVars.setVar(AcDbSystemVariables.ORTHOMODE, patch.ortho ? 1 : 0, db);
			if (patch.ortho) {
				// Turning ORTHO on disables POLAR
				const currPolarMode = Number(sysVars.getVar(AcDbSystemVariables.POLARMODE, db)) || 0;
				sysVars.setVar(AcDbSystemVariables.POLARMODE, currPolarMode & ~2, db);
			}
		}

		if (patch.polar !== undefined && db) {
			const currPolarMode = Number(sysVars.getVar(AcDbSystemVariables.POLARMODE, db)) || 0;
			sysVars.setVar(AcDbSystemVariables.POLARMODE, patch.polar ? (currPolarMode | 2) : (currPolarMode & ~2), db);
			if (patch.polar) {
				// Turning POLAR on disables ORTHO
				sysVars.setVar(AcDbSystemVariables.ORTHOMODE, 0, db);
			}
		}

		if (patch.polarAngle !== undefined && db) {
			sysVars.setVar(AcDbSystemVariables.POLARANG, patch.polarAngle, db);
		}

		if (patch.dyn !== undefined && db) {
			sysVars.setVar(AcDbSystemVariables.DYNMODE, patch.dyn ? 3 : 0, db);
		}

		if (patch.grid !== undefined) {
			this._grid = patch.grid;
		}

		if (patch.snap !== undefined) {
			this._snap = patch.snap;
		}

		if (patch.snapUnit !== undefined) {
			this._snapUnit = patch.snapUnit;
		}

		if (patch.otrack !== undefined) {
			this._otrack = patch.otrack;
		}

		this.notify();
	}

	toggleOsnap(): boolean {
		const next = !this.get().osnap;
		this.set({ osnap: next });
		return next;
	}

	toggleOrtho(): boolean {
		const next = !this.get().ortho;
		this.set({ ortho: next });
		return next;
	}

	togglePolar(): boolean {
		const next = !this.get().polar;
		this.set({ polar: next });
		return next;
	}

	toggleDyn(): boolean {
		const next = !this.get().dyn;
		this.set({ dyn: next });
		return next;
	}

	toggleGrid(): boolean {
		const next = !this._grid;
		this.set({ grid: next });
		return next;
	}

	toggleSnap(): boolean {
		const next = !this._snap;
		this.set({ snap: next });
		return next;
	}

	toggleOtrack(): boolean {
		const next = !this._otrack;
		this.set({ otrack: next });
		return next;
	}

	setPolarAngle(deg: number): void {
		this.set({ polarAngle: deg });
	}

	toggleOsnapMode(mode: AcDbOsnapMode): void {
		const currentModes = acdbMaskToOsnapModes(this._savedRunningModes);
		const exists = currentModes.includes(mode);
		const nextModes = exists ? currentModes.filter(m => m !== mode) : [...currentModes, mode];
		const nextMask = acdbOsnapModesToMask(nextModes);
		this.set({ osnapModes: nextMask });
	}

	/** Sets a single-pick override for the next point prompt. */
	setSinglePickOverride(mode: AcDbOsnapMode | 0): void {
		const settings = AcApSettingManager.instance;
		if (this._savedOverrideModes === undefined) {
			this._savedOverrideModes = settings.osnapModes;
		}
		this._singlePickOverride = mode;
		settings.osnapModes = mode === 0 ? 0 : (1 << (mode - 1));
	}

	/** Clears any active single-pick override and restores running osnaps. */
	clearSinglePickOverride(): void {
		if (this._savedOverrideModes !== undefined) {
			AcApSettingManager.instance.osnapModes = this._savedOverrideModes;
			this._savedOverrideModes = undefined;
		}
		this._singlePickOverride = undefined;
	}

	hasSinglePickOverride(): boolean {
		return this._singlePickOverride !== undefined;
	}

	getSinglePickOverride(): AcDbOsnapMode | 0 | undefined {
		return this._singlePickOverride;
	}

	/** Minimal object snap tracking helper: records acquired tracking point when hovered. */
	recordTrackingHover(point: { x: number; y: number; z?: number }): void {
		if (!this._otrack) return;
		if (this._hoverTimer) clearTimeout(this._hoverTimer);
		this._lastHoverPoint = { x: point.x, y: point.y };
		this._hoverTimer = setTimeout(() => {
			if (this._lastHoverPoint) {
				const pt = { x: this._lastHoverPoint.x, y: this._lastHoverPoint.y, z: point.z ?? 0 };
				const exists = this._acquiredTrackingPoints.some(p => Math.hypot(p.x - pt.x, p.y - pt.y) < 1e-6);
				if (!exists) {
					this._acquiredTrackingPoints.push(pt);
				}
			}
		}, 500);
	}

	clearTrackingPoints(): void {
		if (this._hoverTimer) clearTimeout(this._hoverTimer);
		this._hoverTimer = null;
		this._lastHoverPoint = null;
		this._acquiredTrackingPoints = [];
	}

	getAcquiredTrackingPoints(): ReadonlyArray<{ x: number; y: number; z: number }> {
		return this._acquiredTrackingPoints;
	}

	/** Constrains cursor point to active alignment rays from acquired tracking points. */
	constrainToTracking(cursor: { x: number; y: number; z?: number }, tol = 0.1): { x: number; y: number; z: number } {
		if (!this._otrack || this._acquiredTrackingPoints.length === 0) {
			return { x: cursor.x, y: cursor.y, z: cursor.z ?? 0 };
		}
		for (const pt of this._acquiredTrackingPoints) {
			// Horizontal ray
			if (Math.abs(cursor.y - pt.y) < tol) {
				return { x: cursor.x, y: pt.y, z: cursor.z ?? pt.z };
			}
			// Vertical ray
			if (Math.abs(cursor.x - pt.x) < tol) {
				return { x: pt.x, y: cursor.y, z: cursor.z ?? pt.z };
			}
		}
		return { x: cursor.x, y: cursor.y, z: cursor.z ?? 0 };
	}

	onDidChangeDrafting(listener: (settings: DraftingSettings) => void): () => void {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	private notify(): void {
		const current = this.get();
		for (const l of this.listeners) l(current);
	}

	dispose(): void {
		this._cleanupFKeys?.();
		this._cleanupSysVars?.();
		this.clearTrackingPoints();
		this.listeners.clear();
	}
}

/** Global manager reference for active editor. */
let activeDraftingManager: DraftingAidsManager | undefined;

export function getActiveDraftingManager(): DraftingAidsManager | undefined {
	return activeDraftingManager;
}

export function setActiveDraftingManager(mgr: DraftingAidsManager | undefined): void {
	activeDraftingManager = mgr;
}

/**
 * OSNAP command: lists modes with on/off and lets the user toggle them by name.
 */
export async function osnapCommand(ctx: CadCommandContext): Promise<void> {
	const mgr = getActiveDraftingManager();
	if (!mgr) {
		ctx.message('Drafting manager not initialized.');
		return;
	}

	while (true) {
		const s = mgr.get();
		const enabledModes = acdbMaskToOsnapModes(s.osnapModes);
		const lines: string[] = [
			`OSNAP is currently: ${s.osnap ? 'ON' : 'OFF'}`,
			'Modes:',
		];
		for (const item of OSNAP_ALL_MODES) {
			const on = enabledModes.includes(item.mode);
			lines.push(`  [${item.code}] ${item.name.padEnd(18)}: ${on ? 'ON' : 'OFF'}`);
		}
		ctx.message(lines.join('\n'));

		const input = await ctx.getString('Enter snap mode to toggle or [ON/OFF/Clear/All/eXit] <eXit>:', {
			allowEmpty: true,
		});

		const choice = input.trim().toUpperCase();
		if (!choice || choice === 'X' || choice === 'EXIT') {
			break;
		}

		if (choice === 'ON') {
			mgr.set({ osnap: true });
			ctx.message('OSNAP turned ON.');
		} else if (choice === 'OFF') {
			mgr.set({ osnap: false });
			ctx.message('OSNAP turned OFF.');
		} else if (choice === 'CLEAR' || choice === 'NONE') {
			mgr.set({ osnapModes: 0 });
			ctx.message('Cleared all snap modes.');
		} else if (choice === 'ALL') {
			const allMask = acdbOsnapModesToMask(OSNAP_ALL_MODES.map(m => m.mode));
			mgr.set({ osnapModes: allMask });
			ctx.message('Enabled all snap modes.');
		} else {
			const mode = OSNAP_MODE_BY_KEYWORD[choice];
			if (mode !== undefined && mode !== 0) {
				mgr.toggleOsnapMode(mode);
				const item = OSNAP_ALL_MODES.find(m => m.mode === mode);
				const nowOn = acdbMaskToOsnapModes(mgr.get().osnapModes).includes(mode);
				ctx.message(`${item?.name ?? choice} is now ${nowOn ? 'ON' : 'OFF'}.`);
			} else {
				ctx.message(`Unknown option or snap mode: "${choice}".`);
			}
		}
	}
}

/**
 * POLARANG command: sets the polar tracking angle increment.
 */
export async function polarangCommand(ctx: CadCommandContext): Promise<void> {
	const mgr = getActiveDraftingManager();
	const current = mgr ? mgr.get().polarAngle : 90;
	const val = await ctx.getDouble(`Enter new value for POLARANG <${current}>:`);
	if (val > 0 && val <= 360) {
		mgr?.setPolarAngle(val);
		ctx.message(`POLARANG set to ${val}°.`);
	} else {
		ctx.message('Invalid angle increment. Must be between 0° and 360°.');
	}
}

/**
 * ORTHO command: toggles orthogonal mode.
 */
export async function orthoCommand(ctx: CadCommandContext): Promise<void> {
	const mgr = getActiveDraftingManager();
	if (!mgr) return;
	const next = mgr.toggleOrtho();
	ctx.message(`ORTHO is now ${next ? 'ON' : 'OFF'}.`);
}

/**
 * POLAR command: toggles polar tracking mode.
 */
export async function polarCommand(ctx: CadCommandContext): Promise<void> {
	const mgr = getActiveDraftingManager();
	if (!mgr) return;
	const next = mgr.togglePolar();
	ctx.message(`POLAR tracking is now ${next ? 'ON' : 'OFF'}.`);
}

/**
 * DYN command: toggles dynamic input mode.
 */
export async function dynCommand(ctx: CadCommandContext): Promise<void> {
	const mgr = getActiveDraftingManager();
	if (!mgr) return;
	const next = mgr.toggleDyn();
	ctx.message(`DYN mode is now ${next ? 'ON' : 'OFF'}.`);
}

/**
 * Registers drafting aid commands with the command stack.
 */
export function registerDraftingCommands(register: (name: string, cmd: (ctx: CadCommandContext) => Promise<void>, opts?: { aliases?: string[] }) => void): void {
	register('OSNAP', osnapCommand, { aliases: ['OS'] });
	register('POLARANG', polarangCommand);
	register('ORTHO', orthoCommand);
	register('POLAR', polarCommand);
	register('DYN', dynCommand);
}
