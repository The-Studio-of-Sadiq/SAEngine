/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadColorValue, CadEditor as CadEditorApi, CadLineweightValue, CadPropertiesResult } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { appendPropertyHeading, appendPropertyRow, applyPropertyOnCommit } from '../../saengineProject/browser/editorFrame.js';
import { STANDARD_COLORS, STANDARD_LINETYPES, STANDARD_LINEWEIGHTS } from './floorPlanCadBar.js';

function round2(val: number | undefined): number {
	return typeof val === 'number' ? Math.round(val * 100) / 100 : 0;
}

export class FloorPlanDraftProperties extends Disposable {
	private activeTypeFilter: string | undefined;

	constructor(
		@IContextViewService private readonly contextViewService: IContextViewService,
	) {
		super();
	}

	public render(
		panel: HTMLElement,
		store: DisposableStore,
		editor: CadEditorApi,
		draftIds: readonly string[],
	): void {
		clearNode(panel);
		let allProps: CadPropertiesResult;
		try {
			allProps = editor.properties.get(draftIds);
		} catch {
			return;
		}

		const summaryTypes = allProps.types ?? [];
		if (draftIds.length === 0 || summaryTypes.length === 0) {
			return;
		}

		// Ensure active filter is still valid
		if (this.activeTypeFilter && !summaryTypes.some(t => t.type === this.activeTypeFilter)) {
			this.activeTypeFilter = undefined;
		}

		const targetEntry = this.activeTypeFilter ? summaryTypes.find(t => t.type === this.activeTypeFilter) : undefined;
		const effectiveIds = targetEntry ? targetEntry.ids : draftIds;
		const props: CadPropertiesResult = targetEntry ? editor.properties.get(effectiveIds) : allProps;
		const effectiveType = targetEntry ? targetEntry.type : allProps.primaryType;

		// 1. Header: Drafting: <N> objects (<type or 'Mixed'>)
		const countStr = effectiveIds.length;
		const typeStr = effectiveType ?? (effectiveIds.length === 1 ? 'Object' : 'Objects');
		const headerText = effectiveIds.length === 1
			? localize('floorPlan.draftPropSingle', "Drafting: 1 object ({0})", typeStr)
			: localize('floorPlan.draftPropPlural', "Drafting: {0} objects ({1})", countStr, typeStr);

		appendPropertyHeading(panel, headerText);

		// 2. Type filter dropdown when mixed
		if (summaryTypes.length > 1) {
			const filterOptions = [
				{ text: localize('floorPlan.draftPropAll', "All ({0})", draftIds.length) },
				...summaryTypes.map(t => ({ text: `${t.type} (${t.count})` })),
			];
			const selectedIndex = this.activeTypeFilter
				? summaryTypes.findIndex(t => t.type === this.activeTypeFilter) + 1
				: 0;

			this.renderSelectRow(
				panel,
				store,
				localize('floorPlan.draftPropFilter', "Object Type"),
				filterOptions,
				Math.max(0, selectedIndex),
				idx => {
					this.activeTypeFilter = idx === 0 ? undefined : summaryTypes[idx - 1]?.type;
					this.render(panel, store, editor, draftIds);
				},
			);
		}

		// 3. General section
		append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.general', "General")));

		this.renderGeneralRows(panel, store, editor, effectiveIds, props, draftIds);

		// 4. Geometry rows per type
		this.renderGeometryRows(panel, store, editor, effectiveIds, props, effectiveType);
	}

