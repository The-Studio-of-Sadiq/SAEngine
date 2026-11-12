/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modelEditors.css';
import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEFAULT_STRUCTURE, STRUCTURE_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

const STRUCTURE_SCHEMA_ID = 'saengine.structure/1';

/** Lists of the structural model, the template of a new entry and its id prefix. */
const LISTS: { readonly [list: string]: { readonly template: string; readonly prefix: string } } = {
	grids: { template: 'CartesianGrid', prefix: 'G' },
	members: { template: 'Member', prefix: 'M' },
	areas: { template: 'Area', prefix: 'A' },
	blocks: { template: 'Block', prefix: 'K' },
	supports: { template: 'Support', prefix: 'SP' },
};

/**
 * The structural model of a special structure (`05 Structural Model/structure.json`) as a form,
 * in the shared editor frame: grid systems, members, areas and supports in 3D. Part 5 owns it;
 * the building model is built from it. This form edits every entry; the 3D modeller draws them.
 */
export class StructureEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.STRUCTURE_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	private objects: JsonObject[] = [];
	private readonly form: SchemaForm;
	private readonly modelerAction = this._register(new Action('saengine.structure.openModeler', localize('structure.openModeler', "Open the 3D Modeller"), ThemeIcon.asClassName(Codicon.symbolStructure), true, async () => this.openModeler()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiation: IInstantiationService,
		@ICommandService commandService: ICommandService,
		@IEditorService private readonly editors: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService project: ISaengineProjectService,
		@IConfigurationService configurationService: IConfigurationService,
	) {
		super(StructureEditor.ID, group, telemetryService, themeService, storageService, commandService, editors, textModelService, project);
		this.trackDeveloperMode(configurationService);
		this.form = instantiation.createInstance(SchemaForm, {
			root: STRUCTURE_SCHEMA,
			template: defName => clone((TEMPLATES[defName] ?? {}) as JsonObject),
			references: path => this.references(path),
			validate: () => undefined,
			changed: (_path, structural) => this.changed(structural),
			mode: () => undefined,
			newItem: (path, list) => this.newItem(path, list),
		});
		this._register({ dispose: () => this.form.dispose() });
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		const frame = this._register(this.instantiation.createInstance(EditorFrame, parent, {
			id: StructureEditor.ID,
			ariaLabel: localize('structure.toolbar', "Structural Model"),
		}));
		frame.element.classList.add('saengine-structure-form');
		frame.setTitle(localize('structure.formTitle', "Structural Model: Grids and Values"));
		// What the model is: the frame's "?" (hover, click or Enter), no paragraph over the form.
		frame.setHelp(localize('structure.intro', "The structure drawn in 3D: grid systems to draw on, members between two points, flat areas (slabs, walls, shell panels) and supports. Coordinates are in mm with Z up. The building model (06 BIM) and the analysis are built from it."));
		return frame;
	}

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor.structure-editor'));
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		return { primary: this.document ? [this.modelerAction] : [] };
	}

	/** The 3D modeller of the same file (its default editor). */
	private openModeler(): void {
		const resource = this.resource;
		if (resource) {
			void this.editors.openEditor({ resource, options: { override: LibraryEditorInput.STRUCTURE_MODELER_ID } });
		}
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === STRUCTURE_SCHEMA_ID) {
			return undefined;
		}
		return {
			message: localize('structure.unexpected', "This file is not a SAEngine structural model ({0}).", STRUCTURE_SCHEMA_ID),
			fix: { label: localize('structure.create', "Start a New Structural Model"), run: () => this.replaceDocument(clone(DEFAULT_STRUCTURE as JsonObject)) },
		};
	}

	protected override onCompanionChanged(text: string): void {
		let parsed: JsonValue | undefined;
		try {
			parsed = JSON.parse(text);
		} catch {
			parsed = undefined;
		}
		this.objects = isObject(parsed) && Array.isArray(parsed.objects) ? parsed.objects.filter(isObject) : [];
	}

	/** Object types of the kinds a member or an area can be. */
	private references(path: string): readonly string[] | undefined {
		const kinds = /^members\.\d+\.type$/.test(path) ? ['beam', 'column', 'brace'] : /^areas\.\d+\.type$/.test(path) ? ['slab', 'wall'] : /^blocks\.\d+\.type$/.test(path) ? ['solid'] : undefined;
		return kinds && kinds.flatMap(kind => this.objects.filter(o => o.kind === kind).map(o => String(o.id)));
	}

	private newItem(path: string, list: readonly JsonValue[]): JsonObject | undefined {
		const spec = LISTS[path];
		if (!spec) {
			return undefined;
		}
		const used = new Set([...(this.document?.members as JsonValue[] ?? []), ...(this.document?.areas as JsonValue[] ?? []), ...(this.document?.blocks as JsonValue[] ?? []), ...list].filter(isObject).map(e => String(e.id)));
		let n = 1;
		while (used.has(`${spec.prefix}${n}`)) {
			n++;
		}
		const item: JsonObject = { ...clone(TEMPLATES[spec.template] as JsonObject), id: `${spec.prefix}${n}` };
		const types = path === 'members' || path === 'areas' || path === 'blocks' ? this.references(`${path}.0.type`) : undefined;
		if (types?.length) {
			item.type = types[0];
		}
		return item;
	}

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.container);
		this.problemBox = undefined;
		if (!this.document) {
			return;
		}
		this.problemBox = append(this.container, $('.library-problems'));
		this.renderProblems();
		this.form.render(append(this.container, $('.library-form')), STRUCTURE_SCHEMA, this.document);
	}

	protected renderProblems(): void {
		const box = this.problemBox;
		const elements = ['members', 'areas', 'blocks', 'supports'].reduce((n, list) => n + (Array.isArray(this.document?.[list]) ? (this.document![list] as JsonValue[]).length : 0), 0);
		if (this.document) {
			this.documentFrame?.setStatus(this.problems.length
				? { severity: 'warning', text: localize('structure.statusProblems', "{0} elements, {1} problem(s): see the list above the form", elements, this.problems.length) }
				: { text: localize('structure.status', "{0} elements; edit them here or draw them in the 3D modeller", elements), link: { label: localize('structure.openModelerLink', "Open the 3D Modeller"), run: () => this.openModeler() } });
		}
		if (!box) {
			return;
		}
		clearNode(box);
		box.classList.toggle('visible', this.problems.length > 0);
		for (const problem of this.problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(row, $('span', undefined, problem.path ? `${problem.path}: ${problem.message}` : problem.message));
		}
	}
}
