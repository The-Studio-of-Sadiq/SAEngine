/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import './media/worksheetEditor.css';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { basename } from '../../../../base/common/resources.js';
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
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from '../../saengineLibrary/browser/jsonDocumentEditor.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { JsonObject } from '../../saengineLibrary/browser/schemaForm.js';
import { PRINT_REPORT_COMMAND_ID } from './reportBuild.js';
import { IWorksheetInput, IWorksheetKind, IWorksheetResult, parseInput, WORKSHEET_SCHEMA_ID, WORKSHEETS_REQUEST_COMMAND_ID } from './worksheetModel.js';

/** The kinds, asked of the backend once per window. */
let kindsPromise: Promise<readonly IWorksheetKind[]> | undefined;

export function worksheetKinds(commands: ICommandService): Promise<readonly IWorksheetKind[]> {
	if (!kindsPromise) {
		kindsPromise = commands.executeCommand<{ kinds?: IWorksheetKind[] }>(WORKSHEETS_REQUEST_COMMAND_ID, 'worksheets/kinds', {})
			.then(answer => answer?.kinds ?? []);
		kindsPromise.catch(() => kindsPromise = undefined);
	}
	return kindsPromise;
}

/**
 * A calculation worksheet (`11 Exports/worksheets/<id>.json`) in the shared editor frame: the
 * inputs of its kind on the left and the calculation on the right, made again by the backend
 * with SAEngine's design functions on every change (each step with its formula and clause,
 * then the checks). Its heading, reference and notes are what the design report prints.
 */