	private renderGeneralRows(
		panel: HTMLElement,
		store: DisposableStore,
		editor: CadEditorApi,
		targetIds: readonly string[],
		props: CadPropertiesResult,
		allDraftIds: readonly string[],
	): void {
		// --- Layer ---
		// Drafting goes on drafting layers: the structural (generated) layers and the plan's own
		// SAENGINE-* preview layers are not offered, unless the selection is already on one.
		const layers = editor.layers.list().filter(l => (!l.generated && !l.name.toUpperCase().startsWith('SAENGINE-')) || l.name === props.layer);
		const layerOptions: { text: string }[] = [];
		const isLayerVaries = props.layer === 'varies';
		if (isLayerVaries) {
			layerOptions.push({ text: '*VARIES*' });
		}
		for (const l of layers) {
			layerOptions.push({ text: l.name });
		}
		const curLayerIndex = isLayerVaries
			? 0
			: layers.findIndex(l => l.name === props.layer) + (isLayerVaries ? 1 : 0);

		this.renderSelectRow(
			panel,
			store,
			localize('floorPlan.props.layer', "Layer"),
			layerOptions,
			Math.max(0, curLayerIndex),
			idx => {
				const chosen = layerOptions[idx]?.text;
				if (chosen && chosen !== '*VARIES*') {
					editor.properties.set(targetIds, { layer: chosen });
				}
			},
		);

		// --- Color ---
		const colorOptions: { text: string; value?: CadColorValue }[] = [];
		const isColorVaries = props.color === 'varies';
		if (isColorVaries) {
			colorOptions.push({ text: '*VARIES*' });
		}
		colorOptions.push({ text: 'ByLayer', value: 'ByLayer' });
		colorOptions.push({ text: 'ByBlock', value: 'ByBlock' });
		for (let i = 0; i < 7; i++) {
			const std = STANDARD_COLORS[i];
			colorOptions.push({ text: `${std.value} - ${std.name}`, value: std.value });
		}

		let curColorIndex = 0;
		if (isColorVaries) {
			curColorIndex = 0;
		} else if (props.color === 'ByLayer') {
			curColorIndex = isColorVaries ? 1 : 0;
		} else if (props.color === 'ByBlock') {
			curColorIndex = isColorVaries ? 2 : 1;
		} else if (typeof props.color === 'number' && props.color >= 1 && props.color <= 7) {
			curColorIndex = (isColorVaries ? 3 : 2) + (props.color - 1);
		} else if (typeof props.color === 'object' && props.color !== null) {
			colorOptions.push({ text: `RGB (${props.color.r}, ${props.color.g}, ${props.color.b})`, value: props.color });
			curColorIndex = colorOptions.length - 1;
		}
		const selectOptionIndex = colorOptions.length;
		colorOptions.push({ text: localize('floorPlan.props.colorSelect', "Select...") });

		const colorCell = $('.floor-plan-prop-control');
		const colorInput = document.createElement('input');
		colorInput.type = 'color';
		colorInput.style.display = 'none';
		colorCell.appendChild(colorInput);
		store.add(addDisposableListener(colorInput, EventType.CHANGE, () => {
			const hex = colorInput.value;
			if (/^#[0-9a-f]{6}$/i.test(hex)) {
				const r = parseInt(hex.slice(1, 3), 16);
				const g = parseInt(hex.slice(3, 5), 16);
				const b = parseInt(hex.slice(5, 7), 16);
				editor.properties.set(targetIds, { color: { r, g, b } });
			}
		}));

		const colorPicker = store.add(new SelectBox(
			colorOptions.map(o => ({ text: o.text })),
			Math.max(0, curColorIndex),
			this.contextViewService,
			defaultSelectBoxStyles,
			{ ariaLabel: localize('floorPlan.props.colorAria', "Color") },
		));
		colorPicker.render(colorCell);
		store.add(colorPicker.onDidSelect(({ index }) => {
			if (index === selectOptionIndex) {
				colorInput.click();
			} else {
				const opt = colorOptions[index];
				if (opt && opt.value !== undefined) {
					editor.properties.set(targetIds, { color: opt.value });
				}
			}
		}));
		appendPropertyRow(panel, localize('floorPlan.props.color', "Color"), colorCell).classList.add('editable');

		// --- Linetype ---
		const ltOptions: { text: string }[] = [];
		const isLtVaries = props.linetype === 'varies';
		if (isLtVaries) {
			ltOptions.push({ text: '*VARIES*' });
		}
		ltOptions.push({ text: 'ByLayer' }, { text: 'ByBlock' });
		for (const lt of STANDARD_LINETYPES) {
			ltOptions.push({ text: lt });
		}
		let curLtIndex = 0;
		if (isLtVaries) {
			curLtIndex = 0;
		} else if (props.linetype === 'ByLayer') {
			curLtIndex = isLtVaries ? 1 : 0;
		} else if (props.linetype === 'ByBlock') {
			curLtIndex = isLtVaries ? 2 : 1;
		} else {
			const idx = STANDARD_LINETYPES.indexOf(String(props.linetype));
			curLtIndex = (isLtVaries ? 3 : 2) + Math.max(0, idx);
		}

		this.renderSelectRow(
			panel,
			store,
			localize('floorPlan.props.linetype', "Linetype"),
			ltOptions,
			curLtIndex,
			idx => {
				const opt = ltOptions[idx];
				if (opt && opt.text !== '*VARIES*') {
					editor.properties.set(targetIds, { linetype: opt.text });
				}
			},
		);

		// --- Linetype scale ---
		const ltScaleVal = props.linetypeScale === 'varies' ? '*VARIES*' : String(props.linetypeScale ?? 1.0);
		this.renderInputRow(
			panel,
			store,
			localize('floorPlan.props.ltscale', "Linetype scale"),
			ltScaleVal,
			'1.0',
			text => {
				const num = Number(text.trim());
				if (Number.isFinite(num) && num > 0) {
					editor.properties.set(targetIds, { linetypeScale: num });
				}
			},
		);

		// --- Lineweight ---
		const lwOptions: { text: string; value?: CadLineweightValue }[] = [];
		const isLwVaries = props.lineweight === 'varies';
		if (isLwVaries) {
			lwOptions.push({ text: '*VARIES*' });
		}
		lwOptions.push({ text: 'ByLayer', value: 'ByLayer' });
		lwOptions.push({ text: 'ByBlock', value: 'ByBlock' });
		lwOptions.push({ text: 'Default', value: 'default' });
		for (const lw of STANDARD_LINEWEIGHTS) {
			lwOptions.push({ text: `${lw.toFixed(2)} mm`, value: lw });
		}

		let curLwIndex = 0;
		if (isLwVaries) {
			curLwIndex = 0;
		} else if (props.lineweight === 'ByLayer') {
			curLwIndex = isLwVaries ? 1 : 0;
		} else if (props.lineweight === 'ByBlock') {
			curLwIndex = isLwVaries ? 2 : 1;
		} else if (props.lineweight === 'default') {
			curLwIndex = isLwVaries ? 3 : 2;
		} else if (typeof props.lineweight === 'number') {
			const idx = STANDARD_LINEWEIGHTS.findIndex(lw => Math.abs(lw - (props.lineweight as number)) < 0.001);
			curLwIndex = (isLwVaries ? 4 : 3) + Math.max(0, idx);
		}

		this.renderSelectRow(
			panel,
			store,
			localize('floorPlan.props.lineweight', "Lineweight"),
			lwOptions,
			curLwIndex,
			idx => {
				const opt = lwOptions[idx];
				if (opt && opt.value !== undefined) {
					editor.properties.set(targetIds, { lineweight: opt.value });
				}
			},
		);
	}

