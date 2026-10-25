/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { gridLabel, IGridLine, nextGridLabel } from '../../../services/saengineProject/common/gridLabels.js';
import { newFloorPlan } from '../../../services/saengineProject/common/partSources.js';
import { FLOOR_PLAN_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';

/** The plan view of the floor plan (contrib/saengineCad, FloorPlanEditorInput.EDITOR_ID). */
const FLOOR_PLAN_EDITOR_ID = 'workbench.editor.saengine.floorPlan';

/** Member lists of the floor plan; they are placed in its plan view, not in this form. */
const MEMBER_LISTS = ['columns', 'beams', 'walls', 'slabs', 'footings'];

/** Default spacing for the first added grid line or story, before there is one to repeat [mm]. */
const DEFAULT_SPACING = { x: 6000, y: 5000, story: 3200 };

export interface IStory { readonly id: string; readonly name: string; readonly elevation: number }

/**
 * The grid line after `lines`: the next label (letters for X, numbers for Y, skipping labels
 * in `used`) at the last spacing.
 */
export function nextGridLine(lines: readonly IGridLine[], axis: 'x' | 'y', used: ReadonlySet<string>): IGridLine {
	const last = lines[lines.length - 1];
	let label = last ? nextGridLabel(last.label) : gridLabel(axis, 0);
	while (used.has(label)) {
		label = nextGridLabel(label);
	}
	const spacing = lines.length >= 2 ? last.position - lines[lines.length - 2].position : DEFAULT_SPACING[axis];
	return { label, position: last ? last.position + spacing : 0 };
}

/** The story above `stories`, at the last story height. */
export function nextStory(stories: readonly IStory[], name: (n: number) => string): IStory {
	const last = stories[stories.length - 1];
	const ids = new Set(stories.map(s => s.id));
	let n = stories.length;
	while (ids.has(`L${n}`)) {
		n++;
	}
	const height = stories.length >= 2 ? last.elevation - stories[stories.length - 2].elevation : DEFAULT_SPACING.story;
	return { id: `L${n}`, name: name(n), elevation: last ? last.elevation + height : 0 };
}

function formatMm(value: number): string {
	return `${Number(value.toFixed(3))}`;
}

/**
 * Form for the grids and stories of the floor plan (`05 Floor Plan/floor-plan.json`). Members
 * are placed on them in the plan view; this form only shows them as counts.
 *
 * In the shared editor frame: the form in the main area, the spacings, story heights and member
 * count it implies in the properties panel, "Open in Floor Plan" in the overflow menu.
 */
export class GridsEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.GRIDS_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	private readonly form: SchemaForm;

	private readonly openPlanAction = this._register(new Action('saengine.grids.openFloorPlan', localize('grids.openFloorPlan', "Open in Floor Plan"), undefined, true, async () => this.openFloorPlan()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService commandService: ICommandService,
		@IEditorService private readonly editors: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IFileService private readonly fileService: IFileService,
		@IConfigurationService configurationService: IConfigurationService,
	) {
		super(GridsEditor.ID, group, telemetryService, themeService, storageService, commandService, editors, textModelService, projectService);
		this.trackDeveloperMode(configurationService);
		this.form = instantiationService.createInstance(SchemaForm, {
			root: FLOOR_PLAN_SCHEMA,
			template: defName => clone((TEMPLATES[defName] ?? {}) as JsonObject),
			// A typical floor repeats another story's plan (see the floor plan's Typical Floors).
			references: path => path === 'stories.similarTo' ? this.stories.map(s => s.id) : undefined,
			validate: (path, value) => this.validate(path, value),
			changed: (_path, structural) => {
				this.changed(structural);
				if (!structural) {
					this.renderSummary();
				}
			},
			mode: () => undefined,
			newItem: (path, list) => this.newItem(path, list),
		});
		this._register({ dispose: () => this.form.dispose() });
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		return this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: GridsEditor.ID,
			ariaLabel: localize('grids.toolbar', "Grids & Stories"),
			properties: { title: localize('grids.summary', "Summary") },
		}));
	}

	protected createBody(body: HTMLElement): void {
		this.documentFrame!.setTitle(localize('grids.title', "Grids & Stories"));
		this.documentFrame!.setHelp(localize('grids.intro', "Grid lines and stories of the floor plan. Columns, beams, walls, slabs and footings are placed on them in the Floor Plan; the building model is generated from it."));
		this.container = append(body, $('.sa-form-page'));
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		return this.document && this.documentFrame
			? { primary: [this.documentFrame.togglePropertiesAction], secondary: [this.openPlanAction] }
			: { primary: [] };
	}

	/** The plan view of the same file (its default editor). */
	private async openFloorPlan(): Promise<void> {
		const resource = this.resource;
		if (resource) {
			await this.editors.openEditor({ resource, options: { override: FLOOR_PLAN_EDITOR_ID } }, this.group);
		}
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === FLOOR_PLAN_SCHEMA_ID) {
			return undefined;
		}
		if (value.part === 'floorPlan') {
			// The placeholder written for projects created before the floor plan owned the layout.
			return {
				message: localize('grids.empty', "This project has no floor plan yet. Creating it moves the grids, stories and members of an older building model here."),
				fix: { label: localize('grids.create', "Create Floor Plan"), run: () => this.createFloorPlan() },
			};
		}
		return { message: localize('grids.unexpected', "This file is not a SAEngine floor plan ({0}).", FLOOR_PLAN_SCHEMA_ID) };
	}

	private async createFloorPlan(): Promise<void> {
		const resource = this.resource;
		const part = PROJECT_PARTS.find(p => p.id === 'bim')!;
		let legacy: string | undefined;
		try {
			legacy = resource && (await this.fileService.readFile(joinPath(dirname(dirname(resource)), part.folder, part.mainFile!))).value.toString();
		} catch {
			legacy = undefined;
		}
		this.replaceDocument(newFloorPlan(legacy) as JsonObject);
	}

	// ───────────────────────────── grid lines and stories ─────────────────────────────

	private get grids(): { x: IGridLine[]; y: IGridLine[] } {
		const grids = isObject(this.document?.grids) ? this.document.grids : {};
		const lines = (value: JsonValue | undefined) => (Array.isArray(value) ? value.filter(isObject) : []) as unknown as IGridLine[];
		return { x: lines(grids.x), y: lines(grids.y) };
	}

	private get stories(): IStory[] {
		const stories = this.document?.stories;
		return (Array.isArray(stories) ? stories.filter(isObject) : []) as unknown as IStory[];
	}

	/** The next grid line or story, continuing the sequence and spacing of the last two. */
	private newItem(path: string, list: readonly JsonValue[]): JsonObject | undefined {
		if (path === 'grids.x' || path === 'grids.y') {
			const used = new Set([...this.grids.x, ...this.grids.y].map(g => g.label));
			const line = nextGridLine(list.filter(isObject) as unknown as IGridLine[], path === 'grids.x' ? 'x' : 'y', used);
			return { ...line };
		}
		if (path === 'stories') {
			const story = nextStory(list.filter(isObject) as unknown as IStory[], n => localize('building.levelName', "Level {0}", n));
			return { ...story };
		}
		return undefined;
	}

	/** Unique grid labels (across both axes) and story ids, checked as they are typed. */
	private validate(path: string, value: string): string | undefined {
		const grid = /^grids\.(x|y)\.(\d+)\.label$/.exec(path);
		if (grid) {
			const own = this.grids[grid[1] as 'x' | 'y'][Number(grid[2])];
			if ([...this.grids.x, ...this.grids.y].some(g => g !== own && g.label === value)) {
				return localize('building.duplicateLabel', "Grid line {0} already exists.", value);
			}
		}
		const story = /^stories\.(\d+)\.id$/.exec(path);
		if (story) {
			const own = this.stories[Number(story[1])];
			if (this.stories.some(s => s !== own && s.id === value)) {
				return localize('building.duplicateStory', "Another story already uses the ID {0}.", value);
			}
		}
		return undefined;
	}

	// ───────────────────────────── rendering ─────────────────────────────

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.container);
		this.problemBox = undefined;
		if (!this.document) {
			return;
		}
		this.problemBox = append(this.container, $('.library-problems'));
		this.renderProblems();
		this.renderSummary();
		this.form.render(append(this.container, $('.library-form')), FLOOR_PLAN_SCHEMA, this.document, MEMBER_LISTS);
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
		this.renderStatus();
	}

	/** What the grids are for, or how many problems there are. */
	private renderStatus(): void {
		const count = this.problems.length;
		this.documentFrame?.setStatus(count
			? { severity: 'warning', text: count === 1 ? localize('grids.oneProblem', "1 problem: {0}", this.problems[0].message) : localize('grids.problems', "{0} problems. {1}", count, this.problems[0].message) }
			: {
				text: localize('grids.status', "Columns, beams, walls, slabs and footings are placed on these grids and stories in the Floor Plan."),
				link: { label: localize('grids.openFloorPlan', "Open in Floor Plan"), run: () => void this.openFloorPlan() },
			});
	}

	/** Spacings and story heights, derived from positions and elevations, in the properties panel. */
	private renderSummary(): void {
		const box = this.documentFrame?.properties;
		if (!box) {
			return;
		}
		clearNode(box);
		if (!this.document) {
			return;
		}
		const spacings = (lines: IGridLine[]) => {
			const sorted = [...lines].sort((a, b) => a.position - b.position);
			return sorted.slice(1).map((line, i) => `${sorted[i].label}–${line.label} ${formatMm(line.position - sorted[i].position)}`).join(', ') || '—';
		};
		const stories = [...this.stories].sort((a, b) => a.elevation - b.elevation);
		const heights = stories.slice(1).map((story, i) => `${stories[i].name} → ${story.name} ${formatMm(story.elevation - stories[i].elevation)}`).join(', ') || '—';
		const members = MEMBER_LISTS.map(key => {
			const list = this.document?.[key];
			return Array.isArray(list) ? list.length : 0;
		}).reduce((a, b) => a + b, 0);

		const item = (label: string, value: string) => {
			append(box, $('.sa-props-heading', undefined, label));
			append(box, $('.sa-props-note.grids-summary-value', undefined, value));
		};
		item(localize('building.xSpacing', "X spacing (mm)"), spacings(this.grids.x));
		item(localize('building.ySpacing', "Y spacing (mm)"), spacings(this.grids.y));
		item(localize('building.storyHeights', "Story heights (mm)"), heights);
		const row = append(box, $('.sa-props-row.grids-members'));
		append(row, $('span.name', undefined, localize('building.members', "Placed members")));
		append(row, $('span.value', undefined, String(members)));
	}
}