export class WorksheetEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.WORKSHEET_EDITOR_ID;

	private container!: HTMLElement;
	private resultBox: HTMLElement | undefined;
	private problemBox: HTMLElement | undefined;
	private sheetKind: IWorksheetKind | undefined;
	private kinds: readonly IWorksheetKind[] = [];
	private result: IWorksheetResult | undefined;
	private calculation = 0;
	private readonly recalculate = this._register(new RunOnceScheduler(() => this.calculate(), 250));
	private readonly printAction = this._register(new Action('saengine.worksheet.print', localize('worksheet.print', "Print Design Report"), ThemeIcon.asClassName(Codicon.filePdf), true, async () => this.print()));
	private readonly resetAction = this._register(new Action('saengine.worksheet.reset', localize('worksheet.reset', "Reset Inputs to the Defaults"), ThemeIcon.asClassName(Codicon.discard), true, async () => this.reset()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiation: IInstantiationService,
		@ICommandService private readonly commands: ICommandService,
		@IEditorService editors: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService project: ISaengineProjectService,
		@IConfigurationService configurationService: IConfigurationService,
	) {
		super(WorksheetEditor.ID, group, telemetryService, themeService, storageService, commands, editors, textModelService, project);
		this.trackDeveloperMode(configurationService);
	}

	private get fileId(): string | undefined {
		return this.resource ? basename(this.resource).replace(/\.json$/i, '') : undefined;
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		const frame = this._register(this.instantiation.createInstance(EditorFrame, parent, {
			id: WorksheetEditor.ID,
			ariaLabel: localize('worksheet.toolbar', "Calculation Worksheet"),
		}));
		frame.setTitle(localize('worksheet.title', "Calculation Worksheet"));
		frame.setHelp(localize('worksheet.help', "A hand calculation made with SAEngine's own design functions and the project's code pack: enter the values on the left, the calculation follows on the right with the formula and clause of every step. A worksheet marked to print goes into the design report's Calculation worksheets section."));
		return frame;
	}

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor.saengine-worksheet-editor'));
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		return { primary: this.document ? [this.printAction] : [], secondary: this.document ? [this.resetAction] : [] };
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === WORKSHEET_SCHEMA_ID) {
			return undefined;
		}
		return { message: localize('worksheet.unexpected', "This file is not a SAEngine calculation worksheet ({0}).", WORKSHEET_SCHEMA_ID) };
	}

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.container);
		this.problemBox = undefined;
		this.resultBox = undefined;
		const document = this.document;
		if (!document) {
			return;
		}
		this.problemBox = append(this.container, $('.library-problems'));
		const layout = append(this.container, $('.sa-worksheet-layout'));
		const form = append(layout, $('.sa-worksheet-inputs'));
		this.resultBox = append(layout, $('.sa-worksheet-result'));
		append(this.resultBox, $('.sa-worksheet-muted', undefined, localize('worksheet.loading', "Calculating...")));
		this.renderProblems();
		worksheetKinds(this.commands).then(kinds => {
			if (this.document !== document) {
				return;
			}
			this.kinds = kinds;
			this.sheetKind = kinds.find(k => k.id === document.kind);
			this.renderForm(form, document);
			this.calculate();
		}, error => {
			clearNode(this.resultBox!);
			append(this.resultBox!, $('.sa-worksheet-fail', undefined, localize('worksheet.noBackend', "The calculation needs the SAEngine backend (Python): {0}", toErrorMessage(error))));
		});
	}

	private renderForm(form: HTMLElement, document: JsonObject): void {
		clearNode(form);
		const kind = this.sheetKind;
		const head = append(form, $('.sa-worksheet-group'));
		this.textField(head, localize('worksheet.heading', "Title"), 'title', document);
		this.textField(head, localize('worksheet.reference', "Reference (member, grid, drawing)"), 'reference', document);
		const printRow = append(head, $('label.sa-worksheet-check'));
		const print = append(printRow, $<HTMLInputElement>('input', { type: 'checkbox' }));
		print.checked = document.print !== false;
		append(printRow, $('span', undefined, localize('worksheet.printIt', "Print in the design report")));
		this.viewDisposables.add(addDisposableListener(print, EventType.CHANGE, () => {
			document.print = print.checked;
			this.changed(false);
			this.renderProblems();
		}));
		if (!kind) {
			append(form, $('.sa-worksheet-fail', undefined, localize('worksheet.unknownKind', "Unknown worksheet kind \"{0}\". Known kinds: {1}.", String(document.kind), this.kinds.map(k => k.id).join(', '))));
			return;
		}
		append(head, $('.sa-worksheet-muted', undefined, `${kind.title}: ${kind.summary}`));
		const inputs = isObject(document.inputs) ? document.inputs : (document.inputs = {});
		const groups = new Map<string, IWorksheetInput[]>();
		for (const input of kind.inputs) {
			const list = groups.get(input.group) ?? [];
			list.push(input);
			groups.set(input.group, list);
		}
		for (const [group, list] of groups) {
			const box = append(form, $('.sa-worksheet-group'));
			if (group) {
				append(box, $('.sa-worksheet-group-title', undefined, group));
			}
			for (const input of list) {
				this.inputField(box, input, inputs);
			}
		}
		const notes = append(form, $('.sa-worksheet-group'));
		append(notes, $('.sa-worksheet-group-title', undefined, localize('worksheet.notes', "Notes (printed under the calculation)")));
		const area = append(notes, $<HTMLTextAreaElement>('textarea.sa-worksheet-notes'));
		area.value = typeof document.notes === 'string' ? document.notes : '';
		this.viewDisposables.add(addDisposableListener(area, EventType.INPUT, () => {
			document.notes = area.value;
			this.changed(false);
		}));
	}

	private textField(parent: HTMLElement, label: string, key: string, document: JsonObject): void {
		const row = append(parent, $('label.sa-worksheet-field.sa-worksheet-wide'));
		append(row, $('span.sa-worksheet-label', undefined, label));
		const field = append(row, $<HTMLInputElement>('input', { type: 'text' }));
		field.value = typeof document[key] === 'string' ? String(document[key]) : '';
		this.viewDisposables.add(addDisposableListener(field, EventType.INPUT, () => {
			document[key] = key === 'title' && !field.value.trim() ? (this.sheetKind?.title ?? this.fileId ?? '') : field.value;
			this.changed(false);
		}));
	}

	private inputField(parent: HTMLElement, input: IWorksheetInput, inputs: JsonObject): void {
		const row = append(parent, $('label.sa-worksheet-field'));
		row.title = input.help;
		const stored = inputs[input.name];
		const current = stored === undefined ? input.default : stored;
		if (input.kind === 'bool') {
			row.classList.add('sa-worksheet-check');
			const box = append(row, $<HTMLInputElement>('input', { type: 'checkbox' }));
			box.checked = Boolean(current);
			append(row, $('span', undefined, input.label));
			this.viewDisposables.add(addDisposableListener(box, EventType.CHANGE, () => this.setInput(input, inputs, box.checked, box)));
			return;
		}
		append(row, $('span.sa-worksheet-label', undefined, input.label));
		if (input.kind === 'choice') {
			const select = append(row, $<HTMLSelectElement>('select'));
			for (const option of input.choices ?? []) {
				const element = append(select, $<HTMLOptionElement>('option', { value: option.value }, option.label));
				element.selected = option.value === String(current);
			}
			this.viewDisposables.add(addDisposableListener(select, EventType.CHANGE, () => this.setInput(input, inputs, select.value, select)));
		} else {
			const field = append(row, $<HTMLInputElement>('input', { type: 'text', inputmode: 'decimal' }));
			field.value = String(current);
			this.viewDisposables.add(addDisposableListener(field, EventType.INPUT, () => this.setInput(input, inputs, field.value, field)));
		}
		append(row, $('span.sa-worksheet-unit', undefined, input.unit));
	}

	private setInput(input: IWorksheetInput, inputs: JsonObject, text: string | boolean, element: HTMLElement): void {
		const value = parseInput(input, text);
		element.classList.toggle('sa-worksheet-invalid', value === undefined);
		if (value === undefined) {
			return;
		}
		inputs[input.name] = value;
		this.changed(false);
		this.recalculate.schedule();
	}

	private async calculate(): Promise<void> {
		const document = this.document;
		if (!document || !this.sheetKind) {
			return;
		}
		const version = ++this.calculation;
		let result: IWorksheetResult | undefined;
		try {
			result = await this.commands.executeCommand<IWorksheetResult>(WORKSHEETS_REQUEST_COMMAND_ID, 'worksheets/calculate', {
				kind: this.sheetKind.id,
				inputs: isObject(document.inputs) ? document.inputs : {},
				projectRoot: this.projectService.project?.root.fsPath,
			});
		} catch (error) {
			result = { kind: this.sheetKind.id, problems: [toErrorMessage(error)] };
		}
		if (version !== this.calculation || this.document !== document) {
			return;
		}
		this.result = result;
		this.renderResult();
		this.renderProblems();
	}

	private renderResult(): void {
		const box = this.resultBox;
		const result = this.result;
		if (!box || !result) {
			return;
		}
		clearNode(box);
		if (result.problems?.length) {
			const fail = append(box, $('.sa-worksheet-fail'));
			append(fail, $('strong', undefined, localize('worksheet.notCalculated', "Not calculated: ")));
			append(fail, $('span', undefined, result.problems.join('; ')));
		}
		const steps = result.steps ?? [];
		if (steps.length) {
			append(box, $('.sa-worksheet-group-title', undefined, localize('worksheet.calculation', "Calculation")));
			const table = append(box, $('table.sa-worksheet-table'));
			for (const step of steps) {
				const row = append(table, $('tr'));
				if (step.heading) {
					append(row, $('th', { colspan: '4' }, step.heading));
					continue;
				}
				append(row, $('td.sa-worksheet-quantity', undefined, step.label ?? ''));
				const expression = append(row, $('td.sa-worksheet-expression'));
				append(expression, $('span', undefined, step.formula ?? ''));
				if (step.clause) {
					append(expression, $('span.sa-worksheet-clause', undefined, step.clause));
				}
				append(row, $('td.sa-worksheet-value', undefined, step.value ?? ''));
				append(row, $('td.sa-worksheet-unit', undefined, step.unit ?? ''));
			}
		}
		const checks = result.checks ?? [];
		if (checks.length) {
			append(box, $('.sa-worksheet-group-title', undefined, localize('worksheet.checks', "Checks")));
			const table = append(box, $('table.sa-worksheet-table.sa-worksheet-checks'));
			for (const check of checks) {
				const row = append(table, $('tr'));
				row.classList.add(check.ok ? 'ok' : 'fail');
				const label = append(row, $('td.sa-worksheet-quantity'));
				append(label, $('span', undefined, check.label));
				if (check.clause) {
					append(label, $('span.sa-worksheet-clause', undefined, check.clause));
				}
				append(row, $('td.sa-worksheet-value', undefined, `${check.demand} ${check.sense} ${check.capacity} ${check.unit}`.trim()));
				append(row, $('td.sa-worksheet-value', undefined, check.utilisation === null ? '–' : check.utilisation.toFixed(2)));
				append(row, $('td.sa-worksheet-verdict', undefined, check.ok ? localize('worksheet.ok', "OK") : localize('worksheet.fails', "Fails")));
			}
		}
		const notes = result.notes ?? [];
		if (notes.length) {
			const list = append(box, $('ul.sa-worksheet-notes-list'));
			for (const text of notes) {
				append(list, $('li', undefined, text));
			}
		}
		if (result.references?.length) {
			append(box, $('.sa-worksheet-muted', undefined, localize('worksheet.references', "References: {0}", result.references.join('; '))));
		}
	}

	protected renderProblems(): void {
		const result = this.result;
		const document = this.document;
		if (document && result) {
			const checks = result.checks ?? [];
			const failing = checks.filter(c => !c.ok).length;
			const printed = document.print !== false ? localize('worksheet.printed', "printed in the report") : localize('worksheet.notPrinted', "not printed");
			this.documentFrame?.setStatus(result.problems?.length
				? { severity: 'warning', text: localize('worksheet.statusProblem', "Not calculated: {0}", result.problems[0]) }
				: failing
					? { severity: 'warning', text: localize('worksheet.statusFail', "{0} of {1} checks fail · {2}", failing, checks.length, printed) }
					: { text: localize('worksheet.statusOk', "{0} checks pass · utilisation {1} · {2}", checks.length, typeof result.utilisation === 'number' ? result.utilisation.toFixed(2) : '–', printed) });
		}
		const box = this.problemBox;
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

	private reset(): void {
		if (!this.document || !this.sheetKind) {
			return;
		}
		const inputs: JsonObject = {};
		for (const input of this.sheetKind.inputs) {
			inputs[input.name] = input.default;
		}
		this.replaceDocument({ ...this.document, inputs });
	}

	private async print(): Promise<void> {
		this.flush();
		const input = this.input as LibraryEditorInput | undefined;
		if (input?.isDirty()) {
			await input.save(this.group.id);
		}
		await this.commands.executeCommand(PRINT_REPORT_COMMAND_ID);
	}
}
