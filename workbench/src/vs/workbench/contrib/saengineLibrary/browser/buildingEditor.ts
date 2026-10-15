/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { JsonObject, JsonValue } from './schemaForm.js';

const BIM_SCHEMA_ID = 'saengine.bim/2';
const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';

/** Desktop command generating the building model with the Python models (see `saengine.library.bim`). */
const GENERATE_COMMAND = 'saengine.bim.generate';

interface IGeneratedBuilding {
	readonly text?: string;
	readonly problems?: readonly string[];
}

const ELEMENT_KINDS: readonly { readonly kind: string; readonly label: string }[] = [
	{ kind: 'column', label: localize('element.columns', "Columns") },
	{ kind: 'beam', label: localize('element.beams', "Beams") },
	{ kind: 'wall', label: localize('element.walls', "Walls") },
	{ kind: 'slab', label: localize('element.slabs', "Slabs") },
	{ kind: 'footing', label: localize('element.footings', "Footings") },
];

/**
 * The building model (`06 BIM/bim.json`), generated from the floor plan. The floor plan owns the
 * layout; this editor shows what was built from it, says when the floor plan has changed since,
 * and rebuilds on request. Elements that belong to the building model itself (no floor-plan
 * source) are kept when it is rebuilt.
 */
export class BuildingEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.BUILDING_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ICommandService private readonly commands: ICommandService,
		@IEditorService private readonly editors: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super(BuildingEditor.ID, group, telemetryService, themeService, storageService, commands, editors, textModelService, projectService);
	}

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor'));
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === BIM_SCHEMA_ID) {
			return undefined;
		}
		const build = { label: localize('building.build', "Build from Floor Plan"), run: () => this.build() };
		if (value.schema === 'saengine.bim/1') {
			return {
				message: localize('building.legacy', "This building model still holds the layout, which the Floor Plan owns now. Open the Floor Plan and create it (it takes the layout over from this file), then build the building model from it."),
				fix: build,
			};
		}
		if (value.part === 'bim') {
			return { message: localize('building.empty', "The building model has not been built from the Floor Plan yet."), fix: build };
		}
		return { message: localize('building.unexpected', "This file is not a SAEngine building model ({0}).", BIM_SCHEMA_ID) };
	}

	protected override updateFromUpstream(): void {
		void this.build();
	}

	/** Generates the model from the current floor plan, keeping the model's own elements. */
	private async build(): Promise<void> {
		const floorPlan = this.upstreamText;
		let parsed: JsonValue | undefined;
		try {
			parsed = floorPlan ? JSON.parse(floorPlan) : undefined;
		} catch {
			parsed = undefined;
		}
		if (!floorPlan || !isObject(parsed) || parsed.schema !== FLOOR_PLAN_SCHEMA_ID) {
			this.notificationService.warn(localize('building.noFloorPlan', "The Floor Plan has no layout yet. Open it and create it first."));
			return;
		}
		let result: IGeneratedBuilding | undefined;
		try {
			result = await this.commands.executeCommand<IGeneratedBuilding>(GENERATE_COMMAND, floorPlan, this.document ? JSON.stringify(this.document) : undefined);
		} catch (error) {
			this.notificationService.error(localize('building.generateFailed', "The building model could not be built: {0}", String(error)));
			return;
		}
		if (result?.text) {
			this.replaceDocument(JSON.parse(result.text));
		} else {
			this.notificationService.warn(localize('building.problems', "Fix the Floor Plan first: {0}", (result?.problems ?? []).join('; ')));
		}
	}

	private openFloorPlan(): void {
		const resource = this.resource;
		const part = PROJECT_PARTS.find(p => p.id === 'floorPlan')!;
		if (resource) {
			void this.editors.openEditor({ resource: joinPath(dirname(dirname(resource)), part.folder, part.mainFile!) });
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.container);
		this.problemBox = undefined;
		append(this.container, $('h2', undefined, localize('building.title', "Building Model")));
		append(this.container, $('p.building-intro', undefined, localize('building.intro', "Built from the Floor Plan, which owns the grids, stories and members. Update it when the Floor Plan changes; elements added to the building model itself are kept. The 3D view and IFC export come with Part 6.")));

		const actions = append(this.container, $('.building-actions'));
		const open = this.viewDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		open.label = `$(${Codicon.symbolArray.id}) ${localize('building.openFloorPlan', "Open Floor Plan")}`;
		this.viewDisposables.add(open.onDidClick(() => this.openFloorPlan()));
		if (!this.document) {
			return;
		}
		const rebuild = this.viewDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		rebuild.label = `$(${Codicon.refresh.id}) ${localize('building.rebuild', "Rebuild from Floor Plan")}`;
		this.viewDisposables.add(rebuild.onDidClick(() => this.build()));

		this.problemBox = append(this.container, $('.library-problems'));
		this.renderProblems();

		const stories = (Array.isArray(this.document.stories) ? this.document.stories.filter(isObject) : [])
			.sort((a, b) => Number(a.elevation) - Number(b.elevation));
		const elements = Array.isArray(this.document.elements) ? this.document.elements.filter(isObject) : [];

		append(this.container, $('h3', undefined, localize('building.stories', "Stories")));
		const storyTable = append(this.container, $('.building-table'));
		for (const header of [localize('building.story', "Story"), localize('building.storyId', "ID"), localize('building.elevation', "Elevation (mm)"), localize('building.height', "Height (mm)")]) {
			append(storyTable, $('span.header', undefined, header));
		}
		stories.forEach((story, i) => {
			const above = stories[i + 1];
			append(storyTable, $('span', undefined, String(story.name ?? story.id)));
			append(storyTable, $('span', undefined, String(story.id)));
			append(storyTable, $('span.number', undefined, String(story.elevation)));
			append(storyTable, $('span.number', undefined, above ? String(Number(above.elevation) - Number(story.elevation)) : '—'));
		});
		if (!stories.length) {
			append(this.container, $('p.building-intro', undefined, localize('building.noStories', "No stories yet.")));
		}

		append(this.container, $('h3', undefined, localize('building.elements', "Elements")));
		const elementTable = append(this.container, $('.building-table'));
		for (const header of [localize('building.kind', "Kind"), localize('building.fromFloorPlan', "From Floor Plan"), localize('building.own', "Own"), localize('building.total', "Total")]) {
			append(elementTable, $('span.header', undefined, header));
		}
		for (const { kind, label } of ELEMENT_KINDS) {
			const ofKind = elements.filter(e => e.kind === kind);
			const generated = ofKind.filter(e => typeof e.source === 'string').length;
			append(elementTable, $('span', undefined, label));
			append(elementTable, $('span.number', undefined, String(generated)));
			append(elementTable, $('span.number', undefined, String(ofKind.length - generated)));
			append(elementTable, $('span.number', undefined, String(ofKind.length)));
		}
	}

	protected renderProblems(): void {
		const box = this.problemBox;
		if (!box) {
			return;
		}
		clearNode(box);
		box.classList.toggle('visible', this.problems.length > 0);
		for (const problem of this.problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(row, $('span', undefined, problem.message));
		}
	}
}