	private renderGeometryRows(
		panel: HTMLElement,
		store: DisposableStore,
		editor: CadEditorApi,
		targetIds: readonly string[],
		props: CadPropertiesResult,
		targetType: string | undefined,
	): void {
		if (targetType === 'Line') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.geometry', "Geometry")));

			this.renderNumberInput(panel, store, localize('floorPlan.props.startX', "Start X (mm)"), props.startX, x => {
				editor.properties.set(targetIds, { startX: x });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.startY', "Start Y (mm)"), props.startY, y => {
				editor.properties.set(targetIds, { startY: y });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.endX', "End X (mm)"), props.endX, x => {
				editor.properties.set(targetIds, { endX: x });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.endY', "End Y (mm)"), props.endY, y => {
				editor.properties.set(targetIds, { endY: y });
			});

			const lenStr = props.length === 'varies' ? '*VARIES*' : props.length !== undefined ? `${round2(props.length)} mm` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.length', "Length"), lenStr);

		} else if (targetType === 'Circle') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.geometry', "Geometry")));

			const cx = props.center === 'varies' || !props.center ? 'varies' : props.center[0];
			const cy = props.center === 'varies' || !props.center ? 'varies' : props.center[1];

			this.renderNumberInput(panel, store, localize('floorPlan.props.centerX', "Center X (mm)"), cx, x => {
				editor.properties.set(targetIds, { centerX: x });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.centerY', "Center Y (mm)"), cy, y => {
				editor.properties.set(targetIds, { centerY: y });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.radius', "Radius (mm)"), props.radius, r => {
				if (r > 0) {
					editor.properties.set(targetIds, { radius: r });
				}
			});

