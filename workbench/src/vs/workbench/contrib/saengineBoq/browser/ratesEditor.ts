/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import { $, append, clearNode } from '../../../../base/browser/dom.js';
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
import { CARBON_SCHEMA, RATES_SCHEMA } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from '../../saengineLibrary/browser/jsonDocumentEditor.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from '../../saengineLibrary/browser/schemaForm.js';

const RATES_SCHEMA_ID = 'saengine.rates/1';
const CARBON_SCHEMA_ID = 'saengine.carbon/1';
/** The units a rate may be quoted in (`saengine.boq.costing.UNITS`). */
export const RATE_UNITS: readonly string[] = ['m3', 'cum', 'cft', 'm2', 'sqm', 'sft', 'm', 'rm', 'rft', 'kg', 't', 'quintal', 'nr', 'each', 'bag', 'l'];

/**
 * The schedule of rates (`10 BOQ/rates.json`) or the embodied carbon factors
 * (`10 BOQ/carbon-factors.json`) of the bill of quantities as a form, in the shared editor frame
 * (as the report templates): the schedule's name, currency and edition, its chapters and its
 * items (item number, description, unit, rate and the bill items each prices), or the carbon
 * factors with their sources. The Python models (`saengine.boq.costing`) check it as it is typed.
 */
export class RatesEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.RATES_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	/** One form per schema (the schema's `$defs` are the form's root). */
	private readonly ratesForm: SchemaForm;
	private readonly carbonForm: SchemaForm;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiation: IInstantiationService,
		@ICommandService commands: ICommandService,
		@IEditorService editors: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService project: ISaengineProjectService,
		@IConfigurationService configurationService: IConfigurationService,
	) {
		super(RatesEditor.ID, group, telemetryService, themeService, storageService, commands, editors, textModelService, project);
		this.trackDeveloperMode(configurationService);
		const form = (root: typeof RATES_SCHEMA) => instantiation.createInstance(SchemaForm, {
			root,
			template: defName => this.template(defName),
			references: path => path === 'items.unit' ? RATE_UNITS : undefined,
			validate: () => undefined,
			changed: (_path, structural) => {
				this.changed(structural);
				this.renderProblems();
			},
			mode: () => undefined,
			newItem: (path, list) => this.newItem(path, list),
		});
		this.ratesForm = form(RATES_SCHEMA);
		this.carbonForm = form(CARBON_SCHEMA);
		this._register({ dispose: () => { this.ratesForm.dispose(); this.carbonForm.dispose(); } });
	}

	private get carbon(): boolean {
		return this.kind === 'carbon';
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		return this._register(this.instantiation.createInstance(EditorFrame, parent, {
			id: RatesEditor.ID,
			ariaLabel: localize('rates.toolbar', "Schedule of Rates"),
		}));
	}

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor.rates-editor'));
	}

	protected override onWillLoadInput(): void {
		const frame = this.documentFrame;
		if (this.carbon) {
			frame?.setTitle(localize('carbon.title', "Embodied Carbon Factors"));
			frame?.setHelp(localize('carbon.help', "kg CO2e per kg of each material of the bill (cement, sand, stone, reinforcement, structural steel, brick work), each with its source. A factor applies to the bill items its 'Applies to' names; an empty factor is not counted."));
		} else {
			frame?.setTitle(localize('rates.title', "Schedule of Rates"));
			frame?.setHelp(localize('rates.help', "The rates the bill of quantities is priced with: chapters and items as a schedule of rates lays them out (item number, description, unit, rate). Each item prices the bill items its 'Applies to' names (group, element kind, material, bar diameters, a description pattern); the first item that matches a bill item prices it. Units: m3 (cum), cft, m2 (sqm), sft, m (rm), rft, kg, t, quintal, nr (each), bag, l."));
		}
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		return { primary: [] };
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		const expected = this.carbon ? CARBON_SCHEMA_ID : RATES_SCHEMA_ID;
		if (value.schema === expected) {
			return undefined;
		}
		return {
			message: this.carbon
				? localize('carbon.unexpected', "This file is not a SAEngine carbon factors file ({0}).", expected)
				: localize('rates.unexpected', "This file is not a SAEngine schedule of rates ({0}).", expected),
		};
	}

	/** A new item, chapter or factor: the next item number of the chapter above, a common unit. */
	private template(defName: string): JsonObject {
		switch (defName) {
			case 'RateItem': return { code: '', description: '', unit: 'm3', rate: null, match: {} };
			case 'Chapter': return { code: '', title: '' };
			case 'CarbonFactor': return { id: '', material: '', factor: null, match: {}, source: '' };
			default: return {};
		}
	}

	private newItem(path: string, list: readonly JsonValue[]): JsonObject | undefined {
		if (path !== 'items') {
			return undefined;
		}
		const last = [...list].reverse().find(isObject);
		const code = typeof last?.code === 'string' ? nextCode(last.code) : '';
		return { code, description: '', unit: typeof last?.unit === 'string' ? last.unit : 'm3', rate: null, match: {} };
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
		const [form, schema] = this.carbon ? [this.carbonForm, CARBON_SCHEMA] : [this.ratesForm, RATES_SCHEMA];
		form.render(append(this.container, $('.library-form')), schema, this.document);
	}

	protected renderProblems(): void {
		const document = this.document;
		if (document) {
			const entries = Array.isArray(this.carbon ? document.factors : document.items) ? (this.carbon ? document.factors : document.items) as JsonValue[] : [];
			const valued = entries.filter(isObject).filter(e => typeof (this.carbon ? e.factor : e.rate) === 'number').length;
			this.documentFrame?.setStatus(this.problems.length
				? { severity: 'warning', text: localize('rates.statusProblems', "{0} problem(s): see the list above the form", this.problems.length) }
				: { text: this.carbon
					? localize('carbon.status', "{0} factors, {1} with a value", entries.length, valued)
					: localize('rates.status', "{0} items, {1} rated ({2})", entries.length, valued, typeof document.currency === 'string' ? document.currency : '') });
		}
		const box = this.problemBox;
		if (!box) {
			return;
		}
		clearNode(box);
		box.classList.toggle('visible', this.problems.length > 0);
		const entries = this.document && Array.isArray(this.carbon ? this.document.factors : this.document.items) ? (this.carbon ? this.document.factors : this.document.items) as JsonValue[] : [];
		for (const problem of this.problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			const entry = problem.index !== null ? entries[problem.index] : undefined;
			const where = isObject(entry) ? String(entry.code ?? entry.id ?? problem.index) : undefined;
			const path = [where, problem.path].filter(Boolean).join('.');
			append(row, $('span', undefined, path ? `${path}: ${problem.message}` : problem.message));
		}
	}
}

/** The item number after `code`: its last number part plus one ("03.02" -> "03.03"). */
export function nextCode(code: string): string {
	const match = /^(.*?)(\d+)(\D*)$/.exec(code);
	if (!match) {
		return code;
	}
	const [, head, digits, tail] = match;
	return `${head}${String(Number(digits) + 1).padStart(digits.length, '0')}${tail}`;
}
