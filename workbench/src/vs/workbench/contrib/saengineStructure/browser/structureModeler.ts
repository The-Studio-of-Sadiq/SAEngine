/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/structureModeler.css';
import type { ModelerEntity, ModelerHit, ModelerTheme, ModelerView, ModelPoint, StructureModeler } from '@saengine/fem-viewer';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isKeyboardEvent } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { chartsBlue, chartsGreen, chartsLines, chartsOrange, chartsPurple, chartsYellow } from '../../../../platform/theme/common/colors/chartsColors.js';
import { editorBackground, editorForeground } from '../../../../platform/theme/common/colors/editorColors.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { loadViewerModule } from '../../saengineFem/browser/viewerModule.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { addArea, addMember, addSupport, copyElements, divideMember, EditResult, isStructure, mirrorElements, moveElements, parseOffset, removeElements } from './structureEdits.js';
import { gridGeometry, Json, list, modelerScene, typeKinds } from './structureGeometry.js';

type Tool = 'select' | 'member' | 'area' | 'support' | 'move' | 'copy' | 'mirror' | 'divide' | 'delete';

const TOOLS: readonly { readonly tool: Tool; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ tool: 'select', label: localize('modeler.select', "Select"), icon: Codicon.inspect },
	{ tool: 'member', label: localize('modeler.member', "Member"), icon: Codicon.dash },
	{ tool: 'area', label: localize('modeler.area', "Area"), icon: Codicon.symbolArray },
	{ tool: 'support', label: localize('modeler.support', "Support"), icon: Codicon.pinned },
	{ tool: 'move', label: localize('modeler.move', "Move"), icon: Codicon.move },
	{ tool: 'copy', label: localize('modeler.copy', "Copy"), icon: Codicon.copy },
	{ tool: 'mirror', label: localize('modeler.mirror', "Mirror"), icon: Codicon.mirror },
	{ tool: 'divide', label: localize('modeler.divide', "Divide"), icon: Codicon.splitHorizontal },
	{ tool: 'delete', label: localize('modeler.delete', "Delete"), icon: Codicon.trash },
];

const VIEWS: readonly { readonly view: ModelerView; readonly label: string }[] = [
	{ view: '3d', label: localize('modeler.view3d', "3D") },
	{ view: 'top', label: localize('modeler.viewTop', "Top") },
	{ view: 'front', label: localize('modeler.viewFront', "Front") },
	{ view: 'side', label: localize('modeler.viewSide', "Side") },
];

/** Object type kinds each drawing tool places. */
const TOOL_KINDS: { readonly [tool in Tool]?: readonly string[] } = {
	member: ['beam', 'column', 'brace'],
	area: ['slab', 'wall'],
};

const SUPPORT_FIXITIES = ['fixed', 'pinned'] as const;

function hint(tool: Tool, picked: number, selected: number): string {
	switch (tool) {
		case 'select': return localize('hint.select', "Click an element to select it; Shift+click adds to the selection. Drag to orbit, right-drag to pan, wheel to zoom.");
		case 'member': return picked ? localize('hint.memberEnd', "Click the end of the member (Esc stops the chain).") : localize('hint.memberStart', "Click the start of the member: a grid point, a member end or a free point on the work level.");
		case 'area': return picked < 3 ? localize('hint.areaCorner', "Click the corners of the area in order ({0} so far).", picked) : localize('hint.areaClose', "Click the first corner, press Enter or right-click to finish the area.");
		case 'support': return localize('hint.support', "Click a member end or area corner to support it.");
		case 'move':
		case 'copy':
			return !selected ? localize('hint.selectFirst', "Click what to {0} (or select it first).", tool === 'move' ? localize('hint.moveVerb', "move") : localize('hint.copyVerb', "copy"))
				: picked ? localize('hint.target', "Click the target point.")
					: localize('hint.base', "Click a base point, or type the offset \"dx, dy, dz\"{0} and press Enter.", tool === 'copy' ? localize('hint.count', " (add \", n\" for n copies)") : '');
		case 'mirror': return !selected ? localize('hint.mirrorSelect', "Select what to mirror first.") : picked ? localize('hint.mirrorSecond', "Click the second point of the mirror line (in plan).") : localize('hint.mirrorFirst', "Click the first point of the mirror line (in plan).");
		case 'divide': return localize('hint.divide', "Click a member to divide it into the number of parts typed beside.");
		case 'delete': return localize('hint.delete', "Click an element to delete it, or press Delete to remove the selection.");
	}
}

