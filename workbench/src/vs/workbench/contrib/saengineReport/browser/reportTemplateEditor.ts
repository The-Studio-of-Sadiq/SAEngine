/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
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
import { DEFAULT_REPORT_TEMPLATE, REPORT_TEMPLATE_SCHEMA } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from '../../saengineLibrary/browser/jsonDocumentEditor.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from '../../saengineLibrary/browser/schemaForm.js';
import { EXPORT_WORD_REPORT_COMMAND_ID, PRINT_REPORT_COMMAND_ID, USE_REPORT_TEMPLATE_COMMAND_ID } from './reportBuild.js';

const REPORT_TEMPLATE_SCHEMA_ID = 'saengine.reportTemplate/1';

/** The section ids in their default order, from the schema (`saengine.library.report_template.SECTIONS`). */
function sectionIds(): readonly string[] {
	const def = REPORT_TEMPLATE_SCHEMA.$defs?.ReportSection?.properties?.id;
	return Array.isArray(def?.enum) ? def.enum.map(String) : [];
}

/** The templates of the template's groups, for "Add" in the form. */
function groupTemplate(defName: string): JsonObject {
	const defaults = DEFAULT_REPORT_TEMPLATE as JsonObject;
	switch (defName) {
		case 'Cover': return clone(defaults.cover as JsonObject);
		case 'Letterhead': return clone(defaults.letterhead as JsonObject);
		case 'MemberSelection': return clone(defaults.members as JsonObject);
		case 'ReportSection': return { id: sectionIds()[0] ?? 'basis', include: true, detail: 'inherit' };
		default: return {};
	}
}

/**
 * A report template (`11 Exports/report-templates/<id>.json`) as a form, in the shared editor
 * frame: the sections of the design report in the order they print, the detail of each, the
 * cover, the letterhead and the members printed. The frame prints the report with it, as PDF or
 * Word, and makes it the one the project prints (Project Settings → Design report → Template).
 */
export class ReportTemplateEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.REPORT_TEMPLATE_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	private readonly form: SchemaForm;
	private readonly printAction = this._register(new Action('saengine.reportTemplate.print', localize('reportTemplate.print', "Print PDF"), ThemeIcon.asClassName(Codicon.filePdf), true, async () => this.print(PRINT_REPORT_COMMAND_ID)));
	private readonly wordAction = this._register(new Action('saengine.reportTemplate.word', localize('reportTemplate.word', "Export Word"), ThemeIcon.asClassName(Codicon.fileText), true, async () => this.print(EXPORT_WORD_REPORT_COMMAND_ID)));
	private readonly useAction = this._register(new Action('saengine.reportTemplate.use', localize('reportTemplate.use', "Print This Template for the Project"), ThemeIcon.asClassName(Codicon.check), true, async () => this.use()));

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
		super(ReportTemplateEditor.ID, group, telemetryService, themeService, storageService, commands, editors, textModelService, project);
		this.trackDeveloperMode(configurationService);
		this.form = instantiation.createInstance(SchemaForm, {
			root: REPORT_TEMPLATE_SCHEMA,
			template: defName => groupTemplate(defName),
			references: () => undefined,
			validate: (path, value) => path === 'id' && value !== this.fileId ? localize('reportTemplate.idMismatch', "The id is the file's name: {0}.", this.fileId ?? '') : undefined,
			changed: (_path, structural) => {
				this.changed(structural);
				this.renderProblems();
			},
			mode: () => undefined,
			newItem: (path, list) => this.newItem(path, list),
		});
		this._register({ dispose: () => this.form.dispose() });
	}

	/** The template's id: the file's name without `.json`. */
	private get fileId(): string | undefined {
		return this.resource ? basename(this.resource).replace(/\.json$/i, '') : undefined;
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		const frame = this._register(this.instantiation.createInstance(EditorFrame, parent, {
			id: ReportTemplateEditor.ID,
			ariaLabel: localize('reportTemplate.toolbar', "Report Template"),
		}));
		frame.setTitle(localize('reportTemplate.title', "Report Template"));
		frame.setHelp(localize('reportTemplate.help', "What the design report prints: its sections in order, summary or full calculations, the cover, the letterhead and the members. The PDF and the Word file follow the same template. Project Settings → Design report → Template says which template the project prints (Run All and Print Design Report)."));
		return frame;
	}

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor.report-template-editor'));
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		return { primary: this.document ? [this.printAction, this.wordAction] : [], secondary: this.document ? [this.useAction] : [] };
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === REPORT_TEMPLATE_SCHEMA_ID) {
			return undefined;
		}
		return {
			message: localize('reportTemplate.unexpected', "This file is not a SAEngine report template ({0}).", REPORT_TEMPLATE_SCHEMA_ID),
			fix: {
				label: localize('reportTemplate.create', "Start a New Report Template"),
				run: () => this.replaceDocument({ ...clone(DEFAULT_REPORT_TEMPLATE as JsonObject), id: this.fileId ?? 'default', name: this.fileId ?? 'Report' }),
			},
		};
	}

	/** The next section not in the list yet. */
	private newItem(path: string, list: readonly JsonValue[]): JsonObject | undefined {
		if (path !== 'sections') {
			return undefined;
		}
		const used = new Set(list.filter(isObject).map(s => String(s.id)));
		const id = sectionIds().find(s => !used.has(s));
		return id ? { id, include: true, detail: 'inherit' } : undefined;
	}

	private async print(command: string): Promise<void> {
		this.flush();
		// The template file is read from disk: save the edits first.
		const input = this.input as LibraryEditorInput | undefined;
		if (input?.isDirty()) {
			await input.save(this.group.id);
		}
		await this.commands.executeCommand(command, { template: this.fileId });
	}

	private async use(): Promise<void> {
		await this.commands.executeCommand(USE_REPORT_TEMPLATE_COMMAND_ID, { template: this.fileId });
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
		this.form.render(append(this.container, $('.library-form')), REPORT_TEMPLATE_SCHEMA, this.document);
	}

	protected renderProblems(): void {
		const document = this.document;
		if (document) {
			const sections = Array.isArray(document.sections) ? document.sections.filter(isObject) : [];
			const printed = sections.filter(s => s.include !== false).length;
			const detail = document.detail === 'summary' ? localize('reportTemplate.summary', "summary") : localize('reportTemplate.full', "full calculations");
			this.documentFrame?.setStatus(this.problems.length
				? { severity: 'warning', text: localize('reportTemplate.statusProblems', "{0} problem(s): see the list above the form", this.problems.length) }
				: { text: localize('reportTemplate.status', "{0} of {1} sections printed, {2}", printed, sectionIds().length, detail) });
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
}