			const circStr = props.circumference === 'varies' ? '*VARIES*' : props.circumference !== undefined ? `${round2(props.circumference)} mm` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.circumference', "Circumference"), circStr);

			const areaStr = props.area === 'varies' ? '*VARIES*' : props.area !== undefined ? `${round2(props.area)} mm²` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.area', "Area"), areaStr);

		} else if (targetType === 'Arc') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.geometry', "Geometry")));

			const cx = props.center === 'varies' || !props.center ? 'varies' : props.center[0];
			const cy = props.center === 'varies' || !props.center ? 'varies' : props.center[1];

			this.renderNumberInput(panel, store, localize('floorPlan.props.centerX', "Center X (mm)"), cx, x => {
				editor.properties.set(targetIds, { centerX: x });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.centerY', "Center Y (mm)"), cy, y => {
				editor.properties.set(targetIds, { centerY: y });
			});
			this.renderNumberInput(panel, store, localize('floorPlan.props.radius', "Radius (mm)"), props.radius, r => {
				if (r > 0) {
					editor.properties.set(targetIds, { radius: r });
				}
			});

			// Angles in degrees
			const saDeg = props.startAngle === 'varies' ? 'varies' : props.startAngle !== undefined ? round2(props.startAngle * 180 / Math.PI) : undefined;
			this.renderNumberInput(panel, store, localize('floorPlan.props.startAngle', "Start angle (°)"), saDeg, deg => {
				editor.properties.set(targetIds, { startAngle: deg * Math.PI / 180 });
			});

			const eaDeg = props.endAngle === 'varies' ? 'varies' : props.endAngle !== undefined ? round2(props.endAngle * 180 / Math.PI) : undefined;
			this.renderNumberInput(panel, store, localize('floorPlan.props.endAngle', "End angle (°)"), eaDeg, deg => {
				editor.properties.set(targetIds, { endAngle: deg * Math.PI / 180 });
			});

			const lenStr = props.length === 'varies' ? '*VARIES*' : props.length !== undefined ? `${round2(props.length)} mm` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.arcLength', "Arc length"), lenStr);

		} else if (targetType === 'Polyline') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.geometry', "Geometry")));

			// Vertices read-only
			const vertCount = Array.isArray(props.vertices) ? props.vertices.length : undefined;
			const vertStr = vertCount !== undefined
				? localize('floorPlan.props.vertexCount', "{0} vertices", vertCount)
				: (props.length !== undefined ? localize('floorPlan.props.polyline', "Polyline") : '*VARIES*');
			appendPropertyRow(panel, localize('floorPlan.props.vertices', "Vertices"), vertStr);

			// Closed toggle
			const closedOptions: { text: string }[] = [];
			const isClosedVaries = props.closed === 'varies';
			if (isClosedVaries) {
				closedOptions.push({ text: '*VARIES*' });
			}
			closedOptions.push({ text: localize('yes', "Yes") }, { text: localize('no', "No") });
			const curClosedIdx = isClosedVaries ? 0 : (props.closed ? 0 : 1);

			this.renderSelectRow(
				panel,
				store,
				localize('floorPlan.props.closed', "Closed"),
				closedOptions,
				curClosedIdx,
				idx => {
					const opt = closedOptions[idx];
					if (opt && opt.text !== '*VARIES*') {
						editor.properties.set(targetIds, { closed: opt.text === localize('yes', "Yes") });
					}
				},
			);

			// Global width
			this.renderNumberInput(panel, store, localize('floorPlan.props.globalWidth', "Global width (mm)"), props.globalWidth, w => {
				if (w >= 0) {
					editor.properties.set(targetIds, { globalWidth: w });
				}
			});

			const lenStr = props.length === 'varies' ? '*VARIES*' : props.length !== undefined ? `${round2(props.length)} mm` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.length', "Length"), lenStr);

			const areaStr = props.area === 'varies' ? '*VARIES*' : props.area !== undefined ? `${round2(props.area)} mm²` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.area', "Area"), areaStr);

		} else if (targetType === 'Text' || targetType === 'MText') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.textSection', "Text")));

			const textVal = props.text === 'varies' ? '*VARIES*' : (props.text ?? '');
			this.renderInputRow(panel, store, localize('floorPlan.props.contents', "Contents"), textVal, '', t => {
				editor.properties.set(targetIds, { text: t });
			});

			this.renderNumberInput(panel, store, localize('floorPlan.props.textHeight', "Height (mm)"), props.textHeight, h => {
				if (h > 0) {
					editor.properties.set(targetIds, { textHeight: h });
				}
			});

			const rotDeg = props.rotation === 'varies' ? 'varies' : props.rotation !== undefined ? round2(props.rotation * 180 / Math.PI) : undefined;
			this.renderNumberInput(panel, store, localize('floorPlan.props.rotation', "Rotation (°)"), rotDeg, deg => {
				editor.properties.set(targetIds, { rotation: deg * Math.PI / 180 });
			});

			const styleVal = props.textStyle === 'varies' ? '*VARIES*' : (props.textStyle ?? 'Standard');
			this.renderInputRow(panel, store, localize('floorPlan.props.style', "Style"), styleVal, 'Standard', s => {
				editor.properties.set(targetIds, { textStyle: s });
			});

		} else if (targetType === 'Dimension') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.dimSection', "Dimension")));

			const dimVal = props.dimensionText === 'varies' ? '*VARIES*' : (props.dimensionText ?? '');
			this.renderInputRow(panel, store, localize('floorPlan.props.dimText', "Text override"), dimVal, '', t => {
				editor.properties.set(targetIds, { dimensionText: t });
			});

			const measStr = props.measurement === 'varies' ? '*VARIES*' : props.measurement !== undefined ? `${round2(props.measurement)} mm` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.measurement', "Measurement"), measStr);

		} else if (targetType === 'Ellipse') {
			append(panel, $('.sa-props-section', undefined, localize('floorPlan.props.geometry', "Geometry")));

			const lenStr = props.length === 'varies' ? '*VARIES*' : props.length !== undefined ? `${round2(props.length)} mm` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.circumference', "Circumference"), lenStr);

			const areaStr = props.area === 'varies' ? '*VARIES*' : props.area !== undefined ? `${round2(props.area)} mm²` : '--';
			appendPropertyRow(panel, localize('floorPlan.props.area', "Area"), areaStr);
		}
	}

	private renderNumberInput(
		panel: HTMLElement,
		store: DisposableStore,
		label: string,
		val: number | 'varies' | undefined,
		apply: (num: number) => void,
	): void {
		const strVal = val === 'varies' ? '*VARIES*' : val !== undefined ? String(round2(val)) : '';
		this.renderInputRow(panel, store, label, strVal, '', text => {
			const n = Number(text.trim());
			if (Number.isFinite(n)) {
				apply(n);
			}
		});
	}

	private renderInputRow(
		panel: HTMLElement,
		store: DisposableStore,
		label: string,
		value: string,
		placeholder: string,
		apply: (text: string) => void,
	): void {
		const cell = $('.floor-plan-prop-control');
		const box = store.add(new InputBox(cell, this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			placeholder,
			ariaLabel: label,
		}));
		box.value = value;
		store.add(applyPropertyOnCommit(box.inputElement, () => {
			const val = box.value.trim();
			if (val !== value && val !== '*VARIES*') {
				apply(val);
			}
		}));
		appendPropertyRow(panel, label, cell).classList.add('editable');
	}

	private renderSelectRow(
		panel: HTMLElement,
		store: DisposableStore,
		label: string,
		options: { text: string }[],
		selectedIndex: number,
		apply: (index: number) => void,
	): void {
		const cell = $('.floor-plan-prop-control');
		const picker = store.add(new SelectBox(
			options,
			Math.max(0, selectedIndex),
			this.contextViewService,
			defaultSelectBoxStyles,
			{ ariaLabel: label },
		));
		picker.render(cell);
		store.add(picker.onDidSelect(({ index }) => {
			apply(index);
		}));
		appendPropertyRow(panel, label, cell).classList.add('editable');
	}
}