/**
 * The 3D modeller of a special structure's structural model (`05 Structural Model/structure.json`):
 * draw members, areas and supports on the grid systems, and move, copy, mirror, divide or delete
 * them. Every change is one undoable edit of the file; the form stays available beside.
 */
export class StructureModelerEditor extends EditorPane {

	static readonly ID = LibraryEditorInput.STRUCTURE_MODELER_ID;

	private root!: HTMLElement;
	private viewport!: HTMLElement;
	private status!: HTMLElement;
	private message!: HTMLElement;
	private typePicker!: SelectBox;
	private levelPicker!: SelectBox;
	private valueBox!: InputBox;
	private typeGroup!: HTMLElement;
	private valueGroup!: HTMLElement;
	private readonly toolButtons = new Map<Tool, Button>();

	private modeler: StructureModeler | undefined;
	private readonly modelerDisposable = this._register(new MutableDisposable());
	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.render(), 50));

	private model: ITextModel | undefined;
	private objects: ITextModel | undefined;
	private doc: Json | undefined;
	private kinds = new Map<string, string>();
	private levels: { label: string; z: number }[] = [];
	private level: number | undefined;
	private tool: Tool = 'select';
	private readonly types = new Map<Tool, string>();
	private typeOptions: string[] = [];
	private points: ModelPoint[] = [];
	private selection: ModelerEntity[] = [];
	private hover: ModelerHit = {};
	private notice: string | undefined;
	private writing = false;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(StructureModelerEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.root = append(parent, $('.saengine-structure-modeler', { tabIndex: -1 }));
		const toolbar = append(this.root, $('.modeler-toolbar'));
		const group = (className: string) => append(toolbar, $(`.modeler-group.${className}`));

		const tools = group('tools');
		for (const { tool, label, icon } of TOOLS) {
			const button = this._register(new Button(tools, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: label }));
			button.label = `$(${icon.id}) ${label}`;
			this._register(button.onDidClick(() => this.setTool(tool)));
			this.toolButtons.set(tool, button);
		}

		this.typeGroup = group('type');
		append(this.typeGroup, $('span.modeler-label', undefined, localize('modeler.type', "Type")));
		this.typePicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('modeler.typeAria', "Object type to draw") }));
		this.typePicker.render(append(this.typeGroup, $('.modeler-select.type')));
		this._register(this.typePicker.onDidSelect(({ index }) => this.types.set(this.tool, this.typeOptions[index])));

		this.valueGroup = group('value');
		this.valueBox = this._register(new InputBox(this.valueGroup, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles }));
		this._register(addDisposableListener(this.valueBox.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				this.applyTyped();
			}
		}));

		const levels = group('level');
		append(levels, $('span.modeler-label', undefined, localize('modeler.level', "Work level")));
		this.levelPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('modeler.levelAria', "Level free points are drawn on") }));
		this.levelPicker.render(append(levels, $('.modeler-select.level')));
		this._register(this.levelPicker.onDidSelect(({ index }) => {
			this.level = this.levels[index - 1]?.z;
			this.modeler?.setWorkPlane(this.level);
		}));

		const views = group('views');
		for (const { view, label } of VIEWS) {
			const button = this._register(new Button(views, { ...defaultButtonStyles, secondary: true }));
			button.label = label;
			this._register(button.onDidClick(() => void this.modeler?.setView(view)));
		}
		const form = this._register(new Button(group('links'), { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('modeler.formTitle', "Edit grid systems and every value of the structural model in the form, beside") }));
		form.label = `$(${Codicon.table.id}) ${localize('modeler.form', "Grids & Values")}`;
		this._register(form.onDidClick(() => this.openForm()));

		this.status = append(this.root, $('.modeler-status'));
		this.viewport = append(this.root, $('.modeler-viewport'));
		this.message = append(this.viewport, $('.modeler-message'));

		this._register(addDisposableListener(this.root, EventType.KEY_DOWN, e => this.onKey(e)));
		this.updateToolbar();
	}

	override async setInput(input: LibraryEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.points = [];
		this.selection = [];
		// The project root is two levels up (05 Structural Model/structure.json); the project itself
		// may not be detected yet when the editor is restored at startup.
		const objectsPart = partById('objects')!;
		try {
			const references = await Promise.all([
				this.textModelService.createModelReference(input.resource),
				this.textModelService.createModelReference(joinPath(dirname(dirname(input.resource)), objectsPart.folder, objectsPart.mainFile!)),
			]);
			if (token.isCancellationRequested || this.input !== input) {
				references.forEach(r => r.dispose());
				return;
			}
			references.forEach(r => this.inputDisposables.add(r));
			[this.model, this.objects] = references.map(r => r.object.textEditorModel);
		} catch (error) {
			this.showMessage(localize('modeler.readFailed', "The structural model could not be read: {0}", String(error)));
			return;
		}
		for (const model of [this.model, this.objects]) {
			if (model) {
				this.inputDisposables.add(model.onDidChangeContent(() => {
					if (!this.writing) {
						this.notice = undefined; // undo, redo or another editor changed it
					}
					this.renderScheduler.schedule();
				}));
			}
		}
		await this.ensureModeler();
		this.render();
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.model = undefined;
		this.objects = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.root.style.width = `${dimension.width}px`;
		this.root.style.height = `${dimension.height}px`;
		this.modeler?.layout();
	}

	override focus(): void {
		super.focus();
		this.root.focus();
	}

	override updateStyles(): void {
		super.updateStyles();
		this.modeler?.setTheme(this.computeTheme());
	}

	private async ensureModeler(): Promise<void> {
		if (this.modeler) {
			return;
		}
		try {
			const { createStructureModeler } = await loadViewerModule();
			if (this.modeler) {
				return;
			}
			const modeler = createStructureModeler(this.viewport, {
				theme: this.computeTheme(),
				onPointerMove: hit => this.onHover(hit),
				onClick: (hit, modifiers) => this.onClick(hit, modifiers.shift, modifiers.secondary),
			});
			this.modeler = modeler;
			this.modelerDisposable.value = toDisposable(() => {
				modeler.dispose();
				this.modeler = undefined;
			});
			modeler.layout();
		} catch (error) {
			this.showMessage(localize('modeler.loadFailed', "The 3D view could not be loaded: {0}", String(error)));
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		let parsed: unknown;
		try {
			parsed = this.model ? JSON.parse(this.model.getValue()) : undefined;
		} catch {
			parsed = undefined;
		}
		if (!isStructure(parsed)) {
			this.doc = undefined;
			this.showMessage(localize('modeler.invalid', "The structural model has errors the 3D view cannot show. Fix them in Grids & Values (the form) or the JSON."));
			return;
		}
		this.showMessage(undefined);
		this.doc = parsed;
		let objects: unknown;
		try {
			objects = this.objects ? JSON.parse(this.objects.getValue()) : undefined;
		} catch {
			objects = undefined;
		}
		this.kinds = typeKinds(objects);
		// Drop selected elements that no longer exist (deleted, or undone).
		const exists = (e: ModelerEntity) => list(parsed[e.kind === 'member' ? 'members' : e.kind === 'area' ? 'areas' : 'supports']).some(x => x.id === e.id);
		this.selection = this.selection.filter(exists);

		const levels = gridGeometry(parsed.grids).levels;
		if (JSON.stringify(levels) !== JSON.stringify(this.levels)) {
			this.levels = levels;
			if (this.level === undefined || !levels.some(l => l.z === this.level)) {
				this.level = levels[0]?.z;
			}
			this.levelPicker.setOptions([
				{ text: localize('modeler.snapOnly', "None (snap points only)") },
				...levels.map(l => ({ text: `${l.label} (${l.z} mm)` })),
			], Math.max(0, levels.findIndex(l => l.z === this.level) + 1));
		}
		this.modeler?.setWorkPlane(this.level);
		this.modeler?.setScene(modelerScene(parsed, this.kinds));
		this.modeler?.setSelection(this.selection);
		this.updateToolbar();
		this.updatePreview();
	}

	private updateToolbar(): void {
		for (const [tool, button] of this.toolButtons) {
			button.element.classList.toggle('active', tool === this.tool);
			button.element.setAttribute('aria-pressed', String(tool === this.tool));
		}
		const kinds = TOOL_KINDS[this.tool];
		this.typeGroup.classList.toggle('hidden', !kinds && this.tool !== 'support');
		if (kinds) {
			this.typeOptions = [...this.kinds].filter(([, kind]) => kinds.includes(kind)).map(([id]) => id);
			const chosen = this.types.get(this.tool);
			const index = chosen ? this.typeOptions.indexOf(chosen) : -1;
			this.typePicker.setOptions(this.typeOptions.length ? this.typeOptions.map(id => ({ text: `${id} (${this.kinds.get(id)})` })) : [{ text: localize('modeler.noTypes', "No types: add them in Object Types") }], Math.max(0, index));
			if (index < 0 && this.typeOptions.length) {
				this.types.set(this.tool, this.typeOptions[0]);
			}
		} else if (this.tool === 'support') {
			this.typeOptions = [...SUPPORT_FIXITIES];
			this.typePicker.setOptions([{ text: localize('modeler.fixed', "Fixed") }, { text: localize('modeler.pinned', "Pinned") }], Math.max(0, this.typeOptions.indexOf(this.types.get('support') ?? 'fixed')));
		}
		const typed = this.tool === 'move' || this.tool === 'copy' || this.tool === 'divide';
		this.valueGroup.classList.toggle('hidden', !typed);
		if (typed) {
			this.valueBox.setPlaceHolder(this.tool === 'divide' ? localize('modeler.partsPlaceholder', "Parts (e.g. 4)") : this.tool === 'copy' ? localize('modeler.copyPlaceholder', "dx, dy, dz[, copies] (mm)") : localize('modeler.movePlaceholder', "dx, dy, dz (mm)"));
		}
		this.renderStatus();
	}

	private renderStatus(): void {
		clearNode(this.status);
		append(this.status, $('span', undefined, this.notice ?? hint(this.tool, this.points.length, this.selection.length)));
		if (this.selection.length) {
			append(this.status, $('span.modeler-selection', undefined, localize('modeler.selected', "Selected: {0}", this.selection.map(s => s.id).join(', '))));
		}
		const at = this.hover.point;
		if (at) {
			append(this.status, $('span.modeler-coordinates', undefined, `${at.map(v => Math.round(v)).join(', ')} mm${this.hover.snap && this.hover.snap !== 'plane' ? ` · ${this.hover.snap}` : ''}`));
		}
	}

	private updatePreview(): void {
		const modeler = this.modeler;
		if (!modeler) {
			return;
		}
		const at = this.hover.point;
		modeler.setCursor(at);
		const points = at ? [...this.points, at] : this.points;
		switch (this.tool) {
			case 'area': modeler.setPreview(points, points.length > 2); break;
			case 'member':
			case 'move':
			case 'copy':
			case 'mirror':
				modeler.setPreview(this.points.length ? points : undefined);
				break;
			default: modeler.setPreview(undefined);
		}
	}

	private showMessage(text: string | undefined): void {
		this.message.classList.toggle('visible', !!text);
		this.message.textContent = text ?? '';
	}

	// ───────────────────────────── tools ─────────────────────────────

	private setTool(tool: Tool): void {
		this.tool = tool;
		this.points = [];
		this.notice = undefined;
		this.valueBox.value = '';
		this.updateToolbar();
		this.updatePreview();
		this.root.focus();
	}

	private onHover(hit: ModelerHit): void {
		this.hover = hit;
		this.renderStatus();
		this.updatePreview();
	}

	private onClick(hit: ModelerHit, shift: boolean, secondary: boolean): void {
		const doc = this.doc;
		if (!doc) {
			return;
		}
		this.notice = undefined;
		if (secondary) {
			if (this.tool === 'area' && this.points.length >= 3) {
				this.finishArea();
			} else {
				this.points = [];
			}
			this.renderStatus();
			this.updatePreview();
			return;
		}
		const p = hit.point;
		switch (this.tool) {
			case 'select':
				this.select(hit.entity, shift);
				break;
			case 'member':
				if (p && this.points.length) {
					// Chains: the end is the start of the next member.
					if (this.apply(addMember(doc, this.types.get('member') ?? '', this.points[0], p))) {
						this.points = [p];
					}
				} else if (p) {
					this.points = [p];
				}
				break;
			case 'area':
				if (p && this.points.length >= 3 && p.every((v, i) => Math.abs(v - this.points[0][i]) < 1)) {
					this.finishArea();
				} else if (p) {
					this.points.push(p);
				}
				break;
			case 'support':
				if (p) {
					this.apply(addSupport(doc, p, (this.types.get('support') ?? 'fixed') as 'fixed' | 'pinned'));
				}
				break;
			case 'move':
			case 'copy':
				if (!this.selection.length) {
					this.select(hit.entity, false);
				} else if (p && this.points.length) {
					const base = this.points[0];
					const delta: ModelPoint = [p[0] - base[0], p[1] - base[1], p[2] - base[2]];
					this.points = [];
					this.apply(this.tool === 'move' ? moveElements(doc, this.selection, delta) : copyElements(doc, this.selection, delta), this.tool === 'copy');
				} else if (p) {
					this.points = [p];
				}
				break;
			case 'mirror':
				if (!this.selection.length) {
					this.select(hit.entity, false);
				} else if (p && this.points.length) {
					const first = this.points[0];
					this.points = [];
					this.apply(mirrorElements(doc, this.selection, first, p), true);
				} else if (p) {
					this.points = [p];
				}
				break;
			case 'divide':
				if (hit.entity?.kind === 'member') {
					this.apply(divideMember(doc, hit.entity.id, Number(this.valueBox.value || 2)));
				}
				break;
			case 'delete':
				if (hit.entity) {
					this.apply(removeElements(doc, [hit.entity]));
				}
				break;
		}
		this.renderStatus();
		this.updatePreview();
	}

	private select(entity: ModelerEntity | undefined, add: boolean): void {
		if (!entity) {
			if (!add) {
				this.selection = [];
			}
		} else if (add) {
			const has = this.selection.some(s => s.kind === entity.kind && s.id === entity.id);
			this.selection = has ? this.selection.filter(s => !(s.kind === entity.kind && s.id === entity.id)) : [...this.selection, entity];
		} else {
			this.selection = [entity];
		}
		this.modeler?.setSelection(this.selection);
	}

	private finishArea(): void {
		const doc = this.doc;
		if (doc && this.apply(addArea(doc, this.types.get('area') ?? '', this.points))) {
			this.points = [];
		}
	}

	/** Move or copy by the typed offset, or the count of parts for Divide. */
	private applyTyped(): void {
		const doc = this.doc;
		if (!doc || (this.tool !== 'move' && this.tool !== 'copy')) {
			return;
		}
		const offset = parseOffset(this.valueBox.value);
		if (!offset) {
			this.notice = localize('modeler.badOffset', "Type the offset as \"dx, dy, dz\" in mm{0}.", this.tool === 'copy' ? localize('modeler.badOffsetCount', ", with \", n\" for n copies") : '');
		} else {
			this.points = [];
			this.apply(this.tool === 'move' ? moveElements(doc, this.selection, offset.delta) : copyElements(doc, this.selection, offset.delta, offset.count ?? 1), this.tool === 'copy');
		}
		this.renderStatus();
		this.updatePreview();
	}

	private onKey(e: KeyboardEvent): void {
		if (!isKeyboardEvent(e) || e.target === this.valueBox.inputElement) {
			return;
		}
		if (e.key === 'Escape') {
			if (this.points.length) {
				this.points = [];
			} else if (this.tool !== 'select') {
				this.setTool('select');
			} else {
				this.select(undefined, false);
			}
		} else if (e.key === 'Enter' && this.tool === 'area' && this.points.length >= 3) {
			this.finishArea();
		} else if ((e.key === 'Delete' || e.key === 'Backspace') && this.selection.length && this.doc) {
			this.apply(removeElements(this.doc, this.selection));
			this.selection = [];
		} else {
			return;
		}
		e.preventDefault();
		this.renderStatus();
		this.updatePreview();
	}

	/** Writes a successful edit (selecting what it made when `selectResult`); shows why not otherwise. */
	private apply(result: EditResult, selectResult = false): boolean {
		if (!result.ok) {
			this.notice = result.error;
			return false;
		}
		if (selectResult) {
			const kindOf = (id: string): ModelerEntity['kind'] => list(result.doc.members).some(m => m.id === id) ? 'member' : list(result.doc.areas).some(a => a.id === id) ? 'area' : 'support';
			this.selection = result.ids.map(id => ({ kind: kindOf(id), id }));
		}
		this.write(result.doc);
		this.notice = localize('modeler.done', "{0}: {1}.", TOOLS.find(t => t.tool === this.tool)?.label ?? '', result.ids.join(', '));
		return true;
	}

	/** Replaces the structural model with `value` as one undoable edit. */
	private write(value: Json): void {
		const model = this.model;
		if (!model || model.isDisposed()) {
			return;
		}
		this.writing = true;
		try {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: JSON.stringify(value, undefined, '\t') + '\n' }], () => null);
			model.pushStackElement();
		} finally {
			this.writing = false;
		}
		this.renderScheduler.cancel();
		this.render();
	}

	private openForm(): void {
		const input = this.input as LibraryEditorInput | undefined;
		if (input) {
			void this.editorService.openEditor({ resource: input.resource, options: { override: LibraryEditorInput.STRUCTURE_EDITOR_ID, pinned: true } }, SIDE_GROUP);
		}
	}

	private computeTheme(): Partial<ModelerTheme> {
		const theme = this.themeService.getColorTheme();
		const color = (id: string) => theme.getColor(id)?.toString();
		return {
			background: color(editorBackground),
			grid: color(chartsLines),
			gridPoint: color(chartsLines),
			member: color(chartsBlue),
			column: color(chartsPurple),
			brace: color(chartsOrange),
			slab: color(chartsGreen),
			wall: color(chartsOrange),
			support: color(chartsGreen),
			selection: color(chartsYellow),
			preview: color(editorForeground),
			cursor: color(chartsYellow),
		};
	}
}
