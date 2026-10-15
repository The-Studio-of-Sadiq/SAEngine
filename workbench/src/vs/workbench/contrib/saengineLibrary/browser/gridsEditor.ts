/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { newFloorPlan } from '../../../services/saengineProject/common/partSources.js';
import { FLOOR_PLAN_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { clone, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';

/** Member lists of the floor plan; they are placed in its plan view, not in this form. */
const MEMBER_LISTS = ['columns', 'beams', 'walls', 'slabs', 'footings'];

/** Default spacing for the first added grid line or story, before there is one to repeat [mm]. */
const DEFAULT_SPACING = { x: 6000, y: 5000, story: 3200 };

export interface IGridLine { readonly label: string; readonly position: number }
export interface IStory { readonly id: string; readonly name: string; readonly elevation: number }

/** "A" -> "B", "Z" -> "AA", "AZ" -> "BA" (spreadsheet-style column letters). */
export function nextLetters(label: string): string {
	const chars = label.toUpperCase().split('');
	for (let i = chars.length - 1; i >= 0; i--) {
		if (chars[i] !== 'Z') {
			chars[i] = String.fromCharCode(chars[i].charCodeAt(0) + 1);
			return chars.join('');
		}
		chars[i] = 'A';
	}
	return 'A' + chars.join('');
}

function nextLabel(label: string): string {
	return /^\d+$/.test(label) ? String(Number(label) + 1) : /^[A-Za-z]+$/.test(label) ? nextLetters(label) : `${label}1`;
}

/**
 * The grid line after `lines`: the next label (letters for X, numbers for Y, skipping labels
 * in `used`) at the last spacing.
 */
export function nextGridLine(lines: readonly IGridLine[], axis: 'x' | 'y', used: ReadonlySet<string>): IGridLine {
	const last = lines[lines.length - 1];
	let label = last ? nextLabel(last.label) : (axis === 'x' ? 'A' : '1');
	while (used.has(label)) {
		label = nextLabel(label);
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
 */
export class GridsEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.GRIDS_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	private summary: HTMLElement | undefined;
	private readonly form: SchemaForm;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@ICommandService commandService: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IFileService private readonly fileService: IFileService,
	) {
		super(GridsEditor.ID, group, telemetryService, themeService, storageService, commandService, editorService, textModelService, projectService);
		this.form = instantiationService.createInstance(SchemaForm, {
			root: FLOOR_PLAN_SCHEMA,
			template: defName => clone((TEMPLATES[defName] ?? {}) as JsonObject),
			references: () => undefined,
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

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor'));
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
		this.summary = undefined;
		if (!this.document) {
			return;
		}
		append(this.container, $('h2', undefined, localize('grids.title', "Grids & Stories")));
		append(this.container, $('p.building-intro', undefined, localize('grids.intro', "Grid lines and stories of the floor plan. Columns, beams, walls, slabs and footings are placed on them in the Floor Plan; the building model is generated from it.")));
		this.problemBox = append(this.container, $('.library-problems'));
		this.renderProblems();
		this.summary = append(this.container, $('.building-summary'));
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
	}

	/** Spacings and story heights, derived from positions and elevations. */
	private renderSummary(): void {
		const box = this.summary;
		if (!box) {
			return;
		}
		clearNode(box);
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
			const entry = append(box, $('div'));
			append(entry, $('span.summary-label', undefined, label));
			append(entry, $('span', undefined, value));
		};
		item(localize('building.xSpacing', "X spacing (mm)"), spacings(this.grids.x));
		item(localize('building.ySpacing', "Y spacing (mm)"), spacings(this.grids.y));
		item(localize('building.storyHeights', "Story heights (mm)"), heights);
		item(localize('building.members', "Placed members"), String(members));
	}
}
